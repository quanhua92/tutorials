//go:build ignore

// embedding_composition.go — Phase 2 bundle #14.
//
// GOAL (one line): show, by printing every value, how Go's embedding builds
// COMPOSITION (method/field forwarding) — struct embedding vs interface
// embedding, the mock/decorator pattern, embedding an interface as a delegate
// field (and its nil-deref trap), and selector-depth conflict resolution.
//
// This is the GROUND TRUTH for EMBEDDING_COMPOSITION.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// Run:
//
//	go run embedding_composition.go

package main

import (
	"bytes"
	"fmt"
	"io"
	"reflect"
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

// --- types used across sections ---------------------------------------------

// Logger is an UNNAMED (embedded) field inside Server. It is the canonical
// "embed by type name, no field name" shape: `type Server struct { Logger }`.
type Logger struct {
	prefix string
}

// Log has a VALUE receiver. Because Server embeds Logger, Log is PROMOTED to
// Server through selector forwarding — but the receiver of the call is always
// the inner Logger, never the Server. (Section B + D exploit this.)
func (l Logger) Log(msg string) string {
	return l.prefix + msg
}

// Loggable is the interface a Logger satisfies. Section B proves that Server
// ALSO satisfies it — NOT because Server is a subtype of Logger (it is not),
// but because promotion makes Log part of Server's method set. This is Go's
// "accidental interface" leak.
type Loggable interface {
	Log(string) string
}

// Server embeds Logger as an UNNAMED field. The field's name is the type name,
// "Logger". Initialization uses the type as the key: Server{Logger: Logger{...}}.
type Server struct {
	Logger
	id int
}

// --- section C: small interfaces composed by embedding ---------------------

// TokenReader / TokenWriter are composed (embedded) into TokenReadWriter below,
// mirroring how io.ReadWriter embeds io.Reader + io.Writer (see io/io.go).
type TokenReader interface{ ReadToken() string }
type TokenWriter interface{ WriteToken(string) }

// TokenReadWriter EMBEDS two interfaces. Its method set is the UNION of theirs
// — the spec phrases this as "the type set of T is the intersection of the type
// sets" (intersection of TYPE sets == union of METHOD sets for basic interfaces).
type TokenReadWriter interface {
	TokenReader
	TokenWriter
}

// TokenStream satisfies TokenReadWriter: it has BOTH ReadToken and WriteToken.
type TokenStream struct{ n int }

func (s *TokenStream) ReadToken() string { s.n++; return fmt.Sprintf("tok%d", s.n) }
func (s *TokenStream) WriteToken(string) {}

// --- section D: the "no virtual dispatch" proof + the decorator -------------

// Base carries Hello and a Greet that calls Hello on its OWN receiver. When
// Override embeds Base and redeclares Hello, Greet (promoted from Base) still
// calls Base.Hello — proving there is no virtual dispatch in Go embedding.
type Base struct{}

func (Base) Hello() string { return "Base.Hello" }

// Greet forwards to b.Hello(). b is statically Base, so this always binds to
// Base.Hello even when the OUTER type redeclares Hello.
func (b Base) Greet() string { return b.Hello() }

// Override embeds Base and redeclares Hello at SHALLOWER depth (depth 0).
// o.Hello() picks Override.Hello (shallowest wins), but o.Greet() still reaches
// Base.Hello because Greet is promoted with receiver = the embedded Base field.
type Override struct {
	Base
}

func (Override) Hello() string { return "Override.Hello" }

// CountingBuffer is the real decorator: embed a *bytes.Buffer (the concrete
// implementation), override Write to count calls, and forward to the embedded
// impl explicitly. Other bytes.Buffer methods stay delegated — and, crucially,
// do NOT route through this override (the receiver is the inner *bytes.Buffer).
type CountingBuffer struct {
	*bytes.Buffer
	writeCalls int
}

// Write "overrides" the promoted bytes.Buffer.Write for DIRECT calls on a
// *CountingBuffer. It explicitly forwards to c.Buffer.Write (the embedded impl).
func (c *CountingBuffer) Write(p []byte) (int, error) {
	c.writeCalls++
	return c.Buffer.Write(p)
}

// --- section E: embedding an interface as a delegate field ------------------

// Decoder embeds an INTERFACE (io.Reader), not a struct. The embedded field is
// named "Reader" and its zero value is nil. Methods are promoted, so d.Read(p)
// compiles — but calling it while the field is nil is a runtime panic (spec
// Selectors rule 6). This is the delegate/middleware shape used throughout the
// standard library (e.g. a wrapper embedding http.Handler).
type Decoder struct {
	io.Reader
}

// --- section F: selector-depth conflict resolution --------------------------

// Alpha and Beta both expose a same-named method Name(). Embedding BOTH in one
// struct makes the bare selector s.Name() AMBIGUOUS at the same depth.
type Alpha struct{}

func (Alpha) Name() string { return "Alpha" }

type Beta struct{}

func (Beta) Name() string { return "Beta" }

// Ambiguous embeds Alpha and Beta; both promote Name() at depth 1. The bare
// selector a.Name() is ILLEGAL (compile error); only a.Alpha.Name() /
// a.Beta.Name() disambiguate.
type Ambiguous struct {
	Alpha
	Beta
}

// Shadowed adds its OWN Name() at depth 0. The shallowest-depth rule then
// makes s.Name() legal and unambiguous: depth 0 (Shadowed.Name) wins, and the
// two depth-1 candidates are silently shadowed (no error).
type Shadowed struct {
	Alpha
	Beta
}

func (Shadowed) Name() string { return "Shadowed" }

// methodNames returns the (reflect-sorted) method names of a reflect.Type.
// reflect's Method(i) is deterministic, so output is byte-stable.
func methodNames(t reflect.Type) []string {
	names := make([]string, 0, t.NumMethod())
	for i := 0; i < t.NumMethod(); i++ {
		names = append(names, t.Method(i).Name)
	}
	return names
}

// panicsWithValue runs f under a recover and reports whether it panicked plus
// the recovered value's string form. It lets Section E demonstrate a nil-deref
// panic WITHOUT taking down the whole program (so `just check` stays green).
func panicsWithValue(f func()) (panicked bool, msg string) {
	defer func() {
		if r := recover(); r != nil {
			panicked = true
			msg = fmt.Sprint(r)
		}
	}()
	f()
	return false, ""
}

// sectionA — STRUCT EMBEDDING & PROMOTION. Server embeds Logger; the embedded
// type's fields and methods are PROMOTED to Server via selector forwarding.
// s.Log(...) and s.Logger.Log(...) both work and reach the same storage.
func sectionA() {
	sectionBanner("A — STRUCT EMBEDDING & PROMOTION (forwarding, same storage)")

	// The embedded field is named with its type name, so the literal key is
	// "Logger" (NOT the promoted field "prefix": Server{prefix:...} is illegal).
	s := Server{Logger: Logger{prefix: "[srv] "}, id: 7}
	fmt.Printf("s := Server{Logger: Logger{prefix: %q}, id: 7}\n", "[srv] ")
	fmt.Printf("s.Log(\"boot\")        == %q   (PROMOTED method, forwarded to s.Logger.Log)\n", s.Log("boot"))
	fmt.Printf("s.Logger.Log(\"boot\") == %q   (explicit selector, identical receiver)\n", s.Logger.Log("boot"))
	fmt.Printf("s.prefix (promoted)  == %q   (PROMOTED field == s.Logger.prefix)\n", s.prefix)
	fmt.Printf("s.Logger.prefix      == %q   s.id == %d (declared field)\n", s.Logger.prefix, s.id)

	// PROMOTED FIELD WRITE on an addressable struct reaches the embedded field.
	s.prefix = "[S] "
	fmt.Printf("s.prefix = \"[S] \"  ->  s.Logger.prefix == %q  (promoted write reaches embedded field)\n", s.Logger.prefix)

	// reflect proves promotion makes Log part of Server's method set.
	st := reflect.TypeOf(Server{})
	_, hasLog := st.MethodByName("Log")
	fmt.Printf("reflect: Server method set = %v  (Log PROMOTED from Logger)\n", methodNames(st))

	check("promoted method s.Log() == s.Logger.Log()", s.Log("x") == s.Logger.Log("x"))
	check("promoted field s.prefix == s.Logger.prefix", s.prefix == s.Logger.prefix)
	check("promoted write reaches the embedded field: s.Logger.prefix == \"[S] \"", s.Logger.prefix == "[S] ")
	check("reflect sees promoted Log in Server's method set", hasLog)
}

// sectionB — COMPOSITION, NOT INHERITANCE. Embedding promotes methods (so Server
// satisfies interfaces Logger's methods satisfy — the "accidental interface"),
// but it creates NO subtype relationship: a *Server is NOT a *Logger, and you
// cannot upcast. You can only reach the inner field explicitly.
func sectionB() {
	sectionBanner("B — COMPOSITION NOT INHERITANCE (no subtype polymorphism)")

	s := Server{Logger: Logger{prefix: "[srv] "}, id: 7}

	// Promotion makes Log part of Server's method set -> Server SATISFIES
	// Loggable. This is real and is the source of Go's "accidental interface".
	var lg Loggable = s // legal: Server's method set is a superset of Loggable's
	fmt.Printf("var lg Loggable = s   -> lg.Log(\"hi\") == %q   (Server SATISFIES Loggable via promotion)\n", lg.Log("hi"))
	fmt.Printf("                       %%T of lg == %T  (dynamic type is Server, not Logger)\n", lg)

	// BUT Server is NOT a Logger. There is no subtype (is-a) relationship: the
	// embedded field is an ordinary has-a field. The following are COMPILE
	// ERRORS and are deliberately NOT compiled (a file with them won't build):
	//
	//   var lp *Logger = &s   // COMPILE ERROR: cannot use &s (*Server) as *Logger
	//   var lf Logger  = s    // COMPILE ERROR: cannot use s (Server) as Logger
	fmt.Println("COMPILE ERROR (documented): var lp *Logger = &s   // *Server is NOT a *Logger (no subtype)")
	fmt.Println("COMPILE ERROR (documented): var lf Logger  = s    // Server is NOT a Logger")

	// What DOES work: reach the inner field directly. The field s.Logger is a
	// Logger; &s.Logger is a *Logger. Embedding is a field, extractable.
	var innerPtr *Logger = &s.Logger // legal: pointer to the embedded FIELD
	innerPtr.prefix = "[inner] "
	fmt.Printf("var innerPtr *Logger = &s.Logger -> innerPtr.Log(\"x\") == %q  (reach the embedded field)\n", innerPtr.Log("x"))

	check("Server satisfies Loggable via promoted Log", lg.Log("hi") == "[srv] hi")
	check("the interface value's dynamic type is Server", fmt.Sprintf("%T", lg) == "main.Server")
	check("embedded field is extractable: &s.Logger is a *Logger", innerPtr.Log("x") == "[inner] x")
}

// sectionC — INTERFACE EMBEDDING (union of method sets). An interface may embed
// other interfaces; the composite's method set is the union of theirs. This is
// exactly how io.ReadWriter = io.Reader + io.Writer is defined in io/io.go.
func sectionC() {
	sectionBanner("C — INTERFACE EMBEDDING (union of method sets)")

	// The stdlib definition (io/io.go), quoted verbatim:
	//   type ReadWriter interface {
	//       Reader
	//       Writer
	//   }
	fmt.Println("io.ReadWriter (stdlib) = interface { Reader; Writer }  // embedded union")

	// TokenReadWriter embeds TokenReader + TokenWriter. *TokenStream has BOTH
	// methods, so it satisfies the composite interface. (ReadToken is stateful,
	// so capture its value once for a stable print + check.)
	var rw TokenReadWriter = &TokenStream{}
	first := rw.ReadToken()
	fmt.Printf("var rw TokenReadWriter = &TokenStream{}\n")
	fmt.Printf("rw.ReadToken() == %q   (satisfies the embedded union)\n", first)

	t := reflect.TypeOf((*TokenReadWriter)(nil)).Elem()
	fmt.Printf("TokenReadWriter method set = %v   (UNION of ReadToken + WriteToken)\n", methodNames(t))

	// *bytes.Buffer has BOTH Read and Write, so it satisfies io.ReadWriter —
	// the canonical composite interface — exactly like TokenStream here.
	var ioRW io.ReadWriter = bytes.NewBufferString("rw")
	fmt.Printf("var ioRW io.ReadWriter = &bytes.Buffer -> %%T = %T  (stdlib composite, same shape)\n", ioRW)

	check("TokenReadWriter's method set is the union {ReadToken, WriteToken}", t.NumMethod() == 2)
	check("*TokenStream satisfies TokenReadWriter", first == "tok1")
	check("*bytes.Buffer satisfies io.ReadWriter (non-nil interface)", ioRW != nil)
}

// sectionD — THE MOCK/DECORATOR PATTERN. Embed a real implementation, override
// one method, keep the rest delegated. Two sub-points: (1) overriding only
// affects DIRECT calls on the outer type — there is no virtual dispatch, so a
// method promoted from the inner type still calls the inner's own method; (2)
// the decorator keeps satisfying the same interface as the wrapped type.
func sectionD() {
	sectionBanner("D — MOCK/DECORATOR: embed + override one (no virtual dispatch)")

	// (1) NO VIRTUAL DISPATCH. Override redeclares Hello at depth 0, so the
	// shallowest-depth rule makes o.Hello() pick Override.Hello. But o.Greet()
	// is PROMOTED from Base; its receiver is the embedded Base field, so the
	// b.Hello() inside Greet binds to Base.Hello — NOT Override.Hello.
	o := Override{}
	fmt.Printf("o.Hello()  == %q   (depth-0 Override.Hello wins on direct call)\n", o.Hello())
	fmt.Printf("o.Greet()  == %q   (Greet promoted from Base; calls Base.Hello, NOT Override.Hello)\n", o.Greet())
	fmt.Println("=> embedding has NO virtual dispatch: the receiver is always the inner type.")

	// (2) THE REAL DECORATOR. CountingBuffer embeds *bytes.Buffer, overrides
	// Write to count, and forwards explicitly. The wrapper STILL satisfies
	// io.ReadWriter (Write is its own pointer method; Read is promoted).
	cb := &CountingBuffer{Buffer: bytes.NewBufferString("seed")}
	n, _ := cb.Write([]byte("hello")) // DIRECT call -> goes through the override
	fmt.Printf("cb.Write([]byte(\"hello\")) -> n=%d, writeCalls=%d, cb.String()==%q\n", n, cb.writeCalls, cb.String())

	// A DELEGATED method (WriteString is promoted from *bytes.Buffer) writes
	// WITHOUT going through the override — its receiver is the embedded
	// *bytes.Buffer field, which has its OWN Write. So writeCalls stays put.
	cb.WriteString("!!") // delegated -> bypasses CountingBuffer.Write
	fmt.Printf("cb.WriteString(\"!!\")      -> writeCalls=%d (UNCHANGED), cb.String()==%q\n", cb.writeCalls, cb.String())

	var rw io.ReadWriter = cb // *CountingBuffer satisfies io.ReadWriter
	fmt.Printf("var rw io.ReadWriter = cb   -> %%T = %T  (decorator keeps the interface)\n", rw)

	check("direct o.Hello() picks the depth-0 override", o.Hello() == "Override.Hello")
	check("no virtual dispatch: o.Greet() still calls Base.Hello", o.Greet() == "Base.Hello")
	check("override counts direct Write calls: writeCalls == 1", cb.writeCalls == 1)
	check("delegated WriteString bypasses the override: writeCalls still 1, content appended",
		cb.writeCalls == 1 && cb.String() == "seedhello!!")
	check("*CountingBuffer satisfies io.ReadWriter", rw != nil)
}

// sectionE — EMBEDDING AN INTERFACE AS A DELEGATE FIELD. A struct may embed an
// interface (not a struct): the embedded field's zero value is nil, its methods
// are promoted, and calling a method while the field is nil is a runtime panic
// (spec Selectors rule 6). This is the middleware/delegate shape: assign the
// field before use.
func sectionE() {
	sectionBanner("E — EMBEDDING AN INTERFACE: delegate field + the nil-deref trap")

	// Zero value: the embedded io.Reader field "Reader" is nil (interface zero).
	var d Decoder
	fmt.Printf("var d Decoder  ->  d.Reader == %v  (embedded INTERFACE field is nil by default)\n", d.Reader)

	// Calling Read while the field is nil is a RUNTIME PANIC (spec rule 6).
	panicked, msg := panicsWithValue(func() { _, _ = d.Read(make([]byte, 1)) })
	fmt.Printf("d.Read(buf) with nil Reader -> panicked=%v, msg=%q\n", panicked, msg)

	// THE FIX: assign the delegate field first, then the promoted method works.
	d.Reader = strings.NewReader("hi")
	buf := make([]byte, 2)
	k, _ := d.Read(buf)
	fmt.Printf("d.Reader = strings.NewReader(\"hi\"); d.Read(buf) -> n=%d, data=%q\n", k, buf)

	var d0 Decoder
	check("fresh Decoder's embedded io.Reader is nil", d0.Reader == nil)
	check("calling Read on a nil embedded interface panics", panicked && msg != "")
	check("after assigning the field, the promoted Read works", string(buf) == "hi")
}

// sectionF — NAME CONFLICTS & SELECTOR DEPTH. Two embedded types promoting a
// same-named method at the SAME depth make the bare selector AMBIGUOUS (compile
// error); you must disambiguate via the explicit selector. A shallower method
// (declared on the outer type, depth 0) SHADOWS deeper ones with no error.
func sectionF() {
	sectionBanner("F — NAME CONFLICTS: same-depth ambiguity vs shallowest-wins")

	// SAME-DEPTH conflict: both Alpha and Beta promote Name() at depth 1.
	// a.Name() is a COMPILE ERROR (ambiguous selector). The explicit selectors
	// a.Alpha.Name() / a.Beta.Name() are the only legal spellings.
	a := Ambiguous{}
	fmt.Printf("Ambiguous embeds Alpha + Beta (both Name() at depth 1)\n")
	fmt.Printf("a.Alpha.Name() == %q   a.Beta.Name() == %q   (explicit selectors disambiguate)\n", a.Alpha.Name(), a.Beta.Name())
	// COMPILE ERROR (documented, not run):
	//   a.Name()   // ambiguous selector a.Name
	fmt.Println("COMPILE ERROR (documented): a.Name()   // ambiguous selector (same depth)")

	// SHALLOWEST-WINS: Shadowed adds its OWN Name() at depth 0. The two
	// depth-1 candidates are shadowed; s.Name() is legal and picks depth 0.
	s := Shadowed{}
	fmt.Printf("Shadowed embeds Alpha + Beta AND declares its own Name() at depth 0\n")
	fmt.Printf("s.Name() == %q   (depth-0 Shadowed.Name shadows both depth-1 candidates)\n", s.Name())

	check("explicit selector a.Alpha.Name() reaches Alpha", a.Alpha.Name() == "Alpha")
	check("explicit selector a.Beta.Name() reaches Beta", a.Beta.Name() == "Beta")
	check("shallowest-depth wins: s.Name() == Shadowed.Name() (depth 0)", s.Name() == "Shadowed")
}

func main() {
	fmt.Println("embedding_composition.go — Phase 2 bundle #14.")
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
