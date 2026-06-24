//! drop_unsafe.rs — Phase 3 bundle.
//!
//! GOAL (one line): show, by printing every value, how the `Drop` trait gives
//! Rust deterministic RAII cleanup, and how `unsafe` is the escape hatch where
//! YOU uphold the invariants the borrow checker cannot prove.
//!
//! This is the GROUND TRUTH for DROP_UNSAFE.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Several rules are COMPILE ERRORS (e.g. a type with a `Drop` impl cannot be
//! `Copy`; a bare `*mut T` is not `Send`; you cannot call `Drop::drop` by
//! hand). Those cannot live in a runnable file — this binary would not build.
//! They are documented in DROP_UNSAFE.md with the exact compiler messages
//! (E0184, E0277, E0040).
//!
//! Run:
//!     just run drop_unsafe   (== cargo run --bin drop_unsafe)

use std::cell::RefCell;

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

/// A tiny RAII Drop sentinel. It prints AND records its name (in drop order)
/// into a shared `RefCell<Vec<&str>>` when destroyed, so the *timing, count,
/// and ORDER* of drops all become observable. It holds a shared `&RefCell`
/// (interior mutability through a shared reference) so two sentinels can share
/// one recorder without `mut`. It implements `Drop`, so it is NOT `Copy`.
struct DropSpy<'a> {
    name: &'static str,
    order: &'a RefCell<Vec<&'static str>>,
}

impl Drop for DropSpy<'_> {
    fn drop(&mut self) {
        self.order.borrow_mut().push(self.name);
        println!("    (drop fires: {})", self.name);
    }
}

// ── Section A: the Drop trait — RAII, deterministic, reverse-order cleanup ──

fn section_a() {
    banner("A — the Drop trait: RAII, deterministic, reverse-order cleanup");
    let order = RefCell::new(Vec::<&'static str>::new());
    {
        // Two owners in one block. Both live until the closing `}`.
        let _a = DropSpy {
            name: "alpha",
            order: &order,
        };
        let _b = DropSpy {
            name: "bravo",
            order: &order,
        };
        println!("  created alpha, then bravo");
        check(
            "no Drop runs while the owners are still in scope",
            order.borrow().is_empty(),
        );
    } // <- `}` fires drop glue: bravo FIRST, then alpha (reverse declaration order)
    println!("  recorded drop order: {:?}", order.borrow());
    check(
        "locals drop in REVERSE declaration order: bravo then alpha",
        *order.borrow() == ["bravo", "alpha"],
    );
}

// ── Section B: std::mem::drop forces an EARLY drop ──────────────────────────

fn section_b() {
    banner("B — std::mem::drop forces an EARLY drop (before scope end)");
    let order = RefCell::new(Vec::<&'static str>::new());
    {
        let _x = DropSpy {
            name: "xray",
            order: &order,
        };
        println!("  created xray");
        check("nothing dropped yet", order.borrow().is_empty());
        std::mem::drop(_x); // drops NOW, at the call site
        println!("  after std::mem::drop(_x): {:?}", order.borrow());
        check(
            "std::mem::drop runs Drop IMMEDIATELY, not at scope end",
            *order.borrow() == ["xray"],
        );
        println!("  (scope continues after the early drop)");
    }
    println!("  after block closed: {:?}", order.borrow());
    check(
        "no double-drop: xray is NOT dropped again at scope end",
        *order.borrow() == ["xray"],
    );
}

// ── Section C: Drop-XOR-Copy — a type with Drop CANNOT be Copy ──────────────

fn section_c() {
    banner("C — Drop-XOR-Copy: a type with Drop CANNOT be Copy (E0184)");
    // A Copy type has NO custom destructor: copying is a cheap bitwise
    // duplicate and BOTH copies stay valid.
    #[derive(Copy, Clone)]
    struct Point(i32, i32);

    let p1 = Point(1, 2);
    let p2 = p1; // COPY (not move): p1 is still valid
    println!(
        "  Point is Copy: p1=({}, {})  p2=({}, {})  (both valid)",
        p1.0, p1.1, p2.0, p2.1
    );
    check(
        "Copy type duplicates: both p1 and p2 stay valid and equal",
        p1.0 == p2.0 && p1.1 == p2.1,
    );
    check(
        "Copy type needs NO drop glue (needs_drop::<Point>() == false)",
        !std::mem::needs_drop::<Point>(),
    );
    check(
        "a Drop type needs drop glue (needs_drop::<DropSpy>() == true)",
        std::mem::needs_drop::<DropSpy<'static>>(),
    );
    println!("  RULE: `impl Drop for T` forbids `impl Copy for T`.");
    println!("  // error[E0184]: the trait `Copy` cannot be implemented for this type;");
    println!("  //              the type has a destructor");
    println!("  // (see DROP_UNSAFE.md for the full compiler message)");
}

// ── Section D: the 4 unsafe superpowers ─────────────────────────────────────

// A `static mut`: accessing/reading/writing it is unsafe (potential data race
// across threads). Single-threaded access here is sound.
static mut COUNTER: u32 = 0;

fn section_d() {
    banner("D — the 4 unsafe superpowers (trivially-sound examples)");
    println!("  `unsafe` unlocks FOUR things the borrow checker cannot check:");
    println!("    1) dereference a raw pointer (*const T / *mut T)   <- shown below");
    println!("    2) call an `unsafe fn`                            <- Section E");
    println!("    3) access/modify a mutable static (static mut)    <- shown below");
    println!("    4) implement an `unsafe trait`                    <- Section F");
    println!("  (the Book & Rustonomicon also list a 5th: access fields of a `union`)");
    println!("  NOTE: `unsafe` does NOT disable the borrow checker - it is a PROMISE");

    // #1 - dereference a raw pointer to a VALID value.
    // Sound: `x` is alive, properly aligned, and not aliased mutably here.
    let x: i32 = 42;
    let p: *const i32 = &x; // creating a raw pointer is SAFE
    let read = unsafe { *p }; // DEREFERENCE is the unsafe op
    println!("  let x = 42i32; let p: *const i32 = &x; unsafe {{ *p }} = {read}");
    check(
        "unsafe deref of a valid, aligned, non-aliased pointer reads 42",
        read == 42,
    );

    // #3 - access/modify a mutable static.
    // Sound: `main` is single-threaded, so there is no concurrent access and
    // hence no data race. Reads must go through a raw pointer in edition 2024
    // (shared references to `static mut` are denied by `static_mut_refs`).
    unsafe {
        COUNTER = 0;
        COUNTER += 3;
    }
    let counter_ptr: *const u32 = &raw const COUNTER;
    let c = unsafe {
        // SAFETY: single-threaded access; no data race on COUNTER.
        *counter_ptr
    };
    println!("  static mut COUNTER; unsafe {{ COUNTER += 3; }} -> {c}");
    check(
        "unsafe can modify a mutable static (single-threaded => no data race)",
        c == 3,
    );
}

// ── Section E: unsafe fn — the CALLER upholds the safety contract ───────────

/// Read `slice[idx]` WITHOUT a bounds check.
///
/// # Safety
/// The caller MUST guarantee `idx < slice.len()`. Passing an out-of-bounds
/// index is Undefined Behavior (the missing bounds check is not performed).
unsafe fn get_unchecked(slice: &[i32], idx: usize) -> i32 {
    // In edition 2024, unsafe operations inside an `unsafe fn` still need their
    // own `unsafe {}` block (`unsafe_op_in_unsafe_fn` is warn-by-default and
    // becomes an error under `-D warnings`).
    unsafe {
        // SAFETY: the caller guaranteed `idx < slice.len()`, so the offset is
        // in bounds, aligned, and points to an initialized i32.
        *slice.as_ptr().add(idx)
    }
}

fn section_e() {
    banner("E — unsafe fn: the CALLER upholds the safety contract");
    let v = [10, 20, 30, 40];
    // Safe call: idx 2 is in bounds, so the contract holds.
    let val = unsafe {
        // SAFETY: idx 2 < v.len() (4); the access is in bounds.
        get_unchecked(&v, 2)
    };
    println!("  unsafe get_unchecked(&[10,20,30,40], 2) -> {val}");
    check(
        "unsafe fn returns the in-bounds element when the contract is upheld",
        val == 30,
    );
    println!("  // CONTRACT (on the fn): caller MUST pass idx < slice.len().");
    println!("  // Passing idx >= len skips the bounds check -> Undefined Behavior.");
}

// ── Section F: unsafe impl Send — YOU assert thread-safety ──────────────────

/// A wrapper around a raw pointer. Raw pointers are neither `Send` nor `Sync`
/// by default (the compiler cannot prove moving/sharing them across threads is
/// sound). If we know our usage is single-owner-per-thread, we take on that
/// proof obligation ourselves with an `unsafe impl`.
struct OwnedPtr(*mut u8);

// SAFETY: `OwnedPtr` is accessed only behind an exclusive owner on a single
// thread; the inner pointer is never shared or mutated concurrently, so moving
// the owning wrapper to another thread cannot introduce a data race.
unsafe impl Send for OwnedPtr {}

/// Compile-time `T: Send` witness, surfaced as a runtime `bool` for a `[check]`.
/// The bound `T: Send` is the load-bearing part: this only compiles when `T` is
/// `Send`, so the returned `true` echoes a compile-time fact.
fn is_send<T: Send>() -> bool {
    // Reference `T` so its bound is exercised (not flagged as unused).
    let _ = std::marker::PhantomData::<T>;
    true
}

fn section_f() {
    banner("F — unsafe impl Send: YOU assert thread-safety the compiler can't");
    check(
        "OwnedPtr satisfies Send (we asserted it via `unsafe impl Send`)",
        is_send::<OwnedPtr>(),
    );

    // The whole POINT of Send: the value can MOVE into another thread. This
    // line would NOT compile without the `unsafe impl Send` above.
    let owned = OwnedPtr(std::ptr::null_mut());
    let handle = std::thread::spawn(move || {
        // Move the whole `OwnedPtr` (a Send wrapper) into a local so the
        // closure captures the WRAPPER, not the raw pointer field directly
        // (edition 2021+ disjoint capture would otherwise grab `*mut u8`).
        let wrapper: OwnedPtr = owned;
        // `is_null()` is a SAFE method on raw pointers (no dereference), so no
        // `unsafe` block is needed to confirm the pointer arrived intact.
        u8::from(wrapper.0.is_null())
    });
    let ok = matches!(handle.join(), Ok(1));
    check(
        "a Send wrapper moves into std::thread::spawn and joins back",
        ok,
    );
    println!("  // NEGATIVE (not runnable): a bare `*mut u8` is NOT Send; a closure");
    println!("  // that captures one fails to compile (E0277) - hence the wrapper.");
}

fn main() {
    println!("drop_unsafe.rs — Phase 3 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
