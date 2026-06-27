"""API Security — ground-truth simulations of OWASP API Top 10 defenses.

Five simulations covering the request-level security stack. Pure Python
stdlib; no network, no external crypto libraries.

  1. OWASP API Top 10 — BOLA (API1), Broken Auth (API2), Excessive Data
     Exposure / BOPLA (API3), BFLA (API5) with vulnerable vs hardened paths
  2. JWT validation — signature, expiry, claims (iss/aud/exp), and the
     algorithm-confusion attack (hardcoded algorithms, fail-closed)
  3. Input sanitization — SQL injection (string-concat vs parameterized),
     XSS (HTML escaping), mass assignment (field whitelist)
  4. CORS policy enforcement — origin allowlist, credentials rule, preflight
  5. Rate limiting — token bucket + sliding-window counter, 429 + Retry-After

Notes
-----
- HS256 is used for the JWT demo because it is pure stdlib. In production
  with more than one verifying service you MUST use RS256 (asymmetric) and
  hardcode algorithms=["RS256"] so an attacker cannot swap the alg header.
  The .md guide explains the algorithm-confusion attack (CVE-2016-10555).
- A fixed timestamp (FIXED_NOW) is used throughout so the output is
  byte-for-byte reproducible and the HTML gold-check can recompute identical
  values. Real JWT uses time.time(); real rate limiting uses the wall clock.

Every number printed below is produced by running this file; nothing is
hand-computed. Capture with:

    python3 api_security.py > api_security_output.txt 2>/dev/null
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import time

# ---------------------------------------------------------------------------
# Shared constants — deterministic so the JS gold-check reproduces bytes.
# ---------------------------------------------------------------------------

HMAC_SECRET = b"csfundamentals-api-security-key-2024"
ISSUER = "https://auth.example.com"
AUDIENCE = "https://api.example.com"

FIXED_NOW = 1700000000            # deterministic "now" for reproducible output
ACCESS_TTL = 900                  # 15 minutes — short-lived access token


# ---------------------------------------------------------------------------
# base64url + HS256 primitives (shared by the JWT-validation section).
# ---------------------------------------------------------------------------

def b64url_encode(data: bytes) -> str:
    """URL-safe base64 with padding stripped (RFC 7515)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    """Inverse of b64url_encode (re-adds missing padding)."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def hs256(msg: str, secret: bytes) -> str:
    """HMAC-SHA256, base64url-encoded (the 'S256' in JWT HS256)."""
    sig = hmac.new(secret, msg.encode("ascii"), hashlib.sha256).digest()
    return b64url_encode(sig)


def jwt_encode(header: dict, payload: dict, secret: bytes) -> str:
    """Compact JWT (HS256). JSON is minified + key-sorted for determinism."""
    h = b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    p = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{h}.{p}"
    return f"{signing_input}.{hs256(signing_input, secret)}"


def jwt_decode_unverified(token: str) -> tuple[dict, dict]:
    """Decode header + payload WITHOUT checking the signature (for demos)."""
    parts = token.split(".")
    assert len(parts) == 3, f"JWT must have 3 parts, got {len(parts)}"
    header = json.loads(b64url_decode(parts[0]))
    payload = json.loads(b64url_decode(parts[1]))
    return header, payload


# ---------------------------------------------------------------------------
# Section 1 — OWASP API Security Top 10 (vulnerable vs hardened endpoints)
# ---------------------------------------------------------------------------

class DocumentStore:
    """In-memory resource store. Each document has an owner + visibility."""

    def __init__(self) -> None:
        self.docs: dict[str, dict] = {
            "doc_001": {"id": "doc_001", "owner": "user:alice",
                        "title": "Alice's tax return", "visibility": "private",
                        "password_hash": "argon2id$secret"},
            "doc_002": {"id": "doc_002", "owner": "user:bob",
                        "title": "Bob's medical record", "visibility": "private",
                        "password_hash": "argon2id$secret"},
        }

    def get_raw(self, doc_id: str) -> dict | None:
        return self.docs.get(doc_id)


def vulnerable_get_doc(store: DocumentStore, doc_id: str) -> dict:
    """API1 BOLA: returns ANY document by id — no ownership check."""
    doc = store.get_raw(doc_id)
    return doc if doc else {}


def safe_get_doc(store: DocumentStore, doc_id: str, user: str) -> dict:
    """Hardened: ALWAYS check resource.owner == current_user."""
    doc = store.get_raw(doc_id)
    if doc is None or doc["owner"] != user:
        return {}                       # fail closed: empty == 404/403
    return doc


def vulnerable_admin_panel(user_role: str) -> bool:
    """API5 BFLA: trusts a hint from the client, no server-side role check."""
    return user_role is not None        # any logged-in user is "admin"


def safe_admin_panel(user: dict) -> bool:
    """Hardened: role check on the server-side session, not the request."""
    return user.get("role") == "admin"


def section_owasp_top10() -> None:
    print("=" * 72)
    print("=== OWASP API Security Top 10 — vulnerable vs hardened endpoints")
    print("=" * 72)
    print("  The 2023 edition is the current API-specific standard. The five")
    print("  simulations below show the attack, then the fix, for the highest-")
    print("  impact risks (API1, API2, API3, API4, API5).")
    print()

    store = DocumentStore()

    # -- API1: Broken Object Level Authorization (BOLA) ---------------------
    print("  API1 — Broken Object Level Authorization (BOLA)  [#1 risk]")
    print("    Attack:  user:alice calls GET /api/documents/doc_002")
    print("             (changes the id to reach Bob's document)")
    leaked = vulnerable_get_doc(store, "doc_002")
    bola_leak = bool(leaked) and leaked["owner"] == "user:bob"
    print(f"    VULNERABLE endpoint -> returns Bob's doc? "
          f"[check] {'OK (leak!)' if bola_leak else 'FAIL'}")
    blocked = safe_get_doc(store, "doc_002", "user:alice")
    bola_safe = blocked == {}
    print(f"    HARDENED   endpoint -> ownership check blocks? "
          f"[check] {'OK' if bola_safe else 'FAIL'}")
    print("    Fix: ALWAYS check resource.owner == current_user on every data")
    print("         access; centralize in middleware; use UUIDs (still check).")
    print()
    assert bola_leak and bola_safe

    # -- API2: Broken Authentication ----------------------------------------
    print("  API2 — Broken Authentication")
    print("    Attack: credential stuffing / brute force with no lockout.")
    login_attempts: dict[str, int] = {}
    password_db = {"user:alice": "correct-horse-battery-staple"}

    def vulnerable_login(user: str, pwd: str) -> bool:
        login_attempts[user] = login_attempts.get(user, 0) + 1
        return password_db.get(user) == pwd          # no lockout, no delay

    cracked = False
    for guess in ["123456", "password", "qwerty", "correct-horse-battery-staple"]:
        if vulnerable_login("user:alice", guess):
            cracked = True
            break
    print(f"    VULNERABLE: 4 guesses, no lockout -> cracked? "
          f"[check] {'OK (cracked!)' if cracked else 'FAIL'}")
    print(f"             attempts recorded = {login_attempts['user:alice']} (no ceiling)")

    # Hardened: lockout after 5 fails + constant-time compare.
    def safe_login(user: str, pwd: str, lockout: dict) -> tuple[bool, str]:
        if lockout.get(user, 0) >= 5:
            return False, "locked"
        stored = password_db.get(user, "")
        ok = hmac.compare_digest(stored, pwd)        # constant-time
        lockout[user] = lockout.get(user, 0) + (0 if ok else 1)
        if ok:
            lockout[user] = 0
        return ok, ("ok" if ok else "bad-creds")
    lockout: dict[str, int] = {}
    attempts_before_lock = 0
    for guess in ["123456", "password", "qwerty", "letmein", "admin"]:
        attempts_before_lock += 1
        ok, reason = safe_login("user:alice", guess, lockout)
        if reason == "locked":
            break
    ok2, reason2 = safe_login("user:alice", "correct-horse-battery-staple", lockout)
    brute_blocked = reason2 == "locked"
    print(f"    HARDENED: lockout after 5 fails -> real password rejected? "
          f"[check] {'OK' if brute_blocked else 'FAIL'}")
    print("    Fix: lockout after N fails, MFA, constant-time compare, short TTL.")
    print()
    assert cracked and brute_blocked

    # -- API3: Broken Object Property Level Auth (excessive data exposure) --
    print("  API3 — Broken Object Property Level Authorization (BOPLA)")
    print("    Attack: GET /api/me returns the whole user object verbatim.")
    user_record = {
        "id": "user:alice", "email": "alice@example.com",
        "role": "viewer", "password_hash": "argon2id$secret",
        "api_key": "sk-live-DEADBEEF", "is_admin": False,
    }

    def vulnerable_profile(u: dict) -> dict:
        return dict(u)                               # serialize everything

    def safe_profile(u: dict) -> dict:
        allow = {"id", "email", "role"}              # explicit field whitelist
        return {k: v for k, v in u.items() if k in allow}
    leaked_fields = sorted(vulnerable_profile(user_record).keys())
    safe_fields = sorted(safe_profile(user_record).keys())
    secret_leaked = "password_hash" in leaked_fields
    print(f"    VULNERABLE: returns {len(leaked_fields)} fields incl. secrets? "
          f"[check] {'OK (leak!)' if secret_leaked else 'FAIL'}")
    print(f"             leaked = {leaked_fields}")
    secret_blocked = "password_hash" not in safe_fields and len(safe_fields) == 3
    print(f"    HARDENED:   whitelist -> returns {safe_fields}? "
          f"[check] {'OK' if secret_blocked else 'FAIL'}")
    print("    Fix: explicit response whitelist; additionalProperties:false;")
    print("         never serialize internal fields (hashes, keys, flags).")
    print()
    assert secret_leaked and secret_blocked

    # -- API4: Unrestricted Resource Consumption (covered in Section 5) ------
    print("  API4 — Unrestricted Resource Consumption")
    print("    Attack: unlimited requests -> unbounded cost (critical for LLM")
    print("             APIs: no prompt-size limit = unbounded token spend).")
    print("    Fix: rate limiting + input-size caps + per-user cost budgets.")
    print("    (Full simulation + 429 handling in Section 5 — Rate Limiting.)")
    print()

    # -- API5: Broken Function Level Authorization (BFLA) -------------------
    print("  API5 — Broken Function Level Authorization (BFLA)")
    print("    Attack: regular user POSTs to /api/admin/promote with role hint.")
    bfla_vuln = vulnerable_admin_panel("viewer")     # trusts client hint
    bfla_safe = not safe_admin_panel({"role": "viewer"})
    print(f"    VULNERABLE: trusts client-supplied role -> admin granted? "
          f"[check] {'OK (escalation!)' if bfla_vuln else 'FAIL'}")
    print(f"    HARDENED:   server-side session role check -> denied? "
          f"[check] {'OK' if bfla_safe else 'FAIL'}")
    print("    Fix: deny-by-default; role from the session, not the request;")
    print("         separate admin paths; per-endpoint permission matrix.")
    print()
    assert bfla_vuln and bfla_safe

    print("  [check] OK   (OWASP API1/2/3/5 attacks reproduced + hardened)")
    print()
    print("  NOTE: API7 (SSRF) and API10 (unsafe consumption of 3rd-party APIs)")
    print("        are especially dangerous for LLM backends with tool-use /")
    print("        function-calling: an agent fetching attacker-supplied URLs")
    print("        is server-side request forgery by construction.")


# ---------------------------------------------------------------------------
# Section 2 — JWT validation (signature, expiry, claims, alg confusion)
# ---------------------------------------------------------------------------

def jwt_verify(
    token: str,
    secret: bytes,
    *,
    expected_aud: str,
    expected_iss: str,
    now: int,
    allowed_algs: tuple[str, ...] = ("HS256",),
) -> tuple[bool, str]:
    """Fail-closed JWT validation. Returns (ok, reason).

    Steps (EVERY request, in order):
      1. structure (3 parts)
      2. decode header — HARDCODE allowed algs (never trust the alg header)
      3. signature (constant-time)
      4. exp (not expired)
      5. nbf (not used prematurely)
      6. iss (trusted issuer)
      7. aud (intended audience — confused-deputy defense)
    """
    parts = token.split(".")
    if len(parts) != 3:
        return False, "malformed"
    header, payload = jwt_decode_unverified(token)
    if header.get("alg") not in allowed_algs:
        return False, f"alg '{header.get('alg')}' not in {list(allowed_algs)}"
    expected_sig = hs256(f"{parts[0]}.{parts[1]}", secret)
    if not hmac.compare_digest(expected_sig, parts[2]):
        return False, "bad signature"
    if payload.get("exp", 0) <= now:
        return False, "expired"
    if "nbf" in payload and payload["nbf"] > now:
        return False, "not-yet-valid"
    if payload.get("iss") != expected_iss:
        return False, "bad issuer"
    if payload.get("aud") != expected_aud:
        return False, "bad audience (confused deputy)"
    return True, "valid"


def section_jwt_validation() -> None:
    print()
    print("=" * 72)
    print("=== JWT Validation — signature, expiry, claims, alg confusion")
    print("=" * 72)

    header = {"alg": "HS256", "typ": "JWT", "kid": "key-1"}
    payload = {
        "iss": ISSUER, "sub": "user:alice", "aud": AUDIENCE,
        "role": "viewer", "scope": "read:documents",
        "iat": FIXED_NOW, "exp": FIXED_NOW + ACCESS_TTL, "jti": "jti_sec_001",
    }
    good_token = jwt_encode(header, payload, HMAC_SECRET)
    print(f"  reference token = {good_token}")
    print()

    def check(label: str, token: str, **kw) -> None:
        ok, reason = jwt_verify(
            token, HMAC_SECRET,
            expected_aud=AUDIENCE, expected_iss=ISSUER,
            now=FIXED_NOW, **kw,
        )
        tag = "OK" if ok else f"REJECTED ({reason})"
        print(f"    {label:<46} [check] {tag}")

    print("  1. STRUCTURE + SIGNATURE")
    check("valid token", good_token)
    # tamper: flip a payload byte without re-signing
    bad = good_token.split(".")
    tampered_payload = b64url_decode(bad[1]).replace(b"viewer", b"admin")
    bad[1] = b64url_encode(tampered_payload)
    check("tampered payload (viewer->admin, no re-sign)", ".".join(bad))
    print()

    print("  2. EXPIRY (exp)")
    expired_payload = {**payload, "exp": FIXED_NOW - 1}
    check("expired token (exp < now)", jwt_encode(header, expired_payload, HMAC_SECRET))
    print()

    print("  3. CLAIMS (iss / aud)")
    bad_aud = {**payload, "aud": "https://other-service.example.com"}
    check("wrong audience (confused deputy)", jwt_encode(header, bad_aud, HMAC_SECRET))
    bad_iss = {**payload, "iss": "https://evil.example.com"}
    check("wrong issuer", jwt_encode(header, bad_iss, HMAC_SECRET))
    print()

    print("  4. ALGORITHM CONFUSION (CVE-2016-10555)")
    print("     Attack: set alg='none' (or HS256 using the RSA public key as")
    print("     the HMAC secret). If the verifier trusts the alg header, the")
    print("     forged token passes. Defense: hardcode allowed_algs.")
    none_header = {"alg": "none", "typ": "JWT"}
    # A real 'alg:none' attack: valid header + valid payload, EMPTY signature.
    h_b64 = b64url_encode(json.dumps(none_header, separators=(",", ":"), sort_keys=True).encode())
    p_b64 = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    forged = f"{h_b64}.{p_b64}."
    ok_default, _ = jwt_verify(forged, HMAC_SECRET,
                               expected_aud=AUDIENCE, expected_iss=ISSUER,
                               now=FIXED_NOW)
    alg_blocked = not ok_default
    print(f"     forged 'alg:none' token rejected by default? "
          f"[check] {'OK' if alg_blocked else 'FAIL'}")
    # A NAIVE verifier trusts the alg header: alg='none' -> skip signature.
    # This is exactly how CVE-2016-10555-style libraries were exploited.
    def naive_verify(token: str) -> bool:
        h, _p = jwt_decode_unverified(token)
        if h.get("alg") == "none":        # trusts the header -> no signature check
            return True
        expected = hs256(token.split(".")[0] + "." + token.split(".")[1], HMAC_SECRET)
        return hmac.compare_digest(expected, token.split(".")[2])
    ok_weak = naive_verify(forged)
    print(f"     naive verifier that trusted 'none' -> forge passes? "
          f"[check] {'OK (vulnerable!)' if ok_weak else 'FAIL'}")
    print("     Fix: hardcode algorithms=['HS256'] (or ['RS256']); NEVER trust")
    print("          the alg header. This is THE classic JWT pitfall.")
    print()
    assert alg_blocked and ok_weak

    print("  [check] OK   (signature/exp/claims/alg-confusion all enforced)")
    print()
    print("  Validation checklist (EVERY request):")
    print("    [ ] signature (constant-time, key from JWK set matched by kid)")
    print("    [ ] alg is in a hardcoded allowlist (never from the header)")
    print("    [ ] exp > now")
    print("    [ ] nbf <= now (if present)")
    print("    [ ] iss == trusted issuer")
    print("    [ ] aud == THIS service (confused-deputy defense)")
    print("    [ ] jti not in revocation set (for high-value ops)")


# ---------------------------------------------------------------------------
# Section 3 — Input sanitization (SQL injection, XSS, mass assignment)
# ---------------------------------------------------------------------------

SAFE_SQL_RE = re.compile(r"(--|;|/\*|\*/|\b(or|and|union|select|drop|insert)\b)",
                         re.IGNORECASE)


def vulnerable_sql(email: str) -> str:
    """String concatenation -> SQL injection. NEVER do this."""
    return f"SELECT id, email FROM users WHERE email = '{email}'"


def safe_sql(email: str) -> tuple[str, tuple]:
    """Parameterized query -> the input is data, never code."""
    return ("SELECT id, email FROM users WHERE email = %s", (email,))


def section_input_sanitization() -> None:
    print()
    print("=" * 72)
    print("=== Input Sanitization — SQLi, XSS, mass assignment")
    print("=" * 72)

    print("  3.1 SQL INJECTION")
    payload_inject = "alice@example.com' OR '1'='1"
    vuln_query = vulnerable_sql(payload_inject)
    safe_query, safe_params = safe_sql(payload_inject)
    sqli_works = "OR '1'='1" in vuln_query and vuln_query.endswith("'")
    print(f"    malicious input = {payload_inject!r}")
    print("    VULNERABLE (string concat):")
    print(f"      {vuln_query}")
    print(f"      -> tautology appended? [check] {'OK (injectable!)' if sqli_works else 'FAIL'}")
    print("    SAFE (parameterized):")
    print(f"      {safe_query}")
    print(f"      params = {safe_params}")
    print(f"      -> input is data, not code?  [check] {'OK' if '%s' in safe_query else 'FAIL'}")
    print()
    assert sqli_works and "%s" in safe_query

    print("  3.2 XSS (stored / reflected)")
    xss_input = '<script>alert("steal-session")</script>'
    escaped = html.escape(xss_input, quote=True)
    xss_raw = "<script>" in xss_input
    xss_safe = "<script>" not in escaped and "&lt;script&gt;" in escaped
    print(f"    raw input    = {xss_input}")
    print(f"    escaped      = {escaped}")
    print(f"    raw contains <script>?      [check] {'OK (XSS!)' if xss_raw else 'FAIL'}")
    print(f"    escaped neutralizes tag?    [check] {'OK' if xss_safe else 'FAIL'}")
    print("    Layers: output-escape (html.escape), CSP header,")
    print("            HttpOnly+SameSite cookies, input allowlist validation.")
    print()
    assert xss_raw and xss_safe

    print("  3.3 MASS ASSIGNMENT (API3 root cause)")
    print("    Attacker POSTs extra fields the server never intended to accept.")
    incoming = {
        "title": "Quarterly report", "content": "Q3 numbers...",
        "visibility": "team",
        "is_admin": True,             # <-- privilege escalation
        "role": "admin",              # <-- privilege escalation
        "owner": "user:attacker",     # <-- object hijack
    }
    allow = {"title", "content", "visibility"}

    def assign_vulnerable(data: dict) -> dict:
        return dict(data)             # blindly spreads everything

    def assign_safe(data: dict) -> dict:
        return {k: v for k, v in data.items() if k in allow}
    mass_vuln = assign_vulnerable(incoming)
    mass_safe = assign_safe(incoming)
    escalate = mass_vuln.get("is_admin") is True
    blocked = "is_admin" not in mass_safe and set(mass_safe) == allow
    print(f"    VULNERABLE: is_admin persisted?  [check] {'OK (escalated!)' if escalate else 'FAIL'}")
    print(f"    SAFE:       whitelist = {sorted(mass_safe)}? [check] {'OK' if blocked else 'FAIL'}")
    print("    Fix: explicit input whitelist (Pydantic model /")
    print("         additionalProperties:false); never bind raw request body.")
    print()
    assert escalate and blocked

    print("  [check] OK   (SQLi/XSS/mass-assignment all demonstrated + defended)")


# ---------------------------------------------------------------------------
# Section 4 — CORS policy enforcement
# ---------------------------------------------------------------------------

ALLOWED_ORIGINS = {
    "https://app.example.com",
    "https://admin.example.com",
}
ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE"}


def cors_policy(origin: str | None, method: str,
                has_credentials: bool) -> tuple[int, dict]:
    """Evaluate a CORS request. Returns (status, headers).

    CORS is NOT a security feature — it is a *relaxation* of the same-origin
    policy, controlled by the server. The browser enforces it; curl/mobile do
    not. Misconfiguration (reflecting Origin, or '*' + credentials) leaks data.
    """
    headers: dict[str, str] = {"Vary": "Origin"}
    if method == "OPTIONS":
        # Preflight: answer which origins/methods/headers are permitted.
        if origin in ALLOWED_ORIGINS:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Access-Control-Allow-Methods"] = ",".join(sorted(ALLOWED_METHODS))
            headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
            headers["Access-Control-Max-Age"] = "86400"
            if has_credentials:
                headers["Access-Control-Allow-Credentials"] = "true"
            return 204, headers
        return 403, headers
    # Actual request.
    if origin is None or origin not in ALLOWED_ORIGINS:
        return 403, headers                 # no ACAO header -> browser blocks
    headers["Access-Control-Allow-Origin"] = origin
    if has_credentials:
        headers["Access-Control-Allow-Credentials"] = "true"
    return 200, headers


def section_cors() -> None:
    print()
    print("=" * 72)
    print("=== CORS Policy Enforcement — origin allowlist + credentials rule")
    print("=" * 72)
    print(f"  allowed origins = {sorted(ALLOWED_ORIGINS)}")
    print("  CORS is NOT a security feature: it relaxes the same-origin policy.")
    print("  The browser enforces it; curl / mobile apps ignore it entirely.")
    print()

    cases = [
        ("legit SPA, cookies",   "https://app.example.com", "GET", True),
        ("preflight legit",      "https://app.example.com", "OPTIONS", True),
        ("evil origin",          "https://evil.example.com", "GET", False),
        ("reflected-Origin bug", "https://evil.example.com", "GET", True),
    ]
    for label, origin, method, creds in cases:
        status, headers = cors_policy(origin, method, creds)
        acao = headers.get("Access-Control-Allow-Origin", "(none)")
        blocked = status >= 400 or acao == "(none)"
        # Highlight the dangerous combo: '*' + credentials is never valid.
        bad_combo = acao == "*" and headers.get("Access-Control-Allow-Credentials") == "true"
        tag = "BLOCKED" if blocked else "ALLOWED"
        if bad_combo:
            tag = "INVALID (wildcard+creds)"
        print(f"    {label:<22} origin={origin}")
        print(f"      -> {status}  ACAO={acao}  creds={creds}  [{tag}]")
        if label.startswith("legit"):
            ok = status == 200 and acao == origin
            print(f"      legit origin reflected exactly? [check] {'OK' if ok else 'FAIL'}")
            assert ok
        if label.startswith("evil"):
            ok = blocked and not bad_combo
            print(f"      evil origin blocked, no reflect? [check] {'OK' if ok else 'FAIL'}")
            assert ok
        if label.startswith("preflight"):
            ok = status == 204 and "Access-Control-Allow-Methods" in headers
            print(f"      preflight answers methods?      [check] {'OK' if ok else 'FAIL'}")
            assert ok
    print()
    print("  Rules:")
    print("    1. NEVER 'Access-Control-Allow-Origin: *' + Allow-Credentials: true")
    print("       (browsers reject it; a proxy that strips+reflects is the bug).")
    print("    2. NEVER reflect the Origin header without an allowlist check.")
    print("    3. Reflect the EXACT allowed origin, not a pattern, not '*'.")
    print("    4. Enumerate only the methods/headers you actually need.")
    print("    5. JWT in Authorization header -> CSRF-proof; no cookies needed.")
    print()
    print("  [check] OK   (CORS allowlist + credentials rule enforced)")


# ---------------------------------------------------------------------------
# Section 5 — Rate limiting (token bucket, sliding-window, 429 handling)
# ---------------------------------------------------------------------------

class TokenBucket:
    """Tokens refill at a constant rate up to capacity. Burst up to capacity.

    O(1) memory per key. Standard for payment/LLM APIs where a controlled
    burst is desirable (a user legitimately sending several requests fast).
    """

    def __init__(self, capacity: int, refill_per_sec: float, now: int) -> None:
        self.capacity = capacity
        self.refill = refill_per_sec
        self.tokens = float(capacity)
        self.last = float(now)

    def allow(self, now: int, cost: float = 1.0) -> bool:
        elapsed = now - self.last
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill)
        self.last = float(now)
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False


class SlidingWindowCounter:
    """Weighted average of current + previous window. O(1), near-exact.

    Fixes the fixed-window burst-at-boundary problem: 100/min would allow
    200 in 4s if the boundary splits a burst in half.
    """

    def __init__(self, limit: int, window: int, now: int) -> None:
        self.limit = limit
        self.window = window
        self.cur_window = now // window
        self.cur_count = 0
        self.prev_count = 0

    def allow(self, now: int) -> bool:
        w = now // self.window
        if w == self.cur_window:
            pass
        elif w == self.cur_window + 1:
            self.prev_count = self.cur_count
            self.cur_count = 0
            self.cur_window = w
        else:
            self.prev_count = 0
            self.cur_count = 0
            self.cur_window = w
        weight = (now % self.window) / self.window
        est = self.cur_count + self.prev_count * (1 - weight)
        if est < self.limit:
            self.cur_count += 1
            return True
        return False


def section_rate_limiting() -> None:
    print()
    print("=" * 72)
    print("=== Rate Limiting — token bucket, sliding window, 429 handling")
    print("=" * 72)

    print("  5.1 TOKEN BUCKET (burst up to capacity, then steady refill)")
    print("     capacity=10, refill=1 token/sec")
    tb = TokenBucket(capacity=10, refill_per_sec=1.0, now=FIXED_NOW)
    burst_at = FIXED_NOW                      # all 15 requests at the same instant
    allowed = 0
    denied = 0
    for _ in range(15):
        if tb.allow(burst_at):
            allowed += 1
        else:
            denied += 1
    print(f"     15 concurrent requests at t={FIXED_NOW}:")
    print(f"       allowed = {allowed}  (drained the bucket to 0)")
    print(f"       denied  = {denied}  (bucket empty -> 429)")
    tb_ok = allowed == 10 and denied == 5
    print(f"     burst capped at capacity? [check] {'OK' if tb_ok else 'FAIL'}")
    print()

    print("     after 10s the bucket refills (1 token/s -> 10 tokens):")
    allowed2 = sum(1 for _ in range(10) if tb.allow(FIXED_NOW + 10))
    refill_ok = allowed2 == 10
    print(f"       next 10 requests at t={FIXED_NOW}+10: allowed={allowed2}")
    print(f"       refill to capacity?       [check] {'OK' if refill_ok else 'FAIL'}")
    print()
    assert tb_ok and refill_ok

    print("  5.2 SLIDING WINDOW COUNTER (no 2x burst at window boundary)")
    print("     limit=100/min, window=60s")
    swc = SlidingWindowCounter(limit=100, window=60, now=FIXED_NOW)
    # Fill the current window to its limit.
    for _ in range(100):
        swc.allow(FIXED_NOW)
    # One second into the NEXT window: fixed-window would allow 100 fresh;
    # sliding window weights prev window heavily, so it denies.
    just_after_boundary = FIXED_NOW + 60 + 1
    fixed_would_allow = 100          # naive fixed window resets to 0
    sw_allows = sum(1 for _ in range(100) if swc.allow(just_after_boundary))
    burst_fixed = fixed_would_allow
    no_burst = sw_allows < burst_fixed
    print(f"     100 req filled window t={FIXED_NOW}.")
    print(f"     At t+{just_after_boundary - FIXED_NOW}s (1s into next window):")
    print(f"       fixed-window (naive) would allow = {burst_fixed}")
    print(f"       sliding-window counter allows    = {sw_allows}")
    print(f"       2x-boundary burst prevented?     [check] {'OK' if no_burst else 'FAIL'}")
    print()
    assert no_burst

    print("  5.3 429 RESPONSE (server) + BACKOFF (client)")
    retry_after = 60                                  # seconds until reset
    backoff_schedule = []
    wait = 2
    for _ in range(5):                                # 5 retries, exponential
        backoff_schedule.append(wait)
        wait = min(wait * 2, 60)
    print(f"     server returns 429 with Retry-After: {retry_after}")
    print("     server returns X-RateLimit-Remaining: 0")
    print(f"     client backoff (s) = {backoff_schedule}")
    print("     Rule: NEVER retry immediately; honor Retry-After; exponential")
    print("     backoff with jitter; cap at 60s; circuit-break on repeat 429.")
    print()
    print("  [check] OK   (token bucket + sliding window + 429 backoff complete)")
    print()
    print("  Per-dimension keys (defense in depth):")
    print("    rl:ip:{ip}:{endpoint}        anonymous public API")
    print("    rl:user:{uid}:{endpoint}     authenticated fair-usage")
    print("    rl:tenant:{tid}:{endpoint}   multi-tenant SaaS ceiling")
    print("    rl:global:{endpoint}         hard service-wide ceiling")
    print("  Distributed: Redis + atomic Lua script (single INCR across all pods).")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    t0 = time.perf_counter()
    section_owasp_top10()
    section_jwt_validation()
    section_input_sanitization()
    section_cors()
    section_rate_limiting()
    elapsed = (time.perf_counter() - t0) * 1000
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print(f"elapsed: {elapsed:.1f} ms")
    print("=" * 72)
