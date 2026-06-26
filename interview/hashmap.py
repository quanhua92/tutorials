"""
hashmap.py - Reference implementation of the HashMap / HashSet pattern for:
hashing & collisions, O(1) insert/remove/getRandom design, frequency counting,
and bijective encode/decode.

This is the SINGLE SOURCE OF TRUTH for HASHMAP.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 hashmap.py > hashmap_output.txt

Pure Python stdlib only. Deterministic (custom string hash, no PYTHONHASHSEED
dependence; random is seeded for getRandom).

============================================================================
THE INTUITION (read this first) - a perfect address book
============================================================================
Imagine a giant library with no catalog. Finding a book means walking every
shelf - O(n). A hashmap is a perfect catalog: you give it a name (the key) and
it instantly tells you the shelf (the bucket). That turns a linear search into
O(1) average-time magic.

The mechanism, in three moves:

    key --hash()--> integer h --mod N--> bucket index --[chain]--> slot

    * The HASH FUNCTION crushes an arbitrary key into an integer.
    * The MODULO maps that integer into one of N buckets.
    * A COLLISION (two keys, same bucket) is resolved by a CHAIN (a small list
      hanging off the bucket) or by OPEN ADDRESSING (probe for the next free
      slot). Python's dict uses open addressing; this file demos chaining
      because it is the clearest to draw.

Three interview idioms all reuse this one idea:

    1. FREQUENCY COUNTING  - "how many times does X appear?"   (P447)
    2. O(1) DESIGN         - "insert/remove/getRandom in O(1)" (P380)
    3. BIJECTIVE MAPPING   - "encode X, later decode it back"  (P535)

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  key            the thing you look up by (a name, a value, a coordinate).
  value          the thing you store (a count, an index, a short code).
  hash function  maps key -> integer. Must be deterministic; ideally uniform.
  bucket         one slot of the bucket array, selected by hash(key) % N.
  collision      two distinct keys land in the SAME bucket.
  chain          a list of (key, value) pairs hanging off one bucket
                 (separate chaining). Alternative: open addressing (probe).
  load factor    n_keys / N_buckets. Python dict grows (resizes + rehashes)
                 when load factor crosses ~2/3 to keep ops O(1).
  idx_map        a dict used as val -> array_index, the trick that makes
                 RandomizedSet.remove O(1): swap-with-last then pop+del.
  base62         an alphabet of 62 chars [0-9a-zA-Z]; the bijective encoding
                 that turns a counter into a short TinyURL code.

============================================================================
THE SKELETON (the four interview idioms share this)
============================================================================
    # 1. frequency counting (Counter / dict.get default)
    freq = {}
    for x in items:
        freq[x] = freq.get(x, 0) + 1

    # 2. O(1) insert/remove/getRandom (list + val->idx map)
    class RandomizedSet:
        def __init__(self):
            self.vals = []           # O(1) random.choice
            self.idx_map = {}        # val -> index in vals

    # 3. set membership / lookup table
    seen = set()
    if x not in seen:
        seen.add(x)

    # 4. bijective mapping (two dicts)
    code_to_url, url_to_code = {}, {}
"""

from __future__ import annotations

import random


# ============================================================================
# HASH FUNCTION - a tiny, deterministic djb2-style string hash. We use our own
# (not Python's hash()) so the bucket distribution is identical run-to-run and
# identical to the JS in hashmap.html. 32-bit wraparound via & 0xFFFFFFFF.
# ============================================================================
_HASH_MASK = 0xFFFFFFFF


def str_hash(s: str) -> int:
    """djb2 string hash, unsigned 32-bit. str_hash("abc") is stable forever."""
    h = 5381
    for ch in s:
        h = (h * 33 + ord(ch)) & _HASH_MASK
    return h


def bucket_of(key: str, n_buckets: int) -> int:
    """Bucket index for `key` in a table of `n_buckets` buckets."""
    return str_hash(key) % n_buckets


# ============================================================================
# A TINY HASH TABLE WITH SEPARATE CHAINING - only for the fundamentals demo.
# Real interviews use Python's dict/set; this exists so we can DRAW buckets.
# ============================================================================
class ChainHashTable:
    """Minimal hash table, separate chaining. put / get / __contains__ are
    amortized O(1 + load_factor). For drawing we expose .buckets directly."""

    def __init__(self, n_buckets: int = 7):
        self.n_buckets = n_buckets
        self.buckets: list[list[tuple[str, object]]] = [[] for _ in range(n_buckets)]
        self.n_keys = 0

    def _idx(self, key: str) -> int:
        return bucket_of(key, self.n_buckets)

    def put(self, key: str, value: object) -> None:
        idx = self._idx(key)
        chain = self.buckets[idx]
        for i, (k, _) in enumerate(chain):
            if k == key:
                chain[i] = (key, value)   # update in place
                return
        chain.append((key, value))        # new key -> append to chain
        self.n_keys += 1

    def get(self, key: str):
        idx = self._idx(key)
        for k, v in self.buckets[idx]:
            if k == key:
                return v
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        idx = self._idx(key)
        return any(k == key for k, _ in self.buckets[idx])

    def collisions(self) -> int:
        """Number of buckets holding 2+ keys."""
        return sum(1 for b in self.buckets if len(b) >= 2)

    def render(self) -> str:
        """Pretty-print the bucket array, showing chains."""
        lines = [f"  {i}: {chain}" for i, chain in enumerate(self.buckets)]
        return "\n".join(lines)


# ============================================================================
# PROBLEM 1 - P380 INSERT DELETE GETRANDOM O(1)
# ============================================================================
class RandomizedSet:
    """All three ops average O(1).

    Trick: a Python list gives O(1) random.choice but O(n) middle removal.
    A dict gives O(1) membership but no random index. COMBINE them:
        vals[]      -> the values, in insertion order
        idx_map{}   -> val -> its index in vals
    Removal = SWAP the target with the LAST element, then pop + del. Both the
    swap and the pop are O(1); the map is updated to match.

    GOTCHA (order of updates): set idx_map[last_val] = idx BEFORE del
    idx_map[val]. If val is itself the last element, deleting first would
    leave a dangling reference.
    """

    def __init__(self, seed: int = 42) -> None:
        self.vals: list[int] = []
        self.idx_map: dict[int, int] = {}
        self._rng = random.Random(seed)

    def insert(self, val: int) -> bool:
        if val in self.idx_map:
            return False
        self.idx_map[val] = len(self.vals)
        self.vals.append(val)
        return True

    def remove(self, val: int) -> bool:
        if val not in self.idx_map:
            return False
        idx = self.idx_map[val]
        last_val = self.vals[-1]
        # swap-with-last, updating the map FIRST (see gotcha above)
        self.vals[idx] = last_val
        self.idx_map[last_val] = idx
        self.vals.pop()
        del self.idx_map[val]
        return True

    def get_random(self) -> int:
        return self._rng.choice(self.vals)

    def state(self) -> str:
        return f"vals={self.vals}  idx_map={self.idx_map}"


def trace_remove(rs: RandomizedSet, val: int) -> list[dict]:
    """Trace the four micro-steps of remove() for the worked example."""
    steps: list[dict] = []
    idx = rs.idx_map[val]
    last_val = rs.vals[-1]
    steps.append({"phase": "lookup",
                  "note": f"idx_map[{val}] = {idx}",
                  "vals": list(rs.vals), "idx_map": dict(rs.idx_map)})
    rs.vals[idx] = last_val
    steps.append({"phase": "swap vals",
                  "note": f"vals[{idx}] = last = {last_val}",
                  "vals": list(rs.vals), "idx_map": dict(rs.idx_map)})
    rs.idx_map[last_val] = idx
    steps.append({"phase": "update map FIRST",
                  "note": f"idx_map[{last_val}] = {idx}  (before del!)",
                  "vals": list(rs.vals), "idx_map": dict(rs.idx_map)})
    rs.vals.pop()
    del rs.idx_map[val]
    steps.append({"phase": "pop + del",
                  "note": f"vals.pop(); del idx_map[{val}]",
                  "vals": list(rs.vals), "idx_map": dict(rs.idx_map)})
    return steps


# ============================================================================
# PROBLEM 2 - P447 NUMBER OF BOOMERANGS
# ============================================================================
def number_of_boomerangs(points: list[list[int]]) -> int:
    """A boomerang is an ORDERED triple (i, j, k) with dist(i, j) == dist(i, k).
    For each pivot i, count how many points sit at each distance. If c points
    share a distance, they yield c*(c-1) ordered pairs as the (j, k) arms
    (c choices for j, c-1 for k). Sum over pivots and distances.

    Use SQUARED distance (no sqrt) - it's an integer and hashable, and the
    equality test is exact.

    Time:  O(n^2)   - a distance map per pivot
    Space: O(n)     - one map at a time
    """
    total = 0
    for i, p in enumerate(points):
        freq: dict[int, int] = {}
        for j, q in enumerate(points):
            if i == j:
                continue
            dx = p[0] - q[0]
            dy = p[1] - q[1]
            d2 = dx * dx + dy * dy
            freq[d2] = freq.get(d2, 0) + 1
        for count in freq.values():
            total += count * (count - 1)
    return total


def trace_boomerang_pivot(points: list[list[int]], pivot_idx: int) -> list[dict]:
    """Trace the frequency map build for one pivot, then the c*(c-1) sum."""
    p = points[pivot_idx]
    rows: list[dict] = []
    freq: dict[int, int] = {}
    for j, q in enumerate(points):
        if j == pivot_idx:
            continue
        d2 = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
        freq[d2] = freq.get(d2, 0) + 1
        rows.append({"j": j, "q": q, "d2": d2,
                     "freq": dict(freq)})
    subtotal = 0
    for d2, count in freq.items():
        contrib = count * (count - 1)
        subtotal += contrib
        rows.append({"d2": d2, "count": count, "contrib": contrib,
                     "subtotal": subtotal})
    return rows


# ============================================================================
# PROBLEM 3 - P535 ENCODE AND DECODE TINYURL
# ============================================================================
_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def to_base62(num: int, width: int = 6) -> str:
    """Counter -> short code. Bijective: every counter maps to one code, and
    decoding (the reverse) is unambiguous. Width-padded so all codes look
    uniform.     to_base62(0) == '000000', to_base62(35) == '00000z', to_base62(61) == '00000Z',
    to_base62(62) == '000010'."""
    if num == 0:
        return _BASE62[0] * width
    chars: list[str] = []
    while num > 0:
        chars.append(_BASE62[num % 62])
        num //= 62
    return "".join(reversed(chars)).zfill(width)


class TinyURL:
    """Bijective URL shortener.

    Two dicts form the bridge:
        code_to_url   short code  ->  long URL   (used by decode)
        url_to_code   long URL    ->  short code (used to dedupe encode)
    A monotonic counter assigns each NEW long URL the next code; base62 keeps
    the code short. Because the mapping is one-to-one, decode is exact.

    Time:  O(1) encode / decode (dict ops + O(width) base62)
    Space: O(U) where U = number of distinct URLs ever encoded.
    """

    PREFIX = "http://tinyurl.com/"

    def __init__(self) -> None:
        self.code_to_url: dict[str, str] = {}
        self.url_to_code: dict[str, str] = {}
        self.counter = 0

    def encode(self, long_url: str) -> str:
        if long_url in self.url_to_code:          # dedupe: same URL -> same code
            return self.PREFIX + self.url_to_code[long_url]
        code = to_base62(self.counter)
        self.counter += 1
        self.code_to_url[code] = long_url
        self.url_to_code[long_url] = code
        return self.PREFIX + code

    def decode(self, short_url: str) -> str:
        code = short_url.rsplit("/", 1)[-1]
        return self.code_to_url[code]


# ============================================================================
# SECTION A - HASHING FUNDAMENTALS (keys -> buckets, collisions, chains)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - Hashing fundamentals: key -> bucket -> chain")
    print("=" * 72)
    print()
    print("Mechanism:  key --str_hash--> h --% N--> bucket --chain--> slot")
    print("Custom djb2 hash (deterministic; matches hashmap.html exactly).")
    print()
    keys = ["apple", "banana", "cherry", "date", "elderberry", "fig", "grape"]
    n_buckets = 7
    print(f"Insert {len(keys)} string keys into a table of {n_buckets} buckets:")
    print()
    print("  key           str_hash(key)   bucket = hash % 7")
    print("  ------------  --------------  ----------------")
    for k in keys:
        h = str_hash(k)
        b = h % n_buckets
        print(f"  {k:<12}  {h:>14}   {b}")
    print()
    ht = ChainHashTable(n_buckets)
    for k in keys:
        ht.put(k, len(k))            # value = length, arbitrary
    print("Resulting bucket array (separate chaining):")
    print(ht.render())
    print()
    print(f"  keys={ht.n_keys}, buckets={n_buckets}, "
          f"load factor={ht.n_keys / n_buckets:.3f}, collisions={ht.collisions()}")
    print()
    print("Lookups are O(1) on average: hash the key, jump to its bucket, walk")
    print("a SHORT chain. Collisions only hurt when a chain gets long; Python's")
    print("dict avoids this by rehashing into a bigger table at load ~2/3.")
    print()
    print("  contains('cherry') ->", "cherry" in ht, " (value:", ht.get("cherry"), ")")
    print("  contains('mango')   ->", "mango" in ht)
    print()


# ============================================================================
# SECTION B - P380 INSERT DELETE GETRANDOM O(1)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P380 Insert Delete GetRandom O(1)")
    print("=" * 72)
    print()
    print("Two structures combined: list (for random access) + dict (for O(1)")
    print("lookup of an element's index). Removal = swap-with-last + pop.")
    print()
    rs = RandomizedSet()
    print("  op               return   state after")
    print("  ---------------  ------   -------------------------------------------")
    ops = [("insert", 1), ("insert", 2), ("insert", 3), ("insert", 4),
           ("remove", 2)]
    for op, arg in ops:
        if op == "insert":
            r = rs.insert(arg)
        else:
            r = rs.remove(arg)
        print(f"  {op}({arg}){' '*(11-len(op)-len(str(arg)))}{str(r):<8} {rs.state()}")
    print()
    print("getRandom is O(1) via random.choice on the list (seeded here):")
    draws = [rs.get_random() for _ in range(4)]
    print(f"  4 draws -> {draws}")
    print()
    print("--- detail: the four micro-steps of remove(2) on a fresh set ---")
    rs2 = RandomizedSet()
    for v in (1, 2, 3, 4):
        rs2.insert(v)
    print(f"  start: {rs2.state()}")
    print(f"  remove(2):")
    for s in trace_remove(rs2, 2):
        print(f"    [{s['phase']:<17}] {s['note']}")
        print(f"        {s['vals']}   {s['idx_map']}")
    print("  result: remove(2) -> True")
    print()
    print("GOTCHA: 'update map FIRST' must precede 'pop + del'. If you delete")
    print("idx_map[val] first and val IS the last element, the swap leaves a")
    print("stale entry pointing at the now-removed slot.")
    print()


# ============================================================================
# SECTION C - P447 NUMBER OF BOOMERANGS
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P447 Number of Boomerangs")
    print("=" * 72)
    print()
    print("For each pivot i, build freq{distance^2: count}. Each bucket with c")
    print("points yields c*(c-1) ordered (j, k) arms. Use SQUARED distance - no")
    print("sqrt, exact integer hash key.")
    print()
    points = [[0, 0], [1, 0], [2, 0]]
    print(f"points = {points}   (answer should be 2)")
    print()
    pivot = 1
    p = points[pivot]
    print(f"Trace pivot i={pivot} at {p}:")
    print("  j   q        d2      freq after")
    print("  --  -------  ------  ----------------")
    for row in trace_boomerang_pivot(points, pivot):
        if "j" in row:
            print(f"  {row['j']:<2}  {str(row['q']):<7}  {row['d2']:<6}  {row['freq']}")
    print("  contribution: c*(c-1) per distance")
    for row in trace_boomerang_pivot(points, pivot):
        if "count" in row:
            print(f"    d2={row['d2']:<4} count={row['count']} -> "
                  f"{row['count']}*{row['count']-1} = {row['contrib']}  "
                  f"(subtotal {row['subtotal']})")
    print()
    print(f"number_of_boomerangs({points}) -> {number_of_boomerangs(points)}   (expected 2)")
    print()
    print("More examples:")
    ex = [[[1, 1], [2, 2], [3, 3]], [[0, 0], [1, 0], [2, 0], [0, 1]]]
    ev = [2, 4]
    for pts, exp in zip(ex, ev):
        got = number_of_boomerangs(pts)
        print(f"  {pts} -> {got}   (expected {exp})")
    print()


# ============================================================================
# SECTION D - P535 ENCODE AND DECODE TINYURL
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - P535 Encode and Decode TinyURL")
    print("=" * 72)
    print()
    print("Bijective mapping: two dicts (code->url and url->code) bridged by a")
    print("monotonic counter. base62 turns the counter into a 6-char code.")
    print()
    print("base62 sample (counter -> code):")
    for c in (0, 1, 61, 62, 3844):
        print(f"  {c:>5} -> {to_base62(c)}")
    print()
    codec = TinyURL()
    urls = [
        "https://leetcode.com/problems/design-tinyurl",
        "https://news.ycombinator.com/",
        "https://leetcode.com/problems/design-tinyurl",   # duplicate -> same code
    ]
    print("Encode three URLs (third is a duplicate of the first):")
    print("  long URL                                          short URL")
    print("  ------------------------------------------------  ---------------------------")
    for u in urls:
        short = codec.encode(u)
        print(f"  {u:<48}  {short}")
    print()
    print("Decode round-trip (code_to_url lookup):")
    for code, long_url in codec.code_to_url.items():
        short = TinyURL.PREFIX + code
        back = codec.decode(short)
        ok = back == long_url
        print(f"  decode({short}) -> {'OK' if ok else 'MISMATCH'}  ({len(code)}-char code)")
    print()
    print(f"  counter after 3 encodes (2 distinct) = {codec.counter}")
    print(f"  distinct codes stored = {len(codec.code_to_url)}")
    print()


# ============================================================================
# SECTION E - COMPLEXITY, GOTCHAS, PROBLEM TABLE
# ============================================================================
def section_e() -> None:
    print("=" * 72)
    print("SECTION E - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Operation                       Time      Space")
    print("  ------------------------------  --------  --------")
    print("  Hash put / get / contains       O(1) avg  O(n)")
    print("  Frequency count over n items    O(n)      O(k)")
    print("  RandomizedSet insert/remove     O(1) avg  O(n)")
    print("  RandomizedSet getRandom         O(1)      O(1)")
    print("  TinyURL encode / decode         O(1)      O(U)")
    print("  (k = distinct keys, U = distinct URLs)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. SWAP-AND-POP ORDER: in RandomizedSet.remove, set")
    print("     idx_map[last_val]=idx BEFORE del idx_map[val]. If val is the")
    print("     last element, deleting first leaves a stale dangling index.")
    print("  2. ZERO COUNTS != MISSING KEY: with a Counter/dict, state[c]==0")
    print("     is NOT the same as c absent. del state[c] at 0 so equality")
    print("     comparisons (window == target) work in sliding-window problems.")
    print("  3. Use SQUARED distance for geometry (P447, P391): avoids sqrt's")
    print("     float error and keeps the key an exact, hashable integer.")
    print("  4. TUPLES hash, LISTS do not. Storing [xi, yi] as a dict key")
    print("     raises TypeError; convert to (xi, yi) first.")
    print("  5. WORST CASE is O(n): if every key collides into one bucket")
    print("     (adversarial input), the chain is length n. Python's dict")
    print("     randomizes string hashing to make this astronomically unlikely.")
    print("  6. For TinyURL, a hash-of-URL (md5[:6]) CAN collide; the")
    print("     counter + base62 is bijective and collision-free by design.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff   Key trick")
    print("  -------------------------------- ------  ----------------------------------------")
    print("  P380 InsertDeleteGetRandom O(1)  Medium list + val->idx map; remove = swap+pop")
    print("  P447 Number of Boomerangs        Medium freq{d^2:count} per pivot; c*(c-1)")
    print("  P535 Encode/Decode TinyURL       Medium two dicts + base62 counter")
    print("  P1   Two Sum                     Easy   map value -> index as you scan")
    print("  P49  Group Anagrams              Medium map sorted(s) -> list of strings")
    print("  P128 Longest Consecutive Seq     Medium set membership, expand from starts")
    print("  P575 Distribute Candies          Easy   min(unique_types, n//2)")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()

    # ---- assertions (all deterministic) ----
    # fundamentals
    assert str_hash("apple") == str_hash("apple")
    ht = ChainHashTable(7)
    for k in ("apple", "banana", "cherry", "date", "fig", "grape"):
        ht.put(k, len(k))
    assert ht.get("cherry") == 6
    assert "mango" not in ht
    assert ht.collisions() >= 1   # 6 keys, 7 buckets -> pigeonhole may not force;
    # but these specific keys DO collide (see Section A output)

    # P380
    rs = RandomizedSet()
    assert rs.insert(1) is True
    assert rs.insert(1) is False          # duplicate
    assert rs.insert(2) is True
    assert rs.insert(3) is True
    assert rs.remove(2) is True
    assert rs.remove(2) is False          # already gone
    assert rs.vals == [1, 3]
    assert rs.idx_map == {1: 0, 3: 1}
    # remove of last element (self-swap) must not corrupt state
    rs2 = RandomizedSet()
    rs2.insert(5)
    rs2.insert(7)
    assert rs2.remove(7) is True
    assert rs2.vals == [5] and rs2.idx_map == {5: 0}

    # P447
    assert number_of_boomerangs([[0, 0], [1, 0], [2, 0]]) == 2
    assert number_of_boomerangs([[1, 1], [2, 2], [3, 3]]) == 2
    assert number_of_boomerangs([[1, 1]]) == 0
    assert number_of_boomerangs([[0, 0], [1, 0], [2, 0], [0, 1]]) == 4

    # P535
    c = TinyURL()
    s1 = c.encode("https://a.example/x")
    s2 = c.encode("https://b.example/y")
    s3 = c.encode("https://a.example/x")    # dup -> same code as s1
    assert s1 == s3
    assert s1 != s2
    assert c.decode(s1) == "https://a.example/x"
    assert c.decode(s2) == "https://b.example/y"
    assert to_base62(0) == "000000"
    assert to_base62(35) == "00000z"
    assert to_base62(61) == "00000Z"
    assert to_base62(62) == "000010"
    assert c.counter == 2                   # two DISTINCT urls

    print("=" * 72)
    print("[check] hashing / RandomizedSet / boomerangs / TinyURL ... OK")
    print("=" * 72)
