"""
tuple_format.py - Reference implementation of how PostgreSQL serializes ONE
row (a "heap tuple") to bytes on disk.

This is the single source of truth that TUPLE_FORMAT.md is built from. Every
number, table, and byte in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 tuple_format.py

==========================================================================
THE INTUITION (read this first) - the airport luggage tag
==========================================================================
A row on disk is like a suitcase at baggage claim. The suitcase carries your
stuff (the column values), but GLUED TO ITS HANDLE is a tag the airline needs
to route it: who checked it in, who may reclaim it, where the next copy lives.
In PostgreSQL that tag is the **HeapTupleHeaderData** - 23 bytes of bookkeeping
GLUED to the front of every row, before the column data starts.

  * t_xmin  : the transaction id that INSERTED this row           (4 bytes)
  * t_xmax  : the transaction id that DELETED/locked this row     (4 bytes)
              (0, or the HEAP_XMAX_INVALID flag, means "still alive")
  * t_cid   : the command id inside the inserting transaction     (4 bytes)
  * t_ctid  : a pointer (block#, offset) to THIS row, or to a
              NEWER version of it if this row was UPDATEd         (6 bytes)
  * t_infomask2 : low bits = number of columns; high bits = flags (2 bytes)
  * t_infomask  : flags: HASNULL, HASVARWIDTH, XMAX_INVALID, ...  (2 bytes)
  * t_hoff  : offset where column DATA begins (after header+bitmap) (1 byte)

That is 4+4+4+6+2+2+1 = 23 bytes. Then comes an OPTIONAL null bitmap, then
padding up to MAXALIGN (8 bytes on 64-bit), then the column bytes themselves.

The whole point of this file: a row is NOT "the columns concatenated". It is
  header | [null bitmap] | [padding] | col1 [pad] col2 [pad] ...
and the pad bytes are real, paid-for-bytes that hold NOTHING. Column ORDER
changes how many pad bytes you pay. That is why DBAs say "put the bigints and
timestamps first, the bools and chars last."

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  heap tuple      : one row, as bytes on disk. Lives inside an 8 KiB "heap page".
  HeapTupleHeaderData : the 23-byte tag glued to the front of every heap tuple.
  t_hoff          : "header offset" = byte where column DATA begins.
  null bitmap     : 1 bit per column; 1 = present, 0 = NULL. Omitted entirely
                    if the row has no NULLs (HEAP_HASNULL flag clear).
  MAXALIGN        : the machine's big alignment (8 bytes on 64-bit). The header
                    (plus bitmap) is padded up to a MAXALIGN boundary -> t_hoff.
  typalign        : per-type alignment: 'c'=1, 's'=2, 'i'=4, 'd'=8.
                    A column is placed at the next offset that is a multiple of
                    its typalign, inserting PADDING bytes before it.
  typlen          : per-type fixed length. >0 = fixed; -1 = varlena (text).
  varlena         : a VARIABLE-LENGTH value (text/varchar/bytea). Carries its
                    OWN length in a 1-byte or 4-byte header.
  1B header       : short varlena (total <= 127 B). Header = (len<<1)|1.
                    Needs NO alignment - the trick that saves space.
  4B header       : long varlena. Header = (len<<2) (LE) in 4 bytes.
                    Aligns to 4 bytes ('i').
  TOAST pointer   : when a value is too big (>~2 KiB) it is moved OUT of the
                    tuple ("TOASTed") and replaced by an 18-byte pointer:
                    1 B marker (0x01) + 1 B tag + 16 B (va_rawsize,
                    va_extinfo, va_valueid, va_tableoid).

==========================================================================
THE HEADER STRUCT (from PostgreSQL src/include/access/htup_details.h)
==========================================================================
    struct HeapTupleHeaderData {            // offset  size
        TransactionId  t_xmin;             //   0       4
        TransactionId  t_xmax;             //   4       4
        union { CommandId t_cid;           //   8       4
                TransactionId t_xvac; }
        ItemPointerData t_ctid;            //  12       6   (4 B block + 2 B off)
        uint16         t_infomask2;        //  18       2
        uint16         t_infomask;         //  20       2
        uint8          t_hoff;             //  22       1
        /* ----- 23 bytes above ----- */
        bits8          t_bits[FLEXIBLE];   //  23  .. (null bitmap, optional)
    };
t_hoff = MAXALIGN(23 + null_bitmap_bytes).

==========================================================================
REFERENCES (every formula/number below verified against these)
==========================================================================
  * PostgreSQL source: src/include/access/htup_details.h (HeapTupleHeaderData),
                       src/include/postgres.h (varlena macros: SET_VARSIZE_1B,
                       SET_VARSIZE_4B, VARATT_IS_1B), src/include/varatt.h
                       (varatt_external, TOAST pointer).
  * PostgreSQL docs: Ch. 73 "Database Physical Storage",
                     https://www.postgresql.org/docs/current/storage-page-layout.html
  * Ramakrishnan & Gehrke, "Database Management Systems", Ch. 9 (storage).
  * Kleppmann, "Designing Data-Intensive Applications", Ch. 3.

KEY FORMULAS (all asserted in code):
    header_size               = 23 bytes            (HeapTupleHeaderData)
    null_bitmap_bytes         = (natts + 7) // 8    (only if HASNULL)
    t_hoff                    = MAXALIGN(23 + null_bitmap_bytes)
    align_to(off, a)          = ((off + a - 1) // a) * a
    column data offset        = align_to(prev_offset, typalign)
    1B varlena header byte    = (total_len << 1) | 0x01     (total_len <= 127)
    4B varlena header (LE)    = (total_len << 2) & ~3        (total_len > 127)
    TOAST pointer in-tuple    = 18 bytes (0x01, tag=18, 16 B varatt_external)
    NULL value                = 0 data bytes; just a 0 bit in the bitmap

Conventions used below:
    MAXALIGN = 8                (the 64-bit default; 4 on 32-bit builds)
    on-disk byte order          = little-endian (x86/ARM64 Postgres)
    sizes counted include the header tag + bitmap + all padding + data.
"""

from __future__ import annotations

import struct

BANNER = "=" * 72

MAXALIGN = 8  # 64-bit build default

# typlen (>0 fixed; -1 varlena) and typalign code -> bytes.
TYPE_REG = {
    # name        : (typlen, align)
    "bool":       (1, 1),
    '"char"':     (1, 1),
    "char1":      (1, 1),
    "smallint":   (2, 2),
    "int2":       (2, 2),
    "integer":    (4, 4),
    "int4":       (4, 4),
    "real":       (4, 4),
    "float4":     (4, 4),
    "date":       (4, 4),
    "bigint":     (8, 8),
    "int8":       (8, 8),
    "double":     (8, 8),
    "float8":     (8, 8),
    "timestamp":  (8, 8),
    "timestamptz":(8, 8),
    "time":       (8, 8),
}

VARLENA = {"text", "varchar", "bytea", "bpchar"}  # typlen = -1, typalign 'i'

# HeapTupleHeaderData is exactly this big.
HEADER_SIZE = 23

# A varlena whose payload exceeds this is TOASTed (moved off-page) and the
# in-tuple value becomes a fixed 18-byte pointer. (Real Postgres uses a more
# involved tuple-budget rule; this threshold is the pedagogical simplification.)
TOAST_THRESHOLD = 2000
TOAST_POINTER_SIZE = 18  # 1 B marker(0x01) + 1 B tag(18) + 16 B varatt_external


# ============================================================================
# 1. THE BYTE-LAYOUT ENGINE (this is the code TUPLE_FORMAT.md walks through)
# ============================================================================

def align_to(offset: int, a: int) -> int:
    """Smallest n >= offset that is a multiple of a (a>=1)."""
    if a <= 1:
        return offset
    return ((offset + a - 1) // a) * a


def varlena_header_len(data_len: int) -> int:
    """Number of header bytes for a varlena of `data_len` payload bytes.

    Short (<=127 B total) -> 1-byte header; otherwise 4-byte header. This is
    PostgreSQL's heaptuple.c `fill_val` / `store_att_byval` path.
    """
    total_short = data_len + 1
    return 1 if total_short <= 127 else 4


def compute_layout(columns, values):
    """Serialize-aware byte layout of ONE heap tuple.

    columns : list of (name, type) tuples, e.g. [('a','int4'),('b','text')]
    values  : list of python values; use None for SQL NULL.

    Returns a dict describing every byte region (header, bitmap, padding,
    each column) plus the totals. Pure: no I/O, no global state.
    """
    natts = len(columns)
    has_null = any(v is None for v in values)
    bitmap_bytes = (natts + 7) // 8 if has_null else 0

    header_end = HEADER_SIZE + bitmap_bytes
    t_hoff = align_to(header_end, MAXALIGN)

    regions = []
    regions.append((0, HEADER_SIZE, "header",
                    "HeapTupleHeaderData", "(t_xmin..t_hoff)"))
    if bitmap_bytes:
        regions.append((HEADER_SIZE, bitmap_bytes, "bitmap",
                        "NULL bitmap", "1 bit/col; 1=present 0=NULL"))
    hpad = t_hoff - header_end
    if hpad:
        regions.append((header_end, hpad, "hpad",
                        "MAXALIGN padding", "pad header to 8"))

    offset = t_hoff
    for (name, typ), val in zip(columns, values):
        if val is None:
            regions.append((offset, 0, "null", name, "NULL: 0 data bytes"))
            continue
        if typ in VARLENA:
            data = val.encode("utf-8") if isinstance(val, str) else bytes(val)
            if len(data) > TOAST_THRESHOLD:
                # TOASTed: replaced by a fixed 18-byte external pointer.
                total = TOAST_POINTER_SIZE
                a = 1                          # marker 0x01 -> no alignment
            else:
                hdr = varlena_header_len(len(data))
                total = hdr + len(data)
                a = 1 if hdr == 1 else 4       # 1B header: no align; else 4
        else:
            typlen, align = TYPE_REG[typ]
            total = typlen
            a = align
        aligned = align_to(offset, a)
        if aligned > offset:
            regions.append((offset, aligned - offset, "pad",
                            f"pad {name}", f"align {a}B"))
        regions.append((aligned, total, "data", f"{name} ({typ})", ""))
        offset = aligned + total

    total_size = offset
    return {
        "natts": natts,
        "has_null": has_null,
        "bitmap_bytes": bitmap_bytes,
        "t_hoff": t_hoff,
        "total_size": total_size,
        "regions": regions,
    }


def encode_tuple(columns, values, *,
                 xmin=1000, xmax=0, cid=0, ctid_block=0, ctid_off=1):
    """Build the ACTUAL byte buffer for a heap tuple (little-endian).

    Returns a bytearray of length total_size. Header fields are filled with
    plausible values so the hex dump is readable.
    """
    lay = compute_layout(columns, values)
    buf = bytearray(lay["total_size"])

    # ---- 23-byte header ----
    infomask2 = lay["natts"] & 0x07FF                 # HEAP_NATTS_MASK
    infomask = 0x0800                                  # HEAP_XMAX_INVALID
    if lay["has_null"]:
        infomask |= 0x0001                             # HEAP_HASNULL
    has_varwidth = any((c[1] in VARLENA and v is not None)
                       for c, v in zip(columns, values))
    if has_varwidth:
        infomask |= 0x0002                             # HEAP_HASVARWIDTH

    struct.pack_into("<I", buf,  0, xmin & 0xFFFFFFFF)   # t_xmin  (0..3)
    struct.pack_into("<I", buf,  4, xmax & 0xFFFFFFFF)   # t_xmax  (4..7)
    struct.pack_into("<I", buf,  8, cid & 0xFFFFFFFF)    # t_cid   (8..11)
    struct.pack_into("<I", buf, 12, ctid_block & 0xFFFFFFFF)  # t_ctid block
    struct.pack_into("<H", buf, 16, ctid_off & 0xFFFF)        # t_ctid off
    struct.pack_into("<H", buf, 18, infomask2)          # t_infomask2
    struct.pack_into("<H", buf, 20, infomask)           # t_infomask
    buf[22] = lay["t_hoff"] & 0xFF                      # t_hoff

    # ---- null bitmap ----
    if lay["has_null"]:
        bits = 0
        for i, v in enumerate(values):
            if v is not None:
                bits |= (1 << i)                        # bit i set = present
        buf[HEADER_SIZE] = bits & 0xFF

    # ---- column data ----
    for (name, typ), val in zip(columns, values):
        if val is None:
            continue
        # find the region offset for this column
        off = next(r[0] for r in lay["regions"]
                   if r[3] == f"{name} ({typ})" and r[2] == "data")
        if typ in VARLENA:
            data = val.encode("utf-8") if isinstance(val, str) else bytes(val)
            if len(data) > TOAST_THRESHOLD:
                # 18-byte TOAST pointer: marker, tag, 16-byte varatt_external.
                buf[off] = 0x01                       # VARATT_IS_1B_E marker
                buf[off + 1] = 18                     # VARTAG_ON_DISK = 18
                struct.pack_into("<I", buf, off + 2,  (len(data) + 4) & 0xFFFFFFFF)
                struct.pack_into("<I", buf, off + 6,  len(data) & 0xFFFFFFFF)
                struct.pack_into("<I", buf, off + 10, 0x12345)        # va_valueid
                struct.pack_into("<I", buf, off + 14, 0x9912)         # va_tableoid
            else:
                hdr = varlena_header_len(len(data))
                if hdr == 1:
                    buf[off] = ((hdr + len(data)) << 1) | 0x01   # 1B header
                    buf[off + 1:off + 1 + len(data)] = data
                else:
                    total = hdr + len(data)
                    struct.pack_into("<I", buf, off, (total << 2) & 0xFFFFFFFC)
                    buf[off + 4:off + 4 + len(data)] = data
        else:
            typlen, _ = TYPE_REG[typ]
            pack = {
                1: ("B", 1), 2: ("<H", 2), 4: ("<I", 4), 8: ("<Q", 8),
            }[typlen]
            fmt, sz = pack
            struct.pack_into(fmt, buf, off, int(val) & ((1 << (8 * sz)) - 1))
    return buf


def hex_dump(buf, base=0, width=16):
    """Pretty-printable hex dump: offset | bytes | ascii."""
    lines = []
    for i in range(0, len(buf), width):
        chunk = buf[i:i + width]
        hexs = " ".join(f"{b:02x}" for b in chunk)
        hexs = hexs.ljust(width * 3 - 1)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{base + i:04x}  {hexs}  |{asc}|")
    return "\n".join(lines)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def render_layout(lay, prefix=""):
    """Print the region table for a layout dict."""
    print(f"{prefix}natts={lay['natts']}  has_null={lay['has_null']}  "
          f"bitmap_bytes={lay['bitmap_bytes']}  t_hoff={lay['t_hoff']}  "
          f"total_size={lay['total_size']}\n")
    print(f"{prefix}{'off':>4}  {'len':>4}  {'kind':<6}  "
          f"{'label':<24}  note")
    print(f"{prefix}{'----':>4}  {'----':>4}  {'------':<6}  "
          f"{'------------------------':<24}  ----")
    for off, length, kind, label, note in lay["regions"]:
        print(f"{prefix}{off:>4}  {length:>4}  {kind:<6}  "
              f"{label:<24}  {note}")
    waste = sum(r[1] for r in lay["regions"] if r[2] in ("pad", "hpad"))
    print(f"\n{prefix}bytes wasted on padding: {waste} / {lay['total_size']}  "
          f"({100*waste/lay['total_size']:.1f}%)")


# ============================================================================
# 3. THE SECTIONS  (each prints a banner + a table; numbers feed the .md)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: fixed-length columns and alignment padding
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: fixed-length columns and alignment padding")
    print("Fixed-length types have a typlen AND a typalign. The column is")
    print("placed at the next offset that is a multiple of typalign, inserting")
    print("PADDING bytes before it.\n")
    print("| type        | typlen | typalign | bytes needed |")
    print("|-------------|--------|----------|--------------|")
    for name in ["bool", "smallint", "integer", "bigint", "double",
                 "timestamp", "date"]:
        L, a = TYPE_REG[name]
        print(f"| {name:<11} | {L:>6} | {a:>8} | {L:>12} |")
    print()
    print("Worked: pack three fixed columns, one row, no NULLs.")
    print("  cols = [('a','integer'), ('b','bigint'), ('c','integer')]")
    lay = compute_layout([("a", "integer"), ("b", "bigint"),
                          ("c", "integer")], [1, 2, 3])
    render_layout(lay)
    print("\nObserve the 1-byte header pad (MAXALIGN) and the 4-byte pad before")
    print("the bigint (it must land on an 8-byte boundary). Section D shows how")
    print("reordering removes some of this.")
    # sanity
    assert lay["t_hoff"] == 24
    assert lay["total_size"] == 44, lay
    assert lay["bitmap_bytes"] == 0
    print("\n[check] t_hoff==24 and total==44:  OK")


# ----------------------------------------------------------------------------
# SECTION B: variable-length columns (varlena) - 1B vs 4B header, TOAST
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: variable-length columns (text/varchar) - varlena headers")
    print("A varlena carries its own length in a 1-byte or 4-byte header.\n")
    print("| payload chars | total bytes | header | header byte (LE) | align |")
    print("|---------------|-------------|--------|------------------|-------|")
    cases = [("hi", 2), ("hello", 5), ("a"*126, 126), ("a"*127, 127),
             ("a"*128, 128), ("a"*200, 200)]
    for s, n in cases:
        hdr = varlena_header_len(n)
        total = hdr + n
        if hdr == 1:
            byte = ((hdr + n) << 1) | 0x01
            hb = f"0x{byte:02x}"
            a = 1
        else:
            word = ((hdr + n) << 2) & 0xFFFFFFFC
            hb = " ".join(f"{b:02x}" for b in struct.pack("<I", word))
            a = 4
        print(f"| {n:>13} | {total:>11} | {hdr:>6} | {hb:<16} | {a:>5} |")
    print()
    print("RULE: total <= 127 bytes  ->  1-byte header, NO alignment.")
    print("      total  > 127 bytes  ->  4-byte header, align to 4 bytes ('i').")
    print("The 1-byte-header exemption is the single biggest space saver in a")
    print("Postgres row: a 'status'='OK' column packs with zero padding.\n")

    print("TOAST: if a varlena is bigger than ~2 KiB it is moved OUT of the")
    print("tuple and replaced by an 18-byte pointer:")
    print("   1 B : 0x01 marker (VARATT_IS_1B_E)")
    print("   1 B : tag (18 = VARTAG_ON_DISK)")
    print("  16 B : varatt_external {va_rawsize, va_extinfo, va_valueid,")
    print("                          va_tableoid}  (4 B each, little-endian)")
    print("  = 18 bytes total, no matter how huge the real value.\n")
    lay = compute_layout([("big", "text")], ["X" * 5000])
    # big text -> TOASTed: model as 18-byte pointer
    print(f"[check] a 5000-char text -> in-tuple pointer is 18 bytes "
          f"(modeled):  OK")
    print("        (in this simulator TOASTed values are reported as 18 B; the")
    print("         real value lives in the pg_toast table, off-page.)")
    assert lay["total_size"] == 24 + 18  # header pad + 18-byte pointer model
    print(f"[check] total_size=={24 + 18}:  OK")


# ----------------------------------------------------------------------------
# SECTION C: NULL values - bitmap, 0 data bytes
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: NULL values - the null bitmap, 0 data bytes")
    print("A NULL column stores NOTHING in the data area. Instead a bit is")
    print("cleared in the null bitmap (1 byte per 8 columns, only present when")
    print("HEAP_HASNULL is set).\n")
    print("Example: [('a','integer'),('b','bigint'),('c','integer')] with")
    print("         b = NULL.\n")
    lay = compute_layout([("a", "integer"), ("b", "bigint"),
                          ("c", "integer")], [1, None, 3])
    render_layout(lay)
    print("\nNote: t_hoff is STILL 24. With <=8 columns the 1-byte bitmap pads")
    print("into the same MAXALIGN chunk as the header, so NULLs cost nothing in")
    print("header overhead here. The bigint's 8 bytes simply disappear.\n")
    # bitmap byte: bits 0 (a=1) and 2 (c=1) set = 0b00000101 = 5
    assert lay["bitmap_bytes"] == 1
    assert lay["total_size"] == 32, lay
    buf = encode_tuple([("a", "integer"), ("b", "bigint"),
                        ("c", "integer")], [1, None, 3])
    assert buf[HEADER_SIZE] == 0b00000101
    print(f"null bitmap byte = {buf[HEADER_SIZE]:#04x}  "
          f"(bit0=a present, bit2=c present, bit1=b NULL)")
    print("[check] bitmap byte==0x05 and total==32:  OK")


# ----------------------------------------------------------------------------
# SECTION D: alignment waste - column ORDER matters
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: alignment waste - column ORDER changes the tuple size")
    print("Same columns, same values, different ORDER -> different total size.")
    print("The classic: [int4, int8, int4] vs [int8, int4, int4].\n")
    cols_left  = [("x", "integer"), ("y", "bigint"), ("z", "integer")]
    cols_right = [("y", "bigint"), ("x", "integer"), ("z", "integer")]
    lay_l = compute_layout(cols_left,  [1, 2, 3])
    lay_r = compute_layout(cols_right, [2, 1, 3])
    print("BAD order  [int4, int8, int4]:")
    render_layout(lay_l, prefix="  ")
    print()
    print("GOOD order [int8, int4, int4]:")
    render_layout(lay_r, prefix="  ")
    print()
    print(f"BAD  total = {lay_l['total_size']} bytes")
    print(f"GOOD total = {lay_r['total_size']} bytes")
    print(f"saving by reordering: {lay_l['total_size'] - lay_r['total_size']} bytes/row")
    print()
    print("WHY: in [int4, int8, int4], the int8 needs an 8-byte boundary, so 4")
    print("bytes of pad are inserted before it (after the first int4 at 28).")
    print("Putting the 8-byte-aligned bigint FIRST (at offset 24, already")
    print("aligned) removes that pad entirely. RULE OF THUMB: order columns by")
    print("descending alignment (8B first, then 4B, then 2B, then 1B).")
    assert lay_l["total_size"] == 44 and lay_r["total_size"] == 40
    print(f"\n[check] BAD==44, GOOD==40, delta==4:  OK")
    # extrapolate to a real table
    rows = 10_000_000
    print(f"\nAt {rows:,} rows this is {(lay_l['total_size']-lay_r['total_size'])*rows/2**20:.0f} MiB "
          f"of pure padding waste. Multiply across every table in a DB.")


# ----------------------------------------------------------------------------
# SECTION E: WORKED EXAMPLE + GOLD (CREATE TABLE t(a int,b text,c bigint,d boolean))
# ----------------------------------------------------------------------------

GOLD_COLUMNS = [("a", "integer"), ("b", "text"),
                ("c", "bigint"), ("d", "bool")]
GOLD_VALUES  = [42, "hello", 9999999999, True]

def section_e():
    banner("SECTION E: WORKED EXAMPLE  CREATE TABLE t(a int, b text, c bigint, d boolean)")
    print("INSERT INTO t VALUES (42, 'hello', 9999999999, true);\n")
    lay = compute_layout(GOLD_COLUMNS, GOLD_VALUES)
    render_layout(lay)
    print("\nByte-by-byte (little-endian, the on-disk format):\n")
    buf = encode_tuple(GOLD_COLUMNS, GOLD_VALUES)
    print(hex_dump(buf))
    print(f"\nGOLD: total tuple size = {lay['total_size']} bytes   "
          f"(this is the value tuple_format.html recomputes in JS)")
    print("GOLD: header fields -> t_hoff=%d, t_infomask=0x%04x, t_infomask2=%d"
          % (buf[22], struct.unpack_from("<H", buf, 20)[0],
             struct.unpack_from("<H", buf, 18)[0]))
    # ---- assertions ----
    assert lay["total_size"] == 49, lay
    assert buf[22] == 24                      # t_hoff
    assert buf[24] == 42 and buf[25] == 0     # a=42 LE
    assert buf[28] == ((6 << 1) | 1)          # 'hello' 1B header = 0x0d
    assert buf[29:34] == b"hello"
    assert struct.unpack_from("<Q", buf, 40)[0] == 9999999999
    assert buf[48] == 1                       # d=true
    print("\n[check] total==49, t_hoff==24, a==42, b header==0x0d, "
          "c==9999999999, d==1:  OK")
    print("[check] GOLD scalar total_size==49 reproduces from "
          "compute_layout():  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("tuple_format.py - reference impl. All numbers below feed "
          "TUPLE_FORMAT.md.")
    print("MAXALIGN =", MAXALIGN, " | byte order = little-endian")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
