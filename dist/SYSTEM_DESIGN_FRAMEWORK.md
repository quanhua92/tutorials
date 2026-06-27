# System Design Framework — Building Blocks, Composition & Capacity Planning

> A concept bundle for high-level system design. Every number below is printed by
> **[`system_design_framework.py`](./system_design_framework.py)** (pure Python
> stdlib, run with `python3 system_design_framework.py`) and recomputed live in
> **[`system_design_framework.html`](./system_design_framework.html)**. This guide
> never hand-computes anything — it cites the `.py` output verbatim.
>
> 🔗 Interactive companion: [`system_design_framework.html`](./system_design_framework.html) &nbsp;|&nbsp;
>    Source of truth: [`system_design_framework.py`](./system_design_framework.py) &nbsp;|&nbsp;
>    Live capture: [`system_design_framework_output.txt`](./system_design_framework_output.txt)

---

## 0. The one-paragraph version

High-level system design is **composition**: you take a small set of building
blocks and wire them so the load hits each in the order it is good at. The same
**five blocks** appear in almost every backend — **load balancer** (distribute),
**cache** (fast reads), **database** (durable truth), **message queue** (decouple
in time), and **CDN** (move bytes close to users) — and knowing what each is
*for* (and not for) is 80% of the work. **Numbers come before architecture**: a
single Postgres handles ~1–5K QPS, so you estimate read/write QPS first; above
~10K read QPS you need a cache, above ~5K write QPS you need sharding, and the
estimate decides which block is even relevant. The **capacity template**
(`qps = daily/86400`, `peak = qps × 3`, `bandwidth = peak × payload`,
`storage = daily_new × bytes × years`) finds the first saturated resource; the
**component-selection matrix** then maps the workload to the right variant of
each block.

> From `system_design_framework.py` GOLD CHECK (the headline numbers):
> ```text
>   write_avg_qps   = 578.7
>   read_avg_qps    = 5787.0
>   write_peak_qps  = 1736.1
>   read_peak_qps   = 17361.1
>   read_bandwidth_gb = 3.47
>   storage_day_tb  = 10.0
>   storage_3yr_pb  = 10.95
>   origin_qps_95   = 868.1
>   shards_meta     = 3
> ```

This is the **system-design-framework overlay** of the `dist/` suite. It connects
the "how do you actually build it" question to the building blocks the deeper
bundles expand on:
[`consistent_hashing_lb.py`](https://github.com/quanhua92/tutorials/blob/main/dist/consistent_hashing_lb.py)
(load balancer internals),
[`circuit_breaker.py`](https://github.com/quanhua92/tutorials/blob/main/dist/circuit_breaker.py)
(failure isolation between blocks),
[`backpressure.py`](https://github.com/quanhua92/tutorials/blob/main/dist/backpressure.py)
(queue burst absorption),
[`cap_tradeoffs.py`](https://github.com/quanhua92/tutorials/blob/main/dist/cap_tradeoffs.py)
(the DB consistency story),
[`saga_pattern.py`](https://github.com/quanhua92/tutorials/blob/main/dist/saga_pattern.py)
(cross-service work via queues), and
[`architectural_patterns.py`](https://github.com/quanhua92/tutorials/blob/main/dist/architectural_patterns.py)
(how the blocks aggregate into topologies).

---

## 1. Section A — the five building blocks

Almost every backend is the same five blocks wired so the load hits each in the
order it is good at.

> From `system_design_framework.py` Section A:
> ```text
>   | block        | job                | good at            | NOT for            |
>   |--------------|--------------------|--------------------|--------------------|
>   | load balancer| distribute traffic | spreading load     | state (it is dumb) |
>   | cache        | fast reads         | hot keys, <1ms     | source of truth    |
>   | database     | durable truth      | consistency, query | raw bytes, petabyte|
>   | message queue| decouple in time   | absorbing bursts   | low-latency RPC    |
>   | CDN          | move bytes close   | static, global     | per-user dynamic   |
> ```

- **Load balancer:** distribute. L4 (TCP) is fast and opaque; L7 (HTTP) is smart
  (path routing, SSL offload, header manipulation) but adds a hop. Place it at
  the edge (user → LB → app) and between tiers (app → LB → DB/cache pool).
- **Cache:** the cheapest read-scaling lever. A cache turns a 5ms DB read into a
  0.5ms memory read for the hot keys. The hard part is **invalidation** (TTL too
  long = stale; too short = stampede), not the read.
- **Database:** the source of truth. Pick by workload — relational for
  consistency + joins, wide-column for write-heavy scale, in-memory for sub-ms,
  blob for files. **Never store binary blobs in a DB**: metadata in the DB, bytes
  in S3.
- **Message queue:** decouple in time. The producer writes and returns
  immediately; consumers pull at their own pace. The queue **absorbs bursts**
  (a flash sale fills the queue, not the database) and enables fan-out. Dead-letter
  after 3–5 retries.
- **CDN:** move bytes close to users. ~200 edge POPs cache static content so a
  Tokyo user fetches from Tokyo, not Virginia. Cuts origin load to a fraction and
  latency to <50ms globally — but only for cacheable content.

> From `system_design_framework.py` Section A (the latency ladder):
> ```text
>   | operation          | latency    | block          |
>   |---------------------|------------|----------------|
>   | memory read         |   0.0001 ms | cache (hot)    |
>   | SSD read            |   0.1500 ms | database       |
>   | HDD seek            |  10.0000 ms | (avoid)        |
>   | network, same DC    |   0.5000 ms | infra          |
>   | network, cross-region| 80.0000 ms | (why a CDN)    |
>   | Redis GET           |   0.7000 ms | cache          |
>   | Postgres indexed    |   3.0000 ms | database       |
>   | S3 GET              | 120.0000 ms | CDN origin     |
> >
>   [check] memory > 50000x faster than HDD => cache sidesteps the slow path: OK
> ```

Memory is ~100,000x faster than an HDD seek; a Redis GET is ~4x faster than an
indexed Postgres query. These gaps are *why* the cache exists — it sidesteps the
slow path entirely for hot keys. 🔗 Deeper load-balancer internals in
[`CONSISTENT_HASHING_LB.md`](https://github.com/quanhua92/tutorials/blob/main/dist/CONSISTENT_HASHING_LB.md).

---

## 2. Section B — the capacity planning template

Back-of-envelope estimation finds the **first saturated resource**: request rate,
storage, bandwidth, or memory.

> From `system_design_framework.py` Section B:
> ```text
>   qps          = daily_ops / 86400        # average
>   peak_qps     = qps * peak_factor        # 3-5x average
>   bandwidth    = peak_qps * payload_bytes # bytes/sec egress
>   storage      = daily_new * bytes_each * days * years
>   cache_miss   = (1 - hit_rate) * read_qps # origin load after cache
> ```

The thresholds that trigger each block:

> From `system_design_framework.py` Section B:
> ```text
>   | signal                   | threshold      | triggers           |
>   |--------------------------|----------------|--------------------|
>   | read QPS                 | > ~5K-10K      | cache (then replica)|
>   | write QPS                | > ~2K-5K       | shard / wide-column|
>   | storage                  | > ~10TB        | blob store, shard DB|
>   | per-op latency           | > ~500ms       | queue (async offload)|
>   | global users             | > 1 region     | CDN (edge caching) |
> ```

**Worked mini-example** (notifications API): 10M/day normal, 100M/day in a spike.
Payload 500 bytes.

> From `system_design_framework.py` Section B:
> ```text
>   normal  10,000,000/day -> avg 116 QPS, peak 347 QPS, egress 0.2 MB/s
>   spike  100,000,000/day -> avg 1,157 QPS, peak 3,472 QPS, egress 1.7 MB/s
> >
>   [check] spike = 10x normal, peak > single-DB threshold => queue absorbs burst: OK
> ```

The spike is 10x normal. A synchronous "send now" design would need 10x the
capacity idle most of the time. A **queue** absorbs the spike: the producer
writes 100M events fast; consumers drain at a steady rate. The queue IS the
buffer. 🔗 Deeper treatment in
[`BACKPRESSURE.md`](https://github.com/quanhua92/tutorials/blob/main/dist/BACKPRESSURE.md).

---

## 3. Section C — composition: wiring the blocks into a request flow

The five blocks compose in a fixed order along the request path:

> From `system_design_framework.py` Section C:
> ```text
>   user -> CDN -> load balancer -> app -> cache -> (miss?) -> database
> ```

Each block is a **gate** that either satisfies the request or passes it on:

> From `system_design_framework.py` Section C:
> ```text
>   | gate         | satisfies?            | on miss, forwards to |
>   |--------------|-----------------------|----------------------|
>   | CDN          | static + cacheable    | load balancer (origin)|
>   | load balancer| never (just routes)   | an app instance      |
>   | app + cache  | hot key in cache      | database             |
>   | database     | always (source of truth)| - (end of the line)|
> ```

The further **left** a request is satisfied, the cheaper and faster it is. A CDN
hit costs ~nothing and is <50ms; a DB hit is ~3ms + compute + the load of every
gate before it. So you push work left: cache hot keys so the DB is never touched;
cache static assets at the CDN so the origin is never touched.

**Writes** flow differently — they go right to the source of truth, then
propagate left asynchronously:

> From `system_design_framework.py` Section C:
> ```text
>   user -> LB -> app -> database (commit) -> CDC/Kafka -> cache/CDN update
> ```

The write commits to the DB (durable truth); the cache and CDN update later
(eventual consistency, ~50–500ms). This is the cache-aside + CDC pattern, and it
is why reads are fast (left gate) and writes are safe (right to truth first).

> From `system_design_framework.py` Section C (cache hit rate → DB load):
> ```text
>   | cache hit rate | satisfied by cache | reach DB (misses) | DB load vs raw |
>   |----------------|--------------------|-------------------|----------------|
>   |   50%          |     10,000         |      5,000        |    50% of raw  |
>   |   80%          |     10,000         |      2,000        |    20% of raw  |
>   |   90%          |     10,000         |      1,000        |    10% of raw  |
>   |   95%          |     10,000         |        500        |     5% of raw  |
>   |   99%          |     10,000         |        100        |     1% of raw  |
> >
>   [check] 90% cache hit cuts DB load 10x; hit rate decides shard-or-not: OK
> ```

At 90% hit rate the DB sees only 10% of reads (1K vs 10K) — a single DB handles
it. At 50% it sees 5K, near the single-node ceiling. **The cache hit rate is the
single most important number in a read-heavy system: it decides whether you need
one DB or a sharded cluster.**

---

## 4. Section D — the component-selection tradeoff matrix

Each block has variants; the choice follows the workload.

> From `system_design_framework.py` Section D (database selection):
> ```text
>   | workload              | best choice   | why                                   |
>   |-----------------------|---------------|---------------------------------------|
>   | user profiles / OLTP  | PostgreSQL    | strong consistency, joins, ACID       |
>   | session / leaderboard | Redis         | in-memory, sub-ms, sorted sets        |
>   | time-series / metrics | Cassandra     | write-optimized, huge scale           |
>   | flexible documents    | MongoDB       | schemaless, horizontal scale          |
>   | full-text search      | Elasticsearch | inverted index, relevance scoring     |
>   | images / video        | S3            | cheap, durable, CDN-ready (NOT a DB)  |
> ```

> From `system_design_framework.py` Section D (cache write strategy):
> ```text
>   | strategy     | write goes to        | consistency      | use when           |
>   |--------------|----------------------|------------------|--------------------|
>   | cache-aside  | DB; cache filled on read| eventual      | default            |
>   | write-through| DB + cache together  | strong          | stale reads fatal  |
>   | write-behind | cache; async to DB   | eventual (risk) | write-heavy        |
> ```

**The economics** — cache first, replicate second:

> From `system_design_framework.py` Section D:
> ```text
>   | option              | QPS added   | cost $/mo   | $ per 1K QPS |
>   |---------------------|-------------|-------------|--------------|
>   | Redis cache node    |   100,000   |       500   |         5.00 |
>   | 4th read replica    |     5,000   |     5,000   |      1000.00 |
> >
>   [check] Redis >10x cheaper per QPS than a replica => cache before replicate: OK
> ```

Redis at $500/mo adds 100K QPS; a 4th replica at $5000/mo adds only 5K QPS. The
cache is 10x cheaper per QPS — always add the cache before the 4th replica.

---

## 5. Gold check — the full capacity worked example: Design Instagram

The capstone: the full back-of-envelope for a photo-sharing service, every number
recomputed from the Section B template. Scale assumptions: 1B users, 100M DAU,
50M photo uploads/day, 500M views/day, average photo 200KB, read:write 10:1.

> From `system_design_framework.py` GOLD CHECK:
> ```text
>   WRITE PATH (uploads):
>     avg write QPS  = 50,000,000 / 86400 = 578.7
>     peak write QPS = 578.7 * 3 = 1,736.1
>     upload egress  = 1,736 * 200 KB = 0.35 GB/s
>   READ PATH (views):
>     avg read QPS   = 500,000,000 / 86400 = 5,787.0
>     peak read QPS  = 5,787.0 * 3 = 17,361.1
>     read egress    = 17,361 * 200 KB = 3.47 GB/s
>     -> 3.5 GB/s peak: NO single server can deliver this. A CDN MUST serve it.
>   STORAGE:
>     per day    = 50,000,000 * 200 KB = 10.00 TB/day
>     3 years    = 10.00 TB * 365 * 3 = 10.95 PB
>     -> metadata (~500B/photo) = 27.4 TB in 3yr; photos -> S3, metadata -> sharded Postgres
>   CDN (95% cache hit rate):
>     origin sees only 5% of reads = 868 QPS
>     -> a few app servers handle origin easily; the CDN absorbs 95%.
>   SHARDING DECISION:
>     metadata read+write QPS ~ 6,366; single DB ~ 3,000 QPS
>     -> need ~3 shards from year 1 (shard by user_id)
> ```

Every downstream design decision falls out of these numbers: the read egress
(3.47 GB/s) *forces* a CDN; the storage (10.95 PB) *forces* S3 + a sharded
metadata DB; the 95% cache hit cuts origin load to 868 QPS so a few app servers
suffice. The `.html` recomputes the entire template live as you adjust DAU,
read:write ratio, payload, and peak factor — a green `check: OK` badge means the
JS numbers match the `.py` exactly. 🔗 Deeper cross-service composition in
[`SAGA_PATTERN.md`](https://github.com/quanhua92/tutorials/blob/main/dist/SAGA_PATTERN.md).

---

## 6. References

- **Martin Kleppmann** — *Designing Data-Intensive Applications*: the canonical
  text; every block and the tradeoffs explained rigorously.
- **CalibreOS HLD framework** — the CIRCLE/RACED method and the back-of-envelope
  cheat sheet (the basis of the Section B template).
- **Jeff Dean** — "Numbers Every Engineer Should Know" (the latency ladder).
- **Redis documentation** — in-memory data store: cache, session, leaderboard.
- **Apache Kafka documentation** — distributed log: durable queue + fan-out.
- **CloudFront / Fastly** — CDN edge caching; cache-control headers, invalidation.
- **HAProxy / Nginx** — L4/L7 load balancing; health checks, session affinity.

🔗 Back to [`system_design_framework.html`](https://github.com/quanhua92/tutorials/blob/main/dist/system_design_framework.html)
for the interactive component composer and the live capacity calculator.
