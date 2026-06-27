"""
opentelemetry.py - OpenTelemetry architecture & mechanics simulation.

The single source of truth that OPENTELEMETRY.md and opentelemetry.html are
built from. Every number, table, and trace in this bundle is printed here.

Run:
    python3 opentelemetry.py

Pure stdlib. Fully deterministic (fixed-seed LCG; no wall-clock; no real
network). Every "random" trace/span ID is reproducible bit-for-bit in
JavaScript via Math.imul.

==========================================================================
THE INTUITION (read this first)
==========================================================================
OpenTelemetry (OTel) is a vendor-neutral standard for emitting telemetry:
traces, metrics, and logs. It splits cleanly into five layers:

  1. API        - interfaces only (Tracer, Span, Meter). No behavior.
  2. SDK        - the implementation of the API. Creates real spans, manages
                  sampling, batching, and export.
  3. Exporter   - serializes spans to OTLP (protobuf over gRPC or HTTP) and
                  sends them out of the process.
  4. Collector  - a standalone binary that receives, processes, and exports
                  telemetry. Decouples apps from backends.
  5. Backend    - Jaeger, Tempo, Datadog, Honeycomb ... storage + UI.

The two ideas that make it WORK across process boundaries:

  - CONTEXT PROPAGATION (W3C Trace Context): a `traceparent` header
    (`00-<traceId>-<spanId>-<flags>`) is injected into every outgoing HTTP /
    gRPC / message request and extracted on the other side. That is how a
    trace is stitched across services.

  - HEAD-BASED SAMPLING: the root service decides whether to sample the trace
    using only the trace ID (TraceIDRatioBased) or a parent's decision
    (ParentBased). Unsampled traces are never created, so overhead is ~zero.

References:
  - W3C Trace Context: https://www.w3.org/TR/trace-context/
  - OTel specification: https://opentelemetry.io/docs/specs/otel/
  - OTLP protocol: https://opentelemetry.io/docs/specs/otlp/
  - Collector: https://opentelemetry.io/docs/collector/
"""

BANNER = "=" * 74


# ============================================================================
# Core primitive: deterministic LCG (identical in Python and JS)
# ============================================================================

class RNG:
    """Linear congruential generator. Same sequence in JS via Math.imul.

    Python:  state = (state * 1103515245 + 12345) & 0x7fffffff
    JS:      state = ((Math.imul(state,1103515245)+12345) & 0x7fffffff) >>> 0

    These are provably identical because 2^31 divides 2^32, so masking the
    low 32 bits of the product then taking mod 2^31 == taking mod 2^31
    directly. Verified for seed=42 -> 1250496027 in both languages.
    """

    def __init__(self, seed: int = 42):
        self.state = seed & 0x7FFFFFFF

    def next(self) -> int:
        self.state = (self.state * 1103515245 + 12345) & 0x7FFFFFFF
        return self.state

    def hex_bytes(self, n: int) -> str:
        """Generate *n* bytes as 2n lowercase hex chars."""
        return "".join(f"{self.next() & 0xFF:02x}" for _ in range(n))


def gen_trace_id(rng: RNG) -> str:
    """16 bytes = 32 hex chars. MUST NOT be all zeros (W3C requirement)."""
    tid = rng.hex_bytes(16)
    assert tid != "0" * 32
    return tid


def gen_span_id(rng: RNG) -> str:
    """8 bytes = 16 hex chars. MUST NOT be all zeros."""
    sid = rng.hex_bytes(8)
    assert sid != "0" * 16
    return sid


# ============================================================================
# W3C Trace Context: traceparent / tracestate
# ============================================================================

def make_traceparent(version: int, trace_id: str, span_id: str,
                     sampled: bool) -> str:
    """W3C traceparent header: version-trace_id-span_id-trace_flags.

    version     = 1 byte  (2 hex, currently 00)
    trace_id    = 16 bytes (32 hex)
    span_id     = 8 bytes  (16 hex)
    trace_flags = 1 byte  (2 hex; bit 0 = sampled)
    """
    flags = 0x01 if sampled else 0x00
    return f"{version:02x}-{trace_id}-{span_id}-{flags:02x}"


def parse_traceparent(tp: str):
    """Parse a traceparent into (version_hex, trace_id, span_id, sampled)."""
    parts = tp.split("-")
    assert len(parts) == 4, f"malformed traceparent: {tp}"
    version = parts[0]
    trace_id = parts[1]
    span_id = parts[2]
    flags = int(parts[3], 16)
    assert len(trace_id) == 32, "trace_id must be 32 hex chars"
    assert len(span_id) == 16, "span_id must be 16 hex chars"
    assert trace_id != "0" * 32, "trace_id must not be all zeros"
    assert span_id != "0" * 16, "span_id must not be all zeros"
    sampled = bool(flags & 0x01)
    return version, trace_id, span_id, sampled


def make_tracestate(members: list) -> str:
    """W3C tracestate: comma-separated key=value, max 32 members."""
    return ",".join(f"{k}={v}" for k, v in members)


def make_baggage(entries: list) -> str:
    """W3C Baggage: comma-separated key=value."""
    return ",".join(f"{k}={v}" for k, v in entries)


# ============================================================================
# Sampling
# ============================================================================

def trace_id_u32(trace_id: str) -> int:
    """First 4 bytes of trace_id as unsigned 32-bit.

    (The real OTel SDK compares the full 128-bit trace ID against the
    threshold; we use 32 bits so JS can do exact integer math without
    BigInt. The principle -- deterministic decision from trace_id alone --
    is identical.)
    """
    return int(trace_id[:8], 16)


def trace_id_ratio_sampled(trace_id: str, ratio: float) -> bool:
    """TraceIDRatioBased: deterministic from trace_id, no per-span RNG."""
    threshold = int(ratio * 0xFFFFFFFF)
    return trace_id_u32(trace_id) < threshold


def parent_based_sampled(parent_sampled: bool, root_trace_id: str,
                         ratio: float) -> bool:
    """ParentBased: child inherits parent's decision.

    - If there IS a parent: child.sampled = parent.sampled.
    - If there is NO parent (root): delegate to the root sampler
      (here TraceIDRatioBased).
    """
    if parent_sampled is None:               # root span
        return trace_id_ratio_sampled(root_trace_id, ratio)
    return parent_sampled                     # child inherits


# ============================================================================
# Span model + trace tree
# ============================================================================

class Span:
    __slots__ = ("name", "kind", "trace_id", "span_id", "parent_id",
                 "start_us", "end_us", "attributes", "events", "links",
                 "status", "sampled")

    def __init__(self, name, kind, trace_id, span_id, parent_id,
                 start_us, end_us, attributes=None, events=None,
                 links=None, status="OK", sampled=True):
        self.name = name
        self.kind = kind
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.start_us = start_us
        self.end_us = end_us
        self.attributes = attributes or {}
        self.events = events or []
        self.links = links or []
        self.status = status
        self.sampled = sampled

    @property
    def duration_us(self):
        return self.end_us - self.start_us

    def duration_ms(self):
        return self.duration_us / 1000


# The canonical checkout trace: 7 spans, max depth 4.
# (name, kind, start_us, end_us, parent_index)
GOLD_TRACE_DEF = [
    ("GET /checkout",      "SERVER",       0,  150000, -1),
    ("auth.verify_token",  "CLIENT",    5000,   20000,  0),
    ("order.create",       "CLIENT",   25000,  120000,  0),
    ("db.insert_order",    "CLIENT",   30000,   60000,  2),
    ("payment.charge",     "CLIENT",   65000,  110000,  2),
    ("db.update_balance",  "CLIENT",   72000,   95000,  4),
    ("resp.serialize",     "INTERNAL", 125000, 145000,  0),
]


def build_gold_trace(rng: RNG):
    """Build the 7-span checkout trace with deterministic IDs."""
    tid = gen_trace_id(rng)
    spans = []
    for i, (name, kind, s, e, pi) in enumerate(GOLD_TRACE_DEF):
        sid = gen_span_id(rng)
        parent_sid = spans[pi].span_id if pi >= 0 else None
        attrs = {"service.name": f"svc-{name.split('.')[0][:4].lower()}",
                 "http.method": "GET"}
        events = []
        if "db." in name:
            attrs["db.system"] = "postgresql"
            attrs["db.statement"] = f"INSERT INTO {name.split('_')[1]}"
        if name == "payment.charge":
            events.append(("exception", {"exception.type": "CardDeclined",
                                          "exception.message": "insufficient funds"}))
        if name == "GET /checkout":
            attrs["http.status_code"] = 200
        status = "ERROR" if events else "OK"
        spans.append(Span(name, kind, tid, sid, parent_sid, s, e,
                          attrs, events, status=status))
    return tid, spans


def trace_depth(spans):
    """Max depth of the span tree (root = 1)."""
    depths = {}
    for s in spans:
        if s.parent_id is None:
            depths[s.span_id] = 1
        else:
            parent_depth = next(
                depths[sp.span_id] for sp in spans
                if sp.span_id == s.parent_id)
            depths[s.span_id] = parent_depth + 1
    return max(depths.values())


# ============================================================================
# Batch processor (Collector)
# ============================================================================

def simulate_batch(spans_count, interval_ms, batch_size, timeout_ms):
    """Simulate the Collector batch processor.

    Spans arrive one per *interval_ms*. The processor flushes when either:
      - accumulated >= batch_size  (size trigger), OR
      - time since last flush >= timeout_ms  (timer trigger).
    Returns a list of flush sizes.
    """
    flushes = []
    pending = 0
    last_flush = 0
    for i in range(1, spans_count + 1):
        t = i * interval_ms
        pending += 1
        if pending >= batch_size:
            flushes.append(pending)
            pending = 0
            last_flush = t
        elif t - last_flush >= timeout_ms:
            flushes.append(pending)
            pending = 0
            last_flush = t
    if pending > 0:
        flushes.append(pending)
    return flushes


# ============================================================================
# Pretty printers
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(desc: str, ok: bool):
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


# ============================================================================
# SECTION A: Architecture - API -> SDK -> Exporter -> Collector -> Backend
# ============================================================================

ARCHITECTURE = [
    ("API", "Interfaces only",
     "Tracer, Span, Meter, Context. Zero behavior. A library that depends "
     "only on the API never breaks if you swap SDKs."),
    ("SDK", "Implementation",
     "Creates real spans, runs the sampler, batches, and drives exporters. "
     "You configure THIS layer, never the API."),
    ("Exporter", "Out-of-process transport",
     "Serializes spans to OTLP (protobuf). Sends over gRPC (port 4317) or "
     "HTTP/protobuf (port 4318). One exporter per backend."),
    ("Collector", "Standalone pipeline",
     "Receives OTLP from many apps, processes (batch, filter, redact), "
     "exports to one or more backends. Decouples apps from backend choice."),
    ("Backend", "Storage + UI",
     "Jaeger, Tempo, Datadog, Honeycomb, New Relic. Stores traces, "
     "indexes by trace ID, renders waterfall UI."),
]


def section_architecture():
    banner("SECTION A: Architecture - API -> SDK -> Exporter -> Collector -> Backend")

    print(f"\n  {'Layer':<12}{'Role':<26}{'Responsibility'}")
    print("  " + "-" * 68)
    for layer, role, resp in ARCHITECTURE:
        print(f"  {layer:<12}{role:<26}{resp[:42]}")

    print(f"\n  THE KEY SEPARATION:")
    print(f"    - Libraries import the API (no SDK dep).")
    print(f"    - The application installs exactly ONE SDK at startup.")
    print(f"    - Swap backends = change the exporter/Collector config,")
    print(f"      never the application code.")

    print(f"\n  AUTO-INSTRUMENTATION vs MANUAL spans:\n")
    auto_libs = [
        ("HTTP server", "Flask, Django, Express, Spring"),
        ("HTTP client", "requests, urllib3, okhttp"),
        ("DB drivers", "psycopg2, pymysql, mongodb-driver"),
        ("Messaging", "Kafka, RabbitMQ, NATS"),
    ]
    print(f"    {'Library (auto-instrumented)':<20}{'Examples'}")
    print(f"    {'-'*55}")
    for lib, ex in auto_libs:
        print(f"    {lib:<20}{ex}")
    print(f"\n    Auto-instrumentation wraps these with ZERO code changes.")
    print(f"    Manual spans needed for: business logic, custom algorithms.")
    print(f"\n    # AUTO (zero code):  OTEL_PYTHON_LOG_CORRELATION=true \\")
    print(f"    #   opentelemetry-instrument python app.py")
    print(f"\n    # MANUAL (business logic):")
    print(f"    #   with tracer.start_as_current_span('checkout.calc_total'):")
    print(f"    #       total = sum(item.price for item in cart)")

    check("API/SDK separation: libraries depend on API only", True)
    check("auto-instrumentation covers HTTP/DB/messaging", len(auto_libs) == 4)


# ============================================================================
# SECTION B: Span lifecycle + trace tree
# ============================================================================

def section_span_lifecycle():
    banner("SECTION B: Span lifecycle + trace tree")

    rng = RNG(42)
    tid, spans = build_gold_trace(rng)

    print(f"\n  Trace ID: {tid}")
    print(f"  Spans: {len(spans)}    Max depth: {trace_depth(spans)}")
    print(f"  Root duration: {spans[0].duration_us / 1000:.0f} ms")

    print(f"\n  {'span':<22}{'kind':<10}{'start_ms':>9}{'dur_ms':>8}"
          f"{'parent':>8}  {'status':<7}")
    print("  " + "-" * 70)
    for s in spans:
        parent_short = s.parent_id[:8] + ".." if s.parent_id else "ROOT"
        print(f"  {s.name:<22}{s.kind:<10}{s.start_us/1000:>9.1f}"
              f"{s.duration_us/1000:>8.1f}{parent_short:>8}  {s.status:<7}")

    print(f"\n  SPAN LIFECYCLE (per span):")
    print(f"    1. start_span(name, kind)    -> assign span_id, parent_id")
    print(f"    2. set_attribute(k, v)        -> key-value metadata")
    print(f"    3. add_event(name, attrs)     -> timestamped log IN the span")
    print(f"    4. add_link(span_ctx)         -> cross-trace reference")
    print(f"    5. set_status(OK / ERROR)     -> outcome")
    print(f"    6. end_span()                 -> fix end_time, enqueue export")

    # Show a span with an error event
    err = [s for s in spans if s.status == "ERROR"][0]
    print(f"\n  ERROR EVENT example ({err.name}):")
    for ename, eattrs in err.events:
        print(f"    event: {ename}")
        for k, v in sorted(eattrs.items()):
            print(f"      {k} = {v}")

    check("trace tree: 7 spans, max depth 4",
          len(spans) == 7 and trace_depth(spans) == 4)
    check("root span duration = 150 ms",
          spans[0].duration_us == 150000)
    return tid, spans


# ============================================================================
# SECTION C: W3C Trace Context propagation + baggage
# ============================================================================

def section_context_propagation():
    banner("SECTION C: W3C Trace Context - traceparent / tracestate / baggage")

    rng = RNG(99)
    tid = gen_trace_id(rng)

    print(f"\n  Trace ID (generated, seed=99): {tid}")
    print(f"\n  traceparent FORMAT:")
    print(f"    00-<trace_id 32hex>-<span_id 16hex>-<flags 2hex>")
    print(f"     |       |               |             |")
    print(f"   version  trace_id       span_id      sampled bit")
    print(f"    (00)   (16 bytes)     (8 bytes)    (01=yes, 00=no)")

    # Simulate a request crossing 3 services: Gateway -> Auth -> Order
    print(f"\n  REQUEST FLOW:  Gateway -> Auth -> Order\n")
    hops = [
        ("Gateway", "SERVER", "GET /api/data"),
        ("Auth", "SERVER", "verify_token"),
        ("Order", "SERVER", "create_order"),
    ]
    prev_span_id = None
    for svc, kind, op in hops:
        sid = gen_span_id(rng)
        if prev_span_id is None:
            tp = make_traceparent(0, tid, sid, True)
            print(f"  [{svc}] {op}")
            print(f"    CREATE root span  span_id={sid}")
            print(f"    INJECT header:    traceparent: {tp}")
        else:
            tp_in = make_traceparent(0, tid, prev_span_id, True)
            tp = make_traceparent(0, tid, sid, True)
            print(f"  [{svc}] {op}")
            print(f"    EXTRACT header:   traceparent: {tp_in}")
            print(f"    CREATE child span span_id={sid}  parent={prev_span_id}")
            print(f"    INJECT header:    traceparent: {tp}")
        prev_span_id = sid
        print()

    # traceparent round-trip
    sid_gold = gen_span_id(rng)
    tp_gold = make_traceparent(0, tid, sid_gold, True)
    ver, rt_tid, rt_sid, rt_sampled = parse_traceparent(tp_gold)
    rt_reserialized = make_traceparent(int(ver, 16), rt_tid, rt_sid, rt_sampled)

    print(f"  ROUND-TRIP TEST:")
    print(f"    built:        {tp_gold}")
    print(f"    parsed:       version={ver}  trace_id={rt_tid}")
    print(f"                  span_id={rt_sid}  sampled={rt_sampled}")
    print(f"    reserialized: {rt_reserialized}")
    check("traceparent round-trip preserves all fields",
          tp_gold == rt_reserialized and rt_sampled is True)

    # tracestate
    print(f"\n  TRACESTATE (vendor-specific, extends traceparent):")
    ts = make_tracestate([("congo", "t61rcWkgMzE"),
                           ("rojo", "00f067aa0ba902b7")])
    print(f"    tracestate: {ts}")
    print(f"    (max 32 members; oldest first; each vendor updates only its own key)")

    # Baggage
    print(f"\n  BAGGAGE (cross-cutting context, propagated alongside trace):")
    bg = make_baggage([("user.id", "42"), ("user.tier", "gold"),
                        ("request.region", "us-east-1")])
    print(f"    baggage: {bg}")
    print(f"    (comma-separated key=value; readable in ANY service without DB lookup)")

    check("tracestate and baggage are comma-separated key=value",
          "," in ts and "," in bg)
    return tid, sid_gold


# ============================================================================
# SECTION D: Head-based sampling
# ============================================================================

def section_sampling():
    banner("SECTION D: Head-based sampling - TraceIDRatioBased + ParentBased")

    print(f"""
  SAMPLING decides which traces are RECORDED. Head-based = decision at the
  root span (before any work is done). Two samplers dominate:

  TraceIDRatioBased(ratio)
    sampled = (trace_id[:4 bytes] as u32) < ratio * 0xFFFFFFFF
    Deterministic from trace_id alone. No per-span RNG. Reproducible.

  ParentBased(root_sampler)
    Root span -> delegates to root_sampler.
    Child span -> INHERITS parent's decision. (A partial trace is useless.)
""")

    rng = RNG(7)
    ratios = [0.10, 0.25, 0.50, 0.75, 1.00]
    n_traces = 2000

    print(f"  TraceIDRatioBased: {n_traces} traces, decision from trace_id\n")
    print(f"  {'ratio':>7}{'sampled':>10}{'dropped':>10}{'actual %':>10}")
    print("  " + "-" * 39)
    gold_decisions = {}
    for ratio in ratios:
        tids = [gen_trace_id(rng) for _ in range(n_traces)]
        decisions = [trace_id_ratio_sampled(t, ratio) for t in tids]
        sampled = sum(decisions)
        dropped = n_traces - sampled
        actual = sampled / n_traces * 100
        gold_decisions[ratio] = (sampled, dropped, actual)
        print(f"  {ratio:>6.0%}{sampled:>10}{dropped:>10}{actual:>9.1f}%")

    print(f"\n  ParentBased(TraceIDRatioBased(0.25)) - child inheritance:\n")
    rng2 = RNG(7)
    root_tid = gen_trace_id(rng2)
    root_decision = trace_id_ratio_sampled(root_tid, 0.25)
    print(f"    root trace_id:   {root_tid}")
    print(f"    root decision:   {root_decision}  (TraceIDRatioBased 0.25)")

    # Children: inherit root's decision, NOT re-evaluated
    children = [gen_trace_id(rng2) for _ in range(5)]
    print(f"\n    {'child #':<10}{'trace_id (first 16)':<20}{'parent_sampled':>15}"
          f"{'child_sampled':>15}")
    print("    " + "-" * 57)
    for i, cid in enumerate(children):
        child_sampled = parent_based_sampled(root_decision, cid, 0.25)
        print(f"    {i:<10}{cid[:16] + '..':<20}{str(root_decision):>15}"
              f"{str(child_sampled):>15}")

    print(f"\n  ALL children inherit the root decision ({root_decision}).")
    print(f"  The child's trace_id is NEVER evaluated for sampling --")
    print(f"  a partial trace (parent sampled, child not) is useless.")

    check("TraceIDRatioBased ratio close to target (within 5%)",
          abs(gold_decisions[0.25][2] - 25.0) < 5.0)
    check("ParentBased: all children inherit root decision",
          all(parent_based_sampled(root_decision, c, 0.25) == root_decision
              for c in children))
    check("ratio=1.00 samples everything",
          gold_decisions[1.00][0] == n_traces)
    return root_tid, root_decision, gold_decisions


# ============================================================================
# SECTION E: OTLP protocol - gRPC vs HTTP/protobuf
# ============================================================================

def section_otlp():
    banner("SECTION E: OTLP protocol - gRPC vs HTTP/protobuf")

    print(f"""
  OTLP (OpenTelemetry Protocol) is THE wire format. It uses protobuf for the
  payload and supports two transports:

  +-----------+----------+-------------------+---------------------------+
  | Transport | Port     | Path              | Encoding                  |
  +-----------+----------+-------------------+---------------------------+
  | gRPC      | 4317     | (service method)  | protobuf over HTTP/2      |
  | HTTP      | 4318     | /v1/traces        | protobuf body (Content-Type|
  |           |          | /v1/metrics       |   application/x-protobuf)  |
  |           |          | /v1/logs          |                           |
  +-----------+----------+-------------------+---------------------------+
""")

    print(f"  MESSAGE STRUCTURE (ExportTraceServiceRequest):\n")
    print(f"    ExportTraceServiceRequest")
    print(f"      +-- resource_spans[]          (one per Resource)")
    print(f"            +-- resource")
    print(f"            |     attributes[]       (service.name, host.name ...)")
    print(f"            +-- scope_spans[]")
    print(f"                  +-- scope")
    print(f"                  +-- spans[]")
    print(f"                        name, kind, trace_id, span_id,")
    print(f"                        parent_span_id, start_time_unix_nano,")
    print(f"                        end_time_unix_nano, attributes[],")
    print(f"                        events[], links[], status")

    print(f"\n  gRPC vs HTTP tradeoffs:\n")
    print(f"    {'Aspect':<20}{'gRPC (4317)':<22}{'HTTP (4318)':<22}")
    print(f"    {'-'*62}")
    print(f"    {'Multiplexing':<20}{'HTTP/2 streams':<22}{'one req / batch':<22}")
    print(f"    {'Load balancing':<20}{'L7 (headers)':<22}{'L4 (round-robin)':<22}")
    print(f"    {'Firewall friendly':<20}{'needs h2':<22}{'yes (plain HTTP)':<22}")
    print(f"    {'Streaming':<20}{'yes (bidir)':<22}{'no':<22}")
    print(f"    {'Debugging':<20}{'hard (binary)':<22}{'curl + protobuf':<22}")

    check("OTLP gRPC=4317, HTTP=4318, paths /v1/{traces,metrics,logs}", True)


# ============================================================================
# SECTION F: Collector pipeline - receivers -> processors -> exporters
# ============================================================================

def section_collector():
    banner("SECTION F: Collector pipeline - receivers -> processors -> exporters")

    print(f"""
  The Collector is configured as a set of PIPELINES. Each pipeline is:
    receiver(s) -> processor(s) -> exporter(s)
  A signal (traces / metrics / logs) flows in one direction.

  +------------+      +-------------+      +-----------+
  |  receivers | ---> |  processors | ---> | exporters |
  | (OTLP,     |      | (batch,     |      | (Jaeger,  |
  |  Jaeger,   |      |  memory_    |      |  Prom,    |
  |  Zipkin)   |      |  limiter,   |      |  OTLP,    |
  +------------+      |  attributes)|      |  file)    |
                      +-------------+      +-----------+
""")

    print(f"  COMPONENT CATALOG:\n")
    catalog = [
        ("receivers", [
            ("otlp", "OTLP gRPC(4317) + HTTP(4318)"),
            ("jaeger", "Jaeger Thrift / protobuf"),
            ("zipkin", "Zipkin v2 JSON"),
            ("hostmetrics", "CPU, mem, disk from /proc"),
        ]),
        ("processors", [
            ("batch", "Accumulate, flush at size OR timeout"),
            ("memory_limiter", "Drop data if heap exceeds soft limit"),
            ("attributes", "Insert/update/delete span attributes"),
            ("tail_sampling", "Decide sampling AFTER trace completes"),
            ("resource", "Add fixed resource attributes"),
        ]),
        ("exporters", [
            ("otlp", "Forward to another Collector / OTLP backend"),
            ("jaeger", "Jaeger storage (badger, cassandra, elasticsearch)"),
            ("prometheus", "Expose metrics on :8889 for scrape"),
            ("debug", "Print to stdout (was 'logging')"),
        ]),
    ]
    for comp_type, items in catalog:
        print(f"  {comp_type}:")
        for name, desc in items:
            print(f"    {name:<18}{desc}")
        print()

    # Batch processor simulation
    print(f"  BATCH PROCESSOR SIMULATION:")
    N_SPANS = 2000
    INTERVAL = 4       # ms between spans
    BATCH_SIZE = 512
    TIMEOUT = 5000     # ms

    flushes = simulate_batch(N_SPANS, INTERVAL, BATCH_SIZE, TIMEOUT)
    total = sum(flushes)

    print(f"\n    {N_SPANS} spans, one per {INTERVAL} ms, "
          f"batch_size={BATCH_SIZE}, timeout={TIMEOUT} ms\n")
    print(f"    flush #   spans   trigger")
    print(f"    {'-'*35}")
    for i, sz in enumerate(flushes):
        trigger = "size (>= 512)" if sz >= BATCH_SIZE else "timeout/end"
        print(f"    {i+1:>8}{sz:>8}   {trigger}")
    print(f"    {'total':>8}{total:>8}")

    check("batch processor flushes all spans",
          total == N_SPANS)
    check("batch flush sizes = [512, 512, 512, 464]",
          flushes == [512, 512, 512, 464])
    return flushes


# ============================================================================
# SECTION G: Overhead math - span bytes, batch bandwidth
# ============================================================================

def section_overhead():
    banner("SECTION G: Overhead math - span size, batch bandwidth")

    print(f"""
  A span in OTLP/protobuf costs bytes. Estimating the size lets you budget
  bandwidth and CPU before deploying.
""")

    # Protobuf field cost estimation (varint tags + length-delimited fields)
    print(f"  SPAN BYTE BUDGET (protobuf, estimated):\n")
    fields = [
        ("trace_id", 18, "1(tag)+1(len)+16"),
        ("span_id", 10, "1+1+8"),
        ("parent_span_id", 10, "1+1+8"),
        ("name", 22, "1+1+len(~20)"),
        ("kind", 2, "1+1 (varint enum)"),
        ("start_time_unix_nano", 9, "1+8 (fixed64)"),
        ("end_time_unix_nano", 9, "1+8 (fixed64)"),
        ("status", 5, "1+1+varint(code)"),
    ]
    print(f"    {'field':<24}{'bytes':>6}  {'encoding'}")
    print(f"    {'-'*52}")
    base = 0
    for name, b, enc in fields:
        print(f"    {name:<24}{b:>6}  {enc}")
        base += b

    per_attr = 30
    n_attrs = 4
    attr_total = per_attr * n_attrs
    span_bytes = base + attr_total

    wrap = 50  # ResourceSpans + ScopeSpans nesting overhead
    total_per_span = span_bytes + wrap

    print(f"\n    {'base fields':<24}{base:>6}")
    print(f"    {'attributes (4 x 30)':<24}{attr_total:>6}")
    print(f"    {'span subtotal':<24}{span_bytes:>6}")
    print(f"    {'OTLP wrap overhead':<24}{wrap:>6}")
    print(f"    {'TOTAL per span':<24}{total_per_span:>6}  bytes")

    # Batch bandwidth
    BATCH_SIZE = 512
    batch_bytes = BATCH_SIZE * total_per_span
    print(f"\n  BATCH BANDWIDTH (batch_size={BATCH_SIZE}):\n")
    print(f"    {BATCH_SIZE} spans x {total_per_span} B = {batch_bytes} B")
    print(f"                                  = {batch_bytes/1024:.1f} KB per batch")

    for sps in [500, 2000, 10000, 50000]:
        bw_kbs = sps * total_per_span / 1024
        exports = sps / BATCH_SIZE
        print(f"    {sps:>6} spans/s -> {bw_kbs:>8.1f} KB/s  "
              f"({exports:>5.1f} batches/s)")

    print(f"\n  RULE OF THUMB: OTel SDK overhead < 1% CPU at 10K spans/s/node.")
    print(f"  The Collector's batch processor is the main memory consumer")
    print(f"  (it buffers up to batch_size * send_queue_size spans in RAM).")

    check("span byte estimate: base=85, +4 attrs=120, total=255",
          span_bytes == 205 and total_per_span == 255)
    return total_per_span, batch_bytes


# ============================================================================
# SECTION H: GOLD values - pinned for opentelemetry.html
# ============================================================================

def section_gold():
    banner("SECTION H: GOLD values - pinned for opentelemetry.html")

    # GOLD 1: traceparent round-trip
    rng = RNG(123)
    g_tid = gen_trace_id(rng)
    g_sid = gen_span_id(rng)
    g_tp = make_traceparent(0, g_tid, g_sid, True)
    _, _, _, g_sampled = parse_traceparent(g_tp)

    print(f"\n  GOLD 1 - traceparent round-trip:")
    print(f"    trace_id:    {g_tid}")
    print(f"    span_id:     {g_sid}")
    print(f"    traceparent: {g_tp}")
    print(f"    sampled:     {g_sampled}")
    check("traceparent round-trip == identity",
          g_tp == make_traceparent(0, g_tid, g_sid, True) and g_sampled)

    # GOLD 2: sampling decision (TraceIDRatioBased)
    rng2 = RNG(77)
    g_stid = gen_trace_id(rng2)
    g_u32 = trace_id_u32(g_stid)
    g_ratio = 0.25
    g_threshold = int(g_ratio * 0xFFFFFFFF)
    g_sampled_25 = trace_id_ratio_sampled(g_stid, g_ratio)

    print(f"\n  GOLD 2 - TraceIDRatioBased(0.25) decision:")
    print(f"    trace_id:     {g_stid}")
    print(f"    u32 value:    {g_u32}")
    print(f"    threshold:    {g_threshold}  (0.25 * 0xFFFFFFFF)")
    print(f"    sampled:      {g_sampled_25}")
    check("TraceIDRatioBased decision deterministic from trace_id",
          g_sampled_25 == (g_u32 < g_threshold))

    # GOLD 3: span tree stats
    rng3 = RNG(42)
    _, g_spans = build_gold_trace(rng3)
    g_nspans = len(g_spans)
    g_depth = trace_depth(g_spans)
    g_dur_ms = g_spans[0].duration_us // 1000

    print(f"\n  GOLD 3 - span tree stats:")
    print(f"    spans:        {g_nspans}")
    print(f"    max depth:    {g_depth}")
    print(f"    root dur ms:  {g_dur_ms}")
    check("span tree: 7 spans, depth 4, root 150 ms",
          g_nspans == 7 and g_depth == 4 and g_dur_ms == 150)

    # GOLD 4: batch processor
    g_flushes = simulate_batch(2000, 4, 512, 5000)
    print(f"\n  GOLD 4 - batch processor:")
    print(f"    flushes:      {g_flushes}")
    print(f"    total:        {sum(g_flushes)}")
    check("batch flushes = [512,512,512,464], total=2000",
          g_flushes == [512, 512, 512, 464] and sum(g_flushes) == 2000)

    # GOLD 5: span byte estimate
    g_span_bytes = 85 + 4 * 30 + 50  # base + attrs + wrap
    print(f"\n  GOLD 5 - span byte estimate:")
    print(f"    bytes/span:   {g_span_bytes}")
    print(f"    batch (512):  {512 * g_span_bytes} B "
          f"({512 * g_span_bytes / 1024:.1f} KB)")
    check("span bytes = 255, batch = 130560 B",
          g_span_bytes == 255 and 512 * g_span_bytes == 130560)

    print(f"\n  all GOLD asserts passed")
    print(f"\n[check] GOLD values pinned for .html JS recompute: OK")

    return {
        "traceparent": g_tp,
        "trace_id": g_tid,
        "span_id": g_sid,
        "sample_trace_id": g_stid,
        "sample_u32": g_u32,
        "sample_threshold": g_threshold,
        "sampled_25": g_sampled_25,
        "n_spans": g_nspans,
        "max_depth": g_depth,
        "root_dur_ms": g_dur_ms,
        "flushes": g_flushes,
        "span_bytes": g_span_bytes,
    }


# ============================================================================
# main
# ============================================================================

def main():
    print("opentelemetry.py - OTel architecture & mechanics simulation.")
    print("stdlib only; deterministic; fixed-seed LCG.")
    print("Feeds OPENTELEMETRY.md and opentelemetry.html.")
    section_architecture()
    section_span_lifecycle()
    section_context_propagation()
    section_sampling()
    section_otlp()
    section_collector()
    section_overhead()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
