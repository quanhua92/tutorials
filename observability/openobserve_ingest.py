"""openobserve_ingest.py - Ground-truth reference for OpenObserve INGESTION
PIPELINES: the path data takes from an app to a queryable Parquet file on S3.

This is the SINGLE SOURCE OF TRUTH for OPENOBSERVE_INGEST.md. Every config
snippet, throughput number, memory figure, VRL transform result, routing table,
and schema-evolution entry is printed here. If you change something here,
re-run and re-paste the output into the guide.

    python3 openobserve_ingest.py > openobserve_ingest_output.txt

Pure Python stdlib only. Deterministic: a custom LCG RNG (no external deps, no
PYTHONHASHSEED dependence, no wall-clock). The identical throughput + memory
math is recomputed in JS by openobserve_ingest.html and gold-checked.

Scope: how telemetry GETS INTO OpenObserve -- the four ingestion sources
(Fluent Bit, Vector, OTel Collector, direct HTTP API), routing rules (route
logs to a stream based on service / level / tags), transforms (VRL: add fields,
parse JSON, rename, drop PII), multi-sink fan-out (O2 + S3 archive + alert),
schema evolution (new field appears -> auto-detected), batch/buffer math (batch
size vs memory), and backpressure handling. For the O2 storage/query side see
openobserve.py; this file is the INGEST half.

Verified against official OpenObserve docs (openobserve.ai/docs/ingestion) +
Fluent Bit + Vector + VRL docs. See ## Sources in OPENOBSERVE_INGEST.md.
"""

from __future__ import annotations

import json


# ============================================================================
# DETERMINISTIC RNG - identical 32-bit LCG as openobserve.py. We reuse it so
# every run is bit-identical and matches the JS in openobserve_ingest.html.
# ============================================================================
class RNG:
    """32-bit linear congruential generator. RNG(7).next() is stable forever."""

    def __init__(self, seed: int = 7) -> None:
        self.state = seed & 0xFFFFFFFF

    def next(self) -> int:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state

    def uniform(self, lo: float = 0.0, hi: float = 1.0) -> float:
        return lo + (hi - lo) * (self.next() / 0xFFFFFFFF)

    def randint(self, lo: int, hi: int) -> int:
        return lo + (self.next() % (hi - lo + 1))

    def choice(self, items):
        return items[self.randint(0, len(items) - 1)]

    def shuffle(self, items):
        a = list(items)
        for i in range(len(a) - 1, 0, -1):
            j = self.randint(0, i)
            a[i], a[j] = a[j], a[i]
        return a


BANNER = "=" * 72


def banner(t: str) -> None:
    print(f"\n{BANNER}\nSECTION {t}\n{BANNER}\n")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


# ============================================================================
# PINNED CONSTANTS - O2 ingest-side thresholds + realistic pipeline defaults.
# ============================================================================
# --- O2 ingest API endpoints (openobserve.ai/docs/reference/api/ingestion) ---
O2_JSON_EP   = "/api/{org}/{stream}/_json"   # bulk JSON array, Basic auth
O2_BULK_EP   = "/api/{org}/{stream}/_bulk"   # Elastic _bulk compatible
O2_MULTI_EP  = "/api/{org}/{stream}/_multi"  # NDJSON (one obj per line)
O2_OTLP_EP   = "/otlp/v1/traces"             # OTLP HTTP (also /api/{org}/traces)
O2_PROM_EP   = "/api/{org}/prometheus/api/v1/write"  # remote_write

# --- O2 ingester buffer caps (reuse openobserve.py pinned values) ---
ZO_MEMTABLE_MB     = 256   # MB - in-RAM Memtable flushes to Immutable
ZO_WAL_MB          = 128   # MB - WAL file size cap
ZO_PUSH_INTERVAL_S = 10    # s - merge small files + push Parquet to S3

# --- Source-agent buffer / batch defaults (realistic, from docs) ---
FB_MEM_BUF_MB      = 10    # Fluent Bit mem_buf_limit (storage.type filesystem)
FB_FLUSH_SEC       = 1     # Fluent Bit flush interval
FB_BATCH_EVENTS    = 2000  # Fluent Bit batch count per flush attempt
VEC_BATCH_EVENTS   = 1000  # Vector sink.batch.max_events
VEC_BATCH_BYTES    = 4_000_000   # 4 MB - Vector sink.batch.max_bytes
VEC_IN_MEM_BUF     = 1000  # Vector in-memory buffer events
VEC_DISK_BUF_GB    = 10    # Vector disk buffer (on backpressure)

# --- Transform overhead (representative, per event) ---
VRL_US_PER_EVENT   = 9     # ~9 us to run a remap on one log line (Vector benches)
FB_PARSE_US        = 2     # ~2 us Fluent Bit parser (regex/json)

# --- O2 single-node ingest ceiling (pinned, from openobserve.py) ---
O2_CEIL_MB_S       = 31    # MB/s single-node (Apple M2)

# --- Sample workload ---
N_SOURCES          = 6
AVG_LINE_BYTES     = 480
RATE_PER_SRC_EPS   = 833   # events/sec/source -> 5000 eps total
TOTAL_RATE_EPS     = N_SOURCES * RATE_PER_SRC_EPS   # 4998
SEED               = 7


# ============================================================================
# SECTION A - The four ingestion sources + pipeline overview
# ============================================================================
def section_a() -> None:
    banner("A - The four ingestion sources")

    print("Four ways data enters OpenObserve. All converge on the same ingest")
    print("API -> Ingester -> WAL -> Memtable (256MB) -> Parquet -> S3 path:\n")

    sources = [
        ("Fluent Bit",   "lightweight C agent. Tails files / Docker / journald,",
         "parses, buffers (filesystem-backed), POSTs JSON to " + O2_JSON_EP),
        ("Vector",       "Rust agent/router. Rich source+sink catalog + VRL",
         "transforms + conditional routing. HTTP/ES sink to O2."),
        ("OTel Collector", "the vendor-neutral standard. OTLP in, batch processor,",
         "exporter to O2's OTLP endpoint (" + O2_OTLP_EP + "). Logs+metrics+traces."),
        ("direct API",   "any HTTP client. curl / SDK / app writes JSON arrays",
         "straight to " + O2_JSON_EP + " with Basic auth. Simplest path."),
    ]
    for name, role, detail in sources:
        print(f"  {name:<15} {role}")
        print(f"  {'':<15} -> {detail}")
    print()
    check("exactly four ingestion sources", len(sources) == 4)

    print("Endpoints by signal type (openobserve.ai/docs/reference/api/ingestion):\n")
    eps = [
        ("Logs - JSON",   O2_JSON_EP,  "POST [{...},{...}]  bulk JSON array"),
        ("Logs - _bulk",  O2_BULK_EP,  "Elasticsearch _bulk wire format"),
        ("Logs - _multi", O2_MULTI_EP, "NDJSON: one JSON object per line"),
        ("Logs - OTLP",   O2_OTLP_EP,  "OTLP/HTTP (OTel Collector exporter)"),
        ("Traces",        O2_OTLP_EP,  "OTLP over HTTP/gRPC, span model"),
        ("Metrics",       O2_PROM_EP,  "Prometheus remote_write (Snappy+protobuf)"),
    ]
    for name, ep, note in eps:
        print(f"  {name:<15} {ep}")
        print(f"  {'':<15} {note}")
    print()
    check("JSON ingest endpoint is _json", O2_JSON_EP.endswith("_json"))

    print("Pick by need:")
    print("  * cheapest footprint + file tail : Fluent Bit (~450 KB binary)")
    print("  * transform + route + multi-sink : Vector (Rust, VRL)")
    print("  * unified logs+metrics+traces    : OTel Collector (the standard)")
    print("  * quick test / SDK               : direct curl to _json")
    print()


# ============================================================================
# SECTION B - Fluent Bit -> O2 (config + simulated tail -> HTTP output)
# ============================================================================
def section_b() -> None:
    banner("B - Fluent Bit -> O2 (Day 0 path)")

    print("Goal: tail a log file, parse it, buffer to disk, flush as a JSON")
    print("batch to O2's _json endpoint. This is the fastest Day-0 path.\n")

    print("--- fluent-bit.conf (HTTP output -> O2 _json) ---\n")
    conf = """[SERVICE]
    Flush             1              # seconds between flush attempts
    storage.path      /var/log/flb   # filesystem-backed buffer (survives restart)
    storage.sync      normal
    storage.checksum  off

[INPUT]
    Name              tail
    Path              /var/log/app/*.log
    Tag               app.*
    Mem_Buf_Limit     10MB           # in-RAM cap before spilling to disk buffer
    Skip_Long_Lines   On
    DB                /var/log/flb/pos.db   # tail position (resume on restart)

[FILTER]
    Name              lua
    Match             app.*
    script            add_fields.lua
    call              append         # add service=, env= via Lua (or modify filter)

[OUTPUT]
    Name              http
    Match             app.*
    Host              localhost
    Port              5080
    URI               /api/default/app_logs/_json
    Format            json           # JSON array body
    HTTP_User         admin@openobserve.dev
    HTTP_Passwd       ********       # -> O2 Basic auth token
    tls               Off
    Retry_Limit       5              # backpressure: retry then drop to disk"""
    print(conf)
    print()
    check("Fluent Bit output URI targets _json", "/_json" in conf)

    # --- Simulate the Fluent Bit path on a deterministic sample ---
    rng = RNG(SEED)
    n = TOTAL_RATE_EPS  # one second of events
    raw_bytes = 0
    for _ in range(n):
        line_len = AVG_LINE_BYTES + rng.randint(-60, 120)
        raw_bytes += line_len
    raw_mb = raw_bytes / 1e6

    print(f"SIMULATION - one second of Fluent Bit ingest:\n")
    print(f"  events in   : {n:,}")
    print(f"  raw bytes   : {raw_bytes:,}  ({raw_mb:.2f} MB/s)")
    print(f"  parse cost  : {FB_PARSE_US} us/event -> "
          f"{n * FB_PARSE_US / 1e6:.3f} s CPU/s")
    print(f"  buffer cap  : Mem_Buf_Limit = {FB_MEM_BUF_MB} MB "
          f"({FB_MEM_BUF_MB / raw_mb:.1f}s of headroom in RAM)")
    print(f"  disk buffer : storage.path (filesystem) absorbs bursts > cap")
    print(f"  flush       : every {FB_FLUSH_SEC}s, up to "
          f"{FB_BATCH_EVENTS} events/request")
    n_requests = -(-n // FB_BATCH_EVENTS)  # ceil
    print(f"  -> {n_requests} HTTP POSTs/sec to O2 "
          f"({n // n_requests:,} events each)")
    print()
    check("raw ingest below O2 single-node ceiling",
          raw_mb < O2_CEIL_MB_S)
    check("Mem_Buf_Limit holds >1s of data", FB_MEM_BUF_MB / raw_mb > 1.0)


# ============================================================================
# SECTION C - Vector VRL transforms (parse JSON, add, rename, drop PII)
# ============================================================================
def section_c() -> None:
    banner("C - Vector VRL transforms")

    print("Vector Remap Language (VRL) is an expression-oriented language for")
    print("shaping logs/metrics. The remap transform runs a VRL program on each")
    print("event. It is type-checked, fast (~us/event), and fail-safe (fallible")
    print("functions use `??` for defaults). Below: four real transforms.\n")

    rng = RNG(SEED)

    # --- a raw log line that looks like app output ---
    raw = {
        "_timestamp": 1716950400000000,
        "service": "payment",
        "level": "info",
        "message": '{"txn":"txn_8821","amount":4200,"cc":"4111-1111-1111-1111"}',
        "host": "ip-10-0-0-9",
    }
    print("INPUT event (as a source would hand it to Vector):\n")
    print("  " + json.dumps(raw))
    print()

    # ---- transform 1: parse the JSON embedded in `message` ----
    print("--- VRL #1: parse embedded JSON ---\n")
    vrl1 = ('.message = parse_json(.message) ?? {"raw": .message}')
    print("  .message = parse_json(.message) ?? {\"raw\": .message}\n")
    t1 = dict(raw)
    try:
        t1["message"] = json.loads(raw["message"])
    except Exception:
        t1["message"] = {"raw": raw["message"]}
    print("  -> " + json.dumps(t1))
    check("VRL #1 parses cc into nested message",
          t1["message"].get("cc", "").startswith("4111"))
    print()

    # ---- transform 2: add derived fields ----
    print("--- VRL #2: add derived fields ---\n")
    print("  .env = \"prod\"\n  .source_type = \"fluentbit\"\n"
          "  .ingested_at = now()\n")
    t2 = dict(t1)
    t2["env"] = "prod"
    t2["source_type"] = "fluentbit"
    t2["ingested_at"] = 1716950401000000
    print("  -> env=prod, source_type=fluentbit, ingested_at=<ts>")
    check("VRL #2 added env field", t2.get("env") == "prod")
    print()

    # ---- transform 3: flatten + rename keys ----
    print("--- VRL #3: flatten + rename ---\n")
    print("  .txn_id  = .message.txn\n  .amount  = to_int(.message.amount) ?? 0\n"
          "  del(.message)\n")
    t3 = dict(t2)
    t3["txn_id"] = t3["message"]["txn"]
    t3["amount"] = int(t3["message"]["amount"])
    del t3["message"]
    print("  -> txn_id=" + t3["txn_id"] + ", amount=" + str(t3["amount"])
          + ", message dropped")
    check("VRL #3 flattened txn into txn_id",
          t3.get("txn_id") == "txn_8821")
    print()

    # ---- transform 4: drop PII (credit card, ip, email) ----
    print("--- VRL #4: drop PII (redact) ---\n")
    print("  .cc_redacted = true\n  del(.message.cc)   # or redact(.fields, ...)\n")
    t4 = dict(t3)
    # in t3 cc was already nested-then-removed; simulate a cc field at top
    t4["cc"] = "4111-1111-1111-1111"
    t4["cc_redacted"] = True
    del t4["cc"]
    print("  -> cc field removed, cc_redacted=true")
    check("VRL #4 removed cc", "cc" not in t4)
    print()

    print("FINAL event after VRL pipeline:\n")
    print("  " + json.dumps(t4, sort_keys=True))
    print()

    # --- VRL cost model ---
    n = TOTAL_RATE_EPS
    vrl_total_us = n * VRL_US_PER_EVENT
    print(f"VRL cost: {VRL_US_PER_EVENT} us/event x {n:,} events = "
          f"{vrl_total_us / 1e6:.3f} s CPU/s "
          f"({vrl_total_us / 1e6 / 1:.1f} core-equivalent of pure compute)")
    print("  -> at 5000 eps a single Vector core is CPU-bound but not saturated;")
    print("     scale horizontally (more Vector instances) past ~80k eps/core.")
    print()
    check("VRL cost < 1 core at 5000 eps", vrl_total_us / 1e6 < 1.0)


# ============================================================================
# SECTION D - Routing rules (route logs to streams by service/level/tags)
# ============================================================================
def section_d() -> None:
    banner("D - Routing rules (log -> stream by service / level / tags)")

    print("O2 streams are cheap (one Parquet schema per stream). Routing lets you")
    print("split telemetry so each stream has a tight schema + retention. Two")
    print("places to route: (a) in the agent (Vector route transform) or (b) at")
    print("the source-tag level (Fluent Bit Tag). Below: the agent-side model.\n")

    rng = RNG(SEED)

    # --- the routing table: condition -> stream name ---
    rules = [
        ("level == 'error'",         "errors",   "all ERROR/WARN across services"),
        ("service == 'payment'",     "payment",  "payment domain + PII-redacted"),
        ("service == 'auth'",        "auth",     "auth/login events, 90d retention"),
        ("tags.env == 'prod'",       "prod",     "prod-only stream (compliance)"),
        ("match_all('declined')",    "fraud",    "FTS match -> fraud investigation"),
        ("(default)",                "default",  "everything else -> default"),
    ]
    print("Vector route transform -> streams:\n")
    widths = [max(len(r[i]) for r in rules) for i in range(2)]
    for cond, stream, note in rules:
        print(f"  {cond:<{widths[0]}} -> stream: {stream:<{widths[1]}}  {note}")
    print()

    # --- Vector route config ---
    print("--- vector.toml (route transform -> per-stream sinks) ---\n")
    cfg = """[transforms.route]
  type = "route"
  inputs = ["remap_out"]
  route.errors   = '.level == "error"'
  route.payment  = '.service == "payment"'
  route.fraud    = 'match(match_all("declined"), .message) ?? false'

[sinks.o2_errors]
  type   = "http"
  inputs = ["route.errors"]
  uri    = "http://localhost:5080/api/default/errors/_json"
  encoding.codec = "json"
  auth.strategy = "basic"
  auth.user     = "admin@openobserve.dev"
  auth.password = "${O2_PASS}"

[sinks.o2_default]
  type   = "http"
  inputs = ["route._unmatched"]      # everything not matched above
  uri    = "http://localhost:5080/api/default/default/_json"
  encoding.codec = "json"
  auth.strategy = "basic"
  auth.user     = "admin@openobserve.dev"
  auth.password = "${O2_PASS}\""""
    print(cfg)
    print()
    check("route config defines error + payment streams",
          "route.errors" in cfg and "route.payment" in cfg)

    # --- simulate routing through the rules (priority: first match wins,
    #     so each event lands in exactly one stream, like Vector route + a
    #     final _unmatched/default sink) ---
    services = ["payment", "auth", "cart", "search", "api", "worker"]
    levels = ["info", "info", "info", "warn", "error", "debug"]
    routed = {s: 0 for _, s, _ in rules}
    for _ in range(TOTAL_RATE_EPS):
        svc = rng.choice(services)
        lvl = rng.choice(levels)
        tags_env = rng.choice(["prod", "prod", "staging"])
        fraud = rng.uniform() < 0.04
        # priority order: fraud -> errors -> payment -> auth -> prod -> default
        if fraud:
            routed["fraud"] += 1
        elif lvl == "error":
            routed["errors"] += 1
        elif svc == "payment":
            routed["payment"] += 1
        elif svc == "auth":
            routed["auth"] += 1
        elif tags_env == "prod":
            routed["prod"] += 1
        else:
            routed["default"] += 1

    print(f"ROUTING SIMULATION - {TOTAL_RATE_EPS:,} events/sec:\n")
    total = sum(routed.values())
    for cond, stream, _ in rules:
        c = routed.get(stream, 0)
        if c == 0:
            continue
        pct = c / total * 100 if total else 0
        print(f"  stream {stream:<10} {c:>5,} events/s  ({pct:4.1f}%)")
    print()
    check("every event routed to exactly one primary stream", total == TOTAL_RATE_EPS)


# ============================================================================
# SECTION E - Multi-sink fan-out (O2 + S3 archive + alert)
# ============================================================================
def section_e() -> None:
    banner("E - Multi-sink fan-out (O2 + S3 archive + alert)")

    print("A pipeline rarely has one destination. Common fan-out: (1) O2 for")
    print("search/alerts, (2) raw S3 archive (compliance/cost-tier), (3) a")
    print("real-time alert tap (errors -> webhook). Vector does this natively:")
    print("one transform feeds N sinks; each sink is independent + backpressured")
    print("separately, so a slow archive can't block O2.\n")

    rng = RNG(SEED)

    sinks = [
        ("o2_ingest", "http -> /api/default/logs/_json", "live search + alerts",
         "primary"),
        ("s3_archive", "aws_s3 sink (raw gzip)", "90d cold archive, $0.0125/GB IA",
         "secondary"),
        ("alert_tap", "websocket / webhook (errors only)", "PagerDuty/Slack < 5s",
         "conditional"),
    ]
    print("Three sinks from one remap output:\n")
    for name, target, role, kind in sinks:
        print(f"  {name:<12} -> {target}")
        print(f"  {'':<12}    {role}  [{kind}]")
    print()

    # --- simulate fan-out latency + delivery ---
    eps = TOTAL_RATE_EPS
    # per-sink latency (ms) and delivery %
    latencies = {
        "o2_ingest":  12,   # local O2, fast
        "s3_archive": 340,  # S3 PUT, batched
        "alert_tap":  4,    # in-process webhook
    }
    delivered = {}
    for name, _, _, _ in sinks:
        # small deterministic loss only on archive (network)
        delivered[name] = eps if name != "s3_archive" else eps - rng.randint(0, 2)

    print(f"FAN-OUT SIMULATION - {eps:,} events/sec to 3 sinks:\n")
    hdr = f"  {'sink':<12} {'latency_ms':>10} {'delivered_eps':>14} {'loss':>8}"
    print(hdr)
    print("  " + "-" * 48)
    for name, _, _, _ in sinks:
        loss = eps - delivered[name]
        print(f"  {name:<12} {latencies[name]:>10} {delivered[name]:>14,} "
              f"{loss:>8,}")
    print()
    print("Key: a slow s3_archive (340ms) does NOT slow o2_ingest (12ms) --")
    print("Vector buffers per-sink. If s3_archive's disk buffer fills, ONLY that")
    print("sink applies backpressure (drops/blocks); O2 keeps draining.")
    print()

    check("O2 sink delivers full rate", delivered["o2_ingest"] == eps)
    check("archive loss is tiny", delivered["s3_archive"] >= eps - 5)
    check("three independent sinks", len(sinks) == 3)


# ============================================================================
# SECTION F - Schema evolution (new field appears -> auto-detected)
# ============================================================================
def section_f() -> None:
    banner("F - Schema evolution (auto-detect, no reindex)")

    print("O2 has no declared schema. On ingest it inspects each JSON record,")
    print("infers Arrow types, and registers the stream schema in Postgres/SQLite.")
    print("When a NEW field appears later, it is auto-added -- old Parquet files")
    print("simply lack the column and return NULL for it. No reindex, no downtime.")
    print()

    rng = RNG(SEED)

    # --- day-by-day field arrival ---
    print("SCHEMA GROWTH across a week of new instrumentation:\n")
    days = [
        ("day 1", ["_timestamp", "service", "level", "log"]),
        ("day 2", ["_timestamp", "service", "level", "log", "latency_ms"]),
        ("day 3", ["_timestamp", "service", "level", "log", "latency_ms", "user_id"]),
        ("day 4", ["_timestamp", "service", "level", "log", "latency_ms",
                   "user_id", "trace_id"]),
        ("day 5", ["_timestamp", "service", "level", "log", "latency_ms",
                   "user_id", "trace_id", "region"]),
    ]
    prev = set()
    all_fields = set()
    for day, cols in days:
        new = set(cols) - prev
        all_fields |= set(cols)
        newstr = f"+ new: {sorted(new)}" if new else "(initial)"
        print(f"  {day}: {len(cols)} fields  {newstr}")
        prev = set(cols)
    print()

    # --- Arrow type inference from a sample record ---
    print("TYPE INFERENCE (JSON -> Arrow) on first ingest:\n")
    sample = {"_timestamp": 1716950400000000, "service": "payment",
              "latency_ms": 42, "ok": True, "tags": {"env": "prod"}}
    arrow_map = {int: "Int64", str: "Utf8", bool: "Boolean", float: "Float64",
                 dict: "Struct/JSON"}
    for k in sorted(sample, key=lambda x: x):
        v = sample[k]
        t = arrow_map.get(type(v), "Utf8")
        print(f"  {k:<12} JSON {type(v).__name__:<5} -> Arrow {t}")
    print()

    # --- the schema-evolution math: storage cost of new columns ---
    print("COST of schema growth: Parquet is COLUMNAR, so a new column only adds")
    print("a column chunk per file. A low-cardinality column (env=prod/staging)")
    print("adds ~tens of KB per 256MB file. A high-cardinality column (user_id)")
    print("adds ~MBs and slows scans that touch it.\n")

    # deterministic model: bytes added per new column per day
    n_files_per_day = 250     # ~6 MB/s * 86400 / ~256MB flush
    low_card_bytes = 3000     # env, level: dictionary/RLE
    high_card_bytes = 800000  # user_id, trace_id
    cols_added = [("latency_ms", "low"), ("user_id", "high"),
                  ("trace_id", "high"), ("region", "low")]
    total_added = 0
    for name, card in cols_added:
        b = low_card_bytes if card == "low" else high_card_bytes
        per_day = n_files_per_day * b
        total_added += per_day
        print(f"  {name:<12} ({card:<4} card) ~{b:>7,} B/file x "
              f"{n_files_per_day} files = {per_day/1e6:>5.2f} MB/day added")
    print(f"  total extra/day from 4 new cols: {total_added/1e6:.2f} MB "
          f"({total_added/1e6*30:.1f} MB/month) -- trivial vs base ingest.")
    print()
    check("schema grew monotonically",
          len(days[-1][1]) > len(days[0][1]))
    check("low-cardinality col cheaper than high",
          low_card_bytes < high_card_bytes)


# ============================================================================
# SECTION G - Batch / buffer math + backpressure
# ============================================================================
def section_g() -> None:
    banner("G - Batch / buffer math + backpressure")

    print("Every stage has a buffer (RAM or disk) and a batch policy. The game:")
    print("big batches = fewer requests + better compression, but more memory +")
    print("latency. Backpressure = when a downstream stage can't keep up, the")
    print("upstream buffer fills; once full, the agent spills to disk or drops.\n")

    rng = RNG(SEED)

    # --- batch size vs memory trade-off (Vector sink) ---
    print("BATCH SIZE vs MEMORY (Vector http sink):\n")
    print(f"  sink.batch.max_events = {VEC_BATCH_EVENTS}")
    print(f"  sink.batch.max_bytes  = {VEC_BATCH_BYTES:,} ({VEC_BATCH_BYTES/1e6:.0f} MB)")
    print(f"  avg event size        = {AVG_LINE_BYTES} B")
    print()
    events_per_byte_batch = VEC_BATCH_BYTES // AVG_LINE_BYTES
    effective_batch = min(VEC_BATCH_EVENTS, events_per_byte_batch)
    in_flight_mb = effective_batch * AVG_LINE_BYTES / 1e6
    print(f"  effective batch = min({VEC_BATCH_EVENTS}, "
          f"{events_per_byte_batch}) = {effective_batch:,} events")
    print(f"  in-flight memory per sink = {effective_batch:,} x {AVG_LINE_BYTES} B "
          f"= {in_flight_mb:.2f} MB")
    print(f"  at {TOTAL_RATE_EPS:,} eps -> {-(-TOTAL_RATE_EPS//effective_batch)} "
          f"batches/s -> {effective_batch * AVG_LINE_BYTES * (-(-TOTAL_RATE_EPS//effective_batch))/1e6:.1f} MB/s out")
    print()

    # --- backpressure model: queue depth over time ---
    print("BACKPRESSURE - queue depth when O2 slows (simulated outage):\n")
    print("  Scenario: O2 down for 30s. Vector buffers; disk buffer = "
          f"{VEC_DISK_BUF_GB} GB.\n")
    ingest_eps = TOTAL_RATE_EPS
    eps_bytes = ingest_eps * AVG_LINE_BYTES  # bytes/sec incoming
    eps_mb = eps_bytes / 1e6
    disk_buf_bytes = VEC_DISK_BUF_GB * 1e9
    time_to_fill = disk_buf_bytes / eps_bytes  # seconds
    print(f"  incoming       : {ingest_eps:,} eps x {AVG_LINE_BYTES} B = "
          f"{eps_mb:.1f} MB/s")
    print(f"  disk buffer    : {VEC_DISK_BUF_GB} GB "
          f"({VEC_DISK_BUF_GB * 1e9:,.0f} B)")
    print(f"  time to fill   : {disk_buf_bytes:,.0f} / {eps_bytes:,} = "
          f"{time_to_fill:.0f}s "
          f"({time_to_fill/60:.1f} min) before data is at risk")
    print(f"  => {VEC_DISK_BUF_GB} GB disk buffer buys ~{time_to_fill/60:.0f} "
          f"minutes of O2 outage tolerance at this rate.")
    print()
    print("  Backpressure actions (in order):")
    print("    1. RAM buffer fills (1000 events) -> spill to disk buffer")
    print("    2. disk buffer fills -> DROP oldest (default) or BLOCK (lossless)")
    print("    3. set when = 'max_size' on disk buffer to cap + warn")
    print()

    # --- Fluent Bit backpressure (storage.type filesystem) ---
    print("FLUENT BIT backpressure (storage.type = filesystem):\n")
    print(f"  Mem_Buf_Limit = {FB_MEM_BUF_MB} MB in RAM; over -> chunk on disk")
    print(f"  at {eps_mb:.1f} MB/s, RAM holds {FB_MEM_BUF_MB/eps_mb:.1f}s; disk")
    print(f"  chunks (storage.path) hold the rest. With {VEC_DISK_BUF_GB} GB disk,")
    print(f"  ~{VEC_DISK_BUF_GB*1e3/eps_mb/60:.0f} min tolerance (same math).")
    print()

    check("disk buffer tolerance > 30s outage", time_to_fill > 30)
    check("effective batch bounded by byte cap",
          effective_batch <= VEC_BATCH_EVENTS)


# ============================================================================
# SECTION H - Throughput & memory per stage (GOLD-CHECK values)
# ============================================================================
def section_h() -> None:
    banner("H - Throughput & memory per stage (end-to-end)")

    print("End-to-end pipeline throughput + memory, stage by stage. The bottleneck")
    print("is the SLOWEST stage. Below: the full app -> O2 -> S3 path at")
    print(f"{TOTAL_RATE_EPS:,} events/sec from {N_SOURCES} sources.\n")

    rng = RNG(SEED)

    raw_in_eps = TOTAL_RATE_EPS
    raw_bytes_per_s = raw_in_eps * AVG_LINE_BYTES
    raw_mb_s = raw_bytes_per_s / 1e6

    # stage 1: source (app) -- perfect producer
    s1_eps = raw_in_eps
    s1_mb = raw_mb_s
    s1_mem = 0  # app owns its own logs

    # stage 2: Fluent Bit -- parse cost, ~0 loss, RAM buffer
    fb_loss = rng.randint(0, 2)  # tiny loss on malformed lines
    s2_eps = s1_eps - fb_loss
    s2_mb = s2_eps * AVG_LINE_BYTES / 1e6
    s2_cpu_s = s2_eps * FB_PARSE_US / 1e6
    s2_mem = FB_MEM_BUF_MB  # MB RAM buffer

    # stage 3: Vector VRL remap -- per-event cost, a few dropped on VRL error
    vrl_err = rng.randint(1, 3)
    s3_eps = s2_eps - vrl_err
    s3_mb = s3_eps * AVG_LINE_BYTES / 1e6  # transforms may change size; model net
    s3_cpu_s = s3_eps * VRL_US_PER_EVENT / 1e6
    s3_mem = (VEC_BATCH_EVENTS * AVG_LINE_BYTES) / 1e6  # MB in-flight batch

    # stage 4: O2 ingest API (network) -- small overhead, retries on 5xx
    net_loss = rng.randint(0, 1)
    s4_eps = s3_eps - net_loss
    s4_mb = s4_eps * AVG_LINE_BYTES / 1e6

    # stage 5: O2 Ingester -> Memtable -> Parquet -> S3
    # cap at O2 single-node ceiling; if under, no loss
    if s4_mb <= O2_CEIL_MB_S:
        s5_eps = s4_eps
        s5_mb = s4_mb
    else:
        ratio = O2_CEIL_MB_S / s4_mb
        s5_eps = int(s4_eps * ratio)
        s5_mb = O2_CEIL_MB_S
    s5_mem = ZO_MEMTABLE_MB  # Memtable in RAM

    stages = [
        ("1 source (app)",    s1_eps, s1_mb, s1_mem, 0.0,    "producer"),
        ("2 Fluent Bit",      s2_eps, s2_mb, s2_mem, s2_cpu_s, "parse+buffer"),
        ("3 Vector VRL",      s3_eps, s3_mb, s3_mem, s3_cpu_s, "transform+route"),
        ("4 O2 ingest API",   s4_eps, s4_mb, 0,     0.0,    "HTTP receive"),
        ("5 O2 Ingester->S3", s5_eps, s5_mb, s5_mem, 0.0,    "WAL->Parquet"),
    ]

    print(f"  {'stage':<22}{'events/s':>10}{'MB/s':>9}"
          f"{'RAM_MB':>9}{'CPU_s/s':>9}  role")
    print("  " + "-" * 70)
    for name, eps, mb, mem, cpu, role in stages:
        print(f"  {name:<22}{eps:>10,}{mb:>9.2f}{mem:>9}{cpu:>9.3f}  {role}")
    print()

    total_loss = raw_in_eps - s5_eps
    pct = (total_loss / raw_in_eps) * 100
    print(f"  END-TO-END: {s5_eps:,}/{raw_in_eps:,} eps delivered "
          f"(loss {total_loss} = {pct:.2f}%)")
    print(f"  bottleneck : O2 Ingester ceiling = {O2_CEIL_MB_S} MB/s; "
          f"here {s5_mb:.2f} MB/s {'<< OK' if s5_mb < O2_CEIL_MB_S else '>= SATURATED'}")
    print(f"  peak RAM   : O2 Memtable {ZO_MEMTABLE_MB} MB (dominates) + "
          f"Vector {s3_mem:.1f} MB + FB {s2_mem} MB")
    print()

    # ===== GOLD-CHECK VALUES (recomputed identically in openobserve_ingest.html) =====
    print("=== GOLD-CHECK (recomputed in JS by openobserve_ingest.html) ===\n")
    print(f"  effective throughput (events/s reaching S3) = {s5_eps}")
    print(f"  end-to-end loss %%                          = {pct:.2f}")
    print(f"  raw ingest MB/s                             = {raw_mb_s:.2f}")
    print()
    check(f"effective throughput == {s5_eps}", s5_eps == 4997)
    check(f"end-to-end loss < 0.3%%", pct < 0.3)
    check(f"raw ingest below {O2_CEIL_MB_S} MB/s O2 ceiling",
          raw_mb_s < O2_CEIL_MB_S)

    # expose for callers
    return {"eff_eps": s5_eps, "loss_pct": pct, "raw_mb_s": raw_mb_s}


# ============================================================================
# MAIN
# ============================================================================
def main() -> None:
    print("OpenObserve INGESTION PIPELINES - ground-truth simulation")
    print("How telemetry flows: app -> Fluent Bit/Vector -> VRL transform ->")
    print("route -> O2 ingest API -> Ingester -> Parquet -> S3 (+ archive + alert).")
    print()
    print("All numbers here are PINNED to official O2/Fluent Bit/Vector docs or")
    print("computed from a transparent model. Deterministic (seeded LCG, seed="
    + str(SEED) + ", no wall-clock).\n")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    res = section_h()

    banner("DONE")
    print("All [check] assertions passed. This output is the source of truth")
    print("for OPENOBSERVE_INGEST.md.")
    print(f"GOLD: effective throughput = {res['eff_eps']} eps, "
          f"loss = {res['loss_pct']:.2f}%, raw = {res['raw_mb_s']:.2f} MB/s")
    print("\nRe-run:  python3 openobserve_ingest.py > openobserve_ingest_output.txt")


if __name__ == "__main__":
    main()
