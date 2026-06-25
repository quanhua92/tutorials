// std_expected_optional.cpp — Phase 7 bundle.
//
// GOAL (one line): show, by printing every value, how std::optional<T>
// ("maybe a T") and std::expected<T,E> (C++23, "a T OR an error E") behave —
// the checked accessors (.value()/.value_or/.error()), the UB of `*opt` on an
// empty optional and of `.value()` on an unexpected expected (documented, NEVER
// executed in the verified path), the C++23 monadic ops (.and_then/
// .transform/.or_else), and how `expected` is the error-as-value style that
// Rust `Result<T,E>` + `?` and Go's `error` return embody — no hidden control
// flow, the error visible in the signature.
//
// This is the GROUND TRUTH for STD_EXPECTED_OPTIONAL.md. Every value, [check],
// and worked example in the guide is printed by this file. Change it ->
// re-compile -> re-paste. Never hand-compute.
//
// SAFETY NOTE: there are TWO documented UB traps in this domain and BOTH are
// kept out of the verified path (mirroring how values_types.cpp handles the
// uninitialized-read UB):
//   (1) `*opt` (operator*) on an EMPTY optional -> UB.  We use .value() (throws
//       std::bad_optional_access, caught in Section A) or check .has_value().
//   (2) `.value()` on an UNEXPECTED expected -> UB (expected has NO throwing
//       accessor — unlike optional, .value() does NOT throw here; it is UB).
//       The offending call is gated behind #ifdef DEMO_UB, which `just run`/
//       `just out`/`just check`/`just sanitize` NEVER pass.
//
// Run:
//     just run std_expected_optional
//         (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//             std_expected_optional.cpp -o /tmp/cpp_std_expected_optional
//             && /tmp/cpp_std_expected_optional)

#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar) + strcmp
#include <optional>    // std::optional, std::nullopt, std::bad_optional_access
#include <expected>    // std::expected, std::unexpected (C++23)
#include <stdexcept>   // std::runtime_error (the throw-vs-expected contrast)
#include <string>      // std::string (the error payload)

namespace {

constexpr int BANNER_WIDTH = 70;

// sectionBanner prints a clearly delimited section divider (the house style).
void sectionBanner(const char* title) {
    char bar[BANNER_WIDTH + 1];
    std::memset(bar, '=', BANNER_WIDTH);
    bar[BANNER_WIDTH] = '\0';
    std::printf("\n%s\nSECTION %s\n%s\n", bar, title, bar);
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it prints to stderr and exits non-zero so `just check`/`just sweep`
// catch it (and ASan/UBSan stay happy — no throw across the verified path).
void check(const char* description, bool ok) {
    if (!ok) {
        std::fprintf(stderr, "INVARIANT VIOLATED: %s\n", description);
        std::exit(EXIT_FAILURE);
    }
    std::printf("[check] %s: OK\n", description);
}

// === Section A — std::optional<T>: "maybe a T" ==============================
//
// std::optional<T> (C++17) holds EITHER a T OR nothing (std::nullopt). It is
// the idiomatic return type for "a function that might not have a result" (a
// lookup that misses, a parse that fails with no rich error). The value is
// NESTED INSIDE the optional object (it models an object, not a pointer — even
// though operator* and operator-> are defined).
//
// THE KEY ACCESSOR ASYMMETRY (memorize this):
//   .value()        -> the T if present; THROWS std::bad_optional_access if
//                      empty. The SAFE accessor (catchable).
//   .value_or(def)  -> the T if present, else `def`. Never throws.
//   operator*       -> the T if present; UB IF EMPTY. The fast/unchecked path —
//                      only after you have checked .has_value().
void sectionA() {
    sectionBanner("A — std::optional<T>: maybe-a-value");

    // (1) An optional WITH a value.
    std::optional<int> has = 42;
    std::printf("(1) std::optional<int> has = 42;\n");
    std::printf("    has.has_value() = %s\n", has.has_value() ? "true" : "false");
    std::printf("    (bool)has       = %s   (contextual conversion)\n",
                has ? "true" : "false");
    std::printf("    has.value()     = %d   (the SAFE accessor)\n", has.value());
    std::printf("    *has            = %d   (unchecked; safe ONLY after has_value)\n", *has);
    std::printf("    has.value_or(0) = %d   (returns the T, ignores the default)\n",
                has.value_or(0));

    check("optional<int>=42 has_value", has.has_value());
    check("(bool)optional matches has_value", (bool)has == has.has_value());
    check("optional.value() == 42", has.value() == 42);
    check("operator* == .value() when engaged", *has == has.value());
    check("value_or returns the T when present", has.value_or(0) == 42);

    // (2) An EMPTY optional. Two ways to spell "no value": default-construct,
    //     or assign std::nullopt (the empty sentinel).
    std::optional<int> empty;            // default -> no value
    std::optional<int> emptied = 7;
    emptied = std::nullopt;              // reset to empty via the sentinel
    std::printf("\n(2) std::optional<int> empty;        emptied = 7; emptied = nullopt;\n");
    std::printf("    empty.has_value()  = %s\n", empty.has_value() ? "true" : "false");
    std::printf("    emptied.has_value()= %s   (nullopt assignment clears it)\n",
                emptied.has_value() ? "true" : "false");
    std::printf("    empty.value_or(99) = %d   (the default, since empty)\n",
                empty.value_or(99));

    check("default-constructed optional is empty", !empty.has_value());
    check("nullopt assignment empties the optional", !emptied.has_value());
    check("value_or returns the default when empty", empty.value_or(99) == 99);

    // (3) .value() on an EMPTY optional THROWS std::bad_optional_access. This
    //     is the SAFE accessor's contract: a catchable exception, not UB. We
    //     catch it (every throw in the verified path is caught — no
    //     std::terminate) and record its message.
    std::printf("\n(3) empty.value()  -> THROWS std::bad_optional_access (caught):\n");
    std::string thrown;
    try {
        // Deliberately the throwing accessor on an empty optional.
        (void)empty.value();   // [[nodiscard]]-free; the side effect IS the throw
    } catch (const std::bad_optional_access& e) {
        thrown = e.what();
        std::printf("    caught std::bad_optional_access: what() = \"%s\"\n", thrown.c_str());
    }
    check("empty.value() threw std::bad_optional_access", !thrown.empty());

    // (4) THE UB TRAP — operator* on an EMPTY optional is UNDEFINED BEHAVIOR.
    //     Unlike .value(), operator* does NOT check and does NOT throw; the
    //     standard says the behavior is undefined if !has_value(). We therefore
    //     DECLINE to call it on `empty`; the offending read is gated behind
    //     #ifdef DEMO_UB below, which the verification recipes never define.
    std::printf("\n(4) *empty  -> UNDEFINED BEHAVIOR (documented, NOT executed):\n");
    std::printf("    operator* performs NO check. The verified path uses .value()\n");
    std::printf("    (throws) or checks .has_value() first. The offending call lives\n");
    std::printf("    behind #ifdef DEMO_UB (never passed by just run/out/check/sanitize).\n");
    check("operator* on empty optional NOT called (UB; gated behind DEMO_UB)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // Compile with -DDEMO_UB to see this build; RUNNING it is UB. UBSan reports
    //   "runtime error: load of value <N>, which is not a valid value for type
    //    'int'" (or no diagnostic at all — UB means the compiler may assume it
    //   cannot happen and delete the surrounding code).
    int garbage = *empty;   // <-- UNDEFINED BEHAVIOR
    std::printf("[DEMO_UB] *empty = %d   <-- meaningless; do NOT rely on this\n", garbage);
#else
    std::printf("    (DEMO_UB not defined: the UB call is correctly omitted from this build.)\n");
#endif
}

// === Section B — std::expected<T,E>: "a T OR an error E" =====================
//
// std::expected<T,E> (C++23) holds EITHER the expected value T (success) OR an
// unexpected value E (the error). It is the C++23 analog of Rust's Result<T,E>
// and Go's (T, error) return — the error-as-value style: the caller MUST
// inspect the result, there is no hidden control-flow jump.
//
// THE KEY ACCESSOR ASYMMETRY (and how it DIFFERS from optional — note this!):
//   .has_value()    -> true if it holds a T (success), false if it holds an E.
//   .value()        -> the T if success; UB IF UNEXPECTED (expected does NOT
//                      throw on bad access — unlike optional). Check first.
//   .error()        -> the E if unexpected; UB IF SUCCESS.
//   .value_or(def)  -> the T if success, else `def`. Safe.
// So: optional.value()-on-empty THROWS; expected.value()-on-unexpected is UB.
// Both demand a .has_value() check before the unchecked path.
void sectionB() {
    sectionBanner("B — std::expected<T,E>: a-value-OR-an-error");

    using Exp = std::expected<int, std::string>;

    // (1) A SUCCESS expected: holds the T. Constructed directly from a T.
    Exp ok = 42;                         // success — implicit from the T
    std::printf("(1) std::expected<int,std::string> ok = 42;\n");
    std::printf("    ok.has_value()  = %s   (success)\n", ok.has_value() ? "true" : "false");
    std::printf("    ok.value()      = %d\n", ok.value());
    std::printf("    *ok             = %d   (unchecked; safe only after has_value)\n", *ok);
    std::printf("    ok.value_or(0)  = %d\n", ok.value_or(0));

    check("expected<int,string>=42 has_value (success)", ok.has_value());
    check("success .value() == 42", ok.value() == 42);
    check("operator* == .value() on success", *ok == ok.value());
    check("value_or returns the T on success", ok.value_or(0) == 42);

    // (2) An UNEXPECTED expected: holds the E. Built with std::unexpected(e) —
    //     the sentinel that selects the error half (a bare E would construct a
    //     success holding an E when T == E, so the wrapper is mandatory).
    Exp err = std::unexpected(std::string("disk full"));   // error half
    std::printf("\n(2) Exp err = std::unexpected(std::string(\"disk full\"));\n");
    std::printf("    err.has_value() = %s   (failure)\n", err.has_value() ? "true" : "false");
    std::printf("    err.error()     = \"%s\"   (the E)\n", err.error().c_str());
    std::printf("    err.value_or(0) = %d   (the default; .value() would be UB here)\n",
                err.value_or(0));

    check("unexpected expected has_value() == false", !err.has_value());
    check("unexpected .error() == \"disk full\"",
          std::strcmp(err.error().c_str(), "disk full") == 0);
    check("value_or returns the default on unexpected", err.value_or(0) == 0);

    // (3) THE UB TRAPS for expected (documented, NOT executed):
    //     (a) .value()  on an UNEXPECTED -> UB   (expected does NOT throw here!)
    //     (b) .error()  on a SUCCESS     -> UB
    //     Both are gated behind #ifdef DEMO_UB; the verified path ALWAYS checks
    //     .has_value() first. Contrast: optional.value() on empty THROWS
    //     bad_optional_access (Section A); expected.value() on unexpected is UB.
    std::printf("\n(3) THE TWO expected UB TRAPS (documented, NOT executed):\n");
    std::printf("    (a) err.value()  on UNEXPECTED -> UB  (expected does NOT throw;\n");
    std::printf("        contrast optional.value() which throws bad_optional_access)\n");
    std::printf("    (b) ok.error()   on SUCCESS     -> UB\n");
    std::printf("    Always check .has_value() before the unchecked accessors.\n");
    check("expected .value()/.error() UB traps NOT triggered (gated behind DEMO_UB)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    int v = err.value();   // <-- UB: .value() on an unexpected expected
    std::string e = ok.error();   // <-- UB: .error() on a success expected
    std::printf("[DEMO_UB] err.value()=%d  ok.error()=\"%s\"  <-- UB; meaningless\n",
                v, e.c_str());
#else
    std::printf("    (DEMO_UB not defined: the UB calls are correctly omitted from this build.)\n");
#endif
}

// === Section C — Monadic ops (C++23) + the error-as-value return style =======
//
// C++23 added the three monadic operations to BOTH optional and expected,
// enabling chained pipelines WITHOUT a ladder of if-has_value checks:
//   .and_then(f)   f: T -> optional<U> / expected<U,E>.  Flat-map: if engaged,
//                  calls f on the value; else propagates the empty/error.
//   .transform(f)  f: T -> U.           Maps: if engaged, wraps f(value); else
//                  propagates the empty/error. (expected's transform = Rust map.)
//   .or_else(f)    f: nullopt_t/error -> optional<T>/expected<T,E>.  Recovery:
//                  if NOT engaged, calls f to try to produce a value.
//
// The error-as-value STYLE: a function returns expected<T,E>; the caller
// inspects — no throw, the error is in the signature. This is the Rust
// `Result<T,E>` + `?` discipline and the Go `(T, error)` discipline, brought to
// C++ in C++23.

// A function that MAY fail, returning expected — the error-as-value style.
// No throw; the caller sees the error type in the signature.
enum class DivErr { ZeroDivisor };

std::expected<int, DivErr> safe_div(int a, int b) {
    if (b == 0) return std::unexpected(DivErr::ZeroDivisor);   // error half
    return a / b;                                              // success half
}

// A step that lifts a success into ANOTHER expected (for .and_then chaining).
std::expected<int, DivErr> add_one(int x) { return x + 1; }

void sectionC() {
    sectionBanner("C — Monadic ops (C++23) & the error-as-value return");

    // --- optional monadic ops ---
    std::printf("--- optional monadic ops ---\n");

    // transform: lift a function T->U over an engaged optional.
    std::optional<int> o = 5;
    std::optional<int> doubled = o.transform([](int x) { return x * 2; });
    std::optional<int> empty_then =
        std::optional<int>{}.transform([](int x) { return x * 2; });  // empty propagates
    std::printf("o = 5;\n");
    std::printf("    o.transform(x*2)                  = %d\n", doubled.value_or(-1));
    std::printf("    optional<int>{}.transform(x*2)    = %s   (empty propagates)\n",
                empty_then.has_value() ? "(engaged)" : "(empty)");

    // and_then: chain a T -> optional<U>.
    std::optional<int> chained =
        std::optional<int>{7}
            .and_then([](int x) { return std::optional<int>{x + 10}; })
            .transform([](int x) { return x * 3; });
    std::printf("    optional{7}.and_then(+10).transform(*3) = %d\n", chained.value_or(-1));

    // or_else: recover from an empty optional.
    std::optional<int> recovered =
        std::optional<int>{}.or_else([] { return std::optional<int>{99}; });
    std::printf("    optional<int>{}.or_else(=>99)        = %d   (recovered)\n",
                recovered.value_or(-1));

    check("optional transform engaged = 10", doubled.value_or(-1) == 10);
    check("optional transform on empty propagates empty", !empty_then.has_value());
    check("optional and_then+transform chain = (7+10)*3 = 51", chained.value_or(-1) == 51);
    check("optional or_else recovered empty to 99", recovered.value_or(-1) == 99);

    // --- expected monadic ops: the Rust Result pipeline, in C++23 ---
    std::printf("\n--- expected monadic ops (the Rust Result pipeline) ---\n");

    auto good = safe_div(20, 4)                 // 20/4 = 5  (success)
                    .and_then(add_one)          // 5+1   = 6  (still success)
                    .transform([](int x) { return x * 10; });  // 6*10 = 60
    auto bad = safe_div(20, 0)                  // ZeroDivisor (error)
                  .and_then(add_one)            // skipped — error propagates
                  .transform([](int x) { return x * 10; });   // skipped
    std::printf("    safe_div(20,4).and_then(add_one).transform(*10)\n");
    std::printf("        -> has_value=%s, value=%d\n",
                good.has_value() ? "true" : "false", good.value_or(-1));
    std::printf("    safe_div(20,0).and_then(add_one).transform(*10)\n");
    std::printf("        -> has_value=%s, error=ZeroDivisor (pipeline short-circuited)\n",
                bad.has_value() ? "true" : "false");

    check("expected pipeline success: 20/4=5, +1=6, *10=60", good.value_or(-1) == 60);
    check("expected pipeline short-circuits on error (no add_one, no *10)",
          !bad.has_value() && bad.error() == DivErr::ZeroDivisor);

    // --- the error-as-value STYLE: a function returning expected, called twice ---
    std::printf("\n--- the error-as-value return style (no throw; error in signature) ---\n");
    auto r1 = safe_div(100, 5);     // success
    auto r2 = safe_div(100, 0);     // error
    std::printf("    safe_div(100,5) -> has_value=%s, value=%d\n",
                r1.has_value() ? "true" : "false", r1.value_or(-1));
    std::printf("    safe_div(100,0) -> has_value=%s, error=ZeroDivisor\n",
                r2.has_value() ? "true" : "false");

    check("safe_div(100,5) == 20 (success path)", r1.has_value() && r1.value() == 20);
    check("safe_div(100,0) is an error (no throw; caller inspects .error())",
          !r2.has_value() && r2.error() == DivErr::ZeroDivisor);
}

// === Section D — The throw-vs-expected-vs-error-code decision ================
//
// Three ways to signal "this operation can fail", three contracts:
//
//   (a) THROW an exception (throw std::runtime_error(...)).  Invisible in the
//       signature. Propagates implicitly up the stack, unwinding dtors (RAII).
//       Best for TRULY exceptional failure that crosses many layers and that
//       the immediate caller usually cannot handle.
//
//   (b) RETURN std::expected<T,E>.  Visible in the signature (expected<T,E>).
//       The caller MUST inspect (the type forces a decision). No control-flow
//       jump — cheap, deterministic, easy to reason about. Best for RECOVERABLE
//       failure where the immediate caller knows what to do.
//
//   (c) RETURN an error CODE (int / bool / errno).  The legacy C style. Visible
//       only by CONVENTION (the type is just int) — easy to ignore silently.
//       No payload (just a number) unless you also pass an out-param.
//
// All three are demonstrated below on the SAME operation (parse an int), so the
// contracts can be compared side by side.

// (a) throw style
int parse_throw(const std::string& s) {
    if (s.empty()) throw std::runtime_error("empty input");
    // Tiny deterministic parser: only "42" is valid.
    if (s == "42") return 42;
    throw std::runtime_error("not 42");
}

// (b) expected style
std::expected<int, std::string> parse_expected(const std::string& s) {
    if (s.empty()) return std::unexpected(std::string("empty input"));
    if (s == "42") return 42;
    return std::unexpected(std::string("not 42"));
}

// (c) error-code style (legacy C): 0 == ok, non-zero == error; payload via out-param
int parse_errcode(const std::string& s, int& out) {
    if (s.empty()) return 1;       // 1 = empty
    if (s == "42") { out = 42; return 0; }
    return 2;                      // 2 = not 42
}

void sectionD() {
    sectionBanner("D — throw vs expected vs error-code (the decision)");

    // Same input, three contracts. We exercise the SUCCESS and FAILURE cases.
    const std::string good_input = "42";
    const std::string bad_input = "no";

    // --- (a) throw: caught (every throw in the verified path is caught) ---
    std::printf("(a) THROW style  (invisible in signature; implicit propagation):\n");
    int a_ok = parse_throw(good_input);
    std::string a_err;
    try {
        (void)parse_throw(bad_input);
    } catch (const std::runtime_error& e) {
        a_err = e.what();
    }
    std::printf("    parse_throw(\"42\")  = %d   (success)\n", a_ok);
    std::printf("    parse_throw(\"no\")  -> caught runtime_error: \"%s\"\n", a_err.c_str());
    check("throw style: success returns 42", a_ok == 42);
    check("throw style: failure throws a catchable runtime_error", !a_err.empty());

    // --- (b) expected: the caller inspects; no throw ---
    std::printf("\n(b) EXPECTED style (visible in signature; caller MUST inspect):\n");
    auto b_ok = parse_expected(good_input);
    auto b_err = parse_expected(bad_input);
    std::printf("    parse_expected(\"42\") -> has_value=%s, value=%d\n",
                b_ok.has_value() ? "true" : "false", b_ok.value_or(-1));
    std::printf("    parse_expected(\"no\") -> has_value=%s, error=\"%s\"\n",
                b_err.has_value() ? "true" : "false", b_err.error().c_str());
    check("expected style: success has_value == true and == 42",
          b_ok.has_value() && b_ok.value() == 42);
    check("expected style: failure carries the error payload (no throw)",
          !b_err.has_value() && std::strcmp(b_err.error().c_str(), "not 42") == 0);

    // --- (c) error-code: convention-only; easy to ignore ---
    std::printf("\n(c) ERROR-CODE style (legacy C; type is just int; easy to ignore):\n");
    int c_out = 0;
    int c_rc_ok = parse_errcode(good_input, c_out);
    int c_dummy = 0;
    int c_rc_err = parse_errcode(bad_input, c_dummy);   // rc==2; many callers forget to check
    std::printf("    parse_errcode(\"42\",out) -> rc=%d, out=%d   (rc 0 == ok)\n",
                c_rc_ok, c_out);
    std::printf("    parse_errcode(\"no\", out) -> rc=%d        (rc 2 == not-42; payload via out)\n",
                c_rc_err);
    check("error-code style: rc==0 on success and out==42", c_rc_ok == 0 && c_out == 42);
    check("error-code style: rc!=0 on failure (caller MUST check rc, not out)",
          c_rc_err != 0);

    // --- the DECISION (documented, not a runtime branch) ---
    std::printf("\nDECISION RULE (no single right answer):\n");
    std::printf("  - THROW      for truly exceptional failure crossing many layers the\n");
    std::printf("               immediate caller cannot handle (RAII unwinds cleanup).\n");
    std::printf("  - EXPECTED   for recoverable failure visible in the signature; the\n");
    std::printf("               caller usually knows what to do (parse, lookup, I/O).\n");
    std::printf("  - ERROR-CODE for legacy C interop / tiny bool-ish success flags.\n");
    check("all three styles exercised on the same operation", a_ok == 42 && b_ok.value() == 42 &&
                                                              c_out == 42);
}

// === Section E — expected IS Rust Result<T,E> (the cross-language pivot) =====
//
// The error-as-value model is the same idea across three languages:
//
//   C++23     std::expected<T,E>     (.value/.error/.has_value; .and_then)
//   Rust      Result<T,E>  + `?`     (Ok(T) | Err(E); the `?` operator propagates)
//   Go        (T, error)             (multiple return; `if err != nil`)
//   Rust      Option<T>              (Some(T) | None)   ==  C++ std::optional<T>
//
// The headline DIFFERENCE: Rust FORCES handling at compile time (you cannot
// read Ok(T) without matching, and `?` makes propagation explicit); C++ and Go
// TRUST you to check (C++ gives you UB if you call .value() on an unexpected;
// Go silently proceeds with a zero-valued T if you ignore the error). This is
// the same trust-vs-enforce axis as C++ vs Rust on memory (no GC + UB vs the
// borrow checker) — see the cross-language table in the .md.
void sectionE() {
    sectionBanner("E — expected IS Rust Result (the cross-language pivot)");

    // The Rust `?` operator, expressed in C++23: each step returns expected;
    // an error short-circuits the whole pipeline. We mirror the canonical
    // Rust `fn() -> Result<_, E> { let x = step1()?; let y = step2(x)?; Ok(y) }`
    // using .and_then, so the two languages line up exactly.
    auto pipeline = [](int seed) -> std::expected<int, DivErr> {
        return safe_div(seed, 2)        // step1: seed/2   (may fail)
                   .and_then(add_one);  // step2: +1       (may fail)
    };

    auto ok = pipeline(10);    // 10/2=5, +1 = 6   -> success
    auto err = pipeline(0);    // wait: 0/2=0, +1=1 — exercise the error path below

    // Exercise the actual ERROR short-circuit: a step that divides by zero.
    auto err2 = safe_div(10, 0).and_then(add_one);   // ZeroDivisor propagates

    std::printf("Rust `?`-style pipeline in C++23 (safe_div(seed,2).and_then(add_one)):\n");
    std::printf("    pipeline(10) -> has_value=%s, value=%d   (== Rust Ok(6))\n",
                ok.has_value() ? "true" : "false", ok.value_or(-1));
    std::printf("    pipeline(0)  -> has_value=%s, value=%d   (0/2=0, +1=1; still Ok)\n",
                err.has_value() ? "true" : "false", err.value_or(-1));
    std::printf("    safe_div(10,0).and_then(add_one) -> has_value=%s, error=ZeroDivisor\n",
                err2.has_value() ? "true" : "false");
    std::printf("        (== Rust: the `?` short-circuits on Err, returning Err early)\n");

    std::printf("\nCross-language alignment (expected <-> Result <-> (T,error)):\n");
    std::printf("    C++23 std::optional<T>      ==  Rust Option<T>   (Some|None)\n");
    std::printf("    C++23 std::expected<T,E>    ==  Rust Result<T,E> (Ok|Err) + `?`\n");
    std::printf("    Go (T, error)               ==  same error-as-value idea, runtime-only\n");
    std::printf("    ENFORCEMENT: Rust = compile time; C++/Go = trust (+UB if you lie in C++)\n");

    check("pipeline(10) == Ok(6)", ok.has_value() && ok.value() == 6);
    check("pipeline(0) succeeds (0/2=0, +1=1)", err.has_value() && err.value() == 1);
    check("error short-circuits the .and_then chain (== Rust ?)",
          !err2.has_value() && err2.error() == DivErr::ZeroDivisor);
}

}  // namespace

int main() {
    std::printf("std_expected_optional.cpp — Phase 7 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
