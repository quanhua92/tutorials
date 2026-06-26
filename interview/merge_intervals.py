"""
merge_intervals.py - Reference implementation of the Merge Intervals pattern,
covering its three canonical variants:

    1. Merge overlapping intervals  (P056)  -- sort + extend end greedily
    2. Insert interval             (P057)  -- three-phase linear scan
    3. Minimum meeting rooms       (P253)  -- sweep-line / two-pointer

This is the single source of truth that MERGE_INTERVALS.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 merge_intervals.py

============================================================================
THE INTUITION (read this first) -- cleaning up a messy calendar
============================================================================
You have a calendar full of overlapping meetings. The meetings arrive in any
order. To clean them up you do ONE thing first:

    SORT the meetings by their start time.

After sorting, the rest is mechanical: walk left to right. If the next meeting
starts before (or exactly when) the last one ends, they OVERLAP -- extend the
last meeting's end. If not, they are DISJOINT -- start a new entry.

That is the whole pattern. Sorting is the universal setup because it unlocks a
transitivity property: if sorted intervals A and B don't overlap, and B and C
don't overlap, then A and C cannot overlap either. So you only ever compare
EACH interval with the PREVIOUS one -- never look further back. A single O(n)
scan after an O(n log n) sort gives the answer.

The three variants differ only in WHAT you keep as the running state:

    Merge            : running state = the last merged interval; extend its end.
    Insert           : input is ALREADY sorted & disjoint; run three phases
                       (before / overlap / after) in one O(n) pass -- no sort.
    Meeting Rooms II : convert each [s, e] to two sweep events (s, +1) and
                       (e, -1); the PEAK of the running count is the answer.
                       (Equivalently: two sorted arrays of starts and ends, with
                       a two-pointer "free up a room when start >= ends[ptr]".)

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  interval       : a half-open or closed [start, end] pair. Most LeetCode
                   problems treat them as CLOSED: [1,2] and [2,3] OVERLAP at 2.
  overlap        : two intervals overlap iff next.start <= current.end (closed)
                   or next.start <  current.end (half-open). ALWAYS check which.
  sort by start  : intervals.sort(key=lambda x: x[0]). The universal step 1.
  extend         : on overlap, current.end = max(current.end, next.end). The
                   max() is mandatory -- handles nested intervals (gotcha #1).
  sweep line     : convert intervals into event points (+1 on start, -1 on end),
                   sort by time, scan to find the peak running count.
  boundary       : closed [s,e] uses <= for overlap; half-open [s,e) uses <.
                   Meeting rooms RECYCLE at the boundary: start >= ends[ptr].

============================================================================
THE LINEAGE (textbooks / real systems)
============================================================================
  Interval problems : CLRS §2.1 ("insertion sort" exercises), but the modern
                       canonical treatment is competitive-programming folklore.
  Meeting Rooms II  : LeetCode P253 (locked). The two-pointer trick is due to
                       the "chronological ordering" insight: you don't need to
                       know WHICH meeting ends, only that ONE ends.
  Sweep line        : Bentley & Ottmann (1979) -- the general plane-sweep
                       technique. Meeting Rooms II is its 1-D special case.
  Real systems      : Google Calendar conflict detection, OS process scheduling
                       ("how many CPU cores do I need?"), bandwidth/buffer
                       sizing for overlapping I/O requests.

KEY FORMULAS (all verified/printed by the sections below):
    overlap (closed) : next.start <= last.end
    overlap (half-open): next.start <  last.end
    merge extend     : last.end = max(last.end, next.end)   [handles nesting]
    sort cost        : O(n log n)           -- dominates
    scan cost        : O(n)                 -- after sort
    total            : O(n log n) time, O(n) space (output/events)
    insert           : O(n) time (no sort, input already sorted)
    meeting rooms    : O(n log n) time, O(n) space (sorted starts/ends)

Conventions:
    interval = [start, end] with start <= end, CLOSED (touching = overlap).
    Meeting rooms exception: a room ending at t frees up for one starting at t
    (start >= ends[ptr]), because back-to-back meetings share a room.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS (this is the code MERGE_INTERVALS.md walks
#    through). The plain versions solve the problem; the _traced versions record
#    every decision so the guide can print a step-by-step trace.
# ============================================================================

def merge_intervals(intervals: list[list[int]]) -> list[list[int]]:
    """Variant 1 (P056): merge overlapping intervals.

    Sort by start, then scan left to right extending the last interval's end on
    overlap. O(n log n) time, O(n) space (output).
    """
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged: list[list[int]] = [intervals[0][:]]
    for start, end in intervals[1:]:
        last = merged[-1]
        if start <= last[1]:                       # overlap (closed: <=)
            last[1] = max(last[1], end)            # extend (max handles nesting)
        else:
            merged.append([start, end])            # disjoint -> new entry
    return merged


def merge_intervals_traced(intervals: list[list[int]]) -> dict:
    """Same algorithm, but records each merge decision so the guide can print
    a step-by-step trace.

    Records:
      sorted   : the input after the mandatory sort-by-start
      steps    : list of {idx, cur, last_before, action, last_after} per interval
                 (action in {"extend", "new"}; cur=None / step[0] = seed)
      merged   : final result
    """
    if not intervals:
        return {"input": [], "sorted": [], "steps": [], "merged": []}

    srt = sorted((list(iv) for iv in intervals), key=lambda x: x[0])
    merged: list[list[int]] = [srt[0][:]]
    steps: list[dict] = [{
        "idx": 0, "cur": srt[0][:], "last_before": None,
        "action": "seed", "last_after": srt[0][:],
    }]
    for i, (start, end) in enumerate(srt[1:], start=1):
        last = merged[-1]
        last_before = last[:]
        if start <= last[1]:
            last[1] = max(last[1], end)
            action = "extend"
        else:
            merged.append([start, end])
            action = "new"
        steps.append({
            "idx": i, "cur": [start, end], "last_before": last_before,
            "action": action, "last_after": merged[-1][:],
        })
    return {"input": [list(iv) for iv in intervals], "sorted": srt,
            "steps": steps, "merged": merged}


def insert_interval(
    intervals: list[list[int]], new_interval: list[int]
) -> list[list[int]]:
    """Variant 2 (P057): insert new_interval into an already-sorted,
    non-overlapping list, merging as needed.

    Three-phase single pass: BEFORE (end < new.start), OVERLAP (start <= new.end),
    AFTER (the rest). O(n) time -- no sort needed.
    """
    result: list[list[int]] = []
    i, n = 0, len(intervals)
    new = list(new_interval)
    while i < n and intervals[i][1] < new[0]:          # phase 1: before
        result.append(intervals[i][:]); i += 1
    while i < n and intervals[i][0] <= new[1]:         # phase 2: overlap
        new[0] = min(new[0], intervals[i][0])
        new[1] = max(new[1], intervals[i][1])
        i += 1
    result.append(new)                                  # the merged interval
    while i < n:                                        # phase 3: after
        result.append(intervals[i][:]); i += 1
    return result


def insert_interval_traced(
    intervals: list[list[int]], new_interval: list[int]
) -> dict:
    """Same algorithm, but records the phase transitions and what got absorbed
    so the guide can print the three-phase trace.

    Records:
      phases   : list of {phase, intervals_added, new_so_far} (3 entries max)
      absorbed : list of intervals swallowed during phase 2
      result   : final list
    """
    result: list[list[int]] = []
    i, n = 0, len(intervals)
    new = list(new_interval)
    phases: list[dict] = []
    absorbed: list[list[int]] = []

    # phase 1: before
    before: list[list[int]] = []
    while i < n and intervals[i][1] < new[0]:
        before.append(intervals[i][:]); i += 1
    phases.append({"phase": "before", "added": before, "new_so_far": list(new)})

    # phase 2: overlap (merge into new)
    while i < n and intervals[i][0] <= new[1]:
        absorbed.append(intervals[i][:])
        new[0] = min(new[0], intervals[i][0])
        new[1] = max(new[1], intervals[i][1])
        i += 1
    phases.append({"phase": "overlap", "added": [list(new)],
                   "new_so_far": list(new)})

    # phase 3: after
    after: list[list[int]] = []
    while i < n:
        after.append(intervals[i][:]); i += 1
    phases.append({"phase": "after", "added": after, "new_so_far": list(new)})

    result = before + [new] + after
    return {
        "input": [list(iv) for iv in intervals], "new": list(new_interval),
        "phases": phases, "absorbed": absorbed, "result": result,
    }


def min_meeting_rooms(intervals: list[list[int]]) -> int:
    """Variant 3a (P253): minimum meeting rooms via two-pointer sweep.

    Sort starts and ends separately. For each start, if it is >= the earliest
    end, a room frees up (end_ptr++); else we need a new room. The number of
    rooms in use at the end is the answer (equiv. to peak concurrency).
    O(n log n) time, O(n) space.
    """
    if not intervals:
        return 0
    starts = sorted(s for s, _ in intervals)
    ends = sorted(e for _, e in intervals)
    rooms = 0
    end_ptr = 0
    for start in starts:
        if start >= ends[end_ptr]:                     # a room freed up
            end_ptr += 1
        else:                                          # need a new room
            rooms += 1
    return rooms


def min_meeting_rooms_sweep(intervals: list[list[int]]) -> int:
    """Variant 3b (P253): minimum meeting rooms via sweep-line events.

    Convert each [s, e] to (s, +1) and (e, -1); sort by time, breaking ties so
    that END (-1) comes before START (+1) at the same timestamp (back-to-back
    meetings share a room). Track the peak of the running count.
    """
    events: list[tuple[int, int]] = []
    for s, e in intervals:
        events.append((s, +1))                         # meeting starts
        events.append((e, -1))                         # meeting ends
    # tie-break: at same time, end (-1) before start (+1) -> room recycles first
    events.sort(key=lambda x: (x[0], x[1]))
    rooms = peak = 0
    for _, delta in events:
        rooms += delta
        peak = max(peak, rooms)
    return peak


def min_meeting_rooms_traced(intervals: list[list[int]]) -> dict:
    """Records the sweep-line timeline (events sorted with the end-before-start
    tie-break) so the guide can print a step-by-step count.

    Records:
      events      : sorted list of (time, delta)
      timeline    : list of {t, delta, running, peak} per event
      peak        : the answer
      two_pointer : same answer computed via the two-pointer method (cross-check)
    """
    events: list[tuple[int, int]] = []
    for s, e in intervals:
        events.append((s, +1))
        events.append((e, -1))
    events.sort(key=lambda x: (x[0], x[1]))

    timeline: list[dict] = []
    running = peak = 0
    for t, delta in events:
        running += delta
        peak = max(peak, running)
        timeline.append({"t": t, "delta": delta, "running": running, "peak": peak})

    tp = min_meeting_rooms(intervals)                  # two-pointer cross-check
    return {
        "input": [list(iv) for iv in intervals],
        "events": events, "timeline": timeline,
        "peak": peak, "two_pointer": tp,
    }


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt(iv: list[int]) -> str:
    return f"[{iv[0]}, {iv[1]}]"


# ============================================================================
# 3. THE TINY CONCRETE EXAMPLES (LeetCode canonical inputs)
# ============================================================================

MERGE_INPUT = [[1, 3], [2, 6], [8, 10], [15, 18]]      # P056 example 1
INSERT_INPUT = [[1, 3], [6, 9]]                        # P057 example 1
INSERT_NEW = [2, 5]
ROOMS_INPUT = [[0, 30], [5, 10], [15, 20]]             # P253 example 1
NESTED_INPUT = [[1, 4], [0, 4]]                        # P056 example 2 (touching)


# ----------------------------------------------------------------------------
# SECTION A: the universal setup (sort by start)
# ----------------------------------------------------------------------------

def section_setup():
    banner("SECTION A: the universal setup  (sort by start, then scan)")
    print("Every interval problem starts the same way: SORT BY START. After")
    print("sorting, you only ever compare each interval with the PREVIOUS one --")
    print("transitivity of non-overlap means you never look further back.\n")
    print(f"Example (P056):  input  = {MERGE_INPUT}")
    srt = sorted(MERGE_INPUT, key=lambda x: x[0])
    print(f"                  sorted = {srt}   (sort key = start time)\n")
    print("The scan is then a single O(n) pass: for each interval, decide")
    print("EXTEND (overlap -> last.end = max(last.end, end)) or NEW (disjoint).")
    print("Sort cost O(n log n) dominates; the scan is O(n).\n")
    print("Variant       | running state           | sort?")
    print("--------------|-------------------------|--------")
    print("merge (P056)  | last merged interval    | yes")
    print("insert (P057) | input already sorted    | NO (O(n) total)")
    print("rooms  (P253) | sweep-line running count| yes (events)")


# ----------------------------------------------------------------------------
# SECTION B: P056 Merge Intervals -- sort + extend
# ----------------------------------------------------------------------------

def section_merge():
    banner("SECTION B: P056 Merge Intervals  (sort + extend the last end)")
    r = merge_intervals_traced(MERGE_INPUT)
    print(f"Input  : {r['input']}")
    print(f"Sorted : {r['sorted']}   (by start time)\n")
    print("Walk left to right. Compare each interval's START with the LAST")
    print("merged interval's END. Overlap (closed: start <= end) -> EXTEND")
    print("using max() (handles nesting). Disjoint -> NEW entry.\n")
    print(f"{'i':>2}  {'cur':>10}  {'last before':>14}  "
          f"{'action':>8}  {'last after':>14}")
    for st in r["steps"]:
        cur = "seed" if st["cur"] is None else fmt(st["cur"])
        last_b = "-" if st["last_before"] is None else fmt(st["last_before"])
        last_a = fmt(st["last_after"])
        print(f"{st['idx']:>2}  {cur:>10}  {last_b:>14}  "
              f"{st['action']:>8}  {last_a:>14}")
    print(f"\nMerged result: {r['merged']}\n")
    print("Step i=1 is the overlap: [2,6] starts at 2 <= last end 3 -> EXTEND")
    print("  the last interval to end = max(3, 6) = 6. Now [1,6].")
    print("Step i=2: [8,10] starts at 8 > 6 -> disjoint -> NEW entry.")
    print("Step i=3: [15,18] starts at 15 > 10 -> disjoint -> NEW entry.\n")

    print("-- nested-interval edge case (gotcha: must use max, not assign) --")
    r2 = merge_intervals_traced([[1, 10], [2, 3], [4, 5]])
    print(f"Input  : {r2['input']}   (two intervals nested inside [1,10])")
    print(f"Sorted : {r2['sorted']}")
    for st in r2["steps"]:
        if st["cur"] is None:
            continue
        last_b = fmt(st["last_before"]) if st["last_before"] else "-"
        print(f"  i={st['idx']}: cur={fmt(st['cur'])}  last={last_b}  "
              f"-> {st['action']:>7}  last becomes {fmt(st['last_after'])}")
    print(f"Merged : {r2['merged']}   <- [2,3] and [4,5] are swallowed; the")
    print("  end stays 10 = max(10, 3) = max(10, 5). A naive `last.end = end`")
    print("  would WRONGLY truncate to [1,3]. max() is mandatory.\n")

    assert r["merged"] == [[1, 6], [8, 10], [15, 18]]
    assert r2["merged"] == [[1, 10]]
    print("[check] merge_intervals(MERGE_INPUT) == [[1,6],[8,10],[15,18]]:  OK")
    print("[check] nested [[1,10],[2,3],[4,5]] == [[1,10]]:  OK")


# ----------------------------------------------------------------------------
# SECTION C: P057 Insert Interval -- three-phase scan (no sort)
# ----------------------------------------------------------------------------

def section_insert():
    banner("SECTION C: P057 Insert Interval  (three-phase scan, already sorted)")
    r = insert_interval_traced(INSERT_INPUT, INSERT_NEW)
    print(f"Input       : {r['input']}   (already sorted & non-overlapping)")
    print(f"New interval: {r['new']}\n")
    print("The input is ALREADY sorted and disjoint, so NO sort is needed --")
    print("the whole thing is O(n). Three phases in a single left-to-right pass:\n")
    print("  PHASE 1 (before) : copy every interval whose END < new.start.")
    print("  PHASE 2 (overlap): while interval.START <= new.end, absorb it:")
    print("                      new.start = min(...); new.end = max(...).")
    print("  PHASE 3 (after)  : copy the rest verbatim.\n")
    for ph in r["phases"]:
        added = ", ".join(fmt(a) for a in ph["added"]) or "(nothing)"
        print(f"  phase {ph['phase']:>7}: add {added:<22} "
              f"| new so far = {fmt(ph['new_so_far'])}")
    print(f"\nAbsorbed into new during phase 2: {r['absorbed']}")
    print(f"Result: {r['result']}\n")
    print("Phase boundary detail: phase 1 uses STRICT < (intervals ending")
    print("strictly before new.start are untouched); phase 2 uses <= (intervals")
    print("whose start is <= new.end overlap and get absorbed). The transition")
    print("from < to <= is what makes touching intervals merge correctly.\n")

    print("-- boundary case: new interval at the very end --")
    r2 = insert_interval_traced([[1, 5]], [6, 8])
    print(f"Input {r2['input']}, new {r2['new']} -> {r2['result']}  "
          f"(disjoint, just appended)\n")
    print("-- boundary case: new interval covers everything --")
    r3 = insert_interval_traced([[1, 2], [3, 5], [6, 7], [8, 10], [12, 16]],
                                [4, 8])
    print(f"Input {r3['input']}\nnew   {r3['new']}")
    print(f"Absorbed: {r3['absorbed']}  -> new becomes "
          f"{fmt(r3['phases'][1]['new_so_far'])}")
    print(f"Result  : {r3['result']}\n")

    assert r["result"] == [[1, 5], [6, 9]]
    assert r2["result"] == [[1, 5], [6, 8]]
    assert r3["result"] == [[1, 2], [3, 10], [12, 16]]
    print("[check] insert([[1,3],[6,9]], [2,5]) == [[1,5],[6,9]]:  OK")
    print("[check] insert([[1,5]], [6,8]) == [[1,5],[6,8]]:  OK")
    print("[check] big overlap -> [[1,2],[3,10],[12,16]]:  OK")


# ----------------------------------------------------------------------------
# SECTION D: P253 Meeting Rooms II -- sweep-line + two-pointer
# ----------------------------------------------------------------------------

def section_rooms():
    banner("SECTION D: P253 Meeting Rooms II  (sweep-line peak / two-pointer)")
    r = min_meeting_rooms_traced(ROOMS_INPUT)
    print(f"Input : {r['input']}\n")
    print("GOAL: minimum conference rooms so no two meetings overlap in a room.\n")
    print("SWEEP-LINE method: turn each [s,e] into two events -- (s, +1) for a")
    print("meeting starting and (e, -1) for one ending. Sort by time; at the SAME")
    print("timestamp put END (-1) BEFORE start (+1) so a room recycles first")
    print("(back-to-back meetings [1,2],[2,3] share one room).\n")
    print("Then scan; the PEAK of the running count is the answer.\n")
    print(f"Sorted events: {[(t, ('+1' if d>0 else '-1')) for t, d in r['events']]}\n")
    print(f"{'time':>5}  {'delta':>6}  {'running':>8}  {'peak':>5}")
    for ev in r["timeline"]:
        d = "+1" if ev["delta"] > 0 else "-1"
        print(f"{ev['t']:>5}  {d:>6}  {ev['running']:>8}  {ev['peak']:>5}")
    print(f"\nPeak running count = {r['peak']}  ->  need {r['peak']} room(s).\n")

    print("TWO-POINTER method (same answer, no event list): sort starts and ends")
    print("separately. For each start, if start >= earliest end, a room freed up")
    print("(advance end pointer); else need a new room.\n")
    starts = sorted(s for s, _ in ROOMS_INPUT)
    ends = sorted(e for _, e in ROOMS_INPUT)
    print(f"  starts = {starts}")
    print(f"  ends   = {ends}")
    rooms = ep = 0
    for s in starts:
        if s >= ends[ep]:
            ep += 1
            tag = "free a room"
        else:
            rooms += 1
            tag = "need new room"
        print(f"  start={s:>3}  >= ends[{ep}]={ends[ep] if ep < len(ends) else '-'}?  "
              f"{tag}")
    print(f"  two-pointer answer = {rooms}\n")

    print("-- tie-break matters: back-to-back meetings share a room --")
    r2 = min_meeting_rooms_traced([[0, 30], [5, 10], [15, 20]])
    assert r2["peak"] == 2
    r3 = min_meeting_rooms_traced([[7, 10], [2, 4]])
    assert r3["peak"] == 1
    print(f"  [[7,10],[2,4]] -> {r3['peak']} room (disjoint in time)")
    print(f"  [[0,30],[5,10],[15,20]] -> {r2['peak']} rooms (the 0-30 meeting")
    print("    runs concurrently with BOTH shorter ones -> 2 needed)\n")

    assert r["peak"] == 2
    assert r["two_pointer"] == 2
    assert r["peak"] == r["two_pointer"]
    print("[check] sweep-line peak == 2:  OK")
    print("[check] two-pointer    == 2:  OK")
    print("[check] sweep-line == two-pointer:  OK")


# ----------------------------------------------------------------------------
# SECTION E: complexity + the boundary-convention table
# ----------------------------------------------------------------------------

def section_complexity():
    banner("SECTION E: complexity + the closed vs half-open boundary table")
    print("All three variants share the same shape: an O(n log n) SORT followed")
    print("by an O(n) SCAN. The sort dominates; the scan is linear.\n")
    print("  variant            | sort? | time        | space  | notes")
    print("  -------------------|-------|-------------|--------|---------------------")
    print("  merge (P056)       | yes   | O(n log n)  | O(n)   | output list")
    print("  insert (P057)      | NO    | O(n)        | O(n)   | input already sorted")
    print("  rooms  (P253)      | yes   | O(n log n)  | O(n)   | events or 2 sorted arrays")
    print()
    print("BOUNDARY CONVENTION -- the #1 source of off-by-one bugs:")
    print()
    print("  convention   | overlap test       | example [1,2] & [2,3]")
    print("  -------------|--------------------|------------------------")
    print("  closed [s,e] | next.start <= end  | OVERLAP (share point 2)")
    print("  half-open    | next.start <  end  | disjoint (room recycles)")
    print()
    print("Merge Intervals (P056) uses CLOSED (<=). Meeting Rooms II (P253) uses")
    print("the boundary as a FREE point: start >= ends[ptr] recycles a room, so")
    print("back-to-back [1,2],[2,3] need only 1 room. The sweep-line tie-break")
    print("(-1 before +1 at the same time) encodes this convention directly.\n")

    print("-- killer gotchas --")
    print("  1. NESTED intervals: use max(last.end, end), NOT last.end = end.")
    print("     [1,10]+[2,3] must stay [1,10]; naive assign truncates to [1,3].")
    print("  2. SORT DEFENSIVELY even if the input looks sorted -- the spec")
    print("     rarely guarantees it (P057 Insert is the exception).")
    print("  3. TIE-BREAK in the sweep line: at the same timestamp, END before")
    print("     START, or you over-count rooms by 1 for back-to-back meetings.")
    print("  4. SCHEDULING-MAX (max non-overlapping subset) sorts by END, not")
    print("     start -- a different problem, easy to confuse with merge.")


# ============================================================================
# main + GOLD
# ============================================================================

def main():
    print("merge_intervals.py - reference impl. All numbers below feed "
          "MERGE_INTERVALS.md.")
    section_setup()
    section_merge()
    section_insert()
    section_rooms()
    section_complexity()

    banner("GOLD (pinned for merge_intervals.html)")
    rm = merge_intervals_traced(MERGE_INPUT)
    ri = insert_interval_traced(INSERT_INPUT, INSERT_NEW)
    rr = min_meeting_rooms_traced(ROOMS_INPUT)
    print(f"merge  input   : {MERGE_INPUT}")
    print(f"merge  result  : {rm['merged']}")
    print(f"insert input   : {INSERT_INPUT}, new = {INSERT_NEW}")
    print(f"insert result  : {ri['result']}")
    print(f"rooms  input   : {ROOMS_INPUT}")
    print(f"rooms  events  : "
          f"{[(t, ('+1' if d>0 else '-1')) for t, d in rr['events']]}")
    print(f"rooms  peak    : {rr['peak']}")
    print(f"rooms  timeline: {[(ev['t'], ev['running']) for ev in rr['timeline']]}")

    GOLD_MERGE = [[1, 6], [8, 10], [15, 18]]
    GOLD_INSERT = [[1, 5], [6, 9]]
    GOLD_ROOMS_PEAK = 2
    GOLD_ROOMS_TIMELINE = [(0, 1), (5, 2), (10, 1), (15, 2), (20, 1), (30, 0)]
    assert rm["merged"] == GOLD_MERGE
    assert ri["result"] == GOLD_INSERT
    assert rr["peak"] == GOLD_ROOMS_PEAK
    assert [(ev["t"], ev["running"]) for ev in rr["timeline"]] == GOLD_ROOMS_TIMELINE
    print()
    print(f"GOLD merge   = {GOLD_MERGE}")
    print(f"GOLD insert  = {GOLD_INSERT}")
    print(f"GOLD rooms peak     = {GOLD_ROOMS_PEAK}")
    print(f"GOLD rooms timeline = {GOLD_ROOMS_TIMELINE}")
    print("[check] GOLD reproduces from the traced functions:  OK")

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
