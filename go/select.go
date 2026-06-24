//go:build ignore

// select.go — Phase 3 bundle #3.
//
// GOAL (one line): show, by printing every observable outcome, how Go's
// `select` statement multiplexes channel operations — the first READY case
// runs, when SEVERAL are ready one is picked at random, `default` makes it
// non-blocking, `time.After` provides a timeout case, and a nil channel
// disables its case.
//
// This is the GROUND TRUTH for SELECT.md. Every set and worked example in the
// guide is printed by this file. Change it -> re-run -> re-paste. Never
// hand-compute.
//
// DETERMINISM NOTE: when several select cases are ready the runtime picks ONE
// via a *uniform pseudo-random* selection (Go spec). That runtime coin-flip is
// independent of math/rand and cannot be seeded, so this file NEVER asserts
// WHICH ready case won. Instead each section either (a) forces exactly one
// case to be ready (deterministic — there is nothing to randomize), or
// (b) collects many trials into a SORTED set and asserts the set's MEMBERSHIP.
// Either way the printed bytes are identical across runs.
//
// Run:
//
//	go run select.go

package main

import (
	"fmt"
	"slices"
	"strings"
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

// sortedKeys returns the keys of m sorted ascending, so map-based sets print
// deterministically (map iteration is intentionally randomized — see MAPS).
func sortedKeys(m map[string]bool) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	return keys
}

// sectionA — only ONE case is ready, so select picks it deterministically: c1
// has a buffered value ready right now; c2 has no sender so a receive on it
// would block forever. With exactly one ready case there is nothing to
// randomize — select MUST take c1.
func sectionA() {
	sectionBanner("A — Only one case ready: deterministic pick")

	c1 := make(chan string, 1) // buffered: a value here is immediately "ready"
	c2 := make(chan string)    // unbuffered, no sender: a receive BLOCKS forever
	c1 <- "a"                  // ready now — no goroutine needed

	var got string
	select {
	case got = <-c1: // the only ready case -> this runs
	case <-c2: // never ready here -> cannot run
	}

	fmt.Println("c1: buffered chan holding \"a\" (ready)")
	fmt.Println("c2: unbuffered chan with no sender (blocks forever)")
	fmt.Printf("select picked: %q\n", got)
	check("only c1 ready -> select picks \"a\"", got == "a")
}

// sectionB — BOTH cases ready: select chooses ONE at random. Run 1000 trials,
// recording which case won each time into a set. With a ~50/50 pick the chance
// that only one side EVER wins is ~2*(1/2)^1000 (about 1e-301), so asserting
// that BOTH appeared is deterministic in practice. We print the SORTED set,
// never the per-trial order (which is random).
func sectionB() {
	sectionBanner("B — Multiple cases ready: one chosen at random")

	left := make(chan string, 1)
	right := make(chan string, 1)
	winners := make(map[string]bool)

	const trials = 1000
	for i := 0; i < trials; i++ {
		left <- "left" // both buffered(1): both become ready
		right <- "right"
		select {
		case <-left:
			winners["left"] = true
		case <-right:
			winners["right"] = true
		}
		// Drain whichever case did NOT win, so the next iteration's sends
		// do not block on a still-full buffer. (A select+default receive is
		// itself the non-blocking idiom from section C.)
		select {
		case <-left:
		default:
		}
		select {
		case <-right:
		default:
		}
	}

	keys := sortedKeys(winners)
	fmt.Printf("ran select with BOTH cases ready %d times\n", trials)
	fmt.Printf("set of winners (sorted) = {%s}\n", strings.Join(keys, ", "))
	check("left appeared at least once", winners["left"])
	check("right appeared at least once", winners["right"])
	check("winner set has exactly 2 members {left,right}", len(winners) == 2)
}

// sectionC — a `default` clause makes select NON-blocking: if no case is ready,
// default runs immediately instead of blocking. This is the basis of
// non-blocking send/receive and of polling.
func sectionC() {
	sectionBanner("C — default: non-blocking select")

	empty := make(chan int) // no sender -> receive would block
	received := false
	hitDefault := false

	select {
	case <-empty:
		received = true
	default:
		hitDefault = true // no case ready -> default runs right away
	}

	fmt.Println("empty channel (no sender) + default clause")
	fmt.Printf("default path taken: %v\n", hitDefault)
	check("default ran because no case was ready", hitDefault)
	check("no value was received from the empty channel", !received)
}

// sectionD — time.After(d) returns a channel that fires ONCE after d. As a
// select case it implements a timeout. We race a channel that NEVER fires
// against time.After; the timeout case always wins. We do NOT print the
// duration (a wall-clock value is not a reproducible number).
func sectionD() {
	sectionBanner("D — time.After: the timeout case")

	neverFires := make(chan struct{}) // no sender -> never ready
	timedOut := false
	gotData := false

	select {
	case <-neverFires:
		gotData = true
	case <-time.After(5 * time.Millisecond):
		timedOut = true // wins once the fixed duration elapses
	}

	fmt.Println("select { <-neverFires ; <-time.After(d) }")
	fmt.Printf("timeout case won: %v\n", timedOut)
	check("timeout case won", timedOut)
	check("the never-fire case did NOT win", !gotData)
}

// sectionE — a receive/send on a NIL channel blocks FOREVER, so select treats
// a nil-channel case as permanently NOT-ready and skips it. Assigning nil to a
// channel variable dynamically DISABLES that case. Run a select in a loop with
// one live channel and one nil channel; the nil case can never win.
func sectionE() {
	sectionBanner("E — nil channel disables its case")

	live := make(chan string, 1)
	var dead chan string // nil -> its case can never proceed
	winners := make(map[string]bool)

	const trials = 100
	for i := 0; i < trials; i++ {
		live <- "A" // drained by the select below; cap 1 so it never blocks
		select {
		case v := <-live:
			winners[v] = true
		case v := <-dead: // nil channel -> never ready, never chosen
			winners["DEAD:"+v] = true
		}
	}

	keys := sortedKeys(winners)
	fmt.Printf("ran select { live ; nil } %d times\n", trials)
	fmt.Printf("set of winners (sorted) = {%s}\n", strings.Join(keys, ", "))
	check("nil-channel case never won (set has only A)", len(winners) == 1 && winners["A"])
	check("the live value \"A\" was received", winners["A"])
}

// fanIn merges two input channels into one output channel using a select inside
// a loop. When an input is closed (comma-ok returns false) we set it to nil to
// DISABLE that case (the section E idiom), so the select keeps waiting on the
// remaining live input instead of hot-looping on a closed channel.
func fanIn(a, b <-chan int) <-chan int {
	out := make(chan int)
	go func() {
		for a != nil || b != nil {
			select {
			case v, ok := <-a:
				if !ok {
					a = nil // disable: a closed channel is always "ready" with zero
				} else { // value — without this we would spin forever.
					out <- v
				}
			case v, ok := <-b:
				if !ok {
					b = nil
				} else {
					out <- v
				}
			}
		}
		close(out)
	}()
	return out
}

// produce emits the given ints on a channel then closes it (sender-closes).
func produce(vals ...int) <-chan int {
	out := make(chan int)
	go func() {
		for _, v := range vals {
			out <- v
		}
		close(out)
	}()
	return out
}

// sectionF — fan-in: merge two producer channels via select-in-a-loop into one,
// collect every value, SORT it, and assert the merged set equals the union.
// (Arrival order is random; the sorted set is deterministic.)
func sectionF() {
	sectionBanner("F — fan-in: merging channels with select")

	in1 := produce(1, 2, 3)
	in2 := produce(4, 5, 6)
	merged := fanIn(in1, in2)

	got := make([]int, 0, 6)
	for v := range merged {
		got = append(got, v)
	}
	slices.Sort(got)

	fmt.Println("merged producers {1,2,3} and {4,5,6} via select-in-a-loop")
	fmt.Printf("collected (sorted) = %v\n", got)
	check("fan-in delivered all 6 values", len(got) == 6)
	check("sorted merge == union {1..6}", slices.Equal(got, []int{1, 2, 3, 4, 5, 6}))
}

func main() {
	fmt.Println("select.go — Phase 3 bundle #3.")
	fmt.Println("Every observable outcome below is produced by this file; the .md guide")
	fmt.Println("pastes it verbatim. Random per-trial winners are collapsed into sorted")
	fmt.Println("sets so the output is byte-identical across runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
