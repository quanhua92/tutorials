"""
slotted_page.py - Reference implementation of the slotted-page storage layout
used by PostgreSQL (and virtually every row-store RDBMS) to pack tuples inside a
fixed-size 8 KB page.

This is the single source of truth that SLOTTED_PAGE.md is built from. Every
number, table, and byte-offset map in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 slotted_page.py

==========================================================================
THE INTUITION (read this first) - the shelf that fills from BOTH ends
==========================================================================
A database table is not one big file you append to. It is split into thousands of
FIXED-SIZE blocks called PAGES (PostgreSQL's default page = 8192 bytes = 8 KB).
Each page is a tiny self-contained shelf that manages its own free space.

The problem: tuples have DIFFERENT sizes, they get INSERTED, DELETED, and UPDATED
all the time, and we must find any row by its position (an "item number") in O(1)
without scanning. The solution is the SLOTTED PAGE:

  * A PAGE HEADER sits at the start (24 bytes of bookkeeping: pd_lower/pd_upper
    free-space cursors, the page LSN, a checksum, ...).
  * An array of LINE POINTERS ("item identifiers", 4 bytes each) grows FORWARD
    from the end of the header. Line pointer #N is a small (offset, length, flags)
    triple that says "tuple #N lives at byte offset X, size Y".
  * The actual TUPLE DATA grows BACKWARD from the END of the page.
  * The shrinking gap between them is the FREE SPACE.

  low addresses -------------------------------------------> high addresses
  +---------+------+------+------+------------------+------+------+------+
  | HEADER  | LP#1 | LP#2 | LP#3 |      FREE        | Tup3 | Tup2 | Tup1 |
  +---------+------+------+------+------------------+------+------+------+
  0        24                                    pd_upper         PAGE_SIZE
              pd_lower -->                       <-- pd_upper
              (grows ->)                         (<- grows)

Insert a row: add a line pointer on the LEFT, drop the tuple on the RIGHT, the
FREE gap in the middle shrinks from both sides. They meet -> page full. Find a
row: jump to line pointer #N, read its (offset, length), fetch the bytes. The
tuples can MOVE (e.g. after an UPDATE) because the line pointer is the STABLE
address - you just update where it points.

THE LINEAGE:
  Flat file  ->  Slotted page
  A flat file has no structure: append rows, then scan to find one. A slotted
  page adds the line-pointer array so any row is addressable in O(1) by item
  number, and the page manages its own free space (inserts carve from both ends;
  deletes punch holes that VACUUM later compacts). This is THE fundamental
  storage unit in PostgreSQL, MySQL/InnoDB, DB2, Oracle, Informix, ...

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  page (block)   : a fixed-size chunk of disk, the unit of I/O. PostgreSQL = 8192 B.
  page header    : the 24-byte PageHeaderData at the start of every page: holds
                   pd_lower, pd_upper (the free-space cursors), the page LSN,
                   a checksum, flags, and pd_prune_xid.
  line pointer   : a 4-byte (offset, length, flags) triple = "ItemIdData". Numbered
                   1..N (PostgreSQL's OffsetNumber is 1-based). This is the STABLE
                   address of a row: indexes point at a (page, item-number) pair.
  tuple          : a stored row = a small tuple header + the column values. Lives at
                   the FAR end of the page and grows backward.
  free space     : the contiguous gap [pd_lower, pd_upper). New tuples are carved
                   out of pd_upper (pushing it down); new line pointers out of
                   pd_lower (pushing it up).
  pd_lower       : offset = end of the line-pointer array = START of free space.
  pd_upper       : offset = start of the tuple area      = END of free space.
  lp_flags states: 0=UNUSED (slot free), 1=NORMAL (live row), 2=REDIRECT (HOT),
                   3=DEAD (row gone; bytes are a hole until VACUUM compacts).
  HOT update     : Heap-Only Tuples. An UPDATE that keeps the new row on the SAME
                   page and doesn't change any indexed column needs NO index update:
                   the old line pointer becomes a REDIRECT to the new version.

==========================================================================
THE LINEAGE (sources)
==========================================================================
  Slotted pages : described in Database System Concepts (Silberschatz/Korth/
                  Sudarshan), "Storage and File Structure" chapter; and Database
                  System Implementation (Garcia-Molina/Ullman/Widom). The standard
                  row-store layout.
  PostgreSQL    : src/include/storage/bufpage.h (PageHeaderData, ItemIdData);
                  src/include/access/htup_details.h (HeapTupleHeaderData).
  HOT           : PostgreSQL 8.2+ (Heikki Linnakangas). The lp_flags REDIRECT
                  mechanism keeps an UPDATE off the indexes when the new tuple
                  fits on the same page.

KEY FACTS (all asserted in code below):
  default page size     BLCKSZ                  = 8192 bytes
  page header size      sizeof(PageHeaderData)  = 24 bytes
  line pointer size     sizeof(ItemIdData)      = 4 bytes  (15+2+15 bit fields)
  lp_flags              2 bits -> 4 states: UNUSED / NORMAL / REDIRECT / DEAD
  tuple header (real)   sizeof(HeapTupleHeaderData) = 23 bytes (-> 24 aligned)
  heap special area     0 bytes (pd_special == page_size for heap tables;
                         index pages - B-tree, GiST - use the page TAIL instead)

KEY FORMULAS (derived + asserted in section E):
  usable space      = page_size - header_size
  free space now    = pd_upper - pd_lower
  max tuples (size) = floor( (page_size - header_size) / (ip_size + tuple_size) )
  INVARIANT         page_size == header + line_pointers + live_tuples + holes + free
                    (verified after EVERY operation below -> the gold check)
"""

from __future__ import annotations

BANNER = "=" * 72

# ---------------------------------------------------------------------------
# Real PostgreSQL constants (used in section E for the 8 KB page math)
# ---------------------------------------------------------------------------
REAL_PAGE = 8192          # BLCKSZ
REAL_HEADER = 24          # sizeof(PageHeaderData) -- verified 8+2+2+2+2+2+2+4
REAL_IP = 4               # sizeof(ItemIdData)     -- lp_off:15, lp_flags:2, lp_len:15
REAL_TUPHDR = 24          # sizeof(HeapTupleHeaderData) aligned to MAXALIGN(8)

# ---------------------------------------------------------------------------
# TINY dims for the printable simulation (sections A-D). A 128-byte page so
# every byte offset fits on screen; the structure is byte-identical to 8 KB.
# ---------------------------------------------------------------------------
SIM_PAGE = 128
SIM_HEADER = 24           # same as real: PageHeaderData
SIM_IP = 4                # same as real: ItemIdData
SIM_TUPHDR = 4            # toy tuple header (real is ~24); shrunk so several
                          # rows fit a 128-byte page and stay printable

# line-pointer flag states (PostgreSQL bufpage.h: LP_UNUSED..LP_DEAD)
LP_UNUSED, LP_NORMAL, LP_REDIRECT, LP_DEAD = 0, 1, 2, 3
LP_NAMES = {0: "UNUSED", 1: "NORMAL", 2: "REDIRECT", 3: "DEAD"}


class PageFull(Exception):
    """Raised when an insert/update cannot find contiguous free space."""


class LinePointer:
    """A 4-byte item identifier: (offset, length, flags). Item numbers are 1-based."""

    __slots__ = ("off", "size", "flags", "redirect", "name")

    def __init__(self, off: int, size: int, name: str = ""):
        self.off = off            # byte offset of the tuple (lp_off)
        self.size = size          # byte length of the tuple (lp_len)
        self.flags = LP_NORMAL    # lp_flags
        self.redirect = None      # target item number (1-based) when REDIRECT
        self.name = name          # payload label, for readable maps only


class SlottedPage:
    """A simulated fixed-size page. Mirrors PostgreSQL's layout exactly, just tiny.

    Region layout:
        [0           , header_size)            PageHeaderData
        [header_size , pd_lower)               line-pointer array (grows ->)
        [pd_lower    , pd_upper)               FREE SPACE (contiguous gap)
        [pd_upper    , page_size)              tuple data (grows <-)
    For heap pages there is NO special area at the tail (pd_special == page_size).
    """

    def __init__(self, page_size=SIM_PAGE, header_size=SIM_HEADER,
                 ip_size=SIM_IP, tup_hdr=SIM_TUPHDR):
        self.P = page_size
        self.H = header_size
        self.I = ip_size
        self.th = tup_hdr
        self.lps: list[LinePointer] = []
        self.pd_lower = header_size          # = end of line-pointer array
        self.pd_upper = page_size            # = start of tuple area
        self.holes: list[tuple[int, int]] = []   # (off, size) of REDIRECT dead bytes

    # -- queries ----------------------------------------------------------
    def free(self) -> int:
        """Contiguous free space = pd_upper - pd_lower."""
        return self.pd_upper - self.pd_lower

    def item(self, i1: int) -> LinePointer:
        """1-based item number -> LinePointer (PostgreSQL OffsetNumber is 1-based)."""
        return self.lps[i1 - 1]

    def num_items(self) -> int:
        return len(self.lps)

    def tuple_size(self, payload: str) -> int:
        return self.th + len(payload.encode())

    # -- mutations --------------------------------------------------------
    def insert(self, payload: str, name: str | None = None) -> int:
        """Append a tuple: carve it out of pd_upper, add a line pointer at pd_lower.
        Reuses an UNUSED line-pointer slot if one exists (keeps the array tight).
        Returns the 1-based item number of the new row."""
        if name is None:
            name = payload
        tup = self.tuple_size(payload)
        need = self.I + tup
        if self.free() < need:
            raise PageFull(f"need {need} B (ptr {self.I} + tuple {tup}), "
                           f"have {self.free()} B")
        # carve the tuple out of the TOP of the free gap
        off = self.pd_upper - tup
        self.pd_upper -= tup
        # reuse a freed slot if possible, else grow the array (push pd_lower up)
        slot = next((i for i, lp in enumerate(self.lps)
                     if lp.flags == LP_UNUSED), None)
        if slot is None:
            self.lps.append(LinePointer(off, tup, name))
            self.pd_lower += self.I
            return len(self.lps)
        self.lps[slot] = LinePointer(off, tup, name)
        return slot + 1

    def delete(self, i1: int) -> None:
        """Mark item #i1 DEAD. Its bytes become a hole (reclaimed later by compact).
        NOTE: the contiguous free gap does NOT grow unless the dead tuple was
        adjacent to it - holes need a VACUUM-style compaction to be reclaimed."""
        lp = self.item(i1)
        assert lp.flags == LP_NORMAL, "can only delete a NORMAL tuple"
        lp.flags = LP_DEAD

    def compact(self) -> None:
        """VACUUM's PageRepairFragmentation (simplified): slide all LIVE tuples to
        the top of the page so holes vanish, then convert DEAD line pointers to
        UNUSED (reclaimable) and drop trailing UNUSED slots so pd_lower can shrink."""
        live = [lp for lp in self.lps if lp.flags == LP_NORMAL]
        self.pd_upper = self.P
        for lp in live:                 # repack live tuples against the page end
            self.pd_upper -= lp.size
            lp.off = self.pd_upper
        for lp in self.lps:             # dead tuples -> unused slots
            if lp.flags == LP_DEAD:
                lp.flags = LP_UNUSED
                lp.off = lp.size = 0
        self.holes.clear()              # redirect-origin holes also reclaimed
        while self.lps and self.lps[-1].flags == LP_UNUSED:
            self.lps.pop()
            self.pd_lower -= self.I

    def update(self, i1: int, new_payload: str, new_name: str | None = None):
        """HOT (Heap-Only Tuples) UPDATE: append the new version on the SAME page
        and turn the old line pointer into a REDIRECT to it. No index touched.
        Returns (new_item_number, (old_hole_off, old_hole_size)). Raises PageFull
        if the new version does not fit -> a non-HOT update would spill to another
        page AND require index updates."""
        if new_name is None:
            new_name = new_payload
        old = self.item(i1)
        assert old.flags == LP_NORMAL, "can only HOT-update a NORMAL tuple"
        new_tup = self.tuple_size(new_payload)
        if self.free() < self.I + new_tup:
            raise PageFull("update would spill the page (NOT a HOT update)")
        off = self.pd_upper - new_tup
        self.pd_upper -= new_tup
        self.lps.append(LinePointer(off, new_tup, new_name))
        self.pd_lower += self.I
        new_item = len(self.lps)
        # the OLD tuple bytes become a dead hole; the OLD line pointer redirects
        self.holes.append((old.off, old.size))
        old.flags = LP_REDIRECT
        old.redirect = new_item
        old.off = old.size = 0           # REDIRECT reuses these fields for the target
        return new_item, self.holes[-1]

    # -- layout accounting ------------------------------------------------
    def regions(self) -> list[dict]:
        """All byte regions on the page, sorted by offset. Used for the byte-offset
        map, the ASCII bar, and the partition invariant (gold check)."""
        rs = []
        rs.append({"start": 0, "end": self.H, "kind": "header", "name": "PageHeaderData"})
        for i, lp in enumerate(self.lps):
            rs.append({"start": self.H + i * self.I,
                       "end": self.H + (i + 1) * self.I,
                       "kind": "lp", "item": i + 1, "lp": lp})
        if self.pd_lower < self.pd_upper:
            rs.append({"start": self.pd_lower, "end": self.pd_upper,
                       "kind": "free"})
        for i, lp in enumerate(self.lps):
            if lp.flags == LP_NORMAL:
                rs.append({"start": lp.off, "end": lp.off + lp.size,
                           "kind": "tuple", "item": i + 1, "lp": lp})
            elif lp.flags == LP_DEAD:
                rs.append({"start": lp.off, "end": lp.off + lp.size,
                           "kind": "hole", "item": i + 1, "lp": lp,
                           "note": "dead tuple (hole)"})
        for (ho, hs) in self.holes:
            rs.append({"start": ho, "end": ho + hs,
                       "kind": "hole", "note": "redirect dead bytes"})
        rs.sort(key=lambda r: r["start"])
        return rs

    def partition_totals(self) -> dict:
        """Category byte totals; their sum MUST equal page_size (the invariant)."""
        t = {"header": self.H,
             "pointers": len(self.lps) * self.I,
             "tuples": sum(lp.size for lp in self.lps if lp.flags == LP_NORMAL),
             "holes": (sum(lp.size for lp in self.lps if lp.flags == LP_DEAD)
                       + sum(s for _, s in self.holes)),
             "free": self.free()}
        t["total"] = sum(t.values())
        return t


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def foff(a: int, b: int) -> str:
    """Format a [start, end) byte range, right-aligned in 4 chars."""
    return f"[{a:>4}..{b:>4})"


def byte_map(page: SlottedPage, title: str = "byte-offset map"):
    """Print a precise byte-offset map of the page."""
    print(f"\n{title}  (page_size={page.P}, pd_lower={page.pd_lower}, "
          f"pd_upper={page.pd_upper}, free={page.free()}):")
    for r in page.regions():
        k = r["kind"]
        if k == "header":
            print(f"  {foff(r['start'], r['end'])}  HEADER   PageHeaderData "
                  f"({r['end'] - r['start']} B): pd_lower, pd_upper, LSN, ...")
        elif k == "lp":
            lp = r["lp"]
            st = LP_NAMES[lp.flags]
            extra = ""
            if lp.flags == LP_NORMAL:
                extra = f'-> tuple{foff(lp.off, lp.off + lp.size)} "{lp.name}" ({lp.size} B)'
            elif lp.flags == LP_REDIRECT:
                extra = f"-> REDIRECT to item #{lp.redirect}"
            elif lp.flags == LP_DEAD:
                extra = f"-> hole {foff(lp.off, lp.off + lp.size)} (dead, {lp.size} B)"
            else:
                extra = "-> (reclaimable slot)"
            print(f"  {foff(r['start'], r['end'])}  LP[{r['item']:<2}]   {st:<8} {extra}")
        elif k == "free":
            print(f"  {foff(r['start'], r['end'])}  FREE     contiguous gap "
                  f"({r['end'] - r['start']} B)   <- pd_lower .. pd_upper")
        elif k == "tuple":
            lp = r["lp"]
            print(f"  {foff(r['start'], r['end'])}  TUPLE    item #{r['item']} "
                  f'"{lp.name}" ({lp.size} B)  [hdr {page.th} + payload '
                  f"{lp.size - page.th}]")
        elif k == "hole":
            note = r.get("note", "")
            print(f"  {foff(r['start'], r['end'])}  HOLE     dead bytes "
                  f"({r['end'] - r['start']} B)  {note}")


def ascii_bar(page: SlottedPage, width: int = 60) -> str:
    """A fixed-width ASCII bar: H=header, i=line pointer, .=free, T=tuple, x=hole."""
    glyph = {"header": "H", "lp": "i", "free": ".", "tuple": "T", "hole": "x"}
    regs = page.regions()
    out = []
    for c in range(width):
        mid = (c + 0.5) * page.P / width
        cell = next((r for r in regs if r["start"] <= mid < r["end"]), None)
        out.append(glyph[(cell or {"kind": "free"})["kind"]])
    return "".join(out)


def check_invariant(page: SlottedPage, label: str):
    """The gold check: header + pointers + tuples + holes + free == page_size."""
    t = page.partition_totals()
    ok = t["total"] == page.P
    # also verify the region list tiles [0, P) with no gaps/overlaps
    regs = page.regions()
    tiled = (regs[0]["start"] == 0 and regs[-1]["end"] == page.P
             and all(regs[j]["start"] == regs[j - 1]["end"]
                     for j in range(1, len(regs))))
    ok = ok and tiled
    status = "OK" if ok else "FAIL"
    print(f"  [check] {label}: "
          f"hdr({t['header']}) + ptr({t['pointers']}) + tup({t['tuples']}) "
          f"+ hole({t['holes']}) + free({t['free']}) = {t['total']} "
          f"== page_size({page.P})  ->  {status}")
    assert ok, f"INVARIANT BROKEN: {label}"
    return t


# ============================================================================
# 3. THE CANONICAL 5-TUPLE PAGE (the gold scenario both .py and .html run)
# ============================================================================

CANON_PAYLOADS = ["Alice", "Bob", "Carol", "Dave", "Eve"]


def build_canonical():
    """The 5-tuple page every section starts from. Deterministic inputs."""
    pg = SlottedPage()
    for name in CANON_PAYLOADS:
        pg.insert(name)
    return pg


# ----------------------------------------------------------------------------
# SECTION A: the page layout (byte-offset map of the canonical page)
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the slotted-page layout  (header + line pointers + free + tuples)")
    pg = build_canonical()
    print("A real PostgreSQL page is 8192 B; we use a 128-B page with the IDENTICAL")
    print("structure so every byte offset is printable. Header=24 B (same as real),")
    print("line pointer=4 B (same as real), toy tuple header=4 B (real ~= 24).\n")
    byte_map(pg, "Canonical 5-tuple page")
    print()
    print("Read it bottom-to-top on the tuple side: tuples fill from the END of the")
    print("page backward (Eve is last in -> closest to the free gap), while line")
    print("pointers fill from the header forward. The free gap is the meat in the")
    print("sandwich: pd_lower chases pd_upper until they meet -> page full.")
    check_invariant(pg, "canonical page tiles [0, page_size)")


# ----------------------------------------------------------------------------
# SECTION B: insert 5 tuples one at a time (the two-sided growth)
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: insert 5 tuples one at a time  (line pointers grow ->, tuples grow <-)")
    pg = SlottedPage()
    print("Watch the two cursors close in on each other after every insert:")
    print("  pd_lower climbs (new line pointer +4 B on the LEFT),")
    print("  pd_upper drops  (new tuple carved on the RIGHT).\n")
    print(f"  legend:  H=header  i=line pointer  .=free  T=tuple\n")
    for k, name in enumerate(CANON_PAYLOADS, 1):
        item = pg.insert(name)
        t = pg.tuple_size(name)
        print(f"  insert #{k} \"{name}\" (payload {len(name)} -> tuple {t} B):  "
              f"item #{item}, lower={pg.pd_lower}, upper={pg.pd_upper}, "
              f"free={pg.free()}")
        print(f"    {ascii_bar(pg)}")
    print("\nFinal state:")
    byte_map(pg, "After 5 inserts")
    print(f"\nThe two fronts met in the middle leaving a {pg.free()}-B free gap. "
          f"More inserts would keep shrinking it until pd_lower >= pd_upper")
    print("(no room for a pointer + a tuple) -> the page is full and a new page is")
    print("allocated. This two-ended scheme is why slotted pages pack rows densely")
    print("AND stay O(1) addressable by item number.")
    check_invariant(pg, "after 5 inserts")


# ----------------------------------------------------------------------------
# SECTION C: delete item #3, then compact (VACUUM) to reclaim the hole
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: delete item #3 (Carol)  ->  hole, then VACUUM reclaims it")
    pg = build_canonical()
    print("STEP 1 - delete item #3 (\"Carol\"). Its line pointer flips NORMAL -> DEAD;")
    print("the tuple bytes become a HOLE. Crucially, the CONTIGUOUS free gap does NOT")
    print("grow, because Carol sat in the MIDDLE of the tuple area - it is not next to")
    print("the free gap. Reclaiming it needs a compaction (what VACUUM does).\n")
    before_free = pg.free()
    pg.delete(3)
    byte_map(pg, "After delete item #3")
    t = check_invariant(pg, "after delete")
    print(f"\n  contiguous free gap: {before_free} -> {pg.free()} B  (UNCHANGED)")
    print(f"  dead holes now:      {t['holes']} B  (Carol's tuple, reclaimable)")
    print(f"  total reclaimable:   {pg.free()} (gap) + {t['holes']} (holes) "
          f"= {pg.free() + t['holes']} B\n")

    print("STEP 2 - VACUUM compaction (PageRepairFragmentation): slide LIVE tuples to")
    print("the top so the hole vanishes, turning DEAD line pointers UNUSED. The hole")
    print("bytes flow back into the single contiguous free gap.\n")
    pg.compact()
    byte_map(pg, "After VACUUM compact")
    t = check_invariant(pg, "after compact")
    print(f"\n  contiguous free gap: {before_free} -> {pg.free()} B  (GREW by the hole)")
    print(f"  dead holes now:      {t['holes']} B")
    print("  Note item #3's slot is now UNUSED but still occupies 4 B (only TRAILING")
    print("  unused slots are dropped), so pd_lower did not shrink. A future insert")
    print("  reuses that slot without growing the pointer array.")


# ----------------------------------------------------------------------------
# SECTION D: HOT update (old line pointer -> REDIRECT, new version appended)
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: HOT update  (update \"Bob\"->\"Bobby\"; old LP -> REDIRECT, no index touch)")
    pg = SlottedPage()
    for name in ["Alice", "Bob", "Carol"]:
        pg.insert(name)
    print("Start from a 3-tuple page. An UPDATE that (a) keeps the new row on the SAME")
    print("page and (b) changes no indexed column is a HOT (Heap-Only Tuples) update:")
    print("the new version is just appended and the OLD line pointer REDIRECTS to it,")
    print("so PostgreSQL never touches the indexes.\n")
    byte_map(pg, "Before update (3 tuples)")
    check_invariant(pg, "before update")

    print("\nUPDATE item #2 \"Bob\"(7 B) -> \"Bobby\"(9 B): does NOT fit in the old slot,")
    print("so the new version is appended at the end of the tuple area and item #2")
    print("becomes a REDIRECT pointer to the new item.\n")
    new_item, hole = pg.update(2, "Bobby")
    byte_map(pg, "After HOT update")
    t = check_invariant(pg, "after update")
    print(f"\n  HOT redirect chain:  item #2  --REDIRECT-->  item #{new_item} (\"Bobby\")")
    print(f"  indexes still point at item #2; they are NEVER updated. A sequential")
    print(f"  scan follows the redirect to the latest version for free.")
    print(f"  old \"Bob\" bytes {foff(hole[0], hole[0] + hole[1])} are now a dead hole "
          f"({hole[1]} B) - reclaimed by the next VACUUM (section C).")
    print(f"  free gap: {67} -> {pg.free()} B  (new tuple + its pointer cost "
          f"{pg.I + 9} B; the hole is reclaimed later).")
    print("\nIf the new version did NOT fit on the page, this would NOT be HOT: the row")
    print("would move to another page and EVERY index on the table would need a new")
    print("(page, item) entry. HOT exists to dodge exactly that cost.")


# ----------------------------------------------------------------------------
# SECTION E: max tuples per page (the capacity formula)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: max tuples per page  =  floor( (page_size - header) / (ip + tuple) )")
    print("For uniformly-sized rows, each row costs one 4-B line pointer PLUS its tuple,")
    print("so the page holds at most:\n")
    print("    max_tuples = floor( (page_size - header_size) / (ip_size + tuple_size) )\n")
    print("This is an UPPER bound: real capacity is a bit lower because of MAXALIGN")
    print("padding on tuple headers and free-space fragmentation from deletes.\n")

    def max_tuples(P, H, I, T):
        return (P - H) // (I + T)

    print("--- tiny 128-B simulation page (header=24, ip=4, toy tuple-hdr=4) ---")
    print("| payload | tuple = hdr+payload | ip+tuple | max tuples | free left |")
    print("|---------|---------------------|----------|------------|-----------|")
    for pay in [3, 5, 12, 20]:
        T = SIM_TUPHDR + pay
        n = max_tuples(SIM_PAGE, SIM_HEADER, SIM_IP, T)
        used = SIM_HEADER + n * (SIM_IP + T)
        print(f"| {pay:>7} | {T:>19} | {SIM_IP + T:>8} | {n:>10} | "
              f"{SIM_PAGE - used:>9} |")

    print("\n--- real PostgreSQL 8 KB page (header=24, ip=4, tuple-hdr=24) ---")
    print("| payload (B) | tuple = 24+payload | ip+tuple | max tuples | rows/MB*1000 |")
    print("|-------------|--------------------|----------|------------|--------------|")
    for pay in [0, 8, 40, 100, 232, 1000]:
        T = REAL_TUPHDR + pay
        n = max_tuples(REAL_PAGE, REAL_HEADER, REAL_IP, T)
        rows_per_mb = n * (REAL_PAGE // 8192) / 8 * 1000  # pages per MB(8192B) * rows
        # pages per 1 MiB = 2**20/8192 = 128 ; rows/MB = 128*n
        rows_per_mb = 128 * n
        print(f"| {pay:>11} | {T:>18} | {REAL_IP + T:>8} | {n:>10} | "
              f"{rows_per_mb:>12} |")

    print("\nSanity checks (asserted):")
    assert max_tuples(SIM_PAGE, SIM_HEADER, SIM_IP, 9) == 8
    assert max_tuples(REAL_PAGE, REAL_HEADER, REAL_IP, 32) == 226
    assert max_tuples(REAL_PAGE, REAL_HEADER, REAL_IP, 256) == 31
    print("  [check] tiny page, tuple=9 B: 8 tuples  (fills the 128-B page exactly)  OK")
    print("  [check] 8 KB page, tuple=32 B: 226 tuples                                     OK")
    print("  [check] 8 KB page, tuple=256 B: 31 tuples                                     OK")
    print("\nBig picture: small rows pack hundreds per 8 KB page; a 1 KB row fits only ~7.")
    print("Row width directly sets table size and scan cost - this is why DBAs watch")
    print("tuple width and why PostgreSQL stores TOAST pointers for wide values.")


# ============================================================================
# 4. THE GOLD BLOCK (what slotted_page.html recomputes and checks against)
# ============================================================================

def gold_block():
    banner("GOLD - the canonical 5-tuple page (slotted_page.html recomputes this)")
    pg = build_canonical()
    t = pg.partition_totals()
    print(f"dims:        page_size={SIM_PAGE}  header={SIM_HEADER}  ip={SIM_IP}  "
          f"tuple_hdr={SIM_TUPHDR}")
    print(f"payloads:    {CANON_PAYLOADS}")
    print(f"tuple sizes: {[pg.tuple_size(n) for n in CANON_PAYLOADS]}")
    print(f"pd_lower:    {pg.pd_lower}")
    print(f"pd_upper:    {pg.pd_upper}")
    print(f"free_space:  {pg.free()}")
    print(f"partition:   header={t['header']} + pointers={t['pointers']} "
          f"+ tuples={t['tuples']} + holes={t['holes']} + free={t['free']} "
          f"= {t['total']}")
    assert t["total"] == SIM_PAGE
    assert pg.free() == 44
    assert pg.pd_lower == 44 and pg.pd_upper == 88
    print(f"[check] gold invariant total == page_size ({SIM_PAGE}):      OK")
    print(f"[check] gold free_space == 44  (the .html gold scalar):      OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("slotted_page.py - reference impl. All numbers below feed SLOTTED_PAGE.md.")
    print("Real PostgreSQL page = 8192 B; printable sim page = 128 B (same structure).")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_block()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
