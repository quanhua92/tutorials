//go:build ignore

// arrays_slices.go — Phase 1 bundle #3.
//
// GOAL (one line): show, by printing every value, how Go arrays are fixed value
// types and how a slice is a 3-word header (ptr+len+cap) that shares a backing
// array — and why `append` and aliasing are the expert-payoff traps.
//
// This is the GROUND TRUTH for ARRAYS_SLICES.md. Every number, address, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//     go run arrays_slices.go

package main

import (
	"fmt"
	"slices"
	"strings"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// mutateArray takes [3]int BY VALUE: the caller's array is copied, so mutating
// the parameter cannot affect the caller. This is array value semantics.
func mutateArray(a [3]int) {
	a[0] = 999
}

// mutateSlice takes a slice header BY VALUE: the 3-word header is copied, but
// the copied header still points at the SAME backing array — so writing
// elements through it IS visible to the caller. This is the slice-header alias.
func mutateSlice(s []int) {
	s[0] = 999
}

// sectionA: arrays are fixed-size VALUE types. Assigning or passing copies all N
// elements. len(a) == cap(a) == N, the length baked into the type.
func sectionA() {
	sectionBanner("A — ARRAY VALUE SEMANTICS (fixed size, copied on assign/pass)")

	x := [3]int{1, 2, 3}
	fmt.Printf("x := [3]int{1,2,3}  ->  x=%v  len=%d  cap=%d\n", x, len(x), cap(x))
	check("[3]int: len == cap == 3", len(x) == 3 && cap(x) == 3)

	// The length is part of the TYPE. [...] lets the compiler count it.
	y := [...]int{10, 20, 30}
	fmt.Printf("y := [...]int{10,20,30}  ->  type=[3]int (counted for you)  y=%v\n", y)
	check("[...]int literal has length 3", len(y) == 3)

	// VALUE COPY on assignment: y is an independent array; mutating y never
	// touches x. This is the single most important array fact.
	y[0] = 99
	fmt.Printf("after y[0]=99:  x=%v  y=%v  (x[0] is STILL %d — y was a copy)\n", x, y, x[0])
	check("array assignment copies: x[0] unchanged after mutating y", x[0] == 1)

	// VALUE-COPY on function call: same rule, same outcome.
	z := [3]int{7, 8, 9}
	mutateArray(z) // receives a COPY of z; the copy is mutated, then discarded
	fmt.Printf("after mutateArray(z):  z=%v  (unchanged — the copy was mutated)\n", z)
	check("array passed to func is copied: z unchanged", z == [3]int{7, 8, 9})
}

// sectionB: a slice []T is a HEADER {ptr, len, cap} over a backing array.
// Passing/assigning a slice copies the 3-word header (cheap) but shares the
// backing array — so the callee CAN mutate elements.
func sectionB() {
	sectionBanner("B — SLICE HEADER (ptr+len+cap; copies share the backing array)")

	s := make([]int, 3, 5)
	fmt.Printf("s := make([]int, 3, 5)  ->  s=%v  len=%d  cap=%d\n", s, len(s), cap(s))
	check("make([]int,3,5): len=3 cap=5", len(s) == 3 && cap(s) == 5)

	// The header is a value too. Assigning it copies 3 words (ptr,len,cap) —
	// NOT the backing array. Both names now describe the SAME memory.
	h := s
	fmt.Printf("h := s  ->  &h[0]==&s[0]? %v  (same backing; only the 3-word header was copied)\n", &h[0] == &s[0])
	check("header copy shares the backing array: &h[0] == &s[0]", &h[0] == &s[0])

	// Mutate through the callee's header copy -> caller sees it (alias!).
	t := []int{1, 2, 3}
	mutateSlice(t)
	fmt.Printf("t := []int{1,2,3}; mutateSlice(t)  ->  t=%v  (callee wrote through shared backing)\n", t)
	check("slice header copy shares backing: t[0] mutated by callee", t[0] == 999)

	// nil slice: zero value of []T. len==cap==0; appending to nil works.
	var nilSlice []int
	fmt.Printf("var nilSlice []int  ->  nilSlice==nil? %v  len=%d cap=%d\n", nilSlice == nil, len(nilSlice), cap(nilSlice))
	nilSlice = append(nilSlice, 42)
	fmt.Printf("after append(nilSlice, 42)  ->  nilSlice=%v  (append allocates the first backing array)\n", nilSlice)
	check("nil slice has len 0 and is appendable", len(nilSlice) == 1 && nilSlice[0] == 42)
}

// sectionC: append grows the slice. While len<cap it writes in place (no alloc);
// when len==cap it allocates a NEW larger backing array, copies, returns a NEW
// header. The returned slice may point at different memory than the input.
func sectionC() {
	sectionBanner("C — APPEND & GROWTH (in-place vs realloc; cap doubles for small slices)")

	// Pin the address of element 0 BEFORE and AFTER a realloc to prove the
	// backing array changed. &s[0] is the start of the backing array.
	s := make([]int, 0, 3)
	fmt.Printf("s := make([]int, 0, 3)  ->  len=%d cap=%d  &s[0] would be invalid (len=0)\n", len(s), cap(s))

	s = append(s, 1, 2, 3) // fill exactly to capacity — same backing, no realloc
	addrBefore := &s[0]    // capture pointer BEFORE the realloc (raw hex is non-deterministic;
	// we prove the realloc via pointer EQUALITY, which is stable across runs)
	fmt.Printf("s = append(s,1,2,3)  ->  len=%d cap=%d  &s[0] captured (pre-realloc)\n", len(s), cap(s))

	// Keep a header pointing at the CURRENT backing so we can prove the old
	// array survives the realloc and keeps its values.
	old := s // old copies the header: points at the current backing, len=3 cap=3

	// This append EXCEEDS cap(3) -> realloc. s now points at a NEW array; old
	// still points at the original. The growth factor for small slices is ~2x.
	s = append(s, 4)
	addrAfter := &s[0]
	fmt.Printf("s = append(s,4)      ->  len=%d cap=%d  (cap DOUBLED 3->6)\n", len(s), cap(s))
	fmt.Printf("same &s[0] before/after the append? %v  =>  realloc happened=%v (NEW backing array)\n",
		addrBefore == addrAfter, addrBefore != addrAfter)
	check("append beyond cap reallocates to a new backing (address changed)", addrBefore != addrAfter)
	check("small-slice growth factor ~2x: cap 3 -> 6", cap(s) == 6)
	check("old slice's [0] unchanged after realloc (old array survives)", old[0] == 1)

	// Keep appending to watch the doubling ladder: 6 -> 12 (and so on).
	for i := 5; i <= 12; i++ {
		s = append(s, i)
	}
	fmt.Printf("s after appending through 12  ->  len=%d cap=%d  (6 -> 12 doubling)\n", len(s), cap(s))
	check("next growth doubles 6 -> 12", cap(s) == 12)
}

// sectionD: THE ALIASING TRAP. A subslice shares the backing array, so appending
// into a slice that has spare capacity silently mutates memory visible through
// every other slice over that array. Once append reallocates, the alias breaks.
func sectionD() {
	sectionBanner("D — THE ALIASING TRAP (append into shared cap corrupts the parent)")

	// a has len 4, cap 4 (slice literal => len==cap).
	a := []int{1, 2, 3, 4}
	fmt.Printf("a := []int{1,2,3,4}  ->  a=%v  len=%d cap=%d\n", a, len(a), cap(a))

	// b := a[:2] shares a's backing. b has len 2 but cap 4 (cap = cap(a) - 0),
	// so it has TWO spare slots at indices [2] and [3].
	b := a[:2]
	fmt.Printf("b := a[:2]          ->  b=%v  len=%d cap=%d  (cap 4 = cap-from-start)\n", b, len(b), cap(b))
	check("subslice cap = cap-from-index: cap(b)=4", cap(b) == 4)

	// Append into b's spare cap writes directly into a's backing at index 2.
	// This is the silent corruption: a[2] flips from 3 to 99.
	b = append(b, 99)
	fmt.Printf("b = append(b, 99)   ->  b=%v  len=%d cap=%d\n", b, len(b), cap(b))
	fmt.Printf("                     ->  a=%v  (a[2] became %d — b wrote into SHARED backing!)\n", a, a[2])
	check("ALIASING TRAP: append to b within cap mutated a[2] to 99", a[2] == 99 && a[0] == 1 && a[1] == 2 && a[3] == 4)

	// Now b is at capacity (len=3, cap=4). One more append fits in place and
	// still aliases a's index 3.
	b = append(b, 100)
	fmt.Printf("b = append(b,100)   ->  a=%v  (a[3] became %d — still aliasing)\n", a, a[3])
	check("alias still live at cap boundary: a[3] mutated to 100", a[3] == 100)

	// b is now full (len=4==cap=4). The NEXT append reallocates into a NEW
	// backing array. From here on, b and a are decoupled — a stops changing.
	aBefore := fmt.Sprintf("%v", a)
	b = append(b, 777) // forces realloc; b points to fresh memory
	fmt.Printf("b = append(b,777)   ->  b=%v  (realloc; b decoupled from a)\n", b)
	fmt.Printf("                     ->  a=%v  (UNCHANGED across this realloc: %q)\n", a, aBefore)
	check("after realloc the alias breaks: a unchanged by 777 append", a[3] == 100 && aBefore == fmt.Sprintf("%v", a))
}

// sectionE: copy + the slices package (stdlib, Go 1.21+). copy returns the
// element count; slices.Clone makes an independent backing; slices.Sort /
// slices.Grow / slices.Delete operate in place.
func sectionE() {
	sectionBanner("E — copy & THE slices PACKAGE (Clone, Sort, Grow, Delete)")

	// copy copies min(len(dst), len(src)) elements and returns that count.
	dst := []int{0, 0, 0}
	n := copy(dst, []int{1, 2, 3, 4}) // dst shorter -> only 3 copied
	fmt.Printf("copy([]int{0,0,0}, []int{1,2,3,4}) -> dst=%v  returned=%d\n", dst, n)
	check("copy returns min(len(dst),len(src)) == 3", n == 3 && dst[0] == 1 && dst[2] == 3)

	// slices.Clone: returns a shallow copy with an INDEPENDENT backing array.
	src := []int{1, 2, 3}
	clone := slices.Clone(src)
	clone[0] = 999
	fmt.Printf("clone := slices.Clone(src); clone[0]=999  ->  src=%v  clone=%v  (independent backings)\n", src, clone)
	check("slices.Clone detaches backing: src unaffected", src[0] == 1 && clone[0] == 999)

	// slices.Sort: sorts the slice in place (mutates the backing). Requires
	// cmp.Ordered elements (int is).
	toSort := []int{5, 2, 8, 1, 9}
	slices.Sort(toSort)
	fmt.Printf("slices.Sort([]int{5,2,8,1,9})  ->  %v\n", toSort)
	check("slices.Sort ascending in place", slices.IsSorted(toSort) && toSort[0] == 1 && toSort[4] == 9)

	// slices.Grow: guarantees room for n more appends WITHOUT reallocating, by
	// reallocating once now if needed. Useful to avoid repeated growth in a loop.
	s := make([]int, 0, 1)
	s = slices.Grow(s, 5)
	fmt.Printf("slices.Grow(make([]int,0,1), 5) -> len=%d cap=%d (room for 5 appends without realloc)\n", len(s), cap(s))
	check("slices.Grow reserves capacity >= len+5", cap(s) >= 1+5)

	// slices.Delete: removes s[i:j] in place, returns the shorter slice, and
	// zeroes the tail so dropped elements don't linger (no memory leak).
	d := []string{"a", "b", "c", "d", "e"}
	d = slices.Delete(d, 1, 4) // remove indices 1,2,3 ("b","c","d")
	fmt.Printf("slices.Delete([a b c d e], 1, 4) -> %v\n", d)
	check("slices.Delete removes s[i:j]", len(d) == 2 && d[0] == "a" && d[1] == "e")
}

func main() {
	fmt.Println("arrays_slices.go — Phase 1 bundle #3.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
