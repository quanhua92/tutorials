"""
bubble_sort.py - Reference implementation of Bubble Sort with the early-exit
flag, fully traced.

This is the single source of truth that BUBBLE_SORT.md is built from and that
bubble_sort.html replays step-by-step. Every number in the guide and every
frame of the animation is produced by this file - nothing is hand-computed.

Run:
    uv run python bubble_sort.py

==========================================================================
THE INTUITION (read this first) - heavy bubbles sink, light ones rise
==========================================================================
Picture the array as a row of bubbles in water, laid out left to right. Each
PASS scans adjacent pairs left-to-right; whenever the LEFT bubble is HEAVIER
than its right neighbour, they SWAP. So the heaviest bubble "sinks" one step
at a time to the far right. After pass k, the k largest values are locked in
their final positions at the tail - no later pass touches them.

THE EARLY-EXIT FLAG (the whole reason bubble sort isn't always O(n^2)):
    If a pass completes with ZERO swaps, the array is already sorted - stop
    immediately. On an already-sorted input this means just ONE pass of n-1
    comparisons -> best case O(n), not O(n^2). Without the flag, bubble sort
    is always O(n^2) regardless of input.

THE INVARIANT (why it is correct):
    After pass i, the last i+1 elements are the i+1 largest, in final order.
    Equivalently: the unsorted region is arr[0 .. n-2-i].

WHY ONE SWAP PER INVERSION (a useful identity, used in Section B):
    Each swap fixes EXACTLY ONE inversion (an out-of-order pair). Bubble sort
    removes inversions one adjacent-swap at a time, so #swaps == #inversions
    in the input. On [64,34,25,12,22,11,90] there are 14 inversions, so it
    does exactly 14 swaps.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  pass         : one left-to-right scan over the (shrinking) unsorted region.
  compare      : checking arr[j] > arr[j+1]. A pass's cost = #compares in it.
  swap         : exchanging an out-of-order adjacent pair. Fixes 1 inversion.
  inversion    : a pair (i<j) with arr[i] > arr[j]. A sorted array has 0.
  early exit   : stop the whole sort the first time a pass does 0 swaps.
  stable       : equal keys keep their relative order. Bubble sort IS stable
                 (we only swap on strict >, never >=).

==========================================================================
COMPLEXITY  (n = len(arr);  all verified in Section C)
==========================================================================
  comparisons : best  n-1        (already sorted -> early exit after pass 0)
                avg   Theta(n^2)
                worst n(n-1)/2    (reverse sorted; early exit never helps)
  swaps       : best  0          avg  ~ n(n-1)/4   worst  n(n-1)/2  (= inversions)
  space       : O(1), in place
  adaptive    : YES (only with the early-exit flag)
  stable      : YES
  Source: Knuth, TAOCP Vol 3, Section 5.2.2 (exchange / bubble sorting).
"""

from __future__ import annotations

import json

BANNER = "=" * 72

# The canonical worked example - identical input to insertion_sort.py so the
# two bundles can be compared head-to-head (Section D).
INPUT = [64, 34, 25, 12, 22, 11, 90]


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (the code BUBBLE_SORT.md walks through)
# ============================================================================

def bubble_sort_traced(arr):
    """Bubble sort WITH the early-exit flag, fully traced.

    Returns
    -------
    sorted_arr : list[int]      a fresh sorted copy (input is untouched)
    trace      : list[dict]     one frame per comparison (plus an initial frame)
    comparisons: int            total compare operations
    swaps      : int            total adjacent swaps

    Each trace frame has the SAME shape the .html animates:
        {a: [...], cmp: [j, j+1] or None, swp: [j, j+1] or None, pass: i}
    Frame 0 is the initial state (cmp=None, swp=None). Every later frame is
    one comparison; swp is set to the swapped pair only when a swap happened.
    """
    a = list(arr)
    n = len(a)
    trace = [{"a": list(a), "cmp": None, "swp": None, "pass": -1}]
    comparisons = 0
    swaps = 0
    for i in range(n - 1):
        swapped = False
        for j in range(n - 1 - i):
            comparisons += 1
            will_swap = a[j] > a[j + 1]
            if will_swap:
                a[j], a[j + 1] = a[j + 1], a[j]
                swaps += 1
                swapped = True
            trace.append({
                "a": list(a),
                "cmp": [j, j + 1],
                "swp": [j, j + 1] if will_swap else None,
                "pass": i,
            })
        if not swapped:                 # early exit: this pass ordered nothing
            break
    return a, trace, comparisons, swaps


def count_inversions(arr):
    """#inversions via insertion-count: pairs (i<j) with arr[i] > arr[j]."""
    a = list(arr)
    n = len(a)
    inv = 0
    for i in range(1, n):
        key = a[i]
        j = i - 1
        while j >= 0 and a[j] > key:
            a[j + 1] = a[j]
            j -= 1
            inv += 1
        a[j + 1] = key
    return inv


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_arr(a):
    return "[" + ", ".join(f"{x:>3}" for x in a) + "]"


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the algorithm walkthrough, pass by pass, on the canonical input
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the algorithm walkthrough  on " + str(INPUT))
    sorted_a, trace, comp, swaps = bubble_sort_traced(INPUT)
    n = len(INPUT)
    print(f"Input  n={n}: {fmt_arr(INPUT)}")
    print(f"Goal: sort ascending. Compare ADJACENT pairs; swap if left > right.\n")
    print("Legend:  (j vs j+1)  compare pair   |  <->  swapped   |  .  in order\n")

    pass_no = None
    pass_comp = 0
    pass_swap = 0
    for f in trace[1:]:                      # skip the initial frame
        i = f["pass"]
        j = f["cmp"][0]
        op = "<->" if f["swp"] else " . "
        if i != pass_no:
            if pass_no is not None:
                print(f"        pass {pass_no} subtotal: "
                      f"{pass_comp} compares, {pass_swap} swaps "
                      f"-> tail {pass_no + 1} locked\n")
            pass_no = i
            pass_comp = pass_swap = 0
            print(f"--- PASS {i} ---  unsorted region = arr[0 .. {n - 2 - i}]  "
                  f"(scan indices 0..{n - 2 - i})")
        pass_comp += 1
        if f["swp"]:
            pass_swap += 1
        lo = trace[idx_of(trace, f) - 1]["a"][j]   # value at j before this frame
        hi = trace[idx_of(trace, f) - 1]["a"][j + 1]
        print(f"  j={j}: compare {lo:>2} vs {hi:<2}  {op}  -> {fmt_arr(f['a'])}")
    if pass_no is not None:
        print(f"        pass {pass_no} subtotal: {pass_comp} compares, "
              f"{pass_swap} swaps -> tail {pass_no + 1} locked\n")

    print(f"RESULT: {fmt_arr(sorted_a)}")
    print(f"TOTALS: {comp} comparisons, {swaps} swaps.\n")
    print("Read it top-to-bottom: 90 sank to the end in pass 0, then 64 in "
          "pass 1, then 34 in pass 2 ... each pass locks one more element at "
          "the tail. The last pass that changes nothing would trigger the "
          "EARLY EXIT (see Section C best-case).")
    return sorted_a, trace, comp, swaps


def idx_of(trace, frame):
    """Index of `frame` within `trace` (frames are unique objects)."""
    for k, fr in enumerate(trace):
        if fr is frame:
            return k
    return -1


# ----------------------------------------------------------------------------
# SECTION B: count comparisons + swaps, and the inversions identity
# ----------------------------------------------------------------------------

def section_b(sorted_a, comp, swaps):
    banner("SECTION B: counting comparisons and swaps")
    inv = count_inversions(INPUT)
    n = len(INPUT)
    print(f"Input {fmt_arr(INPUT)}  (n={n})\n")
    print(f"  comparisons performed : {comp}")
    print(f"  swaps performed       : {swaps}")
    print(f"  inversions in input   : {inv}\n")
    print("THE INVARIANTS:")
    print(f"  [1] swaps == inversions?  {swaps} == {inv}  -> "
          f"{'OK' if swaps == inv else 'FAIL'}")
    max_pairs = n * (n - 1) // 2
    print(f"  [2] comparisons <= n(n-1)/2 = {max_pairs}?  {comp} <= {max_pairs}  -> "
          f"{'OK' if comp <= max_pairs else 'FAIL'}")
    # note why comparisons == max_pairs here despite early exit
    print()
    print("Note: comparisons hit the MAXIMUM n(n-1)/2 here even WITH the early-")
    print("exit flag, because every pass up to the last still does swaps (the")
    print("array is far from sorted). Early exit only saves comparisons when a")
    print("pass makes ZERO swaps - i.e. on already- or nearly-sorted input.")
    print("Compare with the best case in Section C (6 comparisons).")
    assert swaps == inv
    assert comp <= max_pairs
    print("\n[check] invariants hold: OK")


# ----------------------------------------------------------------------------
# SECTION C: best / average / worst analysis (concrete on n=7)
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: best / average / worst  (n = len(arr))")
    n = len(INPUT)
    best_in = list(range(1, n + 1))                  # already sorted
    worst_in = list(range(n, 0, -1))                 # reverse sorted
    _, _, comp_best, swap_best = bubble_sort_traced(best_in)
    _, _, comp_worst, swap_worst = bubble_sort_traced(worst_in)
    _, _, comp_ours, swap_ours = bubble_sort_traced(INPUT)

    print(f"n = {n}.  worst-pair-count = n(n-1)/2 = {n*(n-1)//2}.\n")
    print(f"| case     | input                | comparisons | swaps | passes |")
    print(f"|----------|----------------------|-------------|-------|--------|")
    print(f"| BEST     | {str(best_in):<20} | {comp_best:<11} | {swap_best:<5} | "
          f"{n_passes(bubble_sort_traced(best_in)[1]):<6} |")
    print(f"| OUR INPUT| {str(INPUT):<20} | {comp_ours:<11} | {swap_ours:<5} | "
          f"{n_passes(bubble_sort_traced(INPUT)[1]):<6} |")
    print(f"| WORST    | {str(worst_in):<20} | {comp_worst:<11} | {swap_worst:<5} | "
          f"{n_passes(bubble_sort_traced(worst_in)[1]):<6} |")
    print()
    print("Reading the table:")
    print(f"  BEST   (already sorted): early exit fires after pass 0 -> only "
          f"{comp_best} comparisons, {swap_best} swaps.  =>  O(n).")
    print(f"  WORST  (reverse sorted): every pass swaps until the last -> "
          f"{comp_worst} = {n*(n-1)//2} comparisons, {swap_worst} swaps.  =>  O(n^2).")
    print(f"  AVERAGE: Theta(n^2) comparisons and ~ n(n-1)/4 swaps on random input.")
    print()
    print("The early-exit flag is what makes bubble sort ADAPTIVE: cost tracks")
    print("how disordered the input is. Strip the flag and EVERY input costs "
          f"{n*(n-1)//2} comparisons - best case collapses to O(n^2).")
    # sanity assertions
    assert comp_best == n - 1 and swap_best == 0
    assert comp_worst == n * (n - 1) // 2 and swap_worst == n * (n - 1) // 2
    print("\n[check] best==(n-1) and worst==n(n-1)/2: OK")


def n_passes(trace):
    """Number of passes actually executed (pass indices seen, +1)."""
    ps = {f["pass"] for f in trace if f["pass"] >= 0}
    return len(ps)


# ----------------------------------------------------------------------------
# SECTION D: when to use bubble sort (+ head-to-head vs insertion sort)
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: when to use bubble sort  (vs insertion sort, same input)")
    # import-free: replicate the swap-based insertion sort counts here
    def insertion_counts(arr):
        a = list(arr)
        n = len(a)
        comp = swap = 0
        for i in range(1, n):
            j = i
            while j > 0 and a[j - 1] > a[j]:
                a[j], a[j - 1] = a[j - 1], a[j]
                comp += 1
                swap += 1
                j -= 1
            if j > 0:                 # the final failed comparison
                comp += 1
        return comp, swap

    b_comp, b_swap = bubble_sort_traced(INPUT)[2], bubble_sort_traced(INPUT)[3]
    i_comp, i_swap = insertion_counts(INPUT)
    print(f"Same input {fmt_arr(INPUT)}:\n")
    print(f"| algorithm     | comparisons | swaps/shifts |")
    print(f"|---------------|-------------|--------------|")
    print(f"| bubble sort   | {b_comp:<11} | {b_swap:<12} |")
    print(f"| insertion sort| {i_comp:<11} | {i_swap:<12} |")
    print()
    print("Insertion sort does FEWER comparisons here because its inner loop")
    print("STOPS the moment it finds a smaller element, whereas bubble sort")
    print("always scans the whole unsorted region. Swaps are EQUAL (both fix")
    print("exactly one inversion per swap, and there are 14 inversions).\n")
    print("USE BUBBLE SORT WHEN:")
    print("  * you are TEACHING / explaining an adaptive, stable sort - its")
    print("    correctness invariant ('each pass locks the next largest') is")
    print("    the easiest of any sort to see.")
    print("  * the input is tiny (n < ~16) AND you want a 10-line, in-place,")
    print("    stable, no-allocation sort.")
    print("DO NOT use it when performance matters - insertion sort (or the")
    print("stdlib's Timsort, which uses insertion sort for small runs) is")
    print("strictly better in practice: same O(n^2) worst case but fewer")
    print("comparisons and better cache behaviour. See INSERTION_SORT.md.")


# ============================================================================
# 4. GOLD CHECK + TRACE EXPORT (the .html replays this exact trace)
# ============================================================================

def gold_check(sorted_a):
    banner("GOLD CHECK")
    expected = sorted(INPUT)
    ok = sorted_a == expected
    print(f"  bubble_sort({INPUT})")
    print(f"  = {sorted_a}")
    print(f"  sorted(input)        = {expected}")
    print(f"  match? {ok}  ->  {'GOLD OK' if ok else 'GOLD FAIL'}")
    assert ok
    print("[check] sorted output == sorted(input): OK")
    return ok


def export_trace(trace):
    print("\n# ---- TRACE for bubble_sort.html (one frame per comparison) ----")
    print("# frame: {a: [...], cmp: [j,j+1]|null, swp: [j,j+1]|null, pass: i}")
    print("const TRACE = " + json.dumps(trace) + ";")
    print("# ----------------------------------------------------------------")


# ============================================================================
# main
# ============================================================================

def main():
    print("bubble_sort.py - reference impl. All numbers below feed "
          "BUBBLE_SORT.md + bubble_sort.html.")
    sorted_a, trace, comp, swaps = section_a()
    section_b(sorted_a, comp, swaps)
    section_c()
    section_d()
    gold_check(sorted_a)
    export_trace(trace)
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
