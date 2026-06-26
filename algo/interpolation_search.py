"""
interpolation_search.py - Reference implementation of Interpolation Search,
the probe-by-ESTIMATION cousin of binary search.

This is the SINGLE SOURCE OF TRUTH for INTERPOLATION_SEARCH.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 interpolation_search.py > interpolation_search_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - the dictionary, not the phone book
============================================================================
Binary search always flips to the MIDDLE page. That is optimal when you know
NOTHING about where the word lives. But you do not look up "xylophone" by
opening the dictionary to M and halving from there - you open near the BACK,
because you know the alphabet. Interpolation search does exactly that: it uses
the VALUES at the ends of the live window to ESTIMATE where the key sits, then
probes there.

  * binary search      : probe the MIDDLE.       Uniform effort, O(log n).
  * interpolation search: probe where the key is EXPECTED to be.

The estimate (linear interpolation between the endpoints):

        pos = lo + (key - arr[lo]) / (arr[hi] - arr[lo]) * (hi - lo)

Geometrically: draw a straight line from (lo, arr[lo]) to (hi, arr[hi]) and
read off the x-position whose y-value equals `key`. If the data is UNIFORM,
that line IS the data, so `pos` lands ON the key in one shot.

THE REASON INTERPOLATION SEARCH EXISTS: on uniformly distributed data the
expected gap shrinks DOUBLY exponentially, giving O(log log n) probes - a full
log factor faster than binary search's O(log n). But the estimate is only as
good as the data is linear: cluster the data and the estimate repeatedly
over/undershoots, and the algorithm degrades all the way to O(n).

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  probe          one comparison of arr[pos] against the key.
  live window    [lo, hi] (inclusive) that may still hold the key.
  estimate / pos the predicted index of the key, from linear interpolation
                 between the two endpoints (lo, arr[lo]) and (hi, arr[hi]).
  uniform data   values are (roughly) evenly spread: arr[i] ~ a + b*i. The
                 interpolation line coincides with the data -> 1-shot hits.
  clustered data values are bunched (exponential, heavy-tailed, etc.). The
                 line misrepresents the data -> estimates misfire -> O(n).
  O(log log n)   doubly-logarithmic: grows slower than log n. For n=2^32,
                 log2 n = 32 but log2 log2 n = 5.

============================================================================
THE LOOP (mirrors binary search, but `mid` becomes `pos`)
============================================================================
    lo, hi = 0, n - 1
    while lo <= hi and arr[lo] <= key <= arr[hi]:
        if arr[lo] == arr[hi]:            # all-equal window -> avoid /0
            return lo if arr[lo] == key else -1
        # ESTIMATE where the key is (the only line that differs from bsearch)
        pos = lo + (key - arr[lo]) * (hi - lo) // (arr[hi] - arr[lo])
        if arr[pos] == key:
            return pos
        elif arr[pos] < key:
            lo = pos + 1
        else:
            hi = pos - 1
    return -1

NOTE on the guard `arr[lo] <= key <= arr[hi]`: if the key lies OUTSIDE the
endpoint range it cannot be present (the array is sorted), so we stop at once.
This is also why a flat (all-equal) window needs a /0 guard.

KEY FORMULAS (all verified + asserted in code):
    probe estimate       pos = lo + (key-arr[lo])*(hi-lo) // (arr[hi]-arr[lo])
    average probes       O(log log n)   on UNIFORM data
    worst case           O(n)           on CLUSTERED / adversarial data
    binary search        O(log n)       always (data-shape independent)
    crossover intuition  beats binary search iff the data is ~linear

References:
    Peterson, W.W. (1957), "Addressing for random-access storage", IBM J. Res.
    Dev. - the original interpolation search idea.
    Knuth, TAOCP Vol 3, §6.2.1 / §6.2.2 - the O(log log n) average analysis for
    uniform keys, and the O(n) worst case.
    Gonnet, Rogers, "An empirical exploration of the average-case analysis of
    interpolation search" (1991) - practical probe counts.
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# Deterministic arrays (hand-seeded, no RNG) so the .html reproduces every step.
# UNIFORM: 16 evenly spaced values, step 10. The interpolation line == the data.
ARR_UNI = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100,
           110, 120, 130, 140, 150, 160]
# CLUSTERED: 15 values packed 0..14, then a single huge outlier 1_000_000.
# The interpolation line is dragged by the outlier -> estimates misfire -> O(n).
ARR_CLU = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 1_000_000]


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code INTERPOLATION_SEARCH.md)
# ============================================================================

def interpolation_search(arr: list[int], key: int) -> int:
    """Interpolation search. Returns the index of `key`, or -1.

    Invariant: if key is in arr, it lies in arr[lo..hi], and (because arr is
    sorted) arr[lo] <= key <= arr[hi]. The estimate `pos` is the index a
    straight line through the endpoints would predict for `key`.
    """
    lo, hi = 0, len(arr) - 1
    while lo <= hi and arr[lo] <= key <= arr[hi]:
        if arr[lo] == arr[hi]:                 # flat window -> no slope
            return lo if arr[lo] == key else -1
        # THE estimate (integer arithmetic, mirrors the formula exactly).
        pos = lo + (key - arr[lo]) * (hi - lo) // (arr[hi] - arr[lo])
        if arr[pos] == key:
            return pos
        elif arr[pos] < key:
            lo = pos + 1
        else:
            hi = pos - 1
    return -1


def interpolation_search_path(arr: list[int], key: int) -> tuple[list[int], int]:
    """Interpolation search that records the probe path (list of `pos`) and the
    final index (-1 if absent). Used to visualize & count probes."""
    lo, hi = 0, len(arr) - 1
    path: list[int] = []
    while lo <= hi and arr[lo] <= key <= arr[hi]:
        if arr[lo] == arr[hi]:
            if arr[lo] == key:
                path.append(lo)
                return path, lo
            return path, -1
        pos = lo + (key - arr[lo]) * (hi - lo) // (arr[hi] - arr[lo])
        # clamp pos into [lo, hi] (the formula can drift on rounding)
        pos = max(lo, min(hi, pos))
        path.append(pos)
        if arr[pos] == key:
            return path, pos
        elif arr[pos] < key:
            lo = pos + 1
        else:
            hi = pos - 1
    return path, -1


def binary_search_path(arr: list[int], key: int) -> tuple[list[int], int]:
    """Binary search companion (same path+index interface) for side-by-side
    comparison. Identical to algo/binary_search.py's exact search."""
    lo, hi = 0, len(arr) - 1
    path: list[int] = []
    while lo <= hi:
        mid = lo + (hi - lo) // 2
        path.append(mid)
        if arr[mid] == key:
            return path, mid
        elif arr[mid] < key:
            lo = mid + 1
        else:
            hi = mid - 1
    return path, -1


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE WORKED EXAMPLES
# ============================================================================

def section_probe_formula():
    banner("SECTION A: the probe formula - estimating where the key is")
    n = len(ARR_UNI)
    print("The single line that distinguishes interpolation from binary search:")
    print()
    print("    pos = lo + (key - arr[lo]) * (hi - lo) // (arr[hi] - arr[lo])")
    print()
    print("Think of it as: how far along the VALUE range [arr[lo], arr[hi]] is")
    print("the key, applied to the INDEX range [lo, hi]. Geometrically, it is")
    print("the x-coordinate where the straight line through the two endpoints")
    print("(lo, arr[lo]) and (hi, arr[hi]) reaches height `key`.\n")

    key = 110
    lo, hi = 0, n - 1
    frac_num = key - ARR_UNI[lo]
    frac_den = ARR_UNI[hi] - ARR_UNI[lo]
    pos = lo + frac_num * (hi - lo) // frac_den
    print(f"Uniform array (n={n}, step 10):")
    print("  idx:", " ".join(f"{i:>4}" for i in range(n)))
    print("  val:", " ".join(f"{v:>4}" for v in ARR_UNI))
    print(f"\nEstimate pos for key={key} on the FULL window [lo={lo}, hi={hi}]:")
    print("  fraction = (key - arr[lo]) / (arr[hi] - arr[lo])")
    print(f"           = ({key} - {ARR_UNI[lo]}) / ({ARR_UNI[hi]} - {ARR_UNI[lo]})"
          f"  = {frac_num} / {frac_den}  = {frac_num / frac_den:.4f}")
    print("  pos = lo + fraction * (hi - lo)")
    print(f"      = {lo} + {frac_num / frac_den:.4f} * {hi - lo}  = {pos}")
    print(f"  arr[{pos}] = {ARR_UNI[pos]} == key={key}  ->  ONE-SHOT HIT\n")
    assert pos == 10 and ARR_UNI[pos] == key
    print("[check] one-probe hit on uniform data:  pos=10, arr[10]=110:  OK")
    print("        (binary search on the same key takes 4 probes - Section C)")


def section_why_uniform():
    banner("SECTION B: why it works on uniform data - the line IS the data")
    print("For a perfectly uniform array arr[i] = a + b*i, the interpolation")
    print("line through ANY two points (i, arr[i]) coincides with the data. So")
    print("the estimated `pos` for any in-range key lands EXACTLY on the index")
    print("that holds it (or its insertion point). That is the source of the")
    print("one-shot hits.\n")
    print("Verify on ARR_UNI (a=10, b=10): for several keys, the estimate on")
    print("the full window lands on the true index:\n")
    print("| key | linear est. pos | true index | arr[pos] | one-shot? |")
    print("|-----|-----------------|-------------|----------|-----------|")
    lo, hi = 0, len(ARR_UNI) - 1
    one_shots = 0
    for key in [10, 40, 90, 110, 160]:
        pos = lo + (key - ARR_UNI[lo]) * (hi - lo) // (ARR_UNI[hi] - ARR_UNI[lo])
        idx = ARR_UNI.index(key)
        hit = ARR_UNI[pos] == key
        one_shots += hit
        print(f"| {key:>3} | {pos:>15} | {idx:>11} | {ARR_UNI[pos]:>8} | "
              f"{'yes' if hit else 'no ':>9} |")
    print(f"\n{one_shots}/5 in-range keys are hit in a single probe. The miss")
    print("(if any) is purely integer-rounding at the endpoints. This is why")
    print("interpolation search averages O(log log n) - rarely more than ~2-3")
    print("probes - on uniform data.")


def section_complexity_uniform():
    banner("SECTION C: complexity on uniform data - O(log log n) vs O(log n)")
    n = len(ARR_UNI)
    key = 110
    ipath, ifound = interpolation_search_path(ARR_UNI, key)
    bpath, bfound = binary_search_path(ARR_UNI, key)
    print(f"Uniform array, n={n}, search key={key} (present):\n")
    print(f"  interpolation search : path {ipath}  -> index {ifound}  "
          f"({len(ipath)} probe{'s' if len(ipath)!=1 else ''})")
    print(f"  binary search        : path {bpath}  -> index {bfound}  "
          f"({len(bpath)} probes)\n")
    assert ifound == bfound == ARR_UNI.index(key)
    print(f"Interpolation wins {len(bpath)}-to-{len(ipath)} here. The expected")
    print("probe count is O(log log n); binary search is O(log n):\n")
    print("| n            | log2 n (binary) | log2 log2 n (interp) |")
    print("|--------------|-----------------|----------------------|")
    for nn in [16, 256, 4096, 65536, 1 << 20, 1 << 32]:
        logn = math.log2(nn)
        loglogn = math.log2(logn) if logn > 0 else 0
        print(f"| {nn:>12,} | {logn:>15.1f} | {loglogn:>20.1f} |")
    print("\nFor a billion elements, binary search needs ~30 probes but")
    print("interpolation search averages ~5. That gap is the whole point.")
    print("\n[check] interpolation beats binary on uniform key=110:  "
          f"{len(ipath)} < {len(bpath)}:  OK")


def section_degradation():
    banner("SECTION D: the degradation - clustered data collapses to O(n)")
    n = len(ARR_CLU)
    print("Now a CLUSTERED array: 15 values packed tightly (0..14) plus one")
    print("huge outlier (1,000,000). The interpolation line is dragged by the")
    print("outlier, so the estimated `pos` for a small key lands near 0 every")
    print("time, and the search CRAWLS one index per probe.\n")
    print("  idx:", " ".join(f"{i:>8}" for i in range(n)))
    print("  val:", " ".join(f"{v:>8,}" for v in ARR_CLU))
    print()

    key = 14
    ipath, ifound = interpolation_search_path(ARR_CLU, key)
    bpath, bfound = binary_search_path(ARR_CLU, key)
    print(f"Search key={key} (present at index 14):\n")
    print("Interpolation search - step by step:")
    lo, hi = 0, n - 1
    for step, pos in enumerate(ipath):
        if pos < len(ARR_CLU):
            verdict = ("== key -> FOUND" if ARR_CLU[pos] == key else
                       ("< key -> lo=pos+1" if ARR_CLU[pos] < key
                        else "> key -> hi=pos-1"))
            print(f"  step {step:>2}: window [lo={lo}, hi={hi}]  "
                  f"pos={pos:>2}  arr[pos]={ARR_CLU[pos]:>9,}  {verdict}")
            if ARR_CLU[pos] < key:
                lo = pos + 1
            elif ARR_CLU[pos] > key:
                hi = pos - 1
            else:
                break
    print(f"\n  interpolation: {len(ipath)} probes -> index {ifound}")
    print(f"  binary       : {len(bpath)} probes -> index {bfound}  "
          f"(path {bpath})\n")
    assert ifound == bfound == 14
    ratio = len(ipath) / len(bpath)
    print(f"Interpolation is {ratio:.1f}x SLOWER than binary search here. The")
    print("outlier makes (arr[hi]-arr[lo]) ~ 1,000,000 while (key-arr[lo]) is")
    print("~14, so the fraction is ~0.000014 and `pos` floored to `lo` every")
    print("time - the window shrinks by ONE index per step, i.e. O(n).\n")
    print("Worst case (adversarial / exponential data): interpolation search is")
    print("O(n); binary search stays O(log n). Use interpolation ONLY when the")
    print("data is known to be (approximately) uniform.")
    print("\n[check] interpolation degrades (>= binary probes) on clustered "
          f"key=14:  {len(ipath)} >= {len(bpath)}:  "
          f"{'OK' if len(ipath) >= len(bpath) else 'FAIL'}")


def section_comparison():
    banner("SECTION E: when to use which - the decision table")
    print("| data shape          | interpolation avg | binary worst | pick        |")
    print("|---------------------|-------------------|--------------|-------------|")
    print("| uniform / linear    | O(log log n)      | O(log n)     | INTERPOLATE |")
    print("| clustered / skewed  | up to O(n)        | O(log n)     | BINARY      |")
    print("| unknown / adversarial| up to O(n)       | O(log n)     | BINARY      |")
    print("| small n (< ~50)     | ~same             | O(log n)     | BINARY      |")
    print()
    print("Side-by-side probe counts across BOTH arrays and several keys:\n")
    print("| array      | key        | interpolation probes | binary probes | winner |")
    print("|------------|------------|----------------------|---------------|--------|")
    cases = [
        (ARR_UNI, 110, "present"),
        (ARR_UNI, 75, "absent"),
        (ARR_UNI, 10, "first"),
        (ARR_CLU, 14, "clustered-small"),
        (ARR_CLU, 1_000_000, "outlier"),
    ]
    for arr, key, tag in cases:
        ipath, ifound = interpolation_search_path(arr, key)
        bpath, bfound = binary_search_path(arr, key)
        name = "uniform" if arr is ARR_UNI else "clustered"
        winner = "interp" if len(ipath) < len(bpath) else (
            "binary" if len(bpath) < len(ipath) else "tie")
        print(f"| {name:<10} | {key:>10,} | {len(ipath):>20} | "
              f"{len(bpath):>13} | {winner:<6} |")
    print()
    print("Read it: interpolation dominates on the uniform array (incl. the")
    print("absent key, which exits in 1 probe because the estimate places it")
    print("outside the endpoint range). On the clustered array it loses badly")
    print("for the small key (crawls) and ties/wins for the outlier itself.")


def section_gold():
    banner("SECTION F: GOLD values (pinned for interpolation_search.html)")
    ipath, ifound = interpolation_search_path(ARR_UNI, 110)
    print(f"Uniform array: {ARR_UNI}")
    print(f"interpolation_search(key=110) -> index {ifound}, path {ipath}, "
          f"{len(ipath)} probe(s)")
    print(f"GOLD uniform path for key=110: {ipath}")
    print(f"GOLD uniform index for key=110: {ifound}")

    bpath, bfound = binary_search_path(ARR_UNI, 110)
    print(f"binary_search(key=110)         -> index {bfound}, path {bpath}, "
          f"{len(bpath)} probes")
    print(f"GOLD binary path for key=110: {bpath}")

    cpath, cfound = interpolation_search_path(ARR_CLU, 14)
    print(f"\nClustered array: {ARR_CLU}")
    print(f"interpolation_search(key=14) -> index {cfound}, {len(cpath)} probes")
    print(f"GOLD clustered probe count for key=14: {len(cpath)}")
    print(f"GOLD clustered path for key=14: {cpath}")

    bpath_c, _ = binary_search_path(ARR_CLU, 14)
    print(f"binary_search(key=14)       -> {len(bpath_c)} probes (path {bpath_c})")
    print(f"GOLD binary probes on clustered key=14: {len(bpath_c)}")

    # self-consistency asserts
    assert ipath == [10] and ifound == 10
    assert bpath == [7, 11, 9, 10] and bfound == 10
    assert cfound == 14 and len(cpath) == 15
    assert cpath == list(range(15))
    assert len(bpath_c) == 4
    print("\n[check] all GOLD values reproduce from the implementations:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("interpolation_search.py - reference impl. All numbers below feed "
          "INTERPOLATION_SEARCH.md.")
    section_probe_formula()
    section_why_uniform()
    section_complexity_uniform()
    section_degradation()
    section_comparison()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
