//! move_semantics.rs — Phase 1 bundle #4.
//!
//! GOAL (one line): show, by printing every value, the SHAPES a move can take
//! (assign, into-fn, partial move out of a struct, `move ||` closure) and how a
//! moved binding can be re-initialized, plus the move-vs-copy-vs-clone split.
//!
//! This is the GROUND TRUTH for MOVE_SEMANTICS.md. Every number, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Run:
//!     just run move_semantics   (== cargo run --bin move_semantics)

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

// ── A. MOVE ON ASSIGN (recap) ───────────────────────────────────────────────
// For a non-Copy type, `let s2 = s1;` is a MOVE: s1's handle is transferred and
// s1 becomes uninitialized. A moved binding can be re-initialized with a NEW
// value; this is NOT "un-moving" the old value.

fn section_a() {
    banner("A — MOVE ON ASSIGN: `let s2 = s1;` transfers ownership");
    let mut s1 = String::from("hello");
    let s2 = s1; // MOVE: s1 is now uninitialized
    println!("after `let s2 = s1;`:");
    println!("  s2 = {s2:?}   (owns the heap buffer now)");
    println!("  s1           -> uninitialized; reading it is a compile error");

    // Re-initialize the SAME binding; its storage slot is reused.
    s1 = String::from("world"); // s1 gets a brand-new String
    println!("after `s1 = String::from(\"world\");`:");
    println!("  s1 = {s1:?}   (a fresh value in the reused slot)");

    check(
        "moved String travelled to s2; s2 == \"hello\"",
        s2 == "hello",
    );
    check(
        "re-initialized binding holds the NEW value; s1 == \"world\"",
        s1 == "world",
    );

    // The illegal line is documented, not shipped runnable:
    //   println!("{}", s1);          // before re-init
    // ...yields:
    //   error[E0382]: borrow of moved value: `s1`
    //    move occurs because `s1` has type `String`, which does not implement
    //    the `Copy` trait
    println!("DOCUMENTED (not run): reading s1 right after the move yields:");
    println!("  error[E0382]: borrow of moved value: `s1`");
    println!("   value borrowed here after move");

    std::mem::drop(s1);
    std::mem::drop(s2);
}

// ── B. MOVE INTO A FUNCTION ─────────────────────────────────────────────────
// `fn take(v: Vec<i32>)` takes the Vec BY VALUE -> the caller's binding is
// moved into the callee and is unusable afterwards. Borrow with `&` to avoid
// the move.

fn take_vec(v: Vec<i32>) -> usize {
    // `v` is now owned by this frame; it is dropped at function exit.
    v.len()
}

fn borrow_sum(slice: &[i32]) -> i32 {
    // `slice` is a borrowed view; the caller keeps ownership.
    slice.iter().sum()
}

fn section_b() {
    banner("B — MOVE INTO A FUNCTION: `fn take(v: Vec<T>)` steals the Vec");
    let v = vec![1, 2, 3, 4];
    let n = take_vec(v); // MOVE: v is gone after this call
    println!("take_vec(vec![1,2,3,4]) returned len = {n}");
    println!("  v is now uninitialized in the caller");
    check("moved Vec had 4 elements", n == 4);

    println!("DOCUMENTED (not run): `println!(\"{{:?}}\", v);` after the call yields:");
    println!("  error[E0382]: borrow of moved value: `v`");
    println!("   move occurs because `v` has type `Vec<i32>`,");
    println!("   which does not implement the `Copy` trait");

    // Alternative: BORROW. The caller stays usable.
    let v2 = vec![10, 20, 30];
    let sum = borrow_sum(&v2); // borrow, NOT a move
    println!("\nalternative: borrow_sum(&v2) keeps v2 usable");
    println!("  sum = {sum}; v2.len() = {} (still owned)", v2.len());
    check(
        "borrow keeps caller usable; sum == 60 and v2.len() == 3",
        sum == 60 && v2.len() == 3,
    );
    std::mem::drop(v2);
}

// ── C. PARTIAL MOVE OUT OF A STRUCT ─────────────────────────────────────────
// `let Person { name, .. } = p;` moves ONLY `name` out (a non-Copy field).
// Copy fields are copied. The remaining fields stay usable INDIVIDUALLY, but
// the WHOLE struct becomes unusable (it is structurally incomplete).

struct Person {
    name: String,
    age: i32,
}

fn section_c() {
    banner("C — PARTIAL MOVE: one field leaves, the rest stay");
    let p = Person {
        name: String::from("Ada"),
        age: 36,
    };
    let Person { name, .. } = p; // moves `name` (String); nothing else moves
    println!("after `let Person {{ name, .. }} = p;`:");
    println!("  name    = {name:?}   (moved OUT of p; this binding owns it)");
    println!(
        "  p.age   = {}       (still readable: i32 is Copy and was not moved)",
        p.age
    );

    check("String field moved out; name == \"Ada\"", name == "Ada");
    check(
        "Copy field still readable after partial move; p.age == 36",
        p.age == 36,
    );

    println!("DOCUMENTED (not run): using the WHOLE `p` (e.g. `let q = p;`) yields:");
    println!("  error[E0382]: use of partially moved value: `p`");
    println!("   value used here after partial move");
    println!("   partial move occurs because `p.name` has type `String`,");
    println!("   which does not implement the `Copy` trait");
    println!("DOCUMENTED (not run): using `p.name` again yields:");
    println!("  error[E0382]: borrow of moved value: `p.name`");

    // NOTE: we deliberately do NOT drop(p) — that would be a whole-struct use.
    std::mem::drop(name);
}

// ── D. `move ||` CLOSURE ────────────────────────────────────────────────────
// `move` forces the closure to TAKE OWNERSHIP of every captured variable,
// instead of the default (borrow by reference). This is required when the
// closure must outlive the capturing scope (e.g. returned from a fn, or handed
// to `thread::spawn`).

fn make_greeter() -> impl Fn() -> String {
    let greeting = String::from("hello");
    // `move` moves `greeting` INTO the closure, so the closure owns it and can
    // outlive `make_greeter`'s frame. The body `.clone()` keeps it `Fn` (not
    // `FnOnce`), so it is callable many times.
    move || greeting.clone()
}

fn section_d() {
    banner("D — `move ||` CLOSURE: forced ownership capture");
    let greeter = make_greeter(); // greeting's frame is gone, but greeter owns its copy
    let out1 = greeter();
    let out2 = greeter(); // Fn (not FnOnce): callable repeatedly
    println!("returned closure outlives its capturing scope:");
    println!("  greeter() call #1 = {out1:?}");
    println!("  greeter() call #2 = {out2:?}");
    check(
        "move closure outlives the capturing scope; call #1 == \"hello\"",
        out1 == "hello",
    );
    check(
        "move closure is Fn, callable repeatedly; call #2 == \"hello\"",
        out2 == "hello",
    );

    // In-scope contrast: a `move` closure that captures by ownership.
    let data = String::from("payload");
    let owns = move || data.len(); // captures `data` BY OWNERSHIP
    let len = owns();
    println!("\nin-scope: `let owns = move || data.len();` -> owns() = {len}");
    check("move closure owns data; len == 7", len == 7);

    println!("DOCUMENTED (not run): returning `|| data.len()` (NO `move`) yields:");
    println!("  error[E0597]: `data` does not live long enough");
    println!("   value captured here");
    println!("   borrowed value does not live long enough");
    println!("   `data` dropped here while still borrowed");

    std::mem::drop(greeter);
}

// ── E. RE-INITIALIZE AFTER MOVE ─────────────────────────────────────────────
// A moved binding is NOT destroyed — its STORAGE slot is reusable. Assigning a
// NEW value to it works; this re-initializes the binding. It is NOT
// "un-moving" the old value (that value now lives wherever it was moved to).

fn section_e() {
    banner("E — RE-INITIALIZE AFTER MOVE: a moved binding is reusable storage");
    let mut x = String::from("a");
    let _y = x; // MOVE: x is now uninitialized (NOT "un-moved")
    x = String::from("b"); // x's slot is reused for a brand-new String
    println!("after `_y = x; x = String::from(\"b\");`:");
    println!("  x  = {x:?}   (re-initialized; the NEW value)");
    println!("  _y = {_y:?}   (the OLD value travelled here)");
    check(
        "re-initialized binding holds the NEW value; x == \"b\"",
        x == "b",
    );
    check("the OLD value travelled to _y; _y == \"a\"", _y == "a");
    std::mem::drop(x);
    std::mem::drop(_y);
}

// ── F. CLONE vs MOVE (summary) ──────────────────────────────────────────────
// MOVE (`let m = s;`) transfers ownership; the source becomes unusable.
// CLONE (`let c = s.clone();`) produces a deep copy; BOTH remain usable.
// CLONE is EXPLICIT — the compiler never inserts it silently.

fn section_f() {
    banner("F — CLONE vs MOVE: clone keeps the source, move doesn't");

    // MOVE: source becomes unusable.
    let original = String::from("seed");
    let moved = original; // MOVE
    println!("move:  `let moved = original;` -> moved = {moved:?}; original is gone");
    check(
        "move transfers ownership; moved == \"seed\"",
        moved == "seed",
    );
    std::mem::drop(moved);

    // CLONE: source stays usable; an independent deep copy is produced.
    let source = String::from("seed");
    let cloned = source.clone(); // CLONE (explicit)
    println!(
        "clone: `let cloned = source.clone();` -> cloned = {cloned:?}; source = {source:?} (BOTH usable)"
    );
    check(
        "clone keeps source usable; source == \"seed\"",
        source == "seed",
    );
    check(
        "clone yields an equal independent value; cloned == \"seed\"",
        cloned == "seed",
    );
    std::mem::drop(source);
    std::mem::drop(cloned);
}

fn main() {
    println!("move_semantics.rs — Phase 1 bundle #4.");
    println!("Every value below is computed by this file.");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
