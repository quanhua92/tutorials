//! testing.rs — Phase 8 bundle (TESTING).
//!
//! GOAL (one line): show, by RUNNING table-driven cases, a panic-expecting
//! case via `std::panic::catch_unwind`, and a `Result<T, E>` case from `main`,
//! how Rust's built-in test framework (`#[test]`, `assert_eq!`,
//! `#[should_panic]`, `cargo test`) actually works.
//!
//! This is the GROUND TRUTH for TESTING.md. Every case outcome below is
//! computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//!
//! META NOTE: this bundle TEACHES `cargo test` but RUNS via
//! `cargo run --bin testing` — a `[[bin]]` cannot itself be a test suite in a
//! workspace of many `main` programs. So instead of `#[test]` the body drives
//! the SAME logic from `main` through the house `check()` idiom:
//!   - test logic   -> plain functions + a table-driven loop, each row checked;
//!   - should_panic -> reproduced with `std::panic::catch_unwind` (catch the
//!     panic, assert `is_err()`, then inspect the payload message);
//!   - Result<T,E>  -> a function returning `Result`, assert Ok / Err.
//!
//! The canonical `#[test] fn foo()` signature and every `cargo test` invocation
//! live in TESTING.md (clearly labeled, NOT under a .rs callout). A REAL
//! `#[cfg(test)] mod tests` block is included at the BOTTOM of this file: run
//! it with `cargo test --bin testing` to see the genuine harness in action.
//!
//! Run:
//!     just run testing   (== cargo run --bin testing)

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

// ── Code under test (pure logic, extracted so it is testable) ───────────────
// Each mirrors a Rust Book ch11 example. These are the functions a real
// `#[test]` suite would exercise; here the runner in `main` checks them too.

/// Adds two to its argument — the Book's `add_two` (ch11.1 / ch11.2).
fn add_two(a: u64) -> u64 {
    a + 2
}

/// A newtype that PANICS on out-of-range input — the Book's `Guess` (ch9/ch11).
/// This is the code under test for the `#[should_panic]` / catch_unwind demo in
/// section C. `Debug` is derived so the test harness can print it.
#[derive(Debug)]
struct Guess {
    value: i32,
}

impl Guess {
    fn new(value: i32) -> Guess {
        // Equivalent to the Book's `value < 1 || value > 100`; the idiomatic
        // clippy-clean form is an inclusive-range containment check.
        if !(1..=100).contains(&value) {
            panic!("Guess value must be between 1 and 100, got {value}.");
        }
        Guess { value }
    }

    fn value(&self) -> i32 {
        self.value
    }
}

/// Parses a hexadecimal string into a `u64` — a `Result`-returning function,
/// the code under test for the `Result<T, E>` test demonstration in section D.
fn parse_hex(s: &str) -> Result<u64, ParseIntError> {
    u64::from_str_radix(s, 16)
}

/// Doubles a hex value, propagating parse errors with `?` — the shape of a
/// `Result<(), E>` test-fn body that uses `?` to fail the test on any `Err`.
fn double_hex(s: &str) -> Result<u64, ParseIntError> {
    let n = parse_hex(s)?;
    Ok(n * 2)
}

// ── Section A: table-driven test — a slice of (input, want) + a loop ────────

fn section_a() {
    banner("A — Table-driven test: a slice of (input, want) + a loop");

    println!("A table-driven test stores cases as DATA: a `&[(input, want)]` slice");
    println!("ranged in a loop, each row checked with the SAME assert. Adding a case");
    println!("means adding a ROW, not copy-pasting a whole test function.");
    println!();
    println!("    pub fn add_two(a: u64) -> u64 {{ a + 2 }}");
    println!();

    // The table: each row is (input, expected output). `want` is the oracle.
    let cases: &[(u64, u64)] = &[
        (0, 2),
        (2, 4), // the Book's `it_adds_two` case
        (40, 42),
        (100, 102),               // matches the Book ch11.2 `one_hundred` case
        (u64::MAX - 2, u64::MAX), // boundary: (MAX-2)+2 = MAX, no overflow
    ];

    println!("{:>22} {:>24}", "input", "want");
    println!("{}", "─".repeat(48));
    let mut all_passed = true;
    for &(input, want) in cases {
        let got = add_two(input);
        if got != want {
            all_passed = false;
        }
        println!("{:>22} {:>24}   got = {}", input, want, got);
    }
    println!();
    for &(input, want) in cases {
        check(
            &format!("table row: add_two({input}) == {want}"),
            add_two(input) == want,
        );
    }
    check(
        "ALL table-driven rows passed (the runner's summary assertion)",
        all_passed,
    );
}

// ── Section B: the assertion macros — assert! / assert_eq! / assert_ne! ─────

/// A small struct that derives `PartialEq` + `Debug` so the equality macros can
/// compare AND print it on failure (both traits are required by assert_eq!).
#[derive(PartialEq, Debug)]
struct Point {
    x: i32,
    y: i32,
}

fn section_b() {
    banner("B — The assertion macros: assert! / assert_eq! / assert_ne!");

    println!("Three macros back every test. All PANIC on failure (the test thread");
    println!("dies -> the harness marks the test FAILED). `assert_eq!` and");
    println!("`assert_ne!` require `PartialEq` + `Debug`; on failure they print the");
    println!("two values. Rust names them 'left'/'right' (NOT 'expected'/'actual').");
    println!();

    // assert!(cond) — panics if cond is false. The underlying check is a bool.
    let bool_ok = true;
    assert!(bool_ok);
    println!("    assert!(true);                       // passes: nothing happens");
    check(
        "assert!(cond) backs every test; underlying check is a bool",
        bool_ok,
    );

    // assert_eq!(left, right) — uses == ; needs PartialEq + Debug.
    let got = add_two(2);
    assert_eq!(got, 4);
    assert_eq!(4, got); // order does NOT matter (left/right, not expected/actual)
    println!("    assert_eq!(add_two(2), 4);            // passes: 4 == 4");
    check(
        "assert_eq! uses == (order-independent): add_two(2) == 4",
        got == 4,
    );

    // assert_ne!(left, right) — uses != ; passes when the two differ.
    assert_ne!(add_two(0), 99);
    println!("    assert_ne!(add_two(0), 99);           // passes: 2 != 99");
    check("assert_ne! uses != : add_two(0) != 99", add_two(0) != 99);

    // PartialEq + Debug are REQUIRED for custom types — derive them.
    let p1 = Point { x: 1, y: 2 };
    let p2 = Point { x: 1, y: 2 };
    assert_eq!(p1, p2); // compiles only because Point: PartialEq + Debug
    println!("    assert_eq!(Point{{1,2}}, Point{{1,2}}); // needs #[derive(PartialEq, Debug)]");
    check(
        "custom types need #[derive(PartialEq, Debug)] for the equality macros",
        p1 == p2,
    );

    // Custom failure message: extra format args after the required ones.
    let val = 42;
    assert!(val > 0, "val must be positive, got {val}");
    println!("    assert!(val > 0, \"val must be positive, got {{val}}\");  // custom message");
    check(
        "custom messages take format args after the required ones",
        val > 0,
    );
}

// ── Section C: #[should_panic] analog — catch_unwind catches a panic ────────

fn section_c() {
    banner("C — #[should_panic] analog: catch_unwind catches a panic");

    println!("`#[should_panic]` makes a test PASS only if it panics. A `[[bin]]`");
    println!("cannot show that attribute directly (its body is `main`), so the");
    println!("runner uses `std::panic::catch_unwind` — the PROGRAMMATIC analog: it");
    println!("runs a closure and returns Ok(result) or Err(panic payload).");
    println!();

    // Suppress the panic's stderr message while we catch it, so the captured
    // stdout stays clean; restore the original hook afterwards. (The payload is
    // a `String` here because the panic! uses a format string.)
    let default_hook = std::panic::take_hook();
    std::panic::set_hook(Box::new(|_| {}));

    // (1) Valid input -> NO panic -> catch_unwind returns Ok(Guess).
    let ok_result = std::panic::catch_unwind(|| Guess::new(50));
    println!("    catch_unwind(|| Guess::new(50))  -> Ok (no panic)");
    check("valid Guess: catch_unwind returns Ok", ok_result.is_ok());
    // `thread::Result`'s Err is `Box<dyn Any>` (not PartialEq), so read the Ok
    // value via `.ok()` and compare an `Option<i32>` to `Some(50)`.
    check(
        "valid Guess: the Ok value is the built Guess (value 50)",
        ok_result.ok().map(|g| g.value()) == Some(50),
    );

    // (2) Invalid input -> PANIC -> catch_unwind returns Err(payload).
    let err_result = std::panic::catch_unwind(|| Guess::new(200));
    println!("    catch_unwind(|| Guess::new(200)) -> Err (panic caught)");
    check(
        "invalid Guess: catch_unwind returns Err (panic caught)",
        err_result.is_err(),
    );

    // (3) The #[should_panic(expected = "...")] analog: inspect the payload
    // message and assert it contains the expected substring.
    let payload = err_result.unwrap_err();
    let msg: String = if let Some(s) = payload.downcast_ref::<String>() {
        s.clone()
    } else if let Some(s) = payload.downcast_ref::<&'static str>() {
        s.to_string()
    } else {
        String::new()
    };
    println!("    panic payload message: {msg:?}");
    check(
        "panic payload contains the expected substring (the expected= analog)",
        msg.contains("between 1 and 100"),
    );

    // (4) AssertUnwindSafe: capturing &mut across an unwind boundary needs it
    // (the UnwindSafe bound encodes exception safety). A mutation made BEFORE
    // the panic is still observable afterwards.
    let mut count = 0_i32;
    let mutating = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        count += 1; // happens before the panic
        Guess::new(200) // panics here
    }));
    println!(
        "    AssertUnwindSafe: count after caught panic = {count} (mutation before panic persists)"
    );
    check(
        "AssertUnwindSafe wraps a closure capturing &mut",
        mutating.is_err(),
    );
    check(
        "a mutation made before the panic is observable after catch_unwind",
        count == 1,
    );

    std::panic::set_hook(default_hook); // restore the original panic hook
}

// ── Section D: Result<T,E> tests — Ok value + Err propagation ───────────────

fn section_d() {
    banner("D — Result<T,E> tests: Ok value + Err propagation");

    println!("A test fn may RETURN `Result<(), E>` instead of panicking. Then `?`");
    println!("propagates any `Err` as a test failure. To assert an `Err`, use");
    println!("`assert!(r.is_err())` — you CANNOT combine `#[should_panic]` with a");
    println!("`Result`-returning test. (Rust Book ch11.1.)");
    println!();

    let ok = parse_hex("ff");
    println!("    parse_hex(\"ff\")  -> {:?}", ok);
    check(
        "Result Ok case: parse_hex(\"ff\") == Ok(255)",
        ok == Ok(255_u64),
    );

    let err = parse_hex("nope");
    println!("    parse_hex(\"nope\") -> Err (propagated ParseIntError)");
    check("Result Err case: parse_hex(\"nope\") is Err", err.is_err());

    // `?` propagation analog: double_hex uses `?`, so an Err short-circuits.
    let doubled = double_hex("ff");
    println!(
        "    double_hex(\"ff\")  -> {:?}   (parse_hex then *2, via `?`)",
        doubled
    );
    check(
        "`?` propagation: double_hex(\"ff\") == Ok(510)",
        doubled == Ok(510_u64),
    );

    let propagated = double_hex("zz");
    println!("    double_hex(\"zz\")  -> Err (the parse Err propagated by `?`)");
    check(
        "`?` propagation: double_hex(\"zz\") is Err (parse error short-circuited)",
        propagated.is_err(),
    );
}

// ── Section E: test organization — unit / integration / doc-tests ───────────

fn section_e() {
    banner("E — Test organization: unit (mod tests) / integration (tests/) / doc-tests");

    println!("Rust has THREE kinds of tests, discovered differently by `cargo test`:");
    println!();
    println!("    KIND          WHERE                         cfg(test)?  NOTES");
    println!("    ────────────────────────────────────────────────────────────────────");
    println!(
        "    unit          src/*.rs #[cfg(test)] mod tests   yes     `use super::*;`, lives next to code"
    );
    println!(
        "    integration   tests/*.rs (each file = 1 bin)    no      `use my_crate::...`, tests the public API"
    );
    println!(
        "    doc-tests     /// code blocks in rustdoc        n/a     compiled & run; no_run/ignore/should_panic"
    );
    println!();
    println!("A REAL #[cfg(test)] mod tests block lives at the BOTTOM of this file.");
    println!("Run it with `cargo test --bin testing` to see the genuine harness.");
    println!();

    // The unit-test module is compiled ONLY under cfg(test) — so it never
    // bloats a release build. Under `cargo run`/`cargo build`, cfg!(test) is
    // false and the module is dropped entirely. (Book ch11.3.)
    let cfg_test_on = cfg!(test);
    println!("    cfg!(test) under `cargo run` = {cfg_test_on}  (mod tests is compiled OUT here)");
    check(
        "unit-test #[cfg(test)] mod tests is excluded from `cargo run` builds",
        !cfg_test_on,
    );

    check(
        "unit tests live in #[cfg(test)] mod tests { use super::*; ... }",
        true,
    );
    check(
        "integration tests live in tests/ and do NOT need #[cfg(test)]",
        true,
    );
    check(
        "doc-tests come from /// rustdoc code blocks, run by `cargo test`",
        true,
    );
}

fn main() {
    println!("testing.rs — Phase 8 bundle (TESTING).");
    println!("Rust's built-in test framework (#[test] / assert_eq! / #[should_panic]),");
    println!("driven from main: table-driven cases, a catch_unwind panic check, and a");
    println!("Result<T,E> case. Nothing is hand-computed.");
    println!("NOTE: this is a META bundle — it teaches `cargo test` but runs via");
    println!("`cargo run --bin testing`. The canonical #[test] signatures and the");
    println!("`cargo test` invocations live in TESTING.md. A real #[cfg(test)] mod");
    println!("tests at the bottom of this file runs under `cargo test --bin testing`.");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    banner("DONE — all sections printed");
}

// ── A REAL test suite: compiled & run ONLY by `cargo test`. ─────────────────
// This block exercises the SAME functions as the runner above, in the canonical
// shape the Book teaches. `cargo run --bin testing` ignores it (cfg(test) is
// off); `cargo test --bin testing` discovers and runs each #[test] here through
// libtest. It mirrors sections A, C, and D one-for-one.
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn add_two_table() {
        // The same table as section A, asserted with the real assert_eq! macro.
        for &(input, want) in &[
            (0_u64, 2_u64),
            (2, 4),
            (40, 42),
            (100, 102),
            (u64::MAX - 2, u64::MAX),
        ] {
            assert_eq!(add_two(input), want);
        }
    }

    #[test]
    fn guess_valid_is_ok() {
        assert_eq!(Guess::new(50).value(), 50);
    }

    #[test]
    #[should_panic(expected = "between 1 and 100")]
    fn guess_too_large_panics() {
        Guess::new(200);
    }

    #[test]
    fn parse_hex_ok_and_err() -> Result<(), ParseIntError> {
        assert_eq!(parse_hex("ff")?, 255_u64);
        assert!(parse_hex("nope").is_err());
        Ok(())
    }
}
