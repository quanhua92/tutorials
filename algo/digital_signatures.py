"""
digital_signatures.py - Reference implementation of digital signatures:
RSA signatures, ECDSA (elliptic-curve), and HMAC (symmetric MAC).

This is the single source of truth that DIGITAL_SIGNATURES.md is built from.
Every number, table, and worked example in DIGITAL_SIGNATURES.md is printed
by this file. If you change something here, re-run and re-paste the output.

Run:
    uv run python digital_signatures.py

==========================================================================
THE INTUITION (read this first) - a wax seal you can verify but not forge
==========================================================================
A hand-written signature proves WHO wrote a document. A DIGITAL signature
adds two things a wax seal can't: it proves the document has NOT been
CHANGED (integrity), and the signer CANNOT later deny signing it
(non-repudiation). The trick is ASYMMETRY - a key pair where one half
signs and the other half verifies:

  * PRIVATE key (d) : the signer's wax ring. Used to SEAL. Kept secret.
  * PUBLIC  key (e) : published, so anyone can CHECK the seal. Cannot forge.

The core idea is a TRAPDOOR one-way function - easy in one direction
(sign/verify), impossible to reverse (forge a signature without d):

  * RSA sign    : sig = hash(m)^d mod n        (sealed with private d)
  * RSA verify  : check sig^e mod n == hash(m)  (opened with public e)

Because only the holder of d can produce a sig whose e-th power lands on
the hash, a matching signature is PROOF of authorship + integrity.

Three flavours, all implemented here from scratch:

  * RSA     : integer arithmetic. sign = H(m)^d mod n. Classic (1978).
  * ECDSA   : elliptic-curve points. Smaller keys, same security.
              Used by Bitcoin, TLS, Apple Secure Enclave.
  * HMAC    : NOT asymmetric - a SHARED key tags a message. No
              non-repudiation (both parties share the key), but it is fast
              and proves the message came from someone holding the key.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  private key d  : the secret exponent/point used to SIGN. Never shared.
  public  key    : (n, e) for RSA, or the point Q = d*G for ECDSA. Anyone
                   can verify with it; nobody can derive d from it.
  hash H(m)      : a fixed-size fingerprint of the message. Any change to m
                   (even one bit) flips ~half the output bits. We sign the
                   HASH, not the whole message (speed + fixed size).
  signature      : the pair (r, s) [ECDSA] or single int sig [RSA] that the
                   signer outputs alongside the message.
  verify         : recompute the expected value from m and the public key,
                   compare to the signature. Match => authentic + intact.
  non-repudiation: only the private-key holder could have made the signature,
                   so they cannot later deny it. (HMAC does NOT give this.)
  trapdoor       : easy one way, hard the other. (x -> x^e is easy; sig ->
                   d is the discrete log / factoring problem.)
  modinv x^-1    : the number y with x*y == 1 mod n. Computed fast via the
                   extended Euclidean algorithm (Python's pow(x, -1, n)).

==========================================================================
HISTORY / PAPERS
==========================================================================
  - Diffie & Hellman (1976), "New Directions in Cryptography" - first
    described the idea of a digital signature using public-key crypto.
  - Rivest, Shamir, Adleman (1978), "A Method for Obtaining Digital
    Signatures and Public-Key Cryptosystems". The RSA scheme. 🔗 Pair with
    DIFFIE_HELLMAN.md: RSA signatures authenticate the DH channel, killing
    the man-in-the-middle attack.
  - ElGamal (1985) signatures -> DSA (FIPS 186) -> ECDSA (with elliptic
    curves, Koblitz/Miller 1985). Used in Bitcoin (secp256k1), TLS, SSH.
  - Bellare, Canetti, Krawczyk (1996) - formal security of HMAC; HMAC
    became FIPS 198 / RFC 2104.

DETERMINISM NOTE: all keys, messages, and the ECDSA nonce k are FIXED in
this file, so every worked example is byte-identical every run. Real
systems draw d and k from a CSPRNG.

KEY FORMULAS (all asserted in code):
  RSA keygen : n = p*q ; phi = (p-1)(q-1) ; e*d == 1 mod phi
  RSA sign   : sig = H(m)^d mod n
  RSA verify : sig^e mod n == H(m)        (accept if equal)
  ECDSA pub  : Q = d * G   (scalar mult on the curve)
  ECDSA sign : r = (k*G).x mod n ; s = k^-1 (H(m) + r*d) mod n
  ECDSA vfy  : w = s^-1 ; (x1,_) = H(m)*w * G + r*w * Q ; accept r == x1 mod n
  HMAC       : tag = H( (k ^ opad) || H( (k ^ ipad) || m ) )
==========================================================================
"""

from __future__ import annotations

import hashlib

BANNER = "=" * 72


# ============================================================================
# 1. RSA - keygen, sign, verify  (textbook small primes)
# ============================================================================

# Classic textbook RSA primes (used in countless lectures). Small enough to
# print, large enough to show the full mechanics.
RSA_P = 61
RSA_Q = 53
RSA_E = 17  # public exponent (must be coprime with phi)


def rsa_keygen(p: int, q: int, e: int) -> tuple[int, int, int]:
    """RSA key generation. Returns (n, e, d).

    n = p*q (public modulus), phi = (p-1)(q-1), d = e^-1 mod phi (private).
    """
    n = p * q
    phi = (p - 1) * (q - 1)
    d = pow(e, -1, phi)        # modular inverse (extended Euclid)
    return n, e, d


def hash_to_int(msg: bytes, mod: int) -> int:
    """Map a message to an integer < mod via SHA-256.

    We take the leftmost bitlen(mod) bits of the hash (the standard ECDSA/RSA
    "leftmost bits" rule) then reduce mod `mod`. Deterministic.
    """
    h = hashlib.sha256(msg).digest()
    val = int.from_bytes(h, "big")
    bl = mod.bit_length()
    if 256 > bl:
        val >>= (256 - bl)         # keep leftmost bl bits
    return val % mod


def rsa_sign(msg: bytes, d: int, n: int) -> int:
    """RSA signature: sig = H(m)^d mod n. The signer seals with d."""
    m = hash_to_int(msg, n)
    return pow(m, d, n)


def rsa_verify(msg: bytes, sig: int, e: int, n: int) -> bool:
    """RSA verification: sig^e mod n == H(m)? Accept iff equal."""
    m = hash_to_int(msg, n)
    return pow(sig, e, n) == m


# ============================================================================
# 2. ELLIPTIC-CURVE ARITHMETIC (for ECDSA) over a tiny curve
# ============================================================================

# Curve: y^2 = x^3 + 2x + 2 mod 17. A classic textbook curve (Hankerson et al).
# Small enough to draw every point, big enough to demonstrate ECDSA fully.
EC_A = 2
EC_B = 2
EC_P = 17
EC_G = (5, 1)   # a point on the curve; its order n is found below


def ec_on_curve(pt: tuple[int, int]) -> bool:
    """True if pt lies on y^2 = x^3 + a x + b mod p."""
    if pt is None:
        return True
    x, y = pt
    return (y * y - (x * x * x + EC_A * x + EC_B)) % EC_P == 0


def ec_add(P: tuple[int, int] | None, Q: tuple[int, int] | None) -> tuple[int, int] | None:
    """Elliptic-curve point addition over F_p (short Weierstrass form).

    None is the point at infinity (group identity). Handles P+Q, P+P
    (doubling), and P + (-P) = infinity.
    """
    if P is None:
        return Q
    if Q is None:
        return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2 and (y1 + y2) % EC_P == 0:
        return None                          # P + (-P) = infinity
    if x1 == x2:
        # doubling: lambda = (3 x^2 + a) / (2 y)
        lam = (3 * x1 * x1 + EC_A) * pow(2 * y1, -1, EC_P) % EC_P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, EC_P) % EC_P
    x3 = (lam * lam - x1 - x2) % EC_P
    y3 = (lam * (x1 - x3) - y1) % EC_P
    return (x3, y3)


def ec_mul(k: int, P: tuple[int, int] | None) -> tuple[int, int] | None:
    """Scalar multiplication k*P via double-and-add (left to right)."""
    result = None
    addend = P
    while k > 0:
        if k & 1:
            result = ec_add(result, addend)
        addend = ec_add(addend, addend)
        k >>= 1
    return result


def ec_order(P: tuple[int, int]) -> int:
    """Order of point P = smallest n > 0 with n*P == infinity."""
    acc = P
    n = 1
    while acc is not None:
        acc = ec_add(acc, P)
        n += 1
    return n


# ECDSA over the tiny curve
EC_N = ec_order(EC_G)   # subgroup order (computed, not hand-picked)


def ecdsa_keygen(d: int) -> tuple[int, tuple[int, int]]:
    """Private d -> public Q = d*G."""
    Q = ec_mul(d, EC_G)
    assert Q is not None
    return d, Q


def _hash_trunc(msg: bytes, n: int) -> int:
    """Leftmost bitlen(n) bits of H(m), reduced mod n (same as hash_to_int)."""
    return hash_to_int(msg, n)


def ecdsa_sign(msg: bytes, d: int, k: int) -> tuple[int, int]:
    """ECDSA sign. Returns (r, s). k is the per-signature secret nonce."""
    e = _hash_trunc(msg, EC_N)
    R = ec_mul(k, EC_G)
    assert R is not None
    r = R[0] % EC_N
    s = (pow(k, -1, EC_N) * (e + r * d)) % EC_N
    assert r != 0 and s != 0
    return r, s


def ecdsa_verify(msg: bytes, sig: tuple[int, int], Q: tuple[int, int]) -> bool:
    """ECDSA verify. Recompute r from (m, Q, (r,s)); accept iff equal."""
    r, s = sig
    if not (1 <= r < EC_N and 1 <= s < EC_N):
        return False
    e = _hash_trunc(msg, EC_N)
    w = pow(s, -1, EC_N)
    u1 = (e * w) % EC_N
    u2 = (r * w) % EC_N
    X = ec_add(ec_mul(u1, EC_G), ec_mul(u2, Q))
    if X is None:
        return False
    return (X[0] % EC_N) == r


# ============================================================================
# 3. HMAC (symmetric message authentication) from scratch
# ============================================================================

HMAC_BLOCK = 64                  # SHA-256 block size in bytes
HMAC_IPAD = 0x36
HMAC_OPAD = 0x5c


def _xor_bytes(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    """HMAC-SHA256 from scratch (RFC 2104 / FIPS 198).

    tag = H( (k ^ opad) || H( (k ^ ipad) || m ) )
    Keys shorter than the block are padded with zeros; longer keys are
    hashed first (then padded). ipad/opad are fixed constants.
    """
    if len(key) > HMAC_BLOCK:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (HMAC_BLOCK - len(key))
    inner = hashlib.sha256(_xor_bytes(key, bytes([HMAC_IPAD] * HMAC_BLOCK)) + msg).digest()
    outer = hashlib.sha256(_xor_bytes(key, bytes([HMAC_OPAD] * HMAC_BLOCK)) + inner).digest()
    return outer


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def pt_str(pt) -> str:
    return "O" if pt is None else f"({pt[0]},{pt[1]})"


# ============================================================================
# 5. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: RSA algorithm walkthrough (keygen + sign + verify)
# ----------------------------------------------------------------------------

def section_rsa_walkthrough():
    banner("SECTION A: RSA signatures - the algorithm walkthrough")
    print(f"Textbook primes: p={RSA_P}, q={RSA_Q}, public exponent e={RSA_E}\n")
    n, e, d = rsa_keygen(RSA_P, RSA_Q, RSA_E)
    phi = (RSA_P - 1) * (RSA_Q - 1)
    print("KEY GENERATION:")
    print(f"  n   = p*q        = {RSA_P}*{RSA_Q} = {n}        (public modulus)")
    print(f"  phi = (p-1)(q-1) = {RSA_P-1}*{RSA_Q-1} = {phi}   (Euler totient)")
    print(f"  d   = e^-1 mod phi = {RSA_E}^-1 mod {phi} = {d}    (private key)")
    print(f"  check: e*d mod phi = {RSA_E}*{d} mod {phi} = {(RSA_E*d)%phi}\n")
    print("PUBLIC KEY  = (n, e) = " f"({n}, {e})   -> publish this")
    print(f"PRIVATE KEY = (n, d) = ({n}, {d})  -> KEEP SECRET\n")
    print("THE TRAPDOOR: computing d needs phi, which needs the factors p,q.")
    print("Factoring n=3233 is trivial; factoring a 2048-bit n is infeasible.")
    print("That gap is ALL of RSA's security.\n")
    print("SIGN / VERIFY formulas:")
    print("  sign   : sig = H(m)^d mod n        (sealed with private d)")
    print("  verify : sig^e mod n == H(m)?      (opened with public e)")
    ok = (RSA_E * d) % phi == 1
    print(f"\n[check] e*d == 1 mod phi?  {ok}")
    assert ok


# ----------------------------------------------------------------------------
# SECTION B: the sign-then-verify flow (RSA round trip)
# ----------------------------------------------------------------------------

def section_sign_verify_flow():
    banner("SECTION B: the sign-then-verify flow  (RSA round trip)")
    n, e, d = rsa_keygen(RSA_P, RSA_Q, RSA_E)
    msg = b"hello"
    print(f"message m = {msg!r}\n")
    hm = hash_to_int(msg, n)
    print(f"Step 1 - hash: H(m) = SHA-256 leftmost {n.bit_length()}-bits mod {n} = {hm}\n")

    sig = rsa_sign(msg, d, n)
    print("Step 2 - SIGN (Alice, with private d):")
    print(f"  sig = H(m)^d mod n = {hm}^{d} mod {n} = {sig}\n")

    print("Step 3 - VERIFY (Bob, with public e):")
    recovered = pow(sig, e, n)
    print(f"  sig^e mod n = {sig}^{e} mod {n} = {recovered}")
    print(f"  H(m)        = {hm}")
    ok = recovered == hm
    print(f"  match? {recovered} == {hm} -> {ok}\n")
    print("[check] rsa_verify(m, sig, e, n)?  " + str(rsa_verify(msg, sig, e, n)))
    assert rsa_verify(msg, sig, e, n)
    print("\nBob never sees d. He only needed the PUBLIC (n, e) and the signature")
    print("to confirm Alice authored 'hello' and it was not altered in transit.")


# ----------------------------------------------------------------------------
# SECTION C: tampering detection (modified message -> signature fails)
# ----------------------------------------------------------------------------

def section_tampering():
    banner("SECTION C: tampering detection  (modified message -> signature FAILS)")
    n, e, d = rsa_keygen(RSA_P, RSA_Q, RSA_E)
    msg = b"hello"
    sig = rsa_sign(msg, d, n)
    print(f'Alice signs m="{msg.decode()}" -> sig = {sig}\n')
    print("Now an attacker flips ONE character of the message in transit:\n")

    tampered = b"hellp"
    hm_orig = hash_to_int(msg, n)
    hm_tamp = hash_to_int(tampered, n)
    print(f'  original m="{msg.decode()}"  -> H(m) = {hm_orig}')
    print(f'  tampered m="{tampered.decode()}"  -> H(m) = {hm_tamp}')
    print("  (one bit of m flips ~half the hash bits -> totally different H(m))\n")

    print("Bob verifies the tampered message with the SAME signature:")
    rec = pow(sig, e, n)
    print(f"  sig^e mod n = {rec}")
    print(f"  H(tampered) = {hm_tamp}")
    ok = rsa_verify(tampered, sig, e, n)
    print(f"  match? {rec} == {hm_tamp} -> {ok}\n")
    print(f"[check] verify original  ?  {rsa_verify(msg, sig, e, n)}")
    print(f"[check] verify tampered  ?  {rsa_verify(tampered, sig, e, n)}")
    assert rsa_verify(msg, sig, e, n) and not rsa_verify(tampered, sig, e, n)
    print("\nThe signature is BOUND to the exact bytes signed. Change one bit and")
    print("verification fails - that is the INTEGRITY guarantee. A wax seal that")
    print("shatters if anyone so much as breathes on the document.")


# ----------------------------------------------------------------------------
# SECTION D: ECDSA - elliptic-curve signatures
# ----------------------------------------------------------------------------

def section_ecdsa():
    banner("SECTION D: ECDSA - elliptic-curve signatures")
    print(f"Tiny curve: y^2 = x^3 + {EC_A}x + {EC_B}  (mod {EC_P})")
    print(f"Generator G = {EC_G}, on curve? {ec_on_curve(EC_G)}\n")
    # list all curve points
    pts = []
    for x in range(EC_P):
        rhs = (x * x * x + EC_A * x + EC_B) % EC_P
        for y in range(EC_P):
            if (y * y) % EC_P == rhs:
                pts.append((x, y))
    print(f"The curve has {len(pts)+1} points (+the point at infinity O):")
    print("  " + ", ".join(pt_str(p) for p in pts) + ", O\n")

    print(f"Order of G (smallest n with n*G = O): n = {EC_N}")
    check_order = ec_mul(EC_N, EC_G)
    print(f"[check] {EC_N}*G = {pt_str(check_order)} (infinity)? {check_order is None}")
    assert check_order is None

    d = 7           # private key
    k = 11          # signing nonce
    msg = b"curve"
    _, Q = ecdsa_keygen(d)
    print(f"\nprivate key d = {d}  ->  public key Q = d*G = {d}*{EC_G} = {pt_str(Q)}")
    print(f"Q on curve? {ec_on_curve(Q)}\n")

    r, s = ecdsa_sign(msg, d, k)
    e = _hash_trunc(msg, EC_N)
    print(f'Sign m="{msg.decode()}":')
    print(f"  H(m) truncated to {EC_N.bit_length()} bits mod {EC_N} = {e}")
    print(f"  k = {k}, k*G = {pt_str(ec_mul(k, EC_G))}")
    print(f"  r = (k*G).x mod n = {r}")
    print(f"  s = k^-1 * (H(m) + r*d) mod n = {pow(k,-1,EC_N)} * ({e}+{r}*{d}) mod {EC_N} = {s}")
    print(f"  -> signature (r, s) = ({r}, {s})\n")

    print(f'Verify m="{msg.decode()}" with public Q={pt_str(Q)}:')
    w = pow(s, -1, EC_N)
    u1 = (e * w) % EC_N
    u2 = (r * w) % EC_N
    X = ec_add(ec_mul(u1, EC_G), ec_mul(u2, Q))
    print(f"  w = s^-1 mod n = {w}")
    print(f"  u1 = H(m)*w = {u1}, u2 = r*w = {u2}")
    print(f"  X = u1*G + u2*Q = {u1}*G + {u2}*Q = {pt_str(X)}")
    print(f"  r == X.x mod n ?  {r} == {X[0] % EC_N}  -> {r == X[0]%EC_N}\n")
    ok = ecdsa_verify(msg, (r, s), Q)
    print(f"[check] ecdsa_verify(m, sig, Q)?  {ok}")
    assert ok

    # tampered ECDSA verification
    bad = ecdsa_verify(b"curvE", (r, s), Q)
    print(f"[check] ecdsa_verify(tampered 'curvE', sig, Q)?  {bad}")
    assert not bad
    print("\nSame guarantee as RSA: one byte changed -> verification fails.")
    print("WHY ECDSA WINS in practice: a 256-bit ECDSA key matches a 3072-bit")
    print("RSA key for security, with signatures ~64 bytes vs ~256. That is why")
    print("Bitcoin, TLS, and Apple's Secure Enclave all use ECDSA/Ed25519.")


# ----------------------------------------------------------------------------
# SECTION E: HMAC - symmetric message authentication
# ----------------------------------------------------------------------------

def section_hmac():
    banner("SECTION E: HMAC - symmetric message authentication")
    print("HMAC is NOT asymmetric: BOTH parties share the SAME key. There is no")
    print("public key, so HMAC gives authentication + integrity but NOT")
    print("non-repudiation (either party could have made the tag).\n")
    key = b"secret-key"
    msg = b"transfer $100"
    print(f"key  = {key!r}  (shared, secret)")
    print(f"msg  = {msg!r}\n")
    print("CONSTRUCTION (RFC 2104):")
    print(f"  block size = {HMAC_BLOCK} bytes ; ipad = 0x{HMAC_IPAD:02x}, opad = 0x{HMAC_OPAD:02x}")
    print("  tag = H( (k ^ opad) || H( (k ^ ipad) || m ) )\n")

    tag = hmac_sha256(key, msg)
    inner = hashlib.sha256(_xor_bytes(key.ljust(HMAC_BLOCK, b"\x00"),
                                      bytes([HMAC_IPAD]*HMAC_BLOCK)) + msg).digest()
    print(f"inner = H( (k^ipad) || m ) = {inner.hex()}")
    print(f"tag   = H( (k^opad) || inner ) = {tag.hex()}\n")

    ok = hmac_sha256(key, msg) == tag
    print(f"[check] recompute tag matches?  {ok}")
    assert ok
    # tamper detection
    bad = hmac_sha256(key, b"transfer $900") == tag
    print(f"[check] tag of tampered 'transfer $900' matches?  {bad}  (must be False)")
    assert not bad
    # wrong key
    wrong = hmac_sha256(b"wrong-key", msg) == tag
    print(f"[check] tag with wrong key matches?  {wrong}  (must be False)")
    assert not wrong
    print("\nUse HMAC when two parties ALREADY share a secret and want fast")
    print("message authentication: API tokens (JWT), TLS record layer, cookie")
    print("sealing, code-deploy signatures. Use RSA/ECDSA when only one party")
    print("should be ABLE to sign (e.g. a server proving its identity).")


# ----------------------------------------------------------------------------
# SECTION F: applications + comparison
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION F: applications  (RSA vs ECDSA vs HMAC)")
    rows = [
        ("RSA", "asymmetric", "TLS certs, code signing, PGP",
         "sign = H(m)^d mod n ; slow, big keys (2048+ bits)"),
        ("ECDSA", "asymmetric", "Bitcoin, TLS, SSH, Apple enclave",
         "point math; 256-bit key ~= 3072-bit RSA; ~64-byte sig"),
        ("Ed25519", "asymmetric", "SSH, Signal, apt, age",
         "fast + deterministic ECDSA variant on Curve25519"),
        ("HMAC", "symmetric", "JWT, API auth, TLS record, cookies",
         "shared key; fast; NO non-repudiation"),
    ]
    print("| scheme  | type        | used in                         | notes                              |")
    print("|---------|-------------|---------------------------------|------------------------------------|")
    for name, typ, used, note in rows:
        print(f"| {name:<7} | {typ:<11} | {used:<31} | {note:<34} |")
    print()
    print("THE THREE GUARANTEES a signature gives:")
    print("  1. AUTHENTICITY    : only the private-key holder could sign it.")
    print("  2. INTEGRITY       : any change to m breaks verification.")
    print("  3. NON-REPUDIATION : the signer can't later deny it (only d could")
    print("                       have produced the signature). HMAC lacks #3.")
    print()
    print("WHY SIGN THE HASH, not the message?")
    print("  - SIZE: a signature operates on a fixed-size digest, not a")
    print("    gigabyte document. SHA-256 -> always 32 bytes.")
    print("  - SECURITY: SHA-256 is collision-resistant, so signing H(m) is as")
    print("    safe as signing m, for any practical message length.")


# ----------------------------------------------------------------------------
# SECTION G: GOLD values for digital_signatures.html (JS rebuilds & compares)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION G: GOLD values for digital_signatures.html  (rebuild in JS)")
    # RSA gold
    n, e, d = rsa_keygen(RSA_P, RSA_Q, RSA_E)
    msg = b"hello"
    sig = rsa_sign(msg, d, n)
    hm = hash_to_int(msg, n)
    print("RSA GOLD:")
    print(f"  p={RSA_P}, q={RSA_Q}, e={RSA_E} -> n={n}, d={d}")
    print(f'  m="{msg.decode()}"  ->  H(m) mod {n} = {hm}')
    print(f"  sig = H(m)^d mod n = {sig}")
    print(f"  sig^e mod n = {pow(sig,e,n)}  (== H(m)? {pow(sig,e,n)==hm})")
    ok = rsa_verify(msg, sig, e, n)
    print(f"  [check] rsa_verify?  {ok}")
    assert ok
    bad = rsa_verify(b"hellp", sig, e, n)
    print(f"  [check] tampered verify?  {bad}  (must be False)")
    assert not bad

    # ECDSA gold
    _, Q = ecdsa_keygen(7)
    r, s = ecdsa_sign(b"curve", 7, 11)
    print("\nECDSA GOLD:")
    print(f"  curve y^2=x^3+{EC_A}x+{EC_B} mod {EC_P}, G={EC_G}, n={EC_N}")
    print(f"  d=7 -> Q=d*G={pt_str(Q)}")
    print(f"  m=\"curve\", k=11 -> (r,s)=({r},{s})")
    ok2 = ecdsa_verify(b"curve", (r, s), Q)
    print(f"  [check] ecdsa_verify?  {ok2}")
    assert ok2
    print(f"  [check] tampered verify?  {ecdsa_verify(b'curvE',(r,s),Q)}  (must be False)")
    assert not ecdsa_verify(b"curvE", (r, s), Q)

    print("\nThe .html re-runs RSA sign/verify + ECDSA sign/verify + HMAC in JS")
    print("with these exact parameters and checks the verdicts match.")


# ============================================================================
# main
# ============================================================================

def main():
    print("digital_signatures.py - reference impl. All numbers below feed "
          "DIGITAL_SIGNATURES.md.")
    print("pure Python stdlib (hashlib only), deterministic (fixed keys).\n")

    section_rsa_walkthrough()
    section_sign_verify_flow()
    section_tampering()
    section_ecdsa()
    section_hmac()
    section_applications()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
