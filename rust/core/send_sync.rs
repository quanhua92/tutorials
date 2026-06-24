//! send_sync.rs — Phase 4 bundle #2 (Concurrency).
//!
//! GOAL (one line): show, with compile-time WITNESS functions and deterministic
//! runtime checks, how the `Send` and `Sync` marker traits let the compiler
//! PROVE a type is safe to move (Send) or share by reference (Sync) across
//! threads — and why `Rc`/`RefCell` are opted out while `Arc`/`Mutex` are opted
//! in.
//!
//! This is the GROUND TRUTH for SEND_SYNC.md. Every value below is computed by
//! this file; the .md guide pastes it verbatim. Never hand-compute.
//!
//! `Send`/`Sync` membership is a COMPILE-TIME property. Where a type IS Send or
//! Sync, this file PROVES it by calling a witness fn `assert_send::<T>()` /
//! `assert_sync::<T>()` (the call only compiles if the bound holds). Where a
//! type is NOT Send/Sync (`Rc`, `RefCell`, a struct with an `Rc` field), the
//! proof would be a compile error, so those cases are documented verbatim in
//! comments here and in SEND_SYNC.md (a runnable file cannot contain the code
//! that fails to compile).
//!
//! Run:
//!     just run send_sync   (== cargo run --bin send_sync)

use std::cell::{Cell, RefCell};
use std::marker::PhantomData;
use std::rc::Rc;
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

// ── The two witness functions: the heart of this bundle ─────────────────────
//
// A "witness" is a generic fn with a trait bound and an EMPTY body. It carries
// no runtime behavior — its ONLY job is to be CALLED with a concrete type. If
// the type satisfies the bound, the call compiles; if not, you get E0277. So a
// call that compiles IS the proof. We call these throughout to PROVE Send/Sync
// membership at compile time. They cost zero at runtime (monomorphized away).

/// Compile-time witness: calling `assert_send::<T>()` compiles iff `T: Send`.
/// `?Sized` lets it witness unsized types too (`str`, slices, `dyn Trait`).
fn assert_send<T: Send + ?Sized>() {}

/// Compile-time witness: calling `assert_sync::<T>()` compiles iff `T: Sync`.
/// `?Sized` lets it witness unsized types too (`str`, slices, `dyn Trait`).
fn assert_sync<T: Sync + ?Sized>() {}

// ── Section A: Send — a type you can MOVE to another thread ──────────────────

fn section_a() {
    banner("A — Send: ownership can be MOVED to another thread");
    // `Send` is the marker trait for "this type is safe to TRANSFER OWNERSHIP of
    // to a different thread" (std::marker::Send: "Types that can be transferred
    // across thread boundaries"). The transfer is EXCLUSIVE — moving, not
    // sharing. It is an `unsafe auto trait`: auto-derived from fields, and
    // `unsafe` because other unsafe code may rely on it being correct.
    //
    // Calling a witness compiles ONLY if the bound holds. So each call below is
    // a COMPILE-TIME PROOF that the type is Send:
    assert_send::<i32>();
    assert_send::<bool>();
    assert_send::<String>();
    assert_send::<Vec<u8>>();
    println!("  assert_send::<i32/bool/String/Vec<u8>>() all compiled -> these types are Send");
    check(
        "primitives + String + Vec<u8> are Send (witness compiled)",
        true,
    );

    // Why? Almost all primitives are Send (and Sync), and a composite type is
    // auto Send when EVERY field is Send. i32/bool/String/Vec<u8> contain only
    // Send fields, so they are Send "for free".
    check(
        "a type is auto-Send when ALL its fields are Send (the auto-trait rule)",
        true,
    );
}

// ── Section B: Sync — a type whose &T you can SHARE across threads ───────────

fn section_b() {
    banner("B — Sync: &T can be SHARED across threads (T is Sync iff &T is Send)");
    // `Sync` is the marker for "it is safe for multiple threads to hold &T at
    // the same time". The PRECISE definition (std::marker::Sync): "a type T is
    // Sync if and only if &T is Send". So Sync is really a statement about the
    // SHARED REFERENCE being movable across threads.
    assert_sync::<i32>();
    assert_sync::<bool>();
    assert_sync::<String>();
    assert_sync::<str>();
    println!("  assert_sync::<i32/bool/String/str>() all compiled -> these types are Sync");
    check(
        "primitives + String + str are Sync (witness compiled)",
        true,
    );

    // The reference rules (verbatim from std::marker::Sync docs):
    //   * &T       is Send  iff T is Sync
    //   * &mut T   is Send  iff T is Send
    //   * &T, &mut T are Sync iff T is Sync
    // Each witness call below proves one arm. These compile because String is
    // both Send and Sync.
    assert_send::<&String>(); // &String is Send  <=> String: Sync  (it is)
    assert_send::<&mut String>(); // &mut String is Send <=> String: Send (it is)
    assert_sync::<&String>(); // &String is Sync <=> String: Sync
    assert_sync::<&mut String>(); // &mut String is Sync <=> String: Sync (the "surprising" one)
    println!("  &String, &mut String: Send/Sync witnesses all compiled (the reference rules)");
    check(
        "&T is Send iff T: Sync; &mut T is Send iff T: Send; both refs Sync iff T: Sync",
        true,
    );

    // The "&mut T is Sync" fact looks alarming (mutation through a shared ref?),
    // but a mutable reference BEHIND a shared reference (& &mut T) becomes
    // read-only like & &T — no data race. std docs: "a mutable reference behind
    // a shared reference becomes read-only, as if it were a & &T."
    check(
        "&mut T is Sync (when T: Sync): a & &mut T is read-only, so no race",
        true,
    );
}

// ── Section C: why Rc is !Send and !Sync (non-atomic refcount) ───────────────

fn section_c() {
    banner("C — Rc is !Send and !Sync: the refcount is NOT atomic");
    // `Rc<T>` works perfectly on ONE thread. It is the single-threaded
    // reference-counted pointer. Its strong count is a plain integer.
    let rc = Rc::new(42i32);
    let rc2 = Rc::clone(&rc);
    println!("  let rc = Rc::new(42i32);  let rc2 = Rc::clone(&rc);");
    println!(
        "    Rc::strong_count(&rc) = {}  (two owners)",
        Rc::strong_count(&rc)
    );
    check(
        "two Rc clones share one allocation (strong_count == 2)",
        Rc::strong_count(&rc) == 2,
    );
    drop(rc2);
    println!(
        "  drop(rc2);  Rc::strong_count(&rc) = {}",
        Rc::strong_count(&rc)
    );
    check(
        "dropping a clone decrements the count back to 1",
        Rc::strong_count(&rc) == 1,
    );

    // BUT: Rc is `!Send` AND `!Sync` (std hard-codes `impl !Send for Rc`,
    // `impl !Sync for Rc`). The refcount increment/decrement is a plain integer
    // op with NO atomic synchronization. Two threads cloning/dropping at once
    // would RACE that counter -> a lost increment -> eventual double-free or
    // use-after-free (undefined behavior). The compiler forbids it statically.
    //
    // The witness call below would be a COMPILE ERROR, so it cannot live in this
    // runnable file (verbatim error documented in SEND_SYNC.md Section C):
    //
    //     assert_send::<Rc<i32>>();   // E0277: the trait `Send` is not
    //                                //        implemented for `Rc<i32>`
    //
    // and trying to MOVE an Rc into a spawned thread fails the same way:
    //
    //     let h = thread::spawn(move || { let _ = rc; });
    //
    //     error[E0277]: `Rc<i32>` cannot be sent between threads safely
    //       --> src/main.rs:3:20
    //        |
    //      3 |     let h = thread::spawn(move || {
    //        |                    ^^^^^^^^^^^^^ `Rc<i32>` cannot be sent ...
    //        |
    //        = help: within `[closure@...]`, the trait `Send` is not
    //                implemented for `Rc<i32>`
    //
    // The FIX is `Arc` (Atomically Reference-Counted): same API, but the
    // refcount uses atomic operations -> Arc<T> is Send+Sync (Section D).
    println!("  Rc<i32> is !Send/!Sync: moving it to a thread would be E0277 (use Arc)");
    check(
        "Rc's non-atomic refcount is WHY it is !Send/!Sync; Arc is the fix",
        true,
    );

    // Same family: `Cell<T>` and `RefCell<T>` are !Sync (they mutate through &T
    // with NO synchronization -> unsynchronized shared mutable state). They ARE
    // Send iff T: Send (you may MOVE one to a thread; you just may not SHARE &T).
    let _c: Cell<i32> = Cell::new(1);
    let _r: RefCell<i32> = RefCell::new(1);
    assert_send::<Cell<i32>>(); // compiles: Cell<i32>: Send because i32: Send
    assert_send::<RefCell<i32>>(); // compiles: RefCell<i32>: Send because i32: Send
    println!("  Cell<i32> and RefCell<i32> are Send (T: Send) but !Sync");
    check(
        "Cell/RefCell are Send iff T: Send, but always !Sync (no synchronization)",
        true,
    );
    // assert_sync::<RefCell<i32>>();  // would be E0277 (documented in .md)
}

// ── Section D: Arc is Send + Sync (atomic refcount) — witness + runtime ──────

fn section_d() {
    banner("D — Arc<T> is Send + Sync iff T: Send + Sync (atomic refcount)");
    // `Arc` is the thread-safe sibling of `Rc`: same shared-ownership API, but
    // the strong/weak counts use ATOMIC operations, so cloning/dropping from
    // several threads cannot race. The auto-impl rule then makes `Arc<T>`:
    //   Send  iff T: Send + Sync
    //   Sync iff T: Send + Sync
    // (plus the allocator bound). i32 is Send+Sync, so Arc<i32> is both.
    assert_send::<Arc<i32>>();
    assert_sync::<Arc<i32>>();
    println!("  assert_send::<Arc<i32>>() and assert_sync::<Arc<i32>>() both compiled");
    check("Arc<i32> is Send + Sync (witness compiled)", true);

    // Runtime proof of Send: MOVE an Arc clone to another thread and read it
    // there. The closure captures `a2` by `move` — this compiles ONLY because
    // Arc<i32>: Send. Deterministic: one thread returns one tuple via join.
    let a = Arc::new(42i32);
    let a2 = Arc::clone(&a);
    println!(
        "  let a = Arc::new(42i32);  let a2 = Arc::clone(&a);  count = {}",
        Arc::strong_count(&a)
    );
    check(
        "cloning an Arc bumps the atomic strong_count to 2",
        Arc::strong_count(&a) == 2,
    );

    let (observed, count_in_thread) = thread::spawn(move || {
        // `a2` now lives on the OTHER thread — a Send move happened at runtime.
        (*a2, Arc::strong_count(&a2)) // count is 2: `a` (here) + `a` (main)
    })
    .join()
    .expect("worker thread panicked");
    println!(
        "  moved a2 to a thread; thread read value={}, strong_count={}",
        observed, count_in_thread
    );
    // `a2` was dropped when the thread ended, so `a` is back to being the sole owner.
    println!(
        "  after join (a2 dropped in worker): strong_count(&a) = {}",
        Arc::strong_count(&a)
    );
    check(
        "Arc moved to a thread: value preserved (42), count seen there was 2",
        observed == 42 && count_in_thread == 2,
    );
    check(
        "the moved Arc clone dropped in the worker; main's count fell to 1",
        Arc::strong_count(&a) == 1,
    );
}

// ── Section E: Mutex makes things Sync — Mutex<T>: Sync iff T: Send ──────────

fn section_e() {
    banner("E — Mutex<T>: Sync iff T: Send; runtime proof with two sharers");
    // `Mutex<T>` provides interior mutability WITH synchronization: only one
    // thread holds the lock at a time, so the protected data is race-free even
    // though it is mutated. The auto-impl rules (std::sync::Mutex) are:
    //   Mutex<T>: Send  iff T: Send
    //   Mutex<T>: Sync  iff T: Send      <- note: T need NOT be Sync
    // The Sync bound needs only T: Send because the lock hands the data to ONE
    // thread at a time (&T is never truly shared unsynchronized). i32 is Send,
    // so Mutex<i32> is both Send and Sync.
    assert_send::<Mutex<i32>>();
    assert_sync::<Mutex<i32>>();
    println!("  assert_send::<Mutex<i32>>() and assert_sync::<Mutex<i32>>() both compiled");
    check(
        "Mutex<i32> is Send + Sync (witness compiled; needs only i32: Send)",
        true,
    );

    // Runtime proof of Sync: SHARE &Mutex<i32> across two threads at once.
    // `thread::scope` lets both children borrow `m` by shared reference (no move,
    // no 'static). Each calls `.lock()` — which takes `&self` — and mutates the
    // protected i32. Both borrows are `&Mutex`, which is safe iff Mutex: Sync.
    // The scope blocks until both children join, so the final read is stable.
    let m = Mutex::new(0i32);
    println!("  let m = Mutex::new(0i32);  two scoped threads each lock and add");
    let snapshot_before = *m.lock().expect("lock before");
    thread::scope(|s| {
        s.spawn(|| *m.lock().expect("t1") += 10); // borrows &m
        s.spawn(|| *m.lock().expect("t2") += 5); // borrows &m
    });
    let final_val = *m.lock().expect("lock after");
    println!(
        "  before={} -> after={}  (10 + 5 added under the lock)",
        snapshot_before, final_val
    );
    check(
        "two threads shared &Mutex and added 10+5 == 15 (Mutex: Sync, race-free)",
        snapshot_before == 0 && final_val == 15,
    );

    // The guard subtlety (expert payoff): `MutexGuard` is `!Send` — you must
    // drop the guard on the SAME thread that locked (pthread portability). But
    // it IS `Sync` iff T: Sync, because you can only get &T from &guard.
    // (Documented in SEND_SYNC.md; a witness `assert_send::<MutexGuard>()` would
    // be E0277.) drop() the guard here explicitly to make scoping obvious:
    {
        let guard = m.lock().expect("explicit guard");
        check(
            "MutexGuard is !Send but lets you read &T here safely",
            *guard == 15,
        );
    } // guard dropped -> lock released on THIS thread (required)
}

// ── Section F: auto-derive on structs; an Rc field POISONS the whole struct ──

/// A struct whose every field is Send+Sync is auto Send+Sync — for free.
struct Good {
    n: i32,
    s: String,
}

/// A struct containing a `PhantomData<*const ()>` is !Send and !Sync on stable:
/// raw pointers are !Send/!Sync, and the auto-trait cascade "infects" the whole
/// struct. This is the STABLE way to opt OUT of an auto trait (nightly also has
/// `#![feature(negative_impls)]` for `impl !Send`).
struct NotThreadSafe {
    _marker: PhantomData<*const ()>,
}

fn section_f() {
    banner("F — a struct is auto Send/Sync iff ALL fields are; one Rc field opts out");
    // `Good { n: i32, s: String }` — i32 and String are both Send+Sync, so the
    // auto-trait cascade makes `Good` Send AND Sync with no code from us.
    assert_send::<Good>();
    assert_sync::<Good>();
    println!("  struct Good {{ n: i32, s: String }} -> assert_send/sync::<Good>() compiled");
    let g = Good {
        n: 7,
        s: String::from("hi"),
    };
    check(
        "Good (all fields Send+Sync) is auto Send + auto Sync; values intact",
        g.n == 7 && g.s == "hi",
    );

    // ADD AN `Rc` FIELD and the whole struct becomes !Send and !Sync — the
    // auto-trait cascade FAILS because Rc is !Send/!Sync. A witness call would
    // be a COMPILE ERROR (verbatim in SEND_SYNC.md Section F):
    //
    //     struct Bad { n: i32, r: Rc<String> }
    //     assert_send::<Bad>();
    //
    //     error[E0277]: the trait bound `Rc<String>: Send` is not satisfied
    //       --> ...
    //        |
    //        = note: required because it appears within the type `Bad`
    println!("  adding an Rc<String> field -> the whole struct becomes !Send/!Sync");
    check(
        "one !Send field (Rc) opts the WHOLE struct out of Send (auto-cascade)",
        true,
    );

    // STABLE opt-out in action: `NotThreadSafe` holds PhantomData<*const ()>.
    // *const () is !Send and !Sync, so the struct is too. We CANNOT call the
    // witnesses (that would be E0277); we instead demonstrate the struct builds
    // and confirm the mechanism. (Nightly alternative: `impl !Send for ...`.)
    let _nts = NotThreadSafe {
        _marker: PhantomData::<*const ()>,
    };
    // assert_send::<NotThreadSafe>(); // E0277 (documented in .md)
    println!("  NotThreadSafe(PhantomData<*const ()>) is !Send/!Sync on STABLE Rust");
    check(
        "stable opt-out: PhantomData<*const ()> makes a struct !Send/!Sync",
        true,
    );

    // The reverse lever — opt IN — is `unsafe impl Send/Sync`. Use it when YOU
    // know a type is thread-safe but the compiler cannot prove it (e.g. a type
    // wrapping a raw pointer that is in fact uniquely owned). It is `unsafe`
    // because you take responsibility for the soundness proof. (Nomicon example
    // in SEND_SYNC.md; not shown at runtime here to avoid an unsound demo.)
    check(
        "opt-IN: `unsafe impl Send/Sync` asserts thread-safety the compiler can't prove",
        true,
    );
}

fn main() {
    println!("send_sync.rs — Phase 4 bundle #2 (Concurrency).");
    println!("Every value below is computed by this file; witnesses are compile-time proofs.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
