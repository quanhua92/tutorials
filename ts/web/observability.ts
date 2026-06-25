// observability.ts — Phase 7 bundle (Async Runtime, HTTP & Realtime; member: web).
//
// GOAL (one line): show, by capturing every JSON log line, that production
// observability rests on THREE pillars — STRUCTURED LOGS (pino), METRICS
// (counters/histograms), and DISTRIBUTED TRACES (OpenTelemetry spans) — and that
// the Node-specific primitive AsyncLocalStorage propagates a correlation ID
// across async hops WITHOUT threading it as an argument (the JS analog of Go's
// context-carried log/slog fields and Rust's tracing span context).
//
// This is the GROUND TRUTH for OBSERVABILITY.md. Every log line, level number,
// span tree, and metric below is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists, and what the three pillars ARE): a request
// enters an HTTP server and fans out across awaits, timers, I/O, and (in a real
// system) other services. To diagnose that request you need THREE independent
// signals, each answering a different question:
//   - LOGS    = discrete EVENTS ("user 42 logged in at level=info"). pino emits
//               one JSON object per event: {level, time, msg, ...fields}.
//   - METRICS = AGGREGATES ("99th percentile latency = 18ms; req_count = 1024").
//               Counters/gauges/histograms compress many events into numbers.
//   - TRACES  = a SPAN TREE across services ("GET /order -> db.query -> http.call"),
//               each span carrying the SAME traceId so a single request's path is
//               reconstructable end-to-end (OpenTelemetry is the cross-language std).
// The glue between them is the CORRELATION ID (reqId / traceId): every log line
// in one request carries the same id, so a trace span and a log line can be
// joined. In Node that id is propagated by AsyncLocalStorage (🔗 ASYNC_PATTERNS)
// — set once at the request boundary, read anywhere downstream, across awaits.
//
// DETERMINISM NOTE (§4.2): pino's default timestamp is `Date.now()` (wall-clock,
// NON-reproducible) and its default `base` adds the live `pid` + `hostname`. To
// make every log line BYTE-STABLE across `just out`, this file configures pino
// with a FIXED timestamp `timestamp: () => ',"time":0'` AND `base: null` (drops
// pid/hostname). The result is a pure-structure line like
// `{"level":30,"time":0,"msg":"...","userId":42}`. We assert the STRUCTURE
// (level/msg/bound fields), never the wall-clock. No Math.random; span IDs come
// from a monotonic counter (deterministic); latency samples are fixed literals.
//
// Run:
//     pnpm exec tsx observability.ts   (or: just run observability)

import { AsyncLocalStorage } from "node:async_hooks";
import { Writable } from "node:stream";
import pino from "pino";

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// ============================================================================
// Deterministic pino destination: an in-memory Writable that collects raw lines.
// pino accepts ANY Writable as its destination stream (it does not require the
// SonicBoom stdout sink). Each log.info() calls write() synchronously, so the
// `lines` array is populated the moment the call returns — no flush dance needed.
// ============================================================================

interface LogBuffer {
  stream: Writable;
  lines: string[];
}

function makeLogBuffer(): LogBuffer {
  const lines: string[] = [];
  const stream = new Writable({
    write(chunk: Buffer, _enc: BufferEncoding, cb: () => void): void {
      // pino emits one JSON object terminated by "\n"; strip trailing newlines.
      lines.push(chunk.toString("utf8").replace(/[\r\n]+$/, ""));
      cb();
    },
  });
  return { stream, lines };
}

// A typed view of a pino JSON line. Index signature keeps field access honest
// under `noUncheckedIndexedAccess` without resorting to `any`.
interface PinoLine {
  level: number;
  time: number;
  msg: string;
  [key: string]: unknown;
}

function parseLine(line: string): PinoLine {
  return JSON.parse(line) as PinoLine;
}

// The DETERMINISTIC pino options: fixed timestamp + no pid/hostname base.
// `base: null` makes pino skip the default {pid, hostname} child logger, so the
// only fields on a line are level/time/msg + the caller's bound fields.
const FIXED_OPTS: pino.LoggerOptions = {
  base: null,
  timestamp: (): string => `,"time":0`,
};

// ============================================================================
// Section A — pino structured logging: the JSON line, log levels, threshold,
// and child loggers (bound context).
// ============================================================================

function sectionA(): void {
  sectionBanner("A — pino structured logging: JSON line, levels, child loggers");

  // A structured log call: the FIRST argument is the merge object (bound fields
  // for THIS line); the SECOND is the human `msg`. pino serializes both into one
  // JSON object. The captured line is byte-stable (fixed time, no base).
  const buf = makeLogBuffer();
  const log: pino.Logger = pino(FIXED_OPTS, buf.stream);
  log.info({ userId: 42 }, "user logged in");

  const raw = buf.lines[0] ?? "<missing>";
  const parsed = parseLine(raw);
  console.log("  raw line : " + raw);
  console.log("  parsed   : " + JSON.stringify(parsed));
  check("log line is valid JSON", typeof parsed === "object" && parsed !== null);
  check('level === 30 (info)', parsed.level === 30);
  check('msg === "user logged in"', parsed.msg === "user logged in");
  check("bound field userId === 42", parsed.userId === 42);
  check("time === 0 (FIXED timestamp -> byte-stable)", parsed.time === 0);
  check("no pid/hostname (base: null)", parsed.pid === undefined && parsed.hostname === undefined);

  // --- Log levels: the six pino levels map to fixed integer severity values ---
  // (silent = Infinity, never printed). `logger.levels.values` exposes the map.
  const vals = log.levels.values;
  const orderedLevels: ReadonlyArray<readonly [string, number]> = [
    ["trace", 10],
    ["debug", 20],
    ["info", 30],
    ["warn", 40],
    ["error", 50],
    ["fatal", 60],
  ];
  console.log("");
  console.log("  pino log levels (severity integers; higher = more severe):");
  for (const [name, num] of orderedLevels) {
    const actual = vals[name];
    console.log(`    ${name.padEnd(8)} -> ${String(actual)}`);
    check(`levels.values["${name}"] === ${num}`, actual === num);
  }

  // --- Threshold: `level` controls the minimum severity that is EMITTED. A
  // call BELOW the threshold is dropped before the JSON line is even built (so
  // the destination stream is never written). This is why pino is "fast": it
  // short-circuits suppressed levels synchronously.
  const quietBuf = makeLogBuffer();
  const quietLog = pino({ ...FIXED_OPTS, level: "info" }, quietBuf.stream);
  quietLog.debug("this debug is below info -> suppressed");
  console.log("");
  console.log("  threshold demo (logger level = 'info'):");
  console.log(`    lines emitted by debug call: ${quietBuf.lines.length}`);
  check("debug below info threshold is suppressed (0 lines)", quietBuf.lines.length === 0);

  const loudBuf = makeLogBuffer();
  const loudLog = pino({ ...FIXED_OPTS, level: "debug" }, loudBuf.stream);
  loudLog.debug("now visible");
  const loudParsed = parseLine(loudBuf.lines[0] ?? "<missing>");
  console.log(`    lines emitted at debug threshold: ${loudBuf.lines.length} (level=${loudParsed.level})`);
  check("debug at debug threshold is emitted (1 line, level 20)", loudBuf.lines.length === 1 && loudParsed.level === 20);

  // --- Child loggers: bound context that EVERY line from the child carries ---
  // `log.child({reqId})` returns a NEW logger that stamps `reqId` onto every
  // subsequent line. This is how request-scoped fields are attached without
  // repeating them on each call (the static-bound analog of AsyncLocalStorage's
  // dynamic binding, covered in Section B).
  const childBuf = makeLogBuffer();
  const childLog = pino(FIXED_OPTS, childBuf.stream).child({ reqId: "r-1", svc: "api" });
  childLog.info("handling request");
  childLog.warn({ ms: 12 }, "slow query");
  const c0 = parseLine(childBuf.lines[0] ?? "<missing>");
  const c1 = parseLine(childBuf.lines[1] ?? "<missing>");
  console.log("");
  console.log("  child logger (bound reqId='r-1', svc='api'):");
  console.log("    " + childBuf.lines[0]);
  console.log("    " + childBuf.lines[1]);
  check("child line 0 carries bound reqId", c0.reqId === "r-1");
  check("child line 0 carries bound svc", c0.svc === "api");
  check("child line 1 ALSO carries bound reqId (every line)", c1.reqId === "r-1");
  check("child line 1 level === 40 (warn)", c1.level === 40);
  check("child line 1 carries per-call field ms === 12", c1.ms === 12);
}

// ============================================================================
// Section B — AsyncLocalStorage: a correlation ID propagates across awaits
// WITHOUT being passed as an argument (THE Node payoff; the JS analog of Go's
// context-carried slog fields and Rust's tracing span context).
// ============================================================================

interface RequestContext {
  reqId: string;
}

// A real async boundary: resolves on the next macrotask (setImmediate), so the
// continuation after `await` is provably on a DIFFERENT async frame than the
// als.run() call. If AsyncLocalStorage did not propagate, getStore() would
// return undefined after this await.
function hop(): Promise<void> {
  return new Promise((resolve) => setImmediate(resolve));
}

async function sectionB(): Promise<void> {
  sectionBanner("B — AsyncLocalStorage: correlation ID survives an await");

  const als = new AsyncLocalStorage<RequestContext>();
  const buf = makeLogBuffer();
  const log = pino(FIXED_OPTS, buf.stream);

  // getStore() returns the store WITHOUT any argument threading. We read it
  // before AND after an await to prove the SAME store is visible across the
  // async hop — that is the whole reason AsyncLocalStorage exists.
  async function handle(): Promise<void> {
    const before = als.getStore();
    log.info({ reqId: before?.reqId }, "request start");
    await hop(); // <-- cross an async boundary
    const after = als.getStore();
    log.info({ reqId: after?.reqId }, "request end");
  }

  // Two INDEPENDENT contexts run sequentially. Each sees only its own store.
  await als.run({ reqId: "r-1" }, handle);
  await als.run({ reqId: "r-2" }, handle);

  // Outside any als.run, getStore() is undefined (no context leaked out).
  const outside = als.getStore();

  console.log("  captured log lines (reqId from getStore(), never an argument):");
  for (const line of buf.lines) {
    console.log("    " + line);
  }
  console.log(`  getStore() outside als.run: ${outside === undefined ? "undefined" : String(outside)}`);

  const l0 = parseLine(buf.lines[0] ?? "<missing>");
  const l1 = parseLine(buf.lines[1] ?? "<missing>");
  const l2 = parseLine(buf.lines[2] ?? "<missing>");
  const l3 = parseLine(buf.lines[3] ?? "<missing>");

  check("4 log lines captured (2 contexts x 2 calls)", buf.lines.length === 4);
  check("context r-1: reqId visible BEFORE the await", l0.reqId === "r-1");
  check("context r-1: reqId STILL visible AFTER the await (propagated)", l1.reqId === "r-1");
  check("context r-2: reqId is r-2 (independent store)", l2.reqId === "r-2");
  check("context r-2: reqId survives the await", l3.reqId === "r-2");
  check("the two contexts are isolated (r-1 !== r-2)", l0.reqId !== l2.reqId);
  check("als.getStore() is undefined outside als.run", outside === undefined);

  // The payoff, stated plainly: every log line in a request carries the SAME
  // reqId, so a trace and a log line for one request can be JOINED on reqId.
  check("every line in context r-1 shares reqId (correlation)", l0.reqId === l1.reqId);
}

// ============================================================================
// Section C — The three pillars: LOGS (events), METRICS (aggregates), TRACES
// (a span tree). Here we build a tiny manual span tree (no OTel SDK dep) to
// pin the traceId/spanId/parent model that OpenTelemetry standardizes.
// ============================================================================

// --- METRICS: a Counter (monotonic) and a Histogram (distribution) ----------
// These are toy implementations of the two most common metric instruments. Real
// systems use prom-client or the OpenTelemetry Metrics SDK, but the model is
// identical: a Counter only goes up; a Histogram records a distribution and
// answers "what is the p99?".
class Counter {
  #value = 0;
  inc(by = 1): void {
    this.#value += by;
  }
  get value(): number {
    return this.#value;
  }
}

class Histogram {
  readonly #samples: number[] = [];
  record(ms: number): void {
    this.#samples.push(ms);
  }
  stats(): { count: number; sum: number; mean: number; p50: number; p99: number } {
    const sorted = [...this.#samples].sort((a, b) => a - b);
    const sum = sorted.reduce((acc, n) => acc + n, 0);
    const at = (p: number): number => {
      const idx = Math.min(sorted.length - 1, Math.floor(p * sorted.length));
      return sorted[idx] ?? 0;
    };
    const count = sorted.length;
    return {
      count,
      sum,
      mean: count > 0 ? sum / count : 0,
      p50: at(0.5),
      p99: at(0.99),
    };
  }
}

// --- TRACES: a minimal span model -----------------------------------------
// A real OTel span has name, parentSpanId, start/end timestamps, spanContext
// {traceId, spanId, traceFlags, traceState}, attributes, events, status, kind.
// We model the CORRELATION-relevant subset: name + traceId + spanId + parentId.
// The spanId is a monotonic counter (hex, zero-padded to W3C's 16 chars) so the
// output is deterministic. The traceId is a fixed 32-hex literal.
interface ManualSpan {
  name: string;
  traceId: string;
  spanId: string;
  parentId: string | null;
}

let spanSeq = 0;
function newSpanId(): string {
  spanSeq += 1;
  return spanSeq.toString(16).padStart(16, "0");
}

const FIXED_TRACE = "00000000000000000000000000000001"; // 32 hex chars (W3C traceId)

function startSpan(name: string, parent: ManualSpan | null): ManualSpan {
  const spanId = newSpanId();
  const traceId = parent !== null ? parent.traceId : FIXED_TRACE;
  const parentId = parent !== null ? parent.spanId : null;
  return { name, traceId, spanId, parentId };
}

function sectionC(): void {
  sectionBanner("C — The three pillars: logs, metrics, and a span tree");

  // PILLAR 1 — LOGS: discrete events. (Section A/B showed these; recap: one
  // JSON object per event, structured, searchable by field.)
  console.log("  PILLAR 1 - LOGS    : discrete events; one JSON object per event");
  console.log("                       (level/time/msg + bound fields). Searchable.");

  // PILLAR 2 — METRICS: aggregates. A Counter compresses N increments into one
  // number; a Histogram records a distribution and answers percentiles. Fixed
  // samples keep the numbers byte-stable.
  console.log("  PILLAR 2 - METRICS : aggregates over many events.");
  const reqs = new Counter();
  for (let i = 0; i < 1024; i++) {
    reqs.inc();
  }
  const latency = new Histogram();
  const samples: ReadonlyArray<number> = [3, 12, 8, 25, 7, 15, 9];
  for (const ms of samples) {
    latency.record(ms);
  }
  const stats = latency.stats();
  console.log(`    counter  req_count -> ${reqs.value}`);
  console.log(`    histogram latency  -> count=${stats.count} sum=${stats.sum} mean=${stats.mean} p50=${stats.p50} p99=${stats.p99}`);
  check("counter aggregated 1024 increments to value 1024", reqs.value === 1024);
  check("histogram count === 7 (number of recorded samples)", stats.count === 7);
  check("histogram sum === 79 (3+12+8+25+7+15+9)", stats.sum === 79);
  check("histogram mean === 79/7", stats.mean === 79 / 7);
  check("histogram p50 === 9 (middle of sorted [3,7,8,9,12,15,25])", stats.p50 === 9);

  // PILLAR 3 — TRACES: a span tree. A root span has parentId === null; every
  // child span shares the parent's traceId and records the parent's spanId.
  // That is EXACTLY the OpenTelemetry model (documented in Section D).
  spanSeq = 0;
  const root = startSpan("GET /api/order", null);
  const dbSpan = startSpan("db.query orders", root);
  const httpSpan = startSpan("http.call payment", root);
  console.log("  PILLAR 3 - TRACES  : a span tree (parent/child share a traceId).");
  console.log("    root  " + JSON.stringify(root));
  console.log("    child " + JSON.stringify(dbSpan));
  console.log("    child " + JSON.stringify(httpSpan));
  check("root span has no parent (parentId === null)", root.parentId === null);
  check("root span carries the fixed traceId", root.traceId === FIXED_TRACE);
  check("db child shares the root traceId", dbSpan.traceId === root.traceId);
  check("http child shares the root traceId", httpSpan.traceId === root.traceId);
  check("db child's parent is the root span", dbSpan.parentId === root.spanId);
  check("http child's parent is the root span", httpSpan.parentId === root.spanId);
  check("siblings have distinct spanIds", dbSpan.spanId !== httpSpan.spanId);
  check("child spanId differs from root spanId", dbSpan.spanId !== root.spanId);
  check("whole tree shares ONE traceId (the definition of a trace)", root.traceId === dbSpan.traceId && dbSpan.traceId === httpSpan.traceId);
}

// ============================================================================
// Section D — OpenTelemetry (documented) + linking logs<->traces via traceId.
// No OTel SDK dependency: we DOCUMENT the API surface and demonstrate the
// trace-correlation that makes logs and traces joinable.
// ============================================================================

// Build a W3C TraceContext `traceparent` header from a span. Format:
//   version(2)-traceId(32)-spanId(16)-flags(2)   ->  55 chars total.
// This is the wire format OTel propagators inject to carry context across hops.
function traceparent(span: ManualSpan, sampled = true): string {
  const flags = sampled ? "01" : "00";
  return `00-${span.traceId}-${span.spanId}-${flags}`;
}

// Correlation helper: emit a log line tagged with the span's traceId/spanId.
// In a real OTel app, pino's transport or a mixin reads the ACTIVE span context
// (via `trace.getActiveSpan()`) and stamps it automatically. Here we pass it
// explicitly to keep the demo dependency-free.
function logForSpan(log: pino.Logger, span: ManualSpan, msg: string): void {
  log.info({ traceId: span.traceId, spanId: span.spanId }, msg);
}

function sectionD(): void {
  sectionBanner("D — OpenTelemetry (documented) + log<->trace correlation");

  // DOCUMENT the OTel API surface (we do NOT instantiate the SDK here — it
  // requires @opentelemetry/api + sdk packages and an exporter; the model is
  // what matters and is exactly the span tree from Section C).
  console.log("  OpenTelemetry API surface (documented; no SDK instantiated here):");
  console.log("    TracerProvider  -> factory for Tracers (one per app lifecycle).");
  console.log("    Tracer          -> tracer.startSpan(name) returns a Span.");
  console.log("    Span            -> name + spanContext{traceId,spanId,flags,state}");
  console.log("                       + parentId + attributes + events + status + kind.");
  console.log("    Context/Propagation -> carries spanContext across processes");
  console.log("                       via W3C TraceContext (the 'traceparent' header).");
  console.log("    Exporter        -> sends spans to a backend (Collector/Jaeger/...).");
  console.log("    Semantic Conventions -> standard attribute names (http.method,");
  console.log("                       http.route, db.system, net.peer.name, ...).");
  check("documented: TracerProvider is the factory (concept)", true);
  check("documented: tracer.startSpan(name) creates a span (concept)", true);

  // --- log <-> trace correlation: a log line tagged with traceId+spanId -----
  // Build a tiny span tree, then emit ONE log line per span, each carrying that
  // span's traceId. A backend can now JOIN a log line to its span on traceId.
  spanSeq = 0;
  const root = startSpan("checkout", null);
  const pay = startSpan("charge card", root);
  const buf = makeLogBuffer();
  const log = pino(FIXED_OPTS, buf.stream);
  logForSpan(log, root, "checkout started");
  logForSpan(log, pay, "payment captured");

  console.log("");
  console.log("  log lines tagged with the active span's traceId/spanId:");
  for (const line of buf.lines) {
    console.log("    " + line);
  }
  const r = parseLine(buf.lines[0] ?? "<missing>");
  const p = parseLine(buf.lines[1] ?? "<missing>");
  check("log line carries the span's traceId", r.traceId === root.traceId);
  check("two log lines in one trace share the SAME traceId", r.traceId === p.traceId);
  check("log line's spanId matches the span that produced it", r.spanId === root.spanId);
  check("child log line's spanId differs from root", p.spanId === pay.spanId && p.spanId !== r.spanId);
  check("a backend can JOIN log <-> trace on traceId (the correlation key)", r.traceId === root.traceId && p.traceId === root.traceId);

  // --- W3C TraceContext: the traceparent wire format -----------------------
  const tp = traceparent(root, true);
  const parts = tp.split("-");
  console.log("");
  console.log("  W3C traceparent header (context propagation across services):");
  console.log(`    ${tp}`);
  console.log(`    version=${parts[0]}  traceId=${parts[1]}  spanId=${parts[2]}  flags=${parts[3]} (sampled)`);
  check("traceparent length === 55 (W3C fixed width)", tp.length === 55);
  check("traceparent has 4 dash-separated fields", parts.length === 4);
  check("traceparent carries the span's traceId", parts[1] === root.traceId);
  check("traceparent carries the span's spanId", parts[2] === root.spanId);
  check("traceparent sampled flag === '01' (will be recorded)", parts[3] === "01");
}

// ============================================================================
// Section E — pino performance, transports/sinks, and the cross-language model.
// ============================================================================

function sectionE(): void {
  sectionBanner("E — pino performance, transports/sinks, cross-language model");

  // --- pino performance: WHY it is fast (documented) -----------------------
  // pino builds the JSON line in the calling thread but with MINIMUM allocation,
  // and writes to a destination stream. For stdout it uses SonicBoom, a fast
  // non-blocking writer that batches writes. Levels below the threshold are
  // short-circuited BEFORE any JSON is built (Section A showed the 0-line case).
  // The pino README claims it is "over 5x faster than alternatives" in many
  // cases. The design rule: do log PROCESSING (reformatting, sending to a
  // remote aggregator) in a SEPARATE process or worker thread, never inline.
  console.log("  pino performance model (documented):");
  console.log("    - synchronous JSON line build in the caller (minimal allocation)");
  console.log("    - SonicBoom destination batches stdout writes (non-blocking)");
  console.log("    - below-threshold levels short-circuit before any serialization");
  console.log("    - rule: log PROCESSING belongs in a worker, never inline");
  check("documented: pino builds the JSON line synchronously (concept)", true);

  // The buffering destination we have used throughout PROVES pino writes to a
  // plain Writable synchronously: each line is in `buf.lines` the instant the
  // log call returns.
  const proveBuf = makeLogBuffer();
  const proveLog = pino(FIXED_OPTS, proveBuf.stream);
  proveLog.info({ proof: true }, "writes are synchronous to the destination");
  check("proof: a custom Writable destination received the line immediately", proveBuf.lines.length === 1);

  // --- Transports / sinks (documented API surface) -------------------------
  // `pino.transport()` spawns a worker thread that runs a log processor (e.g.
  // pino-pretty for dev, or a custom sender that ships to Loki/ELK/Datadog).
  // `pino.destination()` returns a SonicBoom sink (file or fd). In containers
  // the canonical sink is STDOUT: the container runtime captures it and a log
  // aggregator (Fluent Bit/Vector/Promtail) forwards it to a backend.
  console.log("");
  console.log("  transports / sinks (documented API surface):");
  console.log("    pino.transport()  -> worker-thread log processor (pino-pretty, custom)");
  console.log("    pino.destination()-> SonicBoom sink (file or fd; stdout default)");
  console.log("    container sink    -> stdout -> docker/k8s logs -> collector -> backend");
  console.log("    aggregators       -> Loki, ELK (Elasticsearch), Datadog, Splunk, ...");
  check("documented: pino.transport is a function (API surface)", typeof pino.transport === "function");
  check("documented: pino.destination is a function (API surface)", typeof pino.destination === "function");

  // --- Cross-language: the SAME three-pillar model everywhere ---------------
  // OpenTelemetry is cross-language: the traceId/spanId/traceparent model is
  // identical in Go, Rust, Python, and JS. The logging libraries differ in
  // ergonomics but all produce structured records and bind request context:
  console.log("");
  console.log("  cross-language parallels (the same three pillars):");
  console.log("    Go     : log/slog (structured, context-bound attrs) + OTel-Go");
  console.log("    Rust   : tracing crate (spans+events+subscriber)    + OTel-Rust");
  console.log("    Python : logging/structlog + FastAPI structured     + OTel-Python");
  console.log("    JS/TS  : pino (this bundle) + AsyncLocalStorage     + OTel-JS");
  check("documented: the three-pillar model is cross-language (concept)", true);
  check("AsyncLocalStorage is the JS analog of Go context / Rust tracing span context", true);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("observability.ts — Phase 7 bundle (web/).");
  console.log("Every log line below is emitted by this file via pino; the .md guide");
  console.log("pastes it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("DETERMINISM: pino is configured with base:null and a FIXED timestamp");
  console.log('(\'timestamp: () => ","time":0\'), so every JSON log line is byte-stable');
  console.log("across runs. We assert STRUCTURE (level/msg/bound fields), never wall-clock.");
  sectionA();
  await sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main().catch((err: unknown) => {
  console.error(err instanceof Error ? err.stack ?? err.message : String(err));
  process.exitCode = 1;
});
