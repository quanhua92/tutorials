//go:build ignore

// pointers.go — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how Go's address operator
// (&), dereference (*), pointer types (*T), new(T), and value-vs-pointer
// argument passing actually behave — and why dereferencing nil panics.
//
// This is the GROUND TRUTH for POINTERS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// Run:
//
//	go run pointers.go

package main

import (
	"fmt"
	"strings"
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

// --- types used across sections ---------------------------------------------

// Counter is a small aggregate used to show value-copy vs pointer-share on a
// function call. The [4]int makes the copy cost tangible: a value argument
// copies the WHOLE struct (all three fields) on every call.
type Counter struct {
	Hits int
	Tag  string
	Buf  [4]int
}

// Greeter is used in section E to show that an interface already boxes its
// dynamic value (as a (type, value) pair); mutating through a boxed *Greeter
// is visible in the caller.
type Greeter struct {
	Name string
}

// SetName mutates the receiver through a pointer.
func (g *Greeter) SetName(s string) { g.Name = s }

// Box is used in section F to demonstrate "returning the address of a local".
type Box struct {
	N int
}

// bumpValue takes Counter BY VALUE: it receives a copy of the whole struct.
// Mutations touch only the local copy; the caller's original is untouched.
func bumpValue(c Counter) {
	c.Hits++
	c.Tag = "bumped-by-value"
}

// bumpPtr takes Counter BY POINTER: no copy of the struct; the pointer aliases
// the caller's original, so the mutation is visible to the caller.
func bumpPtr(c *Counter) {
	c.Hits++
	c.Tag = "bumped-by-ptr"
}

// newBox returns the address of a local. Because the local `b` outlives the
// call (its address escapes), the compiler is FORCED to allocate `b` on the
// heap instead of the stack. The pointer is cheap to return but allocates.
func newBox() *Box {
	b := Box{N: 7} // would die with the stack frame; returning &b -> heap escape
	return &b
}

// mustNilDeref deliberately dereferences a nil pointer and returns the
// recovered panic message. The deferred recover() catches the run-time panic so
// this function (and the whole program) keeps running.
func mustNilDeref() (msg string, panicked bool) {
	defer func() {
		if r := recover(); r != nil {
			panicked = true
			msg = fmt.Sprintf("%v", r)
		}
	}()
	var p *int // zero value of *int is nil
	_ = *p     // nil pointer dereference -> run-time panic
	return "", false
}

// --- sections ---------------------------------------------------------------

// sectionA pins & (address-of), * (dereference), and the *T pointer type.
func sectionA() {
	sectionBanner("A — & (address), * (dereference), and the *T type")

	n := 10
	p := &n // &x generates a *T pointing at x (here *int)
	fmt.Printf("n := 10; p := &n    -> type(p) = %T, *p = %d, n = %d\n", p, *p, n)

	*p = 42 // *x denotes the variable pointed at; assigning writes THROUGH it
	fmt.Printf("*p = 42             -> n = %d  (wrote through the pointer)\n", n)

	// Two addresses of the SAME variable are equal: &n is stable across takes.
	p1, p2 := &n, &n
	fmt.Printf("&n == &n (same var) -> %v  (one addressable var has one address)\n", p1 == p2)

	// Address of a composite literal is the idiomatic way to get a *Struct.
	cp := &Counter{Hits: 3, Tag: "lit"}
	fmt.Printf("&Counter{...}       -> type %T, cp.Hits = %d, cp.Tag = %q\n", cp, cp.Hits, cp.Tag)

	check("*int is the pointer type of &n", fmt.Sprintf("%T", p) == "*int")
	check("*p = 42 makes n == 42", n == 42)
	check("&n taken twice yields equal pointers", p1 == p2)
	check("&Counter{...} yields *main.Counter", fmt.Sprintf("%T", cp) == "*main.Counter")

	// NOTE (documented in the .md; deliberately NOT compiled): Go has NO pointer
	// arithmetic. `p + 1`, `p++`, `p[i]` on a *T are all COMPILE ERRORS. The
	// only escape hatch is package `unsafe` (out of scope here).
}

// sectionB pins value-copy vs pointer-share on a function call.
func sectionB() {
	sectionBanner("B — Value copy vs pointer share (pass-by-value ALWAYS)")

	a := Counter{Hits: 0, Tag: "orig"}
	before := a
	bumpValue(a) // a is COPIED into the parameter; only the local copy is mutated
	fmt.Printf("after bumpValue(a)  -> a.Hits = %d, a.Tag = %q  (copy mutated, original intact)\n", a.Hits, a.Tag)
	check("by value: a unchanged after bumpValue", a == before)

	bumpPtr(&a) // a POINTER (itself copied) is passed; it aliases the original
	fmt.Printf("after bumpPtr(&a)   -> a.Hits = %d, a.Tag = %q  (mutated through the pointer)\n", a.Hits, a.Tag)
	check("by pointer: a.Hits == 1 after bumpPtr", a.Hits == 1)
	check("by pointer: a.Tag == bumped-by-ptr", a.Tag == "bumped-by-ptr")
}

// sectionC pins new(T) vs &T{}: both yield *T to a zero-valued T.
func sectionC() {
	sectionBanner("C — new(T) vs &T{} (both give *T; new is rarely used)")

	np := new(int) // *int pointing to a zero-valued (0) int
	fmt.Printf("new(int)    -> type %T, *new(int) = %d  (zero value)\n", np, *np)

	cp := &Counter{} // idiomatic: *Counter pointing to a zero-valued Counter
	fmt.Printf("&Counter{}  -> type %T, Hits = %d, Tag = %q  (zero value)\n", cp, cp.Hits, cp.Tag)

	sp := new(Counter) // equivalent type to &Counter{}; rarely written this way
	fmt.Printf("new(Counter) and &Counter{} share the type *Counter: %v\n",
		fmt.Sprintf("%T", sp) == fmt.Sprintf("%T", cp))

	check("*new(int) == 0 (new returns pointer to the zero value)", *np == 0)
	check("&Counter{} yields *main.Counter", fmt.Sprintf("%T", cp) == "*main.Counter")
	check("new(Counter) and &Counter{} have the same type *main.Counter",
		fmt.Sprintf("%T", sp) == "*main.Counter")
}

// sectionD pins that dereferencing a nil *T panics, recoverable via defer.
func sectionD() {
	sectionBanner("D — Nil pointer dereference panics (defer/recover)")

	var p *int
	fmt.Printf("var p *int -> p == nil ? %v  (zero value of *int)\n", p == nil)

	msg, panicked := mustNilDeref()
	fmt.Printf("defer/recover caught: panicked = %v\n", panicked)
	fmt.Printf("panic message: %s\n", msg)

	check("nil pointer deref panicked", panicked)
	check(`panic message contains "nil pointer"`, strings.Contains(msg, "nil pointer"))
}

// sectionE shows the pointer-to-interface anti-pattern: an interface already
// boxes its dynamic value, so taking its address is meaningless.
func sectionE() {
	sectionBanner("E — Pointer-to-interface is an anti-pattern")

	// An interface value is a (type, value) pair: it already holds the concrete
	// value (often itself a pointer). Storing a *Greeter in `any` lets us mutate
	// the ORIGINAL through the interface — no extra *any needed.
	g := Greeter{Name: "ann"}
	var i any = &g // the interface boxes the *Greeter directly
	i.(*Greeter).SetName("bea")
	fmt.Printf("interface held *Greeter; after type-assert + SetName: g.Name = %q\n", g.Name)
	fmt.Printf("dynamic type boxed in the interface: %T\n", i)

	check("interface boxes the pointer; mutation visible in original", g.Name == "bea")
	check("the boxed value is a *main.Greeter (type-assertable)", fmt.Sprintf("%T", i) == "*main.Greeter")

	// WRONG — pointer-to-interface anti-pattern (legal syntax, wrong idea):
	//   func bad(p *any) { /* ... */ } // *any: a pointer to an interface value
	//   var itf any = Greeter{}
	//   bad(&itf)                       // meaningless: the interface already holds
	//                                   // a (type, pointer-to-value) pair; the
	//                                   // extra * is noise that misleads readers
	//                                   // and tools. Use the interface value.
	// RIGHT:
	//   func good(v any) { /* ... */ }   // accept the interface value itself
	//   good(Greeter{})                  // box a value
	//   good(&Greeter{})                 // box a pointer to a value
}

// sectionF previews escape: returning &local forces the local onto the heap.
func sectionF() {
	sectionBanner("F — Returning &local forces it to escape (heap)")

	bp := newBox() // the local `b` inside newBox escaped to the heap
	got := bp.N    // 7: the value the local was initialized with
	fmt.Printf("newBox() -> type %T, bp.N = %d  (local survived via the returned pointer)\n", bp, got)

	bp.N = 99 // caller now owns the heap object and may mutate it
	fmt.Printf("bp.N = 99 -> bp.N = %d  (caller owns the heap object)\n", bp.N)

	// The compiler proved `b` outlives newBox(), so it allocates `b` on the heap
	// instead of the stack. Verify with:  go build -gcflags=-m pointers.go
	// (see ESCAPE_ANALYSIS for the full -gcflags=-m treatment).

	check("newBox returned &local; *bp == 7 (local survived the call)", got == 7)
	check("caller can mutate the heap object (bp.N = 99)", bp.N == 99)
}

func main() {
	fmt.Println("pointers.go — Phase 1 bundle.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
