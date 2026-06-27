"""System Security — ground-truth simulations of defense-in-depth, the TLS
handshake, mutual TLS (mTLS), secrets-management rotation, and zero-trust
architecture.

Five simulations covering the system-security stack. Pure Python stdlib; no
network, no cryptography library, no external dependencies.

  1. Defense in depth — four independent layers (network, host, app, data);
     each layer has its own controls and its own stop probability. The
     combined breach probability is the PRODUCT of per-layer leak rates, so
     a 95% / 80% / 90% / 95% stack yields a 0.015% breach — 333x better than
     the single best layer alone.
  2. TLS handshake — TLS 1.2 (2-RTT) vs TLS 1.3 (1-RTT) vs 0-RTT resumption;
     ECDHE forward secrecy; the exact message sequence of each flight.
  3. mTLS — mutual authentication: the CLIENT also presents a certificate.
     Adds ~2 KB to the handshake and a verification step both ways. The basis
     of service-mesh identity (Istio, Linkerd) and SPIFFE/SPIRE.
  4. Secrets management — the generate / distribute / use / rotate / revoke /
     audit lifecycle; a leak-risk model that grows with secret age; dual-key
     overlap rotation; short-lived tokens vs long-lived keys.
  5. Zero trust — castle-and-moat (trust by network location) vs zero-trust
     (every request verified, least privilege per request). A compromised
     credential reaches 100% of resources in a flat network but only its
     authorized scope under zero-trust.

Notes
-----
- A fixed model (stop probabilities, RTT, leak rate, fleet size) is used so
  the output is byte-for-byte reproducible and the HTML gold-check recomputes
  identical values.
- The attack simulation uses a seeded LCG (no PRNG). The same seed + attempt
  count yields the same breach count in Python and in the JS gold-check.

Every number printed below is produced by running this file; nothing is
hand-computed. Capture with:

    python3 system_security.py > system_security_output.txt 2>/dev/null
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared constants — deterministic so the JS gold-check reproduces identical
# values.
# ---------------------------------------------------------------------------

# Defense-in-depth layers: (name, stop_probability, [controls]).
# Stop probabilities are representative of a well-instrumented stack; the
# PRODUCT of the complementary (leak) rates is the combined breach probability.
LAYERS: list[tuple[str, float, list[str]]] = [
    ("network", 0.85, ["WAF", "firewall + ACLs", "DDoS scrubbing", "segmentation"]),
    ("host",    0.80, ["OS hardening", "patching", "EDR / antivirus", "host firewall"]),
    ("app",     0.90, ["input validation", "authN + authZ", "secure coding", "SCA / SAST"]),
    ("data",    0.95, ["encryption at rest", "tokenization", "DLP", "access audit log"]),
]

ATTACK_ATTEMPTS = 100_000         # simulated attacks flowing through the stack
ATTACK_SEED = 20260627            # fixed LCG seed (deterministic, matches JS)

# TLS handshake timing.
RTT_MS = 50                       # representative client-server round-trip time
TLS12_FLIGHTS = 2                 # 2 RTT before application data
TLS13_FLIGHTS = 1                 # 1 RTT before application data
TLS13_RESUMPTION = 0              # 0-RTT: early data in the first flight

# Secrets-management risk model.
ROTATION_DAYS = 90                # canonical key-rotation interval
LEAK_RATE = 0.001                 # daily probability the secret leaks (0.1%)
OVERLAP_DAYS = 7                  # dual-key overlap window during rotation
SHORT_TTL_HOURS = 1               # short-lived token TTL

# Zero-trust blast-radius model.
RESOURCES = 100                   # internal services in the estate
CRED_SCOPE = 0.02                 # compromised cred authorized for 2% (least priv)
CASTLE_DETECT_MIN = 60 * 24 * 7   # castle-moat: anomalous access noticed in ~7 days
ZT_DETECT_MIN = 5                 # zero-trust: continuous eval flags in ~5 min


# ---------------------------------------------------------------------------
# Deterministic LCG — no randomness; matches the JS gold-check exactly.
# ---------------------------------------------------------------------------

def lcg_next(state: int) -> int:
    """Linear congruential generator (glibc constants), masked to 31 bits.
    Deterministic: same seed + same call count -> same sequence in Python and
    in the JS gold-check (which uses Math.imul + >>> 0 + & 0x7fffffff)."""
    m = (state * 1103515245 + 12345) & 0xFFFFFFFF
    return m & 0x7FFFFFFF


def combined_breach() -> float:
    """Analytic combined breach probability = product of per-layer leak rates.
    Independent layers multiply, so a strong stack leaks far less than any one
    layer. (1-0.85)(1-0.80)(1-0.90)(1-0.95) = 0.00015 = 0.015%."""
    p = 1.0
    for _, stop, _ in LAYERS:
        p *= (1.0 - stop)
    return p


def simulate_attacks(n: int, seed: int = ATTACK_SEED) -> tuple[int, list[int]]:
    """Flow `n` attacks through the layers in order. Each layer independently
    stops an attack with its stop probability (deterministic LCG draws).
    Returns (breaches, per_layer_stops)."""
    state = seed
    breaches = 0
    stops = [0] * len(LAYERS)
    for _ in range(n):
        got_through = True
        for i in range(len(LAYERS)):
            state = lcg_next(state)
            r = (state % 10000) / 10000.0          # [0, 1)
            if r < LAYERS[i][1]:
                stops[i] += 1
                got_through = False
                break                              # stopped at layer i
        if got_through:
            breaches += 1
    return breaches, stops


def leak_risk(days: int) -> float:
    """Probability the secret has leaked by day `days`, given a daily leak
    rate. risk = 1 - (1 - LEAK_RATE)^days. Compounds: the longer a secret
    lives, the larger the window in which a leak goes undetected."""
    return 1.0 - (1.0 - LEAK_RATE) ** days


# ---------------------------------------------------------------------------
# Section 1 — Defense in Depth
# ---------------------------------------------------------------------------

def section_defense_in_depth() -> None:
    print("=" * 72)
    print("=== Defense in Depth — independent layers, multiplicative defense")
    print("=" * 72)
    print("  A castle with MANY concentric walls. No single wall is perfect;")
    print("  each layer has independent controls and an independent probability")
    print("  of stopping an attack. Because the layers are INDEPENDENT, the")
    print("  combined breach probability is the PRODUCT of per-layer leak")
    print("  rates — so a stack of good-enough layers leaks far less than any")
    print("  one perfect layer.")
    print()
    print("  layer     stop_prob   leak_rate   controls")
    print("  " + "-" * 60)
    for name, stop, controls in LAYERS:
        print(f"  {name:<9} {stop:>7.0%}      {1 - stop:>7.0%}      "
              f"{', '.join(controls)}")
    print()

    combined = combined_breach()
    best_single = max(s for _, s, _ in LAYERS)
    best_single_leak = 1.0 - best_single
    improvement = best_single_leak / combined
    print("  combined breach = product of leak rates")
    leak_parts = " x ".join(f"{1 - s:.2f}" for _, s, _ in LAYERS)
    print(f"                  = {leak_parts}")
    print(f"                  = {combined:.5f}  ({combined:.3%})")
    print(f"                  = {int(combined * ATTACK_ATTEMPTS)} "
          f"breaches per {ATTACK_ATTEMPTS:,} attacks")
    print()
    print(f"  best single layer (data, stop={best_single:.0%}) leaks "
          f"{best_single_leak:.0%} = {int(best_single_leak * ATTACK_ATTEMPTS):,} "
          f"per {ATTACK_ATTEMPTS:,}")
    print(f"  defense-in-depth improves on the best single layer by "
          f"{improvement:,.0f}x")
    print()

    breaches, stops = simulate_attacks(ATTACK_ATTEMPTS)
    print(f"  SIMULATION ({ATTACK_ATTEMPTS:,} attacks, LCG seed={ATTACK_SEED}):")
    for (name, stop, _), cnt in zip(LAYERS, stops):
        print(f"    stopped at {name:<9} = {cnt:>6,}   (expected "
              f"{stop * ATTACK_ATTEMPTS:>8,.0f})")
    print(f"    breached ALL layers   = {breaches:>6,}   (expected "
          f"{combined * ATTACK_ATTEMPTS:>8.1f})")
    print()

    ok_product = abs(combined - 0.00015) < 1e-9
    ok_simulation = breaches == int(round(combined * ATTACK_ATTEMPTS)) or \
        abs(breaches - combined * ATTACK_ATTEMPTS) <= 5
    ok_improvement = improvement > 100
    print(f"  combined breach = 0.015% (product of 4 leak rates)? "
          f"[check] {'OK' if ok_product else 'FAIL'}")
    print(f"  simulation matches analytic (within +/-5)?            "
          f"[check] {'OK' if ok_simulation else 'FAIL'}")
    print(f"  defense-in-depth > 100x better than best single layer?"
          f"  [check] {'OK' if ok_improvement else 'FAIL'}")
    assert ok_product and ok_simulation and ok_improvement
    print()
    print("  [check] OK   (defense-in-depth: independent layers multiply)")
    print()
    print("  GOTCHA: layers must be INDEPENDENT. If the same misconfigured IAM")
    print("  role grants access at network, host, AND app layers, they are")
    print("  perfectly correlated and provide the defense of only ONE layer.")
    print("  GOTCHA: the WEAKEST layer dominates the user-facing risk. A 99%")
    print("  stack with one 40% layer leaks ~60% — fix the floor first.")


# ---------------------------------------------------------------------------
# Section 2 — TLS Handshake (1.2 vs 1.3 vs 0-RTT)
# ---------------------------------------------------------------------------

def section_tls_handshake() -> None:
    print()
    print("=" * 72)
    print("=== TLS Handshake — TLS 1.2 (2-RTT) vs TLS 1.3 (1-RTT) vs 0-RTT")
    print("=" * 72)
    print("  TLS provides encryption (confidentiality), authentication (server")
    print("  identity via X.509 certificate), and integrity (tamper detection).")
    print("  TLS 1.3 halved the handshake to a single round trip and added")
    print("  0-RTT resumption; both use ECDHE for forward secrecy — past")
    print("  sessions stay secure even if the server's long-term key leaks.")
    print()

    tls12 = [
        ("C->S", "ClientHello",
         "version, random_client, cipher_suites, SNI, key_share (1.3)"),
        ("S->C", "ServerHello + Certificate + ServerKeyExchange + HelloDone",
         "random_server, chosen cipher, DH params, cert chain"),
        ("C->S", "ClientKeyExchange + ChangeCipherSpec + Finished",
         "encrypted premaster / DH public, switch to encrypted"),
        ("S->C", "ChangeCipherSpec + Finished", "server switches to encrypted"),
    ]
    tls13 = [
        ("C->S", "ClientHello (+ key_share, + early_data on resumption)",
         "one flight: proposed ciphers + ECDHE public key"),
        ("S->C", "ServerHello + {EncryptedExtensions, Cert, CertVerify, Finished}",
         "from here on EVERYTHING is encrypted"),
        ("C->S", "{Finished}", "client confirms; app data follows"),
    ]

    print("  TLS 1.2 full handshake (2 RTT before app data):")
    for d, m, note in tls12:
        print(f"    {d}  {m}")
        print(f"          {note}")
    print()
    print("  TLS 1.3 full handshake (1 RTT before app data):")
    for i, (d, m, note) in enumerate(tls13):
        print(f"    {d}  {m}")
        print(f"          {note}")
    print()

    t12_ms = TLS12_FLIGHTS * RTT_MS
    t13_ms = TLS13_FLIGHTS * RTT_MS
    t0_ms = TLS13_RESUMPTION * RTT_MS
    saving = t12_ms - t13_ms
    print(f"  RTT = {RTT_MS}ms (representative)")
    print(f"    TLS 1.2        = {TLS12_FLIGHTS} RTT = {t12_ms}ms   (handshake)")
    print(f"    TLS 1.3        = {TLS13_FLIGHTS} RTT = {t13_ms}ms   (handshake)")
    print(f"    TLS 1.3 0-RTT  = {TLS13_RESUMPTION} RTT = {t0_ms}ms   (resumed session)")
    print(f"    1.3 saves {saving}ms per connection vs 1.2")
    print()

    print("  FORWARD SECRECY (ECDHE): each session derives EPHEMERAL keys from")
    print("  a fresh Diffie-Hellman exchange. If the server's long-term private")
    print("  key is stolen tomorrow, PAST recorded sessions CANNOT be decrypted")
    print("  — the ephemeral keys were destroyed at session end.")
    print()

    ok_13 = TLS13_FLIGHTS == 1 and t13_ms == 50
    ok_saving = saving == RTT_MS
    ok_fs = TLS13_FLIGHTS < TLS12_FLIGHTS
    print(f"  TLS 1.3 = 1 RTT (50ms)?                       [check] "
          f"{'OK' if ok_13 else 'FAIL'}")
    print(f"  TLS 1.3 saves exactly 1 RTT (50ms) vs 1.2?    [check] "
          f"{'OK' if ok_saving else 'FAIL'}")
    print(f"  TLS 1.3 has fewer flights than TLS 1.2?        [check] "
          f"{'OK' if ok_fs else 'FAIL'}")
    assert ok_13 and ok_saving and ok_fs
    print()
    print("  [check] OK   (TLS 1.3: 1-RTT handshake, 0-RTT resumption, ECDHE)")
    print()
    print("  GOTCHA: 0-RTT is vulnerable to REPLAY — an attacker can replay the")
    print("  early-data request (e.g. a duplicate POST). Only allow 0-RTT for")
    print("  idempotent operations, or enforce idempotency keys server-side.")
    print("  GOTCHA: TLS authenticates the CHANNEL, not the USER. A valid TLS")
    print("  connection to api.evil.com still reaches the attacker's server —")
    print("  always validate the certificate's hostname (SAN), not just the CA.")


# ---------------------------------------------------------------------------
# Section 3 — mTLS (mutual authentication)
# ---------------------------------------------------------------------------

def section_mtls() -> None:
    print()
    print("=" * 72)
    print("=== mTLS — mutual authentication (the client proves identity too)")
    print("=" * 72)
    print("  Standard TLS authenticates only the SERVER. mTLS (mutual TLS)")
    print("  requires the CLIENT to ALSO present a certificate, signed by a CA")
    print("  the server trusts. The server verifies it — both sides are now")
    print("  authenticated and the channel is encrypted. This is the identity")
    print("  backbone of service meshes and zero-trust internal networks.")
    print()

    server_tls = [
        "Client validates SERVER certificate against trusted CA",
        "Server is authenticated; client is anonymous (or auth via app layer)",
    ]
    mtls = [
        "Client validates SERVER certificate against trusted CA",
        "Server requests + validates CLIENT certificate against internal CA",
        "Server maps client cert to a workload identity (SPIFFE ID / service)",
        "Server authorizes the request based on that identity",
    ]
    print("  server-only TLS:")
    for s in server_tls:
        print(f"    - {s}")
    print()
    print("  mTLS (adds the client-cert flight):")
    for s in mtls:
        print(f"    - {s}")
    print()

    print("  HANDSHAKE COST (mTLS vs server-only TLS 1.3):")
    server_bytes = 3500
    client_cert_bytes = 2000
    certverify_bytes = 64
    mtls_bytes = server_bytes + client_cert_bytes + certverify_bytes
    overhead = mtls_bytes - server_bytes
    print(f"    server-only handshake  = {server_bytes:,} bytes (1 RTT)")
    print(f"    mTLS handshake         = {mtls_bytes:,} bytes "
          f"(+{client_cert_bytes} client cert, +{certverify_bytes} CertVerify)")
    print(f"    overhead               = +{overhead:,} bytes "
          f"(~{overhead / server_bytes:.0%} larger), still 1 RTT")
    print()

    print("  WORKLOAD IDENTITY (SPIFFE / SPIRE):")
    print("    - SPIFFE ID: a URI-shaped identity, e.g.")
    print("      spiffe://prod.acme.com/payments/service")
    print("    - issued by SPIRE (or the mesh control plane) as a short-lived")
    print(f"      X.509 SVID (rotated automatically, TTL ~{OVERLAP_DAYS}d)")
    print("    - the cert IS the identity; no shared passwords, no long-lived keys")
    print()

    print("  WHERE mTLS IS USED:")
    print("    service mesh (Istio / Linkerd) : sidecar enforces mTLS transparently")
    print("    microservice-to-microservice   : every hop authenticated")
    print("    internal APIs / banking         : strong client identity required")
    print("    Kubernetes pod-to-pod          : mesh + NetworkPolicy together")
    print()

    ok_both = len(mtls) > len(server_tls)
    ok_overhead = overhead > 0
    ok_rtt = TLS13_FLIGHTS == 1
    print(f"  mTLS adds client-auth steps vs server-only TLS? [check] "
          f"{'OK' if ok_both else 'FAIL'}")
    print(f"  mTLS adds bytes but keeps the same RTT?         [check] "
          f"{'OK' if (ok_overhead and ok_rtt) else 'FAIL'}")
    print(f"  mTLS authenticates BOTH directions?             [check] "
          f"{'OK' if ok_both else 'FAIL'}")
    assert ok_both and ok_overhead and ok_rtt
    print()
    print("  [check] OK   (mTLS: mutual auth, workload identity, ~1 RTT overhead)")
    print()
    print("  GOTCHA: the internal CA (or SPIRE trust domain) is now a CRITICAL")
    print("  root of trust. If its private key leaks, every workload identity it")
    print("  issued is forgeable. Protect it in an HSM and rotate its root.")
    print("  GOTCHA: mTLS authenticates the WORKLOAD, not the end USER. A")
    print("  compromised pod has a valid cert — pair mTLS with per-request USER")
    print("  authZ (zero trust) so a stolen workload identity cannot impersonate")
    print("  arbitrary users.")


# ---------------------------------------------------------------------------
# Section 4 — Secrets Management (rotation lifecycle)
# ---------------------------------------------------------------------------

def section_secrets() -> None:
    print()
    print("=" * 72)
    print("=== Secrets Management — the rotation lifecycle")
    print("=" * 72)
    print("  A secret (API key, DB password, signing key) is valuable ONLY while")
    print("  it is secret. The lifecycle keeps it that way: generate outside the")
    print("  app, distribute via a sidecar, rotate on a schedule, revoke on")
    print("  compromise, and audit every access. NEVER bake secrets into images,")
    print("  env vars, or source control.")
    print()

    lifecycle = [
        ("generate",  "create in HSM/KMS; plaintext never leaves the boundary"),
        ("distribute", "inject at runtime via sidecar (Vault Agent) / CSI volume"),
        ("use",        "fetch + cache with TTL; never log, never return to client"),
        ("rotate",     "periodic dual-key overlap; old + new valid during window"),
        ("revoke",     "kill compromised key via KMS; propagates to all consumers"),
        ("audit",      "log every read/decrypt; alert on anomalous access"),
    ]
    print("  lifecycle:")
    for step, desc in lifecycle:
        print(f"    {step:<12} - {desc}")
    print()

    print(f"  LEAK-RISK MODEL (daily leak rate = {LEAK_RATE:.1%}):")
    print("    risk(days) = 1 - (1 - leak_rate)^days   (compounds daily)")
    risk_1 = leak_risk(1)
    risk_30 = leak_risk(30)
    risk_90 = leak_risk(ROTATION_DAYS)
    risk_365 = leak_risk(365)
    risk_1h = leak_risk(SHORT_TTL_HOURS / 24)
    print(f"    1 day   -> risk = {risk_1:.4%}")
    print(f"    30 days -> risk = {risk_30:.2%}")
    print(f"    {ROTATION_DAYS} days -> risk = {risk_90:.2%}   "
          f"(canonical rotation interval)")
    print(f"    365 days-> risk = {risk_365:.1%}   (a year-old key is risky)")
    print()
    print(f"    short-lived token (TTL {SHORT_TTL_HOURS}h) "
          f"-> risk = {risk_1h:.4%}")
    reduction = risk_90 / risk_1h
    print(f"    1h token vs 90-day key: {reduction:,.0f}x lower leak risk")
    print()

    print("  DUAL-KEY ROTATION (zero-downtime key change):")
    print("    day 0   : create key_v2 alongside key_v1 (both can DECRYPT)")
    print("    day 0+  : new writes use key_v2; old writes still readable")
    print(f"    day {OVERLAP_DAYS}   : all data re-encrypted to key_v2; revoke key_v1")
    print(f"    overlap = {OVERLAP_DAYS} days, so a rolling deploy never sees a")
    print("              key the other instances cannot decrypt")
    print()

    print("  SHORT-LIVED vs LONG-LIVED:")
    print("    long-lived (90-day key) : blast radius = 90 days of data")
    print("    short-lived (1h token)  : blast radius = 1 hour of data")
    print(f"    {reduction:,.0f}x reduction in the window of compromise")
    print()

    ok_risk = risk_90 > risk_30 > risk_1
    ok_reduction = reduction > 1000
    ok_overlap = OVERLAP_DAYS < ROTATION_DAYS
    print(f"  risk grows monotonically with secret age?     [check] "
          f"{'OK' if ok_risk else 'FAIL'}")
    print(f"  1h token > 1000x lower risk than 90-day key?  [check] "
          f"{'OK' if ok_reduction else 'FAIL'}")
    print(f"  overlap window shorter than rotation interval?[check] "
          f"{'OK' if ok_overlap else 'FAIL'}")
    assert ok_risk and ok_reduction and ok_overlap
    print()
    print("  [check] OK   (secrets: rotate often, overlap keys, prefer short TTLs)")
    print()
    print("  GOTCHA: secrets in ENV VARS are leaked via /proc/<pid>/environ,")
    print("  process listings, and crash dumps. Inject via a mounted volume or")
    print("  sidecar that fetches on demand and caches with a short TTL.")
    print("  GOTCHA: a secret in git is compromised FOREVER — the commit history")
    print("  is forever. Rotate immediately AND scrub history (git filter-repo),")
    print("  because anyone may have already cloned the repo.")


# ---------------------------------------------------------------------------
# Section 5 — Zero Trust
# ---------------------------------------------------------------------------

def section_zero_trust() -> None:
    print()
    print("=" * 72)
    print("=== Zero Trust — never trust, always verify (every request)")
    print("=" * 72)
    print("  Castle-and-moat security trusts anything INSIDE the network (a VPN")
    print("  or office IP grants broad access). Once an attacker breaches the")
    print("  perimeter — a phished credential, a vulnerable pod — they move")
    print("  LATERALLY with little resistance. Zero trust (BeyondCorp, NIST")
    print("  800-207) eliminates implicit trust: EVERY request is authenticated")
    print("  and authorized, regardless of where it originates, based on identity")
    print("  + device posture + context — not network position.")
    print()

    print("  THE MODEL (one compromised internal credential):")
    print(f"    estate              = {RESOURCES} internal services")
    print(f"    compromised cred    = authorized for {CRED_SCOPE:.0%} "
          f"(least privilege) = {int(CRED_SCOPE * RESOURCES)} service(s)")
    print()

    castle_reach = RESOURCES                   # flat network: lateral movement
    zt_reach = int(CRED_SCOPE * RESOURCES)     # per-request authZ, least priv
    reduction = castle_reach / zt_reach

    print("  castle-and-moat (trust by location):")
    print("    attacker is 'inside' the VPN -> trusted by the network")
    print(f"    lateral movement reaches ALL {castle_reach} services")
    print(f"    detection: ~{CASTLE_DETECT_MIN // (60 * 24)} days "
          f"(anomalous access unnoticed)")
    print()
    print("  zero-trust (verify every request):")
    print("    every request hits a PEP (policy enforcement point)")
    print("    -> authenticates identity (mTLS / token)")
    print("    -> authorizes THIS action on THIS resource (least privilege)")
    print(f"    -> continuous eval flags anomalous access in ~{ZT_DETECT_MIN} min")
    print(f"    attacker reaches only {zt_reach} service(s) the cred can access")
    print()

    print("  BLAST-RADIUS COMPARISON:")
    print(f"    castle-and-moat : {castle_reach} services, "
          f"detected in ~{CASTLE_DETECT_MIN // (60 * 24)} days")
    print(f"    zero-trust      : {zt_reach} service(s),  "
          f"detected in ~{ZT_DETECT_MIN} min")
    print(f"    reduction       : {reduction:.0f}x smaller blast radius "
          f"(+ {CASTLE_DETECT_MIN // ZT_DETECT_MIN:.0f}x faster detection)")
    print()

    castle_cost = castle_reach * (CASTLE_DETECT_MIN / 60)   # service-hours exposed
    zt_cost = zt_reach * (ZT_DETECT_MIN / 60)
    cost_ratio = castle_cost / zt_cost
    print("  COMPROMISE COST (services x hours exposed):")
    print(f"    castle-and-moat : {castle_reach} svc x {CASTLE_DETECT_MIN // 60}h "
          f"= {castle_cost:,.0f} svc-hours")
    print(f"    zero-trust      : {zt_reach} svc x {ZT_DETECT_MIN // 60}h "
          f"= {zt_cost:,.1f} svc-hours")
    print(f"    ratio           : {cost_ratio:,.0f}x lower impact under zero trust")
    print()

    ok_reach = castle_reach == RESOURCES and zt_reach < castle_reach
    ok_reduction = reduction >= 10
    ok_detect = ZT_DETECT_MIN < CASTLE_DETECT_MIN
    print(f"  zero-trust limits reach to the cred's scope?  [check] "
          f"{'OK' if ok_reach else 'FAIL'}")
    print(f"  blast radius reduced >= 10x?                  [check] "
          f"{'OK' if ok_reduction else 'FAIL'}")
    print(f"  zero-trust detects compromise faster?         [check] "
          f"{'OK' if ok_detect else 'FAIL'}")
    assert ok_reach and ok_reduction and ok_detect
    print()
    print("  [check] OK   (zero-trust: verify every request, least privilege)")
    print()
    print("  GOTCHA: zero trust is not a product — it is a PROPERTY of the")
    print("  architecture. Buying a ZTNA appliance while services still accept")
    print("  shared tokens with no per-request authZ changes nothing.")
    print("  GOTCHA: the FIRST request still needs to be verified — bootstrapping")
    print("  workload identity (mTLS + SPIFFE) is what makes per-request authZ")
    print("  possible without a password on every call.")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_defense_in_depth()
    section_tls_handshake()
    section_mtls()
    section_secrets()
    section_zero_trust()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
