//! tracing_basics.rs — Phase 7 bundle.
//!
//! GOAL (one line): show, by capturing every record into a buffer, that
//! `tracing` emits STRUCTURED diagnostic records — {level, message, fields,
//! span-context} — routed by a pluggable `Subscriber`, and that the span
//! context propagates across `.await` points (the async-aware part).
//!
//! This is the GROUND TRUTH for TRACING_BASICS.md. Every captured line and
//! substring assertion below is produced by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM NOTE: tracing's default `fmt` output embeds a wall-clock
//! TIMESTAMP (and may embed thread ids) — both vary per run, so the raw output
//! is NOT byte-identical across runs. This binary neutralizes ALL of them:
//! `.without_time()` drops the timestamp; `.with_ansi(false)` drops color
//! escapes; thread ids stay OFF by default (we never call
//! `.with_thread_ids(true)`). Every record is captured into an in-memory
//! `Arc<Mutex<Vec<u8>>>` buffer via a custom `MakeWriter`, then inspected with
//! substring `check(...)`s. We assert on the STRUCTURED FIELDS we logged, never
//! on timestamps. Two `just out tracing_basics` runs are byte-identical.
//!
//! Run:
//!     just run tracing_basics   (== cargo run --bin tracing_basics)

use std::io::{self, Write};
use std::sync::{Arc, Mutex, MutexGuard};

use tracing_subscriber::filter::LevelFilter;
use tracing_subscriber::fmt::MakeWriter;
use tracing_subscriber::util::SubscriberInitExt;

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar = "=".repeat(BANNER_WIDTH);
    println!("\n{bar}\nSECTION {title}\n{bar}");
}

/// Assert an invariant and print a uniform `[check] ...: OK` line.
/// Panics on failure (non-zero exit) so `just check` / `just sweep` catch it.
fn check(desc: &str, ok: bool) {
    if !ok {
        panic!("INVARIANT VIOLATED: {desc}");
    }
    println!("[check] {desc}: OK");
}

// ── A custom MakeWriter: route tracing records into an Arc<Mutex<Vec<u8>>> ──

/// Owns one handle to the shared capture buffer. Implements `MakeWriter` so
/// `tracing_subscriber::fmt().with_writer(capture)` can write records into it.
/// We keep a second `Arc` clone to read the buffer back out after the section.
struct Capture {
    buf: Arc<Mutex<Vec<u8>>>,
}

impl<'a> MakeWriter<'a> for Capture {
    type Writer = CaptureWriter<'a>;
    fn make_writer(&'a self) -> Self::Writer {
        CaptureWriter {
            guard: self.buf.lock().expect("capture mutex poisoned"),
        }
    }
}

/// A `Write` adapter over a `MutexGuard<Vec<u8>>`. One is created per record
/// (the fmt layer calls `make_writer` for each event), so writes serialize.
struct CaptureWriter<'a> {
    guard: MutexGuard<'a, Vec<u8>>,
}

impl Write for CaptureWriter<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.guard.extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

/// Build a SCOPED (thread-local, via `set_default`) fmt subscriber that writes
/// to a fresh buffer with the timestamp + ANSI neutralized. Returns the buffer
/// handle and the default-guard. Dropping the guard restores the prior default
/// — so each section gets its own independent subscriber + buffer.
fn scoped_capture(
    max_level: LevelFilter,
) -> (Arc<Mutex<Vec<u8>>>, tracing::subscriber::DefaultGuard) {
    let buf = Arc::new(Mutex::new(Vec::<u8>::new()));
    let writer = Capture { buf: buf.clone() };
    let guard = tracing_subscriber::fmt()
        .with_writer(writer)
        .with_ansi(false)
        .without_time()
        .with_target(false)
        .with_max_level(max_level)
        .set_default();
    (buf, guard)
}

/// Drain the buffer into a `String` (after the section's records are emitted).
fn drain(buf: &Arc<Mutex<Vec<u8>>>) -> String {
    let guard = buf.lock().expect("capture mutex poisoned");
    String::from_utf8_lossy(&guard).into_owned()
}

/// Print the captured buffer verbatim, so it appears in stdout alongside the
/// `check(...)` lines (the records themselves are at column 0 on purpose).
fn show(captured: &str) {
    println!("  // --- captured tracing records (timestamp dropped, ANSI off) ---");
    print!("{captured}");
}

// ── Section A: events + levels — a record is {level, message, fields} ────────

fn section_a() {
    banner("A — events + levels: a record is {level, message, fields}");
    println!("  // An EVENT is a single point-in-time record. Each carries a LEVEL");
    println!("  // (ERROR > WARN > INFO > DEBUG > TRACE) and STRUCTURED FIELDS, not");
    println!("  // just a flat string. The Subscriber decides where each record goes.");

    let (buf, _guard) = scoped_capture(LevelFilter::TRACE);
    // Fields come BEFORE the message format string (tracing grammar). This also
    // keeps rustc's format-args checker happy: "app started" has no placeholders
    // and no trailing format args.
    tracing::info!(version = "1.0", "app started");
    tracing::warn!(percent = 95_u32, "disk almost full");
    tracing::error!(status = 500_u32, "request failed");

    let captured = drain(&buf);
    show(&captured);

    check(
        "info! event message 'app started' is captured",
        captured.contains("app started"),
    );
    check(
        "structured field version=\"1.0\" is captured (strings are quoted)",
        captured.contains("version=\"1.0\""),
    );
    check(
        "warn! field percent=95 is captured",
        captured.contains("percent=95"),
    );
    check(
        "error! field status=500 is captured",
        captured.contains("status=500"),
    );
    check(
        "level INFO appears in the record",
        captured.contains("INFO"),
    );
    check(
        "level WARN appears in the record",
        captured.contains("WARN"),
    );
    check(
        "level ERROR appears in the record",
        captured.contains("ERROR"),
    );
}

// ── Section B: spans — a structured scope; events inside carry the context ──

fn section_b() {
    banner("B — spans: a structured scope; events inside carry the context");
    println!("  // A SPAN is a PERIOD of time (a scope), unlike an event's instant.");
    println!("  // `.enter()` returns an RAII guard: while it lives, the span is the");
    println!("  // current context, so events inside it are tagged with the span.");
    println!("  // (The `enter` guard must NOT be held across `.await` — Section F.)");

    let (buf, _guard) = scoped_capture(LevelFilter::INFO);
    let span = tracing::info_span!("request", id = "req-42");
    {
        let _enter = span.enter(); // current context = "request" until `_enter` drops
        tracing::info!("handling request");
        tracing::info!("finished request");
    } // `_enter` drops here -> span context ends

    let captured = drain(&buf);
    show(&captured);

    check(
        "span name 'request' appears as context",
        captured.contains("request"),
    );
    check(
        "span field id=\"req-42\" appears (strings are quoted)",
        captured.contains("id=\"req-42\""),
    );
    check(
        "event 'handling request' is recorded inside the span",
        captured.contains("handling request"),
    );
    check(
        "event 'finished request' is recorded inside the span",
        captured.contains("finished request"),
    );
}

// ── Section C: fields are STRUCTURED (queryable), not flat text ──────────────

fn section_c() {
    banner("C — fields are STRUCTURED (queryable), not flat text");
    println!("  // Unlike `println!`, tracing fields are KEY=VALUE data. A downstream");
    println!("  // subscriber (Honeycomb/OpenTelemetry/journald/...) can INDEX");
    println!("  // 'count=3' as a field rather than grep it out of a string.");

    let (buf, _guard) = scoped_capture(LevelFilter::INFO);
    let order_id = "ord-7";
    tracing::info!(
        order_id,
        count = 3_u32,
        total_cents = 4999_u32,
        "order placed"
    );

    let captured = drain(&buf);
    show(&captured);

    check(
        "count=3 is a structured field",
        captured.contains("count=3"),
    );
    check(
        "total_cents=4999 is a structured field",
        captured.contains("total_cents=4999"),
    );
    check(
        "field-init shorthand records order_id=\"ord-7\"",
        captured.contains("order_id=\"ord-7\""),
    );
}

// ── Section D: level filtering — INFO is DROPPED when max level is WARN ──────

fn section_d() {
    banner("D — level filtering: INFO is DROPPED when max level is WARN");
    println!("  // `.with_max_level(WARN)` makes the subscriber drop every record below");
    println!("  // WARN — BEFORE it is even formatted (cheap). We emit one INFO and one");
    println!("  // WARN record and assert the INFO one is absent, the WARN one present.");

    let (buf, _guard) = scoped_capture(LevelFilter::WARN);
    tracing::info!("FILTERED_INFO_RECORD_should_be_dropped");
    tracing::warn!("KEPT_WARN_RECORD_should_survive");

    let captured = drain(&buf);
    show(&captured);

    check(
        "INFO record is DROPPED under max_level=WARN",
        !captured.contains("FILTERED_INFO_RECORD_should_be_dropped"),
    );
    check(
        "WARN record SURVIVES under max_level=WARN",
        captured.contains("KEPT_WARN_RECORD_should_survive"),
    );
}

// ── Section E: #[tracing::instrument] auto-names the span after the fn ───────

#[tracing::instrument]
fn do_thing(magic: u32) -> u32 {
    tracing::info!("working inside do_thing");
    magic + 1
}

fn section_e() {
    banner("E — #[tracing::instrument]: span auto-named after the fn");
    println!("  // `#[tracing::instrument]` on `fn do_thing(magic)` creates + enters a");
    println!("  // span named 'do_thing' with `magic` recorded as a field, on every");
    println!("  // call (default level INFO). The event inside carries that span.");

    let (buf, _guard) = scoped_capture(LevelFilter::INFO);
    let out = do_thing(7);
    let captured = drain(&buf);
    show(&captured);

    check("instrumented fn returns magic+1 = 8", out == 8);
    check(
        "a span named 'do_thing' appears as context",
        captured.contains("do_thing"),
    );
    check(
        "instrument records the arg as a field magic=7",
        captured.contains("magic=7"),
    );
    check(
        "event 'working inside do_thing' is captured",
        captured.contains("working inside do_thing"),
    );
}

// ── Section F: context propagates across `.await` via #[instrument] ───────────

#[tracing::instrument]
async fn fetch_with_context() -> u32 {
    tracing::info!("before yield (poll 1)");
    tokio::task::yield_now().await; // suspend point: the future returns Pending
    tracing::info!("after yield (poll 2) - STILL inside fetch_with_context");
    42
}

async fn section_f() {
    banner("F — context propagates across .await (#[instrument] on async fn)");
    println!("  // `#[instrument]` on an ASYNC fn instruments the returned FUTURE: it");
    println!("  // ENTERS the span on every poll and EXITS on every return. So an event");
    println!("  // emitted AFTER an `.await` still carries the span — even though the");
    println!("  // future was suspended and resumed (possibly on another thread).");
    println!("  // Contrast: a hand `span.enter()` guard held across `.await` is UNSOUND");

    let (buf, _guard) = scoped_capture(LevelFilter::INFO);
    let n = fetch_with_context().await;
    let captured = drain(&buf);
    show(&captured);

    check("instrumented async fn returns 42", n == 42);
    check(
        "pre-await event captured",
        captured.contains("before yield (poll 1)"),
    );
    check(
        "post-await event captured",
        captured.contains("after yield (poll 2)"),
    );
    check(
        "span 'fetch_with_context' wraps BOTH polls (carries across .await)",
        captured.matches("fetch_with_context").count() >= 2,
    );
}

#[tokio::main]
async fn main() {
    println!("tracing_basics.rs — Phase 7 bundle (async member).");
    println!("Every captured record below is produced by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f().await;
    banner("DONE — all sections printed");
}
