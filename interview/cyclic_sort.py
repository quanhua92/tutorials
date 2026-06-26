"""
cyclic_sort.py - Reference implementation of Cyclic Sort for:
  * Cyclic sort: swap each number to its correct index (range [1, n])
  * P268 Missing Number: cyclic-sort swap on [0, n] then scan
  * P442 Find All Duplicates: negation marking on [1, n]
  * P448 Find All Numbers Disappeared: negation marking on [1, n]

This is the SINGLE SOURCE OF TRUTH for CYCLIC_SORT.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 cyclic_sort.py > cyclic_sort_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - numbered balls into numbered boxes
============================================================================
You have an array of N numbers, and the numbers all come from a small known
range (1..N or 0..N). That means every value has a *natural home index*:

    range [1, n] : value v belongs at index  v - 1   (1 -> 0, n -> n-1)
    range [0, n] : value v belongs at index  v       (0 -> 0, n-1 -> n-1)

Think numbered balls rolling around in numbered boxes. If ball #3 is in box
#5, just swap it with whatever is in box #3. Repeat until the box you're
holding already holds the right ball, then move on. Two strategies, same idea:

  1. SWAP-TO-PLACE (move the balls). Walk left to right with index i. If the
     ball at i does not belong at i, swap it into its home; stay at i because
     the new arrival might *also* be misplaced. Only advance i once the ball
     at i is home (or is out of range, like the value n in [0, n]). After one
     pass the array is sorted; a quick scan reveals any missing value.

  2. NEGATION-MARK (deface the boxes). You cannot always move balls, so mark
     box v with a scratch (flip the sign of nums[v-1]) to record "ball v was
     seen." A sign bit is a 1-bit bitmap at zero memory cost. Two reads of
     the same box => a duplicate; a box never scratched => its ball never
     appeared (it "disappeared").

  --> Both are O(n) time and O(1) extra space because the array is its own
      hash table: the *value* is the *key* and the *index* is the *bucket*.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  correct index   the home slot for a value. For range [1,n]: v -> v-1.
                  For range [0,n]: v -> v. The out-of-range value n in [0,n]
                  has NO home, so guard with `correct < n` before swapping.
  cyclic sort     the swap-to-place pass. Despite nested-looking logic
                  (while inside while), total work is O(n): every swap puts
                  one more ball home, and there are at most n-1 swaps total.
  negation mark   flipping nums[v-1] to negative to mean "v was seen."
                  Always index with abs(num)-1 because num may itself have
                  been negated by an earlier step.
  already-home    nums[i] == nums[correct], i.e. the target slot already
                  holds this value (a duplicate in that slot). Just advance.
  disappeared     a value in [1, n] whose box was never scratched; after the
                  negate pass its slot is still positive.
  duplicate       a value whose box was ALREADY negative when we tried to
                  scratch it -> the value occurred at least twice.

============================================================================
THE SKELETON (two strategies, one mental model)
============================================================================
    # Strategy 1 - SWAP-TO-PLACE (range [1, n])
    i = 0
    while i < len(nums):
        correct = nums[i] - 1
        if nums[i] != nums[correct]:
            nums[i], nums[correct] = nums[correct], nums[i]   # stay at i
        else:
            i += 1

    # Strategy 1b - SWAP-TO-PLACE (range [0, n])  -> P268 Missing Number
    n = len(nums)
    i = 0
    while i < n:
        correct = nums[i]                # v belongs at index v
        if correct < n and nums[i] != nums[correct]:   # guard: n has no home
            nums[i], nums[correct] = nums[correct], nums[i]
        else:
            i += 1
    for j in range(n):
        if nums[j] != j:
            return j
    return n

    # Strategy 2 - NEGATION-MARK (range [1, n])  -> P442 + P448
    for num in nums:
        idx = abs(num) - 1               # abs(): num may be a negated mark
        if nums[idx] < 0:
            ... duplicate detected       # P442
        else:
            nums[idx] = -nums[idx]       # scratch the box
"""

from __future__ import annotations


# ============================================================================
# TEMPLATE 1 - CYCLIC SORT (swap-to-place, range [1, n])
# ============================================================================
def cyclic_sort(nums: list[int]) -> list[int]:
    """Sort an array containing a permutation of 1..n in place.

    Each value v belongs at index v-1. Walk left to right; if the value at i
    is not home, swap it home and re-check i (the newcomer may be misplaced
    too). Advance only once nums[i] is already at its correct slot.

    Time:  O(n)   (at most n-1 swaps total across the whole pass)
    Space: O(1)
    """
    i = 0
    while i < len(nums):
        correct = nums[i] - 1
        if nums[i] != nums[correct]:
            nums[i], nums[correct] = nums[correct], nums[i]
        else:
            i += 1
    return nums


def trace_cyclic_sort(nums: list[int]) -> list[dict]:
    """Record each swap/advance of cyclic_sort (range [1, n]).

    Each step: {i, val, correct, action, dup, before, after}
      action = 'swap'    swapped nums[i] with nums[correct]
      action = 'advance' nums[i] already home (or a duplicate) -> i += 1
    """
    a = list(nums)
    steps: list[dict] = []
    i = 0
    while i < len(a):
        correct = a[i] - 1
        if a[i] != a[correct]:
            before = list(a)
            a[i], a[correct] = a[correct], a[i]
            steps.append({
                "i": i, "val": before[i], "correct": correct,
                "action": "swap", "dup": False,
                "swapped_with": before[correct],
                "before": before, "after": list(a),
            })
        else:
            steps.append({
                "i": i, "val": a[i], "correct": correct,
                "action": "advance",
                "dup": (a[i] - 1 != i),
                "before": list(a), "after": list(a),
            })
            i += 1
    return steps


# ============================================================================
# TEMPLATE 2 - P268 MISSING NUMBER (swap-to-place on range [0, n], then scan)
# ============================================================================
def missing_number(nums: list[int]) -> int:
    """Return the one number missing from [0, n].

    Cyclic-sort: place each value v at index v. The value n has no home
    (index n is out of bounds), so guard with `correct < n`. After the pass,
    the first index whose value disagrees is the missing number; if every
    slot matches, the missing value is n itself.

    Time:  O(n)
    Space: O(1)
    """
    n = len(nums)
    a = list(nums)
    i = 0
    while i < n:
        correct = a[i]
        if correct < n and a[i] != a[correct]:
            a[i], a[correct] = a[correct], a[i]
        else:
            i += 1
    for j in range(n):
        if a[j] != j:
            return j
    return n


def trace_missing_number(nums: list[int]) -> tuple[list[dict], int]:
    """Trace the cyclic-sort pass of P268. Returns (swap_steps, answer).

    Only swap events are recorded (the meat of the algorithm); the final scan
    is summarized in the returned answer.
    """
    n = len(nums)
    a = list(nums)
    steps: list[dict] = []
    i = 0
    while i < n:
        correct = a[i]
        if correct < n and a[i] != a[correct]:
            before = list(a)
            a[i], a[correct] = a[correct], a[i]
            steps.append({
                "i": i, "val": before[i], "correct": correct,
                "swapped_with": before[correct],
                "before": before, "after": list(a),
            })
        else:
            i += 1
    missing = n
    for j in range(n):
        if a[j] != j:
            missing = j
            break
    return steps, missing


# ============================================================================
# TEMPLATE 3 - P442 FIND ALL DUPLICATES (negation mark, range [1, n])
# ============================================================================
def find_duplicates(nums: list[int]) -> list[int]:
    """Return every value in [1, n] that appears twice.

    For each value v, look at slot v-1. If it is already negative, v was
    seen before -> record it. Otherwise scratch the slot (negate it).

    Time:  O(n)
    Space: O(1) extra (output list not counted)
    """
    a = list(nums)
    duplicates: list[int] = []
    for num in a:
        idx = abs(num) - 1
        if a[idx] < 0:
            duplicates.append(abs(num))
        else:
            a[idx] = -a[idx]
    return duplicates


def trace_find_duplicates(nums: list[int]) -> tuple[list[dict], list[int]]:
    """Trace the negation pass of P442. Returns (steps, duplicates).

    Each step: {k, read, idx, mark, dup, cell_before, array_after}
      read    abs() of the value scanned (its original magnitude)
      mark    True if we negated the slot this step
      dup     True if the slot was already negative (a duplicate)
    """
    a = list(nums)
    steps: list[dict] = []
    duplicates: list[int] = []
    for k in range(len(a)):
        read = abs(a[k])
        idx = read - 1
        cell_before = a[idx]
        if a[idx] < 0:
            duplicates.append(read)
            steps.append({
                "k": k, "read": read, "idx": idx, "mark": False, "dup": True,
                "cell_before": cell_before, "array_after": list(a),
            })
        else:
            a[idx] = -a[idx]
            steps.append({
                "k": k, "read": read, "idx": idx, "mark": True, "dup": False,
                "cell_before": cell_before, "array_after": list(a),
            })
    return steps, duplicates


# ============================================================================
# TEMPLATE 4 - P448 FIND ALL NUMBERS DISAPPEARED (negation mark, range [1, n])
# ============================================================================
def find_disappeared(nums: list[int]) -> list[int]:
    """Return every value in [1, n] that does not appear.

    Same negate pass as find_duplicates (without early recording). After the
    pass, any slot still positive was never scratched -> its ball (idx+1)
    never appeared.

    Time:  O(n)
    Space: O(1) extra (output list not counted)
    """
    a = list(nums)
    for num in a:
        idx = abs(num) - 1
        if a[idx] > 0:
            a[idx] = -a[idx]
    return [i + 1 for i in range(len(a)) if a[i] > 0]


def trace_find_disappeared(nums: list[int]) -> tuple[list[dict], list[int]]:
    """Trace the negation pass of P448. Returns (steps, disappeared).

    Same step shape as trace_find_duplicates; disappeared values are the
    slots that remain positive after the full pass.
    """
    a = list(nums)
    steps: list[dict] = []
    for k in range(len(a)):
        read = abs(a[k])
        idx = read - 1
        cell_before = a[idx]
        if a[idx] > 0:
            a[idx] = -a[idx]
            steps.append({
                "k": k, "read": read, "idx": idx, "mark": True,
                "cell_before": cell_before, "array_after": list(a),
            })
        else:
            steps.append({
                "k": k, "read": read, "idx": idx, "mark": False,
                "cell_before": cell_before, "array_after": list(a),
            })
    disappeared = [i + 1 for i in range(len(a)) if a[i] > 0]
    return steps, disappeared


# ============================================================================
# SECTION A - CYCLIC SORT (the swap-to-place mechanic, range [1, n])
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - Cyclic Sort  (swap each value to its home, range [1, n])")
    print("=" * 72)
    print()
    nums = [3, 1, 5, 4, 2]
    print(f"nums = {nums}   (a permutation of 1..5)")
    print()
    print("Rule: value v belongs at index v - 1.")
    print("    Walk i left to right. If nums[i] is not home, swap it home;")
    print("    re-check i (the newcomer may be misplaced). Advance only when")
    print("    nums[i] is home. A nested-looking while is STILL O(n): each")
    print("    swap puts one more ball home, so there are at most n-1 swaps.")
    print()
    print("Step-by-step:")
    print()
    steps = trace_cyclic_sort(nums)
    print("  i | val | correct | action         | before            -> after")
    print("  --+-----+---------+----------------+------------------------------------------")
    for s in steps:
        if s["action"] == "swap":
            action = f"swap with [{s['correct']}]={s['swapped_with']}"
        else:
            tag = " (already home)"
            if s["dup"]:
                tag = " (slot holds dup -> just advance)"
            action = "advance" + tag
        print(f"  {s['i']} |  {s['val']}  |    {s['correct']:>2}    | {action:14} | "
              f"{s['before']} -> {s['after']}")
    print()
    result = cyclic_sort(list(nums))
    print(f"cyclic_sort({nums}) -> {result}   (expected [1, 2, 3, 4, 5])")
    print()
    print(f"Total recorded steps: {len(steps)}; the array of 5 elements needed")
    print(f"only a handful of swaps - each swap resolved exactly one value.")
    print()
    print("--- edge cases ---")
    print(f"  [1]                       -> {cyclic_sort([1])}        (single element, already home)")
    print(f"  [1, 2, 3]                 -> {cyclic_sort([1, 2, 3])}    (already sorted: 0 swaps)")
    print(f"  [5, 4, 3, 2, 1]          -> {cyclic_sort([5, 4, 3, 2, 1])}    (fully reversed)")
    print(f"  [2, 1, 4, 3, 6, 5]       -> {cyclic_sort([2, 1, 4, 3, 6, 5])} (adjacent swaps)")
    print()


# ============================================================================
# SECTION B - P268 MISSING NUMBER (swap-to-place on [0, n], then scan)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P268 Missing Number  (cyclic sort on [0, n] + scan)")
    print("=" * 72)
    print()
    nums = [3, 0, 1]
    print(f"nums = {nums}   (n = {len(nums)}; values from [0, {len(nums)}], one missing)")
    print()
    print("Rule: value v belongs at index v. CAUTION: the value n has NO home")
    print("(index n is out of bounds), so guard every swap with `correct < n`.")
    print()
    print("Swap pass:")
    print()
    steps, missing = trace_missing_number(nums)
    print("  i | val | correct | guard      | before        -> after")
    print("  --+-----+---------+------------+--------------------------------")
    for s in steps:
        guard = f"{s['correct']} < {len(nums)} = {s['correct'] < len(nums)}"
        print(f"  {s['i']} |  {s['val']}  |    {s['correct']:>2}    | {guard:10} | "
              f"{s['before']} -> {s['after']}")
    print()
    print("Scan: find first index j where nums[j] != j.")
    print(f"  -> missing_number({nums}) = {missing}   (expected 2)")
    print()
    print("--- LeetCode canonical inputs ---")
    print(f"  [3, 0, 1]                    -> {missing_number([3, 0, 1])}    (expected 2)")
    print(f"  [0, 1]                       -> {missing_number([0, 1])}    (expected 2; nothing")
    print(f"                                     mismatches, so the answer is n = 2)")
    print(f"  [9, 6, 4, 2, 3, 5, 7, 0, 1] -> {missing_number([9, 6, 4, 2, 3, 5, 7, 0, 1])}    (expected 8)")
    print()
    print("--- the n-has-no-home trap (why the guard matters) ---")
    print("  In [0, 1], value 2 (= n) is in the array. correct = 2 >= n, so the")
    print("  swap is skipped and we advance. Without `correct < n` you'd index")
    print("  nums[n] and crash. The value n simply floats until the final scan.")
    print()


# ============================================================================
# SECTION C - P442 FIND ALL DUPLICATES (negation mark, range [1, n])
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P442 Find All Duplicates  (negation mark, range [1, n])")
    print("=" * 72)
    print()
    nums = [4, 3, 2, 7, 8, 2, 3, 1]
    print(f"nums = {nums}   (n = {len(nums)}; values in [1, {len(nums)}], each once or twice)")
    print()
    print("Rule: for each value v, the slot at v-1 is its 'mailbox'. Scratch it")
    print("(negate it) the first time you see v. If the slot is ALREADY")
    print("negative the next time -> v is a duplicate. Use abs(num) because num")
    print("itself may have been negated by an earlier mark.")
    print()
    print("Negation pass:")
    print()
    steps, dups = trace_find_duplicates(nums)
    print("  k | read | idx | mark? | slot before | after marking   | note")
    print("  --+------+-----+-------+-------------+-----------------+----------------")
    for s in steps:
        if s["dup"]:
            note = f"slot [{s['idx']}] already < 0 -> {s['read']} is a DUPLICATE"
            mark_str = "skip"
            after = s["array_after"]
        else:
            note = f"scratch slot [{s['idx']}]: {s['cell_before']} -> {-s['cell_before']}"
            mark_str = "negate"
            after = s["array_after"]
        print(f"  {s['k']} |   {s['read']}  |  {s['idx']}  | {mark_str:5} | "
              f"{str(s['cell_before']):>11} | {str(after):15} | {note}")
    print()
    result = find_duplicates(list(nums))
    print(f"find_duplicates({nums}) -> {result}   (expected [2, 3])")
    print()
    print("--- edge cases ---")
    print(f"  [1, 1, 2]          -> {find_duplicates([1, 1, 2])}    (expected [1])")
    print(f"  [1]                -> {find_duplicates([1])}    (expected []; no value appears twice)")
    print(f"  [2, 2, 3, 3, 1]    -> {find_duplicates([2, 2, 3, 3, 1])} (expected [2, 3])")
    print()


# ============================================================================
# SECTION D - P448 FIND ALL NUMBERS DISAPPEARED (negation mark, range [1, n])
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - P448 Find All Numbers Disappeared  (negation mark)")
    print("=" * 72)
    print()
    nums = [4, 3, 2, 7, 8, 2, 3, 1]
    print(f"nums = {nums}   (same input as Section C!)")
    print()
    print("Rule: IDENTICAL negate pass to P442 - but do not record duplicates")
    print("mid-pass. After the full pass, any slot still POSITIVE was never")
    print("scratched, so its ball (idx + 1) never appeared in the array.")
    print("Same input, opposite question -> same scratches, different readout.")
    print()
    print("Negation pass:")
    print()
    steps, dis = trace_find_disappeared(nums)
    print("  k | read | idx | mark?   | slot before | after marking")
    print("  --+------+-----+---------+-------------+----------------")
    for s in steps:
        mark_str = "negate" if s["mark"] else "already <0"
        print(f"  {s['k']} |   {s['read']}  |  {s['idx']}  | {mark_str:7} | "
              f"{str(s['cell_before']):>11} | {s['array_after']}")
    print()
    print("Final scan: collect i+1 for every slot still > 0.")
    result = find_disappeared(list(nums))
    print(f"find_disappeared({nums}) -> {result}   (expected [5, 6])")
    print()
    print("--- edge cases ---")
    print(f"  [1, 1]              -> {find_disappeared([1, 1])}    (expected [2])")
    print(f"  [1, 2, 3]           -> {find_disappeared([1, 2, 3])}    (expected []; all present)")
    print(f"  [4, 3, 2, 7, 8, 2, 3, 1] -> {find_disappeared([4, 3, 2, 7, 8, 2, 3, 1])} (expected [5, 6])")
    print()
    print("--- P442 vs P448: two questions, one pass ---")
    print(f"  same input {nums}")
    print(f"    duplicates   (mid-pass)  : {find_duplicates(list(nums))}")
    print(f"    disappeared  (post-pass) : {find_disappeared(list(nums))}")
    print("  Together they fully account for the [1, n] range:")
    print("    every value appears exactly once, is a duplicate, or disappeared.")
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
    print("  Operation                            Time   Space")
    print("  ------------------------------------ ------ ------")
    print("  Cyclic sort 1..n (swap-to-place)     O(n)   O(1)")
    print("  P268 Missing Number ([0,n] sort+scan) O(n)  O(1)")
    print("  P442 Find Duplicates (negation mark) O(n)   O(1) extra")
    print("  P448 Find Disappeared (negation mark) O(n)  O(1) extra")
    print("  Single lookup of 'is value v present' O(n)  O(1)  (one pass)")
    print()
    print("Why nested-while is still O(n)")
    print("------------------------------")
    print("  The outer `while i < n` looks like it could blow up, but EVERY")
    print("  swap places one more value into its final home. There are at most")
    print("  n-1 useful swaps, and i advances n times. So total work <= 2n-1")
    print("  => O(n). Each cell is swapped *to* at most once and *from* at most")
    print("  once.")
    print()
    print("Core identity (memorize)")
    print("------------------------")
    print("  range [1, n] : home index of value v is  v - 1")
    print("  range [0, n] : home index of value v is  v       (v = n has none)")
    print("  nums[idx] *= -1        scratch mailbox idx (idempotent-safe via abs)")
    print("  abs(num) - 1           recover the mailbox AFTER signs are corrupted")
    print("  correct < n            the out-of-bounds guard for the value n in [0, n]")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. THE OUT-OF-BOUNDS SWAP: in range [0, n] the value n would index")
    print("     nums[n] and crash. ALWAYS guard with `correct < n`. In range")
    print("     [1, n] this never happens because v-1 <= n-1.")
    print("  2. ADVANCE i ONLY IN THE else BRANCH: if you `swap; i += 1` you skip")
    print("     checking the new value that just landed at i. Keep re-checking i")
    print("     until it is home, THEN advance.")
    print("  3. FORGETTING abs() IN NEGATION MARK: once signs flip, raw values are")
    print("     corrupted. Index and append with abs(num) - 1 and abs(num). A")
    print("     negative num used as `num - 1` silently hits the WRONG mailbox.")
    print("  4. DUPLICATE vs DISAPPEARED READOUT: finding duplicates means checking")
    print("     if the mailbox is *already* negative MID-pass. Finding disappeared")
    print("     means checking which mailboxes are *still* positive AFTER the pass.")
    print("     Same scratches, opposite detection moment.")
    print("  5. THE 'ALREADY-HOME' DUPLICATE: nums[i] == nums[correct] with")
    print("     correct != i means two slots hold the same value. Swapping would")
    print("     loop forever - so the `if nums[i] != nums[correct]` check doubles")
    print("     as an infinite-loop guard (P442 single-duplicate variant).")
    print("  6. XOR/SUM ALTERNATIVES FOR P268: res = n; for i, x: res ^= i ^ x")
    print("     also finds the missing value in one pass without sorting, avoiding")
    print("     the n*(n+1)/2 overflow trap in C++/Java. But the cyclic-sort")
    print("     approach generalizes to *many* missing/duplicate values.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff  Range  Algorithm         Key trick")
    print("  -------------------------------- ----  -----  ----------------  ----------------------------------")
    print("  P268 Missing Number              Easy  [0,n]  Cyclic sort+scan  guard `correct<n`; 1st nums[j]!=j -> j")
    print("  P442 Find All Duplicates         Med   [1,n]  Negation mark     slot already <0 mid-pass -> abs(num)")
    print("  P448 Find Disappeared            Easy  [1,n]  Negation mark     slot still >0 post-pass -> idx+1")
    print("  P287 Find Duplicate Number       Med   [1,n]  Floyd cycle       slow/fast on value-as-pointer")
    print("  P41  First Missing Positive      Hard  [1,n]  Cyclic sort+scan  ignore <=0 & >n; same scan as P268")
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

    # ---- assertions (mirror LeetCode canonical cases) ----
    # cyclic sort
    assert cyclic_sort([3, 1, 5, 4, 2]) == [1, 2, 3, 4, 5]
    assert cyclic_sort([1]) == [1]
    assert cyclic_sort([1, 2, 3]) == [1, 2, 3]
    assert cyclic_sort([5, 4, 3, 2, 1]) == [1, 2, 3, 4, 5]
    assert cyclic_sort([2, 1, 4, 3, 6, 5]) == [1, 2, 3, 4, 5, 6]

    # P268 missing number
    assert missing_number([3, 0, 1]) == 2
    assert missing_number([0, 1]) == 2
    assert missing_number([9, 6, 4, 2, 3, 5, 7, 0, 1]) == 8
    assert missing_number([0]) == 1
    assert missing_number([1]) == 0

    # P442 find all duplicates
    assert find_duplicates([4, 3, 2, 7, 8, 2, 3, 1]) == [2, 3]
    assert find_duplicates([1, 1, 2]) == [1]
    assert find_duplicates([1]) == []
    assert find_duplicates([2, 2, 3, 3, 1]) == [2, 3]

    # P448 find disappeared
    assert find_disappeared([4, 3, 2, 7, 8, 2, 3, 1]) == [5, 6]
    assert find_disappeared([1, 1]) == [2]
    assert find_disappeared([1, 2, 3]) == []
    assert find_disappeared([1, 1, 2, 2]) == [3, 4]

    # ---- cross-check: present & disappeared partition [1, n]; dups ⊆ present ----
    base = [4, 3, 2, 7, 8, 2, 3, 1]
    n = len(base)
    present = set(base)
    dups = sorted(find_duplicates(list(base)))
    dis = sorted(find_disappeared(list(base)))
    # present and disappeared partition [1, n]
    assert present | set(dis) == set(range(1, n + 1))
    assert present & set(dis) == set()
    # duplicates are a subset of present values
    assert set(dups) <= present
    # each present value appears once or twice: count(once)*1 + count(dups)*2 == n
    once = present - set(dups)
    assert len(once) + 2 * len(dups) == n

    print("=" * 72)
    print("[check] cyclic_sort / missing_number / find_duplicates / find_disappeared ... OK")
    print("=" * 72)
