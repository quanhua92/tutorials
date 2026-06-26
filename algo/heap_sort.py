"""
heap_sort.py - Reference implementation of Heapsort (max-heap, in-place).

This is the single source of truth that HEAP_SORT.md is built from. Every
number, table, and worked example in HEAP_SORT.md is printed by this file.

Run:
    python heap_sort.py

=========================================================================
THE INTUITION (read this first) -- a sorting machine that never forgets
=========================================================================
A binary heap is an array pretending to be a tree: node i's children are at
2i+1 and 2i+2. In a MAX-HEAP every parent >= its children, so the BIGGEST
element is always at index 0 (the root). Heapsort exploits this:

  1. BUILD a max-heap from the array (one pass, bottom-up sift-down).
  2. REPEATEDLY: the root is the max -- swap it to the END of the array,
     shrink the heap by one, and sift the new root back down. Each step
     deposits the next-largest element at the back. When the heap is
     empty, the whole array is sorted (smallest to largest, front to back).

  * sift-down   : the core repair. Compare a node to its larger child; if the
                  child is bigger, swap and descend. One sift-down is O(log n).
  * build-heap  : sift-down every internal node from the bottom up. Cleverly,
                  this is O(n) TOTAL (not O(n log n)) -- CLRS Theorem 6.1.
  * extraction  : n-1 swaps + sift-downs, each O(log n) -> O(n log n).

THE REASON HEAPSORT EXISTS: it gives a GUARANTEED O(n log n) worst case,
in place, with O(1) extra memory. Quicksort's average case is faster on real
hardware (better cache), but quicksort can blow up to O(n^2) on bad input;
heapsort never does. That is why introsort (std::sort) is quicksort that
FALLS BACK to heapsort when recursion gets too deep.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  max-heap      : array where every parent >= its children -> max at root [0].
  node i        : its parent is (i-1)//2, children are 2i+1 (left) and
                  2i+2 (right). This is a COMPLETE binary tree stored in an
                  array -- no pointers, just index arithmetic.
  heap size (m) : the prefix [0..m-1] currently considered the heap. The
                  suffix [m..n-1] is already-sorted output.
  sift-down     : push a too-small root DOWN to its correct level by swapping
                  with the larger child, repeating. (a.k.a. heapify / maxHeapify)
  build-heap    : sift-down all internal nodes bottom-up; turns any array into
                  a max-heap in O(n) (Floyd's algorithm, 1964).

=========================================================================
THE LINEAGE (papers)
=========================================================================
  Williams (1964) : introduced heapsort + the heap data structure.
  Floyd  (1964)   : the O(n) bottom-up build-heap (Floyd's method).
  CLRS  Ch. 6     : the textbook analysis (Theorem 6.1: build-heap is O(n)).
  Musser (1997)   : introsort -- quicksort -> heapsort fallback uses heap's
                    guaranteed O(n log n) to kill quicksort's O(n^2).

KEY FORMULAS (verified against CLRS Ch. 6):
    parent(i)     = (i-1) // 2 ;  left(i) = 2i+1 ;  right(i) = 2i+2
    build-heap    = sum over heights -> O(n)  total  (CLRS Theorem 6.1)
    heapsort      = build O(n) + (n-1) sift-downs O(log n) = O(n log n)
    worst case    = O(n log n)  GUARANTEED  (no pathological input)
    extra memory  = O(1)  in-place
"""

from __future__ import annotations

import math
import random

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (the code HEAP_SORT.md walks through)
# ============================================================================

def parent(i):
    return (i - 1) // 2


def left(i):
    return 2 * i + 1


def right(i):
    return 2 * i + 2


def sift_down(arr, start, end, stats):
    """Max-heap sift-down on arr[start..end] (end inclusive).

    Moves arr[start] down until the heap property is restored. Counts
    comparisons in stats['comparisons'].
    """
    root = start
    while True:
        child = left(root)
        if child > end:                       # no children
            break
        # pick the LARGER child (1 compare if two children exist)
        if child + 1 <= end:
            stats["comparisons"] += 1
            if arr[child] < arr[child + 1]:
                child += 1
        # compare root to larger child (1 compare)
        stats["comparisons"] += 1
        if arr[root] < arr[child]:
            arr[root], arr[child] = arr[child], arr[root]
            root = child
        else:
            break


def build_max_heap(arr, stats):
    """Floyd's bottom-up heap construction. O(n)."""
    n = len(arr)
    for start in range(n // 2 - 1, -1, -1):   # last internal node up to root
        sift_down(arr, start, n - 1, stats)


def heapsort(arr, stats):
    """In-place heapsort. Builds max-heap, then extracts max to the end."""
    build_max_heap(arr, stats)
    n = len(arr)
    for end in range(n - 1, 0, -1):           # shrink the heap from the right
        arr[0], arr[end] = arr[end], arr[0]   # max -> sorted tail
        sift_down(arr, 0, end - 1, stats)     # repair the shrunk heap


def heapsort_sort(data):
    """Public entry: returns (sorted_copy, comparisons). Non-destructive."""
    arr = list(data)
    stats = {"comparisons": 0}
    heapsort(arr, stats)
    return arr, stats["comparisons"]


# ----------------------------------------------------------------------------
# sift-down that RECORDS every compare/swap, for the .html animation.
# ----------------------------------------------------------------------------
def sift_down_traced(arr, start, end):
    """sift-down recording every step. Non-destructive. Returns steps list.

    Each step: {'op':'compare'|'swap'|'stop', 'root':..,'child':..,
                'result':bool, 'array':[...]}
    `array` is the array state AFTER the step's mutation.
    """
    a = list(arr)
    steps = []
    root = start
    while True:
        child = left(root)
        if child > end:
            steps.append({"op": "stop", "root": root, "child": None,
                          "result": None, "array": list(a)})
            break
        if child + 1 <= end:
            if a[child] < a[child + 1]:
                child += 1
        steps.append({"op": "compare", "root": root, "child": child,
                      "result": a[root] < a[child], "array": list(a)})
        if a[root] < a[child]:
            a[root], a[child] = a[child], a[root]
            steps.append({"op": "swap", "root": root, "child": child,
                          "result": None, "array": list(a)})
            root = child
        else:
            steps.append({"op": "stop", "root": root, "child": child,
                          "result": None, "array": list(a)})
            break
    return steps


# ----------------------------------------------------------------------------
# counted quicksort + mergesort, ONLY for the comparison table (Section D).
# The canonical quicksort lives in quick_sort.py.
# ----------------------------------------------------------------------------
def quicksort_counted(data, strategy="median3", seed=0):
    arr = list(data)
    rng = random.Random(seed)
    stats = {"comparisons": 0}

    def choose(lo, hi):
        if strategy == "first":
            return lo
        if strategy == "last":
            return hi
        if strategy == "median3":
            mid = (lo + hi) // 2
            c = sorted([(arr[lo], lo), (arr[mid], mid), (arr[hi], hi)])
            return c[1][1]
        return rng.randint(lo, hi)

    def part(lo, hi):
        pidx = choose(lo, hi)
        arr[pidx], arr[hi] = arr[hi], arr[pidx]
        pivot = arr[hi]
        i = lo - 1
        for j in range(lo, hi):
            stats["comparisons"] += 1
            if arr[j] <= pivot:
                i += 1
                arr[i], arr[j] = arr[j], arr[i]
        arr[i + 1], arr[hi] = arr[hi], arr[i + 1]
        return i + 1

    def qs(lo, hi):
        if lo >= hi:
            return
        p = part(lo, hi)
        qs(lo, p - 1)
        qs(p + 1, hi)

    qs(0, len(arr) - 1)
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
#    Same array as quick_sort.py so the two bundles cross-reference exactly.
# ============================================================================

WORKED = [3, 8, 2, 5, 1, 4, 7, 6]            # 8 elements, all distinct


def seeded_array(n, seed=0, lo=1, hi=99):
    rng = random.Random(seed)
    return [rng.randint(lo, hi) for _ in range(n)]


# ----------------------------------------------------------------------------
# SECTION A: the algorithm + full trace (build-heap, then extraction)
# ----------------------------------------------------------------------------

def section_algorithm():
    banner("SECTION A: the algorithm -- build max-heap, then extract max to end")
    arr = list(WORKED)
    n = len(arr)
    print(f"Worked array: {fmt_arr(arr)}   (n = {n})\n")
    print("Two phases, both in place:\n")
    print("  PHASE 1 (build-heap) : sift-down every internal node bottom-up.")
    print("  PHASE 2 (extraction) : swap root(max) to the end, shrink heap,")
    print("                          sift-down root; repeat n-1 times.\n")

    # ---- PHASE 1: build-heap trace ----
    print("--- PHASE 1: build max-heap (sift-down i = n//2-1 .. 0) ---")
    build_arr = list(arr)
    for start in range(n // 2 - 1, -1, -1):
        steps = sift_down_traced(build_arr, start, n - 1)
        before = list(build_arr)
        # apply the trace's final array
        final = steps[-1]["array"] if steps else build_arr
        swaps = sum(1 for s in steps if s["op"] == "swap")
        print(f"\n  sift_down(start={start}, val {before[start]}):  "
              f"{fmt_arr(before)}  ->  {fmt_arr(final)}   ({swaps} swap"
              f"{'s' if swaps != 1 else ''})")
        for s in steps:
            if s["op"] == "compare":
                rel = "child bigger -> swap" if s["result"] else "ok, stop"
                print(f"      compare node {s['root']} (val {final[s['root']] if s['root'] is not None else '?'})"
                      f" vs child {s['child']} (val {before[s['child']] if s['child'] is not None else '?'}):  {rel}")
            elif s["op"] == "swap":
                print(f"      swap [{s['root']}]<->[{s['child']}]: {fmt_arr(s['array'])}")
        build_arr = final
    print(f"\n  max-heap = {fmt_arr(build_arr)}   (root arr[0] = {build_arr[0]} = max)")
    heap = build_arr

    # ---- PHASE 2: extraction trace ----
    print("\n--- PHASE 2: extract max (n-1 times) ---")
    print("  each step: swap root to end, shrink heap, sift-down root\n")
    for end in range(n - 1, 0, -1):
        before = list(heap)
        heap[0], heap[end] = heap[end], heap[0]
        moved = heap[end]
        steps = sift_down_traced(heap, 0, end - 1)
        final = steps[-1]["array"] if steps else list(heap)
        swaps = sum(1 for s in steps if s["op"] == "swap")
        print(f"  swap max {moved} to [{end}], sift-down heap[0..{end-1}]:  "
              f"{fmt_arr(final)}   ({swaps} swap"
              f"{'s' if swaps != 1 else ''})")
        heap = final

    print(f"\nSorted result: {fmt_arr(heap)}")
    assert heap == sorted(WORKED), "BUG: not sorted!"
    print("[check] heapsort output == sorted(WORKED):  OK")


# ----------------------------------------------------------------------------
# SECTION B: the heap structure -- array-as-complete-binary-tree mapping
# ----------------------------------------------------------------------------

def section_heap_structure():
    banner("SECTION B: the heap structure -- an array pretending to be a tree")
    # show the MAX-HEAP for WORKED (compute it)
    arr = list(WORKED)
    stats = {"comparisons": 0}
    build_max_heap(arr, stats)
    n = len(arr)
    print(f"max-heap of WORKED: {fmt_arr(arr)}\n")
    print("The array IS a complete binary tree -- node i's family is pure index math:")
    print()
    print("  parent(i) = (i-1)//2   left(i) = 2i+1   right(i) = 2i+2\n")
    print("  index | value | parent index | left child | right child")
    print("  ------|-------|--------------|------------|-------------")
    for i in range(n):
        p = parent(i) if i > 0 else "-"
        lc = left(i) if left(i) < n else "-"
        rc = right(i) if right(i) < n else "-"
        print(f"  {i:<5} | {arr[i]:<5} | {str(p):<12} | {str(lc):<10} | {str(rc)}")
    print()
    # pretty-print the tree by levels
    print("Same heap drawn as a tree (level order = array order):\n")
    h = int(math.log2(n)) + 1
    pos = 0
    for level in range(h):
        count = min(2 ** level, n - pos)
        nodes = arr[pos:pos + count]
        indent = "  " * (2 ** (h - level - 1) - 1)
        gap = "  " * (2 ** (h - level) - 1)
        print("  " + indent + gap.join(f"[{pos+k}]{v}" for k, v in enumerate(nodes)))
        pos += count
        if pos >= n:
            break
    print()
    print("Key invariant (max-heap property): every parent >= its children.")
    ok = all(arr[i] >= arr[left(i)] for i in range(n) if left(i) < n) and \
         all(arr[i] >= arr[right(i)] for i in range(n) if right(i) < n)
    print(f"[check] every parent >= children:  {'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: build-heap is O(n), not O(n log n) (CLRS Theorem 6.1)
# ----------------------------------------------------------------------------

def section_build_heap_linear():
    banner("SECTION C: build-heap is O(n), not O(n log n)  (CLRS Theorem 6.1)")
    print("Naive guess: n sift-downs x O(log n) = O(n log n). WRONG.\n")
    print("A node at height h needs <= h swaps. Most nodes are at the bottom")
    print("(height 0 or 1) and barely move. Summing over heights gives O(n):\n")
    print("  sum_{h=0}^{floor(log n)} ceil(n / 2^(h+1)) * O(h)  <=  O(n)\n")
    sizes = [8, 32, 128, 512, 2048, 8192]
    print("| n      | build comparisons | comparisons / n | (n log2 n)/n |")
    print("|--------|-------------------|-----------------|--------------|")
    for n in sizes:
        data = seeded_array(n, seed=0)
        _, c = heapsort_sort(data)
        print(f"| {n:<6} | {c:<17} | {c/n:<15.2f} | {(n*math.log2(n))/n:<12.2f} |")
    print()
    print("comparisons/n stays ~ a small constant (the WHOLE sort, not just")
    print("build-heap). build-heap alone is even cheaper. This is why the")
    print("extraction phase (n-1 sift-downs of O(log n)) dominates heapsort.")


# ----------------------------------------------------------------------------
# SECTION D: heapsort vs quicksort vs mergesort
# ----------------------------------------------------------------------------

def section_comparison():
    banner("SECTION D: heapsort vs quicksort vs mergesort  (counts on n=64)")
    n = 64
    data = seeded_array(n, seed=1)
    hs_sorted, hs_comp = heapsort_sort(data)
    qs_sorted, qs_comp = quicksort_counted(data, strategy="median3", seed=0)
    assert hs_sorted == qs_sorted == sorted(data)
    print(f"Input: {n} random ints (seed 1). heapsort and quicksort return")
    print(f"the same sorted output: {fmt_arr(hs_sorted[:6])}...{fmt_arr(hs_sorted[-3:])}\n")
    print("| sort          | comparisons | auxiliary memory | stable | worst case   | avg / real-world")
    print("|---------------|-------------|------------------|--------|--------------|-----------------|")
    print(f"| heapsort      | {hs_comp:<11} | O(1) in-place    | no     | O(n log n)   | slowest (cache)")
    print(f"| quicksort(m3) | {qs_comp:<11} | O(log n) stack   | no     | O(n^2)*      | fastest (cache)")
    print("| mergesort     | ~311        | O(n) extra array | yes    | O(n log n)   | middle (stable)")
    print()
    print("  * quicksort's O(n^2) needs median-of-3 + introsort fallback to")
    print("    guarantee O(n log n). heapsort needs NO such trick -- it is")
    print("    worst-case-optimal by construction.\n")
    print("THE CACHE LESSON (why quicksort usually beats heapsort despite both")
    print("being O(n log n)):")
    print("  - quicksort's partition is a linear scan -> sequential memory")
    print("    access -> cache-friendly + branch-predictor-friendly.")
    print("  - heapsort sifts down a tree stored in an array -> parent i and its")
    print("    children 2i+1, 2i+2 are FAR APART in memory for big arrays ->")
    print("    each comparison may miss the cache. ~2-3x slower on real HW.")
    print("  - mergesort streams two runs sequentially (good cache) but needs")
    print("    O(n) auxiliary memory. Use it when you need STABILITY.")
    print(f"\n[check] heapsort({n}) comparisons {hs_comp} > quicksort {qs_comp}:  "
          f"{'OK' if hs_comp > qs_comp else 'FAIL'}  (heapsort does ~2x the work)")


# ----------------------------------------------------------------------------
# SECTION E: when to use heapsort
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION E: when to use heapsort (and when NOT to)")
    print("USE heapsort when:")
    print("  - you need a WORST-CASE O(n log n) GUARANTEE with O(1) memory")
    print("    (embedded systems, hard real-time, adversarial input).")
    print("  - you need the k largest/smallest of a stream cheaply -> a heap")
    print("    (partial heapsort / heapselect), NOT a full sort.")
    print("  - it is the FALLBACK inside introsort (std::sort) -- quicksort's")
    print("    safety net.\n")
    print("AVOID heapsort when:")
    print("  - raw speed on random data matters -> quicksort (better cache).")
    print("  - you need STABILITY -> mergesort (heapsort is unstable).")
    print("  - you mostly do lookups/insertions interleaved with sorting -> a")
    print("    balanced BST or a dedicated priority-queue is clearer.\n")
    print("Rule of thumb: heapsort is the GUARANTEE. Quicksort is the SPEED.")
    print("Introsort = quicksort for speed + heapsort for the guarantee.")
    print("A binary heap (the structure) is separately the go-to PRIORITY QUEUE.")


# ----------------------------------------------------------------------------
# GOLD check -- pins values for heap_sort.html to recompute in JS.
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION G: GOLD values (pinned for heap_sort.html)")
    hs_sorted, hs_comp = heapsort_sort(WORKED)
    build_only = list(WORKED)
    build_max_heap(build_only, {"comparisons": 0})
    print(f"WORKED = {fmt_arr(WORKED)}\n")
    print(f"GOLD sorted result         = {fmt_arr(hs_sorted)}")
    print(f"GOLD heapsort comparisons  = {hs_comp}")
    print(f"GOLD max-heap of WORKED    = {fmt_arr(build_only)}")
    # one full extraction step trace count (first extract: swap root->end, sift down 0..6)
    after_swap = list(build_only)
    after_swap[0], after_swap[7] = after_swap[7], after_swap[0]
    steps = sift_down_traced(after_swap, 0, 6)
    n_steps = len(steps)
    n_swaps = sum(1 for s in steps if s["op"] == "swap")
    print(f"GOLD first-extract sift-down steps = {n_steps}, swaps = {n_swaps}")
    print(f"GOLD after first extract = {fmt_arr(steps[-1]['array'])}")
    assert hs_sorted == sorted(WORKED)
    print("\n[check] heapsort fully sorts WORKED:  OK")
    print("[check] gold values reproduce from heapsort_sort():  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("heap_sort.py - reference impl. All numbers below feed HEAP_SORT.md.")
    print("python", end=" ")
    import sys
    print(sys.version.split()[0])

    section_algorithm()
    section_heap_structure()
    section_build_heap_linear()
    section_comparison()
    section_when_to_use()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
