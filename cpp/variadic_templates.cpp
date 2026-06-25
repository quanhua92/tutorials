// variadic_templates.cpp — Phase 2 bundle.
//
// GOAL (one line): show, by printing every value, how a VARIADIC TEMPLATE accepts
// any number of arguments via a PARAMETER PACK (`template <typename... Ts>` /
// `Ts... args`), how the pre-C++17 RECURSIVE idiom (head + tail, base case)
// consumed it, and how C++17 FOLD EXPRESSIONS collapse a pack with a binary
// operator in one line — the mechanism behind std::make_unique / std::tuple /
// std::function / perfect forwarding.
//
// This is the GROUND TRUTH for VARIADIC_TEMPLATES.md. Every value below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     just run variadic_templates   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                      -Wpedantic variadic_templates.cpp
//                                      -o /tmp/cpp_variadic_templates
//                                      && /tmp/cpp_variadic_templates)

#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <sstream>     // ostringstream (heterogeneous -> string)
#include <string>      // string
#include <tuple>       // tuple, tuple_size, get
#include <utility>     // std::forward (perfect-forwarding preview)
#include <vector>      // vector (collect-on-each)

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

// Generic value->string: works for int, double, const char*, std::string, ...
// (used by the recursive printer in B and the comma-fold collector in D).
template <typename T>
std::string to_str(const T& v) {
    std::ostringstream os;
    os << v;
    return os.str();
}

// === Section A — Parameter packs: accepts 0+ args; sizeof...(pack) ===========
//
// A template with >=1 parameter pack is a VARIADIC TEMPLATE. Here `Ts...` is a
// TYPE parameter pack and `args...` is a FUNCTION parameter pack. ONE signature
// accepts zero or more args of ANY types. sizeof...(pack) is the count — a
// constant expression of type std::size_t (usable as an array bound, a template
// argument, ...).
template <typename... Ts>
constexpr std::size_t arity(const Ts&... args) {
    // The pack values are unused here — we query only the COUNT. (Compilers do
    // not emit -Wunused-parameter for a parameter pack, so this stays warning-clean.)
    return sizeof...(args);
}

// A NON-TYPE template parameter pack: `template <auto... Ns>`. Each element's
// TYPE is deduced independently (so the pack may hold heterogeneous values:
// int, unsigned long, char, ...). sizeof... still counts them.
template <auto... Ns>
constexpr std::size_t nttp_count() {
    return sizeof...(Ns);
}

// === Section B — The RECURSIVE idiom (pre-C++17) ============================
//
// Before fold expressions (C++17), the ONLY way to consume a pack was recursive
// pattern-matching: a BASE CASE (zero args) + a RECURSIVE CASE that peels off
// the HEAD (one typed arg) and recurses on the TAIL (the rest of the pack).
// Still useful when each element needs per-type logic a fold can't express.

// Base case: empty pack -> empty string. Terminates the recursion.
std::string join_rec() { return ""; }

// Recursive case: head + (", " if more follow) + join the tail.
//   T         head : one concrete type (the peeled-off HEAD)
//   Ts...     rest : the remaining pack (the TAIL)
template <typename T, typename... Ts>
std::string join_rec(const T& head, const Ts&... rest) {
    return to_str(head) + (sizeof...(rest) ? ", " : "") + join_rec(rest...);
}

// === Section C — FOLD EXPRESSIONS (C++17) ===================================
//
// A fold collapses a pack with a BINARY operator in one expression — no manual
// recursion. Four forms exist (see section E); here we use the everyday ones.
//
//   (args + ...)    unary RIGHT fold: E1 + (E2 + (E3 + ...))   sum/combine
//   (... + args)    unary LEFT  fold: ((E1 + E2) + E3) + ...
//   (args && ...)   unary right fold over && : all-true
//   (args || ...)   unary right fold over || : any-true
// An EMPTY pack is allowed ONLY for && (-> true), || (-> false), and , (-> void()).
// For any other operator an empty unary fold is ill-formed; use a BINARY fold
// with an init value: (args + ... + 0) -> 0 when the pack is empty.

template <typename... Ts>
int sum_right(const Ts&... args) { return (args + ...); }        // unary right
template <typename... Ts>
int sum_left(const Ts&... args)  { return (... + args); }        // unary left
template <typename... Ts>
int sum_empty_safe(const Ts&... args) { return (args + ... + 0); } // binary right, init 0

template <typename... Ts>
bool all_true(const Ts&... args) { return (args && ...); }       // unary right, &&
template <typename... Ts>
bool any_true(const Ts&... args) { return (args || ...); }       // unary right, ||

// === Section D — Pack EXPANSION in other contexts ===========================

// (1) Pack expansion into a TYPE: std::tuple<Ts...> is THE variadic class
// template (🔗 CLASS_TEMPLATES). By-value params make string literals decay to
// `const char*` (the std::make_tuple semantics), so Ts deduces to the element
// types we actually want stored.
template <typename... Ts>
std::tuple<Ts...> make_tup(Ts... args) {
    return std::tuple<Ts...>{args...};
}

// (2) Comma-fold: call a function on EACH element, left-to-right. This is the
// C++17 one-liner that replaces the recursive printer of section B.
//   (fn(args), ...)  ==  fn(E1), fn(E2), fn(E3)  (comma sequences L-to-R).
template <typename... Ts>
std::vector<std::string> collect_each(const Ts&... args) {
    std::vector<std::string> out;
    auto fn = [&out](const auto& v) { out.push_back(to_str(v)); };
    (fn(args), ...);   // unary right fold over the comma operator
    return out;
}

// === Section E — Perfect-forwarding PREVIEW + the 4 fold forms ===============

// The make_unique / emplace_back idiom: Ts&&... is a pack of FORWARDING
// references; std::forward<Ts>(args)... re-expands the pack, PERFECTLY
// preserving each argument's value category (lvalue vs rvalue). Full treatment
// lands in MOVE_SEMANTICS (P3); here we only verify values pass through.
static std::string g_sink_s;
static int         g_sink_n;

void forward_target(const std::string& s, int n) {
    g_sink_s = s;
    g_sink_n = n;
}

template <typename... Ts>
void forward_to_target(Ts&&... args) {
    forward_target(std::forward<Ts>(args)...);   // pack expansion inside the call
}

// The four fold forms, shown over '-' so DIRECTION visibly changes the answer.
//   (E op ...)         unary RIGHT : E1-(E2-(...-EN))
//   (... op E)         unary LEFT  : ((E1-E2)-...)-EN
//   (E op ... op I)    binary RIGHT: E1-(...-(EN-I))
//   (I op ... op E)    binary LEFT : ((I-E1)-...)-EN
template <typename... Ts>
int fold_unary_right(const Ts&... args)  { return (args - ...); }        // form 1
template <typename... Ts>
int fold_unary_left(const Ts&... args)   { return (... - args); }        // form 2
template <typename... Ts>
int fold_binary_right(const Ts&... args) { return (args - ... - 100); }  // form 3, init 100
template <typename... Ts>
int fold_binary_left(const Ts&... args)  { return (100 - ... - args); }  // form 4, init 100

// ==========================================================================

void sectionA() {
    sectionBanner("A — Parameter packs: accepts 0+ args; sizeof...(pack)");

    std::printf("template <typename... Ts> arity(const Ts&... args) { return sizeof...(args); }\n");
    std::printf("arity()              = %zu   <- EMPTY pack (zero args accepted)\n", arity());
    std::printf("arity(1)             = %zu\n", arity(1));
    std::printf("arity(1, 2.0, \"x\")   = %zu   <- heterogeneous types, ONE signature\n",
                arity(1, 2.0, "x"));

    check("empty pack:  arity() == 0", arity() == 0);
    check("one arg:     arity(1) == 1", arity(1) == 1);
    check("three args:  arity(1, 2.0, \"x\") == 3", arity(1, 2.0, "x") == 3);

    // sizeof...(pack) is a CONSTANT EXPRESSION -> usable as an array bound.
    constexpr std::size_t n = arity(1, 2, 3);
    int arr[n] = {0};   // a runtime value could NOT be used here
    (void)arr;
    std::printf("\nsizeof...(pack) is a constant expression: constexpr n = arity(1,2,3) = %zu\n", n);
    std::printf("  -> int arr[n]; compiles (a runtime value could not be an array bound)\n");
    check("sizeof...(args) usable as array bound (n == 3)", n == 3);

    // NON-TYPE template parameter pack: `template <auto... Ns>`. Each element's
    // type is deduced independently, so the pack may hold mixed value types.
    constexpr std::size_t m = nttp_count<1, 2UL, 'a'>();
    std::printf("\nNon-type pack  template <auto... Ns>  sizeof...(Ns)\n");
    std::printf("nttp_count<1, 2UL, 'a'>() = %zu   (int, unsigned long, char in ONE pack)\n", m);
    check("non-type pack nttp_count<1,2UL,'a'>() == 3", m == 3);
}

// ---------------------------------------------------------------------------

void sectionB() {
    sectionBanner("B — RECURSIVE idiom (pre-C++17): base case + head/tail");

    std::printf("void join_rec() { return \"\"; }                          // base case\n");
    std::printf("template <typename T, typename... Ts>                    // recursive case\n");
    std::printf("std::string join_rec(const T& head, const Ts&... rest);\n");

    const std::string r0 = join_rec();
    const std::string r1 = join_rec(42);
    const std::string r3 = join_rec(1, 2.5, "hello");
    std::printf("\njoin_rec()               = \"%s\"    (empty pack -> base case)\n", r0.c_str());
    std::printf("join_rec(42)             = \"%s\"\n", r1.c_str());
    std::printf("join_rec(1, 2.5, \"hello\") = \"%s\"   (head + \", \" + tail, recursed)\n",
                r3.c_str());

    check("recursive base case: join_rec() == \"\"", r0 == "");
    check("recursive single:    join_rec(42) == \"42\"", r1 == "42");
    check("recursive walk:      join_rec(1,2.5,\"hello\") == \"1, 2.5, hello\"", r3 == "1, 2.5, hello");
}

// ---------------------------------------------------------------------------

void sectionC() {
    sectionBanner("C — FOLD EXPRESSIONS (C++17): collapse a pack in one line");

    std::printf("(args + ...)  unary RIGHT fold  : E1 + (E2 + (E3 + ...))\n");
    std::printf("(... + args)  unary LEFT  fold  : ((E1 + E2) + E3) + ...\n");
    std::printf("\nsum_right(1,2,3,4) = (args + ...) = %d\n", sum_right(1, 2, 3, 4));
    std::printf("sum_left (1,2,3,4) = (... + args) = %d   (+ is associative: same result)\n",
                sum_left(1, 2, 3, 4));

    check("unary right fold: (1+2+3+4 via (args+...)) == 10", sum_right(1, 2, 3, 4) == 10);
    check("unary left  fold: (1+2+3+4 via (...+args)) == 10", sum_left(1, 2, 3, 4) == 10);

    // --- all-true / any-true over && and ||
    std::printf("\n(args && ...)  unary right fold over && : all-true\n");
    std::printf("(args || ...)  unary right fold over || : any-true\n");
    std::printf("all_true(true,true,false) = %s\n", all_true(true, true, false) ? "true" : "false");
    std::printf("all_true(true,true)       = %s\n", all_true(true, true) ? "true" : "false");
    std::printf("any_true(false,false,true)= %s\n", any_true(false, false, true) ? "true" : "false");
    std::printf("any_true(false,false)     = %s\n", any_true(false, false) ? "true" : "false");

    check("all_true(true,true,false) == false", all_true(true, true, false) == false);
    check("all_true(true,true) == true", all_true(true, true) == true);
    check("any_true(false,false,true) == true", any_true(false, false, true) == true);
    check("any_true(false,false) == false", any_true(false, false) == false);

    // --- EMPTY pack: only && (true), || (false), and , (void()) are allowed.
    std::printf("\nEMPTY-pack unary folds (the ONLY 3 legal operators):\n");
    std::printf("  all_true()        = (args && ...) with 0 args = %s   (identity for &&)\n",
                all_true() ? "true" : "false");
    std::printf("  any_true()        = (args || ...) with 0 args = %s  (identity for ||)\n",
                any_true() ? "true" : "false");
    check("empty pack: (args && ...) == true", all_true() == true);
    check("empty pack: (args || ...) == false", any_true() == false);

    // --- BINARY fold with an init value: makes '+' (and others) empty-safe.
    std::printf("\nBINARY fold with init: (args + ... + 0)  -> init when pack is empty\n");
    std::printf("  sum_empty_safe(1,2,3) = (args + ... + 0) = %d\n", sum_empty_safe(1, 2, 3));
    std::printf("  sum_empty_safe()      = (args + ... + 0) = %d   (empty -> the init 0)\n",
                sum_empty_safe());
    check("binary fold non-empty: sum_empty_safe(1,2,3) == 6", sum_empty_safe(1, 2, 3) == 6);
    check("binary fold empty:     sum_empty_safe() == 0  (init value)", sum_empty_safe() == 0);
}

// ---------------------------------------------------------------------------

void sectionD() {
    sectionBanner("D — Pack EXPANSION in other contexts: tuple, comma-fold, fwd");

    // (1) Pack expansion into a TYPE: std::tuple<Ts...>.
    std::tuple<int, double, const char*> t = make_tup(1, 2.5, "hi");
    std::printf("(1) std::tuple<Ts...> from a pack (args... expands in the ctor call):\n");
    std::printf("    std::tuple<int,double,const char*> t = make_tup(1, 2.5, \"hi\");\n");
    std::printf("    std::get<0>(t) = %d\n", std::get<0>(t));
    std::printf("    std::get<1>(t) = %.1f\n", std::get<1>(t));
    std::printf("    std::get<2>(t) = %s\n", std::get<2>(t));
    std::printf("    std::tuple_size = %zu  (== sizeof...(Ts))\n",
                std::tuple_size<std::tuple<int, double, const char*>>::value);

    check("tuple pack expansion: get<0> == 1", std::get<0>(t) == 1);
    check("tuple pack expansion: get<1> == 2.5", std::get<1>(t) == 2.5);
    check("tuple pack expansion: tuple_size == sizeof...(pack) == 3",
          std::tuple_size<std::tuple<int, double, const char*>>::value == 3);

    // (2) Comma-fold: call f on EACH element, left-to-right (replaces recursion).
    std::printf("\n(2) Comma-fold  (fn(args), ...) : call fn on each, left-to-right\n");
    std::vector<std::string> c3 = collect_each(10, 2.5, "z");
    std::vector<std::string> c0 = collect_each();
    std::printf("    collect_each(10, 2.5, \"z\") = [");
    for (std::size_t i = 0; i < c3.size(); ++i) {
        std::printf("%s%s", c3[i].c_str(), (i + 1 == c3.size() ? "" : ", "));
    }
    std::printf("]\n");
    std::printf("    collect_each()             = %zu elements  (empty pack -> void())\n", c0.size());

    check("comma-fold collect_each(10,2.5,\"z\") has 3 elements", c3.size() == 3);
    check("comma-fold order preserved: [0]==\"10\"", c3[0] == "10");
    check("comma-fold order preserved: [2]==\"z\"", c3[2] == "z");
    check("comma-fold empty pack -> 0 elements", c0.empty());

    // (3) Perfect-forwarding PREVIEW: Ts&&... + std::forward<Ts>(args)... .
    std::printf("\n(3) Perfect forwarding PREVIEW (full treatment: MOVE_SEMANTICS, P3):\n");
    std::printf("    template <typename... Ts> void f(Ts&&... args) { g(forward<Ts>(args)...); }\n");
    forward_to_target(std::string("yo"), 42);
    std::printf("    forward_to_target(string(\"yo\"), 42) -> sink = (\"%s\", %d)\n",
                g_sink_s.c_str(), g_sink_n);
    check("perfect forwarding: string passed through", g_sink_s == "yo");
    check("perfect forwarding: int passed through", g_sink_n == 42);
}

// ---------------------------------------------------------------------------

void sectionE() {
    sectionBanner("E — The 4 fold forms (direction + init matter)");

    // Subtraction is NOT associative, so the four forms give four DIFFERENT
    // answers for the same pack {10, 3, 1}. This is the clearest way to SEE the
    // difference between left/right and unary/binary folds.
    std::printf("Pack = {10, 3, 1}, operator = '-'  (NOT associative -> forms diverge):\n\n");
    std::printf("  form  syntax              expansion              result\n");
    std::printf("  ----  -----------------   ---------------------  ------\n");

    const int r1 = fold_unary_right(10, 3, 1);
    const int r2 = fold_unary_left(10, 3, 1);
    const int r3 = fold_binary_right(10, 3, 1);
    const int r4 = fold_binary_left(10, 3, 1);

    std::printf("  (1)   (args - ...)        E1-(E2-(...-EN))       %d   (10-(3-1))\n", r1);
    std::printf("  (2)   (... - args)        ((E1-E2)-...)-EN       %d   ((10-3)-1)\n", r2);
    std::printf("  (3)   (args - ... - 100)  E1-(...-(EN-100))      %d   (10-(3-(1-100)))\n", r3);
    std::printf("  (4)   (100 - ... - args)  ((100-E1)-...)-EN      %d   (((100-10)-3)-1)\n", r4);

    check("form 1 unary right:  (args - ...) == 8", r1 == 8);
    check("form 2 unary left:   (... - args) == 6", r2 == 6);
    check("form 3 binary right: (args - ... - 100) == -92", r3 == -92);
    check("form 4 binary left:  (100 - ... - args) == 86", r4 == 86);

    // The 32 legal fold operators (cppreference): any binary operator.
    std::printf("\n32 binary operators may fold: + - * / %% ^ & | << >> == != <= >= && || ,\n");
    std::printf("  (and += -= *= ... ->* etc.). In a BINARY fold, both ops must match.\n");
    check("this file exercises fold over +, &&, ||, and ,  (all legal fold operators)",
          sum_right(1, 1) == 2 && all_true(true, true) && !any_true(false, false));
}

}  // namespace

int main() {
    std::printf("variadic_templates.cpp — Phase 2 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
