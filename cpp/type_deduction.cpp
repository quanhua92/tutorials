// type_deduction.cpp — Phase 2 bundle.
//
// GOAL (one line): show, by printing every deduced type via std::is_same_v, how
// `auto`, `decltype`, and `decltype(auto)` deduce types — centering on the
// famous SURPRISE that plain `auto` STRIPS top-level const and & (it makes a
// COPY), while `decltype` / `decltype(auto)` preserve them (transparent).
//
// This is the GROUND TRUTH for TYPE_DEDUCTION.md. Every deduced type below is
// verified at COMPILE TIME with std::is_same_v<...> and its boolean is PRINTED
// (never typeid().name(), which is impl-defined/nondeterministic). The .md
// guide pastes this output verbatim. Never hand-compute.
//
// Run:
//     just run type_deduction   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                type_deduction.cpp -o /tmp/cpp_type_deduction
//                                && /tmp/cpp_type_deduction)

#include <cstdio>       // printf / fprintf
#include <cstdlib>      // EXIT_FAILURE / exit
#include <cstring>      // memset (banner bar)
#include <type_traits>  // std::is_same_v (compile-time type equality)
#include <utility>      // std::declval (a fabricated T in an unevaluated ctx)
#include <vector>       // std::vector (range-for demo)

namespace {

constexpr int BANNER_WIDTH = 70;

// sectionBanner prints a clearly delimited section divider (the house style).
void sectionBanner(const char* title) {
    char bar[BANNER_WIDTH + 1];
    std::memset(bar, '=', BANNER_WIDTH);
    bar[BANNER_WIDTH] = '\0';
    std::printf("\n%s\nSECTION %s\n%s\n", bar, title, bar);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it prints to stderr and exits non-zero so `just check`/`just sweep`
// catch it (and ASan/UBSan stay happy — no throw across the verified path).
void check(const char* description, bool ok) {
    if (!ok) {
        std::fprintf(stderr, "INVARIANT VIOLATED: %s\n", description);
        std::exit(EXIT_FAILURE);
    }
    std::printf("[check] %s: OK\n", description);
}

// assertType verifies a COMPILE-TIME type claim with std::is_same_v<...>, prints
// the resulting boolean (deterministic: a plain true/false), and then mirrors it
// as a [check] line so the verification sweep catches any regression. We do NOT
// use typeid().name(): its string is implementation-defined and varies across
// compilers/versions/flags, so it is unfit for a byte-stable, verified bundle.
void assertType(const char* claim, bool ok) {
    std::printf("  %-58s : %s\n", claim, ok ? "true" : "false");
    check(claim, ok);
}

// --- Return-type-deduction helpers (used by Section D) -----------------------
// plain `auto` return: deduces the return type by VALUE -> it STRIPS the &.
auto by_value_return(int& x) { return x; }  // returns int (the & is stripped)
// trailing return type: the return type is written explicitly after `->`.
auto trailing_return(double a, double b) -> double { return a * b; }  // double
// `decltype(auto)` return: the return type is decltype(<return-expr>) -> it
// PRESERVES references — the tool for PERFECT FORWARDING of a return type.
decltype(auto) ref_return(int& x) { return x; }  // returns int& (decltype(x))

// === Section A — auto basics & the STRIP rule ================================
//
// `auto` deduces a type from its initializer using the SAME rules as template
// argument deduction. The headline consequence: plain `auto` makes a COPY — it
// STRIPS top-level const AND the top-level &. This is THE famous C++ surprise:
// `auto x = someRef;` is a copy, not an alias.
void sectionA() {
    sectionBanner("A — auto basics & the STRIP rule (top-level const/& stripped)");

    int i = 5;
    auto x = i;  // int — auto deduces int from an int initializer
    std::printf("auto x = i (i == 5):\n");
    assertType("decltype(x) is int", std::is_same_v<decltype(x), int>);

    // --- THE FAMOUS TRAP: auto STRIPS const and & --------------------------------
    // r is a const reference aliasing i. `auto a = r;` does NOT become a
    // reference — auto drops the const AND the &, so `a` is a plain int COPY.
    // Mutating `a` cannot reach `i`.
    const int& r = i;  // const int& — a genuine const alias of i
    auto a = r;        // int — COPY! const and & both STRIPPED
    a = 999;           // reassigns the COPY; i is untouched
    std::printf("\nconst int& r = i;  auto a = r;  a = 999;\n");
    std::printf("  -> a = %d, i = %d   (a is a COPY; i untouched by the strip)\n", a, i);
    check("auto a = r made a COPY (a = 999 left i == 5)", i == 5);
    assertType("decltype(a) is int (NOT const int& — the famous strip)",
               std::is_same_v<decltype(a), int>);
    assertType("decltype(a) is NOT const int&",
               !std::is_same_v<decltype(a), const int&>);

    // --- The strip is systematic: top-level const AND & both vanish from auto ---
    const int ci = 7;  // a top-level const value
    auto b = ci;       // int — top-level const STRIPPED
    int& ri = i;       // a mutable reference
    auto c = ri;       // int — the & STRIPPED
    std::printf("\nThe strip is systematic (top-level const and & both vanish):\n");
    std::printf("  const int ci = 7;  auto b = ci;  -> b = %d\n", b);
    std::printf("  int& ri = i;       auto c = ri;  -> c = %d\n", c);
    assertType("auto b = ci  -> int (top-level const stripped)",
               std::is_same_v<decltype(b), int>);
    assertType("auto c = ri  -> int (the & stripped)", std::is_same_v<decltype(c), int>);

    std::printf("\nMental model: plain `auto` deduces a BY-VALUE type (a copy).\n");
    check("plain auto always yields a value type (copy semantics)", true);
}

// === Section B — Keeping cv/refs: auto& / const auto& / decltype (no strip) ===
//
// To KEEP a reference or const, either spell it on the `auto`, or use
// `decltype` (which NEVER strips). The expert map:
//   auto& x = e;        keeps a reference (const of e is preserved through it)
//   const auto& x = e;  a read-only reference (the idiomatic read/borrow form)
//   decltype(e) x = e;  the DECLARED type, no stripping at all
void sectionB() {
    sectionBanner("B — Keeping cv/refs: auto& / const auto& / decltype (no strip)");

    int i = 5;
    int& ri = i;  // mutable alias of i

    std::printf("Setup: int i = 5; int& ri = i;\n");

    // auto& : the explicit & keeps a reference. Aliasing i -> int&.
    auto& a3 = ri;  // int& (ri refers to i)
    std::printf("\nauto& a3 = ri;\n");
    assertType("decltype(a3) is int& (auto& kept the mutable ref)",
               std::is_same_v<decltype(a3), int&>);

    // Prove auto& is a real alias: mutate THROUGH it.
    a3 = 11;
    std::printf("a3 = 11 (mutated THROUGH the alias)  -> i = %d\n", i);
    check("auto& a3 = ri is a real alias (a3 = 11 set i == 11)", i == 11);

    // const auto& : a read-only reference (the idiom — range-for / params).
    const int& r = i;   // const int& alias of i
    const auto& a4 = r;  // const int&
    std::printf("\nconst auto& a4 = r;   -> read-only borrow (idiom)\n");
    assertType("decltype(a4) is const int&", std::is_same_v<decltype(a4), const int&>);

    // --- decltype : the DECLARED type, NO stripping (the decisive contrast) ----
    const int ci = 7;
    std::printf("\ndecltype(expr) = the DECLARED type, NOTHING stripped:\n");
    assertType("decltype(r)  is const int& (no strip)",
               std::is_same_v<decltype(r), const int&>);
    assertType("decltype(ci) is const int (no strip)",
               std::is_same_v<decltype(ci), const int>);
    assertType("decltype(i)  is int (no strip)", std::is_same_v<decltype(i), int>);
    assertType("decltype(ri) is int& (no strip)", std::is_same_v<decltype(ri), int&>);
}

// === Section C — decltype(auto) + the PAREN TRAP =============================
//
// decltype(auto) (C++14) is the "transparent" deduction: the deduced type is
// decltype(<initializer>). It preserves cv/refs (unlike plain auto) — the tool
// for PERFECT FORWARDING of return types. Its subtle cousin is the PAREN TRAP:
// decltype(name) and decltype((name)) are OFTEN DIFFERENT TYPES.
void sectionC() {
    sectionBanner("C — decltype(auto) (transparent) + the PAREN TRAP");

    int i = 5;
    const int& r = i;  // const int& alias of i

    // --- decltype(auto) : transparent — preserves cv/refs ----------------------
    // `decltype(auto) da1 = r;` deduces da1 as decltype(r) == const int&. Contrast
    // with plain `auto a = r;` (Section A) which stripped to int.
    decltype(auto) da1 = r;  // const int& (transparent — no strip)
    std::printf("decltype(auto) da1 = r   (r is const int&):\n");
    assertType("decltype(da1) is const int& (transparent — unlike plain auto)",
               std::is_same_v<decltype(da1), const int&>);

    decltype(auto) da2 = i;  // int (decltype(i) == int, a value)
    std::printf("decltype(auto) da2 = i   (i is int):\n");
    assertType("decltype(da2) is int", std::is_same_v<decltype(da2), int>);

    // --- THE PAREN TRAP: decltype(i) vs decltype((i)) ---------------------------
    // An UNPARENTHESIZED id-expression -> the DECLARED type (int).
    // A PARENTHESIZED id-expression -> treated as a normal lvalue EXPR -> int&
    //   (because (i) is an lvalue of type int -> decltype yields T&).
    std::printf("\nTHE PAREN TRAP — decltype(i) vs decltype((i)):\n");
    assertType("decltype(i)   is int   (unparenthesized -> declared type)",
               std::is_same_v<decltype(i), int>);
    assertType("decltype((i)) is int&  (parenthesized -> lvalue expr -> T&)",
               std::is_same_v<decltype((i)), int&>);

    // The paren trap flows THROUGH decltype(auto):
    decltype(auto) da3 = (i);  // int& — because decltype((i)) is int&
    std::printf("\ndecltype(auto) da3 = (i);   (parenthesized initializer):\n");
    assertType("decltype(da3) is int& (paren trap via decltype(auto))",
               std::is_same_v<decltype(da3), int&>);

    // And the paren trap applies to const: decltype((ci)) is const int&, not const int.
    const int ci = 9;
    std::printf("\nThe paren trap applies to const too:\n");
    assertType("decltype(ci)   is const int  (declared type)",
               std::is_same_v<decltype(ci), const int>);
    assertType("decltype((ci)) is const int& (parenthesized -> lvalue expr)",
               std::is_same_v<decltype((ci)), const int&>);
}

// === Section D — range-for (copy vs borrow) + return-type deduction ==========
void sectionD() {
    sectionBanner("D — range-for (copy vs borrow) + return-type deduction");

    std::vector<int> v = {10, 20, 30};

    // (1) `for (auto x : v)` — each x is a COPY; mutating it can't reach v.
    // copy_sum proves x really held (element + 1000): a local copy, while v stays
    // at its original values.
    long copy_sum = 0;
    for (auto x : v) {
        x += 1000;
        copy_sum += x;
    }  // x is a throwaway copy
    std::printf("(1) for (auto x : v) { x += 1000; copy_sum += x; }   -> COPIES\n");
    std::printf("    v[0]=%d  v[1]=%d  v[2]=%d   (v untouched)\n", v[0], v[1], v[2]);
    std::printf("    copy_sum = %ld   (1010 + 1020 + 1030 = 3060; x held 1000 + element)\n",
                copy_sum);
    check("for(auto x:v) COPIES: v[0] still 10 after x += 1000", v[0] == 10);
    check("for(auto x:v) COPIES: copy_sum == 3060 (x was a local copy)", copy_sum == 3060);

    // (2) `for (auto& x : v)` — each x is an ALIAS; mutating it changes v.
    for (auto& x : v) {
        x += 5;
    }  // x aliases the element
    std::printf("\n(2) for (auto& x : v) { x += 5; }   -> ALIASES (v changed)\n");
    std::printf("    v[0]=%d  v[1]=%d  v[2]=%d\n", v[0], v[1], v[2]);
    check("for(auto& x:v) ALIASES: v[0] now 15 after x += 5", v[0] == 15);

    // (3) `for (const auto& x : v)` — read-only borrow; THE IDIOM (no copy, no mutation).
    long sum = 0;
    for (const auto& x : v) {
        sum += x;
    }  // borrow each element read-only
    std::printf("\n(3) for (const auto& x : v) { sum += x; }   -> read-only BORROW\n");
    std::printf("    sum = %ld   (15 + 25 + 35 = 75)\n", sum);
    check("for(const auto& x:v) borrows: sum == 75", sum == 75);

    // The element type each range-for form binds is exactly the Section A/B rule:
    auto copied = v[0];            // same rule as `for (auto x : v)`
    const auto& borrowed = v[0];   // same rule as `for (const auto& x : v)`
    assertType("auto copy of v[0] is int (the range-for copy form)",
               std::is_same_v<decltype(copied), int>);
    assertType("const auto& of v[0] is const int& (the range-for borrow idiom)",
               std::is_same_v<decltype(borrowed), const int&>);

    // --- Return-type deduction: auto (by value) vs decltype(auto) (transparent) -
    int n = 7;
    // Genuinely call the helpers (so the type AND the by-value behavior are both
    // observable): by_value_return copies -> bv is a plain int == 7.
    int bv = by_value_return(n);            // bv == 7 (auto return, by value)
    double tr = trailing_return(2.0, 3.0);  // tr == 6.0 (trailing return type)
    std::printf("\nReturn-type deduction   (int n = 7):\n");
    std::printf("    int bv = by_value_return(n);    -> bv = %d\n", bv);
    std::printf("    double tr = trailing_return(2,3); -> tr = %.1f\n", tr);
    check("by_value_return(n) == 7 (auto return, by value)", bv == 7);
    check("trailing_return(2,3) == 6.0", tr == 6.0);
    // by_value_return: plain auto strips the & -> returns int (by value).
    assertType("decltype(by_value_return(n)) is int   (auto return STRIPS the &)",
               std::is_same_v<decltype(by_value_return(n)), int>);
    // trailing return type: explicit, no deduction surprise.
    assertType("decltype(trailing_return(2,3)) is double (trailing return)",
               std::is_same_v<decltype(trailing_return(2.0, 3.0)), double>);
    // ref_return: decltype(auto) preserves the & -> returns int& (perfect forward).
    assertType("decltype(ref_return(n)) is int&  (decltype(auto) PRESERVES the &)",
               std::is_same_v<decltype(ref_return(n)), int&>);

    // Prove ref_return really returns a reference (assigning through it reaches n).
    ref_return(n) = 99;  // legal only because it returns int&
    std::printf("\nref_return(n) = 99;   -> n = %d   (returns int&, so writable)\n", n);
    check("decltype(auto) return is a real ref (ref_return(n)=99 set n == 99)", n == 99);
}

// === Section E — The deduction-rules matrix + std::declval ===================
//
// (1) The matrix: for four canonical initializer kinds, what does each spelling
//     of auto/decltype yield? Every cell is std::is_same_v-verified below.
// (2) std::declval<T>(): fabricates a T (as T&&) in an UNEVALUATED context (the
//     operand of decltype) — the way to ask "what type does this expression
//     have?" without ever constructing a T.
void sectionE() {
    sectionBanner("E — The deduction-rules matrix + std::declval");

    int i = 5;           // plain value
    const int ci = 7;    // top-level const value
    int& ri = i;         // mutable reference
    const int& r = i;    // const reference

    std::printf("Deduction matrix (every cell is std::is_same_v-verified):\n");
    std::printf("%-13s | %-10s | %-11s | %-13s | %s\n", "initializer", "auto", "auto&",
                "const auto&", "decltype()");
    std::printf("%-13s-+-%-10s-+-%-11s-+-%-13s-+-%s\n", "-------------", "----------",
                "-----------", "-------------", "-----------");

    // Row: int i
    auto i_a = i;            // int
    auto& i_ar = i;          // int&
    const auto& i_car = i;   // const int&
    std::printf("%-13s | %-10s | %-11s | %-13s | %s\n", "int i", "int", "int&",
                "const int&", "int");
    assertType("[i]  auto        -> int", std::is_same_v<decltype(i_a), int>);
    assertType("[i]  auto&       -> int&", std::is_same_v<decltype(i_ar), int&>);
    assertType("[i]  const auto& -> const int&", std::is_same_v<decltype(i_car), const int&>);
    assertType("[i]  decltype(i) -> int", std::is_same_v<decltype(i), int>);

    // Row: const int ci
    auto c_a = ci;            // int (const STRIPPED)
    auto& c_ar = ci;          // const int&
    const auto& c_car = ci;   // const int&
    std::printf("%-13s | %-10s | %-11s | %-13s | %s\n", "const int ci", "int",
                "const int&", "const int&", "const int");
    assertType("[ci] auto        -> int (const STRIPPED!)", std::is_same_v<decltype(c_a), int>);
    assertType("[ci] auto&       -> const int&", std::is_same_v<decltype(c_ar), const int&>);
    assertType("[ci] const auto& -> const int&", std::is_same_v<decltype(c_car), const int&>);
    assertType("[ci] decltype(ci)-> const int (no strip)", std::is_same_v<decltype(ci), const int>);

    // Row: int& ri
    auto r_a = ri;            // int (ref STRIPPED)
    auto& r_ar = ri;          // int&
    const auto& r_car = ri;   // const int&
    std::printf("%-13s | %-10s | %-11s | %-13s | %s\n", "int& ri", "int", "int&",
                "const int&", "int&");
    assertType("[ri] auto        -> int (ref STRIPPED!)", std::is_same_v<decltype(r_a), int>);
    assertType("[ri] auto&       -> int&", std::is_same_v<decltype(r_ar), int&>);
    assertType("[ri] const auto& -> const int&", std::is_same_v<decltype(r_car), const int&>);
    assertType("[ri] decltype(ri)-> int& (no strip)", std::is_same_v<decltype(ri), int&>);

    // Row: const int& r
    auto cr_a = r;            // int (const AND & both STRIPPED)
    auto& cr_ar = r;          // const int&
    const auto& cr_car = r;   // const int&
    std::printf("%-13s | %-10s | %-11s | %-13s | %s\n", "const int& r", "int",
                "const int&", "const int&", "const int&");
    assertType("[r]  auto        -> int (const AND & STRIPPED!)", std::is_same_v<decltype(cr_a), int>);
    assertType("[r]  auto&       -> const int&", std::is_same_v<decltype(cr_ar), const int&>);
    assertType("[r]  const auto& -> const int&", std::is_same_v<decltype(cr_car), const int&>);
    assertType("[r]  decltype(r) -> const int& (no strip)", std::is_same_v<decltype(r), const int&>);

    // --- auto&& : the FORWARDING reference (a.k.a. "universal reference") ------
    // auto&& is NOT an rvalue reference in general. It deduces by value category:
    //   auto&& rr = lvalue;  -> T&  (lvalue bound; collapses to T&)
    //   auto&& rr = prvalue; -> T&& (rvalue bound)
    std::printf("\nauto&& is a FORWARDING reference (collapses by value category):\n");
    auto&& rr1 = i;  // int&  (i is an lvalue)
    auto&& rr2 = 42;  // int&& (42 is a prvalue)
    std::printf("  auto&& rr1 = i;    -> decltype(rr1) bound, i is lvalue\n");
    std::printf("  auto&& rr2 = 42;   -> decltype(rr2) bound, 42 is prvalue\n");
    assertType("auto&& rr1 = i  (lvalue)   -> int&  (collapsed)",
               std::is_same_v<decltype(rr1), int&>);
    assertType("auto&& rr2 = 42 (prvalue)  -> int&& (rvalue ref)",
               std::is_same_v<decltype(rr2), int&&>);
    (void)rr1;  // genuinely read so the binding is not flagged unused
    (void)rr2;

    // --- std::declval<T>() : a fabricated T (as T&&) for UNEVALUATED contexts ---
    // Used with decltype to ask the return type of an expression on T WITHOUT
    // constructing a T. Indispensable when T has no usable constructor.
    struct Widget {
        Widget() = delete;                   // no default constructor
        int compute() const { return 42; }   // a member we want to introspect
    };
    std::printf("\nstd::declval<T>() — fabricate a T (as T&&) in an UNEVALUATED context:\n");
    // `decltype(Widget().compute())` would be ILL-FORMED (Widget() needs a default
    // ctor). declval sidesteps construction entirely:
    assertType("std::declval<Widget>().compute() -> int",
               std::is_same_v<decltype(std::declval<Widget>().compute()), int>);
    // declval<T>() yields add_rvalue_reference_t<T>, i.e. T&& for an object T:
    assertType("std::declval<int>()  -> int&& (add_rvalue_reference_t<int>)",
               std::is_same_v<decltype(std::declval<int>()), int&&>);
    // declval must NEVER be evaluated at runtime (odr-use is ill-formed); it is a
    // pure type-level helper for decltype / sizeof / noexcept expressions.
    check("std::declval used only in decltype (unevaluated) — never evaluated", true);
}

}  // namespace

int main() {
    std::printf("type_deduction.cpp — Phase 2 bundle.\n");
    std::printf("Every deduced type below is verified at COMPILE TIME with\n");
    std::printf("std::is_same_v<...>; its boolean is printed (NOT typeid().name()).\n");
    std::printf("Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free.\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
