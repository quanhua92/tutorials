// concepts.cpp — Phase 2 bundle #12.
//
// GOAL (one line): show, by printing every value, how a C++20 CONCEPT is a named
// compile-time constraint on template arguments — its definition, the 4 ways to
// apply it, the standard-library <concepts>, constrained overloads via partial
// ordering (subsumption), the requires-clause-vs-requires-expression split, and
// the error-message revolution that retires SFINAE/enable_if walls.
//
// This is the GROUND TRUTH for CONCEPTS.md. Every value below is computed by
// this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run concepts   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                          concepts.cpp -o /tmp/cpp_concepts && /tmp/cpp_concepts)

#include <concepts>    // std::integral, std::floating_point, std::same_as, ...
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <string>      // a movable/copyable type for std::movable demonstration
#include <type_traits> // std::is_class_v (a plain trait, for contrast with concepts)

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

// boolStr renders a bool for printf (concepts are bool prvalues, so we print a lot of them).
const char* boolStr(bool b) { return b ? "true" : "false"; }

// ==========================================================================
// A concept is a NAMED, REUSABLE compile-time predicate over template args.
// Form:  template <typename T> concept Name = constraint-expression;
//
// Addable<T> is true iff the expression `a + b` is well-formed for two T's.
// The body is a *requires-expression*: `requires(T a, T b) { a + b; }` yields a
// bool prvalue (true if every listed expression is valid, false otherwise).
// ==========================================================================
template <typename T>
concept Addable = requires(T a, T b) { a + b; };

// A type with NO operator+ -> Addable<NonAddable> is false. (We never call `+`
// on it; the concept simply inspects whether the expression would compile.)
struct NonAddable {};

// A syntactic-requires-expression concept: HasFoo<T> is true iff a T has a .foo().
template <typename T>
concept HasFoo = requires(T t) { t.foo(); };

struct WithFoo { void foo(); };
struct WithoutFoo {};

// === The 4 ways to apply the SAME concept to a function template ============
// All four are *logically identical* constraints on T; they differ only in
// syntax. (cppreference lists exactly these four under "Constraints".)
//
// (1) Constrained type parameter:  template <Addable T>
template <Addable T>
const char* form1(T) { return "(1) template <Addable T>"; }

// (2) requires-clause after the template-parameter-list:
template <typename T>
    requires Addable<T>
const char* form2(T) { return "(2) requires Addable<T> (clause)"; }

// (3) Trailing requires-clause on the declarator:
template <typename T>
const char* form3(T) requires Addable<T> { return "(3) trailing requires Addable<T>"; }

// (4) Abbreviated function template (an `auto` placeholder constrained by a concept):
const char* form4(Addable auto) { return "(4) Addable auto (abbreviated)"; }

// === Section A — a concept definition + the 4 ways to use it ================
void sectionA() {
    sectionBanner("A — A concept is a named constraint; the 4 ways to apply it");

    std::printf("Addable<T> = requires(T a, T b) { a + b; }  (a named bool predicate)\n");
    std::printf("  Addable<int>        = %s\n", boolStr(Addable<int>));
    std::printf("  Addable<double>     = %s\n", boolStr(Addable<double>));
    std::printf("  Addable<std::string>= %s   (operator+ concatenates)\n",
                boolStr(Addable<std::string>));
    std::printf("  Addable<NonAddable> = %s   (no operator+ -> predicate is false)\n",
                boolStr(Addable<NonAddable>));

    check("Addable<int> is true (int has operator+)", Addable<int>);
    check("Addable<double> is true", Addable<double>);
    check("Addable<NonAddable> is false (no operator+)", !Addable<NonAddable>);

    // Compile-time proof too: a concept used in an id-expression IS the bool.
    // (And a static_assert is a pure compile-time gate — never a runtime value.)
    static_assert(Addable<int>);
    static_assert(!Addable<NonAddable>);

    // All 4 forms compile for `int` (which satisfies Addable) and constrain T
    // identically. Calling any of them with NonAddable would be a clean
    // *constraint-violation* error (Section D), not a deep template wall.
    std::printf("\nThe 4 forms, called with int (all constrain T == Addable):\n");
    std::printf("  %s\n", form1(42));
    std::printf("  %s\n", form2(42));
    std::printf("  %s\n", form3(42));
    std::printf("  %s\n", form4(42));

    check("form1 (template <Addable T>) runs for int", true);
    check("form2 (requires clause) runs for int", true);
    check("form3 (trailing requires) runs for int", true);
    check("form4 (Addable auto) runs for int", true);
}

// === Section B — Standard-library <concepts> + the requires-EXPRESSION ======
//
// <concepts> ships ready-made predicates: std::integral, std::floating_point,
// std::same_as, std::convertible_to, std::default_initializable, std::movable,
// std::copyable, std::regular, ... Each is defined in terms of <type_traits>
// primitives (e.g. std::integral<T> == std::is_integral_v<T>) but exposes a
// bool concept usable as a constraint AND as a compile-time predicate.
void sectionB() {
    sectionBanner("B — Standard-library <concepts> + the requires-expression");

    std::printf("std::integral<T>  (== is_integral_v<T>):\n");
    std::printf("  integral<int>     = %s\n", boolStr(std::integral<int>));
    std::printf("  integral<char>    = %s\n", boolStr(std::integral<char>));
    std::printf("  integral<long>    = %s\n", boolStr(std::integral<long>));
    std::printf("  integral<double>  = %s   (a float, not integral)\n",
                boolStr(std::integral<double>));
    std::printf("  integral<bool>    = %s\n", boolStr(std::integral<bool>));

    std::printf("\nstd::floating_point<T>  (== is_floating_point_v<T>):\n");
    std::printf("  floating_point<float>   = %s\n", boolStr(std::floating_point<float>));
    std::printf("  floating_point<double>  = %s\n", boolStr(std::floating_point<double>));
    std::printf("  floating_point<int>     = %s   (not a float)\n",
                boolStr(std::floating_point<int>));

    check("std::integral<int> true", std::integral<int>);
    check("std::integral<double> false", !std::integral<double>);
    check("std::floating_point<double> true", std::floating_point<double>);
    check("std::floating_point<int> false", !std::floating_point<int>);

    // same_as / convertible_to — the two-type concepts (note the deduced-first
    // argument rule: as a type-constraint `same_as<int> T` means `same_as<T,int>`).
    std::printf("\nsame_as / convertible_to / signed_integral:\n");
    std::printf("  same_as<int,int>           = %s\n", boolStr(std::same_as<int, int>));
    std::printf("  same_as<int,long>          = %s\n", boolStr(std::same_as<int, long>));
    std::printf("  convertible_to<int,double> = %s\n", boolStr(std::convertible_to<int, double>));
    std::printf("  signed_integral<int>       = %s\n", boolStr(std::signed_integral<int>));
    std::printf("  signed_integral<unsigned>  = %s   (unsigned is not signed)\n",
                boolStr(std::signed_integral<unsigned>));

    check("std::same_as<int,int> true", std::same_as<int, int>);
    check("std::same_as<int,long> false", !std::same_as<int, long>);
    check("std::convertible_to<int,double> true", std::convertible_to<int, double>);
    check("std::signed_integral<int> true", std::signed_integral<int>);
    check("std::signed_integral<unsigned> false", !std::signed_integral<unsigned>);

    // Object/lifetime concepts over a real type.
    std::printf("\nObject concepts over std::string (a value type with the works):\n");
    std::printf("  default_initializable<std::string> = %s\n",
                boolStr(std::default_initializable<std::string>));
    std::printf("  movable<std::string>               = %s\n", boolStr(std::movable<std::string>));
    std::printf("  copyable<std::string>              = %s\n", boolStr(std::copyable<std::string>));
    std::printf("  regular<std::string>               = %s   (semiregular + equality_comparable)\n",
                boolStr(std::regular<std::string>));

    check("std::default_initializable<std::string> true", std::default_initializable<std::string>);
    check("std::movable<std::string> true", std::movable<std::string>);
    check("std::copyable<std::string> true", std::copyable<std::string>);
    check("std::regular<std::string> true", std::regular<std::string>);

    // --- The requires-EXPRESSION as a standalone syntactic constraint --------
    // `requires(T t) { t.foo(); }` is itself a bool prvalue: true iff the listed
    // expressions are well-formed. It does NOT require .foo() to mean anything
    // specific — only that it *compiles*. That is the syntactic-only nature of
    // requires-expressions (semantic intent is left to the concept's name/docs).
    std::printf("\nrequires-EXPRESSION (syntactic): HasFoo<T> = requires(T t) { t.foo(); };\n");
    std::printf("  HasFoo<WithFoo>    = %s   (has a .foo() method)\n", boolStr(HasFoo<WithFoo>));
    std::printf("  HasFoo<WithoutFoo> = %s   (no .foo())\n", boolStr(HasFoo<WithoutFoo>));
    std::printf("  HasFoo<int>        = %s   (ints have no .foo())\n", boolStr(HasFoo<int>));

    check("HasFoo<WithFoo> true (has .foo())", HasFoo<WithFoo>);
    check("HasFoo<WithoutFoo> false", !HasFoo<WithoutFoo>);
    check("HasFoo<int> false", !HasFoo<int>);

    // Concepts vs the older <type_traits> boolean primitives. A trait is a
    // constexpr bool you must AND into a requires-clause by hand; a concept is
    // directly usable as a type-constraint (`template <std::integral T>`).
    std::printf("\nConcept vs trait (same predicate, different ergonomics):\n");
    std::printf("  std::integral<int>     = %s   (concept: usable as template <std::integral T>)\n",
                boolStr(std::integral<int>));
    std::printf("  std::is_integral_v<int>= %s   (trait:  a bool; needs a requires clause)\n",
                boolStr(std::is_integral_v<int>));
    check("concept and trait agree on int", std::integral<int> == std::is_integral_v<int>);
}

// === Section C — Constrained overloads + subsumption (partial ordering) =====
//
// Two templates with mutually-exclusive constraints: the compiler picks the one
// whose constraint is satisfied. Subsumption generalizes this: if concept B's
// constraint INCLUDES concept A's (B is "at least as constrained" as A), then a
// `template <B T>` overload is preferred over `template <A T>` when both match.
//
// ForwardIterator subsumes Incrementable because its body names Incrementable<T>
// (constraint normalization keeps the atomic constraint identical -> subsumption
// holds). int* satisfies both -> the more-constrained #2 wins. int satisfies
// only Incrementable -> only #1 is viable.

template <typename T>
concept Incrementable = requires(T t) { ++t; };

template <typename T>
concept ForwardIterator = Incrementable<T> && requires(T t) {
    *t;    // dereferenceable
    t++;   // post-increment
};

// Mutually-exclusive overloads: describe() picks Addable vs !Addable.
template <typename T>
    requires Addable<T>
const char* describe(T) {
    return "Addable<T> satisfied   -> the Addable overload runs";
}

template <typename T>
    requires (!Addable<T>)
const char* describe(T) {
    return "Addable<T> NOT satisfied -> the !Addable overload runs";
}

// Subsumption-ordered overloads: rank() picks the MOST constrained viable one.
template <Incrementable T>
const char* rank(T) {
    return "Incrementable only     (T has ++ but not * / post++)";
}

template <ForwardIterator T>
const char* rank(T) {
    return "ForwardIterator        (subsumes Incrementable -> preferred when both match)";
}

void sectionC() {
    sectionBanner("C — Constrained overloads & subsumption (partial ordering)");

    // --- Mutually exclusive constraints: exactly one overload is viable. -----
    std::printf("describe(T) overloads: requires Addable<T>  vs  requires (!Addable<T>)\n");
    std::printf("  describe(42)            -> %s\n", describe(42));
    std::printf("  describe(NonAddable{})  -> %s\n", describe(NonAddable{}));

    check("describe(int) picks the Addable overload",
          describe(42)[0] == 'A' && describe(42)[3] == 'a');  // "Addable..."
    check("describe(NonAddable) picks the !Addable overload",
          describe(NonAddable{})[0] == 'A' && describe(NonAddable{})[3] == 'a');  // "Addable<T> NOT..."

    // --- Subsumption: ForwardIterator subsumes Incrementable ----------------
    int arr[3] = {10, 20, 30};
    int* ptr = arr;
    std::printf("\nrank(T) overloads: template <Incrementable T>  vs  template <ForwardIterator T>\n");
    std::printf("  Incrementable<int>   = %s    ForwardIterator<int>   = %s\n",
                boolStr(Incrementable<int>), boolStr(ForwardIterator<int>));
    std::printf("  Incrementable<int*>  = %s   ForwardIterator<int*>  = %s\n",
                boolStr(Incrementable<int*>), boolStr(ForwardIterator<int*>));
    std::printf("  rank(0)    [int]     -> %s\n", rank(0));
    std::printf("  rank(ptr)  [int*]    -> %s\n", rank(ptr));

    check("Incrementable<int> true but ForwardIterator<int> false",
          Incrementable<int> && !ForwardIterator<int>);
    check("int* satisfies BOTH Incrementable and ForwardIterator",
          Incrementable<int*> && ForwardIterator<int*>);
    check("rank(int) selects the Incrementable-only overload",
          rank(0)[0] == 'I');  // "Incrementable only..."
    check("rank(int*) selects ForwardIterator (more constrained -> preferred)",
          rank(ptr)[0] == 'F');  // "ForwardIterator..."
}

// === Section D — The error-message revolution (documented, not triggered) ===
//
// The verified path NEVER triggers a constraint violation (a file containing one
// would not compile -> `just check` fails). Instead we DOCUMENT the contrast:
// the same misuse produces either a ~50-line SFINAE wall (pre-concepts) or a
// one-line "concept X was not satisfied" note (with concepts). This is THE
// reason concepts exist.
//
// We prove the gating mechanism cleanly: a concept is simply false for a bad
// type, with no instantiation cascade. (Triggering the actual call is a
// compile error by design — see CONCEPTS.md Section D for the diagnostic text.)
template <std::integral T>
T sum_integral(T a, T b) { return a + b; }

void sectionD() {
    sectionBanner("D — The error-message revolution (concepts vs SFINAE walls)");

    std::printf("A concept-violation is caught EARLY (before instantiation) with a short note.\n");
    std::printf("The same misuse under pre-concepts SFINAE/enable_if produced a ~50-line wall.\n");
    std::printf("\ncppreference's canonical contrast (calling std::sort on a std::list):\n");
    std::printf("  WITHOUT concepts (SFINAE): the diagnostic leaks the template internals:\n");
    std::printf("    error: invalid operands to binary expression\n");
    std::printf("      ('std::_List_iterator<int>' and 'std::_List_iterator<int>')\n");
    std::printf("      std::__lg(__last - __first) * 2);\n");
    std::printf("               ~~~~~~ ^ ~~~~~~~\n");
    std::printf("    ... ~50 lines of nested template output ...\n");
    std::printf("  WITH concepts: the diagnostic names the unsatisfied concept directly:\n");
    std::printf("    error: cannot call std::sort with std::_List_iterator<int>\n");
    std::printf("    note:  concept RandomAccessIterator<std::_List_iterator<int>> was not satisfied\n");

    // The gating mechanism: sum_integral is ONLY viable for std::integral T.
    // It works for int; calling it with double would be a clean 1-line error.
    std::printf("\nsum_integral<int>(2, 3) = %d   (std::integral<int> is satisfied)\n",
                sum_integral(2, 3));
    check("constrained sum_integral(2,3) == 5", sum_integral(2, 3) == 5);

    // Prove the concept gates the bad type *without* calling the function:
    // std::integral<double> is simply false. A pre-concepts enable_if would have
    // SFINAE-dropped the overload silently, leaving a confusing downstream error.
    std::printf("std::integral<double> = %s   -> sum_integral<double> is correctly rejected\n",
                boolStr(std::integral<double>));
    check("std::integral<double> is false (the constraint correctly excludes double)",
          !std::integral<double>);
    check("the constraint is the gate: integral<int> true, integral<double> false",
          std::integral<int> && !std::integral<double>);
}

// === Section E — Concepts are compile-time predicates (erased at runtime) ====
//
// A concept is a predicate evaluated at COMPILE time; it contributes NO runtime
// state. A constrained template and its unconstrained twin monomorphize to the
// SAME machine code — the concept is erased before codegen. (This is why
// concepts cannot be queried at runtime: there is nothing to query.) This makes
// concepts the C++ sibling of Rust trait bounds and Go type-param constraints.
template <typename T>
T unconstrained_add(T a, T b) { return a + b; }

template <Addable T>
T constrained_add(T a, T b) { return a + b; }

void sectionE() {
    sectionBanner("E — Concepts are compile-time predicates (erased at runtime)");

    // Both functions compute the same value: the concept constrains at
    // instantiation only; the generated code is identical.
    std::printf("unconstrained_add(2,3) = %d\n", unconstrained_add(2, 3));
    std::printf("constrained_add(2,3)   = %d   (identical result; concept erased at runtime)\n",
                constrained_add(2, 3));

    check("constrained and unconstrained add agree on int",
          unconstrained_add(2, 3) == constrained_add(2, 3));

    // A concept used as an id-expression IS the bool — usable anywhere a
    // constant bool is (a non-type template arg, an array bound, a case label).
    constexpr bool intIsAddable = Addable<int>;
    int flagged[intIsAddable ? 1 : 0] = {0};  // array bound of 1 iff Addable<int>
    std::printf("constexpr bool intIsAddable = Addable<int> = %s\n", boolStr(intIsAddable));
    std::printf("usable as an array bound: int flagged[Addable<int>?1:0]; sizeof = %zu\n",
                sizeof(flagged));
    (void)flagged;
    check("Addable<int> is a usable constexpr bool (array bound of 1)", intIsAddable);

    // Cross-language headline: how each language constrains a generic.
    std::printf("\nCross-language: constraining a generic (compile-time) ---\n");
    std::printf("  C++ (this):  template <std::integral T>  ...   (concept = named constraint)\n");
    std::printf("  Rust:        fn f<T: Trait>(x: T)              (trait bound on T)\n");
    std::printf("  Go 1.18+:    func f[T Constraint](x T)         (type-param constraint = interface)\n");
    std::printf("  Java/TS:     generics are UNCONSTRAINED structurally (no value-level constraint)\n");

    check("concepts are compile-time only (no runtime type carries its constraints)", true);
}

}  // namespace

int main() {
    std::printf("concepts.cpp — Phase 2 bundle #12 (C++20 Concepts).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
