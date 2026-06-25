// errors_exceptions_intro.cpp — Phase 1 bundle (intro to exceptions).
//
// GOAL (one line): show, by printing every value, how C++'s throw/try/catch
// exception machinery behaves — the std::exception hierarchy (.what()), stack
// UNWINDING (dtors run during propagation = RAII cleanup), the catch-by-value
// SLICING trap, re-throw (`throw;` preserves type vs `throw e;` slices), noexcept
// (preview), and how exceptions differ from error codes (std::expected) — pinning
// "catch by const reference" as the expert payoff.
//
// This is the GROUND TRUTH for ERRORS_EXCEPTIONS_INTRO.md. Every value, message,
// and [check] below is printed by this file. Change it -> re-compile -> re-paste.
// Never hand-compute.
//
// SAFETY NOTE: EVERY throw in the verified path is caught (no uncaught exception
// -> std::terminate). The noexcept-violation -> std::terminate path is DOCUMENTED
// (Section D) but never executed here: a program that calls its own noexcept-
// violator cannot continue (std::terminate ends it). See the .md "verified by
// reference" note, mirroring how values_types.cpp documents (never runs) UB.
//
// Run:
//     just run errors_exceptions_intro
//         (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//             errors_exceptions_intro.cpp -o /tmp/cpp_errors_exceptions_intro
//             && /tmp/cpp_errors_exceptions_intro)

#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar) + strcmp
#include <exception>   // std::exception (the hierarchy root)
#include <expected>    // std::expected (C++23) — the Result-like error-code path
#include <stdexcept>   // std::runtime_error / std::logic_error / std::out_of_range
#include <string>      // std::string (custom exception message composition)
#include <typeinfo>    // typeid (slicing detection — names are NOT printed, only compared)

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

// A custom exception class: derive from std::runtime_error (the idiomatic base),
// carry an extra field (line_), and OVERRIDE what() to compose a richer message.
// The stored std::string msg_ keeps the returned const char* valid for the
// object's lifetime (what() is `const noexcept`, so it must never throw).
class ParseError : public std::runtime_error {
public:
    ParseError(const std::string& what, int line)
        : std::runtime_error(what), line_(line), msg_(what + " @line " + std::to_string(line)) {}

    const char* what() const noexcept override { return msg_.c_str(); }
    int line() const noexcept { return line_; }

private:
    int line_;
    std::string msg_;
};

// A function that MAY throw (not declared noexcept). Used to query the noexcept
// operator (Section D). Called with a safe argument so the verified path never
// actually throws from here.
int maybeThrow(int x) {
    if (x < 0) throw std::runtime_error("negative input");
    return x * 2;
}

// A function declared noexcept: it PROMISES not to throw. If it did, the runtime
// would call std::terminate (documented in Section D, never executed here).
int neverThrows(int x) noexcept { return x + 1; }

// The std::expected (C++23) error-code path: instead of throwing, RETURN either a
// value or an error. No control-flow jump; the caller MUST inspect the result
// (like Rust's Result<T,E> — see Section E / the .md cross-language table).
enum class DivError { ZeroDivisor };

std::expected<int, DivError> safeDiv(int a, int b) {
    if (b == 0) return std::unexpected(DivError::ZeroDivisor);  // early return, no division
    return a / b;
}

// === Section A — throw + try/catch (const ref) + the std::exception hierarchy ==
//
// throw constructs an exception OBJECT (dynamic storage duration, allocated by
// the runtime) and transfers control UP the call stack to a matching handler. By
// convention the object derives from std::exception, whose hierarchy is:
//   std::exception
//     |- std::logic_error   -> std::invalid_argument / std::domain_error
//     |                       std::length_error / std::out_of_range
//     |- std::runtime_error -> std::range_error / std::overflow_error
//     |                       std::underflow_error
//     |- std::bad_alloc  std::bad_cast  std::bad_typeid  std::bad_exception ...
// NOTE: std::out_of_range derives from std::logic_error, NOT std::runtime_error.
// Catch by CONST REFERENCE to avoid copying AND (Section C) object slicing.
void sectionA() {
    sectionBanner("A — throw / try / catch & the std::exception hierarchy");

    std::printf("1) throw std::runtime_error(\"divisor is zero\");  caught by const ref:\n");
    std::string caught_what;
    try {
        throw std::runtime_error("divisor is zero");
    } catch (const std::runtime_error& e) {
        caught_what = e.what();
        std::printf("   caught const std::runtime_error& : what() = \"%s\"\n", e.what());
    }
    check("thrown std::runtime_error was caught", !caught_what.empty());
    check("caught what() matches the thrown message (strcmp == 0)",
          std::strcmp(caught_what.c_str(), "divisor is zero") == 0);

    // Catching the BASE std::exception catches ANY derived type (is-a). We throw
    // std::out_of_range (a std::logic_error) and catch it as the base.
    std::printf("\n2) throw std::out_of_range(\"idx 42\");  caught as the BASE std::exception:\n");
    std::string base_what;
    try {
        throw std::out_of_range("idx 42");
    } catch (const std::exception& e) {  // base catches derived
        base_what = e.what();
        std::printf("   caught const std::exception& (base): what() = \"%s\"\n", e.what());
    }
    check("catching base std::exception caught the derived std::out_of_range",
          std::strcmp(base_what.c_str(), "idx 42") == 0);

    // .what() returns a const char* (the explanatory string). It is virtual, so a
    // base-reference dispatches to the DERIVED what(). runtime_error/logic_error
    // store the string you passed to their constructor; a default std::exception's
    // what() is implementation-defined, so never assert its text.
    std::printf("\n3) what() is virtual const char*; a base-ref dispatches to the derived:\n");
    std::printf("   std::runtime_error(\"x\").what()  -> \"%s\"\n", std::runtime_error("x").what());
    std::printf("   std::logic_error(\"y\").what()    -> \"%s\"\n", std::logic_error("y").what());
    check("runtime_error(\"x\").what() == \"x\"",
          std::strcmp(std::runtime_error("x").what(), "x") == 0);
    check("logic_error(\"y\").what() == \"y\"",
          std::strcmp(std::logic_error("y").what(), "y") == 0);
}

// === Section B — stack UNWINDING: dtors run during propagation; catch-all + re-throw
//
// When a throw happens, control unwinds UP the call stack toward a matching
// handler. For EVERY fully-constructed automatic object between the throw and the
// catch, the DESTRUCTOR runs — in REVERSE order of construction. This is RAII
// cleanup firing automatically: resources are released even on the error path.
void sectionB() {
    sectionBanner("B — stack unwinding (dtors run), catch-all & re-throw");

    // Three local Loggers, constructed A,B,C. The throw escapes `run`; as it does,
    // ~Logger fires for c,b,a in REVERSE order -> the log appends "CBA".
    std::printf("1) throw inside a frame with 3 local Loggers -> dtors run C,B,A:\n");
    auto run = [](std::string* log) {
        struct Logger {
            std::string* out;
            char tag;
            Logger(std::string* o, char t) : out(o), tag(t) {}
            ~Logger() {
                if (out) out->push_back(tag);
            }
        };
        Logger a(log, 'A');
        Logger b(log, 'B');
        Logger c(log, 'C');
        throw std::runtime_error("unwind me");
    };

    std::string dtor_order;
    try {
        run(&dtor_order);
    } catch (const std::runtime_error& e) {
        std::printf("   caught: \"%s\"; dtor log = \"%s\"\n", e.what(), dtor_order.c_str());
    }
    check("stack unwinding ran dtors in REVERSE order (C, B, A)", dtor_order == "CBA");

    // catch-all `catch (...)` catches ANY exception type, but you get NO object
    // (no what(), no typeid). It is mainly a cleanup/translation backstop.
    bool caught_all = false;
    try {
        throw 42;  // throwing a bare int is legal but discouraged (see pitfalls)
    } catch (...) {
        caught_all = true;
    }
    check("catch (...) caught a thrown int (no object accessible)", caught_all);

    // re-throw with `throw;` RE-ACTIVATES the current exception object — the
    // ORIGINAL (derived) type is preserved (no slicing). `throw e;` instead
    // copy-constructs a NEW base object -> SLICED. Proven below via typeid (we
    // only COMPARE types, never print the impl-defined type_info::name()).
    std::printf("\n2) re-throw `throw;` preserves type; `throw e;` SLICES:\n");
    std::string kind_semi;
    try {
        try {
            throw std::out_of_range("orig");
        } catch (const std::exception&) {
            throw;  // re-throws the ORIGINAL out_of_range object
        }
    } catch (const std::exception& e2) {
        kind_semi = (typeid(e2) == typeid(std::out_of_range)) ? "out_of_range" : "sliced";
        std::printf("   throw;  -> outer catches typeid == %s\n", kind_semi.c_str());
    }
    check("throw; preserved the derived type (out_of_range)", kind_semi == "out_of_range");

    std::string kind_expr;
    try {
        try {
            throw std::out_of_range("orig");
        } catch (const std::exception& e) {
            throw e;  // copy-constructs a NEW std::exception object -> SLICED
        }
    } catch (const std::exception& e2) {
        kind_expr = (typeid(e2) == typeid(std::out_of_range)) ? "out_of_range" : "sliced";
        std::printf("   throw e; -> outer catches typeid == %s\n", kind_expr.c_str());
    }
    check("throw e; SLICED the exception to base std::exception", kind_expr == "sliced");
}

// === Section C — the SLICING trap + custom exception classes ==================
//
// Catching a DERIVED exception BY VALUE copies only the BASE subobject; the
// derived part (its data + its overridden what()) is sliced off. The fix is
// always: catch by const reference.
void sectionC() {
    sectionBanner("C — the catch-by-value SLICING trap & custom exceptions");

    std::printf("1) throw std::out_of_range; compare by-value vs by-reference:\n");
    std::printf("   catch(std::exception e)        <- BY VALUE: derived part sliced\n");
    std::printf("   catch(const std::exception& e) <- BY REF:   dynamic type preserved\n");

    bool by_value_sliced = false;
    try {
        throw std::out_of_range("k");
    } catch (std::exception e) {  // BY VALUE -> sliced to std::exception
        by_value_sliced = (typeid(e) == typeid(std::exception));
    }
    check("catch-by-VALUE sliced: dynamic typeid == std::exception", by_value_sliced);

    bool by_ref_preserved = false;
    try {
        throw std::out_of_range("k");
    } catch (const std::exception& e) {  // BY REF -> not sliced
        by_ref_preserved = (typeid(e) == typeid(std::out_of_range));
    }
    check("catch-by-REFERENCE preserved: typeid still std::out_of_range", by_ref_preserved);

    // A custom exception: derive from std::runtime_error, add a field, override
    // what(). Caught polymorphically via a base reference -> the OVERRIDDEN what()
    // runs (virtual dispatch), and the derived's own members are reachable.
    std::printf("\n2) custom ParseError(\"bad token\", 42); caught as derived & base:\n");
    std::string custom_what;
    int custom_line = -1;
    try {
        throw ParseError("bad token", 42);
    } catch (const ParseError& e) {
        custom_what = e.what();
        custom_line = e.line();
        std::printf("   caught const ParseError&: what()=\"%s\"  line=%d\n", e.what(), e.line());
    }
    check("custom ParseError caught as its own (derived) type", custom_line == 42);
    check("ParseError::what() composed the message (\"bad token @line 42\")",
          custom_what == "bad token @line 42");

    // The SAME throw, caught by the BASE std::runtime_error&: virtual dispatch
    // still reaches the overridden what() — polymorphism survives the hierarchy.
    std::string base_custom_what;
    try {
        throw ParseError("bad token", 42);
    } catch (const std::runtime_error& e) {  // base ref -> OVERRIDDEN what() runs
        base_custom_what = e.what();
        std::printf("   caught const std::runtime_error& (base): what()=\"%s\"\n", e.what());
    }
    check("base std::runtime_error& dispatched to OVERRIDDEN what() (polymorphic)",
          base_custom_what == "bad token @line 42");

    // The slicing payoff, concretely: catch ParseError BY VALUE as std::runtime_error
    // -> the msg_/line_ members vanish; what() falls back to the BASE message only.
    std::printf("\n3) catch ParseError BY VALUE as std::runtime_error -> what() sliced:\n");
    std::string sliced_what;
    try {
        throw ParseError("bad token", 42);
    } catch (std::runtime_error e) {  // BY VALUE -> sliced
        sliced_what = e.what();
        std::printf("   caught std::runtime_error e (by value): what()=\"%s\"\n", e.what());
    }
    check("catch-by-VALUE sliced ParseError: what() lost the @line 42 part",
          sliced_what == "bad token");
}

// === Section D — noexcept (preview) + the cost model =========================
//
// `noexcept` on a DECLARATION is a PROMISE: the function will not throw. If it
// does, the runtime calls std::terminate (-> std::abort): there is no catch.
// Destructors are implicitly noexcept since C++11, which is what makes the
// stack-unwinding cleanup of Section B safe to rely on. Full depth (the four
// exception-safety guarantees, conditional noexcept, move-if-noexcept, the actual
// throwing cost) lands in EXCEPTIONS_DEEP (Phase 7).
void sectionD() {
    sectionBanner("D — noexcept specifier/operator (preview) & the cost model");

    std::printf("1) the noexcept SPECIFIER is a non-throwing promise:\n");
    std::printf("   int neverThrows(int) noexcept;   // if it threw -> std::terminate\n");
    std::printf("   int maybeThrow(int);             // not noexcept (may throw)\n");
    // Call both with safe inputs so the verified path never throws.
    std::printf("   neverThrows(41) = %d ;  maybeThrow(21) = %d\n", neverThrows(41), maybeThrow(21));

    // The noexcept OPERATOR (noexcept(expr)) is a COMPILE-TIME bool query: does the
    // expression's call sequence contain a (non-noexcept) potentially-throwing call?
    // It does NOT evaluate expr (unevaluated operand) — a pure type query.
    std::printf("\n2) the noexcept OPERATOR (compile-time query, unevaluated):\n");
    std::printf("   noexcept(neverThrows(0)) = %d   (declared noexcept)\n",
                static_cast<int>(noexcept(neverThrows(0))));
    std::printf("   noexcept(maybeThrow(0))  = %d   (body can throw)\n",
                static_cast<int>(noexcept(maybeThrow(0))));
    check("noexcept(neverThrows(0)) == true (declared noexcept)", noexcept(neverThrows(0)));
    check("noexcept(maybeThrow(0)) == false (its body can throw)", !noexcept(maybeThrow(0)));

    // noexcept(expr) takes a bool: `noexcept(false)` / `noexcept(true)` make the
    // promise CONDITIONAL on another expression's noexcept-ness (a constexpr bool).
    constexpr bool promise = noexcept(neverThrows(0));
    check("noexcept(neverThrows(0)) is a constexpr bool == true", promise);

    // COST MODEL (documented — not measured, since timing is non-deterministic):
    // The Itanium C++ ABI (Unix/macOS) and 64-bit SEH (Windows) use a "zero-cost"
    // exception model: the NOT-thrown path has NO per-try/catch runtime overhead;
    // the cost is paid only when an exception is actually thrown (unwinding-table
    // walk + handler lookup), plus BINARY SIZE for the unwind tables. This is the
    // opposite of older setjmp/longjmp ("SJLJ") models where every try costs a
    // little at runtime. Full depth lands in EXCEPTIONS_DEEP (P7).
    std::printf("\n3) cost model: zero-cost-when-NOT-thrown on this ABI (Itanium C++ ABI);\n");
    std::printf("   the thrown path pays unwinding + handler lookup; tables add .text size.\n");
    check("cost model documented (not measured): zero-cost-when-not-thrown", true);

    // std::terminate path (DOCUMENTED, never executed in the verified path — see
    // the file header). A function marked noexcept that throws, OR an uncaught
    // exception, OR an exception escaping a destructor DURING unwinding, calls
    // std::terminate -> std::abort. We never leave such a throw live here.
    std::printf("\n4) std::terminate: noexcept-violation / uncaught / throw-in-dtor-during-unwind\n");
    std::printf("   -> std::terminate() -> std::abort. (Documented; not run — ends the program.)\n");
    check("std::terminate path documented (not executed; it ends the program)", true);
}

// === Section E — exceptions vs error codes (std::expected) & cross-language ====
void sectionE() {
    sectionBanner("E — exceptions vs error codes (std::expected) & cross-language");

    // The two error-signaling philosophies in C++:
    //  (a) THROW an exception — control jumps to a handler; the happy path stays
    //      uncluttered; zero-cost-when-not-thrown (Section D).
    //  (b) RETURN an error — std::expected<T,E> (C++23) carries either a value or
    //      an error; the caller MUST inspect it (no silent ignore); no jump.
    // std::expected is C++'s Rust-Result<T,E> analog; std::error_code/std::error
    // _condition are the older C-ish pair. The SAME divide, both ways:
    std::printf("1) safeDiv via std::expected<int, DivError> (the error-code path):\n");
    std::printf("   safeDiv(10, 2) -> ");
    auto r1 = safeDiv(10, 2);
    if (r1.has_value()) std::printf("value %d\n", *r1);
    std::printf("   safeDiv(10, 0) -> ");
    auto r2 = safeDiv(10, 0);
    if (!r2.has_value()) std::printf("error DivError::ZeroDivisor (no throw, no jump)\n");

    check("std::expected: 10/2 == 5 (value present)", r1.has_value() && *r1 == 5);
    check("std::expected: 10/0 is an error (b == 0 checked BEFORE the division)",
          !r2.has_value() && r2.error() == DivError::ZeroDivisor);

    // The SAME divide, the THROW path — same outcome, very different control flow:
    auto divOrThrow = [](int a, int b) -> int {
        if (b == 0) throw std::runtime_error("div by zero");
        return a / b;
    };
    std::printf("\n2) the SAME divide, the throw path (divOrThrow(10, 0) throws):\n");
    std::string thrown;
    try {
        divOrThrow(10, 0);
    } catch (const std::runtime_error& e) {
        thrown = e.what();
        std::printf("   caught: \"%s\"\n", e.what());
    }
    check("throw path: div by zero was caught",
          std::strcmp(thrown.c_str(), "div by zero") == 0);

    // Cross-language map (the 5-language curriculum). C++ is structurally closest
    // to TS/Python (throw-based) and the OPPOSITE of Go (return errors) / Rust
    // (Result + ?). See the .md cross-references table.
    std::printf("\n3) cross-language error signaling:\n");
    std::printf("   C++ / TS / Python : throw / try / catch     (control-flow JUMP)\n");
    std::printf("   Go                : return error, if err != nil (EXPLICIT, no throw)\n");
    std::printf("   Rust              : Result<T,E> + ?         (typed, FORCED handling)\n");
    check("cross-language map documented (C++ closest to TS/Python throw-based)", true);
}

}  // namespace

int main() {
    std::printf("errors_exceptions_intro.cpp — Phase 1 bundle (intro to exceptions).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23 -O2\n");
    std::printf("-Wall -Wextra -Wpedantic; UB-free (just sanitize clean); every throw caught.\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
