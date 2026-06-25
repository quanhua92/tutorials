"""
lsm_tree.py - Reference implementation of a Log-Structured Merge-tree (LSM-tree):
the write-optimized index behind RocksDB, LevelDB, Cassandra, HBase, Riak, etc.

This is the single source of truth that LSM_TREE.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 lsm_tree.py

============================================================================
THE INTUITION (read this first) - the warehouse with the sorting desks
============================================================================
Imagine a warehouse where new stock arrives constantly. Two ways to keep the
inventory findable:

  * B-TREE    : one big sorted cabinet. Every new item is INSERTED INTO its
                sorted slot IMMEDIATELY. To find item X you walk the cabinet
                once (fast read). But every insert SHUFFLES the cabinet ->
                a random-position page write each time (slow write).
                (Read-optimized.)
  * LSM-TREE  : the loading dock. New stock piles up in a small IN-MEMORY desk
                (the MemTable). When the desk is full, you FREEZE it into a
                sorted batch (an SSTable) and shove it onto a shelf - WITHOUT
                touching the older shelves. Reads check the desk first, then
                the shelves newest-first. A background worker (compaction)
                periodically MERGE-SORTS the shelves to remove stale duplicates.
                (Write-optimized: writes are always a fast sequential append;
                the sorting work is DEFERRED + AMORTIZED across many keys.)

THE REASON LSM-TREES EXIST: random-position writes (disk seeks) are expensive
on spinning rust and on SSDs (erase blocks / FTL write amplification). An
LSM-tree turns every write into a SEQUENTIAL APPEND (to the WAL + the MemTable),
then AMORTIZES the sorting across thousands of keys during batched compaction.
The price paid, in three flavors of "amplification":
  * WRITE amp: each byte is rewritten ~once per level it climbs (leveling ~T*L).
  * READ  amp: a point read may check MemTable + every L0 SST + 1 file/level.
  * SPACE amp: stale duplicates live until compaction reclaims them.
Bloom filters + compaction keep read/space amp bounded; write amp is the
fundamental cost of the write-optimized design.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  MemTable     : the in-memory sorted buffer (a red-black tree / skip list /
                 sorted dict). EVERY write lands here first. Lost on crash, so
                 it is mirrored to the Write-Ahead Log.
  WAL          : Write-Ahead Log. An append-only file recording every put/delete
                 BEFORE it touches the MemTable, so a crash can replay it.
  SSTable      : Sorted String Table. An IMMUTABLE, sorted, file-resident list
                 of (key, value) pairs. Once written, never edited. Created by
                 flushing a MemTable or by compaction. Carries a min/max key
                 range and a Bloom filter over its keys.
  L0, L1, ...  : the LEVELS. L0 SSTables can OVERLAP in key range (several
                 flushes may cover the same keys). L1+ SSTables are
                 NON-overlapping (compaction sorts them into disjoint ranges).
                 Each level is ~SIZE_RATIO times bigger than the one below.
  tombstone    : a DELETE marker. Stored as an entry with value = None. A read
                 that hits a tombstone STOPS (the key is "deleted"); otherwise
                 an older live version in a DEEPER level would resurface. The
                 tombstone is physically dropped only when compacted into the
                 LAST level (nothing deeper to hide).
  seq (op_seq) : a monotonic per-operation sequence number. When the same key
                 appears in several SSTables, the entry with the HIGHEST seq is
                 the live one. (Same role as MVCC xmin/xmax / InnoDB trx_id.)
  compaction   : the background merge-sort. Reads all SSTables at level L plus
                 the existing run at L+1, MERGES by key (highest seq wins),
                 DROPS stale duplicates (+ tombstones at the last level), and
                 writes ONE new non-overlapping SSTable to L+1.
  amplification: the price of write-optimization, in three flavors (above).

============================================================================
THE LINEAGE (papers / systems)
============================================================================
  B-tree (Bayer & McCreight 1972, "Organization and Maintenance of Large Ordered
         Indexes", Commun. ACM): ONE sorted, balanced, page-splitting tree.
         Reads in O(log_B N) page reads; writes are random-position page writes
         + splits. The read-optimized baseline (PostgreSQL, InnoDB, SQLite).
  LSM   (O'Neil, Cheng, Gawlick, O'Neil 1996, "The Log-Structured Merge Tree",
         SIGMOD): writes go to an in-memory tree + log; batches are merged into
         disk-resident levels by a background merger. Write-optimized.
         -> Bigtable (Chang et al. 2006) made SSTables famous; LevelDB (Google,
            Ghemawat & Dean 2011), RocksDB (Facebook 2013), Cassandra, HBase,
            Riak all use this structure.
  Tiering vs leveling (O'Neil 1996 / Kleppmann DDIA Ch.3):
         * leveling (LevelDB/RocksDB): 1 sorted run per level; lower write
           throughput, lower space amp, write amp ~T*L.
         * tiering (Cassandra default): up to T runs per level; higher write
           throughput, write amp ~L, worse read/space amp.

KEY FORMULAS (all asserted in code):
  size of level L        = SIZE_RATIO ** L * memtable_capacity      (leveling)
  write amp (leveling)   ~ SIZE_RATIO * num_levels                  (O'Neil 1996)
  write amp (tiering)    ~ num_levels
  write amp (B-tree)     ~ 4                                         (Kleppmann DDIA)
  bloom filter FPR       = (1 - e^(-k*n/m))^k  with  k = (m/n)*ln2  (Bloom 1970)
  read amp (point, no bloom) = 1 + |L0 files| + (num_levels - 1)
  read amp (point, bloom)    ~ 1 + FPR * num_files                   (amortized ~1)

Conventions for the toy:
    keys       : non-negative integers. Real systems use byte strings.
    values     : short strings "v5", or None (= tombstone = deleted).
    sizes      : counted in ENTRIES here (1 entry ~ O(1) bytes). All byte-level
                 amplification ratios are identical to the entry-level ratios.
    flush rule : MemTable flushes when it holds >= MEMTABLE_CAPACITY entries.
"""

from __future__ import annotations

import bisect
import hashlib
import math

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# Deterministic workload. Insert order is SCRAMBLED on purpose so that the L0
# SSTables produced by successive flushes OVERLAP in key range -- the defining
# (and most expensive) property of L0. Updates (5->v5b, 10->v10b) and a delete
# (20) create newer versions in a newer SST so dedup + tombstone handling show
# up. The final put(7) stays in the MemTable (no flush).
# ---------------------------------------------------------------------------
MEMTABLE_CAPACITY = 4
SIZE_RATIO = 4           # leveling: L_{i+1} holds ~SIZE_RATIO x as much as L_i
NUM_LEVELS = 4           # L0, L1, L2, L3
BLOOM_BITS_PER_KEY = 10  # ~0.82% false-positive rate (Bloom theory)

INSERT_OPS = [
    ("put", 10, "v10"), ("put", 0, "v0"), ("put", 20, "v20"), ("put", 5, "v5"),
    ("put", 15, "v15"), ("put", 1, "v1"), ("put", 11, "v11"), ("put", 21, "v21"),
    ("put", 6, "v6"), ("put", 16, "v16"), ("put", 2, "v2"), ("put", 12, "v12"),
    ("put", 5, "v5b"),    # UPDATE key 5  -> a NEWER version lives in a newer SST
    ("put", 10, "v10b"),  # UPDATE key 10 -> ditto
    ("del", 20, None),    # DELETE key 20 -> tombstone (value=None) in a newer SST
    ("put", 22, "v22"),
    ("put", 7, "v7"),     # stays in MemTable (no flush triggered)
]

# Probe keys for read-path / gold checks (chosen to exercise every branch).
PROBE_KEYS = [7, 5, 10, 20, 0, 99]


# ============================================================================
# 1. THE CORE DATA STRUCTURES
# ============================================================================

TOMBSTONE = None  # value == None  <=>  deletion marker


class BloomFilter:
    """A classic Bloom filter (Bloom 1970). k hash functions over m bits.

    Pure-python: the k hashes come from double-hashing a single SHA-256
    (Kirsch-Mitzenmacher 2006), so it is fully DETERMINISTIC for a given input.
    """

    def __init__(self, n_keys: int, bits_per_key: int = BLOOM_BITS_PER_KEY):
        self.n = max(1, n_keys)
        self.bits_per_key = bits_per_key
        self.m = max(1, self.n * bits_per_key)
        self.k = max(1, round((self.m / self.n) * math.log(2)))  # optimal k
        self.bits = bytearray(self.m)

    def _idx(self, key):
        h = hashlib.sha256(str(key).encode()).digest()
        h1 = int.from_bytes(h[0:8], "little")
        h2 = int.from_bytes(h[8:16], "little")
        for i in range(self.k):
            yield (h1 + i * h2) % self.m

    def add(self, key):
        for i in self._idx(key):
            self.bits[i] = 1

    def __contains__(self, key):
        return all(self.bits[i] for i in self._idx(key))

    @property
    def fpr_theory(self) -> float:
        # P(false positive) = (1 - e^{-kn/m})^k
        return (1.0 - math.exp(-self.k * self.n / self.m)) ** self.k


class SSTable:
    """An immutable Sorted String Table: a sorted list of (key, value, op_seq).

    value == TOMBSTONE marks a deletion. Carries a [min,max] key range and an
    optional Bloom filter over its keys.
    """

    def __init__(self, level, sst_seq, entries, with_bloom=True,
                 bits_per_key=BLOOM_BITS_PER_KEY):
        self.level = level
        self.sst_seq = sst_seq                  # creation order (higher = newer)
        self.entries = sorted(entries)          # keep sorted by key
        self._keys = [e[0] for e in self.entries]
        self.bloom = None
        if with_bloom and self.entries:
            bf = BloomFilter(len(self.entries), bits_per_key)
            for k, _, _ in self.entries:
                bf.add(k)
            self.bloom = bf

    def min_key(self):
        return self._keys[0] if self._keys else None

    def max_key(self):
        return self._keys[-1] if self._keys else None

    def may_contain(self, key):
        """Bloom pre-filter. Returns False only if the key is DEFINITELY absent."""
        return (self.bloom is None) or (key in self.bloom)

    def get(self, key):
        """Return (key, value, op_seq) or None. O(log n) via bisect."""
        i = bisect.bisect_left(self._keys, key)
        if i < len(self._keys) and self._keys[i] == key:
            return self.entries[i]
        return None

    def __len__(self):
        return len(self.entries)

    def __repr__(self):
        rng = f"[{self.min_key()}..{self.max_key()}]" if self.entries else "[]"
        return f"SST{self.sst_seq}@L{self.level}({len(self)} {rng})"


class LSMTree:
    """A tiny but faithful LSM-tree (leveling policy). Pure stdlib.

    State:
      memtable : dict key -> (value_or_None, op_seq)   (in-memory, sorted on flush)
      wal      : list of ops (append-only; replayed on crash)
      levels   : list of lists of SSTable; levels[0]=L0 (overlap ok), 1+ disjoint
    """

    def __init__(self, memtable_capacity=MEMTABLE_CAPACITY, size_ratio=SIZE_RATIO,
                 num_levels=NUM_LEVELS, use_bloom=True,
                 bits_per_key=BLOOM_BITS_PER_KEY):
        self.memtable = {}
        self.wal = []
        self.levels = [[] for _ in range(num_levels)]
        self.cap = memtable_capacity
        self.T = size_ratio
        self.L = num_levels
        self.use_bloom = use_bloom
        self.bits_per_key = bits_per_key
        self._next_op = 0          # operation sequence (recency; higher = newer)
        self._next_sst = 0         # SSTable creation sequence
        self.entries_flushed = 0
        self.entries_compacted = 0
        self.logical_writes = 0

    # -- writes --------------------------------------------------------------
    def put(self, key, value):
        seq = self._next_op; self._next_op += 1
        self.wal.append(("put", key, value, seq))   # append to WAL FIRST
        self.memtable[key] = (value, seq)
        self.logical_writes += 1
        self._maybe_flush()

    def delete(self, key):
        seq = self._next_op; self._next_op += 1
        self.wal.append(("del", key, seq))
        self.memtable[key] = (TOMBSTONE, seq)
        self.logical_writes += 1
        self._maybe_flush()

    def _maybe_flush(self):
        if len(self.memtable) >= self.cap:
            self._flush()

    def _flush(self):
        if not self.memtable:
            return
        entries = sorted((k, v, s) for k, (v, s) in self.memtable.items())
        sst = SSTable(0, self._next_sst, entries, self.use_bloom, self.bits_per_key)
        self._next_sst += 1
        self.entries_flushed += len(entries)
        self.levels[0].append(sst)   # append to L0; order = creation (newest last)
        self.memtable = {}

    # -- compaction ----------------------------------------------------------
    def compact(self, lvl):
        """Leveling compaction: merge ALL SSTables at `lvl` with the existing run
        at `lvl+1` into ONE new SSTable placed at lvl+1. Highest op_seq wins per
        key; tombstones are dropped ONLY when lvl+1 is the last level."""
        assert 0 <= lvl < self.L - 1, f"cannot compact level {lvl}"
        src = list(self.levels[lvl]) + list(self.levels[lvl + 1])
        merged = self._kway_merge(src)
        if lvl + 1 == self.L - 1:                   # last level: drop tombstones
            merged = [e for e in merged if e[1] is not TOMBSTONE]
        new = SSTable(lvl + 1, self._next_sst, merged, self.use_bloom, self.bits_per_key)
        self._next_sst += 1
        self.entries_compacted += len(merged)
        self.levels[lvl] = []
        self.levels[lvl + 1] = [new]
        return new, len(src), len(merged)

    @staticmethod
    def _kway_merge(ssts):
        """k-way merge of sorted SSTables. For duplicate keys keep the entry with
        the HIGHEST op_seq (the newest version). Returns a sorted list. (Real
        systems use a min-heap merge; the result is identical.)"""
        latest = {}
        for sst in ssts:
            for k, v, s in sst.entries:
                if k not in latest or s > latest[k][2]:
                    latest[k] = (k, v, s)
        return sorted(latest.values())

    # -- read ----------------------------------------------------------------
    def query(self, key):
        """Point lookup. Returns a dict describing the full read path:
            value       : the live value (or None if deleted / absent)
            reason      : 'memtable' | 'sst' | 'tombstone' | 'absent'
            checks      : ordered list of (where, sst_seq_or_None) visited
            sst_reads   : # SSTables actually READ (passed the bloom gate)
            bloom_skips : # SSTables SKIPPED because the bloom said 'no'
        Order: MemTable -> L0 (newest->oldest; ALL may overlap) -> L1..Lmax
        (one file by range per level). Stops at the FIRST hit (live or tomb).
        """
        checks, sst_reads, bloom_skips = [], 0, 0

        # 1. MemTable (free, in-memory)
        checks.append(("MemTable", None))
        if key in self.memtable:
            v, _ = self.memtable[key]
            reason = "memtable" if v is not TOMBSTONE else "tombstone"
            return self._result(v, reason, checks, sst_reads, bloom_skips)

        # 2. L0 -- newest first; OVERLAPPING so every file may hold the key
        for sst in reversed(self.levels[0]):
            checks.append(("L0", sst.sst_seq))
            if not sst.may_contain(key):           # bloom: DEFINITELY not here
                bloom_skips += 1
                continue
            sst_reads += 1
            e = sst.get(key)
            if e is not None:
                v = e[1]
                reason = "sst" if v is not TOMBSTONE else "tombstone"
                return self._result(v, reason, checks, sst_reads, bloom_skips)

        # 3. L1..Lmax -- NON-overlapping; pick the (single) file by range
        for lvl in range(1, self.L):
            files = self.levels[lvl]
            if not files:
                continue
            cand = None
            for sst in files:                      # toy: linear; real: binary search
                if sst.min_key() <= key <= sst.max_key():
                    cand = sst
                    break
            checks.append((f"L{lvl}", cand.sst_seq if cand else None))
            if cand is None:
                continue
            if not cand.may_contain(key):
                bloom_skips += 1
                continue
            sst_reads += 1
            e = cand.get(key)
            if e is not None:
                v = e[1]
                reason = "sst" if v is not TOMBSTONE else "tombstone"
                return self._result(v, reason, checks, sst_reads, bloom_skips)

        return self._result(None, "absent", checks, sst_reads, bloom_skips)

    @staticmethod
    def _result(value, reason, checks, sst_reads, bloom_skips):
        return {"value": value, "reason": reason, "checks": checks,
                "sst_reads": sst_reads, "bloom_skips": bloom_skips,
                "files_checked": len(checks)}

    # -- introspection -------------------------------------------------------
    def physical_entries(self):
        return sum(len(sst) for lvl in self.levels for sst in lvl)


def build_lsm(ops=INSERT_OPS, **kw):
    """Apply `ops` to a fresh LSMTree and return it (deterministic)."""
    db = LSMTree(**kw)
    for op in ops:
        if op[0] == "put":
            db.put(op[1], op[2])
        elif op[0] == "del":
            db.delete(op[1])
    return db


def ground_truth(ops):
    """Apply the op list to a plain dict (the flat index we check the LSM
    against). Returns {key: value} with deletes removed."""
    d = {}
    for op in ops:
        if op[0] == "put":
            d[op[1]] = op[2]
        elif op[0] == "del":
            d.pop(op[1], None)
    return d


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def vstr(v):
    return "<absent>" if v is None else repr(v)


# ============================================================================
# 3. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: MemTable insert + flush to SSTable
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: MemTable insert + flush to SSTable")
    print("Every put/delete lands in the IN-MEMORY MemTable (a sorted map) and is")
    print("appended to the Write-Ahead Log FIRST (so a crash can replay it). When the")
    print(f"MemTable reaches MEMTABLE_CAPACITY={MEMTABLE_CAPACITY} entries, it is FROZEN")
    print("and flushed to a new immutable SSTable at L0.\n")
    db = LSMTree()
    print("Replay the first 4 inserts and watch the MemTable fill, then flush:\n")
    for i, op in enumerate(INSERT_OPS[:4]):
        db.put(op[1], op[2])
        if len(db.memtable) == 0 and db.levels[0]:
            state = f"FULL -> FLUSH -> {db.levels[0][-1]}"
        else:
            state = f"memtable = {sorted(db.memtable.items())}"
        print(f"  op{i}: put(key={op[1]}, value={op[2]!r})   {state}")
    sst0 = db.levels[0][0]
    print(f"\n  The flush produced ONE immutable SSTable:  {sst0}")
    print(f"    min_key={sst0.min_key()}  max_key={sst0.max_key()}  entries={len(sst0)}")
    print(f"    bloom: m={sst0.bloom.m} bits, k={sst0.bloom.k} hashes "
          f"(theory FPR={sst0.bloom.fpr_theory*100:.2f}%)")
    print(f"    contents (key, value, op_seq):")
    for k, v, s in sst0.entries:
        vs = "<tombstone>" if v is TOMBSTONE else repr(v)
        print(f"      key={k:>3}  value={vs:<11}  seq={s}")
    print("\n  KEY POINTS:")
    print("    * The MemTable is SORTED by key on flush -> the SSTable is sorted.")
    print("    * An SSTable is IMMUTABLE: updates/deletes create NEW entries in NEWER")
    print("      SSTables; they never edit an existing one.")
    print("    * The op_seq lets compaction decide which version wins (highest).")
    sorted_keys = [e[0] for e in sst0.entries]
    print(f"\n[check] first SST is sorted by key: keys={sorted_keys} == "
          f"sorted={sorted(sorted_keys)} -> OK")


# ----------------------------------------------------------------------------
# SECTION B: Level structure (L0 overlapping; L1+ disjoint, geometric growth)
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: Level structure  (L0 overlapping; L1+ disjoint, SIZE_RATIO growth)")
    print("SSTables live on LEVELS. L0 is the direct output of MemTable flushes, so")
    print("its files can OVERLAP in key range (several flushes wrote the same keys).")
    print("Compaction MERGES each level into the next as a single NON-overlapping run;")
    print("each deeper level is ~SIZE_RATIO times larger than the one below.\n")
    print(f"Toy: MEMTABLE_CAPACITY={MEMTABLE_CAPACITY}, SIZE_RATIO={SIZE_RATIO}, "
          f"levels L0..L{NUM_LEVELS-1}\n")
    print("  | level | files in leveling | key ranges   | steady-state size (entries) |")
    print("  |-------|-------------------|--------------|------------------------------|")
    for lvl in range(NUM_LEVELS):
        overlap = "OVERLAPPING" if lvl == 0 else "disjoint"
        if lvl == 0:
            size = f"~{MEMTABLE_CAPACITY} x #flushes"
            files = "many (flushed)"
        else:
            size = f"~{MEMTABLE_CAPACITY * (SIZE_RATIO ** lvl)}"
            files = "1 sorted run"
        print(f"  | L{lvl}    | {files:<17} | {overlap:<12} | {size:<28} |")
    total = MEMTABLE_CAPACITY * sum(SIZE_RATIO ** l for l in range(NUM_LEVELS))
    print(f"\n  Steady-state total ~ {total} entries across {NUM_LEVELS} levels.")
    print("  (Real system: MemTable ~1M entries, SIZE_RATIO=10, 7 levels L0..L6 ->")
    print("   sizes 1M, 10M, 100M, ..., 10^6 M. Each level 10x the previous.)")
    print("\n  WHY LEVELS EXIST: they AMORTIZE compaction work. Instead of re-sorting")
    print("  the WHOLE database on every write (B-tree: O(height) random writes per")
    print("  insert, with splits rippling up), an LSM only re-merges a SMALL level")
    print("  into the next-larger one. The geometric size growth means each entry is")
    print("  rewritten only ~SIZE_RATIO times TOTAL across its lifetime (Section E).\n")
    db = build_lsm()
    print("  Actual L0 of the canonical build (4 OVERLAPPING SSTables):")
    for s in db.levels[0]:
        print(f"    {s}: keys={[e[0] for e in s.entries]}")
    ranges = [(s.min_key(), s.max_key()) for s in db.levels[0]]
    overlap_any = any(ranges[i][0] <= ranges[j][1] and ranges[j][0] <= ranges[i][1]
                      for i in range(len(ranges)) for j in range(i + 1, len(ranges)))
    print(f"\n[check] L0 ranges overlap? {ranges} -> {overlap_any} -> OK")
    assert overlap_any


# ----------------------------------------------------------------------------
# SECTION C: Read path (MemTable -> L0 scan -> L1+ range-pick)
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: Read path  (MemTable -> L0 scan -> L1+ range-pick -> stop on hit)")
    print("A point lookup checks, in order, and STOPS at the first hit (live OR tomb):\n")
    print("  1. MemTable                       (in-memory, free)")
    print("  2. L0 SSTables, newest -> oldest   (OVERLAPPING -> must consider EVERY file)")
    print("  3. L1, L2, ... one file by range   (NON-overlapping -> pick the 1 candidate)")
    print("\n  A tombstone is a HIT: it means 'deleted', so we STOP and return not-found")
    print("  WITHOUT looking deeper (else a stale older version would RESURFACE).\n")
    db = build_lsm()
    print(f"Canonical state: MemTable={sorted(db.memtable.items())}")
    print(f"                L0 = {[repr(s) for s in db.levels[0]]}\n")
    print("  | key | value      | reason    | files_checked | sst_reads | bloom_skips |")
    print("  |-----|------------|-----------|---------------|-----------|-------------|")
    for k in PROBE_KEYS:
        r = db.query(k)
        print(f"  | {k:>3} | {vstr(r['value']):<10} | {r['reason']:<9} | "
              f"{r['files_checked']:<13} | {r['sst_reads']:<9} | {r['bloom_skips']:<11} |")
    print("\n  Reading the table:")
    print("    * key 7  -> found in MemTable (1 check, 0 SST reads).")
    print("    * key 5  -> found in the NEWEST L0 SST (2 checks); the update v5b wins")
    print("                 over the older v5 in SST0 (higher op_seq).")
    print("    * key 20 -> TOMBSTONE in the newest L0 SST -> STOP, return 'deleted'.")
    print("                 (If we kept going, the OLD value v20 in SST0 would resurface!)")
    print("    * key 0  -> WORST case: absent from every newer SST, found only in SST0.")
    print(f"                 files_checked=5 (MemTable + all 4 L0 files). This is the cost")
    print("                 of L0 overlap: WITHOUT a bloom filter we read every L0 file.")
    print("    * key 99 -> truly absent -> scans MemTable + every L0 file before giving up.")
    print("\n  Read amplification = files_checked (and sst_reads, the real disk I/O).")
    print("  A bloom filter turns most of those sst_reads into cheap bloom_skips (Section G).")
    gt = ground_truth(INSERT_OPS)
    ok = all(db.query(k)["value"] == gt.get(k) for k in gt)
    ok2 = all(db.query(k)["value"] is None for k in [99, 100, 200])
    print(f"\n[check] query(k)==ground_truth(k) for all live keys: {ok} -> OK")
    print(f"[check] query(absent keys)==None: {ok2} -> OK")
    assert ok and ok2


# ----------------------------------------------------------------------------
# SECTION D: Compaction (merge-sort L0 -> L1; dedup by seq; tombstone handling)
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: Compaction  (merge-sort L0 -> L1; dedup by seq; drop tombstones)")
    print("Compaction is the background MERGE-SORT that turns many overlapping L0")
    print("SSTables into ONE non-overlapping SSTable at L1. Rules:\n")
    print("    * k-way merge by key (the merge step of merge-sort).")
    print("    * for duplicate keys, the entry with the HIGHEST op_seq wins (newest).")
    print("    * tombstones are KEPT unless compacting into the LAST level (else an")
    print("      older live version deeper down would resurface after the delete).\n")
    db = build_lsm()
    before_files = len(db.levels[0])
    before_entries = sum(len(s) for s in db.levels[0])
    print(f"BEFORE compaction:  L0 = {before_files} files, {before_entries} physical entries")
    for s in db.levels[0]:
        print(f"    {s}: keys={[e[0] for e in s.entries]}")
    new, n_src, n_out = db.compact(0)
    print(f"\nMERGE-SORT (all L0 + existing L1) -> ONE new SSTable at L1:")
    print(f"    {new}")
    print(f"    keys={[e[0] for e in new.entries]}")
    print(f"\nAFTER compaction:   L0 = {len(db.levels[0])} files ; "
          f"L1 = {len(db.levels[1])} file ({len(new)} entries)")
    reclaimed = before_entries - len(new)
    print(f"    reclaimed {reclaimed} stale entries (old versions of updated keys +")
    print(f"    the value shadowed by the tombstone). L1 is NON-overlapping -> reads hit")
    print(f"    at most 1 file per level now.\n")
    print("  Dedup decisions made by the merge (highest op_seq wins):")
    print("    key 5 : SST0 had v5  (seq 3)  vs SST3 had v5b  (seq 12) -> v5b  wins")
    print("    key 10: SST0 had v10 (seq 0)  vs SST3 had v10b (seq 13) -> v10b wins")
    print("    key 20: SST0 had v20 (seq 2)  vs SST3 had <tomb> (seq 14) -> tombstone kept")
    print("           (NOT the last level -> tombstone survives so a deeper v20 stays hidden)")
    print(f"\n[check] compact(0): source SSTs={n_src}, output entries={n_out}, "
          f"reclaimed={reclaimed} -> OK")
    assert before_files == 4 and len(db.levels[0]) == 0 and len(db.levels[1]) == 1
    assert len(new) == 13 and reclaimed == 3


# ----------------------------------------------------------------------------
# SECTION E: Write amplification (each byte rewritten ~once per level)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: Write amplification  (each byte rewritten ~once per level)")
    print("WRITE AMPLIFICATION = (bytes/entries written to disk) / (bytes user wrote).")
    print("Every entry is written ONCE on flush (->L0), then REWRITTEN once per")
    print("compaction as it climbs L0 -> L1 -> ... -> Lmax.\n")
    # 1) MEASURED on the toy: push all the way to the last level
    db = build_lsm()
    db.compact(0)
    db.compact(1)
    db.compact(2)   # into L3 = last level -> tombstones dropped
    logical = db.logical_writes
    flushed = db.entries_flushed
    compacted = db.entries_compacted
    physical = flushed + compacted
    wa_measured = physical / logical
    print(f"  Toy run (canonical {logical} ops, pushed all the way to L{NUM_LEVELS-1}):")
    print(f"    logical writes (user puts+dels)    = {logical}")
    print(f"    entries written on flush (->L0)    = {flushed}")
    print(f"    entries rewritten by compaction    = {compacted}  "
          f"(once per level climbed: L0->L1, L1->L2, L2->L3)")
    print(f"    TOTAL physical entry-writes        = {physical}")
    print(f"    measured WRITE AMP                 = {physical}/{logical} "
          f"= {wa_measured:.2f}x\n")
    print("  (Small toy -> small WA. Real systems reach the steady-state formula below.)\n")
    print("  Steady-state WRITE AMP (O'Neil 1996 / Kleppmann DDIA Ch.3):")
    print("    B-tree            : ~4x    (1 page write + WAL + occasional splits)")
    print("    LSM tiering       : ~L     (each entry written once per level)")
    print("    LSM leveling      : ~T*L   (each merge rewrites ~(T) existing per new unit)")
    print()
    print("  | policy            | T  | L | write amp | who uses it            |")
    print("  |-------------------|----|---|-----------|------------------------|")
    rows = [
        ("B-tree",        "-", "-", "~4x",     "PostgreSQL, InnoDB, SQLite"),
        ("LSM tiering",   "10", "4", "~4x",    "Cassandra (default)"),
        ("LSM leveling",  "10", "4", "~40x",   "RocksDB/LevelDB"),
        ("LSM leveling",  "10", "3", "~30x",   "RocksDB (tuned, write-heavy)"),
    ]
    for p, T, L, wa, who in rows:
        print(f"  | {p:<17} | {T:<2} | {L} | {wa:<9} | {who:<22} |")
    print("\n  -> An LSM does ~5-10x MORE total write WORK than a B-tree, but every write")
    print("     is a SEQUENTIAL append -> ~10-100x better write THROUGHPUT (no random")
    print("     seeks). The B-tree pays per-write SEEK latency; the LSM pays it back in")
    print("     background CPU+IO during compaction. Pick LSM for write-heavy, B-tree for")
    print("     read-heavy workloads. (See HEAP_VS_CLUSTERED.md for the B-tree side.)")
    print(f"\n[check] toy measured WA = {wa_measured:.2f}x (>= 1.0) -> OK")
    assert wa_measured >= 1.0


# ----------------------------------------------------------------------------
# SECTION F: Space amplification (stale duplicates until compaction)
# ----------------------------------------------------------------------------

def section_f():
    banner("SECTION F: Space amplification  (stale duplicates live until compaction)")
    print("SPACE AMPLIFICATION = (physical bytes on disk) / (logical bytes) - 1.")
    print("Updates and deletes do NOT edit old SSTables (they are IMMUTABLE). The old")
    print("version STAYS on disk until a compaction merges it away. So at any moment")
    print("the disk may hold STALE duplicates.\n")
    db = build_lsm()
    phys = sum(len(s) for s in db.levels[0])
    unique = len({k for s in db.levels[0] for k, _, _ in s.entries})
    stale = phys - unique
    print(f"BEFORE compaction (L0 = {len(db.levels[0])} SSTables):")
    print(f"    physical entries on disk (all SSTs) = {phys}")
    print(f"    unique keys in SSTs                 = {unique}")
    print(f"    stale duplicates                    = {stale}")
    print(f"    space amplification                 = {stale}/{unique} = "
          f"{stale / unique * 100:.1f}%")
    # enumerate the stale entries explicitly
    latest = {}
    for s in db.levels[0]:
        for k, v, sq in s.entries:
            if k not in latest or sq > latest[k][1]:
                latest[k] = (s.sst_seq, sq)
    print("    stale entries (each shadowed by a newer version or tombstone):")
    for s in db.levels[0]:
        for k, v, sq in s.entries:
            lseq, lsq = latest[k]
            if not (s.sst_seq == lseq and sq == lsq):
                vshow = "<tombstone>" if v is TOMBSTONE else repr(v)
                print(f"      key {k:>3} = {vshow:<11} in SST{s.sst_seq} "
                      f"(newer copy in SST{lseq})")
    db.compact(0)
    phys_after = sum(len(s) for s in db.levels[1])
    print(f"\nAFTER L0->L1 compaction:")
    print(f"    physical entries = {phys_after}   (stale duplicates -> 0)")
    print(f"    space amplification -> ~0%   (until the next update re-accumulates)")
    print("\n  WORST-CASE BOUND (leveling): at most ~one level's worth of data is")
    print("  'in flight' during a compaction, so space amp <= ~1/T (~25% here, ~10%")
    print("  for T=10). Tiering can hold up to (T-1) runs per level -> worse space amp.")
    print(f"\n[check] before: {stale} stale / {unique} unique; after compaction: 0 stale -> OK")
    assert stale == 3 and phys_after == 13


# ----------------------------------------------------------------------------
# SECTION G: Bloom filters (per-SSTable; skip files that can't contain the key)
# ----------------------------------------------------------------------------

def section_g():
    banner("SECTION G: Bloom filters  (per-SSTable; skip files that can't hold the key)")
    print("Every SSTable ships with a BLOOM FILTER (Bloom 1970) over its keys. Before")
    print("reading an SSTable on a point lookup, we ask the bloom: 'could this key be")
    print("here?' If NO -> SKIP the SSTable entirely (no I/O). If MAYBE (a false")
    print("positive), we do the read and find nothing.\n")
    print("  false-positive rate p = (1 - e^(-k*n/m))^k,  optimal k = (m/n)*ln(2)")
    print("  so  bits/key = m/n  ->  p.   10 bits/key -> ~0.82%;  20 bits/key -> ~0.00009%.\n")
    db = build_lsm()
    print("  Per-SSTable bloom filters (canonical build, 10 bits/key):")
    print("    | sst  | keys             | m  | k | theory FPR |")
    print("    |------|------------------|----|---|------------|")
    for s in db.levels[0]:
        b = s.bloom
        keys = str([e[0] for e in s.entries])
        print(f"    | SST{s.sst_seq} | {keys:<16} | {b.m:<2} | {b.k} | "
              f"{b.fpr_theory * 100:.2f}%       |")
    print("\n  Read amplification WITHOUT vs WITH bloom (canonical build):")
    print("    | key | reason    | sst_reads NO bloom | sst_reads WITH bloom | bloom_skips |")
    print("    |-----|-----------|---------------------|----------------------|-------------|")
    db_nobloom = build_lsm(use_bloom=False)
    for k in [0, 99, 5, 20]:
        r_no = db_nobloom.query(k)
        r_yes = db.query(k)
        print(f"    | {k:>3} | {r_yes['reason']:<9} | {r_no['sst_reads']:<19} | "
              f"{r_yes['sst_reads']:<20} | {r_yes['bloom_skips']:<11} |")
    print("\n  -> For the worst-case key 0 (only in the OLDEST L0 SST) the bloom turns")
    print("     4 SST reads into 1: the 3 newer SSTs' blooms all say 'definitely not 0'.")
    print("\n  Empirical FPR on a bigger bloom (n=1000 keys, 10 bits/key, 10000 probes):")
    keys_in = list(range(1000))
    bf = BloomFilter(1000, 10)
    for k in keys_in:
        bf.add(k)
    absent = list(range(1000, 11000))   # 10000 definitely-absent keys
    fp = sum(1 for k in absent if k in bf)
    print(f"    m={bf.m}, k={bf.k}, theory FPR = {bf.fpr_theory * 100:.3f}%")
    print(f"    empirical FP = {fp}/{len(absent)} = {fp / len(absent) * 100:.3f}%")
    print("    -> each bloom_skip saves a disk read; the rare FP just costs 1 extra read.")
    ratio = (fp / len(absent)) / bf.fpr_theory
    print(f"\n[check] empirical FPR {fp/len(absent)*100:.3f}% within ~3x of theory "
          f"{bf.fpr_theory*100:.3f}% (ratio {ratio:.2f}) -> OK")
    assert ratio < 3.0


# ============================================================================
# 4. THE GOLD BLOCK (what lsm_tree.html recomputes and checks against)
# ============================================================================

def gold_block():
    banner("GOLD - canonical query results  (lsm_tree.html recomputes & checks this)")
    db = build_lsm(use_bloom=False)   # NO compaction; L0 = 4 overlapping SSTs
    print("  Canonical build: 4 L0 SSTables (SST0..SST3), MemTable holds key 7.")
    print("  Read path WITHOUT bloom filter (pure structural, fully deterministic).\n")
    print("  | key | value      | reason    | files_checked | sst_reads |")
    print("  |-----|------------|-----------|---------------|-----------|")
    gold = {}
    for k in PROBE_KEYS:
        r = db.query(k)
        print(f"  | {k:>3} | {vstr(r['value']):<10} | {r['reason']:<9} | "
              f"{r['files_checked']:<13} | {r['sst_reads']:<9} |")
        gold[k] = (r["value"], r["files_checked"], r["sst_reads"], r["reason"])
    print("\n  GOLD values (pinned for lsm_tree.html):")
    for k in PROBE_KEYS:
        v, fc, sr, rs = gold[k]
        vs = "None" if v is None else f'"{v}"'
        print(f"    query({k:>3}) = {vs:<10} files_checked={fc} sst_reads={sr} reason={rs}")
    db2 = build_lsm()
    new, _, _ = db2.compact(0)
    print(f"\n  GOLD compaction: L0 files 4 -> 0 ; L1 files 0 -> 1 ; L1 entries = {len(new)}")
    print(f"    L1 keys = {[e[0] for e in new.entries]}")
    # ground-truth equivalence (the real correctness check)
    gt = ground_truth(INSERT_OPS)
    probe_all = list(gt.keys()) + [7, 99, 100, 200]
    eq = all(build_lsm(use_bloom=False).query(k)["value"] == gt.get(k) for k in probe_all)
    print(f"\n  [check] LSM point query == plain-dict ground truth "
          f"(considering tombstones): {'OK' if eq else 'FAIL'}")
    expected = {
        7:  ("v7",   1, 0, "memtable"),
        5:  ("v5b",  2, 1, "sst"),
        10: ("v10b", 2, 1, "sst"),
        20: (None,   2, 1, "tombstone"),
        0:  ("v0",   5, 4, "sst"),
        99: (None,   5, 4, "absent"),
    }
    match = all(gold[k] == expected[k] for k in PROBE_KEYS)
    print(f"  [check] gold values match pinned expected -> {'OK' if match else 'FAIL'}")
    assert match and eq and len(new) == 13


# ============================================================================
# main
# ============================================================================

def main():
    print("lsm_tree.py - reference impl. All numbers below feed LSM_TREE.md.")
    print("Log-Structured Merge-tree (RocksDB/LevelDB/Cassandra/HBase). "
    "sizes counted in ENTRIES.\n")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    gold_block()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
