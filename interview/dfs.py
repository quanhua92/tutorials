"""
dfs.py - Reference implementation of Depth-First Search for:
  * grid flood-fill island counting      (P200 Number of Islands)
  * grid flood-fill max-area component   (P695 Max Area of Island)
  * tree structural subtree matching     (P572 Subtree of Another Tree)

This is the SINGLE SOURCE OF TRUTH for DFS.md. Every number, table, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 dfs.py > dfs_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - exploring a maze with a piece of chalk
============================================================================
You are inside a maze. The rule is simple: keep walking down one corridor
until you hit a dead end. At a dead end, take ONE step back and try the next
untried branch. Keep going. The trick is the piece of chalk in your pocket:
the moment you enter any square you mark it on the floor, so you never walk
in a circle forever.

That is Depth-First Search. It plunges as DEEP as possible along one path
before it ever considers an alternative. The chalk mark is the "visited"
bit. The "one step back" is just a recursive return.

Two grid flavours + one tree flavour, all the same skeleton:

    def dfs(node):            # node = a cell (r,c) or a TreeNode
        if out_of_bounds(node) or already_visited(node) or wrong_type(node):
            return
        MARK_VISITED(node)    # <-- BEFORE recursing, never after
        for nxt in neighbors(node):
            dfs(nxt)

P200 wraps the skeleton in a double loop and counts how many times it has
to LAUNCH a fresh flood (= number of islands). P695 makes the flood RETURN
the area (1 + sum of the areas of its neighbours). P572 runs DFS on a tree:
an outer DFS walks every node, an inner DFS checks structural equality.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  flood / sink     grid DFS that drowns a whole connected component by
                   overwriting '1' -> '0' (or 1 -> 0) IN PLACE. Sinking acts
                   as the "visited" mark, so no separate visited set is
                   needed.
  call stack       the depth of recursion. Every dfs(cell) call pushes one
                   frame; every return pops one. The stack IS the current
                   path from the seed down to the cell being sunk.
  seed             the first unvisited '1' the outer loop finds. Each seed
                   starts exactly one flood and increments the island count.
  area             for P695, the flood returns 1 + sum(areas of 4 neighbours).
                   The outer loop keeps the running MAX.
  is_same / is_subtree
                   P572 uses TWO recursions. is_same(a, b) checks two trees
                   are structurally identical. is_subtree(root, sub) walks
                   root and, at every node, asks is_same(node, sub).

============================================================================
THE SKELETON (all three flavours share this)
============================================================================
    # GRID (P200 / P695) - mark visited in place, recurse on 4 neighbours
    DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    def dfs(r, c):
        if r < 0 or r >= rows or c < 0 or c >= cols or grid[r][c] != target:
            return 0          # for P200 use `return` (void)
        grid[r][c] = sunk     # MARK BEFORE recursing
        area = 1
        for dr, dc in DIRS:
            area += dfs(r + dr, c + dc)
        return area           # for P200 omit this line

    # TREE (P572) - two coupled recursions
    def is_same(a, b):
        if a is None and b is None: return True
        if a is None or b is None:  return False
        return (a.val == b.val
                and is_same(a.left,  b.left)
                and is_same(a.right, b.right))

    def is_subtree(root, sub):
        if root is None: return False
        return is_same(root, sub) or is_subtree(root.left, sub) \
                                  or is_subtree(root.right, sub)
"""

from __future__ import annotations

from typing import Any


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

    build_tree([3, 4, 5, 1, 2]) ->

            3
           / \\
          4   5
         / \\
        1   2
    """
    if not values or values[0] is None:
        return None
    root = TreeNode(values[0])  # type: ignore[arg-type]
    queue: list[TreeNode] = [root]
    i = 1
    while queue and i < len(values):
        node = queue.pop(0)
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
    """One-line LeetCode-style dump: '3,4,5,1,2'."""
    if root is None:
        return "empty"
    out: list[str] = []
    q: list[TreeNode | None] = [root]
    while q:
        n = q.pop(0)
        if n is None:
            out.append("null")
            continue
        out.append(str(n.val))
        if n.left or n.right:
            q.append(n.left)
            q.append(n.right)
    while out and out[-1] == "null":
        out.pop()
    return ",".join(out)


# ============================================================================
# TEMPLATE 1 - GRID FLOOD-FILL ISLAND COUNT                    P200
# ============================================================================
def num_islands(grid: list[list[str]]) -> int:
    """Count islands in a grid of '0' (water) / '1' (land).

    Sink each island in place ('1' -> '0') as we DFS it, so no visited set
    is needed. Each time the outer loop finds a fresh '1' we have discovered
    one new island.

    Time:  O(R * C)   -- every cell is sunk at most once
    Space: O(R * C)   -- recursion depth in the worst case (a snake island)
    """
    if not grid or not grid[0]:
        return 0
    rows, cols = len(grid), len(grid[0])
    count = 0

    def _sink(r: int, c: int) -> None:
        if r < 0 or r >= rows or c < 0 or c >= cols or grid[r][c] != "1":
            return
        grid[r][c] = "0"          # MARK BEFORE recursing
        _sink(r + 1, c)
        _sink(r - 1, c)
        _sink(r, c + 1)
        _sink(r, c - 1)

    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == "1":
                count += 1
                _sink(r, c)
    return count


# ============================================================================
# TEMPLATE 2 - GRID FLOOD-FILL MAX AREA                         P695
# ============================================================================
def max_area_of_island(grid: list[list[int]]) -> int:
    """Largest connected component of 1s in an int grid. 0 if no land.

    The flood RETURNS its area: 1 + sum of the four neighbours' areas. The
    outer loop keeps the running max. Sink cells (1 -> 0) before recursing.

    Time:  O(R * C)
    Space: O(R * C)
    """
    rows, cols = len(grid), len(grid[0])
    best = 0

    def _area(r: int, c: int) -> int:
        if r < 0 or r >= rows or c < 0 or c >= cols or grid[r][c] != 1:
            return 0
        grid[r][c] = 0            # MARK BEFORE recursing
        return (1
                + _area(r + 1, c)
                + _area(r - 1, c)
                + _area(r, c + 1)
                + _area(r, c - 1))

    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == 1:
                best = max(best, _area(r, c))
    return best


# ============================================================================
# TEMPLATE 3 - TREE SUBTREE MATCH (two coupled recursions)      P572
# ============================================================================
def is_same_tree(a: TreeNode | None, b: TreeNode | None) -> bool:
    """Structurally identical trees with identical values?"""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return (a.val == b.val
            and is_same_tree(a.left, b.left)
            and is_same_tree(a.right, b.right))


def is_subtree(root: TreeNode | None, subRoot: TreeNode | None) -> bool:
    """True iff subRoot appears as an exact subtree of root.

    Outer DFS walks every node of root; at each node the inner DFS
    (is_same_tree) checks structural equality against subRoot.
    """
    if subRoot is None:
        return True
    if root is None:
        return False

    def _dfs(node: TreeNode | None) -> bool:
        if node is None:
            return False
        if is_same_tree(node, subRoot):
            return True
        return _dfs(node.left) or _dfs(node.right)

    return _dfs(root)


# ============================================================================
# STEP TRACERS - re-implement the same logic but record every recursive step.
# Used by the worked-example sections so the .md and .html can show the call
# stack growing/shrinking and the grid filling in.
# ============================================================================
def trace_islands(grid: list[list[str]]) -> list[dict]:
    """Trace P200. Return a list of step dicts:
       {kind:'seed'|'sink'|'pop', cell, depth, stack, count, grid}.
    `grid` is a snapshot AFTER this step's mutation."""
    rows, cols = len(grid), len(grid[0])
    g = [row[:] for row in grid]
    steps: list[dict] = []
    stack: list[tuple[int, int]] = []
    count = 0
    max_depth = 0

    def _sink(r: int, c: int, depth: int) -> None:
        nonlocal count, max_depth
        if r < 0 or r >= rows or c < 0 or c >= cols or g[r][c] != "1":
            return
        g[r][c] = "0"
        max_depth = max(max_depth, depth)
        stack.append((r, c))
        steps.append({"kind": "sink", "cell": (r, c), "depth": depth,
                      "stack": list(stack), "count": count,
                      "grid": [row[:] for row in g]})
        _sink(r + 1, c, depth + 1)
        _sink(r - 1, c, depth + 1)
        _sink(r, c + 1, depth + 1)
        _sink(r, c - 1, depth + 1)
        stack.pop()
        steps.append({"kind": "pop", "cell": (r, c), "depth": depth,
                      "stack": list(stack), "count": count,
                      "grid": [row[:] for row in g]})

    for r in range(rows):
        for c in range(cols):
            if g[r][c] == "1":
                count += 1
                steps.append({"kind": "seed", "cell": (r, c), "depth": 0,
                              "stack": [], "count": count,
                              "grid": [row[:] for row in g]})
                _sink(r, c, 1)
    steps.append({"kind": "done", "cell": None, "depth": 0,
                  "stack": [], "count": count, "grid": [row[:] for row in g],
                  "max_depth": max_depth})
    return steps


def trace_max_area(grid: list[list[int]]) -> list[dict]:
    """Trace P695. Step dicts:
       {kind:'seed'|'sink'|'pop'|'done', cell, depth, stack, area_so_far,
        best, grid}. area_so_far is the running area of the CURRENT island."""
    rows, cols = len(grid), len(grid[0])
    g = [row[:] for row in grid]
    steps: list[dict] = []
    stack: list[tuple[int, int]] = []
    best = 0
    max_depth = 0

    def _area(r: int, c: int, depth: int, area_state: list[int]) -> int:
        nonlocal best, max_depth
        if r < 0 or r >= rows or c < 0 or c >= cols or g[r][c] != 1:
            return 0
        g[r][c] = 0
        max_depth = max(max_depth, depth)
        area_state[0] += 1
        stack.append((r, c))
        steps.append({"kind": "sink", "cell": (r, c), "depth": depth,
                      "stack": list(stack), "area": area_state[0],
                      "best": best, "grid": [row[:] for row in g]})
        total = 1
        total += _area(r + 1, c, depth + 1, area_state)
        total += _area(r - 1, c, depth + 1, area_state)
        total += _area(r, c + 1, depth + 1, area_state)
        total += _area(r, c - 1, depth + 1, area_state)
        stack.pop()
        steps.append({"kind": "pop", "cell": (r, c), "depth": depth,
                      "stack": list(stack), "area": area_state[0],
                      "best": best, "grid": [row[:] for row in g]})
        return total

    for r in range(rows):
        for c in range(cols):
            if g[r][c] == 1:
                steps.append({"kind": "seed", "cell": (r, c), "depth": 0,
                              "stack": [], "area": 0, "best": best,
                              "grid": [row[:] for row in g]})
                a = _area(r, c, 1, [0])
                best = max(best, a)
                steps.append({"kind": "island_done", "cell": (r, c),
                              "depth": 0, "stack": [], "area": a,
                              "best": best, "grid": [row[:] for row in g]})
    steps.append({"kind": "done", "cell": None, "depth": 0, "stack": [],
                  "area": best, "best": best,
                  "grid": [row[:] for row in g], "max_depth": max_depth})
    return steps


def trace_subtree(root: TreeNode | None,
                  sub: TreeNode | None) -> list[dict]:
    """Trace P572 outer DFS. Step dicts:
       {kind, node, depth, stack, matched (is_same at this node?), grid:none}.
    Records every node the outer DFS visits and whether is_same matched."""
    steps: list[dict] = []
    stack: list[int] = []
    depth = 0

    def _walk(node: TreeNode | None, d: int) -> bool:
        nonlocal depth
        if node is None:
            return False
        depth = max(depth, d)
        stack.append(node.val)
        same = is_same_tree(node, sub)
        steps.append({"kind": "visit", "node": node.val, "depth": d,
                      "stack": list(stack), "matched": same})
        if same:
            return True
        if _walk(node.left, d + 1):
            return True
        if _walk(node.right, d + 1):
            return True
        stack.pop()
        steps.append({"kind": "back", "node": node.val, "depth": d,
                      "stack": list(stack), "matched": same})
        return False

    if sub is not None:
        found = _walk(root, 1)
    else:
        found = True
    steps.append({"kind": "done", "node": None, "depth": depth,
                  "stack": [], "matched": found, "found": found})
    return steps


def grid_to_str(grid: list[list[Any]]) -> str:
    """Render a grid as space-separated cells."""
    return "\n".join(" ".join(str(v) for v in row) for row in grid)


# ============================================================================
# SECTION A - P200 NUMBER OF ISLANDS (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P200 Number of Islands  (grid flood-fill DFS)")
    print("=" * 72)
    print()
    grid = [
        ["1", "1", "0", "0", "0"],
        ["1", "1", "0", "0", "0"],
        ["0", "0", "1", "0", "0"],
        ["0", "0", "0", "1", "1"],
    ]
    print("Grid ('1'=land, '0'=water):")
    for row in grid:
        print("   " + " ".join(row))
    print()
    print("The outer loop scans row by row. The FIRST '1' it meets is a SEED:")
    print("increment count, then flood-fill (sink '1'->'0') the whole island.")
    print("Because we sink in place, no separate visited set is needed.")
    print()
    print("Per-island summary (seeds in scan order):")
    print()
    steps = trace_islands(grid)
    done = [s for s in steps if s["kind"] == "done"][0]
    # segment sinks by position: each seed starts a bucket; following sinks
    # belong to that bucket until the next seed (or "done").
    buckets: list[dict] = []
    for s in steps:
        if s["kind"] == "seed":
            buckets.append({"seed": s["cell"], "count": s["count"], "cells": []})
        elif s["kind"] == "sink":
            buckets[-1]["cells"].append((s["cell"], s["depth"]))
    print("  island# | seed cell | cells sunk (order)                | max depth")
    print("  --------+-----------+-----------------------------------+----------")
    for b in buckets:
        cells_str = ", ".join(f"({r},{c})" for (r, c), _ in b["cells"])
        depth = max((d for _, d in b["cells"]), default=0)
        sc = b["seed"]
        print(f"    {b['count']}     |  ({sc[0]},{sc[1]})   | "
              f"{cells_str:33} | {depth}")
    print()
    print(f"num_islands -> {done['count']}   (expected 3)")
    print(f"max recursion depth reached -> {done['max_depth']}")
    print()
    print("Step-by-step call stack (first 10 frames):")
    print("  step | action  | cell   | depth | stack (call path)")
    print("  -----+---------+--------+-------+---------------------------")
    for i, s in enumerate(steps[:10]):
        cell = s["cell"] if s["cell"] else "-"
        stack_str = " -> ".join(f"({r},{c})" for r, c in s["stack"]) or "(empty)"
        print(f"  {i:4} | {s['kind']:7} | {str(cell):6} | "
              f"{s['depth']:5} | {stack_str}")
    print(f"  ... ({len(steps)} steps total)")
    print()
    print("--- edge cases ---")
    print(f"  empty grid []                  -> {num_islands([])}")
    print(f"  all water  [['0','0'],['0','0']] -> "
          f"{num_islands([['0', '0'], ['0', '0']])}")
    print(f"  all land   [['1','1'],['1','1']] -> "
          f"{num_islands([['1', '1'], ['1', '1']])}")
    print(f"  single cell [['1']]            -> {num_islands([['1']])}")
    print()


# ============================================================================
# SECTION B - P695 MAX AREA OF ISLAND (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P695 Max Area of Island  (flood returns its area)")
    print("=" * 72)
    print()
    grid = [
        [0, 0, 1, 0, 0],
        [1, 1, 1, 0, 0],
        [1, 0, 0, 1, 1],
        [0, 0, 0, 1, 1],
    ]
    print("Grid (1=land, 0=water):")
    for row in grid:
        print("   " + " ".join(str(v) for v in row))
    print()
    print("Same skeleton as P200, but _area() RETURNS an int: "
          "1 + sum of the four neighbours'.")
    print("The outer loop keeps the running MAX. Two islands expected: a "
          "5-cell blob and a 4-cell block.")
    print()
    steps = trace_max_area(grid)
    seeds = [s for s in steps if s["kind"] == "seed"]
    islands = [s for s in steps if s["kind"] == "island_done"]
    done = [s for s in steps if s["kind"] == "done"][0]
    print("Per-island summary:")
    print("  island# | seed cell | area | running best")
    print("  --------+-----------+------+--------------")
    for seed, isl in zip(seeds, islands):
        sc = seed["cell"]
        print(f"    {seeds.index(seed) + 1}     |  ({sc[0]},{sc[1]})   | "
              f"{isl['area']:4} | {isl['best']}")
    print()
    print(f"max_area_of_island -> {done['best']}   (expected 5)")
    print(f"max recursion depth reached -> {done['max_depth']}")
    print()
    print("Call-stack trace for the FIRST island (seed (0,2), area 5):")
    print("  step | action | cell   | depth | area_now | stack")
    print("  -----+--------+--------+-------+----------+---------------------")
    shown = 0
    for i, s in enumerate(steps):
        if s["kind"] in ("sink", "pop") and shown < 12:
            cell = s["cell"]
            stack_str = "->".join(f"({r},{c})" for r, c in s["stack"]) or "()"
            print(f"  {i:4} | {s['kind']:6} | ({cell[0]},{cell[1]}) | "
                  f"{s['depth']:5} | {s['area']:8} | {stack_str}")
            shown += 1
        if s["kind"] == "island_done":
            break
    print()
    print("--- edge cases ---")
    print(f"  no land [[0,0],[0,0]]      -> "
          f"{max_area_of_island([[0,0],[0,0]])}   (0)")
    print(f"  single cell [[1]]          -> {max_area_of_island([[1]])}   (1)")
    print(f"  full 2x2 [[1,1],[1,1]]     -> "
          f"{max_area_of_island([[1,1],[1,1]])}   (4)")
    print()


# ============================================================================
# SECTION C - P572 SUBTREE OF ANOTHER TREE (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P572 Subtree of Another Tree  (two coupled DFS)")
    print("=" * 72)
    print()
    print("TRUE case:")
    print("    root           subRoot")
    print("      3              4")
    print("     / \\            / \\")
    print("    4   5          1   2")
    print("   / \\")
    print("  1   2")
    print()
    root = build_tree([3, 4, 5, 1, 2])
    sub = build_tree([4, 1, 2])
    print(f"ascii dump  root    = {tree_ascii(root)}")
    print(f"ascii dump  subRoot = {tree_ascii(sub)}")
    print()
    print("Two recursions: outer is_subtree WALKS root; at each node the inner")
    print("is_same_tree checks structural equality with subRoot. Short-circuits")
    print("on the FIRST match (root's left child 4 == subRoot).")
    print()
    steps = trace_subtree(root, sub)
    print("Outer-DFS walk:")
    print("  step | node | depth | matched? | stack (path of vals)")
    print("  -----+------+-------+----------+----------------------")
    for i, s in enumerate(steps):
        if s["kind"] == "done":
            continue
        node = s["node"]
        stack_str = "->".join(str(v) for v in s["stack"]) or "()"
        match = "YES <==" if s["matched"] else "no"
        print(f"  {i:4} | {node:4} | {s['depth']:5} | "
              f"{match:8} | {stack_str}")
    done = [s for s in steps if s["kind"] == "done"][0]
    print()
    print(f"is_subtree(root, subRoot) -> {done['found']}   (expected True)")
    print()
    print("FALSE case (root has an extra node 0 under 2):")
    print("      3")
    print("     / \\")
    print("    4   5")
    print("   / \\")
    print("  1   2")
    print("     /")
    print("    0")
    root2 = build_tree([3, 4, 5, 1, 2, None, None, None, None, 0])
    print(f"ascii dump  root    = {tree_ascii(root2)}")
    print(f"ascii dump  subRoot = {tree_ascii(sub)}")
    res2 = is_subtree(root2, sub)
    print(f"is_subtree(root2, subRoot) -> {res2}   (expected False)")
    print()
    print("--- edge cases ---")
    print(f"  empty subRoot            -> {is_subtree(build_tree([1,2,3]), None)}")
    print(f"  empty root, nonempty sub -> {is_subtree(None, build_tree([1]))}")
    print(f"  identical trees          -> "
          f"{is_subtree(build_tree([1,2,3]), build_tree([1,2,3]))}")
    print(f"  sub larger than root     -> "
          f"{is_subtree(build_tree([1]), build_tree([1,2]))}")
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
    print("  Number of Islands (P200)        O(R*C)    O(R*C)")
    print("  Max Area of Island (P695)       O(R*C)    O(R*C)")
    print("  Subtree of Another Tree (P572)  O(m*n)    O(m+n)")
    print("  General DFS on graph            O(V + E)  O(V + E)")
    print("  (P572: m=#nodes in root, n=#nodes in subRoot)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. MARK BEFORE YOU MOVE. Set grid[r][c] = sunk (or add to a")
    print("     visited set) BEFORE the recursive calls, never after. Marking")
    print("     after lets two neighbours each call dfs on the other, looping")
    print("     forever (infinite recursion -> stack overflow / TLE).")
    print("  2. SINK IN PLACE to avoid a visited set: overwrite '1'->'0' (or")
    print("     1->0). This is O(1) extra space per cell and reads cleanly.")
    print("  3. CHECK BOUNDS BEFORE INDEXING. The guard")
    print("         if r < 0 or r >= rows or c < 0 or c >= cols ...:")
    print("     must come BEFORE grid[r][c] or you get IndexError.")
    print("  4. PYTHON RECURSION LIMIT is ~1000 by default. A long snake")
    print("     island in a 1000x1000 grid can overflow the stack; use")
    print("     sys.setrecursionlimit or an explicit stack for huge inputs.")
    print("  5. P695 RETURNS the area (1 + sum of neighbours); P200 returns")
    print("     nothing. The only difference between the two skeletons is")
    print("     whether _flood returns an int.")
    print("  6. P572 needs BOTH is_same_tree AND is_subtree. A common bug is")
    print("     to check is_same at the root only and miss a match deeper.")
    print("     Short-circuit with `or` so the first match wins.")
    print("  7. P572 edge case: subRoot == None is ALWAYS true (empty tree is")
    print("     a subtree of everything). Handle it first.")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff   Key trick")
    print("  -------------------------------- ------  --------------------------------------")
    print("  P200 Number of Islands           Medium  sink '1'->'0' in place; count seeds")
    print("  P695 Max Area of Island          Medium  _area returns 1 + sum(neighbours); max")
    print("  P572 Subtree of Another Tree     Easy    outer is_subtree + inner is_same_tree")
    print("  P463 Island Perimeter            Easy    per cell +4, -1 per land neighbour")
    print("  P1306 Jump Game III              Medium  DFS on index graph; visited.add(i)")
    print("  P133 Clone Graph                  Medium  DFS + hashmap old->new node")
    print("  P617 Merge Two Binary Trees      Easy    parallel DFS building a new tree")
    print("  P130 Surrounded Regions          Medium  DFS from border 'O's; flip the rest")
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
    assert num_islands([
        ["1", "1", "0", "0", "0"],
        ["1", "1", "0", "0", "0"],
        ["0", "0", "1", "0", "0"],
        ["0", "0", "0", "1", "1"],
    ]) == 3
    assert num_islands([]) == 0
    assert num_islands([["0", "0"], ["0", "0"]]) == 0
    assert num_islands([["1", "1"], ["1", "1"]]) == 1
    assert num_islands([["1"]]) == 1
    assert num_islands([["1", "0", "1"]]) == 2

    assert max_area_of_island([
        [0, 0, 1, 0, 0],
        [1, 1, 1, 0, 0],
        [1, 0, 0, 1, 1],
        [0, 0, 0, 1, 1],
    ]) == 5
    assert max_area_of_island([[0, 0], [0, 0]]) == 0
    assert max_area_of_island([[1]]) == 1
    assert max_area_of_island([[1, 1], [1, 1]]) == 4
    # LeetCode example 1 (max area 6)
    assert max_area_of_island([
        [0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0],
        [0, 1, 1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0],
        [0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 1, 0, 0],
        [0, 1, 0, 0, 1, 1, 0, 0, 1, 1, 1, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0, 0],
    ]) == 6

    assert is_subtree(build_tree([3, 4, 5, 1, 2]),
                      build_tree([4, 1, 2])) is True
    assert is_subtree(build_tree([3, 4, 5, 1, 2, None, None,
                                  None, None, 0]),
                      build_tree([4, 1, 2])) is False
    assert is_subtree(build_tree([1, 2, 3]), None) is True
    assert is_subtree(None, build_tree([1])) is False
    assert is_subtree(build_tree([1, 2, 3]),
                      build_tree([1, 2, 3])) is True
    assert is_subtree(build_tree([1]),
                      build_tree([1, 2])) is False

    print("=" * 72)
    print("[check] num_islands / max_area_of_island / is_subtree ... OK")
    print("=" * 72)
