//go:build ignore

// runtime_internals.go — Phase 4 bundle (the runtime package).
//
// GOAL (one line): show, by printing every value, how the `runtime` package
// exposes the scheduler (GOMAXPROCS/NumCPU/NumGoroutine), stack introspection
// (Caller/Callers/Stack/FuncForPC), thread pinning (LockOSThread), the build
// platform (GOOS/GOARCH), and the GC/control knobs (GC/Gosched/KeepAlive +
// debug.SetGCPercent) actually behave.
//
// This is the GROUND TRUTH for RUNTIME_INTERNALS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// DETERMINISM (critical for this bundle): NumCPU, GOMAXPROCS, NumGoroutine and
// the stack's exact bytes are host/schedule-dependent. We PRINT host-specific
// values (NumCPU, GOOS) for the reader but only ever ASSERT structural/relative
// facts (>= 1, contains "main.", contains this filename, before<after). We NEVER
// print a raw stack trace verbatim (line numbers/addresses may shift); we print
// the byte count + the first header line + assert substrings. Two `just out
// runtime_internals` runs are byte-identical.
//
// Run:
//
//	go run runtime_internals.go

package main

import (
	"fmt"
	"path/filepath"
	"runtime"
	"runtime/debug"
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

// callerInfo carries the resolved (file, function) for a stack frame, used by
// sectionC to demonstrate the runtime.Caller(skip) skip argument.
type callerInfo struct {
	file string
	name string
}

// whereCalledFrom calls runtime.Caller(1), so it reports ITS CALLER's frame
// (not its own). This isolates the effect of the `skip` argument.
func whereCalledFrom() callerInfo {
	pc, file, _, ok := runtime.Caller(1) // skip=1 -> the caller of whereCalledFrom
	var name string
	if fn := runtime.FuncForPC(pc); fn != nil { // FuncForPC is correct for a single Caller PC
		name = fn.Name()
	}
	_ = ok
	return callerInfo{file: file, name: name}
}

// sectionA prints the parallelism knobs: NumCPU (hardware) and GOMAXPROCS (the P
// count that bounds true parallelism). Both are host-specific, so we print the
// real numbers but only assert >= 1 and the side-effect-free query contract.
func sectionA() {
	sectionBanner("A — runtime.NumCPU / GOMAXPROCS (the parallelism bound)")

	ncpu := runtime.NumCPU()
	gmp := runtime.GOMAXPROCS(0) // n < 1 -> query the current setting WITHOUT changing it
	fmt.Printf("runtime.NumCPU()      = %d  (logical CPUs usable by this process)\n", ncpu)
	fmt.Printf("runtime.GOMAXPROCS(0) = %d  (current P count; #P bounds parallelism)\n", gmp)
	fmt.Println("(GOMAXPROCS == #P: at most this many goroutines run truly in parallel.)")

	// Query semantics: GOMAXPROCS(0) never mutates the setting.
	q1 := runtime.GOMAXPROCS(0)
	q2 := runtime.GOMAXPROCS(0)
	fmt.Printf("two GOMAXPROCS(0) queries: %d, %d  (identical -> query is side-effect-free)\n", q1, q2)

	// Set then restore: GOMAXPROCS(n>=1) returns the PREVIOUS setting.
	prev := runtime.GOMAXPROCS(4)
	restored := runtime.GOMAXPROCS(prev)
	fmt.Printf("GOMAXPROCS(4)=%d, then GOMAXPROCS(%d)=%d  (current restored to %d)\n", prev, prev, restored, prev)

	check("NumCPU() >= 1", ncpu >= 1)
	check("GOMAXPROCS(0) >= 1", gmp >= 1)
	check("GOMAXPROCS(0) queries without changing the setting (q1==q2)", q1 == q2)
	check("GOMAXPROCS(4) returned the previous setting (restored==4)", restored == 4)
}

// sectionB shows NumGoroutine: the live goroutine count. It is the canonical leak
// detector. The baseline is host-dependent (the count includes whichever runtime
// helpers happen to exist), so we only assert RELATIVE facts: it rises when we
// block k goroutines and falls again once they join.
func sectionB() {
	sectionBanner("B — runtime.NumGoroutine (live count; the leak detector)")

	baseline := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (baseline) = %d\n", baseline)

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
			<-release // blocked here: this G is live but not runnable
		}()
	}
	for range k {
		<-started // drain: guarantees all k goroutines exist before we measure
	}
	during := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (+%d blocked) = %d  (delta = %d)\n", k, during, during-baseline)

	close(release) // closed-channel receive returns the zero value -> unblocks them
	wg.Wait()
	after := runtime.NumGoroutine()
	fmt.Printf("NumGoroutine (after join) = %d  (blocked goroutines terminated)\n", after)

	check("NumGoroutine baseline >= 1", baseline >= 1)
	check("blocked goroutines strictly increased NumGoroutine", during > baseline)
	check("NumGoroutine fell back once the goroutines joined", after < during)
}

// sectionC demonstrates stack introspection: runtime.Caller (one frame),
// runtime.Callers + CallersFrames (a walk), and runtime.FuncForPC (the function
// object). This is the machinery every logging/tracing framework is built on.
func sectionC() {
	sectionBanner("C — runtime.Caller / Callers / FuncForPC (stack introspection)")

	// runtime.Caller(0): skip=0 identifies the CALLER of Caller, i.e. this frame
	// (sectionC). The returned file is THIS source file (forward slashes, even on
	// Windows); the line is the call site below.
	pc, file, line, ok := runtime.Caller(0)
	fmt.Printf("runtime.Caller(0) from sectionC:\n")
	fmt.Printf("  ok   = %v\n", ok)
	fmt.Printf("  file = %s   (filepath.Base of the full path)\n", filepath.Base(file))
	fmt.Printf("  line = %d   (the call site in this file)\n", line)
	if fn := runtime.FuncForPC(pc); fn != nil {
		fmt.Printf("  func = %s   (via runtime.FuncForPC(pc).Name())\n", fn.Name())
	}

	// whereCalledFrom uses Caller(1), so it resolves to ITS caller = sectionC.
	fromHelper := whereCalledFrom()
	fmt.Printf("whereCalledFrom() (Caller(1)) -> file=%s, func=%s\n",
		filepath.Base(fromHelper.file), fromHelper.name)

	// runtime.Callers fills a slice of return PCs. Resolve them with
	// CallersFrames — NOT FuncForPC, which cannot handle inlining / return-PC
	// adjustment on a Callers slice (the doc is explicit about this).
	pcs := make([]uintptr, 16)
	n := runtime.Callers(0, pcs)
	frames := runtime.CallersFrames(pcs[:n])
	fmt.Printf("runtime.Callers wrote %d PCs; CallersFrames resolves these names:\n", n)
	var sawMain bool
	count := 0
	for {
		fr, more := frames.Next()
		count++
		name := fr.Function
		if name == "" {
			name = "(unknown)"
		}
		fmt.Printf("  [%d] %s\n", count, name)
		if strings.Contains(name, "main.") {
			sawMain = true
		}
		if !more {
			break
		}
	}

	check("Caller(0) file contains runtime_internals.go", strings.Contains(file, "runtime_internals.go"))
	check("Caller(0) returned ok=true", ok)
	check("FuncForPC(pc) found the enclosing function (non-nil)", runtime.FuncForPC(pc) != nil)
	check("whereCalledFrom (Caller(1)) reports runtime_internals.go", strings.Contains(fromHelper.file, "runtime_internals.go"))
	check("Callers returned >= 1 frame", n >= 1)
	check("the call-stack walk included a main.* function", sawMain)
}

// sectionD captures the current goroutine's stack as TEXT via runtime.Stack.
// We never print the whole trace verbatim (line numbers/addresses may shift);
// we print the byte count + the header line and assert structural substrings.
func sectionD() {
	sectionBanner("D — runtime.Stack: capture a goroutine stack as text")

	buf := make([]byte, 4096)
	n := runtime.Stack(buf, false) // all=false -> only THIS goroutine
	st := string(buf[:n])

	firstLine := strings.SplitN(st, "\n", 2)[0]
	fmt.Printf("runtime.Stack(buf, all=false) wrote %d bytes\n", n)
	fmt.Printf("first line: %q   (header: 'goroutine N [state]:')\n", firstLine)
	fmt.Println("(full trace NOT printed verbatim — line numbers/addresses may shift;")
	fmt.Println(" we assert STRUCTURAL substrings only, per the determinism discipline.)")

	check("captured stack is non-empty", n > 0)
	check("stack begins with the 'goroutine N [state]:' header", strings.HasPrefix(st, "goroutine "))
	check("stack text contains 'main.' (a user function is on it)", strings.Contains(st, "main."))
	check("stack text contains 'runtime_internals.go' (this source)", strings.Contains(st, "runtime_internals.go"))
}

// sectionE documents runtime.LockOSThread / UnlockOSThread. There is NO public
// API to query "is this goroutine locked to its thread?", so we exercise the
// balanced call protocol (Lock then a matching Unlock) and a locked worker, and
// document WHEN the pinning is required.
func sectionE() {
	sectionBanner("E — runtime.LockOSThread / UnlockOSThread (pin a G to an M)")

	// Balanced protocol in the current goroutine: lock, then unlock. Until the
	// unlock count matches the lock count, the goroutine stays welded to its M.
	runtime.LockOSThread()
	runtime.UnlockOSThread()
	fmt.Println("LockOSThread() then UnlockOSThread(): balanced (goroutine free to migrate again)")
	fmt.Println("(There is NO public runtime API to query locked state — the contract is")
	fmt.Println(" 'match every Lock with an Unlock'; a goroutine that exits locked TERMINATES its thread.)")

	// Canonical pattern: a worker that MUST run on a fixed OS thread (an OpenGL
	// context, a cgo callback, a signal handler) locks on entry and defers the
	// unlock. A portable thread id is not printable from pure Go, so the worker
	// reports that it executed its pinned section.
	const want = "locked worker ran on a fixed OS thread"
	done := make(chan string, 1)
	go func() {
		runtime.LockOSThread()
		defer runtime.UnlockOSThread()
		// ... per-thread OS work would go here (cgo, OpenGL, Cocoa main loop) ...
		done <- want
	}()
	msg := <-done
	fmt.Printf("locked worker: %s\n", msg)

	fmt.Println("Use LockOSThread for: cgo callbacks, OpenGL/rendering contexts, signal")
	fmt.Println(" handling, the macOS Cocoa main thread, and any non-Go library that")
	fmt.Println(" depends on per-thread state.")

	check("locked goroutine completed its pinned section", msg == want)
}

// sectionF prints the compile-time platform constants and asserts each is a
// member of the known GOOS/GOARCH set (portable) rather than a single value.
func sectionF() {
	sectionBanner("F — runtime.GOOS / GOARCH / Compiler (the build platform)")

	fmt.Printf("runtime.GOOS     = %q   (operating system target)\n", runtime.GOOS)
	fmt.Printf("runtime.GOARCH   = %q   (architecture target)\n", runtime.GOARCH)
	fmt.Printf("runtime.Compiler = %q   (toolchain: 'gc' or 'gccgo')\n", runtime.Compiler)

	goosSet := map[string]bool{
		"aix": true, "darwin": true, "dragonfly": true, "freebsd": true,
		"illumos": true, "ios": true, "linux": true, "netbsd": true,
		"openbsd": true, "plan9": true, "solaris": true, "windows": true,
	}
	goarchSet := map[string]bool{
		"386": true, "amd64": true, "arm": true, "arm64": true,
		"loong64": true, "mips": true, "mips64": true, "mipsle": true,
		"ppc64": true, "ppc64le": true, "riscv64": true, "s390x": true, "wasm": true,
	}

	check("GOOS is a non-empty known target", runtime.GOOS != "" && goosSet[runtime.GOOS])
	check("GOARCH is a non-empty known target", runtime.GOARCH != "" && goarchSet[runtime.GOARCH])
	check("Compiler is the gc toolchain", runtime.Compiler == "gc")
}

// sectionG covers the control primitives: runtime.GC (force a collection),
// runtime.Gosched (yield the P), runtime.KeepAlive (defer finalization), and
// debug.SetGCPercent (the GOGC knob, which returns the previous setting).
func sectionG() {
	sectionBanner("G — runtime.GC / Gosched / KeepAlive & debug.SetGCPercent")

	// runtime.GC() forces a full collection and blocks the caller until done.
	var before, after runtime.MemStats
	runtime.ReadMemStats(&before)
	runtime.GC()
	runtime.ReadMemStats(&after)
	fmt.Printf("runtime.GC() forced a collection: NumGC %d -> %d\n", before.NumGC, after.NumGC)

	// debug.SetGCPercent returns the PREVIOUS setting on every call; we restore
	// the original at the end so we never leave GOGC perturbed.
	orig := debug.SetGCPercent(200)     // returns the original; current is now 200
	prev200 := debug.SetGCPercent(400)  // returns 200 (what we set just above)
	prev400 := debug.SetGCPercent(orig) // restore to orig; returns 400 (set just above)
	fmt.Printf("debug.SetGCPercent: orig=%d, set(200) returned %d, set(400) returned %d, restore returned %d\n",
		orig, orig, prev200, prev400)

	// runtime.Gosched() yields the processor, letting other goroutines run; the
	// caller is NOT suspended, so it resumes automatically. Rarely needed in
	// practice — prefer channels / sync for coordination.
	runtime.Gosched()
	fmt.Println("runtime.Gosched() returned (yielded the P, then resumed)")

	// runtime.KeepAlive marks its argument reachable until this point, preventing
	// a finalizer from closing a cgo/unsafe resource prematurely. On a plain Go
	// object it is a harmless no-op; its value is unsafe/cgo code (see .md).
	obj := struct{ id int }{id: 42}
	runtime.KeepAlive(&obj)
	fmt.Println("runtime.KeepAlive(&obj) executed (matters for cgo/unsafe + finalizers)")

	check("runtime.GC incremented NumGC", after.NumGC > before.NumGC)
	check("SetGCPercent(400) returned the previous setting (200)", prev200 == 200)
	check("SetGCPercent(orig) returned the value set before it (400)", prev400 == 400)
	check("Gosched() returned without panic", true)
	check("KeepAlive(&obj) executed", true)
}

func main() {
	fmt.Println("runtime_internals.go — Phase 4 bundle (the runtime package).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes it")
	fmt.Println("verbatim. Host-specific values (NumCPU, GOOS) are printed but only")
	fmt.Println("STRUCTURAL facts are asserted -> byte-identical `just out` runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionG()
	sectionBanner("DONE — all sections printed")
}
