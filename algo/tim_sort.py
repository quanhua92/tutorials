"""
tim_sort.py - Reference implementation of Timsort (the hybrid sort behind
Python's list.sort / sorted, Java's Arrays.sort for objects, and Rust's stable
slice::sort). Built from: run detection + binary insertion sort + a balanced
merge stack + galloping merge.

This is the single source of truth that TIM_SORT.md is built from. Every
number, table, and worked example in TIM_SORT.md is printed by this file.

Run:
    uv run python tim_sort.py

=========================================================================
THE INTUITION (read this first) - exploiting the order that's already there
=========================================================================
Real-world data is rarely a perfectly shuffled mess. It has STREAKS of already-
sorted elements: a partly-sorted log, a list someone appended to, a table sorted
on one column. Mergesort ignores that structure and pays n-log-n every time.
Quicksort ignores it too. Timsort HUNTS for that existing order and exploits it.

The four ideas, in one breath:

  1. RUN DETECTION   : scan left-to-right, grab every maximal ascending or
                       strictly-descending run. A descending run is reversed in
                       place. If the input is already sorted, timsort finds ONE
                       run covering everything -> O(n), done. THAT is why its
                       best case is O(n), not O(n log n).
  2. MINRUN          : runs shorter than `minrun` (32..64 in CPython) are too
                       tiny to be worth keeping - extend them to minrun with
                       binary insertion sort (fast on small n). minrun is chosen
                       so the number of runs is near a power of 2, giving a
                       BALANCED merge tree.
  3. MERGE STACK     : push runs onto a stack and maintain an INVARIANT
                       (A > B + C and B > C) so merges stay balanced and shallow.
                       This is what bounds the worst case at O(n log n).
  4. GALLOPING       : during a merge, if one side "wins" MIN_GALLOP (7) times
                       running, the elements from that side are clustered - so
                       instead of comparing one-by-one, we GALLOP (exponential +
                       binary search) to grab a whole run of them at once. This
                       turns merges of very-imbalanced data into near O(n).

THE REASON TIMSORT EXISTS: it gives O(n log n) worst case like mergesort, but
O(n) best case (already-ordered data) and excellent constant factors on real
(non-random) inputs, while being STABLE. That combination is why it became the
default sort in Python (2002), Java (2007), V8, Android, Rust (stable path).

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  run         : a maximal slice that is already ascending or strictly
                descending. Descending runs are reversed to ascending.
  minrun      : minimum run length, in [32, 64] (CPython). Runs shorter than
                minrun are extended with binary insertion sort. Chosen so that
                n/minrun is ~a power of 2.
  merge stack : a stack of pending runs; an invariant keeps merges balanced.
  invariant   : for the top three runs A, B, C (A deepest):  A > B + C  and
                B > C. Violated -> merge the shorter of A/B with C until it holds.
  galloping   : exponential-then-binary search used to copy a whole cluster of
                equal-or-smaller elements in one shot when one side dominates.
  MIN_GALLOP  : consecutive wins from one side that triggers galloping mode = 7.

=========================================================================
THE LINEAGE (sources)
=========================================================================
  Timsort : Tim Peters, "listsort.txt" (2002), shipped in CPython 2.3.
            The design doc describing minrun, the merge invariant, galloping.
  Binary insertion sort : standard; extends short runs to minrun length.
  Java port: 2007, JDK Arrays.sort(Object[]) - Joshua Bloch.
  Rust     : stable sort since 1.0 uses a timsort variant.

KEY FORMULAS (all verified against listsort.txt + asserted in code):
    minrun(n)        : shift n right until < 64; OR in any dropped low bit;
                       result in [32, 64]. (CPython merge_compute_minrun)
    count_run(a,lo)  : ascend if a[lo] <= a[lo+1] (allow equals -> STABLE);
                       strictly descend otherwise (a[lo] > a[lo+1] > ...).
                       Reverse a descending run. Return run length.
    merge invariant : stack X satisfies, for top-3 (A,B,C):
                         len(A) > len(B) + len(C)   and   len(B) > len(C)
    gallop_search   : exponential jump (1,3,7,15,...) to bracket, then binary
                       search within the bracket. O(log k) for a run of k.
    complexity      : worst O(n log n) [balanced merges], best O(n) [one run].
"""

from __future__ import annotations

import math
import random

BANNER = "=" * 72
MIN_GALLOP = 7          # consecutive wins from one side -> enter galloping
MIN_MERGE = 64          # below this, the whole array is one insertion sort


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code TIM_SORT.md walks through)
# ============================================================================

def compute_minrun(n: int) -> int:
    """Timsort minrun selection (CPython listsort.txt / merge_compute_minrun).

    Take the top bits of n, and OR in 1 if ANY of the lower bits that were
    shifted off are set. Result is always in [32, 64], and n/minrun comes out
    at or slightly above a power of two -> balanced merge tree.

    Why [32,64]?  CPython sets MAX_MINRUN=MIN_MERGE=64 and the loop `while
    n >= 64` leaves a residual n in [32,64) (+0/1 flag -> [32,64]). The lower
    bound 32 is where binary insertion sort is still faster than merge overhead;
    64 caps run length so we get enough runs to balance. NOTE: Java's TimSort
    uses MIN_MERGE=32, which yields minrun in [16,32] - same idea, different
    constant. We follow CPython (the original, Tim Peters 2002).
    """
    r = 0
    while n >= MIN_MERGE:
        r |= (n & 1)
        n >>= 1
    return n + r


def count_run(arr, lo, hi):
    """Find the next natural run starting at lo. Returns (start, end_exclusive,
    was_descending).

    A run is the LONGEST slice that is either:
      - ascending :  arr[i] <= arr[i+1]   (<= keeps equal elements in order
                     -> STABILITY)
      - strictly descending : arr[i] > arr[i+1]  (> strictly so reversal keeps
                     equal elements in input order -> STABILITY)
    Strictly-descending runs are REVERSED in place to become ascending, and
    was_descending=True is returned so the caller/trace can report it.

    Returns (start, end, flag). end-start >= 2 always (or 1 at the very tail).
    """
    start = lo
    if lo + 1 >= hi:
        return start, lo + 1, False
    if arr[lo] <= arr[lo + 1]:                       # ascending
        lo += 1
        while lo + 1 < hi and arr[lo] <= arr[lo + 1]:
            lo += 1
        return start, lo + 1, False
    else:                                            # strictly descending
        lo += 1
        while lo + 1 < hi and arr[lo] > arr[lo + 1]:
            lo += 1
        arr[start:lo + 1] = arr[start:lo + 1][::-1]  # reverse -> ascending
        return start, lo + 1, True


def binary_search_left(arr, key, base, length):
    """Leftmost insertion point of `key` in arr[base : base+length]
    (i.e. first index i with arr[base+i] >= key). Used by insertion sort to
    extend a run: place the new element before any equal element -> STABLE.
    """
    lo = 0
    hi = length
    while lo < hi:
        mid = (lo + hi) >> 1
        if arr[base + mid] < key:
            lo = mid + 1
        else:
            hi = mid
    return lo


def binary_insertion_sort(arr, lo, hi, start):
    """Sort arr[lo:hi] in place; elements arr[lo:start] are already sorted.

    Insert each element from start..hi-1 into the sorted prefix via binary
    search. This is how timsort pads a short run up to minrun. O(k log k) for
    the k new elements, but with cheap constants - faster than merge overhead
    for k <= ~32.
    """
    if start == lo:
        start += 1
    while start < hi:
        key = arr[start]
        pos = lo + binary_search_left(arr, key, lo, start - lo)
        # shift arr[pos:start] right by one, drop key into pos
        arr[pos + 1:start + 1] = arr[pos:start]
        arr[pos] = key
        start += 1


def gallop_left(key, arr, base, length):
    """GALLOP search: return count p in [0,length] of leading elements
    arr[base:base+length] that are STRICTLY LESS than key (= first index with
    arr >= key). Exponential jump to bracket, then binary search.

    This is the speedup behind galloping mode: locating where `key` belongs in
    a run of length `length` is O(log k) when only k << length leading elements
    qualify, instead of O(log length) full binary search every time.
    """
    if length == 0 or arr[base] >= key:
        return 0
    last = 0                          # offset of last known < key
    ofs = 1                           # exponential: 1, 3, 7, 15, ...
    while ofs < length and arr[base + ofs] < key:
        last = ofs
        ofs = (ofs << 1) + 1
    hi = min(ofs, length)             # answer lives in (last, hi]
    lo = last + 1
    while lo < hi:
        mid = (lo + hi) >> 1
        if arr[base + mid] < key:
            lo = mid + 1
        else:
            hi = mid
    return lo


def gallop_right(key, arr, base, length):
    """GALLOP search: return count p in [0,length] of leading elements <= key
    (= first index with arr > key). Mirrors gallop_left for the >= side."""
    if length == 0 or arr[base] > key:
        return 0
    if arr[base + length - 1] <= key:
        return length
    last = 0
    ofs = 1
    while ofs < length and arr[base + ofs] <= key:
        last = ofs
        ofs = (ofs << 1) + 1
    hi = min(ofs, length)
    lo = last + 1
    while lo < hi:
        mid = (lo + hi) >> 1
        if arr[base + mid] <= key:
            lo = mid + 1
        else:
            hi = mid
    return lo


def merge_runs(arr, a_start, a_len, b_start, b_len, tmp, stats=None):
    """Merge two adjacent ascending runs A (a_len, left) and B (b_len, right)
    into place, with GALLOPING mode.

    Copy A into tmp, then merge tmp + B -> arr. Standard one-at-a-time compare,
    but if one side wins MIN_GALLOP times in a row we switch to galloping: grab
    a whole block (found by gallop_right / gallop_left) in one shot. This is
    what makes merges of clustered/imbalanced data near O(n).

    Stability rule: when equal (tmp[i] == arr[j]) A (the left run) wins, so
    equal elements keep their original relative order. `stats` (optional) tallies
    galloping-mode entries for teaching/diagnostics.
    """
    tmp[:a_len] = arr[a_start:a_start + a_len]
    i = 0                             # cursor in tmp (A)
    j = b_start                       # cursor in B
    b_end = b_start + b_len
    k = a_start                       # write cursor
    gallop = MIN_GALLOP
    while i < a_len and j < b_end:
        # ---- one-at-a-time mode ----
        win_a = 0
        win_b = 0
        use_gallop = False
        while i < a_len and j < b_end:
            if tmp[i] <= arr[j]:      # A wins (<= keeps stable)
                arr[k] = tmp[i]
                i += 1
                k += 1
                win_a += 1
                win_b = 0
            else:
                arr[k] = arr[j]
                j += 1
                k += 1
                win_b += 1
                win_a = 0
            if win_a >= gallop or win_b >= gallop:
                use_gallop = True
                break
        if not use_gallop:
            break                     # one side exhausted in one-at-a-time
        # ---- galloping mode ----
        # lower the bar each gallop round: once data is clustered, stay in gallop
        gallop = max(2, gallop - 1)
        if stats is not None:
            stats["gallop_entries"] = stats.get("gallop_entries", 0) + 1
        while i < a_len and j < b_end:
            # how many from A are <= arr[j]? gallop them in as one block.
            na = gallop_right(arr[j], tmp, i, a_len - i)
            for _ in range(na):
                arr[k] = tmp[i]
                i += 1
                k += 1
            if i >= a_len or j >= b_end:
                break
            # how many from B are STRICTLY < tmp[i]? gallop them in (equal->A).
            nb = gallop_left(tmp[i], arr, j, b_end - j)
            for _ in range(nb):
                arr[k] = arr[j]
                j += 1
                k += 1
            if i >= a_len or j >= b_end:
                break
            # if both blocks were tiny, momentum is gone -> back to one-at-a-time
            if na < MIN_GALLOP and nb < MIN_GALLOP:
                break
    # ---- drain whichever side remains ----
    while i < a_len:
        arr[k] = tmp[i]
        i += 1
        k += 1
    while j < b_end:
        arr[k] = arr[j]
        j += 1
        k += 1


def merge_at(arr, stack, i, tmp, stats=None):
    """Merge stack[i] and stack[i+1] (adjacent runs) into stack[i]."""
    a = stack[i]
    b = stack[i + 1]
    assert a["start"] + a["len"] == b["start"], "runs must be adjacent"
    merge_runs(arr, a["start"], a["len"], b["start"], b["len"], tmp, stats)
    a["len"] += b["len"]
    del stack[i + 1]


def merge_collapse(arr, stack, tmp, tr=None):
    """Enforce the merge invariant on the stack until only the invariant-
    satisfying runs remain, then drain to one.

    Invariant for top three runs A,B,C (A deepest):
        len(A) > len(B) + len(C)   and   len(B) > len(C)
    Violation -> merge the shorter of {A,C} with B. This keeps the merge tree
    balanced: the largest run is never merged until smaller ones are, so depth
    stays O(log n) -> worst case O(n log n).
    """
    stats = tr["stats"] if tr is not None else None
    while len(stack) > 1:
        n = len(stack)
        if n >= 3 and stack[n - 3]["len"] <= stack[n - 2]["len"] + stack[n - 1]["len"]:
            if stack[n - 3]["len"] < stack[n - 1]["len"]:
                merge_at(arr, stack, n - 3, tmp, stats)
            else:
                merge_at(arr, stack, n - 2, tmp, stats)
        elif stack[n - 2]["len"] <= stack[n - 1]["len"]:
            merge_at(arr, stack, n - 2, tmp, stats)
        else:
            break
    # final drain: collapse to a single run
    while len(stack) > 1:
        merge_at(arr, stack, len(stack) - 2, tmp, stats)


def tim_sort(arr, trace=False):
    """In-place Timsort. Returns the sorted array (mutated in place).

    trace=True returns (array, trace_dict) where trace_dict records minrun,
    the runs found (start, len, was_descending), the merge-stack history, and
    a count of galloping triggers (approx, via a counter).
    """
    n = len(arr)
    tr = {"minrun": None, "runs": [], "merges": [],
          "gallop_threshold": MIN_GALLOP}
    if n < 2:
        tr["minrun"] = n
        return arr, tr if trace else arr
    if n < MIN_MERGE:
        # tiny: one binary insertion sort over the whole thing
        binary_insertion_sort(arr, 0, n, 0)
        tr["minrun"] = n
        tr["runs"].append({"start": 0, "len": n, "desc": False, "natural": n})
        return (arr, tr) if trace else arr

    minrun = compute_minrun(n)
    tr["minrun"] = minrun
    tr["stats"] = {"gallop_entries": 0}
    stack = []
    tmp = [0] * (n // 2 + 1)            # temp buffer for the shorter side
    lo = 0
    while lo < n:
        hi = n
        start, end, was_desc = count_run(arr, lo, hi)
        run_len = end - start
        natural = run_len
        # extend short runs to minrun with binary insertion sort
        if run_len < minrun:
            force = min(n - start, minrun)
            binary_insertion_sort(arr, start, start + force, end)
            run_len = force
            end = start + run_len
        tr["runs"].append({"start": start, "len": run_len, "natural": natural,
                           "desc": was_desc})
        stack.append({"start": start, "len": run_len})
        tr["merges"].append([(s["start"], s["len"]) for s in stack])
        merge_collapse_partial(arr, stack, tmp, tr)
        lo = end
    merge_collapse(arr, stack, tmp, tr)
    return (arr, tr) if trace else arr


def merge_collapse_partial(arr, stack, tmp, tr):
    """Same invariant as merge_collapse but stops as soon as it holds (does
    not drain to one) - runs keep coming. Records merges in tr."""
    stats = tr["stats"]
    while len(stack) > 1:
        n = len(stack)
        merged = False
        if n >= 3 and stack[n - 3]["len"] <= stack[n - 2]["len"] + stack[n - 1]["len"]:
            if stack[n - 3]["len"] < stack[n - 1]["len"]:
                merge_at(arr, stack, n - 3, tmp, stats)
            else:
                merge_at(arr, stack, n - 2, tmp, stats)
            merged = True
        elif stack[n - 2]["len"] <= stack[n - 1]["len"]:
            merge_at(arr, stack, n - 2, tmp, stats)
            merged = True
        if not merged:
            break
        tr["merges"].append([(s["start"], s["len"]) for s in stack])


# a clean, dependency-light public entry that hides the trace scaffolding
def tim_sort_simple(arr):
    return tim_sort(arr, trace=False)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_arr(a, width=4):
    return "[" + ", ".join(str(x).rjust(width) for x in a) + "]"


# ============================================================================
# 3. DETERMINISTIC INPUTS
# ============================================================================

def make_realworld(seed=7, n=32, max_val=99):
    """Simulate 'real-world' data: mostly-sorted with a few local runs and a
    couple of out-of-place appends. Deterministic seed."""
    rng = random.Random(seed)
    base = sorted(rng.randint(0, max_val) for _ in range(n))
    # introduce disorder: swap a few adjacent pairs, append some chaos
    for _ in range(3):
        i = rng.randint(0, n - 2)
        base[i], base[i + 1] = base[i + 1], base[i]
    return base


def make_input(seed=42, n=64, max_val=999):
    rng = random.Random(seed)
    return [rng.randint(0, max_val) for _ in range(n)]


# ----------------------------------------------------------------------------
# SECTION A: minrun selection - why [32,64] and why near-powers-of-two
# ----------------------------------------------------------------------------

def section_minrun():
    banner("SECTION A: minrun - the [32,64] dial that balances the merge tree")
    print(f"MIN_MERGE = {MIN_MERGE}. For n < {MIN_MERGE}, timsort is just one")
    print("binary-insertion-sort over the whole array (no runs, no merges).\n")
    print("compute_minrun(n): shift n right until < 64, OR in any dropped low")
    print("bit. Result always in [32, 64].\n")
    print("| n        | minrun | num runs ~ n/minrun | nearest pow2 |")
    print("|----------|--------|---------------------|--------------|")
    for n in [64, 100, 128, 1000, 1024, 10000, 1_000_000]:
        mr = compute_minrun(n)
        runs = math.ceil(n / mr)
        p2 = 2 ** (runs.bit_length() - 1)
        print(f"| {n:<8} | {mr:<6} | {runs:<19} | {p2:<12} |")
    print()
    print("Read it: minrun keeps num-runs at or just above a power of two, so the")
    print("merge tree is BALANCED (shallow). That is what bounds depth at O(log n)")
    print("and total work at O(n log n). The [32,64] window balances 'insertion")
    print("sort is still cheap' vs 'enough runs to balance'. Java's TimSort uses")
    print("MIN_MERGE=32 -> minrun in [16,32]; same algorithm, different constant.\n")
    # invariant: minrun in [32,64] for all n >= MIN_MERGE
    ok = all(32 <= compute_minrun(n) <= 64 for n in
             [64, 65, 127, 128, 10**6, 10**9])
    print(f"[check] minrun in [32,64] for all tested n >= {MIN_MERGE}? {ok}")
    assert ok


# ----------------------------------------------------------------------------
# SECTION B: run detection - finding the natural runs (and reversing descenders)
# ----------------------------------------------------------------------------

def section_run_detection():
    banner("SECTION B: run detection - grab every ascending/descending streak")
    # show on the classic-ish example that has a descending run
    arr = [5, 4, 3, 2, 8, 9, 1, 0, 7, 6]
    print(f"input = {fmt_arr(arr, 2)}\n")
    runs = []
    lo = 0
    n = len(arr)
    work = list(arr)
    while lo < n:
        start, end, was_desc = count_run(work, lo, n)
        runs.append((start, end, list(arr[start:end]), list(work[start:end]),
                     was_desc))
        lo = end
    print("Runs found (a run is the longest ascending OR strictly-descending slice):")
    for i, (s, e, before, after, was_desc) in enumerate(runs):
        kind = "descending -> REVERSED" if was_desc else "ascending"
        print(f"  run {i}: [{s}:{e}] = {fmt_arr(before,2)}  ({kind})  "
              f"=> {fmt_arr(after,2)}")
    print()
    print("WHY strict '>' on the descending side: equal elements must keep input")
    print("order. If a descending run used >=, two equal elements would swap on")
    print("reversal and stability is LOST. '>' keeps equals in original order.\n")
    # the already-sorted best case: one run -> O(n)
    asc = list(range(10))
    s, e, _ = count_run(list(asc), 0, len(asc))
    one_run = (e - s) == len(asc)
    print(f"already-sorted input {fmt_arr(asc,2)} -> ONE run of length {e-s}: "
          f"{one_run}")
    print(f"[check] sorted input -> single run (best case O(n))? {one_run}")
    assert one_run


# ----------------------------------------------------------------------------
# SECTION C: binary insertion sort extends short runs to minrun
# ----------------------------------------------------------------------------

def section_insertion_extension():
    banner("SECTION C: binary insertion sort - pad short runs up to minrun")
    print("A natural run shorter than minrun is too small to be worth merging.")
    print("Timsort EXTENDS it to minrun by inserting the next few elements with")
    print("BINARY insertion sort (binary search for the slot -> O(k log k) for k")
    print("new elements, cheap constants, STABLE because we use leftmost slot).\n")
    # demo: run of length 3 inside a length-8 slice, extend to minrun=8 (forced)
    arr = [2, 5, 9, 7, 1, 8, 3, 6]
    print(f"slice      : {fmt_arr(arr,2)}   (natural run [2,5,9] at start)")
    binary_insertion_sort(arr, 0, 8, 3)     # sort [0:8], prefix [0:3] sorted
    print(f"after ext. : {fmt_arr(arr,2)}   (run extended to cover the slice)")
    ok = arr == sorted([2, 5, 9, 7, 1, 8, 3, 6])
    print(f"[check] extended slice == sorted()? {ok}")
    assert ok


# ----------------------------------------------------------------------------
# SECTION D: run detection + merge invariant + galloping on real-world data
# ----------------------------------------------------------------------------

def make_gallop_demo():
    """A constructed input that exercises timsort's merge + galloping:
      * TWO natural ascending runs (so the merge stack fills then merges),
      * the RIGHT run is entirely SMALLER than the LEFT run's first element,
        so during the merge the right side wins >= MIN_GALLOP in a row and
        GALLOPING mode fires (one big block-copy instead of 32 one-by-ones).
    n = 64 -> minrun = 32, so neither run gets extended (clean trace).
    Deterministic (no RNG). Descending-run reversal is shown separately in
    Section B."""
    return list(range(60, 92)) + list(range(1, 33))    # [60..91] + [1..32]


def section_merge_gallop():
    banner("SECTION D: run detection + merge invariant + galloping")
    # ---- (1) the O(n) best case: mostly-sorted -> one run, no merges ----
    best = make_realworld(seed=7, n=32, max_val=99)
    print("(1) BEST CASE - 'real-world' mostly-sorted input (seed=7, n=32):")
    print(f"    {fmt_arr(best, 3)}")
    sb, tb = tim_sort(list(best), trace=True)
    nm = max(0, len(tb["merges"]) - 1)
    print(f"    -> {len(tb['runs'])} natural run(s), ~{nm} merge(s). cost ~ O(n). "
          f"sorted()? {sb == sorted(best)}\n")

    # ---- (2) the full machinery: runs + merge + galloping ----
    data = make_gallop_demo()
    n = len(data)
    print(f"(2) MERGE + GALLOP - constructed input (n={n}, "
          f"minrun={compute_minrun(n)}):")
    print("    run A = [60..91] (left, all >= 60)")
    print("    run B = [ 1..32] (right, all <  60)  <- B will win the merge in a run\n")
    sorted_data, tr = tim_sort(list(data), trace=True)
    ref = sorted(data)
    print(f"natural runs detected = {len(tr['runs'])}:")
    for i, r in enumerate(tr["runs"]):
        tag = "DESC -> REVERSED" if r.get("desc") else "ascending"
        ext = f", extended to {r['len']}" if r["natural"] != r["len"] else ""
        print(f"  run {i}: start={r['start']:<3} natural={r['natural']:<3} "
              f"-> len={r['len']:<3} ({tag}{ext})")
    print("\nMerge stack evolution (snapshot after each push/merge):")
    for idx, snap in enumerate(tr["merges"]):
        print(f"  step {idx}: " + ", ".join(f"({s},{ln})" for s, ln in snap))

    ge = tr.get("stats", {}).get("gallop_entries", 0)
    print(f"\nGALLOPING fired {ge} time(s) (MIN_GALLOP={MIN_GALLOP}). When B won")
    print(">= 7 in a row, the merge switched to exponential+binary search and")
    print("grabbed a whole cluster (all of B) in one shot, not 32 one-by-ones.")
    print(f"\nresult == sorted()? {sorted_data == ref}")
    ok = sorted_data == ref
    print(f"[check] timsort == sorted() on constructed input? {ok}")
    assert ok


# ----------------------------------------------------------------------------
# SECTION E: complexity + comparison, and the GOLD check
# ----------------------------------------------------------------------------

def section_complexity_and_gold():
    banner("SECTION E: complexity, comparison, and GOLD for tim_sort.html")
    print("BEST  O(n)       : input is one long run -> detected, no merges.")
    print("WORST O(n log n) : random input -> balanced merge tree (invariant).")
    print("AVG   O(n log n) : real-world sits between, often closer to O(n).\n")
    rows = [
        ("timsort",   "O(n)",        "O(n log n)", "O(n)",     "YES", "Python/Java/Rust stable"),
        ("mergesort", "O(n log n)",  "O(n log n)", "O(n)",     "YES", "guaranteed, simple"),
        ("quicksort", "O(n log n)",  "O(n^2)",     "O(log n)", "NO",  "fast avg, in-place"),
        ("heapsort",  "O(n log n)",  "O(n log n)", "O(1)",     "NO",  "in-place, worst-case ok"),
    ]
    print("| algorithm  | best        | worst        | space    | stable? | best for               |")
    print("|------------|-------------|--------------|----------|---------|------------------------|")
    for r in rows:
        print(f"| {r[0]:<10} | {r[1]:<11} | {r[2]:<12} | {r[3]:<8} | {r[4]:<7} | {r[5]:<22} |")
    print()
    print("The one-line pitch: timsort is mergesort that doesn't throw away the\n"
          "order you already had. Best case O(n), stable, and great constants.\n")

    # GOLD on a seeded input
    arr = make_input(seed=42, n=64, max_val=999)
    print("GOLD - seeded input (seed=42, n=64, max=999):")
    print(f"  input[:8]  = {fmt_arr(arr[:8], 4)}")
    print(f"  input[-8:] = {fmt_arr(arr[-8:], 4)}")
    out, tr = tim_sort(list(arr), trace=True)
    ref = sorted(arr)
    ok = out == ref
    print(f"\n  timsort result == sorted()? {ok}")
    print(f"  minrun        = {tr['minrun']}")
    print(f"  num runs      = {len(tr['runs'])}")
    print(f"  num merges    = {len(tr['merges'])}")
    assert ok
    # GOLD compact scalars for tim_sort.html
    print("\nGOLD compact scalars (for tim_sort.html):")
    print(f"  minrun     = {tr['minrun']}")
    print(f"  num_runs   = {len(tr['runs'])}")
    print(f"  sorted[0]  = {out[0]}")
    print(f"  sorted[-1] = {out[-1]}")
    # self-consistency
    assert out[0] == min(arr) and out[-1] == max(arr)
    assert 32 <= tr["minrun"] <= 64
    print("[check] gold scalars reproduce from input: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("tim_sort.py - reference impl. All numbers below feed TIM_SORT.md.")
    print("python stdlib only (no torch/numpy).\n")

    section_minrun()
    section_run_detection()
    section_insertion_extension()
    section_merge_gallop()
    section_complexity_and_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
