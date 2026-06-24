//go:build ignore

// request_validation.go — Phase 6 bundle.
//
// GOAL (one line): show, by printing every behavior, how to BIND a JSON request
// body into a struct (strict decode), VALIDATE it via a hand-rolled reflect-based
// struct-tag engine, COLLECT every error, and wire it into an HTTP handler that
// returns 200 or 400 — all stdlib, all offline (httptest).
//
// This is the GROUND TRUTH for REQUEST_VALIDATION.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// The ecosystem choice (go-playground/validator) is DOCUMENTED in the .md and is
// NOT imported here — we implement the patterns by hand to stay stdlib-first and
// to TEACH how a tag-driven validator works under the hood.
//
// Run:
//
//	go run request_validation.go

package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"
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

// =============================================================================
// STRICT BINDING: json.Decoder + DisallowUnknownFields + no trailing garbage
// =============================================================================

// strictDecode decodes a JSON body into dst with TWO strict-mode guarantees that
// a plain json.Unmarshal does NOT give:
//
//  1. DisallowUnknownFields: any JSON key with no matching struct field is an
//     error. The default (Unmarshal/Decoder) silently IGNORES unknown keys — a
//     classic source of typos, client/server schema drift, and (per Trail of
//     Bits) security bypasses.
//  2. No trailing garbage: after the first JSON value there must be EOF, not
//     more bytes. The streaming Decoder otherwise happily leaves trailing data
//     unread — e.g. `{"x":1}EVIL` decodes the object and stops, hiding the rest.
//
// It reads the body with a single Decoder and attempts a SECOND Decode into an
// empty value: a well-formed single-value body yields io.EOF there; anything
// else (extra bytes, a second value, garbage) is rejected.
func strictDecode(dst any, body []byte) error {
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return err
	}
	var extra struct{}
	if err := dec.Decode(&extra); err != io.EOF {
		if err == nil {
			return fmt.Errorf("unexpected trailing data after JSON value")
		}
		return fmt.Errorf("unexpected trailing data: %w", err)
	}
	return nil
}

// =============================================================================
// HAND-ROLLED VALIDATION ENGINE (reflect over `validate:"..."` struct tags)
// =============================================================================
//
// This is a tiny reimplementation of the IDEA behind go-playground/validator:
// read a struct-tag DSL with reflect, enforce each rule, collect every failure.
// Supported rules (comma-separated in the tag):
//
//	required          non-zero value (reflect Value.IsZero)
//	min=N             strings/slices: len >= N ; numbers: value >= N
//	max=N             strings/slices: len <= N ; numbers: value <= N
//	oneof=a b c       value must equal one of the space-separated options (enum)
//	email             must match a simple email regex (a "format" rule)
//	utf8              must be valid UTF-8 (unicode/utf8.Valid) — a security check
//
// min/max are TYPE-DEPENDENT (length for sequences, magnitude for numbers),
// exactly like go-playground/validator. This dual meaning is the key teaching
// point and a frequent surprise.

// emailRegex is a deliberately simple email format check. Production code should
// not roll its own — this exists to TEACH how a format rule is wired in, and to
// contrast with go-playground/validator's built-in `email` tag.
var emailRegex = regexp.MustCompile(`^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$`)

// ValidationErrors maps an offending field (by its JSON name) to a human message.
// It is nil when the value is valid. Implementing error lets a caller treat the
// whole set as one error while ranging the map for per-field detail. Multiple
// failing rules on a single field are JOINED with "; " so nothing is lost.
type ValidationErrors map[string]string

// Error renders the set as a deterministic "field: msg; field: msg" string. Map
// iteration is randomized, so keys are SORTED first — this is what keeps the
// bundle's _output.txt byte-identical across runs.
func (ve ValidationErrors) Error() string {
	if len(ve) == 0 {
		return ""
	}
	keys := make([]string, 0, len(ve))
	for k := range ve {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	var b strings.Builder
	for i, k := range keys {
		if i > 0 {
			b.WriteString("; ")
		}
		b.WriteString(k)
		b.WriteString(": ")
		b.WriteString(ve[k])
	}
	return b.String()
}

// Validate walks the exported fields of a struct, reads each `validate:"..."`
// tag, and enforces every rule by hand via reflect. Returns nil if the value is
// valid, otherwise a non-empty ValidationErrors.
func Validate(v any) ValidationErrors {
	rv := reflect.ValueOf(v)
	for rv.Kind() == reflect.Ptr && !rv.IsNil() {
		rv = rv.Elem()
	}
	if rv.Kind() != reflect.Struct {
		return nil
	}
	rt := rv.Type()
	errs := ValidationErrors{}
	for i := 0; i < rt.NumField(); i++ {
		f := rt.Field(i)
		if !f.IsExported() {
			continue
		}
		tag := f.Tag.Get("validate")
		if tag == "" || tag == "-" {
			continue
		}
		fv := rv.Field(i)
		var msgs []string
		for _, rule := range splitRules(tag) {
			if msg, fail := applyRule(rule, fv); fail {
				msgs = append(msgs, msg)
			}
		}
		if len(msgs) > 0 {
			errs[jsonName(f)] = strings.Join(msgs, "; ")
		}
	}
	if len(errs) == 0 {
		return nil
	}
	return errs
}

// applyRule enforces a single rule against a field value, returning a message
// when the rule is violated. Unknown rules are ignored (forward-compatible).
func applyRule(rule string, fv reflect.Value) (message string, failed bool) {
	key, arg, _ := strings.Cut(rule, "=")
	switch key {
	case "required":
		if fv.IsZero() {
			return "is required", true
		}
	case "min":
		if n, ok := atoi(arg); ok && belowMin(fv, n) {
			return minMsg(fv, n), true
		}
	case "max":
		if n, ok := atoi(arg); ok && aboveMax(fv, n) {
			return maxMsg(fv, n), true
		}
	case "oneof":
		opts := strings.Fields(arg)
		if !inSlice(stringOf(fv), opts) {
			return fmt.Sprintf("must be one of %v", opts), true
		}
	case "email":
		if fv.Kind() == reflect.String && !emailRegex.MatchString(fv.String()) {
			return "must be a valid email address", true
		}
	case "utf8":
		if fv.Kind() == reflect.String && !utf8.ValidString(fv.String()) {
			return "must be valid UTF-8", true
		}
	}
	return "", false
}

// --- small reflect/format helpers -------------------------------------------

func jsonName(f reflect.StructField) string {
	if jn := f.Tag.Get("json"); jn != "" && jn != "-" {
		if name, _, _ := strings.Cut(jn, ","); name != "" && name != "-" {
			return name
		}
	}
	return f.Name
}

func splitRules(tag string) []string {
	parts := strings.Split(tag, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

// lenLike reports the length for sequence kinds (string/slice/array/map).
func lenLike(fv reflect.Value) (int, bool) {
	switch fv.Kind() {
	case reflect.String, reflect.Slice, reflect.Array, reflect.Map:
		return fv.Len(), true
	}
	return 0, false
}

// numeric reports the magnitude for numeric kinds (used by min/max as a range).
func numeric(fv reflect.Value) (float64, bool) {
	switch fv.Kind() {
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		return float64(fv.Int()), true
	case reflect.Uint, reflect.Uint8, reflect.Uint16, reflect.Uint32, reflect.Uint64:
		return float64(fv.Uint()), true
	case reflect.Float32, reflect.Float64:
		return fv.Float(), true
	}
	return 0, false
}

func belowMin(fv reflect.Value, n int) bool {
	if l, ok := lenLike(fv); ok {
		return l < n
	}
	if x, ok := numeric(fv); ok {
		return x < float64(n)
	}
	return false
}

func aboveMax(fv reflect.Value, n int) bool {
	if l, ok := lenLike(fv); ok {
		return l > n
	}
	if x, ok := numeric(fv); ok {
		return x > float64(n)
	}
	return false
}

// minMsg/maxMsg produce type-aware messages so a reader sees whether the bound
// applied to LENGTH or to MAGNITUDE.
func minMsg(fv reflect.Value, n int) string {
	if _, ok := lenLike(fv); ok {
		return fmt.Sprintf("length must be >= %d", n)
	}
	return fmt.Sprintf("must be >= %d", n)
}

func maxMsg(fv reflect.Value, n int) string {
	if _, ok := lenLike(fv); ok {
		return fmt.Sprintf("length must be <= %d", n)
	}
	return fmt.Sprintf("must be <= %d", n)
}

func atoi(s string) (int, bool) {
	n, err := strconv.Atoi(strings.TrimSpace(s))
	return n, err == nil
}

func inSlice(v string, opts []string) bool {
	for _, o := range opts {
		if v == o {
			return true
		}
	}
	return false
}

func stringOf(fv reflect.Value) string {
	if fv.Kind() == reflect.String {
		return fv.String()
	}
	return fmt.Sprint(fv.Interface())
}

// --- output helpers ---------------------------------------------------------

// printErrs prints a sorted, deterministic view of an error set. Map iteration
// is randomized, so the keys are sorted first (HOW_TO_RESEARCH §4.2 rule 1).
func printErrs(label string, errs ValidationErrors) {
	if errs == nil {
		fmt.Printf("%-12s -> (valid)\n", label)
		return
	}
	keys := make([]string, 0, len(errs))
	for k := range errs {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	fmt.Printf("%-12s -> %d error(s):\n", label, len(errs))
	for _, k := range keys {
		fmt.Printf("                 %s: %s\n", k, errs[k])
	}
}

func hasKey(errs ValidationErrors, key string) bool {
	_, ok := errs[key]
	return ok
}

// =============================================================================
// SECTIONS
// =============================================================================

// CreatePost is the binding target for section A: a strict JSON decode.
type CreatePost struct {
	Title string `json:"title"`
	Body  string `json:"body"`
}

// sectionA: bind a JSON body with strict mode — DisallowUnknownFields + no
// trailing garbage. A good body decodes; an unknown field is rejected; trailing
// bytes after the value are rejected.
func sectionA() {
	sectionBanner("A — Binding: json.Decoder + DisallowUnknownFields + no trailing garbage")

	var p CreatePost

	// Good body: both known fields, nothing extra, nothing trailing.
	good := []byte(`{"title":"Hello","body":"world"}`)
	if err := strictDecode(&p, good); err != nil {
		panic(err)
	}
	fmt.Printf("good body             -> decoded: %+v\n", p)

	// Unknown field "admin": no matching struct field -> DisallowUnknownFields.
	unknown := []byte(`{"title":"Hello","body":"world","admin":true}`)
	errUnknown := strictDecode(&p, unknown)
	fmt.Printf("unknown field \"admin\" -> err: %v\n", errUnknown)

	// Trailing garbage after the JSON value -> rejected by the second Decode.
	trailing := []byte(`{"title":"Hello","body":"world"} EXTRA`)
	errTrailing := strictDecode(&p, trailing)
	fmt.Printf("trailing garbage      -> err: %v\n", errTrailing)

	check("good body decodes with no unknown fields", p.Title == "Hello" && p.Body == "world")
	check(`unknown field rejected (DisallowUnknownFields)`, errUnknown != nil)
	check("trailing garbage rejected", errTrailing != nil)
}

// Comment is the section B target: multiple rules per field (required + bounds).
type Comment struct {
	Author string `json:"author" validate:"required,min=2,max=20"`
	Text   string `json:"text"   validate:"required,min=1,max=200"`
}

// sectionB: the hand-rolled Validate engine. A fully-valid comment passes (nil
// error set); a bad one fails. This is "how a validator library works inside".
func sectionB() {
	sectionBanner("B — Hand-rolled Validate(v) via reflect struct tags")

	good := Comment{Author: "Ada", Text: "nice post"}
	errsGood := Validate(good)
	fmt.Printf("good comment -> Validate: %v   (nil == valid)\n", errsGood)

	bad := Comment{Author: "X", Text: ""} // Author len 1 < min=2; Text empty
	errsBad := Validate(bad)
	printErrs("bad comment", errsBad)

	check("good comment validates (nil error set)", errsGood == nil)
	check("bad comment fails validation (non-nil error set)", errsBad != nil)
	check("author field flagged (len 1 < min=2)", hasKey(errsBad, "author"))
	check("text field flagged (required + empty)", hasKey(errsBad, "text"))
}

// Draft exercises every rule KIND: oneof (enum), min/max as a numeric RANGE,
// and email as a format (regex) check.
type Draft struct {
	Status string `json:"status" validate:"oneof=draft published archived"`
	Age    int    `json:"age"    validate:"min=0,max=150"`
	Email  string `json:"email"  validate:"email"`
}

// sectionC: one rule kind per case, so each rule is shown failing in isolation.
func sectionC() {
	sectionBanner("C — Rule kinds: oneof (enum), min/max range (numeric), email (regex)")

	valid := Draft{Status: "draft", Age: 30, Email: "a@b.com"}
	printErrs("all-valid", Validate(valid))
	printErrs("bad-status", Validate(Draft{Status: "xyz", Age: 30, Email: "a@b.com"}))
	printErrs("bad-age", Validate(Draft{Status: "draft", Age: 200, Email: "a@b.com"}))
	printErrs("bad-email", Validate(Draft{Status: "draft", Age: 30, Email: "nope"}))

	check(`oneof: "draft" passes`, Validate(valid) == nil)
	check(`oneof: "xyz" fails`, hasKey(Validate(Draft{Status: "xyz", Age: 30, Email: "a@b.com"}), "status"))
	check("range: Age 200 > max=150 fails", hasKey(Validate(Draft{Status: "draft", Age: 200, Email: "a@b.com"}), "age"))
	check("range: Age -1 < min=0 fails", hasKey(Validate(Draft{Status: "draft", Age: -1, Email: "a@b.com"}), "age"))
	check("format: bad email fails", hasKey(Validate(Draft{Status: "draft", Age: 30, Email: "nope"}), "email"))
}

// Signup is the section D target: two DIFFERENT fields each breaking a rule, so
// the collected error set has >=2 entries (validation does not stop at first).
type Signup struct {
	Name string `json:"name" validate:"required"`
	Code string `json:"code" validate:"min=5"`
}

// sectionD: collect ALL errors, not just the first. Name="" breaks `required`;
// Code="ab" breaks `min=5` (len 2). Two offending fields -> two map entries.
func sectionD() {
	sectionBanner("D — Collect ALL errors: required + min on two fields -> >=2 entries")

	bad := Signup{Name: "", Code: "ab"}
	errs := Validate(bad)
	printErrs("signup", errs)

	check("struct violating required+min -> >=2 error entries", len(errs) >= 2)
	check("name (required) flagged", hasKey(errs, "name"))
	check("code (min=5) flagged", hasKey(errs, "code"))
}

// Note is the section E target: a UTF-8 validity rule on a string field.
type Note struct {
	Tag string `json:"tag" validate:"utf8"`
}

// sectionE: invalid UTF-8 in a string field fails validation. Invalid byte
// sequences in user input are a correctness/security bug (log injection,
// truncation, downstream parser confusion) — utf8.Valid catches them.
func sectionE() {
	sectionBanner("E — UTF-8 validity: invalid byte sequences fail validation")

	good := Note{Tag: "héllo 世界"}
	bad := Note{Tag: "bad\xff\xfe"} // 0xff/0xfe are not valid UTF-8 lead bytes
	errsGood := Validate(good)
	errsBad := Validate(bad)
	printErrs("valid-utf8", errsGood)
	printErrs("invalid-utf8", errsBad)

	check("valid UTF-8 string passes", errsGood == nil)
	check("invalid UTF-8 string fails validation", hasKey(errsBad, "tag"))
}

// =============================================================================
// HANDLER: decode + validate -> 200 or 400 (httptest, fully offline)
// =============================================================================

// Reg is the handler's request body for section F.
type Reg struct {
	Email string `json:"email" validate:"required,email"`
	Age   int    `json:"age"   validate:"min=0,max=150"`
}

// regHandler is the end-to-end pipeline: BIND (strict decode) -> VALIDATE ->
// respond. Each failure phase returns 400 with a distinct "phase" so callers
// can tell a malformed body from a semantically invalid one. On success, 200.
func regHandler(w http.ResponseWriter, r *http.Request) {
	var reg Reg
	if err := strictDecode(&reg, readAll(r.Body)); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error": "invalid JSON: " + err.Error(),
			"phase": "bind",
		})
		return
	}
	if errs := Validate(reg); errs != nil {
		writeJSON(w, http.StatusBadRequest, map[string]any{
			"error":  "validation failed",
			"phase":  "validate",
			"errors": sortedErrors(errs),
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status": "ok",
		"email":  reg.Email,
	})
}

// keyVal is a sorted error entry, marshaled as {"field":..,"message":..}. Using
// a slice (sorted) instead of a raw map makes the JSON order deterministic and
// explicit, even though json.Marshal already sorts map keys.
type keyVal struct {
	Field   string `json:"field"`
	Message string `json:"message"`
}

func sortedErrors(errs ValidationErrors) []keyVal {
	keys := make([]string, 0, len(errs))
	for k := range errs {
		keys = append(keys, k)
	}
	slices.Sort(keys)
	out := make([]keyVal, 0, len(keys))
	for _, k := range keys {
		out = append(out, keyVal{Field: k, Message: errs[k]})
	}
	return out
}

func readAll(r io.Reader) []byte {
	b, err := io.ReadAll(r)
	if err != nil {
		return nil
	}
	return b
}

// writeJSON sets the content type, status, and body in one shot. Encode appends
// a trailing newline (so callers must NOT add their own — go vet enforces that).
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

// doRequest runs a handler against an in-memory httptest recorder — no socket,
// no network, fully deterministic. This is the offline handler-test pattern.
func doRequest(h http.HandlerFunc, method string, body []byte) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(method, "/register", bytes.NewReader(body))
	h(rec, req)
	return rec
}

// sectionF: the full pipeline through an HTTP handler. A semantically bad body
// (valid JSON, invalid values) -> 400 + sorted field errors; a good body -> 200.
// A malformed body -> 400 from the bind phase.
func sectionF() {
	sectionBanner("F — Handler end-to-end: decode + validate -> 400 or 200 (httptest)")

	// Bad body: valid JSON, but email fails the format rule and age exceeds max.
	badBody := []byte(`{"email":"not-an-email","age":200}`)
	recBad := doRequest(regHandler, http.MethodPost, badBody)
	fmt.Printf("POST bad body  -> status %d, body %s", recBad.Code, recBad.Body.Bytes())

	// Good body: every field passes both binding and validation.
	goodBody := []byte(`{"email":"a@b.com","age":30}`)
	recGood := doRequest(regHandler, http.MethodPost, goodBody)
	fmt.Printf("POST good body -> status %d, body %s", recGood.Code, recGood.Body.Bytes())

	// Malformed body: not even JSON -> rejected in the bind phase.
	malformed := []byte(`{"email":"a@b.com",}`)
	recMal := doRequest(regHandler, http.MethodPost, malformed)
	fmt.Printf("POST malformed -> status %d, body %s", recMal.Code, recMal.Body.Bytes())

	check("handler: bad POST -> 400", recBad.Code == http.StatusBadRequest)
	check("handler: good POST -> 200", recGood.Code == http.StatusOK)
	check("handler: malformed POST -> 400 (bind phase)", recMal.Code == http.StatusBadRequest)
	check("handler: bad response lists the offending fields",
		bytes.Contains(recBad.Body.Bytes(), []byte(`"email"`)) &&
			bytes.Contains(recBad.Body.Bytes(), []byte(`"age"`)))
}

func main() {
	fmt.Println("request_validation.go — Phase 6 bundle.")
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
