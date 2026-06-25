"""
bst_redblack.py - Reference implementation: Binary Search Tree -> Red-Black Tree.

This is the SINGLE SOURCE OF TRUTH for BST_REDBLACK.md. Every number, table,
and worked example in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 bst_redblack.py > bst_redblack_output.txt

Pure Python stdlib only. Deterministic (no randomness, no external deps).

============================================================================
THE INTUITION (read this first) -- the library bookshelves, and the leaning tower
============================================================================
A BINARY SEARCH TREE (BST) is a row of LIBRARY BOOKSHELVES arranged by call
number: everything LEFT of a shelf has a smaller number, everything RIGHT has a
bigger one. To find a book you walk left/right at each shelf -- O(h) comparisons,
where h is the height of the arrangement. When books arrive in RANDOM order the
shelves stay roughly balanced, so h ~ log N and every lookup is fast.

But hand the librarian books already SORTED (1, 2, 3, 4, 5, ...) and she always
files each one to the RIGHT of the last. The shelves collapse into a single
LEANING TOWER: 1 -> 2 -> 3 -> 4 -> 5. The "tree" is now a linked list, h = N-1,
and a lookup walks the whole tower. O(h) quietly became O(N). THAT is the BST's
fatal flaw: its shape depends entirely on the INSERT ORDER, and the worst order
(sorted) is exactly the order real data often arrives in.

A RED-BLACK TREE (Guibas & Sedgewick 1978; CLRS Ch. 13) is a BST that heals its
own shape. Every node wears a color, and two cheap local tricks -- COLOR FLIPS
and ROTATIONS -- are applied after each insert so four INVARIANTS always hold.
Those invariants FORCE the tower to stay short: the longest root-to-leaf path is
never more than TWICE the shortest, which pins the height at h <= 2 log2(N+1),
NO MATTER the insert order. Sorted input that crippled the plain BST now costs
the RB tree O(log N) per operation, exactly as if the input had been random.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  key            the value stored at a node; orders the tree (left < node < right).
  BST property   for every node: left subtree keys < node key < right subtree keys.
  height h       EDGES on the longest root-to-leaf path (CLRS convention).
                 single node h=0; empty h=-1. Operations cost O(h).
  NIL / leaf     a sentinel black "null" node. All real leaves point at NIL.
  color          RED or BLACK, painted on each node. The 4 RB invariants use it.
  black-height   black nodes on any root->NIL path. MUST be identical on every
  bh(x)          path -- this is the invariant that bounds the height.
  rotation       a LOCAL pointer rewiring (left or right) that preserves the BST
                 order but moves a child up and a parent down. O(1).
  color flip     repainting two children black and the parent red (or vice versa).
  fixup          the post-insert dance (CLRS 13.3) of flips + rotations that
                 restores the RB invariants.

============================================================================
THE TWO STRUCTURES (CLRS Ch. 12 + Ch. 13)
============================================================================
  BST   (CLRS 12.3): insert/search/delete are O(h). Nothing keeps h small, so a
        sorted insert makes h = N-1 and operations degrade to O(N).
  RB    (CLRS 13, Guibas & Sedgewick 1978): a BST PLUS the 4 invariants below.
        Self-balancing: h <= 2 log2(N+1) GUARANTEED, so O(log N) always.

RED-BLACK INVARIANTS (the whole guarantee rests on these four):
  1. Every node is RED or BLACK.
  2. The ROOT is BLACK.
  3. A RED node has only BLACK children (no two reds in a row on any path).
  4. Every root-to-leaf (NIL) path has the SAME number of black nodes (the
     black-height bh).  <- this is the one we gold-check.

WHY THOSE FOUR PIN THE HEIGHT (the key insight):
  Invariant 4 says every path has bh black nodes. Invariant 3 says a red node
  cannot have a red child, so along any path blacks and reds can alternate at
  best one-for-one. Therefore a path of bh black nodes is AT MOST 2*bh nodes
  long (bh blacks + at most bh reds). The shortest path is all-black = bh nodes;
  the longest is <= 2*bh. So longest <= 2 * shortest, and with N nodes the
  shortest path satisfies bh <= log2(N+1), giving h <= 2*log2(N+1). QED
  (CLRS Lemma 13.1 + Theorem 13.1).

KEY FORMULAS (all asserted in code below, gold-checked):
    BST sorted-insert height   = N - 1                 (the leaning tower)
    RB height guarantee        = h <= 2*log2(N+1)       (CLRS Thm 13.1)
    AVL height (tighter)       = h < 1.4405*log2(N+2) - 0.3277  (AVL tighter)
    black-height consistency   = every root->NIL path identical black count
    rotation cost              = O(1) pointer ops       (left & right are mirrors)
"""

from __future__ import annotations

import math

BANNER = "=" * 72

RED = "R"
BLACK = "B"


# ============================================================================
# 1. THE BINARY SEARCH TREE  (the leaning-tower baseline)
# ============================================================================

class BSTNode:
    __slots__ = ("key", "left", "right")

    def __init__(self, key: int):
        self.key = key
        self.left: BSTNode | None = None
        self.right: BSTNode | None = None


class BST:
    """Plain binary search tree. Insert = O(h); h depends on insert order."""

    def __init__(self):
        self.root: BSTNode | None = None

    def insert(self, key: int) -> None:
        z = BSTNode(key)
        y, x = None, self.root
        while x is not None:
            y = x
            x = x.left if z.key < x.key else x.right
        if y is None:
            self.root = z
        elif z.key < y.key:
            y.left = z
        else:
            y.right = z

    def height(self) -> int:
        """Height in EDGES (CLRS). Empty = -1, single node = 0."""
        def h(n: BSTNode | None) -> int:
            if n is None:
                return -1
            return 1 + max(h(n.left), h(n.right))
        return h(self.root)


# ============================================================================
# 2. THE RED-BLACK TREE  (CLRS Ch. 13, with a shared NIL sentinel)
# ============================================================================

class RBNode:
    __slots__ = ("key", "color", "left", "right", "parent")

    def __init__(self, key, color: str = RED):
        self.key = key
        self.color = color
        self.left: "RBNode" = None       # type: ignore[assignment]
        self.right: "RBNode" = None      # type: ignore[assignment]
        self.parent: "RBNode" = None     # type: ignore[assignment]


class RBTree:
    """Red-Black tree (Guibas & Sedgewick 1978; CLRS 13). Self-balancing.

    Uses ONE shared black NIL sentinel as every leaf, exactly as CLRS does.
    Real nodes start RED; insert_fixup restores the 4 invariants with at most
    two rotations and O(log N) recolors.
    """

    def __init__(self):
        self.NIL = RBNode(None, BLACK)
        self.NIL.left = self.NIL.right = self.NIL.parent = self.NIL
        self.root: RBNode = self.NIL
        self.actions: list[tuple] = []          # trace, filled when trace=True

    def _new_node(self, key: int) -> RBNode:
        n = RBNode(key, RED)
        n.left = n.right = n.parent = self.NIL
        return n

    # ---- CLRS 13.2 rotations (mirrors of each other; O(1) pointer ops) ----

    def left_rotate(self, x: RBNode) -> None:
        """Pull x's RIGHT child y up over x; x becomes y's left child.
        Preserves the BST order. (CLRS LEFT-ROTATE.)"""
        y = x.right
        x.right = y.left                         # turn y's left subtree into x's right
        if y.left is not self.NIL:
            y.left.parent = x
        y.parent = x.parent                      # link x's parent to y
        if x.parent is self.NIL:
            self.root = y
        elif x is x.parent.left:
            x.parent.left = y
        else:
            x.parent.right = y
        y.left = x                               # put x on y's left
        x.parent = y

    def right_rotate(self, x: RBNode) -> None:
        """Pull x's LEFT child y up over x; x becomes y's right child.
        The exact mirror of left_rotate. (CLRS RIGHT-ROTATE.)"""
        y = x.left
        x.left = y.right
        if y.right is not self.NIL:
            y.right.parent = x
        y.parent = x.parent
        if x.parent is self.NIL:
            self.root = y
        elif x is x.parent.right:
            x.parent.right = y
        else:
            x.parent.left = y
        y.right = x
        x.parent = y

    # ---- CLRS 13.3 insert + fixup ----

    def insert(self, key: int, trace: bool = False) -> None:
        if trace:
            self.actions = []
        z = self._new_node(key)
        y, x = self.NIL, self.root
        while x is not self.NIL:
            y = x
            x = x.left if z.key < x.key else x.right
        z.parent = y
        if y is self.NIL:
            self.root = z
        elif z.key < y.key:
            y.left = z
        else:
            y.right = z
        # z.left, z.right already NIL; z.color already RED (from _new_node)
        self._insert_fixup(z, trace=trace)

    def _insert_fixup(self, z: RBNode, trace: bool = False) -> None:
        """Restore the RB invariants after z (a fresh RED node) was inserted.
        CLRS RB-INSERT-FIXUP: three cases, mirrored for left/right.
          Case 1: uncle RED   -> recolor parent+uncle BLACK, grandparent RED,
                                  move the "problem" up two levels.
          Case 2: uncle BLACK, z is an INNER child  -> rotate parent to turn it
                                  into Case 3.
          Case 3: uncle BLACK, z is an OUTER child  -> recolor + rotate
                                  grandparent. Done (loop exits)."""
        while z.parent.color == RED:
            if z.parent is z.parent.parent.left:        # parent is a LEFT child
                uncle = z.parent.parent.right           # uncle
                if uncle.color == RED:                  # ---- Case 1: recolor ----
                    if trace:
                        self.actions.append(
                            ("case1", z.key, "recolor",
                             f"parent {z.parent.key} & uncle {uncle.key} -> BLACK, "
                             f"grandparent {z.parent.parent.key} -> RED"))
                    z.parent.color = BLACK
                    uncle.color = BLACK
                    z.parent.parent.color = RED
                    z = z.parent.parent                 # bubble up
                else:
                    if z is z.parent.right:             # ---- Case 2: inner ----
                        if trace:
                            self.actions.append(
                                ("case2", z.key, "left-rotate(parent)",
                                 f"z={z.key} is right child of {z.parent.key}"))
                        z = z.parent
                        self.left_rotate(z)
                    # now z is an outer (left) child -> Case 3
                    if trace:
                        self.actions.append(
                            ("case3", z.key, "recolor+right-rotate(grandparent)",
                             f"parent {z.parent.key} -> BLACK, "
                             f"grandparent {z.parent.parent.key} -> RED, "
                             f"right-rotate {z.parent.parent.key}"))
                    z.parent.color = BLACK
                    z.parent.parent.color = RED
                    self.right_rotate(z.parent.parent)
            else:                                        # parent is a RIGHT child (mirror)
                uncle = z.parent.parent.left
                if uncle.color == RED:                   # ---- Case 1: recolor ----
                    if trace:
                        self.actions.append(
                            ("case1", z.key, "recolor",
                             f"parent {z.parent.key} & uncle {uncle.key} -> BLACK, "
                             f"grandparent {z.parent.parent.key} -> RED"))
                    z.parent.color = BLACK
                    uncle.color = BLACK
                    z.parent.parent.color = RED
                    z = z.parent.parent
                else:
                    if z is z.parent.left:               # ---- Case 2: inner ----
                        if trace:
                            self.actions.append(
                                ("case2", z.key, "right-rotate(parent)",
                                 f"z={z.key} is left child of {z.parent.key}"))
                        z = z.parent
                        self.right_rotate(z)
                    # now z is an outer (right) child -> Case 3
                    if trace:
                        self.actions.append(
                            ("case3", z.key, "recolor+left-rotate(grandparent)",
                             f"parent {z.parent.key} -> BLACK, "
                             f"grandparent {z.parent.parent.key} -> RED, "
                             f"left-rotate {z.parent.parent.key}"))
                    z.parent.color = BLACK
                    z.parent.parent.color = RED
                    self.left_rotate(z.parent.parent)
        self.root.color = BLACK                          # invariant 2: root is BLACK

    # ---- queries / invariant checks (used for gold checks) ----

    def height(self) -> int:
        def h(n: RBNode) -> int:
            if n is self.NIL:
                return -1
            return 1 + max(h(n.left), h(n.right))
        return h(self.root)

    def path_black_counts(self) -> list[int]:
        """Black nodes on EVERY root->NIL path (counting the NIL leaf as 1 black).
        Invariant 4 requires all these numbers to be EQUAL."""
        counts: list[int] = []

        def dfs(n: RBNode, acc: int) -> None:
            if n is self.NIL:
                counts.append(acc + 1)        # the NIL leaf itself is black
                return
            dfs(n.left, acc + (1 if n.color == BLACK else 0))
            dfs(n.right, acc + (1 if n.color == BLACK else 0))

        dfs(self.root, 0)
        return counts

    def black_height(self) -> int:
        """The (common) black-height of the root, NIL counted. 0 if empty."""
        counts = self.path_black_counts()
        return counts[0] if counts else 0

    def check_invariants(self) -> dict:
        """Verify all 4 RB invariants. Returns a dict of booleans + the bh."""
        root_black = (self.root is self.NIL) or (self.root.color == BLACK)
        no_red_red = True

        def rr(n: RBNode) -> None:
            nonlocal no_red_red
            if n is self.NIL:
                return
            if n.color == RED and (n.left.color == RED or n.right.color == RED):
                no_red_red = False
            rr(n.left)
            rr(n.right)

        rr(self.root)
        counts = self.path_black_counts()
        bh_consistent = len(set(counts)) == 1
        return {
            "root_is_black": root_black,
            "no_red_red": no_red_red,
            "bh_consistent": bh_consistent,
            "bh": counts[0] if counts else 0,
            "all_ok": root_black and no_red_red and bh_consistent,
        }


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def render_sideways(root, is_nil, left, right, key_of, color_of=None) -> str:
    """Sideways ASCII tree: root at the LEFT margin, right subtree drawn ABOVE,
    left subtree drawn BELOW. Red nodes tagged (R), black (B).

        ┌── 20 (B)
    ┌── 15 (R)
    │   └── 12 (B)
    ● 10 (B)
        ...
    """
    lines: list[str] = []

    def walk(n, prefix: str, is_left: bool, depth: int) -> None:
        if is_nil(n):
            return
        # right child is drawn ABOVE -> recurse first, NOT a tail
        walk(right(n), prefix + ("    " if is_left else "│   "), False, depth + 1)
        col = color_of(n) if color_of else ""
        tag = f" ({col})" if col else ""
        if depth == 0:
            connector = "● "
        else:
            connector = "└── " if is_left else "┌── "
        lines.append(f"{prefix}{connector}{key_of(n)}{tag}")
        # left child is drawn BELOW -> recurse last, IS a tail
        walk(left(n), prefix + ("    " if is_left else "│   "), True, depth + 1)

    walk(root, "", True, 0)
    return "\n".join(lines)


def render_bst(t: BST) -> str:
    return render_sideways(t.root, lambda n: n is None,
                           lambda n: n.left, lambda n: n.right,
                           lambda n: n.key)


def render_rb(t: RBTree) -> str:
    return render_sideways(t.root, lambda n: n is t.NIL,
                           lambda n: n.left, lambda n: n.right,
                           lambda n: n.key, lambda n: n.color)


# ----------------------------------------------------------------------------
# SECTION A: the plain BST  (balanced input, then the leaning tower)
# ----------------------------------------------------------------------------

def section_bst_balanced_and_tower() -> None:
    banner("SECTION A: the plain BST  (balanced input, then the leaning tower)")
    seq = [10, 5, 15, 3, 7, 12, 20, 1]
    t = BST()
    for k in seq:
        t.insert(k)
    print(f"Insert {seq} into a plain BST. Arrives roughly balanced ->")
    print(render_bst(t))
    print(f"height h = {t.height()} (edges). Operations cost O(h) = O({t.height()}).")
    print("Random-ish order -> the BST stays shallow. Good.\n")

    # the leaning tower: sorted input
    sorted_seq = [1, 2, 3, 4, 5]
    t2 = BST()
    for k in sorted_seq:
        t2.insert(k)
    print(f"Now insert the SAME KIND of data but already SORTED: {sorted_seq}.")
    print("Every key files to the RIGHT of the last -> a single chain:")
    print(render_bst(t2))
    n = len(sorted_seq)
    print(f"height h = {t2.height()} = N-1 = {n}-1. The 'tree' is a linked list.")
    print("A lookup now walks the whole chain: O(h) collapsed to O(N).")
    print("THIS is the BST's fatal flaw: shape depends on insert order, and the")
    print("worst order (sorted) is the order real data often arrives in.")
    assert t2.height() == n - 1, "sorted-insert BST must have height N-1"
    assert t.height() == 3
    print(f"\n[check] sorted-insert height == N-1 == {n-1}: OK")
    print(f"[check] balanced-seq height == {t.height()}: OK")


# ----------------------------------------------------------------------------
# SECTION B: the Red-Black tree heals the same inputs  (trace + bound)
# ----------------------------------------------------------------------------

def section_rb_main_sequence() -> None:
    banner("SECTION B: Red-Black tree heals the same inputs  (trace + height bound)")
    seq = [10, 5, 15, 3, 7, 12, 20, 1]
    t = RBTree()
    print(f"Insert {seq} into a Red-Black tree, tracing every fixup step:\n")
    for k in seq:
        t.insert(k, trace=True)
        if t.actions:
            for a in t.actions:
                case, zk, op, detail = a
                print(f"  insert {k:>3}: [{case}] {op}  ->  {detail}")
        else:
            print(f"  insert {k:>3}: no fixup (parent was BLACK)  ->  invariants hold")
    print("\nFinal Red-Black tree (R = red, B = black):")
    print(render_rb(t))
    chk = t.check_invariants()
    bound = 2 * math.log2(len(seq) + 1)
    print(f"\nheight h = {t.height()}  (bound 2*log2(N+1) = 2*log2({len(seq)}) "
          f"= {bound:.2f})")
    print(f"black-height bh = {chk['bh']} (consistent across all paths: "
          f"{chk['bh_consistent']})")
    assert t.height() <= bound
    assert chk["all_ok"]
    print(f"[check] h <= 2*log2(N+1): {t.height()} <= {bound:.2f}: OK")
    print(f"[check] all RB invariants hold (root black, no red-red, bh consistent): OK")

    # ---- same shape-killer input that crippled the plain BST ----
    print("\n--- Now the SAME sorted input that made the plain BST a chain ---")
    sorted_seq = [1, 2, 3, 4, 5, 6, 7, 8]
    print(f"Insert {sorted_seq} (sorted) into an RB tree. Every insert's fixup:")
    # build once, printing a per-step fixup trace as each key lands:
    t3 = RBTree()
    print()
    for k in sorted_seq:
        t3.insert(k, trace=True)
        if t3.actions:
            for a in t3.actions:
                case, zk, op, detail = a
                print(f"  insert {k}: [{case}] {op}  ->  {detail}")
        else:
            print(f"  insert {k}: no fixup (parent BLACK)")
    print("\nFinal RB tree from SORTED input (compare with the BST chain above):")
    print(render_rb(t3))
    n = len(sorted_seq)
    bound2 = 2 * math.log2(n + 1)
    chk3 = t3.check_invariants()
    print(f"\nN = {n}, height h = {t3.height()}, bound = 2*log2({n}+1) = {bound2:.2f}")
    print(f"black-height bh = {chk3['bh']} (consistent: {chk3['bh_consistent']})")
    print("The sorted input that produced a height-7 chain in the plain BST gives")
    print(f"a height-{t3.height()} RB tree. Rotations + color flips absorbed every")
    print("lean. The 'leaning tower' problem is gone.")
    assert t3.height() <= bound2
    assert chk3["all_ok"]
    assert t3.height() < n - 1           # RB strictly better than the BST chain
    print(f"[check] h <= 2*log2(N+1): {t3.height()} <= {bound2:.2f}: OK")
    print(f"[check] RB h ({t3.height()}) < BST chain h ({n-1}): OK")
    print(f"[check] all RB invariants hold: OK")


# ----------------------------------------------------------------------------
# SECTION C: rotations  (the O(1) local pointer rewiring)
# ----------------------------------------------------------------------------

def _rb_from_nested(spec) -> RBTree:
    """Build a tiny RB tree by hand for rotation demos, from a nested tuple
    (key, color, left, right). Lets us draw an EXACT starting shape."""
    t = RBTree()

    def build(spec):
        if spec is None:
            return t.NIL
        key, color, left, right = spec
        n = RBNode(key, color)
        n.left = build(left)
        n.right = build(right)
        if n.left is not t.NIL:
            n.left.parent = n
        if n.right is not t.NIL:
            n.right.parent = n
        return n

    t.root = build(spec)
    t.root.parent = t.NIL
    return t


def section_rotations() -> None:
    banner("SECTION C: rotations  (the O(1) local rewiring that moves subtrees)")
    print("A rotation is a LOCAL pointer swap that preserves the BST order but")
    print("rotates a child UP and a parent DOWN. Both flavors are mirrors.\n")

    # ---- LEFT ROTATE ----
    # shape:   x=10(B) with left a=5(B), right y=15(R) with left b=12, right c=20
    before = _rb_from_nested(
        (10, BLACK, (5, BLACK, None, None),
         (15, RED, (12, BLACK, None, None), (20, BLACK, None, None))))
    print("BEFORE left_rotate(x=10):   subtrees a=5, b=12, c=20")
    print(render_rb(before))
    before.left_rotate(before.root)
    print("\nAFTER  left_rotate(x=10):  y=15 pulled up over x; x becomes 15's left;")
    print("subtree b=12 moved from 15's left to 10's right. BST order preserved:")
    print(render_rb(before))
    print("  x.right = y.left(b);  y takes x's old parent slot;  y.left = x.\n")

    # ---- RIGHT ROTATE (the mirror) ----
    before2 = _rb_from_nested(
        (20, BLACK, (15, RED, (12, BLACK, None, None), (17, BLACK, None, None)),
         (25, BLACK, None, None)))
    print("BEFORE right_rotate(x=20):  subtrees a=12, b=17, c=25")
    print(render_rb(before2))
    before2.right_rotate(before2.root)
    print("\nAFTER  right_rotate(x=20): y=15 pulled up over x; x becomes 15's right;")
    print("subtree b=17 moved from 15's right to 20's left. BST order preserved:")
    print(render_rb(before2))
    print("  x.left = y.right(b);  y takes x's old parent slot;  y.right = x.")
    print("\nEach rotation is 6 pointer assignments => O(1). It never touches the")
    print("keys' ORDER, only the geometry. That is why it is the cheap fix-up tool.")

    # ---- verify rotations preserve the BST inorder order ----
    def inorder(n, nil, out):
        if n is nil:
            return
        inorder(n.left, nil, out)
        out.append(n.key)
        inorder(n.right, nil, out)
    keys_after_left, keys_after_right = [], []
    inorder(before.root, before.NIL, keys_after_left)
    inorder(before2.root, before2.NIL, keys_after_right)
    print(f"\ninorder keys after left_rotate : {keys_after_left}  (sorted -> BST ok)")
    print(f"inorder keys after right_rotate: {keys_after_right}  (sorted -> BST ok)")
    assert keys_after_left == sorted(keys_after_left)
    assert keys_after_right == sorted(keys_after_right)
    print("[check] rotations preserve BST inorder order: OK")


# ----------------------------------------------------------------------------
# SECTION D: the three insert-fixup cases  (targeted triggers)
# ----------------------------------------------------------------------------

def _trace_one(seq):
    t = RBTree()
    print(f"sequence: {seq}")
    for k in seq:
        t.insert(k, trace=True)
        if t.actions:
            for a in t.actions:
                case, zk, op, detail = a
                print(f"  insert {k}: [{case}] {op}  ->  {detail}")
        else:
            print(f"  insert {k}: no fixup (parent BLACK)")
    print("  result:")
    print("    " + render_rb(t).replace("\n", "\n    "))
    return t


def section_fixup_cases() -> None:
    banner("SECTION D: the three insert-fixup cases  (CLRS 13.3)")
    print("After inserting a RED node, only its RED PARENT violates invariant 3")
    print("(two reds in a row). Fixup looks at the UNCLE to pick a case:\n")
    print("  Case 1  uncle RED            -> recolor parent+uncle BLACK,")
    print("                                   grandparent RED; bubble problem up.")
    print("  Case 2  uncle BLACK, INNER   -> rotate parent once -> becomes Case 3.")
    print("  Case 3  uncle BLACK, OUTER   -> recolor + rotate grandparent. DONE.\n")

    print("== Case 1 (uncle RED -> recolor) ==")
    print("Both siblings of the new node are red, so we push red UP a level:\n")
    _trace_one([10, 5, 15, 3])

    print("\n== Case 3 (uncle BLACK, OUTER child -> single rotate) ==")
    print("New node is a same-side grandchild; one rotation rebalances:\n")
    _trace_one([10, 15, 20])

    print("\n== Case 2 (uncle BLACK, INNER child -> DOUBLE rotate) ==")
    print("New node is an opposite-side grandchild; rotate parent first to reach")
    print("the Case 3 shape, then rotate the grandparent:\n")
    _trace_one([10, 15, 12])

    print("\nNote: Case 1 can repeat up the tree (it bubbles red up); Case 2 never")
    print("stands alone -- it always converts into Case 3; Case 3 ends the fixup")
    print("(at most ONE rotation in Cases 2+3, plus O(log N) recolors from Case 1).")


# ----------------------------------------------------------------------------
# SECTION E: height comparison  BST vs RB vs AVL  (+ the gold check)
# ----------------------------------------------------------------------------

def section_height_comparison() -> dict:
    banner("SECTION E: height comparison  BST vs RB vs AVL  (the bound, gold-checked)")
    print("Feed each tree the WORST input (sorted) and measure height vs N.\n")
    print("| N  | BST h (=N-1) | RB h | RB bound 2log2(N+1) | AVL bound          |")
    print("|----|--------------|------|----------------------|--------------------|")
    gold = {}
    for n in [1, 2, 3, 4, 5, 8, 16, 32, 64]:
        keys = list(range(1, n + 1))
        bst = BST()
        rb = RBTree()
        for k in keys:
            bst.insert(k)
            rb.insert(k)
        bh = rb.check_invariants()
        rb_bound = 2 * math.log2(n + 1)
        avl_bound = 1.4405 * math.log2(n + 2) - 0.3277
        assert rb.height() <= rb_bound + 1e-9, f"RB height {rb.height()} > bound {rb_bound}"
        assert bh["all_ok"]
        assert bst.height() == n - 1
        print(f"| {n:<2} | {bst.height():<12} | {rb.height():<4} | "
              f"{rb_bound:<20.2f} | {avl_bound:<18.2f} |")
        if n in (8, 32, 64):
            gold[n] = {"bst_h": bst.height(), "rb_h": rb.height(),
                       "rb_bound": rb_bound, "bh": bh["bh"]}
    print()
    print("Reading the table: the BST column is a straight LINE (h = N-1, O(N)).")
    print("The RB column grows like log N, and ALWAYS stays under 2log2(N+1).")
    print("AVL is even tighter (< 1.44 log2(N+2)) but pays with more rotations.")
    print("\nWHY RB AND NOT AVL? Both are O(log N). AVL keeps height tighter so")
    print("LOOKUPS are slightly faster; RB does fewer rotations so INSERTS and")
    print("DELETES are cheaper and the rebalance is simpler. The tradeoff favors")
    print("RB for write-heavy / general use -> that is why C++ std::map, Java")
    print("TreeMap, Linux scheduler (CFS), and epoll all use Red-Black trees.")
    return gold


def section_gold_check(gold: dict) -> None:
    banner("GOLD CHECK  (black-height consistency -- the invariant that bounds height)")
    # re-run the canonical worst case N=32 sorted and pin numbers for the .html
    n = 32
    keys = list(range(1, n + 1))
    rb = RBTree()
    for k in keys:
        rb.insert(k)
    counts = rb.path_black_counts()
    distinct = set(counts)
    bh = counts[0] if counts else 0
    print(f"Sorted insert N={n}: every root->NIL path's black-node count = {bh}.")
    print(f"distinct path counts = {sorted(distinct)} "
          f"({'CONSISTENT' if len(distinct) == 1 else 'INCONSISTENT!'})")
    assert len(distinct) == 1, "black-height must be consistent"
    assert rb.height() <= 2 * math.log2(n + 1)
    print(f"\nGOLD values (pinned for bst_redblack.html):")
    print(f"  N=8  sorted: BST h={gold[8]['bst_h']}, RB h={gold[8]['rb_h']}, "
          f"bh={gold[8]['bh']}, bound={gold[8]['rb_bound']:.2f}")
    print(f"  N=32 sorted: BST h={gold[32]['bst_h']}, RB h={gold[32]['rb_h']}, "
          f"bh={gold[32]['bh']}, bound={gold[32]['rb_bound']:.2f}")
    print(f"  N=64 sorted: BST h={gold[64]['bst_h']}, RB h={gold[64]['rb_h']}, "
          f"bh={gold[64]['bh']}, bound={gold[64]['rb_bound']:.2f}")
    print(f"\n[check] RB black-height consistent across all paths (N={n}): OK")
    print(f"[check] RB h ({rb.height()}) <= 2log2({n}+1) ({2*math.log2(n+1):.2f}): OK")
    print(f"[check] BST sorted h ({n-1}) == N-1: OK")


# ============================================================================
# main
# ============================================================================

def main() -> None:
    print("bst_redblack.py - reference impl. "
          "All numbers below feed BST_REDBLACK.md.")
    print(f"height convention: EDGES (CLRS). single node h=0, empty h=-1.")

    section_bst_balanced_and_tower()
    section_rb_main_sequence()
    section_rotations()
    section_fixup_cases()
    gold = section_height_comparison()
    section_gold_check(gold)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
