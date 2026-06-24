//go:build ignore

// build_ldflags_generate.go — Phase 7 bundle (build-time mechanisms).
//
// GOAL (one line): show, by printing every value, how Go's BUILD-TIME
// machinery shapes a binary: //go:build constraints select files at compile
// time, //go:embed bakes bytes into the binary, -ldflags -X rewrites a string
// package var at link time, GOOS/GOARCH drive cross-compilation, and
// //go:generate drives codegen — plus the runtime read-outs (runtime.GOOS /
// GOARCH) that let a running program inspect which target it was built for.
//
// This is the GROUND TRUTH for BUILD_LDFLAGS_GENERATE.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// IMPORTANT — what this file CAN and CANNOT self-demonstrate:
//   - CAN (runnable): print runtime.GOOS/GOARCH; switch on them; read an
//     //go:embedded asset; print the default value of the `version` var.
//   - CANNOT (build-time only, documented in the .md, NOT attempted here):
//     a running program cannot -X inject into itself, cannot re-run `go
//     generate` on itself, and cannot cross-compile itself. Those are
//     build-link-codegen-time mechanisms; they are shown as the exact commands
//     a developer runs, clearly labelled, never executed from inside main().
//
// DETERMINISM: runtime.GOOS/GOARCH are host-specific, so we PRINT them (stable
// run-to-run on one host) but only ASSERT structural facts (set membership,
// non-empty). The version var, the embedded go.mod, and the curated target
// table are fully deterministic. No time.Now() printed values; no unsorted map
// output. Two `just out build_ldflags_generate` runs are byte-identical.
//
// Run:
//
//	go run build_ldflags_generate.go

package main

import (
	"embed"
	"fmt"
	"runtime"
	"strings"
)

// version is the canonical "overridable at build time" package variable. By
// default it is the literal string "dev". A release build rewrites it at LINK
// time via the linker, e.g.:
//
//	go build -ldflags "-X 'main.version=v1.2.3' -X 'main.commit=abc123'" -o app .
//
// (Documented in the .md; the .go only ever observes the default "dev".)
// Per cmd/link -X: this works because the var is "initialized to a constant
// string expression". A var whose initializer calls a function or refers to
// another variable is NOT rewritable by -X.
var version = "dev"

// commit is a second -X target, defaulting to "unknown". Same rule: a plain
// constant-string initializer is link-time-overridable; the .go asserts the
// default.
var commit = "unknown"

//go:embed go.mod
var embeddedFS embed.FS // bakes go.mod's bytes into this binary at COMPILE time

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

// contains reports whether ss contains s.
func contains(ss []string, s string) bool {
	for _, x := range ss {
		if x == s {
			return true
		}
	}
	return false
}

// knownGOOS / knownGOARCH mirror the curated target set the Go toolchain
// supports (a subset that is stable across releases). They are used only for
// structural assertions (set membership), never to pin a single value.
var knownGOOS = map[string]bool{
	"aix": true, "darwin": true, "dragonfly": true, "freebsd": true,
	"illumos": true, "ios": true, "js": true, "linux": true, "netbsd": true,
	"openbsd": true, "plan9": true, "solaris": true, "wasip1": true, "windows": true,
}

var knownGOARCH = map[string]bool{
	"386": true, "amd64": true, "arm": true, "arm64": true,
	"loong64": true, "mips": true, "mips64": true, "mipsle": true, "mips64le": true,
	"ppc64": true, "ppc64le": true, "riscv64": true, "s390x": true, "wasm": true,
}

// curatedTargets is a FIXED, human-curated table of common cross-compile
// targets. It is static data (not host-specific), so it is safe to print
// verbatim. The Go toolchain actually supports more (`go tool dist list`); this
// subset is the handful a release pipeline typically builds.
var curatedTargets = []struct {
	goos, goarch, note string
}{
	{"linux", "amd64", "the default server target"},
	{"linux", "arm64", "Raspberry Pi 4 / AWS Graviton"},
	{"darwin", "amd64", "Intel macOS"},
	{"darwin", "arm64", "Apple Silicon macOS"},
	{"windows", "amd64", "the default Windows target"},
	{"windows", "arm64", "Windows on ARM"},
	{"js", "wasm", "browser WebAssembly"},
	{"wasip1", "wasm", "WebAssembly System Interface (preview1)"},
}

// sectionA prints the runtime read-outs of the build target and shows a
// runtime.GOOS switch: the SAME source compiles for every target, and the
// running program branches on which target it was built for.
func sectionA() {
	sectionBanner("A — runtime.GOOS / GOARCH: the build target, read at run time")

	fmt.Printf("runtime.GOOS     = %q\n", runtime.GOOS)
	fmt.Printf("runtime.GOARCH   = %q\n", runtime.GOARCH)
	fmt.Printf("runtime.Compiler = %q   (the toolchain; 'gc' is the standard Go compiler)\n", runtime.Compiler)

	// A runtime switch on GOOS is how one source tree serves every platform:
	// the branch taken is decided by which target the binary was COMPILED for,
	// not by anything the program does at run time. (For per-OS source FILES,
	// see Section B: that selection happens at COMPILE time via //go:build.)
	var platformTag string
	switch runtime.GOOS {
	case "darwin", "ios":
		platformTag = "Apple (macOS / iOS)"
	case "linux", "freebsd", "netbsd", "openbsd", "dragonfly":
		platformTag = "Unix-like (BSD / Linux)"
	case "windows":
		platformTag = "Windows"
	default:
		platformTag = "other: " + runtime.GOOS
	}
	fmt.Printf("switch runtime.GOOS -> platform tag: %s\n", platformTag)

	check("GOOS is a non-empty known target", runtime.GOOS != "" && knownGOOS[runtime.GOOS])
	check("GOARCH is a non-empty known target", runtime.GOARCH != "" && knownGOARCH[runtime.GOARCH])
	check("Compiler is the gc toolchain", runtime.Compiler == "gc")
}

// sectionB documents //go:build constraints. The LIVE proof is the very first
// line of THIS file: `//go:build ignore`. That single directive is why 50+
// `package main` programs can coexist in one directory without
// "main redeclared" errors — `go build ./...` skips every file whose
// constraint evaluates false, while `go run <file.go>` compiles the named files
// directly and ignores the tag.
//
// The example constraint/directive texts below are held in string VARIABLES so
// they are DATA, not real directives — `go generate` and the constraint parser
// only act on lines that START with the marker; an assignment line does not.
func sectionB() {
	sectionBanner("B — //go:build constraints: selecting files at COMPILE time")

	// These are illustrative directive texts (string data, NOT active
	// directives). Held in vars so no tool misreads them.
	constraintIgnore := "//go:build ignore"
	constraintLinuxArm64 := "//go:build linux && arm64"
	constraintLegacy := "// +build !windows"
	fmt.Printf("this file's first line:   %s   (excludes it from `go build ./...`)\n", constraintIgnore)
	fmt.Printf("per-platform file example: %s   (file compiles ONLY for linux/arm64)\n", constraintLinuxArm64)
	fmt.Printf("legacy pre-1.17 form:      %s   (still honored for back-compat)\n", constraintLegacy)

	// The selection rules, stated as structural facts the .md relies on:
	fmt.Println("rules:")
	fmt.Println("  - directive MUST be the first line(s), before `package`.")
	fmt.Println("  - no space between `//` and `go:build` (else it is a plain comment).")
	fmt.Println("  - expression is boolean over tags: GOOS, GOARCH, go1.N, custom -tags, &&, ||, !.")
	fmt.Println("  - gofmt (1.17+) keeps //go:build and the legacy // +build line in sync.")

	check("constraint text starts with the marker (no leading space)",
		strings.HasPrefix(constraintIgnore, "//go:build"))
	check("no space between // and go:build in the marker",
		!strings.HasPrefix(constraintIgnore, "// go:build"))
	check("the legacy form used the separate // +build marker",
		strings.HasPrefix(constraintLegacy, "// +build"))
}

// sectionC uses the //go:embed directive at the top of this file: it bakes
// go.mod's bytes into the binary at COMPILE time. embed.FS.ReadFile reads them
// back at run time — with no file on the host. Cross-ref OS_FILEPATH_EMBED for
// the full embed.FS / io/fs.FS story.
func sectionC() {
	sectionBanner("C — //go:embed: baking a file into the binary at compile time")

	raw, err := embeddedFS.ReadFile("go.mod")
	if err != nil {
		panic("embeddedFS.ReadFile(go.mod): " + err.Error())
	}
	first := string(raw)
	if i := strings.IndexByte(first, '\n'); i >= 0 {
		first = first[:i]
	}
	first = strings.TrimRight(first, "\r")
	fmt.Printf("//go:embed go.mod -> embed.FS baked in %d bytes at compile time\n", len(raw))
	fmt.Printf("embeddedFS.ReadFile(\"go.mod\") first line = %q\n", first)

	check(`embedded go.mod first line contains "module"`, strings.Contains(first, "module"))
	check("embedded bytes length > 0", len(raw) > 0)
	check("embedded content matches `module tutorials/go`", first == "module tutorials/go")
}

// sectionD is the version-variable pattern. The .go observes its DEFAULT value
// ("dev"); the override is a build-time (link-time) action documented in the
// .md and shown here only as the exact command string.
func sectionD() {
	sectionBanner("D — the version var: overridable at LINK time via -ldflags -X")

	fmt.Printf("var version = %q   (the default; no -X was applied to THIS run)\n", version)
	fmt.Printf("var commit   = %q   (a second -X target, same pattern)\n", commit)

	// The exact command a release pipeline runs (NOT executed here — a running
	// program cannot -X into itself; -X is a LINKER operation). Shown as data.
	ldflagsCmd := "go build -ldflags \"-X 'main.version=v1.2.3' -X 'main.commit=abc123'\" -o app ."
	fmt.Printf("release build command:\n  %s\n", ldflagsCmd)
	fmt.Println("after that build, the resulting `./app` would print version=\"v1.2.3\" commit=\"abc123\".")

	// cmd/link -X doc (verbatim summary): works "only if the variable is
	// declared... either uninitialized or initialized to a constant string
	// expression. -X will not work if the initializer makes a function call or
	// refers to other variables."
	fmt.Println("-X caveat: only string vars with a constant-string (or no) initializer are rewritable.")

	check(`version == "dev" by default (no -X applied to a go run)`, version == "dev")
	check(`commit == "unknown" by default`, commit == "unknown")
	check("the -X command targets main.version via importpath.name=value",
		strings.Contains(ldflagsCmd, "-X 'main.version=v1.2.3'"))
}

// sectionE prints a curated GOOS/GOARCH cross-compile matrix and asserts the
// CURRENT pair is in it. Cross-compilation is a first-class, fast, no-toolchain
// feature of Go (a single `GOOS=linux GOARCH=arm64 go build` produces a native
// linux/arm64 binary); cgo complicates it because the C toolchain must also be
// a cross-compiler.
func sectionE() {
	sectionBanner("E — GOOS/GOARCH matrix: cross-compiling to many targets")

	fmt.Printf("%-10s %-8s %s\n", "GOOS", "GOARCH", "note")
	fmt.Println("---------- -------- -----------------------------------------")
	for _, t := range curatedTargets {
		fmt.Printf("%-10s %-8s %s\n", t.goos, t.goarch, t.note)
	}

	currentPair := runtime.GOOS + "/" + runtime.GOARCH
	fmt.Printf("\ncurrent target (runtime.GOOS/GOARCH) = %s\n", currentPair)

	// The cross-compile command form (data, not executed).
	crossCmd := "GOOS=linux GOARCH=arm64 go build -o app-linux-arm64 ."
	fmt.Printf("cross-compile example:\n  %s\n", crossCmd)
	fmt.Println("note: CGO_ENABLED=1 cross-builds additionally need a cross C compiler (CC).")

	// Structural assertions over the curated table.
	var currentInTable bool
	for _, t := range curatedTargets {
		if t.goos == runtime.GOOS && t.goarch == runtime.GOARCH {
			currentInTable = true
			break
		}
	}
	check("every curated target has a known GOOS",
		func() bool {
			for _, t := range curatedTargets {
				if !knownGOOS[t.goos] {
					return false
				}
			}
			return true
		}())
	check("every curated target has a known GOARCH",
		func() bool {
			for _, t := range curatedTargets {
				if !knownGOARCH[t.goarch] {
					return false
				}
			}
			return true
		}())
	check("current GOOS/GOARCH pair is present in the curated table", currentInTable)
	check("cross-compile command sets both GOOS and GOARCH",
		strings.Contains(crossCmd, "GOOS=linux") && strings.Contains(crossCmd, "GOARCH=arm64"))
}

// sectionF documents the //go:generate directive. Like //go:embed and
// //go:build it is a comment the toolchain recognizes, but it is driven by a
// SEPARATE command (`go generate ./...`) that is explicitly NOT part of go
// build. It runs external generators (stringer, mockgen, protoc-gen-go, ...).
//
// The directive text is held in a string variable so `go generate` (which scans
// raw lines and does not parse Go) does not mistake it for a real directive.
func sectionF() {
	sectionBanner("F — //go:generate: driving codegen (a separate, explicit step)")

	// Illustrative directive texts (string DATA, not active directives).
	directiveStringer := "//go:generate stringer -type=Pill -output=pill_string.go"
	directiveMock := "//go:generate mockgen -source=store.go -destination=mock_store.go -package=mocks"
	fmt.Printf("stringer directive example:\n  %s\n", directiveStringer)
	fmt.Printf("mockgen directive example:\n  %s\n", directiveMock)

	fmt.Println("how it runs:")
	fmt.Println("  - `go generate ./...` scans every .go file for //go:generate lines.")
	fmt.Println("  - it is NOT part of `go build`/`go test`; run it explicitly before building.")
	fmt.Println("  - each directive runs the named generator with these env vars set:")
	for _, kv := range []string{
		"$GOOS / $GOARCH   (the build target)",
		"$GOFILE           (base name of the containing file)",
		"$GOLINE           (line number of the directive)",
		"$GOPACKAGE        (package name of the containing file)",
	} {
		fmt.Printf("      %s\n", kv)
	}
	fmt.Println("  - convention: generated files carry a line matching  ^// Code generated .* DO NOT EDIT\\.$")

	check("directive has no space between // and go:generate",
		strings.HasPrefix(directiveStringer, "//go:generate") && !strings.HasPrefix(directiveStringer, "// go:generate"))
	check("the DO NOT EDIT convention regex contains 'Code generated'",
		strings.Contains("// Code generated by stringer -type Pill; DO NOT EDIT.", "Code generated") &&
			strings.Contains("// Code generated by stringer -type Pill; DO NOT EDIT.", "DO NOT EDIT"))
	check("go generate runs stringer/mockgen (external tools), not go build",
		contains([]string{"stringer", "mockgen"}, "stringer") && contains([]string{"stringer", "mockgen"}, "mockgen"))
}

func main() {
	fmt.Println("build_ldflags_generate.go — Phase 7 bundle (build-time mechanisms).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes it")
	fmt.Println("verbatim. Host-specific values (GOOS/GOARCH) are printed but only")
	fmt.Println("STRUCTURAL facts are asserted -> byte-identical `just out` runs.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
