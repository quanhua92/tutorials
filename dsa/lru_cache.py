"""
lru_cache.py - Reference implementation: LRU Cache (HashMap + Doubly Linked List).

This is the single source of truth that LRU_CACHE.md is built from. Every
number, table, and worked example in LRU_CACHE.md is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    python3 lru_cache.py

==========================================================================
THE INTUITION (read this first) - the desk and the card catalog
==========================================================================
You have a small DESK that holds at most C books (the cache, capacity C). You
also have a huge LIBRARY of every book (main memory / backing store). To work,
you pull a book onto the desk; when the desk is full and you need a new one, you
must put ONE back to make room. The question is: WHICH one?

LRU's answer: put back the book you have NOT TOUCHED for the longest time - the
*Least Recently Used*. The intuition is *temporal locality*: if you used a book
recently, you will probably use it again soon; if you have not touched it in a
long time, you probably will not need it soon either. So evicting the coldest
book keeps the hot ones on the desk and (we hope) maximizes future hits.

To make get/put O(1), we keep TWO data structures that point at each other:

  * a HASHMAP (the card catalog): key -> node. O(1) "is this book on the desk,
    and where?" lookup.
  * a DOUBLY LINKED LIST (the bookmark chain): nodes ordered most-recently-used
    (head) -> least-recently-used (tail). Touching a book moves its node to the
    head; when we must evict, we cut the node off the TAIL.

The DLL gives O(1) reorder (a doubly-linked node knows both neighbors, so
unlinking/relinking is a constant number of pointer writes) and the HashMap
gives O(1) find. Together: O(1) get and O(1) put, with O(C) memory.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  capacity C   : how many items the cache holds (the "desk" size). Fixed.
  hit          : requested key is already in the cache. O(1) + move to head.
  miss         : requested key is absent. Fetch + insert at head; maybe evict.
  node         : one entry {key, value, prev, next} in the doubly linked list.
  head         : the MOST-recently-used end. New/touched items go HERE.
  tail         : the LEAST-recently-used end. Evictions cut from HERE.
  sentinel     : a dummy head/tail node that never holds data. It removes ALL
                 the "is prev/next None?" special cases from the pointer code.
  HashMap      : dict key -> node. The O(1) lookup half.
  recency      : a node's position in the DLL encodes when it was last used.
                 Head = just now, tail = longest ago.
  evict        : remove the tail node (LRU victim) to make room on a miss.
  locality     : "recently used -> soon reused." The assumption LRU exploits.
                 Strong locality -> LRU hits a lot; no locality -> LRU ~= random.

==========================================================================
THE LINEAGE (where you meet LRU in the wild)
==========================================================================
  LRU  (Sedgewick 1970s; CLRS "linked-list implementation", problem 11-? ) : the
        classic page-replacement / cache-eviction policy. Basis of most
        production caches.
  Real uses:
    * Python functools.lru_cache   - per-process memoization. (Section F.)
    * Redis  maxmemory-policy=allkeys-lru  - evict LRU keys under memory cap.
    * Memcached  (-M not set)       - an LRU-ish eviction per slab class.
    * OS page cache / many CPU caches use approximate/pseudo-LRU (true LRU per
      access is too expensive in hardware; software uses true LRU).
  Cousins (Section E comparison):
    * FIFO  : evict the OLDEST INSERTED (ignores re-access). Cheaper, dumber.
    * LFU   : evict the LEAST FREQUENTLY used (counts hits). Great on stable
              hot sets; blind to shifting working sets (stale frequency).
    * Random: evict a random victim. Cheap, surprisingly competitive, no state.
    * Belady/OPT : evict the one used FARTHEST IN THE FUTURE. The theoretical
              optimum - unimplementable (needs the future) but the gold standard
              to benchmark against.

KEY FACTS (CLRS + standard OS texts, verified/asserted in code below):
    get(key) : O(1)  = dict lookup + O(1) DLL move-to-head (6 pointer writes).
    put(k,v) : O(1)  = dict set + O(1) DLL insert-at-head; maybe O(1) pop-tail.
    space    : O(C)  (C nodes + C dict entries + 2 sentinels).
    LRU vs FIFO  : identical under a pure cyclic scan; LRU wins under re-access
                   because FIFO ignores recency updates on a hit.
    LRU vs LFU   : LFU wins on a STABLE hot set; LRU wins when the WORKING SET
                   SHIFTS (LFU's frequency counts go stale).
    LRU vs Random: LRU wins roughly in proportion to locality strength; on
                   uniform-random access they converge (no locality to exploit).

Conventions: integer keys/values; capacity fixed at construction; cache state is
always printed MOST-recently-used -> LEAST-recently-used (head -> tail). All
"random" sequences use a fixed seed so output (and lru_cache.html) are
byte-identical across runs.
"""

from __future__ import annotations

import functools
import random
from collections import deque

BANNER = "=" * 72

# The access sequence used throughout Section D. Deterministic.
# capacity = 3, so the cache holds 3 items; the 4th distinct access evicts.
ACCESS_SEQ = [1, 2, 3, 4, 1, 2, 5, 1]
CAPACITY = 3


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (the code LRU_CACHE.md walks through)
# ============================================================================

class Node:
    """One entry in the recency doubly-linked list.

    prev/next are ALWAYS non-None for a live node, because the list is bounded
    by the two sentinels (LRUCache.head, LRUCache.tail). That is the whole
    reason sentinels exist: they kill every "if prev is None" edge case.
    """

    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key=0, value=0):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


class LRUCache:
    """O(1) get/put LRU cache = HashMap (dict) + doubly linked list.

    Layout:
        head <-> MRU node <-> ... <-> LRU node <-> tail
        head  = dummy, the MOST-recently-used side (new nodes inserted after it)
        tail  = dummy, the LEAST-recently-used side (evictions take node before it)
        map   = {key: node}, the O(1) lookup half.

    Both halves cross-reference: the map points to list nodes, and every node
    carries its key so the eviction path can delete the map entry in O(1).
    """

    def __init__(self, capacity: int):
        assert capacity > 0
        self.cap = capacity
        self.map: dict = {}                       # key -> Node  (the HashMap)
        self.head = Node()                        # sentinel (MRU side)
        self.tail = Node()                        # sentinel (LRU side)
        self.head.next = self.tail
        self.tail.prev = self.head
        self.evictions: list = []                 # log of evicted keys, in order

    # ---- DLL primitives: each is a fixed number of pointer writes = O(1) ----
    def _add_head(self, node: Node):
        """Insert `node` right after the head sentinel (it becomes MRU)."""
        node.prev = self.head
        node.next = self.head.next
        self.head.next.prev = node
        self.head.next = node

    def _remove(self, node: Node):
        """Unlink `node` from the list (does not touch the map)."""
        node.prev.next = node.next
        node.next.prev = node.prev

    def _move_to_head(self, node: Node):
        """Mark `node` most-recently-used: unlink, then re-insert at head."""
        self._remove(node)
        self._add_head(node)

    def _pop_tail(self) -> Node:
        """Remove and return the LRU node (the one just before the tail sentinel)."""
        lru = self.tail.prev
        self._remove(lru)
        return lru

    # ---- the two public O(1) operations ----
    def get(self, key):
        """Return value, or -1 on miss. Side effect: a hit moves key to MRU."""
        node = self.map.get(key)
        if node is None:
            return -1                             # miss: nothing to update
        self._move_to_head(node)                  # hit: refresh recency -> O(1)
        return node.value

    def put(self, key, value):
        """Insert or update (key, value). Returns the evicted key, or None.

        - key present : update value, move to head. No eviction.  (O(1))
        - key absent  : add at head; if over capacity, evict tail. (O(1))
        """
        node = self.map.get(key)
        if node is not None:                      # UPDATE path
            node.value = value
            self._move_to_head(node)
            return None
        # INSERT path
        node = Node(key, value)
        self.map[key] = node
        self._add_head(node)
        evicted = None
        if len(self.map) > self.cap:              # over capacity -> evict LRU
            lru = self._pop_tail()
            del self.map[lru.key]
            self.evictions.append(lru.key)
            evicted = lru.key
        return evicted

    def access(self, key):
        """Cache-reference semantics: hit -> refresh; miss -> insert (+evict).

        Returns (hit: bool, evicted: key | None). This is the operation the
        Section D trace and the Section E hit-rate comparison use, because it
        models "an access stream" (a CPU/cache or a Redis key workload) where a
        miss *brings the item in*. (Plain get() would leave misses out.)
        """
        if self.get(key) != -1:                   # hit (already moved to head)
            return (True, None)
        evicted = self.put(key, key)              # miss: bring it in
        return (False, evicted)

    def state(self):
        """Return keys MOST-recently-used -> LEAST-recently-used (head -> tail)."""
        out = []
        node = self.head.next
        while node is not self.tail:
            out.append(node.key)
            node = node.next
        return out

    def __len__(self):
        return len(self.map)


# ============================================================================
# 1b. THE RIVAL POLICIES (for Section E comparison). Same access() contract.
# ============================================================================

def simulate_lru(seq, cap):
    """LRU. Returns (hits, evictions_list). Reuses LRUCache.access."""
    c = LRUCache(cap)
    hits = 0
    for k in seq:
        hit, _ = c.access(k)
        if hit:
            hits += 1
    return hits, list(c.evictions)


def simulate_fifo(seq, cap):
    """FIFO: evict the oldest INSERTED. A hit does NOT change the order.

    Implemented with a deque (front = next victim) + a set for O(1) membership.
    This is the policy that ignores recency, so it cannot benefit from re-access.
    """
    q = deque()
    present = set()
    hits = 0
    evictions = []
    for k in seq:
        if k in present:
            hits += 1                             # hit: order unchanged
            continue
        if len(q) >= cap:
            victim = q.popleft()                  # oldest inserted
            present.discard(victim)
            evictions.append(victim)
        q.append(k)
        present.add(k)
    return hits, evictions


def simulate_lfu(seq, cap):
    """LFU: evict the least FREQUENTLY used; ties broken by oldest insertion.

    freq[k] = access count; order[k] = first-insertion timestamp. Victim =
    min(freq), and among those the earliest inserted. Great when the hot set is
    STABLE; degrades when the working set SHIFTS (old frequencies go stale).
    """
    freq = {}
    order = {}
    present = set()
    hits = 0
    evictions = []
    t = 0
    for k in seq:
        t += 1
        if k in present:
            freq[k] += 1                          # hit: bump frequency only
            hits += 1
            continue
        if len(present) >= cap:
            victim = min(present, key=lambda x: (freq[x], order[x]))
            present.discard(victim)
            del freq[victim]
            del order[victim]
            evictions.append(victim)
        present.add(k)
        freq[k] = 1
        order[k] = t
    return hits, evictions


def simulate_random(seq, cap, seed=0):
    """Random replacement: evict a uniformly random victim on a miss.

    Needs no recency/frequency state, so it costs nothing to maintain and (the
    surprising result) is often within a few percent of LRU when locality is
    weak. Fixed seed -> deterministic output for the gold check.
    """
    rng = random.Random(seed)
    items = []
    present = set()
    hits = 0
    evictions = []
    for k in seq:
        if k in present:
            hits += 1
            continue
        if len(items) >= cap:
            idx = rng.randrange(len(items))       # random victim
            victim = items.pop(idx)
            present.discard(victim)
            evictions.append(victim)
        items.append(k)
        present.add(k)
    return hits, evictions


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_state(keys):
    """Pretty-print a cache state (MRU -> LRU) as head -> ... -> tail."""
    if not keys:
        return "(empty)"
    return " <-> ".join(str(k) for k in keys)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the data structure - HashMap cross-referenced with a DLL
# ----------------------------------------------------------------------------
def section_structure():
    banner("SECTION A: the data structure - HashMap + Doubly Linked List")
    print("An LRU cache is TWO structures pointing at each other:\n")
    print("  (1) HashMap  map: { key -> node }       the O(1) lookup half")
    print("  (2) DLL      head <-> MRU ... LRU <-> tail   the O(1) recency half")
    print()
    print("The list uses TWO SENTINELS (dummy head + dummy tail). Because every")
    print("real node is bracketed by non-None neighbors, the unlink/relink code")
    print("has NO None-checks - just 4 fixed pointer writes. That is the trick")
    print("that makes move-to-head O(1) instead of a special-cased mess.\n")
    print("Layout (head = MRU side, tail = LRU side):\n")
    print("   head <-> [3] <-> [2] <-> [1] <-> tail")
    print("     ^                            ^")
    print("     new/touched nodes            evictions cut HERE")
    print("     go in AFTER head             (the least recently used node)\n")
    # build a tiny concrete example
    c = LRUCache(3)
    for k in (1, 2, 3):
        c.put(k, k)
    print(f"Built cache(cap=3) via put(1),put(2),put(3):  state (MRU->LRU) = {c.state()}")
    print(f"  len(map) = {len(c)} ;  head.next.key = {c.head.next.key} (MRU) ;  "
          f"tail.prev.key = {c.tail.prev.key} (LRU)\n")
    print("Cross-referencing: map[2] points at the middle node, and that node's")
    print(".prev.key / .next.key let us walk the list in O(1) per step:\n")
    n2 = c.map[2]
    print(f"  map[2] -> node(key={n2.key});  node.prev.key={n2.prev.key}  "
          f"node.next.key={n2.next.key}\n")
    print("WHY BOTH halves: HashMap alone cannot answer 'who is least recent?'")
    print("(a dict has no order of use). DLL alone cannot answer 'is key k")
    print("present?' in O(1) (you'd scan the list). Each half supplies the O(1)")
    print("operation the other lacks. The node carries its own key so an")
    print("eviction can delete the matching map entry in O(1) too.\n")
    print("KEY FORMULAS:")
    print("  get(k) : O(1)  =  map.get  +  (on hit) _move_to_head (6 pointer writes)")
    print("  put(k,v): O(1) =  map[k]=n + _add_head + (if over cap) _pop_tail + del map")
    print("  space  : O(C)  (C nodes + C dict entries + 2 sentinels)")
    # GOLD CHECKS
    assert c.state() == [3, 2, 1]
    assert c.head.next.key == 3 and c.tail.prev.key == 1
    assert n2.prev.key == 3 and n2.next.key == 1
    assert len(c) == 3 == len(c.map)
    print("[check] state == [3,2,1], head.next==3 (MRU), tail.prev==1 (LRU)? OK")
    print("[check] map[2].prev==3, map[2].next==1 (DLL neighbors wired)? OK")


# ----------------------------------------------------------------------------
# SECTION B: get(key) - O(1) lookup, then move-to-head on a hit
# ----------------------------------------------------------------------------
def section_get():
    banner("SECTION B: get(key) - HashMap lookup + move-to-head on hit")
    c = LRUCache(3)
    for k in (1, 2, 3):
        c.put(k, k)
    print(f"Start: state (MRU->LRU) = {c.state()}   (cap={c.cap})\n")
    print("get(k) does TWO things, both O(1):\n")
    print("  STEP 1 - LOOKUP:  node = map.get(k)")
    print("     O(1) hash-table probe. node is None  <=>  miss.\n")
    print("  STEP 2 (hit only) - REFRESH RECENCY:  _move_to_head(node)")
    print("     _remove(node)       : node.prev.next = node.next ;")  # noqa
    print("                            node.next.prev = node.prev   (2 writes)")
    print("     _add_head(node)     : splice node in right after head (4 writes)")
    print("     => 6 pointer writes total. No scan, no search. O(1).\n")
    # --- case 1: a HIT ---
    print("CASE 1 - HIT:  get(1)")
    print(f"  before: {fmt_state(c.state())}   (1 is the LRU/tail node)")
    val = c.get(1)
    print(f"  map.get(1) -> node(value={val}) ; _move_to_head lifts it to MRU")
    print(f"  after : {fmt_state(c.state())}   (1 jumped 3->2->1 to the front)")
    assert c.state() == [1, 3, 2]
    assert val == 1
    print("  [check] get(1) returned 1 and state is now [1,3,2]? OK\n")
    # --- case 2: a MISS ---
    print("CASE 2 - MISS: get(99)")
    print(f"  before: {fmt_state(c.state())}")
    val = c.get(99)
    print("  map.get(99) -> None  =>  return -1 immediately; state UNCHANGED")
    print(f"  after : {fmt_state(c.state())}   (a miss never mutates recency)")
    assert val == -1
    assert c.state() == [1, 3, 2]
    print("  [check] get(99) returned -1 and state unchanged [1,3,2]? OK\n")
    print("THE SUBTLE POINT: a hit is not free of side effects - it REORDERS the")
    print("list. That reordering IS the 'recency' bookkeeping, done eagerly so the")
    print("LRU victim is always sitting at the tail ready to evict in O(1). A miss")
    print("does nothing: you cannot 'use' something that is not there.")
    # GOLD
    assert c.state() == [1, 3, 2]
    print("\n[check] after get(1) then get(99): state == [1,3,2]? OK")


# ----------------------------------------------------------------------------
# SECTION C: put(key,value) - insert at head; evict tail if over capacity
# ----------------------------------------------------------------------------
def section_put():
    banner("SECTION C: put(key,value) - add at head; evict tail if over cap")
    c = LRUCache(3)
    print(f"Empty cache, cap={c.cap}. Walk the three cases of put().\n")
    # case 1: fresh insert, room available
    print("CASE 1 - fresh key, room available:  put(1, 'a')")
    ev = c.put(1, "a")
    print(f"  map has no 1 -> create node, map[1]=node, _add_head. size now {len(c)}")
    print(f"  state: {fmt_state(c.state())}   evicted: {ev}")
    assert ev is None and c.state() == [1]
    print("  [check] no eviction, state [1]? OK\n")
    # case 2: key present -> update + refresh (NO eviction even if full)
    c.put(2, "b")
    c.put(3, "c")                                 # now full: [3,2,1]
    print(f"Filled to capacity: put(2),put(3) -> state {fmt_state(c.state())} "
          f"(cap={c.cap}, size={len(c)})\n")
    print("CASE 2 - key present (update):  put(2, 'B')")
    ev = c.put(2, "B")
    print(f"  map has 2 -> update value 'b'->'B', _move_to_head. size stays {len(c)}")
    print(f"  state: {fmt_state(c.state())}   evicted: {ev}")
    assert ev is None and c.state() == [2, 3, 1]
    assert c.map[2].value == "B"
    print("  [check] value updated to 'B', 2 moved to MRU, no eviction? OK\n")
    # case 3: fresh key, over capacity -> evict tail
    print("CASE 3 - fresh key, OVER capacity:  put(4, 'd')")
    print(f"  before: {fmt_state(c.state())}   (LRU/tail = 1)")
    ev = c.put(4, "d")
    print(f"  map has no 4 -> _add_head -> size would be {c.cap + 1} > cap={c.cap}")
    print("  -> _pop_tail() cuts node 1 (the LRU); del map[1].")
    print(f"  state: {fmt_state(c.state())}   evicted: {ev}")
    assert ev == 1 and c.state() == [4, 2, 3]
    assert 1 not in c.map
    print("  [check] evicted the LRU (1), state [4,2,3], 1 gone from map? OK\n")
    print("THE EVICTION RULE IN ONE LINE: when an INSERT would exceed capacity,")
    print("remove the node immediately before the tail sentinel (the LRU). Because")
    print("hits and updates keep moving touched nodes to the head, the tail always")
    print("holds the single coldest item - so picking the victim is O(1), not a")
    print("scan. That is the whole reason the DLL exists.")
    assert c.evictions == [1]
    assert len(c) == c.cap
    print(f"\n[check] eviction log == [1], size == cap == {c.cap}? OK")


# ----------------------------------------------------------------------------
# SECTION D: access sequence simulation [1,2,3,4,1,2,5,1], cap=3 (the GOLD trace)
# ----------------------------------------------------------------------------
def section_trace():
    banner("SECTION D: access-sequence trace  [1,2,3,4,1,2,5,1]  cap=3")
    seq, cap = ACCESS_SEQ, CAPACITY
    print(f"Apply the access stream {seq} to an LRU cache of capacity {cap}.")
    print("Access semantics: a HIT refreshes recency (move to head); a MISS inserts")
    print("at head and, if over capacity, evicts the tail. State shown MRU -> LRU.\n")
    print("| step | access | result | evicted | cache state (MRU->LRU) |")
    print("|------|--------|--------|---------|------------------------|")
    c = LRUCache(cap)
    rows = []
    for i, k in enumerate(seq, 1):
        hit, ev = c.access(k)
        rows.append((i, k, hit, ev, list(c.state())))
        res = "HIT " if hit else "miss"
        evs = "-" if ev is None else str(ev)
        print(f"| {i:<4} | {k:<6} | {res:<6} | {evs:<7} | {c.state()} |")
    hits = sum(1 for r in rows if r[2])
    misses = len(rows) - hits
    evictions = [r[3] for r in rows if r[3] is not None]
    final = rows[-1][4]
    print()
    print(f"Summary over {len(seq)} accesses:")
    print(f"  hits      = {hits}   (step(s) {[r[0] for r in rows if r[2]]})")
    print(f"  misses    = {misses}")
    print(f"  hit rate  = {hits}/{len(seq)} = {hits / len(seq):.4f}  "
          f"({hits / len(seq) * 100:.1f}%)")
    print(f"  evictions = {evictions}   (order: first-evicted -> last-evicted)")
    print(f"  final cache (MRU->LRU) = {final}\n")
    print("Read the trace: the cache thrashes. After it fills at step 3, EVERY")
    print("subsequent distinct key evicts the LRU. Only step 8 is a hit - by then")
    print("key 1 (re-inserted at step 5) is still resident, so it refreshes to MRU.")
    print("This cyclic-ish stream is LRU's known weak spot: when the working set")
    print("(here 4 distinct keys) just exceeds capacity (3), LRU evicts the very")
    print("key the stream is about to revisit. (See Section E: no policy beats")
    print("random much here; Belady/OPT would, but only by knowing the future.)")
    # GOLD CHECKS - the pinned values lru_cache.html reproduces
    assert hits == 1, f"expected 1 hit, got {hits}"
    assert misses == 7
    assert evictions == [1, 2, 3, 4], f"evictions {evictions}"
    assert final == [1, 5, 2], f"final {final}"
    # per-step states pinned
    expected_states = [[1], [2, 1], [3, 2, 1], [4, 3, 2], [1, 4, 3],
                       [2, 1, 4], [5, 2, 1], [1, 5, 2]]
    got_states = [r[4] for r in rows]
    assert got_states == expected_states, got_states
    print("\n[check] hits=1, misses=7, evictions=[1,2,3,4], final=[1,5,2]? OK")
    print("[check] per-step states match the pinned 8-state sequence? OK")


# ----------------------------------------------------------------------------
# SECTION E: policy comparison - LRU vs FIFO vs LFU vs Random vs OPT
# ----------------------------------------------------------------------------
def section_comparison():
    banner("SECTION E: LRU vs FIFO vs LFU vs Random (and OPT) on three workloads")
    print("Same access() contract for every policy: hit -> refresh/record; miss ->")
    print("insert + evict per the policy's rule. Workloads:\n")
    print("  W1 CYCLIC   : the gold stream [1,2,3,4,1,2,5,1], cap=3. Thrashes LRU.")
    print("  W2 UNIFORM  : 300 uniform-random draws from keys 1..8, cap=4. No locality.")
    print("  W3 LOCALITY : 300 draws, 70% from hot set {1,2,3}, 30% from 1..8, cap=4.\n")

    rng_u = random.Random(42)
    W_UNIFORM = [rng_u.randint(1, 8) for _ in range(300)]
    rng_l = random.Random(7)
    hot = (1, 2, 3)
    W_LOCALITY = []
    for _ in range(300):
        if rng_l.random() < 0.7:
            W_LOCALITY.append(rng_l.choice(hot))
        else:
            W_LOCALITY.append(rng_l.randint(1, 8))

    def run(seq, cap):
        n = len(seq)
        lru_h, lru_e = simulate_lru(seq, cap)
        fifo_h, fifo_e = simulate_fifo(seq, cap)
        lfu_h, lfu_e = simulate_lfu(seq, cap)
        rnd_h, rnd_e = simulate_random(seq, cap, seed=0)
        opt_h, opt_e = simulate_opt(seq, cap)
        return [
            ("LRU", lru_h, len(lru_e)),
            ("FIFO", fifo_h, len(fifo_e)),
            ("LFU", lfu_h, len(lfu_e)),
            ("Random", rnd_h, len(rnd_e)),
            ("OPT", opt_h, len(opt_e)),
        ], n

    def opt_text(name, seq, cap):
        rows, n = run(seq, cap)
        opt = rows[-1][1]
        lru = rows[0][1]
        print(f"\n{name}  (n={n}, cap={cap}):")
        print("| policy | hits | hit rate | evictions |")
        print("|--------|------|----------|-----------|")
        for nm, h, ev in rows:
            tag = ""
            if nm == "LRU":
                tag = "  <-- this bundle"
            elif nm == "OPT":
                tag = "  (unimplementable; the ceiling)"
            print(f"| {nm:<6} | {h:<4} | {h / n:.4f}   | {ev:<9} |{tag}")
        gap = (opt - lru) / n * 100
        print(f"  LRU hits {lru} ({lru / n:.1%}); OPT hits {opt} ({opt / n:.1%}); "
              f"LRU is {gap:.1f} pp below the optimum.")
        return rows, n

    print("-" * 60)
    r1, n1 = opt_text("W1 CYCLIC   ", ACCESS_SEQ, 3)
    print("  All four real policies tie on this stream: the only hit (access 1 at")
    print("  step 8) lands for everyone, and every miss evicts once. There is no")
    print("  locality to exploit - the working set (4 keys) just exceeds cap (3).")
    r2, n2 = opt_text("W2 UNIFORM  ", W_UNIFORM, 4)
    print("  With NO locality, recency/frequency carry ~no signal: LRU, FIFO, LFU")
    print("  and Random all cluster near cap/universe = 4/8 = 50%. Random is")
    print("  within a hair of LRU. OPT still edges them out because even uniform")
    print("  streams have accidental near-future repeats it can see.")
    r3, n3 = opt_text("W3 LOCALITY ", W_LOCALITY, 4)
    print("  Strong locality (a 3-key hot set that fits in cap=4) lets recency/")
    print("  frequency identify the hot keys: LRU and LFU pull well ahead of FIFO")
    print("  and Random. FIFO loses because it ignores re-access recency; Random")
    print("  sometimes evicts a hot key by bad luck. OPT remains the ceiling.")
    print()
    print("RULES OF THUMB:")
    print("  - LRU  exploits TEMPORAL locality. Best general-purpose default.")
    print("  - FIFO cheapest, but blind to re-access; ties LRU only on pure scans.")
    print("  - LFU  best on a STABLE hot set; worst when the working set SHIFTS")
    print("         (frequency counts go stale - LRU's recency adapts, LFU's doesn't).")
    print("  - Random: ~free, robust, within a few % of LRU when locality is weak.")
    print("  - OPT   the theoretical ceiling; needs the future, so only a benchmark.")
    # GOLD CHECKS on the pinned W1 row (deterministic, the star policy)
    assert r1[0] == ("LRU", 1, 4)
    assert r1[4][0] == "OPT" and r1[4][1] >= r1[0][1]
    # locality: LRU and LFU must beat Random (strong locality => recency helps)
    lru3 = next(r[1] for r in r3 if r[0] == "LRU")
    lfu3 = next(r[1] for r in r3 if r[0] == "LFU")
    rnd3 = next(r[1] for r in r3 if r[0] == "Random")
    fifo3 = next(r[1] for r in r3 if r[0] == "FIFO")
    assert lru3 > rnd3 and lfu3 > rnd3
    assert lru3 > fifo3
    print("\n[check] W1 LRU row == ('LRU',1,4)? OK")
    print(f"[check] W3 LRU({lru3}) & LFU({lfu3}) > Random({rnd3}); LRU > FIFO({fifo3})? OK")


def simulate_opt(seq, cap):
    """Belady's OPT: on a miss that needs eviction, evict the key whose NEXT use
    is farthest in the future (or never). Provably maximizes hits - but it needs
    the future, so it is a BENCHMARK ceiling, not a real policy. O(n*cap) here.
    """
    present = set()
    items = []
    hits = 0
    evictions = 0
    n = len(seq)
    for i, k in enumerate(seq):
        if k in present:
            hits += 1
            continue
        if len(items) >= cap:
            # next-use distance for each resident key; evict the farthest (inf=never)
            best, best_dist = None, -1
            for cand in items:
                dist = next((j - i for j in range(i + 1, n) if seq[j] == cand),
                            float("inf"))
                if dist > best_dist:
                    best_dist, best = dist, cand
            items.remove(best)
            present.discard(best)
            evictions += 1
        items.append(k)
        present.add(k)
    return hits, [None] * evictions


# ----------------------------------------------------------------------------
# SECTION F: real-world LRU - functools.lru_cache and Redis allkeys-lru
# ----------------------------------------------------------------------------
def section_realworld():
    banner("SECTION F: LRU in the wild - functools.lru_cache and Redis")
    print("The HashMap+DLL LRU is not just a textbook exercise; it ships in the\n"
          "standard library and in the most popular cache servers.\n")

    print("(1) Python functools.lru_cache - per-process MEMOIZATION.")
    print("    Decorate a function and calls are cached; under the hood it is the\n"
          "    same dict + doubly-linked-list LRU (the CPython C implementation\n"
          "    keeps an ordered structure evicted least-recently-used).\n")
    call_count = 0

    @functools.lru_cache(maxsize=3)
    def slow_square(x):
        nonlocal call_count
        call_count += 1
        return x * x

    for x in (2, 3, 4, 2, 5, 2):                  # 2 is revisited after eviction
        slow_square(x)
    info = slow_square.cache_info()
    print("    calls: (2,3,4,2,5,2) with maxsize=3")
    print(f"    functools.lru_cache cache_info(): hits={info.hits} "
          f"misses={info.misses} maxsize={info.maxsize} "
          f"cursize={info.currsize}")
    print("    (the underlying cache evicts least-recently-used, exactly the\n"
          "     structure in Sections A-C.)\n")
    # GOLD CHECK: with maxsize=3 on (2,3,4,2,5,2):
    #   2 miss, 3 miss, 4 miss, 2 hit, 5 miss (evicts LRU=3), 2 hit -> hits=2,misses=4
    assert (info.hits, info.misses) == (2, 4), info
    assert info.maxsize == 3 and info.currsize == 3
    print("    [check] hits=2, misses=4, cursize=3? OK\n")

    print("(2) Redis  maxmemory-policy=allkeys-lru.")
    print("    When Redis hits maxmemory, with this policy it evicts the")
    print("    approximately-LRU key among ALL keys. (Redis uses SAMPLED LRU for")
    print("    speed: it picks the LRU among a random sample of ~5 keys, not a")
    print("    global DLL - a speed/accuracy trade-off. The IDEA is identical to")
    print("    this bundle: evict the key used longest ago.)\n")
    print("    CONFIG SET maxmemory 256mb")
    print("    CONFIG SET maxmemory-policy allkeys-lru\n")
    print("(3) Why approximations? A TRUE global LRU DLL update on every access")
    print("    costs shared-state contention in a multi-threaded server. Production")
    print("    systems (Redis sampled-LRU, Memcached, CPU pseudo-LRU) trade a small")
    print("    hit-rate loss for large throughput/scalability gains. The HashMap+DLL")
    print("    here is the single-threaded gold reference they approximate.")
    assert call_count == 4


# ----------------------------------------------------------------------------
# GOLD: the compact values lru_cache.html recomputes and checks against
# ----------------------------------------------------------------------------
def section_gold():
    banner("GOLD VALUES (pinned for lru_cache.html)")
    c = LRUCache(CAPACITY)
    states = []
    for k in ACCESS_SEQ:
        c.access(k)
        states.append(list(c.state()))
    print(f"Section D trace: access {ACCESS_SEQ}, cap={CAPACITY}")
    print(f"  per-step states (MRU->LRU): {states}")
    print(f"  final cache               : {states[-1]}")
    print(f"  eviction order            : {c.evictions}")
    # recompute hits/misses cleanly on a fresh cache
    c2 = LRUCache(CAPACITY)
    hits = sum(1 for k in ACCESS_SEQ if c2.access(k)[0])
    misses = len(ACCESS_SEQ) - hits
    print(f"  hits/misses               : {hits}/{misses}")
    print(f"  hit rate                  : {hits}/{len(ACCESS_SEQ)} = "
          f"{hits / len(ACCESS_SEQ):.4f}")
    print()
    print("GOLD scalars for .html:")
    print(f"  evictions      = {c.evictions}        (== [1,2,3,4])")
    print(f"  final MRU->LRU = {states[-1]}        (== [1,5,2])")
    print(f"  hits           = {hits}               (== 1, at step 8)")
    print(f"  misses         = {misses}              (== 7)")
    print(f"  step states    = {states}")
    # assertions
    assert c.evictions == [1, 2, 3, 4]
    assert states[-1] == [1, 5, 2]
    assert states == [[1], [2, 1], [3, 2, 1], [4, 3, 2], [1, 4, 3],
                      [2, 1, 4], [5, 2, 1], [1, 5, 2]]
    assert hits == 1 and misses == 7
    print("\n[check] GOLD reproduces from LRUCache? OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("lru_cache.py - reference impl. All numbers below feed LRU_CACHE.md.")
    print("python stdlib only (functools, random, collections). Deterministic.\n")

    section_structure()
    section_get()
    section_put()
    section_trace()
    section_comparison()
    section_realworld()
    section_gold()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
