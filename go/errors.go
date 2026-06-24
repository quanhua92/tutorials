//go:build ignore

// errors.go — Phase 2 bundle (the `error` type: interface, wrapping, panic/recover).
//
// GOAL (one line): show, by printing every value, how Go's `error` interface,
// sentinel errors, error wrapping (%w), errors.Is/As/Unwrap/Join, and
// panic/recover actually behave.
//
// This is the GROUND TRUTH for ERRORS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run errors.go

package main

import (
	"errors"
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

// --- shared error values used across sections --------------------------------

// ErrNotFound is a SENTINEL error: a package-level singleton compared by
// identity (==) when bare, or reached THROUGH a wrap chain by errors.Is.
// Sentinels carry NO per-call context — they exist to be tested, not inspected.
var ErrNotFound = errors.New("not found")

// NotFoundError is a typed error: a struct that IMPLEMENTS the error interface
// and CARRIES per-call context (the missing Item). Callers extract it with
// errors.As to read the fields. Contrast with ErrNotFound (sentinel) above.
type NotFoundError struct {
	Item string
}

// Error makes NotFoundError satisfy the built-in `error` interface
// (`type error interface { Error() string }`). Value receiver -> a plain
// NotFoundError value is itself an error (no pointer needed).
func (n NotFoundError) Error() string {
	return fmt.Sprintf("not found: %s", n.Item)
}

// sectionA shows that `error` is just a one-method interface, that a custom
// struct type satisfies it implicitly, that the zero value of the interface is
// nil (the foundation of the `if err != nil` idiom), and that errors.New
// returns a DISTINCT value per call (which is why sentinels must be declared
// ONCE and reused, not recreated).
func sectionA() {
	sectionBanner("A — `error` is a built-in one-method interface")

	// The zero value of the `error` interface is nil: a (type=nil, val=nil) pair.
	// The if-err-nil idiom relies on this: a function returning `error` returns
	// nil until a real error is assigned.
	var e error
	fmt.Printf("var e error            -> %v   (zero value: a nil interface)\n", e)
	fmt.Printf("e == nil               -> %v\n", e == nil)

	// Any type with an `Error() string` method satisfies `error` — there is no
	// "implements" keyword and no explicit declaration. Assignment to `error` is
	// what proves satisfaction (interface satisfaction is structural).
	nfe := NotFoundError{Item: "X"}
	var asErr error = nfe // legal BECAUSE NotFoundError has Error() string
	fmt.Printf("nfe := NotFoundError{Item:\"X\"}; var asErr error = nfe\n")
	fmt.Printf("    asErr              -> %v\n", asErr)
	fmt.Printf("    concrete type      -> %T   (the dynamic type behind the interface)\n", asErr)

	// errors.New returns a DISTINCT value per call, even for identical text. Two
	// calls with the same string are NOT == — each is its own *errorString.
	a := errors.New("dup")
	b := errors.New("dup")
	fmt.Printf("errors.New(\"dup\") == errors.New(\"dup\") -> %v   (distinct instances; reuse a sentinel)\n", a == b)

	check("zero value of the error interface is nil", e == nil)
	check("NotFoundError satisfies error (assignable to error)", asErr != nil)
	check(`NotFoundError{X}.Error() == "not found: X"`, nfe.Error() == "not found: X")
	check("two errors.New with same text are distinct (a != b)", a != b)
}

// sectionB shows sentinel errors + errors.Is. We wrap ErrNotFound two layers
// deep with %w. errors.Is walks the Unwrap chain and finds the sentinel; a
// bare == comparison sees only the OUTER error and misses it entirely.
func sectionB() {
	sectionBanner("B — Sentinels & errors.Is (walks the Unwrap chain)")

	inner := fmt.Errorf("db: %w", ErrNotFound) // layer 1 wraps the sentinel
	wrapped := fmt.Errorf("load: %w", inner)   // layer 2 wraps layer 1

	fmt.Println("wrap chain (built bottom-up with %w):")
	fmt.Printf("  ErrNotFound (sentinel) = errors.New(\"not found\")\n")
	fmt.Printf("  inner   = fmt.Errorf(\"db:   %%w\", ErrNotFound)   -> %q\n", inner)
	fmt.Printf("  wrapped = fmt.Errorf(\"load: %%w\", inner)         -> %q\n", wrapped)

	// errors.Is walks: wrapped -> inner -> ErrNotFound (match!).
	fmt.Printf("errors.Is(wrapped, ErrNotFound)        = %v   (walked the chain)\n", errors.Is(wrapped, ErrNotFound))
	// A bare == sees only the OUTER error value; the chain is invisible to ==.
	fmt.Printf("wrapped == ErrNotFound                 = %v   (== sees only the outer error)\n", wrapped == ErrNotFound)

	// errors.Unwrap peels ONE layer at a time (the single-error form).
	fmt.Printf("errors.Unwrap(wrapped)                 = %q   (one step -> inner)\n", errors.Unwrap(wrapped))
	fmt.Printf("errors.Unwrap(errors.Unwrap(wrapped))  = %q   (two steps -> the sentinel)\n", errors.Unwrap(errors.Unwrap(wrapped)))

	check("errors.Is(wrapped, ErrNotFound) is true", errors.Is(wrapped, ErrNotFound))
	check("wrapped == ErrNotFound is false (identity differs)", wrapped != ErrNotFound)
	check("two Unwrap steps reach the sentinel", errors.Unwrap(errors.Unwrap(wrapped)) == ErrNotFound)
}

// sectionC shows errors.As: it walks the chain and, when it finds an error
// whose concrete type is assignable to the target, it COPIES that error into
// *target and returns true. This is how callers read the FIELDS of a typed
// error hidden behind a wrap chain.
func sectionC() {
	sectionBanner("C — errors.As (extract a typed error from the chain)")

	source := NotFoundError{Item: "X"}
	wrapped := fmt.Errorf("lookup: %w", fmt.Errorf("cache: %w", source))

	fmt.Printf("source  = NotFoundError{Item:\"X\"}\n")
	fmt.Printf("wrapped = fmt.Errorf(\"lookup: %%w\", fmt.Errorf(\"cache: %%w\", source)) -> %q\n", wrapped)

	// errors.As needs a POINTER to a variable of the target type. On success it
	// sets *target = the matched error and returns true.
	var target NotFoundError
	ok := errors.As(wrapped, &target)
	fmt.Printf("var target NotFoundError; errors.As(wrapped, &target) -> %v\n", ok)
	fmt.Printf("target.Item = %q   (the field survived the wrap chain)\n", target.Item)

	check("errors.As found NotFoundError in the chain", ok)
	check(`target.Item == "X" (per-call context preserved)`, target.Item == "X")

	// Contrast: errors.As on an error whose chain has NO NotFoundError -> false,
	// and target is LEFT UNTOUCHED (retains its prior value).
	plain := errors.New("something else")
	var miss NotFoundError
	miss.Item = "PRESET" // preset to prove As does not clobber target on failure
	missOK := errors.As(plain, &miss)
	fmt.Printf("errors.As(errors.New(\"something else\"), &miss) -> %v   (target untouched: %q)\n", missOK, miss.Item)

	check("errors.As returns false when the type is absent in the chain", !missOK)
	check("errors.As leaves target untouched on failure (still PRESET)", miss.Item == "PRESET")
}

// sectionD contrasts %w (WRAP — keeps the chain alive for errors.Is/As) with
// %v (FORMAT-ONLY — stringifies the inner error and BREAKS the chain). The two
// produce IDENTICAL Error() text, which is exactly what makes %v a silent bug.
func sectionD() {
	sectionBanner("D — %w (wrap) vs %v (format-only, breaks the chain)")

	withW := fmt.Errorf("open: %w", ErrNotFound)
	withV := fmt.Errorf("open: %v", ErrNotFound)

	fmt.Printf("withW = fmt.Errorf(\"open: %%w\", ErrNotFound) -> %q\n", withW)
	fmt.Printf("withV = fmt.Errorf(\"open: %%v\", ErrNotFound) -> %q   (SAME text!)\n", withV)
	fmt.Println("The Error() strings are identical — the ONLY difference is the Unwrap method:")

	fmt.Printf("errors.Unwrap(withW)        = %q   (%%w produced an Unwrap() error method)\n", errors.Unwrap(withW))
	fmt.Printf("errors.Unwrap(withV)        = %v   (%%v produced NO Unwrap method -> nil)\n", errors.Unwrap(withV))
	fmt.Printf("errors.Is(withW, ErrNotFound) = %v   (chain alive)\n", errors.Is(withW, ErrNotFound))
	fmt.Printf("errors.Is(withV, ErrNotFound) = %v   (chain BROKEN)\n", errors.Is(withV, ErrNotFound))

	check("%w keeps the chain: errors.Is(withW, ErrNotFound) is true", errors.Is(withW, ErrNotFound))
	check("%v breaks the chain: errors.Is(withV, ErrNotFound) is false", !errors.Is(withV, ErrNotFound))
	check("%w gives an Unwrap method (non-nil)", errors.Unwrap(withW) != nil)
	check("%v gives no Unwrap method (nil)", errors.Unwrap(withV) == nil)
}

// sectionE shows errors.Join (Go 1.20+): it bundles multiple errors into one
// whose Unwrap() []error returns the list. errors.Is/As walk EVERY branch; the
// plain errors.Unwrap (single-error form) does NOT unwrap a joined error.
func sectionE() {
	sectionBanner("E — errors.Join (1.20) & multi-Unwrap ([]error)")

	e1 := errors.New("disk full")
	e2 := errors.New("timeout")
	joined := errors.Join(e1, e2)

	fmt.Printf("e1     = errors.New(\"disk full\") -> %q\n", e1)
	fmt.Printf("e2     = errors.New(\"timeout\")    -> %q\n", e2)
	fmt.Printf("joined = errors.Join(e1, e2)\n")
	fmt.Printf("    joined.Error() = %q   (newline-joined messages)\n", joined.Error())

	// Both branches are reachable via errors.Is (depth-first over the []error).
	fmt.Printf("errors.Is(joined, e1) = %v   (branch 1)\n", errors.Is(joined, e1))
	fmt.Printf("errors.Is(joined, e2) = %v   (branch 2)\n", errors.Is(joined, e2))

	// THE EXPERT DETAIL: the single-argument errors.Unwrap only calls the
	// "Unwrap() error" method; a joined error exposes "Unwrap() []error", so the
	// plain Unwrap returns nil. You must type-assert to the multi-Unwrap form to
	// see the branches.
	fmt.Printf("errors.Unwrap(joined)        = %v   (single-Unwrap does NOT see Join)\n", errors.Unwrap(joined))
	multi := joined.(interface{ Unwrap() []error }).Unwrap()
	fmt.Printf("joined.Unwrap() []error       = %q   (the multi-error branch list)\n", multi)

	check("errors.Is(joined, e1) is true (branch 1)", errors.Is(joined, e1))
	check("errors.Is(joined, e2) is true (branch 2)", errors.Is(joined, e2))
	check("plain errors.Unwrap(joined) is nil (Join uses the []error form)", errors.Unwrap(joined) == nil)
	check("joined multi-Unwrap has exactly 2 branches", len(multi) == 2)
}

// deliberatePanic panics with a string; the deferred recover catches it and
// returns the panic value. The function returns NORMALLY despite the panic.
func deliberatePanic() (rec any) {
	defer func() {
		rec = recover()
	}()
	panic("boom: unrecoverable programmer error")
}

// indexOutOfRange triggers a REAL runtime panic (index out of range). The
// recovered value implements `error` (it is a runtime.Error) — runtime panics
// carry an error-typed value, NOT a bare string. recover() only works in the
// deferred function of the panicking goroutine.
func indexOutOfRange() (rec any, isErr bool) {
	defer func() {
		rec = recover()
		_, isErr = rec.(error) // runtime.Error satisfies the error interface
	}()
	s := []int{1, 2, 3}
	_ = s[10] // runtime panic: index out of range [10] with length 3
	return
}

// sectionF shows panic/recover: recover ONLY works in the deferred function of
// the panicking goroutine; runtime panics carry a runtime.Error value; and
// recover() called outside a defer is always nil.
func sectionF() {
	sectionBanner("F — panic & recover (programmer errors, NOT control flow)")

	rec := deliberatePanic()
	fmt.Printf("deliberatePanic: panic(\"boom...\") recovered -> %q   (type %T)\n", rec, rec)
	fmt.Printf("    the function returned NORMALLY despite the panic\n")

	rtRec, rtIsErr := indexOutOfRange()
	fmt.Printf("indexOutOfRange: s[10] on a len-3 slice -> runtime panic recovered:\n")
	fmt.Printf("    value = %v\n", rtRec)
	fmt.Printf("    implements error? %v   (runtime.Error satisfies error)\n", rtIsErr)

	// recover() called OUTSIDE a deferred function returns nil — it is useless
	// except inside the defer of the panicking function (and only that goroutine).
	direct := recover()
	fmt.Printf("recover() called directly (not deferred) = %v   (nil: only works in a defer)\n", direct)

	check("recover caught the string panic value", rec == "boom: unrecoverable programmer error")
	check("runtime panic value implements error (runtime.Error)", rtIsErr)
	check("recover() outside a defer returns nil", direct == nil)
}

func main() {
	fmt.Println("errors.go — the `error` interface, wrapping, Is/As/Unwrap/Join, panic/recover.")
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
