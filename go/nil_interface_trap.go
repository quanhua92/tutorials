//go:build ignore

// nil_interface_trap.go — Phase 2 bundle (THE classic Go bug).
//
// GOAL (one line): show, by printing every value, why a non-nil interface can
// hold a nil pointer — and why that turns a well-meant `return nil` into a
// lying error that fires every caller's `if err != nil`.
//
// This is the GROUND TRUTH for NIL_INTERFACE_TRAP.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run nil_interface_trap.go

package main

import (
	"fmt"
	"reflect"
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

// MyError is a concrete pointer-type that satisfies the `error` interface. Its
// nil value — `(*MyError)(nil)` — is the protagonist of THE bug.
type MyError struct {
	Code int
}

func (e *MyError) Error() string {
	return fmt.Sprintf("code %d", e.Code)
}

// bad returns a *MyError that happens to be nil. Because the return type is the
// INTERFACE `error`, the nil *MyError is boxed into a (type=*MyError, val=nil)
// interface on the way out — which is NOT nil. This is THE bug.
func bad() error {
	var e *MyError // e is a nil *MyError
	return e       // boxed into `error` -> (type=*MyError, val=nil) != nil
}

// good returns an explicit nil. Because no concrete value is ever stored, the
// returned `error` interface is genuinely (type=nil, val=nil) — i.e. nil.
func good() error {
	return nil
}

// sectionA shows that a bare interface value is nil only when BOTH its dynamic
// type AND dynamic value are nil — the (type, value) pair model from the spec.
func sectionA() {
	sectionBanner("A — The (type, value) pair: a truly nil interface")

	// A freshly declared interface value holds NOTHING: no type, no value.
	var i any // i is the zero value of `any`/`interface{}`: a nil interface
	fmt.Println("var i any")
	fmt.Printf("  i                 = %v\n", i)
	fmt.Printf("  i == nil          = %v   (type=nil, value=nil -> genuinely nil)\n", i == nil)

	// reflect.TypeOf returns nil ONLY for a nil interface (it never even sees a
	// type to report). This is the canonical "is this interface really nil?" test.
	t := reflect.TypeOf(i)
	fmt.Printf("  reflect.TypeOf(i) = %v   (nil -> the interface holds no type)\n", t)

	check("truly-nil interface compares == nil", i == nil)
	check("reflect.TypeOf(nil interface) == nil", t == nil)
}

// sectionB shows the SURPRISE: storing a nil *T into an interface produces a
// NON-NIL interface, because the interface now records type=*T. This is the
// single line that catches every Go programmer at least once.
func sectionB() {
	sectionBanner("B — The typed-nil trap: a nil pointer makes a non-nil interface")

	var p *int = nil // p is a nil pointer of concrete type *int
	var j any = p    // boxing: j records (type=*int, value=nil)
	fmt.Println("var p *int = nil; var j any = p")
	fmt.Printf("  p                 = %v\n", p)
	fmt.Printf("  p == nil          = %v   (the pointer itself IS nil)\n", p == nil)
	fmt.Printf("  j                 = %#v\n", j)
	fmt.Printf("  j == nil          = %v   <-- THE TRAP: type is *int, so j is NOT nil\n", j == nil)
	fmt.Printf("  reflect.TypeOf(j) = %v   (the interface remembers the type)\n", reflect.TypeOf(j))

	check("the nil pointer itself is nil", p == nil)
	check("the interface holding a nil *int is NON-nil (THE TRAP)", j != nil)
	check("reflect.TypeOf(typed-nil interface) is non-nil", reflect.TypeOf(j) != nil)

	// Two typed nils are equal only if their DYNAMIC TYPES agree. Different
	// concrete types -> unequal, even when both wrapped values are nil.
	var a any = (*int)(nil)
	var b any = (*string)(nil)
	var c any = (*int)(nil)
	fmt.Printf("  (*int)(nil)    == (*string)(nil) as interfaces? %v   (different types)\n", a == b)
	fmt.Printf("  (*int)(nil)    == (*int)(nil)    as interfaces? %v   (same type, both nil)\n", a == c)
	check("typed nils of different concrete types are NOT equal", a != b)
	check("typed nils of the same concrete type ARE equal", a == c)
}

// sectionC is THE bug in its native habitat: an error-returning function that
// hands back a typed nil, lying to every `if err != nil` caller. We also pin
// the two diagnosis tools (%#v and reflect.TypeOf) that reveal a typed nil.
func sectionC() {
	sectionBanner("C — THE bug: bad() returns a non-nil error from a nil *MyError")

	err := bad()
	fmt.Println("err := bad()")
	fmt.Printf("  err                = %#v\n", err)
	fmt.Printf("  err == nil         = %v   <-- caller's `if err != nil` FIRES (no real error!)\n", err == nil)
	fmt.Printf("  reflect.TypeOf(err)= %v   (non-nil: the interface holds type *MyError)\n", reflect.TypeOf(err))

	// Diagnosis tools that reveal a typed nil:
	//   %#v            -> (*main.MyError)(nil)   (type + nil value, explicit)
	//   reflect.TypeOf -> *main.MyError          (non-nil; a truly-nil error yields nil)
	check("bad() returns a NON-nil error even though *MyError is nil", err != nil)
	check("reflect.TypeOf(bad()'s error) is non-nil", reflect.TypeOf(bad()) != nil)
	check("reflect.TypeOf(a truly nil error) == nil", reflect.TypeOf(error(nil)) == nil)
}

// sectionD shows the one-line fix: return nil explicitly so no concrete value
// is ever stored in the interface. The error then crosses the boundary as a
// genuine (type=nil, value=nil).
func sectionD() {
	sectionBanner("D — The fix: good() returns nil explicitly")

	err := good()
	fmt.Println("err := good()")
	fmt.Printf("  err                = %#v\n", err)
	fmt.Printf("  err == nil         = %v   (genuinely nil: type=nil, value=nil)\n", err == nil)
	fmt.Printf("  reflect.TypeOf(err)= %v\n", reflect.TypeOf(err))

	check("good() returns a genuinely nil error", err == nil)
	check("reflect.TypeOf(good()'s error) == nil", reflect.TypeOf(err) == nil)
}

// sectionE shows the typed-nil leak traveling through realistic structures: an
// embedded interface field, and an error-wrapping helper. Once the nil pointer
// is boxed into an interface, the leak is "baked in" — passing it along never
// re-empties the interface. The only fix is to check the pointer BEFORE it
// becomes an interface.
func sectionE() {
	sectionBanner("E — The leak propagates: embedded fields & wrappers")

	// (1) Embedded interface field: assigning a nil *T fills the field's type
	// slot, so the field reads as non-nil — the Dave Cheney "Thing{P}" pattern.
	type Holder struct {
		err error // an interface field
	}
	var rawErr *MyError // nil
	h := Holder{err: rawErr}
	fmt.Println("h := Holder{err: (*MyError)(nil)}")
	fmt.Printf("  h.err == nil       = %v   (the field absorbed the type *MyError)\n", h.err == nil)
	check("embedded error field holds a non-nil typed nil", h.err != nil)

	// (2) A wrapper that returns its error argument unchanged: the leak was
	// already created at the boxing point inside `bad`, so wrapping is harmless
	// to the bug — the error stays non-nil end to end.
	wrap := func(e error) error { return e }
	wrapped := wrap(bad())
	fmt.Println("wrapped := wrap(bad())")
	fmt.Printf("  wrapped == nil     = %v   (boxing already happened; wrapping preserves it)\n", wrapped == nil)
	check("typed nil survives an identity wrapper unchanged", wrapped != nil)

	// (3) The defensive check for a pointer-returning helper: test the pointer
	// BEFORE it crosses the interface boundary, and return a bare nil.
	safe := func(e *MyError) error {
		if e == nil {
			return nil // never let a nil *MyError cross the interface boundary
		}
		return e
	}
	fmt.Println("safe((*MyError)(nil))")
	fmt.Printf("  safe(nil) == nil   = %v   (checked before boxing -> genuinely nil)\n", safe(nil) == nil)
	check("safe() converts a nil pointer into a genuinely nil error", safe(nil) == nil)
}

func main() {
	fmt.Println("nil_interface_trap.go — Phase 2 bundle (THE classic Go bug).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. An interface value == nil ONLY when BOTH its dynamic")
	fmt.Println("type AND dynamic value are nil. Storing a nil *T makes it non-nil.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
