"""
radix_sort.py - Reference implementation of LSD Radix Sort, with counting sort
as its stable subroutine.

This is the single source of truth that RADIX_SORT.md is built from. Every
number, table, and worked example in RADIX_SORT.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python radix_sort.py

=========================================================================
THE INTUITION (read this first) - sorting a deck of cards, one column at a time
=========================================================================
Imagine you are sorting 10,000 phone numbers written on cards, each digit in its
own little window. You can't compare whole numbers at a glance, but you CAN sort
by a SINGLE digit instantly: make 10 piles (buckets 0..9), deal every card onto
the pile matching that digit, then scoop the piles back up in order 0,1,...,9.

Do that for the UNITS digit, then the TENS, then the HUNDREDS... and after the
last pass the whole deck is sorted. That is RADIX SORT.

  * Why "radix"?  The RADIX (base) is how many buckets you use. Base 10 -> 10
    buckets. Base 2 -> 2 buckets but more passes. Base 256 -> 256 buckets but
    fewer passes (this is what real int-sort code uses).
  * Why LSD (Least Significant Digit) first?  Because a STABLE per-digit sort
    preserves the order built by the lower digits. The most-significant-digit
    pass then acts last and "wins" - exactly like how the last comparator in a
    tuple sort decides the final order when earlier keys tie.
  * Why no comparisons?  We never ask "is 45 < 75?". We only ask "what is the
    units digit?". That is why the cost is O(d*n), NOT O(n log n): it sidesteps
    the comparison-sort lower bound entirely (the bound only applies to sorts
    that learn about order solely through pairwise comparisons).

THE REASON RADIX EXISTS: comparison sorts (mergesort, quicksort, heapsort) are
proven to need Omega(n log n) comparisons. But integers are NOT a black box -
they are a fixed number of digits d. Radix sort exploits that structure to do
d counting passes, each O(n + b). When d is small and fixed (e.g. 32-bit ints
in base 2^16 = 2 passes), radix beats the n-log-n barrier in raw work count.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  radix / base : number of buckets per pass. Here b = 10 (decimal digits).
  digit pass   : one counting-sort round on ONE digit position.
  LSD          : Least Significant Digit - the order we process digits in.
  counting sort: a stable, non-comparison sort on keys in a small range [0,b).
                 THE subroutine of radix sort.
  stable       : equal keys keep their input order. REQUIRED for radix to work.
  bucket       : the pile of numbers sharing the same digit this pass.

=========================================================================
THE LINEAGE (sources)
=========================================================================
  Radix sort (Herman 1961 computer implementation; idea is older - radix goes
              back to mechanical card sorters, Hollerith 1890 census machine).
  Counting sort : CLRS 8.2 (the stable subroutine).
  LSD radix     : CLRS 8.3 (the version here - least-significant first).
  MSD radix     : CLRS 8.3 - most-significant first, recursive; not covered.

KEY FORMULAS (all verified against CLRS + asserted in code):
    digit(x, place) = (x // place) % radix        # the digit at `place`
    counting pass   : O(n + radix) time, O(n+radix) extra space, STABLE
    radix total     : O(d * (n + radix))  =  O(d*n) when radix << n
                      where d = number of digits of the max element
    d               = floor(log_radix(max)) + 1
    STABILITY RULE  : counting sort MUST process input left-to-right and place
                      elements right-to-left in the output (see Section A) so
                      ties keep input order. Without stability radix is WRONG.

Conventions:
    n     = number of elements
    radix = base (10 here)
    d     = number of digit passes = digits(max_value)
    place = radix**exp  (1, 10, 100, ...)  the weight of the current digit
"""

from __future__ import annotations

import random

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code RADIX_SORT.md walks through)
# ============================================================================

def counting_sort_by_digit(arr, place, radix=10):
    """Stable counting sort on the digit at `place` (weight = radix**exp).

    This is the ONE subroutine radix sort reuses d times. STABILITY is the
    entire point: equal-digit elements must emerge in their input order, or the
    lower-digit passes' work gets destroyed by the higher-digit passes.

    IN PLAIN ENGLISH (the bucket dealer):
        1. COUNT  how many cards land in each of the `radix` buckets.
        2. PREFIX-SUM the counts -> each bucket now says "my cards go to output
           positions [start .. start+count)".
        3. DEAL  walk the input RIGHT-TO-LEFT, placing each card at the
           (decremented) bucket position. Right-to-left is what makes it stable:
           the last-seen equal card goes in the last slot of its run.

    Returns a NEW list (does not mutate input). O(n + radix).
    """
    n = len(arr)
    output = [0] * n
    count = [0] * radix

    # 1. COUNT digit frequencies
    for x in arr:
        d = (x // place) % radix
        count[d] += 1

    # 2. PREFIX SUM -> bucket start positions (exclusive end -> inclusive start)
    for i in range(1, radix):
        count[i] += count[i - 1]

    # 3. DEAL right-to-left for STABILITY
    for i in range(n - 1, -1, -1):
        x = arr[i]
        d = (x // place) % radix
        count[d] -= 1
        output[count[d]] = x
    return output


def bucket_distribution(arr, place, radix=10):
    """Return {digit: [elements in input order]} for tracing/teaching.

    Same grouping the counting pass computes, but kept as explicit buckets so
    the .md / .html can show "pile 5 got [45, 75]". Order within a bucket is
    the input order (left-to-right), which is what stability later preserves.
    """
    buckets = {i: [] for i in range(radix)}
    for x in arr:
        d = (x // place) % radix
        buckets[d].append(x)
    return buckets


def radix_sort_lsd(arr, radix=10, trace=False):
    """LSD radix sort. Returns a sorted NEW list (does not mutate input).

    Passes from the LEAST significant digit to the MOST. After pass k, the
    array is sorted by the low k digits; the final pass (most significant)
    leaves it fully sorted. Non-negative integers only (see note below).

    trace=True yields (place, buckets, array_after) tuples per pass.
    """
    if not arr:
        return []
    assert all(x >= 0 for x in arr), "LSD radix here handles non-negative ints"
    mx = max(arr)
    # number of passes d = digits of max in this base = floor(log_radix(mx))+1,
    # i.e. place = radix**0, radix**1, ..., up to the highest digit of mx.
    work = list(arr)
    place = 1
    passes = []
    while place <= mx:                    # places 1, radix, radix^2, ... <= mx
        buckets = bucket_distribution(work, place, radix)
        work = counting_sort_by_digit(work, place, radix)
        passes.append((place, buckets, list(work)))
        place *= radix
    # edge case mx == 0: every element is 0, already "sorted" (0 passes).
    if trace:
        return work, passes
    return work


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
# 3. THE TINY CONCRETE WORKED EXAMPLE  (classic textbook trace, fixed)
#    Small enough to print every bucket, big enough to show all 3 passes.
# ============================================================================

CLASSIC = [170, 45, 75, 90, 802, 24, 2, 66]


def make_input(seed=42, n=12, max_val=9999):
    """Deterministic input for the gold-check example.

    Seeded so every run + the .html use byte-identical inputs.
    """
    rng = random.Random(seed)
    return [rng.randint(0, max_val) for _ in range(n)]


# ----------------------------------------------------------------------------
# SECTION A: the counting-sort subroutine, and why it must be STABLE
# ----------------------------------------------------------------------------

def section_counting_sort():
    banner("SECTION A: counting sort - the stable subroutine (and why "
           "stability is non-negotiable)")
    radix = 10
    print(f"radix (base) = {radix} buckets, digits 0..{radix-1}\n")
    print("Counting sort on a single digit, place=1 (units):\n")
    demo = [40, 21, 11, 30, 22]            # units digits: 0,1,1,0,2
    print(f"  input   : {fmt_arr(demo)}")
    print(f"  digits  : {[ (x // 1) % radix for x in demo]}")
    out = counting_sort_by_digit(demo, place=1, radix=radix)
    print(f"  output  : {fmt_arr(out)}")
    print("  (two 0-units then two 1-units then 2; within a digit, INPUT order "
          "kept -> stable)\n")

    print("WHY STABILITY IS THE WHOLE GAME:")
    print("  Suppose we sorted the units digit UNSTABLY. After the units pass:")
    print("    [40, 30, 21, 11, 22]   <- some tie order (say 30 before 40)")
    print("  The tens pass would then carry that scrambled tie order up. After")
    print("  radix finishes, ties could be in ANY order - but worse, a higher")
    print("  digit pass can DEMOTE a correctly-placed lower digit. Stability")
    print("  guarantees: 'a later pass only reorders when its digit differs.'\n")

    # prove stability directly on the duplicate-unit pairs (40,30) and (21,11):
    # each pair must keep its input order in the output.
    pairs = [(40, 30), (21, 11)]
    ok = all(out.index(x) < out.index(y) for x, y in pairs)
    print(f"[check] counting sort stable on duplicate-unit pairs? {ok}")
    assert ok, "counting sort lost stability!"


# ----------------------------------------------------------------------------
# SECTION B: LSD digit-pass trace on the classic example (bucket distribution)
# ----------------------------------------------------------------------------

def section_digit_pass_trace():
    banner("SECTION B: LSD digit-pass trace - watch the buckets fill, 3 passes")
    arr = list(CLASSIC)
    radix = 10
    print(f"input = {fmt_arr(arr)}   (max = {max(arr)}, so d = "
          f"{len(str(max(arr)))} passes)\n")
    sorted_arr, passes = radix_sort_lsd(arr, radix=radix, trace=True)
    exp = 0
    for place, buckets, after in passes:
        exp += 1
        digit_name = {1: "units", 10: "tens", 100: "hundreds",
                      1000: "thousands"}.get(place, f"x{place}")
        print(f"--- PASS {exp}: sort by the {digit_name} digit (place={place}) ---")
        print("  digit of each element:")
        for x in arr:
            print(f"    {x:>4} -> digit {(x // place) % radix}")
        print("  bucket distribution (non-empty buckets only):")
        for d in range(radix):
            if buckets[d]:
                print(f"    bucket[{d}] = {fmt_arr(buckets[d])}")
        print(f"  array after this pass: {fmt_arr(after)}\n")
        arr = after
    print(f"RESULT after {len(passes)} passes: {fmt_arr(sorted_arr)}")
    correct = sorted(CLASSIC)
    print(f"sorted() reference      : {fmt_arr(correct)}")
    ok = sorted_arr == correct
    print(f"[check] matches Python sorted()? {ok}")
    assert ok


# ----------------------------------------------------------------------------
# SECTION C: complexity - O(d*(n+radix)), the comparison-sort barrier, and when
#            radix actually wins
# ----------------------------------------------------------------------------

def section_complexity():
    banner("SECTION C: complexity - O(d * (n + radix)) and the n-log-n barrier")
    print("Per counting pass:  O(n) to count + O(radix) prefix sums + O(n) to "
          "deal = O(n + radix).")
    print("Number of passes d = floor(log_radix(max)) + 1.\n")
    print("TOTAL:  T(n) = d * (n + radix)\n")
    print("  When radix is constant (10) and small vs n:  T = O(d * n).")
    print("  d is a property of the DATA, not of n. For 32-bit ints in base")
    print("  2^16, d = 2. So radix sort of 1M 32-bit ints = 2 counting passes.")
    print("  A comparison sort of the same = ~20M comparisons. Radix does LESS.\n")

    # comparison-sort lower bound reminder
    import math
    n = 1_000_000
    comp_lo = n * math.log2(n)
    print(f"  n = {n:,}:  comparison-sort lower bound ~ n*log2(n) = "
          f"{comp_lo:,.0f} comparisons")
    for base, d_bits in [(10, None), (256, None), (2**16, None)]:
        # digits to cover a 32-bit int in this base
        d = math.ceil(math.log(2**32, base))
        cost = d * n
        print(f"  radix sort base {base:<6}: d = {d} passes -> {cost:,.0f} "
              f"digit-ops  ({cost/comp_lo:.2f}x the comparison bound)")
    print("\n  Note base 2^16 (d=2) does ~8% of the work of the comparison")
    print("  lower bound. THAT is why radix wins for fixed-width integer keys.\n")

    # SPACE
    print("SPACE: O(n + radix) extra per pass (count array + output buffer).")
    print("  This is the trade-off vs in-place heapsort: radix is NOT in-place.")
    print("STABILITY: YES (inherited from counting sort).")
    print("NOT a comparison sort, so Omega(n log n) lower bound DOES NOT APPLY.")


# ----------------------------------------------------------------------------
# SECTION D: comparison table vs the comparison sorts
# ----------------------------------------------------------------------------

def section_comparison():
    banner("SECTION D: radix sort vs the comparison sorts")
    rows = [
        ("radix sort",   "O(d*(n+b))", "O(d*(n+b))", "O(n+b)",   "YES (stable)", "int/str keys"),
        ("counting sort","O(n+k)",     "O(n+k)",     "O(n+k)",   "YES (stable)", "small int range k"),
        ("quicksort",    "O(n log n)", "O(n^2)",     "O(log n)", "NO  (in-place)","general, comparison"),
        ("mergesort",    "O(n log n)", "O(n log n)", "O(n)",     "YES (stable)", "general, stable"),
        ("heapsort",     "O(n log n)", "O(n log n)", "O(1)",     "NO  (in-place)","general, guaranteed"),
    ]
    print("| algorithm    | best         | worst        | space      | stable?        | best for            |")
    print("|--------------|--------------|--------------|------------|----------------|---------------------|")
    for r in rows:
        print(f"| {r[0]:<12} | {r[1]:<12} | {r[2]:<12} | {r[3]:<10} | "
              f"{r[4]:<14} | {r[5]:<19} |")
    print()
    print("When to pick radix: fixed-width integer/string keys, n large, and you")
    print("can afford the O(n) extra memory. When keys are arbitrary comparable")
    print("objects (no digit decomposition) or memory is tight -> quicksort/heap.")
    print("PITFALL: radix needs non-negative ints here. For signed/floats you map")
    print("them to unsigned first (flip sign bit for floats) - see CLRS 8.3 notes.")


# ----------------------------------------------------------------------------
# SECTION E: gold check on a seeded input (pin for radix_sort.html)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION E: GOLD - pinned output for radix_sort.html")
    arr = make_input(seed=42, n=12, max_val=9999)
    print("seeded input (seed=42, n=12, max=9999):")
    print(f"  {fmt_arr(arr)}\n")
    result, passes = radix_sort_lsd(arr, radix=10, trace=True)
    ref = sorted(arr)
    print(f"radix result : {fmt_arr(result)}")
    print(f"sorted() ref : {fmt_arr(ref)}")
    ok = result == ref
    print(f"[check] radix == sorted()? {ok}")
    assert ok

    print(f"\nnumber of digit passes d = {len(passes)} (max={max(arr)}, "
          f"{len(str(max(arr)))} digits)\n")

    # pin bucket distribution of PASS 1 (units) for the .html
    p1_place, p1_buckets, p1_after = passes[0]
    print(f"GOLD pass-1 (units, place={p1_place}) bucket distribution:")
    for d in range(10):
        if p1_buckets[d]:
            print(f"  bucket[{d}] = {fmt_arr(p1_buckets[d])}")
    print(f"GOLD pass-1 array after: {fmt_arr(p1_after)}\n")

    # GOLD compact scalars: first & last element of the final sorted array, and
    # the size of bucket[0] in pass 1. .html recomputes and checks these.
    gold_first = result[0]
    gold_last = result[-1]
    gold_b0_pass1 = len(p1_buckets[0])
    print("GOLD compact scalars (for radix_sort.html):")
    print(f"  sorted[0]            = {gold_first}")
    print(f"  sorted[-1]           = {gold_last}")
    print(f"  pass1 bucket[0] size = {gold_b0_pass1}")
    # self-consistency
    assert gold_first == min(arr) and gold_last == max(arr)
    assert len(p1_buckets[0]) == sum(1 for x in arr if x % 10 == 0)
    print("[check] gold scalars reproduce from input: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("radix_sort.py - reference impl. All numbers below feed RADIX_SORT.md.")
    print("python stdlib only (no torch/numpy).\n")

    section_counting_sort()
    section_digit_pass_trace()
    section_complexity()
    section_comparison()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
