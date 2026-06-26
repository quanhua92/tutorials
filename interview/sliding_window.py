"""
sliding_window.py - Reference implementation of the sliding window pattern in its
three shapes: fixed-size window, variable-size shrink, and exact-count.

This is the SINGLE SOURCE OF TRUTH for SLIDING_WINDOW.md. Every number, table,
and worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 sliding_window.py > sliding_window_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - the box on a conveyor belt
============================================================================
Picture a BOX of fixed width sitting on a conveyor belt of items. As the belt
moves one step, ONE new item enters the box on the right and ONE old item leaves
on the left. You never re-scan the whole box - you only ever ADD the entering
item and SUBTRACT the leaving item. That incremental update is what turns the
brute-force O(n^2) "try every window" into O(n).

For variable-size windows the box can also GROW (right advances) and SHRINK
(left catches up) - but crucially BOTH pointers only ever move forward, so the
total work across the whole run is at most 2n = O(n).

  * fixed window   : window is always exactly k wide. Add arr[right], remove
                     arr[right - k]. No inner loop.  (P438 anagrams, P239 max.)
  * variable shrink: expand right freely; the moment a constraint is violated,
                     shrink from the left until it is restored.  (P003, P424.)
  * exact count    : "exactly k distinct" / "exactly target sum" - reformulate
                     as atMost(k) - atMost(k-1), or use prefix sums when the
                     array can hold negatives.

THE REASON SLIDING WINDOW EXISTS: when (a) the answer is over CONTIGUUS runs,
(b) you optimize over all windows, and (c) the constraint is MONOTONE (expanding
only ever makes the window "more invalid", shrinking only ever restores it),
you can maintain a LIVE window state and update it incrementally - collapsing
O(n^2) into O(n). Drop any of the three and you need a different tool (DP,
binary-search-on-answer, two converging pointers).

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  window          a contiguous slice [left, right] of the array/string. Both
                  ends inclusive unless noted.
  window state    whatever you must remember to answer in O(1): a running sum,
                  a char-frequency dict, a max_freq counter, a have/need tally.
  invariant       the fact that stays true every loop step. For P003 it is
                  "all chars in [left,right] are distinct". For P424 it is
                  "window_len - max_freq <= k" after the shrink loop. The
                  shrink loop's JOB is to restore the invariant.
  monotone        expanding right cannot flip the window from invalid back to
                  valid. If it can, classic sliding window does not apply and
                  you need the atMostK(k) - atMostK(k-1) trick or prefix sums.
  shrink trigger  for "longest" problems you shrink WHILE invalid then update
                  the answer AFTER. For "shortest" problems you update WHILE
                  valid then shrink. Mixing these is the #1 wrong-answer bug.

============================================================================
THE LOOP (all three variants share this skeleton)
============================================================================
    left = 0
    state = <empty>                # sum, freq dict, counter, ...
    best  = <identity>
    for right in range(len(arr)):
        state.add(arr[right])      # EXPAND: fold in the entering element
        while constraint_violated(state):    # variable windows only
            state.remove(arr[left]); left += 1   # SHRINK: undo the leaving elt
        best = reduce(best, right - left + 1)    # UPDATE from the valid window

KEY FACTS (all verified + asserted in code):
    amortized cost of the inner while loop   <=  n total   (left only advances)
    fixed window: element leaving            =   arr[right - k]   (NOT arr[left])
    P003 long-substring answer on "abcabcbb"  =   3
    P424 char-replacement answer on "AABABBA", k=2  =  5
    P438 anagram start indices on s="cbaebabacd", p="abc"  =  [0, 6]

References:
    LeetCode P003 / P424 / P438 (problem statements).
    Grokking the Coding Interview, "Sliding Window" chapter.
    discussion.md in the source repo for the amortized-analysis argument.
"""

from collections import deque


# ============================================================================
# 0. THE THREE TEMPLATE SKELETONS (memorize these)
# ============================================================================

def template_fixed_window(nums, k):
    """Variant 1: FIXED-size window (size always exactly k).

    No inner while loop. The element leaving is arr[right - k] - NOT arr[left]
    (there is no `left` to track). Use a monotonic deque when you need the
    window MAXIMUM in O(1) amortized; a plain running sum suffices for sums.
    """
    from collections import deque
    if not nums or k <= 0 or k > len(nums):
        return []
    dq = deque()                 # indices, values monotonically decreasing
    out = []
    for right, val in enumerate(nums):
        while dq and nums[dq[-1]] <= val:   # evict smaller: front = window max
            dq.pop()
        dq.append(right)
        while dq[0] <= right - k:           # front fell out the left of window
            dq.popleft()
        if right >= k - 1:                  # window full for the first time
            out.append(nums[dq[0]])
    return out


def template_variable_shrink(s):
    """Variant 2: VARIABLE window, shrink-to-valid (find the LONGEST).

    Expand right freely; the instant the invariant breaks, shrink left until it
    is restored; THEN update the answer. Answer update MUST sit after the while.
    """
    last = {}                    # window state: char -> last index seen
    left = 0
    best = 0
    for right, ch in enumerate(s):
        # invariant about to break? jump left past the previous occurrence
        if ch in last and last[ch] >= left:
            left = last[ch] + 1
        last[ch] = right
        best = max(best, right - left + 1)   # UPDATE after the window is valid
    return best


def template_exact_count(nums, target):
    """Variant 3: EXACT condition via prefix sums (handles negatives).

    'Number of subarrays summing to exactly target' is NOT monotone when values
    can be negative, so the classic shrink fails. Instead count, at each right,
    how many earlier prefix sums equal (running_sum - target).
    """
    seen = {0: 1}                # prefix_sum -> count of occurrences
    running = 0
    total = 0
    for val in nums:
        running += val
        total += seen.get(running - target, 0)
        seen[running] = seen.get(running, 0) + 1
    return total


# ============================================================================
# 1. THE THREE PROBLEMS (canonical LeetCode solutions)
# ============================================================================

def longest_substring_no_repeat(s):
    """P003 Longest Substring Without Repeating Characters (variable shrink).

    State: dict mapping each char to the last index where it appeared.
    When s[right] already lives inside [left, right], jump left just past it.
    """
    last = {}
    left = 0
    best = 0
    for right, ch in enumerate(s):
        if ch in last and last[ch] >= left:
            left = last[ch] + 1
        last[ch] = right
        best = max(best, right - left + 1)
    return best


def character_replacement(s, k):
    """P424 Longest Repeating Character Replacement (variable + counter).

    A window [left, right] can be made all-one-char with k swaps iff
        window_len - max_freq  <=  k
    where max_freq is the count of the most frequent char IN the window. Shrink
    while that fails. (max_freq is recomputed honestly here so the trace is
    faithful; the O(n) "max_freq never decreases" shortcut is noted in the .md.)
    """
    freq = {}
    left = 0
    best = 0
    for right, ch in enumerate(s):
        freq[ch] = freq.get(ch, 0) + 1
        while (right - left + 1) - max(freq.values()) > k:
            freq[s[left]] -= 1
            if freq[s[left]] == 0:
                del freq[s[left]]
            left += 1
        best = max(best, right - left + 1)
    return best


def find_anagrams(s, p):
    """P438 Find All Anagrams in a String (fixed window + frequency match).

    Fixed window of size len(p). Maintain the running freq of the window and
    compare to freq(p). Deleting keys that hit 0 makes dict == dict work.
    """
    from collections import Counter
    need = len(p)
    if len(s) < need:
        return []
    target = Counter(p)
    window = Counter(s[:need])
    starts = []
    for left in range(0, len(s) - need + 1):
        right = left + need - 1
        if left > 0:                       # roll the window one step right
            window[s[left - 1]] -= 1
            if window[s[left - 1]] == 0:
                del window[s[left - 1]]
            window[s[right]] += 1
        if window == target:
            starts.append(left)
    return starts


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

BANNER = "=" * 72


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_window(s: str, left: int, right: int) -> str:
    """Render s with the live window [left..right] wrapped in [ ]."""
    out = []
    for i, ch in enumerate(s):
        if i == left:
            out.append("[")
        out.append(ch)
        if i == right:
            out.append("]")
    if right == len(s) - 1:                # window reaches the end
        pass
    return "".join(out)


# ============================================================================
# 3. THE WORKED EXAMPLES
# ============================================================================

def section_template():
    banner("SECTION A: the three template skeletons")
    print("Every sliding-window problem is one of three shapes. Memorize the")
    print("skeleton for each; the problems are just a different `state` and a")
    print("different `constraint_violated` test.\n")

    print("-- variant 1: FIXED-size window (size exactly k) --")
    arr = [1, 3, -1, -3, 5, 3, 6, 7]
    k = 3
    mx = template_fixed_window(arr, k)
    print(f"  arr = {arr},  k = {k}")
    print(f"  template_fixed_window -> max of each size-{k} window = {mx}")
    print("  trick: monotonic deque evicts smaller values; front = window max.")
    print("  leaving element is arr[right - k], NOT arr[left] (no left tracked).\n")

    print("-- variant 2: VARIABLE shrink (find the LONGEST valid window) --")
    s = "abcabcbb"
    ans = template_variable_shrink(s)
    print(f"  s = {s!r}")
    print(f"  template_variable_shrink (here: longest all-distinct) = {ans}")
    print("  trick: expand right freely; while invalid, drop arr[left] & left+=1;")
    print("  update answer AFTER the while loop, never inside it.\n")

    print("-- variant 3: EXACT count via prefix sums (handles negatives) --")
    nums = [1, 1, 1]
    target = 2
    cnt = template_exact_count(nums, target)
    print(f"  nums = {nums},  target = {target}")
    print(f"  template_exact_count -> subarrays summing to {target} = {cnt}")
    print("  trick: 'exactly target' is NOT monotone with negatives, so the")
    print("  shrink fails; count prefix sums equal to (running - target) instead.\n")

    # self-check on the templates themselves
    assert mx == [3, 3, 5, 5, 6, 7]
    assert ans == 3
    assert cnt == 2
    print("[check] template skeletons produce correct values:  OK")


def section_p003():
    banner("SECTION B: P003 Longest Substring Without Repeating Characters")
    s = "abcabcbb"
    print(f"Problem: length of the longest substring of {s!r} with all chars")
    print("distinct.  Shape: VARIABLE shrink.  State: char -> last index seen.")
    print("Invariant: every char inside [left, right] is unique.\n")
    print("Trace (right scans 0..n-1; `left` jumps past any duplicate):\n")
    print(f"  {'r':>2}  {'ch':>3}  {'window':<14} {'len':>4}  {'best':>4}   note")
    print("  " + "-" * 64)

    last = {}
    left = 0
    best = 0
    for right, ch in enumerate(s):
        note = ""
        if ch in last and last[ch] >= left:
            note = f"dup of s[{last[ch]}] in window -> left := {last[ch]}+1 = {last[ch] + 1}"
            left = last[ch] + 1
        last[ch] = right
        cur = right - left + 1
        best = max(best, cur)
        win = fmt_window(s, left, right)
        print(f"  {right:>2}  {ch:>3}  {win:<14} {cur:>4}  {best:>4}   {note}")

    final = longest_substring_no_repeat(s)
    print(f"\n  -> longest_substring_no_repeat({s!r}) = {final}")
    print("Read it: the window grows to 3 ('abc') and then NEVER grows again -")
    print("every later step just slides that size-3 window along the string.")
    print("left only ever moves RIGHT, so the total work is <= 2n = O(n).\n")
    assert final == 3
    print("[check] P003 answer == 3:  OK")


def section_p424():
    banner("SECTION C: P424 Longest Repeating Character Replacement")
    s = "AABABBA"
    k = 2
    print(f"Problem: longest substring of {s!r} you can make all-one-letter by")
    print(f"changing at most k={k} characters.")
    print("Shape: VARIABLE shrink + a frequency counter.")
    print("Key identity: a window can be unified with <= k swaps IFF")
    print("    window_len - max_freq <= k")
    print("where max_freq = count of the most frequent char IN the window.\n")
    print("Trace (recompute max_freq honestly each step so it stays faithful):\n")
    header = (f"  {'r':>2}  {'ch':>3}  {'window':<12} {'len':>3}  "
              f"{'maxf':>4}  {'len-maxf':>8}  {'ok?':>4}  note")
    print(header)
    print("  " + "-" * 70)

    freq = {}
    left = 0
    best = 0
    for right, ch in enumerate(s):
        freq[ch] = freq.get(ch, 0) + 1
        maxf = max(freq.values())
        note = ""
        while (right - left + 1) - max(freq.values()) > k:
            gap = (right - left + 1) - max(freq.values())
            note = f"len-maxf={gap} > {k}: drop s[{left}]={s[left]!r}, left:= {left + 1}"
            freq[s[left]] -= 1
            if freq[s[left]] == 0:
                del freq[s[left]]
            left += 1
            maxf = max(freq.values())
        cur = right - left + 1
        best = max(best, cur)
        gap = cur - maxf
        ok = "ok" if gap <= k else "BAD"
        win = fmt_window(s, left, right)
        print(f"  {right:>2}  {ch:>3}  {win:<12} {cur:>3}  {maxf:>4}  "
              f"{gap:>8}  {ok:>4}  {note}")

    final = character_replacement(s, k)
    print(f"\n  -> character_replacement({s!r}, k={k}) = {final}")
    print("Read it: the window reaches width 5 at r=4 ('AABAB') and stays at 5;")
    print("each later invalid step just slides it right. The optimal substring")
    print("is 'BABBA' / 'AABAB' unified to 'BBBBB' / 'AAAAA' with 2 changes.\n")
    print("OPTIMIZATION (the famous trick): max_freq never needs to DECREASE.")
    print("Keep a running max and never lower it - a stale (too-high) max_freq")
    print("only makes the validity check STRICTER, which can never over-count.")
    print("That lets you drop the inner recomputation and the honest shrink,\n"
          "  yielding the one-pass `left += 1` version in O(n).")
    assert final == 5
    print("[check] P424 answer == 5:  OK")


def section_p438():
    banner("SECTION D: P438 Find All Anagrams in a String")
    s = "cbaebabacd"
    p = "abc"
    print(f"Problem: all start indices in s={s!r} of substrings that are")
    print(f"anagrams of p={p!r}.  Shape: FIXED window of size len(p)={len(p)}.")
    print("State: running freq dict of the current window vs freq(p).")
    print("Trick: DELETE keys whose count hits 0 so dict == dict is meaningful.\n")
    print("Trace (window = s[left .. left+len(p)-1]; compare to freq(p)):\n")
    print(f"  {'left':>4}  {'window':<10}  {'freq(window)':<26}  match?")
    print("  " + "-" * 58)

    from collections import Counter
    need = len(p)
    target = Counter(p)
    window = Counter(s[:need])
    starts = []
    for left in range(0, len(s) - need + 1):
        right = left + need - 1
        if left > 0:
            window[s[left - 1]] -= 1
            if window[s[left - 1]] == 0:
                del window[s[left - 1]]
            window[s[right]] += 1
        sub = s[left:right + 1]
        match = window == target
        if match:
            starts.append(left)
        # render freq dict sorted by key for a stable, readable display
        freq_str = "{" + ", ".join(f"{c}:{window[c]}" for c in sorted(window)) + "}"
        mark = "YES <- record" if match else "no"
        print(f"  {left:>4}  {sub:<10}  {freq_str:<26}  {mark}")

    final = find_anagrams(s, p)
    print(f"\n  -> find_anagrams({s!r}, {p!r}) = {final}")
    print("Read it: only left=0 ('cba') and left=6 ('bac') are rearrangements of")
    print("'abc'. The fixed window rolls one step per iteration - add s[right],")
    print("remove s[left-1] - so each comparison is O(1) work on top of the")
    print("O(|alphabet|) dict equality. Overall O(|s| * |alphabet|) = O(n).\n")
    assert final == [0, 6]
    print("[check] P438 answer == [0, 6]:  OK")


def section_gold():
    banner("SECTION E: GOLD values (pinned for sliding_window.html)")
    # The .html recomputes these on the SAME inputs in JS and checks them.
    a3 = longest_substring_no_repeat("abcabcbb")
    a3b = longest_substring_no_repeat("bbbbb")
    c424 = character_replacement("AABABBA", 2)
    c438 = find_anagrams("cbaebabacd", "abc")
    t_fixed = template_fixed_window([1, 3, -1, -3, 5, 3, 6, 7], 3)
    print(f'longest_substring_no_repeat("abcabcbb") = {a3}')
    print(f'longest_substring_no_repeat("bbbbb")    = {a3b}')
    print('GOLD P003 answer: 3')
    print(f'character_replacement("AABABBA", 2)     = {c424}')
    print('GOLD P424 answer: 5')
    print(f'find_anagrams("cbaebabacd", "abc")       = {c438}')
    print('GOLD P438 answer: [0, 6]')
    print(f'template_fixed_window max-of-each-3      = {t_fixed}')
    print('GOLD fixed-window maxes: [3, 3, 5, 5, 6, 7]')
    # self-consistency asserts - these ARE the gold values
    assert a3 == 3
    assert a3b == 1
    assert c424 == 5
    assert c438 == [0, 6]
    assert t_fixed == [3, 3, 5, 5, 6, 7]
    print("\n[check] all GOLD values reproduce from the implementations:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("sliding_window.py - reference impl. All numbers below feed "
          "SLIDING_WINDOW.md.")
    section_template()
    section_p003()
    section_p424()
    section_p438()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
