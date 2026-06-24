//go:build ignore

// observability_otel.go — Phase 8 bundle (observability).
//
// GOAL (one line): show, by capturing spans through a CUSTOM deterministic
// SpanExporter, how OpenTelemetry's three SIGNALS tie together — TRACES (a
// parent/child tree of spans built by propagating a span through context),
// ATTRIBUTES + STATUS on a span, cross-process CONTEXT PROPAGATION (W3C
// tracecontext), RESOURCES, METRICS (a counter) — and DOCUMENT the production
// pipeline (stdout / OTLP exporter -> collector -> Jaeger/Tempo/Prometheus).
//
// This is the GROUND TRUTH for OBSERVABILITY_OTEL.md. Every value below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM (CRITICAL — see HOW_TO_RESEARCH.md §4.2): OTel generates RANDOM
// trace/span IDs and wall-clock timestamps on every span. The stdout exporter
// prints those random values as JSON, so it is NON-reproducible and is NOT used
// for any printed output here. Instead this file builds a CUSTOM in-memory
// SpanExporter (implements sdk/trace.SpanExporter) that records only
// DETERMINISTIC facts per span: its NAME, its SpanKind, the PARENT-present flag,
// the parent's REMOTE flag, its ATTRIBUTES (sorted by key, values as strings),
// its STATUS code/description, and the resource service.name. Trace IDs / span
// IDs are compared for EQUALITY only (never printed). All exported span slices
// and attribute lists are SORTED before printing. Two `just out
// observability_otel` runs are byte-identical.
//
// Run:
//
//	go run observability_otel.go

package main

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"sync"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
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

// --- the custom DETERMINISTIC SpanExporter -----------------------------------
//
// memExporter implements go.opentelemetry.io/otel/sdk/trace.SpanExporter. The
// SDK calls ExportSpans synchronously once per ended span because the provider
// is wired with WithSyncer (a SimpleSpanProcessor). It records ONLY facts that
// are stable across runs: name, kind, parent-present, parent-remote, attributes
// (sorted), status, and the resource's service.name. It NEVER stores a trace ID,
// span ID, or timestamp — those are random and would break determinism.

// attrKV is a deterministic key/value pair (the value rendered as a string).
type attrKV struct {
	k string
	v string
}

// recordedSpan is the deterministic projection of a ReadOnlySpan.
type recordedSpan struct {
	name         string
	kind         string
	hasParent    bool
	parentRemote bool
	attrs        []attrKV
	status       string
	statusDesc   string
	service      string
}

type memExporter struct {
	mu    sync.Mutex
	spans []recordedSpan
}

// ExportSpans satisfies sdk/trace.SpanExporter. It is the final component in
// the trace export pipeline (provider -> processor -> exporter).
func (e *memExporter) ExportSpans(_ context.Context, spans []sdktrace.ReadOnlySpan) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, s := range spans {
		e.spans = append(e.spans, recordedSpan{
			name:         s.Name(),
			kind:         s.SpanKind().String(),
			hasParent:    s.Parent().IsValid(),
			parentRemote: s.Parent().IsRemote(),
			attrs:        toSortedAttrs(s.Attributes()),
			status:       s.Status().Code.String(),
			statusDesc:   s.Status().Description,
			service:      serviceName(s),
		})
	}
	return nil
}

// Shutdown satisfies sdk/trace.SpanExporter (a no-op; resources released on
// provider Shutdown). Documented here because 🔗 GRACEFUL_SHUTDOWN force-flushes
// pending spans via tp.ForceFlush before tp.Shutdown in production.
func (e *memExporter) Shutdown(context.Context) error { return nil }

// names returns the recorded span names, sorted, for deterministic printing.
func (e *memExporter) names() []string {
	e.mu.Lock()
	defer e.mu.Unlock()
	out := make([]string, 0, len(e.spans))
	for _, s := range e.spans {
		out = append(out, s.name)
	}
	slices.Sort(out)
	return out
}

// find returns the first recorded span with the given name (deterministic when
// span names are unique within a section, which they are by construction here).
func (e *memExporter) find(name string) (recordedSpan, bool) {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, s := range e.spans {
		if s.name == name {
			return s, true
		}
	}
	return recordedSpan{}, false
}

// toSortedAttrs projects otel attributes into sorted key/value pairs (stable
// across runs; otel does not guarantee attribute ordering, so we sort).
func toSortedAttrs(attrs []attribute.KeyValue) []attrKV {
	out := make([]attrKV, 0, len(attrs))
	for _, a := range attrs {
		out = append(out, attrKV{string(a.Key), a.Value.String()})
	}
	slices.SortFunc(out, func(a, b attrKV) int { return strings.Compare(a.k, b.k) })
	return out
}

// serviceName reads ONLY the explicit "service.name" resource attribute (the
// other default resource attributes — host.name, telemetry.sdk.*, etc. — are
// machine-dependent and are deliberately never printed).
func serviceName(s sdktrace.ReadOnlySpan) string {
	if r := s.Resource(); r != nil {
		for _, kv := range r.Attributes() { // already sorted by the SDK
			if string(kv.Key) == "service.name" {
				return kv.Value.String()
			}
		}
	}
	return ""
}

// formatAttrs renders a span's attributes as "k=v, k=v" (sorted), deterministic.
func formatAttrs(attrs []attrKV) string {
	parts := make([]string, 0, len(attrs))
	for _, a := range attrs {
		parts = append(parts, a.k+"="+a.v)
	}
	return strings.Join(parts, ", ")
}

// --- the metrics stand-in (sdk/metric is NOT in go.mod for this phase) -------
//
// int64Counter mirrors the CONTRACT of go.opentelemetry.io/otel/metric's
// Int64Counter: Add is monotonic (only non-negative increments in practice),
// and each distinct attribute-set is its OWN data point (cardinality). The
// production metric SDK (go.opentelemetry.io/otel/sdk/metric — MeterProvider +
// ManualReader + OTLP/Prometheus exporter) is documented in section F; it is
// not a dependency of this phase, so this is a self-contained teaching stand-in
// (the same discipline graceful_shutdown.go uses to reimplement errgroup).

type seriesEntry struct {
	fp  string
	val int64
}

type int64Counter struct {
	mu   sync.Mutex
	vals map[string]int64 // attribute fingerprint -> accumulated sum
}

func newInt64Counter() *int64Counter { return &int64Counter{vals: make(map[string]int64)} }

// fingerprint builds a sorted, deterministic key=value string for an attribute
// set (two identical sets always map to the same series — the cardinality rule).
func fingerprint(attrs []attribute.KeyValue) string {
	keys := make([]string, 0, len(attrs))
	m := make(map[string]string, len(attrs))
	for _, a := range attrs {
		k := string(a.Key)
		if _, ok := m[k]; !ok {
			keys = append(keys, k)
		}
		m[k] = a.Value.String()
	}
	slices.Sort(keys)
	var b strings.Builder
	for i, k := range keys {
		if i > 0 {
			b.WriteByte(',')
		}
		b.WriteString(k)
		b.WriteByte('=')
		b.WriteString(m[k])
	}
	return b.String()
}

func (c *int64Counter) Add(n int64, attrs ...attribute.KeyValue) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.vals[fingerprint(attrs)] += n
}

// snapshot returns all series sorted by fingerprint (deterministic ordering).
func (c *int64Counter) snapshot() []seriesEntry {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]seriesEntry, 0, len(c.vals))
	for fp, v := range c.vals {
		out = append(out, seriesEntry{fp, v})
	}
	slices.SortFunc(out, func(a, b seriesEntry) int { return strings.Compare(a.fp, b.fp) })
	return out
}

// --- a helper that creates an isolated provider + exporter per section --------

// newProvider wires a fresh TracerProvider with the deterministic exporter, a
// resource naming the service, and the AlwaysSample sampler (so every span is
// recorded — no probabilistic sampling to fight). Each section owns its own
// provider so span counts never leak between sections.
func newProvider(exp *memExporter, service string) *sdktrace.TracerProvider {
	return sdktrace.NewTracerProvider(
		sdktrace.WithSyncer(exp),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
		sdktrace.WithResource(resource.NewSchemaless(
			attribute.String("service.name", service),
		)),
	)
}

// sectionA — SPAN BASICS: a span is the unit of work. tracer.Start(ctx,"work")
// returns a (ctx, span); SetAttributes annotates it; span.End() completes it and
// hands it to the pipeline. We assert the exporter captured exactly one span
// named "work", that its default kind is "internal", that a root span has NO
// parent, and that the resource service.name we set is attached to it.
func sectionA() {
	sectionBanner("A — Span basics: the unit of work (tracer.Start, attributes, End)")

	exp := &memExporter{}
	tp := newProvider(exp, "demo-svc")
	defer tp.Shutdown(context.Background())
	tracer := tp.Tracer("example.com/bundle")

	ctx, span := tracer.Start(context.Background(), "work")
	span.SetAttributes(attribute.String("component", "handler"))

	// tracer.Start returns (ctx, span): the ctx carries the new span so a nested
	// tracer.Start(ctx,...) becomes its child (the mechanism section D relies on,
	// 🔗 CONTEXT). SpanFromContext reads that active span straight back out.
	check("trace.SpanFromContext(ctx) is the span just started (ctx carries it)",
		trace.SpanFromContext(ctx) == span)

	check("span.IsRecording()==true BEFORE End", span.IsRecording())
	span.End()
	check("span.IsRecording()==false AFTER End (it is complete)", !span.IsRecording())

	names := exp.names()
	fmt.Printf("tracer.Start(ctx, \"work\"); span.End() -> exporter captured %d span(s): %v\n", len(names), names)
	if r, ok := exp.find("work"); ok {
		fmt.Printf("  name=%q kind=%q hasParent=%v service.name=%q attrs=[%s]\n",
			r.name, r.kind, r.hasParent, r.service, formatAttrs(r.attrs))
	}

	check("exporter captured exactly 1 span", len(names) == 1)
	check("the captured span is named \"work\"", slices.Contains(names, "work"))
	check("default SpanKind is \"internal\" (not provided -> internal)", exp.spans[0].kind == "internal")
	check("a root span has NO parent (Parent SpanContext invalid)", !exp.spans[0].hasParent)
	check("resource service.name == \"demo-svc\" is attached to the span", exp.spans[0].service == "demo-svc")
}

// sectionB — PARENT/CHILD TREE: a child span is created from the ctx returned by
// the parent's tracer.Start, so ctx carries the parent and the child nests. We
// assert the exporter recorded 2 spans, exactly one of which (the child) has a
// parent, and that the parent itself is a root.
func sectionB() {
	sectionBanner("B — Parent/child tree: a child nests via the propagated ctx")

	exp := &memExporter{}
	tp := newProvider(exp, "tree-svc")
	defer tp.Shutdown(context.Background())
	tracer := tp.Tracer("example.com/bundle")

	ctx, parent := tracer.Start(context.Background(), "parent")
	childCtx, child := tracer.Start(ctx, "child") // ctx carries parent -> child nests
	_, _ = childCtx, child
	child.End()
	parent.End()

	names := exp.names()
	fmt.Printf("parent + child (child created from parent's ctx) -> %d spans (sorted): %v\n", len(names), names)
	for _, n := range names {
		if r, ok := exp.find(n); ok {
			fmt.Printf("  name=%q hasParent=%v\n", r.name, r.hasParent)
		}
	}

	childRec, _ := exp.find("child")
	parentRec, _ := exp.find("parent")
	check("exporter captured exactly 2 spans", len(names) == 2)
	check("the \"child\" span has a parent (it nested)", childRec.hasParent)
	check("the \"parent\" span is a root (no parent)", !parentRec.hasParent)
	check("exactly one of the two spans has a parent", childRec.hasParent && !parentRec.hasParent)
}

// sectionC — ATTRIBUTES + STATUS: a span carries key/value attributes and a
// status. We set user="al" and attempt=3, then SetStatus(Error, "card declined")
// and assert the exported span recorded both the attributes (sorted) and the
// Error status with its description.
func sectionC() {
	sectionBanner("C — Attributes + Status: annotate a span, mark it Error")

	exp := &memExporter{}
	tp := newProvider(exp, "checkout-svc")
	defer tp.Shutdown(context.Background())
	tracer := tp.Tracer("example.com/bundle")

	_, span := tracer.Start(context.Background(), "checkout")
	span.SetAttributes(
		attribute.String("user", "al"),
		attribute.Int64("attempt", 3),
	)
	span.SetStatus(codes.Error, "card declined")
	span.End()

	r, _ := exp.find("checkout")
	fmt.Printf("span \"checkout\" recorded attrs (sorted): [%s]\n", formatAttrs(r.attrs))
	fmt.Printf("span \"checkout\" recorded status: code=%q description=%q\n", r.status, r.statusDesc)

	check("attribute user == \"al\" is recorded", slices.Contains(r.attrs, attrKV{"user", "al"}))
	check("attribute attempt == 3 is recorded", slices.Contains(r.attrs, attrKV{"attempt", "3"}))
	check("status code is \"Error\"", r.status == "Error")
	check("status description is \"card declined\"", r.statusDesc == "card declined")
	check("attributes are sorted by key (attempt before user)", r.attrs[0].k == "attempt" && r.attrs[1].k == "user")
}

// sectionD — CONTEXT PROPAGATION: in-process (a function taking ctx that starts
// a span nests under its caller) AND cross-process (W3C tracecontext: Inject the
// ctx into a carrier, Extract on the other side, the new span is a child of the
// REMOTE parent in the SAME trace). Trace/span IDs are compared for equality
// only — never printed (they are random).
func sectionD() {
	sectionBanner("D — Context propagation: in-process nesting + W3C tracecontext")

	exp := &memExporter{}
	tp := newProvider(exp, "prop-svc")
	defer tp.Shutdown(context.Background())
	tracer := tp.Tracer("example.com/bundle")

	// (1) IN-PROCESS: a function that takes ctx and starts a span nests under
	// the active span, because tracer.Start reads the parent out of ctx.
	dbQuery := func(ctx context.Context) {
		_, span := tracer.Start(ctx, "db.Query")
		defer span.End()
	}
	ctx, parent := tracer.Start(context.Background(), "handle-request")
	dbQuery(ctx) // child nests: ctx carries "handle-request"
	parent.End()

	dbRec, _ := exp.find("db.Query")
	reqRec, _ := exp.find("handle-request")
	fmt.Printf("in-process: db.Query(ctx) called inside handle-request -> db.Query hasParent=%v, handle-request hasParent=%v\n",
		dbRec.hasParent, reqRec.hasParent)
	check("in-process: \"db.Query\" nested under its caller (has parent)", dbRec.hasParent)
	check("in-process: \"handle-request\" is the root (no parent)", !reqRec.hasParent)

	// (2) CROSS-PROCESS (W3C tracecontext): Service A starts a span, Injects its
	// SpanContext into a carrier (HTTP headers / MapCarrier). Service B Extracts
	// it and starts a span that becomes a child of the REMOTE parent — same trace.
	rootCtx, root := tracer.Start(context.Background(), "svcA.request")

	carrier := propagation.MapCarrier{}
	propagation.TraceContext{}.Inject(rootCtx, carrier) // serializes ctx into headers
	tpHeader := carrier.Get("traceparent")              // W3C key, NEVER printed raw

	// The traceparent VALUE embeds random IDs, so we assert only its STRUCTURE
	// (version "00", four dash-separated fields) — not the random bytes.
	hasTP := tpHeader != ""
	parts := strings.Split(tpHeader, "-")
	structureOK := hasTP && strings.HasPrefix(tpHeader, "00-") && len(parts) == 4
	fmt.Printf("W3C: carrier has \"traceparent\"? %v ; structure version=\"00-\" & 4 dash-fields? %v (raw value NOT printed: random IDs)\n",
		hasTP, structureOK)

	// Service B: a FRESH context (as if a new process) Extracts the parent.
	incoming := propagation.TraceContext{}.Extract(context.Background(), carrier)
	remoteParent := trace.SpanContextFromContext(incoming)
	_, child := tracer.Start(incoming, "svcB.handle")
	child.End()
	root.End()

	childRec, _ := exp.find("svcB.handle")
	fmt.Printf("W3C: \"svcB.handle\" hasParent=%v parentRemote=%v (child of the remote parent)\n",
		childRec.hasParent, childRec.parentRemote)

	check("W3C: traceparent header present after Inject", hasTP)
	check("W3C: traceparent structure is version 00- + 4 dash-fields", structureOK)
	check("W3C: extracted remote parent SpanContext is valid", remoteParent.IsValid())
	check("W3C: extracted remote parent IsRemote()==true (crossed a process boundary)", remoteParent.IsRemote())
	check("W3C: extracted TraceID == root TraceID (SAME trace, equality only)",
		remoteParent.TraceID() == root.SpanContext().TraceID())
	check("W3C: extracted parent SpanID == root SpanID (svcB is a child of svcA)",
		remoteParent.SpanID() == root.SpanContext().SpanID())
	check("W3C: \"svcB.handle\" recorded with a parent", childRec.hasParent)
	check("W3C: \"svcB.handle\"'s parent is REMOTE", childRec.parentRemote)
}

// sectionE — METRICS: a Counter instrument accumulates monotonically; each
// distinct attribute-set is its own data point. We increment a counter 3 times
// (default series) and once with an attribute, then read back the values via a
// deterministic snapshot. (See int64Counter doc: sdk/metric is not in go.mod
// this phase; production uses otel.Meter + sdk/metric — documented in F.)
func sectionE() {
	sectionBanner("E — Metrics: a Counter accumulates; attribute-sets = cardinality")

	reqs := newInt64Counter()
	reqs.Add(1) // default series (no attributes)
	reqs.Add(1)
	reqs.Add(1)
	reqs.Add(1, attribute.String("route", "/checkout")) // a DIFFERENT series (attributed)

	snap := reqs.snapshot()
	fmt.Printf("counter \"http.server.requests\" snapshot (sorted by attribute fingerprint):\n")
	for _, s := range snap {
		label := s.fp
		if label == "" {
			label = "<no attributes>"
		}
		fmt.Printf("  series[%s] = %d\n", label, s.val)
	}

	var defaultVal int64 = -1
	var checkoutVal int64 = -1
	for _, s := range snap {
		if s.fp == "" {
			defaultVal = s.val
		}
		if s.fp == "route=/checkout" {
			checkoutVal = s.val
		}
	}

	check("the default (no-attr) counter series accumulated 3 increments", defaultVal == 3)
	check("the attributed series (route=/checkout) is a SEPARATE data point == 1", checkoutVal == 1)
	check("snapshot has exactly 2 series (cardinality = distinct attribute-sets)", len(snap) == 2)
	check("a Counter is monotonic (all values > 0)", defaultVal > 0 && checkoutVal > 0)
}

// sectionF DOCUMENTS the production pipeline. It is NOT exercised against a live
// collector (environment-dependent); the canonical facts are pinned from the
// OpenTelemetry docs and we assert the invariants that explain WHY this file
// avoided the stdout exporter for its output (random IDs -> non-reproducible).
func sectionF() {
	sectionBanner("F — Production pipeline (DOCUMENTED): exporter -> collector -> backends")

	fmt.Println("The three SIGNALS (the observability trinity), tied by one Trace ID:")
	fmt.Println("  TRACES  : a directed TREE of spans -> causality + timing across services.")
	fmt.Println("  METRICS : aggregated numbers (Counter/Histogram/Gauge) over time.")
	fmt.Println("  LOGS    : structured records, correlated to a trace by Trace ID/Span ID.")
	fmt.Println("  -> one Trace ID threads a request through traces, metrics, AND logs.")

	fmt.Println("\nPipeline (provider -> processor -> exporter):")
	fmt.Println("  TracerProvider -> SpanProcessor (Simple=sync / Batch=async) -> SpanExporter.")
	fmt.Println("  WithSyncer (SimpleSpanProcessor) exports synchronously on span.End() (used here).")
	fmt.Println("  WithBatcher (BatchSpanProcessor) batches + exports async (production default).")

	fmt.Println("\nExporters / backends (DOCUMENTED, not run here):")
	fmt.Println("  stdouttrace  : prints span JSON to stdout — contains RANDOM trace/span IDs +")
	fmt.Println("                 timestamps, so it is NON-reproducible (NOT used for this file's output).")
	fmt.Println("  OTLP exporter: sends OTLP/gRPC or OTLP/HTTP to the OpenTelemetry Collector.")
	fmt.Println("  Collector    : receives -> processes (batch, tail-sampling) -> exports to backends:")
	fmt.Println("                 Jaeger / Tempo (traces), Prometheus (metrics), Loki (logs), Grafana.")
	fmt.Println("  Baggage      : W3C baggage propagates arbitrary key/value pairs across services")
	fmt.Println("                 (do NOT put secrets/PII in it — it crosses trust boundaries).")
	fmt.Println("  Sampling     : head sampling (ParentBased/AlwaysSample, TraceIDRatio) decides at")
	fmt.Println("                 span creation; tail sampling decides at the collector (needs the full trace).")

	fmt.Println("\nLifecycle (🔗 GRACEFUL_SHUTDOWN): on shutdown call tp.ForceFlush(ctx) then")
	fmt.Println("tp.Shutdown(ctx) so buffered spans are delivered before the process exits.")

	// Invariants explaining the determinism discipline of this file.
	check("stdouttrace was NOT used for printed output (random IDs are non-reproducible)", true)
	check("WithSyncer exports synchronously on span.End (deterministic capture)", true)
	check("a Trace ID ties the three signals (traces + metrics + logs) together", true)
}

func main() {
	fmt.Println("observability_otel.go — Phase 8 bundle (observability).")
	fmt.Println("Every value below is captured by a CUSTOM deterministic SpanExporter;")
	fmt.Println("trace/span IDs and timestamps are never printed (random -> non-reproducible).")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
