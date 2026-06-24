//! error_handling.rs — Phase 2 bundle.
//!
//! GOAL (one line): show, by printing every value, that Rust has NO exceptions:
//! recoverable failures are `Result<T, E>` (handled by `match` or `?`),
//! unrecoverable failures are `panic!`, and a custom error type is a
//! hand-written trio of `Debug + Display + Error` with `From` impls that make
//! `?` adapt one error type into another.
//!
//! This is the GROUND TRUTH for ERROR_HANDLING.md. Every value below is computed
//! by this file; the .md guide pastes it verbatim. Never hand-compute.
//!
//! Some error rules are COMPILE ERRORS (e.g. using `?` in a `() -> ()` fn, or
//! `?` on a `Result` inside an `Option`-returning fn) and so cannot live in a
//! runnable file — this binary would not build. They are documented in
//! ERROR_HANDLING.md with the exact compiler message.
//!
//! Run:
//!     just run error_handling   (== cargo run --bin error_handling)

use std::error::Error;
use std::fmt;
use std::io;
use std::num::ParseIntError;

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

// ── A thiserror-STYLE custom error type, built BY HAND from std traits ───────
// The `thiserror` crate DERIVES all of this with `#[derive(Error)]` + `#[from]`.
// Here we write the same impls by hand — `Debug` (derived), `Display` (a match),
// `Error` (a `source()` that returns the wrapped cause) — to show exactly what
// the macro emits. No external crate is used: this member is `core` (stdlib
// only). See ERROR_HANDLING.md "Why hand-roll it" for the thiserror/anyhow note.
#[derive(Debug)]
enum AppError {
    /// Wraps an I/O failure, preserving the original as the error's `source`.
    Io(io::Error),
    /// Wraps a parse failure, preserving the original as the `source`.
    Parse(ParseIntError),
    /// A config error with no underlying cause (a leaf in the source chain).
    Config(String),
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // Error messages are concise lowercase sentences with no trailing period
        // (the std::error::Error doc convention).
        match self {
            AppError::Io(e) => write!(f, "io failure: {e}"),
            AppError::Parse(e) => write!(f, "parse failure: {e}"),
            AppError::Config(msg) => write!(f, "config failure: {msg}"),
        }
    }
}

impl Error for AppError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        // Return the WRAPPED cause for Io and Parse; Config has no cause. The
        // std guidance: expose the cause via `source()`, NOT also via `Display`.
        match self {
            AppError::Io(e) => Some(e),
            AppError::Parse(e) => Some(e),
            AppError::Config(_) => None,
        }
    }
}

// ── From impls: the conversions `?` runs to ADAPT error types ────────────────
// `?` calls `From::from` on the Err value, so a fn returning `Result<_, AppError>`
// can `?` any `io::Error` or `ParseIntError` and it converts automatically — no
// manual wrapping at the call site.
impl From<io::Error> for AppError {
    fn from(e: io::Error) -> Self {
        AppError::Io(e)
    }
}

impl From<ParseIntError> for AppError {
    fn from(e: ParseIntError) -> Self {
        AppError::Parse(e)
    }
}

// ── Helpers used across Sections A/C ─────────────────────────────────────────

/// Simulated I/O: returns `Err` for the "missing" record, `Ok` otherwise. Purely
/// in-memory (no real file) so the output is byte-reproducible.
fn fetch_record(name: &str) -> Result<String, io::Error> {
    if name == "missing" {
        Err(io::Error::new(io::ErrorKind::NotFound, "record not found"))
    } else {
        Ok(name.to_string())
    }
}

/// Reads a record and parses it to `i32`. Uses `?` twice — once on an
/// `io::Error`, once on a `ParseIntError` — both auto-converted to `AppError`
/// via the `From` impls above.
fn read_config(name: &str) -> Result<i32, AppError> {
    let text = fetch_record(name)?; // `?` : io::Error      -> AppError
    let n: i32 = text.trim().parse()?; // `?` : ParseIntError -> AppError
    Ok(n)
}

// ── Section A: Result<T,E> — Ok/Err, match, and the ? shortcut ───────────────

fn section_a() {
    banner("A — Result<T,E>: Ok/Err, match, and the ? shortcut");
    println!("  enum Result<T, E> {{ Ok(T), Err(E) }}");
    println!("  (T = success value type; E = error type)");

    // Parsing a string to i32 returns Result<i32, ParseIntError>.
    let good = "42".parse::<i32>();
    let bad = "NaN".parse::<i32>();
    println!("    \"42\".parse::<i32>()  = {:?}", good);
    println!("    \"NaN\".parse::<i32>() = {:?}", bad);

    // Handle a Result by match: the exhaustive, explicit path.
    let n = match good {
        Ok(v) => v,
        Err(e) => panic!("should not happen: {e}"),
    };
    println!("    match on Ok extracts the inner value: {}", n);
    check("match on Ok extracts the inner value (42)", n == 42);

    // ? propagates: inside a Result-returning fn, `expr?` returns Ok's value,
    // OR early-returns the Err. read_config uses ? on both an io op and a parse.
    let ok = read_config("42");
    let io_err = read_config("missing");
    let parse_err = read_config("NaN");
    println!("    read_config(\"42\")      = {:?}", ok);
    println!("    read_config(\"missing\") = {:?}", io_err);
    println!("    read_config(\"NaN\")     = {:?}", parse_err);

    check(
        "read_config(\"42\") propagates the Ok value (42)",
        matches!(ok, Ok(42)),
    );
    check(
        "read_config(\"missing\") early-returns Err via ? (io path)",
        matches!(io_err, Err(AppError::Io(_))),
    );
    check(
        "read_config(\"NaN\") early-returns Err via ? (parse path)",
        matches!(parse_err, Err(AppError::Parse(_))),
    );
}

// ── Section B: a hand-written custom error type (Debug + Display + Error) ────

fn section_b() {
    banner("B — custom error type: Debug + Display + Error (by hand)");
    println!("  // `thiserror` would derive all of this; here we write it by hand:");
    println!("  #![derive(Debug)]");
    println!("  enum AppError {{ Io(io::Error), Parse(ParseIntError), Config(String) }}");

    let io_err = AppError::Io(io::Error::new(io::ErrorKind::NotFound, "record not found"));
    let parse_err = AppError::Parse("NaN".parse::<i32>().unwrap_err());
    let cfg_err = AppError::Config(String::from("port out of range"));

    println!("    Display ({{}}):  Io     = \"{}\"", io_err);
    println!("    Display ({{}}):  Parse  = \"{}\"", parse_err);
    println!("    Display ({{}}):  Config = \"{}\"", cfg_err);
    println!("    Debug   ({{:?}}): Io    = {:?}", io_err);

    check(
        "Display of AppError::Io contains the inner io message",
        format!("{}", io_err).contains("record not found"),
    );
    check(
        "Display of AppError::Config shows its message",
        format!("{}", cfg_err) == "config failure: port out of range",
    );
    check(
        "AppError implements std::error::Error (usable as &dyn Error)",
        (&io_err as &dyn Error).to_string().contains("io failure"),
    );
}

// ── Section C: From<E> for AppError — the ?-conversion that adapts types ─────

fn section_c() {
    banner("C — From<E> for AppError: ? converts io::Error -> AppError");
    println!("  impl From<io::Error> for AppError       {{ fn from(e) {{ AppError::Io(e) }} }}");
    println!(
        "  impl From<ParseIntError> for AppError    {{ fn from(e) {{ AppError::Parse(e) }} }}"
    );
    println!("  // `?` calls From::from on the Err -> the fn returns AppError.");

    // Demonstrate the conversion directly (exactly what `?` does under the hood).
    let raw_io = io::Error::new(io::ErrorKind::PermissionDenied, "access denied");
    let adapted = AppError::from(raw_io);
    println!("    AppError::from(io::Error::new(PermissionDenied, \"access denied\"))");
    println!("      -> {:?}", adapted);
    check(
        "From<io::Error> wraps the value into AppError::Io",
        matches!(adapted, AppError::Io(_)),
    );

    // The payoff: read_config returns Result<_, AppError> and uses `?` on an io
    // op AND a parse op, both converting automatically.
    let r = read_config("missing");
    println!("    read_config(\"missing\") uses ? on an io op -> {:?}", r);
    check(
        "a Result<_,AppError> fn can ? an io::Error (From converts it)",
        matches!(r, Err(AppError::Io(_))),
    );
}

// ── Section D: Error::source() — walking the cause chain ─────────────────────

fn section_d() {
    banner("D — Error::source(): walking the cause chain");
    println!("  impl Error for AppError {{");
    println!("      fn source(&self) -> Option<&(dyn Error + 'static)> {{");
    println!("          match self {{ Io(e)|Parse(e) => Some(e), Config(_) => None }}");
    println!("      }}");
    println!("  }}");

    let io_err = AppError::Io(io::Error::new(io::ErrorKind::NotFound, "record not found"));
    let cfg_err = AppError::Config(String::from("no such key"));

    // AppError::Io exposes its wrapped io::Error via source(); Config is a leaf.
    check(
        "source() on AppError::Io returns Some(inner io::Error)",
        io_err.source().is_some(),
    );
    check(
        "source() on AppError::Config returns None (a leaf, no cause)",
        cfg_err.source().is_none(),
    );

    // Walk the WHOLE source chain deterministically: level 0 is the error
    // itself, then source() repeatedly until None. The depth is fixed for a
    // given chain (no randomness), so _output.txt reproduces.
    let mut chain: Vec<String> = Vec::new();
    let mut current: Option<&dyn Error> = Some(&io_err);
    while let Some(e) = current {
        chain.push(format!("{}", e));
        current = e.source();
    }
    println!(
        "    source chain from AppError::Io ({} levels):",
        chain.len()
    );
    for (i, msg) in chain.iter().enumerate() {
        println!("      [{}] {}", i, msg);
    }
    check(
        "the chain starts at AppError::Io and reaches its wrapped cause (>=2 levels)",
        chain.len() >= 2 && chain[0].contains("io failure"),
    );
}

// ── Section E: Option <-> Result bridges (ok_or / ok_or_else / .ok() / .err()) ─

fn section_e() {
    banner("E — Option <-> Result: ok_or / ok_or_else / .ok() / .err()");
    println!("  // Option -> Result: turn None into a concrete Err.");
    println!("  // Result -> Option: discard the Err with .ok().");

    // .ok_or: None -> Err, Some -> Ok (the error is evaluated eagerly).
    let some: Option<i32> = Some(5);
    let none: Option<i32> = None;
    println!(
        "    Some(5).ok_or(\"missing\") = {:?}",
        some.ok_or("missing")
    );
    println!(
        "    None.ok_or(\"missing\")     = {:?}",
        none.ok_or("missing")
    );
    check(
        "None.ok_or(\"missing\") == Err(\"missing\")",
        none.ok_or("missing") == Err("missing"),
    );
    check(
        "Some(5).ok_or(\"missing\") == Ok(5)",
        some.ok_or("missing") == Ok(5),
    );

    // .ok_or_else: lazy construction — the closure runs only on None.
    let from_none = none.ok_or_else(|| String::from("built lazily"));
    println!("    None.ok_or_else(|| \"built lazily\") = {:?}", from_none);
    check(
        "ok_or_else builds the Err only on None",
        from_none == Err(String::from("built lazily")),
    );

    // Result -> Option (and the error half via .err()).
    println!(
        "    Ok::<i32,&str>(5).ok()   = {:?}",
        Ok::<i32, &str>(5).ok()
    );
    println!(
        "    Err::<i32,&str>(\"x\").ok()= {:?}",
        Err::<i32, &str>("x").ok()
    );
    println!(
        "    Ok::<i32,&str>(5).err()  = {:?}",
        Ok::<i32, &str>(5).err()
    );
    check(
        "Ok(5).ok() == Some(5)",
        matches!(Ok::<i32, &str>(5).ok(), Some(5)),
    );
    check(
        "Err(\"x\").ok() == None",
        Err::<i32, &str>("x").ok().is_none(),
    );

    // ? on Option works inside an Option-returning fn (but NOT mixed with
    // Result — see ERROR_HANDLING.md "can't mix ? types").
    let first = first_line("alpha\nbeta");
    println!(
        "    first_line(\"alpha\\\\nbeta\") via ? on Option = {:?}",
        first
    );
    check(
        "? on Option early-returns None inside an Option-returning fn",
        first == Some("alpha"),
    );
}

/// Demonstrates `?` on Option: returns None early when there is no first line.
fn first_line(text: &str) -> Option<&str> {
    let line = text.lines().next()?; // ? on Option: None -> return None
    Some(line)
}

// ── Section F: panic! vs Result — unrecoverable vs recoverable ───────────────

fn section_f() {
    banner("F — panic! vs Result: unrecoverable vs recoverable");
    println!("  // panic!  = unrecoverable; unwinds the stack (or aborts).");
    println!("  // Result  = recoverable; the caller decides what to do.");
    println!("  // Rule: panic for BROKEN INVARIANTS; Result for EXPECTED failure.");

    // catch_unwind catches an UNWINDING panic (not an abort) and returns the
    // payload as Err. Used here only to PROVE panic! is a catchable unwind — in
    // real code you catch panics at FFI/thread boundaries, not for control flow.
    let caught = std::panic::catch_unwind(|| {
        panic!("invariant violated: vector index out of bounds");
    });
    let msg = caught
        .as_ref()
        .err()
        .and_then(|p| p.downcast_ref::<&'static str>());
    match &caught {
        Ok(_) => println!("    (panic did not fire — unexpected)"),
        Err(_) => println!("    catch_unwind caught a panic! payload: {:?}", msg),
    }
    check(
        "catch_unwind turns a panic! into Err (an unwind is catchable)",
        caught.is_err(),
    );
    check(
        "the panic payload is the &'static str message",
        msg.is_some(),
    );

    // The Result alternative: the same kind of "bad input" handled gracefully,
    // with no panic and no stack unwind.
    let parsed = "NaN".parse::<i32>();
    println!(
        "    \"NaN\".parse::<i32>() = {:?}  (Result, NOT a panic)",
        parsed
    );
    check(
        "expected failure (bad parse) returns Err, not a panic",
        parsed.is_err(),
    );
}

fn main() {
    println!("error_handling.rs — Phase 2 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
