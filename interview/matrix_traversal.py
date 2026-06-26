"""
matrix_traversal.py - Reference implementation of the three "traversal-order"
matrix patterns:
  * spiral order          (P054 Spiral Matrix)        — 4 boundary pointers
  * rotate image 90 CW    (P048 Rotate Image)         — transpose + reverse
  * diagonal traverse     (P498 Diagonal Traverse)    — direction flip per diag

This is the SINGLE SOURCE OF TRUTH for MATRIX_TRAVERSAL.md. Every number, table,
and worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 matrix_traversal.py > matrix_traversal_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) - a matrix is just a grid; find the rule
============================================================================
A matrix is a grid of numbers. Do NOT get lost in nested loops. Each traversal
problem has ONE simple geometric rule:

  * SPIRAL     — imagine FOUR WALLS (top, bottom, left, right). Walk the top
                 wall left->right, then the right wall top->bottom, then the
                 bottom wall right->left, then the left wall bottom->top. After
                 each wall, PUSH IT INWARD by one. Stop when the walls cross.

  * ROTATE 90  — two reflections. (1) TRANSPOSE: swap matrix[i][j] with
                 matrix[j][i] for every i<j (reflect across the main diagonal).
                 (2) REVERSE every row (reflect left/right). Diagonal flip +
                 horizontal flip = a quarter turn clockwise.

  * DIAGONAL   — every cell on the SAME diagonal shares the sum (row + col).
                 There are m + n - 1 diagonals, numbered d = 0..m+n-2. Walk them
                 in order, FLIPPING the walking direction each diagonal: even d
                 goes UP-RIGHT, odd d goes DOWN-LEFT. That zig-zag is the answer.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  walls / boundaries
                   the four ints (top, bottom, left, right) that bound the
                   not-yet-visited ring in spiral order. After a wall is walked
                   it is "consumed" and pushed inward (top++, right--, etc).
  transpose        reflect across the main diagonal: cell (i,j) <-> (j,i).
                   Done only for i<j so every pair swaps exactly once.
  reverse a row    mirror the row in place: [a,b,c] -> [c,b,a].
  diagonal sum     the constant d = row + col for every cell on one NW->SE
                   diagonal. d ranges 0 .. (m-1)+(n-1) = m+n-2.
  direction flip   even diagonals head up-right (row-1, col+1); odd diagonals
                   head down-left (row+1, col-1). Flip on every new diagonal.

============================================================================
THE THREE SKELETONS (memorize these)
============================================================================
    # --- SPIRAL (P054) --- 4 walls, walk + shrink
    def spiral_order(matrix):
        res = []
        top, bottom = 0, len(matrix) - 1
        left, right = 0, len(matrix[0]) - 1
        while top <= bottom and left <= right:
            for c in range(left, right + 1):   res.append(matrix[top][c])
            top += 1
            for r in range(top, bottom + 1):   res.append(matrix[r][right])
            right -= 1
            if top <= bottom:
                for c in range(right, left - 1, -1): res.append(matrix[bottom][c])
                bottom -= 1
            if left <= right:
                for r in range(bottom, top - 1, -1): res.append(matrix[r][left])
                left += 1
        return res

    # --- ROTATE (P048) --- transpose, then reverse every row
    def rotate(matrix):
        n = len(matrix)
        for i in range(n):
            for j in range(i + 1, n):
                matrix[i][j], matrix[j][i] = matrix[j][i], matrix[i][j]
        for row in matrix:
            row.reverse()

    # --- DIAGONAL (P498) --- flip direction each diagonal
    def diagonal_traverse(matrix):
        m, n = len(matrix), len(matrix[0])
        res = []
        for d in range(m + n - 1):
            if d % 2 == 0:                      # go UP-RIGHT
                r, c = min(d, m - 1), d - min(d, m - 1)
                while r >= 0 and c < n:
                    res.append(matrix[r][c]); r -= 1; c += 1
            else:                               # go DOWN-LEFT
                c, r = min(d, n - 1), d - min(d, n - 1)
                while c >= 0 and r < m:
                    res.append(matrix[r][c]); r += 1; c -= 1
        return res
"""

from __future__ import annotations


# ============================================================================
# TEMPLATE 1 - SPIRAL ORDER (4 boundary pointers)                 P054
# ============================================================================
def spiral_order(matrix: list[list[int]]) -> list[int]:
    """Return all elements of an m x n matrix in clockwise spiral order.

    Four walls (top, bottom, left, right) bound the unvisited ring. Walk each
    wall, then push it inward. The guards `if top <= bottom` / `if left <= right`
    on the bottom-row and left-col legs are what stop a 1D strip from being
    counted twice.

    Time:  O(m * n)
    Space: O(1) extra (the output list is O(m * n))
    """
    if not matrix or not matrix[0]:
        return []
    result: list[int] = []
    top, bottom = 0, len(matrix) - 1
    left, right = 0, len(matrix[0]) - 1

    while top <= bottom and left <= right:
        # top wall: left -> right
        for c in range(left, right + 1):
            result.append(matrix[top][c])
        top += 1
        # right wall: top -> bottom
        for r in range(top, bottom + 1):
            result.append(matrix[r][right])
        right -= 1
        # bottom wall: right -> left (only if the row still exists)
        if top <= bottom:
            for c in range(right, left - 1, -1):
                result.append(matrix[bottom][c])
            bottom -= 1
        # left wall: bottom -> top (only if the column still exists)
        if left <= right:
            for r in range(bottom, top - 1, -1):
                result.append(matrix[r][left])
            left += 1
    return result


# ============================================================================
# TEMPLATE 2 - ROTATE IMAGE 90 CW (transpose + reverse)           P048
# ============================================================================
def rotate_image(matrix: list[list[int]]) -> list[list[int]]:
    """Rotate an n x n matrix 90 degrees clockwise IN PLACE.

    Step 1 - transpose: swap matrix[i][j] <-> matrix[j][i] for i < j only
             (start the inner loop at j = i+1, or you swap twice and undo it).
    Step 2 - reverse every row.

    Time:  O(n^2)
    Space: O(1)
    """
    n = len(matrix)
    for i in range(n):
        for j in range(i + 1, n):
            matrix[i][j], matrix[j][i] = matrix[j][i], matrix[i][j]
    for row in matrix:
        row.reverse()
    return matrix


# ============================================================================
# TEMPLATE 3 - DIAGONAL TRAVERSE (direction flip per diagonal)     P498
# ============================================================================
def diagonal_traverse(matrix: list[list[int]]) -> list[int]:
    """Return all elements in diagonal zig-zag order.

    Cells on the same diagonal share d = row + col. There are m + n - 1
    diagonals. Walk them in order; even d goes UP-RIGHT, odd d goes DOWN-LEFT.

    Time:  O(m * n)
    Space: O(1) extra
    """
    if not matrix or not matrix[0]:
        return []
    m, n = len(matrix), len(matrix[0])
    result: list[int] = []
    for d in range(m + n - 1):
        if d % 2 == 0:
            # up-right: start low-left, walk to high-right
            row = min(d, m - 1)
            col = d - row
            while row >= 0 and col < n:
                result.append(matrix[row][col])
                row -= 1
                col += 1
        else:
            # down-left: start high-right, walk to low-left
            col = min(d, n - 1)
            row = d - col
            while col >= 0 and row < m:
                result.append(matrix[row][col])
                row += 1
                col -= 1
    return result


# ============================================================================
# STEP TRACERS - re-run the same logic but record every step (for the .md
# worked-example tables and the .html animation). The grid snapshots and
# boundary values are exactly what the algorithm sees.
# ============================================================================
def trace_spiral(matrix: list[list[int]]) -> list[dict]:
    """Trace P054. Step dicts:
       {kind:'start'|'visit'|'done', cell, side, order, result, top, bottom,
        left, right}. `result` and the walls are snapshots AT this step."""
    if not matrix or not matrix[0]:
        return [{"kind": "done", "cell": None, "side": None, "order": 0,
                 "result": [], "top": 0, "bottom": -1, "left": 0, "right": -1}]
    m, n = len(matrix), len(matrix[0])
    result: list[int] = []
    top, bottom = 0, m - 1
    left, right = 0, n - 1
    steps: list[dict] = [{
        "kind": "start", "cell": None, "side": None, "order": 0,
        "result": [], "top": top, "bottom": bottom, "left": left, "right": right,
    }]
    order = 0
    side_names = {
        "top": "top: left->right",
        "right": "right: top->bottom",
        "bottom": "bottom: right->left",
        "left": "left: bottom->top",
    }

    def visit(r: int, c: int, side: str) -> None:
        nonlocal order
        result.append(matrix[r][c])
        steps.append({"kind": "visit", "cell": (r, c), "side": side,
                      "sidename": side_names[side], "order": order,
                      "result": list(result), "top": top, "bottom": bottom,
                      "left": left, "right": right})
        order += 1

    while top <= bottom and left <= right:
        for c in range(left, right + 1):
            visit(top, c, "top")
        top += 1
        for r in range(top, bottom + 1):
            visit(r, right, "right")
        right -= 1
        if top <= bottom:
            for c in range(right, left - 1, -1):
                visit(bottom, c, "bottom")
            bottom -= 1
        if left <= right:
            for r in range(bottom, top - 1, -1):
                visit(r, left, "left")
            left += 1
    steps.append({"kind": "done", "cell": None, "side": None, "order": order,
                  "result": list(result), "top": top, "bottom": bottom,
                  "left": left, "right": right})
    return steps


def trace_rotate(matrix: list[list[int]]) -> list[dict]:
    """Trace P048. Step dicts:
       {kind:'start'|'transpose'|'reverse'|'done', i|row, j, phase, grid}."""
    n = len(matrix)
    g = [row[:] for row in matrix]
    steps: list[dict] = [{
        "kind": "start", "phase": "transpose", "i": None, "j": None,
        "row": None, "grid": [row[:] for row in g],
    }]
    # Phase 1 - transpose (swap (i,j)<->(j,i) for i<j)
    for i in range(n):
        for j in range(i + 1, n):
            g[i][j], g[j][i] = g[j][i], g[i][j]
            steps.append({"kind": "transpose", "phase": "transpose",
                          "i": i, "j": j, "row": None,
                          "grid": [row[:] for row in g]})
    # Phase 2 - reverse every row
    for r in range(n):
        g[r].reverse()
        steps.append({"kind": "reverse", "phase": "reverse",
                      "i": None, "j": None, "row": r,
                      "grid": [row[:] for row in g]})
    steps.append({"kind": "done", "phase": "done", "i": None, "j": None,
                  "row": None, "grid": [row[:] for row in g]})
    return steps


def trace_diagonal(matrix: list[list[int]]) -> list[dict]:
    """Trace P498. Step dicts:
       {kind:'start'|'visit'|'diag_done'|'done', cell, diag, direction,
        order, result}. `direction` is 'up' or 'down'."""
    if not matrix or not matrix[0]:
        return [{"kind": "done", "cell": None, "diag": -1,
                 "direction": None, "order": 0, "result": []}]
    m, n = len(matrix), len(matrix[0])
    result: list[int] = []
    steps: list[dict] = [{"kind": "start", "cell": None, "diag": -1,
                          "direction": None, "order": 0, "result": []}]
    order = 0
    for d in range(m + n - 1):
        if d % 2 == 0:
            direction = "up"
            row = min(d, m - 1)
            col = d - row
        else:
            direction = "down"
            col = min(d, n - 1)
            row = d - col
        while row >= 0 and col >= 0 and row < m and col < n:
            result.append(matrix[row][col])
            steps.append({"kind": "visit", "cell": (row, col), "diag": d,
                          "direction": direction, "order": order,
                          "result": list(result)})
            order += 1
            if direction == "up":
                row -= 1
                col += 1
            else:
                row += 1
                col -= 1
    steps.append({"kind": "done", "cell": None, "diag": -1,
                  "direction": None, "order": order, "result": list(result)})
    return steps


# ============================================================================
# RENDER HELPERS
# ============================================================================
def grid_to_str(grid: list[list[int]], pad: int = 2) -> str:
    """Render a grid as space-separated cells, right-aligned to a fixed width."""
    width = 1
    for row in grid:
        for v in row:
            width = max(width, len(str(v)))
    width += pad
    return "\n".join("".join(str(v).rjust(width) for v in row) for row in grid)


def grid_repr(grid: list[list[int]]) -> str:
    """Compact one-line grid repr, e.g. [[1,4,3],[2,5,6],[7,8,9]]."""
    return "[" + ",".join("[" + ",".join(str(v) for v in row) + "]"
                          for row in grid) + "]"


def fmt_list(values: list[int]) -> str:
    return "[" + ", ".join(str(v) for v in values) + "]"


# ============================================================================
# SECTION A - P054 SPIRAL MATRIX (worked example)
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - P054 Spiral Matrix  (4 boundary pointers, shrink inward)")
    print("=" * 72)
    print()
    matrix = [
        [1, 2, 3],
        [4, 5, 6],
        [7, 8, 9],
    ]
    print("Matrix (3x3):")
    print(grid_to_str(matrix))
    print()
    print("Four walls: top, bottom, left, right. Walk each wall, then push it")
    print("inward. The guards `if top<=bottom` / `if left<=right` on the bottom")
    print("and left legs stop a 1-row or 1-column strip being walked twice.")
    print()
    steps = trace_spiral(matrix)
    done = [s for s in steps if s["kind"] == "done"][0]
    visits = [s for s in steps if s["kind"] == "visit"]

    # legs summary: group consecutive visits by side
    legs: list[dict] = []
    for s in visits:
        if not legs or legs[-1]["side"] != s["side"]:
            legs.append({"side": s["side"], "sidename": s["sidename"],
                         "cells": [s["cell"]],
                         "walls_after": (s["top"], s["bottom"],
                                         s["left"], s["right"])})
        else:
            legs[-1]["cells"].append(s["cell"])
    print("Legs walked (one ring unwrap = 4 legs, then repeat inward):")
    print("  leg# | side                | cells visited            | walls (T,B,L,R)")
    print("  -----+---------------------+--------------------------+-----------------")
    for idx, leg in enumerate(legs, 1):
        cells = ", ".join(f"({r},{c})" for r, c in leg["cells"])
        w = leg["walls_after"]
        print(f"    {idx} | {leg['sidename']:<19} | {cells:<24} | ({w[0]},{w[1]},{w[2]},{w[3]})")
    print()
    print(f"spiral_order -> {fmt_list(done['result'])}")
    print(f"final walls  -> top={done['top']} bottom={done['bottom']} "
          f"left={done['left']} right={done['right']}  (crossed = stop)")
    print()
    print("Per-cell walk (the cursor's path; order = output index):")
    print("  step | side   | cell   | value | order | walls (T,B,L,R)")
    print("  -----+--------+--------+-------+-------+-----------------")
    for i, s in enumerate(visits):
        r, c = s["cell"]
        w = (s["top"], s["bottom"], s["left"], s["right"])
        print(f"  {i:4} | {s['side']:<6} | ({r},{c}) | {matrix[r][c]:5} | "
              f"{s['order']:5} | ({w[0]},{w[1]},{w[2]},{w[3]})")
    print()
    print("--- non-square + edge cases ---")
    rect = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
    print(f"  3x4 rect {fmt_list(rect[0] + rect[1] + rect[2])}")
    print(f"           -> {fmt_list(spiral_order(rect))}")
    print(f"  1x3 row [[1,2,3]]          -> {fmt_list(spiral_order([[1, 2, 3]]))}")
    print(f"  3x1 col [[1],[2],[3]]      -> "
          f"{fmt_list(spiral_order([[1], [2], [3]]))}")
    print(f"  2x2    [[1,2],[3,4]]       -> "
          f"{fmt_list(spiral_order([[1, 2], [3, 4]]))}")
    print(f"  1x1    [[1]]               -> {fmt_list(spiral_order([[1]]))}")
    print(f"  empty  []                  -> {fmt_list(spiral_order([]))}")
    print()


# ============================================================================
# SECTION B - P048 ROTATE IMAGE (worked example)
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - P048 Rotate Image  (transpose + reverse each row)")
    print("=" * 72)
    print()
    matrix = [
        [1, 2, 3],
        [4, 5, 6],
        [7, 8, 9],
    ]
    print("Matrix (3x3, before):")
    print(grid_to_str(matrix))
    print()
    print("Two reflections = a quarter turn clockwise:")
    print("  (1) TRANSPOSE  : swap (i,j) <-> (j,i) for i<j  (reflect main diagonal)")
    print("  (2) REVERSE ROW: mirror every row left<->right (reflect vertically)")
    print()
    steps = trace_rotate(matrix)
    transpose_steps = [s for s in steps if s["kind"] == "transpose"]
    reverse_steps = [s for s in steps if s["kind"] == "reverse"]
    done = [s for s in steps if s["kind"] == "done"][0]
    print("Phase 1 - transpose (only i<j, so each pair swaps once):")
    print("  swap# | pair            | grid after swap")
    print("  ------+-----------------+-----------------------------")
    for i, s in enumerate(transpose_steps, 1):
        print(f"     {i} | ({s['i']},{s['j']}) <-> ({s['j']},{s['i']}) | {grid_repr(s['grid'])}")
    print()
    print("Phase 2 - reverse each row:")
    print("  row# | row reversed | grid after reverse")
    print("  -----+--------------+-----------------------------")
    for i, s in enumerate(reverse_steps, 1):
        print(f"    {s['row']} | {grid_repr([s['grid'][s['row']]]):<12} | {grid_repr(s['grid'])}")
    print()
    print("Matrix (after, rotated 90 CW):")
    print(grid_to_str(done["grid"]))
    print()
    print("--- edge cases ---")
    one = [[1]]
    rotate_image(one)
    print(f"  1x1 [[1]]                  -> {one}")
    two = [[1, 2], [3, 4]]
    rotate_image(two)
    print(f"  2x2 [[1,2],[3,4]]          -> {two}")
    four = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]]
    rotate_image(four)
    print(f"  4x4 1..16                  -> {four}")
    print()


# ============================================================================
# SECTION C - P498 DIAGONAL TRAVERSE (worked example)
# ============================================================================
def section_c() -> None:
    print("=" * 72)
    print("SECTION C - P498 Diagonal Traverse  (flip direction each diagonal)")
    print("=" * 72)
    print()
    matrix = [
        [1, 2, 3],
        [4, 5, 6],
        [7, 8, 9],
    ]
    print("Matrix (3x3):")
    print(grid_to_str(matrix))
    print()
    print("Every cell on a diagonal shares d = row + col. There are m+n-1")
    print("diagonals. Walk them in order; EVEN d goes up-right, ODD d goes")
    print("down-left. The zig-zag is the answer.")
    print()
    steps = trace_diagonal(matrix)
    done = [s for s in steps if s["kind"] == "done"][0]
    visits = [s for s in steps if s["kind"] == "visit"]

    # diagonal summary: group visits by diag
    diags: list[dict] = []
    for s in visits:
        if not diags or diags[-1]["diag"] != s["diag"]:
            diags.append({"diag": s["diag"], "direction": s["direction"],
                          "cells": [s["cell"]]})
        else:
            diags[-1]["cells"].append(s["cell"])
    print("Diagonals (d = row + col):")
    print("  d | direction    | cells walked                  | values")
    print("  --+--------------+-------------------------------+------------------")
    for d in diags:
        cells = ", ".join(f"({r},{c})" for r, c in d["cells"])
        vals = ", ".join(str(matrix[r][c]) for r, c in d["cells"])
        arrow = "up-right ^" if d["direction"] == "up" else "down-left v"
        print(f"  {d['diag']} | {arrow:<12} | {cells:<29} | {vals}")
    print()
    print(f"diagonal_traverse -> {fmt_list(done['result'])}")
    print()
    print("Per-cell walk (order = output index):")
    print("  step | d | direction  | cell   | value | order")
    print("  -----+---+------------+--------+-------+------")
    for i, s in enumerate(visits):
        r, c = s["cell"]
        arrow = "up-right" if s["direction"] == "up" else "down-left"
        print(f"  {i:4} | {s['diag']} | {arrow:<10} | ({r},{c}) | "
              f"{matrix[r][c]:5} | {s['order']}")
    print()
    print("--- non-square + edge cases ---")
    rect = [[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]
    print(f"  3x4 rect -> {fmt_list(diagonal_traverse(rect))}")
    print(f"  2x3 [[1,2,3],[4,5,6]] -> "
          f"{fmt_list(diagonal_traverse([[1, 2, 3], [4, 5, 6]]))}")
    print(f"  1x1 [[1]]             -> {fmt_list(diagonal_traverse([[1]]))}")
    print(f"  1x3 row [[1,2,3]]     -> "
          f"{fmt_list(diagonal_traverse([[1, 2, 3]]))}")
    print(f"  empty []              -> {fmt_list(diagonal_traverse([]))}")
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
    print("  Operation                       Time      Space (extra)")
    print("  ------------------------------- --------  -------------")
    print("  Spiral Matrix (P054)            O(m*n)    O(1)  (output O(m*n))")
    print("  Rotate Image (P048)             O(n^2)    O(1)  in-place")
    print("  Diagonal Traverse (P498)        O(m*n)    O(1)  (output O(m*n))")
    print("  (m = rows, n = cols; P048 needs a SQUARE n x n matrix)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. SPIRAL DOUBLE-COUNTING. After walking the top and right walls")
    print("     you MUST guard the bottom and left legs with `if top<=bottom`")
    print("     and `if left<=right`. Without them a single row or column gets")
    print("     walked twice (e.g. 1x5 emits [1,2,3,4,5,4,3,2,1]). Trace a 1xN.")
    print("  2. TRANSPOSE BOUNDS. The inner loop must be `for j in range(i+1, n)`.")
    print("     Starting at j=0 swaps every pair twice, UNDOING the transpose.")
    print("  3. ROTATE ORDER MATTERS. Transpose-then-reverse = 90 CW. Reverse-")
    print("     then-transpose = 90 CCW. For CCW you can also reverse COLUMNS")
    print("     (top<->bottom) after the transpose. Decide the direction up front.")
    print("  4. DIAGONAL START CELL. Even d starts at row=min(d,m-1) (bottom-left")
    print("     of the diagonal); odd d starts at col=min(d,n-1) (top-right). Get")
    print("     these backwards and you walk the diagonal in reverse / out of bounds.")
    print("  5. DIAGONAL DIRECTION PARITY depends on the convention. Here even d =")
    print("     up-right matches LeetCode P498 exactly. Some texts flip the parity")
    print("     for the OPPOSITE zig-zag - always check against the example.")
    print("  6. IN-PLACE vs COPY. P048 demands in-place (no second matrix). The")
    print("     transpose+reverse trick is O(1) extra space; a 4-way swap of each")
    print("     4-cell group also works but the two-reflection version is easier")
    print("     to recall under pressure.")
    print("  7. EMPTY / 1xN INPUTS. Always short-circuit `if not matrix or not")
    print("     matrix[0]: return []` at the top of spiral & diagonal, or the")
    print("     very first len(matrix[0]) raises IndexError on [].")
    print()
    print("Problem table")
    print("-------------")
    print("  Problem                          Diff   Key trick")
    print("  -------------------------------- ------  ------------------------------------------")
    print("  P054 Spiral Matrix               Medium 4 walls; guard bottom/left legs")
    print("  P048 Rotate Image                Medium transpose (i<j) + reverse each row")
    print("  P498 Diagonal Traverse            Medium d=row+col; flip dir each diagonal")
    print("  P059 Spiral Matrix II             Medium fill 1..n^2 in spiral order (same walls)")
    print("  P885 Spiral Matrix III            Hard   walk by step-length (1,1,2,2,3,3,...)")
    print("  P73  Set Matrix Zeroes            Medium flag rows/cols in-place, not traversal")
    print("  P542 01 Matrix                     Medium multi-source BFS from all 0-cells")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()

    # ---- assertions (these are the values the .html gold-check recomputes) ----
    assert spiral_order([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [1, 2, 3, 6, 9, 8, 7, 4, 5]
    assert spiral_order([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]) == [1, 2, 3, 4, 8, 12, 11, 10, 9, 5, 6, 7]
    assert spiral_order([[1, 2], [3, 4]]) == [1, 2, 4, 3]
    assert spiral_order([[1, 2, 3]]) == [1, 2, 3]
    assert spiral_order([[1], [2], [3]]) == [1, 2, 3]
    assert spiral_order([[1]]) == [1]
    assert spiral_order([]) == []
    assert spiral_order([[]]) == []

    def _rot(m):
        return rotate_image([row[:] for row in m])

    assert _rot([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [[7, 4, 1], [8, 5, 2], [9, 6, 3]]
    assert _rot([[1, 2], [3, 4]]) == [[3, 1], [4, 2]]
    assert _rot([[1]]) == [[1]]
    assert _rot([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, 15, 16]]) == [[13, 9, 5, 1], [14, 10, 6, 2], [15, 11, 7, 3], [16, 12, 8, 4]]

    assert diagonal_traverse([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [1, 2, 4, 7, 5, 3, 6, 8, 9]
    assert diagonal_traverse([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12]]) == [1, 2, 5, 9, 6, 3, 4, 7, 10, 11, 8, 12]
    assert diagonal_traverse([[1, 2, 3], [4, 5, 6]]) == [1, 2, 4, 5, 3, 6]
    assert diagonal_traverse([[1]]) == [1]
    assert diagonal_traverse([[1, 2, 3]]) == [1, 2, 3]
    assert diagonal_traverse([]) == []
    assert diagonal_traverse([[]]) == []

    print("=" * 72)
    print("[check] spiral_order / rotate_image / diagonal_traverse ... OK")
    print("=" * 72)
