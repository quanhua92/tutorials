# AUTH_SESSIONS — Password Hashing (scrypt), JWTs (jose), Hardened Cookies & Sessions

> **Goal (one line):** show, by printing every behavior, how a Node/TS app
> stores passwords with a SLOW salted hash (`scrypt`), signs & verifies
> stateless JWTs (`jose`), backs them with hardened cookies, and falls back to
> stateful server sessions — pinning the 3 auth failure modes (wrong pw /
> tampered / expired) as `check()`'d invariants.
>
> **Run:** `just run auth_sessions`
>
> **Ground truth:** [`db/auth_sessions.ts`](./db/auth_sessions.ts) → captured
> stdout in
> [`db/auth_sessions_output.txt`](./db/auth_sessions_output.txt). Every token,
> hash hex, boolean, and error code below is pasted **verbatim** from that file
> under a `> From auth_sessions.ts Section X:` callout. Nothing is hand-computed.
>
> **Prerequisites:** 🔗 [`ERRORS_EXCEPTIONS`](./ERRORS_EXCEPTIONS.md) (jose
> `jwtVerify` throws typed subclasses — `JWTExpired`,
> `JWSSignatureVerificationFailed`, `JWTClaimValidationFailed` — that you
> `instanceof`-match, exactly the error-class pattern of P1), 🔗
> [`PROMISES`](./PROMISES.md) (`jose` is async — `sign()`/`jwtVerify()` return
> `Promise`s), and 🔗 [`COLLECTIONS_DEEP`](./COLLECTIONS_DEEP.md) (the
> stateful-session store is a `Map`).

---

## 1. Why this bundle exists (lineage)

HTTP is **stateless**: each request is independent, and the server has no
built-in memory of "who sent the previous one." So *authentication* — proving
*who* a request is from — must be **re-asserted on every request**. There are
two industry-standard ways to carry that assertion, plus one for *delegating*
the password check entirely:

1. **Stateless JWT** — the server signs a token (`header.payload.signature`)
   carrying the user's **claims** (sub, iss, exp, …). On every later request
   the server verifies the **signature** using only its secret — **no DB
   lookup**. Fast and horizontally scalable, but a minted token **cannot be
   revoked** before its `exp` without a server-side blocklist.
2. **Stateful session** — the server generates an **opaque random ID**, stores
   the session data keyed by that ID (in-memory `Map` here; Redis/DB in prod),
   and sends *only the ID* to the client in a hardened cookie. Every request
   does a **lookup** (the opposite of the JWT). Slower, but **instantly
   revocable** (delete the row).
3. **OAuth2 / OIDC** — delegate the password check to an **identity provider**
   (Google, GitHub, Auth0). Your server never sees that password; it trades an
   authorization code for provider-signed tokens (JWTs signed with an
   **asymmetric** key — RS256/ES256 — verified via JWKS).

All three sit on **one shared foundation**: the user's password is **never
stored in the clear** — only a **slow, salted hash** (`scrypt`/`bcrypt`/
`argon2`). This bundle wires all three end-to-end, **offline**, using
`node:crypto` (`scrypt` — built-in, no dep) and `jose` (JWT). It is the
cross-language analog of Go's `golang-jwt` + `bcrypt`.

```mermaid
graph TD
    U["user submits password"] --> H["scryptSync(password, salt, 64)<br/>SLOW + SALTED hash<br/>(NEVER plaintext, NEVER fast hash)"]
    H --> V{"timingSafeEqual<br/>(constant-time compare)"}
    V -->|"match"| ISSUE["issue assertion"]
    V -->|"no match"| F1["401 wrong password"]
    ISSUE --> JWT["STATELESS: sign JWT (jose)<br/>verify = signature only, NO lookup"]
    ISSUE --> SESS["STATEFUL: opaque cookie ID<br/>verify = server store LOOKUP"]
    JWT --> COOKIE["Set-Cookie hardened:<br/>HttpOnly + Secure + SameSite"]
    SESS --> COOKIE
    COOKIE --> REQ["later request carries it"]
    REQ --> VERIFY{"verify"}
    VERIFY -->|"sig ok + not expired"| OK["200 authenticated"]
    VERIFY -->|"tampered sig"| F2["401 JWSSignatureVerificationFailed"]
    VERIFY -->|"exp past"| F3["401 JWTExpired -> refresh flow"]
    style H fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style JWT fill:#e7f0ff,stroke:#3178c6
    style SESS fill:#fef9e7,stroke:#f1c40f
    style F1 fill:#fadbd8,stroke:#e74c3c
    style F2 fill:#fadbd8,stroke:#e74c3c
    style F3 fill:#fadbd8,stroke:#e74c3c
```

The headline contrast across the curriculum is the whole point:

> 🔗 [`../go/AUTH_SESSIONS_JWT.md`](../go/AUTH_SESSIONS_JWT.md) — Go solves the
> **same** three jobs with `golang.org/x/crypto/bcrypt` (hashing) +
> `golang-jwt/jwt/v5` (JWT) + `net/http` cookies. `bcrypt` is **CPU-hard** only;
> Node's `scrypt` (this bundle) is **memory-hard** (costlier to GPU/ASIC
> brute-force). `argon2id` is the current OWASP top pick but needs a native dep
> in Node. The JWT model is identical; only the libraries differ.
>
> 🔗 [`../python/`](../python/) — Python's FastAPI uses
> `OAuth2PasswordBearer` + `passlib[bcrypt]` for the **identical** flow. The
> `Depends(...)` injection of the current user is Python's analog of an Express
> middleware that stashes the verified principal on `req.user`.

---

## 2. The mental model: stateless (JWT) vs stateful (session)

The single diagram that separates juniors from experts is the
**where-does-the-state-live** question. In a JWT, the state (the claims)
**travels with the token**; the server is stateless. In a session, the state
**lives on the server**; the cookie is just an opaque key.

```mermaid
graph LR
    subgraph STATELESS["STATELESS — JWT"]
        direction LR
        C1["client holds JWT<br/>(claims inside)"] -->|"sends JWT"| S1["server: verify SIGNATURE only<br/>(HMAC re-derive, NO lookup)"]
    end
    subgraph STATEFUL["STATEFUL — session"]
        direction LR
        C2["client holds opaque ID<br/>( meaningless string )"] -->|"sends cookie"| S2["server: LOOKUP store[id]<br/>-> session data"]
    end
    S1 -.->|"CANNOT revoke before exp<br/>(needs blocklist)"| TR1["tradeoff"]
    S2 -.->|"delete row = instant revoke"| TR2["tradeoff"]
    style STATELESS fill:#e7f0ff,stroke:#3178c6
    style STATEFUL fill:#fef9e7,stroke:#f1c40f
    style TR1 fill:#fadbd8,stroke:#e74c3c
    style TR2 fill:#eafaf1,stroke:#27ae60
```

**The password-storage invariant is independent of which model you pick.**
Whether you issue a JWT or a session cookie, the user's password at *login* is
checked against a **slow salted hash**, never plaintext, never a fast hash.
Section A pins that; Sections B–E build on top.

---

## 3. Section A — Password hashing: `scrypt` + FIXED salt + `timingSafeEqual`

`scryptSync(password, salt, keylen)` is a **key derivation function**: it is
intentionally **slow** (≈100 ms at Node's default `N=16384, r=8, p=1`) and
**memory-hard**, so brute-forcing a stolen hash is economically infeasible. It
is deterministic given `(password, salt, keylen, N, r, p)`. The bundle uses a
**FIXED 16-byte salt** so the derived key is byte-identical across runs; **real
code uses `randomBytes(16)` per user** (printed length only here, never the
value, to keep `_output.txt` stable).

> From `OWASP Password Storage Cheat Sheet` (verbatim): *"Passwords should never
> be stored in plain text. Instead, they must be protected using strong, slow
> hashing algorithms such as Argon2id, bcrypt, or PBKDF2."* Raw/fast hashes
> (MD5, SHA-256, SHA-512) are explicitly **forbidden** for passwords — they are
> too fast, making rainbow-table and GPU brute-force attacks trivial.

> From auth_sessions.ts Section A:
> ```
> scrypt('hunter2', FIXED_SALT, 64) ->
>   stored length : 80 bytes  (16 salt + 64 hash)
>   salt (hex)    : 0123456789abcdef0123456789abcdef
>   hash (hex)    : e9374ba623f86ce9282d8973e008d359cb75adb23526506ba3083306fb93c2e2337064868158822c122943224b937bbe184d07cfa89f87726b168feb893d257e
> [check] scrypt is deterministic: same pw+salt -> same 80-byte stored hash: OK
> 
> scrypt('hunter3', same salt) -> different hash
>   hash (hex)    : 37ebfd201ed71478d6c3fb7ac1368aa61ff661161d769832ce9abaa9f6d4a1fc0491ce6f9f989cea67e5fce7a88119da24a566c99562073c9a24f492d319451d
> [check] different password -> different hash: OK
> 
> verifyPassword results:
>   verify('hunter2')        -> true
>   verify('wrong-password') -> false
> [check] correct password verifies: OK
> [check] wrong password fails (no match): OK
> [check] timingSafeEqual is used (constant-time, equal-length only): OK
> [check] real salt via randomBytes(16) is 16 bytes: OK
>   (real code: randomBytes(16) salt per user; demo uses FIXED salt for determinism)
> ```

**The storage layout: `salt || hash`.** The bundle stores the 16-byte salt
**prepended** to the 64-byte derived key as a single 80-byte `Buffer`. To verify
a login, it slices off the first 16 bytes (the salt), re-derives
`scryptSync(candidate, salt, 64)`, and compares. This layout means the salt is
**not secret** (it just defeats precomputed rainbow tables) and you never need a
separate salt column.

**Why `timingSafeEqual`, not `===`.** A naive `===` compare on `Buffer`s
short-circuits on the first mismatched byte — an attacker measuring response
time can leak **how many leading bytes matched**, dramatically shrinking the
search space. `crypto.timingSafeEqual(a, b)` runs in time **independent of the
data** (constant time). Caveat: it **throws** if `a.length !== b.length`, so the
two operands must be the same length (both 64 bytes here — verified by the
`[check]` above).

**The payoff.** Note the second hash: `scrypt('hunter3', same salt)` produces a
*completely different* 64-byte hash — this is the **avalanche** property of a
cryptographic KDF. And `verify('wrong-password')` returns `false` **only after**
paying the full scrypt cost (≈100 ms), which is *the* defense against online
guessing: an attacker can try maybe ~10 passwords/second per core, not millions.

> 🔗 [`../go/AUTH_SESSIONS_JWT.md`](../go/AUTH_SESSIONS_JWT.md) §3 — Go's
> `bcrypt.CompareHashAndPassword` does the **same** constant-time compare
> internally; you never call `==` on a bcrypt hash either. The `bcrypt` cost
> factor is the analog of scrypt's `N` parameter.

---

## 4. Section B — JWT sign & verify: claims, 3-part structure, decode

A JWT (RFC 7519) is three base64url-encoded parts joined by `.`:
`header.payload.signature`.

- **header** — the JWS protected header (`{"alg":"HS256"}`).
- **payload** — the **Claims Set**: the *registered* claims (`iss`, `sub`,
  `aud`, `exp`, `nbf`, `iat`, `jti`) plus any *custom* claims (here `role`).
- **signature** — `HMAC-SHA256(base64url(header) + "." + base64url(payload), secret)`.

> From `RFC 7519` §4 (registered claims, summarized): `iss` (Issuer, §4.1.1),
> `sub` (Subject, §4.1.2), `aud` (Audience, §4.1.3), `exp` (Expiration Time,
> §4.1.4), `nbf` (Not Before, §4.1.5), `iat` (Issued At, §4.1.6), `jti` (JWT ID,
> §4.1.7). A JWT with `exp` set "MUST NOT be accepted for processing" after the
> expiry; `nbf` similarly gates "before which the JWT MUST NOT be accepted."

`jose`'s `SignJWT` builder sets these fluently. The bundle **pins `iat` and
`exp` to fixed unix timestamps** (via `setIssuedAt(FIXED)` /
`setExpirationTime(FIXED-number)`), and pins the secret + claims, so the
**token string itself is byte-identical** across runs — the strongest possible
determinism proof:

> From auth_sessions.ts Section B:
> ```
> signed JWT (HS256, iss=tutorials-app, sub=user-1, role=admin):
>   eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYWRtaW4iLCJpc3MiOiJ0dXRvcmlhbHMtYXBwIiwic3ViIjoidXNlci0xIiwiaWF0IjoxNzAwMDAwMDAwLCJleHAiOjk5OTk5OTk5OTl9.6Ga9tdEIAtW6adahKIawFf6_iMll8Orn43IbULoP-4c
> 
> structure: header.payload.signature  (3 base64url parts, 2 dots)
>   parts.length === 3
> [check] JWT has exactly 3 dot-separated parts: OK
> 
> decoded header (decodeProtectedHeader, NO signature check):
>   alg = HS256
> 
> decoded payload (decodeJwt, NO signature check):
>   iss = tutorials-app
>   sub = user-1
>   role = admin
>   iat = 1700000000   (pinned -> deterministic token)
>   exp = 9999999999
> [check] decoded header alg === "HS256": OK
> [check] decoded claim iss === "tutorials-app": OK
> [check] decoded claim sub === "user-1": OK
> [check] decoded custom claim role === "admin": OK
> [check] decoded claim iat === FIXED_IAT (pinned): OK
> [check] decoded claim exp === FIXED_EXP_VALID (pinned): OK
> 
> jwtVerify(token, SECRET, {issuer}) -> TRUSTED payload:
>   sub = user-1
>   role = admin
> [check] verified token sub === user-1: OK
> [check] verified token role === admin: OK
> [check] JWT is deterministic: pinned secret+claims+iat -> same string: OK
> ```

**Decode vs verify — do not confuse them.** `jose.decodeJwt(token)` and
`decodeProtectedHeader(token)` parse the base64url and hand you the claims **with
no signature check whatsoever**. Anyone can craft a token whose *decoded*
payload says `role: "admin"`. **`jwtVerify(token, secret, {issuer})` is the
authoritative operation**: it re-derives the HMAC and constant-time-compares it,
*then* validates the registered claims (`iss`, `exp`, …). Only trust claims that
came back from `jwtVerify`. This is the #1 JWT footgun (see pitfalls).

**Why `HS256` here, and what changes for a provider.** HS256 is **symmetric**:
the same `SECRET` signs and verifies. That works for a single trusted server.
OAuth2/OIDC providers (Section E) sign with an **asymmetric** key (RS256/ES256):
a private key signs, the **public** key verifies — so any client can verify a
provider's token without the provider disclosing its signing key.

> 🔗 [`JSON`](./JSON.md) — a JWT payload *is* JSON (the base64url decodes to a
> UTF-8 JSON object). The custom-claim indexing (`payload.role`) is plain object
> access on the parsed JSON.
> 🔗 [`ERRORS_EXCEPTIONS`](./ERRORS_EXCEPTIONS.md) P1 — `jose`'s typed error
> class hierarchy (`JOSEError` → `JWTExpired` / `JWSSignatureVerificationFailed`
> / …) is the textbook example of error-class-based dispatch.

---

## 5. Section C — JWT failure modes + the stateless tradeoff

`jwtVerify` throws a **specific** `jose` error subclass for each failure. The
bundle exercises all three failure modes — each maps to an **HTTP 401** — plus
the refresh-token flow that recovers from an expired access token.

> From auth_sessions.ts Section C:
> ```
> FAILURE 1 — tampered signature:
>   tampered token : eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYWRtaW4iLCJpc3MiOiJ0dXRvcmlhbHMtYXBwIiwic3ViIjoidXNlci0xIiwiaWF0IjoxNzAwMDAwMDAwLCJleHAiOjk5OTk5OTk5OTl9.6Ga9tdEIAtW6adahKIawFf6_iMll8Orn43IbULoAAAA
>   -> threw JWSSignatureVerificationFailed (code: ERR_JWS_SIGNATURE_VERIFICATION_FAILED)
> [check] tampered token throws JWSSignatureVerificationFailed: OK
> [check] tampered token -> HTTP 401 (signature invalid): OK
> 
> FAILURE 2 — expired token (exp pinned to the past):
>   expired token  : eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYWRtaW4iLCJpc3MiOiJ0dXRvcmlhbHMtYXBwIiwic3ViIjoidXNlci0xIiwiaWF0IjoxNzAwMDAwMDAwLCJleHAiOjE3MDAwMDAwMDF9.YQWDP7-Rw4Oj6vJtdk-mAcPKhwKkHGrkz-KDeA3BwVs
>   -> threw JWTExpired (code: ERR_JWT_EXPIRED)
> [check] expired token throws JWTExpired: OK
> [check] expired token -> HTTP 401 (trigger refresh flow): OK
> 
> FAILURE 3 — wrong issuer (signature valid, claim mismatch):
>   token (iss=some-other-app) : eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYWRtaW4iLCJpc3MiOiJzb21lLW90aGVyLWFwcCIsInN1YiI6InVzZXItMSIsImlhdCI6MTcwMDAwMDAwMCwiZXhwIjo5OTk5OTk5OTk5fQ.skbbxAatP5OoqcPLwqRfEO3N8FvcCVl1r5CCPXF3lM0
>   -> threw JWTClaimValidationFailed (code: ERR_JWT_CLAIM_VALIDATION_FAILED)
> [check] wrong-issuer token throws JWTClaimValidationFailed: OK
> [check] wrong-issuer token -> HTTP 401: OK
> 
> STATELESS TRADEOFF:
>   verify(token) needs ONLY the HMAC secret — no DB/store lookup.
>   => fast, scales horizontally. BUT: cannot revoke a minted token
>      before its exp without a server-side denylist (blocklist).
> 
> REFRESH-TOKEN FLOW (access + refresh):
>   access token  : eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYWRtaW4iLCJ0eXAiOiJhY2Nlc3MiLCJpc3MiOiJ0dXRvcmlhbHMtYXBwIiwic3ViIjoidXNlci0xIiwiaWF0IjoxNzAwMDAwMDAwLCJleHAiOjk5OTk5OTk5OTl9.xQ8tZx7xbDflXzU6rsSXK_yoNAeaLRqEd4XnJL2HBLo
>   refresh token : eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoiYWRtaW4iLCJ0eXAiOiJyZWZyZXNoIiwiaXNzIjoidHV0b3JpYWxzLWFwcCIsInN1YiI6InVzZXItMSIsImlhdCI6MTcwMDAwMDAwMCwiZXhwIjo5OTk5OTk5OTk5OX0.qnlou4BYGWjVH_CL9NpSqWN4yehHkZCF-VaCgCI8yM8
>   access.typ=access  refresh.typ=refresh
> [check] access token has typ=access: OK
> [check] refresh token has typ=refresh (longer-lived): OK
> [check] refresh token exp >= access token exp: OK
> [check] jose error subclasses extend JOSEError (typed, .code present): OK
> ```

**The three error classes (and their `.code`s), pinned.** Each subclass extends
`jose.errors.JOSEError` and carries a stable `code` string you can branch on:

| Failure | jose class | `.code` | HTTP |
|---|---|---|---|
| bad signature / tampered payload | `JWSSignatureVerificationFailed` | `ERR_JWS_SIGNATURE_VERIFICATION_FAILED` | 401 |
| `exp` in the past | `JWTExpired` | `ERR_JWT_EXPIRED` | 401 |
| wrong `iss`/`aud` | `JWTClaimValidationFailed` | `ERR_JWT_CLAIM_VALIDATION_FAILED` | 401 |

**Failure 1 (tampered)** is the signature defense doing its job: the attacker
flipped 4 bytes of the signature, so the recomputed HMAC no longer matches —
`jwtVerify` throws *before* it even looks at the claims. **Failure 2
(expired)** is the signature **valid** but `exp` (pinned to `1700000001`, a
second after `iat`, clearly in the past) has elapsed. **Failure 3 (wrong
issuer)** is subtle: the signature is **valid** (the attacker used the *real*
secret — e.g. a leaked key, or a token minted for a *different* app), but the
`iss` claim does not match the verifier's expectation, so claim validation
rejects it. This is why you should **always pass `{ issuer, audience }`** to
`jwtVerify`.

**The stateless tradeoff, concretely.** Because `verify` needs only the secret,
a token that has been minted is **good until its `exp`** no matter what the
server does afterwards. If a user logs out, changes their password, or is banned,
their existing JWT still works. The mitigations are: (a) keep `exp` **short**
(minutes, not days), (b) issue a **refresh token** (longer-lived, presented to a
`/refresh` endpoint that re-checks the user's status before minting a new access
token), and/or (c) maintain a server-side **blocklist** of revoked `jti`s (which
re-introduces a lookup — eroding the stateless benefit).

**The refresh-token flow (printed above).** The bundle mints two JWTs: an
**access token** (short `exp`, `typ: "access"`) and a **refresh token**
(longer `exp`, `typ: "refresh"`). When the access token expires (Failure 2),
the client sends the refresh token to `/refresh`; the server verifies it and
mints a fresh access token — **without re-entering the password**. The `[check]`
proves the refresh token's `exp` is ≥ the access token's `exp`.

> 🔗 [`ERRORS_EXCEPTIONS`](./ERRORS_EXCEPTIONS.md) — `catch (err) { if (err
> instanceof joseErrors.JWTExpired) … }` is the canonical **typed error
> dispatch**. The `.code` string is the secondary, instance-of-independent way
> to branch (useful when errors cross a serialization boundary).

---

## 6. Section D — Stateful sessions: opaque cookie ID → server store + cookie flags

The **stateful** model is the dual of the JWT: the client holds an **opaque,
meaningless** ID; the session *data* lives on the server. Verifying a request
means a **lookup** (here an in-memory `Map`; production uses Redis or a DB).
Because the data is server-side, **deleting the row instantly revokes the
session** — the client's cookie becomes a dead string. (The price: every request
costs a round-trip to the store.)

> From auth_sessions.ts Section D:
> ```
> STATEFUL session store (Map: opaqueId -> Session):
>   set('sess_4f8a7c2b9e1d6053a0cb2def78193456', {userId, role, createdAt})
>   get('sess_4f8a7c2b9e1d6053a0cb2def78193456') -> userId=user-1, role=admin
> [check] session set -> get returns the stored userId: OK
> [check] session set -> get returns the stored role: OK
> [check] stateful session is revocable: delete -> get returns undefined: OK
> 
> production session id via randomBytes(32).toString('hex'):
>   id length = 69  (prefix 'sess_' + 64 hex chars)
> [check] production session id is 'sess_' + 64 hex chars: OK
> [check] production session id is hex after prefix: OK
> 
> Set-Cookie header (hardened):
>   session=sess_4f8a7c2b9e1d6053a0cb2def78193456; Path=/; Max-Age=3600; HttpOnly; Secure; SameSite=Strict
> [check] Set-Cookie has HttpOnly (blocks XSS document.cookie theft): OK
> [check] Set-Cookie has Secure (HTTPS only): OK
> [check] Set-Cookie has SameSite=Strict (blocks CSRF): OK
> [check] Set-Cookie has Path=/: OK
> [check] Set-Cookie carries the opaque session value: OK
> ```

**Why the ID is opaque and random.** The session ID is a **capability**: whoever
holds it can act as that user. So it must be **unguessable** — `randomBytes(32)`
(256 bits of entropy, 64 hex chars). The bundle exercises the real `randomBytes`
API but asserts only its **length/charset** (deterministic), never the value;
the set/get flow uses a **FIXED** ID so `_output.txt` is stable. (Contrast: a
JWT is *not* opaque — its claims are readable by anyone who holds it, which is
fine because its integrity is guaranteed by the signature.)

**Cookie flags — each closes one attack:**

```mermaid
graph TD
    CK["Set-Cookie: session=..."] --> HT["HttpOnly<br/>JS cannot read document.cookie"]
    CK --> SC["Secure<br/>sent only over HTTPS"]
    CK --> SS["SameSite=Strict | Lax | None"]
    HT -->|"stops"| XSS["XSS cookie theft<br/>(stealing session via injected script)"]
    SC -->|"stops"| SNIFF["wire sniffing<br/>(cookie read off plain HTTP)"]
    SS -->|"stops"| CSRF["CSRF<br/>(cross-site forged request)"]
    SS --> S1["Strict: never send cross-site<br/>(even on top-level link click)"]
    SS --> S2["Lax: send on top-level GET nav<br/>(browser DEFAULT in modern engines)"]
    SS --> S3["None: always send<br/>(REQUIRES Secure)"]
    style XSS fill:#fadbd8,stroke:#e74c3c
    style SNIFF fill:#fadbd8,stroke:#e74c3c
    style CSRF fill:#fadbd8,stroke:#e74c3c
    style HT fill:#eafaf1,stroke:#27ae60
    style SC fill:#eafaf1,stroke:#27ae60
    style SS fill:#eafaf1,stroke:#27ae60
```

> From `MDN — Set-Cookie` (verified): **`HttpOnly`** forbids JavaScript access
> via `document.cookie` (only sent on HTTP requests) — *"HttpOnly cookies are
> inaccessible to JavaScript's `Document.cookie` API; they're only sent to the
> server"*; **`Secure`** restricts the cookie to **HTTPS**; **`SameSite`**
> (`Strict`/`Lax`/`None`) controls cross-site sending — *"`SameSite=Lax` is the
> new default if `SameSite` isn't specified"* and *"cookies with `SameSite=None`
> must now also specify the `Secure` attribute."*

> 🔗 [`COLLECTIONS_DEEP`](./COLLECTIONS_DEEP.md) — the session store here is a
> `Map`, which preserves insertion order and uses **SameValueZero** key equality.
> Redis is the production analog (with TTL-based expiry that `Map` lacks — you'd
> pair it with a `setTimeout` sweeper or a periodic cleanup).

---

## 7. Section E — OAuth2/OIDC (documented) + the 3 failure modes + cross-language

**OAuth2 / OpenID Connect** is the third model: **delegate** the password check
to an **identity provider**. The canonical **Authorization Code flow** has six
steps; OIDC layers an **ID token** (a provider-signed JWT with user claims) on
top of OAuth2's access tokens. The bundle documents the flow (it requires a live
provider, so it is not executed) and contrasts the **asymmetric** signing
(`RS256`/`ES256` — verify with the provider's public key via **JWKS**) against
this bundle's symmetric `HS256`.

> From auth_sessions.ts Section E:
> ```
> OAuth2/OIDC Authorization Code flow (documented — not executed):
>   1. client -> redirect to provider /authorize?client_id=...&redirect_uri=...
>   2. user authenticates AT the provider (you never see the password)
>   3. provider redirects to your /callback?code=XYZ
>   4. server POSTs code+client_secret to provider /token -> access+id tokens
>   5. server verifies provider-signed ID token (JWT, RS256, via JWKS)
>   6. server mints its OWN session/JWT from the verified identity
>   KEY DIFF: provider signs with an ASYMMETRIC key (RS256/ES256); you
>   verify with the public key. This bundle uses SYMMETRIC HS256.
> [check] OAuth2 model documented (provider authenticates, not your server): OK
> 
> The 3 auth failure modes (all -> HTTP 401):
>   1. wrong password  -> scrypt compare fails            (Section A)
>   2. tampered token  -> HMAC signature verify fails     (Section C F1)
>   3. expired token   -> exp in the past -> refresh flow (Section C F2)
> [check] the 3 auth failure modes are documented (all 401): OK
> 
> CROSS-LANGUAGE (same models, different libraries):
>   Go     : golang-jwt/jwt/v5 + golang.org/x/crypto/bcrypt
>   Python : FastAPI OAuth2PasswordBearer + passlib[bcrypt]
>   Node   : jose + node:crypto scrypt  (THIS bundle)
>   bcrypt vs scrypt: both slow + salted; scrypt is MEMORY-HARD.
>   argon2 (PHC winner) is the current pick but needs a native dep in Node.
> [check] cross-language parallels documented (Go/Python/Node): OK
> 
> PRIMITIVE -> JOB map (the whole bundle in one table):
>   scrypt (slow+salted hash)   : store passwords safely (never plaintext)
>   timingSafeEqual             : constant-time hash compare (no timing leak)
>   jose SignJWT / jwtVerify    : stateless signed assertions (no DB lookup)
>   opaque cookie ID + store    : stateful revocable sessions (DB lookup)
>   HttpOnly/Secure/SameSite    : harden the cookie (XSS/sniff/CSRF)
>   OAuth2/OIDC code flow       : delegate auth to a provider (no pw stored)
> [check] primitive->job map documented: OK
> ```

**The 3 failure modes, unified.** Whether you use JWTs, sessions, or OAuth2,
every auth system answers "who is this?" with one of three 401 failures:
**wrong password** (Section A), **tampered token** (Section C F1), or **expired
token** (Section C F2). The primitives differ; the failure taxonomy does not.

**Why `alg: none` and algorithm confusion are the #1 JWT vuln.** A classic
attack: send a token with `alg: "none"` (no signature) and hope the verifier
accepts it. `jose` **rejects `none` by default** and lets you pin an
`algorithms: ["HS256"]` allowlist on `jwtVerify` — **always pass it** when
verifying tokens signed by others, to defeat algorithm-confusion attacks (e.g. a
public RS256 key being mis-used as an HS256 secret).

> 🔗 [`REST_API`](./REST_API.md) P8 — the **auth middleware** that gates a route
> is where this bundle's primitives plug in: extract the `Authorization: Bearer
> <jwt>` header (or the session cookie), call `verifyJwt`, and either attach
> `req.user = payload` or return 401. That middleware is the seam between auth
> (this bundle) and routing.
> 🔗 [`../go/AUTH_SESSIONS_JWT.md`](../go/AUTH_SESSIONS_JWT.md) — Go's
> `jwt.Parse` with `ValidMethods: []string{"HS256"}` is the exact analog of
> jose's `algorithms` allowlist; Go's `bcrypt.GenerateFromPassword` is the
> analog of `scryptSync`. Same model, different KDF.

---

## 8. Pitfalls (the expert payoff)

| Trap | Symptom | Fix |
|---|---|---|
| Storing passwords as plaintext (or a fast hash: MD5/SHA-256) | DB leak = instant mass account takeover; fast hashes brute-force at billions/sec | Use a **slow salted KDF**: `scryptSync` / `bcrypt` / `argon2id`. OWASP mandates this. Never raw `crypto.createHash`. |
| Comparing hashes with `===` / `Buffer.equals` in a timing-sensitive path | response-time side-channel leaks how many leading bytes matched, shrinking brute-force | Use **`timingSafeEqual(a, b)`** for the compare; both buffers must be equal length. |
| Trusting claims from `decodeJwt` | `decodeJwt` does **no** signature check — an attacker crafts `{"role":"admin"}` and you believe it | Only trust claims returned by **`jwtVerify`** (signature verified). `decodeJwt` is a preview-only/debug helper. |
| Not passing `{ issuer, audience }` (and `algorithms`) to `jwtVerify` | wrong-issuer / wrong-audience / alg-confusion tokens slip through | Always pass the expected `issuer`, `audience`, **and** `algorithms: [...]` allowlist. |
| Accepting `alg: "none"` | unauthenticated tokens honored | Pin `algorithms: ["HS256"]` (or your real alg). `jose` rejects `none` by default but be explicit. |
| Minting a JWT that never expires (`exp` absent or years out) | a leaked/stolen token is valid forever; no logout possible server-side | Set a **short** `exp` (minutes); use a refresh token for longevity. |
| Assuming logout revokes a JWT | the stateless token still verifies until `exp` | Use short `exp` + refresh flow, OR a server-side `jti` blocklist (re-introduces a lookup). |
| Reusing the session cookie ID as the JWT `jti` (or vice-versa) | cross-purpose capability leakage | Keep them separate namespaces; `jti` is a token ID, the session ID is a store key. |
| Missing `HttpOnly` on the session/JWT cookie | XSS reads `document.cookie` and exfiltrates the token | Set `HttpOnly` on **every** auth cookie. |
| Missing `Secure` (cookie sent over plain HTTP) | MITM reads the cookie off the wire | Set `Secure`; enforce HTTPS (HSTS) in production. |
| `SameSite=None` without `Secure` | rejected by modern browsers; or CSRF if `None` and not required | Default to `SameSite=Lax` (browser default) or `Strict`; use `None` only when cross-site sending is genuinely needed (with `Secure`). |
| `timingSafeEqual` on unequal-length buffers | throws `RangeError` → 500 instead of a clean 401 | Ensure both operands are the key length (slice the stored hash to match); guard length first. |
| Putting the JWT in `localStorage` instead of a cookie | XSS steals it from `localStorage` (no `HttpOnly` equivalent) | Store the JWT in an `HttpOnly` cookie (CSRF-protected via `SameSite`), or use a session cookie. |
| Generating session IDs with `Math.random()` | predictable IDs → session hijacking | Use **`crypto.randomBytes(32)`** (CSPRNG). `Math.random` is **not** cryptographically secure. |
| Treating `iat` as authoritative clock skew | `iat` is informational, not validated against "now" by default | Rely on `exp`/`nbf` + `clockTolerance` for time-based decisions; `iat` is for age auditing. |

---

## 9. Cheat sheet

```typescript
// === Password hashing (node:crypto scrypt — SLOW + SALTED) =================
//   NEVER plaintext. NEVER a fast hash (MD5/SHA-256). Always scrypt/bcrypt/argon2id.
import { scryptSync, timingSafeEqual, randomBytes } from "node:crypto";

const salt = randomBytes(16);                       // unique per user (demo: FIXED)
const stored = Buffer.concat([salt, scryptSync(password, salt, 64)]); // salt || hash (80 bytes)

function verify(candidate: string, stored: Buffer): boolean {
  const salt = stored.subarray(0, 16);
  const expected = stored.subarray(16);
  const got = scryptSync(candidate, salt, 64);
  return timingSafeEqual(got, expected);            // CONSTANT-TIME (throws if len !=)
}
//   scrypt is ~100ms at default N — that slowness IS the defense vs online guessing.

// === JWT sign/verify (jose — stateless signed assertions) ==================
import { SignJWT, jwtVerify, errors as joseErrors } from "jose";
import type { JWTPayload } from "jose";

const secret = new TextEncoder().encode(">=32-byte-hs256-secret");
const token: string = await new SignJWT({ role: "admin" })   // custom claims
  .setProtectedHeader({ alg: "HS256" })
  .setIssuer("app")          // iss  (RFC7519 §4.1.1)
  .setSubject("user-1")      // sub  (§4.1.2)
  .setAudience("app-api")    // aud  (§4.1.3)
  .setIssuedAt()             // iat  (§4.1.6) — pass a NUMBER to PIN for determinism
  .setExpirationTime("15m")  // exp  (§4.1.4) — pass a NUMBER to PIN
  .sign(secret);             // -> "header.payload.signature" (3 base64url parts)

const { payload } = await jwtVerify(token, secret, {
  issuer: "app", audience: "app-api", algorithms: ["HS256"],  // ALWAYS pin these
});
//   decodeJwt(token) does NOT verify the signature — preview only. Trust jwtVerify.

//   Failure -> typed throws (all extend joseErrors.JOSEError, all have .code):
//     JWSSignatureVerificationFailed  ERR_JWS_SIGNATURE_VERIFICATION_FAILED (tampered)
//     JWTExpired                      ERR_JWT_EXPIRED                       (exp past)
//     JWTClaimValidationFailed        ERR_JWT_CLAIM_VALIDATION_FAILED       (iss/aud)

// === Stateless vs stateful =================================================
//   STATELESS (JWT):     state travels in the token; verify = signature only (NO lookup).
//                         cannot revoke before exp (needs a blocklist) — keep exp SHORT.
//   STATEFUL (session):  state lives server-side; cookie is an OPAQUE random ID; lookup per request.
//                         delete the row = instant revoke. Store = Map / Redis / DB.

// === Cookie flags (each closes one attack) =================================
//   HttpOnly          : blocks XSS (document.cookie) theft   — always set on auth cookies
//   Secure            : HTTPS only                           — blocks wire sniffing
//   SameSite=Strict   : never cross-site                     — strongest CSRF defense
//   SameSite=Lax      : top-level GET nav only               — browser DEFAULT
//   SameSite=None     : always (REQUIRES Secure)             — only when cross-site needed

// === OAuth2/OIDC code flow (delegate the password check) ===================
//   redirect -> provider /authorize -> user logs in AT provider -> /callback?code=
//   -> POST code to /token -> verify provider-signed ID token (RS256 via JWKS)
//   -> mint YOUR OWN session/JWT. Provider key is ASYMMETRIC (vs your HS256).
```

---

## Sources

Every signature, claim name, error code, and behavioral assertion above was
verified against the upstream `jose` type definitions, the Node.js docs, RFC
7519, the OWASP cheat sheet, and MDN — then **corroborated by at least one
independent secondary source**. Every JWT result, hash, and error code is
*additionally* asserted at runtime by the `.ts` itself (`check()` throws on any
mismatch) — the strongest possible verification: Node V8 + OpenSSL's actual
verdict. The captured `db/auth_sessions_output.txt` is **byte-identical across
re-runs** (FIXED salt + FIXED secret + PINNED `iat`/`exp`).

- **`jose` (v5.10.0, installed in `db/`)** — JWT sign/verify/decode + typed
  error hierarchy. Type definitions verified at
  `db/node_modules/jose/dist/types/` (`jwt/sign.d.ts`, `jwt/produce.d.ts`,
  `jwt/verify.d.ts`, `util/errors.d.ts`, `util/decode_jwt.d.ts`):
  https://github.com/panva/jose
  - `SignJWT` builder: `setProtectedHeader({alg})`, `setIssuer`,
    `setSubject`, `setAudience`, `setIssuedAt(input?)`, `setExpirationTime(input)`,
    `sign(key)` — the `number` form of `setIssuedAt`/`setExpirationTime` is
    *"used as the claim directly"* (verbatim from `produce.d.ts`), which is how
    this bundle pins `iat`/`exp` for determinism.
  - `jwtVerify(token, key, {issuer, audience, algorithms})` returns
    `{payload, protectedHeader}` and throws typed subclasses.
  - Error classes & codes (verified by `node -e` at build time):
    `JWTExpired` → `ERR_JWT_EXPIRED`; `JWSSignatureVerificationFailed` →
    `ERR_JWS_SIGNATURE_VERIFICATION_FAILED`; `JWTClaimValidationFailed` →
    `ERR_JWT_CLAIM_VALIDATION_FAILED`; all extend `JOSEError`.
- **Node.js — `node:crypto`**: `scryptSync(password, salt, keylen[, options])`,
  `timingSafeEqual(a, b)`, `randomBytes(size)`:
  https://nodejs.org/api/crypto.html#cryptoscryptsyncpassword-salt-keylen-options
  - `timingSafeEqual`: *"should not be called with buffers of different lengths"*
    (throws) — why the bundle slices the stored hash to match the candidate.
- **OWASP — Password Storage Cheat Sheet** (the foundational rule — *"Passwords
  should never be stored in plain text. Instead, they must be protected using
  strong, slow hashing algorithms such as Argon2id, bcrypt, or PBKDF2"*; raw
 /fast hashes forbidden; per-user random salt; key-stretching / peppering):
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
- **RFC 7519 — JSON Web Token (JWT)** (the three-part structure; the seven
  registered claims `iss`/`sub`/`aud`/`exp`/`nbf`/`iat`/`jti` §4.1.1–4.1.7; *"a
  JWT with exp set MUST NOT be accepted for processing"* after expiry; *"nbf …
  the time before which the JWT MUST NOT be accepted"*):
  https://datatracker.ietf.org/doc/html/rfc7519
  - IANA JWT registry (registered-claim names registry):
    https://www.iana.org/assignments/jwt
- **MDN — `Set-Cookie` header** (`HttpOnly`, `Secure`, `SameSite=Strict|Lax|None`,
  `Max-Age`, `Path`; *"HttpOnly cookies are inaccessible to JavaScript's
  `Document.cookie` API"*; *"SameSite=Lax is the new default"*; *"SameSite=None
  must also specify Secure"*):
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie
- **MDN — Using HTTP cookies** (security implications; SameSite/CSRF; why
  `HttpOnly`+`Secure` are the baseline for auth cookies):
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies
- **OWASP / Auth0 — salt + slow hashing rationale** (why a unique random salt
  defeats rainbow tables; why slowness matters):
  https://auth0.com/blog/adding-salt-to-hashing-a-better-way-to-store-passwords/

**Secondary corroboration (independent of OWASP/RFC, ≥1 per major claim):**
- web.dev — *"SameSite cookies explained"* (`Lax` default, `None` requires
  `Secure`, the CSRF rationale):
  https://web.dev/articles/samesite-cookies-explained
- Auth0 Docs — *"JSON Web Token claims"* (`iss`/`sub`/`aud`/`exp`/`iat`/`nbf`
  plain-English summary corroborating RFC 7519):
  https://auth0.com/docs/secure/tokens/json-web-tokens/json-web-token-claims
- Deepak Gupta — *"The Complete Guide to Password Hashing"* (Argon2 vs bcrypt
  vs scrypt tradeoffs; why algorithms must be *"intentionally slow"* + *"unique,
  randomly generated salt"*, corroborating OWASP):
  https://guptadeepak.com/research/password-hashing-guide-2026/

**Facts that could not be verified by running this bundle** (documented, not
executed, because they require a live third-party identity provider or a network
redirect): the OAuth2/OIDC Authorization Code flow (steps 1–6 in Section E) and
the RS256/JWKS asymmetric verification path. These are confirmed by the RFC 7519
registered-claim set, the OWASP cheat sheet, and the `jose` type definitions
(which expose `createRemoteJWKSet` for exactly this flow), corroborated by the
Auth0 and web.dev sources above — not reproduced as runnable output, since a
file that required a live provider would not pass `just check`. No claim in a
runtime callout above is unverified.
