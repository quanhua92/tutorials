//go:build ignore

// net_http.go — Phase 5 bundle.
//
// GOAL (one line): show, by exercising http.Handler/HandlerFunc, the Go 1.22
// enhanced ServeMux (method + {wildcard} + PathValue), the http.Client timeout
// footgun, middleware composition, and httptest (NewRecorder / NewServer) — all
// in-process, deterministic, no real network.
//
// This is the GROUND TRUTH for NET_HTTP.md. Every status code, header, and body
// below is produced by this file; the .md guide pastes it verbatim. Nothing is
// hand-computed. Determinism is total: httptest.NewServer runs on a loopback
// port we NEVER print (random port); we print only status codes, headers, and
// bodies, which are stable across runs.
//
// Run:
//
//	go run net_http.go

package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"time"
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

// closeBody closes a response body, ignoring the (uninteresting) error. Defined
// once so every section reads cleanly; ignoring Body.Close's error is idiomatic
// after the body has already been consumed.
func closeBody(resp *http.Response) {
	_ = resp.Body.Close()
}

// sectionA pins the two foundational types: http.Handler is an interface with
// one method; http.HandlerFunc adapts a plain func into that interface.
// httptest.NewRecorder captures the response with NO socket at all.
func sectionA() {
	sectionBanner("A — Handler interface, HandlerFunc adapter, NewRecorder")

	// helloHandler is a PLAIN function whose signature matches ServeHTTP. A bare
	// func is NOT itself an http.Handler — it has no method — so it must be
	// adapted by the named type http.HandlerFunc.
	helloHandler := func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK) // 200
		_, _ = w.Write([]byte("hello"))
	}

	// http.HandlerFunc(f) adapts f into an http.Handler: HandlerFunc is a named
	// type with a ServeHTTP method that just calls f, so it satisfies Handler.
	var h http.Handler = http.HandlerFunc(helloHandler)
	fmt.Printf("type of http.HandlerFunc(helloHandler): %T\n", h)

	// httptest.NewRecorder returns a *ResponseRecorder, which implements
	// http.ResponseWriter but records writes in memory instead of a socket.
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))

	fmt.Printf("hello handler via NewRecorder -> status %d, body %q\n",
		rec.Code, rec.Body.String())

	check("hello handler status == 200", rec.Code == http.StatusOK)
	check(`hello handler body == "hello"`, rec.Body.String() == "hello")
}

// sectionB shows the Go 1.22+ enhanced ServeMux: method-prefixed patterns,
// the {id} single-segment wildcard, and r.PathValue("id"). The handler is
// served end-to-end via httptest.NewServer (in-process loopback socket).
func sectionB() {
	sectionBanner("B — Go 1.22 ServeMux: {id} wildcard + r.PathValue")

	// "GET /items/{id}" is a 1.22 pattern: method GET + path with a {id}
	// wildcard that matches exactly one path segment. Pre-1.22 you had to
	// register "/items/" and parse the suffix yourself.
	mux := http.NewServeMux()
	mux.HandleFunc("GET /items/{id}", func(w http.ResponseWriter, r *http.Request) {
		id := r.PathValue("id") // new in Go 1.22
		fmt.Fprintf(w, "item id=%s", id)
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()

	// We deliberately do NOT print srv.URL (it carries a random port). Only the
	// status code and body are printed — both deterministic.
	resp, err := srv.Client().Get(srv.URL + "/items/42")
	if err != nil {
		panic(err)
	}
	body, _ := io.ReadAll(resp.Body)
	closeBody(resp)

	fmt.Printf("GET /items/42 -> status %d, body %q\n", resp.StatusCode, string(body))

	check("GET /items/{id} -> status 200", resp.StatusCode == http.StatusOK)
	check(`body contains PathValue "42"`, strings.Contains(string(body), "42"))
}

// sectionC shows method matching: register "GET /x" and "POST /x". A request
// whose method matches no pattern gets 405 Method Not Allowed (per RFC 9110),
// with an Allow header listing the registered methods.
func sectionC() {
	sectionBanner("C — Method matching: GET/POST 200, DELETE -> 405")

	mux := http.NewServeMux()
	mux.HandleFunc("GET /x", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("GET ok"))
	})
	mux.HandleFunc("POST /x", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("POST ok"))
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()
	c := srv.Client()

	// GET -> 200
	rGet, err := c.Get(srv.URL + "/x")
	if err != nil {
		panic(err)
	}
	bodyGet, _ := io.ReadAll(rGet.Body)
	closeBody(rGet)

	// POST -> 200
	rPost, err := c.Post(srv.URL+"/x", "text/plain", strings.NewReader(""))
	if err != nil {
		panic(err)
	}
	bodyPost, _ := io.ReadAll(rPost.Body)
	closeBody(rPost)

	// DELETE -> no pattern matches -> ServeMux replies 405 with Allow header.
	reqDel, err := http.NewRequest(http.MethodDelete, srv.URL+"/x", nil)
	if err != nil {
		panic(err)
	}
	rDel, err := c.Do(reqDel)
	if err != nil {
		panic(err)
	}
	closeBody(rDel)

	fmt.Printf("GET    /x -> status %d, body %q\n", rGet.StatusCode, string(bodyGet))
	fmt.Printf("POST   /x -> status %d, body %q\n", rPost.StatusCode, string(bodyPost))
	fmt.Printf("DELETE /x -> status %d, Allow=%q\n", rDel.StatusCode, rDel.Header.Get("Allow"))

	check("GET /x -> 200", rGet.StatusCode == http.StatusOK)
	check("POST /x -> 200", rPost.StatusCode == http.StatusOK)
	check("DELETE /x -> 405 (Method Not Allowed)", rDel.StatusCode == http.StatusMethodNotAllowed)
	check("405 response has a non-empty Allow header", rDel.Header.Get("Allow") != "")
	check("Allow header advertises GET and POST",
		strings.Contains(rDel.Header.Get("Allow"), "GET") &&
			strings.Contains(rDel.Header.Get("Allow"), "POST"))
}

// sectionD pins the timeout footgun: http.DefaultClient.Timeout == 0, and 0
// means NO timeout. http.Get/Post use DefaultClient, so a hung server hangs
// them forever. The fix is always to construct an http.Client{Timeout: ...}.
func sectionD() {
	sectionBanner("D — http.Client timeout pitfall (DefaultClient has NO timeout)")

	// THE FOOTGUN, printed verbatim: DefaultClient.Timeout is the zero value 0,
	// and 0s means "no timeout" — a hung server hangs you forever.
	fmt.Printf("http.DefaultClient.Timeout = %v  (0s == NO timeout: the footgun)\n",
		http.DefaultClient.Timeout)

	mux := http.NewServeMux()
	mux.HandleFunc("GET /fast", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("fast ok"))
	})
	// A deliberately slow handler: it sleeps far longer than the short client
	// timeout we will use below.
	mux.HandleFunc("GET /slow", func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(100 * time.Millisecond)
		_, _ = w.Write([]byte("slow ok"))
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()

	// 1) A client WITH a Timeout hits the fast handler -> 200.
	client := &http.Client{Timeout: 1 * time.Second}
	resp, err := client.Get(srv.URL + "/fast")
	if err != nil {
		panic(err)
	}
	closeBody(resp)
	fmt.Printf("client{Timeout:1s} GET /fast -> status %d, err=<nil>\n", resp.StatusCode)
	check("client with Timeout gets 200 from fast handler", resp.StatusCode == http.StatusOK)

	// 2) A client whose Timeout is SHORTER than the handler's response time
	//    aborts the request. The error is deterministic in KIND: it wraps the
	//    context.DeadlineExceeded sentinel. We assert the sentinel, never a
	//    duration — so output is byte-identical run to run.
	shortClient := &http.Client{Timeout: 10 * time.Millisecond}
	resp2, err2 := shortClient.Get(srv.URL + "/slow")
	if resp2 != nil {
		closeBody(resp2)
	}
	fmt.Printf("client{Timeout:10ms} GET /slow -> err wraps context.DeadlineExceeded? %v\n",
		errors.Is(err2, context.DeadlineExceeded))
	check("short-timeout client errors on a slow handler", err2 != nil)
	check("short-timeout error wraps context.DeadlineExceeded",
		errors.Is(err2, context.DeadlineExceeded))
}

// sectionE shows middleware: a function that takes an http.Handler and returns
// a wrapped http.Handler. Composition is just HandlerFunc nesting.
func sectionE() {
	sectionBanner("E — Middleware: HandlerFunc composition (wraps + sets header)")

	// A middleware takes a Handler (the "next" one) and returns a Handler.
	logging := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Header().Set MUST happen before WriteHeader/Write — once the
			// status line is sent the header map is frozen.
			w.Header().Set("X-Wrapped", "yes")
			next.ServeHTTP(w, r)
		})
	}

	// The inner/terminal handler.
	final := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("from inner handler"))
	})

	// Wrap final with the logging middleware. Multiple middlewares stack the
	// same way: a(logging(b(final))).
	wrapped := logging(final)

	srv := httptest.NewServer(wrapped)
	defer srv.Close()

	resp, err := srv.Client().Get(srv.URL + "/anything")
	if err != nil {
		panic(err)
	}
	body, _ := io.ReadAll(resp.Body)
	closeBody(resp)

	fmt.Printf("GET via middleware -> status %d, X-Wrapped=%q, body=%q\n",
		resp.StatusCode, resp.Header.Get("X-Wrapped"), string(body))

	check("middleware response status == 200", resp.StatusCode == http.StatusOK)
	check(`middleware set X-Wrapped header == "yes"`, resp.Header.Get("X-Wrapped") == "yes")
	check("inner handler body delivered through middleware",
		string(body) == "from inner handler")
}

// sectionF is the end-to-end slice: a JSON handler served over
// httptest.NewServer, fetched with an http.Client, decoded with json.Decoder.
func sectionF() {
	sectionBanner("F — End-to-end: JSON handler over NewServer + decode")

	type widget struct {
		ID   int    `json:"id"`
		Name string `json:"name"`
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /widget", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(widget{ID: 42, Name: "widget"})
	})

	srv := httptest.NewServer(mux)
	defer srv.Close()

	resp, err := srv.Client().Get(srv.URL + "/widget")
	if err != nil {
		panic(err)
	}
	defer closeBody(resp)

	var got widget
	if err := json.NewDecoder(resp.Body).Decode(&got); err != nil {
		panic(err)
	}

	fmt.Printf("decoded JSON -> ID=%d Name=%q (Content-Type=%q)\n",
		got.ID, got.Name, resp.Header.Get("Content-Type"))

	check("decoded widget ID == 42", got.ID == 42)
	check(`decoded widget Name == "widget"`, got.Name == "widget")
	check(`Content-Type == "application/json"`,
		resp.Header.Get("Content-Type") == "application/json")
}

func main() {
	fmt.Println("net_http.go — Phase 5 bundle.")
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
