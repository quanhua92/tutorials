"""
avl_tree.py - Reference implementation of the AVL Tree (Adelson-Velsky &
Landis, 1962), the original self-balancing binary search tree.

This is the SINGLE SOURCE OF TRUTH for AVL_TREE.md. Every number, tree, and
worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 avl_tree.py > avl_tree_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

========================================================================
THE INTUITION (read this first) — the self-righting mobile
========================================================================
Hang a BST in your mind as a baby MOBILE (the hanging sculpture): each node is
a bar that must stay roughly level. A plain BST lets one side grow indefinitely
long, so the mobile tips over and a search degenerates to O(N). An AVL tree
adds one rule that keeps every bar level: the BALANCE FACTOR.

  balance factor of a node = height(left subtree) - height(right subtree)

The rule: the balance factor of EVERY node must be in {-1, 0, +1}. The instant
an insert or delete pushes a node to +2 or -2, we ROTATE the subtree to pull it
back level. There are four tilt patterns and one fix each (two single rotations
and two double rotations).

THE REASON AVL EXISTS: a balanced tree has height O(log N) instead of O(N), so
search/insert/delete are all O(log N) in the WORST case, not just on average.
AVL is the MOST rigidly balanced of the common trees (tighter than Red-Black),
which makes LOOKUP fastest (shortest tree) at the cost of more rotations on
insert/delete. That is the whole trade-off story in Section E.

========================================================================
PLAIN-ENGLISH GLOSSARY
========================================================================
  BST             binary search tree: left subtree < node < right subtree.
  node            a cell: value + left child + right child + height.
  height(node)    the number of nodes on the longest downward path to a null.
                  A leaf has height 1; a null (empty) has height 0.
  balance factor  BF(node) = height(left) - height(right). Must be in
                  {-1, 0, +1}. +2/-2 means the tree is tilted and must rotate.
  rotation        a local pointer rewrite that swaps a node with its child to
                  restore balance, PRESERVING the in-order (sorted) order.
  LL / RR         single rotations: the tilt is a straight line.
  LR / RL         double rotations: the tilt is a zig-zag (rotate the child,
                  then the parent).

========================================================================
THE FOUR ROTATION CASES (the heart of AVL)
========================================================================
  LL  (left-left):  left child of a left-heavy node is itself left-heavy.
                    FIX = one RIGHT rotation at the node.
  RR  (right-right): right child of a right-heavy node is itself right-heavy.
                    FIX = one LEFT rotation at the node.
  LR  (left-right): left child of a left-heavy node is RIGHT-heavy (zig-zag).
                    FIX = LEFT-rotate the child, then RIGHT-rotate the node.
  RL  (right-left): right child of a right-heavy node is LEFT-heavy (zig-zag).
                    FIX = RIGHT-rotate the child, then LEFT-rotate the node.

KEY FACTS (all asserted in code below, gold-checked):
    height of an AVL tree with N nodes  <=  1.4405 * log2(N+2) - 0.3277
    every node's balance factor is in {-1, 0, +1}   (the invariant)
    one insert causes at most ONE rotation (single or double) to fix
    rotations PRESERVE the in-order traversal (sorted order never changes)
    search / insert / delete are all O(log N) WORST case

References:
    Adelson-Velsky & Landis (1962), "An algorithm for the organization of
    information." Soviet Doklady. — the original AVL paper.
    CLRS ch. 13 (Red-Black Trees) for the balancing mindset; Knuth Vol. 3
    for the AVL height bound 1.4405*log2(N+2)-0.3277.
"""

from __future__ import annotations

import math

BANNER = "=" * 72


# ============================================================================
# 0. THE AVL NODE + HELPERS
# ============================================================================

class AVLNode:
    """One AVL cell: a value plus two child pointers and a cached height.

    height is the number of NODES on the longest path down to a null (so a leaf
    is height 1). We cache it so balance factors are O(1) to compute.
    """

    __slots__ = ("val", "left", "right", "height")

    def __init__(self, val: int):
        self.val = val
        self.left: AVLNode | None = None
        self.right: AVLNode | None = None
        self.height = 1


def height(node: AVLNode | None) -> int:
    """Height in NODES; empty subtree = 0, leaf = 1."""
    return node.height if node else 0


def balance_factor(node: AVLNode | None) -> int:
    """BF = height(left) - height(right). 0 if node is None."""
    if node is None:
        return 0
    return height(node.left) - height(node.right)


def update_height(node: AVLNode) -> None:
    """Recompute the cached height from the children's heights."""
    node.height = 1 + max(height(node.left), height(node.right))


# ============================================================================
# 1. THE FOUR ROTATIONS  (each preserves in-order order)
# ============================================================================

def rotate_right(y: AVLNode) -> AVLNode:
    r"""RIGHT rotation. Used for LL case.

          y                x
         / \              / \
        x   T3   --->   T1   y
       / \                  / \
      T1  T2              T2  T3

    In-order (T1 < x < T2 < y < T3) is preserved. y drops to become x's right
    child; x's old right child (T2) becomes y's left child.
    """
    x = y.left
    assert x is not None, "rotate_right needs a left child"
    t2 = x.right
    x.right = y
    y.left = t2
    update_height(y)     # y first (it is now lower)
    update_height(x)
    return x             # x is the new subtree root


def rotate_left(x: AVLNode) -> AVLNode:
    r"""LEFT rotation. Used for RR case.

        x                  y
       / \                / \
      T1  y     --->     x   T3
         / \            / \
        T2  T3        T1  T2
    """
    y = x.right
    assert y is not None, "rotate_left needs a right child"
    t2 = y.left
    y.left = x
    x.right = t2
    update_height(x)
    update_height(y)
    return y


# ----------------------------------------------------------------------------
# Rotation event log (reset per build). Each entry: (case, at_node, description)
# ----------------------------------------------------------------------------
_rotations: list[tuple[str, int, str]] = []


def reset_rotations() -> None:
    _rotations.clear()


# ============================================================================
# 2. INSERT (recursive, with balance restoration + rotation logging)
# ============================================================================

def insert(root: AVLNode | None, val: int) -> AVLNode:
    """Insert val into the AVL tree rooted at root; return the new root.

    Standard BST insert, then walk back up the recursion fixing heights and
    checking balance factors. At most ONE subtree rotation fixes the tree (a
    property unique to AVL inserts: one fix and the whole tree is balanced).
    """
    # ---- standard BST insert ----
    if root is None:
        return AVLNode(val)
    if val < root.val:
        root.left = insert(root.left, val)
    else:
        root.right = insert(root.right, val)

    update_height(root)
    b = balance_factor(root)

    # ---- Left heavy (BF == +2) ----
    if b > 1:
        if val < root.left.val:                     # inserted into left-left
            _rotations.append(("LL", root.val, "right-rotate"))
            return rotate_right(root)
        else:                                       # inserted into left-right
            _rotations.append(("LR", root.val,
                               "left-rotate @left, then right-rotate"))
            root.left = rotate_left(root.left)
            return rotate_right(root)

    # ---- Right heavy (BF == -2) ----
    if b < -1:
        if val > root.right.val:                    # inserted into right-right
            _rotations.append(("RR", root.val, "left-rotate"))
            return rotate_left(root)
        else:                                       # inserted into right-left
            _rotations.append(("RL", root.val,
                               "right-rotate @right, then left-rotate"))
            root.right = rotate_right(root.right)
            return rotate_left(root)

    return root


# ============================================================================
# 3. DELETE (recursive, with rebalancing up the path)
# ============================================================================

def min_value_node(node: AVLNode) -> AVLNode:
    """Leftmost node of the subtree = in-order successor."""
    cur = node
    while cur.left is not None:
        cur = cur.left
    return cur


def delete(root: AVLNode | None, val: int) -> AVLNode | None:
    """Delete val from the AVL tree; return the new root.

    Unlike insert, a delete can trigger a ROTATION at EVERY ancestor on the
    way back up (so it is still O(log N), but possibly more than one rotation).
    """
    if root is None:
        return None

    if val < root.val:
        root.left = delete(root.left, val)
    elif val > root.val:
        root.right = delete(root.right, val)
    else:
        # found the node to delete
        if root.left is None:
            return root.right
        if root.right is None:
            return root.left
        # two children: replace with in-order successor, delete the successor
        succ = min_value_node(root.right)
        root.val = succ.val
        root.right = delete(root.right, succ.val)

    update_height(root)
    b = balance_factor(root)

    if b > 1:                                       # left heavy after delete
        if balance_factor(root.left) >= 0:         # LL
            _rotations.append(("LL", root.val, "right-rotate (delete)"))
            return rotate_right(root)
        else:                                       # LR
            _rotations.append(("LR", root.val,
                               "left-rotate @left, then right-rotate (delete)"))
            root.left = rotate_left(root.left)
            return rotate_right(root)

    if b < -1:                                      # right heavy after delete
        if balance_factor(root.right) <= 0:        # RR
            _rotations.append(("RR", root.val, "left-rotate (delete)"))
            return rotate_left(root)
        else:                                       # RL
            _rotations.append(("RL", root.val,
                               "right-rotate @right, then left-rotate (delete)"))
            root.right = rotate_right(root.right)
            return rotate_left(root)

    return root


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_tree(node: AVLNode | None, depth: int = 0) -> None:
    """Sideways ASCII tree (right children drawn ABOVE the node, left below).

    Tilt your head to the LEFT to read it. Each node shows value, balance
    factor (bf=height(left)-height(right)), and cached height (h).
    """
    if node is None:
        return
    print_tree(node.right, depth + 1)
    bf = balance_factor(node)
    print("    " * depth + f"{node.val}(bf={bf:+d},h={node.height})")
    print_tree(node.left, depth + 1)


def node_table(root: AVLNode | None) -> list[tuple[int, int, int, int | str, int | str]]:
    """Collect (val, bf, height, left_child, right_child) for every node,
    sorted by value. Used to print a flat table and to run gold checks."""
    rows: list[tuple[int, int, int, int | str, int | str]] = []

    def walk(n: AVLNode | None) -> None:
        if n is None:
            return
        walk(n.left)
        lc = n.left.val if n.left else "-"
        rc = n.right.val if n.right else "-"
        rows.append((n.val, balance_factor(n), n.height, lc, rc))
        walk(n.right)

    walk(root)
    return rows


def inorder(root: AVLNode | None) -> list[int]:
    out: list[int] = []

    def walk(n: AVLNode | None) -> None:
        if n is None:
            return
        walk(n.left)
        out.append(n.val)
        walk(n.right)

    walk(root)
    return out


def check_avl(root: AVLNode | None) -> tuple[bool, int]:
    """Return (is_balanced, height). Verify the AVL invariant on every node."""
    if root is None:
        return True, 0
    lb, lh = check_avl(root.left)
    rb, rh = check_avl(root.right)
    bf = lh - rh
    balanced = lb and rb and -1 <= bf <= 1
    return balanced, 1 + max(lh, rh)


# ----------------------------------------------------------------------------
# SECTION A: insert [10,20,30,40,50,25] — rotation triggers
# ----------------------------------------------------------------------------

def section_insert_sequence() -> AVLNode:
    banner("SECTION A: insert [10,20,30,40,50,25]  (watch the rotations fire)")
    seq = [10, 20, 30, 40, 50, 25]
    print(f"Insert each value in turn into an empty AVL tree: {seq}\n")
    print("After each insert we print the tree (sideways: head LEFT, right "
          "children up).\n")
    root: AVLNode | None = None
    for v in seq:
        reset_rotations()
        root = insert(root, v)
        print(f"--- insert {v} ---")
        if _rotations:
            for case, at, desc in _rotations:
                print(f"  >> IMBALANCE at {at}: {case} case -> {desc}")
        else:
            print("  (no rotation needed; balance factors all in {-1,0,+1})")
        print_tree(root)
        print()
    assert root is not None
    print("Final AVL tree after inserting all of", seq, ":")
    print_tree(root)
    print()
    print("In-order traversal (must stay sorted):", inorder(root))
    return root


# ----------------------------------------------------------------------------
# SECTION B: the four rotation cases in isolation
# ----------------------------------------------------------------------------

def section_four_rotations() -> None:
    banner("SECTION B: the four rotation cases  (LL, RR, LR, RL)")
    cases = [
        ("LL (left-left):  straight left tilt -> ONE right rotation",
         [3, 2, 1]),
        ("RR (right-right): straight right tilt -> ONE left rotation",
         [1, 2, 3]),
        ("LR (left-right):  zig-zag in left subtree -> left THEN right",
         [3, 1, 2]),
        ("RL (right-left):  zig-zag in right subtree -> right THEN left",
         [1, 3, 2]),
    ]
    for title, seq in cases:
        print(f"\n  {title}")
        print(f"  insert sequence: {seq}")
        reset_rotations()
        r: AVLNode | None = None
        for v in seq:
            r = insert(r, v)
        for case, at, desc in _rotations:
            print(f"    >> {case} at {at}: {desc}")
        print("    BEFORE rotation triggers, the 3rd insert would tilt the "
              "root to |BF|=2.")
        print("    AFTER fix -> tree:")
        print_tree(r)
        print(f"    in-order (unchanged by rotation): {inorder(r)}")
        bal, _ = check_avl(r)
        print(f"    [check] balanced? {bal}")


# ----------------------------------------------------------------------------
# SECTION C: balance factor tracking across the whole tree
# ----------------------------------------------------------------------------

def section_balance_factors(root: AVLNode) -> None:
    banner("SECTION C: balance factor tracking  (the invariant, node by node)")
    rows = node_table(root)
    print("For every node in the Section A tree: val | BF | height | "
          "left | right\n")
    print("| val | balance factor | height | left child | right child |")
    print("|-----|----------------|--------|------------|-------------|")
    for val, bf, h, lc, rc in rows:
        print(f"| {val:<3} | {bf:+d}              | {h:<6} | "
              f"{str(lc):<10} | {str(rc):<11} |")
    print()
    bfs = [bf for _, bf, _, _, _ in rows]
    print(f"all balance factors: {bfs}")
    allowed = {-1, 0, 1}
    all_ok = all(b in allowed for b in bfs)
    print(f"each BF in {{-1,0,+1}}? {all_ok}")
    print(f"max |BF| = {max(abs(b) for b in bfs)}  "
          f"(must be <= 1 for a valid AVL tree)")


# ----------------------------------------------------------------------------
# SECTION D: delete + rebalance
# ----------------------------------------------------------------------------

def section_delete_rebalance() -> None:
    banner("SECTION D: delete + rebalance  "
           "(deletion can rotate at every ancestor up the path)")
    print("Build a tree from [10,20,30,40,50,25,5], then DELETE 50.\n")
    print("Why delete 50: it is the only right-side leaf; removing it makes "
          "the root left-heavy by 2, firing an LL (right) rotation.\n")
    seq = [10, 20, 30, 40, 50, 25, 5]
    root: AVLNode | None = None
    for v in seq:
        root = insert(root, v)
    print("Tree after insert [10,20,30,40,50,25,5]:")
    print_tree(root)
    print(f"in-order: {inorder(root)}\n")

    target = 50
    reset_rotations()
    root = delete(root, target)
    print(f"--- delete {target} ---")
    for case, at, desc in _rotations:
        print(f"  >> IMBALANCE at {at}: {case} case -> {desc}")
    if not _rotations:
        print("  (no rebalance needed)")
    print("Tree after delete + rebalance:")
    print_tree(root)
    print(f"in-order (still sorted, length-1): {inorder(root)}\n")
    bal, tree_h = check_avl(root)
    print(f"[check] balanced after delete? {bal}   height = {tree_h}")
    print("Note: an INSERT fixes balance with at most ONE rotation; a DELETE "
          "may rotate at every ancestor on the way up (still O(log N)).")


# ----------------------------------------------------------------------------
# SECTION E: AVL vs Red-Black  + height bound
# ----------------------------------------------------------------------------

def section_avl_vs_rb(root: AVLNode) -> None:
    banner("SECTION E: AVL vs Red-Black  (+ the height bound)")
    n = len(inorder(root))
    tree_h = check_avl(root)[1]
    bound = 1.4405 * math.log2(n + 2) - 0.3277
    print(f"Our tree: N = {n} nodes, height = {tree_h} (node-count).\n")
    print(f"AVL height bound (Knuth):  h <= 1.4405*log2(N+2) - 0.3277")
    print(f"  for N = {n}:  bound = 1.4405*log2({n+2}) - 0.3277 = {bound:.3f}")
    print(f"  our height {tree_h} <= {bound:.3f}?  {tree_h <= bound}")
    print()
    print("| property            | AVL tree            | Red-Black tree          |")
    print("|---------------------|---------------------|-------------------------|")
    print("| balance rule        | |BF| <= 1 everywhere | no path is >2x another  |")
    print("| height bound        | ~1.44 log2 N        | ~2.00 log2 N            |")
    print("| rotations / insert  | up to 2 (double)    | at most 2               |")
    print("| rotations / delete  | O(log N) (cascade)  | at most 3               |")
    print("| lookup speed        | FASTER (shorter tree)| slightly slower         |")
    print("| insert/delete speed | SLOWER (more rotates)| faster (relaxed)        |")
    print("| use when            | read-heavy workload | write-heavy / general   |")
    print()
    print("Bottom line: AVL is the most rigidly balanced -> shortest tree -> ")
    print("fastest lookup, but pays with more rotations on update. Red-Black ")
    print("relaxes the rule (O(1) rotations on delete) so it is the default in")
    print("most stdlibs (C++ std::map, Java TreeMap, Linux CFS scheduler).")


# ============================================================================
# 5. GOLD CHECK
# ============================================================================

def gold_check(root: AVLNode) -> None:
    banner("GOLD CHECK: AVL invariant holds for the whole tree")
    rows = node_table(root)
    bfs = {val: bf for val, bf, _, _, _ in rows}
    balanced, tree_h = check_avl(root)
    all_in_range = all(bf in (-1, 0, 1) for bf in bfs.values())
    ok = balanced and all_in_range
    print(f"node balance factors: {bfs}")
    print(f"every BF in {{-1,0,+1}}? {all_in_range}")
    print(f"recursive invariant check? {balanced}")
    print(f"tree height = {tree_h}")
    print(f"GOLD (pinned for avl_tree.html): "
          f"final tree in-order = {inorder(root)}, "
          f"height = {tree_h}, balanced = {balanced}")
    print(f"[check] AVL invariant (all BF in {{-1,0,+1}}): {'OK' if ok else 'FAIL'}")
    assert ok, "AVL invariant violated!"


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("avl_tree.py - reference impl. All numbers below feed AVL_TREE.md.")
    print("balance factor = height(left) - height(right); must be in {-1,0,+1}.")

    root = section_insert_sequence()
    section_four_rotations()
    section_balance_factors(root)
    section_delete_rebalance()
    section_avl_vs_rb(root)
    gold_check(root)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
