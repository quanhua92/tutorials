//! barrier_once.rs — Phase 4 bundle.
//!
//! GOAL (one line): show, by printing every value, that `Barrier` rendezvouses
//! N threads (all release together, exactly one is the "leader"), that
//! `Once::call_once` runs a closure EXACTLY ONCE across threads, that
//! `OnceLock<T>` and `LazyLock<T,F>` give thread-safe one-shot / lazy
//! initialization, and that `Condvar` does wait/notify on a `Mutex` predicate.
//!
//! This is the GROUND TRUTH for BARRIER_ONCE.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM: per-thread interleaving is nondeterministic, so we NEVER print
//! per-thread scheduling or who-the-leader-was. We assert DETERMINISTIC
//! aggregates only — the COUNT of threads that crossed, the COUNT of leaders
//! (always exactly 1), and the COUNT of times an init closure ran (always 1).
//! Any per-thread output is collected into a Vec, SORTED, then printed from
//! `main` after `join`. See HOW_TO_RESEARCH.md §4.2 rule 3.
//!
//! Run:
//!     just run barrier_once   (== cargo run --bin barrier_once)

use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::{Arc, Barrier, Condvar, LazyLock, Mutex, Once, OnceLock};
use std::thread;

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

// ── Section A: Barrier — N threads rendezvous; all release together ───────────

fn section_a_barrier() {
    banner("A — Barrier: N threads rendezvous; all release together");
    // `Barrier::new(n)` builds a gate that blocks `n-1` callers of `.wait()`;
    // when the Nth caller arrives, ALL N are released at once. `.wait()` hands
    // back a BarrierWaitResult whose `.is_leader()` is true for EXACTLY ONE
    // (arbitrary) thread. Barriers are RE-USABLE: after a rendezvous they reset.
    const N: usize = 3;
    let barrier = Barrier::new(N);
    let crossed = AtomicUsize::new(0); // how many threads got past the gate
    let leaders = AtomicUsize::new(0); // how many were the leader
    let order = Mutex::new(Vec::<usize>::new()); // thread ids, collected then sorted

    // thread::scope lets the closures borrow the locals (&barrier, &crossed, ...)
    // by shared reference without Arc. `move` is needed to capture the per-loop
    // `id` by value; the `_ref` bindings move cheap, copyable shared references.
    let barrier_ref = &barrier;
    let crossed_ref = &crossed;
    let leaders_ref = &leaders;
    let order_ref = &order;
    thread::scope(|s| {
        for id in 0..N {
            s.spawn(move || {
                // Before this returns, the thread is BLOCKED at the gate. After
                // it returns, every thread has crossed simultaneously.
                let result = barrier_ref.wait();
                crossed_ref.fetch_add(1, Ordering::SeqCst);
                if result.is_leader() {
                    leaders_ref.fetch_add(1, Ordering::SeqCst);
                }
                order_ref.lock().unwrap().push(id);
            });
        }
    });

    let c = crossed.load(Ordering::SeqCst);
    let l = leaders.load(Ordering::SeqCst);
    let mut o = order.into_inner().unwrap();
    o.sort_unstable();
    println!("  Barrier::new({N}); {N} threads each call .wait()");
    println!("  threads that crossed the barrier: {c}");
    println!("  leader threads (is_leader() == true): {l}");
    println!("  thread ids that crossed (sorted): {:?}", o);
    check("all N threads crossed the Barrier together", c == N);
    check("exactly ONE thread is the leader (is_leader)", l == 1);
    check(
        "the same N thread ids crossed (no thread lost/stuck)",
        o.len() == N,
    );
}

// ── Section B: Once — call_once runs the closure EXACTLY ONCE ─────────────────

fn section_b_once() {
    banner("B — Once::call_once: the closure runs EXACTLY ONCE");
    // `Once` is the low-level one-time global execution primitive: the first
    // caller's closure runs; every later caller (concurrent or not) just blocks
    // until it finishes, then returns WITHOUT re-running it. If the closure
    // panics it POISONS the Once (all future call_once panic). `OnceLock<T>`
    // supersedes Once for the common "init that returns data" case (Section C).
    const N: usize = 4;
    let init = Once::new();
    let runs = AtomicUsize::new(0);

    let init_ref = &init;
    let runs_ref = &runs;
    thread::scope(|s| {
        for _ in 0..N {
            s.spawn(move || {
                init_ref.call_once(|| {
                    runs_ref.fetch_add(1, Ordering::SeqCst);
                });
            });
        }
    });

    let r = runs.load(Ordering::SeqCst);
    println!("  Once::new(); {N} threads call_once an init that bumps a counter");
    println!("  init closure executed: {r} time(s)");
    check(
        "call_once ran the closure EXACTLY ONCE across N threads",
        r == 1,
    );
    check(
        "is_completed() is true after a successful call_once",
        init.is_completed(),
    );
}

// ── Section C: OnceLock<T> — a cell initialized ONCE, lazily, thread-safely ───

fn section_c_oncelock() {
    banner("C — OnceLock<T>: a cell initialized ONCE, lazily, thread-safely");
    // `OnceLock<T>` (1.70) is a thread-safe OnceCell, usable in `static`s. Many
    // threads may call get_or_init concurrently; "only one function will be
    // executed if the function doesn't panic" (std docs). Unlike Mutex it is
    // NEVER poisoned on panic. `set(v)` returns Err(value) if already set.
    const N: usize = 4;
    let cell = OnceLock::new();
    let inits = AtomicUsize::new(0);
    let seen = Mutex::new(Vec::<i32>::new());

    let cell_ref = &cell;
    let inits_ref = &inits;
    let seen_ref = &seen;
    thread::scope(|s| {
        for _ in 0..N {
            s.spawn(move || {
                let v = cell_ref.get_or_init(|| {
                    inits_ref.fetch_add(1, Ordering::SeqCst);
                    42
                });
                seen_ref.lock().unwrap().push(*v);
            });
        }
    });

    let mut vs = seen.into_inner().unwrap();
    vs.sort_unstable();
    let i = inits.load(Ordering::SeqCst);
    println!("  OnceLock::new(); {N} threads call get_or_init(|| 42)");
    println!("  init closure executed: {i} time(s)");
    println!("  values returned to threads (sorted): {:?}", vs);
    check("get_or_init ran the closure EXACTLY ONCE", i == 1);
    check(
        "all N threads observed the initialized value (42)",
        vs.len() == N && vs.iter().all(|&x| x == 42),
    );
    check(
        "get() returns Some(&42) after initialization",
        cell.get() == Some(&42),
    );
    let rejected = cell.set(99);
    check(
        "set() after initialization returns Err (already set, value refused)",
        rejected.is_err(),
    );
}

// ── Section D: LazyLock<T,F> — initialized on first deref (std 1.80) ──────────

fn section_d_lazylock() {
    banner("D — LazyLock<T,F> (std 1.80): initialized on first deref");
    // `LazyLock<T, F>` (1.80) is a thread-safe LazyCell: you hand it a thunk `F`,
    // and it runs `F` ONCE, lazily, the first time the value is dereferenced. It
    // `impl Deref<Target = T>`, so `&*lazy` looks like `&T`. It is `Sync` and
    // usable in `static`s — the std replacement for the old `lazy_static!` macro.
    const N: usize = 4;
    let inits = AtomicUsize::new(0);
    let lazy = LazyLock::new(|| {
        inits.fetch_add(1, Ordering::SeqCst);
        String::from("configured-on-first-deref")
    });

    // Before any deref, get() reports None — the thunk has NOT run yet.
    let before = LazyLock::get(&lazy).is_some();
    println!(
        "  LazyLock::new(|| ...); before first access get().is_some() = {}",
        before
    );
    check("LazyLock is NOT initialized until first deref", !before);

    let snapshots = Mutex::new(Vec::<String>::new());
    let lazy_ref = &lazy;
    let snapshots_ref = &snapshots;
    thread::scope(|s| {
        for _ in 0..N {
            s.spawn(move || {
                // `lazy_ref` Deref-coerces to &String; the deref FORCES init on
                // the very first call (under the hood, an OnceLock + call_once).
                let snapshot = lazy_ref.as_str().to_owned();
                snapshots_ref.lock().unwrap().push(snapshot);
            });
        }
    });

    let mut ss = snapshots.into_inner().unwrap();
    ss.sort_unstable();
    let i = inits.load(Ordering::SeqCst);
    println!("  {N} threads deref it; init closure executed: {i} time(s)");
    println!("  snapshots (sorted): {:?}", ss);
    check("LazyLock initialized EXACTLY ONCE across N threads", i == 1);
    check(
        "all N threads saw the same lazy value",
        ss.len() == N && ss.iter().all(|x| x == "configured-on-first-deref"),
    );
    check(
        "the value derefs to 'configured-on-first-deref'",
        &*lazy == "configured-on-first-deref",
    );
}

// ── Section E: Condvar — wait() releases the Mutex; notify_* wakes it ─────────

fn section_e_condvar() {
    banner("E — Condvar: wait() releases the Mutex; notify_* wakes it");
    // A Condvar lets a thread BLOCK (consuming no CPU) until another thread
    // signals. The canonical pattern pairs it with a `Mutex<P>` holding the
    // predicate: `cvar.wait(guard)` atomically UNLOCKS the mutex and parks the
    // thread; on wake it RE-LOCKS and hands back the guard. `notify_one`/
    // `notify_all` are NOT buffered — a notify with no current waiter is lost,
    // which is why the predicate loop is mandatory. Use Condvar sparingly:
    // channels fit more cases (see MPSC_CHANNELS) and are harder to misuse.
    let pair = Arc::new((Mutex::new(false), Condvar::new()));
    let woken = Arc::new(AtomicBool::new(false));

    // Notifier thread: lock, flip the predicate, notify.
    let notifier = {
        let pair = Arc::clone(&pair);
        thread::spawn(move || {
            let (lock, cvar) = &*pair;
            let mut started = lock.lock().unwrap();
            *started = true;
            cvar.notify_one();
        })
    };

    // Waiter thread: loop on the predicate; wait() releases the lock while parked.
    let waiter = {
        let pair = Arc::clone(&pair);
        let woken = Arc::clone(&woken);
        thread::spawn(move || {
            let (lock, cvar) = &*pair;
            let mut started = lock.lock().unwrap();
            // Spurious wakeups are possible -> ALWAYS re-check the predicate.
            while !*started {
                started = cvar.wait(started).unwrap();
            }
            woken.store(true, Ordering::SeqCst);
        })
    };

    notifier.join().unwrap();
    waiter.join().unwrap();
    let did_wake = woken.load(Ordering::SeqCst);
    println!("  Arc<(Mutex<bool>, Condvar)>; waiter parks until notified");
    println!("  waiter observed the predicate and set woken = {did_wake}");
    check(
        "the Condvar woke the waiting thread (predicate true after join)",
        did_wake,
    );
}

// ── Section F: when to use what (rendezvous vs init vs wait/notify) ───────────

fn section_f_when_to_use() {
    banner("F — when to use what: rendezvous vs one-shot init vs wait/notify");
    // None of these primitives TRANSFER ownership between threads — that is what
    // channels are for (MPSC_CHANNELS). They are the higher-level layer above
    // raw atomics (ATOMICS): Barrier = rendezvous; Once/OnceLock/LazyLock =
    // one-shot/lazy init; Condvar = wait/notify on shared state.
    let rows: [(&str, &str, &str); 5] = [
        (
            "Barrier",
            "rendezvous: N threads meet, then all proceed together",
            "compute phases / fan-out then sync",
        ),
        (
            "Once",
            "one-shot SIDE-EFFECTING init, returns no data",
            "global setup over static mut",
        ),
        (
            "OnceLock<T>",
            "one-shot init that RETURNS a shared &T",
            "lazy global config / cache",
        ),
        (
            "LazyLock<T,F>",
            "OnceLock that inits on first DEREF (ergonomic &T)",
            "static computed-once value",
        ),
        (
            "Condvar",
            "wait/notify on a Mutex predicate",
            "rare; channels usually fit better",
        ),
    ];
    println!("  {:<13} {:<55} TYPICAL USE", "PRIMITIVE", "ROLE");
    for (p, role, uses) in rows {
        println!("  {:<13} {:<55} {}", p, role, uses);
    }
    check(
        "the five primitives map to five distinct roles",
        rows.len() == 5,
    );
    check(
        "none of these transfer ownership across threads (channels do)",
        true,
    );
}

fn main() {
    println!("barrier_once.rs — Phase 4 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a_barrier();
    section_b_once();
    section_c_oncelock();
    section_d_lazylock();
    section_e_condvar();
    section_f_when_to_use();
    banner("DONE — all sections printed");
}
