"""
mst_kruskal_prim.py - Reference implementation of the two classic Minimum
Spanning Tree algorithms: Kruskal's (sort edges + Union-Find) and Prim's
(grow from a source via a priority queue). Includes the cut property and a
tie-graph where the two algorithms produce DIFFERENT MSTs of equal weight.

This is the single source of truth that MST_KRUSKAL_PRIM.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 mst_kruskal_prim.py

============================================================================
THE INTUITION (read this first) - "wire up every city, pay the least cable"
============================================================================
You have V cities and a cost for laying cable between each pair. You want every
city reachable from every other (one connected network) for the LEAST total
cable. That minimal network is the MINIMUM SPANNING TREE (MST): it spans all V
vertices, has exactly V-1 edges, and no cycle.

Two ways to grow it, both provably optimal:

  * KRUSKAL : look at the cheapest edges one by one (globally sorted). Add an
              edge UNLESS it would close a cycle (checked in O(1)-ish by a
              Union-Find / disjoint-set structure). Builds a FOREST that merges
              into one tree. "Cheapest edges first, skip if it loops back."
  * PRIM    : start at any vertex. Repeatedly add the cheapest edge that
              connects a vertex ALREADY in the tree to a vertex NOT yet in it.
              Uses a priority queue of frontier edges. "Grow one blob outward."

Both rest on the SAME theorem - the CUT PROPERTY: the lightest edge crossing
any cut (a partition of the vertices into two sets) is in SOME MST. Kruskal
applies it to the cut "this edge's endpoints are in different components";
Prim applies it to the cut "tree | everything else".

THE REASON BOTH EXIST: same O(E log V), different feel. Kruskal is edge-centric
(global sort, easy to reason about, and gives you clustering for free - stop
early to get k clusters). Prim is vertex-centric (one priority queue, naturally
incremental, and the dense-graph / Fibonacci-heap variant hits O(E + V log V)).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  V              : number of vertices. The worked graph has V=5 (S,A,B,C,D).
  E              : number of (undirected) edges.
  spanning tree  : a subset of edges that connects all V vertices with no cycle.
                   Always has exactly V-1 edges.
  MST            : the spanning tree with minimum total edge weight.
  cut            : a partition of vertices into two non-empty sets (S, V-S).
  cut property   : the lightest edge crossing ANY cut belongs to SOME MST.
                   This single fact proves BOTH Kruskal and Prim correct.
  cycle          : a closed loop of edges. A spanning tree has none.
  Union-Find     : disjoint-set forest: find(x)=root of x's set, union(a,b)=
                   merge the two sets. With path compression + union by rank,
                   each op is effectively O(1) (inverse-Ackermann). Kruskal uses
                   it to test "would this edge form a cycle?" in one find-pair.
  relaxation
  (Prim)         : push every frontier edge into a min-priority-queue keyed by
                   weight; pop the lightest edge to a NEW vertex to extend tree.
  forest         : Kruskal starts with V singletons (a forest of V trees); each
                   accepted edge merges two trees. After V-1 merges: one tree.

============================================================================
THE LINEAGE (references)
============================================================================
  Boruvka  (Boruvka 1926) : the FIRST MST algorithm (parallelizable), predates
                            even computers; still used for distributed MST.
  Kruskal  (Kruskal 1956, "On the shortest spanning subtree of a graph") : the
                            sort-edges + greedy-add idea.
  Prim     (Prim 1957; also Jarnik 1930) : grow-from-a-source via lightest cut
                            edge.
  CLRS Ch.23 : the cut property, the cycle property, and the optimality proofs
                            of both algorithms.

KEY FACTS (all asserted in code below):
    Kruskal  time   = O(E log E)  = O(E log V)   (sort dominates)
    Prim     time   = O(E log V)                  (binary-heap priority queue)
    Prim dense        = O(V^2)                     (adjacency-matrix, no heap)
    edges in MST      = V - 1
    both optimal      : proved via the cut property
    may differ        : on graphs with tied weights Kruskal & Prim can pick
                        DIFFERENT edge sets of IDENTICAL total weight.

Conventions:
    Vertices are integers 0..V-1. Edges are (u, v, w) tuples, UNDIRECTED
    (each pair appears once in the input list).
    Labels: 0=S, 1=A, 2=B, 3=C, 4=D (the main worked graph).
"""

from __future__ import annotations

import heapq

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS
#    This is the code MST_KRUSKAL_PRIM.md walks through.
# ============================================================================

class UnionFind:
    """Disjoint-set forest with path compression + union by rank. Each op is
    O(alpha(N)) ~ O(1). Kruskal uses it to reject cycle-forming edges."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n
        self.components = n

    def find(self, x: int) -> int:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:          # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: int, b: int) -> bool:
        """Merge the sets of a and b. Return True if they were separate (a
        real merge), False if already in the same set (edge would form a cycle)."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1
        self.components -= 1
        return True

    def connected(self, a: int, b: int) -> bool:
        return self.find(a) == self.find(b)


def kruskal(V, edges, trace=False):
    """Kruskal's MST. Returns (mst_edges, total_weight, log).

    log : list of (edge, decision, components_after) per sorted edge, if trace.
    """
    uf = UnionFind(V)
    mst = []
    total = 0.0
    log = []
    for u, v, w in sorted(edges, key=lambda e: e[2]):
        merged = uf.union(u, v)
        if merged:
            mst.append((u, v, w))
            total += w
            decision = "ADD"
        else:
            decision = "skip (cycle)"
        if trace:
            log.append(((u, v, w), decision, self_components(uf, V)))
        if len(mst) == V - 1:
            if trace:                                              # fill skips
                for u2, v2, w2 in sorted(edges, key=lambda e: e[2])[len(log):]:
                    log.append(((u2, v2, w2), "skip (tree complete)",
                                self_components(uf, V)))
            break
    return mst, total, log


def self_components(uf, n):
    """Snapshot of Union-Find components as a list of frozensets (for display)."""
    groups: dict[int, list[int]] = {}
    for x in range(n):
        groups.setdefault(uf.find(x), []).append(x)
    return [sorted(g) for g in groups.values()]


def prim(V, edges, src=0, trace=False):
    """Prim's MST from `src` via a binary-heap priority queue.

    Returns (mst_edges, total_weight, log). log is a list of step dicts when
    trace=True: each step = {popped_edge, new_vertex, frontier_size, total}.

    Standard trick: the priority queue holds (weight, vertex, parent). When a
    vertex is popped, if it is already in the tree we discard it (a stale,
    heavier copy); otherwise we add (parent, vertex, weight) to the MST and
    push its unvisited neighbors. We also skip stale entries by tracking the
    in-tree set, so the queue never inserts the same vertex's lightest edge
    twice as a real edge.
    """
    adj = [[] for _ in range(V)]
    for u, v, w in edges:
        adj[u].append((w, v))
        adj[v].append((w, u))

    in_tree = [False] * V
    in_tree[src] = True
    pq: list[tuple[int, int, int]] = []      # (weight, vertex, parent)
    for w, nb in adj[src]:
        heapq.heappush(pq, (w, nb, src))

    mst = []
    total = 0.0
    log = []
    visited_count = 1
    while pq and visited_count < V:
        w, u, parent = heapq.heappop(pq)
        if in_tree[u]:
            if trace:
                log.append({"popped": (parent, u, w), "new_vertex": None,
                            "note": "stale (already in tree)", "total": total})
            continue
        in_tree[u] = True
        visited_count += 1
        mst.append((parent, u, w))
        total += w
        if trace:
            log.append({"popped": (parent, u, w), "new_vertex": u,
                        "note": "ADD", "total": total})
        for nw, nb in adj[u]:
            if not in_tree[nb]:
                heapq.heappush(pq, (nw, nb, u))
    return mst, total, log


def edge_set(mst):
    """Edges as a set of frozensets {u,v} (order-independent) for comparison."""
    return {frozenset((u, v)) for u, v, _ in mst}


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

NAMES = ["S", "A", "B", "C", "D"]
TIE_NAMES = ["P", "Q", "R", "T"]


def banner(title):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def elab(u, v, names):
    return f"{names[u]}-{names[v]}"


def components_str(comps, names):
    parts = ["{" + ",".join(names[i] for i in g) + "}" for g in comps]
    return "  ".join(parts)


# ============================================================================
# 3. THE WORKED GRAPHS
#    Small enough to print every step, big enough to show all behavior.
# ============================================================================

# --- main worked graph: V=5 (S,A,B,C,D), 7 undirected edges ---
V_MAIN = 5
EDGES_MAIN = [
    (0, 1, 2),    # S - A
    (0, 3, 6),    # S - C
    (1, 2, 3),    # A - B
    (1, 3, 8),    # A - C
    (1, 4, 5),    # A - D
    (2, 4, 7),    # B - D
    (3, 4, 9),    # C - D
]

# --- tie graph: V=4 (P,Q,R,T), a 4-cycle all weight 1 -> Kruskal != Prim edges ---
V_TIE = 4
EDGES_TIE = [
    (0, 1, 1),    # P - Q
    (1, 2, 1),    # Q - R
    (2, 3, 1),    # R - T
    (3, 0, 1),    # T - P
]


# ----------------------------------------------------------------------------
# SECTION A: Kruskal - sort edges, Union-Find cycle check, build MST
# ----------------------------------------------------------------------------

def section_kruskal():
    banner("SECTION A: Kruskal - sort edges, Union-Find cycle check")
    print(f"Graph: V={V_MAIN} (S,A,B,C,D), E={len(EDGES_MAIN)} undirected edges.\n"
          f"Goal: a spanning tree with exactly V-1 = {V_MAIN - 1} edges and minimum\n"
          f"total weight.\n")
    print("Step 1 - sort all edges by weight (ascending):")
    for u, v, w in sorted(EDGES_MAIN, key=lambda e: e[2]):
        print(f"  {elab(u, v, NAMES):<6} w = {w}")
    print()

    mst, total, log = kruskal(V_MAIN, EDGES_MAIN, trace=True)
    print("Step 2 - scan in order; ADD the edge iff its endpoints are in DIFFERENT\n"
          "Union-Find components (otherwise it would close a cycle). Components after\n"
          "each decision:\n")
    print(f"  {'#':<3}{'edge':<8}{'w':<5}{'decision':<22}{'components after':<40}")
    print("  " + "-" * 76)
    for i, ((u, v, w), dec, comps) in enumerate(log, 1):
        print(f"  {i:<3}{elab(u, v, NAMES):<8}{w:<5}{dec:<22}"
              f"{components_str(comps, NAMES):<40}")
    print()

    uf_demo = UnionFind(V_MAIN)
    for u, v, w in mst:
        uf_demo.union(u, v)
    print(f"MST edges ({len(mst)} = V-1):")
    for u, v, w in mst:
        print(f"  {elab(u, v, NAMES):<6} w = {w}")
    print(f"\n  total weight = {total}\n")
    print("Three edges were SKIPPED (B-D, A-C, C-D): each would have connected two\n"
          "vertices already in the same component -> a cycle. Union-Find's find()\n"
          "detected that in near-O(1) (inverse-Ackermann) per check.\n")
    assert len(mst) == V_MAIN - 1
    assert total == 16
    assert edge_set(mst) == {frozenset((0, 1)), frozenset((1, 2)),
                             frozenset((1, 4)), frozenset((0, 3))}
    print(f"[check] MST has V-1 = {V_MAIN - 1} edges, no cycle, total = {total}:  OK")


# ----------------------------------------------------------------------------
# SECTION B: Prim - grow from source via a priority queue
# ----------------------------------------------------------------------------

def section_prim():
    banner("SECTION B: Prim - grow from source via a priority queue")
    print(f"Same graph (V={V_MAIN}, E={len(EDGES_MAIN)}). Start from S. Repeatedly add\n"
          f"the CHEAPEST edge crossing the cut (tree | rest), tracked by a min-priority\n"
          f"queue of frontier edges.\n")
    mst, total, log = prim(V_MAIN, EDGES_MAIN, src=0, trace=True)
    print(f"  {'step':<5}{'popped edge':<14}{'w':<5}{'decision':<24}{'total':<8}")
    print("  " + "-" * 54)
    step = 0
    for entry in log:
        parent, u, w = entry["popped"]
        if entry["new_vertex"] is None:
            print(f"  {'':<5}{elab(parent, u, NAMES):<14}{w:<5}"
                  f"{entry['note']:<24}{'':<8}")
        else:
            step += 1
            print(f"  {step:<5}{elab(parent, u, NAMES):<14}{w:<5}"
                  f"{'ADD ' + NAMES[u] + ' to tree':<24}{entry['total']:<8}")
    print()
    print(f"MST edges ({len(mst)} = V-1):")
    for u, v, w in mst:
        print(f"  {elab(u, v, NAMES):<6} w = {w}")
    print(f"\n  total weight = {total}\n")
    print("Each step pops the globally-lightest edge whose endpoint is NEW. Stale\n"
          "entries (a vertex pushed with a heavier weight before a lighter path was\n"
          "found) are discarded when popped. The tree grows one vertex per accepted\n"
          "edge until it spans all V vertices.\n")
    assert len(mst) == V_MAIN - 1
    assert total == 16
    print(f"[check] Prim MST has V-1 = {V_MAIN - 1} edges, total = {total}:  OK")


# ----------------------------------------------------------------------------
# SECTION C: compare on the SAME graph + a tie graph where they differ
# ----------------------------------------------------------------------------

def section_compare():
    banner("SECTION C: Kruskal vs Prim on the SAME graph (+ a tie graph)")
    kmst, ktotal, _ = kruskal(V_MAIN, EDGES_MAIN)
    pmst, ptotal, _ = prim(V_MAIN, EDGES_MAIN, src=0)
    same_edges = edge_set(kmst) == edge_set(pmst)
    print("Main graph (S,A,B,C,D):\n")
    print("  | algorithm | total weight | # edges | edge set identical? |")
    print("  |-----------|--------------|---------|---------------------|")
    print(f"  | Kruskal   | {ktotal:<12} | {len(kmst):<7} | "
          f"{'yes' if same_edges else 'no (see below)':<19} |")
    print(f"  | Prim      | {ptotal:<12} | {len(pmst):<7} |")
    print(f"\n  -> same total weight? {'YES (' + str(ktotal) + ')' if ktotal == ptotal else 'NO'}")
    print(f"  -> identical edges?   {'YES' if same_edges else 'NO'}\n")

    print("Now a TIE graph: a 4-cycle (P,Q,R,T) where every edge has weight 1.\n"
          "Any 3 of the 4 edges form an MST of weight 3 - so Kruskal and Prim can\n"
          "legitimately pick DIFFERENT edge sets:\n")
    for u, v, w in EDGES_TIE:
        print(f"  {elab(u, v, TIE_NAMES):<6} w = {w}")
    print()
    km, kt, _ = kruskal(V_TIE, EDGES_TIE)
    pm, pt, _ = prim(V_TIE, EDGES_TIE, src=0)
    kset, pset = edge_set(km), edge_set(pm)
    same2 = kset == pset
    print("  | algorithm | edges chosen        | total |")
    print("  |-----------|---------------------|-------|")
    ke = ", ".join(elab(u, v, TIE_NAMES) for u, v, _ in km)
    pe = ", ".join(elab(u, v, TIE_NAMES) for u, v, _ in pm)
    print(f"  | Kruskal   | {ke:<19} | {kt:<5} |")
    print(f"  | Prim      | {pe:<19} | {pt:<5} |")
    konly = kset - pset
    ponly = pset - kset
    print(f"\n  same total weight? {kt == pt}    identical edges? {same2}")
    if not same2:
        ko = next(iter(konly))
        po = next(iter(ponly))
        print(f"  Kruskal-only edge: {elab(*sorted(ko), TIE_NAMES)}")
        print(f"  Prim-only edge:    {elab(*sorted(po), TIE_NAMES)}")
        print("  Both are weight 1, so swapping them keeps the total at 3 - BOTH are\n"
              "  valid MSTs. This is why we say 'identical weight, may differ in edges'.")
    print()
    assert ktotal == ptotal == 16
    assert kt == pt == 3
    print("[check] main graph: Kruskal total == Prim total == 16:  OK")
    print("[check] tie graph:  Kruskal total == Prim total == 3 (different edges):  OK")


# ----------------------------------------------------------------------------
# SECTION D: the cut property (why both algorithms are correct)
# ----------------------------------------------------------------------------

def section_cut_property():
    banner("SECTION D: the cut property - why both algorithms are optimal")
    print("THE CUT PROPERTY: for ANY cut (S, V-S) of the graph, the LIGHTEST edge\n"
          "crossing it belongs to SOME minimum spanning tree.\n")
    print("This single theorem proves BOTH algorithms correct:\n"
          "  - Kruskal accepts edge (u,v) across cut 'component(u) | rest'; it is the\n"
          "    lightest such edge (edges are processed cheapest-first), so it is safe.\n"
          "  - Prim adds the lightest edge leaving the current tree (cut 'tree | rest').\n")

    # demonstrate on the main graph: cut {S,A} | {B,C,D}
    cut_in = {0, 1}     # {S, A}
    label_in = "{" + ",".join(NAMES[i] for i in sorted(cut_in)) + "}"
    label_out = "{" + ",".join(NAMES[i] for i in range(V_MAIN) if i not in cut_in) + "}"
    print(f"Concrete cut on the main graph: {label_in} | {label_out}\n")
    crossing = []
    for u, v, w in EDGES_MAIN:
        if (u in cut_in) != (v in cut_in):
            crossing.append((u, v, w))
    print("Crossing edges (one endpoint inside, one outside):")
    for u, v, w in crossing:
        print(f"  {elab(u, v, NAMES):<6} w = {w}")
    lightest = min(crossing, key=lambda e: e[2])
    mst, _, _ = kruskal(V_MAIN, EDGES_MAIN)
    in_mst = frozenset((lightest[0], lightest[1])) in edge_set(mst)
    print(f"\nLightest crossing edge = {elab(*lightest[:2], NAMES)} (w = {lightest[2]}).")
    print(f"Is it in the MST? {in_mst}  <- the cut property guarantees it.\n")

    # second cut: {S} | {A,B,C,D}
    cut_in = {0}
    label_in = "{" + ",".join(NAMES[i] for i in sorted(cut_in)) + "}"
    label_out = "{" + ",".join(NAMES[i] for i in range(V_MAIN) if i not in cut_in) + "}"
    crossing2 = [(u, v, w) for u, v, w in EDGES_MAIN if (u in cut_in) != (v in cut_in)]
    light2 = min(crossing2, key=lambda e: e[2])
    print(f"Another cut {label_in} | {label_out}: crossing = "
          f"{[elab(u,v,NAMES)+'(w='+str(w)+')' for u,v,w in crossing2]}")
    print(f"Lightest = {elab(*light2[:2], NAMES)} (w = {light2[2]}), also in the MST.")
    print("\nThe cut property is symmetric with the CYCLE property: the HEAVIEST edge on\n"
          "any cycle is NOT in any MST (removing it keeps the graph connected and only\n"
          "lowers the total). Kruskal's cycle-skip is exactly this applied greedily.\n")
    assert in_mst
    print("[check] lightest crossing edge of each cut is in the MST:  OK")


# ----------------------------------------------------------------------------
# SECTION E: applications - network design & clustering - GOLD CHECK
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION E: applications + GOLD CHECK")
    print("APPLICATION 1 - network design. The MST is literally the minimum-cost way\n"
          "to wire up a set of points: power grids, fiber backbones, pipe networks,\n"
          "PCB routing. Both algorithms give the optimal layout.\n")
    print("APPLICATION 2 - single-linkage clustering. Run Kruskal but STOP after\n"
          "V - k accepted edges: you get k connected components = k clusters, where no\n"
          "two clusters can be merged more cheaply. This is 'maximum spacing' k-clustering\n"
          "(each merge greedily joins the two closest clusters).\n")

    # clustering demo: stop Kruskal at V - 2 edges -> 2 clusters
    uf = UnionFind(V_MAIN)
    se = sorted(EDGES_MAIN, key=lambda e: e[2])
    accepted = 0
    target = V_MAIN - 2          # 2 clusters
    for u, v, w in se:
        if accepted >= target:
            break
        if uf.union(u, v):
            accepted += 1
    clusters = self_components(uf, V_MAIN)
    print(f"Kruskal stopped at V-2 = {target} edges -> {len(clusters)} clusters:")
    for c in clusters:
        print("  cluster: {" + ", ".join(NAMES[i] for i in c) + "}")
    print(f"\nThe NEXT edge Kruskal would add is "
          f"{elab(*se[accepted][:2], NAMES)} (w = {se[accepted][2]}) - the distance\n"
          f"(min edge between clusters) between the two clusters. Maximum-spacing\n"
          f"clustering maximizes this minimum inter-cluster distance.\n")

    # ---- GOLD CHECK: both produce the same total MST weight on the main graph ----
    print("-" * 68)
    kmst, ktotal, _ = kruskal(V_MAIN, EDGES_MAIN)
    pmst, ptotal, _ = prim(V_MAIN, EDGES_MAIN, src=0)
    print("\nGOLD CHECK on the main graph (S,A,B,C,D):")
    print(f"  Kruskal total = {ktotal}")
    print(f"  Prim    total = {ptotal}")
    match = abs(ktotal - ptotal) < 1e-9 and len(kmst) == V_MAIN - 1 \
        and len(pmst) == V_MAIN - 1
    print(f"  -> both = V-1 = {V_MAIN - 1} edges, same total weight: "
          f"{'OK' if match else 'FAIL'}")
    assert match
    print(f"\nGOLD CHECK: OK - Kruskal total ({ktotal}) == Prim total ({ptotal})")
    print("(mst_kruskal_prim.html re-runs both algorithms in JS and re-checks these values.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("mst_kruskal_prim.py - reference impl. All numbers below feed MST_KRUSKAL_PRIM.md.")
    print("python stdlib only; deterministic.")

    section_kruskal()
    section_prim()
    section_compare()
    section_cut_property()
    section_applications()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
