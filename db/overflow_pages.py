"""
overflow_pages.py - Reference implementation of TOAST (The Oversized-Attribute
Storage Technique): how PostgreSQL stores values too large to fit in a page.

This is the single source of truth that OVERFLOW_PAGES.md is built from. Every
number, table, and worked example in OVERFLOW_PAGES.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 overflow_pages.py       (pure stdlib, no external deps)

==========================================================================
THE INTUITION (read this first) - the suitcase and the warehouse
==========================================================================
A database page is a fixed-size suitcase (PostgreSQL: 8 KB). Most rows fit
easily. But sometimes a single column holds something huge - a 50 KB JSON
document, a 2 MB image, a 100 KB log blob. You cannot jam a 50 KB object into
an 8 KB suitcase, and even a 3 KB object would leave no room for anything else
on the page.

  * inline storage:  jam the whole value into the suitcase. Works only while
                      the value is small. A single oversized value bloats every
                      SELECT that scans the page (you read 50 KB to fetch one
                      integer column next to it).
  * overflow pages:  move the big value to a SEPARATE warehouse shelf (a
                      linked list of overflow pages) and leave a small tag in
                      the suitcase pointing at it. Now scans that do not need
                      the big column never touch it.
  * TOAST:           before moving the value to the warehouse, try to SHRINK it
                      (compress). If it is still too big, cut it into ~2 KB
                      slices and store each slice on its own warehouse row, in
                      order. The suitcase keeps one 18-byte tag. TOAST = the
                      union of "compress, then chunk" + the pointer trick.

PostgreSQL's trigger: if a whole tuple would exceed TOAST_TUPLE_THRESHOLD
(~2 KB), the biggest varlena columns are toasted until the tuple fits.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  page             : the fixed-size suitcase (default 8 KB).
  tuple / row      : one record, which must fit (roughly) in a page.
  varlena          : PostgreSQL's variable-length column type (text, bytea,
                     jsonb, ...). Its on-disk form carries a length header. Only
                     varlena values can be toasted; a fixed int8 never is.
  TOAST threshold  : TOAST_TUPLE_THRESHOLD = 2000 bytes (the ~2 KB ceiling a
                     tuple should stay under). Real PostgreSQL ~2032; we use the
                     commonly cited 2000 for clean math.
  compress         : pglz (PostgreSQL's built-in Lempel-Ziv). We model it with a
                     simplified greedy LZ77 (see lz_compress). Rule: keep the
                     compressed form ONLY if it is strictly smaller.
  chunk            : a ~2 KB slice of the (compressed) value. TOAST_MAX_CHUNK_SIZE
                     = 2000 bytes of payload per chunk row.
  TOAST table      : the warehouse - a hidden per-table side table named
                     pg_toast_<oid>, with columns (chunk_id, chunk_seq, chunk_data).
  varlena pointer  : the 18-byte tag left in the main tuple when a value is
                     toasted. It says "my real bytes live in TOAST table X, row Y,
                     and are Z bytes long."
  detoast          : the reverse: read all chunks in chunk_seq order, glue them,
                     then decompress. Costs N chunk reads (often N random I/Os).

==========================================================================
THE LINEAGE (how storage of big values evolved)
==========================================================================
  inline        : value lives in the main tuple.          Fails > ~2 KB.
  overflow      : value moved to a linked list of overflow pages; main tuple
                  holds a pointer. (The "long field" trick - System R, IBM, and
                  still how some engines handle blobs.)
  TOAST         : compress first, then chunk into a TOAST table; main tuple holds
                  an 18-byte varlena pointer. (PostgreSQL, since 7.1, 2001; see
                  src/backend/access/heap/tuptoaster.c.)

==========================================================================
KEY FORMULAS / CONSTANTS (verified against PostgreSQL source, asserted in code)
==========================================================================
  TOAST_TUPLE_THRESHOLD = 2000            # bytes; tuple should stay under this
  TOAST_MAX_CHUNK_SIZE  = 2000            # payload bytes per chunk row
  num_chunks            = ceil(value_len / TOAST_MAX_CHUNK_SIZE)   # value_len is
                                                                  # the COMPRESSED
                                                                  # length
  TOAST_POINTER_BYTES   = 18              # varlena header(2) + varatt_external(16)
  CHUNK_ROW_OVERHEAD    = 40              # line ptr(4) + tup hdr(24) + chunk_id(4)
                                          # + chunk_seq(4) + bytea varlena hdr(4)
  total_storage = base_tuple + 18
                + sum_over_chunks( 40 + len(chunk_data) )

  compression rule: store compressed bytes only if len(compressed) < len(raw);
                     otherwise keep raw and (if still oversized) toast it raw.

  detoast cost   = num_chunks chunk reads (to reassemble) + 1 decompress
                    (if it was compressed). Worst case num_chunks random I/Os.

Conventions:
  Sizes are in BYTES unless stated. 1 KB = 1000 bytes (SI) in the prose; the
  code always works in raw bytes. The compressor is deterministic and seeded,
  so overflow_pages.html re-runs the IDENTICAL algorithm in JS and gold-checks.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# CONSTANTS  (documented; faithful to PostgreSQL, rounded for clean teaching)
# ---------------------------------------------------------------------------
TOAST_TUPLE_THRESHOLD = 2000   # ~2 KB tuple ceiling (real PG: ~2032 = MaxHeapTupleSize/4)
TOAST_MAX_CHUNK_SIZE = 2000    # payload bytes per chunk row (real PG: ~1996)
TOAST_POINTER_BYTES = 18       # on-tuple external pointer footprint (varatt_external)
CHUNK_ROW_OVERHEAD = 40        # per-chunk-row fixed cost (see glossary)

# main-tuple fixed cost for the worked example: header + line pointer + the
# row's OTHER (small) columns. The big value is NOT counted here; it is either
# inline or replaced by the 18-byte pointer.
BASE_TUPLE_BYTES = 60

# compressor parameters (must match overflow_pages.html exactly)
LZ_WINDOW = 4096
LZ_MIN_MATCH = 3
LZ_MAX_LEN = 130               # 0x80 + (130-3) fits in one control byte (T < 0xFF)
LZ_MAX_CHAIN = 32

BANNER = "=" * 74


# ============================================================================
# 1. THE COMPRESSOR  (simplified pglz: greedy LZ77 with grouped literals)
#    Deterministic. Identical algorithm is ported to JS in overflow_pages.html.
#    Format (byte stream):
#       control T in [0x00, 0x7F]  -> literal run, count = T+1 (1..128) literals
#       control T in [0x80, 0xFF]  -> match, length = (T-0x80)+MIN_MATCH,
#                                     followed by 2-byte little-endian offset
#       (the control byte alone disambiguates token type; T=0xFF = max-length match)
#    pglz rule: keep the compressed form only if strictly smaller than raw.
# ============================================================================
def lz_compress(data: bytes,
                window: int = LZ_WINDOW,
                min_match: int = LZ_MIN_MATCH,
                max_len: int = LZ_MAX_LEN,
                max_chain: int = LZ_MAX_CHAIN) -> bytes:
    """Greedy LZ77 with a 3-byte hash, bounded candidate chain, grouped
    literals. Fully deterministic for a fixed input. Mirrors pglz in spirit:
    back-references for repeated substrings, abandoned (returns raw) when the
    result is not smaller.
    """
    n = len(data)
    out = bytearray()
    pending = bytearray()            # buffered literals (emitted as runs)
    head: dict[bytes, list[int]] = {}

    def flush_literals():
        i = 0
        while i < len(pending):
            run = pending[i:i + 128]
            out.append(len(run) - 1)            # control: 0..127
            out.extend(run)
            i += len(run)
        pending.clear()

    def insert_prefix(p: int):
        if p + 3 <= n:
            k = bytes(data[p:p + 3])
            lst = head.setdefault(k, [])
            lst.append(p)
            if len(lst) > max_chain:
                del lst[0:len(lst) - max_chain]  # keep most-recent max_chain

    pos = 0
    while pos < n:
        best_len = 0
        best_off = 0
        if pos + min_match <= n:
            key = bytes(data[pos:pos + 3])
            cands = head.get(key)
            if cands:
                limit = min(max_len, n - pos)
                # scan most-recent first; update only on strictly longer match
                # -> ties resolve to smallest offset (most recent). Deterministic.
                for p in reversed(cands):
                    off = pos - p
                    if off > window:
                        break
                    L = 0
                    while L < limit and data[pos + L] == data[p + (L % off)]:
                        L += 1
                    if L > best_len:
                        best_len = L
                        best_off = off
                        if L >= limit:
                            break
        if best_len >= min_match:
            flush_literals()
            ctrl = 0x80 + (best_len - min_match)
            out.append(ctrl)
            out.append(best_off & 0xFF)
            out.append((best_off >> 8) & 0xFF)
            end = pos + best_len
            while pos < end:
                insert_prefix(pos)
                pos += 1
        else:
            pending.append(data[pos])
            insert_prefix(pos)
            pos += 1
    flush_literals()
    return bytes(out) if len(out) < n else bytes(data)


def lz_decompress(comp: bytes, raw_len: int) -> bytes:
    """Inverse of lz_compress. Used to prove round-trip integrity in Section E.
    """
    out = bytearray()
    i = 0
    n = len(comp)
    while i < n:
        t = comp[i]
        if t < 0x80:                       # literal run
            count = t + 1
            out.extend(comp[i + 1:i + 1 + count])
            i += 1 + count
        else:                              # match
            length = (t - 0x80) + LZ_MIN_MATCH
            off = comp[i + 1] | (comp[i + 2] << 8)
            start = len(out) - off
            for k in range(length):
                out.append(out[start + (k % off)])
            i += 3
    if len(out) != raw_len:
        raise ValueError(f"decompress length mismatch: {len(out)} != {raw_len}")
    return bytes(out)


# ============================================================================
# 2. THE TOAST PIPELINE  (compress -> maybe chunk -> build pointer -> detoast)
# ============================================================================
def compress_value(raw: bytes) -> tuple[bytes, bool]:
    """Return (stored_bytes, was_compressed). was_compressed is False when pglz
    could not shrink the value (then we store it raw, as PostgreSQL does).
    """
    comp = lz_compress(raw)
    if len(comp) < len(raw):
        return comp, True
    return raw, False


def chunk_value(value: bytes,
                chunk_size: int = TOAST_MAX_CHUNK_SIZE) -> list[bytes]:
    """Slice a (possibly already-compressed) value into <=chunk_size chunks."""
    if len(value) == 0:
        return [b""]
    return [value[i:i + chunk_size] for i in range(0, len(value), chunk_size)]


def make_toast_pointer(toastrel_oid: int, value_oid: int,
                       stored_len: int, compressed: bool) -> dict:
    """Build the 18-byte varlena external pointer that replaces the value in
    the main tuple. Fields mirror PostgreSQL's varatt_external:
        va_header        (2 bytes)  varlena on-disk external marker
        va_toastrelid    (4 bytes)  OID of the pg_toast_<oid> side table
        va_valueid       (4 bytes)  chunk_id of this value's chunks (an OID)
        va_size          (4 bytes)  stored length; low bit flags compression
        va_rawsize       (4 bytes)  original (uncompressed) length
    2 + 4 + 4 + 4 + 4 = 18 bytes total in the main tuple.
    """
    return {
        "bytes": TOAST_POINTER_BYTES,
        "va_header": "ext (2B)",
        "va_toastrelid": toastrel_oid,
        "va_valueid": value_oid,
        "va_size": stored_len,
        "va_size_flags": "compressed" if compressed else "raw",
        "va_rawsize": None,            # filled by caller with raw length
    }


def detoast(toast_table: dict, pointer: dict) -> tuple[bytes, int]:
    """Read all chunks for pointer['va_valueid'] in chunk_seq order, glue them,
       then decompress if needed. Return (raw_value, num_chunk_reads).
    """
    chunks = sorted(toast_table[pointer["va_valueid"]], key=lambda c: c["seq"])
    glued = b"".join(c["data"] for c in chunks)
    if pointer["va_size_flags"] == "compressed":
        raw = lz_decompress(glued, pointer["va_rawsize"])
    else:
        raw = glued
    return raw, len(chunks)


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def human(n: int) -> str:
    if n < 1000:
        return f"{n} B"
    if n < 1_000_000:
        return f"{n / 1000:.2f} KB"
    return f"{n / 1_000_000:.2f} MB"


# ============================================================================
# 4. DETERMINISTIC SAMPLE PAYLOADS
#    (identical generators are ported to JS in overflow_pages.html)
# ============================================================================
def make_repetitive(n: int = 2500) -> bytes:
    """Highly repetitive -> compresses to almost nothing."""
    unit = b"TOAST!"
    return (unit * (n // len(unit) + 1))[:n]


def make_text_like(n: int = 2600) -> bytes:
    """English-ish prose repeated -> moderate compression."""
    unit = (b"The Oversized-Attribute Storage Technique moves large values "
            b"out of the main heap tuple into a side table. ")
    return (unit * (n // len(unit) + 1))[:n]


def make_random(n: int = 3000, seed: int = 1337) -> bytes:
    """Pseudo-random bytes (xorshift32) -> essentially incompressible.
    Emits all 4 bytes of each 32-bit word so every output byte carries
    entropy (a single-byte LCG would be periodic and compress trivially).
    """
    out = bytearray()
    state = seed & 0xFFFFFFFF or 1            # xorshift state must be non-zero
    while len(out) < n:
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= (state >> 17) & 0xFFFFFFFF
        state ^= (state << 5) & 0xFFFFFFFF
        out.append(state & 0xFF)
        out.append((state >> 8) & 0xFF)
        out.append((state >> 16) & 0xFF)
        out.append((state >> 24) & 0xFF)
    return bytes(out[:n])


def make_gold_payload() -> bytes:
    """The pinned worked-example payload: semi-structured JSON-ish log lines
    with incrementing ids and several varying fields. Compresses (shared
    scaffolding text) but stays well above the threshold AFTER compression, so
    it fans out into multiple chunks. This is the value overflow_pages.html
    re-runs and gold-checks against.
    """
    lines = []
    for i in range(1, 601):                 # 600 lines
        hexf = "%06x" % (i * 2654435761 & 0xFFFFFF)
        lines.append(
            '{"id":%d,"ts":%d,"level":%d,"tag":"TOAST",'
            '"note":"chunk me please","hex":"%s","v":%d}'
            % (i, i * 1000 + 1234567890, i % 5, hexf, (i * 7) % 13)
        )
    return ("\n".join(lines)).encode()


# ============================================================================
# SECTION A: the threshold + the lineage
# ============================================================================
def section_a():
    banner("SECTION A: the ~2 KB threshold and the storage lineage")
    print("A database page is a fixed-size suitcase (PostgreSQL default 8 KB).")
    print("A tuple should stay small so many fit per page. PostgreSQL's rule:\n")
    print(f"  TOAST_TUPLE_THRESHOLD = {TOAST_TUPLE_THRESHOLD} bytes  (~2 KB)")
    print("  If a tuple would exceed this, its biggest varlena columns are")
    print("  toasted (compressed and/or moved out of line) until it fits.\n")
    print("| storage era   | idea                                        | "
          "fits in page? |")
    print("|---------------|---------------------------------------------|"
          "---------------|")
    rows = [
        ("inline", "value jammed into the main tuple", "only if < ~2 KB"),
        ("overflow", "value on linked overflow pages; tuple holds a pointer",
         "yes (pointer)"),
        ("TOAST", "compress first, then chunk into a side table; 18-byte ptr",
         "yes (ptr)"),
    ]
    for era, idea, fits in rows:
        print(f"| {era:<13} | {idea:<43} | {fits:<13} |")
    print()
    print("The threshold is not magic: it is ~MaxHeapTupleSize/4, so ~4 toasted")
    print("tuples can still share an 8 KB page with room for the small columns.")
    print("\n[check] threshold is ~2 KB:", TOAST_TUPLE_THRESHOLD == 2000, "-> OK")


# ============================================================================
# SECTION B: compression (pglz concept) - ratio across data patterns
# ============================================================================
def section_b():
    banner("SECTION B: compression attempt (pglz concept)")
    print("Before moving a value out of line, PostgreSQL tries to SHRINK it with")
    print("pglz (a Lempel-Ziv variant). Modeled here as greedy LZ77. pglz rule:")
    print("keep the compressed form ONLY if it is strictly smaller than raw.\n")
    samples = [
        ("repetitive", make_repetitive(2500)),
        ("text-like", make_text_like(2600)),
        ("random (xorshift)", make_random(3000)),
    ]
    print("| pattern       | raw (B) | compressed (B) | ratio  | compressed? | "
          "toasted?* |")
    print("|---------------|---------|----------------|--------|-------------|"
          "-----------|")
    for name, raw in samples:
        comp = lz_compress(raw)
        compressed = len(comp) < len(raw)
        stored = comp if compressed else raw
        ratio = len(raw) / len(stored) if len(stored) else 0
        # value is toasted if, AFTER compression, it still cannot live inline.
        # A single value this big in a tuple > threshold -> toasted.
        toasted = len(stored) + BASE_TUPLE_BYTES > TOAST_TUPLE_THRESHOLD
        print(f"| {name:<13} | {len(raw):<7} | {len(stored):<14} | "
              f"{ratio:<6.2f} | {'yes' if compressed else 'no':<11} | "
              f"{'yes' if toasted else 'no':<9} |")
    print("\n* 'toasted' here = stored out of line (would not fit inline with the")
    print("  base tuple). Repetitive data shrinks below the threshold and could")
    print("  even stay inline; random data barely compresses and must be moved.")
    print("\nLESSON: compression is a free win for repetitive blobs and a no-op")
    print("for random blobs. That is why TOAST tries compress FIRST, chunk SECOND.")


# ============================================================================
# SECTION C: chunking - the TOAST table layout
# ============================================================================
def section_c():
    banner("SECTION C: chunking - slice the (compressed) value into a TOAST table")
    raw = make_gold_payload()
    comp, was_compressed = compress_value(raw)
    stored = comp if was_compressed else raw
    print(f"Gold payload: {len(raw)} raw bytes "
          f"({human(len(raw))}), semi-structured JSON-ish log lines.")
    print(f"After pglz:    {len(stored)} stored bytes "
          f"({human(len(stored))})  "
          f"[compressed={was_compressed}]\n")
    print(f"Stored size {len(stored)} B > TOAST_TUPLE_THRESHOLD "
          f"{TOAST_TUPLE_THRESHOLD} B -> MUST be chunked.\n")
    chunks = chunk_value(stored, TOAST_MAX_CHUNK_SIZE)
    print(f"num_chunks = ceil({len(stored)} / {TOAST_MAX_CHUNK_SIZE}) = "
          f"{len(chunks)}\n")
    print("TOAST table  pg_toast_<oid>  schema:")
    print("    chunk_id   Oid    -- same for all chunks of one value")
    print("    chunk_seq  int4   -- 0,1,2,...  (the glue order)")
    print("    chunk_data bytea  -- up to TOAST_MAX_CHUNK_SIZE bytes\n")
    toastrel_oid = 16432
    value_oid = 4321
    print(f"| chunk_id | chunk_seq | chunk_data (B) | full row (B) |")
    print("|----------|-----------|----------------|--------------|")
    toast_rows = []
    total_chunk_bytes = 0
    for seq, data in enumerate(chunks):
        row_bytes = CHUNK_ROW_OVERHEAD + len(data)
        total_chunk_bytes += row_bytes
        print(f"| {value_oid:<8} | {seq:<9} | {len(data):<14} | "
              f"{row_bytes:<12} |")
        toast_rows.append({"seq": seq, "data": data})
    print(f"\nTotal chunk storage = sum of full row sizes = {total_chunk_bytes} B "
          f"({human(total_chunk_bytes)}).")
    expected = math.ceil(len(stored) / TOAST_MAX_CHUNK_SIZE)
    print(f"\n[check] num_chunks == ceil(stored/chunk_size) "
          f"== ceil({len(stored)}/{TOAST_MAX_CHUNK_SIZE}) == {expected}: "
          f"{'OK' if len(chunks) == expected else 'FAIL'}")
    return {
        "raw": raw, "stored": stored, "compressed": was_compressed,
        "chunks": chunks, "toast_rows": toast_rows,
        "toastrel_oid": toastrel_oid, "value_oid": value_oid,
        "total_chunk_bytes": total_chunk_bytes,
    }


# ============================================================================
# SECTION D: the varlena pointer (18-byte tag left in the main tuple)
# ============================================================================
def section_d(ctx):
    banner("SECTION D: the 18-byte varlena pointer (the tag in the suitcase)")
    stored = ctx["stored"]
    ptr = make_toast_pointer(ctx["toastrel_oid"], ctx["value_oid"],
                             len(stored), ctx["compressed"])
    ptr["va_rawsize"] = len(ctx["raw"])
    print("When a value is toasted, the main tuple NO LONGER holds the bytes.")
    print(f"It holds an {TOAST_POINTER_BYTES}-byte external pointer "
          "(PostgreSQL varatt_external):\n")
    print("| field           | bytes | value (this example)        |")
    print("|-----------------|-------|-----------------------------|")
    print(f"| va_header       | 2     | external-marker (on-disk)   |")
    print(f"| va_toastrelid   | 4     | {ptr['va_toastrelid']} "
          f"(pg_toast_{ptr['va_toastrelid']}) |")
    print(f"| va_valueid      | 4     | {ptr['va_valueid']} "
          f"(chunk_id for all chunks)  |")
    print(f"| va_size         | 4     | {ptr['va_size']} "
          f"({ptr['va_size_flags']}, low bit=flag) |")
    print(f"| va_rawsize      | 4     | {ptr['va_rawsize']} (uncompressed len)|")
    print("|-----------------|-------|-----------------------------|")
    print(f"| TOTAL in tuple  | {TOAST_POINTER_BYTES}     | "
          f"replaces {len(ctx['raw'])} raw bytes "
          f"({human(len(ctx['raw']))})\n")
    print("So the {0:,}-byte value is represented in the main tuple by just "
          "{1} bytes - a {2:.0f}x shrink in the hot path."
          .format(len(ctx["raw"]), TOAST_POINTER_BYTES,
                  len(ctx["raw"]) / TOAST_POINTER_BYTES))
    print("\nSELECTs that do not project this column never follow the pointer -")
    print("they never pay the chunk-read cost. THAT is the point of out-of-line.")
    assert ptr["bytes"] == 18
    print("\n[check] pointer footprint == 18 bytes: OK")
    ctx["pointer"] = ptr


# ============================================================================
# SECTION E: detoasting - reassemble + decompress, and its cost
# ============================================================================
def section_e(ctx):
    banner("SECTION E: retrieval (detoast) - glue chunks, then decompress")
    ptr = ctx["pointer"]
    n_chunks = len(ctx["chunks"])
    print("To read a toasted value back, PostgreSQL must:\n")
    print("  1. read the {0}-byte pointer from the main tuple".format(
        TOAST_POINTER_BYTES))
    print(f"  2. fetch all {n_chunks} chunks WHERE chunk_id = {ptr['va_valueid']}")
    print("     ORDER BY chunk_seq   <- this is the expensive part")
    print("  3. concatenate chunk_data in chunk_seq order")
    print("  4. if va_size says compressed: pglz-decompress the glued bytes\n")
    toast_table = {ptr["va_valueid"]: ctx["toast_rows"]}
    recovered, reads = detoast(toast_table, ptr)
    ok = recovered == ctx["raw"]
    print(f"Round-trip check: detoasted bytes == original raw bytes? {ok}")
    print(f"  original  : {len(ctx['raw'])} bytes")
    print(f"  recovered : {len(recovered)} bytes")
    print(f"  chunk reads: {reads}  (= num_chunks; often {reads} random I/Os "
          f"if not cached)\n")
    print("COST: detoasting a value split across N chunks is N index lookups +")
    print("N page reads in pg_toast_<oid>, plus a decompress. For a value that")
    print("fanned out into many chunks this is dramatically more expensive than")
    print("reading an inline value. This is why EXTERNAL (no compression) can be")
    print("SLOWER to read than EXTENDED (compress first -> fewer chunks) even")
    print("though it skips the decompress step: more chunks = more reads.")
    print(f"\n[check] detoast round-trip == raw: {'OK' if ok else 'FAIL'}")


# ============================================================================
# SECTION F: the four strategies (PLAIN / EXTERNAL / EXTENDED / MAIN)
# ============================================================================
def section_f():
    banner("SECTION F: the four TOAST strategies (column attstorage)")
    print("Each column has a strategy (attstorage). The four values:\n")
    rows = [
        ("PLAIN", "0", "no", "no", "fixed-size types, small varlena",
         "inline, always"),
        ("EXTERNAL", "1", "no", "yes", "blob columns where decompress cost "
         "matters more than size", "out-of-line, uncompressed"),
        ("EXTENDED", "2", "yes", "yes", "DEFAULT for most varlena (text, "
         "bytea, jsonb)", "compress, then out-of-line if still big"),
        ("MAIN", "3", "yes", "last resort", "values you want inline if at all "
         "possible", "compress; keep inline; move out-of-line only if forced"),
    ]
    print("| strategy | code | compress? | out-of-line? | typical use        "
          "            | resulting storage        |")
    print("|----------|------|-----------|--------------|----------------------"
          "--------|--------------------------|")
    for r in rows:
        print(f"| {r[0]:<8} | {r[1]:<4} | {r[2]:<9} | {r[3]:<12} | "
              f"{r[4]:<34} | {r[5]:<24} |")
    print()
    print("EXTENDED is the default and almost always right: compress first (a")
    print("free win for repetitive data), and only pay the chunk-read cost if the")
    print("value is genuinely huge. EXTERNAL trades space for decompress-CPU and")
    print("is used for blobs that are already compressed (e.g. JPEG) where pglz")
    print("would do nothing but the column is read often. MAIN tries hard to keep")
    print("a value inline (in the main tuple, possibly compressed) and only")
    print("overflows as a last resort.\n")
    raw = make_gold_payload()
    comp, was = compress_value(raw)
    print("Same gold payload under each strategy:")
    print(f"  raw={len(raw)} B, pglz={len(comp)} B "
          f"(compressed={was}), threshold={TOAST_TUPLE_THRESHOLD} B\n")
    print("| strategy | bytes in main tuple | chunks | detoast reads | notes")
    print("|----------|---------------------|--------|---------------|-----")
    for name, do_compress, allow_external in [
        ("PLAIN", False, False),
        ("EXTERNAL", False, True),
        ("EXTENDED", True, True),
        ("MAIN", True, False),
    ]:
        if name == "PLAIN":
            inline = raw
            note = "raw inline; bloats every scan"
            main_bytes = len(inline)
            chunks_n = 0
            reads = 0
        else:
            stored = comp if (do_compress and was) else raw
            if allow_external and (len(stored) + BASE_TUPLE_BYTES
                                   > TOAST_TUPLE_THRESHOLD):
                main_bytes = TOAST_POINTER_BYTES
                chunks_n = math.ceil(len(stored) / TOAST_MAX_CHUNK_SIZE)
                reads = chunks_n
                note = ("compressed" if do_compress and was else "raw") + \
                    " -> out-of-line"
            else:
                main_bytes = len(stored)
                chunks_n = 0
                reads = 0
                if do_compress and was and allow_external:
                    note = "compressed; small enough to stay inline"
                elif do_compress and was:
                    note = "compressed inline (forced)"
                else:
                    note = "raw inline"
        print(f"| {name:<8} | {main_bytes:<19} | {chunks_n:<6} | "
              f"{reads:<13} | {note}")
    print()
    print("PLAIN is shown for contrast only: a {0:,}-byte value inline would"
          .format(len(raw)))
    print("make the tuple far exceed the page - PostgreSQL would in fact refuse")
    print("such a tuple. The other three all keep the main tuple tiny; they")
    print("differ in compression and in read cost (number of chunk reads).")


# ============================================================================
# GOLD SUMMARY (pinned values for overflow_pages.html)
# ============================================================================
def gold_summary(ctx):
    banner("GOLD VALUES (pinned for overflow_pages.html)")
    raw = ctx["raw"]
    stored = ctx["stored"]
    chunks = ctx["chunks"]
    total_storage = (BASE_TUPLE_BYTES + TOAST_POINTER_BYTES
                     + sum(CHUNK_ROW_OVERHEAD + len(c) for c in chunks))
    print(f"payload        : {len(raw)} raw bytes  ({human(len(raw))})")
    print(f"compressed     : {len(stored)} stored bytes  "
          f"(compressed={ctx['compressed']})")
    print(f"num_chunks     : {len(chunks)}  "
          f"(= ceil({len(stored)}/{TOAST_MAX_CHUNK_SIZE}))")
    print(f"pointer        : {TOAST_POINTER_BYTES} bytes in main tuple")
    print(f"chunk reads    : {len(chunks)}  (detoast cost)")
    print(f"total storage  : base({BASE_TUPLE_BYTES}) "
          f"+ pointer({TOAST_POINTER_BYTES}) "
          f"+ {len(chunks)} chunk rows "
          f"= {total_storage} bytes  ({human(total_storage)})")

    # ---- assertions (the gold contract) ----
    assert len(chunks) == math.ceil(len(stored) / TOAST_MAX_CHUNK_SIZE)
    assert ctx["pointer"]["bytes"] == TOAST_POINTER_BYTES == 18
    assert total_storage == BASE_TUPLE_BYTES + TOAST_POINTER_BYTES + \
        sum(CHUNK_ROW_OVERHEAD + len(c) for c in chunks)
    # round-trip
    toast_table = {ctx["value_oid"]: ctx["toast_rows"]}
    rec, _ = detoast(toast_table, ctx["pointer"])
    assert rec == raw
    print("\n[check] num_chunks == ceil(stored/chunk_size): OK")
    print("[check] pointer == 18 bytes: OK")
    print("[check] total_storage == base + pointer + sum(chunk rows): OK")
    print("[check] detoast(raw) == payload: OK")

    # ---- compact scalars for the .html gold-check ----
    print("\nGOLD scalars (copy into overflow_pages.html):")
    print(f"  GOLD_RAW_LEN      = {len(raw)}")
    print(f"  GOLD_STORED_LEN   = {len(stored)}")
    print(f"  GOLD_COMPRESSED   = {str(ctx['compressed']).lower()}")
    print(f"  GOLD_NUM_CHUNKS   = {len(chunks)}")
    print(f"  GOLD_TOTAL_BYTES  = {total_storage}")
    print(f"  GOLD_POINTER      = {TOAST_POINTER_BYTES}")
    print(f"  GOLD_CHUNK_SIZES  = {[len(c) for c in chunks]}")
    print(f"  GOLD_TOASTREL_OID = {ctx['toastrel_oid']}")
    print(f"  GOLD_VALUE_OID    = {ctx['value_oid']}")


# ============================================================================
# main
# ============================================================================
def main():
    print("overflow_pages.py - reference impl. All numbers feed OVERFLOW_PAGES.md.")
    print("pure Python stdlib. Deterministic inputs.")

    section_a()
    section_b()
    ctx = section_c()
    section_d(ctx)
    section_e(ctx)
    section_f()
    gold_summary(ctx)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
