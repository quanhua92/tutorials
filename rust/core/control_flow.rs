//! control_flow.rs — Phase 1 bundle.
//!
//! GOAL (one line): show, by printing every value, that Rust's control-flow
//! constructs are EXPRESSIONS (they yield values), that `match` is EXHAUSTIVE
//! (every case must be covered or it will not compile), and that `?` / `let`
//! else / `loop { break v }` are all just early-return shapes built on the same
//! expression model.
//!
//! This is the GROUND TRUTH for CONTROL_FLOW.md. Every number, table, and
//! worked example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! Several rules are COMPILE ERRORS (a non-`bool` `if` condition; a
//! non-exhaustive `match`; `?` in a `()`-returning function). Those cannot live
//! in a runnable file — this binary would not build. They are documented in
//! CONTROL_FLOW.md with the exact compiler message (E0308, E0004, E0277).
//!
//! Run:
//!     just run control_flow   (== cargo run --bin control_flow)

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

// ── Section A: `if` is an EXPRESSION (it yields a value); conditions are bool ─

fn section_a() {
    banner("A — if is an EXPRESSION (yields a value); condition must be bool");
    // `if`/`else`/`else if` are expressions: the taken arm's value becomes the
    // value of the whole `if`. Both arms MUST have the same type (else E0308).
    let x: i32 = if true { 10 } else { 20 };
    let y: i32 = if false { 10 } else { 20 };
    println!("  let x: i32 = if true  {{10}} else {{20}};  -> x = {x}");
    println!("  let y: i32 = if false {{10}} else {{20}};  -> y = {y}");
    check(
        "if-expression yields the TAKEN arm: if true {10} else {20} == 10",
        x == 10,
    );
    check(
        "if-expression yields the ELSE arm when cond is false: == 20",
        y == 20,
    );

    // An `else if` chain evaluates top-down; the FIRST true arm wins and the
    // rest are not even checked (Book ch3.5). 6 is divisible by 3 AND by 2, but
    // the `div3` arm comes first, so it wins.
    let n = 6;
    let bucket: &str = if n % 4 == 0 {
        "div4"
    } else if n % 3 == 0 {
        "div3"
    } else if n % 2 == 0 {
        "div2"
    } else {
        "none"
    };
    println!("  n = {n}; else-if chain -> bucket = {bucket:?}");
    check(
        "else-if chain: first TRUE arm wins (6 -> div3, not div2)",
        bucket == "div3",
    );

    // The condition must be exactly `bool`. There is NO truthiness of ints: the
    // form `if number { ... }` is a COMPILE ERROR E0308 when number is an i32.
    // The fix is to make the boolean explicit (`number != 0`). See CONTROL_FLOW.md.
    let number = 3;
    if number != 0 {
        println!("  number = {number}; `if number != 0` (explicit bool) -> taken");
    }
    check(
        "conditions require an explicit bool (no int truthiness): number != 0",
        number != 0,
    );
}

// ── Section B: `match` is EXHAUSTIVE — every case must be covered ────────────

#[derive(Debug, Clone, Copy)]
enum Light {
    Red,
    Yellow,
    Green,
}

/// Matching on an enum with NO catch-all: every variant is named, so the match
/// is exhaustive without `_`. Adding a new variant later is a compile error here
/// until you handle it — that is the exhaustiveness promise.
fn light_action(l: Light) -> &'static str {
    match l {
        Light::Red => "stop",
        Light::Yellow => "prepare to stop",
        Light::Green => "go",
    }
}

fn section_b() {
    banner("B — match is EXHAUSTIVE: every case must be covered (else E0004)");
    let actions = [
        light_action(Light::Red),
        light_action(Light::Yellow),
        light_action(Light::Green),
    ];
    println!("  light_action(Red/Yellow/Green) = {actions:?}");
    check(
        "exhaustive match on enum: all 3 variants named, no `_` arm needed",
        actions == ["stop", "prepare to stop", "go"],
    );

    // For wide types (a u8 has 256 values), you cannot list them all — so you
    // add a `_` catch-all arm to satisfy exhaustiveness. The `_` arm must be
    // LAST: arms are tried in order, and the compiler warns about unreachable
    // arms placed after a catch-all.
    let roll: u8 = 7;
    let outcome = match roll {
        3 => "add hat",
        7 => "remove hat",
        _ => "move",
    };
    println!("  roll = {roll}; match {{3, 7, _}} -> outcome = {outcome:?}");
    check(
        "u8 match with `_` catch-all: 7 -> \"remove hat\"",
        outcome == "remove hat",
    );

    let other = match 42u8 {
        3 => "add hat",
        7 => "remove hat",
        _ => "move",
    };
    println!("  roll = 42; same match -> outcome = {other:?}");
    check(
        "u8 match with `_` catch-all: 42 -> \"move\" (the _ arm)",
        other == "move",
    );
}

// ── Section C: match guards, ranges, and or-patterns ─────────────────────────

fn section_c() {
    banner("C — match guards, ranges (1..=3), and or-patterns (a|e|i|o|u)");

    // Range patterns (`1..=3`) and or-patterns (`a|e|i|o|u`) are matched in
    // order. A guard (`if cond`) narrows an arm further. IMPORTANT: a guard can
    // always evaluate false, so the compiler treats guarded arms as NOT covering
    // their pattern — you still need a `_` (or full coverage) for exhaustiveness.
    let classify = |n: i32| -> &'static str {
        match n {
            1..=3 => "tiny (range 1..=3)",
            x if x % 2 == 0 => "even (guard x % 2 == 0)",
            _ => "other",
        }
    };
    let c2 = classify(2);
    let c4 = classify(4);
    let c9 = classify(9);
    println!("  classify(2) = {c2:?}   (2 is in 1..=3 -> first arm wins)");
    println!("  classify(4) = {c4:?}   (4 not in range; 4 % 2 == 0 -> guarded arm)");
    println!("  classify(9) = {c9:?}   (9 not in range; 9 odd -> `_` arm)");
    check(
        "range arm wins first: classify(2) == \"tiny (range 1..=3)\"",
        c2 == "tiny (range 1..=3)",
    );
    check(
        "guard arm matches when range did not: classify(4) == even",
        c4 == "even (guard x % 2 == 0)",
    );
    check(
        "unmatched value falls through to `_`: classify(9) == other",
        c9 == "other",
    );

    // Or-pattern: several literals share one arm. Cleaner than a long else-if.
    let classify_char = |c: char| -> &'static str {
        match c {
            'a' | 'e' | 'i' | 'o' | 'u' => "vowel",
            _ => "consonant or other",
        }
    };
    let v = classify_char('e');
    let s = classify_char('k');
    println!("  classify_char('e') = {v:?};  classify_char('k') = {s:?}");
    check("or-pattern: 'e' is a vowel", v == "vowel");
    check("or-pattern: 'k' falls to `_`", s == "consonant or other");
}

// ── Section D: `if let` and `while let` — single-pattern control flow ────────

fn section_d() {
    banner("D — if let / while let: sugar for a match that cares about ONE pattern");
    // `if let P = expr { .. } else { .. }` is sugar for a `match` with one real
    // arm and a `_` arm. It BINDS the inner value on a match; the else runs on a
    // miss. You LOSE the exhaustive check `match` enforces — that is the trade.
    let opt: Option<i32> = Some(42);
    if let Some(v) = opt {
        println!("  if let Some(v) = Some(42) -> v = {v}");
        check("if let binds the inner value on a match: v == 42", v == 42);
    } else {
        check("if let binds the inner value on a match: v == 42", false);
    }

    let none: Option<i32> = None;
    let mut hit_else = false;
    if let Some(_v) = none {
        // not taken: None does not match Some(_v)
    } else {
        hit_else = true;
    }
    check(
        "if let runs the else block when the pattern does NOT match",
        hit_else,
    );

    // `while let P = expr { .. }` re-evaluates expr each iteration; it stops the
    // moment the pattern fails. The classic use: drain a stack via `Vec::pop`.
    let mut stack: Vec<i32> = vec![10, 20, 30];
    let mut drained: Vec<i32> = Vec::new();
    while let Some(top) = stack.pop() {
        drained.push(top);
    }
    println!("  vec![10,20,30] drained by `while let Some(top) = stack.pop()`:");
    println!(
        "    drained (pop order) = {drained:?};  stack.is_empty() = {}",
        stack.is_empty()
    );
    check(
        "while let drains a Vec via pop(): order is [30, 20, 10] (LIFO)",
        drained == [30, 20, 10],
    );
    check(
        "while let stops when pop() returns None: stack now empty",
        stack.is_empty(),
    );
}

// ── Section E: `let ... else` — refutable binding with a divergent else ──────

/// `let P = expr else { diverge };` binds on a match but, unlike `if let`, the
/// binding lives in the OUTER scope (the "happy path" stays flat). The `else`
/// block MUST diverge: `return`, `break`, `continue`, `panic!`, or `loop {}`.
/// Stabilized in Rust 1.65 (Nov 2022).
fn parse_decimal(s: &str) -> Result<u32, String> {
    let Some(c) = s.chars().next() else {
        return Err("empty input".to_string());
    };
    let Some(d) = c.to_digit(10) else {
        return Err(format!("not a decimal digit: {c:?}"));
    };
    Ok(d)
}

fn section_e() {
    banner("E — let ... else: refutable binding with a DIVERGENT else branch");
    let ok = parse_decimal("7");
    let empty = parse_decimal("");
    let bad = parse_decimal("x");
    println!("  parse_decimal(\"7\")  = {ok:?}    (happy path binds c, then d)");
    println!("  parse_decimal(\"\")   = {empty:?}   (no first char -> else returns)");
    println!("  parse_decimal(\"x\")  = {bad:?}    (char not a digit -> else returns)");
    check(
        "let-else happy path: parse_decimal(\"7\") == Ok(7)",
        ok == Ok(7),
    );
    check(
        "let-else diverges on miss: parse_decimal(\"\") == Err(\"empty input\")",
        empty == Err("empty input".to_string()),
    );
    check(
        "let-else diverges on miss: parse_decimal(\"x\") == Err(\"not a decimal digit: 'x'\")",
        bad == Err("not a decimal digit: 'x'".to_string()),
    );
}

// ── Section F: the `?` operator — early-return Err (or None) up the call stack ─

#[derive(Debug, Clone, PartialEq, Eq)]
enum PipeErr {
    Empty,
    NotDigit(char),
    TooLarge(u32),
}

fn first_char(s: &str) -> Result<char, PipeErr> {
    s.chars().next().ok_or(PipeErr::Empty)
}

fn digit_value(c: char) -> Result<u32, PipeErr> {
    // `PipeErr::NotDigit(c)` is cheap to build (char is Copy), so `ok_or` is
    // fine here; clippy would flag the closure form as needless. `?` then
    // propagates the error out of this fn.
    c.to_digit(10).ok_or(PipeErr::NotDigit(c))
}

fn scale(n: u32) -> Result<u32, PipeErr> {
    if n > 5 {
        Err(PipeErr::TooLarge(n))
    } else {
        Ok(n * 10)
    }
}

/// `?` unwraps an `Ok` in place and, on `Err`, does an early `return Err(...)`.
/// Because the fn returns `Result<_, PipeErr>`, every `?` here must produce a
/// `PipeErr` (it does — `?` also runs `From::from` to convert, but these already
/// match). Three `?`s in a row = three propagation points.
fn run_pipeline(s: &str) -> Result<u32, PipeErr> {
    let c = first_char(s)?; // propagates Empty
    let d = digit_value(c)?; // propagates NotDigit
    let scaled = scale(d)?; // propagates TooLarge
    Ok(scaled + 1)
}

/// `?` also works on `Option`, but ONLY inside an `Option`-returning fn. You
/// cannot mix `?` on a `Result` in an `Option` fn (or vice versa) without an
/// explicit conversion (.ok() / .ok_or()).
fn first_decimal_value(text: &str) -> Option<u32> {
    let first = text.chars().next()?; // ? on Option: early-returns None
    first.to_digit(10)
}

fn section_f() {
    banner("F — the ? operator: early-return Err up the stack (and None for Option)");
    let ok = run_pipeline("3");
    let empty = run_pipeline("");
    let bad = run_pipeline("x");
    let big = run_pipeline("9");
    println!("  run_pipeline(\"3\") = {ok:?}   (3 -> 3 -> scale=30 -> 31)");
    println!("  run_pipeline(\"\")  = {empty:?}");
    println!("  run_pipeline(\"x\") = {bad:?}");
    println!("  run_pipeline(\"9\") = {big:?}   (9 -> 9 -> scale errs TooLarge)");
    check(
        "? success path: run_pipeline(\"3\") == Ok(31)",
        ok == Ok(31),
    );
    check(
        "? propagates the FIRST Err: run_pipeline(\"\") == Err(Empty)",
        empty == Err(PipeErr::Empty),
    );
    check(
        "? propagates the SECOND Err: run_pipeline(\"x\") == Err(NotDigit('x'))",
        bad == Err(PipeErr::NotDigit('x')),
    );
    check(
        "? propagates the THIRD Err: run_pipeline(\"9\") == Err(TooLarge(9))",
        big == Err(PipeErr::TooLarge(9)),
    );

    let od = first_decimal_value("7abc");
    let on = first_decimal_value("");
    let oother = first_decimal_value("abc");
    println!("  first_decimal_value(\"7abc\") = {od:?};  (\"\") = {on:?};  (\"abc\") = {oother:?}");
    check(
        "? on Option: first_decimal_value(\"7abc\") == Some(7)",
        od == Some(7),
    );
    check(
        "? on Option: first_decimal_value(\"\") == None",
        on.is_none(),
    );
    check(
        "? on Option: first_decimal_value(\"abc\") == None ('a' not a digit)",
        oother.is_none(),
    );
}

// ── Section G: loop-with-break-value, labels, while, for, continue ───────────

fn section_g() {
    banner("G — loop { break v } yields a value; labels; while; for + IntoIterator");

    // `loop` is infinite unless a `break` stops it. A `break` may carry a VALUE:
    // that value becomes the value of the whole `loop` expression (Reference
    // §expr.loop.break-value). Classic example: first Fibonacci number > 10.
    let (mut a, mut b) = (1u32, 1u32);
    let first_fib_over_ten: u32 = loop {
        if b > 10 {
            break b;
        }
        let next = a + b;
        a = b;
        b = next;
    };
    println!("  first Fibonacci > 10 = {first_fib_over_ten}  (loop {{ break b; }})");
    check(
        "loop with break value: first Fibonacci > 10 is 13",
        first_fib_over_ten == 13,
    );

    // A LABEL (`'name:`) lets `break 'name` / `continue 'name` target an OUTER
    // loop. Here a labeled `for` exits the outer scan the moment the target is
    // found, counting how many cells were visited first.
    let matrix: [[i32; 2]; 2] = [[1, 2], [3, 4]];
    let target = 4;
    let mut visits_before_hit = 0u32;
    'outer: for row in &matrix {
        for &v in row {
            if v == target {
                break 'outer;
            }
            visits_before_hit += 1;
        }
    }
    println!(
        "  matrix {matrix:?}; target {target}; cells visited before hit = {visits_before_hit}"
    );
    check(
        "labeled for + break 'outer: 3 cells visited before finding 4",
        visits_before_hit == 3,
    );

    // A labeled BLOCK (`'blk: { ... }`) runs once but lets `break 'blk value`
    // return a value from the middle of the block — handy for early-exit search.
    let grid = [[0, 1, 2], [3, 4, 5], [6, 7, 8]];
    let want = 5;
    let found: Option<(usize, usize)> = 'search: {
        for (r, row) in grid.iter().enumerate() {
            for (c, &v) in row.iter().enumerate() {
                if v == want {
                    break 'search Some((r, c));
                }
            }
        }
        None
    };
    println!("  grid search for {want} -> found = {found:?}  (break 'search value)");
    check(
        "labeled block + break 'label value: 5 found at (row 1, col 2)",
        found == Some((1, 2)),
    );

    // `while cond { .. }`: a predicate loop. Evaluates to `()`.
    let mut countdown = 3u32;
    let mut ticks = 0u32;
    while countdown > 0 {
        ticks += 1;
        countdown -= 1;
    }
    println!("  countdown from 3 via `while` -> ticks = {ticks}");
    check(
        "while loop: 3 iterations for a countdown from 3",
        ticks == 3,
    );

    // `continue` skips the rest of the current iteration. Here it skips odd n.
    let mut sum_even = 0u32;
    for n in 1..=6u32 {
        if n % 2 != 0 {
            continue;
        }
        sum_even += n;
    }
    println!("  sum of even n in 1..=6 (skipping odds via continue) = {sum_even}");
    check("for + continue: 2+4+6 == 12", sum_even == 12);

    // `for x in coll` takes anything that implements `IntoIterator`. Consuming a
    // Vec by value yields owned elements (the Vec is drained into the loop).
    let words: Vec<String> = vec!["rust".to_string(), "ace".to_string()];
    let mut total_chars = 0usize;
    for w in words {
        total_chars += w.len();
    }
    println!("  for w in Vec<String> (IntoIterator) -> total chars = {total_chars}");
    check(
        "for consumes a Vec via IntoIterator: 4 + 3 == 7 chars",
        total_chars == 7,
    );
}

fn main() {
    println!("control_flow.rs — Phase 1 bundle.");
    println!("Every value below is computed by this file.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    section_g();
    banner("DONE — all sections printed");
}
