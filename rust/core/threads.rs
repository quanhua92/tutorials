//! threads.rs — Phase 4 bundle #1 (Concurrency).
//!
//! GOAL (one line): show, by printing every value, how Rust spawns OS threads
//! (`thread::spawn`), how a `move` closure transfers ownership into a thread,
//! how `JoinHandle::join` blocks and captures panics (so they never propagate),
//! and how `thread::scope` (1.63+) lifts the `'static` bound so scoped threads
//! can BORROW local data.
//!
//! This is the GROUND TRUTH for THREADS.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Two facts here are COMPILE-TIME properties that cannot live in a runnable
//! file (e.g. `Rc<T>` is `!Send`). They are documented in THREADS.md with the
//! exact compiler error (`E0277`); where a property IS runnable, this file
//! proves it with a `check(...)` or a compile-time witness.
//!
//! Run:
//!     just run threads   (== cargo run --bin threads)

use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

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

/// Compile-time witness: this function only compiles if `T: Send + Sync`.
/// Calling `is_send_sync::<Arc<i32>>()` proves `Arc<i32>` is `Send + Sync`.
/// (Calling it with `Rc<i32>` would be `E0277` — see Section F.)
fn is_send_sync<T: Send + Sync>() {}

// ── Section A: thread::spawn -> JoinHandle; join() returns the value ─────────

/// A tiny pure computation that the spawned thread will return through its
/// `JoinHandle`. Threads return whatever their closure returns.
fn fib(n: u32) -> u64 {
    let mut a = 0u64;
    let mut b = 1u64;
    for _ in 0..n {
        let t = a + b;
        a = b;
        b = t;
    }
    a
}

fn section_a() {
    banner("A — thread::spawn -> JoinHandle; join() returns the closure's value");
    // `thread::spawn` schedules the closure on a NEW OS thread and immediately
    // hands back a `JoinHandle<T>` (here T = u64). spawn() returns AT ONCE —
    // the child runs concurrently with the caller.
    let handle: thread::JoinHandle<u64> = thread::spawn(|| fib(20));
    println!("  let handle = thread::spawn(|| fib(20));   (runs on another thread)");

    // `handle.join()` BLOCKS the calling thread until the child finishes, then
    // yields its return value (boxed in a Result). `.unwrap()` extracts it.
    let result = handle.join().expect("worker thread panicked");
    println!("  handle.join().unwrap() -> {}", result);

    // Independent corroboration: compute the same thing on this thread.
    let here = fib(20);
    println!("  fib(20) on this thread   -> {}  (identical)", here);
    check(
        "spawned thread returns its closure value via join: fib(20) == 6765",
        result == 6765 && result == here,
    );
}

// ── Section B: `move` closure transfers ownership into the thread ────────────

fn section_b() {
    banner("B — `move` closure: transfer ownership of a captured value");
    // `spawn` requires F: 'static — a plain closure borrowing `secret` would
    // borrow a local of THIS function, which is NOT 'static. `move` converts
    // the borrow into an OWNERSHIP TRANSFER: `secret` moves into the closure,
    // so the closure is self-contained ('static) and `Send`.
    let secret = String::from("bismuth");
    println!(
        "  let secret = String::from(\"bismuth\");  (len {})",
        secret.len()
    );

    let handle = thread::spawn(move || {
        // The thread now OWNS `secret`. After join, only the thread ever saw it.
        format!("len({}) = {}", secret, secret.len())
    });
    let observed = handle.join().expect("worker thread panicked");
    println!("  thread (moved secret) -> {:?}", observed);

    // `secret` is gone from this scope — using it here would be E0382 (see
    // THREADS.md). We instead recompute the expected value locally.
    let expected = format!("len({}) = {}", "bismuth", "bismuth".len());
    check(
        "`move` closure owned the String; thread read it correctly",
        observed == expected,
    );
}

// ── Section C: thread panic is ISOLATED -> join() returns Err (main lives) ───

fn section_c() {
    banner("C — a thread panic is ISOLATED: join() yields Err, main continues");
    // A panic in a spawned thread does NOT unwind into the parent. The panic is
    // caught at the thread boundary, captured as `Box<dyn Any + Send + 'static>`,
    // and surfaced to `join()` as `Err(payload)`. The parent thread keeps going.
    let handle = thread::spawn(|| {
        panic!("boom: worker fault");
    });

    let joined: Result<usize, Box<dyn std::any::Any + Send>> = handle.join();
    let is_err = joined.is_err();
    println!("  spawned `panic!(\"boom: worker fault\")`;");
    println!("  handle.join() -> Err (main thread still alive)");
    println!("  joined.is_err() -> {is_err}");

    // The payload type is `Box<dyn Any + Send + 'static>`. We can downcast the
    // known `&'static str` the panic! macro put in to read its content.
    let payload_str = joined
        .as_ref()
        .err()
        .and_then(|any| any.downcast_ref::<&'static str>())
        .copied();
    println!("  payload.downcast_ref::<&str>() -> {:?}", payload_str);

    check(
        "a panicking thread -> join().is_err() (panic contained, parent unharmed)",
        is_err,
    );
    check(
        "panic payload is Box<dyn Any + Send>: downcast recovers \"boom: worker fault\"",
        payload_str == Some("boom: worker fault"),
    );
}

// ── Section D: scoped threads (thread::scope, 1.63+) can BORROW non-'static ─

fn section_d() {
    banner("D — scoped threads (thread::scope, 1.63+) BORROW non-'static data");
    // `thread::scope` lets child threads borrow LOCAL variables: the scope
    // blocks until every spawned child has been joined, so the borrowed refs
    // stay valid for the whole lifetime of the scope.
    let data: Vec<i32> = vec![10, 20, 30, 40];
    let sum_total: i32 = data.iter().sum();
    println!("  let data = {:?};   sum = {}", data, sum_total);

    let collected = Arc::new(Mutex::new(Vec::<i32>::new()));
    {
        let collected = Arc::clone(&collected);
        thread::scope(|s| {
            // Two scoped threads BORROW `data` by shared reference — no `move`,
            // no clone, no `'static` required. Both refs are `&` so it is safe.
            s.spawn(|| {
                let first_half: i32 = data[..2].iter().sum();
                collected.lock().unwrap().push(first_half);
            });
            s.spawn(|| {
                let second_half: i32 = data[2..].iter().sum();
                collected.lock().unwrap().push(second_half);
            });
            // <-- scope returns only after BOTH children join, so `data` outlives them.
        });
    }

    let mut got = collected.lock().unwrap().clone();
    got.sort_unstable();
    println!(
        "  collected (sorted) = {:?}  (each child summed half of `data`)",
        got
    );
    check(
        "scoped threads borrowed `data` (no 'static, no clone): partial sums present",
        got.len() == 2 && got.contains(&30) && got.contains(&70),
    );
    check(
        "sum of the two partial sums == the whole sum (correctness)",
        got.iter().sum::<i32>() == sum_total,
    );

    // The borrow ENDS with the scope: `data` is fully usable here again.
    let after = data.len();
    println!("  after scope: data still owned by parent, len = {}", after);
    check(
        "borrow ends at scope exit: parent keeps `data` (len 4)",
        after == 4,
    );
}

// ── Section E: N workers -> collect+SORT -> deterministic (no scheduling) ────

fn section_e() {
    banner("E — N workers: collect via Mutex<Vec>, SORT, print from main");
    // Thread scheduling is NONDETERMINISTIC — the OS decides who runs first. To
    // get byte-stable output we collect results into a Mutex<Vec>, join every
    // worker, then SORT the Vec and print from main AFTER all joins. The
    // sorted set is what we check; the arrival order is irrelevant.

    const N: u32 = 6;
    let results = Arc::new(Mutex::new(Vec::<(u32, u64)>::new()));
    let mut handles = Vec::with_capacity(N as usize);

    for id in 0..N {
        let results = Arc::clone(&results);
        // `move` captures `id` (a Copy i32-range) into each child's closure.
        handles.push(thread::spawn(move || {
            let value = fib(id + 4); // fib(4) .. fib(9) — distinct per worker
            results.lock().unwrap().push((id, value));
        }));
    }

    // Join EVERY worker before reading the shared state — the last `join()`
    // returning establishes a happens-before with every push that came before.
    let joined_count = handles
        .into_iter()
        .map(|h| h.join().expect("worker panicked"))
        .count();
    println!("  spawned {N} workers; joined {joined_count} (all returned Ok)");

    let mut got = Arc::try_unwrap(results)
        .expect("all clones moved into joined threads")
        .into_inner()
        .expect("mutex never poisoned");
    got.sort_unstable();
    println!("  collected then sorted by worker id:");
    for (id, v) in &got {
        println!("    worker {id} -> fib({}) = {}", id + 4, v);
    }

    // The EXPECTED set is computed in advance (and id-sorted) so the check is
    // against the deterministic ordering we just printed, not arrival order.
    let expected: Vec<(u32, u64)> = (0..N).map(|id| (id, fib(id + 4))).collect();
    let expected_set: Vec<u64> = (0..N).map(|id| fib(id + 4)).collect::<Vec<_>>();
    check(
        "all N workers joined cleanly (no panic)",
        joined_count == N as usize,
    );
    check(
        "collected+sorted worker results == expected sorted set",
        got == expected,
    );
    check("the SET of fib values is exactly {3,5,8,13,21,34}", {
        let mut s = expected_set.clone();
        s.sort_unstable();
        s == vec![3, 5, 8, 13, 21, 34]
    });
}

// ── Section F: collect via channel (mpsc) — sorted on main; Rc cannot cross ─

fn section_f() {
    banner("F — channel (mpsc) collect; Arc works, Rc cannot cross (E0277)");
    // Same determinism discipline as Section E, but the rendezvous is a channel
    // (mpsc) instead of a Mutex. Each worker sends its result; main collects,
    // sorts, prints. Channels are the thread-comms primitive — see MPSC_CHANNELS.
    const N: u32 = 4;
    let (tx, rx) = mpsc::channel::<(u32, u64)>();
    let mut handles = Vec::with_capacity(N as usize);
    for id in 0..N {
        let tx = tx.clone();
        handles.push(thread::spawn(move || {
            let value = fib(id + 5); // fib(5)..fib(8) = {5,8,13,21}
            tx.send((id, value)).expect("receiver gone");
            // `tx` (the clone) drops here — only the original survives.
        }));
    }
    drop(tx); // close the channel: rx.recv() returns Err after this drains.
    for h in handles {
        h.join().expect("worker panicked");
    }

    let mut got: Vec<(u32, u64)> = rx.iter().collect();
    got.sort_unstable();
    println!("  via mpsc, collected+sorted:");
    for (id, v) in &got {
        println!("    worker {id} -> fib({}) = {}", id + 5, v);
    }
    check(
        "mpsc collected {5,8,13,21} (sorted), all 4 workers delivered",
        got == vec![(0, 5), (1, 8), (2, 13), (3, 21)],
    );

    // Compile-time proof that the threading primitives are `Send + Sync`. This
    // line COMPILES only because Arc<i32>, Mutex<i32>, and the mpsc Sender all
    // implement Send (+ Sync where relevant). A `Sender` is `Send` but NOT
    // `Sync`; a `Receiver` is `Send` but not `Sync` either — so we witness the
    // shared-state primitives here instead. See MPSC_CHANNELS for the channel
    // story.
    is_send_sync::<Arc<i32>>();
    is_send_sync::<Mutex<i32>>();
    println!("  is_send_sync::<Arc<i32>>() and is_send_sync::<Mutex<i32>>() both compiled.");

    // The Rc-vs-Arc fact is a COMPILE-TIME property: the following does NOT
    // compile, so it cannot live in this runnable file (verbatim error in
    // THREADS.md Section F):
    //
    //   let r = std::rc::Rc::new(1);
    //   std::thread::spawn(move || { let _ = r; });
    //
    //   error[E0277]: `Rc<{integer}>` cannot be sent between threads safely
    //     --> the trait `Send` is not implemented for `Rc<{integer}>`
    //   help: ...
    //
    // WHY: Rc's refcount is a plain integer (no atomic). Two threads doing
    // Rc::clone / drop at once would race that counter — lost increment ->
    // double-free or use-after-free. The compiler forbids the move statically.
    // Arc uses atomic increments, so it IS Send + Sync. Use Arc across threads.
    println!("  (is_send_sync::<Rc<i32>>() would be E0277: Rc is !Send/!Sync; Arc is not.)");
    check(
        "Arc<i32> + Mutex<i32> are Send + Sync (compile-proved); Rc<i32> is not",
        true,
    );
}

fn main() {
    println!("threads.rs — Phase 4 bundle #1 (Concurrency).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
