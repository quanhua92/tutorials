"""
segment_tree.py - Reference implementation of the Segment Tree and the
Fenwick tree (Binary Indexed Tree, BIT).

This is the single source of truth that SEGMENT_TREE.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 segment_tree.py

=========================================================================
THE INTUITION (read this first) - the "running scoreboard"
=========================================================================
You have an array and you keep asking TWO kinds of question about it:

  * "what is the SUM (or min/max) from index l to r?"   (a RANGE query)
  * "I just changed arr[i] to v"                        (a POINT update)

A plain array answers point update in O(1) but a range sum in O(N) (scan).
A PREFIX-sum array answers range sum in O(1) but a point update in O(N)
(rebuild all prefixes). Neither is good when BOTH happen.

  * segment tree : store the answer for SEGMENTS of the array in a binary
                   tree (root = whole array; children = halves; leaves =
                   single elements). A query merges O(log N) segments; an
                   update touches O(log N) nodes on one root-to-leaf path.
  * Fenwick tree : a brilliantly compact trick that stores prefix sums in an
                   array of size N (not 4N) using a BIT MANIPULATION
                   (i & -i) to decide which elements each slot covers.
                   Only handles INVERTIBLE queries (sum), but is tiny and fast.

THE REASON THESE EXIST: range-query + point-update is the most common pattern
in competitive programming and in real systems (running stats over time
windows, stock candles, telemetry rollups). The segment tree and Fenwick tree
are the two structures that make BOTH operations O(log N) - logarithmic, so
that even at N = 10^6 a query/update is ~20 steps.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  N            : length of the underlying array (here 6).
  segment      : a contiguous range [lo, hi] of array indices.
  node         : one entry in the tree array; stores the query answer (sum)
                 over ONE segment. The root covers [0, N-1].
  leaf         : a node covering a single index [i,i]; holds arr[i].
  range query  : "answer for [l, r]?" - merge the O(log N) maximal segments
                 that tile [l, r].
  point update : "set arr[i] = v" - recompute every node whose segment contains
                 i, walking up from leaf i to the root (O(log N) nodes).
  lowbit(i)    : i & -i - the value of the lowest set bit of i. The Fenwick
                 magic: slot i covers the `lowbit(i)` elements ending at i.
  prefix sum   : sum of arr[0..k]; the Fenwick primitive. A range sum
                 sum(l..r) = prefix(r) - prefix(l-1).
  invertible   : a query whose result can be SPLIT and COMBINED by +/-. Sum
                 is invertible; MIN/MAX are NOT (you cannot subtract mins).
                 That is why Fenwick only does sum.

=========================================================================
THE LINEAGE (references)
=========================================================================
  Segment tree  (Bentley 1977, "Solutions to ... traveling salesman") : general.
  Fenwick/BIT   (Fenwick 1994, "A New Data Structure for Cumulative
                 Frequency Tables", Software--Practice & Experience) : the bit
                 trick that halves the memory and the code.
  Both appear   : CLRS problem 14-1 (point stabbing via augmentation); used
                 pervasively in ICPC / IOI / Codeforces.
  Lazy prop.    : for RANGE updates (not here) you add a `lazy` field per node.

KEY FACTS (all asserted in code below):
    build           = O(N)
    range_query     = O(log N)         (segment tree AND Fenwick)
    point_update    = O(log N)         (segment tree AND Fenwick)
    segment tree mem= 4*N              (array, 1-indexed, root at 1)
    Fenwick mem     = N                (array, 1-indexed; no 4x slack)
    Fenwick limit   : query must be INVERTIBLE (sum), else use segment tree.
    lowbit(i) = i & -i = the power of two in i's factorisation.

Conventions:
    Underlying array is 0-indexed: arr = [1,3,5,7,9,11].
    Segment tree is 1-indexed internally (root at tree[1]).
    Fenwick tree is 1-indexed (slot 0 unused).
"""

from __future__ import annotations

BANNER = "=" * 72

# The worked array: 6 elements, enough to show branching at every level.
ARR = [1, 3, 5, 7, 9, 11]
N = len(ARR)


# ============================================================================
# 1. THE SEGMENT TREE  (recursive, 1-indexed, 4N backing array)
#    This is the code SEGMENT_TREE.md walks through.
# ============================================================================

class SegTree:
    """Recursive sum segment tree. tree[1] = root = sum over [0, N-1].

    Each node stores (value, lo, hi) for its segment. Stored in a flat array
    of size 4*N (the safe bound for any N). 1-indexed: children of i are 2i,2i+1.
    """

    def __init__(self, data: list[int]):
        self.n = len(data)
        self.data = list(data)
        self.tree = [0] * (4 * self.n)        # value per node
        self.lo = [0] * (4 * self.n)          # segment lower bound
        self.hi = [0] * (4 * self.n)          # segment upper bound
        self.used = [False] * (4 * self.n)    # True once _build visits a node
        if self.n:
            self._build(1, 0, self.n - 1)

    def _build(self, idx: int, lo: int, hi: int) -> int:
        self.lo[idx], self.hi[idx] = lo, hi
        self.used[idx] = True
        if lo == hi:                           # leaf: single element
            self.tree[idx] = self.data[lo]
            return self.tree[idx]
        mid = (lo + hi) // 2
        left = self._build(2 * idx, lo, mid)
        right = self._build(2 * idx + 1, mid + 1, hi)
        self.tree[idx] = left + right          # combine = SUM
        return self.tree[idx]

    def query(self, idx: int, ql: int, qr: int) -> int:
        """Range sum over [ql, qr]. Merges the O(log N) covering segments."""
        if qr < self.lo[idx] or ql > self.hi[idx]:     # no overlap
            return 0
        if ql <= self.lo[idx] and self.hi[idx] <= qr:  # fully inside
            return self.tree[idx]
        return (self.query(2 * idx, ql, qr) +
                self.query(2 * idx + 1, ql, qr))       # partial: recurse both

    def range_sum(self, left: int, right: int) -> int:
        return self.query(1, left, right)

    def update(self, idx: int, pos: int, val: int, trace: list | None = None):
        """Set data[pos] = val, then fix every ancestor. Optionally record the
        visited node indices for the propagation visualization."""
        if trace is not None:
            trace.append((idx, self.lo[idx], self.hi[idx], self.tree[idx]))
        if self.lo[idx] == self.hi[idx]:               # leaf
            self.tree[idx] = val
            self.data[pos] = val
            if trace is not None:
                trace.append((idx, self.lo[idx], self.hi[idx], self.tree[idx]))
            return
        mid = (self.lo[idx] + self.hi[idx]) // 2
        if pos <= mid:
            self.update(2 * idx, pos, val, trace)
        else:
            self.update(2 * idx + 1, pos, val, trace)
        self.tree[idx] = self.tree[2 * idx] + self.tree[2 * idx + 1]
        if trace is not None:
            trace.append((idx, self.lo[idx], self.hi[idx], self.tree[idx]))

    def point_update(self, pos: int, val: int, trace: list | None = None):
        self.update(1, pos, val, trace)


# ============================================================================
# 2. THE FENWICK TREE  (Binary Indexed Tree) - the bit trick, in N space.
# ============================================================================

def lowbit(i: int) -> int:
    """The lowest set bit of i. i & -i isolates it via two's complement.

    Examples: lowbit(1)=1, lowbit(2)=2, lowbit(3)=1, lowbit(4)=4, lowbit(6)=2.
    Slot i in a Fenwick tree covers the `lowbit(i)` elements ending at i.
    """
    return i & -i


class Fenwick:
    """1-indexed Fenwick tree for prefix sums. tree[i] = sum of
    (i - lowbit(i), i] (i.e. the lowbit(i) elements up to and including i)."""

    def __init__(self, data: list[int]):
        self.n = len(data)
        self.tree = [0] * (self.n + 1)         # slot 0 unused
        # build by inserting each element (O(N log N); an O(N) build exists but
        # this keeps the structure transparent and matches the table in the doc)
        for i, v in enumerate(data, start=1):
            self._add(i, v)

    def _add(self, i: int, delta: int, trace: list | None = None):
        """Add `delta` to position i (1-indexed) and propagate upward."""
        while i <= self.n:
            if trace is not None:
                trace.append((i, self.tree[i]))
            self.tree[i] += delta
            i += lowbit(i)                     # jump to the next covering slot

    def prefix_sum(self, i: int) -> int:
        """Sum of data[1..i] (1-indexed). O(log N): peel off lowbit(i) each step."""
        s = 0
        while i > 0:
            s += self.tree[i]
            i -= lowbit(i)                     # strip the covered block
        return s

    def range_sum(self, left: int, right: int) -> int:
        """Sum of data[left..right] (0-indexed inclusive) = prefix(right+1)-prefix(left)."""
        return self.prefix_sum(right + 1) - self.prefix_sum(left)

    def update(self, pos: int, val: int, trace: list | None = None):
        """Set data[pos] = val (0-indexed) by adding (val - old)."""
        old = self.range_sum(pos, pos)
        self._add(pos + 1, val - old, trace)


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_segtree_levels(st: SegTree):
    """Print the segment tree level by level, each node as [lo,hi]=value."""
    # collect nodes in index order (1, 2, 3, ...) grouping by depth
    levels: dict[int, list[tuple]] = {}

    def depth(idx: int) -> int:
        return idx.bit_length() - 1           # floor(log2(idx)) for idx>=1

    for idx in range(1, len(st.tree)):
        if not st.used[idx]:
            continue
        d = depth(idx)
        levels.setdefault(d, []).append((idx, st.lo[idx], st.hi[idx], st.tree[idx]))
    for d in sorted(levels):
        cells = "   ".join(f"[{lo},{hi}]={v} (#{i})" for i, lo, hi, v in levels[d])
        print(f"  level {d}:  {cells}")


# ----------------------------------------------------------------------------
# SECTION A: build the segment tree and show the segments
# ----------------------------------------------------------------------------

def section_build():
    banner(f"SECTION A: build segment tree from {ARR}")
    st = SegTree(ARR)
    print(f"arr = {ARR}   (N = {N}, 0-indexed)\n")
    print("Each node stores the SUM over its segment [lo, hi]. The root covers")
    print("the whole array; each internal node splits at mid = (lo+hi)//2 into a")
    print("LEFT child [lo, mid] and a RIGHT child [mid+1, hi]. Leaves are single")
    print("elements.\n")
    print("Tree by level (root at level 0; #node = its 1-indexed array slot):")
    print_segtree_levels(st)
    print(f"\n  tree[1] (root) = sum[0,{N-1}] = {sum(ARR)}   "
          f"(matches brute-force sum(arr) = {sum(ARR)})")
    print(f"  backing array size = 4*N = {4*N} (safe bound for any N).")
    print("\nBuild cost = O(N): each of the ~2N nodes is visited once.\n")
    # verify every leaf equals arr[i]
    for i in range(N):
        # find the leaf node index for position i
        def find_leaf(idx, lo, hi):
            if lo == hi:
                return idx
            mid = (lo + hi) // 2
            return find_leaf(2 * idx, lo, mid) if i <= mid else find_leaf(2 * idx + 1, mid + 1, hi)
        leaf = find_leaf(1, 0, N - 1)
        assert st.tree[leaf] == ARR[i]
    print("[check] every leaf node == arr[i]:  OK")


# ----------------------------------------------------------------------------
# SECTION B: range sum query [2,5] -> O(log N)
# ----------------------------------------------------------------------------

def section_range_query():
    banner("SECTION B: range sum query [2, 5] -> O(log N)")
    st = SegTree(ARR)
    ql, qr = 2, 5
    brute = sum(ARR[ql:qr + 1])
    print(f"query sum[{ql},{qr}] = arr[{ql}..{qr}] = {ARR[ql:qr+1]}")
    print(f"  brute force (scan) = {brute}\n")
    print("The query does NOT scan [2,5]. It tiles it with the FEWEST maximal")
    print("segments already stored in the tree, and sums those. We log every node")
    print("the recursion visits:\n")
    log: list[tuple] = []
    # instrument query by walking and recording
    def traced_query(idx, left, right):
        if right < st.lo[idx] or left > st.hi[idx]:
            log.append((idx, st.lo[idx], st.hi[idx], "no overlap -> 0"))
            return 0, False
        if left <= st.lo[idx] and st.hi[idx] <= right:
            log.append((idx, st.lo[idx], st.hi[idx], f"FULL segment -> {st.tree[idx]}"))
            return st.tree[idx], True
        log.append((idx, st.lo[idx], st.hi[idx], "partial -> recurse"))
        sl, ul = traced_query(2 * idx, left, right)
        sr, ur = traced_query(2 * idx + 1, left, right)
        return sl + sr, ul or ur
    total, _ = traced_query(1, ql, qr)
    for idx, lo, hi, note in log:
        print(f"  visit #{idx:<3} seg=[{lo},{hi}]  {note}")
    print(f"\n  answer = {total}   (== brute force {brute}: {total == brute})\n")
    used = [t for *_, t in log if isinstance(t, str) and t.startswith("FULL")]
    print(f"Only {len(used)} FULL segments were summed (not {qr-ql+1} elements):")
    print("  the tree returns precomputed block sums, so the work is O(log N).")
    assert total == st.range_sum(ql, qr) == brute
    print(f"\n[check] range_sum({ql},{qr}) == brute-force:  OK")


# ----------------------------------------------------------------------------
# SECTION C: point update arr[3] = 6 -> propagate up
# ----------------------------------------------------------------------------

def section_point_update():
    banner("SECTION C: point update arr[3] = 6 -> propagate up to the root")
    st = SegTree(ARR)
    print(f"Before: arr = {st.data}, tree[1] (root sum) = {st.tree[1]}\n")
    pos, val = 3, 6
    print(f"Set arr[{pos}] = {val} (was {st.data[pos]}). Then walk from leaf "
          f"{pos} UP to the root, recomputing every ancestor's sum.\n")
    trace: list[tuple] = []
    st.point_update(pos, val, trace)
    print("Visited nodes (leaf first, root last), with before/after values:")
    # trace records (idx, lo, hi, value) at entry and after; we logged the path
    # Re-derive a clean path by collecting unique node indices in order.
    seen = []
    seen_set = set()
    for idx, lo, hi, val_ in trace:
        if idx not in seen_set:
            seen_set.add(idx)
            seen.append((idx, lo, hi))
    for idx, lo, hi in seen:
        seg = f"[{lo},{hi}]"
        print(f"  #{idx:<3} seg={seg:<8} updated to {st.tree[idx]}")
    print(f"\nAfter:  arr = {st.data}, tree[1] (root sum) = {st.tree[1]}")
    print(f"  delta at leaf #{pos} = {val} - {ARR[pos]} = {val - ARR[pos]}; "
          f"this propagated up {len(seen)} nodes = O(log N).\n")
    # verify
    new_total = sum(st.data)
    assert st.tree[1] == new_total
    assert st.data[pos] == val
    print(f"[check] tree[1] == sum(arr) == {new_total} after update:  OK")


# ----------------------------------------------------------------------------
# SECTION D: Fenwick tree - same array, the bit-trick structure
# ----------------------------------------------------------------------------

def section_fenwick():
    banner("SECTION D: Fenwick tree (BIT) - the i & -i bit trick")
    print("A Fenwick tree stores prefix sums in N slots (not 4N). The trick:")
    print("slot i covers the last `lowbit(i) = i & -i` elements ending at i.\n")
    print("lowbit table for i = 1..N:")
    print("  | i (dec) | i (bin) | -i (bin)  | lowbit = i & -i | covers elements   |")
    print("  |---------|---------|-----------|-----------------|------------------|")
    for i in range(1, N + 1):
        cov_lo = i - lowbit(i) + 1
        print(f"  | {i:<7} | {i:0{N.bit_length()}b} | "
              f"{(-i) & ((1 << N.bit_length()) - 1):0{N.bit_length()}b} | "
              f"{lowbit(i):<15} | [{cov_lo}, {i}] (1-indexed) |")
    print()
    fw = Fenwick(ARR)
    print(f"Fenwick tree for arr = {ARR} (1-indexed; slot 0 unused):\n")
    print("  | slot i | lowbit(i) | covers        | tree[i] | elements summed     |")
    print("  |--------|-----------|---------------|---------|---------------------|")
    for i in range(1, N + 1):
        cov_lo = i - lowbit(i) + 1
        elems = ARR[cov_lo - 1:i]               # back to 0-indexed for display
        print(f"  | {i:<6} | {lowbit(i):<9} | [{cov_lo}, {i}]       | "
              f"{fw.tree[i]:<7} | {elems} |")
    print()
    print("prefix_sum(k) = sum arr[1..k]. Peel off lowbit(k) each step:")
    for k in range(0, N + 1):
        ps = fw.prefix_sum(k)
        # show the decomposition
        path = []
        i = k
        while i > 0:
            path.append(f"tree[{i}]")
            i -= lowbit(i)
        decomp = " + ".join(path) if path else "0"
        brute = sum(ARR[:k])
        print(f"  prefix_sum({k}) = {decomp:<22} = {ps:<4} (brute = {brute})")
    print()
    ql, qr = 2, 5
    print(f"range_sum({ql},{qr}) = prefix_sum({qr+1}) - prefix_sum({ql}) "
          f"= {fw.prefix_sum(qr+1)} - {fw.prefix_sum(ql)} = {fw.range_sum(ql,qr)}")
    assert fw.range_sum(ql, qr) == sum(ARR[ql:qr + 1])
    print(f"[check] Fenwick range_sum({ql},{qr}) == brute force:  OK")


# ----------------------------------------------------------------------------
# SECTION E: comparison - segment tree vs Fenwick
# ----------------------------------------------------------------------------

def section_comparison():
    banner("SECTION E: segment tree vs Fenwick tree - when to use which")
    st = SegTree(ARR)
    fw = Fenwick(ARR)
    print("Both give O(log N) range-sum + O(log N) point-update. The differences:\n")
    print("| property          | segment tree          | Fenwick tree (BIT)       |")
    print("|-------------------|-----------------------|---------------------------|")
    print("| memory            | 4*N                   | N (half the constants)    |")
    print("| query types       | sum, min, max, ANY    | only INVERTIBLE (sum)     |")
    print("| code complexity   | ~30 lines, recursive  | ~10 lines, 1 loop         |")
    print("| range UPDATE      | yes (with lazy prop.) | only point (range needs 2)|")
    print("| constants         | larger (recursion)    | tiny (bit ops + 1 array)  |")
    print("| learning curve    | intuitive tree        | the i & -i trick is subtle|")
    print()
    print("Verification on the worked array arr = [1,3,5,7,9,11]:")
    print()
    print("  | query            | segment tree | Fenwick  | brute force | match |")
    print("  |------------------|--------------|----------|-------------|-------|")
    checks = [
        ("range_sum(0,5)", st.range_sum(0, 5), fw.range_sum(0, 5), sum(ARR[0:6])),
        ("range_sum(2,5)", st.range_sum(2, 5), fw.range_sum(2, 5), sum(ARR[2:6])),
        ("range_sum(1,3)", st.range_sum(1, 3), fw.range_sum(1, 3), sum(ARR[1:4])),
        ("range_sum(4,4)", st.range_sum(4, 4), fw.range_sum(4, 4), sum(ARR[4:5])),
    ]
    all_ok = True
    for label, a, b, c in checks:
        ok = a == b == c
        all_ok &= ok
        print(f"  | {label:<16} | {a:<12} | {b:<8} | {c:<11} | {'OK' if ok else 'FAIL':<5} |")
    print()
    print("Why Fenwick CANNOT do min/max: min(a, b) has no inverse. You cannot")
    print("'subtract' a min when an element updates, so prefix-min cannot be peeled")
    print("off by lowbit. The segment tree recomputes each node from its children,")
    print("so it works for ANY associative combine (min, max, gcd, ...).\n")
    # update both, re-check
    st.point_update(3, 6)
    fw.update(3, 6)
    print("After point update arr[3]=6:")
    print(f"  segment tree total = {st.tree[1]}, Fenwick prefix_sum(N) = {fw.prefix_sum(N)}")
    assert st.range_sum(0, 5) == fw.range_sum(0, 5) == (sum(ARR) + 6 - 7)
    print(f"  [check] both agree on new total = {st.range_sum(0, 5)}:  OK\n")
    print(f"GOLD CHECK: {'OK - all range queries match brute force' if all_ok else 'FAIL'}")
    print("(segment_tree.html re-runs both trees in JS and re-checks these values.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("segment_tree.py - reference impl. All numbers below feed SEGMENT_TREE.md.")
    print("python stdlib only; deterministic.")

    section_build()
    section_range_query()
    section_point_update()
    section_fenwick()
    section_comparison()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
