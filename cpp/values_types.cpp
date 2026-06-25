// values_types.cpp — Phase 1 bundle #1 (STYLE ANCHOR).
//
// GOAL (one line): show, by printing every value, how C++'s fundamental types,
// value-initialization (zero) vs default-initialization (indeterminate UB),
// sizeof/alignof, auto, and const/constexpr behave — pinning the
// uninitialized-read-UB trap as a documented expert payoff (never executed in
// the verified path).
//
// This is the GROUND TRUTH for VALUES_TYPES.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-compile ->
// re-paste. Never hand-compute.
//
// Run:
//     just run values_types   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                              values_types.cpp -o /tmp/cpp_values_types
//                              && /tmp/cpp_values_types)

#include <climits>    // CHAR_BIT (bits per byte)
#include <cstdint>    // int8_t..int64_t, INT32_MAX, UINT64_MAX, SIZE_MAX, ...
#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <limits>     // std::numeric_limits

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

// A constexpr function: evaluated at compile time when used in a constant
// expression. Section E proves it really runs at compile time by using it as an
// array bound (a runtime function could not be used there).
constexpr int square(int n) { return n * n; }

// === Section A — Fundamental types & their (implementation-defined) sizes ====
//
// The standard fixes only MINIMUM bit widths + the sizeof ordering chain; the
// absolute widths are implementation-defined (the "data model": LP64 on this
// Unix/macOS box = int 4 / long 8 / pointer 8). The ONE size fixed exactly is
// char == 1 byte (by definition); a byte is CHAR_BIT bits (8 on every modern
// platform, but the standard permits more).
void sectionA() {
    sectionBanner("A — Fundamental types: sizes & alignment (impl-defined)");

    std::printf("CHAR_BIT = %d   (bits per byte; sizeof counts THESE, not bits)\n", CHAR_BIT);
    std::printf("\ntype           sizeof  alignof\n");
    std::printf("--------------  ------  ------\n");
    std::printf("bool             %4zu    %4zu\n", sizeof(bool), alignof(bool));
    std::printf("char             %4zu    %4zu\n", sizeof(char), alignof(char));
    std::printf("signed char      %4zu    %4zu\n", sizeof(signed char), alignof(signed char));
    std::printf("unsigned char    %4zu    %4zu\n", sizeof(unsigned char), alignof(unsigned char));
    std::printf("wchar_t          %4zu    %4zu\n", sizeof(wchar_t), alignof(wchar_t));
    std::printf("char16_t         %4zu    %4zu\n", sizeof(char16_t), alignof(char16_t));
    std::printf("char32_t         %4zu    %4zu\n", sizeof(char32_t), alignof(char32_t));
    std::printf("short            %4zu    %4zu\n", sizeof(short), alignof(short));
    std::printf("int              %4zu    %4zu\n", sizeof(int), alignof(int));
    std::printf("long             %4zu    %4zu\n", sizeof(long), alignof(long));
    std::printf("long long        %4zu    %4zu\n", sizeof(long long), alignof(long long));
    std::printf("float            %4zu    %4zu\n", sizeof(float), alignof(float));
    std::printf("double           %4zu    %4zu\n", sizeof(double), alignof(double));
    std::printf("long double      %4zu    %4zu\n", sizeof(long double), alignof(long double));

    // The ONLY size the standard fixes exactly: a byte (char) is 1 by definition.
    check("sizeof(char) == 1 (by definition)", sizeof(char) == 1);
    check("sizeof(signed char) == 1", sizeof(signed char) == 1);
    check("sizeof(unsigned char) == 1", sizeof(unsigned char) == 1);
    // The standard pins the sizeof ORDERING chain, not the absolute widths.
    check("sizeof chain: 1 == sizeof(char) <= short <= int <= long <= long long",
          1 == sizeof(char) && sizeof(char) <= sizeof(short) && sizeof(short) <= sizeof(int) &&
              sizeof(int) <= sizeof(long) && sizeof(long) <= sizeof(long long));
    // Minimum guaranteed widths (bytes): short>=2, int>=2, long>=4, long long>=8.
    check("sizeof(short) >= 2 (>= 16 bits)", sizeof(short) >= 2);
    check("sizeof(int) >= 2 (>= 16 bits)", sizeof(int) >= 2);
    check("sizeof(long) >= 4 (>= 32 bits)", sizeof(long) >= 4);
    check("sizeof(long long) >= 8 (>= 64 bits)", sizeof(long long) >= 8);
    // Floats: long double is at least as wide as double, which is >= float.
    check("sizeof(float) <= sizeof(double) <= sizeof(long double)",
          sizeof(float) <= sizeof(double) && sizeof(double) <= sizeof(long double));
    check("CHAR_BIT == 8 (a byte is 8 bits on this platform)", CHAR_BIT == 8);
}

// === Section B — Fixed-width integer types (<cstdint>): the portable story ===
//
// intN_t / uintN_t are typedefs with EXACT widths and no padding bits. They are
// formally OPTIONAL (an exotic platform with no 8/16/32/64-bit type need not
// define them), but every mainstream compiler provides all of them. Use these
// whenever the bit width matters (file formats, wire protocols, hashing) and
// leave plain int/long for "just a number".
void sectionB() {
    sectionBanner("B — Fixed-width integers (<cstdint>): exact widths");

    std::printf("typedef           sizeof   min                           max\n");
    std::printf("----------------  ------   ---------------------------   ----------------------------\n");
    std::printf("std::int8_t           %zu   %-28lld  %-28lld\n",
                sizeof(std::int8_t), (long long)INT8_MIN, (long long)INT8_MAX);
    std::printf("std::int16_t          %zu   %-28lld  %-28lld\n",
                sizeof(std::int16_t), (long long)INT16_MIN, (long long)INT16_MAX);
    std::printf("std::int32_t          %zu   %-28lld  %-28lld\n",
                sizeof(std::int32_t), (long long)INT32_MIN, (long long)INT32_MAX);
    std::printf("std::int64_t          %zu   %-28lld  %-28lld\n",
                sizeof(std::int64_t), (long long)INT64_MIN, (long long)INT64_MAX);
    std::printf("std::uint64_t         %zu   %-28s  %-28llu\n",
                sizeof(std::uint64_t), "0", (unsigned long long)UINT64_MAX);
    std::printf("std::size_t           %zu   %-28s  %-28llu\n",
                sizeof(std::size_t), "0", (unsigned long long)SIZE_MAX);
    std::printf("\n(the width-flexible typedefs: at-least-N, not exactly-N)\n");
    std::printf("std::int_fast32_t   %2zu bytes  (fastest  signed int with width >= 32)\n",
                sizeof(std::int_fast32_t));
    std::printf("std::int_least32_t  %2zu bytes  (smallest  signed int with width >= 32)\n",
                sizeof(std::int_least32_t));
    std::printf("std::intptr_t       %2zu bytes  (signed;   holds a void* of %zu bytes)\n",
                sizeof(std::intptr_t), sizeof(void*));
    std::printf("std::uintptr_t      %2zu bytes  (unsigned; holds a void*)\n",
                sizeof(std::uintptr_t));

    check("sizeof(std::int8_t) == 1", sizeof(std::int8_t) == 1);
    check("sizeof(std::int16_t) == 2", sizeof(std::int16_t) == 2);
    check("sizeof(std::int32_t) == 4", sizeof(std::int32_t) == 4);
    check("sizeof(std::int64_t) == 8", sizeof(std::int64_t) == 8);
    check("INT8_MAX == 127", INT8_MAX == 127);
    check("INT32_MAX == 2147483647", INT32_MAX == 2147483647);
    check("INT64_MAX == 9223372036854775807",
          INT64_MAX == 9223372036854775807LL);
    check("UINT64_MAX == 18446744073709551615",
          UINT64_MAX == 18446744073709551615ULL);
    // intptr_t must be wide enough to losslessly hold a void* bit pattern.
    check("sizeof(std::intptr_t) == sizeof(void*)", sizeof(std::intptr_t) == sizeof(void*));
}

// === Section C — Value-init (zero) vs Default-init (indeterminate UB) =======
//
// THE expert payoff of the whole bundle. Two ways to write "a variable", two
// utterly different outcomes:
//
//   T x{};   value-initialization   -> for a scalar, ZERO.                 SAFE.
//   T x;     default-initialization -> for an AUTOMATIC scalar, NO init at
//                                      all -> INDETERMINATE value. READING
//                                      it (print/compare/branch) is UB.
//
// We DEMONSTRATE value-init by printing the zeros; we DOCUMENT the default-init
// trap and gate the offending read behind #ifdef DEMO_UB, which is NEVER passed
// by `just run`/`just out`/`just check`/`just sanitize` (so the default build
// and the sanitizer build stay UB-free).
void sectionC() {
    sectionBanner("C — Value-init (zero) vs Default-init (indeterminate)");

    // (1) VALUE-initialization: `T x{};` (the C++11 brace form) or `T x = T();`.
    //     For a scalar this performs ZERO-initialization: 0 / 0.0 / nullptr /
    //     false. These are SAFE to read and print.
    int vi{};            // 0
    double vd{};         // 0.0
    int* vp{};           // nullptr
    bool vb{};           // false
    std::printf("(1) VALUE-initialization (T x{}): scalars are ZERO, safe to read\n");
    std::printf("    int     x{}  = %d\n", vi);
    std::printf("    double  x{}  = %.6f\n", vd);
    std::printf("    int*    x{}  = %s\n", vp == nullptr ? "nullptr" : "non-null");
    std::printf("    bool    x{}  = %s\n", vb ? "true" : "false");

    check("value-initialized int == 0", vi == 0);
    check("value-initialized double == 0.0", vd == 0.0);
    check("value-initialized int* == nullptr", vp == nullptr);
    check("value-initialized bool == false", vb == false);

    // (2) STATIC storage duration: even though the SYNTAX is `T x;` (no
    //     initializer, i.e. default-init), objects with STATIC storage duration
    //     are ZERO-initialized first (then default-init, which does nothing for
    //     scalars). So a static `int si;` is 0. SAFE to read.
    static int si;      // static -> zero-initialized before first use
    std::printf("\n(2) STATIC default-init (static int si;): two-phase -> ZERO, safe\n");
    std::printf("    static int si = %d\n", si);
    check("static default-initialized int == 0 (two-phase zero-init)", si == 0);

    // (3) AUTOMATIC storage duration, default-init: NO initialization at all.
    //     `int di;` holds whatever bytes were on the stack -> INDETERMINATE
    //     value. READING `di` (the printf / the comparison / the branch) is
    //     UNDEFINED BEHAVIOR. We therefore DECLINE to read it: [[maybe_unused]]
    //     silences the unused-variable warning, and no line in this verified
    //     path touches its value. (C++26 will reclassify this read as "erroneous
    //     behaviour" rather than UB; under C++23 it remains UB.)
    [[maybe_unused]] int di;   // <- indeterminate; deliberately NEVER read here

    std::printf("\n(3) AUTOMATIC default-init (int di;): INDETERMINATE — read is UB\n");
    std::printf("    (the verified path does NOT read `di`; the #ifdef DEMO_UB block below\n");
    std::printf("     shows the read you must NOT write, compiled only with -DDEMO_UB)\n");
    check("automatic default-init NOT read (reading an indeterminate value is UB)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // Compile with -DDEMO_UB to see this build; RUNNING it is UB. Reading
    // `garbage` has NO defined result: UBSan reports
    //   "runtime error: load of value <N>, which is not a valid value for type 'int'"
    // and the printed value is meaningless (a compiler entitled to assume no UB
    // may even fold the read to an arbitrary constant).
    int garbage;   // default-initialized -> indeterminate
    std::printf("[DEMO_UB] int garbage = %d   <-- UNDEFINED BEHAVIOR to read\n", garbage);
#else
    std::printf("    (DEMO_UB not defined: the UB read is correctly omitted from this build.)\n");
#endif
}

// === Section D — sizeof / alignof / alignas + std::numeric_limits ===========
void sectionD() {
    sectionBanner("D — sizeof / alignof / alignas + numeric_limits");

    // sizeof yields a std::size_t (a constant expression). alignof yields a
    // std::size_t too; alignment is ALWAYS a power of two.
    std::printf("sizeof  returns std::size_t (%zu bytes); alignof likewise.\n", sizeof(std::size_t));
    std::printf("alignof: char=%zu  short=%zu  int=%zu  double=%zu  int64_t=%zu  void*=%zu\n",
                alignof(char), alignof(short), alignof(int), alignof(double),
                alignof(std::int64_t), alignof(void*));

    // alignas lets you REQUIRE a stronger alignment for a type/object. It must
    // be a power of two and not weaker than the type's natural alignment; the
    // compiler pads sizeof up to a multiple of the alignment so objects pack
    // correctly into arrays.
    struct alignas(16) Aligned16 { int x; };
    struct Natural { int x; };
    std::printf("alignas(16): alignof(Aligned16)=%zu  sizeof(Aligned16)=%zu "
                "(vs Natural align=%zu size=%zu)\n",
                alignof(Aligned16), sizeof(Aligned16),
                alignof(Natural), sizeof(Natural));

    // std::numeric_limits<T> is the portable query for type limits. It fully
    // replaces the C <climits>/<cfloat> macros (INT_MAX, DBL_EPSILON, ...) and
    // works for ANY arithmetic type, including aliases like std::size_t.
    std::printf("numeric_limits<int>    : min=%lld  lowest=%lld  max=%lld\n",
                (long long)std::numeric_limits<int>::min(),
                (long long)std::numeric_limits<int>::lowest(),
                (long long)std::numeric_limits<int>::max());
    std::printf("numeric_limits<unsigned>: min=%llu  lowest=%llu  max=%llu\n",
                (unsigned long long)std::numeric_limits<unsigned>::min(),
                (unsigned long long)std::numeric_limits<unsigned>::lowest(),
                (unsigned long long)std::numeric_limits<unsigned>::max());
    std::printf("numeric_limits<double> : min=%.6e  lowest=%.6e  max=%.6e  epsilon=%.6e\n",
                std::numeric_limits<double>::min(),
                std::numeric_limits<double>::lowest(),
                std::numeric_limits<double>::max(),
                std::numeric_limits<double>::epsilon());

    check("alignof(char) == 1 (the smallest possible alignment)", alignof(char) == 1);
    check("alignof(std::int64_t) is a power of two",
          (alignof(std::int64_t) & (alignof(std::int64_t) - 1)) == 0);
    check("alignas(16) raised the alignment to 16", alignof(Aligned16) == 16);
    check("alignas(16) padded sizeof to a multiple of 16", sizeof(Aligned16) % 16 == 0);
    check("sizeof(Aligned16) >= sizeof(int)", sizeof(Aligned16) >= sizeof(int));
    check("numeric_limits<int>::max() == 2147483647",
          std::numeric_limits<int>::max() == 2147483647);
    check("numeric_limits<int>::min() == -2147483648",
          std::numeric_limits<int>::min() == -2147483647 - 1);
    check("numeric_limits<double>::epsilon() > 0.0",
          std::numeric_limits<double>::epsilon() > 0.0);
}

// === Section E — auto (deduction) + const (immutable) + constexpr ===========
//
// Note the VALUE-vs-REFERENCE axis threaded through `auto`: plain `auto` COPIES
// (it strips top-level const and the &, exactly like template argument
// deduction); `auto&` keeps a reference alias. That copy-vs-alias fork is the
// entire subject of REFERENCES_POINTERS_INTRO (bundle #2).
void sectionE() {
    sectionBanner("E — auto (deduction) + const + constexpr");

    // --- auto: deduces the type from the initializer using the SAME rules as
    //     template argument deduction. Plain `auto` makes a COPY.
    int x = 5;
    auto val = x;          // int — a COPY of x (auto drops nothing here)
    val = 999;             // reassigns the COPY; x is untouched

    int& ref = x;          // int& — a genuine ALIAS of x
    auto aref = ref;       // int — auto STRIPS the &, so this is a COPY of x (5)
    auto& realref = ref;   // int& — explicit & keeps it: an ALIAS of x
    realref = 7;           // mutates x THROUGH the alias

    std::printf("int x = 5;  auto val = x;  val = 999;  -> val=%d, x=%d (auto COPIED)\n",
                val, x);
    std::printf("auto aref = ref;        -> aref=%d (auto stripped the & -> a COPY of old x)\n",
                aref);
    std::printf("auto& realref = ref; realref = 7;     -> x=%d (auto& kept the alias)\n", x);

    check("auto deduces int from an int initializer", val == 999);
    check("plain `auto` made a COPY: val = 999 did not change x", x == 7);
    check("auto stripped the &: aref captured x's value at copy time (5)", aref == 5);
    check("auto& kept the reference: realref = 7 changed x to 7", x == 7 && realref == 7);

    // --- const: a const object cannot be modified after initialization.
    //     (Bonus: in C++, a `const` variable at namespace scope has INTERNAL
    //     linkage by default — the opposite of C, where it is external.)
    const int ci = 42;
    std::printf("\nconst int ci = 42;  -> ci = %d  (a later `ci = 7;` is a compile error)\n", ci);
    check("const int holds its initialized value", ci == 42);

    // --- constexpr: the value CAN be evaluated at compile time, so it is usable
    //     in any constant expression (array bound, template argument, case
    //     label, ...). constexpr on a variable also implies const.
    constexpr int N = square(3);   // square(3) == 9, computed at compile time
    int arr[N];                    // N is usable as an array bound -> 9 ints
    for (int i = 0; i < N; ++i) arr[i] = i * i;
    std::printf("\nconstexpr int N = square(3);  -> N = %d  (compile-time evaluated)\n", N);
    std::printf("int arr[N]; uses N as an array bound -> sizeof(arr) = %zu bytes\n", sizeof(arr));
    // Touch arr so it is not optimized away and we can confirm its contents.
    int sum = 0;
    for (int i = 0; i < N; ++i) sum += arr[i];
    std::printf("sum of arr (0*0 + 1*1 + ... + 8*8) = %d\n", sum);

    check("constexpr square(3) == 9", N == 9);
    check("constexpr N is usable as an array bound (arr has N elements)",
          sizeof(arr) / sizeof(arr[0]) == static_cast<std::size_t>(N));
    check("constexpr implies const: N is immutable and == 9", N == 9);
    check("arr contents are the squares 0..64 (sum of squares 0..8)", sum == 204);
}

}  // namespace

int main() {
    std::printf("values_types.cpp — Phase 1 bundle #1 (STYLE ANCHOR).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
