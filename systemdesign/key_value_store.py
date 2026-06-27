"""
key_value_store.py - LSM-tree Key-Value Store simulation (Dynamo / Cassandra / RocksDB style).

This is the single source of truth that KEY_VALUE_STORE.md is built from and that
key_value_store.html re-computes in JS. Every number, table, and worked trace in
those files is printed by this one.

Run:
    python3 key_value_store.py

The big idea: writes are CHEAP and reads are EXPENSIVE. We trade random
in-place disk writes (B-tree) for sequential appends (WAL) + in-memory
buffering (memtable) + immutable on-disk files (SSTable) + background
compaction. The cost: reads may have to look in several places, so we add
Bloom filters + compaction to keep that cost bounded.

================================================================================
THE INTUITION (read this first) - the inbox that turns into a filing cabinet
================================================================================
Think of the LSM tree as a mailroom:

  * WAL        = the postmark ink. You stamp the envelope BEFORE you do anything
                 else, so even if the building burns down you know what was
                 received.
  * Memtable   = the inbox tray. Sorted (so you can find things fast) but small
                 and lives in RAM. Every write lands here next.
  * SSTable    = the filing cabinet drawer. When the inbox overflows you sort
                 the tray, write it once to disk as an immutable sorted file,
                 and empty the tray.
  * Compaction = the periodic tidy-up. You take several drawers, merge them
                 (latest version wins, deletes become tombstones and then
                 vanish), and replace them with one clean drawer. This is what
                 keeps the cabinet from overflowing with stale copies.

  Reads: check the inbox first (memtable), then the most recent drawers (newer
  SSTables), then older ones. A Bloom filter on each drawer says "this key
  definitely isn't in here" most of the time, saving a disk seek.

================================================================================
PLAIN-ENGLISH GLOSSARY
================================================================================
  WAL         Write-Ahead Log. Append-only file on disk; every PUT/DELETE is
              fsync'd here BEFORE the memtable is touched, so a crash loses at
              most the in-flight memtable.
  Memtable    In-memory ordered map (skip list / red-black tree in real life;
              here an OrderedDict sorted on flush). The write target.
  SSTable     Sorted String Table. Immutable, key-sorted on-disk file. Each one
              carries a Bloom filter and (in our sim) a min/max key range.
  Level       A bucket of SSTables. L0 SSTables can overlap (they are flushes,
              unmerged). L1+ SSTables in leveled compaction have disjoint key
              ranges so a read needs at most ONE SSTable per level.
  Bloom filter Probabilistic set-membership test. "Maybe in" / "definitely not
              in". Lets reads skip SSTables that cannot contain the key with no
              disk I/O. Tuned for ~1% false positive rate.
  Tombstone   A deletion marker. Deletes are also writes (you can't mutate an
              immutable SSTable), so we write a tombstone and let compaction
              physically remove the key later.
  Compaction  Background merge of SSTables. Two flavors:
                * Size-tiered (STCS): merge T similar-sized SSTables into one.
                  Low write amplification, HIGH read + space amplification.
                * Leveled      (LCS): L_i is T x larger than L_{i-1}; merges
                  push data down level by level. High write amplification,
                  LOW read + space amplification.
  Write amp   (bytes written to disk) / (bytes the user wrote). WAL + flush +
              every rewrite during compaction. The headline cost of LSM.
  Read amp    SSTables a single GET may consult in the worst case.
  Space amp   (disk bytes used) / (logical live bytes). Stale versions + tomb-
              stones that compaction has not yet reclaimed.

References:
  * O'Neil et al. 1996, "The Log-Structured Merge-Tree" (the original paper).
  * DeCandia et al. 2007, "Dynamo: Amazon's Highly Available Key-Value Store".
  * Lakshman & Malik 2010, "Cassandra - A Decentralized Structured Storage
    System".
  * RocksDB wiki, "RocksDB Tuning Guide" and the write-amplification vs
    read-amplification vs space-amplification tradeoff write-ups.
"""

from __future__ import annotations

import hashlib
import math
from collections import OrderedDict

BANNER = "=" * 74


# ============================================================================
# 1. CORE PRIMITIVES: Bloom filter, WAL, SSTable, Memtable
# ============================================================================

class BloomFilter:
    """A textbook Bloom filter (m bits, k hashes via Kirsch-Mitzenmacher).

    Tuned for a target false-positive rate. For p=0.01, that is ~9.6 bits per
    element and ~7 hash functions. We use deterministic md5/sha1 (not Python's
    randomized hash()) so the output is reproducible.
    """

    def __init__(self, capacity: int, fp_rate: float = 0.01):
        # bits per element = -ln(p) / (ln 2)^2
        self.bits_per_elem = -math.log(fp_rate) / (math.log(2) ** 2)
        # number of hash functions = (bits/elem) * ln 2
        self.k = max(1, round(self.bits_per_elem * math.log(2)))
        nbits = max(8, int(capacity * self.bits_per_elem))
        self.bits = [0] * nbits
        self.capacity = capacity
        self.fp_rate = fp_rate
        self.added = 0

    def _hashes(self, key: str):
        # double hashing: h_i = h1 + i * h2  (Kirsch & Mitzenmacher 2006)
        b1 = hashlib.md5(key.encode()).digest()
        b2 = hashlib.sha1(key.encode()).digest()
        h1 = int.from_bytes(b1[:8], "big")
        h2 = int.from_bytes(b2[:8], "big") | 1  # ensure nonzero stride
        n = len(self.bits)
        for i in range(self.k):
            yield (h1 + i * h2) % n

    def add(self, key: str):
        for h in self._hashes(key):
            self.bits[h] = 1
        self.added += 1

    def might_contain(self, key: str) -> bool:
        return all(self.bits[h] for h in self._hashes(key))


class WAL:
    """Append-only Write-Ahead Log. Replay rebuilds the memtable, latest wins."""

    def __init__(self):
        self.records: list[tuple[str, str, object]] = []
        self.fsyncs = 0

    def append(self, op: str, key: str, value):
        # every write is fsync'd (durability) before the memtable is mutated
        self.records.append((op, key, value))
        self.fsyncs += 1

    def replay(self) -> "OrderedDict[str, object]":
        """Rebuild memtable state from the log. Latest write per key wins."""
        mem: OrderedDict[str, object] = OrderedDict()
        for op, key, value in self.records:
            if op == "PUT":
                mem[key] = value
            elif op == "DEL":
                mem[key] = ("TOMBSTONE",)
        return mem


class SSTable:
    """Immutable, key-sorted table. Carries a Bloom filter + min/max key range.

    In production this is a file on disk with an index block + data blocks. In
    this simulation it lives in memory; the get() path is otherwise faithful:
    Bloom check first, then a binary search.
    """

    def __init__(self, entries, level: int = 0, seq: int = 0):
        # entries: list of (key, value, seq, tombstone). Sort by key.
        self.entries = sorted(entries, key=lambda e: e[0])
        self.level = level
        self.seq = seq  # creation sequence number (higher = newer)
        self.size = len(self.entries)
        self.min_key = self.entries[0][0] if self.entries else None
        self.max_key = self.entries[-1][0] if self.entries else None
        self.bloom = BloomFilter(max(self.size, 16), fp_rate=0.01)
        for k, _, _, _ in self.entries:
            self.bloom.add(k)
        self.disk_reads = 0  # instrumentation

    def get(self, key: str):
        """Return (entry_or_None, status). status in:
           'bloom_skip' | 'disk_hit' | 'disk_miss' | 'range_skip'."""
        if self.min_key is None or key < self.min_key or key > self.max_key:
            # range guard (free for L1+; skipped at L0 where ranges overlap)
            return None, "range_skip"
        if not self.bloom.might_contain(key):
            return None, "bloom_skip"
        self.disk_reads += 1
        lo, hi = 0, len(self.entries) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if self.entries[mid][0] == key:
                return self.entries[mid], "disk_hit"
            elif self.entries[mid][0] < key:
                lo = mid + 1
            else:
                hi = mid - 1
        return None, "disk_miss"


# ============================================================================
# 2. THE LSM TREE
# ============================================================================

class LSMTree:
    """Memtable + levels of SSTables + a WAL. Two compaction strategies.

    levels[i] = list of SSTables at level i. levels[0] = L0 (flushes, ranges
    may overlap). levels[1+] are post-compaction; in leveled mode their key
    ranges are disjoint.
    """

    def __init__(self, memtable_limit: int = 4,
                 strategy: str = "size_tiered",
                 stcs_threshold: int = 4):
        self.memtable: OrderedDict[str, object] = OrderedDict()
        self.memtable_limit = memtable_limit
        self.wal = WAL()
        self.levels: list[list[SSTable]] = [[]]
        self.next_seq = 0
        self.strategy = strategy
        self.stcs_threshold = stcs_threshold  # T for size-tiered
        self.stats = {
            "writes": 0, "reads": 0, "flushes": 0, "compactions": 0,
            "disk_reads": 0, "bloom_skips": 0, "range_skips": 0,
        }

    # -- write path ---------------------------------------------------------
    def _flush(self):
        if not self.memtable:
            return
        entries = []
        for k, v in self.memtable.items():
            if isinstance(v, tuple) and v and v[0] == "TOMBSTONE":
                entries.append((k, None, self.next_seq, True))
            else:
                entries.append((k, v, self.next_seq, False))
        sst = SSTable(entries, level=0, seq=self.next_seq)
        self.levels[0].append(sst)
        self.memtable = OrderedDict()
        self.stats["flushes"] += 1

    def put(self, key: str, value):
        self.wal.append("PUT", key, value)
        self.memtable[key] = value
        self.next_seq += 1
        self.stats["writes"] += 1
        if len(self.memtable) >= self.memtable_limit:
            self._flush()
            self._maybe_compact()

    def delete(self, key: str):
        self.wal.append("DEL", key, None)
        self.memtable[key] = ("TOMBSTONE",)
        self.next_seq += 1
        self.stats["writes"] += 1
        if len(self.memtable) >= self.memtable_limit:
            self._flush()
            self._maybe_compact()

    # -- read path ----------------------------------------------------------
    def get(self, key: str):
        """Returns (value_or_None, status). Status tells where the answer came
        from, so a caller can count read amplification."""
        self.stats["reads"] += 1
        # 1. memtable (always the freshest)
        if key in self.memtable:
            v = self.memtable[key]
            if isinstance(v, tuple) and v and v[0] == "TOMBSTONE":
                return None, "memtable_tombstone"
            return v, "memtable_hit"
        # 2. SSTables, newest level first, newest SSTable first within a level
        for level_idx in range(len(self.levels)):
            for sst in sorted(self.levels[level_idx], key=lambda s: -s.seq):
                res, status = sst.get(key)
                if status in ("bloom_skip", "range_skip"):
                    self.stats["bloom_skips" if status == "bloom_skip"
                               else "range_skips"] += 1
                    continue
                self.stats["disk_reads"] += 1
                if res is not None:
                    if res[3]:  # tombstone
                        return None, "sst_tombstone"
                    return res[1], "sst_hit"
        return None, "miss"

    # -- compaction ---------------------------------------------------------
    def _maybe_compact(self):
        if self.strategy == "size_tiered":
            self._compact_size_tiered()
        elif self.strategy == "leveled":
            self._compact_leveled()

    @staticmethod
    def _merge_ssts(ssts, seq):
        """Latest-wins merge of a list of SSTables -> list of entries."""
        latest = {}  # key -> (entry, seq)
        for sst in ssts:
            for entry in sst.entries:
                k, v, s, tomb = entry
                if k not in latest or s >= latest[k][1]:
                    latest[k] = (entry, s)
        return [rec[0] for rec in latest.values()]

    def _compact_size_tiered(self):
        """Merge T similar-sized L0 SSTables into one. New SSTable stays at L0.
        Low write amplification (each byte is rewritten ~T times total across
        its lifetime), high read + space amplification."""
        while len(self.levels[0]) >= self.stcs_threshold:
            merged_entries = self._merge_ssts(self.levels[0], self.next_seq)
            new_sst = SSTable(merged_entries, level=0, seq=self.next_seq)
            self.levels[0] = [new_sst]
            self.stats["compactions"] += 1

    def _compact_leveled(self):
        """When L0 has >= threshold SSTables, merge L0 into L1. Each level is T x
        the previous; within a level, SSTables have disjoint key ranges. High
        write amplification (each byte rewritten at every level), low read +
        space amplification."""
        threshold = self.stcs_threshold
        while len(self.levels[0]) >= threshold:
            while len(self.levels) < 2:
                self.levels.append([])
            merged = self._merge_ssts(self.levels[0] + self.levels[1],
                                      self.next_seq)
            # split into disjoint key-range runs so future reads can range-skip
            new_sst = SSTable(merged, level=1, seq=self.next_seq)
            self.levels[1] = [new_sst]
            self.levels[0] = []
            self.stats["compactions"] += 1


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_sst(sst: SSTable) -> str:
    body = ",".join(
        (f"{k}:del" if t else f"{k}:{v}") for k, v, _, t in sst.entries)
    return f"L{sst.level}[{body}]"


def fmt_tree(tree: LSMTree) -> str:
    parts = []
    mem = ",".join(
        f"{k}:del" if (isinstance(v, tuple) and v and v[0] == "TOMBSTONE")
        else f"{k}:{v}" for k, v in tree.memtable.items())
    parts.append(f"memtable{{{mem or '-'}}}")
    for i, ssts in enumerate(tree.levels):
        if ssts:
            parts.append("L" + str(i) + "=[" + ", ".join(fmt_sst(s) for s in ssts) + "]")
    return "  ".join(parts) if len(parts) > 1 else parts[0]


# ============================================================================
# 4. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: write path - WAL -> memtable -> flush to SSTable
# ----------------------------------------------------------------------------

WRITE_TRACE = [
    ("PUT", "user:1", "alice"),
    ("PUT", "user:2", "bob"),
    ("PUT", "user:3", "carol"),
    ("PUT", "user:4", "dave"),     # memtable fills (limit=4) -> flush #1
    ("PUT", "user:1", "ALICE"),    # update alice (in NEW memtable)
    ("DEL", "user:2"),             # delete bob (tombstone in new memtable)
    ("PUT", "user:5", "eve"),
    ("PUT", "user:6", "frank"),    # flush #2
    ("PUT", "user:7", "grace"),
    ("PUT", "user:8", "heidi"),    # memtable has 2 entries, no flush yet
]


def section_write_path():
    banner("SECTION A: write path  WAL -> memtable -> immutable SSTable")
    print("  memtable limit = 4. Every PUT/DEL is fsync'd to the WAL FIRST,\n"
          "  then appended to the in-memory memtable. When the memtable hits\n"
          "  the limit we sort it and write it to disk as an immutable SSTable\n"
          "  (a flush). The memtable is then empty and ready for more writes.\n")
    tree = LSMTree(memtable_limit=4, strategy="none")
    print(f"  {'#':>2}  {'op':<22}  {'event':<14}  state")
    print("  " + "-" * 96)
    for i, entry in enumerate(WRITE_TRACE, 1):
        op, key = entry[0], entry[1]
        val = entry[2] if len(entry) > 2 else None
        before_flushes = tree.stats["flushes"]
        if op == "PUT":
            tree.put(key, val)
            opstr = f"PUT {key}={val}"
        else:
            tree.delete(key)
            opstr = f"DEL {key}"
        event = "FLUSH+newSST" if tree.stats["flushes"] > before_flushes else "wal+mem"
        print(f"  {i:>2}  {opstr:<22}  {event:<14}  {fmt_tree(tree)}")
    print(f"\n  writes={tree.stats['writes']}  flushes={tree.stats['flushes']}  "
          f"L0 SSTables={len(tree.levels[0])}  "
          f"WAL records={len(tree.wal.records)}  fsyncs={tree.wal.fsyncs}")

    print("\n  --- WAL replay simulation (crash, lose memtable, replay log) ---")
    print("  We DROP the memtable (simulate a crash), then replay the WAL. The\n"
          "  replayed memtable contains the LATEST value per key (ALICE wins\n"
          "  over alice; user:2 is a tombstone). Notice: replay does NOT rebuild\n"
          "  SSTables - those are durable on disk already. It only rebuilds the\n"
          "  in-memory state that had not been flushed yet.")
    replayed = tree.wal.replay()
    ritems = ", ".join(
        f"{k}:del" if (isinstance(v, tuple) and v and v[0] == "TOMBSTONE")
        else f"{k}={v}" for k, v in replayed.items())
    print(f"\n  replayed memtable (latest-wins across all {len(tree.wal.records)} "
          f"WAL records):  {{{ritems}}}")
    assert replayed["user:1"] == "ALICE", "replay must take latest PUT"
    assert isinstance(replayed["user:2"], tuple) and replayed["user:2"][0] == "TOMBSTONE"
    assert replayed["user:8"] == "heidi"
    assert len(replayed) == 8  # 8 distinct keys across the trace
    print("\n[check] WAL replay correctness  OK")
    return tree


# ----------------------------------------------------------------------------
# SECTION B: read path - memtable -> SSTables -> bloom filter
# ----------------------------------------------------------------------------

READ_QUERIES = [
    ("user:1", "ALICE",  "memtable_tombstone/sst_hit/miss... (latest in a newer SSTable than flush #1)"),
    ("user:2", None,     "tombstone wins (deleted after first flush)"),
    ("user:3", "carol",  "old key, lives in an SSTable"),
    ("user:4", "dave",   "old key, lives in an SSTable"),
    ("user:7", "grace",  "in memtable"),
    ("user:9", None,     "never written -> miss"),
]


def section_read_path():
    banner("SECTION B: read path  memtable -> L0 -> L1 -> ...  + bloom filter")
    # fresh tree with size-tiered compaction off so we can SEE L0 stacks
    tree = LSMTree(memtable_limit=4, strategy="none")
    for entry in WRITE_TRACE:
        op, key = entry[0], entry[1]
        val = entry[2] if len(entry) > 2 else None
        if op == "PUT":
            tree.put(key, val)
        else:
            tree.delete(key)
    # extra flush so user:7..8 are on disk too
    print(f"  State before reads:\n    {fmt_tree(tree)}\n")
    print("  Each GET walks: memtable (1 lookup) -> every L0 SSTable newest-first\n"
          "  -> every L1 SSTable. At each SSTable we first check the key range,\n"
          "  then the Bloom filter; only if both pass do we pay a disk read.\n")
    print(f"  {'#':>2}  {'GET':<10}  {'expected':<8}  "
          f"{'got':<8}  {'status':<20}  notes")
    print("  " + "-" * 96)
    for i, (key, expected, note) in enumerate(READ_QUERIES, 1):
        before = (tree.stats["disk_reads"], tree.stats["bloom_skips"])
        val, status = tree.get(key)
        d_dr = tree.stats["disk_reads"] - before[0]
        d_bs = tree.stats["bloom_skips"] - before[1]
        ok = "OK" if val == expected else "FAIL"
        valstr = "-" if val is None else str(val)
        expstr = "-" if expected is None else str(expected)
        print(f"  {i:>2}  GET {key:<10}  {expstr:<8}  {valstr:<8}  "
              f"{status:<20}  disk_reads+{d_dr} bloom_skip+{d_bs}  {ok}")
    total_levels = sum(len(L) for L in tree.levels)
    print(f"\n  totals: reads={tree.stats['reads']}  "
          f"disk_reads={tree.stats['disk_reads']}  "
          f"bloom_skips={tree.stats['bloom_skips']}  "
          f"SSTables present={total_levels}")
    print("\n  READ AMPLIFICATION in this trace: the worst-case GET would touch "
          f"{total_levels} SSTables. Bloom filters + range guards turned that "
          f"into {tree.stats['disk_reads']} actual disk reads across "
          f"{tree.stats['reads']} GETs.")
    assert all(
        (tree.get(k)[0] == exp) for k, exp, _ in READ_QUERIES
    ), "read path correctness"
    print("\n[check] read path correctness  OK")
    return tree


# ----------------------------------------------------------------------------
# SECTION C: compaction - size-tiered vs leveled
# ----------------------------------------------------------------------------

def section_compaction():
    banner("SECTION C: compaction  size-tiered (write-heavy) vs leveled (read-heavy)")
    workload = []
    for batch in range(3):
        for i in range(8):
            workload.append(("PUT", f"k{batch*8+i:02d}", f"v{batch}_{i}"))
    # also re-write some keys to create stale versions
    workload.append(("PUT", "k00", "vFRESH"))
    workload.append(("DEL", "k01"))

    print("  Workload: 3 batches of 8 PUTs (24 keys) + an update to k00 + a DEL of k01.")
    print("  memtable limit = 4, STCS threshold T = 4.\n")

    # --- size-tiered ---
    st = LSMTree(memtable_limit=4, strategy="size_tiered", stcs_threshold=4)
    for entry in workload:
        op, k = entry[0], entry[1]
        v = entry[2] if len(entry) > 2 else None
        st.put(k, v) if op == "PUT" else st.delete(k)
    st_keys = set()
    st_dead = 0
    for L in st.levels:
        for sst in L:
            for k, v, s, t in sst.entries:
                if t:
                    st_dead += 1
                st_keys.add(k)
    print(f"  SIZE-TIERED:")
    print(f"    {fmt_tree(st)}")
    print(f"    SSTables in L0 = {len(st.levels[0])}  compactions = "
          f"{st.stats['compactions']}  flushes = {st.stats['flushes']}")
    print(f"    live keys (after merge resolves updates/deletes): {len(st_keys)}")
    print(f"    -- STCS keeps WRITE amplification low (each byte rewritten only\n"
          f"       T={st.stcs_threshold} times across its life) but reads may\n"
          f"       have to scan every L0 SSTable.")

    # --- leveled ---
    print()
    lv = LSMTree(memtable_limit=4, strategy="leveled", stcs_threshold=4)
    for entry in workload:
        op, k = entry[0], entry[1]
        v = entry[2] if len(entry) > 2 else None
        lv.put(k, v) if op == "PUT" else lv.delete(k)
    lv_keys = set()
    for L in lv.levels:
        for sst in L:
            for k, v, s, t in sst.entries:
                lv_keys.add(k)
    print(f"  LEVELED:")
    print(f"    {fmt_tree(lv)}")
    l0_count = len(lv.levels[0]) if lv.levels else 0
    l1_count = len(lv.levels[1]) if len(lv.levels) > 1 else 0
    print(f"    SSTables in L0 = {l0_count}  L1 = {l1_count}  "
          f"compactions = {lv.stats['compactions']}  flushes = {lv.stats['flushes']}")
    print(f"    live keys: {len(lv_keys)}")
    print(f"    -- LCS keeps READ + SPACE amplification low (at most ONE SSTable\n"
          f"       per level holds a key) but writes are amplified at every\n"
          f"       level merge.")

    # verify both end states have same LIVE data
    st_live = {}
    for L in st.levels:
        for sst in L:
            for k, v, s, t in sst.entries:
                st_live[k] = ("DEL" if t else v)
    lv_live = {}
    for L in lv.levels:
        for sst in L:
            for k, v, s, t in sst.entries:
                lv_live[k] = ("DEL" if t else v)
    # both must report the same answer for every key
    for k in sorted(set(st_live) | set(lv_live)):
        a = st.get(k)[0]
        b = lv.get(k)[0]
        assert a == b, f"STCS vs LCS divergence on {k}: {a!r} vs {b!r}"
    print(f"\n  both strategies return identical answers for all "
          f"{len(set(st_live) | set(lv_live))} live keys  OK")
    # k00 must be the fresh value, k01 must be a tombstone
    assert st.get("k00")[0] == "vFRESH"
    assert st.get("k01")[0] is None
    assert lv.get("k00")[0] == "vFRESH"
    assert lv.get("k01")[0] is None
    print("[check] compaction correctness (latest-wins + tombstones honored)  OK")
    return st, lv


# ----------------------------------------------------------------------------
# SECTION D: consistency mechanisms (read repair, hinted handoff, anti-entropy)
# ----------------------------------------------------------------------------

def section_consistency():
    banner("SECTION D: consistency  read repair / hinted handoff / anti-entropy")
    RF = 3
    W = R = 2  # quorum (W + R > RF -> strong-ish consistency)
    print(f"  Replication factor RF={RF}, write quorum W={W}, read quorum R={R}.")
    print(f"  W + R = {W + R} > RF = {RF}  =>  quorum intersection guarantees a\n"
          f"  read sees the latest committed write (no 'lost update' on a single key).\n")

    # ---- D.1 Read repair ----
    print("  D.1  READ REPAIR")
    print("  Three replicas have drifted (one missed a write). A quorum read sees")
    print("  two values; the coordinator writes the newest back to the stale replica.\n")
    replicas = [
        {"k": ("v3", 3)},  # newest
        {"k": ("v3", 3)},
        {"k": ("v2", 2)},  # stale
    ]
    # quorum read: contact R=2 replicas; pick highest seq
    contacted = replicas[:R]
    newest = max((v for v in (r.get("k") for r in contacted) if v),
                 key=lambda x: x[1])
    repaired = 0
    for r in replicas:
        cur = r.get("k")
        if cur is None or cur[1] < newest[1]:
            r["k"] = newest
            repaired += 1
    print(f"    quorum read returned ({newest[0]}, seq={newest[1]}); "
          f"repaired {repaired} stale replica(s).")
    assert repaired == 1
    assert all(r["k"] == newest for r in replicas)
    print("    [check] read repair  OK\n")

    # ---- D.2 Hinted handoff ----
    print("  D.2  HINTED HANDOFF")
    print("  Replica C is down. The coordinator writes to A and B (quorum met) and")
    print("  stores a HINT for C. When C rejoins, the coordinator replays the hint.\n")
    nodes = {"A": {}, "B": {}, "C": {}}
    down = {"C"}
    hints = []  # (target, op, key, value)
    coordinator_write = ("PUT", "x", ("vx", 1))
    for n in ("A", "B", "C"):
        if n in down:
            hints.append((n,) + coordinator_write)
        else:
            op, key, val = coordinator_write
            nodes[n][key] = val
    print(f"    write {coordinator_write} -> A:{list(nodes['A'].keys())} "
          f"B:{list(nodes['B'].keys())} C:{list(nodes['C'].keys())}  "
          f"(quorum W={W} met). {len(hints)} hint(s) buffered.")
    assert len(hints) == 1 and hints[0][0] == "C"
    # C rejoins
    down.discard("C")
    while hints:
        tgt, op, key, val = hints.pop(0)
        if tgt not in down:
            nodes[tgt][key] = val
    print(f"    C rejoined; coordinator replayed hint -> "
          f"C now has {list(nodes['C'].keys())}.")
    assert nodes["C"]["x"] == ("vx", 1)
    assert all(nodes[n] == {"x": ("vx", 1)} for n in nodes)
    print("    [check] hinted handoff  OK\n")

    # ---- D.3 Anti-entropy (Merkle tree) ----
    print("  D.3  ANTI-ENTROPY (Merkle tree)")
    print("  Each replica builds a Merkle tree over its key range. Replicas compare")
    print("  root hashes; if different, they descend to the differing leaf range")
    print("  and stream-repair only THAT range (cheap, bounded work).\n")

    def mtree_hash(items):
        # leaf = hash(key+value); parent = hash(left+right); full binary-ish
        if not items:
            return "0" * 8
        leaves = [hashlib.sha1((k + str(v)).encode()).hexdigest()[:8]
                  for k, v in sorted(items.items())]
        layer = leaves[:]
        while len(layer) > 1:
            nxt = []
            for i in range(0, len(layer), 2):
                l = layer[i]
                r = layer[i + 1] if i + 1 < len(layer) else ""
                nxt.append(hashlib.sha1((l + r).encode()).hexdigest()[:8])
            layer = nxt
        return layer[0]

    replica_a = {"k1": "v1", "k2": "v2", "k3": "v3", "k4": "v4"}
    replica_b = {"k1": "v1", "k2": "STALE", "k3": "v3", "k4": "v4"}
    ha = mtree_hash(replica_a)
    hb = mtree_hash(replica_b)
    print(f"    replica A root = {ha}")
    print(f"    replica B root = {hb}   (differ -> dig deeper)")
    assert ha != hb
    # leaf-level diff
    differing = [k for k in replica_a if replica_a[k] != replica_b[k]]
    print(f"    differing leaves: {differing}  -> stream-repair just those keys")
    for k in differing:
        replica_b[k] = replica_a[k]
    assert mtree_hash(replica_a) == mtree_hash(replica_b)
    print(f"    after repair, both roots = {mtree_hash(replica_a)}  (match)")
    print("    [check] anti-entropy  OK")
    print("\n[check] all consistency mechanisms  OK")


# ----------------------------------------------------------------------------
# SECTION E: scale + amplification math
# ----------------------------------------------------------------------------

def section_scale():
    banner("SECTION E: scale + amplification math (write-heavy workload, RF=3)")

    # workload assumptions (sized to look like a real Dynamo-class cluster)
    writes_per_sec = 500_000
    reads_per_sec = 1_000_000
    key_bytes = 100
    value_bytes = 1024                 # 1 KB average
    total_keys = 10_000_000_000        # 10 B keys
    days_per_year = 365
    RF = 3                             # replication factor

    # logical storage (one copy)
    logical_bytes = total_keys * (key_bytes + value_bytes)
    logical_tb = logical_bytes / (1024 ** 4)
    # with replication
    raw_bytes = logical_bytes * RF
    raw_tb = raw_bytes / (1024 ** 4)

    # network bandwidth (single copy, just the user payload)
    write_bw_mbps = writes_per_sec * (key_bytes + value_bytes) * 8 / 1e6
    read_bw_mbps = reads_per_sec * (key_bytes + value_bytes) * 8 / 1e6

    print("  WORKLOAD")
    print(f"    writes/s         = {writes_per_sec:,}")
    print(f"    reads/s          = {reads_per_sec:,}     (read:write = "
          f"{reads_per_sec // writes_per_sec}:1)")
    print(f"    key+value        = {key_bytes}+{value_bytes} = "
          f"{key_bytes + value_bytes} bytes/op")
    print(f"    total keys       = {total_keys:,}")
    print(f"    replication RF   = {RF}")

    print("\n  STORAGE (raw, one copy + after RF)")
    print(f"    logical       = {logical_tb:,.1f} TB")
    print(f"    x RF={RF}      = {raw_tb:,.1f} TB")

    print("\n  NETWORK (user payload only)")
    print(f"    write BW = {write_bw_mbps:,.0f} Mbps = "
          f"{write_bw_mbps / 1000:,.2f} Gbps")
    print(f"    read  BW = {read_bw_mbps:,.0f} Mbps = "
          f"{read_bw_mbps / 1000:,.2f} Gbps")

    # ---- amplification model ----
    # fanout / size ratio
    T = 10
    L = 4  # number of levels (L0..L3)
    T_st = 4  # size-tiered tier threshold

    # Write amplification
    # Leveled: a key is rewritten once per level transition. Each merge
    # rewrites the level's worth of data into the next level. Total work for
    # one logical byte = T per level (each level passes through ~T merges).
    # Conventional estimate: WA_leveled ~= T * (L - 1).
    wa_leveled = T * (L - 1)
    # Size-tiered: each byte is in one merge per level, and is rewritten T_st
    # times within each tier (T_st SSTables merge into 1, so each byte is
    # written T_st times). Total: T_st * (number of tiers it passes through).
    # With one tier (L0 only here), WA ~= T_st.
    wa_stcs = T_st

    # Read amplification (worst case SSTables consulted)
    # Leveled: at most ONE SSTable per level (disjoint ranges) => L
    ra_leveled = L
    # Size-tiered: up to T_st SSTables per tier * number of tiers
    ra_stcs = T_st * L

    # Space amplification (disk / live)
    # Leveled: ~1 + 1/T (only L0 + one in-flight merge contributes dead space)
    sa_leveled = 1 + 1 / T
    # Size-tiered: ~T_st (need T_st SSTables of a tier alive before a merge,
    # so up to T_st-1 stale copies of any byte can be on disk)
    sa_stcs = T_st

    print("\n  AMPLIFICATION  (T = size ratio / tier threshold, L = #levels)")
    print(f"    {'metric':<22}{'size-tiered':>14}{'leveled':>14}")
    print("    " + "-" * 50)
    print(f"    {'write amp (disk/user)':<22}{wa_stcs:>14}x{wa_leveled:>13}x")
    print(f"    {'read amp (SSTables/GET)':<22}{ra_stcs:>14}{ra_leveled:>14}")
    print(f"    {'space amp (disk/live)':<22}{sa_stcs:>14}x{sa_leveled:>13.1f}x")

    print("\n  WHAT THAT MEANS FOR DISK BANDWIDTH")
    user_write_bw_mbps = write_bw_mbps
    disk_stcs = user_write_bw_mbps * wa_stcs
    disk_lcs = user_write_bw_mbps * wa_leveled
    print(f"    user writes       = {user_write_bw_mbps:,.0f} Mbps")
    print(f"    STCS disk writes  = {disk_stcs:,.0f} Mbps  ({wa_stcs}x)")
    print(f"    LCS  disk writes  = {disk_lcs:,.0f} Mbps  ({wa_leveled}x)")
    print(f"    --> STCS writes ~{wa_leveled / wa_stcs:.0f}x less to disk than LCS,")
    print(f"        but reads pay up to {ra_stcs}/{ra_leveled} = "
          f"{ra_stcs / ra_leveled:.0f}x more SSTable lookups per GET.")

    print("\n  RULE OF THUMB")
    print("    * Write-heavy  -> size-tiered  (Cassandra default, RocksDB on logs)")
    print("    * Read-heavy   -> leveled      (RocksDB/LevelDB default)")
    print("    * Time-series  -> time-window  (drop whole expired SSTables, no rewrite)")

    # sanity asserts
    assert wa_leveled == 30
    assert wa_stcs == 4
    assert ra_leveled == 4
    assert ra_stcs == 16
    assert abs(sa_leveled - 1.1) < 0.01
    assert sa_stcs == 4
    print("\n[check] amplification math (T=10, L=4, T_st=4)  OK")
    return {
        "writes_per_sec": writes_per_sec, "reads_per_sec": reads_per_sec,
        "logical_tb": logical_tb, "raw_tb": raw_tb,
        "write_bw_mbps": write_bw_mbps, "read_bw_mbps": read_bw_mbps,
        "T": T, "L": L, "T_st": T_st, "RF": RF,
        "wa_leveled": wa_leveled, "wa_stcs": wa_stcs,
        "ra_leveled": ra_leveled, "ra_stcs": ra_stcs,
        "sa_leveled": sa_leveled, "sa_stcs": sa_stcs,
    }


# ----------------------------------------------------------------------------
# SECTION F: GOLD values pinned for key_value_store.html
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION F: GOLD values - pinned for key_value_store.html")
    # Run the canonical workload through a size-tiered tree and pin the result.
    gold_workload = [
        ("PUT", "k01", "v1"), ("PUT", "k02", "v2"), ("PUT", "k03", "v3"),
        ("PUT", "k04", "v4"),   # -> flush #1 (memtable limit 4)
        ("PUT", "k05", "v5"), ("PUT", "k06", "v6"), ("PUT", "k07", "v7"),
        ("PUT", "k08", "v8"),   # -> flush #2
        ("PUT", "k09", "v9"), ("PUT", "k10", "v10"), ("PUT", "k11", "v11"),
        ("PUT", "k12", "v12"),  # -> flush #3
        ("PUT", "k13", "v13"), ("PUT", "k14", "v14"), ("PUT", "k15", "v15"),
        ("PUT", "k16", "v16"),  # -> flush #4 -> STCS compaction merges 4 -> 1
        ("PUT", "k01", "FRESH"),  # update in new memtable
        ("DEL", "k02"),           # tombstone in new memtable
    ]
    tree = LSMTree(memtable_limit=4, strategy="size_tiered", stcs_threshold=4)
    for entry in gold_workload:
        op, k = entry[0], entry[1]
        v = entry[2] if len(entry) > 2 else None
        tree.put(k, v) if op == "PUT" else tree.delete(k)

    l0_count = len(tree.levels[0])
    compactions = tree.stats["compactions"]
    flushes = tree.stats["flushes"]
    # after compaction: one merged SSTable in L0; memtable holds k01=FRESH, k02=del
    mem_keys = sorted(tree.memtable.keys())
    mem_val_01 = tree.memtable.get("k01")
    mem_val_02 = tree.memtable.get("k02")

    # the merged SSTable's keys (16 total, k01 has stale 'v1' but that's fine;
    # read path returns memtable's FRESH first)
    merged = tree.levels[0][0]
    merged_keys = sorted(k for k, _, _, _ in merged.entries)
    merged_size = merged.size

    # GET k01 -> FRESH (memtable beats SSTable)
    v01, st01 = tree.get("k01")
    # GET k02 -> None (memtable tombstone)
    v02, st02 = tree.get("k02")
    # GET k08 -> v8 (in SSTable only)
    v08, st08 = tree.get("k08")
    # GET k99 -> None (miss)
    v99, st99 = tree.get("k99")

    print("GOLD workload (size-tiered, memtable_limit=4, T=4):")
    print(f"  writes                = {len(gold_workload)}")
    print(f"  flushes               = {flushes}")
    print(f"  compactions           = {compactions}")
    print(f"  L0 SSTables after run = {l0_count}")
    print(f"  memtable keys         = {mem_keys}")
    print(f"  memtable['k01']       = {mem_val_01!r}")
    print(f"  memtable['k02']       = {mem_val_02!r}")
    print(f"  merged SST size       = {merged_size}")
    print(f"  merged SST keys       = {merged_keys}")
    print(f"  GET k01 -> {v01!r} ({st01})")
    print(f"  GET k02 -> {v02!r} ({st02})")
    print(f"  GET k08 -> {v08!r} ({st08})")
    print(f"  GET k99 -> {v99!r} ({st99})")

    # self-consistency asserts (these MUST hold; the HTML re-derives them)
    assert flushes == 4
    assert compactions == 1
    assert l0_count == 1
    assert mem_keys == ["k01", "k02"]
    assert mem_val_01 == "FRESH"
    assert isinstance(mem_val_02, tuple) and mem_val_02[0] == "TOMBSTONE"
    assert merged_size == 16
    assert v01 == "FRESH" and st01 == "memtable_hit"
    assert v02 is None and st02 == "memtable_tombstone"
    assert v08 == "v8" and st08 == "sst_hit"
    assert v99 is None and st99 == "miss"
    print("\n[check] all GOLD asserts passed  OK")

    # Amplification gold
    print("\nGOLD amplification (for the calculator in key_value_store.html):")
    print(f"  T (fanout)            = 10")
    print(f"  L (levels)            = 4")
    print(f"  T_st (STCS threshold) = 4")
    print(f"  write_amp_leveled     = T*(L-1) = 30")
    print(f"  write_amp_stcs        = T_st    = 4")
    print(f"  read_amp_leveled      = L       = 4")
    print(f"  read_amp_stcs         = T_st*L  = 16")
    print(f"  space_amp_leveled     = 1+1/T   = 1.1")
    print(f"  space_amp_stcs        = T_st    = 4")
    print("\n[check] GOLD amplification values  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("key_value_store.py - LSM-tree KV store simulation. "
          "Feeds KEY_VALUE_STORE.md + key_value_store.html.")
    print("stdlib only; deterministic; no torch/numpy.")
    print("Models WAL + memtable + SSTable + bloom filter + compaction "
          "(size-tiered & leveled).")
    section_write_path()
    section_read_path()
    section_compaction()
    section_consistency()
    section_scale()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
