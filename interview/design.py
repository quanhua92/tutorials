"""
design.py - Reference implementation of the Design pattern for O(1) caches
with an eviction policy: LFU Cache (HashMap + frequency buckets, where each
bucket is an OrderedDict = HashMap + DLL) and LRU Cache (HashMap + explicit
doubly-linked list).

This is the SINGLE SOURCE OF TRUTH for DESIGN.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 design.py > design_output.txt

Pure Python stdlib only. Deterministic (hardcoded op sequences; OrderedDict
gives a stable, defined eviction order so the LRU tie-break is reproducible
and identical to the JS in design.html).

============================================================================
THE INTUITION (read this first) - a busy restaurant
============================================================================
Imagine you run a busy restaurant. Looking up a customer's order by walking a
long list is too slow. Instead you keep SEVERAL fast-access lists, each giving
you one view of the data, and you update them all together so they never
disagree. You spend memory (paper) to buy time (speed).

That is the whole "design" pattern: combine structures so every operation is
O(1) average AND a policy (recency / frequency) is enforceable in O(1).

    * For LRU you need "which key was least-recently-used?" in O(1):
      a HashMap (key -> node) + a doubly-linked list ordered by recency.
      The HashMap gives O(1) lookup; the DLL gives O(1) splice-to-front
      (mark MRU) and O(1) pop-from-back (evict LRU).

    * For LFU you need "which key has the smallest frequency, and among those
      the least-recently-used?" in O(1): THREE dicts -
          key_to_val   (key -> value)
          key_to_freq  (key -> frequency)
          freq_to_keys (frequency -> OrderedDict of keys)   <-- the DLL is here
      plus a min_freq counter. The OrderedDict per bucket is itself a
      HashMap + DLL, giving O(1) LRU tie-break inside one frequency bucket.

The mechanism, in four moves (shared by both caches):

    operation -> HashMap gives O(1) locate the node
              -> splice it out of its current DLL/bucket position  (O(1))
              -> re-insert it at the "most-recently-used" slot    (O(1))
              -> if full, drop the policy victim (LRU / min_freq) (O(1))

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  key, value      the cached entry. The key is the lookup handle.
  capacity (cap)  max entries. put beyond cap triggers eviction.
  recency         WHEN a key was last touched. LRU evicts the least-recent.
  frequency       HOW OFTEN a key is touched. LFU evicts the least-frequent.
  tie-break       when two keys share the eviction priority (same min freq in
                  LFU), the least-RECENTLY-used one among them goes. An
                  OrderedDict (or DLL) per bucket encodes recency for free.
  min_freq        the smallest frequency currently held by any key. The LFU
                  victim always lives at the front of freq_to_keys[min_freq].
  DLL             doubly-linked list: each node knows prev + next, so removing
                  or re-inserting a known node is O(1) (no scan).
  OrderedDict     Python's dict + DLL hybrid: move_to_end and popitem(last=)
                  are O(1). We use it as a ready-made per-frequency DLL.
  sentinel        a dummy head/tail node so the DLL never has empty edge cases.

============================================================================
THE SKELETONS (the two interview answers - memorize the shapes)
============================================================================
    # --- LRU: HashMap + doubly-linked list --------------------------------
    class LRUCache:
        def __init__(self, capacity):
            self.cap = capacity
            self.map = {}                      # key -> Node  (O(1) locate)
            self.head = Node()                 # sentinel: head side = MRU
            self.tail = Node()                 # sentinel: tail side = LRU
            self.head.nxt = self.tail
            self.tail.prev = self.head

        def get(self, key):
            if key not in self.map: return -1
            node = self.map[key]
            self._remove(node); self._add_front(node)   # mark MRU
            return node.val

        def put(self, key, value):
            if self.cap <= 0: return
            if key in self.map:                          # update + refresh
                node = self.map[key]; node.val = value
                self._remove(node); self._add_front(node); return
            node = Node(key, value)
            self.map[key] = node; self._add_front(node)
            if len(self.map) > self.cap:                 # evict LRU (tail.prev)
                lru = self.tail.prev
                self._remove(lru); del self.map[lru.key]

    # --- LFU: HashMap + frequency buckets (OrderedDict = HashMap + DLL) ---
    class LFUCache:
        def __init__(self, capacity):
            self.cap = capacity
            self.key_to_val  = {}                        # key -> value
            self.key_to_freq = {}                        # key -> frequency
            self.freq_to_keys = {}                       # frequency -> OD{key}
            self.min_freq = 0

        def get(self, key):
            if key not in self.key_to_val: return -1
            self._bump(key)                              # freq += 1, refresh
            return self.key_to_val[key]

        def put(self, key, value):
            if self.cap <= 0: return
            if key in self.key_to_val:                   # update + bump
                self.key_to_val[key] = value; self._bump(key); return
            if len(self.key_to_val) >= self.cap:         # evict LFU+LRU
                bucket = self.freq_to_keys[self.min_freq]
                evict, _ = bucket.popitem(last=False)    # front = least recent
                if not bucket: del self.freq_to_keys[self.min_freq]
                del self.key_to_val[evict]; del self.key_to_freq[evict]
            self.key_to_val[key] = value
            self.key_to_freq[key] = 1
            self.freq_to_keys.setdefault(1, OrderedDict())[key] = None
            self.min_freq = 1                            # new key -> freq 1

        def _bump(self, key):
            f = self.key_to_freq[key]
            bucket = self.freq_to_keys[f]
            bucket.pop(key)                              # leave old bucket
            if not bucket:
                del self.freq_to_keys[f]
                if self.min_freq == f: self.min_freq = f + 1
            nf = f + 1
            self.key_to_freq[key] = nf
            self.freq_to_keys.setdefault(nf, OrderedDict())[key] = None  # MRU
"""

from __future__ import annotations

from collections import OrderedDict


# ============================================================================
# LRU CACHE - HashMap + explicit doubly-linked list
# ============================================================================
class _Node:
    """A DLL node. __slots__ keeps it tiny and fast."""
    __slots__ = ("key", "val", "prev", "nxt")

    def __init__(self, key: int = 0, val: int = 0) -> None:
        self.key = key
        self.val = val
        self.prev: _Node | None = None
        self.nxt: _Node | None = None


class LRUCache:
    """O(1) get/put via HashMap (key -> Node) + DLL ordered MRU..LRU.

    head side == MOST-recently-used; tail side == LEAST-recently-used.
    get/put on an existing key splice it to the front (MRU). When the cache
    overflows, tail.prev (the LRU) is dropped. Sentinels remove all edge cases.
    """

    def __init__(self, capacity: int) -> None:
        self.cap = capacity
        self.map: dict[int, _Node] = {}
        self.head = _Node()          # sentinel MRU side
        self.tail = _Node()          # sentinel LRU side
        self.head.nxt = self.tail
        self.tail.prev = self.head

    # ---- DLL primitives: both O(1) ----------------------------------------
    def _remove(self, node: _Node) -> None:
        node.prev.nxt = node.nxt     # type: ignore[union-attr]
        node.nxt.prev = node.prev     # type: ignore[union-attr]

    def _add_front(self, node: _Node) -> None:
        """Insert right after head == mark as most-recently-used."""
        node.prev = self.head
        node.nxt = self.head.nxt
        self.head.nxt.prev = node     # type: ignore[union-attr]
        self.head.nxt = node

    # ---- public API --------------------------------------------------------
    def get(self, key: int) -> int:
        if key not in self.map:
            return -1
        node = self.map[key]
        self._remove(node)
        self._add_front(node)
        return node.val

    def put(self, key: int, value: int) -> None:
        if self.cap <= 0:
            return
        if key in self.map:
            node = self.map[key]
            node.val = value
            self._remove(node)
            self._add_front(node)
            return
        node = _Node(key, value)
        self.map[key] = node
        self._add_front(node)
        if len(self.map) > self.cap:
            lru = self.tail.prev     # type: ignore[assignment]
            self._remove(lru)
            del self.map[lru.key]

    # ---- introspection (for traces / asserts; NOT used by the algorithm) --
    def order_mru_to_lru(self) -> list[int]:
        """Keys from most-recently-used to least-recently-used."""
        out: list[int] = []
        cur = self.head.nxt
        while cur is not self.tail and cur is not None:
            out.append(cur.key)
            cur = cur.nxt
        return out

    def values(self) -> dict[int, int]:
        return {k: n.val for k, n in self.map.items()}


# ============================================================================
# LFU CACHE - HashMap + frequency buckets (OrderedDict per bucket) + min_freq
# ============================================================================
class LFUCache:
    """O(1) get/put via three dicts + a min_freq counter.

    freq_to_keys[f] is an OrderedDict whose key order encodes RECENCY within
    that frequency (front = least recent, end = most recent). That OrderedDict
    is itself a HashMap + DLL, so every per-bucket op is O(1).

    Eviction picks freq_to_keys[min_freq] and pops its FRONT (least-recent
    among the least-frequent) -> the LFU-with-LRU-tiebreak victim, in O(1).
    """

    def __init__(self, capacity: int) -> None:
        self.cap = capacity
        self.key_to_val: dict[int, int] = {}
        self.key_to_freq: dict[int, int] = {}
        self.freq_to_keys: dict[int, OrderedDict[int, None]] = {}
        self.min_freq = 0

    def _bump(self, key: int) -> None:
        """Increase key's frequency by 1: move it to the next bucket, keeping
        it as the most-recent entry there. Maintain min_freq in O(1)."""
        f = self.key_to_freq[key]
        bucket = self.freq_to_keys[f]
        bucket.pop(key)                          # O(1): leave old bucket
        if not bucket:
            del self.freq_to_keys[f]
            if self.min_freq == f:
                self.min_freq = f + 1            # no key left at old min -> bump
        nf = f + 1
        self.key_to_freq[key] = nf
        self.freq_to_keys.setdefault(nf, OrderedDict())[key] = None   # O(1): MRU

    def get(self, key: int) -> int:
        if key not in self.key_to_val:
            return -1
        self._bump(key)
        return self.key_to_val[key]

    def put(self, key: int, value: int) -> None:
        if self.cap <= 0:
            return
        if key in self.key_to_val:               # update + bump (no size change)
            self.key_to_val[key] = value
            self._bump(key)
            return
        if len(self.key_to_val) >= self.cap:     # evict LFU (+ LRU tie-break)
            bucket = self.freq_to_keys[self.min_freq]
            evict, _ = bucket.popitem(last=False)   # front = least recent
            if not bucket:
                del self.freq_to_keys[self.min_freq]
            del self.key_to_val[evict]
            del self.key_to_freq[evict]
        self.key_to_val[key] = value
        self.key_to_freq[key] = 1
        self.freq_to_keys.setdefault(1, OrderedDict())[key] = None
        self.min_freq = 1                        # a brand-new key is the new min


# ============================================================================
# TRACE BUILDERS - drive a cache through an op list, snapshotting each step
# for the worked-example tables in DESIGN.md and the animation in design.html.
# ============================================================================
def trace_lru(cap: int, ops: list[tuple]) -> list[dict]:
    """ops entries: ('put', k, v) | ('get', k). Each step captures the state
    AFTER the op plus the evicted key (if any)."""
    c = LRUCache(cap)
    snaps: list[dict] = []
    snaps.append({"op": "(init)", "ret": None, "evict": None,
                  "order": [], "kv": {}, "note": f"capacity = {cap}, empty"})
    for op in ops:
        before = set(c.map)
        if op[0] == "put":
            ret = None
            c.put(op[1], op[2])
            label = f"put({op[1]},{op[2]})"
        else:
            ret = c.get(op[1])
            label = f"get({op[1]})"
        after = set(c.map)
        evict_set = before - after
        evict = next(iter(evict_set)) if evict_set else None
        order = c.order_mru_to_lru()
        if evict is not None:
            note = (f"cache full -> evict LRU key {evict} (tail.prev); "
                    f"insert {op[1]} at MRU")
        elif op[0] == "put" and op[1] in before:
            note = f"update key {op[1]} = {op[2]}; splice to MRU (no resize)"
        elif op[0] == "put":
            note = f"insert {op[1]} at MRU (front)"
        elif ret == -1:
            note = f"key {op[1]} absent -> -1"
        else:
            note = f"hit key {op[1]}; splice to MRU, return {ret}"
        snaps.append({"op": label, "ret": ret, "evict": evict,
                      "order": order, "kv": c.values(), "note": note})
    return snaps


def trace_lfu(cap: int, ops: list[tuple]) -> list[dict]:
    """ops entries: ('put', k, v) | ('get', k). Each step captures freq buckets
    (ordered LRU..MRU within each), key_to_val, min_freq, and the evicted key."""
    c = LFUCache(cap)
    snaps: list[dict] = []
    snaps.append({"op": "(init)", "ret": None, "evict": None,
                  "min_freq": 0, "buckets": {}, "kv": {},
                  "note": f"capacity = {cap}, empty"})
    for op in ops:
        before = set(c.key_to_val)
        min_before = c.min_freq
        old_freq = c.key_to_freq.get(op[1])
        if op[0] == "put":
            ret = None
            c.put(op[1], op[2])
            label = f"put({op[1]},{op[2]})"
        else:
            ret = c.get(op[1])
            label = f"get({op[1]})"
        after = set(c.key_to_val)
        evict_set = before - after
        evict = next(iter(evict_set)) if evict_set else None
        buckets = {f: list(od.keys()) for f, od in sorted(c.freq_to_keys.items())}
        new_freq = c.key_to_freq.get(op[1])
        if evict is not None:
            note = (f"cache full -> evict LFU key {evict} "
                    f"(front of min_freq={min_before} bucket); "
                    f"insert {op[1]} at freq 1, min_freq=1")
        elif op[0] == "put" and op[1] in before:
            note = f"update key {op[1]} = {op[2]}; freq {old_freq} -> {new_freq}"
        elif op[0] == "put":
            note = f"insert {op[1]} at freq 1 (min_freq resets to 1)"
        elif ret == -1:
            note = f"key {op[1]} absent -> -1"
        else:
            note = (f"hit key {op[1]}; freq {old_freq} -> {new_freq}, "
                    f"min_freq {min_before} -> {c.min_freq}")
        snaps.append({"op": label, "ret": ret, "evict": evict,
                      "min_freq": c.min_freq, "buckets": buckets,
                      "kv": dict(c.key_to_val), "note": note})
    return snaps


# ============================================================================
# The canonical op sequences used everywhere (py output, md tables, html trace)
# ============================================================================
LFU_OPS = [
    ("put", 1, 1), ("put", 2, 2), ("get", 1), ("put", 3, 3), ("get", 2),
    ("get", 3), ("put", 4, 4), ("get", 1), ("get", 3), ("get", 4),
]
LFU_EXPECTED = [None, None, 1, None, -1, 3, None, -1, 3, 4]

LRU_OPS = [
    ("put", 1, 1), ("put", 2, 2), ("get", 1), ("put", 3, 3), ("get", 2),
    ("put", 4, 4), ("get", 1), ("get", 3), ("get", 4),
]
LRU_EXPECTED = [None, None, 1, None, -1, None, -1, 3, 4]


# ============================================================================
# SECTION A - the pattern: combine structures for O(1) + a policy
# ============================================================================
def section_a() -> None:
    print("=" * 76)
    print("SECTION A - The Design pattern: O(1) ops + an eviction policy")
    print("=" * 76)
    print()
    print("Mental model: keep SEVERAL fast-access structures and update them")
    print("together so they never disagree. The HashMap gives O(1) locate; a")
    print("second structure (DLL / OrderedDict / frequency bucket) encodes the")
    print("policy (recency or frequency) and gives O(1) splice + evict.")
    print()
    print("  LRU = HashMap{key -> node}  +  DLL ordered MRU..LRU")
    print("        get/put splice the node to the front (MRU); evict tail.prev")
    print()
    print("  LFU = HashMap{key -> val}  +  HashMap{key -> freq}")
    print("        + HashMap{freq -> OrderedDict{keys}}  +  min_freq counter")
    print("        bump a key = pop from bucket[f], append to bucket[f+1];")
    print("        evict = popitem(last=False) of bucket[min_freq]")
    print()
    print("Pattern-recognition signals")
    print("---------------------------")
    print('  "Design a class", "implement a data structure"          -> design')
    print('  "implement a cache", "eviction policy"                  -> design')
    print('  "O(1) average time" for get/put/insert/delete           -> design')
    print('  "Least Recently Used", "LRU"                            -> DLL+map')
    print('  "Least Frequently Used", "LFU"                          -> freq buckets')
    print('  "most/least recent", "recency", "last used"             -> DLL+map')
    print('  "how many times used", "frequency", "use counter"       -> freq buckets')
    print()
    print("The two interview skeletons (see module docstring for full code):")
    print()
    print("  class LRUCache:                        class LFUCache:")
    print("      self.map  = {}   # key->Node          self.key_to_val  = {}")
    print("      self.head = Node()  # MRU side        self.key_to_freq = {}")
    print("      self.tail = Node()  # LRU side        self.freq_to_keys = {}")
    print("      get(k): map[k];                       self.min_freq = 0")
    print("          _remove; _add_front")
    print("      put(k,v): if k in map: update;        get(k): _bump(k); return val")
    print("          else: add_front;                   put(k,v): if k present: _bump;")
    print("          if over cap: evict tail.prev                else: evict min_freq;")
    print("                                                   insert @freq1; min_freq=1")
    print()


# ============================================================================
# SECTION B - P460 LFU CACHE (full trace of the LeetCode example)
# ============================================================================
def section_b() -> None:
    print("=" * 76)
    print("SECTION B - P460 LFU Cache  (HashMap + frequency buckets + DLL)")
    print("=" * 76)
    print()
    print("Three dicts + a min_freq counter. freq_to_keys[f] is an OrderedDict")
    print("(= HashMap + DLL): its order encodes RECENCY within frequency f, so")
    print("the LFU+LRU tie-break victim is just popitem(last=False) of the")
    print("min_freq bucket - O(1).")
    print()
    cap = 2
    print(f"capacity = {cap}")
    print("op sequence (LeetCode P460 Example 1):")
    print("  put 1,1 ; put 2,2 ; get 1 ; put 3,3 ; get 2 ; get 3 ; "
          "put 4,4 ; get 1 ; get 3 ; get 4")
    print()
    snaps = trace_lfu(cap, LFU_OPS)
    print("Step trace  (buckets list keys LRU..MRU within each frequency):")
    print()
    print("  op          return  evict  min  freq buckets                  key->val")
    print("  ----------  ------  -----  ---  -----------------------------  --------")
    for s in snaps:
        ret = "null" if s["ret"] is None else str(s["ret"])
        ev = "-" if s["evict"] is None else str(s["evict"])
        buck = ", ".join(f"{f}:{ks}" for f, ks in s["buckets"].items()) or "(empty)"
        kv = ", ".join(f"{k}:{v}" for k, v in sorted(s["kv"].items())) or "(empty)"
        print(f"  {s['op']:<10}  {ret:<6}  {ev:<5}  {str(s['min_freq']):<3}  "
              f"{buck:<29}  {kv}")
    print()
    print("Notes per step:")
    for s in snaps[1:]:
        print(f"  {s['op']:<10}  {s['note']}")
    print()
    # verify against LeetCode
    c = LFUCache(cap)
    got = []
    for op in LFU_OPS:
        if op[0] == "put":
            c.put(op[1], op[2]); got.append(None)
        else:
            got.append(c.get(op[1]))
    expected_str = ", ".join("null" if x is None else str(x) for x in LFU_EXPECTED)
    got_str = ", ".join("null" if x is None else str(x) for x in got)
    print(f"returns     = [{got_str}]")
    print(f"LeetCode    = [{expected_str}]")
    print(f"match: {got == LFU_EXPECTED}")
    print()


# ============================================================================
# SECTION C - P146 LRU CACHE (full trace)
# ============================================================================
def section_c() -> None:
    print("=" * 76)
    print("SECTION C - P146 LRU Cache  (HashMap + doubly-linked list)")
    print("=" * 76)
    print()
    print("HashMap{key -> node} gives O(1) locate. A doubly-linked list with")
    print("head/tail sentinels is ordered MRU (head side) .. LRU (tail side).")
    print("get/put on a key splice it to the front (MRU) in O(1); when the")
    print("cache overflows, tail.prev (the LRU) is removed in O(1).")
    print()
    cap = 2
    print(f"capacity = {cap}")
    print("op sequence (representative; mirrors the LRU contract):")
    print("  put 1,1 ; put 2,2 ; get 1 ; put 3,3 ; get 2 ; "
          "put 4,4 ; get 1 ; get 3 ; get 4")
    print()
    snaps = trace_lru(cap, LRU_OPS)
    print("Step trace  (order list is MRU -> LRU; first element = most recent):")
    print()
    print("  op          return  evict  DLL order (MRU..LRU)   key->val")
    print("  ----------  ------  -----  ---------------------  --------")
    for s in snaps:
        ret = "null" if s["ret"] is None else str(s["ret"])
        ev = "-" if s["evict"] is None else str(s["evict"])
        order = "[" + ", ".join(str(k) for k in s["order"]) + "]" or "[]"
        kv = ", ".join(f"{k}:{v}" for k, v in sorted(s["kv"].items())) or "(empty)"
        print(f"  {s['op']:<10}  {ret:<6}  {ev:<5}  {order:<21}  {kv}")
    print()
    print("Notes per step:")
    for s in snaps[1:]:
        print(f"  {s['op']:<10}  {s['note']}")
    print()
    c = LRUCache(cap)
    got = []
    for op in LRU_OPS:
        if op[0] == "put":
            c.put(op[1], op[2]); got.append(None)
        else:
            got.append(c.get(op[1]))
    expected_str = ", ".join("null" if x is None else str(x) for x in LRU_EXPECTED)
    got_str = ", ".join("null" if x is None else str(x) for x in got)
    print(f"returns     = [{got_str}]")
    print(f"expected    = [{expected_str}]")
    print(f"match: {got == LRU_EXPECTED}")
    print()


# ============================================================================
# SECTION D - complexity, killer gotchas, problem table
# ============================================================================
def section_d() -> None:
    print("=" * 76)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 76)
    print()
    print("Complexity")
    print("----------")
    print("  Operation                  LRU        LFU        Space")
    print("  -------------------------  ---------  ---------  ------")
    print("  get (hit)                  O(1)       O(1)       O(cap)")
    print("  get (miss)                 O(1)       O(1)       O(cap)")
    print("  put (new key, no evict)    O(1)       O(1)       O(cap)")
    print("  put (new key, evict)       O(1)       O(1)       O(cap)")
    print("  put (update existing)      O(1)       O(1)       O(cap)")
    print("  (all average; HashMap ops are O(1) amortized)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. DELETE EMPTY FREQUENCY BUCKETS in LFU. When bucket[f] empties")
    print("     after a bump, del freq_to_keys[f]. If you leave it, min_freq")
    print("     can point at an empty bucket and eviction looks up a victim")
    print("     that is not there -> KeyError / wrong eviction.")
    print("  2. UPDATE min_freq CORRECTLY on a bump: only when the emptied")
    print("     bucket was AT min_freq do you set min_freq = f + 1. If the")
    print("     emptied bucket was above min_freq, min_freq is unchanged.")
    print("  3. A NEW KEY ALWAYS RESETS min_freq = 1 (its frequency starts at")
    print("     1, so it is the new global minimum). Forgetting this is the")
    print("     classic 'works for a while then evicts the wrong key' bug.")
    print("  4. UPDATE != INSERT. put() on an existing key changes the value")
    print("     and bumps frequency / refreshes recency, but must NOT grow the")
    print("     size and must NOT evict. Guard `if key in map` BEFORE the")
    print("     capacity check.")
    print("  5. ZERO / NEGATIVE CAPACITY: handle `cap <= 0` at the top of put")
    print("     (and usually return -1 / no-op). LeetCode tests cap = 0.")
    print("  6. DLL SENTINELS: always use a dummy head and tail so _remove and")
    print("     _add_front never special-case an empty list. Update prev and")
    print("     nxt in the right order, or you will orphan a node.")
    print("  7. RECENCY WITHIN A FREQUENCY (the LFU tie-break): without an")
    print("     OrderedDict / DLL per bucket, two keys at the same min freq")
    print("     evict in an UNDEFINED order and your cache is non-deterministic.")
    print("  8. PYTHON ORDEREDDICT IS THE DLL: move_to_end, popitem(last=False)")
    print("     are O(1). For LRU you may use it directly; for LFU you need one")
    print("     per frequency bucket.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                       Diff   Key trick")
    print("  ----------------------------- ------  --------------------------------------")
    print("  P460 LFU Cache                Hard   3 dicts + min_freq; OrderedDict/bucket")
    print("                                       for O(1) LRU tie-break; del empty bucket")
    print("  P146 LRU Cache                Medium HashMap + DLL (or OrderedDict); evict")
    print("                                       tail.prev; splice-to-front on every touch")
    print("  P380 InsertDeleteGetRandom    Medium list + val->idx map; remove = swap+pop")
    print("  P355 Design Twitter           Medium heaps of (-timestamp, tweet) per followee")
    print("  P432 All O(1) Data Structure  Hard   freq buckets like LFU but with inc/dec")
    print("  P716 Max Stack                Hard   two stacks / DLL + sorted set for popMax")
    print("  P1146 Snapshot Array          Medium version-stamped writes; per-snap read")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions (all deterministic) ----
    # P460 LFU: LeetCode Example 1 exact return sequence
    lfu = LFUCache(2)
    got = []
    for op in LFU_OPS:
        if op[0] == "put":
            lfu.put(op[1], op[2]); got.append(None)
        else:
            got.append(lfu.get(op[1]))
    assert got == LFU_EXPECTED, (got, LFU_EXPECTED)

    # LFU tie-break determinism: among two freq-2 keys, evict the LRU one
    tb = LFUCache(2)
    tb.put(1, 1)       # freq{1:[1]}
    tb.put(2, 2)       # freq{1:[1,2]}
    tb.get(1)          # freq{1:[2], 2:[1]}
    tb.get(2)          # freq{2:[1,2]}
    tb.put(3, 3)       # full; min_freq=2; front of bucket2 is 1 -> evict 1
    assert 1 not in tb.key_to_val and 2 in tb.key_to_val and 3 in tb.key_to_val

    # LFU update-existing does not grow size, bumps freq
    up = LFUCache(2)
    up.put(1, 1)
    up.put(2, 2)
    up.put(1, 10)      # update existing -> size stays 2, freq(1)=2
    assert len(up.key_to_val) == 2
    assert up.key_to_val[1] == 10
    assert up.key_to_freq[1] == 2
    assert up.min_freq == 1            # key 2 still at freq 1

    # LFU zero capacity is a no-op
    z = LFUCache(0)
    z.put(1, 1)
    assert z.get(1) == -1

    # P146 LRU: representative sequence exact returns
    lru = LRUCache(2)
    got = []
    for op in LRU_OPS:
        if op[0] == "put":
            lru.put(op[1], op[2]); got.append(None)
        else:
            got.append(lru.get(op[1]))
    assert got == LRU_EXPECTED, (got, LRU_EXPECTED)

    # LRU get refreshes recency: get(1) then put(3) must evict 2, not 1
    r = LRUCache(2)
    r.put(1, 1)
    r.put(2, 2)
    assert r.get(1) == 1
    r.put(3, 3)        # evict LRU = 2
    assert r.get(2) == -1
    assert r.get(1) == 1
    assert r.get(3) == 3

    # LRU update-existing updates value + refreshes, no growth
    r2 = LRUCache(2)
    r2.put(1, 1)
    r2.put(2, 2)
    r2.put(1, 11)      # update 1 -> MRU
    assert len(r2.map) == 2
    assert r2.map[1].val == 11
    assert r2.order_mru_to_lru()[0] == 1
    r2.put(3, 3)       # evict LRU = 2
    assert r2.get(2) == -1
    assert r2.get(1) == 11

    # LRU zero capacity is a no-op
    zl = LRUCache(0)
    zl.put(1, 1)
    assert zl.get(1) == -1

    print("=" * 76)
    print("[check] LFU Cache / LRU Cache design + traces ... OK")
    print("=" * 76)
