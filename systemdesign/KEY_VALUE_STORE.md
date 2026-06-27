# Design a Key-Value Store (LSM-Tree)

> **Companion code:** [`key_value_store.py`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/key_value_store.py).
> **Live demo:** [`key_value_store.html`](./key_value_store.html) — step through
> the write path (WAL → memtable → SSTable → compaction), watch reads walk the
> levels with a Bloom filter, and tune the amplification calculator.
>
> **Every number in this guide is printed by `python3 key_value_store.py`** —
> nothing hand-computed.

---

## 0. TL;DR — the inbox that turns into a filing cabinet

> **The mental model:** Writes land in an in-memory **inbox** (the *memtable*).
> Before anything is touched, the envelope is **postmarked** (appended to the
> **WAL** on disk) so a crash loses nothing. When the inbox overflows we **sort
> it once** and write it as an immutable on-disk **SSTable** (a *filing-cabinet
> drawer*). Background **compaction** periodically merges drawers so stale
> versions and tombstones don't pile up. Reads check the inbox first, then the
> most recent drawers, then older ones — a **Bloom filter** on each drawer
> skips the ones that *definitely* don't hold the key. This trades random
> in-place disk writes (B-tree) for **sequential appends** → gigantic write
> throughput, at the cost of slightly more work per read.

```mermaid
graph LR
    W["client PUT/DEL"] --> WAL["WAL<br/>(append-only, fsync)"]
    WAL --> MEM["memtable<br/>(in-memory, sorted)"]
    MEM -->|"limit hit -> flush"| L0["L0 SSTables<br/>(immutable,<br/>ranges may overlap)"]
    L0 -->|"compaction"| L1["L1 SSTable<br/>(disjoint ranges)"]
    L1 --> L2["L2 ... Ln"]
    L2 -.->|"size-tiered OR leveled"| L1
    classDef store fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    classDef mem fill:#fef9e7,stroke:#f1c40f,stroke-width:2px
    classDef log fill:#fdecea,stroke:#c0392b,stroke-width:2px
    class WAL,log
    class MEM,mem
    class L0,L1,L2,store
```

```mermaid
graph LR
    G["client GET key"] --> M1{"in memtable?"}
    M1 -->|"yes"| HIT1["return (newest)"]
    M1 -->|"no"| BF{"for each SSTable<br/>newest-first:"}
    BF -->|"range skip"| SKIP1["free"]
    BF -->|"bloom: definitely no"| SKIP2["free"]
    BF -->|"bloom: maybe"| DR["disk read<br/>(binary search)"]
    DR -->|"found + live"| HIT2["return"]
    DR -->|"found + tombstone"| DEL["return NOT FOUND"]
    DR -->|"not found"| BF
    BF -->|"exhausted"| MISS["NOT FOUND"]
    classDef hit fill:#eafaf1,stroke:#27ae60
    classDef miss fill:#fdecea,stroke:#c0392b
    classDef io fill:#fef9e7,stroke:#f1c40f
    class HIT1,HIT2,hit
    class DEL,MISS,miss
    class DR,io
```

> **One-line definition:** An **LSM-tree KV store** turns every write into a
> sequential append (WAL + memtable insert), periodically sorts and flushes the
> memtable into immutable on-disk **SSTables**, and runs background
> **compaction** to merge them. Reads merge across memtable + SSTables,
> short-circuited by **Bloom filters**. This is the engine inside Cassandra,
> RocksDB, LevelDB, HBase, and Dynamo-style systems.

---

## 1. Requirements

### Functional
- `PUT(key, value)` — store a key-value pair (the hot path).
- `GET(key)` — retrieve the latest value for a key.
- `DELETE(key)` — remove a key (implemented as a *tombstone* write).
- `SCAN(start, end, limit)` — range scan over sorted keys.
- Configurable **consistency level** per operation (one / quorum / all).
- Automatic **partitioning** + **replication** + **rebalancing**.

### Non-Functional
- High write throughput — millions of writes/sec/node.
- Low read latency — p99 < 10 ms (Bloom + block cache make most reads memory-only).
- Horizontal scalability to petabytes across hundreds of nodes.
- **Durability** — no data loss on node failure (WAL fsync per write).
- **Tunable consistency** — eventual by default, strong on demand (quorum).
- 99.99 % availability — tolerate node + network failures.

---

## 2. Scale Estimation

> From `key_value_store.py` **Section E** (write-heavy workload, RF=3):

| Metric | Value |
|---|---|
| Writes/sec | 500,000 |
| Reads/sec | 1,000,000 (read:write ≈ **2:1**) |
| Key + value size | 100 B + 1 KB = 1,124 B/op |
| Total keys | 10 B |
| Logical storage (1 copy) | **10.2 TB** |
| Storage with RF=3 | **30.6 TB** |
| Write bandwidth (user) | **4,496 Mbps ≈ 4.50 Gbps** |
| Read bandwidth (user) | **8,992 Mbps ≈ 8.99 Gbps** |
| Cluster size | ~100 nodes (≈ 300 GB/node raw) |

> **Why this skews write-heavy in practice:** even at a 2:1 read:write ratio,
> LSM is chosen when *writes* dominate cost. Random B-tree writes max out the
> disk's IOPS long before the network saturates; LSM's sequential appends let
> you fill the network pipe.

---

## 3. Architecture

### Write path (PUT / DELETE)

```mermaid
graph TB
    C["client"] -->|"PUT k v"| CO["coordinator node<br/>(hash k -> partition)"]
    CO -->|"replicate to N=3"| R1["replica A"]
    CO --> R2["replica B"]
    CO --> R3["replica C"]
    R1 --> W1["1. fsync WAL"]
    W1 --> W2["2. insert memtable"]
    W2 --> W3["3. ack (W=2 quorum)"]
    W2 -->|"limit hit"| FL["4. flush -> immutable SSTable in L0"]
    FL --> CP["5. background compaction"]
    CP --> LV["L1, L2, ... (10x larger each)"]
    classDef hot fill:#eafaf1,stroke:#27ae60,stroke-width:2px
    class W1,W2,W3,hot
    classDef cool fill:#eaf2f8,stroke:#2980b9
    class FL,CP,LV,cool
```

### Read path (GET)

```mermaid
graph LR
    GET["GET k"] --> MEM{"memtable?"}
    MEM -->|"hit"| DONE["return"]
    MEM -->|"miss"| L0["scan L0 SSTables<br/>(newest first, ranges overlap)"]
    L0 --> L1["scan L1 (disjoint ranges,<br/>≤1 SSTable holds k)"]
    L1 --> LN["... Ln"]
    LN --> MISS["NOT FOUND"]
    L0 -.->|"each SSTable: range guard<br/>-> bloom filter -> disk read"| L1
    classDef hit fill:#eafaf1,stroke:#27ae60
    classDef io fill:#fef9e7,stroke:#f1c40f
    classDef miss fill:#fdecea,stroke:#c0392b
    class DONE,hit
    class L0,L1,LN,io
    class MISS,miss
```

### Key Components

| Component | Technology (real-world) | Why |
|---|---|---|
| **WAL** | Append-only file, `fsync(2)` per write or batched | Durability — replay rebuilds memtable on crash. |
| **Memtable** | Skip list / red-black tree (in-memory, sorted) | O(log n) insert + ordered scan; cheap to flush. |
| **SSTable** | Immutable, key-sorted file + index block + Bloom filter | Sequential reads, no in-place mutation, shareable across nodes. |
| **Block cache** | LRU over SSTable data blocks (off-heap) | Most reads served from RAM. |
| **Compaction** | Background thread pool, STCS / LCS / TWCS | Bounds read + space amplification. |
| **Partitioner** | Murmur3 hash / consistent hashing | Even distribution; minimal reshuffle on add/remove node. |
| **Replication** | Leaderless (Dynamo-style), RF=3 | No leader bottleneck; survives 1 node loss with quorum. |
| **Gossip** | Phi-Accrual failure detector (Cassandra-style) | Decentralized membership + failure detection. |
| **Hinted handoff** | Coordinator stores writes for down replicas | Catches up a briefly-down replica without anti-entropy. |
| **Anti-entropy** | Merkle tree per token range | Detects + repairs long-running divergence between replicas. |

---

## 4. Key Design Decisions

### 4.1 Storage engine: B-tree vs LSM

| Decision | **Option A: LSM-tree** | Option B: B-tree |
|---|---|---|
| Write cost | **O(1) append** to WAL + memtable insert | O(log n) random in-place page write |
| Read cost | O(levels) — memtable + each SSTable | **O(log n)** — single tree descent |
| Best fit | **Write-heavy, petabyte-scale** | Read-heavy, transactional (RDBMS) |
| Used by | Cassandra, RocksDB, LevelDB, HBase, DynamoDB | PostgreSQL, MySQL/InnoDB, SQLite |
| Winner | ✅ **LSM** — the workload is write-heavy at scale | |

### 4.2 Compaction strategy

| Decision | **Size-tiered (STCS)** | Leveled (LCS) | Time-window (TWCS) |
|---|---|---|---|
| Write amp | **~T (4×)** | ~T·(L−1) (30×) | ~T (low) |
| Read amp | T·L (16 SSTables worst-case) | **L (4)** | depends |
| Space amp | T (4×) | **1+1/T (1.1×)** | depends |
| Best fit | **Write-heavy** (default in Cassandra) | Read-heavy (RocksDB default) | Time-series with TTL |
| Winner | ✅ **STCS** for this workload | | |

> From `key_value_store.py` **Section E** (T=10 fanout, L=4 levels, T_st=4):

| metric | size-tiered | leveled |
|---|---:|---:|
| write amp (disk / user) | **4×** | 30× |
| read amp (SSTables / GET, worst case) | 16 | **4** |
| space amp (disk / live) | 4× | **1.1×** |
| disk write BW at 4.5 Gbps user writes | **18.0 Gbps** | 134.9 Gbps |

STCS writes **~8× less** to disk than LCS at this workload; the price is up to
**4× more SSTable lookups per GET** and **~4× more disk space** transiently.

### 4.3 Consistency model

| Decision | **Option A: Tunable, leaderless (Dynamo)** | Option B: Strong, single-leader |
|---|---|---|
| Write availability | **Any coordinator can accept** | Leader is a bottleneck + SPOF |
| Default consistency | Eventual (W=1, R=1) | Linearizable |
| Strong reads | Quorum W+R > RF | Always |
| Conflict resolution | Last-write-wins (timestamp) / vector clocks | None needed |
| Winner | ✅ **Leaderless** — availability + write throughput | |

With **RF=3, W=R=2**: `W + R = 4 > RF = 3` → quorum intersection guarantees a
read sees the latest committed write for a single key (verified in
`key_value_store.py` **Section D**).

### 4.4 Partitioning

| Decision | **Option A: Hash partitioning + consistent hashing** | Option B: Range partitioning |
|---|---|---|
| Distribution | **Even (murmur3)** | Skewed by key distribution |
| Range scans | Slow (must contact all nodes) | **Native** |
| Hot keys | Spread across the ring | Hotspots at popular ranges |
| Reshard cost | **Only K/n keys move** (consistent hashing) | Range splits are heavier |
| Winner | ✅ **Hash + consistent hashing** — even load, cheap reshard | |

---

## 5. Data Model

The internal SSTable row carries MVCC metadata so reads at any snapshot work and
deletes are durable until compaction physically removes them.

| Field | Type | Notes |
|---|---|---|
| `user_key` | byte string | The application key (≤ 100 B). |
| `value` | byte blob | Up to ~10 MB; large values usually go to object storage. |
| `version / sequence` | int64 | Monotonically increasing; latest wins on merge. |
| `vector_clock` | list[(node_id, counter)] | Conflict detection in multi-leader setups. |
| `timestamp` | int64 (µs) | Wall clock for last-write-wins; tie-break + TTL. |
| `tombstone` | bool | `DELETE` writes a tombstone, not an immediate removal. |
| `ttl` | int32 (seconds, optional) | Key auto-expires; compaction drops it once expired. |

> From `key_value_store.py` **Section C**: when the merge sees both an old
> `(k, v_old, seq=2)` and a newer `(k, v_new, seq=5)`, the **highest seq wins**.
> A tombstone with seq=5 shadows any older live value. Both behaviors are
> asserted in the GOLD section.

---

## 6. API

| Method | Path | Body / Params | Response | Notes |
|---|---|---|---|---|
| `PUT` | `/v1/keys/{key}` | `{"value": "...", "ttl": 3600}` | `201 Created` | WAL → memtable → ack on W quorum. |
| `GET` | `/v1/keys/{key}` | — | `{"key","value","version"}` or `404` | Memtable → SSTables (Bloom-guarded). |
| `DELETE` | `/v1/keys/{key}` | — | `204 No Content` | Writes a **tombstone**, not a physical delete. |
| `POST` | `/v1/keys/scan` | `{"start","end","limit"}` | `[{"key","value"}, ...]` | Merge-iterator over SSTables. |
| `PUT` | `/v1/keys/{key}?consistency=quorum` | header `X-Consistency: all` | — | Per-request tunable consistency. |

---

## 7. Consistency mechanisms (when replicas drift)

> From `key_value_store.py` **Section D** — three complementary repair paths:

| Mechanism | When it runs | Cost | What it fixes |
|---|---|---|---|
| **Read repair** | On every quorum read that sees divergent values | Tiny (1 extra write per stale replica) | **Recent** drift caught at read time. |
| **Hinted handoff** | A replica is briefly unreachable | Bounded (hint stored at coordinator, replayed on rejoin) | A **short** outage window. |
| **Anti-entropy (Merkle)** | Periodic background sweep | Bounded (only differing ranges streamed) | **Long-running** divergence the first two miss. |

```mermaid
graph LR
    W["write"] --> A["A: v3"]
    W --> B["B: v3"]
    W -.->|"C down: hint stored"| H[("hint")]
    R["read (R=2)"] --> A
    R --> B
    R --> RR["read repair:<br/>write v3 to stale replica"]
    H -->|"C rejoins"| C["C: v3"]
    AE["periodic anti-entropy:<br/>Merkle root compare"] --> A
    AE --> C
    classDef fix fill:#eafaf1,stroke:#27ae60
    class RR,C,fix
```

---

## 8. Scale numbers — what the math says

> From `key_value_store.py` **Section E** — a single node on a write-heavy
> workload, RF=3, T=10 fanout, L=4 levels, T_st=4 size-tiered threshold.

| What | Formula | size-tiered | leveled |
|---|---|---:|---:|
| Write amplification | STCS: `T_st`; LCS: `T·(L−1)` | **4×** | 30× |
| Read amplification | STCS: `T_st·L`; LCS: `L` | 16 | **4** |
| Space amplification | STCS: `T_st`; LCS: `1 + 1/T` | 4× | **1.1×** |
| Disk write BW @ 4.5 Gbps user writes | `user × WA` | **18 Gbps** | 135 Gbps |

> **Why writes are cheap and reads are expensive:** every user PUT is *one*
> sequential WAL append + *one* memtable insertion — both in-memory or
> sequential. A B-tree PUT is a random 4 KB page write (in-place mutation). At
> spinning-rust or cheap-NAND IOPS budgets, the LSM write is essentially free;
> the B-tree write is the bottleneck. The tax shows up on reads (multiple
> SSTables) and is paid down by Bloom filters + block cache + compaction.

---

## Killer Gotchas

- **Write amplification can surprise you.** Leveled compaction's `T·(L−1)` ≈
  30× is the *steady-state* cost; with `L0` stalls (compaction can't keep up)
  the WAL can't flush and writes stall. **Monitor pending compaction bytes**,
  not just user QPS. *Cassandra operators have a name for this:
  "compaction storm."*
- **Read amplification is worst at L0.** All L0 SSTables can overlap, so a GET
  may have to consult *all of them*. The fix is aggressive L0→L1 compaction,
  but that's exactly what triggers write amp. **Tune `min_threshold` and
  `max_threshold` together**, not independently.
- **Bloom filters are per-SSTable, not global.** When compaction finishes, the
  old Bloom filters are *deleted and rebuilt*. A brief window exists where the
  new SSTable's Bloom filter hasn't loaded into RAM yet — first reads to it
  hit disk. Pre-load Bloom filters into RAM after compaction.
- **Tombstones don't free space until compaction.** A `DELETE` is a write —
  the tombstone lives in an SSTable until a compaction merges it and discards
  the row. **GC grace period (default 10 days in Cassandra)** prevents a
  tombstone from being dropped before a delayed replica sees it — shortering
  this can resurrect deleted data.
- **Hinted handoff is bounded; don't use it for long outages.** Hints are kept
  for `max_hint_window` (default 3 h in Cassandra); beyond that the coordinator
  drops them and only **anti-entropy repair** can recover consistency. Run
  `nodetool repair` on a schedule.
- **Quorum ≠ strong consistency across keys.** `W+R > RF` gives linearizable
  reads *for a single key* (last-write-wins), not serializable multi-key
  transactions. Use **LWT (lightweight transactions / Paxos)** for compare-and-set,
  at a 4–10× latency cost.
- **Read repair is a write in disguise.** Every divergent quorum read fires a
  write-back. Under sustained skew this can amplify write load silently; cap
  `read_repair` probability or use `DCLOCAL` for cross-DC traffic control.
- **Range scans are O(SSTables).** Without secondary indexes, `SCAN` must open a
  merge iterator over *every* SSTable in every level. Leveled compaction keeps
  this tractable; size-tiered can be brutal at high write rates.

---

## Sources

- O'Neil et al., *"The Log-Structured Merge-Tree (LSM-Tree)"* (SIGMOD '96) — the
  original LSM paper.
- DeCandia et al., *"Dynamo: Amazon's Highly Available Key-Value Store"* (SOSP '07)
  — leaderless quorum, vector clocks, hinted handoff, Merkle anti-entropy.
- Lakshman & Malik, *"Cassandra — A Decentralized Structured Storage System"*
  (SIGMOD '10) — production LSM + gossip + tunable consistency.
- RocksDB wiki, *"Write-Amplification, Read-Amplification and Space-Amplification"*
  — the T, L, T_st formulas used in Section E.
- Kirsch & Mitzenmacher, *"Less Hashing, Same Performance: Building a Better
  Bloom Filter"* (ESA '06) — the double-hashing trick used in
  `BloomFilter._hashes`.
- Source-of-truth simulation:
  [`key_value_store.py`](https://github.com/quanhua92/tutorials/blob/main/systemdesign/key_value_store.py).
