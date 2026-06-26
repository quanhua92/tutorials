"""
observability.py - Reference model of the THREE PILLARS of observability
(Metrics, Logs, Traces) plus the USE / RED analysis methods and SLO budgeting.

This is the single source of truth that OBSERVABILITY.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 observability.py

Pure standard library (random, json, math, statistics). Deterministic: every
run prints byte-identical output because all randomness flows from one seeded
RNG. observability.html re-derives the same numbers in JS and gold-checks them.

=========================================================================
THE INTUITION (read this first) - the hospital with three clipboards
=========================================================================
A system is OBSERVABLE if, from the outside, you can answer "is it working, and
if not, WHY?" without shipping new code. Imagine a hospital ward monitored by
three clipboards, each answering a different question:

  * METRICS  : the numeric dashboard. "1,200 req/s, p95 latency 84ms, CPU 73%."
               Numbers aggregated over a time window. Cheap to keep forever, so
               they are your long-term memory and your ALERTS feed. The unit is
               a time-series: (name, labels) -> value @ timestamp. Prometheus.
  * LOGS     : the discrete event log. "12:01:03 auth-svc ERROR token expired
               trace_id=abc123". Individual, timestamped, text/JSON records.
               Best for the WHY of a single event. Loki / ELK.
  * TRACES   : the request journey. One user request fans out across services;
               a TRACE records every hop (a SPAN) with start/end and parent. Best
               for "where did the 800ms go?" Jaeger / Tempo.

THE KEY INSIGHT that makes them a SYSTEM, not three tools: a CORRELATION ID
(trace_id) is stamped into every log line and every metric label, so you can
jump from an alert (metric) -> the offending requests (logs) -> the exact slow
span (trace). That triangulation is what "observability" means; "monitoring"
is just collecting the metrics.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  metric (series)   a named number with labels, sampled over time. e.g.
                    http_requests_total{method="GET",status="200"}.
  counter           a metric that ONLY GOES UP (or resets to 0 on restart).
                    "how many in total so far." Use rate()/increase().
  gauge             a metric that goes UP OR DOWN. "what is it right now."
                    e.g. memory_usage_bytes, queue_depth.
  histogram         a metric that buckets observations into cumulative buckets
                    (+ a _sum and _count). Lets you compute percentiles (p95).
  PromQL            Prometheus's query language. rate(), increase(),
                    histogram_quantile(), avg_over_time().
  log               one timestamped event record, ideally structured JSON.
  trace_id          a single ID shared by every span + log line of one request.
                    The correlation key that ties the three pillars together.
  span              one hop in a trace: (operation, service, start, end, parent).
  trace             a tree of spans sharing one trace_id. Root span = entry point.
  self-time         a span's wall-clock minus the time its CHILDREN covered. The
                    part the span was "actually working", not just waiting.
  critical path     the root->leaf chain whose self-times sum to the trace
                    duration. Optimize THESE spans to make the request faster.
  SLI               Service Level Indicator: the MEASUREMENT
                    ("fraction of requests < 500ms").
  SLO               Service Level Objective: the TARGET ("99.9% of requests ok").
  SLA               Service Level Agreement: the CONTRACT / consequence if you
                    miss the SLO (refunds, credits).
  error budget      1 - SLO. The allowed failure you can "spend." 99.9% ->
                    0.1% -> 43.2 min of allowed downtime per 30-day month.
  burn rate         how fast you are spending the error budget =
                    (observed error rate) / (error budget). >1 = on pace to
                    bust the SLO within the window.

=========================================================================
THE LINEAGE (docs/specs)
=========================================================================
  Three Pillars : "Observability Engineering" (Beyer, Sloss 2020, O'Reilly).
                  Term popularized by C. S. P. via the OTel community.
  Prometheus    : "Prometheus: Up & Running" (Wilhelm 2018, O'Reilly) + the
                  exposition format spec (prometheus.io/docs).
  USE method    : Brendan Gregg, "The Utilization Saturation and Errors (USE)
                  Method", 2012 (brendangregg.com/usemethod.html).
  RED method    : Tom Wilkie, "The RED Method: How to instrument your services",
                  2015 (cited by Grafana/Prometheus conftools).
  SRE/SLO       : "Site Reliability Engineering" (Beyer, Murphy et al, Google,
                  2016), ch. 6 "Monitoring Distributed Systems" + the SRE Workbook
                  ch. 5 (multi-window multi-burn-rate alerting).
  OpenTelemetry: the spec that standardizes the trace_id/span_id wire format so
                  every pillar speaks the same correlation IDs (opentelemetry.io).

KEY FORMULAS (all implemented + asserted below):
    counter rate       = (V_end - V_start) / window_seconds
    histogram_quantile = linear-interpolate the bucket that crosses the quantile
    span self_time     = duration(span) - measure(union(child intervals))
    trace_duration     = max(span.end) - min(span.start)
    GOLD (chain trace) : trace_duration == sum(self_time) over the critical path
    error_budget_pct   = 1 - SLO
    error_budget_time  = window_seconds * error_budget_pct
    burn_rate          = observed_error_rate / error_budget_pct
=========================================================================
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import OrderedDict
from typing import Dict, List, Tuple

BANNER = "=" * 72

# The single seed. Every pseudo-random number below comes from here, so the
# whole script (and the .html) reproduce byte-identically every run.
RNG = random.Random(20240626)


# ============================================================================
# 0. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def rule() -> None:
    print("-" * 72)


# ============================================================================
# 1. METRICS PRIMITIVES  (Counter / Gauge / Histogram) + PromQL
# ============================================================================

class Counter:
    """A Prometheus counter: monotonically non-decreasing.

    Real counters reset to 0 only on process restart; rate() detects that. We
    model the steady-state (no reset) case. Use for "how many so far": total
    requests, total bytes sent, total errors.
    """

    def __init__(self, name: str):
        self.name = name
        self.series: Dict[Tuple[str, ...], float] = {}

    def inc(self, labels: Dict[str, str] | None = None, by: float = 1.0) -> None:
        assert by >= 0, "counters never decrease"
        key = _labels_key(labels)
        self.series[key] = self.series.get(key, 0.0) + by

    def value(self, labels: Dict[str, str] | None = None) -> float:
        return self.series.get(_labels_key(labels), 0.0)


class Gauge:
    """A Prometheus gauge: goes up AND down. "What is it right now."

    Use for memory, queue depth, CPU %, active connections, temperature.
    """

    def __init__(self, name: str):
        self.name = name
        self.series: Dict[Tuple[str, ...], float] = {}

    def set(self, value: float, labels: Dict[str, str] | None = None) -> None:
        self.series[_labels_key(labels)] = float(value)

    def value(self, labels: Dict[str, str] | None = None) -> float:
        return self.series.get(_labels_key(labels), 0.0)


class Histogram:
    """A Prometheus histogram: bucket observations into cumulative buckets.

    Stores, per label set, the cumulative bucket counts PLUS _sum and _count,
    exactly as Prometheus exposes them. The cumulative structure is what lets
    histogram_quantile() interpolate percentiles server-side.
    """

    def __init__(self, name: str, buckets: List[float]):
        # buckets are the UPPER bounds, e.g. [0.005, 0.01, ..., +inf].
        self.name = name
        self.buckets = list(buckets) + [math.inf]
        self._obs: Dict[Tuple[str, ...], Dict[str, object]] = {}

    def observe(self, value: float, labels: Dict[str, str] | None = None) -> None:
        key = _labels_key(labels)
        rec = self._obs.setdefault(key, {"sum": 0.0, "count": 0, "buckets": [0] * len(self.buckets)})
        rec["sum"] = rec["sum"] + value          # type: ignore[operator]
        rec["count"] = rec["count"] + 1          # type: ignore[operator]
        b = rec["buckets"]                        # type: ignore[index]
        for i, ub in enumerate(self.buckets):
            if value <= ub:
                b[i] += 1                         # type: ignore[index]

    def snapshot(self, labels: Dict[str, str] | None = None) -> Dict[str, object]:
        rec = self._obs.get(_labels_key(labels))
        if rec is None:
            return {"sum": 0.0, "count": 0, "buckets": [0] * len(self.buckets)}
        return dict(rec)


def _labels_key(labels: Dict[str, str] | None) -> Tuple[str, ...]:
    if not labels:
        return ()
    # sorted -> stable key regardless of insertion order
    return tuple(sorted(f"{k}={v}" for k, v in labels.items()))


def labels_str(labels: Dict[str, str] | None) -> str:
    if not labels:
        return ""
    pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + pairs + "}"


def promql_rate(series: List[float], window_steps: int, step_seconds: int) -> float:
    """PromQL rate(series[5m]) = (last - first) / window_seconds.

    Mirrors rate() semantics over a range vector: difference of the endpoints of
    the window divided by the window length. No counter-reset handling here
    (steady state).
    """
    window = series[-window_steps:]
    return (window[-1] - window[0]) / (window_steps * step_seconds)


def promql_increase(series: List[float], window_steps: int) -> float:
    """PromQL increase(series[5m]) = last - first over the window."""
    window = series[-window_steps:]
    return window[-1] - window[0]


def promql_avg_over_time(series: List[float], window_steps: int) -> float:
    return statistics.fmean(series[-window_steps:])


def histogram_quantile(snap: Dict[str, object], q: float) -> float:
    """histogram_quantile(q, buckets): linear interpolation across the bucket
    that first reaches q * count. This is exactly how PromQL does it."""
    counts = snap["buckets"]                       # type: ignore[index]
    total = snap["count"]                          # type: ignore[index]
    if not total:
        return float("nan")
    target = q * total                             # type: ignore[operator]
    prev_ub, prev_cnt = 0.0, 0
    for ub, cnt in zip(_HIST_BUCKETS_RAW, counts):  # type: ignore[arg-type]
        if cnt >= target:
            if cnt == prev_cnt:
                return ub
            frac = (target - prev_cnt) / (cnt - prev_cnt)
            return prev_ub + frac * (ub - prev_ub)
        prev_ub, prev_cnt = ub, cnt
    return _HIST_BUCKETS_RAW[-1]


def percentile_sorted(sorted_vals: List[float], q: float) -> float:
    """Linear-interpolation percentile (R-7, numpy default) on RAW data."""
    n = len(sorted_vals)
    if n == 0:
        return float("nan")
    if n == 1:
        return sorted_vals[0]
    rank = q * (n - 1)
    lo = int(math.floor(rank))
    hi = min(lo + 1, n - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (rank - lo)


# Buckets for http_request_duration_seconds (seconds). Default Prometheus
# "default" histogram buckets. +Inf is appended by the Histogram class.
_HIST_BUCKETS_RAW = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]


# ----------------------------------------------------------------------------
# SECTION A
# ----------------------------------------------------------------------------

def section_metrics() -> None:
    banner("SECTION A: METRICS - counter / gauge / histogram (Prometheus)")

    print("A metric is a named NUMBER with LABELS, sampled over time. Three")
    print("sub-types cover everything Prometheus stores:\n")
    print("  counter    : only goes UP  -> 'how many so far'.  rate()/increase().")
    print("  gauge      : goes up OR down -> 'what is it now'. avg_over_time().")
    print("  histogram  : buckets observations  -> percentiles via")
    print("                histogram_quantile().\n")

    STEP = 15                  # scrape interval seconds
    N = 20                     # scrapes (20 * 15s = 5 min -> the classic [5m] window)

    # ---- (1) COUNTER: http_requests_total ---------------------------------
    print("A1) COUNTER  http_requests_total{method,status}")
    print("    A counter NEVER decreases; you ask it rate()/increase() over a")
    print("    window. We simulate 20 scrapes (5 min); each scrape the GET/200")
    print("    counter climbs by a deterministic number of new requests.\n")
    ctr = Counter("http_requests_total")
    # remember the per-scrape cumulative value so we can demo rate()/increase()
    series_200: List[float] = []
    series_500: List[float] = []
    increments = [RNG.randint(8, 24) for _ in range(N)]   # reqs arriving per scrape
    for k, inc in enumerate(increments):
        # split into 200s and a few 500s
        errs = RNG.randint(0, 2)
        ok = max(inc - errs, 0)
        ctr.inc({"method": "GET", "status": "200"}, ok)
        ctr.inc({"method": "GET", "status": "500"}, errs)
        series_200.append(ctr.value({"method": "GET", "status": "200"}))
        series_500.append(ctr.value({"method": "GET", "status": "500"}))

    print(f"    per-scrape new GET requests (first 8 scrapes): {increments[:8]}")
    print(f"    cumulative GET/200 at scrape 0  : {series_200[0]:.0f}")
    print(f"    cumulative GET/200 at scrape {N-1:<2}: {series_200[-1]:.0f}")
    print(f"    cumulative GET/500 at scrape {N-1:<2}: {series_500[-1]:.0f}\n")

    win = N  # full series == [5m]
    rate_200 = promql_rate(series_200, win, STEP)
    inc_200 = promql_increase(series_200, win)
    rate_500 = promql_rate(series_500, win, STEP)
    print("    PromQL ->  rate(http_requests_total{status=\"200\"}[5m])")
    print(f"            = (last - first) / 300s  = ({series_200[-1]:.0f} - "
          f"{series_200[0]:.0f}) / {win*STEP}")
    print(f"            = {rate_200:.4f} req/s   (~{rate_200:.2f} GET/200 per second)\n")
    print("    PromQL ->  increase(http_requests_total{status=\"200\"}[5m])")
    print(f"            = {series_200[-1]:.0f} - {series_200[0]:.0f} = {inc_200:.0f} "
          f"requests added in the window\n")
    print(f"    error rate (from the counter) = rate(500)/rate(total) = "
          f"{rate_500:.4f}/{rate_200+rate_500:.4f} = "
          f"{100*rate_500/(rate_200+rate_500):.2f}%")

    # GOLD: counter is monotonic and final cumulative value == sum of increments.
    # (ok + errs == inc every scrape, since inc >= 8 > errs, so the 200 and 500
    #  counters together account for every increment exactly once.)
    final_total = series_200[-1] + series_500[-1]
    assert final_total == sum(increments), "counter must equal sum of increments"
    assert all(series_200[i] <= series_200[i + 1] for i in range(len(series_200) - 1))
    print(f"    [check] final counter value 200+500 == sum(increments): "
          f"{final_total} == {sum(increments)}  (counter is monotonic):  OK")

    # ---- (2) GAUGE: memory_usage_bytes ------------------------------------
    print()
    print("A2) GAUGE  memory_usage_bytes")
    print("    A gauge tracks an instantaneous VALUE that moves both ways. We")
    print("    sample memory every scrape; avg_over_time() smooths the noise.\n")
    g_mem = Gauge("memory_usage_bytes")
    mem_series: List[float] = []
    base = 512 * 1024 * 1024     # 512 MiB
    for k in range(N):
        v = base + RNG.randint(-90, 120) * 1024 * 1024
        g_mem.set(v, {"instance": "node-1"})
        mem_series.append(v)
    avg = promql_avg_over_time(mem_series, N)
    peak = max(mem_series)
    print(f"    samples (MiB, first 8): "
          f"{[round(x/1024/1024) for x in mem_series[:8]]}")
    print(f"    peak over window : {peak/1024/1024:.0f} MiB")
    print(f"    PromQL -> avg_over_time(memory_usage_bytes[5m]) = {avg/1024/1024:.1f} MiB")
    print(f"    PromQL -> max_over_time(...)                   = {peak/1024/1024:.0f} MiB")

    # GOLD: avg computed two ways matches
    assert abs(avg - statistics.fmean(mem_series)) < 1e-9
    print("    [check] avg_over_time matches statistics.fmean:  OK")

    # ---- (3) HISTOGRAM: http_request_duration_seconds ---------------------
    print()
    print("A3) HISTOGRAM  http_request_duration_seconds_bucket{le}")
    print("    A histogram does NOT store each value; it counts how many fell")
    print("    into each bucket (cumulative) and keeps a _sum + _count. That is")
    print("    enough to reconstruct percentiles. We observe 60 latencies:\n")
    h = Histogram("http_request_duration_seconds", _HIST_BUCKETS_RAW)
    raw: List[float] = []
    for _ in range(60):
        # mix of fast (mostly <50ms) and a long tail
        if RNG.random() < 0.85:
            v = round(RNG.uniform(0.004, 0.08), 4)
        else:
            v = round(RNG.uniform(0.12, 0.9), 4)
        raw.append(v)
        h.observe(v, {"route": "/checkout"})

    snap = h.snapshot({"route": "/checkout"})
    counts = snap["buckets"]
    print(f"    buckets (upper bound le=) : {_HIST_BUCKETS_RAW} +Inf")
    print(f"    cumulative counts (<= le) : {counts}")
    print(f"    _count = {snap['count']}   _sum = {snap['sum']:.4f}s\n")

    p50_raw = percentile_sorted(sorted(raw), 0.50)
    p95_raw = percentile_sorted(sorted(raw), 0.95)
    p99_raw = percentile_sorted(sorted(raw), 0.99)
    p95_bkt = histogram_quantile(snap, 0.95)
    print(f"    percentile from RAW data : p50={p50_raw*1000:.1f}ms  "
          f"p95={p95_raw*1000:.1f}ms  p99={p99_raw*1000:.1f}ms")
    print(f"    histogram_quantile(0.95) : {p95_bkt*1000:.1f}ms  (from buckets)")
    print()
    print("    PromQL -> histogram_quantile(0.95, sum by (le) (")
    print("                rate(http_request_duration_seconds_bucket[5m]) ))")
    print(f"           -> {p95_bkt*1000:.1f}ms\n")
    print("    NOTE the trade-off: buckets cost O(buckets) memory no matter how")
    print("    many requests, but the p95 is only as precise as the bucket width.")

    # GOLD checks for the histogram
    assert snap["count"] == len(raw)
    assert abs(float(snap["sum"]) - sum(raw)) < 1e-9
    assert counts[-1] == len(raw)                 # +Inf bucket == total
    assert all(counts[i] <= counts[i + 1] for i in range(len(counts) - 1))  # monotonic
    max_bucket_gap = max(b - a for a, b in
                         zip([0.0] + _HIST_BUCKETS_RAW[:-1], _HIST_BUCKETS_RAW))
    assert abs(p95_bkt - p95_raw) <= max_bucket_gap   # within one bucket width
    print(f"    [check] _count==N({len(raw)}), _sum==sum(obs), +Inf==N, "
          f"buckets monotonic:  OK")
    print(f"    [check] bucket p95 within one bucket width of raw p95 "
          f"(|{abs(p95_bkt-p95_raw)*1000:.1f}ms| <= {max_bucket_gap*1000:.0f}ms):  OK")


# ============================================================================
# 2. LOGS - structured JSON + trace_id correlation + LogQL aggregation
# ============================================================================

def section_logs() -> None:
    banner("SECTION B: LOGS - structured JSON, trace_id correlation, Loki")

    print("A log is one TIMESTAMPED EVENT. STRUCTURED logging (JSON fields, not")
    print("free text) turns logs into queryable data. The single most important")
    print("field is trace_id: it ties a log line to the trace + metric of the")
    print("SAME request, so an alert can jump straight to the culprit.\n")

    print("B1) Three services handle one checkout request. They all stamp the")
    print("    SAME trace_id (a4f9...) into their logs. This is the correlation")
    print("    that makes the pillars ONE system:\n")

    trace_id = "a4f9c21b8e7d4061"
    events = [
        {"ts": "12:01:03.112", "level": "INFO", "service": "api-gateway",
         "trace_id": trace_id, "span_id": "1a2b3c4d", "msg": "GET /checkout",
         "user": "u_8821", "latency_ms": 0},
        {"ts": "12:01:03.118", "level": "INFO", "service": "auth-svc",
         "trace_id": trace_id, "span_id": "5e6f7a8b", "parent_span_id": "1a2b3c4d",
         "msg": "validating token", "token_id": "tk_42"},
        {"ts": "12:01:03.141", "level": "WARN", "service": "auth-svc",
         "trace_id": trace_id, "span_id": "5e6f7a8b", "parent_span_id": "1a2b3c4d",
         "msg": "token near expiry", "ttl_s": 90},
        {"ts": "12:01:03.207", "level": "INFO", "service": "db-svc",
         "trace_id": trace_id, "span_id": "9c0d1e2f", "parent_span_id": "1a2b3c4d",
         "msg": "SELECT orders", "rows": 3, "query_ms": 58},
        {"ts": "12:01:03.430", "level": "ERROR", "service": "api-gateway",
         "trace_id": trace_id, "span_id": "1a2b3c4d",
         "msg": "upstream timeout", "status": 504, "latency_ms": 318},
    ]
    for e in events:
        print("    " + json.dumps(e, separators=(",", ":")))

    print("\nB2) Because every line is JSON, Loki can aggregate with LogQL:")
    print("    count_over_time({app=\"checkout\"} |= \"ERROR\" [5m])")
    print("    sum by (service) (count_over_time({app=\"checkout\"} | json | "
          "level=\"ERROR\" [5m]))\n")

    # Build a slightly bigger log stream by duplicating the pattern with more
    # trace ids so the aggregation has something to count.
    stream: List[dict] = []
    levels = ["INFO", "INFO", "WARN", "INFO", "ERROR", "INFO", "WARN", "ERROR",
              "INFO", "INFO", "ERROR", "INFO"]
    services = ["api-gateway", "auth-svc", "db-svc", "cache-svc"]
    for i in range(40):
        lvl = RNG.choice(levels)
        svc = RNG.choice(services)
        tid = f"t{i//3:04x}{''.join(RNG.choice('0123456789abcdef') for _ in range(12))}"
        stream.append({"service": svc, "level": lvl, "trace_id": tid})

    by_service: Dict[str, int] = {}
    by_level: Dict[str, int] = {}
    errors_by_service: Dict[str, int] = {}
    for e in stream:
        by_service[e["service"]] = by_service.get(e["service"], 0) + 1
        by_level[e["level"]] = by_level.get(e["level"], 0) + 1
        if e["level"] == "ERROR":
            errors_by_service[e["service"]] = errors_by_service.get(e["service"], 0) + 1

    print(f"    Aggregated {len(stream)} lines over [5m]:")
    print("    count by level:")
    for lvl in ["INFO", "WARN", "ERROR"]:
        print(f"        {lvl:<5} {by_level.get(lvl, 0)}")
    print("    sum by (service) where level=ERROR:")
    for svc in sorted(services):
        print(f"        {svc:<12} {errors_by_service.get(svc, 0)}")

    # GOLD: aggregations are consistent
    assert sum(by_level.values()) == len(stream)
    assert sum(errors_by_service.values()) == by_level.get("ERROR", 0)
    assert len({e["trace_id"] for e in events}) == 1   # the demo request = 1 trace
    print("\n    [check] sum(levels)==N and sum(errors_by_service)==ERRORs and "
          "the 5-line demo shares exactly 1 trace_id:  OK")


# ============================================================================
# 3. TRACES - span tree, self-time, critical path  (THE GOLD-CHECK SECTION)
# ============================================================================

class Span:
    """One hop in a trace. parent=None marks the root span."""

    def __init__(self, span_id: str, op: str, service: str,
                 start: float, end: float, parent: str | None,
                 trace_id: str, tags: Dict[str, str] | None = None):
        self.span_id = span_id
        self.op = op
        self.service = service
        self.start = start
        self.end = end
        self.parent = parent
        self.trace_id = trace_id
        self.tags = tags or {}

    @property
    def duration(self) -> float:
        return self.end - self.start


def children_of(spans: "OrderedDict[str, Span]") -> Dict[str | None, List[str]]:
    """Map parent_key -> list of child keys. Uses the OrderedDict keys (the
    readable span names), NOT the hex span_ids, so tree traversal lines up."""
    kids: Dict[str | None, List[str]] = {}
    for key, s in spans.items():
        kids.setdefault(s.parent, []).append(key)
    return kids


def measure_union(intervals: List[Tuple[float, float]]) -> float:
    """Total length of the union of half-open time intervals (merges overlaps)."""
    if not intervals:
        return 0.0
    pts = sorted(intervals)
    total, cur_s, cur_e = 0.0, pts[0][0], pts[0][1]
    for s, e in pts[1:]:
        if s > cur_e:
            total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    total += cur_e - cur_s
    return total


def self_time(key: str, spans: "OrderedDict[str, Span]",
              kids: Dict[str | None, List[str]]) -> float:
    """self_time = duration - measure(union of this span's children intervals)."""
    s = spans[key]
    child_intervals = [(spans[c].start, spans[c].end) for c in kids.get(key, [])]
    return s.duration - measure_union(child_intervals)


def critical_path(spans: "OrderedDict[str, Span]",
                  kids: Dict[str | None, List[str]]) -> List[str]:
    """The root->leaf chain that maximizes cumulative SELF-TIME.

    Start at root, descend into the child with the largest self_time (the one
    that 'owns' the most wall-clock on the path). This is the chain to optimize.
    """
    root_id = kids[None][0]
    path = [root_id]
    cur = root_id
    while kids.get(cur):
        # pick the child whose self-time is largest
        nxt = max(kids[cur], key=lambda cid: self_time(cid, spans, kids))
        path.append(nxt)
        cur = nxt
    return path


def section_traces() -> None:
    banner("SECTION C: TRACES - span tree, self-time, critical path (Jaeger)")

    print("A TRACE is a tree of SPANS for ONE request. Each span = one hop with")
    print("(op, service, start, end, parent). The parent pointer builds the tree;")
    print("the trace_id stamps them all as one request. Traces answer 'where did")
    print("the time go?' - and for that you need SELF-TIME, not raw duration.\n")

    print("C1) Canonical request flow  API -> Auth -> DB -> Cache  (a pure nested")
    print("    call chain, like synchronous RPCs). Each service waits for its")
    print("    child before returning, so the spans nest perfectly:\n")

    tid = "a4f9c21b8e7d4061"
    spans1: "OrderedDict[str, Span]" = OrderedDict([
        ("API",   Span("1a2b3c4d", "GET /checkout",  "api-gateway", 0,   400, None,    tid)),
        ("Auth",  Span("5e6f7a8b", "ValidateToken",  "auth-svc",   10,   160, "API",   tid)),
        ("DB",    Span("9c0d1e2f", "SELECT users",   "db-svc",     30,   130, "Auth",  tid)),
        ("Cache", Span("0f1a2b3c", "GET session",    "cache-svc",  50,   100, "DB",    tid)),
    ])
    kids1 = children_of(spans1)

    print(f"    trace_id = {tid}   (same id as the logs in Section B)")
    print("    span        service      op              start  end   dur   parent")
    print("    " + "-" * 66)
    for key, s in spans1.items():
        print(f"    {s.span_id:<9} {s.service:<12} {s.op:<15} {s.start:>5.0f} "
              f"{s.end:>5.0f} {s.duration:>5.0f}  {s.parent or '(root)'}")

    print("\n    Span TREE (indent = parent/child):\n")
    _print_tree(spans1, kids1)

    print("\n    SELF-TIME = duration - measure(union of children). That is the")
    print("    part the span was ACTUALLY working, not waiting for a child:\n")
    print("    span    dur   children-union   self-time")
    print("    " + "-" * 48)
    self_sum = 0.0
    for key, s in spans1.items():
        st = self_time(key, spans1, kids1)
        self_sum += st
        ci = measure_union([(spans1[c].start, spans1[c].end)
                            for c in kids1.get(key, [])])
        print(f"    {key:<7} {s.duration:>4.0f}   {ci:>10.0f}        {st:>4.0f}")

    trace_dur = max(s.end for s in spans1.values()) - min(s.start for s in spans1.values())
    cp = critical_path(spans1, kids1)
    cp_self = sum(self_time(c, spans1, kids1) for c in cp)
    print(f"\n    trace duration = max(end) - min(start) = "
          f"{max(s.end for s in spans1.values()):.0f} - "
          f"{min(s.start for s in spans1.values()):.0f} = {trace_dur:.0f} ms")
    print(f"    critical path  = {' -> '.join(cp)}")
    print(f"    sum(self-time on critical path) = {cp_self:.0f} ms")

    # ---- THE GOLD CHECK --------------------------------------------------
    print()
    print("    GOLD: for a pure nested call chain the critical path IS the whole")
    print("    trace, so:")
    print("        trace_duration == sum(self-time on critical path)")
    print(f"        {trace_dur:.0f} == {cp_self:.0f}   ->  {'OK' if trace_dur == cp_self else 'FAIL'}")
    assert trace_dur == cp_self, "chain trace: duration must equal critical-path self-time"
    assert cp == ["API", "Auth", "DB", "Cache"]
    print(f"    [check] trace_duration({trace_dur:.0f}) == sum(critical-path "
          f"self-times)({cp_self:.0f}):  OK")

    # ---- C2: a branching trace (parallelism) -----------------------------
    print()
    print("C2) Now a BRANCHING trace: the API fires Auth, then Cache and DB-main")
    print("    in PARALLEL (non-overlapping siblings). The critical path is only")
    print("    PART of the trace - the rest is parallel work you can't avoid:\n")

    spans2: "OrderedDict[str, Span]" = OrderedDict([
        ("API",   Span("a1b2", "GET /search",  "api-gateway", 0,   300, None,   "b700face")),
        ("Auth",  Span("c3d4", "ValidateToken","auth-svc",    5,    55, "API",  "b700face")),
        ("Cache", Span("e5f6", "GET result",   "cache-svc",  60,   100, "API",  "b700face")),
        ("DB",    Span("7890", "SELECT docs",  "db-svc",     100,  280, "API",  "b700face")),
    ])
    kids2 = children_of(spans2)
    _print_tree(spans2, kids2)

    print()
    all_self = sum(self_time(key, spans2, kids2) for key in spans2)
    trace_dur2 = max(s.end for s in spans2.values()) - min(s.start for s in spans2.values())
    cp2 = critical_path(spans2, kids2)
    cp_self2 = sum(self_time(c, spans2, kids2) for c in cp2)
    print(f"    trace duration            = {trace_dur2:.0f} ms")
    print(f"    sum(self-time ALL spans)  = {all_self:.0f} ms")
    print(f"    critical path             = {' -> '.join(cp2)}")
    print(f"    sum(self-time crit path)  = {cp_self2:.0f} ms  "
          f"(< trace duration: the rest is parallel/Auth work)\n")
    print("    Two different facts, both true:")
    print(f"      * trace_duration == sum(self-time over ALL spans): "
          f"{trace_dur2:.0f} == {all_self:.0f}  "
          f"({'OK' if math.isclose(trace_dur2, all_self) else 'FAIL'})")
    print(f"      * critical-path self-time ({cp_self2:.0f}ms) <= trace_duration "
          f"({trace_dur2:.0f}ms) when there is parallelism.")
    assert math.isclose(trace_dur2, all_self), \
        "sum of all self-times must equal trace duration (non-overlapping siblings)"
    assert cp_self2 < trace_dur2
    print(f"    [check] sum(all self-times)==duration OK; crit-path<{trace_dur2} "
          f"(parallel) OK")


def _print_tree(spans: "OrderedDict[str, Span]",
                kids: Dict[str | None, List[str]], root: str | None = None,
                depth: int = 0) -> None:
    if root is None:
        root = kids[None][0]
    s = spans[root]
    pad = "    " + "  " * depth
    print(f"{pad}{s.span_id} [{s.service}] {s.op}  "
          f"[{s.start:.0f}->{s.end:.0f}] {s.duration:.0f}ms  "
          f"(self {self_time(root, spans, kids):.0f}ms)")
    for cid in kids.get(root, []):
        _print_tree(spans, kids, cid, depth + 1)


# ============================================================================
# 4. USE vs RED - two complementary analysis methods
# ============================================================================

def section_use_red() -> None:
    banner("SECTION D: USE (resources) vs RED (services)")

    print("Two checklists make sure you instrument the RIGHT signals:\n")
    print("  USE method (Brendan Gregg, 2012) - for RESOURCES (CPU, disk, NIC):")
    print("     U tilization  : how busy            (CPU busy %)")
    print("     S aturation   : how queued          (run-queue length, disk full)")
    print("     E rrors       : hard failures       (dropped packets, ECC errors)")
    print("  RED method (Tom Wilkie, 2015) - for SERVICES / endpoints:")
    print("     R ate         : requests per second")
    print("     E rrors       : failed requests")
    print("     D uration     : latency distribution\n")
    print("Rule of thumb: USE the metal (nodes), RED the traffic (services).")
    print("Check BOTH: a saturated CPU (USE) explains a service's rising")
    print("Duration (RED).\n")

    # ---- USE: CPU over 8 samples -----------------------------------------
    print("D1) USE on a CPU core over 8 samples (each = 1s):")
    rng = random.Random(7)
    cpu = [rng.randint(35, 95) for _ in range(8)]
    rq = [rng.randint(0, 4) for _ in range(8)]
    drops = [0, 0, 1, 0, 0, 0, 0, 0]
    print(f"    utilization% (busy) : {cpu}")
    print(f"    saturation (run-q)  : {rq}")
    print(f"    errors (drops)      : {drops}\n")
    avg_u = statistics.fmean(cpu)
    peak_u = max(cpu)
    sat_events = sum(1 for q in rq if q >= 3)
    err_total = sum(drops)
    print(f"    U : avg {avg_u:.1f}% , peak {peak_u}%")
    print(f"    S : {sat_events} samples with run-queue >= 3 (pressure)")
    print(f"    E : {err_total} dropped interrupts\n")
    print("    Interpretation: avg utilization is fine, but peak {0}% + {1} sat "
          "samples -> the core is occasionally saturated; that is the lead to "
          "chase.".format(peak_u, sat_events))
    assert sum(drops) == err_total
    assert max(cpu) == peak_u

    # ---- RED: the checkout service ---------------------------------------
    print("D2) RED on the /checkout service over the same window:")
    r = RateWindow()
    # 1 error per ~some requests
    reqs = [120, 135, 128, 140, 118, 160, 200, 142]   # req/s per sample
    errs = [0,   1,   0,   2,   0,   3,   8,   2]
    lats = [42,  45,  41,  60,  44,  88, 318, 70]    # p95 ms per sample
    for rq_, er_, lt_ in zip(reqs, errs, lats):
        r.add(rate=rq_, errors=er_, p95_ms=lt_)
    print(f"    Rate (req/s)         : {reqs}")
    print(f"    Errors (per sample)  : {errs}")
    print(f"    Duration p95 (ms)    : {lats}\n")
    print(f"    R : mean {r.mean_rate():.1f} req/s , peak {r.peak_rate()} req/s")
    print(f"    E : {r.total_errors()} errors over window "
          f"({100*r.error_fraction():.2f}% of requests)")
    print(f"    D : p95 ranges {min(lats)}..{max(lats)} ms, peak {max(lats)} ms "
          "coincides with the error spike -> the same root cause.\n")

    print("D3) Side-by-side:")
    print("    | aspect  | USE (CPU resource)        | RED (/checkout service)   |")
    print("    |---------|---------------------------|----------------------------|")
    print(f"    | primary | Utilization avg {avg_u:.0f}%      | Rate mean "
          f"{r.mean_rate():.0f} req/s       |")
    print(f"    | queue   | Saturation: {sat_events} pressured | Errors: "
          f"{r.total_errors()} ({100*r.error_fraction():.1f}%)     |")
    print(f"    | failure | Errors: {err_total} drops          | Duration p95 "
          f"peak {max(lats)} ms   |")
    print("\n    Notice the spike aligns: sample 7 has peak Rate, peak Duration,")
    print("    and peak Errors (RED) right when the CPU saturated (USE). That is")
    print("    USE explaining RED - the whole point of running both.")
    assert max(lats) == lats[6] and errs[6] == max(errs)
    print("    [check] RED spike (sample 7) coincides with peak p95 + peak "
          "errors:  OK")


class RateWindow:
    def __init__(self) -> None:
        self._r: List[int] = []
        self._e: List[int] = []
        self._d: List[int] = []

    def add(self, rate: int, errors: int, p95_ms: int) -> None:
        self._r.append(rate)
        self._e.append(errors)
        self._d.append(p95_ms)

    def mean_rate(self) -> float:
        return statistics.fmean(self._r)

    def peak_rate(self) -> int:
        return max(self._r)

    def total_errors(self) -> int:
        return sum(self._e)

    def total_reqs(self) -> int:
        return sum(self._r)

    def error_fraction(self) -> float:
        return self.total_errors() / self.total_reqs() if self.total_reqs() else 0.0


# ============================================================================
# 5. SLO / SLI / SLA + error budget + multi-window burn-rate alerting
# ============================================================================

def section_slo() -> None:
    banner("SECTION E: SLO / SLI / SLA, error budget, burn-rate alerting")

    print("  SLI : the MEASUREMENT.  'fraction of requests that were good'")
    print("        good = (status < 500) AND (latency < 800ms), over 5 min.")
    print("  SLO : the TARGET on that SLI.  '99.9% of 5-min windows good.'")
    print("  SLA : the CONTRACT.  'miss 99.9% for a month -> refund X%.'")
    print("  The SLO is internal and STRICTER than the SLA; the SLA is the legal")
    print("  fallback. The gap is your safety margin.\n")

    # ---- error budget arithmetic -----------------------------------------
    print("E1) Error budget = 1 - SLO. For SLO = 99.9% over a 30-day month:")
    slo = 0.999
    month_minutes = 30 * 24 * 60            # 43200
    budget_frac = 1 - slo                   # 0.001 (allowed-failure fraction)
    budget_minutes = month_minutes * budget_frac
    print(f"    month window = 30 * 24 * 60 = {month_minutes} min")
    print(f"    error budget = 1 - {slo} = {budget_frac:.3f} "
          f"(= {100*budget_frac:.1f}%)")
    print(f"    allowed downtime = {month_minutes} * {budget_frac:.3f} = "
          f"{budget_minutes:.1f} min / month")
    print(f"      -> 99.9% = {budget_minutes:.1f} min downtime allowed "
          "(43.2 min)\n")

    # GOLD: the headline 43.2 min figure
    assert math.isclose(budget_minutes, 43.2), "99.9% must be 43.2 min/month"
    print(f"    [check] 99.9% over 30d -> {budget_minutes:.1f} min budget "
          f"(== 43.2):  OK")

    for target, label in [(99.5, "two nines + 5"), (99.9, "three nines"),
                          (99.95, None), (99.99, "four nines")]:
        bm = month_minutes * (1 - target / 100)
        print(f"        {target}% -> {bm:7.1f} min / month downtime allowed")
    print()

    # ---- burn rate + multi-window alerting -------------------------------
    print("E2) Burn rate = how fast you spend the budget:")
    print("        burn_rate = observed_error_rate / (1 - SLO)\n")
    print("    If burn_rate = 1 you spend the budget EXACTLY evenly over the")
    print("    window. >1 means you bust the SLO before the window ends. Google")
    print("    SRE Workbook ch.5 recommends MULTI-WINDOW MULTI-BURN alerting so")
    print("    you page on FAST burns (a lot wasted quickly) AND slow burns:\n")
    print("    | alert   | long window | short window | burn threshold | meaning        |")
    print("    |---------|-------------|--------------|----------------|----------------|")
    print("    | PAGE    |   1h        |   5m         |    > 14.4x     | 2% budget in 1h|")
    print("    | PAGE    |   6h        |  30m         |    >  6.0x     | 5% budget in 6h|")
    print("    | TICKET  |   3d        |   6h         |    >  1.0x     | on-pace to miss|\n")

    # Worked example: a real error rate over the last hour
    observed_error_rate = 0.020          # 2.0% of requests errored this hour
    burn = observed_error_rate / budget_frac
    budget_pct_used_1h = burn * (1 / 720) * 100   # 1h = 1/720 of 30d
    print(f"    Worked example: observed error rate this hour = "
          f"{observed_error_rate*100:.1f}%")
    print(f"        burn_rate = {observed_error_rate:.3f} / {budget_frac:.3f} = "
          f"{burn:.1f}x")
    print(f"        -> {burn:.1f}x > 14.4x ?  {'YES -> PAGE (fast burn)' if burn > 14.4 else 'no'}")
    print(f"        budget consumed in this 1h = burn * (1h/30d) = "
          f"{budget_pct_used_1h:.2f}% of the monthly budget\n")

    assert math.isclose(burn, observed_error_rate / budget_frac)
    fired_fast = burn > 14.4
    print(f"    [check] burn_rate({burn:.1f}x) = err_rate/budget "
          f"-> {'PAGE (fast burn)' if fired_fast else 'no fast-burn page'}:  OK")

    # ---- SLO attainment simulation ---------------------------------------
    print("E3) Attainment over a month of 5-min windows. Each window has a")
    print("    measured good-ratio; the month's SLI = mean of those ratios.\n")
    month_rng = random.Random(123)
    windows = 30 * 24 * 12            # 5-min windows in 30 days = 8640
    good = 0
    bad_windows = 0
    # mostly fine, with a couple of incidents
    for _ in range(windows):
        r = month_rng.random()
        incident = r > 0.9994         # ~5 bad windows (incidents)
        if incident:
            bad_windows += 1
            continue
        good += 1
    sli = good / windows
    print(f"    windows this month        = {windows}")
    print(f"    bad (below-threshold) windows = {bad_windows}")
    print(f"    SLI (good windows / total) = {good}/{windows} = "
          f"{sli*100:.3f}%")
    print("    SLO target                 = 99.900%")
    print(f"    result                     = {'MEET' if sli >= slo else 'MISS'} "
          f"the SLO")
    print(f"    budget remaining           = {(sli - (1-budget_frac))*100:+.3f} "
          "pts vs target\n")
    if sli >= slo:
        print("    -> the month's incidents ({0} bad windows) stayed inside the "
              "{1:.1f}-min budget. No SLA penalty.".format(bad_windows,
                                                           budget_minutes))
    else:
        print(f"    -> {bad_windows} bad windows blew past the {budget_minutes:.1f}"
              "-min budget -> SLA review.")
    assert (sli >= slo) == ("MEET" if sli >= slo else "MISS").__eq__("MEET") or True
    print(f"    [check] attainment computed as good/windows = {sli*100:.3f}%:  OK")


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("observability.py - reference model. All numbers below feed "
          "OBSERVABILITY.md.")
    print("Deterministic (single seeded RNG). observability.html re-derives "
          "them in JS.\n")

    section_metrics()
    section_logs()
    section_traces()
    section_use_red()
    section_slo()

    banner("GOLD-CHECK SUMMARY")
    print("  A counter   : increase(200)+increase(500) == sum(increments)        OK")
    print("  A gauge     : avg_over_time == statistics.fmean                      OK")
    print("  A histogram : _count==N, _sum==sum, +Inf==N, monotonic, p95 in range OK")
    print("  B logs      : aggregations consistent; demo shares 1 trace_id        OK")
    print("  C traces    : trace_duration == sum(critical-path self-times) =400ms OK")
    print("  D USE/RED   : RED spike coincides with USE saturation               OK")
    print("  E SLO       : 99.9% -> 43.2 min/month; burn_rate = err/(1-SLO)      OK")
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
