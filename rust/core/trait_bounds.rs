//! trait_bounds.rs — Phase 2 bundle.
//!
//! GOAL (one line): show, by printing every value, how a generic type `T` is
//! NARROWED by TRAIT BOUNDS (`T: PartialOrd`, `T: Clone + Ord`, `impl Display`,
//! `where` clauses) so the body may call those traits' methods, how ASSOCIATED
//! TYPES pin ONE concrete type per impl (`type Item`), how SUPERTRAITS stack
//! contracts (`trait Greet: Named`), and how a bound on an `impl` block gives a
//! BLANKET implementation (`impl<T: Display> Quoted for T`).
//!
//! This is the GROUND TRUTH for TRAIT_BOUNDS.md. Every value below is computed
//! by this file; the .md guide pastes it verbatim. Never hand-compute.
//!
//! Some trait-bound rules are COMPILE ERRORS (e.g. impl'ing a trait with an
//! associated type twice for the same type, E0207). Those cannot live in a
//! runnable file — this binary would not build. They are documented in
//! TRAIT_BOUNDS.md with the exact compiler message.
//!
//! Run:
//!     just run trait_bounds   (== cargo run --bin trait_bounds)

use std::fmt;

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

// ── Section A: a basic bound — `fn largest<T: PartialOrd>(slice)` ────────────
//
// `T: PartialOrd` is a TRAIT BOUND: it narrows "any T" to "any T that can be
// compared with `>`". WITHOUT the bound the body could only move/copy `T` —
// `x > biggest` would be a compile error (no `>` on a totally-unknown type).

fn largest<T: PartialOrd>(slice: &[T]) -> &T {
    let mut biggest = &slice[0];
    for x in &slice[1..] {
        if x > biggest {
            biggest = x;
        }
    }
    biggest
}

// ── Section B: `impl Trait` SUGAR — `fn shout(x: impl Display)` ──────────────
//
// `impl Display` in PARAMETER position is syntax sugar for `<T: Display>`:
//   fn shout(x: impl Display)        ~=     fn shout<T: Display>(x: T)
// The bound lets the body call any Display method (here `to_string`, which the
// stdlib provides via the blanket `impl<T: Display> ToString for T`).

fn shout(x: impl fmt::Display) -> String {
    x.to_string()
}

// ── Section C: multiple bounds (`+`) AND a `where` clause ────────────────────
//
// (1) Multiple bounds with `+`: `T: Clone + Ord` means T must impl BOTH. The
//     body may then use methods from either trait (here `>=` from Ord).
// (2) A `where` clause moves the bounds to AFTER the signature — same
//     semantics, far more readable once you have 2+ generics or 2+ bounds each.

fn max_of<T: Clone + Ord>(a: T, b: T) -> T {
    if a >= b { a } else { b }
}

fn join_display<T, U>(a: T, b: U) -> String
where
    T: fmt::Display,
    U: fmt::Display,
{
    format!("{a} & {b}")
}

// ── Section D: ASSOCIATED TYPES — `type Item` pins ONE type per impl ─────────
//
// An associated type is a type PLACEHOLDER a trait declares and each impl
// fixes to exactly ONE concrete type (`type Item = u32;`). The Book's
// `Iterator` trait is the canonical example:
//     trait Iterator { type Item; fn next(&mut self) -> Option<Self::Item>; }
// Contrast with a GENERIC trait `Foo<T>`: that can be impl'd many times for the
// same type (once per T). An associated type can be set only ONCE per type, so
// callers never annotate it — `Counter::next` is unambiguously `Option<u32>`.

trait Emitter {
    type Item; // placeholder: each impl states exactly one concrete type
    fn next(&mut self) -> Option<Self::Item>;
}

struct Counter {
    count: u32,
}

impl Emitter for Counter {
    type Item = u32; // <- the ONE concrete type for THIS impl
    fn next(&mut self) -> Option<Self::Item> {
        if self.count >= 3 {
            None
        } else {
            let v = self.count;
            self.count += 1;
            Some(v)
        }
    }
}

// ── Section E: SUPERTRAITS — `trait Greet: Named` requires Named ─────────────
//
// `trait Greet: Named` makes Named a SUPERTRAIT of Greet: any type impl'ing
// Greet MUST also impl Named, and Greet's body may call Named's methods
// (`self.name()`). This is a trait bound on `Self`, written in the trait header.

trait Named {
    fn name(&self) -> &str;
}

trait Greet: Named {
    fn greet(&self) -> String {
        format!("Hello, {}!", self.name())
    }
}

struct Person {
    name: &'static str,
}

impl Named for Person {
    fn name(&self) -> &str {
        self.name
    }
}

impl Greet for Person {} // empty: uses the default greet(), Named satisfied above

// ── Section F: a bound on `impl` — BLANKET implementation ────────────────────
//
// A bound on an `impl` block implements a trait for EVERY type satisfying the
// bound. `impl<T: Display> Quoted for T` says: "any T that impls Display also
// impls Quoted". This is the stdlib's `impl<T: Display> ToString for T`
// pattern (the one that gives every Display type a `.to_string()`).

trait Quoted {
    fn quoted(&self) -> String;
}

impl<T: fmt::Display> Quoted for T {
    fn quoted(&self) -> String {
        format!("\"{self}\"")
    }
}

// ── Section A ────────────────────────────────────────────────────────────────

fn section_a() {
    banner("A — basic bound: fn largest<T: PartialOrd>(slice) -> &T");
    let nums = [3, 1, 2];
    let big = largest(&nums);
    println!("  fn largest<T: PartialOrd>(slice: &[T]) -> &T");
    println!("  let nums = [3, 1, 2];");
    println!("  largest(&nums) -> {big}   (bound lets the body use `>`)");
    check(
        "largest(&[3,1,2]) == 3  (T: PartialOrd enables the comparison)",
        *big == 3,
    );

    // The SAME generic works for any PartialOrd type — strings included:
    let words = ["apple", "zebra", "mango"];
    let top = largest(&words);
    println!("  largest(&[\"apple\",\"zebra\",\"mango\"]) -> {:?}", top);
    check(
        "one generic fn, by-virtue-of PartialOrd, also finds the largest &str",
        *top == "zebra",
    );
}

// ── Section B ────────────────────────────────────────────────────────────────

fn section_b() {
    banner("B — impl Trait SUGAR: fn shout(x: impl Display) -> String");
    let a = shout(42u8);
    let b = shout("hi");
    println!("  fn shout(x: impl fmt::Display) -> String {{ x.to_string() }}");
    println!("  shout(42u8)   -> {:?}", a);
    println!("  shout(\"hi\")   -> {:?}", b);
    println!("  (impl Display in arg position == <T: Display>; both calls monomorphize)");
    check("impl Display sugar: shout(42u8) == \"42\"", a == "42");
    check("impl Display sugar: shout(\"hi\") == \"hi\"", b == "hi");
}

// ── Section C ────────────────────────────────────────────────────────────────

fn section_c() {
    banner("C — multiple bounds (T: Clone + Ord) AND a where clause");
    let m = max_of(3, 7);
    let w = max_of("zebra", "apple");
    println!("  fn max_of<T: Clone + Ord>(a: T, b: T) -> T   // +  =  BOTH bounds");
    println!("    max_of(3, 7)             -> {m}");
    println!("    max_of(\"zebra\",\"apple\")  -> {:?}", w);

    let j = join_display(1, "two");
    println!("  fn join_display<T, U>(a: T, b: U) -> String");
    println!("  where T: Display, U: Display                // bounds moved to end");
    println!("    join_display(1, \"two\")  -> {:?}", j);

    check("multiple bounds `Clone + Ord`: max_of(3,7) == 7", m == 7);
    check(
        "multiple bounds work for any Ord type: max_of words == \"zebra\"",
        w == "zebra",
    );
    check(
        "where clause applies Display to BOTH generics: join_display -> \"1 & two\"",
        j == "1 & two",
    );
}

// ── Section D ────────────────────────────────────────────────────────────────

fn section_d() {
    banner("D — associated types: type Item; one concrete type per impl");
    let mut c = Counter { count: 0 };
    let first: <Counter as Emitter>::Item = c.next().unwrap();
    let second: <Counter as Emitter>::Item = c.next().unwrap();
    let third = c.next();
    let fourth = c.next();
    println!("  trait Emitter {{ type Item; fn next(&mut self) -> Option<Self::Item>; }}");
    println!("  impl Emitter for Counter {{ type Item = u32; ... }}");
    println!("    c.next() -> Some({first})");
    println!("    c.next() -> Some({second})");
    println!("    c.next() -> {:?}", third);
    println!("    c.next() -> {:?}", fourth);
    println!(
        "  <Counter as Emitter>::Item resolves to u32 (size = {} bytes)",
        std::mem::size_of::<<Counter as Emitter>::Item>()
    );
    check(
        "associated-type Emitter: Counter.next() first  == Some(0)",
        first == 0,
    );
    check(
        "associated-type Emitter: Counter.next() second == Some(1)",
        second == 1,
    );
    check(
        "Counter stops at 3: third is Some(2), fourth is None",
        third == Some(2) && fourth.is_none(),
    );
    check(
        "<Counter as Emitter>::Item is fixed to u32 (4 bytes)",
        std::mem::size_of::<<Counter as Emitter>::Item>() == 4,
    );
}

// ── Section E ────────────────────────────────────────────────────────────────

fn section_e() {
    banner("E — supertrait: trait Greet: Named  (Greet REQUIRES Named)");
    let p = Person { name: "Ada" };
    println!("  trait Named {{ fn name(&self) -> &str; }}");
    println!("  trait Greet: Named {{ fn greet(&self) -> String {{ ... }} }}");
    println!("  impl Named for Person  /  impl Greet for Person {{}}");
    println!("    p.name()  -> {:?}", p.name());
    println!("    p.greet() -> {:?}", p.greet());
    println!("  (Greet's default body calls self.name() — legal ONLY via the supertrait)");
    check(
        "supertrait satisfied: Person impls BOTH Named and Greet",
        p.name() == "Ada" && p.greet() == "Hello, Ada!",
    );
    check(
        "Greet's default greet() composes the supertrait's name()",
        p.greet() == "Hello, Ada!",
    );
}

// ── Section F ────────────────────────────────────────────────────────────────

fn section_f() {
    banner("F — bound on impl: BLANKET  impl<T: Display> Quoted for T");
    let n: u8 = 42;
    let s = String::from("hi");
    println!("  trait Quoted {{ fn quoted(&self) -> String; }}");
    println!("  impl<T: fmt::Display> Quoted for T {{ ... }}   // every Display type");
    println!("    42u8.quoted()           -> {:?}", n.quoted());
    println!("    String::from(\"hi\").quoted() -> {:?}", s.quoted());
    println!("  (u8 and String are UNRELATED types; both get Quoted via Display)");
    check(
        "blanket impl: a u8 (impl Display) gets Quoted",
        n.quoted() == "\"42\"",
    );
    check(
        "blanket impl: a String (impl Display) ALSO gets Quoted",
        s.quoted() == "\"hi\"",
    );
}

fn main() {
    println!("trait_bounds.rs — Phase 2 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
