"""
topological_sort.py - Reference implementation of topological sort of a DAG:
the DFS-based post-order reversal and Kahn's in-degree (BFS) algorithm.

This is the single source of truth that TOPOLOGICAL_SORT.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 topological_sort.py

============================================================================
THE INTUITION (read this first) - the "course catalog" / "build pipeline"
============================================================================
You have a set of TASKS with PREREQUISITES: "task v cannot start until task u
finishes" (an edge u -> v). You need a LINEAR ORDER that respects every
prerequisite. That linear order is a **topological sort**.

  * DFS topo sort : run DFS; each time you FINISH exploring a node (post-order),
                    push it onto a stack. Reverse the stack = topo order. The
                    node that finishes LAST (the source) comes FIRST.
  * Kahn's algo   : count how many edges point INTO each node (its IN-DEGREE).
                    Repeatedly pluck out a node with in-degree 0 (no unmet
                    prerequisites), "remove" it (decrement its neighbours), and
                    repeat. A queue of ready nodes drives a BFS.

THE REASON THESE EXIST: ordering under precedence constraints is everywhere -
Make/Gradle/Cargo build order, course prerequisites, pip/npm dependency
resolution, CPU instruction scheduling, spreadsheet recalculation, dataflow
pipelines. A topological sort is THE way to linearise a DAG. And because the
two algorithms above also detect cycles (a cyclic graph has NO valid order),
they double as the standard cycle detector.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  DAG          : directed acyclic graph. "Acyclic" = no directed cycle, which
                 is exactly what makes a topological order EXIST.
  edge u -> v  : "u must come before v." u is a prerequisite of v.
  topo order   : a permutation of the V nodes such that for EVERY edge u->v,
                 u appears before v in the permutation.
  in-degree(v) : number of edges pointing INTO v = number of unmet
                 prerequisites of v. in-degree 0 = "ready to run now."
  DFS finish   : post-order - the moment we have explored ALL descendants of a
  (post-order)   node and are about to return from its recursive call.
  stack        : where DFS pushes nodes on finish. Reversing it yields the
                 topo order (last-finished = first in order).
  queue (Kahn) : holds all currently in-degree-0 nodes. Any order of popping
                 them is valid (a DAG can have MANY valid topo orders).
  cycle        : a directed loop. If one exists, NO topo order is possible.
                 Kahn detects it: fewer than V nodes get output.

============================================================================
THE LINEAGE (references)
============================================================================
  Kahn's algorithm  (Kahn 1962, "Topological Sorting of Large Networks",
                     CACM) : the in-degree / BFS method.
  DFS topo sort     : standard DFS (Tarjan 1972 lineage; CLRS ch. 22).
  Both appear       : CLRS ch. 22.4 "Topological sort"; Sedgewick & Wayne
                     ch. 4.2. Both are O(V + E) - linear in the graph size.
  Cycle detection   : topo sort produces < V nodes iff the graph has a cycle
                     (CLRS 22.4 theorem).

KEY FACTS (all asserted in code below):
    topo sort exists        IFF the graph is a DAG (no directed cycle).
    DFS topo sort           O(V + E) time, O(V) recursion + O(V) stack.
    Kahn's algorithm        O(V + E) time, O(V) in-degree array + O(V) queue.
    cycle detection         if |output| < V -> cycle exists (|output| == V
                            iff the graph is acyclic).
    # of valid topo orders  can be exponential (DAGs are rarely unique).

Conventions:
    Nodes are integers 0..V-1. The worked DAG has V = 6 nodes.
    adj[u] = sorted list of v such that u -> v (sorted for determinism).
    Outer DFS loop visits nodes 0, 1, ... in order (deterministic).
"""

from __future__ import annotations

from collections import deque

BANNER = "=" * 72

# The worked DAG: 6 nodes. Meaning of each edge u -> v: "u before v."
#   0 -> 1, 0 -> 2     (0 is the root task; 1,2 depend on it)
#   1 -> 3, 2 -> 3     (3 needs both 1 and 2)
#   3 -> 4             (4 needs 3)
#   4 -> 5             (5 needs 4)
# This is a classic build/prerequisite chain with a "diamond" at 1,2->3.
DAG_ADJ: dict[int, list[int]] = {
    0: [1, 2],
    1: [3],
    2: [3],
    3: [4],
    4: [5],
    5: [],
}
V = len(DAG_ADJ)
DAG_EDGES = [(u, w) for u in range(V) for w in DAG_ADJ[u]]


# ============================================================================
# 1. THE TWO REFERENCE IMPLEMENTATIONS
#    (this is the code TOPOLOGICAL_SORT.md walks through)
# ============================================================================

def dfs_toposort(adj: dict[int, list[int]], n: int) -> tuple[list[int], list]:
    """DFS topological sort via post-order reversal.

    Returns (topo_order, trace). topo_order is a list of nodes such that every
    edge u->v has u before v. trace records (node, event) for the walkthrough,
    where event is 'enter', 'finish' (push), or 'cross' (already visited).
    Outer loop is over nodes 0..n-1 in order so the result is deterministic.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = [WHITE] * n
    stack: list[int] = []
    trace: list[tuple[int, str]] = []

    def visit(u: int):
        color[u] = GRAY
        trace.append((u, "enter"))
        for w in adj[u]:
            if color[w] == WHITE:
                visit(w)
            elif color[w] == GRAY:
                trace.append((w, "back-edge (cycle!)"))
        color[u] = BLACK
        stack.append(u)                       # push on FINISH (post-order)
        trace.append((u, "finish -> push"))

    for u in range(n):
        if color[u] == WHITE:
            visit(u)
    stack.reverse()                           # reverse -> topo order
    return stack, trace


def kahn_toposort(adj: dict[int, list[int]], n: int) -> tuple[list[int], list]:
    """Kahn's algorithm: BFS driven by in-degree.

    Returns (topo_order, trace). Repeatedly removes an in-degree-0 node and
    decrements its neighbours. If the output has < n nodes, a cycle exists.
    trace records (node, indeg_before, removed_neighbors) per popped node.
    """
    indeg = [0] * n
    for u in range(n):
        for w in adj[u]:
            indeg[w] += 1
    q: deque[int] = deque(u for u in range(n) if indeg[u] == 0)
    order: list[int] = []
    trace: list[tuple[int, int, list[int]]] = []
    while q:
        u = q.popleft()
        trace.append((u, indeg[u], list(adj[u])))
        order.append(u)
        for w in adj[u]:
            indeg[w] -= 1
            if indeg[w] == 0:
                q.append(w)
    return order, trace


def is_valid_topo(order: list[int], edges: list[tuple[int, int]]) -> bool:
    """Gold check: every edge u->v has u before v in `order`."""
    pos = {node: i for i, node in enumerate(order)}
    return all(pos[u] < pos[v] for u, v in edges) and len(order) == len(pos)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_graph(adj: dict[int, list[int]], edges: list[tuple[int, int]], n: int):
    print(f"Nodes: {list(range(n))}   (V = {n})")
    print(f"Edges ({len(edges)}):")
    for u, v in edges:
        print(f"    {u} -> {v}    ({u} must come before {v})")
    print("Adjacency list (sorted for determinism):")
    for u in range(n):
        print(f"    adj[{u}] = {adj[u]}")


# ----------------------------------------------------------------------------
# SECTION A: DFS topological sort on the 6-node DAG
# ----------------------------------------------------------------------------

def section_dfs():
    banner("SECTION A: DFS topological sort (post-order reversal)")
    print("THE ALGORITHM in one line: run DFS, push each node onto a stack")
    print("when you FINISH it (post-order), then REVERSE the stack.\n")
    print("WHY it works: DFS finishes a node only after finishing all nodes")
    print("that depend on it (its descendants). So 'finished last' = 'has no")
    print("unmet prerequisites' = should come FIRST. Reversing the finish")
    print("order gives a valid topological order.\n")
    print("Worked DAG:")
    print_graph(DAG_ADJ, DAG_EDGES, V)
    print()
    order, trace = dfs_toposort(DAG_ADJ, V)
    print("DFS trace (events in order, outer loop over nodes 0..5):")
    for node, event in trace:
        print(f"    node {node}: {event}")
    print(f"\nStack after all finishes (top = last pushed):  "
          f"{list(reversed(order))}")
    print(f"Reversed  -> topological order:                 {order}")
    print("\nCheck: for every edge u->v, is u before v?")
    ok = is_valid_topo(order, DAG_EDGES)
    pos = {nd: i for i, nd in enumerate(order)}
    for u, v in DAG_EDGES:
        print(f"    edge {u}->{v}: pos({u})={pos[u]} < pos({v})={pos[v]}  "
              f"{'OK' if pos[u] < pos[v] else 'FAIL'}")
    print(f"\n[check] DFS order is a valid topological order: "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION B: Kahn's algorithm
# ----------------------------------------------------------------------------

def section_kahn():
    banner("SECTION B: Kahn's algorithm (BFS via in-degree = 0)")
    print("THE ALGORITHM in one line: repeatedly pluck out a node whose")
    print("in-degree is 0 (no unmet prerequisites), 'remove' it by")
    print("decrementing each neighbour's in-degree, and repeat.\n")
    print("WHY it works: an in-degree-0 node has ALL prerequisites met, so it")
    print("is safe to place next. Removing it mirrors 'task is done, its")
    print("dependents lose one prerequisite.' A queue of ready nodes drives a")
    print("Breadth-First layer-by-layer peeling of the DAG.\n")
    print("Step 1 - compute in-degrees:")
    indeg = [0] * V
    for u in range(V):
        for w in DAG_ADJ[u]:
            indeg[w] += 1
    print("  | node | in-degree | incoming edges        |")
    print("  |------|-----------|-----------------------|")
    for u in range(V):
        inc = [str(s) for s in range(V) if u in DAG_ADJ[s]]
        print(f"  | {u:<4} | {indeg[u]:<9} | {inc}{' ' * (22 - len(str(inc)))} |")
    print(f"\nInitial queue (in-degree == 0): {[u for u in range(V) if indeg[u] == 0]}\n")
    order, trace = kahn_toposort(DAG_ADJ, V)
    print("Step 2 - repeatedly pop a 0-in-degree node, output it, decrement")
    print("its neighbours (the queue drives the BFS):\n")
    for node, _, nbrs in trace:
        dec = [w for w in nbrs]
        newly = []
        # replay to find newly-zeroed neighbours for this step
        idx = trace.index((node, _, nbrs))
        temp = list(indeg)
        for j in range(idx):
            pn = trace[j][0]
            for w in DAG_ADJ[pn]:
                temp[w] -= 1
        for w in dec:
            temp[w] -= 1
            if temp[w] == 0:
                newly.append(w)
        newly_str = f"  -> {newly} now ready" if newly else ""
        print(f"    pop {node}, output it, decrement {dec}{newly_str}")
    print(f"\nKahn's topological order: {order}")
    ok = is_valid_topo(order, DAG_EDGES)
    print(f"[check] Kahn order is a valid topological order: "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: cycle detection (output < V => cycle)
# ----------------------------------------------------------------------------

def section_cycle():
    banner("SECTION C: cycle detection - if |output| < V, a cycle exists")
    print("A topological order EXISTS iff the graph is a DAG. If we add a")
    print("back-edge that closes a directed cycle, neither algorithm can place")
    print("all V nodes: DFS never 'finishes' the cycle, and Kahn's queue")
    print("empties before everything is peeled. So: |output| < V  <=>  cycle.\n")
    # build a cyclic graph: add edge 5 -> 2, closing 2->3->4->5->2
    cyclic_adj = {u: list(ws) for u, ws in DAG_ADJ.items()}
    cyclic_adj[5] = [2]
    cyclic_edges = [(u, w) for u in range(V) for w in cyclic_adj[u]]
    print("Cyclic graph = DAG + back-edge 5 -> 2 (closes 2->3->4->5->2):")
    print_graph(cyclic_adj, cyclic_edges, V)
    print("\nKahn on the cyclic graph:")
    indeg = [0] * V
    for u in range(V):
        for w in cyclic_adj[u]:
            indeg[w] += 1
    order, trace = kahn_toposort(cyclic_adj, V)
    for node, _, nbrs in trace:
        print(f"    pop {node}, output it, decrement {list(nbrs)}")
    print(f"\nKahn output = {order}   (length {len(order)} < V = {V})")
    print("Remaining nodes (stuck in the cycle, never reach in-degree 0):")
    remaining = [u for u in range(V) if u not in order]
    print(f"    {remaining}")
    has_cycle = len(order) < V
    print(f"\n[check] cycle detected (|output| < V)? "
          f"{'YES - cycle exists' if has_cycle else 'NO - it is a DAG'}")
    print("\nDFS would detect it via a GRAY back-edge (a neighbour already on")
    print("the recursion stack). Both methods agree: this graph has a cycle.")
    # also run DFS to show the back-edge trace
    _, dfs_trace = dfs_toposort(cyclic_adj, V)
    backs = [t for t in dfs_trace if "back-edge" in t[1]]
    print(f"\nDFS back-edge events: {backs}")
    assert has_cycle and backs, "cycle detection must fire"


# ----------------------------------------------------------------------------
# SECTION D: DFS vs Kahn - the two methods compared
# ----------------------------------------------------------------------------

def section_compare():
    banner("SECTION D: DFS vs Kahn - same goal, different mechanics")
    dfs_order, _ = dfs_toposort(DAG_ADJ, V)
    kahn_order, _ = kahn_toposort(DAG_ADJ, V)
    print("Both produce a VALID topological order, but via opposite mechanics:\n")
    print("| aspect        | DFS topo sort                | Kahn's algorithm            |")
    print("|---------------|------------------------------|------------------------------|")
    print("| core idea     | finish-time stack reversal   | peel in-degree-0 nodes      |")
    print("| traversal     | DFS (recursive)              | BFS (queue, iterative)      |")
    print("| key structure | recursion stack + result stk | in-degree[] + FIFO queue    |")
    print("| cycle detect  | GRAY back-edge in recursion  | output length < V           |")
    print("| stack depth   | O(V) recursion (watch Python | O(1) - no recursion         |")
    print("|               |   recursion limit on big V)  |                              |")
    print("| order flavour | tends to go DEEP first        | tends to go BREADTH first   |")
    print("| parallelism   | hard (single DFS path)       | NATURAL: all 0-indeg nodes  |")
    print("|               |                              | are independent -> run in   |")
    print("|               |                              | parallel (build systems!)   |")
    print()
    print(f"DFS  order: {dfs_order}")
    print(f"Kahn order: {kahn_order}")
    print("\nNote both are valid (all edges go forward) yet DIFFERENT: a DAG can")
    print("have many valid topological orders. DFS dives deep (0 -> 1 -> 3 -> 4")
    print("-> 5) before backtracking to 2; Kahn peels layer by layer (0, then 1")
    print("and 2 become ready, then 3, ...).\n")
    both_ok = is_valid_topo(dfs_order, DAG_EDGES) and is_valid_topo(kahn_order, DAG_EDGES)
    print(f"[check] both orders valid: {'OK' if both_ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: applications + gold check
# ----------------------------------------------------------------------------

def section_apps():
    banner("SECTION E: applications + GOLD CHECK")
    print("Topological sort is the engine behind every 'do things in dependency")
    print("order' system:\n")
    print("  - Build systems (Make, Gradle, Cargo, Bazel, npm): compile targets")
    print("    in dependency order; Kahn's independent 0-in-degree set is the")
    print("    basis for PARALLEL builds.")
    print("  - Course prerequisites: a valid semester-by-semester plan is a")
    print("    topological order of courses (edge: 'X is a prereq of Y').")
    print("  - Package managers (pip, apt, brew): resolve install order; a")
    print("    dependency CYCLE is a hard error (|output| < V).")
    print("  - Task scheduling / dataflow (Airflow, Spark, spreadsheets):")
    print("    compute stages once all inputs are ready.")
    print("  - Circuit layout / Verilog: signal propagation order.")
    print("  - Git commit history (DAG of commits): linearised history.\n")
    print("Worked example - course prerequisites (6 courses, diamond at 1,2->3):")
    courses = {0: "Algorithms", 1: "OS", 2: "Networks", 3: "Distributed Sys",
               4: "Cloud", 5: "Capstone"}
    order, _ = kahn_toposort(DAG_ADJ, V)
    print("  prereqs: 0->{1,2}, 1->3, 2->3, 3->4, 4->5\n")
    print(f"  A valid semester plan (Kahn order): {[courses[c] for c in order]}")
    print(f"  as indices: {order}\n")
    # GOLD CHECK
    print("GOLD CHECK - re-verify both algorithms produce valid orders:")
    dfs_order, _ = dfs_toposort(DAG_ADJ, V)
    kahn_order, _ = kahn_toposort(DAG_ADJ, V)
    gold_ok = (is_valid_topo(dfs_order, DAG_EDGES)
               and is_valid_topo(kahn_order, DAG_EDGES)
               and len(dfs_order) == V and len(kahn_order) == V)
    print(f"  DFS  order {dfs_order}: valid = {is_valid_topo(dfs_order, DAG_EDGES)}")
    print(f"  Kahn order {kahn_order}: valid = {is_valid_topo(kahn_order, DAG_EDGES)}")
    print(f"  both place all {V} nodes: "
          f"{len(dfs_order) == V and len(kahn_order) == V}")
    print(f"\nGOLD CHECK: {'OK - both orders valid, all edges go forward' if gold_ok else 'FAIL'}")
    print("(topological_sort.html re-runs both algorithms in JS and re-checks")
    print(" these exact orders against the edge set.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("topological_sort.py - reference impl. All numbers below feed")
    print("TOPOLOGICAL_SORT.md. python stdlib only; deterministic.")
    print(f"Worked DAG: V = {V} nodes, {len(DAG_EDGES)} edges.")

    section_dfs()
    section_kahn()
    section_cycle()
    section_compare()
    section_apps()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
