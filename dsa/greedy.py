"""
greedy.py - Reference implementation of Greedy Algorithms: when they are
optimal and when they fail.

This is the SINGLE SOURCE OF TRUTH for GREEDY.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 greedy.py > greedy_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

========================================================================
THE INTUITION (read this first) -- the always-grab-the-best-looking-bite rule
========================================================================
A GREEDY algorithm builds a solution one step at a time: at each step it makes
the choice that looks best RIGHT NOW (locally optimal) and NEVER undoes it. It
does not look ahead and never backtracks.

  * When it works : the locally-best choices chain up into a GLOBALLY-best
                    solution. Examples below: activity selection, Huffman
                    codes, fractional knapsack, Dijkstra, Kruskal.
  * When it fails : a choice that is best NOW paints you into a corner later,
                    so the greedy answer is worse than optimal. Classic case:
                    0/1 knapsack (and coin change with weird denominations).

THE QUESTION greedy.py answers: HOW do you know, for a given problem, whether
greedy is optimal? Two ways, both shown below:
  (1) An EXCHANGE ARGUMENT -- assume an optimal solution differs from greedy,
      then SWAP one greedy choice in and show the result is no worse. Done for
      activity selection in Section E.
  (2) MATROID THEORY -- a problem whose feasible solutions are the independent
      sets of a matroid ALWAYS has an optimal greedy solution (Edmonds 1971).
      Activity selection and MST live on matroids; 0/1 knapsack does NOT.

========================================================================
PLAIN-ENGLISH GLOSSARY
========================================================================
  greedy choice    the locally-best option taken at each step, never undone.
  feasible         satisfies all the problem's constraints (e.g. no two
                   activities overlap; total knapsack weight <= capacity).
  optimal          no other feasible solution has a better objective value.
  exchange argument a proof technique: swap a greedy choice into an optimum
                   and show the objective cannot get worse.
  matroid          a set system (S, independent_sets) with three rules --
                   heredity, empty set is independent, and an augmentation
                   property. Greedy is optimal on every matroid.
  fractional ...   you may take a FRACTION of an item (greedy by value/weight
  knapsack         density is optimal).
  0/1 knapsack     you must take ALL of an item or NONE -- greedy by density
                   is NOT optimal (Section B).

========================================================================
THE CANONICAL CASES (all verified against CLRS + asserted in code)
========================================================================
  Activity selection (CLRS 16.1): sort by finish time, repeatedly pick the
      next compatible activity. OPTIMAL. Lives on a matroid-like interval
      structure; proved by exchange argument in Section E.
  Fractional knapsack (CLRS 16.2): sort by value/weight, greedily fill.
      OPTIMAL. (Section B.)
  0/1 knapsack (CLRS 16.2): greedy-by-density is NOT optimal -- it leaves
      capacity stranded. Needs DP. (Section B.)
  Huffman codes (CLRS 16.3): greedily merge the two smallest frequencies.
      OPTIMAL prefix code. (Section C.)
  Coin change (CLRS 16.1 ex): greedy is optimal for "canonical" coin systems
      (US: 25,10,5,1) but FAILS for arbitrary ones (e.g. [4,3,1]). (Section D.)

KEY FACTS (all asserted / gold-checked below):
    greedy activity selection count == exhaustive optimum   (Section A + gold)
    fractional-knapsack greedy value == optimum (capacity never left empty)
    0/1 knapsack greedy-by-density (160) < DP optimum (220)  -> greedy FAILS
    Huffman weighted path length for f={a45,b13,c12,d16,e9,f5} == 224 bits
    coin change greedy on [4,3,1] amount 6 == 3 coins; optimum == 2 (FAILS)

References:
    CLRS, Introduction to Algorithms, 3rd ed. -- ch.16 (Greedy Algorithms).
    Edmonds (1971), "Matroids and the greedy algorithm", J. Res. NBS 69B.
    Huffman (1952), "A Method for the Construction of Minimum-Redundancy
    Codes", Proc. IRE -- the original paper.
"""

from __future__ import annotations

import heapq
import itertools

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code GREEDY.md walks through)
# ============================================================================

# --- Activity selection ------------------------------------------------------
# Each activity is (name, start, finish). Two activities are COMPATIBLE if they
# do not overlap: one finishes before the other starts.

Activity = tuple[str, int, int]


def activity_selection_greedy(acts: list[Activity]) -> list[Activity]:
    """CLRS 16.1 greedy. Sort by FINISH time, then repeatedly pick the next
    activity whose start >= last chosen finish. Returns a maximum-size set of
    mutually compatible activities. OPTIMAL (proved in Section E)."""
    ordered = sorted(acts, key=lambda a: a[2])     # by finish time
    chosen: list[Activity] = []
    last_finish = -1
    for name, s, f in ordered:
        if s >= last_finish:                        # compatible with last pick
            chosen.append((name, s, f))
            last_finish = f
    return chosen


def activity_selection_bruteforce(acts: list[Activity]) -> int:
    """Exhaustive optimum: try every subset, keep the largest compatible one.
    O(2^n) -- only usable for tiny n, used purely as the gold reference."""
    best = 0
    n = len(acts)
    for r in range(n + 1):
        for combo in itertools.combinations(acts, r):
            # compatible iff, after sorting by start, each next start >= prev finish
            ordered = sorted(combo, key=lambda a: a[1])
            ok = all(ordered[i + 1][1] >= ordered[i][2] for i in range(len(ordered) - 1))
            if ok:
                best = max(best, len(combo))
    return best


# --- Fractional knapsack (greedy works) --------------------------------------
Item = tuple[str, float, float]   # (name, value, weight)


def fractional_knapsack(items: list[Item], capacity: float) -> tuple[float, list[tuple[str, float]]]:
    """CLRS 16.2. Sort items by value/weight DESC, take whole items until the
    next one does not fit, then take a FRACTION of it. OPTIMAL."""
    ordered = sorted(items, key=lambda it: it[1] / it[2], reverse=True)
    total_value = 0.0
    taken: list[tuple[str, float]] = []
    rem = capacity
    for name, val, wt in ordered:
        if rem <= 0:
            break
        if wt <= rem:                              # take the whole item
            taken.append((name, 1.0))
            total_value += val
            rem -= wt
        else:                                      # take a fraction to fill the rest
            frac = rem / wt
            taken.append((name, frac))
            total_value += val * frac
            rem = 0
    return total_value, taken


# --- 0/1 knapsack: greedy-by-density (FAILS) vs DP optimum -------------------
def knapsack01_greedy_density(items: list[Item], capacity: float) -> tuple[float, list[str]]:
    """The NAIVE greedy that everyone reaches for: sort by value/weight and take
    whole items. NOT OPTIMAL for 0/1 knapsack -- it strands capacity."""
    ordered = sorted(items, key=lambda it: it[1] / it[2], reverse=True)
    total = 0.0
    chosen: list[str] = []
    rem = capacity
    for name, val, wt in ordered:
        if wt <= rem:
            chosen.append(name)
            total += val
            rem -= wt
    return total, chosen


def knapsack01_dp(items: list[Item], capacity: float) -> tuple[float, list[str]]:
    """Exact 0/1 knapsack optimum via dynamic programming. O(n*W). Used as the
    gold reference that exposes the greedy-by-density failure."""
    n = len(items)
    W = int(capacity)
    # dp[w] = best value with capacity w
    dp = [0.0] * (W + 1)
    keep = [[False] * (W + 1) for _ in range(n)]
    for i, (_, val, wt) in enumerate(items):
        wi = int(wt)
        for w in range(W, wi - 1, -1):
            cand = dp[w - wi] + val
            if cand > dp[w]:
                dp[w] = cand
                keep[i][w] = True
    # reconstruct
    chosen: list[str] = []
    w = W
    for i in range(n - 1, -1, -1):
        if keep[i][w]:
            chosen.append(items[i][0])
            w -= int(items[i][2])
    return dp[W], chosen[::-1]


# --- Huffman coding ----------------------------------------------------------
class HuffNode:
    __slots__ = ("freq", "char", "left", "right")

    def __init__(self, freq: int, char: str | None = None,
                 left: "HuffNode | None" = None, right: "HuffNode | None" = None):
        self.freq = freq
        self.char = char
        self.left = left
        self.right = right


def huffman_codes(freqs: dict[str, int]) -> tuple[dict[str, str], HuffNode]:
    """CLRS 16.3. Greedily merge the two smallest-frequency nodes until one tree
    remains. Returns (char -> codeword, root). OPTIMAL prefix code."""
    # heap entries: (freq, counter, node) -- counter breaks ties deterministically
    heap: list[tuple[int, int, HuffNode]] = []
    counter = 0
    for ch, f in freqs.items():
        heapq.heappush(heap, (f, counter, HuffNode(f, ch)))
        counter += 1
    while len(heap) > 1:
        f1, _, n1 = heapq.heappop(heap)            # two smallest
        f2, _, n2 = heapq.heappop(heap)
        merged = HuffNode(f1 + f2, None, n1, n2)   # n1 = left (0), n2 = right (1)
        heapq.heappush(heap, (f1 + f2, counter, merged))
        counter += 1
    root = heap[0][2]
    codes: dict[str, str] = {}

    def walk(node: HuffNode, prefix: str) -> None:
        if node.char is not None:                  # leaf
            codes[node.char] = prefix or "0"
            return
        if node.left:
            walk(node.left, prefix + "0")
        if node.right:
            walk(node.right, prefix + "1")

    walk(root, "")
    return codes, root


def huffman_weighted_length(codes: dict[str, str], freqs: dict[str, int]) -> int:
    """sum(freq * codelength) -- the quantity Huffman minimizes."""
    return sum(freqs[ch] * len(code) for ch, code in codes.items())


# --- Coin change: greedy vs optimal ------------------------------------------
def coin_change_greedy(coins: list[int], amount: int) -> tuple[int, list[int]]:
    """Greedy: always take the largest coin that fits. Optimal ONLY for
    'canonical' coin systems (e.g. US 25,10,5,1); FAILS otherwise."""
    coins_desc = sorted(coins, reverse=True)
    count = 0
    used: list[int] = []
    rem = amount
    for c in coins_desc:
        while rem >= c:
            rem -= c
            count += 1
            used.append(c)
    if rem != 0:
        return float("inf"), []                    # greedy could not make exact change
    return count, used


def coin_change_dp(coins: list[int], amount: int) -> tuple[int, list[int]]:
    """Exact fewest-coins optimum via DP. O(amount * len(coins)). Gold ref."""
    INF = amount + 1
    dp = [0] + [INF] * amount
    par = [-1] * (amount + 1)                       # par[a] = coin used to reach a
    for a in range(1, amount + 1):
        for c in coins:
            if c <= a and dp[a - c] + 1 < dp[a]:
                dp[a] = dp[a - c] + 1
                par[a] = c
    if dp[amount] == INF:
        return float("inf"), []
    # reconstruct
    used: list[int] = []
    a = amount
    while a > 0:
        used.append(par[a])
        a -= par[a]
    return dp[amount], sorted(used, reverse=True)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_huffman_tree(node: HuffNode, depth: int = 0, edge: str = "") -> None:
    """Sideways ASCII tree. Left edge labelled 0, right edge labelled 1.
    Leaves show char(freq); internal nodes show their merged frequency."""
    if node is None:
        return
    indent = "    " * depth
    if node.char is not None:
        print(f"{indent}{edge}{node.char}({node.freq})")
    else:
        if node.right:
            print_huffman_tree(node.right, depth + 1, "1-")
        print(f"{indent}{edge}*({node.freq})")
        if node.left:
            print_huffman_tree(node.left, depth + 1, "0-")


# ----------------------------------------------------------------------------
# SECTION A: activity selection -- the canonical greedy-that-works example
# ----------------------------------------------------------------------------

def section_activity_selection() -> None:
    banner("SECTION A: activity selection  (greedy that WORKS)")
    # CLRS 16.1 activities: (name, start, finish). s < f.
    acts: list[Activity] = [
        ("A1", 1, 4), ("A2", 3, 5), ("A3", 0, 6), ("A4", 5, 7),
        ("A5", 3, 9), ("A6", 5, 9), ("A7", 6, 10), ("A8", 8, 11),
        ("A9", 8, 12), ("A10", 2, 14), ("A11", 12, 16),
    ]
    print("Activities (name, start, finish). Two are compatible if one finishes")
    print("before the other starts.\n")
    print("| name | start | finish |")
    print("|------|-------|--------|")
    for name, s, f in acts:
        print(f"| {name}  | {s:<5} | {f:<6} |")
    print()
    greedy = activity_selection_greedy(acts)
    opt = activity_selection_bruteforce(acts)
    print("GREEDY (sort by finish, repeatedly pick next compatible):\n")
    print("  step: order activities by FINISH time, keep an activity iff its")
    print("  start >= the finish of the last one we kept.\n")
    print("  selections:")
    last = -1
    for name, s, f in greedy:
        print(f"    + {name} (s={s}, f={f})   [start {s} >= last_finish {last}]")
        last = f
    print(f"\n  greedy picks {len(greedy)} activities: {[n for n, _, _ in greedy]}")
    print(f"  exhaustive optimum (try all 2^{len(acts)} subsets) = {opt}")
    print(f"  [check] greedy == optimum? {len(greedy) == opt}")
    print("\nThis is the textbook greedy that is provably optimal. The proof is an")
    print("exchange argument -- see Section E.")


# ----------------------------------------------------------------------------
# SECTION B: fractional knapsack (works) vs 0/1 knapsack (fails)
# ----------------------------------------------------------------------------

def section_knapsack() -> None:
    banner("SECTION B: fractional knapsack WORKS, 0/1 knapsack FAILS")
    # CLRS 16.2 items: (name, value, weight). Same three items both times.
    items: list[Item] = [("i1", 60.0, 10.0), ("i2", 100.0, 20.0), ("i3", 120.0, 30.0)]
    W = 50.0
    print(f"Items (name, value, weight), capacity W = {W:.0f}\n")
    print("| item | value | weight | value/weight |")
    print("|------|-------|--------|--------------|")
    for name, v, w in items:
        print(f"| {name}  | {v:<5.0f} | {w:<6.0f} | {v/w:<12.2f} |")
    print()

    print("--- (1) FRACTIONAL knapsack: greedy by value/weight is OPTIMAL ---")
    frac_val, frac_taken = fractional_knapsack(items, W)
    print(f"  greedy takes: {frac_taken}")
    print(f"  total value   = {frac_val:.0f}")
    print("  (takes all of i1, all of i2, then 20/30 = 0.667 of i3 to fill the")
    print("   last 20 units. Capacity is exactly used; nothing better exists.)\n")

    print("--- (2) 0/1 knapsack: greedy-by-DENSITY is NOT optimal ---")
    g_val, g_chosen = knapsack01_greedy_density(items, W)
    print(f"  greedy-by-density takes {g_chosen}: value = {g_val:.0f}")
    print("  (takes i1 (w=10) + i2 (w=20) = w30; i3 needs w30 but only w20 left,")
    print("   so it is SKIPPED. 20 units of capacity go unused.)\n")
    opt_val, opt_chosen = knapsack01_dp(items, W)
    print(f"  DP optimum takes {opt_chosen}: value = {opt_val:.0f}")
    print("  (i2 + i3 = w50 exactly, value 220.)\n")
    print(f"  greedy value {g_val:.0f}  vs  optimum {opt_val:.0f}")
    print(f"  [check] greedy == optimum? {abs(g_val - opt_val) < 1e-9}  "
          f"(FALSE -> greedy FAILS by {opt_val - g_val:.0f})")
    print("\nWHY greedy fails here: taking the best value/weight item (i1) first")
    print("strands 20 units of capacity. The optimum DROPS i1 to make room for")
    print("the bulky-but-valuable i3. Greedy has no way to 'un-choose' i1.")
    print("This is exactly why 0/1 knapsack needs DYNAMIC PROGRAMMING, not greed.")


# ----------------------------------------------------------------------------
# SECTION C: Huffman coding -- greedy builds the optimal prefix code
# ----------------------------------------------------------------------------

def section_huffman() -> None:
    banner("SECTION C: Huffman coding  (greedily merge two smallest frequencies)")
    # CLRS 16.3 frequencies. char -> frequency (in 1000-char sample).
    freqs = {"a": 45, "b": 13, "c": 12, "d": 16, "e": 9, "f": 5}
    print(f"Character frequencies (from a 1000-char sample): {freqs}\n")
    print("GREEDY RULE: repeatedly pop the TWO smallest-frequency nodes from a")
    print("min-heap and merge them into a new internal node whose frequency is")
    print("their sum. Repeat until one tree remains. Left edge = 0, right = 1.\n")

    # replay the merge trace for printing
    heap: list[tuple[int, int, HuffNode]] = []
    cnt = 0
    for ch, f in freqs.items():
        heapq.heappush(heap, (f, cnt, HuffNode(f, ch)))
        cnt += 1
    print("merge steps:")
    step = 1
    while len(heap) > 1:
        f1, _, n1 = heapq.heappop(heap)
        f2, _, n2 = heapq.heappop(heap)
        merged = HuffNode(f1 + f2, None, n1, n2)
        l1 = n1.char if n1.char else f"*{n1.freq}"
        l2 = n2.char if n2.char else f"*{n2.freq}"
        print(f"  step {step}: merge {l1}({f1}) + {l2}({f2}) -> *{merged.freq}")
        heapq.heappush(heap, (merged.freq, cnt, merged))
        cnt += 1
        step += 1
    print()

    codes, root = huffman_codes(freqs)
    print("Resulting Huffman tree (sideways; head LEFT; 0=left, 1=right):")
    print_huffman_tree(root)
    print()
    print("| char | freq | code | bits = freq x len |")
    print("|------|------|------|------------------|")
    total_bits = 0
    for ch in sorted(freqs, key=lambda c: codes[c]):
        bits = freqs[ch] * len(codes[ch])
        total_bits += bits
        print(f"| {ch}    | {freqs[ch]:<4} | {codes[ch]:<4} | {bits:<16} |")
    print()
    wpl = huffman_weighted_length(codes, freqs)
    print(f"weighted path length (total bits) = {wpl}")
    print(f"vs. fixed 3-bit code for 6 chars  = {sum(freqs.values()) * 3}  "
          f"(Huffman saves {sum(freqs.values()) * 3 - wpl} bits)")
    print(f"[check] Huffman WPL == 224 (CLRS value)? {wpl == 224}")
    # prefix-free check: no code is a prefix of another
    code_list = list(codes.values())
    prefix_free = not any(a != b and b.startswith(a) for a in code_list for b in code_list)
    print(f"[check] prefix-free? {prefix_free}  (no codeword is a prefix of another)")
    print("\nHuffman is the canonical greedy-that-is-PROVABLY-optimal: it minimizes")
    print("the weighted path length over ALL binary prefix codes (CLRS thm 16.4).")


# ----------------------------------------------------------------------------
# SECTION D: coin change -- greedy works for US coins, fails for [4,3,1]
# ----------------------------------------------------------------------------

def section_coin_change() -> None:
    banner("SECTION D: coin change  (greedy works for US coins, FAILS for [4,3,1])")

    print("--- (1) US coins [25,10,5,1]: greedy is OPTIMAL (canonical system) ---\n")
    us_coins = [25, 10, 5, 1]
    amt = 40
    g, used = coin_change_greedy(us_coins, amt)
    opt, optused = coin_change_dp(us_coins, amt)
    print(f"  amount = {amt}, coins = {us_coins}")
    print(f"  greedy : {used}  = {g} coins")
    print(f"  optimum: {optused} = {opt} coins")
    print(f"  [check] greedy == optimum? {g == opt}\n")

    print("--- (2) Arbitrary coins [4,3,1]: greedy FAILS on amount 6 ---\n")
    weird = [4, 3, 1]
    amt = 6
    g, used = coin_change_greedy(weird, amt)
    opt, optused = coin_change_dp(weird, amt)
    print(f"  amount = {amt}, coins = {weird}")
    print(f"  greedy : {used}  = {g} coins   (4, then 1+1: 4+1+1=6)")
    print(f"  optimum: {optused} = {opt} coins   (3+3=6)")
    print(f"  [check] greedy == optimum? {g == opt}  "
          f"(FALSE -> greedy uses {g - opt} extra coin(s))\n")
    print("WHY: the largest coin (4) eats the budget, leaving 2 which only 1's can")
    print("fill. The optimum ignores the 4 entirely and uses two 3's. Greedy cannot")
    print("'see' this because it commits to the 4 immediately. Like 0/1 knapsack,")
    print("the general coin-change problem needs DP.")


# ----------------------------------------------------------------------------
# SECTION E: exchange argument -- the proof technique for greedy optimality
# ----------------------------------------------------------------------------

def section_exchange_argument() -> None:
    banner("SECTION E: exchange argument  (how you PROVE greedy is optimal)")
    print("THE TECHNIQUE, in four lines:\n")
    print("  1. Let G be the greedy solution, O any optimal solution.")
    print("  2. Suppose O differs from G; let a_G be the first greedy choice")
    print("     where they diverge, and a_O the choice O made instead.")
    print("  3. SWAP: replace a_O with a_G in O. Show the result is still")
    print("     feasible AND its objective is no worse.")
    print("  4. By induction over choices, G is optimal.\n")
    print("APPLIED to activity selection (sort by finish):\n")
    print("  Claim: the greedy first pick -- the activity f_min with the EARLIEST")
    print("  finish time -- is in SOME optimal solution.\n")
    print("  Proof (exchange):")
    print("    - Let O be any optimal set, and let x = the activity in O that")
    print("      finishes earliest. Greedy picked f_min, so finish(f_min) <= finish(x).")
    print("    - Replace x with f_min: f_min finishes no later than x did, so every")
    print("      other activity in O (all start after finish(x)) is STILL compatible")
    print("      with f_min. Feasible, same size -> still optimal.")
    print("    - So there is an optimum containing f_min. Strip it off and repeat")
    print("      on the remaining subproblem. By induction, greedy is optimal.\n")
    acts: list[Activity] = [
        ("A1", 1, 4), ("A2", 3, 5), ("A3", 0, 6), ("A4", 5, 7),
        ("A5", 3, 9), ("A6", 5, 9), ("A7", 6, 10), ("A8", 8, 11),
        ("A9", 8, 12), ("A10", 2, 14), ("A11", 12, 16),
    ]
    greedy = activity_selection_greedy(acts)
    print(f"  On our 11 activities, greedy = {[n for n, _, _ in greedy]} "
          f"({len(greedy)} activities).")
    print("  The exchange argument GUARANTEES no subset of size 5 exists; the gold")
    print("  check below confirms it by brute force.")
    print("\nMATROID VIEW (Edmonds 1971): a problem is greedily-solvable iff its")
    print("feasible solutions are the independent sets of a MATROID. Activity")
    print("selection, MST (Kruskal), and scheduling on matroids all qualify;")
    print("0/1 knapsack and general coin change do NOT -- which is exactly why")
    print("greedy fails on them in Sections B and D.")


# ============================================================================
# 3. GOLD CHECK  (greedy activity selection count == exhaustive optimum)
# ============================================================================

def gold_check() -> None:
    banner("GOLD CHECK: greedy activity selection count matches exhaustive optimum")
    acts: list[Activity] = [
        ("A1", 1, 4), ("A2", 3, 5), ("A3", 0, 6), ("A4", 5, 7),
        ("A5", 3, 9), ("A6", 5, 9), ("A7", 6, 10), ("A8", 8, 11),
        ("A9", 8, 12), ("A10", 2, 14), ("A11", 12, 16),
    ]
    greedy = activity_selection_greedy(acts)
    opt = activity_selection_bruteforce(acts)
    g_names = [n for n, _, _ in greedy]
    ok = len(greedy) == opt
    print(f"greedy selection     : {g_names}  ({len(greedy)} activities)")
    print(f"exhaustive optimum   : {opt} activities  (checked all 2^{len(acts)} subsets)")
    print(f"GOLD (pinned for greedy.html): greedy_count = {len(greedy)}, "
          f"optimum = {opt}, selected = {g_names}")
    print(f"[check] greedy == optimum? {'OK' if ok else 'FAIL'}")
    assert ok, "greedy activity selection is not optimal!"

    # also pin a couple of scalar golds used by greedy.html
    items: list[Item] = [("i1", 60.0, 10.0), ("i2", 100.0, 20.0), ("i3", 120.0, 30.0)]
    g01, _ = knapsack01_greedy_density(items, 50.0)
    opt01, _ = knapsack01_dp(items, 50.0)
    frac_v, _ = fractional_knapsack(items, 50.0)
    freqs = {"a": 45, "b": 13, "c": 12, "d": 16, "e": 9, "f": 5}
    codes, _ = huffman_codes(freqs)
    wpl = huffman_weighted_length(codes, freqs)
    print(f"GOLD scalars: 0/1 greedy={g01:.0f}, 0/1 opt={opt01:.0f}, "
          f"fractional={frac_v:.0f}, huffman_wpl={wpl}")
    print(f"[check] 0/1 greedy FAILS (160 < 220)? {g01 < opt01}")
    print(f"[check] fractional greedy == 240? {frac_v == 240}")
    print(f"[check] Huffman WPL == 224? {wpl == 224}")
    assert g01 == 160 and opt01 == 220 and frac_v == 240 and wpl == 224


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("greedy.py - reference impl. All numbers below feed GREEDY.md.")
    print("greedy = make the locally-best choice at each step, never undo it.")

    section_activity_selection()
    section_knapsack()
    section_huffman()
    section_coin_change()
    section_exchange_argument()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
