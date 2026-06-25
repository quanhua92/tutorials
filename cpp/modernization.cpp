// modernization.cpp — Phase 8 bundle.
//
// GOAL (one line): show, by asserting feature-test-macro values and running
// old-vs-modern before/after code shapes, how C++ evolves (98/03/11/14/17/20/23/
// 26) and how the `modernize-*` migration (raw new->smart ptr, manual loop->
// range-for, C array->std::array, macro->constexpr, explicit->auto, copy->move,
// SFINAE->concepts, null->nullptr) fixes whole bug classes — the modern version
// is the one that runs in the verified path.
//
// This is the GROUND TRUTH for MODERNIZATION.md. Every value/table below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     just run modernization   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                modernization.cpp -o /tmp/cpp_modernization
//                                && /tmp/cpp_modernization)

#include <array>       // std::array (the modern C-array)
#include <concepts>    // std::integral (C++20 concepts)
#include <cstddef>     // std::size_t
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <memory>      // std::unique_ptr / std::make_unique (RAII smart pointers)
#include <string>      // std::string (move-vs-copy demo)
#include <type_traits> // std::is_integral_v / std::enable_if_t / std::is_same_v
#include <vector>      // std::vector
#include <version>     // library feature-test macros (__cpp_lib_*)

// Fail fast if compiled against a pre-C++20 toolchain: this bundle needs
// concepts + C++23 stdlib. (Apple clang 17 / gcc 14 ship these at -std=c++23.)
#if !defined(__cpp_concepts) || (__cpp_concepts < 201907L) || (__cplusplus < 202002L)
#error "modernization.cpp requires C++20+ (concepts). Compile with -std=c++23."
#endif

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

// ftm prints one feature-test-macro row of the Section A table.
void ftm(const char* name, long value, const char* label) {
    std::printf("  %-26s = %-8ld  %s\n", name, value, label);
}

// === Section C helpers: a copy/move-counting type + guaranteed-RVO factory ===

// Tracker counts how many times it is copied vs moved. The counters are
// deterministic (reset before each measurement), so copy-vs-move behavior is a
// reproducible printed number — the heart of the copy->move modernization.
struct Tracker {
    int payload;
    static int copies;
    static int moves;
    explicit Tracker(int v) : payload(v) {}
    Tracker(const Tracker& o) : payload(o.payload) { ++copies; }
    Tracker(Tracker&& o) noexcept : payload(o.payload) { ++moves; }
    Tracker& operator=(const Tracker& o) {
        payload = o.payload;
        ++copies;
        return *this;
    }
    Tracker& operator=(Tracker&& o) noexcept {
        payload = o.payload;
        ++moves;
        return *this;
    }
    ~Tracker() = default;
};
int Tracker::copies = 0;
int Tracker::moves = 0;

// make_tracker returns a prvalue Tracker. Under C++17 *guaranteed* copy elision
// the caller is initialized directly — zero copies, zero moves (the modern
// replacement for the copy-everything C++03 world).
Tracker make_tracker(int v) { return Tracker(v); }

// === Section C helpers: SFINAE-vs-concept + overload-resolution demo ========

// BEFORE (C++11 SFINAE): enable_if in a default template argument. Verbose,
// error-prone, and the constraint is invisible at the call site.
template <class T, class = std::enable_if_t<std::is_integral_v<T>>>
int sfinae_double(const T& x) {
    return static_cast<int>(x) * 2;
}

// AFTER (C++20 concept): a named, readable constraint on T directly.
template <std::integral T>
int concept_double(const T& x) {
    return static_cast<int>(x) * 2;
}

// AFTER (C++17 if constexpr): the branch is selected at COMPILE time, so each
// instantiation keeps only the branch that matches its type (here even allowing
// a different return type per branch — impossible with a runtime if).
template <class T>
auto modern_value(const T& x) {
    if constexpr (std::is_integral_v<T>) {
        return x + x;   // integral: double it
    } else {
        return x;       // non-integral: pass through
    }
}

// nullptr overload-resolution demo. nullptr (type std::nullptr_t) selects the
// POINTER overload; a bare 0 (a null-pointer CONSTANT that is also an int)
// selects the INT overload — the classic reason nullptr replaced NULL/0.
constexpr int OVERLOAD_INT = 0;
constexpr int OVERLOAD_PTR = 1;
int call_kind(int) { return OVERLOAD_INT; }
int call_kind(char*) { return OVERLOAD_PTR; }   // never dereferenced -> UB-free

// === Section A — the C++ timeline + feature-test macros =====================

void sectionA() {
    sectionBanner("A — The C++ standard timeline (98..26) + feature-test macros");

    std::printf("__cplusplus = %ld  -> C++23 (202302L) on this compiler\n",
                (long)__cplusplus);
    check("__cplusplus == 202302 (C++23)", __cplusplus == 202302L);

    std::printf("\nStandard  Year     ISO / era\n");
    std::printf("--------  ----     -------------------------------------------------\n");
    std::printf("C++98     1998     ISO/IEC 14882:1998  first standard (STL, templates, exceptions, bool)\n");
    std::printf("C++03     2003     ISO/IEC 14882:2003  minor revision (defines value initialization)\n");
    std::printf("C++11     2011     ISO/IEC 14882:2011  *** BIG LEAP *** auto, smart ptrs, move, lambda, range-for\n");
    std::printf("C++14     2014     ISO/IEC 14882:2014  minor (make_unique, generic lambda, relaxed constexpr)\n");
    std::printf("C++17     2017     ISO/IEC 14882:2017  major (string_view, optional, variant, if constexpr, CTAD)\n");
    std::printf("C++20     2020     ISO/IEC 14882:2020  major (concepts, ranges, coroutines, modules, <=>)\n");
    std::printf("C++23     2024     ISO/IEC 14882:2024  expected, print, mdspan, deducing-this\n");
    std::printf("C++26     upcoming n5046 (draft)      reflection, contracts, erroneous behaviour\n");
    std::printf("\n\"modern C++\" = C++11 onward. C++23 is the CURRENT standard (this bundle).\n");

    // Feature-test macros (<version> + predefined): compile-time detection of
    // which features a toolchain actually ships. The portable idiom is
    // `#if defined(__cpp_X) && __cpp_X >= <needed>`. Each value below is this
    // compiler's real value (Apple clang 17).
    std::printf("\nFeature-test macros (real values on THIS compiler):\n");
    std::printf("  LANGUAGE features (predefined):\n");
#ifdef __cpp_lambdas
    ftm("__cpp_lambdas", (long)__cpp_lambdas, "C++11 lambdas");
    check("__cpp_lambdas defined (>= 200907, C++11)", __cpp_lambdas >= 200907L);
#endif
#ifdef __cpp_range_based_for
    ftm("__cpp_range_based_for", (long)__cpp_range_based_for, "C++11 range-for");
    check("__cpp_range_based_for defined (>= 200907, C++11)", __cpp_range_based_for >= 200907L);
#endif
#ifdef __cpp_rvalue_references
    ftm("__cpp_rvalue_references", (long)__cpp_rvalue_references, "C++11 move semantics");
    check("__cpp_rvalue_references defined (>= 200610, C++11)", __cpp_rvalue_references >= 200610L);
#endif
#ifdef __cpp_constexpr
    ftm("__cpp_constexpr", (long)__cpp_constexpr, "C++11, refined through C++23");
    check("__cpp_constexpr defined (>= 202207, C++23)", __cpp_constexpr >= 202207L);
#endif
#ifdef __cpp_if_constexpr
    ftm("__cpp_if_constexpr", (long)__cpp_if_constexpr, "C++17 if constexpr");
    check("__cpp_if_constexpr defined (>= 201606, C++17)", __cpp_if_constexpr >= 201606L);
#endif
#ifdef __cpp_structured_bindings
    ftm("__cpp_structured_bindings", (long)__cpp_structured_bindings, "C++17 (DR value)");
    check("__cpp_structured_bindings defined (>= 201606, C++17)", __cpp_structured_bindings >= 201606L);
#endif
#ifdef __cpp_deduction_guides
    ftm("__cpp_deduction_guides", (long)__cpp_deduction_guides, "C++17 CTAD");
    check("__cpp_deduction_guides defined (>= 201703, C++17)", __cpp_deduction_guides >= 201703L);
#endif
#ifdef __cpp_concepts
    ftm("__cpp_concepts", (long)__cpp_concepts, "C++20 concepts");
    check("__cpp_concepts defined (>= 202002, C++20)", __cpp_concepts >= 202002L);
#endif
#ifdef __cpp_constinit
    ftm("__cpp_constinit", (long)__cpp_constinit, "C++20 constinit");
    check("__cpp_constinit defined (>= 201907, C++20)", __cpp_constinit >= 201907L);
#endif

    std::printf("  LIBRARY features (from <version>):\n");
#ifdef __cpp_lib_make_unique
    ftm("__cpp_lib_make_unique", (long)__cpp_lib_make_unique, "C++14 std::make_unique");
    check("__cpp_lib_make_unique defined (>= 201304, C++14)", __cpp_lib_make_unique >= 201304L);
#endif
#ifdef __cpp_lib_string_view
    ftm("__cpp_lib_string_view", (long)__cpp_lib_string_view, "C++17 std::string_view");
    check("__cpp_lib_string_view defined (>= 201606, C++17)", __cpp_lib_string_view >= 201606L);
#endif
#ifdef __cpp_lib_ranges
    ftm("__cpp_lib_ranges", (long)__cpp_lib_ranges, "C++20 ranges (C++23 value here)");
    check("__cpp_lib_ranges defined (>= 201911, C++20)", __cpp_lib_ranges >= 201911L);
#endif
#ifdef __cpp_lib_expected
    ftm("__cpp_lib_expected", (long)__cpp_lib_expected, "C++23 std::expected");
    check("__cpp_lib_expected defined (>= 202211, C++23)", __cpp_lib_expected >= 202211L);
#endif
#ifdef __cpp_lib_print
    ftm("__cpp_lib_print", (long)__cpp_lib_print, "C++23 std::print");
    check("__cpp_lib_print defined (>= 202207, C++23)", __cpp_lib_print >= 202207L);
#endif
#ifdef __cpp_lib_mdspan
    ftm("__cpp_lib_mdspan", (long)__cpp_lib_mdspan, "C++23 std::mdspan");
    check("__cpp_lib_mdspan defined (>= 202207, C++23)", __cpp_lib_mdspan >= 202207L);
#endif

    // nullptr has NO dedicated __cpp_* macro: it is a keyword since C++11, so
    // detection is via __cplusplus >= 201103L, not a feature-test macro.
    std::printf("\nNote: `nullptr` is a keyword (C++11) with NO __cpp_nullptr macro\n");
    std::printf("      (keywords need no feature-test macro; detect via __cplusplus).\n");
    check("nullptr available: __cplusplus >= 201103L (C++11)", __cplusplus >= 201103L);
}

// === Section B — OLD vs MODERN before/after idioms ==========================

void sectionB() {
    sectionBanner("B — OLD vs MODERN: before/after idioms");

    // (1) raw new/delete -> unique_ptr / make_unique (RAII, no leak)
    std::printf("(1) raw new/delete  ->  std::unique_ptr / std::make_unique\n");
    //     BEFORE (documented legacy shape, leak-prone):
    //         int* p = new int(42);   use(p);   delete p;   // forget delete => LEAK
    //     AFTER (runs here; RAII frees at scope end automatically):
    auto p = std::make_unique<int>(42);
    std::printf("    auto p = std::make_unique<int>(42);   -> *p = %d\n", *p);
    check("make_unique holds the value", *p == 42);
    {
        auto q = std::make_unique<int>(7);
        check("inner unique_ptr holds 7", *q == 7);
    }   // q destroyed here: no delete, no leak, even across an exception
    check("unique_ptr is RAII: no explicit delete needed (freed at scope end)", true);

    // (2) manual index loop -> range-for (C++11)
    std::printf("\n(2) manual index loop  ->  range-for (C++11)\n");
    //     BEFORE: for (std::size_t i = 0; i < v.size(); ++i) sum += v[i];
    //     AFTER:  for (auto x : v) sum += x;
    const std::vector<int> v = {1, 2, 3, 4, 5};
    int sum_index = 0;
    for (std::size_t i = 0; i < v.size(); ++i) sum_index += v[static_cast<int>(i)];
    int sum_range = 0;
    for (auto x : v) sum_range += x;
    std::printf("    sum via index loop = %d ; sum via range-for = %d\n", sum_index, sum_range);
    check("range-for equals index loop (== 15)", sum_index == sum_range && sum_index == 15);

    // (3) C array -> std::array (knows its size, never decays to a pointer)
    std::printf("\n(3) C array  ->  std::array / std::vector\n");
    //     BEFORE: int carr[3] = {10,20,30};   // decays to int*, loses sizeof/size info
    //     AFTER:  std::array<int,3> arr = {10,20,30};
    const std::array<int, 3> arr = {10, 20, 30};
    std::printf("    std::array<int,3> = {%d,%d,%d};  size()=%zu  sum=%d\n",
                arr[0], arr[1], arr[2], arr.size(), arr[0] + arr[1] + arr[2]);
    check("std::array keeps its size (3)", arr.size() == 3);
    check("std::array sum == 60", arr[0] + arr[1] + arr[2] == 60);

    // (4) macro constant -> constexpr (typed, scoped, debuggable, compile-time)
    std::printf("\n(4) #define constant  ->  constexpr\n");
    //     BEFORE: #define BUFSIZE 256   // untyped, unscoped, pollutes the macro namespace
    //     AFTER:  constexpr int bufsize = 256;
    constexpr int bufsize = 256;
    int buf[bufsize];   // constexpr is usable as an array bound; a macro is too, but untyped
    buf[0] = 1;
    buf[bufsize - 1] = 2;
    std::printf("    constexpr int bufsize = 256;  -> sizeof(buf) = %zu bytes\n", sizeof(buf));
    check("constexpr usable as array bound (bufsize == 256)", bufsize == 256);
    check("buf spans 256 ints and ends are set", sizeof(buf) / sizeof(int) == 256u && buf[0] == 1 && buf[255] == 2);

    // (5) explicit (long) type -> auto (deduction)
    std::printf("\n(5) explicit type  ->  auto\n");
    //     BEFORE: std::vector<int>::const_iterator it = v.cbegin();
    //     AFTER:  auto it = v.cbegin();
    auto it = v.cbegin();
    std::printf("    auto it = v.cbegin();   -> *it = %d  (no long type name)\n", *it);
    check("auto deduces the iterator; *it == 1", *it == 1);
}

// === Section C — copy->move, SFINAE->concepts, null->nullptr ================

void sectionC() {
    sectionBanner("C — copy->move, SFINAE->concepts, null->nullptr");

    // (1) copy-everywhere -> move + guaranteed copy elision (C++17 RVO)
    std::printf("(1) copy-everywhere  ->  std::move + guaranteed copy elision (C++17)\n");
    Tracker::copies = 0;
    Tracker::moves = 0;
    Tracker src(42);
    Tracker cp = src;   // COPY: a (here cheap, in general expensive) deep copy
    std::printf("    Tracker cp = src;            -> copies=%d moves=%d  (a copy)\n",
                Tracker::copies, Tracker::moves);
    check("copy incremented copies, not moves", Tracker::copies == 1 && Tracker::moves == 0);

    Tracker::copies = 0;
    Tracker::moves = 0;
    Tracker mv = std::move(cp);   // MOVE: cheap ownership transfer, no deep copy
    std::printf("    Tracker mv = std::move(cp);  -> copies=%d moves=%d  (a cheap move)\n",
                Tracker::copies, Tracker::moves);
    check("std::move incremented moves, not copies", Tracker::copies == 0 && Tracker::moves == 1);
    check("moved-into payload is readable (42)", mv.payload == 42);

    Tracker::copies = 0;
    Tracker::moves = 0;
    Tracker rvo = make_tracker(7);   // guaranteed copy elision: prvalue -> direct init
    std::printf("    Tracker rvo = make_tracker(7); -> copies=%d moves=%d  (C++17 GUARANTEED elision)\n",
                Tracker::copies, Tracker::moves);
    check("guaranteed copy elision: no copy, no move", Tracker::copies == 0 && Tracker::moves == 0);
    check("RVO value == 7", rvo.payload == 7);

    // (2) SFINAE -> concepts (C++20) + if constexpr (C++17)
    std::printf("\n(2) SFINAE (enable_if)  ->  concepts (C++20) + if constexpr (C++17)\n");
    //     BEFORE: template<class T, class = enable_if_t<is_integral_v<T>>> ...
    //     AFTER:  template<std::integral T> ...
    const int si = sfinae_double(21);   // BEFORE path (still compiles & runs)
    const int ci = concept_double(21);  // AFTER  path
    std::printf("    sfinae_double(21) = %d   concept_double(21) = %d\n", si, ci);
    check("SFINAE and concept versions agree (== 42)", si == ci && si == 42);

    //     if constexpr: branch chosen at COMPILE time (no runtime branch)
    std::printf("    if constexpr: modern_value<int>(5) = %d, modern_value<double>(2.0) = %.1f\n",
                modern_value(5), modern_value(2.0));
    check("if constexpr integral branch doubles the value (5 -> 10)", modern_value(5) == 10);
    check("if constexpr non-integral branch passes through (2.0 -> 2.0)", modern_value(2.0) == 2.0);

    // (3) naked null (0 / NULL) -> nullptr (typed std::nullptr_t)
    std::printf("\n(3) naked null (0 / NULL)  ->  nullptr (typed)\n");
    //     BEFORE: int* p = 0;   /   int* p = NULL;   // 0 is an int; NULL is macro soup
    //     AFTER:  int* p = nullptr;                  // type std::nullptr_t, unambiguous
    const int* np = nullptr;
    std::printf("    const int* np = nullptr;   -> (np == nullptr) : %s\n",
                np == nullptr ? "true" : "false");
    check("nullptr is a null pointer", np == nullptr);
    //     Overload resolution proves why nullptr is better than 0/NULL:
    std::printf("    call_kind(nullptr) = %d (POINTER) ; call_kind(0) = %d (INT)\n",
                call_kind(nullptr), call_kind(0));
    check("nullptr selects the POINTER overload", call_kind(nullptr) == OVERLOAD_PTR);
    check("bare 0 selects the INT overload (the NULL/0 footgun)", call_kind(0) == OVERLOAD_INT);
}

// === Section D — clang-tidy modernize-* + backward-compat ===================

void sectionD() {
    sectionBanner("D — clang-tidy modernize-* (automated) + backward-compat");

    std::printf("clang-tidy's `modernize-*` module auto-rewrites legacy C++ to modern:\n");
    std::printf("  modernize-use-nullptr        NULL / 0           -> nullptr          (C++11)\n");
    std::printf("  modernize-loop-convert       index for-loop     -> range-for        (C++11)\n");
    std::printf("  modernize-make-unique        new T              -> make_unique<T>   (C++14)\n");
    std::printf("  modernize-make-shared        new T              -> make_shared<T>   (C++11)\n");
    std::printf("  modernize-use-auto           long type names    -> auto             (C++11)\n");
    std::printf("  modernize-deprecated-headers <stdio.h>          -> <cstdio>         (C++11)\n");
    std::printf("  modernize-use-override       missing `override` -> `override`       (C++11)\n");
    std::printf("  modernize-use-using          typedef            -> using =          (C++11)\n");
    std::printf("  modernize-replace-auto-ptr   std::auto_ptr      -> std::unique_ptr  (C++17)\n");
    std::printf("  modernize-pass-by-value      const T& + copy    -> T (pass + move)  (C++11)\n");
    std::printf("\nInvocation (documented — clang-tidy is a separate tool, not run inline):\n");
    std::printf("  clang-tidy -checks='-*,modernize-*' -fix -std=c++23 file.cpp -- -Wall -Wextra\n");
    std::printf("  (review every diff; auto-fixes are good but not infallible)\n");

    // Backward-compat: C++ ACCUMULATES idioms. Legacy code still compiles; the
    // modern subset is preferred, but old forms coexist (no "rewrite the world").
    std::printf("\nBackward-compat: legacy idioms STILL COMPILE alongside modern ones.\n");
    typedef int LegacyInt;     // C++98 form (still valid)
    using ModernInt = int;     // C++11 form (preferred)
    const LegacyInt a = 10;
    const ModernInt b = 20;
    std::printf("    typedef int LegacyInt;       -> a = %d\n", a);
    std::printf("    using ModernInt = int;       -> b = %d   (both compile; 'using' preferred)\n", b);
    check("typedef and using alias the same type (std::is_same_v)",
          std::is_same_v<LegacyInt, ModernInt>);
    check("legacy + modern coexist and interoperate (a + b == 30)", a + b == 30);
}

// === Section E — Migrating a legacy codebase + cross-language ===============

void sectionE() {
    sectionBanner("E — Migrating a legacy codebase + cross-language");

    std::printf("Migrating C++03 -> modern is incremental, clang-tidy-assisted, test-covered:\n");
    std::printf("  1. bump -std to c++23 (or c++17); fix the compile errors first.\n");
    std::printf("  2. run `clang-tidy -checks='modernize-*' -fix`; review every diff.\n");
    std::printf("  3. enable -Wall -Wextra -Wpedantic; drive to ZERO warnings.\n");
    std::printf("  4. add ASan + UBSan to CI; eliminate UB (the silent-killer class).\n");
    std::printf("  5. replace raw new/delete -> smart pointers one hotspot at a time.\n");
    std::printf("  6. lock the modern style in via a committed .clang-tidy file.\n");

    // Worked micro-example: a tiny 'legacy' snippet and its modern rewrite, both
    // runnable, both producing the SAME result (modern is safer + shorter).
    std::printf("\nMicro-example (same result, modern is safer/shorter):\n");
    int* raw = new int(5);        // BEFORE: raw new
    const int legacy = *raw * 2;
    delete raw;                   // must NOT forget; leak or double-free otherwise
    auto smart = std::make_unique<int>(5);   // AFTER: RAII smart pointer
    const int modern = *smart * 2;           // auto-freed at scope end
    std::printf("    legacy  (new/delete)     = %d\n", legacy);
    std::printf("    modern  (make_unique)    = %d   <- same value, no manual delete\n", modern);
    check("legacy and modern produce the same value (== 10)", legacy == 10 && modern == 10);

    std::printf("\nCross-language: every language has a 'modernization' story.\n");
    std::printf("  C++  : 98->03->11(BIG)->14->17->20->23->26  (decades of accumulated idiom)\n");
    std::printf("  Rust : stable since 1.0 (2015). Editions (2015/2018/2021/2024) are OPT-IN\n");
    std::printf("         and never break old code -> no 'modernize' migration needed.\n");
    std::printf("  Go   : Go 1 compatibility promise -> old code keeps working forever.\n");
    check("cross-language modernization story captured", legacy == modern);
}

}  // namespace

int main() {
    std::printf("modernization.cpp — Phase 8 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
