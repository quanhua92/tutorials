//go:build ignore

// interfaces_basics.go — Phase 2 bundle (Interfaces & Type System).
//
// GOAL (one line): show, by printing every value, how Go interfaces work —
// implicit satisfaction by method sets, the method-set rule (T vs *T), the
// (type,value) interface pair & boxing, interface embedding, and "accept
// interfaces, return structs".
//
// This is the GROUND TRUTH for INTERFACES_BASICS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run interfaces_basics.go

package main

import (
	"bytes"
	"fmt"
	"io"
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

// --- types used across sections ---------------------------------------------

// Stringer is a one-method interface. Any type with a `String() string` method
// SATISFIES it implicitly — there is no `implements` keyword, no declaration
// linking a concrete type to the interface.
type Stringer interface {
	String() string
}

// Dog satisfies Stringer implicitly: it has a String() string method, so its
// method set is a superset of Stringer's method set. Dog never names Stringer.
type Dog struct{ Name string }

func (d Dog) String() string { return "dog:" + d.Name }

// Cat satisfies Stringer by the same implicit rule.
type Cat struct{ Name string }

func (c Cat) String() string { return "cat:" + c.Name }

// I is a one-method interface used to pin the METHOD-SET RULE in section B.
type I interface {
	M()
}

// W has exactly ONE method, M, declared with a POINTER receiver. Per the spec,
// M is in the method set of *W but NOT in the method set of W. So only *W
// satisfies I; a bare W value does not (a compile error, documented in B).
type W struct{ N int }

func (w *W) M() { w.N++ }

// Greeter and Namer are two small interfaces embedded into GreeterNamer in
// section D to demonstrate INTERFACE EMBEDDING (the union of method sets).
type Greeter interface{ Greet() string }
type Namer interface{ Name() string }

// GreeterNamer embeds Greeter and Namer. Its method set is the UNION of the two
// — identical in effect to declaring Greet() and Name() directly. The spec
// phrases this as the intersection of the embedded type sets.
type GreeterNamer interface {
	Greeter
	Namer
}

// Person satisfies BOTH Greet and Name (value receivers), so a Person value
// satisfies GreeterNamer.
type Person struct{ name string }

func (p Person) Name() string  { return p.name }
func (p Person) Greet() string { return "hi, " + p.name }

// methodNames returns the (already name-sorted by reflect) method names of a
// reflect.Type. reflect's Method(i) is deterministic, so output is byte-stable.
func methodNames(t reflect.Type) []string {
	names := make([]string, 0, t.NumMethod())
	for i := 0; i < t.NumMethod(); i++ {
		names = append(names, t.Method(i).Name)
	}
	return names
}

// sectionA — IMPLICIT SATISFACTION. Dog and Cat satisfy Stringer without ever
// naming it; collect them into a []Stringer and dispatch polymorphically. The
// empty interface (any) is satisfied by every type.
func sectionA() {
	sectionBanner("A — IMPLICIT SATISFACTION (no `implements` keyword)")

	var s Stringer = Dog{Name: "Rex"} // Dog satisfies Stringer implicitly
	fmt.Printf("var s Stringer = Dog{Name:%q}\n", "Rex")
	fmt.Printf("s.String()  = %q   (dispatched to Dog.String)\n", s.String())
	fmt.Printf("s %%T        = %T   (the CONCRETE type, not Stringer)\n", s)

	// Polymorphism: a slice of the interface type holds DIFFERENT concrete
	// types; each String() call dispatches to that type's own method.
	zoo := []Stringer{Dog{Name: "Rex"}, Cat{Name: "Tom"}, Dog{Name: "Ace"}}
	fmt.Println("[]Stringer{ Dog{Rex}, Cat{Tom}, Dog{Ace} } ->")
	for _, s := range zoo {
		fmt.Printf("    %T -> %s\n", s, s.String())
	}

	// The EMPTY interface (any == interface{}) has zero methods, so EVERY type
	// satisfies it — a Dog, an int, and a string all box into `any`.
	var anything any
	anything = Dog{Name: "Rex"}
	fmt.Printf("any holds Dog: %%T=%T %%v=%v\n", anything, anything)
	anything = 42
	fmt.Printf("any holds int: %%T=%T %%v=%v\n", anything, anything)
	anything = "go"
	fmt.Printf("any holds str: %%T=%T %%v=%v\n", anything, anything)

	check("Dog satisfies Stringer (implicit)", s.String() == "dog:Rex")
	check("[]Stringer dispatches per concrete type",
		zoo[0].String() == "dog:Rex" && zoo[1].String() == "cat:Tom" && zoo[2].String() == "dog:Ace")
	check("any (empty interface) is satisfied by every type: holds a string here",
		fmt.Sprintf("%T", anything) == "string")
	check("any and interface{} are the identical type",
		reflect.TypeOf((*any)(nil)).Elem() == reflect.TypeOf((*interface{})(nil)).Elem())
}

// sectionB — THE METHOD-SET RULE (spec). The method set of T contains only its
// value-receiver methods; the method set of *T contains BOTH value- and
// pointer-receiver methods. So a pointer-receiver method is satisfiable ONLY by
// *T, never by a bare T value.
func sectionB() {
	sectionBanner("B — METHOD-SET RULE: T has value methods; *T has BOTH")

	vt := reflect.TypeOf(W{})  // the type W
	pt := reflect.TypeOf(&W{}) // the type *W
	fmt.Printf("W declares: func (w *W) M()   // POINTER receiver -> in *W ONLY\n")
	fmt.Printf("reflect.TypeOf(W{}).NumMethod()  = %d   (value-receiver methods of W)\n", vt.NumMethod())
	fmt.Printf("reflect.TypeOf(&W{}).NumMethod() = %d   (value + pointer methods of *W)\n", pt.NumMethod())
	fmt.Printf("method set of W : %v\n", methodNames(vt))
	fmt.Printf("method set of *W: %v\n", methodNames(pt))

	// The consequence: only *W satisfies I.
	var i I = &W{} // legal: *W's method set is a superset of I's
	fmt.Printf("var i I = &W{}  -> %%T=%T  (legal: *W satisfies I)\n", i)

	// The line below is a COMPILE ERROR and is deliberately NOT compiled (a
	// file containing it would not build). It is the canonical statement of the
	// method-set rule: because M has a pointer receiver, a bare W value does
	// NOT implement I.
	//
	//   var i I = W{}   // COMPILE ERROR: W does not implement I
	//                   //   (method M has pointer receiver)
	fmt.Println("COMPILE ERROR (documented, not run): var i I = W{}  // W does not implement I")

	check("W's method set is EMPTY (M is pointer-receiver)", vt.NumMethod() == 0)
	check("*W's method set has 1 method: M", pt.NumMethod() == 1)
	check("*W has strictly MORE methods than W", pt.NumMethod() > vt.NumMethod())
	check("*W satisfies I (concrete type is *main.W)",
		fmt.Sprintf("%T", i) == "*main.W")
}

// sectionC — the (type,value) INTERFACE PAIR. An interface value is a 2-word
// struct: an itable pointer + a data pointer. Assigning a concrete value BOXES
// a COPY into the interface (so mutating the source afterward does not affect
// the interface value). %T reports the CONCRETE type, not the interface type.
func sectionC() {
	sectionBanner("C — INTERFACE VALUE = (type, value) PAIR (boxing copies)")

	// %T on an interface value prints the CONCRETE (dynamic) type, never the
	// static interface type.
	var s Stringer = Dog{Name: "Rex"}
	fmt.Printf("var s Stringer = Dog{Name:%q}\n", "Rex")
	fmt.Printf("static type of s   : Stringer (the interface)\n")
	fmt.Printf("%%T (concrete type): %T   (the dynamic type inside the pair)\n", s)
	fmt.Printf("%%v (concrete val) : %v\n", s)

	// BOXING COPIES: storing an int in `any` copies the int; the interface
	// value's data word points at the copy, not at n.
	n := 7
	var a any = n // boxes a COPY of n into the interface
	fmt.Printf("n := 7; var a any = n  -> a == %v (a boxed copy)\n", a)
	n = 999 // mutate the SOURCE after boxing
	fmt.Printf("n = 999 (mutate source) -> a == %v (the boxed copy is UNCHANGED)\n", a)

	// The same copy rule for a struct value stored in an interface.
	d := Dog{Name: "Rex"}
	var sd Stringer = d // boxes a copy of d
	d.Name = "BOOM"     // mutate the source
	fmt.Printf("d.Name=%q before; after d.Name=\"BOOM\", sd=%v (copy, source mutation invisible)\n", "Rex", sd)

	check("interface %T reports the concrete type, not the interface", fmt.Sprintf("%T", s) == "main.Dog")
	check("boxing copies: mutating source n=999 leaves boxed a == 7", a.(int) == 7)
	check("boxing copies structs: sd unchanged after d.Name=BOOM", sd.String() == "dog:Rex")
}

// sectionD — INTERFACE EMBEDDING. An interface may embed other interfaces; its
// method set is the UNION of its own methods and the embedded interfaces'
// methods. io.ReadWriter embeds io.Reader + io.Writer the same way.
func sectionD() {
	sectionBanner("D — INTERFACE EMBEDDING (union of method sets)")

	p := Person{name: "Ada"}
	var gn GreeterNamer = p // Person has BOTH Greet and Name -> satisfies GreeterNamer
	fmt.Printf("type GreeterNamer interface { Greeter; Namer }  // embedded union\n")
	fmt.Printf("var gn GreeterNamer = Person{name:%q}\n", "Ada")
	fmt.Printf("gn.Greet() = %q   gn.Name() = %q\n", gn.Greet(), gn.Name())

	t := reflect.TypeOf((*GreeterNamer)(nil)).Elem()
	fmt.Printf("GreeterNamer method set: %v  (union of Greet + Name)\n", methodNames(t))

	check("Person satisfies GreeterNamer (has Greet and Name)",
		gn.Greet() == "hi, Ada" && gn.Name() == "Ada")
	check("GreeterNamer's method set is the union {Greet, Name}",
		t.NumMethod() == 2)
}

// sectionE — ACCEPT INTERFACES, RETURN STRUCTS. A function parameter typed as
// an interface (here io.Reader) is satisfied by ANY concrete type whose method
// set is a superset — so one function body serves bytes.NewReader,
// strings.NewReader, and *bytes.Buffer alike (no network, pure stdlib).
func sectionE() {
	sectionBanner("E — ACCEPT INTERFACES, RETURN STRUCTS (polymorphic io.Reader)")

	// readN takes an io.Reader (the interface) and works for ANY concrete type
	// that implements Read([]byte) (int, error).
	readN := func(r io.Reader, n int) (string, error) {
		buf := make([]byte, n)
		if _, err := io.ReadFull(r, buf); err != nil {
			return "", err
		}
		return string(buf), nil
	}

	srcs := []struct {
		kind string
		r    io.Reader
	}{
		{"strings.NewReader", strings.NewReader("hello")},
		{"bytes.NewReader", bytes.NewReader([]byte("world"))},
		{"*bytes.Buffer", bytes.NewBufferString("buff!")},
	}
	fmt.Println("readN(io.Reader, 5) applied to three DIFFERENT concrete types:")
	for _, s := range srcs {
		got, _ := readN(s.r, 5)
		fmt.Printf("    %-20s concrete type %-24T -> %q\n", s.kind, s.r, got)
	}

	// *bytes.Buffer implements BOTH Read and Write, so it satisfies io.ReadWriter
	// (which embeds io.Reader + io.Writer) — concrete types commonly satisfy
	// several interfaces at once.
	var rw io.ReadWriter = bytes.NewBufferString("rw")
	fmt.Printf("var rw io.ReadWriter = &bytes.Buffer  -> %%T=%T\n", rw)

	check("strings.NewReader satisfies io.Reader",
		mustRead(readN(strings.NewReader("hello"), 5)) == "hello")
	check("bytes.NewReader satisfies io.Reader",
		mustRead(readN(bytes.NewReader([]byte("world")), 5)) == "world")
	check("*bytes.Buffer satisfies io.ReadWriter (non-nil interface)", rw != nil)
	check("the SAME readN body serves 3 concrete types",
		mustRead(readN(strings.NewReader("AAAAA"), 5)) == "AAAAA" &&
			mustRead(readN(bytes.NewReader([]byte("BBBBB")), 5)) == "BBBBB")
}

// mustRead returns s, panicking on error (keeps the checks above one-line).
func mustRead(s string, err error) string {
	if err != nil {
		panic(err)
	}
	return s
}

func main() {
	fmt.Println("interfaces_basics.go — Phase 2 bundle (Interfaces & Type System).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
