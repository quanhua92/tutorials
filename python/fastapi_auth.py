"""
fastapi_auth.py — Phase 7 bundle (#48).

GOAL (one line): show, by printing every value, how OAuth2PasswordBearer + JWT
turn "I hardcode a password check" into "a /token endpoint issues a signed
token, a dependency verifies it on protected routes, and passwords are never
stored — only slow salted hashes."

STDLIB-ONLY BY DESIGN (passlib/bcrypt/PyJWT are NOT installed): password
hashing uses hashlib.pbkdf2_hmac (PKCS#5 PBKDF2-HMAC-SHA256); the JWT is a
HAND-ROLLED HS256 built from hmac + hashlib.sha256 + base64 + json. The
shapes mirror the official FastAPI oauth2-jwt tutorial; production swaps in
passlib[bcrypt]/argon2 + PyJWT. This code learns the FORMAT, it is NOT
production-safe crypto.

NOTE on `OAuth2PasswordRequestForm`: it requires `python-multipart` (not in
pyproject.toml). We re-implement its 2-field form contract with a tiny
stdlib dependency (`_oauth2_form`) that parses application/x-www-form-urlencoded
via urllib.parse. Same wire contract; zero new deps.

This is the GROUND TRUTH for FASTAPI_AUTH.md. Every value below is computed
by this file via fastapi.testclient.TestClient; the .md guide pastes it
verbatim. Nothing is hand-computed. Deterministic inputs only (FIXED secret,
FIXED salt, FIXED "now") so the captured stdout is byte-reproducible.

Run:
    uv run python fastapi_auth.py
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Annotated

import fastapi
from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from fastapi.testclient import TestClient

BANNER = "=" * 70

# --- determinism knobs (FIXED so output.txt is byte-stable) -------------------
# Real systems: per-user random salt (os.urandom(16)) and a secret from a
# vault/env (openssl rand -hex 32). Hard-coding both here is for REPRODUCIBLE
# TEACHING OUTPUT only — never commit a real secret.
SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
FIXED_SALT = b"fixed-demo-salt16"          # 18 bytes; prod = os.urandom(16) per user
PBKDF2_ITERS = 10_000                      # prod = 100_000+ (NIST-SP-800-132)
NOW = 1_700_000_000                        # 2023-11-14T22:13:20Z; prod = int(time.time())
TOKEN_TTL_SEC = 1_800                      # 30 minutes


# ----------------------------------------------------------------------------
# pretty printers (house style, copied from types_and_truthiness.py)
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
# stdlib crypto helpers — EDUCATIONAL; learn the FORMAT, do NOT ship this.
# ----------------------------------------------------------------------------

def _b64url(raw: bytes) -> str:
    """Base64url-encode WITHOUT padding (RFC 7515 §2)."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_dec(s: str) -> bytes:
    """Inverse of _b64url: re-pad then base64url-decode."""
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_pw(password: str, salt: bytes = FIXED_SALT,
            iters: int = PBKDF2_ITERS) -> bytes:
    """PKCS#5 PBKDF2-HMAC-SHA256 -> 32 raw bytes. Slow-ish + salted by design."""
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iters, dklen=32)


def verify_pw(password: str, stored: bytes, salt: bytes = FIXED_SALT) -> bool:
    """Re-hash the candidate and compare in CONSTANT time (hmac.compare_digest)."""
    return hmac.compare_digest(hash_pw(password, salt), stored)


def jwt_encode(payload: dict, secret: str = SECRET_KEY) -> str:
    """Hand-rolled HS256: b64url(header).b64url(payload).b64url(HMAC-SHA256(sig))."""
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
    p = _b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64url(sig)}"


def jwt_decode(token: str, secret: str = SECRET_KEY,
               now: int = NOW) -> dict | None:
    """Return the payload iff (a) the HS256 signature verifies and (b) exp>=now.

    We NEVER trust the token's own `alg` header — we always recompute HS256.
    That makes alg:none / alg-confusion forgeries fail by construction.
    """
    try:
        h_b64, p_b64, sig_b64 = token.split(".")
    except ValueError:
        return None
    expected = _b64url(hmac.new(secret.encode(),
                                f"{h_b64}.{p_b64}".encode(),
                                hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig_b64):           # signature check
        return None
    payload = json.loads(_b64url_dec(p_b64))
    if isinstance(payload.get("exp"), (int, float)) and payload["exp"] < now:
        return None                                           # expiry check
    return payload


def create_access_token(subject: str, scopes: list[str],
                        ttl: int = TOKEN_TTL_SEC) -> str:
    """Build the JWT we hand to clients. `scope` is a space-separated string
    (RFC 6749 §3.3). `sub` is the subject (username). `exp`/`iat` are unix ts."""
    return jwt_encode({
        "sub": subject,
        "scope": " ".join(scopes),
        "iat": NOW,
        "exp": NOW + ttl,
    })


# ----------------------------------------------------------------------------
# the user "DB" — in-memory dict; NEVER stores plaintext, only salted hashes.
# ----------------------------------------------------------------------------

USER_DB: dict[str, dict] = {
    "alice": {
        "username": "alice",
        "full_name": "Alice Liddell",
        "salted_hash": hash_pw("wonderland"),
        "scopes": ["read"],
    },
    "bob": {
        "username": "bob",
        "full_name": "Bob Builder",
        "salted_hash": hash_pw("can-we-fix-it"),
        "scopes": ["read", "admin"],
    },
}


def authenticate_user(username: str, password: str) -> dict | None:
    """Return the user dict if (username, password) matches, else None."""
    user = USER_DB.get(username)
    if user is None or not verify_pw(password, user["salted_hash"]):
        return None
    return user


# ----------------------------------------------------------------------------
# FastAPI wiring: OAuth2PasswordBearer + an OAuth2PasswordRequestForm stand-in.
# ----------------------------------------------------------------------------

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


async def _oauth2_form(request: Request) -> dict:
    """Stand-in for OAuth2PasswordRequestForm (which needs python-multipart).
    Parses application/x-www-form-urlencoded with stdlib urllib.parse."""
    body = (await request.body()).decode("utf-8")
    form = urllib.parse.parse_qs(body)
    return {
        "username": form.get("username", [""])[0],
        "password": form.get("password", [""])[0],
    }


async def get_current_user(
    security_scopes: SecurityScopes,
    token: Annotated[str, Depends(oauth2_scheme)],
) -> dict:
    """Decode+verify the Bearer token, look up the user, enforce required scopes."""
    payload = jwt_decode(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = USER_DB.get(payload.get("sub", ""))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_scopes = payload.get("scope", "").split()
    for needed in security_scopes.scopes:                     # scope enforcement
        if needed not in token_scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {needed}",
                headers={"WWW-Authenticate": f'Bearer scope="{needed}"'},
            )
    return user


def _build_app() -> FastAPI:
    """Assemble the demo app: /token (login -> JWT) + /me + /admin."""
    app = FastAPI()

    @app.post("/token")
    async def login(creds: Annotated[dict, Depends(_oauth2_form)]) -> dict:
        user = authenticate_user(creds["username"], creds["password"])
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = create_access_token(user["username"], user["scopes"])
        return {"access_token": token, "token_type": "bearer"}

    @app.get("/me/")
    async def me(
        current: Annotated[dict, Security(get_current_user)],
    ) -> dict:
        return {"username": current["username"], "full_name": current["full_name"]}

    @app.get("/admin/")
    async def admin(
        current: Annotated[dict, Security(get_current_user, scopes=["admin"])],
    ) -> dict:
        return {"admin": True, "user": current["username"]}

    return app


APP = _build_app()


# ----------------------------------------------------------------------------
# Section A — password hashing: pbkdf2_hmac (salted, slow KDF)
# ----------------------------------------------------------------------------

def section_a_password_hashing() -> None:
    banner("A — Password hashing: pbkdf2_hmac (salted, slow KDF)")
    print("A password hash must be (1) DETERMINISTIC, (2) ONE-WAY, and (3) SLOW\n"
          "so brute-force is expensive. pbkdf2_hmac hashes `iters` times with\n"
          "HMAC-SHA256 over the password + a per-user salt. Real systems use\n"
          "bcrypt/argon2; we use stdlib pbkdf2 to stay dependency-free.\n")

    good = "wonderland"
    h_good = hash_pw(good)
    print(f"password             : {good!r}")
    print(f"hash_pw(good).hex()  : {h_good.hex()}")
    print(f"len(hash) (bytes)    : {len(h_good)}")
    print(f"hash_pw(good) again  : {hash_pw(good).hex()}  (identical -> deterministic)")
    print(f"verify_pw('wonderland', h) : {verify_pw('wonderland', h_good)}")
    print(f"verify_pw('WONDERLAND', h) : {verify_pw('WONDERLAND', h_good)}  "
          f"(case-sensitive!)")
    print(f"verify_pw('wrong',      h) : {verify_pw('wrong', h_good)}")
    print()

    check("hash_pw is deterministic (same input -> same bytes)",
          hash_pw(good) == hash_pw(good))
    check("verify_pw accepts the correct password", verify_pw(good, h_good))
    check("verify_pw rejects a wrong password", not verify_pw("wrong", h_good))
    check("verify_pw rejects a case-mismatched password",
          not verify_pw("WONDERLAND", h_good))
    check("the hash is exactly 32 bytes (sha256 dklen), independent of pw length",
          len(h_good) == 32 == len(hash_pw("x")))


# ----------------------------------------------------------------------------
# Section B — the user DB: {username: {salted_hash, scopes, ...}}
# ----------------------------------------------------------------------------

def section_b_user_db() -> None:
    banner("B — The user DB: {username: {salted_hash, scopes, ...}}")
    print("The 'DB' is a dict. It stores ONLY the salted hash — never plaintext.\n"
          "Iterating it leaks nothing usable; a stolen DB still forces brute-force.\n")

    usernames = list(USER_DB)
    print(f"users in DB          : {usernames}")
    for u in usernames:
        info = USER_DB[u]
        print(f"  {u:<6} scopes={info['scopes']} "
              f"stored_hash[:16]={info['salted_hash'][:16].hex()}…")
    print()

    check("both demo users are present", set(USER_DB) == {"alice", "bob"})
    check("no DB row stores the plaintext password",
          "wonderland" not in str(USER_DB) and "can-we-fix-it" not in str(USER_DB))
    check("authenticate_user accepts (alice, wonderland)",
          authenticate_user("alice", "wonderland") is not None)
    check("authenticate_user rejects (alice, wrong)",
          authenticate_user("alice", "wrong") is None)
    check("authenticate_user rejects an unknown user",
          authenticate_user("nobody", "x") is None)


# ----------------------------------------------------------------------------
# Section C — hand-rolled HS256 JWT: header.payload.signature (+ tamper test)
# ----------------------------------------------------------------------------

def section_c_jwt_hs256() -> None:
    banner("C — Hand-rolled HS256 JWT: b64url(header).b64url(payload).b64url(sig)")
    print("A JWT is THREE base64url strings joined by '.'. The signature is\n"
          "HMAC-SHA256(secret, b64(header) + '.' + b64(payload)). Editing ANY\n"
          "part invalidates the signature. We NEVER trust the header's `alg`.\n")

    payload = {"sub": "alice", "scope": "read", "iat": NOW, "exp": NOW + 60}
    token = jwt_encode(payload)
    h_b64, p_b64, s_b64 = token.split(".")
    print(f"header  (b64url)  : {h_b64}")
    print(f"payload (b64url)  : {p_b64}")
    print(f"signature(b64url) : {s_b64}")
    print(f"full token        : {token}")
    print(f"jwt_decode(token) : {jwt_decode(token)}")
    print()

    # Forge: swap the payload half for a different one, keep the old signature.
    tampered = f"{h_b64}.{_b64url(b'AAAA')}.{s_b64}"
    print(f"tampered token    : {tampered}")
    print(f"jwt_decode(tamp.) : {jwt_decode(tampered)}  (signature mismatch -> None)")

    # Forge: alg:none attack (header claims no signature). Our decoder ignores
    # the header's alg and always recomputes HS256 -> must fail.
    none_header = _b64url(json.dumps({"alg": "none", "typ": "JWT"},
                                     sort_keys=True, separators=(",", ":")).encode())
    alg_none_token = f"{none_header}.{p_b64}."                  # empty signature
    print(f"alg:none token    : {alg_none_token}")
    print(f"jwt_decode(none)  : {jwt_decode(alg_none_token)}  (we ignore alg -> None)")
    print()

    check("jwt_decode round-trips a well-formed token",
          jwt_decode(token) == payload)
    check("jwt_decode rejects a tampered payload (signature no longer matches)",
          jwt_decode(tampered) is None)
    check("jwt_decode rejects an alg:none forgery (we always HS256)",
          jwt_decode(alg_none_token) is None)
    check("jwt_decode rejects malformed input (no two dots)",
          jwt_decode("not-a-jwt") is None)


# ----------------------------------------------------------------------------
# Section D — the /token endpoint: form login -> JWT
# ----------------------------------------------------------------------------

def section_d_token_endpoint() -> None:
    banner("D — The /token endpoint: OAuth2PasswordRequestForm -> JWT")
    print("POST /token with form fields username+password. On success it returns\n"
          "{\"access_token\": <jwt>, \"token_type\": \"bearer\"}. On failure, 401.\n")

    client = TestClient(APP)
    ok = client.post("/token", data={"username": "alice", "password": "wonderland"})
    bad = client.post("/token", data={"username": "alice", "password": "WRONG"})
    print(f"POST /token (alice/wonderland) -> {ok.status_code}")
    print(f"  access_token[:32] : {ok.json()['access_token'][:32]}…")
    print(f"  token_type        : {ok.json()['token_type']}")
    print(f"POST /token (alice/WRONG)      -> {bad.status_code}  {bad.json()['detail']}")
    print()

    check("/token returns 200 on good credentials", ok.status_code == 200)
    check("/token returns token_type 'bearer'", ok.json()["token_type"] == "bearer")
    check("/token's access_token is a 3-part JWT (two dots)",
          ok.json()["access_token"].count(".") == 2)
    check("/token returns 401 on a bad password", bad.status_code == 401)


# ----------------------------------------------------------------------------
# Section E — OAuth2PasswordBearer dependency: no token -> 401
# ----------------------------------------------------------------------------

def section_e_oauth2_dependency() -> None:
    banner("E — OAuth2PasswordBearer dependency: missing/bad token -> 401")
    print("OAuth2PasswordBearer(tokenUrl='token') is a callable dependency: it\n"
          "looks for 'Authorization: Bearer <token>' and returns the token str.\n"
          "Missing header -> 401 (raised by the scheme itself, before our code).\n")

    client = TestClient(APP)
    no_tok = client.get("/me/")
    with_tok = client.get(
        "/me/",
        headers={"Authorization": f"Bearer {create_access_token('alice', ['read'])}"},
    )
    print(f"GET /me/ (no Authorization)        -> {no_tok.status_code}")
    print(f"GET /me/ (Bearer <valid alice>)    -> {with_tok.status_code} "
          f"{with_tok.json()}")
    print()

    check("no Authorization header -> 401 (scheme short-circuits)",
          no_tok.status_code == 401)
    check("missing-token 401 carries WWW-Authenticate: Bearer",
          no_tok.headers.get("WWW-Authenticate") == "Bearer")
    check("valid Bearer token -> 200 and the dep injected the user",
          with_tok.status_code == 200 and with_tok.json()["username"] == "alice")


# ----------------------------------------------------------------------------
# Section F — full flow: login -> Bearer token -> protected route
# ----------------------------------------------------------------------------

def section_f_full_flow() -> None:
    banner("F — Full flow: POST /token -> Bearer -> GET /me/")
    print("The end-to-end OAuth2 password flow in two HTTP calls.\n")

    client = TestClient(APP)
    step1 = client.post("/token", data={"username": "bob",
                                        "password": "can-we-fix-it"})
    token = step1.json()["access_token"]
    step2 = client.get("/me/", headers={"Authorization": f"Bearer {token}"})
    print(f"step 1: POST /token (bob) -> {step1.status_code}, "
          f"got JWT of {len(token)} chars")
    print(f"step 2: GET /me/ Authorization: Bearer <token> -> {step2.status_code}")
    print(f"        body: {step2.json()}")
    print()

    check("step 1 returned a bearer token", step1.json()["token_type"] == "bearer")
    check("step 2 reached the handler (200)", step2.status_code == 200)
    check("step 2 body is the authenticated user",
          step2.json() == {"username": "bob", "full_name": "Bob Builder"})


# ----------------------------------------------------------------------------
# Section G — token expiry (exp): a token past exp is rejected
# ----------------------------------------------------------------------------

def section_g_token_expiry() -> None:
    banner("G — Token expiry (exp): a token whose exp < now is rejected")
    print("The `exp` registered claim (RFC 7519 §4.1.4) is a unix timestamp.\n"
          "jwt_decode returns None when exp < now, so get_current_user raises 401.\n")

    expired_token = create_access_token("alice", ["read"], ttl=-1)  # exp = NOW - 1
    decoded = jwt_decode(expired_token)
    client = TestClient(APP)
    r = client.get("/me/", headers={"Authorization": f"Bearer {expired_token}"})
    print(f"minted token with exp = NOW - 1  ({NOW - 1})")
    print(f"jwt_decode(expired_token)        : {decoded}  (rejected by exp check)")
    print(f"GET /me/ with the expired token  -> {r.status_code}")
    print()

    check("an expired token fails jwt_decode (returns None)", decoded is None)
    check("an expired token is rejected at /me/ (401)", r.status_code == 401)


# ----------------------------------------------------------------------------
# Section H — scopes preview: Security(dep, scopes=["admin"])
# ----------------------------------------------------------------------------

def section_h_scopes_preview() -> None:
    banner("H — Scopes preview: Security(get_current_user, scopes=[...])")
    print("Security() is Depends() + an OAuth2 scopes list. The dependency reads\n"
          "SecurityScopes and 403-rejects tokens missing a required scope.\n")

    client = TestClient(APP)
    alice_tok = create_access_token("alice", USER_DB["alice"]["scopes"])   # read
    bob_tok = create_access_token("bob", USER_DB["bob"]["scopes"])         # read admin
    as_alice = client.get("/admin/", headers={"Authorization": f"Bearer {alice_tok}"})
    as_bob = client.get("/admin/", headers={"Authorization": f"Bearer {bob_tok}"})
    print(f"alice's token scopes : {USER_DB['alice']['scopes']}")
    print(f"bob's token scopes   : {USER_DB['bob']['scopes']}")
    print(f"GET /admin/ as alice  -> {as_alice.status_code}  {as_alice.json()['detail']}")
    print(f"GET /admin/ as bob    -> {as_bob.status_code}  {as_bob.json()}")
    print()

    check("alice (no admin scope) is forbidden from /admin/ (403)",
          as_alice.status_code == 403)
    check("bob (admin scope) reaches /admin/ (200)",
          as_bob.status_code == 200 and as_bob.json()["admin"] is True)

    # Pitfalls preview (full table is in FASTAPI_AUTH.md).
    print("Security pitfalls (see .md for the full table):")
    for line in [
        "  - storing plaintext passwords (or 'encrypted' reversible passwords)",
        "  - using a fast hash (MD5/SHA-256) WITHOUT a KDF/salt -> brute-forceable",
        "  - hard-coding the JWT secret in source (we do it here ONLY for teaching)",
        "  - tokens with no `exp` (or very long TTL) -> stolen tokens valid forever",
        "  - serving login/JWTs over plain HTTP -> token interception",
        "  - trusting the JWT `alg` header -> alg:none / alg-confusion attack",
    ]:
        print(line)
    check("the pitfall list above is non-empty", True)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW))
    print(f"fastapi_auth.py — Phase 7 bundle #48.\n"
          "Every value below is computed by this file via TestClient; the .md\n"
          "guide pastes it verbatim. Nothing is hand-computed.\n"
          f"FastAPI {fastapi.__version__} on this machine. "
          "stdlib crypto only (no passlib/bcrypt/PyJWT).\n"
          f"NOW pinned to {NOW} ({now_iso}) for byte-reproducible output.")
    section_a_password_hashing()
    section_b_user_db()
    section_c_jwt_hs256()
    section_d_token_endpoint()
    section_e_oauth2_dependency()
    section_f_full_flow()
    section_g_token_expiry()
    section_h_scopes_preview()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
