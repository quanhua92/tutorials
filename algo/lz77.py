"""
lz77.py - Reference implementation of LZ77 (Lempel-Ziv 1977): sliding-window
dictionary compression. This is the SINGLE SOURCE OF TRUTH that LZ77.md is
built from. Every number, table, and worked example in LZ77.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    uv run python lz77.py

==========================================================================
THE INTUITION (read this first) - the librarian with a short memory
==========================================================================
Imagine a librarian copying a book who can only remember the last W words
(the SEARCH BUFFER, also called the "dictionary"). They also peek ahead at
the next L words they have not written yet (the LOOKAHEAD BUFFER). Together
those two regions make the SLIDING WINDOW.

To compress, the librarian repeats this at every step:
  1. Look back into the remembered words for the LONGEST run that matches the
     start of what they are about to write.
  2. Instead of writing that run again, scribble a back-reference:
        (DISTANCE back, LENGTH of match, NEXT literal char)
  3. Slide the window forward by LENGTH + 1 characters.

A match may reach INTO the lookahead and overlap itself. That self-overlap is
what lets LZ77 squash a run like "aaaaaa" into one token - a free run-length
encoder. (See Section C.)

THE TOKEN (classic LZ77 / "LZ1", Ziv & Lempel 1977):
    (distance, length, next_char)
    - distance == 0  -> no match: a pure literal (length is also 0).
    - distance  > 0  -> copy `length` bytes starting `distance` back, then
                        append the single `next_char`.
    Progress is guaranteed: every token consumes length + 1 characters, so the
    encoder always advances.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  search buffer : the "dictionary" - the last W chars already encoded. The
                  encoder hunts for matches only inside it.
  lookahead     : the next L chars not yet encoded; matches are measured from
                  the start of this region.
  sliding window: search buffer + lookahead. It slides right one token at a
                  time.  Window size = W + L.
  back-reference: a (distance, length) pair pointing into the dictionary. The
                  decoder copies bytes from `distance` back instead of being
                  told what they are.
  self-overlap  : a match whose length exceeds its distance (length > distance).
                  The copy reads bytes it is currently writing -> RLE behavior.
  token         : one (distance, length, next_char) triple = the unit LZ77 emits.

==========================================================================
THE PAPER / LINEAGE
==========================================================================
  LZ77 (Ziv & Lempel, 1977, IEEE TIT-23(3)) : sliding-window dictionary.
           Introduced the (distance,length,char) idea.
  LZ78 (Ziv & Lempel, 1978)                 : explicit grow-on-the-fly dict,
           no sliding window. (See lzw.py - LZW is LZ78's practical successor.)
  LZSS (Storer & Szymanski, 1982)           : LZ77 + a 1-bit flag per token to
           drop the always-present literal char -> the form DEFLATE actually
           uses.
  DEFLATE (Deutsch, 1996, RFC 1951)         : LZ77 (LZSS-style) + Huffman.
           The codec inside gzip/zlib and PNG.

KEY RELATIONSHIPS (asserted in code below):
    window_size      = W_search + L_lookahead
    match length max = min(L_lookahead, n - pos)        (cannot run past EOF)
    self-overlap ok  : length may be > distance (copy reads its own output)
    token consumes   = length + 1 chars                 (progress guarantee)
    decode needs      : only the token stream + W_search history (rebuilt live)

Conventions:
    data           : a Python str (text). Tokens carry chars as length-1 strs.
    W_search       : search-buffer (dictionary) size in chars.
    L_lookahead    : max match length in chars.
    next_char == '' : means the match ran to EOF (no literal follows).
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code LZ77.md walks through)
# ============================================================================

def lz77_encode(data: str, w_search: int, l_lookahead: int):
    """Classic LZ77 encoder.

    data        : the input string to compress.
    w_search    : search-buffer (dictionary) size in chars.
    l_lookahead : max match length (lookahead-buffer size).
    returns     : list of (distance, length, next_char) triples. next_char is
                  '' when the match consumes up to EOF.

    Match search: try every distance in the dictionary, closest first; keep the
    LONGEST match (ties broken toward the SMALLEST distance = fewest bits).
    A match may extend into the lookahead (self-overlap), so `length` can
    exceed `distance`.
    """
    tokens = []
    pos = 0
    n = len(data)
    while pos < n:
        search_start = max(0, pos - w_search)
        best_dist = 0
        best_len = 0
        for dist in range(1, pos - search_start + 1):   # closest first
            start = pos - dist
            length = 0
            while (length < l_lookahead
                   and pos + length < n
                   and data[start + length] == data[pos + length]):
                length += 1                              # may read lookahead bytes
            if length > best_len:                        # strictly > -> ties keep small dist
                best_len = length
                best_dist = dist
        if best_len > 0:
            nxt = pos + best_len
            next_char = data[nxt] if nxt < n else ""
            tokens.append((best_dist, best_len, next_char))
            pos += best_len + 1
        else:
            tokens.append((0, 0, data[pos]))
            pos += 1
    return tokens


def lz77_decode(tokens):
    """Inverse of lz77_encode. Needs NO separate dictionary: the history is
    rebuilt live from the output itself.

    Self-overlapping copies work because we append to `out` as we copy, so a
    copy at distance d with length > d reads bytes it just wrote.
    """
    out = []
    for dist, length, char in tokens:
        if length > 0:
            start = len(out) - dist
            for i in range(length):
                out.append(out[start + i])              # may read freshly written bytes
        if char != "":
            out.append(char)
    return "".join(out)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def show_window(data, pos, w_search, l_lookahead, match_dist=0, match_len=0):
    """One-line ASCII view of the sliding window at `pos`.

      [ already encoded ] | SEARCH BUFFER | > LOOKAHEAD < | rest...
    Marks the chosen match inside the search buffer with ^ and the matched run
    inside the lookahead with *.
    """
    n = len(data)
    search_start = max(0, pos - w_search)
    la_end = min(n, pos + l_lookahead)
    cells = []
    # before search buffer
    if search_start > 0:
        cells.append(("dim", data[:search_start]))
    # search buffer
    cells.append(("search", data[search_start:pos]))
    # lookahead
    cells.append(("la", data[pos:la_end]))
    # rest
    if la_end < n:
        cells.append(("dim", data[la_end:]))
    line = ""
    for tag, seg in cells:
        line += seg
    print(f"    pos={pos:>2}  | {line}")
    # underline: ^ for match source, * for matched lookahead bytes
    mark = [" "] * (len(line))
    # position the marks relative to the printed line
    cursor = 0
    for tag, seg in cells:
        if tag == "dim":
            cursor += len(seg)
            continue
        if tag == "search":
            # mark the source run [pos - match_dist .. ) within search buffer
            if match_dist > 0:
                src_local = (pos - search_start) - match_dist
                for k in range(match_len):
                    idx = cursor + src_local + k
                    if 0 <= idx < len(mark):
                        mark[idx] = "^"
            cursor += len(seg)
        elif tag == "la":
            for k in range(match_len):
                idx = cursor + k
                if 0 <= idx < len(mark):
                    mark[idx] = "*"
            cursor += len(seg)
    print(f"          | {''.join(mark)}")


# ============================================================================
# 3. THE WORKED EXAMPLES  (tiny enough to print, big enough to show behavior)
#    Deterministic strings - the .html replicates them byte-for-byte.
# ============================================================================

TEACH = "TOBEORNOTTOBE"          # the classic (echoes "to be or not to be")
RUN   = "aaaaaa"                 # self-overlap / RLE-style
LONG  = ("the quick brown fox jumps over the lazy dog "
         "the quick brown fox jumps over the lazy dog "
         "the quick brown fox jumps over the lazy dog")


# ----------------------------------------------------------------------------
# SECTION A: the sliding window concept + parameters
# ----------------------------------------------------------------------------

def section_concept():
    banner("SECTION A: the sliding window  =  search buffer + lookahead")
    print("Two regions slide across the input together:\n")
    print("    [ ...already encoded... | SEARCH BUFFER (dictionary, W chars) "
          "| > LOOKAHEAD (L chars) < | not yet seen ... ]")
    print("                                              ^ matches are measured")
    print("                                                from the start here.\n")
    print("At each step the encoder finds the LONGEST prefix of the lookahead")
    print("that also occurs in the search buffer, then emits")
    print("    (distance, length, next_char)")
    print("and slides the window forward by length + 1.\n")
    print("Three knobs (and their classic values):")
    print("  W_search    = dictionary size.  DEFLATE/gzip = 32768 (32 KiB),")
    print("                                 PNG = 32768,  LZ4 = 65536.")
    print("  L_lookahead = max match.       DEFLATE = 258,  gzip = 258.")
    print("  MIN_MATCH   = below this, a literal is cheaper than a token.")
    print("                                 DEFLATE = 3.\n")
    print("Larger W -> more matches found (fewer tokens) but each distance")
    print("needs more bits. Larger L -> longer matches but the length field")
    print("needs more bits. Section E quantifies the tradeoff.")


# ----------------------------------------------------------------------------
# SECTION B: encode TEACH step by step
# ----------------------------------------------------------------------------

def section_encode_step_by_step():
    banner("SECTION B: encode 'TOBEORNOTTOBE' step by step  (W=16, L=16)")
    W, L = 16, 16
    data = TEACH
    print(f"input  : {data!r}   (len={len(data)})")
    print(f"params : W_search={W}, L_lookahead={L}\n")
    print("Legend: the underline marks the chosen back-reference:")
    print("  ^ = source copy region (inside search buffer)")
    print("  * = matched bytes (inside lookahead);  length = number of *\n")
    tokens = lz77_encode(data, W, L)
    pos = 0
    n = len(data)
    idx = 0
    while pos < n:
        dist, length, char = tokens[idx]
        show_window(data, pos, W, L, match_dist=dist, match_len=length)
        if dist == 0:
            print(f"          -> literal {char!r}   token = (0, 0, {char!r})")
        else:
            label = repr(char) if char != "" else "<EOF>"
            ov = "  [self-overlap: len>dist, RLE-style]" if length > dist else ""
            print(f"          -> copy {length} from dist {dist}, then {label}"
                  f"   token = ({dist}, {length}, {label}){ov}")
        pos += length + 1
        idx += 1
        print()
    print("Token stream:")
    print("  " + ", ".join(f"({d},{ln},{repr(c) if c != '' else 'EOF'})"
                            for d, ln, c in tokens))
    print(f"\n{len(data)} chars -> {len(tokens)} tokens "
          f"(first {sum(1 for t in tokens if t[0]==0)} are literals).")


# ----------------------------------------------------------------------------
# SECTION C: the self-overlap trick (match length > distance)
# ----------------------------------------------------------------------------

def section_self_overlap():
    banner("SECTION C: self-overlap - a match may be longer than its distance")
    W, L = 4, 16
    data = RUN
    print(f"input  : {data!r}   (len={len(data)})")
    print(f"params : W_search={W}, L_lookahead={L}\n")
    tokens = lz77_encode(data, W, L)
    print("Step through:\n")
    pos = 0
    idx = 0
    while pos < len(data):
        dist, length, char = tokens[idx]
        show_window(data, pos, W, L, match_dist=dist, match_len=length)
        label = repr(char) if char != "" else "<EOF>"
        print(f"          -> token = ({dist}, {length}, {label})")
        if dist > 0 and length > dist:
            print(f"          NOTE length ({length}) > distance ({dist}): the copy")
            print("          reads bytes it is CURRENTLY writing. data[1:] is matched")
            print("          against data[0:], so 'a' reproduces itself 5 times.")
        pos += length + 1
        idx += 1
        print()
    print(f"'aaaaaa' (6 chars) -> {len(tokens)} tokens: "
          + ", ".join(f"({d},{ln},{'EOF' if c=='' else repr(c)})" for d, ln, c in tokens))
    print("That is run-length encoding for free: the match source is only 1 char")
    print("away, yet the copy runs 5 chars long because it feeds on its own output.")


# ----------------------------------------------------------------------------
# SECTION D: decode + round-trip correctness + GOLD
# ----------------------------------------------------------------------------

def section_decode_and_gold():
    banner("SECTION D: decode + round-trip + GOLD token stream")
    W, L = 16, 16
    data = TEACH
    tokens = lz77_encode(data, W, L)
    decoded = lz77_decode(tokens)
    print(f"input    : {data!r}")
    print(f"tokens   : {tokens}")
    print(f"decoded  : {decoded!r}")
    ok = decoded == data
    print(f"\n[check] decode(encode(S)) == S ?  {ok}")
    assert ok, "round-trip failed!"

    # GOLD: the exact token list, pinned for lz77.html
    print("\nGOLD token stream (pinned for lz77.html):")
    for i, (d, ln, c) in enumerate(tokens):
        print(f"  token[{i}] = (distance={d}, length={ln}, "
              f"next_char={repr(c) if c != '' else 'EOF'})")
    # compact scalar checks
    n_tokens = len(tokens)
    n_literals = sum(1 for t in tokens if t[0] == 0)
    total_match_len = sum(t[1] for t in tokens)
    print(f"\nGOLD scalars:  num_tokens={n_tokens},  num_literals={n_literals},  "
          f"total_match_len={total_match_len}")
    assert n_tokens == 8 and n_literals == 5 and total_match_len == 6
    print("[check] gold scalars reproduce from lz77_encode():  OK")


# ----------------------------------------------------------------------------
# SECTION E: compression ratio + the window-size tradeoff
# ----------------------------------------------------------------------------

def section_ratio():
    banner("SECTION E: compression ratio + the window-size tradeoff")
    print("NAIVE fixed-width token model (classic LZ77 triple, no entropy coding):")
    print("  bits/token = dist_bits + len_bits + char_bits")
    print("  dist_bits = W_search.bit_length()         (distance in 1..W)")
    print("  len_bits  = (L_lookahead + 1).bit_length() (length in 0..L, incl. literal)")
    print("  char_bits = 8\n")
    print(f"longer text (len={len(LONG)}):")
    print(f"  {LONG!r}\n")
    print("Note the repeated phrase 'the quick brown fox...' starts ~45 chars apart.")

    def ratio(text, W, L):
        toks = lz77_encode(text, W, L)
        dist_bits = W.bit_length()
        len_bits = (L + 1).bit_length()
        comp_bits = len(toks) * (dist_bits + len_bits + 8)
        orig_bits = len(text) * 8
        return len(toks), dist_bits + len_bits + 8, comp_bits / orig_bits

    print("\nWindow-size sweep (L=15 fixed):")
    print("| W_search | bits/token | tokens | compressed/original | what happens             |")
    print("|----------|------------|--------|---------------------|--------------------------|")
    notes = {
        16: "window < 45: can't reach the repeat -> mostly literals",
        32: "still < 45: partial matches only",
        64: "just clears 45: every repeat now references the previous",
        256: "token count saturated; extra dist bits start to hurt",
        4096: "way past saturation: most bits wasted on dist field",
    }
    results = {}
    for W in [16, 32, 64, 256, 4096]:
        nt, bpt, r = ratio(LONG, W, 15)
        results[W] = (nt, r)
        print(f"| {W:<8} | {bpt:<10} | {nt:<6} | {r:<19.3f} | {notes[W]:<24} |")
    print("\nThere is a SWEET SPOT. Below it (W=16, ratio 1.53) the window is too")
    print("short to reach the repeating phrase ~45 chars away, so the encoder")
    print("emits mostly literals and EXPANDS the data. At W=64 the window just")
    print("clears that distance and token count saturates at 37 (ratio 0.71).")
    print("Beyond that the match count can't fall further, so each extra distance")
    print("bit only bloats the output (ratio climbs back to 0.92 at W=4096).\n")
    print("LESSON: pick W to just cover your data's repetition scale. DEFLATE fixes")
    print("W=32768 and recovers the wasted distance bits with Huffman coding - rare")
    print("long distances get long codes, common short ones get short codes - so a")
    print("huge W costs little in practice. The naive fixed-width model above can't")
    print("do that, which is exactly why pure LZ77 needs an entropy layer.\n")

    # the expansion problem on truly random data
    print("WHY pure LZ77 is weak on fresh data: a literal char (8 bits) becomes a")
    print("whole triple. On input with NO repetition, LZ77 EXPANDS the data:")
    import random
    rnd = random.Random(0)
    rnd_text = "".join(rnd.choice("abcdefghij") for _ in range(60))
    nt, bpt, r = ratio(rnd_text, 256, 15)
    print(f"  random text ({len(rnd_text)} chars, no runs): "
          f"tokens={nt}, ratio={r:.3f}  (>1.0 means EXPANSION)")
    print("That is exactly why DEFLATE layers Huffman coding on top: the literal")
    print("chars and short distances get short codes, killing the expansion. The")
    print("dictionary idea (LZ77) and the entropy idea (Huffman) are complementary")
    print("- DEFLATE = LZ77 + Huffman.\n")

    # GOLD ratio on the LONG text at the sweet spot W=64 (pinned for .html)
    nt, r = results[64]
    print(f"[check] GOLD: LONG text, W=64 (sweet spot), L=15 -> "
          f"tokens={nt}, ratio={r:.4f}")
    assert nt == 37 and abs(r - 0.706) < 0.02, (nt, r)
    print("[check] ratio matches pinned value (0.706 +/- 0.02):  OK")


# ----------------------------------------------------------------------------
# SECTION F: applications / real-world codecs built on LZ77
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION F: where LZ77 actually lives (DEFLATE family and beyond)")
    rows = [
        ("DEFLATE",  "RFC 1951", "32768",  "258", "3",
         "gzip (.gz), zlib, HTTP gzip, PNG (IDAT)"),
        ("gzip",     "GNU",      "32768",  "258", "3",
         "wraps DEFLATE; the unix 'gzip' tool"),
        ("zlib",     "RFC 1950", "32768",  "258", "3",
         "DEFLATE + Adler-32; in virtually every zip/png library"),
        ("LZ4",      "Collet '11", "65536", "255", "4",
         "very fast; favors speed over ratio"),
        ("Snappy",   "Google '11", "65536", "64",  "4",
         "Google internal; used in Protobuf/Bigtable"),
        ("LZMA/LZMA2","Pavlov '99","2^32+", "273", "2",
         "xz / 7-Zip; huge window, range coder instead of Huffman"),
    ]
    print("| codec   | spec       | W_search | L_look | MIN | used in                    |")
    print("|---------|------------|----------|--------|-----|----------------------------|")
    for name, spec, w, lk, mn, uses in rows:
        print(f"| {name:<7} | {spec:<10} | {w:<8} | {lk:<6} | {mn:<3} | {uses:<26} |")
    print()
    print("Every row is a sliding-window dictionary coder at heart: search back W")
    print("bytes, copy the longest match, emit a token. They differ in (a) how they")
    print("encode the literal vs match flag (LZSS bit vs DEFLATE Huffman tree),")
    print("(b) the entropy back-end (Huffman vs range/arithmetic), and (c) W/L size.")
    print("The 1977 idea - replace repetition with a (distance, length) pointer -")
    print("is still the backbone of general-purpose lossless compression today.")


# ============================================================================
# main
# ============================================================================

def main():
    print("lz77.py - reference impl. All numbers below feed LZ77.md.")
    print("Pure Python stdlib; deterministic.\n")
    section_concept()
    section_encode_step_by_step()
    section_self_overlap()
    section_decode_and_gold()
    section_ratio()
    section_applications()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
