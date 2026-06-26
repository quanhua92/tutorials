# Observability — Metrics, Logs, Traces (the three pillars)

> The single source of truth for every number below is **`observability.py`**.
> Run `python3 observability.py` and the output is pasted verbatim into this
> guide (`observability_output.txt`). Nothing here is hand-computed.
> Interactive version: **`observability.html`** — recomputes the trace
> gold-check live in JS.

## 0. The intuition — the hospital with three clipboards

A system is **observable** if, from the outside, you can answer *"is it working,
and if not, WHY?"* without shipping new code. Imagine a hospital ward watched by
three clipboards, each answering a different question:

| Pillar | Question it answers | Unit | Best at | Tool |
|--------|---------------------|------|---------|------|
| **Metrics** | *how is it doing in aggregate?* | a number sampled over time | long-term memory + **alerts** | Prometheus |
| **Logs** | *why did THIS event happen?* | one timestamped record | root-cause a single event | Loki / ELK |
| **Traces** | *where did this request's time go?* | a tree of spans (hops) | latency across services | Jaeger / Tempo |

The thing that makes them a **system** and not three tools is the **correlation
ID** (`trace_id`): it is stamped into every log line and every span of one
request, so you can jump from an alert (a metric crosses a threshold) → the
offending requests (their logs) → the exact slow span (the trace). That
triangulation is what *observability* means; *monitoring* is merely collecting
metrics.

> **Rule of thumb:** instrument the three pillars, then tie them together with
> `trace_id`. An alert without a path to a trace is just noise.

## 1. Metrics — counter / gauge / histogram (Prometheus)

A metric is a **named number with labels**, sampled over time:
`http_requests_total{method="GET",status="200"}`. Prometheus stores three
sub-types that cover essentially everything:

- **counter** — only goes **UP** (resets to 0 on restart). "How many so far."
  Query with `rate()` / `increase()`.
- **gauge** — goes up **OR** down. "What is it right now." Memory, queue depth,
  CPU %, active connections. Query with `avg_over_time()`.
- **histogram** — buckets observations into cumulative buckets (+ a `_sum` and
  `_count`). Lets you reconstruct percentiles with `histogram_quantile()`.

### 1a. Counter — `http_requests_total`

From `observability.py` Section A1 (20 scrapes @ 15 s = a 5-minute window):

```
cumulative GET/200 at scrape 0  : 16
cumulative GET/200 at scrape 19: 289
```

```promql
# requests per second over the last 5 minutes
rate(http_requests_total{status="200"}[5m])
  = (289 - 16) / 300 = 0.9100 req/s

# total requests added in the window
increase(http_requests_total{status="200"}[5m])  =  283
```

**[check] OK** — the final counter value (200 + 500 = 300) equals the sum of all
increments exactly, and the series is monotonic. A counter that goes *down* (other
than a restart reset) is a bug; `rate()` auto-detects resets.

### 1b. Gauge — `memory_usage_bytes`

```
peak over window : 632 MiB
avg_over_time(memory_usage_bytes[5m]) = 518.6 MiB
max_over_time(...)                   = 632 MiB
```
**[check] OK** — `avg_over_time` reproduces `statistics.fmean` to 1e-9.

### 1c. Histogram — `http_request_duration_seconds`

60 observed latencies are sorted into the default Prometheus buckets:

```
buckets (upper bound le=) : [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0] +Inf
cumulative counts (<= le) : [   1,    4,    14,   25,  46,   49,  54,  60,  60]
_count = 60   _sum = 8.8032s
```

```promql
histogram_quantile(0.95, sum by (le) (
    rate(http_request_duration_seconds_bucket[5m]) ))
  -> 750.0 ms
```

The raw-data p95 is 790.2 ms; the **bucket** p95 is 750.0 ms — within one bucket
width (the 0.5→1.0 bucket is 500 ms wide). **That is the histogram trade-off:**
buckets cost O(buckets) of memory no matter how many requests, but the percentile
is only as precise as the bucket width. If you need exact tail latency, use a
**summary** (`quantile_over_time`) instead — at the cost of more memory.

**[check] OK** — `_count == N`, `_sum == sum(obs)`, the `+Inf` bucket == total,
buckets are monotonic, and the bucket p95 is within one bucket width of the raw p95.

## 2. Logs — structured JSON + `trace_id` correlation (Loki)

A log is one **timestamped event**. **Structured logging** (JSON fields, not free
text) turns logs into queryable data. The single most important field is
`trace_id`: it ties a log line to the trace and metric of the *same* request.

Three services handle one checkout request; they all stamp the *same* `trace_id`
(`a4f9c21b8e7d4061`) into their logs:

```
{"ts":"12:01:03.112","level":"INFO" ,"service":"api-gateway","trace_id":"a4f9...","span_id":"1a2b3c4d","msg":"GET /checkout",   ...}
{"ts":"12:01:03.118","level":"INFO" ,"service":"auth-svc"   ,"trace_id":"a4f9...","span_id":"5e6f7a8b","parent_span_id":"1a2b3c4d","msg":"validating token"}
{"ts":"12:01:03.141","level":"WARN" ,"service":"auth-svc"   ,"trace_id":"a4f9...","span_id":"5e6f7a8b","msg":"token near expiry","ttl_s":90}
{"ts":"12:01:03.207","level":"INFO" ,"service":"db-svc"     ,"trace_id":"a4f9...","span_id":"9c0d1e2f","msg":"SELECT orders","rows":3,"query_ms":58}
{"ts":"12:01:03.430","level":"ERROR","service":"api-gateway","trace_id":"a4f9...","span_id":"1a2b3c4d","msg":"upstream timeout","status":504,"latency_ms":318}
```

Because every line is JSON, **Loki** can aggregate with **LogQL**:

```logql
# count of ERROR lines per service over 5m
sum by (service) (count_over_time({app="checkout"} | json | level="ERROR" [5m]))
```
```
api-gateway  3
auth-svc     1
cache-svc    1
db-svc       4
```

**[check] OK** — `sum(levels) == N`, the per-service error counts sum to the total
ERROR count, and the 5-line demo request shares exactly one `trace_id`.

> The `trace_id` is the bridge: clicking it in a dashboard jumps you from this
> ERROR log straight to the trace's span tree (Section 3) and the request-rate
> metric (Section 1). Three pillars, one click.

## 3. Traces — span tree, self-time, critical path (Jaeger)

A **trace** is a tree of **spans** for *one* request. Each span records
`(op, service, start, end, parent)`; the parent pointer builds the tree, and the
`trace_id` stamps them all as one request. Traces answer *"where did the time
go?"* — and for that you need **self-time**, not raw duration.

### 3a. Self-time

> **self_time(span) = duration(span) − measure(union of child intervals)**

…i.e. the wall-clock the span was *actually working*, not the time it spent
*waiting for a child* to return. This is the number that tells you what to
optimize.

### 3b. The canonical request flow — `API → Auth → DB → Cache`

A pure nested call chain (synchronous RPCs: each service waits for its child).
All spans nest perfectly:

```
1a2b3c4d [api-gateway] GET /checkout  [  0->400] 400ms  (self 250ms)
  5e6f7a8b [auth-svc] ValidateToken  [ 10->160] 150ms  (self  50ms)
    9c0d1e2f [db-svc] SELECT users    [ 30->130] 100ms  (self  50ms)
      0f1a2b3c [cache-svc] GET session [ 50->100]  50ms  (self  50ms)
```

| span | duration | children-union | **self-time** |
|------|---------:|---------------:|--------------:|
| API  | 400 ms | 150 ms | **250 ms** |
| Auth | 150 ms | 100 ms | **50 ms** |
| DB   | 100 ms |  50 ms | **50 ms** |
| Cache | 50 ms |   0 ms | **50 ms** |

```
trace duration = max(end) - min(start) = 400 - 0 = 400 ms
critical path  = API -> Auth -> DB -> Cache
sum(self-time on critical path) = 250 + 50 + 50 + 50 = 400 ms
```

### 🥇 THE GOLD CHECK

For a pure nested call chain the critical path **is** the whole trace, so:

> **`trace_duration == sum(self-time on the critical path)`**
> **`400 == 400  →  OK`**

This is exactly what `observability.html` recomputes live. The take-away:
**optimize the spans with the largest self-time** — here `API` (250 ms) is mostly
its own work, not waiting; that is where your latency budget actually is. (By
contrast, the root's raw 400 ms is misleading — most of it is *children*.)

### 3c. Branching trace (parallelism) — the general case

When the API fans out into **non-overlapping** parallel children, the critical
path is only *part* of the trace:

```
a1b2 [api-gateway] GET /search  [  0->300] 300ms  (self 30ms)
  c3d4 [auth-svc] ValidateToken [  5-> 55]  50ms  (self 50ms)
  e5f6 [cache-svc] GET result   [ 60->100]  40ms  (self 40ms)
  7890 [db-svc] SELECT docs     [100->280] 180ms  (self 180ms)
```

```
trace duration            = 300 ms
sum(self-time ALL spans)  = 300 ms     ← every ms is "owned" by exactly one span
critical path             = API -> DB
sum(self-time crit path)  = 210 ms      (< duration: the rest is parallel/Auth work)
```

Two different facts, both true:
- **`trace_duration == sum(self-time over ALL spans)`** = 300 == 300 — **OK**.
  This holds whenever sibling spans don't overlap (a valid span tree).
- **critical-path self-time (210 ms) ≤ trace_duration (300 ms)** when there is
  parallelism. The 90 ms gap is the Auth + Cache work that the API did in
  parallel with DB; you can't remove it from the wall-clock, only from the
  critical path.

**[check] OK** — sum-of-all-self-times == duration, and critical-path < duration
when there is parallelism.

## 4. USE vs RED — two complementary checklists

Two checklists make sure you instrument the **right** signals:

- **USE method** (Brendan Gregg, 2012) — for **resources** (CPU, disk, NIC):
  **U**tilization · **S**aturation · **E**rrors.
- **RED method** (Tom Wilkie, 2015) — for **services / endpoints**:
  **R**ate · **E**rrors · **D**uration.

> **Rule of thumb:** USE the metal (nodes), RED the traffic (services). Check
> **both**: a saturated CPU (USE) *explains* a service's rising Duration (RED).

From `observability.py` Section D, the spike aligns: sample 7 has peak **Rate**,
peak **Duration** (p95 = 318 ms), and peak **Errors** (RED) right when the CPU
hit peak **Utilization** + a pressured run-queue (USE). That is USE *explaining*
RED — the whole point of running both.

| aspect  | USE (CPU resource) | RED (/checkout service) |
|---------|--------------------|--------------------------|
| primary | Utilization avg ~64% | Rate mean ~144 req/s |
| queue   | Saturation: pressured samples | Errors: total (~1.5%) |
| failure | Errors: 1 drop | Duration p95 peak 318 ms |

**[check] OK** — the RED spike coincides with peak p95 + peak errors.

## 5. SLO / SLI / SLA + error budget + burn-rate alerting

- **SLI** — the **measurement**: *"fraction of requests that were good"*, where
  `good = (status < 500) AND (latency < 800 ms)` over 5 minutes.
- **SLO** — the **target** on that SLI: *"99.9% of 5-min windows good."*
- **SLA** — the **contract**: *"miss 99.9% for a month → refund X%."*

The SLO is internal and **stricter** than the SLA; the SLA is the legal fallback.
The gap is your safety margin.

### 5a. The error budget

**`error budget = 1 − SLO`** — the allowed failure you can "spend."

```
month window = 30 * 24 * 60 = 43200 min
error budget = 1 - 0.999 = 0.001  (= 0.1%)
allowed downtime = 43200 * 0.001 = 43.2 min / month
  -> 99.9% = 43.2 min downtime allowed
```

| SLO | downtime allowed / month |
|------|-------------------------:|
| 99.5% | 216.0 min |
| **99.9%** | **43.2 min** |
| 99.95% | 21.6 min |
| 99.99% | 4.3 min |

> Each extra "nine" costs roughly 10× less allowed downtime — and exponentially
> more engineering effort. **[check] OK** — 99.9% → exactly 43.2 min/month.

**The cultural point of the budget:** it is *permission to take risks*. As long
as you are inside budget you can ship aggressively; when the budget is low you
freeze feature work and focus on reliability. Burn it deliberately on
experiments, not accidentally on regressions.

### 5b. Burn rate + multi-window alerting

**`burn_rate = observed_error_rate / (1 − SLO)`** — how fast you spend the
budget. `burn = 1` means evenly over the window; `> 1` means you will bust the
SLO before the window ends. The Google SRE Workbook (ch. 5) recommends
**multi-window multi-burn-rate** alerting so you page on *fast* burns (a lot of
budget wasted quickly) *and* catch *slow* burns:

| alert  | long window | short window | burn threshold | meaning |
|--------|-------------|--------------|----------------|---------|
| PAGE   | 1 h | 5 m | **> 14.4×** | 2% budget in 1 h |
| PAGE   | 6 h | 30 m | **> 6.0×** | 5% budget in 6 h |
| TICKET | 3 d | 6 h | > 1.0× | on-pace to miss |

**Worked example** (Section E2): observed error rate this hour = 2.0%.

```
burn_rate = 0.020 / 0.001 = 20.0×
-> 20.0× > 14.4× ?  YES -> PAGE (fast burn)
budget consumed in this 1h = burn * (1h/30d) = 2.78% of the monthly budget
```

**[check] OK** — `burn_rate = err_rate / budget = 20.0×` → fast-burn PAGE.
Multi-window alerting avoids two failure modes: a single bad minute shouldn't
page you at 3 a.m. (use the long window), but 2% of your monthly budget gone in
one hour absolutely should (use the short window + high threshold).

### 5c. Attainment

Over a month of 5-minute windows (8640 total), 7 fell below threshold:

```
SLI (good / total) = 8633 / 8640 = 99.919%
SLO target         = 99.900%
result             = MEET the SLO   (budget remaining: +0.019 pts)
```
The incidents stayed inside the 43.2-min budget → no SLA penalty.

## 6. How it all fits together

```
   alert fires ──metric threshold crossed──┐
                                            │  same trace_id
   ERROR log ◀──────────────────────────────┤
        │                                   │
        └── trace_id ──▶ trace span tree ───┘  → optimize the biggest self-time span
```

The three pillars are useless in isolation. The `trace_id` (and the `span_id` /
`parent_span_id`) is the single field that makes an alert *actionable*: from a
rate spike, to the failing requests, to the exact slow database query, in one
click. Instrument all three, correlate them, then choose your analysis lens —
**USE** for the nodes, **RED** for the services, and budget your failures with
**SLOs + burn-rate alerts**.

---

*Built from `observability.py` — pure stdlib, deterministic (seeded RNG). Every
figure is reproduced live in `observability.html` and gold-checked against the
Python output.*
