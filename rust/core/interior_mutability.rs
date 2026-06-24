//! interior_mutability.rs — Phase 3 bundle.
//!
//! GOAL (one line): show, by printing every value, how the interior-mutability
//! pattern (`Cell`, `RefCell`, `Mutex`, `RwLock`, `UnsafeCell`) lets you MUTATE
//! through a shared `&T` by moving the aliasing-XOR-mutability rule off the
//! compile-time borrow checker — onto a RUNTIME check (`RefCell` panics) or a
//! BLOCKING lock (`Mutex`/`RwLock`).
//!
//! This is the GROUND TRUTH for INTERIOR_MUTABILITY.md. Every number, table,
//! and worked example in the guide is printed by this file. Change it ->
//! re-run -> re-paste. Never hand-compute.
//!
//! The compile-time rule this evades ("`&T` is read-only") is enforced by the
//! borrow checker (see BORROWING). The interior-mutability types use `unsafe`
//! internally (an `UnsafeCell`) to mutate behind `&T`, then expose a SAFE API
//! that re-checks the aliasing rule dynamically — so the soundness contract is
//! upheld, just not by the static checker.
//!
//! Run:
//!     just run interior_mutability   (== cargo run --bin interior_mutability)

use std::cell::{Cell, RefCell, UnsafeCell};
use std::panic::{self, AssertUnwindSafe};
use std::rc::Rc;
use std::sync::{Arc, Mutex, RwLock};
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

/// Downcast a caught panic payload to a readable string. `panic!` stores either
/// a `&'static str` (literal message) or a `String` (formatted message); both
/// are covered so the actual RefCell panic text is recoverable.
fn panic_payload_str(payload: &(dyn std::any::Any + Send)) -> String {
    if let Some(s) = payload.downcast_ref::<&'static str>() {
        (*s).to_string()
    } else if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else {
        String::from("(non-string panic payload)")
    }
}

// ── Section A: Cell<T> — interior mutability for COPY types ──────────────────

fn section_a_cell() {
    banner("A — Cell<T>: interior mutability for COPY types (get/set)");
    // `Cell<T>` mutates through a shared `&T` by COPYING values in and out. The
    // bound `T: Copy` is required because get()/set()/replace() move whole
    // values through the cell — there is NEVER a borrow pointing into the
    // interior, so the aliasing rule is trivially upheld. Cheap, single-threaded.
    let cell = Cell::new(5i32);
    println!(
        "  let cell = Cell::new(5i32);   cell.get() = {}",
        cell.get()
    );

    // Mutate through a SHARED reference — note: `cell` is NOT declared `mut`.
    let r: &Cell<i32> = &cell;
    r.set(7);
    println!("  let r: &Cell<i32> = &cell;  r.set(7);   // mutate via an & !");
    println!("  cell.get() = {}", cell.get());
    check("Cell: set(7) through &cell => get() == 7", cell.get() == 7);

    // replace() installs a new value and returns the OLD one, all through &Cell.
    let old = cell.replace(42);
    println!(
        "  cell.replace(42) -> old = {old};  cell.get() = {}",
        cell.get()
    );
    check(
        "Cell::replace returns the old value (7) and installs 42",
        old == 7 && cell.get() == 42,
    );

    // Layout: Cell<T> shares T's representation (it wraps an UnsafeCell<T>),
    // so it adds NO borrow counter — that is why it is limited to Copy types.
    let sz = std::mem::size_of::<Cell<i32>>();
    let inner_sz = std::mem::size_of::<i32>();
    println!("  size_of::<Cell<i32>>() = {sz}, size_of::<i32>() = {inner_sz}  (identical)");
    check(
        "Cell<i32> shares i32's layout (no borrow state — needs T: Copy)",
        sz == inner_sz,
    );
}

// ── Section B: RefCell<T> — borrow/borrow_mut checked at RUNTIME ─────────────

fn section_b_refcell_borrow() {
    banner("B — RefCell<T>: borrow / borrow_mut, checked at RUNTIME");
    // `RefCell<T>` works for ANY T (not just Copy). It hands out `Ref<T>`
    // (shared, like &T) and `RefMut<T>` (exclusive, like &mut T) smart pointers,
    // each Deref-implementing, and tracks an integer borrow count. The
    // aliasing-XOR-mutability rule is enforced when you call borrow/borrow_mut.
    let logs = RefCell::new(Vec::<&str>::new());
    println!("  let logs = RefCell::new(Vec::<&str>::new());");

    // borrow_mut() -> RefMut<Vec>: DerefMut, so push() goes straight through.
    logs.borrow_mut().push("hello");
    println!("  logs.borrow_mut().push(\"hello\");");
    println!(
        "  logs.borrow().len() = {}   logs.borrow()[0] = {:?}",
        logs.borrow().len(),
        logs.borrow()[0],
    );
    check(
        "RefCell<Vec>: borrow_mut().push then borrow().len() == 1",
        logs.borrow().len() == 1,
    );

    // Many shared borrow() guards may be alive at once, exactly like many &T.
    {
        let r1 = logs.borrow();
        let r2 = logs.borrow();
        println!(
            "  two borrow() at once: r1[0] = {:?}, r2[0] = {:?}",
            r1[0], r2[0]
        );
        check(
            "RefCell allows multiple simultaneous borrow() guards",
            r1[0] == "hello" && r2[0] == "hello",
        );
    } // r1, r2 drop here -> shared borrow count back to 0
}

// ── Section C: RefCell — a second borrow_mut PANICS (caught, not fatal) ──────

fn section_c_refcell_panic() {
    banner("C — RefCell: a second borrow_mut PANICS (caught, not fatal)");
    let cell = RefCell::new(5i32);
    println!("  let cell = RefCell::new(5i32);");

    // Two borrow_mut() in the same scope is an aliasing violation. The borrow
    // checker cannot see this (the borrows are runtime RefMut values), so
    // RefCell detects it at RUNTIME and panics. We catch the panic so the
    // program keeps running — the default panic strategy is `unwind`, which is
    // what makes catch_unwind work. The panic HOOK (which prints to stderr) is
    // silenced for this deliberately-triggered panic, then restored.
    let prev_hook = panic::take_hook();
    panic::set_hook(Box::new(|_| {}));
    let result = panic::catch_unwind(AssertUnwindSafe(|| {
        let _b1 = cell.borrow_mut(); // first exclusive borrow — OK
        let _b2 = cell.borrow_mut(); // PANIC: already borrowed
    }));
    panic::set_hook(prev_hook);
    println!(
        "  two borrow_mut() in one scope -> catch_unwind caught a panic = {}",
        result.is_err()
    );
    check(
        "double borrow_mut is caught as Err (not fatal to the program)",
        result.is_err(),
    );

    if let Err(payload) = result {
        let msg = panic_payload_str(&*payload);
        println!("  panic message: {:?}", msg);
        check(
            "the RefCell panic message mentions 'borrowed'",
            msg.contains("borrowed"),
        );
    }

    // During the unwind, _b1 (the first RefMut) was DROPPED, which released the
    // borrow — so the cell is back in a clean state and usable again.
    let after = *cell.borrow();
    println!("  after the panic, cell.borrow() = {after}  (cell still usable)");
    check(
        "after a caught panic the RefCell is usable (RefMut dropped on unwind)",
        after == 5,
    );
}

// ── Section D: Rc<RefCell<T>> — multiple owners that can MUTATE ──────────────

fn section_d_rc_refcell() {
    banner("D — Rc<RefCell<T>>: multiple owners that can MUTATE");
    // Rc<T> gives multiple owners but only shared (&) access. RefCell<T> adds
    // mutation behind that &. Together: shared, mutable, SINGLE-THREADED — the
    // classic "graph node" combo. (The thread-safe twin is Arc<Mutex<T>>.)
    let shared: Rc<RefCell<i32>> = Rc::new(RefCell::new(0));
    println!("  let shared = Rc::new(RefCell::new(0));");

    let owner_a = Rc::clone(&shared);
    let owner_b = Rc::clone(&shared);
    println!("  let owner_a = Rc::clone(&shared);  let owner_b = Rc::clone(&shared);");
    println!("  Rc strong_count = {}", Rc::strong_count(&shared));
    check(
        "two clones + original => Rc strong_count == 3",
        Rc::strong_count(&shared) == 3,
    );

    // Mutate through ONE clone ...
    *owner_a.borrow_mut() += 99;
    println!("  *owner_a.borrow_mut() += 99;   // mutate through one clone");

    // ... and read through the OTHER clone: they share ONE RefCell interior.
    let seen_by_a = *owner_a.borrow();
    let seen_by_b = *owner_b.borrow();
    println!("  owner_a.borrow() = {seen_by_a}   owner_b.borrow() = {seen_by_b}",);
    check(
        "Rc<RefCell<T>>: a mutation via one clone is seen by all (== 99)",
        seen_by_a == 99 && seen_by_b == 99,
    );
}

// ── Section E: Mutex / RwLock — thread-safe interior mutability ──────────────

fn section_e_mutex_rwlock() {
    banner("E — Mutex / RwLock: thread-safe interior mutability (block, not panic)");
    // `Mutex<T>` is the multi-threaded RefCell. lock() BLOCKS (waits) if another
    // thread holds the lock instead of panicking — so writers are serialized by
    // the OS rather than the borrow rule. (A panic only happens if a thread
    // panicked WHILE holding the lock, leaving it "poisoned".)
    let m = Mutex::new(0i32);
    println!("  let m = Mutex::new(0i32);");
    {
        let mut guard = m.lock().unwrap();
        *guard = 42;
        println!("  inside lock(): *guard = 42");
    } // guard drops -> lock released
    let after = *m.lock().unwrap();
    println!("  after block: *m.lock().unwrap() = {after}");
    check("Mutex lock + mutate -> 42", after == 42);

    // `RwLock<T>`: many readers OR one writer — the same runtime rule, but
    // read-heavy workloads get parallel shared reads.
    let rw = RwLock::new(100i32);
    {
        let r1 = rw.read().unwrap();
        let r2 = rw.read().unwrap(); // many read() guards at once is fine
        println!("  RwLock: two read() guards at once: {r1} and {r2}");
        check(
            "RwLock allows multiple simultaneous read() guards",
            *r1 == 100 && *r2 == 100,
        );
    } // r1, r2 drop -> readers gone
    {
        let mut w = rw.write().unwrap();
        *w += 1;
        println!("  RwLock: write() guard mutates 100 -> {w}");
        check("RwLock write() guard mutates -> 101", *w == 101);
    }

    // Real thread-safety, kept DETERMINISTIC: 4 threads each add 10 under the
    // same Arc<Mutex>. After join the total is always 40 regardless of how the
    // OS scheduled them — the lock serializes the increments. (We print only the
    // post-join total, never per-thread order — see the DETERMINISM rule.)
    let counter = Arc::new(Mutex::new(0i32));
    let mut handles = Vec::with_capacity(4);
    for _ in 0..4 {
        let counter = Arc::clone(&counter);
        handles.push(thread::spawn(move || {
            *counter.lock().unwrap() += 10;
        }));
    }
    for h in handles {
        h.join().unwrap();
    }
    let total = *counter.lock().unwrap();
    println!("  4 threads * (+10) under Arc<Mutex> -> total = {total}");
    check(
        "Arc<Mutex<i32>>: 4 threads * 10 = 40 (lock serializes, deterministic)",
        total == 40,
    );
}

// ── Section F: UnsafeCell — the primitive under Cell / RefCell / Mutex ───────

fn section_f_unsafecell() {
    banner("F — UnsafeCell: the primitive beneath Cell / RefCell / Mutex");
    // `UnsafeCell<T>` is the ONLY core-language-legal way to have an `&T` whose
    // interior may be mutated. Cell, RefCell, Mutex, and RwLock ALL wrap an
    // UnsafeCell internally and add the bookkeeping (none / borrow count / OS
    // lock) that re-establishes the aliasing rule. Used directly it is unsafe:
    // YOU must uphold the rule. Here we only CONSTRUCT it and read structural
    // facts — we never dereference the raw pointer (that is the DROP_UNSAFE
    // bundle's territory).
    let uc = UnsafeCell::new(5i32);
    let sz = std::mem::size_of::<UnsafeCell<i32>>();
    let inner_sz = std::mem::size_of::<i32>();
    println!("  let uc = UnsafeCell::new(5i32);");
    println!("  size_of::<UnsafeCell<i32>>() = {sz}, size_of::<i32>>() = {inner_sz}  (identical)");
    check(
        "UnsafeCell<T> shares T's layout (repr(transparent), zero-cost wrapper)",
        sz == inner_sz,
    );

    // get() returns a *mut T pointing at the interior. Dereferencing it is the
    // unsafe step; is_null() is a safe, deterministic structural query.
    let ptr = uc.get();
    check(
        "UnsafeCell::get() yields a non-null raw pointer to the interior",
        !ptr.is_null(),
    );
    println!("  uc.get() -> *mut i32  (raw ptr; dereferencing it is `unsafe`)");
}

fn main() {
    println!("interior_mutability.rs — Phase 3 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a_cell();
    section_b_refcell_borrow();
    section_c_refcell_panic();
    section_d_rc_refcell();
    section_e_mutex_rwlock();
    section_f_unsafecell();
    banner("DONE — all sections printed");
}
