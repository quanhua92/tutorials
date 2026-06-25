"""
gin_gist.py - Reference implementation of PostgreSQL's two "generalized"
access methods: GIN (Generalized Inverted Index) and GiST (Generalized
Search Tree).

B-trees and hash indexes assume one key per row and a single ordering or
equality predicate. A lot of real data does NOT look like that:

  * a document contains MANY words      -> "which rows contain the word X?"
  * an array contains MANY elements     -> "which rows contain element X?"
  * a jsonb has MANY keys/paths         -> "which rows match this path?"
  * a geometry OVERLAPS another         -> "which rows intersect this box?"
  * a trigram is CLOSE to a string      -> "which rows are similar to X?"

GIN and GiST are the two PostgreSQL answers, and they are OPPOSITE strategies:

  * GIN : build an INVERTED INDEX -- map each ELEMENT to the list of row TIDs
          that contain it. Lookup is "look up the element, read its TID list."
          This is exactly how a search engine works. Fast lookup, slow insert
          (every new element must be threaded into the per-key posting tree).
          Used for tsvector (full-text), array, jsonb.

  * GiST: a balanced SEARCH TREE where every node stores a UNION KEY -- a
          summary of all its descendants (e.g. the bounding box of all
          geometries below). A query descends the tree and PRUNES any branch
          whose union key cannot possibly match. Used for geometric/spatial,
          range types, trigram similarity (pg_trgm).

This is the single source of truth that GIN_GIST.md is built from. Every
number, table, and worked example in the guide is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    python3 gin_gist.py

============================================================================
THE INTUITION (read this first) -- the library card catalogue vs the map
============================================================================
Suppose you want to find "every book that mentions DATABASES."

  * GIN is the CARD CATALOGUE. For every word, there is a card listing every
    book (by shelf number) that contains it. To find books with BOTH
    "database" AND "index", you pull the two cards and find the shelf numbers
    that appear on BOTH -- a set INTERSECTION. Adding a new book means filing
    a card for every word in it (slow insert); but once filed, lookups are
    instant. This is why PG's full-text and jsonb indexes are GIN.

  * GiST is the MAP with FOLD-OUT REGIONS. Each page of the atlas draws a
    BOUNDING BOX around everything on the pages beneath it. To find "what is
    at point (5,5)", you start at the front cover: if its bounding box does
    not contain (5,5), the answer is empty; otherwise you open the next layer
    and repeat. Whole subtrees are SKIPPED when their box misses the point.
    This is why PG's geometric and range indexes are GiST.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  TID            : tuple id -- the row's physical location (block, offset).
                   GIN stores TIDs in its posting lists; GiST stores a TID in
                   each leaf entry. We use a plain integer doc_id/rect_id as
                   the TID stand-in.
  element        : a searchable piece of a value. A word in a document, an
                   item in an array, a key/path in jsonb.
  posting list   : the sorted list of TIDs that share one element. GIN's
                   atomic unit. Stored inside a per-key "posting tree" (a
                   tiny B-tree of TIDs) when long, or inline when short.
  inverted index : element -> posting list. The whole GIN structure.
  AND query      : "rows containing ALL of {w1, w2, ...}" = INTERSECTION of
                   the per-element posting lists.
  OR query       : "rows containing ANY of {w1, w2, ...}" = UNION.
  pending list   : GIN's unsorted insert buffer. New entries append here
                   (O(1)) instead of threading into the posting trees (slow).
                   When it fills, it is sorted and batch-merged in one pass.
                   Toggle: CREATE INDEX ... WITH (fastupdate = on/off).
  union key      : GiST's per-node summary. For spatial data it is the
                   bounding box (min/max of children). For ranges, the union
                   range. For trigrams, the trigram set. A parent's union key
                   ALWAYS encloses every child's union key (nesting).
  bounding box   : the smallest axis-aligned rectangle covering a set of
                   geometries. Abbreviated BB.
  predicate      : the op-class question asked of a union key during descent,
                   e.g. "does this box contain point P?" or "does this range
                   overlap query range Q?" If false, the subtree is PRUNED.
  op-class       : the plug-in that teaches GIN/GiST about a data type
                   (tsvector_ops, array_ops, gist_geometry_ops, ...). GIN and
                   GiST are FRAMEWORKS; the op-class supplies element extraction
                   (GIN) or union/predicate/consistent (GiST).

============================================================================
THE LINEAGE (papers)
============================================================================
  Inverted files         (books, centuries old; Zobel & Moffat 2006 survey):
                           the classic full-text structure: term -> doc list.
  GIN                    (PostgreSQL, Bartunov & Sigaev, ~2007):  a generalized
                           inverted index -- same idea, generalized to any type
                           whose op-class can extract elements.
  R-tree                 (Guttman 1984, SIGMOD):  the original balanced spatial
                           tree with bounding-box union keys.
  GiST                   (Hellerstein, Naughton, Padiou 1995, SIGMOD):  a
                           generalization of the R-tree framework to ANY
                           data type whose op-class supplies union + consistent.
  pg_trgm / GIN trigrams : trigram similarity can be indexed EITHER way --
                           a nice illustration that GIN and GiST overlap.

KEY FORMULAS / INVARIANTS (all verified in code below):

  GIN
    inverted[w]            = sorted({ tid : w in elements(row[tid]) })
    AND(w1..wn)            = inverted[w1] ∩ inverted[w2] ∩ ... ∩ inverted[wn]
    OR(w1..wn)             = inverted[w1] ∪ ... ∪ inverted[wn]
    fast-update insert     = O(1) append to pending list
    flush cost             = O(sort(B) + D * log N)  where B = pending size,
                             D = #distinct elements in batch, N = posting-tree
                             size. D, not B, drives the descent count.
    lookup (fastupdate on) = scan main posting tree + linear pending scan

  GiST
    node.bb                = union of all children's keys   (nesting invariant)
    consistent(node.bb, q) = predicate; if false, PRUNE the whole subtree
    contains_point(bb, p)  = bb.x0 <= p.x <= bb.x1 and bb.y0 <= p.y <= bb.y1
    lookup(node, q)        = if not consistent(bb, q): return []
                             else: recurse into children that are consistent
    depth                  = O(log_F N)  (balanced, like a B-tree)

Sources:
  [1] PostgreSQL source, src/backend/access/gin/ and src/backend/access/gist/.
  [2] PostgreSQL docs: storage-gin.html, storage-gist.html, indexes-types.html,
      textsearch.html, functions-admin.html (gin_pending_list_limit).
  [3] J. M. Hellerstein, J. F. Naughton, P. Padiou, "Generalized Search Trees
      for Secondary Storage", VLDB 1995 -- wait, SIGMOD 1995. The GiST paper.
  [4] A. Guttman, "R-trees: A Dynamic Index Structure for Spatial Searching",
      SIGMOD 1984 -- the spatial op-class archetype.
  [5] J. Zobel, A. Moffat, "Inverted files for text search engines", ACM
      Computing Surveys 38(2), 2006 -- the inverted-index survey.
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# 0. CONSTANTS
# ----------------------------------------------------------------------------
BANNER = "=" * 72

# GIN: how big the pending list grows before it is flushed into the main
# (per-key posting-tree) index. PG default behaviour is governed by
# gin_pending_list_limit (4 MB default) per index, or per tablespace.
GIN_PENDING_THRESHOLD = 4


# ============================================================================
# 1. GIN -- the inverted index
# ============================================================================

def tokenize(text: str) -> list[str]:
    """Split text into searchable elements (words).

    PG full-text search first tokenizes, then REDUCES each token to a lexeme
    via a dictionary (e.g. snowball English: "indexes" -> "index"). We skip
    the lexeme step so the map is literal -- this keeps the worked example
    transparent. The structure is identical; only the dictionary is missing.
    """
    out: list[str] = []
    cur = []
    for ch in text.lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def build_inverted_index(docs: list[str]) -> dict[str, list[int]]:
    """Build element -> sorted list of doc TIDs (the GIN structure).

    Mirrors PG's approach: for each row, the op-class extracts its elements;
    each element is inserted into that element's posting list. The posting
    list is sorted and de-duplicated (a real GIN keeps it in a per-key posting
    TREE; we keep a sorted Python list -- same abstract behaviour).
    """
    inverted: dict[str, list[int]] = {}
    for tid, doc in enumerate(docs):
        seen: set[str] = set()
        for w in tokenize(doc):
            if w in seen:                 # one TID per element per row
                continue
            seen.add(w)
            inverted.setdefault(w, []).append(tid)
    for w in inverted:
        inverted[w].sort()
    return inverted


def gin_and(inverted: dict[str, list[int]], words: list[str]) -> list[int]:
    """AND query: rows containing ALL words = INTERSECTION of posting lists.

    This is the key GIN operation. Each word's posting list is fetched, then
    the lists are intersected. Because every posting list is sorted, the
    intersection is a linear merge -- O(sum of list lengths).
    """
    if not words:
        return []
    # start from the smallest list (cheapest intersection)
    lists = [inverted.get(w, []) for w in words]
    if any(len(lst) == 0 for lst in lists):
        return []
    lists.sort(key=len)
    result = set(lists[0])
    for lst in lists[1:]:
        result &= set(lst)
        if not result:
            return []
    return sorted(result)


def brute_force_and(docs: list[str], words: list[str]) -> list[int]:
    """Brute-force AND query: scan every document, check each word.

    This is the BASELINE that GIN exists to avoid. Cost = O(total words in
    corpus). Used as the GOLD reference for correctness.
    """
    out = []
    for tid, doc in enumerate(docs):
        tokens = set(tokenize(doc))
        if all(w in tokens for w in words):
            out.append(tid)
    return out


class GinIndex:
    """A GIN with fast update (pending list + batch flush).

    Layout:
      posting   : element -> sorted list of TIDs  (the "main" posting trees)
      pending   : unsorted [(element, tid), ...]  (the fast-update buffer)
      threshold : pending capacity; on overflow, sort + batch-merge into main

    Mirrors PG's ginInsertFASTUPDATE path: inserts append to a pending list,
    and a work-item (autovacuum or the next insert) merges the list in one
    sorted pass. We model the descent cost: every distinct element in a flush
    batch costs ONE posting-tree descent (to find/extend that element's tree).
    Inserting the same element 1000 times costs 1 descent per flush, not 1000.
    """

    def __init__(self, pending_threshold: int = GIN_PENDING_THRESHOLD):
        self.posting: dict[str, list[int]] = {}
        self.pending: list[tuple[str, int]] = []
        self.threshold = pending_threshold
        self.flushes = 0
        self.main_descents = 0          # #posting-tree descents (per distinct key)
        self.last_flush = None          # (batch_size, distinct_keys) for tracing

    def insert(self, element: str, tid: int) -> str:
        """Append to the pending list; flush when it reaches the threshold."""
        self.pending.append((element, tid))
        if len(self.pending) >= self.threshold:
            size, distinct = self._flush()
            return f"inserted+flush(batch={size},distinct={distinct})"
        return f"inserted(pending={len(self.pending)})"

    def _flush(self) -> tuple[int, int]:
        # sort by element so all entries for one element are contiguous, then
        # merge them into that element's posting list. ONE descent per distinct
        # element -- the whole point of batching.
        batch = sorted(self.pending)
        self.pending = []
        distinct: set[str] = {el for el, _ in batch}
        self.main_descents += len(distinct)
        for el, tid in batch:
            lst = self.posting.setdefault(el, [])
            if tid not in lst:
                lst.append(tid)
                lst.sort()
        self.flushes += 1
        size = len(batch)
        self.last_flush = (size, len(distinct))
        return size, len(distinct)

    def flush(self):
        """Public wrapper -- force a final flush (mirrors VACUUM merging)."""
        if self.pending:
            return self._flush()
        return None

    def query(self, element: str) -> list[int]:
        """Lookup must read BOTH the main posting list AND the pending list.

        This is the price of fast update: un-flushed entries live only in the
        (unsorted, linear) pending list, so a query scans it linearly too.
        """
        result = list(self.posting.get(element, []))
        for el, tid in self.pending:
            if el == element and tid not in result:
                result.append(tid)
        result.sort()
        return result


# ============================================================================
# 2. GiST -- the generalized search tree (spatial / bounding-box op-class)
# ============================================================================

class Rect:
    """An axis-aligned rectangle with inclusive bounds [x0,x1] x [y0,y1]."""

    __slots__ = ("x0", "y0", "x1", "y1")

    def __init__(self, x0: float, y0: float, x1: float, y1: float):
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1

    def contains_point(self, x: float, y: float) -> bool:
        return self.x0 <= x <= self.x1 and self.y0 <= y <= self.y1

    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def enlarge(self, other: "Rect") -> float:
        """Area added if `self` must grow to swallow `other`."""
        return Rect.union(self, other).area() - self.area()

    @staticmethod
    def union(a: "Rect", b: "Rect") -> "Rect":
        return Rect(min(a.x0, b.x0), min(a.y0, b.y0),
                    max(a.x1, b.x1), max(a.y1, b.y1))

    @staticmethod
    def union_all(rects: list["Rect"]) -> "Rect":
        it = iter(rects)
        acc = next(it)
        for r in it:
            acc = Rect.union(acc, r)
        return acc

    def __repr__(self) -> str:
        return f"Rect({g(self.x0)},{g(self.y0)})-({g(self.x1)},{g(self.y1)})"


def g(v: float) -> str:
    """Compact int-or-float formatter."""
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return s


class GistNode:
    """A GiST node. Children are (union_key, payload) pairs.

    Internal node: payload is a child GistNode. Leaf node: payload is the row
    label (the leaf entry's TID stand-in). A node's `bb` is the UNION of its
    children's keys -- the nesting invariant that makes pruning work.
    """

    def __init__(self, children, is_leaf: bool, name: str):
        self.children = children          # [(Rect_key, payload), ...]
        self.is_leaf = is_leaf
        self.name = name
        self.bb = Rect.union_all([k for k, _ in children])


def gist_point_query(root: GistNode, x: float, y: float):
    """Traverse the tree; PRUNE any subtree whose bb does not contain (x,y).

    Returns (hits, trace):
      hits  : [(label, Rect), ...] leaf entries containing the point
      trace : [(node_name, is_leaf, bb_str, contains, decision), ...]
              decision in {"descend", "PRUNE", "HIT", "miss"}
    """
    hits: list[tuple[str, Rect]] = []
    trace: list[tuple[str, bool, str, bool, str]] = []

    def rec(node: GistNode):
        c = node.bb.contains_point(x, y)
        trace.append((node.name, node.is_leaf, repr(node.bb), c,
                      "descend" if c else "PRUNE"))
        if not c:
            return
        if node.is_leaf:
            for key, label in node.children:
                hit = key.contains_point(x, y)
                trace.append((f"  {label}", True, repr(key), hit,
                              "HIT" if hit else "miss"))
                if hit:
                    hits.append((label, key))
        else:
            for _key, child in node.children:
                rec(child)

    rec(root)
    return hits, trace


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def dump_inverted(inverted: dict[str, list[int]]) -> str:
    """Pretty-print the inverted index, sorted by word."""
    lines = []
    for w in sorted(inverted):
        tids = inverted[w]
        lines.append(f"  {w:<12} -> TIDs {tids}")
    return "\n".join(lines)


def dump_tree(node: GistNode, depth: int = 0) -> str:
    """Pretty-print the GiST tree, indenting children. Shows bb nesting."""
    pad = "  " * depth
    role = "LEAF" if node.is_leaf else "NODE"
    lines = [f"{pad}{role} {node.name}  bb={node.bb}  "
             f"(union of {len(node.children)} children)"]
    for key, payload in node.children:
        if node.is_leaf:
            lines.append(f"{pad}  entry {payload:<3} key={key}")
        else:
            lines.append(f"{pad}  -- child key={key} ->")
            lines.append(dump_tree(payload, depth + 2))
    return "\n".join(lines)


# ============================================================================
# 4. THE DETERMINISTIC INPUTS  (pinned so .py == .html byte-for-byte)
# ============================================================================

# --- GIN corpus: 5 documents. Chosen so "database" and "index" co-occur in
#     exactly one document (doc 3), and "index"/"indexes" stay distinct
#     tokens (no stemming) to expose the lexeme step cleanly.
DOCS = [
    "the database stores data in pages",          # doc 0
    "a btree index sorts keys for range queries", # doc 1
    "full text search uses an inverted index",    # doc 2
    "the database index speeds up point lookups", # doc 3  <- the AND hit
    "gin indexes arrays and jsonb documents",     # doc 4
]

# The fast-update insert stream: 6 (element, tid) pairs with REPEATED elements
# (database x3, index x2, gin x1) so the batch-flush collapses many inserts
# into few posting-tree descents.
GIN_INSERTS = [
    ("database", 0),
    ("index", 1),
    ("database", 2),
    ("gin", 3),
    ("index", 4),
    ("database", 5),
]

# --- GiST corpus: 7 rectangles, clustered into 4 leaves / 2 internal nodes /
#     root, so the nesting + pruning is visible on a 3-level tree.
RECTS: dict[str, Rect] = {
    "R0": Rect(1, 1, 3, 3),
    "R1": Rect(2, 2, 5, 5),
    "R2": Rect(8, 1, 11, 4),
    "R3": Rect(9, 3, 12, 6),
    "R4": Rect(2, 9, 4, 12),
    "R5": Rect(5, 10, 7, 13),
    "R6": Rect(10, 9, 13, 12),
}


def build_gist_tree() -> GistNode:
    """Construct the worked GiST tree (fanout 2, 3 levels).

    Real GiST insertion uses op-class pick/split heuristics (R-tree: least
    enlargement; R*-tree: overlap minimization). We bulk-load a clean
    clustered tree so the STRUCTURE (union keys) and the QUERY (pruning) --
    which are the GiST essence -- are the focus. The node layout:

        root (X, Y)
          X  -> Leaf A [R0, R1],  Leaf C [R4, R5]   (left half)
          Y  -> Leaf B [R2, R3],  Leaf D [R6]       (right half)
    """
    leaf_a = GistNode([(RECTS["R0"], "R0"), (RECTS["R1"], "R1")],
                      is_leaf=True, name="Leaf A")
    leaf_b = GistNode([(RECTS["R2"], "R2"), (RECTS["R3"], "R3")],
                      is_leaf=True, name="Leaf B")
    leaf_c = GistNode([(RECTS["R4"], "R4"), (RECTS["R5"], "R5")],
                      is_leaf=True, name="Leaf C")
    leaf_d = GistNode([(RECTS["R6"], "R6")],
                      is_leaf=True, name="Leaf D")
    node_x = GistNode([(leaf_a.bb, leaf_a), (leaf_c.bb, leaf_c)],
                      is_leaf=False, name="Node X")
    node_y = GistNode([(leaf_b.bb, leaf_b), (leaf_d.bb, leaf_d)],
                      is_leaf=False, name="Node Y")
    root = GistNode([(node_x.bb, node_x), (node_y.bb, node_y)],
                    is_leaf=False, name="Root")
    return root


# ----------------------------------------------------------------------------
# SECTION A: GIN inverted index -- element -> posting list
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: GIN -- build the inverted index (element -> TIDs)")
    print("For each document, the op-class extracts its elements (words). Each")
    print("element is filed under its posting list -- the sorted TIDs of every")
    print("row containing it. This IS the GIN structure.\n")
    print("Corpus (5 documents, TIDs 0..4):")
    for i, d in enumerate(DOCS):
        print(f"  doc {i}: \"{d}\"")
    print()
    inverted = build_inverted_index(DOCS)
    print(f"Inverted index ({len(inverted)} distinct elements):")
    print(dump_inverted(inverted))
    print()
    print("Read it: 'database' -> [0, 3] means docs 0 and 3 contain 'database'.")
    print("'index' -> [1, 2, 3] (docs 1, 2, 3). Note 'indexes' (doc 4) is a")
    print("DIFFERENT token -- PG would reduce both to the lexeme 'index' via its")
    print("dictionary; our literal tokenizer keeps them apart (see pitfall §).")

    # GOLD CHECK 1: every posting list is sorted + de-duplicated
    ok = all(lst == sorted(set(lst)) for lst in inverted.values())
    assert ok
    print()
    print("[check] every posting list sorted + de-duplicated:  OK")
    return inverted


# ----------------------------------------------------------------------------
# SECTION B: GIN AND query -- intersect posting lists
# ----------------------------------------------------------------------------

def section_b(inverted: dict[str, list[int]]):
    banner("SECTION B: GIN AND query  --  intersect the posting lists")
    words = ["database", "index"]
    print(f"Query: find docs containing ALL of {words}\n")
    print("Step 1 -- fetch each word's posting list:")
    for w in words:
        print(f"  '{w}' -> TIDs {inverted.get(w, [])}")
    print()
    result = gin_and(inverted, words)
    print("Step 2 -- INTERSECT the lists (sorted-list merge, linear in their size):")
    print(f"  {inverted[words[0]]}  (intersection)  {inverted[words[1]]}")
    print(f"  = {result}")
    print()
    print(f"RESULT: docs {result} contain BOTH 'database' AND 'index'.")
    print("For an OR query we would UNION instead; the per-element lookup is the")
    print("same -- only the set combiner changes.\n")

    # show a second AND that yields the empty set
    words2 = ["database", "jsonb"]
    r2 = gin_and(inverted, words2)
    print(f"Second query: {words2}")
    print(f"  'database' -> {inverted['database']} ; 'jsonb' -> {inverted['jsonb']}")
    print(f"  intersection = {r2}   (no doc has both -> empty)\n")

    # GOLD CHECK 2: AND query matches the brute-force baseline
    brute = brute_force_and(DOCS, words)
    assert result == brute, f"GIN AND {result} != brute {brute}"
    print(f"[check] GIN AND {result} == brute-force scan {brute}:  OK")


# ----------------------------------------------------------------------------
# SECTION C: GIN fast update -- pending list amortizes inserts
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: GIN fast update  --  pending list + batch flush")
    print("Inserting into a posting tree is expensive (find the element's tree,")
    print("insert the TID, rebalance). FAST UPDATE buffers inserts in an unsorted")
    print("PENDING LIST (O(1) append each), then flushes the whole batch in one")
    print(f"sorted pass when it reaches {GIN_PENDING_THRESHOLD} entries. The win:")
    print("one flush costs ONE posting-tree descent per DISTINCT element in the")
    print("batch -- not one per entry.\n")
    print("Insert stream (element, tid) -- note the repetition:")
    print("  " + ", ".join(f"({e},{t})" for e, t in GIN_INSERTS))
    print()

    idx = GinIndex(pending_threshold=GIN_PENDING_THRESHOLD)
    print("| step | (element, tid) | action                         | "
          "pending after | main posting (after flush)        |")
    print("|------|----------------|--------------------------------|"
          "---------------|-----------------------------------|")
    for step, (el, tid) in enumerate(GIN_INSERTS, 1):
        action = idx.insert(el, tid)
        pending_str = ", ".join(f"({e},{t})" for e, t in idx.pending) or "(empty)"
        main_str = ", ".join(f"{k}:{v}" for k, v in sorted(idx.posting.items())) \
            or "(empty)"
        print(f"| {step:<4} | ({el:<8},{tid}) | "
              f"{action:<30} | {pending_str:<13} | {main_str:<33} |")
    print()
    print("Watch step 4: the pending list hits 4 entries -> FLUSH. The batch")
    print("sorted = [(database,0),(database,2),(gin,3),(index,1)] -- 3 distinct")
    print("elements {database, gin, index} -> 3 posting-tree descents. A naive")
    print("(fastupdate=off) insert would have done 1 descent PER entry = 4.\n")

    # cost comparison
    n = len(GIN_INSERTS)
    naive_descents = n
    fast_descents = idx.main_descents
    print(f"After {n} inserts ({idx.flushes} flush, "
          f"{len(idx.pending)} still pending):")
    print(f"  fastupdate=OFF : {naive_descents} posting-tree descents "
          f"(1 per insert)")
    print(f"  fastupdate=ON  : {fast_descents} descents "
          f"(1 per distinct element per flush)")
    print(f"  ratio          : {fast_descents / naive_descents:.2f}x  "
          f"(the win grows with element repetition + batch size)\n")

    # the lookup price: pending must be scanned linearly
    print("The price: a lookup must scan BOTH the main posting list AND the")
    print("pending list, because un-flushed entries live only there:")
    for el in ("database", "index", "gin"):
        main = idx.posting.get(el, [])
        pend = [t for e, t in idx.pending if e == el]
        print(f"  query('{el}'): main={main} + pending={pend} "
              f"-> {idx.query(el)}")
    print()

    # force final flush + show the amortization scaling edge case
    print("Force a final flush (mirrors VACUUM emptying the pending list):")
    final = idx.flush()
    if final:
        size, distinct = final
        print(f"  flushed {size} entries, {distinct} distinct -> "
              f"{distinct} more descents. Total descents now {idx.main_descents}.")
    print()
    print("Scaling: if all 6 inserts had been the SAME element, a flush would")
    print("still cost 1 descent (1 distinct element). fastupdate turns N inserts")
    print("of one element into ~1 descent per flush -- the extreme case where")
    print("fast update shines. PG's gin_pending_list_limit caps the list so")
    print("lookups never pay too much linear pending scan.\n")

    # GOLD CHECK 3: fast-update query matches a directly-built index
    direct = build_inverted_index_from_inserts(GIN_INSERTS)
    for el in ("database", "index", "gin"):
        assert idx.query(el) == direct[el], f"{el}: {idx.query(el)} != {direct[el]}"
    print("[check] fast-update query(posting+pending) == direct index:  OK")


def build_inverted_index_from_inserts(inserts):
    """Helper: build the same inverted index straight from the insert stream."""
    inv: dict[str, list[int]] = {}
    for el, tid in inserts:
        if tid not in inv.setdefault(el, []):
            inv[el].append(tid)
    for el in inv:
        inv[el].sort()
    return inv


# ----------------------------------------------------------------------------
# SECTION D: GiST spatial tree -- union keys (bounding boxes) nest
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: GiST -- build the tree; union keys (BBs) nest")
    print("Insert 7 rectangles. The op-class groups them into leaves (fanout 2),")
    print("and every internal node stores the BOUNDING BOX of its children --")
    print("the UNION KEY. A parent's BB always encloses every child's BB. That")
    print("nesting is what lets a query prune whole subtrees.\n")
    print("Rectangles (axis-aligned, inclusive bounds):")
    for label, r in RECTS.items():
        print(f"  {label}: {r}   area={g(r.area())}")
    print()

    root = build_gist_tree()
    print("Tree (each node's bb == union of its children's keys):")
    print()
    print(dump_tree(root))
    print()
    print("Nesting check (parent.bb MUST enclose each child.bb):")
    _check_nesting(root)
    print()
    print("Observe: Root bb (1,1)-(13,13) covers everything. Node X bb")
    print("(1,1)-(7,13) covers leaves A+C (the left half). Node Y bb")
    print("(8,1)-(13,12) covers leaves B+D (the right half). A query for a")
    print("point in the LEFT half never touches Y's subtree at all.\n")

    # GOLD CHECK 4: nesting invariant holds everywhere
    ok = _check_nesting(root, quiet=True)
    assert ok
    print("[check] every parent.bb encloses every child.bb (nesting):  OK")
    return root


def _check_nesting(node: GistNode, quiet: bool = False) -> bool:
    """Verify and (unless quiet) print the nesting invariant."""
    ok = True
    if not quiet:
        print(f"  {node.name}: bb={node.bb}")
    if node.is_leaf:
        for key, label in node.children:
            enc = _encloses(node.bb, key)
            ok = ok and enc
            if not quiet:
                print(f"      entry {label} key={key}  enclosed: {enc}")
    else:
        for key, child in node.children:
            enc = _encloses(node.bb, key)
            ok = ok and enc
            if not quiet:
                print(f"      child {child.name} bb={child.bb}  "
                      f"(key={key})  enclosed: {enc}")
            ok = _check_nesting(child, quiet=quiet) and ok
    return ok


def _encloses(outer: Rect, inner: Rect) -> bool:
    return (outer.x0 <= inner.x0 and outer.y0 <= inner.y0
            and outer.x1 >= inner.x1 and outer.y1 >= inner.y1)


# ----------------------------------------------------------------------------
# SECTION E: GiST query -- descend + prune by the union key
# ----------------------------------------------------------------------------

def section_e(root: GistNode):
    banner("SECTION E: GiST point query  --  descend, PRUNE by bounding box")
    print("Query: 'which rectangles contain point P?'\n")
    print("At each node, test the union key: does this node's BB contain P?")
    print("  YES -> descend into the children.")
    print("  NO  -> PRUNE the whole subtree (skip every entry beneath it).\n")

    queries = [(4, 4), (11, 11)]
    for (x, y) in queries:
        hits, trace = gist_point_query(root, x, y)
        print(f"--- query point ({x}, {y}) ---")
        print(f"{'node':<14} {'kind':<8} {'key/bb':<26} {'contains?':<10} "
              f"{'decision':<10}")
        print("-" * 74)
        for name, is_leaf, bbstr, c, dec in trace:
            kind = "leaf" if is_leaf else "node"
            ch = "yes" if c else "no"
            print(f"{name:<14} {kind:<8} {bbstr:<26} {ch:<10} {dec:<10}")
        hit_labels = [h[0] for h in hits]
        visited = sum(1 for t in trace if not t[0].startswith("  ") and t[4] != "PRUNE")
        pruned = sum(1 for t in trace if not t[0].startswith("  ") and t[4] == "PRUNE")
        print(f"\nRESULT: {hit_labels}.  Visited {visited} tree node(s) (of 7); "
              f"PRUNED {pruned}.\n")

    # verify against brute force
    print("Brute-force check (scan all 7 rectangles, no tree):")
    for (x, y) in queries:
        brute = [lbl for lbl, r in RECTS.items() if r.contains_point(x, y)]
        hits, _ = gist_point_query(root, x, y)
        tree = [h[0] for h in hits]
        assert tree == brute, f"({x},{y}): tree {tree} != brute {brute}"
        print(f"  point ({x},{y}): tree={tree}  brute={brute}  -> match")
    print()
    print("[check] GiST point query == brute-force rectangle scan:  OK")
    print()
    print("WHY THIS IS FAST: a B-tree cannot index 'contains point' at all (no")
    print("total ordering on 2D). A sequential scan is O(N). GiST visits only")
    print("the nodes whose BB contains the point -- O(log_F N + matches) when")
    print("the data is well-clustered. The pruning is what turns O(N) into")
    print("O(log N).")


# ----------------------------------------------------------------------------
# SECTION F: GIN vs GiST -- when to use which
# ----------------------------------------------------------------------------

def section_f():
    banner("SECTION F: GIN vs GiST  --  pick by query shape")
    rows = [
        ("Core idea",
         "inverted index: element -> TID list",
         "search tree: node stores union key of children"),
        ("Best for",
         "membership: 'row contains element X'",
         "overlap/containment/distance: 'row overlaps X'"),
        ("Typical types",
         "tsvector (FTS), array, jsonb",
         "geometry, range types, pg_trgm"),
        ("AND of many terms",
         "INTERSECT posting lists (cheap)",
         "n/a (each predicate is a separate descent)"),
        ("Nearest-neighbour / distance",
         "no",
         "yes (KNN via priority queue over union keys)"),
        ("Lookup cost",
         "O(log N) per element + TID-list merge",
         "O(log_F N) descent + prune"),
        ("Insert cost",
         "slow per-key (fastupdate amortizes)",
         "moderate (find leaf, update union keys to root)"),
        ("Fast-update / buffer",
         "yes (pending list)",
         "no direct equivalent"),
        ("Index size",
         "large (one entry per element)",
         "moderate (one entry per row + union keys)"),
    ]
    print("| Aspect               | GIN                              | "
          "GiST                                       |")
    print("|----------------------|----------------------------------|"
          "--------------------------------------------|")
    for aspect, gin, gist in rows:
        print(f"| {aspect:<20} | {gin:<32} | {gist:<42} |")
    print()
    print("RULE OF THUMB:")
    print("  - GIN : the value is a SET/MULTISET and you ask 'does it contain X?'")
    print("          (words in a doc, items in an array, keys in jsonb). Build the")
    print("          inverted map; intersect posting lists for AND queries.")
    print("  - GiST: the value has GEOMETRY / OVERLAP / DISTANCE and you ask")
    print("          'does it relate to X?' (rect contains point, range overlaps")
    print("          range, trigram similar to string). Build the union-key tree;")
    print("          prune subtrees whose key cannot match.")
    print()
    print("OVERLAP: trigram similarity (pg_trgm) can be indexed EITHER way --")
    print("gin_trgm_ops (one posting list per trigram) or gist_trgm_ops (union")
    print("of trigrams). GIN is usually faster for exact trigram membership;")
    print("GiST supports the KNN (<->) operator for 'most similar' ordering.")
    print()
    print("Neither GIN nor GiST does what a B-tree does (sorted range scans,")
    print("ORDER BY). For equality only, a hash index is simpler (see")
    print("HASH_INDEX.md). Each access method is a tool for a query shape.")


# ============================================================================
# 5. main
# ============================================================================

def main():
    print("gin_gist.py - reference impl. All numbers below feed GIN_GIST.md.")
    print(f"GIN_PENDING_THRESHOLD={GIN_PENDING_THRESHOLD}  "
          f"GiST corpus={len(RECTS)} rects  docs={len(DOCS)}")

    inverted = section_a()
    section_b(inverted)
    section_c()
    root = section_d()
    section_e(root)
    section_f()

    banner("GOLD - GIN AND query must match brute-force document scan")
    gold_words = ["database", "index"]
    gin_result = gin_and(inverted, gold_words)
    brute_result = brute_force_and(DOCS, gold_words)
    print(f"GIN AND{gold_words}            = {gin_result}")
    print(f"brute_force_and(docs){gold_words} = {brute_result}")
    assert gin_result == brute_result == [3]
    print("[check] GIN AND == brute-force == [3]:  OK  "
          "(this is what gin_gist.html recomputes)")

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
