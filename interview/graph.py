"""
graph.py - Reference implementation of the Graph pattern (topological sort,
cycle detection, degree arithmetic) for:
  * Kahn's topological sort (BFS in-degree peeling)  (P210 Course Schedule II)
  * 3-state DFS cycle detection (WHITE/GRAY/BLACK)    (P207 Course Schedule)
  * Net-degree score (trusted minus trusting)          (P997 Town Judge)

This is the SINGLE SOURCE OF TRUTH for GRAPH.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 graph.py > graph_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - a to-do list, and an election
============================================================================
A graph connects things. Two flavors of interview problem live here:

  1. ORDERING problems ("can I finish all my courses?", "give a build order"):
     think of a to-do list where some tasks MUST come before others. If Task A
     needs Task B and Task B needs Task A, you are stuck in a CIRCLE = a cycle,
     and no valid order exists. Peeling off "ready" tasks (zero prerequisites)
     one layer at a time is TOPOLOGICAL SORT (Kahn's algorithm).

  2. "SPECIAL NODE" problems ("find the town judge", "find the center"):
     think of an election. The judge is trusted by everyone and trusts nobody.
     You do NOT walk the graph - you just COUNT. One pass over the edges,
     +1 for being trusted, -1 for trusting; the judge's net score is N-1.

The two flavors are solved by two completely different tricks:
  - ordering  -> repeatedly delete zero-in-degree nodes (Kahn's BFS)
  - special   -> one pass of degree arithmetic (no traversal at all)

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  directed edge u -> v   an arrow FROM u TO v. u is the source/tail,
                         v is the destination/head. Prerequisite [a, b]
                         ("b before a") means edge b -> a.
  in-degree (of v)        how many arrows point INTO v = how many things v
                         must wait for. A course with in-degree 0 is READY.
  out-degree (of v)       how many arrows leave v = how many things depend
                         on v / how many people v trusts.
  DAG                    Directed Acyclic Graph. A graph with NO cycles.
                         ONLY a DAG has a topological order.
  topological order      a linear listing where every edge u -> v puts u
                         BEFORE v. If the list has < n nodes, a cycle exists.
  cycle                  a path that returns to its start (A->B->C->A).
                         Nothing in a cycle can ever have in-degree 0, so
                         Kahn's never dequeues cycle members.
  3-state coloring       WHITE = never visited, GRAY = on the current DFS
                         path (visiting), BLACK = fully explored (visited).
                         Hitting a GRAY node = back edge = cycle.
  net degree score       in-degree MINUS out-degree. The judge has score
                         N-1 (trusted by all N-1 others, trusts nobody).

============================================================================
THE SKELETONS (three independent templates)
============================================================================
    # --- 1. Kahn's topological sort (BFS) ---
    from collections import deque
    def topo_sort(n, edges):
        graph = {i: [] for i in range(n)}
        in_degree = [0] * n
        for u, v in edges:          # edge u -> v
            graph[u].append(v)
            in_degree[v] += 1
        queue = deque(i for i in range(n) if in_degree[i] == 0)
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for nei in graph[node]:
                in_degree[nei] -= 1
                if in_degree[nei] == 0:
                    queue.append(nei)
        return order            # len(order) < n  ==>  cycle exists

    # --- 2. 3-state DFS cycle detection ---
    def has_cycle(n, edges):
        graph = {i: [] for i in range(n)}
        for u, v in edges:
            graph[u].append(v)
        WHITE, GRAY, BLACK = 0, 1, 2
        color = [WHITE] * n
        def dfs(node):
            color[node] = GRAY
            for nei in graph[node]:
                if color[nei] == GRAY:   return True   # back edge -> cycle
                if color[nei] == WHITE and dfs(nei): return True
            color[node] = BLACK
            return False
        return any(dfs(i) for i in range(n) if color[i] == WHITE)

    # --- 3. Net-degree score (Town Judge) ---
    def find_special_node(n, edges):       # 1-indexed
        score = [0] * (n + 1)
        for u, v in edges:                  # u -> v  (u trusts v)
            score[u] -= 1                   # u points out (trusts someone)
            score[v] += 1                   # v is pointed to (is trusted)
        for i in range(1, n + 1):
            if score[i] == n - 1:
                return i
        return -1
"""

from __future__ import annotations

from collections import deque


# ============================================================================
# TEMPLATE 1 - KAHN'S TOPOLOGICAL SORT (BFS in-degree peeling)
# ============================================================================
def topological_sort(n: int, edges: list[tuple[int, int]]) -> list[int]:
    """Return a topological ordering of a DAG using Kahn's algorithm.

    `edges` are directed as (u, v) meaning u -> v. If the result has fewer
    than n nodes, the graph contains a cycle and no valid order exists.

    Time:  O(V + E),  Space: O(V)
    """
    graph: dict[int, list[int]] = {i: [] for i in range(n)}
    in_degree: list[int] = [0] * n
    for u, v in edges:                     # edge u -> v
        graph[u].append(v)
        in_degree[v] += 1

    queue: deque[int] = deque(i for i in range(n) if in_degree[i] == 0)
    order: list[int] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return order                           # len(order) < n  ==>  cycle


def trace_topological_sort(n: int, edges: list[tuple[int, int]]) -> list[dict]:
    """Capture Kahn's algorithm as a flat event list for the printer/viz.

    Events: 'init' (show in-degrees), 'enqueue' (node becomes ready),
            'dequeue' (process a node, append to order), 'decrement'
            (a neighbor's in-degree drops), 'ready' (neighbor hits 0, enqueue),
            'done' (queue empty -> report order length / cycle).
    """
    events: list[dict] = []
    graph: dict[int, list[int]] = {i: [] for i in range(n)}
    in_degree: list[int] = [0] * n
    for u, v in edges:
        graph[u].append(v)
        in_degree[v] += 1
    events.append({
        "kind": "init", "order": [], "queue": [],
        "in_degree": in_degree[:],
        "note": f"in-degree = {in_degree}",
    })

    queue: deque[int] = deque(i for i in range(n) if in_degree[i] == 0)
    events.append({
        "kind": "enqueue", "order": [], "queue": list(queue),
        "in_degree": in_degree[:], "node": None,
        "note": f"seed queue with in-degree-0 nodes: {list(queue)}",
    })

    order: list[int] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        events.append({
            "kind": "dequeue", "order": order[:], "queue": list(queue),
            "in_degree": in_degree[:], "node": node,
            "note": f"dequeue {node}, append -> order={order}",
        })
        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
                events.append({
                    "kind": "ready", "order": order[:], "queue": list(queue),
                    "in_degree": in_degree[:], "node": neighbor,
                    "note": f"  {node}->{neighbor}: in-degree -> 0, enqueue {neighbor}",
                })
            else:
                events.append({
                    "kind": "decrement", "order": order[:], "queue": list(queue),
                    "in_degree": in_degree[:], "node": neighbor,
                    "note": f"  {node}->{neighbor}: in-degree -> {in_degree[neighbor]}",
                })

    cyclic = len(order) < n
    events.append({
        "kind": "done", "order": order[:], "queue": [], "node": None,
        "in_degree": in_degree[:],
        "note": (f"order has {len(order)}/{n} nodes -> CYCLE (no valid order)"
                 if cyclic else f"order has {len(order)}/{n} nodes -> valid DAG"),
    })
    return events


# ============================================================================
# TEMPLATE 2 - 3-STATE DFS CYCLE DETECTION (WHITE / GRAY / BLACK)
# ============================================================================
WHITE, GRAY, BLACK = 0, 1, 2


def has_cycle_dfs(n: int, edges: list[tuple[int, int]]) -> bool:
    """Detect a cycle in a directed graph using 3-state coloring DFS.

    WHITE = unvisited, GRAY = on the current recursion path (visiting),
    BLACK = fully explored. Encountering a GRAY node is a back edge = cycle.

    Time:  O(V + E),  Space: O(V)
    """
    graph: dict[int, list[int]] = {i: [] for i in range(n)}
    for u, v in edges:
        graph[u].append(v)
    state: list[int] = [WHITE] * n

    def dfs(node: int) -> bool:
        state[node] = GRAY
        for neighbor in graph[node]:
            if state[neighbor] == GRAY:           # back edge -> cycle
                return True
            if state[neighbor] == WHITE and dfs(neighbor):
                return True
        state[node] = BLACK
        return False

    for i in range(n):
        if state[i] == WHITE and dfs(i):
            return True
    return False


def trace_cycle_dfs(n: int, edges: list[tuple[int, int]]) -> list[dict]:
    """Capture 3-state DFS as an event list. Stops at the first back edge."""
    events: list[dict] = []
    graph: dict[int, list[int]] = {i: [] for i in range(n)}
    for u, v in edges:
        graph[u].append(v)
    state: list[int] = [WHITE] * n
    events.append({
        "kind": "init", "state": state[:], "depth": 0, "node": None,
        "note": f"all nodes WHITE {[WHITE]*n}",
    })

    def dfs(node: int, depth: int) -> bool:
        state[node] = GRAY
        events.append({
            "kind": "enter", "state": state[:], "node": node, "depth": depth,
            "note": f"{'  '*depth}enter {node}: WHITE -> GRAY (on path)",
        })
        for neighbor in graph[node]:
            if state[neighbor] == GRAY:
                events.append({
                    "kind": "back", "state": state[:], "node": neighbor,
                    "depth": depth + 1,
                    "note": (f"{'  '*depth}{node}->{neighbor}: {neighbor} is GRAY "
                             f"=> BACK EDGE => CYCLE! return True"),
                })
                return True
            if state[neighbor] == WHITE:
                if dfs(neighbor, depth + 1):
                    return True
            else:
                events.append({
                    "kind": "skip", "state": state[:], "node": neighbor,
                    "depth": depth + 1,
                    "note": f"{'  '*depth}{node}->{neighbor}: BLACK (done), skip",
                })
        state[node] = BLACK
        events.append({
            "kind": "done", "state": state[:], "node": node, "depth": depth,
            "note": f"{'  '*depth}leave {node}: GRAY -> BLACK (done)",
        })
        return False

    cyclic = False
    for i in range(n):
        if state[i] == WHITE:
            events.append({
                "kind": "root", "state": state[:], "node": i, "depth": 0,
                "note": f"new DFS root {i} (still WHITE)",
            })
            if dfs(i, 0):
                cyclic = True
                break
    events.append({
        "kind": "result", "state": state[:], "node": None, "depth": 0,
        "note": f"=> has_cycle = {cyclic}",
    })
    return events


# ============================================================================
# TEMPLATE 3 - NET-DEGREE SCORE (Town Judge)
# ============================================================================
def find_judge(n: int, trust: list[list[int]]) -> int:
    """Find the town judge, or -1. Nodes are 1-indexed (1..n).

    The judge is trusted by EVERYONE else (in-degree n-1) and trusts NOBODY
    (out-degree 0), so net score = (n-1) - 0 = n-1. One pass over edges.

    Time:  O(n + E),  Space: O(n)
    """
    score: list[int] = [0] * (n + 1)       # 1-indexed; index 0 unused
    for u, v in trust:                     # u trusts v  =>  edge u -> v
        score[u] -= 1                      # u points out (it trusts someone)
        score[v] += 1                      # v is pointed to (it is trusted)
    for i in range(1, n + 1):
        if score[i] == n - 1:
            return i
    return -1


def trace_find_judge(n: int, trust: list[list[int]]) -> list[dict]:
    """Capture the net-degree scan as an event list."""
    events: list[dict] = []
    score: list[int] = [0] * (n + 1)
    events.append({
        "kind": "init", "score": score[:],
        "note": f"score = {[0]*(n+1)}  (+1 trusted, -1 trusting)",
    })
    for u, v in trust:
        score[u] -= 1
        score[v] += 1
        events.append({
            "kind": "trust", "score": score[:], "u": u, "v": v,
            "note": f"{u} trusts {v}:  score[{u}]-- -> {score[u]},  score[{v}]++ -> {score[v]}",
        })
    judge = -1
    for i in range(1, n + 1):
        hit = score[i] == n - 1
        events.append({
            "kind": "scan", "score": score[:], "node": i, "hit": hit,
            "note": f"score[{i}]={score[i]} {'== n-1=' + str(n-1) + ' => JUDGE' if hit else '!= ' + str(n-1)}",
        })
        if hit and judge == -1:
            judge = i
    events.append({
        "kind": "result", "score": score[:], "judge": judge,
        "note": f"=> judge = {judge}",
    })
    return events


# ============================================================================
# EVENT PRINTER (shared by all sections)
# ============================================================================
def print_events(events: list[dict]) -> None:
    for e in events:
        marker = _KIND_MARKER.get(e["kind"], "[?]")
        print(f"  {marker} {e['note']}")


_KIND_MARKER = {
    "init":      "[.]",   # setup
    "enqueue":   "[>]",   # added to queue / seeded
    "dequeue":   "[o]",   # processed (popped, appended to order)
    "decrement": "[ ]",   # in-degree dropped but not to 0
    "ready":     "[+]",   # in-degree hit 0, enqueued
    "done":      "[=]",   # algorithm finished
    "enter":     "[>]",   # DFS enter (WHITE->GRAY)
    "back":      "[!]",   # back edge found (cycle!)
    "skip":      "[ ]",   # neighbor already BLACK
    "root":      "[*]",   # new DFS root
    "result":    "[=]",
    "trust":     "[+]",   # an edge applied
    "scan":      "[ ]",   # scanning a node's score
}


# ============================================================================
# SECTION A - P207 COURSE SCHEDULE (cycle detection via Kahn's AND 3-state DFS)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P207 Course Schedule  (can you finish all courses?)")
    print("=" * 72)
    print()
    print("Problem: numCourses courses labelled 0..n-1; prerequisites[i] = [a, b]")
    print("means you must take b BEFORE a (edge b -> a). Return True if you can")
    print("finish ALL courses, i.e. if the prerequisite graph is a DAG (no cycle).")
    print()
    print("Two equivalent cycle detectors: Kahn's (len(order)==n?) and 3-state DFS.")
    print()

    # --- Example 1: a clean DAG ---
    n1 = 4
    pre1 = [[1, 0], [2, 0], [3, 1], [3, 2]]   # 0 is base; 1,2 need 0; 3 needs 1,2
    edges1 = [(b, a) for a, b in pre1]         # convert [a,b] -> edge b->a
    print(f"Example 1 (DAG): numCourses={n1}, prerequisites={pre1}")
    print(f"  -> directed edges (prereq -> course): {edges1}")
    print()
    print("Kahn's trace (peel zero-in-degree nodes layer by layer):")
    print()
    ev = trace_topological_sort(n1, edges1)
    print_events(ev)
    order1 = topological_sort(n1, edges1)
    print()
    print(f"  order={order1}, len={len(order1)} == n={n1}  ->  canFinish = True")
    print(f"  canFinish({n1}, {pre1}) = {can_finish(n1, pre1)}")
    print()

    # --- Example 2: a cycle ---
    n2 = 3
    pre2 = [[0, 1], [1, 2], [2, 0]]            # 1->0, 2->1, 0->2  (0->2->1->0)
    edges2 = [(b, a) for a, b in pre2]
    print(f"Example 2 (CYCLE): numCourses={n2}, prerequisites={pre2}")
    print(f"  -> directed edges: {edges2}   (0 -> 2 -> 1 -> 0, a ring)")
    print()
    print("Kahn's trace (every node has in-degree 1, queue never seeds):")
    print()
    ev = trace_topological_sort(n2, edges2)
    print_events(ev)
    order2 = topological_sort(n2, edges2)
    print()
    print(f"  order={order2}, len={len(order2)} < n={n2}  ->  canFinish = False")
    print(f"  canFinish({n2}, {pre2}) = {can_finish(n2, pre2)}")
    print()

    # --- Same cycle, shown via 3-state DFS ---
    print("Same cycle via 3-state DFS (GRAY node hit = back edge = cycle):")
    print()
    ev = trace_cycle_dfs(n2, edges2)
    print_events(ev)
    print()
    print(f"  has_cycle_dfs({n2}, {edges2}) = {has_cycle_dfs(n2, edges2)}")
    print()
    print("--- edge cases ---")
    print(f"  canFinish(2, [[1,0]])          = {can_finish(2, [[1,0]])}      "
          f"(0 before 1, no cycle)")
    print(f"  canFinish(1, [])               = {can_finish(1, [])}      "
          f"(one course, no prereqs, trivially finishable)")
    print(f"  canFinish(2, [[1,0],[0,1]])    = {can_finish(2, [[1,0],[0,1]])}     "
          f"(0 before 1 AND 1 before 0 = 2-cycle)")
    print()


def can_finish(num_courses: int, prerequisites: list[list[int]]) -> bool:
    """P207: True iff all courses can be finished (graph is a DAG)."""
    edges = [(b, a) for a, b in prerequisites]      # [a,b] "b before a" -> b->a
    order = topological_sort(num_courses, edges)
    return len(order) == num_courses


# ============================================================================
# SECTION B - P210 COURSE SCHEDULE II (return a valid ordering)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P210 Course Schedule II  (return a valid ordering)")
    print("=" * 72)
    print()
    print("Problem: same setup as P207, but RETURN any valid course order. If a")
    print("cycle makes it impossible, return []. Same Kahn's algorithm; we just")
    print("hand back the order list (or [] when len(order) < n).")
    print()

    n = 4
    pre = [[1, 0], [2, 0], [3, 1], [3, 2]]
    edges = [(b, a) for a, b in pre]
    print(f"Example: numCourses={n}, prerequisites={pre}")
    print(f"  -> directed edges: {edges}")
    print()
    print("Kahn's trace (order is built as nodes become ready):")
    print()
    ev = trace_topological_sort(n, edges)
    print_events(ev)
    order = find_order(n, pre)
    print()
    print(f"  findOrder({n}, {pre}) = {order}")
    print(f"  (prereq 0 before 1,2 and 1,2 before 3 -> 0 first, 3 last: check)")
    print()
    print("--- edge cases ---")
    print(f"  findOrder(2, [[1,0]])          = {find_order(2, [[1,0]])}     "
          f"(0 before 1)")
    print(f"  findOrder(1, [])               = {find_order(1, [])}     "
          f"(single course, no prereqs)")
    cyc = find_order(2, [[1, 0], [0, 1]])
    print(f"  findOrder(2, [[1,0],[0,1]])    = {cyc}   "
          f"(2-cycle -> impossible -> [])")
    print()


def find_order(num_courses: int, prerequisites: list[list[int]]) -> list[int]:
    """P210: a valid course ordering, or [] if a cycle exists."""
    edges = [(b, a) for a, b in prerequisites]
    order = topological_sort(num_courses, edges)
    return order if len(order) == num_courses else []


# ============================================================================
# SECTION C - P997 FIND THE TOWN JUDGE (net-degree score)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P997 Find the Town Judge  (net-degree score)")
    print("=" * 72)
    print()
    print("Problem: n people labelled 1..n; trust[i] = [a, b] means a TRUSTS b")
    print("(edge a -> b). The judge: (1) trusts nobody, (2) is trusted by everyone")
    print("else. Return the judge's label, or -1.")
    print()
    print("Key insight: NO traversal needed. The judge has in-degree n-1 and")
    print("out-degree 0, so net score = in - out = n-1. One pass over edges:")
    print("score[a] -= 1 (a trusts someone), score[b] += 1 (b is trusted).")
    print()

    # --- Example 1: a real judge ---
    n1, t1 = 4, [[1, 3], [2, 3], [4, 3]]
    print(f"Example 1: n={n1}, trust={t1}")
    print(f"  (1,2,4 all trust 3; 3 trusts nobody)")
    print()
    print("Net-degree trace (+1 = trusted, -1 = trusting):")
    print()
    ev = trace_find_judge(n1, t1)
    print_events(ev)
    print()
    print(f"  findJudge({n1}, {t1}) = {find_judge(n1, t1)}  "
          f"(score[3] = 3 = n-1)")
    print()

    # --- Example 2: no judge ---
    n2, t2 = 3, [[1, 2], [2, 3]]
    print(f"Example 2 (no judge): n={n2}, trust={t2}")
    print(f"  (1 trusts 2, 2 trusts 3; nobody is trusted by all)")
    print()
    print("Net-degree trace:")
    print()
    ev = trace_find_judge(n2, t2)
    print_events(ev)
    print()
    print(f"  findJudge({n2}, {t2}) = {find_judge(n2, t2)}  "
          f"(no node reaches score n-1=2)")
    print()
    print("--- edge cases ---")
    print(f"  findJudge(2, [[1,2]])            = {find_judge(2, [[1,2]])}      "
          f"(1 trusts 2, 2 trusts nobody -> 2 is judge)")
    print(f"  findJudge(1, [])                 = {find_judge(1, [])}      "
          f"(lone person: trusted by 0 = n-1 others, vacuously the judge)")
    print(f"  findJudge(2, [[1,2],[2,1]])     = {find_judge(2, [[1,2],[2,1]])}     "
          f"(mutual trust: score[1]=0, score[2]=0, both cancel -> no judge)")
    print()
    print("Note: a node reaching score n-1 already ENCODES both conditions:")
    print("trusted by all (in=n-1) AND trusts nobody (out=0), since out would")
    print("subtract. So one check, not two.")
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
    print("  Operation                          Time        Space")
    print("  ---------------------------------- ----------- --------")
    print("  Kahn's topological sort             O(V + E)    O(V)")
    print("  3-state DFS cycle detection         O(V + E)    O(V)")
    print("  Net-degree score (Town Judge)       O(V + E)    O(V)")
    print("  Build adjacency list from edges     O(E)        O(V + E)")
    print()
    print("  All three are LINEAR - no exponential anywhere. The whole pattern")
    print("  is O(V + E); only the constant and the output differ.")
    print()
    print("The three skeletons (memorize them)")
    print("------------------------------------")
    print("  # 1. Kahn's topo sort - order or cycle check")
    print("  def topo_sort(n, edges):")
    print("      graph = {i: [] for i in range(n)}")
    print("      in_degree = [0] * n")
    print("      for u, v in edges:")
    print("          graph[u].append(v); in_degree[v] += 1")
    print("      q = deque(i for i in range(n) if in_degree[i] == 0)")
    print("      order = []")
    print("      while q:")
    print("          node = q.popleft(); order.append(node)")
    print("          for nei in graph[node]:")
    print("              in_degree[nei] -= 1")
    print("              if in_degree[nei] == 0: q.append(nei)")
    print("      return order            # len < n => cycle")
    print()
    print("  # 2. 3-state DFS - WHITE/GRAY/BLACK, back edge = cycle")
    print("  def has_cycle(n, edges):")
    print("      g = {i: [] for i in range(n)}")
    print("      for u, v in edges: g[u].append(v)")
    print("      color = [0]*n  # 0=WHITE 1=GRAY 2=BLACK")
    print("      def dfs(x):")
    print("          color[x] = 1")
    print("          for y in g[x]:")
    print("              if color[y] == 1: return True")
    print("              if color[y] == 0 and dfs(y): return True")
    print("          color[x] = 2; return False")
    print("      return any(dfs(i) for i in range(n) if color[i]==0)")
    print()
    print("  # 3. Net-degree - one pass, no traversal")
    print("  def find_judge(n, trust):")
    print("      score = [0]*(n+1)   # 1-indexed")
    print("      for a, b in trust:  # a trusts b")
    print("          score[a] -= 1; score[b] += 1")
    print("      for i in range(1, n+1):")
    print("          if score[i] == n-1: return i")
    print("      return -1")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. EDGE DIRECTION: prerequisite [a, b] means 'b before a', i.e. edge")
    print("     b -> a (NOT a -> b). Reverse it and your zero-in-degree seeds are")
    print("     the wrong nodes -> silent wrong answer. Town Judge [a, b] means")
    print("     'a trusts b', i.e. edge a -> b.")
    print("  2. CYCLE DETECTION CHECK: after Kahn's, ALWAYS check len(order) == n.")
    print("     Cycle members never reach in-degree 0, so they are never dequeued")
    print("     and silently vanish. len(order) < n IS the cycle signal.")
    print("  3. GRAY vs BLACK in 3-state DFS: a back edge hits a GRAY node (on the")
    print("     current path). A cross/forward edge to a BLACK node is FINE - it is")
    print("     NOT a cycle. Using a 2-state visited set here gives FALSE POSITIVES.")
    print("  4. 1-INDEXED NODES: Town Judge uses 1..n. Allocate size n+1 and loop")
    print("     range(1, n+1). Off-by-one on array size or loop bounds is the #1 bug.")
    print("  5. JUDGE SCORE IS n-1, NOT n: the judge is trusted by everyone ELSE")
    print("     (n-1 people), and trusts nobody (out 0), so net = n-1. The judge does")
    print("     not trust itself, so it can never reach score n.")
    print("  6. MULTIPLE VALID ORDERS: Kahn's may return ANY valid topo order (which")
    print("     zero-in-degree node you dequeue first is arbitrary). Accept any order")
    print("     that respects every edge; don't assert a specific permutation.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                       Diff  Key trick")
    print("  ----------------------------- ----  ----------------------------------------")
    print("  P207 Course Schedule          Med   Kahn's: len(order)==n ? True : False")
    print("  P210 Course Schedule II       Med   Kahn's: return order, or [] on cycle")
    print("  P997 Find the Town Judge      Easy  net score array [0]*(n+1); judge == n-1")
    print("  P269 Alien Dictionary         Hard  build graph from letter pairs; topo sort")
    print("  P310 Min Height Trees         Med   peel leaves inward (Kahn's, undirected)")
    print("  P444 Sequence Reconstruction  Med   topo sort on position constraints")
    print("  P802 Find Eventual Safe States Med   3-state DFS / reverse-graph Kahn's")
    print("  P2392 Build a Matrix          Hard  topo sort rows AND cols independently")
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
    # P207 Course Schedule
    assert can_finish(2, [[1, 0]]) is True
    assert can_finish(2, [[1, 0], [0, 1]]) is False
    assert can_finish(4, [[1, 0], [2, 0], [3, 1], [3, 2]]) is True
    assert can_finish(3, [[0, 1], [1, 2], [2, 0]]) is False   # ring
    assert can_finish(1, []) is True

    # P210 Course Schedule II (order is one of possibly many; validate it is a
    # valid topo order, not a fixed permutation)
    def is_valid_order(n, pre, order):
        if len(order) != n:
            return False
        pos = {node: i for i, node in enumerate(order)}
        return all(pos[b] < pos[a] for a, b in pre)

    assert is_valid_order(4, [[1, 0], [2, 0], [3, 1], [3, 2]],
                          find_order(4, [[1, 0], [2, 0], [3, 1], [3, 2]]))
    assert find_order(2, [[1, 0]]) == [0, 1]
    assert find_order(1, []) == [0]
    assert find_order(2, [[1, 0], [0, 1]]) == []              # cycle

    # P997 Find the Town Judge
    assert find_judge(2, [[1, 2]]) == 2
    assert find_judge(3, [[1, 3], [2, 3]]) == 3
    assert find_judge(1, []) == 1
    assert find_judge(4, [[1, 3], [2, 3], [4, 3]]) == 3
    assert find_judge(3, [[1, 2], [2, 3]]) == -1
    assert find_judge(2, [[1, 2], [2, 1]]) == -1          # mutual trust cancels

    # ---- cross-check: Kahn's and 3-state DFS agree on cycle detection ----
    for n, edges in [
        (4, [(0, 1), (0, 2), (1, 3), (2, 3)]),    # DAG
        (3, [(1, 0), (2, 1), (0, 2)]),              # ring
        (5, [(0, 1), (1, 2), (2, 3), (3, 4)]),      # chain (DAG)
        (5, [(0, 1), (1, 2), (2, 0), (3, 4)]),      # ring in 0-1-2, rest DAG
    ]:
        kahn_cyclic = len(topological_sort(n, edges)) < n
        assert kahn_cyclic == has_cycle_dfs(n, edges)

    print("=" * 72)
    print("[check] can_finish / find_order / find_judge / has_cycle_dfs ... OK")
    print("=" * 72)
