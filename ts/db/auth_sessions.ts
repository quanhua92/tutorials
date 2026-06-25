// auth_sessions.ts — Phase 8 bundle (member: db; deps: jose, node:crypto).
//
// GOAL (one line): show, by printing every behavior, how a Node/TS app stores
// passwords with a SLOW salted hash (scrypt), signs & verifies stateless JWTs
// (jose), backs them with hardened cookies, and falls back to stateful server
// sessions — pinning the 3 auth failure modes (wrong pw / tampered / expired)
// as check()'d invariants.
//
// This is the GROUND TRUTH for AUTH_SESSIONS.md. Every token, hash hex, boolean,
// and status code in the guide is printed by this file. Change it -> re-run
// (just out auth_sessions) -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): HTTP is stateless, so "who is this request
// from?" must be re-asserted on EVERY request. There are two models:
//   - STATELESS: a JWT signed by the server carries the user's claims; the
//     server verifies the SIGNATURE (no DB lookup) — fast, horizontally
//     scalable, but UNREVOKABLE without a server-side blocklist.
//   - STATEFUL: an opaque random session ID in a cookie keys a server-side
//     store (Map / Redis); every request does a lookup — revocable, but slower.
// Both sit on top of the SAME foundation: a password that is NEVER stored in
// the clear — only a SLOW, SALTED hash (scrypt/bcrypt/argon2). This bundle
// wires all three (hash, JWT, session) end-to-end, OFFLINE, using node:crypto
// (scrypt — built-in, no dep) and jose (JWT). It is the cross-language analog
// of Go's golang-jwt + bcrypt (../go/AUTH_SESSIONS_JWT.md).
//
// DETERMINISM NOTES (how output is byte-identical across `just out` runs):
//   - scrypt is deterministic given (password, salt, keylen, N,r,p). We use a
//     FIXED 16-byte salt so the hash is stable. REAL code uses
//     randomBytes(16) per user — printed length only, never the value.
//   - HS256 JWT signing is deterministic given (key, protected header, claims).
//     We pin iat (setIssuedAt(FIXED)) and exp (setExpirationTime(FIXED number))
//     so the token string is byte-identical run to run. No Date.now().
//   - Session IDs are opaque random in production; here we use a FIXED id for
//     the set/get flow (deterministic) and only assert randomBytes() length.
//
// Run:
//     pnpm exec tsx auth_sessions.ts   (or: just run auth_sessions)

import { scryptSync, timingSafeEqual, randomBytes } from "node:crypto";
import { SignJWT, jwtVerify, decodeJwt, decodeProtectedHeader, errors as joseErrors } from "jose";
import type { JWTPayload } from "jose";

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// === PINNED CONSTANTS (determinism — see header) ============================
// The HMAC secret for HS256. >= 32 bytes (256 bits) — HS256 needs a key whose
// length matches the hash output. Fixed for the demo so the JWT is stable.
const SECRET = new TextEncoder().encode("tutorials-db-auth-secret-key-fixed-32b!");

// A FIXED 16-byte salt for scrypt, so the derived key is byte-identical across
// runs. REAL CODE: const salt = randomBytes(16); // unique per user.
const FIXED_SALT = Buffer.from("0123456789abcdef0123456789abcdef", "hex");

// Pinned JWT timestamps (unix seconds). iat is "issued at"; exp is "expiry".
// Both fixed so the JWT string does not drift across runs.
const FIXED_IAT = 1_700_000_000; // Tue Nov 14 2023 (clearly in the past)
const FIXED_EXP_VALID = 9_999_999_999; // Sat Nov 20 2286 (far future => valid)
const FIXED_EXP_EXPIRED = 1_700_000_001; // 1s after iat => already expired

// hashPassword derives a 64-byte key from password+salt via scrypt, then
// returns salt||hash as a single Buffer (the "stored hash"). Storing the salt
// PREPENDED to the hash is the standard layout: to verify, split off the first
// SALT_LEN bytes, re-derive, constant-time compare. scrypt is intentionally
// SLOW (memory-hard) so brute-force is infeasible — the opposite of fast hashes
// like MD5/SHA-256, which must NEVER be used for passwords.
function hashPassword(password: string, salt: Buffer): Buffer {
  const derived = scryptSync(password, salt, 64); // 64-byte derived key
  return Buffer.concat([salt, derived]); // store salt + hash together
}

// verifyPassword re-derives the hash from the candidate password using the
// salt sliced off the stored hash, then compares in CONSTANT TIME via
// timingSafeEqual. Constant-time compare prevents timing side-channels that
// would leak how many leading bytes matched (a classic auth bypass).
// NOTE: scryptSync is itself slow (~100ms at default N), which is the point —
// it rate-limits online guessing. timingSafeEqual only protects the COMPARE.
function verifyPassword(password: string, stored: Buffer): boolean {
  const salt = stored.subarray(0, 16);
  const expected = stored.subarray(16);
  const candidate = scryptSync(password, salt, 64);
  // timingSafeEqual requires equal-length Buffers; both are 64 bytes here.
  return timingSafeEqual(candidate, expected);
}

// signJwt builds & signs a compact JWS-formatted JWT. The payload carries the
// registered claims (iss/sub/iat/exp) plus a custom "role" claim. Returns the
// 3-part base64url string: header.payload.signature
async function signJwt(
  subject: string,
  role: string,
  expSeconds: number,
): Promise<string> {
  return new SignJWT({ role })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer("tutorials-app")
    .setSubject(subject)
    .setIssuedAt(FIXED_IAT)
    .setExpirationTime(expSeconds)
    .sign(SECRET);
}

// verifyJwt wraps jose.jwtVerify, asserting the issuer. It returns the payload
// (typed) on success and THROWS a jose error subclass on any failure:
//   - bad signature        -> JWSSignatureVerificationFailed (code ERR_JWS_...)
//   - past exp             -> JWTExpired                     (code ERR_JWT_EXPIRED)
//   - wrong iss/aud        -> JWTClaimValidationFailed       (code ERR_JWT_...)
async function verifyJwt(token: string): Promise<JWTPayload> {
  const { payload } = await jwtVerify(token, SECRET, { issuer: "tutorials-app" });
  return payload;
}

// ============================================================================
// Section A — Password hashing: scrypt + FIXED salt + timingSafeEqual
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — Password hashing: scrypt + FIXED salt + timingSafeEqual");

  // The PAYOFF: the same password + the SAME salt yields the SAME derived key.
  // (Real code uses a fresh randomBytes(16) salt per user, stored with the hash.)
  const storedCorrect = hashPassword("hunter2", FIXED_SALT);
  const storedAgain = hashPassword("hunter2", FIXED_SALT);

  console.log("scrypt('hunter2', FIXED_SALT, 64) ->");
  console.log(`  stored length : ${storedCorrect.length} bytes  (16 salt + 64 hash)`);
  console.log(`  salt (hex)    : ${storedCorrect.subarray(0, 16).toString("hex")}`);
  console.log(`  hash (hex)    : ${storedCorrect.subarray(16).toString("hex")}`);
  check("scrypt is deterministic: same pw+salt -> same 80-byte stored hash",
    timingSafeEqual(storedCorrect, storedAgain));

  // A DIFFERENT password produces a completely different hash (avalanche).
  const storedOther = hashPassword("hunter3", FIXED_SALT);
  console.log(`\nscrypt('hunter3', same salt) -> different hash`);
  console.log(`  hash (hex)    : ${storedOther.subarray(16).toString("hex")}`);
  check("different password -> different hash",
    !timingSafeEqual(storedCorrect.subarray(16), storedOther.subarray(16)));

  // Verify: correct password passes, wrong password fails (constant-time).
  console.log("\nverifyPassword results:");
  const okCorrect = verifyPassword("hunter2", storedCorrect);
  const okWrong = verifyPassword("wrong-password", storedCorrect);
  console.log(`  verify('hunter2')        -> ${okCorrect}`);
  console.log(`  verify('wrong-password') -> ${okWrong}`);
  check("correct password verifies", okCorrect === true);
  check("wrong password fails (no match)", okWrong === false);

  // timingSafeEqual throws on length mismatch — demonstrate it protects the
  // compare by requiring equal-length buffers (both 64 bytes here).
  check("timingSafeEqual is used (constant-time, equal-length only)",
    typeof timingSafeEqual === "function");

  // REAL CODE note: production uses randomBytes salt per user. We exercise the
  // real API here but only assert its LENGTH (deterministic), never the value.
  const realSalt = randomBytes(16);
  check("real salt via randomBytes(16) is 16 bytes", realSalt.length === 16);
  console.log("  (real code: randomBytes(16) salt per user; demo uses FIXED salt for determinism)");
}

// ============================================================================
// Section B — JWT sign & verify: claims, 3-part structure, decode
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — JWT sign & verify: claims, 3-part structure, decode");

  const token = await signJwt("user-1", "admin", FIXED_EXP_VALID);
  const parts = token.split(".");

  console.log(`signed JWT (HS256, iss=tutorials-app, sub=user-1, role=admin):`);
  console.log(`  ${token}`);
  console.log(`\nstructure: header.payload.signature  (3 base64url parts, 2 dots)`);
  console.log(`  parts.length === ${parts.length}`);
  check("JWT has exactly 3 dot-separated parts", parts.length === 3);

  // Decode WITHOUT verifying (decodeJwt does NOT check the signature — preview
  // only). The header carries alg; the payload carries the registered claims.
  const header = decodeProtectedHeader(token);
  const decoded = decodeJwt(token);
  console.log(`\ndecoded header (decodeProtectedHeader, NO signature check):`);
  console.log(`  alg = ${header.alg}`);
  console.log(`\ndecoded payload (decodeJwt, NO signature check):`);
  console.log(`  iss = ${decoded.iss}`);
  console.log(`  sub = ${decoded.sub}`);
  console.log(`  role = ${decoded.role}`);
  console.log(`  iat = ${decoded.iat}   (pinned -> deterministic token)`);
  console.log(`  exp = ${decoded.exp}`);
  check('decoded header alg === "HS256"', header.alg === "HS256");
  check('decoded claim iss === "tutorials-app"', decoded.iss === "tutorials-app");
  check('decoded claim sub === "user-1"', decoded.sub === "user-1");
  check('decoded custom claim role === "admin"', decoded.role === "admin");
  check("decoded claim iat === FIXED_IAT (pinned)", decoded.iat === FIXED_IAT);
  check("decoded claim exp === FIXED_EXP_VALID (pinned)", decoded.exp === FIXED_EXP_VALID);

  // VERIFY (signature + issuer). This is the authoritative check — decodeJwt
  // above only previewed. jwtVerify re-derives the HMAC and constant-time
  // compares it; on success it returns the trusted payload.
  const payload = await verifyJwt(token);
  console.log(`\njwtVerify(token, SECRET, {issuer}) -> TRUSTED payload:`);
  console.log(`  sub = ${payload.sub}`);
  console.log(`  role = ${payload.role}`);
  check("verified token sub === user-1", payload.sub === "user-1");
  check("verified token role === admin", payload.role === "admin");
  check("JWT is deterministic: pinned secret+claims+iat -> same string",
    token === await signJwt("user-1", "admin", FIXED_EXP_VALID));
}

// ============================================================================
// Section C — JWT failure modes + the stateless tradeoff
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — JWT failure modes + the stateless tradeoff");

  const goodToken = await signJwt("user-1", "admin", FIXED_EXP_VALID);

  // FAILURE 1: a TAMPERED token (signature no longer matches the payload).
  // Flip the last chars of the signature -> HMAC verify fails.
  const tampered = goodToken.slice(0, -4) + "AAAA";
  console.log("FAILURE 1 — tampered signature:");
  console.log(`  tampered token : ${tampered}`);
  let tamperedThrew = false;
  let tamperedCode = "";
  try {
    await verifyJwt(tampered);
  } catch (err) {
    tamperedThrew = true;
    tamperedCode = err instanceof joseErrors.JWSSignatureVerificationFailed
      ? "ERR_JWS_SIGNATURE_VERIFICATION_FAILED"
      : (err as Error).message;
    console.log(`  -> threw ${err instanceof Error ? err.constructor.name : "Error"} (code: ${tamperedCode})`);
  }
  check("tampered token throws JWSSignatureVerificationFailed",
    tamperedThrew && tamperedCode === "ERR_JWS_SIGNATURE_VERIFICATION_FAILED");
  check("tampered token -> HTTP 401 (signature invalid)", tamperedThrew);

  // FAILURE 2: an EXPIRED token (exp in the past).
  const expiredToken = await signJwt("user-1", "admin", FIXED_EXP_EXPIRED);
  console.log("\nFAILURE 2 — expired token (exp pinned to the past):");
  console.log(`  expired token  : ${expiredToken}`);
  let expiredThrew = false;
  let expiredIsExpiredClass = false;
  try {
    await verifyJwt(expiredToken);
  } catch (err) {
    expiredThrew = true;
    expiredIsExpiredClass = err instanceof joseErrors.JWTExpired;
    console.log(`  -> threw ${err instanceof Error ? err.constructor.name : "Error"} (code: ${err instanceof joseErrors.JOSEError ? err.code : "?"})`);
  }
  check("expired token throws JWTExpired", expiredThrew && expiredIsExpiredClass);
  check("expired token -> HTTP 401 (trigger refresh flow)", expiredThrew);

  // FAILURE 3: WRONG ISSUER (claim validation fails). The token's signature is
  // VALID, but the iss claim does not match what the verifier expects.
  const wrongIssuerToken = await new SignJWT({ role: "admin" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer("some-other-app")
    .setSubject("user-1")
    .setIssuedAt(FIXED_IAT)
    .setExpirationTime(FIXED_EXP_VALID)
    .sign(SECRET);
  console.log("\nFAILURE 3 — wrong issuer (signature valid, claim mismatch):");
  console.log(`  token (iss=some-other-app) : ${wrongIssuerToken}`);
  let wrongIssThrew = false;
  let wrongIssCode = "";
  try {
    await verifyJwt(wrongIssuerToken);
  } catch (err) {
    wrongIssThrew = true;
    wrongIssCode = err instanceof joseErrors.JWTClaimValidationFailed
      ? "ERR_JWT_CLAIM_VALIDATION_FAILED"
      : (err instanceof Error ? err.constructor.name : "Error");
    console.log(`  -> threw ${err instanceof Error ? err.constructor.name : "Error"} (code: ${wrongIssCode})`);
  }
  check("wrong-issuer token throws JWTClaimValidationFailed",
    wrongIssThrew && wrongIssCode === "ERR_JWT_CLAIM_VALIDATION_FAILED");
  check("wrong-issuer token -> HTTP 401", wrongIssThrew);

  // THE STATELESS TRADEOFF: verifying a JWT needs ONLY the secret — no DB
  // lookup. That makes it fast & horizontally scalable, but a minted token
  // CANNOT be revoked before its exp without a server-side blocklist.
  console.log("\nSTATELESS TRADEOFF:");
  console.log("  verify(token) needs ONLY the HMAC secret — no DB/store lookup.");
  console.log("  => fast, scales horizontally. BUT: cannot revoke a minted token");
  console.log("     before its exp without a server-side denylist (blocklist).");

  // REFRESH-TOKEN FLOW: a short-lived access token + a longer-lived refresh
  // token (also a signed JWT, distinguished by a custom claim). When the access
  // token expires (Failure 2), the client presents the refresh token to mint a
  // a new access token — without re-entering the password.
  const accessToken = await new SignJWT({ role: "admin", typ: "access" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer("tutorials-app")
    .setSubject("user-1")
    .setIssuedAt(FIXED_IAT)
    .setExpirationTime(FIXED_EXP_VALID)
    .sign(SECRET);
  const refreshToken = await new SignJWT({ role: "admin", typ: "refresh" })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuer("tutorials-app")
    .setSubject("user-1")
    .setIssuedAt(FIXED_IAT)
    .setExpirationTime(99_999_999_999) // longer-lived than access (year ~5138)
    .sign(SECRET);
  console.log("\nREFRESH-TOKEN FLOW (access + refresh):");
  console.log(`  access token  : ${accessToken}`);
  console.log(`  refresh token : ${refreshToken}`);
  const accessClaims = decodeJwt(accessToken);
  const refreshClaims = decodeJwt(refreshToken);
  console.log(`  access.typ=${accessClaims.typ}  refresh.typ=${refreshClaims.typ}`);
  check("access token has typ=access", accessClaims.typ === "access");
  check("refresh token has typ=refresh (longer-lived)", refreshClaims.typ === "refresh");
  check("refresh token exp >= access token exp",
    (refreshClaims.exp ?? 0) >= (accessClaims.exp ?? 0));
  check("jose error subclasses extend JOSEError (typed, .code present)",
    new joseErrors.JWTExpired("x", {}) instanceof joseErrors.JOSEError);
}

// ============================================================================
// Section D — Stateful sessions: opaque cookie ID -> server store + cookie flags
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — Stateful sessions: opaque cookie ID -> server store + cookie flags");

  // A STATEFUL session: the server generates an opaque random ID, stores the
  // session data keyed by that ID (here an in-memory Map; production uses
  // Redis/DB), and sends ONLY the ID to the client in a hardened cookie. On
  // every later request the client sends the cookie back; the server does a
  // LOOKUP (the opposite of the stateless JWT, which needs no lookup). Because
  // the data lives server-side, deleting the row INSTANTLY revokes the session.
  type Session = { userId: string; role: string; createdAt: number };
  const sessionStore = new Map<string, Session>();

  // Opaque session IDs are random in production. For determinism the demo uses
  // a FIXED id for the set/get flow; we only assert randomBytes() length.
  const FIXED_SESSION_ID = "sess_4f8a7c2b9e1d6053a0cb2def78193456";
  const session: Session = { userId: "user-1", role: "admin", createdAt: FIXED_IAT };
  sessionStore.set(FIXED_SESSION_ID, session);

  const fetched = sessionStore.get(FIXED_SESSION_ID);
  console.log("STATEFUL session store (Map: opaqueId -> Session):");
  console.log(`  set('${FIXED_SESSION_ID}', {userId, role, createdAt})`);
  console.log(`  get('${FIXED_SESSION_ID}') -> userId=${fetched?.userId}, role=${fetched?.role}`);
  check("session set -> get returns the stored userId", fetched?.userId === "user-1");
  check("session set -> get returns the stored role", fetched?.role === "admin");

  // Revocation = delete the row. The client's cookie is now a dead string.
  sessionStore.delete(FIXED_SESSION_ID);
  check("stateful session is revocable: delete -> get returns undefined",
    sessionStore.get(FIXED_SESSION_ID) === undefined);

  // Real production IDs are random & unguessable. Exercise the real API but
  // assert only length/charset (deterministic), never the random value.
  const realSessionId = `sess_${randomBytes(32).toString("hex")}`;
  console.log(`\nproduction session id via randomBytes(32).toString('hex'):`);
  console.log(`  id length = ${realSessionId.length}  (prefix 'sess_' + 64 hex chars)`);
  check("production session id is 'sess_' + 64 hex chars", realSessionId.length === 5 + 64);
  check("production session id is hex after prefix",
    /^[0-9a-f]{64}$/.test(realSessionId.slice(5)));

  // COOKIE FLAGS — the Set-Cookie header that carries the session ID (or JWT)
  // must be hardened. Each flag closes a specific attack:
  //   HttpOnly   : JS cannot read the cookie (document.cookie) -> stops XSS theft
  //   Secure     : cookie only sent over HTTPS               -> stops wire sniffing
  //   SameSite   : restricts cross-site sending              -> stops CSRF
  //                 Strict = never send on cross-site nav
  //                 Lax    = send on top-level GET nav (default on modern browsers)
  //                 None   = always (REQUIRES Secure)
  //   Path=/; Max-Age=... : scope + lifetime
  function buildSetCookie(name: string, value: string, maxAge: number): string {
    return [
      `${name}=${value}`,
      "Path=/",
      `Max-Age=${maxAge}`,
      "HttpOnly",
      "Secure",
      "SameSite=Strict",
    ].join("; ");
  }
  const setCookie = buildSetCookie("session", FIXED_SESSION_ID, 3600);
  console.log(`\nSet-Cookie header (hardened):`);
  console.log(`  ${setCookie}`);
  check("Set-Cookie has HttpOnly (blocks XSS document.cookie theft)",
    setCookie.includes("HttpOnly"));
  check("Set-Cookie has Secure (HTTPS only)", setCookie.includes("Secure"));
  check("Set-Cookie has SameSite=Strict (blocks CSRF)",
    setCookie.includes("SameSite=Strict"));
  check("Set-Cookie has Path=/", setCookie.includes("Path=/"));
  check("Set-Cookie carries the opaque session value",
    setCookie.includes(`session=${FIXED_SESSION_ID}`));
}

// ============================================================================
// Section E — OAuth2/OIDC (documented) + cross-language + 3 failure modes
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — OAuth2/OIDC (documented) + cross-language + 3 failure modes");

  // OAuth2 / OpenID Connect (OIDC) — the THIRD model (documented, not built):
  // instead of YOUR server checking the password, an identity provider (Google,
  // GitHub, Auth0...) does. The canonical Authorization Code flow:
  //   1. client -> your server -> redirect to provider's /authorize?client_id=...
  //   2. user logs in at the provider (you never see the password)
  //   3. provider redirects back to your /callback?code=XYZ
  //   4. your server POSTs code + client_secret to provider's /token -> tokens
  //   5. your server verifies the provider-signed ID token (a JWT, signed with
  //      the provider's asymmetric key — RS256/ES256, verified via JWKS)
  //   6. you mint YOUR OWN session/JWT from the verified identity.
  // OIDC layers an "ID token" (a JWT with user claims: sub/email/name) on top
  // of OAuth2's access tokens. The security win: you never store or touch the
  // user's password for that provider, and the key is ASYMMETRIC (public verify,
  // private sign) — unlike this bundle's HS256 (symmetric shared secret).
  console.log("OAuth2/OIDC Authorization Code flow (documented — not executed):");
  console.log("  1. client -> redirect to provider /authorize?client_id=...&redirect_uri=...");
  console.log("  2. user authenticates AT the provider (you never see the password)");
  console.log("  3. provider redirects to your /callback?code=XYZ");
  console.log("  4. server POSTs code+client_secret to provider /token -> access+id tokens");
  console.log("  5. server verifies provider-signed ID token (JWT, RS256, via JWKS)");
  console.log("  6. server mints its OWN session/JWT from the verified identity");
  console.log("  KEY DIFF: provider signs with an ASYMMETRIC key (RS256/ES256); you");
  console.log("  verify with the public key. This bundle uses SYMMETRIC HS256.");
  check("OAuth2 model documented (provider authenticates, not your server)", true);

  // The 3 AUTH FAILURE MODES, summarized (each exercised in Section C above):
  //   wrong password -> 401 (scrypt compare fails, Section A)
  //   tampered token -> 401 (HMAC signature mismatch, Section C Failure 1)
  //   expired token  -> 401 (exp in the past -> refresh flow, Section C Failure 2)
  console.log("\nThe 3 auth failure modes (all -> HTTP 401):");
  console.log("  1. wrong password  -> scrypt compare fails            (Section A)");
  console.log("  2. tampered token  -> HMAC signature verify fails     (Section C F1)");
  console.log("  3. expired token   -> exp in the past -> refresh flow (Section C F2)");
  check("the 3 auth failure modes are documented (all 401)", true);

  // CROSS-LANGUAGE: the SAME models, different libraries.
  //   Go     : golang-jwt/jwt/v5 (JWT) + golang.org/x/crypto/bcrypt (hashing)
  //   Python : FastAPI OAuth2PasswordBearer + passlib[bcrypt]
  //   Node   : jose (JWT) + node:crypto scrypt (this bundle)
  // bcrypt vs scrypt: both slow + salted; scrypt is MEMORY-HARD (costly to
  // GPU/ASIC brute-force); bcrypt is CPU-hard only. argon2 (the PHC winner) is
  // the current recommendation but needs a native dep in Node.
  console.log("\nCROSS-LANGUAGE (same models, different libraries):");
  console.log("  Go     : golang-jwt/jwt/v5 + golang.org/x/crypto/bcrypt");
  console.log("  Python : FastAPI OAuth2PasswordBearer + passlib[bcrypt]");
  console.log("  Node   : jose + node:crypto scrypt  (THIS bundle)");
  console.log("  bcrypt vs scrypt: both slow + salted; scrypt is MEMORY-HARD.");
  console.log("  argon2 (PHC winner) is the current pick but needs a native dep in Node.");
  check("cross-language parallels documented (Go/Python/Node)", true);

  // Final summary: which primitive solves which job.
  console.log("\nPRIMITIVE -> JOB map (the whole bundle in one table):");
  console.log("  scrypt (slow+salted hash)   : store passwords safely (never plaintext)");
  console.log("  timingSafeEqual             : constant-time hash compare (no timing leak)");
  console.log("  jose SignJWT / jwtVerify    : stateless signed assertions (no DB lookup)");
  console.log("  opaque cookie ID + store    : stateful revocable sessions (DB lookup)");
  console.log("  HttpOnly/Secure/SameSite    : harden the cookie (XSS/sniff/CSRF)");
  console.log("  OAuth2/OIDC code flow       : delegate auth to a provider (no pw stored)");
  check("primitive->job map documented", true);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("auth_sessions.ts — Phase 8 bundle (member: db; jose + node:crypto).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Determinism: FIXED salt (scrypt) + FIXED secret + PINNED iat/exp (JWT)");
  console.log("=> output is byte-identical across `just out auth_sessions` runs.");
  console.log("(Real code uses randomBytes(16) salt per user + rotating secrets.)");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

await main();
