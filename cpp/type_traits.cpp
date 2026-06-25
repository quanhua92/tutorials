// type_traits.cpp — Phase 6 bundle.
//
// GOAL (one line): show, by printing every boolean and asserting every
// resulting type via std::is_same_v, how <type_traits> provides COMPILE-TIME
// TYPE INTROSPECTION (queries -> bool: is_integral_v, is_same_v, is_base_of_v,
// is_convertible_v) and TYPE TRANSFORMATION (maps -> type: remove_const_t,
// remove_reference_t, add_const_t, decay_t) — the building blocks of SFINAE,
// modernized by C++20 concepts.
//
// This is the GROUND TRUTH for TYPE_TRAITS.md. Every value/table below is
// printed by this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// Determinism note: every value below is a COMPILE-TIME CONSTANT (type traits
// are evaluated by the compiler, never at runtime). Output is therefore 100%
// reproducible across runs/machines for a given ABI. Types are asserted with
// std::is_same_v<...> and the boolean is PRINTED (never typeid().name(), whose
// output is impl-defined and nondeterministic).
//
// Run:
//     just run type_traits   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                              type_traits.cpp -o /tmp/cpp_type_traits
//                              && /tmp/cpp_type_traits)

#include <concepts>    // std::integral, std::convertible_to, std::derived_from (traits vs concepts)
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <cstdint>     // std::int32_t (a typedef — used to show is_same on aliases)
#include <string>      // std::string (a class type — used for is_class_v)
#include <type_traits> // the whole metaprogramming library

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

// Types used by the introspection queries below.
struct MyClass {};        // a plain class
struct Base {};           // a base class
struct Derived : Base {}; // publicly derived from Base
struct Other {};          // unrelated class
enum MyEnum {};           // an unscoped enum
union MyUnion {};         // a union

// === Section A — Primary type categories + the _v (C++17) bool shortcut ======
//
// The PRIMARY category traits partition every type into one bucket: integral,
// floating_point, class, union, enum, array, pointer, function, reference,
// member_pointer, null_pointer, void. They answer "what KIND of thing is T?"
// Each is exposed in THREE equivalent spellings:
//     C++11:  std::is_integral<T>::value        (a member constant)
//     C++17:  std::is_integral_v<T>             (a variable template = the bool)
// (the C++14 _t alias is for TRANSFORMATIONS, covered in Section C).
//
// Expert detail: std::is_integral_v<bool> is TRUE — bool IS an integral type
// (the standard lists bool among the integral types). So is char, signed char,
// unsigned char, the char*_t family, short/int/long/long long + signed/unsigned.
void sectionA() {
    sectionBanner("A — Primary categories + the _v (C++17) bool shortcut");

    std::printf("PRIMARY CATEGORY TRAITS (each returns a compile-time bool):\n\n");
    std::printf("trait                              result\n");
    std::printf("---------------------------------- ------\n");
    std::printf("is_integral_v<int>                 %s\n", b(std::is_integral_v<int>));
    std::printf("is_integral_v<bool>                %s   (bool IS integral)\n",
                b(std::is_integral_v<bool>));
    std::printf("is_integral_v<char>                %s\n", b(std::is_integral_v<char>));
    std::printf("is_integral_v<std::size_t>         %s   (size_t is an integer typedef)\n",
                b(std::is_integral_v<std::size_t>));
    std::printf("is_integral_v<double>              %s   (floats are NOT integral)\n",
                b(std::is_integral_v<double>));
    std::printf("is_integral_v<std::string>         %s\n",
                b(std::is_integral_v<std::string>));

    std::printf("is_floating_point_v<float>         %s\n",
                b(std::is_floating_point_v<float>));
    std::printf("is_floating_point_v<double>        %s\n",
                b(std::is_floating_point_v<double>));
    std::printf("is_floating_point_v<int>           %s\n",
                b(std::is_floating_point_v<int>));

    std::printf("is_class_v<MyClass>                %s\n", b(std::is_class_v<MyClass>));
    std::printf("is_class_v<std::string>            %s   (string is a class)\n",
                b(std::is_class_v<std::string>));
    std::printf("is_class_v<int>                    %s\n", b(std::is_class_v<int>));
    std::printf("is_class_v<MyEnum>                 %s   (enums are NOT classes)\n",
                b(std::is_class_v<MyEnum>));

    std::printf("is_pointer_v<int*>                 %s\n", b(std::is_pointer_v<int*>));
    std::printf("is_pointer_v<std::string*>         %s\n",
                b(std::is_pointer_v<std::string*>));
    std::printf("is_pointer_v<int>                  %s\n", b(std::is_pointer_v<int>));
    std::printf("is_pointer_v<int&>                 %s   (references are NOT pointers)\n",
                b(std::is_pointer_v<int&>));

    std::printf("is_enum_v<MyEnum>                  %s\n", b(std::is_enum_v<MyEnum>));
    std::printf("is_array_v<int[5]>                 %s\n", b(std::is_array_v<int[5]>));
    std::printf("is_union_v<MyUnion>                %s\n", b(std::is_union_v<MyUnion>));
    std::printf("is_void_v<void>                    %s\n", b(std::is_void_v<void>));

    // The OLD ::value form is EXACTLY the same bool; _v is just sugar.
    std::printf("\nThe _v shortcut vs the old ::value form (identical bool):\n");
    std::printf("  C++11:  std::is_integral<int>::value   = %s\n",
                b(std::is_integral<int>::value));
    std::printf("  C++17:  std::is_integral_v<int>        = %s   (same bool, less typing)\n",
                b(std::is_integral_v<int>));

    check("is_integral_v<int> == true", std::is_integral_v<int>);
    check("is_integral_v<bool> == true (bool IS integral)", std::is_integral_v<bool>);
    check("is_integral_v<double> == false (floats are not integral)",
          !std::is_integral_v<double>);
    check("is_floating_point_v<double> == true", std::is_floating_point_v<double>);
    check("is_class_v<std::string> == true", std::is_class_v<std::string>);
    check("is_pointer_v<int*> == true", std::is_pointer_v<int*>);
    check("is_pointer_v<int&> == false (a reference is not a pointer)",
          !std::is_pointer_v<int&>);
    check("is_enum_v<MyEnum> == true", std::is_enum_v<MyEnum>);
    check("is_integral<int>::value == is_integral_v<int> (the two forms agree)",
          std::is_integral<int>::value == std::is_integral_v<int>);
}

// === Section B — Type relations (is_same / is_base_of / is_convertible) ======
//
// The RELATION traits take TWO types and answer a question about their
// relationship. All three return bool; all three have _v shortcuts.
//
//   is_same_v<T, U>        : do T and U name the SAME type (incl. cv-qualifiers)?
//   is_base_of_v<B, D>     : is D derived from B (or are they the same class)?
//   is_convertible_v<F, T> : can an lvalue of type F be IMPLICITLY converted to T?
//
// is_same_v is THE foundational check — it is how EVERY other type claim in
// this curriculum is verified (see 🔗 TYPE_DEDUCTION). It is what we use to
// assert the result of a TRANSFORMATION in Section C (transformations yield a
// TYPE, not a bool — only is_same_v can pin them down).
void sectionB() {
    sectionBanner("B — Type relations (is_same / is_base_of / is_convertible)");

    // --- is_same_v: the type-equality check. cv-qualifiers make DIFFERENT types.
    std::printf("is_same_v<T, U> (type equality — cv-qualifiers make distinct types):\n");
    std::printf("  is_same_v<int, int>            = %s\n", b(std::is_same_v<int, int>));
    std::printf("  is_same_v<int, const int>      = %s   (const matters!)\n",
                b(std::is_same_v<int, const int>));
    std::printf("  is_same_v<int, int&>           = %s   (a reference is a distinct type)\n",
                b(std::is_same_v<int, int&>));
    std::printf("  is_same_v<int, unsigned int>   = %s   (signedness matters)\n",
                b(std::is_same_v<int, unsigned int>));
    // A typedef is the SAME type as its target (no new type is introduced).
    std::printf("  is_same_v<int, std::int32_t>   = %s   (int32_t is a typedef of int here)\n",
                b(std::is_same_v<int, std::int32_t>));

    // --- is_base_of_v: does D inherit from B?
    //   Subtle: a class is a base OF ITSELF (is_base_of_v<Base, Base> == true).
    std::printf("\nis_base_of_v<Base, Derived> (inheritance — incl. private/ambiguous):\n");
    std::printf("  is_base_of_v<Base, Derived>    = %s   (Derived : Base)\n",
                b(std::is_base_of_v<Base, Derived>));
    std::printf("  is_base_of_v<Derived, Base>    = %s   (reversed: false)\n",
                b(std::is_base_of_v<Derived, Base>));
    std::printf("  is_base_of_v<Base, Base>       = %s   (a class is a base of ITSELF)\n",
                b(std::is_base_of_v<Base, Base>));
    std::printf("  is_base_of_v<Base, Other>      = %s   (unrelated)\n",
                b(std::is_base_of_v<Base, Other>));

    // --- is_convertible_v: IMPLICIT conversion (what a cast-free expression does).
    //   Derived* -> Base* : implicit UP-cast (true). Base* -> Derived* : needs
    //   static_cast (false). This is the foundation of overload/SFINAE dispatch.
    std::printf("\nis_convertible_v<From, To> (IMPLICIT conversion only — no casts):\n");
    std::printf("  is_convertible_v<Derived*, Base*> = %s   (upcast is implicit)\n",
                b(std::is_convertible_v<Derived*, Base*>));
    std::printf("  is_convertible_v<Base*, Derived*> = %s   (downcast needs static_cast)\n",
                b(std::is_convertible_v<Base*, Derived*>));
    std::printf("  is_convertible_v<int, double>     = %s   (numeric promotion)\n",
                b(std::is_convertible_v<int, double>));
    std::printf("  is_convertible_v<double, int>     = %s   (narrowing, but still implicit)\n",
                b(std::is_convertible_v<double, int>));
    std::printf("  is_convertible_v<std::string, int> = %s\n",
                b(std::is_convertible_v<std::string, int>));

    check("is_same_v<int, int>", std::is_same_v<int, int>);
    check("is_same_v<int, const int> == false (cv makes distinct types)",
          !std::is_same_v<int, const int>);
    check("is_same_v<int, std::int32_t> == true on this LP64 ABI",
          std::is_same_v<int, std::int32_t>);
    check("is_base_of_v<Base, Derived>", std::is_base_of_v<Base, Derived>);
    check("is_base_of_v<Derived, Base> == false (reversed)",
          !std::is_base_of_v<Derived, Base>);
    check("is_base_of_v<Base, Base> == true (reflexive)",
          std::is_base_of_v<Base, Base>);
    check("is_convertible_v<Derived*, Base*> (implicit upcast)",
          std::is_convertible_v<Derived*, Base*>);
    check("is_convertible_v<Base*, Derived*> == false (downcast needs static_cast)",
          !std::is_convertible_v<Base*, Derived*>);
}

// === Section C — Type TRANSFORMATIONS (map -> type; assert via is_same_v) ====
//
// The TRANSFORMATION traits take a type and PRODUCE a new type. They do NOT
// return a bool — so the only way to assert their result is to compare the
// output type against an expected type with std::is_same_v, and print THAT bool.
// (You cannot "print a type" portably — typeid().name() is impl-defined mangled
// garbage — so we pin each transform with an is_same_v check + its boolean.)
//
// Each transformation has a _t (C++14) alias template:
//     C++11:  std::remove_const<const int>::type    (a member typedef)
//     C++14:  std::remove_const_t<const int>         (an alias = the type itself)
//
// decay_t is the crown jewel: it applies the EXACT conversions the language
// performs when passing an argument BY VALUE to a template (array -> pointer,
// function -> function pointer, strip cv-ref). It is how std::tuple, std::function,
// std::thread, and almost every generic "store-by-value" wrapper normalize the T.
void sectionC() {
    sectionBanner("C — Type TRANSFORMATIONS (yield a type; assert via is_same_v)");

    // --- cv-qualifier additions/removals.
    std::printf("cv-qualifier additions / removals (assert via is_same_v):\n");
    std::printf("  remove_const_t<const int>          == int        ? %s\n",
                b(std::is_same_v<std::remove_const_t<const int>, int>));
    std::printf("  remove_volatile_t<volatile int>    == int        ? %s\n",
                b(std::is_same_v<std::remove_volatile_t<volatile int>, int>));
    std::printf("  remove_cv_t<const volatile int>    == int        ? %s\n",
                b(std::is_same_v<std::remove_cv_t<const volatile int>, int>));
    std::printf("  add_const_t<int>                   == const int  ? %s\n",
                b(std::is_same_v<std::add_const_t<int>, const int>));
    std::printf("  add_cv_t<int>                      == const vola ? %s\n",
                b(std::is_same_v<std::add_cv_t<int>, const volatile int>));

    // --- reference additions/removals.
    std::printf("\nreference additions / removals:\n");
    std::printf("  remove_reference_t<int&>           == int        ? %s\n",
                b(std::is_same_v<std::remove_reference_t<int&>, int>));
    std::printf("  remove_reference_t<int&&>          == int        ? %s\n",
                b(std::is_same_v<std::remove_reference_t<int&&>, int>));
    std::printf("  add_lvalue_reference_t<int>        == int&       ? %s\n",
                b(std::is_same_v<std::add_lvalue_reference_t<int>, int&>));
    std::printf("  add_rvalue_reference_t<int>        == int&&      ? %s\n",
                b(std::is_same_v<std::add_rvalue_reference_t<int>, int&&>));

    // --- pointer addition.
    std::printf("\npointer addition:\n");
    std::printf("  add_pointer_t<int>                 == int*       ? %s\n",
                b(std::is_same_v<std::add_pointer_t<int>, int*>));
    std::printf("  remove_pointer_t<int*>             == int        ? %s\n",
                b(std::is_same_v<std::remove_pointer_t<int*>, int>));

    // --- decay_t: the template-deduction-by-value simulation.
    //   array of T    -> T*
    //   function F    -> pointer-to-F (F*)
    //   otherwise     -> remove_cv(remove_reference(T))
    std::printf("\ndecay_t<T> — simulates passing T BY VALUE to a template:\n");
    std::printf("  decay_t<int>                       == int        ? %s\n",
                b(std::is_same_v<std::decay_t<int>, int>));
    std::printf("  decay_t<int&>                      == int        ? %s   (ref stripped)\n",
                b(std::is_same_v<std::decay_t<int&>, int>));
    std::printf("  decay_t<int&&>                     == int        ? %s   (rref stripped)\n",
                b(std::is_same_v<std::decay_t<int&&>, int>));
    std::printf("  decay_t<const int&>                == int        ? %s   (cv AND ref stripped)\n",
                b(std::is_same_v<std::decay_t<const int&>, int>));
    std::printf("  decay_t<int[5]>                    == int*       ? %s   (array -> pointer)\n",
                b(std::is_same_v<std::decay_t<int[5]>, int*>));
    std::printf("  decay_t<int(int)>                  == int(*)(int)? %s   (function -> fn-ptr)\n",
                b(std::is_same_v<std::decay_t<int(int)>, int (*)(int)>));
    // Multi-dim arrays decay ONE LEVEL only: int[4][2] -> int(*)[2], NOT int**.
    std::printf("  decay_t<int[4][2]>                 == int(*)[2]  ? %s   (one level only)\n",
                b(std::is_same_v<std::decay_t<int[4][2]>, int (*)[2]>));

    // --- remove_cvref_t (C++20): the common one-liner = remove_cv<remove_reference<T>>.
    std::printf("\nremove_cvref_t (C++20) — the modern shortcut for cv+ref stripping:\n");
    std::printf("  remove_cvref_t<const int&>         == int        ? %s\n",
                b(std::is_same_v<std::remove_cvref_t<const int&>, int>));
    std::printf("  remove_cvref_t<int&&>              == int        ? %s\n",
                b(std::is_same_v<std::remove_cvref_t<int&&>, int>));

    // The _t alias vs the old ::type form (identical type).
    std::printf("\nThe _t shortcut vs the old ::type form (identical type):\n");
    std::printf("  C++11:  std::remove_const<const int>::type   == int ? %s\n",
                b(std::is_same_v<std::remove_const<const int>::type, int>));
    std::printf("  C++14:  std::remove_const_t<const int>       == int ? %s\n",
                b(std::is_same_v<std::remove_const_t<const int>, int>));

    check("remove_const_t<const int> == int",
          std::is_same_v<std::remove_const_t<const int>, int>);
    check("remove_cv_t<const volatile int> == int",
          std::is_same_v<std::remove_cv_t<const volatile int>, int>);
    check("remove_reference_t<int&> == int",
          std::is_same_v<std::remove_reference_t<int&>, int>);
    check("remove_reference_t<int&&> == int",
          std::is_same_v<std::remove_reference_t<int&&>, int>);
    check("add_const_t<int> == const int",
          std::is_same_v<std::add_const_t<int>, const int>);
    check("add_pointer_t<int> == int*",
          std::is_same_v<std::add_pointer_t<int>, int*>);
    check("decay_t<const int&> == int (cv AND ref stripped)",
          std::is_same_v<std::decay_t<const int&>, int>);
    check("decay_t<int[5]> == int* (array decays to pointer)",
          std::is_same_v<std::decay_t<int[5]>, int*>);
    check("decay_t<int(int)> == int(*)(int) (function decays to fn-ptr)",
          std::is_same_v<std::decay_t<int(int)>, int (*)(int)>);
    check("decay_t<int[4][2]> == int(*)[2] (one level only)",
          std::is_same_v<std::decay_t<int[4][2]>, int (*)[2]>);
    check("remove_cvref_t<const int&> == int (C++20 shortcut)",
          std::is_same_v<std::remove_cvref_t<const int&>, int>);
    check("remove_const<T>::type == remove_const_t<T> (the two forms agree)",
          std::is_same_v<std::remove_const<const int>::type,
                         std::remove_const_t<const int>>);
}

// === Section D — Composite categories + property queries (rank / extent) ====
//
// COMPOSITE category traits are unions of the primary categories:
//   is_arithmetic_v = is_integral_v || is_floating_point_v
//   is_object_v     = !(is_reference_v || is_void_v || is_function_v)
//   is_scalar_v     = is_arithmetic_v || is_enum_v || is_pointer_v ||
//                     is_member_pointer_v || is_null_pointer_v
//
// PROPERTY-QUERY traits return a NUMBER (a size_t), not a bool:
//   rank_v<T>      = number of array dimensions (0 if T is not an array)
//   extent_v<T, N> = bound of the Nth dimension (0 if none)
// These let generic code handle arrays of arbitrary rank.
void sectionD() {
    sectionBanner("D — Composite categories + property queries (rank / extent)");

    std::printf("COMPOSITE category traits (unions of the primary categories):\n");
    std::printf("  is_arithmetic_v<int>          = %s   (integral OR floating_point)\n",
                b(std::is_arithmetic_v<int>));
    std::printf("  is_arithmetic_v<double>       = %s\n",
                b(std::is_arithmetic_v<double>));
    std::printf("  is_arithmetic_v<bool>         = %s   (bool is integral -> arithmetic)\n",
                b(std::is_arithmetic_v<bool>));
    std::printf("  is_arithmetic_v<int*>         = %s   (pointers are NOT arithmetic)\n",
                b(std::is_arithmetic_v<int*>));
    std::printf("  is_arithmetic_v<std::string>  = %s\n",
                b(std::is_arithmetic_v<std::string>));

    std::printf("\n  is_object_v<int>              = %s   (an int IS an object)\n",
                b(std::is_object_v<int>));
    std::printf("  is_object_v<int&>             = %s   (references are NOT objects)\n",
                b(std::is_object_v<int&>));
    std::printf("  is_object_v<void>             = %s   (void is incomplete)\n",
                b(std::is_object_v<void>));

    std::printf("\n  is_scalar_v<int>              = %s\n", b(std::is_scalar_v<int>));
    std::printf("  is_scalar_v<MyEnum>           = %s   (enums are scalars)\n",
                b(std::is_scalar_v<MyEnum>));
    std::printf("  is_scalar_v<int*>             = %s\n", b(std::is_scalar_v<int*>));

    // Property queries (return size_t, not bool).
    std::printf("\nPROPERTY QUERIES (return std::size_t — a dimension, not a bool):\n");
    std::printf("  rank_v<int>                   = %zu   (not an array -> 0 dimensions)\n",
                std::rank_v<int>);
    std::printf("  rank_v<int[10]>               = %zu   (1-dimensional)\n",
                std::rank_v<int[10]>);
    std::printf("  rank_v<int[3][4]>             = %zu   (2-dimensional)\n",
                std::rank_v<int[3][4]>);
    std::printf("  rank_v<int[2][3][4]>          = %zu   (3-dimensional)\n",
                std::rank_v<int[2][3][4]>);

    std::printf("\n  extent_v<int, 0>              = %zu   (not an array -> 0)\n",
                std::extent_v<int, 0>);
    std::printf("  extent_v<int[10]>             = %zu   (== extent_v<int[10], 0>)\n",
                std::extent_v<int[10]>);
    std::printf("  extent_v<int[3][4], 0>        = %zu\n", std::extent_v<int[3][4], 0>);
    std::printf("  extent_v<int[3][4], 1>        = %zu   (the inner dimension)\n",
                std::extent_v<int[3][4], 1>);
    std::printf("  extent_v<int[3], 5>           = %zu   (no such dimension -> 0)\n",
                std::extent_v<int[3], 5>);

    std::printf("\nsizeof the array TYPES (the extent product * sizeof element):\n");
    std::printf("  sizeof(int[10])    = %zu   (10 * %zu)\n",
                sizeof(int[10]), sizeof(int));
    std::printf("  sizeof(int[3][4])  = %zu   (3 * 4 * %zu)\n",
                sizeof(int[3][4]), sizeof(int));

    check("is_arithmetic_v<int>", std::is_arithmetic_v<int>);
    check("is_arithmetic_v<double>", std::is_arithmetic_v<double>);
    check("is_arithmetic_v<bool> (bool is arithmetic)", std::is_arithmetic_v<bool>);
    check("is_arithmetic_v<int*> == false (pointers are not arithmetic)",
          !std::is_arithmetic_v<int*>);
    check("is_object_v<int>", std::is_object_v<int>);
    check("is_object_v<int&> == false (references are not objects)", !std::is_object_v<int&>);
    check("is_scalar_v<MyEnum> (enums are scalars)", std::is_scalar_v<MyEnum>);
    check("rank_v<int> == 0 (not an array)", std::rank_v<int> == static_cast<std::size_t>(0));
    check("rank_v<int[10]> == 1", std::rank_v<int[10]> == static_cast<std::size_t>(1));
    check("rank_v<int[3][4]> == 2", std::rank_v<int[3][4]> == static_cast<std::size_t>(2));
    check("extent_v<int[3][4], 1> == 4",
          std::extent_v<int[3][4], 1> == static_cast<std::size_t>(4));
    check("extent_v<int> == 0 (not an array)", std::extent_v<int> == static_cast<std::size_t>(0));
    check("sizeof(int[3][4]) == 3 * 4 * sizeof(int)",
          sizeof(int[3][4]) == 3 * 4 * sizeof(int));
}

// === Section E — How traits work + _v/_t history + traits vs concepts ========
//
// (1) THE IMPLEMENTATION TRICK. Every trait is a primary class template that
//     DERIVES FROM std::false_type (so ::value == false for ANY T by default),
//     plus a list of FULL/PartIAL SPECIALIZATIONS — one per type the trait is
//     true for — that derive from std::true_type (::value == true). The compiler
//     picks the most-specific specialization; if none matches, the primary
//     template wins (false). That is the entire mechanism. We hand-roll a tiny
//     is_my_integral<T> below to prove it.
//
// (2) _v (C++17 variable templates) and _t (C++14 alias templates) are SUGAR
//     over the C++11 ::value / ::type forms — same bool, same type, less typing.
//
// (3) TRAITS vs CONCEPTS (C++20). Many category/relation traits have concept
//     equivalents: std::integral<T>, std::convertible_to<F,T>, std::derived_from
//     <D,B>. Concepts CONSTRAINT templates with named diagnostics; traits are
//     the lower-level bool predicates that concepts are built on top of.
namespace demo {

// A hand-rolled is_integral-ish trait: primary = false_type, specializations =
// true_type for int/long/etc. This is EXACTLY how the real std::is_integral is
// implemented (modulo the full list of integral types).
template <class T>
struct is_my_integral : std::false_type {};          // primary: false for ALL T
template <> struct is_my_integral<bool>      : std::true_type {};
template <> struct is_my_integral<char>      : std::true_type {};
template <> struct is_my_integral<short>     : std::true_type {};
template <> struct is_my_integral<int>       : std::true_type {};
template <> struct is_my_integral<long>      : std::true_type {};
template <> struct is_my_integral<long long> : std::true_type {};
// (a real impl also specializes signed/unsigned char, wchar_t, char8/16/32_t,
//  unsigned short/int/long/long long, and the cv-qualified variants.)

}  // namespace demo

void sectionE() {
    sectionBanner("E — The implementation trick + _v/_t history + traits vs concepts");

    // (1) The primary-template + specializations mechanism, proven by a hand-rolled trait.
    std::printf("(1) A HAND-ROLLED is_my_integral<T> (primary = false_type + specializations):\n");
    std::printf("    is_my_integral<int>::value         = %s   (specialization hit)\n",
                b(demo::is_my_integral<int>::value));
    std::printf("    is_my_integral<long>::value        = %s   (specialization hit)\n",
                b(demo::is_my_integral<long>::value));
    std::printf("    is_my_integral<double>::value      = %s   (PRIMARY template: false)\n",
                b(demo::is_my_integral<double>::value));
    std::printf("    is_my_integral<std::string>::value = %s   (PRIMARY template: false)\n",
                b(demo::is_my_integral<std::string>::value));

    check("hand-rolled is_my_integral<int>::value (specialization matches)",
          demo::is_my_integral<int>::value);
    check("hand-rolled is_my_integral<double>::value == false (primary template wins)",
          !demo::is_my_integral<double>::value);

    // (2) _v (C++17) / _t (C++14) shortcuts vs the C++11 ::value / ::type forms.
    std::printf("\n(2) The _v / _t SHORTCUTS vs the old ::value / ::type forms:\n");
    std::printf("    QUERY  (-> bool):\n");
    std::printf("      C++11:  std::is_integral<int>::value              = %s\n",
                b(std::is_integral<int>::value));
    std::printf("      C++17:  std::is_integral_v<int>                   = %s   (variable template)\n",
                b(std::is_integral_v<int>));
    std::printf("    TRANSFORM (-> type):\n");
    std::printf("      C++11:  std::remove_const<const int>::type == int ? %s\n",
                b(std::is_same_v<std::remove_const<const int>::type, int>));
    std::printf("      C++14:  std::remove_const_t<const int>      == int ? %s   (alias template)\n",
                b(std::is_same_v<std::remove_const_t<const int>, int>));

    check("is_integral<int>::value == is_integral_v<int>",
          std::is_integral<int>::value == std::is_integral_v<int>);

    // (3) Traits vs concepts (C++20): the modern replacement for many traits.
    std::printf("\n(3) TRAITS vs CONCEPTS (C++20): the modern replacement for category/relation traits\n");
    std::printf("    trait (bool)                       concept (constraint)            same answer?\n");
    std::printf("    ----------------------------------  -----------------------------  -------------\n");
    std::printf("    is_integral_v<int>           = %s   std::integral<int>           = %s   %s\n",
                b(std::is_integral_v<int>), b(std::integral<int>),
                b(std::is_integral_v<int> == std::integral<int>));
    std::printf("    is_integral_v<double>        = %s  std::integral<double>        = %s  %s\n",
                b(std::is_integral_v<double>), b(std::integral<double>),
                b(std::is_integral_v<double> == std::integral<double>));
    std::printf("    is_base_of_v<Base,Derived>   = %s   std::derived_from<Derived,Base> = %s   %s\n",
                b(std::is_base_of_v<Base, Derived>), b(std::derived_from<Derived, Base>),
                b(std::is_base_of_v<Base, Derived> == std::derived_from<Derived, Base>));
    std::printf("    is_convertible_v<Derived*,Base*> = %s   std::convertible_to<Derived*,Base*> = %s   %s\n",
                b(std::is_convertible_v<Derived*, Base*>),
                b(std::convertible_to<Derived*, Base*>),
                b(std::is_convertible_v<Derived*, Base*> == std::convertible_to<Derived*, Base*>));

    // Compile-time proofs via static_assert (the concept constraints).
    static_assert(std::integral<int>);
    static_assert(!std::integral<double>);
    static_assert(std::derived_from<Derived, Base>);
    static_assert(std::convertible_to<Derived*, Base*>);
    std::printf("\n    static_assert(std::integral<int>);                       passes\n");
    std::printf("    static_assert(!std::integral<double>);                    passes\n");
    std::printf("    static_assert(std::derived_from<Derived, Base>);         passes\n");
    std::printf("    static_assert(std::convertible_to<Derived*, Base*>);     passes\n");
    std::printf("\n    -> Concepts give NAMED constraint-failure diagnostics instead of an\n");
    std::printf("       SFINAE substitution-failure wall of template spew. But they cannot\n");
    std::printf("       REPLACE transformations (remove_const_t, decay_t) — there is no\n");
    std::printf("       'remove_const concept'; traits remain the type-level compute layer.\n");

    check("std::integral<int> (concept form) == is_integral_v<int>",
          std::integral<int> == std::is_integral_v<int>);
    check("std::integral<double> == false (matches the trait)",
          !std::integral<double> && !std::is_integral_v<double>);
    check("std::derived_from<Derived, Base> == is_base_of_v<Base, Derived>",
          std::derived_from<Derived, Base> == std::is_base_of_v<Base, Derived>);
    check("std::convertible_to<Derived*, Base*> == is_convertible_v<Derived*, Base*>",
          std::convertible_to<Derived*, Base*> == std::is_convertible_v<Derived*, Base*>);
}

}  // namespace

int main() {
    std::printf("type_traits.cpp — Phase 6 bundle.\n");
    std::printf("Compile-time TYPE INTROSPECTION (queries -> bool) + TRANSFORMATION (maps -> type).\n");
    std::printf("Every value below is a COMPILE-TIME constant; asserted via std::is_same_v + the boolean.\n");
    std::printf("Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
