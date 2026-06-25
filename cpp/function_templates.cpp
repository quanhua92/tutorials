// function_templates.cpp — Phase 2 bundle.
//
// GOAL (one line): show, by printing every value, how a C++ FUNCTION TEMPLATE is
// a blueprint parameterized by type T that the compiler INSTANTIATES (stamps out
// a concrete function) for each distinct type you call it with — MONOMORPHIZATION
// (one compiled copy per type: zero runtime cost, binary-size cost) — and how
// TEMPLATE ARGUMENT DEDUCTION infers T from the call args so you usually write
// my_max(1,2), not my_max<int>(1,2).
//
// This is the GROUND TRUTH for FUNCTION_TEMPLATES.md. Every number, tag, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run function_templates   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                     -Wpedantic function_templates.cpp
//                                     -o /tmp/cpp_function_templates
//                                     && /tmp/cpp_function_templates)

#include <cinttypes>   // PRIxPTR
#include <cstddef>     // std::size_t
#include <cstdint>     // std::uintptr_t
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <type_traits> // std::is_same_v

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

// type_tag<T>() returns a stable human-readable name for the (deduced) type T.
// Used at call sites via decltype to PROVE which T the compiler deduced — the
// whole point of the deduction demo. Covers exactly the types this file uses.
template <typename T>
const char* type_tag() {
    if constexpr (std::is_same_v<T, int>) return "int";
    else if constexpr (std::is_same_v<T, double>) return "double";
    else if constexpr (std::is_same_v<T, float>) return "float";
    else if constexpr (std::is_same_v<T, long>) return "long";
    else if constexpr (std::is_same_v<T, bool>) return "bool";
    else return "(other)";
}

// === The canonical function template: a BLUEPRINT, not a function =============
//
// `template <typename T> T my_max(T a, T b)` defines a PATTERN. The compiler
// generates a real function (an INSTANTIATION) only for each T you actually call
// it with. `my_max` by itself is NOT a function — NO code is emitted until you
// use it with a concrete type. T is a TYPE template parameter.
template <typename T>
T my_max(T a, T b) {
    return a < b ? b : a;
}

// === Section A — Blueprint + instantiation + MONOMORPHIZATION (one copy/type) =
//
// Calling my_max(1, 2) forces the compiler to instantiate my_max<int>: it stamps
// out a real `int my_max(int, int)` by substituting T=int everywhere. Calling
// my_max(1.5, 2.5) stamps out a SEPARATE `double my_max(double, double)`. These
// are TWO distinct functions in the binary — that per-type codegen is called
// MONOMORPHIZATION (== Rust generics; != Java/TS erasure).
void sectionA() {
    sectionBanner("A — Blueprint + instantiation + monomorphization");

    auto r1 = my_max(1, 2);          // instantiates my_max<int>;  T deduced int
    auto r2 = my_max(1.5, 2.5);      // instantiates my_max<double>; T deduced double
    std::printf("my_max(1, 2)     = %d   (T deduced as %s -> instantiated my_max<int>)\n",
                r1, type_tag<decltype(r1)>());
    std::printf("my_max(1.5, 2.5) = %.6f   (T deduced as %s -> instantiated my_max<double>)\n",
                r2, type_tag<decltype(r2)>());
    std::printf("-> TWO instantiations now exist in the binary: my_max<int> and my_max<double>\n");

    check("my_max<int>(1, 2) == 2", r1 == 2);
    check("my_max<double>(1.5, 2.5) == 2.5", r2 == 2.5);
    check("the two results have DIFFERENT deduced types (int vs double)",
          !std::is_same_v<decltype(r1), decltype(r2)>);
}

// === Section B — Template argument DEDUCTION + explicit template args =========
//
// DEDUCTION: the compiler figures out T from the argument types, so you write
// my_max(1, 2), not my_max<int>(1, 2). But deduction requires CONSISTENCY: both
// args must yield the SAME T. my_max(1, 2.5) FAILS to deduce — is T int or
// double? The rescue is an EXPLICIT template argument: my_max<double>(1, 2.5)
// forces T=double (and `1` then implicitly converts to 1.0). Explicit args are
// read left-to-right; trailing params may still be deduced.
void sectionB() {
    sectionBanner("B — Argument deduction + explicit template args");

    // (1) Deduction succeeds when all args agree on T.
    auto a = my_max(7, 3);           // T deduced int (both args int)
    auto b = my_max(2.5, 1.5);       // T deduced double (both args double)
    std::printf("(1) deduction: my_max(7, 3)=%d  [T=%s];   my_max(2.5, 1.5)=%.6f  [T=%s]\n",
                a, type_tag<decltype(a)>(), b, type_tag<decltype(b)>());

    // (2) The mixed-type call my_max(1, 2.5) is a DEDUCTION CONFLICT (T=int vs
    //     T=double). It does NOT compile, so we DOCUMENT it, we don't run it:
    //         my_max(1, 2.5);   // ERROR: deduced conflicting types for 'T'
    //                            //         ('int' vs 'double')
    //     The rescue is an EXPLICIT template argument:
    auto c = my_max<double>(1, 2.5); // forces T=double; int 1 -> double 1.0
    std::printf("(2) mixed types: my_max<double>(1, 2.5) = %.6f   [T FORCED to %s]\n",
                c, type_tag<decltype(c)>());

    check("deduction: my_max(7, 3) == 7 (T=int)", a == 7);
    check("deduction: my_max(2.5, 1.5) == 2.5 (T=double)", b == 2.5);
    check("explicit <double> resolves the mixed-type conflict: my_max<double>(1,2.5) == 2.5",
          c == 2.5);
    check("explicit <double> made the return type double",
          std::is_same_v<decltype(c), double>);
}

// === Section C — Multiple type params + NON-TYPE template params ==============
//
// (1) MULTIPLE TYPE PARAMETERS: `template <typename T, typename U>` — one call
//     deduces two independent types. The trailing return `decltype(a + b)` lets
//     the return type depend on the deduced params (a "dependent type").
//
// (2) NON-TYPE TEMPLATE PARAMETERS: `template <int N>` takes a COMPILE-TIME
//     CONSTANT VALUE (not a type). factorial<N> recurses at compile time;
//     array_len deduces the array bound N from a reference-to-array argument.
//     This is the mechanism std::array<int, N> (P1) and fixed-size buffers rest
//     on. `template <auto N>` (C++17) lets N's type be deduced too.
template <typename T, typename U>
auto add(const T& a, const U& b) -> decltype(a + b) {
    return a + b;
}

template <int N>
constexpr int factorial() {
    if constexpr (N <= 1) return 1;          // base case, resolved at compile time
    else return N * factorial<N - 1>();      // recurse with a smaller N
}

// N deduced from a reference-to-array of N elements (the array bound IS the
// non-type template param).
template <typename T, std::size_t N>
constexpr std::size_t array_len(const T (&)[N]) { return N; }

// Compile-time proof that non-type template params are evaluated at compile time:
static_assert(factorial<5>() == 120);
static_assert(factorial<0>() == 1);

void sectionC() {
    sectionBanner("C — Multiple type params + non-type template params");

    // (1) Two independently deduced types: add(int, double) -> double (3.5)
    auto s = add(1, 2.5);            // T=int, U=double; return decltype(int+double)=double
    std::printf("(1) add(1, 2.5) = %.6f   [T=int, U=double, return %s]\n",
                s, type_tag<decltype(s)>());

    // (2) Non-type template param N: a compile-time integer.
    constexpr int f5 = factorial<5>();   // 5! == 120, computed at compile time
    std::printf("(2) factorial<5>() = %d   (computed at compile time; static_assert'd)\n", f5);
    std::printf("    factorial<0>() = %d   (base case via if constexpr)\n", factorial<0>());

    // (3) Non-type param N DEDUCED from a reference-to-array argument.
    int arr[5] = {10, 20, 30, 40, 50};
    std::printf("(3) int arr[5]; array_len(arr) = %zu   (N deduced from the array type)\n",
                array_len(arr));

    check("add(int,double) == 3.5 (return type double)", s == 3.5);
    check("add's return type is double (decltype(int+double))",
          std::is_same_v<decltype(s), double>);
    check("factorial<5>() == 120 (compile-time, non-type param N)", f5 == 120);
    check("factorial<0>() == 1 (if-constexpr base case)", factorial<0>() == 1);
    check("array_len(int[5]) == 5 (non-type param N deduced from array)", array_len(arr) == 5);
}

// === Section D — Template vs non-template overload interaction ===============
//
// Function templates and ordinary (non-template) functions can be OVERLOADED
// together. The ranking (the deep dive belongs to OVERLOAD_RESOLUTION P2):
//   - an EXACT-MATCH non-template overload is preferred over a template;
//   - a template instantiation wins when no non-template matches exactly (the
//     template gives an exact match via deduction; a non-template needing a
//     conversion is a worse call).
// tag_of(int) wins over the template for an int arg; tag_of(long) has no
// non-template overload, so the template is instantiated with T=long.
template <typename T>
int tag_of(T) { return 0; }         // #0 the template (fallback)
int tag_of(int) { return 1; }       // #1 non-template, exact for int
int tag_of(double) { return 2; }    // #2 non-template, exact for double

void sectionD() {
    sectionBanner("D — Template vs non-template overload interaction");

    int t_int = tag_of(5);          // exact non-template tag_of(int) preferred -> 1
    int t_dbl = tag_of(2.5);        // exact non-template tag_of(double) preferred -> 2
    int t_lng = tag_of(5L);         // no non-template for long -> template, T=long -> 0
    std::printf("tag_of(5)   = %d   (int    -> exact non-template beats template)\n", t_int);
    std::printf("tag_of(2.5) = %d   (double -> exact non-template beats template)\n", t_dbl);
    std::printf("tag_of(5L)  = %d   (long   -> no non-template; template instantiated)\n", t_lng);

    check("tag_of(int) == 1: exact non-template overload preferred over template", t_int == 1);
    check("tag_of(double) == 2: exact non-template overload preferred", t_dbl == 2);
    check("tag_of(long) == 0: template fallback (no non-template for long)", t_lng == 0);

    // The famously BAD ERROR: a deduction failure produces a wall of text. The
    // mixed-type call my_max(1, 2.5) (Section B) is the canonical example — pre-
    // concepts the diagnostic lists every overload the compiler considered. The
    // rescue is my_max<double>(1, 2.5) (shown in Section B). Concepts (P2) turn
    // these into short "constraints not satisfied" messages.
    std::printf("\n(deduction-failure diagnostics: my_max(1, 2.5) won't compile; the rescue\n");
    std::printf(" my_max<double>(1, 2.5) is shown in Section B. Concepts (P2) shorten\n");
    std::printf(" these famously-long errors.)\n");
    check("the mixed-type deduction conflict is documented (not compiled here)", true);
}

// === Section E — MONOMORPHIZATION cost model + cross-language =================
//
// MONOMORPHIZATION = the compiler emits a separate body for each instantiated
// (type, function) pair. The COST MODEL:
//   - RUNTIME: zero — each instantiation is a direct, statically-typed call; no
//     boxing, no virtual dispatch, no dynamic type checks (unlike erasure).
//   - BINARY SIZE: one copy per type used — can bloat (code size / I-cache).
// We PROVE the per-type copies are distinct functions by printing the addresses
// of &my_max<int> and &my_max<double>: they differ. Taking the address forces
// the instantiation to exist (ODR-uses it), so the bodies really are emitted.
void sectionE() {
    sectionBanner("E — Monomorphization cost model + cross-language");

    using IntMaxFn = int (*)(int, int);
    using DblMaxFn = double (*)(double, double);
    IntMaxFn pi = &my_max<int>;     // ODR-uses my_max<int>  -> body emitted
    DblMaxFn pd = &my_max<double>;  // ODR-uses my_max<double> -> body emitted
    // Cast each function pointer to a common void(*)() (reinterpret_cast) so we
    // can compare them and read their addresses as integers. We never CALL
    // through the reinterpreted type (that would be UB).
    // NOTE: absolute addresses are NON-DETERMINISTIC (the OS applies ASLR — a
    // different load base each run), so we print the OFFSET between the two
    // functions, which the LINKER fixes and which is stable across runs.
    auto addr_i = (std::uintptr_t)(void (*)())pi;
    auto addr_d = (std::uintptr_t)(void (*)())pd;
    auto offset = (addr_d > addr_i) ? (addr_d - addr_i) : (addr_i - addr_d);
    std::printf("my_max<int> and my_max<double> are %zu bytes apart in the binary\n", offset);
    std::printf("-> a NONZERO offset means two DISTINCT function bodies (one per type)\n");

    std::printf("\nmonomorphization cost model:\n");
    std::printf("  runtime cost : ZERO  (direct call, no boxing / no dispatch)\n");
    std::printf("  binary size  : one body per instantiated type (code-bloat risk)\n");

    std::printf("\ncross-language generics model:\n");
    std::printf("  C++    templates   : MONOMORPHIZED (one copy/type)\n");
    std::printf("  Rust   generics    : MONOMORPHIZED (the closest sibling)\n");
    std::printf("  Go     type params : GC-shape stenciling (partial mono)\n");
    std::printf("  TS/Java generics   : ERASED (one body, no per-type copy)\n");

    check("my_max<int> and my_max<double> are DISTINCT functions (monomorphization)",
          (void (*)())pi != (void (*)())pd);
    check("both instantiations have a real (nonzero) address (codegen happened)",
          addr_i != 0 && addr_d != 0);
    check("the two bodies are a nonzero offset apart (two emitted copies)", offset != 0);
}

}  // namespace

int main() {
    std::printf("function_templates.cpp — Phase 2 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
