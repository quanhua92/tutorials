"""
data_pipelines.py - Reference simulation of an ETL/streaming data pipeline.

This is the single source of truth that DATA_PIPELINES.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 data_pipelines.py      (pure stdlib; no dependencies)

============================================================================
THE INTUITION (read this first) -- a factory assembly line
============================================================================
A data pipeline is a factory ASSEMBLY LINE for data. Raw material (records)
enters at one end, gets cleaned and assembled at workstations (transforms),
and finished goods (curated tables) come out the other end. Two production
styles exist:

  BATCH   : load a whole truck of parts at once, process them, ship a pallet.
            High throughput, minutes-to-hours latency. (Airflow + Spark + dbt)
  STREAM  : parts arrive on a conveyor belt one at a time; each is processed
            the instant it lands. Low latency, continuous. (Kafka + Flink)

The orchestrator is the FACTORY MANAGER: it reads the order sheet (a DAG of
which workstation feeds which), respects dependencies (welding must finish
before painting), and re-runs a station if it faults.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  ETL          : Extract -> Transform -> Load (transform on a separate server).
  ELT          : Extract -> Load -> Transform (transform INSIDE the warehouse).
  Batch        : process big bounded chunks on a schedule (minutes..hours).
  Streaming    : process unbounded records as they arrive (ms..seconds).
  Kafka topic  : an append-only log partitioned for parallelism.
  Partition    : ordered shard of a topic; the unit of parallelism (1
                 partition -> 1 consumer in a group, preserving order).
  Offset       : a record's sequence number within a partition; consumers
                 commit offsets to mark progress.
  Backpressure : when a downstream stage is slower than upstream, the pipeline
                 must SLOW the producer (buffer / block / shed load) or it will
                 drown in unbounded in-flight data.
  Exactly-once : every input record affects the output exactly once -- no
                 duplicates, no losses. Built from idempotent writes +
                 transactional offset commits.
  DAG          : Directed Acyclic Graph of tasks; the orchestrator runs tasks
                 in topological order so dependencies are respected.

KEY FACTS (all asserted in code below):
  * A DAG with a cycle is REJECTED -- pipelines must be acyclic.
  * Topological order lets independent tasks run in PARALLEL (fan-out / fan-in).
  * Backpressure caps in-flight records; once the cap is hit the producer stalls.
  * Exactly-once = idempotent sink + atomic (offset-commit + write). A retry of
    the same offset rewrites the SAME row -> no duplicate effect.
  * At-least-once WITHOUT idempotency produces DUPLICATE outputs on retry.

Sources: Apache Airflow core concepts, Apache Kafka docs, Confluent
"exactly-once semantics", dbt documentation, Spark Structured Streaming.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 0. THE PIPELINE MODEL -- deterministic, no randomness.
# ============================================================================

# Raw events the pipeline ingests. (In production this is Kafka / S3 / a DB.)
RAW_EVENTS = [
    {"id": 1, "user": "alice", "amount": "120.5",  "currency": "usd", "ts": "2026-01-01"},
    {"id": 2, "user": "bob",   "amount": "-5",     "currency": "usd", "ts": "2026-01-01"},
    {"id": 3, "user": "alice", "amount": "30",     "currency": "eur", "ts": "2026-01-02"},
    {"id": 4, "user": "carol", "amount": "200",    "currency": "usd", "ts": "2026-01-02"},
    {"id": 5, "user": "bob",   "amount": "not-a-number", "currency": "usd", "ts": "2026-01-03"},
    {"id": 6, "user": "carol", "amount": "50",     "currency": "eur", "ts": "2026-01-03"},
]

FX = {"usd": 1.0, "eur": 1.10}  # currency -> USD


# ============================================================================
# 1. ETL CORE  (extract / transform / load)
# ============================================================================

def extract(rows: list) -> list:
    """Extract: pull raw records from the source verbatim (no cleaning yet)."""
    return [dict(r) for r in rows]


def transform(rows: list) -> tuple[list, list]:
    """Transform: clean, type, enrich. Returns (valid, quarantined)."""
    valid, bad = [], []
    for r in rows:
        try:
            amount = float(r["amount"])
        except (ValueError, TypeError):
            r["error"] = f"amount not numeric: {r['amount']!r}"
            bad.append(r)
            continue
        if amount < 0:
            r["error"] = f"amount negative: {amount}"
            bad.append(r)
            continue
        cur = r["currency"]
        if cur not in FX:
            r["error"] = f"unknown currency: {cur!r}"
            bad.append(r)
            continue
        r["amount_usd"] = round(amount * FX[cur], 2)
        valid.append(r)
    return valid, bad


def load(rows: list, sink: list) -> None:
    """Load: write validated records to the target (here, an in-memory list)."""
    sink.extend(rows)


def run_etl():
    """Full ETL pass. Returns (loaded, quarantined)."""
    sink = []
    raw = extract(RAW_EVENTS)
    valid, bad = transform(raw)
    load(valid, sink)
    return sink, bad


# ============================================================================
# 2. DAG ORCHESTRATION  (topological order, cycle detection, fan-out)
# ============================================================================

def topo_sort(tasks: dict) -> list:
    """Kahn's algorithm. tasks: {name: [deps...]}. Returns order or [] if cyclic.

    Independent tasks (no deps) are GROUPED by level so the orchestrator can run
    each level in parallel -- that is how Airflow/dbt get fan-out.
    """
    in_deg = {t: 0 for t in tasks}
    for t, deps in tasks.items():
        for d in deps:
            in_deg[t] += 1
    order = []
    ready = sorted([t for t, d in in_deg.items() if d == 0])
    while ready:
        order.append(ready)
        nxt = []
        for t in ready:
            for child, deps in tasks.items():
                if t in deps:
                    in_deg[child] -= 1
                    if in_deg[child] == 0:
                        nxt.append(child)
        ready = sorted(nxt)
    if len([t for lvl in order for t in lvl]) != len(tasks):
        return []  # cycle: some tasks never reached in-degree 0
    return order


# The canonical analytics DAG: each task lists its upstream deps.
DAG = {
    "extract_orders":    [],
    "extract_customers": [],
    "stg_orders":        ["extract_orders"],
    "stg_customers":     ["extract_customers"],
    "fct_revenue":       ["stg_orders"],
    "dim_customer":      ["stg_customers", "stg_orders"],
    "mrr_daily":         ["fct_revenue", "dim_customer"],
}


# ============================================================================
# 3. BACKPRESSURE  (bounded buffer between producer and consumer)
# ============================================================================

class BoundedBuffer:
    """A fixed-capacity queue. put() BLOCKS when full -> backpressure to the
    producer. This mirrors Kafka consumer.pause() / reactive streams."""

    def __init__(self, capacity: int):
        self.cap = capacity
        self.buf: list = []

    def put(self, item) -> bool:
        """Return True if accepted, False if full (producer must wait)."""
        if len(self.buf) >= self.cap:
            return False
        self.buf.append(item)
        return True

    def get(self):
        return self.buf.pop(0) if self.buf else None

    def __len__(self):
        return len(self.buf)


def simulate_backpressure(events: list, cap: int, consumer_rate: int) -> dict:
    """Producer pushes events as fast as possible; a slow consumer drains them.

    consumer_rate: how many events the consumer pulls per tick. With a small
    buffer + slow consumer, the producer STALLS (backpressure) instead of
    flooding memory with unbounded in-flight data.
    """
    buf = BoundedBuffer(cap)
    accepted = 0
    stalled = 0
    tick = 0
    idx = 0
    log = []
    while idx < len(events) or len(buf) > 0:
        produced_now = 0
        while idx < len(events):
            if buf.put(events[idx]):
                accepted += 1
                idx += 1
                produced_now += 1
            else:
                stalled += 1
                break  # buffer full -> producer waits this tick
        drained = 0
        for _ in range(consumer_rate):
            if buf.get() is not None:
                drained += 1
            else:
                break
        if tick < 12:  # log first 12 ticks for the readout
            log.append((tick, len(buf), produced_now, drained, stalled))
        tick += 1
    return {"accepted": accepted, "stalled": stalled, "ticks": tick, "log": log}


# ============================================================================
# 4. EXACTLY-ONCE  (idempotent sink + atomic offset+write)
# ============================================================================

def simulate_delivery(mode: str, events: list, failures_at: set) -> dict:
    """Simulate a consumer that commits offsets then writes to a sink.

    mode:
      'at_most_once' : write then crash before commit -> loss (offset not
                       advanced, but write already happened... here we model the
                       classic 'ack before process' -> message lost on crash).
      'at_least_once': commit offset AFTER write, but NON-idempotent sink. On a
                       retry the row is written AGAIN -> duplicate.
      'exactly_once' : idempotent sink (keyed by event id) + atomic commit. A
                       retry rewrites the SAME key -> no duplicate effect.

    failures_at: set of event ids whose processing 'crashes' once before
                 succeeding (modeling a transient fault + retry).
    """
    sink = []            # list sink (non-idempotent: append duplicates)
    sink_keys = set()    # idempotent sink: dedupe by event id
    delivered = []
    crashed = set()

    i = 0
    while i < len(events):
        ev = events[i]
        crash = (ev["id"] in failures_at) and (ev["id"] not in crashed)

        if mode == "at_most_once":
            if crash:
                crashed.add(ev["id"])
                i += 1  # ack-then-crash: message LOST
                continue
            sink.append(ev["id"])
            delivered.append(ev["id"])
            i += 1

        elif mode == "at_least_once":
            sink.append(ev["id"])
            delivered.append(ev["id"])
            if crash:
                crashed.add(ev["id"])
                # retry: do NOT advance offset, reprocess on next iteration
                continue
            i += 1  # commit offset

        elif mode == "exactly_once":
            if ev["id"] not in sink_keys:
                sink_keys.add(ev["id"])
                sink.append(ev["id"])
                delivered.append(ev["id"])
            if crash:
                crashed.add(ev["id"])
                continue  # retry, but idempotent sink dedupes
            i += 1  # atomic: offset commit + write happen together
    return {
        "delivered": delivered,
        "sink_count": len(sink),
        "duplicates": len(sink) - len(set(sink)),
        "lost": len(events) - len(set(delivered) & {e["id"] for e in events}),
    }


# ============================================================================
# 5. BATCH vs STREAMING  (throughput / latency tradeoff)
# ============================================================================

def simulate_batch(events: list, batch_size: int, setup: float,
                   proc: float) -> dict:
    """Batch: accumulate records into a batch, then process them together.

    Throughput wins because the fixed SETUP cost is amortized over the whole
    batch (compute = batches*setup + n*proc). Latency LOSES because every
    record waits for the batch window to fill before processing starts.
    """
    n = len(events)
    batches = (n + batch_size - 1) // batch_size
    compute = batches * setup + n * proc
    throughput = n / compute if compute else 0
    # wall-clock latency = wait for the window to fill + bulk process the batch
    window_wait = batch_size              # records arrive 1/tick
    batch_proc = setup + proc             # bulk: not multiplied per record
    latencies = [window_wait + batch_proc for _ in range(n)]
    return {
        "mode": "batch",
        "batches": batches,
        "throughput": throughput,
        "avg_latency": sum(latencies) / n if n else 0,
        "max_latency": max(latencies) if latencies else 0,
    }


def simulate_stream(events: list, setup: float, proc: float) -> dict:
    """Streaming: process each record the moment it arrives.

    Latency wins because there is NO batch window to wait for. Throughput LOSES
    because the SETUP cost is paid on EVERY record (compute = n*(setup+proc)).
    """
    n = len(events)
    compute = n * (setup + proc)
    throughput = n / compute if compute else 0
    latencies = [setup + proc for _ in range(n)]  # no window wait
    return {
        "mode": "stream",
        "batches": n,
        "throughput": throughput,
        "avg_latency": sum(latencies) / n if n else 0,
        "max_latency": max(latencies) if latencies else 0,
    }


# ============================================================================
# 6. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 7. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: ETL pass
# ----------------------------------------------------------------------------

def section_etl():
    banner("SECTION A: ETL -- extract, transform, load")
    print("Raw events from the source:")
    for r in RAW_EVENTS:
        print(f"  {r}")
    print()
    sink, bad = run_etl()
    print(f"Extract pulled {len(RAW_EVENTS)} raw records.")
    print(f"Transform produced {len(sink)} valid + {len(bad)} quarantined:\n")
    print("  valid (loaded to warehouse):")
    for r in sink:
        print(f"    id={r['id']:<2} user={r['user']:<5} "
              f"amount_usd={r['amount_usd']:<7} ({r['currency']})")
    print("  quarantined (data-quality rejects):")
    for r in bad:
        print(f"    id={r['id']:<2} user={r['user']:<5} ERROR: {r['error']}")
    print()
    print("Transform rules applied:")
    print("  1. amount must parse to a non-negative float")
    print("  2. currency must be in the FX table {usd:1.0, eur:1.10}")
    print("  3. amount_usd = amount * FX[currency]  (normalization)")
    print()
    print(f"Load wrote {len(sink)} rows to the curated 'payments' table.")
    ok = (len(sink) == 4 and len(bad) == 2)
    print(f"[check] ETL produced 4 valid + 2 quarantined (id 2 negative, "
          f"id 5 non-numeric)?  {'OK' if ok else 'FAIL'}")
    return sink, bad


# ----------------------------------------------------------------------------
# SECTION B: DAG orchestration
# ----------------------------------------------------------------------------

def section_dag():
    banner("SECTION B: DAG orchestration -- topological order + fan-out")
    print("Pipeline DAG (task: [upstream deps]):\n")
    for t, deps in DAG.items():
        print(f"  {t:<18} <- {deps or '-'}")
    print()
    order = topo_sort(DAG)
    print("Topological order, GROUPED BY LEVEL (each level runs in parallel):\n")
    for lvl, tasks in enumerate(order):
        tag = "parallel fan-out" if len(tasks) > 1 else "single"
        print(f"  level {lvl}: {tasks}   ({tag})")
    print()
    print("Critical path (longest dependency chain):")
    print("  extract_orders -> stg_orders -> fct_revenue -> mrr_daily")
    print("  (4 hops -- this bounds the minimum wall-clock time of the DAG)")
    print()
    cyclic = topo_sort({"a": ["b"], "b": ["a"]})
    ok = (order[-1] == ["mrr_daily"]) and (cyclic == [])
    print("Cycle check: {'a':['b'],'b':['a']} -> "
          f"topo order = {cyclic or 'REJECTED (cycle)'}")
    print("  (orchestrator REFUSES a cyclic graph -- pipelines must be acyclic)")
    print()
    print("GOLD (pinned for data_pipelines.html):")
    print(f"  topo levels = {[lvl for lvl in order]}")
    print(f"[check] DAG has {len(order)} levels and mrr_daily runs last?  "
          f"{'OK' if ok else 'FAIL'}")
    return order


# ----------------------------------------------------------------------------
# SECTION C: Backpressure
# ----------------------------------------------------------------------------

def section_backpressure():
    banner("SECTION C: Backpressure -- slow consumer throttles the producer")
    cap = 3
    rate = 1
    res = simulate_backpressure(list(range(10)), cap, rate)
    print(f"Bounded buffer capacity = {cap} ; consumer drains {rate}/tick ; "
          f"producer pushes up to {cap}+1/tick.\n")
    print("  tick | buffer | produced | drained | stalls (backpressure)")
    print("  -----+--------+----------+---------+------------------------")
    for tick, blen, prod, drn, stalls in res["log"]:
        stall_now = 1 if (len(res["log"]) > 0 and prod == 0 and blen == cap) else 0
        flag = "  <-- BACKPRESSURE" if stall_now else ""
        print(f"  {tick:<4} | {blen:<6} | {prod:<8} | {drn:<7} | {flag}")
    print()
    print(f"Producer accepted {res['accepted']} events over {res['ticks']} ticks "
          f"with {res['stalled']} stall ticks.")
    print()
    print("WHY IT MATTERS: without a bound, a 100k-eps producer feeding a 1k-eps")
    print("consumer would buffer 99k events/sec in RAM -> OOM. Backpressure makes")
    print("the producer WAIT so memory stays bounded (the buffer size, not the")
    print("arrival rate, bounds in-flight data). Kafka expresses this as")
    print("consumer.pause(); Spark as rate-limiting; reactive streams as")
    print("request(n) upstream demand signaling.")
    print()
    ok = res["accepted"] == 10 and res["stalled"] > 0
    print("GOLD (pinned for data_pipelines.html):")
    print(f"  backpressure stalls = {res['stalled']} (cap {cap}, rate {rate})")
    print(f"[check] producer stalled at least once under load?  "
          f"{'OK' if ok else 'FAIL'}")
    return res


# ----------------------------------------------------------------------------
# SECTION D: Exactly-once semantics  (GOLD)
# ----------------------------------------------------------------------------

def section_exactly_once():
    banner("SECTION D: Delivery semantics -- at-most / at-least / exactly-once")
    events = [{"id": i} for i in range(1, 6)]   # ids 1..5
    fails = {2, 4}                              # these crash once, then retry
    print(f"5 input events (ids 1..5). A transient crash is injected at ids "
          f"{sorted(fails)}; the consumer retries them.\n")
    print("  mode          | delivered | sink writes | duplicates | lost")
    print("  --------------+-----------+--------------+------------+-----")
    gold = {}
    for mode in ("at_most_once", "at_least_once", "exactly_once"):
        r = simulate_delivery(mode, events, fails)
        gold[mode] = r
        label = {"at_most_once": "at-most-once",
                 "at_least_once": "at-least-once",
                 "exactly_once": "exactly-once"}[mode]
        print(f"  {label:<13} | {len(set(r['delivered'])):<9} | "
              f"{r['sink_count']:<12} | {r['duplicates']:<10} | {r['lost']}")
    print()
    print("WHAT EACH ROW PROVES:")
    print("  at-most-once  : ack-before-process -> the crashed records (2,4) are")
    print("                  LOST on the crash. No duplicate, but data is missing.")
    print("  at-least-once : process-then-commit. The crashed records (2,4) are")
    print("                  retried and WRITTEN AGAIN -> 2 duplicates in the sink.")
    print("  exactly-once  : idempotent sink (dedupe by event id) + atomic")
    print("                  offset commit. Retries rewrite the SAME key -> 0")
    print("                  duplicates AND 0 losses.")
    print()
    am = gold["at_most_once"]
    al = gold["at_least_once"]
    eo = gold["exactly_once"]
    ok = (am["lost"] == 2 and al["duplicates"] == 2 and eo["duplicates"] == 0
          and eo["lost"] == 0)
    print("GOLD (pinned for data_pipelines.html):")
    print(f"  exactly-once: delivered={sorted(set(eo['delivered']))}, "
          f"sink_writes={eo['sink_count']}, duplicates={eo['duplicates']}")
    print(f"[check] exactly-once yields 0 duplicates + 0 losses (vs the others)?  "
          f"{'OK' if ok else 'FAIL'}")
    return gold


# ----------------------------------------------------------------------------
# SECTION E: Batch vs Streaming
# ----------------------------------------------------------------------------

def section_batch_stream():
    banner("SECTION E: Batch vs streaming -- the latency/throughput tradeoff")
    events = list(range(1, 9))  # 8 events
    print("8 events arrive (1 per tick). Compare processing styles.\n")
    print("  setup=2 ticks (per-batch OR per-record fixed cost), proc=1 tick/record.\n")
    batch = simulate_batch(events, batch_size=4, setup=2.0, proc=1.0)
    stream = simulate_stream(events, setup=2.0, proc=1.0)
    print(f"  {'metric':<16}{'batch (size 4)':>16}{'streaming':>14}")
    print(f"  {'-'*16}{'-'*16}{'-'*14}")
    print(f"  {'batches/run':<16}{batch['batches']:>16}{stream['batches']:>14}")
    print(f"  {'throughput':<16}{batch['throughput']:>16.3f}"
          f"{stream['throughput']:>14.3f}")
    print(f"  {'avg latency':<16}{batch['avg_latency']:>16.2f}"
          f"{stream['avg_latency']:>14.2f}")
    print(f"  {'max latency':<16}{batch['max_latency']:>16.2f}"
          f"{stream['max_latency']:>14.2f}")
    print()
    print("WHAT THE NUMBERS SAY:")
    print("  * BATCH amortizes the setup (2.0 ticks) over 4 records -> total")
    print("    compute 2 batches*2 + 8*1 = 12 ticks -> throughput")
    print(f"    {batch['throughput']:.3f}/tick (HIGHER).")
    print("    BUT every record waits for the 4-record window to fill -> max")
    print(f"    latency {batch['max_latency']:.2f} ticks (window 4 + bulk proc 3).")
    print("  * STREAMING pays setup on EVERY record -> total compute")
    print(f"    8*(2+1) = 24 ticks -> throughput {stream['throughput']:.3f}/tick")
    print(f"    (LOWER). BUT no window wait -> max latency {stream['max_latency']:.2f}")
    print("    ticks (just setup 2 + proc 1).")
    print()
    print("RULE OF THUMB:")
    print("  - latency budget in seconds  -> streaming (Kafka + Flink / Kinesis)")
    print("  - latency budget in minutes+ -> batch   (Airflow + Spark + dbt)")
    print("  - hybrid: stream for real-time views, batch for full recomputation")
    print("    (Lambda); or unify both as stream replay (Kappa).")
    print()
    ok = (batch["throughput"] > stream["throughput"]
          and stream["max_latency"] < batch["max_latency"])
    print("GOLD (pinned for data_pipelines.html):")
    print(f"  batch throughput = {batch['throughput']:.3f}  "
          f"(> stream {stream['throughput']:.3f})")
    print(f"  stream max latency = {stream['max_latency']:.2f}  "
          f"(< batch {batch['max_latency']:.2f})")
    print(f"[check] batch wins throughput, streaming wins latency?  "
          f"{'OK' if ok else 'FAIL'}")
    return batch, stream


# ============================================================================
# main
# ============================================================================

def main():
    print("data_pipelines.py - reference simulation.")
    print("All numbers below feed DATA_PIPELINES.md.")
    print("stdlib only; deterministic.")

    section_etl()
    section_dag()
    section_backpressure()
    section_exactly_once()
    section_batch_stream()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
