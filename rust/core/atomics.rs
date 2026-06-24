//! atomics.rs — Phase 4 bundle #4 (Concurrency).
//!
//! GOAL (one line): show, by printing every value, how `std::sync::atomic`
//! gives lock-FREE, single-word shared state with memory ordering — the
//! primitive underneath `Arc`'s refcount, `Once`, and channels.
//!
//! This is the GROUND TRUTH for ATOMICS.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM: the FINAL value of an atomic counter is the deterministic SUM
//! of all operations, but the per-thread interleaving is NOT. So this file only
//! ever asserts TOTALS (read after every thread joins) — never scheduling
//! order — and never prints from inside a thread.
//!
//! Run:
//!     just run atomics   (== cargo run --bin atomics)

use std::sync::atomic::{AtomicBool, AtomicI32, AtomicUsize, Ordering};
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

// ── Section A: load / store / fetch_add / swap — the RMW vocabulary ──────────

fn section_a() {
    banner("A — load / store / fetch_add / swap: the RMW vocabulary");
    // An atomic is a single machine word whose reads/writes are indivisible: no
    // thread ever sees a half-updated value, and read-modify-write (RMW) ops
    // happen as one uninterruptible step. `new` constructs the atomic cell.
    let a = AtomicI32::new(0);
    println!(
        "  let a = AtomicI32::new(0);   a.load(Relaxed) = {}",
        a.load(Ordering::Relaxed)
    );

    // store writes a whole word atomically; load reads a whole word atomically.
    a.store(7, Ordering::Relaxed);
    println!(
        "  a.store(7, Relaxed);         a.load(Relaxed) = {}",
        a.load(Ordering::Relaxed)
    );
    check(
        "store writes a whole word: a.load(Relaxed) == 7 after store(7)",
        a.load(Ordering::Relaxed) == 7,
    );

    // fetch_add is an RMW: it returns the OLD value, then the cell holds old+n.
    // This single hardware instruction is the heart of a lock-free counter.
    let c = AtomicI32::new(0);
    let old = c.fetch_add(5, Ordering::Relaxed);
    let now = c.load(Ordering::Relaxed);
    println!(
        "  let c = AtomicI32::new(0); c.fetch_add(5, Relaxed) -> {} (OLD); c.load -> {}",
        old, now
    );
    check(
        "fetch_add returns the PREVIOUS value (0); the cell then holds 0+5 = 5",
        old == 0 && now == 5,
    );

    // A second fetch_add: returns 5, cell becomes 10.
    let old2 = c.fetch_add(5, Ordering::Relaxed);
    println!(
        "  c.fetch_add(5, Relaxed) -> {} (OLD);  c.load -> {}",
        old2,
        c.load(Ordering::Relaxed)
    );
    check(
        "second fetch_add returns 5 (the previous), cell now 10",
        old2 == 5 && c.load(Ordering::Relaxed) == 10,
    );

    // swap is an RMW that unconditionally replaces the value, returning the old.
    let prev = c.swap(99, Ordering::Relaxed);
    println!(
        "  c.swap(99, Relaxed) -> {} (OLD);       c.load -> {}",
        prev,
        c.load(Ordering::Relaxed)
    );
    check(
        "swap returns the previous (10) and stores 99",
        prev == 10 && c.load(Ordering::Relaxed) == 99,
    );
}

// ── Section B: Ordering — a Release store pairs with an Acquire load ─────────

fn section_b() {
    banner("B — Ordering: a Release store pairs with an Acquire load");
    // Atomics do TWO jobs: (1) make the word indivisible, AND (2) optionally
    // publish/observe a HAPPENS-BEFORE edge between threads (the nomicon model,
    // inherited from C++20). The classic pair:
    //   * Release store  = "everything I wrote before this is now published"
    //   * Acquire  load  = "if I read that published value, I see all those writes"
    //
    // Demo: producer writes `data`, then raises `ready` with Release; consumer
    // spins on `ready` with Acquire, then reads `data`. The Acquire/Release pair
    // GUARANTEES the consumer sees data == 42 once it observes ready == true.
    // (With only Relaxed this guarantee would NOT hold — see ATOMICS.md.)
    let data = AtomicI32::new(0);
    let ready = AtomicBool::new(false);
    println!("  data = AtomicI32::new(0);  ready = AtomicBool::new(false);");

    let seen = thread::scope(|s| {
        let producer = s.spawn(|| {
            data.store(42, Ordering::Relaxed); // (1) plain write of the payload
            ready.store(true, Ordering::Release); // (2) RELEASE: publishes (1)
        });
        let consumer = s.spawn(|| -> i32 {
            // (3) ACQUIRE: spin until it reads the Release-published `true`.
            while !ready.load(Ordering::Acquire) {
                std::hint::spin_loop();
            }
            // (4) happens-after (3), which happens-after (2), which happens-after (1)
            //     => this read is GUARANTEED to observe 42, never the stale 0.
            data.load(Ordering::Relaxed)
        });
        producer.join().expect("producer panicked");
        consumer.join().expect("consumer panicked")
    });

    println!(
        "  after join: consumer broke the Acquire spin loop and read data = {}",
        seen
    );
    check(
        "Release-store / Acquire-load handshake: consumer observed the payload (42)",
        seen == 42,
    );
    check(
        "producer's Relaxed store of 42 is the cell's final value after join",
        data.load(Ordering::Relaxed) == 42,
    );
}

// ── Section C: the CAS loop — a lock-free update via compare_exchange ─────────

fn section_c() {
    banner("C — the CAS loop: a lock-free update via compare_exchange");
    // compare_exchange (CAS): "if the current value == `expected`, replace with
    // `new` and succeed; otherwise leave it and fail (returning what was there)."
    // A CAS LOOP retries until it wins — that is a LOCK-FREE update: progress is
    // guaranteed as long as SOME thread advances. No mutex, no syscall.
    const THREADS: usize = 8;
    const ITERS: usize = 20_000;
    let counter = AtomicUsize::new(0);
    println!(
        "  counter = AtomicUsize::new(0);  {} threads x {} increments each",
        THREADS, ITERS
    );

    thread::scope(|s| {
        for _ in 0..THREADS {
            s.spawn(|| {
                for _ in 0..ITERS {
                    // The canonical CAS loop: load -> compute next -> try to swap.
                    loop {
                        let cur = counter.load(Ordering::Relaxed);
                        let next = cur + 1;
                        if counter
                            .compare_exchange(cur, next, Ordering::Relaxed, Ordering::Relaxed)
                            .is_ok()
                        {
                            break;
                        }
                        // lost the race: `cur` was stale; retry with a fresh load.
                    }
                }
            });
        }
    });
    // All threads joined. The FINAL value is the deterministic SUM of increments;
    // the interleaving is not. We assert the TOTAL, never the order.
    let total = counter.load(Ordering::Relaxed);
    println!(
        "  CAS-loop version: final counter.load(Relaxed) = {}  (== {} * {})",
        total, THREADS, ITERS
    );
    check(
        "lock-free CAS loop: N threads x K increments -> final == N*K (no lost updates)",
        total == THREADS * ITERS,
    );

    // Same workload with the one-instruction primitive: fetch_add does the RMW in
    // hardware with no retry loop. Prefer it when you only need "add to a word".
    let simple = AtomicUsize::new(0);
    thread::scope(|s| {
        for _ in 0..THREADS {
            s.spawn(|| {
                for _ in 0..ITERS {
                    simple.fetch_add(1, Ordering::Relaxed);
                }
            });
        }
    });
    let simple_total = simple.load(Ordering::Relaxed);
    println!(
        "  fetch_add version: final = {}  (one RMW per increment, no retry loop)",
        simple_total
    );
    check(
        "fetch_add(1, Relaxed) reaches the same total as the CAS loop (both lock-free)",
        simple_total == THREADS * ITERS,
    );
}

// ── Section D: compare_exchange — Ok on match, Err on mismatch ───────────────

fn section_d() {
    banner("D — compare_exchange: Ok on match, Err on mismatch");
    // Single-threaded, so the result is fully deterministic (no racing writer).
    let a = AtomicI32::new(5);
    println!("  let a = AtomicI32::new(5);");

    // SUCCESS: current(5) == expected(5), so swap to 10. Returns Ok(previous)=Ok(5).
    let ok = a.compare_exchange(5, 10, Ordering::Acquire, Ordering::Relaxed);
    println!("  a.compare_exchange(5, 10, Acquire, Relaxed) -> {:?}", ok);
    println!(
        "  a.load(Relaxed) -> {} (swapped)",
        a.load(Ordering::Relaxed)
    );
    check(
        "compare_exchange Ok when expected matches: Ok(5), cell now 10",
        ok == Ok(5) && a.load(Ordering::Relaxed) == 10,
    );

    // FAILURE: current is 10, expected(6) mismatches. Returns Err(actual)=Err(10).
    let err = a.compare_exchange(6, 12, Ordering::SeqCst, Ordering::Acquire);
    println!("  a.compare_exchange(6, 12, SeqCst, Acquire) -> {:?}", err);
    println!(
        "  a.load(Relaxed) -> {} (unchanged)",
        a.load(Ordering::Relaxed)
    );
    check(
        "compare_exchange Err on mismatch: Err(10) (the ACTUAL value), cell unchanged",
        err == Err(10) && a.load(Ordering::Relaxed) == 10,
    );
}

// ── Section E: when atomics beat a mutex (and when they don't) ───────────────

fn section_e() {
    banner("E — when atomics beat a mutex (and when they don't)");
    // RULE OF THUMB: a single word of INDEPENDENT state -> atomic (lock-free, no
    // syscall). A multi-field INVARIANT that must change atomically -> mutex.

    // (1) A single counter: AtomicI32 is ideal. One RMW instruction, no lock.
    let hits = AtomicI32::new(0);
    hits.fetch_add(1, Ordering::Relaxed);
    hits.fetch_add(1, Ordering::Relaxed);
    println!(
        "  hits = AtomicI32::new(0); two fetch_add(1) -> {}",
        hits.load(Ordering::Relaxed)
    );
    check(
        "single counter: two atomic increments -> 2 (lock-free, no mutex needed)",
        hits.load(Ordering::Relaxed) == 2,
    );

    // (2) Two fields that must change TOGETHER: a transfer must debit `checking`
    // and credit `savings` as ONE operation, or the total is briefly wrong. A
    // single atomic word cannot update two fields atomically -> use a Mutex.
    struct Account {
        checking: i64,
        savings: i64,
    }
    let acct = Mutex::new(Account {
        checking: 100,
        savings: 0,
    });
    println!("  acct = Mutex(Account {{ checking: 100, savings: 0 }})");
    {
        let mut g = acct.lock().unwrap();
        g.checking -= 50;
        g.savings += 50;
    } // guard drops here -> lock released; both edits published as one.
    let total = {
        let g = acct.lock().unwrap();
        g.checking + g.savings
    };
    println!(
        "  after a 50 transfer: checking + savings = {} (invariant held)",
        total
    );
    check(
        "multi-field invariant needs a mutex: total preserved across the transfer (== 100)",
        total == 100,
    );
}

// ── Section F: atomics under the hood — Arc's refcount IS an AtomicUsize ─────

fn section_f() {
    banner("F — atomics under the hood: Arc's refcount IS an AtomicUsize");
    // Arc<T> = a heap box + an AtomicUsize strong-count (+ a weak count). Every
    // clone does an atomic increment; every drop does an atomic decrement + check
    // for zero. That atomic count is WHY Arc is Send+Sync — and why Rc, whose
    // count is a plain (non-atomic) integer, is !Send/!Sync. Atomics are the
    // foundation under Arc, Once, and mpsc channels.  (See BOX_RC_ARC for the
    // full Arc/Rc/Weak treatment.)
    let a = Arc::new(7_i32);
    let c1 = Arc::strong_count(&a);
    println!("  let a = Arc::new(7);  strong_count = {}", c1);
    check(
        "Arc starts at strong_count == 1 (its AtomicUsize refcount = 1)",
        c1 == 1,
    );

    // Two workers each clone the Arc (atomic ++) then drop it (atomic --). After
    // join the count MUST be back to 1 — the atomic increments/decrements never
    // lose a step, even under concurrent cloning.
    thread::scope(|s| {
        for _ in 0..2 {
            let ac = Arc::clone(&a);
            s.spawn(move || {
                let _owned = ac; // count hits 3 inside; drops when the closure ends
            });
        }
    }); // <- thread::scope joins every worker HERE, so their clones are dropped.
    let c_after = Arc::strong_count(&a);
    println!(
        "  after 2 worker clones dropped: strong_count = {}",
        c_after
    );
    check(
        "atomic refcount: count returns to 1 after the worker clones drop",
        c_after == 1,
    );
    check(
        "the shared value is still readable (Arc kept it alive): *a == 7",
        *a == 7,
    );
}

fn main() {
    println!("atomics.rs — Phase 4 bundle #4 (Concurrency).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
