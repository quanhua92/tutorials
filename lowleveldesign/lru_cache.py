#!/usr/bin/env python3
"""LRU Cache -- HashMap + doubly-linked list (O(1) get/put).

Ground-truth implementation of a capacity-bounded Least-Recently-Used cache,
plus a thread-safe variant and a head-to-head comparison with LFU and FIFO.

What this demonstrates:
  * O(1) get/put via a HashMap (key -> Node) + a doubly-linked list (recency
    order). Each constraint forces the next data-structure decision:
    O(1) lookup  -> HashMap
    O(1) evict   -> tail pointer (no scan)
    O(1) promote -> doubly linked list (both neighbours rewired in O(1))
  * Sentinel head/tail nodes eliminate every null-check edge case.
  * The five invariants that must hold after every operation.
  * A step-by-step eviction animation trace (DLL + HashMap state per op).
  * Capacity edge cases (capacity = 1, existing-key update, miss eviction).
  * A thread-safe variant guarded by threading.RLock.
  * Side-by-side comparison with LFU and FIFO on the same workload.
  * A gold-check signature recomputed by lru_cache.html in JavaScript.

Companion files: LRU_CACHE.md, lru_cache.html
"""

import threading
from collections import OrderedDict, deque


# --------------------------------------------------------------------------- #
#  Node -- one entry in the doubly-linked list
# --------------------------------------------------------------------------- #
class Node:
    """A list node. Holds the key alongside the value so that eviction can
    delete the key from the HashMap in O(1) without searching the list.

    __slots__ shaves ~40% off per-node memory vs a full __dict__.
    """

    __slots__ = ("key", "value", "prev", "next")

    def __init__(self, key=None, value=None):
        self.key = key
        self.value = value
        self.prev = None
        self.next = None


# --------------------------------------------------------------------------- #
#  LRUCache -- the core data structure
# --------------------------------------------------------------------------- #
class LRUCache:
    """Capacity-bounded LRU cache. All operations O(1).

    Layout (sentinel nodes bookend the list):

        head(sentinel) <-> [MRU] <-> ... <-> [LRU] <-> tail(sentinel)

    The HashMap stores Node references, so move-to-head is O(1) pointer
    surgery with no list search. head.next is MRU; tail.prev is LRU.
    """

    def __init__(self, capacity):
        if capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._map = {}                          # key -> Node
        self._head = Node()                     # sentinel (MRU side)
        self._tail = Node()                     # sentinel (LRU side)
        self._head.next = self._tail
        self._tail.prev = self._head

    # -- private helpers (MUST be called with any lock already held) --
    def _insert_at_head(self, node):
        """Splice node between the head sentinel and the current MRU."""
        node.prev = self._head
        node.next = self._head.next
        self._head.next.prev = node
        self._head.next = node

    def _remove_node(self, node):
        """Unlink node by rewiring its two neighbours."""
        node.prev.next = node.next
        node.next.prev = node.prev

    def _move_to_head(self, node):
        """Compose remove + insert. Refreshes recency on a hit."""
        self._remove_node(node)
        self._insert_at_head(node)

    def _evict_tail(self):
        """Detach and return the LRU node (tail.prev). Caller updates map."""
        lru = self._tail.prev
        self._remove_node(lru)
        return lru

    # -- public API --
    def get(self, key):
        """Return value or None on miss. O(1). Promotes the node on hit."""
        node = self._map.get(key)
        if node is None:
            return None                         # cache miss
        self._move_to_head(node)                # refresh recency
        return node.value

    def put(self, key, value):
        """Insert or update. Evicts the LRU entry when over capacity. O(1)."""
        node = self._map.get(key)
        if node is not None:                    # update-in-place path
            node.value = value
            self._move_to_head(node)
            return
        node = Node(key, value)                 # fresh-insert path
        self._map[key] = node
        self._insert_at_head(node)
        if len(self._map) > self.capacity:      # over capacity -> evict LRU
            lru = self._evict_tail()
            del self._map[lru.key]

    def delete(self, key):
        """Remove a key from both map and list. No-op if absent. O(1)."""
        node = self._map.pop(key, None)
        if node is not None:
            self._remove_node(node)

    # -- introspection (used by the trace + gold check) --
    def order(self):
        """Keys from MRU (head side) to LRU (tail side)."""
        out = []
        cur = self._head.next
        while cur is not self._tail:
            out.append(cur.key)
            cur = cur.next
        return out

    def value_of(self, key):
        node = self._map.get(key)
        return node.value if node is not None else None

    def __len__(self):
        return len(self._map)

    def __contains__(self, key):
        return key in self._map


# --------------------------------------------------------------------------- #
#  ThreadSafeLRUCache -- guarded by a reentrant lock
# --------------------------------------------------------------------------- #
class ThreadSafeLRUCache:
    """LRU cache guarded by a reentrant lock.

    Every public method acquires self._lock for its FULL critical section so
    the five invariants hold as observed by any thread. Trade-offs:

      * Global lock (this class)  -- correct, simplest; serialises all access.
      * ReadWriteLock             -- many concurrent readers, one writer; wins
                                     on read-heavy workloads.
      * Segmented locking         -- partition keys across N independent
                                     (map, dll, lock) shards via hash(key) % N;
                                     ~Nx throughput. Production grade.

    Use RLock so a method that calls another guarded method does not
    self-deadlock (re-entrant acquisition).
    """

    def __init__(self, capacity):
        self._inner = LRUCache(capacity)
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            return self._inner.get(key)

    def put(self, key, value):
        with self._lock:
            self._inner.put(key, value)

    def delete(self, key):
        with self._lock:
            self._inner.delete(key)

    def order(self):
        with self._lock:
            return self._inner.order()

    def __len__(self):
        with self._lock:
            return len(self._inner)

    def __contains__(self, key):
        with self._lock:
            return key in self._inner


# --------------------------------------------------------------------------- #
#  FIFOCache -- baseline for comparison (oldest INSERT wins eviction)
# --------------------------------------------------------------------------- #
class FIFOCache:
    """First-In-First-Out cache. Evicts the oldest INSERTED key.

    A get() does NOT refresh recency -- that is the entire difference from
    LRU. Implemented with a deque (insertion queue) + HashMap. O(1) get/put.
    """

    def __init__(self, capacity):
        if capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._map = {}
        self._queue = deque()                   # keys in insertion order

    def get(self, key):
        return self._map.get(key)

    def put(self, key, value):
        if key in self._map:
            self._map[key] = value              # update value, keep position
            return
        if len(self._map) >= self.capacity:
            oldest = self._queue.popleft()
            del self._map[oldest]
        self._map[key] = value
        self._queue.append(key)

    def order(self):
        return list(self._queue)                # insertion order

    def value_of(self, key):
        return self._map.get(key)

    def __len__(self):
        return len(self._map)

    def __contains__(self, key):
        return key in self._map


# --------------------------------------------------------------------------- #
#  LFUCache -- the canonical "harder than LRU" policy
# --------------------------------------------------------------------------- #
class LFUCache:
    """Least-Frequently-Used cache. Evicts the key with the smallest access
    count; ties are broken by LRU within that frequency bucket.

    O(1) amortised via three structures:
      key -> [value, freq]            (the value + its frequency)
      freq -> OrderedDict(keys)       (keys at that frequency, in recency order)
      min_freq cursor                 (cheapest eviction target)

    Every access that touches a key bumps its frequency and moves it to the
    next bucket. When a bucket empties and it was the min, min_freq advances.
    """

    def __init__(self, capacity):
        if capacity <= 0:
            raise ValueError("capacity must be a positive integer")
        self.capacity = capacity
        self._kv = {}                           # key -> [value, freq]
        self._freq = {}                         # freq -> OrderedDict(key -> None)
        self._min_freq = 0

    def _bump(self, key):
        val, f = self._kv[key]
        bucket = self._freq[f]
        del bucket[key]
        if not bucket:
            del self._freq[f]
            if self._min_freq == f:
                self._min_freq = f + 1
        nf = f + 1
        self._kv[key][1] = nf
        self._freq.setdefault(nf, OrderedDict())[key] = None

    def get(self, key):
        if key not in self._kv:
            return None
        self._bump(key)
        return self._kv[key][0]

    def put(self, key, value):
        if key in self._kv:
            self._kv[key][0] = value
            self._bump(key)
            return
        if len(self._kv) >= self.capacity:
            lfu_bucket = self._freq[self._min_freq]
            evict, _ = lfu_bucket.popitem(last=False)   # LRU within min freq
            del self._kv[evict]
            if not lfu_bucket:
                del self._freq[self._min_freq]
        self._kv[key] = [value, 1]
        self._freq.setdefault(1, OrderedDict())[key] = None
        self._min_freq = 1

    def order(self):
        """Keys ordered by (frequency asc, then recency asc). For display."""
        out = []
        for f in sorted(self._freq):
            out.extend(self._freq[f].keys())
        return out

    def value_of(self, key):
        entry = self._kv.get(key)
        return entry[0] if entry is not None else None

    def freq_of(self, key):
        entry = self._kv.get(key)
        return entry[1] if entry is not None else 0

    def __len__(self):
        return len(self._kv)

    def __contains__(self, key):
        return key in self._kv


# --------------------------------------------------------------------------- #
#  Pretty-printer + state renderer
# --------------------------------------------------------------------------- #
def banner(title):
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}")


def render_dll(cache):
    """ASCII of the doubly-linked list: head <-> [k:v] <-> ... <-> tail."""
    keys = cache.order()
    if not keys:
        return "head <-> tail  (empty)"
    nodes = " <-> ".join(f"[{k}:{cache.value_of(k)}]" for k in keys)
    return f"head <-> {nodes} <-> tail"


def render_map(cache):
    keys = cache.order()
    inner = ", ".join(
        f"{k} -> Node(value={cache.value_of(k)})" for k in keys
    )
    return "{" + inner + "}"


def render_state(cache, note=""):
    line = f"    DLL : {render_dll(cache)}"
    line += f"\n    MAP : {render_map(cache)}"
    if note:
        line += f"\n    NOTE: {note}"
    return line


# --------------------------------------------------------------------------- #
#  Demo sections
# --------------------------------------------------------------------------- #
def section_why_composition():
    banner("WHY HASHMAP + DOUBLY-LINKED LIST -- each constraint forces the next")

    print("""
  Goal: O(1) get(key) AND O(1) put(key,value) with capacity-bounded eviction.

  Constraint chasing (say this OUT LOUD in the interview):

    1. O(1) lookup by key
         --> we need a HashMap (key -> something).

    2. O(1) eviction of the least-recently-used entry
         --> we must know the LRU node WITHOUT scanning
         --> a tail pointer: tail.prev is always the LRU.

    3. O(1) move-to-head on every hit (promote recency)
         --> we must rewire a node's TWO neighbours in O(1)
         --> a SINGLY linked list only gives the successor in O(1);
             finding the predecessor is O(n)
         --> therefore we need a DOUBLY linked list.

    4. The HashMap stores NODE POINTERS, not just values
         --> so move-to-head needs NO list search; O(1) pointer surgery.

    5. Sentinel head/tail nodes
         --> head.next is MRU, tail.prev is LRU
         --> eliminates EVERY null check during pointer surgery
             (insert/remove never touch a None neighbour).

  The singly-vs-doubly decision is the #1 follow-up question. The answer:
  removing an arbitrary node needs its predecessor; only a back-pointer
  gives that in O(1).""")


def section_invariants():
    banner("THE FIVE INVARIANTS -- state these BEFORE you write any code")

    invs = [
        ("1. Size",
         "len(map) == count of non-sentinel nodes in the list"),
        ("2. Recency",
         "head.next is MRU; tail.prev is LRU (always)"),
        ("3. Capacity",
         "len(map) <= capacity after EVERY put()"),
        ("4. Bidirectionality",
         "for every node N: N.prev.next == N and N.next.prev == N"),
        ("5. Thread safety",
         "invariants 1-4 hold as observed by ANY thread"),
    ]
    for name, body in invs:
        print(f"  {name:<20}{body}")

    print("""
  Every helper (_insert_at_head, _remove_node, _move_to_head, _evict_tail)
  must preserve all five. The invariant that breaks most often in bugs is
  #4 (bidirectionality) when someone forgets to update prev.next AND next.prev.

  Self-test: after every operation assert len(cache) == len(cache.order())
  and that order() is non-empty iff len(cache) > 0.""")

    c = LRUCache(3)
    c.put(1, 1)
    c.put(2, 2)
    c.get(1)
    assert len(c) == len(c.order()) == 2
    assert c.order()[0] == 1                      # MRU
    print("  [check] invariant self-test passed (cap=3, 2 keys, MRU=1)")


def section_eviction_animation_trace():
    banner("EVICTION ANIMATION TRACE -- watch the list + map after every op")

    print("""
  Capacity = 2. The classic LeetCode 146 scenario. Watch how a hit promotes
  a node to MRU and how put() on a full cache evicts tail.prev (the LRU).""")

    c = LRUCache(2)
    ops = [
        ("put(1, 1)", "insert 1 -- cache was empty"),
        ("put(2, 2)", "insert 2 -- now full (cap=2)"),
        ("get(1)",    "HIT 1 -- promote 1 to MRU; 2 becomes LRU"),
        ("put(3, 3)", "insert 3 -- FULL, evict LRU (key 2)"),
        ("get(2)",    "MISS 2 -- it was just evicted"),
        ("put(4, 4)", "insert 4 -- FULL, evict LRU (key 1)"),
        ("get(1)",    "MISS 1 -- evicted on the previous put"),
        ("get(3)",    "HIT 3 -- promote 3 to MRU"),
        ("get(4)",    "HIT 4 -- promote 4 to MRU"),
    ]
    print()
    for i, (op, note) in enumerate(ops):
        print(f"  step {i + 1}:  {op}")
        if op.startswith("put"):
            k, v = op[4:-1].split(",")
            c.put(int(k.strip()), int(v.strip()))
        else:
            k = int(op[4:-1])
            result = c.get(k)
            tag = f"-> {result}" if result is not None else "-> MISS (None)"
            print(f"        return {tag}")
        print(render_state(c, note))
        print()
    print("  Final key order (MRU -> LRU): " + str(c.order()))


def section_capacity_scenarios():
    banner("CAPACITY EDGE CASES -- capacity=1, update-in-place, miss-eviction")

    print("\n  Scenario A: capacity = 1 (every put beyond the first evicts)")
    c = LRUCache(1)
    c.put(10, 100)
    print(render_state(c, "after put(10,100)"))
    c.put(20, 200)
    print(render_state(c, "after put(20,200) -- key 10 evicted"))
    c.get(10)
    print(render_state(c, "get(10) returned None (miss)"))
    assert c.get(10) is None and c.get(20) == 200
    print("  [check] capacity=1 behaves (put evicts, miss returns None)")

    print("\n  Scenario B: put() on an EXISTING key updates value + promotes, "
          "NO eviction")
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    before = len(c)
    c.put(1, 999)                                 # update existing
    after = len(c)
    print(render_state(c, "after put(1, 999) -- value updated, moved to MRU, "
                          "size unchanged"))
    assert c.value_of(1) == 999 and before == after == 2
    assert c.order()[0] == 1
    print(f"  [check] update-in-place: size {before} -> {after} (no evict), "
          f"value=999, MRU=1")

    print("\n  Scenario C: delete() keeps map and list consistent (no leak)")
    c = LRUCache(3)
    for k in (1, 2, 3):
        c.put(k, k * 10)
    c.delete(2)
    print(render_state(c, "after delete(2) -- removed from BOTH map and list"))
    assert len(c) == 2 and 2 not in c and c.order() == [3, 1]
    print("  [check] delete() consistent: size=2, key 2 gone, order=[3,1]")

    print("\n  Scenario D: invalid capacity is rejected")
    try:
        LRUCache(0)
        print("  [FAIL] LRUCache(0) should have raised")
    except ValueError:
        print("  [check] LRUCache(0) raised ValueError as expected")


def section_thread_safe():
    banner("THREAD-SAFE VARIANT -- global RLock guards every critical section")

    print("""
  200 concurrent workers each do 500 puts on shared keys [0..9]. Without a
  lock the map/list would desync (memory leak or double-evict). With the
  RLock the five invariants hold for every observer.""")

    tc = ThreadSafeLRUCache(capacity=8)
    workers = 200
    per_worker = 500

    def worker(tid):
        for i in range(per_worker):
            key = (tid + i) % 10
            tc.put(key, tid * 1000 + i)
            tc.get(key)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    size = len(tc)
    order = tc.order()
    print(f"  {workers} workers x {per_worker} ops = "
          f"{workers * per_worker * 2} total ops")
    print(f"  final size = {size}  (cap=8, so size <= 8)")
    print(f"  final order (MRU -> LRU) = {order}")
    assert size <= 8, f"capacity violated: size={size} > 8"
    assert size == len(order), "map/list desync"
    # bidirectionality walk: every node reachable both directions
    cur = tc._inner._head
    fwd = 0
    while cur.next is not None:
        fwd += 1
        cur = cur.next
    assert cur is tc._inner._tail
    print(f"  [check] thread-safe: size={size} <= 8, list walks cleanly "
          f"({fwd} ptrs to tail), no crash across "
          f"{workers * per_worker * 2} ops")


def section_comparison():
    banner("LRU vs LFU vs FIFO -- same workload, different eviction choice")

    print("""
  Run ONE workload through all three policies (capacity = 2) and observe
  which key each evicts and the resulting hit rate. The workload warms key 1
  heavily (hot key), then touches key 2 to make it the LRU, then inserts key 3
  to force an eviction.""")

    workload = [
        ("put", 1, 10),
        ("put", 2, 20),
        ("get", 1),     # warm key 1 (LFU freq 1 -> 2)
        ("get", 1),     # freq 2 -> 3
        ("get", 1),     # freq 3 -> 4   (key 1 is now hot)
        ("get", 2),     # warm key 2; in LRU this makes key 1 the LRU
        ("put", 3, 30), # EVICTION POINT (cap=2 full)
        ("get", 1),     # LFU kept the hot key -> HIT; LRU/FIFO evicted it -> MISS
        ("get", 1),     # same again
    ]

    def run(policy):
        hits = misses = 0
        evicted_at_put3 = None
        for op in workload:
            if op[0] == "put":
                policy.put(op[1], op[2])
                if op[1] == 3:
                    # whatever got removed is the complement of the members
                    members = set(policy.order())
                    evicted_at_put3 = (
                        ({1, 2, 3} - members).pop() if len(members) < 3
                        else None)
            else:
                v = policy.get(op[1])
                if v is None:
                    misses += 1
                else:
                    hits += 1
        total = hits + misses
        return hits, misses, evicted_at_put3, policy.order(), total

    policies = [
        ("LRU", LRUCache(2)),
        ("LFU", LFUCache(2)),
        ("FIFO", FIFOCache(2)),
    ]

    print(f"\n  {'Policy':<7}{'evicted@put(3)':<18}"
          f"{'final members':<16}{'hits':<7}{'hit rate'}")
    print("  " + "-" * 60)
    results = {}
    for name, p in policies:
        hits, misses, evicted, members, total = run(p)
        rate = hits / total * 100
        results[name] = (hits, total, evicted, members)
        print(f"  {name:<7}{str(evicted):<18}{str(members):<16}"
              f"{hits:<7}{rate:.1f}%")

    print("""
  Reading the table:
    * LFU evicted key 2 because key 1 had frequency 4 >> 2's frequency 2.
      It PROTECTED the hot key -> 100% hit rate on the trailing gets.
    * LRU evicted key 1 because the get(2) right before put(3) had just made
      key 1 the LRU. LRU has no memory of key 1's high frequency.
    * FIFO evicted key 1 because key 1 was inserted FIRST -- gets never
      refresh position in FIFO.

  The takeaway: on a FREQUENCY-skewed workload LFU wins; on a RECENCY-skewed
  workload (temporal locality, e.g. news feed) LRU wins; FIFO is the cheapest
  baseline and rarely the right answer when access is skewed.""")

    # concrete assertions for the gold check
    assert results["LRU"][2] == 1, "LRU should evict key 1 here"
    assert results["LFU"][2] == 2, "LFU should evict key 2 here"
    assert results["FIFO"][2] == 1, "FIFO should evict key 1 here"
    assert results["LFU"][0] == 6 and results["LRU"][0] == 4
    print("  [check] eviction choices match the analysis above")


def section_gold_check():
    """A single concrete signature recomputed by lru_cache.html in JS."""
    banner("GOLD CHECK  (recomputed by lru_cache.html in JS)")

    # Classic LeetCode 146 trace -- the canonical LRU signature.
    c = LRUCache(2)
    c.put(1, 1)
    c.put(2, 2)
    gets = []
    gets.append(c.get(1))     # 1
    c.put(3, 3)               # evicts 2
    gets.append(c.get(2))     # None -> -1
    c.put(4, 4)               # evicts 1
    gets.append(c.get(1))     # None -> -1
    gets.append(c.get(3))     # 3
    gets.append(c.get(4))     # 4

    sig = ",".join(str(g) if g is not None else "-1" for g in gets)
    final_order = ",".join(str(k) for k in c.order())

    gold_sig = "1,-1,-1,3,4"
    gold_order = "4,3"
    print(f"  lru.gets_signature   = {sig}")
    print(f"  lru.final_order      = {final_order}   (MRU -> LRU)")
    assert sig == gold_sig, f"signature mismatch: {sig} != {gold_sig}"
    assert final_order == gold_order, (
        f"order mismatch: {final_order} != {gold_order}")
    print("  [check] OK")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("#" * 78)
    print("# LRU CACHE -- HashMap + doubly-linked list, O(1) get/put "
          "(pure stdlib)")
    print("#" * 78)
    section_why_composition()
    section_invariants()
    section_eviction_animation_trace()
    section_capacity_scenarios()
    section_thread_safe()
    section_comparison()
    section_gold_check()
    print("\n[check] OK -- all sections ran")
