//go:build ignore

// atomic_state.go — Phase 3 bundle (lock-free state).
//
// GOAL (one line): show, by printing every total, how sync/atomic provides
// lock-free primitives (Add/Load/Store/Swap/CompareAndSwap, atomic.Pointer[T],
// atomic.Value), how sync.Map serves read-heavy maps, how a singleflight clone
// dedupes identical concurrent calls, and when a mutex beats atomic.
//
// This is the GROUND TRUTH for ATOMIC_STATE.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// DETERMINISM (critical for this bundle): goroutine scheduling is intentionally
// nondeterministic, so NO goroutine ever prints and NO per-goroutine order is
// asserted. Every section asserts only TOTALS / SETS that are invariant under
// any interleaving: the atomic counter always reaches exactly N; the CAS loop
// always reaches exactly N; readers never observe a torn snapshot; sync.Map
// always ends with the same key set; singleflight always computes exactly once;
// a mutex-guarded transfer always conserves the total. Two runs of `just out
// atomic_state` are byte-identical.
//
// STDLIB-FIRST: only fmt, runtime, slices, strconv, sync, sync/atomic are used.
// singleflight lives in golang.org/x/sync/singleflight (NOT stdlib), so a tiny
// equivalent is implemented from scratch here (sync + sync/atomic + a map) for
// the educational value — no third-party import.
//
// Run:
//
//	go run atomic_state.go

package main

import (
	"fmt"
	"runtime"
	"slices"
	"strconv"
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

// sum returns the total of a slice of int64 (used by the transfer section).
func sum(a []int64) int64 {
	var s int64
	for _, x := range a {
		s += x
	}
	return s
}

// sectionA demonstrates the atomic integer API on a single int64, then a
// race-free counter: 1000 goroutines each AddInt64(&c, 1) and the final value is
// EXACTLY 1000. The atomic ops give a happens-before edge (memory model) without
// any mutex; the equivalent `c++` (a plain read-modify-write) is a DATA RACE the
// race detector flags (documented in the .md, not run here).
//
// Value-vs-pointer: every atomic function takes a *int64 — a pointer to the
// machine word — because it must read/modify the SAME memory as other goroutines
// via a single hardware instruction (e.g. LOCK XADD on amd64).
func sectionA() {
	sectionBanner("A — Atomic integer counter (Add/Load/Store/Swap, race-free)")

	// --- API tour on one int64 (single-threaded, so fully deterministic) -----
	var n int64
	atomic.StoreInt64(&n, 10)
	v := atomic.LoadInt64(&n)
	old := atomic.SwapInt64(&n, 99) // returns the PREVIOUS value (10); n is now 99
	added := atomic.AddInt64(&n, 1) // n is now 100; returns the new value
	fmt.Println("API tour on one int64 (single-threaded):")
	fmt.Printf("  StoreInt64(&n, 10); LoadInt64 -> %d\n", v)
	fmt.Printf("  SwapInt64(&n, 99)   -> previous %d (n now 99)\n", old)
	fmt.Printf("  AddInt64(&n, 1)     -> new %d\n", added)
	check("StoreInt64 then LoadInt64 == 10", v == 10)
	check("SwapInt64 returns the previous value 10", old == 10)
	check("AddInt64(&n,1) after Swap to 99 yields 100", added == 100)

	// --- Concurrent counter: 1000 goroutines, each AddInt64(&c, 1) ----------
	const goroutines = 1000
	var c int64
	var wg sync.WaitGroup
	wg.Add(goroutines)
	for range goroutines {
		go func() {
			defer wg.Done()
			atomic.AddInt64(&c, 1)
		}()
	}
	wg.Wait()
	final := atomic.LoadInt64(&c)
	fmt.Printf("\n%d goroutines, each atomic.AddInt64(&c, 1) -> final == %d\n", goroutines, final)
	check("atomic counter == 1000 (exactly, no lost updates)", final == goroutines)
	check("atomic counter lost no increments (final not < 1000)", final >= goroutines)
}

// sectionB builds a lock-free counter from a CompareAndSwap (CAS) retry loop:
//
//	for { old := Load(&p); new := f(old); if CompareAndSwap(&p, old, new) { break } }
//
// CAS atomically writes `new` only if the current value still equals `old`,
// returning whether it won the race. On failure another goroutine raced ahead,
// so the loop reloads and retries. The NUMBER of retries is scheduling-dependent
// (never printed); only the FINAL total — always exactly N — is asserted.
func sectionB() {
	sectionBanner("B — CAS retry loop (lock-free update)")

	const n = 1000
	var c int64
	var wg sync.WaitGroup
	wg.Add(n)
	for range n {
		go func() {
			defer wg.Done()
			for {
				old := atomic.LoadInt64(&c)
				new := old + 1
				if atomic.CompareAndSwapInt64(&c, old, new) {
					break // won the race; our increment is committed
				}
				// CAS failed: another goroutine changed `c` under us -> retry.
			}
		}()
	}
	wg.Wait()
	final := atomic.LoadInt64(&c)
	fmt.Printf("%d goroutines increment via a CAS retry loop -> final == %d\n", n, final)
	fmt.Println("(retry count is scheduling-dependent and therefore NOT printed; only the total is asserted)")
	check("CAS-loop counter final == 1000", final == n)
	check("CAS-loop counter >= 1000 (no lost increments)", final >= n)
}

// config is the value published atomically in section C. Its `greeting` encodes
// its `version`, so a reader can detect a "torn" snapshot (fields from two
// different generations) by checking the pair is self-consistent.
type config struct {
	version  int
	greeting string
}

func newConfig(v int) *config {
	return &config{version: v, greeting: "v" + strconv.Itoa(v)}
}

// consistent reports whether a snapshot is internally coherent. atomic.Pointer
// publishes a whole *config with one pointer swap, so a reader always sees one
// complete generation — this is never false under atomic access.
func (c *config) consistent() bool {
	return c.greeting == "v"+strconv.Itoa(c.version)
}

// sectionC shows atomic.Pointer[T] (Go 1.19+): a type-safe generic atomic
// pointer. Store publishes a *config atomically; Load reads it without locks.
// Many readers run alongside a single updater; because the whole struct is
// published via a single pointer swap, NO reader ever sees a torn {version,
// greeting} pair. Readers never block the writer (lock-free reads).
//
// Value-vs-pointer: atomic.Pointer[config] holds a *config. Store takes *config
// and publishes it wholesale; Load returns *config. You swap entire immutable
// snapshots rather than mutating fields in place — this is the lock-free config
// pattern (atomic.Value's typed successor for pointer cases).
func sectionC() {
	sectionBanner("C — atomic.Pointer[T]: typed snapshot, lock-free readers")

	var ptr atomic.Pointer[config]
	ptr.Store(newConfig(1)) // initial generation; never nil from here on

	const (
		readers = 8
		iters   = 1000
	)
	var (
		ok   int64 // snapshots that were internally consistent
		torn int64 // snapshots mixing two generations (impossible under atomic)
		wg   sync.WaitGroup
	)

	// One updater publishes 1->2->3 three times, ending at generation 3. Being a
	// single goroutine, its LAST Store is deterministic -> the final snapshot is
	// always generation 3.
	wg.Add(1)
	go func() {
		defer wg.Done()
		for range 3 {
			for v := 1; v <= 3; v++ {
				ptr.Store(newConfig(v))
			}
		}
	}()

	// Readers Load a snapshot and verify consistency; they take no lock and never
	// block the updater. Each Load returns a coherent *config (old or new).
	wg.Add(readers)
	for range readers {
		go func() {
			defer wg.Done()
			for range iters {
				c := ptr.Load()
				if c.consistent() {
					atomic.AddInt64(&ok, 1)
				} else {
					atomic.AddInt64(&torn, 1)
				}
			}
		}()
	}
	wg.Wait()

	final := ptr.Load()
	fmt.Printf("%d readers x %d Loads each (%d total) racing one updater\n", readers, iters, readers*iters)
	fmt.Printf("consistent snapshots: %d   torn snapshots: %d (atomic.Pointer publishes whole structs)\n",
		atomic.LoadInt64(&ok), atomic.LoadInt64(&torn))
	fmt.Printf("final snapshot after updater joined -> version %d, greeting %q\n", final.version, final.greeting)
	check("every snapshot was consistent (0 torn reads)", atomic.LoadInt64(&torn) == 0)
	check("snapshot count == readers*iters (8000)", atomic.LoadInt64(&ok)+atomic.LoadInt64(&torn) == int64(readers*iters))
	check("final snapshot is generation 3 (single updater, deterministic last Store)", final.version == 3)
}

// sectionD uses sync.Map: a concurrent map optimized for read-heavy / write-light
// workloads where keys are stable (written once, read many). N goroutines each
// LoadOrStore a key; exactly one store wins per key, the rest Load the existing
// value. Range order is intentionally RANDOM, so keys are collected and SORTED
// before printing for byte-identical output.
//
// Value-vs-pointer: sync.Map carries internal state, so it must NOT be copied
// after first use — always operate on a *sync.Map (here a stack value addressed
// by the methods is fine because we never copy it across the goroutines).
func sectionD() {
	sectionBanner("D — sync.Map: concurrent LoadOrStore (read-heavy workload)")

	var m sync.Map
	const (
		keys    = 8
		callers = 16 // 2 callers per key -> exactly 1 store + 1 load per key
	)
	var (
		stores int64 // LoadOrStore that STORED (loaded == false)
		loads  int64 // LoadOrStore that LOADED an existing value (loaded == true)
		wg     sync.WaitGroup
	)
	wg.Add(callers)
	for i := range callers {
		go func(i int) {
			defer wg.Done()
			key := "k" + strconv.Itoa(i%keys)
			_, loaded := m.LoadOrStore(key, i) // value is the caller index
			if loaded {
				atomic.AddInt64(&loads, 1)
			} else {
				atomic.AddInt64(&stores, 1)
			}
		}(i)
	}
	wg.Wait()

	// Range visits keys in RANDOM order -> collect, then SORT for stable output.
	got := make([]string, 0, keys)
	m.Range(func(k, _ any) bool {
		got = append(got, k.(string))
		return true
	})
	slices.Sort(got)

	expected := make([]string, keys)
	for i := range keys {
		expected[i] = "k" + strconv.Itoa(i)
	}
	fmt.Printf("%d callers LoadOrStore across %d keys (2 callers/key) -> %d stores, %d loads\n",
		callers, keys, atomic.LoadInt64(&stores), atomic.LoadInt64(&loads))
	fmt.Printf("sorted keys after Range -> %v\n", got)
	check("sync.Map holds all 8 keys", len(got) == keys)
	check("sorted keys == [k0 k1 k2 k3 k4 k5 k6 k7]", fmt.Sprint(got) == fmt.Sprint(expected))
	check("exactly 8 stores (one winner per key)", atomic.LoadInt64(&stores) == keys)
	check("exactly 8 loads (one duplicate per key)", atomic.LoadInt64(&loads) == callers-keys)
}

// --- singleflight-equivalent (built from scratch; stdlib only) ----------------
//
// singleflight dedupes concurrent identical calls: if N callers ask for the same
// key while one computation is in-flight, the computation runs ONCE and every
// caller shares the result. The real type is golang.org/x/sync/singleflight.Group
// (NOT stdlib); this minimal clone mirrors its design — a mutex-guarded map of
// key -> *call, where a late caller attaches to the existing call and waits on
// its WaitGroup instead of recomputing.

// call is one in-flight (or completed) computation for a key.
type call struct {
	wg      sync.WaitGroup // late callers Wait on this; the leader Done's it
	waiters int64          // # Do callers attached to this call (leader counts as 1)
	val     int            // the shared result
}

// sfGroup is a minimal singleflight.Group: duplicate-suppressing memoization.
type sfGroup struct {
	mu sync.Mutex
	m  map[string]*call
}

// do runs fn for `key` exactly once among concurrent callers, sharing the result.
// `total` is the expected number of concurrent callers; the leader waits until
// all of them have attached before computing, so the "exactly once" outcome is
// deterministic regardless of scheduling (no caller can arrive after a cleanup
// and trigger a second compute). Returns (value, isLeader).
func (g *sfGroup) do(key string, total int64, fn func() int) (int, bool) {
	g.mu.Lock()
	if g.m == nil {
		g.m = make(map[string]*call)
	}
	if c, ok := g.m[key]; ok {
		// A call is already in-flight: attach and wait for the shared result.
		atomic.AddInt64(&c.waiters, 1)
		g.mu.Unlock()
		c.wg.Wait()
		return c.val, false
	}
	// First caller for this key: register the call and become the leader.
	c := &call{}
	c.wg.Add(1)
	atomic.StoreInt64(&c.waiters, 1)
	g.m[key] = c
	g.mu.Unlock()

	// Wait until EVERY concurrent caller has attached, so they all share this
	// compute and none can miss it (guaranteeing exactly-one computation).
	for atomic.LoadInt64(&c.waiters) < total {
		runtime.Gosched()
	}
	c.val = fn()
	c.wg.Done() // wake every attached waiter

	g.mu.Lock()
	delete(g.m, key)
	g.mu.Unlock()
	return c.val, true
}

// sectionE runs N goroutines that all request the SAME key. singleflight runs the
// computation EXACTLY ONCE and shares the result; all N callers receive it. The
// compute-count (1) and the shared value are deterministic under any scheduling.
func sectionE() {
	sectionBanner("E — singleflight (from scratch): N callers, ONE computation")

	const callers = 10
	var (
		g           sfGroup
		computeRuns int64 // # times the expensive function actually executed
		successes   int64 // # callers that received the correct shared value
		wg          sync.WaitGroup
	)
	const want = 499500 // sum(0..999)

	wg.Add(callers)
	for range callers {
		go func() {
			defer wg.Done()
			got, _ := g.do("expensive-key", int64(callers), func() int {
				atomic.AddInt64(&computeRuns, 1) // runs in the leader only
				var s int
				for i := 0; i < 1000; i++ { // "expensive" work
					s += i
				}
				return s
			})
			if got == want {
				atomic.AddInt64(&successes, 1)
			}
		}()
	}
	wg.Wait()

	fmt.Printf("%d callers request the SAME key concurrently via singleflight\n", callers)
	fmt.Printf("expensive function executed: %d time(s) (dedup worked -> all callers shared one compute)\n",
		atomic.LoadInt64(&computeRuns))
	fmt.Printf("callers that received the shared result == %d: %d/%d\n", want, atomic.LoadInt64(&successes), callers)
	check("singleflight computed exactly once", atomic.LoadInt64(&computeRuns) == 1)
	check("all 10 callers received the shared result", atomic.LoadInt64(&successes) == callers)
}

// sectionF contrasts WHEN to use atomic vs mutex.
//   - A SINGLE counter/flag/pointer -> atomic (section A): one word, one
//     invariant, no critical section needed.
//   - A MULTI-FIELD invariant -> mutex. A bank transfer must debit one account
//     AND credit another as one indivisible step so the TOTAL is always
//     conserved (and so an auditor summing balances never sees a half-applied
//     transfer). Independent atomic ops on each field cannot make the two
//     updates, nor a check-then-act, appear atomic to other goroutines.
//
// Only the conserved TOTAL is asserted (individual balances are scheduling-
// dependent and therefore not printed).
func sectionF() {
	sectionBanner("F — atomic vs mutex: single counter vs multi-field invariant")

	// Case 1: a single counter -> ATOMIC is the right tool (one word, one op).
	var counter int64
	atomic.AddInt64(&counter, 42)
	fmt.Printf("single counter (atomic): AddInt64(&c, 42) -> %d  (one word, no lock needed)\n", atomic.LoadInt64(&counter))
	check("single counter via atomic == 42", atomic.LoadInt64(&counter) == 42)

	// Case 2: a transfer between TWO accounts -> MUTEX, because the invariant
	// (total conserved; observers see a consistent snapshot) spans both fields.
	accounts := []int64{100, 200, 300}
	var mu sync.Mutex
	total0 := sum(accounts) // 600
	const (
		groups        = 10
		transfersEach = 100
	)
	var wg sync.WaitGroup
	wg.Add(groups)
	for g := range groups {
		go func(g int) {
			defer wg.Done()
			for k := range transfersEach {
				src := (g + k) % len(accounts)
				dst := (src + 1) % len(accounts)
				mu.Lock()
				accounts[src] -= 1 // debit ...
				accounts[dst] += 1 // ... and credit, as ONE critical section
				mu.Unlock()
			}
		}(g)
	}
	wg.Wait()
	total1 := sum(accounts)
	fmt.Printf("transfer: 3 accounts {%d %d %d}, total before = %d\n", 100, 200, 300, total0)
	fmt.Printf("%d groups x %d mutex-guarded transfers -> total after = %d (conserved)\n",
		groups, transfersEach, total1)
	check("initial total == 600", total0 == 600)
	check("final total == 600 (multi-field invariant conserved by mutex)", total1 == 600)
	check("total conserved across all transfers (before == after)", total0 == total1)
}

func main() {
	fmt.Println("atomic_state.go — Phase 3 bundle (lock-free state).")
	fmt.Println("Every total below is computed by this file; the .md guide pastes it")
	fmt.Println("verbatim. No goroutine prints; only scheduling-invariant totals are")
	fmt.Println("asserted -> byte-identical runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
