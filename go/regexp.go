//go:build ignore

// regexp.go — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how Go's `regexp` package
// (an RE2 engine with a LINEAR-time guarantee, NO backtracking) compiles,
// matches, captures, replaces, and — crucially — what it REFUSES to compile
// (backreferences, lookahead) and why compiling ONCE matters.
//
// This is the GROUND TRUTH for REGEXP.md. Every number, table, error message,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// Run:
//
//	go run regexp.go

package main

import (
	"fmt"
	"regexp"
	"strings"
	"testing"
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

// sectionA: MatchString — the quick boolean membership test.
//
// `re.MatchString(s)` returns true iff s contains ANY (leftmost) match of the
// compiled pattern. This is the cheapest question you can ask of a regexp.
func sectionA() {
	sectionBanner("A — MatchString: does it match anywhere?")

	// re.MatchString: the compiled-regexp method (preferred — compiled ONCE).
	digits := regexp.MustCompile(`\d+`)
	fmt.Printf("re = MustCompile(`\\d+`)\n")
	fmt.Printf(`re.MatchString("123")   = %v`+"\n", digits.MatchString("123"))
	fmt.Printf(`re.MatchString("abc")   = %v`+"\n", digits.MatchString("abc"))
	fmt.Printf(`re.MatchString("a1b2")  = %v  (match ANYWHERE: "1")`+"\n", digits.MatchString("a1b2"))

	// Two anchored real-world patterns: a phone-like and an email-like shape.
	// `^` and `$` anchor to the start/end, so the WHOLE string must match.
	phone := regexp.MustCompile(`^\d{3}-\d{4}$`)
	email := regexp.MustCompile(`^\w+@\w+\.\w+$`)
	fmt.Printf("\nphone = MustCompile(`^\\d{3}-\\d{4}$`)  (anchored: whole string)\n")
	fmt.Printf(`phone.MatchString("555-1234") = %v`+"\n", phone.MatchString("555-1234"))
	fmt.Printf(`phone.MatchString("555-123")  = %v  (too few digits)`+"\n", phone.MatchString("555-123"))
	fmt.Printf(`phone.MatchString("x555-1234")= %v  (not anchored at start)`+"\n", phone.MatchString("x555-1234"))
	fmt.Printf("\nemail = MustCompile(`^\\w+@\\w+\\.\\w+$`)\n")
	fmt.Printf(`email.MatchString("a@b.cd")   = %v`+"\n", email.MatchString("a@b.cd"))
	fmt.Printf(`email.MatchString("no-at-sign") = %v`+"\n", email.MatchString("no-at-sign"))

	check(`\d+ matches "123"`, digits.MatchString("123"))
	check(`\d+ does NOT match "abc"`, !digits.MatchString("abc"))
	check(`\d+ matches inside "a1b2"`, digits.MatchString("a1b2"))
	check("phone matches 555-1234", phone.MatchString("555-1234"))
	check("phone rejects short 555-123", !phone.MatchString("555-123"))
	check("email matches a@b.cd", email.MatchString("a@b.cd"))
	check("email rejects no-at-sign", !email.MatchString("no-at-sign"))
}

// sectionB: FindString (first/leftmost match) and FindAllString (all matches).
//
// FindString returns "" both for "no match" AND for "matched the empty string";
// use FindStringIndex to distinguish. FindAllString takes n: -1 = unlimited,
// n>=0 = at most n matches; returns nil if there are no matches at all.
func sectionB() {
	sectionBanner("B — FindString / FindAllString")

	digits := regexp.MustCompile(`\d+`)
	src := "a1 b22 c333"

	first := digits.FindString(src)
	all := digits.FindAllString(src, -1) // -1 = unlimited
	two := digits.FindAllString(src, 2)  // at most 2
	none := digits.FindAllString("no digits", -1)

	fmt.Printf("re = MustCompile(`\\d+`);  src = %q\n", src)
	fmt.Printf("re.FindString(src)        = %q   (leftmost match)\n", first)
	fmt.Printf("re.FindAllString(src, -1) = %q   (-1 = all)\n", all)
	fmt.Printf("re.FindAllString(src,  2) = %q   (n = 2 caps it)\n", two)
	fmt.Printf("re.FindAllString(\"no digits\", -1) = %#v   (nil: no matches)\n", none)

	// A word-matching pattern over a sentence (FindAllString keeps input order
	// by spec: matches are "successive non-overlapping", left to right).
	words := regexp.MustCompile(`\w+`)
	sentence := "Go is fast; Go is fun!"
	fmt.Printf("\nwords = MustCompile(`\\w+`);  sentence = %q\n", sentence)
	fmt.Printf("words.FindAllString(sentence, -1) = %q\n", words.FindAllString(sentence, -1))

	check("FindString(src) == \"1\"", first == "1")
	check("FindAllString(src, -1) == [1 22 333]",
		fmt.Sprintf("%q", all) == `["1" "22" "333"]`)
	check("FindAllString(src, 2) == [1 22]",
		fmt.Sprintf("%q", two) == `["1" "22"]`)
	check("FindAllString with no matches is nil", none == nil)
	check("words over sentence == 6 tokens",
		len(words.FindAllString(sentence, -1)) == 6)
}

// sectionC: capture groups via FindStringSubmatch.
//
// Submatch 0 is the ENTIRE match; submatch 1..n are the parenthesized groups,
// numbered left-to-right by OPENING parenthesis. Named groups (?P<name>...)
// occupy the same indices; look them up by name with SubexpIndex.
func sectionC() {
	sectionBanner("C — Capture groups: FindStringSubmatch")

	// Pinned shape: "YYYY-MM".
	ym := regexp.MustCompile(`(\d+)-(\d+)`)
	sub := ym.FindStringSubmatch("release 2024-06 shipped")
	fmt.Printf("re = MustCompile(`(\\d+)-(\\d+)`)\n")
	fmt.Printf(`re.FindStringSubmatch("release 2024-06 shipped") = %q`+"\n", sub)
	fmt.Printf("  sub[0] = %q  (the FULL match)\n", sub[0])
	fmt.Printf("  sub[1] = %q  (group 1: \\d+  -> year)\n", sub[1])
	fmt.Printf("  sub[2] = %q  (group 2: \\d+  -> month)\n", sub[2])
	fmt.Printf("  re.NumSubexp() = %d   (number of parenthesized groups)\n", ym.NumSubexp())

	// The same pattern with NAMED groups. Indices are unchanged; names ride
	// alongside in SubexpNames() (index 0 is always "", the full match has no name).
	named := regexp.MustCompile(`(?P<year>\d+)-(?P<month>\d+)`)
	nsub := named.FindStringSubmatch("2024-06")
	fmt.Printf("\nnamed = MustCompile(`(?P<year>\\d+)-(?P<month>\\d+)`)\n")
	fmt.Printf("named.FindStringSubmatch(\"2024-06\") = %q\n", nsub)
	fmt.Printf("named.SubexpNames()                 = %q   (index 0 is always \"\")\n", named.SubexpNames())
	fmt.Printf("named.SubexpIndex(\"month\")          = %d   (group index of 'month')\n", named.SubexpIndex("month"))

	check("sub[0] (full match) == \"2024-06\"", sub[0] == "2024-06")
	check("sub[1] (year group) == \"2024\"", sub[1] == "2024")
	check("sub[2] (month group) == \"06\"", sub[2] == "06")
	check("NumSubexp() == 2", ym.NumSubexp() == 2)
	check("named month group == \"06\"", nsub[named.SubexpIndex("month")] == "06")
}

// sectionD: ReplaceAllString — substitution with $1/$2 group references.
//
// In the replacement, $name / ${name} / $1 refer to captured groups; $$ is a
// literal $. Use ReplaceAllLiteralString to turn OFF group expansion.
func sectionD() {
	sectionBanner("D — ReplaceAllString & $group references")

	digits := regexp.MustCompile(`\d`)
	redacted := digits.ReplaceAllString("a1b2", "#")
	fmt.Printf("re = MustCompile(`\\d`)\n")
	fmt.Printf(`re.ReplaceAllString("a1b2", "#") = %q`+"\n", redacted)

	// Reorder captured groups: turn "YYYY-MM" into "MM/YYYY" via $2/$1.
	ym := regexp.MustCompile(`(\d+)-(\d+)`)
	reordered := ym.ReplaceAllString("2024-06", "$2/$1")
	fmt.Printf("\nre = MustCompile(`(\\d+)-(\\d+)`)\n")
	fmt.Printf(`re.ReplaceAllString("2024-06", "$2/$1") = %q  (groups reordered)`+"\n", reordered)

	// A subtle gotcha: $10 means group 10, NOT "$1" then "0". Use ${1}0 to be
	// explicit. Here group 1 = "2024", so ${1}0 -> "20240".
	padded := ym.ReplaceAllString("2024-06", "${1}0")
	fmt.Printf(`re.ReplaceAllString("2024-06", "${1}0")  = %q  (explicit ${1} + literal "0")`+"\n", padded)

	// Literal "$" in the output needs "$$".
	price := regexp.MustCompile(`USD`)
	fmt.Printf("\nMustCompile(`USD`).ReplaceAllString(\"USD 5\", \"$$\") = %q  ($$ -> literal $)\n",
		price.ReplaceAllString("USD 5", "$$"))

	check(`ReplaceAllString("a1b2", "#") == "a#b#"`, redacted == "a#b#")
	check(`$2/$1 reorder of "2024-06" == "06/2024"`, reordered == "06/2024")
	check(`${1}0 of "2024-06" == "20240"`, padded == "20240")
	check(`$$ -> literal $`, price.ReplaceAllString("USD 5", "$$") == "$ 5")
}

// sectionE: RE2 limitations — what the linear-time guarantee COSTS you.
//
// Because RE2 matches via NFA simulation in time linear in the input (NO
// backtracking), it CANNOT support features whose semantics require backtracking
// or arbitrary memory: backreferences (\1) and lookahead/lookbehind ((?=)...).
// These are not runtime errors — they are COMPILE errors (regexp.Compile returns
// a non-nil error; regexp.MustCompile PANICS).
func sectionE() {
	sectionBanner("E — RE2 limits: backreferences & lookahead are COMPILE errors")

	type probe struct {
		name string
		pat  string
	}
	probes := []probe{
		{"backreference `(a)\\1`", `(a)\1`}, // RE2 has no \1
		{"lookahead `(?=x)`", `(?=x)`},      // RE2 has no lookahead
		{"lookbehind `(?<=x)y`", `(?<=x)y`}, // RE2 has no lookbehind
	}
	fmt.Println("regexp.Compile on each unsupported pattern (error verbatim):")
	for _, p := range probes {
		_, err := regexp.Compile(p.pat)
		fmt.Printf("  Compile(%-18q) -> err != nil? %-5v  : %v\n", p.pat, err != nil, err)
		check(p.name+" rejected by RE2 (err != nil)", err != nil)
	}

	// MustCompile PANICS on a bad pattern. We recover to observe the panic
	// value without crashing the program — proving MustCompile is panic-on-error,
	// not a returned error. (The panic value is a plain string here.)
	var panicked bool
	var panicVal any
	func() {
		defer func() {
			if r := recover(); r != nil {
				panicked = true
				panicVal = r
			}
		}()
		_ = regexp.MustCompile(`(a)\1`) // would-be backreference: PANIC
	}()
	fmt.Printf("\nMustCompile(`(a)\\1`) panicked? %v  (panic value type: %T)\n", panicked, panicVal)

	check("backreference `(a)\\1` -> Compile error", func() bool {
		_, err := regexp.Compile(`(a)\1`)
		return err != nil
	}())
	check("lookahead `(?=x)` -> Compile error", func() bool {
		_, err := regexp.Compile(`(?=x)`)
		return err != nil
	}())
	check("MustCompile on bad pattern PANICS", panicked)
	// A *Regexp is safe for concurrent use (only Longest is configuration).
	shared := regexp.MustCompile(`\d+`)
	check("concurrent-safe: shared MatchString works", shared.MatchString("x9"))
}

// sectionF: compile ONCE, reuse forever. Recompiling per call is expensive.
//
// regexp.Compile parses + builds the NFA every call; that allocates. A
// package-level *Regexp is built once and reused across calls (and goroutines),
// allocating ZERO per match. We measure with testing.Benchmark and assert the
// ALLOC COUNT (deterministic). We deliberately print and assert allocs/op ONLY:
// bytes/op and ns/op are timing/allocation-amortization dependent and are NOT
// reproducible run-to-run, so they stay out of the captured output.
var sharedDigits = regexp.MustCompile(`\d+`)

func sectionF() {
	sectionBanner("F — Compile once & reuse: allocs/op (deterministic)")

	const input = "a1 b22 c333"

	// Reuse a package-level compiled regexp: zero allocations per match.
	reuse := testing.Benchmark(func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			_ = sharedDigits.FindString(input)
		}
	})
	// Recompile INSIDE the loop: every iteration re-parses the pattern.
	recompile := testing.Benchmark(func(b *testing.B) {
		for i := 0; i < b.N; i++ {
			re, _ := regexp.Compile(`\d+`)
			_ = re.FindString(input)
		}
	})

	fmt.Printf("reuse    (package-level MustCompile): allocs/op = %d\n", reuse.AllocsPerOp())
	fmt.Printf("recompile (Compile inside the loop) : allocs/op = %d\n", recompile.AllocsPerOp())
	fmt.Println("(bytes/op & ns/op intentionally NOT printed: non-deterministic; allocs/op is stable.)")

	check("reuse a package-level regexp: 0 allocs/op", reuse.AllocsPerOp() == 0)
	check("recompile per call: > 0 allocs/op", recompile.AllocsPerOp() > 0)
	check("reuse allocates strictly less than recompile", reuse.AllocsPerOp() < recompile.AllocsPerOp())
}

func main() {
	fmt.Println("regexp.go — Phase 5 bundle.")
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
