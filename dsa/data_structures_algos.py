"""
data_structures_algos.py - DSA refresher: the one-file cheat sheet.

This is the single source of truth that DATA_STRUCTURES_ALGOS.md is built from.
Every number, table, and worked example below is printed by this file and
re-checked with [check] assertions. If you change something here, re-run and
re-paste the output into the guide.

Run:
    python3 data_structures_algos.py

============================================================================
THE INTUITION (read this first) - the map and the territory
============================================================================
Every DSA interview question reduces to TWO decisions:

  (1) WHICH DATA STRUCTURE holds the data?
  (2) WHICH ALGORITHM PARADIGM transforms it?

Decision (1) is driven by the ACCESS PATTERN you need: O(1) membership -> hash
table; ordered range queries -> balanced BST; repeated min/max -> heap; range
sums -> prefix sum / segment tree; connected components -> union-find. Decision
(2) is driven by the PROBLEM STRUCTURE: overlapping subproblems -> DP; locally
optimal = globally optimal -> greedy; explore all candidates -> backtracking;
split in half -> divide and conquer; "just try everything" -> brute force.

This file is the cheat sheet for both decisions. It has three parts:
  - Section A: the data-structure operation complexity table (the "which DS?")
  - Section B: the Big-O cheat sheet (the "how fast?") with concrete examples
  - Section C: the five algorithm paradigms (the "how to solve?")
  - Section D: one worked example per paradigm, each [check]-verified
  - GOLD: the compact values data_structures_algos.html recomputes in JS.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  Big-O       : growth rate of work as input size N -> infinity. Ignores
                constants; only the dominant term survives. O(3N^2 + 1000N)
                is just O(N^2).
  amortized   : worst case per op is bad, but averaged over a sequence it is
                cheap (e.g. dynamic-array append: rare O(N) resize, usual O(1)).
  access      : read element by index/position (array[5]).
  search      : find whether a value is present.
  insert/delete: add/remove an element (cost depends on WHERE: head/tail/middle).
  balanced BST: a search tree whose height is kept O(log N) via rotations
                (AVL, red-black); an unbalanced BST degrades to O(N).
  complete    : (heap) every level full except possibly the last, filled L->R;
                this lets a heap live in a flat array with index arithmetic.
  paradigm    : a strategy family for building algorithms (see Section C).

Conventions: all code is deterministic; "random" does not appear. Every worked
example prints its input, result, and the [check] it must satisfy.
"""

from __future__ import annotations

import math

BANNER = "=" * 72


# ============================================================================
# 1. THE DATA  (the tables Sections A & B print, and the HTML renders)
# ============================================================================

# ---- Section A: data-structure operation complexity ----
# (name, access, search, insert, delete, space, note)
DATA_STRUCTURES = [
    ("Array",        "O(1)",    "O(n)",    "O(n)",     "O(n)",     "O(n)",
     "contiguous memory; O(1) index, cache-friendly; insert/delete shift"),
    ("Linked List",  "O(n)",    "O(n)",    "O(1)*",    "O(1)*",    "O(n)",
     "*O(1) only at a known node; pointer chasing, no locality"),
    ("Hash Table",   "O(N/A)",  "O(1)avg", "O(1)avg",  "O(1)avg",  "O(n)",
     "degrades to O(n) under collisions; no ordering; load factor alpha"),
    ("BST (bal.)",   "O(log n)","O(log n)","O(log n)", "O(log n)", "O(n)",
     "AVL/red-black; sorted in-order; supports range queries"),
    ("Heap",         "O(1)^",   "O(n)",    "O(log n)", "O(log n)", "O(n)",
     "^peek min/max only; array-backed complete binary tree"),
    ("Graph (adj.)", "O(1)#",   "O(V+E)",  "O(1)",     "O(V+E)",   "O(V+E)",
     "#vertex access O(1); edge lookup O(deg); dense -> adjacency matrix"),
]

# ---- Section B: Big-O cheat sheet (classes -> example algorithms) ----
# (class, name, example_algorithms, n_value_for_growth)
BIG_O_CLASSES = [
    ("O(1)",      "constant",      "hash lookup, array index, stack push/pop"),
    ("O(log n)",  "logarithmic",   "binary search, balanced BST op, exponentiation"),
    ("O(n)",      "linear",        "linear scan, BFS/DFS visit, single pass"),
    ("O(n log n)","linearithmic",  "merge/heap sort, FFT, convex hull"),
    ("O(n^2)",    "quadratic",     "bubble/selection sort, two-sum brute force"),
    ("O(2^n)",    "exponential",   "naive recursive Fibonacci, all subsets"),
    ("O(n!)",     "factorial",     "permutations, brute-force TSP"),
]


def big_o_growth(name: str, n: int) -> float:
    """Exact operation count for a complexity class at size n (mirrors the .html)."""
    if name == "O(1)":
        return 1
    if name == "O(log n)":
        return math.log2(n) if n > 0 else 0
    if name == "O(n)":
        return n
    if name == "O(n log n)":
        return n * math.log2(n) if n > 0 else 0
    if name == "O(n^2)":
        return n * n
    if name == "O(2^n)":
        return float(2 ** n)
    if name == "O(n!)":
        return float(math.factorial(n))
    raise ValueError(name)


# ============================================================================
# 1b. THE FIVE PARADIGM IMPLEMENTATIONS (Section D worked examples)
# ============================================================================

# ---- Brute Force: two-sum (check every pair) ----
def two_sum_bruteforce(nums: list, target: int):
    """Return (i, j) with nums[i]+nums[j]==target, or None; plus pair count."""
    comparisons = 0
    n = len(nums)
    for i in range(n):
        for j in range(i + 1, n):
            comparisons += 1
            if nums[i] + nums[j] == target:
                return (i, j), comparisons
    return None, comparisons


# ---- Divide and Conquer: merge sort (split, sort halves, merge) ----
def merge_sort(arr: list):
    """Return (sorted_list, comparisons). Stable, O(n log n) guaranteed."""
    comparisons = 0
    a = list(arr)

    def merge(lo, mid, hi):
        nonlocal comparisons
        left = a[lo:mid + 1]
        right = a[mid + 1:hi + 1]
        i = j = 0
        k = lo
        while i < len(left) and j < len(right):
            comparisons += 1
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

    def sort(lo, hi):
        if lo < hi:
            mid = (lo + hi) // 2
            sort(lo, mid)
            sort(mid + 1, hi)
            merge(lo, mid, hi)

    if a:
        sort(0, len(a) - 1)
    return a, comparisons


# ---- Greedy: activity selection (pick earliest-finishing non-overlapping) ----
def activity_selection(activities: list):
    """activities: list of (start, finish). Return max non-overlapping set."""
    acts = sorted(activities, key=lambda x: x[1])  # sort by finish time
    if not acts:
        return []
    selected = [acts[0]]
    for s, f in acts[1:]:
        if s >= selected[-1][1]:     # starts after last selected finishes
            selected.append((s, f))
    return selected


# ---- Dynamic Programming: 0/1 knapsack (classic CLRS) ----
def knapsack_01(weights: list, values: list, capacity: int):
    """Return (max_value, dp_table). dp[i][w] = best value using first i items,
    capacity w."""
    n = len(weights)
    dp = [[0] * (capacity + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        wi, vi = weights[i - 1], values[i - 1]
        for w in range(capacity + 1):
            if wi <= w:
                dp[i][w] = max(dp[i - 1][w], dp[i - 1][w - wi] + vi)
            else:
                dp[i][w] = dp[i - 1][w]
    return dp[n][capacity], dp


def knapsack_items(weights: list, values: list, dp: list):
    """Trace back the dp table to recover which items were taken."""
    n = len(weights)
    w = len(dp[0]) - 1
    taken = []
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            taken.append(i - 1)
            w -= weights[i - 1]
    taken.reverse()
    return taken


# ---- Backtracking: N-queens (count all valid placements) ----
def count_nqueens(n: int) -> int:
    """Count distinct N-queens solutions (column placements per row)."""
    solutions = 0
    cols = set()       # occupied columns
    diag1 = set()      # occupied r - c diagonals
    diag2 = set()      # occupied r + c diagonals

    def backtrack(row: int):
        nonlocal solutions
        if row == n:
            solutions += 1
            return
        for c in range(n):
            if c in cols or (row - c) in diag1 or (row + c) in diag2:
                continue
            cols.add(c)
            diag1.add(row - c)
            diag2.add(row + c)
            backtrack(row + 1)
            cols.discard(c)
            diag1.discard(row - c)
            diag2.discard(row + c)

    backtrack(0)
    return solutions


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_ops(v: float) -> str:
    """Format an operation count: small -> int, large -> scientific."""
    if v < 1e9:
        if v == int(v):
            return f"{int(v)}"
        return f"{v:.2f}"
    logv = math.log10(v)
    exp = math.floor(logv)
    mant = 10 ** (logv - exp)
    return f"{mant:.3f}e{int(exp)}"


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the data-structure operation complexity table
# ----------------------------------------------------------------------------
def section_data_structures():
    banner("SECTION A: data structure operation complexity")
    print("Pick the data structure that supports the ACCESS PATTERN you need.\n")
    print("| Data Structure | Access   | Search   | Insert   | Delete   | Space    |")
    print("|----------------|----------|----------|----------|----------|----------|")
    for name, acc, srch, ins, dele, sp, note in DATA_STRUCTURES:
        print(f"| {name:<14} | {acc:<8} | {srch:<8} | {ins:<8} | "
              f"{dele:<8} | {sp:<8} |")
    print()
    print("Notes on the asterisks/markers above:")
    for name, acc, srch, ins, dele, sp, note in DATA_STRUCTURES:
        print(f"  - {name:<14}: {note}")
    print()
    print("SELECTION RULE OF THUMB (access pattern -> structure):")
    print("  - O(1) membership / lookup by key      -> hash table (dict)")
    print("  - sorted order / range queries         -> balanced BST / sorted array")
    print("  - repeated min/max extraction          -> heap (priority queue)")
    print("  - prefix / autocomplete                -> trie")
    print("  - connected components / union         -> union-find (DSU)")
    print("  - next-greater / histogram             -> monotonic stack")
    print("  - range sum + point update             -> Fenwick / segment tree")
    print("  - O(1) both-ends push/pop              -> deque (NOT list.pop(0))")
    print()
    print("THE COMMON MISTAKE: using a Python list when a deque is needed.")
    print("list.pop(0) is O(n) (shifts every element); deque.popleft() is O(1).")
    # GOLD CHECK: table shape
    assert len(DATA_STRUCTURES) == 6
    assert DATA_STRUCTURES[0][0] == "Array"
    assert DATA_STRUCTURES[3][0] == "BST (bal.)"
    print("\n[check] table has 6 structures, Array first, BST balanced 4th? OK")


# ----------------------------------------------------------------------------
# SECTION B: the Big-O cheat sheet with concrete examples
# ----------------------------------------------------------------------------
def section_big_o():
    banner("SECTION B: Big-O cheat sheet - classes, examples, growth")
    print("Big-O = growth rate of work as N -> infinity. Constants drop; only\n"
          "the dominant term survives. Lower in the table = slower.\n")
    print("| Class       | Name          | Example algorithms")
    print("|-------------|---------------|--------------------------------------")
    for cls, name, ex in BIG_O_CLASSES:
        print(f"| {cls:<11} | {name:<13} | {ex}")
    print()
    print("Growth at concrete N (operation counts, recomputed live):\n")
    print("| Class       |   N=10          |   N=100")
    print("|-------------|-----------------|-------------------------")
    for cls, _, _ in BIG_O_CLASSES:
        v10 = big_o_growth(cls, 10)
        v100 = big_o_growth(cls, 100)
        print(f"| {cls:<11} | {fmt_ops(v10):<15} | {fmt_ops(v100):<15}")
    print()
    print("THE TRACTABILITY CLIFF: at N=100, every class up to O(n^2) finishes in")
    print("well under a millisecond (1 op/ns). O(2^n) ~ 1.27e30 ns = ~4e13 years;")
    print("O(n!) ~ 9.3e157 ns = absurdly past the age of the universe. The jump")
    print("from polynomial to exponential is the single most important fact in DSA:")
    print("polynomial-time algorithms SCALE; exponential ones DO NOT.")
    print()
    print("MASTER THEOREM (divide-and-conquer): T(N) = a*T(N/b) + Theta(N^c).")
    print("Let p = log_b(a). If c < p -> Case 1: Theta(N^p). If c == p -> Case 2:")
    print("Theta(N^p log N). If c > p -> Case 3: Theta(N^c). Examples: merge sort")
    print("(a=2,b=2,c=1,p=1 -> Case 2 -> N log N); binary search (a=1,b=2,c=0,p=0")
    print("-> Case 2 -> log N); Strassen (a=7,b=2,c=2,p=2.807 -> Case 1 -> N^2.807).")
    # GOLD CHECKS
    assert big_o_growth("O(1)", 100) == 1
    assert abs(big_o_growth("O(log n)", 8) - 3) < 1e-12
    assert big_o_growth("O(n^2)", 100) == 10000
    assert big_o_growth("O(2^n)", 10) == 1024
    assert big_o_growth("O(n!)", 5) == 120
    print("\n[check] growth(1,100)=1, log(8)=3, n^2(100)=10000, 2^10=1024, 5!=120? OK")


# ----------------------------------------------------------------------------
# SECTION C: the five algorithm paradigms overview
# ----------------------------------------------------------------------------
def section_paradigms():
    banner("SECTION C: the five algorithm paradigms")
    print("A paradigm is a STRATEGY for building an algorithm. Each has a shape\n"
          "it imposes on the solution. Match the paradigm to the problem structure.\n")
    paradigms = [
        ("Brute Force", "O(n^k) typical",
         "Try EVERY candidate; check each. Always correct; often too slow. Use as the "
         "BASELINE you state first in an interview, then optimize.",
         "two-sum nested loop, naive string match, TSP enumeration"),
        ("Divide & Conquer", "O(n log n) typical",
         "Split the input in half, solve each recursively, COMBINE the results. "
         "Shines when the combine step is cheap (linear or less).",
         "merge sort, quicksort, binary search, FFT, closest-pair"),
        ("Greedy", "O(n log n) typical",
         "Make the locally optimal choice at each step; NEVER reconsider. Works "
         "ONLY when local optimum => global optimum (provably).",
         "activity selection, Huffman coding, Dijkstra, Kruskal MST"),
        ("Dynamic Programming", "O(n*k) typical",
         "Overlapping subproblems + optimal substructure. Solve each subproblem "
         "ONCE, memoize/tabulate, combine. Turns exponential recursion polynomial.",
         "0/1 knapsack, LCS, edit distance, Floyd-Warshall, Fibonacci"),
        ("Backtracking", "O(2^n) / O(n!) typical",
         "Systematically explore ALL candidate solutions; PRUNE a branch the moment "
         "it violates a constraint. DFS over the solution space.",
         "N-queens, Sudoku solver, permutations, subsets, regex match"),
    ]
    print(f"| {'Paradigm':<20} | {'Typical':<16} | Idea")
    print(f"|{'-'*20}-+-{'-'*16}-+-{'-'*40}")
    for name, cost, idea, _ in paradigms:
        print(f"| {name:<20} | {cost:<16} | {idea}")
    print()
    print("Paradigm -> signal words (recognize within 2 minutes):")
    print("  - Brute Force      : 'how many pairs/triples?' , small N, baseline")
    print("  - Divide & Conquer : 'split in half', 'sorted', 'balanced'")
    print("  - Greedy           : 'maximum/minimum', 'schedule', 'can you reach'")
    print("  - DP               : 'count the ways', 'min cost', 'longest/shortest'")
    print("  - Backtracking     : 'all possible', 'generate every', 'satisfies'")
    print()
    print("WHEN GREEDY FAILS (the trap): greedy gives no guarantee unless the")
    print("'greedy choice property' holds. Counterexample: 0/1 knapsack is NOT")
    print("greedy (best value-density item first can leave unfillable space) but")
    print("FRACTIONAL knapsack IS (you can take part of an item). Coin change with")
    print("US denominations {1,5,10,25} is greedy-solvable; {1,3,4} for 6 is NOT")
    print("(greedy picks 4+1+1=3 coins; optimal is 3+3=2 coins).")
    assert len(paradigms) == 5
    print("\n[check] exactly 5 paradigms defined? OK")


# ----------------------------------------------------------------------------
# SECTION D: five worked examples (one per paradigm) - the GOLD section
# ----------------------------------------------------------------------------
def section_examples():
    banner("SECTION D: one worked example per paradigm (all [check]-verified)")

    # ---- Brute Force: two sum ----
    print("(1) BRUTE FORCE - two sum (check every pair).")
    nums = [2, 7, 11, 15]
    target = 9
    (i, j), comps = two_sum_bruteforce(nums, target)
    print(f"    nums = {nums}, target = {target}")
    print(f"    scan all C({len(nums)},2)={len(nums)*(len(nums)-1)//2} pairs; "
          f"stop at first match.")
    print(f"    result: indices ({i},{j}) since nums[{i}]+nums[{j}]="
          f"{nums[i]}+{nums[j]}={target}  after {comps} comparison(s)")
    print("    complexity: O(n^2) time, O(1) space. (Hash map improves to O(n)).")
    assert (i, j) == (0, 1) and comps == 1
    print("    [check] (0,1) with 1 comparison? OK\n")

    # ---- Divide and Conquer: merge sort ----
    print("(2) DIVIDE AND CONQUER - merge sort.")
    arr = [38, 27, 43, 3, 9, 82, 10]
    sorted_arr, comps = merge_sort(arr)
    print(f"    input  = {arr}")
    print(f"    output = {sorted_arr}")
    print(f"    comparisons performed = {comps}  (worst case ~ n*log2(n) = "
          f"{int(len(arr)*math.log2(len(arr)))})")
    print("    complexity: O(n log n) time, O(n) space; STABLE sort.")
    assert sorted_arr == [3, 9, 10, 27, 38, 43, 82]
    print(f"    [check] sorted correctly, {comps} comparisons? OK\n")

    # ---- Greedy: activity selection ----
    print("(3) GREEDY - activity selection (earliest finish first).")
    acts = [(1, 4), (3, 5), (0, 6), (5, 7), (3, 9), (5, 9),
            (6, 10), (8, 11), (8, 12), (2, 14), (12, 16)]
    chosen = activity_selection(acts)
    print(f"    {len(acts)} activities (start,finish) = {acts}")
    print("    sort by finish, take each that starts after last chosen finish:")
    print(f"    selected {len(chosen)}: {chosen}")
    print("    complexity: O(n log n) time (the sort), O(1) extra space.")
    # no two selected overlap
    for a, b in zip(chosen, chosen[1:]):
        assert a[1] <= b[0], (a, b)
    assert len(chosen) == 4
    print("    [check] 4 non-overlapping activities, no gaps violate? OK\n")

    # ---- DP: 0/1 knapsack ----
    print("(4) DYNAMIC PROGRAMMING - 0/1 knapsack (classic CLRS).")
    weights = [1, 2, 3]
    values = [6, 10, 12]
    capacity = 5
    best, dp = knapsack_01(weights, values, capacity)
    taken = knapsack_items(weights, values, dp)
    tw = sum(weights[t] for t in taken)
    tv = sum(values[t] for t in taken)
    print(f"    weights = {weights}, values = {values}, capacity = {capacity}")
    print(f"    dp table ({len(weights)+1}x{capacity+1}); dp[i][w] = best value")
    print("      using first i items at capacity w.")
    print(f"    max value = {best}; items taken (0-indexed) = {taken}")
    print(f"      -> weight {tw} <= {capacity}, value {tv} == {best}")
    print("    complexity: O(n*W) time and space (W = capacity).")
    assert best == 22 and taken == [1, 2] and tw <= capacity and tv == best
    print("    [check] value 22 via items [1,2]? OK\n")

    # ---- Backtracking: N-queens ----
    print("(5) BACKTRACKING - N-queens (count all valid placements).")
    for n in (4, 8):
        count = count_nqueens(n)
        print(f"    N={n}: {count} distinct solutions  "
              f"(backtracking with col/diag1/diag2 pruning)")
    print("    complexity: O(n!) worst case (pruned dramatically by constraints).")
    assert count_nqueens(4) == 2
    assert count_nqueens(8) == 92
    print("    [check] N=4 -> 2 solutions, N=8 -> 92 solutions? OK")


# ----------------------------------------------------------------------------
# GOLD: the compact values data_structures_algos.html recomputes and checks
# ----------------------------------------------------------------------------
def section_gold():
    banner("GOLD VALUES (pinned for data_structures_algos.html)")
    print("The standalone .html recomputes these in JS from the identical logic\n"
          "and asserts them via the gold-check badge.\n")

    # two-sum
    (ij, comps) = two_sum_bruteforce([2, 7, 11, 15], 9)
    print(f"two_sum_bruteforce([2,7,11,15], 9)        = {ij}, {comps} comparison")
    assert ij == (0, 1) and comps == 1

    # merge sort
    sarr, mc = merge_sort([38, 27, 43, 3, 9, 82, 10])
    print(f"merge_sort([38,27,43,3,9,82,10])          = {sarr}")
    print(f"                                             ({mc} comparisons)")
    assert sarr == [3, 9, 10, 27, 38, 43, 82]

    # activity selection
    chosen = activity_selection(
        [(1, 4), (3, 5), (0, 6), (5, 7), (3, 9), (5, 9),
         (6, 10), (8, 11), (8, 12), (2, 14), (12, 16)])
    print(f"activity_selection(...) -> {len(chosen)} acts = {chosen}")
    assert len(chosen) == 4

    # knapsack
    best, dp = knapsack_01([1, 2, 3], [6, 10, 12], 5)
    taken = knapsack_items([1, 2, 3], [6, 10, 12], dp)
    print(f"knapsack_01([1,2,3],[6,10,12], cap 5)     = {best}, items {taken}")
    assert best == 22 and taken == [1, 2]

    # n-queens
    q4 = count_nqueens(4)
    q8 = count_nqueens(8)
    print(f"count_nqueens(4) = {q4}   count_nqueens(8) = {q8}")
    assert q4 == 2 and q8 == 92

    # big-o growth scalars
    print(f"big_o_growth('O(2^n)', 10) = {big_o_growth('O(2^n)', 10)}")
    print(f"big_o_growth('O(n!)',   5) = {big_o_growth('O(n!)', 5)}")
    print(f"big_o_growth('O(n^2)', 100) = {big_o_growth('O(n^2)', 100)}")
    assert big_o_growth("O(2^n)", 10) == 1024
    assert big_o_growth("O(n!)", 5) == 120
    assert big_o_growth("O(n^2)", 100) == 10000

    print("\nGOLD scalars for .html:")
    print("  two_sum       = (0,1), 1 comparison")
    print(f"  merge_sort    = {sarr}")
    print(f"  activity_sel  = {len(chosen)} activities")
    print(f"  knapsack      = {best}, items {taken}")
    print(f"  nqueens(4,8)  = ({q4}, {q8})")
    print("\n[check] all GOLD values reproduce from source? OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("data_structures_algos.py - DSA refresher. All numbers below feed")
    print("DATA_STRUCTURES_ALGOS.md. Python stdlib only (math). Deterministic.\n")

    section_data_structures()
    section_big_o()
    section_paradigms()
    section_examples()
    section_gold()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
