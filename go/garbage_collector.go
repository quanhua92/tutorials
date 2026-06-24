//go:build ignore

// garbage_collector.go — Phase 4 bundle #23.
//
// GOAL (one line): show, by measuring runtime.MemStats deltas and GC counts,
// how Go's concurrent tri-color mark-sweep garbage collector behaves, and how
// GOGC, GOMEMLIMIT, runtime.GC, finalizers, and sync.Pool affect it.
//
// This is the GROUND TRUTH for GARBAGE_COLLECTOR.md. Every number/delta below
// is computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM: absolute HeapAlloc bytes and heap addresses vary per run (they
// depend on sweep timing and ASLR), so this file asserts only RELATIVE deltas
// ("NumGC went up", "HeapObjects went up") and exact deterministic counters
// (NumGC, NumForcedGC, allocs/op, SetGCPercent/SetMemoryLimit return values).
// It never prints raw drifting bytes/durations. Two `just out garbage_collector`
// runs are byte-identical for every asserted quantity.
//
// Run:
//
//	go run garbage_collector.go

package main

import (
	"fmt"
	"math"
	"runtime"
	"strings"
	"sync"
	"testing"

	debug "runtime/debug"
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

// readStats wraps runtime.ReadMemStats. ReadMemStats briefly stops the world,
// so it is called deliberately at measurement points, never in a hot loop.
func readStats() runtime.MemStats {
	var m runtime.MemStats
	runtime.ReadMemStats(&m)
	return m
}

// Box is a fixed-size heap object used to grow the heap deterministically.
// 64 bytes of payload + an int: small enough to print, large enough to escape.
type Box struct {
	_ [64]byte
	n int
}

// globalSink forces heap allocation inside benchmarks: assigning to a package
// variable makes the address escape, defeating stack allocation.
var globalSink any

// sectionA introduces the tri-color algorithm and the runtime.MemStats lens.
// It allocates live heap objects and asserts the DIRECTION of HeapAlloc /
// HeapObjects (the byte counts themselves drift between runs and are not shown).
func sectionA() {
	sectionBanner("A — Tri-color mark-sweep & runtime.MemStats")

	fmt.Println("Go's GC is a CONCURRENT, NON-GENERATIONAL, NON-COMPACTING,")
	fmt.Println("tri-color MARK-AND-SWEEP collector:")
	fmt.Println("  WHITE = unscanned  (candidate for sweep)")
	fmt.Println("  GREY  = reachable, its pointers not yet scanned")
	fmt.Println("  BLACK = reachable, fully scanned (kept alive)")
	fmt.Println("Marking runs CONCURRENTLY with the mutator; only small STW")
	fmt.Println("(stop-the-world) windows occur at the start (sweep termination)")
	fmt.Println("and end (mark termination) of each cycle. Sweeping reclaims the")
	fmt.Println("WHITE objects. The WRITE BARRIER is enabled only while marking.")

	fmt.Println("\nruntime.MemStats key fields (measured here, asserted by direction):")
	fmt.Println("  HeapAlloc    bytes of allocated heap objects (live + not-yet-swept)")
	fmt.Println("  HeapObjects  count of allocated heap objects")
	fmt.Println("  NumGC        uint32, # of completed GC cycles (cumulative)")
	fmt.Println("  NumForcedGC  uint32, # of cycles forced by an application runtime.GC()")
	fmt.Println("  NextGC       target heap size; the goal is HeapAlloc <= NextGC")
	fmt.Println("  PauseTotalNs cumulative ns spent in STW pauses")

	before := readStats()
	fmt.Printf("  EnableGC (always true, even when GOGC=off): %v\n", before.EnableGC)

	// Allocate a fixed number of LIVE heap objects, then observe the DIRECTION
	// of the change. Raw byte counts are intentionally NOT printed (they drift).
	const n = 10000
	live := make([]*Box, n)
	for i := 0; i < n; i++ {
		live[i] = &Box{n: i}
	}
	var after runtime.MemStats
	runtime.ReadMemStats(&after)
	runtime.KeepAlive(live) // keep the set live until after the second read

	heapObjectsUp := after.HeapObjects > before.HeapObjects
	heapAllocUp := after.HeapAlloc > before.HeapAlloc
	fmt.Printf("\nallocated %d *Box into a live slice:\n", n)
	fmt.Printf("  HeapObjects went up? %v\n", heapObjectsUp)
	fmt.Printf("  HeapAlloc   went up? %v\n", heapAllocUp)
	fmt.Println("  (raw byte counts are runtime-dependent; only the delta is asserted)")

	check("MemStats.EnableGC is always true (even with GOGC=off)", before.EnableGC)
	check("NumGC is a cumulative, monotonic counter (after >= before)", after.NumGC >= before.NumGC)
	check(fmt.Sprintf("allocating %d live objects raised HeapObjects", n), heapObjectsUp)
	check(fmt.Sprintf("allocating %d live objects raised HeapAlloc", n), heapAllocUp)

	live = nil
	runtime.GC() // release the set before later sections
}

// sectionB forces explicit GC cycles and shows NumGC / NumForcedGC move by
// exactly the number of runtime.GC() calls (the most deterministic GC signal).
func sectionB() {
	sectionBanner("B — Force a cycle: runtime.GC() bumps NumGC/NumForcedGC")

	fmt.Println("runtime.GC() runs a full collection and BLOCKS until it completes,")
	fmt.Println("so each call completes exactly one cycle. NumGC counts every cycle;")
	fmt.Println("NumForcedGC counts only the application-forced ones — a precise")
	fmt.Println("signal that is byte-identical across runs.")

	const forced = 3
	before := readStats()
	for i := 0; i < forced; i++ {
		runtime.GC()
	}
	after := readStats()

	numGCDelta := int64(after.NumGC) - int64(before.NumGC)
	forcedDelta := int64(after.NumForcedGC) - int64(before.NumForcedGC)
	pauseNotDown := after.PauseTotalNs >= before.PauseTotalNs

	fmt.Printf("forced %d runtime.GC() calls:\n", forced)
	fmt.Printf("  NumGC       delta = %d  (>= %d; background cycles may add more)\n", numGCDelta, forced)
	fmt.Printf("  NumForcedGC delta = %d  (exactly the forced cycles)\n", forcedDelta)
	fmt.Printf("  PauseTotalNs did not decrease? %v  (STW pauses accumulate)\n", pauseNotDown)

	check(fmt.Sprintf("NumGC increased by >= %d after %d runtime.GC calls", forced, forced), numGCDelta >= forced)
	check(fmt.Sprintf("NumForcedGC increased by exactly %d", forced), forcedDelta == forced)
	check("PauseTotalNs is monotonic non-decreasing", pauseNotDown)
}

// sectionC demonstrates GOGC: with the collector disabled (GOGC=off) heavy
// allocation triggers ZERO cycles; with the default (100) it triggers >= 1.
func sectionC() {
	sectionBanner("C — GOGC: the live-heap-growth trigger")

	fmt.Println("GOGC (default 100) triggers a GC when the heap GROWS by GOGC% since")
	fmt.Println("the last sweep (at 100 it roughly doubles). GOGC=off disables automatic")
	fmt.Println("collection entirely (unless GOMEMLIMIT applies). debug.SetGCPercent")
	fmt.Println("returns the PREVIOUS value. Target heap = LiveHeap + (LiveHeap + GC")
	fmt.Println("roots) * GOGC/100 (roots counted since Go 1.18); minimum heap 4 MiB.")

	// (1) Round-trip: SetGCPercent returns the previous value on every call.
	initialPct := debug.SetGCPercent(-1)      // disable; returns the prior % (default 100)
	echoOff := debug.SetGCPercent(initialPct) // re-enable;  returns -1 (it was off)
	echoBack := debug.SetGCPercent(-1)        // disable;    returns initialPct again
	debug.SetGCPercent(initialPct)            // leave GC enabled at the original setting
	fmt.Printf("SetGCPercent round-trip: initial=%d  offEcho=%d  backEcho=%d\n",
		initialPct, echoOff, echoBack)
	check("SetGCPercent(-1) then restore echoes -1 (it was off)", echoOff == -1)
	check("SetGCPercent round-trips back to the initial value", echoBack == initialPct)

	// (2) With GC OFF, heavy allocation triggers NO cycles.
	const chunk = 1 << 20 // 1 MiB
	debug.SetGCPercent(-1)
	before := readStats()
	trash := make([][]byte, 0, 64)
	for i := 0; i < 64; i++ {
		trash = append(trash, make([]byte, chunk)) // ~64 MiB allocated, none collected
	}
	runtime.KeepAlive(trash) // keep the 64 MiB live across the stats read
	offDelta := int64(readStats().NumGC) - int64(before.NumGC)
	fmt.Printf("GOGC=off, allocated ~64 MiB -> NumGC delta = %d (no automatic GC)\n", offDelta)
	check("with GOGC=off, allocating ~64 MiB triggered 0 GC cycles", offDelta == 0)
	trash = nil
	debug.SetGCPercent(initialPct) // restore default
	runtime.GC()                   // reclaim the 64 MiB

	// (3) With GC ON (default), the SAME allocation triggers >= 1 cycle.
	before = readStats()
	trash = make([][]byte, 0, 64)
	for i := 0; i < 64; i++ {
		trash = append(trash, make([]byte, chunk))
	}
	runtime.KeepAlive(trash) // keep the 64 MiB live across the stats read
	onDelta := int64(readStats().NumGC) - int64(before.NumGC)
	fmt.Printf("GOGC=default(%d), allocated ~64 MiB -> NumGC delta = %d (>=1 automatic GC)\n", initialPct, onDelta)
	check("with GOGC enabled, allocating ~64 MiB triggered >= 1 GC cycle", onDelta >= 1)
	trash = nil
	runtime.GC()
}

// sectionD exercises the GOMEMLIMIT soft ceiling (Go 1.19+) via its API
// round-trip. The behavioral effect (GC works harder) needs huge allocations
// and timing to observe, so only the deterministic API contract is asserted.
func sectionD() {
	sectionBanner("D — GOMEMLIMIT: the soft memory ceiling (Go 1.19+)")

	fmt.Println("GOMEMLIMIT (debug.SetMemoryLimit, added in Go 1.19) sets a SOFT ceiling")
	fmt.Println("on total Go-runtime memory (MemStats.Sys - HeapReleased). It is enforced")
	fmt.Println("EVEN IF GOGC=off: the GC runs more often (up to ~50% CPU) to stay under")
	fmt.Println("it, which helps avoid OOM in memory-capped containers. It is SOFT on")
	fmt.Println("purpose: under extreme pressure the runtime lets memory exceed the limit")
	fmt.Println("rather than thrash (stall) the program. SetMemoryLimit returns the")
	fmt.Println("PREVIOUS limit; a NEGATIVE argument only queries, without changing it.")

	// Query is non-mutating: two consecutive negative reads agree.
	q1 := debug.SetMemoryLimit(-1)
	q2 := debug.SetMemoryLimit(-1)
	fmt.Printf("current memory limit: %d bytes  (math.MaxInt64 == disabled? %v)\n", q1, q1 == math.MaxInt64)

	const tryLimit = int64(1 << 30)        // 1 GiB
	prev := debug.SetMemoryLimit(tryLimit) // set; returns the prior limit
	now := debug.SetMemoryLimit(-1)        // query; should be tryLimit
	echo := debug.SetMemoryLimit(prev)     // restore; returns tryLimit (what we set)
	fmt.Printf("SetMemoryLimit(1 GiB) -> previous=%d  queryNow=%d  restoreEcho=%d\n", prev, now, echo)

	check("SetMemoryLimit(-1) is a non-mutating query (q1 == q2)", q1 == q2)
	check("SetMemoryLimit(N) takes effect (a query then returns N)", now == tryLimit)
	check("SetMemoryLimit returns the value that was previously set", echo == tryLimit)
	check("after restore, querying again equals the original limit", debug.SetMemoryLimit(-1) == prev)
}

// sectionE shows finalizers are observable after a forced GC but are NOT a
// reliable cleanup hook (timing undefined, not guaranteed at exit). It asserts
// only what is reproducible: that the callback can fire, and that the object is
// no longer referenced by the program.
func sectionE() {
	sectionBanner("E — Finalizers are NOT a reliable cleanup hook")

	fmt.Println("runtime.SetFinalizer attaches a callback that runs AFTER an object")
	fmt.Println("becomes unreachable and a GC sweeps it. But its timing is UNDEFINED")
	fmt.Println("and it is NOT guaranteed to run at process exit. Finalizers even")
	fmt.Println("RESURRECT the object (passing it in alive), so prefer defer / Close")
	fmt.Println("/ runtime.AddCleanup (1.24+). Here we only observe that it CAN fire.")

	ran := make(chan struct{}, 1)
	type fin struct{ id int }
	obj := &fin{id: 7}
	runtime.SetFinalizer(obj, func(f *fin) {
		_ = f // do not resurrect; just signal
		select {
		case ran <- struct{}{}:
		default:
		}
	})
	obj = nil // drop our reference -> the object becomes unreachable

	// Force GCs (and yield) until the finalizer fires or the bound is hit.
	// The exact cycle count is scheduling-dependent, so only the boolean is
	// reported (byte-identical across runs).
	fired := false
	for cycles := 0; cycles < 20; cycles++ {
		runtime.GC()
		runtime.Gosched()
		select {
		case <-ran:
			fired = true
		default:
		}
		if fired {
			break
		}
	}
	fmt.Printf("finalizer fired within a bounded GC loop? %v\n", fired)

	check("the object is no longer referenced by the program (obj == nil)", obj == nil)
	check("the finalizer was observed to run after forced GC", fired)
}

// sectionF measures allocation reduction: a sync.Pool reuse loop allocates far
// fewer objects per op than allocating fresh. testing.Benchmark.AllocsPerOp is
// an integer and is byte-identical across runs (ns/op and b.N are NOT printed).
func sectionF() {
	sectionBanner("F — Reducing GC pressure: sync.Pool vs fresh allocation")

	fmt.Println("Fewer heap allocations = less GC work (see ESCAPE_ANALYSIS). sync.Pool")
	fmt.Println("loans out objects across GC cycles (Get/Put), turning a per-op heap")
	fmt.Println("allocation into ~0 in the steady state. testing.Benchmark reports")
	fmt.Println("AllocsPerOp, a deterministic integer we compare here.")

	pooled := &sync.Pool{New: func() any { return &Box{} }}

	freshRes := testing.Benchmark(func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			globalSink = &Box{} // escapes to the heap every iteration
		}
	})
	poolRes := testing.Benchmark(func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			x := pooled.Get().(*Box) // reuse; no allocation in steady state
			globalSink = x
			pooled.Put(x)
		}
	})

	freshAllocs := freshRes.AllocsPerOp()
	poolAllocs := poolRes.AllocsPerOp()
	fmt.Printf("fresh &Box{} every op : AllocsPerOp = %d\n", freshAllocs)
	fmt.Printf("sync.Pool Get/Put      : AllocsPerOp = %d\n", poolAllocs)
	fmt.Printf("pool allocates fewer ops per iteration? %v\n", poolAllocs < freshAllocs)

	check("fresh allocation allocates >= 1 object per op", freshAllocs >= 1)
	check("sync.Pool AllocsPerOp < fresh-allocation AllocsPerOp", poolAllocs < freshAllocs)
	_ = globalSink // the sink exists only to force heap escape; mark it used
}

func main() {
	fmt.Println("garbage_collector.go — Phase 4 bundle #23.")
	fmt.Println("Go's concurrent tri-color mark-sweep GC, measured via runtime.MemStats.")
	fmt.Println("Only RELATIVE deltas and deterministic counters are asserted")
	fmt.Println("(byte-identical across two `just out garbage_collector` runs).")
	fmt.Printf("runtime.Version()=%s  GOMAXPROCS=%d  NumCPU=%d\n",
		runtime.Version(), runtime.GOMAXPROCS(-1), runtime.NumCPU())
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
