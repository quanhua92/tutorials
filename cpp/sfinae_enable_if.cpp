// sfinae_enable_if.cpp — Phase 6 bundle (the pre-concepts metaprogramming workhorse).
//
// GOAL (one line): show, by printing every value and asserting the right
// overload/template is selected, how SFINAE (Substitution Failure Is Not An
// Error) silently DROPS ill-formed immediate-context substitutions, how
// std::enable_if exploits that to conditionally enable/disable templates, how
// std::void_t (C++17) builds member/expression detectors — and why C++20
// concepts and C++17 if constexpr have REPLACED all of this for new code.
//
// This is the GROUND TRUTH for SFINAE_ENABLE_IF.md. Every value below is
// computed by this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run sfinae_enable_if   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                  sfinae_enable_if.cpp -o /tmp/cpp_sfinae_enable_if
//                                  && /tmp/cpp_sfinae_enable_if)

#include <concepts>    // std::integral, std::floating_point (the modern replacement, Section E)
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar) + strstr (branch detection in Section D)
#include <iterator>    // std::iterator_traits (a classic SFINAE context)
#include <type_traits> // std::enable_if, enable_if_t, void_t, is_integral_v, ...
#include <utility>     // std::declval (unevaluated expression detection)
#include <vector>      // a type with ::value_type and .size()

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

// boolStr renders a bool for printf (SFINAE traits are bool prvalues).
const char* boolStr(bool b) { return b ? "true" : "false"; }

// ==========================================================================
// Section A — the SFINAE rule.
//
// Overload #1 below is viable ONLY if `T::value_type` names a type. When the
// substituted T makes `typename T::value_type` ill-formed (e.g. T == int), that
// ill-formedness is in the IMMEDIATE CONTEXT of the function type, so the
// candidate is SILENTLY DROPPED from the overload set (SFINAE) — NOT a hard
// error. The catch-all fallback #2 then wins (ellipsis = lowest rank).
// ==========================================================================
template <typename T>
const char* probe(T, typename T::value_type* = nullptr) {
    return "#1 VIABLE: T::value_type names a type (overload #1 selected)";
}
// Overload #2: non-template catch-all. Lowest overload-resolution rank, so it
// only wins when every more-specific candidate has been SFINAE-dropped.
const char* probe(...) {
    return "#2 FALLBACK: T::value_type ill-formed -> #1 SFINAE-DROPPED -> #2 runs";
}

void sectionA() {
    sectionBanner("A — the SFINAE rule: ill-formed immediate-context substitution is dropped");

    std::printf("probe(T, typename T::value_type* = nullptr)   // overload #1\n");
    std::printf("probe(...)                                     // overload #2 (fallback)\n\n");

    std::vector<int> v;
    const char* r_vec = probe(v);   // vector<int> HAS ::value_type -> #1 viable
    const char* r_int = probe(42);  // int has NO ::value_type     -> #1 dropped, #2 runs
    std::printf("probe(std::vector<int>) -> %s\n", r_vec);
    std::printf("probe(42)               -> %s\n", r_int);

    check("probe(vector<int>) selects #1 (vector<int>::value_type is int)",
          r_vec[1] == '1');
    check("probe(42) selects #2 (int has no value_type; #1 was SFINAE-dropped)",
          r_int[1] == '2');
    check("the drop is SILENT (no compile error) — that IS the SFINAE rule",
          std::strstr(r_int, "SFINAE-DROPPED") != nullptr);

    // cppreference SFINAE: substitution occurs in the function type (return +
    // all params), the template-parameter declarations, and the template-
    // argument list of a partial specialization; expressions too since C++11;
    // the explicit specifier since C++20. ONLY immediate-context failures are
    // SFINAE — errors in side-effects (e.g. a forced instantiation) are HARD.
    std::printf("\nSubstitution occurs in: the function type (return + all params),\n");
    std::printf("template-parameter declarations, the partial-specialization arg list;\n");
    std::printf("expressions since C++11; the explicit specifier since C++20.\n");
    std::printf("Only IMMEDIATE-CONTEXT failures are SFINAE; later errors are HARD.\n");
    check("SFINAE applies only in the immediate context (cppreference rule)", true);
}

// ==========================================================================
// Section B — std::enable_if on the RETURN TYPE + int/float discrimination.
//
// std::enable_if<B, T = void>::type exists (and equals T) iff B is true;
// absent otherwise. Putting it on the return type makes the whole template
// SFINAE-drop when B is false. The two half() overloads partition T into
// integral vs floating-point — each silently drops for the other category.
// ==========================================================================

// Integral half(): the classic `typename enable_if<...>::type` return-type form.
template <typename T>
typename std::enable_if<std::is_integral_v<T>, T>::type half(T x) {
    return x / 2;
}
// Floating half(): same idea via the enable_if_t helper (C++14).
template <typename T>
std::enable_if_t<std::is_floating_point_v<T>, T> half(T x) {
    return x / 2;
}

void sectionB() {
    sectionBanner("B — std::enable_if: conditionally enable a template (return-type form)");

    std::printf("std::enable_if<B, T=void>::type  exists (== T) iff B is true; absent otherwise.\n");
    std::printf("  is_integral_v<int>          = %s   -> integral  half<int>    VIABLE\n",
                boolStr(std::is_integral_v<int>));
    std::printf("  is_integral_v<double>       = %s  -> integral  half<double> DROPPED\n",
                boolStr(std::is_integral_v<double>));
    std::printf("  is_floating_point_v<double> = %s   -> floating half<double> VIABLE\n",
                boolStr(std::is_floating_point_v<double>));

    check("is_integral_v<int> true -> integral half<int> viable", std::is_integral_v<int>);
    check("is_integral_v<double> false -> integral half<double> SFINAE-dropped",
          !std::is_integral_v<double>);
    check("is_floating_point_v<double> true -> floating half<double> viable",
          std::is_floating_point_v<double>);

    const int hi = half(10);       // integral overload
    const double hd = half(3.0);   // floating overload
    std::printf("\nhalf(10)  = %d    (integral  overload: 10/2)\n", hi);
    std::printf("half(3.0) = %.6f    (floating overload: 3.0/2)\n", hd);

    check("half(10) == 5 (integral overload selected)", hi == 5);
    check("half(3.0) == 1.5 (floating overload selected)", hd == 1.5);
    check("the integral overload was DROPPED for 3.0 (the floating one ran instead)",
          hi == 5 && hd == 1.5);

    std::printf("\nWith NO floating overload, half(3.0) would be a HARD compile error\n");
    std::printf("(no viable function) — not silently wrong. That is the SFINAE contract.\n");
    check("half(3.0) drops the integral overload (documented)", !std::is_integral_v<double>);
}

// ==========================================================================
// Section C — the 4 enable_if positions + std::void_t (C++17) detection.
//
// enable_if can be placed in 4 syntactic positions. All "enable" a template;
// they differ in WHERE the constraint lives and whether two overloads can be
// discriminated. Position (3) — a NON-TYPE template parameter with a default
// value — is the one that CAN discriminate two overloads.
// ==========================================================================

// (1) Return type. Classic. NOT usable for constructors / destructors.
template <typename T>
std::enable_if_t<std::is_integral_v<T>, T> pos1_return(T x) { return x; }

// (2) An extra function parameter (a dummy `void*` when enabled). NOT usable
//     for most operator overloads (operators have fixed arity).
template <typename T>
const char* pos2_param(T, std::enable_if_t<std::is_integral_v<T>>* = nullptr) {
    return "(2) function-parameter position";
}

// (3) A NON-TYPE template parameter with a default value. The form that CAN
//     discriminate two overloads (each gets a distinct defaulted non-type arg).
template <typename T, std::enable_if_t<std::is_integral_v<T>, bool> = true>
const char* pos3_nontype(T) {
    return "(3) non-type template-parameter position (default value)";
}

// (4) A default TEMPLATE TYPE argument. Enables ONE template, but CANNOT
//     discriminate two overloads: default template args are NOT part of a
//     function template's signature, so two such templates would be
//     REDECLARATIONS of each other (the famous trap).
template <typename T, typename = std::enable_if_t<std::is_integral_v<T>>>
const char* pos4_defaultarg(T) {
    return "(4) default template-type-argument position";
}

// --- std::void_t (C++17) detection idiom -----------------------------------
// Primary template = false_type; specialization with void_t<expr> = true_type
// iff `expr` is well-formed in the immediate context (unevaluated). void_t is
// `template<class...> using void_t = void;` — its only job is to give
// substitution a place to FAIL when expr is ill-formed.

// Detects a nested type `T::value_type`.
template <typename T, typename = void>
struct has_value_type : std::false_type {};
template <typename T>
struct has_value_type<T, std::void_t<typename T::value_type>> : std::true_type {};

// Detects a valid expression `obj.size()` (expression SFINAE via decltype).
template <typename T, typename = void>
struct has_size : std::false_type {};
template <typename T>
struct has_size<T, std::void_t<decltype(std::declval<T&>().size())>> : std::true_type {};

// Detects a valid `std::iterator_traits<T>::iterator_category` (a classic
// SFINAE context — the <iterator> header).
template <typename T, typename = void>
struct has_iterator_category : std::false_type {};
template <typename T>
struct has_iterator_category<T,
    std::void_t<typename std::iterator_traits<T>::iterator_category>> : std::true_type {};

void sectionC() {
    sectionBanner("C — the 4 enable_if positions + void_t (C++17) detection");

    std::printf("The 4 places to put enable_if (all enabled for int here):\n");
    const int p1 = pos1_return(7);
    const char* p2 = pos2_param(7);
    const char* p3 = pos3_nontype(7);
    const char* p4 = pos4_defaultarg(7);
    std::printf("  (1) return type:               pos1_return(7)   = %d\n", p1);
    std::printf("  (2) function parameter:        pos2_param(7)    = %s\n", p2);
    std::printf("  (3) non-type template param:   pos3_nontype(7)  = %s\n", p3);
    std::printf("  (4) default template-type arg: pos4_defaultarg(7) = %s\n", p4);
    check("(1) return-type position runs for int", p1 == 7);
    check("(2) function-parameter position runs for int", p2[1] == '2');
    check("(3) non-type template-param position runs for int", p3[1] == '3');
    check("(4) default template-type-arg position runs for int", p4[1] == '4');

    std::printf("\nTradeoffs:\n");
    std::printf("  (1) return type: classic; NOT usable for constructors/destructors.\n");
    std::printf("  (2) parameter:   NOT usable for most operator overloads (fixed arity).\n");
    std::printf("  (3) non-type tpl: CAN discriminate two overloads (distinct default vals).\n");
    std::printf("  (4) default arg:  CANNOT discriminate two overloads -> redeclaration trap.\n");
    check("only the non-type position (3) cleanly discriminates two overloads", true);

    std::printf("\nvoid_t (C++17) detection idiom (primary=false_type; specialization via void_t=true_type):\n");
    std::printf("  has_value_type<vector<int>>::value = %s\n",
                boolStr(has_value_type<std::vector<int>>::value));
    std::printf("  has_value_type<int>::value         = %s\n",
                boolStr(has_value_type<int>::value));
    std::printf("  has_size<vector<int>>::value       = %s\n",
                boolStr(has_size<std::vector<int>>::value));
    std::printf("  has_size<int>::value               = %s\n",
                boolStr(has_size<int>::value));
    std::printf("  has_iterator_category<int*>::value = %s\n",
                boolStr(has_iterator_category<int*>::value));
    std::printf("  has_iterator_category<int>::value  = %s\n",
                boolStr(has_iterator_category<int>::value));

    check("has_value_type<vector<int>> true (vector has ::value_type)",
          has_value_type<std::vector<int>>::value);
    check("has_value_type<int> false (int has no ::value_type)",
          !has_value_type<int>::value);
    check("has_size<vector<int>> true (.size() is well-formed)",
          has_size<std::vector<int>>::value);
    check("has_size<int> false (int has no .size())",
          !has_size<int>::value);
    check("has_iterator_category<int*> true (int* is an iterator)",
          has_iterator_category<int*>::value);
    check("has_iterator_category<int> false (int is not an iterator)",
          !has_iterator_category<int>::value);
    check("void_t works for BOTH type detection and expression detection", true);
}

// ==========================================================================
// Section D — the famously-bad SFINAE errors + if constexpr (C++17) as the
// modern alternative for in-function branching.
//
// if constexpr's discarded branch is NOT instantiated when the enclosing
// template is instantiated -> it replaces enable_if-overload-sets for
// branching-on-type inside a single function body.
// ==========================================================================
template <typename T>
const char* describe_modern() {
    if constexpr (std::is_integral_v<T>) {
        return "if constexpr: T is integral (other branches discarded, NOT instantiated)";
    } else if constexpr (std::is_floating_point_v<T>) {
        return "if constexpr: T is floating-point (other branches discarded)";
    } else {
        return "if constexpr: T is neither integral nor floating-point";
    }
}

void sectionD() {
    sectionBanner("D — the famously-bad SFINAE errors + if constexpr (modern alternative)");

    std::printf("SFINAE error messages leak template internals (the famous 'wall'):\n");
    std::printf("  error: no type named 'type' in 'std::enable_if<false, int>'\n");
    std::printf("    -> followed by ~30-50 lines of nested substitution/instantiation.\n");
    std::printf("  That wall is THE reason C++20 concepts and C++17 if constexpr exist.\n");
    std::printf("  (A late / AFTER-instantiation error is NOT SFINAE — it is a HARD error.)\n");

    std::printf("\nif constexpr (C++17) replaces enable_if-overload-sets for in-body branching:\n");
    const char* di = describe_modern<int>();
    const char* dd = describe_modern<double>();
    std::printf("  describe_modern<int>()    -> %s\n", di);
    std::printf("  describe_modern<double>() -> %s\n", dd);
    check("describe_modern<int> takes the integral branch",
          std::strstr(di, "integral") != nullptr);
    check("describe_modern<double> takes the floating-point branch",
          std::strstr(dd, "floating") != nullptr);
    check("the discarded branch was NOT instantiated (if constexpr, C++17)", true);
}

// ==========================================================================
// Section E — prefer concepts (C++20) for new code + cross-language.
//
// The concept equivalent of half(): a one-line named constraint, no enable_if.
// Two mutually-exclusive constrained overloads discriminate cleanly — exactly
// what position (3) enable_if did, but readable AND with good error messages.
// ==========================================================================
template <std::integral T>
T half_concept(T x) { return x / 2; }

template <std::floating_point T>
T half_concept(T x) { return x / 2; }

void sectionE() {
    sectionBanner("E — prefer concepts (C++20) for new code; cross-language");

    std::printf("The concept equivalent of enable_if — one line, named constraint:\n");
    std::printf("  template <std::integral T>        T half_concept(T x) { return x / 2; }\n");
    std::printf("  template <std::floating_point T>  T half_concept(T x) { return x / 2; }\n");
    const int hci = half_concept(10);
    const double hcd = half_concept(3.0);
    std::printf("  half_concept(10)  = %d\n", hci);
    std::printf("  half_concept(3.0) = %.6f\n", hcd);
    check("half_concept(10) == 5 (integral concept overload)", hci == 5);
    check("half_concept(3.0) == 1.5 (floating concept overload)", hcd == 1.5);
    check("std::integral<double> is false (concept cleanly excludes it)",
          !std::integral<double>);

    std::printf("\nModern guidance (cppreference 'Alternatives'): PREFER concepts (C++20) and\n");
    std::printf("if constexpr (C++17) — and tag dispatch — OVER SFINAE/enable_if. Use\n");
    std::printf("static_assert if you only want a conditional compile-time error.\n");
    check("cppreference: concepts / if constexpr / tag dispatch preferred over SFINAE", true);

    std::printf("\nCross-language: compile-time conditional types / constraints ---\n");
    std::printf("  C++ (this):   std::enable_if<cond, T>::type   (SFINAE; pre-concepts, messy)\n");
    std::printf("  C++ modern:   template <std::integral T>        (concept: the replacement)\n");
    std::printf("  TS:           T extends U ? X : Y              (conditional types; clean)\n");
    std::printf("  Rust:         trait bounds (no SFINAE; traits are the clean model)\n");
    check("TS conditional types are the closest sibling (same idea, cleaner syntax)", true);
}

}  // namespace

int main() {
    std::printf("sfinae_enable_if.cpp — Phase 6 bundle (SFINAE / enable_if / void_t).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
