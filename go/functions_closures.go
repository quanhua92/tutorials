//go:build ignore

// functions_closures.go — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how Go functions are
// first-class values, how closures capture VARIABLES by reference (not by
// value), and why the pre-1.22 loop-variable-capture trap existed and how the
// Go 1.22+ per-iteration fix resolves it.
//
// This is the GROUND TRUTH for FUNCTIONS_CLOSURES.md. Every number and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// Run:
//
//	go run functions_closures.go

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

// applyTwice takes a function VALUE as an argument — proof that functions are
// first-class values that can be passed around like any other.
func applyTwice(f func(int) int, x int) int {
	return f(f(x))
}

// makeAdder RETURNS a function value created inside it. (It is already a closure
// because it captures `base`; section B dissects that capture in depth.)
func makeAdder(base int) func(int) int {
	return func(n int) int {
		return base + n
	}
}

// makeCounter returns a closure that captures the variable `n`. Every call of
// the returned function increments and returns the SAME `n` — n is shared BY
// REFERENCE, not copied. We also return &n so the caller can prove the closure
// reads and writes that exact cell, and that the cell outlives makeCounter.
func makeCounter() (func() int, *int) {
	n := 0
	return func() int {
		n++
		return n
	}, &n
}

// sum is VARIADIC: the last parameter is `nums ...int`. Inside the function the
// parameter `nums` has the slice type []int.
func sum(nums ...int) int {
	total := 0
	for _, n := range nums {
		total += n
	}
	return total
}

// divmod returns MULTIPLE values — Go's only form of tuple-like return. The
// caller may use the blank identifier _ to discard any of them.
func divmod(a, b int) (int, int) {
	return a / b, a % b
}

// sectionA: functions are first-class VALUES. A function type has a zero value
// (nil); values can be assigned to variables, passed as arguments, returned
// from functions, and stored in data structures.
func sectionA() {
	sectionBanner("A — FIRST-CLASS FUNCTIONS (assign, pass, return, nil)")

	// The zero value of a function type is nil, exactly like a pointer.
	var f func(int) int
	fmt.Printf("var f func(int) int   ->  f == nil? %v   (zero value of a func type)\n", f == nil)
	check("zero value of a func type is nil", f == nil)

	// Assign a function literal (an anonymous function) to the variable.
	f = func(n int) int { return n * n }
	fmt.Printf("f = func(n) n*n       ->  f(5) = %d\n", f(5))
	check("func value assigned then called: f(5)==25", f(5) == 25)

	// Pass a function VALUE as an argument to another function.
	r := applyTwice(f, 3) // f(f(3)) == f(9) == 81
	fmt.Printf("applyTwice(f, 3)      ->  f(f(3)) = %d\n", r)
	check("func passed as arg: applyTwice(f,3)==81", r == 81)

	// Return a function VALUE from a function (here a closure capturing base).
	add10 := makeAdder(10)
	fmt.Printf("add10 := makeAdder(10) ->  add10(5) = %d\n", add10(5))
	check("func returned from a func: add10(5)==15", add10(5) == 15)

	// Two distinct function literals with identical code are the SAME TYPE but
	// are NOT the same value. NOTE (not compiled): `f == g` is a COMPILE ERROR
	// — "func can only be compared to nil". See pitfalls in the .md.
	g := func(n int) int { return n * n }
	fmt.Printf("g := func(n) n*n       ->  g(5) = %d  (same code & type, distinct value)\n", g(5))
	check("f and g share the func type func(int) int",
		fmt.Sprintf("%T", f) == fmt.Sprintf("%T", g) && fmt.Sprintf("%T", f) == "func(int) int")
}

// sectionB: a closure is a function literal that refers to variables of its
// enclosing scope. Those variables are shared BY REFERENCE (the same cell), and
// they survive as long as the closure is reachable (they escape to the heap).
func sectionB() {
	sectionBanner("B — CLOSURES CAPTURE BY REFERENCE (shared variable, not a copy)")

	counter, nAddr := makeCounter()
	a := counter()
	b := counter()
	c := counter()
	fmt.Printf("counter, _ := makeCounter()\n")
	fmt.Printf("counter() -> %d   counter() -> %d   counter() -> %d   (each call shares one n)\n", a, b, c)
	check("counter shares captured n: calls return 1,2,3", a == 1 && b == 2 && c == 3)

	// The captured n is STILL ALIVE after makeCounter returned — it escaped to
	// the heap so the closure can keep using it. The closure mutated it to 3.
	fmt.Printf("*nAddr (captured n, after 3 calls) = %d   (outlived makeCounter's scope)\n", *nAddr)
	check("captured n outlived its declaring scope: *nAddr==3", *nAddr == 3)

	// Two counters are INDEPENDENT: each call to makeCounter creates a fresh n,
	// so c1 and c2 hold two distinct captured cells.
	c1, _ := makeCounter()
	c2, _ := makeCounter()
	c1()       // c1's n -> 1
	c1()       // c1's n -> 2
	v1 := c1() // c1's n -> 3
	v2 := c2() // c2's n -> 1
	fmt.Printf("c1() x2; then c1()->%d ; c2()->%d   (two independent captured n's)\n", v1, v2)
	check("two counters are independent: c1->3, c2->1", v1 == 3 && v2 == 1)
}

// sectionC: variadic parameters (...T) and multiple return values.
func sectionC() {
	sectionBanner("C — VARIADIC (...int) + MULTIPLE RETURN VALUES")

	// Call a variadic function with individual args; inside, nums == []int{1,2,3}.
	fmt.Printf("sum(1, 2, 3)           -> %d   (nums is []int{1,2,3} inside)\n", sum(1, 2, 3))
	check("variadic call with args: sum(1,2,3)==6", sum(1, 2, 3) == 6)

	// Call a variadic function with ZERO args; inside, nums is a nil slice (len 0).
	fmt.Printf("sum()                  -> %d   (nums is []int(nil) — zero args)\n", sum())
	check("variadic with zero args: sum()==0", sum() == 0)

	// Spread an EXISTING slice into the variadic parameter with the ... operator.
	nums := []int{10, 20, 30, 40}
	fmt.Printf("nums := []int{...}; sum(nums...) -> %d   (spread operator, no copy)\n", sum(nums...))
	check("spread a slice into variadic: sum(nums...)==100", sum(nums...) == 100)

	// Multiple return values.
	q, r := divmod(17, 5)
	fmt.Printf("divmod(17, 5)          -> q=%d, r=%d\n", q, r)
	check("multiple return: divmod(17,5) -> quotient 3, remainder 2", q == 3 && r == 2)

	// The blank identifier discards a return value. divmod returns
	// (quotient, remainder); discard the quotient to keep only the remainder.
	_, rem := divmod(17, 5)
	fmt.Printf("_, rem := divmod(17, 5) -> rem=%d   (quotient discarded with _)\n", rem)
	check("blank identifier discards a return value: rem==2", rem == 2)
}

// sectionD: THE loop-variable-capture trap — the expert payoff. Pre-1.22, the
// for-clause declared ONE loop variable reused across iterations; every closure
// or goroutine that captured it saw the SAME (final) value. Go 1.22+ creates a
// FRESH variable per iteration, fixing the bug. Output is collected, sorted, and
// printed from main() (never from a goroutine) so stdout is byte-stable.
func sectionD() {
	sectionBanner("D — THE LOOP-VARIABLE CAPTURE TRAP (Go 1.22+ per-iteration fix)")

	// Force real parallelism so goroutines genuinely interleave.
	prev := runtime.GOMAXPROCS(4)
	defer runtime.GOMAXPROCS(prev)

	const n = 3

	// (1) Concurrent form: goroutines capturing the loop variable. Pre-1.22 they
	// usually all read the final i (3); Go 1.22+ each reads its own 0/1/2.
	var (
		mu       sync.Mutex
		wg       sync.WaitGroup
		captured = make([]int, 0, n)
	)
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			mu.Lock()
			captured = append(captured, i)
			mu.Unlock()
		}()
	}
	wg.Wait()
	slices.Sort(captured) // sort: goroutine scheduling order is nondeterministic
	fmt.Printf("GOMAXPROCS(4); launched %d goroutines capturing loop var i\n", n)
	fmt.Printf("captured (sorted)      -> %v\n", captured)
	fmt.Printf("pre-1.22: usually [3 3 3] (shared i). Go 1.22+: [0 1 2] (fresh i per iter)\n")
	check("Go 1.22+ concurrent loop-var capture: sorted == [0 1 2]",
		slices.Equal(captured, []int{0, 1, 2}))

	// (2) Non-concurrent form: the same trap WITHOUT goroutines. Collecting
	// function literals that capture i. Pre-1.22 every fn() returned 3.
	var fns []func() int
	for i := 0; i < n; i++ {
		fns = append(fns, func() int { return i })
	}
	got := make([]int, 0, n)
	for _, fn := range fns {
		got = append(got, fn())
	}
	slices.Sort(got)
	fmt.Printf("non-concurrent (funcs) -> %v   (each closure has its own i)\n", got)
	check("Go 1.22+ non-concurrent loop-var capture: sorted == [0 1 2]",
		slices.Equal(got, []int{0, 1, 2}))
}

// sectionE: a deferred statement evaluates its arguments IMMEDIATELY (at the
// defer), but a deferred CLOSURE reads its captured variables at execution time
// (at return, LIFO). Contrast the snapshot vs the live read.
func sectionE() {
	sectionBanner("E — DEFER ARG vs DEFER CLOSURE (snapshot vs live read)")

	x := 1
	// Rule 1 (spec, Defer statements): "the function value and parameters to the
	// call are evaluated as usual and saved" AT THE DEFER. So x is snapshotted
	// to 1 NOW, even though it runs at return.
	defer fmt.Printf("defer fmt.Printf(x): x = %d   (argument snapshotted at the defer)\n", x)
	// Rule 2: a deferred CLOSURE does not read x until it executes (at return).
	// By then x==99, so it prints 99.
	defer func() {
		fmt.Printf("defer func(){Printf(x)}: x = %d   (read at execution, LIFO)\n", x)
	}()
	x = 99
	fmt.Printf("x := 1; ...two defers...; x = 99   -> x is now %d\n", x)
	check("x mutated to 99 before the function returns", x == 99)
	// On return, deferred calls run LIFO: the closure (deferred last) runs FIRST
	// and prints 99; the snapshot (deferred first) runs SECOND and prints 1.
}

func main() {
	fmt.Println("functions_closures.go — Phase 1 bundle.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
