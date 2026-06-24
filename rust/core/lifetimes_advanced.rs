//! lifetimes_advanced.rs — Phase 3 bundle (core).
//!
//! GOAL (one line): go past the basics — structs that hold references,
//! higher-ranked trait bounds (`for<'a>`), the `'static` lifetime (both as a
//! reference and as a `T: 'static` bound), non-lexical lifetimes (NLL), and
//! variance (covariance / invariance / contravariance).
//!
//! This is the GROUND TRUTH for LIFETIMES_ADVANCED.md. Every value, string, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Some lifetime rules are COMPILE ERRORS (returning a ref to a local;
//! mismatched lifetimes). Those cannot live in a runnable file — this binary
//! would not build. They are documented in LIFETIMES_ADVANCED.md with the exact
//! compiler message (E0515, E0621, E0597).
//!
//! Run:
//!     just run lifetimes_advanced   (== cargo run --bin lifetimes_advanced)

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

// ── Section A: a struct holding a reference — `Parser<'a>` ───────────────────

/// A `Parser` borrows text it does NOT own, so it must carry a lifetime that
/// ties the whole struct to the borrowed data's validity: it cannot outlive the
/// `&'a str` it points at.
struct Parser<'a> {
    text: &'a str,
}

impl<'a> Parser<'a> {
    /// Return the n-th whitespace-separated word. The output is `&'a str` —
    /// tied to the DATA lifetime `'a`, NOT to the borrow of `&self`. So a
    /// returned slice stays valid for as long as the borrowed text, even after
    /// the `Parser` itself is dropped.
    fn word(&self, n: usize) -> Option<&'a str> {
        self.text.split_whitespace().nth(n)
    }
}

fn section_a() {
    banner("A — a struct holding a reference: Parser<'a>");
    println!("struct Parser<'a> {{ text: &'a str }}");
    println!("impl<'a> Parser<'a> {{ fn word(&self, n) -> Option<&'a str> }}");
    let src = String::from("rust lifetimes are not magic");
    {
        let p = Parser { text: &src };
        let w0 = p.word(0);
        let w2 = p.word(2);
        println!("Parser{{text:\"{src}\"}}.word(0) -> {w0:?}");
        println!("                                   .word(2) -> {w2:?}");
        check(
            "Parser::word(0) returns the 1st word, tied to the data lifetime",
            w0 == Some("rust"),
        );
        check("Parser::word(2) returns the 3rd word", w2 == Some("are"));
    } // p dropped here; src still alive and usable
    println!(
        "after the Parser dropped, the source String is still usable (len = {})",
        src.len()
    );
    check(
        "the source outlives the Parser that borrowed it",
        src == "rust lifetimes are not magic",
    );
}

// ── Section B: the 'static lifetime (reference AND bound) ────────────────────

/// `T: 'static` is a BOUND on a type, not a reference. It means "T can survive
/// for the rest of the program" — i.e. it holds no non-`'static` references.
/// That includes every OWNED type (String, i32, Vec, ...) as well as `&'static str`.
fn needs_static<T: 'static>(tag: &str, _val: &T) {
    println!("  needs_static({tag:?}, &..): accepted  (T: 'static satisfied)");
}

fn section_b() {
    banner("B — 'static: a forever reference, AND a `T: 'static` bound");
    // (1) &'static str — the reference form. String literals are baked into the
    // read-only data of the binary, so they exist for the whole program.
    let s: &'static str = "literal";
    println!("let s: &'static str = \"literal\";   (a string literal IS 'static)");
    check("a &'static str literal holds \"literal\"", s == "literal");

    // (2) T: 'static the BOUND. Both an OWNED String and a &'static str satisfy
    // it — the bound asks "can T live forever?", not "is T a static reference?".
    // (`needs_static("short ref", &local)` would NOT compile -> see the .md.)
    println!("fn needs_static<T: 'static>(tag: &str, _val: &T)");
    needs_static("&'static str", &s);
    let owned = String::from("owned");
    needs_static("String (owned)", &owned);
    check(
        "an OWNED String satisfies T: 'static and stays usable",
        owned == "owned",
    );
}

// ── Section C: Higher-Ranked Trait Bounds — `for<'a>` ────────────────────────

/// `apply_any` takes a callback that works for ANY lifetime of its `&str`
/// argument. Written explicitly: `F: for<'a> Fn(&'a str) -> bool`.
/// The sugar `F: Fn(&str) -> bool` desugars to exactly this `for<'a>` bound.
fn apply_any<F>(s: &str, f: F) -> bool
where
    F: for<'a> Fn(&'a str) -> bool,
{
    f(s)
}

/// A plain function, usable wherever a `for<'a> Fn(&'a str) -> bool` is asked.
fn is_short(s: &str) -> bool {
    s.len() < 5
}

/// Uses the *sugar* form `impl Fn(&str) -> bool` to show it accepts the SAME
/// callbacks as the explicit `for<'a>` bound above — they are the same thing.
fn higher_order_any(words: &[&str], f: impl Fn(&str) -> bool) -> bool {
    words.iter().copied().any(f)
}

fn section_c() {
    banner("C — Higher-Ranked Trait Bounds: for<'a>");
    println!("fn apply_any<F>(s: &str, f: F) -> bool  where  F: for<'a> Fn(&'a str) -> bool");
    println!("  (the sugar `F: Fn(&str) -> bool` desugars to that `for<'a>` bound)");

    let with_closure = apply_any("rust forever", |w| w.contains("rust"));
    println!("apply_any(\"rust forever\", |w| w.contains(\"rust\")) -> {with_closure}");
    check("HRTB callback (closure) matches a substring", with_closure);

    let with_fn = apply_any("hi", is_short);
    println!("apply_any(\"hi\", is_short as fn(&str) -> bool) -> {with_fn}");
    check("HRTB callback (plain fn) sees len < 5", with_fn);

    let any_short = higher_order_any(&["hi", "world", "x"], is_short);
    println!("higher_order_any(&[\"hi\",\"world\",\"x\"], is_short) -> {any_short}");
    check(
        "the `Fn(&str)` sugar IS the `for<'a> Fn(&'a str)` HRTB",
        any_short,
    );
}

// ── Section D: Non-Lexical Lifetimes (NLL) ───────────────────────────────────

fn section_d() {
    banner("D — Non-Lexical Lifetimes: a borrow ends at its LAST USE");
    println!("NLL: the borrow of `r` ends at `println!(\"{{r}}\")`, not at the `}}`.");
    let mut x = 1;
    let r = &x; // shared borrow starts
    println!("  let r = &x;            r = {r}      <- last use of the borrow");
    x = 5; // would be a borrow-check error pre-NLL
    println!("  x = 5;   (mutate AFTER the borrow's last use) -> x = {x}");
    check(
        "NLL: mutating x after the shared borrow's last use succeeds",
        x == 5,
    );
}

// ── Section E: Variance — covariance (and the invariance safety net) ─────────

/// `debug_two` requires its two args to share ONE lifetime `'a`. Covariance lets
/// a `&'static str` be silently downgraded to the shorter `'a` of the other arg.
fn debug_two<'a>(a: &'a str, b: &'a str) -> usize {
    println!("  debug_two: a = {a:?}, b = {b:?}");
    a.len() + b.len()
}

fn section_e() {
    banner("E — Variance: a longer lifetime can satisfy a shorter one");
    println!("rule: 'long <: 'short  <=>  'long outlives 'short  (so 'static <: 'b)");

    // (1) Covariant assignment: a &'static str fits into a &str binding.
    let s: &'static str = "hi";
    let r: &str = s; // covariance: &'static str <: &'short str
    println!("let s: &'static str = \"hi\";  let r: &str = s;   // OK via covariance");
    check(
        "covariant assignment: &'static str fits a &str binding",
        r == "hi",
    );

    // (2) Covariance across args: a 'static arg downgrades to match a 'short arg.
    let hello: &'static str = "hello";
    {
        let world = String::from("world");
        println!("debug_two(\"hello\" [&'static], &world [&'short]):");
        let n = debug_two(hello, &world); // hello silently becomes &'short str
        check(
            "covariance lets &'static and &'short share one lifetime param",
            n == 10,
        );
    }
    println!("  -> &'static str was downgraded to &'short; no error, no data lost");
    println!("note: &mut T is INVARIANT — it CANNOT be downgraded this way.");
    println!("      that is what blocks the classic use-after-free (see .md E0597).");
}

// ── Section F: compile errors — documented, and their fixes shown running ─────

/// Fix for E0515: return OWNED data instead of a reference into a dropped local.
/// Contrast with `let x = 0; &x` (E0515): here we RETURN ownership of the local's
/// heap data, so there is nothing left dangling when the frame ends.
fn no_dangle() -> String {
    String::from("ok")
}

/// Fix for E0621: give BOTH inputs (and the output) the same lifetime `'a`.
fn longest<'a>(x: &'a i32, y: &'a i32) -> &'a i32 {
    if x > y { x } else { y }
}

fn section_f() {
    banner("F — compile errors E0515 / E0621 (documented) + their fixes (running)");
    println!("E0515 — returning a reference to a local variable (dangling ref):");
    println!("    fn dangle() -> &'static i32 {{ let x = 0; &x }}   // E0515");
    let recovered = no_dangle();
    println!("    fix: return owned data -> no_dangle() = {recovered:?}");
    check(
        "E0515 fix: return owned data instead of a ref to a local",
        recovered == "ok",
    );

    println!("E0621 — mismatched lifetimes (body returns data the signature omits):");
    println!("    fn foo<'a>(x: &'a i32, y: &i32) -> &'a i32 {{");
    println!("        if x > y {{ x }} else {{ y }}   // y has no lifetime -> E0621");
    println!("    }}");
    let (a, b) = (3, 7);
    let max = longest(&a, &b);
    println!("    fix: give y the same 'a -> longest(&3, &7) = {max}");
    check(
        "E0621 fix: both args share 'a, returns the larger (7)",
        *max == 7,
    );
}

fn main() {
    println!("lifetimes_advanced.rs — Phase 3 bundle (core).");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
