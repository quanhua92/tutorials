//! borrowing.rs — Phase 1 bundle.
//!
//! GOAL (one line): show, by printing every value, how `&T` (shared) and
//! `&mut T` (exclusive) let you read and mutate a value WITHOUT taking
//! ownership — the aliasing-XOR-mutability rule enforced at compile time.
//!
//! This is the GROUND TRUTH for BORROWING.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Run:
//!     just run borrowing   (== cargo run --bin borrowing)

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

// A shared reference `&T` is read-only and MANY may exist at once. Dereferencing
// any of them yields the SAME value. We never print pointer addresses (ASLR
// makes them non-reproducible); we assert the structural fact instead.
fn section_a_shared_refs() {
    banner("A — Shared references (&T): many readers, read-only");

    let x: i32 = 42;
    let r1: &i32 = &x; // create a shared reference (does NOT move x)
    let r2: &i32 = &x; // ...and another — many shared refs are allowed
    let r3: &i32 = &x; // ...and a third, all simultaneously

    println!("value x = {x}");
    println!(
        "deref r1 = {} | deref r2 = {} | deref r3 = {}",
        *r1, *r2, *r3
    );
    println!("implicit deref (Display): r1 = {r1} | r2 = {r2} | r3 = {r3}");

    check(
        "three &i32 to the same value all deref to 42",
        *r1 == 42 && *r2 == 42 && *r3 == 42,
    );
    check("shared refs are Copy (r1 still readable again)", *r1 == 42);
    check(
        "x still owned & unchanged after borrowing (borrow != move)",
        x == 42,
    );
}

// A mutable reference `&mut T` is EXACTLY ONE at a time and mutation is allowed.
// Writing through it mutates the original owner's value: the ref does not own
// the value, it only holds the permission to mutate it.
fn section_b_exclusive_ref() {
    banner("B — Exclusive reference (&mut T): one writer, mutable");

    let mut x: i32 = 10;
    println!("before: x = {x}");
    {
        let r: &mut i32 = &mut x; // exactly one &mut — no other ref may coexist
        *r = 99; // mutate THROUGH the reference
        println!("inside block, after *r = 99: *r = {}", *r);
    } // r ends here; x is free to be borrowed again
    println!("after:  x = {x}  (mutation reflected on the owner)");

    check(
        "&mut mutation reflects on the original (x 10 -> 99)",
        x == 99,
    );
}

// Borrowing does NOT move. After `let r = &s;` the owner `s` is still usable.
// Contrast with a move, which invalidates the source (see OWNERSHIP).
fn section_c_borrow_does_not_move() {
    banner("C — Borrowing keeps ownership usable (borrow != move)");

    let s = String::from("hi"); // owner
    let r = &s; // borrow — s is NOT moved
    println!("borrow r reads: \"{r}\"");
    println!("owner s still works after the borrow: \"{s}\""); // s still owned

    check("s is still usable after `let r = &s;`", s == "hi");
    // The owner must outlive its references — the compiler forbids a dangling
    // reference (a & to data already dropped); see LIFETIMES for the mechanism.
}

// Non-Lexical Lifetimes (NLL): a borrow's scope ends at its LAST USE, not at the
// closing brace. So a fresh &mut AFTER the last & use is legal — the immutable
// borrows are already "dead" when the mutable one is born.
fn section_d_nll() {
    banner("D — NLL: a borrow ends at last use, so a later &mut is fine");

    let mut s = String::from("nll");
    let r1 = &s; // immutable borrow starts
    let r2 = &s; // another immutable — fine
    println!("shared reads: \"{r1}\" + \"{r2}\""); // LAST use of r1, r2
    // r1, r2 are now dead -> s is free to be mutably borrowed:
    let r3 = &mut s; // legal under NLL: no overlap with r1/r2
    r3.push_str(" works");
    println!("mutated via &mut: \"{s}\"");

    check(
        "NLL: &mut after last & use compiles and runs",
        s == "nll works",
    );
}

// Borrowing a slice `&[T]`: a function can read a whole sequence without owning
// (or copying) it. This is the idiomatic "lend me the data" signature.
fn section_e_slice_borrow() {
    banner("E — Borrowing a slice &[T]: read without owning");

    let data: [i32; 4] = [4, 8, 15, 23];
    let sum = sum_slice(&data); // borrow the array as &[i32]; data still owned
    println!("data = {data:?}");
    println!("sum_slice(&data) = {sum}  (data not moved)");

    check("sum_slice([4, 8, 15, 23]) == 50", sum == 50);
    check(
        "data still owned after passing &data to a fn",
        data == [4, 8, 15, 23],
    );
}

// Mutable reborrow: from an existing &mut you mint another &mut to the same
// data with `&mut *r`. The original is reborrowed and unavailable until the
// reborrow ends, so the XOR-mutability invariant still holds (still ONE writer).
fn section_f_reborrow() {
    banner("F — Mutable reborrow: &mut *r reborrows a &mut");

    let mut x: i32 = 7;
    let r: &mut i32 = &mut x;
    add_one(r); // passing `r` reborrows it as &mut *r into the fn
    println!("after add_one(&mut x): x = {x}");

    check("reborrow &mut *r mutated through a fn (x 7 -> 8)", x == 8);
}

/// Sum a borrowed slice of i32. Takes `&[i32]` so it reads without owning.
fn sum_slice(nums: &[i32]) -> i32 {
    nums.iter().sum()
}

/// Take an exclusive ref and mutate through it. The call site passes `r`, which
/// Rust implicitly reborrows as `&mut *r`, so the caller keeps ownership.
fn add_one(n: &mut i32) {
    *n += 1;
}

fn main() {
    println!("borrowing.rs — Phase 1 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a_shared_refs();
    section_b_exclusive_ref();
    section_c_borrow_does_not_move();
    section_d_nll();
    section_e_slice_borrow();
    section_f_reborrow();
    banner("DONE — all sections printed");
}
