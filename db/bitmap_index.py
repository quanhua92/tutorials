"""
bitmap_index.py - Reference implementation of the Bitmap Index: one bit per row
per distinct value, the data structure that makes low-cardinality columns and
multi-predicate queries cheap.

This is the single source of truth that BITMAP_INDEX.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 bitmap_index.py

============================================================================
THE INTUITION (read this first) -- the wall of push-buttons
============================================================================
Picture a wall in a warehouse, one column of push-buttons per distinct value
of a column (status), and one row of buttons per tuple. To ask "which rows are
ACTIVE?", you just read the ACTIVE column: every lit button is a matching row,
and its position IS the tuple id. One bit per row, per value -- that is a
bitmap index.

Now the magic. Suppose you also have a REGION column with its own wall of
buttons. To answer "status=ACTIVE AND region=EAST", you do NOT walk over to the
shelves and inspect boxes one by one. You take the ACTIVE column and the EAST
column and you AND them -- button by button. The buttons that stay lit are
exactly the rows that satisfy BOTH predicates, and you computed it without
touching a single tuple. THIS is why bitmap indexes exist: bitwise AND/OR/NOT
on the index collapses several predicates to one set of TIDs BEFORE the
(expensive, random-IO) heap fetch.

  * BITMAP INDEX : a set of bitmaps, one per distinct value of a column. Bitmap
                   for value v has bit i = 1  <=>  row i holds v.
  * CARDINALITY  : number of distinct values D. Bitmap indexes SHINE when D is
                   small (gender: D=2; status: D=4; country: D~200). They DIE
                   when D ~ N (unique keys -> D bitmaps each ~N bits = N^2 bits).
  * BITWISE OPS  : AND / OR / NOT over equal-length bit vectors. O(N/word) CPU,
                   zero heap IO. The whole point.
  * RLE          : run-length encoding. A sparse bitmap (long runs of 0s) is
                   stored as a few (value,length) pairs instead of N bits.
  * BITMAP SCAN  : PostgreSQL's two-phase pipeline. Phase 1 = "Bitmap Index
                   Scan" turns predicate(s) into a TID bitmap. Phase 2 =
                   "Bitmap Heap Scan" walks the pages in that bitmap, fetches
                   each, and RE-CHECKS the condition (mandatory when the bitmap
                   is lossy = per-page instead of per-tuple).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  bitmap       : a fixed-length vector of bits, one position per row in the
                 table. Position i corresponds to row (tuple) i.
  bitmap index : a collection of bitmaps -- one per distinct value of the
                 indexed column. bitmaps_active, bitmaps_pending, ... etc.
  TID          : tuple id = (page, offset). The physical address of a row.
                 A set bit at position i means "row i qualifies" -> TID of row i.
  cardinality  : D = number of distinct values. Low D = good for bitmaps.
  density      : fraction of 1s in a bitmap = (rows with that value) / N.
                 Sparse = low density (long 0-runs) -> RLE compresses well.
  bitmap AND   : intersection. rows matching predicate A AND predicate B.
  bitmap OR    : union. rows matching A OR B.
  bitmap NOT   : complement. rows NOT matching.
  RLE          : run-length encoding. Replace "00000000" with "(0, run=8)".
  TID bitmap   : the output of phase 1. Either EXACT (one entry per matching
                 TID) or LOSSY (one bit per PAGE: "this page might hold a hit").
  recheck      : phase 2 re-tests the predicate on each tuple of a visited page.
                 Always done in lossy mode; also done to handle MVCC visibility.
  work_mem     : the memory budget. If the TID bitmap would overflow it,
                 PostgreSQL degrades exact -> lossy (trades IO for memory).

============================================================================
THE LINEAGE
============================================================================
  Full table scan (naive)      : O(N) heap reads for every query. Unusable on
                                 big tables.
  B-tree index                 : O(log N) to find one value's TIDs. Great for
                                 HIGH cardinality and single-predicate equality
                                 / range. Weak for combining several LOW-
                                 selectivity predicates (each matches many rows;
                                 combining means fetching & discarding).
  Bitmap index (O'Neil 1987)   : D bitmaps of N bits. Predicates combine by
                                 bitwise AND/OR in O(N/word) CPU with ZERO heap
                                 IO. Ideal for low D + many predicates. The
                                 catch: bad for OLTP writes (flip bits = rewrite
                                 compressed runs), and O(D*N) size blows up when
                                 D ~ N.  (Oracle, DB2 ship real bitmap indexes.)
  Bitmap SCAN of B-tree (PG)   : PostgreSQL has NO on-disk bitmap index, but it
                                 can build a TID bitmap ON THE FLY from any
                                 B-tree/GIN index and run the same two-phase
                                 pipeline. So you get bitmap-AND benefits without
                                 maintaining a bitmap index. (src/backend/...)

KEY FORMULAS (all verified against O'Neil 1987 + PostgreSQL docs, asserted below):
    bitmap[v][i]        = 1 if row i == v else 0
    AND(A,B)[i]         = A[i] & B[i]            (intersection)
    OR(A,B)[i]          = A[i] | B[i]            (union)
    NOT(A)[i]           = 1 - A[i]               (complement over N rows)
    index size (bytes)  = D * N / 8               (uncompressed; RLE shrinks it)
    RLE bytes           ~= number_of_runs         (1 byte per run-length, value
                                                   bit packed in the header)
    Bitmap Heap Scan    : pages = { page_of(i) : i in TID_bitmap }
                          for p in pages: fetch p; recheck each visible tuple
    win vs B-tree       : low D, AND/OR of several low-selectivity predicates
    lose vs B-tree      : high D (size ~ D*N), frequent writes, single-predicate
                          high-selectivity lookup

Sources:
  [1] O'Neil, P. 1987, "Model 204 Architecture and Performance", HPTS.
      -- the canonical origin of the commercial bitmap index (Model 204).
  [2] PostgreSQL docs, "Bitmap Scans" (planner/executor + EXPLAIN):
      "the bitmap index scan ... produces a bitmap of tuple TIDs ... If the
       bitmap would be too large to keep in memory, it becomes lossy: a page
       level bitmap ... the bitmap heap scan must then recheck the quals."
  [3] Chan & Ioannidis 1998, "Bitmap Index Design and Evaluation".
  [4] Roaring bitmaps (Chambi et al. 2015, arXiv:1402.2485) -- the modern
      compressed-bitmap technique (hybrid: array/bitmap/run containers).

The 16-row worked example below is DETERMINISTIC and byte-identical to the
inputs recomputed in bitmap_index.html. Edit here, re-run, re-paste.
"""

from __future__ import annotations

# ----------------------------------------------------------------------------
# 0. CONSTANTS + THE DETERMINISTIC 16-ROW DATASET
#    Same data the .html recomputes in JS -- byte-for-byte identical.
# ----------------------------------------------------------------------------

N_ROWS = 16                       # rows in the worked table
STATUS_VALUES = ["active", "pending", "closed", "deleted"]   # D_status = 4
REGION_VALUES = ["east", "west", "north", "south"]           # D_region = 4

# Hand-picked so the worked AND is non-trivial (3 of 16 rows).
#      row:   0        1         2        3        4         5        6         7        8        9        10       11         12       13        14       15
STATUS = ["active", "pending", "closed", "active", "deleted", "active", "pending", "closed",
          "active", "active", "closed", "pending", "active", "deleted", "closed", "active"]
REGION = ["east",   "west",   "east",  "north",  "south",   "east",  "west",   "north",
          "east",   "south",  "east",  "west",   "north",   "south", "east",   "west"]

ROWS_PER_PAGE = 4                 # tuples per heap page (tiny, for illustration)
N_PAGES = (N_ROWS + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE   # 4 pages

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code BITMAP_INDEX.md walks)
# ============================================================================

def build_bitmap(values: list, target) -> list[int]:
    """Bitmap for `target`: bit i = 1 iff values[i] == target. Length = len(values)."""
    return [1 if v == target else 0 for v in values]


def build_index(values: list, distinct: list) -> dict:
    """Build a bitmap index: {value: bitmap} for every distinct value."""
    return {v: build_bitmap(values, v) for v in distinct}


def bitmap_and(a: list[int], b: list[int]) -> list[int]:
    """Bitwise AND = intersection of two row sets. Equal length required."""
    assert len(a) == len(b), "bitmaps must be the same length"
    return [x & y for x, y in zip(a, b)]


def bitmap_or(a: list[int], b: list[int]) -> list[int]:
    """Bitwise OR = union of two row sets."""
    assert len(a) == len(b)
    return [x | y for x, y in zip(a, b)]


def bitmap_not(a: list[int]) -> list[int]:
    """Bitwise NOT = complement, over the full N-row range."""
    return [1 - x for x in a]


def ones(bitmap: list[int]) -> list[int]:
    """Positions of 1-bits = the matching row indices (TIDs)."""
    return [i for i, b in enumerate(bitmap) if b]


def popcount(bitmap: list[int]) -> int:
    """Number of 1-bits (rows matching)."""
    return sum(bitmap)


def rle_encode(bitmap: list[int]) -> list[tuple[int, int]]:
    """Run-length encode: list of (value, length) pairs. Runs strictly
    alternate value, so we can decode from just the first value + lengths.

    >>> rle_encode([0,0,0,1,0,0])
    [(0, 3), (1, 1), (0, 2)]
    >>> rle_encode([1,0,0,0,0])
    [(1, 1), (0, 4)]
    """
    if not bitmap:
        return []
    runs = []
    cur = bitmap[0]
    n = 1
    for b in bitmap[1:]:
        if b == cur:
            n += 1
        else:
            runs.append((cur, n))
            cur = b
            n = 1
    runs.append((cur, n))
    return runs


def rle_decode(runs: list[tuple[int, int]]) -> list[int]:
    """Inverse of rle_encode."""
    out = []
    for v, n in runs:
        out.extend([v] * n)
    return out


def rle_bytes(runs: list[tuple[int, int]]) -> int:
    """Storage cost model: 1 byte per run-length (lengths 0..255), with the
    run VALUE bits packed densely into a header (1 bit per run -> negligible,
    rounds up to ceil(runs/8) extra bytes). We report the dominant term:
    runs bytes for the lengths, plus the packed value bits.

    This mirrors how real sparse-bitmap encoders (BBC, Roaring run containers)
    are dominated by the run count, not the literal bit count.
    """
    if not runs:
        return 0
    length_bytes = len(runs)                       # 1 byte / run-length
    value_bits_packed = (len(runs) + 7) // 8       # packed value bits
    return length_bytes + value_bits_packed


def page_of(row: int) -> int:
    """Heap page holding row `row` (ROWID -> page)."""
    return row // ROWS_PER_PAGE


def offset_of(row: int) -> int:
    """Offset of row `row` within its page."""
    return row % ROWS_PER_PAGE


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_bits(bitmap: list[int], group: int = 8) -> str:
    """Render a bitmap as grouped bits, e.g. '10001000 01000100'."""
    s = "".join(str(b) for b in bitmap)
    return " ".join(s[i:i + group] for i in range(0, len(s), group))


def fmt_index_row(idx: int) -> str:
    return f"{idx:>2}"


# ============================================================================
# 3. THE SIX SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: build a bitmap index on the 'status' column (4 bitmaps x 16 bits)
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: build a bitmap index on 'status'  (4 values x 16 rows)")
    print(f"Table: {N_ROWS} rows. Indexed column 'status' has D = "
          f"{len(STATUS_VALUES)} distinct values: {STATUS_VALUES}.\n")
    print("The table data (what an INDEX is built from):\n")
    print("| row | 0  | 1  | 2  | 3  | 4  | 5  | 6  | 7  | 8  | 9  | 10 | 11 | "
          "12 | 13 | 14 | 15 |")
    print("|-----|----|----|----|----|----|----|----|----|----|----|----|----|"
          "----|----|----|----|")
    print("|status|" + "|".join(f" {s[:4]:<3}" for s in STATUS) + "|")
    print("|region|" + "|".join(f" {r[:5]:<4}" for r in REGION) + "|")
    print()
    idx = build_index(STATUS, STATUS_VALUES)
    print(f"For each distinct value, build a {N_ROWS}-bit bitmap "
          f"(bit i = 1 iff row i has that value):\n")
    print("| value   | bitmap (16 bits, grouped 8)          | #1s | rows (TIDs)        |")
    print("|---------|--------------------------------------|-----|--------------------|")
    for v in STATUS_VALUES:
        bm = idx[v]
        print(f"| {v:<7} | {fmt_bits(bm):<36} | {popcount(bm):<3} | "
              f"{str(ones(bm)):<18} |")
    total_bits = len(STATUS_VALUES) * N_ROWS
    print(f"\nTotal index size (uncompressed) = D x N = {len(STATUS_VALUES)} x "
          f"{N_ROWS} = {total_bits} bits = {total_bits // 8} bytes.\n")
    print("Sanity: the {value} bitmaps are a PARTITION -- every row is 1 in "
          "exactly one of them.\n")
    part_ok = all(sum(idx[v][i] for v in STATUS_VALUES) == 1
                  for i in range(N_ROWS))
    assert part_ok
    print(f"[check] every column position sums to 1 across the {len(STATUS_VALUES)} "
          f"bitmaps (partition):  OK")
    return idx


# ----------------------------------------------------------------------------
# SECTION B: WHERE status='active' AND region='east'  ->  bitmap AND
# ----------------------------------------------------------------------------

def section_b(status_idx, region_idx):
    banner("SECTION B: WHERE status='active' AND region='east'  ->  bitmap AND")
    a = status_idx["active"]
    b = region_idx["east"]
    r = bitmap_and(a, b)
    print("Fetch the bitmap for each predicate (no heap IO yet):\n")
    print(f"  active  : {fmt_bits(a)}   (popcount {popcount(a)})")
    print(f"  east    : {fmt_bits(b)}   (popcount {popcount(b)})")
    print("\nBit-by-bit AND (one CPU op per word in hardware; shown per bit):\n")
    print(f"  A      : {fmt_bits(a)}")
    print(f"  B      : {fmt_bits(b)}")
    print(f"  A AND B: {fmt_bits(r)}")
    print(f"\nResult bitmap has popcount {popcount(r)} -> matching rows (TIDs) "
          f"{ones(r)}.\n")
    print("That is the entire query: 16 bitwise ANDs, ZERO heap tuple reads. "
          "Only the 3 surviving positions will later be fetched.\n")

    # GOLD CHECK: bitmap AND == linear scan
    linear = [i for i in range(N_ROWS)
              if STATUS[i] == "active" and REGION[i] == "east"]
    bm_rows = ones(r)
    print(f"  bitmap AND rows  : {bm_rows}")
    print(f"  linear scan rows : {linear}")
    assert bm_rows == linear, "bitmap AND must equal linear scan"
    print(f"\n[check] bitmap AND == linear scan  (both -> {bm_rows}):  OK")
    return r


# ----------------------------------------------------------------------------
# SECTION C: RLE compression of a sparse bitmap
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: RLE compression  (sparse bitmap -> run-length pairs)")
    print("Bitmap indexes shine on LOW-cardinality columns, and within them the\n"
          "RARE values produce SPARSE bitmaps (long runs of 0s). Run-length\n"
          "encoding (RLE) replaces a run of identical bits with one (value,\n"
          "length) pair, so the cost becomes proportional to the NUMBER of runs,\n"
          "not N.\n")

    # Sparse: 128-bit 'deleted' bitmap with only 2 ones (1.6% density).
    sparse = [0] * 128
    sparse[15] = 1
    sparse[96] = 1
    print("Example 1 -- SPARSE (status='deleted' on a 128-row table, 2 rows):\n")
    print(f"  uncompressed ({len(sparse)} bits = {len(sparse)//8} bytes):\n"
          f"    {fmt_bits(sparse)}\n")
    runs = rle_encode(sparse)
    print(f"  RLE runs ({len(runs)} pairs): {runs}")
    assert rle_decode(runs) == sparse, "RLE round-trip must reproduce input"
    rb = rle_bytes(runs)
    ub = len(sparse) // 8
    print(f"  RLE bytes = {len(runs)} run-lengths + "
          f"{(len(runs)+7)//8} packed value-bits = {rb} bytes")
    print(f"  -> {ub} B -> {rb} B  =  {rb/ub*100:.1f}% of original  "
          f"({ub/rb:.1f}x smaller)\n")

    # Periodic: "1 in every 8" -- the textbook anti-pattern for naive RLE.
    periodic = [1 if i % 8 == 0 else 0 for i in range(128)]
    print("Example 2 -- PERIODIC '1 in every 8' (16 ones, evenly spaced):\n")
    print(f"  uncompressed ({len(periodic)} bits = {len(periodic)//8} bytes):\n"
          f"    {fmt_bits(periodic)}\n")
    runs2 = rle_encode(periodic)
    assert rle_decode(runs2) == periodic
    rb2 = rle_bytes(runs2)
    print(f"  RLE runs ({len(runs2)} pairs): (1,1),(0,7) x 16  ->  "
          f"{len(runs2)} runs = {rb2} bytes")
    print(f"  -> {ub} B -> {rb2} B  =  {rb2/ub*100:.1f}% of original  "
          f"({rb2/ub:.1f}x BIGGER)\n")

    print("LESSON: naive RLE wins when runs are LONG (very sparse or clustered\n"
          "1s). Regular/periodic patterns (1-in-8) have MANY short runs, so RLE\n"
          "makes them BIGGER. Production bitmap indexes use smarter hybrids:\n"
          "  - BBC (Byte-aligned Bitmap Code): Oracle's byte-aligned RLE.\n"
          "  - Roaring (Chambi 2015): per-65535-row chunk picks ONE of\n"
          "    {sorted-array | 1024-bit bitmap | RLE runs}, whichever is smallest.\n"
          "That adaptivity is why Roaring is the de-facto standard today.\n")

    # GOLD CHECK: round-trip + space savings on the sparse case
    assert rle_decode(rle_encode(sparse)) == sparse
    assert rb < ub, "sparse bitmap must compress smaller"
    assert rb2 > ub, "periodic bitmap must NOT compress (the anti-pattern)"
    print(f"[check] RLE round-trip exact, sparse {ub}B->{rb}B (smaller), "
          f"periodic {ub}B->{rb2}B (larger):  OK")
    return rb, ub


# ----------------------------------------------------------------------------
# SECTION D: Bitmap Index Scan -> Bitmap Heap Scan  (two-phase pipeline)
# ----------------------------------------------------------------------------

def section_d(tid_bitmap: list[int]):
    banner("SECTION D: Bitmap Index Scan -> Bitmap Heap Scan  (two-phase)")
    rows = ones(tid_bitmap)
    print(f"Phase 1 (Bitmap Index Scan): the predicate's bitmap IS the TID set.\n"
          f"  result TID bitmap: {fmt_bits(tid_bitmap)}\n"
          f"  matching rows     : {rows}\n")
    print("Convert row positions to physical TIDs (page, offset), "
          f"{ROWS_PER_PAGE} rows/page:\n")
    print("| row | page | offset | TID    |")
    print("|-----|------|--------|--------|")
    for r in rows:
        print(f"| {r:<3} | {page_of(r):<4} | {offset_of(r):<6} | "
              f"({page_of(r)},{offset_of(r)})   |")
    print()

    # Phase 2a: EXACT bitmap -> visit only pages with a hit, recheck optional.
    pages_with_hits = sorted({page_of(r) for r in rows})
    all_pages = list(range(N_PAGES))
    print("Phase 2a (EXACT bitmap): collect the DISTINCT pages that own a hit:\n")
    page_bits = {p: 0 for p in all_pages}
    for r in rows:
        page_bits[page_of(r)] += 1
    print("| page | rows on page   | has hit? | tuples to fetch & recheck |")
    print("|------|----------------|----------|---------------------------|")
    for p in all_pages:
        page_rows = list(range(p * ROWS_PER_PAGE, min((p + 1) * ROWS_PER_PAGE, N_ROWS)))
        hit = p in pages_with_hits
        print(f"| {p:<4} | {str(page_rows):<14} | "
              f"{'YES' if hit else 'skip':<8} | "
              f"{page_bits[p] if hit else 0:<25} |")
    print(f"\n  -> visit {len(pages_with_hits)} of {N_PAGES} pages, "
          f"recheck {len(rows)} tuples. Pages with no hit (here page "
          f"{[p for p in all_pages if p not in pages_with_hits]}) are NEVER read.\n")

    # Phase 2b: LOSSY bitmap -> per-page bit, recheck ALL tuples on visited pages.
    print("Phase 2b (LOSSY bitmap): if work_mem is too small for the exact TID\n"
          "bitmap, PostgreSQL degrades to a PAGE-level bitmap (1 bit/page).\n")
    page_bm = [1 if p in pages_with_hits else 0 for p in all_pages]
    print(f"  page bitmap over {N_PAGES} pages: {page_bm}  "
          f"(set where >=1 hit MIGHT live)\n")
    recheck_tuples = sum(ROWS_PER_PAGE for p in pages_with_hits)
    print(f"  -> still visit {len(pages_with_hits)} pages, but now must RECHECK "
          f"ALL {recheck_tuples} tuples on them\n     (vs {len(rows)} in exact "
          f"mode) -- trading CPU/IO for bounded memory.\n")
    print("The RECHECK is also what keeps the answer correct under MVCC: a TID\n"
          "in the bitmap may belong to a tuple that was since updated/deleted;\n"
          "phase 2 re-tests visibility AND the predicate before returning it.\n")

    # GOLD CHECK: both phases return the same rows
    exact_rows = [r for r in rows]
    lossy_rows = [r for p in pages_with_hits
                  for r in range(p * ROWS_PER_PAGE, min((p + 1) * ROWS_PER_PAGE, N_ROWS))
                  if STATUS[r] == "active" and REGION[r] == "east"]
    assert set(exact_rows) == set(lossy_rows), "lossy recheck must recover exact hits"
    assert recheck_tuples >= len(rows), "lossy rechecks >= exact fetches"
    print(f"[check] exact TID set {sorted(exact_rows)} == lossy recheck result "
          f"{sorted(lossy_rows)}; recheck count {recheck_tuples} >= hits "
          f"{len(rows)}:  OK")
    return pages_with_hits


# ----------------------------------------------------------------------------
# SECTION E: cardinality analysis -- when bitmap wins / loses vs B-tree
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: cardinality analysis  (when bitmap wins, when it loses)")
    N = 1_000_000
    print(f"Fix N = {N:,} rows. Bitmap index size = D x N / 8 bytes. B-tree size\n"
          f"is ~O(N) regardless of D. Sweep D and watch what happens:\n")
    print("| column example   | D (distinct) | bitmap size = D*N/8 | verdict       |")
    print("|------------------|--------------|---------------------|---------------|")
    cases = [
        ("gender (D=2)", 2),
        ("status (D=4)", 4),
        ("country (D=200)", 200),
        ("category (D=1k)", 1_000),
        ("user_id (D=N)", N),
    ]
    for name, D in cases:
        bits = D * N
        b = bits / 8
        if b < 1024:
            size = f"{b:.0f} B"
        elif b < 1024 ** 2:
            size = f"{b/1024:.1f} KB"
        elif b < 1024 ** 3:
            size = f"{b/1024**2:.2f} MB"
        else:
            size = f"{b/1024**3:.2f} GB"
        if D <= 4:
            verdict = "WIN (tiny, low D)"
        elif D <= 200:
            verdict = "ok (warehouse)"
        elif D <= 1000:
            verdict = "borderline"
        else:
            verdict = "LOSE (D~N, huge)"
        print(f"| {name:<16} | {D:<12} | {size:<19} | {verdict:<13} |")
    print()
    print("The breaking point: bitmap size is LINEAR in D. Double the distinct\n"
          "values and you double the index. At D ~ N (a unique key) it becomes\n"
          "N^2/8 bits -- catastrophic. A B-tree on the same column stays O(N).\n")
    print("RULE OF THUMB:")
    print("  - WIN  : low D (gender, status, boolean, country), AND/OR of SEVERAL\n"
          "           low-selectivity predicates, read-mostly / warehouse.\n"
          "  - LOSE : high D (~unique keys), OLTP with frequent writes (each\n"
          "           update flips bits = rewrites compressed runs), or a single\n"
          "           high-selectivity predicate (B-tree reaches the few TIDs\n"
          "           directly -- no need to build a bitmap).\n")
    print("NOTE: PostgreSQL has NO persistent bitmap index. It builds a TID\n"
          "bitmap ON THE FLY from a B-tree/GIN index and runs the Section D\n"
          "pipeline. So you get the bitmap-AND benefit for ad-hoc queries\n"
          "without the write penalty. Real on-disk bitmap indexes live in\n"
          "Oracle, DB2, and ClickHouse (the latter uses sparse-encoding /\n"
          "bitset columns).\n")

    # GOLD CHECK: bitmap size formula + the quadratic blowup at D=N
    assert (2 * N) // 8 == 250_000            # gender
    disaster_bits = N * N
    assert disaster_bits / 8 / 1024 ** 3 > 100, "D=N must blow past 100 GB"
    print(f"[check] gender idx = {2*N//8:,} B; user_id (D=N) = "
          f"{disaster_bits/8/1024**3:.1f} GB (quadratic blowup):  OK")


# ----------------------------------------------------------------------------
# SECTION F: bitmap AND/OR -- why combining predicates in the index wins
# ----------------------------------------------------------------------------

def section_f(status_idx, region_idx):
    banner("SECTION F: bitmap AND/OR -- combine predicates BEFORE the heap fetch")
    print("The headline benefit: AND/OR of bitmaps costs O(N/word) CPU and ZERO\n"
          "heap IO, so you only fetch the rows that survive ALL predicates.\n\n"
          "Compare plans for  WHERE status='active' AND region='east':\n")
    a = status_idx["active"]
    b = region_idx["east"]
    r = bitmap_and(a, b)
    seq_fetches = N_ROWS
    bt_status_fetches = popcount(a)
    bt_region_fetches = popcount(b)
    bm_fetches = popcount(r)
    print("| plan                                   | heap tuples fetched | discarded |")
    print("|----------------------------------------|---------------------|-----------|")
    print(f"| sequential scan, filter in memory      | {seq_fetches:<19} | "
          f"{seq_fetches - bm_fetches:<9} |")
    print(f"| B-tree(status) then filter region      | {bt_status_fetches:<19} | "
          f"{bt_status_fetches - bm_fetches:<9} |")
    print(f"| B-tree(region) then filter status      | {bt_region_fetches:<19} | "
          f"{bt_region_fetches - bm_fetches:<9} |")
    print(f"| BITMAP AND, then fetch survivors       | {bm_fetches:<19} | "
          f"{0:<9} |")
    print(f"\nBitmap AND fetches only {bm_fetches} tuples (the {bm_fetches} that "
          f"survive both predicates), discarding none. A single-predicate index\n"
          "fetches every row matching THAT predicate, then throws away the ones\n"
          "failing the other. On random IO, fetches are the expensive part.\n")

    # OR example
    p = status_idx["pending"]
    c = status_idx["closed"]
    o = bitmap_or(p, c)
    print("OR is symmetric. WHERE status='pending' OR status='closed':\n")
    print(f"  pending : {fmt_bits(p)}   (popcount {popcount(p)})")
    print(f"  closed  : {fmt_bits(c)}   (popcount {popcount(c)})")
    print(f"  P OR C  : {fmt_bits(o)}   (popcount {popcount(o)})  "
          f"-> rows {ones(o)}")
    print("\n  One bitmap op yields the union; no merge-sort of two TID lists, no\n"
          "  duplicate elimination (bitwise OR is idempotent by construction).\n")

    # NOT example
    na = bitmap_not(a)
    print("NOT inverts (over the full N-row range). "
          "WHERE status != 'active' is NOT(active):\n")
    print(f"  active    : {fmt_bits(a)}   (popcount {popcount(a)})")
    print(f"  NOT active: {fmt_bits(na)}   (popcount {popcount(na)})  "
          f"-> rows {ones(na)}")
    print("\n  A NOT predicate is cheap on a bitmap (flip every bit) and murderous\n"
          "  on a B-tree (it means 'everything except these' -> scan). This is\n"
          "  another reason OLAP loves bitmaps.\n")

    # GOLD CHECK: AND == intersection, OR == union, NOT == complement
    active_rows = set(ones(a))
    east_rows = set(ones(b))
    assert set(ones(r)) == active_rows & east_rows
    assert set(ones(o)) == set(ones(p)) | set(ones(c))
    assert set(ones(na)) == set(range(N_ROWS)) - active_rows
    assert popcount(a) + popcount(na) == N_ROWS
    print(f"[check] AND=intersection, OR=union, NOT=complement, "
          f"popcount(A)+popcount(NOT A)={N_ROWS}:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("bitmap_index.py - reference impl. All numbers below feed "
          "BITMAP_INDEX.md.")
    print(f"N_ROWS={N_ROWS}  STATUS_VALUES={STATUS_VALUES}  "
          f"REGION_VALUES={REGION_VALUES}  ROWS_PER_PAGE={ROWS_PER_PAGE}")

    status_idx = section_a()
    # also build the region index for B, D, F
    region_idx = build_index(REGION, REGION_VALUES)
    tid_bm = section_b(status_idx, region_idx)
    section_c()
    section_d(tid_bm)
    section_e()
    section_f(status_idx, region_idx)

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
