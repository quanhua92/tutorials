"""
array_vs_linkedlist.py - Reference implementation comparing Array vs Linked List.

This is the SINGLE SOURCE OF TRUTH for ARRAY_VS_LINKEDLIST.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 array_vs_linkedlist.py > array_vs_linkedlist_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

=========================================================================
THE INTUITION (read this first) — the bookshelf vs the treasure hunt
=========================================================================
An ARRAY is one long BOOKSHELF: every book sits right next to the last. To get
book #3 you walk straight to slot 3 — you know exactly where it is because the
shelf is one solid block of wood. But to INSERT a book in the middle you must
slide every later book one slot to the right (expensive).

A LINKED LIST is a TREASURE HUNT: each clue (node) tells you where the next clue
is, but the clues are HIDDEN ALL OVER TOWN. To find clue #3 you must follow the
chain from clue #0 -> #1 -> #2 -> #3 (slow). But to INSERT a new clue you just
rewrite TWO clues' "next" pointers — nothing else moves (cheap).

THE REASON ARRAYS WIN IN PRACTICE (the plot of this whole bundle):
The CPU does not fetch memory one byte at a time. It fetches a whole CACHE LINE
(64 bytes = 16 ints) at once. On the bookshelf, grabbing book #0 silently drags
books #1..#15 into the fast L1 cache for FREE — spatial locality. On the treasure
hunt, clue #0 is in one part of town and clue #1 is across town, so each clue is
a fresh cache MISS. Pointer chasing = cache thrashing. Big-O says linked-list
insert is O(1); reality says the traversal to FIND the spot is cache-miss-bound,
so the array usually wins overall. THAT is the lesson.

=========================================================================
PLAIN-ENGLISH GLOSSARY
=========================================================================
  element / item   one value stored in the structure (here: a 4-byte int).
  index i          the position of an element, counting from 0.
  address          where a byte lives in (fake) memory. We print it as 0x....
  contiguous       addresses that are back-to-back with no gaps.
  node             a linked-list cell: [value | next-pointer].
  next-pointer     the address of the NEXT node (or 0 / null if it is the tail).
  head             the first node. tail = the last node (next == null).
  cache line       the unit the CPU fetches from RAM. 64 bytes = 16 ints here.
  cache hit / miss a fetch that finds / does not find the data already in L1.
  locality         spatial = nearby addresses reused; temporal = same address
                   reused soon. Arrays have both; linked lists have neither.

=========================================================================
THE TWO STRUCTURES (CLRS ch. 10)
=========================================================================
  Array        (CLRS 10.1, "stacks and queues" use it): a contiguous block of
               equal-sized cells. addr(a[i]) = base + i * sizeof(cell).
               O(1) random access; O(N) middle insert/delete (shift).
  Linked list  (CLRS 10.2): nodes linked by pointers. No random access; insert
               and delete at a KNOWN node are O(1) (pointer rewrire only).

KEY FACTS (all asserted in code below, gold-checked):
    array access      a[i]  costs 1 add + 1 mul  (O(1))      — addr = base + i*4
    list access       L[i]  costs i pointer follows (O(N))   — chase head->...->i
    array insert mid  shift (N - i) cells right              — O(N) moves
    list  insert mid  (given the predecessor) 1 pointer swap — O(1) moves
    cache line        64 bytes = 16 ints (int = 4 bytes)
    cold misses, sequential array scan of N ints  = ceil(N / 16)
    cold misses, scattered linked-list scan of N   = N   (one per node)

Conventions used throughout:
    INT_SIZE   = 4   bytes  (a C int)
    PTR_SIZE   = 8   bytes  (a 64-bit pointer)
    NODE_SIZE  = 16  bytes  (4 + 8, padded to 16 for alignment)
    LINE_SIZE  = 64  bytes  (one L1 cache line  = 16 ints, or 4 nodes)
"""

from __future__ import annotations

BANNER = "=" * 72

INT_SIZE = 4      # bytes per int cell
PTR_SIZE = 8      # bytes per pointer
NODE_SIZE = 16    # padded node = value(4) + next(8), rounded to 16 for alignment
LINE_SIZE = 64    # L1 cache line in bytes (= 16 ints, = 4 nodes)


# ============================================================================
# 0. THE TWO STRUCTURES (deterministic, in fake memory)
# ============================================================================

def hexaddr(n: int) -> str:
    return f"0x{n:04x}"


class ArrayList:
    """A contiguous array of ints living at a fixed base address.

    Cell i sits at address  base + i*INT_SIZE.  No pointers, no nodes:
    address is COMPUTED, never stored. That is the whole reason random access
    is O(1) and cache-friendly.
    """

    def __init__(self, values: list[int], base: int):
        self.values = list(values)
        self.base = base
        self.n = len(values)

    def addr_of(self, i: int) -> int:
        return self.base + i * INT_SIZE

    def get(self, i: int) -> int:
        return self.values[i]


class LinkedList:
    """A singly linked list of nodes scattered in (fake) memory.

    Each node carries a VALUE and a NEXT pointer (address of the next node, 0
    for the tail). Addresses are assigned by the caller, so we can place nodes
    anywhere — including far apart, which is the realistic, cache-hostile case.
    """

    def __init__(self, values: list[int], addrs: list[int]):
        assert len(values) == len(addrs)
        self.n = len(values)
        # node i: value at addrs[i], next pointer at addrs[i] + INT_SIZE
        self.values = list(values)
        self.addrs = list(addrs)
        # next[i] = address of node i+1, or 0 if tail
        self.next = [addrs[i + 1] if i + 1 < self.n else 0 for i in range(self.n)]
        self.head_addr = addrs[0] if self.n else 0

    def node_value_addr(self, i: int) -> int:
        return self.addrs[i]

    def node_next_addr(self, i: int) -> int:
        return self.addrs[i] + INT_SIZE

    def find_index_of_addr(self, addr: int) -> int:
        """Inverse of addrs[i] — which node lives at this address?"""
        return self.addrs.index(addr)


# ============================================================================
# 1. THE CACHE SIMULATOR (direct-mapped-in-spirit, LRU over line tags)
#    Models an L1 with `capacity` lines, each LINE_SIZE bytes, LRU eviction.
# ============================================================================

class Cache:
    """A tiny L1 cache model.

    access(addr): the line tag = addr // LINE_SIZE. If the tag is resident it
    is a HIT (and, under LRU, moved to most-recently-used); otherwise it is a
    MISS — the line is loaded, evicting the least-recently-used if full.

    The miss count is what we gold-check against the .html. It depends ONLY on
    the sequence of addresses touched and (line_size, capacity), so the JS
    recompute in array_vs_linkedlist.html reproduces it exactly.
    """

    def __init__(self, line_size: int = LINE_SIZE, capacity: int = 8):
        self.line_size = line_size
        self.capacity = capacity
        self.tags: list[int] = []      # LRU order; index 0 = least recent
        self.hits = 0
        self.misses = 0

    def tag(self, addr: int) -> int:
        return addr // self.line_size

    def access(self, addr: int) -> bool:
        t = self.tag(addr)
        if t in self.tags:
            self.hits += 1
            self.tags.remove(t)
            self.tags.append(t)        # bump to MRU
            return True
        self.misses += 1
        if len(self.tags) >= self.capacity:
            self.tags.pop(0)           # evict LRU
        self.tags.append(t)
        return False

    def reset(self) -> None:
        self.tags = []
        self.hits = 0
        self.misses = 0


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ----------------------------------------------------------------------------
# SECTION A: memory layout — contiguous array vs scattered linked list
# ----------------------------------------------------------------------------

def section_memory_layout() -> tuple[ArrayList, LinkedList]:
    banner("SECTION A: memory layout  (contiguous array vs scattered linked list)")
    values = [10, 20, 30, 40]
    n = len(values)
    print(f"Store the same four ints {values} two ways. INT_SIZE={INT_SIZE}B, "
          f"PTR_SIZE={PTR_SIZE}B, NODE_SIZE={NODE_SIZE}B (padded).\n")

    # ---- ARRAY: one contiguous block at base 0x1000 ----
    arr = ArrayList(values, base=0x1000)
    print("ARRAY  — one contiguous block. address of cell i = base + i*INT_SIZE:")
    print(f"  base = {hexaddr(arr.base)}")
    for i in range(n):
        a = arr.addr_of(i)
        nxt = arr.addr_of(i + 1) if i + 1 < n else arr.addr_of(i) + INT_SIZE
        gap = nxt - a
        print(f"  a[{i}] = {arr.get(i):>3}  @ {hexaddr(a)}   "
              f"(next cell +{gap}B = {hexaddr(nxt)})")
    span = arr.addr_of(n - 1) + INT_SIZE - arr.base
    print(f"  whole array spans {span} contiguous bytes "
          f"[{hexaddr(arr.base)} .. {hexaddr(arr.addr_of(n-1)+INT_SIZE-1)}]. "
          f"Zero gaps. Zero pointers.\n")

    # ---- LINKED LIST: nodes scattered far apart ----
    addrs = [0x2000, 0x3000, 0x4000, 0x5000]      # 4 KiB apart -> different cache lines
    ll = LinkedList(values, addrs)
    print("LINKED LIST — four NODES scattered across memory, glued by pointers:")
    for i in range(n):
        va = ll.node_value_addr(i)
        na = ll.node_next_addr(i)
        nxt = ll.next[i]
        nxt_s = hexaddr(nxt) if nxt else "NULL"
        print(f"  node {i}: value {ll.values[i]:>3} @ {hexaddr(va)}  |  "
              f"next @ {hexaddr(na)} -> {nxt_s}")
    print(f"  head @ {hexaddr(ll.head_addr)}  (points at node 0). "
          f"Nodes are {hexaddr(addrs[1])}-{hexaddr(addrs[0])} = "
          f"{addrs[1]-addrs[0]}B apart — NOT contiguous.")
    print("\nRead it side by side:")
    print("  ARRAY      cells: 0x1000 0x1004 0x1008 0x100c   (stride +4B, touching)")
    print("  LIST  node addrs: 0x2000 0x3000 0x4000 0x5000   (stride +4096B, far)")
    print("Same data, totally different footprint. The array's contiguity is the")
    print("seed of every advantage that follows.")
    return arr, ll


# ----------------------------------------------------------------------------
# SECTION B: access — array O(1) indexing vs linked list O(N) traversal
# ----------------------------------------------------------------------------

def section_access(arr: ArrayList, ll: LinkedList) -> None:
    banner("SECTION B: access  (array O(1) indexing vs linked list O(N) traversal)")
    target = 2
    print(f"Fetch element at index i = {target} "
          f"(value = {arr.get(target)}) from each structure.\n")

    # ---- ARRAY: compute address, one memory touch ----
    print("ARRAY  — compute the address arithmetically, touch ONE cell:")
    computed = arr.addr_of(target)
    print(f"  addr = base + i*INT_SIZE = {hexaddr(arr.base)} + {target}*{INT_SIZE} "
          f"= {hexaddr(computed)}")
    print(f"  pointer follows: 0     arithmetic ops: 1 add + 1 mul")
    print(f"  memory accesses: 1     => O(1)\n")

    # ---- LINKED LIST: chase pointers from the head ----
    print("LINKED LIST — cannot compute a node address; CHASE pointers from head:")
    cur = ll.head_addr
    follows = 0
    print(f"  start at head @ {hexaddr(cur)} (node 0)")
    for step in range(target):
        nxt = ll.next[step]
        follows += 1
        print(f"  follow next @ {hexaddr(ll.node_next_addr(step))} "
              f"-> node {step+1} @ {hexaddr(nxt)}   (pointer follow #{follows})")
    print(f"  pointer follows: {follows}   memory accesses: {follows+1} "
          f"(each follow reads a next pointer; +1 to read the value)")
    print(f"  => O(N). To reach index i you ALWAYS do i pointer follows.\n")

    print("Summary of access cost (N elements, fetching index i):")
    print("| structure   | cost         | why                                   |")
    print("|-------------|--------------|---------------------------------------|")
    print("| array       | O(1)         | address is computed: base + i*size    |")
    print("| linked list | O(N) worst   | must chase i next-pointers from head  |")
    print(f"[check] array fetches index {target} in 1 access; "
          f"list needs {target} follows = {target} fetches: OK")


# ----------------------------------------------------------------------------
# SECTION C: insert / delete — array shift O(N) vs linked list O(1)
# ----------------------------------------------------------------------------

def section_insert_delete() -> None:
    banner("SECTION C: insert / delete  "
           "(array shift O(N) vs linked list pointer swap O(1))")
    n = 4
    print(f"Insert a NEW value (99) at index 1 of an N={n} element structure.\n")

    # ---- ARRAY: shift cells 1..N-1 one slot right, then drop in ----
    arr_vals = [10, 20, 30, 40]
    idx = 1
    shifts = n - idx                 # cells that must move right
    print("ARRAY — make room by shifting every cell from idx..N-1 one slot RIGHT:")
    print(f"  before: {arr_vals}")
    print(f"  shift cell 3 (40) right -> [10,20,30,_,40]   move #{1}")
    print(f"  shift cell 2 (30) right -> [10,20,_,30,40]   move #{2}")
    print(f"  shift cell 1 (20) right -> [10,_,20,30,40]   move #{3}")
    print(f"  write 99 into slot 1    -> [10,99,20,30,40]")
    print(f"  cells moved: {shifts}  (right-to-left so we do not clobber)  => O(N)")
    print(f"  worst case insert at front (idx=0): shift all N={n} cells.\n")

    # ---- LINKED LIST: given a pointer to the predecessor, rewire 2 pointers ----
    print("LINKED LIST — we ALREADY hold a pointer to node 0 (the predecessor).")
    print("  before: node0(10) -> node1(20) -> node2(30) -> node3(40) -> NULL")
    print("  step 1: new.next      = node0.next          (1 pointer read)")
    print("  step 2: node0.next    = &new                (1 pointer write)")
    print("  after:  node0(10) -> new(99) -> node1(20) -> node2(30) -> node3(40)")
    print("  cells moved: 0   pointer ops: 2  => O(1)  (NO data ever shifts)\n")

    print("Delete is the mirror image (shift LEFT for array; rewire 1-2 pointers "
          "for list):\n")
    print("| operation (at index/pos i) | array            | linked list (given pred) |")
    print("|----------------------------|------------------|---------------------------|")
    print("| insert                     | O(N) shift right | O(1) pointer swap         |")
    print("| delete                     | O(N) shift left  | O(1) pointer swap         |")
    print()
    print("THE CATCH (CLRS 10.2): the O(1) is only for insert/delete at a KNOWN")
    print("node. Finding that node is the O(N) traversal from Section B. So a")
    print("\"linked-list insert at index i\" is still O(N) end-to-end unless you")
    print("already hold the predecessor pointer. Arrays pay at insert time;")
    print("lists pay at search time. Pick your poison — then add cache effects.")


# ----------------------------------------------------------------------------
# SECTION D: cache simulation — array hits L1, linked list misses every time
# ----------------------------------------------------------------------------

def scan_cache_cost(addrs_sequence: list[int], line_size: int, capacity: int):
    """Run an L1 sim over a sequence of addresses; return (hits, misses)."""
    c = Cache(line_size=line_size, capacity=capacity)
    for a in addrs_sequence:
        c.access(a)
    return c.hits, c.misses


def section_cache_simulation() -> dict:
    banner("SECTION D: cache simulation  "
           "(array hits L1, linked list misses every access)")
    N = 32
    print(f"Sequentially READ all N={N} elements of each structure and count "
          f"L1 cache hits/misses.\n")
    print(f"Cache model: line_size={LINE_SIZE}B ({LINE_SIZE//INT_SIZE} ints/line), "
          f"capacity=8 lines, LRU eviction.\n")

    # ---- ARRAY addresses: contiguous from 0x1000 ----
    arr_base = 0x1000
    arr_addrs = [arr_base + i * INT_SIZE for i in range(N)]
    print(f"ARRAY addresses: {hexaddr(arr_addrs[0])} .. {hexaddr(arr_addrs[-1])} "
          f"(contiguous, stride +{INT_SIZE}B).")
    print(f"  line tags touched: "
          f"{sorted(set(a // LINE_SIZE for a in arr_addrs))}")
    ints_per_line = LINE_SIZE // INT_SIZE
    expected_arr_misses = (N + ints_per_line - 1) // ints_per_line   # ceil
    arr_hits, arr_misses = scan_cache_cost(arr_addrs, LINE_SIZE, 8)
    print(f"  result: hits={arr_hits}, misses={arr_misses}  "
          f"(= ceil({N}/{ints_per_line}) = {expected_arr_misses} cold misses)")
    print(f"  why: reading int 0 drags ints 1..{ints_per_line-1} into L1 for FREE "
          f"(spatial locality). One miss feeds {ints_per_line} reads.\n")

    # ---- LINKED LIST addresses: scattered, one node per cache line ----
    ll_base = 0x10000
    ll_addrs = [ll_base + i * (LINE_SIZE * 2) for i in range(N)]   # 2 lines apart
    print(f"LINKED LIST node addresses: {hexaddr(ll_addrs[0])}, "
          f"{hexaddr(ll_addrs[1])}, ... (scattered, stride +{LINE_SIZE*2}B).")
    print(f"  distinct line tags touched: "
          f"{len(set(a // LINE_SIZE for a in ll_addrs))} (one per node)")
    ll_hits, ll_misses = scan_cache_cost(ll_addrs, LINE_SIZE, 8)
    print(f"  result: hits={ll_hits}, misses={ll_misses}  "
          f"(= N = {N} — every node is a fresh miss)")
    print(f"  why: node i+1 lives in a DIFFERENT line from node i. The line we just")
    print(f"  loaded is useless for the next read. This is POINTER CHASING: each")
    print(f"  hop pays a full RAM round-trip (~100x slower than an L1 hit).\n")

    print("Side-by-side (N=32, 8-line L1, 64B lines):")
    print("| structure   | cache hits | cache misses | misses / element |")
    print("|-------------|------------|--------------|------------------|")
    print(f"| array       | {arr_hits:>10} | {arr_misses:>12} | "
          f"{arr_misses/N:>16.3f} |")
    print(f"| linked list | {ll_hits:>10} | {ll_misses:>12} | "
          f"{ll_misses/N:>16.3f} |")
    print()
    print("So even a 'cheap' O(1) linked-list hop can be ~100x slower than an")
    print("array access once the cache enters the picture. Big-O hides constants;")
    print("the cache IS the constant that dominates in practice.\n")

    # ---- GOLD CHECKS (reproduced verbatim in array_vs_linkedlist.html) ----
    assert arr_misses == expected_arr_misses, "array cold-miss count wrong"
    assert ll_misses == N, "linked-list miss count wrong"
    print("GOLD values (pinned for array_vs_linkedlist.html):")
    print(f"  array       N={N}: hits={arr_hits}, misses={arr_misses}")
    print(f"  linked list N={N}: hits={ll_hits}, misses={ll_misses}")
    print(f"[check] array misses == ceil(N/16) == {expected_arr_misses}: OK")
    print(f"[check] list  misses == N           == {N}: OK")
    return {
        "N": N,
        "arr_addrs": arr_addrs,
        "ll_addrs": ll_addrs,
        "arr_hits": arr_hits,
        "arr_misses": arr_misses,
        "ll_hits": ll_hits,
        "ll_misses": ll_misses,
    }


# ----------------------------------------------------------------------------
# SECTION E: the big-O table (and the cache reality check)
# ----------------------------------------------------------------------------

def section_big_o(gold: dict) -> None:
    banner("SECTION E: the big-O comparison  (+ the cache reality check)")
    print("| operation            | array       | linked list | notes                    |")
    print("|----------------------|-------------|-------------|--------------------------|")
    print("| random access a[i]   | O(1)        | O(N)        | array computes addr      |")
    print("| search (unsorted)    | O(N)        | O(N)        | linear scan either way   |")
    print("| search (sorted)      | O(log N)    | O(N)        | binary search needs O(1) |")
    print("|                      |             |             |   random access -> array |")
    print("| insert at FRONT      | O(N)        | O(1)        | array shifts all N       |")
    print("| insert at TAIL       | O(1) amort* | O(N) or O(1)** | *dynamic array       |")
    print("|                      |             |             |   **if you keep a tail ptr|")
    print("| insert in MIDDLE     | O(N)        | O(1)**      | **given predecessor ptr  |")
    print("| delete at FRONT      | O(N)        | O(1)        | mirror of insert         |")
    print("| delete in MIDDLE     | O(N)        | O(1)**      | **given predecessor ptr  |")
    print("| memory overhead      | 0 extra     | 1 ptr/node  | list pays PTR_SIZE*N     |")
    print("| cache locality       | EXCELLENT   | POOR        | the deciding factor      |")
    print("| prefetch friendly    | YES         | NO          | HW prefetcher loves stride|")
    print()
    print("WHEN TO USE WHICH (engineer's cheat sheet):")
    print("  * Need random access / binary search / indexing?         -> ARRAY.")
    print("  * Need to iterate over everything, in order?             -> ARRAY.")
    print("  * Need O(1) insert/delete at BOTH ends?                  -> ARRAY")
    print("      (a deque / ring buffer beats a linked list here too).")
    print("  * Need O(1) splice of WHOLE sub-chains, unknown sizes,   -> LINKED LIST")
    print("      and you already hold the node pointers?                 (rare).")
    print("  * Implementing an LRU cache / free list / adjacency list? -> LINKED LIST")
    print("      (often combined with a hash map for O(1) node lookup).")
    print()
    print("THE PUNCHLINE: in modern code the linked list almost never wins on")
    print("raw speed, because traversal cost is dominated by cache misses, not by")
    print("instruction count. Big-O calls list insert O(1); the cache calls it")
    print(f"~{gold['ll_misses']}/{gold['arr_misses']}x = "
          f"{gold['ll_misses']/gold['arr_misses']:.0f}x the memory stalls of the "
          "array. Measure, do not assume.")


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("array_vs_linkedlist.py - reference impl. "
          "All numbers below feed ARRAY_VS_LINKEDLIST.md.")
    print(f"INT_SIZE={INT_SIZE}B  PTR_SIZE={PTR_SIZE}B  NODE_SIZE={NODE_SIZE}B  "
          f"LINE_SIZE={LINE_SIZE}B ({LINE_SIZE//INT_SIZE} ints/line)")

    arr, ll = section_memory_layout()
    section_access(arr, ll)
    section_insert_delete()
    gold = section_cache_simulation()
    section_big_o(gold)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
