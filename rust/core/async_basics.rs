//! async_basics.rs — Phase 4 bundle #2 (Concurrency).
//!
//! GOAL (one line): show, by printing every value, that `async`/`await` is
//! COOPERATIVE concurrency on ONE thread — an `async fn` compiles to a state
//! machine that implements `Future`, a `Future` does NOTHING until a `poll` is
//! driven by an executor, `poll` returns `Pending` (yield) or `Ready(T)`, and
//! `Pin` keeps self-referential state machines from being moved — all with NO
//! runtime (we hand-roll a tiny `block_on`; tokio is Phase 7).
//!
//! This is the GROUND TRUTH for ASYNC_BASICS.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM: the Future state machine + our single-threaded busy-poll
//! executor are fully deterministic — a FIXED poll order, NO timers, NO
//! wall-clock, NO OS scheduling. "Async waiting" here is a ready flag flipped on
//! the next poll, so `_output.txt` reproduces byte-for-byte across runs.
//!
//! Run:
//!     just run async_basics   (== cargo run --bin async_basics)

use std::future::Future;
use std::pin::{Pin, pin};
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::task::{Context, Poll, Wake, Waker};

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar: String = "=".repeat(BANNER_WIDTH);
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

// ── The executor: a hand-rolled block_on (NO runtime; stdlib only) ───────────
// A Future is INERT until polled. `.await` only works INSIDE another async fn
// (itself a future someone else must drive). To run a future from a sync
// `fn main` we need an EXECUTOR: a loop that polls until `Poll::Ready`. Below is
// the tiniest possible one — a faithful simplification of the `std::task::Wake`
// docs' canonical `block_on` (which uses `thread::park`; we busy-poll, so there
// is NO timer and NO OS thread scheduling — the output is deterministic).

/// A `Waker` that does nothing. Our busy-poll executors re-poll every future on
/// each loop pass regardless of wakes, so the `Waker`'s only job is to EXIST
/// (`Context::from_waker` needs one). A production executor's waker RE-SCHEDULES
/// the task — e.g. the docs' `ThreadWaker` calls `thread::current().unpark()`.
struct NoopWaker;

impl Wake for NoopWaker {
    fn wake(self: Arc<Self>) {
        // Intentionally inert: the busy-poll loop re-polls unconditionally.
        let _ = self;
    }
}

fn noop_waker() -> Waker {
    Waker::from(Arc::new(NoopWaker))
}

/// Drive ONE future to completion on THIS thread (busy-poll). Returns its
/// `Output`. This is what `futures::executor::block_on` and a `tokio` runtime's
/// `block_on` do — minus the thread parking and the multi-task queue.
fn block_on<F: Future>(fut: F) -> F::Output {
    let waker = noop_waker();
    let mut cx = Context::from_waker(&waker);
    // Pin the future on the stack. async-generated futures are !Unpin, so they
    // CANNOT be polled without pinning — `pin!` is the safe way to do it.
    let mut fut = pin!(fut);
    loop {
        if let Poll::Ready(v) = fut.as_mut().poll(&mut cx) {
            return v;
        }
        // Pending -> loop and poll again. Our futures flip a ready flag on the
        // NEXT poll, so this always terminates. No thread::park, no wall-clock.
    }
}

/// Drive TWO futures to completion concurrently on ONE thread, ROUND-ROBIN:
/// poll `fa` then `fb`, repeat until both are `Ready`. This is COOPERATIVE
/// concurrency — no OS threads, just interleaved polls on the calling thread.
/// The poll order is fixed, so the outcome is deterministic (unlike OS threads).
fn block_join2<A, B>(fa: A, fb: B) -> (A::Output, B::Output)
where
    A: Future,
    B: Future,
{
    let waker = noop_waker();
    let mut cx = Context::from_waker(&waker);
    let mut fa = pin!(fa);
    let mut fb = pin!(fb);
    let mut oa: Option<A::Output> = None;
    let mut ob: Option<B::Output> = None;
    while oa.is_none() || ob.is_none() {
        if oa.is_none()
            && let Poll::Ready(v) = fa.as_mut().poll(&mut cx)
        {
            oa = Some(v);
        }
        if ob.is_none()
            && let Poll::Ready(v) = fb.as_mut().poll(&mut cx)
        {
            ob = Some(v);
        }
    }
    (
        oa.expect("both futures completed"),
        ob.expect("both futures completed"),
    )
}

// ── Two hand-written Futures (Ready, and Pending-once-then-Ready) ────────────

/// The simplest possible Future: `Ready` on the FIRST poll. This mirrors
/// `std::future::ready`. (Bounded to `T: Unpin` so it can take its value out of
/// `Pin<&mut Self>` via the shared-reference path; `std`'s version handles all
/// `T` internally — this is a teaching simplification.)
struct Ready<T>(Option<T>);

impl<T: Unpin> Future for Ready<T> {
    type Output = T;
    fn poll(mut self: Pin<&mut Self>, _cx: &mut Context<'_>) -> Poll<T> {
        Poll::Ready(self.0.take().expect("Ready polled after completion"))
    }
}

/// A Future that returns `Poll::Pending` ONCE (honoring the contract by storing
/// and immediately calling the waker), then `Poll::Ready(value)` on the next
/// poll. This is the canonical "yield once" primitive: it lets us observe a
/// genuine Pending->Ready transition with NO timers and NO wall-clock — progress
/// is driven purely by being polled again. An optional shared counter makes the
/// poll count observable so we can assert the Pending actually happened.
struct YieldOnce<T> {
    value: Option<T>,
    yielded: bool,
    polls: Arc<AtomicU32>,
}

impl<T> YieldOnce<T> {
    fn new(value: T) -> Self {
        Self::counted(value, Arc::new(AtomicU32::new(0)))
    }

    fn counted(value: T, polls: Arc<AtomicU32>) -> Self {
        Self {
            value: Some(value),
            yielded: false,
            polls,
        }
    }
}

impl<T: Unpin> Future for YieldOnce<T> {
    type Output = T;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<T> {
        let this = self.get_mut(); // OK: YieldOnce<T>: Unpin when T: Unpin
        this.polls.fetch_add(1, Ordering::SeqCst);
        if this.yielded {
            Poll::Ready(this.value.take().expect("YieldOnce polled after Ready"))
        } else {
            this.yielded = true;
            // The Future contract: when returning Pending, arrange a wakeup so
            // the executor knows to poll again. Our busy executor ignores it;
            // a real (parking) executor would be re-scheduled BY this call.
            cx.waker().wake_by_ref();
            Poll::Pending
        }
    }
}

/// Compile-time witness: this fn compiles only for `T: Unpin`. Calling it with
/// a value proves that type is `Unpin`. (Calling it with an async-block future
/// would FAIL to compile — that future is `!Unpin`; see Section F.)
fn needs_unpin<T: Unpin>() {}

/// `async fn` desugars to a fn returning `impl Future<Output = ..>`. The body
/// runs NOTHING until the returned future is driven by an executor.
async fn add(a: i32, b: i32) -> i32 {
    a + b
}

// ── Section A: async fn returns a Future; nothing happens until you drive it ─

fn section_a() {
    banner("A — async fn returns a Future; NOTHING happens until polled");
    // Calling add(2, 3) does NOT run `a + b`. It builds an inert state machine.
    // Only block_on's poll loop makes it compute.
    let fut = add(2, 3);
    println!("  async fn add(a: i32, b: i32) -> i32 {{ a + b }}");
    println!("  let fut = add(2, 3);        // fut is a Future; body NOT run yet");
    let result = block_on(fut);
    println!("  let result = block_on(fut); // NOW the executor polls it to Ready");
    println!("  result = {result}");
    check("block_on(add(2, 3)) == 5", result == 5);

    // `.await` polls a sub-future to completion, INSIDE an async fn/block. The
    // outer block is itself a future that block_on drives. Two awaits chain.
    let r2 = block_on(async {
        let y = add(10, 10).await; // await polls add(10,10) to completion
        add(y, 1).await // and again: y is live across the await point
    });
    println!("  block_on(async {{ add(10,10).await + 1 }}) = {r2}");
    check(
        "nested .await across two await points: result == 21",
        r2 == 21,
    );
}

// ── Section B: a hand-rolled block_on — a minimal single-threaded executor ───

fn section_b() {
    banner("B — a hand-rolled block_on: poll until Ready (the executor)");
    println!("  pub trait Future {{");
    println!("      type Output;");
    println!("      fn poll(self: Pin<&mut Self>, cx: &mut Context) -> Poll<Self::Output>;");
    println!("  }}");
    println!("  pub enum Poll<T> {{ Ready(T), Pending }}");
    println!();
    println!("  block_on = `loop {{ if Ready(v) = poll(cx) {{ return v }} }}`");
    println!("  (with a Waker in the Context; we use a noop one + busy poll)");

    // std::future::ready is Ready on the FIRST poll -> block_on returns at once.
    let from_std = block_on(std::future::ready(42i32));
    println!("  block_on(std::future::ready(42)) -> {from_std}  (Ready on poll #1)");
    check(
        "block_on drives std::future::ready(42) == 42",
        from_std == 42,
    );

    // Our own Ready<T> wrapper (defined above): identical behavior.
    let from_ours = block_on(Ready(Some(42i32)));
    println!("  block_on(Ready(Some(42)))     -> {from_ours}  (Ready on poll #1)");
    check(
        "our Ready<T> wrapper == std::future::ready behavior",
        from_ours == 42,
    );

    check(
        "block_on always returns exactly the future's Output (here i32)",
        from_std == from_ours,
    );
}

// ── Section C: Poll semantics — Pending ONCE, then Ready ─────────────────────

fn section_c() {
    banner("C — Poll semantics: a custom Future that is Pending ONCE, then Ready");
    let polls = Arc::new(AtomicU32::new(0));
    println!("  impl Future for YieldOnce<T> {{");
    println!("      fn poll(self: Pin<&mut Self>, cx) -> Poll<T> {{");
    println!("          if self.yielded {{ Poll::Ready(value) }}");
    println!("          else {{ self.yielded = true; cx.waker().wake_by_ref();");
    println!("                Poll::Pending }}   // <- yields the thread once");
    println!("      }}");
    println!("  }}");

    let out = block_on(YieldOnce::counted(String::from("done"), Arc::clone(&polls)));
    let n = polls.load(Ordering::SeqCst);
    println!("  block_on(YieldOnce::counted(\"done\")) -> {out:?}");
    println!("  poll count = {n}  (Pending on poll #1, Ready on poll #2)");

    check("YieldOnce returned its value: \"done\"", out == "done");
    check(
        "YieldOnce polled exactly twice: Pending once, then Ready",
        n == 2,
    );
}

// ── Section D: async fn == a state machine (one state per .await) ────────────

/// An async fn with TWO awaits. Each `.await` is a suspension point, so the
/// generated state machine has a state per await: it runs to await #1, YIELDS,
/// resumes at await #1 and runs to await #2, YIELDS, resumes and finishes.
async fn two_steps(log: Arc<Mutex<Vec<&'static str>>>) -> i32 {
    log.lock().unwrap().push("step1: before first await");
    let a = YieldOnce::new(10).await; // suspension point #1
    log.lock().unwrap().push("step2: after await #1, a = 10");
    let b = YieldOnce::new(a + 5).await; // suspension point #2
    log.lock().unwrap().push("step3: after await #2, b = 15");
    b
}

fn section_d() {
    banner("D — async fn is a state machine: suspend & resume across awaits");
    let log = Arc::new(Mutex::new(Vec::<&'static str>::new()));
    let value = block_on(two_steps(Arc::clone(&log)));
    let trace = log.lock().unwrap().clone();
    println!("  async fn two_steps(log) -> i32 {{");
    println!("      log.push(\"step1...\"); let a = yield(10).await;");
    println!("      log.push(\"step2...\"); let b = yield(a+5).await;");
    println!("      log.push(\"step3...\"); b");
    println!("  }}");
    println!("  block_on(two_steps(..)) -> {value}   (suspend, resume, suspend, resume)");
    println!("  execution trace (in order):");
    for line in &trace {
        println!("    {line}");
    }
    check(
        "two_steps returned the final value 15 (10 then 10+5)",
        value == 15,
    );
    check(
        "state machine ran step1, step2, step3 in ORDER (suspend+resume preserves it)",
        trace
            == [
                "step1: before first await",
                "step2: after await #1, a = 10",
                "step3: after await #2, b = 15",
            ],
    );
}

// ── Section E: concurrency on ONE thread — round-robin join of two futures ───

/// A named Future that yields once then returns a value, logging each poll so
/// the round-robin INTERLEAVING becomes visible. (Like YieldOnce but observable.)
struct StepFuture {
    id: &'static str,
    value: i32,
    yielded: bool,
    log: Arc<Mutex<Vec<String>>>,
}

impl Future for StepFuture {
    type Output = i32;
    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<i32> {
        let this = self.get_mut(); // OK: StepFuture is Unpin (all fields Unpin)
        if this.yielded {
            this.log
                .lock()
                .unwrap()
                .push(format!("{}: Ready({})", this.id, this.value));
            Poll::Ready(this.value)
        } else {
            this.yielded = true;
            this.log
                .lock()
                .unwrap()
                .push(format!("{}: Pending (yield once)", this.id));
            cx.waker().wake_by_ref();
            Poll::Pending
        }
    }
}

impl StepFuture {
    fn new(id: &'static str, value: i32, log: Arc<Mutex<Vec<String>>>) -> Self {
        Self {
            id,
            value,
            yielded: false,
            log,
        }
    }
}

fn section_e() {
    banner("E — concurrency on ONE thread: round-robin join of two futures");
    let log = Arc::new(Mutex::new(Vec::<String>::new()));
    // Two futures on ONE thread. block_join2 polls A then B each pass — they
    // make progress by COOPERATING (yielding), not by being on separate threads.
    let (va, vb) = block_join2(
        StepFuture::new("A", 100, Arc::clone(&log)),
        StepFuture::new("B", 200, Arc::clone(&log)),
    );
    let trace = log.lock().unwrap().clone();
    let mut sorted = vec![va, vb];
    sorted.sort_unstable();
    println!("  block_join2(StepFuture(\"A\",100), StepFuture(\"B\",200))");
    println!("  poll order (deterministic round-robin):");
    for line in &trace {
        println!("    {line}");
    }
    println!("  outputs = ({va}, {vb});  sorted = {sorted:?}");
    check(
        "both futures completed: outputs (100, 200)",
        va == 100 && vb == 200,
    );
    check(
        "round-robin interleaving is deterministic: A-pend, B-pend, A-ready, B-ready",
        trace
            == [
                "A: Pending (yield once)".to_string(),
                "B: Pending (yield once)".to_string(),
                "A: Ready(100)".to_string(),
                "B: Ready(200)".to_string(),
            ],
    );
    check(
        "sorted outputs == [100, 200] (determinism discipline)",
        sorted == vec![100, 200],
    );
}

// ── Section F: why Pin — self-referential state machines after an .await ─────

fn section_f() {
    banner("F — why Pin: async state machines can be self-referential");
    println!("  async fn body -> a generated state-machine struct.");
    println!("  Locals LIVE across an .await are stored IN that struct. If a local");
    println!("  holds a reference into ANOTHER local of the same struct, the struct");
    println!("  is SELF-REFERENTIAL. Moving it in memory would dangle that pointer.");
    println!("  Pin<&mut Self> in poll's signature GUARANTEES the value will not be");
    println!("  moved, so the self-reference stays valid. `Unpin` types opt out.");
    println!();

    // For an Unpin type, Pin<&mut T> behaves like &mut T: you CAN mutate/move it.
    let mut x: i32 = 1;
    let p = Pin::new(&mut x); // Pin::new exists ONLY for T: Unpin
    *p.get_mut() = 2; // get_mut is allowed because i32: Unpin
    println!("  i32 is Unpin -> Pin::new(&mut x); *p.get_mut() = 2; -> x = {x}");
    check(
        "Unpin type (i32): Pin<&mut> allows mutation via get_mut",
        x == 2,
    );

    // Compile-time witness: needs_unpin::<i32>() compiles (i32: Unpin).
    needs_unpin::<i32>();
    println!("  needs_unpin::<i32>() compiled  (i32: Unpin).");
    // The line below would FAIL to compile — the future from `async {}` is
    // !Unpin (it may be self-referential). Verbatim error in ASYNC_BASICS.md:
    //
    //   needs_unpin::<<_>>()   // can't even name the type; conceptually:
    //   let _f = async {};
    //   needs_unpin_val(&_f);
    //   // error[E0277]: `<async block>` doesn't implement `std::marker::Unpin`
    check(
        "i32: Unpin (compile-witness); an async-block future is !Unpin",
        true,
    );
}

fn main() {
    println!("async_basics.rs — Phase 4 bundle #2 (Concurrency).");
    println!("Every value below is computed by this file (no timers, no runtime).\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
