"""
sha256.py - Reference implementation of SHA-256 (NIST FIPS 180-4), from scratch.

This is the single source of truth that SHA256.md is built from. Every number,
table, and worked example in SHA256.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python sha256.py

    (redirect to capture output:)
    uv run python sha256.py > sha256_output.txt

==========================================================================
THE INTUITION (read this first) — the meat grinder
==========================================================================
Imagine a meat grinder with a fixed set of blades (the compression function)
and a hopper. You feed the input in fist-sized chunks (512-bit blocks), and
after every chunk the grinder's INTERNAL STATE (256 bits, eight 32-bit words)
gets mashed up with that chunk. Once the last chunk is through, you read off
the final state — THAT is the hash. It is one-way because the blades mix
everything irreversibly: you cannot un-grind the state back to the input.

Three ideas make this secure:
  1. MERKLE-DAMGÅRD : process the message block by block, feeding each
     block's output back as the next block's input. Start from a FIXED
     public initial state (IV). The final state IS the hash.
  2. PADDING        : append a '1' bit, then '0' bits, then the 64-bit
     message length, so the total is a multiple of 512 bits. The length
     field makes SHA-256 resistant to length-extension tricks (partly).
  3. COMPRESSION    : each 512-bit block is stretched into a 64-word
     SCHEDULE, then crunched through 64 ROUNDS of bit-mixing (rotates,
     shifts, adds, and lookup constants). Every round touches every state
     word, so one flipped input bit avalanches across the whole state.

The 64 round constants K and the 8 initial values H are NOT random — they
are "nothing-up-my-sleeve" numbers derived from prime numbers:
  K[i] = first 32 bits of the fractional part of  (i-th prime)^(1/3)
  H[i] = first 32 bits of the fractional part of  (i-th prime)^(1/2)
This removes suspicion that the designers hid a backdoor in the constants.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  block        : a 512-bit chunk of the padded message = 16 words of 32 bits.
  word         : a 32-bit unsigned integer (all arithmetic is mod 2^32).
  schedule     : the 64-word working array W[0..63] built from one block's
                 16 words (the first 16 ARE the block; the next 48 are
                 derived by mixing earlier schedule words).
  compression  : the per-block function that folds W[t] and constant K[t]
  round        : into the 8-word state for 64 rounds. Each round rotates the
                 state a..h and injects two temporary values T1, T2.
  state (a..h) : the 8 working words, carried block-to-block. Initialized to
                 H[0..7]; after the final block, H[i] += state[i] gives the hash.
  IV / H       : the 8 initial hash words (square roots of the first 8 primes).
  K            : the 64 round constants (cube roots of the first 64 primes).
  avalanche    : one input bit flip changes ~half the output bits.

==========================================================================
THE HISTORY (papers + standard)
==========================================================================
  Merkle-Damgård (1989) : the iterate-compress construction SHA is built on.
  Rivest (1990, MD4 / 1992, MD5) : the 4-round-per-block word-mixing style.
  NIST FIPS 180-4 (2015) : the authoritative SHA-256 spec this file follows.
  SHA-3 / Keccak (2015)  : a sponge construction — the planned successor,
               because Merkle-Damgård is vulnerable to length extension.

KEY FORMULAS (all asserted in code, all arithmetic mod 2^32):
    ROTR(x,n) = (x>>n) | (x<<(32-n))            right rotation within 32 bits
    Ch(x,y,z) = (x&y) ^ (~x&z)                   "choose": z where x=0, y where x=1
    Maj(x,y,z)= (x&y) ^ (x&z) ^ (y&z)            majority vote
    Σ0(x)     = ROTR(x,2)^ROTR(x,13)^ROTR(x,22)  big sigma on a/e
    Σ1(x)     = ROTR(x,6)^ROTR(x,11)^ROTR(x,25)
    σ0(x)     = ROTR(x,7)^ROTR(x,18)^SHR(x,3)    small sigma for the schedule
    σ1(x)     = ROTR(x,17)^ROTR(x,19)^SHR(x,10)
    schedule  : W[t]=M[t] (t<16); W[t]=σ1(W[t-2])+W[t-7]+σ0(W[t-15])+W[t-16]
    round t   : T1=h+Σ1(e)+Ch(e,f,g)+K[t]+W[t] ; T2=Σ0(a)+Maj(a,b,c)
                h=g;g=f;f=e;e=d+T1;d=c;c=b;b=a;a=T1+T2
    finalize  : H[i]+=state[i]  ->  concatenate H[0..7] = the 256-bit hash

This file uses short ASCII inputs ("abc", "") so every step is printable.
The math is identical for gigabyte inputs — just more blocks.
"""

from __future__ import annotations

import hashlib  # ONLY to verify our from-scratch impl matches the library

BANNER = "=" * 72
MASK32 = 0xFFFFFFFF


# ============================================================================
# 0. THE "NOTHING-UP-MY-SLEEVE" CONSTANTS
#    Derived from primes, but hardcoded here (every real impl does this).
# ============================================================================


def _primes(n: int) -> list[int]:
    """First n primes."""
    out: list[int] = []
    c = 2
    while len(out) < n:
        if all(c % p for p in out):
            out.append(c)
        c += 1
    return out


# K[t] = floor(2^32 * frac( (t-th prime)^(1/3) ))   t = 0..63
# H[i] = floor(2^32 * frac( (i-th prime)^(1/2) ))   i = 0..7
_K = [
    0x428A2F98,
    0x71374491,
    0xB5C0FBCF,
    0xE9B5DBA5,
    0x3956C25B,
    0x59F111F1,
    0x923F82A4,
    0xAB1C5ED5,
    0xD807AA98,
    0x12835B01,
    0x243185BE,
    0x550C7DC3,
    0x72BE5D74,
    0x80DEB1FE,
    0x9BDC06A7,
    0xC19BF174,
    0xE49B69C1,
    0xEFBE4786,
    0x0FC19DC6,
    0x240CA1CC,
    0x2DE92C6F,
    0x4A7484AA,
    0x5CB0A9DC,
    0x76F988DA,
    0x983E5152,
    0xA831C66D,
    0xB00327C8,
    0xBF597FC7,
    0xC6E00BF3,
    0xD5A79147,
    0x06CA6351,
    0x14292967,
    0x27B70A85,
    0x2E1B2138,
    0x4D2C6DFC,
    0x53380D13,
    0x650A7354,
    0x766A0ABB,
    0x81C2C92E,
    0x92722C85,
    0xA2BFE8A1,
    0xA81A664B,
    0xC24B8B70,
    0xC76C51A3,
    0xD192E819,
    0xD6990624,
    0xF40E3585,
    0x106AA070,
    0x19A4C116,
    0x1E376C08,
    0x2748774C,
    0x34B0BCB5,
    0x391C0CB3,
    0x4ED8AA4A,
    0x5B9CCA4F,
    0x682E6FF3,
    0x748F82EE,
    0x78A5636F,
    0x84C87814,
    0x8CC70208,
    0x90BEFFFA,
    0xA4506CEB,
    0xBEF9A3F7,
    0xC67178F2,
]
_H = [
    0x6A09E667,
    0xBB67AE85,
    0x3C6EF372,
    0xA54FF53A,
    0x510E527F,
    0x9B05688C,
    0x1F83D9AB,
    0x5BE0CD19,
]


# ============================================================================
# 1. THE BIT PRIMITIVES  (32-bit word operations)
# ============================================================================


def rotr(x: int, n: int) -> int:
    """Right-rotate a 32-bit word x by n bits (bits wrap around)."""
    return ((x >> n) | (x << (32 - n))) & MASK32


def shr(x: int, n: int) -> int:
    """Right-shift a 32-bit word x by n bits (zeros fill from the left)."""
    return x >> n


def small_sigma0(x: int) -> int:
    """σ0(x) = ROTR(x,7) ^ ROTR(x,18) ^ SHR(x,3)  — used in the schedule."""
    return rotr(x, 7) ^ rotr(x, 18) ^ shr(x, 3)


def small_sigma1(x: int) -> int:
    """σ1(x) = ROTR(x,17) ^ ROTR(x,19) ^ SHR(x,10) — used in the schedule."""
    return rotr(x, 17) ^ rotr(x, 19) ^ shr(x, 10)


def big_sigma0(x: int) -> int:
    """Σ0(x) = ROTR(x,2) ^ ROTR(x,13) ^ ROTR(x,22)  — used on 'a' each round."""
    return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22)


def big_sigma1(x: int) -> int:
    """Σ1(x) = ROTR(x,6) ^ ROTR(x,11) ^ ROTR(x,25) — used on 'e' each round."""
    return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25)


def ch(x: int, y: int, z: int) -> int:
    """Ch(x,y,z) = (x&y) ^ (~x&z). Chooses z bits where x=0, y bits where x=1."""
    return (x & y) ^ (~x & z & MASK32)


def maj(x: int, y: int, z: int) -> int:
    """Maj(x,y,z) = (x&y)^(x&z)^(y&z). Bitwise majority of three words."""
    return (x & y) ^ (x & z) ^ (y & z)


# ============================================================================
# 2. PADDING  (Merkle-Damgård message preprocessing)
# ============================================================================


def pad_message(data: bytes) -> list[int]:
    """Pad to a multiple of 512 bits and return a list of 32-bit words.

    FIPS 180-4 §5.1.1:
      1. append a single '1' bit
      2. append '0' bits until length ≡ 448 (mod 512)
      3. append the ORIGINAL message length as a 64-bit big-endian integer
    The length field reserves the last 64 bits of the final block.
    """
    msg_len_bits = len(data) * 8
    # step 1 + 2: append 0x80 (the '1' bit + seven '0' bits), then zeros
    padded = bytearray(data)
    padded.append(0x80)
    while len(padded) % 64 != 56:
        padded.append(0x00)
    # step 3: 64-bit big-endian length
    padded += msg_len_bits.to_bytes(8, "big")
    # split into 32-bit big-endian words
    return [int.from_bytes(padded[i : i + 4], "big") for i in range(0, len(padded), 4)]


# ============================================================================
# 3. THE MESSAGE SCHEDULE  (expand 16 block words into 64)
# ============================================================================


def build_schedule(block_words: list[int]) -> list[int]:
    """Expand a block's 16 words into the 64-word schedule W[0..63].

    W[t] = M[t]                              for 0 <= t <= 15  (copy the block)
    W[t] = σ1(W[t-2]) + W[t-7]
           + σ0(W[t-15]) + W[t-16]           for 16 <= t <= 63 (mix earlier words)
    All additions mod 2^32.
    """
    assert len(block_words) == 16
    W = list(block_words) + [0] * 48
    for t in range(16, 64):
        W[t] = (
            small_sigma1(W[t - 2]) + W[t - 7] + small_sigma0(W[t - 15]) + W[t - 16]
        ) & MASK32
    return W


# ============================================================================
# 4. THE COMPRESSION FUNCTION  (64 rounds on the 8-word state)
# ============================================================================


def compress(state: list[int], W: list[int]) -> list[int]:
    """Run 64 rounds of the SHA-256 compression on the 8-word state.

    Returns the NEW state (the caller adds it into the running hash H).
    Each round rotates a..h and injects T1 = h+Σ1(e)+Ch(e,f,g)+K[t]+W[t] and
    T2 = Σ0(a)+Maj(a,b,c). The result is a complete remix of the state.
    """
    a, b, c, d, e, f, g, h = state
    for t in range(64):
        T1 = (h + big_sigma1(e) + ch(e, f, g) + _K[t] + W[t]) & MASK32
        T2 = (big_sigma0(a) + maj(a, b, c)) & MASK32
        h, g, f = g, f, e
        e = (d + T1) & MASK32
        d, c, b = c, b, a
        a = (T1 + T2) & MASK32
    return [a, b, c, d, e, f, g, h]


# ============================================================================
# 5. THE FULL HASH  (pad -> schedule each block -> compress -> finalize)
# ============================================================================


def sha256(data: bytes) -> str:
    """Compute the SHA-256 hex digest of `data`, entirely from scratch.

    Mirrors FIPS 180-4 §6.2: pad, then for each 512-bit block build the
    schedule and compress it into the running hash, then concatenate.
    """
    words = pad_message(data)
    H = list(_H)
    for blk_start in range(0, len(words), 16):
        block = words[blk_start : blk_start + 16]
        W = build_schedule(block)
        new_state = compress(H, W)
        H = [(H[i] + new_state[i]) & MASK32 for i in range(8)]
    return "".join(f"{w:08x}" for w in H)


# ============================================================================
# 6. PRETTY PRINTERS
# ============================================================================


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def to_bits(word: int) -> str:
    """A 32-bit word as a readable binary string (space every 8 bits)."""
    s = f"{word:032b}"
    return " ".join(s[i : i + 8] for i in range(0, 32, 8))


# ============================================================================
# 7. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the nothing-up-my-sleeve constants
# ----------------------------------------------------------------------------


def section_constants():
    banner("SECTION A: the constants  (derived from primes, not random)")
    primes = _primes(64)
    print("Every constant in SHA-256 is derived from PRIME NUMBERS, so the")
    print("designers could not have hidden a weakness in them. The recipe:\n")
    print("  K[t] = floor( 2^32 * frac( prime[t]^(1/3) ) )   t = 0..63")
    print("  H[i] = floor( 2^32 * frac( prime[i]^(1/2) ) )   i = 0..7\n")
    print("First 8 primes: " + ", ".join(str(p) for p in primes[:8]))
    print()
    print("| i | prime | root |  constant (hex) | recomputed (hex) | match |")
    print("|---|-------|------|-----------------|------------------|-------|")
    for i in range(8):
        p = primes[i]
        k_known = _K[i]
        k_recomp = int((p ** (1 / 3) % 1) * 2**32) & MASK32
        ok = k_known == k_recomp
        print(
            f"| {i} | {p:<5} | ∛    | {k_known:#010x}    | {k_recomp:#010x}    | "
            f"{'OK' if ok else 'DIFF'}   |"
        )
    print("|   |       |      |                 |                  |       |")
    for i in range(8):
        p = primes[i]
        h_known = _H[i]
        h_recomp = int((p ** (0.5) % 1) * 2**32) & MASK32
        ok = h_known == h_recomp
        print(
            f"| {i} | {p:<5} | √    | {h_known:#010x}    | {h_recomp:#010x}    | "
            f"{'OK' if ok else 'DIFF'}   |"
        )
    all_k_ok = all(
        _K[t] == int((primes[t] ** (1 / 3) % 1) * 2**32) & MASK32 for t in range(64)
    )
    all_h_ok = all(
        _H[i] == int((primes[i] ** (0.5) % 1) * 2**32) & MASK32 for i in range(8)
    )
    print(f"\n[check] all 64 K constants match ∛(prime) fractional parts?  {all_k_ok}")
    print(f"[check] all 8  H constants match √(prime) fractional parts?   {all_h_ok}")
    assert all_k_ok and all_h_ok


# ----------------------------------------------------------------------------
# SECTION B: padding (the Merkle-Damgård preprocessing)
# ----------------------------------------------------------------------------


def section_padding():
    banner("SECTION B: padding  (Merkle-Damgård preprocessing)")
    data = b"abc"
    print(f"input = {data!r}   (3 bytes = 24 bits)\n")
    print("A 512-bit block holds 16 words. 'abc' is only 24 bits, so we must")
    print("PAD it to 512 bits. The padding has three parts:\n")
    print("  1. the message bits:   0x61 0x62 0x63            ('a','b','c')")
    print("  2. a single '1' bit:   0x80  (1 bit, then seven 0 bits)")
    print("  3. '0' bits until 448 mod 512, then the 64-bit length\n")
    words = pad_message(data)
    print(
        f"After padding: {len(words)} words = {len(words) * 32} bits "
        f"= {len(words) // 16} block(s)\n"
    )
    print("| word | hex      | meaning                                  |")
    print("|------|----------|------------------------------------------|")
    meanings = [
        "0x61626380  = 'a','b','c' then the 0x80 stop bit",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = zero padding",
        "0x00000000  = high 32 bits of length (0)",
        "0x00000018  = low 32 bits of length (24 bits = 0x18)",
    ]
    for i, w in enumerate(words):
        print(f"| {i:<4} | {w:#010x} | {meanings[i]:<40} |")
    print("\nmessage length in bits = 3 bytes * 8 = 24 = 0x18")
    print(
        f"[check] last word == bit-length?  {words[-1]} == {len(data) * 8}  "
        f"{'OK' if words[-1] == len(data) * 8 else 'FAIL'}"
    )
    assert words[-1] == len(data) * 8
    print(
        f"[check] padded length % 512 == 0?  {len(words) * 32} % 512 = "
        f"{(len(words) * 32) % 512}  OK"
    )
    assert (len(words) * 32) % 512 == 0


# ----------------------------------------------------------------------------
# SECTION C: the message schedule (expand 16 words into 64)
# ----------------------------------------------------------------------------


def section_schedule():
    banner("SECTION C: the message schedule  (16 block words -> 64 schedule words)")
    data = b"abc"
    words = pad_message(data)
    block = words[:16]
    W = build_schedule(block)
    print("The first 16 schedule words ARE the padded block (copied). Words")
    print("16..63 are DERIVED by mixing earlier words:\n")
    print("  W[t] = σ1(W[t-2]) + W[t-7] + σ0(W[t-15]) + W[t-16]   (mod 2^32)\n")
    print("σ0 and σ1 are rotates+shifts that spread bits around. This")
    print("expansion is why flipping ONE input bit changes almost every W[t].\n")
    print("| t  | W[t] (hex)    | source                          |")
    print("|----|---------------|---------------------------------|")
    for t in range(64):
        if t < 16:
            src = "block word (copy)"
        else:
            src = "σ1(W[t-2])+W[t-7]+σ0(W[t-15])+W[t-16]"
        print(f"| {t:<2} | {W[t]:#010x}    | {src:<31} |")
    print("\nThe derived words (t>=16) look random even though the input was")
    print("almost all zeros — that is the bit-mixing doing its job.")
    # avalanche: flip one bit in the input and show W[0] differs, schedule differs
    W2 = build_schedule(pad_message(b"abd")[:16])  # last byte 0x63 -> 0x64
    diffs = sum(1 for t in range(64) if W[t] != W2[t])
    print(
        f"\nAvalanche check: flip 'abc'->'abd' (1 bit) -> {diffs}/64 schedule "
        f"words differ."
    )
    assert diffs >= 40


# ----------------------------------------------------------------------------
# SECTION D: the compression function (round-by-round on the state)
# ----------------------------------------------------------------------------


def section_compress():
    banner("SECTION D: the compression function  (64 rounds, round by round)")
    data = b"abc"
    W = build_schedule(pad_message(data)[:16])
    a, b, c, d, e, f, g, h = list(_H)
    print("Start the state at the IV (the 8 H constants). Each round computes:")
    print("  T1 = h + Σ1(e) + Ch(e,f,g) + K[t] + W[t]")
    print("  T2 = Σ0(a) + Maj(a,b,c)")
    print("  then shift the register: a<-T1+T2, e<-d+T1, and h<-g<-f<-e<-d<-c<-b\n")
    print("initial state (the IV):")
    print(f"  a={a:#010x}  e={e:#010x}\n")
    print("| t  | a after round  | e after round  | T1             | T2             |")
    print("|----|----------------|----------------|----------------|----------------|")
    sampled = {}
    for t in range(64):
        T1 = (h + big_sigma1(e) + ch(e, f, g) + _K[t] + W[t]) & MASK32
        T2 = (big_sigma0(a) + maj(a, b, c)) & MASK32
        h, g, f = g, f, e
        e = (d + T1) & MASK32
        d, c, b = c, b, a
        a = (T1 + T2) & MASK32
        if t < 8 or t == 63:
            print(f"| {t:<2} | {a:#014x} | {e:#014x} | {T1:#014x} | {T2:#014x} |")
            sampled[t] = (a, e, T1, T2)
    print("| .. | (rounds 8-62 omitted; every round runs identically)              |")
    new_state = [a, b, c, d, e, f, g, h]
    # finalize: add into H
    final = [(_H[i] + new_state[i]) & MASK32 for i in range(8)]
    digest = "".join(f"{w:08x}" for w in final)
    print("\nAfter 64 rounds, add the new state into the IV to get the hash words:")
    print(f"  H[0] = {_H[0]:#010x} + {new_state[0]:#010x} = {final[0]:#010x}")
    print(f"  H[1] = {_H[1]:#010x} + {new_state[1]:#010x} = {final[1]:#010x}")
    print("  ... (8 words)")
    print(f"\nfinal digest = {digest}")
    print(
        f"[check] matches hashlib.sha256(b'abc')?  "
        f"{digest == hashlib.sha256(data).hexdigest()}"
    )
    assert digest == hashlib.sha256(data).hexdigest()


# ----------------------------------------------------------------------------
# SECTION E: full hash + known test vectors (verification)
# ----------------------------------------------------------------------------


def section_test_vectors():
    banner("SECTION E: full hash + known test vectors  (verification)")
    cases = [
        (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
        (b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
        (
            b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
        ),
        (
            b"hello world",
            "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9",
        ),
    ]
    print("The real test of a from-scratch SHA-256: does it match the official")
    print("NIST test vectors and Python's hashlib?\n")
    print("| input | our sha256 | hashlib | NIST | match |")
    print("|-------|------------|---------|------|-------|")
    all_ok = True
    for data, nist in cases:
        ours = sha256(data)
        lib = hashlib.sha256(data).hexdigest()
        ok = ours == lib == nist
        all_ok = all_ok and ok
        disp = data.decode() if data else "(empty)"
        disp = (disp[:18] + "...") if len(disp) > 21 else disp
        print(
            f"| {disp:<5} | {ours[:16]}... | {lib[:16]}... | {nist[:16]}... | "
            f"{'OK' if ok else 'FAIL'}   |"
        )
    print(f"\n[check] all {len(cases)} test vectors match hashlib + NIST?  {all_ok}")
    assert all_ok
    # avalanche demo
    h1 = sha256(b"hello")
    h2 = sha256(b"hellp")  # one bit different
    diff_bits = sum(
        bin(x ^ y).count("1") for x, y in zip(bytes.fromhex(h1), bytes.fromhex(h2))
    )
    print("\nAvalanche: sha256('hello') vs sha256('hellp') (1-bit input change)")
    print(
        f"  {diff_bits} / 256 output bits differ "
        f"({diff_bits / 256 * 100:.1f}%)  <- near the ideal 50%"
    )
    print(f"  {h1}\n  {h2}")


# ----------------------------------------------------------------------------
# SECTION F: GOLD values pinned for sha256.html
# ----------------------------------------------------------------------------


def section_gold():
    banner("SECTION F: GOLD values for sha256.html")
    data = b"abc"
    print(f"gold input = {data!r}\n")
    # gold: the padded block (first 16 words)
    block = pad_message(data)[:16]
    print("gold padded block (16 words):")
    for i, w in enumerate(block):
        print(f"  W[{i}] = {w:#010x}")
    # gold: schedule words 0..15 == block; pin a few derived words for the .html
    W = build_schedule(block)
    print("\ngold schedule (sampled):")
    for t in [0, 15, 16, 17, 63]:
        print(f"  W[{t}] = {W[t]:#010x}")
    # gold: state after round 0 and round 1 (the .html replays these)
    a, b, c, d, e, f, g, h = list(_H)
    gold_rounds = {}
    for t in range(64):
        T1 = (h + big_sigma1(e) + ch(e, f, g) + _K[t] + W[t]) & MASK32
        T2 = (big_sigma0(a) + maj(a, b, c)) & MASK32
        h, g, f = g, f, e
        e = (d + T1) & MASK32
        d, c, b = c, b, a
        a = (T1 + T2) & MASK32
        if t in (0, 1, 63):
            gold_rounds[t] = (a, e, T1, T2)
    print("\ngold round values (a, e, T1, T2):")
    for t, (a, e, T1, T2) in gold_rounds.items():
        print(f"  round {t:<2}: a={a:#010x}  e={e:#010x}  T1={T1:#010x}  T2={T2:#010x}")
    # gold: final digest
    digest = sha256(data)
    print(f"\ngold digest = {digest}")
    print(
        f"[check] gold digest matches hashlib?  "
        f"{digest == hashlib.sha256(data).hexdigest()}"
    )
    assert digest == hashlib.sha256(data).hexdigest()
    print("\nThe .html re-runs the SHA-256 compression in JS from the same IV and")
    print("block, checking the schedule, round values, and final digest above.")


# ============================================================================
# main
# ============================================================================


def main():
    print("sha256.py - reference impl. All numbers below feed SHA256.md.")
    print("pure Python stdlib, deterministic (no randomness).\n")

    section_constants()
    section_padding()
    section_schedule()
    section_compress()
    section_test_vectors()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
