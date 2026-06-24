//go:build ignore

// testing.go — Phase 5 bundle (TESTING & TOOLING).
//
// GOAL (one line): show, by RUNNING table-driven cases, an in-process
// benchmark, and a seed-corpus fuzz check from main, how Go's `testing`
// package (TestXxx / BenchmarkXxx / FuzzXxx) actually works.
//
// This is the GROUND TRUTH for TESTING.md. Every case outcome, AllocsPerOp,
// and seed result below is computed by this file; the .md guide pastes it
// verbatim. Never hand-compute.
//
// DETERMINISM: this bundle is META — it teaches `go test` but runs via
// `go run` (it cannot itself be a _test.go in a module of 52 main programs).
// So instead of TestXxx it RUNS the same logic from main:
//   - TEST logic: extracted into plain functions, driven by a table-driven
//     loop asserted via check() (the house panic-on-invariant idiom).
//   - BENCHMARK logic: actually executed via testing.Benchmark(func(b){
//     ...}).AllocsPerOp() — a deterministic integer for a fixed workload.
//   - FUZZ logic: a fixed seed corpus is run through the fuzz TARGET (the
//     property-check function); each seed is asserted to pass (no panic).
//
// The canonical TestXxx(t *testing.T)/BenchmarkXxx(b *testing.B)/
// FuzzXxx(f *testing.F) signatures + the `go test`/`go test -bench`/
// `go test -fuzz` invocations live in TESTING.md (clearly labeled, NOT under
// a .go callout). Seed RNG; no time.Now() printed values.
//
// Run:
//
//	go run testing.go
package main

import (
	"fmt"
	"reflect"
	"runtime"
	"strings"
	"testing"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
// This is the runnable analog of a testify-free test assertion (see section E).
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// --- SINKS ---------------------------------------------------------------
// Package-level sinks keep benchmark results live so the optimizer cannot
// prove them unused and elide the work (the standard allocation-benchmark
// idiom; see ESCAPE_ANALYSIS.go). Only AllocsPerOp (a deterministic int) is
// read back — never ns/op or b.N, which vary per run.
var (
	sinkStr string
)

// --- Tested functions (pure; the .md shows them under real TestXxx) -------

// romanToInt converts a Roman-numeral string to its integer value. It is the
// "code under test" for sections A and B (table-driven tests + subtests).
// The subtractive rule (IV=4, IX=9, XL=40 ...) is handled by scanning right
// to left and subtracting any digit smaller than the one seen before it.
func romanToInt(s string) int {
	values := map[byte]int{'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
	total, prev := 0, 0
	for i := len(s) - 1; i >= 0; i-- {
		v := values[s[i]]
		if v < prev {
			total -= v
		} else {
			total += v
		}
		prev = v
	}
	return total
}

// reverseRunes reverses a string RUNE-by-rune (not byte-by-byte), so the
// double-reverse identity reverse(reverse(s))==s holds even for multi-byte
// UTF-8. It is the "fuzz target" for section D (the property the fuzzer
// checks). The official Go fuzz tutorial starts from a BUGGY byte-by-byte
// version that fuzzing breaks; this is the corrected rune version.
func reverseRunes(s string) string {
	r := []rune(s)
	for i, j := 0, len(r)-1; i < len(r)/2; i, j = i+1, j-1 {
		r[i], r[j] = r[j], r[i]
	}
	return string(r)
}

// --- Benchmarked functions (section C) -----------------------------------

// concatNaive builds a string with '+='. Every concatenation allocates a fresh
// backing array, so N parts cost O(N) allocations (quadratic bytes copied).
func concatNaive(parts []string) string {
	s := ""
	for _, p := range parts {
		s += p
	}
	return s
}

// concatBuilder builds a string with strings.Builder, which amortizes growth
// across writes (doubling backing buffer) -> far fewer allocations than '+='.
func concatBuilder(parts []string) string {
	var b strings.Builder
	for _, p := range parts {
		b.WriteString(p)
	}
	return b.String()
}

// --- Canonical testify-free assertion helper (section E) -----------------
// assertEqual is the form you would call from a real TestXxx under `go test`.
// t.Helper() marks THIS function as a test helper: when a failure is reported,
// the file:line printed is the CALLER's, not this line — so failure messages
// point at the test that used the helper, not at the helper itself. It is the
// testify-free equivalent of assert.Equal. (Shown verbatim in TESTING.md; it
// is exercised by example _test.go files under `go test`, hence defined here
// for the guide to cite.)

//nolint:unused // referenced by TESTING.md and by example _test.go files.
func assertEqual(t *testing.T, got, want any) {
	t.Helper()
	if !reflect.DeepEqual(got, want) {
		t.Errorf("assertEqual: got %v, want %v", got, want)
	}
}

// ownName returns the name of THIS function (skip = 0): it is what a failure
// reports when a helper is NOT marked with t.Helper() — the file:line/func
// points INSIDE the helper.
func ownName() string {
	pc, _, _, ok := runtime.Caller(0)
	if !ok {
		return ""
	}
	return runtime.FuncForPC(pc).Name()
}

// callerName returns the name of its CALLER (skip = 1): this is exactly the
// frame-skipping that t.Helper() grants to failure reporting — the reported
// location becomes the CALLER's function, not the helper's. A concrete,
// deterministic (function names are stable strings) demonstration.
func callerName() string {
	pc, _, _, ok := runtime.Caller(1)
	if !ok {
		return ""
	}
	return runtime.FuncForPC(pc).Name()
}

// --- The table (shared by sections A and B) ------------------------------

// romanCase is one row of a table-driven test: an input and its expected
// output. The same slice drives both the plain loop (section A) and the
// subtest-shaped runner (section B).
type romanCase struct {
	name string
	in   string
	want int
}

var romanTable = []romanCase{
	{"empty", "", 0},
	{"one", "I", 1},
	{"additive", "III", 3},
	{"subtractive_iv", "IV", 4},
	{"subtractive_ix", "IX", 9},
	{"fifty_eight", "LVIII", 58},
	{"mcmxciv", "MCMXCIV", 1994},
}

// sectionA drives romanToInt through the table with a plain loop, asserting
// each want via check(). This is the runnable core of a table-driven test.
func sectionA() {
	sectionBanner("A — Table-driven test: a slice of {in, want} + a loop")

	fmt.Println("A table-driven test is a []struct{in, want} ranged in a loop.")
	fmt.Println("Each row is one case; the same assert runs for every row, so")
	fmt.Println("adding coverage means adding a row, not copy-pasting a test.")
	fmt.Println()
	fmt.Printf("%-18s %-12s %-8s %s\n", "name", "in", "want", "got")
	fmt.Println("----------------------------------------------------------")

	// Two-phase printing (rows first, then checks) so the captured output splits
	// into a contiguous data block followed by a contiguous checks block — the
	// same layout as the VALUES_TYPES_ZERO style anchor, and byte-identical to
	// the verbatim callouts in TESTING.md.
	type result struct {
		tc  romanCase
		got int
		ok  bool
	}
	results := make([]result, len(romanTable))
	allPassed := true
	for i, tc := range romanTable {
		got := romanToInt(tc.in)
		ok := got == tc.want
		if !ok {
			allPassed = false
		}
		results[i] = result{tc, got, ok}
		fmt.Printf("%-18s %-12q %-8d %d\n", tc.name, tc.in, tc.want, got)
	}
	for _, r := range results {
		check(fmt.Sprintf("romanToInt(%q) == %d", r.tc.in, r.tc.want), r.ok)
	}
	check("all table-driven cases passed", allPassed)
}

// sectionB runs the SAME table through runSub — a helper that mimics the
// shape of t.Run(name, func(t){...}): each case becomes a named "subtest"
// whose pass/fail is reported by name, without halting the others (soft-fail
// via Errorf semantics, vs Fatal which stops the current test).
func sectionB() {
	sectionBanner("B — Subtests: the t.Run(name, fn) shape (runSub analog)")

	fmt.Println("t.Run(name, func(t *testing.T){...}) turns each table row into")
	fmt.Println("a NAMED subtest. The runner below is the .go analog: runSub")
	fmt.Println("reports each case by name and keeps going on failure (like")
	fmt.Println("t.Errorf, a SOFT fail). t.Fatalf would stop only the current")
	fmt.Println("subtest, not its siblings or the parent. The .md shows the")
	fmt.Println("real t.Run + t.Parallel form.")
	fmt.Println()

	allPassed := true
	for _, tc := range romanTable {
		tc := tc // pin the loop variable (pre-1.22 capture bug; harmless on 1.22+)
		ok := runSub("roman/"+tc.name, func() bool {
			return romanToInt(tc.in) == tc.want
		})
		if !ok {
			allPassed = false
		}
	}
	check("all subtest-shaped cases reported PASS", allPassed)
}

// runSub is the runnable analog of t.Run(name, func(t){...}): it invokes a
// case closure, prints a "--- PASS/FAIL: <name>" line (mirroring `go test -v`
// output), and returns the boolean result. The real t.Run also enables
// -run=name filtering, parallelism, and setup/teardown scoping.
func runSub(name string, fn func() bool) bool {
	ok := fn()
	status := "PASS"
	if !ok {
		status = "FAIL"
	}
	fmt.Printf("    --- %s: %s\n", status, name)
	return ok
}

// sectionC actually RUNS two benchmarks in-process via testing.Benchmark and
// compares AllocsPerOp — a deterministic integer for a fixed workload. It
// proves strings.Builder allocates fewer times than naive '+=' concatenation.
func sectionC() {
	sectionBanner("C — Benchmark: testing.Benchmark runs b.N; compare AllocsPerOp")

	fmt.Println("testing.Benchmark(func(b *testing.B){...}) runs a benchmark")
	fmt.Println("IN-PROCESS and returns a BenchmarkResult. The harness picks")
	fmt.Println("b.N (auto-scaled until the run is long enough to time) and")
	fmt.Println("calls the function repeatedly. b.ReportAllocs() makes it count")
	fmt.Println("allocations; result.AllocsPerOp() is a deterministic integer")
	fmt.Println("for a fixed workload. (ns/op and b.N vary per run and are NOT")
	fmt.Println("printed.) Under `go test` you write BenchmarkXxx(b) instead.")
	fmt.Println()

	parts := []string{"the", "quick", "brown", "fox", "jumps", "over", "the", "dog"}

	naiveRes := testing.Benchmark(func(b *testing.B) {
		b.ReportAllocs()
		for range b.N {
			sinkStr = concatNaive(parts)
		}
	})
	builderRes := testing.Benchmark(func(b *testing.B) {
		b.ReportAllocs()
		for range b.N {
			sinkStr = concatBuilder(parts)
		}
	})

	naiveAllocs := naiveRes.AllocsPerOp()
	builderAllocs := builderRes.AllocsPerOp()
	fmt.Printf("%-28s allocs/op = %d\n", "'+=' concat (8 parts)", naiveAllocs)
	fmt.Printf("%-28s allocs/op = %d\n", "strings.Builder (8 parts)", builderAllocs)
	fmt.Printf("Builder allocates fewer than '+='? %v\n", builderAllocs < naiveAllocs)

	check("'+=' concat allocates >= 1 per op", naiveAllocs >= 1)
	check("strings.Builder allocates <= '+=' concat", builderAllocs <= naiveAllocs)
	check("strings.Builder allocates STRICTLY fewer than '+='", builderAllocs < naiveAllocs)
	_ = sinkStr // sink exists only to force the result live; mark it used
}

// sectionD runs a fixed SEED CORPUS through the fuzz target's property check.
// In a real `go test -fuzz`, f.Add(seed...) registers these seeds and the
// engine mutates them to find panics/failures; here we replay the seeds and
// assert each satisfies the property (no panic, identity holds).
func sectionD() {
	sectionBanner("D — Fuzz: a seed corpus replayed through the target's property")

	fmt.Println("A fuzz test is func FuzzXxx(f *testing.F). f.Add(seed...) adds")
	fmt.Println("CORPUS seeds; f.Fuzz(func(t *testing.T, s string){...}) is the")
	fmt.Println("TARGET the engine runs against generated + seed inputs. You can't")
	fmt.Println("predict outputs, so you check PROPERTIES. Here the property is")
	fmt.Println("reverseRunes(reverseRunes(s)) == s (the double-reverse identity).")
	fmt.Println("`go test` replays the seeds; `go test -fuzz=FuzzXxx` generates")
	fmt.Println("mutated inputs to hunt for panics/failures (any failing input is")
	fmt.Println("saved to testdata/fuzz/<Name> as a regression case).")
	fmt.Println()

	seeds := []string{
		"",
		"a",
		"ab",
		"hello",
		"世界",   // multi-byte UTF-8
		"Go 🚀", // emoji (4-byte rune)
	}

	allHeld := true
	type seedResult struct {
		seed  string
		runes int
		held  bool
	}
	results := make([]seedResult, len(seeds))
	for i, s := range seeds {
		held := reverseRunes(reverseRunes(s)) == s
		if !held {
			allHeld = false
		}
		results[i] = seedResult{s, len([]rune(s)), held}
	}
	fmt.Printf("%-14s %-12s %s\n", "seed", "runes", "property_holds")
	fmt.Println("-----------------------------------------")
	for _, r := range results {
		fmt.Printf("%-14q %-12d %v\n", r.seed, r.runes, r.held)
	}
	for _, r := range results {
		check(fmt.Sprintf("fuzz seed %q: double-reverse identity holds", r.seed), r.held)
	}
	check("all fuzz seeds satisfied the property (no panic)", allHeld)
}

// sectionE demonstrates t.Helper(): a helper marked with t.Helper() is skipped
// when the test framework reports the file:line of a failure, so the message
// points at the CALLER. The frame-skip is reproduced here with runtime.Caller,
// and the DeepEqual logic assertEqual relies on is itself asserted via check().
func sectionE() {
	sectionBanner("E — t.Helper(): a test helper is skipped in failure line reports")

	fmt.Println("t.Helper() marks the calling function as a test helper. When a")
	fmt.Println("failure is printed, the testing package SKIPS helper frames, so")
	fmt.Println("the reported file:line is the line that CALLED the helper — not")
	fmt.Println("the line inside it. This is what makes custom assertEqual/t")
	fmt.Println("helpers usable: failures point at your test, not at the helper.")
	fmt.Println()
	fmt.Println("Mechanism demo (runtime.Caller mirrors the frame skip). skip=0")
	fmt.Println("reports the helper's OWN function; skip=1 reports its CALLER:")
	fmt.Printf("  ownName()    -> %q    (skip=0: points INSIDE the helper)\n", ownName())
	caller := callerName()
	fmt.Printf("  callerName() -> %q    (skip=1: points at the CALLER)\n", caller)

	fmt.Println()
	fmt.Println("assertEqual(t, got, want) (cited verbatim in TESTING.md) uses")
	fmt.Println("reflect.DeepEqual under the hood; its comparison logic is")
	fmt.Println("asserted here directly:")

	check("skip=0 reports the helper's own function (main.ownName)", ownName() == "main.ownName")
	check("skip=1 reports the CALLER's function (main.sectionE)", caller == "main.sectionE")
	check("the two skip levels report different functions", ownName() != caller)
	check("reflect.DeepEqual(3, 3) is true (assertEqual equality logic)", reflect.DeepEqual(3, 3))
	check("reflect.DeepEqual(3, 4) is false (assertEqual rejects unequal)", !reflect.DeepEqual(3, 4))
	check("reflect.DeepEqual(\"abc\", \"abc\") is true", reflect.DeepEqual("abc", "abc"))
}

func main() {
	// testing.Init() registers the testing flags; it is REQUIRED before calling
	// testing.Benchmark outside of `go test` (the package docs note Init "is only
	// needed when calling functions such as Benchmark without using go test").
	testing.Init()

	fmt.Println("testing.go — Phase 5 bundle (testing & tooling).")
	fmt.Println("Go's testing package (TestXxx / BenchmarkXxx / FuzzXxx), driven")
	fmt.Println("from main: table-driven cases, an in-process benchmark, and a")
	fmt.Println("seed-corpus fuzz replay. Nothing is hand-computed.")
	fmt.Println("NOTE: this is a META bundle — it teaches `go test` but runs via")
	fmt.Println("`go run`. The canonical TestXxx/BenchmarkXxx/FuzzXxx signatures")
	fmt.Println("and the `go test` invocations live in TESTING.md.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
