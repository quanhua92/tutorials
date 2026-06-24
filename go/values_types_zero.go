//go:build ignore

// values_types_zero.go — Phase 1 bundle #1 (STYLE ANCHOR).
//
// GOAL (one line): show, by printing every value, how Go's type system, zero
// values, variables, and constants behave.
//
// This is the GROUND TRUTH for VALUES_TYPES_ZERO.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run values_types_zero.go

package main

import (
	"fmt"
	"strconv"
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

// Point is a tiny aggregate used to show the zero value of a struct type.
type Point struct {
	N int
	B bool
}

// --- constant blocks used by section D (iota) -------------------------------

// The first spec, `_ = iota`, consumes iota==0. KB then sits at iota==1, so
// `1 << (10*iota)` == 1<<10 == 1024. MB (iota==2) and GB (iota==3) repeat the
// expression and so shift by 20 and 30 bits respectively.
const (
	_  = iota             // iota == 0, discarded
	KB = 1 << (10 * iota) // iota == 1 -> 1<<10
	MB                    // iota == 2 -> 1<<20 (expression repeats)
	GB                    // iota == 3 -> 1<<30
)

// Day is an enum-style type: the first name is given an explicit type (Day) and
// value (iota==0); every following name repeats both, incrementing iota.
type Day int

const (
	Sunday    Day = iota // 0
	Monday               // 1
	Tuesday              // 2
	Wednesday            // 3
	Thursday             // 4
	Friday               // 5
	Saturday             // 6
)

// --- constant blocks used by section C (typed vs untyped) -------------------

// Big is an UNTYPED integer constant. Untyped numeric constants have arbitrary
// precision and never overflow, so 1<<100 is perfectly legal even though it
// dwarfs the int64 range. (Assigning Big directly to an int would be a compile
// error; see sectionC and VALUES_TYPES_ZERO.md.)
const Big = 1 << 100

// SmallUntyped is untyped; its "default type" (used when it lands in a context
// that needs a concrete type with none specified) is int.
const SmallUntyped = 1 << 10

// SmallTyped carries an explicit type, so it is a *typed* int constant.
const SmallTyped int = 1 << 10

// sectionA prints the zero value of one variable of every kind.
func sectionA() {
	sectionBanner("A — Zero value of every type")

	var (
		b   bool
		n   int
		f   float64
		s   string
		p   *int
		fn  func()
		itf any
		sl  []int
		mp  map[string]int
		ch  chan int
		pt  Point
		arr [3]int
	)

	fmt.Println("type        : zero value (human)        zero value (Go-syntax)")
	fmt.Println("------------ ---------------------------------------------------------")
	fmt.Printf("bool        : %v   %#v\n", b, b)
	fmt.Printf("int         : %v   %#v\n", n, n)
	fmt.Printf("float64     : %v   %#v\n", f, f)
	fmt.Printf("string      : %q   %#q\n", s, s)
	fmt.Printf("*int        : %v   %#v\n", p, p)
	fmt.Printf("func()      : %v   %#v\n", any(fn), any(fn))
	fmt.Printf("any         : %v   %#v\n", itf, itf)
	fmt.Printf("[]int       : %v   %#v\n", sl, sl)
	fmt.Printf("map[..]..   : %v   %#v\n", mp, mp)
	fmt.Printf("chan int    : %v   %#v\n", ch, ch)
	fmt.Printf("struct      : %v   %#v\n", pt, pt)
	fmt.Printf("[3]int      : %v   %#v\n", arr, arr)

	check("bool zero is false", b == false)
	check("int zero is 0", n == 0)
	check("float64 zero is 0", f == 0)
	check(`string zero is ""`, s == "")
	check("pointer zero is nil", p == nil)
	check("func zero is nil", fn == nil)
	check("interface zero is nil", itf == nil)
	check("slice zero is nil", sl == nil)
	check("map zero is nil", mp == nil)
	check("chan zero is nil", ch == nil)
	check("struct zero is {0 false}", fmt.Sprintf("%v", pt) == "{0 false}")
	check("array zero is [0 0 0]", fmt.Sprintf("%v", arr) == "[0 0 0]")
}

// sectionB contrasts `var` (zero-initialised) with `:=` (short declaration),
// and shows the "at least one new LHS name" redeclaration rule.
func sectionB() {
	sectionBanner("B — var (zero-init) vs := (short declaration)")

	var x int // declared with a type but no initializer -> the zero value (0).
	fmt.Printf("var x int        -> x = %d  (zero value, not undefined)\n", x)

	y := 42 // := infers the type from the RHS; legal ONLY inside a function.
	fmt.Printf("y := 42          -> y = %d, type = %T\n", y, y)

	// := may REDECLARE names already in the same block, provided at least one
	// name on the left is new. Here y is reused (re-assigned) and z is created.
	y, z := 100, 200
	fmt.Printf("y, z := 100, 200 -> y = %d, z = %d  (:= redeclares y, declares z)\n", y, z)

	// At package scope there is no := — only `var`/`const`/`type` are allowed.
	// (Demonstrated by the package-level declarations above this function.)
	fmt.Println("Note: := is legal only inside a function; package scope uses var.")

	check("var x int is the zero value 0", x == 0)
	check("y was reassigned to 100 by :=", y == 100)
	check("z is a brand-new variable == 200", z == 200)
}

// sectionC demonstrates typed vs untyped constants and arbitrary precision.
func sectionC() {
	sectionBanner("C — Constants: typed vs untyped (arbitrary precision)")

	// Big (1<<100) is fine AS AN UNTYPED constant. We never print Big itself
	// (it would not fit in an int when boxed into an interface for fmt); we do
	// exact arithmetic on it as an untyped constant, THEN convert to int64.
	downshifted := int64(Big >> 99) // 1<<100 >> 99 == 1<<1 == 2
	fmt.Printf("const Big = 1 << 100            (untyped, arbitrary precision)\n")
	fmt.Printf("int64(Big >> 99) = %d            (exact untyped arithmetic, then convert)\n", downshifted)

	// An untyped constant gains a concrete "default type" only when it is used
	// in a context that requires a typed value (e.g. a var decl with no type).
	var fromUntyped = SmallUntyped // default type int
	var fromTyped = SmallTyped     // already typed int
	fmt.Printf("var fromUntyped = SmallUntyped  -> %d, type %T (default type of untyped int)\n", fromUntyped, fromUntyped)
	fmt.Printf("var fromTyped   = SmallTyped    -> %d, type %T (explicit type)\n", fromTyped, fromTyped)

	// bool literals are untyped bool constants; their default type is bool.
	fmt.Printf("const true has default type %T\n", true)

	check("Big>>99 == 2 (untyped constants do not overflow)", downshifted == 2)
	check("untyped int const gets default type int", fmt.Sprintf("%T", fromUntyped) == "int")
	check("typed const SmallTyped is int", fmt.Sprintf("%T", fromTyped) == "int")
}

// sectionD shows iota: a per-ConstSpec counter that resets at each const block.
func sectionD() {
	sectionBanner("D — iota: a counter that increments per ConstSpec")

	fmt.Printf("KB = 1 << (10*1) = %d\n", KB)
	fmt.Printf("MB = 1 << (10*2) = %d\n", MB)
	fmt.Printf("GB = 1 << (10*3) = %d\n", GB)

	fmt.Printf("Day enum: Sun=%d Mon=%d Tue=%d Wed=%d Thu=%d Fri=%d Sat=%d\n",
		Sunday, Monday, Tuesday, Wednesday, Thursday, Friday, Saturday)

	check("KB == 1024", KB == 1024)
	check("MB == 1048576", MB == 1048576)
	check("GB == 1073741824", GB == 1073741824)
	check("Sunday (iota==0) == 0", Sunday == 0)
	check("Saturday (iota==6) == 6", Saturday == 6)
}

// sectionE shows the numeric kinds, the byte/rune aliases, and IEEE-754 limits.
func sectionE() {
	sectionBanner("E — Numeric kinds, aliases & IEEE-754 limits")

	// int/uint are the machine word; strconv.IntSize reports their bit width.
	fmt.Printf("strconv.IntSize = %d   (width of int/uint on this machine)\n", strconv.IntSize)

	// byte and rune are ALIASES (type byte = uint8; type rune = int32), so a
	// variable of type byte reports its underlying name, uint8, under %T.
	var by byte = 200
	var r rune = '世'
	fmt.Printf("var by byte = 200  -> type %T, value %v\n", by, by)
	fmt.Printf("var r rune = '世'  -> type %T, codepoint %d\n", r, r)

	// float64 is IEEE-754 binary64: 0.1 and 0.2 are not exactly representable, so
	// their RUNTIME sum is not exactly 0.3. Note the subtlety: `0.1 + 0.2` written
	// with untyped constant operands is a *constant expression*, computed at
	// arbitrary precision, and DOES equal the constant 0.3. To see the rounding
	// you must force float64 operands (variables), so the add happens at 64 bits.
	const constSum = 0.1 + 0.2 // constant expression: arbitrary precision
	var one, two float64 = 0.1, 0.2
	rtSum := one + two // runtime float64 addition
	fmt.Printf("const (0.1+0.2) == 0.3 ? %v   (constant expression, arbitrary precision)\n", constSum == 0.3)
	fmt.Printf("var   (0.1+0.2) = %v   (literal 0.3 = %v)   equal? %v\n", rtSum, 0.3, rtSum == 0.3)

	check("strconv.IntSize == 64 on this machine", strconv.IntSize == 64)
	check("byte aliases uint8 (same type name)", fmt.Sprintf("%T", by) == "uint8")
	check("rune aliases int32 (same type name)", fmt.Sprintf("%T", r) == "int32")
	check("rune '世' == 19990 (U+4E16)", r == 19990)
	check("constant 0.1+0.2 == 0.3 (arbitrary precision)", constSum == 0.3)
	check("runtime float64 0.1+0.2 != 0.3 (IEEE-754)", rtSum != 0.3)
}

// sectionF shows that bool is its own type: comparisons yield bool, and Go has
// no implicit numeric<->bool conversion (no "truthiness" of non-bools).
func sectionF() {
	sectionBanner("F — Booleans are not numbers (no truthiness)")

	// Relational and equality operators always yield a bool.
	less := 1 < 2
	eq := 3 == 3
	gt := 5 > 9
	fmt.Printf("1 < 2 -> %v   3 == 3 -> %v   5 > 9 -> %v   (all type %T)\n", less, eq, gt, less)

	var b bool = true
	fmt.Printf("var b bool = true -> type %T, value %v\n", b, b)

	// NOTE (documented in the .md; deliberately NOT compiled here): both
	//   if 1 { ... }        // non-bool used as if condition
	//   _ = b + 1           // invalid operation: bool + int
	// are COMPILE ERRORS. Go offers no C/Python-style truthiness: a condition
	// must be a bool, and a bool cannot take part in arithmetic.

	check("1 < 2 yields type bool", fmt.Sprintf("%T", less) == "bool")
	check("3 == 3 is true", eq == true)
	check("5 > 9 is false", gt == false)
	check("true literal has default type bool", fmt.Sprintf("%T", true) == "bool")
}

func main() {
	fmt.Println("values_types_zero.go — Phase 1 bundle #1 (style anchor).")
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
