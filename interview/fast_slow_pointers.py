"""
fast_slow_pointers.py - Reference implementation of Fast & Slow Pointers
(Floyd's tortoise & hare) for: cycle detection, middle finding, happy number.

This is the SINGLE SOURCE OF TRUTH for FAST_SLOW_POINTERS.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 fast_slow_pointers.py > fast_slow_pointers_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - two cars on a road
============================================================================
Imagine two cars driving on a road. One car drives TWICE AS FAST as the other.

  * If the road is STRAIGHT (no cycle): the fast car reaches the end exactly
    when the slow car is at the MIDDLE. That gives middle-finding.

  * If the road loops back on itself (a cycle): the fast car laps the slow
    car and they MEET somewhere on the loop. That gives cycle detection.

The whole pattern is one skeleton:

        slow = head
        fast = head
        while fast and fast.next:    # guard fast.next.next
            slow = slow.next          # 1 step
            fast = fast.next.next     # 2 steps
            ...                       # check: did they meet? is fast at the end?

For an abstract SEQUENCE (like the Happy Number transformation n -> sum of
squared digits), we OFFSET the start so slow != fast on iteration 1:

        slow = n
        fast = get_next(n)            # one step ahead

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  head           first node of the linked list.
  next           the pointer field; the "road" is the chain of .next links.
  slow           the tortoise; advances 1 node per step.
  fast           the hare; advances 2 nodes per step.
  meet           slow IS fast (same node, not same value). Signals a cycle.
  cycle          some node's .next points BACK at an earlier node, making the
                 list a loop instead of a straight line ending in None.
  middle         the node slow is sitting on when fast can no longer advance.
                 for EVEN-length lists slow lands on the SECOND middle node.
  happy number   repeatedly replacing n with the sum of squared digits reaches
                 1 (so the transformation sequence terminates). Otherwise it
                 enters a cycle that does NOT contain 1.

============================================================================
THE SKELETON (all three variants share this)
============================================================================
    slow = head
    fast = head
    while fast and fast.next:        # CRITICAL: guard before .next.next
        slow = slow.next              # 1 step
        fast = fast.next.next         # 2 steps
        if slow is fast:              # for cycle detection only
            return True
    # acyclic exit: slow is now at the middle
    return slow
"""

from __future__ import annotations


# ============================================================================
# LINKED LIST - minimal demo class (NOT LeetCode's ListNode signature; this
# one adds helpers for printing and step-tracing, so the .md and .html can
# show actual pointer positions).
# ============================================================================
class ListNode:
    """Singly linked list node."""

    __slots__ = ("val", "next")

    def __init__(self, val: int, next: "ListNode | None" = None):
        self.val = val
        self.next = next

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"ListNode({self.val})"


def build_list(values: list[int]) -> ListNode | None:
    """Build an ACYCLIC list from a value list.  build_list([1,2,3]) -> 1->2->3."""
    dummy = ListNode(-1)
    cur = dummy
    for v in values:
        cur.next = ListNode(v)
        cur = cur.next
    return dummy.next


def make_cycle(values: list[int], pos: int) -> ListNode | None:
    """Build a list from `values` and link the TAIL back to node at index `pos`.

    make_cycle([1,2,3,4], pos=1)  ->  1 -> 2 -> 3 -> 4 --back-to--> 2
    """
    if not values:
        return None
    head = build_list(values)
    # walk to the tail
    tail = head
    while tail.next:
        tail = tail.next
    # walk to the cycle entry
    entry = head
    for _ in range(pos):
        entry = entry.next  # type: ignore[assignment]
    tail.next = entry  # create the back-edge
    return head


def list_str(head: ListNode | None, slow: ListNode | None = None,
             fast: ListNode | None = None, limit: int = 12) -> str:
    """Render the list as '1 -> 2 -> 3 -> None', marking slow/fast nodes.

    For cyclic lists we stop after `limit` nodes (so we don't loop forever)
    and insert '...' at the point where the cycle was entered a second time.
    """
    seen: dict[int, int] = {}  # id(node) -> visit number
    parts: list[str] = []
    cur = head
    i = 0
    while cur is not None and i < limit:
        nid = id(cur)
        if nid in seen:
            parts.append(f"(cycle back to idx {seen[nid]})")
            break
        seen[nid] = i
        tags = []
        if cur is slow:
            tags.append("S")
        if cur is fast:
            tags.append("F")
        label = f"{cur.val}" + (f"[{','.join(tags)}]" if tags else "")
        parts.append(label)
        cur = cur.next
        i += 1
    else:
        parts.append("None")
    return " -> ".join(parts)


# ============================================================================
# TEMPLATE 1 - CYCLE DETECTION  (Floyd's tortoise & hare)   P141
# ============================================================================
def has_cycle(head: ListNode | None) -> bool:
    """Return True iff the list contains a cycle.

    slow moves 1, fast moves 2. If they ever refer to the SAME node, a cycle
    exists. If fast reaches None (or fast.next is None), there is no cycle.

    Time:  O(n)   -- fast visits at most 2n nodes
    Space: O(1)   -- two pointers only, no hashset
    """
    slow = head
    fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow is fast:
            return True
    return False


# ============================================================================
# TEMPLATE 2 - FIND THE MIDDLE                                 P876
# ============================================================================
def find_middle(head: ListNode | None) -> ListNode | None:
    """Return the middle node. For even-length lists, returns the SECOND middle.

    Same skeleton as has_cycle, but with NO cycle check: we just stop when
    fast can no longer advance. slow is then on the middle.

    Time:  O(n)
    Space: O(1)
    """
    slow = head
    fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
    return slow


# ============================================================================
# TEMPLATE 3 - HAPPY NUMBER                                    P202
# ============================================================================
def _sum_sq_digits(n: int) -> int:
    """Sum of squares of decimal digits.  _sum_sq_digits(19) = 1+81 = 82."""
    total = 0
    while n > 0:
        d = n % 10
        total += d * d
        n //= 10
    return total


def is_happy(n: int) -> bool:
    """Return True iff repeatedly replacing n with sum of squared digits hits 1.

    We treat the transformation sequence as a 'linked list' where each node's
    .next is _sum_sq_digits. By pigeonhole the sequence eventually repeats, so
    Floyd's cycle detection tells us whether the cycle CONTAINS 1.

    OFFSET INIT: slow = n, fast = _sum_sq_digits(n). If both started at n,
    the slow == fast check would fire on iteration 1 (before any real move).

    Time:  O(log n) per step (digit operations shrink n fast), bounded steps
    Space: O(1)
    """
    slow = n
    fast = _sum_sq_digits(n)
    while fast != 1 and slow != fast:
        slow = _sum_sq_digits(slow)
        fast = _sum_sq_digits(_sum_sq_digits(fast))
    return fast == 1


# ============================================================================
# STEP TRACERS - re-implement the same logic but record every pointer
# position. Used by the worked-example sections so the .md and .html can show
# the tortoise and hare chasing each other node-by-node.
# ============================================================================
def trace_cycle(head: ListNode | None) -> list[dict]:
    """Trace has_cycle; return list of {slow_val, fast_val, meet} per step."""
    steps: list[dict] = []
    slow = head
    fast = head
    # record the entry state BEFORE any move (both at head)
    steps.append({"i": 0, "slow": slow.val if slow else None,
                  "fast": fast.val if fast else None, "meet": slow is fast})
    i = 0
    while fast and fast.next:
        i += 1
        slow = slow.next  # type: ignore[union-attr]
        fast = fast.next.next
        meet = slow is fast
        steps.append({"i": i, "slow": slow.val if slow else None,
                      "fast": fast.val if fast else None, "meet": meet})
        if meet:
            break
    return steps


def trace_middle(head: ListNode | None) -> list[dict]:
    """Trace find_middle; return list of {slow_val, fast_val} per step."""
    steps: list[dict] = []
    slow = head
    fast = head
    steps.append({"i": 0, "slow": slow.val if slow else None,
                  "fast": fast.val if fast else None, "done": False})
    i = 0
    while fast and fast.next:
        i += 1
        slow = slow.next  # type: ignore[union-attr]
        fast = fast.next.next
        done = not (fast and fast.next)
        steps.append({"i": i, "slow": slow.val if slow else None,
                      "fast": fast.val if fast else None, "done": done})
    return steps


def trace_happy(n: int, cap: int = 30) -> list[dict]:
    """Trace is_happy; return list of {i, slow, fast, hit1, meet} per step."""
    steps: list[dict] = []
    slow = n
    fast = _sum_sq_digits(n)
    steps.append({"i": 0, "slow": slow, "fast": fast,
                  "hit1": fast == 1, "meet": slow == fast})
    i = 0
    while fast != 1 and slow != fast and i < cap:
        i += 1
        slow = _sum_sq_digits(slow)
        fast = _sum_sq_digits(_sum_sq_digits(fast))
        steps.append({"i": i, "slow": slow, "fast": fast,
                      "hit1": fast == 1, "meet": slow == fast})
    return steps


# ============================================================================
# SECTION A - P141 LINKED LIST CYCLE (worked example with step trace)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P141 Linked List Cycle  (Floyd's tortoise & hare)")
    print("=" * 72)
    print()
    print("Build:  1 -> 2 -> 3 -> 4 --back-to--> 2   (cycle entry = index 1)")
    head = make_cycle([1, 2, 3, 4], pos=1)
    print("  initial: ", list_str(head))
    print()
    print("Run has_cycle step by step. S = slow, F = fast.")
    print("  Both start at head. Each step: slow += 1, fast += 2.")
    print()
    steps = trace_cycle(head)
    for s in steps:
        slow_node = _find_node_with_val_trace(head, s["slow"])
        fast_node = _find_node_with_val_trace(head, s["fast"])
        marker = "  <-- MEET (cycle confirmed)" if s["meet"] and s["i"] > 0 else ""
        print(f"  step {s['i']}: slow at {s['slow']}, fast at {s['fast']}{marker}")
        print(f"           {list_str(head, slow_node, fast_node)}")
    print()
    result = has_cycle(head)
    print(f"has_cycle -> {result}   (expected True)")
    print()
    print("No-cycle control: 1 -> 2 -> 3 -> 4 -> None")
    acyclic = build_list([1, 2, 3, 4])
    steps2 = trace_cycle(acyclic)
    for s in steps2:
        print(f"  step {s['i']}: slow at {s['slow']}, fast at {s['fast']}")
    print(f"           fast reached None -> no cycle")
    print(f"has_cycle -> {has_cycle(acyclic)}   (expected False)")
    print()


def _find_node_with_val_trace(head: ListNode | None, val: int | None):
    """Find the FIRST node with the given value (for marking in list_str)."""
    if val is None:
        return None
    cur = head
    seen = set()
    while cur is not None and id(cur) not in seen:
        if cur.val == val:
            return cur
        seen.add(id(cur))
        cur = cur.next
    return None


# ============================================================================
# SECTION B - P876 MIDDLE OF THE LINKED LIST (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P876 Middle of the Linked List")
    print("=" * 72)
    print()
    print("Odd length:  1 -> 2 -> 3 -> 4 -> 5 -> None   (middle = 3)")
    head = build_list([1, 2, 3, 4, 5])
    print("  initial: ", list_str(head))
    print()
    steps = trace_middle(head)
    for s in steps:
        slow_node = _find_node_with_val_trace(head, s["slow"])
        fast_node = _find_node_with_val_trace(head, s["fast"])
        done = "  <-- fast can't advance, slow is the middle" if s["done"] else ""
        print(f"  step {s['i']}: slow at {s['slow']}, fast at {s['fast']}{done}")
        print(f"           {list_str(head, slow_node, fast_node)}")
    mid = find_middle(head)
    print(f"middle -> {mid.val if mid else None}   (expected 3)")
    print()
    print("Even length: 1 -> 2 -> 3 -> 4 -> None   (slow lands on SECOND middle = 3)")
    head2 = build_list([1, 2, 3, 4])
    print("  initial: ", list_str(head2))
    print()
    steps2 = trace_middle(head2)
    for s in steps2:
        slow_node = _find_node_with_val_trace(head2, s["slow"])
        fast_node = _find_node_with_val_trace(head2, s["fast"])
        done = "  <-- fast is None, slow on second middle" if s["done"] else ""
        print(f"  step {s['i']}: slow at {s['slow']}, fast at {s['fast']}{done}")
        print(f"           {list_str(head2, slow_node, fast_node)}")
    mid2 = find_middle(head2)
    print(f"middle -> {mid2.val if mid2 else None}   (expected 3, the second middle)")
    print()
    print("To get the FIRST middle for even lists, use a dummy start:")
    print("    slow, fast = head, ListNode(-1, head)")
    print("    while fast and fast.next: slow=slow.next; fast=fast.next.next")
    print()


# ============================================================================
# SECTION C - P202 HAPPY NUMBER (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P202 Happy Number  (cycle detection on a sequence)")
    print("=" * 72)
    print()
    print("Transformation: n -> sum of squared decimal digits.")
    print("A number is HAPPY iff the sequence reaches 1; otherwise it enters")
    print("a cycle that does NOT contain 1 (e.g. 4 -> 16 -> 37 -> 58 -> ... -> 4).")
    print()
    print("--- n = 19 (HAPPY) ---")
    print("  Full forward sequence from 19:")
    seq = []
    cur = 19
    for _ in range(8):
        seq.append(cur)
        if cur == 1:
            break
        cur = _sum_sq_digits(cur)
    print("   " + " -> ".join(str(x) for x in seq) + " -> 1 ...")
    print()
    print("  Floyd trace (slow=1 step, fast=2 steps, OFFSET INIT):")
    steps = trace_happy(19)
    for s in steps:
        tag = ""
        if s["hit1"]:
            tag = "  <-- fast hit 1 -> HAPPY"
        elif s["meet"]:
            tag = "  <-- slow == fast (cycle, no 1) -> NOT HAPPY"
        print(f"  step {s['i']}: slow={s['slow']}, fast={s['fast']}{tag}")
    print(f"is_happy(19) -> {is_happy(19)}   (expected True)")
    print()
    print("--- n = 2 (NOT HAPPY) ---")
    print("  The cycle is 4 -> 16 -> 37 -> 58 -> 89 -> 145 -> 42 -> 20 -> 4.")
    print("  Floyd trace:")
    steps2 = trace_happy(2)
    for s in steps2:
        tag = ""
        if s["hit1"]:
            tag = "  <-- fast hit 1 -> HAPPY"
        elif s["meet"]:
            tag = "  <-- slow == fast (cycle, no 1) -> NOT HAPPY"
        print(f"  step {s['i']}: slow={s['slow']}, fast={s['fast']}{tag}")
    print(f"is_happy(2) -> {is_happy(2)}   (expected False)")
    print()


# ============================================================================
# SECTION D - COMPLEXITY TABLE & GOTCHAS
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Operation                  Time      Space")
    print("  -------------------------  --------  --------")
    print("  Cycle detection (P141)     O(n)      O(1)")
    print("  Find middle (P876)         O(n)      O(1)")
    print("  Happy number (P202)        O(log n)  O(1)")
    print("  Find cycle START (P142)    O(n)      O(1)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. ALWAYS guard fast's two-step: `while fast and fast.next:`.")
    print("     Calling fast.next.next when fast.next is None crashes.")
    print("  2. Use `is` not `==` for the meet check: two DIFFERENT nodes")
    print("     can hold the same value. You want the same NODE.")
    print("  3. For sequences (Happy Number), OFFSET the start: slow=n,")
    print("     fast=get_next(n). Otherwise slow==fast fires immediately.")
    print("  4. Even-length lists: the basic skeleton lands slow on the")
    print("     SECOND middle node. Use a dummy start for the first middle.")
    print("  5. To find the cycle START (P142): after slow==fast, reset")
    print("     slow=head and move both at speed 1; they meet at the entry.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff   Key trick")
    print("  -------------------------------- ------  ----------------------------------------")
    print("  P141 Linked List Cycle           Easy    Floyd's; slow is fast -> cycle")
    print("  P876 Middle of Linked List       Easy    When fast can't move, slow is middle")
    print("  P202 Happy Number                Easy    Offset init; return fast == 1")
    print("  P142 Linked List Cycle II        Medium  Detect, then reset slow to find entry")
    print("  P287 Find Duplicate Number       Medium  Treat arr[i] as next ptr; cycle = dup")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions ----
    cyc = make_cycle([1, 2, 3, 4], pos=1)
    nocyc = build_list([1, 2, 3, 4])
    assert has_cycle(cyc) is True
    assert has_cycle(nocyc) is False
    assert has_cycle(build_list([])) is False
    assert has_cycle(build_list([1])) is False

    assert find_middle(build_list([1, 2, 3, 4, 5])).val == 3
    assert find_middle(build_list([1, 2, 3, 4])).val == 3  # second middle
    assert find_middle(build_list([1])).val == 1
    assert find_middle(build_list([])) is None

    assert is_happy(19) is True
    assert is_happy(1) is True
    assert is_happy(2) is False
    assert is_happy(7) is True

    print("=" * 72)
    print("[check] has_cycle / find_middle / is_happy ... OK")
    print("=" * 72)
