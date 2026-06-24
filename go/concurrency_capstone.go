//go:build ignore

// concurrency_capstone.go — Phase 8 bundle (the concurrency SYNTHESIS / capstone).
//
// GOAL (one line): show, by running ONE realistic program, how a BOUNDED
// CONCURRENT FETCHER composes the Phase-3 primitives (goroutines, channels,
// select, the errgroup-equivalent) with the Phase-8 production patterns
// (context cancellation, a real token-bucket rate limiter, graceful shutdown)
// into a system with bounded concurrency, first-error-wins error propagation,
// and a clean drain.
//
// This is the GROUND TRUTH for CONCURRENCY_CAPSTONE.md. Every number, set, and
// error below is computed by this file; the .md guide pastes it verbatim. Never
// hand-compute.
//
// DETERMINISM (critical — see HOW_TO_RESEARCH.md §4.2):
//   - NO goroutine ever prints. Every worker writes results into a mutex-free
//     channel (or an atomic counter); main collects, SORTS, and prints only
//     AFTER every goroutine joins. No raw interleaving, no per-worker identity,
//     no scheduling order is ever asserted or printed.
//   - The fake upstream `fetch` is a pure function of (id, failingID, payloads):
//     deterministic. Payloads and the failing id are derived from a SEEDED RNG
//     (math/rand/v2 PCG, fixed seeds), so every printed value is reproducible.
//   - The rate limiter uses a HIGH finite rate (rate.Limit(10000)) so work is
//     never bottlenecked on wall-clock; we assert STRUCTURAL facts
//     (limiterWaits == fetchesInvoked) rather than timings.
//   - Cancellation sections assert BOUNDS (1 <= completed <= N) and the captured
//     first error — never the exact count of jobs that raced the cancel signal
//     (that count is scheduler-dependent). Two `just out` runs are byte-identical.
//
// STDLIB-FIRST + one allowed dep: only the stdlib + golang.org/x/time/rate (in
// go.mod) are used. The errgroup-equivalent is reimplemented from scratch (NOT
// imported) per the golang.org/x/sync/errgroup design — first-error-wins via
// atomic.Pointer[error] + CompareAndSwap, plus WithContext-style cancel-on-error.
//
// Run:
//
//	go run concurrency_capstone.go
//
// RACE-CHECK: this file ships only DATA-RACE-FREE code; verify with
//
//	go run -race concurrency_capstone.go
//
// (it must report nothing).

package main

import (
	"context"
	"fmt"
	"math/rand/v2"
	"runtime"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"golang.org/x/time/rate"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

// highRate is a finite rate high enough that the limiter never bottlenecks the
// test on wall-clock, while still being a REAL rate.NewLimiter (every fetch
// goes through lim.Wait). Asserted structurally (waits == fetches), never timed.
const highRate rate.Limit = 10000

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

// --- errgroup-equivalent (built from scratch; mirrors golang.org/x/sync/errgroup) ---
//
// golang.org/x/sync/errgroup.Group is "related to sync.WaitGroup but adds
// handling of tasks returning errors" (pkg.go.dev). We reimplement its core:
//
//   - Go(f) launches f in a goroutine tracked by a WaitGroup.
//   - The FIRST non-nil error wins (atomic.Pointer[error] + CompareAndSwap).
//   - WithContext(ctx) derives a child ctx that is CANCELLED the first time a Go
//     function returns a non-nil error OR the first time Wait returns
//     (errgroup.WithContext semantics) — so an error in one goroutine fans out
//     as ctx.Done() to every other goroutine selecting on it.
//
// This is the natural coordinator for the fetcher: run W workers + a dispatcher
// under one Group; bail the whole tree on the first upstream failure.

// group is an errgroup-equivalent: a set of goroutines whose first error is kept.
// A zero group (cancel == nil) behaves like errgroup.Group{} (no ctx, no cancel).
type group struct {
	wg     sync.WaitGroup
	err    atomic.Pointer[error]
	cancel context.CancelFunc // optional; set by withContext (errgroup.WithContext)
}

// withContext mirrors errgroup.WithContext: it derives a cancellable child of ctx
// and returns a Group that cancels that child on the first non-nil error (or when
// Wait returns). The returned CancelFunc is safe to defer in the caller.
func withContext(ctx context.Context) (*group, context.Context, context.CancelFunc) {
	ctx, cancel := context.WithCancel(ctx)
	return &group{cancel: cancel}, ctx, cancel
}

// Go launches f in a new goroutine tracked by the WaitGroup. If f returns a
// non-nil error, it is stored only if none was stored before (first error wins),
// and — when the Group has an associated context — that first store also cancels
// the context (broadcasting ctx.Done() to every peer).
func (g *group) Go(f func() error) {
	g.wg.Add(1)
	go func() {
		defer g.wg.Done()
		if err := f(); err != nil {
			if g.err.CompareAndSwap(nil, &err) && g.cancel != nil {
				g.cancel() // cancel on the FIRST error only (errgroup.WithContext)
			}
		}
	}()
}

// Wait blocks until every Go-launched goroutine exits, cancels the associated
// context (if any — errgroup cancels when Wait returns), and returns the first
// non-nil error (or nil if none erred). Safe to call more than once.
func (g *group) Wait() error {
	g.wg.Wait()
	if g.cancel != nil {
		g.cancel()
	}
	if p := g.err.Load(); p != nil {
		return *p
	}
	return nil
}

// --- the fake upstream fetch + its job stream ---------------------------------
//
// fetch is the shared primitive every section composes. It models "call an
// upstream that can fail": it rate-limits via lim.Wait(ctx) (honoring
// cancellation), counts the wait atomically, then returns either the seeded
// payload for id or an injected, deterministic error when id == failingID.
// failingID < 0 means "no injected failure". No real network, no wall-clock
// dependence in any printed value.
func fetch(ctx context.Context, id, failingID int, lim *rate.Limiter, payloads []int, limWaits *int64) (int, error) {
	if err := lim.Wait(ctx); err != nil {
		return 0, fmt.Errorf("limiter wait: %w", err)
	}
	atomic.AddInt64(limWaits, 1)
	if id == failingID {
		return 0, fmt.Errorf("fetch id=%d: injected upstream failure", id)
	}
	return payloads[id], nil
}

// sectionA introduces the two atoms every later section composes: the JOB STREAM
// (ids 0..N-1 with seeded payloads) and the FAKE FETCH (healthy id -> payload;
// the failing id -> an injected error). It isolates fetch's behavior so later
// sections can compose it without re-explaining it.
func sectionA() {
	sectionBanner("A — The fetch primitive & the job stream")

	const N = 8
	rng := rand.New(rand.NewPCG(42, 42))
	payloads := make([]int, N)
	for i := range payloads {
		payloads[i] = rng.IntN(100000)
	}
	const failingID = 3

	// The JOB STREAM: ids 0..N-1 (a generator would emit these onto a channel;
	// here we materialize the slice to assert its shape before plumbing it).
	jobs := make([]int, N)
	for i := range jobs {
		jobs[i] = i
	}

	lim := rate.NewLimiter(rate.Inf, 1) // unlimited: section A isolates fetch semantics
	var limWaits int64

	okPayload, okErr := fetch(context.Background(), 1, failingID, lim, payloads, &limWaits)
	failPayload, failErr := fetch(context.Background(), failingID, failingID, lim, payloads, &limWaits)

	fmt.Printf("job stream: %d jobs (ids 0..%d); seeded payloads (math/rand/v2 PCG seed 42,42)\n", N, N-1)
	fmt.Printf("fetch(id=1, healthy)  -> payload=%d, err=%v\n", okPayload, okErr)
	fmt.Printf("fetch(id=%d, failing) -> payload=%d, err=%v\n", failingID, failPayload, failErr)
	check("job stream has exactly N=8 jobs", len(jobs) == N)
	check("fetch of a healthy id returns nil error", okErr == nil)
	check("fetch of a healthy id returns its seeded payload", okPayload == payloads[1])
	check("fetch of the failing id returns the injected error", failErr != nil)
	check("the injected error names the failing id", failErr != nil && strings.Contains(failErr.Error(), "id=3"))
	check("each fetch went through lim.Wait (2 waits for 2 fetches)", limWaits == 2)
}

// sectionB is the errgroup-equivalent in isolation (mirrors the JustErrors
// example in pkg.go.dev/golang.org/x/sync/errgroup): three funcs, one returns an
// error; Wait blocks until ALL exit and returns that first (and only) error.
func sectionB() {
	sectionBanner("B — errgroup-equivalent: Go/Wait, first-error-wins")

	var (
		g   group // zero group: no ctx, no cancel (plain first-error-wins)
		ran int64
	)
	g.Go(func() error { atomic.AddInt64(&ran, 1); return nil })
	g.Go(func() error { atomic.AddInt64(&ran, 1); return fmt.Errorf("boom: stage 2 failed") })
	g.Go(func() error { atomic.AddInt64(&ran, 1); return nil })

	err := g.Wait()

	fmt.Println("errgroup-equivalent: 3 funcs launched (one returns an error)")
	fmt.Printf("all %d/3 funcs ran (Wait blocks until EVERY goroutine exits)\n", atomic.LoadInt64(&ran))
	fmt.Printf("Wait() error: %v\n", err)
	check("all 3 funcs ran (Wait blocks until every goroutine exits)", atomic.LoadInt64(&ran) == 3)
	check("Wait() returned a non-nil error", err != nil)
	check("Wait() error is the injected first error", err != nil && err.Error() == "boom: stage 2 failed")
}

// sectionC composes a BOUNDED WORKER POOL with a RATE LIMITER: W=4 workers drain
// a shared jobs channel; each fetch is gated by lim.Wait (a real token bucket).
// No job fails, so the sorted result set is exactly all N payloads regardless of
// which worker handled which job (the per-job split is nondeterministic; the SET
// is not). This is the fan-out + back-pressure core of the fetcher.
func sectionC() {
	sectionBanner("C — Bounded worker pool + rate limiter (fan-out, no failure)")

	const (
		N = 12
		W = 4
	)
	rng := rand.New(rand.NewPCG(7, 7))
	payloads := make([]int, N)
	for i := range payloads {
		payloads[i] = rng.IntN(100000)
	}

	lim := rate.NewLimiter(highRate, W) // real limiter, high rate: structural assert only
	var limWaits int64

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	jobs := make(chan int, N)    // buffered: enqueue all up front, then close
	results := make(chan int, N) // workers -> main

	var wg sync.WaitGroup
	wg.Add(W)
	for range W {
		go func() {
			defer wg.Done()
			for id := range jobs { // exits when `jobs` is closed
				if p, err := fetch(ctx, id, -1, lim, payloads, &limWaits); err == nil {
					results <- p
				}
			}
		}()
	}
	go func() { wg.Wait(); close(results) }() // close only after every send is done

	for i := range N { // dispatch all jobs, then close so the ranges end
		jobs <- i
	}
	close(jobs)

	got := make([]int, 0, N)
	for p := range results {
		got = append(got, p)
	}
	slices.Sort(got)

	expected := append([]int(nil), payloads...)
	slices.Sort(expected)

	fmt.Printf("bounded pool: %d workers, %d jobs, rate=%v tokens/sec burst=%d (no failure)\n",
		W, N, highRate, W)
	fmt.Printf("collected %d payloads (sorted) -> %v\n", len(got), got)
	check("pool processed all 12 jobs (12 payloads collected)", len(got) == N)
	check("sorted result set == all N payloads (set is scheduler-independent)",
		fmt.Sprint(got) == fmt.Sprint(expected))
	check("every fetch went through lim.Wait (limWaits == fetches == N)",
		atomic.LoadInt64(&limWaits) == int64(N))
}

// sectionD exercises CANCELLATION ON FIRST ERROR: the failing job is dispatched
// first; the worker that hits it returns the error, which the Group stores
// (first-error-wins) and uses to cancel the derived ctx. The dispatcher stops
// feeding (its send selects on ctx.Done()); the other workers bail on ctx.Done().
// The exact number of fetches that raced the cancel signal is scheduler-
// dependent, so we assert the BOUND (1 <= fetchesInvoked <= N) and the captured
// first error — never the count.
func sectionD() {
	sectionBanner("D — Cancellation on first error (errgroup.WithContext semantics)")

	const (
		N         = 12
		W         = 4
		failingID = 0 // the FIRST job dispatched fails -> cancel fans out ASAP
	)
	rng := rand.New(rand.NewPCG(7, 7))
	payloads := make([]int, N)
	for i := range payloads {
		payloads[i] = rng.IntN(100000)
	}

	lim := rate.NewLimiter(highRate, W)
	var (
		limWaits       int64
		fetchesInvoked int64
	)

	// errgroup.WithContext: the derived ctx is cancelled on the first non-nil
	// error returned by any Go func (or when Wait returns).
	g, ctx, cancel := withContext(context.Background())
	defer cancel()

	jobs := make(chan int)    // unbuffered: dispatcher feeds one at a time, honoring ctx
	results := make(chan int) // workers -> main (rendezvous with the collector)

	// Dispatcher (group-tracked): feed ids 0..N-1, bailing on ctx.Done().
	g.Go(func() error {
		defer close(jobs)
		for i := 0; i < N; i++ {
			select {
			case jobs <- i:
			case <-ctx.Done():
				return nil // ctx already cancelled by the originator; stop feeding
			}
		}
		return nil
	})

	// W workers (group-tracked): each returns its fetch error (first one wins +
	// cancels ctx); otherwise drains jobs until closed or ctx.Done().
	for range W {
		g.Go(func() error {
			for {
				select {
				case <-ctx.Done():
					return nil
				case id, ok := <-jobs:
					if !ok {
						return nil
					}
					atomic.AddInt64(&fetchesInvoked, 1)
					p, err := fetch(ctx, id, failingID, lim, payloads, &limWaits)
					if err != nil {
						return err // first non-nil error wins + cancels ctx
					}
					select {
					case results <- p:
					case <-ctx.Done():
						return nil
					}
				}
			}
		})
	}

	// Closer: once every group goroutine exits, close results so the range ends.
	go func() { g.Wait(); close(results) }()

	got := make([]int, 0, N)
	for p := range results { // drains until closed (workers exited)
		got = append(got, p)
	}
	slices.Sort(got)
	err := g.Wait() // first (and only) error captured; safe to call again after the closer

	fmt.Printf("cancellation: failing id=%d (first dispatched), %d workers, ctx from errgroup.WithContext\n",
		failingID, W)
	fmt.Printf("first error captured by Wait(): %v\n", err)
	fmt.Println("(fetches that raced the cancel signal are scheduler-dependent; asserting bounds only)")
	check("Wait() returned a non-nil error (first error captured)", err != nil)
	check("the captured error is the injected failure for id=0",
		err != nil && strings.Contains(err.Error(), "id=0"))
	check("completed fetches bounded: 1 <= fetchesInvoked <= N",
		atomic.LoadInt64(&fetchesInvoked) >= 1 && atomic.LoadInt64(&fetchesInvoked) <= int64(N))
}

// sectionE demonstrates GRACEFUL DRAIN: a generator feeds a long stream honoring
// ctx; W workers fetch each item; the collector takes a few results and then
// cancels (the shutdown trigger). On cancel the generator stops feeding, workers
// stop pulling, the results channel drains whatever was in flight, and the pool
// WaitGroup joins. The exact count drained is scheduler-dependent, so we assert
// bounds (>= a few, well below the stream cap) and that the drain completed.
func sectionE() {
	sectionBanner("E — Graceful drain: cancel stops the stream, pool joins cleanly")

	const (
		streamCap = 1000 // generator's natural end (cancel stops it far earlier)
		W         = 3
		take      = 5 // results the collector accepts before triggering shutdown
	)
	lim := rate.NewLimiter(highRate, W)
	payloads := make([]int, streamCap) // values irrelevant here; fetch still returns them

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	jobs := make(chan int)    // unbuffered: generator -> workers
	results := make(chan int) // unbuffered: workers -> collector

	var poolWg sync.WaitGroup

	// Generator: emit 0..streamCap-1, honoring ctx (closes jobs on exit).
	poolWg.Add(1)
	go func() {
		defer poolWg.Done()
		defer close(jobs)
		for i := 0; i < streamCap; i++ {
			select {
			case jobs <- i:
			case <-ctx.Done():
				return
			}
		}
	}()

	// W workers, each honoring ctx.Done() on both receive and send.
	poolWg.Add(W)
	for range W {
		go func() {
			defer poolWg.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case id, ok := <-jobs:
					if !ok {
						return
					}
					p, err := fetch(ctx, id, -1, lim, payloads, new(int64))
					if err != nil {
						return
					}
					select {
					case results <- p:
					case <-ctx.Done():
						return
					}
				}
			}
		}()
	}

	// Closer: once generator + workers all exit, close results.
	go func() { poolWg.Wait(); close(results) }()

	// Collector: accept `take` results, then trigger graceful shutdown.
	drained := 0
	for range results {
		drained++
		if drained == take {
			cancel() // shutdown trigger
		}
	}

	fmt.Printf("graceful drain: generator feeds up to %d, %d workers; collector takes %d then cancels\n",
		streamCap, W, take)
	fmt.Println("(drained count is scheduler-dependent; asserting bounds only)")
	check("at least the requested results drained before cancel", drained >= take)
	check("drain stopped far below streamCap (cancel stopped the generator)", drained < streamCap)
}

// sectionF is the FULL SYSTEM + METRICS: N jobs, W workers, a real rate limiter,
// and exactly one injected failure (seeded id). All jobs run (no cancel-on-error
// here — the cancel path is section D); the Group captures the single error via
// first-error-wins while the rest succeed. Asserts: the successful result SET
// (sorted) == all ids except the failing one; the first error is captured; every
// fetch went through lim.Wait; and runtime.NumGoroutine returns to ~baseline
// after Wait (no goroutine leak).
func sectionF() {
	sectionBanner("F — The full system: pool + rate limiter + errgroup + metrics")

	const (
		N = 16
		W = 4
	)
	rng := rand.New(rand.NewPCG(99, 99))
	payloads := make([]int, N)
	for i := range payloads {
		payloads[i] = rng.IntN(100000)
	}
	failingID := rng.IntN(N) // seeded: deterministic single injected failure

	lim := rate.NewLimiter(highRate, W)
	var (
		limWaits       int64
		fetchesInvoked int64
	)

	baseline := runtime.NumGoroutine()

	var g group // plain group: run ALL jobs; first error captured, no cancel-on-error
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	jobs := make(chan int, N)    // pre-fill all jobs, then close
	results := make(chan int, N) // workers -> main
	for i := range N {
		jobs <- i
	}
	close(jobs)

	// W group-tracked workers; the one that hits failingID returns its error
	// (first-error-wins), the others keep draining the shared jobs channel.
	for range W {
		g.Go(func() error {
			for id := range jobs {
				atomic.AddInt64(&fetchesInvoked, 1)
				p, err := fetch(ctx, id, failingID, lim, payloads, &limWaits)
				if err != nil {
					return err
				}
				results <- p
			}
			return nil
		})
	}
	go func() { g.Wait(); close(results) }() // close results after all workers exit

	got := make([]int, 0, N)
	for p := range results {
		got = append(got, p)
	}
	slices.Sort(got)
	err := g.Wait()

	// Expected successful set: every payload except the failing id's, sorted.
	expected := make([]int, 0, N-1)
	for i := 0; i < N; i++ {
		if i != failingID {
			expected = append(expected, payloads[i])
		}
	}
	slices.Sort(expected)

	// Give the runtime a moment to reap exited goroutines before the leak check.
	time.Sleep(5 * time.Millisecond)
	after := runtime.NumGoroutine()

	fmt.Printf("full system: N=%d jobs, W=%d workers, rate=%v tokens/sec, one injected failure at id=%d\n",
		N, W, highRate, failingID)
	fmt.Printf("successful payloads (sorted) -> %v\n", got)
	fmt.Printf("first error captured         -> %v\n", err)
	fmt.Printf("metrics: fetchesInvoked=%d, limWaits=%d (NumGoroutine counts runtime-dependent, not printed)\n",
		atomic.LoadInt64(&fetchesInvoked), atomic.LoadInt64(&limWaits))
	check("all N fetches invoked (jobs channel fully drained)", atomic.LoadInt64(&fetchesInvoked) == int64(N))
	check("every fetch went through lim.Wait (limWaits == fetches == N)",
		atomic.LoadInt64(&limWaits) == int64(N))
	check("successful result set == all ids except the failing one (sorted)",
		fmt.Sprint(got) == fmt.Sprint(expected))
	check("exactly N-1 successes (one injected failure)", len(got) == N-1)
	check("Wait() returned the injected error for the failing id",
		err != nil && strings.Contains(err.Error(), fmt.Sprintf("id=%d", failingID)))
	check("no goroutine leak (NumGoroutine within baseline+3 after Wait)", after <= baseline+3)
}

func main() {
	fmt.Println("concurrency_capstone.go — Phase 8 bundle (the concurrency synthesis).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes it verbatim.")
	fmt.Println("No goroutine prints; results are collected, SORTED, and printed from main after")
	fmt.Println("every goroutine joins -> byte-identical runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
