//go:build ignore

// unsafe_cgo.go — Phase 4 bundle.
//
// GOAL (one line): show, by printing every value, how the `unsafe` package
// (Sizeof/Alignof/Offsetof, Pointer reinterpretation, zero-copy String/Slice)
// bypasses Go's type system, and how cgo calls real C code across the Go<->C
// boundary.
//
// This is the GROUND TRUTH for UNSAFE_CGO.md. Every number and worked example
// in the guide is printed by this file. Change it -> re-run -> re-paste. Never
// hand-compute.
//
// The cgo preamble (the C code) MUST sit immediately above `import "C"` with no
// blank line between them, or cgo will not pick it up. This file requires
// CGO_ENABLED=1 (the default when a C compiler is present); `just check
// unsafe_cgo` verifies it compiles and runs.
//
// Run:
//
//	go run unsafe_cgo.go

package main

/*
#include <stdlib.h>
#include <string.h>

// add — a trivial C function, called from Go across the cgo boundary.
int add(int a, int b) { return a + b; }

// c_strlen — wrap strlen so a Go-originated C string's length is measured in C.
size_t c_strlen(const char *s) { return s ? strlen(s) : 0; }
*/
import "C"

import (
	"fmt"
	"math"
	"runtime"
	"strings"
	"unsafe"
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

// Padded is a struct that forces alignment padding between its two fields:
// Flag occupies 1 byte, then 7 bytes of padding so Val (int64) is 8-aligned.
// Go aligns int64 to 8 bytes on EVERY platform (including 32-bit), so the
// offsets below are platform-independent.
type Padded struct {
	Flag bool
	Val  int64
}

// sectionA prints unsafe.Sizeof / Alignof / Offsetof — all COMPILE-TIME
// CONSTANTS describing the byte layout of a type (or a struct field).
func sectionA() {
	sectionBanner("A — unsafe.Sizeof / Alignof / Offsetof (compile-time constants)")

	var sl []int64
	var st string
	var p Padded

	fmt.Println("type                  Sizeof  Alignof   note")
	fmt.Println("--------------------  ------  -------   ----------------------------")
	fmt.Printf("int8                  %4d    %4d\n", unsafe.Sizeof(int8(0)), unsafe.Alignof(int8(0)))
	fmt.Printf("int16                 %4d    %4d\n", unsafe.Sizeof(int16(0)), unsafe.Alignof(int16(0)))
	fmt.Printf("int32                 %4d    %4d\n", unsafe.Sizeof(int32(0)), unsafe.Alignof(int32(0)))
	fmt.Printf("int64                 %4d    %4d\n", unsafe.Sizeof(int64(0)), unsafe.Alignof(int64(0)))
	fmt.Printf("float64               %4d    %4d\n", unsafe.Sizeof(float64(0)), unsafe.Alignof(float64(0)))
	fmt.Printf("bool                  %4d    %4d\n", unsafe.Sizeof(false), unsafe.Alignof(false))
	fmt.Printf("int (machine word)    %4d    %4d   <- platform-dependent (== word size)\n", unsafe.Sizeof(int(0)), unsafe.Alignof(int(0)))
	fmt.Printf("*int64 (any pointer)  %4d    %4d   <- platform-dependent (== word size)\n", unsafe.Sizeof((*int64)(nil)), unsafe.Alignof((*int64)(nil)))
	fmt.Printf("[]int64 (slice hdr)   %4d    %4d   <- ptr+len+cap, NOT the backing array\n", unsafe.Sizeof(sl), unsafe.Alignof(sl))
	fmt.Printf("string (string hdr)   %4d    %4d   <- ptr+len, NOT the bytes\n", unsafe.Sizeof(st), unsafe.Alignof(st))

	fmt.Printf("struct Padded{Flag bool; Val int64}:\n")
	fmt.Printf("  Sizeof(Padded)   = %d   (1 + 7 padding + 8)\n", unsafe.Sizeof(p))
	fmt.Printf("  Alignof(Padded)  = %d   (dominant field: int64)\n", unsafe.Alignof(p))
	fmt.Printf("  Offsetof(Flag)   = %d\n", unsafe.Offsetof(p.Flag))
	fmt.Printf("  Offsetof(Val)    = %d   (Flag + 7 bytes padding)\n", unsafe.Offsetof(p.Val))

	check("Sizeof(int8) == 1", unsafe.Sizeof(int8(0)) == 1)
	check("Sizeof(int16) == 2", unsafe.Sizeof(int16(0)) == 2)
	check("Sizeof(int32) == 4", unsafe.Sizeof(int32(0)) == 4)
	check("Sizeof(int64) == 8", unsafe.Sizeof(int64(0)) == 8)
	check("Sizeof(float64) == 8", unsafe.Sizeof(float64(0)) == 8)
	check("Sizeof(bool) == 1", unsafe.Sizeof(false) == 1)
	check("Alignof(int64) == 8 (every platform)", unsafe.Alignof(int64(0)) == 8)
	check("Sizeof(Padded) == 16 (bool + 7 pad + int64)", unsafe.Sizeof(p) == 16)
	check("Alignof(Padded) == 8", unsafe.Alignof(p) == 8)
	check("Offsetof(Padded.Flag) == 0", unsafe.Offsetof(p.Flag) == 0)
	check("Offsetof(Padded.Val) == 8 (after 7 bytes padding)", unsafe.Offsetof(p.Val) == 8)
	check("Sizeof([]int64) == 3 words (header only, not data)", unsafe.Sizeof(sl) == 3*unsafe.Sizeof((*int64)(nil)))
}

// sectionB demonstrates unsafe.Pointer pattern (1): converting *T1 to *T2 to
// REINTERPRET the same bytes as a different type. This is exactly how
// math.Float64bits is implemented in the standard library.
func sectionB() {
	sectionBanner("B — unsafe.Pointer reinterpretation (pattern 1: *T1 -> *T2)")

	// The textbook bit-pattern trick: read the 8 bytes of a float64 as a uint64.
	// *(*uint64)(unsafe.Pointer(&f)) is the literal implementation of math.Float64bits.
	var f float64 = 1.0
	bits := *(*uint64)(unsafe.Pointer(&f))
	fmt.Printf("f = float64(1.0)\n")
	fmt.Printf("bits := *(*uint64)(unsafe.Pointer(&f)) = %#016x\n", bits)
	fmt.Printf("math.Float64bits(1.0)                 = %#016x   (same bits, computed normally)\n", math.Float64bits(1.0))

	// A second, fully portable reinterpretation: int8(-1) read back as uint8.
	// The bit pattern (0xFF) is identical; only the TYPE interpretation changes.
	var n int8 = -1
	asUint8 := *(*uint8)(unsafe.Pointer(&n))
	fmt.Printf("n = int8(-1)\n")
	fmt.Printf("*(*uint8)(unsafe.Pointer(&n)) = %d (0x%02X)   (two's-complement bits, re-typed)\n", asUint8, asUint8)

	check("float64(1.0) bits == math.Float64bits(1.0)", bits == math.Float64bits(1.0))
	check("float64(1.0) bit pattern == 0x3FF0000000000000 (IEEE-754)", bits == 0x3FF0000000000000)
	check("int8(-1) reinterpreted as uint8 == 255 (0xFF)", asUint8 == 0xFF)
}

// sectionC uses the Go 1.20+ unsafe.String / Slice / StringData functions — the
// recommended zero-copy API that REPLACES the deprecated reflect.StringHeader /
// SliceHeader approach (unsafe.Pointer pattern 6).
func sectionC() {
	sectionBanner("C — unsafe.String / Slice / StringData (zero-copy, Go 1.20+)")

	// Build a []byte that aliases a string's backing bytes WITHOUT copying.
	s := "hello, unsafe"
	b := unsafe.Slice(unsafe.StringData(s), len(s))
	fmt.Printf("s := %q  (len %d)\n", s, len(s))
	fmt.Printf("unsafe.Slice(unsafe.StringData(s), len(s)) -> []byte (len %d, cap %d)  — NO copy\n", len(b), cap(b))
	fmt.Printf("string(b) == s ?  %v\n", string(b) == s)

	// The reverse: build a string that aliases a []byte's data WITHOUT copying.
	raw := []byte{'x', 'y', 'z'}
	str := unsafe.String(&raw[0], len(raw))
	fmt.Printf("raw := []byte{'x','y','z'} -> unsafe.String(&raw[0], len) = %q  — NO copy\n", str)

	check("len(zero-copy []byte) == len(string)", len(b) == len(s))
	check("string(zero-copy slice) == original string", string(b) == s)
	check("unsafe.String from []byte data == \"xyz\"", str == "xyz")
}

// sectionD makes a REAL cgo call: a C `add` and a C `strlen`, compiled by clang
// and invoked from Go. This proves cgo compiles and runs in this environment.
func sectionD() {
	sectionBanner("D — cgo: a real C function call across the Go<->C boundary")

	sum := int(C.add(2, 3))
	fmt.Printf("C.add(2, 3) = %d   (C compiled by clang, called from Go)\n", sum)

	// Passing a Go string to C: C.CString malloc's a NUL-terminated copy in the
	// C heap. The caller MUST free it (C.free) — cgo's pointer rules are checked
	// at runtime (GODEBUG=cgocheck=1 by default).
	greeting := "hello, cgo"
	cstr := C.CString(greeting)
	defer C.free(unsafe.Pointer(cstr))
	clen := int(C.c_strlen(cstr))
	fmt.Printf("C.CString(%q) -> C.c_strlen = %d   (Go string -> C heap -> strlen; len(greeting) = %d)\n",
		greeting, clen, len(greeting))

	check("C.add(2,3) == 5 (real cgo call)", sum == 5)
	check("C.c_strlen(\"hello, cgo\") == 10 (matches len)", clen == len(greeting))
}

// sectionE explains CGO_ENABLED and the per-call cost. Timing ns/op is
// non-deterministic, so instead we use a DETERMINISTIC runtime counter to prove
// a cgo call actually happened, and document the cost qualitatively.
func sectionE() {
	sectionBanner("E — CGO_ENABLED & the cgo cost (documentary + runtime proof)")

	// runtime.NumCgoCall() counts every C call made by the process. It is
	// deterministic across runs (a counter, not a clock).
	before := runtime.NumCgoCall()
	_ = C.add(40, 2)
	after := runtime.NumCgoCall()
	fmt.Printf("runtime.NumCgoCall(): before C.add = %d   after C.add = %d   (delta %d)\n", before, after, after-before)

	fmt.Println("Documentary (NOT timed — ns/op is non-deterministic across runs):")
	fmt.Println("  - This binary is a cgo build: `import \"C\"` compiled against libc via clang.")
	fmt.Println("  - CGO_ENABLED=1 (default) links libc and allows the C calls above;")
	fmt.Println("    CGO_ENABLED=0 yields a pure-Go static binary and EXCLUDES import \"C\".")
	fmt.Println("  - Each C call crosses the goroutine<->OS-thread boundary: tens of ns to")
	fmt.Println("    ~200 ns of overhead plus possible M-thread handoff, and it defeats")
	fmt.Println("    inlining + escape analysis across the boundary. A tight loop of C calls")
	fmt.Println("    can be SLOWER than equivalent pure-Go code; batch C work or prefer Go.")

	check("runtime.NumCgoCall() advanced after one C.add call", after > before)
}

func main() {
	fmt.Println("unsafe_cgo.go — Phase 4 bundle (unsafe.Pointer + cgo).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
