//! closures.rs — Phase 3 bundle (Memory & Smart Pointers).
//!
//! GOAL (one line): show, by printing every value, that a Rust closure is an
//! anonymous function that CAPTURES variables from its environment, that the
//! compiler picks one of three capture modes (by shared ref, by mut ref, or by
//! value via `move`) and one of three call traits (`Fn` / `FnMut` / `FnOnce`)
//! from how the body uses each capture, and that a closure DESUGARS to an
//! anonymous struct holding the captures plus an `impl` of those traits — which
//! is why its type is unnameable and must be returned as `impl Fn` or
//! `Box<dyn Fn>`.
//!
//! This is the GROUND TRUTH for CLOSURES.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Several closure rules are COMPILE ERRORS (calling an `FnOnce` twice, returning
//! a closure that borrows a local without `move`, passing a `FnMut` where `Fn`
//! is bound). Those cannot live in a runnable file — this binary would not
//! build. They are documented in CLOSURES.md with the exact compiler message
//! (E0382, E0373, E0525).
//!
//! Run:
//!     just run closures   (== cargo run --bin closures)

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

// ── Section A: capture by SHARED reference (&T) — the cheapest mode, a `Fn` ──
// A closure that only READS a capture borrows it by shared reference. That is
// the default and cheapest capture mode, and it makes the closure `Fn`
// (callable by `&self`, repeatedly, without mutating or consuming anything).

fn section_a() {
    banner("A — capture by shared reference (&T): a read-only closure is `Fn`");
    let greeting = String::from("hello");
    println!("  let greeting = String::from(\"hello\");");

    // `greet` captures `greeting` by SHARED reference (the body only reads it).
    // The caller keeps ownership; the closure value just holds a `&String`.
    let greet = || {
        println!(
            "    [closure] greeting = {:?} (len {})",
            greeting,
            greeting.len()
        );
    };
    println!("  let greet = || {{ ... &greeting ... }};   // captures &greeting");

    // A `Fn` closure is callable any number of times; the environment is
    // unchanged on every call (it never mutates or consumes a capture).
    greet();
    greet();
    println!("  greet() called twice (same shared borrow, no mutation)");

    println!("  caller still owns greeting = {:?}", greeting);
    check(
        "a read-only closure borrows by shared ref: caller keeps ownership",
        greeting == "hello",
    );
    check(
        "a Fn closure reads the SAME value on every call (no consumption)",
        greeting.len() == 5,
    );
}

// ── Section B: capture by MUTABLE reference (&mut T) — a `FnMut` closure ────
// A closure that MUTATES a capture borrows it by mutable reference. That makes
// it `FnMut` (callable by `&mut self`, repeatedly, may mutate the environment).
// The `&mut` borrow lasts as long as the closure binding is alive, so the
// caller cannot touch the captured value directly until the closure drops.

fn section_b() {
    banner("B — capture by mutable reference (&mut T): a mutating closure is `FnMut`");
    let mut count = 0u32;
    println!("  let mut count = 0u32;");
    // Scope `bump` so its `&mut count` borrow is released before we read `count`
    // again below. (Reading `count` while `bump` is alive would be a borrow
    // error; this scoping is the workaround.)
    let (c1, c2, c3) = {
        let mut bump = || {
            count += 1;
            count
        };
        println!("  let mut bump = || {{ count += 1; count }};   // captures &mut count");
        (bump(), bump(), bump())
    };
    println!(
        "    bump() called 3 times -> {} then {} then {}",
        c1, c2, c3
    );
    println!(
        "  after `bump` drops, the &mut borrow releases; count = {}",
        count
    );
    check(
        "1st FnMut call returns the incremented counter (1)",
        c1 == 1,
    );
    check(
        "3rd FnMut call returns the incremented counter (3)",
        c3 == 3,
    );
    check(
        "the captured counter's final value is 3 after 3 calls",
        count == 3,
    );
}

// ── Section C: moving a capture OUT makes the closure `FnOnce` (call once) ──
// A closure that MOVES a captured value OUT of its environment (transferring
// ownership away on each call) can be called only ONCE: a second call would
// have nothing left to move. The compiler therefore types it `FnOnce`
// (callable by `self`, consuming the closure). Calling it twice is E0382.

fn section_c() {
    banner("C — moving a capture OUT makes the closure `FnOnce` (call once)");
    let name = String::from("Ferris");
    println!("  let name = String::from(\"Ferris\");");

    // The body is just `name` — returning a captured `String` BY VALUE MOVES it
    // out of the environment into the return value. That single move makes the
    // whole closure `FnOnce`: after one call `name` (now returned) is gone, so a
    // second call cannot exist.
    let consume = || name; // returns `name` by value -> moves it OUT -> FnOnce
    println!("  let consume = || name;   // returns name BY VALUE -> moves it OUT -> FnOnce");
    let recovered = consume();
    println!("  let recovered = consume();  -> {:?}", recovered);
    // consume();   // <-- E0382: use of moved value: `consume` (documented in .md)
    check(
        "an FnOnce closure returns the moved-out String on its single call",
        recovered == "Ferris",
    );
    check(
        "the returned value carries the captured length (6)",
        recovered.len() == 6,
    );
}

/// `make_repeater` builds a closure that OWNS `word` and repeats it `n` times.
/// `move` is REQUIRED here: without it the closure would capture `&word`, but
/// `word` is dropped when `make_repeater` returns -> E0373 ("closure may outlive
/// the current function, but it borrows `word`"). `move` makes the closure take
/// ownership, so it is self-contained and freely returnable. The body only
/// READS `word` (`str::repeat` takes `&self`), so the returned closure is `Fn`.
fn make_repeater(word: String) -> Box<dyn Fn(usize) -> String> {
    Box::new(move |n| word.repeat(n))
}

// ── Section D: `move` forces by-value capture (own, don't borrow) ────────────
fn section_d() {
    banner("D — `move` forces by-value capture (the closure OWNS its captures)");
    println!("  fn make_repeater(word: String) -> Box<dyn Fn(usize) -> String>");
    println!("      Box::new(move |n| word.repeat(n))   // `move ||` owns `word`");
    let rep = make_repeater(String::from("ab"));
    println!("  let rep = make_repeater(String::from(\"ab\"));   // word moved INTO rep");
    println!("    rep(3) -> {:?}", rep(3));
    println!("    rep(2) -> {:?}", rep(2));
    check(
        "a move closure owns its capture: rep(3) == \"ababab\"",
        rep(3) == "ababab",
    );
    check(
        "a move closure that only READS its capture is still `Fn` (callable N times)",
        rep(2) == "abab" && rep(0).is_empty(),
    );
    check(
        "move => by-value capture => 'static => RETURNABLE from a fn (no E0373)",
        rep(4) == "abababab",
    );
}

/// `make_adder` returns a closure by its concrete (anonymous) type via
/// `impl Fn(i32) -> i32`. This is STATIC: the compiler monomorphizes one
/// concrete type per call site, so there is no heap allocation and no virtual
/// call (zero-cost). Closures have anonymous, unnameable types, so `impl Fn` is
/// the only way to return one BY VALUE; `Box<dyn Fn>` (below) returns it boxed
/// when you need to erase the concrete type.
fn make_adder(n: i32) -> impl Fn(i32) -> i32 {
    move |x| x + n
}

// ── Section E: returning a closure — impl Fn (static) vs Box<dyn Fn> (dynamic)
fn section_e() {
    banner("E — returning a closure: `impl Fn` (static) vs `Box<dyn Fn>` (dynamic)");
    let add10 = make_adder(10);
    println!("  fn make_adder(n: i32) -> impl Fn(i32) -> i32 {{ move |x| x + n }}");
    println!("  let add10 = make_adder(10);   // returned by value (impl Fn)");
    println!("    add10(5)   -> {}", add10(5));
    println!("    add10(100) -> {}", add10(100));
    check("impl Fn return: make_adder(10)(5) == 15", add10(5) == 15);
    check(
        "the returned closure is `Fn` (callable many times, not once)",
        add10(0) == 10 && add10(100) == 110,
    );

    // `Box<dyn Fn>` is the DYNAMIC alternative: the concrete type is erased
    // behind a trait object, so DIFFERENT closure types can share one boxed
    // type (e.g. stored together in a Vec). Cost: one heap allocation + an
    // indirect (virtual) call per invocation.
    let boxed: Box<dyn Fn(i32) -> i32> = Box::new(make_adder(7));
    println!("  let boxed: Box<dyn Fn(i32) -> i32> = Box::new(make_adder(7));");
    println!("    boxed(3) -> {}", boxed(3));
    check(
        "Box<dyn Fn>: make_adder(7) boxed, call with 3 == 10",
        boxed(3) == 10,
    );
}

// ── Section F helpers: the three call-trait bounds ──────────────────────────
// They form a supertrait chain — `trait Fn<Args>: FnMut<Args>` and
// `trait FnMut<Args>: FnOnce<Args>` — so every `Fn` IS-A `FnMut` IS-A `FnOnce`.
// Each helper takes the closure BY VALUE (mirroring `FnOnce`'s `self` receiver)
// and returns its output.

fn call_fnonce<T, F: FnOnce() -> T>(f: F) -> T {
    f()
}
fn call_fnmut<T, F: FnMut() -> T>(mut f: F) -> T {
    f()
}
fn call_fn<T, F: Fn() -> T>(f: F) -> T {
    f()
}

// ── Section F: the call-trait hierarchy Fn <: FnMut <: FnOnce ────────────────
fn section_f() {
    banner("F — the hierarchy: `Fn` <: `FnMut` <: `FnOnce` (least restrictive wins)");
    println!("  // trait Fn<Args>:    FnMut<Args>   // Fn is MOST restrictive (callable by &self)");
    println!("  // trait FnMut<Args>: FnOnce<Args>  // FnMut callable by &mut self");
    println!("  // => every Fn IS-A FnMut IS-A FnOnce; a Fn works where FnOnce is asked");

    // (1) A read-only closure is `Fn`. Because Fn <: FnMut <: FnOnce, it
    //     satisfies ALL THREE bounds. It captures `ten` by shared ref, and a
    //     closure capturing only shared refs to `Copy` data is itself `Copy`,
    //     so each helper below takes its own copy of the closure.
    let ten = 10i32;
    let reader = || ten + 1; // reads ten -> Fn
    println!("  let reader = || ten + 1;   // reads `ten` -> Fn (also FnMut, also FnOnce)");
    let via_fn = call_fn(reader);
    let via_fnmut = call_fnmut(reader); // Fn is also FnMut
    let via_fnonce = call_fnonce(reader); // Fn is also FnOnce
    println!("    call_fn(reader)     -> {}", via_fn);
    println!("    call_fnmut(reader)  -> {}", via_fnmut);
    println!("    call_fnonce(reader) -> {}", via_fnonce);
    check("a Fn closure satisfies the Fn bound", via_fn == 11);
    check(
        "a Fn closure ALSO satisfies FnMut (Fn <: FnMut)",
        via_fnmut == 11,
    );
    check(
        "a Fn closure ALSO satisfies FnOnce (Fn <: FnOnce)",
        via_fnonce == 11,
    );

    // (2) A mutating closure is `FnMut` (and `FnOnce`), but NOT `Fn`. Passing it
    //     to call_fn(...) would be E0525 — see CLOSURES.md.
    let mut state = 0i32;
    let mutator = || {
        state += 2;
        state
    }; // mutates -> FnMut
    println!("  let mutator = || {{ state += 2; state }};   // mutates -> FnMut, NOT Fn");
    let via_fnmut2 = call_fnmut(mutator);
    println!(
        "    call_fnmut(mutator)        -> {}  (FnMut-bound accepts it)",
        via_fnmut2
    );
    // The same shape passes the FnOnce bound too (FnMut <: FnOnce):
    let mut state2 = 0i32;
    let via_fnonce_m = call_fnonce(|| {
        state2 += 5;
        state2
    });
    println!(
        "    call_fnonce(FnMut closure) -> {}  (FnMut <: FnOnce)",
        via_fnonce_m
    );
    check("a FnMut closure satisfies the FnMut bound", via_fnmut2 == 2);
    check(
        "a FnMut closure ALSO satisfies FnOnce (FnMut <: FnOnce)",
        via_fnonce_m == 5,
    );

    // (3) A consuming closure is `FnOnce` ONLY — it moves a capture out, so it
    //     cannot be called twice (FnMut/Fn both require repeated calls). Only
    //     the FnOnce-bound helper accepts it.
    let owned = String::from("x");
    let consumer = || owned; // returns `owned` by value -> moves it OUT -> FnOnce
    println!("  let consumer = || owned;   // moves owned OUT -> FnOnce ONLY");
    let via_fnonce3 = call_fnonce(consumer);
    println!("    call_fnonce(consumer) -> {:?}", via_fnonce3);
    check(
        "an FnOnce closure satisfies ONLY the FnOnce bound (it moved the String out)",
        via_fnonce3 == "x",
    );

    // Bonus: a NON-CAPTURING closure coerces to a plain function pointer `fn`.
    // Capturing *anything* would make its type the anonymous closure type, so
    // only zero-capture closures get this coercion.
    let add: fn(i32, i32) -> i32 = |a, b| a + b;
    println!("  let add: fn(i32, i32) -> i32 = |a, b| a + b;   // non-capturing -> coerces to fn");
    println!("    add(2, 3) -> {}", add(2, 3));
    check(
        "a non-capturing closure coerces to a fn pointer (add(2,3) == 5)",
        add(2, 3) == 5,
    );
}

fn main() {
    println!("closures.rs — Phase 3 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
