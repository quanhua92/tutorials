"""
prefix_sum.py - Reference implementation of the Prefix Sum pattern in its four
interview shapes:
  1. Prefix sum ARRAY         -> O(1) range-sum queries
  2. Prefix sum + HASH MAP    -> count subarrays whose sum == k   (P560)
  3. Prefix PRODUCT, L/R pass -> product except self              (P238)
  4. 0 -> -1 BALANCE + first-seen map -> longest equal-0/1 array (P525)

This is the SINGLE SOURCE OF TRUTH for PREFIX_SUM.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 prefix_sum.py > prefix_sum_output.txt

Pure Python stdlib only. Deterministic (hardcoded inputs, no randomness).

============================================================================
THE INTUITION (read this first) - a running bank balance
============================================================================
A prefix sum is your running bank balance. If the balance in January was $100
and in March it is $500, you made $400 across Feb-Mar WITHOUT re-reading every
receipt. Save a running total ONCE; then answer any "how much in [i..j]?" with
ONE subtraction:   Sum(i..j) = Prefix[j+1] - Prefix[i].

That single idea, plus a hash map that remembers PAST balances, collapses every
"contiguous subarray" problem from O(n^2) to O(n):

  * COUNT subarrays summing to k:  sum(i..j) = prefix[j] - prefix[i-1] = k
    rearranges to  prefix[i-1] = prefix[j] - k. As we scan, we just ask the
    hash map "how many times have I already seen the balance (curr - k)?"

  * PRODUCT except self (division banned): run a LEFT pass storing the product
    of everything left of i, then a RIGHT pass multiplying in the product of
    everything right of i. Two O(n) passes, O(1) extra space.

  * LONGEST subarray with equal 0s and 1s: treat 0 as -1 so "equal count"
    becomes "balance returns to a value seen before". Store ONLY the first
    index each balance appeared -> the longest gap. Never overwrite.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  prefix[i]      sum of nums[0..i-1]. prefix[0] = 0 (the empty prefix).
  range sum      sum of nums[l..r) = prefix[r] - prefix[l]. Half-open [l, r).
  curr_sum       the running balance as we scan (the "current" prefix value).
  freq map       dict {prefix_sum -> how many times seen so far}. Used to
                 COUNT subarrays ending here that sum to k.
  first_seen     dict {balance -> earliest index}. Used to MAXIMIZE length;
                 NEVER overwrite an existing entry.
  base case      freq[0] = 1 (one empty prefix before the array) for COUNTING;
                 first_seen[0] = -1 for LENGTHS. Forgetting it drops every
                 valid subarray that starts at index 0.
  balance        (P525) count(1) - count(0); constant across a subarray iff
                 that subarray has equal numbers of 0s and 1s.

============================================================================
THE SKELETONS (the four interview answers - memorize the shapes)
============================================================================
    # --- 1. Prefix sum array + O(1) range sum ----------------------------
    def prefix_sum_array(nums):
        prefix = [0] * (len(nums) + 1)
        for i, v in enumerate(nums):
            prefix[i + 1] = prefix[i] + v
        return prefix
    def range_sum(prefix, l, r):            # sum of nums[l:r], half-open
        return prefix[r] - prefix[l]

    # --- 2. Prefix sum + hash map (P560 Subarray Sum Equals K) -----------
    def subarray_sum_equals_k(nums, k):
        freq = {0: 1}                       # BASE CASE: one empty prefix
        curr = count = 0
        for x in nums:
            curr += x
            count += freq.get(curr - k, 0)  # how many earlier prefixes match
            freq[curr] = freq.get(curr, 0) + 1
        return count

    # --- 3. Prefix product, left/right pass (P238 Product Except Self) ---
    def product_except_self(nums):
        n = len(nums)
        out = [1] * n
        left = 1
        for i in range(n):                  # LEFT: out[i] = prod(nums[0:i])
            out[i] = left                   #  ASSIGN before multiply
            left *= nums[i]
        right = 1
        for i in range(n - 1, -1, -1):      # RIGHT: out[i] *= prod(nums[i+1:n])
            out[i] *= right
            right *= nums[i]
        return out

    # --- 4. 0 -> -1 balance + first-seen map (P525 Contiguous Array) -----
    def find_max_length_contiguous(nums):
        first = {0: -1}                     # BASE CASE: balance 0 at index -1
        balance = best = 0
        for i, x in enumerate(nums):
            balance += 1 if x == 1 else -1
            if balance in first:            # seen before -> candidate length
                best = max(best, i - first[balance])
            else:                           # NEVER overwrite (we want LONGEST)
                first[balance] = i
        return best
"""

from __future__ import annotations


# ============================================================================
# Variant 1: Standard prefix sum array + O(1) range-sum queries
# ============================================================================
def prefix_sum_array(nums: list[int]) -> list[int]:
    """Build prefix[0..n] where prefix[i] = sum(nums[0..i-1]) and prefix[0]=0.

    Length is len(nums)+1 so that range_sum(prefix, 0, n) and range_sum on an
    empty range both work with no special cases.
    """
    prefix: list[int] = [0] * (len(nums) + 1)
    for i, v in enumerate(nums):
        prefix[i + 1] = prefix[i] + v
    return prefix


def range_sum(prefix: list[int], left: int, right: int) -> int:
    """Sum of nums[left:right] (half-open) via prefix[right] - prefix[left]."""
    return prefix[right] - prefix[left]


# ============================================================================
# Variant 2: Prefix sum + hash map  (P560 Subarray Sum Equals K)
# ============================================================================
def subarray_sum_equals_k(nums: list[int], k: int) -> int:
    """Count subarrays whose sum is exactly k, in ONE pass.

    sum(i..j) = prefix[j] - prefix[i-1] = k  <=>  prefix[i-1] = prefix[j] - k.
    As we scan, freq holds {prefix_sum -> times seen}. For each new prefix we
    add freq[curr - k]: every earlier prefix equal to (curr - k) closes a
    valid subarray ending here. Init freq = {0: 1} for subarrays at index 0.
    """
    freq: dict[int, int] = {0: 1}
    curr = 0
    count = 0
    for x in nums:
        curr += x
        count += freq.get(curr - k, 0)
        freq[curr] = freq.get(curr, 0) + 1
    return count


# ============================================================================
# Variant 3: Prefix product, left/right pass  (P238 Product Except Self)
# ============================================================================
def product_except_self(nums: list[int]) -> list[int]:
    """out[i] = product of all nums except nums[i], no division, O(n), O(1) extra.

    Left pass:  out[i]  = product of nums[0..i-1]   (assign BEFORE multiply,
    else nums[i] leaks into its own result).
    Right pass: out[i] *= product of nums[i+1..n-1].
    """
    n = len(nums)
    out: list[int] = [1] * n
    left = 1
    for i in range(n):
        out[i] = left
        left *= nums[i]
    right = 1
    for i in range(n - 1, -1, -1):
        out[i] *= right
        right *= nums[i]
    return out


# ============================================================================
# Variant 4: 0 -> -1 balance + first-seen map  (P525 Contiguous Array)
# ============================================================================
def find_max_length_contiguous(nums: list[int]) -> int:
    """Longest contiguous subarray with equal # of 0s and 1s.

    Treat 0 as -1: balance = count(1) - count(0). A subarray has equal counts
    iff balance is the SAME at both ends. Store only the FIRST index each
    balance appears (we maximize length, so never overwrite). Base case
    first[0] = -1 captures subarrays starting at index 0.
    """
    first: dict[int, int] = {0: -1}
    balance = 0
    best = 0
    for i, x in enumerate(nums):
        balance += 1 if x == 1 else -1
        if balance in first:
            best = max(best, i - first[balance])
        else:
            first[balance] = i
    return best


# ============================================================================
# TRACE BUILDERS - snapshot each step for the worked-example tables in
# PREFIX_SUM.md and the animation in prefix_sum.html.
# ============================================================================
def trace_range(nums: list[int], queries: list[tuple[int, int]]) -> list[dict]:
    """Build the prefix array one cell at a time, then answer each [l:r) query."""
    snaps: list[dict] = []
    prefix = [0]
    snaps.append({"phase": "build", "i": -1, "val": None,
                  "prefix": list(prefix), "note": "prefix[0] = 0 (empty prefix)"})
    for i, v in enumerate(nums):
        prefix.append(prefix[-1] + v)
        snaps.append({"phase": "build", "i": i, "val": v,
                      "prefix": list(prefix),
                      "note": f"prefix[{i + 1}] = prefix[{i}] + nums[{i}] = "
                              f"{prefix[-2]} + {v} = {prefix[-1]}"})
    for (l, r) in queries:
        ans = prefix[r] - prefix[l]
        seg = "+".join(str(x) for x in nums[l:r]) or "0"
        snaps.append({"phase": "query", "l": l, "r": r,
                      "pl": prefix[l], "pr": prefix[r], "ans": ans,
                      "seg": seg, "prefix": list(prefix),
                      "note": f"sum[{l}:{r}) = prefix[{r}] - prefix[{l}] = "
                              f"{prefix[r]} - {prefix[l]} = {ans}   "
                              f"(nums[{l}:{r}] = [{seg}] = {ans})"})
    return snaps


def trace_subarray_sum_k(nums: list[int], k: int) -> list[dict]:
    """One-pass scan: per step capture curr, target=curr-k, how many matched,
    running count, and the freq map AFTER the update."""
    freq: dict[int, int] = {0: 1}
    curr = 0
    count = 0
    snaps: list[dict] = []
    snaps.append({"step": -1, "num": None, "curr": 0, "target": None,
                  "matched": 0, "count": 0, "freq": dict(freq),
                  "note": f"init: freq = {{0: 1}}  (one empty prefix), "
                          f"curr = 0, count = 0"})
    for i, x in enumerate(nums):
        curr += x
        target = curr - k
        matched = freq.get(target, 0)
        count += matched
        freq[curr] = freq.get(curr, 0) + 1
        snaps.append({"step": i, "num": x, "curr": curr, "target": target,
                      "matched": matched, "count": count, "freq": dict(freq),
                      "note": (f"curr += {x} -> {curr};  target = curr - k = "
                               f"{target};  freq[{target}] = {matched};  "
                               f"count -> {count};  freq[{curr}] += 1")})
    return snaps


def trace_product_except_self(nums: list[int]) -> list[dict]:
    """Left pass then right pass. Each step shows the out array mid-pass."""
    n = len(nums)
    out = [1] * n
    snaps: list[dict] = []
    snaps.append({"phase": "left", "i": None, "out": list(out),
                  "running": 1,
                  "note": "out = [1]*n;  left = 1  (product of nothing = 1)"})
    left = 1
    for i in range(n):
        out[i] = left
        snaps.append({"phase": "left", "i": i, "out": list(out),
                      "running": left,
                      "note": f"out[{i}] = left = {left}  (prod of nums[0:{i}]);"
                              f"  then left *= nums[{i}] = {nums[i]} -> "
                              f"{left * nums[i]}"})
        left *= nums[i]
    snaps.append({"phase": "left-done", "i": None, "out": list(out),
                  "running": left,
                  "note": f"after LEFT pass: out = {out}  "
                          f"(out[i] = product of everything left of i)"})
    right = 1
    for i in range(n - 1, -1, -1):
        out[i] *= right
        snaps.append({"phase": "right", "i": i, "out": list(out),
                      "running": right,
                      "note": f"out[{i}] *= right = {right};  then right *= "
                              f"nums[{i}] = {nums[i]} -> {right * nums[i]}"})
        right *= nums[i]
    snaps.append({"phase": "right-done", "i": None, "out": list(out),
                  "running": right,
                  "note": f"after RIGHT pass: out = {out}  "
                          f"(each *= product of everything right of i)"})
    return snaps


def trace_contiguous_array(nums: list[int]) -> list[dict]:
    """Balance walk. Each step: new balance, whether seen, candidate length,
    running best, and the first_seen map (only first occurrences stored)."""
    first: dict[int, int] = {0: -1}
    balance = 0
    best = 0
    snaps: list[dict] = []
    snaps.append({"step": -1, "num": None, "balance": 0, "seen_at": None,
                  "length": None, "best": 0, "first": dict(first),
                  "note": "init: first = {0: -1}  (balance 0 at virtual idx -1),"
                          "  balance = 0, best = 0"})
    for i, x in enumerate(nums):
        delta = 1 if x == 1 else -1
        balance += delta
        if balance in first:
            length = i - first[balance]
            best = max(best, length)
            seen_at = first[balance]
            action = (f"balance += {delta:+d} -> {balance};  SEEN at idx "
                      f"{seen_at};  length = {i} - {seen_at} = {length};  "
                      f"best -> {best};  (do NOT overwrite)")
            first_after = dict(first)
        else:
            first[balance] = i
            seen_at = None
            length = None
            action = (f"balance += {delta:+d} -> {balance};  new -> "
                      f"first[{balance}] = {i};  best stays {best}")
            first_after = dict(first)
        snaps.append({"step": i, "num": x, "balance": balance,
                      "seen_at": seen_at, "length": length, "best": best,
                      "first": first_after, "note": action})
    return snaps


# ============================================================================
# The canonical inputs used everywhere (py output, md tables, html trace)
# ============================================================================
RANGE_NUMS = [2, -1, 3, -2, 4, 1]
RANGE_QUERIES = [(0, 6), (1, 4), (2, 5), (3, 3), (4, 6)]
# expected: [7, 0, 5, 0, 5]

P560_NUMS = [1, 1, 1]
P560_K = 2
P560_EXPECTED = 2

P560_NUMS2 = [1, 2, 3]
P560_K2 = 3
P560_EXPECTED2 = 2

P238_NUMS = [1, 2, 3, 4]
P238_EXPECTED = [24, 12, 8, 6]
P238_NUMS2 = [-1, 1, 0, -3, 3]
P238_EXPECTED2 = [0, 0, 9, 0, 0]

P525_NUMS = [0, 1, 1, 0, 1, 1, 1, 0]
P525_EXPECTED = 4
P525_NUMS2 = [0, 1]
P525_EXPECTED2 = 2


# ============================================================================
# SECTION A - the pattern: save a running total, answer ranges by subtraction
# ============================================================================
def section_a() -> None:
    print("=" * 76)
    print("SECTION A - The Prefix Sum pattern: running total + hash lookups")
    print("=" * 76)
    print()
    print("Mental model: a prefix sum is a running bank balance. Save the total")
    print("once; answer any 'sum of [i..j]' by ONE subtraction instead of")
    print("re-scanning. A hash map of PAST balances then turns every")
    print("'contiguous subarray' question from O(n^2) into O(n).")
    print()
    print("  1. PREFIX ARRAY:  prefix[i] = sum(nums[0..i-1]), prefix[0] = 0.")
    print("                    range[l:r) = prefix[r] - prefix[l]   O(1) query.")
    print()
    print("  2. + HASH MAP:    sum(i..j) = prefix[j] - prefix[i-1] = k")
    print("                    <=> prefix[i-1] = prefix[j] - k.")
    print("                    Scan once; at each step add freq[curr - k].")
    print("                    Base case freq = {0: 1} (subarrays from idx 0).")
    print()
    print("  3. PREFIX PRODUCT (no division): LEFT pass stores prod left of i;")
    print("                    RIGHT pass multiplies prod right of i. O(1) extra.")
    print()
    print("  4. BALANCE + FIRST-SEEN (equal 0/1): treat 0 as -1 so equal-count")
    print("                    <=> balance returns to a value seen before. Store")
    print("                    only the FIRST index per balance (maximize length).")
    print()
    print("Pattern-recognition signals")
    print("---------------------------")
    print('  "sum of a subarray", "range sum", "cumulative sum"        -> prefix')
    print('  "subarray sum equals K", "count subarrays with sum"      -> + hash')
    print('  "product of array except self", "without division"       -> L/R pass')
    print('  "contiguous array with equal # of 0 and 1"               -> balance')
    print('  "longest subarray with sum/product == K"                 -> + hash')
    print('  "number of subarrays" with a contiguous property         -> + hash')
    print()
    print("The four interview skeletons (see module docstring for full code):")
    print()
    print("  prefix_sum_array(nums):  prefix[0]=0; prefix[i+1]=prefix[i]+nums[i]")
    print("  range_sum(prefix, l, r): prefix[r] - prefix[l]   (half-open)")
    print("  subarray_sum_equals_k:   freq={0:1}; curr+=x; count+=freq[curr-k]")
    print("  product_except_self:     LEFT pass then RIGHT pass; assign 1st")
    print("  find_max_length:         first={0:-1}; balance+=+/-1; never overwrite")
    print()


# ============================================================================
# SECTION B - Variant 1 + Variant 2 foundations / range queries
# ============================================================================
def section_b() -> None:
    print("=" * 76)
    print("SECTION B - Prefix sum array + O(1) range queries  (Variant 1)")
    print("=" * 76)
    print()
    print("Build prefix[0..n] where prefix[i] = sum(nums[0..i-1]) and prefix[0]=0.")
    print("Any half-open range sum[l:r) is then a single subtraction:")
    print("    sum(nums[l:r]) = prefix[r] - prefix[l].")
    print("Build cost O(n) once; every query O(1). Handles negatives fine.")
    print()
    print(f"nums    = {RANGE_NUMS}")
    prefix = prefix_sum_array(RANGE_NUMS)
    print(f"prefix  = {prefix}   (length {len(prefix)} = len(nums)+1)")
    print()
    snaps = trace_range(RANGE_NUMS, RANGE_QUERIES)
    print("Build trace:")
    print("  i    nums[i]   prefix[i+1] = prefix[i] + nums[i]")
    print("  --   -------   ------------------------------------")
    for s in snaps:
        if s["phase"] == "build":
            if s["i"] == -1:
                print(f"  --   -         prefix[0] = 0")
            else:
                print(f"  {s['i']:<3}  {s['val']:^7}   {s['note']}")
    print()
    print("Range queries (half-open [l:r)):")
    print("  query       prefix[r]-prefix[l]        result")
    print("  ----------  --------------------------  ------")
    for s in snaps:
        if s["phase"] == "query":
            print(f"  [{s['l']}:{s['r']})         "
                  f"prefix[{s['r']}] - prefix[{s['l']}] = "
                  f"{s['pr']} - {s['pl']}        {s['ans']}")
    print()
    # verify every query against the brute-force definition
    for (l, r) in RANGE_QUERIES:
        brute = sum(RANGE_NUMS[l:r])
        fast = range_sum(prefix, l, r)
        assert brute == fast, (l, r, brute, fast)
    answers = [range_sum(prefix, l, r) for (l, r) in RANGE_QUERIES]
    print(f"answers     = {answers}")
    print(f"expected    = {[7, 0, 5, 0, 5]}")
    print(f"match: {answers == [7, 0, 5, 0, 5]}")
    print()


# ============================================================================
# SECTION C - P560 Subarray Sum Equals K (prefix sum + hash map)
# ============================================================================
def section_c() -> None:
    print("=" * 76)
    print("SECTION C - P560 Subarray Sum Equals K  (prefix sum + hash map)")
    print("=" * 76)
    print()
    print("Count subarrays summing to k. Brute force is O(n^2): try every (i, j).")
    print("sum(i..j) = prefix[j] - prefix[i-1] = k  <=>  prefix[i-1] = prefix[j]-k.")
    print("So at each j we just ask the freq map 'how many earlier prefixes equal")
    print("curr - k?'. ONE pass, O(n) time, O(n) space. Base case freq = {0: 1}")
    print("captures subarrays that start at index 0.")
    print()
    print(f"nums = {P560_NUMS},  k = {P560_K}")
    print()
    snaps = trace_subarray_sum_k(P560_NUMS, P560_K)
    print("Step trace:")
    print()
    print("  step  num   curr   target=curr-k   matched   count   freq (after)")
    print("  ----  ---   ----   -------------   -------   -----   ----------------")
    for s in snaps:
        if s["step"] == -1:
            tgt = "-"
        else:
            tgt = str(s["target"])
        freq_str = "{" + ", ".join(f"{kk}:{vv}" for kk, vv in sorted(s["freq"].items())) + "}"
        print(f"  {str(s['step']):<4}  {('-' if s['num'] is None else str(s['num'])):^3}   "
              f"{s['curr']:<4}   {tgt:<13}   {s['matched']:<7}   "
              f"{s['count']:<5}   {freq_str}")
    print()
    print("Notes per step:")
    for s in snaps[1:]:
        print(f"  step {s['step']}:  {s['note']}")
    print()
    # the two valid subarrays of [1,1,1] summing to 2: [0:2] and [1:3]
    got = subarray_sum_equals_k(P560_NUMS, P560_K)
    print(f"subarray_sum_equals_k({P560_NUMS}, {P560_K}) = {got}")
    print(f"LeetCode example 1 expected            = {P560_EXPECTED}")
    print(f"match: {got == P560_EXPECTED}")
    print()
    print("-- base case demonstration: drop {0:1} and you miss index-0 subarrays --")
    print(f"  with freq = {{0:1}}  -> {subarray_sum_equals_k(P560_NUMS, P560_K)}")
    freq_broken: dict[int, int] = {}  # simulate the bug
    curr = count_b = 0
    for x in P560_NUMS:
        curr += x
        count_b += freq_broken.get(curr - P560_K, 0)
        freq_broken[curr] = freq_broken.get(curr, 0) + 1
    print(f"  with freq = {{}}  (no base case) -> {count_b}   "
          f"(WRONG: misses [0:2] which starts at index 0)")
    print()
    print("-- second LeetCode example --")
    got2 = subarray_sum_equals_k(P560_NUMS2, P560_K2)
    print(f"  nums = {P560_NUMS2}, k = {P560_K2}  ->  {got2}  "
          f"(subarrays [1,2] and [3]); expected {P560_EXPECTED2}; "
          f"match: {got2 == P560_EXPECTED2}")
    print()


# ============================================================================
# SECTION D - P238 Product of Array Except Self (prefix product, L/R pass)
# ============================================================================
def section_d() -> None:
    print("=" * 76)
    print("SECTION D - P238 Product of Array Except Self  (left/right prefix pass)")
    print("=" * 76)
    print()
    print("out[i] = product of all nums except nums[i], WITHOUT division, O(n).")
    print("Two passes: LEFT stores product of everything LEFT of i into out[i];")
    print("RIGHT multiplies in the product of everything RIGHT of i. Crucial:")
    print("ASSIGN out[i] = running BEFORE multiplying nums[i] into running, else")
    print("nums[i] leaks into its own answer. O(1) extra space (the output array")
    print("does not count toward space).")
    print()
    print(f"nums = {P238_NUMS}")
    print()
    snaps = trace_product_except_self(P238_NUMS)
    print("LEFT pass  (out[i] = product of nums[0:i]):")
    print("  i    nums[i]   out[i] = left   then left *= nums[i]")
    print("  --   -------   -------------   ---------------------")
    for s in snaps:
        if s["phase"] == "left" and s["i"] is not None:
            print(f"  {s['i']:<3}  {P238_NUMS[s['i']]:^7}   "
                  f"out[{s['i']}] = {s['running']}        "
                  f"left -> {s['running'] * P238_NUMS[s['i']]}")
        elif s["phase"] == "left-done":
            print(f"  out after LEFT = {s['out']}")
    print()
    print("RIGHT pass  (out[i] *= product of nums[i+1:n]):")
    print("  i    nums[i]   out[i] *= right   then right *= nums[i]")
    print("  --   -------   ----------------   ---------------------")
    for s in snaps:
        if s["phase"] == "right" and s["i"] is not None:
            print(f"  {s['i']:<3}  {P238_NUMS[s['i']]:^7}   "
                  f"out[{s['i']}] *= {s['running']} -> {s['out'][s['i']]:<6} "
                  f" right -> {s['running'] * P238_NUMS[s['i']]}")
        elif s["phase"] == "right-done":
            print(f"  out after RIGHT = {s['out']}")
    print()
    got = product_except_self(P238_NUMS)
    print(f"product_except_self({P238_NUMS}) = {got}")
    print(f"LeetCode example 1 expected       = {P238_EXPECTED}")
    print(f"match: {got == P238_EXPECTED}")
    print()
    print("-- second LeetCode example (contains a zero) --")
    got2 = product_except_self(P238_NUMS2)
    print(f"  nums = {P238_NUMS2}  ->  {got2}  expected {P238_EXPECTED2}  "
          f"match: {got2 == P238_EXPECTED2}")
    print()


# ============================================================================
# SECTION E - P525 Contiguous Array + complexity + gotchas + problem table
# ============================================================================
def section_e() -> None:
    print("=" * 76)
    print("SECTION E - P525 Contiguous Array  (0->-1 balance + first-seen map)")
    print("=" * 76)
    print()
    print("Longest contiguous subarray with equal # of 0s and 1s. Treat 0 as -1:")
    print("balance = count(1) - count(0). A subarray has equal counts iff balance")
    print("is the SAME at both endpoints. Store only the FIRST index each balance")
    print("appears (we want LONGEST, so never overwrite). Base case first[0] = -1")
    print("captures subarrays that begin at index 0.")
    print()
    print(f"nums = {P525_NUMS}")
    print()
    snaps = trace_contiguous_array(P525_NUMS)
    print("Step trace:")
    print()
    print("  i    num   balance   seen?          length    best   first (after)")
    print("  --   ---   -------   -------------  ------    ----   ----------------")
    for s in snaps:
        if s["step"] == -1:
            seen = "-"
            length = "-"
        else:
            seen = ("no (new)" if s["seen_at"] is None
                    else f"yes @ {s['seen_at']}")
            length = "-" if s["length"] is None else str(s["length"])
        first_str = "{" + ", ".join(f"{kk}:{vv}" for kk, vv in sorted(s["first"].items())) + "}"
        print(f"  {str(s['step']):<3}  {('-' if s['num'] is None else str(s['num'])):^3}   "
              f"{s['balance']:<7}   {seen:<13}  {length:<7}   "
              f"{s['best']:<4}   {first_str}")
    print()
    print("Notes per step:")
    for s in snaps[1:]:
        print(f"  i={s['step']}:  {s['note']}")
    print()
    got = find_max_length_contiguous(P525_NUMS)
    print(f"find_max_length_contiguous({P525_NUMS}) = {got}   "
          f"(subarray [0,1,1,0] at indices 0..3); expected {P525_EXPECTED}; "
          f"match: {got == P525_EXPECTED}")
    print()
    print("-- the 'never overwrite' gotcha: balance 1 first appears at i=2,")
    print("   reappears at i=4; using the LATER index would give length 0 not 2 --")
    print()
    got2 = find_max_length_contiguous(P525_NUMS2)
    print(f"  nums = {P525_NUMS2}  ->  {got2}  expected {P525_EXPECTED2}  "
          f"match: {got2 == P525_EXPECTED2}")
    print()
    print("=" * 76)
    print("Complexity, killer gotchas, problem table")
    print("=" * 76)
    print()
    print("Complexity")
    print("----------")
    print("  Variant                        Build     Query     Space")
    print("  -----------------------------  --------  --------  ---------")
    print("  1. prefix array + range sum    O(n)      O(1)      O(n)")
    print("  2. prefix + hash (sum == k)    O(n)      -         O(n)")
    print("  3. prefix product (L/R pass)   O(n)      -         O(1) extra")
    print("  4. balance + first-seen        O(n)      -         O(n)")
    print("  (all SINGLE pass; hash ops are O(1) amortized)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. THE MISSING EMPTY PREFIX. For counting, init freq = {0: 1}; for")
    print("     longest-by-index, init first = {0: -1}. Without it, EVERY valid")
    print("     subarray that starts at index 0 is silently dropped.")
    print("  2. OVERWRITE vs ACCUMULATE. For COUNTING use freq[curr] += 1 (every")
    print("     occurrence is a distinct subarray end). For LONGEST use")
    print("     first.setdefault / 'if balance not in first' so you keep the")
    print("     EARLIEST index only. Mixing the two is the #1 silent-wrong-answer.")
    print("  3. ASSIGN BEFORE MULTIPLY (Product Except Self). out[i] = running;")
    print("     THEN running *= nums[i]. Reverse the order and nums[i] divides its")
    print("     own answer (you include the element you must exclude).")
    print("  4. HALF-OPEN INDEXING. prefix has length n+1; range[l:r) =")
    print("     prefix[r] - prefix[l]. sum of the whole array is prefix[n]-prefix[0].")
    print("     Test the full-array and empty-range cases by hand.")
    print("  5. NEGATIVES ARE FINE for prefix sums and for freq maps; but a")
    print("     sliding window is NOT (it relies on monotone sums). With negatives")
    print("     reach for prefix-sum + hash, never a two-pointer window.")
    print("  6. 0 -> -1 is the trick for 'equal count of two values': any pair of")
    print("     values (a, b) works by mapping a -> +1, b -> -1; equal-count iff the")
    print("     running balance repeats.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                       Diff   Key trick")
    print("  ----------------------------- ------  --------------------------------------")
    print("  P560 Subarray Sum Equals K    Medium prefix freq map; count += freq[curr-k];")
    print("                                       init freq={0:1}")
    print("  P238 Product Except Self      Medium LEFT pass then RIGHT pass; assign")
    print("                                       BEFORE multiply; O(1) extra; no division")
    print("  P525 Contiguous Array         Medium 0->-1 balance, first-seen map;")
    print("                                       first={0:-1}; never overwrite")
    print("  P303 Range Sum Query          Easy   immutable prefix array;")
    print("                                       sum[l:r]=prefix[r]-prefix[l]")
    print("  P523 Continuous Subarray Sum  Medium prefix MOD k, first-seen map;")
    print("                                       gap>=2; never overwrite")
    print("  P713 Subarray Product < K     Medium sliding window (NOT prefix!);")
    print("                                       k<=1 -> 0; count += r-l+1")
    print("  P528 Random Pick with Weight  Medium prefix sums + binary search;")
    print("                                       randint(1,total); first prefix >= t")
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

    # ---- assertions (all deterministic) ----
    # Variant 1: range queries match brute force
    pref = prefix_sum_array(RANGE_NUMS)
    assert [range_sum(pref, l, r) for (l, r) in RANGE_QUERIES] == [7, 0, 5, 0, 5]
    for (l, r) in RANGE_QUERIES:
        assert range_sum(pref, l, r) == sum(RANGE_NUMS[l:r])

    # P560 Subarray Sum Equals K — LeetCode examples
    assert subarray_sum_equals_k(P560_NUMS, P560_K) == P560_EXPECTED        # [1,1,1],2 -> 2
    assert subarray_sum_equals_k(P560_NUMS2, P560_K2) == P560_EXPECTED2     # [1,2,3],3 -> 2
    assert subarray_sum_equals_k([1], 0) == 0                               # no subarray
    assert subarray_sum_equals_k([1, -1, 0], 0) == 3                        # neg + zero

    # base case {0:1} is essential: without it index-0 subarrays are missed
    assert subarray_sum_equals_k([2, 2], 4) == 1                            # only [0:2]
    assert subarray_sum_equals_k([0, 0, 0], 0) == 6                         # all subarrays

    # P238 Product Except Self — LeetCode examples
    assert product_except_self(P238_NUMS) == P238_EXPECTED                   # [24,12,8,6]
    assert product_except_self(P238_NUMS2) == P238_EXPECTED2                 # contains 0
    assert product_except_self([5]) == [1]                                   # single elem
    assert product_except_self([2, 3]) == [3, 2]

    # P525 Contiguous Array
    assert find_max_length_contiguous(P525_NUMS) == P525_EXPECTED            # 4
    assert find_max_length_contiguous(P525_NUMS2) == P525_EXPECTED2          # 2
    assert find_max_length_contiguous([0, 1, 0]) == 2
    assert find_max_length_contiguous([0, 0, 0, 0]) == 0                    # all same
    assert find_max_length_contiguous([1]) == 0

    # 'never overwrite' is essential: balance repeats, latest index would shrink len
    # bug demo: unconditional overwrite (correct keeps ONLY the earliest index).
    # For [0,1,1,0] the correct answer is 4 (balance 0 at i=3 vs first[0]=-1);
    # overwriting first[0] to 1 at i=1 makes i=3 compute 3-1=2 instead of 3-(-1)=4.
    first_bad: dict[int, int] = {0: -1}
    bal = best_bad = 0
    for i, x in enumerate([0, 1, 1, 0]):
        bal += 1 if x == 1 else -1
        if bal in first_bad:                 # compute with the stored (earliest) index
            best_bad = max(best_bad, i - first_bad[bal])
        first_bad[bal] = i                   # BUG: unconditional overwrite
    assert best_bad == 2 < find_max_length_contiguous([0, 1, 1, 0])  # 2 < 4

    print("=" * 76)
    print("[check] Prefix Sum array + range queries + subarray-sum-K +")
    print("        product-except-self + contiguous-array ... OK")
    print("=" * 76)
