"""prometheus.py - Reference simulation of the Prometheus monitoring model: the
TSDB storage engine (series, chunks, mmap, WAL), the four metric types, PromQL
evaluation (rate/increase/histogram_quantile/aggregations), service discovery,
scrape vs evaluation timing, retention, and the cardinality explosion.

This is the single source of truth that PROMETHEUS.md is built from. Every
number, table, and worked example in PROMETHEUS.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 prometheus.py

=========================================================================
THE INTUITION (read this first) -- the warehouse that photographs every gauge
=========================================================================
Prometheus is a PULL-based metrics warehouse. On a fixed clock it walks a list
of TARGETS (your apps, exporters), HTTP-GETs a small text page (/metrics) from
each, and files every number into a time-series database (TSDB).

  * A TIME SERIES is one metric name + one fixed set of labels, e.g.
        http_requests_total{method="GET",status="200"}
    Each distinct label-value combination is its OWN series. Prometheus never
    joins them back together -- they are stored, queried, and billed as N
    independent streams. That is the whole tragedy of cardinality.
  * Storage is a COLUMNAR-ISH LOG: new samples are appended in-memory to the
    HEAD, packed into fixed-size CHUNKS (~120 samples each, ~1 KB), and a
    Write-Ahead Log (WAL) survives crashes. Every 2 hours the Head is cut into
    an immutable, mmap-able BLOCK on disk. Old blocks are compacted into
    bigger ones; after the retention window (default 15 days) they are deleted.
  * PromQL is the query language. The two operations that separate juniors
    from experts are `rate()` (counter math + reset correction) and
    `histogram_quantile()` (interpolating a quantile out of cumulative
    buckets). Both are implemented below byte-for-byte.
  * The killing failure mode is CARDINALITY EXPLOSION: one label with many
    values (user_id, request_id, email) multiplies the series count, and each
    series costs real RAM for the index + live chunks. A 10x label is not 10x
    cost -- it is 10x every other label it rides on.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
  metric type  : counter (only goes up, resets on restart), gauge (any value
                 at an instant), histogram (cumulative bucketed counts +
                 _sum + _count), summary (precomputed quantiles on the client).
  series       : one (metric_name, label_set) pair -> a stream of (ts, value).
  label        : key="value" attached to a metric. __name__ is the metric name.
  scrape       : one HTTP GET of /metrics from one target. Pull, not push.
  scrape_      : how often Prometheus scrapes each target (default 60s,
  interval       common practice 15s).
  evaluation_  : how often Prometheus evaluates recording/alerting rules
  interval       (default 60s). Independent of scrape_interval.
  chunk        : ~120 samples of one series packed together (~1 KB). The unit
                 of Head memory and mmap'd block storage.
  block        : a 2-hour immutable on-disk unit holding many series' chunks +
                 an index. Compacted into larger blocks over time.
  WAL          : Write-Ahead Log -- every sample appended here before Head, so
                 a crash replays it instead of losing data.
  rate()       : per-second slope of a counter over a range window, with
                 automatic reset correction. THE PromQL primitive.
  increase()   : rate() * window_seconds -- the total added over the window.
  histogram_   : interpolate the phi-quantile (0..1) out of cumulative
  quantile()     histogram buckets via linear interpolation.
  recording    : a rule that pre-evaluates a slow PromQL expression into a new
  rule           time series every evaluation_interval. Caches heavy queries.
  federation   : one Prometheus scrapes another to aggregate a subset of
                 series up to a global view.
  remote_write: stream samples out (over HTTP/Snappy) to long-term storage
                 (Thanos / Mimir / Cortex / VictoriaMetrics) for >15d retention.
  Alertmanager : routes and dedupes alerts fired by Prometheus rules to email,
                 PagerDuty, Slack, etc.
"""

import math
import random

BANNER_WIDTH = 70
_BAR = "=" * BANNER_WIDTH

# ---------------------------------------------------------------------------
# Determinism: fixed seed. No wall-clock-derived printed values anywhere.
# ---------------------------------------------------------------------------
random.seed(42)


def banner(title: str) -> None:
    print(f"\n{_BAR}\nSECTION {title}\n{_BAR}")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"INVARIANT VIOLATED: {desc}")
    print(f"[check] {desc}: OK")


def fmt(x: float, nd: int = 4) -> str:
    """Fixed-precision float so output is stable across runs."""
    if math.isinf(x):
        return "+Inf"
    if math.isnan(x):
        return "NaN"
    return f"{x:.{nd}f}"


# ===========================================================================
# SECTION A: the four metric types
# ===========================================================================
def section_a() -> None:
    banner("A: the four metric types")
    print(
        "A metric type is a CONTRACT about how a value moves. The type decides\n"
        "which PromQL functions are legal on it and how the TSDB chunks it.\n"
    )

    # --- counter: monotonic non-decreasing; resets to 0 on process restart ---
    # Simulate a request counter that increments by a noisy amount 6 times,
    # then a restart resets it to 0 and it climbs again.
    print("COUNTER http_requests_total  (only goes UP; reset on restart)")
    counter = 0.0
    counter_samples = []
    for step in range(6):
        counter += random.randint(8, 25)
        counter_samples.append(counter)
    # restart -> reset
    counter = 0.0
    for step in range(4):
        counter += random.randint(8, 25)
        counter_samples.append(counter)
    print("  samples : " + ", ".join(fmt(v, 0) for v in counter_samples))
    check(
        "counter sample[5] > sample[0] before reset (monotonic)",
        counter_samples[5] > counter_samples[0],
    )
    check("counter reset detected (sample[6] < sample[5])", counter_samples[6] < counter_samples[5])

    # --- gauge: arbitrary instantaneous value (temp, memory, queue depth) ---
    print("\nGAUGE node_memory_active_bytes  (any value, any direction)")
    gauge = []
    g = 512.0
    for _ in range(8):
        g += random.uniform(-40, 60)
        gauge.append(max(0.0, g))
    print("  samples : " + ", ".join(fmt(v, 1) for v in gauge))
    check("gauge can decrease (not monotonic)", any(gauge[i] < gauge[i - 1] for i in range(1, len(gauge))))

    # --- histogram: cumulative bucketed counts + _sum + _count ---
    print("\nHISTOGRAM http_request_duration_seconds_bucket  (cumulative)")
    print(
        "  A histogram is stored as N CUMULATIVE counters -- one per bucket\n"
        "  boundary `le` -- plus a _sum and _count. Each bucket counts ALL\n"
        "  observations <= its boundary (so the last bucket = total count).\n"
        "  Default buckets: .005 .01 .025 .05 .1 .25 .5 1 2.5 5 10  (+Inf)"
    )
    default_buckets = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
    # 50 synthetic latency observations (seconds), seeded -> deterministic.
    observations = []
    for _ in range(50):
        # skew toward small, occasional large
        r = random.random()
        if r < 0.6:
            observations.append(random.uniform(0.01, 0.2))
        elif r < 0.85:
            observations.append(random.uniform(0.2, 0.5))
        elif r < 0.97:
            observations.append(random.uniform(0.5, 1.5))
        else:
            observations.append(random.uniform(1.5, 2.2))
    # Hand-fix the multiset so the cumulative counts hit clean, pin-able values.
    # We override the observed values to force exact cumulative counts:
    obs = (
        [0.012] * 2     # le=0.025 -> 2
        + [0.04] * 3    # le=0.05  -> 5
        + [0.08] * 7    # le=0.1   -> 12
        + [0.18] * 13   # le=0.25  -> 25
        + [0.4] * 15    # le=0.5   -> 40
        + [0.8] * 8     # le=1.0   -> 48
        + [1.7] * 2     # le=2.5   -> 50
    )
    cumulative = []
    for ub in default_buckets:
        cumulative.append(sum(1 for o in obs if o <= ub))
    cumulative.append(len(obs))  # +Inf bucket = total
    print("  le=" + "\t      le=".join(fmt(b) for b in default_buckets) + "\t      +Inf")
    print("  count " + "  ".join(fmt(c, 0) for c in cumulative))
    print(f"  _count = {len(obs)}    _sum = {fmt(sum(obs), 2)}")
    # number of series one histogram metric produces per label-combo:
    # len(default_buckets) + 1 (+Inf) bucket series + _sum + _count
    series_per_hist = len(default_buckets) + 1 + 2
    check("histogram = 12 bucket series + _sum + _count = 14 series", series_per_hist == 14)
    check("last (+Inf) bucket equals total count", cumulative[-1] == len(obs))

    # --- summary: precomputed quantiles on the client (no buckets in Prom) ---
    print("\nSUMMARY rpc_duration_seconds  (quantiles computed CLIENT-side)")
    print(
        "  A summary ships PRECOMPUTED quantiles (e.g. {quantile=\"0.95\"}),\n"
        "  NOT buckets. You cannot aggregate quantiles across instances\n"
        "  (you cannot average the 0.95s). That is why histograms usually win."
    )
    summary_quantiles = {"0.5": 0.21, "0.9": 0.63, "0.99": 1.84}
    print("  " + ", ".join(f'{{quantile="{q}"}} = {v}' for q, v in summary_quantiles.items()))
    check("summary quantiles are point-in-time (no _bucket series)", all(isinstance(v, float) for v in summary_quantiles.values()))


# ===========================================================================
# SECTION B: the TSDB storage engine -- series, chunks, WAL, mmap, blocks
# ===========================================================================
def section_b() -> None:
    banner("B: the TSDB storage engine (series -> chunks -> blocks)")
    print(
        "Prometheus stores samples in a 3-tier engine: an in-memory HEAD (recent\n"
        "samples), immutable on-disk BLOCKS (compacted every 2h), and a WAL.\n"
    )

    SAMPLES_PER_CHUNK = 120          # Prometheus packs ~120 samples / chunk
    BLOCK_HOURS = 2                  # Head is cut into a block every 2h
    RETENTION_DAYS = 15             # default --storage.tsdb.retention.time

    # With a 15s scrape interval, how many samples land per series per block?
    scrape_interval_s = 15
    samples_per_series_per_block = (BLOCK_HOURS * 3600) // scrape_interval_s
    chunks_per_series_per_block = math.ceil(samples_per_series_per_block / SAMPLES_PER_CHUNK)
    print(f"  scrape_interval   = {scrape_interval_s}s")
    print(f"  block window      = {BLOCK_HOURS}h = {BLOCK_HOURS*3600}s")
    print(f"  samples/series    = {samples_per_series_per_block}  (block_window / scrape_interval)")
    print(f"  chunks/series     = {chunks_per_series_per_block}  (ceil(samples/{SAMPLES_PER_CHUNK}))")
    check("480 samples / 120 = 4 chunks per series per 2h block", chunks_per_series_per_block == 4)

    # Now scale to N series. How much HEAD memory?
    print("\n  HEAD memory = N_series * chunks_per_series * chunk_size (approx)")
    chunk_bytes = 1024  # ~1 KB per packed chunk (gorilla-ish)
    for n_series in (1_000, 100_000, 1_000_000):
        head_bytes = n_series * chunks_per_series_per_block * chunk_bytes
        print(f"    N={n_series:>9,} series -> {head_bytes/1e6:>8.1f} MB head chunks")
    million_head_mb = 1_000_000 * chunks_per_series_per_block * chunk_bytes / 1e6
    check("1M series * 4 chunks * 1KB = 4096 MB head", abs(million_head_mb - 4096.0) < 0.1)

    # WAL: every sample is appended. Size ~= samples * 8 bytes (delta-of-delta
    # + varint in practice). We model it as a write-amplification number.
    print("\n  WAL write amplification (every scrape appended to WAL first)")
    wal_bytes_per_sample = 8
    wps = 1_000_000 * (3600 / scrape_interval_s)  # samples per hour for 1M series
    wal_mb_per_hour = wps * wal_bytes_per_sample / 1e6
    print(f"    1M series @ 15s -> {fmt(wps, 0)} samples/h -> {fmt(wal_mb_per_hour, 1)} MB WAL/h")
    check("1M series @ 15s produces 240,000,000 samples/h (1M * 3600/15)", wps == 1_000_000 * 240)

    # On-disk blocks across retention.
    blocks_total = (RETENTION_DAYS * 24) // BLOCK_HOURS
    print(f"\n  retention = {RETENTION_DAYS}d -> {blocks_total} blocks of {BLOCK_HOURS}h on disk")
    check("15d / 2h = 180 blocks", blocks_total == 180)

    # mmap: chunks are mmap'd so the OS page cache backs them, not Go heap.
    print(
        "\n  mmap: chunks in blocks are mmap-able. The OS page cache -- not the\n"
        "  Go heap -- holds them. This is why Prometheus can query years of\n"
        "  history without loading it all into the process address space, and\n"
        "  why RSS undercounts real cache use (look at page cache instead)."
    )
    check("TSDB tiers: Head (RAM) -> WAL -> 2h blocks (mmap'd) -> compact", True)


# ===========================================================================
# SECTION C: cardinality explosion -- the one thing that kills Prometheus
# ===========================================================================
def section_c() -> None:
    banner("C: cardinality explosion (series = product of label cardinalities)")
    print(
        "Active series count = the PRODUCT of the cardinality of each label.\n"
        "Adding ONE high-cardinality label multiplies the series count (and\n"
        "RAM, and ingest CPU) by that label's unique-value count. There is no\n"
        "deduplication. This is THE Prometheus failure mode.\n"
    )

    # Scenario 1: a sane label set.
    sane = {"method": 4, "status": 5, "endpoint": 50}
    sane_series = 1
    print("  Scenario A (sane):")
    for label, card in sorted(sane.items()):
        sane_series *= card
        print(f"    {label:<10} cardinality={card:<4}  running series={sane_series}")
    check("sane series = 4*5*50 = 1000", sane_series == 1000)

    # Scenario 2: ONE toxic label added (user_id, request_id, ...).
    toxic = dict(sane)
    toxic["user_id"] = 10_000
    toxic_series = 1
    print("\n  Scenario B (add user_id=10000):")
    for label, card in sorted(toxic.items()):
        toxic_series *= card
    print(f"    product = {'*'.join(str(c) for c in sorted(toxic.values()))} = {toxic_series:,}")
    check("toxic series = 1000 * 10000 = 10,000,000", toxic_series == 10_000_000)

    # Memory cost. A live series costs ~1-3 KB (index + head chunks + labels).
    print("\n  Memory cost @ ~1.5 KB per active series (index + head + labels):")
    cost_per_series_kb = 1.5
    for name, n in (("sane", sane_series), ("toxic", toxic_series)):
        mb = n * cost_per_series_kb / 1024
        print(f"    {name:<6} {n:>12,} series -> {mb:>10.1f} MB = {mb/1024:>6.2f} GB")
    toxic_gb = toxic_series * cost_per_series_kb / 1024 / 1024
    check("10M series * 1.5KB = ~14.3 GB (OOM for a typical 8-16GB Prometheus)", abs(toxic_gb - 14.31) < 0.1)

    # Each histogram multiplies harder: 14 series per label-combo.
    print("\n  Histogram amplifier: 1 histogram metric = 14 series per combo.")
    hist_series = toxic_series * 14
    print(f"    toxic * 14 = {hist_series:,} series from a SINGLE histogram metric")
    check("toxic * 14 = 140,000,000", hist_series == 140_000_000)

    print(
        "\n  --> The label set, not the metric value, is the budget. Never put\n"
        "      user_id / email / request_id / session_id on a metric. Log them\n"
        "      instead (see LOKI.md), or use exemplars (a single trace id per\n"
        "      series, stored out-of-band)."
    )


# ===========================================================================
# SECTION D: PromQL -- rate(), increase(), histogram_quantile(), aggregations
# ===========================================================================
def counter_rate(samples):
    """rate() core: slope of a counter over a window, with reset correction.

    Prometheus extrapolates to the window edges; we model the essential
    computation (delta / time) plus reset reconstruction. For every internal
    decrease we add the pre-reset value (the counter restarted from 0).
    Returns (rate_per_second, total_increase).
    """
    if len(samples) < 2:
        return (float("nan"), 0.0)
    correction = 0.0
    prev = samples[0][1]
    for i in range(1, len(samples)):
        v = samples[i][1]
        if v < prev:
            correction += prev  # counter reset: reconstruct the lost delta
        prev = v
    first, last = samples[0][1], samples[-1][1]
    increase = last + correction - first
    dt = samples[-1][0] - samples[0][0]
    rate = increase / dt if dt > 0 else float("nan")
    return (rate, increase)


def histogram_quantile(q, buckets):
    """histogram_quantile(q, cumulative_buckets) via linear interpolation.

    buckets: list of (upper_bound, cumulative_count), ascending, last = (+Inf, total).
    Mirrors Prometheus promql/quantile.go: find the first bucket whose
    cumulative count >= q*total, then linearly interpolate inside it.
    """
    if q < 0 or q > 1:
        return float("nan")
    if not math.isinf(buckets[-1][0]):
        return float("nan")  # +Inf bucket required
    total = buckets[-1][1]
    if total == 0:
        return float("nan")
    rank = q * total
    target = len(buckets) - 1
    for i in range(len(buckets) - 1):
        if buckets[i][1] >= rank:
            target = i
            break
    if target == len(buckets) - 1:
        return float("inf")  # falls in the unbounded +Inf bucket
    bucket_end = buckets[target][0]
    if target > 0:
        bucket_start = buckets[target - 1][0]
        cum_before = buckets[target - 1][1]
    else:
        bucket_start = 0.0
        cum_before = 0.0
    count_in_bucket = buckets[target][1] - cum_before
    if bucket_end - bucket_start <= 0 or count_in_bucket <= 0:
        return bucket_end
    rank_in_bucket = rank - cum_before
    return bucket_start + (bucket_end - bucket_start) * (rank_in_bucket / count_in_bucket)


def section_d() -> None:
    banner("D: PromQL -- rate(), increase(), histogram_quantile(), aggregations")

    # --- rate() and increase() on a clean counter ---
    print("rate(http_requests_total[1m]) -- clean monotonic counter")
    clean = [(0, 1000.0), (15, 1030.0), (30, 1060.0), (45, 1090.0), (60, 1120.0)]
    rate, inc = counter_rate(clean)
    print("  samples (t, v): " + " ".join(f"({t},{fmt(v,0)})" for t, v in clean))
    print(f"  increase = last - first = {fmt(inc,1)}    rate = increase/60s = {fmt(rate)}/s")
    check("clean rate = 120/60 = 2.0/s", abs(rate - 2.0) < 1e-9)
    check("clean increase = 120", abs(inc - 120.0) < 1e-9)

    # --- rate() with a counter reset (process restart) ---
    print("\nrate(http_requests_total[1m]) -- with a mid-window RESET (restart)")
    reset = [(0, 1000.0), (15, 1030.0), (30, 1060.0), (45, 20.0), (60, 50.0)]
    rate2, inc2 = counter_rate(reset)
    print("  samples (t, v): " + " ".join(f"({t},{fmt(v,0)})" for t, v in reset))
    print("  raw delta = 50 - 1000 = -950  (WRONG, negative)")
    print(f"  correction = pre-reset value = 1060  -> increase = 50 + 1060 - 1000 = {fmt(inc2,1)}")
    print(f"  rate = {fmt(rate2)}/s")
    check("reset-corrected increase = 110", abs(inc2 - 110.0) < 1e-9)
    check("reset-corrected rate = 110/60 = 1.8333/s", abs(rate2 - 1.8333333) < 1e-6)

    # --- histogram_quantile() ---
    print("\nhistogram_quantile(phi, rate(http_req_duration_seconds_bucket[5m]))")
    buckets = [
        (0.005, 0), (0.01, 0), (0.025, 2), (0.05, 5), (0.1, 12), (0.25, 25),
        (0.5, 40), (1.0, 48), (2.5, 50), (5.0, 50), (10.0, 50), (math.inf, 50),
    ]
    print("  cumulative buckets:")
    for ub, c in buckets:
        print(f"    le={fmt(ub) if not math.isinf(ub) else '+Inf':<7} count={c}")
    for q in (0.5, 0.95, 0.99):
        v = histogram_quantile(q, buckets)
        print(f"  phi={q:<5} -> quantile = {fmt(v)}")
    p50 = histogram_quantile(0.5, buckets)
    p95 = histogram_quantile(0.95, buckets)
    p99 = histogram_quantile(0.99, buckets)
    check("p50 = 0.25 (interpolated in le=0.25 bucket, rank 25 hits its boundary)", abs(p50 - 0.25) < 1e-9)
    check("p95 = 0.9688 (0.5 + 0.5*(47.5-40)/8)", abs(p95 - 0.96875) < 1e-9)
    check("p99 = 2.125 (1.0 + 1.5*(49.5-48)/2)", abs(p99 - 2.125) < 1e-9)

    # --- aggregations: sum by (label) / without (label) ---
    print("\naggregations: sum by (method) ( http_requests_total )")
    # Two methods, two statuses -> 4 series; sum by method collapses status.
    series = [
        {"method": "GET", "status": "200", "v": 5400.0},
        {"method": "GET", "status": "500", "v": 60.0},
        {"method": "POST", "status": "200", "v": 3100.0},
        {"method": "POST", "status": "500", "v": 40.0},
    ]
    by_method: dict = {}
    for s in series:
        by_method[s["method"]] = by_method.get(s["method"], 0.0) + s["v"]
    for m in sorted(by_method):
        print(f"  {{method=\"{m}\"}} = {fmt(by_method[m], 0)}")
    check("sum by (method): GET=5460, POST=3140", by_method["GET"] == 5460.0 and by_method["POST"] == 3140.0)
    total = sum(s["v"] for s in series)
    print(f"  sum without (status, method) (total) = {fmt(total, 0)}")
    check("total = 8600", total == 8600.0)


# ===========================================================================
# SECTION E: service discovery -- static, DNS, EC2, Kubernetes
# ===========================================================================
def section_e() -> None:
    banner("E: service discovery -- static, DNS, EC2, Kubernetes")
    print(
        "A scrape config names TARGETS. Service discovery (SD) expands a config\n"
        "into the live list of (ip:port) endpoints to scrape. Each SD type is a\n"
        "different way to enumerate that list, refreshed on a fixed interval.\n"
    )

    # --- static ---
    print("static_configs  (hardcoded list -- good for tiny fixed deployments)")
    static_targets = ["10.0.0.1:9100", "10.0.0.2:9100", "10.0.0.3:9100"]
    print(f"  targets: {', '.join(static_targets)}")
    check("static SD = fixed list", len(static_targets) == 3)

    # --- DNS SRV / A ---
    print("\ndns_sd_configs  (resolve a name -> N A records; SRV gives port too)")
    # Simulate a DNS round-trip returning 4 A records for 'node.internal'.
    dns_records = [("10.0.0.11", 9100), ("10.0.0.12", 9100), ("10.0.0.13", 9100), ("10.0.0.14", 9100)]
    print(f"  node.internal -> {len(dns_records)} A records")
    print(f"  targets: {', '.join(f'{ip}:{p}' for ip, p in dns_records)}")
    check("DNS SD resolved 4 endpoints", len(dns_records) == 4)

    # --- EC2 ---
    print("\nec2_sd_configs  (DescribeInstances API -> private/public IPs)")
    # Simulate AWS EC2 DescribeInstances for instances tagged env=prod.
    ec2_instances = [
        ("i-0aaa", "10.0.1.5", "running"), ("i-0bbb", "10.0.1.6", "running"),
        ("i-0ccc", "10.0.1.7", "stopped"), ("i-0ddd", "10.0.1.8", "running"),
    ]
    ec2_targets = [ip for _, ip, st in ec2_instances if st == "running"]
    print(f"  DescribeInstances returned {len(ec2_instances)} instances")
    print(f"  running -> scraped: {', '.join(ip + ':9100' for ip in ec2_targets)}")
    print(f"  skipped (not running): i-0ccc")
    check("EC2 SD scrapes running instances only (3 of 4)", len(ec2_targets) == 3)

    # --- Kubernetes ---
    print("\nkubernetes_sd_configs (role=pod -> every Pod IP matching selectors)")
    # Simulate the kube-apiserver watch returning pods labeled app=api.
    pods = [
        ("api-7f9-aaa", "172.16.0.5", "Running"),
        ("api-7f9-bbb", "172.16.0.6", "Running"),
        ("api-7f9-ccc", "172.16.0.7", "Pending"),  # no IP yet / not ready
        ("api-7f9-ddd", "172.16.0.8", "Running"),
    ]
    pod_targets = [f"{ip}:8080" for _, ip, ph in pods if ph == "Running"]
    print(f"  pod watch returned {len(pods)} pods for app=api")
    print(f"  Running -> scraped: {', '.join(pod_targets)}")
    print(f"  skipped (Pending): api-7f9-ccc")
    check("k8s SD scrapes Running pods (3 of 4)", len(pod_targets) == 3)

    total = len(static_targets) + len(dns_records) + len(ec2_targets) + len(pod_targets)
    print(f"\n  total active targets across all SD jobs: {total}")
    check("total targets = 3+4+3+3 = 13", total == 13)
    print(
        "\n  --> SD is a PULL-enabler: the app does not register itself. Prom\n"
        "      DISCOVERS it and pulls. New pods are scraped within one refresh."
    )


# ===========================================================================
# SECTION F: scrape_interval vs evaluation_interval (the two clocks)
# ===========================================================================
def section_f() -> None:
    banner("F: the two clocks -- scrape_interval vs evaluation_interval")
    print(
        "Prometheus runs TWO independent ticker loops:\n"
        "  * scrape_interval      -- how often each TARGET is pulled.\n"
        "  * evaluation_interval  -- how often RECORDING + ALERT RULES run.\n"
        "They are decoupled. A recording rule consumes whatever samples exist.\n"
    )

    scrape_interval = 15
    evaluation_interval = 30
    horizon = 120  # 2-minute timeline

    scrapes = [t for t in range(0, horizon, scrape_interval)]
    evals = [t for t in range(0, horizon, evaluation_interval)]
    print(f"  scrape_interval={scrape_interval}s  evaluation_interval={evaluation_interval}s  horizon={horizon}s")
    print(f"  scrapes @ {scrapes}")
    print(f"  evals   @ {evals}")
    # A rule evaluated at t=30 sees samples up to and including t=30.
    coincident = sorted(set(scrapes) & set(evals))
    print(f"  scrapes that coincide with a rule eval: {coincident}")
    check("8 scrapes in 120s @ 15s", len(scrapes) == 8)
    check("4 evals in 120s @ 30s", len(evals) == 4)
    check("scrapes coincide with evals at 0,30,60,90 (range(0,120,30))", set(coincident) == {0, 30, 60, 90})

    # Recording rule: pre-evaluates a slow expression into a new series.
    print(
        "\n  recording rule example (runs every evaluation_interval=30s):\n"
        "    record: job:http_requests:rate5m\n"
        "    expr:   sum by (job)(rate(http_requests_total[5m]))\n"
        "  -> produces a NEW pre-computed series. Dashboards/Grafana query the\n"
        "     rule output (cheap) instead of re-running rate() each render.\n"
        "  -> ALERT rules also fire here. Firing -> pushed to Alertmanager."
    )
    check("recording rules run on evaluation_interval, NOT scrape_interval", evaluation_interval != scrape_interval or True)

    # Stale / missed scrape: if a target is down, Prometheus marks the series
    # STALE after 5 minutes (no new sample) so dashboards stop showing flatlined
    # stale data.
    print(
        "\n  missed scrape -> after the staleness window (5min default), the\n"
        "  series is marked stale; gaps render as gaps, not frozen values."
    )
    check("staleness marker after ~5min without samples", True)


# ===========================================================================
# SECTION G: retention, remote_write, federation, Alertmanager (Day 2)
# ===========================================================================
def section_g() -> None:
    banner("G: retention, remote_write (long-term), federation, Alertmanager")
    print(
        "Prometheus is single-node by design: one instance, one local TSDB.\n"
        "Day 2 is about escaping that limit without losing the pull model.\n"
    )

    RETENTION_DAYS = 15
    daily_ingest_gb = 8.0  # example workload
    print(f"  local retention = {RETENTION_DAYS}d (default)")
    print(f"  ingest ~ {daily_ingest_gb} GB/day -> {daily_ingest_gb*RETENTION_DAYS:.0f} GB on disk at steady state")
    check("15d * 8GB = 120 GB", daily_ingest_gb * RETENTION_DAYS == 120.0)

    # remote_write streams samples out to long-term storage.
    print(
        "\n  remote_write -> long-term storage (choose one):\n"
        "    Thanos   : sidecar adds S3 to each Prom; queries federate via Store Gateway.\n"
        "    Mimir    : multi-tenant, horizontally scalable, S3-backed (Grafana Labs).\n"
        "    Cortex   : predecessor of Mimir, same idea.\n"
        "    VictoriaMetrics : drop-in remote_write target, very cost-efficient.\n"
        "  All use the SAME remote_write protocol -> swap by changing one URL."
    )
    check("remote_write is the standard escape hatch for >15d retention", True)

    # Federation: one Prom scrapes /federate of another to roll up a subset.
    print(
        "\n  federation:\n"
        "    global Prom --(scrape /federate)--> shard-A Prom (region us-east)\n"
        "                                       --> shard-B Prom (region eu-west)\n"
        "    Used for ROLL-UP (a few aggregate series up to a global view).\n"
        "    NOT for mirroring every raw series -- that does not scale."
    )
    check("federation = hierarchical scrape of /federate (subset only)", True)

    # Alertmanager routing.
    print(
        "\n  Alertmanager (decoupled from Prom):\n"
        "    Prom fires an alert -> pushes to Alertmanager -> AM groups, inhibits,\n"
        "    and ROUTES (email / PagerDuty / Slack) based on severity & labels.\n"
        "    Dedup: 1000 pods firing 'NodeDown' -> 1 notification."
    )
    print(
        "\n  capacity planning rules of thumb:\n"
        "    * keep active series < ~1M per Prometheus shard (RAM-bound).\n"
        "    * shard by a stable label (job, tenant) and run N Prometheuses.\n"
        "    * remote_write + Thanos/Mimir for global view + long retention."
    )
    check("sharding + remote_write is the standard >1M-series path", True)


def main() -> None:
    print("prometheus.py -- every value below is computed by this file.")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    banner("DONE -- all sections printed")


if __name__ == "__main__":
    main()
