//go:build ignore

// resilience_patterns.go — Phase 8 bundle (resilience patterns).
//
// GOAL (one line): show, by driving a DETERMINISTIC fake operation (fails the
// first K times, then succeeds) through each resilience pattern, how RETRY with
// exponential backoff + seeded jitter, CIRCUIT BREAKER (gobreaker), RATE LIMITER
// (golang.org/x/time/rate token bucket), TIMEOUTS (context.WithTimeout), and
// BULKHEADS (counting semaphore) behave — and how they compose into one
// resilient client.
//
// This is the GROUND TRUTH for RESILIENCE_PATTERNS.md. Every value below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM (critical — see HOW_TO_RESEARCH.md §4.2):
//   - The fake operation is a COUNTER (fails the first K times, then succeeds);
//     no real network, no flaky dependency. We assert attempt COUNTS, OUTCOMES
//     (error sentinels / state names), and computed backoff values — NEVER an
//     elapsed wall-clock duration.
//   - Jitter RNG is SEEDED (math/rand/v2 PCG with a fixed seed), so the printed
//     backoff sequence is byte-identical across runs.
//   - The circuit breaker's Open->HalfOpen cooldown uses a REAL short Timeout
//     (50ms) plus time.Sleep(80ms) to cross it; we assert the resulting STATE
//     names and the op-call count, not durations.
//   - The rate limiter uses rate.Every(time.Hour) (~0.000278 tokens/sec) with
//     burst 3: within the test no token refills, so Allow() outcomes (true,true,
//     true,false,...) are deterministic.
//   - The bulkhead launches goroutines; NO goroutine prints. Worker ids are
//     collected into a channel, SORTED, and printed from main after all join.
//     The (scheduler-dependent) peak in-flight value is asserted as a bound but
//     NEVER printed, so two `just out` runs are byte-identical.
//
// Run:
//
//	go run resilience_patterns.go

package main

import (
	"context"
	"errors"
	"fmt"
	"math/rand/v2"
	"runtime"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/sony/gobreaker"
	"golang.org/x/time/rate"
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

// --- shared, deterministic fake operation ------------------------------------

// errRetryable is the sentinel a fake op wraps its transient failures in, so the
// retry loop can classify it via errors.Is and decide to retry. A RETRYABLE error
// is one where re-executing is safe and likely to eventually succeed (a timeout,
// a 503, a transient network blip).
var errRetryable = errors.New("retryable transient error")

// errFatal is a NON-retryable error: the retry loop must bail out IMMEDIATELY.
// Non-retryable = a non-idempotent write that already partially succeeded, a 4xx
// (bad request — retrying the identical bytes is pointless), or a validation error.
var errFatal = errors.New("fatal non-retryable error")

// flakyOp is the deterministic fake dependency. It fails (wrapping errRetryable)
// for the first failN Do() calls, then succeeds forever after. `calls` counts
// invocations so sections can assert EXACTLY how many times the op was reached
// (e.g. that an Open circuit breaker fast-failed WITHOUT invoking the op).
type flakyOp struct {
	failN int
	calls int
}

func (f *flakyOp) Do() (string, error) {
	f.calls++
	if f.calls <= f.failN {
		return "", fmt.Errorf("%w: call #%d", errRetryable, f.calls)
	}
	return "ok", nil
}

// isRetryable classifies an error: only errRetryable (wrapped) is retried.
// Everything else (errFatal, context.Canceled, gobreaker.ErrOpenState, ...) stops
// the retry loop — see the "retryable-error classification" pitfall.
func isRetryable(err error) bool { return errors.Is(err, errRetryable) }

// backoffAdditiveJitter computes a CAPPED exponential backoff with ADDITIVE
// (seeded) jitter: sleep = min(cap, base*2^attempt) + uniform[0, base). The RNG
// is a seeded *rand.Rand so the value is byte-stable across runs. (AWS's "Full
// Jitter" variant replaces the whole value with uniform[0, min(cap, base*2^a)];
// see RESILIENCE_PATTERNS.md §3 for the comparison.) The returned duration is
// ASSERTED/printed, never measured as elapsed time.
func backoffAdditiveJitter(attempt int, base, cap time.Duration, rng *rand.Rand) time.Duration {
	if attempt > 62 { // guard against 1<<attempt overflow
		attempt = 62
	}
	exp := base * time.Duration(int64(1)<<attempt) // base * 2^attempt
	if exp > cap {
		exp = cap
	}
	jitter := time.Duration(rng.Int64N(int64(base))) // uniform in [0, base)
	return exp + jitter
}

// sectionA — RETRY with exponential backoff + seeded jitter. A fake op fails the
// first 3 times then succeeds; the retry loop sleeps a capped exponential backoff
// (with seeded jitter) between attempts. We assert the FINAL outcome (success),
// the total attempt count (4 = 3 failures + 1 success), and that the op was
// invoked exactly 4 times. A second sub-demo proves a NON-retryable error aborts
// immediately (attempts == 1).
func sectionA() {
	sectionBanner("A — Retry + exponential backoff + seeded jitter")

	const (
		maxAttempts = 5
		base        = 1 * time.Millisecond
		capBackoff  = 50 * time.Millisecond
	)
	rng := rand.New(rand.NewPCG(42, 42)) // SEEDED -> identical jitter every run

	// retryWithBackoff runs op up to maxAttempts times, sleeping a capped
	// exponential+ jitter backoff between attempts, but ONLY for retryable errors.
	retryWithBackoff := func(op func() (string, error)) (result string, attempts int, delays []time.Duration, err error) {
		var lastErr error
		for attempt := 0; attempt < maxAttempts; attempt++ {
			attempts++
			result, lastErr = op()
			if lastErr == nil {
				return result, attempts, delays, nil
			}
			// Classification gate: a NON-retryable error must NOT be retried.
			if !isRetryable(lastErr) {
				return "", attempts, delays, lastErr
			}
			if attempt == maxAttempts-1 {
				break // exhausted retries
			}
			d := backoffAdditiveJitter(attempt, base, capBackoff, rng)
			delays = append(delays, d)
			time.Sleep(d) // real sleep, but its duration is never printed/measured
		}
		return "", attempts, delays, lastErr
	}

	// (1) Retryable op: fails 3x (wrapping errRetryable), succeeds on call #4.
	op := &flakyOp{failN: 3}
	result, attempts, delays, err := retryWithBackoff(op.Do)
	fmt.Printf("retry config: maxAttempts=%d, base=%v, cap=%v, jitter=seeded additive[0,base)\n", maxAttempts, base, capBackoff)
	fmt.Printf("fake op: fails first 3 calls then succeeds -> result=%q, attempts=%d, op.calls=%d, err=%v\n",
		result, attempts, op.calls, err)
	fmt.Printf("backoff delays actually slept (base*2^attempt + seeded jitter, capped): %v\n", delays)
	check("retry eventually succeeded (err == nil)", err == nil)
	check("final result == \"ok\"", result == "ok")
	check("attempts == 4 (3 failures + 1 success)", attempts == 4)
	check("op invoked exactly 4 times", op.calls == 4)
	check("exactly 3 backoff delays slept (one per failure, none after success)", len(delays) == 3)

	// (2) Non-retryable error: the loop MUST bail out on the first attempt.
	fatalCalls := 0
	fatalOp := func() (string, error) {
		fatalCalls++
		return "", fmt.Errorf("%w: bad request", errFatal)
	}
	_, fatalAttempts, _, fatalErr := retryWithBackoff(fatalOp)
	fmt.Printf("non-retryable op -> attempts=%d, fatalCalls=%d, err=%v (no retry attempted)\n",
		fatalAttempts, fatalCalls, fatalErr)
	check("non-retryable error: attempts == 1 (no retry)", fatalAttempts == 1)
	check("non-retryable error: op invoked exactly once", fatalCalls == 1)
	check("non-retryable error returned is errFatal", errors.Is(fatalErr, errFatal))
}

// sectionB — CIRCUIT BREAKER (github.com/sony/gobreaker). A state machine with
// three states: Closed (normal), Open (failing -> fast-fail), HalfOpen (probe).
// ReadyToTrip trips after 2 consecutive failures; a 50ms Timeout is the Open->
// HalfOpen cooldown. We feed a deterministic fail,fail sequence, assert the
// breaker is Open and that an Open Execute returns ErrOpenState WITHOUT invoking
// the op (call count stays at 2), then cross the cooldown and prove a probe
// success transitions HalfOpen -> Closed.
func sectionB() {
	sectionBanner("B — Circuit breaker (gobreaker): Closed -> Open -> HalfOpen -> Closed")

	var opCalls int // incremented ONLY inside the request func
	op := func(success bool) func() (any, error) {
		return func() (any, error) {
			opCalls++
			if success {
				return "ok", nil
			}
			return nil, fmt.Errorf("%w: op call #%d", errRetryable, opCalls)
		}
	}

	var transitions []string // OnStateChange appends "from -> to" synchronously (no race: all from main)
	cb := gobreaker.NewCircuitBreaker(gobreaker.Settings{
		Name: "demo",
		ReadyToTrip: func(c gobreaker.Counts) bool {
			return c.ConsecutiveFailures >= 2 // trip after 2 consecutive failures (default is >5)
		},
		Timeout: 50 * time.Millisecond, // Open -> HalfOpen cooldown (short, for the test)
		OnStateChange: func(name string, from, to gobreaker.State) {
			transitions = append(transitions, fmt.Sprintf("%s -> %s", from, to))
		},
	})

	// Two failures -> ReadyToTrip returns true -> state becomes Open.
	cb.Execute(op(false)) // op call #1, fail
	cb.Execute(op(false)) // op call #2, fail -> trips to Open
	fmt.Printf("after 2 failures: state=%s, opCalls=%d\n", cb.State(), opCalls)
	check("after 2 failures the breaker is Open", cb.State() == gobreaker.StateOpen)
	check("op was invoked exactly 2 times", opCalls == 2)

	// An Execute while Open returns ErrOpenState INSTANTLY without calling the op.
	_, err := cb.Execute(op(true))
	fmt.Printf("Execute while Open -> err=%v, opCalls=%d (op NOT invoked)\n", err, opCalls)
	check("Open Execute returned gobreaker.ErrOpenState", errors.Is(err, gobreaker.ErrOpenState))
	check("op STILL invoked exactly 2 times (Open fast-failed without calling it)", opCalls == 2)

	// Cross the 50ms cooldown: the next Execute observes now > expiry and transitions
	// Open -> HalfOpen; a success in HalfOpen then transitions HalfOpen -> Closed.
	time.Sleep(80 * time.Millisecond)
	_, err = cb.Execute(op(true)) // op call #3, success -> HalfOpen -> Closed
	fmt.Printf("after cooldown + probe success: state=%s, opCalls=%d, probe err=%v\n", cb.State(), opCalls, err)
	check("after cooldown+success the breaker is Closed", cb.State() == gobreaker.StateClosed)
	check("op invoked exactly 3 times (the probe ran)", opCalls == 3)
	check("probe Execute returned nil", err == nil)

	fmt.Printf("state transitions observed (via OnStateChange): %v\n", transitions)
	check("first transition was closed -> open",
		len(transitions) >= 1 && transitions[0] == "closed -> open")
	check("transition sequence is [closed->open, open->half-open, half-open->closed]",
		fmt.Sprint(transitions) == "[closed -> open open -> half-open half-open -> closed]")
}

// sectionC — RATE LIMITER (golang.org/x/time/rate). A token bucket of size b,
// refilled at r tokens/sec, initially full. Allow() consumes one token (true) or
// returns false when the bucket is empty. We use rate.Every(time.Hour) (~1
// token/3600s) with burst 3 so NO token refills during the test: the first 3
// Allows return true, the (burst+1)th and after return false. Wait() is exercised
// on a pre-cancelled context (deterministic) to show it honours cancellation.
func sectionC() {
	sectionBanner("C — Rate limiter (x/time/rate): token bucket, burst then block")

	const burst = 3
	lim := rate.NewLimiter(rate.Every(time.Hour), burst) // ~0.000278 tokens/sec; bucket starts full

	fmt.Printf("Limiter: rate=Every(1h) = %g tokens/sec, burst=%d, bucket initially full\n",
		float64(lim.Limit()), lim.Burst())

	allows := make([]bool, 0, burst+2)
	for i := 0; i < burst+2; i++ {
		allows = append(allows, lim.Allow())
	}
	fmt.Printf("Allow() x%d outcomes: %v\n", burst+2, allows)

	nTrue := 0
	for _, a := range allows {
		if a {
			nTrue++
		}
	}
	check(fmt.Sprintf("exactly burst=%d Allows returned true", burst), nTrue == burst)
	check("the (burst+1)th Allow returned false (bucket empty, ~1 token/hour refill)", !allows[burst])
	check("the (burst+2)th Allow returned false too", !allows[burst+1])

	// Wait(ctx) BLOCKS until a token is available OR ctx is cancelled. To show its
	// cancellation contract deterministically (no wall-clock wait), pre-cancel ctx.
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	werr := lim.Wait(ctx)
	fmt.Printf("Wait(pre-cancelled ctx) -> err=%v (Wait blocks for a token unless ctx is done)\n", werr)
	check("Wait on a pre-cancelled ctx returned context.Canceled", errors.Is(werr, context.Canceled))
}

// sectionD — TIMEOUT (context.WithTimeout). A per-call deadline: an op slower
// than the timeout returns context.DeadlineExceeded. We wrap a fixed slow op
// (selects on a 50ms time.After) with a 5ms timeout and assert the error sentinel.
// The error CODE is the deterministic assertion; no elapsed time is printed.
func sectionD() {
	sectionBanner("D — Timeout (context.WithTimeout): slow op -> DeadlineExceeded")

	slowOp := func(ctx context.Context) error {
		select {
		case <-time.After(50 * time.Millisecond):
			return nil // would succeed, but the timeout fires first
		case <-ctx.Done():
			return ctx.Err() // honour the deadline/cancellation
		}
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Millisecond)
	defer cancel()
	err := slowOp(ctx)
	fmt.Printf("slow op (50ms) under ctx timeout (5ms) -> err=%v\n", err)
	check("slow op returned context.DeadlineExceeded", errors.Is(err, context.DeadlineExceeded))
	check("ctx.Err() is also context.DeadlineExceeded", errors.Is(ctx.Err(), context.DeadlineExceeded))
}

// sectionE — BULKHEAD (counting semaphore). A buffered chan of size N bounds
// concurrency: a flooded dependency cannot exhaust your goroutines because at
// most N callers hold a slot at once. We launch 10 goroutines through a cap-3
// semaphore, track in-flight via atomics, and assert the PEAK is <= 3. The
// peak value itself is scheduler-dependent so it is asserted (as a bound) but
// NEVER printed; worker ids are collected and SORTED for byte-identical output.
func sectionE() {
	sectionBanner("E — Bulkhead (semaphore): cap concurrency at N, isolate a flooded dependency")

	const (
		capacity = 3
		workers  = 10
	)
	sem := make(chan struct{}, capacity) // the bulkhead: acquire=send, release=<-sem

	var (
		inFlight int64
		peak     int64
		total    int64
		wg       sync.WaitGroup
	)
	results := make(chan int, workers)

	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			sem <- struct{}{} // ACQUIRE: send blocks while `capacity` slots are held

			cur := atomic.AddInt64(&inFlight, 1)
			for { // lock-free peak = max(peak, cur)
				p := atomic.LoadInt64(&peak)
				if cur <= p || atomic.CompareAndSwapInt64(&peak, p, cur) {
					break
				}
			}

			// Deterministic token work held INSIDE the slot so the bound is exercised.
			var acc int64
			for k := int64(0); k < 100000; k++ {
				acc += k
			}
			atomic.AddInt64(&total, acc)
			runtime.Gosched() // yield so other goroutines pile into the semaphore

			atomic.AddInt64(&inFlight, -1)
			<-sem // RELEASE: receive frees a slot for a waiter

			results <- id
		}(i)
	}
	wg.Wait()
	close(results)

	var ids []int
	for id := range results {
		ids = append(ids, id)
	}
	slices.Sort(ids)

	fmt.Printf("bulkhead: chan struct{} cap=%d gates %d workers (acquire=send, release=<-sem)\n", capacity, workers)
	fmt.Printf("workers that completed (sorted): %v\n", ids)
	fmt.Printf("total token work (%d * sum(0..99999)): %d\n", workers, atomic.LoadInt64(&total))
	check("all 10 workers completed", len(ids) == workers)
	check("every worker id 0..9 ran exactly once", fmt.Sprint(ids) == "[0 1 2 3 4 5 6 7 8 9]")
	check("peak in-flight <= capacity (3)", atomic.LoadInt64(&peak) <= int64(capacity))
	check("peak in-flight >= 1 (bulkhead was exercised)", atomic.LoadInt64(&peak) >= 1)
	check("total work == 10 * sum(0..99999) = 49999500000 (all goroutines completed)",
		atomic.LoadInt64(&total) == int64(49999500000))
}

// sectionF — COMPOSITION. A production resilient client stacks the patterns: a
// per-attempt context.WithTimeout caps each call; the circuit breaker gates each
// attempt (and fast-fails if Open); retry with seeded-jitter backoff wraps the
// loop. We run it against the fake op (fails 3x, ok on the 4th) with a HIGH
// ReadyToTrip threshold (6) so the 3 transient failures do NOT trip the breaker —
// it ends Closed. This proves the layers compose without interfering.
func sectionF() {
	sectionBanner("F — Composition: timeout + retry + circuit breaker in one resilient call")

	const (
		maxAttempts = 5
		perCallTo   = 100 * time.Millisecond // generous: the fake op is instant
		base        = 1 * time.Millisecond
		capBackoff  = 50 * time.Millisecond
	)
	rng := rand.New(rand.NewPCG(7, 7))

	var opCalls int
	op := func(ctx context.Context) error {
		opCalls++
		if opCalls <= 3 {
			return fmt.Errorf("%w: call #%d", errRetryable, opCalls)
		}
		return nil // success on the 4th
	}

	cb := gobreaker.NewCircuitBreaker(gobreaker.Settings{
		Name: "resilient-client",
		ReadyToTrip: func(c gobreaker.Counts) bool {
			return c.ConsecutiveFailures >= 6 // high: 3 transient fails will NOT trip it
		},
	})

	// callResilient layers timeout (innermost) inside the breaker (per attempt)
	// inside retry+backoff (outermost). An Open breaker or a non-retryable error
	// stops the retry loop immediately.
	callResilient := func(ctx context.Context) error {
		var lastErr error
		for attempt := 0; attempt < maxAttempts; attempt++ {
			_, err := cb.Execute(func() (any, error) {
				callCtx, cancel := context.WithTimeout(ctx, perCallTo)
				defer cancel()
				return nil, op(callCtx)
			})
			if err == nil {
				return nil
			}
			lastErr = err
			if !isRetryable(err) || errors.Is(err, gobreaker.ErrOpenState) {
				return err
			}
			if attempt == maxAttempts-1 {
				break
			}
			time.Sleep(backoffAdditiveJitter(attempt, base, capBackoff, rng))
		}
		return lastErr
	}

	err := callResilient(context.Background())
	fmt.Printf("composite call (timeout+retry+breaker) vs op(fails 3x then ok): err=%v\n", err)
	fmt.Printf("op invocations=%d, final breaker state=%s\n", opCalls, cb.State())
	check("composite call succeeded (err == nil)", err == nil)
	check("op invoked exactly 4 times (3 retries + 1 success)", opCalls == 4)
	check("breaker ended Closed (the 3 transient fails did not trip the high threshold)",
		cb.State() == gobreaker.StateClosed)
}

func main() {
	fmt.Println("resilience_patterns.go — Phase 8 bundle (resilience patterns).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes it verbatim.")
	fmt.Println("Deterministic: fake ops, seeded jitter, no printed timings, sorted goroutine output.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
