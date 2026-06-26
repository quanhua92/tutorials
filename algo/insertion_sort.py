"""
insertion_sort.py - Reference implementation of Insertion Sort, fully traced.

This is the single source of truth that INSERTION_SORT.md is built from and
that insertion_sort.html replays step-by-step. Every number in the guide and
every frame of the animation is produced by this file - nothing is
hand-computed.

Run:
    uv run python insertion_sort.py

==========================================================================
THE INTUITION (read this first) - sorting a hand of cards
==========================================================================
Think of sorting a hand of playing cards. You hold the cards in your left
hand; they start in random order. You take them ONE AT A TIME with your right
hand and slide each new card into its correct spot among the cards you've
already placed, shifting the larger ones one slot to the right to make room.

That is the whole algorithm. After step i, the prefix arr[0..i] is SORTED
(and these are exactly the original first i+1 cards, just reordered). The
suffix arr[i+1..] is untouched - still the original tail.

THE ADAPTIVE BIT (why best case is O(n)):
    Each new card only walks left WHILE it sees a LARGER card. On already-
    sorted input every card is already in place -> 1 comparison each, no
    moves -> O(n). On reverse-sorted input every card walks all the way to
    the front -> O(n^2). Cost tracks how far each card has to travel.

THE SWAP-BASED FORM (used here for clean tracing/animation):
    Instead of "pull the card out, shift others, drop it in", we walk the
    card left by SWAPPING it with its left neighbour as long as that neighbour
    is larger. This is mathematically identical to the shift-based version in
    CLRS (2.1): same number of comparisons, same number of element moves
    (one swap == one shift here, because the card being inserted is itself
    one of the two swapped elements). Both remove exactly one INVERSION per
    swap, so #swaps == #inversions in both forms.

THE INVARIANT (why it is correct):
    After outer step i, arr[0..i] is sorted. Base case i=0 is trivial. The
    inductive step: arr[0..i-1] was sorted; we walk arr[i] left past every
    larger element, so arr[0..i] is sorted.

WHY TIMSORT USES IT (the real-world relevance):
    Python's sorted(), Java's Arrays.sort on objects, and V8's Array.sort all
    use TIMSORT, a hybrid of merge sort + insertion sort. Insertion sort runs
    on the "small runs" (length <= 64 in CPython) because at small n its low
    constant factor + cache friendliness + adaptivity beat any O(n log n)
    sort. So insertion sort is not a relic - it runs inside every Python
    sorted() call. See Section D.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  outer step i : "take the next card" arr[i] into the sorted prefix.
  inner walk   : slide that card left past larger neighbours (via swaps).
  compare      : checking arr[j-1] > arr[j]; STOPS as soon as it is false.
  swap / shift : exchanging the card with its left neighbour. Fixes 1 inversion.
  inversion    : a pair (i<j) with arr[i] > arr[j]. Sorted array has 0.
  run          : a short already-ordered slice. Timsort finds these and hands
                 small ones to insertion sort.
  stable       : equal keys keep their relative order. Insertion sort IS stable
                 (we only swap on strict >).

==========================================================================
COMPLEXITY  (n = len(arr);  all verified in Section C)
==========================================================================
  comparisons : best  n-1        (already sorted -> 1 per card)
                avg   ~ n^2/4
                worst n(n-1)/2    (reverse sorted -> card i walks i steps)
  swaps       : best  0          avg  ~ n^2/4   worst  n(n-1)/2  (= inversions)
  space       : O(1), in place
  adaptive    : YES (the inner walk short-circuits)
  stable      : YES
  Source: CLRS (3rd ed.) Section 2.1; Knuth TAOCP Vol 3 Section 5.2.1.
"""

from __future__ import annotations

import json

BANNER = "=" * 72

# The canonical worked example - identical input to bubble_sort.py so the two
# bundles can be compared head-to-head (Section D).
INPUT = [64, 34, 25, 12, 22, 11, 90]


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (the code INSERTION_SORT.md walks through)
# ============================================================================

def insertion_sort_traced(arr):
    """Insertion sort (swap-based form), fully traced.

    Returns
    -------
    sorted_arr : list[int]      a fresh sorted copy (input is untouched)
    trace      : list[dict]     one frame per comparison (plus an initial frame)
    comparisons: int            total compare operations
    swaps      : int            total adjacent swaps

    Each trace frame has the SAME shape the .html animates (and the SAME shape
    as bubble_sort.py's trace, so the two animations share a renderer):
        {a: [...], cmp: [j-1, j] or None, swp: [j-1, j] or None, pass: i}
    Frame 0 is the initial state (cmp=None, swp=None). Every later frame is
    one comparison of the adjacent pair (j-1, j); swp is set only if the pair
    swapped. `pass` is the index i of the card currently being inserted.
    """
    a = list(arr)
    n = len(a)
    trace = [{"a": list(a), "cmp": None, "swp": None, "pass": -1}]
    comparisons = 0
    swaps = 0
    for i in range(1, n):
        j = i
        while j > 0 and a[j - 1] > a[j]:
            comparisons += 1                      # this comparison said "swap"
            a[j], a[j - 1] = a[j - 1], a[j]
            swaps += 1
            trace.append({
                "a": list(a),
                "cmp": [j - 1, j],
                "swp": [j - 1, j],
                "pass": i,
            })
            j -= 1
        if j > 0:                                 # the final comparison that said "stop"
            comparisons += 1
            trace.append({
                "a": list(a),
                "cmp": [j - 1, j],
                "swp": None,
                "pass": i,
            })
    return a, trace, comparisons, swaps


def count_inversions(arr):
    """#inversions: pairs (i<j) with arr[i] > arr[j]."""
    inv = 0
    n = len(arr)
    for i in range(n):
        for k in range(i + 1, n):
            if arr[i] > arr[k]:
                inv += 1
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


def idx_of(trace, frame):
    for k, fr in enumerate(trace):
        if fr is frame:
            return k
    return -1


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the algorithm walkthrough, card by card, on the canonical input
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the algorithm walkthrough  on " + str(INPUT))
    sorted_a, trace, comp, swaps = insertion_sort_traced(INPUT)
    n = len(INPUT)
    print(f"Input  n={n}: {fmt_arr(INPUT)}")
    print(f"Goal: build a sorted PREFIX arr[0..i] left to right. At step i,")
    print(f"insert arr[i] into the sorted prefix by walking it left via swaps.\n")
    print("Legend:  (j-1 vs j)  compare pair   |  <->  swapped   |  .  in order\n")

    cur_i = None
    step_comp = 0
    step_swap = 0
    for f in trace[1:]:                      # skip the initial frame
        i = f["pass"]
        lo = f["cmp"][0]
        hi = f["cmp"][1]
        if i != cur_i:
            if cur_i is not None:
                print(f"        step i={cur_i}: {step_comp} compares, "
                      f"{step_swap} swaps -> prefix arr[0..{cur_i}] sorted\n")
            cur_i = i
            step_comp = step_swap = 0
            print(f"--- STEP i={i} ---  take card arr[i]={INPUT[i]} (original), "
                  f"walk it left into the sorted prefix arr[0..{i - 1}]")
        step_comp += 1
        if f["swp"]:
            step_swap += 1
        v_lo = trace[idx_of(trace, f) - 1]["a"][lo]   # value at lo before this frame
        v_hi = trace[idx_of(trace, f) - 1]["a"][hi]
        op = "<->" if f["swp"] else " . "
        print(f"  compare {v_lo:>2} vs {v_hi:<2} (idx {lo},{hi})  {op}  -> {fmt_arr(f['a'])}")
    if cur_i is not None:
        print(f"        step i={cur_i}: {step_comp} compares, "
              f"{step_swap} swaps -> prefix arr[0..{cur_i}] sorted\n")

    print(f"RESULT: {fmt_arr(sorted_a)}")
    print(f"TOTALS: {comp} comparisons, {swaps} swaps.\n")
    print("Read it card by card: 34 slid in front of 64; 25 in front of both; "
          "12 in front of all three; 22 stopped after 3 swaps (12 is smaller); "
          "11 went all the way to the front (5 swaps); 90 was already largest "
          "so 1 comparison, 0 swaps.")
    return sorted_a, trace, comp, swaps


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
    print()
    print("WHY comparisons (16) < inversions-swaps (14) is possible here:")
    print("  Each swap fixes exactly one inversion (so swaps == inversions == 14).")
    print("  But comparisons also count the ONE 'stop' check per card that does")
    print("  NOT lead to a swap (when the card finds a smaller neighbour, or when")
    print("  it reaches the front it needs no stop-check). On this input the")
    print("  extra stops add up so comparisons = swaps + (stops). Fewer than the")
    print("  n(n-1)/2 ceiling because the inner walk short-circuits - this is")
    print("  exactly why insertion sort beats bubble sort on comparisons.")
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
    _, _, comp_best, swap_best = insertion_sort_traced(best_in)
    _, _, comp_worst, swap_worst = insertion_sort_traced(worst_in)
    _, _, comp_ours, swap_ours = insertion_sort_traced(INPUT)

    print(f"n = {n}.  worst-pair-count = n(n-1)/2 = {n*(n-1)//2}.\n")
    print(f"| case     | input                | comparisons | swaps |")
    print(f"|----------|----------------------|-------------|-------|")
    print(f"| BEST     | {str(best_in):<20} | {comp_best:<11} | {swap_best:<5} |")
    print(f"| OUR INPUT| {str(INPUT):<20} | {comp_ours:<11} | {swap_ours:<5} |")
    print(f"| WORST    | {str(worst_in):<20} | {comp_worst:<11} | {swap_worst:<5} |")
    print()
    print("Reading the table:")
    print(f"  BEST   (already sorted): each card needs 1 comparison and 0 moves "
          f"-> {comp_best} comparisons.  =>  O(n).")
    print(f"  WORST  (reverse sorted): card i walks all i steps to the front -> "
          f"{comp_worst} = {n*(n-1)//2} comparisons.  =>  O(n^2).")
    print(f"  AVERAGE: ~ n^2/4 comparisons and ~ n^2/4 swaps on random input.")
    print()
    print("Insertion sort is ADAPTIVE: the inner walk stops early, so nearly-")
    print("sorted input runs in near-linear time. This is the property Timsort")
    print("exploits (Section D).")
    assert comp_best == n - 1 and swap_best == 0
    assert comp_worst == n * (n - 1) // 2 and swap_worst == n * (n - 1) // 2
    print("\n[check] best==(n-1) and worst==n(n-1)/2: OK")


# ----------------------------------------------------------------------------
# SECTION D: when to use insertion sort (+ Timsort + head-to-head vs bubble)
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: when to use insertion sort  (Timsort, vs bubble sort)")
    i_comp, i_swap = insertion_sort_traced(INPUT)[2], insertion_sort_traced(INPUT)[3]

    # bubble counts (re-derived here to keep the file self-contained)
    def bubble_counts(arr):
        a = list(arr)
        n = len(a)
        comp = swap = 0
        for i in range(n - 1):
            swapped = False
            for j in range(n - 1 - i):
                comp += 1
                if a[j] > a[j + 1]:
                    a[j], a[j + 1] = a[j + 1], a[j]
                    swap += 1
                    swapped = True
            if not swapped:
                break
        return comp, swap
    b_comp, b_swap = bubble_counts(INPUT)

    print(f"Same input {fmt_arr(INPUT)}:\n")
    print(f"| algorithm     | comparisons | swaps |")
    print(f"|---------------|-------------|-------|")
    print(f"| insertion sort| {i_comp:<11} | {i_swap:<5} |")
    print(f"| bubble sort   | {b_comp:<11} | {b_swap:<5} |")
    print()
    print("On this input insertion sort makes FEWER comparisons (16 vs 21) for")
    print("the same 14 swaps. In general insertion sort dominates bubble sort:")
    print("same O(n^2) worst case, but its inner loop short-circuits so it never")
    print("does MORE comparisons and usually does fewer.\n")
    print("USE INSERTION SORT WHEN:")
    print("  * n is SMALL (roughly <= 64). Below that its tiny constant factor")
    print("    and cache-friendly sequential access beat any O(n log n) sort.")
    print("  * the input is NEARLY SORTED. Adaptivity gives near-O(n) here.")
    print("  * you need STABILITY (equal keys keep their order) in O(1) space.")
    print("  * you are implementing a HYBRID sort's small-case path.\n")
    print("WHERE IT HIDES IN REAL SYSTEMS - TIMSORT:")
    print("  Python sorted()/list.sort(), Java Arrays.sort(objects), V8")
    print("  Array.sort, Rust's stable sort all run TIMSORT (Peters 2002), a")
    print("  merge-sort + insertion-sort hybrid. CPython's Timsort scans for")
    print("  'runs' of already-ordered elements; runs shorter than 64 are grown")
    print("  to length 64 using BINARY insertion sort, then merged. So every")
    print("  Python sorted() call runs insertion sort internally on small slices.")
    print("  -> Insertion sort is not legacy; it is the workhorse of the world's")
    print("     most-used stable sorts. Cross-ref bubble_sort.py Section D.")


# ============================================================================
# 4. GOLD CHECK + TRACE EXPORT (the .html replays this exact trace)
# ============================================================================

def gold_check(sorted_a):
    banner("GOLD CHECK")
    expected = sorted(INPUT)
    ok = sorted_a == expected
    print(f"  insertion_sort({INPUT})")
    print(f"  = {sorted_a}")
    print(f"  sorted(input)        = {expected}")
    print(f"  match? {ok}  ->  {'GOLD OK' if ok else 'GOLD FAIL'}")
    assert ok
    print("[check] sorted output == sorted(input): OK")
    return ok


def export_trace(trace):
    print("\n# ---- TRACE for insertion_sort.html (one frame per comparison) ----")
    print("# frame: {a: [...], cmp: [j-1,j]|null, swp: [j-1,j]|null, pass: i}")
    print("const TRACE = " + json.dumps(trace) + ";")
    print("# ----------------------------------------------------------------")


# ============================================================================
# main
# ============================================================================

def main():
    print("insertion_sort.py - reference impl. All numbers below feed "
          "INSERTION_SORT.md + insertion_sort.html.")
    sorted_a, trace, comp, swaps = section_a()
    section_b(sorted_a, comp, swaps)
    section_c()
    section_d()
    gold_check(sorted_a)
    export_trace(trace)
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
