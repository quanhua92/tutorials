//go:build ignore

// strings_runes_bytes.go — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, that a Go string is an
// IMMUTABLE sequence of BYTES, that `for range` decodes UTF-8 into RUNES, and
// how the rune/byte aliases, byte<->string conversions, and the
// unicode/utf8 + strconv + strings stdlib actually behave.
//
// This is the GROUND TRUTH for STRINGS_RUNES_BYTES.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//     go run strings_runes_bytes.go

package main

import (
	"fmt"
	"strconv"
	"strings"
	"testing"
	"unicode/utf8"
	"unsafe"
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

// sectionA: a Go string is an IMMUTABLE sequence of BYTES (not runes).
// len(s) is the BYTE count; s[i] is a single byte.
func sectionA() {
	sectionBanner("A — a string is a sequence of BYTES (not runes)")

	resume := "résumé" // é = U+00E9 = 2 UTF-8 bytes (0xC3 0xA9), appearing twice
	wave := "👋"        // U+1F44B = 4 UTF-8 bytes (0xF0 0x9F 0x91 0x8B)

	fmt.Printf("s        = %q\n", resume)
	fmt.Printf("len(s)                 = %d   (the BYTE count)\n", len(resume))
	fmt.Printf("utf8.RuneCountInString = %d   (the RUNE count)\n", utf8.RuneCountInString(resume))
	fmt.Printf("raw bytes (hex)        = % x\n", []byte(resume))

	fmt.Println()
	fmt.Printf("s        = %q\n", wave)
	fmt.Printf("len(s)                 = %d   (the BYTE count)\n", len(wave))
	fmt.Printf("utf8.RuneCountInString = %d   (the RUNE count)\n", utf8.RuneCountInString(wave))
	fmt.Printf("raw bytes (hex)        = % x\n", []byte(wave))

	fmt.Println()
	// Indexing a string yields a BYTE (uint8), never a "character".
	fmt.Printf("resume[0] = 0x%02x (decimal %d), type %T — a byte, not a rune\n",
		resume[0], resume[0], resume[0])

	check("len(\"résumé\") == 8 bytes", len(resume) == 8)
	check("utf8.RuneCountInString(\"résumé\") == 6", utf8.RuneCountInString(resume) == 6)
	check("len(\"👋\") == 4 bytes", len(wave) == 4)
	check("utf8.RuneCountInString(\"👋\") == 1", utf8.RuneCountInString(wave) == 1)
	check("resume[0] is the byte 'r' (0x72)", resume[0] == 'r')
}

// sectionB: `for i, r := range s` yields (byte OFFSET, RUNE). This is the ONLY
// construct in Go that hides the byte-vs-rune distinction: it decodes one
// UTF-8 rune per iteration, and i is that rune's starting BYTE position.
func sectionB() {
	sectionBanner("B — range over a string yields (byte offset, rune)")

	for _, label := range []string{"Hi", "résumé"} {
		fmt.Printf("ranging %q:\n", label)
		offsets := make([]int, 0, len(label))
		count := 0
		for i, r := range label {
			fmt.Printf("  byte offset %d -> rune %q (U+%04X, %d UTF-8 bytes)\n",
				i, r, r, utf8.RuneLen(r))
			offsets = append(offsets, i)
			count++
		}
		fmt.Printf("  => %d runes; byte offsets = %v\n", count, offsets)
		check("range rune count == utf8.RuneCountInString",
			count == utf8.RuneCountInString(label))
	}

	// In "résumé" the byte offsets are [0 1 3 4 5 6]: they jump by 2 right after
	// each 2-byte 'é' (offset 1->3 and 5->... end). Pin this exactly.
	got := []int{}
	for i := range "résumé" {
		got = append(got, i)
	}
	check("\"résumé\" range offsets == [0 1 3 4 5 6] (é is 2 bytes wide)",
		len(got) == 6 && got[0] == 0 && got[1] == 1 && got[2] == 3 &&
			got[3] == 4 && got[4] == 5 && got[5] == 6)
}

// sectionC: converting []byte(s) or string(b) always COPIES. A string cannot be
// mutated in place; to "change" one you build a new string.
func sectionC() {
	sectionBanner("C — []byte(s) COPIES; strings are immutable")

	s := "abc"

	// []byte(s) allocates a NEW backing array and copies the bytes into it.
	b := []byte(s)
	strPtr := unsafe.StringData(s) // points at the string's read-only bytes
	bytePtr := unsafe.SliceData(b) // points at the []byte's own backing array
	fmt.Printf("s = %q\n", s)
	fmt.Printf("[]byte(s) = % x\n", b)
	check("[]byte(s) is a distinct allocation (backing pointers differ)",
		strPtr != bytePtr)

	// Because b is an independent copy, mutating it cannot touch the original.
	b[0] = 'X'
	fmt.Printf("after b[0]='X': []byte(s) = %q,  original s = %q\n", b, s)
	check("mutating the []byte copy leaves the string unchanged", s == "abc")

	// string(b) copies back the other way, producing a brand-new string.
	again := string(b)
	fmt.Printf("string(mutated []byte) = %q (a new string)\n", again)
	check("string([]byte) rebuilds the value from the copy", again == "Xbc")

	fmt.Println()
	fmt.Println("  s[0] = 'x'   // COMPILE ERROR: cannot assign to s[0]")
	fmt.Println("               // (strings are immutable). To alter text you")
	fmt.Println("               // convert to []byte, change, and convert back.")
}

// sectionD: rune is an alias for int32; byte is an alias for uint8.
func sectionD() {
	sectionBanner("D — rune = int32, byte = uint8 (they are type aliases)")

	var r rune = '⌘'  // '⌘' is a rune constant == 0x2318
	var i32 int32 = r // compiles ONLY because rune IS int32
	var b byte = 'A'  // a byte literal
	var u8 uint8 = b  // compiles ONLY because byte IS uint8

	fmt.Printf("var r  rune  = '⌘' -> value U+%04X, type %T\n", r, r)
	fmt.Printf("var i32 int32 = r  -> value U+%04X, type %T   (identical type!)\n", i32, i32)
	fmt.Printf("var b  byte  = 'A' -> value %-3d,   type %T\n", b, b)
	fmt.Printf("var u8 uint8 = b   -> value %-3d,   type %T   (identical type!)\n", u8, u8)

	check("rune is assignable to int32 (alias)", r == i32)
	check("byte is assignable to uint8 (alias)", b == u8)
	check("'⌘' rune value == 0x2318", r == 0x2318)
}

// sectionE: stdlib greatest hits — unicode/utf8, strconv, strings, strings.Builder.
func sectionE() {
	sectionBanner("E — stdlib: unicode/utf8 + strconv + strings + Builder")

	// --- unicode/utf8: decode / encode / validate ---
	s := "Go⌘"
	r, size := utf8.DecodeRuneInString(s[2:]) // decode the ⌘ sitting at byte 2
	fmt.Printf("utf8.DecodeRuneInString(\"%s\"[2:]) = rune %q (U+%04X), size = %d bytes\n",
		s, r, r, size)
	fmt.Printf("utf8.RuneLen('⌘')               = %d bytes (its UTF-8 width)\n", utf8.RuneLen('⌘'))
	fmt.Printf("utf8.ValidString(\"%s\")          = %v\n", s, utf8.ValidString(s))

	check("DecodeRuneInString(\"⌘\") == U+2318, size 3", r == '⌘' && size == 3)
	check("RuneLen('⌘') == 3", utf8.RuneLen('⌘') == 3)

	fmt.Println()

	// --- strconv: string <-> number, and Quote (escapes non-printables) ---
	n, err := strconv.Atoi("42")
	f, ferr := strconv.ParseFloat("3.14", 64)
	fmt.Printf("strconv.Atoi(\"42\")          = %d, err = %v\n", n, err)
	fmt.Printf("strconv.Itoa(42)            = %q\n", strconv.Itoa(42))
	fmt.Printf("strconv.ParseFloat(\"3.14\",64)= %v, err = %v\n", f, ferr)
	fmt.Printf("strconv.FormatFloat(3.14,'f',2,64) = %q\n", strconv.FormatFloat(3.14, 'f', 2, 64))
	fmt.Printf("strconv.Quote(\"a\\tb\")       = %s   (escapes the tab)\n", strconv.Quote("a\tb"))

	check("Atoi(\"42\")==42 && Itoa(42)==\"42\"", n == 42 && err == nil && strconv.Itoa(42) == "42")
	check("ParseFloat(\"3.14\") round-trips to 3.14", f == 3.14 && ferr == nil)

	fmt.Println()

	// --- strings: search / split / join / replace ---
	fmt.Printf("strings.Contains(\"foobar\",\"oba\")  = %v\n", strings.Contains("foobar", "oba"))
	fmt.Printf("strings.HasPrefix(\"foobar\",\"foo\") = %v\n", strings.HasPrefix("foobar", "foo"))
	fmt.Printf("strings.Split(\"a,b,c\",\",\")       = %q\n", strings.Split("a,b,c", ","))
	fmt.Printf("strings.Join([a b c],\"-\")         = %q\n", strings.Join([]string{"a", "b", "c"}, "-"))
	fmt.Printf("strings.Replace(\"aaa\",\"a\",\"X\",2)  = %q\n", strings.Replace("aaa", "a", "X", 2))
	fmt.Printf("strings.Index(\"foobar\",\"bar\")     = %d\n", strings.Index("foobar", "bar"))

	check("Replace(\"aaa\",\"a\",\"X\",2)==\"XXa\"", strings.Replace("aaa", "a", "X", 2) == "XXa")
	check("Index(\"foobar\",\"bar\")==3", strings.Index("foobar", "bar") == 3)

	fmt.Println()

	// --- strings.Builder: amortized O(n) concatenation (avoids the O(n^2) of '+=' in a loop) ---
	const pieces = 100
	plusAllocs := testing.AllocsPerRun(10, func() {
		s := ""
		for i := 0; i < pieces; i++ {
			s += "x" // every += allocates a fresh backing array and copies -> O(n^2)
		}
		_ = s
	})
	builderAllocs := testing.AllocsPerRun(10, func() {
		var b strings.Builder // grows an internal []byte by doubling -> amortized O(n)
		for i := 0; i < pieces; i++ {
			b.WriteString("x")
		}
		_ = b.String()
	})
	var bld strings.Builder
	for i := 0; i < pieces; i++ {
		bld.WriteString("x")
	}
	built := bld.String()
	fmt.Printf("concat with '+='   (%d pieces): %.0f allocs/run\n", pieces, plusAllocs)
	fmt.Printf("concat with Builder(%d pieces): %.0f allocs/run\n", pieces, builderAllocs)
	fmt.Printf("Builder result: %q (Len=%d, Cap=%d)\n", built, bld.Len(), bld.Cap())

	check("Builder result holds all 100 pieces", bld.Len() == pieces)
	check("Builder allocates far less than '+=' loop", builderAllocs < plusAllocs)
}

func main() {
	fmt.Println("strings_runes_bytes.go — Phase 1 bundle.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
