"""
bfs.py - Reference implementation of Breadth-First Search for:
  * tree level-order traversal      (P102)
  * graph / grid shortest-path BFS  (P1091)
  * grid multi-source BFS           (P994 Rotting Oranges)

This is the SINGLE SOURCE OF TRUTH for BFS.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 bfs.py > bfs_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - dropping a stone in a pond
============================================================================
Drop a stone into still water. Ripples spread outward in concentric rings:
every point 1 inch from the splash gets wet at the same moment, then every
point 2 inches away, then 3 inches, ...

BFS works exactly like that. A queue holds the current "ring" of cells. On
each step you drain the WHOLE ring (a wave), and as you drain it you enqueue
every freshly-touched neighbor. The newly enqueued neighbors become the NEXT
ring.

Because every cell in ring k is reached in exactly k steps, the FIRST time
BFS arrives at a target it has used the SHORTEST possible path. That is why
"shortest path on an unweighted graph" and "minimum steps" are the two big
BFS signals.

Three flavors, all the same skeleton:

    queue = deque([source(s)])      # seed
    visited = {source(s)}           # MARK ON ENQUEUE, never on dequeue
    steps = 0
    while queue:
        for _ in range(len(queue)): # <-- snapshot ring size BEFORE draining
            node = queue.popleft()
            for nxt in neighbors(node):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)
        steps += 1

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  ring (wave)     all cells at EXACTLY the same distance from the source.
                  drained atomically: `for _ in range(len(queue)):`.
  queue           FIFO. The front is the current cell; the back is what will
                  become future rings.
  visited         set (or in-grid mutation) of cells already enqueued. The
                  golden rule: mark visited ON ENQUEUE, never on dequeue.
  multi-source    instead of one source, seed the queue with MANY sources at
                  distance 0. The rings expand outward simultaneously, and
                  each cell is claimed by whichever source reached it first.
  8-directional   grid moves that include diagonals. Used by P1091.
  fresh count     in Rotting Oranges we keep a running count of fresh cells
                  so we can return -1 if any are unreachable.

============================================================================
THE SKELETON (all three variants share this)
============================================================================
    from collections import deque

    def bfs_template(sources, neighbors_fn, is_target=None):
        queue = deque(sources)
        visited = set(sources)          # MARK ON ENQUEUE
        steps = 0
        while queue:
            for _ in range(len(queue)): # ring boundary
                node = queue.popleft()
                if is_target and is_target(node):
                    return steps        # shortest distance
                for nxt in neighbors_fn(node):
                    if nxt not in visited:
                        visited.add(nxt)
                        queue.append(nxt)
            steps += 1
        return -1                       # target unreachable
"""

from __future__ import annotations

from collections import deque


# ============================================================================
# TREE NODE - minimal demo class (NOT LeetCode's TreeNode signature; this one
# adds helpers for printing and step-tracing).
# ============================================================================
class TreeNode:
    """Binary tree node."""

    __slots__ = ("val", "left", "right")

    def __init__(self, val: int,
                 left: "TreeNode | None" = None,
                 right: "TreeNode | None" = None):
        self.val = val
        self.left = left
        self.right = right

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return f"TreeNode({self.val})"


def build_tree(values: list[int | None]) -> TreeNode | None:
    """Build a binary tree from LeetCode-style level-order list.

    build_tree([3, 9, 20, None, None, 15, 7]) ->

            3
           / \\
          9   20
             /  \\
            15   7
    """
    if not values or values[0] is None:
        return None
    root = TreeNode(values[0])  # type: ignore[arg-type]
    queue: deque[TreeNode] = deque([root])
    i = 1
    while queue and i < len(values):
        node = queue.popleft()
        if i < len(values) and values[i] is not None:
            node.left = TreeNode(values[i])  # type: ignore[arg-type]
            queue.append(node.left)
        i += 1
        if i < len(values) and values[i] is not None:
            node.right = TreeNode(values[i])  # type: ignore[arg-type]
            queue.append(node.right)
        i += 1
    return root


def tree_ascii(root: TreeNode | None) -> str:
    """One-line LeetCode-style dump: '3,9,20,null,null,15,7'."""
    if root is None:
        return "empty"
    out: list[str] = []
    q: deque[TreeNode | None] = deque([root])
    while q:
        n = q.popleft()
        if n is None:
            out.append("null")
            continue
        out.append(str(n.val))
        # only enqueue children if at least one is non-null somewhere below
        if n.left or n.right:
            q.append(n.left)
            q.append(n.right)
    # trim trailing nulls
    while out and out[-1] == "null":
        out.pop()
    return ",".join(out)


# ============================================================================
# TEMPLATE 1 - TREE LEVEL-ORDER BFS                              P102
# ============================================================================
def level_order(root: TreeNode | None) -> list[list[int]]:
    """Return the level-by-level traversal of a binary tree.

    The ring trick: snapshot `len(queue)` at the start of each level, then
    drain exactly that many nodes. Children enqueued during the drain belong
    to the NEXT level, not the current one.

    Time:  O(n)    -- every node is enqueued/dequeued exactly once
    Space: O(w)    -- queue holds at most one level (w = max width)
    """
    if root is None:
        return []
    result: list[list[int]] = []
    queue: deque[TreeNode] = deque([root])
    while queue:
        level_size = len(queue)             # <-- ring boundary
        level: list[int] = []
        for _ in range(level_size):
            node = queue.popleft()
            level.append(node.val)
            if node.left:
                queue.append(node.left)
            if node.right:
                queue.append(node.right)
        result.append(level)
    return result


# ============================================================================
# TEMPLATE 2 - GRID SHORTEST-PATH BFS (single source, 8 dirs)    P1091
# ============================================================================
EIGHT_DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0),
              (1, 1), (1, -1), (-1, 1), (-1, -1)]


def shortest_path_binary_matrix(grid: list[list[int]]) -> int:
    """Length of the shortest clear-path from (0,0) to (n-1,n-1), 8 dirs.

    A cell is passable iff grid[r][c] == 0. We mutate the grid in place:
    marking a visited cell to 1 (blocked) avoids a separate visited set.

    Time:  O(n^2)   -- each cell visited at most once
    Space: O(n^2)   -- queue in the worst case
    """
    n = len(grid)
    if grid[0][0] == 1 or grid[n - 1][n - 1] == 1:
        return -1
    if n == 1:
        return 1

    grid[0][0] = 1                                   # mark visited on enqueue
    queue: deque[tuple[int, int, int]] = deque([(0, 0, 1)])  # (r, c, dist)
    while queue:
        r, c, d = queue.popleft()
        for dr, dc in EIGHT_DIRS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < n and 0 <= nc < n and grid[nr][nc] == 0:
                if nr == n - 1 and nc == n - 1:      # early exit at target
                    return d + 1
                grid[nr][nc] = 1                     # mark BEFORE enqueue
                queue.append((nr, nc, d + 1))
    return -1


# ============================================================================
# TEMPLATE 3 - GRID MULTI-SOURCE BFS                            P994
# ============================================================================
FOUR_DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]


def oranges_rotting(grid: list[list[int]]) -> int:
    """Minutes until no fresh orange remains. -1 if some are unreachable.

    Multi-source BFS: every cell that is already rotten at t=0 is enqueued
    as a distance-0 source. The rings then expand simultaneously. The
    "if queue: minutes += 1" guard is critical - it prevents counting one
    extra minute for an empty trailing wave.

    Time:  O(R * C)
    Space: O(R * C)
    """
    rows, cols = len(grid), len(grid[0])
    queue: deque[tuple[int, int]] = deque()
    fresh = 0
    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == 2:
                queue.append((r, c))                 # all sources at dist 0
            elif grid[r][c] == 1:
                fresh += 1
    if fresh == 0:
        return 0

    minutes = 0
    while queue:
        for _ in range(len(queue)):                  # ring boundary
            r, c = queue.popleft()
            for dr, dc in FOUR_DIRS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] == 1:
                    grid[nr][nc] = 2                 # rot in place = visited
                    fresh -= 1
                    queue.append((nr, nc))
        if queue:                                    # <-- guard against off-by-1
            minutes += 1
    return minutes if fresh == 0 else -1


# ============================================================================
# STEP TRACERS - re-implement the same logic but record every wave. Used by
# the worked-example sections so the .md and .html can show ring expansion.
# ============================================================================
def trace_level_order(root: TreeNode | None) -> list[dict]:
    """Return [{level, level_values, queue_after}]."""
    waves: list[dict] = []
    if root is None:
        return waves
    queue: deque[TreeNode] = deque([root])
    lvl = 0
    while queue:
        size = len(queue)
        level_vals: list[int] = []
        snapshot_front = [queue[0].val] if queue else []
        for _ in range(size):
            node = queue.popleft()
            level_vals.append(node.val)
            if node.left:
                queue.append(node.left)
            if node.right:
                queue.append(node.right)
        waves.append({
            "level": lvl,
            "values": level_vals,
            "ring_size": size,
            "queue_front_before": snapshot_front,
            "queue_after": [n.val for n in queue],
        })
        lvl += 1
    return waves


def trace_shortest_path(grid: list[list[int]]) -> list[dict]:
    """Trace P1091; return [{wave, dist, frontier, visited, reached}]."""
    n = len(grid)
    waves: list[dict] = []
    if grid[0][0] == 1 or grid[n - 1][n - 1] == 1:
        return waves
    g = [row[:] for row in grid]            # don't mutate the input
    g[0][0] = 1
    queue: deque[tuple[int, int, int]] = deque([(0, 0, 1)])
    visited = {(0, 0)}
    dist = 1
    wave_idx = 0
    reached = False
    if n == 1:
        waves.append({"wave": 0, "dist": 1, "frontier": [(0, 0)],
                      "visited": sorted(visited), "reached": True})
        return waves
    while queue and not reached:
        frontier: list[tuple[int, int]] = []
        size = len(queue)
        for _ in range(size):
            r, c, d = queue.popleft()
            frontier.append((r, c))
            for dr, dc in EIGHT_DIRS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < n and 0 <= nc < n and g[nr][nc] == 0:
                    if nr == n - 1 and nc == n - 1:
                        reached = True
                        dist = d + 1
                    g[nr][nc] = 1
                    visited.add((nr, nc))
                    queue.append((nr, nc, d + 1))
        waves.append({"wave": wave_idx, "dist": dist, "frontier": frontier,
                      "visited": sorted(visited), "reached": reached})
        wave_idx += 1
    if not reached:
        dist = -1
    # store final distance on every wave via the last entry's `reached`
    for w in waves:
        w["final_dist"] = dist
    return waves


def trace_oranges(grid: list[list[int]]) -> list[dict]:
    """Trace P994; return [{minute, rotten_now, fresh_after, grid_snapshot}]."""
    rows, cols = len(grid), len(grid[0])
    g = [row[:] for row in grid]
    queue: deque[tuple[int, int]] = deque()
    fresh = 0
    for r in range(rows):
        for c in range(cols):
            if g[r][c] == 2:
                queue.append((r, c))
            elif g[r][c] == 1:
                fresh += 1
    waves: list[dict] = []
    minute = -1  # wave 0 is the seed (distance 0), reported as minute 0
    if fresh == 0:
        waves.append({"minute": 0, "rotten_now": list(queue),
                      "fresh_after": 0, "grid": [row[:] for row in g]})
        return waves
    # wave 0: the initial rotten sources (distance 0)
    waves.append({"minute": 0, "rotten_now": list(queue),
                  "fresh_after": fresh, "grid": [row[:] for row in g]})
    minute = 0
    while queue:
        for _ in range(len(queue)):
            r, c = queue.popleft()
            for dr, dc in FOUR_DIRS:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and g[nr][nc] == 1:
                    g[nr][nc] = 2
                    fresh -= 1
                    queue.append((nr, nc))
        if queue:
            minute += 1
            waves.append({"minute": minute, "rotten_now": list(queue),
                          "fresh_after": fresh,
                          "grid": [row[:] for row in g]})
    waves[-1]["final_fresh"] = fresh
    waves[-1]["final_minutes"] = minute if fresh == 0 else -1
    return waves


def grid_to_str(grid: list[list[int]]) -> str:
    """Render a grid as 3-char cells (2=rotten, 1=fresh, 0=empty)."""
    return "\n".join(" ".join(str(v) for v in row) for row in grid)


# ============================================================================
# SECTION A - P102 BINARY TREE LEVEL ORDER TRAVERSAL (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P102 Binary Tree Level Order Traversal  (tree BFS)")
    print("=" * 72)
    print()
    print("Tree (LeetCode style:  3,9,20,null,null,15,7):")
    print()
    print("            3")
    print("           / \\")
    print("          9   20")
    print("             /  \\")
    print("            15    7")
    print()
    root = build_tree([3, 9, 20, None, None, 15, 7])
    print(f"ascii dump: {tree_ascii(root)}")
    print()
    print("Level-order BFS drains the queue one LEVEL at a time by snapshotting")
    print("len(queue) before the inner loop. Children enqueued during the drain")
    print("belong to the NEXT level.")
    print()
    print("  level | ring_size | values         | queue after")
    print("  ------+-----------+----------------+----------------")
    waves = trace_level_order(root)
    for w in waves:
        print(f"   {w['level']}   |    {w['ring_size']}     | "
              f"{str(w['values']):14} | {w['queue_after']}")
    print()
    print(f"level_order -> {level_order(build_tree([3, 9, 20, None, None, 15, 7]))}")
    print("expected      [[3], [9, 20], [15, 7]]")
    print()
    print("Edge cases:")
    print(f"  empty tree       -> {level_order(None)}")
    print(f"  single node [1]  -> {level_order(build_tree([1]))}")
    print(f"  left-skewed      -> {level_order(build_tree([1, 2, None, 3]))}")
    print()


# ============================================================================
# SECTION B - P1091 SHORTEST PATH BINARY MATRIX (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P1091 Shortest Path Binary Matrix  (single-source, 8 dirs)")
    print("=" * 72)
    print()
    grid = [[0, 1], [1, 0]]
    print(f"Grid:  {grid}")
    print()
    print("Path: (0,0) -> (1,1)  (diagonal move, 1 step). Length = 2.")
    print("8-directional BFS: at each cell we look at all 8 neighbours. The")
    print("FIRST arrival at (n-1,n-1) is on the shortest path.")
    print()
    print("Wave expansion (mark visited ON ENQUEUE by setting the cell to 1):")
    print()
    waves = trace_shortest_path(grid)
    print("  wave | dist | frontier    | visited cells")
    print("  -----+------+-------------+------------------")
    for w in waves:
        fr = ", ".join(f"({r},{c})" for r, c in w["frontier"])
        vs = ", ".join(f"({r},{c})" for r, c in w["visited"])
        print(f"   {w['wave']}   | {w['dist']:4} | {fr:11} | {vs}")
    print(f"  final shortest_path -> {waves[-1]['final_dist'] if waves else -1}   "
          f"(expected 2)")
    print()
    print("--- bigger grid 3x3 ---")
    grid2 = [[0, 0, 0],
             [1, 1, 0],
             [1, 1, 0]]
    for row in grid2:
        print("   " + " ".join(str(v) for v in row))
    print()
    waves2 = trace_shortest_path(grid2)
    print("  wave | frontier                | #visited")
    print("  -----+--------------------------+---------")
    for w in waves2:
        fr = ", ".join(f"({r},{c})" for r, c in w["frontier"])
        print(f"   {w['wave']}   | {fr:24} | {len(w['visited'])}")
    print(f"  final shortest_path -> {waves2[-1]['final_dist']}   (expected 4)")
    print()
    print("--- blocked start (no path) ---")
    grid3 = [[1, 0], [0, 0]]
    print(f"  grid {grid3}  -> start blocked -> -1")
    print(f"  shortest_path -> {shortest_path_binary_matrix([row[:] for row in grid3])}")
    print()
    print("--- 1x1 clear ---")
    print(f"  grid [[0]] -> n==1 special case -> 1")
    print(f"  shortest_path -> {shortest_path_binary_matrix([[0]])}")
    print()


# ============================================================================
# SECTION C - P994 ROTTING ORANGES (worked example, multi-source BFS)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P994 Rotting Oranges  (multi-source grid BFS)")
    print("=" * 72)
    print()
    grid = [[2, 1, 1],
            [1, 1, 0],
            [0, 1, 1]]
    print("Grid (2=rotten, 1=fresh, 0=empty):")
    for row in grid:
        print("   " + " ".join(str(v) for v in row))
    print()
    print("Multi-source BFS: seed the queue with EVERY rotten cell at minute 0.")
    print("Each wave expands one ring outward. The 'if queue: minutes += 1'")
    print("guard prevents counting a trailing empty wave.")
    print()
    print("Wave-by-wave (R = newly rotten this minute):")
    print()
    waves = trace_oranges(grid)
    for w in waves:
        print(f"  --- minute {w['minute']} ---")
        rotten = ", ".join(f"({r},{c})" for r, c in w["rotten_now"])
        print(f"    rotten frontier (queue): {rotten}")
        print(f"    fresh remaining: {w['fresh_after']}")
        print(f"    grid state:")
        for row in w["grid"]:
            print("      " + " ".join(str(v) for v in row))
        print()
    final = waves[-1].get("final_minutes", -1)
    print(f"oranges_rotting -> {final}   (expected 4)")
    print()
    print("--- already all rotten ---")
    print(f"  [[0,2]] -> {oranges_rotting([[0, 2]])}   (no fresh -> 0)")
    print("--- unreachable fresh ---")
    print(f"  [[2,1,1],[0,1,1],[1,0,1]] -> "
          f"{oranges_rotting([[2, 1, 1], [0, 1, 1], [1, 0, 1]])}   (some "
          f"fresh unreachable -> -1)")
    print("--- two sources ---")
    grid2 = [[2, 1, 1],
             [1, 1, 1],
             [0, 1, 2]]
    print("  grid:")
    for row in grid2:
        print("      " + " ".join(str(v) for v in row))
    out = oranges_rotting([row[:] for row in grid2])
    print(f"  -> {out}   (two rotten seeds at minute 0 -> 2 minutes)")
    print()


# ============================================================================
# SECTION D - COMPLEXITY TABLE & GOTCHAS
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Complexity, killer gotchas, problem table")
    print("=" * 72)
    print()
    print("Complexity")
    print("----------")
    print("  Operation                       Time      Space")
    print("  ------------------------------- --------  --------")
    print("  Tree level-order (P102)         O(n)      O(w)")
    print("  Shortest path grid (P1091)      O(n^2)    O(n^2)")
    print("  Rotting oranges (P994)          O(R*C)    O(R*C)")
    print("  General BFS on graph            O(V + E)  O(V + E)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. MARK VISITED ON ENQUEUE, never on dequeue. If you mark on")
    print("     dequeue, the same cell can be enqueued by many neighbours,")
    print("     blowing up to exponential time (TLE).")
    print("  2. Always snapshot ring size BEFORE the inner loop:")
    print("        for _ in range(len(queue)):")
    print("     If you forget, you process nodes from the NEXT level in the")
    print("     same wave and lose the 'shortest path' guarantee.")
    print("  3. In grid problems, mutate the grid in place to mark visited")
    print("     (e.g. set 1->2) instead of allocating a visited set.")
    print("  4. Rotting Oranges: only increment minutes with")
    print("        if queue: minutes += 1")
    print("     AFTER each wave, or you'll count one extra minute for an")
    print("     empty trailing wave (off-by-one).")
    print("  5. Multi-source BFS: seed ALL sources at distance 0 BEFORE the")
    print("     main loop. They expand simultaneously; each cell is claimed")
    print("     by whichever source reached it first.")
    print("  6. P1091 has a 1x1 special case: if n==1 and grid[0][0]==0,")
    print("     return 1 immediately (don't enqueue and never find target).")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff   Key trick")
    print("  -------------------------------- ------  -------------------------------------")
    print("  P102 Level Order Traversal       Easy    level_size = len(queue) per level")
    print("  P1091 Shortest Path Binary Mat   Medium  single source, 8 dirs, early return")
    print("  P994 Rotting Oranges             Medium  multi-source BFS; if queue: min += 1")
    print("  P542 01 Matrix                   Medium  multi-source from every 0-cell")
    print("  P513 Bottom Left Tree Value      Medium  capture queue[0].val at level start")
    print("  P207 Course Schedule             Medium  Kahn's BFS topological sort")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions ----
    assert level_order(build_tree([3, 9, 20, None, None, 15, 7])) == \
        [[3], [9, 20], [15, 7]]
    assert level_order(None) == []
    assert level_order(build_tree([1])) == [[1]]
    assert level_order(build_tree([1, 2, None, 3])) == [[1], [2], [3]]

    assert shortest_path_binary_matrix([[0, 1], [1, 0]]) == 2
    assert shortest_path_binary_matrix([[0, 0, 0], [1, 1, 0], [1, 1, 0]]) == 4
    assert shortest_path_binary_matrix([[1, 0], [0, 0]]) == -1
    assert shortest_path_binary_matrix([[0]]) == 1
    assert shortest_path_binary_matrix([[1]]) == -1

    assert oranges_rotting([[2, 1, 1], [1, 1, 0], [0, 1, 1]]) == 4
    assert oranges_rotting([[0, 2]]) == 0
    assert oranges_rotting([[2, 1, 1], [0, 1, 1], [1, 0, 1]]) == -1
    assert oranges_rotting([[2, 1, 1], [1, 1, 1], [0, 1, 2]]) == 2

    print("=" * 72)
    print("[check] level_order / shortest_path / oranges_rotting ... OK")
    print("=" * 72)
