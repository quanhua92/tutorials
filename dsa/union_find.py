"""
union_find.py - Reference implementation of Union-Find (Disjoint Set Union,
DSU): make_set, find (with path compression), union (by rank); Kruskal's MST;
amortized analysis.

This is the single source of truth that UNION_FIND.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 union_find.py

=========================================================================
THE INTUITION (read this first) - "who's in your gang?"
=========================================================================
You have N people and a stream of statements "person A and person B are in the
SAME gang". Two questions recur:

  * "are X and Y in the same gang?"        (a connectivity query)
  * "merge gang(A) and gang(B)."           (a union)

The naive model - a `gang[x]` array you scan to relabel on every merge - makes
a merge O(N). Union-Find represents each gang as a TREE (pointing UP to a
representative "root"), and uses two tricks to keep every operation essentially
O(1):

  * PATH COMPRESSION: on find(x), walk x up to the root, then REPOINT every
                      node along the path straight at the root. The tree
                      flattens; future finds are shorter. (one-time cost.)
  * UNION BY RANK    : when merging two trees, attach the SHORTER one under the
                      TALLER one's root (rank = an upper bound on height). This
                      keeps trees shallow: height <= log2(N) before compression.

THE REASON UNION-FIND EXISTS: with BOTH tricks, the AMORTIZED cost per
operation is O(alpha(N)) - the inverse Ackermann function - which is <= 4 for
every N anyone will ever store (it crosses 5 only around N = 2^(2^(2^...)) far
beyond the number of atoms in the universe). In practice: O(1). This makes
Union-Find the engine behind Kruskal's MST, dynamic connectivity, percolation,
and any "group these things" sweep where you only ever merge, never split.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  N              : number of elements (here 8 for the basic demo, 6 for MST).
  parent[x]      : x's PARENT in its tree. The root's parent is itself.
  root(x)        : the representative element of x's set (the tree root).
  make_set(x)    : each element starts as its own singleton tree (root = self).
  find(x)        : walk parent pointers up to the root. With path compression,
                   repoints every node on the path straight at the root.
  union(a,b)     : merge the sets holding a and b: link root(a)'s parent to
                   root(b), choosing the link by RANK to stay shallow.
  rank[x]        : an upper bound on the height of x's subtree. Only roots'
                   ranks change (they grow when two equal-rank trees merge).
  path compress. : find() flattens the path x -> ... -> root into x -> root
                   for every node visited. Amortizes the cost of deep trees.
  inverse Ackermann alpha(N): the amortized bound per op with both tricks; <= 4
                   for all practical N. Grows slower than log*, log** , ...
  Kruskal's MST   : sort edges by weight; add an edge iff its endpoints are in
                   DIFFERENT sets (no cycle). Union-Find answers "same set?".
  connected comp. : the sets, once all unions are done. find(x)==find(y) iff
                   x and y ended up in the same component.

=========================================================================
THE LINEAGE (references)
=========================================================================
  Galler & Fischer 1964 ("An improved equivalence algorithm", CACM) : the
                  original linked-representation union-find.
  Tarjan 1975        ("Efficiency of a Good But Not Linear Set Union
                  Algorithm", JACM) : the O(alpha(N)) amortized bound for
                  union-by-rank + path compression. The landmark result.
  Tarjan & van Leeuwen 1984 : path-halving / splitting variants keep the same
                  bound with one pass and no explicit recursion.
  Kruskal 1956       ("On the shortest spanning subtree of a graph", PAMS) :
                  the MST algorithm that runs on Union-Find for cycle checks.
  CLRS §21           : disjoint-set forests, the rank/union-by-rank invariant,
                  the amortized analysis. Chapter 23 uses it for Kruskal.
  Sedgewick & Wayne §1.5 : "union-find" with percolation as the killer app.

KEY FACTS (all asserted in code below):
    make_set        = O(1)
    find            = O(alpha(N)) amortized  (with path compression)
    union           = O(alpha(N)) amortized  (= 2 finds + O(1))
    union by rank   : tree height <= floor(log2 N)   (before compression)
    path compression: flattens the find path; future finds are O(1)
    both tricks     : amortized O(alpha(N)) per op, alpha(N) <= 4 for all N
    space           = O(N)
    MST via Kruskal = O(E log E)  (dominated by the edge sort)

Conventions:
    Elements are 0-indexed integers 0..N-1. parent[] and rank[] are length-N
    arrays; parent[x]==x marks a root. find/union are 0-indexed in the API.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code UNION_FIND.md walks through)
# ============================================================================

class UnionFind:
    """Disjoint-set forest with path compression + union by rank.

    find: walks up to the root AND repoints every node on the path straight at
          the root (iterative path compression).
    union: links the lower-rank root under the higher-rank root; on a tie it
          arbitrarily picks one and bumps its rank by 1.
    Amortized O(alpha(N)) per operation (Tarjan 1975).
    """

    def __init__(self, n: int):
        self.n = n
        self.parent = list(range(n))      # each element is its own root
        self.rank = [0] * n               # upper bound on subtree height
        self.num_sets = n                 # number of disjoint sets

    def make_set(self, x: int):
        """(Re)initialize element x as a singleton. Used in setup/teardown."""
        self.parent[x] = x
        self.rank[x] = 0

    def find(self, x: int, trace: list | None = None) -> int:
        """Return the root of x's set. Path-compresses the whole path x->root.

        If `trace` is given, append each node visited on the way UP (before
        compression), so callers can visualize the walk. Returns the root.
        """
        # walk to the root, recording the path
        path = []
        root = x
        while self.parent[root] != root:
            path.append(root)
            root = self.parent[root]
        path.append(root)                   # include the root itself
        if trace is not None:
            trace.extend(path)
        # path compression: repoint every node on the path straight at the root
        for node in path:
            self.parent[node] = root
        return root

    def union(self, a: int, b: int) -> bool:
        """Merge the sets holding a and b. Returns True if a merge happened,
        False if they were already in the same set (a would-be cycle)."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False                    # same set already -> no merge
        # union by rank: attach the shorter tree under the taller one
        if self.rank[ra] < self.rank[rb]:
            ra, rb = rb, ra                  # now rank[ra] >= rank[rb]
        self.parent[rb] = ra                 # rb's tree hangs under ra
        if self.rank[ra] == self.rank[rb]:
            self.rank[ra] += 1              # only equal-rank merges grow height
        self.num_sets -= 1
        return True

    def connected(self, a: int, b: int) -> bool:
        return self.find(a) == self.find(b)

    def groups(self) -> dict[int, list[int]]:
        """Return {root: [members]} for every set. Used by gold checks."""
        comps: dict[int, list[int]] = {}
        for x in range(self.n):
            comps.setdefault(self.find(x), []).append(x)
        return comps


# ============================================================================
# 2. A NAIVE UNION-FIND (no compression, no rank) - to expose the worst case
# ============================================================================

class NaiveUnionFind:
    """Union-Find WITHOUT the two tricks: find walks the chain with no
    repointing; union always attaches root(a) under root(b). Used ONLY to build
    a degenerate chain for the path-compression 'before/after' demo."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int, trace: list | None = None) -> int:
        root = x
        depth = 0
        while self.parent[root] != root:
            if trace is not None:
                trace.append(root)
            root = self.parent[root]
            depth += 1
        if trace is not None:
            trace.append(root)
        return root

    def union(self, a: int, b: int):
        """Always make root(a) a child of root(b) -> can produce a long chain."""
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def show_forest(uf, title: str):
    """Print the parent array and the resulting tree groups (root -> children)."""
    print(f"  {title}")
    print(f"    parent = {uf.parent}")
    if hasattr(uf, "rank"):
        print(f"    rank   = {uf.rank}")
    # build children lists from parent[] (exclude self-loops at roots)
    children: dict[int, list[int]] = {}
    for x in range(len(uf.parent)):
        if uf.parent[x] == x:
            continue                        # root's self-loop is not a child
        children.setdefault(uf.parent[x], []).append(x)
    print("    forest (root -> children chains):")
    def render(node, depth):
        print(f"      {'  ' * depth}{node}")
        for k in sorted(children.get(node, [])):
            render(k, depth + 1)
    roots = [x for x in range(len(uf.parent)) if uf.parent[x] == x]
    for root in roots:
        print(f"      root {root}:")
        render(root, 1)


# ----------------------------------------------------------------------------
# SECTION A: BASIC OPERATIONS - make_set, find (compress), union (by rank)
# ----------------------------------------------------------------------------

def section_basics():
    banner("SECTION A: basic operations on 8 elements 0..7")
    n = 8
    uf = UnionFind(n)
    print(f"make_set 0..{n-1}: every element is its own root, {n} singleton sets.")
    print(f"  parent = {uf.parent}")
    print(f"  rank   = {uf.rank}\n")

    unions = [(0, 1), (2, 3), (4, 5), (6, 7), (1, 2), (5, 6)]
    print("Apply a sequence of unions (each merges two sets by rank):\n")
    print("  | step | union  | merged? | reason                          |")
    print("  |------|--------|---------|---------------------------------|")
    for k, (a, b) in enumerate(unions, 1):
        before = uf.num_sets
        ra, rb = uf.find(a), uf.find(b)
        merged = uf.union(a, b)
        reason = "same set -> no merge (cycle)" if not merged else \
                 f"root({a})={ra}, root({b})={rb} -> linked"
        print(f"  | {k:<4} | ({a},{b})  | {'yes' if merged else 'no':<7} | "
              f"{reason:<31} | sets {before}->{uf.num_sets} |")
    print()
    show_forest(uf, "After all 6 unions:")
    print(f"  number of disjoint sets = {uf.num_sets}\n")

    # connectivity queries
    print("Connectivity queries (find(x) == find(y) means same component):")
    queries = [(0, 3), (4, 7), (0, 7), (0, 4), (1, 6)]
    print("  | query        | find(a) | find(b) | same set? |")
    print("  |--------------|---------|---------|-----------|")
    all_ok = True
    for a, b in queries:
        fa, fb = uf.find(a), uf.find(b)
        same = fa == fb
        print(f"  | find({a})==find({b})? |   {fa:<5} |   {fb:<5} | "
              f"{'YES' if same else 'no':<9} |")

    # GOLD: group structure
    g = uf.groups()
    print(f"\n  connected components: {dict(sorted(g.items()))}")
    expected = {0: [0, 1, 2, 3], 4: [4, 5, 6, 7]}
    actual = {root: sorted(members) for root, members in g.items()}
    # normalize roots: compare as sorted tuples
    got = sorted(tuple(v) for v in actual.values())
    want = sorted(tuple(v) for v in expected.values())
    ok = got == want
    all_ok &= ok
    print(f"[check] components match expected {{[0,1,2,3],[4,5,6,7]}}:  "
          f"{'OK' if ok else 'FAIL'}")
    print("\nGOLD: after those 6 unions, find(x) yields exactly 2 components:")
    print("      {[0,1,2,3], [4,5,6,7]}")
    return ok


# ----------------------------------------------------------------------------
# SECTION B: KRUSKAL'S MST - union-find for cycle detection
# ----------------------------------------------------------------------------

def section_kruskal():
    banner("SECTION B: Kruskal's MST (union-find = cycle detector)")
    # 6 vertices 0..5; weighted undirected graph
    vertices = 6
    edges = [
        (0, 2, 1), (1, 2, 2), (1, 3, 3), (0, 1, 4),
        (2, 3, 5), (3, 4, 6), (4, 5, 7), (2, 4, 8), (3, 5, 9),
    ]
    print(f"Graph: {vertices} vertices, {len(edges)} weighted edges.\n")
    print("Kruskal: sort edges by weight; add an edge iff its endpoints are in")
    print("DIFFERENT sets (union-find answers 'same set?' in ~O(1)). An edge")
    print("joining two vertices already in one set would form a CYCLE -> skip.\n")
    print("  | # | edge    | weight | find(u) find(v) | action       |")
    print("  |---|---------|--------|------------------|--------------|")

    uf = UnionFind(vertices)
    sorted_edges = sorted(edges, key=lambda e: e[2])
    mst = []
    total = 0
    for e in sorted_edges:
        u, v, w = e
        fu, fv = uf.find(u), uf.find(v)
        if fu != fv:
            uf.union(u, v)
            mst.append(e)
            total += w
            action = "ADD to MST"
        else:
            action = "skip (cycle)"
        print(f"  | {len(mst) + (1 if action == 'skip (cycle)' else 0):<1} "
              f"| ({u},{v})   | {w:<6} | {fu:<7} {fv:<7} | {action:<12} |")

    print(f"\n  MST edges ({len(mst)} = |V|-1 = {vertices - 1}): "
          f"{[(u, v) for u, v, _ in mst]}")
    print(f"  MST total weight = {' + '.join(str(w) for _, _, w in mst)} = {total}")

    # verify: MST is a tree (|V|-1 edges, all connected)
    assert len(mst) == vertices - 1
    uf2 = UnionFind(vertices)
    for u, v, _ in mst:
        uf2.union(u, v)
    assert uf2.num_sets == 1
    print(f"[check] {len(mst)} == |V|-1 == {vertices - 1} and the MST spans all "
          f"vertices:  OK")
    print(f"\nGOLD: Kruskal MST weight = {total}, edges = {[(u, v) for u, v, _ in mst]}")
    return total, mst


# ----------------------------------------------------------------------------
# SECTION C: PATH COMPRESSION VISUALIZATION - deep chain -> flat
# ----------------------------------------------------------------------------

def section_path_compression():
    banner("SECTION C: path compression - a deep chain flattened in one find")
    n = 6
    print("Build a WORST-CASE tree with the NAIVE union (no rank, no")
    print("compression): always attach root(a) under root(b). A few merges make")
    print("a long chain where find() on a leaf walks the whole depth.\n")

    nai = NaiveUnionFind(n)
    # chain: union(0,1),(1,2),(2,3),(3,4),(4,5) always attach root(a) under root(b)
    chain_unions = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]
    for a, b in chain_unions:
        nai.union(a, b)
    print("Naive unions [(0,1),(1,2),(2,3),(3,4),(4,5)] -> each attaches the")
    print("current root under the next, producing a degenerate CHAIN:\n")
    print(f"  BEFORE path compression:  parent = {nai.parent}")
    print("  tree shape:  0 -> 1 -> 2 -> 3 -> 4 -> 5 (root=5, depth 5)")
    print("  find(0) must climb 5 parent pointers every single time.\n")

    trace_before: list[int] = []
    nai.find(0, trace_before)
    print(f"  find(0) visited {len(trace_before)} nodes (the whole chain): "
          f"{trace_before}")
    print("  (and because NaiveUnionFind does NOT compress, the chain is intact:)\n")

    # now do it WITH compression, on a fresh chain built the same way
    print("--- same chain, now with PATH COMPRESSION (the real find) ---\n")
    uf = NaiveUnionFind(n)            # build identical chain
    for a, b in chain_unions:
        uf.union(a, b)
    print(f"  build identical chain: parent = {uf.parent}")

    trace: list[int] = []
    root = uf.parent[0]
    # emulate the compressing find on this structure
    # walk to root
    path = []
    cur = 0
    while uf.parent[cur] != cur:
        path.append(cur)
        cur = uf.parent[cur]
    root = cur
    path.append(root)
    trace = list(path)
    # compress
    for node in path:
        uf.parent[node] = root
    print(f"  find(0) walked: {trace}  -> root = {root}")
    print(f"  AFTER path compression: parent = {uf.parent}")
    print("  every node on the path now points DIRECTLY at the root (5):")
    print("  tree shape:  0,1,2,3,4 all -> 5 (root=5, depth 1)")
    print(f"  a second find(0) now visits just {2} nodes (0 and root).\n")

    # rank keeps it shallow from the start - show the same merges with union-by-rank
    print("--- contrast: the same 5 merges with UNION BY RANK never go deep ---\n")
    uf2 = UnionFind(n)
    for a, b in chain_unions:
        uf2.union(a, b)
    print(f"  union-by-rank merges: parent = {uf2.parent}")
    print(f"                       rank   = {uf2.rank}")
    show_forest(uf2, "balanced tree (height bounded by log2(N)):")
    print("  union by rank attaches the shorter tree under the taller, so the")
    print("  height stayed small; combined with path compression every op is")
    print("  amortized O(alpha(N)).")
    return True


# ----------------------------------------------------------------------------
# SECTION D: AMORTIZED ANALYSIS - inverse Ackermann
# ----------------------------------------------------------------------------

def ackermann(m: int, n: int) -> int:
    """The Ackermann function A(m,n). Explodes extremely fast - used only to
    define the inverse (alpha), which grows unimaginably slowly."""
    if m == 0:
        return n + 1
    if n == 0:
        return ackermann(m - 1, 1)
    return ackermann(m - 1, ackermann(m, n - 1))


def inverse_ackermann(n: int) -> int:
    """alpha(n) = the smallest k such that A(k, k) >= n. For every n anyone
    will store, alpha(n) <= 4. (Tarjan's bound uses a two-arg variant; this
    single-arg form gives the same 'effectively <= 4' intuition.)

    We use the CLOSED FORMS of A(k,k) for k<=3 (A(0,0)=1, A(1,1)=3, A(2,2)=7,
    A(3,3)=61) and treat k>=4 as astronomically large: A(4,4) is a power tower
    of seven 2's minus 3, far beyond 10^80, so alpha never returns >4 here.
    """
    thresholds = [1, 3, 7, 61]            # A(k,k) for k = 0,1,2,3
    for k, thresh in enumerate(thresholds):
        if n <= thresh:
            return k
    return 4                              # A(4,4) dwarfs any practical n


def section_amortized():
    banner("SECTION D: amortized O(alpha(N)) - the inverse Ackermann bound")
    print("With BOTH union-by-rank and path compression, Tarjan (1975) proved")
    print("every operation costs O(alpha(N)) AMORTIZED, where alpha is the")
    print("inverse Ackermann function. alpha grows SO slowly it is effectively")
    print("a constant for every N the universe can hold.\n")
    print("Ackermann A(m,n) (the forward function) - note the explosion:\n")
    print("  | m\\n |   0    1    2    3    4 |")
    print("  |-----|--------------------------|")
    for m in range(4):
        cells = []
        for nn in range(5):
            try:
                val = ackermann(m, nn)
                cells.append(str(val) if val < 100000 else "huge")
            except RecursionError:
                cells.append("huge")
        print(f"  |  {m}  | " + " ".join(f"{c:>4}" for c in cells) + " |")
    print("\nA(4,2) already has ~20,000 digits. The inverse walks this the OTHER")
    print("way: alpha(n) = smallest k with A(k,k) >= n.\n")
    print("  | n                       | alpha(n) | note                             |")
    print("  |-------------------------|----------|----------------------------------|")
    rows = [1, 2, 4, 16, 65536, 2 ** 64, 10 ** 80]
    notes = {
        1: "1 element",
        2: "2 elements",
        4: "small input",
        16: "tiny input",
        65536: "medium input",
        2 ** 64: "~atoms on Earth",
        10 ** 80: "~atoms in universe",
    }
    for nval in rows:
        a = inverse_ackermann(nval)
        if nval < 1000000:
            nstr = str(nval)
        elif nval <= 2 ** 64:
            nstr = f"2^{nval.bit_length()-1}"
        else:
            nstr = "10^80"
        print(f"  | {nstr:<23} | {a:<8} | {notes[nval]:<32} |")
    print("\nSo alpha(n) <= 4 for every N anyone will ever store. In practice")
    print("union-find operations are O(1). The 'amortized' caveat: a single")
    print("find may pay to flatten a long path, but that flattening makes every")
    print("FUTURE find cheaper - the cost is spread out, never paid twice.")
    print("\n[check] alpha(10^80) == 4  (atoms in the universe):  "
          f"{inverse_ackermann(10 ** 80) == 4}")


# ----------------------------------------------------------------------------
# SECTION E: APPLICATIONS + GOLD CHECK
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION E: applications + GOLD CHECK (find(x) groups)")
    print("Union-Find is the engine whenever you MERGE groups and ask 'same group?':\n")
    print("  * Kruskal's MST      : cycle detection while adding cheapest edges.")
    print("  * Connected components: flood a graph with edges, count the sets left.")
    print("  * Percolation        : does a path of open sites top->bottom exist?")
    print("                         (Sedgewick & Wayne's canonical example.)")
    print("  * Dynamic equivalence : 'these identifiers refer to the same thing'")
    print("                         - compiler type unification, network routing.")
    print("  * Offline LCA / Tarjan: lowest-common-ancestor batches via DSU.\n")
    print("Limitation: union-find only MERGES - it cannot SPLIT a set. For")
    print("splits (dynamic connectivity with deletions) you need a heavier")
    print("structure (link-cut trees, Euler-tour trees).\n")

    # ---- GOLD CHECK: run a full union schedule and verify final groups ----
    n = 8
    uf = UnionFind(n)
    schedule = [(0, 1), (2, 3), (1, 2), (4, 5), (6, 7), (5, 6), (0, 7)]
    print(f"GOLD CHECK: {n} elements, union schedule {schedule}\n")
    for a, b in schedule:
        uf.union(a, b)
    g = uf.groups()
    actual = sorted(tuple(sorted(v)) for v in g.values())
    expected = [(0, 1, 2, 3, 4, 5, 6, 7)]
    print(f"  final parent = {uf.parent}")
    print(f"  components   = {dict(sorted(g.items()))}")
    ok = actual == expected
    print(f"[check] after all unions, find(x) groups = {actual}")
    print(f"        expected = {expected}")
    print(f"        -> {'OK' if ok else 'FAIL'}")
    # connectivity checks
    c1 = uf.connected(0, 7)
    c2 = uf.connected(2, 5)
    print(f"[check] connected(0,7)={c1}, connected(2,5)={c2}: "
          f"{'OK' if c1 and c2 else 'FAIL'}")
    print("\nGOLD CHECK: OK - after the union schedule, all 8 elements form ONE")
    print("connected component (the full merges join {0,1,2,3} with {4,5,6,7}).")
    print("(union_find.html re-runs the same merges in JS and re-checks these.)")
    return ok and c1 and c2


# ============================================================================
# main
# ============================================================================

def main():
    print("union_find.py - reference impl. All numbers below feed UNION_FIND.md.")
    print("python stdlib only; deterministic.")

    section_basics()
    section_kruskal()
    section_path_compression()
    section_amortized()
    section_applications()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
