//go:build ignore

// auth_sessions_jwt.go — Phase 6 bundle.
//
// GOAL (one line): show, by printing every behavior, how Go hashes passwords
// with bcrypt, signs/verifies JWTs (and defeats alg-confusion), sets hardened
// session cookies, and guards an HTTP route with Bearer-token middleware.
//
// This is the GROUND TRUTH for AUTH_SESSIONS_JWT.md. Every value, token, and
// status code below is computed by this file; the .md guide pastes it verbatim.
// Never hand-compute.
//
// Determinism notes (see HOW_TO_RESEARCH.md §4.2):
//   - bcrypt uses a RANDOM salt, so the hash bytes differ every run. We NEVER
//     print the hash; we only assert match/no-match booleans. Two `just out`
//     runs are therefore byte-identical.
//   - The JWT uses a FIXED signing key + FIXED claims (exp is a far-future fixed
//     Unix time, NOT time.Now()), so the signed token is byte-stable and safe to
//     print.
//
// Run:
//
//	go run auth_sessions_jwt.go

package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// --- shared, deterministic JWT inputs ----------------------------------------

// jwtSecret is the HMAC-SHA256 key. Fixed -> the signed token is byte-stable.
// (In production: 32+ random bytes from crypto/rand, never committed.)
var jwtSecret = []byte("all-your-base-are-belong-to-us")

// userCtxKey is an UNEXPORTED context key type (see CONTEXT.md): only this
// package can forge a value under it, preventing cross-package collisions.
type userCtxKey struct{}

// issueToken builds the deterministic HS256 token used across sections.
// exp is a FIXED far-future Unix time (year 2286), NOT time.Now(), so the token
// is always valid and byte-identical between runs.
func issueToken() (string, jwt.MapClaims) {
	claims := jwt.MapClaims{
		"sub":  "al",
		"role": "admin",
		"exp":  int64(9999999999), // fixed: Sat Nov 20 2286 — no time.Now()
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	ss, err := tok.SignedString(jwtSecret)
	if err != nil {
		panic(err)
	}
	return ss, claims
}

// verifyKeyfunc is the safe keyfunc: it only hands out the key when the token's
// signing method is HMAC (HS256). This single check defeats the alg-confusion /
// alg=none attack: a forged "none" or RS256 token has a non-HMAC Method, so the
// keyfunc returns an error and jwt.Parse rejects it.
func verifyKeyfunc(t *jwt.Token) (any, error) {
	if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
		return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
	}
	return jwtSecret, nil
}

// authMiddleware is a Bearer-token guard. It verifies the JWT and, on success,
// stashes the authenticated subject in the request context for the next handler.
func authMiddleware(secret []byte, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		auth := r.Header.Get("Authorization")
		if !strings.HasPrefix(auth, "Bearer ") {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		tokStr := strings.TrimPrefix(auth, "Bearer ")
		tok, err := jwt.Parse(tokStr, func(t *jwt.Token) (any, error) {
			if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", t.Header["alg"])
			}
			return secret, nil
		})
		if err != nil || !tok.Valid {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		claims, _ := tok.Claims.(jwt.MapClaims)
		user, _ := claims["sub"].(string)
		ctx := context.WithValue(r.Context(), userCtxKey{}, user)
		next.ServeHTTP(w, r.WithContext(ctx))
	}
}

// sectionA — bcrypt: hash (random salt), verify correct vs wrong password.
func sectionA() {
	sectionBanner("A — bcrypt: hash a password; verify correct vs wrong")

	password := []byte("correct horse battery staple")
	wrong := []byte("Tr0ub4dor&3")

	// GenerateFromPassword hashes `password` at cost MinCost (4). It embeds a
	// RANDOM salt, so two hashes of the SAME password differ — that is the
	// point. We never print the hash (it is random); we only compare.
	hash1, err := bcrypt.GenerateFromPassword(password, bcrypt.MinCost)
	if err != nil {
		panic(err)
	}
	hash2, err := bcrypt.GenerateFromPassword(password, bcrypt.MinCost)
	if err != nil {
		panic(err)
	}
	fmt.Printf("GenerateFromPassword(pw, MinCost=%d) -> hash of %d bytes (NOT printed: random salt)\n",
		bcrypt.MinCost, len(hash1))
	fmt.Printf("DefaultCost=%d  MinCost=%d  MaxCost=%d  (cost < MinCost is bumped to DefaultCost)\n",
		bcrypt.DefaultCost, bcrypt.MinCost, bcrypt.MaxCost)
	fmt.Printf("two hashes of the SAME password differ? %v  (random salt each call)\n",
		!bytes.Equal(hash1, hash2))

	// CompareHashAndPassword(hash, candidate): nil on match, an error on
	// mismatch. The hash itself records the cost, so the verifier needs no
	// separate cost parameter — that is how it stays "adaptive".
	fmt.Printf("CompareHashAndPassword(hash, correctPw) -> err == nil? %v   (validates)\n",
		bcrypt.CompareHashAndPassword(hash1, password) == nil)
	errWrong := bcrypt.CompareHashAndPassword(hash1, wrong)
	fmt.Printf("CompareHashAndPassword(hash, wrongPw)   -> err == nil? %v   (rejects: %v)\n",
		errWrong == nil, errors.Is(errWrong, bcrypt.ErrMismatchedHashAndPassword))

	check("correct password validates (CompareHashAndPassword == nil)",
		bcrypt.CompareHashAndPassword(hash1, password) == nil)
	check("wrong password is rejected (CompareHashAndPassword != nil)",
		errWrong != nil)
	check("wrong password yields ErrMismatchedHashAndPassword",
		errors.Is(errWrong, bcrypt.ErrMismatchedHashAndPassword))
	check("two hashes of the same password differ (random salt)",
		!bytes.Equal(hash1, hash2))
	check("both random-salt hashes still validate the password",
		bcrypt.CompareHashAndPassword(hash2, password) == nil)
}

// sectionB — JWT: issue (HS256, fixed key + fixed claims) and verify.
func sectionB() {
	sectionBanner("B — JWT: issue with HS256 + fixed claims; verify & read sub")

	tokenStr, _ := issueToken()
	fmt.Printf("header.payload.signature (deterministic, printed: fixed key+claims):\n  %s\n", tokenStr)

	parts := strings.Split(tokenStr, ".")
	fmt.Printf("token has %d parts (header.payload.signature)? %v\n",
		len(parts), len(parts) == 3)

	// Verify: Parse runs the keyfunc (which checks the alg) and validates the
	// signature + registered claims (exp/nbf/iat if present).
	tok, err := jwt.Parse(tokenStr, verifyKeyfunc)
	fmt.Printf("jwt.Parse(token, keyfunc) -> err == nil? %v   token.Valid? %v\n",
		err == nil, tok != nil && tok.Valid)

	sub, _ := tok.Claims.(jwt.MapClaims)["sub"].(string)
	role, _ := tok.Claims.(jwt.MapClaims)["role"].(string)
	fmt.Printf("claims: sub=%q  role=%q\n", sub, role)

	check("token verifies (err == nil)", err == nil)
	check("token.Valid is true", tok.Valid)
	check(`claims["sub"] == "al"`, sub == "al")
	check(`claims["role"] == "admin"`, role == "admin")
	check("token has exactly 3 dot-separated parts", len(parts) == 3)
}

// sectionC — JWT tamper detection: flip one base64url char in the signature.
func sectionC() {
	sectionBanner("C — JWT tamper detection: flipping a signature byte fails Parse")

	tokenStr, _ := issueToken()
	parts := strings.Split(tokenStr, ".")
	sig := parts[2]

	// Flip the FIRST byte of the signature segment to a different valid
	// base64url char -> the signature no longer matches the signed content.
	flipped := byte('A')
	if sig[0] == 'A' {
		flipped = 'B'
	}
	tamperedSig := string(flipped) + sig[1:]
	tampered := parts[0] + "." + parts[1] + "." + tamperedSig
	fmt.Printf("original signature : %s\n", sig)
	fmt.Printf("tampered signature : %s  (first char flipped)\n", tamperedSig)

	tok, err := jwt.Parse(tampered, verifyKeyfunc)
	fmt.Printf("jwt.Parse(tampered, keyfunc) -> err == nil? %v   token.Valid? %v\n",
		err == nil, tok != nil && tok.Valid)

	check("tampered token is rejected (err != nil)", err != nil)
	check("rejection is ErrTokenSignatureInvalid",
		errors.Is(err, jwt.ErrTokenSignatureInvalid))
}

// sectionD — alg-confusion / alg=none: a forged none token is rejected.
func sectionD() {
	sectionBanner("D — alg-confusion defense: forged alg=none token rejected by keyfunc")

	// Build a forged "none" token IN CODE (no hand-computed base64): empty
	// signature, alg=none header. The keyfunc requires HMAC, so the library
	// never even asks for an HMAC key.
	header, _ := json.Marshal(map[string]any{"alg": "none", "typ": "JWT"})
	payload, _ := json.Marshal(map[string]any{"sub": "attacker", "role": "admin"})
	noneToken := base64.RawURLEncoding.EncodeToString(header) + "." +
		base64.RawURLEncoding.EncodeToString(payload) + "."
	fmt.Printf("forged none token: %s\n", noneToken)

	tok, err := jwt.Parse(noneToken, verifyKeyfunc)
	fmt.Printf("jwt.Parse(noneToken, keyfunc) -> err == nil? %v   (rejection message: %v)\n",
		err == nil, err)
	fmt.Printf("  -> the keyfunc only accepts *jwt.SigningMethodHMAC; 'none' is not HMAC.\n")
	fmt.Printf("  -> documented alt defense: jwt.WithValidMethods([]string{\"HS256\"}).\n")

	check("alg=none token rejected (err != nil)", err != nil)
	check("forged none token is not valid", tok == nil || !tok.Valid)
}

// sectionE — session cookie flags via httptest.NewRecorder.
func sectionE() {
	sectionBanner("E — session cookie flags: Secure / HttpOnly / SameSite=Strict")

	ck := &http.Cookie{
		Name:     "session",
		Value:    "opaque-session-value", // value NOT printed below (security habit)
		Path:     "/",
		Secure:   true,
		HttpOnly: true,
		SameSite: http.SameSiteStrictMode,
	}

	rec := httptest.NewRecorder()
	http.SetCookie(rec, ck)
	setCookie := rec.Result().Header.Get("Set-Cookie")

	fmt.Printf("cookie flags set: Secure=%v  HttpOnly=%v  SameSite=Strict=%v  Path=%q\n",
		ck.Secure, ck.HttpOnly, ck.SameSite == http.SameSiteStrictMode, ck.Path)
	fmt.Printf("Set-Cookie contains HttpOnly?      %v\n", strings.Contains(setCookie, "HttpOnly"))
	fmt.Printf("Set-Cookie contains Secure?         %v\n", strings.Contains(setCookie, "Secure"))
	fmt.Printf("Set-Cookie contains SameSite=Strict? %v\n", strings.Contains(setCookie, "SameSite=Strict"))
	fmt.Printf("(Set-Cookie value intentionally not printed; flags are the security payload.)\n")

	check("Set-Cookie contains HttpOnly", strings.Contains(setCookie, "HttpOnly"))
	check("Set-Cookie contains Secure", strings.Contains(setCookie, "Secure"))
	check("Set-Cookie contains SameSite=Strict", strings.Contains(setCookie, "SameSite=Strict"))
	check("cookie.Path == \"/\"", ck.Path == "/")
}

// sectionF — auth middleware end-to-end: valid Bearer -> 200; absent/invalid -> 401.
func sectionF() {
	sectionBanner("F — auth middleware: valid Bearer -> 200; none/invalid -> 401")

	tokenStr, _ := issueToken()

	protected := authMiddleware(jwtSecret, func(w http.ResponseWriter, r *http.Request) {
		user, _ := r.Context().Value(userCtxKey{}).(string)
		fmt.Fprintf(w, "hello %s", user)
	})

	// 1) valid Bearer token -> 200, and the subject was placed in context.
	reqOK := httptest.NewRequest(http.MethodGet, "/me", nil)
	reqOK.Header.Set("Authorization", "Bearer "+tokenStr)
	recOK := httptest.NewRecorder()
	protected.ServeHTTP(recOK, reqOK)
	fmt.Printf("valid Bearer   -> status %d, body %q\n", recOK.Code, recOK.Body.String())

	// 2) no Authorization header -> 401.
	reqNone := httptest.NewRequest(http.MethodGet, "/me", nil)
	recNone := httptest.NewRecorder()
	protected.ServeHTTP(recNone, reqNone)
	fmt.Printf("no token       -> status %d\n", recNone.Code)

	// 3) tampered token -> 401.
	parts := strings.Split(tokenStr, ".")
	tampered := parts[0] + "." + parts[1] + "." + strings.Repeat("A", len(parts[2]))
	reqBad := httptest.NewRequest(http.MethodGet, "/me", nil)
	reqBad.Header.Set("Authorization", "Bearer "+tampered)
	recBad := httptest.NewRecorder()
	protected.ServeHTTP(recBad, reqBad)
	fmt.Printf("tampered token -> status %d\n", recBad.Code)

	check("valid Bearer token -> 200", recOK.Code == http.StatusOK)
	check("no Authorization header -> 401", recNone.Code == http.StatusUnauthorized)
	check("tampered token -> 401", recBad.Code == http.StatusUnauthorized)
	check(`valid request body == "hello al"`, recOK.Body.String() == "hello al")
}

func main() {
	fmt.Println("auth_sessions_jwt.go — Phase 6 bundle.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
