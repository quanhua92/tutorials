// const_qualifiers.cpp — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how C++'s const family —
// `const` objects/params/methods, the const-POSITION rule (pointer to const vs
// const pointer), `constexpr` (compile-time), `constinit` (C++20, static init),
// and `mutable` (mutate-in-const) — behave, pinning const-correctness as a
// COMPILE-TIME discipline that catches accidental mutation at zero runtime cost.
//
// This is the GROUND TRUTH for CONST_QUALIFIERS.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     just run const_qualifiers   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                   const_qualifiers.cpp -o /tmp/cpp_const_qualifiers
//                                   && /tmp/cpp_const_qualifiers)

#include <cstddef>     // std::size_t
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <type_traits> // std::is_same_v (top-level vs low-level const checks)

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

// === Section B's type: a const method, a non-const method, and `mutable` =====
// `mutable` marks a member that may change even inside a const method (physical
// state that is NOT part of the object's logical/client-visible state — the
// "logical const" notion: caches, mutexes, debug/access counters).
struct Widget {
    int data = 0;
    mutable int inspect_count = 0;   // mutable: may change inside a const method

    int inspect() const {            // const member fn: promises not to mutate *this
        ++inspect_count;             // OK: inspect_count is `mutable`
        // ++data;                   // would be a COMPILE ERROR: data is not mutable
        return data;
    }
    void mutate(int v) {             // non-const member fn: may change *this
        data = v;
    }
};

// === Section D's compile-time family ========================================
// A constexpr function: evaluatable at compile time when called in a constant
// expression context (array bound, template arg, case label, ...).
constexpr int factorial(int n) {
    int r = 1;
    for (int i = 2; i <= n; ++i) r *= i;
    return r;
}

// A consteval function (C++20): an "immediate function" — every call MUST
// produce a constant (run at compile time). Calling it with a runtime value is
// a compile error; only legal in a constant-evaluation context.
consteval int compile_time_only(int n) { return n * n; }

// constinit (C++20): asserts this static-duration variable is CONSTANT-
// initialized (zero + constant init) — there is NO dynamic initialization, so
// the static-initialization-order fiasco cannot occur. Unlike constexpr,
// constinit does NOT imply const: the variable stays MUTABLE at runtime.
constinit int g_seed = 100;

// === Section A — const object + const T& param (const correctness begins) ====
void sectionA() {
    sectionBanner("A — const object + const T& param (const correctness begins)");

    // (1) const OBJECT: cannot be modified after initialization.
    const int ci = 42;
    std::printf("(1) const int ci = 42;  -> ci = %d\n", ci);
    std::printf("    (a later `ci = 7;` is a COMPILE ERROR — documented, not run)\n");
    check("const object holds its initialized value (ci == 42)", ci == 42);

    // (2) const T& PARAMETER: the callee PROMISES not to mutate the argument.
    //     Bonus: a const T& can bind to a TEMPORARY (rvalue) — a non-const T& CANNOT.
    auto plus_one = [](const int& x) { return x + 1; };   // promises: no mutation via x
    int n = 10;
    int from_lvalue = plus_one(n);    // binds the lvalue `n`
    int from_temp = plus_one(99);     // binds a TEMPORARY — only const T& allows this
    std::printf("\n(2) plus_one(const int& x): from lvalue n=10 -> %d; from temp 99 -> %d\n",
                from_lvalue, from_temp);
    check("const T& binds an lvalue (plus_one(10) == 11)", from_lvalue == 11);
    check("const T& binds a temporary/rvalue (plus_one(99) == 100)", from_temp == 100);
    check("const T& did NOT mutate the lvalue argument (n still 10)", n == 10);

    // (3) const at NAMESPACE scope has INTERNAL linkage in C++ (vs external in C).
    //     Each TU gets its own copy; share ONE definition across TUs with
    //     `inline constexpr` (C++17). (Documented from cppreference storage_duration.)
    std::printf("\n(3) namespace-scope `const int k = ..;` has INTERNAL linkage in C++\n");
    std::printf("    (vs external in C). Share one def across TUs with `inline constexpr`.\n");
    check("namespace-scope const has internal linkage in C++ (documented, cppreference)", true);
}

// === Section B — const member function + the viral cascade + mutable =========
void sectionB() {
    sectionBanner("B — const member function + the viral cascade + mutable");

    // (1) A const member function is callable on a CONST object; a non-const one
    //     is NOT. The check is entirely at COMPILE TIME (zero runtime cost).
    const Widget cw{};               // a const object
    int seen = cw.inspect();         // OK: inspect() is const -> callable on const object
    std::printf("(1) const Widget cw;  cw.inspect() = %d  (const method OK on const object)\n", seen);
    // cw.mutate(5);                 // COMPILE ERROR: mutate() is non-const -> rejected
    std::printf("    (cw.mutate(5) would be a COMPILE ERROR: non-const method on a const object)\n");
    check("const member function is callable on a const object (cw.inspect() == 0)", seen == 0);

    // (2) THE VIRAL CASCADE: const methods are callable on non-const objects too
    //     (the more-qualified can always call the less-qualified); but the reverse
    //     fails. And a const method can ONLY call other const methods on *this —
    //     forgetting `const` on one member makes it uncallable from const code.
    Widget mw{};                     // a non-const object
    mw.mutate(7);                    // OK: non-const method on non-const object
    int seen2 = mw.inspect();        // OK: const method ALSO callable on non-const objects
    std::printf("\n(2) Widget mw;  mw.mutate(7);  mw.inspect() = %d\n", seen2);
    std::printf("    (const methods are callable on non-const objects too; the reverse is not)\n");
    check("non-const method callable on a non-const object (mw.data set to 7)", seen2 == 7);

    // (3) mutable: a `mutable` member CAN be mutated inside a const method.
    //     Use case: caches, mutexes, debug/access counters — physical state that is
    //     not part of the object's LOGICAL (client-visible) state. (isocpp FAQ:
    //     "logical const" vs "physical const".)
    int before = cw.inspect_count;   // reading a mutable member is always fine
    cw.inspect();                    // mutates inspect_count EVEN THOUGH cw is const
    cw.inspect();
    int after = cw.inspect_count;
    std::printf("\n(3) mutable int inspect_count: cw.inspect_count %d -> %d (delta=%d)\n",
                before, after, after - before);
    std::printf("    (a const method mutated a `mutable` member of a CONST object — by design)\n");
    check("mutable member was mutated INSIDE a const method on a const object (delta == 2)",
          after - before == 2);
}

// === Section C — THE const-POSITION rule (read right-to-left) ================
void sectionC() {
    sectionBanner("C — THE const-POSITION rule (read right-to-left)");

    int a = 10;
    int b = 20;

    std::printf("Read pointer declarations RIGHT-TO-LEFT. `const` binds to what is on its\n");
    std::printf("LEFT; if leftmost it binds RIGHT (the 'const-West' quirk). The consistent\n");
    std::printf("style is 'East const' (always put const on the RIGHT of what it constifies):\n");
    std::printf("    const int* p  ==  int const* p     (the SAME type: pointer to const int)\n");

    // (1) "pointer to const int":  const int* p  ==  int const* p
    //     *p is immutable THROUGH p; p itself can be reassigned to point elsewhere.
    const int* p1 = &a;              // int* -> const int* (implicit qualification conversion)
    // *p1 = 99;                     // COMPILE ERROR: *p1 is const (as seen through p1)
    p1 = &b;                         // OK: p1 itself is reassignable
    std::printf("\n(1) const int* p1 = &a;  p1 = &b;  -> *p1 = %d  (p reassigned; *p read-only via p)\n",
                *p1);
    // CRITICAL nuance (isocpp FAQ "aliasing-and-const"): const int* does NOT make `a`
    // const. `a` is still mutable directly; only ACCESS THROUGH p1 is read-only.
    a = 55;
    p1 = &a;                         // point p1 back at a
    std::printf("    a = 55; p1 = &a;  -> *p1 = %d  (a is NOT const; only *p1 is read-only VIA p1)\n",
                *p1);
    check("const int* is reassignable (p1 now points at a; *p1 == 55)", *p1 == 55 && p1 == &a);
    check("const int* == int const* (the SAME type)", std::is_same_v<const int*, int const*>);

    // (2) "const pointer to int":  int* const p
    //     p is FIXED (cannot reassign); *p is mutable.
    int* const p2 = &a;              // const pointer to (mutable) int
    *p2 = 99;                        // OK: *p2 is mutable
    // p2 = &b;                      // COMPILE ERROR: p2 is const (cannot reassign)
    std::printf("\n(2) int* const p2 = &a;  *p2 = 99;  -> a = %d  (p fixed; *p mutable)\n", a);
    check("int* const: *p is mutable (a mutated to 99 via p2)", a == 99);
    check("int* const: p itself is fixed (p2 == &a)", p2 == &a);

    // (3) "const pointer to const int":  const int* const p  ==  int const* const p
    //     BOTH locked: *p is read-only AND p is fixed.
    const int* const p3 = &a;
    // *p3 = 1;                      // COMPILE ERROR
    // p3 = &b;                      // COMPILE ERROR
    std::printf("\n(3) const int* const p3 = &a;  -> *p3 = %d  (BOTH locked: *p read-only AND p fixed)\n",
                *p3);
    check("const int* const: *p read-only and p fixed (*p3 == 99, p3 == &a)",
          *p3 == 99 && p3 == &a);
    check("const int* const == int const* const (the SAME type)",
          std::is_same_v<const int* const, int const* const>);

    // ── Decision table: which cell is mutable? ───────────────────────────────
    std::printf("\n    spelling                pointee (*p)    pointer (p)\n");
    std::printf("    ----------------------   -----------     -----------\n");
    std::printf("    const int*  (= int const*)   READ-ONLY    reassignable\n");
    std::printf("    int* const                  mutable      FIXED\n");
    std::printf("    const int* const            READ-ONLY    FIXED\n");

    // ── TOP-LEVEL vs LOW-LEVEL const (the auto / template-deduction split) ───
    //   top-level const: on the OBJECT or the POINTER ITSELF -> STRIPPED by auto
    //                                                    and by template deduction.
    //   low-level  const: on the POINTEE              -> KEPT by auto / template
    //                                                    deduction (it is part of the
    //                                                    derived type, not a property
    //                                                    of the variable).
    const int ci = 7;
    auto top_stripped = ci;           // int         — top-level const STRIPPED
    const int* lp = &ci;
    auto low_kept = lp;               // const int*  — low-level const KEPT
    int* const tcp = &a;              // const pointer to mutable int (top-level on the ptr)
    auto ptr_stripped = tcp;          // int*        — top-level const STRIPPED

    std::printf("\nTOP-LEVEL vs LOW-LEVEL const (auto / template argument deduction):\n");
    std::printf("    const int ci=7;  auto x = ci;     -> int         (top-level const STRIPPED)\n");
    std::printf("    const int* p=&ci; auto y = p;     -> const int*  (low-level  const KEPT)\n");
    std::printf("    int* const cp=&a; auto z = cp;    -> int*        (top-level const STRIPPED)\n");
    std::printf("    derived values: x=%d, *y=%d, *z=%d\n", top_stripped, *low_kept, *ptr_stripped);
    check("auto strips top-level const on a value (const int -> int)",
          std::is_same_v<decltype(top_stripped), int>);
    check("auto keeps low-level const (const int* stays const int*)",
          std::is_same_v<decltype(low_kept), const int*>);
    check("auto strips top-level const on a pointer (int* const -> int*)",
          std::is_same_v<decltype(ptr_stripped), int*>);
}

// === Section D — constexpr / consteval / constinit (the compile-time family) ==
void sectionD() {
    sectionBanner("D — constexpr / consteval / constinit (the compile-time family)");

    // (1) constexpr VARIABLE: value computable at compile time; usable as an array
    //     bound, template arg, case label. constexpr on a variable IMPLIES const.
    constexpr int N = factorial(5);   // 120, computed at compile time
    int arr[N];                        // N usable as an array bound (proof of compile-time eval)
    for (int i = 0; i < N; ++i) arr[i] = i;
    long sum = 0;
    for (int i = 0; i < N; ++i) sum += arr[i];
    std::printf("(1) constexpr int N = factorial(5);  -> N = %d\n", N);
    std::printf("    int arr[N]; (N as array bound) -> sizeof(arr) = %zu bytes; sum(0..%d) = %ld\n",
                sizeof(arr), N - 1, sum);
    check("constexpr factorial(5) == 120 (computed at compile time)", N == 120);
    check("constexpr N is usable as an array bound (arr has N elements)",
          sizeof(arr) / sizeof(arr[0]) == static_cast<std::size_t>(N));
    check("constexpr implies const: N is immutable (== 120)", N == 120);

    // (2) consteval FUNCTION (C++20): an "immediate function" — every call MUST
    //     produce a constant. The result is only usable where a constant is
    //     required; calling it with a runtime value is a compile error.
    constexpr int sq = compile_time_only(7);   // 49, MUST run at compile time
    std::printf("\n(2) consteval int compile_time_only(int);   constexpr sq = compile_time_only(7);\n");
    std::printf("    -> sq = %d   (consteval: the call is FORCED to compile time)\n", sq);
    check("consteval function forced to compile time (compile_time_only(7) == 49)", sq == 49);

    // (3) constinit VARIABLE (C++20): asserts CONSTANT initialization (zero +
    //     constant init) — there is NO dynamic init, so the static-initialization-
    //     order fiasco cannot occur. Unlike constexpr, it does NOT make the
    //     variable const: g_seed is still MUTABLE at runtime.
    int snap1 = g_seed;
    g_seed = 999;                      // OK: constinit does NOT imply const
    int snap2 = g_seed;
    std::printf("\n(3) constinit int g_seed = 100;   (constant-initialized, NOT const)\n");
    std::printf("    g_seed before = %d;  after `g_seed = 999;` -> %d   (mutable, unlike constexpr)\n",
                snap1, snap2);
    check("constinit does NOT imply const (g_seed mutated 100 -> 999)",
          snap1 == 100 && snap2 == 999);
    // The ill-formed case (NOT compiled): constinit with a dynamic initializer.
    std::printf("    (`constinit int bad = some_runtime_fn();` is ILL-FORMED — documented)\n");
    check("constinit requires a constant initializer (documented: dynamic init is ill-formed)", true);

    // ── The family at a glance ───────────────────────────────────────────────
    std::printf("\n    specifier    applies to   implies const?   enforces\n");
    std::printf("    ----------   ----------   --------------   --------------------------------------\n");
    std::printf("    const        object/ref   YES              immutability after init (runtime)\n");
    std::printf("    constexpr    var/fn       YES (var)        value computable at COMPILE TIME\n");
    std::printf("    consteval    fn           n/a (it is a fn) every call MUST run at compile time\n");
    std::printf("    constinit    static var   NO               CONSTANT init only (no dynamic init)\n");
}

// === Section E — const-correctness discipline (qual-conv, const_cast danger) =
void sectionE() {
    sectionBanner("E — const-correctness discipline (qual-conv, const_cast danger)");

    // (1) QUALIFICATION CONVERSION: T* -> const T* is IMPLICIT (adding const is
    //     safe — a read-only view of a possibly-mutable object). The REVERSE
    //     (const T* -> T*) requires const_cast and is dangerous.
    int x = 5;
    int* mut = &x;
    const int* ro = mut;              // IMPLICIT: int* -> const int* (add const, safe)
    std::printf("(1) int* -> const int* is IMPLICIT (qualification conversion, safe):\n");
    std::printf("    const int* ro = mut;  -> *ro = %d  (a read-only view of a mutable int)\n", *ro);
    check("qualification conversion int* -> const int* is implicit (*ro == 5)", *ro == 5);

    // const_cast is DEFINED only when the underlying object is NON-const. Here `x`
    // is non-const, so casting away const from `*ro` and writing is well-defined.
    const_cast<int&>(*ro) = 8;        // OK: defined because the underlying object x is non-const
    std::printf("    const_cast<int&>(*ro) = 8;  -> x = %d   (defined: the underlying object x is non-const)\n",
                x);
    check("const_cast is defined when the underlying object is non-const (x == 8)", x == 8);

    // The DANGEROUS case (documented, NOT run): const_cast-ing away const from a
    // TRULY-const object and mutating it is UNDEFINED BEHAVIOR.
    std::printf("    (`const int k=1; const_cast<int&>(k)=2;` is UNDEFINED BEHAVIOR — documented)\n");
    check("const_cast on a truly-const object is UB (documented, not run)", true);

    // (2) CONST-CORRECTNESS CASCADE: const is VIRAL. A const member fn can only
    //     call other const member fns on *this; a const T& param can only flow to
    //     callees that accept const T&. Adding const in one place forces it
    //     downstream. (isocpp FAQ: "Add const early and often" — back-patching it
    //     later causes a snowball effect.)
    std::printf("\n(2) const is VIRAL: a const method can only call const methods on *this;\n");
    std::printf("    a const T& only flows to const T& params. Add const EARLY and OFTEN.\n");
    check("const-correctness is viral / cascading (documented, isocpp FAQ)", true);

    // (3) CROSS-LANGUAGE immutability models (the 5-language curriculum).
    std::printf("\n(3) Cross-language immutability models:\n");
    std::printf("    C++ :  const/opt-in; `mutable` escape hatch; const-METHOD concept; viral.\n");
    std::printf("    Go  :  `const` = COMPILE-TIME constants ONLY (not a general immutability marker).\n");
    std::printf("    Rust:  `let` immutable by DEFAULT; `mut` OPTS IN (the inverse default).\n");
    check("cross-language immutability models documented (C++ vs Go vs Rust)", true);
}

}  // namespace

int main() {
    std::printf("const_qualifiers.cpp — Phase 1 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
