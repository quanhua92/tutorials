"""
merge_sort.py - Reference implementation of Merge Sort, the stable
divide-and-conquer sort.

This is the single source of truth that MERGE_SORT.md is built from. Every
number, table, and worked example in MERGE_SORT.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python merge_sort.py

=========================================================================
THE INTUITION (read this first) -- two sorted piles of cards
=========================================================================
You have a shuffled deck of n cards. To sort it:

  1. CUT the deck exactly in half. Recursively sort each half. (A one-card
     "half" is already sorted -- that is the base case.)
  2. MERGE the two sorted halves into one: look at the top card of each pile,
     take the SMALLER, put it down. Repeat until both piles are empty.

That is the whole algorithm. The magic is that MERGING two already-sorted
piles is LINEAR (O(n)) -- you never compare a card to more than one other
card per output. And because you halve the deck log2(n) times, you do that
linear merge log2(n) times: O(n log n) total.

Contrast with selection_sort (🔗 SELECTION_SORT.md): selection makes the
fewest SWAPS but Theta(n^2) COMPARISONS because it re-scans the whole tail
every pass. Merge sort never re-scans -- it DIVIDES once, then only ever
compares across the boundary of two sorted piles. The price: O(n) extra
memory for the merge buffer (selection sort is in-place, O(1)).

STABILITY comes for free: when the two top cards are EQUAL, the merge rule
"take from the LEFT pile first" preserves the original order. Selection
sort's swap breaks this (🔗 SELECTION_SORT.md Section D); merge sort never
does.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  divide        : split arr[lo..hi] at mid = (lo+hi)//2 into arr[lo..mid]
                  and arr[mid+1..hi]. O(1) -- just index arithmetic (we do
                  NOT copy; we recurse on sub-ranges of the same array).
  base case     : a range of length 0 or 1 (lo >= hi). Already sorted; return.
  merge         : combine two ADJACENT sorted ranges [lo..mid] and [mid+1..hi]
                  into one sorted range [lo..hi], using an O(n) auxiliary
                  buffer. This is where all the actual work happens.
  recursion tree: the tree of divide calls. n leaves (single elements),
                  height ceil(log2 n). Every internal node = one merge.
  level         : all subproblems of the same size. Level k handles subarrays
                  of size ~ n/2^k. There are ceil(log2 n) levels.
  stable        : equal keys keep their input order. Merge sort IS stable
                  (take-from-left rule); selection sort is NOT.

=========================================================================
THE LINEAGE (textbooks / real systems)
=========================================================================
  Merge sort    : von Neumann, ~1945. The original divide-and-conquer sort.
                  Knuth, TAOCP Vol 3 §5.2.4. Guaranteed O(n log n) in EVERY
                  case (best/avg/worst identical) -- the "no bad input" sort.
  TimSort       : Tim Peters, 2002. Python's built-in `list.sort` and Java's
                  Arrays.sort(Object[]). HYBRID: merge sort + insertion sort
                  for short runs + detection of already-sorted "runs". Merge
                  sort is the backbone; insertion sort handles n < ~64 and
                  natural runs make the best case O(n). See §F.
  Heap sort     : the in-place O(n log n) alternative. Not stable. When you
                  can't afford O(n) auxiliary memory, heap sort; when you need
                  stability + guaranteed O(n log n), merge sort.
  External sort : merge sort is the basis of sorting data TOO BIG for RAM --
                  sorted runs on disk, then k-way merge. Its sequential memory
                  access pattern is what makes this work.

KEY FORMULAS (all verified/printed by the sections below):
    T(n) = 2*T(n/2) + Theta(n)         (Master theorem case 2 -> Theta(n log n))
    merge cost at level k  = n         (every element touched once per level)
    number of levels       = ceil(log2 n)
    total comparisons      <= n * ceil(log2 n)   (worst case; best case ~ n/2 * log n)
    auxiliary space        = Theta(n)            (the merge buffer)
    stable                 = YES                 (take-from-left on ties)
    best/avg/worst         = Theta(n log n)      (NO degenerate input)

Conventions:
    n   = len(arr)
    lo, hi = inclusive indices of the current sub-range
    mid  = (lo + hi) // 2      (left half = [lo..mid], right = [mid+1..hi])
"""

from __future__ import annotations

import math

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code MERGE_SORT.md walks
#    through). merge_sort() is the plain version; merge_sort_traced() records
#    the recursion tree and every merge for the guide to print.
# ============================================================================

def merge(arr: list[int], lo: int, mid: int, hi: int) -> int:
    """Merge two adjacent sorted ranges arr[lo..mid] and arr[mid+1..hi]
    in place into arr[lo..hi]. Returns the number of key comparisons made.

    Uses a temporary buffer of size (hi-lo+1). On ties we take from the LEFT
    range first -> STABLE. This stability rule is the only thing separating
    a stable from an unstable merge; get it backwards and you lose stability.
    """
    left = arr[lo:mid + 1]                  # copy left half
    right = arr[mid + 1:hi + 1]             # copy right half
    i = j = 0
    k = lo
    cmp = 0
    while i < len(left) and j < len(right):
        cmp += 1
        if left[i] <= right[j]:            # <= : LEFT on tie -> stable
            arr[k] = left[i]
            i += 1
        else:
            arr[k] = right[j]
            j += 1
        k += 1
    while i < len(left):                    # drain remaining left
        arr[k] = left[i]
        i += 1
        k += 1
    while j < len(right):                   # drain remaining right
        arr[k] = right[j]
        j += 1
        k += 1
    return cmp


def merge_sort(arr: list[int]) -> list[int]:
    """Top-down recursive merge sort. Returns a NEW sorted list (does not
    mutate the input). Theta(n log n) time, Theta(n) auxiliary space, stable.
    """
    a = list(arr)
    _merge_sort_range(a, 0, len(a) - 1)
    return a


def _merge_sort_range(a: list[int], lo: int, hi: int):
    if lo >= hi:
        return
    mid = (lo + hi) // 2
    _merge_sort_range(a, lo, mid)
    _merge_sort_range(a, mid + 1, hi)
    merge(a, lo, mid, hi)


def merge_sort_traced(arr: list[int]) -> dict:
    """Same algorithm, but records the recursion tree (divides) and every
    merge so the guide can print a divide tree + merge-step trace.

    Records:
      divides : list of (depth, lo, hi, subarray-before) for each call, in the
                order calls are made (pre-order). Lets us draw the divide tree.
      merges  : list of {left, right, result, comparisons} for each merge,
                in execution order.
    Aggregates: total comparisons, number of merges, tree height.
    """
    a = list(arr)
    n = len(a)
    divides: list[dict] = []
    merges: list[dict] = []

    def rec(lo: int, hi: int, depth: int):
        divides.append({
            "depth": depth, "lo": lo, "hi": hi,
            "sub": list(a[lo:hi + 1]),
            "is_leaf": lo >= hi,
        })
        if lo >= hi:
            return
        mid = (lo + hi) // 2
        rec(lo, mid, depth + 1)
        rec(mid + 1, hi, depth + 1)
        before = list(a[lo:hi + 1])
        cmp = merge(a, lo, mid, hi)
        merges.append({
            "lo": lo, "mid": mid, "hi": hi,
            "left": list(before[:mid - lo + 1]),
            "right": list(before[mid - lo + 1:]),
            "result": list(a[lo:hi + 1]),
            "comparisons": cmp,
        })

    rec(0, n - 1, 0)
    height = max(d["depth"] for d in divides) if divides else 0
    return {
        "input": list(arr),
        "sorted": a,
        "n": n,
        "divides": divides,
        "merges": merges,
        "total_comparisons": sum(m["comparisons"] for m in merges),
        "num_merges": len(merges),
        "tree_height": height,
        "expected_levels": math.ceil(math.log2(n)) if n > 1 else 0,
    }


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE TINY CONCRETE EXAMPLE: [64, 25, 12, 22, 11]
#    n=5 -> tree height ceil(log2 5) = 3 levels, 4 merges.
# ============================================================================

EXAMPLE = [64, 25, 12, 22, 11]


# ----------------------------------------------------------------------------
# SECTION A: the algorithm, top to bottom
# ----------------------------------------------------------------------------

def section_algorithm():
    banner("SECTION A: the algorithm  (array = [64,25,12,22,11])")
    r = merge_sort_traced(EXAMPLE)
    n = r["n"]
    print(f"Input  : {r['input']}")
    print(f"Sorted : {r['sorted']}")
    print(f"n = {n}  ->  divide log2({n}) = {math.log2(n):.2f} -> "
          f"{r['tree_height']} levels of recursion, {r['num_merges']} merges.\n")
    print("Two phases repeat at every node of the recursion tree:")
    print("  DIVIDE : cut arr[lo..hi] at mid=(lo+hi)//2 -> recurse on each half.")
    print("  MERGE  : after both halves return sorted, merge them in O(n).\n")
    print("Base case: a range of length <= 1 is already sorted (nothing to do).")
    print("All the real work is in the MERGE step, never in the divide.")


# ----------------------------------------------------------------------------
# SECTION B: the divide tree
# ----------------------------------------------------------------------------

def section_divide_tree():
    banner("SECTION B: the divide tree  (how the array gets chopped up)")
    r = merge_sort_traced(EXAMPLE)
    print("Every node is a recursive call. Leaves (length 1) are sorted.\n")
    # group divides by depth to draw the tree
    by_depth: dict[int, list[dict]] = {}
    for d in r["divides"]:
        by_depth.setdefault(d["depth"], []).append(d)
    for depth in sorted(by_depth):
        nodes = by_depth[depth]
        indent = "  " * depth
        print(f"depth {depth}: {indent}", end="")
        for nd in nodes:
            tag = "leaf" if nd["is_leaf"] else f"[{nd['lo']}..{nd['hi']}]"
            print(f"{nd['sub']} {tag}   ", end="")
        print()
    print()
    print("Read top-down: the whole array splits into [64,25,12] and [22,11],")
    print("each of those splits again, until every piece is a single element.")
    print("The number of splits along the longest root-to-leaf path is the")
    print(f"tree HEIGHT = {r['tree_height']} = ceil(log2 {r['n']}) "
          f"= ceil({math.log2(r['n']):.2f}).")
    assert r["tree_height"] == r["expected_levels"]
    print("[check] height == ceil(log2 n):  OK")
    print(f"\nn = {r['n']} leaves (one per element). An internal node has exactly")
    print(f"2 children, so #merges = #internal nodes = {r['num_merges']}.")


# ----------------------------------------------------------------------------
# SECTION C: the merge steps (where the work happens)
# ----------------------------------------------------------------------------

def section_merge_steps():
    banner("SECTION C: the merge steps  (each merge is O(n), take-left on tie)")
    r = merge_sort_traced(EXAMPLE)
    print("Merges run bottom-up (deepest first), as each pair of children returns.")
    print("Rule: compare the two fronts; take the SMALLER; on a TIE take LEFT")
    print("(-> stable). When one pile empties, copy the rest of the other.\n")
    total = 0
    for idx, m in enumerate(r["merges"]):
        total += m["comparisons"]
        print(f"-- merge {idx}: [{m['lo']}..{m['mid']}] + [{m['mid']+1}..{m['hi']}] --")
        print(f"   left  : {m['left']}")
        print(f"   right : {m['right']}")
        print(f"   result: {m['result']}   "
              f"({m['comparisons']} comparisons)")
        print()
    print(f"Total comparisons across all {r['num_merges']} merges: {total}")
    n = r["n"]
    upper = n * r["tree_height"]
    print(f"Upper bound n * ceil(log2 n) = {n} * {r['tree_height']} = {upper}.")
    print(f"Measured {total} <= {upper}: "
          f"{'OK' if total <= upper else 'FAIL'}")
    assert total <= upper
    print("\nEach LEVEL of the tree touches every element exactly once during its")
    print("merges -> O(n) work per level. With ceil(log2 n) levels, total work")
    print("= O(n log n). That is the Master theorem on T(n) = 2*T(n/2) + Theta(n).")


# ----------------------------------------------------------------------------
# SECTION D: complexity analysis (NO bad input)
# ----------------------------------------------------------------------------

def section_complexity():
    banner("SECTION D: complexity analysis  (BEST = AVERAGE = WORST = Theta(n log n))")
    print("Merge sort ALWAYS divides in half and ALWAYS merges linearly. The")
    print("input's order only changes HOW MANY comparisons each merge makes")
    print("(best case ~ n/2 per level if already sorted, worst case ~ n per")
    print("level), NOT the number of levels. So there is no degenerate input.\n")
    cases = [
        ("best    (already sorted)  ", sorted(EXAMPLE)),
        ("average (random)          ", [25, 64, 12, 22, 11]),
        ("worst   (reverse sorted)  ", sorted(EXAMPLE, reverse=True)),
    ]
    n = len(EXAMPLE)
    print(f"  {'case':<28} {'comparisons':<12} {'merges':<8} {'sorted?'}")
    for label, arr in cases:
        r = merge_sort_traced(arr)
        is_sorted = r["sorted"] == sorted(arr)
        print(f"  {label:<28} {r['total_comparisons']:<12} "
              f"{r['num_merges']:<8} {is_sorted}")
    print("\nComparison count varies only by a constant factor (~2x) across")
    print(f"cases; the n log n SHAPE is identical. n log2 n for n={n} = "
          f"{n * math.log2(n):.1f}.\n")
    print("Summary table:")
    print("  | case    | comparisons        | time         | space     | stable |")
    print("  |---------|--------------------|--------------|-----------|--------|")
    print("  | best    | ~(n/2) log n       | Theta(n log n)| Theta(n) | yes    |")
    print("  | average | ~ n log n          | Theta(n log n)| Theta(n) | yes    |")
    print("  | worst   | ~ n log n          | Theta(n log n)| Theta(n) | yes    |")
    print("\nSpace: Theta(n) auxiliary for the merge buffer (NOT in-place).")
    print("Contrast selection_sort (🔗 SELECTION_SORT.md Section C): Theta(n^2)")
    print("comparisons in EVERY case, but O(1) auxiliary space, in-place.")


# ----------------------------------------------------------------------------
# SECTION E: stability (merge sort IS stable -- take-left rule)
# ----------------------------------------------------------------------------

def section_stability():
    banner("SECTION E: stability  (YES -- the take-from-left rule preserves order)")
    print("A sort is STABLE if equal keys keep their original relative order.\n")
    print("Merge sort is stable BY CONSTRUCTION: the merge rule says 'on a tie,\n"
          "take from the LEFT half first'. Since the left half held the elements\n"
          "that came EARLIER in the input, ties always resolve in input order.\n")
    print("The ONLY way to break this is to write `<` instead of `<=` in the")
    print("merge (taking right on a tie). The implementation above uses `<=`.\n")
    print("Demonstration: tag two equal keys with their original index.\n")
    tagged_vals = [("2a", 2), ("1", 1), ("2b", 2), ("3", 3)]
    print(f"Input (tag, value): {tagged_vals}")
    # run merge sort on the values, carrying tags, using <= (stable).
    a = list(tagged_vals)
    _merge_sort_tagged(a, 0, len(a) - 1)
    print(f"Output             : {a}")
    twos = [t for (t, v) in a if v == 2]
    stable_order = ["2a", "2b"]
    is_stable = twos == stable_order
    print(f"\nThe two 2's ended up as {twos}; a stable sort keeps {stable_order}.")
    print(f"[check] stable?  {is_stable}  ->  merge sort IS stable")
    assert is_stable
    print("\nCompare with selection_sort (🔗 SELECTION_SORT.md Section D): the")
    print("swap leapfrogs equal keys -> NOT stable. Merge sort pays O(n) space")
    print("and GETS stability for free.")


def _merge_sort_tagged(a: list[tuple], lo: int, hi: int):
    """Merge sort on (tag, value) tuples keyed by value, stable via <=."""
    if lo >= hi:
        return
    mid = (lo + hi) // 2
    _merge_sort_tagged(a, lo, mid)
    _merge_sort_tagged(a, mid + 1, hi)
    left = a[lo:mid + 1]
    right = a[mid + 1:hi + 1]
    i = j = 0
    k = lo
    while i < len(left) and j < len(right):
        if left[i][1] <= right[j][1]:      # <= : LEFT on tie -> stable
            a[k] = left[i]
            i += 1
        else:
            a[k] = right[j]
            j += 1
        k += 1
    while i < len(left):
        a[k] = left[i]
        i += 1
        k += 1
    while j < len(right):
        a[k] = right[j]
        j += 1
        k += 1


# ----------------------------------------------------------------------------
# SECTION F: when to use merge sort (TimSort, linked lists, external sort)
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION F: when to use merge sort  (and where it hides in real systems)")
    print("USE merge sort when:")
    print("  * You need GUARANTEED O(n log n) with no bad input. Quicksort's")
    print("    worst case is Theta(n^2); merge sort's never is. Mission-critical")
    print("    / real-time systems often prefer the predictability.")
    print("  * You need STABILITY. It is the canonical stable O(n log n) sort.")
    print("  * Sorting LINKED LISTS: merge is O(1) extra space on linked lists")
    print("    (relink pointers, no buffer), and divide is pointer-based. The")
    print("    one place merge sort beats quicksort on space.")
    print("  * EXTERNAL sorting (data > RAM): write sorted runs to disk, then")
    print("    k-way merge. Merge sort's sequential access pattern is ideal for")
    print("    slow spinning/sequential media; random-access sorts thrash.")
    print()
    print("DO NOT use plain merge sort when:")
    print("  * You are tight on MEMORY: it needs Theta(n) auxiliary space. Use")
    print("    heapsort (in-place, O(1)) or an in-place merge variant.")
    print("  * You want cache-friendly in-place sorting on arrays: quicksort's")
    print("    partitioning is in-place and cache-friendlier; merge sort's")
    print("    buffer copy hurts. (This is why libc qsort is usually quicksort.)")
    print("  * n is SMALL (< ~64): insertion sort's lower overhead wins. This is")
    print("    exactly the hybrid trick TimSort uses.")
    print()
    print("WHERE IT HIDES:")
    print("  * Python list.sort / sorted()  -> TimSort (merge sort + run detect).")
    print("  * Java Arrays.sort(Object[])   -> TimSort since Java 7.")
    print("  * Java Arrays.sort(int[])      -> dual-pivot quicksort (NOT merge;")
    print("    chose speed + in-place over stability for primitives).")
    print("  * V8 / libstdc++ std::stable_sort -> merge sort (stability required).")
    print("\nSee SELECTION_SORT.md for the Theta(n^2) minimum-swap foil.")


# ============================================================================
# main + GOLD
# ============================================================================

def main():
    print("merge_sort.py - reference impl. All numbers below feed MERGE_SORT.md.")
    section_algorithm()
    section_divide_tree()
    section_merge_steps()
    section_complexity()
    section_stability()
    section_when_to_use()

    banner("GOLD (pinned for merge_sort.html) -- array = [64,25,12,22,11]")
    r = merge_sort_traced(EXAMPLE)
    print(f"sorted array        : {r['sorted']}")
    print(f"total comparisons   : {r['total_comparisons']}")
    print(f"number of merges    : {r['num_merges']}")
    print(f"tree height         : {r['tree_height']}")
    print(f"merge sequence (results): "
          f"{[m['result'] for m in r['merges']]}")
    # GOLD scalars for the .html to recompute and check.
    GOLD_SORTED = [11, 12, 22, 25, 64]
    GOLD_COMPARISONS = 6
    GOLD_NUM_MERGES = 4
    GOLD_MERGE_RESULTS = [[25, 64], [12, 25, 64], [11, 22], [11, 12, 22, 25, 64]]
    assert r["sorted"] == GOLD_SORTED
    assert r["total_comparisons"] == GOLD_COMPARISONS
    assert r["num_merges"] == GOLD_NUM_MERGES
    assert [m["result"] for m in r["merges"]] == GOLD_MERGE_RESULTS
    print()
    print(f"GOLD sorted          = {GOLD_SORTED}")
    print(f"GOLD comparisons     = {GOLD_COMPARISONS}")
    print(f"GOLD num merges      = {GOLD_NUM_MERGES}")
    print(f"GOLD merge results   = {GOLD_MERGE_RESULTS}")
    print("[check] GOLD reproduces from merge_sort_traced(EXAMPLE):  OK")

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
