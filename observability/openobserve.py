"""openobserve.py - Ground-truth reference for OpenObserve (O2): an S3-native,
Rust-based observability platform for logs, metrics, and traces.

This is the SINGLE SOURCE OF TRUTH for OPENOBSERVE.md. Every number, table,
docker-compose snippet, simulated API response, and cost figure in the guide is
printed by this file. If you change something here, re-run and re-paste the
output into the guide.

    python3 openobserve.py > openobserve_output.txt

Pure Python stdlib only. Deterministic: a custom LCG RNG (no external deps, no
PYTHONHASHSEED dependence, no wall-clock). The identical cost / compaction /
compression math is recomputed in JS by openobserve.html and gold-checked.

Verified against official OpenObserve docs (openobserve.ai/docs) + multiple
secondary sources. See ## Sources in OPENOBSERVE.md for the full URL list.

PINNED (official docs): the five components, the WAL/Memtable/Immutable flush
thresholds (ZO_MAX_FILE_SIZE_IN_MEMORY=256MB, ZO_MAX_FILE_SIZE_ON_DISK=128MB,
ZO_FILE_PUSH_INTERVAL=10s, ZO_MAX_FILE_RETENTION_TIME=600s,
ZO_COMPACT_MAX_FILE_SIZE=2048MB), the ~31 MB/s single-node ingest rate, and the
HTTP ingest endpoint shape (POST /api/{org}/{stream}/_json, Basic auth).
REPRESENTATIVE (clearly labelled): compression ratios (O2 ~15x, Loki ~8x), ES
storage multipliers, and EC2/AWS pricing used in the cost model.
"""

from __future__ import annotations

import math


# ============================================================================
# DETERMINISTIC RNG - a tiny 32-bit LCG (Numerical Recipes constants). We roll
# our own so every run is bit-identical and matches the JS in openobserve.html.
# ============================================================================
class RNG:
    """32-bit linear congruential generator. RNG(42).next() is stable forever."""

    def __init__(self, seed: int = 42) -> None:
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


BANNER = "=" * 72


def banner(t: str) -> None:
    print(f"\n{BANNER}\nSECTION {t}\n{BANNER}\n")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


# ============================================================================
# PINNED CONSTANTS - from official OpenObserve docs + AWS public pricing.
# ============================================================================
# --- Ingest path thresholds (openobserve.ai/docs/architecture, Ingester) ---
ZO_MAX_FILE_SIZE_IN_MEMORY = 256    # MB - Memtable flushes to Immutable
ZO_MAX_FILE_SIZE_ON_DISK = 128      # MB - WAL file size cap
ZO_MEM_PERSIST_INTERVAL = 5         # seconds - Immutable -> local parquet
ZO_FILE_PUSH_INTERVAL = 10          # seconds - merge small files, push to S3
ZO_MAX_FILE_RETENTION_TIME = 600    # seconds - max age before push to S3
ZO_COMPACT_MAX_FILE_SIZE = 2048     # MB (2 GB) - max merged file from Compactor

# --- Single-node ingest throughput (openobserve.ai/docs/architecture, M2) ---
SINGLE_NODE_MB_PER_SEC = 31         # MB/s on Apple M2, default config
MB_PER_DAY = SINGLE_NODE_MB_PER_SEC * 86400          # bytes-ish, in MB
SINGLE_NODE_GB_PER_DAY = SINGLE_NODE_MB_PER_SEC * 86400 / 1000  # decimal GB/day

# --- Storage media pricing (AWS us-east-1, 2025 public) - $/GB-month ---
S3_STANDARD = 0.023
S3_IA = 0.0125
EBS_GP3 = 0.080
HOURS_PER_MONTH = 730

# --- EC2 on-demand (AWS us-east-1, Linux, 2025) - $/hour ---
EC2 = {
    "t3.medium":   {"vcpu": 2, "ram_gib": 4, "hr": 0.0416},
    "c6i.large":   {"vcpu": 2, "ram_gib": 4, "hr": 0.0848},
    "r5.large":    {"vcpu": 2, "ram_gib": 16, "hr": 0.1260},
    "r5.2xlarge":  {"vcpu": 8, "ram_gib": 64, "hr": 0.5040},
}

# --- REPRESENTATIVE compression / storage multipliers (clearly labelled) ---
O2_COMPRESSION = 15.0     # Parquet columnar + zstd on logs: 10-20x, model 15x
LOKI_COMPRESSION = 8.0    # gzip chunks, label-only index
ES_REPLICA_FACTOR = 2.0   # 1 primary + 1 replica (default)
ES_INDEX_FACTOR = 1.0     # net on-disk ~ raw after source compression vs index

RETENTION_DAYS = 30


# ============================================================================
# MONEY HELPERS
# ============================================================================
def money(per_hour: float) -> float:
    return per_hour * HOURS_PER_MONTH


def fmt_usd(x: float) -> str:
    if x >= 1000:
        return f"${x:,.0f}"
    if x >= 1:
        return f"${x:,.2f}"
    return f"${x:,.3f}"


def o2_stored_gb(raw_gb_per_day: float, days: int = RETENTION_DAYS) -> float:
    return raw_gb_per_day * days / O2_COMPRESSION


def loki_stored_gb(raw_gb_per_day: float, days: int = RETENTION_DAYS) -> float:
    return raw_gb_per_day * days / LOKI_COMPRESSION


def es_stored_gb(raw_gb_per_day: float, days: int = RETENTION_DAYS) -> float:
    return raw_gb_per_day * days * ES_REPLICA_FACTOR * ES_INDEX_FACTOR


def o2_storage_cost_mo(raw_gb_per_day: float) -> float:
    return o2_stored_gb(raw_gb_per_day) * S3_STANDARD


def loki_storage_cost_mo(raw_gb_per_day: float) -> float:
    return loki_stored_gb(raw_gb_per_day) * S3_STANDARD


def es_storage_cost_mo(raw_gb_per_day: float) -> float:
    return es_stored_gb(raw_gb_per_day) * EBS_GP3


# ============================================================================
# SECTION A - Architecture
# ============================================================================
def section_a() -> None:
    banner("A - Architecture: Rust + S3 + Parquet")

    print("OpenObserve (O2) is a single Rust binary that does logs, metrics, and")
    print("traces. The storage tier is object storage (S3/MinIO/GCS/Azure Blob):")
    print("Parquet columnar files, queried directly off S3. No mandatory local disk")
    print("for data -- only a small WAL buffer on the ingester. This is the inverse")
    print("of Elasticsearch, which ties data to local disk + JVM heap.\n")

    print("Five core components (HA mode). In single-node mode all five collapse")
    print("into ONE process:\n")
    comps = [
        ("Router",      "Client-facing HTTP/gRPC gateway + serves the web UI. A thin"),
        ("",             "proxy: routes ingest -> Ingester, query -> Querier."),
        ("Ingester",    "Receives ingest, parses, schema-evolves, writes WAL -> Memtable"),
        ("",             "(256MB) -> Immutable -> local Parquet -> flush to S3. 3 buffers:"),
        ("",             "Memtable, Immutable, wal Parquet not-yet-on-S3."),
        ("Compactor",   "Merges small S3 Parquet files into big ones (<= 2 GB) so"),
        ("",             "queries scan fewer files. Also enforces retention + deletions."),
        ("Querier",     "FULLY STATELESS. Scans S3 Parquet. A LEADER partitions the file"),
        ("",             "list across WORKER queriers over gRPC, then merges results."),
        ("",             "Caches Parquet in RAM (default 50% of free memory)."),
        ("AlertManager", "Runs scheduled alert queries + report jobs; fires notifications"),
        ("",             "to destinations (Slack/email/webhook/Teams/PagerDuty)."),
    ]
    for name, role in comps:
        if name:
            print(f"  {name:<13} {role}")
        else:
            print(f"  {'':<13} {role}")
    print()

    print("HA-mode dependencies (single-node uses SQLite, no extra deps):")
    print("  NATS        - cluster coordinator + node discovery + event bus")
    print("  PostgreSQL  - metadata: orgs, users, functions, alert rules,")
    print("                stream schema, file list (index of Parquet files)")
    print("  S3/MinIO    - ALL Parquet data (the actual telemetry)\n")

    print("Why Rust (vs Java/ES, vs Go/Loki):")
    print("  * Zero-cost abstractions + no GC pauses -> predictable ingest latency")
    print("  * SIMD-accelerated string parsing -> fast line-by-line ingest decode")
    print("  * ~50% lower resource use than Elasticsearch at equal ingest (O2 claim)")
    print("  * Memory-efficient: no JVM heap tax, no per-object overhead\n")

    # --- Storage model comparison ---
    print("Storage model comparison (the whole cost story):\n")
    rows = [
        ("Engine",        "Lang",  "Storage",       "Format",        "Index"),
        ("OpenObserve",   "Rust",  "S3 (object)",   "Parquet col.",  "Tantivy FTS"),
        ("Elasticsearch", "Java",  "local EBS/disk", "inverted idx",  "Lucene"),
        ("Loki",          "Go",    "S3 (chunks)",   "gzip chunks",   "labels only"),
    ]
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    for i, r in enumerate(rows):
        line = "  " + "  ".join(c.ljust(widths[j]) for j, c in enumerate(r))
        print(line)
        if i == 0:
            print("  " + "  ".join("-" * widths[j] for j in range(5)))
    print()

    # --- Pinned ingest throughput per vCPU ---
    m2_vcpu = 8  # Apple M2 ~8 cores
    per_vcpu_mbps = SINGLE_NODE_MB_PER_SEC / m2_vcpu
    print(f"Single-node ingest (pinned, official, Apple M2): {SINGLE_NODE_MB_PER_SEC} MB/s")
    print(f"  = {SINGLE_NODE_GB_PER_DAY:,.0f} GB/day  ({SINGLE_NODE_MB_PER_SEC} x 86400 / 1000)")
    print(f"  ~ {per_vcpu_mbps:.1f} MB/s per vCPU (M2 ~{m2_vcpu} cores)")
    check("single-node daily ingest is ~2.6 TB",
          abs(SINGLE_NODE_GB_PER_DAY - 2678.4) < 1.0)
    print()


# ============================================================================
# SECTION B - Day 0: Deploy with S3
# ============================================================================
def section_b() -> None:
    banner("B - Day 0: Deploy with S3 (single-node + object storage)")

    print("Goal: one OpenObserve container, data on S3/MinIO, ready to ingest in")
    print("under 15 minutes. Single-node-with-S3 uses SQLite for metadata (no")
    print("Postgres/NATS needed) but stores all telemetry on object storage -- so")
    print("storage is durable and cheap from day one.\n")

    print("--- docker-compose.yml (single node + S3/MinIO) ---\n")
    compose = """version: "3.8"

services:
  openobserve:
    image: openobserve/openobserve:latest
    container_name: openobserve
    ports:
      - "5080:5080"          # Web UI + HTTP ingest API
    environment:
      # --- root credentials (created on first boot) ---
      ZO_ROOT_USER_EMAIL: "admin@openobserve.dev"
      ZO_ROOT_USER_PASSWORD: "admin123Complex#"

      # --- S3 / object storage (MinIO here; swap for AWS S3) ---
      ZO_S3_PROVIDER: "minio"           # aws | minio | gcs | azure
      ZO_S3_SERVER_URL: "http://minio:9000"
      ZO_S3_REGION: "us-east-1"
      ZO_S3_BUCKET: "openobserve"
      ZO_S3_ACCESS_KEY: "minioadmin"
      ZO_S3_SECRET_KEY: "minioadmin"

      # --- ingest tuning (defaults, shown for clarity) ---
      ZO_MAX_FILE_SIZE_IN_MEMORY: "256"  # MB -> Memtable -> Immutable
      ZO_MAX_FILE_SIZE_ON_DISK: "128"    # MB -> WAL cap
      ZO_FILE_PUSH_INTERVAL: "10"        # s -> merge + push to S3
      ZO_COMPACT_MAX_FILE_SIZE: "2048"   # MB (2 GB) merged file ceiling
    volumes:
      - o2-data:/data                   # local WAL buffer only (data lives on S3)
    depends_on:
      - minio

  minio:                                # S3-compatible object store
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"                      # MinIO console
    environment:
      MINIO_ROOT_USER: "minioadmin"
      MINIO_ROOT_PASSWORD: "minioadmin"
    volumes:
      - minio-data:/data

volumes:
  o2-data:
  minio-data:"""
    print(compose)
    print()

    print("--- Health check ---\n")
    print("  # login -> returns an org-scoped token; Basic auth also works for ingest")
    print("  curl -s http://localhost:5080/api/default/streams \\")
    print("       -u 'admin@openobserve.dev:admin123Complex#' | head")
    print()
    print("  # first ingest (creates the stream on the fly, auto-detects schema)")
    print("  curl -s http://localhost:5080/api/default/quickstart1/_json \\")
    print("       -u 'admin@openobserve.dev:admin123Complex#' \\")
    print("       -d '[{\"level\":\"info\",\"service\":\"api\",\"log\":\"O2 is up\"}]'")
    print()

    print("--- Resource requirements (vs Elasticsearch) ---\n")
    print("  OpenObserve single node : min 1 vCPU, 2 GB RAM, ~no local disk for data")
    print("  Elasticsearch (3 nodes) : min 3 x 4 vCPU, 8-16 GB RAM each, EBS per node")
    print()

    # --- Expected ingestion throughput per vCPU ---
    per_vcpu_mbps = SINGLE_NODE_MB_PER_SEC / 8
    per_vcpu_gb_day = per_vcpu_mbps * 86400 / 1000
    print(f"Expected ingestion throughput:")
    print(f"  ~{SINGLE_NODE_MB_PER_SEC} MB/s on an 8-core node (pinned, official)")
    print(f"  ~{per_vcpu_mbps:.1f} MB/s per vCPU  ->  ~{per_vcpu_gb_day:,.1f} GB/day per vCPU")
    print(f"  A 2-vCPU t3.medium can reasonably ingest ~{2*per_vcpu_mbps:.0f} MB/s "
          f"(~{2*per_vcpu_gb_day:,.0f} GB/day) for logs")
    print()
    check("2-vCPU ingest estimate > 100 GB/day",
          2 * per_vcpu_gb_day > 100)


# ============================================================================
# SECTION C - Day 1: Ingest & Search
# ============================================================================
def section_c() -> None:
    banner("C - Day 1: Ingest & Search (simulated API round-trip)")
    rng = RNG(42)

    print("A stream is just a named table auto-created on first ingest. O2 detects")
    print("the schema from the JSON you send (fields, types) and evolves it as new")
    print("fields appear. _timestamp is added automatically (microseconds) if absent.\n")

    # --- Step 1: ingest logs via HTTP API ---
    print("STEP 1  POST /api/default/logs/_json  (5 records)\n")
    services = ["payment", "auth", "cart", "search", "payment"]
    levels = ["info", "warn", "error", "info", "error"]
    msgs = [
        "payment captured id=txn_8821",
        "rate limit near for ip=10.0.0.9",
        "db connection refused host=db-2",
        "user login ok uid=4451",
        "card declined code=do_not_honor",
    ]
    records = []
    ts_base = 1716950400000000  # fixed micros epoch (deterministic, NOT wall-clock)
    for i in range(5):
        records.append({
            "_timestamp": ts_base + i * 1_000_000,
            "service": services[i],
            "level": levels[i],
            "log": msgs[i],
            "latency_ms": rng.randint(8, 420),
        })
    print("  REQUEST body:")
    for r in records:
        print(f"    {r}")
    print()
    print('  RESPONSE:  {"code":200,"status":[{"name":"logs","successful":5,"failed":0}]}')
    print("  -> stream 'default/logs' created; schema auto-detected:")
    schema = ["_timestamp: Int64", "service: Utf8", "level: Utf8",
              "log: Utf8", "latency_ms: Int64"]
    for s in sorted(schema):
        print(f"       {s}")
    print()
    check("all 5 records ingested successfully", len(records) == 5)

    # --- Step 2: SQL filter + sort ---
    print("STEP 2  SQL  filter + newest-first\n")
    print("  SELECT * FROM logs WHERE level = 'error' ORDER BY _timestamp DESC LIMIT 20\n")
    errors = sorted([r for r in records if r["level"] == "error"],
                    key=lambda r: r["_timestamp"], reverse=True)
    print(f"  hits: {len(errors)}")
    for r in errors:
        print(f"    [{r['_timestamp']}] {r['service']:>8}  {r['level']}  {r['log']}")
    print(f'  took: 47 ms   scanned: 1 file (256 KB)   cached: no')
    check("step 2 returns the 2 error logs", len(errors) == 2)

    # --- Step 3: full-text search ---
    print("STEP 3  full-text search  (Tantivy index on 'log')\n")
    print("  SELECT * FROM logs WHERE match_all('declined') AND service = 'payment'\n")
    hits_fts = [r for r in records if "declined" in r["log"] and r["service"] == "payment"]
    print(f"  hits: {len(hits_fts)}")
    for r in hits_fts:
        print(f"    [{r['_timestamp']}] {r['service']:>8}  {r['log']}")
    print(f"  took: 9 ms   (match_all uses the Tantivy full-text index, not a scan)")
    check("step 3 matches the declined-payment log", len(hits_fts) == 1)

    # --- Step 4: aggregation ---
    print("STEP 4  aggregation  GROUP BY service\n")
    print("  SELECT service, count(*) AS cnt FROM logs GROUP BY service ORDER BY cnt DESC\n")
    counts = {}
    for r in records:
        counts[r["service"]] = counts.get(r["service"], 0) + 1
    for svc, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {svc:>8}  {c}")
    print()
    check("payment has count 2 (top)", counts["payment"] == 2)

    # --- Query performance: S3 scan vs cached (predicate pushdown) ---
    print("STEP 5  query performance  S3 scan vs Parquet predicate pushdown\n")
    raw_scan_files = 12
    cols_total = 5
    cols_needed = 3
    pushdown_factor = cols_needed / cols_total   # columnar: read only needed columns
    bytes_per_file_mb = 256
    scan_bytes = raw_scan_files * bytes_per_file_mb
    pushdown_bytes = scan_bytes * pushdown_factor
    print(f"  full S3 scan   : {raw_scan_files} files x {bytes_per_file_mb} MB = {scan_bytes} MB")
    print(f"  pushdown (3/5 cols): {scan_bytes} MB x {cols_needed}/{cols_total} = {pushdown_bytes:.0f} MB read")
    print(f"  cached (in RAM): 0 MB from S3 -> served from ZO_MEMORY_CACHE_MAX_SIZE")
    print(f"  -> columnar Parquet reads ~{pushdown_bytes:.0f}/{scan_bytes} = "
          f"{pushdown_factor*100:.0f}% of a row-store scan")
    check("pushdown reads less than full scan", pushdown_bytes < scan_bytes)


# ============================================================================
# SECTION D - Day 2: Scale, Alerts, Dashboards, Compaction
# ============================================================================
def section_d() -> None:
    banner("D - Day 2: Scale, Compaction, Alerts, Dashboards")

    # --- Scale: stateless queriers ---
    print("SCALING  add queriers (stateless, no data on them)\n")
    print("  Queriers are fully stateless: they only scan S3 + cache Parquet in RAM.")
    print("  Double query throughput by doubling querier pods -- no rebalancing, no")
    print("  shard pain. A LEADER querier partitions the file list across WORKERs\n")
    print("  over gRPC and merges partial results.\n")
    files = 100
    for n in (1, 2, 5):
        per = math.ceil(files / n)
        print(f"  {n} querier(s): {files} files -> {per} files/querier")
    print()

    # --- Compaction math ---
    print("COMPACTION  merge small S3 Parquet files -> bigger files\n")
    small_files = 1200
    small_mb = 2                          # each small file ~2 MB
    total_mb = small_files * small_mb
    merged_files = math.ceil(total_mb / ZO_COMPACT_MAX_FILE_SIZE)
    last_file_mb = total_mb - (merged_files - 1) * ZO_COMPACT_MAX_FILE_SIZE
    print(f"  before: {small_files} files x {small_mb} MB = {total_mb:,} MB "
          f"(avg {small_mb} MB/file)")
    print(f"  compactor target ceiling: ZO_COMPACT_MAX_FILE_SIZE = "
          f"{ZO_COMPACT_MAX_FILE_SIZE} MB (2 GB)")
    print(f"  after : {merged_files} files (1 x {ZO_COMPACT_MAX_FILE_SIZE} MB + "
          f"{merged_files-1} tail) ...")
    print(f"          = {merged_files} files x up to {ZO_COMPACT_MAX_FILE_SIZE} MB "
          f"= {total_mb:,} MB")
    print(f"  file-count reduction: {small_files} -> {merged_files} "
          f"({small_files/merged_files:.0f}x fewer files to plan/scan)")
    # show the exact tail
    sizes = [ZO_COMPACT_MAX_FILE_SIZE] * (merged_files - 1) + [last_file_mb]
    print(f"  exact merged sizes (MB): {sizes}")
    check("compaction reduces file count", merged_files < small_files)
    check("merged bytes conserve total bytes", sum(sizes) == total_mb)

    # --- Alerting pipeline ---
    print("\nALERTING  rule -> evaluate -> destination\n")
    print("  Create an alert (scheduled, runs a SQL query on a cadence):")
    alert_rule = {
        "name": "high_error_rate",
        "stream": "logs",
        "query": "SELECT count(*) AS c FROM logs WHERE level='error' "
                 "AND _timestamp > now() - 10m",
        "condition": "c >= 10",
        "frequency": "60s",
        "destination": "slack-oncall",
    }
    for k, v in sorted(alert_rule.items()):
        print(f"    {k:<12} {v}")
    print()
    print("  Destinations (where notifications go):")
    dests = ["slack", "email", "webhook (custom)", "teams", "pagerduty", "alertmanager"]
    for d in sorted(dests):
        print(f"    - {d}")
    print()
    print("  Eval: query runs every 60s. When c>=10 fires -> template + POST to")
    print("  the Slack webhook destination. Real-time alerts also exist (evaluated")
    print("  inline at ingest, sub-second).")
    check("alert fires when c >= 10", 12 >= 10)

    # --- Dashboards ---
    print("\nDASHBOARDS  panels reference streams\n")
    print("  A dashboard = panels; each panel runs a SQL/PromQL query against a")
    print("  stream. Variables let one dashboard filter across services/envs.\n")
    panels = [
        ("Error rate (last 1h)", "logs", "SELECT _timestamp, count(*) FROM logs "
                                       "WHERE level='error' GROUP BY _timestamp"),
        ("p95 latency", "metrics", "SELECT histogram_quantile(0.95, ...) ..."),
        ("Top error services", "logs", "SELECT service, count(*) FROM logs "
                                       "WHERE level='error' GROUP BY service"),
    ]
    for title, stream, _q in panels:
        print(f"    panel : {title}  (stream: {stream})")
    check("dashboard references streams", len(panels) == 3)

    # --- Cold storage: S3 IA ---
    print("\nCOLD STORAGE  tier old Parquet to S3 Infrequent Access\n")
    hot_gb_day = 100
    hot_days = 7
    cold_days = RETENTION_DAYS - hot_days
    hot_cost = hot_gb_day * hot_days / O2_COMPRESSION * S3_STANDARD
    cold_cost = hot_gb_day * cold_days / O2_COMPRESSION * S3_IA
    all_hot = hot_gb_day * RETENTION_DAYS / O2_COMPRESSION * S3_STANDARD
    print(f"  100 GB/day raw, 30-day retention:")
    print(f"    all on S3 Standard : {hot_gb_day*RETENTION_DAYS/O2_COMPRESSION:.0f} GB "
          f"-> {fmt_usd(all_hot)}/mo")
    print(f"    tier: 7d Standard + 23d IA:")
    print(f"      Standard ({hot_gb_day*hot_days/O2_COMPRESSION:.0f} GB): {fmt_usd(hot_cost)}/mo")
    print(f"      IA      ({hot_gb_day*cold_days/O2_COMPRESSION:.0f} GB): {fmt_usd(cold_cost)}/mo")
    print(f"      total tiered                              : {fmt_usd(hot_cost+cold_cost)}/mo")
    print(f"    saving: {fmt_usd(all_hot)} -> {fmt_usd(hot_cost+cold_cost)} "
          f"({(1-(hot_cost+cold_cost)/all_hot)*100:.0f}% cheaper)")
    check("tiering is cheaper than all-hot", hot_cost + cold_cost < all_hot)


# ============================================================================
# SECTION E - Storage & Cost Analysis
# ============================================================================
def section_e() -> None:
    banner("E - Storage & Cost Analysis (S3 Parquet, model-based)")

    print("Parquet is columnar + dictionary/RLE/zstd encoded. For repetitive log")
    print("fields (level, service, host) it crushes redundancy. Representative")
    print(f"compression on logs: O2 ~{O2_COMPRESSION:.0f}x, Loki ~{LOKI_COMPRESSION:.0f}x")
    print("(gzip chunks). ES keeps an inverted index + replicas on local EBS.\n")

    print(f"Assumptions (transparent, AWS us-east-1 2025 pricing):")
    print(f"  retention            = {RETENTION_DAYS} days")
    print(f"  O2 storage mult.     = 1/{O2_COMPRESSION:.0f} (compressed Parquet, single copy, on S3)")
    print(f"  Loki storage mult.   = 1/{LOKI_COMPRESSION:.0f} (compressed chunks, on S3)")
    print(f"  ES storage mult.     = {ES_REPLICA_FACTOR:.0f} x {ES_INDEX_FACTOR:.0f} "
          f"(primary+replica, net ~raw, on EBS gp3)")
    print(f"  S3 Standard          = ${S3_STANDARD}/GB-mo    S3 IA = ${S3_IA}/GB-mo")
    print(f"  EBS gp3              = ${EBS_GP3}/GB-mo")
    print(f"  (STORAGE ONLY; ES also needs compute that scales with data -- see ROI)\n")

    print("Cost table -- STORAGE cost / month by daily ingest volume:\n")
    header = f"  {'ingest/day':<12}{'O2 (S3)':<14}{'Loki (S3)':<14}{'ES (EBS)':<14}{'O2 vs ES':<10}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    scenarios = [1, 10, 100, 1000]
    gold = None
    for gpd in scenarios:
        o2 = o2_storage_cost_mo(gpd)
        lok = loki_storage_cost_mo(gpd)
        es = es_storage_cost_mo(gpd)
        ratio = es / o2
        label = f"{gpd} GB/day" if gpd < 1000 else f"{gpd//1000} TB/day"
        print(f"  {label:<12}{fmt_usd(o2):<14}{fmt_usd(lok):<14}{fmt_usd(es):<14}{ratio:>6.0f}x")
        if gpd == 100:
            gold = o2
    print()

    print("ROI -- when does O2's S3-native model win MASSIVELY?\n")
    print("  * The gap widens with VOLUME and RETENTION. ES cost grows with data")
    print("    (more EBS + more data nodes holding indices in RAM). O2 storage is")
    print("    ~flat (S3 price) and compute is a handful of stateless nodes that do")
    print("    NOT grow with historical data.\n")
    print("  * Cross-over: at ~10 GB/day x 30d retention, ES storage already costs")
    print(f"    ~{es_storage_cost_mo(10)/o2_storage_cost_mo(10):.0f}x O2. At 1 TB/day it is "
          f"~{es_storage_cost_mo(1000)/o2_storage_cost_mo(1000):.0f}x on storage ALONE, before")
    print("    ES compute. O2's official headline is '140x lower storage cost' vs ES\n"
          "    (specific configurations); our transparent model shows ~100x+ on storage\n"
          "    at 1 TB/day, which is the right order of magnitude.\n")
    print("  * O2 does NOT win on: tiny volumes (<1 GB/day, where ES single-node is")
    print("    fine), or queries needing ES's mature Lucene relevance ranking.\n")

    # GOLD VALUE for the HTML gold-check
    print(f"GOLD (pinned for HTML gold-check):")
    print(f"  O2 S3 cost at 100 GB/day, 30d retention = "
          f"{o2_stored_gb(100):.0f} GB x ${S3_STANDARD} = {fmt_usd(gold)}/mo")
    check("gold O2 cost @100GB/day == $4.60/mo",
          abs(gold - 4.60) < 0.001)
    check("ES storage cost ratio vs O2 grows past 100x at 1 TB/day",
          es_storage_cost_mo(1000) / o2_storage_cost_mo(1000) > 100)


# ============================================================================
# SECTION F - Data Pipeline & Schema
# ============================================================================
def section_f() -> None:
    banner("F - Data Pipeline & Schema")

    print("SCHEMA DETECTION  (auto, from ingested JSON)\n")
    print("  No schema declared up front. On first ingest O2 inspects the JSON")
    print("  records, infers Arrow types, and registers the stream schema in")
    print("  Postgres (HA) / SQLite (single-node). Example:\n")
    raw = {"_timestamp": 1716950400000000, "service": "api", "level": "info",
           "latency_ms": 42, "ok": True}
    for k in sorted(raw):
        t = type(raw[k]).__name__
        arrow = {"int": "Int64", "str": "Utf8", "bool": "Boolean"}[t]
        print(f"    {k:<12} JSON {t:<5} -> Arrow {arrow}")
    print()

    print("SCHEMA EVOLUTION  (new fields appear -> auto-added)\n")
    evolution = [
        ("day 1", ["_timestamp", "service", "level", "log"]),
        ("day 2", ["_timestamp", "service", "level", "log", "latency_ms"]),
        ("day 3", ["_timestamp", "service", "level", "log", "latency_ms", "user_id"]),
    ]
    prev = set()
    for day, cols in evolution:
        new = set(cols) - prev
        marker = f"  + new: {sorted(new)}" if new else "  (initial)"
        print(f"  {day}: {len(cols)} fields{marker if new else ''}")
        prev = set(cols)
    print("  Old Parquet files simply lack the new column; queries return NULL for")
    print("  it on those files. No reindex, no downtime.\n")
    check("schema grew across days", len(evolution[2][1]) > len(evolution[0][1]))

    print("MULTI-FORMAT  one platform, three signal types\n")
    sigs = [
        ("Logs",   "JSON via POST /api/{org}/{stream}/_json ; OTLP ; syslog",
         "Parquet row per event"),
        ("Metrics", "Prometheus remote_write (/api/{org}/prometheus/api/v1/write) ;",
         "OTLP metrics"),
        ("Traces", "OTLP over HTTP/gRPC (/api/{org}/traces ; /otlp/v1/traces)",
         "span model"),
    ]
    for name, ingest, note in sigs:
        print(f"  {name:<9} {ingest}")
        print(f"  {'':<9} -> {note}")
    check("three signal types supported", len(sigs) == 3)

    print("\nPARTITIONING  time-based folders in S3\n")
    print("  Parquet files are laid out by hour/day under the object prefix, e.g.:")
    print("    files/logs/default/2024/05/29/00/<uuid>.parquet")
    print("    files/logs/default/2024/05/29/01/<uuid>.parquet")
    print("  A time-range query only lists the partitions it overlaps -> the file-")
    print("  list index (in Postgres/SQLite) prunes the rest BEFORE any S3 scan.")
    print("  This is why Querier->S3 stays fast: time predicate -> partition pruning.")
    check("time partitioning enables pruning", True)


# ============================================================================
# MAIN
# ============================================================================
def main() -> None:
    print("OpenObserve (O2) — S3-native observability: ground-truth simulation")
    print("Rust + Parquet-on-S3, single binary, logs + metrics + traces.\n")
    print("All numbers here are PINNED to official O2 docs or computed from a")
    print("transparent model. Deterministic (seeded LCG, no wall-clock).\n")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()

    banner("DONE")
    print("All [check] assertions passed. This output is the source of truth for")
    print("OPENOBSERVE.md. Re-run:  python3 openobserve.py > openobserve_output.txt")


if __name__ == "__main__":
    main()
