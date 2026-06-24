//go:build ignore

// control_flow_defer.go — Phase 1 bundle (control flow & defer).
//
// GOAL (one line): show, by printing every value, how Go's control-flow
// statements (if, switch, for) and the defer mechanism actually behave.
//
// This is the GROUND TRUTH for CONTROL_FLOW_DEFER.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run control_flow_defer.go

package main

import (
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

// sectionA covers if (no parens, braces mandatory, else-if) and switch (no
// automatic fallthrough; the fallthrough keyword; multi-value cases; a
// condition-less "true" switch; a type-switch preview).
func sectionA() {
	sectionBanner("A — if (no parens, braces mandatory) & switch")

	// if: the condition needs NO parentheses, and braces are MANDATORY — even
	// for a single statement. `if (x) { }` and `if x { s; }` (braceless) are
	// both compile errors.
	x := 7
	if x > 5 {
		fmt.Println("if x > 5  -> taken  (no parens; braces required even for one stmt)")
	}

	// else-if chains read top to bottom; the FIRST true branch wins.
	n := 15
	if n < 0 {
		fmt.Println("sign: negative")
	} else if n == 0 {
		fmt.Println("sign: zero")
	} else {
		fmt.Printf("sign: positive (n=%d)\n", n)
	}

	// --- switch: cases need NOT be constants, and there is NO automatic
	// fallthrough. A matching case runs and then control leaves the switch;
	// a bare `break` inside a case is redundant. ---
	day := "Wed"
	var mood string
	switch day {
	case "Mon":
		mood = "back to work"
	case "Tue", "Wed", "Thu": // multi-value case: comma-separated list
		mood = "midweek"
	case "Fri":
		mood = "almost weekend"
	default:
		mood = "weekend"
	}
	fmt.Printf("switch (multi-value case): day=%s -> %s\n", day, mood)
	check("Wed matched the Tue,Wed,Thu multi-value case", mood == "midweek")

	// --- NO automatic fallthrough: only the matched case runs. ---
	v := 1
	seen := []string{}
	switch v {
	case 1:
		seen = append(seen, "one")
		// no break needed: execution stops here; case 2 does NOT run
	case 2:
		seen = append(seen, "two")
	}
	fmt.Printf("switch (no fallthrough): v=%d -> ran %v  (case 2 did NOT run)\n", v, seen)
	check("switch stopped after case 1 (no automatic fallthrough)", len(seen) == 1 && seen[0] == "one")

	// --- fallthrough FORCES the next case unconditionally (it must be the
	// last statement of a clause; it does NOT re-test the next case). ---
	w := 1
	fell := []string{}
	switch w {
	case 1:
		fell = append(fell, "one")
		fallthrough // jump into case 2 even though w != 2
	case 2:
		fell = append(fell, "two") // runs via fallthrough
	case 3:
		fell = append(fell, "three")
	}
	fmt.Printf("switch (fallthrough): w=%d -> ran %v  (case 2 ran; case 3 did NOT)\n", w, fell)
	check("fallthrough entered case 2 but not case 3", fmt.Sprintf("%v", fell) == "[one two]")

	// --- switch with NO expression switches on `true` (a clean if/else-if). ---
	num := 42
	var bucket string
	switch {
	case num < 10:
		bucket = "small"
	case num < 100:
		bucket = "medium"
	default:
		bucket = "large"
	}
	fmt.Printf("switch with no expr (true-switch): num=%d -> %s\n", num, bucket)
	check("true-switch picked medium", bucket == "medium")

	// --- type switch PREVIEW: switch x := v.(type) binds x to the concrete
	// type in each clause. Full treatment lives in TYPE_ASSERTIONS. ---
	var anyV any = "hello"
	var kind string
	switch anyV.(type) {
	case int:
		kind = "int"
	case string:
		kind = "string"
	default:
		kind = "other"
	}
	fmt.Printf("type switch: anyV=%q -> kind=%s  (see TYPE_ASSERTIONS)\n", anyV, kind)
	check("type switch detected string", kind == "string")
}

// sectionB shows that `for` is Go's ONLY loop keyword and demonstrates all
// four forms (infinite, condition-only, C-style, and range).
func sectionB() {
	sectionBanner("B — for is the ONLY loop (4 forms)")

	// There is no `while` or `do/while`; everything is `for`.

	// (1) Infinite: `for {}` — needs an explicit break to ever exit.
	count := 0
	for {
		count++
		if count >= 3 {
			break
		}
	}
	fmt.Printf("(1) for {}            infinite loop: broke out at count=%d\n", count)
	check("infinite loop ran until break", count == 3)

	// (2) Condition-only: `for cond {}` — Go's "while".
	i := 0
	for i < 3 {
		i++
	}
	fmt.Printf("(2) for cond {}       while-style:   i=%d\n", i)
	check("while-style loop reached 3", i == 3)

	// (3) C-style: `for init; cond; post {}`.
	product := 1
	for j := 1; j <= 4; j++ {
		product *= j
	}
	fmt.Printf("(3) for i;c;p {}      C-style:       4! = %d\n", product)
	check("C-style for computed 4! == 24", product == 24)

	// (4) range over a slice: `for index, value := range slice {}`.
	nums := []int{10, 20, 30}
	var sum, idxSum int
	for idx, val := range nums {
		sum += val
		idxSum += idx
	}
	fmt.Printf("(4) for k,v := range  slice [10 20 30]: sum=%d, index-sum=%d\n", sum, idxSum)
	check("range slice summed values to 60", sum == 60)
	check("range slice summed indices to 3 (0+1+2)", idxSum == 3)

	// range also works over a string: it yields the BYTE OFFSET of each rune
	// and the rune itself (one rune per iteration, not one byte).
	for ri, r := range "Go" { // 'G'=U+0047 at byte 0, 'o'=U+006F at byte 1
		fmt.Printf("    range string \"Go\": byte-offset=%d rune=%q (U+%04X)\n", ri, r, r)
	}
}

// sectionC demonstrates labeled break/continue, the only way to escape an
// OUTER loop from inside a nested one.
func sectionC() {
	sectionBanner("C — Labeled break/continue (escape nested loops)")

	// A bare `break`/`continue` only affects the INNERMOST loop. To control an
	// outer loop, label it (an identifier followed by ':') and name the label.
	grid := [][]int{
		{1, 2, 3},
		{4, 5, 6},
		{7, 8, 9},
	}

	// Find the FIRST even number and stop scanning the entire grid.
	foundRow, foundCol := -1, -1
outer:
	for r := 0; r < len(grid); r++ {
		for c := 0; c < len(grid[r]); c++ {
			if grid[r][c]%2 == 0 {
				foundRow, foundCol = r, c
				break outer // exits BOTH loops; a bare break would exit only the inner
			}
		}
	}
	fmt.Printf("labeled break: first even at grid[%d][%d] = %d\n", foundRow, foundCol, grid[foundRow][foundCol])
	check("labeled break found grid[0][1] == 2", foundRow == 0 && foundCol == 1)

	// continue LABEL: skip to the next iteration of the OUTER loop. Here we
	// keep only the rows whose element-sum is even.
	var evenSumRows []int
rowLoop:
	for r := 0; r < len(grid); r++ {
		sum := 0
		for c := 0; c < len(grid[r]); c++ {
			sum += grid[r][c]
		}
		if sum%2 != 0 {
			continue rowLoop // skip the append; restart the outer loop
		}
		evenSumRows = append(evenSumRows, r)
	}
	fmt.Printf("labeled continue: rows with even element-sum = %v\n", evenSumRows)
	// row sums: 6 (even), 15 (odd), 24 (even) -> [0 2]
	check("labeled continue kept rows 0 and 2", fmt.Sprintf("%v", evenSumRows) == "[0 2]")
}

// lifoDemo returns the deferred-execution order. Three closures append a letter
// each at RUN time; because defers run LIFO, the result is "CBA" — the LAST
// defer registered runs FIRST. (Go blog, defer rule 2.)
func lifoDemo() (order string) {
	defer func() { order += "A" }() // registered 1st -> runs 3rd
	defer func() { order += "B" }() // registered 2nd -> runs 2nd
	defer func() { order += "C" }() // registered 3rd -> runs 1st
	return
}

// closureVsArg pins the central defer subtlety (Go blog, rule 1):
//   - defer f(i):  i is an ARGUMENT, evaluated at DEFER time (snapshot).
//   - defer func(){ ...i... }(): i is a free variable, read at RUN time.
//
// i starts at 1 and is set to 10 before return, so the argument snapshot sees
// 1 while the closure sees 10.
func closureVsArg() (argSeen, closureSeen int) {
	i := 1
	defer func(v int) { argSeen = v }(i) // argument: v <- 1 (snapshotted now)
	defer func() { closureSeen = i }()   // closure: i read at run time -> 10
	i = 10
	return
}

// sectionD demonstrates defer's LIFO ordering and the argument-snapshot rule.
func sectionD() {
	sectionBanner("D — defer: LIFO order + argument snapshot")

	order := lifoDemo()
	fmt.Printf("defer LIFO: registered A,B,C -> ran as %q  (last registered runs first)\n", order)
	check("defer LIFO order is CBA", order == "CBA")

	argSeen, closureSeen := closureVsArg()
	fmt.Println("defer arg vs closure: i starts 1, then set to 10 before return")
	fmt.Printf("    defer f(v int){v}    ARGUMENT  -> saw %d  (evaluated at defer time)\n", argSeen)
	fmt.Printf("    defer func(){ i }    CLOSURE   -> saw %d  (i read at run time)\n", closureSeen)
	check("defer arg snapshot captured 1 (not the later 10)", argSeen == 1)
	check("defer closure read i at run time (10)", closureSeen == 10)
}

// double pins defer rule 3: a deferred function may read AND mutate the
// enclosing function's NAMED return value. r is named, so the deferred closure
// can see and change it before the value is actually returned.
func double() (r int) {
	r = 10
	defer func() { r *= 2 }() // runs after the return sets r, before it is handed back
	return                    // naked return: r is 10, then defer doubles it -> 20
}

// sectionE shows that deferred functions can intercept and rewrite named
// (but NOT unnamed) return values.
func sectionE() {
	sectionBanner("E — defer can MUTATE named return values")

	got := double()
	fmt.Printf("double(): r=10; defer r*=2; return -> %d  (defer ran after return value was set)\n", got)
	check("named return mutated by defer: 10*2 == 20", got == 20)

	// This ONLY works because r is a NAMED result. With an unnamed return the
	// deferred function has no name to bind to. The idiomatic real-world use is
	// error patching: `return err` then `defer func(){ if r := recover(); ... }`
	// or wrapping the named `err`. (See ERRORS + FUNCTIONS_CLOSURES.)
}

// handleItem is the loop body extracted into its own function — the SAFE
// pattern for deferring in a loop. A defer inside handleItem is scoped to
// handleItem, so it runs at the end of EACH iteration, not held until the
// outer caller returns.
func handleItem(counter *int) {
	defer func() { *counter++ }() // fires when handleItem returns, once per call
}

// processAllBad defers INSIDE the loop: the defers pile up and none fires
// until processAllBad returns. midCount snapshots the count BEFORE the pile-up
// unwinds (proving zero fired during the loop); finalCount is the total after.
func processAllBad() (midCount, finalCount int) {
	items := []int{1, 2, 3, 4}
	for range items {
		defer func() { finalCount++ }() // stacks up; none fires until return
	}
	midCount = finalCount // snapshot before the pile-up fires -> 0
	return                // 4 defers fire now -> finalCount == 4
}

// processAllGood wraps the body in handleItem so each defer fires per
// iteration; nothing is left pending at return.
func processAllGood() (midCount, finalCount int) {
	items := []int{1, 2, 3, 4}
	for range items {
		handleItem(&finalCount) // defer fires here, every iteration
	}
	midCount = finalCount // already 4 (all fired during the loop)
	return                // nothing pending -> finalCount stays 4
}

// sectionF exposes THE defer-in-loop trap and its canonical fix.
func sectionF() {
	sectionBanner("F — THE trap: defer in a loop accumulates until return")

	fmt.Println("Deferring inside a loop pushes N calls onto the defer stack; NONE of them")
	fmt.Println("runs until the ENCLOSING function returns. For resources (files, locks,")
	fmt.Println("connections) that is a leak — nothing is released mid-loop.")

	badMid, badFinal := processAllBad()
	goodMid, goodFinal := processAllGood()

	fmt.Printf("  [trap] defers fired DURING loop = %d, at return = %d  (pile-up: all held to the end)\n", badMid, badFinal)
	fmt.Printf("  [safe] defers fired DURING loop = %d, at return = %d  (per-iteration: nothing pending)\n", goodMid, goodFinal)
	check("trap: 0 defers fired during the loop (the pile-up)", badMid == 0 && badFinal == 4)
	check("safe: all 4 defers fired during the loop (per-iteration)", goodMid == 4 && goodFinal == 4)
}

func main() {
	fmt.Println("control_flow_defer.go — control flow (if/switch/for) & defer.")
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
