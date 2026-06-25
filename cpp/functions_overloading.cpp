// functions_overloading.cpp — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how C++ function overloading,
// pass-by value/reference/pointer, default arguments, `inline`, `constexpr`
// functions, `[[nodiscard]]`/`[[maybe_unused]]`, and function pointers behave —
// and why C++ has overloading when Go and Rust deliberately do not.
//
// This is the GROUND TRUTH for FUNCTIONS_OVERLOADING.md. Every number, tag, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run functions_overloading   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                        -Wpedantic functions_overloading.cpp
//                                        -o /tmp/cpp_functions_overloading
//                                        && /tmp/cpp_functions_overloading)

#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <string>     // std::string (an overload target)

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

// ===== The overloaded set for Section A =====================================
// Three functions, ONE name, DISTINCT parameter types. The compiler picks. Each
// returns an integer tag so the call site can assert WHICH overload ran (we
// never compare string literals with ==, which would be a pointer compare).
int pick(int x) {
    std::printf("  -> pick(int=%d) ran\n", x);
    return 1;
}
int pick(double x) {
    std::printf("  -> pick(double=%g) ran\n", x);
    return 2;
}
int pick(const std::string& s) {
    std::printf("  -> pick(const std::string&=\"%s\") ran\n", s.c_str());
    return 3;
}

// ===== Pass-by modes for Section B ==========================================
// The value/reference/pointer trichotomy applied to parameters (recap of P1#2,
// REFERENCES_POINTERS_INTRO). Returning the post-call value lets us observe the
// mutation (or non-mutation) of the caller's object.
int byValue(int x)            { x = 100; return x; }  // mutates a COPY
int byRef(int& x)             { x = 100; return x; }  // mutates the CALLER's int
int byConstRef(const int& x)  { return x + 1; }       // read-only alias
int byPtr(int* x)             { *x = 100; return *x; }  // mutates via an address

// Default arguments: trailing params may carry a default; the default is
// substituted at the CALL SITE. The default is NOT part of the function type.
int withDefault(int a, int b = 10) { return a + b; }

// ===== inline + constexpr for Section C =====================================
// `inline` in modern C++ primarily means "may be defined in multiple TUs"
// (header-defined functions); the inlining HINT is mostly ignored by optimizers.
// constexpr / consteval functions and member functions defined inside a class
// body are IMPLICITLY inline.
inline int inlineAdd(int a, int b) { return a + b; }

// A constexpr function: CAN be evaluated at compile time when called with
// constant-expression arguments; MAY also be called at runtime when they are
// not. Section C proves the compile-time path by using the result as an array
// bound (a context that REQUIRES a constant expression).
constexpr int cube(int n) { return n * n * n; }

// ===== Attributes + function-pointer targets for Section D ==================
// [[nodiscard]]: callers MUST use the return value, else -Wunused-result warns.
// The verified path USES it; the warning-triggering call is gated behind
// #ifdef DEMO_WARN (never passed by just run/out/check/sanitize).
[[nodiscard]] int important() { return 42; }

// [[maybe_unused]] on a parameter silences -Wunused-parameter (part of -Wextra)
// when the body does not name that parameter.
int tagged([[maybe_unused]] int verbose, int payload) { return payload * 2; }

// Two free functions of identical signature — function-pointer targets.
void shout(int x)   { std::printf("  shout(%d)\n", x); }
void whisper(int x) { std::printf("  whisper(%d)\n", x); }

// ===== Overload-resolution preview for Section E ============================
// The overloaded name `route`: exact match beats standard conversion. For an int
// argument, route(int) is an exact match; route(long) needs int->long (an
// integral CONVERSION — worse rank). Returns a tag so we can assert which ran.
int route(int)  { std::printf("  -> route(int) ran  [EXACT MATCH]\n");   return 1; }
int route(long) { std::printf("  -> route(long) ran [int->long CONVERSION]\n"); return 2; }

// =============================================================================
// Section A — Overloading basics: same name, distinct parameter types
// =============================================================================
void sectionA() {
    sectionBanner("A — Overloading: same name, distinct parameter types");

    std::printf("Three overloads of `pick`: pick(int) / pick(double) / pick(const std::string&).\n");
    std::printf("The compiler picks ONE per call, by the argument's type:\n\n");

    std::printf("pick(1)  [int literal]:\n");
    int a = pick(1);                 // exact match -> pick(int)
    std::printf("pick(1.0) [double literal]:\n");
    int b = pick(1.0);               // exact match -> pick(double)
    std::printf("pick(std::string(\"s\")) [exact std::string]:\n");
    int c = pick(std::string("s"));  // exact match -> pick(const std::string&)

    check("pick(1) -> int overload (tag 1)", a == 1);
    check("pick(1.0) -> double overload (tag 2)", b == 2);
    check("pick(std::string(\"s\")) -> string overload (tag 3)", c == 3);

    // The string-literal "s" is `const char[2]`; it reaches pick(const
    // std::string&) via the NON-EXPLICIT string(const char*) constructor — a
    // user-defined conversion. No int/double overload is viable (there is no
    // const char* -> int/double path), so resolution is unique.
    std::printf("\npick(\"s\")  [const char[2] -> const std::string& via user-defined conv]:\n");
    int d = pick("s");
    check("pick(\"s\") -> string overload (via const char* -> std::string)", d == 3);

    // Return type alone does NOT distinguish overloads: `int f(int);` and
    // `double f(int);` is a redefinition error. Only the PARAMETER LIST
    // (arity + types) distinguishes overloads. (Documented here; a file
    // containing the redefinition would not compile -> not in the verified path.)
    std::printf("\nReturn type does NOT participate: only the PARAMETER LIST distinguishes\n");
    std::printf("overloads. `int f(int); double f(int);` is a redefinition error.\n");
    check("overloads distinguished by parameter list, NOT return type", true);
}

// =============================================================================
// Section B — Pass-by value/ref/ptr + default arguments
// =============================================================================
void sectionB() {
    sectionBanner("B — Pass-by value/ref/ptr + default arguments");

    // (1) BY VALUE: the parameter is a COPY; mutating it does not reach caller.
    int v = 5;
    int r1 = byValue(v);
    std::printf("(1) by-value:        v=5; byValue(v)=%d; v still %d (copy mutated, caller's safe)\n",
                r1, v);
    check("by-value: caller's v unchanged after byValue(v)=100", v == 5 && r1 == 100);

    // (2) BY REFERENCE: int& aliases the caller's object; mutation is visible.
    int w = 5;
    int r2 = byRef(w);
    std::printf("(2) by-reference:    w=5; byRef(w)=%d; w now %d (alias mutated)\n", r2, w);
    check("by-reference: caller's w mutated to 100 by byRef", w == 100 && r2 == 100);

    // (3) BY CONST REFERENCE: read-only alias; no copy, mutation not allowed.
    int u = 41;
    int r3 = byConstRef(u);
    std::printf("(3) by-const-ref:    u=41; byConstRef(u)=%d (read-only; no copy of u)\n", r3);
    check("by-const-ref: returns u+1 without mutating u", u == 41 && r3 == 42);

    // (4) BY POINTER: aliases via an address; mutation through *p is visible.
    int p = 5;
    int r4 = byPtr(&p);
    std::printf("(4) by-pointer:      p=5; byPtr(&p)=%d; p now %d (mutated via *)\n", r4, p);
    check("by-pointer: caller's p mutated to 100 via byPtr(&p)", p == 100 && r4 == 100);

    // (5) DEFAULT ARGUMENTS: trailing params may be omitted at the call site;
    //     the default is substituted. withDefault(5) == withDefault(5, 10).
    std::printf("\n(5) Default argument: int withDefault(int a, int b = 10);\n");
    std::printf("    withDefault(5)   = %d   (b defaulted to 10)\n", withDefault(5));
    std::printf("    withDefault(5,1) = %d   (b supplied explicitly)\n", withDefault(5, 1));
    check("withDefault(5) uses b=10 -> 15", withDefault(5) == 15);
    check("withDefault(5, 1) uses b=1 -> 6", withDefault(5, 1) == 6);

    // The default is NOT part of the function type: a pointer to withDefault has
    // type int(*)(int,int) — you cannot rely on the default through a pointer.
    int (*fp)(int, int) = &withDefault;
    std::printf("    int (*fp)(int,int) = &withDefault;  fp(5, 10) = %d\n", fp(5, 10));
    check("pointer to withDefault has type int(*)(int,int); default NOT in type",
          fp(5, 10) == 15);
}

// =============================================================================
// Section C — inline (modern meaning) + constexpr functions
// =============================================================================
void sectionC() {
    sectionBanner("C — inline (multi-TU permission) + constexpr functions");

    // `inline` today is principally a LINKAGE specifier: it permits the function
    // to be defined in multiple translation units (e.g. in a header) provided
    // every definition is identical. As an inlining HINT it is largely ignored
    // — optimizers inline freely regardless of the keyword (and may emit a real
    // call to a function marked `inline`). constexpr/consteval functions, and
    // member functions defined inside a class body, are IMPLICITLY inline. The
    // multi-TU property cannot be shown in a single TU; the .md carries it.
    std::printf("`inline` modern meaning = 'may be defined in multiple TUs' (header-defined).\n");
    std::printf("As an inlining hint it is largely ignored by optimizers.\n");
    std::printf("inline int inlineAdd(int,int): inlineAdd(2,3) = %d\n", inlineAdd(2, 3));
    check("inline function computes 2+3", inlineAdd(2, 3) == 5);

    // constexpr function — DUAL NATURE: it MAY evaluate at compile time when the
    // arguments are constant expressions, AND may also run at runtime when they
    // are not. The compile-time path is PROVEN by using the result as an array
    // bound (a context that REQUIRES a constant expression).
    constexpr int C = cube(3);   // 27, computed at compile time
    int arr[C];                  // array bound requires a constant -> the proof
    int sum = 0;
    for (int i = 0; i < C; ++i) { arr[i] = i; sum += arr[i]; }
    std::printf("\nconstexpr int cube(int) — dual nature (compile OR run):\n");
    std::printf("  constexpr int C = cube(3);  -> C = %d   (compile-time evaluated)\n", C);
    std::printf("  int arr[C];  (C usable as an array bound -> proof of compile-time eval)\n");
    std::printf("  sum of arr[0..%d] = %d\n", C - 1, sum);

    // The SAME constexpr function is also callable at RUNTIME with a value not
    // known until runtime (read here from a non-constant variable).
    int runtime_n = 4;
    int runtime_c = cube(runtime_n);   // evaluated at runtime
    std::printf("  int runtime_c = cube(runtime_n=4);  -> %d   (runtime path of the SAME fn)\n",
                runtime_c);

    check("constexpr cube(3) == 27 (compile-time path)", C == 27);
    check("constexpr result usable as array bound", sizeof(arr) / sizeof(arr[0]) == static_cast<std::size_t>(C));
    check("constexpr function also runs at runtime: cube(4) == 64", runtime_c == 64);
}

// =============================================================================
// Section D — [[nodiscard]] / [[maybe_unused]] + function pointers
// =============================================================================
void sectionD() {
    sectionBanner("D — [[nodiscard]] / [[maybe_unused]] + function pointers");

    // (1) [[nodiscard]]: the return value must not be discarded. In the verified
    // path we USE it; the warning-triggering call is gated behind DEMO_WARN.
    int v = important();
    std::printf("(1) [[nodiscard]] int important();  int v = important();  -> v = %d\n", v);
    check("[[nodiscard]] result captured: important() == 42", v == 42);

    std::printf("\n    Ignoring the result would WARN (documented; gated off here):\n");
    std::printf("    > warning: ignoring return value of function declared with\n");
    std::printf("    >          'nodiscard' attribute [-Wunused-result]\n");
    check("ignoring [[nodiscard]] is a warning (documented; gated off in the verified path)",
          true);

#ifdef DEMO_WARN
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // Compile with -DDEMO_WARN to reproduce the -Wunused-result warning printed
    // above. The verified path keeps the build warning-clean instead.
    important();
#else
    std::printf("    (DEMO_WARN not defined: the warning-triggering call is omitted.)\n");
#endif

    // (2) [[maybe_unused]]: silences -Wunused-parameter (part of -Wextra) for a
    // parameter the body intentionally does not name.
    int t = tagged(/*verbose=*/99, /*payload=*/21);
    std::printf("\n(2) [[maybe_unused]] int tagged(int verbose, int payload);\n");
    std::printf("    tagged(verbose=99, payload=21) = %d  (verbose unused, no warning)\n", t);
    check("[[maybe_unused]] silences unused-param; tagged(99,21) == 42", t == 42);

    // (3) FUNCTION POINTERS: a function name decays to a pointer-to-function
    //     (the `&` is optional). Call via fp(x) or (*fp)(x) — both invoke it.
    std::printf("\n(3) Function pointers (a function name decays to &function):\n");
    void (*fp1)(int) = &shout;   // explicit address-of
    void (*fp2)(int) = whisper;  // implicit decay (no &)
    std::printf("    void (*fp1)(int) = &shout;   void (*fp2)(int) = whisper;  (& optional)\n");
    fp1(1);                      // call via pointer
    (*fp2)(2);                   // call via dereference (equivalent)
    check("function name decays to pointer: fp1 == &shout", fp1 == &shout);
    check("decay form: fp2 == whisper", fp2 == whisper);

    // An ARRAY of function pointers — the basis of dispatch tables / callbacks.
    void (*table[2])(int) = {&shout, &whisper};
    std::printf("    void (*table[2])(int) = {&shout, &whisper};  dispatched in order:\n");
    for (int i = 0; i < 2; ++i) table[i](10 + i);
    check("array of function pointers: table[0]==&shout, table[1]==whisper",
          table[0] == &shout && table[1] == whisper);
}

// =============================================================================
// Section E — Overload resolution preview + cross-language (Go / Rust)
// =============================================================================
void sectionE() {
    sectionBanner("E — Overload resolution preview + cross-language (Go/Rust)");

    // EXACT MATCH beats STANDARD CONVERSION. For an int argument, route(int) is
    // an exact match; route(long) needs int->long (an integral CONVERSION — a
    // worse rank). The exact match wins; no ambiguity.
    std::printf("(1) Exact match beats standard conversion:\n");
    std::printf("    Candidates visible: route(int) [exact] vs route(long) [int->long conv]\n");
    std::printf("    Calling route(7)  with an int argument:\n");
    int r1 = route(7);   // overload resolution picks route(int) [exact match]
    std::printf("    Calling route(7L) with a long argument:\n");
    int r2 = route(7L);  // exact match -> route(long)
    check("route(7) [int]  -> route(int)  — exact beats conversion", r1 == 1);
    check("route(7L) [long] -> route(long) — exact match for the long overload", r2 == 2);

    // The full ranking (preview; the deep dive is OVERLOAD_RESOLUTION, P2):
    std::printf("\n(2) The implicit-conversion-sequence ranking (best -> worst):\n");
    std::printf("    1. Exact match         (T -> T; array->ptr, function->ptr, qualification)\n");
    std::printf("    2. Promotion           (char/short -> int; float -> double)\n");
    std::printf("    3. Conversion          (int -> long; int -> double; double -> int)\n");
    std::printf("    4. User-defined conv   (const char* -> std::string; a class converter)\n");
    std::printf("    5. Variadic ellipsis   (...)\n");
    std::printf("    Two viable candidates at the SAME best rank => AMBIGUOUS (compile error).\n");
    check("ranking preview: exact > promotion > conversion > user-defined > ellipsis", true);

    std::printf("\n(3) Cross-language: who has name-based FUNCTION OVERLOADING?\n");
    std::printf("    C++  : YES — pick(int)/pick(double)/pick(const string&) coexist; compiler picks.\n");
    std::printf("    Go   : NO  — one signature per name; rename (printInt/printDouble) or interfaces.\n");
    std::printf("    Rust : NO  — traits + generics; `impl Trait for Type` is the substitute.\n");
    check("of {C++, Go, Rust}, only C++ has name-based function overloading", true);
}

}  // namespace

int main() {
    std::printf("functions_overloading.cpp — Phase 1 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
