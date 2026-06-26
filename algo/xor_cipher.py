"""
xor_cipher.py - Reference implementation of the XOR stream cipher.

Covers the WHOLE story in one file:
  * XOR is its own inverse  (c = p ^ k ; p = c ^ k).
  * The ONE-TIME PAD (Shannon 1949): truly random, full-length, never-reused
    key -> PERFECT SECRECY (information-theoretic; the ciphertext leaks 0 bits).
  * REPEATING-KEY XOR (= the Vigenere cipher): a short key cycled over the
    plaintext. Breakable: the period leaks (Kasiski), and every key byte is
    exposed to frequency analysis.
  * KEY REUSE is catastrophic: reusing a pad is a "two-time pad". C1 ^ C2 =
    P1 ^ P2 (the key vanishes), enabling CRIB-DRAGGING.
  * MALLEABILITY: XOR is a group operation, so flipping a ciphertext bit flips
    the matching plaintext bit FOR FREE, with no knowledge of the key.

This is the single source of truth that XOR_CIPHER.md is built from. Every
number, table, and worked example in XOR_CIPHER.md is printed by this file.

Run:
    uv run python xor_cipher.py

=========================================================================
THE INTUITION (read this first) — XOR is a one-way mirror you can flip back
=========================================================================
XOR (^) compares two bit patterns and outputs 1 wherever they DIFFER and 0
wherever they AGREE:

    1 ^ 1 = 0   (agree)        0 ^ 0 = 0   (agree)
    1 ^ 0 = 1   (differ)       0 ^ 1 = 1   (differ)

The magic property is that XOR is its OWN INVERSE: x ^ k ^ k = x. Apply the
same key twice and you get the original back. That single identity IS the
cipher:

    ENCRYPT:   ciphertext = plaintext ^ key
    DECRYPT:   plaintext  = ciphertext ^ key      (same operation!)

So encryption and decryption are the SAME function. The security question is
entirely about the KEY, never about the XOR operation:

  * random + full-length + used-once  ->  ONE-TIME PAD  ->  unbreakable
  * short key, repeated               ->  VIGENERE      ->  breakable
  * good key, reused                  ->  TWO-TIME PAD  ->  catastrophic

=========================================================================
PLAIN-ENGLISH GLOSSARY
=========================================================================
  plaintext (p)  : the message you want to hide, as bytes.
  key (k)        : the secret byte string, same length as the plaintext (for
                   a stream cipher). a.k.a. the "pad" or "keystream".
  ciphertext (c) : p ^ k. Looks like random noise (IF the key is good).
  XOR (^)        : bitwise exclusive-or. Output bit = 1 iff the two input
                   bits differ. Its own inverse: x ^ k ^ k == x.
  one-time pad   : a key that is (1) truly random, (2) exactly as long as the
                   message, (3) used exactly ONCE. Gives perfect secrecy.
  keystream      : a (pseudo)random byte stream the plaintext is XORed with.
                   In a real stream cipher (ChaCha20, AES-CTR) the keystream
                   is generated from a short key + nonce, NOT reused.
  crib           : a fragment of guessed plaintext (e.g. "the ", "HTTP/1").
  crib-dragging  : sliding a crib across C1^C2 in a two-time-pad attack to
                   recover plaintext fragments of the other message.
  malleability   : an attacker can EDIT the plaintext by editing the
                   ciphertext (c ^ delta -> p ^ delta) with no key needed.

=========================================================================
HISTORY
=========================================================================
  - Vernam (1917): the original teleprinter one-time pad (patent 1919). Key
    on paper tape, truly random, destroyed after one use.
  - Shannon (1949), "Communication Theory of Secrecy Systems": PROVED the
    one-time pad has PERFECT SECRECY (H(P) == H(P|C), ciphertext leaks 0
    info) if and only if the key is random, full-length, and never reused.
  - Vigenere (16th c.): polyalphabetic substitution = repeating-key XOR on
    letters. Broken by Kasiski (1863) and Friedman (1920) via the index of
    coincidence. Same break works on repeating-key XOR byte-for-byte.
  - Modern stream ciphers (RC4 [broken], Salsa20/ChaCha20, AES-CTR/GCM):
    they are all "XOR with a keystream" — the difference is the keystream
    comes from a CSPRNG seeded by (key, nonce), so it LOOKS one-time.

DETERMINISM NOTE: the one-time-pad key in Section B is drawn from a SEEDED
random.Random(42), so every run (and the .html) uses byte-identical pads.

KEY IDENTITIES (all asserted in code):
    self-inverse : x ^ k ^ k == x               (encrypt == decrypt)
    key cancels  : (p1 ^ k) ^ (p2 ^ k) == p1 ^ p2   (two-time pad leak)
    malleability : decrypt(c ^ d) == p ^ d       (edit ciphertext -> edit text)
    perfect secrecy (OTP) : H(P | C) == H(P)  <=>  I(P ; C) == 0
    stream cipher : ciphertext = plaintext ^ keystream   (keystream = CSPRNG)
"""

from __future__ import annotations

import random

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code XOR_CIPHER.md walks)
# ============================================================================

def xor_bytes(a: bytes, b: bytes) -> bytes:
    """XOR two equal-length byte strings, element-wise. The core operation.

    This single function is BOTH encrypt and decrypt. length(a) must equal
    length(b): a stream cipher needs a keystream exactly as long as the data.
    """
    if len(a) != len(b):
        raise ValueError(
            f"length mismatch: {len(a)} vs {len(b)} "
            "(a stream cipher key must be as long as the message)"
        )
    return bytes(x ^ y for x, y in zip(a, b))


def repeating_key_xor(data: bytes, key: bytes) -> bytes:
    """Repeating-key XOR (the Vigenere cipher, on bytes).

    A SHORT key is cycled to match the data length. This is what every
    "XOR with a password" toy cipher does, and it is BREAKABLE (Section C):
    the period leaks and each key byte sees frequency analysis.
    """
    if not key:
        raise ValueError("key must be non-empty")
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def otp_encrypt(plaintext: bytes, rng: random.Random) -> tuple[bytes, bytes]:
    """One-time pad encryption: a TRULY-RANDOM, full-length key used ONCE.

    Returns (ciphertext, key). The key is uniform random, exactly as long as
    the plaintext. This is the ONLY XOR construction with perfect secrecy.
    """
    key = bytes(rng.randrange(256) for _ in range(len(plaintext)))
    return xor_bytes(plaintext, key), key


def crib_drag(xored: bytes, crib: bytes) -> bytes:
    """Recover a plaintext fragment in a two-time-pad attack.

    Given xored == C1 ^ C2 == P1 ^ P2, and a GUESSED fragment of P1 (the
    'crib'), XOR the crib into xored to reveal the matching fragment of P2.
    Works because (P1 ^ P2) ^ P1 == P2. The key never enters the picture.
    """
    return xor_bytes(xored[: len(crib)], crib)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def hexb(bs: bytes) -> str:
    """Bytes -> space-separated hex, e.g. b'\\x03\\x00' -> '03 00'."""
    return " ".join(f"{b:02x}" for b in bs)


def asciirepr(bs: bytes) -> str:
    """Bytes -> printable form: printable ASCII shown as char, else '.'."""
    return "".join(chr(b) if 32 <= b < 127 else "." for b in bs)


def bitstr(b: int) -> str:
    """A byte value -> 8-bit binary string, e.g. 72 -> '01001000'."""
    return f"{b:08b}"


# ============================================================================
# 3. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: XOR is its own inverse (the core identity + round-trip)
# ----------------------------------------------------------------------------

def section_self_inverse():
    banner("SECTION A: XOR is its own inverse  (c = p ^ k ; p = c ^ k)")
    p = b"HELLO"
    k = b"POWER"                    # full-length key for this demo
    c = xor_bytes(p, k)
    p2 = xor_bytes(c, k)
    print(f'plaintext  = {p!r}   ({asciirepr(p)})')
    print(f'key        = {k!r}   ({asciirepr(k)})   (same length as p)\n')

    print("byte-by-byte XOR (the bit pattern: 1 where inputs DIFFER):")
    print("  pos | p      k      c=p^k  | bits")
    for i in range(len(p)):
        print(f"   {i}  | {chr(p[i])}={p[i]:3d}  "
              f"{chr(k[i])}={k[i]:3d}  {c[i]:3d}    | "
              f"{bitstr(p[i])} ^ {bitstr(k[i])} = {bitstr(c[i])}")
    print(f"\nciphertext = {hexb(c)}   (ascii: {asciirepr(c)})")

    print("\nDECRYPT applies the SAME operation: p = c ^ k")
    print("  pos | c      k      p=c^k  | bits")
    for i in range(len(p)):
        print(f"   {i}  | {c[i]:3d}    {k[i]:3d}    {p2[i]:3d}    | "
              f"{bitstr(c[i])} ^ {bitstr(k[i])} = {bitstr(p2[i])} "
              f"= '{chr(p2[i])}'")
    ok = p2 == p
    print(f'\ndecrypt(ciphertext) = {p2!r}')
    print(f"[check] p ^ k ^ k == p ?  {ok}   "
          "(XOR is its own inverse -> encrypt and decrypt are the same fn)")
    assert ok


# ----------------------------------------------------------------------------
# SECTION B: the ONE-TIME PAD — perfect secrecy (Shannon 1949)
# ----------------------------------------------------------------------------

def section_one_time_pad():
    banner("SECTION B: the ONE-TIME PAD  (random, full-length, used once = PERFECT SECRECY)")
    rng = random.Random(42)                  # seeded -> byte-identical every run
    p = b"SECRET"
    c, k = otp_encrypt(p, rng)
    print(f'plaintext = {p!r}   ({hexb(p)})')
    print(f'key (pad) = random, full-length, seeded(42)   ({hexb(k)})')
    print(f'ciphertext = p ^ k   ({hexb(c)})\n')

    ok = xor_bytes(c, k) == p
    print(f'decrypt: c ^ k = {p!r}   [check] round-trip ?  {ok}')
    assert ok

    print("\nWHY IT IS UNBREAKABLE — every plaintext is equally likely:")
    print("  For ANY guess P', there is a key K' = P' ^ C that produces the")
    print("  SAME ciphertext C. The observed ciphertext therefore rules out")
    print("  NO plaintext. Concretely, ciphertext C = "
          f"{hexb(c)} could come from:\n")
    guesses = [b"ATTACK", b"DEFEND", b"RETIRE", b"BREAK!", p]
    for g in guesses:
        kprime = xor_bytes(g, c)             # the key that would map g -> c
        back = xor_bytes(c, kprime)          # proves K' decrypts C to g
        valid = len(g) == len(c)
        print(f"    P'={g!r:12} -> key K'=P'^C={hexb(kprime):<23}"
              f" -> decrypt(C,K')={back!r}  {'(len match)' if valid else '(len mismatch)'}")
    print("\n  All these keys are equally probable (uniform random), so the")
    print("  ciphertext gives the attacker ZERO information about the plaintext.")
    print("  Formally (Shannon 1949):  H(P | C) == H(P)   <=>   I(P ; C) == 0.")
    print("  This is PERFECT SECRECY. The 3 conditions are ALL required:")
    print("    1. key is TRULY RANDOM   (uniform)")
    print("    2. key is as LONG as the message")
    print("    3. key is used ONCE      (Section D shows what reuse does)")


# ----------------------------------------------------------------------------
# SECTION C: REPEATING-KEY XOR (Vigenere) — and why it is breakable
# ----------------------------------------------------------------------------

def section_repeating_key():
    banner("SECTION C: repeating-key XOR = Vigenere  (breakable: period + freq analysis)")
    p = b"THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG"
    key = b"KEY"
    c = repeating_key_xor(p, key)
    print(f'plaintext = {p!r}')
    print(f'key       = {key!r}   (length {len(key)}, REPEATED to fit)\n')

    print("The short key CYCLES over the plaintext — every 3rd byte uses the")
    print("same key byte:")
    print("  pos | p           key pos | key byte")
    for i in range(len(p)):
        tag = " " if i % len(key) else "  <- key restarts"
        print(f"   {i:>2} | {chr(p[i])}            "
              f"{i % len(key)}       | '{chr(key[i % len(key)])}'{tag}")
    print(f"\nciphertext = {hexb(c)}\n")

    print("WHY THIS BREAKS (two facts):")
    print("  1. PERIOD LEAKS (Kasiski). A repeated PLAINTEXT byte (e.g. space)")
    print("     encrypted under the SAME key position yields a repeated CIPHERTEXT")
    print("     byte. The spacing between such repeats is a multiple of the key")
    print("     length, so their GCD reveals the period.")
    from collections import Counter
    cnt = Counter(c)
    common_byte, _ = cnt.most_common(1)[0]
    positions = [i for i, b in enumerate(c) if b == common_byte]
    diffs = [positions[k + 1] - positions[k] for k in range(len(positions) - 1)]
    g = 0
    for d in diffs:
        g = _gcd(g, d)
    print(f'     most common cipher byte 0x{common_byte:02x} (= space ^ key[0])')
    print(f'     appears at positions {positions}; distances {diffs} -> '
          f'gcd = {g} = key length')
    ok_period = g == len(key)
    print(f'     [check] gcd == key length ({len(key)}) ?  {ok_period}   '
          '(period recovered)')
    assert ok_period

    print("  2. FREQUENCY ANALYSIS per column. Group ciphertext bytes by their")
    print("     key position (i % period). Each column is a SINGLE-byte XOR")
    print("     cipher -> the most frequent byte there is the key byte XORed")
    print("     with the most common plaintext byte (space, 0x20, in English).")
    print("\n     Recovering the key by assuming space is the most common byte:")
    recovered = []
    for pos in range(len(key)):
        col = [c[i] for i in range(pos, len(c), len(key))]
        cc = Counter(col)
        most = cc.most_common(1)[0][0]
        guessed_key_byte = most ^ 0x20                  # 0x20 = space
        recovered.append(guessed_key_byte)
        mark = "(matches key!)" if guessed_key_byte == key[pos] \
            else "(no space landed here -> needs more text)"
        print(f"     column {pos}: most common cipher byte 0x{most:02x} "
              f"^ 0x20(space) = 0x{guessed_key_byte:02x} "
              f"= '{chr(guessed_key_byte)}'  {mark}")
    ncorrect = sum(1 for i in range(len(key)) if recovered[i] == key[i])
    print(f"\n     recovered key bytes = {hexb(bytes(recovered))}   "
          f"({ncorrect}/{len(key)} correct)")
    print("\n  2 of 3 columns cracked instantly; column 2 had no spaces in this")
    print("  short text, so the space heuristic missed. With MORE ciphertext the")
    print("  statistics sharpen and ALL columns fall. Real stream ciphers")
    print("  (ChaCha20, AES-CTR) generate a keystream that LOOKS full-length and")
    print("  random from a (key, nonce) seed -> no period, no columns to analyze.")


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


# ----------------------------------------------------------------------------
# SECTION D: KEY REUSE = two-time pad (crib-dragging). Catastrophic.
# ----------------------------------------------------------------------------

def section_key_reuse():
    banner("SECTION D: key reuse is catastrophic  (two-time pad + crib-dragging)")
    rng = random.Random(7)
    p1 = b"ATTACKATDAWN"
    p2 = b"DEFENDATDAWN"
    k = bytes(rng.randrange(256) for _ in range(len(p1)))   # SAME key, once
    c1 = xor_bytes(p1, k)
    c2 = xor_bytes(p2, k)
    print(f'message 1 = {p1!r}')
    print(f'message 2 = {p2!r}   (both encrypted with the SAME key)\n')
    print(f"c1 = {hexb(c1)}")
    print(f"c2 = {hexb(c2)}")

    print("\nTHE LEAK: the key CANCELS when you XOR the two ciphertexts.")
    xored = xor_bytes(c1, c2)
    p1xorp2 = xor_bytes(p1, p2)
    print(f"\n  c1 ^ c2        = {hexb(xored)}")
    print(f"  p1 ^ p2 (check)= {hexb(p1xorp2)}")
    ok = xored == p1xorp2
    print(f"  [check] c1^c2 == p1^p2 ?  {ok}   (the key is GONE)")
    assert ok

    print("\n  math:  c1 ^ c2 = (p1^k) ^ (p2^k) = p1 ^ p2 ^ (k ^ k) = p1 ^ p2")
    print("  The attacker now has p1 ^ p2 with NO key and NO randomness.\n")

    print("CRIB-DRAGGING — guess a fragment of one message, recover the other:")
    print('  attacker guesses message 1 starts with "ATTACK" (a "crib").')
    crib = b"ATTACK"
    recovered = crib_drag(xored, crib)
    print(f'  (c1^c2)[:6] ^ "ATTACK" = {recovered!r}')
    ok2 = recovered == p2[:len(crib)]
    print(f'  [check] recovered == message2[:6] ?  {ok2}   '
          f'(leaked "{recovered.decode()}" of "DEFEND")')
    assert ok2
    print("\n  Slide the crib across every offset: each correct guess peels open")
    print("  a 6-letter window of the OTHER message. This is why reusing a pad")
    print("  ONE TIME destroys perfect secrecy. The NSA called this the"
          ' "Venona" break (1940s): reused Soviet one-time pads were read.')


# ----------------------------------------------------------------------------
# SECTION E: MALLEABILITY — flip ciphertext bits to edit the plaintext
# ----------------------------------------------------------------------------

def section_malleability():
    banner("SECTION E: malleability  (flip ciphertext bits -> edit plaintext, no key)")
    rng = random.Random(99)
    p = b"AMOUNT=$1000"
    c, k = otp_encrypt(p, rng)
    print(f'plaintext  = {p!r}')
    print(f'ciphertext = {hexb(c)}   (good OTP key, unbreakable for secrecy)\n')

    print("XOR is a GROUP operation, so an attacker can EDIT the plaintext by")
    print("EDITING the ciphertext. They never need the key:\n")
    print("  decrypt(c ^ d) = (c ^ d) ^ k = (p ^ k ^ d) ^ k = p ^ d")
    print("  -> XORing ciphertext byte i with d flips plaintext byte i by d.\n")

    pos = p.index(b"1")                 # the hundreds digit
    delta = ord("1") ^ ord("9")         # '1' ^ '9' = 0x08
    forged = bytearray(c)
    forged[pos] ^= delta
    forged = bytes(forged)
    p_forged = xor_bytes(forged, k)
    print(f'  attacker wants to turn "1" (pos {pos}) into "9".')
    print(f"  delta = ord('1') ^ ord('9') = 0x{ord('1'):02x} ^ 0x{ord('9'):02x} "
          f"= 0x{delta:02x}")
    print(f"  forged ciphertext byte {pos}: 0x{c[pos]:02x} ^ 0x{delta:02x} "
          f"= 0x{forged[pos]:02x}")
    print(f"\n  decrypt(forged) = {p_forged!r}")
    ok = p_forged == b"AMOUNT=$9000"
    print(f'  [check] forged decrypts to "AMOUNT=$9000" ?  {ok}')
    assert ok
    print("\n  XOR secrecy does NOT mean integrity. The ciphertext is 'opaque'")
    print("  but 'soft': anyone can knead it into a meaningful new plaintext.")
    print("  This is why real systems add a MAC / use AEAD (AES-GCM, ChaCha20-")
    print("  Poly1305): the tag detects ANY ciphertext tampering.")


# ----------------------------------------------------------------------------
# SECTION F: when to use XOR (and when NOT to)
# ----------------------------------------------------------------------------

def section_when_to_use():
    banner("SECTION F: when to use XOR  (and the constructions to NEVER roll yourself)")
    print("XOR itself is just a building block. Security depends ENTIRELY on the")
    print("keystream. Never XOR data with a password or a short repeating key.\n")
    rows = [
        ("one-time pad", "pre-shared random key",
         "perfect secrecy", "military/diplomatic (key distribution is the hard part)"),
        ("ChaCha20", "CSPRNG keystream from (key, nonce)",
         "confidential", "TLS 1.3, WireGuard, mobile (no AES hardware)"),
        ("AES-CTR", "AES-block-encrypt a counter -> keystream",
         "confidential", "disk, general TLS (with AES-NI)"),
        ("AES-GCM", "AES-CTR + GHASH auth tag",
         "confidential + integrity", "the TLS 1.3 default AEAD"),
        ("repeating key", "short key cycled",
         "BROKEN", "toys/C TF only — Vigenere, Kasiski-broken"),
        ("XOR + password", "hash(password) cycled",
         "BROKEN", "NEVER — trivially frequency-analyzed"),
    ]
    print("| construction   | keystream source                | security           "
          "| when to use                          |")
    print("|----------------|---------------------------------|--------------------"
          "|--------------------------------------|")
    for name, src, sec, use in rows:
        print(f"| {name:<14} | {src:<31} | {sec:<18} | {use:<36} |")
    print()
    print("RULE OF THUMB: XOR with a CSPRNG keystream (ChaCha20, AES-CTR/GCM).")
    print("The keystream must (a) look random, (b) be full-length, and (c) NEVER")
    print("repeat for a given (key, nonce). Get this from a vetted library, not")
    print("from random.random() or a repeating password. And always pair")
    print("confidentiality with integrity (MAC / AEAD) to stop Section E's edits.")


# ----------------------------------------------------------------------------
# SECTION G: GOLD values pinned for xor_cipher.html (JS rebuilds & compares)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION G: GOLD values for xor_cipher.html  (rebuild in JS, compare)")
    # gold 1: repeating-key XOR on "HELLO" with key "KEY"
    p, key = b"HELLO", b"KEY"
    c = repeating_key_xor(p, key)
    dec = repeating_key_xor(c, key)
    print(f'gold plaintext = {p!r}')
    print(f'gold key       = {key!r}   (repeating)')
    print(f'gold ciphertext (hex) = {hexb(c)}')
    print(f'gold ciphertext (dec) = {list(c)}')
    ok = dec == p
    print(f'gold decrypt(c) = {dec!r}   [check] round-trip ?  {ok}')
    assert ok

    # gold 2: two-time pad crib drag (fixed messages, seeded key)
    rng = random.Random(7)
    p1, p2 = b"ATTACKATDAWN", b"DEFENDATDAWN"
    k = bytes(rng.randrange(256) for _ in range(len(p1)))
    c1, c2 = xor_bytes(p1, k), xor_bytes(p2, k)
    xored = xor_bytes(c1, c2)
    crib = b"ATTACK"
    recovered = crib_drag(xored, crib)
    print(f"\ngold two-time pad: c1^c2 (hex) = {hexb(xored)}")
    print(f'gold crib "ATTACK" -> recovered = {recovered!r}')
    print(f'gold c1[0]^c2[0] = 0x{c1[0]:02x} ^ 0x{c2[0]:02x} = '
          f'0x{xored[0]:02x} = {xored[0]}')

    # gold 3: malleability delta
    delta = ord("1") ^ ord("9")
    print(f"\ngold malleability: delta('1'->'9') = 0x{delta:02x} = {delta}")
    print("\nThe .html rebuilds the repeating-key XOR and the two-time-pad")
    print("attack in JS on these exact inputs and verifies the ciphertext, the")
    print("round-trip, the c1^c2 leak, and the crib-drag recovery match the .py.")


# ============================================================================
# main
# ============================================================================

def main():
    print("xor_cipher.py - reference impl. All numbers below feed XOR_CIPHER.md.")
    print("pure Python stdlib, deterministic (seeded pads for byte-identical "
          "runs).\n")

    section_self_inverse()
    section_one_time_pad()
    section_repeating_key()
    section_key_reuse()
    section_malleability()
    section_when_to_use()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
