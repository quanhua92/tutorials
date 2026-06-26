"""
rsa.py - Reference implementation of the RSA public-key cryptosystem
(Rivest-Shamir-Adleman, 1978).

This is the single source of truth that RSA.md is built from. Every number,
table, and worked example in RSA.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python rsa.py

    (redirect to capture output:)
    uv run python rsa.py > rsa_output.txt

==========================================================================
THE INTUITION (read this first) — the one-way padlock
==========================================================================
Imagine a padlock with a key. You can hand out OPEN padlocks to anyone (that
is the PUBLIC key) — anyone can snap one shut onto a box (encrypt). But ONLY
you hold the key (the PRIVATE key) that opens a locked box (decrypt). Making
the lock is cheap; picking it is astronomically hard. That is RSA in one
image.

The trick that makes the padlock a "one-way" operation is modular
exponentiation:
    encrypt:   c = m^e mod n        (anyone with the public key can do this)
    decrypt:   m = c^d mod n        (only the private-key holder can do this)
Raising to a power mod n is easy. Undoing it — finding the e-th root mod n
without knowing d — is (we believe) impossible for large n.

WHERE DOES d COME FROM? d is the secret that undoes e. We build it so that
e*d ≡ 1 (mod φ(n)), where φ is Euler's totient. Then Euler's theorem
guarantees m^(e*d) ≡ m (mod n) — i.e. encrypt-then-decrypt gives back m.
The CATCH: computing φ(n) = (p-1)(q-1) requires factoring n = p*q, and that
is the hard problem. An attacker who can factor n can recompute d and break
everything; an attacker who cannot is stuck.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  prime p, q : two large secret primes (the "ingredients").
  modulus n  : n = p * q. Part of BOTH keys. All arithmetic is mod n.
               Messages must be < n, so n's bit-length bounds message size.
  totient φ  : φ(n) = (p-1)(q-1) = how many numbers < n are coprime to n.
               SECRET — knowing it is as good as knowing the factorization.
  public exp : e, coprime to φ. The pair (n, e) is the PUBLIC key.
  private exp: d = e^-1 mod φ (the modular inverse of e). The pair (n, d) is
               the PRIVATE key.
  plaintext  : m, the message number, 0 <= m < n.
  ciphertext : c = m^e mod n. Looks random; can only be undone with d.
  signature  : s = m^d mod n (sign with PRIVATE key).
  verify     : check s^e mod n == m (anyone verifies with PUBLIC key).

==========================================================================
THE HISTORY (papers)
==========================================================================
  Diffie-Hellman (1976, "New Directions in Cryptography") : introduced the
               idea of public-key crypto but not a working encryption scheme.
  Rivest-Shamir-Adleman (1978, "A Method for Obtaining Digital Signatures
               and Public-Key Cryptosystems") : the RSA scheme below. Built
               on the hardness of integer factorization.
  Shor (1994) : a quantum algorithm that factors n in polynomial time —
               RSA's eventual doom on a large enough quantum computer.
  Current NIST: 2048-bit RSA is the minimum; 3072-bit recommended for
               long-term security.

KEY FORMULAS (all verified against the paper + asserted in code):
    n = p * q
    φ(n) = (p-1)(q-1)
    d = e^-1 mod φ               (extended Euclidean algorithm)
    encrypt:  c = m^e mod n
    decrypt:  m = c^d mod n
    sign:     s = m^d mod n
    verify:   s^e mod n == m
    CORRECTNESS (Euler's theorem):  m^(e*d) ≡ m (mod n)  when gcd(m,n)=1
        proof sketch: e*d = 1 + k*φ, so m^(e*d) = m * (m^φ)^k ≡ m * 1^k = m

This file uses TINY primes (p=61, q=53) so every number is printable. Real
RSA uses ~1024-bit primes. The math is identical — only the bit-lengths
change. NEVER use these tiny numbers for real secrecy.
"""

from __future__ import annotations

import hashlib  # only to show RSA needs NO hashing internally; see §E
import math

BANNER = "=" * 72
MASK32 = 0xFFFFFFFF


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code RSA.md walks through)
# ============================================================================


def egcd(a: int, b: int) -> tuple[int, int, int]:
    """Extended Euclidean algorithm: return (g, x, y) with a*x + b*y = g = gcd.

    This is how we find d: we need e*d ≡ 1 (mod φ), i.e. e*d + φ*k = 1, which
    is exactly what egcd(e, φ) solves — the returned x (reduced mod φ) is d.
    """
    if b == 0:
        return a, 1, 0
    g, x1, y1 = egcd(b, a % b)
    return g, y1, x1 - (a // b) * y1


def mod_inverse(e: int, phi: int) -> int:
    """Modular inverse of e mod φ: the d such that e*d ≡ 1 (mod φ).

    Built on egcd. Asserts gcd(e, φ) == 1 first (otherwise no inverse exists
    and e is not a valid public exponent).
    """
    g, x, _ = egcd(e, phi)
    assert g == 1, f"e={e} is not coprime to φ={phi}; gcd={g}"
    return x % phi


def generate_keypair(
    p: int, q: int, e: int = 17
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Generate an RSA keypair from two primes.

    Returns ((n, e) public, (n, d) private). In real RSA p and q are random
    ~1024-bit primes generated by a cryptographically secure RNG and a
    Miller-Rabin primality test. Here they are fixed tiny primes for teaching.

    Why e=17? It is the conventional 4th Fermat prime (2^4+1); 65537
    (2^16+1) is the real-world default. e must be coprime to φ.
    """
    n = p * q
    phi = (p - 1) * (q - 1)
    assert math.gcd(e, phi) == 1, "e must be coprime to φ"
    d = mod_inverse(e, phi)
    return (n, e), (n, d)


def encrypt(m: int, public: tuple[int, int]) -> int:
    """Encrypt message m with the PUBLIC key (n, e): c = m^e mod n.

    Anyone can do this — the public key is published. Python's pow(m, e, n)
    does modular exponentiation efficiently (square-and-multiply), which is
    why even 2048-bit exponents are fast.
    """
    n, e = public
    assert 0 <= m < n, f"message m={m} must satisfy 0 <= m < n={n}"
    return pow(m, e, n)


def decrypt(c: int, private: tuple[int, int]) -> int:
    """Decrypt ciphertext c with the PRIVATE key (n, d): m = c^d mod n.

    Only the private-key holder can do this. d is the secret that undoes e:
    because e*d ≡ 1 (mod φ), Euler's theorem gives c^d = (m^e)^d = m^(e*d)
    ≡ m (mod n). See §D for the proof.
    """
    n, d = private
    return pow(c, d, n)


def sign(m: int, private: tuple[int, int]) -> int:
    """Sign message m with the PRIVATE key: s = m^d mod n.

    Signatures flip encrypt/decrypt: you sign with the PRIVATE key, so only
    YOU could have produced s. Anyone verifies with the PUBLIC key.
    """
    n, d = private
    assert 0 <= m < n
    return pow(m, d, n)


def verify(s: int, public: tuple[int, int]) -> int:
    """Verify a signature s with the PUBLIC key: returns m = s^e mod n.

    If the returned m matches the claimed message, the signature is genuine
    (only the private-key holder could have made s such that s^e ≡ m).
    """
    n, e = public
    return pow(s, e, n)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def egcd_trace(a: int, b: int) -> list[tuple[int, int, int, int]]:
    """Run egcd and record each (a, b, q, r) step for the §D walkthrough."""
    steps = []
    while b != 0:
        q, r = a // b, a % b
        steps.append((a, b, q, r))
        a, b = b, r
    steps.append((a, b, 0, 0))  # final row: gcd, 0
    return steps


# ============================================================================
# 3. THE TINY CONCRETE KEYS: p=61, q=53 (printable numbers)
# ============================================================================

P, Q = 61, 53  # tiny primes (real RSA: ~1024-bit primes)
E = 17  # public exponent (a Fermat prime)
PUB, PRIV = generate_keypair(P, Q, E)


# ----------------------------------------------------------------------------
# SECTION A: key generation (the one-way padlock factory)
# ----------------------------------------------------------------------------


def section_keygen():
    banner("SECTION A: key generation  (p=61, q=53, e=17)")
    print(f"Pick two secret primes:  p = {P},  q = {Q}\n")
    n = P * Q
    phi = (P - 1) * (Q - 1)
    print(f"modulus    n = p*q            = {P}*{Q}        = {n}")
    print(f"totient    φ = (p-1)(q-1)     = {P - 1}*{Q - 1}        = {phi}\n")
    print("The modulus n is PUBLIC (part of both keys). The totient φ is")
    print("SECRET: knowing φ is exactly as valuable as knowing p and q,")
    print("because d is computed from φ. An attacker who knows φ computes")
    print("d = e^-1 mod φ instantly — so φ must never leak.\n")
    print(f"public exponent e = {E}   (a Fermat prime; must satisfy gcd(e,φ)=1)")
    g = math.gcd(E, phi)
    print(f"[check] gcd(e={E}, φ={phi}) = {g}  ->  e is a valid exponent")
    assert g == 1
    d = mod_inverse(E, phi)
    print(f"\nprivate exponent d = e^-1 mod φ = {E}^-1 mod {phi} = {d}")
    print(f"[check] e*d mod φ = {E}*{d} mod {phi} = {(E * d) % phi}   (must be 1)")
    assert (E * d) % phi == 1
    print()
    print(f"PUBLIC  key = (n={n}, e={E})   <- publish this; anyone may encrypt")
    print(f"PRIVATE key = (n={n}, d={d})   <- keep secret; only you can decrypt")
    print("\nNote n and e are SHARED between the two keys. The ONLY secret in")
    print("the whole system is d (and, equivalently, p, q, and φ). Factoring")
    print(f"n={n} back into {P}*{Q} is trivial for these tiny primes — but for")
    print("a 2048-bit n it is believed infeasible (see §E).")


# ----------------------------------------------------------------------------
# SECTION B: encrypt + decrypt (the worked example)
# ----------------------------------------------------------------------------


def section_encrypt_decrypt():
    banner("SECTION B: encrypt + decrypt  (the worked example)")
    m = 65  # ASCII 'A'
    n = P * Q
    print(f"plaintext m = {m}   (ASCII '{chr(m)}'; note m < n={n})\n")
    print(f"ENCRYPT  with public key (n={n}, e={E}):")
    c = encrypt(m, PUB)
    print(f"  c = m^e mod n = {m}^{E} mod {n} = {c}\n")
    print(f"DECRYPT  with private key (n={n}, d={PRIV[1]}):")
    m2 = decrypt(c, PRIV)
    print(f"  m = c^d mod n = {c}^{PRIV[1]} mod {n} = {m2}\n")
    ok = m2 == m
    print(f"[check] decrypt(encrypt({m})) == {m} ?  {ok}")
    assert ok
    # also show a small multi-character message
    print("\n--- a 3-character message 'CAT' ---")
    for ch in "CAT":
        mm = ord(ch)
        cc = encrypt(mm, PUB)
        dd = decrypt(cc, PRIV)
        print(
            f"  '{ch}' m={mm:>3} -> c={cc:>4} -> decrypt={dd:>3} "
            f"{'✓' if dd == mm else '✗'}"
        )


# ----------------------------------------------------------------------------
# SECTION C: sign + verify (digital signatures)
# ----------------------------------------------------------------------------


def section_sign_verify():
    banner("SECTION C: sign + verify  (digital signatures)")
    m = 42
    n = P * Q
    print("Signatures flip the roles of e and d:")
    print(f"  SIGN   with PRIVATE key (n={n}, d={PRIV[1]}):  s = m^d mod n")
    print(f"  VERIFY with PUBLIC  key (n={n}, e={E}):        recover m = s^e mod n\n")
    s = sign(m, PRIV)
    print(f"plaintext m = {m}")
    print(f"signature  s = m^d mod n = {m}^{PRIV[1]} mod {n} = {s}\n")
    recovered = verify(s, PUB)
    print(f"verify: s^e mod n = {s}^{E} mod {n} = {recovered}")
    ok = recovered == m
    print(f"[check] verify(sign({m})) == {m} ?  {ok}")
    assert ok
    # forgery demo: a wrong signature recovers a different value
    print("\nForgery attempt: an attacker sends s' = 999 (not a real signature):")
    fake = verify(999, PUB)
    print(f"  verify(999) = 999^{E} mod {n} = {fake}   != {m}  -> REJECTED")
    assert fake != m
    print("[check] a forged signature fails verification:  OK")


# ----------------------------------------------------------------------------
# SECTION D: WHY IT WORKS — Euler's theorem + extended Euclid for d
# ----------------------------------------------------------------------------


def section_why_it_works():
    banner("SECTION D: why it works — Euler's theorem  (the correctness proof)")
    phi = (P - 1) * (Q - 1)
    n = P * Q
    d = PRIV[1]
    print("We built d so that e*d ≡ 1 (mod φ). WHY does that make decryption")
    print("undo encryption? The answer is Euler's theorem:\n")
    print("  Euler's theorem:  if gcd(m, n) = 1,  then  m^φ(n) ≡ 1 (mod n).\n")
    print("Since e*d ≡ 1 (mod φ), write e*d = 1 + k*φ for some integer k:")
    print("  m^(e*d) = m^(1 + k*φ) = m * (m^φ)^k ≡ m * 1^k = m (mod n).")
    print("So (m^e)^d = m^(e*d) ≡ m (mod n). Encrypt then decrypt gives m back.\n")
    k = (E * d - 1) // phi
    print(
        f"For our keys: e*d = {E}*{d} = {E * d} = 1 + {k}*φ  "
        f"(check: 1+{k}*{phi} = {1 + k * phi})"
    )
    assert 1 + k * phi == E * d
    # demonstrate Euler's theorem numerically for several m
    print("\nEuler's theorem in action — m^φ ≡ 1 (mod n) for coprime m:\n")
    print("| m  | gcd(m,n) | m^φ mod n |")
    print("|----|----------|-----------|")
    for m in [2, 7, 65, 100]:
        g = math.gcd(m, n)
        val = pow(m, phi, n)
        tag = "  <- coprime -> 1" if g == 1 else f"  <- NOT coprime (gcd={g})"
        print(f"| {m:<2} | {g:<8} | {val:<9}|{tag}")
    print("\nFor m coprime to n, m^φ mod n is always 1. The chain")
    print("m^(e*d) = m * (m^φ)^k = m * 1 = m holds, so decryption recovers m.\n")
    # extended Euclid walkthrough for computing d
    print("HOW d IS COMPUTED — the extended Euclidean algorithm finds x with")
    print(f"e*x + φ*y = 1, and x mod φ is d. Trace for e={E}, φ={phi}:\n")
    steps = egcd_trace(E, phi)
    print("| step |   a    |   b    |  q=a//b  |  r=a%b  |")
    print("|------|--------|--------|----------|---------|")
    for i, (a, b, q, r) in enumerate(steps):
        if b == 0:
            print(f"| {i:<4} | {a:<6} | {b:<6} |  (gcd)   |         |  <- gcd={a}")
        else:
            print(f"| {i:<4} | {a:<6} | {b:<6} | {q:<8} | {r:<7} |")
    g, x, y = egcd(E, phi)
    print(f"\nResult: gcd={g}, x={x}, y={y}")
    print(f"  check: e*x + φ*y = {E}*{x} + {phi}*{y} = {E * x + phi * y} (== gcd={g})")
    assert E * x + phi * y == g
    print(f"  d = x mod φ = {x % phi}")
    assert x % phi == d


# ----------------------------------------------------------------------------
# SECTION E: security properties (factoring hardness + key sizes)
# ----------------------------------------------------------------------------


def section_security():
    banner("SECTION E: security properties  (factoring hardness + key sizes)")
    n = P * Q
    print("RSA's security rests ENTIRELY on one assumption:\n")
    print("  FACTORING n = p*q is hard for an attacker who knows only n.\n")
    print("Why? Because every other secret (φ, d) follows from p and q:")
    print("  know p,q  ->  φ=(p-1)(q-1)  ->  d=e^-1 mod φ  ->  private key.\n")
    print("For our toy n this is trivial:")
    print(f"  factor({n}) = {P} * {Q}   (a modern CPU does this in microseconds)\n")
    print("But the difficulty EXPLODES with bit-length:\n")
    print("| RSA modulus | bit-length | factoring effort            | status      |")
    print("|-------------|------------|-----------------------------|-------------|")
    rows = [
        ("p=61,q=53 (toy)", 12, "instant", "BROKEN (trivial)"),
        ("512-bit", 512, "~weeks on a cluster", "BROKEN (2009)"),
        ("768-bit", 768, "~1500 CPU-years (record)", "BROKEN (2009, Kleinjung)"),
        ("1024-bit", 1024, "estimated feasible for nation-states", "deprecated"),
        ("2048-bit", 2048, "infeasible today", "current minimum"),
        ("3072-bit", 3072, "infeasible for decades", "recommended"),
        ("4096-bit", 4096, "very hard; diminishing returns", "conservative"),
    ]
    for name, bits, effort, status in rows:
        print(f"| {name:<11} | {bits:<10} | {effort:<27} | {status:<11} |")
    print()
    print("The gap between 'easy to multiply' and 'hard to factor' is RSA's")
    print("whole leverage: multiplying two 1024-bit primes to get n is fast,")
    print("but recovering them from n alone is (we believe) infeasible.\n")
    # note on the textbook-RSA caveats
    print("TEXTBOOK RSA (what this file implements) is NOT secure as-is. Real")
    print("deployments add PADDING (OAEP for encryption, PSS for signatures)")
    print("to defeat chosen-ciphertext and malleability attacks. Without")
    print("padding, RSA is multiplicatively homomorphic:")
    c1 = encrypt(7, PUB)
    c2 = encrypt(11, PUB)
    c77 = encrypt(77, PUB)  # 77 = 7*11
    print(f"  enc(7)*enc(11) mod n = {c1}*{c2} mod {n} = {(c1 * c2) % n}")
    print(f"  enc(7*11) = enc(77)            = {c77}")
    print(f"  equal? {((c1 * c2) % n) == c77}   <- an attacker can combine ciphertexts")
    assert ((c1 * c2) % n) == c77
    print("\nThat is why real RSA wraps every m in randomized padding before")
    print("exponentiating. 🔗 The padding is hashed — see SHA256.md for how a")
    print("cryptographic hash is built. (hashlib imported only to make the")
    print("point that core RSA uses NO hashing internally.)")
    _ = hashlib  # silence unused import; kept to make the §E point above


# ----------------------------------------------------------------------------
# SECTION F: GOLD values pinned for rsa.html (JS re-computes & compares)
# ----------------------------------------------------------------------------


def section_gold():
    banner("SECTION F: GOLD values for rsa.html")
    n = P * Q
    d = PRIV[1]
    print(f"Keys: p={P}, q={Q}, n={n}, e={E}, d={d}\n")
    # the gold message: m=65 ('A')
    m_gold = 65
    c_gold = encrypt(m_gold, PUB)
    print(f"GOLD encrypt:  m={m_gold} ('{chr(m_gold)}')  ->  c = m^e mod n = {c_gold}")
    print(f"GOLD decrypt:  c={c_gold}  ->  m = c^d mod n = {decrypt(c_gold, PRIV)}")
    assert decrypt(c_gold, PRIV) == m_gold
    # gold signature
    m_sig = 42
    s_gold = sign(m_sig, PRIV)
    print(f"GOLD sign:     m={m_sig}  ->  s = m^d mod n = {s_gold}")
    print(f"GOLD verify:   s={s_gold}  ->  m = s^e mod n = {verify(s_gold, PUB)}")
    assert verify(s_gold, PUB) == m_sig
    # a compact scalar the .html checks
    print(f"\nGOLD scalar (compact .html check): encrypt(65) = {c_gold}")
    print(
        f"GOLD scalar (compact .html check): verify(sign(42)) = {verify(s_gold, PUB)}"
    )
    print("\nThe .html re-derives (n,e,d) from p=61,q=53 and recomputes these")
    print("values in JS, checking against the numbers above.")


# ============================================================================
# main
# ============================================================================


def main():
    print("rsa.py - reference impl. All numbers below feed RSA.md.")
    print("pure Python stdlib, deterministic (no randomness).\n")
    print(f"keys: p={P}, q={Q}, e={E}   (toy primes for printable numbers)\n")

    section_keygen()
    section_encrypt_decrypt()
    section_sign_verify()
    section_why_it_works()
    section_security()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
