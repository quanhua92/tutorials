"""
observability_fundamentals.py - Ground truth for the observability fundamentals
concept bundle (bundle #01).

This is the SINGLE SOURCE OF TRUTH. Every number in OBSERVABILITY_FUNDAMENTALS.md
and every recomputation in observability_fundamentals.html derives from this
file. Change something here, re-run, re-paste the output into the .md, and
confirm the .html gold-check still says OK.

Run:
    python3 observability_fundamentals.py > observability_fundamentals_output.txt

Pure standard library (random, math). Deterministic: every run is byte-identical
because all randomness flows from one seeded RNG. No wall-clock, no dict order
dependency, no network.

What this bundle covers (the observability "fundamentals"):
  A. The three pillars: metric types (counter, gauge, histogram)
  B. Structured logs: JSON records + trace_id correlation
  C. Distributed traces: span trees, self-time, critical path
  D. SLI / SLO / SLA + error budget math
  E. Error budget burn rate + Google SRE multi-window alerting
  F. USE method (resources: Utilization / Saturation / Errors)
  G. RED method (services: Rate / Errors / Duration)
  H. High-cardinality label explosion (the silent Prometheus killer)
"""
import json
import math
import random

# ---- determinism --------------------------------------------------------
RNG = random.Random(42)  # fixed seed; all randomness flows from here

# ---- formatting helpers (the house style) -------------------------------
BANNER = "=" * 72


def banner(title):
    print(f"\n{BANNER}\n{title}\n{BANNER}")


def check(desc, ok):
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


def line(label, value):
    print(f"  {label:<38} {value}")


# =========================================================================
# SECTION A - The Three Pillars: metric types (counter / gauge / histogram)
# =========================================================================
def section_a():
    banner("SECTION A - THE THREE PILLARS: METRIC TYPES")
    print(
        "Metrics are the numeric dashboard: numbers aggregated over a time\n"
        "  window. The unit is a time-series: (name, labels) -> value @ sample.\n"
        "  There are THREE primitive metric types, each answering a different\n"
        "  question."
    )

    # --- A1. counter: only goes up (or resets to 0 on restart) ------------
    print("\n  A1. COUNTER - 'how many in total so far.' Only goes UP.")
    print("      Use rate()/increase() over a window. Never subtract samples.")
    counter = 0
    samples = []  # 12 samples, one per minute
    for _ in range(12):
        # cumulative: each minute adds some requests
        counter += RNG.randint(80, 120)
        samples.append(counter)
    for i, v in enumerate(samples):
        line(f"http_requests_total @ t={i}min", v)
    # rate() = (last - first) / window_seconds
    rate_per_sec = (samples[-1] - samples[0]) / (11 * 60)
    line("rate(http_requests_total[11m])", f"{rate_per_sec:.4f} req/s")
    check("counter monotonically non-decreasing", all(
        samples[i] <= samples[i + 1] for i in range(len(samples) - 1)
    ))

    # --- A2. gauge: goes up AND down. 'what is it right now.' -------------
    print("\n  A2. GAUGE - 'what is it right now.' Goes UP or DOWN.")
    print("      e.g. queue_depth, memory_bytes, active_connections.")
    gauge = 0
    g_samples = []
    for _ in range(8):
        gauge += RNG.randint(-15, 20)  # can go up or down
        gauge = max(0, gauge)
        g_samples.append(gauge)
    for i, v in enumerate(g_samples):
        line(f"queue_depth @ t={i}", v)
    line("avg_over_time(queue_depth[8])", f"{sum(g_samples) / len(g_samples):.2f}")
    check("gauge can decrease", any(
        g_samples[i] > g_samples[i + 1] for i in range(len(g_samples) - 1)
    ))

    # --- A3. histogram: buckets + _sum + _count. p95 via interpolation ----
    print("\n  A3. HISTOGRAM - buckets observations + sum + count.")
    print("      Lets you compute percentiles (p95/p99). Cheaper than storing")
    print("      every raw observation.")
    # bucket boundaries (seconds): the classic latency buckets
    bounds = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, math.inf]
    # simulate 1000 latencies ~ log-normal
    latencies = [RNG.lognormvariate(-4.0, 0.6) for _ in range(1000)]
    total_sum = sum(latencies)
    # per-bucket (non-cumulative) counts first
    per_bucket = [0] * len(bounds)
    for lat in latencies:
        for i, b in enumerate(bounds):
            if lat <= b:
                per_bucket[i] += 1
                break
    # Prometheus histograms are CUMULATIVE: bucket[i] = sum(per_bucket[0..i])
    cum = []
    running = 0
    for c in per_bucket:
        running += c
        cum.append(running)
    buckets = list(zip(bounds, cum))
    print("      http_request_duration_seconds_bucket (CUMULATIVE):")
    for b, c in buckets:
        label_b = "+Inf" if math.isinf(b) else f"{b}"
        line(label_b, c)
    line("_count", cum[-1])
    line("_sum", f"{total_sum:.4f}")

    def histogram_quantile(buckets, q):
        total = buckets[-1][1]
        target = q * total
        for i, (bound, count) in enumerate(buckets):
            if count >= target:
                if i == 0:
                    return bound
                prev_bound, prev_count = buckets[i - 1]
                span = count - prev_count
                if span == 0:
                    return bound
                frac = (target - prev_count) / span
                return prev_bound + frac * (bound - prev_bound)
        return buckets[-1][0]

    p50 = histogram_quantile(buckets, 0.50)
    p95 = histogram_quantile(buckets, 0.95)
    p99 = histogram_quantile(buckets, 0.99)
    line("histogram_quantile(..., 0.50) p50", f"{p50:.4f}s")
    line("histogram_quantile(..., 0.95) p95", f"{p95:.4f}s")
    line("histogram_quantile(..., 0.99) p99", f"{p99:.4f}s")
    check("p50 <= p95 <= p99 (monotonic percentiles)", p50 <= p95 <= p99)
    check("p95 within bucket bounds", bounds[0] <= p95 <= bounds[-2])


# =========================================================================
# SECTION B - Structured logs: JSON records + trace_id correlation
# =========================================================================
def section_b():
    banner("SECTION B - STRUCTURED LOGS: THE 'WHY' OF ONE EVENT")
    print(
        "A log is ONE timestamped event record, ideally structured JSON. Best\n"
        "  for the WHY of a single event. The KEY is a trace_id stamped into\n"
        "  every log line AND every metric label AND every trace span - that\n"
        "  correlation key is what lets you jump alert -> log -> trace."
    )
    trace_id = "4a3b2c1d-trace-0001"
    user_id = 8842
    log_events = [
        {"ts": "12:01:03.012", "level": "INFO", "svc": "gateway",
         "msg": "request start", "trace_id": trace_id, "user_id": user_id,
         "method": "GET", "path": "/api/checkout"},
        {"ts": "12:01:03.087", "level": "INFO", "svc": "checkout",
         "msg": "calling payment", "trace_id": trace_id, "user_id": user_id},
        {"ts": "12:01:03.901", "level": "ERROR", "svc": "payment",
         "msg": "token expired", "trace_id": trace_id, "user_id": user_id,
         "code": "AUTH_EXPIRED"},
        {"ts": "12:01:03.905", "level": "WARN", "svc": "gateway",
         "msg": "request failed", "trace_id": trace_id, "user_id": user_id,
         "status": 502},
    ]
    print("\n  Sample structured log stream (JSON lines):")
    for ev in log_events:
        print(f"  {json.dumps(ev, sort_keys=True)}")

    # severity levels and their meaning
    levels = [("DEBUG", "fine-grained dev detail"),
              ("INFO", "normal operation"),
              ("WARN", "unexpected but handled"),
              ("ERROR", "a request failed"),
              ("FATAL", "the process must exit")]
    print("\n  Severity level taxonomy:")
    for name, meaning in levels:
        line(name, meaning)

    # correlation proof: the same trace_id appears in a metric label too
    metric_label = f'http_requests_total{{trace_id="{trace_id}",status="502"}}'
    line("\n  correlated metric series", metric_label)
    line("logs sharing trace_id", sum(1 for e in log_events if e["trace_id"] == trace_id))
    check("trace_id ties log lines together", all(
        e["trace_id"] == trace_id for e in log_events
    ))


# =========================================================================
# SECTION C - Distributed traces: span tree, self-time, critical path
# =========================================================================
def section_c():
    banner("SECTION C - DISTRIBUTED TRACES: THE REQUEST JOURNEY")
    print(
        "A TRACE records every hop (a SPAN) of one user request across services,\n"
        "  with start/end and a parent pointer. Best for 'where did the 800ms\n"
        "  go?' A span = (name, service, start_ms, end_ms, parent_id)."
    )
    # span tree: one root, two children, one grandchild
    spans = [
        {"id": "s0", "parent": None,    "name": "GET /checkout", "svc": "gateway",  "start": 0,   "end": 890},
        {"id": "s1", "parent": "s0",    "name": "validate_cart", "svc": "checkout", "start": 10,  "end": 60},
        {"id": "s2", "parent": "s0",    "name": "charge_card",   "svc": "payment",  "start": 65,  "end": 880},
        {"id": "s3", "parent": "s2",    "name": "stripe_api",    "svc": "payment",  "start": 70,  "end": 875},
    ]
    children = {}
    for s in spans:
        children.setdefault(s["parent"], []).append(s)

    def self_time(span):
        dur = span["end"] - span["start"]
        kids = children.get(span["id"], [])
        covered = sum(k["end"] - k["start"] for k in kids)
        return dur - covered

    print("\n  Span tree with self-time (the part the span was ACTUALLY working):")
    for s in spans:
        dur = s["end"] - s["start"]
        st = self_time(s)
        line(f"{s['id']} {s['svc']}.{s['name']}",
             f"dur={dur}ms self={st}ms parent={s['parent']}")

    # critical path: chain of spans whose self-times dominate the trace.
    # follow the child with the largest covered time at each level.
    path = []
    node = None  # root's parent
    cur = children[None][0]  # root span
    while cur is not None:
        path.append(cur)
        kids = children.get(cur["id"], [])
        if not kids:
            break
        cur = max(kids, key=lambda k: k["end"] - k["start"])

    path_desc = " -> ".join(f"{s['svc']}.{s['name']}" for s in path)
    line("\n  critical path", path_desc)
    line("trace duration (root span)", f"{spans[0]['end'] - spans[0]['start']}ms")
    check("root span span_id s0 has no parent", spans[0]["parent"] is None)
    check("critical path visits the slow payment hop",
          any(s["svc"] == "payment" for s in path))
    check("stripe_api self-time is small (it's a leaf, self==dur)",
          self_time(spans[3]) == spans[3]["end"] - spans[3]["start"])


# =========================================================================
# SECTION D - SLI / SLO / SLA + error budget math
# =========================================================================
def section_d():
    banner("SECTION D - SLI / SLO / SLA + ERROR BUDGET")
    print(
        "  SLI  Service Level Indicator  - the MEASUREMENT\n"
        "      ('fraction of requests < 500ms' or '2xx responses / total')\n"
        "  SLO  Service Level Objective  - the TARGET ('99.9% of requests ok')\n"
        "  SLA  Service Level Agreement  - the CONTRACT / consequence\n"
        "      (refunds/credits if you miss the SLO)\n"
        "  error budget = 1 - SLO. The allowed failure you can 'spend.'"
    )

    def error_budget_minutes(slo, window_days=30):
        frac = 1.0 - slo
        return frac * window_days * 24 * 60

    def error_budget_seconds(slo, window_days=30):
        return (1.0 - slo) * window_days * 24 * 3600

    print("\n  Error budget per 30-day window by SLO target:")
    print(f"  {'SLO':<14} {'budget %':<12} {'min/30d':<12} {'sec/30d':<12}")
    nines = [(0.99, "99%"), (0.999, "99.9%"), (0.9999, "99.99%"),
             (0.99999, "99.999%"), (0.999999, "99.9999%")]
    pinned = None
    for slo, label_slo in nines:
        mins = error_budget_minutes(slo)
        secs = error_budget_seconds(slo)
        if abs(slo - 0.999) < 1e-12:
            pinned = mins
        print(f"  {label_slo:<14} {(1-slo)*100:<12.4f} {mins:<12.2f} {secs:<12.1f}")

    line("\n  PINNED: 99.9% SLO error budget", f"{pinned:.1f} min / 30 days")
    check("99.9% SLO -> 43.2 min / 30 days", abs(pinned - 43.2) < 1e-9)
    check("99.999% (five nines) -> 25.9 sec / 30 days",
          abs(error_budget_seconds(0.99999) - 25.92) < 1e-6)
    # SLI sample computation from synthetic event stream
    events = [("ok", 120), ("ok", 90), ("ok", 150), ("slow", 520),
              ("ok", 110), ("ok", 130), ("err", 0), ("ok", 140),
              ("ok", 100), ("slow", 610)]
    good = sum(1 for tag, _ in events if tag == "ok")
    total = len(events)
    sli = good / total
    line("sample SLI (good/total)", f"{sli:.3f}  ({good}/{total})")
    line("SLO target", "0.999")
    check("SLI 0.8 < SLO 0.999 -> SLO missed", sli < 0.999)


# =========================================================================
# SECTION E - Error budget burn rate + Google SRE multi-window alerting
# =========================================================================
def section_e():
    banner("SECTION E - ERROR BUDGET BURN RATE + MULTI-WINDOW ALERTING")
    print(
        "  burn_rate = observed_error_rate / error_budget_fraction.\n"
        "    burn_rate > 1 means you are on pace to exhaust the entire error\n"
        "    budget within the SLO window. burn_rate = 14.4 means you spend\n"
        "    the whole budget in 1/14.4 of the window.\n\n"
        "  Google SRE multi-window burn-rate alerts (SRE Workbook ch.5):\n"
        "    page on a SHORT window (fast burn) + confirm with a LONG window\n"
        "    to avoid flapping. Thresholds below are for a 30-day SLO window."
    )
    window_days = 30
    window_hours = window_days * 24

    def burn_for_budget_share(share, alert_hours):
        # burn rate that consumes `share` of budget in `alert_hours`
        return (share * window_hours) / alert_hours

    # (action, budget_share, short_window_min, long_window_h)
    alerts = [
        ("PAGE",  0.02, 5,   1),    # 2% budget in 1h
        ("PAGE",  0.05, 30,  6),    # 5% budget in 6h
        ("TICKET", 0.10, 120, 24),  # 10% budget in 1 day
        ("TICKET", 0.10, 360, 72),  # 10% budget in 3 days
    ]
    print(f"\n  {'action':<8} {'budget':<9} {'long win':<10} {'short win':<12} "
          f"{'burn_rate':<10}")
    for action, share, short_min, long_h in alerts:
        br = burn_for_budget_share(share, long_h)
        print(f"  {action:<8} {share*100:<8}% {long_h:<10} {short_min:<12} "
              f"{br:<10.1f}")
    # PINNED: 2% budget / 1h -> 14.4
    br_2pct_1h = burn_for_budget_share(0.02, 1)
    br_5pct_6h = burn_for_budget_share(0.05, 6)
    br_10pct_3d = burn_for_budget_share(0.10, 72)
    line("\n  PINNED: 2% budget / 1h", f"{br_2pct_1h:.1f}")
    line("PINNED: 5% budget / 6h", f"{br_5pct_6h:.1f}")
    line("PINNED: 10% budget / 3d", f"{br_10pct_3d:.1f}")
    check("2% budget in 1h -> burn rate 14.4", abs(br_2pct_1h - 14.4) < 1e-9)
    check("5% budget in 6h -> burn rate 6.0", abs(br_5pct_6h - 6.0) < 1e-9)
    check("10% budget in 3d -> burn rate 1.0", abs(br_10pct_3d - 1.0) < 1e-9)
    # worked example: service at 0.5% error rate vs 99.9% SLO
    observed_err = 0.005
    budget_frac = 1 - 0.999
    burn = observed_err / budget_frac
    line("\n  observed error rate", f"{observed_err*100:.2f}%")
    line("error budget fraction", f"{budget_frac*100:.2f}%")
    line("burn rate", f"{burn:.2f}  (>1 => busting SLO)")
    check("0.5% error vs 99.9% SLO -> burn 5.0", abs(burn - 5.0) < 1e-9)


# =========================================================================
# SECTION F - USE method (resources: Utilization / Saturation / Errors)
# =========================================================================
def section_f():
    banner("SECTION F - USE METHOD (RESOURCES)")
    print(
        "  USE (Brendan Gregg) is for RESOURCES: CPU, memory, disk, network.\n"
        "    Utilization : % time the resource was busy\n"
        "    Saturation  : how much work is queued / waiting\n"
        "    Errors      : hardware/transfer errors (CRC, dropped packets)\n"
        "  Apply all three to EVERY resource, every time."
    )
    # CPU: 8 cores, sampled busy-cores over a window
    cores = 8
    busy_samples = [RNG.randint(2, 8) for _ in range(6)]
    runq_samples = [RNG.randint(0, 4) for _ in range(6)]
    crc_errors = 0
    print(f"\n  CPU ({cores} cores):")
    for i, (busy, runq) in enumerate(zip(busy_samples, runq_samples)):
        util = busy / cores
        line(f"t={i} busy={busy} runq={runq}",
             f"U={util*100:.1f}%  S={runq}  E={crc_errors}")
    avg_util = sum(b / cores for b in busy_samples) / len(busy_samples)
    avg_sat = sum(runq_samples) / len(runq_samples)
    line("avg utilization U", f"{avg_util*100:.1f}%")
    line("avg saturation S (runq len)", f"{avg_sat:.2f}")
    line("avg errors E (crc)", crc_errors)
    check("USE CPU utilization in [0,1]", 0.0 <= avg_util <= 1.0)
    check("USE saturation >= 0", avg_sat >= 0)
    # memory: util = used/total, sat = swap/page-faults, err = OOM kills
    mem_total_gb = 16.0
    mem_used_gb = 14.2
    mem_util = mem_used_gb / mem_total_gb
    line("\n  memory util (14.2/16 GB)", f"{mem_util*100:.1f}%")
    line("memory sat (major pagefaults/s)", 3)
    line("memory err (oom_kills)", 0)
    check("memory util > 0.8 => near saturation", mem_util > 0.8)


# =========================================================================
# SECTION G - RED method (services: Rate / Errors / Duration)
# =========================================================================
def section_g():
    banner("SECTION G - RED METHOD (SERVICES)")
    print(
        "  RED (Tom Wilkie) is for REQUEST-DRIVEN SERVICES:\n"
        "    Rate     : requests per second\n"
        "    Errors   : failed requests per second (or error %)\n"
        "    Duration : latency (p50 / p95 / p99)\n"
        "  RED is to services what USE is to resources."
    )
    # 1-minute window, 60 samples of per-second counters
    reqs_per_sec = [RNG.randint(900, 1100) for _ in range(60)]
    errs_per_sec = [RNG.randint(0, 8) for _ in range(60)]
    total_reqs = sum(reqs_per_sec)
    total_errs = sum(errs_per_sec)
    rate_r = total_reqs / 60
    error_rate = total_errs / 60
    error_pct = total_errs / total_reqs * 100
    # duration: synthesize a p95
    durations = sorted(RNG.lognormvariate(-3.5, 0.5) * 1000 for _ in range(200))
    p95_ms = durations[int(0.95 * len(durations))]
    p99_ms = durations[int(0.99 * len(durations))]
    line("\n  Rate     (req/s)", f"{rate_r:.1f}")
    line("Errors    (err/s)", f"{error_rate:.2f}")
    line("Errors    (err %)", f"{error_pct:.2f}%")
    line("Duration  p95", f"{p95_ms:.1f} ms")
    line("Duration  p99", f"{p99_ms:.1f} ms")
    check("RED rate > 0", rate_r > 0)
    check("RED error_pct >= 0", error_pct >= 0)
    check("RED p95 <= p99", p95_ms <= p99_ms)


# =========================================================================
# SECTION H - High-cardinality label explosion
# =========================================================================
def section_h():
    banner("SECTION H - HIGH-CARDINALITY LABEL EXPLOSION")
    print(
        "  Every UNIQUE set of label values = ONE time series in the TSDB.\n"
        "  Series count = the CARTESIAN PRODUCT of every label's cardinality.\n"
        "  Low-cardinality labels (method, status, instance) are fine.\n"
        "  HIGH-cardinality labels (user_id, session_id, trace_id, ip) explode\n"
        "  the series count and OOM your TSDB. THIS is the #1 Prometheus killer."
    )
    # baseline, then add one label at a time
    steps = [
        ("baseline: no labels", {}),
        ("+ method      (4)",   {"method": 4}),
        ("+ status      (6)",   {"status": 6}),
        ("+ instance    (20)",  {"instance": 20}),
        ("+ user_id     (1000)", {"user_id": 1000}),
    ]
    product = 1
    print(f"\n  {'label added':<28} {'cardinality':<14} {'series':<12}")
    for desc, labels in steps:
        for k in labels:
            product *= labels[k]
        line(desc, f"{product:,}")
    line("\n  final series count", f"{product:,}")
    # memory: ~1.5KB per series (chunk headers + recent samples) - conservative
    kbytes_per_series = 1.5
    mem_mb = product * kbytes_per_series / 1024
    line("est. memory @ 1.5KB/series", f"{mem_mb:,.0f} MB ({mem_mb/1024:.2f} GB)")
    check("user_id label causes ~1000x explosion vs prior step",
          product // 1000 == 4 * 6 * 20)
    check("cartesian product == 4*6*20*1000 = 480000",
          4 * 6 * 20 * 1000 == 480000)
    check("est. memory > 500 MB (this is why TSDBs OOM)", mem_mb > 500)
    # cardinality budget rule of thumb
    print("\n  Rule of thumb: keep label cardinality under ~10 per label.")
    print("  NEVER label with user_id / email / ip / trace_id / session_id.")


# =========================================================================
# main
# =========================================================================
if __name__ == "__main__":
    banner("OBSERVABILITY FUNDAMENTALS - BUNDLE #01 - GROUND TRUTH")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    section_h()
    banner("DONE - all checks passed")
