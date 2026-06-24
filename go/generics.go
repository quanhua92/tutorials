//go:build ignore

// generics.go — Phase 2 bundle (Generics & Constraints).
//
// GOAL (one line): show, by printing every value, how Go generics work —
// type parameters, type constraints (interfaces with type sets), type
// inference vs explicit instantiation, generic types with methods, the
// `cmp`/`slices`/`maps` stdlib (1.21+), and the generic type aliases (1.24+).
//
// This is the GROUND TRUTH for GENERICS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run generics.go

package main

import (
	"cmp"
	"fmt"
	"maps"
	"slices"
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

// --- generic functions & constraints used across sections -------------------

// Max is a GENERIC FUNCTION. The type parameter list [T cmp.Ordered] declares
// one type parameter T, whose constraint is cmp.Ordered. cmp.Ordered is the set
// of all types supporting <, <=, >, >= (all integers, floats, and strings, plus
// any defined type whose UNDERLYING type is one of those). The body may use the
// relational operators on a, b precisely because the constraint guarantees them.
func Max[T cmp.Ordered](a, b T) T {
	if a > b {
		return a
	}
	return b
}

// Number is a CUSTOM constraint written as an interface with a TYPE SET
// (a union of types joined by |). Unlike an ordinary method interface, it
// carries no methods — it only lists the allowed type arguments. Because there
// is NO tilde (~), a defined type `type MyInt int` would NOT satisfy Number
// even though its underlying type is int (see section B for the ~ contrast).
type Number interface {
	int | int64 | float64
}

// Sum is generic over T with constraint Number. The variadic args xs are all of
// type T, and the zero value `var s T` is obtained for free (every type has one).
func Sum[T Number](xs ...T) T {
	var s T
	for _, x := range xs {
		s += x
	}
	return s
}

// ExactFloat lists the predeclared type float64 with NO tilde. It accepts ONLY
// float64 — NOT a defined type whose underlying type is float64 (e.g. Celsius).
type ExactFloat interface{ float64 }

// UnderlyingFloat uses ~float64: it accepts float64 AND every defined type whose
// UNDERLYING type is float64. The ~ token is what makes constraints compose
// with named subtypes instead of matching only the exact predeclared type.
type UnderlyingFloat interface{ ~float64 }

// Celsius is a DISTINCT defined type (not an alias): its identity is "Celsius",
// its underlying type is float64. Because of ~float64 in UnderlyingFloat, a
// value of type Celsius satisfies UnderlyingFloat (but NOT ExactFloat).
type Celsius float64

// Half works for any type whose underlying type is float64, so Celsius qualifies.
// Constraint type inference deduces T = Celsius from the argument, then checks
// Celsius ∈ ~float64. The division `t / 2` is legal because ~float64 permits it.
func Half[T UnderlyingFloat](t T) T {
	return t / 2
}

// Stack is a GENERIC TYPE: the type parameter T is in scope for every field and
// every method. To use a Stack you must instantiate it: Stack[int], Stack[string].
type Stack[T any] struct {
	data []T
}

// Push uses a POINTER receiver because it mutates s.data. Per the method-set
// rule (see INTERFACES_BASICS), the method set of Stack[T] does not contain
// Push — only *Stack[T] does. The receiver type is *Stack[T], naming T.
func (s *Stack[T]) Push(v T) {
	s.data = append(s.data, v)
}

// Pop returns the top value and whether a value existed. The zero value of T is
// used as the "empty" return — that is why T's constraint is `any` and not, say,
// comparable: any type has a zero value, even if it is not comparable.
func (s *Stack[T]) Pop() (T, bool) {
	var zero T
	n := len(s.data)
	if n == 0 {
		return zero, false
	}
	v := s.data[n-1]
	s.data = s.data[:n-1]
	return v, true
}

// Peek returns the top value without removing it.
func (s *Stack[T]) Peek() (T, bool) {
	var zero T
	n := len(s.data)
	if n == 0 {
		return zero, false
	}
	return s.data[n-1], true
}

// Map applies f to every element of in, returning a new slice of type []U. Two
// independent type parameters (T for input, U for output) let the element type
// change across the mapping (e.g. []string -> []int by parsing).
func Map[T, U any](in []T, f func(T) U) []U {
	out := make([]U, len(in))
	for i, v := range in {
		out[i] = f(v)
	}
	return out
}

// Filter keeps only the elements of in for which keep returns true.
func Filter[T any](in []T, keep func(T) bool) []T {
	out := make([]T, 0, len(in))
	for _, v := range in {
		if keep(v) {
			out = append(out, v)
		}
	}
	return out
}

// Person is a plain struct used to sort a slice of a custom type via cmp.
type Person struct {
	Name string
	Age  int
}

// Vector is a GENERIC TYPE ALIAS (legal since Go 1.24): the `=` makes Vector[T]
// literally the SAME type as []T — not a new defined type. So Vector[int] and
// []int are interchangeable; you can pass one where the other is expected with
// no conversion, and `type Vector[T any] = []T` could NOT have been written in
// Go 1.23 (a type alias could not carry its own type parameters before 1.24).
type Vector[T any] = []T

// sectionA shows a generic function, explicit instantiation vs type inference.
func sectionA() {
	sectionBanner("A — Generic function: Max[T cmp.Ordered] + inference")

	// EXPLICIT instantiation: Max[int] tells the compiler T = int up front.
	explicit := Max[int](3, 5)
	fmt.Printf("Max[int](3, 5)   = %d   (explicit type argument)\n", explicit)

	// INFERRED: the compiler reads the argument types (both untyped int consts
	// here, defaulting to int) and infers T = int. The call is identical to the
	// explicit one — type inference just fills in [int] for you.
	inferred := Max(3, 5)
	fmt.Printf("Max(3, 5)        = %d   (T inferred from args)\n", inferred)

	// The same generic Max works for strings and floats with no code change:
	// cmp.Ordered admits all three, so one body serves many types.
	fmt.Printf("Max(\"apple\", \"banana\") = %q   (T = string)\n", Max("apple", "banana"))
	fmt.Printf("Max(3.14, 2.71)         = %v   (T = float64)\n", Max(3.14, 2.71))

	// Under the hood the compiler does NOT do full per-type monomorphization
	// (which would duplicate Max for int, string, and float64). It groups type
	// arguments by "GC shape" (identical memory layout) and emits one copy per
	// shape, passing a hidden dictionary with the type-specific details. The net
	// effect for the programmer: generics avoid the runtime itable dispatch of
	// regular interfaces (see INTERFACES_BASICS), and most small generic
	// functions inline at the call site just like their non-generic peers.
	fmt.Println("(mechanism: not pure monomorphization, not runtime dispatch —")
	fmt.Println(" GC-shape stenciling + a per-call dictionary; inlinable like a normal func)")

	check("Max[int](3,5) == 5", explicit == 5)
	check("Max(3,5) inferred == 5", inferred == 5)
	check("inferred == explicit (same instantiation)", inferred == explicit)
	check(`Max("apple","banana") == "banana"`, Max("apple", "banana") == "banana")
	check("Max(3.14, 2.71) == 3.14", Max(3.14, 2.71) == 3.14)
}

// sectionB shows constraints as interfaces with type sets, the | union, and the
// ~ (underlying-type) token, contrasted with listing an exact predeclared type.
func sectionB() {
	sectionBanner("B — Constraints: type sets, |, and the ~ (underlying) token")

	// Number is `int | int64 | float64` (no ~). Sum[int] and Sum[float64] both
	// work because int and float64 are elements of the set.
	fmt.Printf("Sum[int](1, 2, 3)      = %d   (T = int, in the Number set)\n", Sum[int](1, 2, 3))
	fmt.Printf("Sum(1.5, 2.5, 3.0)     = %v   (T = float64 inferred)\n", Sum(1.5, 2.5, 3.0))
	fmt.Printf("Sum[int64](10, 20, 30) = %d   (T = int64)\n", Sum[int64](10, 20, 30))

	// A distinct defined type Celsius has underlying type float64. With ~float64
	// it satisfies UnderlyingFloat; with plain float64 it would satisfy only
	// ExactFloat — which is why the ~ matters. Half's body divides by 2, legal
	// because ~float64 permits arithmetic.
	var c Celsius = 100
	hc := Half(c)
	fmt.Printf("Half(Celsius(100))     = %v   (T = Celsius inferred; ~float64 admits it)\n", hc)

	// Type identity: Celsius and float64 are DIFFERENT types even though they
	// share an underlying type. Assigning across needs an explicit conversion.
	var f float64 = float64(c)
	fmt.Printf("float64(Celsius(100))  = %v   (explicit conversion; Celsius != float64)\n", f)
	fmt.Printf("Celsius type name      = %T   (a distinct defined type)\n", c)

	// cmp.Ordered is the canonical ordered constraint — it is itself written
	// with ~ for every supported kind, which is why Max accepts string, int and
	// Celsius(underlying float64) alike. Print its identity for the record.
	var orderedValue Celsius = 7
	_ = Max(orderedValue, Celsius(3)) // compiles: Celsius ∈ ~float64 ⊂ cmp.Ordered
	fmt.Printf("Max(Celsius(7),Celsius(3)) = %v  (cmp.Ordered accepts ~float64)\n", Max(orderedValue, Celsius(3)))

	check("Sum[int](1,2,3) == 6", Sum[int](1, 2, 3) == 6)
	check("Sum(1.5,2.5,3.0) == 7.0", Sum(1.5, 2.5, 3.0) == 7.0)
	check("Sum[int64](10,20,30) == 60", Sum[int64](10, 20, 30) == 60)
	check("Half(Celsius(100)) == Celsius(50)", Half(c) == Celsius(50))
	check("Celsius(100) converted to float64 == 100", float64(c) == 100)
	check("Celsius type name is main.Celsius", fmt.Sprintf("%T", c) == "main.Celsius")
	check("Max(Celsius(7),Celsius(3)) == 7", Max(orderedValue, Celsius(3)) == Celsius(7))
}

// sectionC shows generic TYPES (a Stack struct with methods) and higher-order
// generic helpers (Map / Filter) that change the element type along the way.
func sectionC() {
	sectionBanner("C — Generic types & methods: Stack[T], Map, Filter")

	// Instantiate the generic type Stack[int]. The empty composite literal gives
	// a zero-value stack (data == nil, len 0) — appendable like any nil slice.
	st := &Stack[int]{}
	st.Push(1)
	st.Push(2)
	st.Push(3)
	fmt.Printf("push 1, 2, 3 -> len = %d\n", len(st.data))

	popped, ok := st.Pop()
	top, _ := st.Peek()
	fmt.Printf("Pop()  -> %v, ok=%v   (last in, first out)\n", popped, ok)
	fmt.Printf("Peek() -> %v   (new top after one pop)\n", top)

	// Map changes the element type: []int -> []string. Both T and U are inferred
	// from the argument slice and the function's result type.
	doubled := Map([]int{1, 2, 3}, func(x int) int { return x * 2 })
	asWords := Map([]int{1, 2, 3}, func(x int) string {
		return fmt.Sprintf("n%d", x)
	})
	fmt.Printf("Map([]int{1,2,3}, x*2)      = %v   (T=int, U=int)\n", doubled)
	fmt.Printf("Map([]int{1,2,3}, \"n\"+x)    = %v   (T=int, U=string)\n", asWords)

	// Filter keeps only the elements matching a predicate; T is preserved.
	evens := Filter([]int{1, 2, 3, 4}, func(x int) bool { return x%2 == 0 })
	fmt.Printf("Filter([]int{1,2,3,4}, even) = %v   (T=int)\n", evens)

	check("Pop returns 3 (LIFO)", popped == 3 && ok)
	check("Peek returns 2 after one pop", top == 2)
	check("len is 2 after one pop", len(st.data) == 2)
	check("Map x*2 yields [2 4 6]", fmt.Sprintf("%v", doubled) == "[2 4 6]")
	check("Map to words yields [n1 n2 n3]", fmt.Sprintf("%v", asWords) == "[n1 n2 n3]")
	check("Filter evens yields [2 4]", fmt.Sprintf("%v", evens) == "[2 4]")
}

// sectionD shows the canonical generic collections in the standard library: the
// `slices` and `maps` packages (both added in Go 1.21). These cover the vast
// majority of collection needs — reach for them before writing your own.
func sectionD() {
	sectionBanner("D — stdlib generics: slices.Sort/Contains, maps.Clone/Equal")

	// slices.Sort sorts a slice of any ORDERED element type in place. No custom
	// comparator is needed because int ∈ cmp.Ordered.
	is := []int{3, 1, 2}
	slices.Sort(is)
	fmt.Printf("slices.Sort([]int{3,1,2})   = %v\n", is)

	// slices.SortFunc takes a comparator func(a, b T) int (cmp.Compare-style:
	// negative/zero/positive). cmp.Compare returns exactly that, so composing
	// them sorts a slice of a custom struct by a chosen field.
	people := []Person{
		{"bob", 30},
		{"alice", 25},
		{"carol", 28},
	}
	slices.SortFunc(people, func(a, b Person) int { return cmp.Compare(a.Name, b.Name) })
	fmt.Printf("SortFunc by Name            = %v\n", people)

	// slices.Contains reports membership (linear scan); slices.Index gives the
	// first matching index (-1 if absent). Both are generic over the element.
	fmt.Printf("slices.Contains([1,2,3],2)  = %v\n", slices.Contains(is, 2))
	fmt.Printf("slices.Contains([1,2,3],9)  = %v\n", slices.Contains(is, 9))
	fmt.Printf("slices.Index([1,2,3],2)     = %d\n", slices.Index(is, 2))
	fmt.Printf("slices.Index([1,2,3],9)     = %d\n", slices.Index(is, 9))

	// maps.Clone deep-copies a map's key/value pairs into a new map; maps.Equal
	// compares two maps for deep equality. Iteration order is randomized, so for
	// deterministic output we sort the keys before printing.
	src := map[string]int{"b": 2, "a": 1, "c": 3}
	clone := maps.Clone(src)
	keys := make([]string, 0, len(src))
	for k := range src {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	fmt.Println("map (keys sorted):")
	for _, k := range keys {
		fmt.Printf("  %s -> %d\n", k, src[k])
	}
	fmt.Printf("maps.Clone then Equal       = %v   (deep copy of all entries)\n", maps.Equal(src, clone))

	// Mutating the clone must not affect the source — that is the point of Clone
	// (it is a new map, not a reference to the old backing storage).
	clone["z"] = 99
	fmt.Printf("after clone[\"z\"]=99, Equal  = %v   (independent maps)\n", maps.Equal(src, clone))

	check("slices.Sort([3,1,2]) == [1 2 3]", fmt.Sprintf("%v", is) == "[1 2 3]")
	check("people sorted by Name == alice,bob,carol",
		people[0].Name == "alice" && people[1].Name == "bob" && people[2].Name == "carol")
	check("slices.Contains([1,2,3],2) == true", slices.Contains(is, 2))
	check("slices.Contains([1,2,3],9) == false", !slices.Contains(is, 9))
	check("slices.Index([1,2,3],2) == 1", slices.Index(is, 2) == 1)
	check("slices.Index([1,2,3],9) == -1", slices.Index(is, 9) == -1)
	check("maps.Clone(src) Equal src (before mutation)", maps.Equal(src, maps.Clone(src)))
	check("clone mutation does not affect source", !maps.Equal(src, clone))
}

// sectionE shows the GENERIC TYPE ALIAS (Go 1.24+) and prints the guidance on
// when NOT to reach for generics.
func sectionE() {
	sectionBanner("E — Generic type alias (1.24+) & when NOT to use generics")

	// Vector[T] = []T is a parameterized alias. Because it is an alias (the =),
	// Vector[int] IS []int — same type identity, no conversion needed either way.
	v := Vector[int]{9, 7, 8, 1}
	fmt.Printf("Vector[int]{9,7,8,1}        = %v   (type %T)\n", v, v)

	// Since Vector[int] is literally []int, stdlib generic functions that take
	// []int accept it with no conversion:
	slices.Sort(v)
	fmt.Printf("slices.Sort(v)              = %v   (alias == []int; no conversion)\n", v)

	// The same idea generalizes: a generic alias can name ANY generic type.
	type Pair[A, B any] struct {
		First  A
		Second B
	}
	p := Pair[string, int]{"go", 124}
	fmt.Printf("Pair[string,int]{\"go\",124} = %v   (generic defined type)\n", p)

	// --- when NOT to use generics (guidance, printed for the record) ----------
	fmt.Println()
	fmt.Println("When NOT to use generics:")
	fmt.Println("  * If a plain interface method expresses the contract, use it;")
	fmt.Println("    generics are not a replacement for ordinary interfaces.")
	fmt.Println("  * If the `slices`/`maps` stdlib already does it, call that;")
	fmt.Println("    do not hand-roll a second-rate generic collection.")
	fmt.Println("  * Do not over-generalize: a little copying is cheaper than a")
	fmt.Println("    poor abstraction. Add the type parameter only when two or more")
	fmt.Println("    concrete types genuinely share identical logic.")

	check("Vector[int] sorted == [1 7 8 9]", fmt.Sprintf("%v", v) == "[1 7 8 9]")
	check("Pair{go,124}.First == \"go\"", p.First == "go" && p.Second == 124)
}

func main() {
	fmt.Println("generics.go — Phase 2 bundle (Generics & Constraints).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
