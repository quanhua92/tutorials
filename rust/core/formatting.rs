//! formatting.rs — Phase 5 bundle.
//!
//! GOAL (one line): show, by printing every value, how Rust turns values into
//! text — the `std::fmt` formatting traits (`Display`/`Debug`), the format
//! spec grammar (`{:>5}`, `{:08}`, `{:.2}`, `{:#x}`, ...), the argument forms
//! (positional / named / dynamic width), and the `format!`/`write!` macros.
//!
//! This is the GROUND TRUTH for FORMATTING.md. Every number and worked example
//! in the guide is printed by this file. Change it -> re-run -> re-paste. Never
//! hand-compute.
//!
//! Determinism: every value below is a pure function of its input (no maps, no
//! addresses, no threads), so the output is byte-reproducible across runs.
//!
//! Run:
//!     just run formatting   (== cargo run --bin formatting)

use std::fmt::{self, Write};

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

// ── The shared sample type: ONE struct, BOTH formatting traits ───────────────
//
// `#[derive(Debug)]` generates an impl of the `Debug` trait automatically.
// The hand-written `impl Display` below gives a user-facing form. A type may
// implement BOTH — `{}` picks Display, `{:?}` picks Debug — which is exactly
// how to expose a clean string to users while keeping a verbose one for logs.

/// A 2D point. `Debug` is derived; `Display` is hand-written (impl below).
#[derive(Debug)]
struct Point {
    x: i32,
    y: i32,
}

impl fmt::Display for Point {
    // The trait method signature is FIXED: take &self and a &mut Formatter,
    // return fmt::Result (== Result<(), std::fmt::Error>). `write!` into the
    // Formatter does the actual emitting; the `?` forwards any write error.
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "P({},{})", self.x, self.y)
    }
}

// ── Section A: Display — the user-facing trait ({}), driven by hand-written fmt ─

fn section_a() {
    banner("A — Display: the user-facing trait ({})");
    let p = Point { x: 1, y: 2 };
    // `{}` (an empty format spec) routes to the `Display` trait. No trait is
    // ever derived for Display — you write the impl yourself.
    let shown = format!("{}", p);
    println!("  format!(\"{{}}\", Point {{ x:1, y:2 }}) = {shown:?}");

    check(
        "Display renders the hand-written form exactly",
        shown == "P(1,2)",
    );

    // `to_string()` is sugar for `format!(\"{}\", x)`: it goes through Display.
    // (ToString is auto-implemented for every T: Display.)
    let s = p.to_string();
    println!("  p.to_string() = {s:?}");
    check("to_string() is Display in disguise", s == "P(1,2)");
}

// ── Section B: Debug — the developer-facing trait ({:?}), usually derived ────

fn section_b() {
    banner("B — Debug: the developer-facing trait ({:?}), usually #[derive(Debug)]");
    let p = Point { x: 1, y: 2 };
    // `{:?}` routes to `Debug`. With `#[derive(Debug)]` the compiler emits an
    // impl that prints `StructName { field: value, ... }`.
    let debug = format!("{:?}", p);
    println!("  format!(\"{{:?}}\", p) = {debug:?}");
    check(
        "derived Debug prints StructName { field: value, ... }",
        debug == "Point { x: 1, y: 2 }",
    );

    // `{:#?}` is the "alternate" (#) Debug: multi-line, 4-space indented.
    let pretty = format!("{:#?}", p);
    println!("  format!(\"{{:#?}}\", p) =");
    // indent the multi-line block under the banner for readability
    for line in pretty.lines() {
        println!("    {line}");
    }
    check(
        "{:#?} pretty-prints Debug across multiple indented lines",
        pretty == "Point {\n    x: 1,\n    y: 2,\n}",
    );

    // Same value, two traits -> two representations. Display is for END USERS
    // (a faithful string); Debug is for DEVELOPERS (internal state, always
    // derivable). The Book: Debug "should be implemented for all public types".
    println!("  same Point:  Display = {}   Debug = {:?}", p, p);
}

// ── Section C: width / alignment / fill / sign-aware zero-pad ────────────────

fn section_c() {
    banner("C — width / alignment / fill / sign-aware zero-pad (spec grammar)");
    // spec grammar (Rust Reference / std::fmt):
    //   format_spec := [[fill]align][sign]['#']['0'][width]['.' precision][type]
    //   align := '<' | '^' | '>'

    // Width N: pad to at least N columns. Default fill is a SPACE; default
    // alignment for numbers is RIGHT, for strings LEFT.
    let r = format!("[{:>5}]", 42); // right-align in 5
    let l = format!("[{:<5}]", 42); // left-align in 5
    let c = format!("[{:^5}]", 42); // center in 5
    println!("  \"[{{:>5}}]\" of 42 = {r}");
    println!("  \"[{{:<5}}]\" of 42 = {l}");
    println!("  \"[{{:^5}}]\" of 42 = {c}");
    check(
        "right-align width 5 pads on the LEFT with spaces",
        r == "[   42]",
    );
    check(
        "left-align width 5 pads on the RIGHT with spaces",
        l == "[42   ]",
    );
    check(
        "center width 5 splits padding around the value",
        c == "[ 42  ]",
    );

    // A custom FILL char goes BEFORE the align char: `{:-<5}` fills with '-'.
    let fill = format!("[{:-<5}]", "x");
    let fill0 = format!("[{:0>5}]", "x");
    println!("  \"[{{:-<5}}]\" of \"x\" = {fill}");
    println!("  \"[{{:0>5}}]\" of \"x\" = {fill0}");
    check(
        "fill char precedes align: {:-<5} fills with '-'",
        fill == "[x----]",
    );
    check(
        "fill '0' + right-align: {:0>5} fills with '0'",
        fill0 == "[0000x]",
    );

    // The `0` FLAG (sign-aware zero-pad): `{:08}` pads with 0 to width 8, but
    // is SIGN-AWARE — the sign (and any base prefix) sits BEFORE the zeros, so
    // a negative number gets ONE FEWER zero than its positive twin.
    let zpos = format!("{:08}", 255);
    let zneg = format!("{:08}", -1);
    println!("  \"{{:08}}\" of 255 = {zpos:?}");
    println!("  \"{{:08}}\" of -1  = {zneg:?}");
    check("{:08} zero-pads 255 to width 8", zpos == "00000255");
    check(
        "{:08} is sign-aware: -1 keeps the sign, then 6 zeros (not 7)",
        zneg == "-0000001",
    );

    // The `+` sign flag: always print the sign of numeric values.
    let plus = format!("{:+}", 5);
    println!("  \"{{:+}}\" of 5 = {plus:?}");
    check(
        "{:+} forces a leading '+' on positive numbers",
        plus == "+5",
    );
}

// ── Section D: precision (float digits / string trunc) + radix + scientific ──

fn section_d() {
    banner("D — precision (float digits / string trunc) + radix + scientific");

    // Precision `.N` is OVERLOADED by type:
    //   - floats  -> digits AFTER the decimal point (rounded, half-to-even)
    //   - strings -> MAXIMUM width (truncated to N chars)
    //   - integers-> IGNORED
    // (1.0/3.0 is a computed value, not a literal, so clippy's approx_constant
    // lint stays quiet — a bare 3.14159 literal would trip it as a PI lookalike.)
    let third = format!("{:.2}", 1.0_f64 / 3.0);
    let trunc = format!("{:.3}", "abcdefg");
    println!("  \"{{:.2}}\" of 1.0/3.0  = {third:?}");
    println!("  \"{{:.3}}\" of \"abcdefg\" = {trunc:?}");
    check(
        "{:.2} keeps 2 fractional digits (1.0/3.0 -> 0.33)",
        third == "0.33",
    );
    check("{:.3} truncates the string to 3 chars", trunc == "abc");

    // Rounding is round-HALF-TO-EVEN (the IEEE 754 default), NOT half-up:
    // 0.5 -> 0 (0 is even) and 2.5 -> 2 (2 is even). This surprises people.
    let half_down = format!("{:.0}", 0.5_f64);
    let half_even = format!("{:.0}", 2.5_f64);
    println!("  \"{{:.0}}\" of 0.5 = {half_down:?}   (round half-to-even -> 0)");
    println!("  \"{{:.0}}\" of 2.5 = {half_even:?}   (round half-to-even -> 2)");
    check("round-half-to-even: 0.5 -> 0", half_down == "0");
    check("round-half-to-even: 2.5 -> 2", half_even == "2");

    // Radix via the `type` field -> a formatting TRAIT. `#` adds a base prefix.
    //   x -> LowerHex, X -> UpperHex, o -> Octal, b -> Binary, ? -> Debug, ...
    let hex = format!("{:x}", 255);
    let hex_alt = format!("{:#x}", 255);
    let oct = format!("{:o}", 8);
    let oct_alt = format!("{:#o}", 8);
    let bin = format!("{:b}", 5);
    let bin_alt = format!("{:#b}", 5);
    println!("  \"{{:x}}\"/\"{{:#x}}\" of 255 = {hex:?} / {hex_alt:?}");
    println!("  \"{{:o}}\"/\"{{:#o}}\" of 8   = {oct:?} / {oct_alt:?}");
    println!("  \"{{:b}}\"/\"{{:#b}}\" of 5   = {bin:?} / {bin_alt:?}");
    check("{:x} is lowercase hex with no prefix", hex == "ff");
    check("{:#x} prepends the 0x prefix", hex_alt == "0xff");
    check("{:o} is octal with no prefix", oct == "10");
    check("{:#o} prepends the 0o prefix", oct_alt == "0o10");
    check("{:b} is binary with no prefix", bin == "101");
    check("{:#b} prepends the 0b prefix", bin_alt == "0b101");

    // Scientific notation: `e` -> LowerExp, `E` -> UpperExp (floats only).
    let sci = format!("{:e}", 25500.0_f64);
    let sci_up = format!("{:E}", 25500.0_f64);
    let sci_one = format!("{:e}", 1.0_f64);
    println!("  \"{{:e}}\"/\"{{:E}}\" of 25500.0 = {sci:?} / {sci_up:?}");
    println!("  \"{{:e}}\" of 1.0 = {sci_one:?}");
    check(
        "{:e} is lowercase scientific (mantissa e exponent)",
        sci == "2.55e4",
    );
    check("{:E} is uppercase scientific", sci_up == "2.55E4");
    check("{:e} of 1.0 is 1e0", sci_one == "1e0");
}

// ── Section E: argument forms — positional, explicit-index, named, dynamic ──

fn section_e() {
    banner("E — argument forms: positional / explicit-index / named / dynamic width");

    // Empty `{}` is the "next argument" — an implicit cursor over the args.
    // Explicit `{N}` reuses the Nth arg WITHOUT advancing that cursor.
    let reuse = format!("{0} {0} {1}", "a", "b");
    let mixed = format!("{1} {} {0} {}", 1, 2);
    println!("  \"{{0}} {{0}} {{1}}\", \"a\", \"b\"   = {reuse:?}");
    println!("  \"{{1}} {{}} {{0}} {{}}\", 1, 2 = {mixed:?}");
    check("{0} reuses arg 0 twice -> \"a a b\"", reuse == "a a b");
    check(
        "{1} {} {0} {} mixes explicit-index and next-arg -> \"2 1 1 2\"",
        mixed == "2 1 1 2",
    );

    // Named args come last: `name = value`. A name also works as a dynamic
    // count (width/precision) with a trailing `$`.
    let named = format!("{} {name}", 1, name = 2);
    let dyn_width = format!("[{:>0width$}]", 7, width = 5);
    println!("  \"{{}} {{name}}\", 1, name=2   = {named:?}");
    println!("  \"[{{:>0width$}}]\", 7, width=5 = {dyn_width:?}");
    check(
        "named arg {name} substitutes the named value",
        named == "1 2",
    );
    check(
        "width$ takes width from a (usize) arg -> zero-padded to 5",
        dyn_width == "[00007]",
    );

    // Escaping: `{{` and `}}` emit a literal brace. (No other escaping.) Mixing
    // them with a real arg shows the rule clearly: `{{{}}}` == literal '{' +
    // the arg + literal '}'.
    let esc = format!("{{{}}}", "x");
    println!("  escaping {{ }} around arg \"x\" -> {esc:?}");
    check(
        "{{ and }} escape to literal braces around an argument -> {x}",
        esc == "{x}",
    );
}

// ── Section F: write! / writeln! — emit into a buffer; format_args! is 0-alloc ─

fn section_f() {
    banner("F — write!/writeln! into a String; format_args! is zero-alloc");

    // `write!`/`writeln!` emit into a `fmt::Write` (String, fmt::Formatter) or
    // an `io::Write` (File, Vec<u8>, ...). For a String the `fmt::Write` trait
    // must be in scope (`use std::fmt::Write;`) or the call won't resolve.
    // They return fmt::Result; `fmt::Write for String` is INFALLIBLE, so an
    // .expect(...) here can never actually panic.
    let mut buf = String::new();
    write!(buf, "x={}", 42).expect("fmt::Write for String is infallible");
    println!("  after write!(buf, \"x={{}}\", 42) -> buf = {buf:?}");
    check("write! appends formatted text to the String", buf == "x=42");

    writeln!(buf, "!").expect("fmt::Write for String is infallible");
    println!("  after writeln!(buf, \"!\")         -> buf = {buf:?}");
    check(
        "writeln! appends the text AND a trailing newline",
        buf == "x=42!\n",
    );

    // fmt::Result is literally the type alias `Result<(), std::fmt::Error>`.
    // Formatting itself is infallible; the Result only exists so a Formatter
    // can surface a write failure from the underlying sink. `format!` (which
    // writes to a String) therefore PANICS if it ever sees an Err (it never
    // will). Proof it is just that alias: its type_name EQUALS the expansion.
    let _: fmt::Result = write!(buf, "ok");
    let alias = std::any::type_name::<fmt::Result>();
    let expanded = std::any::type_name::<Result<(), fmt::Error>>();
    println!("  type_name::<fmt::Result>()           = {alias}");
    println!("  type_name::<Result<(),fmt::Error>>() = {expanded}");
    check(
        "fmt::Result IS Result<(), std::fmt::Error>: identical type_name",
        alias == expanded,
    );

    // `format_args!` builds a `fmt::Arguments` with NO heap allocation — it only
    // borrows the format string + args on the stack. Every macro above is built
    // on it; you can pass it along (e.g. to a logger) and write it later.
    let args = format_args!("{}={}", "k", 1);
    let mut sink = String::new();
    // fmt::Arguments: Display (not Debug-driven), so `{}` works.
    sink.write_fmt(args).expect("String write is infallible");
    println!("  format_args!(\"k={{}}\", 1) -> written = {sink:?}");
    check(
        "format_args! carries the precompiled format, written later",
        sink == "k=1",
    );
}

fn main() {
    println!("formatting.rs — Phase 5 bundle.");
    println!("Every value below is computed by this file (pure std::fmt).\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
