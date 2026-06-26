"""
union_find.py - Reference implementation of Union-Find (Disjoint Set Union) for:
  * Path compression + union by rank, component count  (P323 Connected Components)
  * Cycle detection via union's False return             (P684 Redundant Connection)
  * Two-pass == then != satisfiability                   (P990 Equality Equations)

This is the SINGLE SOURCE OF TRUTH for UNION_FIND.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 union_find.py > union_find_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - clubs with one boss, flattened on the way
============================================================================
Picture every element as a person, and every connected group as a club that
elects one BOSS (the root). Two questions are all you ever answer:

  find(x)   -> "who is the boss of x's club?"   (walk up parent links to root)
  union(x,y)-> "merge x's club and y's club"    (make one boss report to the other)

The trick that makes this fast is two cheap ideas applied together:

  PATH COMPRESSION (in find):  while walking up to the boss, re-point every
     person you pass straight at the boss. Next time any of them asks, it is
     one hop. The tree FLATTENS as you use it.
  UNION BY RANK (in union):    always attach the shorter tree under the taller
     one's boss, so the depth never grows quickly.

Together they drive every operation to amortized O(a(n)) -- the inverse
Ackermann function, which is <= 4 for any input that fits in the universe.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  representative / root  the boss of a club. parent[x] == x means x IS a root.
  parent[x]              x's immediate parent in the tree; roots point to self.
  rank[x]                an UPPER BOUND on the height of x's subtree (only
                         meaningful at roots). Grows only when two equal-rank
                         trees merge.
  find(x)                follow parent links up to the root; compress the path
                         on the way back. Returns the representative.
  union(x, y)            merge the clubs of x and y. Returns True if a merge
                         actually happened, False if they already shared a root
                         (this False IS free cycle detection).
  path compression       re-pointing each node on a find-path directly at the
                         root, flattening the tree.
  count / components      number of disjoint clubs. Starts at n; each
                         successful union decrements it by 1.
  1-indexed nodes        LeetCode (P684) labels nodes 1..n. Make the parent
                         array size n+1 and use node values directly as indices.

============================================================================
THE SKELETON (memorize find + union; both optimizations are required)
============================================================================
    class UnionFind:
        def __init__(self, n):
            self.parent = list(range(n))
            self.rank   = [0] * n
            self.count  = n                      # of disjoint components

        def find(self, x):                       # PATH COMPRESSION
            if self.parent[x] != x:
                self.parent[x] = self.find(self.parent[x])
            return self.parent[x]

        def union(self, x, y):                   # UNION BY RANK
            rx, ry = self.find(x), self.find(y)
            if rx == ry:
                return False                     # same club -> cycle detected
            if self.rank[rx] < self.rank[ry]:
                rx, ry = ry, rx                  # taller root becomes parent
            self.parent[ry] = rx
            if self.rank[rx] == self.rank[ry]:
                self.rank[rx] += 1               # rank grows only on a tie
            self.count -= 1
            return True
"""

from __future__ import annotations


# ============================================================================
# THE UNION-FIND CLASS (path compression + union by rank + component count)
# ============================================================================
class UnionFind:
    """Standard union-find: O(a(n)) amortized per operation with both opts."""

    def __init__(self, n: int) -> None:
        self.parent: list[int] = list(range(n))
        self.rank: list[int] = [0] * n
        self.count: int = n

    def find(self, x: int) -> int:
        """Representative of x's set, with full path compression."""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> bool:
        """Merge x's and y's sets. True if merged, False if already one set."""
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        self.count -= 1
        return True

    def connected(self, x: int, y: int) -> bool:
        return self.find(x) == self.find(y)


# ============================================================================
# INTERNAL: traced find (returns the root AND the path walked) so the printer
# and the HTML viz can show path compression flattening the tree.
# ============================================================================
def _find_with_path(parent: list[int], x: int) -> tuple[int, list[int]]:
    """Iterative find that returns (root, path_walked) and compresses in place."""
    path: list[int] = []
    node = x
    while parent[node] != node:
        path.append(node)
        node = parent[node]
    root = node
    for p in path:                       # path compression
        parent[p] = root
    return root, path


# ============================================================================
# TEMPLATE 1 - COMPONENT COUNT (P323 Number of Connected Components)
# ============================================================================
def count_components(n: int, edges: list[list[int]]) -> int:
    """Number of connected components in an undirected graph.

    Initialize UnionFind(n), union every edge, return the surviving count.
    Time: O(n + E * a(n)), Space: O(n).
    """
    uf = UnionFind(n)
    for u, v in edges:
        uf.union(u, v)
    return uf.count


def trace_count_components(n: int, edges: list[list[int]]) -> list[dict]:
    events: list[dict] = []
    parent = list(range(n))
    rank = [0] * n
    count = n
    for u, v in edges:
        ru, pu = _find_with_path(parent, u)
        rv, pv = _find_with_path(parent, v)
        if pu and len(pu) > 1:
            events.append({"kind": "compress", "parent": parent[:],
                           "path": pu[:], "root": ru,
                           "note": (f"path compression on find({u}): "
                                    f"flatten {pu} -> all point to root {ru}")})
        if ru == rv:
            events.append({"kind": "reject", "u": u, "v": v, "root": ru,
                           "parent": parent[:], "rank": rank[:], "count": count,
                           "note": (f"union({u},{v}): find({u})={ru}, find({v})={rv} "
                                    f"-- SAME root, already one component (no-op)")})
            continue
        if rank[ru] < rank[rv]:
            ru, rv = rv, ru
        parent[rv] = ru
        grew = ""
        if rank[ru] == rank[rv]:
            rank[ru] += 1
            grew = f", rank[{ru}]++ -> {rank[ru]}"
        count -= 1
        events.append({"kind": "merge", "u": u, "v": v, "root": ru, "child": rv,
                       "parent": parent[:], "rank": rank[:], "count": count,
                       "note": (f"union({u},{v}): find({u})={ru}, find({v})={rv} "
                                f"-- MERGE: parent[{rv}]={ru}{grew}   "
                                f"components {count + 1} -> {count}")})
    events.append({"kind": "done", "count": count, "parent": parent[:],
                   "note": f"done: {count} connected component(s) remain"})
    return events


# ============================================================================
# TEMPLATE 2 - CYCLE DETECTION (P684 Redundant Connection)
# ============================================================================
def redundant_connection(edges: list[list[int]]) -> list[int]:
    """The first edge that connects two already-connected nodes (1-indexed).

    union(u, v) returns False exactly when u and v share a root -- adding this
    edge would close a cycle. Return that edge. Time O(E * a(n)), Space O(n).
    """
    n = len(edges)
    uf = UnionFind(n + 1)                 # 1-indexed nodes 1..n
    for u, v in edges:
        if not uf.union(u, v):
            return [u, v]
    return []                             # unreachable: input always has 1 cycle


def trace_redundant_connection(edges: list[list[int]]) -> list[dict]:
    events: list[dict] = []
    n = len(edges)
    parent = list(range(n + 1))
    rank = [0] * (n + 1)
    answer: list[int] = []
    for u, v in edges:
        ru, pu = _find_with_path(parent, u)
        rv, pv = _find_with_path(parent, v)
        if ru == rv:
            answer = [u, v]
            events.append({"kind": "reject", "u": u, "v": v, "root": ru,
                           "parent": parent[:], "answer": answer,
                           "note": (f"union({u},{v}): find({u})={ru}, find({v})={rv} "
                                    f"-- SAME root! This edge is REDUNDANT "
                                    f"(closes a cycle) -> return {answer}")})
            break
        if rank[ru] < rank[rv]:
            ru, rv = rv, ru
        parent[rv] = ru
        grew = ""
        if rank[ru] == rank[rv]:
            rank[ru] += 1
            grew = f", rank[{ru}]++ -> {rank[ru]}"
        events.append({"kind": "merge", "u": u, "v": v, "root": ru, "child": rv,
                       "parent": parent[:], "answer": None,
                       "note": (f"union({u},{v}): find({u})={ru}, find({v})={rv} "
                                f"-- MERGE: parent[{rv}]={ru}{grew}")})
    events.append({"kind": "done", "answer": answer,
                   "note": (f"redundant edge = {answer}" if answer else "no cycle found")})
    return events


# ============================================================================
# TEMPLATE 3 - EQUALITY SATISFIABILITY (P990 Satisfiability of Equality Eqns)
# ============================================================================
def _var(ch: str) -> int:
    """Map a lower-case variable to 0..25."""
    return ord(ch) - ord("a")


def equations_possible(equations: list[str]) -> bool:
    """Can all '==' and '!=' equations over variables a-z hold at once?

    Two passes: union every '==' first (build the clubs), THEN test every '!='
    (a != b is violated iff find(a) == find(b)). Interleaving the passes fails.
    Time O(N * a(26)) ~= O(N), Space O(26) = O(1).
    """
    uf = UnionFind(26)
    for eq in equations:                  # pass 1: all equalities
        if eq[1] == "=":
            uf.union(_var(eq[0]), _var(eq[3]))
    for eq in equations:                  # pass 2: all inequalities
        if eq[1] == "!":
            if uf.connected(_var(eq[0]), _var(eq[3])):
                return False
    return True


def trace_equations(equations: list[str]) -> list[dict]:
    events: list[dict] = []
    parent = list(range(26))
    rank = [0] * 26
    possible = True
    events.append({"kind": "phase", "parent": parent[:],
                   "note": "PASS 1 -- process every '==' equation (build clubs)"})
    for eq in equations:
        a, b = _var(eq[0]), _var(eq[3])
        if eq[1] == "=":
            ra, _ = _find_with_path(parent, a)
            rb, _ = _find_with_path(parent, b)
            if ra == rb:
                events.append({"kind": "reject", "parent": parent[:],
                               "note": (f"{eq}: '{eq[0]}' root {ra} == '{eq[3]}' root "
                                        f"{rb} -- already same club")})
                continue
            if rank[ra] < rank[rb]:
                ra, rb = rb, ra
            parent[rb] = ra
            grew = ""
            if rank[ra] == rank[rb]:
                rank[ra] += 1
                grew = f", rank[{ra}]++"
            events.append({"kind": "merge", "parent": parent[:],
                           "note": (f"{eq}: union('{eq[0]}','{eq[3]}') -> "
                                    f"parent[{rb}]={ra}{grew}")})
    events.append({"kind": "phase", "parent": parent[:],
                   "note": "PASS 2 -- verify every '!=' equation (no contradictions)"})
    for eq in equations:
        a, b = _var(eq[0]), _var(eq[3])
        if eq[1] == "!":
            ra, _ = _find_with_path(parent, a)
            rb, _ = _find_with_path(parent, b)
            if ra == rb:
                possible = False
                events.append({"kind": "reject", "parent": parent[:],
                               "note": (f"{eq}: '{eq[0]}' root {ra} == '{eq[3]}' root "
                                        f"{rb} -- but they must DIFFER -> CONTRADICTION "
                                        f"-> return False")})
                break
            events.append({"kind": "check", "parent": parent[:],
                           "note": (f"{eq}: '{eq[0]}' root {ra} != '{eq[3]}' root "
                                    f"{rb} -- OK (different clubs)")})
    events.append({"kind": "done", "answer": possible,
                   "note": f"result = {'true' if possible else 'false'}"})
    return events


# ============================================================================
# EVENT PRINTER (shared by all sections)
# ============================================================================
_KIND_MARKER = {
    "merge":    "[+]",   # a union merged two components
    "reject":   "[x]",   # same root: cycle / no-op / contradiction
    "check":    "[.]",   # inequality verified OK
    "compress": "[~]",   # path compression flattened a find-path
    "phase":    "[#]",   # pass boundary (P990)
    "done":     "[=]",   # final result
}


def print_events(events: list[dict]) -> None:
    for e in events:
        marker = _KIND_MARKER.get(e["kind"], "[?]")
        print(f"  {marker} {e['note']}")


def summarize_events(events: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


def fmt_parent(parent: list[int]) -> str:
    """Compact parent-array dump: 'idx->p' for nodes whose parent changed."""
    return "[" + ", ".join(f"{i}->{parent[i]}" for i in range(len(parent))) + "]"


# ============================================================================
# SECTION A - P323 NUMBER OF CONNECTED COMPONENTS (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P323 Number of Connected Components  (count = n - merges)")
    print("=" * 72)
    print()
    n, edges = 5, [[0, 1], [2, 3], [3, 4]]
    print(f"n = {n}   edges = {edges}   (how many connected components?)")
    print()
    print("Union every edge. count starts at n; each SUCCESSFUL union decrements")
    print("it by 1. find() uses path compression; union() attaches by rank.")
    print()
    print("Trace (each merge shrinks the component count by 1):")
    print()
    events = trace_count_components(n, edges)
    print_events(events)
    print()
    result = count_components(n, edges)
    print(f"count_components({n}, {edges}) -> {result}")
    print()
    print("--- edge cases ---")
    print(f"  n=4, [[0,1],[2,3]]        -> {count_components(4, [[0,1],[2,3]])}  (two pairs)")
    print(f"  n=5, [[0,1],[1,2],[2,3],[3,4]] -> {count_components(5, [[0,1],[1,2],[2,3],[3,4]])}  (one chain)")
    print(f"  n=3, []                   -> {count_components(3, [])}  (no edges: every node its own)")
    print()


# ============================================================================
# SECTION B - P684 REDUNDANT CONNECTION (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P684 Redundant Connection  (cycle = union returns False)")
    print("=" * 72)
    print()
    edges = [[1, 2], [1, 3], [2, 3]]
    print(f"edges = {edges}   (1-indexed; find the first edge that closes a cycle)")
    print()
    print("union(u, v) returns False EXACTLY when find(u) == find(v): adding that")
    print("edge would link two nodes already in one component -> a cycle. Nodes are")
    print("1-indexed, so the parent array is sized n+1.")
    print()
    print("Trace (stop at the first [x] -- that edge is the answer):")
    print()
    events = trace_redundant_connection(edges)
    print_events(events)
    print()
    result = redundant_connection(edges)
    print(f"redundant_connection({edges}) -> {result}")
    print()
    print("--- edge cases ---")
    e2 = [[1, 2], [2, 3], [3, 4], [1, 4], [1, 5]]
    print(f"  {e2} -> {redundant_connection(e2)}  "
          f"(1-2-3-4 chain first, then 1-4 closes the cycle)")
    print()


# ============================================================================
# SECTION C - P990 SATISFIABILITY OF EQUALITY EQUATIONS (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P990 Satisfiability of Equality Equations  (== then !=)")
    print("=" * 72)
    print()
    equations = ["a==b", "b==c", "a!=c"]
    print(f"equations = {equations}   (can all of these hold simultaneously?)")
    print()
    print("Two passes are MANDATORY. Pass 1 unions every '==' to build the clubs")
    print("(transitivity: a==b and b==c puts a,b,c in one group). Pass 2 checks")
    print("every '!=' -- it is violated iff the two variables share a root.")
    print("Interleaving the passes (checking != before all == are applied) fails.")
    print()
    print("Trace (pass 1 builds clubs, pass 2 catches the contradiction):")
    print()
    events = trace_equations(equations)
    print_events(events)
    print()
    result = equations_possible(equations)
    print(f"equations_possible({equations}) -> {result}   "
          f"(a,b,c all forced equal, yet a!=c demanded -> impossible)")
    print()
    print("--- edge cases ---")
    print(f"  ['a==b','b!=a']      -> {equations_possible(['a==b','b!=a'])}  "
          f"(a==b then b!=a directly contradicts)")
    print(f"  ['b==a','a==b']      -> {equations_possible(['b==a','a==b'])}   "
          f"(no '!=' at all -> trivially satisfiable)")
    print(f"  ['c==c','b==d','x!=z']-> {equations_possible(['c==c','b==d','x!=z'])}   "
          f"(b~d group; x,z never unioned -> x!=z is fine)")
    print(f"  ['a!=a']             -> {equations_possible(['a!=a'])}  "
          f"(a can never differ from itself)")
    print()


# ============================================================================
# SECTION D - COMPLEXITY, GOTCHAS, PROBLEM TABLE
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Implementation                      find/union      Space")
    print("  ----------------------------------- --------------- --------")
    print("  Naive (no optimizations)            O(n)            O(n)")
    print("  Union by rank only                  O(log n)        O(n)")
    print("  Path compression only               O(a(n)) amort.  O(n)")
    print("  BOTH (path comp + union by rank)    O(a(n)) amort.  O(n)")
    print()
    print("  a(n) = inverse Ackermann; <= 4 for any practical n (even 10^80).")
    print("  So 'effectively O(1)' per operation when both optimizations are on.")
    print()
    print("The skeleton (memorize find + union; BOTH optimizations required)")
    print("----------------------------------------------------------------")
    print("  class UnionFind:")
    print("      def __init__(self, n):")
    print("          self.parent = list(range(n))")
    print("          self.rank   = [0]*n")
    print("          self.count  = n")
    print("      def find(self, x):                       # PATH COMPRESSION")
    print("          if self.parent[x] != x:")
    print("              self.parent[x] = self.find(self.parent[x])")
    print("          return self.parent[x]")
    print("      def union(self, x, y):                   # UNION BY RANK")
    print("          rx, ry = self.find(x), self.find(y)")
    print("          if rx == ry: return False            # cycle / no-op")
    print("          if self.rank[rx] < self.rank[ry]: rx, ry = ry, rx")
    print("          self.parent[ry] = rx")
    print("          if self.rank[rx] == self.rank[ry]: self.rank[rx] += 1")
    print("          self.count -= 1")
    print("          return True")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. BOTH OPTIMIZATIONS. Path compression is one line in find; union")
    print("     by rank is one comparison in union. Implement either alone and you")
    print("     get O(log n) or worse instead of O(a(n)). Interviewers expect both.")
    print("  2. RANK GROWS ONLY ON A TIE. self.rank[rx] += 1 happens ONLY when the")
    print("     two roots have EQUAL rank. Incrementing on every union is wrong.")
    print("  3. 1-INDEXED NODES (P684). Nodes labeled 1..n -> parent size n+1,")
    print("     initialized list(range(n+1)). Off-by-one here is a silent bug.")
    print("  4. COUNT IS MAINTAINED, NOT DERIVED. num_components starts at n and")
    print("     decrements ONLY on a successful union (union returned True).")
    print("  5. TWO PASSES FOR EQUATIONS (P990). Union ALL '==' first, THEN check")
    print("     '!='. Interleaving fails because a later '==' can join two groups")
    print("     whose '!=' you already (wrongly) approved.")
    print("  6. UNDIRECTED ONLY. union(x,y) is symmetric -- it cannot model a")
    print("     directed edge. For directed cycle detection / topo-sort use DFS")
    print("     with coloring instead.")
    print("  7. DSU vs BFS/DFS. Use DSU when edges arrive INCREMENTALLY and you")
    print("     query connectivity between additions. For a static graph with one")
    print("     connectivity question, plain BFS/DFS is simpler.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                       Diff  Key trick")
    print("  ----------------------------- ----  ----------------------------------------")
    print("  P323 Connected Components     Med   count = n - (#successful unions)")
    print("  P684 Redundant Connection     Med   1-indexed (size n+1); first union->False")
    print("  P990 Equality Equations       Med   pass1 union all ==, pass2 check !=")
    print("  P547 Number of Provinces      Med   count remaining roots after unions")
    print("  P261 Graph Valid Tree         Med   n-1 edges AND fully connected (no cycle)")
    print("  P721 Accounts Merge           Med   map emails->int IDs; union within account")
    print("  P200 Number of Islands (DSU)  Med   DSU wins when land cells added online")
    print("  P1202 Smallest String Swaps   Med   group indices by component, sort each group")
    print("  P1584 Min Cost Connect Points  Med   Kruskal: sort edges, union until n-1 merges")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions (mirror LeetCode canonical test cases) ----
    # P323 Number of Connected Components
    assert count_components(5, [[0, 1], [2, 3], [3, 4]]) == 2
    assert count_components(4, [[0, 1], [2, 3]]) == 2
    assert count_components(5, [[0, 1], [1, 2], [2, 3], [3, 4]]) == 1
    assert count_components(3, []) == 3

    # P684 Redundant Connection (1-indexed)
    assert redundant_connection([[1, 2], [1, 3], [2, 3]]) == [2, 3]
    assert redundant_connection([[1, 2], [2, 3], [3, 4], [1, 4], [1, 5]]) == [1, 4]

    # P990 Satisfiability of Equality Equations
    assert equations_possible(["a==b", "b!=a"]) is False
    assert equations_possible(["b==a", "a==b"]) is True
    assert equations_possible(["a==b", "b==c", "a!=c"]) is False
    assert equations_possible(["c==c", "b==d", "x!=z"]) is True
    assert equations_possible(["a!=a"]) is False

    # ---- cross-check: trace component count matches the real function ----
    for n, edges in [(5, [[0, 1], [2, 3], [3, 4]]), (3, []), (4, [[0, 1], [2, 3]])]:
        ev = trace_count_components(n, edges)
        done = [e for e in ev if e["kind"] == "done"][0]
        assert done["count"] == count_components(n, edges)

    # ---- cross-check: every node's representative is reachable & stable ----
    uf = UnionFind(10)
    for u, v in [[0, 1], [2, 3], [3, 4], [1, 4]]:
        uf.union(u, v)
    assert uf.count == 10 - 4               # 4 successful merges
    assert uf.connected(0, 4) is True
    assert uf.connected(0, 5) is False

    print("=" * 72)
    print("[check] count_components / redundant_connection / equations_possible ... OK")
    print("=" * 72)
