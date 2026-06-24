//go:build ignore

// maps.go — Phase 1 bundle (Language Foundations).
//
// GOAL (one line): show, by printing every value, how Go's built-in map type
// behaves — reference semantics, the nil-map read-vs-write asymmetry, the
// comma-ok form, the runtime-randomized iteration order (and the sort-keys rule
// that keeps output deterministic), the NON-recoverable concurrent-write fatal,
// and the 1.21+ maps package.
//
// This is the GROUND TRUTH for MAPS.md. Every number, table, and worked example
// in the guide is printed by this file. Change it -> re-run -> re-paste. Never
// hand-compute.
//
// Run:
//     go run maps.go

package main

import (
	"fmt"
	"maps"
	"slices"
	"strings"
	"sync"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

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

// printSorted prints a map[string]int in key order so output reproduces run-to-run.
func printSorted(m map[string]int) {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	for i, k := range keys {
		if i > 0 {
			fmt.Print(" ")
		}
		fmt.Printf("%s:%d", k, m[k])
	}
	fmt.Println()
}

func sectionA() {
	sectionBanner("A: BASICS — make, literal, comma-ok, delete, len")

	// Map literal. map[K]V is a reference type (a hash table).
	m := map[string]int{"a": 1, "b": 2, "c": 3}
	fmt.Println("literal: m := map[string]int{\"a\":1,\"b\":2,\"c\":3}")
	fmt.Printf("len(m) = %d\n", len(m))
	check("len of 3-entry literal is 3", len(m) == 3)

	// make(map[K]V) allocates an empty, writable map.
	mk := make(map[string]int)
	fmt.Printf("make(map[string]int) -> len %d (empty)\n", len(mk))
	mk["x"] = 42
	fmt.Printf("after mk[\"x\"]=42 -> len(mk) = %d\n", len(mk))
	check("make'd map accepts a write (len 1)", len(mk) == 1)

	// Read present key.
	fmt.Printf("m[\"a\"] = %d\n", m["a"])
	check("m[\"a\"] == 1", m["a"] == 1)

	// comma-ok: an ABSENT key yields the value type's zero value AND ok=false.
	v, ok := m["z"]
	fmt.Printf("v, ok := m[\"z\"] -> v=%d, ok=%t  (absent key => zero value + ok=false)\n", v, ok)
	check("absent key returns zero value 0", v == 0)
	check("absent key returns ok=false", !ok)

	// comma-ok on a present key.
	v2, ok2 := m["a"]
	fmt.Printf("v2, ok2 := m[\"a\"] -> v2=%d, ok2=%t\n", v2, ok2)
	check("present key returns ok=true", ok2 && v2 == 1)

	// Zero-value-on-absent turns a map[T]bool into a set.
	set := map[string]bool{}
	fmt.Printf("set := map[string]bool{}; set[\"never\"] (bool zero value) = %t\n", set["never"])

	// delete: drops an entry; a no-op if the key is absent.
	before := len(m)
	delete(m, "b")
	fmt.Printf("delete(m,\"b\"): len %d -> %d\n", before, len(m))
	check("delete drops exactly one entry", len(m) == before-1)
	delete(m, "nonexistent")
	fmt.Printf("delete(m,\"nonexistent\"): len still %d (no-op when absent)\n", len(m))
	check("delete of an absent key is a no-op", len(m) == before-1)

	// Key-type rule: keys must be comparable (== defined).
	fmt.Println("Key types must be COMPARABLE: bool, numeric, string, pointer,")
	fmt.Println("channel, interface, and struct/array built from those. NOT allowed")
	fmt.Println("(compile error): slice, map, function — they have no defined ==")
}

func sectionB() {
	sectionBanner("B: NIL MAP — read returns zero value, write PANICS")

	// The zero value of a map is nil (it points at no hash table).
	var n map[string]int
	fmt.Println("var n map[string]int  // the zero value")
	fmt.Printf("n == nil: %t\n", n == nil)
	check("an uninitialized map is nil", n == nil)

	// Reading a nil map is SAFE: it behaves like an empty map.
	rv, rok := n["anything"]
	fmt.Printf("read n[\"anything\"] -> %d, %t  (nil map reads like empty)\n", rv, rok)
	check("nil map read returns zero value", rv == 0)
	check("nil map read returns ok=false", !rok)
	fmt.Printf("len(n) = %d\n", len(n))

	// Writing to a nil map PANICS. Unlike the concurrent-map fatal (Section D),
	// THIS panic IS recoverable, so a deferred recover() catches it.
	var panicMsg string
	func() {
		defer func() {
			if r := recover(); r != nil {
				panicMsg = fmt.Sprint(r)
			}
		}()
		n["x"] = 1 // panic: assignment to entry in nil map
	}()
	fmt.Printf("attempted n[\"x\"]=1 -> recovered panic: %q\n", panicMsg)
	check("nil-map write panic message mentions 'nil map'", strings.Contains(panicMsg, "nil map"))
}

func sectionC() {
	sectionBanner("C: ITERATION IS RANDOMIZED — always sort keys before printing")

	m := map[string]int{"a": 1, "b": 2, "c": 3}
	fmt.Println("The Go runtime INTENTIONALLY randomizes map iteration order on")
	fmt.Println("every range, so code must never rely on it. We therefore never print")
	fmt.Println("a raw range (its bytes would differ run-to-run).")

	// Deterministic PROOF that the order varies: record the first key hit by each
	// of many independent range passes, then print the SORTED set of distinct
	// first keys (stable output even though each pass was random).
	const passes = 1000
	first := map[string]int{}
	for i := 0; i < passes; i++ {
		for k := range m {
			first[k]++
			break
		}
	}
	distinct := make([]string, 0, len(first))
	for k := range first {
		distinct = append(distinct, k)
	}
	slices.Sort(distinct)
	fmt.Printf("over %d independent range passes, distinct first-keys (sorted): %v\n", passes, distinct)
	check("iteration order is randomized (saw >1 distinct first key)", len(distinct) > 1)

	// The CORRECT, deterministic way to print a map: extract keys, sort, then range.
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	fmt.Println("sorted-key iteration (the only deterministic pattern):")
	for _, k := range keys {
		fmt.Printf("  %s -> %d\n", k, m[k])
	}
	check("sorted keys are exactly [a b c]", fmt.Sprint(keys) == "[a b c]")
}

func sectionD() {
	sectionBanner("D: CONCURRENCY — concurrent writes are a FATAL, not a recoverable panic")

	// DOCUMENTED, not triggered: a concurrent map write aborts the process.
	fmt.Println("Concurrent map WRITES trigger a runtime FATAL (not a panic):")
	fmt.Println("    fatal error: concurrent map writes")
	fmt.Println("A deferred recover() CANNOT catch it — the runtime calls abort(), so the")
	fmt.Println("entire process exits immediately with no clean output. We therefore do")
	fmt.Println("NOT trigger it here (it would abort this program mid-run). Concurrent")
	fmt.Println("READS, however, are safe. The fixes: guard all write access with")
	fmt.Println("sync.Mutex / sync.RWMutex, or use sync.Map for specific access patterns.")
	fmt.Println("(See the ATOMIC_STATE and SYNC_PRIMITIVES bundles for the full story.)")

	// Safe pattern: mutex-guarded concurrent writes, verified deterministically.
	const workers = 8
	const perWorker = 250
	var mu sync.Mutex
	m := make(map[int]int)
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func(base int) {
			defer wg.Done()
			for i := 0; i < perWorker; i++ {
				key := base*perWorker + i
				mu.Lock()
				m[key] = key * 2
				mu.Unlock()
			}
		}(w)
	}
	wg.Wait()

	total := workers * perWorker
	fmt.Printf("mutex-guarded: %d workers x %d writes -> len(m) = %d (expected %d)\n", workers, perWorker, len(m), total)
	check("mutex-guarded concurrent writes produced the correct count", len(m) == total)

	// Order-independent verification: closed-form sums over all entries.
	sumKeys, sumVals := 0, 0
	for k, v := range m {
		sumKeys += k
		sumVals += v
	}
	expKeySum := (total - 1) * total / 2
	fmt.Printf("sum of all keys = %d (expected %d); sum of all values = %d (expected %d)\n",
		sumKeys, expKeySum, sumVals, 2*expKeySum)
	check("sum of keys matches the closed-form 0..N-1", sumKeys == expKeySum)
	check("every value equals 2*key (sum check)", sumVals == 2*expKeySum)
}

type wrap struct{ s string }

func sectionE() {
	sectionBanner("E: maps PACKAGE (stdlib, 1.21+) — Clone, Copy, Keys, Values, Equal")

	src := map[string]int{"a": 1, "b": 2, "c": 3}

	// Clone: a shallow copy (entries copied by ordinary assignment).
	clone := maps.Clone(src)
	fmt.Printf("maps.Clone(src) -> len %d\n", len(clone))
	check("Clone is content-equal to the original (maps.Equal)", maps.Equal(src, clone))
	clone["a"] = 999
	fmt.Printf("after clone[\"a\"]=999: src[\"a\"]=%d, clone[\"a\"]=%d (independent maps)\n", src["a"], clone["a"])
	check("Clone is independent (mutating it leaves the original untouched)", src["a"] == 1 && clone["a"] == 999)

	// Copy: bulk-insert all of src into dst, overwriting on key collision.
	dst := map[string]int{"a": 0, "z": 26}
	maps.Copy(dst, src)
	fmt.Print("maps.Copy(dst, src): dst (sorted) = ")
	printSorted(dst)
	check("Copy overwrote dst[\"a\"] with src's 1", dst["a"] == 1)
	check("Copy carried every src key and kept dst's extra key", len(dst) == 4 && dst["b"] == 2 && dst["c"] == 3 && dst["z"] == 26)

	// Since Go 1.23, maps.Keys/Values return ITERATORS (iter.Seq), not slices —
	// and the order is unspecified. Materialize + sort for deterministic output.
	keys := slices.Sorted(maps.Keys(src))
	fmt.Printf("slices.Sorted(maps.Keys(src)) = %v\n", keys)
	check("sorted keys from maps.Keys are [a b c]", fmt.Sprint(keys) == "[a b c]")
	vals := slices.Sorted(maps.Values(src))
	fmt.Printf("slices.Sorted(maps.Values(src)) = %v\n", vals)
	check("sorted values from maps.Values are [1 2 3]", fmt.Sprint(vals) == "[1 2 3]")

	// Equal: same key/value pairs regardless of insertion order.
	m1 := map[string]int{"a": 1, "b": 2}
	m2 := map[string]int{"b": 2, "a": 1}
	m3 := map[string]int{"a": 1, "b": 3}
	fmt.Printf("maps.Equal(m1, m2) [same kv pairs] = %t\n", maps.Equal(m1, m2))
	fmt.Printf("maps.Equal(m1, m3) [a value differs] = %t\n", maps.Equal(m1, m3))
	check("Equal is true for identical kv pairs regardless of insertion order", maps.Equal(m1, m2))
	check("Equal is false when any value differs", !maps.Equal(m1, m3))

	// EqualFunc: compare values across two maps of different value types.
	w1 := map[int]wrap{1: {"Go"}}
	w2 := map[int]string{1: "go"}
	eq := maps.EqualFunc(w1, w2, func(a wrap, b string) bool {
		return strings.EqualFold(a.s, b)
	})
	fmt.Printf("maps.EqualFunc (case-insensitive value compare) = %t\n", eq)
	check("EqualFunc compares values with a user-supplied function", eq)
}

func main() {
	fmt.Println("maps.go — Phase 1 bundle (Language Foundations).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
