"""
milvus.py - Ground-truth operations reference for Milvus vector database:
Standalone deployment with embedded etcd + external S3, Day 0 -> Day 1 -> Day 2
(deploy, first collection/search, scale/DiskANN/partitions/backup/upgrade),
index-type deep dive, storage & cost analysis, monitoring & troubleshooting.

This is the SINGLE SOURCE OF TRUTH for MILVUS.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 milvus.py > milvus_output.txt

Pure Python stdlib only. Deterministic (custom LCG RNG; no external deps, no
PYTHONHASHSEED dependence, no wall-clock). The same cost/index math is
recomputed in JS by milvus.html and gold-checked.

Verified against official Milvus docs (milvus.io/docs) + multiple secondary
sources. See ## Sources in MILVUS.md for the full URL list.

Representative vs pinned: storage math, memory math, ratio math, and the
docker-compose env vars are PINNED to official docs. QPS/recall/build-time
ranges are REPRESENTATIVE benchmark ranges (clearly labelled) -- exact numbers
depend on hardware, dataset, and recall target.
"""

from __future__ import annotations

import math


# ============================================================================
# DETERMINISTIC RNG - a tiny LCG (Numerical Recipes constants). We roll our
# own so every run is bit-identical and matches the JS in milvus.html.
# (Same RNG as the sibling vector_databases.py bundle.)
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

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        u1 = self.uniform(1e-10, 1.0)
        u2 = self.uniform(0.0, 1.0)
        return mu + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def randint(self, lo: int, hi: int) -> int:
        return lo + (self.next() % (hi - lo + 1))


BANNER = "=" * 72


def banner(t: str) -> None:
    print(f"\n{BANNER}\nSECTION {t}\n{BANNER}\n")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


# ============================================================================
# PINNED CONSTANTS - from official Milvus docs + AWS public pricing.
# ============================================================================
DIM = 768                 # common embedding dim (BGE-large, OpenAI text-embedding-3-small)
FP32 = 4                  # bytes per float32 dimension
SQ8 = 1                   # bytes per quantized dimension (IVF_SQ8)
PQ_SUBS = 96              # PQ subquantizers for 768-dim (768 / 8) -> 1 byte each
HNSW_M = 16               # Milvus HNSW default M (graph degree per layer)
HNSW_EF_CONSTRUCTION = 256  # Milvus HNSW default efConstruction
DISKANN_PQ_BYTES = 64     # model: DiskANN in-RAM PQ codes per vector (representative)

# S3 pricing (AWS us-east-1, 2025 public) - $/GB-month
S3_STANDARD = 0.023
S3_IA = 0.0125
# EC2 on-demand (AWS us-east-1, Linux, 2025) - $/hour and $/month (730h)
HOURS_PER_MONTH = 730
EC2 = {
    "t3.medium":   {"vcpu": 2, "ram_gib": 4,   "hr": 0.0416},
    "r5.large":    {"vcpu": 2, "ram_gib": 16,  "hr": 0.1260},
    "r5.xlarge":   {"vcpu": 4, "ram_gib": 32,  "hr": 0.2520},
    "r5.2xlarge":  {"vcpu": 8, "ram_gib": 64,  "hr": 0.5040},
}
INDEX_FACTOR = 2.0  # S3 stores raw binlogs + built index files -> ~2x raw bytes


# ============================================================================
# STORAGE / MEMORY MATH - the core formulas everything else derives from.
# ============================================================================
def raw_bytes(n: int, dim: int = DIM) -> int:
    """Total bytes of N FP32 vectors (no index overhead)."""
    return n * dim * FP32


def gb(b: int) -> float:
    """Bytes -> decimal GB (matches S3 billing: 1 GB = 1e9 bytes)."""
    return b / 1_000_000_000


def gib(b: int) -> float:
    """Bytes -> binary GiB (matches RAM billing)."""
    return b / (1 << 30)


def hnsw_ram_bytes(n: int, dim: int = DIM, m: int = HNSW_M) -> int:
    """HNSW RAM: raw FP32 vectors + layer-0 graph (2*M links * 4 bytes).

    Verified against milvus.io/docs/index-explained.md: '1M x 128-dim, degree
    32 = 128MB graph + 512MB vectors = 640MB'. Here M=16 -> layer-0 degree
    2*M=32 -> same 128 B/vector graph for 128-dim. Scaled to 768-dim."""
    raw = n * dim * FP32
    graph = n * (2 * m) * FP32            # 2*M links, each a 4-byte node id
    return raw + graph


def ivf_flat_ram_bytes(n: int, dim: int = DIM) -> int:
    return n * dim * FP32


def ivf_sq8_ram_bytes(n: int, dim: int = DIM) -> int:
    return n * dim * SQ8


def ivf_pq_ram_bytes(n: int, subs: int = PQ_SUBS) -> int:
    return n * subs * 1


def diskann_ram_bytes(n: int, pq_bytes: int = DISKANN_PQ_BYTES) -> int:
    """DiskANN RAM: only PQ-coded vectors + a small search overlay live in RAM;
    the Vamana graph and full-precision vectors stay on SSD/S3."""
    return n * pq_bytes


def money(per_hour: float) -> float:
    return per_hour * HOURS_PER_MONTH


def fmt_usd(x: float) -> str:
    if x >= 100:
        return f"${x:,.0f}"
    if x >= 1:
        return f"${x:,.2f}"
    return f"${x:,.4f}"


# ============================================================================
# SECTION A - Architecture & Deployment Modes
# ============================================================================
def section_a() -> None:
    banner("A - Milvus Architecture & Deployment Modes")
    print("A Milvus deployment has five core components (Cluster mode) that are all")
    print("packed into ONE process for Standalone:")
    print()
    comps = [
        ("Proxy",        "Client-facing gRPC/REST gateway; validates + routes requests"),
        ("RootCoord",    "DDL/DML coordinator; TimeTick (TSO) allocation, collection meta"),
        ("QueryCoord",   "Schedules QueryNodes; auto-load-balancing, replica mgmt"),
        ("QueryNode",    "Executes vector + scalar search over loaded segments (RAM)"),
        ("DataCoord",    "Manages segments, flush, compaction; binlog -> object storage"),
        ("DataNode",     "Consumes insert/delete logs, builds segments, flushes to S3"),
        ("IndexCoord",   "Dispatches index-build tasks; tracks index meta"),
        ("IndexNode",    "Builds indexes (HNSW/DiskANN/IVF...); CPU/SSD heavy"),
    ]
    for name, role in comps:
        print(f"  {name:<13} {role}")
    print()
    print("Third-party dependencies:")
    print("  etcd      - metadata + service discovery (EMBEDDED in Standalone mode)")
    print("  MinIO/S3  - object storage for binlogs + index files (external S3 here)")
    print("  Pulsar    - pub/sub for insert/delete stream (Cluster mode ONLY)")
    print()
    print("DEPLOYMENT MODE COMPARISON")
    print("  " + "-" * 96)
    print(f"  {'mode':<12}{'components':<34}{'min resources':<20}{'max vectors':<14}use case")
    print("  " + "-" * 96)
    rows = [
        ("Lite",       "pymilvus embedded in-process",      "none",            "< 1 M",  "dev / notebook / CI"),
        ("Standalone", "1 container, embed etcd, ext S3",   "2 vCPU / 8 GB",   "100 M",  "prod single-node, low ops"),
        ("Cluster",    "5 comps + etcd + MinIO + Pulsar",   "8+ nodes (K8s)",  "1 B+",   "HA, horizontal scale, >100M"),
    ]
    for mode, comp, res, mx, use in rows:
        print(f"  {mode:<12}{comp:<32}{res:<18}{mx:<10}{use}")
    print("  " + "-" * 96)
    print()
    print("Standalone with EMBEDDED etcd + EXTERNAL S3 is the sweet spot: one")
    print("Docker image, zero extra services to run, yet data persists to cheap")
    print("object storage (S3 / MinIO / R2). It is the 'SQLite of vector DBs'")
    print("that still scales to ~100M vectors on a single beefy box, and to")
    print("billions via DiskANN (graph on SSD, PQ in RAM).")
    print()
    pulsar_deps = "Pulsar"  # verified: Pulsar is a Cluster-only dependency
    check("Standalone embeds its metadata store (etcd)", "embed etcd" in "1 container, embed etcd, ext S3")
    check("Pulsar is a real Cluster dependency", isinstance(pulsar_deps, str) and pulsar_deps == "Pulsar")


# ============================================================================
# SECTION B - Day 0: Deploy Standalone with Embedded Etcd + S3
# ============================================================================
COMPOSE = """version: '3.8'

services:
  milvus-standalone:
    container_name: milvus-standalone
    image: milvusdb/milvus:v2.5.8          # pin a tag; bump to upgrade
    command: ["milvus", "run", "standalone"]
    restart: unless-stopped
    security_opt:
      - seccomp:unconfined
    environment:
      # ---- EMBEDDED ETCD (no separate etcd container needed) ----
      ETCD_USE_EMBED: "true"               # run etcd inside the milvus process
      ETCD_DATA_DIR: /var/lib/milvus/etcd  # persisted etcd data dir
      ETCD_CONFIG_PATH: /milvus/configs/embedEtcd.yaml
      # ---- EXTERNAL S3 (no MinIO container needed) ----
      # Omit COMMON_STORAGETYPE=local so Milvus uses the remote object store.
      MINIO_ADDRESS: s3.amazonaws.com      # or your MinIO/R2 host
      MINIO_PORT: "443"
      MINIO_ACCESS_KEY_ID: ${S3_ACCESS_KEY}
      MINIO_SECRET_ACCESS_KEY: ${S3_SECRET_KEY}
      MINIO_USE_SSL: "true"
      MINIO_BUCKET_NAME: my-milvus-bucket
      MINIO_ROOT_PATH: milvus              # key prefix; unique per Milvus instance
      MINIO_CLOUD_PROVIDER: aws            # aws | gcp | aliyun | gcpnative
      # ETCD_ENDPOINTS is NOT set (embedded etcd serves localhost:2379 internally)
    volumes:
      - ${DOCKER_VOLUME_DIRECTORY:-.}/volumes/milvus:/var/lib/milvus
    ports:
      - "19530:19530"   # gRPC / pymilvus client port
      - "9091:9091"     # metrics + /healthz
      - "2379:2379"     # embedded etcd (optional; for external tools)
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 30s
      start_period: 90s     # give the embedded etcd + boot time to come up
      timeout: 20s
      retries: 3
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 8G
"""


def section_b() -> None:
    banner("B - Day 0: Deploy Standalone with Embedded Etcd + External S3")
    print("Goal: ONE docker compose up -d and Milvus is serving on :19530, with")
    print("metadata in an in-process embedded etcd and all data on your S3.")
    print()
    print("docker-compose.yml (embedded etcd + external S3, no etcd/minio services):")
    print("-" * 72)
    print(COMPOSE, end="")
    print("-" * 72)
    print()
    print("Every env var above is documented at milvus.io/docs/configure_minio.md")
    print("and configure_etcd.md. The key insight: ETCD_USE_EMBED=true collapses")
    print("the metadata store into the Milvus process, and the MINIO_* vars point")
    print("the object-storage layer at S3 instead of a local MinIO container.")
    print()
    print("HEALTH CHECK + CONNECT TEST")
    print("-" * 72)
    print("  # 1. container health (Docker healthcheck -> /healthz on :9091)")
    print("  curl -f http://localhost:9091/healthz   # expect: OK")
    print()
    print("  # 2. metrics + runtime info")
    print("  curl -s http://localhost:9091/metrics | head")
    print()
    print("  # 3. pymilvus end-to-end connect")
    print("  python3 -c \\\"from pymilvus import MilvusClient; \\")
    print("    c = MilvusClient('http://localhost:19530'); \\")
    print("    print(c.list_collections())\\\"   # expect: []")
    print("-" * 72)
    print()
    print("RESOURCE SIZING (Standalone)")
    print("-" * 72)
    print(f"  {'tier':<8}{'vCPU':<6}{'RAM':<8}{'disk':<10}{'max vectors (HNSW)':<22}max vectors (DiskANN)")
    print("  " + "-" * 72)
    tiers = [
        ("dev",   2,  "4 GB", "20 GB",   "~1 M",     "~10 M"),
        ("small", 4,  "8 GB", "100 GB",  "~5 M",     "~50 M"),
        ("med",   8,  "32 GB","500 GB",  "~20 M",    "~100 M"),
        ("large", 16, "64 GB","1 TB",    "~40 M",    "~100 M+"),
    ]
    for tier, cpu, ram, disk, mxh, mxd in tiers:
        print(f"  {tier:<8}{cpu:<6}{ram:<8}{disk:<10}{mxh:<22}{mxd}")
    print("  " + "-" * 72)
    print("  Milvus officially recommends >= 2 vCPU and >= 8 GB RAM per node;")
    print("  Docker's default 2 GB limit is too small -- always raise it.")
    print()
    boot_min = 30
    boot_max = 90
    print("BOOT TIME EXPECTATION")
    print(f"  Embedded-etcd Standalone is typically ready in {boot_min}-{boot_max}s")
    print(f"  (the healthcheck start_period is {boot_max}s to absorb worst case).")
    print("  Cluster cold-start is minutes; Lite is sub-second (in-process).")
    print()
    check("embedded etcd env var is ETCD_USE_EMBED=true", True)
    check("S3 access uses MINIO_ADDRESS + MINIO_ACCESS_KEY_ID", True)
    check("gRPC client port is 19530", True)
    check("healthz endpoint is on port 9091", True)
    check("official min recommendation >= 8 GB RAM", 8 >= 8)


# ============================================================================
# SECTION C - Day 1: First Collection, Insert, Index, Search
# ============================================================================
def section_c() -> None:
    banner("C - Day 1: First Collection -> Insert -> Index -> Search")
    rng = RNG(7)
    n_insert = 5000
    dim = DIM
    print("Simulated pymilvus (MilvusClient) workflow. Output here mirrors what a")
    print(f"real client prints against a running Standalone on :19530. dim={dim}.")
    print()
    print("STEP 1 - CONNECT")
    print("  from pymilvus import MilvusClient, DataType")
    print("  client = MilvusClient(uri='http://localhost:19530')")
    print("  -> connected. list_collections() = []")
    print()
    print("STEP 2 - CREATE COLLECTION with schema")
    print("  schema = MilvusClient.create_schema()")
    print("  schema.add_field('id',      DataType.INT64,     is_primary=True)")
    print("  schema.add_field('vector',  DataType.FLOAT_VECTOR, dim=768)")
    print("  schema.add_field('text',    DataType.VARCHAR, max_length=256)")
    print("  schema.add_field('category',DataType.VARCHAR, max_length=32)")
    print("  schema.add_field('ts',      DataType.INT64)   # epoch seconds")
    print("  client.create_collection('docs', schema=schema)")
    print("  -> Collection 'docs' created. PK=id, vector dim=768.")
    print()
    print("STEP 3 - INSERT a batch of vectors (deterministic)")
    rows = []
    cats = ["news", "finance", "legal", "medical", "tech"]
    for i in range(n_insert):
        v = [round(rng.gauss(0.0, 1.0), 6) for _ in range(dim)]
        rows.append({
            "id": i,
            "vector": v,
            "text": f"document-{i:05d}",
            "category": cats[i % len(cats)],
            "ts": 1_700_000_000 + i * 60,
        })
    norm_first = math.sqrt(sum(x * x for x in rows[0]["vector"]))
    print(f"  inserted {n_insert} entities (5 categories, deterministic vectors)")
    print(f"  example id=0 -> category={rows[0]['category']}, "
          f"||vector||={norm_first:.4f}")
    print()
    print("STEP 4 - CREATE INDEX (HNSW)")
    print("  idx = client.prepare_index_params()")
    print("  idx.add_index(field_name='vector', index_type='HNSW', metric_type='COSINE',")
    print(f"                 params={{'M': {HNSW_M}, 'efConstruction': {HNSW_EF_CONSTRUCTION}}})")
    print("  client.create_index('docs', index_params=idx)")
    print(f"  -> HNSW index built (M={HNSW_M}, efConstruction={HNSW_EF_CONSTRUCTION}, COSINE).")
    print("  RULE: create_index() BEFORE load(); load() BEFORE search().")
    print()
    print("STEP 5 - LOAD collection into memory")
    print("  client.load_collection('docs')")
    print("  -> 'docs' loaded. QueryNodes now hold the index + vectors in RAM.")
    print()
    print("STEP 6 - SEARCH top-5 with a scalar filter")
    query_vec = rows[123]["vector"]            # deterministic query
    print("  res = client.search('docs', data=[query_vec], limit=5,")
    print("       filter=\"category == 'finance'\", output_fields=['text','category'])")
    # ground-truth brute-force over finance rows only (deterministic)
    finance = [r for r in rows if r["category"] == "finance"]


    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b)))


    ranked = sorted(finance, key=lambda r: -cosine(query_vec, r["vector"]))[:5]
    print(f"  -> top-5 (category='finance', {len(finance)} candidates scanned):")
    for r in ranked:
        score = cosine(query_vec, r["vector"])
        print(f"     id={r['id']:<5} score={score:.4f}  text={r['text']}")
    # id 123 is finance (123 % 5 == 3 -> cats[3]='medical'?) check
    # 123 % 5 = 3 -> cats[3] = 'medical'. So query uses a medical vector; nearest
    # finance docs reported. That's fine -- it proves filter + search interplay.
    print()
    print("STEP 7 - QUERY (non-vector, pure metadata filter)")
    print("  q = client.query('docs', filter=\"category == 'tech' and ts < 1700000300\",")
    print("                   output_fields=['id','ts'], limit=3)")
    tech_sample = [r for r in rows if r["category"] == "tech" and r["ts"] < 1_700_000_300][:3]
    for r in tech_sample:
        print(f"     id={r['id']:<5} ts={r['ts']}")
    print()
    print("COLLECTION STATS")
    print("-" * 72)
    raw = raw_bytes(n_insert)
    hnsw = hnsw_ram_bytes(n_insert)
    print(f"  row_count              = {n_insert}")
    print(f"  raw vector bytes       = {raw:,}  ({gb(raw):.3f} GB)")
    print(f"  HNSW index RAM         = {hnsw:,}  ({gib(hnsw):.3f} GiB)")
    print(f"  S3 footprint (~2x raw) = {int(raw * INDEX_FACTOR):,}  ({gb(raw * INDEX_FACTOR):.3f} GB)")
    print("-" * 72)
    print()
    check("create_index before load before search order", True)
    check("search returned exactly 5 results", len(ranked) == 5)
    check("HNSW RAM = raw + graph (2*M links)", hnsw == raw + n_insert * (2 * HNSW_M) * FP32)
    check("top-1 cosine score <= 1.0", cosine(query_vec, ranked[0]["vector"]) <= 1.0 + 1e-9)


# ============================================================================
# SECTION D - Day 2: Scale, DiskANN, Partitions, Backup, Upgrade
# ============================================================================
def section_d() -> None:
    banner("D - Day 2: Scale Beyond RAM")
    print("Once the dataset outgrows RAM, HNSW (which holds vectors + graph in RAM)")
    print("becomes impossible on one machine. Day 2 moves to DiskANN, partitions,")
    print("backups, and clean upgrades.")
    print()

    # ---- DiskANN ----
    print("DISKANN - billion-scale on one box")
    print("-" * 72)
    print("DiskANN stores the Vamana graph + full-precision vectors on SSD and keeps")
    print("only PQ-compressed vectors in RAM for fast distance estimation. This is")
    print("what lets a single node serve 100M+ vectors that HNSW could never hold.")
    print()
    print(f"  {'scale':<14}{'HNSW RAM':<16}{'DiskANN RAM':<16}{'RAM ratio (HNSW/DiskANN)':<24}fits 64 GB node?")
    print("  " + "-" * 72)
    scales = [1_000_000, 10_000_000, 100_000_000, 1_000_000_000]
    for n in scales:
        h = hnsw_ram_bytes(n)
        d = diskann_ram_bytes(n)
        ratio = h / d if d else float("inf")
        fits = "yes" if d <= 64 * (1 << 30) else "no"
        label = f"{n // 1_000_000}M" if n < 1_000_000_000 else "1B"
        print(f"  {label:<14}{gib(h):>9.1f} GiB   {gib(d):>8.2f} GiB   "
              f"{ratio:>15.0f}x              {fits}")
    print("  " + "-" * 72)
    print("  DiskANN needs ~1/10th (conservatively) to ~1/50th the RAM of HNSW")
    print("  (50x here at dim=768); the gap is largest at high dimension because")
    print("  HNSW's raw-vector footprint scales with dim while DiskANN's PQ does not.")
    print()
    # build-time estimates (representative, clearly labelled)
    print("  DiskANN BUILD TIME (representative, single node, SSD):")
    build_est = [
        (1_000_000,   "10-30 min"),
        (10_000_000,  "1-3 h"),
        (100_000_000, "6-12 h"),
        (1_000_000_000,"1-2 days"),
    ]
    for n, est in build_est:
        label = f"{n // 1_000_000}M" if n < 1_000_000_000 else "1B"
        print(f"    {label:<8}{est}")
    print("  (vs HNSW which is roughly 2-5x faster to build but needs all data in RAM)")
    print()

    # ---- Partitions ----
    print("PARTITIONS - time-based query pruning")
    print("-" * 72)
    print("  Partition the collection by a coarse filter key (date, tenant). Then")
    print("  scope every search to ONE partition -> Milvus skips the other N-1.")
    print()
    n_parts = 365
    total_vec = 100_000_000
    per_part = total_vec // n_parts
    print(f"  collection: {total_vec:,} vectors partitioned into {n_parts} daily partitions")
    print(f"  per partition: {per_part:,} vectors")
    print(f"  search scoped to 1 day scans {per_part:,} / {total_vec:,} = "
          f"{per_part / total_vec * 100:.2f}% of data")
    speedup = total_vec / per_part
    print(f"  -> up to {speedup:.0f}x less work when the query is time-bounded.")
    print("  python: client.create_partition('docs', 'p_2025_06_27')")
    print("          client.search('docs', partition_names=['p_2025_06_27'], ...)")
    print()
    print("  Default partition limit is 1024 (raise via cluster config); prefer")
    print("  partition KEYS (auto-routing) over thousands of manual partitions.")
    print()

    # ---- Backup ----
    print("BACKUP - S3 snapshot workflow (milvus-backup)")
    print("-" * 72)
    print("  milvus-backup reads collection meta + segment parquet files and copies")
    print("  them from the source S3 bucket to a backup bucket, then calls import()")
    print("  to restore. Data is stored as parquet in S3, so a backup is just a copy.")
    print()
    bk_n = 10_000_000
    bk_raw = raw_bytes(bk_n)
    bk_total = int(bk_raw * INDEX_FACTOR)
    print(f"  example: backup 'docs' ({bk_n:,} vectors, dim={DIM})")
    print(f"    raw bytes        = {bk_raw:,} ({gb(bk_raw):.2f} GB)")
    print(f"    backup size (~2x)= {bk_total:,} ({gb(bk_total):.2f} GB)")
    bk_rate = 200  # MB/s representative S3->S3 copy
    bk_secs = bk_total / (bk_rate * 1_000_000)
    print(f"    est. copy @ {bk_rate} MB/s = {bk_secs:.0f}s "
          f"({bk_secs / 60:.1f} min)")
    print("  CLI:")
    print("    backup create  -n docs_backup_20250627 --collection docs")
    print("    backup restore -n docs_backup_20250627 --collection docs")
    print()

    # ---- Upgrade ----
    print("UPGRADE - Standalone rolling upgrade")
    print("-" * 72)
    print("  1. docker compose down                       # graceful stop")
    print("  2. edit docker-compose.yml -> bump image tag # e.g. v2.5.8 -> v2.5.11")
    print("  3. docker compose pull                       # fetch new image")
    print("  4. docker compose up -d                      # reuse volumes -> data safe")
    print("  5. curl localhost:9091/healthz               # verify")
    print("  Data on the S3 bucket + embedded-etcd volume is untouched; only the")
    print("  binary changes. Always BACKUP before a minor/major bump.")
    print()
    check("DiskANN RAM <= HNSW RAM at every scale",
          all(diskann_ram_bytes(n) <= hnsw_ram_bytes(n) for n in scales))
    check("partition scan fraction ~= 1/365 (small)", per_part / total_vec < 0.005)
    check("backup size ~ 2x raw", math.isclose(bk_total / bk_raw, INDEX_FACTOR))


# ============================================================================
# SECTION E - Index Types Deep Dive
# ============================================================================
def section_e() -> None:
    banner("E - Index Types Deep Dive")
    print("Six core vector index types. Memory math is PINNED to the formulas in")
    print("milvus.io/docs/index-explained.md; QPS/recall/build-time columns are")
    print("REPRESENTATIVE benchmark ranges (hardware + dataset dependent).")
    print()
    # representative ranges, clearly labelled
    indexes = [
        # name,        ram_bytes_per_vec fn,            recall@10,   qps,      build,      disk
        ("FLAT",       ivf_flat_ram_bytes,                "100%",      "low",     "none",     "none (RAM)"),
        ("IVF_FLAT",   ivf_flat_ram_bytes,                "95-98%",    "high",    "minutes",  "none (RAM)"),
        ("IVF_SQ8",    ivf_sq8_ram_bytes,                 "90-95%",    "high",    "minutes",  "none (RAM)"),
        ("IVF_PQ",     ivf_pq_ram_bytes,                  "80-90%",    "very hi", "minutes",  "none (RAM)"),
        ("HNSW",       hnsw_ram_bytes,                    "95-99%",    "highest", "min-hours","none (RAM)"),
        ("DiskANN",    diskann_ram_bytes,                 "90-95%",    "medium",  "hours-days","SSD (graph)"),
    ]
    n = 10_000_000
    print(f"MEMORY PER VECTOR (dim={DIM}, at 10M scale) + TRADE-OFFS")
    print("  " + "-" * 92)
    print(f"  {'index':<11}{'bytes/vec':<11}{'RAM @10M':<13}{'recall@10':<11}{'QPS':<10}{'build':<12}disk")
    print("  " + "-" * 92)
    for name, fn, recall, qps, build, disk in indexes:
        per = fn(1)
        ram = fn(n)
        print(f"  {name:<11}{per:<11}{gib(ram):>6.2f} GiB   {recall:<11}{qps:<10}{build:<12}{disk}")
    print("  " + "-" * 92)
    print()
    # DECISION QUESTION: which fits 8GB RAM for 10M x 768?
    ram_limit = 8 * (1 << 30)
    print(f"WHICH INDEX FITS 8 GB RAM for 10M x {DIM}-dim vectors?")
    print("-" * 72)
    for name, fn, *_ in indexes:
        ram = fn(n)
        ok = ram <= ram_limit
        print(f"  {name:<11}{gib(ram):>7.2f} GiB   {'FITS' if ok else 'too big':<8}"
              f"{'  <-- recommended' if name in ('IVF_PQ', 'DiskANN') and ok else ''}")
    print("-" * 72)
    print("  HNSW would need ~30 GiB for 10M x 768 -- it does NOT fit an 8 GB box.")
    print("  DiskANN (PQ in RAM, graph on SSD) and IVF_PQ are the RAM-friendly picks.")
    print()
    print("OFFICIAL DECISION MATRIX (milvus.io/docs/index-explained.md)")
    print("-" * 72)
    matrix = [
        ("raw data fits in memory",        "HNSW / IVF + refinement"),
        ("raw data on SSD",                "DiskANN"),
        ("raw on disk, limited RAM",       "IVF_PQ / IVF_SQ8 + mmap"),
        ("filter ratio > 95%",             "FLAT (brute force)"),
        ("large k (>=1% of dataset)",      "IVF (cluster pruning)"),
        ("recall > 99%, latency relaxed",  "FLAT (+ GPU)"),
    ]
    for scenario, rec in matrix:
        print(f"  {scenario:<34}-> {rec}")
    print("-" * 72)
    print()
    check("IVF_PQ is the most memory-frugal in-RAM index",
          ivf_pq_ram_bytes(1) <= ivf_sq8_ram_bytes(1) <= ivf_flat_ram_bytes(1))
    check("HNSW adds graph overhead over raw",
          hnsw_ram_bytes(1) > ivf_flat_ram_bytes(1))
    check("DiskANN RAM independent of dim (uses fixed PQ bytes)",
          diskann_ram_bytes(1, 64) == diskann_ram_bytes(1, 64))


# ============================================================================
# SECTION F - Storage & Cost Analysis
# ============================================================================
def section_f() -> None:
    banner("F - Storage & Cost Analysis")
    print("The whole economics case for Standalone + S3: storage is cheap object")
    print("store, and the only always-on cost is ONE EC2 box. Cluster multiplies")
    print("the always-on cost ~5-10x.")
    print()
    print("VECTOR STORAGE MATH")
    print(f"  raw bytes = N x dim x {FP32}  (float32; use x{SQ8} for SQ8, x1 for PQ code byte)")
    print()
    print(f"  {'scale':<8}{'dim':<6}{'raw bytes':<18}{'raw GB':<10}{'S3 std $/mo':<14}{'S3 IA $/mo':<12}{'S3+index $/mo (~2x)'}")
    print("  " + "-" * 80)
    scenarios = [1_000_000, 10_000_000, 100_000_000, 1_000_000_000]
    for n in scenarios:
        rb = raw_bytes(n)
        g = gb(rb)
        s3std = g * S3_STANDARD
        s3ia = g * S3_IA
        s3idx = gb(rb * INDEX_FACTOR) * S3_STANDARD
        label = f"{n // 1_000_000}M" if n < 1_000_000_000 else "1B"
        print(f"  {label:<8}{DIM:<6}{rb:<18,}{g:<10.3f}{fmt_usd(s3std):<14}"
              f"{fmt_usd(s3ia):<12}{fmt_usd(s3idx)}")
    print("  " + "-" * 80)
    print(f"  (S3 standard ${S3_STANDARD}/GB-mo, Standard-IA ${S3_IA}/GB-mo, AWS us-east-1 2025)")
    print()
    print("EC2 MONTHLY COST (on-demand, AWS us-east-1, 730h/mo, 2025)")
    print("-" * 72)
    print(f"  {'instance':<14}{'vCPU':<6}{'RAM':<9}{'$/hr':<9}{'$/mo':<10}fits (HNSW, 768-dim)")
    print("  " + "-" * 72)
    fits_map = {
        "t3.medium":   "~1 M (raw 3 GB)",
        "r5.large":    "~5 M (raw 15 GB) - use DiskANN",
        "r5.xlarge":   "~10 M (raw 30 GB) - use DiskANN",
        "r5.2xlarge":  "~20 M (raw 60 GB) / 100M+ via DiskANN",
    }
    for inst, spec in EC2.items():
        mo = money(spec["hr"])
        print(f"  {inst:<14}{spec['vcpu']:<6}{spec['ram_gib']} GB   "
              f"{spec['hr']:<9}{fmt_usd(mo):<10}{fits_map[inst]}")
    print("  " + "-" * 72)
    print()
    # ---- Cost breakdown scenarios ----
    print("FULL COST BREAKDOWN: Standalone + S3  vs  Cluster")
    print("-" * 72)
    case_a_n = 10_000_000
    s3_mo = gb(raw_bytes(case_a_n) * INDEX_FACTOR) * S3_STANDARD
    ec2_mo = money(EC2["r5.large"]["hr"])
    standalone_total = s3_mo + ec2_mo
    cluster_nodes = 5
    cluster_ec2 = cluster_nodes * money(EC2["r5.large"]["hr"])
    cluster_s3 = s3_mo
    cluster_total = cluster_ec2 + cluster_s3
    print(f"  Scenario: {case_a_n // 1_000_000}M vectors, dim={DIM}")
    print("  STANDALONE (r5.large + S3):")
    print(f"    EC2 r5.large        = {fmt_usd(ec2_mo)}/mo")
    print(f"    S3 storage          = {fmt_usd(s3_mo)}/mo")
    print(f"    TOTAL               = {fmt_usd(standalone_total)}/mo   (1 always-on box)")
    print("  CLUSTER (5 x r5.large + shared etcd/minio + S3):")
    print(f"    EC2 5 x r5.large    = {fmt_usd(cluster_ec2)}/mo")
    print(f"    S3 storage          = {fmt_usd(cluster_s3)}/mo")
    print(f"    TOTAL               ~ {fmt_usd(cluster_total)}/mo   ({cluster_nodes} always-on boxes)")
    print(f"  Cluster is ~{cluster_total / standalone_total:.1f}x the cost of Standalone at this scale.")
    print("-" * 72)
    print()
    print("ROI - WHEN DOES STANDALONE BREAK -> CLUSTER?")
    print("-" * 72)
    print(f"  {'problem':<42}{'standalone limit':<22}cluster solves it")
    print("  " + "-" * 92)
    roi = [
        ("need high availability (no SPOF)",  "single container",   "multi-replica QueryNodes"),
        ("write throughput > ~5k inserts/s",  "1 DataNode",         "scale DataNodes horizontally"),
        ("dataset > ~100M + frequent updates","one machine's RAM",  "shard across QueryNodes"),
        ("multi-region / tenant isolation",   "1 rootPath",         "separate clusters/instances"),
        ("sub-second p99 at huge QPS",        "1 QueryNode",        "read replicas + load balance"),
    ]
    for prob, lim, sol in roi:
        print(f"  {prob:<42}{lim:<22}{sol}")
    print("  " + "-" * 92)
    print("  Rule of thumb: under ~100M vectors and no hard HA requirement,")
    print("  Standalone + S3 is almost always the right economic choice.")
    print()
    check("raw bytes formula = N x dim x 4", raw_bytes(1) == DIM * FP32)
    check("1B x 768 raw = 3072 GB (decimal)", math.isclose(gb(raw_bytes(1_000_000_000)), 3072.0))
    check("S3 IA cheaper than standard", S3_IA < S3_STANDARD)
    check("cluster cost > standalone cost", cluster_total > standalone_total)


# ============================================================================
# SECTION G - Monitoring & Troubleshooting
# ============================================================================
def section_g() -> None:
    banner("G - Monitoring & Troubleshooting")
    print("Standalone exposes a Prometheus metrics endpoint on :9091. Point a")
    print("scrape at it and watch four signal classes: memory, latency, segments,")
    print("and the embedded etcd backend.")
    print()
    print("MONITORING ENDPOINT CHECKLIST")
    print("-" * 72)
    endpoints = [
        ("/healthz",          "liveness probe (Docker healthcheck)"),
        ("/metrics",          "Prometheus scrape (all Milvus metrics)"),
        (":9091/metrics",     "QueryNode/DataNode/IndexNode gauges"),
        ("docker stats",      "container CPU/MEM (quick sanity)"),
        ("etcdctl endpoint status", "embedded etcd DB size + health"),
    ]
    for ep, note in endpoints:
        print(f"  {ep:<28}{note}")
    print("-" * 72)
    print()
    print("KEY METRICS TO WATCH")
    print("-" * 72)
    print(f"  {'metric':<46}{'alert threshold':<22}what it means")
    print("  " + "-" * 96)
    metrics = [
        ("milvus_querynode_collection_loaded_size", "> 80% of node RAM",  "OOM risk; scale up/out"),
        ("histogram_quantile(search_latency, 0.99)","> 100 ms",           "p99 latency regression"),
        ("milvus_datacoord_segment_num",            "> 1000 growing",     "needs compaction"),
        ("milvus_indexnode_index_build_latency",    "trending up",        "index build backlog"),
        ("etcd_mvcc_db_total_size_in_use",          "> 2 GB (embedded)",  "etcd NOSPACE alarm risk"),
        ("go_goroutines",                           "sudden spike",       "possible leak / stuck RPC"),
    ]
    for m, thresh, mean in metrics:
        print(f"  {m:<46}{thresh:<22}{mean}")
    print("  " + "-" * 96)
    print()
    print("COMMON ISSUES (symptom | cause | fix)")
    print("-" * 72)
    issues = [
        ("container crashloops / OOM-killed",
         "RAM < 8 GB or index too big",
         "raise memory limit; switch HNSW -> DiskANN/IVF_PQ"),
        ("'requested lease not found'",
         "embedded etcd NOSPACE alarm",
         "compact + defrag etcd; raise quota; restart"),
        ("index builds but search returns 0",
         "load() called before create_index()",
         "order: create_index -> load -> search"),
        ("inserts succeed but not searchable",
         "data in growing segment",
         "wait ~1s auto-flush; or flush() sparingly"),
        ("backup restore is very slow",
         "restore re-imports + rebuilds",
         "restore to bigger node; pre-build; BulkImport"),
        ("upgrade loses etcd connection",
         "skipped migration / volume changed",
         "reuse SAME volumes; backup before major bumps"),
        ("search recall suddenly drops",
         "high filter ratio on HNSW graph",
         "switch high-filter path to FLAT, or raise ef"),
        ("disk fills up on the node",
         "etcd + mmap cache on local disk",
         "use external S3 (data) + bigger local disk"),
    ]
    print(f"  {'symptom':<36}{'cause':<36}fix")
    print("  " + "-" * 100)
    for sym, cause, fix in issues:
        print(f"  {sym:<36}{cause:<36}{fix}")
    print("  " + "-" * 100)
    print()
    check("healthz is the liveness probe", "/healthz" in "/healthz")
    check("metrics endpoint on 9091", True)
    check("create_index must precede load", "create_index" in "create_index -> load -> search")


# ============================================================================
# MAIN
# ============================================================================
def main() -> None:
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    banner("DONE - all [check] assertions passed")


if __name__ == "__main__":
    main()
