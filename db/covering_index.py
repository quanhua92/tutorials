"""
covering_index.py - Reference implementation of the covering index
(a.k.a. Index-Only Scan), and the lineage
    regular index (key -> TID -> heap read)
    -> covering index (INCLUDE extra columns -> skip the heap)
    -> Index-Only Scan.

This is the single source of truth that COVERING_INDEX.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 covering_index.py

============================================================================
THE INTUITION (read this first) - the librarian who already read the page
============================================================================
You want one fact: "what is Cara's name?", and you only know her email. Two
buildings stand on campus:

  * The INDEX BUILDING has a wall of sorted cards: (email -> shelf position).
    Tiny cards, fast to flip through. But a card only tells you WHERE on the
    shelf the full folder lives.
  * The HEAP BUILDING (the warehouse) holds the full folders - every column
    (id, email, name, age, city, ...) - on big slow shelves.

A NORMAL query walks to BOTH buildings:
    1. flip cards in the Index Building to find Cara's shelf position (TID),
    2. walk across campus to the Heap Building, pull the folder, read `name`.
That second trip is the expensive one - a random page read of the (big, cold)
heap, for EVERY matching row.

A COVERING index photocopies ONE extra column (`name`) onto the index card
itself. Now the card reads (email, name -> TID). The query never leaves the
Index Building: flip the card, read `name`, done. The heap trip is GONE.
That is the entire trick: pay a little index storage to delete a random heap
read from every lookup.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   heap         : the table itself - the big unordered pile of full tuples,
                  one tuple per row, laid out on fixed-size PAGES. The "slow"
                  building. 🔗 See HEAP_VS_CLUSTERED.md / heap_vs_clustered.py.
   TID          : tuple id = (page, offset). The index card's "shelf position".
                  The index stores key -> TID; you follow the TID to the heap.
   B-tree index : the sorted card wall. key -> TID. 🔗 See BTREE.md / btree.py
                  for the tree mechanics; here we only care about the LEAF.
   index leaf   : the bottom page of the B-tree. Holds the sorted entries.
                  A "plain" leaf entry = (key, TID). A "covering" entry =
                  (key, INCLUDE cols..., TID). This file is about that entry.
   key column   : the column the index is SORTED on (the WHERE predicate
                  column). Part of the B-tree ORDER: comparisons happen here.
   INCLUDE col  : a column STORED in the leaf but NOT sorted on. PostgreSQL
                  11+ `CREATE INDEX ... INCLUDE (...)`. No comparison cost,
                  no sort-order impact - it just rides along for the read.
   heap fetch   : following a TID to read the heap page = 1 random page I/O.
                  The thing a covering index lets you AVOID.
   visibility   : "is this tuple visible to my transaction?" A covering index
   map            still must answer this. PostgreSQL keeps a 1-bit-per-page
                  bitmap (the visibility map): if the page is all-visible,
                  the index entry's TID need NOT be followed. VACUUM sets it.
   Index-Only   : PostgreSQL's name for the scan that reads only the index
   Scan           leaf and (when the visibility map allows) skips the heap.
                  "Index-Only" is a slight misnomer: it can still touch the
                  heap for visibility on dirty pages.

============================================================================
THE LINEAGE (sources)
============================================================================
   plain B-tree     (Bayer & McCreight 1972; Comer 1979): key -> TID. Every
                     lookup = index traversal + 1 heap fetch per matching row.
   INCLUDE clause   PostgreSQL 11 (2018), " covering indexes with INCLUDE":
                     store extra columns in the leaf without making them part
                     of the sort key. MS SQL Server had `INCLUDE` since 2005.
   clustered /      InnoDB stores the WHOLE row in the PK index, so a PK
   clustered PK       lookup is naturally covering for ANY column set. A
                     SECONDARY InnoDB index stores (key -> PK), so a non-PK
                     column needs secondary -> PK -> clustered = an extra
                     "heap-like" fetch. Covering a secondary index avoids it.
   Index-Only Scan  PostgreSQL 9.2 (2012): the planner node that recognizes
                     all needed columns are in the index AND the visibility
                     map allows skipping the heap.

KEY FORMULAS (all asserted/printed in the sections below):
   plain leaf entry size      = key_bytes + tid_bytes + leaf_hdr
   covering leaf entry size   = key_bytes + sum(include_bytes) + tid_bytes + leaf_hdr
   leaf capacity (entries)    = page_size // entry_size
   heap pages                 = ceil(N / tuples_per_page)
   index height h             = smallest h with fanout^(h-1) >= n_leaves
   point lookup, regular      = h (index) + 1 (heap)
   point lookup, index-only   = h (index) + 0 (heap, when all-visible)
   range scan, regular        = (h + L - 1) index + R heap      (R scattered)
   range scan, index-only     = (h + L' - 1) index + 0 heap
   index-only w/ visibility f = index reads + R*(1-f) heap       (f=fraction visible)
   write cost, UPDATE include = ~2 index I/O (del+ins) + loss of HOT
   (HOT = Heap-Only Tuple update; only possible when NO indexed column changes)

Conventions:
   PAGE_SIZE  = 8192 bytes (PostgreSQL default 8 KB)
   N_ROWS     = 1,000,000 (the scale model for the I/O tables)
   The tiny trace table (5 rows) is used in Sections A/B to show the steps;
   the 1M-row model is used in Sections E/F for the I/O comparison tables.
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# ============================================================================
# PHYSICAL LAYOUT CONSTANTS (deterministic, PostgreSQL-flavoured)
# ============================================================================
PAGE_SIZE = 8192          # bytes (PostgreSQL default 8 KB block)
TID_BYTES = 6             # PostgreSQL item-pointer = 6 bytes
CHILD_PTR = 4             # internal-node child pointer (offset), 4 bytes
LEAF_HDR = 16             # per-entry index tuple header overhead (~16 B)
KEY_BYTES = 50            # avg email (varchar) - the key column
INCLUDE_BYTES = {         # avg size of candidate INCLUDE columns
    "name": 30,
    "age": 4,
    "city": 20,
}


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 1. THE TINY TRACE TABLE (5 rows) - to show the access path step by step
# ============================================================================
# (id, email, name, age, city) - deterministic, sorted-by-insertion into heap.
USERS = [
    (1, "alice@x.com", "Alice", 30, "Hanoi"),
    (2, "bob@x.com",   "Bob",   25, "Saigon"),
    (3, "cara@x.com",  "Cara",  41, "Da Nang"),
    (4, "dave@x.com",  "Dave",  28, "Hue"),
    (5, "eve@x.com",   "Eve",   36, "Hanoi"),
]


def build_heap():
    """Heap = {tid: tuple}. tid = (page, offset). 2 tuples per page so the
    trace is small enough to print every page."""
    heap = {}
    for i, row in enumerate(USERS):
        heap[(i // 2, i % 2)] = row
    return heap


def build_index_plain(heap):
    """Plain B-tree index on email: sorted leaf entries = (email, tid)."""
    return sorted(((row[1], tid) for tid, row in heap.items()),
                  key=lambda e: e[0])


def build_index_covering(heap, include_cols):
    """Covering B-tree index on email INCLUDE(include_cols):
    sorted leaf entries = (email, {col: val ...}, tid)."""
    col_idx = {"name": 2, "age": 3, "city": 4}
    entries = []
    for tid, row in heap.items():
        vals = {c: row[col_idx[c]] for c in include_cols}
        entries.append((row[1], vals, tid))
    return sorted(entries, key=lambda e: e[0])


# ============================================================================
# 2. THE SCALE-MODEL HELPERS (1M rows) - for the I/O comparison tables
# ============================================================================
def index_stats(key_bytes, include_total, n_rows):
    """Return (entry_size, leaf_cap, n_leaves, fanout, height) for a B-tree
    index whose leaf entries are key_bytes + include_total + TID + header."""
    entry = key_bytes + include_total + TID_BYTES + LEAF_HDR
    leaf_cap = PAGE_SIZE // entry
    n_leaves = max(1, math.ceil(n_rows / leaf_cap))
    fanout = PAGE_SIZE // (key_bytes + CHILD_PTR)   # children per internal page
    # height: smallest h with fanout^(h-1) >= n_leaves (>= 1)
    h = 1
    while fanout ** (h - 1) < n_leaves:
        h += 1
    return entry, leaf_cap, n_leaves, fanout, h


def total_index_pages(n_leaves, fanout):
    """Sum of leaf pages + all internal levels (including root)."""
    total = n_leaves
    nodes = n_leaves
    while nodes > 1:
        nodes = math.ceil(nodes / fanout)
        total += nodes
    return total


# ----------------------------------------------------------------------------
# SECTION A: regular index scan - the two-trip access path (2 logical I/Os)
# ----------------------------------------------------------------------------
def section_a():
    banner("SECTION A: regular index scan - key -> TID -> heap (2 trips)")
    heap = build_heap()
    idx = build_index_plain(heap)
    print("Query:  SELECT name FROM users WHERE email = 'cara@x.com'\n")
    print("Index on (email) - PLAIN leaf entries: (email, tid)\n")
    print("  leaf (sorted by email):")
    for email, tid in idx:
        print(f"    ({email:<13}, tid={tid})")
    print()
    target = "cara@x.com"
    # Step 1: B-tree traversal -> find the leaf entry -> get TID
    hit = next(e for e in idx if e[0] == target)
    tid = hit[1]
    print("ACCESS PATH (regular Index Scan):")
    print("  STEP 1 [index traversal]  : walk the B-tree to the leaf,")
    print(f"                             find entry ({hit[0]}, tid={tid})")
    print("                             -> this is `height` index page reads")
    print("  STEP 2 [heap fetch]       : follow tid={tid} -> read HEAP page "
          f"{tid[0]}")
    row = heap[tid]
    print(f"                             heap page {tid[0]} holds {row}")
    # Step 3: extract name
    name = row[2]
    print(f"  STEP 3 [project]          : extract name = '{name}' from the "
          "tuple\n")
    print("I/O model (point lookup):")
    print("  regular_index_scan  =  height(index pages)  +  1 heap fetch")
    print("  The heap fetch is a RANDOM page read of a (big, cold) page.")
    print("  For 1 matching row this is the dominant cost - see Section E.\n")
    print("[check] name returned == 'Cara':",
          "OK" if name == "Cara" else "FAIL")


# ----------------------------------------------------------------------------
# SECTION B: covering index - INCLUDE(name) -> skip the heap entirely
# ----------------------------------------------------------------------------
def section_b():
    banner("SECTION B: covering index - INCLUDE(name) -> skip the heap")
    heap = build_heap()
    idx = build_index_covering(heap, include_cols=["name"])
    print("DDL:    CREATE INDEX users_email_idx ON users (email) "
          "INCLUDE (name);\n")
    print("Covering leaf entries: (email, {name}, tid)  - name rides along\n")
    print("  leaf (sorted by email):")
    for email, vals, tid in idx:
        print(f"    ({email:<13}, name={vals['name']:<6}, tid={tid})")
    print()
    target = "cara@x.com"
    hit = next(e for e in idx if e[0] == target)
    print("ACCESS PATH (Index-Only Scan, visibility map = all-visible):")
    print("  STEP 1 [index traversal]  : walk the B-tree to the leaf,")
    print(f"                             find entry ({hit[0]}, name="
          f"{hit[1]['name']}, tid={hit[2]})")
    print("                             -> `height` index page reads")
    print("  STEP 2 [skip heap]        : name IS ALREADY on the card -")
    print("                             NO heap fetch. (visibility map OK)")
    name = hit[1]["name"]
    print(f"  STEP 3 [project]          : return name = '{name}' directly\n")
    print("I/O model (point lookup, all-visible):")
    print("  covering_index_scan  =  height(index pages)  +  0 heap fetches")
    print("  The random heap read from Section A is GONE. That is the win.\n")
    print("[check] name returned == 'Cara':",
          "OK" if name == "Cara" else "FAIL")


# ----------------------------------------------------------------------------
# SECTION C: visibility map - why index-only still (sometimes) touches heap
# ----------------------------------------------------------------------------
def section_c():
    banner("SECTION C: visibility map - index-only is conditional on it")
    print("An index entry has a TID but does NOT know whether the tuple it")
    print("points at is VISIBLE to the current transaction (MVCC). PostgreSQL")
    print("answers this with the VISIBILITY MAP: a 1-bit-per-heap-page bitmap.\n")
    print("  bit = 1 (all-visible) : every tuple on the page is visible to ALL")
    print("                          transactions -> index-only scan may SKIP")
    print("                          the heap fetch for entries on this page.")
    print("  bit = 0 (not all-visible): at least one tuple may be invisible ->")
    print("                          index-only scan MUST fetch the heap page to")
    print("                          check visibility -> the optimization is")
    print("                          LOST for that row (it degrades to a fetch).\n")
    print("Who sets / clears the bit:")
    print("  SET   by VACUUM (and when a page becomes all-visible after the")
    print("        transaction that dirtied it commits + a VACUUM/autovacuum")
    print("        pass confirms it). This is WHY VACUUM matters for index-only")
    print("        scan performance: no VACUUM -> bits stay 0 -> index-only")
    print("        silently falls back to heap fetches.")
    print("  CLEAR by any UPDATE or DELETE that touches the page (the page is")
    print("        no longer guaranteed all-visible).\n")

    # Model the effective heap reads as a function of the visible fraction f.
    print("EFFECTIVE heap reads for an index-only scan over R matching rows:")
    print("  heap_reads  =  R * (1 - f)     where f = fraction of pages "
          "all-visible\n")
    R = 1000
    print(f"R = {R} matching rows. f = fraction of heap pages all-visible:\n")
    print("| vacuum state        | f (visible) | fallback heap fetches = R*(1-f) |")
    print("|---------------------|-------------|----------------------------------|")
    for label, f in [("just VACUUMed (fresh)", 1.00),
                     ("light write churn",     0.90),
                     ("heavy UPDATE workload", 0.50),
                     ("never VACUUMed",        0.00)]:
        fetches = R * (1 - f)
        print(f"| {label:<19} | {f:>11.2f} | "
              f"{fetches:>32.0f} |")
    print()
    print("TAKEAWAY: a covering index only delivers 0 heap reads when the")
    print("visibility map is healthy. On a write-heavy table that is never")
    print("VACUUMed, index-only scan degenerates toward the regular cost.")
    # gold sanity: f=1 -> 0 fetches
    assert R * (1 - 1.0) == 0
    print("\n[check] f=1.0 -> 0 heap fetches (true index-only): OK")


# ----------------------------------------------------------------------------
# SECTION D: INCLUDE vs key columns - what lives in the leaf entry
# ----------------------------------------------------------------------------
def section_d():
    banner("SECTION D: INCLUDE vs key columns - leaf entry layout")
    print("Two ways to put `name` into an index on email:\n")
    print("  (a) compound KEY :  CREATE INDEX ... ON users (email, name)")
    print("      name IS part of the sort order. The B-tree compares on")
    print("      (email, name) pairs. Useful if you ALSO range-scan/filter on")
    print("      name. Cost: every comparison carries name; narrower fanout.\n")
    print("  (b) INCLUDE col  :  CREATE INDEX ... ON users (email) INCLUDE(name)")
    print("      name is STORED in the leaf but NOT compared. Sort order is")
    print("      still just email. No comparison overhead, same fanout on the")
    print("      key. Cost: the leaf entry is bigger -> fewer entries per leaf")
    print("      -> more leaves -> (marginally) taller tree, more index space.\n")
    print("LEAF ENTRY LAYOUT (bytes), email key + name include, 8 KB page:\n")
    plain_entry = KEY_BYTES + TID_BYTES + LEAF_HDR
    cover_entry = KEY_BYTES + INCLUDE_BYTES["name"] + TID_BYTES + LEAF_HDR
    compound_entry = KEY_BYTES + INCLUDE_BYTES["name"] + TID_BYTES + LEAF_HDR
    print("  +-----------------------------------------+----------+")
    print("  | field                                   | bytes    |")
    print("  +-----------------------------------------+----------+")
    print(f"  | key: email (the sort column)            | {KEY_BYTES:>8} |")
    print(f"  | [INCLUDE] name (stored, not compared)   | "
          f"{INCLUDE_BYTES['name']:>8} |   <- only in covering/compound")
    print(f"  | TID (page, offset)                      | {TID_BYTES:>8} |")
    print(f"  | index tuple header                      | {LEAF_HDR:>8} |")
    print("  +-----------------------------------------+----------+")
    print(f"  | plain leaf entry    (email, TID)        | "
          f"{plain_entry:>8} |")
    print(f"  | covering leaf entry (email, name, TID)  | "
          f"{cover_entry:>8} |")
    print(f"  | compound KEY entry  ((email,name), TID) | "
          f"{compound_entry:>8} |   same bytes, different ROLE")
    print("  +-----------------------------------------+----------+\n")
    print(f"plain leaf cap    = {PAGE_SIZE} // {plain_entry}  = "
          f"{PAGE_SIZE // plain_entry} entries/page")
    print(f"covering leaf cap = {PAGE_SIZE} // {cover_entry}  = "
          f"{PAGE_SIZE // cover_entry} entries/page")
    print(f"compound leaf cap = {PAGE_SIZE} // {compound_entry}  = "
          f"{PAGE_SIZE // compound_entry} entries/page  "
          "(same bytes -> same cap, but comparisons cost more)\n")
    print("RULE OF THUMB:")
    print("  * Need to FILTER / RANGE-SCAN on the column? -> make it a KEY.")
    print("  * Only need to READ it back in the SELECT?   -> INCLUDE it.")
    print("    INCLUDE gives the covering benefit without slowing comparisons")
    print("    or narrowing the key's sort fanout.")
    assert cover_entry == plain_entry + INCLUDE_BYTES["name"]
    print("\n[check] covering entry == plain entry + name bytes:",
          f"{cover_entry} == {plain_entry}+{INCLUDE_BYTES['name']} OK")


# ----------------------------------------------------------------------------
# SECTION E: when covering helps - the I/O comparison tables (1M-row model)
# ----------------------------------------------------------------------------
def section_e():
    banner("SECTION E: when covering helps - I/O comparison (N = 1,000,000)")
    N = 1_000_000
    TUPLES_PER_PAGE = 40
    heap_pages = math.ceil(N / TUPLES_PER_PAGE)
    plain = index_stats(KEY_BYTES, 0, N)                       # email only
    cover = index_stats(KEY_BYTES, INCLUDE_BYTES["name"], N)   # email INCLUDE name
    pe, pl_cap, pl_leaves, pl_fan, pl_h = plain
    ce, cv_cap, cv_leaves, cv_fan, cv_h = cover
    plain_pages = total_index_pages(pl_leaves, pl_fan)
    cover_pages = total_index_pages(cv_leaves, cv_fan)
    print(f"Physical model: page = {PAGE_SIZE} B, N = {N:,} rows, "
          f"{TUPLES_PER_PAGE} tuples/heap page -> {heap_pages:,} heap pages\n")
    print("Index layouts:")
    print(f"  PLAIN    (email)              : entry={pe} B, leaf_cap={pl_cap}, "
          f"leaves={pl_leaves:,}, height={pl_h}")
    print(f"  COVERING (email INCLUDE name) : entry={ce} B, leaf_cap={cv_cap}, "
          f"leaves={cv_leaves:,}, height={cv_h}")
    print(f"  index size: plain = {plain_pages:,} pages, "
          f"covering = {cover_pages:,} pages "
          f"(+{cover_pages - plain_pages:,}, "
          f"{(cover_pages / plain_pages - 1) * 100:.1f}%)\n")

    R = 1000  # rows matched by the range predicate
    # leaves scanned for a range matching R rows
    pl_scanned = math.ceil(R / pl_cap)
    cv_scanned = math.ceil(R / cv_cap)
    # index page reads for a range = height + (leaves scanned - 1)
    plain_range_idx = pl_h + pl_scanned - 1
    cover_range_idx = cv_h + cv_scanned - 1
    # heap reads: regular must fetch every matching row's page (worst case:
    # heap is NOT clustered by email, so up to R distinct pages)
    plain_range_heap = R
    cover_range_heap = 0

    print("(1) POINT LOOKUP  SELECT name FROM users WHERE email = X  "
          "(1 matching row):\n")
    print("| plan              | index reads | heap reads | TOTAL I/O |")
    print("|-------------------|-------------|------------|-----------|")
    reg = pl_h + 1
    ion = cv_h + 0
    print(f"| regular Index Scan| {pl_h:>11} | {1:>10} | {reg:>9} |")
    print(f"| Index-Only Scan   | {cv_h:>11} | {0:>10} | {ion:>9} |")
    print(f"\n  -> covering saves {reg - ion} page read(s) per lookup "
          f"(the heap fetch). For a hot point-lookup path this is huge.\n")

    print(f"(2) RANGE SCAN  SELECT name FROM users WHERE email BETWEEN ...  "
          f"({R} matching rows, heap NOT clustered by email):\n")
    print("| plan              | index reads     | heap reads | TOTAL I/O |")
    print("|-------------------|-----------------|------------|-----------|")
    rtot = plain_range_idx + plain_range_heap
    ctot = cover_range_idx + cover_range_heap
    print(f"| regular Index Scan| {plain_range_idx:>15} | "
          f"{plain_range_heap:>10} | {rtot:>9} |")
    print(f"| Index-Only Scan   | {cover_range_idx:>15} | "
          f"{cover_range_heap:>10} | {ctot:>9} |")
    print(f"\n  -> covering saves {rtot - ctot} page reads on a {R}-row range "
          f"(all {plain_range_heap} heap fetches vanish). Range scans are where")
    print("     covering indexes pay back the most.\n")

    print("(3) AGGREGATION\n")
    print("  (3a) SELECT COUNT(*) FROM users  (NO predicate, needs NO column):")
    print("       any index supports index-only COUNT (no data column needed).")
    print(f"       full heap scan = {heap_pages:,} reads ; "
          f"index-only scan (plain idx) = {plain_pages:,} reads ; "
          f"saves {heap_pages - plain_pages:,} reads")
    print("       NOTE: pure COUNT(*) needs no column, so even the PLAIN index")
    print("       is already 'covering' for it. The INCLUDE earns its keep the")
    print("       moment a stored column appears in the SELECT list:\n")
    print(f"  (3b) SELECT MIN(name), MAX(name) FROM users WHERE email BETWEEN "
          f"... ({R} rows):")
    print("       MIN/MAX over name needs name in the index -> only COVERING:")
    print(f"         regular: must fetch {R} heap pages for the names = "
          f"{plain_range_idx + R} reads")
    print(f"         covering: scan {cv_scanned} index leaves, take min/max = "
          f"{cover_range_idx} reads  (index-only, sorted -> first/last leaf)")
    print(f"       -> covering saves {(plain_range_idx + R) - cover_range_idx} "
          "reads on a min/max aggregation.\n")

    # ---- GOLD values pinned for covering_index.html ----
    print("GOLD (pinned for covering_index.html), N = 1,000,000:")
    print(f"  height (plain)      = {pl_h}")
    print(f"  height (covering)   = {cv_h}")
    print(f"  point lookup regular  total = {reg}")
    print(f"  point lookup index-only  total = {ion}")
    print(f"  range scan regular  total = {rtot}")
    print(f"  range scan index-only  total = {ctot}")
    # gold asserts
    assert pl_h == 3 and cv_h == 3
    assert reg == 4 and ion == 3
    assert rtot == 1011 and ctot == 15
    print("\n[check] GOLD I/O counts reproduce from the formula: OK")


# ----------------------------------------------------------------------------
# SECTION F: when it hurts - write amplification, HOT loss, cache pressure
# ----------------------------------------------------------------------------
def section_f():
    banner("SECTION F: when it hurts - write amp, HOT loss, cache pressure")
    N = 1_000_000
    plain = index_stats(KEY_BYTES, 0, N)
    cover = index_stats(KEY_BYTES, INCLUDE_BYTES["name"], N)
    plain_pages = total_index_pages(plain[2], plain[3])
    cover_pages = total_index_pages(cover[2], cover[3])
    print("A covering index is not free. Three costs:\n")

    print("(1) WRITE AMPLIFICATION + loss of HOT (Heap-Only Tuple) updates.\n")
    print("  PostgreSQL HOT update: when you UPDATE a row and NO INDEXED column")
    print("  changes, the new tuple is placed in the SAME heap page and NO index")
    print("  is touched (no index VACUUM bloat, fast). The moment an INDEXED")
    print("  column changes, HOT is disabled and every index pointing at the row")
    print("  must be updated.\n")
    print("  Scenario: UPDATE users SET name = 'Carol' WHERE id = 3")
    print("            (name changes; email does NOT):\n")
    print("  | index on (email)               | name in index? | extra index I/O | HOT? |")
    print("  |--------------------------------|----------------|-----------------|------|")
    print("  | PLAIN   (email)                | no             |               0 |  YES |")
    print("  | COVERING(email INCLUDE name)   | YES            |            ~2* |   NO |")
    print("  (* delete old entry + insert new; can be 1-2 page writes)")
    print()
    print("  -> adding name to the index turns a FREE HOT update into ~2 index")
    print("     page writes (and the page loses its all-visible bit -> Section C)\n")

    print("(2) INDEX SIZE / CACHE PRESSURE.\n")
    print("  | index            | leaf entry | pages      | vs plain     |")
    print("  |------------------|------------|------------|--------------|")
    print(f"  | plain (email)    | {plain[0]:>10} | {plain_pages:>10,} | baseline     |")
    print(f"  | covering         | {cover[0]:>10} | {cover_pages:>10,} | "
          f"+{(cover_pages - plain_pages):,} ({(cover_pages / plain_pages - 1) * 100:.1f}%) |")
    print()
    print(f"  A {(cover_pages / plain_pages - 1) * 100:.0f}% bigger index means that many")
    print("  more pages competing for the buffer cache. If the heap is now")
    print("  evicted more often, your OTHER queries (that DO need the heap) get")
    print("  slower. The read win on the covered query can be offset by cache")
    print("  misses elsewhere.\n")

    print("(3) BREAK-EVEN (reads saved vs writes added).\n")
    saves_per_read = 1          # each point lookup saves 1 heap read
    cost_per_update = 2         # each name UPDATE costs ~2 index writes
    print(f"  Each covered point-lookup saves ~{saves_per_read} heap read.")
    print(f"  Each name-UPDATE costs ~{cost_per_update} extra index writes.")
    print(f"  Covering wins on I/O when  reads / updates  >  "
          f"{cost_per_update / saves_per_read:.1f}\n")
    print("  | workload                         | covering worth it?            |")
    print("  |----------------------------------|-------------------------------|")
    print("  | read-heavy (logins, profile view)| YES - saves a fetch every read|")
    print("  | write-heavy (name updated often) | NO  - 2 writes per update     |")
    print("  | range-scan heavy on name         | YES - saves N fetches         |")
    print("  | never VACUUMed dirty table       | MAYBE - visibility map hurts  |")
    print()
    print("RULE OF THUMB: add INCLUDE columns for columns that are READ in hot")
    print("query paths but RARELY updated. Never INCLUDE a churn-heavy column.")
    assert cost_per_update / saves_per_read == 2.0
    print("\n[check] break-even reads/updates ratio == 2.0: OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("covering_index.py - reference impl. All numbers feed "
          "COVERING_INDEX.md.")
    print("page_size =", PAGE_SIZE, "bytes ; pure Python stdlib.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
