//go:build ignore

// escape_analysis.go — Phase 4 bundle (MEMORY, RUNTIME & INTERNALS).
//
// GOAL (one line): show, by MEASURING allocation counts, that the COMPILER —
// not the `new`/`&` keyword — decides stack vs heap via escape analysis, and
// that fewer escapes mean a faster, GC-lighter program.
//
// This is the GROUND TRUTH for ESCAPE_ANALYSIS.md. Every allocs/op and bytes/op
// below is MEASURED by this file via testing.Benchmark().AllocsPerOp() — never
// hand-computed. The .md guide pastes these numbers verbatim. Change it ->
// re-run -> re-paste.
//
// Methodology (so the numbers are reproducible):
//   - Each teaching function is marked //go:noinline, mirroring the Ardan Labs
//     escape-analysis methodology, so inlining does not erase the allocation
//     and the -gcflags=-m diagnostics stay readable.
//   - Each benchmark stores its result in a package-level SINK so the compiler
//     cannot prove the result is unused and elide the allocation. Without a
//     sink the optimizer is free to keep a "returned pointer" on the stack —
//     itself an escape-analysis subtlety (see ESCAPE_ANALYSIS.md §gotchas).
//   - Only allocs/op and bytes/op are printed: those are deterministic for a
//     fixed workload. ns/op depends on CPU/scheduling and is NOT printed.
//
// Run:
//
//	go run escape_analysis.go
//
// See the compiler's escape decisions for yourself:
//
//	go build -gcflags=-m escape_analysis.go
package main

import (
	"fmt"
	"strconv"
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
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// --- SINKS ---------------------------------------------------------------
// Package-level sinks consume each benchmark's result so the optimizer cannot
// prove the result unused and elide the allocation (which would hide the very
// escape we are measuring). Each sink is a distinct type so results do not
// alias. This is the standard allocation-benchmark idiom (see goperf.dev).
var (
	sinkInt   int
	sinkPtr   *int
	sinkStr   string
	sinkSlice []int
	sinkFunc  func(int) int
)

// --- Teaching functions (each //go:noinline for clean, stable diagnostics) ---

// stackSum returns a plain value: no pointer leaves the frame -> nothing
// escapes -> 0 heap allocations. The compiler keeps a, b, and the result on
// the stack, which is reclaimed for free when the frame pops.
//
//go:noinline
func stackSum(a, b int) int { return a + b }

// heapInt returns the ADDRESS of a local. The local's lifetime now outlives the
// frame (the caller holds the pointer), so escape analysis "moves x to heap".
// That is one heap allocation (8 bytes on amd64/arm64) the GC must later track.
//
//go:noinline
func heapInt() *int { x := 1; return &x }

// itoaStr uses strconv.Itoa, a MONOMORPHIC int->string converter that formats
// into a stack buffer for small ints -> 0 allocations.
//
//go:noinline
func itoaStr(n int) string { return strconv.Itoa(n) }

// sprintfStr uses fmt.Sprintf("%d", n). fmt's signature is (string, ...any), so
// n is BOXED into an interface{} and formatted through reflection-like dispatch.
// The boxing + dynamic formatting heap-allocates (1 alloc for "42").
//
//go:noinline
func sprintfStr(n int) string { return fmt.Sprintf("%d", n) }

// preallocSum builds a slice with a compile-time-known capacity (make cap=8),
// fills it, sums it, and returns only the int sum. The slice does NOT escape,
// and because its capacity is statically known the compiler keeps the whole
// backing array on the stack -> 0 heap allocations.
//
//go:noinline
func preallocSum() int {
	s := make([]int, 0, 8)
	for i := 0; i < 8; i++ {
		s = append(s, i)
	}
	sum := 0
	for _, v := range s {
		sum += v
	}
	return sum
}

// growSum builds the slice by appending to a nil slice. The slice header still
// does not escape (only the int sum is returned), but the backing array's final
// size is grown at runtime by runtime.growslice, which heap-allocates -> 1
// allocation. Contrast with preallocSum: same result, one fewer heap alloc.
//
//go:noinline
func growSum() int {
	var s []int
	for i := 0; i < 8; i++ {
		s = append(s, i)
	}
	sum := 0
	for _, v := range s {
		sum += v
	}
	return sum
}

// makeAdder returns a CLOSURE that captures base by reference. Because the
// closure outlives the call (it is returned), the captured base must live on
// the heap along with the closure value -> 1 allocation.
//
//go:noinline
func makeAdder(base int) func(int) int {
	return func(n int) int { return n + base }
}

// --- Benchmark helpers ---------------------------------------------------

// bench runs one workload under testing.Benchmark and returns the
// deterministic allocation stats (allocs/op and bytes/op).
func bench(name string, work func(b *testing.B)) (allocs, bytes int64) {
	r := testing.Benchmark(work)
	allocs = r.AllocsPerOp()
	bytes = r.AllocedBytesPerOp()
	fmt.Printf("  %-32s allocs/op = %-3d  bytes/op = %d\n", name, allocs, bytes)
	return allocs, bytes
}

// sectionA shows a value-returning function: nothing escapes -> 0 allocations.
func sectionA() {
	sectionBanner("A — Stack: a value that stays put (0 allocs)")

	fmt.Println("stackSum(a,b int) int returns a plain VALUE — no pointer leaves")
	fmt.Println("the frame, so nothing escapes. The compiler keeps everything on")
	fmt.Println("the stack, which is reclaimed for free (no GC) when the frame pops.")

	allocs, _ := bench("stackSum(2,3)", func(b *testing.B) {
		for range b.N {
			sinkInt = stackSum(2, 3)
		}
	})

	check("stackSum allocates 0 (stays on the stack)", allocs == 0)
}

// sectionB shows that returning &local forces the local onto the heap.
func sectionB() {
	sectionBanner("B — Heap: `return &local` escapes (>=1 alloc)")

	fmt.Println("heapInt() *int { x := 1; return &x } — the address of x leaves")
	fmt.Println("the frame, so x's lifetime can't be confined to the stack. Escape")
	fmt.Println("analysis MOVES x to the heap: one allocation the GC must track.")

	allocs, _ := bench("heapInt() -> sinkPtr", func(b *testing.B) {
		for range b.N {
			sinkPtr = heapInt()
		}
	})

	check("heapInt allocates >=1 (x moved to heap)", allocs >= 1)
}

// sectionC contrasts a monomorphic converter with fmt's interface-boxing path.
func sectionC() {
	sectionBanner("C — Interface boxing: strconv.Itoa (0) vs fmt.Sprintf (>=1)")

	fmt.Println("fmt.Sprintf takes (string, ...any): the int is BOXED into an")
	fmt.Println("interface{} and formatted through reflection-like dispatch -> an")
	fmt.Println("allocation. strconv.Itoa is monomorphic and uses a stack buffer")
	fmt.Println("for small ints -> 0 allocations. Same output, different cost.")

	itoa, _ := bench("strconv.Itoa(42)", func(b *testing.B) {
		for range b.N {
			sinkStr = itoaStr(42)
		}
	})
	sprintf, _ := bench(`fmt.Sprintf("%d",42)`, func(b *testing.B) {
		for range b.N {
			sinkStr = sprintfStr(42)
		}
	})

	check("strconv.Itoa(42) allocates 0", itoa == 0)
	check("strconv.Itoa allocates <= fmt.Sprintf", itoa <= sprintf)
	check("fmt.Sprintf allocates >=1 (interface boxing)", sprintf >= 1)
}

// sectionD shows preallocation keeping a slice on the stack vs append growth.
func sectionD() {
	sectionBanner("D — Slice preallocation: make(_,0,n) (0) vs append growth (>=1)")

	fmt.Println("Neither slice below escapes (only an int sum is returned). But a")
	fmt.Println("slice preallocated with a KNOWN capacity can keep its backing array")
	fmt.Println("on the stack (0 allocs), while one grown by appending from nil has")
	fmt.Println("its backing array heap-allocated by runtime.growslice (>=1 alloc).")

	prealloc, _ := bench("preallocSum (make cap=8)", func(b *testing.B) {
		for range b.N {
			sinkInt = preallocSum()
		}
	})
	grow, _ := bench("growSum (append from nil)", func(b *testing.B) {
		for range b.N {
			sinkInt = growSum()
		}
	})

	check("preallocated slice allocates 0", prealloc == 0)
	check("grown slice allocates >=1", grow >= 1)
	check("preallocated allocates <= grown", prealloc <= grow)
}

// sectionE shows a closure capturing a local by reference forces it to escape.
func sectionE() {
	sectionBanner("E — Closure capture: the captured value escapes (>=1 alloc)")

	fmt.Println("makeAdder(base) returns a closure that captures base. Because the")
	fmt.Println("closure outlives the call, the captured base and the closure value")
	fmt.Println("itself are moved to the heap -> one allocation.")

	allocs, _ := bench("makeAdder(10) closure", func(b *testing.B) {
		for range b.N {
			sinkFunc = makeAdder(10)
		}
	})

	check("closure capture allocates >=1", allocs >= 1)
}

// sectionF prints the full measured summary and points at the compiler evidence.
func sectionF() {
	sectionBanner("F — Summary: every measured allocation count, pinned")

	fmt.Println("label                            allocs/op   bytes/op   verdict")
	fmt.Println("-------------------------------- ---------- ---------- ----------------------------")

	rows := []struct {
		name    string
		work    func(b *testing.B)
		verdict string
	}{
		{"stackSum(2,3)", func(b *testing.B) {
			for range b.N {
				sinkInt = stackSum(2, 3)
			}
		}, "stack (free)"},
		{"heapInt() return &x", func(b *testing.B) {
			for range b.N {
				sinkPtr = heapInt()
			}
		}, "heap (moved to heap)"},
		{"strconv.Itoa(42)", func(b *testing.B) {
			for range b.N {
				sinkStr = itoaStr(42)
			}
		}, "stack (monomorphic)"},
		{`fmt.Sprintf("%d",42)`, func(b *testing.B) {
			for range b.N {
				sinkStr = sprintfStr(42)
			}
		}, "heap (interface box)"},
		{"preallocSum cap=8", func(b *testing.B) {
			for range b.N {
				sinkInt = preallocSum()
			}
		}, "stack (known cap)"},
		{"growSum append nil", func(b *testing.B) {
			for range b.N {
				sinkInt = growSum()
			}
		}, "heap (growslice)"},
		{"makeAdder(10) closure", func(b *testing.B) {
			for range b.N {
				sinkFunc = makeAdder(10)
			}
		}, "heap (closure esc)"},
	}

	for _, r := range rows {
		res := testing.Benchmark(r.work)
		fmt.Printf("%-32s %10d %10d   %s\n", r.name, res.AllocsPerOp(), res.AllocedBytesPerOp(), r.verdict)
	}

	fmt.Println()
	fmt.Println("These counts are deterministic for a fixed workload and are what")
	fmt.Println("`just check escape_analysis` asserts. To SEE the compiler's escape")
	fmt.Println("DECISIONS (not just their cost), run:")
	fmt.Println("    go build -gcflags=-m escape_analysis.go")
	fmt.Println("and look for: \"moved to heap\", \"escapes to heap\", \"does not escape\".")
}

func main() {
	fmt.Println("escape_analysis.go — Phase 4 bundle (memory, runtime & internals).")
	fmt.Println("Every allocs/op below is MEASURED by testing.Benchmark; the .md guide")
	fmt.Println("pastes these numbers verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
