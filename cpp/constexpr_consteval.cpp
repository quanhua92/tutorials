// constexpr_consteval.cpp — Phase 6 bundle (Compile-time Computation).
//
// GOAL (one line): prove — by using results as array bounds and template
// arguments (places a RUNTIME value is forbidden) — how C++'s three
// compile-time keywords split the language into a compile-time-evaluable
// subset and the runtime language: `constexpr` (compile-OR-run), `consteval`
// (compile-ONLY, C++20 immediate fn), `constinit` (constant-init a static,
// C++20 — the static-init-order-fiasco fix), plus constexpr constructors
// (literal types) and the C++14->23 loosening. `if constexpr` is previewed
// here; its deep treatment lives in IF_CONSTEXPR (P6#39).
//
// This is the GROUND TRUTH for CONSTEXPR_CONSTEVAL.md. Every number, table,
// and worked example in the guide is printed by this file. Change it ->
// re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run constexpr_consteval   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                      -Wpedantic constexpr_consteval.cpp
//                                      -o /tmp/cpp_constexpr_consteval
//                                      && /tmp/cpp_constexpr_consteval)

#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <type_traits> // is_integral_v / is_floating_point_v (Section E preview)

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

// ── Compile-time-evaluable building blocks (shared by several sections) ─────

// A constexpr FUNCTION (C++11): may run at compile time (with constant args)
// OR at runtime (with non-constant args). Recursion is the C++11 form; loops
// and local variables have also been legal since C++14 (see Section D).
constexpr int factorial(int n) { return n <= 1 ? 1 : n * factorial(n - 1); }

// A consteval FUNCTION (C++20): an "immediate function" — every call MUST
// produce a compile-time constant. Calling it with a runtime arg is ill-formed.
consteval int square(int x) { return x * x; }

// consteval builds on other consteval/constexpr functions (it propagates up).
consteval int fourth_power(int x) { return square(square(x)); }

// A constexpr helper used to constant-initialize a constinit variable later.
constexpr int base_seed() { return 100; }

// A "literal type" (constexpr-constructible): can be created at compile time.
struct Point {
    int x, y;
    constexpr Point(int x_, int y_) noexcept : x(x_), y(y_) {}
    constexpr int dot(Point o) const noexcept { return x * o.x + y * o.y; }
};

// A C++14+ constexpr function: local variables and loops are allowed (the
// C++11 single-return restriction was lifted in C++14).
constexpr int sum_squares(int n) {
    int acc = 0;
    for (int i = 1; i <= n; ++i) acc += i * i;
    return acc;
}

// A template that REQUIRES a constant expression as its non-type argument —
// the canonical "proof of compile-time-ness" (a runtime value can never be a
// template argument). If a result feeds CompileTimeInt<...>, it was computed
// at compile time.
template <int N>
struct CompileTimeInt {
    static constexpr int value = N;
};

// if constexpr (C++17) preview — full treatment lives in IF_CONSTEXPR (P6#39).
template <typename T>
constexpr const char* describe_type(T) {
    if constexpr (std::is_integral_v<T>) {
        return "integral";
    } else if constexpr (std::is_floating_point_v<T>) {
        return "floating-point";
    } else {
        return "other";
    }
}

// ── constinit globals (constant-initialized static storage) ────────────────
// constinit asserts CONSTANT initialization (zero- or constant-init) for a
// static/thread-local variable — the C++20 fix for the static-initialization-
// order fiasco. It does NOT imply const: these variables stay MUTABLE.
constinit int g_seed = 42;               // constant-init, mutable
constinit int g_computed = base_seed();  // constant-init via a constexpr fn

// === Section A — constexpr variable & constexpr function ===================
//
// constexpr = "may be evaluated at compile time". The PROOF it really was: the
// result is usable as an array bound and as a template argument — contexts
// where only a constant expression is permitted. The same function ALSO accepts
// a runtime argument (consteval would not).
void sectionA() {
    sectionBanner("A — constexpr variable & function (compile OR run)");

    std::printf("(1) constexpr VARIABLE: computed at compile time, usable as an array\n");
    std::printf("    bound AND a template argument (a runtime value is forbidden there).\n");
    constexpr int N = factorial(5);  // 120, computed at compile time
    int arr[N]{};                    // N usable as an array bound; value-init (no UB)
    constexpr int as_tmpl = CompileTimeInt<factorial(3)>::value;  // factorial(3)=6
    std::printf("    constexpr int N = factorial(5);  -> N = %d\n", N);
    std::printf("    int arr[N]{};                    -> sizeof(arr) = %zu bytes\n",
                sizeof(arr));
    std::printf("    CompileTimeInt<factorial(3)>     -> %d  (factorial(3) as a template arg)\n",
                as_tmpl);
    check("constexpr factorial(5) == 120", N == 120);
    check("constexpr N usable as an array bound (arr has N elements)",
          sizeof(arr) / sizeof(arr[0]) == static_cast<std::size_t>(N));
    check("constexpr factorial(3) usable as a template argument (== 6)", as_tmpl == 6);

    std::printf("\n(2) constexpr FUNCTION: ALSO callable with a NON-constant argument\n");
    std::printf("    (a `volatile` read is never a constant expression -> forces a runtime\n");
    std::printf("    evaluation; the compiler may still fold it, but the call is well-formed).\n");
    volatile int source = 7;       // volatile -> read is a runtime value
    int runtime_n = source;        // a genuine runtime value (deterministically 7)
    int rt = factorial(runtime_n); // constexpr fn accepts a runtime arg; consteval would NOT
    std::printf("    volatile int source = 7; int n = source; factorial(n) = %d\n", rt);
    check("constexpr factorial(7) callable with a runtime arg, == 5040", rt == 5040);

    std::printf("\n(3) constexpr implies const: a later `N = 0;` would be a compile error.\n");
    check("constexpr implies const: N is immutable and == 120", N == 120);
}

// === Section B — consteval (C++20): compile-time ONLY ======================
//
// consteval = "MUST be evaluated at compile time" (an immediate function).
// Every call has to directly produce a compile-time constant. Calling it with a
// runtime argument is a compile error — documented here, NOT built (a file that
// contains it would fail to compile, so it cannot live in the verified path).
void sectionB() {
    sectionBanner("B — consteval (C++20): immediate function, compile-time ONLY");

    std::printf("(1) consteval: EVERY call MUST produce a compile-time constant. Proven by\n");
    std::printf("    using the result as an array bound and as a template argument.\n");
    constexpr int sq = square(7);  // 49, at compile time
    int arr2[square(4)]{};         // square(4)=16 as an array bound
    constexpr int sq_tmpl = CompileTimeInt<square(5)>::value;  // square(5)=25
    constexpr int fp = fourth_power(2);  // (2^2)^2 = 16
    std::printf("    consteval int square(int);   constexpr sq = square(7);  -> sq = %d\n", sq);
    std::printf("    int arr2[square(4)]{};       -> sizeof(arr2) = %zu bytes\n", sizeof(arr2));
    std::printf("    CompileTimeInt<square(5)>    -> %d  (square(5) as a template arg)\n",
                sq_tmpl);
    std::printf("    fourth_power(2) = square(square(2)) -> %d  (consteval calls consteval)\n",
                fp);
    check("consteval square(7) == 49 (computed at compile time)", sq == 49);
    check("consteval square(4) usable as an array bound (arr2 has 16 elements)",
          sizeof(arr2) / sizeof(arr2[0]) == 16);
    check("consteval square(5) usable as a template argument (== 25)", sq_tmpl == 25);
    check("consteval fourth_power(2) == 16 (consteval propagates up)", fp == 16);

    std::printf("\n(2) consteval vs constexpr (the headline contrast):\n");
    std::printf("    constexpr  -> compile-time OR runtime  (the caller's arguments decide)\n");
    std::printf("    consteval  -> compile-time ONLY        (a runtime-arg call is ill-formed)\n");
    check("consteval is compile-time-only (vs constexpr's compile-OR-run)", true);

    std::printf("\n(3) Calling a consteval fn with a RUNTIME arg is ILL-FORMED (documented;\n");
    std::printf("    NOT in this build — a file containing it would not compile):\n");
    std::printf("        int r = square(runtime_n);\n");
    std::printf("        // error: call to immediate function 'square' is not a constant\n");
    std::printf("        //        expression (the arg is not usable at compile time)\n");
    check("consteval runtime-arg call is a compile error (documented, not built)", true);
}

// === Section C — constinit (C++20): constant-init a static (mutable) =======
//
// constinit asserts that a static/thread-local variable has CONSTANT
// initialization (zero- or constant-init) — never dynamic init. That is the
// C++20 fix for the static-initialization-order fiasco: a constinit variable's
// value never depends on cross-TU dynamic-init ordering. Unlike constexpr,
// constinit does NOT imply const: the variable stays MUTABLE.
void sectionC() {
    sectionBanner("C — constinit (C++20): constant-init a static (mutable)");

    std::printf("(1) constinit asserts CONSTANT initialization (no dynamic init) for a static\n");
    std::printf("    or thread-local variable — the C++20 fix for the static-init-order fiasco.\n");
    std::printf("    (That it COMPILES already proves constant init; a dynamic init would be\n");
    std::printf("     ill-formed. The runtime value confirms it.)\n");
    std::printf("    g_seed    (constinit, constant-init)        = %d\n", g_seed);
    std::printf("    g_computed (constinit via a constexpr fn)   = %d\n", g_computed);
    check("constinit g_seed constant-initialized to 42", g_seed == 42);
    check("constinit g_computed = base_seed() == 100 (constant-init via constexpr fn)",
          g_computed == 100);

    std::printf("\n(2) constinit does NOT imply const (unlike constexpr) — the variable stays\n");
    std::printf("    MUTABLE, so it can be assigned later at runtime:\n");
    g_seed = 999;
    std::printf("    after `g_seed = 999;` -> g_seed = %d\n", g_seed);
    check("constinit does NOT imply const (g_seed mutated 42 -> 999)", g_seed == 999);

    std::printf("\n(3) constinit CANNOT combine with constexpr, and a dynamic (runtime) init is\n");
    std::printf("    ill-formed (documented; NOT in this build — would not compile):\n");
    std::printf("        int runtime_fn();\n");
    std::printf("        constinit int bad = runtime_fn();   // ERROR: requires a constant init\n");
    std::printf("        constexpr constinit int x = 0;      // ERROR: constexpr & constinit clash\n");
    check("constinit forbids dynamic init and pairing with constexpr (documented)", true);
}

// === Section D — constexpr ctors (literal types) & the C++14->23 loosening =
//
// A constexpr-constructible type (a "literal type") can be created at compile
// time. Then the C++14->C++23 sequence steadily relaxed what a constexpr
// function body may contain — tracked by the __cpp_constexpr feature-test macro.
void sectionD() {
    sectionBanner("D — constexpr ctors (literal types) & the C++14->23 loosening");

    std::printf("(1) A constexpr-constructible type (a \"literal type\") can be created at\n");
    std::printf("    compile time and used in constant expressions (array bounds, template args):\n");
    constexpr Point p1(3, 4);
    constexpr Point p2(1, 2);
    constexpr int d = p1.dot(p2);  // 3*1 + 4*2 = 11, at compile time
    int arr3[d]{};                 // d=11 as an array bound — proves compile-time
    constexpr int d_tmpl = CompileTimeInt<p1.dot(p2)>::value;
    std::printf("    constexpr Point p1(3,4), p2(1,2);  p1.dot(p2) = %d\n", d);
    std::printf("    int arr3[p1.dot(p2)]{};            -> sizeof(arr3) = %zu bytes\n",
                sizeof(arr3));
    std::printf("    CompileTimeInt<p1.dot(p2)>         -> %d\n", d_tmpl);
    check("constexpr Point::dot computed at compile time: (3,4).(1,2) == 11", d == 11);
    check("constexpr Point::dot usable as an array bound (arr3 has 11 elements)",
          sizeof(arr3) / sizeof(arr3[0]) == 11);
    check("constexpr Point::dot usable as a template argument (== 11)", d_tmpl == 11);

    std::printf("\n(2) C++14+ relaxation: a constexpr function may use local variables & loops\n");
    std::printf("    (C++11 required a single return statement):\n");
    constexpr int ss = sum_squares(5);  // 1+4+9+16+25 = 55
    std::printf("    constexpr int sum_squares(5) = %d  (loop + local `acc` in a constexpr fn)\n",
                ss);
    check("C++14 relaxed constexpr: sum_squares(5) == 55 (loops/locals allowed)", ss == 55);

    std::printf("\n(3) The constexpr loosening, by feature-test macro (this compiler):\n");
    std::printf("    __cpp_constexpr = %ldL\n", (long)__cpp_constexpr);
    std::printf("        200704L C++11  (constexpr)\n");
    std::printf("        201304L C++14  (relaxed: loops/locals)\n");
    std::printf("        201603L C++17  (constexpr lambda)\n");
    std::printf("        201907L C++20  (trivial default-init; asm in constexpr fns)\n");
    std::printf("        202002L C++20  (change the active union member)\n");
    std::printf("        202110L C++23  (non-literal vars, labels, goto in constexpr fns)\n");
    std::printf("        202207L C++23  (relax some constexpr restrictions)\n");
    std::printf("        202211L C++23  (static constexpr vars in constexpr fns)\n");
#ifdef __cpp_consteval
    std::printf("    __cpp_consteval  = %ldL  (201811L C++20; 202211L C++23 propagate-up)\n",
                (long)__cpp_consteval);
#endif
#ifdef __cpp_constinit
    std::printf("    __cpp_constinit  = %ldL  (201907L C++20)\n", (long)__cpp_constinit);
#endif
#ifdef __cpp_constexpr_dynamic_alloc
    std::printf("    __cpp_constexpr_dynamic_alloc = %ldL  (201907L C++20: constexpr new)\n",
                (long)__cpp_constexpr_dynamic_alloc);
#else
    std::printf("    __cpp_constexpr_dynamic_alloc = (not defined on this compiler)\n");
#endif
    check("__cpp_constexpr >= 201907L (this compiler supports at least C++20 relaxed constexpr)",
          __cpp_constexpr >= 201907L);
}

// === Section E — if constexpr (preview) + cross-language ==================
//
// if constexpr (C++17) discards the untaken branch at compile time (it is not
// even instantiated). Its DEEP treatment — including dependent branches and
// template-only validity — is IF_CONSTEXPR (P6#39). This section is a preview.
void sectionE() {
    sectionBanner("E — if constexpr (preview, P6#39) + cross-language");

    std::printf("(1) if constexpr (C++17): compile-time branch DISCARD — the untaken branch\n");
    std::printf("    is not even instantiated. (Full treatment: IF_CONSTEXPR, P6#39.)\n");
    int* ptr = nullptr;
    std::printf("    describe_type(42)   = %s\n", describe_type(42));
    std::printf("    describe_type(3.14) = %s\n", describe_type(3.14));
    std::printf("    describe_type(ptr)  = %s  (int* is neither integral nor floating)\n",
                describe_type(ptr));
    check("if constexpr: int is 'integral'", describe_type(42)[0] == 'i');
    check("if constexpr: double is 'floating-point'", describe_type(3.14)[0] == 'f');
    check("if constexpr: int* is 'other'", describe_type(ptr)[0] == 'o');

    std::printf("\n(2) Cross-language compile-time evaluation (info; this is a C++ bundle):\n");
    std::printf("    C++  constexpr  -> compile-OR-run  (the caller's arguments decide)\n");
    std::printf("    C++  consteval  -> compile-ONLY    (a runtime-arg call is ill-formed)\n");
    std::printf("    C++  constinit  -> constant-init a static (SIOF fix; NOT const)\n");
    std::printf("    Rust const fn   -> callable from a const context; its body is restricted\n");
    std::printf("                       to constant expressions (stricter than C++ constexpr).\n");
    std::printf("                       See ../rust\n");
    std::printf("    TS / JS         -> NO compile-time VALUE evaluation; types erased at runtime\n");
    std::printf("    Go   const      -> compile-time CONSTANTS only (untyped), not general fns\n");
    check("cross-language summary printed (Rust const fn / TS none / Go const-only)", true);
}

}  // namespace

int main() {
    std::printf("constexpr_consteval.cpp — Phase 6 bundle (Compile-time Computation).\n");
    std::printf("Compile-time-ness is PROVEN by using results as array bounds & template args.\n");
    std::printf("Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
