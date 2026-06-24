//go:build ignore

// slog.go — Phase 7 bundle #43.
//
// GOAL (one line): show, by printing every behavior, how log/slog performs
// STRUCTURED logging — a Record = {time, level, msg, attrs...} serialized by a
// Handler (TextHandler -> key=value, JSONHandler -> JSON) — with levels,
// With/Group, LogValuer, and context integration.
//
// This is the GROUND TRUTH for SLOG.md. Every value/line below is computed by
// this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM: the built-in handlers stamp every record with the current time.
// That makes raw output non-reproducible, so EVERY handler in this file is built
// with a HandlerOptions whose ReplaceAttr drops the "time" key (returning a zero
// Attr deletes the attribute). Output is then written to a bytes.Buffer, so two
// `go run` invocations are byte-identical. See SLOG.md §"Determinism".
//
// Run:
//
//	go run slog.go

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
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

// dropTime is a slog.HandlerOptions.ReplaceAttr function that deletes the
// built-in "time" attribute. Returning a zero slog.Attr discards the attribute.
// We guard with len(groups)==0 so we only drop the TOP-LEVEL time, never a
// user attr named "time" nested inside a group. This is the exact pattern from
// the pkg.go.dev/log/slog example.
func dropTime(groups []string, a slog.Attr) slog.Attr {
	if a.Key == slog.TimeKey && len(groups) == 0 {
		return slog.Attr{}
	}
	return a
}

// noTime is the option set every handler in this file uses, so output is
// byte-stable (the timestamp is the only non-deterministic field).
var noTime = &slog.HandlerOptions{ReplaceAttr: dropTime}

// newBufLogger builds a logger writing to a fresh bytes.Buffer with TextHandler
// (time dropped) at the given minimum level.
func newBufLogger(level slog.Leveler) (*slog.Logger, *bytes.Buffer) {
	var buf bytes.Buffer
	h := slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: level, ReplaceAttr: dropTime})
	return slog.New(h), &buf
}

// traceKey is an unexported context key (see CONTEXT.md §E: unexported types
// are the only collision-free key kind).
type traceKey struct{}

// traceHandler wraps an inner Handler and, on every Handle call, pulls a
// trace-id out of the context and attaches it as an attribute. This is the
// canonical pattern for OTel/jaeger integration (see SLOG.md §8).
type traceHandler struct {
	slog.Handler // embed: Enabled/WithAttrs/WithGroup are promoted; we override Handle.
}

// Handle implements slog.Handler. It reads a request-scoped value from ctx and
// enriches the Record before delegating to the wrapped handler.
func (h traceHandler) Handle(ctx context.Context, r slog.Record) error {
	if tid, ok := ctx.Value(traceKey{}).(string); ok {
		r.AddAttrs(slog.String("trace_id", tid))
	}
	return h.Handler.Handle(ctx, r)
}

// --- LogValuer example type (Section E) -------------------------------------

// UserLog implements slog.LogValuer so an instance renders as a GROUP of attrs
// instead of a single unstructured value. The secret `token` is deliberately
// REDACTED — LogValuer is also the standard way to scrub sensitive fields.
type UserLog struct {
	ID    int
	Name  string
	Token string
}

// LogValue implements slog.LogValuer. Returning a Group Value expands one
// object into several attributes; returning an empty Token hides the secret.
func (u UserLog) LogValue() slog.Value {
	return slog.GroupValue(
		slog.Int("id", u.ID),
		slog.String("name", u.Name),
		// token intentionally omitted -> never appears in logs
	)
}

// sectionA contrasts the two built-in handlers on the SAME record.
func sectionA() {
	sectionBanner("A — TextHandler (key=value) vs JSONHandler (JSON)")

	// TextHandler: writes key=value pairs to a buffer.
	var textBuf bytes.Buffer
	textLogger := slog.New(slog.NewTextHandler(&textBuf, noTime))
	textLogger.Info("login", "user", "al", "count", 3)
	fmt.Printf("TextHandler : %s\n", strings.TrimRight(textBuf.String(), "\n"))

	// JSONHandler: writes one JSON object per record to a buffer.
	var jsonBuf bytes.Buffer
	jsonLogger := slog.New(slog.NewJSONHandler(&jsonBuf, noTime))
	jsonLogger.Info("login", "user", "al", "count", 3)
	fmt.Printf("JSONHandler : %s\n", strings.TrimRight(jsonBuf.String(), "\n"))

	textOut := textBuf.String()
	jsonOut := jsonBuf.Bytes()

	// TextHandler renders attrs as key=value pairs.
	check("TextHandler output contains user=al", strings.Contains(textOut, "user=al"))
	check("TextHandler output contains count=3", strings.Contains(textOut, "count=3"))

	// JSONHandler output must be valid JSON decoding to user=="al".
	var m map[string]any
	err := json.Unmarshal(jsonOut, &m)
	check("JSONHandler output is valid JSON", err == nil)
	if err == nil {
		check("JSONHandler decodes to map[user]==\"al\"", m["user"] == "al")
		check("JSONHandler decodes to map[count]==3 (JSON numbers -> float64)", m["count"] == float64(3))
		_, hasTime := m["time"]
		check("JSONHandler output has no time field (neutralized)", !hasTime)
		check("both handlers emit the same msg", strings.Contains(textOut, "msg=login") && m["msg"] == "login")
	}
}

// sectionB pins the four levels and shows that a Level=Warn handler DROPS Info.
func sectionB() {
	sectionBanner("B — Levels & filtering (Level=Warn drops Info)")

	// Levels are just ints: the higher, the more severe. Info is the zero value.
	fmt.Printf("LevelDebug = %d\n", slog.LevelDebug)
	fmt.Printf("LevelInfo  = %d   (the default value of a Level)\n", slog.LevelInfo)
	fmt.Printf("LevelWarn  = %d\n", slog.LevelWarn)
	fmt.Printf("LevelError = %d\n", slog.LevelError)

	// A handler gated at LevelWarn discards anything less severe than Warn.
	logger, buf := newBufLogger(slog.LevelWarn)
	logger.Info("low-importance-info", "k", "v")  // severity 0  < 4 -> DROPPED
	logger.Warn("high-importance-warn", "k", "v") // severity 4 >= 4 -> KEPT
	fmt.Printf("buffer after Info+Warn (Level=Warn):\n%s", buf.String())

	out := buf.String()
	check("LevelDebug == -4", slog.LevelDebug == -4)
	check("LevelInfo == 0", slog.LevelInfo == 0)
	check("LevelWarn == 4", slog.LevelWarn == 4)
	check("LevelError == 8", slog.LevelError == 8)
	check("Info record is DROPPED (absent from output)", !strings.Contains(out, "low-importance-info"))
	check("Warn record is KEPT (present in output)", strings.Contains(out, "high-importance-warn"))
}

// sectionC shows With: a child logger that auto-attaches attrs to every record.
func sectionC() {
	sectionBanner("C — With: a child logger carries request-scoped attrs")

	base, buf := newBufLogger(slog.LevelInfo)
	// With returns a NEW *Logger that will prefix every record with svc=api.
	// The built-in handlers pre-format these attrs ONCE (a performance win).
	child := base.With("svc", "api", "ver", "v2")

	child.Info("hit")
	child.Warn("slow")
	fmt.Printf("base.With(\"svc\",\"api\",\"ver\",\"v2\").Info/Warn:\n%s", buf.String())

	out := buf.String()
	check("child log includes svc=api", strings.Contains(out, "svc=api"))
	check("child log includes ver=v2", strings.Contains(out, "ver=v2"))
	check("BOTH records carry the With attrs (count of svc=api == 2)",
		strings.Count(out, "svc=api") == 2)

	// The base logger is UNAFFECTED — With returns a new logger, it mutates nothing.
	var baseBuf bytes.Buffer
	baseLogger := slog.New(slog.NewTextHandler(&baseBuf, noTime))
	baseLogger.Info("plain")
	check("base logger has NO svc attr (With does not mutate the parent)",
		!strings.Contains(baseBuf.String(), "svc="))
}

// sectionD shows Group: nesting attrs under a namespace.
func sectionD() {
	sectionBanner("D — Group: nest attrs under a namespace")

	// TextHandler flattens a group with a dotted key: req.method, req.path.
	var textBuf bytes.Buffer
	textLogger := slog.New(slog.NewTextHandler(&textBuf, noTime))
	textLogger.Info("finished",
		slog.Group("req", slog.String("method", "GET"), slog.String("path", "/x")),
		slog.Int("status", 200),
	)
	fmt.Printf("TextHandler (Group -> dotted keys):\n%s\n", strings.TrimRight(textBuf.String(), "\n"))

	// JSONHandler renders a group as a nested JSON object.
	var jsonBuf bytes.Buffer
	jsonLogger := slog.New(slog.NewJSONHandler(&jsonBuf, noTime))
	jsonLogger.Info("finished",
		slog.Group("req", slog.String("method", "GET"), slog.String("path", "/x")),
		slog.Int("status", 200),
	)
	fmt.Printf("JSONHandler (Group -> nested object):\n%s\n", strings.TrimRight(jsonBuf.String(), "\n"))

	textOut := textBuf.String()
	check("TextHandler: group flattened to req.method=GET", strings.Contains(textOut, "req.method=GET"))
	check("TextHandler: group flattened to req.path=/x", strings.Contains(textOut, "req.path=/x"))

	var m map[string]any
	if err := json.Unmarshal(jsonBuf.Bytes(), &m); err != nil {
		panic("JSONHandler output not valid JSON: " + err.Error())
	}
	req, _ := m["req"].(map[string]any)
	check("JSONHandler: req is a nested object", req != nil)
	check("JSONHandler: req.method == GET", req["method"] == "GET")
}

// sectionE shows LogValuer: a custom type renders itself as structured attrs.
func sectionE() {
	sectionBanner("E — LogValuer: a type renders itself as attrs (and redacts)")

	u := UserLog{ID: 7, Name: "al", Token: "super-secret"}

	var buf bytes.Buffer
	logger := slog.New(slog.NewTextHandler(&buf, noTime))
	logger.Info("authenticated", "user", u)
	fmt.Printf("LogValue of UserLog{id:7,name:\"al\",token:\"super-secret\"}:\n%s\n", strings.TrimRight(buf.String(), "\n"))

	out := buf.String()
	check("LogValuer rendered id=7", strings.Contains(out, "user.id=7"))
	check("LogValuer rendered name=al", strings.Contains(out, "user.name=al"))
	check("LogValuer REDACTED the token (absent from output)", !strings.Contains(out, "super-secret"))
	check("LogValuer emitted NO user.token key at all", !strings.Contains(out, "user.token"))
}

// sectionF shows InfoContext + a custom handler that pulls a trace-id from ctx.
func sectionF() {
	sectionBanner("F — InfoContext + custom handler reads ctx for a trace-id")

	var buf bytes.Buffer
	// Wrap a TextHandler in traceHandler: every Handle call enriches the record
	// with a trace_id pulled from the context.
	inner := slog.NewTextHandler(&buf, noTime)
	logger := slog.New(traceHandler{Handler: inner})

	ctx := context.WithValue(context.Background(), traceKey{}, "trace-abc-123")
	logger.InfoContext(ctx, "serving request", "path", "/home")
	logger.WarnContext(ctx, "cache miss", "key", "u:7")
	fmt.Printf("InfoContext/WarnContext with ctx carrying trace-id:\n%s", buf.String())

	out := buf.String()
	check("custom handler injected trace_id=trace-abc-123", strings.Contains(out, "trace_id=trace-abc-123"))
	check("BOTH context logs carry the trace_id", strings.Count(out, "trace_id=trace-abc-123") == 2)

	// A context WITHOUT the trace key produces records with NO trace_id.
	var plainBuf bytes.Buffer
	plainInner := slog.NewTextHandler(&plainBuf, noTime)
	plainLogger := slog.New(traceHandler{Handler: plainInner})
	plainLogger.InfoContext(context.Background(), "no trace here")
	check("no trace_id when ctx carries none", !strings.Contains(plainBuf.String(), "trace_id"))
}

func main() {
	fmt.Println("slog.go — Phase 7 bundle #43 (log/slog structured logging).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Timestamps are neutralized (dropped) for determinism.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
