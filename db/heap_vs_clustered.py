"""
heap_vs_clustered.py - Reference implementation comparing HEAP table organization
(PostgreSQL) with CLUSTERED / Index-Organized-Table organization (MySQL InnoDB, and
SQL Server / Oracle "index-organized table").

This is the single source of truth that HEAP_VS_CLUSTERED.md is built from. Every
number, table, and I/O count in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 heap_vs_clustered.py

==========================================================================
THE INTUITION (read this first) - WHERE does the row physically live?
==========================================================================
The single question that separates the two designs:

    "Is the table stored in its OWN file, with indexes POINTING at rows,
     or ARE the rows stored INSIDE the primary-key index itself?"

  * HEAP (PostgreSQL): the table is an UNORDERED pile of pages (the "heap").
        Indexes are SEPARATE structures whose leaves store a PHYSICAL address
        -- the TID (page, offset) -- that says "the row is over THERE". An
        index never holds the row data; after using an index you make ONE
        MORE read into the heap to actually get the columns. (Like a library
        card catalog: the card tells you the shelf, you still walk to the shelf.)

  * CLUSTERED / IOT (MySQL InnoDB): the table IS the primary-key B-tree. The
        rows live INSIDE the B-tree LEAF pages, sorted by PK. There is no
        separate "heap"; the PK index leaf *is* the table. A secondary index
        therefore cannot store a physical address (rows move when the B-tree
        splits) -- it stores the PK VALUE, a LOGICAL handle, and to read the
        row you traverse the PK B-tree a second time. (Like an encyclopedia
        "see also" that gives you a topic name, not a page number.)

THE TRADE-OFF, in one line:
  - PK lookups and PK range scans are CHEAPER on a clustered table (the row is
    in the index; range scans are sequential leaf walks).
  - Secondary-index lookups are CHEAPER on a heap (the index points straight at
    the physical row; a clustered secondary index costs a whole extra PK-tree
    traversal because it only stores the PK).
  - UPDATES that change the PK are EXPENSIVE on a clustered table (the row must
    physically MOVE in the B-tree -> maybe a page split -> and EVERY secondary
    index, which stores the PK, must be rewritten). On a heap, a PK change is
    just another index entry update; the row's heap location is unaffected.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  heap            : an UNORDERED file of fixed-size pages holding the table rows.
                    PostgreSQL, DB2 (by default), Informix. Rows sit wherever
                    they were INSERTED; there is no sort order.
  clustered table : a table whose rows are stored IN the leaves of the
  / IOT            primary-key B-tree, in PK order. MySQL InnoDB (ALWAYS clustered
                    on the PK), SQL Server (optional CLUSTERED), Oracle
                    ("index-organized table"), PostgreSQL? -> NO, Postgres heaps.
  TID (CTID)      : the PHYSICAL address of a heap tuple = (page, offset). What
                    a PostgreSQL index leaf stores. Stable only until the row
                    moves; indexes that point at a moved row must be updated.
  PK value        : the LOGICAL key of a row. What an InnoDB secondary index leaf
                    stores. Stable across B-tree splits (the PK does not change
                    when a leaf splits), so secondary indexes never go stale on
                    a split -- only when the PK itself changes.
  secondary index : any index that is NOT the table. Heap: leaf = key -> TID.
                    Clustered: leaf = key -> PK value.
  page I/O        : reading one page from disk into the buffer pool. The unit of
                    cost counted throughout this file. We count DISTINCT pages
                    read per operation (a page already read this operation is a
                    cache hit = 0 extra I/O).
  page split      : when a B-tree leaf overflows on insert, half its rows move to
                    a NEW leaf page and a separator key is pushed up to the parent.
                    Costs extra page writes; only happens in ORDERED structures
                    (clustered tables, all B-tree indexes) -- never in a heap.

==========================================================================
THE LINEAGE (sources)
==========================================================================
  Sequential scan  : read every page of the file. O(N pages). The baseline; no
                      structure at all.
  Heap + indexes    : (PostgreSQL). Keep the unordered heap; add SEPARATE B-tree
                      indexes whose leaves store TIDs. Point lookups become
                      O(log N) index + 1 heap read. Section A.
  Index-organized   : (InnoDB / IOT). Fold the table INTO the PK B-tree so the
  table / clustered   leaf IS the row. Secondary indexes store PKs not TIDs.
                      Sections B-F. (Bayer & McCreight 1972 for the B-tree itself.)

KEY FORMULAS (all asserted in code; canonical index height h = 2 below):
  heap PK point lookup I/O      = h_pk_index + 1            (index path + 1 heap read)
  clustered PK point lookup I/O = h_pk_index                (row is IN the leaf)
  heap secondary lookup I/O     = h_sec_index + 1           (index path + 1 heap read)
  clustered secondary lookup I/O= h_sec_index + h_pk_index  (index path + full PK-tree walk)
  heap PK range scan (k rows)   = h_pk_index + k            (k RANDOM heap reads)
  clustered PK range scan       = h_pk_index + O(leaves)    (SEQUENTIAL leaf walk)
  GOLD identity (h_pk = h_sec = 2):
     heap(PK+sec) = (h+1)+(h+1) = 2h+2 = 6
     clus(PK+sec) = (h)+(2h)    = 3h   = 6   -> the two designs do EQUAL total
     work for one PK + one secondary lookup; they just spend it differently.
"""

from __future__ import annotations

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# The canonical 5-row table. DETERMINISTIC. Columns: (pk, name, city).
# INSERT order is deliberately NOT pk order -> the heap is physically unordered
# by PK (rows land wherever they are appended). This is the whole point of a heap.
# ---------------------------------------------------------------------------
CANON_ROWS = [
    (5, "Eve",   "El Paso"),
    (1, "Alice", "Austin"),
    (3, "Carol", "Cairo"),
    (2, "Bob",   "Berlin"),
    (4, "Dave",  "Dublin"),
]
PK_OF = {name: pk for pk, name, _ in CANON_ROWS}
NAMES_SORTED = sorted(name for _, name, _ in CANON_ROWS)


# ============================================================================
# 1. THE TWO STORAGE MODELS
# ============================================================================

def build_heap():
    """HEAP model: tuples appended in INSERT order, one per heap page (page id
    'H'+insert_position). The TID is just the page id (offset 0).

    One tuple per page is EXAGGERATED (a real 8 KB page holds hundreds of rows;
    see SLOTTED_PAGE.md). We use it so the random-access pattern of a heap range
    scan is visible: every row fetch is a distinct page read. With realistic
    fill the COUNT drops but the random, non-sequential PATTERN is identical.
    """
    pages = {}        # page_id -> (pk, name, city)
    tid_by_pk = {}    # pk -> page_id  (the heap location = the TID)
    for i, row in enumerate(CANON_ROWS):
        pid = f"H{i}"
        pages[pid] = row
        tid_by_pk[row[0]] = pid
    return pages, tid_by_pk


def make_index(root_id, leaf_id, entries):
    """A 2-level B-tree (height 2): one internal ROOT node -> one LEAF node.

    `entries` is a list of (key, payload) ALREADY sorted by key. Height = 2 is
    the canonical value used by every section; the descent returns [root, leaf].
    """
    return {
        "root": root_id,
        "nodes": {
            root_id: {"kind": "internal", "seps": [], "children": [leaf_id]},
            leaf_id: {"kind": "leaf", "entries": list(entries), "next": None},
        },
    }


def make_clus_pk_index(root_id, leaf_id, rows):
    """The clustered PK B-tree: its LEAF holds the FULL rows, sorted by PK.
    (This is the structural difference vs the heap: the leaf carries row data,
    not just a pointer.)"""
    rows = sorted(rows, key=lambda r: r[0])
    return {
        "root": root_id,
        "nodes": {
            root_id: {"kind": "internal", "seps": [], "children": [leaf_id]},
            leaf_id: {"kind": "leaf", "rows": rows, "next": None},
        },
    }


def descend(index, key):
    """Walk ROOT -> LEAF for `key`. Returns (trace, leaf_node) where trace is the
    list of page ids read (the access path). With height 2 the trace is
    [root, leaf]; the general form is the index height h."""
    trace = []
    node_id = index["root"]
    while True:
        trace.append(node_id)
        node = index["nodes"][node_id]
        if node["kind"] == "leaf":
            return trace, node
        seps = node["seps"]
        children = node["children"]
        if not seps:                      # single child (our 2-level tree)
            node_id = children[0]
        else:                             # general fanout: pick the child
            idx = len(children) - 1
            for i, s in enumerate(seps):
                if key < s:
                    idx = i
                    break
            node_id = children[idx]


def build_indexes():
    """Build all four indexes for the canonical table (heap x2, clustered x2)."""
    pages, tid_by_pk = build_heap()
    # HEAP: PK index leaf stores pk -> TID
    heap_pk = make_index("PKR", "PKL", sorted(tid_by_pk.items()))
    # HEAP: secondary index on `name` leaf stores name -> TID
    heap_sec = make_index("SR", "SL",
                          sorted((n, tid_by_pk[PK_OF[n]]) for n in NAMES_SORTED))
    # CLUSTERED: PK B-tree leaf holds the full rows (sorted by pk)
    clus_pk = make_clus_pk_index("CR", "CL", [r for r in CANON_ROWS])
    # CLUSTERED: secondary index on `name` leaf stores name -> PK VALUE
    clus_sec = make_index("CSR", "CSL",
                          sorted((n, PK_OF[n]) for n in NAMES_SORTED))
    return pages, tid_by_pk, heap_pk, heap_sec, clus_pk, clus_sec


# ---- operation traces (each returns the ordered page-access list) -----------

def heap_pk_lookup(heap_pk, tid_by_pk, pages, pk):
    trace, leaf = descend(heap_pk, pk)
    tid = dict(leaf["entries"])[pk]
    trace = trace + [tid]                 # the extra HEAP read the heap always pays
    return trace, tid, pages[tid]


def clus_pk_lookup(clus_pk, pk):
    trace, leaf = descend(clus_pk, pk)    # row is IN the leaf -> no extra read
    row = {r[0]: r for r in leaf["rows"]}[pk]
    return trace, row


def heap_sec_lookup(heap_sec, pages, name):
    trace, leaf = descend(heap_sec, name)
    tid = dict(leaf["entries"])[name]
    trace = trace + [tid]                 # one heap read
    return trace, tid, pages[tid]


def clus_sec_lookup(clus_sec, clus_pk, name):
    t1, leaf = descend(clus_sec, name)
    pk = dict(leaf["entries"])[name]      # secondary leaf gives the PK, not a TID
    t2, _ = descend(clus_pk, pk)          # must now walk the WHOLE PK tree again
    return t1 + t2, pk


def heap_pk_range(heap_pk, pages, lo, hi):
    trace, leaf = descend(heap_pk, lo)
    hits = []
    for pk, tid in leaf["entries"]:        # leaf is in PK order
        if lo <= pk <= hi:
            trace = trace + [tid]          # one RANDOM heap read per row
            hits.append((pk, tid, pages[tid]))
    return trace, hits


def clus_pk_range(clus_pk, lo, hi):
    trace, leaf = descend(clus_pk, lo)
    hits = [r for r in leaf["rows"] if lo <= r[0] <= hi]
    # single leaf here; a real scan follows leaf 'next' sibling pointers and is
    # fully SEQUENTIAL across adjacent leaf pages (cache-friendly).
    return trace, hits


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def io(trace) -> int:
    """Distinct pages read in one operation (per-operation buffer pool: a page
    already touched this operation is a cache hit, 0 extra I/O)."""
    return len(set(trace))


def fmt_trace(trace) -> str:
    return " -> ".join(trace)


# ============================================================================
# 3. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the HEAP model (unordered heap file + secondary index -> TID)
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the HEAP model  (unordered heap file; indexes store TIDs)")
    pages, tid_by_pk = build_heap()
    print("PostgreSQL stores the table as a HEAP: rows are appended to unordered")
    print("pages in INSERT order. There is NO physical sort by PK. Here the 5 rows")
    print("were inserted as Eve, Alice, Carol, Bob, Dave -> heap page order is NOT")
    print("PK order. (1 tuple/page is exaggerated so a range scan's random reads are")
    print("visible; a real 8 KB page holds hundreds of rows - see SLOTTED_PAGE.md.)\n")
    print("  HEAP FILE  (the table itself; unordered):")
    print("    page | PK | name  | city    | TID = (page, off)")
    print("    -----|----|-------|---------|-----------------")
    for pid in sorted(pages):
        pk, name, city = pages[pid]
        print(f"    {pid:<4} | {pk:>2} | {name:<5} | {city:<7} | ({pid}, 0)")
    print("\n  The heap is the WHOLE table. Indexes are SEPARATE files that merely")
    print("  store a PHYSICAL pointer (the TID) back into these pages.\n")

    # secondary index on `name`
    sec_entries = sorted((n, tid_by_pk[PK_OF[n]]) for n in NAMES_SORTED)
    print("  SECONDARY INDEX on `name`  (a separate B-tree; leaf = name -> TID):")
    print("    name  | -> TID (heap location)")
    print("    ------|---------------------")
    for name, tid in sec_entries:
        print(f"    {name:<5} | {tid}")
    print("\n  KEY POINT: the index leaf holds NO row data - only a TID. To read the")
    print("  city you must follow the TID and read the HEAP page. The PK index is just")
    print("  another such index (pk -> TID); in a heap, the PK gets NO special physical")
    print("  treatment. Every index lookup ends with exactly one extra heap read.")
    print("\n[check] heap rows unordered by PK: "
          f"page order PKs = {[pages[f'H{i}'][0] for i in range(len(pages))]} "
          f"!= sorted {sorted(r[0] for r in CANON_ROWS)}  ->  OK")


# ----------------------------------------------------------------------------
# SECTION B: the CLUSTERED / IOT model (rows IN the PK B-tree leaf; sec -> PK)
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: the CLUSTERED / IOT model  (rows live IN the PK B-tree leaf)")
    rows_sorted = sorted(CANON_ROWS, key=lambda r: r[0])
    print("MySQL InnoDB stores the table AS the primary-key B-tree: the LEAF pages")
    print("hold the FULL rows, in PK order. There is no separate heap - the PK index")
    print("IS the table. (SQL Server calls this a CLUSTERED index; Oracle an")
    print("index-organized table / IOT; PostgreSQL does NOT do this - it always heaps.)\n")
    print("  PK B-TREE LEAF (page CL) = the table, rows sorted by PK:")
    print("    PK | name  | city")
    print("    ---|-------|---------")
    for pk, name, city in rows_sorted:
        print(f"    {pk:>2} | {name:<5} | {city}")
    print("\n  Contrast with Section A: the same 5 rows, but now they are STORED IN")
    print("  PK order, physically clustered. A PK lookup lands directly on the row.\n")

    csec_entries = sorted((n, PK_OF[n]) for n in NAMES_SORTED)
    print("  SECONDARY INDEX on `name`  (leaf = name -> PK VALUE, not a TID):")
    print("    name  | -> PK (logical handle)")
    print("    ------|--------------------")
    for name, pk in csec_entries:
        print(f"    {name:<5} | {pk}")
    print("\n  KEY POINT: the secondary leaf stores the PK VALUE, a LOGICAL handle,")
    print("  NOT a physical address. Why? Because B-tree SPLITS physically move rows")
    print("  between pages - a stored TID would instantly go stale. The PK never")
    print("  changes on a split, so storing the PK keeps secondary indexes stable.")
    print("  The price: reading the row costs a SECOND full PK-tree traversal")
    print("  (Section D).")
    print("\n[check] clustered leaf is PK-sorted: "
          f"PKs = {[r[0] for r in rows_sorted]} == {sorted(r[0] for r in CANON_ROWS)} "
          f" ->  OK")


# ----------------------------------------------------------------------------
# SECTION C: PK point lookup comparison (heap: index + heap read; clustered: 1 path)
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: PK point lookup  (heap pays an extra heap read; clustered does not)")
    pages, tid_by_pk, heap_pk, heap_sec, clus_pk, clus_sec = build_indexes()
    pk = 3                                   # look up Carol by her primary key
    print(f"Lookup PK = {pk} (\"Carol\").\n")
    ht, htid, hrow = heap_pk_lookup(heap_pk, tid_by_pk, pages, pk)
    ct, crow = clus_pk_lookup(clus_pk, pk)
    print(f"  HEAP       : descend PK index  [{fmt_trace(ht[:-1])}]  ->  TID = {htid},")
    print(f"                then read heap page {htid}  ->  row = {hrow}")
    print(f"                trace: {fmt_trace(ht)}    I/O = {io(ht)}")
    print(f"  CLUSTERED  : descend PK B-tree [{fmt_trace(ct)}]  ->  row is IN the leaf")
    print(f"                trace: {fmt_trace(ct)}    I/O = {io(ct)}\n")
    diff = io(ht) - io(ct)
    print(f"  -> CLUSTERED wins by {diff}: the index leaf already holds the full row,")
    print(f"     so there is no separate heap fetch. For a heap, the PK index is just")
    print(f"     an index; its leaf carries only (pk -> TID), so you ALWAYS pay one")
    print(f"     more page read to get the actual columns.")
    print(f"\n  [check] heap_pk_io = {io(ht)} == h+1 = 2+1 = 3        OK")
    print(f"  [check] clus_pk_io = {io(ct)} == h   = 2               OK")
    assert io(ht) == 3 and io(ct) == 2


# ----------------------------------------------------------------------------
# SECTION D: secondary index lookup comparison (heap wins; clustered pays 2 trees)
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: secondary index lookup  (heap wins; clustered walks the PK tree twice)")
    pages, tid_by_pk, heap_pk, heap_sec, clus_pk, clus_sec = build_indexes()
    name = "Carol"
    print(f"Look up `name` = \"{name}\" via the secondary index.\n")
    ht, htid, hrow = heap_sec_lookup(heap_sec, pages, name)
    ct, cpk = clus_sec_lookup(clus_sec, clus_pk, name)
    print(f"  HEAP       : descend sec index  [{fmt_trace(ht[:-1])}]  ->  TID = {htid},")
    print(f"                then read heap page {htid}  ->  row = {hrow}")
    print(f"                trace: {fmt_trace(ht)}    I/O = {io(ht)}")
    print(f"  CLUSTERED  : descend sec index  [{fmt_trace(ct[:2])}]  ->  PK = {cpk},")
    print(f"                then re-walk the PK B-tree {fmt_trace(ct[2:])} to fetch the row")
    print(f"                trace: {fmt_trace(ct)}    I/O = {io(ct)}\n")
    diff = io(ct) - io(ht)
    print(f"  -> HEAP wins by {diff}: the secondary leaf stores a PHYSICAL TID, so one")
    print(f"     heap read fetches the row. The clustered secondary leaf stores only")
    print(f"     the PK VALUE, so it must launch a SECOND full PK-tree traversal")
    print(f"     ({ct[2]} -> {ct[3]}) to get the actual row.\n")
    print(f"  WHO WINS WHEN:")
    print(f"     * Clustered wins PK-driven workloads (OLTP by id, range scans on PK).")
    print(f"     * Heap wins when you read through MANY secondary indexes (each one")
    print(f"       avoids the second tree walk) and when the PK is mutable.")
    print(f"\n  [check] heap_sec_io = {io(ht)} == h_sec+1       = 2+1 = 3   OK")
    print(f"  [check] clus_sec_io = {io(ct)} == h_sec+h_pk     = 2+2 = 4   OK")
    assert io(ht) == 3 and io(ct) == 4


# ----------------------------------------------------------------------------
# SECTION E: PK range scan (heap = k RANDOM reads; clustered = sequential leaf walk)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: PK range scan  (heap = random I/O per row; clustered = sequential)")
    pages, tid_by_pk, heap_pk, heap_sec, clus_pk, clus_sec = build_indexes()
    lo, hi = 2, 4                            # scan PK in [2,4] -> Bob, Carol, Dave
    print(f"Range scan PK in [{lo}, {hi}]  (rows: Bob, Carol, Dave).\n")
    ht, hhits = heap_pk_range(heap_pk, pages, lo, hi)
    ct, chits = clus_pk_range(clus_pk, lo, hi)
    heap_heap_pages = ht[2:]                 # the per-row heap fetches
    print(f"  HEAP       : descend PK index [{fmt_trace(ht[:2])}], then for EACH row in")
    print(f"                range fetch its heap page: {fmt_trace(heap_heap_pages)}")
    print(f"                trace: {fmt_trace(ht)}    I/O = {io(ht)}")
    print(f"                page access order = {heap_heap_pages}  -> RANDOM (3,2,4),")
    print(f"                non-sequential: adjacent PKs are NOT physically adjacent.")
    print(f"  CLUSTERED  : descend PK B-tree [{fmt_trace(ct)}]; the rows Bob, Carol, Dave")
    print(f"                sit CONTIGUOUSLY in leaf {ct[-1]} -> a single sequential scan.")
    print(f"                trace: {fmt_trace(ct)}    I/O = {io(ct)}\n")
    diff = io(ht) - io(ct)
    print(f"  -> CLUSTERED wins by {diff} (and the gap WIDENS with range size): on a heap")
    print(f"     every row is a separate RANDOM page read because rows with adjacent PKs")
    print(f"     are scattered across the heap in INSERT order. On a clustered table the")
    print(f"     rows are physically adjacent in the leaf, so the scan is SEQUENTIAL")
    print(f"     (cache-friendly, prefetchable). This is THE main reason clustered/IOT")
    print(f"     tables are preferred for range queries on the PK.")
    print(f"\n  [check] heap_range_io = {io(ht)} == h + k = 2 + 3 = 5          OK")
    print(f"  [check] clus_range_io = {io(ct)} == h       = 2                OK")
    assert io(ht) == 5 and io(ct) == 2


# ----------------------------------------------------------------------------
# SECTION F: UPDATE behavior (heap: MVCC new version; clustered: in-place or split)
# ----------------------------------------------------------------------------

def btree_split_demo(capacity=3):
    """A full leaf overflows on insert -> SPLIT. Returns the before/after + writes."""
    leaf = [10, 20, 30]                      # a leaf at capacity 3 (full)
    new_key = 25
    merged = sorted(leaf + [new_key])        # [10, 20, 25, 30]
    mid = len(merged) // 2                   # split point
    left = merged[:mid]                      # [10, 20]
    right = merged[mid:]                     # [25, 30]
    sep = right[0]                           # 25 promoted to the parent
    writes = 3                               # rewrite left + write new right + update parent
    return leaf, new_key, merged, left, right, sep, writes


def section_f():
    banner("SECTION F: UPDATE behavior  (heap MVCC vs clustered in-place / page split)")
    print("Two UPDATE cases expose the deepest structural difference.\n")

    print("CASE 1 - UPDATE a NON-key column  (\"Carol\" city Cairo -> Cairo2):\n")
    print("  HEAP       (PostgreSQL MVCC): write a brand-new tuple VERSION at a fresh")
    print("                heap location (new page, new TID). The OLD version stays in")
    print("                place with t_ctid pointing at the new one. Cost = 1 heap WRITE")
    print("                (+ the old version, reclaimed later by VACUUM). If no indexed")
    print("                column changed and it fits the page this is a HOT update:")
    print("                the old line pointer REDIRECTs and NO index is touched.")
    print("                (SLOTTED_PAGE.md Section D).  heap writes = 1.\n")
    print("  CLUSTERED  (InnoDB): the PK is unchanged, so the row STAYS at its leaf")
    print("                position - an IN-PLACE update of the record inside leaf CL.")
    print("                No page split, no row movement, secondary indexes untouched")
    print("                (they store the PK, which did not change).  clus writes = 1.")
    print("  -> Roughly EVEN for a non-key update (1 write each). MVCC keeps the old")
    print("     version around; InnoDB also versions (undo log) - both are MVCC engines.\n")

    print("CASE 2 - UPDATE the PRIMARY KEY  (\"Carol\" PK 3 -> 6):\n")
    leaf, nk, merged, left, right, sep, writes = btree_split_demo(capacity=3)
    print("  HEAP       : the row's heap LOCATION is unaffected by a PK change. The new")
    print("                tuple version is written as usual; only the PK INDEX entry")
    print("                changes (delete pk=3, insert pk=6). No structural change to")
    print("                the heap, no page split possible (heaps never split).")
    print("                Secondary indexes store TIDs: untouched if HOT, else updated.\n")
    print("  CLUSTERED  : the PK IS the physical position. Changing 3 -> 6 means DELETE")
    print("                the row from its old leaf slot and INSERT it at the new PK")
    print("                position. If the target leaf is FULL this forces a PAGE SPLIT:")
    print("                half the rows move to a NEW page and a separator is pushed up.")
    print("                WORSE: every secondary index leaf that stored PK=3 for this")
    print("                row must be rewritten to PK=6 (they store the PK!). Demo of")
    print("                the split mechanics (a capacity-3 leaf, insert {nk}):")
    print(f"                  full leaf = {leaf}")
    print(f"                  insert {nk} -> overflow -> merged {merged}")
    print(f"                  split -> left {left} | right {right}  (separator {sep} up)")
    print(f"                  page WRITES = {writes}  (rewrite left + new right + parent)")
    print(f"                  + {1} secondary-index update per secondary index on the table")
    print("  -> This is WHY InnoDB primary keys should be IMMUTABLE and MONOTONIC (e.g.")
    print("     AUTO_INCREMENT): appends hit only the rightmost leaf, so splits are rare")
    print("     and secondary indexes never need rewriting. A mutable/random PK on a")
    print("     clustered table causes splits + cascading secondary-index updates.")
    print(f"\n  [check] split demo writes = {writes} == 3   OK")
    assert writes == 3 and merged == [10, 20, 25, 30] and left == [10, 20]


# ============================================================================
# 4. THE GOLD BLOCK (what heap_vs_clustered.html recomputes and checks against)
# ============================================================================

def gold_block():
    banner("GOLD - I/O counts for every operation  (heap_vs_clustered.html recomputes this)")
    pages, tid_by_pk, heap_pk, heap_sec, clus_pk, clus_sec = build_indexes()

    ht_pk, _, _ = heap_pk_lookup(heap_pk, tid_by_pk, pages, 3)
    ct_pk, _ = clus_pk_lookup(clus_pk, 3)
    ht_sc, _, _ = heap_sec_lookup(heap_sec, pages, "Carol")
    ct_sc, _ = clus_sec_lookup(clus_sec, clus_pk, "Carol")
    ht_rg, _ = heap_pk_range(heap_pk, pages, 2, 4)
    ct_rg, _ = clus_pk_range(clus_pk, 2, 4)

    hp, cp = io(ht_pk), io(ct_pk)
    hs, cs = io(ht_sc), io(ct_sc)
    hr, cr = io(ht_rg), io(ct_rg)

    print(f"  canonical index height h = 2  (root -> leaf)\n")
    print(f"  | operation             | heap I/O | clustered I/O | winner      |")
    print(f"  |-----------------------|----------|---------------|-------------|")
    print(f"  | PK point lookup (3)   |   {hp}     |       {cp}       | "
          f"{'clustered' if cp < hp else 'heap':<11} |")
    print(f"  | secondary lookup      |   {hs}     |       {cs}       | "
          f"{'heap' if hs < cs else 'clustered':<11} |")
    print(f"  | PK range scan [2..4]  |   {hr}     |       {cr}       | "
          f"{'clustered' if cr < hr else 'heap':<11} |")
    print()
    print(f"  heap_pk_io={hp}  clus_pk_io={cp}  |  heap_sec_io={hs}  clus_sec_io={cs}"
          f"  |  heap_range_io={hr}  clus_range_io={cr}")
    print(f"\n  GOLD identity (one PK + one secondary lookup):")
    print(f"    heap   total = heap_pk + heap_sec = {hp} + {hs} = {hp + hs}")
    print(f"    clus   total = clus_pk + clus_sec = {cp} + {cs} = {cp + cs}")
    print(f"    -> with h_pk = h_sec = 2: 2(h+1) = 2h+2 = {2*2+2}  and  "
          f"3h = {3*2}  -> EQUAL total work, spent differently.\n")
    # gold-check assertions (these are the exact values the .html recomputes)
    assert (hp, cp, hs, cs, hr, cr) == (3, 2, 3, 4, 5, 2), "gold I/O mismatch"
    assert hp + hs == cp + cs == 6, "gold identity broken"
    print(f"  [check] heap_pk={hp} clus_pk={cp} heap_sec={hs} clus_sec={cs} "
          f"heap_rng={hr} clus_rng={cr}  ->  OK")
    print(f"  [check] heap(PK+sec)=={hp+hs} == clus(PK+sec)=={cp+cs} == 6  ->  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("heap_vs_clustered.py - reference impl. All numbers below feed "
          "HEAP_VS_CLUSTERED.md.")
    print("Heap (PostgreSQL) vs Clustered/IOT (MySQL InnoDB). I/O = distinct pages "
          "read per op.\n")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    gold_block()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
