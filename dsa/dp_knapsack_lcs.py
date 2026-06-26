"""
dp_knapsack_lcs.py - Reference implementation of Dynamic Programming via two
canonical problems: 0/1 Knapsack and Longest Common Subsequence (LCS).

This is the single source of truth that DP_KNAPSACK_LCS.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 dp_knapsack_lcs.py

=========================================================================
THE INTUITION (read this first) - "stop recomputing the same subproblem"
=========================================================================
Dynamic programming is the cure for a specific disease: a recursive solution
that solves the SAME small subproblems over and over. Two symptoms must be
present (CLRS §15.3); if both are, DP turns exponential time into polynomial:

  * OPTIMAL SUBSTRUCTURE : the optimal answer to the WHOLE problem is built
                           from optimal answers to smaller pieces. (Knapsack:
                           "best value using first i items" depends only on
                           "best value using first i-1 items".)
  * OVERLAPPING SUBPROBLEMS: the same subproblem is reached by many paths. A
                           naive recursion re-solves each; DP solves each ONCE
                           and reuses the answer.

  * bottom-up (tabulation) : solve subproblems smallest-first, fill a TABLE.
                             Iterative, no recursion overhead. This file's
                             default path.
  * top-down (memoization) : recurse naturally, but CACHE each result so no
                             subproblem is solved twice. Same answers, lazier
                             order.

THE REASON DP EXISTS: naive knapsack recursion is O(2^n) (each item: take or
skip -> binary tree of depth n). Naive LCS is O(2^(m+n)). With memoization the
distinct subproblems shrink to O(n*W) for knapsack and O(m*n) for LCS. The
speedup is the difference between "finish next century" and "finish instantly".

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  n            : number of items (knapsack), here 4.
  W            : knapsack weight capacity, here 5.
  wt[i], val[i]: weight and value of item i (0-indexed).
  dp[i][w]     : KNAPSACK cell = max value using the first i items with a
                 capacity limit of w. i in 0..n, w in 0..W.
  backtrack    : re-walk a finished dp table from dp[n][W] to recover WHICH
                 items were taken (not just the max value).
  m, n         : lengths of the two LCS strings X and Y.
  dp[i][j]     : LCS cell = length of the LCS of X[0..i-1] and Y[0..j-1].
  match cell   : an LCS dp[i][j] where X[i-1]==Y[j-1]; the recurrence adds 1
                 and jumps diagonally (dp[i-1][j-1]+1).
  space opt.   : knapsack only needs the PREVIOUS row -> O(W); LCS only needs
                 two adjacent rows -> O(min(m,n)). Trade: lose backtracking.
  brute force  : enumerate all subsets (knapsack) / all subsequences (LCS) and
                 take the best. O(2^n). Used here ONLY as a gold reference.

=========================================================================
THE LINEAGE (references)
=========================================================================
  Bellman 1952  ("On the Theory of Dynamic Programming", Bull. AMS) : coined
                  "dynamic programming", introduced the knapsack recurrence.
  Bellman 1957  (Dynamic Programming, Princeton) : the canonical text; LCS
                  appears in the edit-distance family.
  Hunt-McIlroy  1975 : the diff algorithm is LCS on lines of text.
  CLRS §15      : optimal substructure + overlapping subproblems (the two
                  requirements). Knapsack (§16.2 0-1) and LCS (§15.4).
  Sedgewick &   Wayne §9.6 : bottom-up DP on the two worked examples here.

KEY FORMULAS (all verified against CLRS + asserted in code):
    KNAPSACK (0/1), 1-indexed items:
        dp[i][w] = dp[i-1][w]                                if wt[i] > w
        dp[i][w] = max(dp[i-1][w],                           otherwise
                       dp[i-1][w - wt[i]] + val[i])
        base     : dp[0][w] = 0 ;  dp[i][0] = 0
        answer   : dp[n][W]
    LCS:
        dp[i][j] = dp[i-1][j-1] + 1                          if X[i]==Y[j]
        dp[i][j] = max(dp[i-1][j], dp[i][j-1])               otherwise
        base     : dp[0][j] = dp[i][0] = 0
        answer   : dp[m][n]
    COMPLEXITY:
        knapsack : O(n*W) time, O(n*W) space (O(W) space-optimized)
        LCS      : O(m*n) time, O(m*n) space (O(min(m,n)) optimized)
    THE TWO REQUIREMENTS (must hold for DP to apply):
        1. optimal substructure, 2. overlapping subproblems.

Conventions:
    Items are 0-indexed in the input arrays; the dp table is 1-indexed in its
    ITEM axis (row i = "first i items"), so item i sits at table row i+1.
    Strings are 1-indexed in the dp table: X[i] means the i-th char.
"""

from __future__ import annotations

from itertools import combinations

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# The two worked instances. Small enough to print every cell, big enough to
# show branching, backtracking, and a real optimum.
# ---------------------------------------------------------------------------
WT = [2, 3, 4, 5]
VAL = [3, 4, 5, 6]
W = 5
X_STR = "ABCDGH"
Y_STR = "AEDFHR"


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (this is the code DP_KNAPSACK_LCS.md walks through)
# ============================================================================

def knapsack_2d(wt: list[int], val: list[int], cap: int) -> list[list[int]]:
    """0/1 Knapsack, bottom-up, full (n+1)x(W+1) table.

    dp[i][w] = best value using the FIRST i items with capacity w.
    Returns the whole table so callers can print / backtrack it.
    """
    n = len(wt)
    dp = [[0] * (cap + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for w in range(cap + 1):
            if wt[i - 1] <= w:
                dp[i][w] = max(dp[i - 1][w],
                               dp[i - 1][w - wt[i - 1]] + val[i - 1])
            else:
                dp[i][w] = dp[i - 1][w]
    return dp


def knapsack_backtrack(dp, wt: list[int], val: list[int], cap: int) -> list[int]:
    """Recover the chosen item indices from a finished knapsack dp table.

    Walk from (n, W) backwards: if dp[i][w] != dp[i-1][w], item i-1 was taken.
    """
    n = len(wt)
    w = cap
    taken = []
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:         # item i-1 contributed
            taken.append(i - 1)
            w -= wt[i - 1]
    taken.reverse()
    return taken


def knapsack_1d(wt: list[int], val: list[int], cap: int) -> list[int]:
    """Space-optimized knapsack: a single row of size W+1, scanned RIGHT to
    LEFT so each item is used at most once. Returns the final row.

    WHY reverse: dp[w] on iteration i needs dp[i-1][w-wt[i]] (the PREVIOUS row
    to the left). Scanning w left->right would overwrite that cell before the
    larger w reads it -> the item could be taken twice. Right->left reads only
    cells still holding previous-row values.
    """
    dp = [0] * (cap + 1)
    for i in range(len(wt)):
        for w in range(cap, wt[i] - 1, -1):
            dp[w] = max(dp[w], dp[w - wt[i]] + val[i])
    return dp


def knapsack_memo(wt: list[int], val: list[int], cap: int) -> int:
    """Top-down memoized knapsack. Recursion + a cache keyed on (i, w).
    `@lru_cache` would do this for free; an explicit dict keeps the memo
    visible and dependency-free.
    """
    n = len(wt)
    memo: dict[tuple[int, int], int] = {}

    def solve(i: int, w: int) -> int:
        if i == 0 or w == 0:
            return 0
        key = (i, w)
        if key in memo:
            return memo[key]
        if wt[i - 1] > w:
            res = solve(i - 1, w)
        else:
            res = max(solve(i - 1, w),
                      solve(i - 1, w - wt[i - 1]) + val[i - 1])
        memo[key] = res
        return res

    ans = solve(n, cap)
    return ans


def lcs_2d(x: str, y: str) -> list[list[int]]:
    """LCS, bottom-up, full (m+1)x(n+1) table. dp[i][j] = LCS length of
    x[0..i-1] and y[0..j-1]."""
    m, n = len(x), len(y)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if x[i - 1] == y[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp


def lcs_backtrack(dp, x: str, y: str) -> str:
    """Recover one LCS string from a finished LCS dp table. Walk from (m,n):
    on a match take the char and go diagonal; else step toward the larger
    neighbor (ties go up, matching the .md)."""
    i, j = len(x), len(y)
    chars = []
    while i > 0 and j > 0:
        if x[i - 1] == y[j - 1]:
            chars.append(x[i - 1])
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    chars.reverse()
    return "".join(chars)


def lcs_1d(x: str, y: str) -> list[int]:
    """Space-optimized LCS: two rows (prev, cur) over the shorter string's
    length. Keep the SHORTER axis as columns -> O(min(m,n)). Returns cur row."""
    # make y the shorter one so the row length = min(m,n)
    if len(x) < len(y):
        x, y = y, x
    prev = [0] * (len(y) + 1)
    for i in range(1, len(x) + 1):
        cur = [0] * (len(y) + 1)
        for j in range(1, len(y) + 1):
            if x[i - 1] == y[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = max(prev[j], cur[j - 1])
        prev = cur
    return prev


def lcs_memo(x: str, y: str) -> int:
    """Top-down memoized LCS. Same answers as the table, lazier evaluation."""
    m, n = len(x), len(y)
    memo: dict[tuple[int, int], int] = {}

    def solve(i: int, j: int) -> int:
        if i == 0 or j == 0:
            return 0
        key = (i, j)
        if key in memo:
            return memo[key]
        if x[i - 1] == y[j - 1]:
            res = solve(i - 1, j - 1) + 1
        else:
            res = max(solve(i - 1, j), solve(i, j - 1))
        memo[key] = res
        return res

    return solve(m, n)


# ============================================================================
# 2. BRUTE-FORCE GOLD REFERENCES (exponential, only for verification)
# ============================================================================

def knapsack_brute(wt, val, cap) -> tuple[int, tuple[int, ...]]:
    """Enumerate every subset of items; return (best_value, best_subset)."""
    n = len(wt)
    best_v, best_set = 0, ()
    for r in range(n + 1):
        for combo in combinations(range(n), r):
            tot_w = sum(wt[i] for i in combo)
            tot_v = sum(val[i] for i in combo)
            if tot_w <= cap and tot_v > best_v:
                best_v, best_set = tot_v, combo
    return best_v, best_set


def lcs_brute(x: str, y: str) -> int:
    """Enumerate every subsequence of the shorter string; test membership in
    the other. Exponential - only usable for tiny inputs (fine here)."""
    from itertools import combinations
    s, t = (x, y) if len(x) <= len(y) else (y, x)        # s = shorter
    best = 0
    n = len(s)
    for r in range(n, -1, -1):                            # longest first
        found = False
        for combo in combinations(range(n), r):
            sub = "".join(s[i] for i in combo)
            # is `sub` a subsequence of t?
            it = iter(t)
            if all(c in it for c in sub):
                best = r
                found = True
                break
        if found:
            break
    return best


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_matrix(dp, row_labels, col_labels, cell_w=5):
    """Print a 2-D dp table with row/col headers (used by both problems)."""
    header = " " * (cell_w + 1) + "".join(f"{c:>{cell_w}}" for c in col_labels)
    print(header)
    for r, lab in enumerate(row_labels):
        line = f"{str(lab):>{cell_w}} " + "".join(f"{v:>{cell_w}}" for v in dp[r])
        print(line)


# ----------------------------------------------------------------------------
# SECTION A: 0/1 KNAPSACK - build the table, backtrack, gold-check vs brute
# ----------------------------------------------------------------------------

def section_knapsack():
    banner(f"SECTION A: 0/1 Knapsack  wt={WT}, val={VAL}, W={W}")
    n = len(WT)
    print("Items (0-indexed): " +
          ", ".join(f"#{i} (wt={WT[i]}, val={VAL[i]})" for i in range(n)))
    print(f"Capacity W = {W}\n")
    print("Recurrence (CLRS 0-1 knapsack):")
    print("  dp[i][w] = dp[i-1][w]                                  if wt[i] > w")
    print("  dp[i][w] = max(dp[i-1][w], dp[i-1][w-wt[i]] + val[i]) otherwise")
    print("Row i = 'first i items'; row 0 = no items (all zero).\n")

    dp = knapsack_2d(WT, VAL, W)
    col_labels = ["w=" + str(w) for w in range(W + 1)]
    row_labels = ["i=0"] + [f"i={i}(#{i-1})" for i in range(1, n + 1)]
    print("Full dp table (cell = best value for first i items, capacity w):")
    print_matrix(dp, row_labels, col_labels, cell_w=7)
    print(f"\n  dp[n][W] = dp[{n}][{W}] = {dp[n][W]}   <- OPTIMAL VALUE\n")

    # brute force gold
    bf_val, bf_set = knapsack_brute(WT, VAL, W)
    print(f"Brute force (all 2^{n}={1 << n} subsets): best value = {bf_val}, "
          f"items = {bf_set}")
    print(f"[check] dp[n][W] == brute-force value?  {dp[n][W] == bf_val}  "
          f"({dp[n][W]} == {bf_val})")

    # backtrack
    taken = knapsack_backtrack(dp, WT, VAL, W)
    tot_w = sum(WT[i] for i in taken)
    tot_v = sum(VAL[i] for i in taken)
    print(f"\nBacktrack from dp[{n}][{W}] to recover WHICH items: {taken}")
    print(f"  items taken = {taken}  -> total wt = {tot_w}, total val = {tot_v}")
    print("  (a cell changed between row i-1 and row i => item i-1 was taken)")
    assert tot_v == dp[n][W] == bf_val
    assert tot_w <= W
    print(f"\n[check] backtracked value {tot_v} == dp[{n}][{W}] == brute:  OK")
    print(f"\nGOLD: knapsack({WT}, {VAL}, W={W}) = {dp[n][W]}, items taken = {taken}")
    return dp[n][W], taken


# ----------------------------------------------------------------------------
# SECTION B: LCS - build the table, backtrack to "ADH", gold-check
# ----------------------------------------------------------------------------

def section_lcs():
    banner(f'SECTION B: LCS  X="{X_STR}", Y="{Y_STR}"')
    m, n = len(X_STR), len(Y_STR)
    print("Recurrence (CLRS LCS):")
    print("  dp[i][j] = dp[i-1][j-1] + 1            if X[i] == Y[j]   (match)")
    print("  dp[i][j] = max(dp[i-1][j], dp[i][j-1]) otherwise          (mismatch)")
    print("dp[i][j] = LCS length of X[0..i-1] and Y[0..j-1].\n")

    dp = lcs_2d(X_STR, Y_STR)
    col_labels = ["j=0 ε"] + [f"j={j} {Y_STR[j-1]}" for j in range(1, n + 1)]
    row_labels = ["i=0 ε"] + [f"i={i} {X_STR[i-1]}" for i in range(1, m + 1)]
    print("Full dp table (match cells are where the LCS grows diagonally):")
    print_matrix(dp, row_labels, col_labels, cell_w=7)
    print(f"\n  dp[m][n] = dp[{m}][{n}] = {dp[m][n]}   <- LCS LENGTH\n")

    bf_len = lcs_brute(X_STR, Y_STR)
    print(f"Brute force (all subsequences of the shorter string): best length = {bf_len}")
    print(f"[check] dp[m][n] == brute-force length?  {dp[m][n] == bf_len}  "
          f"({dp[m][n]} == {bf_len})")

    sub = lcs_backtrack(dp, X_STR, Y_STR)
    print(f"\nBacktrack from dp[{m}][{n}]: on a match go diagonal + take the char;")
    print(f"  else step toward the larger neighbor. Recovered LCS = \"{sub}\"")
    # verify the recovered string really is a common subsequence
    def is_subseq(s, t):
        it = iter(t)
        return all(c in it for c in s)
    assert is_subseq(sub, X_STR) and is_subseq(sub, Y_STR)
    assert len(sub) == dp[m][n] == bf_len
    print(f"[check] \"{sub}\" is a subsequence of both X and Y, length {len(sub)}:  OK")
    print(f'\nGOLD: LCS("{X_STR}", "{Y_STR}") = "{sub}", length = {dp[m][n]}')
    return dp[m][n], sub


# ----------------------------------------------------------------------------
# SECTION C: SPACE OPTIMIZATION - O(W) and O(min(m,n))
# ----------------------------------------------------------------------------

def section_space():
    banner("SECTION C: space optimization  O(W) knapsack, O(min(m,n)) LCS")
    print("The recurrence for EACH row only reads the PREVIOUS row. So we never")
    print("need the whole table - just two rows (or even one, with care).\n")

    # knapsack 1-D
    row = knapsack_1d(WT, VAL, W)
    full = knapsack_2d(WT, VAL, W)
    print(f"Knapsack O(W): one array of size W+1 = {W+1}, scanned right-to-left.")
    print(f"  final row dp[w] = {row}")
    print(f"  dp[W] = {row[W]}  (vs full table dp[n][W] = {full[len(WT)][W]})")
    assert row[W] == full[len(WT)][W]
    print(f"[check] O(W) result {row[W]} == 2-D result {full[len(WT)][W]}:  OK")
    print("  Why reverse scan: reading dp[w-wt[i]] must get the PREVIOUS row's")
    print("  value. Left->right would overwrite it and let an item be taken twice.\n")

    # LCS 2-row
    cur = lcs_1d(X_STR, Y_STR)
    full_lcs = lcs_2d(X_STR, Y_STR)
    print(f'LCS O(min(m,n)): two rows over the shorter string. X="{X_STR}" '
          f'(len {len(X_STR)}), Y="{Y_STR}" (len {len(Y_STR)}).')
    short = min(len(X_STR), len(Y_STR))
    print(f"  row length = min(m,n)+1 = {short + 1}; final cell = {cur[-1]}")
    assert cur[-1] == full_lcs[len(X_STR)][len(Y_STR)]
    print(f"[check] O(min(m,n)) result {cur[-1]} == 2-D result "
          f"{full_lcs[len(X_STR)][len(Y_STR)]}:  OK")
    print("\nTrade-off: with only two rows you can READ the answer but cannot")
    print("BACKTRACK (the path needs the full history). Use the full table when")
    print("you must reconstruct the items/subsequence itself.")


# ----------------------------------------------------------------------------
# SECTION D: TOP-DOWN (memo) vs BOTTOM-UP (tabulation)
# ----------------------------------------------------------------------------

def section_topdown_vs_bottomup():
    banner("SECTION D: top-down (memoization) vs bottom-up (tabulation)")
    print("Same recurrence, two evaluation orders:\n")
    print("  BOTTOM-UP (tabulation): solve smallest-first, fill a table iteratively.")
    print("    + no recursion depth limit   + great cache locality")
    print("    - solves EVERY subproblem even ones the answer never needs\n")
    print("  TOP-DOWN (memoization): recurse from the top; cache each result;")
    print("    never re-solves a subproblem.")
    print("    + only solves subproblems actually reached")
    print("    - recursion overhead / stack depth\n")

    k_bu = knapsack_2d(WT, VAL, W)[len(WT)][W]
    k_td = knapsack_memo(WT, VAL, W)
    l_bu = lcs_2d(X_STR, Y_STR)[len(X_STR)][len(Y_STR)]
    l_td = lcs_memo(X_STR, Y_STR)
    print(f"  knapsack  bottom-up = {k_bu}, top-down = {k_td}  -> "
          f"{'match' if k_bu == k_td else 'MISMATCH'}")
    print(f'  LCS       bottom-up = {l_bu}, top-down = {l_td}  -> '
          f"{'match' if l_bu == l_td else 'MISMATCH'}")
    assert k_bu == k_td and l_bu == l_td
    print(f"\n[check] both orders agree on knapsack ({k_bu}) and LCS ({l_bu}):  OK")
    print("Rule of thumb (CLRS §15.3): top-down is easier to write and wastes no")
    print("work on unreachable states; bottom-up is faster in practice and avoids")
    print("deep recursion. For knapsack all n*W states are reachable, so they do")
    print("exactly the same work - the choice is taste.")


# ----------------------------------------------------------------------------
# SECTION E: PATTERN RECOGNITION + GOLD CHECK
# ----------------------------------------------------------------------------

def section_pattern():
    banner("SECTION E: when to use DP - the two requirements + GOLD CHECK")
    print("DP applies ONLY when BOTH properties hold (CLRS §15.3):\n")
    print("  1. OPTIMAL SUBSTRUCTURE: the optimal solution contains optimal")
    print("     solutions to subproblems.")
    print("       knapsack: best value with first i items = best of (skip item i)")
    print("         and (take item i + best of first i-1 at reduced capacity).")
    print("       LCS: if X[i]==Y[j], the LCS ends in that char + LCS of the")
    print("         prefixes; if not, it's the longer of dropping one char.\n")
    print("  2. OVERLAPPING SUBPROBLEMS: the same subproblem recurs along many")
    print("     paths, so a naive recursion re-solves it exponentially often.\n")
    print("| problem  | subproblem        | distinct subproblems | naive   | DP      |")
    print("|----------|-------------------|----------------------|---------|---------|")
    print("| knapsack | best(first i, cap)| n * W                | O(2^n)  | O(n*W)  |")
    print("| LCS      | LCS(X[..i],Y[..j])| m * n                | O(2^m+n)| O(m*n)  |")
    print()
    print("Anti-pattern: if subproblems do NOT overlap (e.g. merge sort, where")
    print("each half is solved once), memoization buys nothing -> plain D&C.")
    print()

    # ---------- GOLD CHECK: re-derive everything and cross-verify ----------
    k2d = knapsack_2d(WT, VAL, W)[len(WT)][W]
    k1d = knapsack_1d(WT, VAL, W)[W]
    ktd = knapsack_memo(WT, VAL, W)
    kbv, kbs = knapsack_brute(WT, VAL, W)

    l2d = lcs_2d(X_STR, Y_STR)[len(X_STR)][len(Y_STR)]
    l1d = lcs_1d(X_STR, Y_STR)[-1]
    ltd = lcs_memo(X_STR, Y_STR)
    lbv = lcs_brute(X_STR, Y_STR)

    k_ok = k2d == k1d == ktd == kbv
    l_ok = l2d == l1d == ltd == lbv

    print("GOLD CHECK - every method must agree with brute force:")
    print("  knapsack:")
    print(f"    2-D table   = {k2d}")
    print(f"    1-D space   = {k1d}")
    print(f"    top-down    = {ktd}")
    print(f"    brute force = {kbv}  (items {kbs})")
    print(f"    -> {'OK' if k_ok else 'FAIL'}")
    print("  LCS:")
    print(f"    2-D table   = {l2d}")
    print(f"    1-D space   = {l1d}")
    print(f"    top-down    = {ltd}")
    print(f"    brute force = {lbv}")
    print(f"    -> {'OK' if l_ok else 'FAIL'}")
    print()
    print(f"GOLD CHECK: {'OK - knapsack=' + str(k2d) + ', LCS=\"' + str(lcs_backtrack(lcs_2d(X_STR, Y_STR), X_STR, Y_STR)) + '\" (len ' + str(l2d) + ')' if k_ok and l_ok else 'FAIL'}")
    print("(dp_knapsack_lcs.html re-runs both recurrences in JS and re-checks these.)")
    assert k_ok and l_ok
    return k_ok and l_ok


# ============================================================================
# main
# ============================================================================

def main():
    print("dp_knapsack_lcs.py - reference impl. All numbers below feed DP_KNAPSACK_LCS.md.")
    print("python stdlib only; deterministic.")

    section_knapsack()
    section_lcs()
    section_space()
    section_topdown_vs_bottomup()
    section_pattern()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
