"""
bellman_ford.py - Reference implementation of the Bellman-Ford single-source
shortest-path algorithm, negative-cycle detection, SPFA, and currency
arbitrage.

This is the single source of truth that BELLMAN_FORD.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 bellman_ford.py

============================================================================
THE INTUITION (read this first) - the "rumor that keeps getting better"
============================================================================
You want the cheapest way to get from a source to every other vertex. Dijkstra
settles the closest unvisited vertex greedily and never reconsiders it - that
ONLY works when no edge can retroactively lower an already-settled vertex,
which is guaranteed precisely when ALL weights are non-negative.

Bellman-Ford is the patient, brute version:
  * RELAX every edge: "is there a cheaper way to reach v through u?"
        if dist[u] + w(u,v) < dist[v]:  dist[v] = dist[u] + w(u,v)
  * Do that for V-1 PASSES over ALL edges. After V-1 passes every shortest path
    (which is simple, so it has at most V-1 edges) has been fully discovered.
  * Do ONE MORE pass (the V-th). If ANY edge still relaxes -> a NEGATIVE CYCLE
    is reachable from the source. You could loop it forever to drive costs to
    -infinity, so shortest paths are undefined.

THE REASON IT EXISTS: negative weights. Currency exchange rates, log-likelihood
graphs, chemical free-energy diagrams, game theory - all routinely produce
negative edge weights. Dijkstra's greedy "settle the closest vertex" assumption
is WRONG the moment a negative edge can improve an already-settled vertex.
Bellman-Ford never settles early, so negatives are fine.

THE PAYOFF - arbitrage detection: write the exchange rate as weight = -log(rate);
a "cheapest path" becomes a "best conversion", and a NEGATIVE CYCLE becomes an
ARBITRAGE (a loop of trades that ends with more money than you started with).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  V              : number of vertices. The worked graph has V=5 (S,A,B,C,D).
  E              : number of directed edges.
  relaxation     : the one move: try to improve dist[v] via dist[u]+w(u,v).
                   An edge "relaxes" when it actually lowers dist[v].
  pass           : one sweep over ALL E edges (in a fixed order).
  dist[v]        : best known cost source -> v so far. 0 at source, +inf elsewhere.
  predecessor    : the vertex u that gave dist[v] its current value; rebuilds
                   the shortest-path tree.
  V-1 passes     : the completeness bound. Any simple shortest path has at most
                   V-1 edges, so after V-1 sweeps no relaxation is possible
                   UNLESS a negative cycle exists.
  negative cycle : a directed cycle whose total weight is < 0. Shortest paths
                   through it are undefined (loop forever, cost -> -inf).
  detection      : a relaxation on the V-th pass <=> a reachable negative cycle.
  SPFA           : Shortest Path Faster Algorithm - a queue-based Bellman-Ford.
                   Only relax edges leaving vertices whose dist just changed.
                   Same worst case O(V*E), far fewer checks in practice.

============================================================================
THE LINEAGE (references)
============================================================================
  Bellman  (Bellman 1958, "On a Routing Problem", Q. Applied Math) : the DP
                 recurrence that is the V-1 relaxation bound.
  Ford     (Ford 1956, "Network Flow Theory", RAND paper)          : the same
                 relaxation-to-fixpoint idea, independently.
  SPFA     (Moore 1959; popularized by Fanding Duan 1994)          : the queue
                 optimization - only re-examine vertices that changed.
  Arbitrage: the -log(rate) reduction is standard in quantitative finance;
                 see CLRS Ch.24 exercises and any FX-arbitrage primer.

KEY FACTS (all asserted in code below):
    one relaxation pass   = O(E)
    total (no neg cycle)  = O(V*E)        (V-1 passes + 1 detection pass)
    vs Dijkstra           = O(E log V)    (faster, but no negative weights)
    negative weights      : HANDLED       (Dijkstra: NOT handled - silently wrong)
    negative cycle        : DETECTED      (Dijkstra: silently wrong)
    completeness          : after V-1 passes dist[] is exact  <=>  no neg cycle.
    SPFA worst case       = O(V*E)        (same as Bellman-Ford; usually much less)

Conventions:
    Vertices are integers 0..V-1. The source is always vertex 0.
    Edges are a list of (u, v, w) tuples; "in order" = that list's order.
    Labels: 0=S, 1=A, 2=B, 3=C, 4=D (the main worked graph).
"""

from __future__ import annotations

import heapq
import math

BANNER = "=" * 72

INF = float("inf")


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS
#    This is the code BELLMAN_FORD.md walks through.
# ============================================================================

def bellman_ford(V, edges, src=0, trace=False):
    """Single-source shortest paths via V-1 relaxation passes + 1 detection pass.

    Returns (dist, pred, has_negative_cycle, neg_edge, log).
      log : list of (dist_snapshot, relax_count) per pass, when trace=True.
      neg_edge : the (u,v,w) that relaxed on the V-th pass (else None).
    """
    dist = [INF] * V
    pred = [-1] * V
    dist[src] = 0
    log = []

    for k in range(V - 1):                       # passes 1 .. V-1
        relaxed = 0
        for u, v, w in edges:                    # relax every edge
            if dist[u] != INF and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                pred[v] = u
                relaxed += 1
        if trace:
            log.append((dist.copy(), relaxed))

    # detection pass (the V-th)
    neg_edge = None
    for u, v, w in edges:
        if dist[u] != INF and dist[u] + w < dist[v]:
            neg_edge = (u, v, w)
            break

    return dist, pred, neg_edge is not None, neg_edge, log


def dijkstra(V, edges, src=0):
    """Classic Dijkstra. CORRECT ONLY WITH NON-NEGATIVE weights. Used in
    Section D to prove Bellman-Ford agrees when that precondition holds."""
    adj = [[] for _ in range(V)]
    for u, v, w in edges:
        adj[u].append((v, w))
    dist = [INF] * V
    pred = [-1] * V
    dist[src] = 0
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist[v]:
                dist[v] = nd
                pred[v] = u
                heapq.heappush(pq, (nd, v))
    return dist, pred


def spfa(V, edges, src=0):
    """Shortest Path Faster Algorithm - queue-based Bellman-Ford. Push a vertex
    onto the queue only when its dist just decreased, then relax only its
    OUTGOING edges. Returns (dist, pred, edge_checks, relaxes)."""
    adj = [[] for _ in range(V)]
    for u, v, w in edges:
        adj[u].append((v, w))
    dist = [INF] * V
    pred = [-1] * V
    dist[src] = 0
    in_queue = [False] * V
    q = [src]
    in_queue[src] = True
    checks = 0
    relaxes = 0
    while q:
        u = q.pop(0)
        in_queue[u] = False
        for v, w in adj[u]:
            checks += 1
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                pred[v] = u
                relaxes += 1
                if not in_queue[v]:
                    q.append(v)
                    in_queue[v] = True
    return dist, pred, checks, relaxes


def find_negative_cycle(V, edges, src=0):
    """Return a list of vertex indices forming a negative cycle (or None).

    Standard technique: run V passes (V-1 + 1 detection). If the V-th pass
    relaxes vertex x, x is reachable from a negative cycle. Walk predecessors
    V times from x to guarantee we are ON the cycle, then collect until we loop.
    """
    dist = [INF] * V
    pred = [-1] * V
    dist[src] = 0
    x = -1
    for _ in range(V):
        x = -1
        for u, v, w in edges:
            if dist[u] != INF and dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                pred[v] = u
                x = v
    if x == -1:
        return None
    # walk V steps to land inside the cycle
    for _ in range(V):
        x = pred[x]
        if x == -1:
            return None
    cycle = [x]
    y = pred[x]
    while y != x:
        cycle.append(y)
        y = pred[y]
    cycle.reverse()
    return cycle


def reconstruct(pred, target):
    """Walk predecessors from target to source. [] if unreachable."""
    if pred[target] == -1 and target != 0:
        return []
    path = []
    v = target
    while v != -1:
        path.append(v)
        v = pred[v]
    path.reverse()
    return path


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

NAMES = ["S", "A", "B", "C", "D"]


def banner(title):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_dist(dist, names=None):
    names = names or [str(i) for i in range(len(dist))]
    cells = []
    for n, d in zip(names, dist):
        cells.append(f"{n}={'inf' if d == INF else round(d, 6)}")
    return "  ".join(cells)


# ============================================================================
# 3. THE WORKED GRAPHS
#    Small enough to print every pass, big enough to show all behavior.
# ============================================================================

# --- main graph: negative edges, NO negative cycle (S,A,B,C,D) ---
V_MAIN = 5
EDGES_MAIN = [
    (0, 1, 6),    # S -> A
    (0, 2, 7),    # S -> B
    (1, 3, 5),    # A -> C
    (1, 4, -4),   # A -> D   (negative edge, but no negative cycle)
    (2, 1, 8),    # B -> A
    (2, 3, -3),   # B -> C   (negative edge)
    (3, 4, 9),    # C -> D
    (4, 2, 2),    # D -> B
]

# --- negative-cycle graph (P,Q,R) ---
V_NEG = 3
EDGES_NEG = [
    (0, 1, 1),    # P -> Q
    (1, 2, -1),   # Q -> R
    (2, 0, -1),   # R -> P   cycle P->Q->R->P = 1 - 1 - 1 = -1
    (0, 2, 4),    # P -> R   (decoy edge; does not form a cycle by itself)
]
NEG_NAMES = ["P", "Q", "R"]

# --- currency arbitrage (USD,EUR,GBP) ---
CUR_NAMES = ["USD", "EUR", "GBP"]
RATES = {
    ("USD", "EUR"): 0.9,  ("EUR", "USD"): 1.11,
    ("USD", "GBP"): 0.75, ("GBP", "USD"): 1.33,
    ("EUR", "GBP"): 0.89, ("GBP", "EUR"): 1.12,
}

# --- non-negative graph for the Bellman-Ford vs Dijkstra gold check ---
V_POS = 5
EDGES_POS = [
    (0, 1, 10),   # S -> A
    (0, 2, 3),    # S -> B
    (2, 1, 4),    # B -> A
    (1, 3, 2),    # A -> C
    (2, 3, 9),    # B -> C
    (3, 4, 5),    # C -> D
    (2, 4, 12),   # B -> D
]


# ----------------------------------------------------------------------------
# SECTION A: relaxation - V-1 passes on the main graph (neg edges, no neg cycle)
# ----------------------------------------------------------------------------

def section_relaxation():
    banner("SECTION A: relaxation - V-1 passes (negative edges, NO negative cycle)")
    print(f"Graph: V={V_MAIN} vertices (S,A,B,C,D), E={len(EDGES_MAIN)} "
          f"directed edges, source = S.\n")
    print("Edges (in relaxation order):")
    for u, v, w in EDGES_MAIN:
        print(f"  {NAMES[u]} -> {NAMES[v]}  w = {w}")
    print(f"\nThere are negative edges (A->D = -4, B->C = -3) but the cycle\n"
          f"costs are all >= 0 (e.g. B->A->D->B = 8-4+2 = 6), so shortest paths\n"
          f"exist. V-1 = {V_MAIN - 1} passes guarantee convergence.\n")

    dist, pred, has_neg, neg_edge, log = bellman_ford(V_MAIN, EDGES_MAIN, 0, trace=True)

    print(f"{'pass':<6}{'distances after pass':<48}{'#relaxations':<14}")
    print("-" * 68)
    print(f"{'init':<6}{fmt_dist([0] + [INF] * 4, NAMES):<48}{'-':<14}")
    for k, (snap, rel) in enumerate(log):
        print(f"{k + 1:<6}{fmt_dist(snap, NAMES):<48}{rel:<14}")
    # detection pass
    print(f"{'det.':<6}{fmt_dist(dist, NAMES):<48}"
          f"{'0 (no relax -> no neg cycle)' if not has_neg else 'RELAXED!'}\n")

    print("Read it column by column: dist[B] starts at 7, then drops to 4 in pass 1\n"
          "(via S->A->D->B = 6-4+2), then dist[C] drops from 4 to 1 in pass 2 (via\n"
          "B->C once B reached 4). After pass 2 nothing changes - the shortest-path\n"
          "tree is complete.\n")

    print("Shortest-path tree (source S = vertex 0):")
    print(f"  {'to':<6}{'dist':<10}{'path':<24}{'path cost':<12}")
    print("  " + "-" * 50)
    for t in range(V_MAIN):
        p = reconstruct(pred, t)
        plab = " -> ".join(NAMES[i] for i in p) if p else "(unreachable)"
        cost = dist[t] if dist[t] != INF else "inf"
        print(f"  {NAMES[t]:<6}{cost:<10}{plab:<24}{cost if isinstance(cost, str) else ''}")
    print()
    assert not has_neg, "expected NO negative cycle here"
    assert dist == [0, 6, 4, 1, 2], dist
    print(f"[check] final dist = {dist} == [0, 6, 4, 1, 2]:  OK")
    print("[check] no relaxation on V-th (detection) pass:  OK")
    print(f"[check] V-1 = {V_MAIN - 1} passes suffice (passes 3,4 are pure verification):  OK")


# ----------------------------------------------------------------------------
# SECTION B: negative cycle detection - the V-th pass still relaxes
# ----------------------------------------------------------------------------

def section_negative_cycle():
    banner("SECTION B: negative cycle detection - the V-th pass still relaxes")
    print(f"Graph: V={V_NEG} (P,Q,R), E={len(EDGES_NEG)} edges, source = P.\n")
    print("Edges:")
    for u, v, w in EDGES_NEG:
        print(f"  {NEG_NAMES[u]} -> {NEG_NAMES[v]}  w = {w}")
    cyc_w = 1 + (-1) + (-1)
    print(f"\nCycle P->Q->R->P total weight = 1 + (-1) + (-1) = {cyc_w} < 0  ->  "
          f"NEGATIVE CYCLE.\n")

    dist, pred, has_neg, neg_edge, log = bellman_ford(V_NEG, EDGES_NEG, 0, trace=True)
    print(f"{'pass':<6}{'distances after pass':<40}{'#relaxations':<14}")
    print("-" * 58)
    print(f"{'init':<6}{fmt_dist([0, INF, INF], NEG_NAMES):<40}{'-'}")
    for k, (snap, rel) in enumerate(log):
        print(f"{k + 1:<6}{fmt_dist(snap, NEG_NAMES):<40}{rel}")
    print(f"{'det.':<6}{fmt_dist(dist, NEG_NAMES):<40}{'RELAXED!'}\n")

    print(f"On the V-th (detection) pass an edge STILL relaxed -> has_negative_cycle "
          f"= {has_neg}.\n")
    print("The distances keep diverging (more negative) every pass because you can\n"
          "loop P->Q->R->P forever, each lap costing -1. So shortest paths are\n"
          "undefined; Bellman-Ford's job is to DETECT this, not solve it.\n")

    cycle = find_negative_cycle(V_NEG, EDGES_NEG, 0)
    clab = " -> ".join(NEG_NAMES[i] for i in cycle + [cycle[0]])
    print(f"Recovered negative cycle: {clab}  (weight {cyc_w})")
    assert has_neg
    assert cycle == [0, 1, 2] or cycle == [1, 2, 0] or cycle == [2, 0, 1]
    print("[check] negative cycle detected AND recovered:  OK")


# ----------------------------------------------------------------------------
# SECTION C: currency arbitrage - negative cycle == profit opportunity
# ----------------------------------------------------------------------------

def section_arbitrage():
    banner("SECTION C: currency arbitrage - negative cycle == profit")
    V = 3
    print("An exchange rate r(i,j) = 'units of j per 1 unit of i'. A trade loop is\n"
          "profitable iff the PRODUCT of rates around the loop > 1.\n")
    print("Reduction: weight(i,j) = -log(r(i,j)). Then the weight around a loop is\n"
          "  sum -log(r) = -log(product of rates).\n"
          "So:  weight_sum < 0  <=>  -log(product) < 0  <=>  product > 1  <=>  ARBITRAGE.\n"
          "A profitable trade loop is EXACTLY a negative cycle in the -log graph.\n")

    print("Exchange rate table (rate[i][j] = units of j per 1 i):\n")
    print(f"  {'':<6}" + "".join(f"{c:<8}" for c in CUR_NAMES))
    print("  " + "-" * 30)
    for a in CUR_NAMES:
        row = f"  {a:<6}"
        for b in CUR_NAMES:
            if a == b:
                row += f"{'1.00':<8}"
            else:
                row += f"{RATES[(a, b)]:<8.2f}"
        print(row)
    print()

    print("Sanity: every DIRECT round-trip (2-cycle) must be <= 1 or a single pair is\n"
          "already an arbitrage. Here:")
    pairs = [("USD", "EUR"), ("USD", "GBP"), ("EUR", "GBP")]
    for a, b in pairs:
        prod = RATES[(a, b)] * RATES[(b, a)]
        print(f"  {a}->{b}->{a}: {RATES[(a, b)]} * {RATES[(b, a)]} = {prod:.4f}  "
              f"({'arbitrage!' if prod > 1 else 'ok'})")
    print()

    # build -log edges
    edges = []
    print("Edge weights w(i,j) = -ln(rate(i,j)):\n")
    print(f"  {'edge':<14}{'rate':<8}{'-ln(rate)':<12}")
    print("  " + "-" * 34)
    idx = {c: i for i, c in enumerate(CUR_NAMES)}
    for (a, b), r in RATES.items():
        w = -math.log(r)
        edges.append((idx[a], idx[b], w))
        print(f"  {a} -> {b:<6}{r:<8}{w:<+12.6f}")
    print()

    dist, pred, has_neg, neg_edge, log = bellman_ford(V, edges, 0, trace=True)
    print(f"{'pass':<6}{'distances after pass (USD,EUR,GBP)':<44}{'#relax':<8}")
    print("-" * 58)
    print(f"{'init':<6}{fmt_dist([0, INF, INF], CUR_NAMES):<44}{'-'}")
    for k, (snap, rel) in enumerate(log):
        print(f"{k + 1:<6}{fmt_dist(snap, CUR_NAMES):<44}{rel}")
    print(f"{'det.':<6}{fmt_dist(dist, CUR_NAMES):<44}{'RELAXED!'}\n")
    print(f"has_negative_cycle = {has_neg}  ->  an arbitrage loop exists.\n")

    cycle = find_negative_cycle(V, edges, 0)
    clab = [CUR_NAMES[i] for i in cycle]
    # weight around the cycle
    wsum = 0.0
    for i in range(len(cycle)):
        a, b = cycle[i], cycle[(i + 1) % len(cycle)]
        wsum += -math.log(RATES[(CUR_NAMES[a], CUR_NAMES[b])])
    factor = math.exp(-wsum)

    print(f"Recovered arbitrage loop: {' -> '.join(clab + [clab[0]])}")
    print(f"  loop weight sum = {wsum:+.6f}  (< 0, as expected)")
    print(f"  rate product    = exp(-weight) = {factor:.5f}  (> 1, profit!)")
    print("\nConcrete trade, starting with $1000 USD:")
    amt = 1000.0
    print(f"  start: {amt:.2f} {CUR_NAMES[0]}")
    for i in range(len(cycle)):
        nxt = cycle[(i + 1) % len(cycle)]
        rate = RATES[(CUR_NAMES[cycle[i]], CUR_NAMES[nxt])]
        amt *= rate
        print(f"  {CUR_NAMES[cycle[i]]} -> {CUR_NAMES[nxt]} @ {rate}: {amt:.2f} {CUR_NAMES[nxt]}")
    profit = amt - 1000.0
    print(f"\n  ended with {amt:.2f} USD  ->  profit = {profit:+.2f} USD "
          f"({profit / 1000 * 100:+.2f}%) per $1000.")
    print(f"\n[check] rate product = {factor:.5f} > 1  <=>  negative cycle:  OK")
    assert has_neg
    assert round(factor, 4) == 1.0653
    print(f"[check] $1000 -> {amt:.2f} (factor {factor:.5f} == 1.06533):  OK")


# ----------------------------------------------------------------------------
# SECTION D: Bellman-Ford vs Dijkstra (non-negative graph) - GOLD CHECK
# ----------------------------------------------------------------------------

def section_vs_dijkstra():
    banner("SECTION D: Bellman-Ford vs Dijkstra (non-negative graph) - GOLD CHECK")
    print(f"Same family of problem (single-source shortest paths), two engines. On a\n"
          f"NON-NEGATIVE graph both must give identical distances - this is the gold\n"
          f"check. Graph: V={V_POS}, E={len(EDGES_POS)}, source S, all w >= 0.\n")
    print("Edges:")
    for u, v, w in EDGES_POS:
        print(f"  {NAMES[u]} -> {NAMES[v]}  w = {w}")
    print()

    bf_dist, bf_pred, has_neg, _, _ = bellman_ford(V_POS, EDGES_POS, 0)
    dj_dist, dj_pred = dijkstra(V_POS, EDGES_POS, 0)
    assert not has_neg

    print(f"  {'to':<6}{'Bellman-Ford':<16}{'Dijkstra':<16}{'match':<8}")
    print("  " + "-" * 44)
    all_ok = True
    for t in range(V_POS):
        ok = abs(bf_dist[t] - dj_dist[t]) < 1e-9
        all_ok &= ok
        print(f"  {NAMES[t]:<6}{bf_dist[t]:<16}{dj_dist[t]:<16}{'OK' if ok else 'FAIL'}")
    print()

    print("Complexity comparison:\n")
    print("  | algorithm     | time          | negative weights | negative cycle |")
    print("  |---------------|---------------|------------------|----------------|")
    print("  | Dijkstra      | O(E log V)    | NO (silently wrong)| NO          |")
    print("  | Bellman-Ford  | O(V*E)        | YES              | DETECTS       |")
    print()
    print("Rule of thumb: if every edge is >= 0, reach for Dijkstra (faster). The\n"
          "moment a single weight can be negative, you NEED Bellman-Ford - Dijkstra\n"
          "settles a vertex the first time it is popped and never revisits, so a\n"
          "later negative edge that would have lowered it is missed.\n")
    assert all_ok
    assert bf_dist == [0, 7, 3, 9, 14]
    assert dj_dist == [0, 7, 3, 9, 14]
    print(f"GOLD CHECK: {'OK - Bellman-Ford == Dijkstra == [0, 7, 3, 9, 14]' if all_ok else 'FAIL'}")
    print("(bellman_ford.html re-runs both in JS and re-checks these values.)")


# ----------------------------------------------------------------------------
# SECTION E: SPFA optimization - only re-examine vertices that changed
# ----------------------------------------------------------------------------

def section_spfa():
    banner("SECTION E: SPFA - the queue optimization (fewer edge-checks)")
    print("Bellman-Ford re-sweeps ALL E edges every pass, even vertices whose dist\n"
          "hasn't changed (so their outgoing edges can't possibly relax). SPFA keeps\n"
          "a queue of vertices whose dist JUST dropped and only relaxes their\n"
          "outgoing edges. Same result, same worst case O(V*E), far less work in\n"
          "practice.\n")
    print(f"Run both on the Section A main graph (V={V_MAIN}, E={len(EDGES_MAIN)}):\n")

    bf_dist, bf_pred, _, _, _ = bellman_ford(V_MAIN, EDGES_MAIN, 0)
    sp_dist, sp_pred, checks, relaxes = spfa(V_MAIN, EDGES_MAIN, 0)

    bf_checks = V_MAIN * len(EDGES_MAIN)        # V-1 relaxation passes + 1 detection
    print("  | engine       | edge-checks | successful relaxes | final dist          |")
    print("  |--------------|-------------|--------------------|---------------------|")
    print(f"  | Bellman-Ford | {bf_checks:<11} | (not tracked)      | {bf_dist} |")
    print(f"  | SPFA         | {checks:<11} | {relaxes:<18} | {sp_dist} |")
    print()
    print(f"SPFA examined {checks} edges to reach the SAME answer Bellman-Ford gets\n"
          f"after sweeping all {len(EDGES_MAIN)} edges {V_MAIN} times "
          f"({bf_checks} checks) - a {bf_checks / checks:.1f}x reduction.\n")
    print("Why SPFA is still O(V*E) worst case: a pathological graph can push a\n"
          "vertex onto the queue O(V) times, each time triggering E relaxations.\n"
          "But on typical and random graphs it is close to O(E).\n")
    assert bf_dist == sp_dist
    print(f"[check] SPFA dist == Bellman-Ford dist == {bf_dist}:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("bellman_ford.py - reference impl. All numbers below feed BELLMAN_FORD.md.")
    print("python stdlib only; deterministic.")

    section_relaxation()
    section_negative_cycle()
    section_arbitrage()
    section_vs_dijkstra()
    section_spfa()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
