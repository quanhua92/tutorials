# FastAPI Auth — `OAuth2PasswordBearer` + JWT, Passwords as Salted Hashes

> **The one rule:** the moment your API has anything worth protecting, "I
> hardcode a password check" stops being enough. Real auth has three pieces: a
> `/token` endpoint that **issues a signed token** after checking credentials,
> a **dependency** that **verifies the token on every protected route**, and a
> password store that **never holds plaintext** — only slow, salted hashes.
> FastAPI ships the wiring for the first two (`OAuth2PasswordBearer` +
> `Security`); the third is plain crypto hygiene.

**Companion code:** [`fastapi_auth.py`](./fastapi_auth.py).
**Every number, token, and table below is printed by `uv run python
fastapi_auth.py`** — change the code, re-run, re-paste. Nothing here is
hand-computed. Captured stdout lives in
[`fastapi_auth_output.txt`](./fastapi_auth_output.txt).

> ⚠️ **Educational, dependency-free crypto.** This bundle ships **zero**
> crypto deps: password hashing uses `hashlib.pbkdf2_hmac`; the JWT is a
> **hand-rolled HS256** built from `hmac` + `hashlib.sha256` + `base64` +
> `json`. **Production code must NOT do this** — use `passlib[bcrypt]` or
> `argon2` (via `pwdlib[argon2]`) for passwords, and `PyJWT` or
> `python-jose` for JWTs. The stdlib implementation here is for learning the
> **format** of these primitives, not for shipping security. See §1 and §3.

**Goal of this bundle (lineage, old → new):**

> from *"I hardcode a password check"*
> → *"OAuth2PasswordBearer + JWT: the `/token` endpoint issues a signed token,
>   a dependency verifies it on protected routes, and passwords are never
>   stored — only slow salted hashes."*

🔗 Builds on [`FASTAPI_DEPENDENCIES`](./FASTAPI_DEPENDENCIES.md) (Phase 7
#45) — `OAuth2PasswordBearer` and `Security()` are *just* `Depends()` with
extra powers; you need that bundle's per-request cache and `yield`-dep mental
model first. Forward refs: [`FASTAPI_TESTING`](./FASTAPI_TESTING.md) (Phase 7
#49) for `dependency_overrides`-based auth test fakes;
[`FASTAPI_MIDDLEWARE_LIFESPAN`](./FASTAPI_MIDDLEWARE_LIFESPAN.md) (Phase 7
#47) for CORS (a Bearer token from a browser still has to *reach* your API);
and [`HMAC_HASHLIB`](./HMAC_HASHLIB.md) (Phase 1) for the `hmac` / `hashlib`
internals reused here.

---

## 0. The four ideas on one page

```mermaid
graph TD
    U["user types<br/>username + password"] -->|form POST| T["/token endpoint<br/>verify_pw -> mint JWT"]
    T -->|issue| JWT["access_token<br/>header.payload.signature"]
    JWT -->|store in client| H["Authorization: Bearer <jwt>"]
    H -->|on every protected call| DEP["OAuth2PasswordBearer<br/>(a Depends!)"]
    DEP -->|extract token| GV["get_current_user<br/>jwt_decode + scope check"]
    GV -->|inject user dict| ROUTE["handler runs"]
    style T fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style JWT fill:#fef9e7,stroke:#f1c40f
    style DEP fill:#eaf2f8,stroke:#2980b9
    style ROUTE fill:#eafaf1,stroke:#27ae60
```

| Concept | What it is | Lives in |
|---|---|---|
| **Salted KDF hash** | `pbkdf2_hmac(pw, salt, iters)` — slow, one-way, per-user | your user store |
| **JWT** | `b64url(header).b64url(payload).b64url(sig)` — signed, NOT encrypted | the `access_token` string |
| **`OAuth2PasswordBearer`** | callable `Depends` that pulls `Bearer <tok>` from the header | `fastapi.security` |
| **`Security(dep, scopes=[…])`** | `Depends` + an OAuth2 scope list, surfaced as `SecurityScopes` | `fastapi` |

---

## 1. Password hashing: never store plaintext (PBKDF2)

A password hash must be **(1) deterministic** (same input → same bytes),
**(2) one-way** (you can't recover the password from the hash), and
**(3) slow** — slow enough that an attacker who steals the hash table can't
brute-force millions of guesses per second. The Python stdlib provides
[`hashlib.pbkdf2_hmac`](https://docs.python.org/3/library/hashlib.html#hashlib.pbkdf2_hmac)
(PKCS#5 PBKDF2 with HMAC as the PRF):

```python
hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations, dklen=32)
```

`pbkdf2_hmac` runs HMAC-SHA256 `iterations` times over `password || salt`. The
`salt` defeats rainbow tables and makes equal passwords hash differently
across users; `iterations` is the cost knob (the Python docs explicitly say
"[as of 2022] hundreds of thousands of iterations of SHA-256 are suggested",
per NIST-SP-800-132). We use 10 000 here only to keep the demo fast —
**production uses ≥100 000**.

Verification is re-hash + compare. The compare **must** be constant-time
([`hmac.compare_digest`](https://docs.python.org/3/library/hmac.html#hmac.compare_digest))
so an attacker can't time-leak which byte position first mismatched.

> From `fastapi_auth.py` Section A:
> ```
> ======================================================================
> SECTION A — Password hashing: pbkdf2_hmac (salted, slow KDF)
> ======================================================================
> A password hash must be (1) DETERMINISTIC, (2) ONE-WAY, and (3) SLOW
> so brute-force is expensive. pbkdf2_hmac hashes `iters` times with
> HMAC-SHA256 over the password + a per-user salt. Real systems use
> bcrypt/argon2; we use stdlib pbkdf2 to stay dependency-free.
> 
> password             : 'wonderland'
> hash_pw(good).hex()  : 4501f0be939205d771b4a5d85ffc09fc29c33eaa1c8579892ae10466edf20c61
> len(hash) (bytes)    : 32
> hash_pw(good) again  : 4501f0be939205d771b4a5d85ffc09fc29c33eaa1c8579892ae10466edf20c61  (identical -> deterministic)
> verify_pw('wonderland', h) : True
> verify_pw('WONDERLAND', h) : False  (case-sensitive!)
> verify_pw('wrong',      h) : False
> 
> [check] hash_pw is deterministic (same input -> same bytes): OK
> [check] verify_pw accepts the correct password: OK
> [check] verify_pw rejects a wrong password: OK
> [check] verify_pw rejects a case-mismatched password: OK
> [check] the hash is exactly 32 bytes (sha256 dklen), independent of pw length: OK
> ```

### Why pbkdf2 and not bcrypt/argon2 here (and the reverse in production)

This bundle stays dependency-free (`passlib`/`bcrypt`/`argon2`/`PyJWT` are
**not** in `pyproject.toml`), so we use `pbkdf2_hmac` — a real, NIST-approved
KDF shipped with CPython. It is **slower to attack than raw SHA-256** because
each guess costs `iterations` HMAC calls. But bcrypt and especially **argon2**
(the 2015 Password Hashing Competition winner) are stronger still: they are
**memory-hard** (forcing GPU/ASIC attackers to spend RAM, not just cycles),
and bcrypt has a baked-in work factor in the hash string itself. The official
FastAPI tutorial now uses `pwdlib[argon2]`. **Use bcrypt/argon2 in real
code;** this stdlib version is for learning the shape of "salted, slow,
one-way."

### Why compare with `hmac.compare_digest` (internals)

`a == b` on `bytes` returns `False` on the **first** mismatched byte. An
attacker who can measure response time (over many requests, averaging out
noise) can sometimes tell *which* byte position first differed — and walk
the hash byte-by-byte. `hmac.compare_digest` runs in time independent of
where the first difference is, closing that side channel. It's a one-liner
that has zero excuse to skip.

---

## 2. The user "DB": a dict of `{username: {salted_hash, scopes, …}}`

The "database" is just an in-memory dict. The crucial invariant: **no row
ever holds the plaintext password** — only the salted hash, plus any
non-secret metadata (display name, scopes). If the table is exfiltrated, the
attacker still has to mount an offline brute-force against a slow KDF to
recover *any* password.

> From `fastapi_auth.py` Section B:
> ```
> ======================================================================
> SECTION B — The user DB: {username: {salted_hash, scopes, ...}}
> ======================================================================
> The 'DB' is a dict. It stores ONLY the salted hash — never plaintext.
> Iterating it leaks nothing usable; a stolen DB still forces brute-force.
> 
> users in DB          : ['alice', 'bob']
>   alice  scopes=['read'] stored_hash[:16]=4501f0be939205d771b4a5d85ffc09fc…
>   bob    scopes=['read', 'admin'] stored_hash[:16]=5e1b12fbada17f0d413e1ababa52318b…
> 
> [check] both demo users are present: OK
> [check] no DB row stores the plaintext password: OK
> [check] authenticate_user accepts (alice, wonderland): OK
> [check] authenticate_user rejects (alice, wrong): OK
> [check] authenticate_user rejects an unknown user: OK
> ```

**Determinism note (not a security choice):** this bundle uses a single
hardcoded `FIXED_SALT` for every user so the captured stdout is
byte-reproducible. **Real systems use a per-user random salt**
(`os.urandom(16)`) — otherwise two users who pick the same password get the
*same* hash, which both leaks that fact and lets one precomputed cracking run
cover them all.

### Why `authenticate_user` returns `None` on an *unknown username* (timing)

A naive implementation returns `False` immediately if the username isn't
found, and only hashes if it is — leaking whether a username exists via
response time. The official FastAPI tutorial mitigates this by always hashing
against a dummy hash even when the user is missing. Our toy returns `None`
either way without that defense — call it out as a known shortcut; in
production, copy the dummy-hash trick.

---

## 3. The JWT: `header.payload.signature` (hand-rolled HS256)

A [JWT (RFC 7519)](https://datatracker.ietf.org/doc/html/rfc7519) is **three
base64url strings joined by dots**. Per the [jwt.io introduction](https://jwt.io/introduction)
and RFC 7515:

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9       ← header   {"alg":"HS256","typ":"JWT"}
.eyJleHAiOjE3...ic3ViIjoiYWxpY2UifQ        ← payload  {"sub":"alice","exp":...,...}
.T1TGFeNqQs0QvOorqLy6C9ZHd91259dce-94t-t6wHI ← signature
```

For **HS256**, the signature is computed as:

```
HMAC-SHA256(secret, base64url(header) + "." + base64url(payload))
```

The signature is the **only** part that uses the secret. The header and
payload are **base64url-encoded, not encrypted** — anyone with the token can
`base64url_decode` the payload and read it. **Never put a secret in a JWT
payload.** What the signature buys you is *integrity*: editing any byte of
header or payload invalidates the signature, and the server rejects forged
tokens because it can't recompute the correct HMAC without the secret.

> From `fastapi_auth.py` Section C:
> ```
> ======================================================================
> SECTION C — Hand-rolled HS256 JWT: b64url(header).b64url(payload).b64url(sig)
> ======================================================================
> A JWT is THREE base64url strings joined by '.'. The signature is
> HMAC-SHA256(secret, b64(header) + '.' + b64(payload)). Editing ANY
> part invalidates the signature. We NEVER trust the header's `alg`.
> 
> header  (b64url)  : eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9
> payload (b64url)  : eyJleHAiOjE3MDAwMDAwNjAsImlhdCI6MTcwMDAwMDAwMCwic2NvcGUiOiJyZWFkIiwic3ViIjoiYWxpY2UifQ
> signature(b64url) : T1TGFeNqQs0QvOorqLy6C9ZHd91259dce-94t-t6wHI
> full token        : eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MDAwMDAwNjAsImlhdCI6MTcwMDAwMDAwMCwic2NvcGUiOiJyZWFkIiwic3ViIjoiYWxpY2UifQ.T1TGFeNqQs0QvOorqLy6C9ZHd91259dce-94t-t6wHI
> jwt_decode(token) : {'exp': 1700000060, 'iat': 1700000000, 'scope': 'read', 'sub': 'alice'}
> 
> tampered token    : eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.QUFBQQ.T1TGFeNqQs0QvOorqLy6C9ZHd91259dce-94t-t6wHI
> jwt_decode(tamp.) : None  (signature mismatch -> None)
> alg:none token    : eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJleHAiOjE3MDAwMDAwNjAsImlhdCI6MTcwMDAwMDAwMCwic2NvcGUiOiJyZWFkIiwic3ViIjoiYWxpY2UifQ.
> jwt_decode(none)  : None  (we ignore alg -> None)
> 
> [check] jwt_decode round-trips a well-formed token: OK
> [check] jwt_decode rejects a tampered payload (signature no longer matches): OK
> [check] jwt_decode rejects an alg:none forgery (we always HS256): OK
> [check] jwt_decode rejects malformed input (no two dots): OK
> ```

### Why we ignore the header's `alg` (the `alg:none` attack)

The single most dangerous JWT bug is **algorithm confusion**. A forged token
sets `{"alg": "none"}` in the header and omits the signature; if the server
trusts the header and switches behavior on `alg`, it accepts the forgery. The
CVE-history fix is twofold: (a) **always** pass an explicit `algorithms=[…]`
allowlist to your JWT library, never `algorithms=None`; (b) the library must
*not* honor the token's own `alg`. Our toy encoder **hardcodes HS256** and
the decoder **always recomputes HS256**, ignoring the header entirely — that
makes `alg:none` and `alg:RS256→HS256` confusion forgeries fail by
construction (see them both return `None` above). `PyJWT` and `python-jose`
do the same internally *if you pass the allowlist*; if you don't, they're
vulnerable. Always pass it.

### Why base64url and not base64 (internals)

JWT is meant for "HTTP headers and URI query parameters" (RFC 7519 §1). The
[base64url alphabet](https://datatracker.ietf.org/doc/html/rfc7515#section-2)
swaps `+` → `-` and `/` → `_`, and drops the `=` padding, so the token is
URL-safe without percent-encoding. Our `_b64url` strips padding;
`_b64url_dec` re-pads before decoding.

### The registered claims you'll actually use

| Claim | Meaning | Used here? |
|---|---|---|
| `sub` | **sub**ject (the user id; RFC 7519 §4.1.2) | yes — `"sub": "alice"` |
| `exp` | **exp**iration time (unix ts; §4.1.4) | yes — rejected past it (§7) |
| `iat` | **i**ssued **a**t (unix ts; §4.1.6) | yes — informational |
| `scope` | OAuth2 scopes, space-separated (RFC 6749 §3.3) | yes — enforced in §8 |
| `iss`/`aud`/`nbf` | issuer / audience / not-before | no — omit in the toy |

---

## 4. The `/token` endpoint: form login → JWT

OAuth2's password flow sends `username` + `password` as
`application/x-www-form-urlencoded` form fields (RFC 6749 §4.3). FastAPI's
[`OAuth2PasswordRequestForm`](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
encodes that contract as a dependency with `.username` and `.password`
attributes. The `/token` handler:

1. Looks up the user, runs `verify_pw` against the stored hash.
2. On success, mints a JWT with `{"sub": username, "scope": ..., "exp": now+TTL}`.
3. Returns `{"access_token": <jwt>, "token_type": "bearer"}` — the exact
   shape the OAuth2 spec mandates and that Swagger UI / openapi-client
   generators expect.

> From `fastapi_auth.py` Section D:
> ```
> ======================================================================
> SECTION D — The /token endpoint: OAuth2PasswordRequestForm -> JWT
> ======================================================================
> POST /token with form fields username+password. On success it returns
> {"access_token": <jwt>, "token_type": "bearer"}. On failure, 401.
> 
> POST /token (alice/wonderland) -> 200
>   access_token[:32] : eyJhbGciOiJIUzI1NiIsInR5cCI6IkpX…
>   token_type        : bearer
> POST /token (alice/WRONG)      -> 401  Incorrect username or password
> 
> [check] /token returns 200 on good credentials: OK
> [check] /token returns token_type 'bearer': OK
> [check] /token's access_token is a 3-part JWT (two dots): OK
> [check] /token returns 401 on a bad password: OK
> ```

### `_oauth2_form`: a stdlib stand-in for `OAuth2PasswordRequestForm`

`OAuth2PasswordRequestForm` is declared in `fastapi.security`, but using it
at request time requires the `python-multipart` package (not in
`pyproject.toml`). We re-implement its two-field contract with a tiny async
dependency that reads `request.body()` and parses
`application/x-www-form-urlencoded` with stdlib `urllib.parse.parse_qs`.
**Same wire contract**, zero new deps. Real code uses the real form class
once `python-multipart` is installed.

### Why a 401 (not 403) on bad credentials

401 Unauthorized means *"no valid authentication"*. 403 Forbidden means
*"you're authenticated but not allowed"*. A wrong password is the former; a
missing scope (§8) is the latter. The 401 also carries a
`WWW-Authenticate: Bearer` response header (RFC 7235) so clients know which
scheme to retry with.

---

## 5. `OAuth2PasswordBearer`: the auth dependency

[`OAuth2PasswordBearer(tokenUrl="token")`](https://fastapi.tiangolo.com/tutorial/security/first-steps/)
is a callable instance that doubles as a `Depends`. When FastAPI resolves a
route that depends on it, the scheme:

1. Looks for the `Authorization` header.
2. Checks it starts with `Bearer `, strips the prefix.
3. Returns the token string (the part after `Bearer `).
4. If any of the above fails, raises **401** with `WWW-Authenticate: Bearer`
   *before* your handler runs.

The `tokenUrl="token"` argument does **not** create the `/token` route — it
only tells the OpenAPI schema (and Swagger UI's "Authorize" dialog) where
the client should POST to get a token. You still have to write that route
yourself (§4).

`get_current_user(token=Depends(oauth2_scheme))` then turns that raw string
into a real user: `jwt_decode(token)` → look up the subject in `USER_DB` →
inject the user dict. 🔗 This is just the dependency-injection pattern from
[`FASTAPI_DEPENDENCIES`](./FASTAPI_DEPENDENCIES.md); the only new piece is
that the dependable *also* integrates with the OpenAPI security scheme.

> From `fastapi_auth.py` Section E:
> ```
> ======================================================================
> SECTION E — OAuth2PasswordBearer dependency: missing/bad token -> 401
> ======================================================================
> OAuth2PasswordBearer(tokenUrl='token') is a callable dependency: it
> looks for 'Authorization: Bearer <token>' and returns the token str.
> Missing header -> 401 (raised by the scheme itself, before our code).
> 
> GET /me/ (no Authorization)        -> 401
> GET /me/ (Bearer <valid alice>)    -> 200 {'username': 'alice', 'full_name': 'Alice Liddell'}
> 
> [check] no Authorization header -> 401 (scheme short-circuits): OK
> [check] missing-token 401 carries WWW-Authenticate: Bearer: OK
> [check] valid Bearer token -> 200 and the dep injected the user: OK
> ```

---

## 6. The full OAuth2 password flow end-to-end

Two HTTP calls. The client first POSTs the credentials to `/token`, gets a
JWT back, then sends it as `Authorization: Bearer <jwt>` on every subsequent
protected request. The token is stateless — the server doesn't remember it;
each request re-verifies the signature and expiry.

```mermaid
sequenceDiagram
    participant C as Client
    participant T as /token
    participant H as /me/ (handler)
    participant D as OAuth2PasswordBearer + get_current_user
    C->>T: POST username=alice&password=wonderland
    T->>T: verify_pw -> mint JWT(exp, sub, scope)
    T-->>C: 200 {"access_token": <jwt>, "token_type": "bearer"}
    C->>H: GET /me/  Authorization: Bearer <jwt>
    H->>D: Depends(oauth2_scheme)
    D->>D: strip "Bearer ", jwt_decode, lookup user
    D-->>H: inject {"username":"alice", ...}
    H-->>C: 200 {"username":"alice","full_name":"Alice Liddell"}
```

> From `fastapi_auth.py` Section F:
> ```
> ======================================================================
> SECTION F — Full flow: POST /token -> Bearer -> GET /me/
> ======================================================================
> The end-to-end OAuth2 password flow in two HTTP calls.
> 
> step 1: POST /token (bob) -> 200, got JWT of 172 chars
> step 2: GET /me/ Authorization: Bearer <token> -> 200
>         body: {'username': 'bob', 'full_name': 'Bob Builder'}
> 
> [check] step 1 returned a bearer token: OK
> [check] step 2 reached the handler (200): OK
> [check] step 2 body is the authenticated user: OK
> ```

---

## 7. Token expiry (`exp`): a token past `exp` is rejected

The `exp` registered claim (RFC 7519 §4.1.4) is the unix timestamp after
which the token MUST NOT be accepted. `jwt_decode` returns `None` when
`payload["exp"] < now`, so `get_current_user` raises 401 just as it would for
a bad signature. Short-lived tokens (15 min – 1 h typical) limit the blast
radius of a stolen token — combined with a refresh-token flow for ergonomic
renewal, this is the standard access/refresh split.

> From `fastapi_auth.py` Section G:
> ```
> ======================================================================
> SECTION G — Token expiry (exp): a token whose exp < now is rejected
> ======================================================================
> The `exp` registered claim (RFC 7519 §4.1.4) is a unix timestamp.
> jwt_decode returns None when exp < now, so get_current_user raises 401.
> 
> minted token with exp = NOW - 1  (1699999999)
> jwt_decode(expired_token)        : None  (rejected by exp check)
> GET /me/ with the expired token  -> 401
> 
> [check] an expired token fails jwt_decode (returns None): OK
> [check] an expired token is rejected at /me/ (401): OK
> ```

### Why we pin `NOW` (determinism, not crypto)

Real tokens use `int(time.time())` for `iat`/`exp`. We pin `NOW = 1_700_000_000`
so the captured stdout is byte-identical across re-runs (otherwise the
`iat`/`exp` claims and the signature would change every second). This is a
documentation concern, not a security one — production tokens are *meant* to
differ every second.

---

## 8. Scopes: `Security(dep, scopes=[…])`

[`Security()`](https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/)
is `Depends()` plus an OAuth2 **scope** list. The dependable reads a
[`SecurityScopes`](https://fastapi.tiangolo.com/reference/security/#fastapi.security.SecurityScopes)
object (auto-injected by FastAPI) and 403-rejects tokens whose `scope` claim
is missing a required entry. This is how you build "anyone authenticated can
GET, only admins can DELETE": same dependency, different required scopes per
route.

```mermaid
graph LR
    R["route @app.get('/admin/')"] -->|Security(get_current_user, scopes=['admin'])| S["SecurityScopes(scopes=['admin'])"]
    S --> GC["get_current_user(security_scopes, token)"]
    JWT["token payload: scope='read admin'"] --> GC
    GC -->|for each needed: in payload scopes?| D{match?}
    D -->|yes| OK["200 -> handler"]
    D -->|no| F["403 Missing required scope: admin"]
    style OK fill:#eafaf1,stroke:#27ae60
    style F fill:#fdecea,stroke:#c0392b
```

> From `fastapi_auth.py` Section H:
> ```
> ======================================================================
> SECTION H — Scopes preview: Security(get_current_user, scopes=[...])
> ======================================================================
> Security() is Depends() + an OAuth2 scopes list. The dependency reads
> SecurityScopes and 403-rejects tokens missing a required scope.
> 
> alice's token scopes : ['read']
> bob's token scopes   : ['read', 'admin']
> GET /admin/ as alice  -> 403  Missing required scope: admin
> GET /admin/ as bob    -> 200  {'admin': True, 'user': 'bob'}
> 
> [check] alice (no admin scope) is forbidden from /admin/ (403): OK
> [check] bob (admin scope) reaches /admin/ (200): OK
> Security pitfalls (see .md for the full table):
>   - storing plaintext passwords (or 'encrypted' reversible passwords)
>   - using a fast hash (MD5/SHA-256) WITHOUT a KDF/salt -> brute-forceable
>   - hard-coding the JWT secret in source (we do it here ONLY for teaching)
>   - tokens with no `exp` (or very long TTL) -> stolen tokens valid forever
>   - serving login/JWTs over plain HTTP -> token interception
>   - trusting the JWT `alg` header -> alg:none / alg-confusion attack
> [check] the pitfall list above is non-empty: OK
> ```

🔗 For testing this kind of route without doing real crypto per test,
[`FASTAPI_TESTING`](./FASTAPI_TESTING.md) (Phase 7 #49) covers
`app.dependency_overrides[get_current_user] = fake` — swap the dep for a
constant user dict in your test suite.

---

## Pitfalls

| Trap | Example | The fix |
|---|---|---|
| **Storing plaintext** (or "encrypted" reversible) passwords | `db[u] = password` | only store a salted KDF hash (bcrypt / argon2 / pbkdf2); never the plaintext, never symmetric-encrypted reversible text |
| **Fast hash without KDF** | `hashlib.sha256(pw).hexdigest()` | use `pbkdf2_hmac` / `scrypt` / bcrypt / argon2 — *any* password hash MUST be slow and salted; raw SHA-* is brute-forceable at billions/s on a GPU |
| **Shared / hardcoded salt** | one global `SALT` for every user | per-user random salt (`os.urandom(16)`), stored alongside the hash; defeats rainbow tables and same-password correlation |
| **JWT secret in source / committed** | `SECRET_KEY = "..."` checked into git | load from env / vault; rotate; never commit (the secret in this bundle is a *known-public* teaching value) |
| **No `exp` (or huge TTL)** | 1-year access tokens | short `exp` (15 min – 1 h) + a refresh-token flow; long-lived access tokens magnify any theft |
| **Plain HTTP for login / API** | `http://api.example.com/token` | force HTTPS (HSTS, redirect-on-HTTP); a Bearer token intercepted over HTTP is game over |
| **Trusting the JWT `alg` header** | calling `jwt.decode(token, key)` without `algorithms=[...]` | ALWAYS pass the explicit allowlist (`["HS256"]`); a missing list enables the `alg:none` and `alg:RS256→HS256` confusion attacks |
| **Comparing hashes with `==`** | `if user_hash == candidate_hash:` | `hmac.compare_digest(a, b)` — constant-time, defeats timing side-channels |
| **`OAuth2PasswordBearer` with `auto_error=False` silently returns `None`** | missing token → handler runs with `token=None` → `AttributeError` or a 500 | leave `auto_error=True` (the default); only opt out if you have a real fallback dep |
| **Returning `False` early on unknown username** | "user not found" returns in 0 ms, valid user takes 50 ms | always run a `verify_pw` against a *dummy* hash even on miss, so timing can't enumerate usernames |
| **Leaking secrets into JWT payload** | `{"sub":"a", "credit_card":"4111…"}` | payloads are base64, *not encrypted* — anyone holding the token can read it; use encrypted tokens (JWE) if you must hide claims |
| **Hand-rolled crypto in production** | shipping the `jwt_encode` from this file | use `PyJWT` / `python-jose` — battle-audited, handle edge cases (JSON nesting, key rotation, kid headers) you will get wrong |

---

## Cheat sheet

- **Password hashing** — `hashlib.pbkdf2_hmac("sha256", pw, salt, iters, dklen=32)`.
  Deterministic, one-way, slow. Verify by re-hash +
  `hmac.compare_digest(...)`. **Prod: bcrypt / argon2.**
- **User store** — `{username: {salted_hash, scopes, ...}}`. NEVER the
  plaintext password. Use a per-user random salt in production.
- **JWT shape** — `b64url(header).b64url(payload).b64url(sig)`. Header is
  `{"alg":"HS256","typ":"JWT"}`. Payload holds claims (`sub`, `exp`, `iat`,
  `scope`). Signature = `HMAC-SHA256(secret, b64(header)+"."+b64(payload))`.
- **HS256 rules** — never trust the header's `alg` (always recompute HS256);
  pass `algorithms=[...]` to any real decoder; never put secrets in the
  payload (it's base64, not encrypted).
- **`/token` endpoint** — POST form (`username`, `password`) → verify →
  return `{"access_token": jwt, "token_type": "bearer"}`. Bad creds → 401
  with `WWW-Authenticate: Bearer`.
- **`OAuth2PasswordBearer(tokenUrl="token")`** — callable `Depends` that
  pulls `Bearer <token>` out of the Authorization header. Missing → 401
  before your handler runs. `tokenUrl` is just metadata for OpenAPI/Swagger.
- **`get_current_user`** — `Depends(oauth2_scheme)` → `jwt_decode` → user
  lookup → inject the user dict. 401 if decode or lookup fails.
- **`Security(dep, scopes=[…])`** — `Depends` + an OAuth2 scope list. Read
  `SecurityScopes` inside the dep; 403 if the token's `scope` claim is
  missing a required entry.
- **`exp`** — registered claim; reject when `exp < now`. Short TTL limits
  the cost of a stolen token. Pair with a refresh-token flow.
- **401 vs 403** — 401 = "no valid auth" (bad password, missing/invalid
  token); 403 = "auth ok, not allowed" (missing scope, disabled user).

---

## Sources

- **FastAPI docs — Security: First Steps.**
  https://fastapi.tiangolo.com/tutorial/security/first-steps/
  *The `OAuth2PasswordBearer(tokenUrl="token")` callable-dependency pattern;
  the "Bearer foobar" Authorization-header convention; the 401 short-circuit
  behavior. Quoted in §5.*
- **FastAPI docs — OAuth2 with Password (and hashing), Bearer with JWT tokens.**
  https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
  *The canonical `/token` endpoint shape, `OAuth2PasswordRequestForm`,
  `{"access_token":..., "token_type":"bearer"}` response, `SECRET_KEY` /
  `ALGORITHM = "HS256"` / `ACCESS_TOKEN_EXPIRE_MINUTES` constants, the
  `credentials_exception` with `WWW-Authenticate: Bearer`, and the timing-
  attack mitigation via a dummy hash on user-not-found. The whole bundle's
  shape mirrors this tutorial; we substitute stdlib crypto so the bundle
  runs without `PyJWT` or `pwdlib`.*
- **FastAPI docs — Advanced Security: OAuth2 scopes.**
  https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/
  *`Security(get_current_user, scopes=[...])`, `SecurityScopes`, the
  `scope="read"` space-separated claim convention, and the 403-vs-401
  distinction. Quoted in §8.*
- **FastAPI Reference — Security Tools (`OAuth2PasswordBearer`,
  `SecurityScopes`).**
  https://fastapi.tiangolo.com/reference/security/
  *Confirms `OAuth2PasswordBearer` inherits from `OAuth2` → `SecurityBase`
  (which is why FastAPI auto-emits the OpenAPI security scheme), and the
  `SecurityScopes` dataclass shape.*
- **RFC 7519 — JSON Web Token (JWT).**
  https://datatracker.ietf.org/doc/html/rfc7519
  *§1 the "compact, URL-safe" goal; §3 the `header.payload.signature` shape;
  §4.1.2 `sub`; §4.1.4 `exp`; §4.1.6 `iat`. The base64url-not-encrypted
  warning is §7.2 ("Any party [...] can read the contents").*
- **RFC 7515 — JSON Web Signature (JWS).**
  https://datatracker.ietf.org/doc/html/rfc7515
  *§2 the base64url-no-padding encoding; §3 the JOSE header; the rule that
  the `alg` header MUST be on an allowlist. Cited in §3 against `alg:none`.*
- **RFC 6749 — The OAuth 2.0 Authorization Framework.**
  https://datatracker.ietf.org/doc/html/rfc6749
  *§3.3 the space-separated `scope` string; §4.3 the Resource Owner Password
  Credentials flow (POST username/password to /token).*
- **jwt.io — Introduction to JSON Web Tokens.**
  https://jwt.io/introduction/
  *Independent confirmation of the three-part structure, the
  `{"alg":"HS256","typ":"JWT"}` header, and the signature formula
  `HMACSHA256(base64UrlEncode(header) + "." + base64UrlEncode(payload),
  secret)`. The base64-not-encrypted warning and the
  `Authorization: Bearer <token>` header usage. Cited in §3.*
- **Python docs — `hashlib.pbkdf2_hmac`.**
  https://docs.python.org/3/library/hashlib.html#hashlib.pbkdf2_hmac
  *Signature `pbkdf2_hmac(hash_name, password, salt, iterations, dklen=None)`;
  the recommendation that salt be "16 or more bytes from a proper source
  (os.urandom)"; the "as of 2022, hundreds of thousands of iterations of
  SHA-256 are suggested" guidance; the reference to NIST-SP-800-132. Cited
  in §1.*
- **Python docs — `hmac.compare_digest`.**
  https://docs.python.org/3/library/hmac.html#hmac.compare_digest
  *The constant-time comparison function (a "candidate" and a "secret" of
  equal length) that closes the timing side-channel on hash verification.
  Cited in §1.*
- **NIST SP 800-132 — Recommendation for Password-Based Key Derivation.**
  https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication800-132.pdf
  *Appendix A.2.2 — how to choose iteration counts for PBKDF2; the rationale
  behind "hundreds of thousands of iterations". Referenced from the
  `pbkdf2_hmac` docstring and §1.*
