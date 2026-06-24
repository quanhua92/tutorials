//! lifetimes.rs — Phase 1 bundle #3.
//!
//! GOAL (one line): show, by printing every value, how every reference carries
//! a LIFETIME — the code region it is valid for — and how Rust's borrow checker
//! uses lifetimes (and the three elision rules) to guarantee references never
//! dangle.
//!
//! This is the GROUND TRUTH for LIFETIMES.md. Every number, string, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Run:
//!     just run lifetimes   (== cargo run --bin lifetimes)

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

/// Elided: the compiler fills in `<'a>(s: &'a [i32]) -> &'a i32` via elision
/// rule 1 (each input ref gets its own lifetime) then rule 2 (exactly one input
/// lifetime -> assigned to the single output lifetime).
fn first(slice: &[i32]) -> &i32 {
    &slice[0]
}

/// Explicit: both inputs and the output share lifetime `'a`, so the returned
/// reference is valid for the SHORTER of the two input lifetimes.
fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    if x.len() > y.len() { x } else { y }
}

/// A struct holding a reference needs its own lifetime parameter: an
/// `Excerpt<'a>` cannot outlive the data its `part` field borrows.
struct Excerpt<'a> {
    part: &'a str,
}

/// Accepting `&'static str` enforces, at the call site, that the argument lives
/// for the entire program.
fn takes_static(_: &'static str) {}

fn section_a() {
    banner("A — Lifetime elision in action");
    println!("Written signature (no annotations):  fn first(slice: &[i32]) -> &i32");
    println!("Desugared by elision rules 1 + 2:     fn first<'a>(slice: &'a [i32]) -> &'a i32");
    let data = [1, 2, 3];
    let head = first(&data);
    println!("first(&[1, 2, 3]) -> {head}  (returns a reference to the 1st element)");
    check("first(&[1,2,3]) dereferences to 1", *head == 1);
}

fn section_b() {
    banner("B — Explicit lifetime annotation");
    println!("fn longest<'a>(x: &'a str, y: &'a str) -> &'a str");
    let longer = longest("abc", "wxyz");
    println!("longest(\"abc\", \"wxyz\") -> \"{longer}\"");
    check(
        "longest(\"abc\", \"wxyz\") returns \"wxyz\"",
        longer == "wxyz",
    );
    let tie = longest("ab", "cd");
    println!("longest(\"ab\", \"cd\")   -> \"{tie}\"  (equal length -> returns y)");
    check(
        "equal-length tie returns the second argument (y)",
        tie == "cd",
    );
}

fn section_c() {
    banner("C — The 'static lifetime");
    let literal: &'static str = "literal";
    takes_static("literal");
    println!("let literal: &'static str = \"literal\";   (annotation accepted => it is 'static)");
    println!(
        "std::any::type_name::<&str>() = {:?}",
        std::any::type_name::<&str>()
    );
    println!("string literals are baked into the binary, so they live for the whole program");
    check("string literal value == \"literal\"", literal == "literal");
    check(
        "std::any::type_name::<&str>() == \"&str\" (lifetimes are omitted in the name)",
        std::any::type_name::<&str>() == "&str",
    );
}

fn section_d() {
    banner("D — Struct holding a reference");
    println!("struct Excerpt<'a> {{ part: &'a str }}");
    let ex = Excerpt { part: "hi" };
    println!("Excerpt {{ part: \"hi\" }}.part -> {:?}", ex.part);
    check("Excerpt holding \"hi\" reads \"hi\"", ex.part == "hi");
}

fn section_e() {
    banner("E — Non-lexical lifetimes (NLL)");
    println!("NLL: a borrow ends at its LAST USE, not the end of the lexical scope.");
    let mut v = vec![1, 2, 3];
    let first = &v[0];
    println!("borrowed &v[0] = {first}          <- last use of the borrow");
    let grown = v.len() as i32 + 1;
    v.push(grown);
    println!(
        "v.push(4) after the borrow compiles & runs -> v.len() = {}",
        v.len()
    );
    check(
        "NLL lets the &mut push run after the shared borrow's last use",
        v.len() == 4,
    );
}

fn main() {
    println!("lifetimes.rs — Phase 1 bundle #3.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    banner("DONE — all sections printed");
}
