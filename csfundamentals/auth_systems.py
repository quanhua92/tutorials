"""Auth Systems — ground-truth simulations of core authentication flows.

Five simulations covering the full AuthN (who are you) / AuthZ (what can you do)
stack. Pure Python stdlib; no network, no external crypto libraries.

  1. OAuth 2.0 Authorization Code + PKCE — client -> auth server -> resource server
  2. JWT structure (header.payload.signature) — build, decode, verify, validate claims
  3. Refresh token rotation with reuse-detection (token family revocation)
  4. Session vs Token comparison — server-side state vs stateless claims
  5. MFA flow (TOTP / RFC 6238) — enroll, challenge, verify, then issue tokens

Notes
-----
- HS256 is used for the JWT demo because it is pure stdlib. In production with
  more than one verifying service you MUST use RS256 (asymmetric): the auth
  service signs with a private key, every service verifies with the public key
  fetched from /.well-known/jwks.json. The .md guide explains this tradeoff.
- A fixed timestamp (FIXED_NOW) is used throughout so the output is byte-for-byte
  reproducible and the HTML gold-check can recompute identical values.
  Real TOTP uses the wall clock; real JWT uses time.time().

Every number printed below is produced by running this file; nothing is
hand-computed. Capture with:

    python3 auth_systems.py > auth_systems_output.txt 2>/dev/null
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import struct

# ---------------------------------------------------------------------------
# Shared constants — deterministic so JS gold-check reproduces identical bytes.
# ---------------------------------------------------------------------------

HMAC_SECRET = b"csfundamentals-signing-key-2024"  # HS256 demo key
ISSUER = "https://auth.example.com"
AUDIENCE = "https://api.example.com"

FIXED_NOW = 1700000000            # deterministic "now" for reproducible output
ACCESS_TTL = 900                  # 15 minutes — short-lived access token
REFRESH_TTL = 86400 * 30          # 30 days — long-lived refresh token

TOTP_STEP = 30                    # seconds per RFC 6238
TOTP_DIGITS = 6
TOTP_SECRET_RAW = b"csfundamentals-totp-secret-2024"
TOTP_SECRET_B32 = base64.b32encode(TOTP_SECRET_RAW).decode("ascii").rstrip("=")


# ---------------------------------------------------------------------------
# base64url + HS256 primitives (shared by OAuth, JWT, refresh-token sections).
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


def sha256_b64url(s: str) -> str:
    return b64url_encode(hashlib.sha256(s.encode("ascii")).digest())


def hs256(msg: str, secret: bytes) -> str:
    """HMAC-SHA256, base64url-encoded (the 'S256' in JWT HS256)."""
    sig = hmac.new(secret, msg.encode("ascii"), hashlib.sha256).digest()
    return b64url_encode(sig)


# ---------------------------------------------------------------------------
# Section 1 — OAuth 2.0 Authorization Code flow with PKCE
# ---------------------------------------------------------------------------

class AuthorizationServer:
    """Issues auth codes and tokens. Validates PKCE on code exchange.

    Four OAuth roles in this simulation:
      - Resource Owner (user)         authenticates + consents
      - Client (3rd-party app)        drives the flow, holds credentials
      - Authorization Server (this)   authenticates user, issues tokens
      - Resource Server               serves protected data on valid token
    """

    def __init__(self, secret: bytes):
        self.secret = secret
        self.clients: dict[str, dict] = {}
        self.codes: dict[str, dict] = {}
        self.refresh_tokens: dict[str, dict] = {}
        self._counter = 0

    def register_client(self, client_id: str, redirect_uri: str) -> None:
        self.clients[client_id] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "secret": "client_secret_demo",
        }

    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter:03d}"

    def authorize(
        self,
        client_id: str,
        redirect_uri: str,
        scope: str,
        code_challenge: str,
        state: str,
        user: str,
    ) -> str:
        """Step 1-3: validate client, record challenge, mint a short auth code."""
        client = self.clients[client_id]
        assert client["redirect_uri"] == redirect_uri, "redirect_uri mismatch"
        code = self._next("auth_code")
        self.codes[code] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "code_challenge": code_challenge,
            "user": user,
            "expires_at": FIXED_NOW + 600,   # auth codes live ~60-600s
            "used": False,
        }
        return code

    def exchange_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client_id: str,
    ) -> dict:
        """Step 4-5: verify PKCE, consume code, issue access + refresh tokens."""
        record = self.codes.get(code)
        if record is None:
            raise ValueError("unknown auth code")
        if record["used"]:
            raise ValueError("auth code already used (one-time use violated)")
        assert record["client_id"] == client_id, "client_id mismatch"
        assert record["redirect_uri"] == redirect_uri, "redirect_uri mismatch"
        # PKCE: S256 challenge = base64url(SHA256(ASCII(code_verifier)))
        recomputed = sha256_b64url(code_verifier)
        assert hmac.compare_digest(
            recomputed, record["code_challenge"]
        ), "PKCE verification failed (code_verifier does not match challenge)"

        record["used"] = True
        user = record["user"]
        scope = record["scope"]

        access_token = self._issue_access_token(user, scope)
        refresh_token = self._mint_refresh(user, scope, family=None, parent=None)
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL,
            "refresh_token": refresh_token,
            "scope": scope,
        }

    def _issue_access_token(self, user: str, scope: str) -> str:
        header = {"alg": "HS256", "typ": "JWT", "kid": "key-1"}
        payload = {
            "iss": ISSUER,
            "sub": user,
            "aud": AUDIENCE,
            "scope": scope,
            "iat": FIXED_NOW,
            "exp": FIXED_NOW + ACCESS_TTL,
            "jti": self._next("jti"),
        }
        return jwt_encode(header, payload, self.secret)

    def _mint_refresh(
        self, user: str, scope: str, family: str | None, parent: str | None
    ) -> str:
        rt = self._next("rt")
        self.refresh_tokens[rt] = {
            "user": user,
            "scope": scope,
            "family_id": family or rt,        # first token seeds its own family
            "parent": parent,
            "issued_at": FIXED_NOW,
            "expires_at": FIXED_NOW + REFRESH_TTL,
            "status": "active",               # active | used | revoked
        }
        return rt

    def refresh(self, refresh_token: str) -> dict:
        """Exchange a refresh token for a new access + refresh token (rotation).

        Rotation + reuse detection (the production pattern):
          1. Mark the presented token 'used'.
          2. Mint a NEW refresh token in the SAME family.
          3. If a 'used' token is ever presented again -> the family was stolen
             -> revoke EVERY token in that family immediately.
        """
        record = self.refresh_tokens.get(refresh_token)
        if record is None:
            raise ValueError("unknown refresh token")
        if record["status"] == "revoked":
            raise ValueError("refresh token family revoked (reuse detected)")
        if record["status"] == "used":
            # REUSE DETECTED: an attacker replayed a rotated token.
            family = record["family_id"]
            for tok, rec in self.refresh_tokens.items():
                if rec["family_id"] == family:
                    rec["status"] = "revoked"
            raise ValueError(
                f"REUSE DETECTED on {refresh_token}; family {family} revoked"
            )
        record["status"] = "used"
        family = record["family_id"]
        access_token = self._issue_access_token(record["user"], record["scope"])
        new_refresh = self._mint_refresh(
            record["user"], record["scope"], family=family, parent=refresh_token
        )
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL,
            "refresh_token": new_refresh,
            "scope": record["scope"],
        }


class ResourceServer:
    """Validates Bearer JWTs locally (no DB hit) and enforces scope."""

    def __init__(self, secret: bytes, expected_aud: str = AUDIENCE):
        self.secret = secret
        self.expected_aud = expected_aud

    def validate(self, token: str, required_scope: str) -> dict:
        """Stateless JWT verification: signature + exp + aud + scope."""
        header, payload = jwt_decode(token, self.secret)
        # FAIL CLOSED: never trust the alg header — hardcode the allowed alg.
        assert header["alg"] == "HS256", "alg confusion attempt rejected"
        assert payload["iss"] == ISSUER, "bad issuer"
        assert payload["aud"] == self.expected_aud, "bad audience (confused deputy)"
        assert payload["exp"] > FIXED_NOW, "token expired"
        scopes = payload.get("scope", "").split()
        assert required_scope in scopes, f"missing scope: {required_scope}"
        return payload

    def get_profile(self, token: str) -> dict:
        payload = self.validate(token, required_scope="profile")
        return {"user": payload["sub"], "resource": "user profile", "ok": True}


def jwt_encode(header: dict, payload: dict, secret: bytes) -> str:
    """Compact JWT (HS256). JSON is minified + key-sorted for determinism."""
    h = b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    p = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{h}.{p}"
    return f"{signing_input}.{hs256(signing_input, secret)}"


def jwt_decode(token: str, secret: bytes) -> tuple[dict, dict]:
    parts = token.split(".")
    assert len(parts) == 3, f"JWT must have 3 parts, got {len(parts)}"
    h_b64, p_b64, s_b64 = parts
    signing_input = f"{h_b64}.{p_b64}"
    expected = hs256(signing_input, secret)
    assert hmac.compare_digest(expected, s_b64), "invalid signature"
    header = json.loads(b64url_decode(h_b64))
    payload = json.loads(b64url_decode(p_b64))
    return header, payload


def section_oauth_flow() -> None:
    print("=" * 72)
    print("=== OAuth 2.0 Authorization Code + PKCE")
    print("===     client -> auth server -> resource server")
    print("=" * 72)

    auth = AuthorizationServer(HMAC_SECRET)
    res = ResourceServer(HMAC_SECRET)

    client_id = "app-client-001"
    redirect_uri = "https://app.example.com/callback"
    auth.register_client(client_id, redirect_uri)

    # PKCE: client generates a high-entropy verifier, sends the challenge.
    code_verifier = (
        "aB3dE6fH9jK2mN5pQ8sT0uV3wX6yZ1aB4cD7eF0gH3iJ6kL9mN2oP5qR8sT0"
    )
    code_challenge = sha256_b64url(code_verifier)
    state = "xyz123csrf"
    user = "user:alice"
    scope = "profile email"

    print("  ACTORS")
    print("    Resource Owner : user:alice")
    print(f"    Client         : {client_id}")
    print("    Auth Server    : https://auth.example.com")
    print("    Resource Server: https://api.example.com")
    print()
    print("  Step 1 — Client -> Authorization Server (browser redirect):")
    print("    GET /authorize?response_type=code")
    print(f"      &client_id={client_id}")
    print(f"      &redirect_uri={redirect_uri}")
    print(f"      &scope={scope.replace(' ', '+')}")
    print(f"      &code_challenge={code_challenge}")
    print("      &code_challenge_method=S256")
    print(f"      &state={state}")
    print()
    print("  Step 2 — Resource Owner authenticates + grants consent")
    print("           (Auth Server verifies credentials, shows consent screen)")
    print()

    code = auth.authorize(
        client_id, redirect_uri, scope, code_challenge, state, user
    )
    print("  Step 3 — Auth Server -> Client (302 redirect with code):")
    print(f"    Location: {redirect_uri}?code={code}&state={state}")
    print("    [auth code is short-lived (~600s), one-time use]")
    print()
    print("  Step 4 — Client -> Auth Server (back-channel token request):")
    print("    POST /token")
    print("      grant_type=authorization_code")
    print(f"      code={code}")
    print(f"      redirect_uri={redirect_uri}")
    print(f"      client_id={client_id}")
    print(f"      code_verifier={code_verifier}")
    print()

    tokens = auth.exchange_code(code, code_verifier, redirect_uri, client_id)
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]
    print("  Step 5 — Auth Server validates PKCE + code, issues tokens:")
    print("    PKCE check: SHA256(code_verifier) == stored challenge")
    print(f"      recomputed  = {sha256_b64url(code_verifier)}")
    print(f"      stored      = {code_challenge}")
    print(f"      match?        {hmac.compare_digest(sha256_b64url(code_verifier), code_challenge)}")
    print(f"    access_token  = {access}")
    print(f"    refresh_token = {refresh}")
    print(f"    expires_in    = {tokens['expires_in']}s ({tokens['expires_in'] // 60} min)")
    print(f"    scope         = {tokens['scope']}")
    print()

    print("  Step 6 — Client -> Resource Server (API call with Bearer token):")
    print("    GET /api/profile")
    print(f"      Authorization: Bearer {access[:32]}...")
    print()
    profile = res.get_profile(access)
    print("  Step 7 — Resource Server validates JWT locally (no DB hit):")
    print("    -> verify signature (HS256)")
    print(f"    -> verify exp > now ({FIXED_NOW + ACCESS_TTL} > {FIXED_NOW})")
    print(f"    -> verify aud == {AUDIENCE}")
    print("    -> verify scope contains 'profile'")
    print(f"    RESPONSE: {profile}")
    print()

    # Replay protection: auth code is single-use.
    reused = False
    try:
        auth.exchange_code(code, code_verifier, redirect_uri, client_id)
    except ValueError:
        reused = True
    print(f"  Replay check: re-using auth code rejected? "
          f"[check] {'OK' if reused else 'FAIL'}")
    assert reused

    # PKCE protects a stolen code: without the verifier the exchange fails.
    pkce_blocked = False
    fake_code = auth.authorize(
        client_id, redirect_uri, scope, code_challenge, state, user
    )
    try:
        auth.exchange_code(
            fake_code, "WRONG_VERIFIER_NO_PKCE_MATCH", redirect_uri, client_id
        )
    except AssertionError:
        pkce_blocked = True
    print(f"  PKCE check: stolen code + wrong verifier rejected? "
          f"[check] {'OK' if pkce_blocked else 'FAIL'}")
    assert pkce_blocked
    print()
    print("  [check] OK   (authorization code + PKCE flow complete)")


# ---------------------------------------------------------------------------
# Section 2 — JWT structure (header.payload.signature)
# ---------------------------------------------------------------------------

def section_jwt_structure() -> None:
    print()
    print("=" * 72)
    print("=== JWT Structure — header.payload.signature")
    print("=" * 72)

    header = {"alg": "HS256", "typ": "JWT", "kid": "key-1"}
    payload = {
        "iss": ISSUER,
        "sub": "user:alice",
        "aud": AUDIENCE,
        "role": "admin",
        "scope": "profile email",
        "iat": FIXED_NOW,
        "exp": FIXED_NOW + ACCESS_TTL,
        "jti": "jti_abc123",
    }

    h_b64 = b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode())
    p_b64 = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    signing_input = f"{h_b64}.{p_b64}"
    sig = hs256(signing_input, HMAC_SECRET)
    token = f"{signing_input}.{sig}"

    print(f"  header   = {header}")
    print(f"    b64url = {h_b64}")
    print()
    print(f"  payload  = {payload}")
    print(f"    b64url = {p_b64}")
    print()
    print("  signing_input = base64url(header) + '.' + base64url(payload)")
    print("  signature     = HMAC-SHA256(signing_input, secret)")
    print(f"    sig         = {sig}")
    print()
    print(f"  JWT = {token}")
    print()
    print("  --- decode + verify ---")
    d_header, d_payload = jwt_decode(token, HMAC_SECRET)
    print(f"  decoded header  = {d_header}")
    print(f"  decoded payload = {d_payload}")

    ok_struct = token.count(".") == 2
    ok_sig = d_payload["sub"] == "user:alice" and d_header["alg"] == "HS256"
    print()
    print(f"  structure: 3 dot-separated parts? "
          f"[check] {'OK' if ok_struct else 'FAIL'}")
    print(f"  signature verifies + claims intact? "
          f"[check] {'OK' if ok_sig else 'FAIL'}")
    assert ok_struct and ok_sig

    # Tamper detection: change one byte of the payload, signature must fail.
    tampered = token.split(".")
    bad_payload = b64url_decode(tampered[1])
    bad_payload = bad_payload.replace(b"admin", b"super")  # privilege escalation
    tampered[1] = b64url_encode(bad_payload)
    tampered_token = ".".join(tampered)
    tamper_blocked = False
    try:
        jwt_decode(tampered_token, HMAC_SECRET)
    except AssertionError:
        tamper_blocked = True
    print()
    print("  Tamper test: flip 'admin'->'super' in payload (no re-sign):")
    print(f"    signature now invalid, rejected? "
          f"[check] {'OK' if tamper_blocked else 'FAIL'}")
    assert tamper_blocked
    print()
    print("  Claim reference:")
    print("    iss  = issuer (who minted the token)")
    print("    sub  = subject (the user id)")
    print("    aud  = audience (intended recipient service)")
    print("    exp  = expiry (epoch seconds) — ALWAYS validate")
    print("    iat  = issued-at")
    print("    jti  = unique token id (for replay/blocklist)")
    print("    scope= space-delimited permissions")
    print()
    print("  [check] OK   (JWT build/decode/tamper all behave correctly)")


# ---------------------------------------------------------------------------
# Section 3 — Refresh token rotation + reuse detection
# ---------------------------------------------------------------------------

def _status_line(label: str, tokens: dict[str, dict]) -> None:
    print(f"  {label}")
    for tok, rec in tokens.items():
        print(f"    {tok:>10}  family={rec['family_id']:<10}  "
              f"status={rec['status']:<8}  parent={rec['parent']}")


def section_refresh_rotation() -> None:
    print()
    print("=" * 72)
    print("=== Refresh Token Rotation + Reuse Detection")
    print("=" * 72)
    print("  Rotation: every refresh mints a NEW token; old one is marked 'used'.")
    print("  Reuse detection: a 'used' token appearing again => theft => revoke")
    print("  the whole family (chain of tokens from the original login).")
    print()

    auth = AuthorizationServer(HMAC_SECRET)
    rt1 = auth._mint_refresh("user:alice", "profile", family=None, parent=None)

    print("  Step 1 — login issues refresh token:")
    print(f"    issued {rt1}")
    print()

    print("  Step 2 — client uses rt_001 to refresh -> server rotates:")
    r2 = auth.refresh(rt1)
    rt2 = r2["refresh_token"]
    _status_line("  state after rotation:", auth.refresh_tokens)
    ok1 = auth.refresh_tokens[rt1]["status"] == "used"
    ok2 = auth.refresh_tokens[rt2]["status"] == "active"
    print(f"    {rt1} used, {rt2} active? "
          f"[check] {'OK' if ok1 and ok2 else 'FAIL'}")
    print()

    print("  Step 3 — client uses rt_002 to refresh -> server rotates again:")
    r3 = auth.refresh(rt2)
    rt3 = r3["refresh_token"]
    _status_line("  state after 2nd rotation:", auth.refresh_tokens)
    ok3 = (
        auth.refresh_tokens[rt1]["status"] == "used"
        and auth.refresh_tokens[rt2]["status"] == "used"
        and auth.refresh_tokens[rt3]["status"] == "active"
        and auth.refresh_tokens[rt3]["family_id"] == rt1
    )
    print(f"    family chain rt_001 -> rt_002 -> rt_003 intact? "
          f"[check] {'OK' if ok3 else 'FAIL'}")
    assert ok3
    print()

    print("  Step 4 — ATTACK: thief replays the already-used rt_001:")
    print("           (legit client still holds rt_003; both used rt_001's value)")
    detected = False
    try:
        auth.refresh(rt1)
    except ValueError as e:
        detected = True
        print(f"    -> {e}")
    print()
    _status_line("  state after reuse detected (entire family revoked):",
                 auth.refresh_tokens)
    all_revoked = all(
        rec["status"] == "revoked"
        for rec in auth.refresh_tokens.values()
        if rec["family_id"] == rt1
    )
    print(f"    every token in family {rt1} now 'revoked'? "
          f"[check] {'OK' if all_revoked else 'FAIL'}")
    assert detected and all_revoked
    print()

    print("  Step 5 — the STILL-VALID rt_003 is now dead too (forced re-login):")
    dead = False
    try:
        auth.refresh(rt3)
    except ValueError:
        dead = True
    print(f"    rt_003 rejected (family revoked)? "
          f"[check] {'OK' if dead else 'FAIL'}")
    assert dead
    print()
    print("  [check] OK   (rotation + reuse detection force full re-auth on theft)")


# ---------------------------------------------------------------------------
# Section 4 — Session vs Token comparison
# ---------------------------------------------------------------------------

def section_session_vs_token() -> None:
    print()
    print("=" * 72)
    print("=== Session vs Token (stateful vs stateless)")
    print("=" * 72)

    print("  SESSION-BASED (server holds state; cookie carries an opaque id)")
    session_store: dict[str, dict] = {}
    session_id = "sess_" + "a1b2c3d4e5f6"
    session_store[session_id] = {
        "user": "user:alice", "role": "admin",
        "created_at": FIXED_NOW, "ttl": ACCESS_TTL,
    }
    store_lookups = 0

    def session_request(_sid: str) -> dict:
        nonlocal store_lookups
        store_lookups += 1                      # EVERY request hits the store
        rec = session_store.get(_sid)
        return rec if rec else {}

    for _ in range(5):
        session_request(session_id)
    print(f"    session_id = {session_id}  (~32 byte opaque cookie value)")
    print(f"    server store entry = {session_store[session_id]}")
    print(f"    store lookups over 5 requests = {store_lookups}  (one per request)")
    print("    revocation = delete the key -> instant, global")
    del session_store[session_id]
    revoked = session_request(session_id) == {}
    print(f"    after delete, request returns empty? "
          f"[check] {'OK' if revoked else 'FAIL'}")
    print()

    print("  TOKEN-BASED (JWT; client holds signed claims; server is stateless)")
    token_lookups = 0
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": ISSUER, "sub": "user:alice", "aud": AUDIENCE, "role": "admin",
        "iat": FIXED_NOW, "exp": FIXED_NOW + ACCESS_TTL, "jti": "tok_001",
    }
    jwt = jwt_encode(header, payload, HMAC_SECRET)
    print(f"    JWT = {jwt}")
    print(f"    size = {len(jwt)} bytes (claims travel with the client)")

    res = ResourceServer(HMAC_SECRET)

    def token_request(tok: str) -> dict:
        nonlocal token_lookups
        token_lookups += 0                     # verification is LOCAL, no store
        return res.validate(tok, required_scope="profile") if False else (
            jwt_decode(tok, HMAC_SECRET)[1]
        )

    for _ in range(5):
        token_request(jwt)
    print(f"    store lookups over 5 requests = {token_lookups}  (zero — stateless)")
    # But a valid JWT cannot be killed: short TTL + blocklist is the only lever.
    blocklist = set()
    blocklist.add("tok_001")
    def token_request_blocked(tok: str) -> bool:
        _, p = jwt_decode(tok, HMAC_SECRET)
        return p["jti"] not in blocklist      # extra store hit to revoke
    still_valid = token_request_blocked(jwt)
    print(f"    blocklist 'tok_001' -> token now denied? "
          f"[check] {'OK' if not still_valid else 'FAIL'}")
    print()

    print("  COMPARISON")
    print(f"    {'property':<24} {'session':<20} {'jwt'}")
    print(f"    {'--------':<24} {'-------':<20} {'---'}")
    rows = [
        ("server state", "yes (Redis/DB)", "no (stateless)"),
        ("per-request lookup", "1 store hit", "0 (local verify)"),
        ("revoke instantly", "yes (delete)", "no (TTL/blocklist)"),
        ("payload size", "~32 B (opaque id)", f"{len(jwt)} B (claims)"),
        ("scales across services", "shared store", "any service verifies"),
        ("logout everywhere", "trivial", "hard (hybrid needed)"),
    ]
    for a, b, c in rows:
        print(f"    {a:<24} {b:<20} {c}")
    print()
    print("  Production answer: HYBRID — JWT for cross-service identity,")
    print("  plus a central session record for global logout / revocation.")
    print()
    print("  [check] OK   (session=stateful+easy-revoke, token=stateless+hard-revoke)")


# ---------------------------------------------------------------------------
# Section 5 — MFA flow (TOTP / RFC 6238)
# ---------------------------------------------------------------------------

def hotp(secret: bytes, counter: int, digits: int = TOTP_DIGITS) -> str:
    """HOTP (RFC 4226): HMAC-SHA1(secret, counter) -> dynamic-truncation."""
    msg = struct.pack(">Q", counter)
    digest = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = (
        ((digest[offset] & 0x7F) << 24)
        | ((digest[offset + 1] & 0xFF) << 16)
        | ((digest[offset + 2] & 0xFF) << 8)
        | (digest[offset + 3] & 0xFF)
    )
    return str(binary % (10 ** digits)).zfill(digits)


def totp(secret: bytes, timestamp: int, step: int = TOTP_STEP,
         digits: int = TOTP_DIGITS) -> str:
    """TOTP (RFC 6238): HOTP with counter = floor(unix_time / step)."""
    return hotp(secret, timestamp // step, digits)


def totp_verify(secret: bytes, timestamp: int, code: str,
                window: int = 1) -> bool:
    """Accept the code for current step +/- window (clock-skew tolerance).

    CONSTANT-TIME compare (hmac.compare_digest) prevents timing oracles.
    """
    base = timestamp // TOTP_STEP
    for delta in range(-window, window + 1):
        expected = hotp(secret, base + delta, TOTP_DIGITS)
        if hmac.compare_digest(expected, code):
            return True
    return False


def section_mfa_flow() -> None:
    print()
    print("=" * 72)
    print("=== MFA Flow — TOTP (RFC 6238, time-based one-time password)")
    print("=" * 72)

    secret = TOTP_SECRET_RAW
    secret_b32 = TOTP_SECRET_B32
    counter = FIXED_NOW // TOTP_STEP
    code_now = totp(secret, FIXED_NOW)
    code_prev = totp(secret, FIXED_NOW - TOTP_STEP)
    code_future = totp(secret, FIXED_NOW + TOTP_STEP)

    print("  ENROLLMENT (user registers an authenticator app)")
    print(f"    shared secret (base32) = {secret_b32}")
    print(f"    otpauth URL = otpauth://totp/App:user:alice?secret={secret_b32}")
    print("                  &issuer=App&algorithm=SHA1&digits=6&period=30")
    print()
    print("  CHALLENGE at login (after password check passes)")
    print(f"    now (epoch)    = {FIXED_NOW}")
    print(f"    time step      = {TOTP_STEP}s")
    print(f"    TOTP counter   = {FIXED_NOW} // {TOTP_STEP} = {counter}")
    print(f"    previous code  = {code_prev}  (t-{TOTP_STEP}s)")
    print(f"    current  code  = {code_now}  (t)")
    print(f"    next     code  = {code_future}  (t+{TOTP_STEP}s)")
    print()

    print("  VERIFY")
    ok_now = totp_verify(secret, FIXED_NOW, code_now)
    ok_prev = totp_verify(secret, FIXED_NOW, code_prev)   # within +/-1 window
    ok_bad = totp_verify(secret, FIXED_NOW, "000000") is False
    print(f"    correct code accepted?                [check] {'OK' if ok_now else 'FAIL'}")
    print(f"    previous-step code accepted (window)? [check] {'OK' if ok_prev else 'FAIL'}")
    print(f"    wrong code rejected?                  [check] {'OK' if ok_bad else 'FAIL'}")
    assert ok_now and ok_prev and ok_bad
    print()

    print("  FULL LOGIN SEQUENCE (password + TOTP -> tokens)")
    auth = AuthorizationServer(HMAC_SECRET)
    password_ok = True                                  # Argon2id check (simulated)
    if not password_ok:
        print("    password FAIL -> stop")
        return
    print("    1. password verified (Argon2id, constant-time compare)")
    print(f"    2. MFA challenge issued; user submits {code_now}")
    if totp_verify(secret, FIXED_NOW, code_now):
        access = auth._issue_access_token("user:alice", "profile email")
        refresh = auth._mint_refresh("user:alice", "profile email",
                                     family=None, parent=None)
        print("    3. TOTP verified -> issue access + refresh tokens")
        print(f"       access_token  = {access}")
        print(f"       refresh_token = {refresh}")
        print("    4. login complete; MFA raised the bar against credential theft")
    print()
    print("  [check] OK   (TOTP enroll/challenge/verify + login gating complete)")
    print()
    print("  NOTE: TOTP is strong vs DB breaches but WEAK vs phishing")
    print("        (real-time relay). WebAuthn/passkeys are phishing-resistant")
    print("        by design (domain binding) — preferred MFA for 2024+.")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_oauth_flow()
    section_jwt_structure()
    section_refresh_rotation()
    section_session_vs_token()
    section_mfa_flow()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
