"""
delta_encoding.py - Reference implementation of delta encoding + varint.

This is the single source of truth that DELTA_ENCODING.md is built from. Every
number, table, and worked example is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python delta_encoding.py

==========================================================================
THE INTUITION (read this first) - the running tab, not the receipt pile
==========================================================================
Imagine logging your car's odometer every day. Storing the full reading each
day wastes space:

    day 1: 100000 km
    day 2: 100042 km     <- you already knew it was ~100000
    day 3: 100089 km

Most of each number is "the same as yesterday". Delta encoding stores only the
CHANGE:

    day 1: 100000        <- the seed (one absolute value)
    day 2: +42
    day 3: +47

[100,102,105,106,110]  ->  [100, +2, +3, +1, +4]

The first value is stored absolutely (the seed); every later value is the
difference from its predecessor. This pays off enormously when consecutive
values are CLOSE (monotonic, or slowly drifting) - the deltas are small even
when the absolute values are huge. On noisy/random data it buys nothing.

Delta encoding is NOT compression by itself - it is a RESHAPING that makes
the data friendlier to a second step. That second step is usually a VARIABLE-
LENGTH integer codec (varint): small magnitudes take few bytes, so a stream
of tiny deltas shrinks dramatically. Hence the classic pipeline:

    values  ->  delta  ->  zigzag  ->  varint  ->  bytes

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  delta       : the difference value[i] - value[i-1]. Can be negative.
  seed        : the first value, stored absolutely so the chain can restart.
  monotonic   : strictly non-decreasing (or non-increasing). Timestamps, log
                sequence numbers, counters - deltas are all >= 0 (or all <= 0)
                and usually tiny. The sweet spot for delta encoding.
  slowly-varying: each value is close to the previous (small |delta|) even if
                the sign flips. Sensor readings, audio samples.
  zigzag      : a bijection that maps signed ints onto unsigned ints so that
                small-magnitude numbers (both signs) map to small unsigned
                values: 0->0, -1->1, 1->2, -2->3, 2->4, ...
                zigzag(n) = (n << 1) ^ (n >> 63)   (arithmetic shift, 64-bit)
  varint      : base-128 encoding, 7 payload bits per byte, top bit = "more".
                0..127 -> 1 byte; 128..16383 -> 2 bytes; etc. (protobuf / LEB128)
  LEB128      : Little-Endian Base 128 - the varint wire format.

==========================================================================
THE LINEAGE (where it shows up)
==========================================================================
  git packfile   : delta objects ("OBJ_OFS_DELTA"/"OBJ_REF_DELTA") store a
                   compressed diff against a base object. "copy hunk, add hunk".
  RDB / columnar : time-series & OLAP engines (Parquet DELTA_ENCODING,
                   InfluxDB, Apache Druid) delta-encode sorted columns.
  video codecs   : P-frames store motion-compensated DELTAS from the previous
                   frame ("predict the frame, encode the residual").
  protobuf/LEB128: the varint half - every gRPC/Protobuf int field uses it.
  Bitcoin/LevelDB/RocksDB SSTables: delta-encode sorted integer keys.

KEY FACTS (verified):
  delta_encode is its own inverse (delta_decode is a prefix sum / cumsum).
  zigzag is a lossless bijection Int64 <-> UInt64.
  varint(0..127)=1B, varint(128..16383)=2B, ..., varint(64-bit max)=10B max.
  best case (constant stream): n ints -> seed + (n-1) deltas of 0 -> 1 byte each.
  worst case (random): deltas as big as the values -> no win, even a slight loss.

==========================================================================
WHY DELTA + VARINT (not delta alone, not varint alone)
==========================================================================
  delta alone     : same number of values, same bit-width. No size change - it
                    only changes WHICH values are big. Pointless on its own.
  varint alone    : big absolute values still take many bytes, because varint
                    cares about MAGNITUDE, not adjacency.
  delta + varint  : delta makes the magnitudes SMALL (when data is smooth),
                    then varint rewards small magnitudes. The two compose.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE ALGORITHM - delta encode/decode (the core 4-liner)
# ============================================================================

def delta_encode(values: list) -> list:
    """[100,102,105,106,110] -> [100, 2, 3, 1, 4].

    First value kept absolute (the seed); rest are diffs from predecessor.
    Lossless, reversible. Returns the same number of values - delta encoding
    alone does NOT change the count, only the magnitudes."""
    if not values:
        return []
    out = [values[0]]
    for i in range(1, len(values)):
        out.append(values[i] - values[i - 1])
    return out


def delta_decode(deltas: list) -> list:
    """Inverse of delta_encode = a prefix sum (cumulative sum)."""
    if not deltas:
        return []
    out = [deltas[0]]
    acc = deltas[0]
    for d in deltas[1:]:
        acc += d
        out.append(acc)
    return out


# ============================================================================
# 2. ZIGZAG - lossless signed <-> unsigned bijection
# ============================================================================

def zigzag_encode(n: int) -> int:
    """Map signed int -> unsigned int so small magnitude -> small value.
       0->0, -1->1, 1->2, -2->3, 2->4, ...  (protobuf-style zigzag)."""
    return (n << 1) ^ (n >> 63)        # arithmetic shift sign-extends on 64-bit


def zigzag_decode(z: int) -> int:
    """Inverse of zigzag_encode."""
    return (z >> 1) ^ -(z & 1)


# ============================================================================
# 3. VARINT - base-128, 7 payload bits/byte (LEB128 / protobuf wire format)
# ============================================================================

def varint_encode(n: int) -> bytes:
    """Encode a NON-NEGATIVE int as base-128 varint bytes.
       Each byte: low 7 bits = payload, top bit = 1 if more bytes follow."""
    if n < 0:
        raise ValueError("varint_encode needs n >= 0 (zigzag first for signed)")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)        # set continuation bit
        else:
            out.append(b)
            return bytes(out)


def varint_decode(buf: bytes, pos: int = 0):
    """Decode one varint from buf at pos. Returns (value, new_pos)."""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def varint_len(n: int) -> int:
    """Number of bytes varint_encode(n) produces (n >= 0)."""
    if n == 0:
        return 1
    return (n.bit_length() + 6) // 7


# ============================================================================
# 4. THE FULL PIPELINE - values -> delta -> zigzag -> varint -> bytes
# ============================================================================

def delta_varint_encode(values: list) -> bytes:
    """Full pipeline. Returns the compressed byte string."""
    deltas = delta_encode(values)
    out = bytearray()
    for d in deltas:
        out += varint_encode(zigzag_encode(d))
    return bytes(out)


def delta_varint_decode(buf: bytes) -> list:
    """Inverse of delta_varint_encode."""
    deltas = []
    pos = 0
    while pos < len(buf):
        z, pos = varint_decode(buf, pos)
        deltas.append(zigzag_decode(z))
    return delta_decode(deltas)


def raw_fixed_width_size(values: list, width: int = 4) -> int:
    """Naive baseline: every value stored in `width` bytes (e.g. int32)."""
    return len(values) * width


# ============================================================================
# 5. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_signed(n: int) -> str:
    return f"{n:+d}" if n >= 0 else f"{n:d}"


# ----------------------------------------------------------------------------
# SECTION A: the algorithm - what delta encoding is + lineage
# ----------------------------------------------------------------------------

def section_algorithm():
    banner("SECTION A: the algorithm - store differences, not absolutes")
    print("absolute : [100, 102, 105, 106, 110]")
    print("delta    : [100,  +2,  +3,  +1,  +4]   <- seed, then diffs\n")
    print("The pipeline that makes it actually compress:\n")
    print("   values  ->  delta  ->  zigzag  ->  varint  ->  bytes")
    print("   [..]       small     unsigned   1..10B     compact\n")
    print("  delta   : value[i] - value[i-1]   (can be negative)")
    print("  zigzag  : signed -> unsigned so small |n| -> small unsigned")
    print("            0->0  -1->1  1->2  -2->3  2->4  ...")
    print("  varint  : 7 payload bits/byte, top bit = 'more bytes follow'")
    print("            0..127 = 1B, 128..16383 = 2B, ... (LEB128)\n")
    print("Lineage / where it lives:")
    print("  git packfile  - OBJ_OFS_DELTA: store diff against a base object.")
    print("  columnar OLAP - Parquet/Druid/InfluxDB delta-encode sorted columns.")
    print("  video codecs  - P-frames encode motion-compensated residuals.")
    print("  protobuf      - the varint half: every int field is LEB128.")
    print("  LevelDB/RocksDB/Bitcoin - delta-encode sorted integer keys.")


# ----------------------------------------------------------------------------
# SECTION B: encode/decode on the canonical example + roundtrip
# ----------------------------------------------------------------------------

def section_canonical():
    banner("SECTION B: encode/decode on the canonical example")
    values = [100, 102, 105, 106, 110]
    deltas = delta_encode(values)
    print(f"values = {values}\n")
    print(f"delta_encode -> {deltas}")
    print("             (seed = first value, rest are consecutive diffs)\n")
    # show each delta
    print("step-by-step:")
    for i, (v, d) in enumerate(zip(values, deltas)):
        if i == 0:
            print(f"  [{i}] {v:>4}  <- seed (absolute)")
        else:
            prev = values[i - 1]
            print(f"  [{i}] {v:>4}  <- {v} - {prev} = {fmt_signed(d)}")
    back = delta_decode(deltas)
    print(f"\ndelta_decode({deltas}) -> {back}")
    print(f"[check] roundtrip == original?  {back == values}\n")

    # zigzag walk on the deltas
    print("now zigzag the signed deltas (so varint can encode them unsigned):")
    zz = [zigzag_encode(d) for d in deltas]
    print("  zigzag: 0->0  -1->1  1->2  -2->3  2->4 ...\n")
    print(f"  deltas  = {deltas}")
    print(f"  zigzag  = {zz}")
    print(f"  decoded = {[zigzag_decode(z) for z in zz]}   <- inverse matches")
    print(f"[check] zigzag roundtrip?  "
          f"{[zigzag_decode(zigzag_encode(d)) for d in deltas] == deltas}")

    # varint on the canonical
    blob = delta_varint_encode(values)
    print(f"\nfull pipeline delta_varint_encode({values}) ->")
    print(f"  bytes   = {list(blob)}   ({len(blob)} bytes)")
    print(f"  vs raw  = {len(values)} ints x 4 bytes = {raw_fixed_width_size(values)} bytes")
    back2 = delta_varint_decode(blob)
    print(f"[check] full pipeline roundtrip?  {back2 == values}")


# ----------------------------------------------------------------------------
# SECTION C: compression ratio on time-series data
# ----------------------------------------------------------------------------

def section_ratio():
    banner("SECTION C: compression ratio - delta + varint vs raw fixed-width")
    print("Three workloads. Watch how delta wins on SMOOTH data and dies on "
          "RANDOM data.\n")
    print("| workload (n=64)              | raw int32 | delta+varint | ratio  | "
          "verdict            |")
    print("|------------------------------|-----------|--------------|--------|"
          "--------------------|")
    cases = [
        ("monotonic timestamps (1s apart)",
         [1_700_000_000 + i for i in range(64)]),
        ("slowly-drifting sensor (small)",
         [1000 + ((i * 7) % 11) - 5 for i in range(64)]),
        ("uniform random 32-bit",
         [(i * 2654435761) & 0xFFFFFFFF for i in range(64)]),
    ]
    for name, vals in cases:
        raw = raw_fixed_width_size(vals, 4)
        comp = len(delta_varint_encode(vals))
        ratio = comp / raw
        verdict = ("great" if ratio < 0.15 else
                   "good" if ratio < 0.40 else
                   "no win" if ratio < 0.90 else "WORSE than raw")
        print(f"| {name:<28} | {raw:>9} | {comp:>12} | {ratio:.3f}  | "
              f"{verdict:<18} |")
    print("\nReading the table:")
    print("  monotonic : deltas are all +1 -> varint 1 byte each. The huge")
    print("               absolute values (1.7 billion!) collapse to 1 byte.")
    print("  drifting  : deltas stay small in magnitude (|-5|..|5|) -> 1 byte.")
    print("  random    : deltas are as big as the values -> varint grows to")
    print("               5 bytes, so it can actually LOSE to fixed int32.\n")

    # zoom into the monotonic case: show the deltas explicitly
    mono = [1_700_000_000 + i for i in range(8)]
    print("Zoom into monotonic (first 8 of 64):")
    print(f"  values = {mono}")
    print(f"  deltas = {delta_encode(mono)}   <- every delta is just +1")
    print(f"  one value raw = 4 bytes ; one delta varint = "
          f"{varint_len(zigzag_encode(1))} byte")
    print("  => absolute magnitude is irrelevant; only the STEP size matters.")


# ----------------------------------------------------------------------------
# SECTION D: applications deep-dive (git, time-series, P-frames) + monotonic vs random
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION D: applications - git deltas, time-series, video P-frames")
    print("1) git packfile deltas (OBJ_OFS_DELTA)\n")
    print("   A git 'delta' object is a stream of instructions against a BASE:")
    print("     COPY  <offset> <len>   - copy len bytes from base+offset")
    print("     ADD   <bytes...>       - insert literal new bytes")
    print("   The <offset> and <len> themselves are varint-delta-encoded, so a")
    print("   nearby copy is cheap. This is how a 1-line commit to a 1 MB file")
    print("   becomes a ~100 byte delta object in .git/objects/pack/.\n")
    # simulate: same big blob, one small change
    big = list(range(1000))
    big2 = big.copy()
    big2[500] += 1000                 # one value bumped far from its neighbours
    enc1 = delta_varint_encode(big)
    enc2 = delta_varint_encode(big2)
    print("   demo: 1000-int blob vs same blob with one value bumped @500")
    print(f"         blob        delta+varint = {len(enc1)} bytes")
    print(f"         blob+1bump  delta+varint = {len(enc2)} bytes  "
          f"(+{len(enc2)-len(enc1)} bytes: only deltas[500],[501] grew)")
    print("   => a localized edit touches only the 1-2 deltas around it, which")
    print("      is exactly why git stores the delta instead of the new blob.\n")

    print("2) time-series databases (monotonic timestamps)\n")
    print("   Timestamps arrive in order: 1.7B, 1.7B+1, 1.7B+2, ... Storing each")
    print("   as int64 = 8 bytes/point. Delta-encode -> all deltas are +1 ->")
    print("   1 byte/point. That is an 8x reduction on the timestamp column")
    print("   BEFORE any general-purpose compression. Parquet calls this")
    print("   DELTA_ENCODING; InfluxDB/QuestDB do the same on their time index.\n")

    print("3) video codecs - P-frames (predict + encode the residual)\n")
    print("   A P-frame does NOT store pixels. It stores a MOTION-COMPENSATED")
    print("   DELTA from the previous frame: 'this 16x16 block moved (dx,dy) ->")
    print("   here are the small brightness corrections'. Most of the frame is")
    print("   nearly identical to the last, so the residual is mostly ~0 and")
    print("   compresses to almost nothing. This is delta encoding applied to")
    print("   2D image blocks over time. I-frames are the 'seeds'.\n")

    print("4) monotonic vs random - the whole game in one chart\n")
    mono = [1_700_000_000 + i for i in range(32)]
    rand = [(i * 2654435761) & 0xFFFFFFFF for i in range(32)]
    for label, vals in [("monotonic", mono), ("random   ", rand)]:
        raw = raw_fixed_width_size(vals, 4)
        comp = len(delta_varint_encode(vals))
        bar_len = int(comp / raw * 40)
        print(f"  {label}: raw={raw}B  delta+varint={comp}B  "
              f"[{'#' * bar_len}{'.' * (40 - bar_len)}] {comp/raw:.2f}x")
    print("\n  monotonic: tiny deltas -> tiny varints -> tiny file.")
    print("  random   : deltas as big as values -> no win. Delta encoding is a")
    print("             BET, and the bet is 'consecutive values are close'.")


# ----------------------------------------------------------------------------
# SECTION E: gold pin for delta_encoding.html
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION E: GOLD pin for delta_encoding.html")
    values = [100, 102, 105, 106, 110]
    deltas = delta_encode(values)
    blob = delta_varint_encode(values)
    print(f"input  = {values}")
    print(f"deltas = {deltas}")
    print(f"zigzag = {[zigzag_encode(d) for d in deltas]}")
    print(f"varint bytes = {list(blob)}   ({len(blob)} bytes total)")
    print(f"raw int32    = {raw_fixed_width_size(values)} bytes\n")

    # pin scalars for the HTML
    print("GOLD values (pinned, recomputed live in JS):")
    print(f"  delta array        = {deltas}")
    print(f"  zigzag array       = {[zigzag_encode(d) for d in deltas]}")
    print(f"  varint byte total  = {len(blob)}")
    print(f"  first byte (seed)  = {blob[0]}   (varint of zigzag(100) = {zigzag_encode(100)})")
    # monotonic gold too
    mono = [1_700_000_000 + i for i in range(64)]
    mono_blob = delta_varint_encode(mono)
    print(f"  monotonic 64-pt    : deltas all +1 -> {len(mono_blob)} bytes "
          f"(raw int32 = {raw_fixed_width_size(mono)})\n")
    # self-consistency
    assert delta_decode(deltas) == values
    assert delta_varint_decode(blob) == values
    assert delta_varint_decode(mono_blob) == mono
    print("[check] gold reproduces from delta_*():  OK")
    print(f"[check] canonical roundtrip exact?  {delta_varint_decode(blob) == values}")
    print(f"[check] monotonic roundtrip exact?  "
          f"{delta_varint_decode(mono_blob) == mono}")


# ============================================================================
# main
# ============================================================================

def main():
    print("delta_encoding.py - reference impl. All numbers below feed "
          "DELTA_ENCODING.md.")
    print("python stdlib only. Deterministic.\n")

    section_algorithm()
    section_canonical()
    section_ratio()
    section_applications()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
