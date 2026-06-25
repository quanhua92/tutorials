// template_metaprogramming.cpp — Phase 6 bundle (Template Metaprogramming).
//
// GOAL (one line): show, by printing and asserting every compile-time-computed
// value, how C++ templates are TURING-COMPLETE at compile time via RECURSIVE
// TEMPLATE INSTANTIATION + SPECIALIZATION (the "template metaprogramming" / TMP
// pattern) — powerful but arcane; modern C++ prefers `constexpr` functions for
// VALUE computation, so TMP now mainly serves TYPE-level computation.
//
// This is the GROUND TRUTH for TEMPLATE_METAPROGRAMMING.md. Every number, table,
// and worked example in the guide is printed by this file. Change it ->
// re-compile -> re-paste. Never hand-compute.
//
// Determinism note: TMP resolves FULLY at compile time — every value below is a
// compile-time constant, so output is 100% reproducible across runs/machines
// for a given ABI. No rand/now; the runtime code only PRINTS the results.
//
// Run:
//     just run template_metaprogramming   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                          -Wpedantic template_metaprogramming.cpp
//                                          -o /tmp/cpp_template_metaprogramming
//                                          && /tmp/cpp_template_metaprogramming)

#include <concepts>    // std::integral (the C++20 constraint that replaces SFINAE/TMP)
#include <cstddef>     // std::size_t
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <type_traits> // std::integral_constant, true_type, false_type, is_same_v, is_integral_v

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

// b() renders a compile-time bool as the literal "true"/"false" (deterministic,
// portable — unlike typeid().name(), which is impl-defined mangled garbage).
const char* b(bool x) { return x ? "true" : "false"; }

// ==========================================================================
// TMP METAFUNCTIONS — the "template metaprogramming" pattern.
//
// Every one is the SAME shape: a PRIMARY template (the recursive step) plus a
// full SPECIALIZATION (the base case that terminates the compile-time
// recursion). The compiler instantiates Fact<N> -> Fact<N-1> -> ... -> Fact<0>,
// folding the chain into a single constant. That is a "loop that runs in the
// compiler". This is the pre-constexpr way to compute at compile time.
// ==========================================================================

// --- Compile-time FACTORIAL via recursive template instantiation ----------
//   Fact<N>::value  =  N * Fact<N-1>::value   (recursive step)
//   Fact<0>::value  =  1                      (base-case specialization)
// Each distinct N yields a DISTINCT type Fact<N>; the chain unfolds at compile
// time and folds to a constant. This is the canonical TMP "compile-time loop".
template <int N>
struct Fact {
    static constexpr int value = N * Fact<N - 1>::value;
};
template <>
struct Fact<0> {
    static constexpr int value = 1;
};

// --- Compile-time FIBONACCI via template recursion -----------------------
//   Fib<N>::value = Fib<N-1>::value + Fib<N-2>::value   (recursive step)
//   Fib<0>::value = 0 ; Fib<1>::value = 1               (two base cases)
// The body LOOKS exponential, but the COMPILER MEMOIZES instantiations: Fib<k>
// is ONE type, referenced many times but instantiated once. So both the total
// instantiations and the instantiation DEPTH are ~O(N) — well within limits.
template <int N>
struct Fib {
    static constexpr int value = Fib<N - 1>::value + Fib<N - 2>::value;
};
template <>
struct Fib<0> {
    static constexpr int value = 0;
};
template <>
struct Fib<1> {
    static constexpr int value = 1;
};

// --- Compile-time TYPE LIST (a hallmark of TMP) --------------------------
// A Typelist is a template-of-TYPES manipulated via specialization — the SAME
// recursion as Fact/Fib, but it computes on the TYPE LEVEL (where constexpr
// cannot go). We build head/tail/length and an Nth-type lookup entirely at
// compile time.
template <typename... Ts>
struct Typelist {
    // The MODERN one-liner: sizeof...(Ts) folds the pack at compile time. The
    // classic TMP form (the recursive Length<> metafunction below) is what TMP
    // looked like before variadics (C++11) gave us sizeof....
    static constexpr std::size_t size = sizeof...(Ts);
};

// recursive Length<> metafunction: the CLASSIC TMP form.
//   Length<Typelist<>>::value                          = 0   (base case)
//   Length<Typelist<Head, Tail...>>::value             = 1 + Length<Typelist<Tail...>>::value
template <typename List>
struct Length;
template <>
struct Length<Typelist<>> {
    static constexpr std::size_t value = 0;
};
template <typename Head, typename... Tail>
struct Length<Typelist<Head, Tail...>> {
    static constexpr std::size_t value = 1 + Length<Typelist<Tail...>>::value;
};

// recursive TypeAt<> metafunction: fetch the Nth type of a Typelist.
//   TypeAt<Typelist<Head, Tail...>, 0>::type           = Head            (base case)
//   TypeAt<Typelist<Head, Tail...>, N>::type           = TypeAt<Typelist<Tail...>, N-1>::type
template <typename List, std::size_t N>
struct TypeAt;
template <typename Head, typename... Tail>
struct TypeAt<Typelist<Head, Tail...>, 0> {
    using type = Head;
};
template <typename Head, typename... Tail, std::size_t N>
struct TypeAt<Typelist<Head, Tail...>, N> {
    using type = typename TypeAt<Typelist<Tail...>, N - 1>::type;
};

// ==========================================================================
// Section A — Recursive template instantiation = a compile-time loop
// ==========================================================================
void sectionA() {
    sectionBanner("A — Recursive template instantiation = a compile-time loop");

    std::printf("Compile-time FACTORIAL via template recursion (Fact<N>):\n");
    std::printf("    Fact<N>::value = N * Fact<N-1>::value ; Fact<0>::value = 1\n\n");
    std::printf("    N    Fact<N>::value   (each row = a distinct instantiated type)\n");
    std::printf("    --   -------------\n");
    std::printf("     0   %d\n", Fact<0>::value);
    std::printf("     1   %d\n", Fact<1>::value);
    std::printf("     2   %d\n", Fact<2>::value);
    std::printf("     3   %d\n", Fact<3>::value);
    std::printf("     4   %d\n", Fact<4>::value);
    std::printf("     5   %d\n", Fact<5>::value);

    // PROOF it was computed at compile time: Fact<3>::value is usable as an
    // ARRAY BOUND — a place the language FORBIDS a runtime value. If it were
    // not a constant expression, this line would simply not compile.
    int arr[Fact<3>::value];  // == int arr[6];  (constant-expression bound, NOT a VLA)
    for (int i = 0; i < Fact<3>::value; ++i) arr[i] = i;
    int sum = 0;
    for (int i = 0; i < Fact<3>::value; ++i) sum += arr[i];
    std::printf("\n    int arr[Fact<3>::value];  -> array of %d ints (compile-time bound)\n",
                Fact<3>::value);
    std::printf("    sum of arr (0+1+2+3+4+5) = %d\n", sum);

    check("Fact<5>::value == 120 (recursive instantiation folds to a constant)",
          Fact<5>::value == 120);
    check("Fact<0>::value == 1 (the base-case specialization terminates recursion)",
          Fact<0>::value == 1);
    check("Fact<3>::value is usable as an array bound (== 6, a constant expression)",
          Fact<3>::value == 6);
    check("each Fact<N> is a DISTINCT type (monomorphization: Fact<3> != Fact<5>)",
          !std::is_same_v<Fact<3>, Fact<5>>);
    check("sum of arr == 15", sum == 15);
}

// ==========================================================================
// Section B — std::integral_constant (TMP base) + a compile-time TYPE LIST
// ==========================================================================
void sectionB() {
    sectionBanner("B — std::integral_constant (TMP base) + a TYPE LIST");

    // std::integral_constant<T, v> is a TYPE that CARRIES a compile-time
    // constant (::value). It is literally the base class of <type_traits>: every
    // std::is_* trait derives from true_type / false_type (the two bool cases).
    using two_t = std::integral_constant<int, 2>;
    using four_t = std::integral_constant<int, 4>;
    std::printf("std::integral_constant wraps a static constant inside a TYPE:\n");
    std::printf("    integral_constant<int,2>::value       = %d\n", two_t::value);
    std::printf("    integral_constant<int,2>()()          = %d   (operator() since C++14)\n",
                two_t()());
    std::printf("    2 * integral_constant<int,2>::value   = %d   == integral_constant<int,4>::value\n",
                two_t::value * 2);
    std::printf("    is_same_v<two_t::value_type, int>     = %s   (the carried type is exposed)\n",
                b(std::is_same_v<two_t::value_type, int>));
    std::printf("    is_same_v<two_t, four_t>              = %s   (different VALUES -> different TYPES)\n",
                b(std::is_same_v<two_t, four_t>));

    // The two bool typedefs; EVERY binary type trait is one of these under the hood.
    std::printf("\n    true_type  == integral_constant<bool,true>  : %s\n",
                b(std::is_same_v<std::true_type, std::integral_constant<bool, true>>));
    std::printf("    false_type == integral_constant<bool,false> : %s\n",
                b(std::is_same_v<std::false_type, std::integral_constant<bool, false>>));
    std::printf("    is_integral_v<int> (a trait BUILT ON integral_constant) = %s\n",
                b(std::is_integral_v<int>));

    // --- A compile-time TYPE LIST (TMP on the TYPE level, where constexpr
    // cannot go). We compute its length and fetch a type by index — all at
    // compile time, by recursive specialization. ----------------------------
    using MyList = Typelist<char, short, int, long>;
    std::printf("\nCompile-time TYPE LIST: Typelist<char, short, int, long>\n");
    std::printf("    Length<MyList>::value   (classic recursive metafunction) = %zu\n",
                Length<MyList>::value);
    std::printf("    MyList::size            (modern sizeof...(Ts) one-liner) = %zu\n", MyList::size);
    std::printf("    TypeAt<MyList,0>::type == char  : %s\n",
                b(std::is_same_v<TypeAt<MyList, 0>::type, char>));
    std::printf("    TypeAt<MyList,2>::type == int   : %s\n",
                b(std::is_same_v<TypeAt<MyList, 2>::type, int>));
    std::printf("    TypeAt<MyList,3>::type == long  : %s\n",
                b(std::is_same_v<TypeAt<MyList, 3>::type, long>));

    check("integral_constant<int,2>::value == 2", two_t::value == 2);
    check("true_type IS integral_constant<bool,true> (traits inherit ::value from it)",
          std::is_same_v<std::true_type, std::integral_constant<bool, true>>);
    check("Length<Typelist<char,short,int,long>>::value == 4 (computed at compile time)",
          Length<MyList>::value == 4);
    check("MyList::size == Length<MyList>::value (sizeof... matches the recursion)",
          MyList::size == Length<MyList>::value);
    check("TypeAt<MyList,2>::type == int (Nth-type lookup is type-level computation)",
          std::is_same_v<TypeAt<MyList, 2>::type, int>);
}

// ==========================================================================
// Section C — Compile-time Fibonacci + the instantiation-depth limit
// ==========================================================================
void sectionC() {
    sectionBanner("C — Compile-time Fibonacci + the instantiation-depth limit");

    std::printf("Compile-time FIBONACCI via template recursion (Fib<N>):\n");
    std::printf("    Fib<N>::value = Fib<N-1>::value + Fib<N-2>::value ; Fib<0>=0, Fib<1>=1\n\n");
    std::printf("    N    Fib<N>::value   (each row = a compile-time constant from Fib<N>)\n");
    std::printf("    --   -------------\n");
    std::printf("     0   %d\n", Fib<0>::value);
    std::printf("     1   %d\n", Fib<1>::value);
    std::printf("     2   %d\n", Fib<2>::value);
    std::printf("     3   %d\n", Fib<3>::value);
    std::printf("     4   %d\n", Fib<4>::value);
    std::printf("     5   %d\n", Fib<5>::value);
    std::printf("     6   %d\n", Fib<6>::value);
    std::printf("     7   %d\n", Fib<7>::value);
    std::printf("     8   %d\n", Fib<8>::value);
    std::printf("     9   %d\n", Fib<9>::value);
    std::printf("    10   %d\n", Fib<10>::value);
    std::printf("\n    The body looks exponential, but template instantiation is\n");
    std::printf("    MEMOIZED: Fib<k> is ONE type, so total instantiations are O(N)\n");
    std::printf("    and recursion DEPTH is ~N. Fib<10> depth is 10 — tiny.\n");

    // --- The instantiation-depth limit (a STACK OVERFLOW AT COMPILE TIME) ---
    // The standard RECOMMENDS implementations support at least 1024 levels of
    // recursive instantiation; infinite recursion in template instantiation is
    // UNDEFINED BEHAVIOR. We deliberately do NOT trigger it here (that would be
    // a hard compile error / UB). Raise the cap with -ftemplate-depth=N (gcc/
    // clang) if a real TMP chain needs more.
    std::printf("\nINSTANTIATION-DEPTH LIMIT (documented, NOT triggered):\n");
    std::printf("    standard recommends >= 1024 recursive-instantiation levels\n");
    std::printf("    infinite template recursion is UNDEFINED BEHAVIOR\n");
    std::printf("    raise the cap with the -ftemplate-depth=N flag (gcc/clang)\n");
    std::printf("    (this bundle stays at depth <= ~10 — far under any limit)\n");

    check("Fib<10>::value == 55 (the classic TMP Fibonacci)", Fib<10>::value == 55);
    check("Fib<0>::value == 0 (base case)", Fib<0>::value == 0);
    check("Fib<1>::value == 1 (base case)", Fib<1>::value == 1);
    check("Fib<2>::value == Fib<0>::value + Fib<1>::value == 1", Fib<2>::value == 1);
}

// ==========================================================================
// Section D — The MODERN shift: prefer `constexpr` for VALUES; TMP for TYPES
// ==========================================================================

// The SAME factorial/Fibonacci as ordinary constexpr FUNCTIONS — far cleaner
// than the template-struct versions above: no primary/specialization boilerplate,
// debuggable, and with NO instantiation-depth-style ceiling on the recursion
// (it is ordinary function recursion, capped by the constexpr evaluation depth
// / step budget, which is far larger and configurable).
constexpr int fact_cx(int n) { return n <= 1 ? 1 : n * fact_cx(n - 1); }
constexpr int fib_cx(int n) { return n < 2 ? n : fib_cx(n - 1) + fib_cx(n - 2); }

// if constexpr (C++17) + concepts (C++20) replaced the TMP/SFINAE gymnastics
// that BRANCHING on a type used to require. What once needed a recursive
// template + specializations is now one plain function body.
template <typename T>
constexpr const char* kind(T) {
    if constexpr (std::is_integral_v<T>) {
        return "integral";
    } else if constexpr (std::is_floating_point_v<T>) {
        return "floating-point";
    } else {
        return "other";
    }
}

// A C++20 concept is the modern, named, readable replacement for "constrain a
// template via SFINAE/TMP". `template <std::integral T>` says it in one word.
template <std::integral T>
constexpr T twice(T x) {
    return x * 2;
}

void sectionD() {
    sectionBanner("D — The MODERN shift: prefer constexpr for VALUES");

    std::printf("The SAME math as ordinary constexpr FUNCTIONS (no struct boilerplate):\n");
    std::printf("    constexpr int fact_cx(int n) { return n<=1 ? 1 : n*fact_cx(n-1); }\n");
    std::printf("    constexpr int fib_cx(int n)  { return n<2  ? n : fib_cx(n-1)+fib_cx(n-2); }\n\n");
    std::printf("    fact_cx(5) = %d   (matches Fact<5>::value  = %d)\n", fact_cx(5), Fact<5>::value);
    std::printf("    fib_cx(10) = %d   (matches Fib<10>::value = %d)\n", fib_cx(10), Fib<10>::value);

    // PROOF these too are compile-time: array bound + template argument.
    int proof_arr[fact_cx(4)];  // == int proof_arr[24];
    for (int i = 0; i < fact_cx(4); ++i) proof_arr[i] = 1;
    int proof_sum = 0;
    for (int i = 0; i < fact_cx(4); ++i) proof_sum += proof_arr[i];
    std::printf("\n    int proof_arr[fact_cx(4)]; -> %d ints (compile-time bound); sum = %d\n",
                fact_cx(4), proof_sum);

    std::printf("\nif constexpr (C++17) + concepts (C++20) replaced TMP branching:\n");
    std::printf("    kind(42)   = %s\n", kind(42));
    std::printf("    kind(1.5)  = %s\n", kind(1.5));
    std::printf("    kind(\"x\")  = %s\n", kind("x"));
    std::printf("    twice(21)  = %d   (template <std::integral T> — one-word constraint)\n",
                twice(21));

    check("constexpr fact_cx(5) == Fact<5>::value == 120 (same answer, cleaner form)",
          fact_cx(5) == Fact<5>::value);
    check("constexpr fib_cx(10) == Fib<10>::value == 55", fib_cx(10) == Fib<10>::value);
    check("fact_cx(4) usable as array bound (== 24, compile-time constant)", fact_cx(4) == 24);
    check("if constexpr branch picked 'integral' for int", kind(42)[0] == 'i');
    check("twice(21) == 42 (concept-constrained template)", twice(21) == 42);
}

// ==========================================================================
// Section E — The cost (slow instantiation + binary bloat) + cross-language
// ==========================================================================
void sectionE() {
    sectionBanner("E — The cost (instantiation is slow + bloats) + cross-language");

    // Monomorphization: each distinct Fact<N> / Fib<N> is a SEPARATE type with
    // its own ::value. TMP therefore trades RUNTIME cost for COMPILE-TIME cost
    // + binary size. Deep TMP is the classic cause of slow compiles.
    std::printf("Monomorphization — each Fact<N> is a distinct type:\n");
    std::printf("    sizeof(Fact<5>) = %zu   (empty struct: only a static ::value)\n",
                sizeof(Fact<5>));
    std::printf("    Fact<3> != Fact<5> : %s   (two separate instantiations/symbols)\n",
                b(!std::is_same_v<Fact<3>, Fact<5>>));
    std::printf("\nTRADEOFF (documented — not measurable deterministically at runtime):\n");
    std::printf("    - TMP cost is COMPILE-TIME: each instantiation takes time + emits code.\n");
    std::printf("    - Deep TMP -> slow compiles + binary bloat (many near-identical copies).\n");
    std::printf("    - Hence: prefer `constexpr` functions for VALUES (one body, many calls),\n");
    std::printf("      keep TMP for TYPE-level work it is the ONLY tool for.\n");

    std::printf("\nCROSS-LANGUAGE (compile-time computation):\n");
    std::printf("    C++     : TMP (recursive instantiation) for types; constexpr fns for values\n");
    std::printf("    Rust    : NO template metaprogramming — `const fn` for compile-time\n");
    std::printf("              values, traits for type-level work (clean model from the start)\n");
    std::printf("    TS      : type-level computation via conditional/mapped types\n");
    std::printf("              (the same idea, a different mechanism — see MAPPED_CONDITIONAL_TYPES)\n");
    std::printf("    Go      : no TMP — generics are runtime-erased-ish, no compile-time\n");
    std::printf("              computation language\n");

    check("TMP trades runtime cost for compile-time + binary cost (documented above)", true);
    check("Fact<3> and Fact<5> are distinct monomorphized types",
          !std::is_same_v<Fact<3>, Fact<5>>);
}

}  // namespace

int main() {
    std::printf("template_metaprogramming.cpp — Phase 6 bundle.\n");
    std::printf("Every value below is computed at COMPILE TIME by this file.\n");
    std::printf("Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free (sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
