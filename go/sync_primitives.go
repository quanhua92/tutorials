//go:build ignore

// sync_primitives.go — Phase 3 bundle (sync: Mutex, RWMutex, Once, WaitGroup,
// Cond, Pool + the memory model & the race detector).
//
// GOAL (one line): show, by printing every value, how the sync package's
// primitives establish the HAPPENS-BEFORE edges that make concurrent code
// correct — and how the race detector catches the absence of those edges.
//
// This is the GROUND TRUTH for SYNC_PRIMITIVES.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// DETERMINISM (critical for this bundle): goroutine scheduling is intentionally
// nondeterministic, so NO goroutine ever prints directly. Every goroutine writes
// its result into a mutex-guarded slice (or signals via a channel/WaitGroup);
// main SORTS the collected results and prints them only AFTER every goroutine
// joins. Only scheduling-independent quantities (a final counter, a sorted
// result set, a boolean invariant) are printed, so two runs of
// `just out sync_primitives` are byte-identical. RNG is not used.
//
// Run:
//
//	go run sync_primitives.go
//
// RACE-CHECK: this file ships only DATA-RACE-FREE code; verify with
//
//	go run -race sync_primitives.go
//
// (it must report nothing). The racing variant is documented in comments, never
// executed — running it would (correctly) trigger "WARNING: DATA RACE".

package main

import (
	"fmt"
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

// --- scratch object reused by section F (sync.Pool) -------------------------

// scratch is a tiny reusable buffer. sync.Pool's New should return a POINTER so
// it can be boxed into the `any` return value of Get without an allocation.
type scratch struct {
	buf []byte
}

// bufPool is the canonical sync.Pool: it hands out scratch buffers and reclaims
// them via Put to relieve GC pressure. It is NOT a reliable cache — see §F.
var bufPool = sync.Pool{
	New: func() any { return &scratch{buf: make([]byte, 0, 16)} },
}

// sectionA proves the memory-model payoff. Part 1: 1000 goroutines each
// increment a shared counter under a sync.Mutex. The program is DATA-RACE-FREE,
// so by the DRF-SC guarantee (go.dev/ref/mem) it behaves as a sequentially
// consistent interleaving and the counter lands on exactly 1000 — no lost
// updates. Each Unlock "synchronizes before" the next Lock, so every increment
// is visible. Part 2 reproduces the memory model's canonical Lock example to
// prove the Unlock->Lock happens-before edge directly.
func sectionA() {
	sectionBanner("A — Memory model: a Mutex makes a data race impossible")

	// Part 1 — a Mutex-guarded counter incremented by 1000 goroutines.
	const n = 1000
	var (
		mu      sync.Mutex
		counter int
		wg      sync.WaitGroup
	)
	wg.Add(n)
	for range n {
		go func() {
			defer wg.Done()
			mu.Lock()
			counter++ // safe: exactly one goroutine holds the lock at a time
			mu.Unlock()
		}()
	}
	wg.Wait()
	fmt.Printf("1000 goroutines x counter++ under sync.Mutex -> counter = %d\n", counter)
	check("mutex-guarded counter == 1000 (no lost updates)", counter == n)

	// Part 2 — the memory model's canonical Lock example (go.dev/ref/mem, "Locks"):
	// the n'th Unlock "synchronizes before" the m'th Lock returns (n < m), so the
	// read after the second Lock is GUARANTEED to observe the write before the
	// Unlock. main Locks first (holds the lock), the goroutine writes `a` then
	// Unlocks (releasing it), main's second Lock returns only AFTER that Unlock.
	var (
		l  sync.Mutex
		a  string
		hb sync.WaitGroup
	)
	hb.Add(1)
	l.Lock() // main holds the lock
	go func() {
		defer hb.Done()
		a = "hello, world"
		l.Unlock() // release -> synchronized-before the next Lock returns
	}()
	l.Lock() // blocks until the goroutine Unlocks; returns AFTER the write to `a`
	hb.Wait()
	fmt.Printf("happens-before (Unlock -> next Lock): main observed a = %q\n", a)
	check("Unlock happens-before the next Lock (main saw the goroutine's write)", a == "hello, world")

	// The UNSAFE variant is deliberately NOT run — it would be a data race.
	// Dropping the Lock/Unlock lets every goroutine read-modify-write `counter`
	// with no happens-before edge; the memory model makes the result UNDEFINED,
	// and in practice counter < 1000 (lost updates). `go run -race` instruments
	// the binary (ThreadSanitizer) and prints, for the conflicting pair:
	//
	//     WARNING: DATA RACE
	//     Read by goroutine N:
	//       main.sectionA.func1   sync_primitives.go:LL +0xNN
	//     Previous write by goroutine M:
	//       main.sectionA.func1   sync_primitives.go:LL +0xNN
	//
	// The fix is exactly the Lock/Unlock in Part 1: serialize the accesses so a
	// happens-before edge exists between every pair of them.
	fmt.Println("UNSAFE variant (documented, not run): no Lock -> data race; `go run -race` prints \"WARNING: DATA RACE\"")
}

// sectionB contrasts sync.Mutex (one-at-a-time for everyone) with sync.RWMutex
// (many concurrent READERS, or a single WRITER). A read-heavy workload — several
// readers plus a few writers on a shared counter — runs under an RWMutex:
// readers take RLock/RUnlock (they may overlap), the writer takes Lock/Unlock
// (exclusive). Only scheduling-independent facts are asserted: the final value
// equals the number of writes, and every read observed a value in [0, writes]
// (RWMutex never lets a reader share state with a writer -> no torn reads).
func sectionB() {
	sectionBanner("B — RWMutex: many concurrent readers OR one writer")

	const (
		readers = 8
		writes  = 5
	)
	var (
		rw         sync.RWMutex
		value      int
		wg         sync.WaitGroup
		mu         sync.Mutex // guards `reads` and `allInRange`
		reads      int
		allInRange = true
	)

	// Writer: set value = 1..writes (exclusive Lock each time).
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 1; i <= writes; i++ {
			rw.Lock()
			value = i
			rw.Unlock()
		}
	}()

	// Readers: each takes a read lock and snapshots value. Multiple readers may
	// hold RLock simultaneously; a blocked Lock excludes new readers.
	wg.Add(readers)
	for range readers {
		go func() {
			defer wg.Done()
			rw.RLock()
			v := value
			rw.RUnlock()
			mu.Lock()
			reads++
			if v < 0 || v > writes {
				allInRange = false
			}
			mu.Unlock()
		}()
	}
	wg.Wait()

	fmt.Printf("RWMutex: %d readers + %d writers on a shared counter\n", readers, writes)
	fmt.Printf("final value = %d   reads completed = %d   every read in [0, %d]: %v\n",
		value, reads, writes, allInRange)
	check("RWMutex final value == 5 (every write applied exactly once)", value == writes)
	check("all 8 readers completed", reads == readers)
	check("every read observed a value in [0, 5] (RWMutex excludes readers from the writer)", allInRange)
}

// sectionC proves sync.Once.Do runs its argument EXACTLY ONCE across all
// callers, even when N goroutines race to be the "first". The memory model
// guarantees the single call to f completes before ANY Do call returns, so the
// value f wrote is visible to every caller with no extra lock — that is why
// `runs` (written once by f, read by main after the WaitGroup joins) is
// race-free.
func sectionC() {
	sectionBanner("C — sync.Once: the initializer runs EXACTLY once")

	const n = 100
	var (
		once sync.Once
		runs int
		cfg  string
		wg   sync.WaitGroup
	)
	init := func() { // runs in exactly one goroutine
		runs++
		cfg = "initialized"
	}
	wg.Add(n)
	for range n {
		go func() {
			defer wg.Done()
			once.Do(init) // only the first caller runs init; the rest block until it returns
		}()
	}
	wg.Wait()
	fmt.Printf("%d goroutines called once.Do(init); init ran %d time(s); cfg = %q\n", n, runs, cfg)
	check("Once.Do ran the initializer exactly once (runs == 1)", runs == 1)
	check("value written by Once.Do is visible to all callers (no extra lock needed)", cfg == "initialized")
}

// sectionD exercises sync.WaitGroup: Add(N) BEFORE launching, Done() via defer
// inside each goroutine, Wait() to join them all. The memory model makes each
// Done "synchronize before" the Wait it unblocks, so reading the collected
// results after Wait is race-free.
func sectionD() {
	sectionBanner("D — WaitGroup: Add(N) first, Done in defer, Wait joins all")

	const n = 10
	var (
		wg      sync.WaitGroup
		mu      sync.Mutex // guards `results`
		results []int
	)
	wg.Add(n) // Add BEFORE the `go` statements
	for i := range n {
		go func(i int) {
			defer wg.Done() // Done via defer -> runs even on a panic
			v := i * i
			mu.Lock()
			results = append(results, v)
			mu.Unlock()
		}(i)
	}
	wg.Wait()
	slices.Sort(results) // goroutine completion order is nondeterministic -> sort
	fmt.Printf("WaitGroup: launched %d goroutines (i*i); sorted results = %v\n", n, results)
	check("all 10 results present and sorted == [0 1 4 9 16 25 36 49 64 81]",
		fmt.Sprintf("%v", results) == "[0 1 4 9 16 25 36 49 64 81]")
	check("len(results) == 10 (Wait joined every goroutine)", len(results) == n)
}

// sectionE demonstrates sync.Cond: a producer signals when a shared queue
// becomes non-empty; a consumer Waits in the canonical for !condition() loop.
// Wait atomically unlocks the Locker and suspends; on wake it re-locks before
// returning. An unbuffered handshake channel guarantees the consumer is parked
// in Wait before the producer enqueues, keeping the run deterministic.
func sectionE() {
	sectionBanner("E — Cond: producer signals, consumer Waits in a loop")

	var (
		mu    sync.Mutex
		cond  = sync.NewCond(&mu)
		queue []int
	)
	consumerReady := make(chan struct{})
	var (
		wg       sync.WaitGroup
		consumed []int
	)
	wg.Add(1)
	go func() { // consumer
		defer wg.Done()
		mu.Lock()
		defer mu.Unlock()
		consumerReady <- struct{}{} // "I hold the lock and am about to Wait"
		for len(queue) == 0 {       // MUST re-check: Wait can return without the condition holding
			cond.Wait() // atomically: unlock mu, suspend, re-lock mu on wake
		}
		consumed = append(consumed, queue...)
		queue = queue[:0]
	}()
	<-consumerReady // ensure the consumer is parked in Wait before we produce
	mu.Lock()
	queue = append(queue, 11, 22, 33)
	cond.Signal() // wake exactly one waiter (there is one)
	mu.Unlock()
	wg.Wait()
	slices.Sort(consumed)
	fmt.Printf("Cond: producer enqueued 3 items, consumer consumed (sorted) %v\n", consumed)
	check("Cond consumer consumed all signaled items [11 22 33]",
		fmt.Sprintf("%v", consumed) == "[11 22 33]")
}

// sectionF demonstrates sync.Pool: Get/Put reusable scratch objects to amortize
// allocation and relieve GC pressure. Get returns a previously-Put object when
// one is available, otherwise calls New. A Pool is NOT a reliable cache — any
// item may be removed automatically at any time (e.g. on GC) — so callers must
// Reset a returned object and never assume a later Get returns what they Put.
func sectionF() {
	sectionBanner("F — sync.Pool: reusable scratch objects (NOT a reliable cache)")

	// Get a scratch object, use it, reset it, Put it back.
	s1 := bufPool.Get().(*scratch) // Get returns `any`; assert the concrete type
	s1.buf = append(s1.buf, "hello pool"...)
	fmt.Printf("pool.Get() -> *scratch, wrote %q (len=%d cap=%d)\n", s1.buf, len(s1.buf), cap(s1.buf))
	s1.buf = s1.buf[:0] // reset before Put (the caller's contract)
	bufPool.Put(s1)

	// A second Get may return the just-Put s1 OR a freshly-New'd object — the
	// pool does not guarantee which. Either way it is a USABLE, zero-len buffer.
	s2 := bufPool.Get().(*scratch)
	s2.buf = append(s2.buf, "reused"...)
	fmt.Printf("pool.Get() again -> *scratch, wrote %q (len=%d cap=%d)\n", s2.buf, len(s2.buf), cap(s2.buf))
	bufPool.Put(s2)

	check("a pool-returned scratch object is writable", string(s2.buf) == "reused")
	check("pool.Get() returns a non-nil *scratch (New used, or an item reused)", s2 != nil)
}

func main() {
	fmt.Println("sync_primitives.go — Phase 3 bundle (sync + the memory model).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Goroutine output is collected under a mutex, SORTED,")
	fmt.Println("and printed from main after every goroutine joins -> byte-identical runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
