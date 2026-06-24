//go:build ignore

// io_reader_writer.go — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how the io.Reader/io.Writer
// streaming model works, why a single Read may return partial data, how the
// composition helpers (io.Copy/ReadAll, MultiReader, LimitReader, TeeReader),
// bufio.Scanner/Reader, bytes.Buffer, strings.Reader, and io/fs.FS fit on top
// of it.
//
// This is the GROUND TRUTH for IO_READER_WRITER.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run io_reader_writer.go

package main

import (
	"bufio"
	"bytes"
	"embed"
	"fmt"
	"io"
	"io/fs"
	"os"
	"strings"
)

// Compile-time proofs of interface satisfaction. These lines do not run, but
// they make the type-vs-interface relationships a *compile error* if they ever
// drift. They are the runnable counterpart to the io.Reader/io.Writer contract.
var (
	_ io.Reader   = (*strings.Reader)(nil) // strings.NewReader returns *strings.Reader
	_ io.Reader   = (*bytes.Buffer)(nil)   // bytes.Buffer is BOTH a Reader...
	_ io.Writer   = (*bytes.Buffer)(nil)   // ...and a Writer (in-memory round-trip)
	_ io.WriterTo = (*bytes.Buffer)(nil)   // ...and a WriterTo (io.Copy fast-path)
	_ fs.FS       = (fs.FS)(nil)           // io/fs.FS is the filesystem abstraction
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

// dripReader is a deterministic io.Reader that returns AT MOST `chunk` bytes per
// Read call, no matter how big the supplied buffer is. It exists to PROVE the
// cardinal rule of io.Reader: a single Read may legitimately return fewer bytes
// than asked for, and the caller must loop until io.EOF. (See IO_READER_WRITER
// Section B + the io.Reader doc quote in the .md.)
type dripReader struct {
	data  []byte
	chunk int
	off   int
}

// Read copies min(chunk, remaining) bytes into p. It returns (0, io.EOF) only
// once the source is fully consumed, and never returns data alongside EOF.
func (d *dripReader) Read(p []byte) (int, error) {
	if d.off >= len(d.data) {
		return 0, io.EOF
	}
	end := d.off + d.chunk
	if end > len(d.data) {
		end = len(d.data)
	}
	n := copy(p, d.data[d.off:end])
	d.off += n
	return n, nil
}

// sectionA shows the Reader/Writer pipeline at its simplest: a strings.Reader
// (source) copied into a bytes.Buffer (sink) by io.Copy, which loops Read/Write
// until EOF and returns the total byte count.
func sectionA() {
	sectionBanner("A — Reader/Writer basics: strings.Reader -> io.Copy -> bytes.Buffer")

	src := strings.NewReader("hello") // *strings.Reader implements io.Reader
	var buf bytes.Buffer              // *bytes.Buffer implements io.Writer (and io.Reader)

	n, err := io.Copy(&buf, src) // &buf: Write has a pointer receiver
	fmt.Printf("io.Copy(&buf, strings.NewReader(\"hello\")) -> n=%d, err=%v\n", n, err)
	fmt.Printf("buf.String() = %q   buf.Len() = %d\n", buf.String(), buf.Len())
	fmt.Printf("len(\"hello\") = %d   (the source byte count Copy reached EOF at)\n", len("hello"))

	check("io.Copy copied exactly 5 bytes", n == 5)
	check("io.Copy returned err == nil (EOF is NOT an error)", err == nil)
	check("buf.String() == \"hello\" (round-trips the source)", buf.String() == "hello")
	check("bytes copied == len(source)", int(n) == len("hello"))

	// io.CopyN is Copy with a byte budget: copy exactly n, or stop at EOF/error.
	var n2 bytes.Buffer
	copied, err := io.CopyN(&n2, strings.NewReader("HELLOWORLD"), 5)
	fmt.Printf("\nio.CopyN(&buf2, src, 5) -> copied=%d, err=%v, buf2=%q\n", copied, err, n2.String())
	check("CopyN copied exactly 5 bytes", copied == 5 && err == nil)
	check("CopyN stopped after the budget (\"HELLO\")", n2.String() == "HELLO")
}

// sectionB proves the "Read may return partial data" rule with a controlled
// reader, then shows the two ways to handle it: the manual loop, and io.ReadAll
// (which is the loop, pre-written).
func sectionB() {
	sectionBanner("B — Read may return PARTIAL data: loop until io.EOF")

	// dripReader returns 3 bytes per call over an 8-byte source, even though we
	// hand it an 8-byte buffer. A naive "one Read is enough" assumption fails.
	drip := &dripReader{data: []byte("ABCDEFGH"), chunk: 3}
	buf := make([]byte, 8) // deliberately larger than chunk
	var got strings.Builder
	sizes := []int{}
	for {
		n, err := drip.Read(buf)
		sizes = append(sizes, n)
		if n > 0 {
			got.Write(buf[:n])
		}
		fmt.Printf("  Read -> n=%d err=%v\n", n, err)
		if err == io.EOF {
			break
		}
		if err != nil {
			panic(err)
		}
	}
	fmt.Printf("per-call sizes = %v   (3 calls returned LESS than the buffer)\n", sizes[:len(sizes)-1])
	fmt.Printf("manual loop accumulated = %q\n", got.String())

	check("a single Read returned only 3 bytes (not all 8)", sizes[0] == 3)
	check("per-call sizes == [3 3 2 0]", fmt.Sprint(sizes) == "[3 3 2 0]")
	check("manual Read loop reconstructed the full source", got.String() == "ABCDEFGH")

	// io.ReadAll is exactly that loop, written once for everyone.
	all, err := io.ReadAll(&dripReader{data: []byte("ABCDEFGH"), chunk: 3})
	fmt.Printf("\nio.ReadAll(drip of \"ABCDEFGH\") -> %q, err=%v\n", string(all), err)
	check("io.ReadAll reconstructs the same bytes as the manual loop", string(all) == "ABCDEFGH")
	check("io.ReadAll returns err == nil on a clean EOF (EOF is not an error)", err == nil)

	// The sentinel that signals "no more data": callers test with ==, never
	// errors.Is, because a Reader "must return EOF itself, not an error wrapping
	// EOF" (io package doc).
	fmt.Printf("\nio.EOF == %v   (tested with ==; Read returns it at end of stream)\n", io.EOF)
	check("the end-of-stream sentinel is io.EOF", dripEOF() == io.EOF)
}

// dripEOF returns the error a fresh exhausted dripReader reports.
func dripEOF() error {
	d := &dripReader{data: []byte("X"), chunk: 1}
	b := make([]byte, 4)
	_, _ = d.Read(b) // consume the 1 byte
	_, err := d.Read(b)
	return err
}

// sectionC shows Reader COMPOSITION: chaining small readers into bigger ones
// without allocating intermediate buffers. MultiReader concatenates, LimitReader
// caps the byte count, TeeReader taps a side copy to another Writer as you read.
func sectionC() {
	sectionBanner("C — Composition: MultiReader + LimitReader + TeeReader")

	// MultiReader: logical concatenation. Read sequentially from a, then b, c.
	mr := io.MultiReader(
		strings.NewReader("a"),
		strings.NewReader("b"),
		strings.NewReader("c"),
	)
	var mb bytes.Buffer
	n, err := io.Copy(&mb, mr)
	fmt.Printf("MultiReader(\"a\",\"b\",\"c\") copied -> n=%d err=%v content=%q\n", n, err, mb.String())
	check("MultiReader concatenates to \"abc\"", mb.String() == "abc")
	check("MultiReader copied 3 bytes total", n == 3 && err == nil)

	// LimitReader: a Reader that returns EOF after N bytes, capping the stream.
	lr := io.LimitReader(strings.NewReader("HELLOWORLD"), 2)
	limited, err := io.ReadAll(lr)
	fmt.Printf("LimitReader(src, 2) read all -> %q (len %d), err=%v\n", string(limited), len(limited), err)
	check("LimitReader caps the stream at 2 bytes", len(limited) == 2)
	check("LimitReader returned the first 2 bytes \"HE\"", string(limited) == "HE")

	// TeeReader: every byte read is ALSO written to the tap. No internal buffer;
	// the write completes before the read returns. Ideal for logging/caching a
	// stream as it is consumed.
	var tap bytes.Buffer
	tee := io.TeeReader(strings.NewReader("teedata"), &tap)
	consumed, err := io.ReadAll(tee)
	fmt.Printf("TeeReader(src, &tap) read %q; tap captured %q; err=%v\n", string(consumed), tap.String(), err)
	check("TeeReader consumer read the full stream", string(consumed) == "teedata")
	check("TeeReader tap captured every byte the consumer read", tap.String() == string(consumed))
	check("TeeReader tap length == consumed length", tap.Len() == len(consumed))
}

// sectionD contrasts the two buffered readers. bufio.Scanner is token-oriented
// (lines/words by default) and hides the Read loop; bufio.Reader is byte-
// oriented, exposes Read/Peek/ReadString, and lets you interleave reads.
func sectionD() {
	sectionBanner("D — bufio.Scanner (tokens) vs bufio.Reader (bytes)")

	// Scanner with the default split (ScanLines): one token per line, newline
	// stripped. The final line is returned even without a trailing newline.
	scanner := bufio.NewScanner(strings.NewReader("a\nb\nc\n"))
	lines := []string{}
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
	}
	fmt.Printf("Scanner over \"a\\nb\\nc\\n\" -> %d lines = %q\n", len(lines), lines)
	fmt.Printf("scanner.Err() = %v   (io.EOF is swallowed: Err() returns nil)\n", scanner.Err())
	check("Scanner found exactly 3 lines", len(lines) == 3)
	check("Scanner lines == [a b c]", fmt.Sprint(lines) == "[a b c]")
	check("Scanner.Err() is nil after a clean scan", scanner.Err() == nil)

	// Same Scanner, ScanWords split: whitespace-delimited tokens, none empty.
	wordScan := bufio.NewScanner(strings.NewReader("alpha beta gamma"))
	wordScan.Split(bufio.ScanWords)
	words := []string{}
	for wordScan.Scan() {
		words = append(words, wordScan.Text())
	}
	fmt.Printf("\nScanner(ScanWords) over \"alpha beta gamma\" -> %d words = %q\n", len(words), words)
	check("ScanWords found 3 words", len(words) == 3)
	check("ScanWords words == [alpha beta gamma]", fmt.Sprint(words) == "[alpha beta gamma]")

	// bufio.Reader is byte-oriented: ReadString(delim) returns through the delim.
	br := bufio.NewReader(strings.NewReader("line-1\nline-2"))
	first, _ := br.ReadString('\n')
	rest, ferr := br.ReadString('\n')
	fmt.Printf("\nbufio.Reader.ReadString('\\n'): first=%q rest=%q err=%v\n", first, rest, ferr)
	check("bufio.Reader.ReadString returned \"line-1\\n\"", first == "line-1\n")
	check("bufio.Reader read the remaining \"line-2\" (no trailing newline)", rest == "line-2")
}

// sectionE exercises bytes.Buffer as BOTH an io.Writer and an io.Reader — the
// in-memory round-trip. Writing appends to an internal []byte; reading drains
// it from the current offset.
func sectionE() {
	sectionBanner("E — bytes.Buffer: Writer THEN Reader (in-memory round-trip)")

	var buf bytes.Buffer // zero value is ready to use (no make needed)
	m, _ := buf.WriteString("round")
	buf.Write([]byte("-trip"))
	fmt.Printf("Write(\"round\") + Write(\"-trip\") -> n(first write)=%d  String()=%q  Len()=%d\n",
		m, buf.String(), buf.Len())

	check("bytes.Buffer.String() == \"round-trip\"", buf.String() == "round-trip")
	check("bytes.Buffer.Len() == 10 after the writes", buf.Len() == 10)

	// Now read it back: bytes.Buffer also satisfies io.Reader. Each Read drains
	// from the internal offset, so the buffer empties as you read.
	out := make([]byte, 10)
	rn, _ := buf.Read(out)
	fmt.Printf("Read into 10-byte slice -> n=%d  bytes=%q  remaining Len()=%d\n", rn, out, buf.Len())

	check("bytes.Buffer.Read drained all 10 bytes", rn == 10)
	check("bytes.Buffer round-trips the written content", string(out) == "round-trip")
	check("bytes.Buffer is empty after a full drain", buf.Len() == 0)

	// The proof these are real interface methods, not coincidences: the
	// compile-time assertions at the top of the file would fail otherwise.
	fmt.Println("(*bytes.Buffer satisfies io.Reader AND io.Writer — see top-of-file assertions)")
	check("*bytes.Buffer is an io.Writer", isWriter(&buf))
	check("*bytes.Buffer is an io.Reader", isReader(&buf))
}

// isReader reports whether v satisfies io.Reader at runtime.
func isReader(v any) bool {
	_, ok := v.(io.Reader)
	return ok
}

// isWriter reports whether v satisfies io.Writer at runtime.
func isWriter(v any) bool {
	_, ok := v.(io.Writer)
	return ok
}

// sectionF shows io/fs.FS: the filesystem abstraction. os.DirFS(".") and
// embed.FS both implement it, so the SAME helper reads a real directory or
// embedded files. We read a known, fixed file (go.mod) from both.
func sectionF() {
	sectionBanner("F — io/fs.FS: same code reads os.DirFS AND embed.FS")

	dirLine := readFirstLine(os.DirFS("."), "go.mod")
	embedLine := readFirstLine(&embeddedFS, "go.mod")
	fmt.Printf("os.DirFS(\".\").Open(\"go.mod\") first line = %q\n", dirLine)
	fmt.Printf("embed.FS.ReadFile(\"go.mod\")   first line = %q\n", embedLine)

	check("os.DirFS read a first line containing \"module\"", strings.Contains(dirLine, "module"))
	check("embed.FS read a first line containing \"module\"", strings.Contains(embedLine, "module"))
	check("both fs.FS implementations returned the same first line", dirLine == embedLine)

	// os.DirFS and embed.FS are DIFFERENT concrete types that both satisfy the
	// same fs.FS interface — that is the whole point of the abstraction.
	var _ fs.FS = os.DirFS(".")
	var _ fs.FS = &embeddedFS
	fmt.Println("os.DirFS(\".\") and embed.FS both satisfy fs.FS (compile-time asserted above)")
	check("os.DirFS(\".\") is an fs.FS", isFS(os.DirFS(".")))
	check("embed.FS is an fs.FS", isFS(&embeddedFS))
}

// readFirstLine opens name on fsys, reads up to its first newline via the
// fs.File's Read method (an io.Reader), closes it, and returns the first line.
// Because it only depends on the fs.FS interface, it works unchanged for a real
// directory (os.DirFS) and for embedded files (embed.FS).
func readFirstLine(fsys fs.FS, name string) string {
	f, err := fsys.Open(name)
	if err != nil {
		return fmt.Sprintf("<open error: %v>", err)
	}
	defer f.Close()

	var b []byte
	one := make([]byte, 1)
	for {
		n, err := f.Read(one) // fs.File implements io.Reader
		if n > 0 {
			if one[0] == '\n' {
				break
			}
			b = append(b, one[0])
			continue
		}
		if err != nil {
			break
		}
	}
	return string(b)
}

// isFS reports whether v satisfies fs.FS at runtime.
func isFS(v any) bool {
	_, ok := v.(fs.FS)
	return ok
}

func main() {
	fmt.Println("io_reader_writer.go — Phase 5 bundle.")
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
