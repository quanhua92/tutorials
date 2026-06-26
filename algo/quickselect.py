"""
quickselect.py - Reference implementation of Quickselect (Hoare 1961): find the
k-th smallest element of an array in O(n) average time, plus the
median-of-medians (BFPRT) variant that gives an O(n) WORST-CASE guarantee.

This is the single source of truth that QUICKSELECT.md is built from. Every
number, table, and worked example in QUICKSELECT.md is printed by this file.
If you change something here, re-run and re-paste the output.

Run:
    python quickselect.py

============================================================================
THE INTUITION (read this first) -- quicksort that only walks ONE branch
============================================================================
Quickselect is quicksort that refuses to do half the work. To find the k-th
smallest element:

  * partition  : pick a pivot, split the array into "smaller | pivot | bigger"
                 (exactly the quicksort partition -- one linear scan). The pivot
                 lands in its FINAL sorted position, index p.
  * pick side  : if k == p, the pivot IS the answer -- done. If k < p, the
                 answer is in the LEFT part; recurse left. If k > p, recurse
                 RIGHT. We ALWAYS throw away half (on average).
  * vs sort    : quicksort recurses on BOTH halves -> O(n log n). Quickselect
                 recurses on only ONE -> O(n) average. That is the whole trick.

THE REASON IT IS O(n) ON AVERAGE: each level does O(n) partition work, but only
recurses into ONE side of average size n/2, then n/4, then n/8, ... The work is
n + n/2 + n/4 + ... = 2n = O(n). (Quicksort does both sides: the geometric sum
doubles to n log n.)

THE CATCH (same as quicksort): a pathologically bad pivot peels off one element
per level, giving n + (n-1) + ... = O(n^2). The median-of-medians trick (Blum,
Floyd, Pratt, Rivest, Tarjan 1973 -- "BFPRT") spends extra work to pick a pivot
guaranteed to be in the 30%-70% range, restoring the WORST-CASE guarantee O(n)
at the cost of a larger constant. This is sometimes called the "selection
problem"; introselect (std::nth_element) is quickselect + a median-of-medians
fallback, exactly parallel to introsort.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  k-th smallest  : the element that would sit at index k (0-based) if the array
                   were sorted. k=0 is the min; k=n-1 is the max; k=n//2 is the
                   median (lower median for even n).
  order statistic: another name for "k-th smallest". "Selection" = finding one.
  partition      : the single pass (Lomuto here) that rearranges [lo..hi] into
                   "smaller | pivot | bigger" and returns the pivot's final index.
  pivot          : the element we partition around. Its CHOICE is the whole game
                   for the worst case (just like quicksort).
  search region  : the subarray [lo..hi] that still contains index k. Quickselect
                   shrinks this region by ~half each level; that is why it is O(n).
  median-of-medians : a pivot-picking rule: split into groups of 5, take each
                   group's median, then take the median of THOSE as the pivot.
                   Guarantees the pivot is between the 30th and 70th percentile,
                   so each recursion discards >= 30% -> worst case O(n).
  introselect    : quickselect + median-of-medians fallback past some depth =
                   std::nth_element. Guarantees O(n) but keeps quickselect's
                   speed on typical input.

============================================================================
THE LINEAGE (papers)
============================================================================
  Hoare  (1961, Algorithm 65 "FIND") : the original quickselect. Same author,
                                       same year, same partition as quicksort.
  BFPRT  (1973, Blum, Floyd, Pratt, Rivest, Tarjan) : "Time Bounds for
                                       Selection." median-of-medians -> the
                                       LINEAR WORST-CASE guarantee.
  Musser (1997, introsort/introselect) : quickselect + median-of-medians
                                       fallback -> std::nth_element.
  Floyd  (1962-1971)                   : heap-based selection (related); also
                                       co-author of BFPRT.

KEY FORMULAS (verified against CLRS Ch. 9 "Medians and Order Statistics"):
    best / average case : T(n) = T(n/2) + Theta(n) = Theta(n)
                          (work = n + n/2 + n/4 + ... = 2n)
    worst case          : T(n) = T(n-1) + Theta(n) = Theta(n^2)
                          (bad pivot peels one element each level)
    median-of-medians   : T(n) <= T(n/5) + T(7n/10) + Theta(n) = Theta(n)
                          (pivot is in the 30-70% range -> discard >= 3n/10)
    partition cost      : exactly (hi - lo) comparisons per Lomuto partition.
"""

from __future__ import annotations

import random
import sys

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (the code QUICKSELECT.md walks through)
# ============================================================================

def partition(arr, lo, hi, pivot_idx, stats):
    """Lomuto partition of arr[lo..hi]. Returns the pivot's FINAL index.

    Stash pivot at arr[hi], scan j in [lo..hi-1], swap each element <= pivot
    into a growing "small" region (indices lo..i), then drop the pivot at i+1.
    Identical to quick_sort.partition -- quickselect reuses quicksort's core.
    Counts comparisons (the arr[j] <= pivot test) in stats['comparisons'].
    """
    arr[pivot_idx], arr[hi] = arr[hi], arr[pivot_idx]
    pivot = arr[hi]
    i = lo - 1
    for j in range(lo, hi):
        stats["comparisons"] += 1
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]
    arr[i + 1], arr[hi] = arr[hi], arr[i + 1]
    return i + 1


def choose_pivot(arr, lo, hi, strategy, rng):
    """Return the INDEX of the chosen pivot for subarray arr[lo..hi]."""
    if strategy == "last":
        return hi
    if strategy == "first":
        return lo
    if strategy == "median3":
        mid = (lo + hi) // 2
        cands = sorted([(arr[lo], lo), (arr[mid], mid), (arr[hi], hi)])
        return cands[1][1]
    if strategy == "random":
        return rng.randint(lo, hi)
    raise ValueError(f"unknown strategy: {strategy}")


def quickselect(arr, lo, hi, k, strategy, rng, stats):
    """In-place quickselect: put the k-th smallest at index k. Returns arr[k].

    Only ONE side recurses (the side containing index k). That single change vs
    quicksort (which recurses both sides) is what drops the cost from O(n log n)
    to O(n) average.
    """
    if lo == hi:
        return arr[lo]
    pivot_idx = choose_pivot(arr, lo, hi, strategy, rng)
    p = partition(arr, lo, hi, pivot_idx, stats)
    if k == p:
        return arr[p]                        # pivot IS the k-th smallest -- done
    elif k < p:
        return quickselect(arr, lo, p - 1, k, strategy, rng, stats)  # left only
    else:
        return quickselect(arr, p + 1, hi, k, strategy, rng, stats)  # right only


def quickselect_select(data, k, strategy="last", seed=0):
    """Public entry: returns (k-th smallest value, comparisons). Non-destructive."""
    arr = list(data)
    rng = random.Random(seed)
    stats = {"comparisons": 0}
    val = quickselect(arr, 0, len(arr) - 1, k, strategy, rng, stats)
    return val, stats["comparisons"]


# ----------------------------------------------------------------------------
# median-of-medians pivot (BFPRT 1973) -> guaranteed O(n) worst case.
# Clean mutual recursion: select_mm drives the one-sided selection loop;
# _mom_pivot_index picks a pivot whose VALUE is the median-of-medians.
# ----------------------------------------------------------------------------
def _insertion_sort_range(arr, lo, hi, stats):
    """In-place insertion sort of arr[lo..hi]. Counts comparisons in stats."""
    for a in range(lo + 1, hi + 1):
        key = arr[a]
        b = a - 1
        while b >= lo:
            stats["comparisons"] += 1
            if arr[b] > key:
                arr[b + 1] = arr[b]
                b -= 1
            else:
                break
        arr[b + 1] = key


def _mom_pivot_index(arr, lo, hi, stats):
    """Return an index in [lo..hi] whose VALUE is the median-of-medians pivot.

    Rearranges arr[lo..hi]: sorts each group of 5, collects each group's median
    at the front (positions lo..), then recurses on those ~n/5 medians. The
    returned index holds the median-of-medians value. Recursion depth is O(log n)
    on a problem shrinking by 5x each level, so pivot selection is O(n) total.
    """
    n = hi - lo + 1
    if n <= 5:
        _insertion_sort_range(arr, lo, hi, stats)
        return (lo + hi) // 2                      # index of the group median
    out = lo
    g = lo
    while g <= hi:
        gh = min(g + 4, hi)
        _insertion_sort_range(arr, g, gh, stats)
        med = (g + gh) // 2
        arr[out], arr[med] = arr[med], arr[out]    # group median -> front slot
        out += 1
        g += 5
    num = out - lo                                  # medians now at [lo .. lo+num-1]
    return _mom_pivot_index(arr, lo, lo + num - 1, stats)   # median of the medians


def select_mm(arr, lo, hi, k, stats):
    """Median-of-medians selection. Returns the k-th smallest. O(n) worst case."""
    while True:
        if lo == hi:
            return arr[lo]
        pidx = _mom_pivot_index(arr, lo, hi, stats)     # good pivot (30-70% range)
        p = partition(arr, lo, hi, pidx, stats)
        if k == p:
            return arr[p]
        elif k < p:
            hi = p - 1
        else:
            lo = p + 1


def quickselect_mm(data, k):
    """Public entry: (k-th smallest value, comparisons) via median-of-medians."""
    arr = list(data)
    stats = {"comparisons": 0}
    val = select_mm(arr, 0, len(arr) - 1, k, stats)
    return val, stats["comparisons"]


# ----------------------------------------------------------------------------
# a full sort, counted, ONLY for the comparison table (Section C).
# ----------------------------------------------------------------------------
def sort_counted(data):
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
#    Fixed array so quickselect.html can recompute the EXACT same trace in JS.
# ============================================================================

# n=9 (odd, so the median is a single clean element). Find the median:
# sorted = [1,2,3,4,5,6,7,8,9], median (index 4) = 5.
WORKED = [3, 8, 2, 5, 1, 9, 4, 7, 6]
WORKED_K = 4                                # 0-based: the median


# ----------------------------------------------------------------------------
# Quickselect that RECORDS every partition, for the .html animation.
# ----------------------------------------------------------------------------
def quickselect_traced(arr, k, strategy="last", seed=0):
    """Traced quickselect. Non-destructive. Returns (value, levels) where each
    level is a dict:
      {'lo','hi','pivot_idx','pivot_val','partition_steps':[...],
       'pivot_final','go':'left'|'right'|'done','array':[...]}
    partition_steps mirrors quick_sort's trace (stash/compare/swap/place).
    `array` is the array state AFTER that level's partition.
    """
    a = list(arr)
    rng = random.Random(seed)
    levels = []

    def lomuto_traced(lo, hi, pivot_idx):
        a[pivot_idx], a[hi] = a[hi], a[pivot_idx]
        pivot = a[hi]
        psteps = [{"op": "stash", "pivot_val": pivot, "array": list(a),
                   "i": lo - 1, "j": None, "result": None, "pivot_final": None}]
        i = lo - 1
        for j in range(lo, hi):
            res = a[j] <= pivot
            psteps.append({"op": "compare", "pivot_val": pivot, "array": list(a),
                           "i": i, "j": j, "result": res, "pivot_final": None})
            if res:
                i += 1
                a[i], a[j] = a[j], a[i]
                psteps.append({"op": "swap", "pivot_val": pivot, "array": list(a),
                               "i": i, "j": j, "result": None, "pivot_final": None})
        a[i + 1], a[hi] = a[hi], a[i + 1]
        final = i + 1
        psteps.append({"op": "place", "pivot_val": pivot, "array": list(a),
                       "i": None, "j": None, "result": None, "pivot_final": final})
        return final, psteps

    def qs(lo, hi):
        if lo == hi:
            levels.append({"lo": lo, "hi": hi, "pivot_idx": lo,
                           "pivot_val": a[lo], "partition_steps": [],
                           "pivot_final": lo, "go": "done", "array": list(a)})
            return a[lo]
        pidx = choose_pivot(a, lo, hi, strategy, rng)
        p, psteps = lomuto_traced(lo, hi, pidx)
        if k == p:
            go = "done"
        elif k < p:
            go = "left"
        else:
            go = "right"
        levels.append({"lo": lo, "hi": hi, "pivot_idx": pidx,
                       "pivot_val": a[p], "partition_steps": psteps,
                       "pivot_final": p, "go": go, "array": list(a)})
        if go == "done":
            return a[p]
        elif go == "left":
            return qs(lo, p - 1)
        else:
            return qs(p + 1, hi)

    val = qs(0, len(a) - 1)
    return val, levels


def seeded_array(n, seed=0, lo=1, hi=99):
    rng = random.Random(seed)
    return [rng.randint(lo, hi) for _ in range(n)]


# ----------------------------------------------------------------------------
# SECTION A: the algorithm -- a full traced quickselect (find the median)
# ----------------------------------------------------------------------------

def section_algorithm():
    banner("SECTION A: the algorithm -- quickselect, find the median (k=4)")
    n = len(WORKED)
    print(f"Worked array: {fmt_arr(WORKED)}   (n = {n})")
    print(f"Goal: find the k={WORKED_K}-th smallest (0-based) = the median.\n")
    print("sorted(WORKED) =", fmt_arr(sorted(WORKED)), "-> index", WORKED_K,
          "=", sorted(WORKED)[WORKED_K], "(ground truth; quickselect does NOT sort)\n")
    print("The whole algorithm is quicksort that only walks ONE branch:\n")
    print("    partition arr[lo..hi] around a pivot -> pivot lands at index p.")
    print("    if k == p: DONE, arr[p] is the answer.")
    print("    if k <  p: recurse LEFT  only  (arr[lo..p-1]).")
    print("    if k >  p: recurse RIGHT only  (arr[p+1..hi]).\n")
    print("Quicksort recurses BOTH halves -> O(n log n); quickselect recurses")
    print("ONE half -> O(n) average. That single change is the whole algorithm.\n")

    val, levels = quickselect_traced(WORKED, WORKED_K, strategy="last")
    total_cmp = 0
    for li, lv in enumerate(levels):
        lo, hi = lv["lo"], lv["hi"]
        ncmp = sum(1 for s in lv["partition_steps"] if s["op"] == "compare")
        total_cmp += ncmp
        print(f"Level {li}: search region arr[{lo}..{hi}] (size {hi - lo + 1}), "
              f"pivot = arr[{lv['pivot_idx']}] = {lv['pivot_val']}, "
              f"{ncmp} comparisons")
        print(f"  after partition: {fmt_arr(lv['array'])}, pivot at index "
              f"{lv['pivot_final']}")
        if lv["go"] == "done":
            print(f"  k={WORKED_K} == p={lv['pivot_final']} -> DONE. "
                  f"The k-th smallest = {val}.\n")
        else:
            side = "LEFT" if lv["go"] == "left" else "RIGHT"
            print(f"  k={WORKED_K} {'<' if lv['go']=='left' else '>'} "
                  f"p={lv['pivot_final']} -> discard the other half, recurse "
                  f"{side}.\n")
    print(f"Result: the {WORKED_K}-th smallest of {fmt_arr(WORKED)} = {val} "
          f"(== sorted median).")
    print(f"Total comparisons = {total_cmp}. (Full sort would take ~")
    print(f"n log2 n = {n * _log2(n):.0f}; quickselect did {total_cmp} by walking")
    print("one branch per level.)\n")
    assert val == sorted(WORKED)[WORKED_K], "BUG: wrong selection!"
    assert val == quickselect_select(WORKED, WORKED_K, "last")[0]
    print("[check] quickselect result == sorted(WORKED)[k]:  OK")


def _log2(n):
    import math
    return math.log2(n)


# ----------------------------------------------------------------------------
# SECTION B: complexity analysis -- why O(n) average, O(n^2) worst
# ----------------------------------------------------------------------------

def section_complexity():
    banner("SECTION B: complexity -- O(n) average, O(n^2) worst (same pivot trap as quicksort)")
    print("AVERAGE case (good / random pivot splits ~in half):")
    print("    Each level does O(n) partition work, then recurses into ONE side")
    print("    of size ~n/2, then n/4, ... The work telescopes:")
    print("        T(n) = n + n/2 + n/4 + ... = 2n = Theta(n).")
    print("    (Quicksort recurses BOTH sides -> n + 2*(n/2) + 4*(n/4) + ... =")
    print("    n log n. Walking one branch is what halts the doubling.)\n")
    print("WORST case (pivot is always the smallest/largest):")
    print("    Each level peels off ONE element, recursing into size n-1:")
    print("        T(n) = n + (n-1) + (n-2) + ... = n(n+1)/2 = Theta(n^2).")
    print("    Same trap as quicksort: 'last'/'first' pivot on sorted input.\n")

    # Empirical: comparisons vs n, averaged over random inputs (random pivot).
    print("Empirical scaling -- comparisons vs n (mean over 200 random inputs,")
    print("random pivot). Compare to n and to n log2 n (full sort):\n")
    print(f"  {'n':>6}  {'quickselect (avg)':>18}  {'  / n':>8}  "
          f"{'sort (n log2 n)':>16}  {'  ratio qs/sort':>14}")
    for n in [64, 256, 1024, 4096]:
        trials = 200
        tot = 0
        for t in range(trials):
            data = seeded_array(n, seed=t)
            _, c = quickselect_select(data, n // 2, strategy="random", seed=t)
            tot += c
        avg = tot / trials
        nlogn = n * _log2(n)
        print(f"  {n:>6}  {avg:>18.1f}  {avg / n:>8.2f}  {nlogn:>16.0f}  "
              f"{avg / nlogn:>13.2%}")
    print("\nRead it: quickselect comparisons grow ~ LINEARLY in n (the / n")
    print("column is roughly constant ~ a few). A full sort is n log2 n, so")
    print("quickselect is ~1/log2(n) of the sort cost -- e.g. ~1/6 at n=64,")
    print("~1/12 at n=4096. That is the payoff of walking one branch.\n")

    # The worst case, concretely: last-pivot on sorted input, finding the MIN
    # (k=0). Each partition peels the max, recursing into [0..hi-1] every time,
    # down to size 1 -> exactly n(n-1)/2 comparisons. (Finding the median k=n//2
    # is also O(n^2) but stops at ~half that.)
    print("Worst case, concretely -- 'last' pivot on a SORTED array, find the MIN")
    print("(k=0). Each partition peels the max and recurses into [0..hi-1], so it")
    print("walks the whole shrinking array: n + (n-1) + ... + 1.\n")
    n = 256
    sorted_data = list(range(n))
    _, c_worst = quickselect_select(sorted_data, 0, strategy="last")
    _, c_rand = quickselect_select(sorted_data, n // 2, strategy="random", seed=0)
    n2 = n * (n - 1) // 2
    print(f"  n = {n}")
    print(f"  last pivot,  k=0 (min) : {c_worst} comparisons  (== n(n-1)/2 = {n2}, O(n^2))")
    print(f"  random pivot, k=median : {c_rand} comparisons   (linear, dodges the trap)")
    print(f"  [check] last-pivot-on-sorted, k=0 == n(n-1)/2 == {n2}:  "
          f"{'OK' if c_worst == n2 else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: median-of-medians (BFPRT) -- the O(n) worst-case guarantee
# ----------------------------------------------------------------------------

def section_median_of_medians():
    banner("SECTION C: median-of-medians (BFPRT 1973) -- the O(n) WORST-CASE guarantee")
    print("The O(n^2) worst case is real (Section B). Median-of-medians kills it")
    print("by spending extra work to pick a pivot GUARANTEED to be good.\n")
    print("THE RULE (Blum, Floyd, Pratt, Rivest, Tarjan 1973):")
    print("  1. Split arr[lo..hi] into groups of 5 (last group may be smaller).")
    print("  2. Sort each group (<=5 elements, O(1)) and take its median.")
    print("  3. Recursively find the MEDIAN of those medians -> use as pivot.\n")
    print("WHY IT IS LINEAR: half of the ~n/5 group-medians are <= the pivot,")
    print("and each of those is >= 2 elements in its own group. So at least")
    print("3 elements out of every 10 are guaranteed <= pivot (and 3/10 >= it).")
    print("The pivot is in the 30%-70% range, so each partition discards >= 3n/10:")
    print("    T(n) <= T(n/5) [find medians] + T(7n/10) [recurse one side] + O(n)")
    print("        = Theta(n).     (1/5 + 7/10 = 0.9 < 1 -> the recursion sums linearly.)\n")
    print("THE TRADE: the constant is ~5-10x quickselect's, so in practice people")
    print("use INTROSELECT (quickselect + median-of-medians fallback past a depth")
    print("limit). That is exactly std::nth_element: quickselect's speed, linear")
    print("guarantee. See QUICKSELECT.md for the parallel with introsort.\n")

    # Empirical: worst-case comparisons, several strategies x inputs, n=256.
    n = 256
    inputs = {
        "random":   seeded_array(n, seed=0),
        "sorted":   list(range(n)),
        "reversed": list(range(n, 0, -1)),
    }
    print(f"Comparisons to find the median (n={n}), by strategy x input:\n")
    print(f"  {'input':<10}  {'last':>8}  {'median3':>8}  {'random':>8}  "
          f"{'mm (BFPRT)':>11}  {'full sort':>10}")
    print("  " + "-" * 70)
    for label, data in inputs.items():
        _, c_last = quickselect_select(data, n // 2, "last")
        _, c_m3 = quickselect_select(data, n // 2, "median3")
        _, c_rand = quickselect_select(data, n // 2, "random", seed=0)
        _, c_mm = quickselect_mm(data, n // 2)
        _, c_sort = sort_counted(data)
        v_mm = quickselect_mm(data, n // 2)[0]
        assert v_mm == sorted(data)[n // 2], "BUG: mm wrong!"
        print(f"  {label:<10}  {c_last:>8}  {c_m3:>8}  {c_rand:>8}  "
              f"{c_mm:>11}  {c_sort:>10}")
    print()
    print("Read the 'sorted'/'reversed' rows: 'last' pivot blows up to ~n(n-1)/2")
    print("(O(n^2)); median-of-medians stays linear (~ a few x n) on EVERY input,")
    print("including the hostile ones. That guaranteed linearity is what BFPRT")
    print("buys you -- at a constant-factor cost (compare mm vs random on 'random').")

    # assert mm is never worse than ~20*n even on the worst input here
    worst_mm = max(quickselect_mm(d, n // 2)[1] for d in inputs.values())
    print(f"\n[check] median-of-medians worst (over inputs) <= 20n = {20 * n}:  "
          f"{'OK' if worst_mm <= 20 * n else 'FAIL'}  (was {worst_mm})")


# ----------------------------------------------------------------------------
# SECTION D: applications -- when to select instead of sort
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION D: applications -- when to SELECT instead of SORT")
    print("USE quickselect when you need ONE order statistic (or a few), not the")
    print("whole sorted order:\n")
    print("  - MEDIAN of a dataset: the canonical use. O(n) vs O(n log n) to sort.")
    print("  - PERCENTILES / quantiles: P95 latency, box-plot whiskers, the k-th")
    print("    largest sale. Select index k = p*n for the p-th percentile.")
    print("  - top-k / bottom-k: select the k-th element, then everything on one")
    print("    side is your set (O(n + k log k) to finish-sort the top-k).")
    print("  - outlier / anomaly thresholds: 'is this value above the 99th pct?'")
    print("    select once, then compare.\n")
    print("Where it lives in the wild:")
    print("  - C++  std::nth_element  -- introselect (quickselect + mm fallback).")
    print("  - numpy.partition / np.median (small arrays) -- introselect-based.")
    print("  - quickselect is the subroutine behind 'median-of-medians' pivot")
    print("    selection in some quicksort variants.\n")
    print("WHEN NOT to use it:")
    print("  - you need the WHOLE array sorted -> just sort (O(n log n)).")
    print("  - you need MANY order statistics from the same array -> sort once,")
    print("    then every k-th query is O(1). Quickselect per query would be")
    print("    O(n) each -> worse than one O(n log n) sort after ~log n queries.")
    print("  - the array is tiny -> the constant factors of partition/recursion")
    print("    dominate; a small sort is simpler and as fast.")
    print("  - you need a WORST-CASE linear guarantee on adversarial input and")
    print("    can't afford introselect's fallback machinery -> median-of-medians")


# ----------------------------------------------------------------------------
# SECTION G: GOLD -- pins values for quickselect.html to recompute in JS.
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION G: GOLD values (pinned for quickselect.html)")
    val, levels = quickselect_traced(WORKED, WORKED_K, strategy="last")
    last_val, last_cmp = quickselect_select(WORKED, WORKED_K, "last")
    m3_cmp = quickselect_select(WORKED, WORKED_K, "median3")[1]
    rand_cmp = quickselect_select(WORKED, WORKED_K, "random", seed=0)[1]
    mm_val, mm_cmp = quickselect_mm(WORKED, WORKED_K)
    print(f"WORKED = {fmt_arr(WORKED)}  (n={len(WORKED)}, k={WORKED_K})\n")
    print(f"GOLD median (k-th smallest)        = {val}")
    print(f"GOLD quickselect levels (recursions) = {len(levels)}")
    # per-level: pivot value, pivot final index, which side
    print("GOLD per-level pivots:")
    for li, lv in enumerate(levels):
        print(f"  level {li}: pivot {lv['pivot_val']} lands at index "
              f"{lv['pivot_final']}, go={lv['go']}")
    print(f"GOLD last-pivot    comparisons = {last_cmp}")
    print(f"GOLD median3       comparisons = {m3_cmp}")
    print(f"GOLD random(seed0) comparisons = {rand_cmp}")
    print(f"GOLD mm (BFPRT)    comparisons = {mm_cmp}, value = {mm_val}")
    # self-consistency
    assert val == sorted(WORKED)[WORKED_K]
    assert mm_val == val
    assert last_cmp == quickselect_select(WORKED, WORKED_K, "last")[1]
    print("\n[check] gold median reproduces from quickselect_select() & mm:  OK")
    print("[check] gold per-level trace reproduces from quickselect_traced():  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("quickselect.py - reference impl. All numbers below feed QUICKSELECT.md.")
    print("python", sys.version.split()[0])

    section_algorithm()
    section_complexity()
    section_median_of_medians()
    section_applications()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
