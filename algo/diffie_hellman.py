"""
diffie_hellman.py - Reference implementation of the Diffie-Hellman key
exchange (Diffie & Hellman 1976).

This is the single source of truth that DIFFIE_HELLMAN.md is built from.
Every number, table, and worked example in DIFFIE_HELLMAN.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    uv run python diffie_hellman.py

==========================================================================
THE INTUITION (read this first) - mixing paint, then unbending it
==========================================================================
Imagine two people who never meet want to share a SECRET PAINT COLOR. They
both start by publicly agreeing on a bucket of YELLOW paint (public). Each
privately adds their OWN secret pigment - Alice adds red, Bob adds blue -
and each PUBLISHES their mixed bucket. Now anyone can SEE the two mixed
buckets, but un-mixing paint is practically impossible: you cannot recover
"red" from "orange" without trying every possible pigment. The trick:
Alice takes Bob's published bucket and adds HER red; Bob takes Alice's
published bucket and adds HIS blue. Both end up with yellow+red+blue = the
SAME muddy brown. An eavesdropper, seeing only yellow, orange, and green,
can never make the same brown.

Diffie-Hellman (1976) is that idea done with NUMBERS instead of paint:

  * PUBLIC     : a big prime p and a generator g. Everyone knows these.
  * PRIVATE    : Alice picks secret a; Bob picks secret b. Never shared.
  * PUBLIC KEYS: Alice publishes A = g^a mod p; Bob publishes B = g^b mod p.
  * SHARED     : Alice computes B^a mod p; Bob computes A^b mod p.
                 BOTH equal g^(a*b) mod p - the shared secret.

Why an eavesdropper is stuck: they see p, g, A, B. To get g^(ab) they need
a*b, but recovering a from A = g^a mod p is the DISCRETE LOGARITHM PROBLEM
- believed intractable for well-chosen p. "Mixing" = modular
exponentiation; "un-mixing" = discrete log. Easy one way, brutal the other.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  prime p        : a large public prime. The size of the "clock" we wrap on.
  generator g    : a public base whose powers hit (almost) every residue.
                   With the right g, {g^1, g^2, ..., g^(p-1)} covers all of
                   1..p-1 (g is a "primitive root").
  private key a  : Alice's secret exponent, chosen at random in 1..p-1.
  public key A   : what Alice SENDS, = g^a mod p. Safe to broadcast.
  shared secret  : the number both sides land on = g^(a*b) mod p.
  modular exp    : g^e mod p, computed fast by square-and-multiply (Python's
                   built-in pow(g, e, p)). No big numbers ever sit in memory.
  discrete log   : the INVERSE of modular exp: given g and A=g^a mod p, find
                   a. This is the one-way property DH leans on.
  mod p          : "take the remainder mod p" - keeps every number < p.

==========================================================================
HISTORY / PAPERS
==========================================================================
  - Diffie & Hellman (1976), "New Directions in Cryptography", IEEE Trans.
    Inf. Theory, IT-22(6). Introduced public-key exchange + the concept of
    a one-way function underpinning it. 🔗 Pair with DIGITAL_SIGNATURES.md:
    DH alone has NO authentication -> it is vulnerable to a man-in-the-middle.
    Signatures (RSA, DSA, ECDSA) authenticate the channel that DH builds.
  - Diffie-Hellman is the key-agreement step of TLS (historically), SSH,
    IPsec, Signal's X3DH, and many VPN protocols.
  - Related: ECDH (elliptic-curve DH) uses points on a curve instead of
    integers; same idea, smaller keys for the same security.

DETERMINISM NOTE: every exponent is FIXED in this file (a=6, b=15, ...) so
the worked example is byte-identical every run. Real systems draw a,b at
random from 1..p-1.

KEY FORMULAS (all asserted in code):
    public key   A = g^a mod p            (Alice)
    public key   B = g^b mod p            (Bob)
    shared       s = B^a mod p = A^b mod p = g^(a*b) mod p
    correctness  B^a = (g^b)^a = g^(a*b) ; A^b = (g^a)^b = g^(a*b)  (equal)
    security     given g, g^a mod p, finding a = DISCRETE LOG (hard for big p)
    group order  = p - 1   (for a primitive root g over Z_p*)
"""

from __future__ import annotations

BANNER = "=" * 72

# ---- the worked example: small enough to print, big enough to be real ----
# p = 23 is the classic textbook prime (used in countless DH lectures).
# g = 5 is a PRIMITIVE ROOT mod 23: its powers cycle through all of 1..22.
P = 23
G = 5
ALICE_SECRET_A = 6   # Alice's private exponent
BOB_SECRET_B = 15    # Bob's private exponent


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code DIFFIE_HELLMAN.md walks)
# ============================================================================

def is_primitive_root(g: int, p: int) -> bool:
    """True if g is a primitive root mod p: its powers generate all of 1..p-1.

    We simply check that {g^1, g^2, ..., g^(p-1)} mod p == {1, 2, ..., p-1}.
    Only meaningful when p is prime (so the group Z_p* has order p-1).
    """
    seen = {pow(g, e, p) for e in range(1, p)}
    return seen == set(range(1, p))


def alice_public(g: int, a: int, p: int) -> int:
    """Alice's public value A = g^a mod p."""
    return pow(g, a, p)


def bob_public(g: int, b: int, p: int) -> int:
    """Bob's public value B = g^b mod p."""
    return pow(g, b, p)


def shared_secret_from_bob_public(B: int, a: int, p: int) -> int:
    """Alice computes the shared secret = B^a mod p."""
    return pow(B, a, p)


def shared_secret_from_alice_public(A: int, b: int, p: int) -> int:
    """Bob computes the shared secret = A^b mod p."""
    return pow(A, b, p)


def discrete_log_bruteforce(g: int, target: int, p: int) -> tuple[int, int]:
    """Brute-force discrete log: find x with g^x mod p == target.

    Returns (x, tries). This is the ATTACK an eavesdropper must run. It is
    O(p) - fine for p=23, utterly hopeless for a 2048-bit p (~2^112 work with
    the best known sub-exponential algorithms).
    """
    acc = 1
    for x in range(1, p):
        acc = (acc * g) % p           # acc = g^x mod p, built incrementally
        if acc == target:
            return x, x
    raise ValueError(f"{target} is not in <{g}> mod {p}")


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def pow_table(g: int, p: int, limit: int | None = None) -> list[tuple[int, int]]:
    """List [(exponent, g^exp mod p)] up to `limit` (default p-1)."""
    if limit is None:
        limit = p - 1
    return [(e, pow(g, e, p)) for e in range(1, limit + 1)]


# ============================================================================
# 3. SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the algorithm walkthrough - the math, step by step
# ----------------------------------------------------------------------------

def section_algorithm_walkthrough():
    banner("SECTION A: the algorithm walkthrough  (the math, step by step)")
    print(f"Public params: prime p = {P}, generator g = {G}\n")
    # prove g is a primitive root
    prim = is_primitive_root(G, P)
    print(f"[check] is g={G} a primitive root mod {P}?  {prim}  "
          f"(its powers cover all of 1..{P-1})")
    assert prim
    print(f"\nThe 'public clock' is Z_{P}* = {{1, 2, ..., {P-1}}}, which has "
          f"order p-1 = {P-1}.")
    print("g is a generator, so multiplying g by itself steps through EVERY\n"
          "element before returning to 1:\n")
    print("  e   : ", "  ".join(f"{e:>2}" for e, _ in pow_table(G, P)))
    print("  g^e : ", "  ".join(f"{v:>2}" for _, v in pow_table(G, P)))
    print(f"\nAfter {P-1} steps the cycle repeats (Fermat: g^{P-1} mod {P} = 1).\n")
    print("THE PROTOCOL IN ONE LINE EACH:")
    print("  (1) agree  : Alice & Bob publish p, g                          (public)")
    print(f"      -> p={P}, g={G}")
    print("  (2) secrets: Alice picks a in 1..p-1 ; Bob picks b in 1..p-1   (private)")
    print(f"      -> a={ALICE_SECRET_A} (Alice), b={BOB_SECRET_B} (Bob)")
    print("  (3) public : Alice sends A = g^a mod p ; Bob sends B = g^b mod p")
    A = alice_public(G, ALICE_SECRET_A, P)
    B = bob_public(G, BOB_SECRET_B, P)
    print(f"      -> A = {G}^{ALICE_SECRET_A} mod {P} = {A}")
    print(f"      -> B = {G}^{BOB_SECRET_B} mod {P} = {B}")
    print("  (4) shared : Alice = B^a ; Bob = A^b  (both = g^(ab) mod p)")
    print(f"      -> these are {ALICE_SECRET_A}*{BOB_SECRET_B} = "
          f"{ALICE_SECRET_A*BOB_SECRET_B} powers of g, mod {P}")


# ----------------------------------------------------------------------------
# SECTION B: the key exchange flow - both sides land on the SAME secret
# ----------------------------------------------------------------------------

def section_key_exchange():
    banner("SECTION B: the key exchange flow  (both sides land on the SAME secret)")
    A = alice_public(G, ALICE_SECRET_A, P)
    B = bob_public(G, BOB_SECRET_B, P)
    s_alice = shared_secret_from_bob_public(B, ALICE_SECRET_A, P)
    s_bob = shared_secret_from_alice_public(A, BOB_SECRET_B, P)
    s_direct = pow(G, ALICE_SECRET_A * BOB_SECRET_B, P)

    print("WHO KNOWS WHAT:")
    print(f"  Alice : private a={ALICE_SECRET_A}, receives B={B} from Bob")
    print(f"  Bob   : private b={BOB_SECRET_B}, receives A={A} from Alice")
    print(f"  Eve   : sees p={P}, g={G}, A={A}, B={B}  (but NOT a, b, or the secret)\n")

    print("ALICE computes the shared secret:")
    print(f"  s = B^a mod p = {B}^{ALICE_SECRET_A} mod {P} = {s_alice}\n")
    print("BOB computes the shared secret:")
    print(f"  s = A^b mod p = {A}^{BOB_SECRET_B} mod {P} = {s_bob}\n")
    print("DIRECT (sanity): g^(a*b) mod p = "
          f"{G}^({ALICE_SECRET_A}*{BOB_SECRET_B}) mod {P} = {s_direct}\n")

    ok = s_alice == s_bob == s_direct
    print(f"[check] B^a == A^b == g^(ab)?  {ok}   "
          f"(Alice={s_alice}, Bob={s_bob}, direct={s_direct})")
    assert ok
    print("\nWHY they match - the algebra (nothing up the sleeve):")
    print("  B^a = (g^b)^a = g^(b*a) = g^(a*b)        (exponents multiply)")
    print("  A^b = (g^a)^b = g^(a*b)                  (same product, commutative)")
    print("So both sides compute the SAME g^(a*b) mod p without ever sending a or b.")
    print(f"\nThe shared secret is {s_alice}. That number can now feed a cipher")
    print("(e.g. as the AES key) to encrypt the conversation that follows.")


# ----------------------------------------------------------------------------
# SECTION C: security analysis - why the eavesdropper is stuck (discrete log)
# ----------------------------------------------------------------------------

def section_security():
    banner("SECTION C: security analysis  (discrete log - why Eve is stuck)")
    A = alice_public(G, ALICE_SECRET_A, P)
    print(f"Eve's goal: recover Alice's secret a from A = g^a mod p = {A}.\n")
    print("The ONLY known way (for a generic group) is brute force: try every\n"
          "exponent x and check whether g^x mod p equals the public value A.\n")
    print("Brute-force trace (Eve squares-and-multiplies, checking each step):")
    found = None
    tries = 0
    acc = 1
    for x in range(1, P):
        acc = (acc * G) % P
        tries = x
        marker = "  <- MATCH, a recovered!" if acc == A else ""
        print(f"  try x={x:>2}: g^{x:>2} mod {P} = {acc:>2}{marker}")
        if acc == A:
            found = x
            break
    print(f"\nEve finds a = {found} after {tries} tries.\n")

    # cross-check via the helper
    x_chk, n_chk = discrete_log_bruteforce(G, A, P)
    assert x_chk == found and n_chk == tries
    print(f"[check] discrete_log_bruteforce agrees: a={x_chk}, tries={n_chk}")
    print(f"[check] with a in hand, Eve computes the secret = B^a = "
          f"{bob_public(G, BOB_SECRET_B, P)}^{found} mod {P} = "
          f"{pow(bob_public(G, BOB_SECRET_B, P), found, P)}\n")

    print("THE WHOLE SECURITY RESTS ON p BEING BIG. Cost scales with p:")
    print("  | bits of p | group size | generic brute-force | best-known attack | feasible?  |")
    print("  |-----------|------------|---------------------|--------------------|------------|")
    rows = [
        (P.bit_length(), "~2^5",  "~2^5",   "~2^3",   "yes (toy)"),
        (64,            "~2^64", "~2^64", "~2^22",  "seconds"),
        (256,           "~2^256","~2^256","~2^64",  "no (huge)"),
        (2048,          "~2^2048","~2^2048","~2^112","no*        "),
    ]
    for bits, sz, brute, best, feas in rows:
        print(f"  | {bits:>9} | {sz:<10} | {brute:<19} | {best:<18} | {feas:<10} |")
    print("  *for a 2048-bit prime, generic brute force is ~2^2048, but the best")
    print("   KNOWN attack (number-field sieve) is ~2^112 - still infeasible today.")
    print("\nRead it as: doubling p's bit-length makes Eve's job EXPONENTIALLY")
    print("harder. With p=23 Eve wins instantly; with a 2048-bit p she loses.")


# ----------------------------------------------------------------------------
# SECTION D: the man-in-the-middle attack (no authentication)
# ----------------------------------------------------------------------------

def section_mitm():
    banner("SECTION D: the man-in-the-middle attack  (DH has NO authentication)")
    print("THE WEAKNESS: DH guarantees SECRECY against a passive eavesdropper,")
    print("but NOT against an ACTIVE attacker who intercepts and replaces the")
    print("public values. Alice and Bob each run DH - but with the ATTACKER.\n")

    ma = 13   # Mallory's secret for the Alice-side exchange
    mb = 3    # Mallory's secret for the Bob-side exchange
    A = alice_public(G, ALICE_SECRET_A, P)        # Alice -> meant for Bob
    B = bob_public(G, BOB_SECRET_B, P)            # Bob   -> meant for Alice
    M1 = pow(G, ma, P)     # Mallory's fake "Bob"   value sent to Alice
    M2 = pow(G, mb, P)     # Mallory's fake "Alice" value sent to Bob

    print(f"Public values on the wire: Alice sends A={A}, Bob sends B={B}.\n")
    print("Mallory INTERCEPTS both, discards them, and sends her OWN values:")
    print(f"  -> Alice receives M1 = g^{ma} mod {P} = {M1}  (thinks it's Bob's)")
    print(f"  -> Bob   receives M2 = g^{mb} mod {P} = {M2}  (thinks it's Alice's)\n")

    # what each party computes
    s_alice = pow(M1, ALICE_SECRET_A, P)          # Alice thinks: shared with Bob
    s_bob = pow(M2, BOB_SECRET_B, P)              # Bob   thinks: shared with Alice
    s_mallory_alice = pow(A, ma, P)               # Mallory matches Alice's side
    s_mallory_bob = pow(B, mb, P)                 # Mallory matches Bob's side

    print("RESULTING shared secrets (there are now TWO, not one):")
    print(f"  Alice   <-> Mallory : Alice = M1^a = {M1}^{ALICE_SECRET_A} = {s_alice}")
    print(f"                       Mallory = A^ma = {A}^{ma} = {s_mallory_alice}")
    print(f"  Bob     <-> Mallory : Bob   = M2^b = {M2}^{BOB_SECRET_B} = {s_bob}")
    print(f"                       Mallory = B^mb = {B}^{mb} = {s_mallory_bob}\n")

    ok = (s_alice == s_mallory_alice) and (s_bob == s_mallory_bob) and (s_alice != s_bob)
    print(f"[check] Mallory matches both sides, and the two secrets differ?  {ok}")
    assert ok
    print(f"  Alice's secret {s_alice} == Mallory's view of Alice: {s_mallory_alice}")
    print(f"  Bob's   secret {s_bob}   == Mallory's view of Bob:   {s_mallory_bob}")
    print(f"  Alice and Bob hold DIFFERENT secrets ({s_alice} vs {s_bob}) -> they are")
    print("  NOT actually talking to each other. Mallory decrypts every message")
    print("  from Alice, re-encrypts under Bob's secret, and vice versa.\n")
    print("THE FIX: authenticate the channel FIRST. In TLS this is done with")
    print("DIGITAL SIGNATURES (RSA/ECDSA on the server's DH public value) - see")
    print("DIGITAL_SIGNATURES.md. 🔗 Without a signature, DH is blind to who you")
    print("are keying with.")


# ----------------------------------------------------------------------------
# SECTION E: applications
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION E: applications  (where Diffie-Hellman lives in the wild)")
    rows = [
        ("TLS / HTTPS", "web encryption",
         "Key exchange (DHE/ECDHE) negotiates the session key; the server's"),
        ("", "",
         "DH public value is SIGNED (RSA/ECDSA) to stop MITM. 'Forward secrecy'."),
        ("SSH", "secure shell",
         "diffie-hellman-group14/16 + Ed25519 host signature."),
        ("Signal (X3DH)", "end-to-end messaging",
         "Extended triple-DH: 3 DH rounds build the root key; long-term"),
        ("", "",
         "identity keys authenticate, ephemeral keys give forward secrecy."),
        ("IPsec (IKE)", "VPN tunnels",
         "IKE phases use DH to derive keys for the encrypted tunnel."),
        ("Bitcoin (BIP-?)", "wallet / ECDH",
         "ECDH on secp256k1 for address derivation / payment codes."),
    ]
    print("| protocol        | domain             | role of Diffie-Hellman              |")
    print("|-----------------|--------------------|-------------------------------------|")
    for name, dom, role in rows:
        if name:
            print(f"| {name:<15} | {dom:<18} | {role:<37} |")
        else:
            print(f"| {'':<15} | {'':<18} | {role:<37} |")
    print()
    print("FORWARD SECRECY (the headline property): if you use a FRESH a,b per")
    print("session (ephemeral DH = DHE), then a later leak of the long-term key")
    print("CANNOT decrypt old sessions - the per-session a,b are gone. This is")
    print("why modern TLS mandates ECDHE even when RSA keys are present.\n")
    print("VARIANTS:")
    print("  - DH    : integer modular arithmetic (this file).")
    print("  - ECDH  : same idea on an elliptic curve; 256-bit keys ~= 3072-bit")
    print("            RSA security. The dominant choice today.")
    print("  - X25519: a specific fast ECDH curve (Curve25519, Bernstein 2006).")


# ----------------------------------------------------------------------------
# SECTION F: GOLD values for diffie_hellman.html (JS rebuilds & compares)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION F: GOLD values for diffie_hellman.html  (rebuild in JS)")
    A = alice_public(G, ALICE_SECRET_A, P)
    B = bob_public(G, BOB_SECRET_B, P)
    s = pow(B, ALICE_SECRET_A, P)
    print(f"gold public params : p={P}, g={G}")
    print(f"gold secrets       : a={ALICE_SECRET_A} (Alice), b={BOB_SECRET_B} (Bob)")
    print(f"gold public A      = g^a mod p = {G}^{ALICE_SECRET_A} mod {P} = {A}")
    print(f"gold public B      = g^b mod p = {G}^{BOB_SECRET_B} mod {P} = {B}")
    print(f"gold shared secret = B^a mod p = {B}^{ALICE_SECRET_A} mod {P} = {s}")
    print(f"gold shared secret = A^b mod p = {A}^{BOB_SECRET_B} mod {P} = "
          f"{pow(A, BOB_SECRET_B, P)}")
    print(f"gold shared secret = g^(ab)    = {G}^{ALICE_SECRET_A*BOB_SECRET_B} mod "
          f"{P} = {pow(G, ALICE_SECRET_A*BOB_SECRET_B, P)}\n")
    ok = (pow(B, ALICE_SECRET_A, P) == pow(A, BOB_SECRET_B, P)
          == pow(G, ALICE_SECRET_A*BOB_SECRET_B, P) == s)
    print(f"[check] gold B^a == A^b == g^(ab) == {s}?  {ok}")
    assert ok
    # brute-force discrete log on A (how many tries for the toy case)
    _, tries = discrete_log_bruteforce(G, A, P)
    print(f"[check] gold discrete log of A needs {tries} tries (toy p={P})")
    print("\nThe .html re-runs this exact exchange in JS (same p, g, a, b) and")
    print(f"verifies the shared secret equals {s}.")


# ============================================================================
# main
# ============================================================================

def main():
    print("diffie_hellman.py - reference impl. All numbers below feed "
          "DIFFIE_HELLMAN.md.")
    print("pure Python stdlib, deterministic (fixed exponents a=6, b=15).\n")

    section_algorithm_walkthrough()
    section_key_exchange()
    section_security()
    section_mitm()
    section_applications()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
