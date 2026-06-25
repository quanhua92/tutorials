"""
stack_queue_deque.py - Reference implementations of the three linear ADTs
(Stack, Queue, Deque) and the classic algorithms that justify each one.

This is the single source of truth that STACK_QUEUE_DEQUE.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 stack_queue_deque.py

==========================================================================
THE INTUITION (read this first) - the cafeteria and the printer
==========================================================================
Three containers, three disciplines about WHICH END you touch:

  * STACK  (LIFO - Last In, First Out). A stack of TRAYS in a cafeteria: you
            only ever take the tray on top, and you put new trays on top.
            One access point = the TOP.   Operations: push, pop, peek.

  * QUEUE  (FIFO - First In, First Out). A line at the PRINTER: the first
            person to join is the first served. Two access points: back (join)
            and front (leave).   Operations: enqueue, dequeue.

  * DEQUE  (Double-Ended Queue). A DECK of cards you can draw from or add to
            on EITHER side. Both ends are access points.
            Operations: push_front, push_back, pop_front, pop_back.

WHY THREE DIFFERENT STRUCTURES? Each one exists because a famous class of
algorithm needs EXACTLY that access discipline:

  * STACK is needed by function-call recursion (the call stack), expression
    evaluation (operator-precedence / shunting-yard), and undo histories.
    Section A.
  * QUEUE is needed by Breadth-First Search (FIFO frontier) and task
    scheduling / producer-consumer pipelines. Section B.
  * DEQUE is needed by sliding-window-monotonic algorithms (keep a window's
    max in O(1) amortized) and work-stealing schedulers. Section D.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  LIFO / FIFO   : Last-In-First-Out / First-In-First-Out. Which end exits.
  top           : the only accessible end of a Stack.
  front / back  : the two ends of a Queue. enqueue=back, dequeue=front.
  peek          : look at an end WITHOUT removing it.
  amortized O(1): most operations are O(1); occasionally one costs O(n) (an
                  array resize) but averaged out it is still O(1) per op.
  circular buffer: a fixed array used as a queue via head/tail indices that
                  wrap modulo capacity. Avoids shifting elements on dequeue.
  monotonic deque: a deque kept in decreasing (or increasing) order so the
                  front is always the window's max (or min) in O(1).

==========================================================================
COMPLEXITY CHEAT-SHEET (all verified in Section E)
==========================================================================
                      push/enqueue     pop/dequeue      peek      space
  -----------------------------------------------------------------------
  Stack (array)       amortized O(1)   O(1)            O(1)      O(n)
  Stack (linked list) O(1)             O(1)            O(1)      O(n) + ptrs
  Queue (array shift) O(1)             O(n) BAD        O(1)      O(n)
  Queue (circular)    O(1)             O(1)            O(1)      O(capacity)
  Queue (linked list) O(1)             O(1)            O(1)      O(n) + ptrs
  Deque (array-grow)  amortized O(1)   O(1)            O(1)      O(n)
  Deque (linked list) O(1)             O(1)            O(1)      O(n) + 2 ptrs

KEY TAKEAWAY: array-backed gives amortized O(1) + cache friendliness (the CPU
prefetcher loves contiguous memory); linked-list gives GUARANTEED O(1) (no
resize spikes) at the cost of pointer chasing (cache-unfriendly). Section E.

Source material: CLRS ch.10 (Elementary Data Structures), Sedgewick & Wayne
ch.1.3 (Stacks/Queues) and ch.1.4 (analysis of resizing arrays).
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. REFERENCE IMPLEMENTATIONS  (the code STACK_QUEUE_DEQUE.md walks through)
# ============================================================================

# --- (1a) Stack: array-backed, LIFO ---------------------------------------
class Stack:
    """LIFO stack backed by a growable Python list (dynamic array).

    push/pop are amortized O(1): pop is always O(1); push is O(1) except when
    the underlying array must be grown (rare, amortized away). See Section E.
    """

    def __init__(self):
        self._data: list = []

    def push(self, x):
        self._data.append(x)

    def pop(self):
        if not self._data:
            raise IndexError("pop from empty stack")
        return self._data.pop()

    def peek(self):
        if not self._data:
            raise IndexError("peek from empty stack")
        return self._data[-1]

    def __len__(self):
        return len(self._data)

    def is_empty(self):
        return not self._data

    def snapshot(self):
        """A copy of the stack, top = last element."""
        return list(self._data)


# --- (1b) Queue: array-backed FIFO with front-shift (the NAIVE version) ----
class NaiveQueue:
    """FIFO queue backed by a list that SHIFTS on dequeue.

    dequeue() pops index 0, which is O(n) - every other element moves down.
    Shown in Section B / E as the motivation for the circular buffer (1c).
    """

    def __init__(self):
        self._data: list = []

    def enqueue(self, x):
        self._data.append(x)

    def dequeue(self):
        if not self._data:
            raise IndexError("dequeue from empty queue")
        return self._data.pop(0)  # O(n) shift - the whole point of 1c

    def peek(self):
        if not self._data:
            raise IndexError("peek from empty queue")
        return self._data[0]

    def __len__(self):
        return len(self._data)

    def snapshot(self):
        return list(self._data)


# --- (1c) Circular-buffer queue: fixed array + head/tail mod capacity ------
class CircularQueue:
    """FIFO queue in a FIXED array, head/tail wrap modulo capacity.

    Both enqueue and dequeue are TRUE O(1): no element ever moves; we just
    advance an index modulo `capacity`. The price is a hard capacity bound
    and the need to distinguish full from empty (we track `count`).

    Layout (capacity C = 4) after wrap-around:
        index :  0   1   2   3
        buf   : [E] [F] [C] [D]
                 ^tail       ^head
        count = 4, head = 2, tail = 0  -> logical order: C, D, E, F
    """

    def __init__(self, capacity: int):
        self.cap = capacity
        self.buf: list = [None] * capacity
        self.head = 0      # index of the front element
        self.tail = 0      # index where the NEXT enqueue writes
        self.count = 0

    def enqueue(self, x):
        if self.count == self.cap:
            raise OverflowError("circular queue full")
        self.buf[self.tail] = x
        self.tail = (self.tail + 1) % self.cap
        self.count += 1

    def dequeue(self):
        if self.count == 0:
            raise IndexError("dequeue from empty queue")
        x = self.buf[self.head]
        self.buf[self.head] = None
        self.head = (self.head + 1) % self.cap
        self.count -= 1
        return x

    def logical_order(self):
        """Logical FIFO order front->back, following head modulo cap."""
        out = []
        for i in range(self.count):
            out.append(self.buf[(self.head + i) % self.cap])
        return out


# --- (1d) Deque: double-ended, array-backed (grow both ways) --------------
class Deque:
    """Double-ended queue backed by a growable list.

    Both ends support O(1) push and pop (Python list append/pop at the tail is
    O(1); pop(0) is O(n), so for the front we use index 0 via pop(0) ONLY in
    the naive demo. The monotonic-deque algorithm (Section D) only ever pops
    from the two ends, so it stays amortized O(1) per element. A production
    deque (collections.deque) uses a doubly-linked block array for O(1) both
    ends - see Section E.
    """

    def __init__(self):
        self._data: list = []

    def push_back(self, x):
        self._data.append(x)

    def push_front(self, x):
        self._data.insert(0, x)  # O(n); real deques avoid this (Section E)

    def pop_back(self):
        if not self._data:
            raise IndexError("pop_back from empty deque")
        return self._data.pop()

    def pop_front(self):
        if not self._data:
            raise IndexError("pop_front from empty deque")
        return self._data.pop(0)

    def front(self):
        return self._data[0]

    def back(self):
        return self._data[-1]

    def __len__(self):
        return len(self._data)

    def snapshot(self):
        return list(self._data)


# --- (1e) Linked-list Stack: GUARANTEED O(1), for the Section E comparison --
class _Node:
    __slots__ = ("val", "next")

    def __init__(self, val, nxt=None):
        self.val = val
        self.next = nxt


class LinkedListStack:
    """Stack as a singly linked list head. push/pop/peek are all TRUE O(1):
    no array, so no resize can ever spike a push. The cost is one pointer per
    node and poor cache locality (nodes are scattered in the heap). Section E.
    """

    def __init__(self):
        self._head = None
        self._size = 0

    def push(self, x):
        self._head = _Node(x, self._head)
        self._size += 1

    def pop(self):
        if self._head is None:
            raise IndexError("pop from empty stack")
        x = self._head.val
        self._head = self._head.next
        self._size -= 1
        return x

    def peek(self):
        if self._head is None:
            raise IndexError("peek from empty stack")
        return self._head.val

    def __len__(self):
        return self._size

    def snapshot(self):
        out = []
        node = self._head
        while node is not None:
            out.append(node.val)
            node = node.next
        return out  # head = top, i.e. top first


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def show_stack(label, st):
    """Print a stack vertically, top element first (the accessible end)."""
    snap = st.snapshot() if hasattr(st, "snapshot") else list(st)
    print(f"  {label} (top -> bottom): {snap}")


def show_queue(label, q):
    snap = q.snapshot() if hasattr(q, "snapshot") else list(q)
    print(f"  {label} (front -> back): {snap}")


# ============================================================================
# 3. ALGORITHMS
# ============================================================================

# --- Section A: operator-precedence expression evaluation (two stacks) ----
PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2}


def tokenize(expr: str):
    """Split '3 + 4 * 2' into [3, '+', 4, '*', 2] (ints and str operators)."""
    toks = []
    for tok in expr.split():
        if tok in PRECEDENCE:
            toks.append(tok)
        elif tok in "()":
            toks.append(tok)
        else:
            toks.append(int(tok))
    return toks


def apply_op(op, b, a):
    """a op b (note operand order: the FIRST popped is the RIGHT operand)."""
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        return a // b
    raise ValueError(op)


def evaluate_infix(expr: str, stack_factory=Stack, trace=False):
    """Dijkstra two-stack algorithm for + - * / with precedence and parens.

    values stack holds numbers; ops stack holds operators. On seeing an
    operator o, first drain any stacked operator whose precedence is >= o's
    (left-associative: '3 - 2 - 1' must be '(3-2)-1'). Parens just push '('
    and flush until '(' on ')'. The trace prints both stacks at every token -
    this is the material for the .md and .html.
    """
    values = stack_factory()
    ops = stack_factory()
    for tok in tokenize(expr):
        if isinstance(tok, int):
            values.push(tok)
        elif tok == "(":
            ops.push(tok)
        elif tok == ")":
            while (len(ops) > 0) and ops.peek() != "(":
                values.push(apply_op(ops.pop(), values.pop(), values.pop()))
            ops.pop()  # discard '('
        else:  # an operator
            while (len(ops) > 0) and ops.peek() != "(" \
                    and PRECEDENCE[ops.peek()] >= PRECEDENCE[tok]:
                values.push(apply_op(ops.pop(), values.pop(), values.pop()))
            ops.push(tok)
        if trace:
            print(f"    read {tok!r:>5}  | values={values.snapshot()}  "
                  f"ops={ops.snapshot()}")
    while len(ops) > 0:
        values.push(apply_op(ops.pop(), values.pop(), values.pop()))
        if trace:
            print(f"    flush op    | values={values.snapshot()}  "
                  f"ops={ops.snapshot()}")
    result = values.pop()
    return result


# --- Section B: Breadth-First Search using a FIFO queue -------------------
def bfs(graph, start, queue_factory=NaiveQueue, trace=False):
    """BFS over `graph` (adjacency list). Returns (visit_order, snapshots).

    The FIFO queue is the FRONTIER: nodes discovered but not yet explored.
    Dequeue a node, enqueue its unvisited neighbors. Visiting order is the
    order nodes are dequeued. The queue snapshot at each step is returned so
    the .md/.html can show the frontier growing and shrinking.
    """
    visited = set([start])
    order = []
    snaps = []
    q = queue_factory()
    q.enqueue(start)
    snaps.append((f"start: enqueue {start}", q.snapshot()))
    while len(q) > 0:
        node = q.dequeue()
        order.append(node)
        snaps.append((f"dequeue {node} -> visit", q.snapshot()))
        for nb in graph[node]:
            if nb not in visited:
                visited.add(nb)
                q.enqueue(nb)
        if len(q) > 0 or True:
            snaps.append((f"  enqueue neighbors of {node}",
                          q.snapshot()))
        if trace:
            print(f"    visit {node}  frontier={q.snapshot()}")
    return order, snaps


# --- Section D: sliding-window maximum via a monotonic deque of indices ---
def sliding_window_max(nums, k, trace=False):
    """Max of every length-k window of `nums`, in O(n) total.

    The deque stores INDICES, kept so that nums[deque] is strictly DECREASING.
    Therefore deque.front() is always the index of the current window's max.
    For each new element we: (1) drop indices that fell out of the window,
    (2) pop back while the back value <= new value (they can never be a max
    again), (3) push the new index, (4) once the first window is full, emit
    nums[front]. Each index enters and leaves the deque at most once -> O(n).
    """
    dq = Deque()
    out = []
    steps = []
    for i, x in enumerate(nums):
        # (1) evict indices outside the window [i-k+1 .. i]
        while len(dq) > 0 and dq.front() <= i - k:
            dq.pop_front()
        # (2) maintain decreasing invariant: pop smaller-or-equal from back
        while len(dq) > 0 and nums[dq.back()] <= x:
            dq.pop_back()
        # (3) push current index
        dq.push_back(i)
        # (4) emit once the first window is full
        if i >= k - 1:
            out.append(nums[dq.front()])
        if trace:
            win = nums[max(0, i - k + 1):i + 1]
            steps.append((i, x, win, list(dq.snapshot()),
                          out[-1] if out else None))
    return out, steps


# ============================================================================
# 4. THE SECTIONS (each prints what the guide pastes)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: Stack + operator-precedence expression evaluation
# ----------------------------------------------------------------------------
def section_stack():
    banner("SECTION A: Stack (LIFO) - push / pop / peek")
    s = Stack()
    print("A stack has ONE access point: the TOP. push adds on top, pop\n"
          "removes from top. Shown as top -> bottom (leftmost = top).\n")
    for v in [10, 20, 30]:
        s.push(v)
        show_stack("after push", s)
    print(f"  peek() -> {s.peek()}   (top, not removed)")
    print(f"  pop()  -> {s.pop()}")
    print(f"  pop()  -> {s.pop()}")
    show_stack("after two pops", s)

    print("\n--- Operator-precedence evaluation of '3 + 4 * 2' ---")
    print("Two stacks: VALUES (numbers) and OPS (operators). Rule: a stacked\n"
          "operator with precedence >= the incoming one fires first\n"
          "(left-associative). '*' (prec 2) outranks '+' (prec 1), so\n"
          "'4 * 2' is computed BEFORE the '+' is applied. Trace:\n")
    result = evaluate_infix("3 + 4 * 2", trace=True)
    print(f"\n  result = {result}    (== 3 + (4 * 2) = 3 + 8 = 11)")
    assert result == 11, "expression gold check failed"
    print("[check] '3 + 4 * 2' == 11:  OK")

    print("\n--- Parentheses override precedence: '( 3 + 4 ) * 2' ---")
    result2 = evaluate_infix("( 3 + 4 ) * 2", trace=False)
    print(f"  result = {result2}    (== (3 + 4) * 2 = 7 * 2 = 14)")
    assert result2 == 14
    print("[check] '( 3 + 4 ) * 2' == 14:  OK")

    # GOLD for the .html: the headline expression's result, pinned.
    print("\nGOLD scalar (for stack_queue_deque.html): "
          "evaluate_infix('3 + 4 * 2') = 11")
    return result


# ----------------------------------------------------------------------------
# SECTION B: Queue (FIFO) + Breadth-First Search
# ----------------------------------------------------------------------------
def section_queue():
    banner("SECTION B: Queue (FIFO) - enqueue / dequeue, and BFS")
    # the naive shifting queue first
    q = NaiveQueue()
    print("A queue has TWO access points: BACK (enqueue) and FRONT (dequeue).\n"
          "First in, first out. Shown as front -> back (leftmost = front).\n")
    for v in ["A", "B", "C"]:
        q.enqueue(v)
        show_queue("after enqueue", q)
    print(f"  peek()    -> {q.peek()}   (front, not removed)")
    print(f"  dequeue() -> {q.dequeue()}")
    print(f"  dequeue() -> {q.dequeue()}")
    show_queue("after two dequeues", q)

    print("\n--- BFS on a 6-node graph (queue = the FIFO frontier) ---")
    # adjacency list: a small DAG-shaped graph, root 0
    graph = {
        0: [1, 2],
        1: [3, 4],
        2: [5],
        3: [],
        4: [],
        5: [],
    }
    print("graph (adjacency list):")
    for n in sorted(graph):
        print(f"    {n} -> {graph[n]}")
    print("\nBFS from 0. At each step we DEQUEUE one node to visit, then\n"
          "ENQUEUE its unvisited neighbors. The queue is the frontier:\n")
    order, snaps = bfs(graph, 0, trace=False)
    for desc, snap in snaps:
        print(f"    {desc:32s} frontier(front->back) = {snap}")
    print(f"\n  BFS visit order: {order}")
    assert order == [0, 1, 2, 3, 4, 5], "BFS gold check failed"
    print("[check] BFS visit order == [0, 1, 2, 3, 4, 5]:  OK")

    # GOLD for the .html
    print("\nGOLD (for stack_queue_deque.html): BFS order = [0, 1, 2, 3, 4, 5]")
    return order


# ----------------------------------------------------------------------------
# SECTION C: Circular-buffer queue (true O(1), no shifting)
# ----------------------------------------------------------------------------
def section_circular():
    banner("SECTION C: Circular-buffer queue - head/tail mod capacity")
    print("Problem with the naive queue: dequeue() is O(n) because pop(0)\n"
          "shifts every element. FIX: a FIXED array + two indices that wrap\n"
          "modulo capacity. Neither enqueue nor dequeue ever moves data ->\n"
          "both are TRUE O(1). The trick is `index = (index + 1) % cap`.\n")
    C = 4
    cq = CircularQueue(C)
    print(f"capacity = {C}. Track head (front), tail (next write), count.\n")

    def state(note):
        print(f"    {note:34s} buf={cq.buf} head={cq.head} tail={cq.tail} "
              f"count={cq.count} logical={cq.logical_order()}")

    state("init")
    for v in ["A", "B", "C", "D"]:
        cq.enqueue(v)
        state(f"enqueue {v}")
    print("    ^ buffer is now FULL (count == capacity).")
    print(f"    dequeue() -> {cq.dequeue()}   (A leaves; head advances, NO shift)")
    state("after dequeue A")
    print(f"    dequeue() -> {cq.dequeue()}   (B leaves)")
    state("after dequeue B")
    print("    Now tail has wrapped to index 0. Enqueuing writes there:")
    cq.enqueue("E")
    state("enqueue E  <- tail wrapped to 0")
    cq.enqueue("F")
    state("enqueue F  <- tail wrapped to 1; buffer FULL again")
    print("\n  The logical FIFO order (following head mod cap) is "
          f"{cq.logical_order()} = [C, D, E, F].")
    assert cq.logical_order() == ["C", "D", "E", "F"], "circular gold failed"
    print("[check] circular logical order == [C, D, E, F]:  OK")
    print("        (head=2, tail=2, count=4: full; tail caught head)")
    return cq.logical_order()


# ----------------------------------------------------------------------------
# SECTION D: Deque + sliding-window maximum (monotonic deque)
# ----------------------------------------------------------------------------
def section_deque():
    banner("SECTION D: Deque - both ends, and sliding-window maximum")
    dq = Deque()
    print("A deque admits push/pop on BOTH ends. Shown front -> back.\n")
    dq.push_back(2)
    show_queue("push_back 2", dq)
    dq.push_back(5)
    show_queue("push_back 5", dq)
    dq.push_front(1)
    show_queue("push_front 1", dq)
    print(f"  pop_front() -> {dq.pop_front()}   pop_back() -> {dq.pop_back()}")
    show_queue("after both pops", dq)

    print("\n--- Sliding-window maximum, window k = 3 ---")
    nums = [1, 3, -1, -3, 5, 3, 6, 7]
    k = 3
    print(f"nums = {nums}, k = {k}")
    print("Keep a deque of INDICES whose values are STRICTLY DECREASING, so\n"
          "the FRONT is always the window's max. For each new element:\n"
          "  (1) drop front if its index left the window,\n"
          "  (2) pop back while back value <= new value,\n"
          "  (3) push the new index,\n"
          "  (4) once i >= k-1, emit nums[front].\n")
    out, steps = sliding_window_max(nums, k, trace=True)
    print(f"\n  {'i':>2} {'x':>4}  {'window':>16}  "
          f"{'deque(indices)':>18}  {'max':>4}")
    for i, x, win, dqsnap, mx in steps:
        mxs = " " if mx is None else f"{mx:+}"
        print(f"  {i:>2} {x:>+4}  {str(win):>16}  {str(dqsnap):>18}  {mxs:>4}")
    print(f"\n  result = {out}")
    assert out == [3, 3, 5, 5, 6, 7], "sliding-window gold failed"
    print("[check] sliding-window max == [3, 3, 5, 5, 6, 7]:  OK")
    print("        Each index enters and leaves the deque <= once -> O(n).")

    # GOLD for the .html
    print("\nGOLD (for stack_queue_deque.html): "
          "sliding_window_max([1,3,-1,-3,5,3,6,7], 3) = [3,3,5,5,6,7]")
    return out


# ----------------------------------------------------------------------------
# SECTION E: array vs linked-list implementations (gold cross-check)
# ----------------------------------------------------------------------------
def section_impl_compare():
    banner("SECTION E: array vs linked-list implementations")
    print("Same ADT, two backings. The trade-off is AMORTIZED vs GUARANTEED\n"
          "O(1), plus cache behavior:\n")
    print("| backing      | push/enq      | pop/deq | resize spike? | "
          "cache     | per-node overhead |")
    print("|--------------|---------------|---------|---------------|"
          "-----------|-------------------|")
    print("| array        | amortized O(1)| O(1)    | yes (rare)    | "
          "friendly  | 0 (contiguous)    |")
    print("| linked list  | GUARANTEED O(1)| O(1)   | never         | "
          "unfriendly| 1-2 pointers      |")
    print()
    print("AMORTIZED O(1): a single push may trigger a resize that copies all\n"
          "n elements (O(n)), but this happens so rarely (doubling strategy)\n"
          "that the AVERAGE cost over n pushes is still O(1). Linked lists\n"
          "never resize, so worst-case push is O(1) - but every node costs a\n"
          "pointer and the CPU prefetcher cannot pre-load scattered nodes.\n")

    # GOLD cross-check: evaluate the SAME expression with both backings.
    expr = "3 + 4 * 2 - 5"
    r_array = evaluate_infix(expr, stack_factory=Stack)
    r_linked = evaluate_infix(expr, stack_factory=LinkedListStack)
    native = 3 + 4 * 2 - 5
    print(f"Gold cross-check: evaluate '{expr}' three ways")
    print(f"  array-backed  Stack : {r_array}")
    print(f"  linked-list   Stack : {r_linked}")
    print(f"  Python native expr  : {native}")
    match = (r_array == r_linked == native)
    print(f"  [check] all three agree ({native})?  {match}")
    assert match, "implementation comparison gold failed"

    # Why amortized O(1) for array append: doubling strategy cost analysis.
    print("\nCost analysis of array-append doubling (capacity 1 -> 2 -> 4 ...):")
    print("  pushes 1..n: total work = n (the pushes) + (1+2+4+...+n) "
          "(the copies)")
    n = 16
    total_copies = 0
    cap = 1
    copies_log = []
    while cap < n:
        copies_log.append(cap)
        total_copies += cap
        cap *= 2
    print(f"  for n = {n}: resize copies = {' + '.join(map(str, copies_log))} "
          f"= {total_copies}, which is < 2n. So total = O(n) -> O(1) amortized.")
    assert total_copies < 2 * n
    print(f"  [check] resize copies ({total_copies}) < 2n ({2 * n}):  OK")
    return native


# ============================================================================
# main
# ============================================================================

def main():
    print("stack_queue_deque.py - reference impl. "
          "All numbers below feed STACK_QUEUE_DEQUE.md.")
    print("pure Python stdlib; run with: python3 stack_queue_deque.py")

    section_stack()
    section_queue()
    section_circular()
    section_deque()
    section_impl_compare()

    banner("DONE - all sections printed, all gold checks OK")


if __name__ == "__main__":
    main()
