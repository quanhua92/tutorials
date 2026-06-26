"""
dynamic_programming.py - Reference implementation for four DP archetypes:
  * 1D linear DP          (P070 Climbing Stairs)
  * 1D linear scan DP     (P198 House Robber)
  * Unbounded knapsack    (P322 Coin Change)
  * Interval / string DP  (P516 Longest Palindromic Subsequence)

This is the SINGLE SOURCE OF TRUTH for DYNAMIC_PROGRAMMING.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 dynamic_programming.py > dynamic_programming_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - filling in a spreadsheet once
============================================================================
Dynamic Programming is "smart brute force." Instead of recomputing the same
sub-answer over and over (naive recursion), you compute each sub-answer ONCE,
write it into a table, and look it up next time.

Picture a spreadsheet. Every cell `dp[i]` (or `dp[i][j]`) is the answer to a
smaller version of the problem. You fill cells in an order that guarantees
each cell's dependencies are already filled when you reach it. The answer to
the whole problem lives in one specific cell - usually the last one.

Two conditions must hold for DP to apply:
  1. OVERLAPPING SUBPROBLEMS - the same sub-answer is needed many times.
  2. OPTIMAL SUBSTRUCTURE - the optimal answer to the whole problem can be
     assembled from the optimal answers to its sub-problems.

Five-step recipe (every DP problem, every time):
  1. DEFINE THE STATE       what does dp[i] (or dp[i][j]) represent?
  2. BASE CASES             the trivial smallest instances.
  3. RECURRENCE             how dp[i] depends on smaller states.
  4. FILL ORDER             bottom-up (loops) or top-down (memo).
  5. EXTRACT ANSWER         usually dp[n], sometimes max(dp).

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  state           a precise description of a sub-problem. The hardest and
                  most important step: "dp[i] = min coins to make amount i."
  base case       the seed values the table starts from. dp[0] is almost
                  always the anchor (0 cost / 1 way / True).
  recurrence      the formula that combines smaller answers into a bigger
                  one. Write this on the whiteboard BEFORE coding.
  tabulation      bottom-up: loops fill the table from small to large.
  memoization     top-down: recursive function caches each result.
  rolling vars    many 1D DPs need only the last 1-2 cells, so you replace
                  the whole array with two variables. O(1) space.
  sentinel        an "impossible" placeholder. Coin Change fills with
                  amount+1 (bigger than any real answer); if the final cell
                  is still the sentinel, the target is unreachable -> -1.
  interval DP     a 2D table where dp[l][r] describes a CONTIGUOUS slice
                  s[l..r]. Fill by LENGTH first so inner slices exist.

============================================================================
THE SKELETON (1D and 2D share this skeleton)
============================================================================
    # 1D bottom-up
    def solve_1d(items):
        dp = [INIT] * (n + 1)
        dp[0] = BASE
        for i in range(1, n + 1):
            dp[i] = COMBINE(dp[i-1], dp[i-2], ...)   # recurrence
        return dp[n]

    # 2D / interval bottom-up
    def solve_2d(s):
        n = len(s)
        dp = [[0] * n for _ in range(n)]
        for i in range(n): dp[i][i] = 1              # base: single char
        for length in range(2, n + 1):               # by LENGTH
            for l in range(n - length + 1):
                r = l + length - 1
                # recurrence using dp[l+1][r-1], dp[l+1][r], dp[l][r-1]
        return dp[0][n-1]
"""

from __future__ import annotations


# ============================================================================
# VARIANT 1 - 1D LINEAR DP                                 P070 CLIMBING STAIRS
# ============================================================================
def climb_stairs(n: int) -> int:
    """Number of distinct ways to climb *n* stairs taking 1 or 2 steps.

    Recurrence:  dp[i] = dp[i-1] + dp[i-2]   (this is Fibonacci shifted).
    Base:        dp[0]=1, dp[1]=1.
    Rolling two variables -> O(1) space.

    Time:  O(n)
    Space: O(1)
    """
    if n <= 1:
        return 1
    prev2: int = 1   # dp[i-2]
    prev1: int = 1   # dp[i-1]
    for _ in range(2, n + 1):
        prev2, prev1 = prev1, prev1 + prev2
    return prev1


# ============================================================================
# VARIANT 2 - 1D LINEAR SCAN DP                            P198 HOUSE ROBBER
# ============================================================================
def rob(nums: list[int]) -> int:
    """Max money robbable without touching two adjacent houses.

    Recurrence:  dp[i] = max(dp[i-1], dp[i-2] + nums[i])
                 either SKIP house i (keep dp[i-1])
                 or    ROB  house i (add nums[i] to dp[i-2]).
    Base:        dp[0]=nums[0], dp[1]=max(nums[0], nums[1]).
    Rolling vars -> O(1) space.

    Time:  O(n)
    Space: O(1)
    """
    if not nums:
        return 0
    if len(nums) == 1:
        return nums[0]
    prev2: int = nums[0]
    prev1: int = max(nums[0], nums[1])
    for i in range(2, len(nums)):
        prev2, prev1 = prev1, max(prev1, prev2 + nums[i])
    return prev1


# ============================================================================
# VARIANT 3 - UNBOUNDED KNAPSACK (min items)               P322 COIN CHANGE
# ============================================================================
def coin_change(coins: list[int], amount: int) -> int:
    """Fewest coins that sum to *amount*, or -1 if impossible.

    Recurrence:  dp[i] = min over coins c<=i of (dp[i-c] + 1).
                 "best way to make i = best way to make (i-c) plus one coin c".
                 UNBOUNDED: each coin reusable, so we look at the SAME row
                 (dp[i-c] may already include coin c). Forward iteration.
    Base:        dp[0] = 0.
    Sentinel:    every cell starts at amount+1 (bigger than any real answer);
                 if dp[amount] is still the sentinel, return -1.

    Time:  O(amount * len(coins))
    Space: O(amount)
    """
    INF = amount + 1
    dp: list[int] = [INF] * (amount + 1)
    dp[0] = 0
    for i in range(1, amount + 1):
        for c in coins:
            if c <= i and dp[i - c] + 1 < dp[i]:
                dp[i] = dp[i - c] + 1
    return dp[amount] if dp[amount] != INF else -1


# ============================================================================
# VARIANT 4 - INTERVAL / STRING DP                         P516 LONGEST
#                                  PALINDROMIC SUBSEQUENCE (via LCS reduction)
# ============================================================================
def longest_palindrome_subseq(s: str) -> int:
    """Length of the longest palindromic subsequence of *s*.

    Two equivalent formulations:
      (A) Interval DP:  dp[l][r] = LPS length of s[l..r].
            if s[l]==s[r]: dp[l][r] = dp[l+1][r-1] + 2
            else:          dp[l][r] = max(dp[l+1][r], dp[l][r-1])
            base: dp[i][i] = 1.
      (B) LCS reduction: LPS(s) = LCS(s, reverse(s)).

    Here we implement (B) for clarity and to match the LCS mental model.
    The 2D fill below is identical in spirit to interval DP - both fill a
    table from small slices to large.

    Time:  O(n^2)
    Space: O(n^2)   (the rolling-array version drops this to O(n))
    """
    rev = s[::-1]
    n = len(s)
    dp: list[list[int]] = [[0] * (n + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            if s[i - 1] == rev[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
    return dp[n][n]


# ============================================================================
# STEP TRACERS - re-implement the same logic but record every cell fill.
# Used by the worked-example sections so the .md and .html can show the
# table filling step-by-step.
# ============================================================================
def trace_climb_stairs(n: int) -> list[dict]:
    """Record each Fibonacci-style step. Returns [{i, prev2, prev1, new}]."""
    steps: list[dict] = [{"i": 0, "prev2": None, "prev1": None, "new": 1}]
    if n == 0:
        return steps
    steps.append({"i": 1, "prev2": None, "prev1": 1, "new": 1})
    prev2, prev1 = 1, 1
    for i in range(2, n + 1):
        val = prev1 + prev2
        steps.append({"i": i, "prev2": prev2, "prev1": prev1, "new": val})
        prev2, prev1 = prev1, val
    return steps


def trace_rob(nums: list[int]) -> list[dict]:
    """Record each rob/skip decision. Returns [{i, nums_i, skip, rob, pick}]."""
    if not nums:
        return []
    if len(nums) == 1:
        return [{"i": 0, "nums_i": nums[0], "skip": None, "rob": None,
                 "best": nums[0], "pick": "rob"}]
    out: list[dict] = []
    prev2 = nums[0]
    prev1 = max(nums[0], nums[1])
    out.append({"i": 0, "nums_i": nums[0], "skip": None, "rob": None,
                "best": nums[0], "pick": "seed"})
    out.append({"i": 1, "nums_i": nums[1], "skip": nums[0], "rob": nums[1],
                "best": prev1, "pick": "rob" if nums[1] >= nums[0] else "skip"})
    for i in range(2, len(nums)):
        skip_val = prev1
        rob_val = prev2 + nums[i]
        pick = "rob" if rob_val >= skip_val else "skip"
        best = max(skip_val, rob_val)
        out.append({"i": i, "nums_i": nums[i], "skip": skip_val,
                    "rob": rob_val, "best": best, "pick": pick})
        prev2, prev1 = prev1, best
    return out


def trace_coin_change(coins: list[int], amount: int) -> list[dict]:
    """Record each dp[i] fill and which coin achieved it."""
    INF = amount + 1
    dp: list[int] = [INF] * (amount + 1)
    dp[0] = 0
    steps: list[dict] = [{"i": 0, "value": 0, "best_coin": None,
                          "candidates": []}]
    for i in range(1, amount + 1):
        cands: list[tuple[int, int]] = []  # (coin, dp[i-coin]+1)
        for c in coins:
            if c <= i:
                cands.append((c, dp[i - c] + 1))
        if cands:
            best_coin, best_val = min(cands, key=lambda t: t[1])
            dp[i] = best_val
        else:
            best_coin, best_val = None, INF
            dp[i] = INF
        steps.append({"i": i, "value": dp[i], "best_coin": best_coin,
                      "candidates": cands})
    return steps


def trace_lps(s: str) -> dict:
    """Return the full LCS(s, reverse(s)) table plus a cell-by-cell fill log.

    The fill log records each (i, j) in row-major order with the chosen
    transition, so the .html can animate the table filling one cell at a time.
    """
    rev = s[::-1]
    n = len(s)
    dp: list[list[int]] = [[0] * (n + 1) for _ in range(n + 1)]
    log: list[dict] = []
    for i in range(1, n + 1):
        for j in range(1, n + 1):
            if s[i - 1] == rev[j - 1]:
                dp[i][j] = dp[i - 1][j - 1] + 1
                kind = "diag+1"
            else:
                up, left = dp[i - 1][j], dp[i][j - 1]
                if up >= left:
                    dp[i][j] = up
                    kind = "up"
                else:
                    dp[i][j] = left
                    kind = "left"
            log.append({"i": i, "j": j, "value": dp[i][j],
                        "si": s[i - 1], "sr": rev[j - 1], "kind": kind})
    return {"s": s, "rev": rev, "table": dp, "log": log, "answer": dp[n][n]}


# ============================================================================
# SECTION A - P070 CLIMBING STAIRS (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P070 Climbing Stairs  (1D linear DP, Fibonacci-style)")
    print("=" * 72)
    print()
    print("State:    dp[i] = number of distinct ways to reach stair i.")
    print("Recurrence: dp[i] = dp[i-1] + dp[i-2]   (climb 1 from i-1,")
    print("                                   or  climb 2 from i-2).")
    print("Base:     dp[0] = 1 (one way to stand on the ground),")
    print("          dp[1] = 1.")
    print()
    n = 5
    print(f"Worked example: n = {n}")
    print()
    print("  i | prev2 | prev1 | new = prev1 + prev2")
    print("  --+-------+-------+----------------------")
    steps = trace_climb_stairs(n)
    for st in steps:
        if st["prev2"] is None:
            print(f"  {st['i']} |  seed |  seed | {st['new']}")
        else:
            print(f"  {st['i']} | {st['prev2']:5} | {st['prev1']:5} | "
                  f"{st['new']}  = {st['prev1']} + {st['prev2']}")
    print()
    print(f"climb_stairs({n}) -> {climb_stairs(n)}    (expected 8)")
    print()
    print("Rolling-variable view: only the last two cells matter, so the")
    print("array collapses to two scalars - O(1) space.")
    print()
    print("Sequence (n=1..10):")
    seq = [climb_stairs(k) for k in range(1, 11)]
    print("  " + ", ".join(str(v) for v in seq))
    print("  (1, 2, 3, 5, 8, 13, 21, 34, 55, 89)  -- Fibonacci shifted by one.")
    print()
    print("Edge cases:")
    print(f"  n=0 -> {climb_stairs(0)}   (one way: do nothing)")
    print(f"  n=1 -> {climb_stairs(1)}")
    print(f"  n=2 -> {climb_stairs(2)}   (1+1, 2)")
    print()


# ============================================================================
# SECTION B - P198 HOUSE ROBBER (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P198 House Robber  (1D linear scan DP, rob-or-skip)")
    print("=" * 72)
    print()
    print("State:      dp[i] = max money robbing houses[0..i].")
    print("Recurrence: dp[i] = max(dp[i-1], dp[i-2] + nums[i])")
    print("              skip house i -> keep dp[i-1]")
    print("              rob  house i -> add nums[i] to dp[i-2]")
    print("            (cannot rob two adjacent houses, so rob uses i-2.)")
    print("Base:       dp[0] = nums[0],   dp[1] = max(nums[0], nums[1]).")
    print()
    nums = [2, 7, 9, 3, 1]
    print(f"Worked example: nums = {nums}")
    print()
    print("  i | nums[i] | skip=dp[i-1] | rob=dp[i-2]+nums[i] | best | pick")
    print("  --+---------+---------------+---------------------+------+------")
    steps = trace_rob(nums)
    for st in steps:
        if st["skip"] is None:
            print(f"  {st['i']} |   {st['nums_i']:5} |       seed     | "
                  f"       seed          | {st['best']:4} | {st['pick']}")
        else:
            print(f"  {st['i']} |   {st['nums_i']:5} |   {st['skip']:9} | "
                  f"{st['rob']:19} | {st['best']:4} | {st['pick']}")
    print()
    print(f"rob({nums}) -> {rob(nums)}    (expected 12: houses 2+9+1)")
    print()
    print("Path: 2 (i=0) -> skip 7 (i=1) -> rob 9 (i=2) -> skip 3 (i=3) "
          "-> rob 1 (i=4).")
    print("     2 + 9 + 1 = 12.")
    print()
    print("Edge cases:")
    print(f"  []      -> {rob([])}")
    print(f"  [5]     -> {rob([5])}")
    print(f"  [2,1]   -> {rob([2, 1])}   (rob the 2)")
    print(f"  [1,2,3] -> {rob([1, 2, 3])}   (rob 1 and 3)")
    print()


# ============================================================================
# SECTION C - P322 COIN CHANGE (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P322 Coin Change  (unbounded knapsack, minimize items)")
    print("=" * 72)
    print()
    print("State:      dp[i] = minimum coins to make amount i.")
    print("Recurrence: dp[i] = min over coins c<=i of (dp[i-c] + 1).")
    print("              'take one coin c, then fill the rest (i-c) optimally.'")
    print("            UNBOUNDED: the same coin may be reused many times.")
    print("Base:       dp[0] = 0.")
    print("Sentinel:   every cell starts at amount+1 (bigger than any real")
    print("            answer); if dp[amount] is still the sentinel at the")
    print("            end, the amount is unreachable -> return -1.")
    print()
    coins = [1, 2, 5]
    amount = 11
    print(f"Worked example: coins = {coins}, amount = {amount}")
    print()
    print("  i | candidates (coin -> dp[i-coin]+1)       | best | best_coin")
    print("  --+------------------------------------------+------+----------")
    steps = trace_coin_change(coins, amount)
    for st in steps:
        cand_str = ", ".join(f"{c}->{v}" for c, v in st["candidates"])
        if not cand_str:
            cand_str = "(none)"
        val = st["value"] if st["value"] <= amount else "INF"
        bc = st["best_coin"] if st["best_coin"] is not None else "-"
        print(f"  {st['i']:2} | {cand_str:40} | {str(val):4} | {bc}")
    print()
    print(f"coin_change({coins}, {amount}) -> "
          f"{coin_change(coins, amount)}    (expected 3: 5+5+1)")
    print()
    print("Reconstruction (greedy walk back):")
    print("  amount=11, best_coin=5  -> take 5,  remaining 6")
    print("  amount= 6, best_coin=5  -> take 5,  remaining 1")
    print("  amount= 1, best_coin=1  -> take 1,  remaining 0   -> [5, 5, 1].")
    print()
    print("Edge cases:")
    print(f"  coins=[2], amount=3  -> {coin_change([2], 3)}   "
          f"(odd amount, even coin -> impossible)")
    print(f"  coins=[1], amount=0  -> {coin_change([1], 0)}   "
          f"(zero amount needs zero coins)")
    print(f"  coins=[1,5,10], amount=27 -> {coin_change([1, 5, 10], 27)}   "
          f"(10+10+5+1+1)")
    print()


# ============================================================================
# SECTION D - P516 LONGEST PALINDROMIC SUBSEQUENCE (worked example)
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - P516 Longest Palindromic Subsequence  "
          "(interval / string DP)")
    print("=" * 72)
    print()
    print("Reduction:  LPS(s) = LCS(s, reverse(s)).")
    print("A palindromic subsequence reads the same forward and backward,")
    print("so it is exactly a subsequence common to s and its reverse.")
    print()
    print("State:      dp[i][j] = LCS length of s[:i] and reverse(s)[:j].")
    print("Recurrence: if s[i-1] == rev[j-1]:  dp[i][j] = dp[i-1][j-1] + 1")
    print("             else:                    dp[i][j] = max(dp[i-1][j],")
    print("                                                     dp[i][j-1]).")
    print("Base:       row 0 and column 0 are all 0 (LCS with empty string).")
    print("Fill order: row-major, top-left to bottom-right, so the three")
    print("            dependency cells are already computed.")
    print()
    s = "bbbab"
    print(f"Worked example: s = '{s}'   reverse = '{s[::-1]}'")
    print()
    res = trace_lps(s)
    n = len(s)
    print("Full 2D table (rows = s index, cols = reverse(s) index):")
    print()
    hdr = "      " + " ".join(f"{c:>3}" for c in res["rev"])
    print(hdr)
    print("      " + " ".join("---" for _ in res["rev"]))
    for i in range(1, n + 1):
        row = res["table"][i][1:]
        print(f"  {s[i-1]} | " + " ".join(f"{v:>3}" for v in row))
    print()
    print(f"longest_palindrome_subseq('{s}') -> {res['answer']}    "
          f"(expected 4: 'bbbb')")
    print()
    print("Transition tally (cell-by-cell fill log, first 12 entries):")
    print("  (i,j) | s[i] rev[j] | value | transition")
    print("  -------+-------------+-------+------------")
    for entry in res["log"][:12]:
        print(f"  ({entry['i']},{entry['j']})   |  {entry['si']}    "
              f"{entry['sr']}    | {entry['value']:5} | {entry['kind']}")
    print(f"  ... ({len(res['log'])} cells filled in total)")
    print()
    print("Transition legend:")
    print("  diag+1  characters matched -> dp[i-1][j-1] + 1")
    print("  up      chars differed     -> took dp[i-1][j]   (drop s char)")
    print("  left    chars differed     -> took dp[i][j-1]   (drop rev char)")
    print()
    print("Edge cases:")
    print(f"  'a'        -> {longest_palindrome_subseq('a')}   "
          f"(single char is its own palindrome)")
    print(f"  'abc'      -> {longest_palindrome_subseq('abc')}   "
          f"(any single char)")
    print(f"  'aaa'      -> {longest_palindrome_subseq('aaa')}   "
          f"(whole string)")
    print(f"  'bbbab'    -> {longest_palindrome_subseq('bbbab')}   "
          f"(drop the 'a')")
    print(f"  'cbbd'     -> {longest_palindrome_subseq('cbbd')}   "
          f"('bb')")
    print()


# ============================================================================
# SECTION E - COMPLEXITY TABLE & GOTCHAS
# ============================================================================
def section_e() -> None:
    print("=" * 72)
    print("SECTION E - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Problem                          Time          Space  (naive)")
    print("  -------------------------------- -------------- ---------")
    print("  P070 Climbing Stairs             O(n)          O(1) rolling")
    print("  P198 House Robber                O(n)          O(1) rolling")
    print("  P322 Coin Change                 O(A * C)      O(A)")
    print("  P516 Longest Palindromic Subseq  O(n^2)        O(n) rolling")
    print()
    print("  A = amount, C = number of coins, n = string length.")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. STATE DEFINITION IS THE HARDEST PART. Before writing any")
    print("     code, write one English sentence: 'dp[i] = ...'. If you")
    print("     cannot, your state is wrong. Everything else is mechanical.")
    print("  2. SENTINEL FOR MIN-DP. Coin Change initializes every cell")
    print("     with amount+1 (or float('inf')), NOT 0. A 0 default makes")
    print("     every min() pick 0 and silently returns garbage. Always")
    print("     check at the end: if dp[amount] is still the sentinel,")
    print("     return -1.")
    print("  3. WRONG BASE CASE for min vs count. Coin Change (min coins):")
    print("     dp[0]=0, rest=INF. Coin Change II (count ways): dp[0]=1,")
    print("     rest=0. Swapping these corrupts every cell.")
    print("  4. INTERVAL DP FILL ORDER. For palindrome / burst-balloon")
    print("     problems you cannot iterate i from 0 to n. You MUST fill")
    print("     by LENGTH first, so dp[i+1][j-1] exists before dp[i][j].")
    print("  5. INDEX-OFF-BY-ONE in 2D string DP. dp[i][j] covers s[:i],")
    print("     so the character at dp-position i is s[i-1] in string-land.")
    print("     Writing s[i] instead of s[i-1] is a silent wrong-answer bug.")
    print("  6. ROLLING ARRAY for space. If dp[i] only needs dp[i-1] and")
    print("     dp[i-2], replace the array with two scalars (P070, P198).")
    print("     For 2D tables that only need the previous row, use prev/curr")
    print("     arrays to drop O(n*m) to O(min(n,m)).")
    print("  7. UNBOUNDED vs 0/1 KNAPSACK ITERATION DIRECTION. Unbounded")
    print("     (coin change): iterate capacity FORWARD so a coin can be")
    print("     reused. 0/1 (subset sum): iterate capacity BACKWARDS so")
    print("     each item is used at most once. Getting this wrong turns")
    print("     one problem into the other.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff  Key trick")
    print("  -------------------------------- ----  -----------------------------------")
    print("  P070 Climbing Stairs             Easy  dp[i]=dp[i-1]+dp[i-2]; 2 rolling vars")
    print("  P198 House Robber                Med   dp[i]=max(dp[i-1], dp[i-2]+nums[i])")
    print("  P322 Coin Change                 Med   unbounded; sentinel amount+1; -1 if INF")
    print("  P516 Longest Palindromic Subseq  Med   LPS(s) = LCS(s, reverse(s))")
    print("  P746 Min Cost Climbing Stairs    Easy  dp[i] = cost[i] + min(dp[i-1], dp[i-2])")
    print("  P213 House Robber II             Med   run rob() on nums[1:] and nums[:-1], take max")
    print("  P337 House Robber III            Med   tree DP: dp[node] = (rob, not_rob) pair")
    print("  P416 Partition Equal Subset Sum  Med   0/1 knapsack: target = sum/2; reverse iter")
    print("  P494 Target Sum                  Med   count subsets summing to (sum+target)/2")
    print("  P300 Longest Increasing Subseq   Med   dp[i]=max(dp[j]+1) for j<i, nums[j]<nums[i]")
    print("  P062 Unique Paths                Med   dp[i][j]=dp[i-1][j]+dp[i][j-1]")
    print("  P1143 Longest Common Subsequence Med   same table shape as P516")
    print("  P072 Edit Distance               Med   dp[i][j]=1+min(diag,up,left) if mismatch")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()

    # ---- assertions ----
    assert climb_stairs(0) == 1
    assert climb_stairs(1) == 1
    assert climb_stairs(2) == 2
    assert climb_stairs(5) == 8
    assert climb_stairs(10) == 89

    assert rob([]) == 0
    assert rob([5]) == 5
    assert rob([2, 1]) == 2
    assert rob([1, 2, 3]) == 4
    assert rob([2, 7, 9, 3, 1]) == 12
    assert rob([1, 2, 3, 1]) == 4

    assert coin_change([1, 2, 5], 11) == 3
    assert coin_change([2], 3) == -1
    assert coin_change([1], 0) == 0
    assert coin_change([1, 5, 10], 27) == 5
    assert coin_change([186, 419, 83, 408], 6249) == 20

    assert longest_palindrome_subseq("a") == 1
    assert longest_palindrome_subseq("abc") == 1
    assert longest_palindrome_subseq("aaa") == 3
    assert longest_palindrome_subseq("bbbab") == 4
    assert longest_palindrome_subseq("cbbd") == 2

    print("=" * 72)
    print("[check] climb_stairs / rob / coin_change / longest_palindrome_subseq ... OK")
    print("=" * 72)
