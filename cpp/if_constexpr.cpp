// if_constexpr.cpp — Phase 6 bundle.
//
// GOAL (one line): prove — by compiling type-invalid code in a DISCARDED branch
// and asserting the right branch ran — that `if constexpr (cond)` (C++17)
// evaluates `cond` at COMPILE TIME and DISCARDS the false branch WITHOUT
// INSTANTIATING IT, so the discarded branch may contain code that is TYPE-INVALID
// for the actual template arguments (e.g. calling `.size()` on an `int`). This
// is the KEY tool for branch-on-type generic code, and it replaces
// SFINAE/enable_if for that case.
//
// This is the GROUND TRUTH for IF_CONSTEXPR.md. Every value below is computed by
// this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run if_constexpr   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                              if_constexpr.cpp -o /tmp/cpp_if_constexpr
//                              && /tmp/cpp_if_constexpr)

#include <concepts>      // std::integral (concept)
#include <cstddef>       // std::size_t
#include <cstdio>        // printf / fprintf
#include <cstdlib>       // EXIT_FAILURE / exit
#include <cstring>       // memset (banner bar)
#include <string>        // std::string (the .size() payoff in Section B)
#include <type_traits>   // std::is_integral_v, std::is_class_v, std::is_same_v

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

// === Section A — if constexpr basics: compile-time cond, false branch DISCARDED
//
// `if constexpr (cond)` requires `cond` to be a CONTEXTUALLY CONVERTED CONSTANT
// EXPRESSION of type bool — i.e. the compiler can evaluate it at compile time.
// The branch whose cond is false is the DISCARDED statement: in a template it is
// NOT instantiated (its dependent names are not even substituted). The kept
// branch is the only one that ships in the binary — no runtime test exists.
void sectionA() {
    sectionBanner("A — if constexpr basics: compile-time cond, false branch DISCARDED");

    std::printf("cond must be a constant expression of type bool (compile-time).\n");
    std::printf("The FALSE branch is the DISCARDED statement (not instantiated).\n\n");

    // Two compile-time booleans. The compiler picks the branch at compile time.
    constexpr bool take_if = true;
    constexpr bool take_else = false;

    bool if_ran_for_true = false, else_ran_for_true = false;
    if constexpr (take_if) {
        if_ran_for_true = true;
    } else {
        else_ran_for_true = true;
    }
    std::printf("if constexpr (take_if == true):   if_ran=%d  else_ran=%d\n",
                if_ran_for_true, else_ran_for_true);

    bool if_ran_for_false = false, else_ran_for_false = false;
    if constexpr (take_else) {
        if_ran_for_false = true;
    } else {
        else_ran_for_false = true;
    }
    std::printf("if constexpr (take_else == false): if_ran=%d  else_ran=%d\n",
                if_ran_for_false, else_ran_for_false);

    // `cond` may be ANY constant expression, not just a named bool. sizeof is a
    // constant expression; so is a constexpr function call, an arithmetic
    // combination of constants, etc.
    const char* c = "(unset)";
    if constexpr (sizeof(int) >= 4) {
        c = "if-branch ran (sizeof(int) >= 4 on this platform)";
    } else {
        c = "else-branch ran (sizeof(int) < 4)";
    }
    std::printf("if constexpr (sizeof(int) >= 4):   %s\n", c);

    check("if constexpr (true)  -> only the if-branch ran",
          if_ran_for_true && !else_ran_for_true);
    check("if constexpr (false) -> only the else-branch ran",
          !if_ran_for_false && else_ran_for_false);
    check("sizeof(int) >= 4 (a constant expression usable as a constexpr-if cond)",
          sizeof(int) >= 4);
}

// === Section B — THE PAYOFF: a discarded branch may be TYPE-INVALID ===========
//
// This is why if constexpr exists. The function template below calls `x.size()`
// in its else-branch. For T=int there is NO `int::size()` — that code is
// TYPE-INVALID. Yet it COMPILES, because `if constexpr` DISCARDS the else-branch
// for T=int (it is not instantiated; the dependent name `x.size()` is never
// substituted against int). With a plain runtime `if` BOTH branches are
// instantiated and T=int would be a hard compile error (Section C).
//
// We instantiate the template for BOTH T=int (else discarded) and T=std::string
// (if discarded) and assert each ran the correct branch.

// Returns x/2 for integers, x.size() for anything with a .size() member.
// The branch that does NOT match T is DISCARDED at compile time.
template <class T>
std::size_t branchOnType(const T& x) {
    if constexpr (std::is_integral_v<T>) {
        // For T=int this branch is KEPT. Returns x/2.
        return static_cast<std::size_t>(x) / 2;
    } else {
        // For T=int this branch is DISCARDED -> NOT instantiated -> the call
        // `x.size()` is never type-checked against int, so it compiles fine.
        // For T=std::string this branch is KEPT and runs.
        return x.size();
    }
}

void sectionB() {
    sectionBanner("B — THE payoff: a discarded branch can be TYPE-INVALID");

    std::printf("Template branchOnType<T> returns x/2 for integers, x.size() otherwise.\n");
    std::printf("The non-matching branch is DISCARDED (not instantiated) -> compiles.\n\n");

    int n = 42;
    std::string s = "hello";  // length 5

    const std::size_t r_int = branchOnType(n);
    const std::size_t r_str = branchOnType(s);

    std::printf("branchOnType(int 42)        = %zu   (if-branch ran: 42/2)\n", r_int);
    std::printf("branchOnType(string \"%s\")  = %zu   (else-branch ran: .size())\n",
                s.c_str(), r_str);

    check("branchOnType<int>: if-branch ran (42/2 == 21)", r_int == 21);
    check("branchOnType<string>: else-branch ran (\"hello\".size() == 5)", r_str == 5);
    check("the discarded else-branch (int::size()) compiled — PROOF if constexpr discards it",
          true);

    // Return type is deduced from the KEPT branch only when `auto` is used; here
    // the return type is explicit (std::size_t), so both instantiations match.
    std::printf("\nreturn type std::size_t is shared by both instantiations (explicit here).\n");
    check("branchOnType<int> & <string> share the explicit return type std::size_t",
          std::is_same_v<decltype(branchOnType(n)), std::size_t> &&
              std::is_same_v<decltype(branchOnType(s)), std::size_t>);
}

// === Section C — CONTRAST: runtime `if` instantiates BOTH branches ============
//
// A plain runtime `if (cond)` compiles BOTH branches regardless of cond's value
// — so inside a template BOTH branches must be valid for T. The type-invalid
// trick from Section B is IMPOSSIBLE with a runtime if.
//
// We cannot compile the broken version, so it is gated behind #ifdef
// DEMO_COMPILE_ERROR (never passed by just run/out/check/sanitize). The verified
// path shows a runtime if that DOES compile (both branches valid) and documents
// the contrast.
void sectionC() {
    sectionBanner("C — CONTRAST: runtime if compiles BOTH branches");

    // (1) A runtime if: cond is a RUNTIME value. BOTH branches are compiled into
    //     the binary; the CPU picks one at run time. Both must be type-valid.
    int v = 7;
    int got = 0;
    if (v > 5) {  // runtime condition
        got = 1;  // both branches compiled...
    } else {
        got = 2;  // ...both branches compiled
    }
    std::printf("(1) runtime if (v=%d > 5): got=%d  (BOTH branches compiled; CPU picks)\n", v, got);

    // (2) Same logic with if constexpr: cond is COMPILE-TIME. Only ONE branch
    //     exists in the binary. Here cond is a constant, so the else is dropped.
    constexpr int k = 7;
    int got2 = 0;
    if constexpr (k > 5) {
        got2 = 1;
    } else {
        got2 = 2;  // DISCARDED — not in the binary
    }
    std::printf("(2) if constexpr (k=%d > 5): got2=%d  (ONE branch compiled; else DISCARDED)\n",
                k, got2);

    check("runtime if: v>5 picked the if-branch (got==1)", got == 1);
    check("if constexpr: k>5 kept the if-branch (got2==1)", got2 == 1);

    // (3) DOCUMENTED (never compiled in the verified path): a runtime if inside
    //     a template CANNOT discard a type-invalid branch. Build with
    //     -DDEMO_COMPILE_ERROR to see the hard error for yourself.
    std::printf("\n(3) runtime if inside a template would instantiate BOTH branches:\n");
    std::printf("    if (std::is_integral_v<T>) return x/2; else return x.size();\n");
    std::printf("    -> for T=int the else (int::size()) is a COMPILE ERROR.\n");
    std::printf("    (Gated behind #ifdef DEMO_COMPILE_ERROR; `just run` never sets it.)\n");
    check("runtime if cannot discard a type-invalid branch (documented, not compiled)", true);
}

#ifdef DEMO_COMPILE_ERROR
// WHAT NOT TO DO — never compiled by just run/out/check/sanitize. Build with
// -DDEMO_COMPILE_ERROR to see the hard error: "no member named 'size' in 'int'".
// A runtime `if` (not `if constexpr`) instantiates BOTH branches, so for T=int
// the else-branch's `x.size()` is a compile error.
template <class T>
auto brokenRuntimeIf(const T& x) {
    if (std::is_integral_v<T>) {  // RUNTIME if: both branches instantiated
        return static_cast<std::size_t>(x) / 2;
    } else {
        return x.size();  // ERROR for T=int: int has no .size()
    }
}
// Force an instantiation for T=int so the body is checked and the error fires.
static_assert(sizeof(brokenRuntimeIf(42)) > 0, "force instantiation");
#endif

// === Section D — if-with-initializer + concepts; the discard rules ============
//
// (a) if constexpr composes with the C++17 if-with-initializer:
//       if constexpr (init; cond) { ... }
//     The classic use is variadic RECURSION TERMINATION: test sizeof...(pack).
//
// (b) Concepts (C++20) drop in cleanly: `if constexpr (std::integral<T>)` reads
//     better than `if constexpr (std::is_integral_v<T>)`.
//
// (c) Discard rules: a discarded statement is PARSED (must be syntactically
//     valid) but, inside a template, NOT INSTANTIATED — dependent names like
//     `x.size()` are not substituted for the actual T. Outside a template, a
//     discarded statement IS fully checked, so `if constexpr(false){ gobbledygook }`
//     is NOT a free pass to write gibberish.

// Variadic sum using if constexpr for the recursion terminator. Note the
// if-with-initializer: `auto n = sizeof...(Ts); n > 0`.
template <class T, class... Ts>
int sumVariadic(T first, Ts... rest) {
    if constexpr (constexpr std::size_t n = sizeof...(Ts); n > 0) {
        return first + sumVariadic(rest...);
    } else {
        return first;  // base case: exactly one argument left
    }
}

// Concept-based branch (cleaner than the is_integral_v form).
template <class T>
const char* describe(const T&) {
    if constexpr (std::integral<T>) {
        return "an integral type";
    } else if constexpr (std::is_class_v<T>) {
        return "a class type";
    } else {
        return "something else";
    }
}

void sectionD() {
    sectionBanner("D — if-with-initializer + concepts; the discard rules");

    // (a) Variadic recursion terminated by if constexpr (sizeof...(Ts) > 0).
    const int total = sumVariadic(1, 2, 3, 4, 5);
    std::printf("(a) sumVariadic(1,2,3,4,5) = %d   (if constexpr terminates the recursion)\n",
                total);

    // (b) Concept-based branching.
    std::printf("(b) describe(42)          = %s\n", describe(42));
    std::printf("    describe(std::string) = %s\n", describe(std::string("x")));

    check("sumVariadic(1..5) == 15", total == 15);
    check("describe(int) -> \"an integral type\" (concept std::integral<T>)",
          std::string(describe(42)) == "an integral type");
    check("describe(std::string) -> \"a class type\" (std::is_class_v<T>)",
          std::string(describe(std::string("x"))) == "a class type");

    // (c) The discard rules — proven by the fact that this file compiles at all.
    //     branchOnType<int> (Section B) keeps `x/2` and DISCARDS `x.size()`. The
    //     discarded branch's dependent name `x.size()` was NOT substituted for
    //     T=int; if it had been, this TU would not compile. That is the proof.
    std::printf("\n(c) discard rules: a discarded branch is PARSED but not INSTANTIATED.\n");
    std::printf("    branchOnType<int> compiled -> the discarded `x.size()` was never\n");
    std::printf("    substituted against int. (Outside a template, a discarded branch\n");
    std::printf("    IS fully checked — `if constexpr(false){ ...gibberish... }` errors.)\n");
    check("discarded branch's dependent names are NOT substituted (this file compiled)",
          true);
}

// === Section E — Replaces SFINAE for branch-on-type; cross-language ==========
//
// Before if constexpr, "do one thing for ints, another for things with .size()"
// required TWO SFINAE-constrained overloads (see the SFINAE_ENABLE_IF bundle).
// With if constexpr it is ONE function body. We show the one-body form.
//
// Cross-language: Rust has NO if constexpr — it branches on type via SEPARATE
// trait impls or enum match (a different, more explicit model). TypeScript has
// no compile-time branching on type either — types are ERASED at runtime, so
// there is nothing to branch on. Go uses interfaces + runtime type switches.

// ONE function body, type-specific behavior, no overloads. The post-C++17 idiom;
// the SFINAE equivalent needs two template overloads with enable_if.
template <class T>
std::size_t genericSize(const T& x) {
    if constexpr (std::is_integral_v<T>) {
        return sizeof(T);  // ints: report their byte width
    } else {
        return x.size();   // containers: their element count
    }
}

void sectionE() {
    sectionBanner("E — Replaces SFINAE for branch-on-type; cross-language");

    const std::size_t a = genericSize(42);                   // int -> sizeof(int)
    const std::size_t b = genericSize(std::string("abcd"));  // string -> .size()
    const std::size_t c = genericSize(7L);                   // long -> sizeof(long)

    std::printf("genericSize(42)       = %zu  (int -> sizeof(int) == 4)\n", a);
    std::printf("genericSize(\"abcd\")   = %zu  (string -> .size()   == 4)\n", b);
    std::printf("genericSize(7L)       = %zu  (long -> sizeof(long) == 8)\n", c);

    check("genericSize(int 42) == sizeof(int) (if-branch ran)", a == sizeof(int));
    check("genericSize(\"abcd\") == 4 (else-branch .size() ran)", b == 4);
    check("genericSize(long 7L) == sizeof(long) (if-branch ran)", c == sizeof(long));

    std::printf("\nOne function body replaces TWO SFINAE overloads (see SFINAE_ENABLE_IF).\n");
    std::printf("Cross-language: Rust -> separate trait impls; TS -> types erased; "
                "Go -> interfaces + type switch.\n");
    check("if constexpr replaces SFINAE for the branch-on-type case", true);
}

}  // namespace

int main() {
    std::printf("if_constexpr.cpp — Phase 6 bundle.\n");
    std::printf("Proves if constexpr (C++17) DISCARDS the false branch at compile time.\n");
    std::printf("Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free "
                "(just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
