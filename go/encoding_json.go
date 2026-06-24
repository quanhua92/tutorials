//go:build ignore

// encoding_json.go — Phase 5 bundle.
//
// GOAL (one line): show, by printing every byte, how encoding/json marshals and
// unmarshals Go values — struct tags, custom (Un)MarshalJSON, streaming
// Encoder/Decoder, RawMessage deferred parsing, and Number precision.
//
// This is the GROUND TRUTH for ENCODING_JSON.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// Run:
//
//	go run encoding_json.go

package main

import (
	"bytes"
	"encoding/json"
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

// must unwraps a (bytes, error) pair. Marshal/Encoder.Encode never error for
// our well-formed values, so this keeps the section bodies readable; any error
// panics -> non-zero exit -> the verification sweep flags it.
func must(b []byte, err error) []byte {
	if err != nil {
		panic(err)
	}
	return b
}

// --- types used across sections ---------------------------------------------

// User has one UNEXPORTED field (email) to prove the encoder only sees exported
// fields. Unexported fields are invisible to Marshal and cannot round-trip.
type User struct {
	Name  string `json:"name"`
	Age   int    `json:"age"`
	email string // unexported: never serialized
}

// Tagged exercises every struct-tag directive asserted in section B: a renamed
// field, json:"-" to skip, omitempty to drop a zero value, and ",string" to
// force a number out as a JSON string.
type Tagged struct {
	Visible string `json:"visible"`
	Hidden  string `json:"-"`
	Age     int    `json:"age,omitempty"`
	Count   int    `json:"count,string"`
}

// Level is a type-safe enum that controls its OWN JSON form by implementing
// json.Marshaler / json.Unmarshaler. This is the pattern for enums and custom
// date/number formats.
type Level int

const (
	LevelOff Level = iota
	LevelInfo
	LevelWarn
	LevelError
)

// levelName maps a Level to its stable string form; shared by both directions.
func levelName(l Level) string {
	switch l {
	case LevelInfo:
		return "info"
	case LevelWarn:
		return "warn"
	case LevelError:
		return "error"
	default:
		return "off"
	}
}

// MarshalJSON makes Level implement json.Marshaler. It MUST emit valid JSON, so
// the inner string is wrapped with json.Marshal (which quotes it) rather than
// hand-built bytes — a custom string returned without quotes is a runtime error.
func (l Level) MarshalJSON() ([]byte, error) {
	return json.Marshal(levelName(l)) // e.g. -> "warn"  (quoted -> valid JSON string)
}

// UnmarshalJSON makes *Level implement json.Unmarshaler: parse the quoted
// string and map it back to a Level. Unknown strings collapse to LevelOff.
func (l *Level) UnmarshalJSON(data []byte) error {
	var s string
	if err := json.Unmarshal(data, &s); err != nil {
		return err
	}
	switch s {
	case "info":
		*l = LevelInfo
	case "warn":
		*l = LevelWarn
	case "error":
		*l = LevelError
	default:
		*l = LevelOff
	}
	return nil
}

// --- sections ---------------------------------------------------------------

// sectionA round-trips a struct (proving the exported-only rule) and a map
// (proving Go sorts map keys, which keeps this bundle deterministic).
func sectionA() {
	sectionBanner("A — Marshal/Unmarshal round-trip (struct + map)")

	// Struct: only EXPORTED fields are serialized. The unexported `email` is
	// invisible to the encoder, so it cannot survive a round-trip.
	u := User{Name: "Al", Age: 42, email: "secret@x.io"}
	ub := must(json.Marshal(u))
	fmt.Printf("User{Name:\"Al\", Age:42, email:\"secret@x.io\"}\n")
	fmt.Printf("  -> Marshal  = %s\n", ub)
	fmt.Println("  (note: email is unexported -> absent from JSON)")

	var u2 User
	if err := json.Unmarshal(ub, &u2); err != nil {
		panic(err)
	}
	fmt.Printf("  -> Unmarshal = %+v  (email stayed zero: %q)\n", u2, u2.email)

	check(`Marshal(User) == {"name":"Al","age":42}`, string(ub) == `{"name":"Al","age":42}`)
	check("round-trip: Name preserved", u2.Name == "Al")
	check("round-trip: Age preserved", u2.Age == 42)
	check("round-trip: unexported email is lost (zero value)", u2.email == "")

	// Map: Go SORTS the keys alphabetically when marshaling, so the output is
	// deterministic even though map ITERATION order is randomized. This rule is
	// what keeps this bundle's _output.txt byte-identical across runs.
	m := map[string]int{"zulu": 1, "alpha": 2, "mike": 3}
	mb := must(json.Marshal(m))
	fmt.Printf("\nmap[string]int{\"zulu\":1,\"alpha\":2,\"mike\":3}\n")
	fmt.Printf("  -> Marshal  = %s   (keys sorted: alpha,mike,zulu)\n", mb)
	check("map keys sorted alphabetically", string(mb) == `{"alpha":2,"mike":3,"zulu":1}`)
}

// sectionB pins the struct-tag directives: omitempty drops a zero value, "-"
// always skips a field, and ",string" forces a number out as a JSON string.
func sectionB() {
	sectionBanner("B — Struct tags: omitempty, \"-\", and \",string\"")

	t := Tagged{Visible: "hi", Hidden: "TOP SECRET", Age: 0, Count: 7}
	tb := must(json.Marshal(t))
	fmt.Printf("Tagged{Visible:\"hi\", Hidden:\"TOP SECRET\", Age:0, Count:7}\n")
	fmt.Printf("  -> Marshal  = %s\n", tb)
	fmt.Println("  (Age omitempty'd at 0; Hidden skipped via \"-\"; Count emitted as a string)")

	check(`omitempty dropped Age (zero value)`, !strings.Contains(string(tb), "age"))
	check(`json:"-" skipped Hidden`, !strings.Contains(string(tb), "TOP SECRET"))
	check(`",string" emitted Count as a string`, strings.Contains(string(tb), `"count":"7"`))
	check(`exact bytes`, string(tb) == `{"visible":"hi","count":"7"}`)
}

// sectionC shows a type driving its own serialization via MarshalJSON/
// UnmarshalJSON, plus the nil-pointer exception (Marshal skips MarshalJSON for
// a nil pointer and writes null instead).
func sectionC() {
	sectionBanner("C — Custom MarshalJSON: a type controls its own form")

	// LogItem embeds a Level, which implements json.Marshaler. The encoder
	// calls Level.MarshalJSON automatically, turning the int into "warn".
	type LogItem struct {
		Level Level  `json:"level"`
		Msg   string `json:"msg"`
	}
	item := LogItem{Level: LevelWarn, Msg: "disk 90%"}
	ib := must(json.Marshal(item))
	fmt.Printf("LogItem{Level:LevelWarn, Msg:\"disk 90%%\"}\n")
	fmt.Printf("  -> Marshal  = %s   (Level emitted as the quoted string \"warn\")\n", ib)
	check(`custom MarshalJSON: level == "warn"`, string(ib) == `{"level":"warn","msg":"disk 90%"}`)

	// Round-trip through the custom UnmarshalJSON: "warn" decodes to LevelWarn.
	var back LogItem
	if err := json.Unmarshal(ib, &back); err != nil {
		panic(err)
	}
	fmt.Printf("  -> Unmarshal = %+v  (\"warn\" decoded back to LevelWarn)\n", back)
	check("custom UnmarshalJSON round-trips LevelWarn", back.Level == LevelWarn)

	// The nil-pointer exception (the expert detail): "If an encountered value
	// implements Marshaler and is not a nil pointer, Marshal calls
	// MarshalJSON." A nil *Level serializes as null and does NOT invoke our
	// method — the sentinel "off" default never fires by itself.
	var pLevel *Level // nil
	pb := must(json.Marshal(pLevel))
	fmt.Println("\nvar pLevel *Level // nil")
	fmt.Printf("  -> Marshal(nil *Level) = %s   (null; MarshalJSON NOT called)\n", pb)
	check("nil *Level marshals to null (MarshalJSON skipped)", string(pb) == "null")
}

// sectionD contrasts the streaming Encoder/Decoder against Marshal/Unmarshal:
// Encode appends a newline; HTML escaping is controllable only on the Encoder;
// a Decoder consumes concatenated JSON values until io.EOF.
func sectionD() {
	sectionBanner("D — Streaming Encoder/Decoder vs Marshal/Unmarshal")

	// Encoder.Encode writes JSON to a stream (io.Writer) and appends a NEWLINE.
	// Marshal returns the bytes with no newline. For the same value, Encode's
	// output is exactly Marshal's output + "\n".
	v := struct {
		Msg string `json:"msg"`
	}{Msg: "<b>hi&bye</b>"}

	marshaled := must(json.Marshal(v))
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	must(nil, enc.Encode(v)) // Encode returns an error; route it through must
	streamed := buf.Bytes()

	fmt.Printf("value: {Msg:\"<b>hi&bye</b>\"}\n")
	fmt.Printf("  Marshal        = %s\n", marshaled)
	fmt.Printf("  Encoder.Encode = %s", streamed) // streamed already ends in '\n'
	fmt.Println("   ^ note Encode added a trailing newline that Marshal does not")
	check("Encode output ends with newline", streamed[len(streamed)-1] == '\n')
	check("Encode (minus newline) == Marshal output",
		bytes.Equal(streamed[:len(streamed)-1], marshaled))

	// HTML escaping (<,>,& -> \u003c,\u003e,\u0026) is ON by default for BOTH
	// Marshal and Encode. Only the Encoder can turn it OFF (Marshal cannot).
	var buf2 bytes.Buffer
	enc2 := json.NewEncoder(&buf2)
	enc2.SetEscapeHTML(false)
	must(nil, enc2.Encode(v))
	fmt.Printf("\n  Encoder.SetEscapeHTML(false) = %s", buf2.Bytes())
	fmt.Println("   ^ raw <,>,& preserved; Marshal has no way to do this")
	check("SetEscapeHTML(false) keeps raw angle brackets/ampersand",
		bytes.Equal(buf2.Bytes(), []byte(`{"msg":"<b>hi&bye</b>"}`+"\n")))

	// Streaming DECODE: a Decoder reads JSON values one at a time from a reader
	// (no need to buffer the whole input). Concatenated values decode in order
	// until io.EOF. This is the pattern for reading a stream of NDJSON/JSONL.
	stream := `{"id":1}` + "\n" + `{"id":2}` + "\n" + `{"id":3}`
	dec := json.NewDecoder(strings.NewReader(stream))
	var ids []int
	for {
		var msg struct {
			ID int `json:"id"`
		}
		if err := dec.Decode(&msg); err != nil { // nil until io.EOF
			break
		}
		ids = append(ids, msg.ID)
	}
	fmt.Printf("\nstream of 3 concatenated JSON objects -> decoded IDs: %v\n", ids)
	check("streaming Decoder read all 3 in order", fmt.Sprint(ids) == "[1 2 3]")
}

// sectionE shows json.RawMessage: capture a sub-field's raw bytes WITHOUT
// parsing, then decode it into the right concrete type once you know the shape.
// This is the basis for polymorphic JSON (one field, many possible shapes).
func sectionE() {
	sectionBanner("E — json.RawMessage: defer parsing of a sub-field")

	type Envelope struct {
		Type string          `json:"type"`
		Data json.RawMessage `json:"data"`
	}
	type RGB struct {
		R uint8 `json:"r"`
		G uint8 `json:"g"`
		B uint8 `json:"b"`
	}
	type Reading struct {
		Temp float64 `json:"temp"`
	}

	// First envelope: data is an RGB object.
	blob := []byte(`{"type":"rgb","data":{"r":98,"g":218,"b":255}}`)
	var env Envelope
	if err := json.Unmarshal(blob, &env); err != nil {
		panic(err)
	}
	fmt.Printf("input: {\"type\":\"rgb\",\"data\":{...}}\n")
	fmt.Printf("  envelope.Type = %q\n", env.Type)
	fmt.Printf("  envelope.Data = %s   (still raw bytes; not yet parsed)\n", env.Data)

	// Decode Data according to Type. Each branch targets a different struct.
	switch env.Type {
	case "rgb":
		var c RGB
		if err := json.Unmarshal(env.Data, &c); err != nil {
			panic(err)
		}
		fmt.Printf("  decoded as RGB      -> %+v\n", c)
		check("RawMessage: RGB decoded with exact channels", c.R == 98 && c.G == 218 && c.B == 255)
	case "reading":
		var r Reading
		if err := json.Unmarshal(env.Data, &r); err != nil {
			panic(err)
		}
		fmt.Printf("  decoded as Reading  -> %+v\n", r)
	}

	// Same Envelope type, different inner shape: data is a sensor reading.
	blob2 := []byte(`{"type":"reading","data":{"temp":36.6}}`)
	var env2 Envelope
	if err := json.Unmarshal(blob2, &env2); err != nil {
		panic(err)
	}
	fmt.Printf("\ninput: {\"type\":\"reading\",\"data\":{\"temp\":36.6}}\n")
	fmt.Printf("  envelope.Data = %s\n", env2.Data)
	var r Reading
	if err := json.Unmarshal(env2.Data, &r); err != nil {
		panic(err)
	}
	fmt.Printf("  decoded as Reading  -> %+v\n", r)
	check("RawMessage: second envelope parsed as Reading", r.Temp == 36.6)
	check("RawMessage kept bytes verbatim (deferred, not float64)", string(env.Data) == `{"r":98,"g":218,"b":255}`)
}

// sectionF pins two things at once: (1) a JSON number decoded into interface{}
// becomes float64, which drifts for integers above 2^53 — use json.Number via
// Decoder.UseNumber() to keep exact digits; (2) map[string]any is the flexible
// "dynamic JSON" form, at the cost of runtime type assertions.
func sectionF() {
	sectionBanner("F — json.Number vs float64 (precision) & dynamic JSON")

	// 2^53+1 cannot be represented exactly in float64 (53 bits of significand).
	// Decoding it into interface{} yields float64, which DRIFTS. UseNumber()
	// preserves the exact literal digits as json.Number.
	const exact int64 = 9007199254740993 // 2^53 + 1
	payload := []byte(`{"id":9007199254740993}`)

	// (1) Default decode -> float64 (precision lost).
	var def map[string]any
	if err := json.Unmarshal(payload, &def); err != nil {
		panic(err)
	}
	f := def["id"].(float64)
	fmt.Printf("input: {\"id\":9007199254740993}   (2^53 + 1)\n")
	fmt.Printf("  default decode   -> float64 = %v   -> int64 = %d   (DRIFTED)\n", f, int64(f))

	// (2) Decoder.UseNumber -> json.Number (exact digits preserved).
	var num map[string]any
	dec := json.NewDecoder(bytes.NewReader(payload))
	dec.UseNumber()
	if err := dec.Decode(&num); err != nil {
		panic(err)
	}
	n := num["id"].(json.Number)
	got, _ := n.Int64()
	fmt.Printf("  UseNumber decode -> json.Number = %s   -> int64 = %d   (EXACT)\n", n, got)

	check("float64 path drifted (precision lost)", int64(f) != exact)
	check("json.Number path preserved exact int64", got == exact)
	check("json.Number.String() is the literal text", n.String() == "9007199254740993")

	// Dynamic JSON: map[string]any trades type safety for flexibility. Every
	// number becomes float64, every object becomes map[string]any, every array
	// becomes []any — each access needs a runtime type assertion.
	dyn := map[string]any{
		"name":   "Al",
		"active": true,
		"tags":   []any{"go", "json"},
		"meta":   map[string]any{"n": 1},
	}
	db := must(json.Marshal(dyn))
	fmt.Printf("\ndynamic map[string]any -> Marshal = %s\n", db)
	fmt.Println("  (flexible, but every access needs a type assertion; numbers are float64)")
	check("dynamic JSON marshals (keys sorted)", string(db) ==
		`{"active":true,"meta":{"n":1},"name":"Al","tags":["go","json"]}`)
}

func main() {
	fmt.Println("encoding_json.go — Phase 5 bundle.")
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
