# AUTH_SESSIONS_JWT — Password Hashing (bcrypt), JWTs, Hardened Cookies & Auth Middleware

> **Goal (one line):** show, by printing every behavior, how Go stores passwords
> safely with bcrypt, signs/verifies JWTs (and defeats the alg-confusion attack),
> hardens session cookies, and guards an HTTP route with Bearer-token middleware.
>
> **Run:** `go run auth_sessions_jwt.go`
>
> **Ground truth:** [`auth_sessions_jwt.go`](./auth_sessions_jwt.go) → captured
> stdout in [`auth_sessions_jwt_output.txt`](./auth_sessions_jwt_output.txt).
> Every token, status code, and boolean below is pasted **verbatim** from that
> file under a `> From auth_sessions_jwt.go Section X:` callout. Nothing is
> hand-computed.
>
> **Prerequisites:** 🔗 [`NET_HTTP`](./NET_HTTP.md) (the server, `http.Cookie`,
> `httptest`), 🔗 [`MIDDLEWARE_ROUTING`](./MIDDLEWARE_ROUTING.md) (handler
> composition), 🔗 [`CONTEXT`](./CONTEXT.md) (the middleware stashes the
> authenticated user in `r.Context()`), 🔗 [`ERRORS`](./ERRORS.md)
> (`CompareHashAndPassword`/`jwt.Parse` return sentinels you `errors.Is`), and
> 🔗 [`ENCODING_JSON`](./ENCODING_JSON.md) (a JWT payload *is* JSON).

---

## 1. Why this bundle exists (lineage)

Authentication has three jobs that must never be confused:

1. **Prove the password is right at login** — without ever storing the password.
2. **Assert identity on every later request** — without re-sending the password.
3. **Carry that assertion across the wire safely** — without trusting the client.

The Go ecosystem splits these across two libraries and the stdlib: `bcrypt`
(hashing), `golang-jwt/jwt/v5` (signed assertions), and `net/http` (cookies +
middleware). This bundle wires all three end-to-end, **offline**, using
`httptest` so nothing needs a network or a secret key from the environment.

```mermaid
graph TD
    U["user submits password"] --> B["bcrypt.GenerateFromPassword<br/>(RANDOM salt + cost) -> hash"]
    B --> H["store hash in DB<br/>(NEVER the plaintext)"]
    H --> L["login: CompareHashAndPassword<br/>== nil?"]
    L -->|yes| J["issue JWT<br/>(HS256 + claims)"]
    J --> C["Set-Cookie (Secure/HttpOnly/<br/>SameSite=Strict) OR Bearer header"]
    C --> M["auth middleware<br/>(verify JWT, set ctx)"]
    M --> P["protected handler<br/>(reads user from ctx)"]
    style B fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style J fill:#eaf2f8,stroke:#2980b9,stroke-width:3px
    style M fill:#fef9e7,stroke:#f1c40f,stroke-width:3px
```

> From `pkg.go.dev/golang.org/x/crypto/bcrypt` (Overview, verbatim): *"Package
> bcrypt implements the bcrypt password hashing function… bcrypt is an adaptive
> password hashing algorithm… it uses a variant of the Blowfish encryption
> algorithm… the cost can be increased… to make the hash slower."*

---

## 2. Section A — bcrypt: hash (random salt) and verify

```mermaid
graph LR
    P["password + cost"] --> G["GenerateFromPassword"]
    R["crypto/rand salt<br/>(RANDOM each call) --> inside G"]
    G --> H["hash (60 bytes)<br/>format: $2a$cost$<22-byte salt><31-byte digest>"]
    H --> V["CompareHashAndPassword<br/>(hash carries its own cost+salt)"]
    C["candidate password"] --> V
    V -->|"match -> nil"| OK["validates"]
    V -->|"mismatch -> ErrMismatchedHashAndPassword"| NO["rejects"]
    style R fill:#fadbd8,stroke:#e74c3c,stroke-width:3px
    style OK fill:#eafaf1,stroke:#27ae60
```

> From `auth_sessions_jwt.go` Section A:
> ```
> GenerateFromPassword(pw, MinCost=4) -> hash of 60 bytes (NOT printed: random salt)
> DefaultCost=10  MinCost=4  MaxCost=31  (cost < MinCost is bumped to DefaultCost)
> two hashes of the SAME password differ? true  (random salt each call)
> CompareHashAndPassword(hash, correctPw) -> err == nil? true   (validates)
> CompareHashAndPassword(hash, wrongPw)   -> err == nil? false   (rejects: true)
> ```
> ```
> [check] correct password validates (CompareHashAndPassword == nil): OK
> [check] wrong password is rejected (CompareHashAndPassword != nil): OK
> [check] wrong password yields ErrMismatchedHashAndPassword: OK
> [check] two hashes of the same password differ (random salt): OK
> [check] both random-salt hashes still validate the password: OK
> ```

**What.** `bcrypt.GenerateFromPassword(password []byte, cost int) ([]byte, error)`
returns the bcrypt hash at the given cost. `bcrypt.CompareHashAndPassword(hash,
password []byte) error` returns `nil` on a match and
`bcrypt.ErrMismatchedHashAndPassword` on a mismatch.

> From `pkg.go.dev/golang.org/x/crypto/bcrypt` — `GenerateFromPassword`:
> *"returns the bcrypt hash of the password at the given cost. If the cost given
> is less than MinCost, the cost will be set to DefaultCost, instead."*
> `CompareHashAndPassword`: *"compares a bcrypt hashed password with its
> possible plaintext equivalent. Returns nil on success, or an error on
> failure."*

**Why bcrypt (the three properties that make it the right tool).**

1. **Random salt, built in.** Every `GenerateFromPassword` call draws a fresh
   16-byte salt from `crypto/rand` and embeds it in the 60-byte hash. The bundle
   *proves* this: two hashes of the *same* password are `!bytes.Equal` — yet
   both still validate. The salt defeats rainbow tables and makes identical
   passwords hash differently.
2. **Adaptive cost.** The cost factor is an exponent (work = `2^cost`). `MinCost
   = 4`, `DefaultCost = 10`, `MaxCost = 31`. As hardware gets faster you raise
   the cost so hashing stays deliberately slow — this is what makes brute force
   expensive. (🔗 [`GARBAGE_COLLECTOR`](./GARBAGE_COLLECTOR.md): the cost is
   *CPU*, not allocation — bcrypt is compute-bound, so GC tuning is irrelevant
   here.)
3. **The hash is self-describing.** The 60-byte output is
   `$2a$<cost>$<salt><digest>`. `CompareHashAndPassword` reads the cost and salt
   *out of the hash*, which is why the verifier takes **no** cost parameter —
   you can raise the cost on new hashes and old hashes still verify until you
   re-hash them.

**The determinism discipline (why this bundle never prints the hash).** Because
the salt is random, `GenerateFromPassword` returns a **different byte string
every run**. If this guide printed the hash, two `just out` runs would differ.
Instead the bundle asserts only **booleans** (match/no-match, "the two hashes
differ") — those are stable across runs. This is the §4.2 rule applied to
cryptography: never assert randomness, assert *behavior*.

---

## 3. Section B — JWT: issue (HS256, fixed key + fixed claims) and verify

A JWT is a **three-part, dot-separated, base64url-encoded** string:
`header.payload.signature`.

```mermaid
graph LR
    H["header<br/>{alg:HS256, typ:JWT}"] -->|base64url| H64
    PL["payload/claims<br/>{sub, role, exp, ...}"] -->|base64url| PL64
    SS["signing string = H64 '.' PL64"] --> HMAC["HMAC-SHA256(key)"]
    HMAC -->|base64url| SIG["signature"]
    H64 --> TOK["token = H64.P64.SIG"]
    PL64 --> TOK
    SIG --> TOK
    style HMAC fill:#eaf2f8,stroke:#2980b9,stroke-width:3px
```

> From `auth_sessions_jwt.go` Section B:
> ```
> header.payload.signature (deterministic, printed: fixed key+claims):
>   eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjk5OTk5OTk5OTksInJvbGUiOiJhZG1pbiIsInN1YiI6ImFsIn0.B_xWn6dO3vNVTW2RGIfr1ngeI90_G0vdWZHKUWssOPY
> token has 3 parts (header.payload.signature)? true
> jwt.Parse(token, keyfunc) -> err == nil? true   token.Valid? true
> claims: sub="al"  role="admin"
> ```
> ```
> [check] token verifies (err == nil): OK
> [check] token.Valid is true: OK
> [check] claims["sub"] == "al": OK
> [check] claims["role"] == "admin": OK
> [check] token has exactly 3 dot-separated parts: OK
> ```

**What.** `jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{...})` builds
a token; `token.SignedString(key)` signs it with HMAC-SHA256. Verification is
`jwt.Parse(tokenString, keyfunc)`, which checks the signature and validates the
registered claims (`exp`/`nbf`/`iat` when present).

> From `pkg.go.dev/github.com/golang-jwt/jwt/v5` — `NewWithClaims`: *"creates a
> new Token with the specified signing method and claims."* `Parse`: *"parses,
> validates, verifies the signature and returns the parsed token. keyFunc will
> receive the parsed token and should return the cryptographic key for verifying
> the signature. The caller is strongly encouraged to set the WithValidMethods
> option to validate the 'alg' claim in the token matches the expected
> algorithm."* `SigningMethodHMAC`: *"Expects key type of []byte for both
> signing and validation."*

**Why the token here is printable and byte-stable.** A JWT is deterministic
*given* a fixed signing key and fixed claims. This bundle uses a fixed key
(`jwtSecret`) and a **fixed** `exp` (the Unix time `9999999999` — Sat Nov 20
2286 — *not* `time.Now()`), so the signed string is identical on every run and
safe to print. The `exp` is far in the future, so the token is always `Valid`.
This is the JWT half of the determinism discipline: no `time.Now()` may feed a
*printed* value (🔗 [`CONTEXT`](./CONTEXT.md) §5 makes the same point about
timeouts).

**JWT is a signed assertion, NOT encrypted storage.** The header and payload are
base64url — anyone can `base64 -d` them. The signature only proves *who issued
it* and *that it was not modified*; it does **not** hide the contents. Rule:
**never put a secret in a JWT**. And because verification is stateless, **a JWT
cannot be revoked before `exp`** without a server-side blocklist — that is the
core trade-off vs. server-held sessions.

---

## 4. Section C — JWT tamper detection

> From `auth_sessions_jwt.go` Section C:
> ```
> original signature : B_xWn6dO3vNVTW2RGIfr1ngeI90_G0vdWZHKUWssOPY
> tampered signature : A_xWn6dO3vNVTW2RGIfr1ngeI90_G0vdWZHKUWssOPY  (first char flipped)
> jwt.Parse(tampered, keyfunc) -> err == nil? false   token.Valid? false
> ```
> ```
> [check] tampered token is rejected (err != nil): OK
> [check] rejection is ErrTokenSignatureInvalid: OK
> ```

**What.** Flip a single base64url character in the signature segment and the
signing string no longer matches the HMAC. `jwt.Parse` returns a non-nil error
that satisfies `errors.Is(err, jwt.ErrTokenSignatureInvalid)`. This is the
guarantee that lets you trust a token off the wire: **any mutation, anywhere in
the three parts, breaks the signature.**

**Why tampering the signature specifically (not the payload).** Flipping a byte
in the payload *also* invalidates the token, but it might first produce
`ErrTokenMalformed` if the base64 breaks. Flipping a byte in the signature
segment keeps both header and payload decodable, so the failure is cleanly
*signature* invalid — the most direct demonstration of the integrity property.

> From `pkg.go.dev/github.com/golang-jwt/jwt/v5` —
> `var ErrTokenSignatureInvalid = errors.New("token signature is invalid")` is
> the sentinel returned *"if the token's signature is invalid."*

---

## 5. Section D — the alg-confusion / alg=none attack, defeated by the keyfunc

```mermaid
graph TD
    A["attacker forges<br/>header alg=none,<br/>empty signature"] --> PARSE["jwt.Parse(token, keyfunc)"]
    PARSE --> KF["keyfunc receives token:<br/>is Method a *SigningMethodHMAC?"]
    KF -->|"NO (none / RS256)"| ERR["return error -> Parse fails"]
    KF -->|"YES (HS256)"| KEY["return HMAC key -> verify signature"]
    ERR --> REJ["REJECTED (token not valid)"]
    KEY --> OK["validated if signature matches"]
    style ERR fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style A fill:#fadbd8,stroke:#e74c3c
```

> From `auth_sessions_jwt.go` Section D:
> ```
> forged none token: eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJyb2xlIjoiYWRtaW4iLCJzdWIiOiJhdHRhY2tlciJ9.
> jwt.Parse(noneToken, keyfunc) -> err == nil? false   (rejection message: token is unverifiable: error while executing keyfunc: unexpected signing method: none)
>   -> the keyfunc only accepts *jwt.SigningMethodHMAC; 'none' is not HMAC.
>   -> documented alt defense: jwt.WithValidMethods([]string{"HS256"}).
> ```
> ```
> [check] alg=none token rejected (err != nil): OK
> [check] forged none token is not valid: OK
> ```

**The attack.** The JWT `alg` header tells the verifier *which algorithm to
use*. Two classic exploits ride on that:

- **alg=none:** the spec defines an unsecured JWT whose signature is empty. A
  naive verifier that trusts the header and skips the signature check accepts a
  token anyone can forge.
- **alg confusion / key confusion:** a server expecting RS256 (public-key
  verify) is tricked into HS256 (HMAC verify) and uses the *public* RSA key as
  the HMAC secret, which the attacker knows — letting them sign tokens.

**The defense (this bundle).** The `keyfunc` callback receives the **parsed but
unverified** token *before* any key is used. One type assertion kills both
attacks:

```go
func verifyKeyfunc(t *jwt.Token) (any, error) {
    if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {  // require HS256
        return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
    }
    return jwtSecret, nil
}
```

A `none` (or `RS256`) token has a non-HMAC `Method`, so the keyfunc returns an
error and `jwt.Parse` never reaches verification — the run shows the rejection
message `"unexpected signing method: none"`.

> From `pkg.go.dev/github.com/golang-jwt/jwt/v5` — `Keyfunc`: *"will be used by
> the Parse methods as a callback function to supply the key for verification.
> The function receives the parsed, but unverified Token."* And `Parse`:
> *"The caller is strongly encouraged to set the WithValidMethods option to
> validate the 'alg' claim in the token matches the expected algorithm. For more
> details about the importance of validating the 'alg' claim, see
> https://auth0.com/blog/critical-vulnerabilities-in-json-web-token-libraries/."*
> From the README: *"In order to protect against accidental use of Unsecured
> JWTs, tokens using alg=none will only be accepted if the constant
> `jwt.UnsafeAllowNoneSignatureType` is returned [from the keyfunc]."* — so v5
> rejects `none` **by default**; the keyfunc check here is the explicit,
> belt-and-braces version.

---

## 6. Section E — session cookie flags (the wire-level defenses)

```mermaid
graph TD
    C["http.Cookie{...}"] --> F["flag -> defeats"]
    C --> S["Secure: true"]
    C --> H["HttpOnly: true"]
    C --> SS["SameSite: Strict"]
    S --> S1["requires HTTPS -> blocks<br/>plaintext cookie theft on the wire"]
    H --> H1["invisible to document.cookie -><br/>blocks JS exfiltration (XSS)"]
    SS --> SS1["browser won't send cross-site -><br/>blocks CSRF"]
    style H1 fill:#eafaf1,stroke:#27ae60
    style SS1 fill:#eafaf1,stroke:#27ae60
    style S1 fill:#eafaf1,stroke:#27ae60
```

> From `auth_sessions_jwt.go` Section E:
> ```
> cookie flags set: Secure=true  HttpOnly=true  SameSite=Strict=true  Path="/"
> Set-Cookie contains HttpOnly?      true
> Set-Cookie contains Secure?         true
> Set-Cookie contains SameSite=Strict? true
> (Set-Cookie value intentionally not printed; flags are the security payload.)
> ```
> ```
> [check] Set-Cookie contains HttpOnly: OK
> [check] Set-Cookie contains Secure: OK
> [check] Set-Cookie contains SameSite=Strict: OK
> [check] cookie.Path == "/": OK
> ```

**What.** Build an `http.Cookie`, write it with `http.SetCookie`, and read it
back through `httptest.NewRecorder().Result().Header.Get("Set-Cookie")` — fully
offline. The bundle asserts (via `strings.Contains`) that the emitted header
carries `HttpOnly`, `Secure`, and `SameSite=Strict`, and that the value is **not**
printed (a deliberate security habit: a token in a log is a leaked token).

> From `pkg.go.dev/net/http` — `SetCookie`: *"adds a Set-Cookie header to the
> provided ResponseWriter's headers."* `Cookie` struct fields: `Secure` (*"if
> true, cookie is sent only over a secure protocol (https)"*), `HttpOnly`
> (*"HttpOnly cookies are not accessible via JavaScript document.cookie"*),
> `SameSite` (*"provides control over whether cookies are sent by the browser…
> SameSiteStrictMode, SameSiteLaxMode, SameSiteNoneMode, SameSiteDefaultMode"*).

**Why each flag matters (the three attack classes each one blocks).**

| Flag | Browser behavior | Attack it blocks |
|---|---|---|
| `Secure: true` | Cookie only sent over HTTPS | Network sniffing / MITM cookie theft |
| `HttpOnly: true` | `document.cookie` cannot read it | XSS exfiltration of the session token |
| `SameSite: Strict` | Never sent on cross-site requests | CSRF (a forged cross-site POST carries no cookie) |

`SameSite=Strict` is the strongest mode: the cookie is omitted entirely on
top-level navigations from another site. `SameSite=Lax` (the modern browser
default) is a softer choice that still allows the cookie on top-level GETs.
Pick `Strict` for session cookies that nothing but your own JS-driven app needs.

---

## 7. Section F — auth middleware end-to-end (Bearer token → user in context)

> From `auth_sessions_jwt.go` Section F:
> ```
> valid Bearer   -> status 200, body "hello al"
> no token       -> status 401
> tampered token -> status 401
> ```
> ```
> [check] valid Bearer token -> 200: OK
> [check] no Authorization header -> 401: OK
> [check] tampered token -> 401: OK
> [check] valid request body == "hello al": OK
> ```

**What.** The middleware wraps a handler. On each request it:

1. reads `Authorization: Bearer <jwt>` (401 if absent or not `Bearer `),
2. `jwt.Parse`s the token with the alg-checking keyfunc (401 on any error or
   invalid token), and
3. on success, puts the subject (`claims["sub"]`) into `r.Context()` under an
   **unexported** key type, then calls the wrapped handler.

The wrapped handler reads the user back out of context and greets them — proving
the identity flowed through the middleware. Three requests exercise the whole
matrix: a valid token yields `200` with body `hello al`; a missing token and a
tampered token both yield `401`.

**Why context (and the unexported key).** This is the canonical 🔗
[`CONTEXT`](./CONTEXT.md) value pattern done right: `type userCtxKey struct{}`
is a type nothing outside this package can name, so no other package can forge
or clobber the authenticated subject (contrast the string-key collision trap in
`CONTEXT` §7). The handler reads it with a typed assertion and handles the
absent case:

```go
user, _ := r.Context().Value(userCtxKey{}).(string)
```

**The middleware shape (🔗 [`MIDDLEWARE_ROUTING`](./MIDDLEWARE_ROUTING.md)).**
`authMiddleware(secret, next)` returns an `http.HandlerFunc` — the standard Go
"decorator" middleware. Compose it with any router; chain other middleware
(logging, rate limiting) around it. The middleware owns **one** concern — *is
this request authenticated, and if so who is it?* — and nothing else.

---

## 8. Pitfalls (the expert payoff)

| Trap | Symptom | Fix |
|---|---|---|
| Printing/logging the bcrypt hash | `just out` flakes (hash differs each run); also leaks credential material in logs | Never print the hash — assert `CompareHashAndPassword` booleans only. |
| Comparing a password to the stored hash yourself (`==`) | Silent: hash is salted, so a stored-plaintext compare "works" but defeats the point | Always go through `CompareHashAndPassword`; store only the bcrypt hash. |
| Using `bcrypt.DefaultCost` once and never revisiting it | Hashes become brute-forceable as hardware speeds up | Treat cost as a tunable; re-hash on login when you raise it (re-hash-on-login pattern). |
| Putting a secret/PII in a JWT | Anyone base64-decodes the payload; it is **not** encrypted | A JWT is a signed assertion, not a safe. Keep secrets server-side; put only an identity id in it. |
| Trusting the `alg` header / not checking the method in `keyfunc` | alg-confusion or alg=none lets an attacker forge tokens | Type-assert `*jwt.SigningMethodHMAC` in the keyfunc; also pass `jwt.WithValidMethods(["HS256"])`. |
| Expecting to revoke a JWT before `exp` | Stateless verification means the token is valid until it expires, no matter what | Keep `exp` short; maintain a server-side blocklist/jti for revocation; or use server-held sessions. |
| `exp` derived from `time.Now()` and printed | Non-deterministic output / token differs each run | Use a fixed `exp` in tests; in production compute `exp` but never assert its exact value. |
| Omitting `HttpOnly` on the session cookie | XSS reads the token via `document.cookie` | Always `HttpOnly: true` for session/auth cookies. |
| Omitting `SameSite` (or using `Default`) | CSRF: a cross-site forged POST rides the cookie | Use `SameSite: Strict` (or `Lax`) for auth cookies. |
| Omitting `Secure` | Cookie sent over plain HTTP, sniffable | `Secure: true` (HTTPS-only). |
| Using a **string** context key for the user | Cross-package collision / clobbering of the subject | Use an unexported key type (`type userCtxKey struct{}`); see `CONTEXT` §7. |
| `jwt.Parse` with `keyfunc` that returns the key for any method | Accepts `none`/forged-alg tokens | Make the keyfunc return an error for any unexpected `Method`. |
| HMAC key too short / from a "human" string | Weak HMAC, brute-forceable signature | 32+ random bytes from `crypto/rand`; never commit it. |

---

## 9. Cheat sheet

```go
// --- bcrypt (adaptive password hashing; random salt built in) ---
hash, err := bcrypt.GenerateFromPassword([]byte(pw), bcrypt.DefaultCost) // store THIS
// NEVER store pw; the hash is self-describing (carries cost + salt).
if err := bcrypt.CompareHashAndPassword(storedHash, []byte(candidate)); err != nil {
    // wrong password (errors.Is(err, bcrypt.ErrMismatchedHashAndPassword))
}
// consts: MinCost=4, DefaultCost=10, MaxCost=31; cost<MinCost -> DefaultCost.
// Determinism: salt is RANDOM -> never print/assert hash bytes, only match booleans.

// --- JWT (HS256): sign + verify (github.com/golang-jwt/jwt/v5) ---
tok := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
    "sub": "al", "role": "admin", "exp": time.Now().Add(15 * time.Minute).Unix(),
})
ss, _ := tok.SignedString(secretKey)           // secretKey is []byte (>=32 random bytes)
parsed, err := jwt.Parse(ss, func(t *jwt.Token) (any, error) {
    if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {   // defeat alg-confusion/none
        return nil, fmt.Errorf("unexpected method: %v", t.Header["alg"])
    }
    return secretKey, nil
})
// err == nil && parsed.Valid -> trusted; read claims via parsed.Claims.(jwt.MapClaims).
// alt defense: jwt.Parse(ss, kf, jwt.WithValidMethods([]string{"HS256"})).
// JWT is SIGNED not ENCRYPTED (base64 payload) -> never put secrets in it; can't revoke pre-exp.

// --- hardened session cookie (net/http) ---
http.SetCookie(w, &http.Cookie{
    Name: "session", Value: token, Path: "/",
    Secure: true, HttpOnly: true, SameSite: http.SameSiteStrictMode,
    // Secure=HTTPS-only, HttpOnly=no document.cookie (XSS), Strict=no cross-site (CSRF)
})

// --- auth middleware (Bearer token -> user in context) ---
func authMW(secret []byte, next http.HandlerFunc) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        h := r.Header.Get("Authorization")
        if !strings.HasPrefix(h, "Bearer ") { http.Error(w, "unauth", 401); return }
        tok, err := jwt.Parse(strings.TrimPrefix(h, "Bearer "), keyfunc /* checks HMAC */)
        if err != nil || !tok.Valid { http.Error(w, "unauth", 401); return }
        ctx := context.WithValue(r.Context(), userCtxKey{}, tok.Claims.(jwt.MapClaims)["sub"])
        next.ServeHTTP(w, r.WithContext(ctx))
    }
}
```

---

## Sources

Every signature, sentinel name, and behavioral claim above was verified against
the library docs and corroborated by independent secondary sources:

- `golang.org/x/crypto/bcrypt` — https://pkg.go.dev/golang.org/x/crypto/bcrypt
  - Overview (*"bcrypt is an adaptive password hashing algorithm… uses a variant
    of the Blowfish encryption algorithm… the cost can be increased"*):
    https://pkg.go.dev/golang.org/x/crypto/bcrypt#pkg-overview
  - `GenerateFromPassword` (*"returns the bcrypt hash of the password at the
    given cost. If the cost given is less than MinCost, the cost will be set to
    DefaultCost, instead"*) and `CompareHashAndPassword` (*"compares a bcrypt
    hashed password with its possible plaintext equivalent. Returns nil on
    success, or an error on failure"*):
    https://pkg.go.dev/golang.org/x/crypto/bcrypt#GenerateFromPassword
  - `MinCost` / `DefaultCost` / `MaxCost` constants and
    `ErrMismatchedHashAndPassword`:
    https://pkg.go.dev/golang.org/x/crypto/bcrypt#pkg-constants
  - Source (the random-salt path and self-describing hash format):
    https://github.com/golang/crypto/blob/master/bcrypt/bcrypt.go
- `github.com/golang-jwt/jwt/v5` — https://pkg.go.dev/github.com/golang-jwt/jwt/v5
  - `NewWithClaims` / `SignedString` / `Parse` (*"parses, validates, verifies
    the signature… keyFunc will receive the parsed token… The caller is strongly
    encouraged to set the WithValidMethods option to validate the 'alg'
    claim"*), `Keyfunc` (*"receives the parsed, but unverified Token"*),
    `SigningMethodHMAC` (*"Expects key type of []byte"*):
    https://pkg.go.dev/github.com/golang-jwt/jwt/v5
  - `MapClaims` / `RegisteredClaims` (typed claims; `exp`/`nbf`/`iat`
    validated when present):
    https://pkg.go.dev/github.com/golang-jwt/jwt/v5#MapClaims
  - Error sentinels `ErrTokenSignatureInvalid`, `ErrTokenMalformed`,
    `ErrTokenUnverifiable`, etc.:
    https://pkg.go.dev/github.com/golang-jwt/jwt/v5#pkg-variables
  - `WithValidMethods` ParserOption (the documented algorithm-confusion defense):
    https://pkg.go.dev/github.com/golang-jwt/jwt/v5#ParserOption
  - README on `alg=none` (*"tokens using alg=none will only be accepted if the
    constant `jwt.UnsafeAllowNoneSignatureType` is returned"*) and the
    Auth0 "critical vulnerabilities in JSON Web Token libraries" article it
    cites: https://github.com/golang-jwt/jwt  and
    https://auth0.com/blog/critical-vulnerabilities-in-json-web-token-libraries/
- `net/http` — https://pkg.go.dev/net/http
  - `SetCookie` (*"adds a Set-Cookie header"*):
    https://pkg.go.dev/net/http#SetCookie
  - `Cookie` fields `Secure` / `HttpOnly` / `SameSite` (and the `SameSite*Mode`
    constants): https://pkg.go.dev/net/http#Cookie
- Secondary corroboration (>=2 independent sources, web-verified):
  - Auth0 — *"Critical vulnerabilities in JSON Web Token libraries"* (the
    alg-confusion / none-alg attack and why `alg` must be pinned):
    https://auth0.com/blog/critical-vulnerabilities-in-json-web-token-libraries/
  - PortSwigger Web Security Academy — *"Algorithm confusion attacks"* (key
    confusion: forcing HS256 verification with a known public key):
    https://portswigger.net/web-security/jwt/algorithm-confusion
  - MDN — *"Using HTTP cookies"* (`Secure`, `HttpOnly`, `SameSite` browser
    semantics and the attacks each mitigates):
    https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies
  - Alex Edwards — *"A Complete Guide to Working with Cookies in Go"*
    (setting/reading cookies incl. `httptest`):
    https://www.alexedwards.net/blog/working-with-cookies-in-go
  - Calhoun — *"Securing Cookies in Go"* (HttpOnly/Secure/SameSite defaults and
    overrides): https://www.calhoun.io/securing-cookies-in-go/
  - WorkOS — *"How to handle JWT in Go"* (v5 `keyfunc` method check and
    `WithValidMethods`): https://workos.com/blog/how-to-handle-jwt-in-go

**Facts that could not be verified by running** (documented, not executed,
because they are cross-cutting security claims or browser-enforced behavior
rather than single-program output): browser enforcement of `Secure`/`HttpOnly`/
`SameSite` (the bundle verifies the *header* Go emits; the browser *enforces*
them); the claim that v5 accepts `alg=none` **only** when the keyfunc returns
`UnsafeAllowNoneSignatureType` (confirmed by the README, not reproduced — this
bundle rejects `none` earlier in the keyfunc); and the long-term "can't revoke a
JWT before `exp`" trade-off (a property of stateless verification, requiring a
server blocklist to defeat — corroborated by the Auth0 article).
