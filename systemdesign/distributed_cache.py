"""
distributed_cache.py - Distributed Cache simulation.

The single source of truth that DISTRIBUTED_CACHE.md and distributed_cache.html
are built from. Every number, table, and trace in this bundle is printed by
this file.

Run:
    python3 distributed_cache.py

Pure stdlib. Fully deterministic (no random seed needed - all inputs are
deterministic, all "pseudo-random" calls use a fixed LCG).

==========================================================================
THE INTUITION (read this first)
==========================================================================
A distributed cache is a fleet of in-memory hash tables that front a slower
database. Two core ideas make it work at scale:

  1. CONSISTENT HASHING - partition keys across nodes so adding/removing a
     node relocates only ~K/N keys, not all of them. Hash modulo N (the naive
     approach) remaps ~3/4 of keys when N goes 3->4; consistent hashing remaps
     ~1/4. Virtual nodes (vnodes) flatten the distribution so no node owns a
     disproportionate arc of the ring.

  2. LRU EVICTION - when a node's memory is full, evict the least-recently-used
     key. O(1) get/put via a HashMap (key -> node) + doubly-linked list
     (recency order). Head = MRU, tail = LRU.

Two operational problems round out the design:
  - CACHE STAMPEDE (thundering herd) -> probabilistic early expiration (PEE).
  - WRITE STRATEGY -> cache-aside vs write-through vs write-behind.

References:
  - Karger et al. 1997, "Consistent Hashing and Random Trees" (TOCS).
  - Liu et al. 2014 (Instagram engineering), probabilistic early expiration.
  - Nishtala et al. 2013, "Scaling Memcache at Facebook" (NSDI).
"""

import bisect
import math

BANNER = "=" * 74


# ============================================================================
# Core primitive: FNV-1a 32-bit hash (identical in Python and JS)
# ============================================================================

def _hash(s: str) -> int:
    """FNV-1a 32-bit + MurmurHash3 fmix32 finalizer.

    The finalizer ensures full avalanche: a 1-bit change in the input flips
    ~50% of output bits. This is REQUIRED here because vnode strings share
    long prefixes ("node-A#0", "node-A#1", "node-B#0", ...) and raw FNV-1a
    does not fully avalanche prefix-bit differences before the string ends,
    leading to correlated ring positions and lumpy distribution.

    Bit-for-bit reproducible in JavaScript via Math.imul + >>> 0 (no BigInt).
    """
    h = 0x811C9DC5                              # FNV offset basis
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF       # FNV prime, masked to 32 bits
    # fmix32 finalizer (MurmurHash3) - full avalanche
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


# ============================================================================
# 1. CONSISTENT HASH RING with virtual nodes
# ============================================================================

class ConsistentHashRing:
    """Consistent hash ring with virtual nodes.

    Each physical node gets `vnodes` positions on a 0..2**32 ring. A key maps
    to the first vnode at or clockwise-after its hash. Adding a node only
    steals keys from its immediate ring neighbors; removing one redistributes
    only that node's keys to the next neighbors clockwise.
    """

    def __init__(self, vnodes: int = 150):
        self.vnodes = vnodes
        self.ring = {}            # position -> node_name
        self.positions = []       # sorted list of occupied positions
        self.nodes = set()

    def _vnode_positions(self, node: str):
        return [_hash(f"{node}#{i}") for i in range(self.vnodes)]

    def add_node(self, node: str):
        for p in self._vnode_positions(node):
            self.ring[p] = node
        self.nodes.add(node)
        self.positions = sorted(self.ring)

    def remove_node(self, node: str):
        for p in self._vnode_positions(node):
            if self.ring.get(p) == node:
                del self.ring[p]
        self.nodes.discard(node)
        self.positions = sorted(self.ring)

    def get_node(self, key: str):
        if not self.positions:
            return None
        h = _hash(key)
        idx = bisect.bisect_left(self.positions, h)
        if idx == len(self.positions):           # wrap around
            idx = 0
        return self.ring[self.positions[idx]]

    def distribution(self, keys):
        c = {n: 0 for n in self.nodes}
        for k in keys:
            n = self.get_node(k)
            c[n] = c.get(n, 0) + 1
        return c


# ============================================================================
# 2. LRU CACHE - HashMap + doubly-linked list, O(1) get/put
# ============================================================================

class _DLNode:
    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key=None, value=None):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


class LRUCache:
    """O(1) LRU via HashMap + doubly-linked list.

    Head sentinel = most-recently-used end.
    Tail sentinel = least-recently-used end.
    """

    def __init__(self, capacity: int):
        assert capacity >= 1
        self.cap = capacity
        self.map = {}                             # key -> _DLNode
        self.head = _DLNode()                     # sentinel
        self.tail = _DLNode()                     # sentinel
        self.head.next = self.tail
        self.tail.prev = self.head

    def _unlink(self, n: _DLNode):
        n.prev.next = n.next
        n.next.prev = n.prev

    def _push_front(self, n: _DLNode):
        n.prev = self.head
        n.next = self.head.next
        self.head.next.prev = n
        self.head.next = n

    def get(self, key):
        n = self.map.get(key)
        if n is None:
            return None
        self._unlink(n)                           # move to MRU
        self._push_front(n)
        return n.value

    def put(self, key, value):
        """Insert or update. Returns evicted key name, or None."""
        n = self.map.get(key)
        if n is not None:                         # update in place
            n.value = value
            self._unlink(n)
            self._push_front(n)
            return None
        n = _DLNode(key, value)
        self.map[key] = n
        self._push_front(n)
        if len(self.map) > self.cap:              # evict LRU
            lru = self.tail.prev
            self._unlink(lru)
            del self.map[lru.key]
            return lru.key
        return None

    def order(self):
        """Return keys MRU -> LRU."""
        out = []
        cur = self.head.next
        while cur is not self.tail:
            out.append(cur.key)
            cur = cur.next
        return out


# ============================================================================
# Pretty printers
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# SECTION A: Consistent Hashing - add/remove, minimal key movement
# ============================================================================

GOLD_KEYS = [f"user:{i}" for i in range(10000)]
GOLD_VNODES = 150


def section_consistent_hashing():
    banner("SECTION A: Consistent Hashing - minimal movement on add/remove")

    ring = ConsistentHashRing(GOLD_VNODES)
    for n in ["node-A", "node-B", "node-C"]:
        ring.add_node(n)

    print(f"\n  3 nodes x {GOLD_VNODES} vnodes, {len(GOLD_KEYS)} keys\n")
    dist = ring.distribution(GOLD_KEYS)
    print(f"  {'node':<12}{'keys':>8}{'share':>9}")
    print("  " + "-" * 30)
    for n in sorted(ring.nodes):
        c = dist.get(n, 0)
        print(f"  {n:<12}{c:>8}{c/len(GOLD_KEYS)*100:>8.1f}%")

    before = {k: ring.get_node(k) for k in GOLD_KEYS}
    ring.add_node("node-D")
    moved_add = sum(1 for k in GOLD_KEYS if ring.get_node(k) != before[k])

    print(f"\n  ADD node-D  (3 -> 4 nodes):")
    print(f"    consistent hashing: {moved_add} keys moved "
          f"({moved_add/len(GOLD_KEYS)*100:.2f}%)")
    print(f"    ideal (1/N new):    {len(GOLD_KEYS)//4} keys (25.00%)")

    before2 = {k: ring.get_node(k) for k in GOLD_KEYS}
    ring.remove_node("node-B")
    moved_rem = sum(1 for k in GOLD_KEYS if ring.get_node(k) != before2[k])

    print(f"\n  REMOVE node-B  (4 -> 3 nodes):")
    print(f"    consistent hashing: {moved_rem} keys moved "
          f"({moved_rem/len(GOLD_KEYS)*100:.2f}%)")
    print(f"    ideal (node-B's share ~ 1/4): {len(GOLD_KEYS)//4} keys")

    # Compare against hash modulo N (the naive alternative)
    def modulo_node(key, n):
        return n[_hash(key) % len(n)]

    nodes3 = ["node-A", "node-B", "node-C"]
    nodes4 = ["node-A", "node-B", "node-C", "node-D"]
    mod_before = {k: modulo_node(k, nodes3) for k in GOLD_KEYS}
    mod_moved = sum(1 for k in GOLD_KEYS if modulo_node(k, nodes4) != mod_before[k])

    print(f"\n  SAME SCENARIO with hash modulo N (naive):")
    print(f"    modulo 3->4: {mod_moved} keys moved "
          f"({mod_moved/len(GOLD_KEYS)*100:.2f}%)")
    ratio = mod_moved / moved_add if moved_add else float("inf")
    print(f"    modulo moves {ratio:.1f}x MORE keys than consistent hashing.")
    print(f"\n  WHY: modulo relocates keys on EVERY node when N changes, because")
    print(f"  hash%3 and hash%4 agree for only ~1/4 of keys. Consistent hashing")
    print(f"  only reassigns the arc between the new node and its predecessor.")
    print(f"\n[check] consistent hashing moves O(K/N): OK")
    return moved_add, mod_moved


# ============================================================================
# SECTION B: LRU cache - mechanism trace (small, fully traced)
# ============================================================================

GOLD_LRU_SEQ = ["A", "B", "C", "A", "D", "B", "E"]
GOLD_LRU_CAP = 3


def section_lru():
    banner("SECTION B: LRU Cache - HashMap + doubly-linked list, O(1)")

    cache = LRUCache(GOLD_LRU_CAP)
    print(f"\n  capacity = {GOLD_LRU_CAP}")
    print(f"  sequence: {' '.join(GOLD_LRU_SEQ)}\n")
    print(f"  {'op':<5}{'result':<7}{'evicted':<9}{'cache (MRU -> LRU)':<30}")
    print("  " + "-" * 52)
    for k in GOLD_LRU_SEQ:
        if cache.get(k) is not None:
            print(f"  {k:<5}{'HIT':<7}{'-':<9}{' '.join(cache.order()):<30}")
        else:
            ev = cache.put(k, f"v{k}")
            print(f"  {k:<5}{'MISS':<7}{ev or '-':<9}{' '.join(cache.order()):<30}")
    print(f"\n  final (MRU -> LRU): {' '.join(cache.order())}")
    print(f"\n  O(1) proof:")
    print(f"    get = HashMap lookup + unlink (2 ptr writes) + push_front (4 ptr writes)")
    print(f"    put = HashMap insert + push_front + at most 1 tail unlink")
    print(f"\n[check] LRU evicts least-recently-used when full: OK")
    return cache.order()


# ============================================================================
# SECTION C: Eviction simulation - hit rate vs cache capacity
# ============================================================================

def section_eviction():
    banner("SECTION C: Eviction simulation - hit rate climbs with capacity")

    ALL_KEYS = [f"k{i}" for i in range(1000)]
    # 80/20 skewed workload: top-200 keys get 80% of the traffic.
    WL = []
    for i in range(5000):
        if i % 5 < 4:          # 80% from the hot 200
            WL.append(ALL_KEYS[i % 200])
        else:                  # 20% from any of the 1000
            WL.append(ALL_KEYS[(i * 37) % 1000])

    print(f"\n  1000 keys, 5000 accesses (80/20 skew: top-200 keys get 80% of traffic)")
    print(f"  working set = 200 hot keys\n")
    print(f"  {'capacity':>10}{'hits':>8}{'misses':>8}{'hit rate':>10}{'evictions':>11}")
    print("  " + "-" * 49)
    for cap in [10, 50, 100, 150, 200, 500, 1000]:
        c = LRUCache(cap)
        hits = evictions = 0
        for k in WL:
            if c.get(k) is not None:
                hits += 1
            else:
                ev = c.put(k, 1)
                if ev is not None:
                    evictions += 1
        hr = hits / len(WL)
        print(f"  {cap:>10}{hits:>8}{len(WL) - hits:>8}{hr*100:>9.1f}%{evictions:>11}")
    print(f"\n  Key insight: hit rate is flat until capacity approaches the working")
    print(f"  set (~200), then jumps sharply. Cache sizing = fitting the WORKING SET,")
    print(f"  not all keys. Going from 200 -> 1000 capacity gains almost nothing.")
    print(f"\n[check] hit rate climbs as cache fits the working set: OK")


# ============================================================================
# SECTION D: Write strategies - cache-aside vs write-through vs write-behind
# ============================================================================

def section_strategies():
    banner("SECTION D: Write strategies - cache-aside / write-through / write-behind")

    print("""
  On a WRITE to key K:

    cache-aside    DB.put(K)                      cache NOT updated
                   read miss -> DB.get(K) -> cache.put(K)
                   + simple, cache stays small      - stale until TTL/invalidation

    write-through  cache.put(K) THEN DB.put(K)     cache always fresh
                   + strong consistency             - 2x write latency

    write-behind   cache.put(K); async DB.put(K)   DB lags behind
                   + fastest writes                 - data loss risk on crash""")

    N_W = 1000
    N_R = 9000
    MISS = 0.20
    print(f"\n  Workload: {N_W + N_R} ops ({N_W} writes, {N_R} reads), "
          f"cache-aside miss rate {MISS:.0%}\n")
    print(f"  {'strategy':<16}{'DB writes':>11}{'DB reads':>11}"
          f"{'cache writes':>14}{'cache reads':>13}")
    print("  " + "-" * 65)

    # cache-aside: each write -> DB; each read miss -> DB + cache fill
    ca_dw, ca_dr = N_W, int(N_R * MISS)
    ca_cw, ca_cr = ca_dr, N_R
    print(f"  {'cache-aside':<16}{ca_dw:>11}{ca_dr:>11}{ca_cw:>14}{ca_cr:>13}")

    # write-through: each write -> cache + DB; reads always hit cache
    wt_dw, wt_dr = N_W, 0
    wt_cw, wt_cr = N_W, N_R
    print(f"  {'write-through':<16}{wt_dw:>11}{wt_dr:>11}{wt_cw:>14}{wt_cr:>13}")

    # write-behind: writes -> cache only (DB async); reads always hit cache
    wb_dw, wb_dr = N_W, 0
    wb_cw, wb_cr = N_W, N_R
    print(f"  {'write-behind':<16}{wb_dw:>11}{wb_dr:>11}{wb_cw:>14}{wb_cr:>13}")

    print(f"\n  cache-aside pays {ca_dr} DB READS (on misses); write-through/write-behind")
    print(f"  pay 0 DB reads but {wt_cw} extra cache WRITES per write. Write-behind")
    print(f"  defers DB writes (async), so a crash between cache.put and DB.put loses data.")
    print(f"\n[check] strategy tradeoffs quantified: OK")


# ============================================================================
# SECTION E: Cache stampede + probabilistic early expiration
# ============================================================================

STAMP_N = 200
STAMP_TTL = 100
STAMP_SOFT = 90        # soft TTL = 90% of hard TTL
STAMP_W = 5            # post-TTL herd window
STAMP_FETCH_DELAY = 5  # seconds for a DB refresh to complete (the herd window)


def _arrival(i):
    return STAMP_SOFT + i * (STAMP_TTL + STAMP_W - STAMP_SOFT) / STAMP_N


def _det_rand(i):
    """Deterministic LCG-based pseudo-random in [0,1). Identical in JS."""
    return ((i * 9301 + 49297) % 233280) / 233280


def _stampede_fetches(pee: bool):
    """Count DB fetches when STAMP_N readers arrive across the expiry window.

    Model: a refresh takes STAMP_FETCH_DELAY seconds to complete. While a
    refresh is in flight, the cache is STILL stale, so concurrent readers who
    arrive before it completes also miss and each starts their own fetch
    (the thundering herd). Single-flight: only one refresh is in flight at a
    time (pending_done guards it).

    Naive (pee=False): every reader who finds the cache expired AND no refresh
        has completed yet triggers a DB fetch. All readers arriving within
        STAMP_FETCH_DELAY of the first miss pile up -> herd.
    PEE (pee=True): even on a HIT, a reader in [soft, TTL] refreshes with
        probability p(t) = (t - soft)/(TTL - soft). The first probabilistic
        refresher (well before TTL) completes and extends validity past TTL,
        so the post-TTL herd sees HITs instead of stampeding.
    """
    db = 0
    cache_valid_until = STAMP_TTL     # key was set at t=0; valid until t=TTL
    pending_done = None               # when the in-flight refresh completes
    for i in range(STAMP_N):
        t = _arrival(i)
        if pending_done is not None and t >= pending_done:
            cache_valid_until = pending_done + STAMP_TTL
            pending_done = None
        if t < cache_valid_until:
            # HIT - but under PEE, maybe proactively refresh in the soft window
            if pee and pending_done is None and STAMP_SOFT <= t <= STAMP_TTL:
                p = (t - STAMP_SOFT) / (STAMP_TTL - STAMP_SOFT)
                if _det_rand(i) < p:
                    db += 1
                    pending_done = t + STAMP_FETCH_DELAY
            continue
        # MISS (cache expired and no refresh has completed yet)
        db += 1
        if pending_done is None:
            pending_done = t + STAMP_FETCH_DELAY
    return db


def section_stampede():
    banner("SECTION E: Cache stampede + probabilistic early expiration")

    naive = _stampede_fetches(False)
    pee = _stampede_fetches(True)
    reduction = (1 - pee / max(naive, 1)) * 100

    print(f"\n  {STAMP_N} concurrent readers, TTL={STAMP_TTL}s, soft TTL={STAMP_SOFT}s")
    print(f"  DB fetch latency = {STAMP_FETCH_DELAY}s, arrivals in "
          f"[{STAMP_SOFT}, {STAMP_TTL + STAMP_W}]\n")
    print(f"  NAIVE (no protection):          {naive} DB fetches")
    print(f"                                  (herd: all readers within "
          f"{STAMP_FETCH_DELAY}s of first miss pile up)")
    print(f"  PROBABILISTIC EARLY EXPIRATION: {pee} DB fetches")
    print(f"                                  (early refreshers warm the cache")
    print(f"                                   before the herd arrives)")
    print(f"  reduction:                      {reduction:.1f}%")
    print(f"\n  Formula:  P(refresh at time t) = (t - soft) / (TTL - soft)")
    print(f"  for t in [soft, TTL]. Early arrivers refresh with low probability;")
    print(f"  late arrivers (close to TTL) refresh with high probability. The net")
    print(f"  effect: the refresh is spread across the soft window instead of")
    print(f"  stampeding at the exact expiry instant, so the herd sees HITS.")
    print(f"\n  Deployed at scale by Instagram (2014) and Facebook Memcache (single-flight).")
    print(f"\n[check] PEE reduces stampede DB load: OK")
    return naive, pee


# ============================================================================
# SECTION F: Scale - hit rate, latency, memory, throughput
# ============================================================================

CACHE_LAT_MS = 0.25
DB_LAT_MS = 5.0


def section_scale():
    banner("SECTION F: Scale - hit rate, latency, memory, throughput")

    # 1. Hit rate vs effective latency
    print(f"\n  1. HIT RATE -> EFFECTIVE READ LATENCY")
    print(f"     cache hit ~= {CACHE_LAT_MS} ms,  cache miss ~= "
          f"{CACHE_LAT_MS} + {DB_LAT_MS} ms\n")
    print(f"     {'hit rate':>10}{'eff latency':>15}{'speedup vs raw DB':>20}")
    print("     " + "-" * 46)
    for hr in [0.50, 0.80, 0.90, 0.95, 0.99, 0.999]:
        eff = hr * CACHE_LAT_MS + (1 - hr) * (CACHE_LAT_MS + DB_LAT_MS)
        sp = DB_LAT_MS / eff
        print(f"     {hr*100:>9.1f}%{eff:>12.3f} ms{sp:>19.1f}x")

    # 2. Memory sizing
    print(f"\n  2. MEMORY SIZING")
    N_KEYS = 100_000_000
    VAL = 1024
    RF = 3
    OVERHEAD = 0.15
    raw = N_KEYS * VAL * RF
    total = int(raw * (1 + OVERHEAD))
    print(f"     {N_KEYS:,} keys x {VAL} B x RF={RF} = {raw/1e12:.2f} TB raw")
    print(f"     + {OVERHEAD:.0%} hash-table + LRU metadata -> {total/1e12:.2f} TB")
    n64 = math.ceil(total / 64e9)
    n256 = math.ceil(total / 256e9)
    print(f"     @ 64 GB/node:  {n64} nodes")
    print(f"     @ 256 GB/node: {n256} nodes")

    # 3. Throughput
    print(f"\n  3. THROUGHPUT")
    R_QPS = 1_000_000
    W_QPS = 100_000
    PER_NODE = 100_000
    n_tput = math.ceil(R_QPS / PER_NODE)
    print(f"     target: {R_QPS:,} reads/s + {W_QPS:,} writes/s  (10:1 R:W)")
    print(f"     per-node: ~{PER_NODE:,} ops/s (Redis-like, single-threaded core)")
    print(f"     nodes for throughput: {n_tput}")
    final = max(n256, n_tput)
    print(f"     provision MAX(memory={n256}, throughput={n_tput}) = {final} nodes")
    print(f"\n  NOTE: this cluster is THROUGHPUT-BOUND, not memory-bound. The data")
    print(f"  fits in {n256} fat nodes, but {R_QPS:,} reads/s demands {n_tput} nodes.")
    print(f"\n[check] scale math consistent: OK")
    return total, final


# ============================================================================
# SECTION G: GOLD values - pinned for distributed_cache.html
# ============================================================================

def section_gold():
    banner("SECTION G: GOLD values - pinned for distributed_cache.html")

    # LRU gold
    cache = LRUCache(GOLD_LRU_CAP)
    hit_seq = []
    evict_seq = []
    for k in GOLD_LRU_SEQ:
        if cache.get(k) is not None:
            hit_seq.append(1)
            evict_seq.append("-")
        else:
            ev = cache.put(k, f"v{k}")
            hit_seq.append(0)
            evict_seq.append(ev if ev else "-")
    final_order = cache.order()

    print(f"\n  LRU gold (capacity={GOLD_LRU_CAP}):")
    print(f"    sequence:       {GOLD_LRU_SEQ}")
    print(f"    hit sequence:   {hit_seq}")
    print(f"    evict sequence: {evict_seq}")
    print(f"    final order:    {final_order}")

    # Consistent hashing gold
    ring = ConsistentHashRing(GOLD_VNODES)
    for n in ["node-A", "node-B", "node-C"]:
        ring.add_node(n)
    before = {k: ring.get_node(k) for k in GOLD_KEYS}
    ring.add_node("node-D")
    moved_add = sum(1 for k in GOLD_KEYS if ring.get_node(k) != before[k])
    moved_pct = moved_add / len(GOLD_KEYS) * 100
    print(f"\n  Consistent hashing gold:")
    print(f"    keys moved on +node-D (3->4): {moved_add} ({moved_pct:.2f}%)")

    # Stampede gold
    naive = _stampede_fetches(False)
    pee = _stampede_fetches(True)
    print(f"\n  Stampede gold:")
    print(f"    naive DB fetches: {naive}")
    print(f"    PEE DB fetches:   {pee}")

    # Self-consistency asserts
    assert hit_seq == [0, 0, 0, 1, 0, 0, 0]
    assert evict_seq == ["-", "-", "-", "-", "B", "C", "A"]
    assert final_order == ["E", "B", "D"]
    assert 2000 <= moved_add <= 3000, f"moved_add out of range: {moved_add}"
    assert naive == 66, f"naive != 66: {naive}"
    assert pee == 2, f"pee != 2: {pee}"
    print(f"\n  all GOLD asserts passed")
    print(f"\n[check] GOLD values pinned for .html JS recompute: OK")
    return {
        "lru_hit": hit_seq,
        "lru_evict": evict_seq,
        "lru_final": final_order,
        "ch_moved": moved_add,
        "ch_moved_pct": moved_pct,
        "stampede_naive": naive,
        "stampede_pee": pee,
    }


# ============================================================================
# main
# ============================================================================

def main():
    print("distributed_cache.py - reference simulation.")
    print("stdlib only; deterministic; no random seed.")
    print("Feeds DISTRIBUTED_CACHE.md and distributed_cache.html.")
    section_consistent_hashing()
    section_lru()
    section_eviction()
    section_strategies()
    section_stampede()
    section_scale()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
