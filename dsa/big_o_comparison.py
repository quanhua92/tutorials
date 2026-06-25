"""
big_o_comparison.py - Reference implementation of Big-O growth rates and the
Master Theorem.

This is the single source of truth that BIG_O_COMPARISON.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 big_o_comparison.py

=========================================================================
THE INTUITION (read this first) - the "shopping list" analogy
=========================================================================
Big-O is NOT about speed. It is about how badly things blow up as the input N
grows. Imagine your shopping list has N items:

  * O(1)      : read the FIRST item.                List size does not matter.
  * O(log N)  : find an item in a SORTED list by    Halve the list each step.
                halving it (binary search).
  * O(N)      : scan the whole list once.           One pass.
  * O(N log N): sort the list (merge sort).         N halving-passes.
  * O(N^2)    : compare every item to every other.  Nested double loop.
  * O(2^N)    : try every subset of the list.       Doubles each item added.
  * O(N!)     : try every ORDERING of the list.     Traveling salesman.

THE REASON BIG-O EXISTS: hardware gets faster ~linearly, but algorithms scale
DIFFERENTLY. An O(N^2) sort that finishes in 1 second on 1,000 items takes
~28 HOURS on 100,000 items. An O(N log N) sort on 100,000 items takes ~0.02
seconds. Buying a faster computer never rescues a bad complexity class; only a
better algorithm does. That is the whole point of Big-O: it tells you which
algorithm SURVIVES scale, and which one collapses.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  N            : the size of the input (items in the list).
  operation    : one unit of work the algorithm does (a comparison, a write).
  Big-O        : an UPPER bound on growth, ignoring constant factors and lower
                 order terms. "O(N^2)" means "at most ~N^2 work, for large N".
  complexity   : shorthand for "time complexity" - how work scales with N.
  asymptotic   : "as N grows toward infinity". Big-O only cares about large N.
  log2(N)      : how many times you can halve N before hitting 1. The binary
                 search / merge sort workhorse.
  crossover    : the input size where one algorithm overtakes another, because
                 of CONSTANT FACTORS (see Section D).
  recurrence   : T(N) = a*T(N/b) + f(N). How divide-and-conquer work is written.
  Master thm.  : a recipe to turn a recurrence into a closed-form Big-O.

=========================================================================
KEY FORMULAS (all asserted in code below):
    log2(N)            = math.log2(N)
    N!                 = math.factorial(N) = 1 * 2 * ... * N
    T(N) = a*T(N/b) + f(N)              (divide-and-conquer recurrence)
    p    = log_b(a) = log(a)/log(b)     (the critical exponent)
    Master Case 1: f(N) = O(N^(p-eps))   -> T(N) = Theta(N^p)
    Master Case 2: f(N) = Theta(N^p)     -> T(N) = Theta(N^p * log N)
    Master Case 3: f(N) = Omega(N^(p+eps))-> T(N) = Theta(f(N))
    Crossover:        c1*N^2 = c2*N*log2(N)  ->  N / log2(N) = c2 / c1

Conventions:
    log base is ALWAYS 2 (standard in CS). "O(log N)" means O(log2 N).
    1 operation = 1 nanosecond in Section B (a 1 GHz machine does ~1 op/ns).
"""

from __future__ import annotations

import math
import sys

# Python 3.11+ caps int->str at 4300 digits. We print huge integers (100000!
# has 456574 digits), so lift the cap. 0 = unlimited.
sys.set_int_max_str_digits(0)

BANNER = "=" * 72

# The seven complexity classes, in order from fastest to slowest growth.
COMPLEXITIES = ["O(1)", "O(log N)", "O(N)", "O(N log N)", "O(N^2)", "O(2^N)", "O(N!)"]


# ============================================================================
# 1. THE GROWTH FUNCTIONS  (one line per complexity class - the ground truth)
# ============================================================================

def growth(name: str, n: int) -> float | int:
    """Exact operation count for complexity `name` at input size `n`.

    Returns an int for the integer-valued classes and a float for the log-based
    ones. This single function is recomputed in big_o_comparison.html, so every
    table, chart, and gold value derives from it.
    """
    if name == "O(1)":
        return 1
    if name == "O(log N)":
        return math.log2(n) if n > 0 else 0.0
    if name == "O(N)":
        return n
    if name == "O(N log N)":
        return n * math.log2(n) if n > 0 else 0.0
    if name == "O(N^2)":
        return n * n
    if name == "O(2^N)":
        return 2 ** n
    if name == "O(N!)":
        return math.factorial(n)
    raise ValueError(name)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_big(n) -> str:
    """Format an integer operation count. Small -> grouped digits;
    large -> scientific with an exact digit count (e.g. '1.027e301 (302 digits)')."""
    if isinstance(n, float):
        if n < 1000:
            return f"{n:.2f}"
        return f"{n:,.0f}"
    if n < 1_000_000_000:                       # under a billion: full number
        return f"{n:,}"
    s = str(n)
    mant = s[0] + "." + s[1:4]                  # 4 significant figures
    return f"{mant}e{len(s) - 1} ({len(s)} digits)"


def fmt_time_ns(ops) -> str:
    """Human-readable wall-clock time when 1 op = 1 ns. Handles the astronomical
    cases (2^N, N!) that overflow float, by working in log10 space and comparing
    to the age of the universe (~4.35e26 ns)."""
    UNIVERSE_NS = 13.8e9 * 365.25 * 24 * 3600 * 1e9          # ~4.35e26 ns
    if ops < 1e15:                                            # under ~27 years: float
        ns = float(ops)
        if ns < 1e3:
            return f"{ns:.1f} ns"
        if ns < 1e6:
            return f"{ns / 1e3:.2f} us"
        if ns < 1e9:
            return f"{ns / 1e6:.2f} ms"
        if ns < 1e12:
            return f"{ns / 1e9:.2f} s"
        return f"{ns / (60 * 60 * 1e9):.2f} hours"
    # Huge: express as 10^x ns  ==  10^(x - 26.64) ages of the universe.
    if isinstance(ops, int):
        s = str(ops)
        log10_ops = (len(s) - 1) + math.log10(int(s[:16])) - (len(s[:16]) - 1)
    else:
        log10_ops = math.log10(ops)
    log10_uni = math.log10(UNIVERSE_NS)                       # ~26.64
    diff = log10_ops - log10_uni                              # = log10(age-of-universe count)
    mant = 10 ** (diff - math.floor(diff))                    # mantissa in [1, 10), never overflows
    exp = int(math.floor(diff))
    return f"10^{log10_ops:.0f} ns  =  {mant:.1f}e{exp} x age of universe"


# ============================================================================
# 3. THE REFERENCE SORTS  (used in Section D crossover, with comparison counts)
# ============================================================================

def insertion_sort_comps(arr: list[int]) -> int:
    """In-place insertion sort. Returns the EXACT comparison count on the given
    input. Worst case (reverse sorted) = N*(N-1)/2 comparisons."""
    a = list(arr)
    n = len(a)
    comps = 0
    for i in range(1, n):
        key = a[i]
        j = i - 1
        while j >= 0:
            comps += 1
            if a[j] > key:
                a[j + 1] = a[j]
                j -= 1
            else:
                break
        a[j + 1] = key
    return comps


def merge_sort_comps(arr: list[int]) -> int:
    """Top-down merge sort. Returns the EXACT comparison count. Needs an O(N)
    auxiliary buffer each merge (see Section E)."""
    a = list(arr)
    comps = [0]

    def merge(lo, mid, hi):
        left = a[lo:mid + 1]
        right = a[mid + 1:hi + 1]
        i = j = 0
        k = lo
        while i < len(left) and j < len(right):
            comps[0] += 1
            if left[i] <= right[j]:
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

    def msort(lo, hi):
        if lo < hi:
            mid = (lo + hi) // 2
            msort(lo, mid)
            msort(mid + 1, hi)
            merge(lo, mid, hi)

    if a:
        msort(0, len(a) - 1)
    return comps[0]


# ============================================================================
# 4. THE MASTER THEOREM  (recurrence -> closed-form Big-O)
# ============================================================================

def master_theorem(a: int, b: int, c: float):
    """Classify T(N) = a*T(N/b) + Theta(N^c).

    Returns (case_label, p, result_name) where p = log_b(a) is the critical
    exponent and result_name is the closed-form complexity.

    Case 1: c < p   -> T(N) = Theta(N^p)        (leaves dominate)
    Case 2: c = p   -> T(N) = Theta(N^p log N)  (balanced; leaves == combine)
    Case 3: c > p   -> T(N) = Theta(N^c)        (combine/recursive cost dominates)
    """
    assert a >= 1 and b > 1, "need a>=1, b>1"
    p = math.log(a) / math.log(b)
    eps = 1e-9
    def clean(x):
        return int(round(x)) if abs(x - round(x)) < 1e-6 else round(x, 4)
    pc = clean(p)
    if c < p - eps:
        return ("Case 1", p, f"Theta(N^{pc})")
    if abs(c - p) < eps:
        if pc == 0:
            return ("Case 2", p, "Theta(log N)")
        return ("Case 2", p, f"Theta(N^{pc} log N)")
    cc = clean(c)
    return ("Case 3", p, f"Theta(N^{cc})")


# ----------------------------------------------------------------------------
# SECTION A: the growth table  (operations for N = 1 .. 100000)
# ----------------------------------------------------------------------------

def section_growth_table():
    banner("SECTION A: the growth table - operations vs input size N")
    print("Each cell is the EXACT operation count for that complexity at size N.")
    print("The two right-most columns explode so fast that for large N we show")
    print("the value in scientific notation with its exact digit count.\n")
    Ns = [1, 10, 100, 1000, 10000, 100000]
    header = "| {:>7} |".format("N") + "".join(f" {c:>18} |" for c in COMPLEXITIES)
    print(header)
    print("|" + "-" * (len(header) - 2) + "|")
    for n in Ns:
        cells = []
        for c in COMPLEXITIES:
            v = growth(c, n)
            cells.append(fmt_big(v))
        print("| {:>7} |".format(n) + "".join(f" {cell:>18} |" for cell in cells))
    print()
    print("Read the bottom-right corner: N=100000.")
    print(f"  O(2^N)   = {fmt_big(2 ** 100000)}")
    print(f"  O(N!)    = {fmt_big(math.factorial(100000))}")
    print("  O(2^N) and O(N!) are so vast they are not 'slow' - they are")
    print("  IMPOSSIBLE to compute at scale, no matter the hardware. That is why")
    print("  'exponential' and 'factorial' are the border between 'tractable'")
    print("  and 'intractable' in computer science.")


# ----------------------------------------------------------------------------
# SECTION B: time-to-run at N=1000  (1 op = 1 nanosecond)
# ----------------------------------------------------------------------------

def section_time_to_run():
    banner("SECTION B: time-to-run at N=1000  (assume 1 op = 1 ns)")
    N = 1000
    print(f"Fix N = {N}, and pretend the machine does exactly 1 operation per")
    print("nanosecond (a 1 GHz core doing 1 useful op/cycle). How long does each\ncomplexity class take? The last two are not 'slow' - they outlast the\nuniverse.\n")
    print("| {:<12} | {:>22} | {}".format("complexity", "operations", "wall-clock (1 op = 1 ns)"))
    print("|" + "-" * 14 + "|" + "-" * 24 + "|" + "-" * 34)
    for c in COMPLEXITIES:
        ops = growth(c, N)
        print("| {:<12} | {:>22} | {}".format(c, fmt_big(ops), fmt_time_ns(ops)))
    print()
    print("Takeaways:")
    print("  * O(N^2) at N=1000 = 1 million ops = 1 ms.  Comfortable.")
    print("  * O(2^N) at N=1000 = 10^301 ops = ~10^274 ages of the universe.")
    print("  * O(N!)  at N=1000 = 10^2568 ops - a number with more digits than")
    print("    there are atoms in the observable universe (~10^80).")
    print("  => For N=1000, polynomial (any fixed power) is trivial; exponential")
    print("     is forever. The polynomial vs exponential gap is the most")
    print("     important cliff in all of computer science.")


# ----------------------------------------------------------------------------
# SECTION C: the Master Theorem
# ----------------------------------------------------------------------------

def section_master_theorem():
    banner("SECTION C: Master Theorem  T(N) = a*T(N/b) + f(N)")
    print("Every divide-and-conquer algorithm has the SAME shape of recurrence:")
    print()
    print("    T(N) = a * T(N / b) + f(N)")
    print("           a = # subproblems      (split into a pieces)")
    print("           b = shrink factor      (each piece is 1/b the size)")
    print("           f(N) = cost to DIVIDE + COMBINE (outside the recursion)")
    print()
    print("Let p = log_b(a) = log(a)/log(b). Compare f(N) against N^p:\n")
    print("| case | condition on f(N)        | result T(N)        | who wins?        |")
    print("|------|--------------------------|--------------------|------------------|")
    print("|  1   | f(N) = O(N^(p - eps))     | Theta(N^p)         | the LEAVES       |")
    print("|  2   | f(N) = Theta(N^p)         | Theta(N^p * log N) | BALANCED         |")
    print("|  3   | f(N) = Omega(N^(p + eps)) | Theta(f(N))        | the COMBINE step |")
    print()
    print("Worked examples (f(N) = Theta(N^c) for a clean power c):\n")
    print("| algorithm        | a | b | f(N)=N^c | p=log_b(a) | case | T(N)               |")
    print("|------------------|---|---|----------|------------|------|--------------------|")
    examples = [
        ("binary search",  1, 2, 0),   # f=1=N^0  -> log N
        ("merge sort",     2, 2, 1),   # f=N      -> N log N
        ("Karatsuba mult", 3, 2, 1),   # f=N      -> N^1.585
        ("Strassen matmul",7, 2, 2),   # f=N^2    -> N^2.807
        ("bad merge (N^2)",2, 2, 2),   # f=N^2    -> N^2
    ]
    for name, a, b, c in examples:
        case, p, res = master_theorem(a, b, c)
        pstr = f"{p:.3f}"
        print(f"| {name:<16} | {a} | {b} | N^{c:<7} | {pstr:<10} | {case:<4} | {res:<18} |")
    print()
    print("How to read it:")
    print("  * MERGE SORT (a=2,b=2): splits into 2 halves, does O(N) to merge.")
    print("    p=log_2(2)=1, f(N)=N=N^1 -> Case 2 (balanced) -> Theta(N log N).")
    print("  * BINARY SEARCH (a=1,b=2): does NOT branch into multiple subproblems")
    print("    (a=1, it keeps only ONE half), divide/combine is O(1). p=log_2(1)=0,")
    print("    f(N)=1=N^0 -> Case 2 -> Theta(N^0 * log N) = Theta(log N).")
    print("  * STRASSEN (a=7,b=2): 7 sub-multiplications of half size. p=log_2(7)")
    print("    = 2.807. f(N)=N^2 < N^2.807 -> Case 1 (leaves dominate) -> N^2.807.")
    print("    That 0.807 over the naive N^3 is Strassen's whole speedup.")


# ----------------------------------------------------------------------------
# SECTION D: practical crossover (insertion sort vs merge sort)
# ----------------------------------------------------------------------------

def section_crossover():
    banner("SECTION D: practical crossover - O(N^2) can beat O(N log N) at small N")
    print("Big-O hides CONSTANT FACTORS. Insertion sort is O(N^2) but its inner")
    print("loop is tiny (one compare + one shift, cache-friendly, no function")
    print("calls). Merge sort is O(N log N) but pays for recursion, temp-array")
    print("allocation, and copies every merge. So per-element it costs MORE.\n")
    print("We count EXACT comparisons (worst case = reverse-sorted input), then")
    print("weight merge comparisons by a constant factor C_MERGE > 1 to model the")
    print("extra per-step overhead. Insertion's per-step cost is C_INS = 1.\n")
    C_INS, C_MERGE = 1, 4                       # merge ~4x costlier per comparison
    print(f"Cost model: t_ins(N)   = {C_INS} * insertion_comps(N)")
    print(f"            t_merge(N) = {C_MERGE} * merge_comps(N)\n")
    print("| {:>3} | {:>16} | {:>14} | {:>12} | {:>12} | {}".format(
        "N", "insertion comps", "merge comps", "t_ins", "t_merge", "winner"))
    print("|" + "-" * 75)
    crossover = None
    for n in range(1, 61):
        worst = list(range(n, 0, -1))           # reverse sorted = worst case
        ic = insertion_sort_comps(worst)
        mc = merge_sort_comps(worst)
        t_ins = C_INS * ic
        t_merge = C_MERGE * mc
        winner = "insertion" if t_ins <= t_merge else "MERGE"
        if crossover is None and t_merge < t_ins:
            crossover = n
        if n <= 16 or n % 5 == 0 or (crossover and abs(n - crossover) <= 1):
            print("| {:>3} | {:>16,} | {:>14,} | {:>12,} | {:>12,} | {}".format(
                n, ic, mc, t_ins, t_merge, winner))
    print("| ... (rows where winner unchanged omitted) ...")
    print()
    if crossover:
        worst_c = list(range(crossover, 0, -1))
        ic = insertion_sort_comps(worst_c)
        mc = merge_sort_comps(worst_c)
        print(f"CROSSOVER POINT: N = {crossover}")
        print(f"  At N={crossover-1}: t_ins={C_INS*insertion_sort_comps(list(range(crossover-1,0,-1))):,} "
              f"vs t_merge={C_MERGE*merge_sort_comps(list(range(crossover-1,0,-1))):,} -> insertion wins")
        print(f"  At N={crossover}:   t_ins={C_INS*ic:,} vs t_merge={C_MERGE*mc:,} -> MERGE wins")
        print(f"  Below N={crossover}, the O(N^2) insertion sort is FASTER than the")
        print(f"  O(N log N) merge sort, because its constant factor is ~{C_MERGE}x smaller.")
        print(f"  This is why real sort libraries (e.g. Python's Timsort, C++'s")
        print(f"  introsort) switch to insertion sort for small subarrays.")
    print()
    print("Takeaway: Big-O is an ASYMPTOTIC statement. For small N the constant")
    print("factor wins. Always measure; only trust the complexity class once N is")
    print("comfortably past the crossover.")


# ----------------------------------------------------------------------------
# SECTION E: space complexity + GOLD CHECK
# ----------------------------------------------------------------------------

def section_space_and_gold():
    banner("SECTION E: space complexity - and the GOLD CHECK")
    print("Time is only half the story. Space complexity is how much EXTRA memory")
    print("an algorithm needs beyond the input:\n")
    print("| algorithm      | time (avg/worst) | space (auxiliary) | why?                      |")
    print("|----------------|------------------|-------------------|---------------------------|")
    print("| O(1) access    | O(1)             | O(1)              | one index lookup          |")
    print("| binary search  | O(log N)         | O(1)              | iterative: no extra store |")
    print("| insertion sort | O(N^2)           | O(1)              | sorts IN PLACE            |")
    print("| heap sort      | O(N log N)       | O(1)              | sorts in place            |")
    print("| merge sort     | O(N log N)       | O(N)              | needs a temp buffer/move  |")
    print("| quicksort      | O(N log N)*      | O(log N)          | recursion stack (*N^2 wst)|")
    print()
    print("Two flavors of 'space':")
    print("  * O(1) AUXILIARY  (in-place): insertion/heap sort. No array grows")
    print("    with N. Best when memory is tight (embedded, huge datasets).")
    print("  * O(N) AUXILIARY  (out-of-place): merge sort allocates a buffer as")
    print("    big as the input on every merge. Simpler to reason about, but 2x RAM.")
    print("  * O(log N): quicksort's recursion depth (balanced case).")
    print()
    print("RULE OF THUMB: you can usually trade space for time. An O(N) auxiliary")
    print("buffer (merge sort, hash tables) buys a better time complexity. The")
    print("best algorithms (e.g. heapsort) give O(1) space AND O(N log N) time.\n")

    # ----- GOLD CHECK: every value must reproduce from `growth()` -----
    print("-" * 72)
    print("GOLD CHECK - every value recomputed from growth(); nothing hand-typed.")
    print("-" * 72)
    checks = [
        ("growth('O(1)', 100)",          growth("O(1)", 100),          1),
        ("growth('O(log N)', 8)",        growth("O(log N)", 8),        3.0),
        ("growth('O(log N)', 1024)",     growth("O(log N)", 1024),     10.0),
        ("growth('O(N)', 1000)",         growth("O(N)", 1000),         1000),
        ("growth('O(N log N)', 16)",     growth("O(N log N)", 16),     16 * math.log2(16)),
        ("growth('O(N^2)', 100)",        growth("O(N^2)", 100),        10000),
        ("growth('O(2^N)', 10)",         growth("O(2^N)", 10),         1024),
        ("growth('O(2^N)', 20)",         growth("O(2^N)", 20),         1048576),
        ("growth('O(N!)', 5)",           growth("O(N!)", 5),           120),
        ("growth('O(N!)', 10)",          growth("O(N!)", 10),          3628800),
    ]
    all_ok = True
    for label, got, want in checks:
        ok = got == want
        all_ok &= ok
        print(f"  [{'OK' if ok else 'FAIL'}] {label:<32} = {fmt_big(got):>16}")
    # Master theorem checks
    mt_checks = [
        ("master(2,2,c=1) [merge sort]", master_theorem(2, 2, 1), ("Case 2", "Theta(N^1 log N)")),
        ("master(1,2,c=0) [bin search]", master_theorem(1, 2, 0), ("Case 2", "Theta(log N)")),
        ("master(7,2,c=2) [Strassen]",   master_theorem(7, 2, 2), ("Case 1", "Theta(N^2.8074)")),
        ("master(2,2,c=2) [bad merge]",  master_theorem(2, 2, 2), ("Case 3", "Theta(N^2)")),
    ]
    for label, got, want in mt_checks:
        ok = got[0] == want[0] and got[2] == want[1]
        all_ok &= ok
        print(f"  [{'OK' if ok else 'FAIL'}] {label:<32} = {got[0]} -> {got[2]}")
    print()
    print(f"GOLD CHECK: {'OK - all growth values and master cases reproduce' if all_ok else 'FAIL'}")
    print("(big_o_comparison.html re-runs growth() and master_theorem() in JS and")
    print(" re-checks these exact values.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("big_o_comparison.py - reference impl. All numbers below feed BIG_O_COMPARISON.md.")
    print("python", sys.version.split()[0])

    section_growth_table()
    section_time_to_run()
    section_master_theorem()
    section_crossover()
    section_space_and_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
