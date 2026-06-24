//go:build ignore

// context.go — Phase 3 bundle (context.Context: deadlines, cancellation, values).
//
// GOAL (one line): show, by printing every behavior, how context.Context carries
// deadlines, cancellation signals, and request-scoped values across API
// boundaries, and how cancellation propagates down the context tree.
//
// This is the GROUND TRUTH for CONTEXT.md. Every Err() code and Done() state
// below is printed by this file. Change it -> re-run -> re-paste. Never
// hand-compute.
//
// DETERMINISM (critical for this bundle): context deadlines/timeouts are timing
// dependent, so this file NEVER prints elapsed wall-clock or duration values.
// Every assertion is on ctx.Err() (context.Canceled / context.DeadlineExceeded)
// and on whether ctx.Done() is CLOSED, never on how long anything took. Worker
// output is collected into a buffered channel and SORTED before main prints it,
// and a start gate guarantees every worker observes the same cancellation state.
// Two runs of `just out context` are byte-identical.
//
// Run:
//
//	go run context.go

package main

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"sync"
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

// doneClosed reports whether ctx.Done() has been closed WITHOUT blocking: a
// non-blocking receive on the Done channel. For contexts whose Done() is nil
// (Background/TODO, which can never be cancelled) the receive blocks forever, so
// the default branch runs and we report false — exactly the right answer.
func doneClosed(ctx context.Context) bool {
	select {
	case <-ctx.Done():
		return true
	default:
		return false
	}
}

// collect drains a (closed) channel into a slice.
func collect(ch <-chan string) []string {
	var out []string
	for s := range ch {
		out = append(out, s)
	}
	return out
}

// --- unexported context key types (the RIGHT way — see section E) ------------

// ctxKey is an UNEXPORTED type used only as a context key. Because it is
// unexported, no other package can forge a value of this type, so there is no
// chance of a key collision across packages.
type ctxKey struct{}

// keyA and keyB are two distinct unexported key types. Even though both can
// hold the same underlying int value, they are DIFFERENT types, so
// ctx.Value(keyA(1)) and ctx.Value(keyB(1)) retrieve independent values. This is
// how typed keys avoid the collisions that plain string keys suffer.
type (
	keyA int
	keyB int
)

// sectionA shows the two roots — context.Background() and context.TODO() — and
// builds a three-layer-deep context tree from Background. It asserts the
// invariants of a "live" (not-yet-cancelled) context: Done() not closed and
// Err()==nil. For Background itself (which can NEVER be cancelled) Done()
// returns nil.
func sectionA() {
	sectionBanner("A — Background, TODO & the context tree (the roots)")

	bg := context.Background()
	todo := context.TODO()

	// Background and TODO are both "empty" contexts. Background is the root of a
	// real tree (used by main, init, tests, and as the top of incoming requests);
	// TODO is a placeholder for "I have not wired a real context here yet".
	fmt.Printf("Background() == Background()? %v   (same singleton, never cancelled)\n", bg == context.Background())
	fmt.Printf("TODO()       == TODO()?       %v   (same singleton, placeholder)\n", todo == context.TODO())
	fmt.Printf("Background().Done() == nil?  %v   (Background can never be cancelled)\n", bg.Done() == nil)
	fmt.Printf("TODO().Done()       == nil?  %v   (TODO can never be cancelled either)\n", todo.Done() == nil)

	// Build a three-layer tree: Background -> child -> grandchild.
	child, cancel := context.WithCancel(bg)
	defer cancel()
	grand, cancel2 := context.WithCancel(child)
	defer cancel2()

	fmt.Printf("child      Done() closed? %v   Err() = %v   (live child)\n", doneClosed(child), child.Err())
	fmt.Printf("grandchild Done() closed? %v   Err() = %v   (live grandchild)\n", doneClosed(grand), grand.Err())

	check("Background() is the same singleton each call", bg == context.Background())
	check("Background().Done() is nil (never cancellable)", bg.Done() == nil)
	check("TODO().Done() is nil (never cancellable)", todo.Done() == nil)
	check("live child: Done() not yet closed", !doneClosed(child))
	check("live child: Err() == nil", child.Err() == nil)
	check("live grandchild: Done() not yet closed", !doneClosed(grand))
	check("live grandchild: Err() == nil", grand.Err() == nil)
}

// sectionB demonstrates context.WithCancel: calling cancel() CLOSES the Done()
// channel and sets Err() to context.Canceled. defer cancel() is mandatory — it
// releases resources and removes the child from its parent.
func sectionB() {
	sectionBanner("B — WithCancel: cancel() closes Done(); Err()==context.Canceled")

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel() // ALWAYS defer cancel: it releases resources + removes the
	//               child from its parent even on an early return.

	beforeClosed := doneClosed(ctx)
	beforeErr := ctx.Err()
	fmt.Printf("before cancel: Done() closed? %v   Err() = %v\n", beforeClosed, beforeErr)

	cancel() // cancel this ctx and every child derived from it.

	// The close of Done() may happen asynchronously after cancel() returns, so
	// we receive from it to be sure it is closed before we read Err().
	<-ctx.Done()
	afterClosed := doneClosed(ctx)
	afterErr := ctx.Err()
	fmt.Printf("after  cancel: Done() closed? %v   Err() = %v\n", afterClosed, afterErr)

	check("before cancel: Done() not closed", !beforeClosed)
	check("before cancel: Err() == nil", beforeErr == nil)
	check("after cancel: Done() closed", afterClosed)
	check("after cancel: Err() == context.Canceled", afterErr == context.Canceled)
	check("after cancel: ctx.Err() is exactly the context.Canceled sentinel", ctx.Err() == context.Canceled)
}

// sectionC demonstrates WithTimeout and WithDeadline. Both auto-cancel after a
// fixed moment; after that ctx.Err() == context.DeadlineExceeded. We assert the
// ERROR CODE and the Done() closure ONLY — never the elapsed time, which is
// timing-dependent and would make the output non-reproducible.
func sectionC() {
	sectionBanner("C — WithTimeout/WithDeadline: Err()==context.DeadlineExceeded")

	// A FIXED short duration. We never print it (that would be a timing value);
	// we only assert the resulting error code once the deadline fires.
	const fixed = 20 * time.Millisecond

	// WithTimeout(parent, d) is defined as WithDeadline(parent, time.Now()+d).
	tctx, tcancel := context.WithTimeout(context.Background(), fixed)
	defer tcancel()

	// WithDeadline takes an ABSOLUTE time.Time; WithTimeout is sugar over it.
	dctx, dcancel := context.WithDeadline(context.Background(), time.Now().Add(fixed))
	defer dcancel()

	// Block until each deadline fires (Done() closes), then read the error code.
	<-tctx.Done()
	tErr := tctx.Err()
	<-dctx.Done()
	dErr := dctx.Err()

	fmt.Printf("WithTimeout(bg, short-fixed): Done() closed? %v   Err() = %v\n", doneClosed(tctx), tErr)
	fmt.Printf("WithDeadline(bg, now+short) : Done() closed? %v   Err() = %v\n", doneClosed(dctx), dErr)

	check("WithTimeout: Done() closed after it fires", doneClosed(tctx))
	check("WithTimeout: Err() == context.DeadlineExceeded", tErr == context.DeadlineExceeded)
	check("WithDeadline: Done() closed after it fires", doneClosed(dctx))
	check("WithDeadline: Err() == context.DeadlineExceeded", dErr == context.DeadlineExceeded)
}

// sectionD shows the CORE power of context: CANCELLATION PROPAGATES DOWN THE
// TREE. Cancelling a parent cancels every child (and grandchild) derived from
// it. One cancel call cascades through the whole call tree.
func sectionD() {
	sectionBanner("D — Cancellation propagates down the tree")

	// Build: parent -> child -> grandchild (all cancellable). We keep each
	// cancel func (and defer it) but ONLY call the parent's cancel by hand.
	parent, parentCancel := context.WithCancel(context.Background())
	defer parentCancel()
	child, childCancel := context.WithCancel(parent)
	defer childCancel()
	grand, grandCancel := context.WithCancel(child)
	defer grandCancel()

	beforeParent := doneClosed(parent)
	beforeChild := doneClosed(child)
	beforeGrand := doneClosed(grand)
	fmt.Printf("before: parent closed? %v  child closed? %v  grandchild closed? %v\n",
		beforeParent, beforeChild, beforeGrand)

	parentCancel() // cancel ONLY the parent.

	// The child's and grandchild's Done() channels close as a side effect.
	<-child.Done()
	<-grand.Done()
	childErr := child.Err()
	grandErr := grand.Err()
	fmt.Printf("after parentCancel: parent.Err()=%v  child.Err()=%v  grandchild.Err()=%v\n",
		parent.Err(), childErr, grandErr)

	check("before: parent not closed", !beforeParent)
	check("before: child not closed", !beforeChild)
	check("before: grandchild not closed", !beforeGrand)
	check("parentCancel -> child Done() closed", doneClosed(child))
	check("parentCancel -> grandchild Done() closed", doneClosed(grand))
	check("parentCancel -> child.Err() == context.Canceled", childErr == context.Canceled)
	check("parentCancel -> grandchild.Err() == context.Canceled", grandErr == context.Canceled)
}

// sectionE shows context.Value: request-scoped values carried along the call
// chain. The RIGHT way uses an UNEXPORTED key type (no cross-package collision);
// the WRONG way uses a plain string key (collides; staticcheck/golint warn).
// Note the controversy: Value is untyped (any), so retrieval needs a type
// assertion the compiler cannot check.
func sectionE() {
	sectionBanner("E — Values: right (unexported key) vs wrong (string key)")

	// RIGHT: store a trace ID under an unexported-type key.
	bg := context.Background()
	ctx := context.WithValue(bg, ctxKey{}, "req-123")

	v, ok := ctx.Value(ctxKey{}).(string)
	fmt.Printf("right: WithValue(bg, ctxKey{}, \"req-123\"); Value(ctxKey{}).(string) = %q, ok=%v\n", v, ok)

	// Distinct unexported types NEVER collide even with the same underlying value.
	mixed := context.WithValue(context.WithValue(bg, keyA(1), "a-val"), keyB(1), "b-val")
	a, aOK := mixed.Value(keyA(1)).(string)
	b, bOK := mixed.Value(keyB(1)).(string)
	fmt.Printf("typed keys: Value(keyA(1))=%q ok=%v   Value(keyB(1))=%q ok=%v   (no collision)\n", a, aOK, b, bOK)

	// WRONG: a plain string key "works" but two packages both using "role"
	// collide silently. WithValue also SHADOWS: the nearest ancestor's value
	// wins when Value walks up the tree.
	outer := context.WithValue(bg, "role", "admin")
	inner := context.WithValue(outer, "role", "guest")
	role := inner.Value("role")
	fmt.Printf("string key: outer role=admin, inner role=guest -> Value(\"role\")=%q   (nearest ancestor wins)\n", role)
	fmt.Println("note: go vet is silent here, but staticcheck/golint warn —")
	fmt.Println("      \"should not use basic type string as key in context.WithValue\".")

	check("right key: retrieved trace ID == \"req-123\"", v == "req-123" && ok)
	check("right key: type assertion succeeded (ok==true)", ok)
	check("typed keyA(1) retrieves a-val", a == "a-val" && aOK)
	check("typed keyB(1) retrieves b-val", b == "b-val" && bOK)
	check("string key shadowed: inner Value(\"role\") == guest", role == "guest")
	check("missing typed key returns nil (zero value)", mixed.Value(keyA(99)) == nil)
}

// worker demonstrates the ctx-first convention: ctx is the FIRST parameter, and
// the worker selects on ctx.Done() to bail out early. A start gate makes the
// demo deterministic: workers wait at <-start, so main can cancel BEFORE
// releasing them, guaranteeing every worker observes the same cancellation.
func worker(ctx context.Context, id int, start <-chan struct{}, out chan<- string, wg *sync.WaitGroup) {
	defer wg.Done()
	<-start // gate: wait until main releases us
	select {
	case <-ctx.Done():
		out <- fmt.Sprintf("worker-%d stopped: %v", id, ctx.Err())
	default:
		out <- fmt.Sprintf("worker-%d ran to completion", id)
	}
}

// sectionF shows the ctx-first convention in action with three workers. Run 1
// cancels BEFORE releasing the gate -> all three stop with context.Canceled.
// Run 2 never cancels -> all three run to completion. Output is collected then
// SORTED, so two `just out context` runs are byte-identical regardless of
// goroutine scheduling.
func sectionF() {
	sectionBanner("F — ctx-first convention: worker(ctx) selects on Done()")

	var wg sync.WaitGroup

	// Run 1: cancel BEFORE releasing the start gate.
	ctx1, cancel1 := context.WithCancel(context.Background())
	start1 := make(chan struct{})
	out1 := make(chan string, 3)
	for i := 1; i <= 3; i++ {
		wg.Add(1)
		go worker(ctx1, i, start1, out1, &wg)
	}
	cancel1()     // cancel while workers are parked at the gate
	close(start1) // release them -> each sees Done() closed -> stops
	wg.Wait()
	close(out1)
	run1 := collect(out1)
	slices.Sort(run1)
	fmt.Println("run 1 (cancelled before release):")
	for _, line := range run1 {
		fmt.Println("  " + line)
	}

	// Run 2: never cancel -> workers run to completion.
	ctx2, cancel2 := context.WithCancel(context.Background())
	defer cancel2()
	start2 := make(chan struct{})
	out2 := make(chan string, 3)
	for i := 1; i <= 3; i++ {
		wg.Add(1)
		go worker(ctx2, i, start2, out2, &wg)
	}
	close(start2) // release WITHOUT cancelling
	wg.Wait()
	close(out2)
	run2 := collect(out2)
	slices.Sort(run2)
	fmt.Println("run 2 (never cancelled):")
	for _, line := range run2 {
		fmt.Println("  " + line)
	}

	stoppedCount := 0
	for _, l := range run1 {
		if strings.Contains(l, "stopped: context canceled") {
			stoppedCount++
		}
	}
	completedCount := 0
	for _, l := range run2 {
		if strings.Contains(l, "ran to completion") {
			completedCount++
		}
	}

	check("run 1: all 3 workers stopped on cancel", stoppedCount == 3)
	check("run 2: all 3 workers ran to completion", completedCount == 3)
	check("run 1: ctx1.Err() == context.Canceled (we cancelled)", ctx1.Err() == context.Canceled)
	check("run 2: ctx2.Err() == nil (never cancelled)", ctx2.Err() == nil)
}

func main() {
	fmt.Println("context.go — Phase 3 bundle (context.Context: deadlines,")
	fmt.Println("cancellation, request-scoped values). Every Err() code and Done() state")
	fmt.Println("below is computed by this file; the .md guide pastes it verbatim.")
	fmt.Println("Nothing is hand-computed; no wall-clock/duration values are printed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
