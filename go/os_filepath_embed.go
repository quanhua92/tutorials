//go:build ignore

// os_filepath_embed.go — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how os (ReadFile/Create/Open),
// path/filepath (Join/Base/Dir/Ext/Clean/WalkDir/Glob/Abs), the //go:embed
// directive (embed.FS), and the io/fs.FS abstraction fit together — the SAME
// fs.FS-accepting function reads both a real OS dir (os.DirFS) and a
// compile-time baked-in tree (embed.FS).
//
// This is the GROUND TRUTH for OS_FILEPATH_EMBED.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run os_filepath_embed.go

package main

import (
	"bytes"
	"embed"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// Compile-time proofs of interface satisfaction. embed.FS is the canonical
// producer of an fs.FS that is NOT backed by the OS: its bytes are baked into
// the binary at compile time by the //go:embed directive below. These lines are
// a compile error if embed.FS ever drifts away from the fs.FS contract.
var (
	_ fs.FS         = embed.FS{} // Open(name) (fs.File, error)        — the minimum
	_ fs.ReadDirFS  = embed.FS{} // + ReadDir(name) ([]fs.DirEntry, error)
	_ fs.ReadFileFS = embed.FS{} // + ReadFile(name) ([]byte, error)     (fs.ReadFile fast-path)
)

//go:embed go.mod
var embeddedFS embed.FS // a known, fixed file committed in this module -> deterministic

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

// mustNoErr panics on a non-nil error so a failing syscall aborts the run with a
// non-zero exit (the verification sweep catches it). It is the error-returning
// analogue of check().
func mustNoErr(op string, err error) {
	if err != nil {
		panic(op + ": " + err.Error())
	}
}

// contains reports whether ss contains s. (A tiny helper so the bundle does not
// pull in the slices package for a single membership test.)
func contains(ss []string, s string) bool {
	for _, x := range ss {
		if x == s {
			return true
		}
	}
	return false
}

// firstLineOf reads the first line of `name` from ANY fs.FS. The point of this
// helper is that it is POLYMORPHIC: it does not care whether fsys is an
// embed.FS (compile-time bytes) or an os.DirFS (real OS files). Both implement
// the one-method fs.FS interface, so the same code reads both. See Section E.
func firstLineOf(fsys fs.FS, name string) (string, error) {
	f, err := fsys.Open(name)
	if err != nil {
		return "", err
	}
	defer f.Close()
	b, err := io.ReadAll(f)
	if err != nil {
		return "", err
	}
	s := string(b)
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		s = s[:i]
	}
	return strings.TrimRight(s, "\r"), nil
}

// sectionA is a round-trip built on three os entry points:
//   - os.WriteFile(name, data, perm): the 1.16+ one-shot (Create+Write+Close)
//     and the modern replacement for ioutil.WriteFile. It HONORS `perm` (subject
//     to umask) when it creates the file.
//   - os.ReadFile(name): the 1.16+ one-shot reader (replacement for
//     ioutil.ReadFile).
//   - os.Open / os.Create: return a *os.File (an io.ReadWriteCloser) that MUST
//     be Close'd. Note the perm gotcha: os.Create is literally
//     OpenFile(name, O_RDWR|O_CREATE|O_TRUNC, 0666) — it hardcodes 0o666 and gives
//     you NO way to set a different perm, so after umask 0o022 the file lands at
//     0o644. os.WriteFile is the one that lets you pass 0o600.
//
// The temp files live in os.TempDir() (machine-dependent, so NEVER printed) and
// are removed via deferred os.Remove. Only their stable Base() is printed.
func sectionA() {
	sectionBanner("A — WriteFile/ReadFile round-trip + Open/Create (*os.File)")

	content := []byte("os_filepath_embed round-trip\n")
	path := filepath.Join(os.TempDir(), "os_filepath_embed_demo.txt")
	os.Remove(path)       // guarantee a clean slate (ignore "no such file" error)
	defer os.Remove(path) // clean up no matter how we exit

	// os.WriteFile HONORS perm: 0o600 & ^umask(0o022) == 0o600 (no group/other
	// bits to clear), so the file is created exactly rw-------.
	mustNoErr("os.WriteFile", os.WriteFile(path, content, 0o600))

	got, err := os.ReadFile(path) // 1.16+; modern replacement for ioutil.ReadFile
	mustNoErr("os.ReadFile", err)
	fmt.Printf("WriteFile wrote %d bytes, ReadFile read back %d -> equal? %v\n",
		len(content), len(got), bytes.Equal(got, content))
	fmt.Printf("os.ReadFile(%q) = %q\n", filepath.Base(path), got)

	check("os.WriteFile then os.ReadFile returned identical bytes",
		bytes.Equal(got, content))

	// os.Open returns a read-only *os.File. Same Close obligation — here shown
	// with the idiomatic `defer f.Close()` immediately after the error check.
	f, err := os.Open(path)
	mustNoErr("os.Open", err)
	defer f.Close()

	fi, err := f.Stat() // *os.File.Stat uses the already-open fd (no new path lookup)
	mustNoErr("(*os.File).Stat", err)
	fmt.Printf("os.Open -> *os.File; Stat: Name=%q  Size=%d  Mode=%v\n",
		fi.Name(), fi.Size(), fi.Mode())

	check("Stat.Name() == filepath.Base(path)", fi.Name() == filepath.Base(path))
	check("Stat.Size() == len(content)", fi.Size() == int64(len(content)))
	check("Stat.Mode() is a regular file", fi.Mode().IsRegular())
	check("Stat.Mode().Perm() == 0o600 (WriteFile honored perm)", fi.Mode().Perm() == os.FileMode(0o600))

	// os.Create returns a *os.File too, but hardcodes perm 0o666: after umask
	// 0o022 the file is 0o644, NOT 0o600. This is the Create-vs-WriteFile
	// gotcha: use WriteFile (or OpenFile) when you need to control permissions.
	path2 := filepath.Join(os.TempDir(), "os_filepath_embed_create_demo.txt")
	os.Remove(path2)
	defer os.Remove(path2)
	fc, err := os.Create(path2)
	mustNoErr("os.Create", err)
	n, err := fc.Write(content)
	mustNoErr("(*os.File).Write", err)
	mustNoErr("(*os.File).Close", fc.Close())
	check("(*os.File).Write wrote exactly len(content) bytes", n == len(content))

	fc2, err := os.Open(path2)
	mustNoErr("os.Open(path2)", err)
	defer fc2.Close()
	fi2, err := fc2.Stat()
	mustNoErr("(*os.File).Stat (path2)", err)
	fmt.Printf("os.Create -> *os.File; Stat: Name=%q  Mode=%v (0o666 & ^umask -> 0o644)\n",
		fi2.Name(), fi2.Mode())
	check("os.Create perm == 0o644 (0o666 hardcoded, umask 0o022)", fi2.Mode().Perm() == os.FileMode(0o644))
}

// sectionB demonstrates path/filepath: the CROSS-PLATFORM path library. It
// joins with the OS separator (here '/'), and provides Base/Dir/Ext/Clean/Abs.
// (The "path" package — NOT used here — is slash-only and meant for URLs.)
func sectionB() {
	sectionBanner("B — path/filepath: Join/Base/Dir/Ext/Clean/Abs/Glob/Match")

	joined := filepath.Join("a", "b", "c.txt") // OS separator; result is Cleaned
	fmt.Printf(`filepath.Join("a","b","c.txt")   = %q`+"\n", joined)
	fmt.Printf(`filepath.Base("/a/b/c")         = %q`+"\n", filepath.Base("/a/b/c"))
	fmt.Printf(`filepath.Dir("/a/b/c")          = %q`+"\n", filepath.Dir("/a/b/c"))
	fmt.Printf(`filepath.Ext("x.tar.gz")        = %q   (suffix from the FINAL dot)`+"\n", filepath.Ext("x.tar.gz"))
	fmt.Printf(`filepath.Clean("a/./b/../c")    = %q   (. and .. lexically removed)`+"\n", filepath.Clean("a/./b/../c"))

	absGoMod, err := filepath.Abs("go.mod") // cwd-relative -> absolute; result is Cleaned
	mustNoErr("filepath.Abs", err)
	// absGoMod is machine/cwd-specific, so we do NOT print the raw path; we only
	// assert its portable properties (absolute + still rooted at go.mod).
	fmt.Printf(`filepath.Abs("go.mod")          = IsAbs=%v  Base=%q  (raw path is cwd-specific, not printed)`+"\n",
		filepath.IsAbs(absGoMod), filepath.Base(absGoMod))

	matches, err := filepath.Glob("go.mod") // a literal name is a valid pattern -> exact match
	mustNoErr("filepath.Glob", err)
	fmt.Printf(`filepath.Glob("go.mod")         = %v`+"\n", matches)

	ok, err := filepath.Match("go.mo?", "go.mod") // '?' = one non-separator char
	mustNoErr("filepath.Match", err)
	fmt.Printf(`filepath.Match("go.mo?","go.mod") = matched=%v`+"\n", ok)
	fmt.Printf(`filepath.Separator (OS)         = %q`+"\n", string(filepath.Separator))

	check(`filepath.Join("a","b","c.txt") == "a/b/c.txt"`, joined == "a/b/c.txt")
	check(`filepath.Base("/a/b/c") == "c"`, filepath.Base("/a/b/c") == "c")
	check(`filepath.Dir("/a/b/c") == "/a/b"`, filepath.Dir("/a/b/c") == "/a/b")
	check(`filepath.Ext("x.tar.gz") == ".gz"`, filepath.Ext("x.tar.gz") == ".gz")
	check(`filepath.Clean("a/./b/../c") == "a/c"`, filepath.Clean("a/./b/../c") == "a/c")
	check(`filepath.Abs("go.mod") is absolute`, filepath.IsAbs(absGoMod))
	check(`filepath.Glob("go.mod") == ["go.mod"]`, len(matches) == 1 && matches[0] == "go.mod")
	check(`filepath.Match("go.mo?","go.mod") matched`, ok)
	check(`filepath.Separator == "/" (this OS)`, string(filepath.Separator) == "/")
}

// sectionC walks a tree with filepath.WalkDir. WalkDir visits root then recurses
// into subdirectories. Although the docs guarantee lexical order WITHIN each
// directory, we still SORT the collected paths before doing anything with them
// (the house determinism rule: never rely on walk/directory order for output).
// To keep the printed output stable as other bundles are added to this folder,
// we only PRINT the entries matching a fixed allowlist; the full walk still
// drives the "go.mod found" / recursion assertions.
func sectionC() {
	sectionBanner("C — filepath.WalkDir: walking a tree (collected, sorted, filtered)")

	var all []string
	err := filepath.WalkDir(".", func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err // surface access errors (e.g. permission) to the caller
		}
		all = append(all, p)
		return nil
	})
	mustNoErr("filepath.WalkDir", err)
	sort.Strings(all) // determinism: never print walk results in arrival order

	// Fixed allowlist -> printed output is invariant as sibling bundles change.
	allow := map[string]bool{
		"go.mod":               true,
		"HOW_TO_RESEARCH.md":   true,
		"Justfile":             true,
		"os_filepath_embed.go": true,
		"scripts/skeleton.go":  true, // proves WalkDir recursed INTO a subdir
		"values_types_zero.go": true,
	}
	fmt.Println(`WalkDir(".") printed subset (sorted):`)
	for _, p := range all {
		if allow[p] {
			fmt.Printf("  %s\n", p)
		}
	}

	check(`WalkDir found "go.mod" at the root`, contains(all, "go.mod"))
	check(`WalkDir recursed into "scripts/" (found scripts/skeleton.go)`,
		contains(all, "scripts/skeleton.go"))
	check(`WalkDir found this file (os_filepath_embed.go)`,
		contains(all, "os_filepath_embed.go"))
	check("collected WalkDir paths are sorted", sort.StringsAreSorted(all))
}

// sectionD uses the //go:embed directive at the top of this file: it bakes
// go.mod's bytes into the binary at COMPILE time. embed.FS.ReadFile reads them
// back at run time. The directive must sit directly above a package-scope var of
// type embed.FS (or string/[]byte); only blank lines and // comments may sit
// between the directive and the declaration.
func sectionD() {
	sectionBanner("D — //go:embed go.mod: files baked in at compile time")

	raw, err := embeddedFS.ReadFile("go.mod") // embed.FS.ReadFile, NOT os.ReadFile
	mustNoErr("embeddedFS.ReadFile", err)
	fmt.Printf("embeddedFS.ReadFile(\"go.mod\") -> %d bytes\n", len(raw))

	first, err := firstLineOf(embeddedFS, "go.mod")
	mustNoErr("firstLineOf(embeddedFS)", err)
	fmt.Printf("embed go.mod first line = %q\n", first)

	check(`embed go.mod first line contains "module"`,
		strings.Contains(first, "module"))
	check("embedded bytes length > 0", len(raw) > 0)
}

// sectionE is the payoff: the SAME firstLineOf helper (which accepts an fs.FS)
// reads go.mod from TWO different producers — embed.FS (compile-time bytes) and
// os.DirFS(".") (real OS files). Both implement the one-method fs.FS interface,
// so neither the helper nor its caller knows or cares which is which. We also
// prove at run time that os.DirFS satisfies the richer ReadDirFS/ReadFileFS/
// StatFS interfaces, and list a directory THROUGH the fs.FS abstraction.
func sectionE() {
	sectionBanner("E — io/fs.FS abstraction: embed.FS and os.DirFS, one function")

	fromEmbed, err := firstLineOf(embeddedFS, "go.mod")
	mustNoErr("firstLineOf(embeddedFS)", err)
	fromDirFS, err := firstLineOf(os.DirFS("."), "go.mod")
	mustNoErr(`firstLineOf(os.DirFS("."))`, err)

	fmt.Printf(`firstLineOf(embed.FS,      "go.mod") = %q`+"\n", fromEmbed)
	fmt.Printf(`firstLineOf(os.DirFS("."), "go.mod") = %q`+"\n", fromDirFS)
	fmt.Printf(`both contain "module"? embed=%v  dirfs=%v`+"\n",
		strings.Contains(fromEmbed, "module"), strings.Contains(fromDirFS, "module"))

	check(`embed.FS first line contains "module"`,
		strings.Contains(fromEmbed, "module"))
	check(`os.DirFS(".") first line contains "module"`,
		strings.Contains(fromDirFS, "module"))
	check(`embed.FS and os.DirFS(".") returned the SAME first line`,
		fromEmbed == fromDirFS)

	// Runtime proof that os.DirFS implements MORE than the bare fs.FS:
	dirFS := os.DirFS(".")
	_, isReadDirFS := dirFS.(fs.ReadDirFS)
	_, isReadFileFS := dirFS.(fs.ReadFileFS)
	_, isStatFS := dirFS.(fs.StatFS)
	fmt.Printf(`os.DirFS(".") also implements: ReadDirFS=%v  ReadFileFS=%v  StatFS=%v`+"\n",
		isReadDirFS, isReadFileFS, isStatFS)
	check(`os.DirFS(".") implements fs.ReadDirFS`, isReadDirFS)
	check(`os.DirFS(".") implements fs.ReadFileFS`, isReadFileFS)
	check(`os.DirFS(".") implements fs.StatFS`, isStatFS)

	// Listing a directory THROUGH the fs.FS abstraction. fs.ReadDir docs already
	// promise sorted-by-filename output, but we re-sort to model the house rule
	// for arbitrary fs.FS producers (not all of them sort).
	entries, err := fs.ReadDir(dirFS, ".")
	mustNoErr(`fs.ReadDir(dirFS, ".")`, err)
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		names = append(names, e.Name())
	}
	sort.Strings(names)
	allow := map[string]bool{"go.mod": true, "Justfile": true, "values_types_zero.go": true}
	fmt.Println(`fs.ReadDir(os.DirFS("."), ".") printed subset (sorted):`)
	for _, nm := range names {
		if allow[nm] {
			fmt.Printf("  %s\n", nm)
		}
	}
	check(`fs.ReadDir(os.DirFS,".") found "go.mod" via the fs.FS abstraction`,
		contains(names, "go.mod"))
}

func main() {
	fmt.Println("os_filepath_embed.go — Phase 5 bundle.")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionBanner("DONE — all sections printed")
}
