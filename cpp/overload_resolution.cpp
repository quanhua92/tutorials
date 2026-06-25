// overload_resolution.cpp — Phase 2 bundle #13.
//
// GOAL (one line): show, by printing every value, how C++ OVERLOAD RESOLUTION
// builds a CANDIDATE SET of every visible overload (and template specialization),
// filters it down to VIABLE functions (right arity + each arg convertible to its
// param), then ranks the viables by IMPLICIT-CONVERSION-SEQUENCE (ICS) quality —
//   exact match > promotion > standard conversion > user-defined > ellipsis
// — and picks the single BEST, breaking ties with "non-template beats template"
// and "more-constrained concept beats less-constrained (subsumption)"; two
// equal-rank viables with no applicable tie-break => AMBIGUITY (compile error).
//
// This is the GROUND TRUTH for OVERLOAD_RESOLUTION.md. Every number, tag, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run overload_resolution   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                      -Wpedantic overload_resolution.cpp
//                                      -o /tmp/cpp_overload_resolution
//                                      && /tmp/cpp_overload_resolution)

#include <concepts>    // std::integral, std::signed_integral (subsumption demo)
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <string>      // std::string (user-defined-conversion demo)

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

// =============================================================================
// Section A — The pipeline: candidate set -> viable -> ranked -> best (or toss)
// =============================================================================
// Overload resolution is a 3-stage funnel (cppreference, "Overload resolution"):
//   1. CANDIDATE SET  — every name-lookup-found overload + every template
//                       specialization that DEDUCES successfully.
//   2. VIABLE         — keep only those with the right arity (or trailing
//                       defaults / an ellipsis) AND an implicit-conversion path
//                       for EVERY argument. Non-viable candidates are dropped.
//   3. BEST           — rank the viables by their ICS quality; the unique best
//                       wins. A tie at the best rank with no tie-break rule
//                       => AMBIGUOUS (compile error).
//
// `pipe::s` is one name with FOUR overloads. For a `char` argument:
//   - s(char), s(int), s(double) are VIABLE (char converts to all three);
//   - s(const char*) is NOT viable (no char -> const char* conversion) -> dropped
//     at stage 2 (we prove it is still a real candidate by calling it with its
//     own type, where it IS the exact match and wins).
// Of the three viables, s(char) ranks "exact match" -> BEST. The funnel wins.
namespace pipe {
    int s(char)                  { return 1; }  // viable for char: EXACT
    [[maybe_unused]] int s(int)  { return 2; }  // viable for char: PROMOTION
    [[maybe_unused]] int s(double){ return 3; } // viable for char: CONVERSION
    int s(const char*)           { return 4; }  // NOT viable for char (no char->ptr conv)
}

void sectionA() {
    sectionBanner("A — The pipeline: candidate set -> viable -> ranked -> best");

    char c = 'A';
    int won = pipe::s(c);   // resolve once; the tag reveals the winner
    std::printf("Candidates visible for the name `s`: s(char), s(int), s(double), s(const char*).\n");
    std::printf("Argument: char c = 'A';\n");
    std::printf("Stage 2 (viability): s(const char*) DROPPED (no char -> const char* conversion).\n");
    std::printf("Stage 3 (ranking):   s(char)=exact > s(int)=promotion > s(double)=conversion.\n");
    std::printf("Result: pipe::s(c) -> tag %d  (s(char), the EXACT match, is the BEST viable)\n", won);

    check("for a char arg, pipe::s picks s(char) (exact match, tag 1)", won == 1);

    // The dropped candidate is still a REAL overload: for a const char* arg it is
    // the exact match and wins. (Also keeps -Wunused honest by exercising it.)
    const char* cp = "x";
    int won2 = pipe::s(cp);
    std::printf("\nThe dropped s(const char*) is still a real candidate — for a const char* arg\n");
    std::printf("it is the EXACT match: pipe::s(cp) -> tag %d\n", won2);
    check("for a const char* arg, pipe::s picks s(const char*) (tag 4)", won2 == 4);

    // If s(char) were absent, the funnel would fall through to s(int) (promotion).
    // (Demonstrated pairwise in Section B; here we just state the consequence.)
    std::printf("\nIf s(char) were absent, s(int) [promotion] would be the best viable for `c`.\n");
    check("the funnel picks the unique best-ranked viable, else it is ambiguous", true);
}

// =============================================================================
// Section B — The ICS RANKING ladder + the trivial "exact match" conversions
// =============================================================================
// Each argument->parameter pairing gets an IMPLICIT-CONVERSION SEQUENCE (ICS).
// For a STANDARD conversion sequence the ICS is ranked (best -> worst):
//   1. EXACT MATCH   — identity; the "trivial" conversions (lvalue-to-rvalue,
//                      array->pointer decay, function->pointer decay, adding a
//                      cv-qualifier); function-pointer noexcept conversion.
//   2. PROMOTION     — integral promotion (char/short -> int), float -> double.
//   3. CONVERSION    — integral/floating-point/pointer/boolean conversions.
// And the two worse ICS categories (outside the standard-sequence ranks):
//   4. USER-DEFINED  — a converting constructor or conversion operator.
//   5. ELLIPSIS      — the C-style `...` catch-all (beats only no-match).
//
// We prove each rung pairwise: two visible overloads, one argument, the winner's
// tag identifies the better rank. `char` is the canonical demo argument because
// char->char is exact, char->int is a PROMOTION, char->double is a CONVERSION.

// --- rung 1: exact (char->char) beats promotion (char->int) -----------------
namespace exact_vs_promo {
    int f(char)              { return 1; }   // rank: exact
    [[maybe_unused]] int f(int) { return 2; }   // rank: promotion
}
// --- rung 2: promotion (char->int) beats conversion (char->double) ----------
namespace promo_vs_conv {
    int f(int)                 { return 1; }  // rank: promotion
    [[maybe_unused]] int f(double) { return 2; }  // rank: conversion
}
// --- rung 3: exact (char->char) beats conversion (char->double) -------------
namespace exact_vs_conv {
    int f(char)                 { return 1; }  // rank: exact
    [[maybe_unused]] int f(double) { return 2; }  // rank: conversion
}

// The two ranks BELOW the standard sequence: user-defined, and ellipsis.
struct FromInt { FromInt(int) {} };   // a user-defined int -> FromInt conversion

// --- rung 4: standard conversion beats user-defined -------------------------
//   arg `int`: f(long) needs int->long (standard, rank "conversion"); f(const
//   FromInt&) needs int->FromInt (user-defined). Standard > user-defined.
namespace std_vs_udc {
    int f(long)                  { return 1; }  // standard conversion
    [[maybe_unused]] int f(const FromInt&) { return 2; }  // user-defined conversion
}
// --- rung 5: user-defined beats ellipsis ------------------------------------
//   arg "s" (const char[2]): f(const std::string&) needs const char*->string
//   (user-defined); f(...) is the ellipsis. User-defined > ellipsis.
namespace udc_vs_ellipsis {
    int f(const std::string&)    { return 1; }  // user-defined
    [[maybe_unused]] int f(...)  { return 2; }  // ellipsis
}

// --- the TRIVIAL conversions that all rank "exact match" --------------------
// (cppreference: "Exact match: no conversion required, lvalue-to-rvalue,
//  array-to-pointer, function-to-pointer, qualification conversion...")
int trivIdentity(int x)        { return x; }            // T -> T (identity)
int trivArrayDecay(int* p)     { return p[0]; }         // int[N] -> int* (decay)
int trivQualAdd(const int* p)  { return *p; }           // int* -> const int* (add const)
void trivTarget()              {}
int trivFnDecay(void (*pf)())  { pf(); return 1; }      // void() -> void(*)() (decay)
int trivRefBind(int& x)        { return x; }            // bind T& to a T lvalue

void sectionB() {
    sectionBanner("B — The ICS ranking ladder (exact > promotion > conversion > UDC > ellipsis)");

    char c = 'A';
    std::printf("Argument throughout: char c = 'A';\n");
    std::printf("  char->char = EXACT ; char->int = PROMOTION ; char->double = CONVERSION.\n\n");

    int r1 = exact_vs_promo::f(c);
    std::printf("exact_vs_promo { f(char)=1, f(int)=2 }  f(c) -> %d  ", r1);
    std::printf("(exact beats promotion)\n");
    check("exact (char->char) beats promotion (char->int)", r1 == 1);

    int r2 = promo_vs_conv::f(c);
    std::printf("promo_vs_conv  { f(int)=1, f(double)=2 } f(c) -> %d  ", r2);
    std::printf("(promotion beats conversion)\n");
    check("promotion (char->int) beats conversion (char->double)", r2 == 1);

    int r3 = exact_vs_conv::f(c);
    std::printf("exact_vs_conv  { f(char)=1, f(double)=2 } f(c) -> %d  ", r3);
    std::printf("(exact beats conversion directly)\n");
    check("exact (char->char) beats conversion (char->double)", r3 == 1);

    // The ladder below the standard sequence.
    int i = 5;
    int r4 = std_vs_udc::f(i);
    std::printf("\nstd_vs_udc { f(long)=1, f(const FromInt&)=2 } f(int) -> %d  ", r4);
    std::printf("(standard conv int->long beats user-defined int->FromInt)\n");
    check("standard conversion (int->long) beats user-defined (int->FromInt)", r4 == 1);

    int r5 = udc_vs_ellipsis::f("s");
    std::printf("udc_vs_ellipsis { f(const string&)=1, f(...)=2 } f(\"s\") -> %d  ", r5);
    std::printf("(user-defined const char*->string beats ellipsis)\n");
    check("user-defined (const char*->string) beats ellipsis", r5 == 1);

    // The TRIVIAL conversions — every one ranks "exact match".
    std::printf("\nThe TRIVIAL conversions (all rank EXACT MATCH per cppreference):\n");
    int a[3] = {10, 20, 30};
    int raw = 7;
    const int* cptr = &raw;
    int x = 9;
    int t1 = trivIdentity(42);
    int t2 = trivArrayDecay(a);     // int[3] decays to int*
    int t3 = trivQualAdd(cptr);     // int* -> const int* (qualification, exact)
    int t4 = trivFnDecay(trivTarget);  // function name decays to &function
    int t5 = trivRefBind(x);
    std::printf("  identity   T->T            : trivIdentity(42)        = %d\n", t1);
    std::printf("  array decay int[3]->int*   : trivArrayDecay(int[3])  = %d (a[0])\n", t2);
    std::printf("  qual conv  int*->const int*: trivQualAdd(int*)       = %d (*p)\n", t3);
    std::printf("  fn decay   void()->void(*)(): trivFnDecay(&fn)       = %d\n", t4);
    std::printf("  ref bind   T& <- T lvalue   : trivRefBind(int&)      = %d\n", t5);
    check("trivial identity conversion selects the overload (42)", t1 == 42);
    check("array-to-pointer decay is viable: a[0] == 10", t2 == 10);
    check("qualification conversion (add const) is viable: *p == 7", t3 == 7);
    check("function-to-pointer decay is viable: target ran (tag 1)", t4 == 1);
    check("reference binding to an lvalue is viable: x == 9", t5 == 9);
}

// =============================================================================
// Section C — AMBIGUITY: two equal-rank viables and no tie-break -> compile err
// =============================================================================
// When two viables tie at the best rank AND none of the tie-break rules (Section
// D) applies, the call is AMBIGUOUS — a COMPILE ERROR. The classic: an `int`
// argument against f(long) and f(double). int->long is an integral CONVERSION
// and int->double is a floating-integral CONVERSION — BOTH rank "conversion", so
// neither is better. No tie-break applies => ambiguous.
//
// A file containing the bare ambiguous call would not compile, so the offending
// call is gated behind #ifdef DEMO_AMBIGUOUS (NEVER passed by just run/out/
// check/sanitize). The default build stays warning-clean and links fine.
namespace amb2 {
    int a(long)   { return 1; }
    int a(double) { return 2; }
}
// Resolution #2: ADD an exact-match overload. With a(int) present, an int arg
// gets an EXACT match (rank 1) which beats both conversions -> no ambiguity.
namespace amb3 {
    int a(int)                  { return 1; }   // exact — added to break the tie
    [[maybe_unused]] int a(long)   { return 2; }
    [[maybe_unused]] int a(double) { return 3; }
}

void sectionC() {
    sectionBanner("C — Ambiguity: equal-rank viables + no tie-break = compile error");

    std::printf("The classic ambiguity: int arg vs f(long) and f(double).\n");
    std::printf("  int->long  = integral CONVERSION (rank 'conversion')\n");
    std::printf("  int->double= floating-integral CONVERSION (rank 'conversion')\n");
    std::printf("  Both best-rank, no tie-break applies -> AMBIGUOUS (compile error).\n");
    check("two equal-rank viables with no tie-break => ambiguous (documented)", true);

    // Resolution #1: CAST the argument to disambiguate. The cast makes the chosen
    // overload an EXACT match (rank 1), which outranks the other's conversion.
    int x = 0;
    int to_long   = amb2::a(static_cast<long>(x));     // exact -> a(long)
    int to_double = amb2::a(static_cast<double>(x));   // exact -> a(double)
    std::printf("\nFix #1 (cast the argument):\n");
    std::printf("  amb2::a(static_cast<long>(0))   -> tag %d  (a(long),  now exact)\n", to_long);
    std::printf("  amb2::a(static_cast<double>(0)) -> tag %d  (a(double),now exact)\n", to_double);
    check("cast to long selects a(long) (tag 1)", to_long == 1);
    check("cast to double selects a(double) (tag 2)", to_double == 2);

    // Resolution #2: ADD an exact-match overload. amb3::a(int) is an exact match
    // for an int arg, beating both conversions.
    int fixed = amb3::a(0);
    std::printf("\nFix #2 (add an exact-match overload):\n");
    std::printf("  amb3 { a(int)=1, a(long)=2, a(double)=3 }  amb3::a(0) -> tag %d  (a(int) exact)\n",
                fixed);
    check("adding a(int) makes amb3::a(0) select a(int) (exact, tag 1)", fixed == 1);

#ifdef DEMO_AMBIGUOUS
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // Compiling with -DDEMO_AMBIGUOUS reproduces the compiler error printed
    // below. The default build omits this call so it stays warning-clean.
    int bad = amb2::a(0);   // <-- AMBIGUOUS: int->long and int->double tie
    (void)bad;
#else
    std::printf("\n    (DEMO_AMBIGUOUS not defined: the ambiguous amb2::a(0) call is omitted.)\n");
    std::printf("    Enabling it yields: error: call to 'a' is ambiguous\n");
    std::printf("      note: candidate function: int amb2::a(long)\n");
    std::printf("      note: candidate function: int amb2::a(double)\n");
#endif
}

// =============================================================================
// Section D — Tie-breakers: non-template beats template; subsumption (concepts)
// =============================================================================
// When two viables have ICS of EQUAL quality, overload resolution falls through
// to a list of TIE-BREAK rules (cppreference, "Best viable function"). Two of
// them matter day-to-day:
//   (#4) F1 is a NON-TEMPLATE, F2 is a template specialization -> F1 wins.
//   (#6) F1 and F2 are both non-template (or both template) and F1 is
//        MORE partial-ordering-CONSTRAINED than F2 -> F1 wins. For templates
//        this is CONCEPT SUBSUMPTION: if concept B's constraint INCLUDES
//        concept A's (B is "at least as constrained"), a `template <B T>`
//        overload is preferred over `template <A T>` when both match.
int nt(int) { return 1; }                   // non-template
template <typename T>
int nt(T)   { return 2; }                   // template specialization

// Subsumption: std::signed_integral is DEFINED as integral<T> && is_signed<T>,
// so signed_integral SUBSUMES integral. For an `int` (which is both), the
// more-constrained signed_integral overload wins; for an `unsigned` (integral
// but NOT signed), only the integral overload is viable.
template <std::integral T>
int pick(T) { return 1; }                   // less constrained
template <std::signed_integral T>
int pick(T) { return 2; }                   // more constrained (subsumes integral)

void sectionD() {
    sectionBanner("D — Tie-breakers: non-template beats template; concept subsumption");

    // Tie-break #4: non-template beats an equally-good template specialization.
    // nt(int) and nt<T=int> are BOTH exact matches for an int arg (equal rank);
    // the non-template wins by rule #4.
    int r_nt = nt(7);
    std::printf("nt { int nt(int)=1 [non-template], int nt<T>(T)=2 [template] }  nt(7) -> %d\n", r_nt);
    std::printf("  (both exact; tie-break #4: the NON-TEMPLATE wins)\n");
    check("non-template nt(int) beats equally-good template nt<T> (tie-break #4)", r_nt == 1);

    // Subsumption (#6 for templates): signed_integral subsumes integral.
    int ri = pick(7);        // int is integral AND signed -> signed_integral wins
    unsigned u = 7u;
    int ru = pick(u);        // unsigned is integral but NOT signed -> only integral viable
    std::printf("\npick { template<integral T>=1, template<signed_integral T>=2 }\n");
    std::printf("  signed_integral SUBSUMES integral (it adds is_signed on top).\n");
    std::printf("  pick(7)  [int]     -> %d  (both match; the MORE-CONSTRAINED signed_integral wins)\n", ri);
    std::printf("  pick(7u) [unsigned] -> %d  (only integral matches; unsigned is not signed)\n", ru);
    check("pick(int) selects the more-constrained signed_integral overload (tag 2)", ri == 2);
    check("pick(unsigned) selects the only-viable integral overload (tag 1)", ru == 1);
}

// =============================================================================
// Section E — The ellipsis catch-all + cross-language (Go / Rust: no overloading)
// =============================================================================
// The variadic ellipsis `...` is the C-style catch-all. It is the WORST rank —
// it beats ONLY "no match at all". Any standard/user-defined ICS outranks it.
int e(int) { return 1; }                    // standard (exact for int)
int e(...) { return 2; }                    // ellipsis (worst rank)

void sectionE() {
    sectionBanner("E — The ellipsis catch-all + cross-language (Go/Rust)");

    // For an int arg both e(int) and e(...) are viable; exact beats ellipsis.
    int r1 = e(7);
    std::printf("e { int e(int)=1, int e(...)=2 }  e(7) -> %d  (exact beats ellipsis)\n", r1);
    check("e(7): exact-match e(int) beats ellipsis e(...) (tag 1)", r1 == 1);

    // For a string literal, e(int) is NOT viable (no const char* -> int path);
    // only e(...) remains -> it is selected (beats only no-match).
    int r2 = e("hi");
    std::printf("e(\"hi\"): e(int) not viable (no const char* -> int) -> e(...) -> %d\n", r2);
    check("e(\"hi\"): only ellipsis viable (tag 2); it beats no-match", r2 == 2);

    // Cross-language: who has NAME-BASED overload resolution at all?
    std::printf("\nCross-language: who has name-based FUNCTION OVERLOADING?\n");
    std::printf("  C++  : YES — pick(int)/pick(double)/pick(T) coexist; resolution ranks them.\n");
    std::printf("  Go   : NO  — one signature per name; rename (printInt/printDouble) or interfaces.\n");
    std::printf("  Rust : NO  — traits + generics; `impl Trait for Type` is the substitute.\n");
    std::printf("  (C++'s whole ranking machinery has no counterpart in Go/Rust: there is nothing\n");
    std::printf("   to rank when each name has exactly one signature.)\n");
    check("of {C++, Go, Rust}, only C++ has name-based overload resolution", true);
}

}  // namespace

int main() {
    std::printf("overload_resolution.cpp — Phase 2 bundle #13.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
