//go:build ignore

// graceful_shutdown.go — Phase 8 bundle (production patterns).
//
// GOAL (one line): show, by SIMULATING the shutdown trigger, how to drain an
// http.Server gracefully (Shutdown vs Close), propagate cancellation through a
// root context (signal.NotifyContext), fire RegisterOnShutdown hooks, and
// orchestrate the full graceful-termination dance — all offline via httptest.
//
// This is the GROUND TRUTH for GRACEFUL_SHUTDOWN.md. Every status code, error,
// and outcome below is produced by this file; the .md guide pastes it verbatim.
// Nothing is hand-computed.
//
// DETERMINISM (critical for this bundle): a real OS signal (SIGTERM) is awkward
// to trigger deterministically from within a program, so this file NEVER sends
// itself a signal. Instead it SIMULATES the trigger by calling the cancel func
// (stop()) and by calling server.Shutdown/Close directly. httptest.NewServer
// runs on a loopback port we NEVER print. No elapsed duration is ever printed —
// only error codes, HTTP statuses, and boolean outcomes, which are stable. Two
// runs of `just out graceful_shutdown` are byte-identical.
//
// STDLIB-FIRST: only stdlib is used. The errgroup-equivalent is reimplemented
// from scratch (NOT imported) per the golang.org/x/sync/errgroup design.
//
// Run:
//
//	go run graceful_shutdown.go

package main

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/signal"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

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

// --- errgroup-equivalent (built from scratch; stdlib only) -------------------
//
// This mirrors golang.org/x/sync/errgroup.Group: Go(f) launches a goroutine
// tracked by a WaitGroup; Wait() blocks until all exit and returns the FIRST
// non-nil error via atomic.Pointer[error] + CompareAndSwap(nil, &err). It is the
// natural coordinator for the shutdown dance (run Shutdown + worker-drain
// concurrently; bail on the first failure). No golang.org/x import is needed.

// group is an errgroup-equivalent: a set of goroutines whose first error is kept.
type group struct {
	wg  sync.WaitGroup
	err atomic.Pointer[error]
}

// Go launches f in a new goroutine tracked by the WaitGroup. If f returns a
// non-nil error, it is stored only if none was stored before (first error wins).
func (g *group) Go(f func() error) {
	g.wg.Add(1)
	go func() {
		defer g.wg.Done()
		if err := f(); err != nil {
			g.err.CompareAndSwap(nil, &err) // first non-nil error wins
		}
	}()
}

// Wait blocks until every Go-launched goroutine exits, then returns the first
// error (or nil if none of them erred).
func (g *group) Wait() error {
	g.wg.Wait()
	if p := g.err.Load(); p != nil {
		return *p
	}
	return nil
}

// outcome is the observable result of one in-flight HTTP request. ok is false
// when the transport itself errored (e.g. EOF on Close) — i.e. no HTTP response
// was received at all.
type outcome struct {
	ok     bool
	status int
	body   string
	err    string
}

// doGet fires one GET against ts and sends the outcome on res (buffered). It is
// always run in a goroutine so a dropped connection (Close) cannot deadlock main.
func doGet(ts *httptest.Server, path string, res chan<- outcome) {
	resp, err := ts.Client().Get(ts.URL + path)
	if err != nil {
		res <- outcome{err: err.Error()}
		return
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	res <- outcome{ok: true, status: resp.StatusCode, body: string(b)}
}

// sectionA proves the core promise of http.Server.Shutdown: with one request
// in-flight, Shutdown stops accepting NEW connections, waits for the active
// handler to finish (up to the ctx deadline), then returns nil — and the
// in-flight request completes with a full HTTP 200 response, it is NOT dropped.
//
// handlerWork is a tiny FIXED duration. It is NEVER printed as an elapsed value
// (timing is non-deterministic); only the OUTCOME (err code, status, body) is.
// `started` is closed the instant the handler begins, so we KNOW the request is
// in-flight before we call Shutdown — this removes any startup race.
func sectionA() {
	sectionBanner("A — Shutdown drains an in-flight request (the core promise)")

	const handlerWork = 50 * time.Millisecond

	started := make(chan struct{}) // closed when the handler is provably running
	var handlerWrote atomic.Bool

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(started) // the request is now in-flight
		select {
		case <-time.After(handlerWork):
			handlerWrote.Store(true)
			w.WriteHeader(http.StatusOK)
			io.WriteString(w, "drained-ok")
		case <-r.Context().Done():
			return
		}
	}))

	res := make(chan outcome, 1)
	go doGet(ts, "/work", res)

	<-started // guarantee the request is in-flight BEFORE shutting down

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err := ts.Config.Shutdown(shutdownCtx)

	got := <-res

	fmt.Printf("server.Shutdown(ctx) with 1 in-flight request -> err = %v\n", err)
	fmt.Printf("in-flight request outcome: ok=%v status=%d body=%q\n", got.ok, got.status, got.body)
	fmt.Printf("handler ran to completion and wrote the response: %v\n", handlerWrote.Load())

	check("Shutdown returned nil (clean drain)", err == nil)
	check("in-flight request received HTTP 200 (not dropped)", got.ok && got.status == http.StatusOK)
	check("in-flight request body == \"drained-ok\"", got.body == "drained-ok")
	check("handler ran to completion (wrote the response)", handlerWrote.Load())
}

// sectionB contrasts Shutdown (drain) with Close (hard kill) on the SAME slow
// handler. Shutdown waits for the handler -> the client gets HTTP 200. Close
// tears down the connection immediately -> the handler's request context is
// cancelled, it never writes 200, and the client gets a transport error (EOF).
// This is the observable difference between graceful and forceful termination.
func sectionB() {
	sectionBanner("B — Shutdown (drain) vs Close (hard kill)")

	const handlerWork = 50 * time.Millisecond

	// --- Shutdown case: the request finishes with 200 ---
	shStarted := make(chan struct{})
	var shWrote atomic.Bool
	tsShutdown := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(shStarted)
		select {
		case <-time.After(handlerWork):
			shWrote.Store(true)
			w.WriteHeader(http.StatusOK)
			io.WriteString(w, "shutdown-ok")
		case <-r.Context().Done():
			return
		}
	}))

	shRes := make(chan outcome, 1)
	go doGet(tsShutdown, "/work", shRes)

	<-shStarted
	shutdownCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	shutdownErr := tsShutdown.Config.Shutdown(shutdownCtx)
	shutdownGot := <-shRes

	// --- Close case: the request is dropped mid-flight (client gets an error) ---
	clStarted := make(chan struct{})
	var clWrote atomic.Bool
	clExited := make(chan struct{})
	tsClose := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer close(clExited)
		close(clStarted)
		select {
		case <-time.After(handlerWork):
			clWrote.Store(true)
			w.WriteHeader(http.StatusOK)
			io.WriteString(w, "close-ok")
		case <-r.Context().Done():
			return // Close cancelled the request context -> handler bails, no 200
		}
	}))

	clRes := make(chan outcome, 1)
	go doGet(tsClose, "/work", clRes)

	<-clStarted
	closeErr := tsClose.Config.Close()
	closeGot := <-clRes
	<-clExited // the handler has exited (its request ctx was cancelled by Close)

	fmt.Printf("Shutdown: err=%v  request received-response=%v status=%d body=%q\n",
		shutdownErr, shutdownGot.ok, shutdownGot.status, shutdownGot.body)
	// The Close transport error (e.g. "Get \"http://127.0.0.1:<RANDOM>/work\": EOF")
	// embeds the random loopback port, so we print only the deterministic observable
	// (no HTTP response was received) — never the raw error string.
	fmt.Printf("Close:    err=%v  request received-response=%v  handler-wrote-200=%v\n",
		closeErr, closeGot.ok, clWrote.Load())

	check("Shutdown returned nil", shutdownErr == nil)
	check("Shutdown case: in-flight request finished with HTTP 200",
		shutdownGot.ok && shutdownGot.status == http.StatusOK)
	check("Close returned nil (it closes the listener)", closeErr == nil)
	check("Close case: in-flight request got NO response (dropped, transport error)", !closeGot.ok)
	check("Close case: handler did NOT write 200 (cut off mid-flight)", !clWrote.Load())
}

// sectionC shows cancellation propagation in isolation: a worker goroutine
// selects on ctx.Done(); calling cancel() closes Done() (🔗 CONTEXT), the worker
// observes it and records "cancelled". This is the primitive Shutdown and the
// full dance both build on. Deterministic: cancel() is synchronous; the worker's
// select immediately sees Done() ready.
func sectionC() {
	sectionBanner("C — context cancellation: cancel() -> worker exits and records 'cancelled'")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	workerOut := make(chan string, 1)
	go func() {
		select {
		case <-ctx.Done():
			workerOut <- "cancelled: " + ctx.Err().Error()
		case <-time.After(5 * time.Second): // never reached: we cancel immediately
			workerOut <- "ran to completion"
		}
	}()

	cancel() // THE trigger (simulates the root ctx being cancelled)
	msg := <-workerOut

	fmt.Printf("cancel() -> worker observed ctx.Done() and recorded: %q\n", msg)
	fmt.Printf("ctx.Err() after cancel = %v\n", ctx.Err())

	check("worker recorded 'cancelled' after cancel()", msg == "cancelled: context canceled")
	check("ctx.Err() == context.Canceled", ctx.Err() == context.Canceled)
}

// sectionD proves RegisterOnShutdown: a function registered BEFORE Shutdown is
// invoked when Shutdown begins (e.g. close a DB pool). Per net/http's source the
// registered hooks are launched with `go f()` at the start of Shutdown, so they
// run ASYNCHRONOUSLY — we wait on a channel to observe completion deterministically
// (a bare read of the flag right after Shutdown could race the hook goroutine).
func sectionD() {
	sectionBanner("D — RegisterOnShutdown: a hook fires when Shutdown begins")

	var hookRan atomic.Bool
	hookDone := make(chan struct{})

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))

	// Register a cleanup hook (e.g. "close the DB pool") BEFORE calling Shutdown.
	ts.Config.RegisterOnShutdown(func() {
		hookRan.Store(true)
		close(hookDone)
	})

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err := ts.Config.Shutdown(shutdownCtx)
	<-hookDone // hooks run async via `go f()` during Shutdown; wait for ours to land

	fmt.Printf("server.Shutdown err = %v\n", err)
	fmt.Printf("RegisterOnShutdown hook ran = %v\n", hookRan.Load())

	check("Shutdown returned nil", err == nil)
	check("RegisterOnShutdown hook fired (flag set)", hookRan.Load())
}

// sectionE is the FULL graceful-termination dance, stitched together:
//  1. signal.NotifyContext registers SIGINT/SIGTERM. We SIMULATE the OS signal
//     by calling stop() (in production the kubelet delivers SIGTERM and
//     NotifyContext cancels the ctx for us). No real signal is sent -> deterministic.
//  2. server.Shutdown(deadlineCtx) runs in a goroutine (stops new conns, drains).
//  3. a concurrent worker selects on the root ctx.Done() to bail.
//  4. the errgroup-equivalent (group) waits for Shutdown + worker to finish and
//     surfaces the first error.
//  5. a RegisterOnShutdown cleanup hook closes a "DB pool" when Shutdown begins.
func sectionE() {
	sectionBanner("E — Full dance: signal.NotifyContext (simulated) -> Shutdown + worker drain")

	// (1) The real API. We do NOT send a real OS signal; we SIMULATE SIGTERM by
	//     calling stop() below. stop() cancels this ctx exactly as SIGTERM would.
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// (5) cleanup hook: close a "DB pool" when Shutdown begins.
	var dbClosed atomic.Bool
	hookDone := make(chan struct{})

	// the server: a handler that honours request cancellation (the graceful contract).
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-time.After(10 * time.Millisecond):
			w.WriteHeader(http.StatusOK)
			io.WriteString(w, "ok")
		case <-r.Context().Done():
			http.Error(w, "shutting down", http.StatusServiceUnavailable)
		}
	}))
	ts.Config.RegisterOnShutdown(func() {
		dbClosed.Store(true)
		close(hookDone)
	})

	// (3) a concurrent worker that does periodic work and bails on ctx.Done().
	workerDone := make(chan struct{})
	workerMsg := make(chan string, 1)
	go func() {
		defer close(workerDone)
		ticker := time.NewTicker(5 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				workerMsg <- "drained: " + ctx.Err().Error()
				return
			case <-ticker.C:
				// a unit of background work (no-op; deterministic)
			}
		}
	}()

	// (1 cont.) SIMULATE the signal: stop() cancels the root ctx.
	stop()

	// (2)+(4) the dance: Shutdown + worker-drain, coordinated by the group.
	var g group
	g.Go(func() error {
		sctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		return ts.Config.Shutdown(sctx)
	})
	g.Go(func() error {
		<-workerDone // worker has drained and exited
		return nil
	})
	err := g.Wait()
	<-hookDone // wait for the async RegisterOnShutdown cleanup to land

	wmsg := <-workerMsg

	fmt.Printf("simulated signal (stop) -> server.Shutdown err = %v\n", err)
	fmt.Printf("worker drained on ctx.Done: %q\n", wmsg)
	fmt.Printf("RegisterOnShutdown cleanup hook ran (dbClosed) = %v\n", dbClosed.Load())
	fmt.Printf("root ctx.Err() after stop() = %v\n", ctx.Err())

	check("signal.NotifyContext ctx cancelled after stop()", ctx.Err() == context.Canceled)
	check("server.Shutdown returned nil (clean drain)", err == nil)
	check("worker drained with 'context canceled'", wmsg == "drained: context canceled")
	check("RegisterOnShutdown cleanup hook ran", dbClosed.Load())
}

// sectionF DOCUMENTS the Kubernetes graceful-termination timeline. It is NOT
// triggered here (a real pod lifecycle is environment-dependent); the canonical
// constants and the ordering are pinned from the k8s docs, and we assert the one
// invariant that matters for correctness: the Shutdown deadline must be SHORTER
// than terminationGracePeriodSeconds, leaving a safety margin (the preStop hook
// and Shutdown both count against the grace period).
func sectionF() {
	sectionBanner("F — Kubernetes graceful-termination timeline (DOCUMENTED)")

	const (
		terminationGracePeriodSeconds = 30 // k8s default (DOCUMENTED)
		shutdownDeadlineSeconds       = 25 // recommended: leave a safety margin
		safetyMarginSeconds           = terminationGracePeriodSeconds - shutdownDeadlineSeconds
	)

	fmt.Println("k8s graceful-termination sequence (DOCUMENTED, not triggered here):")
	fmt.Println("  1. kubelet sends SIGTERM to the pod's process (PID 1).")
	fmt.Println("  2. App: signal.NotifyContext cancels root ctx -> stop accepting new requests,")
	fmt.Println("     drain in-flight handlers via server.Shutdown(deadlineCtx).")
	fmt.Println("  3. kubelet waits up to terminationGracePeriodSeconds (default 30s) for exit.")
	fmt.Println("  4. If still alive, kubelet sends SIGKILL (uncatchable) -> hard kill.")
	fmt.Printf("recommended: Shutdown deadline (%ds) < grace period (%ds); margin = %ds\n",
		shutdownDeadlineSeconds, terminationGracePeriodSeconds, safetyMarginSeconds)
	fmt.Println("note: the preStop hook AND Shutdown both count against the grace period.")

	check("recommended Shutdown deadline < k8s grace period", shutdownDeadlineSeconds < terminationGracePeriodSeconds)
	check("safety margin is positive", safetyMarginSeconds > 0)
}

func main() {
	fmt.Println("graceful_shutdown.go — Phase 8 bundle (production patterns).")
	fmt.Println("Every value below is produced by this file; the .md guide pastes it verbatim.")
	fmt.Println("No real OS signal is sent — the trigger is SIMULATED (stop()/Shutdown/Close")
	fmt.Println("called directly). httptest runs on loopback; no elapsed time is printed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
