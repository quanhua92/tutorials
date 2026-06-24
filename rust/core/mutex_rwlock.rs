//! mutex_rwlock.rs — Phase 4 bundle.
//!
//! GOAL (one line): show, by printing every value, that `Mutex<T>` / `RwLock<T>`
//! guard shared data with an RAII *borrow* (the guard `Deref`s to `&mut T` and
//! unlocks on `Drop`), that `Arc<Mutex<T>>` is the shared-MUTABLE-thread-safe
//! combo whose FINAL total is deterministic, that a panic-WHILE-locked *poisons*
//! the lock (so the next `lock()` returns `Err`), and that `try_lock` is the
//! non-blocking variant.
//!
//! This is the GROUND TRUTH for MUTEX_RWLOCK.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM: per-thread interleaving is nondeterministic, so we NEVER print
//! per-thread scheduling. A Mutex/RwLock-protected counter's FINAL total IS
//! deterministic (== sum of all increments) — we assert that total, never the
//! order. See HOW_TO_RESEARCH.md §4.2 rule 3.
//!
//! Run:
//!     just run mutex_rwlock   (== cargo run --bin mutex_rwlock)

use std::panic;
use std::sync::{Arc, Mutex, RwLock, TryLockError};
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

// ── Section A: Mutex<T> — lock() blocks; the guard unlocks on Drop ───────────

fn section_a_mutex_basics() {
    banner("A — Mutex<T>: lock() blocks; the guard unlocks on Drop");
    // `Mutex<T>` wraps the data; the ONLY safe way to touch it is through a guard
    // returned by lock() / try_lock(). lock() BLOCKS the calling thread until no
    // other thread holds the lock, then hands back a `MutexGuard<T>`.
    let m = Mutex::new(0i32);
    println!("  let m = Mutex::new(0i32);");
    {
        // lock() returns LockResult<MutexGuard<T>> — a Result because of poisoning
        // (see Section E). unwrap() asserts "not poisoned".
        let mut guard = m.lock().unwrap();
        *guard = 5; // the guard DerefMut's to &mut i32
        println!("  let mut guard = m.lock().unwrap();  *guard = 5;");
        println!("  (guard alive: value inside the mutex is now {guard}, lock HELD)");
    } // <- guard drops HERE -> OS lock released (RAII unlock)
    // A FRESH lock() sees the mutation the guard made before it dropped.
    let after = *m.lock().unwrap();
    println!("  after the guard dropped: *m.lock().unwrap() = {after}");
    check(
        "the guard's mutation survives its Drop (value == 5 after re-lock)",
        after == 5,
    );
}

// ── Section B: the guard IS a borrow — Deref + DerefMut + Drop (RAII) ─────────

fn section_b_guard_is_a_borrow() {
    banner("B — the guard IS a borrow: Deref/DerefMut + Drop = RAII unlock");
    // `MutexGuard<'a, T>` carries a lifetime tied to the Mutex: it is, in effect,
    // a mutable borrow of the protected data for the duration of the lock.
    // Deref -> &T, DerefMut -> &mut T, and Drop releases the OS lock.
    let m = Mutex::new(0i32);

    // While a guard is ALIVE on this thread the lock is HELD. Re-locking on the
    // SAME thread is "left unspecified" (panic or deadlock), so we probe state
    // with the NON-blocking try_lock(), which reports it deterministically.
    let mut guard = m.lock().unwrap();
    *guard = 7;
    let held = m.try_lock(); // lock held by `guard` -> Err(WouldBlock)
    println!("  guard alive; m.try_lock().is_err() = {}", held.is_err());
    check(
        "while the guard is alive, try_lock() is Err (the lock is held)",
        held.is_err(),
    );
    drop(guard); // <- explicit early drop: OS lock released RIGHT NOW
    println!("  std::mem::drop(guard);   // RAII: lock released immediately");

    let free = m.try_lock(); // now free -> Ok(guard)
    println!("  after drop; m.try_lock().is_ok() = {}", free.is_ok());
    check(
        "after the guard is dropped, try_lock() is Ok (the lock is free)",
        free.is_ok(),
    );
    drop(free);

    // std::mem::drop is how you release a lock BEFORE its scope's `}` — the same
    // ownership move that drops a Box/sentinel (see OWNERSHIP Section D). The
    // guard's borrow lifetime IS the lock's lifetime: keep it short.
    check(
        "RAII: std::mem::drop releases the lock early; re-lock sees the mutation (== 7)",
        *m.lock().unwrap() == 7,
    );
}

// ── Section C: Arc<Mutex<T>> — shared, mutable, thread-safe (the combo) ───────

fn section_c_arc_mutex_threads() {
    banner("C — Arc<Mutex<T>>: shared MUTABLE state across threads");
    // `Arc<T>` gives many owners (atomic refcount); `Mutex<T>` adds mutation
    // behind a lock. `Arc<Mutex<T>>` is THE recipe for data shared AND mutated by
    // many threads. Each thread clones the Arc (a cheap atomic refcount bump) and
    // locks the Mutex to mutate the shared value.
    const N_THREADS: usize = 4;
    const INCR_PER_THREAD: i32 = 1000;
    let counter = Arc::new(Mutex::new(0i32));
    println!(
        "  Arc::new(Mutex::new(0));  {N_THREADS} threads each +{INCR_PER_THREAD} under the lock"
    );

    let mut handles = Vec::with_capacity(N_THREADS);
    for _ in 0..N_THREADS {
        let counter = Arc::clone(&counter);
        handles.push(thread::spawn(move || {
            // Each increment is a full lock/mutate/unlock cycle. The OS
            // serializes them; the FINAL total is deterministic even though the
            // interleaving is not. (Without the lock this would be a data race —
            // which safe Rust refuses to even compile.)
            for _ in 0..INCR_PER_THREAD {
                *counter.lock().unwrap() += 1;
            }
        }));
    }
    for h in handles {
        h.join().unwrap();
    }
    let total = *counter.lock().unwrap();
    println!("  after join: total = {total}  (== {N_THREADS} x {INCR_PER_THREAD})");
    check(
        "Arc<Mutex<i32>>: final total == N*K (lock serializes; deterministic)",
        total == (N_THREADS as i32) * INCR_PER_THREAD,
    );
}

// ── Section D: RwLock<T> — many readers OR one writer ────────────────────────

fn section_d_rwlock() {
    banner("D — RwLock<T>: many read() OR one write()");
    // `RwLock<T>` relaxes the Mutex rule: any number of read() guards may coexist
    // (shared, like &T), but a write() guard is EXCLUSIVE (like &mut T). The
    // payoff is read-heavy workloads: readers don't block each other.
    let rw = RwLock::new(100i32);
    println!("  let rw = RwLock::new(100i32);");

    // (1) Deterministic proof that two read() guards coexist: if RwLock were
    // exclusive the second read() would block forever. Both succeed at once.
    {
        let r1 = rw.read().unwrap();
        let r2 = rw.read().unwrap();
        println!("  two read() guards at once: *r1 = {}, *r2 = {}", *r1, *r2);
        check(
            "RwLock allows multiple simultaneous read() guards (shared access)",
            *r1 == 100 && *r2 == 100,
        );
    } // r1, r2 drop -> readers gone

    // (2) While a write() guard is held, even a read() is refused (exclusive).
    {
        let _w = rw.write().unwrap();
        let attempted_read = rw.try_read();
        println!(
            "  write() guard held; rw.try_read().is_err() = {}",
            attempted_read.is_err()
        );
        check(
            "while a write() guard is held, try_read() is Err (write is exclusive)",
            attempted_read.is_err(),
        );
    } // _w drops -> writer gone

    // (3) Across threads: N writers each add A under write() -> final deterministic.
    const N_WRITERS: usize = 3;
    const ADD: i32 = 5;
    let shared = Arc::new(RwLock::new(100i32));
    let mut handles = Vec::with_capacity(N_WRITERS);
    for _ in 0..N_WRITERS {
        let shared = Arc::clone(&shared);
        handles.push(thread::spawn(move || {
            for _ in 0..ADD {
                *shared.write().unwrap() += 1;
            }
        }));
    }
    for h in handles {
        h.join().unwrap();
    }
    let total = *shared.read().unwrap();
    println!("  {N_WRITERS} writers * +{ADD} each -> final = {total}");
    check(
        "RwLock writers serialize: final == base + N*ADD (deterministic)",
        total == 100 + (N_WRITERS as i32) * ADD,
    );
}

// ── Section E: poisoning — a panic WHILE holding the lock taints it ───────────

fn section_e_poisoning() {
    banner("E — poisoning: a panic WHILE locked makes lock() return Err");
    // If a thread panics while holding a lock, the guard's Drop still runs on the
    // unwind path and RELEASES the OS lock — but it ALSO marks the Mutex
    // "poisoned". Every subsequent lock()/try_lock() then returns Err(Poisoned),
    // forcing you to decide: propagate the panic (unwrap) or recover (into_inner).
    let m = Arc::new(Mutex::new(0i32));
    let m2 = Arc::clone(&m);

    // Silence the panic hook for this deliberately-triggered panic, then restore.
    let prev_hook = panic::take_hook();
    panic::set_hook(Box::new(|_| {}));
    let handle = thread::spawn(move || {
        let mut g = m2.lock().unwrap();
        *g = 50; // mutate, THEN panic while still holding the lock
        panic!("boom while holding the lock");
    });
    let join_result = handle.join();
    panic::set_hook(prev_hook);

    check(
        "join() propagates the thread's panic as Err",
        join_result.is_err(),
    );
    check(
        "the mutex is now poisoned (is_poisoned() == true)",
        m.is_poisoned(),
    );

    // A poisoned Mutex: lock() returns Err(PoisonError) — NOT a block, an error.
    let poisoned = m.lock();
    println!(
        "  after the panic, m.lock().is_err() = {}",
        poisoned.is_err()
    );
    check(
        "a poisoned Mutex: lock() returns Err (you must handle it)",
        poisoned.is_err(),
    );

    // RECOVERY: PoisonError::into_inner() hands back the guard anyway — the data
    // is still THERE, just possibly inconsistent; you assert you can deal with it.
    let guard = match poisoned {
        Ok(g) => g,
        Err(pe) => pe.into_inner(), // take the guard despite the poison
    };
    println!("  recovered via into_inner(): *guard = {guard}");
    check(
        "recovery: PoisonError::into_inner() yields the guard (data preserved == 50)",
        *guard == 50,
    );
}

// ── Section F: try_lock() — the non-blocking attempt (Ok | WouldBlock) ───────

fn section_f_try_lock() {
    banner("F — try_lock(): non-blocking (Ok | Err(WouldBlock))");
    // `try_lock()` is lock()'s non-blocking cousin: it returns IMMEDIATELY. If the
    // lock is free -> Ok(guard); if held -> Err(TryLockError::WouldBlock). Use it
    // to probe / poll / avoid stalling a latency-sensitive thread. (A THIRD
    // variant, Poisoned, is covered in Section E.)
    let m = Mutex::new(0i32);

    // Free lock -> Ok.
    let probe1 = m.try_lock();
    println!(
        "  unlocked mutex: m.try_lock().is_ok() = {}",
        probe1.is_ok()
    );
    check("try_lock() on a free Mutex returns Ok", probe1.is_ok());
    drop(probe1);

    // Held lock -> WouldBlock. We hold a guard first to make this DETERMINISTIC.
    let _held = m.lock().unwrap();
    let probe2 = m.try_lock();
    let why = match &probe2 {
        Err(TryLockError::WouldBlock) => "WouldBlock",
        Err(TryLockError::Poisoned(_)) => "Poisoned",
        Ok(_) => "Ok",
    };
    println!("  held mutex: m.try_lock() -> Err({why})");
    check(
        "try_lock() on a held Mutex returns Err(WouldBlock)",
        matches!(probe2, Err(TryLockError::WouldBlock)),
    );
    // `lock()` here would BLOCK (or, on the same thread, deadlock) — try_lock()
    // is the safe way to "ask, don't wait".
}

fn main() {
    println!("mutex_rwlock.rs — Phase 4 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a_mutex_basics();
    section_b_guard_is_a_borrow();
    section_c_arc_mutex_threads();
    section_d_rwlock();
    section_e_poisoning();
    section_f_try_lock();
    banner("DONE — all sections printed");
}
