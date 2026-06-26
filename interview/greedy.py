"""
greedy.py - Reference implementation of Greedy algorithms for:
  * Max-reach tracking      (P055 Jump Game)
  * Activity selection      (P452 Min Arrows to Burst Balloons)
  * Surplus tracking        (P134 Gas Station)

This is the SINGLE SOURCE OF TRUTH for GREEDY.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 greedy.py > greedy_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - the best choice RIGHT NOW is the best choice
============================================================================
Greedy makes the locally optimal choice at every step and never looks back.
Unlike dynamic programming, it never reconsiders a past decision and never
explores the whole space. This only works when the problem has the
GREEDY-CHOICE PROPERTY: a locally optimal step can never block a globally
optimal solution. When that property holds, one linear (or n log n) sweep
beats the exponential / quadratic DP.

The three flavors in this bundle each keep ONE running scalar and update it
in place:

    MAX-REACH     (Jump Game)      how far can I get so far?
    FRONTIER      (Min Arrows)     where did my last greedy pick end?
    SURPLUS       (Gas Station)    am I still in the black?

There is no recursion and no memo table - that is the whole point. The proof
of correctness is the EXCHANGE ARGUMENT: assume an optimum differs from the
greedy choice at some step, then show you can swap the greedy choice in
without making the solution worse. If you can always swap, greedy IS optimal.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  greedy-choice property   the promise that a locally best move can never
                           rule out a globally best solution. Without it,
                           greedy is just a heuristic that may fail.
  exchange argument        the standard proof technique. Take any optimum,
                           find its first deviation from greedy, swap greedy
                           in, show the result is no worse. Repeat.
  max_reach                the farthest index reachable so far. If the scan
                           index ever passes it, you are stuck.
  frontier / arrow_pos     the end coordinate of the last greedy pick.
                           Everything overlapping it is handled for free.
  surplus                  gas[i] - cost[i]. total_surplus decides feasibility;
                           current_surplus decides where to (re)start.
  sort by END              the non-negotiable first move for interval greedy.
                           Sorting by start fails on nested intervals.

============================================================================
THE THREE TEMPLATES (memorize the one-liner update in each)
============================================================================
    # MAX-REACH  - can I get to the end?
    def can_jump(nums):
        max_reach = 0
        for i, jump in enumerate(nums):
            if i > max_reach: return False
            max_reach = max(max_reach, i + jump)
        return True

    # ACTIVITY SELECTION - fewest arrows / most non-overlapping
    def min_arrows(points):
        if not points: return 0
        points.sort(key=lambda x: x[1])      # SORT BY END
        arrows, arrow_pos = 1, points[0][1]
        for start, end in points[1:]:
            if start > arrow_pos:            # needs its own arrow
                arrows += 1
                arrow_pos = end
        return arrows

    # SURPLUS - find the valid starting station
    def can_complete_circuit(gas, cost):
        total = current = start = 0
        for i in range(len(gas)):
            diff = gas[i] - cost[i]
            total += diff
            current += diff
            if current < 0:                  # this start failed
                start = i + 1
                current = 0
        return start if total >= 0 else -1
"""

from __future__ import annotations


# ============================================================================
# TEMPLATE 1 - MAX-REACH TRACKING  (P055 Jump Game)
# ============================================================================
def jump_game(nums: list[int]) -> bool:
    """Can you reach the last index, where nums[i] is the max jump length?

    Greedy: track the farthest index reachable so far. The moment the scan
    index passes max_reach, no path exists. We never care WHICH jump we took
    - only the envelope of reachable positions.

    Time:  O(n)
    Space: O(1)
    """
    max_reach: int = 0
    n: int = len(nums)
    for i in range(n):
        if i > max_reach:
            return False
        max_reach = max(max_reach, i + nums[i])
    return True


def trace_jump_game(nums: list[int]) -> list[dict]:
    """Capture the max-reach scan as a flat event list (one per index).

    Each event records i, nums[i], the previous max_reach, the new max_reach,
    and whether the index was reachable. Used by the printer and the HTML viz.
    """
    events: list[dict] = []
    max_reach: int = 0
    n: int = len(nums)
    last: int = n - 1
    for i in range(n):
        reachable: bool = i <= max_reach
        prev: int = max_reach
        if reachable:
            max_reach = max(max_reach, i + nums[i])
        events.append({
            "i": i,
            "jump": nums[i],
            "prev_reach": prev,
            "new_reach": max_reach,
            "reachable": reachable,
            "reached_end": max_reach >= last,
            "note": ("stuck" if not reachable else
                     ("reached last index!" if max_reach >= last
                      else "extend")),
        })
    events.append({"i": n, "jump": None, "prev_reach": max_reach,
                   "new_reach": max_reach, "reachable": True,
                   "reached_end": True,
                   "note": "reachable" if events[-1]["reachable"] else "unreachable"})
    return events


# ============================================================================
# TEMPLATE 2 - ACTIVITY SELECTION  (P452 Min Arrows to Burst Balloons)
# ============================================================================
def min_arrows(points: list[list[int]]) -> int:
    """Minimum arrows to burst all balloons.

    Each balloon is [x_start, x_end]; an arrow at x bursts every balloon with
    x_start <= x <= x_end. Greedy: sort by END coordinate, shoot an arrow at
    the end of the first balloon; every balloon starting <= that point shares
    the arrow. A balloon starting strictly after needs its own arrow.

    (Contrast: P435 Non-overlapping Intervals uses start >= end because
    touching is allowed there; here touching balloons share an arrow, so the
    test is the strict start > arrow_pos.)

    Time:  O(n log n)  (dominated by the sort)
    Space: O(1)        (or O(n) for the sort itself)
    """
    if not points:
        return 0
    pts: list[list[int]] = sorted(points, key=lambda p: p[1])
    arrows: int = 1
    arrow_pos: int = pts[0][1]
    for start, end in pts[1:]:
        if start > arrow_pos:
            arrows += 1
            arrow_pos = end
    return arrows


def trace_min_arrows(points: list[list[int]]) -> list[dict]:
    """Capture the activity-selection scan as a flat event list."""
    events: list[dict] = []
    if not points:
        return events
    pts: list[list[int]] = sorted(points, key=lambda p: p[1])
    arrows: int = 1
    arrow_pos: int = pts[0][1]
    events.append({
        "balloon": pts[0], "sorted": True,
        "arrow_pos": arrow_pos, "arrows": arrows,
        "action": "first", "note": f"shoot arrow #{arrows} at x={arrow_pos}",
    })
    for start, end in pts[1:]:
        if start > arrow_pos:
            arrows += 1
            arrow_pos = end
            action: str = "new"
            note: str = f"start {start} > {arrow_pos - (end - arrow_pos)}? new arrow #{arrows} at x={end}"
            # clean note: the comparison is against the OLD arrow_pos
            note = f"start {start} > old_pos -> new arrow #{arrows} at x={end}"
        else:
            action = "share"
            note = f"start {start} <= {arrow_pos} -> shares current arrow"
        events.append({
            "balloon": [start, end], "sorted": True,
            "arrow_pos": arrow_pos, "arrows": arrows,
            "action": action, "note": note,
        })
    return events


# ============================================================================
# TEMPLATE 3 - SURPLUS TRACKING  (P134 Gas Station)
# ============================================================================
def gas_station(gas: list[int], cost: list[int]) -> int:
    """Return the starting gas-station index that completes the circuit, or -1.

    Two invariants:
      * total_surplus  = sum(gas - cost) over ALL stations. If < 0, the trip
        is impossible no matter where you start -> return -1.
      * current_surplus = running sum from the current candidate start. The
        instant it dips below zero, that candidate (and everything before it)
        cannot be a valid start: reset start to i+1 and current to 0.

    Why it works: if total >= 0, a valid start MUST exist. Splitting the
    circle at any failed prefix shows the answer lies after that prefix, and
    a single pass finds it.

    Time:  O(n)
    Space: O(1)
    """
    total_surplus: int = 0
    current_surplus: int = 0
    start: int = 0
    for i in range(len(gas)):
        diff: int = gas[i] - cost[i]
        total_surplus += diff
        current_surplus += diff
        if current_surplus < 0:
            start = i + 1
            current_surplus = 0
    return start if total_surplus >= 0 else -1


def trace_gas_station(gas: list[int], cost: list[int]) -> list[dict]:
    """Capture the surplus scan as a flat event list (one per station)."""
    events: list[dict] = []
    total_surplus: int = 0
    current_surplus: int = 0
    start: int = 0
    n: int = len(gas)
    for i in range(n):
        diff: int = gas[i] - cost[i]
        total_surplus += diff
        current_surplus += diff
        reset: bool = False
        if current_surplus < 0:
            start = i + 1
            current_surplus = 0
            reset = True
        events.append({
            "i": i, "gas": gas[i], "cost": cost[i], "diff": diff,
            "total": total_surplus, "current": current_surplus,
            "start": start, "reset": reset,
            "note": ("reset -> start=" + str(i + 1) if reset else "ok"),
        })
    feasible: bool = total_surplus >= 0
    events.append({
        "i": n, "gas": None, "cost": None, "diff": None,
        "total": total_surplus, "current": current_surplus,
        "start": start, "reset": False,
        "note": "return " + (str(start) if feasible else "-1") +
                " (total " + (">= 0 -> feasible" if feasible else "< 0 -> impossible") + ")",
    })
    return events


# ============================================================================
# EVENT PRINTERS
# ============================================================================
def print_jump_events(events: list[dict]) -> None:
    print("  i | nums[i] | prev_reach -> new_reach | status")
    print("  --+---------+-----------------------+----------------------")
    for e in events[:-1]:
        status: str = e["note"]
        mark: str = "  " if e["reachable"] else "!!"
        print(f"  {e['i']} |   {e['jump']:>3}   |    {e['prev_reach']:>3}  ->  "
              f"{e['new_reach']:>3}      | {mark} {status}")
    final = events[-1]
    print(f"  => {final['note']}")


def print_arrow_events(events: list[dict]) -> None:
    print("  balloon     | arrow_pos | arrows | action")
    print("  ------------+-----------+--------+-----------------------------")
    for e in events:
        b = e["balloon"]
        mark = "[new]" if e["action"] == "new" else (
               "[1st]" if e["action"] == "first" else "     ")
        print(f"  [{b[0]:>3},{b[1]:>3}]    |   {e['arrow_pos']:>3}    |"
              f"   {e['arrows']}    | {mark} {e['note']}")


def print_gas_events(events: list[dict]) -> None:
    print("  i | gas cost | diff | total  current | start | note")
    print("  --+----------+------+----------------+-------+----------")
    for e in events[:-1]:
        reset = "RESET" if e["reset"] else "ok"
        print(f"  {e['i']} |  {e['gas']}   {e['cost']}  | {e['diff']:>+3} |"
              f"  {e['total']:>+3}     {e['current']:>+3}   |   {e['start']}   | {reset}")
    final = events[-1]
    print(f"  => {final['note']}")


# ============================================================================
# SECTION A - P055 JUMP GAME (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P055 Jump Game (max-reach tracking)")
    print("=" * 72)
    print()
    print("Goal: from index 0, can you reach the last index, where nums[i]")
    print("bounds your max jump length? Greedy: keep the FARTHEST index you")
    print("can reach so far. If the scan index ever outruns it, you're stuck.")
    print()
    print("Template (memorize the one-line update):")
    print("    max_reach = 0")
    print("    for i, jump in enumerate(nums):")
    print("        if i > max_reach: return False")
    print("        max_reach = max(max_reach, i + jump)")
    print("    return True")
    print()

    # ---- Example 1: reachable ----
    nums1 = [2, 3, 1, 1, 4]
    print(f"Example 1 (REACHABLE): nums = {nums1}, last index = {len(nums1)-1}")
    print()
    ev1 = trace_jump_game(nums1)
    print_jump_events(ev1)
    print()
    print(f"  jump_game({nums1}) -> {jump_game(nums1)}")
    print()

    # ---- Example 2: stuck ----
    nums2 = [3, 2, 1, 0, 4]
    print(f"Example 2 (STUCK): nums = {nums2}, last index = {len(nums2)-1}")
    print()
    ev2 = trace_jump_game(nums2)
    print_jump_events(ev2)
    print()
    print(f"  jump_game({nums2}) -> {jump_game(nums2)}")
    print()
    print("Note: the 0 at index 3 creates a hole. max_reach caps at 3, so")
    print("index 4 (the target) is never reachable. We never track WHICH")
    print("jumps to take - only the envelope of reachability.")
    print()

    # ---- small edge cases ----
    print("--- edge cases ---")
    print(f"  jump_game([0])           -> {jump_game([0])}     "
          f"(single element -> already at the end)")
    print(f"  jump_game([1, 0])        -> {jump_game([1, 0])}      "
          f"(one hop lands exactly on the last index)")
    print(f"  jump_game([0, 1])        -> {jump_game([0, 1])}     "
          f"(stuck at 0, cannot move)")
    print(f"  jump_game([2, 0, 0])     -> {jump_game([2, 0, 0])}      "
          f"(jump over the zeros)")
    print()


# ============================================================================
# SECTION B - P452 MIN ARROWS (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P452 Min Arrows to Burst Balloons (activity selection)")
    print("=" * 72)
    print()
    print("Goal: an arrow at x bursts every balloon [start,end] with")
    print("start <= x <= end. Find the FEWEST arrows. Greedy: sort by END,")
    print("shoot at the end of the first balloon; any balloon starting before")
    print("that point shares the arrow. Start strictly AFTER -> new arrow.")
    print()
    print("Template (the sort is the whole trick):")
    print("    points.sort(key=lambda p: p[1])   # SORT BY END")
    print("    arrows, arrow_pos = 1, points[0][1]")
    print("    for start, end in points[1:]:")
    print("        if start > arrow_pos:")
    print("            arrows += 1; arrow_pos = end")
    print("    return arrows")
    print()

    # ---- Example 1 ----
    pts1 = [[10, 16], [2, 8], [1, 6], [7, 12]]
    print(f"Example 1: points = {pts1}")
    print()
    print("After sorting by END coordinate: "
          f"{sorted(pts1, key=lambda p: p[1])}")
    print()
    ev1 = trace_min_arrows(pts1)
    print_arrow_events(ev1)
    print()
    print(f"  min_arrows({pts1}) -> {min_arrows(pts1)}")
    print("  (arrow at x=6 bursts [1,6] and [2,8]; arrow at x=12 bursts")
    print("   [7,12] and [10,16].)")
    print()

    # ---- Example 2: no overlap ----
    pts2 = [[1, 2], [3, 4], [5, 6], [7, 8]]
    print(f"Example 2: points = {pts2}")
    print()
    ev2 = trace_min_arrows(pts2)
    print_arrow_events(ev2)
    print()
    print(f"  min_arrows({pts2}) -> {min_arrows(pts2)}  (no overlap -> one")
    print("  arrow per balloon)")
    print()

    # ---- Example 3: touching shares an arrow ----
    pts3 = [[1, 2], [2, 3], [3, 4], [4, 5]]
    print(f"Example 3: points = {pts3}")
    print()
    ev3 = trace_min_arrows(pts3)
    print_arrow_events(ev3)
    print()
    print(f"  min_arrows({pts3}) -> {min_arrows(pts3)}  (touching at a point")
    print("  shares an arrow: [1,2] and [2,3] both burst at x=2).")
    print()

    # ---- edge cases ----
    print("--- edge cases ---")
    print(f"  min_arrows([])           -> {min_arrows([])}     (empty -> 0)")
    print(f"  min_arrows([[1,5]])      -> {min_arrows([[1,5]])}     (one balloon)")
    print()


# ============================================================================
# SECTION C - P134 GAS STATION (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P134 Gas Station (surplus tracking)")
    print("=" * 72)
    print()
    print("Goal: find a starting station for a circular tour where station i")
    print("gives gas[i] and reaching the next station costs cost[i]. Greedy")
    print("uses TWO counters: total_surplus (feasibility) and current_surplus")
    print("(where to start). When current dips negative, that candidate and")
    print("everything up to here is hopeless -> restart at i+1.")
    print()
    print("Template (two scalars, one pass):")
    print("    total = current = start = 0")
    print("    for i in range(len(gas)):")
    print("        diff = gas[i] - cost[i]")
    print("        total += diff; current += diff")
    print("        if current < 0: start = i + 1; current = 0")
    print("    return start if total >= 0 else -1")
    print()

    # ---- Example 1: feasible, start = 3 ----
    gas1 = [1, 2, 3, 4, 5]
    cost1 = [3, 4, 5, 1, 2]
    print(f"Example 1 (FEASIBLE): gas = {gas1}, cost = {cost1}")
    print(f"  net per station = {[gas1[i]-cost1[i] for i in range(len(gas1))]}")
    print()
    ev1 = trace_gas_station(gas1, cost1)
    print_gas_events(ev1)
    print()
    print(f"  gas_station(gas={gas1}, cost={cost1}) -> {gas_station(gas1, cost1)}")
    print("  (starting at 3: +3 to reach 4, +3 to reach 0, then -2,-2,-2")
    print("   but you carry a surplus of 6, so you finish.)")
    print()

    # ---- Example 2: impossible ----
    gas2 = [2, 3, 4]
    cost2 = [3, 4, 3]
    print(f"Example 2 (IMPOSSIBLE): gas = {gas2}, cost = {cost2}")
    print(f"  net per station = {[gas2[i]-cost2[i] for i in range(len(gas2))]}")
    print()
    ev2 = trace_gas_station(gas2, cost2)
    print_gas_events(ev2)
    print()
    print(f"  gas_station(gas={gas2}, cost={cost2}) -> {gas_station(gas2, cost2)}")
    print("  (total surplus = -1 < 0 -> no starting point exists.)")
    print()

    # ---- edge cases ----
    print("--- edge cases ---")
    print(f"  gas_station([5], [4])            -> {gas_station([5], [4])}   "
          f"(one station, net +1)")
    print(f"  gas_station([2], [2])            -> {gas_station([2], [2])}   "
          f"(net 0, exactly enough)")
    print(f"  gas_station([1, 2], [2, 1])      -> {gas_station([1, 2], [2, 1])}   "
          f"(start at 1)")
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
    print("  Operation                          Time          Space")
    print("  ---------------------------------- ------------- --------")
    print("  Jump Game, max-reach       (P055)  O(n)          O(1)")
    print("  Min Arrows / activity sel. (P452)  O(n log n)    O(1)*")
    print("  Gas Station, surplus       (P134)  O(n)          O(1)")
    print("  Jump Game II, min jumps    (P045)  O(n)          O(1)")
    print("  Task Scheduler, freq math  (P621)  O(n)          O(1)")
    print("  Assign Cookies, two-ptr    (P455)  O(n log n)    O(1)")
    print()
    print("  * O(n) for the greedy scan; O(n log n) dominates from the sort.")
    print("  n = input size. Greedy trades the exponential space of DP/DFS")
    print("  for a single scalar - that is its entire appeal.")
    print()
    print("The three templates (memorize the one-line update)")
    print("---------------------------------------------------")
    print("  MAX-REACH:     max_reach = max(max_reach, i + nums[i])")
    print("  FRONTIER:      if start > arrow_pos: arrows += 1; arrow_pos = end")
    print("  SURPLUS:       if current < 0: start = i + 1; current = 0")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. SORT BY END, NOT START. For interval greedy (arrows, meeting")
    print("     rooms, non-overlap) the sort key MUST be the end coordinate.")
    print("     Sorting by start fails on nested intervals: [1,10] before")
    print("     [2,3] hides the short one that leaves the most room. Sort by")
    print("     end so the earliest-finishing interval is always picked first.")
    print("  2. GLOBAL CHECK IS MANDATORY (Gas Station). Resetting `start` when")
    print("     current_surplus dips is LOCAL. You MUST still confirm")
    print("     total_surplus >= 0 at the end - otherwise you return a bogus")
    print("     start for an impossible circuit.")
    print("  3. STRICT vs NON-STRICT INEQUALITY. P452 uses start > arrow_pos")
    print("     (touching balloons share an arrow at the shared point). P435")
    print("     Non-overlapping Intervals uses start >= end (touching is allowed")
    print("     to coexist). Same skeleton, different off-by-one - know which.")
    print("  4. GREEDY IS NOT ALWAYS CORRECT. Coin change [1,3,4] target 6:")
    print("     greedy picks 4+1+1 (3 coins) but 3+3 (2 coins) is optimal.")
    print("     Weighted interval scheduling also defeats greedy. The exchange")
    print("     argument is how you PROVE greedy is safe before trusting it.")
    print("  5. JUMP GAME NEEDS ONLY THE ENVELOPE. You never store which jumps")
    print("     to take - just max_reach. A DP/memoized solution is correct but")
    print("     wastes O(n) space and O(n^2) time on a problem greedy solves in")
    print("     O(n)/O(1).")
    print("  6. THE -1 IN TASK SCHEDULER. Formula (max_freq-1)*(n+1)+count_max")
    print("     has a -1 because the LAST execution of the most frequent task")
    print("     needs no trailing cooldown. Drop it and you over-count by n+1.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                       Diff  Key trick")
    print("  ----------------------------- ----  ----------------------------------------")
    print("  P055 Jump Game                Med   track max_reach; return False if i > max_reach")
    print("  P045 Jump Game II             Med   BFS-greedy: jump when i hits current_end")
    print("  P452 Min Arrows               Med   sort by END; new arrow when start > arrow_pos")
    print("  P435 Non-overlapping Intervals Med  sort by END; count overlaps via start >= end")
    print("  P134 Gas Station              Med   reset start when current<0; check total>=0")
    print("  P455 Assign Cookies           Easy  sort both; two-pointer match greed vs size")
    print("  P621 Task Scheduler           Med   (max_freq-1)*(n+1)+count_max; cap at len")
    print("  P135 Candy                    Hard  two passes: L->R then R->L taking max")
    print("  P502 IPO                      Hard  sort by capital; max-heap of affordable profits")
    print("  P053 Max Subarray             Med   Kadane: local max = max(x, local+x)")
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
    # P055 Jump Game
    assert jump_game([2, 3, 1, 1, 4]) is True
    assert jump_game([3, 2, 1, 0, 4]) is False
    assert jump_game([0]) is True
    assert jump_game([1, 0]) is True
    assert jump_game([0, 1]) is False
    assert jump_game([2, 0, 0]) is True
    assert jump_game([2, 5, 0, 0, 0, 0, 0]) is True

    # P452 Min Arrows
    assert min_arrows([[10, 16], [2, 8], [1, 6], [7, 12]]) == 2
    assert min_arrows([[1, 2], [3, 4], [5, 6], [7, 8]]) == 4
    assert min_arrows([[1, 2], [2, 3], [3, 4], [4, 5]]) == 2
    assert min_arrows([]) == 0
    assert min_arrows([[1, 5]]) == 1
    assert min_arrows([[1, 5], [2, 3], [3, 4]]) == 1  # all burst by one arrow at x=3

    # P134 Gas Station
    assert gas_station([1, 2, 3, 4, 5], [3, 4, 5, 1, 2]) == 3
    assert gas_station([2, 3, 4], [3, 4, 3]) == -1
    assert gas_station([5], [4]) == 0
    assert gas_station([2], [2]) == 0
    assert gas_station([1, 2], [2, 1]) == 1

    # ---- cross-checks ----
    # Jump Game: an array where each index can hop at least one forward is
    # always reachable; a lone leading zero on a multi-element array is stuck.
    for n in range(1, 6):
        assert jump_game([1] * (n - 1) + [0]) is True
    assert jump_game([0, 1]) is False
    assert jump_game([0]) is True

    print("=" * 72)
    print("[check] jump_game / min_arrows / gas_station ... OK")
