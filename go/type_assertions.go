//go:build ignore

// type_assertions.go — Phase 2 bundle.
//
// GOAL (one line): show, by printing every value, how Go's type assertions,
// type switches, conversions, named/underlying types, and assignability behave.
//
// This is the GROUND TRUTH for TYPE_ASSERTIONS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run type_assertions.go

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

// --- named types used across sections C/D/E -------------------------------

// Celsius is a NAMED type whose UNDERLYING type is float64. Celsius and
// float64 are DISTINCT named types (spec: "A named type is always different
// from any other type"), so they are NOT assignable to each other without a
// conversion — even though their underlying type is identical.
type Celsius float64

// PosA and PosB are two distinct named struct types whose underlying type is
// the SAME unnamed struct literal `struct{ X, Y int }`. They are not identical
// (both are named) and therefore not assignable — but ARE convertible, and
// each IS assignable to an unnamed `struct{ X, Y int }` (one side unnamed).
type PosA struct{ X, Y int }
type PosB struct{ X, Y int }

// mustBadAssert runs the single-return form `i.(string)` on an interface that
// holds an int, and returns the recovered panic message. A deferred recover()
// catches the run-time panic so this program keeps running (see §CONTROL_FLOW_DEFER).
func mustBadAssert(i any) (msg string, panicked bool) {
	defer func() {
		if r := recover(); r != nil {
			panicked = true
			msg = fmt.Sprintf("%v", r)
		}
	}()
	_ = i.(string) // single-return assertion -> run-time panic when i holds a non-string
	return "", false
}

// sectionA pins the single-return assertion (panics on failure) versus the
// comma-ok form (returns (zero, false) on failure, NO panic).
func sectionA() {
	sectionBanner("A — Single vs comma-ok assertion (panic vs safe)")

	var i any = 7 // i holds a dynamic (type=int, value=7) pair

	// Two-return (comma-ok) form: safe. On miss returns (zero, false).
	vInt, okInt := i.(int)
	fmt.Printf("i = 7 (int);   v, ok := i.(int)    -> v=%v, ok=%t\n", vInt, okInt)

	vStr, okStr := i.(string)
	fmt.Printf("              v, ok := i.(string) -> v=%q, ok=%t  (zero value, no panic)\n", vStr, okStr)

	// Single-return form: UNSAFE. A miss is a run-time panic — we recover it
	// so the program survives and we can print the exact message.
	msg, panicked := mustBadAssert(i)
	fmt.Printf("i.(string) single-form -> panicked=%t\n", panicked)
	fmt.Printf("panic message: %s\n", msg)

	check("i.(int) comma-ok -> v=7, ok=true", vInt == 7 && okInt)
	check(`i.(string) comma-ok -> v="", ok=false (zero value)`, vStr == "" && !okStr)
	check("i.(string) single-form panics", panicked)
	check("panic substring 'interface conversion'", strings.Contains(msg, "interface conversion"))
	check("panic substring 'is int, not string'", strings.Contains(msg, "is int, not string"))
}

// sectionB shows a type switch dispatching over a heterogeneous []any. The
// short-declared variable in the guard takes, in each case, the type listed in
// that case. A `default` (or a multi-type case) leaves it as the interface type.
func sectionB() {
	sectionBanner("B — Type switch dispatch on a mixed []any")

	vals := []any{7, "hi", 3.14}
	for _, v := range vals {
		// `t` is RE-DECLARED per case with THAT case's type (int, string,
		// float64). In `default`/multi-type cases `t` would have type `any`.
		switch t := v.(type) {
		case int:
			fmt.Printf("int       %v   (type of t in this case: %T)\n", t, t)
		case string:
			fmt.Printf("string    %v   (type of t in this case: %T)\n", t, t)
		case float64:
			fmt.Printf("float64   %v (type of t in this case: %T)\n", t, t)
		default:
			fmt.Printf("default   %v   (type of t in this case: %T)\n", t, t)
		}
	}

	// A single case may list MULTIPLE types (case int, int64). When it does,
	// the guard variable keeps the interface type — the compiler cannot pick
	// one. Demonstrate by routing two integer kinds through one branch.
	mixed := []any{int(3), int64(3)}
	for _, v := range mixed {
		switch t := v.(type) {
		case int, int64:
			// In a MULTI-TYPE case the guard variable keeps the STATIC type of
			// the guard expression (`any` here), because the case cannot commit
			// to a single concrete type. Proof: t is still an interface, so we
			// can run a SECOND assertion on it to recover a concrete type.
			n, ok := t.(int) // legal ONLY because t's static type is `any`
			fmt.Printf("int|int64 branch: value=%v, second t.(int) -> %v, %t\n", v, n, ok)
		default:
			fmt.Printf("default: %v\n", v)
		}
	}

	check("7 routes to the int case", func() bool { _, ok := any(7).(int); return ok }())
	check("3.14 routes to the float64 case", func() bool { _, ok := any(3.14).(float64); return ok }())
	check("int64(3) routes to the int,int64 branch", func() bool {
		switch any(int64(3)).(type) {
		case int, int64:
			return true
		}
		return false
	}())
}

// sectionC contrasts CONVERSION `T(x)` (compile-time-checked, changes the
// representation: numeric->numeric, named<->underlying) with ASSERTION
// `i.(T)` (run-time inspection of an interface's dynamic type).
func sectionC() {
	sectionBanner("C — Conversion T(x) vs assertion i.(T)")

	// CONVERSION: a static, compile-time-checked operation that changes the
	// representation. float64 -> Celsius is legal because both are floating-
	// point types AND because Celsius's underlying type is float64.
	var f float64 = 5.0
	c := Celsius(f)
	fmt.Printf("Celsius(float64(5.0)) -> value=%v, type=%T  (conversion: static)\n", c, c)

	// ASSERTION: a run-time inspection of the interface's (type,value) pair.
	// The compiler emits a dynamic type check; the result is the value or panic.
	var i any = 42
	n, ok := i.(int)
	fmt.Printf("i = 42 (any); n, ok := i.(int) -> n=%v, ok=%t   (assertion: runtime)\n", n, ok)

	s, okS := i.(string)
	fmt.Printf("             s, ok := i.(string) -> s=%q, ok=%t  (assertion miss -> zero, false)\n", s, okS)

	// The key contrast: you CANNOT convert an interface value to a concrete
	// type with T(i). `int(i)` where i is `any` is a COMPILE ERROR even when i
	// happens to hold an int at run time. The conversion operates on the
	// STATIC type of i (which is `any`); only the assertion inspects the
	// dynamic type. (The error is documented in the .md; not compiled here.)

	check("Celsius(float64(5.0)) converts -> value 5", c == Celsius(5.0))
	check("conversion result type is Celsius", fmt.Sprintf("%T", c) == "main.Celsius")
	check("i.(int) assertion -> n=42, ok=true", n == 42 && ok)
	check(`i.(string) assertion -> s="", ok=false`, s == "" && !okS)
}

// sectionD pins named type vs underlying type: Celsius and float64 share an
// underlying type (float64) but are DISTINCT named types, so they are
// convertible (identical underlying types) but NOT assignable and NOT directly
// comparable. A common-type conversion is required to compare them.
func sectionD() {
	sectionBanner("D — Named type vs underlying type (Celsius vs float64)")

	// An untyped constant is representable as Celsius (its underlying float64
	// accepts 5.0), so this assignment is legal without an explicit conversion.
	var c Celsius = 5.0
	fmt.Printf("var c Celsius = 5.0  -> value=%v, type=%T\n", c, c)

	// CONVERTIBLE: identical underlying types -> Celsius(x) / float64(c) OK.
	f := float64(c)
	fmt.Printf("f := float64(c)      -> value=%v, type=%T\n", f, f)

	// COMPARABLE within the SAME named type.
	fmt.Printf("c == Celsius(5.0)    -> %t   (same named type)\n", c == Celsius(5.0))

	// COMPARABLE across named types ONLY after a conversion to a common type.
	fmt.Printf("float64(c) == 5.0    -> %t   (convert to common type first)\n", float64(c) == 5.0)

	// NOT ASSIGNABLE without conversion (compile error, documented in the .md):
	//   var f2 float64 = c   // cannot use c (variable of type Celsius) as float64 value
	// NOT DIRECTLY COMPARABLE (compile error, documented in the .md):
	//   _ = c == float64(5.0) // invalid operation (mismatched types Celsius and float64)

	check("c value is 5", c == Celsius(5.0))
	check("float64(c) == 5.0 (convert to compare)", float64(c) == 5.0)
	check("Celsius underlying type is float64 (convertible)", float64(c) == float64(Celsius(5)))
}

// sectionE exercises the assignability rule on two named struct types with an
// identical underlying literal: PosA and PosB are distinct (both named) so
// they are NOT assignable to each other, but each IS assignable to the unnamed
// literal `struct{ X, Y int }` (exactly one side is unnamed).
func sectionE() {
	sectionBanner("E — Assignability edge: named structs, identical underlying")

	a := PosA{1, 2}
	fmt.Printf("a := PosA{1,2} -> %v, type %T\n", a, a)

	// CONVERTIBLE: identical underlying struct literal (struct{ X, Y int }).
	b := PosB(a) // legal conversion
	fmt.Printf("b := PosB(a)   -> %v, type %T  (conversion: identical underlying)\n", b, b)

	// ASSIGNABLE to an UNNAMED struct literal: one side is not a named type.
	// Spec: "V and T have identical underlying types ... and at least one of V
	// or T is not a named type." Here T = `struct{ X, Y int }` is unnamed.
	var anon struct{ X, Y int } = a // legal: PosA -> unnamed struct literal
	fmt.Printf("var anon struct{X,Y int} = a -> %v, type %T  (assignable: T is unnamed)\n", anon, anon)

	// NOT ASSIGNABLE PosA -> PosB (both named; documented in the .md):
	//   var b2 PosB = a  // cannot use a (variable of type PosA) as PosB value

	check("PosB(PosA{1,2}) converts (X=1,Y=2)", b.X == 1 && b.Y == 2)
	check("PosA -> unnamed struct{X,Y int} is assignable", anon.X == 1 && anon.Y == 2)
	check("PosB is a distinct named type from PosA", fmt.Sprintf("%T", b) == "main.PosB")
}

func main() {
	fmt.Println("type_assertions.go — Phase 2 bundle.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
