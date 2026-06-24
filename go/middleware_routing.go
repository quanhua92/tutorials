//go:build ignore

// middleware_routing.go — Phase 6 bundle.
//
// GOAL (one line): show, by exercising every form against httptest, how Go
// middleware is just `func(http.Handler) http.Handler` composition — hand-chained
// in the stdlib, then declared declaratively with chi's Use / Route / With — and
// how a recover() middleware turns a panicking handler into a clean 500.
//
// This is the GROUND TRUTH for MIDDLEWARE_ROUTING.md. Every status code, header,
// and body below is produced by this file; the .md guide pastes it verbatim.
// Determinism is total: httptest.NewRecorder uses no socket, and httptest.NewServer
// runs on a loopback port we NEVER print (random port); we print only status
// codes, headers, and bodies — all stable across runs. No real network.
//
// Run:
//
//	go run middleware_routing.go

package main

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"

	"github.com/go-chi/chi/v5"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// closeBody closes a response body, ignoring the (uninteresting) error.
func closeBody(resp *http.Response) {
	_ = resp.Body.Close()
}

// There is NO special "middleware type" in Go: a middleware is any function with
// the signature func(http.Handler) http.Handler. It takes the "next" handler and
// returns one that wraps it — running before/after next, setting headers,
// short-circuiting, recovering panics, etc. The whole mechanism is plain stdlib.

// chain composes middlewares so chain(a, b)(h) == a(b(h)): the FIRST middleware
// is the OUTERMOST layer (runs first on the way in, last on the way out). This
// is the stdlib way to build a reusable stack without a router.
func chain(mw ...func(http.Handler) http.Handler) func(http.Handler) http.Handler {
	return func(h http.Handler) http.Handler {
		for i := len(mw) - 1; i >= 0; i-- {
			h = mw[i](h)
		}
		return h
	}
}

// stdLogger sets X-Logged BEFORE calling next. The header MUST be set before any
// Write/WriteHeader, or it is silently dropped (the header map freezes once the
// status line flushes).
func stdLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Logged", "yes")
		next.ServeHTTP(w, r)
	})
}

// stdAuth simulates an auth gate: a wrong Authorization header SHORT-CIRCUITS
// (writes 401 and returns — next is never called); a good one sets X-Authed and
// continues. This is the canonical "middleware can abort the chain" pattern.
func stdAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer secret" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		w.Header().Set("X-Authed", "yes")
		next.ServeHTTP(w, r)
	})
}

// recoverPanic wraps next with defer/recover: if next panics, it writes a clean
// 500 instead of letting the panic propagate. Without such a wrapper, a real
// http.Server ABORTS the response (the client sees a broken connection, not a
// 500) and a direct recorder call crashes the caller.
func recoverPanic(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if rec := recover(); rec != nil {
				http.Error(w, "internal server error", http.StatusInternalServerError)
			}
		}()
		next.ServeHTTP(w, r)
	})
}

// sectionA builds a hand-written middleware chain on the stdlib (logger+auth)
// and drives it through httptest.NewRecorder (no socket). It shows the happy
// path (200, both headers) and the short-circuit (401: logger ran, next did not).
func sectionA() {
	sectionBanner("A — Stdlib middleware chain: logger + auth (NewRecorder)")

	final := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("from inner handler"))
	})

	// chain(stdLogger, stdAuth)(final) == stdLogger(stdAuth(final)): logger is
	// outermost, so X-Logged is set before auth even runs.
	h := chain(stdLogger, stdAuth)(final)

	// Happy path: valid token -> auth sets X-Authed and calls final.
	recOK := httptest.NewRecorder()
	reqOK := httptest.NewRequest(http.MethodGet, "/secret", nil)
	reqOK.Header.Set("Authorization", "Bearer secret")
	h.ServeHTTP(recOK, reqOK)
	fmt.Printf("valid token -> status %d, X-Logged=%q, X-Authed=%q, body=%q\n",
		recOK.Code, recOK.Header().Get("X-Logged"), recOK.Header().Get("X-Authed"),
		recOK.Body.String())

	// Short-circuit: bad token -> auth writes 401 and returns; final never runs.
	recBad := httptest.NewRecorder()
	reqBad := httptest.NewRequest(http.MethodGet, "/secret", nil)
	reqBad.Header.Set("Authorization", "Bearer WRONG")
	h.ServeHTTP(recBad, reqBad)
	fmt.Printf("bad token   -> status %d, X-Logged=%q, X-Authed=%q, body=%q\n",
		recBad.Code, recBad.Header().Get("X-Logged"), recBad.Header().Get("X-Authed"),
		recBad.Body.String())

	check("valid token: status == 200", recOK.Code == http.StatusOK)
	check(`valid token: X-Logged == "yes"`, recOK.Header().Get("X-Logged") == "yes")
	check(`valid token: X-Authed == "yes"`, recOK.Header().Get("X-Authed") == "yes")
	check("bad token: status == 401 (auth short-circuited)", recBad.Code == http.StatusUnauthorized)
	check("bad token: logger still ran (X-Logged set)", recBad.Header().Get("X-Logged") == "yes")
	check("bad token: auth did NOT set X-Authed (next skipped)", recBad.Header().Get("X-Authed") == "")
}

// sectionB shows that wrapping a 1.22 ServeMux in middleware does NOT disturb
// pattern matching or PathValue extraction: the request flows through the
// middleware unchanged, so the mux still matches "GET /users/{id}" and the
// handler still reads r.PathValue("id").
func sectionB() {
	sectionBanner("B — 1.22 ServeMux through middleware (PathValue survives)")

	mux := http.NewServeMux()
	mux.HandleFunc("GET /users/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id") // 1.22 wildcard accessor
		fmt.Fprintf(w, "user id=%s", id)
	})

	// Wrap the WHOLE mux in the logger middleware (the "outer middleware" pattern:
	// one chain applied to every route the mux serves).
	h := stdLogger(mux)

	srv := httptest.NewServer(h)
	defer srv.Close()

	resp, err := srv.Client().Get(srv.URL + "/users/7")
	if err != nil {
		panic(err)
	}
	body, _ := io.ReadAll(resp.Body)
	closeBody(resp)

	fmt.Printf("GET /users/7 via logger(mux) -> status %d, X-Logged=%q, body=%q\n",
		resp.StatusCode, resp.Header.Get("X-Logged"), string(body))

	check("GET /users/{id} -> status 200", resp.StatusCode == http.StatusOK)
	check("middleware set X-Logged on a mux-wrapping response",
		resp.Header.Get("X-Logged") == "yes")
	check(`PathValue "7" reached the handler through the middleware`,
		strings.Contains(string(body), "7"))
}

// sectionC proves the recover() middleware two ways: WITHOUT it a panicking
// handler's panic escapes ServeHTTP (here caught locally so the bundle survives
// to print the contrast); WITH recoverPanic the same handler yields a clean 500.
func sectionC() {
	sectionBanner("C — Panic-recovery middleware: panic -> clean 500")

	panicky := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		panic("boom from handler")
	})

	// 1) WITHOUT recovery middleware: the panic escapes ServeHTTP. Caught locally
	//    only so the bundle can keep running — nothing was written, so the
	//    recorder keeps the default 200 and an empty body (a "response aborted").
	var propagated any
	recNoRecover := httptest.NewRecorder()
	func() {
		defer func() { propagated = recover() }()
		panicky.ServeHTTP(recNoRecover, httptest.NewRequest(http.MethodGet, "/boom", nil))
	}()
	fmt.Printf("no recoverer  -> panic propagated? %v, status %d (default; response aborted), body=%q\n",
		propagated != nil, recNoRecover.Code, recNoRecover.Body.String())

	// 2) WITH recoverPanic: the panic is caught and a 500 is written.
	recRecover := httptest.NewRecorder()
	recoverPanic(panicky).ServeHTTP(recRecover, httptest.NewRequest(http.MethodGet, "/boom", nil))
	fmt.Printf("with recoverer -> status %d, body=%q\n", recRecover.Code, recRecover.Body.String())

	check("without recoverer: panic propagated out of ServeHTTP", propagated != nil)
	check("without recoverer: no status written (default 200, empty body)",
		recNoRecover.Code == http.StatusOK && recNoRecover.Body.Len() == 0)
	check("with recoverer: status == 500", recRecover.Code == http.StatusInternalServerError)
	check(`with recoverer: body == "internal server error"`,
		recRecover.Body.String() == "internal server error\n")
}

// sectionD uses chi: a middleware applied with r.Use runs on EVERY route the
// router serves. chi.Router satisfies http.Handler, so httptest.NewServer
// accepts it directly — 100% net/http compatible.
func sectionD() {
	sectionBanner("D — chi r.Use: global middleware on every route")

	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("X-Global", "yes")
			next.ServeHTTP(w, r)
		})
	})
	r.Get("/a", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("a"))
	})
	r.Get("/b", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("b"))
	})

	srv := httptest.NewServer(r)
	defer srv.Close()
	c := srv.Client()

	respA, err := c.Get(srv.URL + "/a")
	if err != nil {
		panic(err)
	}
	bodyA, _ := io.ReadAll(respA.Body)
	closeBody(respA)

	respB, err := c.Get(srv.URL + "/b")
	if err != nil {
		panic(err)
	}
	bodyB, _ := io.ReadAll(respB.Body)
	closeBody(respB)

	fmt.Printf("GET /a -> status %d, X-Global=%q, body=%q\n",
		respA.StatusCode, respA.Header.Get("X-Global"), string(bodyA))
	fmt.Printf("GET /b -> status %d, X-Global=%q, body=%q\n",
		respB.StatusCode, respB.Header.Get("X-Global"), string(bodyB))

	check("chi.Router is an http.Handler (served by NewServer)", respA.StatusCode == http.StatusOK)
	check("chi Use: X-Global set on /a", respA.Header.Get("X-Global") == "yes")
	check("chi Use: X-Global set on /b", respB.Header.Get("X-Global") == "yes")
	check(`/a body == "a"`, string(bodyA) == "a")
	check(`/b body == "b"`, string(bodyB) == "b")
}

// sectionE shows chi's THREE middleware scopes on one router:
//   - Use on the outer router       -> X-Global on EVERY route
//   - Route("/api", ...).Use(...)   -> X-Scoped on /api/* ONLY
//   - r.With(...).Get(...)          -> X-OneTime on that ONE route ONLY
//
// /public gets ONLY X-Global (proving the scoped mw did not leak outside /api).
func sectionE() {
	sectionBanner("E — chi Route/With: scoped vs per-route middleware")

	setHeader := func(key, val string) func(http.Handler) http.Handler {
		return func(next http.Handler) http.Handler {
			return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set(key, val)
				next.ServeHTTP(w, r)
			})
		}
	}

	r := chi.NewRouter()
	r.Use(setHeader("X-Global", "yes")) // global

	// Scoped: middleware inside Route applies only under /api.
	r.Route("/api", func(r chi.Router) {
		r.Use(setHeader("X-Scoped", "yes"))
		r.Get("/users", func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte("api users"))
		})
	})

	// Per-route: With applies middleware to a single endpoint only.
	r.With(setHeader("X-OneTime", "yes")).Get("/onetime", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("one time"))
	})

	// Public: ONLY the global middleware reaches here.
	r.Get("/public/health", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("public ok"))
	})

	srv := httptest.NewServer(r)
	defer srv.Close()
	c := srv.Client()

	get := func(path string) (int, http.Header, string) {
		resp, err := c.Get(srv.URL + path)
		if err != nil {
			panic(err)
		}
		b, _ := io.ReadAll(resp.Body)
		closeBody(resp)
		return resp.StatusCode, resp.Header, string(b)
	}

	stA, hA, bA := get("/api/users")
	stO, hO, bO := get("/onetime")
	stP, hP, bP := get("/public/health")

	fmt.Printf("GET /api/users     -> status %d, X-Global=%q X-Scoped=%q X-OneTime=%q, body=%q\n",
		stA, hA.Get("X-Global"), hA.Get("X-Scoped"), hA.Get("X-OneTime"), bA)
	fmt.Printf("GET /onetime       -> status %d, X-Global=%q X-Scoped=%q X-OneTime=%q, body=%q\n",
		stO, hO.Get("X-Global"), hO.Get("X-Scoped"), hO.Get("X-OneTime"), bO)
	fmt.Printf("GET /public/health -> status %d, X-Global=%q X-Scoped=%q X-OneTime=%q, body=%q\n",
		stP, hP.Get("X-Global"), hP.Get("X-Scoped"), hP.Get("X-OneTime"), bP)

	check("/api/users: status 200", stA == http.StatusOK)
	check("/api/users: has X-Global (inherited)", hA.Get("X-Global") == "yes")
	check("/api/users: has X-Scoped (route-scoped mw)", hA.Get("X-Scoped") == "yes")
	check("/onetime: status 200", stO == http.StatusOK)
	check("/onetime: has X-OneTime (per-route mw via With)", hO.Get("X-OneTime") == "yes")
	check("/public/health: status 200", stP == http.StatusOK)
	check("/public/health: has X-Global", hP.Get("X-Global") == "yes")
	check("/public/health: does NOT have X-Scoped (mw did not leak)", hP.Get("X-Scoped") == "")
	check("/public/health: does NOT have X-OneTime", hP.Get("X-OneTime") == "")
}

// sectionF is the head-to-head: the SAME requirement — "every request is logged,
// /admin requires auth, /public does not" — once in pure stdlib (manual per-route
// wrapping) and once in chi (declarative Route/Use). Both produce identical
// responses; chi is declarative sugar over the same func(http.Handler) http.Handler.
func sectionF() {
	sectionBanner("F — Stdlib manual chaining vs chi declarative groups")

	// --- stdlib: ServeMux has no per-route-middleware support, so wrap by hand.
	stdMux := http.NewServeMux()
	adminHandler := stdLogger(stdAuth(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("admin area"))
	})))
	publicHandler := stdLogger(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("public area"))
	}))
	stdMux.Handle("GET /admin", adminHandler)
	stdMux.Handle("GET /public", publicHandler)

	// --- chi: declarative — one global Use + one scoped Route.
	chiMux := chi.NewRouter()
	chiMux.Use(stdLogger) // global logger
	chiMux.Route("/admin", func(r chi.Router) {
		r.Use(stdAuth) // scoped auth
		r.Get("/", func(w http.ResponseWriter, r *http.Request) {
			_, _ = w.Write([]byte("admin area"))
		})
	})
	chiMux.Get("/public", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("public area"))
	})

	authReq := func() *http.Request {
		req := httptest.NewRequest(http.MethodGet, "/admin", nil)
		req.Header.Set("Authorization", "Bearer secret")
		return req
	}
	publicReq := httptest.NewRequest(http.MethodGet, "/public", nil)

	runOne := func(h http.Handler, req *http.Request) (int, http.Header, string) {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)
		return rec.Code, rec.Header(), rec.Body.String()
	}

	sA, hsA, bA := runOne(stdMux, authReq())
	cA, hcA, bcA := runOne(chiMux, authReq())
	sP, hsP, bP := runOne(stdMux, publicReq)
	cP, hcP, bcP := runOne(chiMux, publicReq)

	fmt.Printf("stdlib /admin  -> status %d, X-Logged=%q X-Authed=%q, body=%q\n",
		sA, hsA.Get("X-Logged"), hsA.Get("X-Authed"), bA)
	fmt.Printf("chi    /admin  -> status %d, X-Logged=%q X-Authed=%q, body=%q\n",
		cA, hcA.Get("X-Logged"), hcA.Get("X-Authed"), bcA)
	fmt.Printf("stdlib /public -> status %d, X-Logged=%q X-Authed=%q, body=%q\n",
		sP, hsP.Get("X-Logged"), hsP.Get("X-Authed"), bP)
	fmt.Printf("chi    /public -> status %d, X-Logged=%q X-Authed=%q, body=%q\n",
		cP, hcP.Get("X-Logged"), hcP.Get("X-Authed"), bcP)

	check("stdlib /admin: status 200 (auth passed)", sA == http.StatusOK)
	check("chi    /admin: status 200 (auth passed)", cA == http.StatusOK)
	check("stdlib /admin: X-Logged + X-Authed both set",
		hsA.Get("X-Logged") == "yes" && hsA.Get("X-Authed") == "yes")
	check("chi    /admin: X-Logged + X-Authed both set",
		hcA.Get("X-Logged") == "yes" && hcA.Get("X-Authed") == "yes")
	check("both /admin: identical body", bA == bcA && bA == "admin area")
	check("both /public: status 200", sP == http.StatusOK && cP == http.StatusOK)
	check("both /public: X-Logged set, X-Authed absent",
		hsP.Get("X-Logged") == "yes" && hcP.Get("X-Logged") == "yes" &&
			hsP.Get("X-Authed") == "" && hcP.Get("X-Authed") == "")
	check("both /public: identical body", bP == bcP && bP == "public area")
}

func main() {
	fmt.Println("middleware_routing.go — Phase 6 bundle.")
	fmt.Println("Every status code, header, and body below is produced by this file;")
	fmt.Println("the .md guide pastes it verbatim. No real network; no printed URLs")
	fmt.Println("(httptest uses random loopback ports).")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
