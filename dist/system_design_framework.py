"""
system_design_framework.py - System design building blocks & capacity planning:
how load balancers, caches, databases, message queues, and CDNs COMPOSE into a
request flow, plus a back-of-envelope capacity-estimation template and a
component-selection tradeoff matrix.

This is the system-design-framework overlay of the dist/ suite. It ties the
"how do you actually build it" question to the building blocks the deeper
bundles expand on (load balancer <-> consistent_hashing_lb; cache <-> the
caching in architectural_patterns; DB <-> the consistency bundles; queue <->
backpressure/saga; CDN <-> read_scaling). Every number, table, and worked
example below is printed by this file and recomputed live in
system_design_framework.html.

Run:
    python3 system_design_framework.py

Pure Python stdlib only (no imports beyond the standard library).

============================================================================
THE INTUITION (read this first) - five blocks, one template, one matrix
============================================================================
System design at the high level is COMPOSITION: you take a small set of building
blocks and wire them so the load hits each in the order it is good at. The same
five blocks appear in almost every backend, and knowing what EACH is for (and
what it is NOT for) is 80% of the work.

  1. LOAD BALANCER - distribute. Its ONLY job is to spread traffic across N
     instances so no one is a bottleneck. L4 (TCP) is fast and opaque; L7 (HTTP)
     is smart (path routing, SSL termination) but adds a hop. Put it at the edge
     (user -> LB -> app) and between tiers (app -> LB -> DB pool).

  2. CACHE - the cheapest read-scaling lever. A cache turns a 5ms DB read into a
     0.5ms memory read for the hot keys. Redis at $500/mo absorbs ~100K QPS; a
     4th read replica at $5000/mo adds only ~5K QPS. CACHE FIRST, REPLICATE
     SECOND. The hard part is invalidation (TTL too long = stale; too short =
     stampede), not the read.

  3. DATABASE - the source of truth. Pick it by the WORKLOAD: relational
     (Postgres) for consistency + joins, wide-column (Cassandra) for write-heavy
     scale, in-memory (Redis) for sub-ms access, blob (S3) for files. Never
     store binary blobs in a DB - metadata in the DB, bytes in S3.

  4. MESSAGE QUEUE - decouple in time. A queue absorbs bursts (the producer is
     never blocked by a slow consumer) and enables fan-out (one event -> N
     consumers). It turns a synchronous, failure-coupled call into an async,
     buffered one. Use it for work that does not need an immediate reply.

  5. CDN - move bytes close to users. A CDN caches static (and semi-static)
     content at ~200 edge locations so a user in Tokyo fetches from Tokyo, not
     from Virginia. It cuts origin load to a fraction and latency to <50ms
     globally - but only for cacheable content.

THE CAPACITY TEMPLATE (back-of-envelope, the single most useful skill):
    qps          = daily_ops / 86400                (average)
    peak_qps     = qps * peak_factor                (3-5x average)
    bandwidth    = peak_qps * payload_bytes         (bytes/sec)
    storage      = daily_new * bytes_each * days * years
    cache_hit    = (1 - hit_rate) * read_qps        (origin sees the misses)

THE HARD TRUTH (numbers before architecture): 100 QPS and 100K QPS are different
systems for the same product. A single Postgres handles ~1-5K QPS; above ~10K
read QPS you need a cache; above ~5K write QPS you need sharding or a
write-optimized store. ESTIMATE FIRST - the number decides whether a single
node, replicas, sharding, or a different store is even relevant.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  load balancer (LB): distributes incoming requests across multiple targets.
                     L4 = TCP/UDP (fast, opaque); L7 = HTTP/gRPC (smart routing).
  cache           : a faster, smaller store in front of a slower store. The hit
                     rate is the fraction of reads it satisfies. Miss -> origin.
  cache-aside     : app reads cache; on miss, reads DB and WRITES the cache.
                     Default - simple, resilient to cache failure.
  write-through   : app writes DB and cache together. Strong consistency, slower
                     writes. Use when stale reads are unacceptable.
  write-behind    : app writes cache; cache async-flushes to DB. Fast writes,
                     risk of data loss on crash. Use for high-write, loss-tolerant.
  cache stampede  : cold start / expiry -> every request misses simultaneously
                     and hammers the origin. Fix: probabilistic early expiry.
  database (DB)   : the durable source of truth. OLTP (transactions) vs OLAP
                     (analytics) vs KV (lookups) vs blob (files).
  read replica    : an async copy of the primary that serves reads. Adds read
                     capacity but with replication lag (0-100ms).
  sharding        : splitting ONE table across N nodes by a shard key. Linear
                     write scale; cross-shard queries become O(N) scatter-gather.
  message queue   : a durable buffer between a producer and consumer(s). At-least-
                     once delivery; consumer pulls at its own rate.
  fan-out         : one message published -> N consumers each get a copy (pub/sub).
  dead letter queue (DLQ): messages that failed N retries land here for inspection.
  CDN             : a geographically distributed cache of static content. Edge
                     POPs serve users from nearby locations.
  cache hit rate  : fraction of reads served by the cache. Target > 90%.
  origin          : the server the CDN/cache fetches from on a miss (your app).
  QPS / RPS       : queries/requests per second. THE unit of load.
  peak factor     : peak_qps / avg_qps. Real traffic is bursty; assume 3-5x.
  back-of-envelope: quick order-of-magnitude estimation from first principles,
                     before any detailed design. Drives every component choice.

============================================================================
THE BUILDING BLOCKS & REFERENCES
============================================================================
  Kleppmann              "Designing Data-Intensive Applications" - the canonical
                         text; every block + the tradeoffs explained rigorously.
  Redis docs             in-memory data store; cache, session, leaderboard, pub/sub.
  Kafka docs             distributed log; durable queue + event stream + fan-out.
  CloudFront/Fastly docs CDN edge caching; cache-control headers, invalidation.
  HAProxy/Nginx          L4/L7 load balancing; health checks, session affinity.
  CalibreOS HLD          the CIRCLE/RACED framework + back-of-envelope cheat sheet.

KEY FORMULAS / facts (all asserted in code):
    qps(daily)   : daily_ops / 86400
    peak(daily)  : qps * peak_factor         (peak_factor 3-5)
    bandwidth    : peak_qps * payload_bytes
    storage      : daily_new * bytes_each * days * years
    cache_miss   : (1 - hit_rate) * read_qps  (origin load)
    single_db_qps: ~1,000-5,000  (the threshold for replicas/cache)
"""

from __future__ import annotations

BANNER = "=" * 74

# ---------------------------------------------------------------------------
# constants for back-of-envelope estimation (decimal units, the loose style
# interviewers use: 1KB = 1e3, 1MB = 1e6, ... so numbers are easy to reason about)
SECS_PER_DAY = 86_400
KB = 1_000
MB = 1_000_000
GB = 1_000_000_000
TB = 1_000_000_000_000
PB = 1_000_000_000_000_000

# A capacity cheat sheet every engineer should know. These are the rule-of-thumb
# numbers that drive component choices in an interview.
LATENCY = [
    ("memory read",        0.0001),   # 0.1 us
    ("SSD read",           0.15),     # 0.15 ms
    ("HDD seek",           10.0),     # ~10 ms
    ("network, same DC",   0.5),      # ~0.5 ms RTT
    ("network, cross-region", 80.0),  # ~80 ms
    ("Redis GET",          0.7),      # ~0.5-1 ms
    ("Postgres indexed",   3.0),      # ~1-5 ms
    ("S3 GET",             120.0),    # ~50-200 ms
]
SINGLE_DB_QPS = 3_000        # a single well-tuned Postgres: ~1-5K QPS
CACHE_TARGET_HIT = 0.90      # target > 90% cache hit rate
REDIS_QPS = 100_000          # Redis cluster ~100K ops/sec
REPLICA_QPS = 5_000          # a read replica ~5K QPS


# ---------------------------------------------------------------------------
# capacity-estimation primitives (the template)
# ---------------------------------------------------------------------------
def qps(daily_ops: float) -> float:
    """Average queries/sec from a daily operation count."""
    return daily_ops / SECS_PER_DAY


def peak_qps(daily_ops: float, peak_factor: float = 3.0) -> float:
    """Peak QPS = average * peak_factor (real traffic bursts 3-5x)."""
    return qps(daily_ops) * peak_factor


def bandwidth_bps(peak: float, payload_bytes: float) -> float:
    """Egress bytes/sec at peak = peak_qps * payload_size."""
    return peak * payload_bytes


def storage(daily_new: float, bytes_each: float, years: float, days: int = 365) -> float:
    """Total storage (bytes) for `daily_new` items/day of `bytes_each` over `years`."""
    return daily_new * bytes_each * days * years


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def human_size(n_bytes: float) -> str:
    """Format bytes into a human-readable size (decimal)."""
    for unit, factor in [("PB", PB), ("TB", TB), ("GB", GB), ("MB", MB), ("KB", KB)]:
        if n_bytes >= factor:
            return f"{n_bytes / factor:.2f} {unit}"
    return f"{n_bytes:.0f} B"


# ---------------------------------------------------------------------------
# SECTION A: the five building blocks
# ---------------------------------------------------------------------------
def section_a():
    banner("SECTION A: the five building blocks - LB, cache, DB, queue, CDN")
    print("Almost every backend is the SAME five blocks wired so the load hits")
    print("each in the order it is good at. Knowing what each is FOR (and NOT")
    print("for) is 80% of high-level design.\n")
    print("  | block        | job                | good at            | NOT for            |")
    print("  |--------------|--------------------|--------------------|--------------------|")
    print("  | load balancer| distribute traffic | spreading load     | state (it is dumb) |")
    print("  | cache        | fast reads         | hot keys, <1ms     | source of truth    |")
    print("  | database     | durable truth      | consistency, query | raw bytes, petabyte|")
    print("  | message queue| decouple in time   | absorbing bursts   | low-latency RPC    |")
    print("  | CDN          | move bytes close   | static, global     | per-user dynamic   |")
    print()
    print("LOAD BALANCER: distribute. L4 (TCP) is fast and opaque; L7 (HTTP) is")
    print("smart (path routing, SSL offload, header manipulation) but adds a hop.")
    print("Place it at the edge (user -> LB -> app) AND between tiers (app -> LB")
    print("-> DB pool / cache pool). Health checks pull dead instances out;")
    print("session affinity (sticky sessions) sends a user to the same instance")
    print("(needed for in-process session state, an anti-pattern at scale).\n")
    print("CACHE: the cheapest read-scaling lever. A cache turns a 5ms DB read")
    print("into a 0.5ms memory read for the hot keys. The hard part is")
    print("INVALIDATION (TTL too long = stale; too short = stampede), not the")
    print("read. Strategies: cache-aside (default), write-through (strong")
    print("consistency, slow writes), write-behind (fast writes, crash risk).\n")
    print("DATABASE: the source of truth. Pick by workload - relational for")
    print("consistency + joins, wide-column for write-heavy scale, in-memory for")
    print("sub-ms, blob for files. NEVER store binary blobs in a DB: metadata in")
    print("the DB, bytes in S3. A single node handles ~1-5K QPS; beyond that")
    print("cache, then read replicas, then shard (in that order).\n")
    print("MESSAGE QUEUE: decouple in time. The producer writes and returns")
    print("immediately; consumers pull at their own pace. The queue ABSORBS")
    print("bursts (a flash sale fills the queue, not the database) and enables")
    print("fan-out (one event -> N consumers). Dead-letter after 3-5 retries.\n")
    print("CDN: move bytes close to users. ~200 edge POPs cache static content so")
    print("a Tokyo user fetches from Tokyo, not Virginia. Cuts origin load to a")
    print("fraction and latency to <50ms globally - but ONLY for cacheable")
    print("content. Set long TTLs + a versioned URL so invalidation = a path")
    print("change, not a purge.\n")

    # latency ladder: where each block lives
    print("The latency ladder (where each block sits in the request path):\n")
    print("  | operation          | latency    | block          |")
    print("  |---------------------|------------|----------------|")
    for name, lat in LATENCY:
        print(f"  | {name:<19} | {lat:>7.4f} ms | ", end="")
        if "memory" in name:
            blk = "cache (hot)"
        elif "Redis" in name:
            blk = "cache"
        elif "Postgres" in name or "SSD" in name:
            blk = "database"
        elif "S3" in name:
            blk = "blob store / CDN origin"
        elif "cross-region" in name:
            blk = "(why a CDN exists)"
        else:
            blk = "infra"
        print(f"{blk:<14} |")
    print()
    print(f"Memory is {LATENCY[2][1]/LATENCY[0][1]:.0f}x faster than an HDD seek; a Redis")
    print("GET is ~4x faster than an indexed Postgres query. These gaps are WHY")
    print("the cache exists - it sidesteps the slow path entirely for hot keys.\n")
    assert LATENCY[2][1] > 50_000 * LATENCY[0][1]   # HDD >> memory
    print("[check] memory > 50000x faster than HDD => cache sidesteps the slow path: OK")


# ---------------------------------------------------------------------------
# SECTION B: capacity planning template (back-of-envelope estimation)
# ---------------------------------------------------------------------------
def section_b():
    banner("SECTION B: the capacity planning template")
    print("Back-of-envelope estimation finds the FIRST SATURATED RESOURCE: request")
    print("rate, storage, bandwidth, or memory. Convert users to actions/day, divide")
    print("by 86400 for average QPS, apply a 3-5x peak factor, then ask which")
    print("component actually sees that load.\n")
    print("THE TEMPLATE (every line is a function in this file):\n")
    print("  qps          = daily_ops / 86400        # average")
    print("  peak_qps     = qps * peak_factor        # 3-5x average")
    print("  bandwidth    = peak_qps * payload_bytes # bytes/sec egress")
    print("  storage      = daily_new * bytes_each * days * years")
    print("  cache_miss   = (1 - hit_rate) * read_qps # origin load after cache\n")
    print("RULES OF THUMB (the thresholds that trigger each block):\n")
    print("  | signal                   | threshold      | triggers           |")
    print("  |--------------------------|----------------|--------------------|")
    print("  | read QPS                 | > ~5K-10K      | cache (then replica)|")
    print("  | write QPS                | > ~2K-5K       | shard / wide-column|")
    print("  | storage                  | > ~10TB        | blob store, shard DB|")
    print("  | per-op latency           | > ~500ms       | queue (async offload)|")
    print("  | global users             | > 1 region     | CDN (edge caching) |")
    print()
    print("WORKED MINI-EXAMPLE (a notifications API): 10M/day normal, 100M/day in")
    print("a spike. Payload 500 bytes.\n")
    daily_normal, daily_spike, payload = 10_000_000, 100_000_000, 500
    for label, daily in [("normal", daily_normal), ("spike", daily_spike)]:
        avg = qps(daily)
        peak = peak_qps(daily, 3)
        bw = bandwidth_bps(peak, payload)
        print(f"  {label:<7} {daily:>10,}/day -> avg {avg:,.0f} QPS, peak {peak:,.0f} QPS, "
              f"egress {bw/MB:.1f} MB/s")
    print()
    print("The spike is 10x normal. A synchronous 'send now' design would need")
    print("10x the capacity idle most of the time. A QUEUE absorbs the spike: the")
    print("producer writes 100M events fast; consumers drain at a steady rate. The")
    print("queue IS the buffer that decouples the burst from the workers.\n")

    assert qps(daily_spike) == 10 * qps(daily_normal)
    assert peak_qps(daily_spike) > 3_000   # beyond a single DB
    print("[check] spike = 10x normal, peak > single-DB threshold => queue absorbs burst: OK")


# ---------------------------------------------------------------------------
# SECTION C: component composition - how the five blocks wire together
# ---------------------------------------------------------------------------
def section_c():
    banner("SECTION C: composition - wiring the blocks into a request flow")
    print("The five blocks compose in a fixed order along the request path. A")
    print("typical read-heavy, globally-distributed request flows:\n")
    print("  user -> CDN -> load balancer -> app -> cache -> (miss?) -> database\n")
    print("Each block is a GATE that either satisfies the request or passes it on:\n")
    print("  | gate         | satisfies?            | on miss, forwards to |")
    print("  |--------------|-----------------------|----------------------|")
    print("  | CDN          | static + cacheable    | load balancer (origin)|")
    print("  | load balancer| never (just routes)   | an app instance      |")
    print("  | app + cache  | hot key in cache      | database             |")
    print("  | database     | always (source of truth)| - (end of the line)|")
    print()
    print("The further LEFT a request is satisfied, the cheaper and faster it is.")
    print("A CDN hit costs ~nothing and is <50ms; a DB hit is ~3ms + compute +")
    print("the load of every gate before it. So you push work LEFT: cache hot")
    print("keys so the DB is never touched; cache static assets at the CDN so the")
    print("origin is never touched.\n")
    print("WRITES flow differently - they go RIGHT to the source of truth, then")
    print("propagate LEFT asynchronously:\n")
    print("  user -> LB -> app -> database (commit) -> CDC/Kafka -> cache/CDN update\n")
    print("The write commits to the DB (durable truth); the cache and CDN update")
    print("later (eventual consistency, ~50-500ms). This is the cache-aside + CDC")
    print("pattern, and it is why reads are fast (left gate) and writes are safe")
    print("(right to truth first).\n")

    # where a request is satisfied at different cache hit rates
    print("Where requests get satisfied at different cache hit rates (read QPS = 10K):\n")
    read_qps_val = 10_000
    print("  | cache hit rate | satisfied by cache | reach DB (misses) | DB load vs raw |")
    print("  |----------------|--------------------|-------------------|----------------|")
    for hit in (0.50, 0.80, 0.90, 0.95, 0.99):
        served = read_qps_val * hit
        misses = read_qps_val * (1 - hit)
        print(f"  | {hit*100:>4.0f}%           | {served:>8,.0f}          | {misses:>8,.0f}            | "
              f"{(1-hit)*100:>5.0f}% of raw   |")
    print()
    print("At 90% hit rate the DB sees only 10% of reads (1K vs 10K) - a single DB")
    print("handles it. At 50% it sees 5K, near the single-node ceiling. THIS is why")
    print("the cache hit rate is the single most important number in a read-heavy")
    print("system: it decides whether you need one DB or a sharded cluster.\n")

    assert read_qps_val * 0.10 == 1_000   # 90% hit -> 1K to DB
    print("[check] 90% cache hit cuts DB load 10x; hit rate decides shard-or-not: OK")


# ---------------------------------------------------------------------------
# SECTION D: component-selection tradeoff matrix
# ---------------------------------------------------------------------------
def section_d():
    banner("SECTION D: component-selection tradeoff matrix")
    print("Each block has variants; the choice follows the workload. These matrices")
    print("are the lookup tables a staff engineer keeps in their head.\n")
    print("DATABASE SELECTION (by workload):\n")
    print("  | workload              | best choice   | why                                   |")
    print("  |-----------------------|---------------|---------------------------------------|")
    print("  | user profiles / OLTP  | PostgreSQL    | strong consistency, joins, ACID       |")
    print("  | session / leaderboard | Redis         | in-memory, sub-ms, sorted sets        |")
    print("  | time-series / metrics | Cassandra     | write-optimized, huge scale           |")
    print("  | flexible documents    | MongoDB       | schemaless, horizontal scale          |")
    print("  | full-text search      | Elasticsearch | inverted index, relevance scoring     |")
    print("  | images / video        | S3            | cheap, durable, CDN-ready (NOT a DB)  |")
    print()
    print("CACHE WRITE STRATEGY (by consistency need):\n")
    print("  | strategy     | write goes to        | consistency      | use when           |")
    print("  |--------------|----------------------|------------------|--------------------|")
    print("  | cache-aside  | DB; cache filled on read| eventual      | default            |")
    print("  | write-through| DB + cache together  | strong          | stale reads fatal  |")
    print("  | write-behind | cache; async to DB   | eventual (risk) | write-heavy        |")
    print()
    print("LOAD BALANCER LAYER (L4 vs L7):\n")
    print("  | layer | operates at | routing        | overhead | use when          |")
    print("  |-------|-------------|----------------|----------|-------------------|")
    print("  | L4    | TCP/UDP     | IP + port      | low      | raw throughput    |")
    print("  | L7    | HTTP/gRPC   | path/header    | higher   | smart routing/TLS |")
    print()
    print("THE ECONOMICS (cache first, replicate second):\n")
    redis_cost, repl_cost = 500, 5_000
    print("  | option              | QPS added   | cost $/mo   | $ per 1K QPS |")
    print("  |---------------------|-------------|-------------|--------------|")
    print(f"  | Redis cache node    | {REDIS_QPS:>7,}   | {redis_cost:>7,}     | {redis_cost/REDIS_QPS*KB:>8.2f}    |")
    print(f"  | 4th read replica    | {REPLICA_QPS:>7,}   | {repl_cost:>7,}     | {repl_cost/REPLICA_QPS*KB:>8.2f}    |")
    print()
    print(f"Redis at ${redis_cost}/mo adds {REDIS_QPS:,} QPS; a 4th replica at ${repl_cost}/mo")
    print(f"adds only {REPLICA_QPS:,} QPS. The cache is {repl_cost/redis_cost:.0f}x cheaper per QPS. ")
    print("Always add the cache before the 4th replica.\n")

    assert redis_cost / REDIS_QPS < repl_cost / REPLICA_QPS / 10
    print("[check] Redis >10x cheaper per QPS than a replica => cache before replicate: OK")


# ---------------------------------------------------------------------------
# GOLD CHECK: full capacity worked example - "Design Instagram"
# ---------------------------------------------------------------------------
def gold_check():
    banner("GOLD CHECK: capacity worked example - Design Instagram")
    print("CAPSTONE: the full back-of-envelope for a photo-sharing service, every")
    print("number recomputed from the Section B template.\n")
    print("SCALE ASSUMPTIONS: 1B users, 100M DAU. 50M photo uploads/day, 500M")
    print("views/day. Average photo = 200 KB (compressed). Read:write = 10:1.\n")
    uploads_day = 50_000_000
    views_day = 500_000_000
    photo_bytes = 200 * KB
    peak_factor = 3.0
    years = 3.0

    write_avg = qps(uploads_day)
    write_peak = peak_qps(uploads_day, peak_factor)
    read_avg = qps(views_day)
    read_peak = peak_qps(views_day, peak_factor)
    write_bw = bandwidth_bps(write_peak, photo_bytes)
    read_bw = bandwidth_bps(read_peak, photo_bytes)
    storage_day = uploads_day * photo_bytes
    storage_3yr = storage(uploads_day, photo_bytes, years)

    print("WRITE PATH (uploads):\n")
    print(f"  avg write QPS  = {uploads_day:,} / 86400 = {write_avg:,.1f}")
    print(f"  peak write QPS = {write_avg:,.1f} * {peak_factor:.0f} = {write_peak:,.1f}")
    print(f"  upload egress  = {write_peak:,.0f} * {photo_bytes/KB:.0f} KB = {write_bw/GB:.2f} GB/s\n")
    print("READ PATH (views):\n")
    print(f"  avg read QPS   = {views_day:,} / 86400 = {read_avg:,.1f}")
    print(f"  peak read QPS  = {read_avg:,.1f} * {peak_factor:.0f} = {read_peak:,.1f}")
    print(f"  read egress    = {read_peak:,.0f} * {photo_bytes/KB:.0f} KB = {read_bw/GB:.2f} GB/s")
    print(f"  -> {read_bw/GB:.1f} GB/s peak: NO single server can deliver this. A CDN MUST serve it.\n")
    print("STORAGE:\n")
    print(f"  per day    = {uploads_day:,} * {photo_bytes/KB:.0f} KB = {human_size(storage_day)}/day")
    print(f"  3 years    = {human_size(storage_day)} * 365 * {years:.0f} = {human_size(storage_3yr)}")
    print(f"  -> metadata (~500B/photo) = {uploads_day*500*365*years/TB:,.1f} TB in 3yr; photos -> S3, metadata -> sharded Postgres\n")

    # the CDN consequence: 95% hit rate cuts origin load
    hit = 0.95
    origin_reads = read_peak * (1 - hit)
    print("CDN (95% cache hit rate):\n")
    print(f"  origin sees only {(1-hit)*100:.0f}% of reads = {origin_reads:,.0f} QPS")
    print(f"  -> a few app servers handle origin easily; the CDN absorbs {hit*100:.0f}%.\n")

    # when do you shard the metadata DB?
    meta_qps = read_avg + write_avg
    shards = max(1, int(meta_qps // SINGLE_DB_QPS) + 1)
    print("SHARDING DECISION:\n")
    print(f"  metadata read+write QPS ~ {meta_qps:,.0f}; single DB ~ {SINGLE_DB_QPS:,} QPS")
    print(f"  -> need ~{shards} shards from year 1 (shard by user_id)\n")

    # GOLD scalars pinned for the .html
    print("GOLD scalars (for a compact .html check):")
    print(f"  write_avg_qps   = {write_avg:.1f}")
    print(f"  read_avg_qps    = {read_avg:.1f}")
    print(f"  write_peak_qps  = {write_peak:.1f}")
    print(f"  read_peak_qps   = {read_peak:.1f}")
    print(f"  read_bandwidth_gb = {read_bw/GB:.2f}")
    print(f"  storage_day_tb  = {storage_day/TB:.1f}")
    print(f"  storage_3yr_pb  = {storage_3yr/PB:.2f}")
    print(f"  origin_qps_95   = {origin_reads:.1f}")
    print(f"  shards_meta     = {shards}")

    # assertions (pin the exact computed values the .html recomputes)
    assert round(write_avg, 1) == 578.7
    assert round(read_avg, 1) == 5787.0
    assert round(write_peak, 1) == 1736.1
    assert round(read_peak, 1) == 17361.1
    assert round(read_bw / GB, 2) == 3.47
    assert round(storage_day / TB, 1) == 10.0
    assert round(storage_3yr / PB, 2) == 10.95
    assert round(origin_reads, 1) == 868.1
    assert shards == 3
    print("\n[check] capacity template (qps/peak/bandwidth/storage/cache/shard) all hold: OK")


# ---------------------------------------------------------------------------
def main():
    print("system_design_framework.py - building blocks & capacity planning. All")
    print("numbers below feed SYSTEM_DESIGN_FRAMEWORK.md. Python stdlib only.")
    print()
    section_a()
    section_b()
    section_c()
    section_d()
    gold_check()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
