"""
strings_and_bytes.py — Bundle #2 (Phase 1).

GOAL (one line): show, by printing every value, that `str` is a sequence of
Unicode code points, `bytes` is raw 8-bit data, and encode/decode is the bridge
between them — and why Python 3 made str != bytes on purpose.

This is the GROUND TRUTH for STRINGS_AND_BYTES.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

Run:
    uv run python strings_and_bytes.py
"""

from __future__ import annotations

import sys
import unicodedata

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


# ----------------------------------------------------------------------------
# Section A — str is a sequence of Unicode code points
# ----------------------------------------------------------------------------

def section_a_str_is_code_points() -> None:
    banner("A — str is a sequence of Unicode code points")
    print("A Python 3 str is NOT bytes. It is an immutable sequence of")
    print("Unicode CODE POINTS — abstract integers that name characters.")
    print("ord(c) returns the code point; chr(n) is its inverse. len(str)")
    print("counts code points, NOT display columns and NOT encoded bytes.\n")

    print(f"{'expression':<32}{'result'}")
    print("-" * 52)
    rows = [
        ("ord('A')", ord("A")),
        ("chr(65)", chr(65)),
        ("ord('Z')", ord("Z")),
        ("ord('0')", ord("0")),
        ("ord('é')", ord("é")),                  # U+00E9 precomposed
        ("hex(ord('é'))", hex(ord("é"))),
        ("ord('🐍')", ord("🐍")),                 # U+1F40D snake
        ("hex(ord('🐍'))", hex(ord("🐍"))),
        ("len('AB')", len("AB")),
        ("len('é')", len("é")),                  # 1 code point (precomposed)
        ("len('🐍')", len("🐍")),                 # 1 code point, NOT 4 bytes
        ("list('Aé')", list("Aé")),              # iterate -> code points
    ]
    for label, value in rows:
        print(f"{label:<32}{value!r}")
    print()

    check("ord('A') == 65 (ASCII capital A is code point 65)", ord("A") == 65)
    check("chr(65) == 'A' (chr is the inverse of ord)", chr(65) == "A")
    check("len('🐍') == 1 (one code point, regardless of byte width)",
          len("🐍") == 1)
    check("ord('🐍') == 0x1F40D (snake is past the BMP, in the SMP)",
          ord("🐍") == 0x1F40D)

    # Concrete: 1 code point that the eye sees as 1 glyph can hide MANY code
    # points once you go to extended grapheme clusters. Family-with-ZWJ demo:
    zwj_family = "\U0001F468\u200D\U0001F469\u200D\U0001F467"  # man + ZWJ + woman + ZWJ + girl
    print("'man + ZWJ + woman + ZWJ + girl' as ONE grapheme cluster:")
    print(f"  len(...) = {len(zwj_family)}  (5 code points, 1 grapheme cluster)")
    print(f"  code points = {[hex(ord(c)) for c in zwj_family]}")
    print("  -> len counts CODE POINTS, not glyphs. For glyph counting you")
    print("     need a grapheme-segmentation library (e.g. thirdparty/regex).")
    print()
    check("ZWJ-joined 'family' has len 5 (5 code points), not 1",
          len(zwj_family) == 5)


# ----------------------------------------------------------------------------
# Section B — bytes and bytearray: raw 8-bit data
# ----------------------------------------------------------------------------

def section_b_bytes_and_bytearray() -> None:
    banner("B — bytes / bytearray: raw 8-bit data (immutable / mutable)")
    print("A bytes object is an immutable sequence of ints in [0, 255].")
    print("Indexing yields an INT (not a 1-char str like in Python 2).")
    print("bytearray is the mutable cousin. b'...' literals give bytes.\n")

    print(f"{'expression':<36}{'result':<14}{'type'}")
    print("-" * 64)
    rows = [
        ("b'AB'", b"AB", "bytes"),
        ("b'AB'[0]", b"AB"[0], "int"),
        ("b'AB'[1]", b"AB"[1], "int"),
        ("chr(b'AB'[0])", chr(b"AB"[0]), "str"),
        ("b'\\x41\\x42'", b"\x41\x42", "bytes"),
        ("b'\\x41\\x42' == b'AB'", b"\x41\x42" == b"AB", "bool"),
        ("b'AB'[0] == 65", b"AB"[0] == 65, "bool"),
        ("b'AB'[0] == 'A'", b"AB"[0] == "A", "bool"),
        ("list(b'\\x41\\x42')", list(b"\x41\x42"), "list"),
        ("bytearray(b'AB')", bytearray(b"AB"), "bytearray"),
        ("type(bytearray(b'AB')).__name__",
         type(bytearray(b"AB")).__name__, "str"),
    ]
    for label, value, tname in rows:
        print(f"{label:<36}{str(value):<14}{tname}")
    print()

    check("b'AB'[0] == 65 (indexing bytes yields an int)", b"AB"[0] == 65)
    check("b'\\x41\\x42' == b'AB' (hex escapes are just byte values)",
          b"\x41\x42" == b"AB")
    check("b'AB'[0] != 'A' (bytes indexing is NOT str indexing)",
          b"AB"[0] != "A")

    # Mutability contrast: bytes is immutable, bytearray is mutable.
    ba = bytearray(b"AB")
    print("ba = bytearray(b'AB'); ba[0] = 67  # 'C' as int")
    ba[0] = 67
    print(f"  -> ba is now {ba!r}  (mutated in place)")
    print("  bytes has NO such operator -> immutable (TypeError on item set)")
    print()

    check("bytearray is mutable (ba[0]=67 succeeds)", bytes(ba) == b"CB")
    check("bytearray is NOT bytes (it is its own type)",
          type(bytearray(b"AB")) is not bytes and
          isinstance(bytearray(b"AB"), bytearray))
    check("bytes IS bytes", type(b"AB") is bytes)


# ----------------------------------------------------------------------------
# Section C — encode/decode round-trip, UTF-8 byte layout, error modes
# ----------------------------------------------------------------------------

def section_c_encode_decode_error_modes() -> None:
    banner("C — encode/decode: the str<->bytes bridge + error modes")
    print("Text (code points) and bytes are DIFFERENT types. encode() goes")
    print("str -> bytes; decode() goes bytes -> str. The ENCODING names the")
    print("rule (UTF-8, UTF-16, ASCII, Latin-1, ...). UTF-8 uses 1-4 bytes")
    print("per code point; ASCII is a 7-bit subset of UTF-8.\n")

    # UTF-8 byte-width table.
    print("UTF-8 byte width by code-point range (the actual layout):")
    print(f"  {'range':<22}{'bytes':<7}{'example':<10}{'octets'}")
    print("  " + "-" * 56)
    examples = [
        ("U+0000..U+007F", "A"),
        ("U+0080..U+07FF", "é"),
        ("U+0800..U+FFFF", "€"),
        ("U+10000..U+10FFFF", "🐍"),
    ]
    for rng, ch in examples:
        b = ch.encode("utf-8")
        octets = " ".join(f"{byte:02x}" for byte in b)
        print(f"  {rng:<22}{len(b):<7}{ch!r:<10}{octets}")
    print()

    snake_bytes = "🐍".encode("utf-8")
    print(f"'🐍'.encode('utf-8') = {snake_bytes!r}")
    print(f"len('🐍'.encode('utf-8')) = {len(snake_bytes)}  (4 bytes, not 1)")
    print(f"'🐍'.encode('utf-8').decode('utf-8') == '🐍':  "
          f"{snake_bytes.decode('utf-8') == '🐍'}")
    print()

    check("'🐍'.encode('utf-8') == b'\\xf0\\x9f\\x90\\x8d' (4 octets)",
          "🐍".encode("utf-8") == b"\xf0\x9f\x90\x8d")
    check("len('🐍'.encode('utf-8')) == 4 (code-point len != byte len)",
          len("🐍".encode("utf-8")) == 4)
    check("'é'.encode('utf-8') has length 2 (U+00E9 is in U+0080..U+07FF)",
          len("é".encode("utf-8")) == 2)
    check("encode then decode round-trips losslessly (UTF-8 is bijective)",
          "café🐍".encode("utf-8").decode("utf-8") == "café🐍")

    # Error modes on encode (str contains chars that ASCII cannot represent).
    src = "a🐍b"
    print(f"src = {src!r}  (contains a non-ASCII code point)")
    print("  strict   -> raises UnicodeEncodeError (shown below)")
    try:
        src.encode("ascii")
    except UnicodeEncodeError as exc:
        print(f"    UnicodeEncodeError: {exc}")
    print(f"  ignore   -> {src.encode('ascii', errors='ignore')!r}"
          "  (drops the un-encodable code point)")
    print(f"  replace  -> {src.encode('ascii', errors='replace')!r}"
          "  (each bad code point becomes b'?')")
    print(f"  backslashreplace -> "
          f"{src.encode('ascii', errors='backslashreplace')!r}"
          "  (literal escapes)")
    print(f"  xmlcharrefreplace -> "
          f"{src.encode('ascii', errors='xmlcharrefreplace')!r}"
          "  (HTML entity)")
    print()

    check("ASCII encode strict raises UnicodeEncodeError for '🐍'",
          _raises(src.encode, "ascii"))
    check("errors='ignore' drops the non-ASCII code point",
          src.encode("ascii", errors="ignore") == b"ab")
    check("errors='replace' substitutes b'?' per bad code point",
          src.encode("ascii", errors="replace") == b"a?b")

    # Mojibake: decode bytes with the WRONG encoding -> garbage text.
    cafe_utf8 = "café".encode("utf-8")        # 5 code points -> 5 bytes
    decoded_latin1 = cafe_utf8.decode("latin-1")  # mis-decode as Latin-1
    print("Mojibake demo (café encoded UTF-8, decoded as Latin-1):")
    print(f"  'café'.encode('utf-8')       = {cafe_utf8!r}")
    print(f"  .decode('latin-1')           = {decoded_latin1!r}"
          "  (the é -> two Latin-1 chars)")
    print("  This is the classic 'cafÃ©' you see on mis-labeled web pages.\n")

    check("mojibake: 'café' UTF-8 bytes mis-decoded as Latin-1 != 'café'",
          cafe_utf8.decode("latin-1") != "café")
    check("re-encoding the mojibake back to latin-1 round-trips the bytes",
          decoded_latin1.encode("latin-1") == cafe_utf8)


def _raises(fn, *args, **kwargs) -> bool:
    """True if calling fn(*args, **kwargs) raises UnicodeEncodeError."""
    try:
        fn(*args, **kwargs)
    except UnicodeEncodeError:
        return True
    return False


# ----------------------------------------------------------------------------
# Section D — the normalization trap: precomposed vs combining forms
# ----------------------------------------------------------------------------

def section_d_normalization_trap() -> None:
    banner("D — The normalization trap: 'é' can be 1 OR 2 code points")
    print("The SAME glyph can have TWO different str representations:")
    print("  NFC: 'é' = U+00E9 (1 precomposed code point, len 1)")
    print("  NFD: 'é' = U+0065 + U+0301 ('e' + combining acute, len 2)")
    print("They render identically but are NOT equal as str. Normalize before")
    print("comparing, hashing, or storing user-provided text.\n")

    precomposed = "é"                          # U+00E9
    decomposed = "e\u0301"                     # U+0065 + U+0301
    print(f"precomposed = 'é'                       = {precomposed!r}")
    print(f"  code points = {[hex(ord(c)) for c in precomposed]}")
    print(f"  len         = {len(precomposed)}")
    print(f"decomposed  = 'e' + '\\u0301'           = {decomposed!r}")
    print(f"  code points = {[hex(ord(c)) for c in decomposed]}")
    print(f"  len         = {len(decomposed)}")
    print(f"precomposed == decomposed : {precomposed == decomposed}  "
          "(visually identical, structurally different!)")
    print("unicodedata.name on each code point:")
    for c in precomposed:
        print(f"  U+{ord(c):04X}  {unicodedata.name(c)}")
    for c in decomposed:
        print(f"  U+{ord(c):04X}  {unicodedata.name(c)}")
    print()

    nfc_pc = unicodedata.normalize("NFC", precomposed)
    nfc_dc = unicodedata.normalize("NFC", decomposed)
    print(f"unicodedata.normalize('NFC', precomposed) = {nfc_pc!r}  "
          f"(len {len(nfc_pc)})")
    print(f"unicodedata.normalize('NFC', decomposed)  = {nfc_dc!r}  "
          f"(len {len(nfc_dc)})")
    print(f"After NFC, both are equal: {nfc_pc == nfc_dc}")
    print()

    check("precomposed 'é' has len 1 (single code point U+00E9)",
          len(precomposed) == 1)
    check("decomposed 'e'+U+0301 has len 2 (two code points)",
          len(decomposed) == 2)
    check("precomposed != decomposed (same glyph, different str)",
          precomposed != decomposed)
    check("NFC normalization makes both forms equal",
          unicodedata.normalize("NFC", precomposed)
          == unicodedata.normalize("NFC", decomposed))


# ----------------------------------------------------------------------------
# Section E — f-strings and format specs
# ----------------------------------------------------------------------------

def section_e_fstrings_and_format_specs() -> None:
    banner("E — f-strings & format specs (PEP 498, Python 3.6+)")
    print("f-strings embed expressions directly in str literals. The part")
    print("after the optional ':' is a FORMAT SPEC (mini-language). !r / !s")
    print("/ !a pick the conversion. The = suffix (3.8+) logs name=value.\n")

    pi = 3.14159
    big = 12345
    name = "zoe"

    print(f"{'expression':<40}{'result'}")
    print("-" * 64)
    rows = [
        ("f'{{pi}}' doubled-braces -> literal", "{pi}"),
        ("f'{pi}'", f"{pi}"),
        ("f'{pi:.2f}'  (2 decimals)", f"{pi:.2f}"),
        ("f'{pi:>8.2f}'  (width 8, right align)", f"{pi:>8.2f}"),
        ("f'{pi:08.2f}'  (zero-pad)", f"{pi:08.2f}"),
        ("f'{big:,}'  (thousands separator)", f"{big:,}"),
        ("f'{big:_}'  (underscore separator)", f"{big:_}"),
        ("f'{big:b}'  (binary)", f"{big:b}"),
        ("f'{big:x}'  (hex)", f"{big:x}"),
        ("f'{big:#x}'  (hex with prefix)", f"{big:#x}"),
        ("f'{255:o}'  (octal)", f"{255:o}"),
        ("f'{65:c}'  (char from code point)", f"{65:c}"),
        ("f'{name!r}'  (repr conversion)", f"{name!r}"),
        ("f'{name!s}'  (str conversion)", f"{name!s}"),
        ("f'{name!a}'  (ascii conversion)", f"{name!a}"),
        ("f'{name:>6}'  (right align width 6)", f"{name:>6}"),
        ("f'{name:^6}'  (center align)", f"{name:^6}"),
        ("f'{name:<6}|' (left align)", f"{name:<6}|"),
    ]
    for label, value in rows:
        print(f"{label:<40}{value!r}")
    print()

    # The = debugger suffix (PEP 698 / Python 3.8): prints name=value.
    x = 42
    y = "hi"
    print("The '=' self-documenting suffix (Python 3.8+):")
    print(f"  f'{{x=}}'      -> {x=}")
    print(f"  f'{{x = :>5}}' -> {x = :>5}")
    print(f"  f'{{y=}}'      -> {y=}")
    print()

    # Nested f-strings / format spec from a variable.
    width = 8
    prec = 3
    nested_d = f"{int(pi):{width}d}"
    nested_f = f"{pi:.{prec}f}"
    print(f"Nested: width={width}, prec={prec}")
    print("  You CAN nest fields inside the format spec (no concatenation):")
    print(f"  f'{{int(pi):{{width}}d}}'  -> {nested_d!r}"
          "  (width applied at runtime)")
    print(f"  f'{{pi:.{{prec}}f}}'        -> {nested_f!r}"
          "  (precision applied at runtime)")
    print()

    check("f'{pi:.2f}' == '3.14'", f"{pi:.2f}" == "3.14")
    check("f'{big:,}' == '12,345'", f"{big:,}" == "12,345")
    check("f'{name!r}' == \"'zoe'\" (repr adds quotes)", f"{name!r}" == "'zoe'")
    check("f'{65:c}' == 'A' (format a code point as a char)",
          f"{65:c}" == "A")
    check("f-string with doubled braces is a literal brace",
          f"{1}{{pi}}" == "1{pi}")
    check("nested format spec: f'{int(pi):{width}d}' honors width=8",
          f"{int(pi):{width}d}" == "       3")
    check("nested precision: f'{pi:.{prec}f}' == '3.142'",
          f"{pi:.{prec}f}" == "3.142")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("strings_and_bytes.py — Phase 1 bundle #2.\n"
          "Every value below is computed by this file; the .md guide pastes\n"
          "it verbatim. Nothing is hand-computed.\n"
          f"Python {sys.version.split()[0]} on this machine.\n"
          f"Default encoding: {sys.getdefaultencoding()}; "
          f"filesystem encoding: {sys.getfilesystemencoding()}.")
    section_a_str_is_code_points()
    section_b_bytes_and_bytearray()
    section_c_encode_decode_error_modes()
    section_d_normalization_trap()
    section_e_fstrings_and_format_specs()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
