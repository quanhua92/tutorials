"""
tarjan_scc.py - Reference implementation of Tarjan's Strongly Connected
Components algorithm (1972), plus a brute-force Floyd-Warshall cross-check.

This is the single source of truth that TARJAN_SCC.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 tarjan_scc.py

============================================================================
THE INTUITION (read this first) - "mutual reachability cliques"
============================================================================
In a DIRECTED graph, two nodes u and v are **strongly connected** if you can
walk u -> ... -> v AND v -> ... -> u. Strong connectivity is an equivalence
relation, so it partitions the nodes into **Strongly Connected Components**
(SCCs). Inside one SCC every node can reach every other node.

A single DFS from node 0 visits a LOT of nodes that are NOT mutually
reachable (you can go down a chain 0->1->2 but not back). Tarjan's trick is to
find, during that SAME DFS, the exact points where a set of nodes becomes a
closed mutual-reachability clique.

  * discovery time disc[v] : the tick when DFS first visits v (a timestamp).
  * low-link value low[v]  : the SMALLEST discovery time reachable from v by
                             following zero-or-more tree edges and then AT MOST
                             ONE back/cross edge to a node still on the stack.
  * the SCC root test      : v is the ROOT of an SCC  <=>  disc[v] == low[v].
                             At that moment, pop the stack down to v: that is
                             exactly one SCC.

THE REASON THIS EXISTS: SCCs are the fundamental structure of any directed
graph. The CONDENSATION (shrink each SCC to one node) is always a DAG - and a
DAG is exactly what you need for topological sort, dependency resolution, and
cycle analysis. So "find the SCCs" is step zero of almost every directed-graph
algorithm. Tarjan does it in a SINGLE DFS pass and O(V+E) time - optimal.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  SCC            : a maximal set of nodes where every node reaches every other.
  condensation   : the graph obtained by shrinking each SCC to one node. It is
                   always a DAG (the SCCs form a DAG of components).
  disc[v]        : discovery time (timestamp) of v in the DFS forest.
  low[v]         : the lowest discovery time reachable from v via tree edges
                   plus at most one edge to a node ON THE STACK. This is the
                   magic number: if low[v] == disc[v], v roots an SCC.
  stack          : the "current DFS frontier" - nodes whose SCC is not yet
                   finalized. A node leaves the stack ONLY when its SCC is
                   popped (when an SCC root is found).
  on_stack[v]    : boolean: is v currently on the stack?
  back edge      : u -> w where w is an ANCESTOR of u (w on stack, GRAY).
  cross edge     : u -> w where w is in a DIFFERENT subtree but still on the
                   stack (already discovered, not finished -> still on stack).
  self-loop      : an edge v -> v. A single node with a self-loop IS an SCC of
                   size 1 that IS a cycle.
  cycle          : any SCC of size > 1, OR a singleton SCC with a self-loop.

============================================================================
THE LINEAGE (references)
============================================================================
  Tarjan  (Tarjan 1972, "Depth-First Search and Linear Graph Algorithms",
           SIAM J. Comput.) : the single-DFS SCC algorithm using low-link.
           O(V + E) - optimal; still the standard.
  Kosaraju (Sharir 1981 / Kosaraju, 1978) : two-DFS-pass algorithm
           (DFS, reverse the graph, DFS in reverse finish order). Same
           O(V+E), conceptually simpler, but TWO passes + a transposed graph.
  Both    : CLRS ch. 22.5 "Strongly connected components"; Sedgewick & Wayne
           ch. 4.2.

KEY FACTS (all asserted in code below):
    complexity      O(V + E) time, O(V) space - ONE DFS pass (Tarjan).
    SCC root test   v roots an SCC  <=>  disc[v] == low[v].
    stack invariant a node is on the stack from its discovery until its SCC
                    is popped; only on-stack neighbours update low-link.
    condensation    collapsing SCCs yields a DAG (never has a cycle).
    cycle detection any SCC of size > 1, or a size-1 SCC with a self-loop,
                    is a directed cycle.
    # of SCCs       between 1 (whole graph strongly connected) and V
                    (no edges / all singletons).

Conventions:
    Nodes are integers 0..V-1. The worked graph has V = 6 nodes, 3 SCCs.
    adj[u] = sorted list of v such that u -> v (sorted for determinism).
    DFS visits neighbours in sorted order; outer loop over 0..V-1.
"""

from __future__ import annotations

BANNER = "=" * 72

# The worked graph: 6 nodes, 3 SCCs.
#   SCC1 = {0, 1, 2}  : a 3-cycle      0->1->2->0   (size 3 -> a cycle)
#   SCC2 = {3, 4}     : a 2-cycle      3->4->3      (size 2 -> a cycle)
#   SCC3 = {5}        : a singleton    no self-loop (size 1, NO self-loop
#                                                  -> NOT a cycle)
# Bridges between SCCs:  2 -> 3   and   4 -> 5.
# Condensation DAG:  {0,1,2} -> {3,4} -> {5}   (a clean linear chain of SCCs).
GRAPH_ADJ: dict[int, list[int]] = {
    0: [1],
    1: [2],
    2: [0, 3],
    3: [4],
    4: [3, 5],
    5: [],
}
V = len(GRAPH_ADJ)
GRAPH_EDGES = [(u, w) for u in range(V) for w in GRAPH_ADJ[u]]


# ============================================================================
# 1. TARJAN'S SCC  (single DFS, low-link, stack)
#    This is the code TARJAN_SCC.md walks through.
# ============================================================================

def tarjan_scc(adj: dict[int, list[int]], n: int):
    """Tarjan's SCC in one DFS pass.

    Returns (sccs, disc, low, trace) where:
      sccs  : list of SCCs (each a sorted list of node ids), in the order
              they were finalized (roots popped). Tarjan emits SCCs in
              REVERSE topological order of the condensation.
      disc  : discovery time per node.
      low   : low-link value per node.
      trace : list of (event, payload) for the walkthrough.
    """
    disc = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack: list[int] = []
    sccs: list[list[int]] = []
    timer = [0]
    trace: list[tuple[str, object]] = []

    def push_trace(ev: str, payload):
        trace.append((ev, payload))

    def strongconnect(u: int):
        disc[u] = low[u] = timer[0]
        timer[0] += 1
        stack.append(u)
        on_stack[u] = True
        push_trace("enter", (u, disc[u], low[u], list(stack)))

        for w in adj[u]:
            if disc[w] == -1:
                push_trace("tree-edge", (u, w))
                strongconnect(w)
                low[u] = min(low[u], low[w])
                push_trace("low-update", (u, low[u], f"min with low[{w}]={low[w]}"))
            elif on_stack[w]:
                # back or cross edge to a node still on the stack:
                # we can reach disc[w], so low[u] may drop.
                low[u] = min(low[u], disc[w])
                push_trace("back/cross-edge", (u, w, disc[w], low[u]))

        # SCC root test
        if low[u] == disc[u]:
            comp: list[int] = []
            while True:
                w = stack.pop()
                on_stack[w] = False
                comp.append(w)
                if w == u:
                    break
            comp.sort()
            sccs.append(comp)
            push_trace("scc-root", (u, disc[u], comp, list(stack)))

    for u in range(n):
        if disc[u] == -1:
            strongconnect(u)
    return sccs, disc, low, trace


# ============================================================================
# 2. BRUTE-FORCE SCC via Floyd-Warshall reachability (the gold check)
# ============================================================================

def floyd_scc(adj: dict[int, list[int]], n: int) -> list[list[int]]:
    """Brute-force SCC via transitive closure (Floyd-Warshall).

    O(V^3). i, j are strongly connected iff reach[i][j] AND reach[j][i].
    Used ONLY as an independent gold check against Tarjan.
    """
    reach = [[False] * n for _ in range(n)]
    for i in range(n):
        reach[i][i] = True
        for w in adj[i]:
            reach[i][w] = True
    for k in range(n):
        for i in range(n):
            if not reach[i][k]:
                continue
            row_k = reach[k]
            row_i = reach[i]
            for j in range(n):
                if row_k[j]:
                    row_i[j] = True
    # group by mutual reachability
    comp_id = [-1] * n
    sccs: list[list[int]] = []
    for i in range(n):
        if comp_id[i] != -1:
            continue
        comp = [j for j in range(n) if reach[i][j] and reach[j][i]]
        cid = len(sccs)
        for j in comp:
            comp_id[j] = cid
        sccs.append(sorted(comp))
    # sort for a stable comparison (by min node)
    sccs.sort(key=lambda c: c[0])
    return sccs


def kosaraju_scc(adj: dict[int, list[int]], n: int) -> list[list[int]]:
    """Kosaraju's two-DFS-pass SCC algorithm (for the Section D comparison).

    Pass 1: DFS on G, push nodes onto a stack by finish time.
    Pass 2: DFS on the TRANSPOSE in DECREASING finish-time order; each DFS
    tree is one SCC. O(V + E), two passes + one transposed graph.
    """
    visited = [False] * n
    finish_stack: list[int] = []

    def dfs1(u: int):
        visited[u] = True
        for w in adj[u]:
            if not visited[w]:
                dfs1(w)
        finish_stack.append(u)

    for u in range(n):
        if not visited[u]:
            dfs1(u)

    radj: dict[int, list[int]] = {i: [] for i in range(n)}
    for u in range(n):
        for w in adj[u]:
            radj[w].append(u)
    for u in range(n):
        radj[u].sort()

    visited2 = [False] * n
    sccs: list[list[int]] = []

    def dfs2(u: int, comp: list[int]):
        visited2[u] = True
        comp.append(u)
        for w in radj[u]:
            if not visited2[w]:
                dfs2(w, comp)

    for u in reversed(finish_stack):
        if not visited2[u]:
            comp: list[int] = []
            dfs2(u, comp)
            sccs.append(sorted(comp))
    sccs.sort(key=lambda c: c[0])
    return sccs


# ============================================================================
# 3. PRETTY PRINTERS
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
        print(f"    {u} -> {v}")
    print("Adjacency list (sorted for determinism):")
    for u in range(n):
        print(f"    adj[{u}] = {adj[u]}")


# ----------------------------------------------------------------------------
# SECTION A: run Tarjan, show disc + low
# ----------------------------------------------------------------------------

def section_run():
    banner("SECTION A: run Tarjan on the worked graph (3 SCCs)")
    print("THE ALGORITHM in one breath: DFS with a timer, a low-link array,")
    print("and a stack of 'open' nodes. When disc[v] == low[v], v is the ROOT")
    print("of an SCC - pop the stack down to v and that is one SCC.\n")
    print("Worked graph (3 SCCs, condensation is a chain {0,1,2}->{3,4}->{5}):")
    print_graph(GRAPH_ADJ, GRAPH_EDGES, V)
    print()
    sccs, disc, low, trace = tarjan_scc(GRAPH_ADJ, V)
    print("DFS trace (events in order; outer loop visits 0..5):")
    for ev, payload in trace:
        if ev == "enter":
            u, d, lv, stk = payload
            print(f"    enter {u}: disc[{u}]={d}, low[{u}]={lv}, stack={stk}")
        elif ev == "tree-edge":
            u, w = payload
            print(f"    tree-edge {u}->{w}: recurse into {w}")
        elif ev == "low-update":
            u, lv, why = payload
            print(f"    back in {u}: low[{u}]={lv}  ({why})")
        elif ev == "back/cross-edge":
            u, w, dw, lu = payload
            print(f"    back/cross {u}->{w}: disc[{w}]={dw} on stack, "
                  f"low[{u}]={lu}")
        elif ev == "scc-root":
            u, d, comp, stk = payload
            print(f"    *** SCC root {u}: disc[{u}]={d} == low[{u}]={low[u]} "
                  f"-> pop SCC {comp}")
    print(f"\nDiscovery times disc: {disc}")
    print(f"Low-link values low:  {low}")
    print("SCCs found (in finalize order, = reverse condensation topo order):")
    for i, c in enumerate(sccs):
        root = c[-1] if len(c) == 1 else [x for x in c if disc[x] == low[x]][0]
        print(f"    SCC #{i + 1}: {c}   (root = {root}, "
              f"disc[{root}]={disc[root]} == low[{root}]={low[root]})")
    print(f"\nThat is {len(sccs)} SCCs. The finalize order {sccs} is the")
    print("REVERSE topological order of the condensation (deepest SCC first).")


# ----------------------------------------------------------------------------
# SECTION B: the SCC-root pop (disc == low)
# ----------------------------------------------------------------------------

def section_root_test():
    banner("SECTION B: the SCC root test - when disc[v] == low[v], pop")
    sccs, disc, low, _ = tarjan_scc(GRAPH_ADJ, V)
    print("A node v is the ROOT of an SCC exactly when its discovery time")
    print("equals its low-link value:  disc[v] == low[v].\n")
    print("WHY: low[v] is the earliest discovery time reachable from v's")
    print("subtree via tree edges + one stack edge. If low[v] > disc[v], some")
    print("node reachable from v can reach an EARLIER node still on the stack")
    print("- so v is NOT the top of a closed mutual-reachability clique; the")
    print("SCC root is higher up. Only when low[v] == disc[v] has the clique")
    print("'closed' at v, and everything from v to the top of the stack is one")
    print("SCC.\n")
    print("  | node | disc | low | disc==low? | role               |")
    print("  |------|------|-----|------------|--------------------|")
    for u in range(V):
        eq = disc[u] == low[u]
        role = "SCC ROOT -> pop" if eq else "merged into a later SCC"
        print(f"  | {u:<4} | {disc[u]:<4} | {low[u]:<3} | "
              f"{'YES' if eq else 'no ':<10} | {role:<18} |")
    print()
    for i, c in enumerate(sccs):
        root = [x for x in c if disc[x] == low[x]][0]
        members = ", ".join(f"{m}(disc={disc[m]},low={low[m]})" for m in c)
        print(f"  SCC #{i + 1} {c}: root = {root} (disc={disc[root]}, "
              f"low={low[root]}). Members: {members}")
    print("\nNote node 5: disc=5 == low=5 but it is a SINGLETON with no")
    print("self-loop, so it is an SCC of size 1 that is NOT a cycle (Section C).")


# ----------------------------------------------------------------------------
# SECTION C: cycle detection via SCCs
# ----------------------------------------------------------------------------

def section_cycles():
    banner("SECTION C: cycle detection - any SCC of size > 1 (or self-loop)")
    sccs, disc, low, _ = tarjan_scc(GRAPH_ADJ, V)
    print("A directed CYCLE exists iff some SCC has size > 1, OR a size-1 SCC")
    print("has a self-loop. Tarjan finds all cycles implicitly: each non-trivial")
    print("SCC IS a cycle (its nodes are mutually reachable).\n")
    self_loops = {u for u in range(V) if u in GRAPH_ADJ[u]}
    print(f"Self-loops in the graph: {sorted(self_loops) or 'none'}\n")
    print("  | SCC          | size | self-loop? | is a cycle? |")
    print("  |--------------|------|------------|-------------|")
    cycles: list[list[int]] = []
    for c in sccs:
        sl = any(m in self_loops for m in c)
        is_cycle = len(c) > 1 or sl
        if is_cycle:
            cycles.append(c)
        print(f"  | {str(c):<12} | {len(c):<4} | "
              f"{'yes' if sl else 'no':<10} | "
              f"{'YES' if is_cycle else 'no':<11} |")
    print(f"\nCycles found: {cycles}")
    print("  SCC {0,1,2} (size 3) and SCC {3,4} (size 2) are cycles;")
    print("  SCC {5} is a singleton with NO self-loop, so it is NOT a cycle.")
    print("\nThis is why SCCs are the gold-standard cycle detector: it finds")
    print("ALL cycles (including interlocking ones) and groups the nodes that")
    print("participate in them, in O(V+E) - one DFS pass.")


# ----------------------------------------------------------------------------
# SECTION D: Tarjan vs Kosaraju (single DFS vs two DFSs)
# ----------------------------------------------------------------------------

def section_compare():
    banner("SECTION D: Tarjan vs Kosaraju - one DFS vs two")
    tar = tarjan_scc(GRAPH_ADJ, V)[0]
    tar.sort(key=lambda c: c[0])
    kos = kosaraju_scc(GRAPH_ADJ, V)
    print("Both are O(V + E). The difference is the NUMBER of DFS passes and")
    print("whether you must transpose the graph:\n")
    print("| aspect          | Tarjan                       | Kosaraju                   |")
    print("|-----------------|------------------------------|-----------------------------|")
    print("| DFS passes      | ONE                          | TWO                        |")
    print("| graph transpose | not needed                   | YES (build reverse graph)  |")
    print("| key structure   | low-link[] + one stack       | finish-time stack + rev DFS|")
    print("| root test       | disc[v] == low[v]            | each rev-DFS tree = 1 SCC  |")
    print("| SCC emit order  | reverse condensation topo    | condensation topo order    |")
    print("| conceptually   | subtle (low-link invariant)   | simpler (two plain DFSs)   |")
    print("| constants       | slightly fewer passes         | two full traversals        |")
    print("| year            | Tarjan 1972                   | Kosaraju 1978 / Sharir 1981|")
    print()
    print(f"Tarjan SCCs:   {tar}")
    print(f"Kosaraju SCCs: {kos}")
    match = tar == kos
    print(f"\n[check] Tarjan == Kosaraju on this graph: {'OK' if match else 'FAIL'}")
    # also compare against brute force
    brute = floyd_scc(GRAPH_ADJ, V)
    print(f"Brute-force (Floyd): {brute}")
    all_match = tar == kos == brute
    print(f"[check] all three agree: {'OK' if all_match else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: applications + GOLD CHECK
# ----------------------------------------------------------------------------

def section_apps():
    banner("SECTION E: applications + GOLD CHECK")
    print("SCCs answer 'which nodes form a mutual-dependency clique' - the")
    print("backbone of dependency analysis:\n")
    print("  - Deadlock detection: a cycle in a wait-for graph = deadlock.")
    print("    SCCs of size > 1 are exactly the deadlocked process sets.")
    print("  - Package / module dependency cycles: an SCC in the import graph")
    print("    is a circular dependency - usually a build error. Python, Rust")
    print("    (cargo), and JS bundlers all run an SCC check.")
    print("  - Compiler optimization: find loops in a control-flow graph")
    print("    (natural loops are SCCs of the CFG) for register allocation.")
    print("  - 2-SAT: a 2-SAT formula is satisfiable iff no variable and its")
    print("    negation share an SCC in the implication graph (Aspvall 1979).")
    print("  - Web / social graph: find 'communities' (SCCs of mutual links)")
    print("    and rank pages (the condensation DAG feeds PageRank).")
    print("  - Model checking: detect liveness/reachability cycles.\n")
    print("Worked example - module imports (3 packages, circular deps inside 2):")
    modules = {0: "auth", 1: "session", 2: "crypto", 3: "db", 4: "orm", 5: "util"}
    sccs, _, _, _ = tarjan_scc(GRAPH_ADJ, V)
    for i, c in enumerate(sccs):
        names = [modules[m] for m in c]
        cycle = len(c) > 1
        tag = "  <- CIRCULAR DEP (cycle)" if cycle else "  <- clean (no cycle)"
        print(f"  SCC #{i + 1} {c} = {names}{tag}")
    print("\nThe condensation DAG {auth,session,crypto} -> {db,orm} -> {util}")
    print("tells you a SAFE build/initialization order: util first, then")
    print("{db,orm}, then {auth,session,crypto}. (That is just a topo sort of")
    print("the SCCs - linking these two concepts.)\n")
    # GOLD CHECK against brute force
    print("GOLD CHECK - Tarjan vs brute-force Floyd-Warshall reachability:")
    tar = sorted((sorted(c) for c in sccs), key=lambda c: c[0])
    brute = floyd_scc(GRAPH_ADJ, V)
    gold_ok = tar == brute
    print(f"  Tarjan SCCs:          {tar}")
    print(f"  Brute-force SCCs:     {brute}")
    print(f"  match: {'OK' if gold_ok else 'FAIL'}")
    print(f"\nGOLD CHECK: {'OK - Tarjan SCCs match brute-force reachability' if gold_ok else 'FAIL'}")
    print("(tarjan_scc.html re-runs Tarjan in JS and re-checks these exact")
    print(" SCCs against the Floyd-Warshall brute force.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("tarjan_scc.py - reference impl. All numbers below feed TARJAN_SCC.md.")
    print("python stdlib only; deterministic.")
    print(f"Worked graph: V = {V} nodes, {len(GRAPH_EDGES)} edges, 3 SCCs.")

    section_run()
    section_root_test()
    section_cycles()
    section_compare()
    section_apps()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
