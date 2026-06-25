//! tokio_runtime.rs — Phase 7 bundle.
//!
//! GOAL (one line): show, by spawning tasks and racing timers, how the tokio
//! async runtime turns `async fn`s into cooperatively-scheduled tasks and how
//! `tokio::spawn`, `spawn_blocking`, `time::timeout`, and `time::sleep` differ.
//!
//! This is the GROUND TRUTH for TOKIO_RUNTIME.md. Every number and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM NOTE: async task interleaving is NONDETERMINISTIC. This binary
//! NEVER prints from tasks in scheduling order. Section F collects each task's
//! value into a shared `tokio::sync::Mutex<Vec>`, SORTS it, and prints only
//! from `main` after every task is joined. No wall-clock/timer value is printed
//! or asserted as a number — only that a timeout FIRED or a flag was SET (the
//! actual elapsed duration varies per machine and must never be a pinned value).
//!
//! Run:
//!     just run tokio_runtime   (== cargo run --bin tokio_runtime)

use std::future::pending;
use std::sync::Arc;
use std::time::Duration;

use tokio::sync::Mutex;

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

// ── Section A: #[tokio::main] + tokio::spawn -> JoinHandle ───────────────────

async fn section_a() {
    banner("A — #[tokio::main] + tokio::spawn -> JoinHandle");
    println!("  // `#[tokio::main]` expands to building a multi-thread runtime and");
    println!("  // calling .block_on() on `async fn main`. It is NOT magic — it is:");
    println!("  //   Builder::new_multi_thread().enable_all().build().block_on(main)");
    println!("  // The async main itself runs as a task on the runtime, NOT as a");
    println!("  // worker; you `tokio::spawn` real worker tasks from it.");
    println!("  let h: JoinHandle<i32> = tokio::spawn(async {{ 42 }});");

    // tokio::spawn schedules the async block as a TASK (the async analog of an
    // OS thread) and hands back a JoinHandle<T>. Awaiting the handle blocks
    // THIS task until the child finishes, yielding Result<T, JoinError>.
    let handle: tokio::task::JoinHandle<i32> = tokio::spawn(async { 42 });
    let result = handle.await;

    println!("  h.await -> {:?}", result);
    check(
        "tokio::spawn(async { 42 }).await yields Ok(42)",
        matches!(result, Ok(42)),
    );
    check(
        "spawned task is a TASK (green thread): its value comes back via the handle",
        result.as_ref().unwrap_or(&-1) == &42,
    );
}

// ── Section B: a panicking task -> JoinHandle.await is Err (JoinError) ───────

async fn section_b() {
    banner("B — a panicking task -> JoinHandle.await is Err (JoinError)");
    println!("  // tokio CATCHES a task panic and surfaces it as Err(JoinError),");
    println!("  // so ONE panicking task does NOT tear down the whole runtime.");
    println!("  // (The panic message still hits stderr; it is NOT in this stdout.)");
    println!("  let h = tokio::spawn(async {{ panic!(\"boom inside a task\") }});");

    let handle: tokio::task::JoinHandle<i32> = tokio::spawn(async {
        panic!("boom inside a task");
    });
    let result = handle.await;

    println!("  panicking_task.await -> is_err() = {}", result.is_err());
    check(
        "a panicked task's JoinHandle.await is Err (JoinError), not an abort",
        result.is_err(),
    );
}

// ── Section C: spawn_blocking offloads SYNC work off the async thread ───────

async fn section_c() {
    banner("C — spawn_blocking offloads SYNC work off the async thread");
    println!("  // A blocking/sync call inside an async fn STALLS the executor");
    println!("  // thread: no other task on that worker can make progress until it");
    println!("  // returns. spawn_blocking moves it to a DEDICATED blocking pool.");
    println!("  // Signature: F: FnOnce() -> R + Send + 'static  (a sync closure!)");
    println!("  let h = tokio::task::spawn_blocking(|| 7 * 6);");

    // spawn_blocking takes a plain (non-async) closure and runs it on a thread
    // where blocking is acceptable. Like spawn, it returns JoinHandle<R>.
    let handle = tokio::task::spawn_blocking(|| 7 * 6);
    let result = handle.await;

    println!("  spawn_blocking(|| 7*6).await -> {:?}", result);
    check(
        "spawn_blocking(|| 7*6).await yields Ok(42)",
        matches!(result, Ok(42)),
    );
    check(
        "spawn_blocking returns the SAME shape as spawn (JoinHandle<R>)",
        matches!(result, Ok(42)),
    );
}

// ── Section D: tokio::time::timeout races a future against a deadline ───────

async fn section_d() {
    banner("D — tokio::time::timeout races a future against a deadline");
    println!("  // timeout(d, future) -> Result<T, Elapsed>. If the future does not");
    println!("  // finish within d, it is CANCELED and you get Err(Elapsed).");
    println!("  // We assert the VARIANT only — never the elapsed wall-clock.");
    println!("  let r = tokio::time::timeout(Duration::from_millis(1), pending::<()>());");

    // std::future::pending::<()>() is a future that NEVER resolves. With a
    // 1 ms deadline it always loses the race -> Err(Elapsed).
    let lost = tokio::time::timeout(Duration::from_millis(1), pending::<()>()).await;
    println!(
        "  timeout(1ms, never_completes).await -> is_err() = {}",
        lost.is_err()
    );
    check(
        "timeout(tiny, never_completes) -> Err(Elapsed)",
        lost.is_err(),
    );

    // The other branch: a future that completes IMMEDIATELY always wins, even
    // against a long deadline (docs: "guaranteed to complete immediately with
    // an Ok variant no matter the provided duration").
    println!("  let r = tokio::time::timeout(Duration::from_secs(60), async {{ 99 }});");
    let won = tokio::time::timeout(Duration::from_secs(60), async { 99_i32 }).await;
    println!("  timeout(60s, immediate).await -> {:?}", won);
    check(
        "timeout(long, immediate_future) -> Ok(99) (instant future wins the race)",
        matches!(won, Ok(99)),
    );
}

// ── Section E: tokio::time::sleep is the async analog of thread::sleep ──────

async fn section_e() {
    banner("E — tokio::time::sleep is the async analog of thread::sleep");
    println!("  // sleep(d).await YIELDS the task back to the executor until d has");
    println!("  // elapsed, then resumes — other tasks run during the wait. This is");
    println!("  // the cooperative scheduling contract: `.await` is the yield point.");
    println!("  // We assert a flag set AFTER, never the wall-clock duration.");

    let done = {
        tokio::time::sleep(Duration::from_millis(1)).await;
        true
    };

    println!("  after sleep(1ms).await: done = {done}");
    check("flag set to true after sleep(tiny).await completes", done);
}

// ── Section F: N concurrent tasks -> collect into Mutex<Vec>, SORT, assert ──

async fn section_f() {
    banner("F — N concurrent tasks -> collect (Mutex<Vec>), SORT, assert the SET");
    println!("  // Task interleaving is nondeterministic, so we NEVER print from");
    println!("  // tasks in scheduling order. Each task pushes its value into a");
    println!("  // shared Mutex<Vec>; after joining ALL tasks we SORT and print from");
    println!("  // main. The sorted SET is invariant; the arrival order is not.");

    const N: i32 = 5;
    let results: Arc<Mutex<Vec<i32>>> = Arc::new(Mutex::new(Vec::new()));

    // Spawn N tasks. Task i computes i*i and appends it. `yield_now().await`
    // is an explicit cooperative yield: the executor may run another task
    // before resuming this one — so the APPEND ORDER varies per run, but the
    // final sorted set does not.
    let mut handles = Vec::new();
    for i in 0..N {
        let r = results.clone();
        handles.push(tokio::spawn(async move {
            tokio::task::yield_now().await;
            r.lock().await.push(i * i);
        }));
    }
    for h in handles {
        h.await.expect("task should not panic");
    }

    let mut sorted = results.lock().await.clone();
    sorted.sort_unstable();
    println!("  {N} tasks each pushed i*i; sorted results = {sorted:?}");

    let expected: Vec<i32> = (0..N).map(|i| i * i).collect();
    check(
        "5 tasks' results collected + sorted == [0, 1, 4, 9, 16]",
        sorted == expected,
    );
    check(
        "exactly 5 values were collected (one per joined task)",
        sorted.len() == N as usize,
    );
}

#[tokio::main]
async fn main() {
    println!("tokio_runtime.rs — Phase 7 bundle (async member).");
    println!("Every value below is computed by this file.\n");
    section_a().await;
    section_b().await;
    section_c().await;
    section_d().await;
    section_e().await;
    section_f().await;
    banner("DONE — all sections printed");
}
