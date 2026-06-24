//go:build ignore

// goroutines.go — Phase 3 bundle (the GMP scheduler).
//
// GOAL (one line): show, by printing every value, how the `go` statement, the
// GMP scheduler (G goroutine, M OS thread, P processor), GOMAXPROCS, and
// goroutine leaks actually behave.
//
// This is the GROUND TRUTH for GOROUTINES.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// DETERMINISM (critical for this bundle): goroutine scheduling is intentionally
// nondeterministic, so NO goroutine ever prints directly. Every goroutine writes
// its result into a mutex-guarded slice (or signals via a channel); main SORTS
// the collected results and prints them only AFTER all goroutines join
// (sync.WaitGroup). Two runs of `just out goroutines` are byte-identical.
//
// Run:
//
//	go run goroutines.go

package main

import (
	"fmt"
	"runtime"
	"slices"
	"strings"
	"sync"
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

// sectionA shows the `go` statement + a sync.WaitGroup. Eight goroutines each
// square their index and append to a SHARED slice under a mutex; main sorts the
// slice and prints it only after WaitGroup.Wait() returns. The sort is what makes
// the output deterministic regardless of completion order.
func sectionA() {
	sectionBanner("A — go statement + WaitGroup (deterministic collection)")

	const n = 8
	var (
		mu      sync.Mutex
		squares []int
		wg      sync.WaitGroup
	)
	wg.Add(n)
	for i := range n {
		go func(i int) {
			defer wg.Done()
			v := i * i
			mu.Lock()
			squares = append(squares, v)
			mu.Unlock()
		}(i)
	}
	wg.Wait() // main blocks until every goroutine has joined
	slices.Sort(squares)

	fmt.Printf("launched %d goroutines: go func(i int){ squares=append(..., i*i) }(i)\n", n)
	fmt.Printf("after WaitGroup.Wait() + sort -> squares = %v\n", squares)
	check("sorted squares == [0 1 4 9 16 25 36 49]",
		fmt.Sprintf("%v", squares) == "[0 1 4 9 16 25 36 49]")
}

// sectionB introspects the scheduler: the P count (GOMAXPROCS), the logical CPU
// count, and the live goroutine count. NumGoroutine includes RUNTIME goroutines
// (GC, scavenger, ...), not just user goroutines — so we never assert it equals
// a specific small number; we assert it strictly rises when blocked goroutines
// are introduced and falls again once they join.
func sectionB() {
	sectionBanner("B — GMP model: P count, NumCPU, live goroutine count")

	fmt.Printf("runtime.NumCPU()        = %d  (logical CPUs usable by this process)\n", runtime.NumCPU())
	fmt.Printf("runtime.GOMAXPROCS(0)   = %d  (current P count; #P = GOMAXPROCS)\n", runtime.GOMAXPROCS(0))

	baseline := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (baseline) = %d  (includes runtime G's: GC, scavenger, ...)\n", baseline)

	// Launch k goroutines that each signal "started" then block on <-release.
	const k = 4
	started := make(chan struct{}, k)
	release := make(chan struct{})
	var wg sync.WaitGroup
	wg.Add(k)
	for range k {
		go func() {
			defer wg.Done()
			started <- struct{}{}
			<-release // block here: this G is live but not runnable
		}()
	}
	for range k {
		<-started // drain: guarantees all k goroutines exist before we measure
	}
	during := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (+%d blocked G's) = %d  (delta = %d)\n", k, during, during-baseline)

	close(release) // unblock the receivers (closed-channel receive returns zero)
	wg.Wait()
	after := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (after join)   = %d  (blocked G's terminated)\n", after)

	check("NumGoroutine() > 0 (runtime goroutines always exist)", baseline > 0)
	check("blocked goroutines strictly increased NumGoroutine", during > baseline)
	check("NumGoroutine fell back once the goroutines joined", after < during)
}

// cpuWorkload runs a deterministic CPU-bound workload under a fixed GOMAXPROCS
// and returns the sorted per-goroutine partials plus their total. It restores
// the previous GOMAXPROCS on return so later sections are unaffected. No timing
// is measured — only work counts — so the result is reproducible.
func cpuWorkload(maxp int) (partials []int64, total int64) {
	prev := runtime.GOMAXPROCS(maxp)
	defer runtime.GOMAXPROCS(prev)

	const n, step = 8, 100
	var (
		mu sync.Mutex
		wg sync.WaitGroup
	)
	wg.Add(n)
	for i := range n {
		go func(i int) {
			defer wg.Done()
			lo := int64(i*step + 1)
			hi := int64((i + 1) * step)
			var sum int64
			for v := lo; v <= hi; v++ {
				sum += v
			}
			mu.Lock()
			partials = append(partials, sum)
			mu.Unlock()
		}(i)
	}
	wg.Wait()
	slices.Sort(partials)
	for _, p := range partials {
		total += p
	}
	return partials, total
}

// sectionC demonstrates that GOMAXPROCS bounds PARALLELISM, not the result.
// The same workload run under GOMAXPROCS=1 (serialized) and GOMAXPROCS=NumCPU
// (parallel) produces byte-identical sorted partials and the same total; only
// the wall-clock time differs, which we deliberately do NOT print.
func sectionC() {
	sectionBanner("C — GOMAXPROCS bounds PARALLELISM, not the result")

	fmt.Println("GOMAXPROCS=1     : at most ONE goroutine runs at a time (concurrency, no parallelism)")
	fmt.Printf("GOMAXPROCS=NumCPU: up to %d goroutines run simultaneously (true parallelism)\n", runtime.NumCPU())

	p1, t1 := cpuWorkload(1)
	pn, tn := cpuWorkload(runtime.NumCPU())

	fmt.Printf("workload under GOMAXPROCS=1      -> total = %d, sorted partials = %v\n", t1, p1)
	fmt.Printf("workload under GOMAXPROCS=NumCPU -> total = %d, sorted partials = %v\n", tn, pn)

	const n, step = 8, 100
	expected := int64(n*step) * int64(n*step+1) / 2 // sum(1..800)
	check("both runs produce the SAME total (parallelism != correctness)", t1 == tn)
	check("total == sum(1..800) = 320400 (GOMAXPROCS-independent)", t1 == expected)
	check("both runs produce byte-identical sorted partials",
		fmt.Sprintf("%v", p1) == fmt.Sprintf("%v", pn))
}

// sectionD shows the SAFE pattern for observing a goroutine's result: main must
// RECEIVE (or WaitGroup.Wait) before returning. If main returned first, the
// program would exit and every goroutine would be killed mid-flight — its result
// discarded. The dangerous version is documented in the .md (and as a comment
// below); it is not run, because running it would make this file nondeterministic
// (the lost output is timing-dependent).
func sectionD() {
	sectionBanner("D — main returning kills goroutines (synchronize or lose work)")

	// SAFE: a buffered result channel + a blocking receive in main.
	result := make(chan int, 1)
	go func() {
		result <- 7 * 6 // return values are otherwise discarded (Go spec)
	}()
	got := <-result // main blocks here until the goroutine completes and sends
	fmt.Printf("go func(){ result <- 7*6 }();  got := <-result  -> got = %d\n", got)

	// DANGEROUS (NOT run): if main returned between launching the goroutine and
	// the receive, the goroutine would be terminated at program exit and 42
	// silently discarded — no panic, no error:
	//
	//   go func() { result <- 7 * 6 }()
	//   // (main returns here -> program exits -> goroutine is killed)
	//
	// The Go spec (Go statements): "When the function terminates, its goroutine
	// also terminates. If the function has any return values, they are discarded
	// when the function completes."

	check("goroutine result observed via channel receive", got == 42)
}

// sectionE demonstrates a goroutine leak: a goroutine blocked on a receive from
// a channel nobody ever sends to is never reclaimed until program exit. We
// observe NumGoroutine rising when the blocked goroutines appear, then show the
// fix (close the channel, which unblocks every receiver) and watch the count
// fall back. No leak survives past this section.
func sectionE() {
	sectionBanner("E — goroutine leak: a blocked G is never reclaimed until exit")

	before := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (before leak) = %d\n", before)

	const k = 3
	leak := make(chan struct{}) // nobody ever sends -> receivers block forever
	started := make(chan struct{}, k)
	var wg sync.WaitGroup
	wg.Add(k)
	for range k {
		go func() {
			defer wg.Done()
			started <- struct{}{}
			<-leak // BLOCKED forever (no sender): this G has leaked
		}()
	}
	for range k {
		<-started // ensure all k are live and blocked before measuring
	}
	afterLeak := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (after %d blocked receivers) = %d  (delta = %d)\n", k, afterLeak, afterLeak-before)
	check("NumGoroutine strictly increased (leaked goroutines persist)", afterLeak > before)

	// THE FIX: close(leak) makes every blocked receive return the zero value
	// immediately, so the goroutines fall through and exit. In production the
	// equivalent is context cancellation (the producer's side of the contract).
	close(leak)
	wg.Wait()
	recovered := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (after close(leak) unblocked them) = %d  (fell from peak)\n", recovered)
	check("unblocking the channel let the goroutines exit (count fell)", recovered < afterLeak)
}

func main() {
	fmt.Println("goroutines.go — Phase 3 bundle (the GMP scheduler).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Goroutine output is collected under a mutex, SORTED, and")
	fmt.Println("printed from main after every goroutine joins -> byte-identical runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
