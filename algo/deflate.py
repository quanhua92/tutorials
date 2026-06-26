"""
deflate.py - Reference implementation of DEFLATE (Deutsch 1996, RFC 1951).

This is the single source of truth that DEFLATE.md is built from. Every number,
table, and worked example in DEFLATE.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python deflate.py

==========================================================================
THE INTUITION (read this first) - the two-pass factory
==========================================================================
DEFLATE squeezes a file in TWO passes, each undoing a different kind of waste:

  Pass 1 (LZ77)   : kills REPETITION.  Scans for "I already said this!" and
                    replaces the second copy with a back-reference
                    (distance, length) = "go back D bytes, copy L bytes".
                    "the rain ... the rain" -> "the rain ... <back 9, copy 8>".

  Pass 2 (Huffman): kills FREQUENCY skew. Some bytes/symbols appear far more
                    often than others. Give the common ones SHORT codes and the
                    rare ones LONG codes (like Morse giving 'E' one dot).

LZ77 first, Huffman second - that order is fixed, because Huffman codes the
SYMBOLS that LZ77 emits (literal bytes + length/distance codes). Reversing the
order makes no sense: you cannot Huffman-code a symbol stream that does not
exist yet.

The wrapping:
  gzip = DEFLATE + a gzip header/trailer (RFC 1952).
  zlib  = DEFLATE + a zlib header/trailer (RFC 1950).
  Both use the IDENTICAL DEFLATE body - only the bookends differ.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  literal       : a raw byte, emitted by LZ77 when no good match was found.
  back-reference: LZ77's "copy from the past" token = (distance, length).
  distance (D)  : how far back in the output to copy from. 1..32768.
  length  (L)   : how many bytes to copy. 3..258 (matches shorter than 3 are
                  not worth it - the token would cost more than 3 literal bytes).
  sliding window: LZ77 only looks back up to 32 KiB (32768 bytes). Older data
                  "falls out" of the window and can no longer be referenced.
  symbol        : the unit Huffman codes. DEFLATE has TWO alphabets:
                    - literal/length: 0..255 (literal bytes) + 256 (end) +
                      257..285 (length codes).
                    - distance: 0..29 (distance codes).
  Huffman code  : a variable-length, prefix-free binary string per symbol.
                  Common symbol -> short code; rare symbol -> long code.
  prefix-free   : no code is the start of another, so the decoder can read
                  bit-by-bit and know exactly where each code ends.
  extra bits    : length/distance codes encode a RANGE; the extra bits pick the
                  exact value inside that range (RFC 1951 tables).

==========================================================================
THE LINEAGE (papers / RFCs)
==========================================================================
  LZ77   (Ziv-Lempel 1977, "A Universal Algorithm for Sequential Data
          Compression", IEEE IT 23(3)) : the back-reference idea.
  Huffman (Huffman 1952, "A Method for the Construction of Minimum-Redundancy
          Codes") : optimal prefix-free codes from symbol frequencies.
  DEFLATE (Deutsch 1996, RFC 1951) : LZ77 + Huffman, frozen into a format.
  gzip   (Deutsch 1996, RFC 1952) : DEFLATE body + gzip header/trailer.
  zlib   (Deutsch 1996, RFC 1950) : DEFLATE body + zlib header/trailer.

KEY FACTS (all verified against RFC 1951):
  window            = 32768 bytes (2^15)
  min match length  = 3      max match length = 258
  literal/length alphabet = 0..285  (286 symbols)
  distance alphabet       = 0..29   (30 symbols)
  length codes 257..285 use the LENGTH_BASE / LENGTH_EXTRA tables (Section C).
  distance codes 0..29  use the DIST_BASE / DIST_EXTRA tables (Section C).
  gzip body == zlib body == DEFLATE stream; only headers/trailers differ.

BIT-PACKING NOTE (important, honest caveat):
  Real DEFLATE packs Huffman codes high-bit-first but length/distance extra
  bits low-bit-first, and packs bits into bytes low-bit-first (RFC 1951 §3.1.1).
  That mixed-endian packing is fiddly and obscures the algorithm. This file
  packs EVERY field high-bit-first into a plain bit-string so the pipeline is
  readable, and stores the Huffman trees alongside the stream (instead of the
  real "dynamic Huffman header"). The ALGORITHMS - LZ77 match finding, Huffman
  code construction, and the RFC length/distance code tables - are faithful.
  The output is therefore NOT byte-identical to gzip, but the compression
  RATIO is representative, and the round-trip is exact (Section D gold check).
"""

from __future__ import annotations

import heapq
import zlib

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# RFC 1951 constants (Section 3.2.5). Verified against the RFC text.
# ----------------------------------------------------------------------------
WINDOW = 32768          # 32 KiB sliding window
MIN_MATCH = 3
MAX_MATCH = 258

# Length codes 257..285 : base length and number of extra bits.
LENGTH_BASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35,
               43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258]
LENGTH_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3,
                4, 4, 4, 4, 5, 5, 5, 5, 0]

# Distance codes 0..29 : base distance and number of extra bits.
DIST_BASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257,
             385, 513, 769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289,
             16385, 24577]
DIST_EXTRA = [0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8,
              9, 9, 10, 10, 11, 11, 12, 12, 13, 13]

# Cap hash-chain search length so big inputs stay fast (zlib does the same
# with `max_chain`; the algorithm is unaffected, only exhaustive-ness).
MAX_CHAIN = 256


# ============================================================================
# 1. PASS 1 - LZ77 (back-references kill repetition)
# ============================================================================

def lz77_compress(data: bytes,
                  window: int = WINDOW,
                  min_match: int = MIN_MATCH,
                  max_match: int = MAX_MATCH) -> list:
    """Greedy longest-match LZ77 with a hash-chain accelerator.

    Returns a token list. Each token is either:
        ('lit', byte_value)                  - a literal byte
        ('match', length, distance)          - a back-reference
    Deterministic: longest match wins; ties broken by SMALLEST distance
    (smaller distance = shorter extra bits, and the copy is closer).
    """
    tokens = []
    n = len(data)
    i = 0
    head = {}            # 3-byte hash -> list of recent positions (the chain)
    while i < n:
        best_len = 0
        best_dist = 0
        if i + min_match <= n:
            key = bytes(data[i:i + 3])
            chain = head.get(key, [])
            limit = i - window
            checked = 0
            for pos in reversed(chain):
                if pos < limit or checked >= MAX_CHAIN:
                    break
                checked += 1
                # extend the match (may run past `pos`, overlapping copies are
                # legal and even common - e.g. run-length patterns like "aaaa").
                max_l = min(max_match, n - i)
                length = 0
                while length < max_l and data[pos + length] == data[i + length]:
                    length += 1
                if length > best_len or (length == best_len and (i - pos) < best_dist):
                    best_len = length
                    best_dist = i - pos
                    if length >= max_l:
                        break
            head.setdefault(key, []).append(i)
        if best_len >= min_match:
            tokens.append(('match', best_len, best_dist))
            # hash the bytes we skip over, so later positions can match them.
            for j in range(1, best_len):
                p = i + j
                if p + 3 <= n:
                    head.setdefault(bytes(data[p:p + 3]), []).append(p)
            i += best_len
        else:
            tokens.append(('lit', data[i]))
            i += 1
    return tokens


def lz77_decompress(tokens: list) -> bytes:
    """Inverse of lz77_compress. Overlapping copies (run-length) handled
    naturally because we copy byte-by-byte from the growing output."""
    out = bytearray()
    for tok in tokens:
        if tok[0] == 'lit':
            out.append(tok[1])
        else:
            _, length, distance = tok
            start = len(out) - distance
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)


# ============================================================================
# 2. LENGTH / DISTANCE CODE TABLES (RFC 1951)
# ============================================================================

def length_symbol(length: int):
    """Map a match length (3..258) to (symbol 257..285, extra_bits, extra_val)."""
    for i in range(len(LENGTH_BASE) - 1, -1, -1):
        if LENGTH_BASE[i] <= length:
            return 257 + i, LENGTH_EXTRA[i], length - LENGTH_BASE[i]
    raise ValueError(f"length {length} out of range")


def distance_symbol(distance: int):
    """Map a distance (1..32768) to (symbol 0..29, extra_bits, extra_val)."""
    for i in range(len(DIST_BASE) - 1, -1, -1):
        if DIST_BASE[i] <= distance:
            return i, DIST_EXTRA[i], distance - DIST_BASE[i]
    raise ValueError(f"distance {distance} out of range")


def bits_msb(value: int, width: int) -> str:
    """Format `value` as a width-bit binary string, most-significant-bit first."""
    if width == 0:
        return ""
    return format(value & ((1 << width) - 1), f"0{width}b")


# ============================================================================
# 3. PASS 2 - HUFFMAN CODING (variable-length codes kill frequency skew)
# ============================================================================

def build_huffman_codes(freq: dict) -> dict:
    """Build optimal prefix-free Huffman codes from a {symbol: frequency} map.

    Returns {symbol: code_string}. Uses a counter in the heap tuple so ties
    never compare the (unorderable) node payloads. A single-symbol alphabet
    gets the code "0" (Huffman is degenerate for one symbol; RFC 1951 completes
    the tree explicitly, but for our bit-count purposes "0" suffices).
    """
    if not freq:
        return {}
    if len(freq) == 1:
        return {next(iter(freq)): "0"}
    counter = 0
    heap = []
    for sym, f in freq.items():
        heapq.heappush(heap, (f, counter, ("leaf", sym)))
        counter += 1
    while len(heap) > 1:
        f1, _, n1 = heapq.heappop(heap)
        f2, _, n2 = heapq.heappop(heap)
        heapq.heappush(heap, (f1 + f2, counter, ("node", n1, n2)))
        counter += 1
    root = heap[0][2]
    codes = {}

    def walk(node, prefix):
        if node[0] == "leaf":
            codes[node[1]] = prefix
            return
        walk(node[1], prefix + "0")
        walk(node[2], prefix + "1")

    walk(root, "")
    return codes


def shannon_entropy_bits(freq: dict, total: int) -> float:
    """Theoretical lower bound on bits for this symbol distribution
    (sum of -p*log2(p)). Huffman gets within <1 bit/symbol of this."""
    import math
    return sum(f * (-math.log2(f / total)) for f in freq.values())


# ============================================================================
# 4. FULL DEFLATE ENCODE / DECODE (LZ77 + Huffman, RFC length/distance tables)
# ============================================================================

def deflate_encode(data: bytes):
    """Run the full two-pass pipeline.

    Returns dict with: tokens, ll_codes, dist_codes, bitstring, stats.
    All fields high-bit-first packing (see module docstring caveat)."""
    tokens = lz77_compress(data)
    ll_freq = {}      # literal/length symbol -> count (0..285)
    dist_freq = {}    # distance symbol -> count (0..29)
    for tok in tokens:
        if tok[0] == 'lit':
            ll_freq[tok[1]] = ll_freq.get(tok[1], 0) + 1
        else:
            lsym, _, _ = length_symbol(tok[1])
            ll_freq[lsym] = ll_freq.get(lsym, 0) + 1
            dsym, _, _ = distance_symbol(tok[2])
            dist_freq[dsym] = dist_freq.get(dsym, 0) + 1
    ll_freq[256] = ll_freq.get(256, 0) + 1          # end-of-block symbol
    ll_codes = build_huffman_codes(ll_freq)
    dist_codes = build_huffman_codes(dist_freq)

    bits = []
    n_match = n_lit = 0
    for tok in tokens:
        if tok[0] == 'lit':
            bits.append(ll_codes[tok[1]])
            n_lit += 1
        else:
            _, length, distance = tok
            lsym, lextra, lval = length_symbol(length)
            bits.append(ll_codes[lsym])
            bits.append(bits_msb(lval, lextra))
            dsym, dextra, dval = distance_symbol(distance)
            bits.append(dist_codes[dsym])
            bits.append(bits_msb(dval, dextra))
            n_match += 1
    bits.append(ll_codes[256])                      # end-of-block
    bitstring = "".join(bits)
    return {
        "tokens": tokens,
        "ll_codes": ll_codes,
        "dist_codes": dist_codes,
        "bitstring": bitstring,
        "ll_freq": ll_freq,
        "dist_freq": dist_freq,
        "n_lit": n_lit,
        "n_match": n_match,
    }


def deflate_decode(bitstring: str, ll_codes: dict, dist_codes: dict) -> bytes:
    """Inverse of deflate_encode. Walks the bitstream, inverting the Huffman
    trees (prefix-free -> unique decode), then expands back-references."""
    ll_dec = {v: k for k, v in ll_codes.items()}
    dist_dec = {v: k for k, v in dist_codes.items()}
    out = bytearray()
    pos = 0
    n = len(bitstring)

    def read_code(dec):
        nonlocal pos
        cur = ""
        while pos < n:
            cur += bitstring[pos]
            pos += 1
            if cur in dec:
                return dec[cur]
        raise ValueError("ran off the end of the bitstream without a symbol")

    def read_extra(width):
        nonlocal pos
        val = 0
        for _ in range(width):
            val = (val << 1) | (1 if bitstring[pos] == '1' else 0)
            pos += 1
        return val

    while True:
        sym = read_code(ll_dec)
        if sym == 256:
            break
        if sym < 256:
            out.append(sym)
        else:
            i = sym - 257
            length = LENGTH_BASE[i] + read_extra(LENGTH_EXTRA[i])
            dsym = read_code(dist_dec)
            j = dsym
            distance = DIST_BASE[j] + read_extra(DIST_EXTRA[j])
            start = len(out) - distance
            for k in range(length):
                out.append(out[start + k])
    return bytes(out)


# ============================================================================
# 5. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def tok_str(tok):
    if tok[0] == 'lit':
        b = tok[1]
        ch = chr(b) if 32 <= b < 127 else '.'
        return f"lit({ch}={b:3d})"
    return f"match(len={tok[1]:>3}, dist={tok[2]:>3})"


# ----------------------------------------------------------------------------
# SECTION A: the two-pass pipeline + lineage
# ----------------------------------------------------------------------------

def section_pipeline():
    banner("SECTION A: the two-pass pipeline  (LZ77 -> Huffman)")
    print("DEFLATE (Deutsch 1996, RFC 1951) squeezes data in two passes:\n")
    print("  raw bytes")
    print("     |  Pass 1: LZ77  -- kills REPETITION")
    print("     v            (replace repeated spans with (distance,length))")
    print("  token stream  { literals } + { back-references }")
    print("     |  Pass 2: Huffman -- kills FREQUENCY skew")
    print("     v            (short codes for common symbols, long for rare)")
    print("  bit-string   (variable-length prefix-free codes + extra bits)\n")
    print("The order is fixed: Huffman codes the SYMBOLS LZ77 emits, so LZ77")
    print("must run first. Then a wrapper adds bookends:\n")
    print("| format | body            | header/trailer          | RFC  |")
    print("|--------|-----------------|-------------------------|------|")
    print("| DEFLATE| DEFLATE stream  | (none)                  | 1951 |")
    print("| zlib   | DEFLATE stream  | 2-byte zlib hdr + adler | 1950 |")
    print("| gzip   | DEFLATE stream  | gzip hdr + crc32/size   | 1952 |")
    print("\n=> gzip body == zlib body == DEFLATE stream. Only bookends differ.")
    print("\nLineage:")
    print("  LZ77    Ziv-Lempel 1977  - the back-reference idea.")
    print("  Huffman Huffman 1952    - optimal prefix-free codes.")
    print("  DEFLATE Deutsch 1996    - LZ77 + Huffman, frozen as RFC 1951.")


# ----------------------------------------------------------------------------
# SECTION B: pass 1 - LZ77 on the canonical tiny example
# ----------------------------------------------------------------------------

def section_lz77():
    banner("SECTION B: pass 1 - LZ77 encode/decode (back-references)")
    data = b"TOBEORNOTTOBEORTOBEORNOT"
    print(f"data = {data.decode()!r}   ({len(data)} bytes)\n")
    tokens = lz77_compress(data)
    print("Tokens (greedy longest-match; tie -> smallest distance):")
    for k, tok in enumerate(tokens):
        print(f"  [{k:>2}] {tok_str(tok)}")
    n_lit = sum(1 for t in tokens if t[0] == 'lit')
    n_match = sum(1 for t in tokens if t[0] == 'match')
    bytes_copied = sum(t[1] for t in tokens if t[0] == 'match')
    print(f"\nliterals: {n_lit}   back-refs: {n_match}   "
          f"bytes covered by back-refs: {bytes_copied} / {len(data)}")
    roundtrip = lz77_decompress(tokens)
    ok = roundtrip == data
    print(f"[check] LZ77 roundtrip == original?  {ok}")
    print("\nReading the tokens: the first 'TOBEORNOT' (9 bytes) is all literals.")
    print("From then on, every recurrence is a back-reference pointing into the")
    print("already-emitted output. 'TOB' at position 9 says 'go back 9, copy 3'.")
    print("DEFLATE only emits a match when length >= 3 (shorter isn't worth it).")

    # show the classic overlap trick (run-length via overlapping copy)
    print("\nOverlap demo (run-length via overlapping back-reference):")
    run = b"aaaaaaaa"            # 8 a's
    rtoks = lz77_compress(run)
    print(f"  {run.decode()!r} -> {rtoks}")
    print("  the match (dist=1,len=7) copies 1 byte ago, 7 times -> the output")
    print("  grows AS it copies, so 'a' multiplies into 'aaaaaaa'. This is how")
    print("  LZ77 expresses runs far longer than the window-less literal would.")


# ----------------------------------------------------------------------------
# SECTION C: pass 2 - Huffman coding + RFC length/distance tables
# ----------------------------------------------------------------------------

def section_huffman():
    banner("SECTION C: pass 2 - Huffman coding (entropy) + RFC code tables")
    # a frequency-skewed mini alphabet to show the short/long code split
    freq = {'E': 12, 'A': 8, 'T': 5, 'X': 2, 'Z': 1}
    codes = build_huffman_codes(freq)
    total = sum(freq.values())
    print(f"Symbol frequencies (total {total}): {freq}\n")
    print("| symbol | freq | code    | bits | freq*bits |")
    print("|--------|------|---------|------|-----------|")
    total_bits = 0
    for sym in sorted(codes, key=lambda s: (-freq[s], s)):
        c = codes[sym]
        total_bits += freq[sym] * len(c)
        print(f"| {sym:<6} | {freq[sym]:<4} | {c:<7} | {len(c):<4} | "
              f"{freq[sym]*len(c):<9} |")
    ent = shannon_entropy_bits(freq, total)
    avg = total_bits / total
    print(f"\ntotal Huffman bits = {total_bits}   avg bits/symbol = {avg:.3f}")
    print(f"Shannon entropy lower bound = {ent:.3f} bits "
          f"(Huffman is within {avg - ent/total:.3f} bits/symbol of optimal)")
    print("[check] codes are prefix-free?  "
          f"{all(not any(c2 != c1 and c2.startswith(c1) for c2 in codes.values()) for c1 in codes.values())}")

    # RFC length/distance tables sanity
    print("\nRFC 1951 code tables (verified against the RFC):")
    print("  length codes 257..285: 29 entries, base 3..258, extra 0..5 bits")
    print("  distance codes 0..29:  30 entries, base 1..24577, extra 0..13 bits")
    # show a few length/distance symbol mappings
    print("\n  sample length_symbol() mappings:")
    for L in [3, 4, 10, 11, 12, 258]:
        sym, ex, val = length_symbol(L)
        print(f"    length {L:>3} -> symbol {sym}, {ex} extra bit(s), extra_val={val}")
    print("  sample distance_symbol() mappings:")
    for D in [1, 2, 5, 6, 32768]:
        sym, ex, val = distance_symbol(D)
        print(f"    dist   {D:>5} -> symbol {sym}, {ex} extra bit(s), extra_val={val}")
    # gold: pin code for the most frequent symbol
    gold_E = codes['E']
    print(f"\nGOLD: Huffman code for 'E' (most frequent) = {gold_E!r}  "
          f"(pinned for deflate.html)")


# ----------------------------------------------------------------------------
# SECTION D: full DEFLATE encode/decode + compression ratio
# ----------------------------------------------------------------------------

def section_roundtrip():
    banner("SECTION D: full DEFLATE encode/decode + compression ratio")
    # a realistic, repetitive text block
    base = ("the rain in spain falls mainly on the plain. "
            "the rain in spain falls mainly on the plain. ")
    data = (base * 4).encode()
    print(f"input: {len(data)} bytes "
          f"({base[:40]!r}... x4)\n")
    enc = deflate_encode(data)
    bits = len(enc["bitstring"])
    out_bytes = (bits + 7) // 8
    ratio = out_bytes / len(data)
    print(f"Pass 1 LZ77 : literals={enc['n_lit']}, back-refs={enc['n_match']}")
    print(f"             tokens total = {len(enc['tokens'])}")
    ll_syms = len(enc["ll_freq"])
    dist_syms = len(enc["dist_freq"])
    print(f"Pass 2 Huff : lit/len alphabet used = {ll_syms} symbols, "
          f"dist alphabet used = {dist_syms} symbols")
    print(f"\ncompressed bit-string length = {bits} bits = {out_bytes} bytes "
          f"(+{bits % 7 if bits % 7 else 0} pad bits -> next byte)")
    print(f"raw size       = {len(data)} bytes")
    print(f"DEFLATE size   = {out_bytes} bytes")
    print(f"ratio          = {ratio:.3f}  ({(1-ratio)*100:.1f}% smaller)")
    # compare with real zlib (same family, real bit-packing + headers)
    zlib_size = len(zlib.compress(data, 9))
    print(f"real zlib -9   = {zlib_size} bytes "
          f"(reference; our pedagogical pack is in the same ballpark)\n")
    # exact roundtrip
    decoded = deflate_decode(enc["bitstring"], enc["ll_codes"], enc["dist_codes"])
    ok = decoded == data
    print(f"[check] DEFLATE roundtrip == original ({len(data)} bytes)?  {ok}")
    # also roundtrip the tiny example
    tiny = b"TOBEORNOTTOBEORTOBEORNOT"
    enc2 = deflate_encode(tiny)
    dec2 = deflate_decode(enc2["bitstring"], enc2["ll_codes"], enc2["dist_codes"])
    print(f"[check] tiny roundtrip == original?  {dec2 == tiny}\n")

    # show the first ~12 tokens' actual Huffman codes flowing into the bitstream
    print("First tokens -> their Huffman codes (lit/len + extra + dist + extra):")
    shown = 0
    for tok in enc["tokens"][:12]:
        if tok[0] == 'lit':
            code = enc["ll_codes"][tok[1]]
            print(f"  lit {chr(tok[1])!r:>5} -> {code}")
        else:
            _, length, distance = tok
            lsym, lex, lval = length_symbol(length)
            dsym, dex, dval = distance_symbol(distance)
            lc = enc["ll_codes"][lsym]
            dc = enc["dist_codes"][dsym]
            print(f"  match L={length} D={distance}: "
                  f"len[{lc}]+{bits_msb(lval,lex)!r}  "
                  f"dist[{dc}]+{bits_msb(dval,dex)!r}")
        shown += 1
    print(f"  ... ({len(enc['tokens']) - shown} more tokens) then end-of-block(256)")


# ----------------------------------------------------------------------------
# SECTION E: applications + gold pin
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION E: applications + GOLD pin for deflate.html")
    print("Where DEFLATE / its halves live in the wild:\n")
    print("| use                       | which half          | note                |")
    print("|---------------------------|---------------------|---------------------|")
    print("| .gz / gzip(1)             | DEFLATE (+ gzip hdr)| RFC 1952            |")
    print("| PNG images                | DEFLATE (zlib hdr)  | on filtered scanline|")
    print("| HTTP gzip content-encoding| DEFLATE (+ gzip hdr)| transparent to app  |")
    print("| ZIP / jar / odt / xlsx    | DEFLATE (per-entry) | the 'deflate' method|")
    print("| HTTP/2 HPACK (history)    | Huffman only        | static Huffman tbls |")
    print("| git packfile (loose)      | zlib(DEFLATE)       | one blob per object |")
    print("| kernel zswap / zram        | DEFLATE (or LZ4)    | in-RAM compression  |")
    print("\nThe split tells the story: LZ77 alone wins on repetition, Huffman")
    print("alone wins on skew; DEFLATE stacks them so BOTH kinds of waste die.")

    # GOLD pin: tiny example, recompute and pin several scalars for the HTML.
    data = b"TOBEORNOTTOBEORTOBEORNOT"
    enc = deflate_encode(data)
    bits = len(enc["bitstring"])
    out_bytes = (bits + 7) // 8
    n_match = enc["n_match"]
    print("\nGOLD values (pinned for deflate.html, recomputed live in JS):")
    print(f"  input               = {data.decode()!r}")
    print(f"  LZ77 token count    = {len(enc['tokens'])}")
    print(f"  LZ77 back-ref count = {n_match}")
    print(f"  Huffman bits        = {bits}")
    print(f"  DEFLATE bytes       = {out_bytes}")
    # self-consistency: re-run must reproduce exactly
    enc2 = deflate_encode(data)
    assert len(enc2["tokens"]) == len(enc["tokens"])
    assert len(enc2["bitstring"]) == bits
    print("[check] gold reproduces from deflate_encode():  OK")
    print(f"[check] DEFLATE roundtrip exact?  "
          f"{deflate_decode(enc['bitstring'], enc['ll_codes'], enc['dist_codes']) == data}")


# ============================================================================
# main
# ============================================================================

def main():
    print("deflate.py - reference impl. All numbers below feed DEFLATE.md.")
    print("python stdlib only (heapq, zlib). Deterministic.\n")

    section_pipeline()
    section_lz77()
    section_huffman()
    section_roundtrip()
    section_applications()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
