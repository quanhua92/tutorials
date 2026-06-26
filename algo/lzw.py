"""
lzw.py - Reference implementation of LZW (Lempel-Ziv-Welch 1984): a dictionary
coder that BUILDS its dictionary on the fly and never has to send it - the
decoder reconstructs the exact same dictionary from the code stream alone.

This is the SINGLE SOURCE OF TRUTH that LZW.md is built from. Every number,
table, and worked example in LZW.md is printed by this file.

Run:
    uv run python lzw.py

==========================================================================
THE INTUITION (read this first) - the translator who coins abbreviations
==========================================================================
Imagine a translator typing out a long message who is allowed to coin new
abbreviations as they go. They keep a glossary (the DICTIONARY) of every
single-character symbol to start. Now they read the message left to right and
greedily extend the current run as long as it is already in the glossary; the
moment they hit a run that is NOT in the glossary, they:

  1. emit the code for the LONGEST run that WAS in the glossary,
  2. add the NEW (slightly longer) run to the glossary with a fresh code,
  3. start a new run from the current character.

Crucially, the decoder performs the SAME steps: every time it reads a code, it
can reconstruct the SAME new glossary entry the encoder just made. So the
glossary is NEVER transmitted - both sides grow it identically. That is LZW's
whole reason for existing over LZ78: no side channel for the dictionary.

THE KEY INVARIANT (encoder and decoder stay in lockstep):
    after processing the k-th emitted code, both sides have added the SAME
    k-1 new dictionary entries (the encoder adds one entry per emitted code,
    except the very last). The decoder lags by exactly one entry - which is
    fine, EXCEPT for one famous edge case (Section C).

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  dictionary   : a table mapping strings -> integer codes. Starts containing
                 only the single-character strings; grows by one entry per
                 emitted code.
  w            : the current run ("prefix" already known to be in the dict).
  code         : a fixed-width integer identifying a dictionary string.
  emit         : output dict[w] when w+c is NOT in the dict.
  variable width: codes start narrow and WIDEN by 1 bit each time the dict
                 fills a power of two, up to a cap (12 bits = 4096 codes).
  special case : the decoder sometimes receives a code for an entry it has
                 not built yet (the entry is being created from THIS code).
                 Handled by entry = w + w[0]. (Section C.)

==========================================================================
THE PAPER / LINEAGE
==========================================================================
  LZ78 (Ziv & Lempel, 1978) : explicit on-line dictionary; (string, char)
           pairs emitted, so the dictionary IS partly sent in the stream.
  LZW  (Welch, 1984, IEEE Computer 17(6)) : LZ78 + the lockstep trick that
           drops the sent dictionary entirely. Fixed-width codes.
  GIF (CompuServe 1987)      : LZW on indexed-color pixels, variable 3..12-bit.
  Unix `compress` (Spencer 1984): LZW with adaptive 9..12-bit codes.
  V.42bis (ITU 1988)         : LZW inside modems for on-the-fly compression.

KEY RELATIONSHIPS (asserted in code below):
    entries added per emitted code   = 1   (except the final trailing code)
    decoder dictionary lag           = 1 entry behind the encoder
    special-case trigger             = the received code == the next free code
    code width                       = grows 1 bit at each 2^k boundary, <= 12
    max codes (12-bit)               = 4096 (then GIF emits a CLEAR code and
                                       resets; `compress` stops adapting)

Conventions:
    For clarity, the worked traces seed the dictionary with only the distinct
    characters that actually appear, numbered 1, 2, 3, ... (so the codes stay
    small and printable). Real byte-level LZW presets codes 0..255 and starts
    new codes at 256; the algorithm is identical, only the offset differs
    (Section F).
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code LZW.md walks through)
# ============================================================================

def build_initial_dict(data):
    """Distinct characters in first-appearance order -> codes 1, 2, 3, ...
    Returns (code_map, next_code). The trailing blank '' is reserved as code 0
    in some variants; here we simply start numbering at 1.
    """
    seen = []
    for ch in data:
        if ch not in seen:
            seen.append(ch)
    code_map = {ch: i + 1 for i, ch in enumerate(seen)}
    return code_map, len(seen) + 1


def lzw_encode(data, init_dict=None, next_code=None):
    """LZW encoder. Returns (codes, final_dict, init_dict, init_next).

    codes      : list of integer codes emitted.
    final_dict : the fully-grown dictionary (string -> code).
    init_dict  : the starting dictionary (passed back for the decoder).
    """
    if init_dict is None:
        init_dict, next_code = build_initial_dict(data)
    code = dict(init_dict)
    nc = next_code
    codes = []
    w = ""
    for c in data:
        wc = w + c
        if wc in code:
            w = wc                       # extend the run while it is known
        else:
            codes.append(code[w])        # emit the longest known prefix
            code[wc] = nc                # coin a NEW abbreviation for wc
            nc += 1
            w = c                        # restart from the current char
    if w != "":
        codes.append(code[w])            # flush the trailing run (no new entry)
    return codes, code, dict(init_dict), next_code


def lzw_decode(codes, init_dict, init_next):
    """LZW decoder. Rebuilds the dictionary WITHOUT receiving it.

    The decoder lags one entry behind the encoder, which is fine - until it
    receives a code for an entry that does not exist yet (the encoder just
    created it from THIS code). That is the special case `entry = w + w[0]`.
    """
    inv = {v: k for k, v in init_dict.items()}
    table = dict(inv)                    # code -> string
    nc = init_next
    if not codes:
        return ""
    out = []
    w = table[codes[0]]
    out.append(w)
    for k in codes[1:]:
        if k in table:
            entry = table[k]
        else:
            # special case: code k was coined by the encoder from w itself
            entry = w + w[0]
        out.append(entry)
        table[nc] = w + entry[0]         # mirror the encoder's new entry
        nc += 1
        w = entry
    return "".join(out)


def lzw_compressed_bits(codes, init_next, max_bits=12):
    """Variable-width LZW bit count (the GIF / Unix-compress scheme).

    Code width starts wide enough to address the initial codes plus room for
    the first new one, then WIDENS by 1 bit each time the dictionary size
    reaches 2^width, up to max_bits. Every emitted code costs the CURRENT
    width bits. Returns (total_bits, final_width).
    """
    width = max(init_next.bit_length(), 1)
    total = 0
    dict_size = init_next                # next free code index
    for i, _code in enumerate(codes):
        total += width
        if i < len(codes) - 1:           # every emitted code except the last
            dict_size += 1               # adds exactly one dictionary entry
            if dict_size >= (1 << width) and width < max_bits:
                width += 1
    return total, width


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def render_step(w, c, wc, in_dict, emitted, new_entry, data, idx):
    """One line of the encode trace."""
    action = "extend" if in_dict else f"emit {emitted}, +dict[{new_entry!r}]"
    consumed = data[:idx + 1]
    rest = data[idx + 1:]
    tag = "  (in dict -> grow w)" if in_dict else "  (NEW -> emit + coin)"
    print(f"    read {c!r}: w+c={wc!r:<6} {action}{tag}")
    _ = consumed, rest  # (kept for potential window rendering)


# ============================================================================
# 3. THE WORKED EXAMPLES  (deterministic; the .html replicates them exactly)
# ============================================================================

TEACH = "ABABABCABABAB"          # rich: phrase repeats + new entries every step
SPECIAL = "AAAA"                 # triggers the decoder special case
LONG = ("the quick brown fox jumps over the lazy dog "
        "the quick brown fox jumps over the lazy dog "
        "the quick brown fox jumps over the lazy dog")


# ----------------------------------------------------------------------------
# SECTION A: concept + the lockstep invariant
# ----------------------------------------------------------------------------

def section_concept():
    banner("SECTION A: build the dictionary on the fly; never send it")
    print("Both sides start with a dictionary of single characters. The encoder")
    print("reads left to right, extending the current run w while w is known;\n")
    print("    while (w + c) in dictionary:  w = w + c")
    print("    the moment (w + c) is NOT in the dictionary:")
    print("        emit code(w)            # the longest known prefix")
    print("        dictionary[w + c] = new # coin a fresh abbreviation")
    print("        w = c                   # restart\n")
    print("The decoder replays the SAME additions: after reading code(w) it can")
    print("compute the SAME new entry the encoder coined. So the dictionary is")
    print("NEVER in the bitstream - it is reconstructed in lockstep.\n")
    print("INVARIANT: after the k-th emitted code, encoder and decoder have both")
    print("added k-1 entries (the encoder adds one per code, except the last).")
    print("The decoder lags one entry behind - harmless, except in Section C.\n")
    print("CODE WIDTH: codes are fixed-width but the width GROWS. It starts at")
    print("just enough bits for the seed alphabet and widens by 1 each time the")
    print("dictionary fills a power of two, capped at 12 bits (= 4096 codes).")
    print("That cap is why GIF emits a CLEAR code to reset, and why Unix")
    print("`compress` stops adapting once full.")


# ----------------------------------------------------------------------------
# SECTION B: encode TEACH step by step
# ----------------------------------------------------------------------------

def section_encode_step_by_step():
    banner("SECTION B: encode 'ABABABCABABAB' step by step")
    data = TEACH
    init_dict, init_next = build_initial_dict(data)
    print(f"input  : {data!r}   (len={len(data)})")
    print(f"seed dictionary: {init_dict}   (next free code = {init_next})\n")
    print("Trace (w = current run, c = next char read):\n")
    code = dict(init_dict)
    nc = init_next
    codes = []
    w = ""
    for i, c in enumerate(data):
        wc = w + c
        if wc in code:
            print(f"    read {c!r}: w+c={wc!r:<6} in dict -> extend w={wc!r}")
            w = wc
        else:
            emitted = code[w]
            code[wc] = nc
            print(f"    read {c!r}: w+c={wc!r:<6} NEW -> emit code({w!r})={emitted}, "
                  f"add dict[{wc!r}]={nc}, reset w={c!r}")
            codes.append(emitted)
            nc += 1
            w = c
    if w != "":
        codes.append(code[w])
        print(f"    EOF : flush trailing w={w!r} -> emit code({w!r})={code[w]} "
              f"(no new entry)")
    print(f"\nEmitted codes: {codes}")
    print(f"Dictionary grew {len(code) - len(init_dict)} entries "
          f"({len(init_dict)} seed -> {len(code)} total).")
    print(f"\n{len(data)} chars -> {len(codes)} codes.")


# ----------------------------------------------------------------------------
# SECTION C: the decoder special case  (w + w[0])
# ----------------------------------------------------------------------------

def section_special_case():
    banner("SECTION C: the decoder special case - a code for a brand-new entry")
    data = SPECIAL
    init_dict, init_next = build_initial_dict(data)
    codes, _, _, _ = lzw_encode(data, init_dict, init_next)
    print(f"input  : {data!r}   seed dict: {init_dict}  (next free = {init_next})")
    print(f"encoder emits: {codes}\n")
    print("Why it happens: the encoder can emit a code for an entry it coins on")
    print("the VERY same step, i.e. a code the decoder has not built yet. Decode:\n")
    inv = {v: k for k, v in init_dict.items()}
    table = dict(inv)
    nc = init_next
    out = []
    w = table[codes[0]]
    out.append(w)
    print(f"    code {codes[0]}: known -> {w!r}.   out={out}")
    for k in codes[1:]:
        if k in table:
            entry = table[k]
            how = f"known -> {entry!r}"
        else:
            entry = w + w[0]
            how = f"NOT in dict yet -> special case entry=w+w[0]={w!r}+{w[0]!r}={entry!r}"
        out.append(entry)
        table[nc] = w + entry[0]
        print(f"    code {k}: {how}.  add dict[{nc}]={w + entry[0]!r}.  "
              f"out={out}")
        nc += 1
        w = entry
    print(f"\nDecoded: {''.join(out)!r}  (matches input: {''.join(out) == data})")
    print("The special case is CORRECT because the only way the encoder could")
    print("emit a not-yet-decoded code is when that code = w+w[0]: the new entry")
    print("always begins with the current run's first character. This is the one")
    print("subtle corner of LZW - get it wrong and decode silently corrupts.")


# ----------------------------------------------------------------------------
# SECTION D: decode + round-trip + GOLD code stream
# ----------------------------------------------------------------------------

def section_decode_and_gold():
    banner("SECTION D: decode + round-trip + GOLD code stream")
    data = TEACH
    init_dict, init_next = build_initial_dict(data)
    codes, final_dict, _, _ = lzw_encode(data, init_dict, init_next)
    decoded = lzw_decode(codes, init_dict, init_next)
    print(f"input    : {data!r}")
    print(f"codes    : {codes}")
    print(f"decoded  : {decoded!r}")
    ok = decoded == data
    print(f"\n[check] decode(encode(S)) == S ?  {ok}")
    assert ok, "round-trip failed!"
    print(f"\nGOLD code stream (pinned for lzw.html): {codes}")
    print("GOLD dictionary growth on this input:")
    # replay to show which string got which NEW code, in order
    code = dict(init_dict)
    nc = init_next
    w = ""
    added = []
    for c in data:
        wc = w + c
        if wc in code:
            w = wc
        else:
            code[wc] = nc
            added.append((nc, wc))
            nc += 1
            w = c
    for codenum, s in added:
        print(f"    code {codenum} = {s!r}")
    # compact scalars
    n_codes = len(codes)
    n_added = len(added)
    print(f"\nGOLD scalars:  num_codes={n_codes},  dict_entries_added={n_added}")
    assert n_codes == 8 and n_added == 7
    assert codes == [1, 2, 4, 4, 3, 6, 5, 2]
    print("[check] gold code stream reproduces from lzw_encode():  OK")


# ----------------------------------------------------------------------------
# SECTION E: compression ratio + variable-width code growth
# ----------------------------------------------------------------------------

def section_ratio():
    banner("SECTION E: compression ratio + variable-width code growth")
    print("Two code-width models are used in practice:\n")
    print("  (1) FIXED 12-bit: every code costs 12 bits. Simple; the historical")
    print("      ceiling of Unix `compress` and the GIF maximum code size.")
    print("  (2) VARIABLE width: codes start narrow (just enough for the seed")
    print("      alphabet) and WIDEN by 1 bit at each 2^k boundary up to 12.")
    print("      GIF and `compress` both do this; it saves bits early on.\n")
    print("  ratio = total_code_bits / (num_chars * 8)\n")
    print(f"longer text (len={len(LONG)}):\n  {LONG!r}\n")

    def measures(text):
        init_dict, init_next = build_initial_dict(text)
        codes, _, _, _ = lzw_encode(text, init_dict, init_next)
        var_bits, final_w = lzw_compressed_bits(codes, init_next)
        fixed_bits = len(codes) * 12
        orig_bits = len(text) * 8
        return (len(codes), final_w,
                fixed_bits / orig_bits, var_bits / orig_bits)

    print("| input                      | chars | codes | final | fixed-12 | variable |")
    print("|                            |       |       | width | ratio    | ratio    |")
    print("|----------------------------|-------|-------|-------|----------|----------|")
    samples = [("TEACH 'ABABABCABABAB'", TEACH),
               ("'AAAA' (degenerate run)", SPECIAL),
               ("LONG (repeated phrase)", LONG)]
    res_long = None
    for label, txt in samples:
        nc, fw, fr, vr = measures(txt)
        print(f"| {label:<26} | {len(txt):<5} | {nc:<5} | {fw:<5} | "
              f"{fr:<8.3f} | {vr:<8.3f} |")
        if txt is LONG:
            res_long = (nc, fw, fr, vr)

    print("\nVariable width always beats (or ties) fixed-12-bit, often dramatically:")
    print("on TEACH it is 0.27 vs 0.92, because the early codes ride at 2-3 bits")
    print("instead of 12. Fixed-12-bit can even EXPAND short data (AAAA: 1.125),")
    print("since 12 bits per code is wasteful when few codes are emitted. On the")
    print("longer repetitive prose, variable width reaches ~0.52 while fixed-12")
    print("barely breaks even (0.96). The degenerate run 'AAAA' crushes to 0.22")
    print("variable because each repetition collapses into a single code. Lesson:")
    print("the adaptive width is not a minor optimization - it is where LZW's")
    print("compression actually comes from.\n")

    # GOLD on LONG (pinned for .html sanity)
    nc, fw, fr, vr = res_long
    print(f"[check] GOLD: LONG text -> codes={nc}, final_width={fw}, "
          f"fixed12_ratio={fr:.3f}, variable_ratio={vr:.3f}")
    assert nc == 84 and fw == 7
    assert abs(fr - 0.962) < 0.02 and abs(vr - 0.523) < 0.02
    print("[check] ratio matches pinned values:  OK")


# ----------------------------------------------------------------------------
# SECTION F: applications / where LZW actually lives
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION F: where LZW actually lives (and why it faded)")
    rows = [
        ("GIF",        "CompuServe 1987", "variable 3..12-bit",
         "indexed-color images; the format that made LZW famous"),
        ("TIFF (LZW)", "Aldus 1986",      "variable 2..12-bit",
         "option tag 5: LZW on TIFF image/tile data"),
        ("Unix compress", "Spencer 1984", "adaptive 9..12-bit",
         ".Z files; the classic 'compress' utility"),
        ("PDF",        "Adobe 1993",      "12-bit (LZWDecode)",
         "early PDF stream filter (mostly replaced by FlateDecode)"),
        ("V.42bis",    "ITU-T 1988",      "on-line, max 12-bit",
         "hardware LZW inside dial-up modems (in real time)"),
    ]
    print("| format        | spec             | code width        | used for                       |")
    print("|---------------|------------------|-------------------|--------------------------------|")
    for name, spec, w, uses in rows:
        print(f"| {name:<13} | {spec:<16} | {w:<17} | {uses:<30} |")
    print()
    print("LZW's heyday was the late 1980s / early 1990s. It lost ground to")
    print("DEFLATE (LZ77 + Huffman) because (a) LZW cannot beat Huffman on the")
    print("literal/symbol probabilities - DEFLATE's entropy stage is strictly")
    print("additive, and (b) the 12-bit dictionary cap limits how far back LZW")
    print("can reach (4096 entries) versus DEFLATE's 32 KiB window. GIF still")
    print("mandates LZW for patent-historical reasons, but PNG (DEFLATE) has")
    print("largely replaced it. The 1984 lockstep trick, however, remains a")
    print("beautiful idea: a dictionary reconstructed from nothing but the data.")


# ============================================================================
# main
# ============================================================================

def main():
    print("lzw.py - reference impl. All numbers below feed LZW.md.")
    print("Pure Python stdlib; deterministic.\n")
    section_concept()
    section_encode_step_by_step()
    section_special_case()
    section_decode_and_gold()
    section_ratio()
    section_applications()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
