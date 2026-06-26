"""
max_flow.py - Reference implementation of Maximum Flow via the Ford-Fulkerson
method with the Edmonds-Karp BFS heuristic (CLRS 3rd ed., ch. 26).

This is the SINGLE SOURCE OF TRUTH for MAX_FLOW.md. Every number, augmenting
path, residual capacity, and cut in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

    python3 max_flow.py > max_flow_output.txt

Pure Python stdlib only. Deterministic: BFS explores neighbours in a FIXED
insertion order, so the augmenting paths are byte-identical every run, and the
.html can replicate them exactly.

============================================================================
THE INTUITION (read this first) - the plumbing of a saturated pipe network
============================================================================
Imagine a network of PIPES carrying water from a spring (the source S) to a
drain (the sink T). Each pipe has a maximum throughput (its CAPACITY). Water
is incompressible, so at every junction the amount flowing IN must equal the
amount flowing OUT (FLOW CONSERVATION). The question: what is the MOST water
you can push from S to T? That maximum is the MAX FLOW.

  * capacity c(u,v)   : the pipe's width. Flow through a pipe cannot exceed it.
  * flow    f(u,v)    : how much water currently moves through (u,v).
                         0 <= f(u,v) <= c(u,v)   (capacity constraint)
  * skew symmetry      : f(u,v) = -f(v,u).  Flow one way is "anti-flow" the
                         other. This is bookkeeping, not physics: it makes the
                         conservation law uniform.
  * conservation       : for every node except S and T, sum of in-flow = sum
                         of out-flow.

The Ford-Fulkerson METHOD (not algorithm - the "method" needs a path rule):
  1. Start with zero flow everywhere.
  2. Find an AUGMENTING PATH - any path from S to T along which you could still
     push MORE water. "Could push more" is captured by the RESIDUAL GRAPH.
  3. AUGMENT along that path: push as much as the tightest pipe on the path
     allows (the BOTTLENECK). Update residual capacities.
  4. Repeat until NO augmenting path exists. The total pushed is the max flow.

THE REASON THE RESIDUAL GRAPH EXISTS: pushing flow down pipe (u,v) "uses up"
capacity on (u,v) but it also OPENS UP the reverse pipe (v,u) - because if we
later decide we sent too much that way, we can cancel some of it by "sending
flow back". The residual graph records, for every edge, how much MORE flow you
could add in that direction:
     residual(u,v) = c(u,v) - f(u,v)     (forward: room left)
     residual(v,u) = f(u,v)              (reverse: flow we could undo)
An augmenting path is just any S->T path in this residual graph where every
edge has residual > 0. The brilliance: by allowing reverse residuals, the
method can UNDO bad earlier choices and converge to the true optimum.

EDMONDS-KARP = Ford-Fulkerson where each augmenting path is chosen by BFS
(shortest path in number of edges). This single change turns "could run forever
on irrational capacities" into a clean O(V * E^2) guarantee.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  source S / sink T   the two special nodes. S produces flow, T consumes it.
                       No flow is conserved at S (all leaves) or T (all enters).
  capacity c(u,v)     the hard upper bound on flow through edge (u,v).
  flow f(u,v)         current flow on edge (u,v).  0 <= f <= c.
  residual r(u,v)     how much MORE flow can be pushed on (u,v):
                       forward  r(u,v) = c(u,v) - f(u,v)
                       reverse  r(v,u) = f(u,v)            (undo room)
  residual graph      the network drawn using only residual capacities. The
                       algorithm searches HERE, never on the raw capacities.
  augmenting path     an S->T path in the residual graph (every edge r > 0).
  bottleneck          the SMALLEST residual on an augmenting path = how much
                       we can push this round.
  augment             push the bottleneck along the path: subtract from forward
                       residuals, add to reverse residuals.
  cut                 a partition of nodes into (A, B) with S in A and T in B.
  capacity of a cut   sum of capacities of edges going A -> B (forward only).
  min cut             the cut with the SMALLEST capacity.
  net flow of a cut   sum of flows A->B minus flows B->A. Equals max flow for
                       ANY S-T cut (flow value lemma).

============================================================================
THE LINEAGE (papers)
============================================================================
  Ford-Fulkerson (1956) : the method. "Maximal flow through a network."
                          Canadian J. Math. Pick ANY augmenting path each
                          round. Pseudopolynomial; can be slow / non-terminating
                          on irrational capacities.
  Edmonds-Karp (1972)   : pick the SHORTEST augmenting path (BFS). Turns the
                          method into O(V*E^2). Published as "Theoretical
                          Improvements in Algorithmic Efficiency for Network
                          Flow Problems", JACM 19(2).
  Dinic (1970)          : level graphs + blocking flows, O(V^2*E). Faster in
                          practice; the basis of modern max-flow solvers.
  Push-Relabel (1988)   : Goldberg & Tarjan. O(V^2 * sqrt(E)) with highest-label.
                          Uses local "push" of excess rather than full paths.

============================================================================
KEY FACTS (all verified against CLRS ch. 26 + asserted in code below)
============================================================================
    capacity constraint : 0 <= f(u,v) <= c(u,v)                  (every edge)
    skew symmetry       : f(u,v) = -f(v,u)
    conservation        : sum_in(v) = sum_out(v)   for v not in {S, T}
    residual edge       : r(u,v) = c(u,v) - f(u,v)  (forward)
                          r(v,u) = f(u,v)            (reverse, undo room)
    max-flow min-cut    : |f*| = capacity(min cut)   (the central theorem)
    value of a flow     : |f| = sum f(S,v) = sum f(v,T)   (gold check)
    Edmonds-Karp        : O(V * E^2); at most O(V*E) augmentations, each a BFS.
    termination         : guaranteed once no S->T path in residual graph.
    the residual graph  : the min cut is the set of nodes STILL REACHABLE from
                          S in the residual graph at termination; the cut edges
                          are exactly the saturated forward edges crossing it.

Conventions for the worked example (CLRS Figure 26.1 / 26.6 network):
    nodes : s, v1, v2, v3, v4, t        (6 nodes)
    S = s, T = t
    edges (directed, with capacity):
        s->v1:16  s->v2:13  v1->v3:12  v2->v1:4   v2->v4:14
        v3->v2:9  v3->t:20  v4->v3:7   v4->t:4
    answer: max flow = 23 ; min cut = {s,v1,v2,v4} | {v3,t}, capacity 23.
"""

from __future__ import annotations

from collections import deque

BANNER = "=" * 72

# The canonical CLRS flow network (Introduction to Algorithms, Fig 26.1/26.6).
NODES = ["s", "v1", "v2", "v3", "v4", "t"]
SOURCE = "s"
SINK = "t"
EDGES: list[tuple[str, str, int]] = [
    ("s", "v1", 16),
    ("s", "v2", 13),
    ("v1", "v3", 12),
    ("v2", "v1", 4),
    ("v2", "v4", 14),
    ("v3", "v2", 9),
    ("v3", "t", 20),
    ("v4", "v3", 7),
    ("v4", "t", 4),
]


# ============================================================================
# 0. THE FLOW NETWORK + EDMONDS-KARP SOLVER
# ============================================================================

class FlowNetwork:
    """A directed flow network with integer capacities.

    The residual graph is stored as `res[u][v]` = remaining capacity on the
    edge u->v. The reverse entry `res[v][u]` always exists (starts at 0) so a
    reverse residual edge is ready the moment any forward flow is pushed - that
    is the whole mechanism by which the method can "undo" earlier flow.

    Original capacities are kept separately in `cap[(u,v)]` so we can recover
    the actual flow on each edge at the end: f(u,v) = cap(u,v) - res[u][v].

    Neighbours are iterated in INSERTION ORDER (dict preserves it), which makes
    the BFS path choice fully deterministic.
    """

    def __init__(self, nodes: list[str]):
        self.nodes = list(nodes)
        self.res: dict[str, dict[str, int]] = {n: {} for n in nodes}
        self.cap: dict[tuple[str, str], int] = {}

    def add_edge(self, u: str, v: str, c: int) -> None:
        """Add a directed edge u->v with capacity c (and its zero reverse)."""
        assert u in self.res and v in self.res, "unknown node"
        self.res[u][v] = self.res[u].get(v, 0) + c
        self.res[v].setdefault(u, 0)          # reverse residual slot (undo room)
        self.cap[(u, v)] = c

    # ---- Edmonds-Karp: BFS for the SHORTEST augmenting path -------------
    def bfs_path(self) -> tuple[list[str], int] | None:
        """BFS from SOURCE to SINK over edges with residual > 0.

        Returns (path, bottleneck) where path is [SOURCE, ..., SINK] and
        bottleneck is the min residual along it. Returns None if no path.

        BFS guarantees the SHORTEST augmenting path (fewest edges) - that is
        the Edmonds-Karp heuristic and what gives the O(V*E^2) bound. Plain
        Ford-Fulkerson could pick any path; the BFS choice is the whole
        difference between the two.
        """
        parent: dict[str, str | None] = {SOURCE: None}
        q: deque[str] = deque([SOURCE])
        while q:
            u = q.popleft()
            for v, r in self.res[u].items():      # insertion order = deterministic
                if v not in parent and r > 0:
                    parent[v] = u
                    if v == SINK:
                        return self._reconstruct(parent)
                    q.append(v)
        return None

    def _reconstruct(self, parent: dict[str, str | None]) -> tuple[list[str], int]:
        """Walk parent pointers SINK->SOURCE, build the path, find bottleneck."""
        path: list[str] = []
        cur: str | None = SINK
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        path.reverse()
        bottleneck = min(self.res[path[i]][path[i + 1]]
                         for i in range(len(path) - 1))
        return path, bottleneck

    # ---- augment: push flow along a path, update residual graph ----------
    def augment(self, path: list[str], bottleneck: int) -> None:
        """Push `bottleneck` units along `path`: subtract forward, add reverse.

        This is the residual update that makes Ford-Fulkerson work:
            r(u,v) -= b   (less room forward)
            r(v,u) += b   (more room to undo later)
        Net effect on the actual flow: f(u,v) goes up by b on forward edges.
        """
        for i in range(len(path) - 1):
            u, v = path[i], path[i + 1]
            self.res[u][v] -= bottleneck
            self.res[v][u] += bottleneck

    # ---- recover actual flow on every original edge ---------------------
    def flow_on(self, u: str, v: str) -> int:
        """Actual flow f(u,v) = original capacity - remaining forward residual."""
        return self.cap[(u, v)] - self.res[u][v]


def solve_edmonds_karp(net: FlowNetwork):
    """Run Edmonds-Karp to completion, recording every augmenting path.

    Yields (iteration, path, bottleneck, running_total) for each augmentation
    so the caller can print a step-by-step trace. Returns the final total.
    """
    total = 0
    it = 0
    while True:
        found = net.bfs_path()
        if found is None:
            break
        it += 1
        path, bottleneck = found
        net.augment(path, bottleneck)
        total += bottleneck
        yield it, path, bottleneck, total
    return total


# ============================================================================
# 1. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_network(net: FlowNetwork) -> None:
    """Print each edge as 'u -> v : cap  (flow/cap)'."""
    print("| edge      | capacity | flow | residual forward |")
    print("|-----------|----------|------|------------------|")
    for (u, v), c in net.cap.items():
        f = net.flow_on(u, v)
        print(f"| {u:>3}->{v:<3} | {c:>8} | {f:>4} | {c - f:>16} |")


def residual_edges(net: FlowNetwork) -> list[tuple[str, str, int]]:
    """All residual edges with r > 0, sorted for stable display."""
    out = []
    for u in net.nodes:
        for v, r in net.res[u].items():
            if r > 0:
                out.append((u, v, r))
    return sorted(out)


# ============================================================================
# 2. THE WORKED EXAMPLE
#    CLRS Fig 26.1/26.6 network: 6 nodes, 9 edges. Max flow = 23.
# ============================================================================

def build_network() -> FlowNetwork:
    net = FlowNetwork(NODES)
    for u, v, c in EDGES:
        net.add_edge(u, v, c)
    return net


# ----------------------------------------------------------------------------
# SECTION A: the flow network - source, sink, capacities. Initial state.
# ----------------------------------------------------------------------------

def section_network() -> FlowNetwork:
    banner("SECTION A: the flow network (source s, sink t, capacities)")
    net = build_network()
    print("Nodes: " + ", ".join(NODES))
    print(f"Source S = {SOURCE}   Sink T = {SINK}\n")
    print("Each directed edge has a CAPACITY (the pipe width). Flow starts at 0:")
    print()
    print_network(net)
    print()
    print("Constraints every valid flow must satisfy:")
    print("  capacity   : 0 <= f(u,v) <= c(u,v)        (never overflow a pipe)")
    print("  skew sym.  : f(u,v) = -f(v,u)             (flow one way = anti-flow)")
    print("  conserve   : sum_in(v) = sum_out(v)       for v != S, T")
    print()
    print("Goal: find the largest total flow S -> T. That value is the MAX FLOW.")
    print("Capacity leaving S (an upper bound on any flow):")
    cap_out_s = sum(c for (u, _, c) in EDGES if u == SOURCE)
    cap_in_t = sum(c for (_, v, c) in EDGES if v == SINK)
    print(f"  sum c(S,*) = {cap_out_s}   (S->v1:16 + S->v2:13)")
    print(f"  sum c(*,T) = {cap_in_t}   (v3->T:20 + v4->T:4)")
    print(f"  loose upper bound = min({cap_out_s},{cap_in_t}) = {min(cap_out_s, cap_in_t)};"
          f" the real max flow is smaller (it is 23, found below).")
    return net


# ----------------------------------------------------------------------------
# SECTION B + C: Edmonds-Karp - find augmenting path (BFS), augment, repeat.
#                Iteration-by-iteration trace with residual updates.
# ----------------------------------------------------------------------------

def section_edmonds_karp() -> tuple[FlowNetwork, list[tuple[int, list[str], int, int]]]:
    banner("SECTION B+C: Edmonds-Karp - BFS augmenting path, augment, repeat")
    net = build_network()
    print("Ford-Fulkerson METHOD: repeatedly find an S->T path in the RESIDUAL")
    print("graph and push the bottleneck. EDMONDS-KARP chooses the path by BFS")
    print("(shortest in edges) - that single rule gives O(V*E^2).\n")
    print("Residual update per augmenting step:")
    print("   forward  r(u,v) -= b    (less room forward)")
    print("   reverse  r(v,u) += b    (more room to UNDO later)\n")
    history: list[tuple[int, list[str], int, int]] = []
    for it, path, b, total in solve_edmonds_karp(net):
        history.append((it, path, b, total))
        print(f"--- iteration {it} ---")
        print(f"  BFS shortest augmenting path: {' -> '.join(path)}")
        print(f"  bottleneck = min residual on path = {b}")
        print(f"  push {b}; running total |f| = {total}")
        print("  residual graph after this push (edges with r > 0):")
        for u, v, r in residual_edges(net):
            tag = ""
            if (u, v) in net.cap:
                tag = f"   [forward edge, flow={net.flow_on(u, v)}/{net.cap[(u, v)]}]"
            else:
                tag = "   [reverse residual = undo room]"
            print(f"     {u:>3} -> {v:<3} : r={r}{tag}")
        print()
    print(f"After {len(history)} augmentations, BFS finds no S->T path with")
    print(f"residual > 0. Algorithm TERMINATES. Max flow = {history[-1][3]}.")
    return net, history


# ----------------------------------------------------------------------------
# SECTION D: final flow - show every edge's flow + conservation check.
# ----------------------------------------------------------------------------

def section_final_flow(net: FlowNetwork, history) -> None:
    banner("SECTION D: final flow per edge + conservation (gold-check)")
    total = history[-1][3]
    print(f"Max flow |f*| = {total}\n")
    print_network(net)
    print()
    # conservation at every internal node
    print("Flow conservation (sum_in == sum_out) at every internal node:")
    print("| node | flow IN                 | flow OUT               | balanced? |")
    print("|------|-------------------------|------------------------|-----------|")
    all_balanced = True
    for n in NODES:
        if n in (SOURCE, SINK):
            continue
        in_flows = [(u, net.flow_on(u, n)) for (u, v) in net.cap if v == n]
        out_flows = [(v, net.flow_on(n, v)) for (u, v) in net.cap if u == n]
        sin = sum(f for _, f in in_flows)
        sout = sum(f for _, f in out_flows)
        bal = sin == sout
        all_balanced = all_balanced and bal
        in_str = " + ".join(f"{u}:{f}" for u, f in in_flows) + f" = {sin}"
        out_str = " + ".join(f"{v}:{f}" for v, f in out_flows) + f" = {sout}"
        print(f"| {n:<4} | {in_str:<23} | {out_str:<22} | {bal!s:<9} |")
    print()
    flow_out_s = sum(net.flow_on(SOURCE, v) for (u, v) in net.cap if u == SOURCE)
    flow_in_t = sum(net.flow_on(u, SINK) for (u, v) in net.cap if v == SINK)
    print(f"flow leaving S = {flow_out_s}")
    print(f"flow entering T = {flow_in_t}")
    print(f"GOLD: total flow = sum leaving source = sum entering sink = {total}")
    ok = (flow_out_s == total and flow_in_t == total and all_balanced)
    print(f"[check] value(f) consistent everywhere? {ok}")
    assert ok, "flow value / conservation failed!"


# ----------------------------------------------------------------------------
# SECTION E: max-flow = min-cut. Show the cut (reachable set from S).
# ----------------------------------------------------------------------------

def section_min_cut(net: FlowNetwork, history) -> tuple[set[str], set[str], list[tuple[str, str, int]]]:
    banner("SECTION E: max-flow = min-cut (the max-flow min-cut theorem)")
    total = history[-1][3]
    print("At termination, BFS from S in the RESIDUAL graph reaches exactly the")
    print("S-side of the minimum cut. Edges crossing A->B are SATURATED (flow =")
    print("capacity); their capacity sum equals the max flow. This is the")
    print("max-flow min-cut THEOREM (Ford-Fulkerson 1956): |f*| = capacity(min cut).\n")
    # reachable set
    reach = {SOURCE}
    q = deque([SOURCE])
    while q:
        u = q.popleft()
        for v, r in net.res[u].items():
            if v not in reach and r > 0:
                reach.add(v)
                q.append(v)
    a_side = sorted(reach)
    b_side = sorted(set(NODES) - reach)
    print(f"S-side (reachable from {SOURCE} in residual graph): {a_side}")
    print(f"T-side (the rest):                                   {b_side}")
    print()
    cut_edges = []
    print("Cut edges (forward edges from A to B) - all SATURATED:")
    print("| edge      | capacity | flow | (flow == capacity) |")
    print("|-----------|----------|------|--------------------|")
    for (u, v), c in net.cap.items():
        if u in reach and v not in reach:
            f = net.flow_on(u, v)
            cut_edges.append((u, v, c))
            sat = f == c
            print(f"| {u:>3}->{v:<3} | {c:>8} | {f:>4} | {sat!s:<18} |")
    cut_cap = sum(c for _, _, c in cut_edges)
    print()
    print(f"capacity(min cut) = {' + '.join(str(c) for _, _, c in cut_edges)} = {cut_cap}")
    print(f"max flow |f*|      = {total}")
    print(f"GOLD: |f*| == capacity(min cut)?  {total == cut_cap}  "
          f"({total} == {cut_cap})")
    ok = (total == cut_cap)
    print(f"[check] max-flow min-cut theorem holds? {'OK' if ok else 'FAIL'}")
    assert ok, "max-flow != min-cut!"
    print()
    print("Why every cut edge is saturated: if an A->B edge had residual > 0,")
    print("BFS would have crossed it and put its head in A - contradiction. So")
    print("the cut is 'tight': forward edges full, and no backward flow leaks")
    print("back into A (else those B nodes would be reachable too).")
    return reach, set(NODES) - reach, cut_edges


# ----------------------------------------------------------------------------
# SECTION F: applications of max-flow.
# ----------------------------------------------------------------------------

def section_applications() -> None:
    banner("SECTION F: applications "
           "(bipartite matching, project selection, image segmentation)")
    print("Max-flow is a Swiss-army knife: many problems are SOLVED by building")
    print("a flow network and running Edmonds-Karp / Dinic on it.\n")
    print("| problem               | how it maps to max-flow                          |")
    print("|-----------------------|--------------------------------------------------|")
    print("| bipartite matching    | add super-source to all L-nodes (cap 1), all     |")
    print("|                       | R-nodes to super-sink (cap 1); max flow = max    |")
    print("|                       | matching. (Konig: = min vertex cover.)           |")
    print("| max bipartite matching| same; integer capacities -> integral flow.       |")
    print("| disjoint paths        | unit capacities; max flow = max edge-disjoint   |")
    print("|                       | S->T paths (Menger's theorem).                   |")
    print("| project selection     | open-pit mining / selection: max closure in a    |")
    print("|                       | dependency DAG -> min cut. (Picard 1976.)        |")
    print("| image segmentation    | foreground/background: pixels to S (fg) or T     |")
    print("|                       | (bg); capacities from pixel similarity; min cut  |")
    print("|                       | = optimal boundary. (Boykov-Kolmogorov 2004.)   |")
    print("| baseball elimination  | can team X still win? build a flow of remaining  |")
    print("|                       | games; if max flow saturates all game nodes, X   |")
    print("|                       | is still alive. (Schwartz 1966.)                 |")
    print("| circulation / demands | add edge T->S with cap = infinity; lower bounds |")
    print("|                       | via node demands. Feasibility via a super-source.|")
    print()
    print("The unifying trick: model 'choices' as cuts. The min cut picks the")
    print("cheapest consistent partition; the max flow proves it is optimal via")
    print("the max-flow min-cut theorem.")


# ============================================================================
# 3. GOLD CHECK: value(f) = sum leaving source = sum entering sink = min cut
# ============================================================================

def gold_check() -> None:
    banner("GOLD CHECK: |f| = sum out(S) = sum in(T) = capacity(min cut)")
    net = build_network()
    history = list(solve_edmonds_karp(net))
    total = history[-1][3]
    # 1. value consistency
    flow_out_s = sum(net.flow_on(SOURCE, v) for (u, v) in net.cap if u == SOURCE)
    flow_in_t = sum(net.flow_on(u, SINK) for (u, v) in net.cap if v == SINK)
    # 2. augmenting paths (pinned for the .html to replicate)
    paths = [(p, b) for _, p, b, _ in history]
    # 3. min cut
    reach = {SOURCE}
    q = deque([SOURCE])
    while q:
        u = q.popleft()
        for v, r in net.res[u].items():
            if v not in reach and r > 0:
                reach.add(v)
                q.append(v)
    a_side = sorted(reach)
    cut_cap = sum(c for (u, v), c in net.cap.items()
                  if u in reach and v not in reach)
    # 4. per-edge final flow
    flows = {f"{u}->{v}": net.flow_on(u, v) for (u, v) in net.cap}
    ok = (total == flow_out_s == flow_in_t == cut_cap == 23
          and len(paths) == 3)
    print("augmenting paths (Edmonds-Karp order):")
    for p, b in paths:
        print(f"  {' -> '.join(p)}   bottleneck {b}")
    print(f"\nnum augmentations       = {len(paths)}")
    print(f"|f| (running total)     = {total}")
    print(f"sum flow leaving source = {flow_out_s}")
    print(f"sum flow entering sink  = {flow_in_t}")
    print(f"min cut S-side          = {a_side}")
    print(f"capacity(min cut)       = {cut_cap}")
    print(f"final flow per edge     = {flows}")
    print("\nGOLD (pinned for max_flow.html):")
    print(f"  max_flow=23, num_paths=3, min_cut_A_side={a_side}, cut_capacity={cut_cap}")
    print(f"[check] |f| = sum_out(S) = sum_in(T) = cap(min cut) = 23? "
          f"{'OK' if ok else 'FAIL'}")
    assert ok, "gold check failed!"


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("max_flow.py - reference impl. All numbers below feed MAX_FLOW.md.")
    print("Ford-Fulkerson method + Edmonds-Karp BFS heuristic (CLRS ch. 26).")
    print("Network: CLRS Fig 26.1/26.6 - 6 nodes, 9 edges.")

    section_network()
    net, history = section_edmonds_karp()
    section_final_flow(net, history)
    section_min_cut(net, history)
    section_applications()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
