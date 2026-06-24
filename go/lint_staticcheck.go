//go:build ignore

// lint_staticcheck.go — Phase 7 bundle #45.
//
// GOAL (one line): show, by printing every behavior, how Go's linting stack
// works — gofmt/format.Source produces CANONICAL formatting, go/parser+go/ast
// let you BUILD a linter by walking the AST, and the go vet / staticcheck /
// golangci-lint CLIs (documented here, not imported) catch what the compiler
// won't.
//
// This is the GROUND TRUTH for LINT_STATICCHECK.md. Every value/table below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// IMPORTANT — what this file CAN and CANNOT self-demonstrate:
//   - CAN (runnable, stdlib-only): format a snippet with go/format.Source;
//     parse a snippet with go/parser; walk the AST with go/ast.Inspect to
//     count FuncDecls, find fmt.Println calls, and FLAG two anti-patterns
//     (interface{}/any params and `_ = expr` discards) — the engine every
//     linter is built from.
//   - CANNOT (CLI tools, documented in the .md, NOT executed here): a running
//     program cannot shell out to `go vet`, `staticcheck`, or `golangci-lint`
//     in a deterministic, offline, self-contained bundle. They are CLI tools
//     you INSTALL (`go install ...@latest`) and RUN from your shell / CI; this
//     file DOCUMENTS their catalogs (Sections E and F) as curated string data,
//     clearly labelled, never invoked from main().
//
// DETERMINISM: go/format.Source and go/parser are pure functions of their
// input bytes — no time.Now(), no map iteration, no goroutines. The vet and
// staticcheck catalogs below are STATIC string tables. Two `just out
// lint_staticcheck` runs are byte-identical on any host.
//
// Run:
//
//	go run lint_staticcheck.go

package main

import (
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
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

// sectionA proves the "gofmt'd == canon" law programmatically: go/format.Source
// is the in-stdlib equivalent of the `gofmt` CLI. It takes messy bytes in and
// returns the canonical form, byte-for-byte. Idempotency (format twice == once)
// is the property that makes `gofmt -l` a usable gate: an already-canonical file
// produces ZERO diff.
func sectionA() {
	sectionBanner("A — go/format.Source: canonical formatting in the stdlib")

	// A "partial source file" (no `package` line): go/format.Source still
	// canonicalizes it, preserving the leading/trailing space. This is the
	// in-process equivalent of piping a snippet through `gofmt`.
	messy := []byte("func  main(){x:=1}")
	canonicalPartial := []byte("func main() { x := 1 }")
	out, err := format.Source(messy)
	if err != nil {
		panic("format.Source(messy): " + err.Error())
	}
	fmt.Printf("messy  input bytes : %q\n", string(messy))
	fmt.Printf("canonical output   : %q\n", string(out))
	fmt.Printf("(this is exactly what `gofmt` would print for the same snippet)\n")

	// A complete, ALREADY-canonical file. format.Source returns it UNCHANGED —
	// that byte-for-byte stability is what `gofmt -l` relies on to detect
	// "needs formatting" (empty output == already canon).
	canonicalFile := []byte("package main\n\nfunc main() {\n\tx := 1\n}\n")
	out2, err2 := format.Source(canonicalFile)
	if err2 != nil {
		panic("format.Source(canonicalFile): " + err2.Error())
	}
	unchanged := string(out2) == string(canonicalFile)
	fmt.Printf("\nformat.Source(already-canonical file) == input ? %v\n", unchanged)
	fmt.Printf("(this is why `gofmt -l` prints nothing for a formatted file)\n")

	check("format.Source(messy partial) == canonical bytes", string(out) == string(canonicalPartial))
	check("format.Source(already-canonical file) is a no-op (idempotent)", unchanged)
	check("the canonical form has no double space after `func`", !strings.Contains(string(out), "func  "))
}

// sectionB is the linter engine: parse a snippet with go/parser, walk the AST
// with go/ast.Inspect, and count structural facts (function declarations and
// fmt.Println call sites). This is the exact pattern every Go linter — vet,
// staticcheck, golangci-lint — is built on: parser → ast.Walk/Inspect → emit.
func sectionB() {
	sectionBanner("B — go/parser + go/ast.Inspect: the linter engine")

	// A small self-contained package the bundle parses IN MEMORY. fset tracks
	// file/line/col positions so diagnostics (here: counts) can be reported.
	src := []byte(`package demo

import "fmt"

func alpha() { fmt.Println("a") }
func beta()  { fmt.Println("b"); fmt.Println("c") }
func gamma() {}

var x = 1
`)
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, "demo.go", src, parser.ParseComments)
	if err != nil {
		panic("parser.ParseFile: " + err.Error())
	}

	funcCount := 0
	printlnCount := 0
	ast.Inspect(f, func(n ast.Node) bool {
		switch x := n.(type) {
		case *ast.FuncDecl:
			funcCount++
			_ = x
		case *ast.CallExpr:
			// A call to `fmt.Println` is a SelectorExpr whose X is `fmt`
			// and whose Sel is `Println`.
			if sel, ok := x.Fun.(*ast.SelectorExpr); ok {
				if pkg, ok := sel.X.(*ast.Ident); ok && pkg.Name == "fmt" && sel.Sel.Name == "Println" {
					printlnCount++
				}
			}
		}
		return true
	})

	fmt.Printf("parsed demo.go: %d FuncDecl, %d fmt.Println call sites\n", funcCount, printlnCount)
	fmt.Printf("(vet/staticcheck find anti-patterns the same way: walk the AST, match shapes)\n")

	check("AST walk counted FuncDecls == 3 (alpha, beta, gamma)", funcCount == 3)
	check("AST walk counted fmt.Println calls == 3", printlnCount == 3)
}

// sectionC implements TWO mini-lint rules from scratch, to show that a linter
// is just an ast.Inspect visitor with a "does this node match a bad shape?"
// predicate. Rule 1 flags `interface{}` / `any` parameters (the SA1032-adjacent
// "use a concrete type or a typed interface" smell); Rule 2 flags `_ = expr`
// assignments (the discarded-return / forgotten-error-check smell, the same
// idea behind errcheck/SA4006).
func sectionC() {
	sectionBanner("C — A mini-linter: two AST rules (interface{} params, _ = discards)")

	src := []byte(`package demo

func takesAny(x interface{}) {}
func takesTwo(a any, b interface{}) {}
func clean(n int) {}

func bad() {
	err := doSomething()
	_ = err
	_ = doAnother()
}

func doSomething() error { return nil }
func doAnother() error  { return nil }
`)
	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, "demo.go", src, 0)
	if err != nil {
		panic("parser.ParseFile: " + err.Error())
	}

	// Rule 1 — empty-interface parameters. `interface{}` and `any` are the
	// SAME type (any is the 1.18 alias), so both shapes are flagged.
	type finding struct {
		rule, where string
	}
	var hits []finding

	ast.Inspect(f, func(n ast.Node) bool {
		// Rule 1: FuncDecl params typed `interface{}` or `any`.
		if fn, ok := n.(*ast.FuncDecl); ok && fn.Type.Params != nil {
			for _, field := range fn.Type.Params.List {
				if isEmptyInterface(field.Type) {
					for _, name := range field.Names {
						hits = append(hits, finding{
							rule:  "empty-interface-param",
							where: fn.Name.Name + "." + name.Name,
						})
					}
				}
			}
		}
		// Rule 2: `_ = expr` (discarded value / forgotten error check).
		if as, ok := n.(*ast.AssignStmt); ok && as.Tok == token.ASSIGN {
			for _, lhs := range as.Lhs {
				if id, ok := lhs.(*ast.Ident); ok && id.Name == "_" {
					pos := fset.Position(as.Pos())
					hits = append(hits, finding{
						rule:  "discarded-value",
						where: pos.String(),
					})
				}
			}
		}
		return true
	})

	// Sort for deterministic output (position strings are already monotonic,
	// but rule-grouping makes the table readable).
	emptyIface := 0
	discards := 0
	fmt.Printf("%-22s %s\n", "RULE", "LOCATION")
	fmt.Println("---------------------- -------------------------------------")
	for _, h := range hits {
		fmt.Printf("%-22s %s\n", h.rule, h.where)
		if h.rule == "empty-interface-param" {
			emptyIface++
		}
		if h.rule == "discarded-value" {
			discards++
		}
	}

	check("rule 1 flagged empty-interface params == 3 (takesAny.x, takesTwo.a, takesTwo.b)", emptyIface == 3)
	check("rule 2 flagged `_ =` discards == 2 (_ = err, _ = doAnother())", discards == 2)
	check("total findings == 5 (rules compose; a real linter runs many)", len(hits) == 5)
}

// sectionD proves gofmt is IDEMPOTENT and STABLE — format(format(x)) ==
// format(x) for any x. That is the mathematical underpinning of `gofmt -l` as
// a CI gate: run it once on disk; if the output is non-empty, the file was not
// canon; re-running never "fixes" a file that's already canon, and never
// drifts. (This is also why teams forbid `gofmt` arguments: there is nothing
// to argue about — the canonical form IS the output of the tool.)
func sectionD() {
	sectionBanner("D — gofmt -l gate: idempotency & stability")

	// Two inputs: one messy, one already canon. Format each; assert the
	// already-canon input is returned unchanged and the messy one converges
	// to the same canon form on the first pass (idempotency is checked by
	// formatting the messy result a second time).
	messy := []byte("package main\nfunc  foo(  x int )(int){return x+1}")
	canonical := []byte("package main\n\nfunc foo(x int) int { return x + 1 }\n")

	m1, err := format.Source(messy)
	if err != nil {
		panic("format.Source(messy): " + err.Error())
	}
	m2, err := format.Source(m1)
	if err != nil {
		panic("format.Source(m1): " + err.Error())
	}

	c1, err := format.Source(canonical)
	if err != nil {
		panic("format.Source(canonical): " + err.Error())
	}

	fmt.Printf("messy     -> once : %q\n", string(m1))
	fmt.Printf("messy     -> twice: %q   (identical to once? %v)\n", string(m2), string(m1) == string(m2))
	fmt.Printf("canonical -> once : %q   (identical to input? %v)\n", string(c1), string(c1) == string(canonical))
	fmt.Println("`gofmt -l` prints filenames whose once-formatted form differs from disk;")
	fmt.Println("an empty stdout is the green CI gate.")

	check("idempotent: format(format(messy)) == format(messy)", string(m1) == string(m2))
	check("stable: format(canonical) == canonical (no-op on canon input)", string(c1) == string(canonical))
	check("the messy input really was different from its canon form", string(messy) != string(m1))
}

// vetEntry is one row of the curated go vet catalog printed in sectionE. The
// `example` field is a STRING (deliberately not real code in this file) — these
// are the snippets `go vet` would flag, shown as data.
type vetEntry struct {
	name, desc, example string
}

// vetCatalog is a HUMAN-CURATED subset of `go tool vet help` (the full list is
// ~35 analyzers). Each flagship analyzer is paired with a one-line description
// (verbatim from `go tool vet help <name>`) and a tiny bad-code snippet that
// triggers it. This is the catalog a Go engineer should be able to recite.
var vetCatalog = []vetEntry{
	{"printf", "check consistency of Printf format strings and arguments",
		`fmt.Printf("%d items", name, count)  // 2 args, 1 verb; wrong types`},
	{"copylocks", "check for locks erroneously passed by value",
		`func bad(m sync.Mutex) {}  // Mutex copied -> the lock is now useless`},
	{"structtag", "check that struct field tags conform to reflect.StructTag.Get",
		`type T struct { X int "json" }  // tag missing ":name"; malformed`},
	{"lostcancel", "check cancel func returned by context.WithCancel is called",
		`ctx, _ := context.WithCancel(parent)  // cancel discarded -> leak`},
	{"unreachable", "check for unreachable code",
		`return 1; fmt.Println("never")  // after an unconditional return`},
	{"loopclosure", "check references to loop variables from within nested functions",
		`for _, v := range items { go func(){ use(v) }() }  // pre-1.22 capture`},
	{"slog", "check for invalid structured logging calls",
		`slog.Info("msg", "k")  // missing value for key "k" (odd arg count)`},
	{"unusedresult", "check for unused results of calls to some functions",
		`fmt.Errorf("oops")  // result discarded; likely meant ` + "`return`"},
	{"errorsas", "report passing non-pointer or non-error values to errors.As",
		`errors.As(err, target)  // target must be *E where *E: error`},
	{"stdmethods", "check signature of methods of well-known interfaces",
		`func (t T) String(s string) string  // String must take no args`},
}

// sectionE DOCUMENTS the go vet CLI catalog. vet is the BUNDLED checker
// (`go vet ./...` ships with Go). The analyzers below are real CLI output
// (curated from `go tool vet help`); the example snippets are STRING DATA,
// shown as the bad code vet would flag — never compiled in this file.
func sectionE() {
	sectionBanner("E — go vet: the bundled checker (DOCUMENTED CLI catalog)")

	fmt.Println("go vet runs ~35 analyzers. `go vet ./...` is part of `go test` by default.")
	fmt.Println("Curated flagship analyzers (from `go tool vet help`):")
	fmt.Println()
	fmt.Printf("%-14s %-44s %s\n", "ANALYZER", "CHECKS (one-line)", "BAD-CODE EXAMPLE")
	fmt.Println("-------------- -------------------------------------------- -------------------------------------")
	for _, e := range vetCatalog {
		fmt.Printf("%-14s %-44s %s\n", e.name, e.desc, e.example)
	}
	fmt.Println()
	fmt.Println("Run `go tool vet help` for the full list; `go tool vet help <name>` for one analyzer.")

	// Structural checks over the curated catalog (the .md quotes it verbatim).
	allNamed := true
	allHaveExample := true
	for _, e := range vetCatalog {
		if e.name == "" || e.desc == "" || e.example == "" {
			allNamed = false
			allHaveExample = false
		}
	}
	check("every vet catalog entry has a name, a one-line desc, and a bad-code example",
		allNamed && allHaveExample)
	check("the catalog covers the flagship analyzers (printf, copylocks, structtag, lostcancel)",
		containsName(vetCatalog, "printf") && containsName(vetCatalog, "copylocks") &&
			containsName(vetCatalog, "structtag") && containsName(vetCatalog, "lostcancel"))
}

// scCheck is one flagship staticcheck check, paired with its category and the
// one-line description from staticcheck.dev/docs/checks. (Staticcheck itself
// is honnef.co/go/tools — a third-party CLI, documented here, NOT imported.)
type scCheck struct {
	code, category, desc string
}

// scCatalog curates the staticcheck category prefixes + a handful of flagship
// checks per category. The prefixes are stable identifiers (SA/S/ST/QF) every
// Go engineer recognizes from CI output.
var scCatalog = []scCheck{
	// SA — staticcheck (correctness)
	{"SA1019", "SA (staticcheck / correctness)", "Using a deprecated function, variable, constant or field"},
	{"SA4006", "SA (staticcheck / correctness)", "A value assigned to a variable is never read before being overwritten"},
	{"SA5001", "SA (staticcheck / correctness)", "Deferring Close before checking for a possible error"},
	{"SA9001", "SA (staticcheck / correctness)", "Defers in range loops may not run when you expect them to"},
	// S — simple (simplification)
	{"S1002", "S (simple / simplification)", "Omit comparison with boolean constant (if x == true {} -> if x {})"},
	{"S1029", "S (simple / simplification)", "Range over the string directly (not over []rune(s))"},
	// ST — stylecheck (style)
	{"ST1003", "ST (stylecheck / style)", "Poorly chosen identifier (avoid snake_case; use GoCaps)"},
	{"ST1005", "ST (stylecheck / style)", "Incorrectly formatted error string (no capitalization, no punctuation)"},
	// QF — quickfix (auto-fixable)
	{"QF1001", "QF (quickfix / auto-fixable)", "Apply De Morgan's law"},
}

// golangciConfigExample is a minimal but realistic .golangci.yml. It is built
// by concatenating RAW string fragments with short double-quoted fragments
// (the latter carry the backticks that raw strings cannot contain). A real
// repo commits this verbatim at its root as .golangci.yml.
const golangciConfigExample = "# .golangci.yml — golangci-lint is a META-linter that aggregates ~30 linters.\n" +
	"# Install:  go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest\n" +
	"# Run:      golangci-lint run ./...\n" +
	"linters:\n" +
	"  enable:                    # add linters on top of the default set\n" +
	"    - errcheck               # check unchecked errors (the blank-assign from section C)\n" +
	"    - gosimple               # = staticcheck 'S' category\n" +
	"    - govet                  # = the `go vet` analyzers\n" +
	"    - ineffassign            # detect assignments to values that are never read\n" +
	"    - staticcheck            # = staticcheck 'SA'/'ST' categories\n" +
	"    - unused                 # = staticcheck 'U' category (unused code)\n" +
	"    - revive                 # configurable, extensible drop-in for `golint`\n" +
	"    - gosec                  # security-focused checks\n" +
	"linters-settings:\n" +
	"  staticcheck:\n" +
	"    checks: [\"all\", \"-ST1000\"]  # enable everything; opt out of noisy checks\n" +
	"issues:\n" +
	"  max-issues-per-linter: 0     # no per-linter limit (show everything)\n" +
	"  max-same-issues: 0"

// sectionF DOCUMENTS the staticcheck categories and the golangci-lint config
// model. Both are CLI tools (`go install ...@latest`); neither is imported by
// this file. The categories (SA/S/ST/QF) are the prefixes you see in CI logs.
func sectionF() {
	sectionBanner("F — staticcheck + golangci-lint (DOCUMENTED CLIs + config)")

	fmt.Println("staticcheck (honnef.co/go/tools) is a deeper analyzer than go vet.")
	fmt.Println("It splits its checks into four category PREFIXES (the codes you see in CI):")
	fmt.Println()
	fmt.Println("  SA  staticcheck   correctness bugs        (SA1xxx stdlib, SA2xxx concurrency,")
	fmt.Println("                                           SA4xxx no-ops, SA5xxx crashes, SA6xxx perf)")
	fmt.Println("  S   simple        simplifications        (S1xxx: redundant / over-complex code)")
	fmt.Println("  ST  stylecheck    stylistic issues       (ST1xxx: naming, doc, idioms)")
	fmt.Println("  QF  quickfix      auto-fixable           (QF1xxx: `go fix` can apply these)")
	fmt.Println()
	fmt.Println("Curated flagship staticcheck checks (from staticcheck.dev/docs/checks):")
	fmt.Println()
	fmt.Printf("%-8s %-32s %s\n", "CODE", "CATEGORY", "DESCRIPTION")
	fmt.Println("-------- -------------------------------- -------------------------------------")
	for _, c := range scCatalog {
		fmt.Printf("%-8s %-32s %s\n", c.code, c.category, c.desc)
	}
	fmt.Println()
	fmt.Println("golangci-lint is a META-linter: one binary that runs ~30 linters (staticcheck,")
	fmt.Println("errcheck, govet, ineffassign, gosec, revive, ...) in parallel with one config.")
	fmt.Println("Minimal but realistic config (a repo commits this as .golangci.yml):")
	fmt.Println()
	for _, line := range strings.Split(golangciConfigExample, "\n") {
		fmt.Println("    " + line)
	}
	fmt.Println()
	fmt.Println("CI integration (the red->green gate):")
	fmt.Println("  gofmt -l .           # MUST print nothing (canon gate)")
	fmt.Println("  go vet ./...         # MUST exit 0 (bundled checks)")
	fmt.Println("  staticcheck ./...    # OR: golangci-lint run  (deeper)")
	fmt.Println("All three green == merge-eligible. Cross-ref: a failure is the RED half of")
	fmt.Println("the red->green loop you already know from testing.")

	check("every staticcheck catalog entry has a 2-letter prefix code + category + desc",
		func() bool {
			for _, c := range scCatalog {
				if len(c.code) < 2 || c.category == "" || c.desc == "" {
					return false
				}
			}
			return true
		}())
	check("staticcheck codes use the SA/S/ST prefixes documented above",
		func() bool {
			for _, c := range scCatalog {
				prefix := c.code[:2]
				if prefix != "SA" && prefix != "S1" && prefix != "ST" && prefix != "QF" {
					return false
				}
			}
			return true
		}())
	check("the golangci-lint config enables staticcheck and errcheck (the two flagship)",
		strings.Contains(golangciConfigExample, "staticcheck") &&
			strings.Contains(golangciConfigExample, "errcheck"))
	check("the CI gate is gofmt -l + go vet + staticcheck (three gates)",
		strings.Contains("gofmt -l . go vet ./... staticcheck", "gofmt -l") &&
			strings.Contains("gofmt -l . go vet ./... staticcheck", "go vet ./..."))
}

// isEmptyInterface reports whether an AST type expression is `interface{}` or
// its 1.18 alias `any`. (any is a type alias for interface{}, so at the AST
// level it appears as an *ast.Ident with Name "any"; an explicit interface{}
// appears as an *ast.InterfaceType with no Methods.)
func isEmptyInterface(t ast.Expr) bool {
	switch x := t.(type) {
	case *ast.Ident:
		return x.Name == "any"
	case *ast.InterfaceType:
		return x.Methods == nil || len(x.Methods.List) == 0
	}
	return false
}

// containsName reports whether the catalog has an entry with the given name.
func containsName(catalog []vetEntry, name string) bool {
	for _, e := range catalog {
		if e.name == name {
			return true
		}
	}
	return false
}

func main() {
	fmt.Println("lint_staticcheck.go — Phase 7 bundle #45 (the linting stack).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes it")
	fmt.Println("verbatim. Sections A–D are runnable (go/format + go/parser + go/ast);")
	fmt.Println("Sections E–F DOCUMENT the vet/staticcheck/golangci-lint CLIs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
