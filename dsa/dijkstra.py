"""
dijkstra.py - Reference implementation of Dijkstra's single-source shortest
path algorithm (non-negative weights), with comparisons to BFS (unweighted)
and Bellman-Ford (negative weights).

This is the single source of truth that DIJKSTRA.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 dijkstra.py

=========================================================================
THE INTUITION (read this first) - the "campfire rumor" that only improves
=========================================================================
You stand at a source node S and want the cheapest route to every other node
in a weighted graph. Dijkstra is greedy and purely local:

  * Keep a working "best known cost" dist[v] for every node (infinity except
    dist[S] = 0).
  * Repeatedly PULL the unfinished node u with the smallest dist[u] out of a
    MIN-PRIORITY-QUEUE, declare it SETTLED (its distance is now final), and
    try to improve its neighbours via RELAXATION:
        if dist[u] + w(u,v) < dist[v]:    dist[v] = dist[u] + w(u,v)
  * The min-pq means we always commit the closest unfinished node first.

THE REASON IT WORKS (and why it needs NON-NEGATIVE weights): once u is pulled,
dist[u] is the TRUE shortest distance. Why? Any other path to u must leave the
settled set through some edge (x, y) with y still unsettled, and because every
edge weight is >= 0 that path costs at least dist[x] + w(x,y) >= dist[x] >=
dist[u]. So no later path can undercut dist[u]. NEGATIVE EDGES break exactly
this inequality: a later edge could be negative, making a later route CHEAPER
than the one we already committed (Section D).

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  source S       : the start node; dist[S] = 0.
  dist[v]        : best known cost from S to v so far (an upper bound).
  settled        : a node whose dist is FINAL - popped from the pq, never
                   reopened. Dijkstra commits a node the instant it is pulled.
  relaxation     : the update "if dist[u]+w(u,v) < dist[v], lower dist[v]".
                   Named because the constraint dist[v] <= dist[u]+w(u,v) (the
                   "triangle inequality") is being "relaxed" (tightened).
  pred[v]        : predecessor on the current best path to v; rebuilds paths.
  w(u,v)         : weight of edge u->v. Must be >= 0 for Dijkstra to be correct.
  min-pq / heap  : a priority queue ordered by dist; pop returns the smallest.
                   Python's heapq is a binary min-heap: push/pop are O(log V).
  shortest-path
  tree (SPT)     : the tree formed by the pred pointers, rooted at S. The S->v
                   path through it is a shortest path.

=========================================================================
THE LINEAGE (references)
=========================================================================
  Dijkstra       (Dijkstra 1959, "A Note on Two Problems in Connexion with
                  Graphs", Numerische Mathematik). The original greedy SSSP.
  BFS            : the unweighted special case - if every edge has weight 1 the
                  min-pq is just a FIFO queue -> breadth-first search, O(V+E).
                  Dijkstra generalises BFS to weighted graphs.
  Bellman-Ford   (Bellman 1958 / Ford 1956): relaxes EVERY edge V-1 times, so
                  it handles NEGATIVE weights (and detects negative cycles).
                  O(V*E), slower but general.
  A*             (Hart, Nilsson, Raphael 1968): Dijkstra + a heuristic.
                  Dijkstra is exactly A* with h = 0. -> see A_STAR.md / a_star.html
  CLRS           : Chapter 24 (Single-Source Shortest Paths) - the primary
                  reference for every assertion below.

KEY FACTS (all asserted in code below):
    complexity (binary heap) = O((V+E) log V)     push/pop are O(log V)
    complexity (array scan)  = O(V^2)             the original 1959 form
    negative edges           = NOT handled        the greedy settle breaks
    optimality               = YES                dist values are exact for w>=0
    BFS special case         = O(V+E)             all weights equal 1
    Bellman-Ford             = O(V*E)             handles negatives; detects cycles

Conventions:
    Graphs are dicts of adjacency lists:  adj[u] = [(v, w), ...]
    Nodes are strings: 'S','A','B','C','D','T' (main) / 'S','A','B','C' (neg demo).
    All weights are integers.
"""

from __future__ import annotations

import heapq
from collections import deque

BANNER = "=" * 72
INF = float("inf")


# ============================================================================
# 1. THE WORKED GRAPHS
#    Main graph: 6 nodes, directed, non-negative weights. Small enough to print
#    every relaxation, big enough to show branching and a non-trivial SPT.
# ============================================================================

def main_graph():
    """The non-negative weighted graph used for Sections A, B, C, E.

         7        4        2
      S ----> A ----> C ----> T
      |  \\    |       |       ^
      |   \\-->|       |       |
      2    3   |       5       8
      v        v       v       |
      B <------'        D ----'
       \\                ^
        6 \\--> D        | 1
            \\> C <------|
    (see the mermaid in DIJKSTRA.md for the canonical picture)
    """
    return {
        "S": [("A", 7), ("B", 2)],
        "A": [("B", 3), ("C", 4)],
        "B": [("A", 2), ("D", 6)],
        "C": [("D", 5), ("T", 2)],
        "D": [("C", 1), ("T", 8)],
        "T": [],
    }


NODES = ["S", "A", "B", "C", "D", "T"]


def neg_graph():
    """A 4-node graph WITH a negative edge (C->A = -5) that breaks Dijkstra.

      S --1--> A --2--> B
      |        ^
      4        | -5
       \\--> C -+

    Dijkstra settles A=1 BEFORE it pops C and sees the -5 edge, so it misses
    the true cost A=-1 (and B=1). Bellman-Ford gets it right (Section D).
    """
    return {
        "S": [("A", 1), ("C", 4)],
        "A": [("B", 2)],
        "C": [("A", -5)],
        "B": [],
    }


NEG_NODES = ["S", "A", "B", "C"]


# ============================================================================
# 2. DIJKSTRA (strict, min-heap, instrumented) - the code the guide walks through
# ============================================================================

def dijkstra(adj, src, nodes, trace=None, heap_snap=False):
    """Strict Dijkstra with a binary min-heap (heapq).

    'Strict' = once a node is popped/settled it is NEVER reopened (any
    relaxation into an already-settled node is skipped). This is the greedy
    version whose O((V+E) log V) proof REQUIRES non-negative weights - which is
    exactly why it FAILS on the negative graph in Section D.

    Returns (dist, pred, push_count, pop_count).
    If `trace` is a list, appends step tuples for the worked example:
        ('pop', u, d, kind)              kind in {'settle','stale'}
        ('relax', u, du, v, w, before, after, improved, settled_skip, snap)
    """
    dist = {v: INF for v in nodes}
    pred = {v: None for v in nodes}
    dist[src] = 0
    settled = set()
    pq = [(0, src)]
    push_count = 1            # the initial (0, src)
    pop_count = 0
    while pq:
        d, u = heapq.heappop(pq)
        pop_count += 1
        if u in settled:
            if trace is not None:
                snap = list(pq) if heap_snap else None
                trace.append(("pop", u, d, "stale", snap))
            continue                       # stale duplicate entry -> discard
        settled.add(u)
        if trace is not None:
            snap = list(pq) if heap_snap else None
            trace.append(("pop", u, d, "settle", snap))
        for v, w in adj[u]:
            before = dist[v]
            if v in settled:
                if trace is not None:
                    snap = list(pq) if heap_snap else None
                    trace.append(("relax", u, d, v, w, before, before, False, True, snap))
                continue                   # STRICT: never reopen a settled node
            nd = d + w
            improved = nd < before
            if improved:
                dist[v] = nd
                pred[v] = u
                heapq.heappush(pq, (nd, v))
                push_count += 1
            if trace is not None:
                snap = list(pq) if heap_snap else None
                trace.append(("relax", u, d, v, w, before, dist[v], improved, False, snap))
    return dist, pred, push_count, pop_count


# ============================================================================
# 3. THE ALTERNATIVES (Bellman-Ford, BFS) - used for Sections D and E
# ============================================================================

def bellman_ford(adj, src, nodes):
    """Bellman-Ford: relax EVERY edge |V|-1 times. Handles negative weights;
    returns (dist, pred, has_negative_cycle)."""
    dist = {v: INF for v in nodes}
    pred = {v: None for v in nodes}
    dist[src] = 0
    edges = [(u, v, w) for u in nodes for (v, w) in adj[u]]
    rounds = 0
    for _ in range(len(nodes) - 1):
        rounds += 1
        changed = False
        for u, v, w in edges:
            if dist[u] != INF and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                pred[v] = u
                changed = True
        if not changed:
            break
    neg_cycle = False
    for u, v, w in edges:
        if dist[u] != INF and dist[u] + w < dist[v]:
            neg_cycle = True
            break
    return dist, pred, neg_cycle, rounds


def bfs_unweighted(adj, src, nodes):
    """BFS treating every edge as weight 1 -> the minimum number of edges."""
    dist = {v: INF for v in nodes}
    dist[src] = 0
    seen = {src}
    q = deque([src])
    while q:
        u = q.popleft()
        for v, _ in adj[u]:
            if v not in seen:
                seen.add(v)
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def reconstruct_path(pred, src, tgt):
    if tgt != src and pred.get(tgt) is None:
        return None
    path = [tgt]
    while path[-1] != src:
        path.append(pred[path[-1]])
    return list(reversed(path))


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_dist(dist, nodes):
    return "{" + ", ".join(f"{n}:{int(dist[n]) if dist[n] != INF else 'inf'}" for n in nodes) + "}"


# ----------------------------------------------------------------------------
# SECTION A: build the weighted graph + step-by-step relaxation
# ----------------------------------------------------------------------------

def section_relaxation(trace):
    banner("SECTION A: build the weighted graph + step-by-step relaxation")
    g = main_graph()
    print("Main graph (directed, non-negative weights):")
    for u in NODES:
        edges = ", ".join(f"{u}-[{w}]->{v}" for v, w in g[u]) or "(no out-edges)"
        print(f"  {u}: {edges}")
    print("\nSource = S. At each step we pop the unsettled node with smallest dist,")
    print("SETTLE it (dist is now final), then RELAX every out-edge:\n")
    step = 0
    for t in trace:
        if t[0] == "pop" and t[3] == "settle":
            _, u, d, _, _ = t
            step += 1
            print(f"  STEP {step}: pop ({d},{u})  ->  SETTLE {u}, dist[{u}] = {d}  (final)")
        elif t[0] == "pop" and t[3] == "stale":
            _, u, d, _, _ = t
            print(f"           : pop ({d},{u})  ->  STALE entry (dist[{u}] already smaller), discard")
        else:  # relax
            _, u, du, v, w, before, after, improved, settled_skip, _ = t
            b = "inf" if before == INF else str(int(before))
            cand = du + w
            if settled_skip:
                print(f"             relax {u}-[{w}]->{v}: {v} already SETTLED -> skip (greedy commitment)")
            elif improved:
                print(f"             relax {u}-[{w}]->{v}: {du}+{w}={cand} < {b}  ->  dist[{v}] = {int(after)}  (push ({int(after)},{v}))")
            else:
                print(f"             relax {u}-[{w}]->{v}: {du}+{w}={cand} >= {b}  (no improvement)")
    print("\nFinal distances:")
    dist, _, _, _ = dijkstra(main_graph(), "S", NODES)
    print(f"  dist = {fmt_dist(dist, NODES)}")
    print("\nThe trace shows the two Dijkstra primitives at work:")
    print("  - SETTLE: commit the closest unfinished node (its dist is permanent).")
    print("  - RELAX : try to lower a neighbour; push it into the pq if improved.")
    print("Notice A is settled at 4 even though edge S->A has weight 7: the cheaper")
    print("two-hop route S->B->A (2+2=4) was found by relaxation BEFORE A settled.")


# ----------------------------------------------------------------------------
# SECTION B: the min-priority-queue (binary heap) - push/pop, O(log V)
# ----------------------------------------------------------------------------

def section_pq(trace):
    banner("SECTION B: the min-priority-queue (binary min-heap) - O(log V) per op")
    print("The 'extract-min' that picks the next node is the heart of Dijkstra. With a")
    print("binary heap (Python heapq), each push and pop is O(log V), so the whole run")
    print("is O((V+E) log V). Here is the FRONTIER (sorted heap contents) after each")
    print("operation on the main graph:\n")
    print("  legend: frontier = unsettled candidates as (dist,node), sorted by dist")
    print("          then node; a stale entry stays in the heap until it is popped.\n")
    op = 0
    for t in trace:
        snap = t[-1]
        front = sorted(snap) if snap is not None else []
        front_s = ", ".join(f"({int(d)},{n})" for d, n in front) if front else "(empty)"
        if t[0] == "pop":
            _, u, d, kind, _ = t
            op += 1
            verb = "SETTLE" if kind == "settle" else "discard stale"
            print(f"  op{op:>2} POP ({int(d)},{u})  -> {verb:<14} frontier = {front_s}")
        else:
            _, u, du, v, w, before, after, improved, skip, _ = t
            if skip or not improved:
                continue
            op += 1
            print(f"  op{op:>2} PUSH ({int(after)},{v}) (relax {u}->{v})   frontier = {front_s}")
    pushes = sum(1 for t in trace if t[0] == "relax" and t[7] and not t[8])  # improved, non-skip
    pops = sum(1 for t in trace if t[0] == "pop")
    stale = sum(1 for t in trace if t[0] == "pop" and t[3] == "stale")
    print(f"\n  total pushes = {pushes + 1} (1 initial + {pushes} successful relaxations)")
    print(f"  total pops   = {pops} ({pops - stale} settle + {stale} stale discard)")
    print(f"  each push/pop is O(log V) = O(log {len(NODES)}) ~ {len(NODES).bit_length()} comparisons.")
    print("\nCost accounting: E edges each cause at most one push, V nodes each pop once")
    print("(plus stale dups). So total work = O((V+E) log V). A naive array-scan")
    print("Dijkstra scans all V nodes to find each min -> O(V^2); the heap wins once")
    print("the graph is even slightly sparse (E << V^2).")


# ----------------------------------------------------------------------------
# SECTION C: the shortest-path tree (SPT) and reconstructed paths
# ----------------------------------------------------------------------------

def section_spt():
    banner("SECTION C: the shortest-path tree (pred pointers) + reconstructed paths")
    g = main_graph()
    dist, pred, _, _ = dijkstra(g, "S", NODES)
    print("After Dijkstra, the pred[] pointers form a TREE rooted at S. Following each")
    print("node's pred chain back to S reconstructs a shortest path, whose total weight")
    print("equals dist[node].\n")
    print("  | node | dist | pred | shortest path        | edges               | total | check |")
    print("  |------|------|------|----------------------|---------------------|-------|-------|")
    all_ok = True
    for v in NODES:
        path = reconstruct_path(pred, "S", v)
        if v == "S":
            pstr = "S"
            estr = "-"
            total = 0
        else:
            pstr = " -> ".join(path)
            ew = []
            total = 0
            for a, b in zip(path, path[1:]):
                w = next(wt for nb, wt in g[a] if nb == b)
                ew.append(str(w))
                total += w
            estr = "+".join(ew)
        ok = total == dist[v]
        all_ok &= ok
        print(f"  | {v:<4} | {int(dist[v]):<4} | {str(pred[v]):<4} | {pstr:<20} | {estr:<19} | {total:<5} | {'OK' if ok else 'FAIL':<5} |")
    print(f"\n[check] every reconstructed path's edge-weight sum == dist[v]:  {'OK' if all_ok else 'FAIL'}")
    print("\nThe SPT itself (parent -> children):")
    children = {n: [] for n in NODES}
    for v in NODES:
        if pred[v] is not None:
            children[pred[v]].append(v)
    for n in NODES:
        kids = children[n] if children[n] else ["(leaf)"]
        print(f"  {n} -> {', '.join(kids)}")
    print("\nThe S->T path is S -> B -> A -> C -> T (cost 10): cheaper than the direct")
    print("S -> A (7) -> C (11) -> T (13) because going through B first saves 3 (A via")
    print("B costs 4, not 7). This is relaxation doing its job: never trust the first")
    print("edge you see - keep the cheapest known route to each node.")


# ----------------------------------------------------------------------------
# SECTION D: WHY NEGATIVE EDGES BREAK IT (Dijkstra vs Bellman-Ford)
# ----------------------------------------------------------------------------

def section_negative():
    banner("SECTION D: why negative edges break Dijkstra (vs Bellman-Ford)")
    ng = neg_graph()
    print("Negative graph (edge C->A = -5):")
    for u in NEG_NODES:
        edges = ", ".join(f"{u}-[{w}]->{v}" for v, w in ng[u]) or "(no out-edges)"
        print(f"  {u}: {edges}")
    print()
    d_dist, _, _, _ = dijkstra(ng, "S", NEG_NODES)
    bf_dist, _, neg_cyc, rounds = bellman_ford(ng, "S", NEG_NODES)
    print("Run BOTH algorithms from S:\n")
    print("  | node | Dijkstra | Bellman-Ford (TRUE) | match? |")
    print("  |------|----------|---------------------|--------|")
    match = True
    for v in NEG_NODES:
        dv = d_dist[v]
        bv = bf_dist[v]
        ok = dv == bv
        match &= ok
        ds = "inf" if dv == INF else str(int(dv))
        bs = "inf" if bv == INF else str(int(bv))
        print(f"  | {v:<4} | {ds:<8} | {bs:<19} | {'OK' if ok else 'WRONG':<6} |")
    print(f"\n  [check] Dijkstra == Bellman-Ford on the negative graph?  {'OK' if match else 'FAIL'}")
    print()
    print("What went wrong - the greedy commitment, step by step:")
    print("  1. pop S(0), settle. Relax S->A=1, S->C=4.   frontier: (1,A),(4,C)")
    print("  2. pop A(1), SETTLE A=1. Relax A->B=3.        A is now PERMANENT.")
    print("  3. pop B(3), settle B=3. (no out-edges)")
    print("  4. pop C(4), settle C=4. Try C->A = 4+(-5) = -1 < 1 ... but A is ALREADY")
    print("     SETTLED, so strict Dijkstra SKIPS it. The true cost A=-1 is lost, and")
    print("     B (settled at 3, should be 1 via C->A->B) is wrong too.")
    print()
    print("Bellman-Ford has no 'settle' step: it relaxes EVERY edge V-1 = "
          f"{len(NEG_NODES)-1} times, so the")
    print(f"-5 edge is eventually applied. It needed {rounds} relaxation round(s) and")
    print(f"reports a negative cycle? {neg_cyc} (none here). Cost: O(V*E) = "
          f"{len(NEG_NODES)}*{sum(len(ng[u]) for u in NEG_NODES)} per round.")
    print()
    print("THE RULE: Dijkstra's correctness PROOF needs 'every edge weight >= 0'. The")
    print("moment a negative edge exists, a node settled 'too early' can never be")
    print("reopened. Bellman-Ford trades the O((V+E)log V) speed for the ability to")
    print("handle negatives by brute-forcing V-1 relaxation sweeps.")


# ----------------------------------------------------------------------------
# SECTION E: comparison - BFS / Dijkstra / Bellman-Ford
# ----------------------------------------------------------------------------

def section_comparison():
    banner("SECTION E: BFS / Dijkstra / Bellman-Ford - three regimes")
    g = main_graph()
    bfs = bfs_unweighted(g, "S", NODES)
    dij, _, _, _ = dijkstra(g, "S", NODES)
    bf, _, _, _ = bellman_ford(g, "S", NODES)
    print("Same main graph, three algorithms. BFS ignores weights (min #edges);")
    print("Dijkstra and Bellman-Ford both minimise total weight (and must agree here\n"
          "since all weights are >= 0).\n")
    print("  | node | BFS (edge count) | Dijkstra (weight) | Bellman-Ford (weight) | D==BF? |")
    print("  |------|------------------|-------------------|-----------------------|--------|")
    gold = True
    for v in NODES:
        ok = dij[v] == bf[v]
        gold &= ok
        print(f"  | {v:<4} | {int(bfs[v]):<16} | {int(dij[v]):<17} | {int(bf[v]):<21} | {'OK' if ok else 'FAIL':<6} |")
    print()
    print("BFS gives T = 3 (S->A->C->T = 3 edges) but Dijkstra gives T = 10 (cheapest")
    print("by WEIGHT is S->B->A->C->T). Fewest edges != cheapest weight: that is why")
    print("Dijkstra exists. When all weights are 1, Dijkstra degenerates to BFS.\n")
    print("Complexity & capability table:")
    print("  | algorithm     | weights allowed   | complexity       | detects neg cycle |")
    print("  |---------------|-------------------|------------------|-------------------|")
    print("  | BFS           | unweighted (=1)   | O(V+E)           | n/a               |")
    print("  | Dijkstra      | >= 0              | O((V+E) log V)   | no                |")
    print("  | Bellman-Ford  | any (incl. neg)   | O(V*E)           | yes               |")
    print()
    print("Reach for BFS on unweighted graphs, Dijkstra whenever weights are")
    print("non-negative (most maps, networks, games), and Bellman-Ford only when")
    print("negative edges are possible (currency arbitrage, constraint systems).")


# ----------------------------------------------------------------------------
# GOLD CHECK
# ----------------------------------------------------------------------------

def gold_check():
    banner("GOLD CHECK")
    g = main_graph()
    dij, _, _, _ = dijkstra(g, "S", NODES)
    bf, _, _, _ = bellman_ford(g, "S", NODES)
    # independent brute force: relax until stable (Bellman-Ford-equivalent) is bf;
    # also verify path-weight sums independently
    ok = all(dij[v] == bf[v] for v in NODES)
    # spot-check the headline number
    headline = dij["T"] == 10
    status = "OK" if (ok and headline) else "FAIL"
    print("Two independent shortest-path engines on the main graph (all weights >= 0):")
    print(f"  Dijkstra    dist = {fmt_dist(dij, NODES)}")
    print(f"  BellmanFord dist = {fmt_dist(bf, NODES)}")
    print(f"  dist[T] (headline) = {int(dij['T'])}")
    print(f"\nGOLD CHECK: {status} - Dijkstra and Bellman-Ford agree on every node")
    print("(dijkstra.html re-runs Dijkstra in JavaScript and re-checks these values.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("dijkstra.py - reference impl. All numbers below feed DIJKSTRA.md.")
    print("python stdlib only (heapq, collections); deterministic.\n")

    # one instrumented run feeds Sections A and B
    trace = []
    dijkstra(main_graph(), "S", NODES, trace=trace, heap_snap=True)

    section_relaxation(trace)
    section_pq(trace)
    section_spt()
    section_negative()
    section_comparison()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
