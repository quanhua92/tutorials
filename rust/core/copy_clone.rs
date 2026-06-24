//! copy_clone.rs — Phase 1 bundle #2.
//!
//! GOAL (one line): show, by printing every value, that `Copy` types are
//! BITWISE-copied on assignment (so the source stays usable), that `Clone` is
//! an EXPLICIT, possibly-deep `.clone()`, and that a type is `Copy` only when
//! ALL its fields are `Copy` and it has NO `Drop` impl.
//!
//! This is the GROUND TRUTH for COPY_CLONE.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Some rules are COMPILE ERRORS (e.g. `#[derive(Copy)]` on a type holding a
//! `String` field, or on a type with a `Drop` impl). Those cannot live in a
//! runnable file — this binary would not build. They are documented in
//! COPY_CLONE.md with the exact compiler message (E0204, E0184).
//!
//! Run:
//!     just run copy_clone   (== cargo run --bin copy_clone)

use std::cell::Cell;

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

// ── Section A: Copy types are bitwise-copied on assignment ──────────────────

fn section_a() {
    banner("A — Copy types are BITWISE-COPIED on assignment; source stays usable");
    // i32 is Copy: `let b = a` is an implicit bitwise copy, NOT a move. Both a
    // and b remain valid, independent values.
    let a: i32 = 5;
    let b = a;
    println!("  let a: i32 = 5;");
    println!("  let b = a;   // i32 is Copy -> bitwise copy (a stays usable)");
    println!("    a = {}, b = {}  (both readable)", a, b);
    check(
        "Copy keeps source usable: a == 5 && b == 5 after `let b = a`",
        a == 5 && b == 5,
    );

    // Copies are independent: deriving a new value from b leaves b untouched.
    let c = b + 100;
    println!("  let c = b + 100 = {};   b is still {}", c, b);
    check(
        "copies are independent: c = 105 while b stays 5",
        b == 5 && c == 105,
    );

    // Copy PROPAGATES through composite types: a tuple of Copy is Copy, an array
    // of Copy is Copy, and a shared reference `&T` is Copy even when `T` is not.
    let t1 = (1, 2, 3);
    let t2 = t1; // (i32, i32, i32) is Copy
    let arr1 = [10u8, 20, 30];
    let arr2 = arr1; // [u8; 3] is Copy
    let big = String::from("non-Copy payload");
    let r1: &String = &big;
    let r2 = r1; // &String is Copy (the reference); the String is not
    println!("  let t1 = (1,2,3);        let t2 = t1;   // tuple of Copy -> Copy");
    println!("  let arr1 = [10,20,30];   let arr2 = arr1; // array of Copy -> Copy");
    println!("  let big = String::from(\"non-Copy payload\");");
    println!("  let r1 = &big;  let r2 = r1;  // &T is Copy even when T is not");
    println!("    t1 = {:?}, t2 = {:?}", t1, t2);
    println!("    arr1 = {:?}, arr2 = {:?}", arr1, arr2);
    println!(
        "    r1 = {:?}, r2 = {:?}  (two refs, same referent)",
        r1, r2
    );
    check(
        "tuples of Copy are Copy: t1 and t2 both readable & equal",
        t1 == t2 && t1.0 == 1,
    );
    check(
        "arrays of Copy are Copy: arr1 and arr2 both readable & equal",
        arr1 == arr2,
    );
    check(
        "&T is Copy even when T is not: r1 AND r2 both usable after copy",
        r1.as_str() == "non-Copy payload" && r2.as_str() == "non-Copy payload",
    );
}

// ── Section B: non-Copy types MOVE on assignment (the contrast) ─────────────

fn section_b() {
    banner("B — non-Copy types MOVE on assignment (contrast with Section A)");
    // String is Clone but NOT Copy. `let s2 = s1` MOVES the heap-buffer handle,
    // so s1 is poisoned. Reading s1 afterwards is compile error E0382 (documented
    // in COPY_CLONE.md) — this file therefore reads only s2 after the move.
    let s1 = String::from("hello");
    let s2 = s1; // MOVE: s1 dead, s2 owns the heap buffer
    println!("  let s1 = String::from(\"hello\");");
    println!("  let s2 = s1;   // MOVE (String is not Copy) -> s1 is now POISONED");
    println!(
        "                  s2 = {:?}  (len {}, cap {})",
        s2,
        s2.len(),
        s2.capacity()
    );
    check(
        "non-Copy String moves: the new owner s2 carries the value",
        s2 == "hello" && s2.len() == 5,
    );

    // The escape hatch is an EXPLICIT .clone(): a user-defined deep copy that
    // leaves the source usable. The two bindings are then independent.
    let c1 = String::from("rust");
    let c2 = c1.clone();
    println!("  let c1 = String::from(\"rust\");  let c2 = c1.clone();  // explicit deep copy");
    println!("    c1 = {:?}, c2 = {:?}  (both usable)", c1, c2);
    check(
        "explicit .clone() keeps the source usable: c1 and c2 both equal \"rust\"",
        c1 == "rust" && c2 == "rust",
    );

    // Clone is DEEP: mutating the clone never affects the source.
    let mut d2 = c2.clone();
    d2.push_str("acean");
    println!("  let mut d2 = c2.clone();  d2.push_str(\"acean\");");
    println!("    d2 = {:?}, but c2 is still {:?}", d2, c2);
    check(
        "Clone is deep: editing the clone leaves the source untouched",
        c2 == "rust" && d2 == "rustacean",
    );
}

// ── Section C: a struct of all-Copy fields is Copy ──────────────────────────

/// All fields are `Copy` (`i32`), so this struct qualifies for `Copy`. Note the
/// paired derive: `Copy` is a sub-trait of `Clone`, so they are derived
/// together as `#[derive(Copy, Clone)]`.
#[derive(Debug, Copy, Clone, PartialEq, Eq)]
struct Point {
    x: i32,
    y: i32,
}

fn section_c() {
    banner("C — a struct of all-Copy fields is Copy: assign COPIES, not moves");
    let p1 = Point { x: 3, y: 4 };
    let p2 = p1; // Point is Copy: bitwise copy; p1 stays usable
    println!("  #[derive(Copy, Clone)]  struct Point {{ x: i32, y: i32 }}");
    println!("  let p1 = Point {{ x: 3, y: 4 }};");
    println!("  let p2 = p1;   // COPY (all fields Copy) -> p1 stays usable");
    println!("    p1 = {:?}, p2 = {:?}", p1, p2);
    check(
        "Copy struct: p1 and p2 both usable & equal after `let p2 = p1`",
        p1 == p2 && p1.x == 3,
    );

    // Copies are independent: mutate the copy, the original is unchanged.
    let mut p3 = p1;
    p3.x = 99;
    println!("  let mut p3 = p1;  p3.x = 99;");
    println!("    p1 = {:?}, p3 = {:?}  (independent)", p1, p3);
    check(
        "Copy struct copies are independent: mutating p3 leaves p1 unchanged",
        p1.x == 3 && p3.x == 99,
    );
}

// ── Section D: ONE non-Copy field makes the whole struct non-Copy ───────────

/// Holds a `String` (non-Copy), so the whole struct is non-Copy. Deriving
/// `Copy` here would be compile error E0204 (see COPY_CLONE.md). `Clone` has no
/// such field requirement, so it is fine.
#[derive(Debug, Clone, PartialEq, Eq)]
struct Labeled {
    tag: String,
    value: i32,
}

fn section_d() {
    banner("D — adding ONE non-Copy field makes the whole struct non-Copy (move)");
    let l1 = Labeled {
        tag: String::from("id"),
        value: 7,
    };
    let l2 = l1; // MOVE: l1 dead, l2 owns the String
    println!("  #[derive(Clone)]  struct Labeled {{ tag: String, value: i32 }}");
    println!("  let l1 = Labeled {{ tag: \"id\", value: 7 }};");
    println!("  let l2 = l1;   // MOVE (String field not Copy) -> l1 is now POISONED");
    println!("    l2 = {:?}", l2);
    check(
        "struct with a non-Copy field moves: the new owner l2 carries the value",
        l2.value == 7 && l2.tag == "id",
    );

    // Clone still works for non-Copy structs (no field-Copy requirement).
    let k1 = Labeled {
        tag: String::from("k"),
        value: 1,
    };
    let k2 = k1.clone();
    println!(
        "  let k1 = Labeled{{tag:\"k\",value:1}};  let k2 = k1.clone();  // explicit deep copy"
    );
    println!(
        "    k1 = {:?}, k2 = {:?}  (both usable, independent)",
        k1, k2
    );
    check(
        "Clone works even for non-Copy structs: k1 and k2 both usable & equal",
        k1 == k2,
    );
}

// ── Section E: Clone is explicit and may be deep (Vec<i32>) ─────────────────

fn section_e() {
    banner("E — Clone is EXPLICIT and may be DEEP: Vec<i32>");
    // Vec is Clone but NOT Copy: cloning allocates a fresh buffer and copies
    // every element. The two Vecs are then fully independent.
    let v1 = vec![10, 20, 30, 40];
    let v2 = v1.clone();
    println!("  let v1 = vec![10, 20, 30, 40];  let v2 = v1.clone();");
    println!("    v1 = {:?}, v2 = {:?}", v1, v2);
    check(
        "Vec clone keeps source usable: v1 and v2 equal",
        v1 == v2 && v1.len() == 4,
    );

    // Independence: a push on the clone never appears on the original.
    let mut v3 = v1.clone();
    v3.push(50);
    println!("  let mut v3 = v1.clone();  v3.push(50);");
    println!("    v3 = {:?}, v1 still = {:?}  (independent)", v3, v1);
    check(
        "Clone is deep: v3.push does not affect v1",
        v1.len() == 4 && v3.len() == 5 && v3[4] == 50,
    );
}

// ── Section F: Copy XOR Drop — a Drop type CANNOT be Copy ───────────────────

/// A custom-`Drop` guard. It CANNOT be `Copy`: a bitwise copy combined with
/// custom cleanup would run `drop` twice and double-free the resource. Trying
/// `#[derive(Copy)]` + `impl Drop` is compile error E0184 (see COPY_CLONE.md).
/// So `Guard` is move-only, exactly like `String`.
struct Guard<'a> {
    name: &'static str,
    drops: &'a Cell<u32>,
}

impl Drop for Guard<'_> {
    fn drop(&mut self) {
        self.drops.set(self.drops.get() + 1);
        println!("    (drop fires: {})", self.name);
    }
}

fn section_f() {
    banner("F — Copy XOR Drop: a type with a custom Drop CANNOT be Copy");
    let drops = Cell::new(0u32);
    {
        let g1 = Guard {
            name: "g1",
            drops: &drops,
        };
        let _g2 = g1; // MOVE (not copy): Guard has a Drop impl, so it's non-Copy
        println!("  created g1; moved into _g2 (Guard is non-Copy because it has Drop)");
        check(
            "Drop type is non-Copy: g1 moved into _g2, no bitwise copy made",
            drops.get() == 0,
        );
    } // _g2 drops here, exactly once (g1 was moved, so it does not drop again)
    println!("  after block: total drops = {}", drops.get());
    check(
        "Drop runs exactly once for a moved Drop type (no double-free)",
        drops.get() == 1,
    );
    // NOTE: `#[derive(Copy)]` + `impl Drop for Guard` = error E0184. It cannot
    // be shown in a runnable file; see COPY_CLONE.md for the verbatim message.
}

fn main() {
    println!("copy_clone.rs — Phase 1 bundle #2.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
