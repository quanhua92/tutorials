//go:build ignore

// structs_methods.go — Phase 1 bundle #6.
//
// GOAL (one line): show, by printing every value, how Go structs, struct
// literals, embedding (composition, NOT inheritance), and value- vs pointer-
// receiver methods behave — including the method-set rule (spec) that ties
// structs to interfaces.
//
// This is the GROUND TRUTH for STRUCTS_METHODS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run structs_methods.go

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

// Point — a tiny aggregate for the struct-literal section.
type Point struct {
	X int
	Y int
}

// Engine — embedded into Car to demonstrate field & method promotion.
type Engine struct {
	Power int
	Name  string
}

// Describe is a VALUE-receiver method on Engine. Because Car embeds Engine,
// Describe is PROMOTED to Car via selector forwarding (composition, not
// inheritance — there is no subtype relationship between Car and Engine).
func (e Engine) Describe() string {
	return fmt.Sprintf("engine %q @ %d kW", e.Name, e.Power)
}

// Car embeds Engine as an UNNAMED field (an "embedded field"). The field name
// is the unqualified type name, "Engine". Engine's fields (Power, Name) and
// methods (Describe) are promoted to Car through selector forwarding.
type Car struct {
	Engine // embedded field; name == "Engine"
	Wheels int
}

// Counter — carries BOTH a value-receiver and a pointer-receiver "increment"
// so Section C can pin that the value receiver mutates only a copy while the
// pointer receiver mutates the original.
type Counter struct {
	N int
}

// IncValue has a VALUE receiver: c is a COPY of the caller's Counter, so the
// increment is applied to the copy and then discarded. The caller sees nothing.
func (c Counter) IncValue() { c.N++ }

// IncPtr has a POINTER receiver: c points at the caller's Counter, so the
// increment is written through to the original storage. The caller sees +1.
func (c *Counter) IncPtr() { c.N++ }

// Widget — carries a mix of value- and pointer-receiver methods so Section D
// can show via reflect that the method set of *Widget is strictly larger than
// the method set of Widget (all three methods are EXPORTED so reflect counts
// them; reflect hides unexported methods from NumMethod).
type Widget struct {
	W, H int
}

// Area and Perimeter are VALUE-receiver methods -> in the method set of BOTH
// Widget and *Widget.
func (w Widget) Area() int      { return w.W * w.H }
func (w Widget) Perimeter() int { return 2 * (w.W + w.H) }

// Scale is a POINTER-receiver method -> in the method set of *Widget ONLY.
// A Widget value (not a pointer) CANNOT satisfy an interface requiring Scale.
func (w *Widget) Scale(n int) { w.W *= n; w.H *= n }

// Tagged — carries struct tags (the preview concept). Tags are optional string
// literals made visible through reflection; encoding/json reads the `json:"...`
// convention. Tags take part in type identity for structs (two structs that
// differ only by a tag are DISTINCT types).
type Tagged struct {
	Name   string `json:"name"`
	Hidden string `json:"-"`
	Plain  string
}

// methodNames returns the (already name-sorted) method names of a reflect.Type.
// reflect's Method(i) is deterministic, so the output is byte-stable.
func methodNames(t reflect.Type) []string {
	names := make([]string, 0, t.NumMethod())
	for i := 0; i < t.NumMethod(); i++ {
		names = append(names, t.Method(i).Name)
	}
	return names
}

// sectionA: struct literals — positional vs named, partial, and the zero struct.
func sectionA() {
	sectionBanner("A — STRUCT LITERALS: positional vs named, partial, zero struct")

	// Named literal (PREFERRED): order-independent, self-documenting, and
	// survives field reordering in the type declaration.
	named := Point{X: 1, Y: 2}
	// Positional literal: must list ALL fields in declaration order; fragile
	// (adding/reordering a field silently breaks every positional literal).
	pos := Point{1, 2}
	fmt.Printf("Point{X:1, Y:2}  (named, preferred) = %v\n", named)
	fmt.Printf("Point{1, 2}      (positional)       = %v\n", pos)

	// Partial named literal: omitted fields take their zero value.
	partial := Point{Y: 9} // X omitted -> the zero value 0
	fmt.Printf("Point{Y:9}       (partial)          = %v  (X == 0, the zero value)\n", partial)

	// Zero struct: a var decl with no initializer zeroes every field.
	var zero Point
	fmt.Printf("var zero Point                     = %v   (%#v)\n", zero, zero)

	check("named == positional: Point{X:1,Y:2} == Point{1,2}", named == pos)
	check("partial literal zeroes omitted fields: Point{Y:9} == {0 9}", partial == Point{X: 0, Y: 9})
	check("zero struct Point == {0 0}", zero == Point{})
}

// sectionB: embedding promotes the embedded type's fields AND methods through
// selector forwarding. This is COMPOSITION (a has-a field), not inheritance
// (there is no is-a subtype, no virtual dispatch, no override).
func sectionB() {
	sectionBanner("B — EMBEDDING: promoted fields & methods (composition, NOT inheritance)")

	// The embedded field is named with its type name, so you initialize it as
	// `Engine: Engine{...}`. Promoted fields CANNOT be keys in a composite
	// literal: `Car{Power: 300}` is a COMPILE ERROR (documented in the .md).
	c := &Car{Engine: Engine{Name: "V8", Power: 300}, Wheels: 4}
	fmt.Printf("c := &Car{Engine: Engine{Name:%q, Power:%d}, Wheels:%d}\n", c.Name, c.Power, c.Wheels)

	// Promoted FIELDS: c.Power and c.Name forward to c.Engine.Power / .Name.
	fmt.Printf("c.Power (promoted) == %d   c.Engine.Power == %d  (same storage)\n", c.Power, c.Engine.Power)
	fmt.Printf("c.Name  (promoted) == %q   c.Wheels        == %d (declared on Car)\n", c.Name, c.Wheels)

	// Promoted FIELD WRITE on an addressable struct reaches the embedded field.
	c.Power = 400 // forwards to c.Engine.Power
	fmt.Printf("c.Power = 400  ->  c.Engine.Power == %d  (promoted write reaches embedded field)\n", c.Engine.Power)

	// Promoted METHOD: c.Describe() forwards to c.Engine.Describe().
	descC := c.Describe()
	descEng := c.Engine.Describe()
	fmt.Printf("c.Describe()        == %s\n", descC)
	fmt.Printf("c.Engine.Describe() == %s  (identical: forwarding, same receiver)\n", descEng)

	// Proof it is COMPOSITION (has-a), not inheritance (is-a): the embedded
	// field is an ordinary field you can extract as a value. There is NO
	// subtype relationship — you cannot assign a *Car to a *Engine variable.
	var extracted Engine = c.Engine // legal: copy the embedded field out
	fmt.Printf("var extracted Engine = c.Engine  ->  %v  (embedding is a field, extractable)\n", extracted)

	check("promoted field c.Power == c.Engine.Power", c.Power == c.Engine.Power)
	check("promoted field write reaches the embedded field: c.Engine.Power == 400", c.Engine.Power == 400)
	check("promoted method c.Describe() == c.Engine.Describe()", descC == descEng)
	check("embedding is a field: extracted == c.Engine", extracted == c.Engine)
}

// sectionC: value vs pointer receiver — the central value/pointer axis. A value
// receiver operates on a COPY (mutations lost); a pointer receiver operates on
// the original (mutations visible) and avoids copying large structs.
func sectionC() {
	sectionBanner("C — VALUE vs POINTER RECEIVER (copy vs mutate)")

	// VALUE receiver: IncValue gets a COPY of `a`, increments the copy, and the
	// copy is discarded. The caller's `a` is untouched.
	a := Counter{N: 0}
	a.IncValue()
	fmt.Printf("a := Counter{N:0}; a.IncValue()  ->  a.N == %d  (value receiver mutated a COPY)\n", a.N)

	// POINTER receiver: IncPtr points at the caller's storage, so the increment
	// is written through to the original. Explicit & first.
	b := Counter{N: 0}
	(&b).IncPtr()
	fmt.Printf("b := Counter{N:0}; (&b).IncPtr() ->  b.N == %d  (pointer receiver mutated ORIGINAL)\n", b.N)

	// AUTO-ADDRESSING: b is an addressable local variable, so Go lets you write
	// b.IncPtr() and silently rewrites it to (&b).IncPtr() for you.
	c := Counter{N: 0}
	c.IncPtr()
	fmt.Printf("c := Counter{N:0}; c.IncPtr()    ->  c.N == %d  (auto &: c is addressable)\n", c.N)

	check("value receiver IncValue does not change the original: a.N still 0", a.N == 0)
	check("pointer receiver IncPtr mutates the original: b.N == 1", b.N == 1)
	check("auto-addressing: c.IncPtr() behaves as (&c).IncPtr(), c.N == 1", c.N == 1)
}

// sectionD: METHOD SETS (spec). The method set of T contains value-receiver
// methods only; the method set of *T contains BOTH value- and pointer-receiver
// methods. reflect.NumMethod exposes exactly this distinction.
func sectionD() {
	sectionBanner("D — METHOD SETS (spec): T has value-receiver methods; *T has BOTH")

	vt := reflect.TypeOf(Widget{})  // the type Widget
	pt := reflect.TypeOf(&Widget{}) // the type *Widget

	fmt.Printf("Widget methods declared:\n")
	fmt.Printf("  func (w Widget)  Area()       // value receiver -> in Widget AND *Widget\n")
	fmt.Printf("  func (w Widget)  Perimeter()  // value receiver -> in Widget AND *Widget\n")
	fmt.Printf("  func (w *Widget) Scale(n)     // pointer receiver -> in *Widget ONLY\n")
	fmt.Printf("reflect.TypeOf(Widget{}).NumMethod()  = %d   (value-receiver methods only)\n", vt.NumMethod())
	fmt.Printf("reflect.TypeOf(&Widget{}).NumMethod() = %d   (value + pointer receivers)\n", pt.NumMethod())
	fmt.Printf("method set of Widget : %v\n", methodNames(vt))
	fmt.Printf("method set of *Widget: %v\n", methodNames(pt))

	check("method set of Widget (value) has 2 methods: Area, Perimeter", vt.NumMethod() == 2)
	check("method set of *Widget has 3 methods: Area, Perimeter, Scale", pt.NumMethod() == 3)
	check("*Widget has strictly MORE methods than Widget", pt.NumMethod() > vt.NumMethod())
	_, scaleInValue := vt.MethodByName("Scale") // value method set
	_, scaleInPtr := pt.MethodByName("Scale")   // pointer method set
	check("Scale (pointer-receiver) is NOT in Widget's method set but IS in *Widget's",
		!scaleInValue && scaleInPtr)
}

// sectionE: ADDRESSABILITY. A pointer-receiver method can be auto-called
// (Go inserts &) only on an ADDRESSABLE operand: a variable, a pointer
// indirection, a slice element, or a &composite-literal. Map elements and bare
// composite literals are NOT addressable -> calling a pointer method on them is
// a COMPILE ERROR (documented below, not run).
func sectionE() {
	sectionBanner("E — ADDRESSABILITY: where pointer-receiver methods can be auto-called")

	// (1) Addressable local variable -> Go auto-inserts &.
	v := Counter{N: 0}
	v.IncPtr() // == (&v).IncPtr()
	fmt.Printf("v := Counter{N:0};        v.IncPtr()  -> v.N == %d   (local var is addressable)\n", v.N)

	// (2) &composite-literal is addressable (the spec's composite-literal
	// exception to the addressability rule).
	lit := &Counter{N: 10}
	lit.IncPtr()
	fmt.Printf("lit := &Counter{N:10};    lit.IncPtr() -> lit.N == %d  (&composite literal addressable)\n", lit.N)

	// (3) Slice ELEMENTS are addressable (they act like variables into the
	// backing array) — contrast with map elements, which are NOT.
	s := []Counter{{N: 1}, {N: 2}}
	s[0].IncPtr() // s[0] is addressable
	fmt.Printf("s := []Counter{{1},{2}}; s[0].IncPtr() -> s[0].N == %d  (slice element addressable)\n", s[0].N)

	// NOT addressable -> COMPILE ERRORS (documented here; not in the runnable
	// source because they would not build):
	//   m := map[string]Counter{"k": {N: 0}}
	//   m["k"].IncPtr()         // ERROR: cannot call pointer method on m["k"] (map elem not addressable)
	//   Counter{N: 0}.IncPtr()  // ERROR: cannot call pointer method on a bare composite literal
	fmt.Println("NOT addressable (compile errors, documented): m[k].IncPtr() and Counter{}.IncPtr()")

	check("addressable local var: v.IncPtr() works, v.N == 1", v.N == 1)
	check("&composite literal is addressable: lit.N == 11", lit.N == 11)
	check("slice element is addressable: s[0].IncPtr() -> s[0].N == 2", s[0].N == 2)
}

// sectionF: STRUCT TAGS (preview). An optional string-literal tag follows a
// field declaration; reflect.StructTag exposes it and encoding/json reads the
// `json:"..."` convention. Tags take part in type identity for structs.
func sectionF() {
	sectionBanner("F — STRUCT TAGS (preview): reflect.StructTag, read by encoding/json")

	t := reflect.TypeOf(Tagged{})
	fmt.Printf("type Tagged struct {\n")
	fmt.Printf("    Name   string `json:\"name\"`\n")
	fmt.Printf("    Hidden string `json:\"-\"`\n")
	fmt.Printf("    Plain  string   (no tag)\n")
	fmt.Printf("}\n")
	fmt.Printf("field        raw tag            reflect .Get(\"json\")\n")
	fmt.Printf("------------ ------------------ ----------------------\n")
	for i := 0; i < t.NumField(); i++ {
		f := t.Field(i)
		raw := string(f.Tag)
		if raw == "" {
			raw = "(no tag)"
		}
		fmt.Printf("%-12s %-18s %q\n", f.Name, raw, f.Tag.Get("json"))
	}

	check(`reflect parses json tag: Field("Name").Tag.Get("json") == "name"`, t.Field(0).Tag.Get("json") == "name")
	check(`json:"-" is the encoding/json omit marker: Field("Hidden").Get == "-"`, t.Field(1).Tag.Get("json") == "-")
	check(`a field with no tag yields "": Field("Plain").Get == ""`, t.Field(2).Tag.Get("json") == "")
}

func main() {
	fmt.Println("structs_methods.go — Phase 1 bundle #6.")
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
