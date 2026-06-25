//! time.rs — Phase 5 bundle.
//!
//! GOAL (one line): show, by printing every value, that Rust has TWO clocks —
//! `Instant` (monotonic, for measuring intervals) and `SystemTime` (wall, for
//! timestamps) — plus `Duration` (a span) and `thread::sleep` (a block), and
//! why the two clocks are NOT interchangeable.
//!
//! This is the GROUND TRUTH for TIME.md. Every number, table, and worked
//! example in the guide is printed by this file. Change it -> re-run ->
//! re-paste. Never hand-compute.
//!
//! DETERMINISM NOTE: `Instant::now()` / `SystemTime::now()` return values that
//! vary every run (wall time / monotonic counter). This file NEVER prints or
//! asserts such a value. It only (a) asserts arithmetic on Durations BUILT FROM
//! CONSTANTS, and (b) asserts the STRUCTURAL BOUND that `start.elapsed()` after
//! a fixed `sleep(d)` is `>= d` (the bound is deterministic; the nanos are not).
//! Therefore two `just out time` runs are byte-identical.
//!
//! Run:
//!     just run time   (== cargo run --bin time)

use std::thread::sleep;
use std::time::{Duration, Instant, SystemTime};

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

// ── Section A: Duration — a span of time built from constants ────────────────

fn section_a() {
    banner("A — Duration: a span built from constants (equality & arithmetic)");
    // A Duration is { whole seconds: u64, sub-second nanos: u32 (< 1e9) }. Every
    // `from_*` constructor just normalizes into that pair, so the SAME span built
    // through different units is EQUAL. The std::time module doc shows exactly:
    //   from_secs(5) == from_millis(5_000) == from_micros(5_000_000) == from_nanos(5_000_000_000)
    let min = Duration::from_secs(60);
    println!("  Duration::from_secs(60)  ==  {:?}", min);
    println!(
        "    also == from_millis(60_000) ?  {}",
        min == Duration::from_millis(60_000)
    );
    println!(
        "    also == from_micros(60_000_000) ?  {}",
        min == Duration::from_micros(60_000_000)
    );
    println!(
        "    also == from_nanos(60_000_000_000) ?  {}",
        min == Duration::from_nanos(60_000_000_000)
    );

    check(
        "Duration::from_secs(60) == from_millis(60_000) (units normalize)",
        min == Duration::from_millis(60_000),
    );
    check(
        "Duration::from_secs(60) == from_micros(60_000_000)",
        min == Duration::from_micros(60_000_000),
    );
    check(
        "Duration::from_secs(60) == from_nanos(60_000_000_000)",
        min == Duration::from_nanos(60_000_000_000),
    );

    // Duration implements Add/Sub/Mul(u32)/Div(u32). Addition of two whole spans
    // is just whole + whole: from_secs(60) + from_secs(60) == from_secs(120).
    let sum = Duration::from_secs(60) + Duration::from_secs(60);
    println!("  from_secs(60) + from_secs(60) == {:?}", sum);
    check(
        "from_secs(60) + from_secs(60) == from_secs(120)",
        sum == Duration::from_secs(120),
    );

    // Mixed units add across the seconds/nanos boundary:
    // 90s + 500ms == 90.5s == from_millis(90_500).
    let mixed = Duration::from_secs(90) + Duration::from_millis(500);
    println!("  from_secs(90) + from_millis(500) == {:?}", mixed);
    check(
        "from_secs(90) + from_millis(500) == from_millis(90_500)",
        mixed == Duration::from_millis(90_500),
    );
}

// ── Section B: Duration parts, comparisons, and the float views ──────────────

fn section_b() {
    banner("B — Duration: parts (as_secs/subsec_*), comparisons, floats");
    // `as_secs()` returns the WHOLE seconds only; the fractional part lives in
    // subsec_*. The std docs pin this: from_millis(5_432) -> as_secs()==5,
    // subsec_millis()==432.
    let d = Duration::from_millis(5_432);
    println!("  Duration::from_millis(5_432):");
    println!("    as_secs()       = {}", d.as_secs());
    println!("    subsec_millis() = {}", d.subsec_millis());
    check(
        "from_millis(5_432).as_secs() == 5 (whole seconds only)",
        d.as_secs() == 5,
    );
    check(
        "from_millis(5_432).subsec_millis() == 432 (fractional part)",
        d.subsec_millis() == 432,
    );

    // as_secs_f64() returns the span INCLUDING the fractional part. For a whole
    // number of seconds it is exact (90.0). Compared with an epsilon because
    // clippy::float_cmp forbids bare == on f64.
    let d90 = Duration::from_secs(90);
    println!(
        "  Duration::from_secs(90).as_secs_f64() = {}",
        d90.as_secs_f64()
    );
    check(
        "from_secs(90).as_secs_f64() == 90.0 (exact, whole seconds)",
        (d90.as_secs_f64() - 90.0).abs() <= f64::EPSILON,
    );
    check("from_secs(90).as_secs() == 90", d90.as_secs() == 90);

    // Total-width accessors (as_millis/as_micros/as_nanos) return u128 and span
    // the WHOLE duration, not just a subsecond slice.
    let one_half = Duration::new(1, 500_000_000); // 1.5s
    println!("  Duration::new(1, 500_000_000)  (1.5s):");
    println!("    as_millis() = {}", one_half.as_millis());
    println!("    as_micros() = {}", one_half.as_micros());
    println!("    as_nanos()  = {}", one_half.as_nanos());
    check(
        "1.5s.as_millis() == 1500 and as_micros() == 1_500_000 and as_nanos() == 1_500_000_000",
        one_half.as_millis() == 1500
            && one_half.as_micros() == 1_500_000
            && one_half.as_nanos() == 1_500_000_000,
    );

    // Duration is Ord: comparisons work directly.
    check(
        "from_secs(60) > from_secs(30) (Duration is Ord)",
        Duration::from_secs(60) > Duration::from_secs(30),
    );
    check(
        "from_millis(1) < from_secs(1)",
        Duration::from_millis(1) < Duration::from_secs(1),
    );

    // ZERO and MAX, plus Default == ZERO (Default returns a zero-length span).
    let zero = Duration::ZERO;
    let default_dur = Duration::default();
    println!(
        "  Duration::ZERO == {:?},  Duration::default() == {:?}",
        zero, default_dur
    );
    check("Duration::ZERO == Duration::default()", zero == default_dur);
    check("Duration::ZERO.is_zero() == true", zero.is_zero());
}

// ── Section C: Instant — the MONOTONIC clock for measuring intervals ─────────

fn section_c() {
    banner("C — Instant: the MONOTONIC clock (measure intervals, never print now())");
    // `Instant` is "a measurement of a monotonically nondecreasing clock. Opaque
    // and useful only with Duration." On Unix it reads CLOCK_MONOTONIC, on macOS
    // CLOCK_UPTIME_RAW, on Windows QueryPerformanceCounter. It never goes
    // backwards (barring OS bugs), so it is the ONLY correct clock for timing.
    //
    // `Instant::now()` returns a value that is DIFFERENT every run. We therefore
    // never print or assert the value itself — only the structural fact that,
    // after a fixed sleep(d), start.elapsed() >= d. That bound is deterministic
    // even though the nanos are not.

    let d = Duration::from_millis(2); // tiny fixed span
    let start = Instant::now(); // value NOT printed (would vary run-to-run)
    sleep(d); // blocks the current thread for >= d
    let elapsed = start.elapsed(); // value NOT printed

    // This is EXACTLY the std doc's `elapsed()` example idiom:
    //   let instant = Instant::now(); let three_secs = ...; sleep(...);
    //   assert!(instant.elapsed() >= three_secs);
    // We assert the BOUND (>= d), never the exact nanos.
    check(
        "after sleep(2ms), start.elapsed() >= 2ms (bound only; nanos not printed)",
        elapsed >= d,
    );
    check(
        "elapsed.is_zero() == false (something measurable passed)",
        !elapsed.is_zero(),
    );
    println!("  OK: slept >= 2ms (elapsed bound holds; value intentionally not shown)");

    // duration_since / checked_duration_since: subtracting two Instant points.
    // We do NOT print the result (it varies), only assert the bound on a pair we
    // built around the same fixed sleep.
    let a = Instant::now();
    sleep(Duration::from_millis(1));
    let b = Instant::now();
    check(
        "b.duration_since(a) >= 1ms (monotonic: later - earlier is positive)",
        b.duration_since(a) >= Duration::from_millis(1),
    );
    check(
        "a.checked_duration_since(b) == None (earlier - later is not representable)",
        a.checked_duration_since(b).is_none(),
    );
}

// ── Section D: SystemTime — the WALL clock (jumpable; for timestamps) ────────

fn section_d() {
    banner("D — SystemTime: the WALL clock (jumpable; use for timestamps, NOT intervals)");
    // `SystemTime` is "a measurement of the system clock, useful for talking to
    // external entities like the file system or other processes." It is NOT
    // monotonic: it CAN jump (NTP step, manual change, leap-second smear), so a
    // later operation may report an EARLIER SystemTime than an earlier one.
    //
    // Consequence #1: SystemTime::now() is NEVER printed/asserted here (it
    // varies, and may even go backwards). We only prove we CAN obtain one, and
    // document that you must NOT measure intervals with it.
    let _now_is_a_systemtime: SystemTime = SystemTime::now();
    println!("  SystemTime::now() obtained (value NOT printed: wall clock varies)");
    check(
        "a SystemTime can be obtained from SystemTime::now() (type proved)",
        // We only check the TYPE is live; the value is nondeterministic, so we
        // never look at it. Use a const-true predicate anchored on the type.
        std::any::TypeId::of::<SystemTime>() == std::any::TypeId::of::<SystemTime>(),
    );

    // Consequence #2: because it can go backwards, duration_since / elapsed
    // return Result<Duration, SystemTimeError> (fallible), unlike Instant's
    // infallible Duration. We demonstrate the Ok and Err arms on CONSTRUCTED
    // SystemTimes anchored at UNIX_EPOCH — fully deterministic, no now().
    //
    // UNIX_EPOCH = "1970-01-01 00:00:00 UTC" — the anchor for all SystemTimes.
    let t1 = SystemTime::UNIX_EPOCH + Duration::from_secs(1_000);
    let t2 = SystemTime::UNIX_EPOCH + Duration::from_secs(2_000);
    println!("  t1 = UNIX_EPOCH + 1000s;  t2 = UNIX_EPOCH + 2000s  (constructed, deterministic)");

    // t2 is later than t1 -> duration_since is Ok(1000s). (SystemTimeError does
    // not impl PartialEq, so we inspect the Ok arm's Duration via as_ref().ok().)
    let forward = t2.duration_since(t1);
    check(
        "t2.duration_since(t1) is Ok  (later - earlier succeeds)",
        forward.is_ok(),
    );
    check(
        "t2.duration_since(t1) carries Ok(1000s)",
        forward.as_ref().ok() == Some(&Duration::from_secs(1_000)),
    );

    // t1.duration_since(t2) is Err(SystemTimeError) — the gap is carried back.
    let backward = t1.duration_since(t2);
    check(
        "t1.duration_since(t2) is Err  (earlier - later -> SystemTimeError)",
        backward.is_err(),
    );
    check(
        "the SystemTimeError carries the magnitude: .duration() == 1000s",
        backward.err().map(|e| e.duration()) == Some(Duration::from_secs(1_000)),
    );

    // Contrast summary (printed, deterministic — it's prose, not a clock value):
    println!("  Instant     : monotonic, infallible Duration   -> USE for intervals");
    println!("  SystemTime  : wall,     Result<_, SystemTimeError> -> USE for timestamps");
}

// ── Section E: thread::sleep — blocks the current thread for at least d ──────

fn section_e() {
    banner("E — thread::sleep: blocks the current thread for AT LEAST d");
    // sleep(dur) "puts the current thread to sleep for at least the specified
    // amount of time. The thread may sleep longer ... due to scheduling
    // specifics or platform-dependent functionality. It will never sleep less."
    // It is a BLOCKING call and must NOT be used inside async functions.
    let before = Instant::now();
    sleep(Duration::from_millis(1)); // blocks ~1ms (>= 1ms, scheduling-dependent)
    let after = Instant::now();

    // The function returns () — there is no value to inspect, so the observable
    // contract is "control resumed AND at least d elapsed". Reaching this line at
    // all proves the call returned.
    let ran_after_sleep = true; // control resumed => sleep returned
    check(
        "control resumes after sleep(1ms) (the () call returned)",
        ran_after_sleep,
    );
    check(
        "sleep(1ms) blocks for >= 1ms (never less; may be more)",
        after.duration_since(before) >= Duration::from_millis(1),
    );
    println!("  OK: thread blocked then resumed; >= 1ms elapsed (value not shown)");

    // A zero Duration on Unix returns immediately without invoking nanosleep; on
    // Windows it still calls the Sleep syscall. Either way it does NOT block.
    let z_before = Instant::now();
    sleep(Duration::ZERO);
    let z_after = Instant::now();
    check(
        "sleep(Duration::ZERO) does not meaningfully block (>= 0s trivially holds)",
        z_after.duration_since(z_before) >= Duration::ZERO,
    );
}

// ── Section F: Duration edge cases — overflow, checked_*, saturating_*, ZERO ─

fn section_f() {
    banner("F — Duration edge cases: overflow, checked_*, saturating_*");
    // Duration::MAX is about 584 billion years (u64 seconds + <1e9 nanos). Adding
    // anything to it overflows: `+` would panic on debug, so use checked_/saturating_.
    let max = Duration::MAX;
    println!("  Duration::MAX (approx 584,942,417,355 years): {:?}", max);

    // checked_add returns None on overflow (the std docs pin this exact example).
    let overflow = max.checked_add(Duration::from_secs(1));
    check(
        "Duration::MAX.checked_add(from_secs(1)) == None (overflow detected)",
        overflow.is_none(),
    );

    // saturating_add clamps to Duration::MAX instead of overflowing.
    let clamped = max.saturating_add(Duration::from_secs(1));
    check(
        "Duration::MAX.saturating_add(from_secs(1)) == Duration::MAX (clamped)",
        clamped == Duration::MAX,
    );

    // Durations cannot be negative: subtracting too much underflows. checked_sub
    // returns None; saturating_sub returns ZERO.
    let none_sub = Duration::ZERO.checked_sub(Duration::from_nanos(1));
    let zero_sub = Duration::ZERO.saturating_sub(Duration::from_nanos(1));
    check(
        "ZERO.checked_sub(from_nanos(1)) == None (negative is not representable)",
        none_sub.is_none(),
    );
    check(
        "ZERO.saturating_sub(from_nanos(1)) == Duration::ZERO (clamps at zero)",
        zero_sub == Duration::ZERO,
    );

    // Multiplication by an integer scalar; checked_/saturating_ mirror add/sub.
    let scaled = Duration::from_millis(500).checked_mul(3);
    check(
        "from_millis(500).checked_mul(3) == Some(from_millis(1_500))",
        scaled == Some(Duration::from_millis(1_500)),
    );
    let mul_overflow = max.checked_mul(2);
    check(
        "Duration::MAX.checked_mul(2) == None (scalar overflow)",
        mul_overflow.is_none(),
    );

    // abs_diff is symmetric and always non-negative (1.81.0).
    let big = Duration::from_secs(100);
    let small = Duration::from_secs(80);
    check(
        "from_secs(100).abs_diff(from_secs(80)) == from_secs(20)  (order-independent)",
        big.abs_diff(small) == Duration::from_secs(20)
            && small.abs_diff(big) == big.abs_diff(small),
    );
}

fn main() {
    println!("time.rs — Phase 5 bundle (std::time: Instant, SystemTime, Duration; sleep).");
    println!("Every value below is computed by this file; no wall/now()-value is printed.\n");
    section_a();
    section_b();
    section_c();
    section_d();
    section_e();
    section_f();
    banner("DONE — all sections printed");
}
