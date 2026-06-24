//go:build ignore

// modules_workspace.go — Phase 7 bundle (CLI, Tooling & Build).
//
// GOAL (one line): show, by simulating the toolchain, how Go modules, Minimal
// Version Selection (MVS), go.sum, the module proxy, vendoring, and workspaces
// actually behave — and how to read the build's module graph at runtime.
//
// This is the GROUND TRUTH for MODULES_WORKSPACE.md. Every version, hash, and
// build list below is computed by this file; the .md guide pastes it verbatim.
// Never hand-compute.
//
// Run:
//
//	go run modules_workspace.go

package main

import (
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"runtime/debug"
	"sort"
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

// --- the Minimal Version Selection (MVS) engine -----------------------------

// req is a single require directive: a dependency path + its minimum version.
type req struct {
	path    string
	version string
}

// modKey identifies one node in the module graph: a (path, version) pair.
type modKey struct {
	path    string
	version string
}

// parseSemver turns "v1.2.3" into [3]int{1,2,3}. Missing components are 0.
func parseSemver(s string) [3]int {
	s = strings.TrimPrefix(s, "v")
	parts := strings.Split(s, ".")
	var v [3]int
	for i := 0; i < 3 && i < len(parts); i++ {
		n, _ := strconv.Atoi(parts[i]) // non-numeric -> 0; fine for our fixed graph
		v[i] = n
	}
	return v
}

// cmpVersion returns -1/0/+1 on the semver (major, minor, patch) tuple.
func cmpVersion(a, b string) int {
	va, vb := parseSemver(a), parseSemver(b)
	for i := 0; i < 3; i++ {
		switch {
		case va[i] < vb[i]:
			return -1
		case va[i] > vb[i]:
			return +1
		}
	}
	return 0
}

// mvs runs a faithful Minimal Version Selection over a module graph.
//
// graph maps each (path, version) node to the require-directives in its go.mod.
// mains is the set of main modules' requirements (the top-level go.mod, plus any
// workspace `use`-ed local modules). The result is the selected (highest)
// version per module path — exactly the build list MVS produces.
//
// Algorithm (matches go.dev/ref/mod): "MVS starts at the main modules ... and
// traverses the graph, tracking the highest required version of each module."
// We keep a worklist; enqueue only when a version strictly rises, so it halts.
func mvs(graph map[modKey][]req, mains []req) map[string]string {
	selected := map[string]string{}
	type task struct{ path, version string }
	var work []task
	enqueue := func(path, version string) {
		cur, ok := selected[path]
		if !ok || cmpVersion(version, cur) > 0 {
			selected[path] = version
			work = append(work, task{path, version})
		}
	}
	for _, r := range mains {
		enqueue(r.path, r.version)
	}
	for len(work) > 0 {
		t := work[0]
		work = work[1:]
		for _, r := range graph[modKey{t.path, t.version}] {
			enqueue(r.path, r.version)
		}
	}
	return selected
}

// printBuildList prints a build list with paths sorted (deterministic output).
func printBuildList(label string, selected map[string]string) {
	paths := make([]string, 0, len(selected))
	for p := range selected {
		paths = append(paths, p)
	}
	sort.Strings(paths)
	fmt.Printf("%s:\n", label)
	for _, p := range paths {
		fmt.Printf("    %-26s %s\n", p, selected[p])
	}
}

// --- Section A: a tiny go.mod parser ----------------------------------------

// goModForParse is a fixed, representative go.mod used to teach the file format.
// The parser below extracts the module path and every require directive from it
// WITHOUT calling the toolchain — mirroring what golang.org/x/mod/modfile does,
// in miniature.
const goModForParse = `module example.com/myapp

go 1.23

require (
	example.com/A v1.0.0
	example.com/B v1.0.0 // direct
	example.com/C v1.2.0 // indirect
)

replace example.com/C v1.2.0 => example.com/cfork v1.2.1
`

// parseRequireLine parses a single "path version [// comment]" require line.
func parseRequireLine(s string) req {
	fields := strings.Fields(s)
	if len(fields) >= 2 {
		return req{path: fields[0], version: fields[1]}
	}
	return req{}
}

// parseGoMod extracts the module path and require directives from a go.mod
// string. It is a deliberately small, line-oriented, comment-aware parser — NOT
// a full grammar implementation (the real one lives in golang.org/x/mod/modfile).
func parseGoMod(src string) (modulePath string, requires []req) {
	inRequire := false
	for _, raw := range strings.Split(src, "\n") {
		line := strings.TrimSpace(raw)
		if line == "" || strings.HasPrefix(line, "//") {
			continue
		}
		if i := strings.Index(line, "//"); i >= 0 { // strip trailing comment
			line = strings.TrimSpace(line[:i])
		}
		switch {
		case strings.HasPrefix(line, "module "):
			modulePath = strings.Trim(strings.TrimSpace(strings.TrimPrefix(line, "module ")), `"`)
		case line == "require (":
			inRequire = true
		case line == ")":
			inRequire = false
		case strings.HasPrefix(line, "require ") && !inRequire:
			if r := parseRequireLine(strings.TrimPrefix(line, "require ")); r.path != "" {
				requires = append(requires, r)
			}
		case inRequire:
			if r := parseRequireLine(line); r.path != "" {
				requires = append(requires, r)
			}
		}
	}
	return modulePath, requires
}

// containsReq reports whether rs holds a (path, version) require directive.
func containsReq(rs []req, path, version string) bool {
	for _, r := range rs {
		if r.path == path && r.version == version {
			return true
		}
	}
	return false
}

func sectionA() {
	sectionBanner("A — Parse a fixed go.mod (module path + require directives)")

	modPath, requires := parseGoMod(goModForParse)
	fmt.Printf("parsed module path  : %s\n", modPath)
	fmt.Printf("parsed require count: %d\n", len(requires))
	sort.Slice(requires, func(i, j int) bool { return requires[i].path < requires[j].path })
	for _, r := range requires {
		fmt.Printf("    require %-24s %s\n", r.path, r.version)
	}

	check(`parsed module path == "example.com/myapp"`, modPath == "example.com/myapp")
	check("parsed require count == 3", len(requires) == 3)
	check("require example.com/A v1.0.0 present", containsReq(requires, "example.com/A", "v1.0.0"))
	check("require example.com/C v1.2.0 present", containsReq(requires, "example.com/C", "v1.2.0"))
}

// --- Section B: MVS — the diamond dependency --------------------------------

func sectionB() {
	sectionBanner("B — Minimal Version Selection: the diamond (max of the mins)")

	// The canonical MVS teaching graph: main requires A and B; A needs C@v1.2.0,
	// B needs C@v1.5.0. MVS selects C@v1.5.0 — the MAXIMUM of the minimum
	// required versions across the graph. See go.dev/ref/mod "Minimal version
	// selection": MVS "tracks the highest required version of each module."
	graph := map[modKey][]req{
		{path: "example.com/A", version: "v1.0.0"}: {{path: "example.com/C", version: "v1.2.0"}},
		{path: "example.com/B", version: "v1.0.0"}: {{path: "example.com/C", version: "v1.5.0"}},
		{path: "example.com/C", version: "v1.2.0"}: {},
		{path: "example.com/C", version: "v1.5.0"}: {},
	}
	mains := []req{
		{path: "example.com/A", version: "v1.0.0"},
		{path: "example.com/B", version: "v1.0.0"},
	}

	fmt.Println("graph edges:")
	fmt.Println("    main        -> A@v1.0.0")
	fmt.Println("    main        -> B@v1.0.0")
	fmt.Println("    A@v1.0.0    -> C@v1.2.0")
	fmt.Println("    B@v1.0.0    -> C@v1.5.0")
	fmt.Println("MVS rule: take the HIGHEST version required by any module in the")
	fmt.Println("          build list -> C is max(v1.2.0, v1.5.0) = v1.5.0.")

	selected := mvs(graph, mains)
	printBuildList("MVS build list", selected)

	check("MVS selects A@v1.0.0", selected["example.com/A"] == "v1.0.0")
	check("MVS selects B@v1.0.0", selected["example.com/B"] == "v1.0.0")
	check("MVS selects C@v1.5.0 (max of A's v1.2.0 and B's v1.5.0)", selected["example.com/C"] == "v1.5.0")
	check("MVS did NOT pick the lower C@v1.2.0", cmpVersion(selected["example.com/C"], "v1.2.0") > 0)
}

// --- Section C: the bumpy upgrade + the replace escape hatch ----------------

func sectionC() {
	sectionBanner("C — The bumpy upgrade (one bump cascades) + replace escape hatch")

	// Add a transitive dep D. Baseline: B needs C@v1.5.0; C@v1.5.0 needs D@v1.2.0.
	baseline := map[modKey][]req{
		{path: "example.com/A", version: "v1.0.0"}: {
			{path: "example.com/C", version: "v1.2.0"},
			{path: "example.com/D", version: "v1.0.0"},
		},
		{path: "example.com/B", version: "v1.0.0"}: {{path: "example.com/C", version: "v1.5.0"}},
		{path: "example.com/C", version: "v1.2.0"}: {{path: "example.com/D", version: "v1.0.0"}},
		{path: "example.com/C", version: "v1.5.0"}: {{path: "example.com/D", version: "v1.2.0"}},
		{path: "example.com/D", version: "v1.0.0"}: {},
		{path: "example.com/D", version: "v1.2.0"}: {},
	}
	mains := []req{
		{path: "example.com/A", version: "v1.0.0"},
		{path: "example.com/B", version: "v1.0.0"},
	}

	selBase := mvs(baseline, mains)
	printBuildList("baseline build list", selBase)

	// BUMPY UPGRADE: bump B's requirement of C from v1.5.0 to v1.7.0. Nothing
	// else in main's go.mod changes — yet C rises to v1.7.0, and because
	// C@v1.7.0 needs D@v1.3.0, D rises too. One bump ripples transitively. This
	// "bumpiness" is inherent to MVS (it always takes the max).
	bumped := make(map[modKey][]req, len(baseline))
	for k, v := range baseline {
		bumped[k] = v
	}
	bumped[modKey{path: "example.com/B", version: "v1.0.0"}] = []req{{path: "example.com/C", version: "v1.7.0"}}
	bumped[modKey{path: "example.com/C", version: "v1.7.0"}] = []req{{path: "example.com/D", version: "v1.3.0"}}
	bumped[modKey{path: "example.com/D", version: "v1.3.0"}] = []req{}

	selBumped := mvs(bumped, mains)
	printBuildList("after bumping B's C-req to v1.7.0", selBumped)

	// REPLACE ESCAPE HATCH: pin C to a local fork cfork@v1.6.0 whose go.mod needs
	// only D@v1.0.0, overriding the cascade. A `replace` directive (main-module
	// go.mod or go.work) rewrites the graph edge, so the build sees cfork's node
	// instead of C's published node.
	replaced := make(map[modKey][]req, len(bumped))
	for k, v := range bumped {
		replaced[k] = v
	}
	replaced[modKey{path: "example.com/A", version: "v1.0.0"}] = []req{
		{path: "example.com/cfork", version: "v1.6.0"},
		{path: "example.com/D", version: "v1.0.0"},
	}
	replaced[modKey{path: "example.com/B", version: "v1.0.0"}] = []req{{path: "example.com/cfork", version: "v1.6.0"}}
	replaced[modKey{path: "example.com/cfork", version: "v1.6.0"}] = []req{{path: "example.com/D", version: "v1.0.0"}}

	selReplaced := mvs(replaced, mains)
	printBuildList("after replace C => cfork v1.6.0", selReplaced)

	check("baseline: C@v1.5.0", selBase["example.com/C"] == "v1.5.0")
	check("baseline: D@v1.2.0 (cascade from C@v1.5.0)", selBase["example.com/D"] == "v1.2.0")
	check("bumpy: C rose to v1.7.0", selBumped["example.com/C"] == "v1.7.0")
	check("bumpy: D cascaded to v1.3.0", selBumped["example.com/D"] == "v1.3.0")
	check("bumpy: C strictly higher than baseline", cmpVersion(selBumped["example.com/C"], selBase["example.com/C"]) > 0)
	check("replace: cfork@v1.6.0 selected (C substituted out)", selReplaced["example.com/cfork"] == "v1.6.0")
	check("replace: D pulled back down to v1.0.0", selReplaced["example.com/D"] == "v1.0.0")
}

// --- Section D: go.sum — the supply-chain hash line -------------------------

// pinnedZipHex is the sha256 hex of the fixed fakeZip bytes below. It is
// machine-computed (sha256 of a constant input) and pinned here so the run both
// prints it AND asserts the deterministic, tamper-evident value.
const pinnedZipHex = "7d2bfef639613c0a72de1b917b95044b6371001827fcef5542122f72e3818000"

func sectionD() {
	sectionBanner("D — go.sum: the supply-chain hash line (h1: = base64(sha256))")

	// A module .zip is just bytes. go.sum stores a cryptographic hash of those
	// bytes (and of the go.mod) so a tampered module is detected at build time.
	// The on-disk line format is:
	//     <module> <version> h1:<base64>            (hash of the .zip)
	//     <module> <version>/go.mod h1:<base64>     (hash of the .mod)
	// "h1" means SHA-256; the digest is base64-encoded (NOT hex).
	fakeZip := []byte("fake module zip contents for example.com/X@v1.0.0\n")
	sum := sha256.Sum256(fakeZip)
	hexDigest := hex.EncodeToString(sum[:])
	b64 := base64.StdEncoding.EncodeToString(sum[:])

	zipLine := fmt.Sprintf("example.com/X v1.0.0 h1:%s", b64)
	modLine := fmt.Sprintf("example.com/X v1.0.0/go.mod h1:%s", b64)
	fmt.Printf("sha256 hex of zip  : %s\n", hexDigest)
	fmt.Printf("go.sum zip line    : %s\n", zipLine)
	fmt.Printf("go.sum go.mod line : %s\n", modLine)

	// Tamper detection: flip one byte; the hash MUST change.
	tampered := append([]byte(nil), fakeZip...)
	tampered[0] ^= 0xFF
	tamperedSum := sha256.Sum256(tampered)
	tamperedHex := hex.EncodeToString(tamperedSum[:])
	fmt.Printf("tampered zip hex   : %s\n", tamperedHex)

	// Determinism: recompute and confirm it is byte-identical.
	recomputed := sha256.Sum256(fakeZip)
	recomputedHex := hex.EncodeToString(recomputed[:])

	check("sha256 hex matches pinned digest", hexDigest == pinnedZipHex)
	check("sha256 is deterministic (recomputed == first)", recomputedHex == hexDigest)
	check("tampering changes the hash (supply-chain integrity)", tamperedHex != hexDigest)
	check("zip line has the h1: prefix", strings.HasPrefix(zipLine, "example.com/X v1.0.0 h1:"))
	check("zip line ends with the base64 sha256", strings.HasSuffix(zipLine, b64))
}

// --- Section E: workspaces — local edits seen without publishing ------------

func sectionE() {
	sectionBanner("E — Workspaces (go.work): local edits seen WITHOUT publishing")

	// Two local modules: app and lib. app requires lib@v1.0.0 (the PUBLISHED
	// version); published lib@v1.0.0 requires X@v1.2.0. Without a workspace, MVS
	// selects lib@v1.0.0 and X@v1.2.0 straight from the proxy/graph.
	published := map[modKey][]req{
		{path: "example.com/app", version: "v1.0.0"}: {{path: "example.com/lib", version: "v1.0.0"}},
		{path: "example.com/lib", version: "v1.0.0"}: {{path: "example.com/X", version: "v1.2.0"}},
		{path: "example.com/X", version: "v1.2.0"}:   {},
	}
	appMain := []req{{path: "example.com/lib", version: "v1.0.0"}}

	selPublished := mvs(published, appMain)
	printBuildList("without go.work (published only)", selPublished)

	// go.work `use ./lib` makes the LOCAL lib a main module. Its locally-edited
	// go.mod requires X@v1.9.0. That local requirement is added to the top-level
	// set, so X rises to v1.9.0 — no `go get` and no publish needed. This is the
	// whole reason `go work` exists: edit one local module, see it everywhere.
	withWorkspace := make(map[modKey][]req, len(published))
	for k, v := range published {
		withWorkspace[k] = v
	}
	withWorkspace[modKey{path: "example.com/X", version: "v1.9.0"}] = []req{}
	workspaceMains := []req{
		{path: "example.com/lib", version: "v1.0.0"}, // from app's go.mod
		{path: "example.com/X", version: "v1.9.0"},   // from LOCAL lib's go.mod (seen via `use ./lib`)
	}

	selWorkspace := mvs(withWorkspace, workspaceMains)
	printBuildList("with go.work `use ./lib` (local lib wins)", selWorkspace)

	check("published: X@v1.2.0", selPublished["example.com/X"] == "v1.2.0")
	check("workspace: X rose to v1.9.0 (local override, no publish)", selWorkspace["example.com/X"] == "v1.9.0")
	check("workspace: X strictly higher than published", cmpVersion(selWorkspace["example.com/X"], selPublished["example.com/X"]) > 0)
}

// --- Section F: runtime/debug.ReadBuildInfo ---------------------------------

func sectionF() {
	sectionBanner("F — runtime/debug.ReadBuildInfo(): inspect the running build")

	// ReadBuildInfo returns the module graph baked into the running binary.
	// Under `go run file.go` the binary is the throwaway "command-line-arguments"
	// pseudo-module, so Path/Main.Version are limited (see the caveat below). A
	// real `go build` binary embeds the full module path, version, deps, and VCS
	// info (vcs.revision / vcs.time / vcs.modified).
	info, ok := debug.ReadBuildInfo()

	fmt.Printf("ReadBuildInfo() ok : %v\n", ok)
	fmt.Printf("info == nil?       : %v\n", info == nil)
	fmt.Printf("info.Path          : %s   (under `go run`: \"command-line-arguments\")\n", info.Path)
	fmt.Printf("info.GoVersion     : %s   (toolchain that compiled this binary)\n", info.GoVersion)
	fmt.Printf("info.Main.Path     : %s\n", info.Main.Path)
	fmt.Printf("info.Main.Version  : %q   (empty under `go run`; real for `go build`)\n", info.Main.Version)
	fmt.Printf("info.Deps length   : %d   (external modules; the stdlib is NOT listed)\n", len(info.Deps))

	// Settings: sorted by key for deterministic output. Includes GOOS/GOARCH,
	// the compiler, CGO_ENABLED, and VCS info when built inside a repo.
	settings := append([]debug.BuildSetting(nil), info.Settings...)
	sort.Slice(settings, func(i, j int) bool { return settings[i].Key < settings[j].Key })
	fmt.Println("info.Settings (sorted):")
	for _, s := range settings {
		fmt.Printf("    %-16s %s\n", s.Key, s.Value)
	}

	check("ReadBuildInfo returns non-nil info", info != nil)
	check("info.GoVersion is non-empty (toolchain known)", info.GoVersion != "")
	check("info.Path under `go run` is the command-line-arguments pseudo-path", info.Path == "command-line-arguments")
	check("no external deps (this bundle is stdlib-only)", len(info.Deps) == 0)
}

func main() {
	fmt.Println("modules_workspace.go — Phase 7 bundle (CLI, Tooling & Build).")
	fmt.Println("Every version, hash, and build list below is computed by this file;")
	fmt.Println("the .md guide pastes it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
