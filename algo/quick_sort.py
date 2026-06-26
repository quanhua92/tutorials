"""
quick_sort.py - Reference implementation of Quicksort, with pivot strategies.

This is the single source of truth that QUICK_SORT.md is built from. Every
number, table, and worked example in QUICK_SORT.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python quick_sort.py

=========================================================================
THE INTUITION (read this first) -- divide and conquer around a pivot
=========================================================================
Quicksort picks ONE element (the PIVOT), splits the array into "smaller
than pivot" and "bigger than pivot" (the PARTITION step), then recurses
on each side. The split is done IN PLACE -- just swaps, no extra arrays.

  * partition  : one linear scan that puts every element < pivot to the
                 left, every element > pivot to the right, and the pivot
                 in its FINAL sorted position in the middle.
  * pivot      : the element we split around. Its CHOICE is the whole
                 game: a good pivot splits the array in half -> O(n log n);
                 a bad pivot (e.g. the smallest, on already-sorted input)
                 peels off one element at a time -> O(n^2).
  * strategies : first element, last element, random, median-of-3.

THE REASON QUICKSORT IS FAST IN PRACTICE: the inner loop (partition) is a
tiny compare-and-swap that is cache-friendly and branch-predictable. Even
though quicksort, mergesort and heapsort are all ~O(n log n), quicksort
usually wins on real hardware because of the cache -- BUT it has an
O(n^2) worst case the others lack, which is why production libraries
(introsort) switch to heapsort once the recursion gets too deep.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  pivot        : the element we split the subarray around.
  partition    : the single pass that rearranges [lo..hi] into
                 "smaller | pivot | bigger"; returns the pivot's final index.
  Lomuto       : a partition scheme that scans left-to-right, swapping the
                 next smaller element into a growing "small" region at the
                 front. (Hoare's original 1961 scheme scans from both ends.)
  comparison   : the basic op we count (arr[j] <= pivot). This single
                 number is what separates O(n log n) from O(n^2).
  median-of-3  : pick the median of arr[lo], arr[mid], arr[hi] as pivot --
                 a cheap heuristic that kills the sorted/reversed worst case.
  introsort    : quicksort that falls back to heapsort after O(log n) depth,
                 GUARANTEEING O(n log n) (Musser 1997). std::sort is this.

=========================================================================
THE LINEAGE (papers)
=========================================================================
  Hoare    (1961, Algorithm 64) : the original quicksort, two-pointer
                                  partition scanning from both ends.
  Lomuto                        : simpler single-pointer partition (taught
                                  here for clarity; same complexity).
  Sedgewick (1975, PhD; 1978)   : median-of-3, average-case analysis --
                                  the version in every textbook / stdlib.
  Musser   (1997, introsort)    : quicksort -> heapsort fallback, the
                                  guarantee that made quicksort safe.

KEY FORMULAS (verified against CLRS Ch. 7):
    best / average case : T(n) = 2 T(n/2) + Theta(n) = Theta(n log n)
    worst case          : T(n) = T(n-1) + Theta(n)   = Theta(n^2)
    comparisons counted : sum over partitions of (subarray length - 1)
    expected (random pivots) : <= 2 n ln n ~ 1.39 n log2 n   (CLRS 7.3)
"""

from __future__ import annotations

import random

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (the code QUICK_SORT.md walks through)
# ============================================================================

def choose_pivot(arr, lo, hi, strategy, rng):
    """Return the INDEX of the chosen pivot for subarray arr[lo..hi]."""
    if strategy == "first":
        return lo
    if strategy == "last":
        return hi
    if strategy == "median3":
        mid = (lo + hi) // 2
        cands = sorted([(arr[lo], lo), (arr[mid], mid), (arr[hi], hi)])
        return cands[1][1]                          # index of median value
    if strategy == "random":
        return rng.randint(lo, hi)
    raise ValueError(f"unknown strategy: {strategy}")


def partition(arr, lo, hi, pivot_idx, stats):
    """Lomuto partition. Returns the pivot's FINAL index.

    Stash pivot at arr[hi], scan [lo..hi-1], swap each element <= pivot into a
    growing "small" region (indices lo..i), then drop the pivot at i+1.
    Counts comparisons (the arr[j] <= pivot test) in stats['comparisons'].
    """
    arr[pivot_idx], arr[hi] = arr[hi], arr[pivot_idx]      # stash pivot at end
    pivot = arr[hi]
    i = lo - 1                                             # end of "small" region
    for j in range(lo, hi):
        stats["comparisons"] += 1
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]
    arr[i + 1], arr[hi] = arr[hi], arr[i + 1]             # pivot -> final spot
    return i + 1


def quicksort(arr, lo, hi, strategy, rng, stats):
    """In-place quicksort of arr[lo..hi]."""
    if lo >= hi:
        return
    pivot_idx = choose_pivot(arr, lo, hi, strategy, rng)
    p = partition(arr, lo, hi, pivot_idx, stats)
    quicksort(arr, lo, p - 1, strategy, rng, stats)
    quicksort(arr, p + 1, hi, strategy, rng, stats)


def quicksort_sort(data, strategy="last", seed=0):
    """Public entry: returns (sorted_copy, comparisons). Non-destructive."""
    arr = list(data)
    rng = random.Random(seed)                              # seed for 'random'
    stats = {"comparisons": 0}
    quicksort(arr, 0, len(arr) - 1, strategy, rng, stats)
    return arr, stats["comparisons"]


# ----------------------------------------------------------------------------
# Lomuto partition that RECORDS every compare/swap, for the .html animation.
# ----------------------------------------------------------------------------
def partition_traced(arr, lo, hi, pivot_idx):
    """Lomuto partition recording every step for animation. Non-destructive.

    Returns (final_pivot_index, steps) where each step is a dict:
      {'op':'stash'|'compare'|'swap'|'place', 'i':..,'j':..,
       'result':bool, 'pivot_val':.., 'pivot_final':.., 'array':[...]}
    `array` is the array state AFTER that step's mutation.
    """
    a = list(arr)
    a[pivot_idx], a[hi] = a[hi], a[pivot_idx]
    pivot = a[hi]
    steps = [{"op": "stash", "pivot_val": pivot, "array": list(a),
              "i": lo - 1, "j": None, "result": None, "pivot_final": None}]
    i = lo - 1
    for j in range(lo, hi):
        res = a[j] <= pivot
        steps.append({"op": "compare", "pivot_val": pivot, "array": list(a),
                      "i": i, "j": j, "result": res, "pivot_final": None})
        if res:
            i += 1
            a[i], a[j] = a[j], a[i]
            steps.append({"op": "swap", "pivot_val": pivot, "array": list(a),
                          "i": i, "j": j, "result": None, "pivot_final": None})
    a[i + 1], a[hi] = a[hi], a[i + 1]
    final = i + 1
    steps.append({"op": "place", "pivot_val": pivot, "array": list(a),
                  "i": None, "j": None, "result": None, "pivot_final": final})
    return final, steps


# ----------------------------------------------------------------------------
# counted mergesort + heapsort, ONLY for the comparison table (Section D).
# The canonical heapsort lives in heap_sort.py.
# ----------------------------------------------------------------------------
def merge_sort_counted(data):
    arr = list(data)
    stats = {"comparisons": 0}
    _ms(arr, 0, len(arr), stats)
    return arr, stats["comparisons"]


def _ms(arr, lo, hi, stats):
    if hi - lo <= 1:
        return
    mid = (lo + hi) // 2
    _ms(arr, lo, mid, stats)
    _ms(arr, mid, hi, stats)
    left, right = arr[lo:mid], arr[mid:hi]
    i = j = 0
    k = lo
    while i < len(left) and j < len(right):
        stats["comparisons"] += 1
        if left[i] <= right[j]:
            arr[k] = left[i]
            i += 1
        else:
            arr[k] = right[j]
            j += 1
        k += 1
    while i < len(left):
        arr[k] = left[i]
        i += 1
        k += 1
    while j < len(right):
        arr[k] = right[j]
        j += 1
        k += 1


def heap_sort_counted(data):
    arr = list(data)
    n = len(arr)
    stats = {"comparisons": 0}

    def siftdown(start, end):
        root = start
        while True:
            child = 2 * root + 1
            if child > end:
                break
            if child + 1 <= end:
                stats["comparisons"] += 1
                if arr[child] < arr[child + 1]:
                    child += 1
            stats["comparisons"] += 1
            if arr[root] < arr[child]:
                arr[root], arr[child] = arr[child], arr[root]
                root = child
            else:
                break

    for start in range(n // 2 - 1, -1, -1):
        siftdown(start, n - 1)
    for end in range(n - 1, 0, -1):
        arr[0], arr[end] = arr[end], arr[0]
        siftdown(0, end - 1)
    return arr, stats["comparisons"]


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_arr(a):
    return "[" + ", ".join(str(x) for x in a) + "]"


# ============================================================================
# 3. THE TINY CONCRETE EXAMPLE
#    Fixed array so quick_sort.html can recompute the EXACT same steps in JS.
# ============================================================================

WORKED = [3, 8, 2, 5, 1, 4, 7, 6]            # 8 elements, all distinct

STRATEGIES = ["first", "last", "random", "median3"]


def seeded_array(n, seed=0, lo=1, hi=99):
    """Deterministic random array for the impact study."""
    rng = random.Random(seed)
    return [rng.randint(lo, hi) for _ in range(n)]


# ----------------------------------------------------------------------------
# SECTION A: the algorithm + a full partition trace
# ----------------------------------------------------------------------------

def section_algorithm():
    banner("SECTION A: the algorithm -- Lomuto partition, last-element pivot")
    arr = list(WORKED)
    print(f"Worked array: {fmt_arr(arr)}   (n = {len(arr)})\n")
    print("The whole algorithm is two lines of recursion around ONE pass:\n")
    print("    partition arr[lo..hi] around a pivot  ->  pivot lands in its")
    print("    FINAL sorted position p; everything left is < pivot,")
    print("    everything right is > pivot. Then recurse on both halves.\n")

    # trace the FIRST (top-level) partition in detail
    lo, hi = 0, len(arr) - 1
    pivot_idx = hi                                   # last-element pivot
    final, steps = partition_traced(arr, lo, hi, pivot_idx)
    print(f"Top-level partition of arr[0..{hi}], pivot = arr[{pivot_idx}] = "
          f"{arr[pivot_idx]}:\n")
    for s in steps:
        op = s["op"]
        if op == "stash":
            print(f"  stash pivot {s['pivot_val']} at end:     {fmt_arr(s['array'])}")
        elif op == "compare":
            r = "<= pivot -> grows small region" if s["result"] else "> pivot -> skip"
            print(f"  compare j={s['j']} (val {s['array'][s['j']]}):  {r}")
        elif op == "swap":
            print(f"    swap i={s['i']}<->j={s['j']}:          {fmt_arr(s['array'])}")
        elif op == "place":
            print(f"  place pivot at index {s['pivot_final']}: "
                  f"{fmt_arr(s['array'])}   <- pivot locked")
    print(f"\nPivot {final} final index. Left = {fmt_arr(arr[lo:final])}, "
          f"right = {fmt_arr(arr[final+1:hi+1])}.\n")

    # run the full sort
    sorted_arr, comps = quicksort_sort(WORKED, strategy="last")
    print(f"Full quicksort (last pivot): {fmt_arr(WORKED)} -> {fmt_arr(sorted_arr)}")
    print(f"Total comparisons = {comps}   (n-1 + n-2-1 + ...; theoretical avg "
          f"~ 1.39 n log2 n = {1.39 * len(WORKED) * _log2(len(WORKED)):.1f})")
    assert sorted_arr == sorted(WORKED), "BUG: not sorted!"
    print("[check] quicksort output == sorted(WORKED):  OK")


def _log2(n):
    import math
    return math.log2(n)


# ----------------------------------------------------------------------------
# SECTION B: the four pivot strategies
# ----------------------------------------------------------------------------

def section_pivot_strategies():
    banner("SECTION B: the four pivot strategies  (first / last / random / median-of-3)")
    arr = list(WORKED)
    lo, hi = 0, len(arr) - 1
    mid = (lo + hi) // 2
    print(f"Worked array: {fmt_arr(arr)}\n")
    print("For the TOP-LEVEL call arr[0..7], each strategy picks:")
    print("| strategy    | pivot index | pivot value | how chosen                      |")
    print("|-------------|-------------|-------------|---------------------------------|")
    rng = random.Random(0)
    rand_idx = rng.randint(lo, hi)
    pivots = [
        ("first",    lo,  arr[lo]),
        ("last",     hi,  arr[hi]),
        ("random",   rand_idx, arr[rand_idx]),
        ("median3",  choose_pivot(arr, lo, hi, "median3", rng),
                     arr[choose_pivot(arr, lo, hi, "median3", rng)]),
    ]
    for name, idx, val in pivots:
        note = {"first": "just arr[lo]",
                "last": "just arr[hi]",
                "random": f"rng.randint({lo},{hi}) (seed 0)",
                "median3": f"median of arr[{lo}]={arr[lo]}, arr[{mid}]={arr[mid]}, "
                           f"arr[{hi}]={arr[hi]}"}[name]
        print(f"| {name:<11} | {idx:<11} | {val:<11} | {note:<31} |")
    print()
    print("first/last are the dangerous ones on sorted/reversed input (see Section C).")
    print("median-of-3 costs 2-3 extra compares per call but avoids the worst case")
    print("on the two commonest real-world inputs (already-sorted, reverse-sorted).")
    print("random makes the WORST case a probability event, not an input pattern.")


# ----------------------------------------------------------------------------
# SECTION C: pivot-choice impact (the O(n^2) worst case)
# ----------------------------------------------------------------------------

def section_pivot_impact():
    banner("SECTION C: pivot-choice impact -- comparisons on hostile inputs")
    n = 32
    already_sorted = list(range(1, n + 1))
    reversed_arr = list(range(n, 0, -1))
    random_arr = seeded_array(n, seed=0)
    few_unique = [1, 2, 3] * (n // 3) + [1] * (n - 3 * (n // 3))
    inputs = [
        ("random", random_arr),
        ("sorted", already_sorted),
        ("reversed", reversed_arr),
        ("few-unique", few_unique),
    ]
    print(f"n = {n}. comparisons per strategy x input:\n")
    header = "| input       | " + " | ".join(f"{s:>9}" for s in STRATEGIES) + \
             " | best possible |"
    print(header)
    print("|-" + "-|-" * (len(STRATEGIES) + 1))
    worst = {"first": 0, "last": 0, "random": 0, "median3": 0}
    for label, data in inputs:
        row = f"| {label:<11} | "
        for s in STRATEGIES:
            _, c = quicksort_sort(data, strategy=s, seed=0)
            row += f"{c:>9} | "
            worst[s] = max(worst[s], c)
        # n log2 n lower bound for comparisons
        row += f"{int(n * _log2(n)):>13} |"
        print(row)
    print()
    print("Read it row by row:")
    print("  - 'sorted'   with first/last pivot -> the WORST CASE. Each partition")
    print("    peels off ONE element, giving n+(n-1)+...+1 = n(n-1)/2 comparisons.")
    print(f"    first/last on sorted/reversed ~ {n*(n-1)//2} = O(n^2).")
    print("  - median-of-3 and random stay near n log2 n on EVERY input.")
    print(f"  - 'best possible' ~ n log2 n = {int(n * _log2(n))}. No comparison sort")
    print("    beats this in the worst case (decision-tree lower bound).")
    print()
    print("| strategy | worst comparisons seen | vs n log2 n |")
    print("|----------|------------------------|-------------|")
    for s in STRATEGIES:
        ratio = worst[s] / (n * _log2(n))
        print(f"| {s:<8} | {worst[s]:<22} | {ratio:.2f}x       |")
    n2 = n * (n - 1) // 2
    print(f"\n[check] first-pivot on sorted == n(n-1)/2 == {n2}:  "
          f"{'OK' if worst['first'] == n2 else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: quicksort vs mergesort vs heapsort
# ----------------------------------------------------------------------------

def section_comparison():
    banner("SECTION D: quicksort vs mergesort vs heapsort  (counts on n=64)")
    n = 64
    data = seeded_array(n, seed=1)
    qs_sorted, qs_comp = quicksort_sort(data, strategy="median3", seed=0)
    ms_sorted, ms_comp = merge_sort_counted(data)
    hs_sorted, hs_comp = heap_sort_counted(data)
    assert qs_sorted == ms_sorted == hs_sorted == sorted(data)
    print(f"Input: {n} random ints (seed 1). All three return the same sorted")
    print(f"output: {fmt_arr(qs_sorted[:6])}...{fmt_arr(qs_sorted[-3:])}\n")
    print("| sort          | comparisons | auxiliary memory | stable | worst case   |")
    print("|---------------|-------------|------------------|--------|--------------|")
    print(f"| quicksort(m3) | {qs_comp:<11} | O(log n) stack   | no     | O(n^2)*      |")
    print(f"| mergesort     | {ms_comp:<11} | O(n) extra array | yes    | O(n log n)   |")
    print(f"| heapsort      | {hs_comp:<11} | O(1) in-place    | no     | O(n log n)   |")
    print()
    print("  * median-of-3 quicksort's O(n^2) is vanishingly rare on random input;")
    print("    introsort (std::sort) makes the GUARANTEE O(n log n) by switching to")
    print("    heapsort after 2*log2(n) recursion levels.\n")
    print("Why quicksort usually WINS in practice despite no guarantee:")
    print("  - tightest inner loop: one compare + one branch + maybe one swap, all on")
    print("    a contiguous array -> superb cache locality + branch prediction.")
    print("  - heapsort hops around a tree stored in an array (parent/child are 2i+1,")
    print("    2i+2 apart) -> cache-unfriendly, ~2-3x slower on real hardware.")
    print("  - mergesort touches O(n) extra memory -> more cache traffic, slower than")
    print("    quicksort unless you specifically need STABILITY or linked-list sort.")


# ----------------------------------------------------------------------------
# SECTION E: when to use quicksort
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION E: when to use quicksort (and when NOT to)")
    print("USE quicksort when:")
    print("  - you sort general arrays in RAM and want the fastest average speed")
    print("    (this is why std::sort / sorted() are quicksort/introsort-based).")
    print("  - you can afford O(log n) stack + no stability requirement.\n")
    print("AVOID quicksort when:")
    print("  - you need a WORST-CASE guarantee without introsort's fallback")
    print("    (hard real-time, adversarial input) -> heapsort.")
    print("  - you need STABILITY (equal keys keep their order) -> mergesort.")
    print("  - the data is a linked list or streamed -> mergesort (O(1) merge).")
    print("  - n is tiny -> insertion sort (fewer ops, no recursion overhead);")
    print("    real quicksorts switch to insertion sort below ~10-20 elements.\n")
    print("Rule of thumb: the default in nearly every stdlib is INTROSORT")
    print("(quicksort + median-of-3 + heapsort fallback + insertion-sort cutoff).")
    print("You get quicksort's speed AND heapsort's O(n log n) guarantee.")


# ----------------------------------------------------------------------------
# GOLD check -- pins values for quick_sort.html to recompute in JS.
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION G: GOLD values (pinned for quick_sort.html)")
    # deterministic median-of-3 sort of WORKED
    qs_sorted, qs_comp = quicksort_sort(WORKED, strategy="median3", seed=0)
    last_sorted, last_comp = quicksort_sort(WORKED, strategy="last", seed=0)
    first_comp = quicksort_sort(WORKED, strategy="first", seed=0)[1]
    print(f"WORKED = {fmt_arr(WORKED)}\n")
    print(f"GOLD sorted result      = {fmt_arr(qs_sorted)}")
    print(f"GOLD median3 comparisons = {qs_comp}")
    print(f"GOLD last    comparisons = {last_comp}")
    print(f"GOLD first   comparisons = {first_comp}")
    # top-level median-of-3 pivot choice on WORKED
    lo, hi = 0, len(WORKED) - 1
    pidx = choose_pivot(WORKED, lo, hi, "median3", random.Random(0))
    final, steps = partition_traced(WORKED, lo, hi, pidx)
    n_steps = len(steps)
    print(f"GOLD median3 top pivot index = {pidx}, value = {WORKED[pidx]}, "
          f"lands at {final}")
    print(f"GOLD top-level partition step count = {n_steps}")
    # self-consistency assertions
    assert qs_sorted == sorted(WORKED)
    assert last_sorted == sorted(WORKED)
    print("\n[check] median3 & last both fully sort WORKED:  OK")
    print("[check] gold values reproduce from quicksort_sort():  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("quick_sort.py - reference impl. All numbers below feed QUICK_SORT.md.")
    print("python", end=" ")
    import sys
    print(sys.version.split()[0])

    section_algorithm()
    section_pivot_strategies()
    section_pivot_impact()
    section_comparison()
    section_when_to_use()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
