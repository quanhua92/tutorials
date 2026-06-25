"""
free_space_map.py - Reference implementation of the PostgreSQL Free Space Map
(FSM): the data structure that lets INSERT find a page with enough free room
WITHOUT scanning every page.

This is the single source of truth that FREE_SPACE_MAP.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 free_space_map.py

=========================================================================
THE INTUITION (read this first) -- the warehouse with the shelves
=========================================================================
Imagine a warehouse (the table) with thousands of shelves (pages), each 8 KB.
When a new box (a tuple) arrives, you must put it on a shelf that has enough
EMPTY room. Two ways to find one:

  * LINEAR SCAN : walk down every aisle, measuring every shelf until you find
                  one that fits. For N shelves that is O(N) reads. On a billion
                  -row table that is catastrophic.
  * FSM         : keep a DIRECTORY by the entrance. Each shelf's free space is
                  rounded to a coarse GRADE 0..255 (a single byte). The grades
                  are stacked into a MAX-TREE: the entry for an aisle holds the
                  BEST grade of any shelf in that aisle; the building entry holds
                  the BEST grade in the building. To seat a box:
                    1. read the building entry -> know in O(1) whether ANY shelf
                       has room at all (if not, build a new shelf = extend the
                       relation by one page);
                    2. follow a path down the tree where each node's grade is
                       >= what you need -> O(log N) descent to a fitting shelf.

THE REASON THE FSM EXISTS: PostgreSQL never moves a tuple once placed, and a
page is only 8 KB, so inserts must constantly find a half-empty page. Scanning
the whole heap every INSERT is unthinkable. The FSM turns that O(N) scan into an
O(log N) tree walk, while costing only ONE BYTE per page.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  page         : a fixed 8 KB (BLCKSZ = 8192) block of a table file. Tuples live
                 between the line-pointer array (top) and the tuple area; the
                 gap between them is the FREE SPACE.
  free space   : bytes of room left on a page for new tuples.
                 free_space = pd_upper - pd_lower.
  category     : a coarse grade 0..255 for the free space. ONE BYTE per page.
                 category = floor(free_space / 32).  (32 = BLCKSZ / 256.)
                 So category N  <=>  at least N*32 bytes free (bucket of 32).
  leaf node    : a tree node holding ONE page's category. One leaf per page.
  internal node: a node holding MAX(category of left child, right child).
                 The max is the key invariant: "best free space in my subtree."
  root         : the top node = MAX free space category in the WHOLE table.
                 Reading just the root tells you the best case anywhere.
  search       : "I need X bytes" -> need_cat = floor(X/32) -> descend the tree
                 always taking a child whose value >= need_cat, until a leaf.
  bubble-up    : after a page's free space changes, update its leaf, then walk
                 UP recomputing each parent = max(children) until one is stable.
  slot / fp_next_slot : a round-robin start hint so concurrent backends don't
                 all pile onto the same page (spreads inserts). Left-first here.
  FSM page     : the max-tree is itself stored inside a normal 8 KB page, with a
                 tiny header (FSMPageHeaderData) + the tree as a flat byte array.
  _fsm fork    : the separate file (relation's FSM fork) holding all FSM pages.

=========================================================================
THE LINEAGE
=========================================================================
  Linear scan  (naive)           : O(N) page reads per INSERT. Unusable on big
                                   tables.
  Per-page byte array (the map)  : O(1) to read one page's free space, but still
                                   O(N) to FIND a fitting page (must scan array).
  + MAX-TREE above the bytes     : the FSM. O(log N) search, O(log N) update,
                                   O(1) "does any page fit?" (just read root).
                                   (PostgreSQL 8.4+, per-relation extensible fork.)

KEY FORMULAS (all verified against the PostgreSQL source README, and asserted
in code below):
    BLCKSZ          = 8192                              (default block size)
    FSM_CATEGORIES  = 256                               (one byte, 0..255)
    FSM_CAT_STEP    = BLCKSZ / FSM_CATEGORIES = 32      (bytes per category)
    category(fs)    = min(255, floor(fs / 32))          (free space -> grade)
    cat_to_space(c) = c * 32  (c==255 -> 8191)          (grade -> min bytes)
    need_cat(X)     = floor(X / 32)                     (bytes wanted -> grade)
    leaf count / FSM page  ~= (BLCKSZ - header) / 2 ~ 4000   (fanout F)
    levels to cover 2^32 blocks: F^3 = 4000^3 = 6.4e10 > 2^32  -> 3 levels

Sources:
  [1] PostgreSQL source, src/backend/storage/freespace/README
      "the stored value is the free space divided by BLCKSZ/256 (rounding
       down)" ... "a non-leaf node stores the max amount of free space on any
       of its children" ... "(BLCKSZ - headers) / 2, or ~4000 with default
       BLCKSZ" ... "three levels is enough ... (4000^3 > 2^32)".
  [2] PostgreSQL docs, storage-fsm.html:
      "Within each FSM page is a binary tree, stored in an array with one byte
       per node. Each leaf node represents a heap page ... In each non-leaf
       node, the max of its children's values is stored."

The array layout used here (and by PostgreSQL) is the standard binary-heap
array: root at index 0; for node i, left child = 2i+1, right child = 2i+2,
parent = (i-1)//2. With 8 leaves there are 15 nodes; leaves live at indices
[7 .. 14] and map to heap pages [0 .. 7].
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# 0. CONSTANTS  (match the PostgreSQL source)
# ----------------------------------------------------------------------------
BLCKSZ = 8192            # default page size, bytes
FSM_CATEGORIES = 256     # one byte per page: category in 0..255
FSM_CAT_STEP = BLCKSZ // FSM_CATEGORIES   # = 32 bytes per category bucket

# A complete binary tree over N_PAGES leaves. Leaves are the LAST N_PAGES slots
# of the heap-array; internal nodes fill the front.
N_PAGES = 8
N_NODES = 2 * N_PAGES - 1          # 15 nodes total
LEAF_BASE = N_PAGES - 1            # leaf for page p is at index LEAF_BASE + p


BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code FREE_SPACE_MAP.md walks)
# ============================================================================

def space_to_cat(free_space: int) -> int:
    """Free space (bytes) -> category 0..255.  Mirrors PostgreSQL
    fsm_space_to_cat(): floor(free_space / (BLCKSZ/256)), capped at 255.

    >>> space_to_cat(0)
    0
    >>> space_to_cat(2000)
    62
    >>> space_to_cat(6000)
    187
    >>> space_to_cat(8191)
    255
    """
    if free_space >= BLCKSZ - 1:        # 8191: page essentially empty -> 255
        return 255
    cat = free_space // FSM_CAT_STEP     # floor(fs / 32)
    return min(cat, 255)


def cat_to_space(cat: int) -> int:
    """Category -> the MINIMUM free space it represents. Mirrors PostgreSQL
    fsm_cat_to_space(). Category N means "at least N*32 bytes free".

    >>> cat_to_space(62)
    1984
    >>> cat_to_space(255)
    8191
    """
    if cat == 255:
        return BLCKSZ - 1
    return cat * FSM_CAT_STEP            # cat * 32


def need_cat(bytes_needed: int) -> int:
    """Bytes wanted by the new tuple -> the category we must search for."""
    return space_to_cat(bytes_needed)


def parent(i: int) -> int:
    """Parent index in the heap-array (0-indexed). parent(0) = -1."""
    return (i - 1) // 2


def left_child(i: int) -> int:
    return 2 * i + 1


def right_child(i: int) -> int:
    return 2 * i + 2


def build_tree(leaf_cats: list[int]) -> list[int]:
    """Build the FSM max-tree from a list of per-page categories.

    The tree is a heap-array of length 2*len(leaf_cats)-1. Leaves go at the
    back; every internal node = max(left child, right child). We fill internal
    nodes bottom-up so each parent is computed after its children.
    """
    n = len(leaf_cats)
    tree = [0] * (2 * n - 1)
    tree[n - 1:2 * n - 1] = leaf_cats          # leaves at the back
    for i in range(n - 2, -1, -1):              # internal nodes, bottom-up
        tree[i] = max(tree[left_child(i)], tree[right_child(i)])
    return tree


def search(tree: list[int], target_cat: int, start_slot: int = 0):
    """Find the first page (in page order) whose category >= target_cat.

    Returns (page_index, path_of_node_indices) or (None, []) if the root itself
    is below target (no page fits). The descent always prefers the LEFT child
    when it qualifies; because each internal node = max(children), at least one
    child always qualifies once the parent does, so the walk never dead-ends.

    (PostgreSQL additionally rotates the start slot via fp_next_slot to spread
    concurrent inserts; the math is identical, only the entry point differs.)
    """
    if tree[0] < target_cat:                    # root = best in whole table
        return None, []                          # no page fits -> extend table
    node = 0
    path = [node]
    n_pages = (len(tree) + 1) // 2
    while node < n_pages - 1:                    # descend while internal
        lc = left_child(node)
        if tree[lc] >= target_cat:               # prefer left (lower page #)
            node = lc
        else:                                    # right must qualify (max invariant)
            node = right_child(node)
        path.append(node)
    page = node - (n_pages - 1)
    return page, path


def update(tree: list[int], page: int, new_cat: int):
    """Set page `page`'s category to `new_cat`, then BUBBLE the max upward.

    Returns the list of node indices touched (for display). We stop as soon as a
    parent's value is unchanged, because no ancestor above it can change either
    (its max depended only on this now-stable subtree).
    """
    leaf = LEAF_BASE + page
    tree[leaf] = new_cat
    touched = [leaf]
    node = parent(leaf)
    while node >= 0:
        new_val = max(tree[left_child(node)], tree[right_child(node)])
        if tree[node] == new_val:                # stable -> stop bubbling
            break
        tree[node] = new_val
        touched.append(node)
        node = parent(node)
    return touched


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def tree_ascii(tree: list[int], n_pages: int = N_PAGES) -> str:
    """Render the heap-array tree as a pretty indented pyramid (for humans)."""
    lines = []
    depth = n_pages.bit_length()        # levels for n_pages leaves (8 -> 4)
    # level l covers indices [2^l - 1, 2^(l+1) - 2]
    for level in range(depth):
        lo = (1 << level) - 1
        hi = (1 << (level + 1)) - 1     # exclusive
        nodes = tree[lo:hi]
        if not nodes:
            break
        pad = " " * (2 * (depth - level))
        gap = " " * (4 * (depth - level))
        cells = []
        for k, v in enumerate(nodes):
            idx = lo + k
            tag = "root" if level == 0 else ("page " + str(idx - (n_pages - 1))
                                             if idx >= n_pages - 1 else "")
            cells.append(f"[{idx}]={v:>3}{(' ('+tag+')') if tag else ''}")
        lines.append(pad + gap.join(cells))
    return "\n".join(lines)


# ============================================================================
# 3. THE DETERMINISTIC INPUT: 8 pages with fixed free space
#    Same numbers the .html recompute in JS -- byte-for-byte identical.
# ============================================================================

# free space, in bytes, for heap pages 0..7  (deterministic, hand-picked so the
# worked example shows a non-trivial "go left, fail, try sibling" search)
PAGE_FREE_SPACE = [1000, 3000, 500, 4500, 200, 6000, 800, 3500]


# ----------------------------------------------------------------------------
# SECTION A: build the FSM tree for 8 pages
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: build the FSM for 8 pages  (free space -> category -> tree)")
    print(f"Constants: BLCKSZ={BLCKSZ}, FSM_CATEGORIES={FSM_CATEGORIES}, "
          f"FSM_CAT_STEP={FSM_CAT_STEP} bytes/category\n")
    print("Each page's free space is folded to a 1-byte category "
          f"(floor(fs/{FSM_CAT_STEP}), capped at 255):\n")
    print("| page | free space (B) | category = floor(fs/32) | bucket >= (B) |")
    print("|------|----------------|--------------------------|--------------|")
    leaf_cats = []
    for p, fs in enumerate(PAGE_FREE_SPACE):
        c = space_to_cat(fs)
        leaf_cats.append(c)
        print(f"| {p:<4} | {fs:<14} | {c:<24} | {cat_to_space(c):<12} |")
    print()
    tree = build_tree(leaf_cats)
    print("Stack the leaf categories into a MAX-TREE (each internal node = "
          "max of its two children). Stored as a heap-array of 15 bytes:\n")
    print(tree_ascii(tree))
    print(f"\nFlat array  tree[{N_NODES}] = {tree}")
    print(f"Root (tree[0]) = {tree[0]}  =  MAX category in the whole table  "
          f"= page {leaf_cats.index(tree[0])}'s free space (the emptiest page).")
    return tree, leaf_cats


# ----------------------------------------------------------------------------
# SECTION B: search -- "I need 2000 bytes"
# ----------------------------------------------------------------------------

def section_b(tree, leaf_cats):
    banner("SECTION B: search  --  \"I need 2000 bytes\"  ->  O(log N) descent")
    need = 2000
    tcat = need_cat(need)
    print(f"1. need_cat = floor({need} / {FSM_CAT_STEP}) = {tcat}\n")
    print(f"2. Read root tree[0] = {tree[0]} >= {tcat}?  "
          f"{'YES -> a fitting page exists' if tree[0] >= tcat else 'NO -> extend relation'}.")
    print("   (This O(1) check is the whole point of keeping a max-tree: the\n"
          "    root alone answers 'does ANY page have room?')\n")
    page, path = search(tree, tcat)
    print("3. Descend, always stepping to a child whose value >= "
          f"{tcat} (prefer left = lower page #):\n")
    n_pages = N_PAGES
    for node in path:
        kind = ("root" if node == 0 else
                ("leaf -> page " + str(node - (n_pages - 1))
                 if node >= n_pages - 1 else "internal"))
        print(f"     node tree[{node}] = {tree[node]:<3}  ({kind})  "
              f"{'OK' if tree[node] >= tcat else 'too small -> try sibling'}")
    print(f"\n4. RESULT: insert into page {page}  "
          f"(free space = {PAGE_FREE_SPACE[page]} B, category {leaf_cats[page]}).")
    print(f"   Visited {len(path)} tree nodes out of {N_NODES} total  "
          f"-> O(log N), NOT O(N) page reads.\n")

    # the quantization teaching point
    print("QUANTIZATION NOTE: category is a floor in 32-byte buckets, so the FSM")
    print(f"guarantees the found page has >= cat_to_space({tcat}) = "
          f"{cat_to_space(tcat)} B, not strictly >= {need} B. A category-{tcat}")
    print("page could hold as little as 1984 B; PostgreSQL therefore RE-CHECKS")
    print("the real free space (pd_upper - pd_lower) on the page before insert,")
    print("and if stale, lowers the leaf and retries. The FSM is a fast FILTER,\n"
          "not an exact account. In this example page 1 has 3000 B >= 2000 B, fine.\n")

    # GOLD CHECK 1: FSM invariant + concrete example
    fs_found = PAGE_FREE_SPACE[page]
    assert leaf_cats[page] >= tcat, "found page category must be >= target"
    assert fs_found >= cat_to_space(tcat), "FSM guarantees >= cat_to_space"
    assert fs_found >= need, "worked example: page 1 must really fit 2000 B"
    print(f"[check] found page {page}: cat {leaf_cats[page]} >= {tcat} AND "
          f"{fs_found} B >= {cat_to_space(tcat)} B (FSM guarantee) "
          f"AND {fs_found} B >= {need} B (example):  OK")
    return page


# ----------------------------------------------------------------------------
# SECTION C: update -- insert a tuple in page 3, bubble the max up
# ----------------------------------------------------------------------------

def section_c(tree, leaf_cats):
    banner("SECTION C: update  --  insert a tuple in page 3, bubble the max UP")
    page = 3
    tuple_bytes = 3000
    print(f"Insert a {tuple_bytes}-byte tuple into page {page}.")
    before_fs = PAGE_FREE_SPACE[page]
    before_cat = leaf_cats[page]
    after_fs = before_fs - tuple_bytes
    after_cat = space_to_cat(after_fs)
    print(f"  page {page} free space: {before_fs} B (cat {before_cat})  ->  "
          f"{after_fs} B (cat {after_cat})\n")
    print("BEFORE update, the tree was:")
    print(tree_ascii(tree))

    touched = update(tree, page, after_cat)
    # keep PAGE_FREE_SPACE/leaf_cats consistent for later sections
    leaf_cats[page] = after_cat

    print("\nAFTER setting leaf and bubbling max up to the root (stop on no-change):")
    print(tree_ascii(tree))
    print(f"\nBUBBLE-UP path (nodes recomputed): {touched}")
    print(f"  leaf tree[{LEAF_BASE + page}] = {after_cat}")
    for k in range(1, len(touched)):
        n = touched[k]
        print(f"  tree[{n}] = max(tree[{left_child(n)}]={tree[left_child(n)]}, "
              f"tree[{right_child(n)}]={tree[right_child(n)]}) = {tree[n]}"
              + ("  <- unchanged, STOP" if k == len(touched) - 1 else ""))
    print(f"\nTree mutated in place: tree = {tree}")

    # GOLD CHECK 2: invariant holds after update -- every node = max(children)
    n_pages = N_PAGES
    ok = True
    for i in range(n_pages - 1):
        if tree[i] != max(tree[left_child(i)], tree[right_child(i)]):
            ok = False
            print(f"  BROKEN at tree[{i}]={tree[i]} (children {tree[left_child(i)]},"
                  f"{tree[right_child(i)]})")
    assert ok
    print(f"\n[check] every internal node == max(children) after update:  OK")

    # show the search result changed: big request no longer lands on page 3
    print("\nConsequence: page 3 is no longer a great target. Search 4000 B now:")
    big_cat = need_cat(4000)
    pg2, _ = search(tree, big_cat)
    fs2 = after_fs if pg2 == page else PAGE_FREE_SPACE[pg2]
    print(f"  need_cat(4000) = {big_cat}; search now returns page {pg2} "
          f"(free space {fs2} B, cat {leaf_cats[pg2]}).")
    assert leaf_cats[pg2] >= big_cat
    print(f"  (before the update, the same query returned page 3; now its "
          f"category {after_cat} < {big_cat} so the tree correctly routes "
          f"elsewhere.)")
    return tree, leaf_cats


# ----------------------------------------------------------------------------
# SECTION D: the array representation -- a page is header + flat byte array
# ----------------------------------------------------------------------------

def section_d(tree):
    banner("SECTION D: the array representation  "
           "(FSM page = header + flat byte heap-array)")
    print("The tree from Section A-C is NOT a pile of pointers. It is a single\n"
          "8 KB page laid out as:\n")
    print("    +---------------------------+  byte 0\n"
          "    | FSMPageHeaderData         |     (one int: fp_next_slot, the\n"
          "    |   fp_next_slot (int32)    |      round-robin search hint)\n"
          "    +---------------------------+  byte ~8\n"
          "    | fp_nodes[0..N_NODES-1]    |     the max-tree as a flat byte\n"
          "    |   root, then internal,    |      array -- no child pointers!\n"
          "    |   then the 8 leaves       |\n"
          "    +---------------------------+\n")
    print("Indices are computed arithmetically (the binary-heap trick), so there\n"
          "are NO pointers -- just byte offsets:\n")
    print("    parent(i)     = (i - 1) // 2")
    print("    left_child(i) = 2*i + 1")
    print("    right_child(i)= 2*i + 2\n")
    print("For our 8-leaf tree the 15 bytes on disk are:\n")
    print("    index:  " + " ".join(f"{i:>4}" for i in range(N_NODES)))
    print("    value:  " + " ".join(f"{v:>4}" for v in tree))
    print("    role:   " + " ".join(
        ("root" if i == 0 else
         ("L" + str(i - LEAF_BASE) if i >= LEAF_BASE else "."))
        .rjust(4) for i in range(N_NODES)))
    print("  (role: root | . = internal | Lk = leaf for page k)\n")
    print("Worked index math:")
    for p in (0, 1, 5):
        leaf = LEAF_BASE + p
        par = parent(leaf)
        print(f"  page {p} -> leaf index {leaf}, parent index {par} "
              f"= max(tree[{left_child(par)}]={tree[left_child(par)]}, "
              f"tree[{right_child(par)}]={tree[right_child(par)]}) = {tree[par]}")
    print(f"\nWhy a flat array? Locality + zero per-child pointer overhead: the\n"
          f"whole tree for ~{N_PAGES} pages fits in {N_NODES} contiguous bytes, so a\n"
          f"search streams through one cache line after another with no chasing.")

    # GOLD CHECK 3: index math is self-consistent with the heap-array
    for i in range(1, N_NODES):
        assert parent(left_child(i)) == i and parent(right_child(i)) == i
    print(f"\n[check] parent(child(i)) == i for all internal nodes:  OK")


# ----------------------------------------------------------------------------
# SECTION E: extension -- millions of pages -> 3-level tree of FSM pages
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: extension  --  millions of pages -> a 3-level tree of FSM pages")
    header_bytes = 8                              # MAXALIGN(sizeof(int)) ~ 8
    leaves_per_fsm_page = (BLCKSZ - header_bytes) // 2   # ~4092, README says ~4000
    print(f"One FSM page is itself an 8 KB page. After the {header_bytes}-byte header,\n"
          f"the tree array holds ~(BLCKSZ-header)/2 = {leaves_per_fsm_page} leaf bytes,\n"
          f"so ONE FSM page tracks the free space of ~{leaves_per_fsm_page} heap pages.\n")
    fanout = leaves_per_fsm_page
    print("To scale beyond a single FSM page, PostgreSQL stacks FSM pages into the\n"
          "SAME max-tree idea, but ACROSS pages -- a tree of trees (the _fsm fork):\n")
    print("        +-----------------------+   level 2 (root FSM page, blk 0)")
    print("        | root FSM page         |     leaves = best(root) of each L1 page")
    print("        +-----------+-----------+")
    print("        |level-1 FSM|  ...      |   level 1")
    print("        +-----+-----+-----+-----+")
    print("        |L0 FSM|L0 FSM| ... |   |   level 0 (bottom)")
    print("        +--...--+--...--+")
    print("        heap pages (each leaf = one heap page's category)")
    print()
    print("Invariants cross the page boundary exactly like within a page:")
    print("  - a level-0 FSM page's ROOT value is copied into a LEAF of its parent")
    print("    (level-1) page; a level-1 root is copied into a leaf of the root page.")
    print("  - search walks DOWN through the page tree, updating bubbles UP the same way.")
    print()
    cap3 = fanout ** 3
    maxblocks = 2 ** 32 - 1
    print("How many levels are needed for the largest possible relation?\n")
    print(f"  fanout F ~ {fanout} heap pages per FSM page")
    print(f"  F^1 = {fanout:,}  pages")
    print(f"  F^2 = {fanout**2:,}  pages")
    print(f"  F^3 = {cap3:,}  pages   >  2^32 - 1 = {maxblocks:,}")
    print(f"\n  -> THREE levels cover the maximum relation size "
          f"({fanout}^3 = {cap3:,} > 2^32). Postgres fixes the tree height at 3.\n")
    print("Storage cost: ONE byte per heap page on disk (the leaf), plus the upper\n"
          "levels which add only ~1/F + 1/F^2 + ... overhead. So a 1 TB table of\n"
          "~130M pages pays ~130 MB for a complete, O(log N)-searchable free map.\n")

    # GOLD CHECK 4: three levels really do cover 2^32 blocks
    assert cap3 > maxblocks, "3 FSM levels must cover 2^32 blocks"
    print(f"[check] {fanout}^3 = {cap3:,} > 2^32-1 = {maxblocks:,}:  OK  "
          f"(3 levels are sufficient)")


# ============================================================================
# main
# ============================================================================

def main():
    print("free_space_map.py - reference impl. All numbers below feed "
          "FREE_SPACE_MAP.md.")
    print(f"BLCKSZ={BLCKSZ}  FSM_CATEGORIES={FSM_CATEGORIES}  "
          f"FSM_CAT_STEP={FSM_CAT_STEP}  N_PAGES={N_PAGES}  N_NODES={N_NODES}")

    tree, leaf_cats = section_a()
    section_b(tree, leaf_cats)
    tree, leaf_cats = section_c(tree, leaf_cats)
    section_d(tree)
    section_e()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
