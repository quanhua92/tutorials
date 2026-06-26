"""
backtracking.py - Reference implementation of Backtracking + Subsets for:
  * Swap-based permutations            (P046 Permutations)
  * Start-index combinations w/ reuse  (P039 Combination Sum)
  * Include/exclude subsets             (P078 Subsets)
  * Digit-to-letter mapping             (P017 Letter Combinations)

This is the SINGLE SOURCE OF TRUTH for BACKTRACKING.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 backtracking.py > backtracking_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - walking a maze, undoing dead ends
============================================================================
Backtracking is structured brute force over a DECISION TREE. At every step
you make a choice (place a queen, pick a number, swap an element into
position), recurse deeper, and - if the branch fails or completes - you
UNDO that exact choice so the next sibling starts from a clean slate.

The entire pattern is the three-line loop body, repeated at every node:

    for choice in choices_at_this_level:
        make(choice)            # CHOOSE   - mutate the shared state
        backtrack(next_state)   # EXPLORE  - recurse one level deeper
        unmake(choice)          # UN-CHOOSE - restore shared state

Every backtracking problem differs in only THREE things:

  1. WHAT the choice is:        swap two indices | append an element |
                                place a letter | drop a queen on a square
  2. WHEN you record a solution: at every node (subsets) | only at leaves
                                (permutations, letter combos) | when a
                                constraint hits zero (combination sum)
  3. HOW you prune:             break when sorted candidate > remaining |
                                skip a square a queen attacks | skip a
                                duplicate at the same tree level

Subsets is NOT a separate pattern - it is backtracking where you record at
EVERY node (not just leaves) and there is no pruning. The "subsets" name
just describes the goal (enumerate the power set); the mechanism is
identical choose -> explore -> un-choose.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  decision tree     the implicit tree of all partial solutions. Each NODE is
                    a partial state (path so far); each EDGE is one choice;
                    each LEAF is either a complete solution or a dead end.
  choose            mutate shared state to commit to a choice
                    (append, swap, mark visited, place a letter).
  explore           recurse one level deeper with the updated state.
  un-choose         undo the mutation EXACTLY (pop, swap back, unmark)
                    so the next sibling iteration sees clean state.
  prune             abandon a branch early because it can never produce a
                    valid solution (candidate > remaining, queen attacked).
  path / current     the mutable partial solution passed down the recursion.
  start index       in combinations/subsets: only consider elements from
                    `start` onward, so each combination is built left-to-right
                    and you never emit the same set twice in different orders.
  reuse             combination-sum allows picking the SAME element again ->
                    recurse with `i` (not `i + 1`).
  base case         when to STOP and record: first == n (permutations),
                    remaining == 0 (combination sum), index == len (letters),
                    every node (subsets).

============================================================================
THE SKELETON (all four variants share the choose -> explore -> un-choose loop)
============================================================================
    def backtrack(state):
        if base_case(state):
            results.append(snapshot(state))     # ALWAYS copy, never alias
            return
        for choice in choices(state):
            choose(choice)                       # mutate state
            backtrack(next(state))               # recurse
            unchoose(choice)                     # restore state (CRITICAL)
"""

from __future__ import annotations


# ============================================================================
# TEMPLATE 1 - PERMUTATIONS via SWAPPING (P046)
# ============================================================================
def permute(nums: list[int]) -> list[list[int]]:
    """Generate all permutations of *nums* (every ordering).

    Swap each unused element into position `first`, recurse to fill the next
    position, then swap back. No `used` set is needed because every index
    < first is already locked in place.

    Time:  O(n * n!)   -- n! leaves, O(n) to copy each
    Space: O(n)         -- recursion depth (output is O(n * n!))
    """
    result: list[list[int]] = []

    def backtrack(first: int = 0) -> None:
        if first == len(nums):              # every position filled
            result.append(nums[:])          # snapshot, NOT a reference
            return
        for i in range(first, len(nums)):
            nums[first], nums[i] = nums[i], nums[first]   # choose (swap)
            backtrack(first + 1)                           # explore
            nums[first], nums[i] = nums[i], nums[first]   # un-choose

    backtrack()
    return result


def trace_permute(nums: list[int]) -> list[dict]:
    """Capture the swap-based decision tree as a flat event list.

    Each event = one step of the choose/explore/un-choose cycle, tagged with
    its recursion depth so the printer (and the HTML viz) can indent it.
    """
    events: list[dict] = []
    work = nums[:]

    def backtrack(first: int, depth: int) -> None:
        if first == len(work):
            events.append({
                "depth": depth, "kind": "found", "path": work[:],
                "note": f"first={first}==n  ->  record {work[:]}",
            })
            return
        for i in range(first, len(work)):
            before = work[:]
            work[first], work[i] = work[i], work[first]
            events.append({
                "depth": depth, "kind": "pick", "path": work[:],
                "first": first, "i": i,
                "note": f"swap({first},{i})  {before} -> {work[:]}",
            })
            backtrack(first + 1, depth + 1)
            work[first], work[i] = work[i], work[first]
            events.append({
                "depth": depth, "kind": "back", "path": work[:],
                "note": f"undo swap({first},{i})  -> {work[:]}",
            })

    backtrack(0, 0)
    return events


# ============================================================================
# TEMPLATE 2 - COMBINATION SUM with REUSE + PRUNING (P039)
# ============================================================================
def combination_sum(candidates: list[int], target: int) -> list[list[int]]:
    """All unique combos of *candidates* (unlimited reuse) summing to *target*.

    Sort first so the loop can `break` the moment a candidate exceeds the
    remaining budget - every later candidate is >= and thus also too big.

    Time:  O(2^t) worst case, t = target / min(candidates)
    Space: O(target / min(candidates)) recursion depth
    """
    result: list[list[int]] = []
    cands = sorted(candidates)

    def backtrack(start: int, remaining: int, path: list[int]) -> None:
        if remaining == 0:
            result.append(path[:])
            return
        for i in range(start, len(cands)):
            if cands[i] > remaining:
                break                                  # sorted -> prune rest
            path.append(cands[i])                      # choose
            backtrack(i, remaining - cands[i], path)   # i (not i+1): reuse OK
            path.pop()                                 # un-choose

    backtrack(0, target, [])
    return result


def trace_combination_sum(candidates: list[int], target: int) -> list[dict]:
    events: list[dict] = []
    cands = sorted(candidates)

    def backtrack(start: int, remaining: int, path: list[int], depth: int) -> None:
        for i in range(start, len(cands)):
            if cands[i] > remaining:
                events.append({
                    "depth": depth, "kind": "prune", "path": path[:],
                    "note": f"cands[{i}]={cands[i]} > rem={remaining}  ->  break (rest pruned)",
                })
                break
            path.append(cands[i])
            events.append({
                "depth": depth, "kind": "pick", "path": path[:],
                "note": f"pick {cands[i]}  rem {remaining}->{remaining - cands[i]}  path={path[:]}",
            })
            if remaining - cands[i] == 0:
                events.append({
                    "depth": depth + 1, "kind": "found", "path": path[:],
                    "note": f"rem==0  ->  record {path[:]}",
                })
            backtrack(i, remaining - cands[i], path, depth + 1)
            popped = path.pop()
            events.append({
                "depth": depth, "kind": "back", "path": path[:],
                "note": f"pop {popped}  ->  path={path[:]}",
            })

    backtrack(0, target, [], 0)
    return events


# ============================================================================
# TEMPLATE 3 - SUBSETS / POWER SET (P078)
# ============================================================================
def subsets(nums: list[int]) -> list[list[int]]:
    """All 2^n subsets of *nums* (the power set).

    Unlike permutations/letters, you record at EVERY node (not just leaves):
    every prefix of the path is itself a valid subset. The `start` index
    walks strictly forward so each subset is emitted exactly once.

    Time:  O(n * 2^n)   -- 2^n subsets, O(n) to copy each
    Space: O(n)          -- recursion depth
    """
    result: list[list[int]] = []

    def backtrack(start: int, path: list[int]) -> None:
        result.append(path[:])                 # record EVERY node
        for i in range(start, len(nums)):
            path.append(nums[i])               # choose
            backtrack(i + 1, path)             # i+1: move forward, no reuse
            path.pop()                         # un-choose

    backtrack(0, [])
    return result


def trace_subsets(nums: list[int]) -> list[dict]:
    events: list[dict] = []

    def backtrack(start: int, path: list[int], depth: int) -> None:
        events.append({
            "depth": depth, "kind": "record", "path": path[:],
            "note": f"record {path[:]}  (every node, not just leaves)",
        })
        for i in range(start, len(nums)):
            path.append(nums[i])
            events.append({
                "depth": depth, "kind": "pick", "path": path[:],
                "note": f"+{nums[i]}  -> {path[:]}",
            })
            backtrack(i + 1, path, depth + 1)
            path.pop()
            events.append({
                "depth": depth, "kind": "back", "path": path[:],
                "note": f"pop {nums[i]}  -> {path[:]}",
            })

    backtrack(0, [], 0)
    return events


# ============================================================================
# TEMPLATE 4 - LETTER COMBINATIONS of a PHONE NUMBER (P017)
# ============================================================================
LETTER_MAP: dict[str, str] = {
    "2": "abc", "3": "def",  "4": "ghi", "5": "jkl",
    "6": "mno", "7": "pqrs", "8": "tuv", "9": "wxyz",
}


def letter_combinations(digits: str) -> list[str]:
    """All strings formed by pressing one letter from each digit's key.

    Classic backtracking: one recursion level per digit; at each level try
    every letter on that key. Base case: index == len(digits).

    Time:  O(4^n * n)   worst case all digits are 7 or 9 (4 letters)
    Space: O(n)          recursion depth
    """
    if not digits:
        return []
    result: list[str] = []

    def backtrack(index: int, current: list[str]) -> None:
        if index == len(digits):
            result.append("".join(current))
            return
        for ch in LETTER_MAP[digits[index]]:
            current.append(ch)                 # choose
            backtrack(index + 1, current)      # explore next digit
            current.pop()                      # un-choose

    backtrack(0, [])
    return result


def trace_letter_combinations(digits: str) -> list[dict]:
    events: list[dict] = []

    def backtrack(index: int, current: list[str], depth: int) -> None:
        if index == len(digits):
            events.append({
                "depth": depth, "kind": "found", "path": "".join(current),
                "note": f"index=={len(digits)}  ->  record '{''.join(current)}'",
            })
            return
        digit = digits[index]
        for ch in LETTER_MAP[digit]:
            current.append(ch)
            events.append({
                "depth": depth, "kind": "pick", "path": "".join(current),
                "note": f"digit '{digit}' -> '{ch}'   cur='{''.join(current)}'",
            })
            backtrack(index + 1, current, depth + 1)
            current.pop()
            events.append({
                "depth": depth, "kind": "back", "path": "".join(current),
                "note": f"pop '{ch}'   -> cur='{''.join(current)}'",
            })

    if digits:
        backtrack(0, [], 0)
    return events


# ============================================================================
# EVENT PRINTER (shared by all sections - renders the decision tree)
# ============================================================================
_KIND_MARKER = {
    "pick":   "[+]",   # choose
    "back":   "[-]",   # un-choose
    "found":  "[=]",   # recorded a solution
    "prune":  "[x]",   # branch cut
    "record": "[*]",   # subsets: record at every node
}


def print_events(events: list[dict]) -> None:
    """Render the decision tree as an indented event stream."""
    for e in events:
        indent = "    " * e["depth"]
        marker = _KIND_MARKER.get(e["kind"], "[?]")
        print(f"  {indent}{marker} {e['note']}")


def summarize_events(events: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


# ============================================================================
# SECTION A - P046 PERMUTATIONS (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P046 Permutations  (swap-based, choose -> explore -> undo)")
    print("=" * 72)
    print()
    nums = [1, 2, 3]
    print(f"nums = {nums}   (want every ordering; expect 3! = 6 permutations)")
    print()
    print("Mechanism: for position `first`, swap each index i >= first into it,")
    print("recurse to fill position first+1, then swap back to restore order.")
    print("Indices < first are locked; no `used` set needed.")
    print()
    print("Decision tree (swap events, indented by recursion depth):")
    print()
    events = trace_permute(nums)
    print_events(events)
    print()
    counts = summarize_events(events)
    print(f"  tree stats: {counts['pick']} chooses, "
          f"{counts['found']} recorded, {counts['back']} undos")
    print(f"  => each of the {counts['found']} leaves is one permutation")
    print()
    result = permute(nums)
    print(f"permute({nums}) -> {result}")
    print(f"  count = {len(result)} = 3!  (expected 6)")
    print()
    print("--- edge cases ---")
    print(f"  permute([0, 1]) -> {permute([0, 1])}    (2! = 2)")
    print(f"  permute([1])    -> {permute([1])}       (1! = 1, single element)")
    print(f"  permute([1, 1]) -> {permute([1, 1][:])}  "
          f"(swap approach treats equal values as distinct positions)")
    print()


# ============================================================================
# SECTION B - P039 COMBINATION SUM (worked example, shows pruning)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P039 Combination Sum  (reuse allowed + sorted-break pruning)")
    print("=" * 72)
    print()
    candidates = [2, 3, 6, 7]
    target = 7
    print(f"candidates = {candidates}   target = {target}   (unlimited reuse)")
    print()
    print("Two tricks that make this backtracking instead of brute force:")
    print("  1. SORT first  -> enables the `break` prune (step 2)")
    print("  2. break when cands[i] > remaining  -> every later candidate is")
    print("     also too big, so the whole rest of this loop is dead.")
    print("  3. recurse with `i` (NOT i+1)  -> the same candidate may be picked")
    print("     again on the next level (that is what 'reuse' means).")
    print()
    print("Decision tree (pick / found / prune / pop, indented by depth):")
    print()
    events = trace_combination_sum(candidates, target)
    print_events(events)
    print()
    counts = summarize_events(events)
    prunes = counts.get("prune", 0)
    print(f"  tree stats: {counts['pick']} chooses, {counts['found']} recorded, "
          f"{prunes} prunes, {counts['back']} undos")
    print(f"  => {prunes} branches cut early by the sorted-break (no wasted recursion)")
    print()
    result = combination_sum(candidates, target)
    print(f"combination_sum({candidates}, {target}) -> {result}")
    print()
    print("--- edge cases ---")
    print(f"  combination_sum([2, 3, 5], 8) -> {combination_sum([2, 3, 5], 8)}")
    print(f"  combination_sum([2], 1)        -> {combination_sum([2], 1)}    "
          f"(no candidate <= 1, empty)")
    print(f"  combination_sum([], 1)         -> {combination_sum([], 1)}    "
          f"(no candidates, empty)")
    print()


# ============================================================================
# SECTION C - P078 SUBSETS (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P078 Subsets  (power set; record at EVERY node)")
    print("=" * 72)
    print()
    nums = [1, 2, 3]
    print(f"nums = {nums}   (want all 2^3 = 8 subsets)")
    print()
    print("Subsets IS backtracking with two relaxations:")
    print("  * record at EVERY node (not just leaves) - each prefix is a subset")
    print("  * no pruning - we want everything, so no branch is ever cut")
    print("The `start` index walks forward (i+1) so each subset is emitted once")
    print("and we never reuse an element within one subset.")
    print()
    print("Decision tree (record at entry, then +element / pop to backtrack):")
    print()
    events = trace_subsets(nums)
    print_events(events)
    print()
    counts = summarize_events(events)
    print(f"  tree stats: {counts['record']} records (= #subsets), "
          f"{counts['pick']} chooses, {counts['back']} undos")
    print(f"  => {counts['record']} subsets = 2^{len(nums)} (including the empty set)")
    print()
    result = subsets(nums)
    print(f"subsets({nums}) -> {result}")
    print(f"  count = {len(result)} = 2^{len(nums)} (expected 8)")
    print()
    print("--- edge cases ---")
    print(f"  subsets([0])  -> {subsets([0])}        (2^1 = 2)")
    print(f"  subsets([])   -> {subsets([])}        (2^0 = 1, just the empty set)")
    print()


# ============================================================================
# SECTION D - P017 LETTER COMBINATIONS (worked example)
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - P017 Letter Combinations of a Phone Number")
    print("=" * 72)
    print()
    digits = "23"
    print(f'digits = "{digits}"   (2->abc, 3->def; expect 3 x 3 = 9 strings)')
    print()
    print("One recursion level per digit. At each level, loop over every letter")
    print("on that key, append it, recurse to the next digit, pop it.")
    print("Base case: index == len(digits) -> join and record.")
    print()
    print("key map: " + ", ".join(f"{k}->{v}" for k, v in LETTER_MAP.items()))
    print()
    print("Decision tree (one letter per level, leaves are the 9 strings):")
    print()
    events = trace_letter_combinations(digits)
    print_events(events)
    print()
    counts = summarize_events(events)
    print(f"  tree stats: {counts['pick']} chooses, {counts['found']} recorded, "
          f"{counts['back']} undos")
    print(f"  => {counts['found']} leaves = 3 x 3 (digits 2 and 3 each have 3 letters)")
    print()
    result = letter_combinations(digits)
    print(f'letter_combinations("{digits}") -> {result}')
    print()
    print("--- edge cases ---")
    empty = letter_combinations("")
    two = letter_combinations("2")
    seven = letter_combinations("7")
    print(f'  letter_combinations("")  -> {empty}     '
          f"(empty input -> empty list, NOT [''])")
    print(f'  letter_combinations("2") -> {two}     (single digit)')
    print(f'  letter_combinations("7") -> {seven} '
          f'(digit 7 has 4 letters: pqrs)')
    print()


# ============================================================================
# SECTION E - COMPLEXITY, GOTCHAS, PROBLEM TABLE
# ============================================================================
def section_e() -> None:
    print("=" * 72)
    print("SECTION E - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Operation                          Time          Space")
    print("  ---------------------------------- ------------- --------")
    print("  Permutations, swap-based  (P046)   O(n * n!)     O(n)")
    print("  Combination Sum, reuse     (P039)  O(2^t) worst  O(t/min)")
    print("  Subsets / power set        (P078)  O(n * 2^n)    O(n)")
    print("  Letter combinations        (P017)  O(4^n * n)    O(n)")
    print("  Combinations C(n,k)        (P077)  O(C(n,k) * k) O(k)")
    print("  N-Queens                          O(n!)         O(n)")
    print()
    print("  n = input size; t = target / min(candidates). All are exponential -")
    print("  the goal of backtracking is to PRUNE, not to avoid exponential.")
    print()
    print("The universal skeleton (memorize the loop body)")
    print("-----------------------------------------------")
    print("  def backtrack(state):")
    print("      if base_case(state):")
    print("          results.append(state[:])   # COPY, never alias")
    print("          return")
    print("      for choice in choices(state):")
    print("          choose(choice)             # mutate shared state")
    print("          backtrack(next(state))     # explore one level deeper")
    print("          unchoose(choice)           # restore (CRITICAL)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. ALIASING: results.append(path) stores a REFERENCE. Later .pop()")
    print("     mutates every entry. ALWAYS append a copy: path[:] or ''.join.")
    print("  2. MISSING UNDO: forget path.pop() and choices leak into sibling")
    print("     branches, corrupting the whole search. Every choose needs a")
    print("     matching unchoose, paired like malloc/free.")
    print("  3. WRONG START INDEX: combinations/subsets recurse with i+1 (move")
    print("     forward, no reuse). Combination Sum recurses with i (same element")
    print("     may be picked again). Swapping them yields duplicates or misses.")
    print("  4. PRUNING UNSORTED INPUT: `break when cands[i] > remaining` only")
    print("     works after sorting. On unsorted input a smaller valid number")
    print("     may appear later and you would skip it. SORT FIRST.")
    print("  5. DUPLICATES (P090 Subsets II): to skip duplicate subsets, SORT then")
    print("     add `if i > start and nums[i] == nums[i-1]: continue`. The i>start")
    print("     guard dedupes siblings at one tree level but allows the same value")
    print("     deeper down a single branch.")
    print("  6. SUBSETS vs COMBINATIONS: subsets records at EVERY node; combinations")
    print("     records ONLY when len(path) == k. Same skeleton, different base case.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                       Diff  Key trick")
    print("  ----------------------------- ----  ----------------------------------------")
    print("  P046 Permutations             Med   swap each i>=first into place; undo swap")
    print("  P039 Combination Sum          Med   sort + break prune; recurse with i (reuse)")
    print("  P078 Subsets                  Med   record at every node; start=i+1 walks forward")
    print("  P017 Letter Combinations      Med   one level per digit; loop letters on the key")
    print("  P077 Combinations             Med   like subsets but record only at len==k")
    print("  P090 Subsets II               Med   sort + i>start dedup skips duplicate siblings")
    print("  P040 Combination Sum II       Med   sort + i>start dedup; each number used once")
    print("  P047 Permutations II          Med   sort + i>0 and used[i-1] guard")
    print("  P051 N-Queens                 Hard  place row by row; prune cols + both diagonals")
    print("  P037 Sudoku Solver            Hard  try 1-9 per empty cell; prune row/col/box")
    print("  P079 Word Search              Med   DFS 4 dirs; mark cell visited, unmark on undo")
    print("  P131 Palindrome Partitioning  Med   backtrack cut points; check palindrome prefix")
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

    # ---- assertions (mirror LeetCode canonical test cases) ----
    # P046 Permutations
    assert permute([1, 2, 3]) == [[1, 2, 3], [1, 3, 2], [2, 1, 3],
                                  [2, 3, 1], [3, 2, 1], [3, 1, 2]]
    assert permute([0, 1]) == [[0, 1], [1, 0]]
    assert permute([1]) == [[1]]

    # P039 Combination Sum (unlimited reuse)
    assert combination_sum([2, 3, 6, 7], 7) == [[2, 2, 3], [7]]
    assert combination_sum([2, 3, 5], 8) == [[2, 2, 2, 2], [2, 3, 3], [3, 5]]
    assert combination_sum([2], 1) == []
    assert combination_sum([], 1) == []

    # P078 Subsets (power set, unique elements)
    assert subsets([1, 2, 3]) == [[], [1], [1, 2], [1, 2, 3], [1, 3], [2], [2, 3], [3]]
    assert subsets([0]) == [[], [0]]
    assert subsets([]) == [[]]

    # P017 Letter Combinations of a Phone Number
    assert letter_combinations("23") == ["ad", "ae", "af", "bd", "be", "bf",
                                         "cd", "ce", "cf"]
    assert letter_combinations("") == []
    assert letter_combinations("2") == ["a", "b", "c"]

    # ---- cross-check: permutation count is n! for small n ----
    def fact(n: int) -> int:
        r = 1
        for i in range(2, n + 1):
            r *= i
        return r
    for n in range(1, 7):
        assert len(permute(list(range(n)))) == fact(n)

    # ---- cross-check: subset count is 2^n ----
    for n in range(0, 9):
        assert len(subsets(list(range(1, n + 1)))) == 2 ** n

    print("=" * 72)
    print("[check] permute / combination_sum / subsets / letter_combinations ... OK")
    print("=" * 72)
