//! macro_rules.rs — Phase 6 bundle.
//!
//! GOAL (one line): show, by printing every value, that a `macro_rules!` macro
//! pattern-matches on input TOKENS at compile time and emits substituted code —
//! driven by fragment specifiers, repetitions, hygiene, recursion, and export.
//!
//! This is the GROUND TRUTH for MACRO_RULES.md. Every number, expansion, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Some macro rules are COMPILE ERRORS (e.g. a fragment followed by an illegal
//! token, or invoking a macro before its textual definition). Those cannot live
//! in a runnable file — this binary would not build. They are documented in
//! MACRO_RULES.md with the exact compiler message.
//!
//! Run:
//!     just run macro_rules   (== cargo run --bin macro_rules)

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

// ── Section A: the simplest macro — match tokens, substitute, repeat ─────────
//
// `macro_rules!` is `match` over TOKENS, not values. One rule here:
//   matcher    `($($x:expr),* $(,)?)` — zero+ comma-separated expressions,
//                                     plus an optional trailing comma.
//   transcriber the `{ ... }` block — `$($x)*` replays once per matched $x.
// `$(,)?` is the "zero or one" repetition operator (it CANNOT take a separator).

macro_rules! say {
    ($($x:expr),* $(,)?) => {
        {
            let mut printed = 0usize;
            $(
                println!("  say: {}", $x);
                printed += 1;
            )*
            printed
        }
    };
}

// ── Section B: fragment specifiers — what class of syntax a `$name:` binds ────
// `$i:ident` an identifier | `$t:ty` a type | `$e:expr` a full expression.
// Also shown below: `:literal` (one literal), `:tt` (one token tree),
// and `:block` (a brace-delimited block).

macro_rules! typed_let {
    ($i:ident, $t:ty, $e:expr) => {
        let $i: $t = $e;
    };
}

macro_rules! double_lit {
    ($l:literal) => {
        $l + $l
    };
}

macro_rules! first_tt {
    ($first:tt $($_rest:tt)*) => {
        stringify!($first)
    };
}

macro_rules! run_block {
    ($b:block) => {
        $b
    };
}

// ── Section C: repetition in the BODY — the vec!-clone ───────────────────────
// `$($x:expr),*` matches; `$()*` in the body emits the inner code per element.
// This is the Book's simplified `vec!` definition almost verbatim.

macro_rules! mk_vec {
    ($($x:expr),* $(,)?) => {
        {
            // `unused_mut` is allowed at the DEFINITION because the binding must be
            // `mut` for the populated case, but the ZERO-repetition case (mk_vec![])
            // expands to no push at all, so rustc would spuriously flag `mut` here.
            // (clippy::vec_init_then_push is handled at the call site — see section_c.)
            #[allow(unused_mut)]
            let mut v = Vec::new();
            $(
                v.push($x);
            )*
            v
        }
    };
}

// ── Section D: a reducing macro — two arms, the second calls itself ──────────
// `sum!(1, 2, 3)` -> `1 + sum!(2, 3)` -> `1 + (2 + (3 + sum!()))` -> 6.
// This is MACRO RECURSION (textual self-reference), NOT a loop.

macro_rules! sum {
    () => { 0 };
    ($first:expr $(, $rest:expr)* $(,)?) => {
        $first + sum!($($rest,)*)
    };
}

// ── Section E: hygiene — a macro's local `x` is NOT the caller's `x` ─────────
// Macros have MIXED-SITE hygiene: identifiers introduced by a macro carry the
// macro's own "syntax context", so they cannot accidentally capture or shadow a
// same-named local at the call site.

macro_rules! hygienic_x {
    ($v:expr) => {{
        let x = $v; // this `x` is the MACRO's binding, distinct from any caller `x`
        x // resolves to the macro's `x`, never the caller's
    }};
}

// ── Section F: recursion + #[macro_export] — a counting (TT-muncher) macro ────
// `#[macro_export]` lifts the macro to the CRATE ROOT for PATH-BASED resolution,
// so it is callable as `crate::count!(...)`. The second arm peels one token tree
// off the front and recurses — the classic "incremental TT muncher" pattern.

#[macro_export]
macro_rules! count {
    () => { 0usize };
    ($head:tt $(, $tail:tt)* $(,)?) => {
        1usize + count!($($tail,)*)
    };
}

// ── sections ──────────────────────────────────────────────────────────────────

fn section_a() {
    banner("A — the simplest macro: match tokens, substitute, repeat");
    println!("  say!(1, 2):");
    let n = say!(1, 2); // prints two lines; returns the repetition count
    println!("  say!(\"hello\", \"macros\", 3 * 4):");
    let m = say!("hello", "macros", 3 * 4); // `3 * 4` is ONE :expr -> prints 12
    check(
        "say!(1,2) prints 2 lines (the repetition expands twice)",
        n == 2,
    );
    check("say!(\"hello\",\"macros\",3*4) prints 3 lines", m == 3);
}

fn section_b() {
    banner("B — fragment specifiers: ident / ty / expr / literal / tt / block");
    // `$i:ident` + `$t:ty` + `$e:expr` assemble a typed binding.
    typed_let!(answer, i32, 6 * 7);
    println!("  typed_let!(answer, i32, 6 * 7)  -> answer = {answer}");
    check(
        "ident+ty+expr build `let answer: i32 = 6*7;` -> 42",
        answer == 42,
    );

    // `:literal` matches exactly ONE literal token (no expressions allowed).
    let d = double_lit!(21);
    println!("  double_lit!(21)        via :literal -> {d}");
    check(":literal matches a single literal; 21 + 21 = 42", d == 42);

    // `:tt` matches one token tree — the most permissive single matcher.
    let f = first_tt!(hello world 123);
    println!("  first_tt!(hello world 123) via :tt -> {:?}", f);
    check(":tt captures one token tree -> \"hello\"", f == "hello");

    // `:block` matches a brace-delimited block expression.
    let rb = run_block!({
        let z = 5;
        z * z
    });
    println!("  run_block!({{ let z = 5; z * z }}) via :block -> {rb}");
    check(":block matches a braced block; 5 * 5 = 25", rb == 25);
}

fn section_c() {
    banner("C — repetition in the BODY: a vec!-clone");
    // clippy::vec_init_then_push is allowed HERE (at the call site) because the
    // lint fires on the EXPANSION of this teaching macro, whose body is the
    // canonical `let mut v = Vec::new(); v.push(...)` pattern — i.e. the very
    // definition of the std vec! macro (Book Listing 20-35). The point of this
    // section is to show that pattern, not to use `vec!` directly.
    #[allow(clippy::vec_init_then_push)]
    let v = mk_vec![10, 20, 30];
    println!("  mk_vec![10, 20, 30] -> {:?}", v);
    check(
        "mk_vec![$($x:expr),*] expands to the same Vec as the std vec! macro",
        v == vec![10, 20, 30],
    );
    check(
        "the body repetition emitted push() exactly 3 times",
        v.len() == 3,
    );

    // The `*` operator allows ZERO repetitions -> an empty Vec. With no elements
    // the element type is unknowable, so an annotation is required (a real,
    // everyday consequence of a variadic macro that can match zero times).
    let empty: Vec<i32> = mk_vec![];
    println!("  mk_vec![]            -> {:?}", empty);
    check(
        "`*` permits zero repetitions -> empty Vec",
        empty.is_empty(),
    );
}

fn section_d() {
    banner("D — a reducing macro: two arms, the second recurses");
    let s = sum!(1, 2, 3);
    println!("  sum!(1, 2, 3) -> {s}   (expands to 1 + (2 + (3 + 0)))");
    check("sum! folds with `a + sum!(rest...)`; 1 + 2 + 3 = 6", s == 6);

    let one = sum!(42);
    println!("  sum!(42)      -> {one}   (arm 2 with empty rest -> 42 + sum!())");
    check(
        "sum!(42): single-element recursion bottoms out at sum!() = 0",
        one == 42,
    );

    let none = sum!();
    println!("  sum!()        -> {none}   (arm 1, the base case)");
    check("sum!(): the empty base-case arm evaluates to 0", none == 0);
}

fn section_e() {
    banner("E — hygiene: a macro's local `x` does NOT collide with a caller's `x`");
    let x = 999; // the CALLER's `x`
    let from_macro = hygienic_x!(7); // the macro introduces its OWN `x` = 7
    println!("  caller `x` = {x};   hygienic_x!(7) returned = {from_macro}");
    check(
        "hygiene: the caller's `x` is UNTOUCHED by the macro's `let x`",
        x == 999,
    );
    check(
        "hygiene: the macro's `x` is a separate binding with its own value",
        from_macro == 7,
    );
}

fn section_f() {
    banner("F — recursion + #[macro_export]: a counting (TT-muncher) macro");
    let c0 = count!();
    let c1 = count!(7);
    let c3 = count!(1, 2, 3);
    println!("  count!()        = {c0}");
    println!("  count!(7)       = {c1}");
    println!("  count!(1, 2, 3) = {c3}");
    check("recursion base case: count!() peels zero tts -> 0", c0 == 0);
    check(
        "recursion: count!(7) peels one tt off the front -> 1",
        c1 == 1,
    );
    check("recursion: count!(1,2,3) peels three tts -> 3", c3 == 3);

    // #[macro_export] grants PATH-BASED scope at the crate root, so the macro is
    // callable via a `crate::` path (here, from within the same crate).
    let via_path = crate::count!(10, 20, 30, 40);
    println!("  crate::count!(10, 20, 30, 40) = {via_path}   (path-based call)");
    check(
        "#[macro_export] enables path-based resolution crate::count!(...) -> 4",
        via_path == 4,
    );
}

fn main() {
    println!("macro_rules.rs — Phase 6 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
