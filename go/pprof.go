//go:build ignore

// pprof.go — Phase 7 bundle.
//
// GOAL (one line): show, by capturing profiles into buffers and asserting their
// STRUCTURAL facts, how Go's runtime/pprof profiler works — CPU, heap, goroutine,
// mutex, and block profiles — and how `go tool pprof` consumes them.
//
// This is the GROUND TRUTH for PPROF.md. Every printed fact below is computed by
// this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM — CRITICAL for this bundle: pprof payloads contain sample counts,
// addresses, and timings that VARY between runs. This file NEVER prints or
// byte-compares raw profile bytes. It captures each profile into a bytes.Buffer
// and asserts only STABLE structural facts: the buffer is non-empty; it starts
// with the gzip magic 0x1f 0x8b (pprof profiles are gzip-compressed protobuf);
// the write returned no error; a named profile is present in the sorted set.
// Two `just out pprof` runs are byte-identical for every asserted quantity.
//
// Run:
//
//	go run pprof.go

package main

import (
	"bytes"
	"fmt"
	"runtime"
	"runtime/pprof"
	"slices"
	"strings"
	"sync"
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

// gzipMagic reports whether b is a gzip stream: every gzip member starts with
// the two bytes 0x1f 0x8b (RFC 1952 §2.3.1). pprof writes its protobuf payload
// gzip-compressed, so every binary (debug=0) profile begins with these bytes.
func gzipMagic(b []byte) bool {
	return len(b) >= 2 && b[0] == 0x1f && b[1] == 0x8b
}

// sectionA captures a CPU profile into a buffer. StartCPUProfile/StopCPUProfile
// stream the profile to a writer; the result is a gzip-compressed protobuf
// consumed by `go tool pprof`. Only structural facts are asserted (the sample
// counts, addresses, and timings inside the protobuf are run-dependent).
func sectionA() {
	sectionBanner("A — CPU profile: StartCPUProfile into a buffer")

	fmt.Println("CPU profiling answers: WHERE does the program spend CPU time?")
	fmt.Println("StartCPUProfile(w) turns on sampling (SIGPROF-driven, ~100Hz);")
	fmt.Println("StopCPUProfile() flushes the buffered, gzip-compressed protobuf")
	fmt.Println("to w. The payload is OPAQUE BINARY — you never read it directly,")
	fmt.Println("you hand it to `go tool pprof` for top/list/web/flame analysis.")

	var buf bytes.Buffer
	err := pprof.StartCPUProfile(&buf)
	check("StartCPUProfile(buf) returned no error", err == nil)

	// Deterministic CPU work: sum of 0..N-1. The SUM is stable and printable;
	// the internal samples/timings captured into the profile are NOT.
	const n = 2_000_000
	sum := 0
	for i := 0; i < n; i++ {
		sum += i
	}
	runtime.KeepAlive(sum) // keep the accumulator live across the profile window
	pprof.StopCPUProfile()

	cpu := buf.Bytes()
	fmt.Printf("deterministic CPU work: sum(0..%d-1) = %d  (printed; stable)\n", n, sum)
	fmt.Printf("CPU profile captured: non-empty? %v   starts with gzip magic 0x1f8b? %v\n",
		buf.Len() > 0, gzipMagic(cpu))
	fmt.Println("(the protobuf sample counts/addresses inside vary per run; not printed)")

	check("CPU profile buffer is non-empty", buf.Len() > 0)
	check("CPU profile starts with gzip magic 0x1f 0x8b", gzipMagic(cpu))
}

// sectionB captures a heap profile. WriteHeapProfile(w) is shorthand for
// Lookup("heap").WriteTo(w, 0); it reports LIVE (in-use) allocations as of the
// most recent GC. runtime.GC() first forces a fresh cycle so the snapshot is
// current. Again only structural facts are asserted.
func sectionB() {
	sectionBanner("B — Heap profile: WriteHeapProfile (live allocations)")

	fmt.Println("The HEAP profile answers: WHERE are LIVE bytes/objects allocated?")
	fmt.Println("It is sampled (1 per 512 KiB historically) and reports the snapshot")
	fmt.Println("as of the last GC. WriteHeapProfile(w) == Lookup(\"heap\").WriteTo(w,0).")
	fmt.Println("The ALLOCS profile is the same data with a different default view")
	fmt.Println("(-alloc_space: total since start, incl. GC'd) — see ESCAPE_ANALYSIS")

	// Grow the live heap with a deterministic set of objects.
	const n = 100_000
	live := make([]*[64]byte, n)
	for i := range live {
		live[i] = &[64]byte{} // each escapes to the heap
	}
	runtime.GC() // make the snapshot current (docs: profile reflects last GC)

	var buf bytes.Buffer
	err := pprof.WriteHeapProfile(&buf)
	heap := buf.Bytes()
	fmt.Printf("allocated %d *[64]byte (heap-resident); forced runtime.GC()\n", n)
	fmt.Printf("heap profile captured: non-empty? %v   starts with gzip magic? %v\n",
		buf.Len() > 0, gzipMagic(heap))

	check("WriteHeapProfile(buf) returned no error", err == nil)
	check("heap profile buffer is non-empty", buf.Len() > 0)
	check("heap profile starts with gzip magic 0x1f 0x8b", gzipMagic(heap))
	runtime.KeepAlive(live)
}

// sectionC captures the goroutine profile. Unlike heap/mutex (gzip protobuf at
// debug=0), Lookup("goroutine").WriteTo(w, 1) emits READABLE TEXT — one entry
// per goroutine with its stack trace. We assert the text is non-empty and
// contains the word "goroutine", and that it is NOT the gzip binary (text form).
func sectionC() {
	sectionBanner("C — Goroutine profile: Lookup(\"goroutine\").WriteTo (text)")

	fmt.Println("The GOROUTINE profile dumps a stack trace for EVERY live goroutine")
	fmt.Println("(the live count is the classic 'goroutine leak' detector). With")
	fmt.Println("debug=1 WriteTo emits HUMAN-READABLE TEXT (not gzip protobuf);")
	fmt.Println("debug=2 prints stacks like an unrecovered-panic dump.")

	p := pprof.Lookup("goroutine")
	var buf bytes.Buffer
	err := p.WriteTo(&buf, 1) // debug=1 -> legacy text format
	text := buf.String()
	hasWord := strings.Contains(text, "goroutine")
	isText := buf.Len() > 0 && !gzipMagic(buf.Bytes()) // text, not gzip binary
	fmt.Printf("goroutine profile: non-empty? %v   contains \"goroutine\"? %v   is text (not gzip)? %v\n",
		buf.Len() > 0, hasWord, isText)
	fmt.Println("(exact goroutine count and stack addresses vary; only structure asserted)")

	check("Lookup(\"goroutine\") returned a non-nil *Profile", p != nil)
	check("goroutine WriteTo(debug=1) returned no error", err == nil)
	check("goroutine profile text is non-empty", buf.Len() > 0)
	check("goroutine profile text contains \"goroutine\"", hasWord)
	check("goroutine profile at debug=1 is TEXT (not gzip binary)", isText)
}

// sectionD enables the two OPT-IN profiles — mutex contention and block
// (synchronization wait) — via the runtime rate knobs, then captures each.
// Both are off by default (rate/fraction == 0) because they have non-trivial
// overhead. SetMutexProfileFraction / SetBlockProfileRate return the PREVIOUS
// value (0 on first call) — a stable, printable integer.
func sectionD() {
	sectionBanner("D — Mutex & block: the opt-in contention profiles")

	fmt.Println("MUTEX profile: WHERE do goroutines wait on contended locks? Needs")
	fmt.Println("  runtime.SetMutexProfileFraction(n) — samples ~1/n of contention events;")
	fmt.Println("  returns the PREVIOUS fraction (0 = off by default).")
	fmt.Println("BLOCK profile: WHERE do goroutines block (chan/mutex/cond/select)?")
	fmt.Println("  Needs runtime.SetBlockProfileRate(n) — samples one block event per n ns;")
	fmt.Println("  n=1 records all; it returns NO value (no read API, unlike mutex).")
	fmt.Println("Both are OFF by default because they add per-event overhead.")

	// --- mutex contention ---
	prevMutex := runtime.SetMutexProfileFraction(1) // enable; returns prior (0)
	var mu sync.Mutex
	var wg sync.WaitGroup
	const workers = 8
	const iters = 200_000
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < iters; j++ {
				mu.Lock()
				mu.Unlock() // many goroutines contend on the same lock
			}
		}()
	}
	wg.Wait()
	var mbuf bytes.Buffer
	mp := pprof.Lookup("mutex")
	mErr := mp.WriteTo(&mbuf, 0) // gzip protobuf
	fmt.Printf("SetMutexProfileFraction(1) returned previous fraction = %d\n", prevMutex)
	fmt.Printf("mutex profile: non-empty? %v   starts with gzip magic? %v\n",
		mbuf.Len() > 0, gzipMagic(mbuf.Bytes()))

	// --- block (synchronization wait) ---
	runtime.SetBlockProfileRate(1) // enable; returns no value (no read API)
	// Cause deterministic blocking: N unbuffered-channel handshakes. Each send
	// blocks until the receive is ready (and vice-versa), feeding the block
	// profile with real wait events.
	const handshakes = 2000
	ch := make(chan struct{})
	var wg2 sync.WaitGroup
	wg2.Add(1)
	go func() {
		defer wg2.Done()
		for range handshakes { // `range int` (Go 1.22+) counts 0..n-1
			<-ch
		}
	}()
	for range handshakes {
		ch <- struct{}{}
	}
	wg2.Wait()
	var bbuf bytes.Buffer
	bp := pprof.Lookup("block")
	bErr := bp.WriteTo(&bbuf, 0) // gzip protobuf
	fmt.Println("SetBlockProfileRate(1) called (returns no value; block now enabled)")
	fmt.Printf("block profile: non-empty? %v   starts with gzip magic? %v\n",
		bbuf.Len() > 0, gzipMagic(bbuf.Bytes()))

	check("SetMutexProfileFraction(1) returned 0 (was off by default)", prevMutex == 0)
	check("Lookup(\"mutex\") is non-nil after enabling", mp != nil)
	check("mutex WriteTo returned no error", mErr == nil)
	check("mutex profile buffer is non-empty", mbuf.Len() > 0)
	check("mutex profile starts with gzip magic 0x1f 0x8b", gzipMagic(mbuf.Bytes()))
	check("Lookup(\"block\") is non-nil after enabling", bp != nil)
	check("block WriteTo returned no error", bErr == nil)
	check("block profile buffer is non-empty", bbuf.Len() > 0)
}

// sectionE enumerates the named profiles via pprof.Profiles() (already sorted
// by name). The SET of predefined profiles is stable: allocs, goroutine, heap,
// threadcreate are always present; block and mutex appear once their rate/fraction
// is set (done in section D). We print the sorted names and assert membership of
// the headline kinds.
func sectionE() {
	sectionBanner("E — Profile kinds: enumerate pprof.Profiles() (sorted)")

	fmt.Println("pprof.Profiles() returns every named Profile, SORTED by name.")
	fmt.Println("Predefined (self-maintained; Add/Remove panic on them):")
	fmt.Println("  goroutine  stack traces of all current goroutines")
	fmt.Println("  heap       sampling of LIVE object allocations")
	fmt.Println("  allocs     sampling of ALL past allocations (incl. GC'd)")
	fmt.Println("  threadcreate stacks that led to new OS threads")
	fmt.Println("  block      stacks where goroutines blocked on sync (opt-in)")
	fmt.Println("  mutex      stacks of holders of contended mutexes (opt-in)")
	fmt.Println("CPU is NOT a Profile — it has its own Start/Stop streaming API.")

	profs := pprof.Profiles()
	names := make([]string, 0, len(profs))
	for _, p := range profs {
		names = append(names, p.Name())
	}
	slices.Sort(names) // docs say already sorted; sort to be safe for stable output
	fmt.Printf("pprof.Profiles() names (sorted): %v\n", names)

	set := make(map[string]bool, len(names))
	for _, n := range names {
		set[n] = true
	}
	check("\"heap\" is a named profile", set["heap"])
	check("\"goroutine\" is a named profile", set["goroutine"])
	check("\"mutex\" is a named profile (enabled in section D)", set["mutex"])
	check("\"block\" is a named profile (enabled in section D)", set["block"])
	check("Profiles() list is sorted ascending", slices.IsSorted(names))
}

func main() {
	fmt.Println("pprof.go — Phase 7 bundle.")
	fmt.Println("runtime/pprof: CPU, heap, goroutine, mutex, block profiles.")
	fmt.Println("Only STRUCTURAL facts are asserted (gzip magic, non-empty, set")
	fmt.Println("membership) — raw profile bytes vary per run and are NOT printed.")
	fmt.Printf("runtime.Version()=%s  GOMAXPROCS=%d  NumCPU=%d\n",
		runtime.Version(), runtime.GOMAXPROCS(-1), runtime.NumCPU())
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
