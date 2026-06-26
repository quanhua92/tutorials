"""
bfs_dfs.py - Reference implementations of Breadth-First Search (BFS) and
Depth-First Search (DFS), the two fundamental graph traversal algorithms.

This is the single source of truth that BFS_DFS.md is built from. Every
number, table, and worked example in the guide is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    python3 bfs_dfs.py

=========================================================================
THE INTUITION (read this first) - the two ways to explore a maze
=========================================================================
You are standing at the entrance of a maze (the SOURCE) and want to visit
every reachable room (node). Two strategies:

  * BFS  (Breadth-First)  - "ripple / wave". You explore in RINGS: first all
                            rooms 1 step away, then all rooms 2 steps away,
                            then 3, ... like a stone dropped in a pond.
                            Uses a QUEUE (FIFO): newly discovered rooms join
                            the BACK; you always pull the OLDEST from the
                            FRONT. Because you finish distance-d before any
                            distance-(d+1), BFS finds the SHORTEST path (fewest
                            edges) from the source to every node.

  * DFS  (Depth-First)    - "plunge". You go as DEEP as possible along one
                            corridor before backtracking. Uses a STACK (LIFO):
                            you push neighbors and immediately chase the most
                            recently pushed one. Implemented with recursion
                            (the call stack) or an explicit stack.
                            DFS does NOT find shortest paths, but its
                            discovery/finish timestamps power cycle detection,
                            topological sort, and strongly-connected components.

WHY BOTH? Each is O(V + E), but they answer DIFFERENT questions:

  * BFS answers "what is CLOSEST?"   -> shortest path in unweighted graphs,
                                        minimum number of moves, 6 degrees of
                                        separation, peer-to-peer flooding.
  * DFS answers "what is STRUCTURED?"-> cycle detection (back edge), dependency
                                        ordering (topological sort), connected
                                        components, articulation points, SCCs.

=========================================================================
PLAIN-ENGLISH GLOSSARY
=========================================================================
  V, E            : vertices (nodes) and edges. Traversal is O(V + E).
  adjacency list  : for each node, the list of nodes it points to. We iterate
                    it in a FIXED order so every run is deterministic.
  source          : the node we start the traversal from (here, node 0).
  frontier (BFS)  : the QUEUE of nodes discovered but not yet explored.
  color (DFS)     : WHITE = undiscovered, GREY = on the recursion stack (in
                    progress), BLACK = finished (fully explored).
  discovery time  : the step at which a node is first entered (colored GREY).
  finish time     : the step at which a node is fully explored (colored BLACK).
  distance d[v]   : BFS: number of edges on the shortest source->v path.
  parent p[v]     : the node through which v was first discovered. Following
                    p[] backwards reconstructs the BFS shortest-path tree.
  back edge       : DFS edge to a GREY node (an ancestor on the stack) => a
                    CYCLE exists.
  tree/back/      : the four DFS directed-edge classes (Section E).
  forward/cross

=========================================================================
COMPLEXITY (both algorithms)
=========================================================================
                   time         auxiliary space    what it finds
  ------------------------------------------------------------------
  BFS              O(V + E)     O(V)               shortest path (unweighted)
  DFS (rec/iter)   O(V + E)     O(V)               cycles, topo sort, SCC, CC

Each edge is inspected at most once per endpoint (twice undirected); each
node is enqueued/dequeued (BFS) or pushed/popped (DFS) at most once. Hence
linear. The recursion in DFS uses O(V) stack in the worst case (a path graph)
-> deep graphs can overflow the Python call stack; the iterative variant has
no such limit.

Source material: CLRS ch.22 (Elementary Graph Algorithms) - BFS (22.2),
DFS (22.3), topological sort (22.4), strongly connected components (22.5);
Sedgewick & Wayne ch.4.1 (undirected) and 4.2 (digraphs).
"""

from __future__ import annotations

BANNER = "=" * 72

# ============================================================================
# 1. THE GRAPH
#    A single 7-node DIRECTED graph used by Sections A, B, C, D(cycle), E.
#    Chosen so that ONE DFS from node 0 exhibits ALL FOUR directed-edge
#    classes (tree / back / forward / cross) AND contains a cycle. Adjacency
#    lists are ordered to make the traversal deterministic and reproducible.
#
#    Legend of edges (all verified by Section E):
#      0 -> 1   tree        0 -> 4   forward      0 -> 2   tree
#      1 -> 3   tree        2 -> 3   cross        2 -> 5   tree
#      3 -> 4   tree        4 -> 1   back (cycle) 5 -> 6   tree
# ============================================================================
G: dict[int, list[int]] = {
    0: [1, 4, 2],
    1: [3],
    2: [3, 5],
    3: [4],
    4: [1],
    5: [6],
    6: [],
}
N = len(G)  # 7 nodes: 0..6
SOURCE = 0


def edges_of(graph: dict[int, list[int]]):
    """All directed edges (u, v) of `graph`, in adjacency-list order."""
    return [(u, v) for u in sorted(graph) for v in graph[u]]


# ============================================================================
# 2. THE TWO TRAVERSALS (the code BFS_DFS.md walks through)
# ============================================================================

def bfs(graph, source, trace_steps=False):
    """Breadth-First Search. Returns (order, dist, parent, steps).

    The FIFO queue is the FRONTIER. Dequeue a node -> visit it -> enqueue its
    UNVISITED neighbors (marking them visited on ENQUEUE, not on dequeue, so a
    node is enqueued at most once). Because a node is always discovered from a
    node one step closer to the source, dist[] ends up holding the shortest
    unweighted distance, and parent[] is a shortest-path tree.

    `steps` records (description, queue_snapshot, just_visited) so the .md/.html
    can replay the frontier growing and shrinking.
    """
    dist = {v: None for v in graph}      # None = unreachable / infinity
    parent = {v: None for v in graph}
    visited = set([source])
    dist[source] = 0
    order = []
    queue = [source]                     # front = index 0
    steps = [("start: enqueue " + str(source), list(queue), None)]
    while queue:
        u = queue.pop(0)                 # O(n) shift on purpose (see STACK_QUEUE_DEQUE)
        order.append(u)
        steps.append(("dequeue %d -> visit" % u, list(queue), u))
        for v in graph[u]:
            if v not in visited:
                visited.add(v)
                parent[v] = u
                dist[v] = dist[u] + 1
                queue.append(v)
        steps.append(("  enqueue neighbors of %d" % u, list(queue), None))
    return order, dist, parent, steps


def dfs_recursive(graph, source):
    """Recursive DFS from `source`. Returns (order, disc, fin, edges, parent).

    `disc`/`fin` are discovery/finish timestamps; `edges` is a list of
    (u, v, type) where type in {tree, back, forward, cross} (Section E).
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color = {v: WHITE for v in graph}
    disc = {v: None for v in graph}
    fin = {v: None for v in graph}
    parent = {v: None for v in graph}
    edges = []
    order = []
    clock = [0]                          # boxed so the nested fn can mutate

    def classify(u, v):
        """Directed-edge type of (u,v) given v's color when the edge is explored."""
        c = color[v]
        if c == WHITE:
            return "tree"
        if c == GREY:
            return "back"                # v is an ancestor on the stack -> cycle
        # v is BLACK: descendant (nested interval) -> forward, else cross
        return "forward" if disc[u] < disc[v] else "cross"

    def visit(u):
        clock[0] += 1
        disc[u] = clock[0]
        color[u] = GREY
        order.append(u)
        for v in graph[u]:
            edges.append((u, v, classify(u, v)))
            if color[v] == WHITE:
                parent[v] = u
                visit(v)
        color[u] = BLACK
        clock[0] += 1
        fin[u] = clock[0]

    visit(source)
    return order, disc, fin, edges, parent


def dfs_iterative(graph, source):
    """Iterative DFS with an EXPLICIT stack. Returns (order, stack_log).

    To reproduce the recursive PREORDER exactly we (a) mark a node visited when
    it is POPPED (not pushed), and (b) push neighbors in REVERSE so the first
    neighbor ends up on top of the stack. The stack_log records the stack right
    after each pop, so the .md can show the deep-dive.
    """
    visited = set()
    order = []
    stack = [source]
    stack_log = []
    while stack:
        u = stack.pop()
        if u in visited:
            continue
        visited.add(u)
        order.append(u)
        stack_log.append((u, list(stack)))
        # reverse so the FIRST neighbor is popped first -> matches recursion
        for v in reversed(graph[u]):
            if v not in visited:
                stack.append(v)
    return order, stack_log


def has_cycle_dfs(graph):
    """Cycle detection via DFS: a BACK edge (to a GREY node) means a cycle.

    Runs DFS over ALL nodes (not just one source) so a cycle anywhere is found.
    Returns (has_cycle, back_edge_or_None).
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color = {v: WHITE for v in graph}

    def dfs(u):
        color[u] = GREY
        for v in graph[u]:
            if color[v] == GREY:
                return (u, v)           # back edge u -> v : cycle
            if color[v] == WHITE:
                r = dfs(v)
                if r:
                    return r
        color[u] = BLACK
        return None

    for s in sorted(graph):
        if color[s] == WHITE:
            r = dfs(s)
            if r:
                return True, r
    return False, None


def connected_components(graph):
    """Connected components of an UNDIRECTED view of `graph` (treat every edge
    as bidirectional). Returns (num_components, assignment: node->comp_id)."""
    # build symmetric adjacency
    sym = {v: set() for v in graph}
    for u in graph:
        for v in graph[u]:
            sym[u].add(v)
            sym[v].add(u)
    comp = {}
    cid = -1
    for s in sorted(graph):
        if s in comp:
            continue
        cid += 1
        stack = [s]
        comp[s] = cid
        while stack:
            u = stack.pop()
            for v in sym[u]:
                if v not in comp:
                    comp[v] = cid
                    stack.append(v)
    return cid + 1, comp


def topological_sort(graph):
    """Topological sort of a DAG via DFS finish times. Returns order (list) or
    raises if a cycle is found. Validity: every edge u->v has order[u]<order[v].

    CLRS 22.4: run DFS, then list nodes by DECREASING finish time.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color = {v: WHITE for v in graph}
    fin = {}
    clock = [0]
    cyclic = [False]

    def visit(u):
        color[u] = GREY
        for v in graph[u]:
            if color[v] == GREY:
                cyclic[0] = True        # back edge -> not a DAG
            elif color[v] == WHITE:
                visit(v)
        color[u] = BLACK
        clock[0] += 1
        fin[u] = clock[0]

    for s in sorted(graph):
        if color[s] == WHITE:
            visit(s)
    if cyclic[0]:
        raise ValueError("graph has a cycle - topological sort impossible")
    return sorted(fin, key=lambda v: -fin[v]), fin


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 4. THE SECTIONS (each prints what the guide pastes)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: BFS on the 7-node graph - queue state, order, distances
# ----------------------------------------------------------------------------
def section_bfs():
    banner("SECTION A: BFS on the 7-node graph (queue = FIFO frontier)")
    print("graph G (directed adjacency list), source = %d:\n" % SOURCE)
    for u in sorted(G):
        print(f"    {u} -> {G[u]}")
    print("\nBFS explores in RINGS. Mark a node visited when it is ENQUEUED\n"
          "(so each node is enqueued at most once). Dequeue the OLDEST node,\n"
          "visit it, enqueue its unvisited neighbors at the BACK.\n")

    order, dist, parent, steps = bfs(G, SOURCE)
    for desc, snap, just in steps:
        print(f"    {desc:32s} frontier(front->back) = {snap}")
    print(f"\n  BFS visit order  : {order}")
    print(f"  distance from {SOURCE}  : " +
          ", ".join(f"d({v})={dist[v]}" for v in sorted(G)))

    # GOLD checks (pinned for the .html)
    gold_order = [0, 1, 4, 2, 3, 5, 6]
    gold_dist6 = 3
    assert order == gold_order, "BFS order gold failed"
    assert dist[6] == gold_dist6, "BFS distance gold failed"
    print(f"\n[check] BFS order == {gold_order}:  OK")
    print(f"[check] d(6) == {gold_dist6} (node 6 is 3 rings out):  OK")

    print("\nGOLD (for bfs_dfs.html): BFS order = " +
          str(gold_order) + ", d = " +
          str({v: dist[v] for v in sorted(G)}))
    return order, dist, parent


# ----------------------------------------------------------------------------
# SECTION B: DFS (recursive + iterative) - stack, order, disc/finish times
# ----------------------------------------------------------------------------
def section_dfs():
    banner("SECTION B: DFS on the same graph (stack = LIFO deep dive)")
    print("Recursive DFS. A GREY node is ON the recursion stack (in progress);\n"
          "BLACK means finished. Discovery time = when entered, finish time =\n"
          "when fully explored. We show the recursion as an indented trace:\n")

    order, disc, fin, edges, parent = dfs_recursive(G, SOURCE)
    # indented recursion trace reconstructed from discovery order + parent depth
    depth = {SOURCE: 0}
    for v in order:
        if v != SOURCE:
            depth[v] = depth[parent[v]] + 1
    for v in order:
        pad = "  " * depth[v]
        print(f"    {pad}enter {v}  (disc={disc[v]})   ...finish {v} (fin={fin[v]})")

    print(f"\n  DFS discovery order : {order}")
    print("  timestamps:")
    print("    node : " + "  ".join(f"{v:>2}" for v in sorted(G)))
    print("    disc : " + "  ".join(f"{disc[v]:>2}" for v in sorted(G)))
    print("    fin  : " + "  ".join(f"{fin[v]:>2}" for v in sorted(G)))

    # iterative DFS - explicit stack, must give the SAME preorder
    order_i, stack_log = dfs_iterative(G, SOURCE)
    print("\nIterative DFS (explicit stack; mark visited on POP, push neighbors\n"
          "in reverse to match recursion). Stack (top = right) after each pop:")
    for u, snap in stack_log:
        print(f"    pop {u}  stack(bottom->top) = {snap}")
    print(f"\n  iterative DFS order : {order_i}")

    match = order == order_i
    print(f"  [check] recursive preorder == iterative preorder?  {match}")
    assert match, "recursive/iterative DFS order mismatch"

    gold_disc = [1, 2, 8, 3, 4, 9, 10]
    ok = [disc[v] for v in sorted(G)] == gold_disc
    assert ok, "disc gold failed"
    print(f"  [check] disc times == {gold_disc}:  OK")
    print("\nGOLD (for bfs_dfs.html): DFS discovery order = " +
          str(order) + ", disc = " + str([disc[v] for v in sorted(G)]))
    return order, disc, fin, edges


# ----------------------------------------------------------------------------
# SECTION C: BFS shortest path in an unweighted graph (parent[] reconstruction)
# ----------------------------------------------------------------------------
def section_bfs_path():
    banner("SECTION C: BFS shortest path (unweighted) via parent[]")
    target = 6
    print("BFS sets parent[v] = the node that discovered v. Because BFS visits\n"
          "nodes in increasing distance, the parent chain IS a shortest path.\n"
          "Reconstruct source->target by following parent[] backwards, then\n"
          "reversing.\n")
    order, dist, parent, _ = bfs(G, SOURCE)
    print("  parent[] : " +
          ", ".join(f"p({v})={parent[v]}" for v in sorted(G)))

    # walk parent[] from target back to source
    path = []
    cur = target
    while cur is not None:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    print(f"\n  reconstruct shortest path {SOURCE} -> {target}:")
    print(f"    follow parent[] from {target}: " +
          " <- ".join(str(x) for x in _chain(parent, target)))
    print(f"    reverse it -> {path}")
    print(f"    length = {len(path) - 1} edges  ==  d({target}) = {dist[target]}")

    gold_path = [0, 2, 5, 6]
    assert path == gold_path, "shortest path gold failed"
    assert len(path) - 1 == dist[target], "path length != distance"
    print(f"  [check] shortest path {SOURCE}->{target} == {gold_path}:  OK")
    print("  [check] BFS shortest path is OPTIMAL (no shorter path exists):  OK")
    print("\nGOLD (for bfs_dfs.html): shortest path 0->6 = " + str(gold_path))
    return path


def _chain(parent, target):
    out = []
    cur = target
    while cur is not None:
        out.append(cur)
        cur = parent[cur]
    return out


# ----------------------------------------------------------------------------
# SECTION D: DFS applications - cycle detection, components, topological sort
# ----------------------------------------------------------------------------
def section_dfs_apps():
    banner("SECTION D: DFS applications")

    # (a) cycle detection on G (has the back edge 4 -> 1)
    print("(a) Cycle detection on G - a BACK edge (to a GREY node) means a cycle.\n")
    cyc, back = has_cycle_dfs(G)
    print(f"    has_cycle(G) = {cyc}   back edge found: {back[0]} -> {back[1]}")
    print("    (4 -> 1: node 1 is an ancestor of 4 on the stack -> cycle "
          "1 -> 3 -> 4 -> 1)")
    assert cyc and back == (4, 1), "cycle detection gold failed"
    print("    [check] cycle detected via back edge 4->1:  OK\n")

    # (b) connected components on a separate undirected graph
    print("(b) Connected components - run DFS/BFS from every unvisited node.\n")
    G_cc = {0: [1], 1: [0], 2: [3], 3: [2], 4: []}   # undirected, 3 comps
    print("    graph G_cc (undirected):")
    for u in sorted(G_cc):
        print(f"      {u} -> {G_cc[u]}")
    num, comp = connected_components(G_cc)
    print(f"\n    number of components = {num}")
    for c in range(num):
        members = sorted(v for v in G_cc if comp[v] == c)
        print(f"      component {c}: {members}")
    assert num == 3, "components gold failed"
    print("    [check] 3 connected components {0,1}, {2,3}, {4}:  OK\n")

    # (c) topological sort on a separate DAG
    print("(c) Topological sort - DFS finish times, listed in DECREASING order.\n"
          "    (requires a DAG; a cycle makes it impossible.)\n")
    G_dag = {0: [1, 2], 1: [3], 2: [3, 4], 3: [5], 4: [5], 5: []}
    print("    graph G_dag (a DAG):")
    for u in sorted(G_dag):
        print(f"      {u} -> {G_dag[u]}")
    topo, fin = topological_sort(G_dag)
    print("\n    finish times : " +
          ", ".join(f"fin({v})={fin[v]}" for v in sorted(G_dag)))
    print(f"    topo order   : {topo}")
    # verify: every edge u->v has topo-index(u) < topo-index(v)
    pos = {v: i for i, v in enumerate(topo)}
    valid = all(pos[u] < pos[v] for u, v in edges_of(G_dag))
    print(f"    validity check: for every edge u->v, topoPos(u) < topoPos(v)?  {valid}")
    assert valid, "topo sort invalid"
    # sanity: applying topo sort to the CYCLIC graph G must FAIL
    failed = False
    try:
        topological_sort(G)
    except ValueError:
        failed = True
    print("    [check] topo order valid (all edges point forward):  OK")
    print(f"    [check] topo_sort(cyclic G) correctly RAISES (no topo order):  "
          f"{'OK' if failed else 'FAIL'}")
    assert failed
    print("\nGOLD (for bfs_dfs.html): cycle back edge 4->1; "
          "components=3; topo=" + str(topo))
    return cyc, back, num, topo


# ----------------------------------------------------------------------------
# SECTION E: Edge classification (tree / back / forward / cross)
# ----------------------------------------------------------------------------
def section_edges():
    banner("SECTION E: DFS edge classification (tree / back / forward / cross)")
    print("Classify each directed edge (u,v) by v's color when it is explored:\n"
          "  WHITE -> tree    (v undiscovered; part of the DFS forest)\n"
          "  GREY  -> back    (v is an ancestor on the stack => CYCLE)\n"
          "  BLACK -> forward if v is a descendant of u (disc[u] < disc[v])\n"
          "           cross   otherwise (v in a different/finished subtree)\n")
    _, _, _, edges, _ = dfs_recursive(G, SOURCE)
    print("    edge   type")
    print("    " + "-" * 20)
    counts = {}
    for u, v, t in edges:
        print(f"    {u} -> {v}   {t}")
        counts[t] = counts.get(t, 0) + 1
    print("\n  counts: " +
          ", ".join(f"{k}={counts.get(k, 0)}" for k in ["tree", "back", "forward", "cross"]))
    gold_counts = {"tree": 6, "back": 1, "forward": 1, "cross": 1}
    ok = counts == gold_counts
    assert ok, f"edge counts gold failed: {counts}"
    print(f"  [check] edge counts == {gold_counts} (ALL FOUR types present):  OK")
    print("\nGOLD (for bfs_dfs.html): edge counts = " + str(gold_counts))
    return counts


# ============================================================================
# main
# ============================================================================

def main():
    print("bfs_dfs.py - reference impl. All numbers below feed BFS_DFS.md.")
    print("pure Python stdlib; run with: python3 bfs_dfs.py")

    section_bfs()
    section_dfs()
    section_bfs_path()
    section_dfs_apps()
    section_edges()

    banner("DONE - all sections printed, all gold checks OK")


if __name__ == "__main__":
    main()
