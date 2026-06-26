"""
monotonic_stack.py - Reference implementation of Monotonic Stack for:
  * Ascending stack, next-greater distance (P739 Daily Temperatures)
  * Area contribution + sentinel   (P084 Largest Rectangle in Histogram)
  * Circular next-greater element   (P503 Next Greater Element II)

This is the SINGLE SOURCE OF TRUTH for MONOTONIC_STACK.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 monotonic_stack.py > monotonic_stack_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - a line of people waiting for a taller friend
============================================================================
A monotonic stack remembers elements that are "waiting" for a future
condition. Picture a queue of people sorted by arrival. Each newcomer scans
the line and answers the question for every shorter person standing there:
"I am the taller person you were waiting for." Those shorter people leave
(having been resolved); the newcomer then joins the end of the line.

Every problem below is the SAME loop body:

    for each element i (left to right):
        while stack is non-empty and element i BREAKS the monotonic order:
            j = stack.pop()              # RESOLVE j: i is its answer
            compute(j, i, stack_top)     # distance / area / next-greater
        stack.append(i)                  # i now waits for ITS answer

Three facts make this O(n), not O(n^2), despite the inner while:
  1. Each index is pushed exactly ONCE (append happens once per iteration).
  2. Each index is popped at most ONCE (a popped element never returns).
  3. So total push + pop <= 2n across the whole run => amortized O(n).

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  monotonic stack      a stack kept in sorted order bottom-to-top. Either
                       strictly increasing (next greater) or strictly
                       decreasing (next smaller). "Strictly" means the
                       incoming element pops elements that are <= (or >=).
  ascending stack      values increase bottom-to-top. Pop when incoming >
                       top. The incoming element IS the next-greater for
                       everything it pops. Used by P739 and P503.
  store INDICES        the golden rule. A stack of values cannot compute
                       distance (i - j) or rectangle width. ALWAYS push
                       indices; read values as arr[idx]. Storing values is
                       the #1 candidate mistake.
  sentinel             append a height of 0 to the histogram array so every
                       bar still on the stack at the end is forced to pop
                       (height 0 < every real height). Avoids a separate
                       post-loop flush and the bugs that come from forgetting
                       it. Used by P084.
  circular pass        for a circular next-greater, loop 2*n times with
                       idx = i % n. Push ONLY on the first pass (i < n) so no
                       index enters the stack twice. Used by P503.
  resolve / pop        the moment an index's answer is computed. For P739 the
                       answer is the distance i - j; for P084 it is the area
                       of the rectangle whose height is arr[j]; for P503 it
                       is the value arr[i].

============================================================================
THE SKELETON (memorize the while + append pair)
============================================================================
    def monotonic(arr):
        ans  = [default] * len(arr)
        st   = []                       # stores INDICES
        for i in range(len(arr)):
            while st and arr[i] violates_order(arr[st[-1]]):
                j = st.pop()            # RESOLVE j
                ans[j] = ... i, j, st[-1] ...
            st.append(i)
        return ans                       # leftovers keep the default
"""

from __future__ import annotations


# ============================================================================
# TEMPLATE 1 - ASCENDING STACK: next-greater DISTANCE (P739 Daily Temperatures)
# ============================================================================
def daily_temperatures(temperatures: list[int]) -> list[int]:
    """For each day, how many days until a strictly warmer day (0 if none).

    Ascending (strictly-decreasing-by-value) stack of indices. When day i is
    warmer than the index on top, that top index is RESOLVED: the gap is i-j.

    Time:  O(n) amortized -- each index pushed once, popped once
    Space: O(n) worst case (a strictly decreasing run fills the stack)
    """
    n = len(temperatures)
    answer: list[int] = [0] * n
    stack: list[int] = []
    for i in range(n):
        while stack and temperatures[i] > temperatures[stack[-1]]:
            j = stack.pop()
            answer[j] = i - j
        stack.append(i)
    return answer


def trace_daily_temperatures(temperatures: list[int]) -> list[dict]:
    """Capture the push / pop / leftover events so the printer (and the HTML
    viz) can step through the stack one element at a time."""
    events: list[dict] = []
    n = len(temperatures)
    answer = [0] * n
    stack: list[int] = []
    for i in range(n):
        while stack and temperatures[i] > temperatures[stack[-1]]:
            j = stack.pop()
            answer[j] = i - j
            events.append({
                "kind": "pop", "i": i, "j": j,
                "ans": answer[:], "stack": stack[:],
                "note": (f"pop idx {j} ({temperatures[j]})  ->  warmer day {i} "
                         f"({temperatures[i]}), gap {i - j}   ans[{j}]={i - j}"),
            })
        stack.append(i)
        vals = [temperatures[s] for s in stack]
        events.append({
            "kind": "push", "i": i,
            "ans": answer[:], "stack": stack[:],
            "note": f"push idx {i} ({temperatures[i]})   stack(by val)={vals}",
        })
    events.append({
        "kind": "done", "ans": answer[:], "stack": stack[:],
        "note": f"leftovers {stack} have no warmer day  ->  keep default 0",
    })
    return events


# ============================================================================
# TEMPLATE 2 - AREA CONTRIBUTION + SENTINEL (P084 Largest Rectangle)
# ============================================================================
def largest_rectangle(heights: list[int]) -> int:
    """Largest rectangle area in a histogram of unit-width bars.

    Ascending stack of indices. When a bar i is SHORTER than the bar on top,
    that top bar's rectangle cannot extend past i, so we RESOLVE it: its
    height is fixed, its width spans from the index below it on the stack to
    i (exclusive). A sentinel height 0 flushes the stack at the very end.

    Time:  O(n) amortized
    Space: O(n)
    """
    h = heights + [0]                       # sentinel flushes the stack
    stack: list[int] = []
    max_area = 0
    for i in range(len(h)):
        while stack and h[i] < h[stack[-1]]:
            top = stack.pop()
            height = h[top]
            width = i if not stack else i - stack[-1] - 1
            max_area = max(max_area, height * width)
        stack.append(i)
    return max_area


def trace_largest_rectangle(heights: list[int]) -> list[dict]:
    events: list[dict] = []
    h = heights + [0]
    stack: list[int] = []
    max_area = 0
    best: tuple | None = None
    for i in range(len(h)):
        is_sentinel = i == len(heights)
        while stack and h[i] < h[stack[-1]]:
            top = stack.pop()
            height = h[top]
            width = i if not stack else i - stack[-1] - 1
            area = height * width
            grew = area > max_area
            if grew:
                max_area = area
                best = (top, height, width, area)
            left = "stack empty" if not stack else f"left boundary idx {stack[-1]}"
            events.append({
                "kind": "pop", "i": i, "top": top,
                "height": height, "width": width, "area": area,
                "max": max_area, "stack": stack[:], "grew": grew,
                "note": (f"pop idx {top} (h={height})  ->  width={width} "
                         f"({left} .. right {i})  area {height}x{width}={area}"
                         + ("   *** new max ***" if grew else "")),
            })
        stack.append(i)
        if is_sentinel:
            events.append({
                "kind": "sentinel", "i": i, "max": max_area, "stack": stack[:],
                "note": "sentinel h=0 appended  ->  forces a final stack flush",
            })
        else:
            events.append({
                "kind": "push", "i": i, "h": h[i],
                "max": max_area, "stack": stack[:],
                "note": f"push idx {i} (h={h[i]})   stack={stack}",
            })
    events.append({
        "kind": "done", "max": max_area, "best": best,
        "note": (f"max area = {max_area}" +
                 ("" if best is None else f"   (bar idx {best[0]} h={best[1]} x w={best[2]})")),
    })
    return events


# ============================================================================
# TEMPLATE 3 - CIRCULAR NEXT-GREATER (P503 Next Greater Element II)
# ============================================================================
def next_greater_circular(nums: list[int]) -> list[int]:
    """Next greater element to the right, treating the array as circular.

    Loop 2*n times with idx = i % n; PUSH only on the first pass (i < n) so
    no index is stacked twice. Remaining indices after the second pass keep
    -1 (no greater element exists anywhere in the circle).

    Time:  O(n) amortized -- 2n iterations, but <= n pushes and <= n pops
    Space: O(n)
    """
    n = len(nums)
    answer: list[int] = [-1] * n
    stack: list[int] = []
    for i in range(2 * n):
        idx = i % n
        while stack and nums[idx] > nums[stack[-1]]:
            j = stack.pop()
            answer[j] = nums[idx]
        if i < n:
            stack.append(idx)
    return answer


def trace_next_greater_circular(nums: list[int]) -> list[dict]:
    events: list[dict] = []
    n = len(nums)
    answer = [-1] * n
    stack: list[int] = []
    for i in range(2 * n):
        idx = i % n
        passed = 2 if i >= n else 1
        while stack and nums[idx] > nums[stack[-1]]:
            j = stack.pop()
            answer[j] = nums[idx]
            events.append({
                "kind": "pop", "i": i, "idx": idx, "j": j, "pass": passed,
                "ans": answer[:], "stack": stack[:],
                "note": (f"pass {passed}, visit idx {idx} (val {nums[idx]})  ->  "
                         f"pop idx {j}, next greater = {nums[idx]}   ans[{j}]={nums[idx]}"),
            })
        if i < n:
            stack.append(idx)
            events.append({
                "kind": "push", "i": i, "idx": idx, "pass": passed,
                "ans": answer[:], "stack": stack[:],
                "note": f"pass 1, push idx {idx} (val {nums[idx]})   stack={stack}",
            })
        else:
            events.append({
                "kind": "peek", "i": i, "idx": idx, "pass": passed,
                "ans": answer[:], "stack": stack[:],
                "note": (f"pass 2, re-visit idx {idx} (val {nums[idx]})  "
                         f"-- NO push (already stacked once)"),
            })
    events.append({
        "kind": "done", "ans": answer[:],
        "note": f"leftovers keep -1  ->  ans = {answer}",
    })
    return events


# ============================================================================
# EVENT PRINTER (shared by all sections - renders the stack trace)
# ============================================================================
_KIND_MARKER = {
    "push":     "[+]",   # index appended to the stack
    "pop":      "[*]",   # index resolved (answer computed)
    "sentinel": "[0]",   # sentinel bar appended
    "peek":     "[.]",   # circular 2nd-pass revisit, no push
    "done":     "[=]",   # end of run
}


def print_events(events: list[dict]) -> None:
    """Render the stack trace as a flat event stream."""
    for e in events:
        marker = _KIND_MARKER.get(e["kind"], "[?]")
        print(f"  {marker} {e['note']}")


def summarize_events(events: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


# ============================================================================
# SECTION A - P739 DAILY TEMPERATURES (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P739 Daily Temperatures  (ascending stack, store INDICES)")
    print("=" * 72)
    print()
    temps = [73, 74, 75, 71, 69, 72, 76, 73]
    print(f"temperatures = {temps}   (for each day, days until a warmer day)")
    print()
    print("Ascend left to right with a strictly-decreasing-by-value stack of")
    print("INDICES. The moment day i is warmer than the index on top, that top")
    print("index is RESOLVED and the gap i - j is its answer.")
    print()
    print("Stack trace (push / pop; a pop means an answer was just filled in):")
    print()
    events = trace_daily_temperatures(temps)
    print_events(events)
    print()
    counts = summarize_events(events)
    pushes = counts.get("push", 0)
    pops = counts.get("pop", 0)
    print(f"  stats: {pushes} pushes, {pops} pops, "
          f"{pushes - pops} leftovers (no warmer day, default 0)")
    print(f"  => total ops {pushes + pops} <= 2*{len(temps)}  ->  amortized O(n)")
    print()
    result = daily_temperatures(temps)
    print(f"daily_temperatures({temps}) -> {result}")
    print()
    print("--- edge cases ---")
    print(f"  [30,40,50,60] -> {daily_temperatures([30,40,50,60])}  "
          f"(strictly rising: every day resolved by the next, last = 0)")
    print(f"  [30,60,90]    -> {daily_temperatures([30,60,90])}    "
          f"(last day never warmer -> 0)")
    print(f"  [90,60,30]    -> {daily_temperatures([90,60,30])}    "
          f"(strictly falling: stack fills to n, all default 0)")
    print()


# ============================================================================
# SECTION B - P084 LARGEST RECTANGLE IN HISTOGRAM (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P084 Largest Rectangle in Histogram  (area contribution)")
    print("=" * 72)
    print()
    heights = [2, 1, 5, 6, 2, 3]
    print(f"heights = {heights}   (bar width = 1; find the biggest rectangle)")
    print()
    print("Ascending stack. When bar i is SHORTER than the bar on top, the top")
    print("bar's rectangle cannot extend past i -> RESOLVE it:")
    print("  height = heights[popped]")
    print("  width  = i - stack[-1] - 1   (left boundary is the bar BELOW it")
    print("           still on the stack; right boundary is i). NOT i - popped.")
    print("Append a sentinel height 0 so every leftover bar is flushed at the")
    print("end (no separate post-loop pass, no forgotten-flush bug).")
    print()
    print("Stack trace (push / pop; each pop computes one candidate area):")
    print()
    events = trace_largest_rectangle(heights)
    print_events(events)
    print()
    print()
    result = largest_rectangle(heights)
    print(f"largest_rectangle({heights}) -> {result}   (bar h=5 spanning idx 2,3: 5x2)")
    print()
    print("--- edge cases ---")
    print(f"  [2, 4]         -> {largest_rectangle([2, 4])}    "
          f"(bar h=4 alone = 4  >  bar h=4 + bar h=2 = 4)")
    print(f"  [2, 1, 2]      -> {largest_rectangle([2, 1, 2])}    "
          f"(short bar h=1 spans all three: 1x3 = 3)")
    print(f"  [1, 2, 3, 4, 5]-> {largest_rectangle([1, 2, 3, 4, 5])}    "
          f"(strictly rising: ZERO pops in the loop; the sentinel flushes")
    print(f"                   everything at the end -> max = 3x3 = 9. This is")
    print(f"                   exactly why the sentinel is mandatory.)")
    print()


# ============================================================================
# SECTION C - P503 NEXT GREATER ELEMENT II (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P503 Next Greater Element II  (circular next-greater)")
    print("=" * 72)
    print()
    nums = [1, 2, 1]
    print(f"nums = {nums}   (next greater element, treating the array circular)")
    print()
    print("Loop 2*n times with idx = i % n to simulate wrapping around once.")
    print("PUSH only when i < n (first pass) so each index enters the stack at")
    print("most once. The second pass only POPS (resolving leftovers via the")
    print("values it re-visits). Anything still unresolvable keeps -1.")
    print()
    print("Stack trace (pass 1 = first lap pushes; pass 2 = second lap resolves):")
    print()
    events = trace_next_greater_circular(nums)
    print_events(events)
    print()
    result = next_greater_circular(nums)
    print(f"next_greater_circular({nums}) -> {result}")
    print()
    print("--- edge cases ---")
    print(f"  [1, 2, 3, 4, 3] -> {next_greater_circular([1, 2, 3, 4, 3])}  "
          f"(4 is the global max -> -1; the rest wrap to find their greater)")
    print(f"  [5, 4, 3, 2, 1] -> {next_greater_circular([5, 4, 3, 2, 1])}  "
          f"(descending: pass 1 fills the stack, pass 2 wraps 5 to the front)")
    print(f"  [1]             -> {next_greater_circular([1])}    "
          f"(single element, nothing is greater -> [-1])")
    print()


# ============================================================================
# SECTION D - COMPLEXITY, GOTCHAS, PROBLEM TABLE
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Operation                          Time         Space")
    print("  ---------------------------------- ------------ --------")
    print("  Daily Temperatures, next greater   O(n) amort.  O(n)")
    print("  Largest Rectangle + sentinel       O(n) amort.  O(n)")
    print("  Next Greater Element II (circular) O(n) amort.  O(n)")
    print("  Previous smaller / next smaller    O(n) amort.  O(n)")
    print("  Sliding window max (monotonic dq)  O(n) amort.  O(k)")
    print()
    print("  Amortized O(n): each index is pushed ONCE and popped AT MOST once,")
    print("  so total stack operations <= 2n regardless of the inner while loop.")
    print()
    print("The universal skeleton (memorize the while + append pair)")
    print("---------------------------------------------------------")
    print("  def monotonic(arr):")
    print("      ans = [default] * len(arr)")
    print("      st  = []                       # store INDICES, not values")
    print("      for i in range(len(arr)):")
    print("          while st and arr[i] violates(arr[st[-1]]):")
    print("              j = st.pop()           # RESOLVE j -> i is its answer")
    print("              ans[j] = ... i, j, st[-1] ...")
    print("          st.append(i)")
    print("      return ans                      # leftovers keep the default")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. STORE INDICES, NOT VALUES. A value stack cannot compute a")
    print("     distance (i - j) or a rectangle width. Values are always")
    print("     recoverable as arr[idx]; position is NOT. This is the #1 mistake.")
    print("  2. RECTANGLE WIDTH IS i - stack[-1] - 1 (the bar BELOW the popped")
    print("     one still on the stack), NOT i - popped. The left boundary is")
    print("     defined by the element that REMAINS beneath it on the stack.")
    print("  3. THE SENTINEL. For histogram/rectangle problems always append a")
    print("     height 0 so the stack is fully flushed at the end. Without it,")
    print("     a strictly rising input like [1,2,3,4,5] never pops in the loop")
    print("     and you miss every area (you'd need a separate post-loop pass).")
    print("  4. CIRCULAR = PUSH ONLY ON PASS 1. Loop 2*n with idx = i % n, but")
    print("     append only when i < n. Pushing twice double-counts and breaks")
    print("     the once-per-index invariant that guarantees O(n).")
    print("  5. ASCENDING vs DESCENDING. An ASCENDING stack (values rise to the")
    print("     top) pops when incoming > top -> next GREATER. A DESCENDING stack")
    print("     pops when incoming < top -> next SMALLER. Reversing the sign")
    print("     silently answers the wrong question.")
    print("  6. STRICT vs NON-STRICT (< vs <=). For distances/next-greater use")
    print("     strict (equal values are independent). For subarray-contribution")
    print("     de-duplication use one pass strict and the other inclusive to")
    print("     avoid double-counting equal elements.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                       Diff  Key trick")
    print("  ----------------------------- ----  ----------------------------------------")
    print("  P739 Daily Temperatures       Med   decreasing-by-value stack of INDICES; ans[j]=i-j")
    print("  P084 Largest Rectangle        Hard  ascending stack + sentinel 0; width=i-st[-1]-1")
    print("  P503 Next Greater II          Med   loop 2n, idx=i%n; push only when i<n")
    print("  P496 Next Greater I           Easy  hashmap of the subsequence + monotonic stack")
    print("  P901 Online Stock Span        Med   stack of (price, span); accumulate spans on pop")
    print("  P907 Sum of Subarray Mins     Med   two passes (left < and right <=); contribution product")
    print("  P042 Trapping Rain Water      Hard  monotonic stack OR two pointers; pop & add layers")
    print("  P456 132 Pattern              Med   scan backwards; stack tracks the max '2', third the '3'")
    print("  P853 Car Fleet                Med   sort by position desc; count times time > slowest")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions (mirror LeetCode canonical test cases) ----
    # P739 Daily Temperatures
    assert daily_temperatures([73, 74, 75, 71, 69, 72, 76, 73]) == [1, 1, 4, 2, 1, 1, 0, 0]
    assert daily_temperatures([30, 40, 50, 60]) == [1, 1, 1, 0]
    assert daily_temperatures([30, 60, 90]) == [1, 1, 0]
    assert daily_temperatures([90, 60, 30]) == [0, 0, 0]

    # P084 Largest Rectangle in Histogram
    assert largest_rectangle([2, 1, 5, 6, 2, 3]) == 10
    assert largest_rectangle([2, 4]) == 4
    assert largest_rectangle([2, 1, 2]) == 3
    assert largest_rectangle([1, 2, 3, 4, 5]) == 9
    assert largest_rectangle([0, 9]) == 9
    assert largest_rectangle([]) == 0

    # P503 Next Greater Element II
    assert next_greater_circular([1, 2, 1]) == [2, -1, 2]
    assert next_greater_circular([1, 2, 3, 4, 3]) == [2, 3, 4, -1, 4]
    assert next_greater_circular([5, 4, 3, 2, 1]) == [-1, 5, 5, 5, 5]
    assert next_greater_circular([1]) == [-1]

    # ---- cross-check: trace event stats obey the O(n) invariant ----
    for temps in ([73, 74, 75, 71, 69, 72, 76, 73], [90, 60, 30], [30, 60, 90]):
        ev = trace_daily_temperatures(temps)
        c = summarize_events(ev)
        pushes, pops = c.get("push", 0), c.get("pop", 0)
        assert pushes == len(temps)                    # exactly one push per index
        assert pushes - pops >= 0                      # pops never exceed pushes
        assert pushes + pops <= 2 * len(temps)         # amortized O(n)

    print("=" * 72)
    print("[check] daily_temperatures / largest_rectangle / next_greater_circular ... OK")
    print("=" * 72)
