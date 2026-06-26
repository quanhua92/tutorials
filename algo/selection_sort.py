"""
selection_sort.py - Reference implementation of Selection Sort, the
"minimum-swap" sort.

This is the single source of truth that SELECTION_SORT.md is built from. Every
number, table, and worked example in SELECTION_SORT.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python selection_sort.py

=========================================================================
THE INTUITION (read this first) — the bookshelf with the shortest books
=========================================================================
Imagine a bookshelf of `n` books you must order from shortest to tallest. You
have ONE empty slot of "scratch space" in your hand.

  Selection sort works in `n-1` rounds. In each round you:
    1. SCAN the books from position i to the end, remembering the SHORTEST one
       you saw (and WHERE it is).
    2. SWAP that shortest book into position i (one swap, done).

That is the whole algorithm. The clever part is step 1 is a pure READ (no
shifting), and step 2 is exactly ONE swap per round. So selection sort makes
the FEWEST swaps of any comparison sort: at most `n-1` swaps total. That is
its reason to exist.

The price: you ALWAYS scan the entire unsorted tail, even if the shelf is
already sorted. There is no "early exit". So selection sort is Theta(n^2) in
comparisons in the BEST, AVERAGE, and WORST case -- it cannot tell that it is
done early. Contrast with insertion_sort, which is O(n) on already-sorted input.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  sorted prefix     : positions [0 .. i-1], already in final order. Grows by
                      one each round. Never touched again.
  unsorted tail     : positions [i .. n-1], not yet processed. We scan this
                      every round looking for the minimum.
  min scan          : the inner loop. Walks the unsorted tail once, tracking
                      the index of the smallest element seen so far.
                      Always does (n-1-i) comparisons at round i.
  swap              : exchange arr[i] <-> arr[min_idx]. ONE swap per round.
                      (If min_idx == i this is a "self-swap" / no-op; we usually
                      skip it, which is why actual swaps <= n-1.)
  pass / round      : one execution of the outer loop body (scan + swap).
                      There are exactly n-1 passes.

=========================================================================
THE LINEAGE (textbooks)
=========================================================================
  Selection sort : one of the oldest known sorts (Knuth traces it to ~1930s
                   punch-card machine practice, TAOCP Vol 3 §5.2.3).
                   Famous for MINIMUM swaps (<= n-1) and NO best case.
  Insertion sort : O(n^2) worst/avg, O(n) BEST case (already sorted). Its
                   foil: both are O(n^2) sorts, but insertion is adaptive and
                   stable while selection is neither (by default).
  Bubble sort    : O(n^2), also O(n) best case. More swaps than selection.
  Heap sort      : selection sort's descendant. "Selection sort, but the scan
                   is replaced by a heap" -> O(n log n). Same selection idea
                   (pick the min/max, move it to the front), faster scan.

KEY FACTS (all verified/printed by the sections below):
    comparisons(round i) = n - 1 - i            (always; no early exit)
    total comparisons    = n*(n-1)/2            = Theta(n^2) in EVERY case
    swaps                <= n - 1               (minimum of any comparison sort)
    best/avg/worst       = Theta(n^2)           (there is NO best-case speedup)
    stable?              = NO                   (the swap can leapfrog an equal)
    auxiliary space      = O(1)                 (in-place; one temp variable)
    adaptive?            = NO                   (ignores existing order)

Conventions:
    n   = len(arr)
    i   = outer loop index = start of the unsorted tail (0 .. n-2)
    j   = inner loop index walking the unsorted tail
    min_idx = index of the smallest element in arr[i..n-1] found this round
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code SELECTION_SORT.md walks
#    through). Instrumented so the sections can replay every comparison/swap.
# ============================================================================

def selection_sort(arr: list[int]) -> list[int]:
    """In-place selection sort. Returns the same list (now sorted).

    Outer loop: n-1 passes. Inner loop: scan arr[i+1..n-1] tracking the
    minimum. Then ONE swap puts the minimum at position i.
    """
    a = list(arr)                       # never mutate the caller's list
    n = len(a)
    for i in range(n - 1):              # n-1 passes
        min_idx = i                     # assume the min is at the boundary
        for j in range(i + 1, n):       # scan the unsorted tail
            if a[j] < a[min_idx]:
                min_idx = j
        if min_idx != i:                # skip the self-swap (min already home)
            a[i], a[min_idx] = a[min_idx], a[i]
    return a


def selection_sort_traced(arr: list[int]) -> dict:
    """Same algorithm, but records every pass so the guide can print a trace.

    Records, per pass i:
      - the array state BEFORE the swap
      - the scan window [i..n-1]
      - the min value and its index
      - whether a real swap happened (min_idx != i)
      - the array state AFTER the swap
      - comparisons made this pass (= len of the window minus 1)
    Plus aggregates: total comparisons, total real swaps, total self-swaps.
    """
    a = list(arr)
    n = len(a)
    passes: list[dict] = []
    total_cmp = 0
    total_real_swaps = 0
    total_self_swaps = 0
    for i in range(n - 1):
        min_idx = i
        cmp = 0
        for j in range(i + 1, n):
            cmp += 1
            if a[j] < a[min_idx]:
                min_idx = j
        before = list(a)
        swapped = min_idx != i
        if swapped:
            a[i], a[min_idx] = a[min_idx], a[i]
            total_real_swaps += 1
        else:
            total_self_swaps += 1
        total_cmp += cmp
        passes.append({
            "pass": i,
            "window_lo": i,
            "window_hi": n - 1,
            "comparisons": cmp,
            "before": before,
            "min_idx": min_idx,
            "min_val": before[min_idx],
            "swapped": swapped,
            "after": list(a),
        })
    return {
        "input": list(arr),
        "sorted": a,
        "n": n,
        "passes": passes,
        "total_comparisons": total_cmp,
        "total_real_swaps": total_real_swaps,
        "total_self_swaps": total_self_swaps,
        "max_possible_swaps": n - 1,
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
#    Same array used to contrast with insertion/bubble. n=5 -> 10 comparisons.
# ============================================================================

EXAMPLE = [64, 25, 12, 22, 11]


# ----------------------------------------------------------------------------
# SECTION A: the algorithm, pass by pass
# ----------------------------------------------------------------------------

def section_algorithm():
    banner("SECTION A: the algorithm, pass by pass  (array = [64,25,12,22,11])")
    r = selection_sort_traced(EXAMPLE)
    n = r["n"]
    print(f"Input  : {r['input']}")
    print(f"Sorted : {r['sorted']}")
    print(f"n = {n}  ->  there are n-1 = {n-1} passes. "
          f"The sorted prefix grows by one each pass.\n")
    print("Each pass: SCAN arr[i..n-1] for the min (comparisons, no writes), "
          "then ONE swap puts the min at position i.\n")
    for p in r["passes"]:
        i = p["pass"]
        win = f"[{p['window_lo']}..{p['window_hi']}]"
        action = "SWAP" if p["swapped"] else "self-swap (min already at i)"
        print(f"-- pass i={i}: scan window {win} "
              f"({p['comparisons']} comparisons) --")
        print(f"   before : {p['before']}   (looking in {win})")
        print(f"   min found: value {p['min_val']} at index {p['min_idx']}  "
              f"-> {action}")
        print(f"   after  : {p['after']}")
        print()
    print("After the last pass, position n-1 is automatically correct "
          "(the lone largest element), so we stop at i = n-2.")


# ----------------------------------------------------------------------------
# SECTION B: comparison and swap counts (the invariant)
# ----------------------------------------------------------------------------

def section_counts():
    banner("SECTION B: comparison & swap counts  "
           "(ALWAYS n(n-1)/2 comparisons, <= n-1 swaps)")
    r = selection_sort_traced(EXAMPLE)
    n = r["n"]
    expected_cmp = n * (n - 1) // 2
    print("Comparisons per pass i = (n-1-i):")
    print(f"  {'pass i':<8} {'window size':<12} {'comparisons':<12}")
    for p in r["passes"]:
        wsize = p["window_hi"] - p["window_lo"] + 1
        print(f"  {p['pass']:<8} {wsize:<12} {p['comparisons']:<12}")
    print(f"  {'total':<8} {'':<12} {r['total_comparisons']:<12}")
    print(f"\nn(n-1)/2 = {n}*{n-1}/2 = {expected_cmp}  "
          f"== measured {r['total_comparisons']}")
    assert r["total_comparisons"] == expected_cmp
    print("[check] comparisons == n(n-1)/2:  OK\n")

    print("Swaps:")
    print(f"  real swaps   (element actually moved): {r['total_real_swaps']}")
    print(f"  self-swaps   (min was already at i)  : {r['total_self_swaps']}")
    print(f"  max possible (n-1)                   : {r['max_possible_swaps']}")
    assert r["total_real_swaps"] + r["total_self_swaps"] == n - 1
    assert r["total_real_swaps"] <= n - 1
    print(f"[check] real_swaps <= n-1:  OK  "
          f"({r['total_real_swaps']} <= {n-1})")
    print("\nTHIS is selection sort's selling point: at most n-1 swaps, "
          "the minimum of any comparison sort. Bubble sort can make O(n^2) "
          "swaps; insertion sort O(n^2) too. Selection makes O(n).")


# ----------------------------------------------------------------------------
# SECTION C: complexity analysis (NO best case)
# ----------------------------------------------------------------------------

def section_complexity():
    banner("SECTION C: complexity analysis  (BEST = AVERAGE = WORST = Theta(n^2))")
    print("The inner scan ALWAYS walks the whole unsorted tail and compares "
          "every element against the running min. The array's current order "
          "is IRRELEVANT to how many comparisons get made -- even a fully "
          "sorted input is scanned end to end every pass.\n")
    cases = [
        ("best    (already sorted)", EXAMPLE[::-1][::-1] if False else sorted(EXAMPLE)),
        ("average (random)         ", [25, 64, 12, 22, 11]),
        ("worst   (reverse sorted) ", sorted(EXAMPLE, reverse=True)),
    ]
    print(f"  {'case':<26} {'comparisons':<12} {'real swaps':<11} "
          f"{'result sorted?'}")
    for label, arr in cases:
        r = selection_sort_traced(arr)
        is_sorted = r["sorted"] == sorted(arr)
        print(f"  {label:<26} {r['total_comparisons']:<12} "
              f"{r['total_real_swaps']:<11} {is_sorted}")
    n = len(EXAMPLE)
    print(f"\nAll three cases use exactly n(n-1)/2 = {n*(n-1)//2} comparisons. "
          "There is no fast path.\n")
    print("Summary table:")
    print("  | case    | comparisons  | swaps     | time       |")
    print("  |---------|--------------|-----------|------------|")
    print("  | best    | n(n-1)/2     | 0..n-1    | Theta(n^2) |")
    print("  | average | n(n-1)/2     | ~ n/2     | Theta(n^2) |")
    print("  | worst   | n(n-1)/2     | n-1       | Theta(n^2) |")
    print("  auxiliary space: O(1)  (in-place, one temp var)")
    print("\nContrast: insertion_sort is O(n) on sorted input (best case); "
          "selection sort has no such mercy.")


# ----------------------------------------------------------------------------
# SECTION D: stability (selection sort is NOT stable by default)
# ----------------------------------------------------------------------------

def section_stability():
    banner("SECTION D: stability  (NOT stable by default -- the swap leapfrogs)")
    print("A sort is STABLE if equal keys keep their original relative order.\n")
    print("Selection sort's swap can BREAK this. Demonstration: tag equal keys\n"
          "with their original index so we can see order get scrambled.\n")
    # The classic counter-example: an EQUAL key sits in the sorted prefix and
    # the swap flings the boundary element PAST it.
    tagged = [("2a", 2), ("2b", 2), ("1", 1)]
    print(f"Input (tag, value): {tagged}")
    a = list(tagged)
    n = len(a)
    for i in range(n - 1):
        min_idx = i
        for j in range(i + 1, n):
            if a[j][1] < a[min_idx][1]:   # strict <: first min index is kept
                min_idx = j
        if min_idx != i:
            a[i], a[min_idx] = a[min_idx], a[i]
        print(f"  pass {i}: {[(t,v) for t,v in a]}  "
              f"(min at index {min_idx}, swapped={min_idx != i})")
    print(f"\nResult: {a}")
    twos = [t for (t, v) in a if v == 2]
    stable_order = ["2a", "2b"]
    is_stable = twos == stable_order
    print(f"The two 2's ended up as {twos}; a stable sort would keep "
          f"{stable_order}.")
    print(f"[check] stable?  {is_stable}  ->  selection sort is NOT stable")
    print("\nWHY it breaks: at pass 0 the min is '1' at index 2. The SWAP is\n"
          "  arr[0] <-> arr[2], i.e. '2a' and '1' exchange places. That flings\n"
          "  '2a' from position 0 to position 2 -- JUMPING PAST '2b' which had\n"
          "  been behind it. Now '2b' precedes '2a': relative order reversed.")
    print("\nFIX (costs the minimum-swap property): instead of SWAPPING, INSERT\n"
          "  the min by shifting the prefix right (O(n) writes per pass). That\n"
          "  restores stability but turns the O(n) swap count into O(n^2) writes\n"
          "  -- exactly what we chose selection sort to avoid. Trade-off.")
    print("\nTAKEAWAY: plain selection sort is NOT stable. Need stability? Use\n"
          "  merge_sort (stable, Theta(n log n)) or insertion_sort (stable).")


# ----------------------------------------------------------------------------
# SECTION E: when to use selection sort (and when NOT to)
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION E: when to use selection sort  (and when NOT to)")
    print("USE selection sort when:")
    print("  * Writes are EXPENSIVE (flash/EEPROM): it makes <= n-1 swaps, the\n"
          "    minimum of any comparison sort. On write-limited hardware this\n"
          "    matters more than comparison count.")
    print("  * n is SMALL (n <= ~20): the constant factor is tiny, no recursion,\n"
          "    no auxiliary buffer. Often the inner loop is the fastest simple\n"
          "    sort to benchmark because the scan is just a 'compare + branch'.")
    print("  * You need a SIMPLE, in-place, O(1)-space sort with predictable\n"
          "    timing (always Theta(n^2), no surprises).")
    print("  * As a building block: heapsort is 'selection sort with a heap for\n"
          "    the scan', turning Theta(n^2) into Theta(n log n).")
    print()
    print("DO NOT use selection sort when:")
    print("  * n is large: Theta(n^2) comparisons dominate. Use merge_sort\n"
          "    (Theta(n log n), stable) or quicksort (Theta(n log n) avg).")
    print("  * The input is NEARLY SORTED: insertion_sort is O(n) on it,\n"
          "    selection_sort is still Theta(n^2). No adaptivity.")
    print("  * You need STABILITY: use merge_sort or insertion_sort instead.")
    print()
    print("See MERGE_SORT.md for the Theta(n log n) divide-and-conquer foil.")


# ============================================================================
# main + GOLD
# ============================================================================

def main():
    print("selection_sort.py - reference impl. All numbers below feed "
          "SELECTION_SORT.md.")
    section_algorithm()
    section_counts()
    section_complexity()
    section_stability()
    section_when_to_use()

    banner("GOLD (pinned for selection_sort.html) -- array = [64,25,12,22,11]")
    r = selection_sort_traced(EXAMPLE)
    print(f"sorted array        : {r['sorted']}")
    print(f"total comparisons   : {r['total_comparisons']}   (= n(n-1)/2 = 10)")
    print(f"total real swaps    : {r['total_real_swaps']}   (<= n-1 = 4)")
    print(f"total self-swaps    : {r['total_self_swaps']}")
    # GOLD scalars for the .html to recompute and check.
    GOLD_SORTED = [11, 12, 22, 25, 64]
    GOLD_COMPARISONS = 10
    GOLD_REAL_SWAPS = 3
    assert r["sorted"] == GOLD_SORTED
    assert r["total_comparisons"] == GOLD_COMPARISONS
    assert r["total_real_swaps"] == GOLD_REAL_SWAPS
    print()
    print(f"GOLD sorted     = {GOLD_SORTED}")
    print(f"GOLD comparisons= {GOLD_COMPARISONS}")
    print(f"GOLD real swaps = {GOLD_REAL_SWAPS}")
    print("[check] GOLD reproduces from selection_sort_traced(EXAMPLE):  OK")

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
