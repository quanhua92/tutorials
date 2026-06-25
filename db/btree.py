"""
btree.py - Reference implementation of the B+tree, the workhorse database index.

This is the single source of truth that BTREE.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 btree.py

============================================================================
THE INTUITION (read this first) - the sorted notebook with tab dividers
============================================================================
Imagine a giant sorted notebook. Finding one value by flipping every page is
O(N). So you tape a set of TAB DIVIDERS across the top, each saying "keys below
this live to the LEFT, keys at/above live to the RIGHT". Now a lookup just reads
the dividers and jumps. But one strip of dividers only speeds things up by the
number of tabs. So you stack ANOTHER strip of dividers on top that points at the
strips below, and another on top of that. That stack of divider-strips is the
B+tree:

   * INTERNAL nodes  = the divider strips. They hold ONLY separator keys + child
                       pointers, never data. They exist purely to route searches.
   * LEAF nodes      = the bottom pages, holding the actual (key -> value) pairs
                       in sorted order. THIS is where the data lives.
   * The "+" in B+   = every leaf is chained to its right neighbour by a "next"
                       pointer. So once you reach the right leaf, a RANGE SCAN is
                       just "walk right along the chain" - no re-traversal needed.
   * "balanced"      = every root-to-leaf path has the SAME length, so a lookup
                       is ALWAYS height page-reads, independent of which key or
                       how lopsided the inserts were. That determinism is the
                       whole reason databases use B+trees for primary indexes.

WHY IT SCALES: a page is fixed-size (e.g. 4 KB). With 8-byte keys you fit ~256
children per internal page (the FANOUT). Three levels of 256-way branching index
256 * 256 * 256 = ~16.7 MILLION rows. So 1 million rows live in a tree just
3 pages tall - a point lookup reads exactly 3 pages. That is the magic: height
grows as log_fanout(N), and fanout is huge, so height stays tiny.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   order m        : the MAX number of CHILDREN an internal node may hold
                    (= max keys + 1). Here m = 4, so max 3 keys / 4 children.
   fanout         : children per internal node. The key number for scaling.
                    ~page_size / (key_bytes + ptr_bytes). Big fanout = short tree.
   internal node  : a "divider strip". Holds separator keys + child pointers.
                    A key k_i routes: keys < k_i go to child i, keys >= k_i go
                    right. Internal nodes store NO values.
   leaf node      : a bottom page. Holds the sorted (key, value) pairs. This is
                    where lookups end and where range scans walk.
   separator key  : a key copied/moved into a parent to tell children apart. It
                    is NOT data (except it does appear in a leaf too, by the
                    B+tree "copy up" rule).
   page split     : when a node overflows (gets max_keys+1 entries) on insert, it
                    splits in half; the median is pushed to the parent. If the
                    parent also overflows, the split propagates upward; if the
                    root splits, a new root is made and the tree grows TALLER by
                    one level. (Splits make the tree grow UP, never DOWN.)
   page merge /   : on delete, if a node drops below MIN occupancy it first tries
   borrow           to BORROW one entry from a sibling; if no sibling can spare,
                    it MERGES with a sibling and pulls the separator down. Merges
                    propagate up and can shrink the tree.
   next pointer   : the right-sibling link on every leaf - the "+" of B+tree.
                    Enables O(leaves hit) range scans with no re-traversal.
   height         : number of levels (root=1). A point lookup costs `height` page
                    reads. Balanced => every path is exactly `height` long.
   Lehman-Yao     : the concurrency trick real systems (PostgreSQL) use: each page
   / Blink tree     stores a "high key" (the max key it may hold) plus a link to
                    its right sibling, so a reader can move RIGHT to a sibling if
                    a concurrent insert pushed the searched key past this page.
                    Lets reads/writes proceed with only short page latches.

============================================================================
THE LINEAGE (sources)
============================================================================
   B-tree  (Bayer & McCreight 1972, "Organization and Maintenance of Large
           Ordered Indexes"): the balanced, page-splitting, multi-way search
           tree. Every modern DB index descends from this.
   B+tree  (Knuth; Comer 1979 "The Ubiquitous B-Tree"): variant where data lives
           ONLY in leaves and leaves are linked. This is what "B-tree index"
           means in PostgreSQL/MySQL/SQLite/etc.
   Lehman- (Lehman & Yoa... Leung) 1981, "Efficient Locking for Concurrent
   Yao       Operations on B-Trees": the high-concurrency B-link-tree. PostgreSQL,
             SQLite, InnoDB all use a descendant of this.
   Wedder  even taller concurrency refinements; the practical takeaway: short
   /OLTP    latches + right-sibling "high key" links = lock-free-ish reads.

KEY FORMULAS (all asserted/printed in the sections below):
   max_keys per node            = m - 1                         (here 3)
   min_keys per non-root leaf   = ceil((m-1)/2)                  (here 2)
   min children per non-root int= ceil(m/2)                      (here 2)
   leaf split (overflow=4)      : left=[k0,k1], right=[k2,k3],
                                  COPY k2 (smallest of right) up to parent
   internal split (overflow=4)  : left=[k0,k1], right=[k3],
                                  MOVE k2 (median) up to parent
   fanout (bytes)               = page_size / (key_bytes + ptr_bytes)  (4KB -> ~256)
   max rows in height-h tree    = fanout^(h-1) * leaf_cap          (3 lvl -> ~16.7M)
   height for N rows            = 1 + ceil(log_fanout(ceil(N/leaf_cap)))
   point-lookup I/O             = height                          (in pages)

Conventions:
   m           = order (max children of an internal node)
   All keys are unique ints (a primary-key index). Values are ints; in a real
   index the "value" is a TID / row pointer. See HEAP_VS_CLUSTERED.md 🔗.
"""

from __future__ import annotations

import bisect
import math

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code BTREE.md walks through)
# ============================================================================

class Node:
    """One B+tree page. Either an internal (divider) node or a leaf (data) node.

    Leaf:     keys[i] / values[i] are parallel arrays; `next` points right.
    Internal: keys[i] are separators; children has len(keys)+1 entries;
              children[i] holds keys < keys[i], children[i+1] holds keys >= keys[i].
    """

    __slots__ = ("leaf", "keys", "values", "children", "next")

    def __init__(self, leaf: bool):
        self.leaf = leaf
        self.keys: list = []
        self.values: list = []          # leaf-only, parallel to keys
        self.children: list = []        # internal-only, len == len(keys)+1
        self.next: "Node | None" = None  # leaf-only: right sibling


class BPlusTree:
    """A textbook B+tree of a given order. Single-threaded (no latches).

    The algorithms are the classic split-on-insert / borrow-or-merge-on-delete.
    PostgreSQL's real index adds Lehman-Yao "high keys" + right links for
    concurrency; the page mechanics here are identical. See BTREE.md §9.
    """

    def __init__(self, order: int):
        self.order = order                       # m: max children of internal
        self.max_keys = order - 1                # max keys in any node
        self.min_leaf_keys = (self.max_keys + 1) // 2   # ceil(max_keys/2): here 2
        self.min_children = (order + 1) // 2            # ceil(m/2): here 2
        self.root = Node(leaf=True)
        self.trace = False                       # verbose split/merge logging

    # ---- INSERT ---------------------------------------------------------

    def insert(self, key, value):
        split = self._insert(self.root, key, value)
        if split is not None:                    # root split -> new root
            sep, new_right = split
            new_root = Node(leaf=False)
            new_root.keys = [sep]
            new_root.children = [self.root, new_right]
            self.root = new_root
            if self.trace:
                print(f"    [NEW ROOT] new root keys=[{sep}] "
                      f"-> height grows to {len(self.levels())}")

    def _insert(self, node, key, value):
        """Insert into `node`'s subtree. Return (sep, new_right) if it split."""
        if node.leaf:
            i = bisect.bisect_left(node.keys, key)
            assert not (i < len(node.keys) and node.keys[i] == key), \
                f"duplicate key {key}"
            node.keys.insert(i, key)
            node.values.insert(i, value)
            if len(node.keys) > self.max_keys:
                return self._split_leaf(node)
            return None
        # internal: route down
        ci = bisect.bisect_right(node.keys, key)
        split = self._insert(node.children[ci], key, value)
        if split is None:
            return None
        sep, new_right = split
        node.keys.insert(ci, sep)
        node.children.insert(ci + 1, new_right)
        if len(node.keys) > self.max_keys:
            return self._split_internal(node)
        return None

    def _split_leaf(self, node):
        overflow = list(node.keys)
        mid = len(overflow) // 2                 # 4 -> 2
        right = Node(leaf=True)
        right.keys = node.keys[mid:]
        right.values = node.values[mid:]
        node.keys = node.keys[:mid]
        node.values = node.values[:mid]
        # splice into the leaf chain
        right.next = node.next
        node.next = right
        sep = right.keys[0]                      # COPY smallest of right up
        if self.trace:
            print(f"    [SPLIT leaf]   overflow {overflow} -> "
                  f"left={node.keys} right={right.keys}; COPY sep {sep} up")
        return (sep, right)

    def _split_internal(self, node):
        overflow = list(node.keys)
        mid = len(overflow) // 2                 # 4 -> 2
        push_key = node.keys[mid]                # MOVE median up
        right = Node(leaf=False)
        right.keys = node.keys[mid + 1:]
        right.children = node.children[mid + 1:]
        node.keys = node.keys[:mid]
        node.children = node.children[:mid + 1]
        if self.trace:
            print(f"    [SPLIT internal] overflow keys {overflow} -> "
                  f"MOVE {push_key} up; left keys={node.keys} right keys={right.keys}")
        return (push_key, right)

    # ---- POINT LOOKUP ---------------------------------------------------

    def find(self, key):
        """Return the value for `key`, or None. No tracing."""
        node = self.root
        while not node.leaf:
            node = node.children[bisect.bisect_right(node.keys, key)]
        i = bisect.bisect_left(node.keys, key)
        if i < len(node.keys) and node.keys[i] == key:
            return node.values[i]
        return None

    def search_trace(self, key):
        """Like find() but records each comparison for the worked example."""
        log = []
        comparisons = 0
        node = self.root
        depth = 0
        while not node.leaf:
            i = len(node.keys)
            detail = []
            for j, k in enumerate(node.keys):
                comparisons += 1
                if key < k:
                    i = j
                    detail.append(f"{key}<{k} -> child {j}")
                    break
                detail.append(f"{key}>={k}")
            else:
                detail.append(f"past all -> child {len(node.keys)}")
            log.append((depth, "INT ", list(node.keys), detail))
            node = node.children[i]
            depth += 1
        # leaf
        found_idx = -1
        detail = []
        for j, k in enumerate(node.keys):
            comparisons += 1
            if key == k:
                found_idx = j
                detail.append(f"{key}=={k} FOUND@{j}")
                break
            if key < k:
                detail.append(f"{key}<{k} (absent, stop)")
                break
            detail.append(f"{key}>{k}")
        else:
            detail.append("end of leaf (absent)")
        value = node.values[found_idx] if found_idx >= 0 else None
        log.append((depth, "LEAF", list(node.keys), detail))
        return {"value": value, "comparisons": comparisons, "log": log}

    # ---- RANGE SCAN (the "+" of B+tree) ---------------------------------

    def range_scan(self, lo, hi):
        """Return (matched [(k,v)...], [leaves visited in chain order])."""
        node = self.root
        while not node.leaf:
            node = node.children[bisect.bisect_right(node.keys, lo)]
        results = []
        visited = []
        while node is not None:
            visited.append(node)
            stop = False
            for k, v in zip(node.keys, node.values):
                if k > hi:
                    stop = True
                    break
                if k >= lo:
                    results.append((k, v))
            if stop:
                break
            node = node.next
        return results, visited

    # ---- DELETE (borrow from sibling, else merge) -----------------------

    def delete(self, key):
        self._actions = []
        self._delete(self.root, key)
        # root collapse: an internal root with one child is redundant
        if not self.root.leaf and len(self.root.children) == 1:
            old = self.root
            self.root = self.root.children[0]
            self._actions.append(("root-collapse", old.keys))
        return self._actions

    def _delete(self, node, key):
        if node.leaf:
            i = bisect.bisect_left(node.keys, key)
            if i < len(node.keys) and node.keys[i] == key:
                node.keys.pop(i)
                node.values.pop(i)
            return
        ci = bisect.bisect_right(node.keys, key)
        child = node.children[ci]
        self._delete(child, key)
        if self._underflows(child):
            self._rebalance(node, ci)

    def _underflows(self, node):
        if node.leaf:
            return len(node.keys) < self.min_leaf_keys
        return len(node.children) < self.min_children

    def _rebalance(self, parent, ci):
        child = parent.children[ci]
        left = parent.children[ci - 1] if ci > 0 else None
        right = parent.children[ci + 1] if ci < len(parent.children) - 1 else None
        if child.leaf:
            # BORROW from left sibling
            if left is not None and len(left.keys) > self.min_leaf_keys:
                child.keys.insert(0, left.keys.pop())
                child.values.insert(0, left.values.pop())
                parent.keys[ci - 1] = child.keys[0]
                self._actions.append(("borrow-left", child.keys))
                return
            # BORROW from right sibling
            if right is not None and len(right.keys) > self.min_leaf_keys:
                child.keys.append(right.keys.pop(0))
                child.values.append(right.values.pop(0))
                parent.keys[ci] = right.keys[0]
                self._actions.append(("borrow-right", child.keys))
                return
            # MERGE (no sibling can spare)
            if left is not None:
                left.keys.extend(child.keys)
                left.values.extend(child.values)
                left.next = child.next
                parent.keys.pop(ci - 1)
                parent.children.pop(ci)
                self._actions.append(("merge-into-left", left.keys))
            else:
                child.keys.extend(right.keys)
                child.values.extend(right.values)
                child.next = right.next
                parent.keys.pop(ci)
                parent.children.pop(ci + 1)
                self._actions.append(("merge-right-into-child", child.keys))
            return
        # ---- internal node underflow ----
        if left is not None and len(left.children) > self.min_children:
            # pull separator down, move left's last child over, push left's last key up
            child.keys.insert(0, parent.keys[ci - 1])
            child.children.insert(0, left.children.pop())
            parent.keys[ci - 1] = left.keys.pop()
            self._actions.append(("borrow-left-internal", child.keys))
            return
        if right is not None and len(right.children) > self.min_children:
            child.keys.append(parent.keys[ci])
            child.children.append(right.children.pop(0))
            parent.keys[ci] = right.keys.pop(0)
            self._actions.append(("borrow-right-internal", child.keys))
            return
        # MERGE internal: separator comes DOWN between the two key sets
        if left is not None:
            left.keys.append(parent.keys[ci - 1])
            left.keys.extend(child.keys)
            left.children.extend(child.children)
            parent.keys.pop(ci - 1)
            parent.children.pop(ci)
            self._actions.append(("merge-internal-left", left.keys))
        else:
            child.keys.append(parent.keys[ci])
            child.keys.extend(right.keys)
            child.children.extend(right.children)
            parent.keys.pop(ci)
            parent.children.pop(ci + 1)
            self._actions.append(("merge-internal-right", child.keys))

    # ---- STRUCTURE / PRETTY PRINT --------------------------------------

    def levels(self):
        """List of levels, root first; last level is the leaves."""
        levels = []
        cur = [self.root]
        while True:
            levels.append(cur)
            if cur[0].leaf:
                break
            nxt = []
            for n in cur:
                nxt.extend(n.children)
            cur = nxt
        return levels

    def leaf_chain(self):
        chain = []
        n = self.levels()[-1][0]
        while n is not None:
            chain.append(n)
            n = n.next
        return chain

    def describe(self):
        levels = self.levels()
        n_keys = sum(len(n.keys) for n in levels[-1])
        return {
            "height": len(levels),
            "n_internal_levels": len(levels) - 1,
            "n_leaves": len(levels[-1]),
            "n_keys": n_keys,
        }

    def compact(self):
        """One-line-per-level snapshot for the step-by-step traces."""
        out = []
        for d, lev in enumerate(self.levels()):
            kind = "LEAF" if lev[0].leaf else "INT "
            cells = "   ".join("[" + ",".join(str(k) for k in n.keys) + "]"
                               for n in lev)
            out.append(f"  L{d} {kind}: {cells}")
        chain = " -> ".join("[" + ",".join(str(k) for k in n.keys) + "]"
                            for n in self.leaf_chain())
        out.append(f"  CHAIN: {chain}")
        return "\n".join(out)


# ============================================================================
# 2. PRETTY PRINTERS + HELPERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def binary_search(ks, vs, key):
    """Plain sorted-list binary search -- the gold reference for find()."""
    lo, hi = 0, len(ks) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if ks[mid] == key:
            return vs[mid]
        if ks[mid] < key:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

INSERTS_A = [10, 20, 5, 6, 12, 30, 7, 17, 25, 31, 1, 3, 8, 22, 9, 28, 15, 2]


def section_a():
    banner("SECTION A: build a B+tree of order m=4 from an insertion sequence")
    print("order m = 4  ->  max 3 keys per node, min 2 keys per non-root leaf.")
    print(f"insertion sequence ({len(INSERTS_A)} keys): {INSERTS_A}\n")
    t = BPlusTree(4)
    for k in INSERTS_A:
        t.insert(k, k)
    print("Final tree, level by level (root at top, leaves at bottom):\n")
    print(t.compact())
    d = t.describe()
    print(f"\nheight = {d['height']} levels "
          f"({d['n_internal_levels']} internal + 1 leaf)")
    print(f"leaves = {d['n_leaves']}, total keys stored = {d['n_keys']}")
    print("\nRead it as: each internal node's keys are dividers; the leaves hold")
    print("the data and are stitched into one sorted chain by the next-pointers.")
    print("A point lookup descends exactly `height` pages; a range scan lands in")
    print("one leaf then walks the chain. (Sections C and D.)")
    return t


def section_b():
    banner("SECTION B: page split, step by step (leaf split -> root grows)")
    print("Watch splits propagate. A leaf overflows at 4 keys; the median is")
    print("COPIED up. When the parent itself overflows, its median is MOVED up.")
    print("When the ROOT splits, a new root is made and the tree grows TALLER.\n")
    t = BPlusTree(4)
    t.trace = True
    seq = [10, 20, 5, 6, 12, 30, 7, 1, 8, 9]
    print(f"insert sequence: {seq}\n")
    for k in seq:
        print(f"--- insert {k} ---")
        t.insert(k, k)
        print(t.compact())
    t.trace = False
    print("\nKey moments above:")
    print("  * insert 6   : leaf [5,6,10,20] overflows -> split, COPY 10 up, NEW ROOT.")
    print("  * insert 30  : right leaf overflows -> split, COPY 20 into the root.")
    print("  * insert 1,9 : splits cascade until the root overflows -> internal split,")
    print("                  MOVE 10 up, NEW ROOT again -> tree is now 3 levels tall.")
    print("\nNote the two different 'push up' rules: leaves COPY the separator up")
    print("(every key stays in a leaf); internals MOVE it (it is only a divider).")


def section_c(t: BPlusTree):
    banner("SECTION C: point lookup -- descend root -> leaf, count comparisons")
    print("At each internal level we compare the search key against the separators")
    print("until we find the child whose range contains it; in the leaf we scan for")
    print("the key. Each comparison is counted. Path length = height = 3 pages.\n")
    for key in [12, 1, 28, 99]:
        r = t.search_trace(key)
        print(f"search({key}):")
        for depth, kind, keys, detail in r["log"]:
            print(f"  L{depth} {kind} {keys}: " + "; ".join(detail))
        if r["value"] is not None:
            status = f"FOUND, value = {r['value']}"
        else:
            status = "NOT FOUND"
        print(f"  -> {status}; comparisons = {r['comparisons']}\n")
    print("Every lookup touched exactly 3 pages (one per level) no matter the key.")
    print("Comparisons scale with keys-per-node; in a real engine each node is read")
    print("once and binary-searched internally, so it is O(log_fanout N) comparisons.")


def section_d(t: BPlusTree):
    banner("SECTION D: range scan -- find leaf, then walk the leaf chain")
    lo, hi = 6, 22
    print(f"range [{lo}, {hi}]:\n")
    results, visited = t.range_scan(lo, hi)
    print("Step 1 - descend to the leaf that would hold the low key (same as a")
    print("point lookup, just using `lo` as the probe):\n")
    print("Step 2 - scan that leaf, then FOLLOW THE NEXT-POINTERS rightward until")
    print("a key exceeds `hi`. No second tree traversal -- the '+' of B+tree:\n")
    for i, leaf in enumerate(visited):
        matched = [k for k in leaf.keys if lo <= k <= hi]
        tag = f"<-- matched {matched}" if matched else "(no match, skipped? )"
        print(f"  leaf {i}: keys={leaf.keys}  {tag if matched else ''}".rstrip())
    print(f"\nresults ({len(results)} keys): {[k for k, _ in results]}")
    print("The chain walk is SEQUENTIAL I/O on contiguous leaf pages -- cheap on")
    print("disk/SSD. This is why clustered PK range scans are so fast. 🔗 HEAP_VS_CLUSTERED.md")


def section_e():
    banner("SECTION E: delete -- borrow from a sibling, or merge on underflow")
    print("min 2 keys per non-root leaf. Delete drops a key; if the leaf now has")
    print("< 2 keys it underflows: BORROW one from a sibling that can spare it,")
    print("else MERGE with a sibling (pulling the separator down). Three demos:\n")
    t = BPlusTree(4)
    for k in [10, 20, 5, 6, 12, 30, 7]:
        t.insert(k, k)
    print("starting tree:")
    print(t.compact())
    print()
    for key in [7, 6, 30]:
        actions = t.delete(key)
        print(f"--- delete {key} ---")
        if not actions:
            print("  (leaf still >= min keys; no rebalancing needed)")
        else:
            for act, payload in actions:
                print(f"  REBALANCE: {act} -> now {payload}")
        print(t.compact())
        print()
    print("What happened:")
    print("  delete 7  : leaf [5,6,7] -> [5,6] (2 keys, still OK) -> no rebalance.")
    print("  delete 6  : leaf [5,6] -> [5] underflows; sibling [10,12] is also at")
    print("               min (2) so cannot lend -> MERGE [5]+[10,12]=[5,10,12],")
    print("               separator 10 pulled down from the root.")
    print("  delete 30 : leaf [20,30] -> [20] underflows; left sibling [5,10,12]")
    print("               has 3 keys (> min) -> BORROW 12 over, leaf -> [12,20],")
    print("               separator updated to 12.")


def section_f():
    banner("SECTION F: fanout math -- why a B+tree of 1M rows is only 3 pages tall")
    page = 4096
    key_b = 8
    val_b = 8
    ptr_b = 8
    print(f"page size = {page} B; key = {key_b} B, value = {val_b} B, child ptr = {ptr_b} B\n")
    # internal node: M keys + (M+1) pointers  (ignore tiny header for the headline)
    # bytes = M*(key+ptr) + ptr   ->  M = (page - ptr) / (key+ptr)
    M = (page - ptr_b) // (key_b + ptr_b)
    fanout = M + 1
    # leaf: key+value per entry
    leaf_cap = page // (key_b + val_b)
    print("internal node: holds M keys + (M+1) child pointers")
    print(f"  M = (page - ptr) / (key + ptr) = ({page} - {ptr_b}) / {key_b + ptr_b} = {M} keys")
    print(f"  fanout (children per internal node) = M + 1 = {fanout}")
    print(f"leaf node: {leaf_cap} (key,value) entries per page\n")
    N = 1_000_000
    leaves = math.ceil(N / leaf_cap)
    print(f"N = {N:,} rows -> leaf pages needed = ceil(N/leaf_cap) = ceil({N}/{leaf_cap}) = {leaves:,}\n")
    print("| height (levels) | role of bottom level | max rows addressable |")
    print("|----------------:|----------------------|---------------------:|")
    for h in range(1, 5):
        cap = (fanout ** (h - 1)) * leaf_cap
        role = "leaf (root is the leaf)" if h == 1 else "leaves (under %d internal level%s)" % (
            h - 1, "" if h - 1 == 1 else "s")
        flag = "  <-- 1M rows live here" if cap >= N and (fanout ** (h - 2)) * leaf_cap < N else ""
        print(f"| {h} | {role:<28} | {cap:>16,} |{flag}")
    # height needed
    h_needed = 1 + math.ceil(math.log(leaves, fanout)) if leaves > 1 else 1
    print(f"\nheight for N = {N:,}: 1 + ceil(log_{fanout}({leaves:,})) = {h_needed} levels")
    print(f"-> a point lookup reads exactly {h_needed} pages. Range scan adds the")
    print("   sequential leaf walk. THAT is the B+tree payoff: O(log_fanout N) I/O,")
    print(f"   and with a {fanout}-way fanout the log barely grows.")
    print(f"\n[check] 1M rows fits in 3 levels: fanout^(3-1)*leaf_cap = "
          f"{fanout}^2*{leaf_cap} = {fanout ** 2 * leaf_cap:,} >= {N:,}: OK")
    assert fanout ** (h_needed - 1) * leaf_cap >= N
    assert fanout ** (h_needed - 2) * leaf_cap < N
    print("[check] 2 levels would cap at "
          f"{fanout ** 1 * leaf_cap:,} < {N:,} -> need 3: OK")


def gold_check(t: BPlusTree):
    banner("GOLD CHECK: btree.search(k) == sorted-list binary search")
    flat = sorted(INSERTS_A)
    ks = flat
    vs = flat
    # every present key
    for k in flat:
        got = t.find(k)
        exp = binary_search(ks, vs, k)
        assert got == exp, f"key {k}: tree={got} binsearch={exp}"
    # a sweep of missing keys (negatives, gaps, huge)
    missing = [-5, 0, 4, 13, 16, 19, 23, 27, 29, 50, 1000]
    for k in missing:
        got = t.find(k)
        exp = binary_search(ks, vs, k)
        assert got == exp, f"missing key {k}: tree={got} binsearch={exp}"
    print(f"checked {len(flat)} present + {len(missing)} absent keys.")
    print("for every k:  BPlusTree.find(k)  ==  binary_search(sorted_inserts, k)")
    print("[check] btree.search matches flat sorted-list binary search:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("btree.py - reference impl. All numbers below feed BTREE.md.")
    print("stdlib only. Run: python3 btree.py")
    t = section_a()
    section_b()
    section_c(t)
    section_d(t)
    section_e()
    section_f()
    gold_check(t)
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
