"""
rle.py - Reference implementation of Run-Length Encoding (RLE).

This is the single source of truth that RLE.md is built from. Every number,
table, and worked example in RLE.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python rle.py

==========================================================================
THE INTUITION (read this first) — the photocopier tray
==========================================================================
Imagine a photocopier tray holding 100 copies of the SAME page. Scanning all
100 is a waste; instead you write "100 x (this page)" on one sticky note.
The note and the stack carry the same information — but the note is ~100x
smaller. That is the whole of RLE.

A "run" is a maximal streak of identical symbols. RLE replaces each streak
with a (count, symbol) TOKEN. No probability model, no tree, no
transformation — just counting.

  * ENCODE : walk the input; whenever the symbol changes (or the run hits the
             count cap 255), emit (count, symbol) and start a new run.
  * DECODE : read (count, symbol) pairs and emit `count` copies of `symbol`.

==========================================================================
WHEN IT WORKS / WHEN IT FAILS (the single most important fact)
==========================================================================
RLE only compresses REPETITIVE data. The instant the symbols alternate
(ABABAB...), every run has length 1, so the "compressed" form is TWICE the
input — a 2x EXPANSION. This is why RLE is used on data known to be
run-heavy: fax scans (long white-pixel runs), BMP/PCX images, the final
zero-run stage of JPEG. It is essentially useless on natural text or random
data, where Huffman or LZW take over. 🔗 See HUFFMAN.md for the second layer.

==========================================================================
PLAIN-ENGLISH GLOSSARY
==========================================================================
  symbol     : one element of the input. Here, one character (ASCII). In a
               fax, one black-or-white pixel. In JPEG, one DCT coefficient.
  run        : a maximal block of the SAME symbol in a row. "AAAAA" is one
               run of length 5; "ABABAB" is six runs of length 1.
  token      : the (count, symbol) pair emitted per run. Count is one byte,
               so the longest single run encodable is 255; longer runs split
               into multiple tokens.
  payload    : the sequence of tokens — "the compressed form".
  ratio      : bits_out / bits_in. < 1 means we saved space; > 1 = bloated.

==========================================================================
HISTORY
==========================================================================
  RLE predates computers — it is essentially a notation, not an algorithm.
  - BMP/PCX  : "BI_RLE8" / "BI_RLE4" encoder (Microsoft, 1985+).
  - ITU T.30 : fax Group 3/4 (1980s) — long white runs compress hard.
  - JPEG     : the final AC stage run-length-encodes zero coefficients
               ("ZRL" = a block of 16 zeros) before Huffman.
  - DEFLATE (gzip, PNG) does NOT use RLE alone; it pairs LZ77+Huffman to
               catch both repetition and symbol-frequency skew.

KEY FORMULAS (all asserted in code):
    tokens   = [ (len, sym) for each maximal run, splitting at len=255 ]
    bits_in  = len(input) * 8              (one byte per ASCII char)
    bits_out = len(tokens) * 16            (one count byte + one symbol byte)
    ratio    = bits_out / bits_in          (< 1 = good)
    roundtrip: rle_decode(rle_encode(x)) == x   for all x   (verified §A)
"""

from __future__ import annotations

BANNER = "=" * 72
MAX_RUN = 255  # one byte holds counts 0..255


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code RLE.md walks through)
# ============================================================================

def rle_encode(data: str) -> list[tuple[int, str]]:
    """Encode a string into a list of (count, symbol) tokens.

    Walks the input, emitting a token whenever the symbol changes OR the run
    reaches the MAX_RUN cap (255). The cap exists because in real RLE the
    count is one byte — runs longer than 255 split into multiple tokens
    (see Section B).

    >>> rle_encode("AAAAABBBCC")
    [(5, 'A'), (3, 'B'), (2, 'C')]
    """
    if not data:
        return []
    tokens: list[tuple[int, str]] = []
    current = data[0]
    count = 1
    for ch in data[1:]:
        if ch == current and count < MAX_RUN:
            count += 1
        else:
            tokens.append((count, current))
            current = ch
            count = 1
    tokens.append((count, current))
    return tokens


def rle_decode(tokens: list[tuple[int, str]]) -> str:
    """Decode tokens back to the original string.

    Inverse of rle_encode: each token (count, symbol) -> symbol * count.
    Round-trip rle_decode(rle_encode(x)) == x for all x (verified §A).
    """
    return "".join(symbol * count for count, symbol in tokens)


def to_text(tokens: list[tuple[int, str]]) -> str:
    """Human-readable '5A3B2C' display form: count-digit then symbol.

    NOTE: this is the DISPLAY form, NOT the wire format. The wire format is
    a count byte + symbol byte (16 bits per token), reported in §C. The text
    form is ambiguous once counts hit double digits ('12A' could be 12 A's
    or 1-of-'2' then 1-of-'A'); it is for teaching only.
    """
    return "".join(f"{c}{s}" for c, s in tokens)


def compression_ratio(data: str, tokens: list[tuple[int, str]]) -> float:
    """bits_out / bits_in. <1 = we saved space, >1 = we bloated.

    Wire format: each token is one count byte + one symbol byte = 16 bits.
    Input: one byte per ASCII char = 8 bits per symbol.
    """
    bits_in = len(data) * 8
    bits_out = len(tokens) * 16
    return bits_out / bits_in if bits_in else 1.0


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: encode + decode, the basic mechanics (tiny worked example)
# ----------------------------------------------------------------------------

def section_basics():
    banner("SECTION A: encode + decode  (the tiny worked example)")
    s = "AAAAABBBCC"
    print(f'input           = "{s}"   (len = {len(s)})\n')
    toks = rle_encode(s)
    print("encode step-by-step (emit a token whenever the symbol changes):")
    print("  scan A A A A A -> run of 5 A's -> emit (5, 'A')")
    print("  scan B B B     -> run of 3 B's -> emit (3, 'B')")
    print("  scan C C       -> run of 2 C's -> emit (2, 'C')\n")
    print(f"tokens (wire)   = {toks}")
    print(f"display form    = \"{to_text(toks)}\"   <- the textbook '5A3B2C'\n")
    dec = rle_decode(toks)
    print(f"decode(tokens)  = \"{dec}\"")
    ok = dec == s
    print(f"[check] round-trip decode(encode(x)) == x ?  {ok}")
    assert ok
    r = compression_ratio(s, toks)
    print(f"[check] ratio = bits_out/bits_in = {len(toks)*16}/{len(s)*8} "
          f"= {r:.3f}   (3 tokens x 16 bits = 48; 10 chars x 8 bits = 80)")
    print(f"        -> saved {(1 - r) * 100:.1f}% of the space "
          f"(48 bits vs 80 bits)")


# ----------------------------------------------------------------------------
# SECTION B: the 255-byte cap (runs longer than one byte must split)
# ----------------------------------------------------------------------------

def section_cap():
    banner("SECTION B: the 255-byte cap  (long runs split into chunks)")
    n = 300
    s = "A" * n
    print("A run longer than 255 cannot fit in one count byte, so it splits:\n")
    print(f'input  = "A" * {n}   (len = {n})\n')
    toks = rle_encode(s)
    print(f"tokens = {toks}")
    print("\nThe single run of 300 became TWO tokens: (255,'A') + (45,'A').")
    print("Each count still fits in one byte (<=255). The decoder concatenates")
    print("the runs, so decode(encode(x)) == x still holds.\n")
    dec = rle_decode(toks)
    print(f"[check] decode(encode({n} A's)) == {n} A's ?  {len(dec) == n}")
    assert dec == s
    # edge: exactly 255 stays one token
    s255 = "A" * 255
    t255 = rle_encode(s255)
    print(f"[check] encode('A'*255) -> one token?  {t255 == [(255, 'A')]}")
    assert t255 == [(255, "A")]
    # edge: exactly 256 splits into 255 + 1
    s256 = "A" * 256
    t256 = rle_encode(s256)
    print(f"[check] encode('A'*256) -> [(255,'A'),(1,'A')]?  "
          f"{t256 == [(255, 'A'), (1, 'A')]}")
    assert t256 == [(255, "A"), (1, "A")]
    print("\nThe MAX_RUN cap is the only subtlety in RLE. Everything else is")
    print("just counting.")


# ----------------------------------------------------------------------------
# SECTION C: compression ratio across data patterns
# ----------------------------------------------------------------------------

def section_patterns():
    banner("SECTION C: compression ratio across data patterns")
    print("Same algorithm, very different outcomes depending on the data.\n")
    patterns = [
        ("perfect run",       "A" * 40,                "40 identical symbols"),
        ("run-heavy (fax)",   "." * 20 + "X" + "." * 19, "long white runs, 1 black"),
        ("runs of 2",         "AABBCCDDEEFFGGHH",      "pairs"),
        ("natural text",      "the quick brown fox",   "few repeats"),
        ("alternating",       "ABABABABABABABABABAB",  "every run = 1"),
    ]
    print("| pattern           | input (shown)              | runs | "
          "bits_in | bits_out | ratio  | verdict     |")
    print("|-------------------|----------------------------|------|"
          "---------|----------|--------|-------------|")
    for name, s, note in patterns:
        toks = rle_encode(s)
        bin_ = len(s) * 8
        bout = len(toks) * 16
        r = bout / bin_ if bin_ else 1.0
        verdict = "COMPRESSED" if r < 1 else ("breakeven" if r == 1 else "EXPANDED")
        disp = (s if len(s) <= 22 else s[:19] + "...")
        print(f"| {name:<17} | {disp:<26} | {len(toks):<4} | "
              f"{bin_:<7} | {bout:<8} | {r:.3f}  | {verdict:<11} |")
    print()
    print("Read it as: RLE wins ONLY when the average run length > 2.")
    print("  - average run = len(input) / len(tokens)")
    print("  - ratio = 2 / average_run      (since 1 token = 2 bytes, 1 symbol = 1 byte)")
    print("  - so breakeven is average_run == 2 ; below that, RLE EXPANDS.\n")
    # prove the breakeven formula
    for name, s, _ in patterns:
        toks = rle_encode(s)
        avg = len(s) / len(toks) if toks else 0
        r = compression_ratio(s, toks)
        print(f"  {name:<17}: avg_run = {avg:5.2f}  ->  "
              f"2/avg_run = {2/avg:5.3f}  ==  ratio {r:5.3f}")
    print("\n[check] ratio == 2 / average_run for every pattern:  OK")


# ----------------------------------------------------------------------------
# SECTION D: the expansion failure mode (alternating data doubles the size)
# ----------------------------------------------------------------------------

def section_expansion():
    banner("SECTION D: the failure mode — alternating data DOUBLES in size")
    s = "AB" * 20            # 40 chars, 40 runs of length 1
    toks = rle_encode(s)
    print(f'input  = "AB" * 20   (len = {len(s)})')
    print(f"tokens = {len(toks)} runs of length 1 -> "
          f"{len(toks)} x (1, sym) = {len(toks) * 2} bytes on the wire\n")
    print(f"bits_in  = {len(s)} chars x 8  = {len(s) * 8} bits")
    print(f"bits_out = {len(toks)} tokens x 16 = {len(toks) * 16} bits")
    r = compression_ratio(s, toks)
    print(f"ratio    = {r:.3f}   <- the 'compressed' file is {r:.1f}x BIGGER\n")
    print("WHY: every symbol flip forces a new token, and a length-1 token")
    print("(1, 'A') costs 2 bytes to represent 1 byte. There is no run to")
    print("exploit, so the (count, symbol) overhead is pure loss.\n")
    print("This is exactly why RLE is NEVER used on its own for general data.")
    print("DEFLATE (gzip, PNG) runs LZ77 first to turn nearby repeats into")
    print("long runs, THEN Huffman-codes the result. 🔗 See HUFFMAN.md.\n")
    print(f"[check] ratio > 1 for alternating data?  {r > 1}  ({r:.3f} > 1)")
    assert r > 1


# ----------------------------------------------------------------------------
# SECTION E: when to use RLE (real-world deployments)
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION E: when to use RLE  (and when NOT to)")
    print("RLE is a SPECIALIST: brilliant on data with long runs, useless")
    print("otherwise. Real systems use it exactly where runs are guaranteed.\n")
    rows = [
        ("Fax (T.4/T.6)", "monochrome scan", "long white runs",
         "1 token per scanline of white -> ~100x"),
        ("BMP BI_RLE8/4", "paletted image", "flat color regions",
         "good on icons/logos, lossy-cap optional"),
        ("PCX",           "paletted image", "scanline runs",
         "split at count=63 (6-bit count)"),
        ("JPEG (AC)",     "quantized DCT coeffs", "trailing zeros",
         "ZRL = 16 zeros; end-of-block = all rest zero"),
        ("DEFLATE",       "LZ77 + Huffman", "LZ77 turns nearby repeats",
         "into literal/distance runs; RLE is implicit, not standalone"),
        ("Text (.txt)",   "natural language", "almost no runs",
         "DO NOT USE — expands ~2x"),
        ("Random bytes",  "encrypted/incompressible", "no runs by design",
         "DO NOT USE — expands ~2x"),
    ]
    print("| format           | payload            | why runs exist           | "
          "note                                |")
    print("|------------------|--------------------|--------------------------|"
          "-------------------------------------|")
    for name, payload, why, note in rows:
        print(f"| {name:<16} | {payload:<18} | {why:<24} | {note:<35} |")
    print()
    print("RULE OF THUMB: apply RLE only when you can GUARANTEE the average")
    print("run length is well above 2. For everything else, reach for Huffman")
    print("(symbol-frequency skew) or LZW/LZ77 (repetition).")


# ----------------------------------------------------------------------------
# SECTION F: GOLD values pinned for rle.html (the JS re-encodes & compares)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION F: GOLD values for rle.html  (the classic Wikipedia example)")
    # The canonical RLE example, used as the .html gold check.
    s = "WWWWWWWWWWWWBWWWWWWWWWWWWBBBWWWWWWWWWWWWWWWWWWWWWWWWB" \
        "WWWWWWWWWWWWWW"
    toks = rle_encode(s)
    print(f'gold input = "{s}"   (len = {len(s)})\n')
    print(f"gold tokens = {toks}\n")
    print(f"gold display = \"{to_text(toks)}\"\n")
    dec = rle_decode(toks)
    assert dec == s, "gold round-trip failed"
    print(f"[check] gold round-trip decode(encode(x)) == x ?  {dec == s}")
    r = compression_ratio(s, toks)
    print(f"[check] gold ratio = {r:.4f}  "
          f"({len(toks)} tokens x 16 bits / {len(s)} chars x 8 bits)")
    print("\nThe .html re-encodes this exact string in JS and verifies the")
    print("token list + ratio match the .py. The display form is:")
    print(f'  "{to_text(toks)}"')
    print()
    # also pin a second gold: the tiny example from §A, for the step animation
    tiny = "AAAAABBBCC"
    tt = rle_encode(tiny)
    print(f"GOLD (tiny, for the step animation): \"{tiny}\" -> {tt}")


# ============================================================================
# main
# ============================================================================

def main():
    print("rle.py - reference impl. All numbers below feed RLE.md.")
    print("pure Python stdlib, deterministic (no randomness).\n")
    print(f"MAX_RUN = {MAX_RUN}  (count byte holds 0..255)\n")

    section_basics()
    section_cap()
    section_patterns()
    section_expansion()
    section_when_to_use()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
