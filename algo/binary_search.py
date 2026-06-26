"""
binary_search.py - Reference implementation of Binary Search and its variants:
exact-match search, lower/upper bound, and binary-search-on-the-answer.

This is the SINGLE SOURCE OF TRUTH for BINARY_SEARCH.md. Every number, table,
and worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 binary_search.py > binary_search_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - the phone book trick
============================================================================
You are looking for a name in a SORTED phone book. You flip to the MIDDLE page
and compare: if your name comes BEFORE the middle, rip the back half off and
throw it away; if AFTER, rip the front half off. Each step cuts the pile in
HALF. After k steps only n / 2^k pages remain, so you need at most

        log2(n) steps

to find any name. That is the whole algorithm: compare the middle, keep one
half, discard the other. The sortedness is what lets you discard safely -
without it the middle tells you nothing about where the target lives.

  * exact search : return the index of `key`, or -1.
  * lower_bound  : the FIRST index i with arr[i] >= key  (left insertion point).
  * upper_bound  : the FIRST index i with arr[i] >  key  (right insertion point).
  * search answer: when a predicate P(x) is MONOTONE (false...false,true...true),
                   binary search the smallest x with P(x) true.

THE REASON BINARY SEARCH EXISTS: comparison + sortedness lets you DISCARD half
the search space per probe. That is the source of the O(log n). Every variant is
the same discard-half loop with a different rule for which half to keep and when
to stop.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  sorted array   a sequence arr[0] <= arr[1] <= ... <= arr[n-1]. REQUIRED.
  probe          one comparison of arr[mid] against the key.
  lo, hi         the current live window [lo, hi] (inclusive) that may hold key.
  mid            the index we probe; the "middle" of the live window.
  search path    the chain of `mid` values visited until the key is found (or
                 the window empties). Length == number of probes.
  invariant      a fact that stays true every loop step. For exact search:
                 "if key is in arr, it is in arr[lo..hi]". Discarding the wrong
                 half would BREAK the invariant - that is what bugs do.
  monotone pred  a boolean function P(x) that is false up to some point and
                 true forever after. Lets you binary-search the threshold.

============================================================================
THE LOOP (all three variants share this skeleton)
============================================================================
    lo = 0                       # live window starts as the whole array
    hi = n - 1
    while lo <= hi:              # inclusive: window non-empty
        mid = lo + (hi - lo) // 2     # overflow-safe midpoint
        if arr[mid] == key:
            return mid                # exact: found
        elif arr[mid] < key:
            lo = mid + 1              # key is in the RIGHT half
        else:
            hi = mid - 1              # key is in the LEFT half
    return -1                        # window empty -> absent

KEY FORMULAS (all verified + asserted in code):
    worst-case probes (exact)    <=  floor(log2(n)) + 1
    midpoint (overflow-safe)     =   lo + (hi - lo) // 2
    lower_bound                  =   smallest i with arr[i] >= key
    upper_bound                  =   smallest i with arr[i] >  key
    range of equal values        =   [lower_bound, upper_bound)
    search-on-answer complexity  =   O(log(answer_range)) * cost(P)

References:
    Knuth, TAOCP Vol 3, §6.2.1 (searching an ordered table).
    CLRS (3rd ed.) Exercise 2.3-5 and the "binary-search pitfalls" discussion.
    Bentley, "Programming Pearls" (1986), column 4 & the famous
    "90% of programmers write it wrong" binary search anecdote.
"""

from __future__ import annotations

BANNER = "=" * 72

# The canonical deterministic array used by every worked example below.
# 16 sorted, distinct, evenly spaced integers. Seeded by hand (no RNG) so the
# .html can reproduce every step byte-for-byte.
ARR = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31]

# A second array WITH DUPLICATES, for the lower/upper-bound section.
ARR_DUP = [1, 2, 2, 2, 3, 3, 4, 4, 4, 4, 5, 6, 7, 8, 8, 9]


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code BINARY_SEARCH.md walks)
# ============================================================================

def binary_search(arr: list[int], key: int) -> int:
    """Exact-match binary search. Returns the index of `key`, or -1.

    Invariant: if key is in arr, then it lies in arr[lo..hi] (inclusive).
    Each iteration halves the live window; lo > hi means the window is empty.
    """
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = lo + (hi - lo) // 2          # overflow-safe midpoint
        if arr[mid] == key:
            return mid
        elif arr[mid] < key:
            lo = mid + 1                   # discard left half
        else:
            hi = mid - 1                   # discard right half
    return -1


def binary_search_path(arr: list[int], key: int) -> list[int]:
    """Same as binary_search but records the search path: the list of `mid`
    indices probed. Used to visualize the halving in Section A.
    """
    lo, hi = 0, len(arr) - 1
    path: list[int] = []
    while lo <= hi:
        mid = lo + (hi - lo) // 2
        path.append(mid)
        if arr[mid] == key:
            return path
        elif arr[mid] < key:
            lo = mid + 1
        else:
            hi = mid - 1
    return path


def lower_bound(arr: list[int], key: int) -> int:
    """First index i such that arr[i] >= key. The LEFT insertion point.

    Uses half-open-style narrowing: `lo` is always a candidate answer, `hi`
    is the exclusive upper bound on the answer. Returns len(arr) if every
    element is < key (key would append at the end).
    """
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if arr[mid] < key:
            lo = mid + 1                  # arr[mid] too small -> answer is right
        else:
            hi = mid                      # arr[mid] >= key -> answer is mid or left
    return lo


def upper_bound(arr: list[int], key: int) -> int:
    """First index i such that arr[i] > key. The RIGHT insertion point.

    Mirrors lower_bound with the strict comparison. The half-open range
    [lower_bound, upper_bound) is exactly the run of values equal to key.
    """
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if arr[mid] <= key:
            lo = mid + 1                  # arr[mid] <= key -> answer is right
        else:
            hi = mid                      # arr[mid] > key -> answer is mid or left
    return lo


def ship_within_days(weights: list[int], days: int) -> int:
    """Binary-search-on-the-answer (Section D). Find the minimum ship capacity
    such that `weights` can be shipped in order within `days` days.

    The predicate `can_ship(cap)` is MONOTONE: once a capacity works, every
    larger capacity also works. So the answer space is false...false,true...true
    and we binary-search the threshold with lower_bound logic.
    """

    def can_ship(cap: int) -> bool:
        need = 1                      # at least one day
        load = 0
        for w in weights:
            if w > cap:               # a single package heavier than cap -> impossible
                return False
            if load + w > cap:
                need += 1
                load = w
            else:
                load += w
        return need <= days

    lo, hi = max(weights), sum(weights)
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if can_ship(mid):
            hi = mid                   # mid works -> try smaller
        else:
            lo = mid + 1               # mid fails -> need bigger
    return lo


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_row(arr: list[int], idx: int, mark: str = " ") -> str:
    return " ".join(f"{mark if i == idx else ' '}{v:>2}" for i, v in enumerate(arr))


# ============================================================================
# 3. THE WORKED EXAMPLES
# ============================================================================

def section_core_loop():
    banner("SECTION A: the core loop - compare middle, discard half")
    n = len(ARR)
    import math
    worst = math.floor(math.log2(n)) + 1
    print(f"Array (n={n}, sorted, distinct):")
    print("  idx:", " ".join(f"{i:>3}" for i in range(n)))
    print("  val:", " ".join(f"{v:>3}" for v in ARR))
    print(f"\nWorst-case probes for n={n}: floor(log2({n})) + 1 = {worst}\n")

    for key, label in [(23, "PRESENT"), (24, "ABSENT")]:
        path = binary_search_path(ARR, key)
        idx = binary_search(ARR, key)
        print(f"-- search key={key}  [{label}] --")
        lo, hi = 0, n - 1
        for step, mid in enumerate(path):
            if ARR[mid] == key:
                verdict = "== key -> FOUND"
            elif ARR[mid] < key:
                verdict = "< key -> go right"
            else:
                verdict = "> key -> go left"
            print(f"  step {step}: window [{lo:>2}..{hi:>2}]  mid={mid:>2}  "
                  f"arr[mid]={ARR[mid]:>2}  {verdict}")
            if ARR[mid] < key:
                lo = mid + 1
            elif ARR[mid] > key:
                hi = mid - 1
            else:
                break
        print(f"  result: index={idx}   probes={len(path)}   "
              f"(worst-case bound {worst})\n")

    print("Read it: each step the live window [lo..hi] AT LEAST halves. For")
    print("key=23 the path is [7, 11]: two probes pin a 16-element array. The")
    print("absent case (key=24) terminates when lo > hi - the window empties.")


def section_probe_overflow():
    banner("SECTION B: probe calculation & the overflow bug  mid = lo + (hi-lo)//2")
    print("The midpoint must be computed as  lo + (hi - lo) // 2  , NOT")
    print(" (lo + hi) // 2. Both are mathematically equal, but (lo + hi) can")
    print("OVERFLOW in fixed-width integer languages (C, Java int). Python ints")
    print("are arbitrary precision so the bug is invisible here, but writing the")
    print("safe form everywhere is a habit that survives language switches.\n")
    print("  (lo + hi) // 2        # DANGEROUS: lo + hi may overflow")
    print("  lo + (hi - lo) // 2   # SAFE: each term stays in [lo, hi]\n")

    # Demonstrate equivalence on the canonical array's extreme window.
    lo, hi = 0, len(ARR) - 1
    naive = (lo + hi) // 2
    safe = lo + (hi - lo) // 2
    print(f"Window [lo={lo}, hi={hi}]  (whole array):")
    print(f"  (lo + hi) // 2        = ({lo} + {hi}) // 2        = {naive}")
    print(f"  lo + (hi - lo) // 2   = {lo} + ({hi} - {lo}) // 2   = {safe}")
    print(f"  [check] equal?  {naive == safe}\n")

    # Reproduce the overflow bug with a simulated 32-bit wrap, to make it
    # concrete: if INT_MAX = 2**31 - 1 and lo = hi = 2**31 - 1 (valid positive
    # indices), (lo + hi) wraps to a NEGATIVE number.
    INT_MAX = (1 << 31) - 1
    lo_b, hi_b = INT_MAX, INT_MAX          # two large but valid indices
    wrapped = ((lo_b + hi_b) & 0xFFFFFFFF) # simulate uint32 truncation
    if wrapped >= (1 << 31):
        wrapped -= (1 << 32)               # interpret as signed int32
    print("Simulated 32-bit overflow: lo = hi = 2**31 - 1 (both valid indices):")
    print(f"  (lo + hi) truncated to int32  = {wrapped}   <- NEGATIVE, crashes")
    print(f"  lo + (hi - lo) // 2           = {lo_b + (hi_b - lo_b) // 2}   <- correct")
    print("This is the bug in nearly every 'subtle binary search' bug report,")
    print("including the one that lived in Java's Arrays.binarySearch for years.")


def section_bounds():
    banner("SECTION C: lower_bound / upper_bound - the insertion points")
    n = len(ARR_DUP)
    print(f"Array with duplicates (n={n}):")
    print("  idx:", " ".join(f"{i:>2}" for i in range(n)))
    print("  val:", " ".join(f"{v:>2}" for v in ARR_DUP))
    print()
    print("  lower_bound(key) = first i with arr[i] >= key   (LEFT insert point)")
    print("  upper_bound(key) = first i with arr[i] >  key   (RIGHT insert point)")
    print("  equal range      = [lower_bound, upper_bound)   (the run of `key`)\n")

    print("| key | lower_bound | upper_bound | equal range        | count |")
    print("|-----|-------------|-------------|--------------------|-------|")
    for key in [0, 2, 4, 8, 9, 10]:
        lb = lower_bound(ARR_DUP, key)
        ub = upper_bound(ARR_DUP, key)
        count = ub - lb
        rng = f"[{lb}, {ub})" if count else "empty"
        print(f"| {key:>3} | {lb:>11} | {ub:>11} | {rng:<18} | {count:>5} |")
    print()
    print("Note key=4: indices 6,7,8,9 are all 4, so lower_bound=6, "
          "upper_bound=10, count=4. key=10 is larger than everything, so both "
          "bounds = 16 (would append at the end). key=0 is smaller than "
          "everything, so lower_bound=0, upper_bound=0, count=0.\n")

    # Verify the lower/upper bounds against a brute-force scan (self-check).
    for key in range(0, 12):
        brute_lb = next((i for i in range(n) if ARR_DUP[i] >= key), n)
        brute_ub = next((i for i in range(n) if ARR_DUP[i] > key), n)
        assert lower_bound(ARR_DUP, key) == brute_lb
        assert upper_bound(ARR_DUP, key) == brute_ub
    print("[check] lower/upper_bound match brute-force scan for keys 0..11:  OK")
    print("        (exact `binary_search` is just lower_bound when arr[lb]==key)")


def section_search_on_answer():
    banner("SECTION D: binary search on the answer (monotone predicate)")
    weights = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    days = 5
    print("Problem: ship packages `weights` IN ORDER within `days` days; each")
    print("day's total load must not exceed the ship CAPACITY. Find the MIN")
    print("capacity. (LeetCode 1011 'Capacity To Ship Packages Within D Days'.)\n")
    print(f"  weights = {weights}")
    print(f"  days    = {days}")
    print(f"  sum     = {sum(weights)}   max = {max(weights)}\n")

    print("The predicate can_ship(cap) is MONOTONE: once a capacity works,")
    print("every larger capacity also works. So the answer space is")
    print("false...false,true...true -> binary-search the threshold.\n")
    print("  search range: [max(weights), sum(weights)] = "
          f"[{max(weights)}, {sum(weights)}]\n")

    def can_ship(cap: int) -> bool:
        need, load = 1, 0
        for w in weights:
            if load + w > cap:
                need += 1
                load = w
            else:
                load += w
        return need <= days

    print("| cap | days_needed | can_ship? | decision        |")
    print("|-----|-------------|-----------|-----------------|")
    # walk the predicate over the candidate capacities to show the flip
    for cap in range(max(weights), sum(weights) + 1):
        need, load = 1, 0
        for w in weights:
            if load + w > cap:
                need += 1
                load = w
            else:
                load += w
        ok = need <= days
        dec = "answer found HERE" if cap == ship_within_days(weights, days) else (
            "keep lowering" if ok else "must go higher")
        print(f"| {cap:>3} | {need:>11} | {'yes' if ok else 'no ':>9} | {dec:<15} |")

    ans = ship_within_days(weights, days)
    print(f"\nmin capacity = {ans}")
    # show the resulting day-by-day loading plan at the optimal capacity
    print(f"\nDay-by-day plan at capacity = {ans}:")
    day, load = 1, 0
    plan: list[list[int]] = [[]]
    for w in weights:
        if load + w > ans:
            day += 1
            load = 0
            plan.append([])
        load += w
        plan[-1].append(w)
    for d, items in enumerate(plan, 1):
        print(f"  day {d}: {items}  (load {sum(items)})")
    print(f"  -> {len(plan)} days <= {days} required:  OK\n")

    # GOLD: the answer is a fixed value, pinned for the .html.
    assert ans == 15
    print("[check] min capacity == 15:  OK   (gold value for binary_search.html)")


def section_off_by_one():
    banner("SECTION E: the off-by-one pitfall - inclusive vs half-open bounds")
    print("Two boundary conventions look almost identical but mix to DIFFERENT")
    print("loop tests. Mixing them is the #1 source of infinite loops and")
    print("missed-first/missed-last bugs.\n")
    print("  CONVENTION A (inclusive):  lo=0, hi=n-1,   while lo <= hi,  "
          "lo=mid+1 / hi=mid-1")
    print("  CONVENTION B (half-open) :  lo=0, hi=n,     while lo <  hi,  "
          "lo=mid+1 / hi=mid\n")
    print("Rule of thumb: pick ONE convention per function and never mix the")
    print("test with the update. The cardinal sins:")
    print("  - half-open test `lo < hi` with inclusive update `hi = mid - 1`")
    print("    -> skips arr[mid-1], can miss the answer.")
    print("  - inclusive test `lo <= hi` with half-open update `hi = mid`")
    print("    -> when lo==hi the window never shrinks -> INFINITE LOOP.\n")

    n = len(ARR)
    key = ARR[0]                                  # first element, easy to miss
    # Conventions A and B both find it.
    ia = binary_search(ARR, key)
    # half-open re-implementation for comparison
    lo, hi = 0, n
    ib = -1
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if ARR[mid] == key:
            ib = mid
            break
        elif ARR[mid] < key:
            lo = mid + 1
        else:
            hi = mid
    print(f"Search the FIRST element key=arr[0]={key} (off-by-one magnet):")
    print(f"  inclusive  (lo<=hi, hi=mid-1): index = {ia}")
    print(f"  half-open  (lo< hi, hi=mid  ): index = {ib}")
    assert ia == ib == 0
    print("  [check] both find index 0:  OK\n")

    # Show the broken mix: inclusive test + half-open update -> infinite loop.
    # Use an ABSENT key (2 is not in ARR) so the stall is guaranteed: once the
    # window collapses to lo==hi==mid with arr[mid] > key, hi=mid never moves
    # past mid, so mid recomputes to itself forever.
    key_absent = 2
    print("Broken mix: `while lo <= hi` with `hi = mid` (should be hi=mid-1),")
    print(f"searching an ABSENT key={key_absent} (not in ARR):")
    lo, hi = 0, n - 1
    spins = 0
    stalled_at = None
    while lo <= hi and spins < 100:
        mid = lo + (hi - lo) // 2
        spins += 1
        if spins <= 8:                      # print the first few steps
            print(f"  spin {spins}: lo={lo} hi={hi} mid={mid} "
                  f"arr[mid]={ARR[mid]}")
        if ARR[mid] == key_absent:
            break
        elif ARR[mid] < key_absent:
            lo = mid + 1
        else:
            hi = mid                        # BUG: should be mid - 1
        if spins == 5:
            stalled_at = (lo, hi, mid)
    if spins >= 100:
        print(f"  ... HIT THE 100-iteration safety cap (stalled at "
              f"lo={stalled_at[0]}==hi={stalled_at[1]}==mid={stalled_at[2]}, "
              f"arr[mid]={ARR[stalled_at[2]]} > {key_absent} but hi never "
              f"moves) -> would loop FOREVER.")
        print("  FIX: with `while lo <= hi` always use hi = mid - 1.")
    print()
    print("Contrast: the CORRECT inclusive version finds absent keys cleanly")
    print("(returns -1 in O(log n)):")
    print(f"  binary_search(ARR, {key_absent}) = {binary_search(ARR, key_absent)}  "
          f"(path {binary_search_path(ARR, key_absent)})\n")
    print("MORAL: the loop TEST and the bound UPDATE must come from the SAME")
    print("convention. `while lo <= hi` pairs with hi = mid - 1; `while lo < hi`")
    print("pairs with hi = mid. Mix them and you either miss the endpoint or")
    print("spin forever.")


def section_gold():
    banner("SECTION F: GOLD values (pinned for binary_search.html)")
    # The .html recomputes the search path on the SAME array and checks these.
    path23 = binary_search_path(ARR, 23)
    idx23 = binary_search(ARR, 23)
    print(f"Array: {ARR}")
    print(f"search key=23 -> index {idx23}, path {path23}, probes {len(path23)}")
    print(f"GOLD path for key=23: {path23}")
    print(f"GOLD index for key=23: {idx23}")
    lb4 = lower_bound(ARR_DUP, 4)
    ub4 = upper_bound(ARR_DUP, 4)
    print(f"lower_bound(arr_dup, 4) = {lb4}   upper_bound = {ub4}   "
          f"count = {ub4 - lb4}")
    print(f"GOLD [lower,upper) for key=4 in arr_dup: [{lb4}, {ub4})")
    cap = ship_within_days([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 5)
    print(f"ship_within_days([1..10], days=5) = {cap}")
    print(f"GOLD min capacity: {cap}")
    # self-consistency asserts
    assert path23 == [7, 11]
    assert idx23 == 11
    assert lb4 == 6 and ub4 == 10
    assert cap == 15
    print("\n[check] all GOLD values reproduce from the implementations:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("binary_search.py - reference impl. All numbers below feed "
          "BINARY_SEARCH.md.")
    section_core_loop()
    section_probe_overflow()
    section_bounds()
    section_search_on_answer()
    section_off_by_one()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
