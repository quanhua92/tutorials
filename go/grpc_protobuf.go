//go:build ignore

// grpc_protobuf.go — Phase 6 bundle.
//
// GOAL (one line): show, by printing every byte, how the protobuf WIRE FORMAT
// encodes messages (varints, tags, length-delimited fields, unknown-field
// skipping) via google.golang.org/protobuf/encoding/protowire — the foundation
// under gRPC — then contrast its size against JSON.
//
// This is the GROUND TRUTH for GRPC_PROTOBUF.md. Every byte sequence, decoded
// value, and size below is produced by this file; the .md guide pastes it
// verbatim. Nothing is hand-computed. Determinism is total: we print only byte
// slices (stable), hex strings (stable), decoded integers/strings (stable),
// and byte lengths (stable). No map iteration, no goroutines, no time.Now()
// printed values, no RNG.
//
// RUNNABLE CORE: the protobuf wire format via protowire (no protoc codegen
// needed — protowire lets you manually encode/decode the raw bytes). gRPC's RPC
// mechanics (proto3 syntax, the 4 RPC kinds, interceptors, HTTP/2 transport,
// the protoc codegen pipeline) are DOCUMENTED in the .md as "workflow" — they
// require protoc + the grpc package, which are out of scope for a single
// runnable file.
//
// Run:
//
//	go run grpc_protobuf.go

package main

import (
	"fmt"
	"strings"

	"google.golang.org/protobuf/encoding/protowire"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

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

// hexFmt returns a space-separated hex string of a byte slice, e.g. "08 96 01".
// Used for every printed byte sequence so the output is byte-stable and
// human-readable (the canonical representation of a wire-format payload).
func hexFmt(b []byte) string {
	parts := make([]string, len(b))
	for i, v := range b {
		parts[i] = fmt.Sprintf("%02x", v)
	}
	return strings.Join(parts, " ")
}

// sectionA pins VARINT encoding: the atom of the entire wire format. A varint
// stores an unsigned integer in 7-bit groups, least-significant group first,
// with the high bit (MSB) of each byte set iff another byte follows. 150 is
// THE classic example from protobuf.dev ("A Simple Message"): it encodes to two
// bytes 0x96 0x01.
func sectionA() {
	sectionBanner("A — Varint encoding (the 7-bit-grouped atom)")

	// protowire.AppendVarint appends the varint encoding of v to b. Passing nil
	// gives us the bare encoding of the single value.
	one := protowire.AppendVarint(nil, 1)
	hundredFifty := protowire.AppendVarint(nil, 150)
	large := protowire.AppendVarint(nil, 300)

	fmt.Printf("AppendVarint(nil, 1)   = %s   (%d byte)\n", hexFmt(one), len(one))
	fmt.Printf("AppendVarint(nil, 150) = %s   (%d bytes)\n", hexFmt(hundredFifty), len(hundredFifty))
	fmt.Printf("AppendVarint(nil, 300) = %s   (%d bytes)\n", hexFmt(large), len(large))

	// SizeVarint reports the encoded length WITHOUT allocating. It must agree
	// with the real append.
	fmt.Printf("SizeVarint(150) = %d (must equal the real length)\n", protowire.SizeVarint(150))

	// Decode the bytes back. ConsumeVarint returns (value, numBytesConsumed);
	// a NEGATIVE n signals a parse error (see protowire.ParseError).
	val, n := protowire.ConsumeVarint(hundredFifty)
	fmt.Printf("ConsumeVarint(%s) = %d, consumed %d bytes\n", hexFmt(hundredFifty), val, n)

	// The bit-level view of 150 -> 96 01. The continuation bit (MSB=1) on the
	// first byte says "another byte follows"; both bytes contribute 7 payload
	// bits, little-endian: 0x16 | (0x01 << 7) = 22 + 128 = 150.
	fmt.Println("bit view of 150:")
	fmt.Println("  byte0 = 0x96 = 1001_0110  (MSB=1 -> more bytes follow; payload = 001_0110 = 22)")
	fmt.Println("  byte1 = 0x01 = 0000_0001  (MSB=0 -> last byte;     payload = 000_0001 = 1)")
	fmt.Println("  value = byte0_payload + byte1_payload<<7 = 22 + 128 = 150")

	check("AppendVarint(nil, 150) == [0x96, 0x01]",
		bytesEqual(hundredFifty, 0x96, 0x01))
	check("AppendVarint(nil, 1) == [0x01]",
		bytesEqual(one, 0x01))
	check("SizeVarint(150) == 2", protowire.SizeVarint(150) == 2)
	check("ConsumeVarint decodes 150 back", val == 150 && n == 2)
	check("ConsumeVarint consumed the whole slice", n == len(hundredFifty))
}

// sectionB pins TAG construction: every field record begins with a tag varint
// that packs the field number and the wire type into one integer via
// (field_number << 3) | wire_type. Field 1 + VarintType(0) -> 0x08, THE first
// byte of protobuf.dev's canonical "08 96 01" message.
func sectionB() {
	sectionBanner("B — Tag = (field_number << 3) | wire_type")

	// EncodeTag computes the tag integer; AppendTag varint-encodes it. The low 3
	// bits of the tag are the wire type; the rest is the field number.
	tagField1Varint := protowire.AppendTag(nil, 1, protowire.VarintType)
	tagField2Bytes := protowire.AppendTag(nil, 2, protowire.BytesType)
	tagField15Varint := protowire.AppendTag(nil, 15, protowire.VarintType)

	fmt.Printf("AppendTag(nil, 1, VarintType) = %s   (field 1, wire type 0)\n", hexFmt(tagField1Varint))
	fmt.Printf("AppendTag(nil, 2, BytesType)  = %s   (field 2, wire type 2)\n", hexFmt(tagField2Bytes))
	fmt.Printf("AppendTag(nil, 15, VarintType) = %s  (field 15, wire type 0)\n", hexFmt(tagField15Varint))

	// The math, exposed by EncodeTag and DecodeTag:
	//   tag(1, VarintType) = (1 << 3) | 0 = 8   -> varint-encodes to 0x08
	//   tag(2, BytesType)  = (2 << 3) | 2 = 18  -> varint-encodes to 0x12
	fmt.Printf("EncodeTag(1, VarintType) = %d  ((1<<3)|0 = 8)\n", protowire.EncodeTag(1, protowire.VarintType))
	fmt.Printf("EncodeTag(2, BytesType)  = %d  ((2<<3)|2 = 18)\n", protowire.EncodeTag(2, protowire.BytesType))

	// DecodeTag splits a tag integer back into (field number, wire type).
	num, typ := protowire.DecodeTag(protowire.EncodeTag(2, protowire.BytesType))
	fmt.Printf("DecodeTag(EncodeTag(2, BytesType)) = field %d, wire type %d\n", num, typ)

	// ConsumeTag parses a tag directly from the byte stream.
	fnum, ftyp, n := protowire.ConsumeTag(tagField1Varint)
	fmt.Printf("ConsumeTag(%s) = field %d, wire type %d, consumed %d\n",
		hexFmt(tagField1Varint), fnum, ftyp, n)

	check("AppendTag(nil, 1, VarintType) == [0x08]",
		bytesEqual(tagField1Varint, 0x08))
	check("tag byte 0x08: wire type = 0x08 & 0x7 == 0", tagField1Varint[0]&0x7 == 0)
	check("tag byte 0x08: field number = 0x08 >> 3 == 1", tagField1Varint[0]>>3 == 1)
	check("AppendTag(nil, 2, BytesType) == [0x12]",
		bytesEqual(tagField2Bytes, 0x12))
	check("EncodeTag(1, VarintType) == 8", protowire.EncodeTag(1, protowire.VarintType) == 8)
	check("DecodeTag round-trips field number", num == 2)
	check("DecodeTag round-trips wire type", typ == protowire.BytesType)
	check("ConsumeTag recovers field 1 / VarintType", fnum == 1 && ftyp == protowire.VarintType && n == 1)
}

// sectionC performs a FULL MESSAGE round-trip: encode {field1=150 (varint),
// field2="hello" (length-delimited)} by hand with protowire, then decode it
// field-by-field and assert the decoded values match. This is the canonical
// TLV (tag-length-value) structure every protobuf message follows.
func sectionC() {
	sectionBanner("C — Full message round-trip (tag-value field by field)")

	// ENCODE: a protobuf message is just the concatenation of field records.
	// Field 1 (varint) = 150: tag(1,Varint) + varint(150).
	// Field 2 (bytes)  = "hello": tag(2,Bytes) + len(5) + "hello".
	msg := protowire.AppendTag(nil, 1, protowire.VarintType)
	msg = protowire.AppendVarint(msg, 150)
	msg = protowire.AppendTag(msg, 2, protowire.BytesType)
	msg = protowire.AppendString(msg, "hello")

	fmt.Printf("encoded message = %s\n", hexFmt(msg))
	fmt.Printf("  08       = tag: field 1, wire type 0 (varint)\n")
	fmt.Printf("  96 01    = varint payload: 150\n")
	fmt.Printf("  12       = tag: field 2, wire type 2 (length-delimited)\n")
	fmt.Printf("  05       = length prefix: 5 bytes follow\n")
	fmt.Printf("  68 65 6c 6c 6f = UTF-8 bytes of \"hello\"\n")
	fmt.Printf("total length: %d bytes\n", len(msg))

	// DECODE field by field, exactly as a generated parser would.
	rest := msg
	var field1Val uint64
	var field2Val string
	var saw1, saw2 bool

	for len(rest) > 0 {
		num, typ, tn := protowire.ConsumeTag(rest)
		rest = rest[tn:]
		// ConsumeFieldValue consumes the value (without the tag) and returns the
		// number of bytes it occupied; a negative n is a parse error.
		vn := protowire.ConsumeFieldValue(num, typ, rest)
		raw := rest[:vn]

		switch {
		case num == 1 && typ == protowire.VarintType:
			field1Val, _ = protowire.ConsumeVarint(raw)
			saw1 = true
			fmt.Printf("decoded field %d (varint)   = %d\n", num, field1Val)
		case num == 2 && typ == protowire.BytesType:
			field2Val, _ = protowire.ConsumeString(raw)
			saw2 = true
			fmt.Printf("decoded field %d (bytes)    = %q\n", num, field2Val)
		default:
			fmt.Printf("decoded field %d (type %d)  = skipped (unknown to this parser)\n", num, typ)
		}
		rest = rest[vn:]
	}

	// ConsumeField is a higher-level helper: it parses a WHOLE field record
	// (tag + value) in one call and returns (number, type, totalLength). This is
	// what you'd loop over to walk every field without caring about its value.
	rest = msg
	fmt.Println("ConsumeField walk (number, type, total length):")
	for len(rest) > 0 {
		num, typ, n := protowire.ConsumeField(rest)
		fmt.Printf("  field %d, wire type %d, record length %d\n", num, typ, n)
		rest = rest[n:]
	}

	check("encoded message is exactly 08 96 01 12 05 68 65 6c 6c 6f",
		bytesEqual(msg, 0x08, 0x96, 0x01, 0x12, 0x05, 0x68, 0x65, 0x6c, 0x6c, 0x6f))
	check("round-trip: field 1 decoded == 150", saw1 && field1Val == 150)
	check("round-trip: field 2 decoded == \"hello\"", saw2 && field2Val == "hello")
	check("message total length == 10", len(msg) == 10)
}

// sectionD enumerates the WIRE TYPES: the low 3 bits of every tag. The parser
// uses them to know how long the payload is, which is what lets old parsers
// skip unknown fields. We encode one field of each type and assert the wire-type
// bits.
func sectionD() {
	sectionBanner("D — Wire types (the low 3 bits of every tag)")

	// The six wire types (groups 3/4 are deprecated):
	//   0 VarintType     - int32/int64/uint32/uint64/sint*/bool/enum
	//   1 Fixed64Type    - fixed64/sfixed64/double (8 raw bytes, little-endian)
	//   2 BytesType      - string/bytes/embedded message/packed repeated
	//   5 Fixed32Type    - fixed32/sfixed32/float (4 raw bytes, little-endian)
	// (3 StartGroupType / 4 EndGroupType are deprecated; we do not use them.)
	types := []struct {
		name string
		typ  protowire.Type
	}{
		{"VarintType(0)", protowire.VarintType},
		{"Fixed64Type(1)", protowire.Fixed64Type},
		{"BytesType(2)", protowire.BytesType},
		{"Fixed32Type(5)", protowire.Fixed32Type},
	}

	fmt.Println("field 1, each wire type -> tag byte and extracted wire-type bits:")
	for _, t := range types {
		tag := protowire.AppendTag(nil, 1, t.typ)
		wireBits := tag[0] & 0x7
		fmt.Printf("  %-16s tag byte=0x%02x  tag&0x7=%d  (== %d? %v)\n",
			t.name, tag[0], wireBits, t.typ, wireBits == byte(t.typ))
	}

	// Show the actual payload encoding of a fixed64 (8 raw bytes) and a
	// fixed32 (4 raw bytes), contrasted with varint's variable length.
	f64 := protowire.AppendTag(nil, 3, protowire.Fixed64Type)
	f64 = protowire.AppendFixed64(f64, 0x0102030405060708)
	f32 := protowire.AppendTag(nil, 4, protowire.Fixed32Type)
	f32 = protowire.AppendFixed32(f32, 0x01020304)
	fmt.Printf("fixed64 field 3 = 0x0102030405060708 -> %s  (tag + 8 raw LE bytes)\n", hexFmt(f64))
	fmt.Printf("fixed32 field 4 = 0x01020304         -> %s  (tag + 4 raw LE bytes)\n", hexFmt(f32))

	// The fixed values are stored little-endian: 08 07 06 05 04 03 02 01.
	check("VarintType tag & 0x7 == 0",
		protowire.AppendTag(nil, 1, protowire.VarintType)[0]&0x7 == 0)
	check("Fixed64Type tag & 0x7 == 1",
		protowire.AppendTag(nil, 1, protowire.Fixed64Type)[0]&0x7 == 1)
	check("BytesType tag & 0x7 == 2",
		protowire.AppendTag(nil, 1, protowire.BytesType)[0]&0x7 == 2)
	check("Fixed32Type tag & 0x7 == 5",
		protowire.AppendTag(nil, 1, protowire.Fixed32Type)[0]&0x7 == 5)
	check("fixed64 payload is 8 bytes little-endian",
		bytesEqual(f64, 0x19, 0x08, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01))
	check("fixed32 payload is 4 bytes little-endian",
		bytesEqual(f32, 0x25, 0x04, 0x03, 0x02, 0x01))
}

// sectionE demonstrates BACKWARDS/FORWARDS COMPATIBILITY: the killer feature of
// the wire format. A parser that does not know about a field SKIPS it (using the
// wire type to compute its length) rather than erroring. We encode a message
// with a "future" field (number 99) interspersed, and decode ONLY the fields the
// parser knows (1 and 2) — the unknown field is silently skipped.
func sectionE() {
	sectionBanner("E — Unknown fields are SKIPPED (forward/backward compat)")

	// Encode {1:150, 99:999 (unknown to an old parser), 2:"hello"}. Field 99
	// simulates a field added in a NEWER .proto that an OLDER parser has never
	// seen. The older parser must still recover fields 1 and 2 intact.
	msg := protowire.AppendTag(nil, 1, protowire.VarintType)
	msg = protowire.AppendVarint(msg, 150)
	msg = protowire.AppendTag(msg, 99, protowire.VarintType) // "future" field
	msg = protowire.AppendVarint(msg, 999)
	msg = protowire.AppendTag(msg, 2, protowire.BytesType)
	msg = protowire.AppendString(msg, "hello")

	fmt.Printf("message with unknown field 99 = %s\n", hexFmt(msg))

	// Decode with a parser that only knows fields 1 and 2. The wire type lets it
	// compute the length of field 99's payload and skip over it.
	knownFields := map[protowire.Number]bool{1: true, 2: true}
	rest := msg
	var field1Val uint64
	var field2Val string
	skippedCount := 0
	for len(rest) > 0 {
		num, typ, tn := protowire.ConsumeTag(rest)
		rest = rest[tn:]
		vn := protowire.ConsumeFieldValue(num, typ, rest)
		raw := rest[:vn]
		if knownFields[num] {
			switch num {
			case 1:
				field1Val, _ = protowire.ConsumeVarint(raw)
			case 2:
				field2Val, _ = protowire.ConsumeString(raw)
			}
			fmt.Printf("  field %2d: KNOWN -> decoded\n", num)
		} else {
			skippedCount++
			fmt.Printf("  field %2d: unknown -> SKIPPED (%d bytes, wire type %d)\n", num, vn, typ)
		}
		rest = rest[vn:]
	}
	fmt.Printf("decoded field 1 = %d, field 2 = %q, skipped %d unknown field(s)\n",
		field1Val, field2Val, skippedCount)

	check("unknown field 99 skipped, field 1 still == 150", field1Val == 150)
	check("unknown field 99 skipped, field 2 still == \"hello\"", field2Val == "hello")
	check("exactly 1 unknown field was skipped", skippedCount == 1)
}

// sectionF contrasts PROTOBUF size against JSON for the same logical payload.
// Protobuf's typed, compact wire format (varints, no field NAMES, no braces or
// quotes) beats JSON's text format on the wire — the core size/perf argument
// for gRPC over REST/JSON.
func sectionF() {
	sectionBanner("F — Protobuf vs JSON size (the compactness argument)")

	// Same logical data: {id: 150, name: "hello"}.
	// Protobuf: tag+varint + tag+len+bytes (no field names, no punctuation).
	pbMsg := protowire.AppendTag(nil, 1, protowire.VarintType)
	pbMsg = protowire.AppendVarint(pbMsg, 150)
	pbMsg = protowire.AppendTag(pbMsg, 2, protowire.BytesType)
	pbMsg = protowire.AppendString(pbMsg, "hello")

	// JSON: human-readable but carries the field NAMES ("id", "name") plus
	// braces, colons, and quotes on every field.
	jsonMsg := []byte(`{"id":150,"name":"hello"}`)

	fmt.Printf("protobuf = %s\n", hexFmt(pbMsg))
	fmt.Printf("  length: %d bytes\n", len(pbMsg))
	fmt.Printf("json     = %s\n", string(jsonMsg))
	fmt.Printf("  length: %d bytes\n", len(jsonMsg))
	fmt.Printf("protobuf is %d bytes smaller (%.0f%% of the JSON size)\n",
		len(jsonMsg)-len(pbMsg),
		float64(len(pbMsg))/float64(len(jsonMsg))*100)

	check("protobuf is smaller than JSON for the same payload", len(pbMsg) < len(jsonMsg))
	check("protobuf == 10 bytes", len(pbMsg) == 10)
	check("json == 25 bytes", len(jsonMsg) == 25)
}

// bytesEqual compares a byte slice against a variadic list of expected byte
// values. Centralizing it keeps the checks readable and avoids per-call boilerplate.
func bytesEqual(got []byte, want ...byte) bool {
	if len(got) != len(want) {
		return false
	}
	for i := range want {
		if got[i] != want[i] {
			return false
		}
	}
	return true
}

func main() {
	fmt.Println("grpc_protobuf.go — Phase 6 bundle.")
	fmt.Println("The RUNNABLE core is the PROTOBUF WIRE FORMAT (via protowire);")
	fmt.Println("gRPC RPC mechanics (proto3, the 4 RPC kinds, interceptors,")
	fmt.Println("HTTP/2 transport, the protoc codegen pipeline) are DOCUMENTED")
	fmt.Println("in the .md. Every byte below is produced by this file; the .md")
	fmt.Println("guide pastes it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
