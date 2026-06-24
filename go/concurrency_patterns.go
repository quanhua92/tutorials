//go:build ignore

// concurrency_patterns.go — Phase 3 bundle (concurrency patterns).
//
// GOAL (one line): show, by printing every value, the production concurrency
// patterns built on goroutines + channels — worker pool, pipeline, generator,
// fan-out/fan-in, semaphore (buffered channel), done-channel cancellation, and
// an errgroup-equivalent built from scratch with sync + sync/atomic.
//
// This is the GROUND TRUTH for CONCURRENCY_PATTERNS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// DETERMINISM (critical for this bundle): goroutine scheduling is intentionally
// nondeterministic, so NO goroutine ever prints. Every worker writes its result
// into a channel (or a shared slice); main collects, SORTS, and prints only
// AFTER all goroutines join (sync.WaitGroup or close-of-results). No raw
// interleaving, no per-worker identity, no timing value is ever printed. Two
// runs of `just out concurrency_patterns` are byte-identical.
//
// STDLIB-FIRST: only sync + sync/atomic are used. The errgroup pattern is
// reimplemented from scratch (NOT imported) per the golang.org/x/sync/errgroup
// design — first-error-wins via atomic.Pointer[error].
//
// Run:
//
//	go run concurrency_patterns.go

package main

import (
	"fmt"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
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

// --- pipeline / generator / fan-in helpers (go.dev/blog/pipelines) -----------
//
// Each helper takes a `done` receive-channel so the whole graph can be torn down
// by closing `done` (a closed channel is always ready to receive -> every
// select-on-done bails out). Sections that drain to completion never trigger it;
// section E exercises it explicitly.

// gen is a GENERATOR: it returns a channel and starts a goroutine that emits the
// given values in order, then closes the channel. This is the "source" stage of
// a pipeline — a function that produces a stream.
func gen(done <-chan struct{}, nums ...int) <-chan int {
	out := make(chan int)
	go func() {
		defer close(out)
		for _, n := range nums {
			select {
			case out <- n:
			case <-done:
				return
			}
		}
	}()
	return out
}

// square is a pipeline STAGE: it reads ints from `in`, squares each, and sends
// the result on `out`, closing `out` when `in` is closed. Stages compose because
// they share the channel type (<-chan int -> <-chan int).
func square(done <-chan struct{}, in <-chan int) <-chan int {
	out := make(chan int)
	go func() {
		defer close(out)
		for n := range in {
			select {
			case out <- n * n:
			case <-done:
				return
			}
		}
	}()
	return out
}

// merge is FAN-IN: it multiplexes many input channels onto one output channel,
// closing `out` after every input is closed. One forwarder goroutine per input
// copies values across; a WaitGroup tracks them; a final goroutine closes `out`
// once they all exit (sends on a closed channel panic, so close must come last).
func merge(done <-chan struct{}, cs ...<-chan int) <-chan int {
	var wg sync.WaitGroup
	out := make(chan int)
	forward := func(c <-chan int) {
		defer wg.Done()
		for n := range c {
			select {
			case out <- n:
			case <-done:
				return
			}
		}
	}
	wg.Add(len(cs))
	for _, c := range cs {
		go forward(c)
	}
	go func() {
		wg.Wait()
		close(out)
	}()
	return out
}

// --- errgroup-equivalent (built from scratch; stdlib only) -------------------
//
// This mirrors golang.org/x/sync/errgroup.Group: Go(f) launches a goroutine and
// tracks it; Wait() blocks until all of them exit and returns the FIRST non-nil
// error. The "first-error-wins" rule is implemented with an atomic.Pointer[error]
// and a CompareAndSwap(nil, &err) — only the first storer wins. No golang.org/x
// import is needed (stdlib-first).

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

// sectionA runs a WORKER POOL: 4 worker goroutines drain a shared `jobs` channel
// and write squares to a shared `results` channel. The dispatcher enqueues 8
// jobs (0..7) and closes `jobs`; a closer goroutine closes `results` once all
// workers exit (signalled by a WaitGroup). Which worker handles which job is
// nondeterministic, so main collects ALL results, SORTS them, and asserts the
// SET is exactly [0 1 4 9 16 25 36 49] regardless of the per-worker split.
func sectionA() {
	sectionBanner("A — Worker pool: N workers drain a shared jobs channel")

	const (
		numWorkers = 4
		numJobs    = 8
	)
	jobs := make(chan int, numJobs) // buffered: enqueue all up front, then close
	results := make(chan int)       // unbuffered: workers -> main

	// Start numWorkers workers, each draining `jobs` until it is closed.
	var wg sync.WaitGroup
	wg.Add(numWorkers)
	for range numWorkers {
		go func() {
			defer wg.Done()
			for j := range jobs { // exits when `jobs` is closed
				results <- j * j
			}
		}()
	}

	// Closer: once every worker has finished, close `results` so the range below
	// terminates. (Sends on a closed channel panic -> close only after all sends
	// are done; the WaitGroup guarantees exactly that.)
	go func() {
		wg.Wait()
		close(results)
	}()

	// Dispatcher: enqueue all jobs, then close `jobs` so the workers' ranges end.
	for j := range numJobs {
		jobs <- j
	}
	close(jobs)

	// Collect (order is nondeterministic), then SORT for stable output.
	got := make([]int, 0, numJobs)
	for r := range results {
		got = append(got, r)
	}
	slices.Sort(got)

	fmt.Printf("worker pool: %d workers drain %d jobs (j*j): chan jobs -> chan results\n", numWorkers, numJobs)
	fmt.Printf("collected %d results, sorted -> %v\n", len(got), got)
	check("worker pool produced exactly 8 results", len(got) == numJobs)
	check("sorted worker-pool results == [0 1 4 9 16 25 36 49]",
		fmt.Sprint(got) == "[0 1 4 9 16 25 36 49]")
}

// sectionB composes a 3-stage PIPELINE: gen -> square -> main-consumer. Each
// stage is its own goroutine connected by channels; there is NO shared mutable
// state. A single goroutine per stage means values arrive in order, so the
// stream is deterministic: gen(0,1,2,3) -> square -> [0 1 4 9].
func sectionB() {
	sectionBanner("B — Pipeline: gen -> square -> collect (channels, no shared state)")

	done := make(chan struct{})
	defer close(done) // safety net: never fires here (the pipeline drains fully)

	// Compose stages by passing one stage's output channel as the next's input.
	out := square(done, gen(done, 0, 1, 2, 3))

	got := make([]int, 0, 4)
	for v := range out { // gen closed -> square closed -> this range ends
		got = append(got, v)
	}

	fmt.Println("pipeline: gen(0,1,2,3) emits a stream -> square(n*n) -> main ranges the output")
	fmt.Printf("collected stream (in order, single stage) -> %v\n", got)
	check("pipeline gen->square produced [0 1 4 9]", fmt.Sprint(got) == "[0 1 4 9]")
}

// sectionC demonstrates FAN-OUT / FAN-IN. A single source (gen of 0..7) is
// consumed by THREE `square` workers that all read from the SAME `in` channel
// (fan-out: distributing work). Each worker writes to its OWN output channel;
// `merge` fans those back into one channel (fan-in). The per-value -> worker
// assignment is nondeterministic, so main collects, SORTS, and asserts the SET
// equals [0 1 4 9 16 25 36 49].
func sectionC() {
	sectionBanner("C — Fan-out / Fan-in: split across workers, merge results")

	done := make(chan struct{})
	defer close(done)

	in := gen(done, 0, 1, 2, 3, 4, 5, 6, 7)

	// FAN-OUT: 3 sq workers, each reading from the SAME `in` channel.
	const workers = 3
	outs := make([]<-chan int, workers)
	for w := range workers {
		outs[w] = square(done, in)
	}

	// FAN-IN: merge all worker outputs onto a single channel.
	merged := merge(done, outs...)

	got := make([]int, 0, 8)
	for v := range merged {
		got = append(got, v)
	}
	slices.Sort(got)

	fmt.Printf("fan-out: %d sq workers read the same `in`; fan-in: merge -> one channel\n", workers)
	fmt.Printf("collected %d results, sorted -> %v\n", len(got), got)
	check("fan-out/fan-in produced exactly 8 results", len(got) == 8)
	check("sorted fan-out/fan-in results == [0 1 4 9 16 25 36 49]",
		fmt.Sprint(got) == "[0 1 4 9 16 25 36 49]")
}

// sectionD implements a SEMAPHORE with a buffered channel: a `chan struct{}` of
// capacity N. Acquire = send (blocks while N goroutines hold a slot); release =
// receive. This bounds concurrency to N without a sync.Mutex. To prove the bound
// deterministically we count in-flight goroutines with atomics and assert the
// observed peak is <= N. (The raw peak is NOT printed — it depends on scheduling;
// only the invariant peak <= N is, and that always holds.)
func sectionD() {
	sectionBanner("D — Semaphore via buffered channel: bound concurrency to N")

	const (
		semCap      = 3
		goroutines  = 10
		workPerCall = 1000
	)
	sem := make(chan struct{}, semCap) // capacity N == max concurrent holders

	var (
		inFlight int64 // # goroutines currently between acquire and release
		peak     int64 // max inFlight ever observed
		total    int64 // sum of token work (proves every goroutine ran)
		wg       sync.WaitGroup
	)
	wg.Add(goroutines)
	for range goroutines {
		go func() {
			defer wg.Done()

			sem <- struct{}{} // ACQUIRE: send blocks while `semCap` slots are held

			cur := atomic.AddInt64(&inFlight, 1)
			for { // lock-free peak = max(peak, cur)
				p := atomic.LoadInt64(&peak)
				if cur <= p || atomic.CompareAndSwapInt64(&peak, p, cur) {
					break
				}
			}

			// token work held inside the slot to exercise the bound
			var acc int64
			for k := int64(0); k < workPerCall; k++ {
				acc += k
			}
			atomic.AddInt64(&total, acc)

			atomic.AddInt64(&inFlight, -1)
			<-sem // RELEASE: receive frees a slot for a waiting goroutine
		}()
	}
	wg.Wait()

	expectedTotal := int64(goroutines) * int64(workPerCall-1) * int64(workPerCall) / 2 // 10 * sum(0..999)
	fmt.Printf("semaphore: chan struct{} cap=%d gates %d goroutines (acquire=send, release=<-sem)\n", semCap, goroutines)
	fmt.Println("invariant: at most `semCap` goroutines hold a slot at once (peak counted via atomics, not printed)")
	fmt.Printf("token work: %d goroutines * sum(0..%d) = %d\n", goroutines, workPerCall-1, atomic.LoadInt64(&total))
	check("peak in-flight <= semaphore cap (3)", atomic.LoadInt64(&peak) <= int64(semCap))
	check("peak in-flight >= 1 (the semaphore was exercised)", atomic.LoadInt64(&peak) >= 1)
	check("token work total == 10 * sum(0..999) = 4995000 (all goroutines ran)",
		atomic.LoadInt64(&total) == expectedTotal)
}

// sectionE demonstrates DONE-CHANNEL cancellation: a `done <-chan struct{}` is
// passed to the producer; closing `done` BROADCASTS "stop" (a closed channel is
// always ready to receive) and the producer's select-on-done bails out. Main
// takes only K=4 values from a stream that would otherwise reach 50, then closes
// `done`. The producer emits EXACTLY K values: the channel is UNBUFFERED, so
// every successful send needs a paired receive, and main performs exactly K of
// them (a counted loop — no select, hence no race between receiving a K+1th
// value and observing `done`). This is the primitive preview of `context`.
func sectionE() {
	sectionBanner("E — Done-channel cancellation: close(done) broadcasts stop")

	done := make(chan struct{})
	const (
		streamCap = 50 // producer's natural end (cancellation stops it well before)
		take      = 4
	)

	var (
		emitted int // written only by the producer goroutine
		wg      sync.WaitGroup
	)
	stream := make(chan int)
	wg.Add(1)
	go func() { // a stream GENERATOR (0..streamCap-1) honouring cancellation
		defer wg.Done()
		defer close(stream)
		for v := 0; v < streamCap; v++ {
			select {
			case stream <- v:
				emitted++
			case <-done:
				return
			}
		}
	}()

	// Take EXACTLY `take` values via a counted receive (no select here, so there
	// is no race between receiving and observing `done`), THEN broadcast cancel.
	got := make([]int, 0, take)
	for i := 0; i < take; i++ {
		got = append(got, <-stream) // rendezvous with the producer's send
	}
	close(done) // BROADCAST: the producer's <-done case becomes ready immediately
	wg.Wait()   // producer has exited; `emitted` is now safe to read (happens-before)

	fmt.Printf("producer emits 0..%d until cancelled; main takes only %d then closes done\n", streamCap-1, take)
	fmt.Printf("received (in order) -> %v\n", got)
	fmt.Printf("producer emitted exactly %d value(s) then stopped (cancellation worked)\n", emitted)
	check("main received exactly take=4 values", len(got) == take)
	check("received stream == [0 1 2 3] (order preserved)", fmt.Sprint(got) == "[0 1 2 3]")
	check("producer emitted exactly 4 (== taken), not more", emitted == take)
	check("producer stopped early (4 < natural cap 50) => cancellation fired", emitted < streamCap)
}

// sectionF runs three functions under the errgroup-equivalent: two succeed, one
// returns an error. Wait() returns that (first, and only) error. Because exactly
// one function errors, the message is deterministic regardless of scheduling;
// Wait() still blocks until ALL three have exited (it never abandons goroutines).
func sectionF() {
	sectionBanner("F — errgroup-equivalent: Wait() returns the first error")

	var (
		g   group
		ran int64 // # funcs that actually ran (all three should)
	)
	g.Go(func() error {
		atomic.AddInt64(&ran, 1)
		return nil
	})
	g.Go(func() error {
		atomic.AddInt64(&ran, 1)
		return fmt.Errorf("boom: stage 2 failed")
	})
	g.Go(func() error {
		atomic.AddInt64(&ran, 1)
		return nil
	})

	err := g.Wait()

	fmt.Println("errgroup-equivalent: 3 funcs launched (one returns an error)")
	fmt.Printf("all %d/3 funcs ran to completion (Wait blocks until EVERY goroutine exits)\n", ran)
	fmt.Printf("Wait() error: %v\n", err)
	check("all 3 funcs ran (Wait blocks until every goroutine exits)", ran == 3)
	check("Wait() returned a non-nil error", err != nil)
	check("Wait() error matches the injected message",
		err != nil && err.Error() == "boom: stage 2 failed")
}

func main() {
	fmt.Println("concurrency_patterns.go — Phase 3 bundle (concurrency patterns).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. No goroutine prints; results are collected, SORTED, and")
	fmt.Println("printed from main after every goroutine joins -> byte-identical runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
