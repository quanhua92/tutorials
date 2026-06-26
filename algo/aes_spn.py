"""
aes_spn.py - Reference implementation of AES-128 (Rijndael) as a
Substitution-Permutation Network, built from scratch.

This file implements, in pure stdlib Python:
  * arithmetic in GF(2^8) (the field AES lives in) — xtime + multiply;
  * the AES S-box GENERATED from scratch (GF(2^8) multiplicative inverse +
    the affine transformation), not pasted from a table;
  * the four round transforms: SubBytes, ShiftRows, MixColumns, AddRoundKey;
  * the Rijndael key schedule (128-bit key -> 11 round keys);
  * a full AES-128 encrypt, verified against the official FIPS-197 test vector.

This is the single source of truth that AES_SPN.md is built from. Every
number, table, and worked example in AES_SPN.md is printed by this file.

Run:
    uv run python aes_spn.py

=========================================================================
THE INTUITION (read this first) — confusion and diffusion, layered 10 times
=========================================================================
A SUBSTITUTION-PERMUTATION NETWORK (SPN) scrambles a block by alternating two
operations, over and over:

  * SUBSTITUTION (confusion): replace each byte with a lookup that is
    deliberately nonlinear and has no algebraic shortcut (the S-box). This
    hides the relationship between the key and the ciphertext.
  * PERMUTATION / MIXING (diffusion): spread each input byte's influence
    across the WHOLE block (ShiftRows shifts bytes between columns; MixColumns
    blends each column so 1 changed input byte flips ~half of all output
    bytes). This is the AVALANCHE that makes a 1-bit change avalanche into a
    totally different ciphertext.

One round of each is weak. AES-128 chains TEN rounds, with a round key mixed
in (AddRoundKey) at every round, so the avalanche compounds: after a few
rounds every output bit depends on every key bit AND every input bit.

The data path of one AES round:
    state --SubBytes--> --ShiftRows--> --MixColumns--> --AddRoundKey--> state
    (sub)              (permute)        (mix/diffuse)   (mix in key)
  (the last round skips MixColumns)

=========================================================================
PLAIN-ENGLISH GLOSSARY
=========================================================================
  block          : the fixed-size data unit AES works on = 128 bits = 16 bytes,
                   arranged as a 4x4 COLUMN-MAJOR matrix called the 'state'.
  state          : the 4x4 byte matrix AES transforms. Filled column by
                   column: input bytes 0..3 = column 0, 4..7 = column 1, ...
  key            : AES-128 key = 128 bits = 16 bytes.
  round key      : a 16-byte key derived from the master key; one is mixed in
                   (AddRoundKey) before round 1 and after every round.
  S-box          : the 256-byte substitution table. Nonlinear. Built from a
                   GF(2^8) inverse + an affine map (see gen_sbox).
  GF(2^8)        : the finite field of 256 elements used by AES. Bytes add by
                   XOR; they multiply modulo the AES polynomial x^8+x^4+x^3+x+1
                   (0x11b). MixColumns multiplies in this field.
  confusion      : the ciphertext should depend on the key in a complex,
                   non-obvious way. Provided by the S-box.
  diffusion      : changing 1 input bit should change MANY output bits.
                   Provided by ShiftRows + MixColumns (avalanche).
  round          : SubBytes -> ShiftRows -> MixColumns -> AddRoundKey. AES-128
                   uses 10 (the last drops MixColumns).
  key schedule   : the algorithm that expands the 128-bit key into 11 round
                   keys (Rijndael key expansion).

=========================================================================
HISTORY
=========================================================================
  - Daemen & Rijndael: designed "Rijndael" as a successor to DES (DES's 56-bit
    key was too short). Selected as AES in 2000 after a 5-year NIST contest.
  - FIPS-197 (2001): the AES standard. Defines 128/192/256-bit keys; this file
    does AES-128 (10 rounds), the most common variant (TLS, disk, everywhere).
  - The design goal: fast in software AND hardware, with a clean security
    argument (wide-trail strategy = strong diffusion so differential/linear
    cryptanalysis need > 2^100 texts after 4 rounds).

DETERMINISM NOTE: AES is a fixed, keyless permutation family — every byte of
output is fully determined by (key, plaintext). The S-box, the round constants
(Rcon), and the test vector below are constants of the standard, so every run
(and the .html) is byte-identical. No randomness anywhere.

KEY FORMULAS (all implemented + asserted below):
    state layout   : state[r][c] = input[r + 4*c]        (column-major)
    S-box(b)       = affine( inverse_gf28(b) )           (inverse(0)=0)
    ShiftRows(r,c) : state[r][(c + r) mod 4]             (row r left-rotates r)
    MixColumns col : fixed matrix mul over GF(2^8) with
                     [2 3 1 1; 1 2 3 1; 1 1 2 3; 3 1 1 2]
    AddRoundKey    : state[r][c] ^= roundkey[r][c]       (byte-wise XOR)
    AES-128        : 1 AddRoundKey, then 9 full rounds, then a final round
                     (SubBytes, ShiftRows, AddRoundKey; NO MixColumns).
"""

from __future__ import annotations

BANNER = "=" * 72

AES_MOD = 0x11B  # x^8 + x^4 + x^3 + x + 1, the AES reduction polynomial


# ============================================================================
# 1. GF(2^8) ARITHMETIC  (the field AES multiplies in)
# ============================================================================

def xtime(a: int) -> int:
    """Multiply by x (i.e. by 2) in GF(2^8), reducing mod the AES polynomial.

    Left-shift by 1; if the top bit overflowed, XOR in 0x1b (the low 8 bits of
    the AES polynomial 0x11b). This is the single primitive MixColumns uses.
    """
    a <<= 1
    if a & 0x100:
        a ^= AES_MOD
    return a & 0xFF


def gmul(a: int, b: int) -> int:
    """Multiply two bytes in GF(2^8) via the Russian-peasant / xtime method.

    For each bit of b (low to high): if set, XOR the current 'a' into the
    result; then double 'a' with xtime. This is multiplication over the field
    with the AES reduction polynomial. Verified against known products below.
    """
    res = 0
    for _ in range(8):
        if b & 1:
            res ^= a
        a = xtime(a)
        b >>= 1
    return res


def gf_inverse(a: int) -> int:
    """Multiplicative inverse in GF(2^8), 0 maps to 0 (by AES convention).

    Computed by exhaustive search for a value b with gmul(a, b) == 1. Slow but
    unambiguous and needs no precomputed tables — perfect for explaining how
    the S-box is actually constructed. (AES implementations use log/exp tables
    for speed; the RESULT is identical.)
    """
    if a == 0:
        return 0
    for b in range(1, 256):
        if gmul(a, b) == 1:
            return b
    raise RuntimeError("no inverse found (field is broken?)")


# ============================================================================
# 2. THE S-BOX, GENERATED FROM SCRATCH  (inverse in GF(2^8) + affine map)
# ============================================================================

def _affine(b: int) -> int:
    """The AES affine transformation on a byte (the second S-box step).

    out = b ^ rotl(b,1) ^ rotl(b,2) ^ rotl(b,3) ^ rotl(b,4) ^ 0x63, where rotl
    is a left rotation of the 8-bit value. Equivalent to the FIPS-197 bit-matrix
    form: out_i = b_i ^ b_(i+4) ^ b_(i+5) ^ b_(i+6) ^ b_(i+7) ^ c_i, c = 0x63.
    The constant 0x63 is added LAST (rotations act on the original input).
    """
    result = b
    for shift in (1, 2, 3, 4):
        result ^= ((b << shift) | (b >> (8 - shift))) & 0xFF
    return (result ^ 0x63) & 0xFF


def gen_sbox() -> list[int]:
    """Build the full 256-byte AES S-box from first principles.

    sbox[b] = affine( inverse_gf28(b) ), with inverse(0) = 0. This is EXACTLY
    how FIPS-197 defines the S-box. We generate it rather than paste it so the
    construction is transparent and verifiable.
    """
    sbox = [0] * 256
    for b in range(256):
        inv = gf_inverse(b)
        sbox[b] = _affine(inv)
    return sbox


SBOX = gen_sbox()


# ============================================================================
# 3. STATE HELPERS  (AES uses a 4x4 COLUMN-MAJOR byte matrix)
# ============================================================================

def bytes_to_state(data: bytes) -> list[list[int]]:
    """16 bytes -> 4x4 state, filled COLUMN by column (AES convention).

    state[r][c] = data[r + 4*c]. So input bytes 0..3 form column 0 (top to
    bottom), bytes 4..7 form column 1, etc.
    """
    assert len(data) == 16
    return [[data[r + 4 * c] for c in range(4)] for r in range(4)]


def state_to_bytes(state: list[list[int]]) -> bytes:
    """4x4 state (column-major) -> 16 bytes (the inverse of bytes_to_state)."""
    return bytes(state[r][c] for c in range(4) for r in range(4))


def fmt_state(state: list[list[int]], indent: int = 4) -> str:
    """Render a 4x4 state as a hex grid (rows = r, columns = c)."""
    sp = " " * indent
    return "\n".join(sp + " ".join(f"{state[r][c]:02x}" for c in range(4))
                     for r in range(4))


# ============================================================================
# 4. THE FOUR ROUND TRANSFORMS  (SubBytes, ShiftRows, MixColumns, AddRoundKey)
# ============================================================================

def sub_bytes(state: list[list[int]]) -> list[list[int]]:
    """SubBytes: replace every byte via the S-box (the nonlinear CONFUSION step).

    Identical, independent substitution on all 16 bytes. This is the only
    nonlinear operation in AES — without it the whole cipher would be linear
    over GF(2) and trivially breakable.
    """
    return [[SBOX[state[r][c]] for c in range(4)] for r in range(4)]


def shift_rows(state: list[list[int]]) -> list[list[int]]:
    """ShiftRows: cyclically left-shift row r by r positions (the first PERMUTE).

    Row 0 stays put, row 1 shifts left by 1, row 2 by 2, row 3 by 3. This
    scatters a column's bytes across all columns so MixColumns then blends them
    across the whole block (diffusion).
    """
    return [
        [state[r][(c + r) % 4] for c in range(4)]
        for r in range(4)
    ]


# MixColumns fixed matrix, over GF(2^8):
MIX = [[2, 3, 1, 1],
       [1, 2, 3, 1],
       [1, 1, 2, 3],
       [3, 1, 1, 2]]


def mix_columns(state: list[list[int]]) -> list[list[int]]:
    """MixColumns: matrix-multiply each COLUMN by the fixed circulant matrix
    [2 3 1 1; 1 2 3 1; 1 1 2 3; 3 1 1 2] over GF(2^8) (the DIFFUSION step).

    One changed input byte in a column flips (on average) half of all 4 output
    bytes in that column; combined with ShiftRows this spreads 1 byte to the
    whole block within 2 rounds.
    """
    out = [[0] * 4 for _ in range(4)]
    for c in range(4):
        col = [state[r][c] for r in range(4)]
        for r in range(4):
            out[r][c] = (gmul(MIX[r][0], col[0]) ^ gmul(MIX[r][1], col[1])
                         ^ gmul(MIX[r][2], col[2]) ^ gmul(MIX[r][3], col[3]))
    return out


INV_MIX = [[0x0e, 0x0b, 0x0d, 0x09],
           [0x09, 0x0e, 0x0b, 0x0d],
           [0x0d, 0x09, 0x0e, 0x0b],
           [0x0b, 0x0d, 0x09, 0x0e]]


def inv_mix_columns(state: list[list[int]]) -> list[list[int]]:
    """Inverse MixColumns (for correctness-checking the forward transform)."""
    out = [[0] * 4 for _ in range(4)]
    for c in range(4):
        col = [state[r][c] for r in range(4)]
        for r in range(4):
            out[r][c] = (gmul(INV_MIX[r][0], col[0]) ^ gmul(INV_MIX[r][1], col[1])
                         ^ gmul(INV_MIX[r][2], col[2]) ^ gmul(INV_MIX[r][3], col[3]))
    return out


def add_round_key(state: list[list[int]], rk: list[list[int]]) -> list[list[int]]:
    """AddRoundKey: XOR the 16-byte round key into the state (mix in the key).

    This is the ONLY step that uses the key. It happens before round 1 and
    after every round. XOR makes it self-inverse, exactly like the XOR cipher.
    """
    return [[state[r][c] ^ rk[r][c] for c in range(4)] for r in range(4)]


# ============================================================================
# 5. KEY SCHEDULE  (Rijndael key expansion: 128-bit key -> 11 round keys)
# ============================================================================

RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def key_expansion(key: bytes) -> list[bytes]:
    """Expand a 16-byte key into 11 round keys (176 bytes total).

    AES-128 needs 44 4-byte WORDS (4 words per round key x 11 round keys). The
    first 4 words are the key itself. Each later word w[i]:
      - if i % 4 == 0: w[i] = w[i-4] ^ SubWord(RotWord(w[i-1])) ^ Rcon
      - else          : w[i] = w[i-4] ^ w[i-1]
    RotWord rotates a word's bytes; SubWord applies the S-box; Rcon is the
    round constant (powers of x in GF(2^8)) that breaks key symmetry.
    """
    assert len(key) == 16
    words = [list(key[4 * i:4 * i + 4]) for i in range(4)]
    for i in range(4, 44):
        temp = list(words[i - 1])
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]            # RotWord
            temp = [SBOX[b] for b in temp]        # SubWord
            temp[0] ^= RCON[i // 4 - 1]           # XOR round constant
        words.append([words[i - 4][j] ^ temp[j] for j in range(4)])
    # pack 4 words -> one 16-byte round key (column-major)
    return [bytes(w for word in words[4 * r:4 * r + 4] for w in word)
            for r in range(11)]


def rk_to_state(rk: bytes) -> list[list[int]]:
    """A 16-byte round key -> 4x4 state (column-major), for AddRoundKey."""
    return bytes_to_state(rk)


# ============================================================================
# 6. FULL AES-128 ENCRYPTION
# ============================================================================

def aes128_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """Encrypt one 128-bit block with AES-128. Verified vs FIPS-197 test vector.

    Structure: AddRoundKey(K0); rounds 1..9 do all four steps; round 10 omits
    MixColumns (so decryption's inverse ShiftRows and inverse MixColumns line
    up — a deliberate design choice, not an optimization).
    """
    assert len(plaintext) == 16 and len(key) == 16
    round_keys = key_expansion(key)
    state = bytes_to_state(plaintext)
    state = add_round_key(state, rk_to_state(round_keys[0]))
    for rnd in range(1, 11):
        state = sub_bytes(state)
        state = shift_rows(state)
        if rnd != 10:
            state = mix_columns(state)
        state = add_round_key(state, rk_to_state(round_keys[rnd]))
    return state_to_bytes(state)


# ============================================================================
# 7. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def hexb(bs) -> str:
    if isinstance(bs, (bytes, bytearray)):
        return " ".join(f"{b:02x}" for b in bs)
    return " ".join(f"{b:02x}" for b in bs)


# ============================================================================
# 8. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: GF(2^8) arithmetic (the field AES multiplies in)
# ----------------------------------------------------------------------------

def section_gf28():
    banner("SECTION A: GF(2^8) arithmetic  (add = XOR; mul mod x^8+x^4+x^3+x+1)")
    print("AES does all its math in GF(2^8): 256 elements, ADDITION is XOR, and")
    print("MULTIPLICATION is polynomial multiply mod the AES polynomial")
    print("0x11b (= x^8 + x^4 + x^3 + x + 1). xtime(a) = a*2, reduced:\n")
    for a in (0x01, 0x02, 0x57, 0x80, 0xff):
        print(f"  xtime(0x{a:02x}) = 0x{xtime(a):02x}")
    print()
    cases = [(0x57, 0x83), (0x02, 0x57), (0x03, 0x57), (0x80, 0x80), (0x53, 0xca)]
    print("products (used by MixColumns and S-box construction):")
    for a, b in cases:
        print(f"  0x{a:02x} * 0x{b:02x} = 0x{gmul(a, b):02x}")
    # FIPS-197 Appendix example: 0x57 * 0x83 = 0xc1
    ok = gmul(0x57, 0x83) == 0xC1
    print(f"\n[check] 0x57 * 0x83 == 0xc1 (FIPS-197 Appendix) ?  {ok}")
    assert ok
    print("\nINVERSES (the heart of the S-box): inverse(a) * a == 1, with "
          "inverse(0)=0:")
    for a in (0x01, 0x02, 0x53, 0x57, 0xff):
        inv = gf_inverse(a)
        prod = gmul(a, inv) if a else 0
        print(f"  inverse(0x{a:02x}) = 0x{inv:02x}   -> 0x{a:02x} * 0x{inv:02x} "
              f"= 0x{prod:02x}  {'(=1 ✓)' if a else '(0 by convention)'}")


# ----------------------------------------------------------------------------
# SECTION B: the S-box, generated from scratch (confusion)
# ----------------------------------------------------------------------------

def section_sbox():
    banner("SECTION B: the S-box, generated from scratch  (inverse + affine = CONFUSION)")
    print("The S-box is the ONLY nonlinear part of AES. FIPS-197 defines it as:\n")
    print("  sbox[b] = affine( inverse_gf28(b) )\n")
    print("Two steps, shown for a few bytes (b -> inverse -> affine -> sbox[b]):")
    print("  b    | inverse | affine | sbox[b]")
    for b in (0x00, 0x01, 0x10, 0x53, 0x57, 0xff):
        inv = gf_inverse(b)
        aff = _affine(inv)
        print(f"  0x{b:02x} |   0x{inv:02x}   |  0x{aff:02x}  |   0x{SBOX[b]:02x}")
    print("\nspot-checks against the FIPS-197 table:")
    checks = [(0x00, 0x63), (0x01, 0x7c), (0x10, 0xca), (0x53, 0xed),
              (0xff, 0x16)]
    all_ok = True
    for b, expected in checks:
        ok = SBOX[b] == expected
        all_ok &= ok
        print(f"  sbox[0x{b:02x}] = 0x{SBOX[b]:02x} "
              f"(expected 0x{expected:02x})  {'✓' if ok else '✗'}")
    print(f"\n[check] generated S-box matches FIPS-197 at all spot-checks ?  "
          f"{all_ok}")
    assert all_ok
    # bijectivity: a proper S-box is a permutation of 0..255
    assert sorted(SBOX) == list(range(256)), "S-box must be a bijection"
    print("[check] S-box is a bijection (permutation of 0..255) ?  True")
    print("\nThe inverse+affine construction has no simple algebraic shortcut,")
    print("which is exactly what CONFUSION needs: the ciphertext's dependence on")
    print("the key becomes opaque.")


# ----------------------------------------------------------------------------
# SECTION C: ShiftRows + MixColumns (diffusion)
# ----------------------------------------------------------------------------

def section_diffusion():
    banner("SECTION C: ShiftRows + MixColumns  (DIFFUSION / avalanche)")
    s = [[0x00, 0x10, 0x20, 0x30],
         [0x40, 0x50, 0x60, 0x70],
         [0x80, 0x90, 0xa0, 0xb0],
         [0xc0, 0xd0, 0xe0, 0xf0]]
    print("starting state (each row reads left = columns 0..3):\n")
    print(fmt_state(s))
    sr = shift_rows(s)
    print("\nShiftRows: row r left-rotates by r (spreads each column's bytes "
          "across all columns):\n")
    print(fmt_state(sr))
    ok = sr[0][0] == 0x00 and sr[1][0] == 0x50 and sr[2][0] == 0xa0 \
        and sr[3][0] == 0xf0
    print(f"\n[check] row0..3 start 0x{sr[0][0]:02x},0x{sr[1][0]:02x},"
          f"0x{sr[2][0]:02x},0x{sr[3][0]:02x} "
          f"(expect 00,50,a0,f0) ?  {ok}")
    assert ok

    print("\nMixColumns: each column * the fixed matrix "
          "[2 3 1 1;1 2 3 1;1 1 2 3;3 1 1 2] over GF(2^8).")
    print("Working column 0 of the ShiftRows state = "
          f"[0x{sr[0][0]:02x}, 0x{sr[1][0]:02x}, 0x{sr[2][0]:02x}, "
          f"0x{sr[3][0]:02x}]:")
    col = [sr[r][0] for r in range(4)]
    for r in range(4):
        terms = [f"{MIX[r][k]}*0x{col[k]:02x}" for k in range(4)]
        vals = [gmul(MIX[r][k], col[k]) for k in range(4)]
        acc = vals[0]
        for v in vals[1:]:
            acc ^= v
        print(f"  out[{r}] = {' ^ '.join(terms)} "
              f"= {' ^ '.join(f'0x{v:02x}' for v in vals)} = 0x{acc:02x}")
    mc = mix_columns(sr)
    print("\nfull MixColumns result:\n")
    print(fmt_state(mc))
    # correctness: inv_mix_columns(mix_columns(x)) == x
    back = inv_mix_columns(mc)
    ok2 = back == sr
    print(f"\n[check] inv_mix_columns(mix_columns(state)) == state ?  {ok2}   "
          "(forward transform verified)")
    assert ok2


# ----------------------------------------------------------------------------
# SECTION D: the key schedule (128-bit key -> 11 round keys)
# ----------------------------------------------------------------------------

def section_key_schedule():
    banner("SECTION D: the Rijndael key schedule  (16-byte key -> 11 round keys)")
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    rks = key_expansion(key)
    print(f"master key = {hexb(key)}\n")
    print("Round constants Rcon (powers of x in GF(2^8)) break key symmetry:")
    print("  " + ", ".join(f"0x{r:02x}" for r in RCON) + "\n")
    print("expansion trace (word w[i] for i % 4 == 0 uses RotWord+SubWord+Rcon):")
    print("  i  | operation              | word")
    words = [list(key[4 * i:4 * i + 4]) for i in range(4)]
    for i in range(4):
        print(f"  {i:<2} | (from key)             | {hexb(words[i])}")
    for i in range(4, 12):
        temp = list(words[i - 1])
        op = "w[i-4] ^ w[i-1]"
        if i % 4 == 0:
            rot = temp[1:] + temp[:1]
            sub = [SBOX[b] for b in rot]
            temp = [sub[0] ^ RCON[i // 4 - 1]] + sub[1:]
            op = "w[i-4] ^ SubWord(RotWord(w[i-1])) ^ Rcon"
        words.append([words[i - 4][j] ^ temp[j] for j in range(4)])
        print(f"  {i:<2} | {op:<22} | {hexb(words[i])}")
    print("  ...(continues to word 43 for 11 round keys)\n")
    print("the 11 round keys (K0 = master key, K1..K10 each mix in one Rcon):")
    for r, rk in enumerate(rks):
        print(f"  K{r:<2} = {hexb(rk)}")
    ok = rks[0] == key and rks[1] == bytes.fromhex("a0fafe1788542cb123a339392a6c7605")
    print(f"\n[check] K0 == master key AND K1 == a0fafe17 88542cb1 23a33939 2a6c7605 "
          f"(FIPS-197 Appendix B) ?  {ok}")
    assert ok


# ----------------------------------------------------------------------------
# SECTION E: one full round, step by step (FIPS-197 test vector)
# ----------------------------------------------------------------------------

def section_one_round():
    banner("SECTION E: one full AES round, step by step  (FIPS-197 test vector)")
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    pt = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
    rks = key_expansion(key)
    print(f"key        = {hexb(key)}")
    print(f"plaintext  = {hexb(pt)}\n")

    state = bytes_to_state(pt)
    print("input state:\n")
    print(fmt_state(state))
    state = add_round_key(state, rk_to_state(rks[0]))
    print("\nafter AddRoundKey(K0)  (plaintext ^ K0):\n")
    print(fmt_state(state))
    after0 = state_to_bytes(state)
    print(f"\n  = {hexb(after0)}\n")
    print("=" * 50)
    print("ROUND 1: SubBytes -> ShiftRows -> MixColumns -> AddRoundKey(K1)")
    print("=" * 50)

    print("\nStep 1 - SubBytes (each byte through the S-box = confusion):\n")
    state = sub_bytes(state)
    print(fmt_state(state))

    print("\nStep 2 - ShiftRows (row r left-rotates r = diffusion):\n")
    state = shift_rows(state)
    print(fmt_state(state))

    print("\nStep 3 - MixColumns (column matrix mul in GF(2^8) = diffusion):\n")
    state = mix_columns(state)
    print(fmt_state(state))

    print("\nStep 4 - AddRoundKey(K1) (XOR in round key 1):\n")
    state = add_round_key(state, rk_to_state(rks[1]))
    print(fmt_state(state))
    after1 = state_to_bytes(state)
    print(f"\n  state after round 1 = {hexb(after1)}")
    ok = after1 == bytes.fromhex("a49c7ff2689f352b6b5bea43026a5049")
    print(f"\n[check] round-1 state == a49c7ff2 689f352b 6b5bea43 026a5049 "
          f"(FIPS-197 Appendix B) ?  {ok}")
    assert ok


# ----------------------------------------------------------------------------
# SECTION F: full AES-128, verified against the FIPS-197 test vector
# ----------------------------------------------------------------------------

def section_full_aes():
    banner("SECTION F: full AES-128 encrypt  (verified vs FIPS-197 test vector)")
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    pt = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
    expected = bytes.fromhex("3925841d02dc09fbdc118597196a0b32")
    ct = aes128_encrypt(pt, key)
    print(f"key        = {hexb(key)}")
    print(f"plaintext  = {hexb(pt)}")
    print(f"ciphertext = {hexb(ct)}")
    print(f"expected   = {hexb(expected)}   (FIPS-197 Appendix B)\n")
    ok = ct == expected
    print(f"[check] AES-128(PT, KEY) == FIPS-197 Appendix B ciphertext ?  {ok}")
    assert ok
    print("\n10 rounds (1 AddRoundKey + 9 full rounds + 1 final round without")
    print("MixColumns) turn the plaintext into unrecognizable ciphertext. Every")
    print("output bit depends on every key bit and every input bit.")


# ----------------------------------------------------------------------------
# SECTION G: why AES is secure (confusion + diffusion -> avalanche)
# ----------------------------------------------------------------------------

def section_why_secure():
    banner("SECTION G: why AES is secure  (avalanche: 1 bit in -> ~64 bits change)")
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    pt = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
    ct = aes128_encrypt(pt, key)
    # flip ONE bit of the plaintext
    pt2 = bytes(b ^ 0x01 if i == 0 else b for i, b in enumerate(pt))
    ct2 = aes128_encrypt(pt2, key)
    diff_bits = sum(bin(a ^ b).count("1") for a, b in zip(ct, ct2))
    print(f"plaintext A = {hexb(pt)}")
    print(f"plaintext B = {hexb(pt2)}   (bit 0 flipped)\n")
    print(f"ciphertext A = {hexb(ct)}")
    print(f"ciphertext B = {hexb(ct2)}\n")
    print(f"bits that differ in the ciphertext = {diff_bits} / 128")
    ok = diff_bits >= 50
    print(f"[check] avalanche >= 50 bits (confusion + diffusion working) ?  {ok}")
    assert ok
    print("\nA 1-bit plaintext change flips ~half the 128 ciphertext bits. After")
    print("a few rounds the diffusion is total: each output bit depends on every")
    print("input bit (diffusion) and the key's influence is smeared by the S-box")
    print("(confusion). Differential & linear cryptanalysis need > 2^100 chosen")
    print("texts to attack 4+ rounds — far beyond brute force of the 2^128 key.")


# ----------------------------------------------------------------------------
# SECTION H: when to use AES (and the modes that make it a stream cipher)
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION H: when to use AES  (and the modes that chain blocks)")
    print("AES is a 128-bit BLOCK cipher: it maps one 16-byte block to one")
    print("16-byte block. Real messages are bigger, so you wrap it in a MODE.\n")
    rows = [
        ("AES-GCM", "counter + auth tag", "confidential + integrity",
         "TLS 1.3, HTTPS, SSH (the default AEAD)"),
        ("AES-CTR", "encrypt a counter", "confidential (no integrity)",
         "turns AES into a keystream -> XOR (see xor_cipher.py)"),
        ("AES-CBC", "chain blocks via XOR", "confidential (needs MAC)",
         "legacy TLS, older disk encryption"),
        ("AES-XTS", "tweak per sector", "confidential", "full-disk encryption (BitLocker, FileVault)"),
        ("raw AES", "1 block", "NOT for messages", "the building block; never use alone"),
    ]
    print("| mode     | how it works            | security              | "
          "when to use                         |")
    print("|----------|-------------------------|-----------------------"
          "|-------------------------------------|")
    for name, how, sec, use in rows:
        print(f"| {name:<8} | {how:<23} | {sec:<21} | {use:<35} |")
    print()
    print("RULE OF THUMB: use AES-GCM (AEAD) for confidentiality + integrity.")
    print("Never use raw AES on data (ECB leaks patterns), and never roll your")
    print("own mode. AES-CTR is literally 'XOR with an AES-derived keystream' —")
    print("the bridge between this guide and xor_cipher.py.")


# ----------------------------------------------------------------------------
# SECTION I: GOLD values pinned for aes_spn.html (JS rebuilds & compares)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION I: GOLD values for aes_spn.html  (rebuild in JS, compare)")
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    pt = bytes.fromhex("3243f6a8885a308d313198a2e0370734")
    rks = key_expansion(key)

    print(f"gold key        = {hexb(key)}")
    print(f"gold plaintext  = {hexb(pt)}")
    print(f"gold round key K1 = {hexb(rks[1])}")
    print(f"gold round key K10 = {hexb(rks[10])}")

    # round 1 intermediate
    state = bytes_to_state(pt)
    state = add_round_key(state, rk_to_state(rks[0]))
    state = sub_bytes(state)
    state = shift_rows(state)
    state = mix_columns(state)
    state = add_round_key(state, rk_to_state(rks[1]))
    after1 = state_to_bytes(state)
    print(f"\ngold state-after-round-1 = {hexb(after1)}")
    ok1 = after1 == bytes.fromhex("a49c7ff2689f352b6b5bea43026a5049")
    print(f"[check] round-1 matches FIPS-197 ?  {ok1}")
    assert ok1

    # full ciphertext
    ct = aes128_encrypt(pt, key)
    print(f"\ngold ciphertext  = {hexb(ct)}")
    ok2 = ct == bytes.fromhex("3925841d02dc09fbdc118597196a0b32")
    print(f"[check] ciphertext matches FIPS-197 Appendix B ?  {ok2}")
    assert ok2

    # S-box spot values for the .html
    print("\ngold S-box entries (for the .html S-box recompute):")
    for b in (0x00, 0x01, 0x53, 0xff):
        print(f"  sbox[0x{b:02x}] = 0x{SBOX[b]:02x}")
    print("\nThe .html rebuilds the S-box (inverse+affine), the key schedule,")
    print("one full round, and the full AES-128 encrypt in JS on this exact "
          "(key, plaintext) and verifies the round-1 state and ciphertext match.")


# ============================================================================
# main
# ============================================================================

def main():
    print("aes_spn.py - reference impl. All numbers below feed AES_SPN.md.")
    print("pure Python stdlib; S-box generated from scratch; deterministic.\n")

    section_gf28()
    section_sbox()
    section_diffusion()
    section_key_schedule()
    section_one_round()
    section_full_aes()
    section_why_secure()
    section_when_to_use()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
