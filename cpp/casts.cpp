// casts.cpp — Phase 2 bundle.
//
// GOAL (one line): show, by printing every value, how C++'s FOUR named casts
// (static_cast / dynamic_cast / const_cast / reinterpret_cast) behave — and why
// the C-style cast `(T)x` should be avoided because it silently picks the most
// dangerous cast that compiles.
//
// UB DISCIPLINE: the verified path (just run/out/check/sanitize) is UB-FREE.
// The genuinely-UB casts are DOCUMENTED and gated behind #ifdef DEMO_UB (never
// passed by the default build / sanitizer build):
//   - reinterpret_cast + DEREF of an UNRELATED type  = strict-aliasing UB
//   - const_cast + WRITE to a TRULY-const object      = UB
//   - static_cast of a WRONG polymorphic downcast      = UB (we use the SAFE form,
//     dynamic_cast, which returns nullptr on a failed pointer downcast and THROWS
//     std::bad_cast on a failed reference downcast — both defined/safe).
// The SAFE forms are demonstrated live: const_cast strips const from a NON-const
// object then modifies it (safe); reinterpret_cast round-trips a pointer through
// uintptr_t and dereferences it as the ORIGINAL type (safe); bit-pattern
// inspection is done via std::memcpy into unsigned char (the canonical,
// aliasing-legal escape). No pointer ADDRESS is ever printed (ASLR would make
// `just out` non-deterministic); only deterministic values + bools are printed.
//
// This is the GROUND TRUTH for CASTS.md. Every value below is computed by this
// file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run casts   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                       casts.cpp -o /tmp/cpp_casts && /tmp/cpp_casts)

#include <cstddef>     // std::size_t
#include <cstdint>     // std::uintptr_t, std::int32_t
#include <cstdio>      // std::printf / std::fprintf
#include <cstdlib>     // EXIT_FAILURE / std::exit
#include <cstring>     // std::memset (banner) + std::memcpy (aliasing-safe copy)
#include <typeinfo>    // std::bad_cast (thrown by failed reference dynamic_cast)

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

// A POLYMORPHIC hierarchy (>=1 virtual function). dynamic_cast downcasts REQUIRE
// a polymorphic type + RTTI (on by default). Used by Sections A (upcast) & B
// (runtime-checked downcast).
struct Animal {
    virtual ~Animal() = default;
};
struct Dog : Animal {};
struct Cat : Animal {};

// A scoped enum, for the int<->enum static_cast demo (Section A).
enum class Color { Red = 0, Green = 1, Blue = 2 };

// === Section A — static_cast: the safe everyday "related-type" cast ==========
//
// static_cast converts between RELATED types at compile time: numeric widening/
// narrowing, int<->enum, void*<->T* (inverse of the implicit T*->void*), and
// upcasts (Derived->Base). It does NO polymorphic runtime check (that is
// dynamic_cast) and does NOT reinterpret bits (that is reinterpret_cast).
void sectionA() {
    sectionBanner("A — static_cast (related-type conversions)");

    // (1) Numeric widening: int -> double (lossless for these values).
    int i = 5;
    double d = static_cast<double>(i);
    std::printf("(1) static_cast<double>(%d) = %.6f   (int -> double, widening)\n", i, d);

    // (2) double -> int TRUNCATES toward zero (no rounding). The only UB here
    //     would be if the truncated value did not fit in int — 2.9 -> 2 is fine.
    double pi = 2.9;
    int trunc = static_cast<int>(pi);
    std::printf("(2) static_cast<int>(%.6f) = %d   (double -> int TRUNCATES toward zero)\n", pi, trunc);

    // (3) int -> scoped enum and back. The integer must be representable in the
    //     enum's underlying type; 1 corresponds to the enumerator Color::Green.
    Color c = static_cast<Color>(1);
    int back = static_cast<int>(c);
    std::printf("(3) static_cast<Color>(1) -> static_cast<int> back = %d   (== Color::Green)\n", back);

    // (4) void* -> T*: the inverse of the implicit T* -> void*. You MUST cast
    //     back to the ORIGINAL type and dereference as that type — casting to a
    //     different type and reading would be aliasing UB (see Section D).
    int x = 7;
    void* vp = &x;                      // implicit int* -> void*
    int* ip = static_cast<int*>(vp);    // void* -> int* (original type: SAFE)
    std::printf("(4) void* round-trip: *static_cast<int*>(void*) = %d   (deref as ORIGINAL type)\n", *ip);

    // (5) Upcast Derived -> Base: always safe, identical to the implicit
    //     conversion. No virtual function is required for an upcast.
    Dog dog;
    Animal* a = static_cast<Animal*>(&dog);
    std::printf("(5) static_cast<Animal*>(&dog) upcast -> %s\n",
                a != nullptr ? "non-null (safe; same as implicit)" : "null");

    check("static_cast<double>(5) == 5.0", d == 5.0);
    check("static_cast<int>(2.9) == 2 (truncates toward zero)", trunc == 2);
    check("static_cast<Color>(1) round-trips to int 1 (Color::Green)", back == 1);
    check("void* round-trip deref equals original (7)", *ip == 7);
    check("static_cast upcast Dog* -> Animal* is non-null", a != nullptr);
}

// === Section B — dynamic_cast: runtime-checked polymorphic downcast ==========
//
// dynamic_cast DOWN-casts along a POLYMORPHIC hierarchy at RUNTIME, consulting
// RTTI. It requires the source type to have >=1 virtual function. On a FAILED
// downcast the behavior is DEFINED and SAFE:
//   - pointer target   -> returns nullptr     (check for null, then use)
//   - reference target -> THROWS std::bad_cast (catch it)
// This is the SAFE alternative to a static_cast downcast, where a wrong downcast
// would be UNDEFINED BEHAVIOR (static_cast trusts you blindly).
void sectionB() {
    sectionBanner("B — dynamic_cast (runtime-checked polymorphic downcast)");

    Dog dog;
    Animal* pa = &dog;   // implicit upcast; a Dog really lives behind the Animal*

    // (1) SUCCESSFUL pointer downcast to the TRUE runtime type.
    Dog* pd = dynamic_cast<Dog*>(pa);
    std::printf("(1) pa points at a Dog; dynamic_cast<Dog*>(pa) -> %s\n",
                pd != nullptr ? "non-null (correct downcast)" : "null (WRONG)");

    // (2) FAILED pointer downcast to the WRONG derived type -> nullptr (SAFE).
    Cat* pc = dynamic_cast<Cat*>(pa);   // a Dog is NOT a Cat
    std::printf("(2) a Dog is not a Cat; dynamic_cast<Cat*>(pa) -> %s (nullptr = SAFE failure)\n",
                pc == nullptr ? "nullptr" : "non-null (WRONG)");

    // (3) FAILED reference downcast to the WRONG type -> THROWS std::bad_cast.
    //     Throwing + catching is well-defined behavior (NOT UB). The reference
    //     form cannot return null (references cannot be null), so it throws.
    Animal& ra = dog;
    bool caught = false;
    try {
        [[maybe_unused]] Cat& rc = dynamic_cast<Cat&>(ra);   // a Dog is not a Cat
        (void)rc;
    } catch (const std::bad_cast&) {
        caught = true;
    }
    std::printf("(3) dynamic_cast<Cat&>(Animal& to a Dog) threw std::bad_cast -> %s\n",
                caught ? "caught (SAFE; reference form always throws on failure)"
                       : "NOT thrown (WRONG)");

    check("dynamic_cast<Dog*>(Animal* to Dog) succeeded (non-null)", pd != nullptr);
    check("dynamic_cast<Cat*>(Animal* to Dog) returned nullptr (safe failure)", pc == nullptr);
    check("dynamic_cast<Cat&>(Animal& to Dog) threw std::bad_cast (safe failure)", caught);
}

// === Section C — const_cast: add/strip const + the truly-const UB trap =======
//
// const_cast is the ONLY cast that can add or remove const/volatile. THE RULE:
// const_cast ITSELF is never UB. UB arises only when you then WRITE through the
// de-consted path to an object that was DECLARED const. Stripping const from a
// NON-const object (merely viewed through a const reference) and modifying it is
// the legitimate, defined use.
void sectionC() {
    sectionBanner("C — const_cast (add/strip const) + the truly-const UB trap");

    // (1) ADD const (rarely needed — the implicit conversion already does it).
    int n = 11;
    const int* cp = const_cast<const int*>(&n);
    std::printf("(1) const_cast<const int*>(&n) reads %d   (adding const; trivial)\n", *cp);

    // (2) STRIP const from a NON-const object accessed via const&, then modify.
    //     `n` itself is NOT const — it is merely viewed through a const int&.
    //     Writing through the de-consted reference mutates the real, mutable
    //     object. This is SAFE and is the canonical legitimate const_cast use.
    const int& cref = n;
    int& mref = const_cast<int&>(cref);   // strip const from the VIEW
    mref = 99;                            // mutate the underlying NON-const object
    std::printf("(2) int n=11; const int& cref=n; int& m=const_cast<int&>(cref); m=99;\n");
    std::printf("    -> n is now %d (SAFE: n itself was never declared const)\n", n);

    // (3) THE UB TRAP — modifying a TRULY-const object. Documented, NOT executed.
    //     `const int k = 5;` is const for real; writing through const_cast<int&>
    //     would be UB. The offending write is gated behind #ifdef DEMO_UB.
    std::printf("(3) THE TRAP (NOT executed): const int k=5; const_cast<int&>(k)=...;\n");
    std::printf("    k is TRULY const -> writing through the de-consted ref is UNDEFINED\n");
    std::printf("    BEHAVIOR (see the #ifdef DEMO_UB block; never built by default).\n");

    check("const_cast can ADD const (cp aliases n)", cp == &n);
    check("const_cast stripped const from a non-const object; n is now 99", n == 99 && mref == 99);
    check("const_cast-then-modify of a truly-const object is UB (documented, not run)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // Compile with -DDEMO_UB to build this; RUNNING it is UB. The compiler may
    // assume `k` never changes and fold the read to 5, or do anything else.
    const int k = 5;
    const_cast<int&>(k) = 999;            // <-- UB: writing to a truly-const object
    std::printf("[DEMO_UB] k = %d   <-- UNDEFINED BEHAVIOR to write\n", k);
#else
    std::printf("    (DEMO_UB not defined: the truly-const write is correctly omitted.)\n");
#endif
}

// === Section D — reinterpret_cast: bit reinterpret + the aliasing UB =========
//
// reinterpret_cast is the DANGEROUS cast: it reinterprets the BIT PATTERN
// (pointer<->pointer of an UNRELATED type, pointer<->integer). The cast itself
// is well-defined; UB comes from how you USE the result. STRICT ALIASING: a T*
// may be dereferenced only as T (or as char / unsigned char / std::byte). The
// SAFE way to "see the bits" of an unrelated type is std::memcpy into char
// storage — char aliases everything by special dispensation.
void sectionD() {
    sectionBanner("D — reinterpret_cast (bit reinterpret) + the aliasing UB");

    // (1) pointer -> uintptr_t -> pointer ROUND-TRIP, then deref as the ORIGINAL
    //     type. Well-defined and SAFE. We do NOT print the address (it changes
    //     every run under ASLR and would break `just out` determinism); we print
    //     the deterministic value behind the round-tripped pointer.
    int x = 0x01020304;   // == 16909060
    std::uintptr_t u = reinterpret_cast<std::uintptr_t>(&x);
    int* p2 = reinterpret_cast<int*>(u);   // round-trip back to int*
    std::printf("(1) reinterpret_cast<uintptr_t>(&x) -> back to int*;\n");
    std::printf("    round-trip preserves the value (*p2 == x == %d); address NOT printed (ASLR).\n", *p2);

    // (2) SAFE bit-pattern inspection: memcpy the int into an unsigned char
    //     array. unsigned char MAY alias any type — this is the canonical,
    //     UB-free type-punning technique. Output is the LITTLE-ENDIAN byte
    //     layout (deterministic on this platform; see the asserted byte[0]).
    unsigned char bytes[sizeof(int)];
    std::memcpy(bytes, &x, sizeof(int));
    std::printf("(2) std::memcpy(&x) into unsigned char[%zu] (aliasing-safe):", sizeof(int));
    for (std::size_t b = 0; b < sizeof(int); ++b)
        std::printf(" %02x", (unsigned)bytes[b]);
    std::printf("  (little-endian: low byte first)\n");

    // (3) THE UB — DOCUMENTED. We create a float* that reinterprets an int's
    //     storage but we NEVER dereference it. Reading *fp would alias an int
    //     object as a float: a STRICT-ALIASING violation (UB). The deref is
    //     gated behind #ifdef DEMO_UB so the default + sanitizer builds stay UB-free.
    [[maybe_unused]] float* fp = reinterpret_cast<float*>(&x);
    std::printf("(3) THE UB (NOT dereffed): float* fp = reinterpret_cast<float*>(&int);\n");
    std::printf("    `fp` exists, but reading *fp would be STRICT-ALIASING UB (int != float).\n");

    check("reinterpret_cast round-trip: int* -> uintptr_t -> int* preserves value", *p2 == x);
    check("round-trip pointer points back at the same object (identity)", p2 == &x);
    check("x == 0x01020304 == 16909060", x == 0x01020304);
    check("little-endian byte[0] == 0x04 (low byte first on this platform)", bytes[0] == 0x04);
    check("aliasing int-as-float deref is UB (documented; *fp never read)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // Reading *fp aliases an int object as a float: STRICT-ALIASING UB. UBSan
    // reports: "runtime error: load of type 'float' from object of type 'int'".
    std::printf("[DEMO_UB] *fp = %f   <-- UNDEFINED BEHAVIOR (aliasing)\n", *fp);
#else
    std::printf("    (DEMO_UB not defined: the aliasing deref is correctly omitted.)\n");
#endif
}

// === Section E — AVOID the C-style cast; the aliasing rule; cross-language ===
//
// The C-style cast `(T)x` is NOT one cast: the compiler tries const_cast,
// static_cast (+ derived<->base), static_cast+const_cast, reinterpret_cast, and
// reinterpret_cast+const_cast in that order and picks the FIRST that compiles —
// even when that is the aliasing-UB reinterpret_cast. It is not auditable. Prefer
// the four named casts (self-documenting + greppable).
void sectionE() {
    sectionBanner("E — AVOID the C-style cast (it silently picks the worst)");

    std::printf("The C-style cast `(T)x` is NOT one cast. The compiler tries, in order:\n");
    std::printf("    (a) const_cast<T>\n");
    std::printf("    (b) static_cast<T>  (+ derived<->base extensions)\n");
    std::printf("    (c) static_cast<T> then const_cast<T>\n");
    std::printf("    (d) reinterpret_cast<T>   <-- the dangerous one\n");
    std::printf("    (e) reinterpret_cast<T> then const_cast<T>\n");
    std::printf("and picks the FIRST that compiles — even if that is (d)/(e). It is not\n");
    std::printf("auditable: a reader cannot tell which cast actually ran. Prefer the four\n");
    std::printf("NAMED casts (self-documenting + greppable).\n");

    // (1) For a plain numeric conversion, (double)x resolves to a static_cast,
    //     so the result is identical. The danger is not the result here — it is
    //     that the C-style form HIDES which cast ran.
    int i = 5;
    double cd = (double)i;
    double sd = static_cast<double>(i);
    std::printf("(1) (double)5 = %.6f   vs   static_cast<double>(5) = %.6f\n", cd, sd);
    std::printf("    (same here: for a numeric conversion both resolve to static_cast)\n");

    // (2) THE DANGER, shown at the type-system level WITHOUT running any UB.
    //     `(float*)&int_x` silently resolves to a reinterpret_cast (d) — the most
    //     dangerous option — and compiles with no warning. The named form makes
    //     the risk VISIBLE and greppable. Neither pointer is dereferenced (a
    //     deref would be the strict-aliasing UB of Section D).
    int x = 1;
    float* cstyle = (float*)&x;                      // SILENT reinterpret_cast
    float* named = reinterpret_cast<float*>(&x);     // explicit — auditable
    std::printf("(2) `(float*)&int` and `reinterpret_cast<float*>(&int)` compile identically;\n");
    std::printf("    the C-style form HIDES that it is a reinterpret_cast. (Not dereffed.)\n");

    // (3) CROSS-LANGUAGE (no runtime here — the .md has the full comparison).
    std::printf("(3) CROSS-LANGUAGE (no runtime here; see the .md):\n");
    std::printf("    - Rust `as`: numeric only, COMPILE-CHECKED (e.g. `5_i32 as f64`).\n");
    std::printf("      `From`/`Into` are infallible + checked; `TryFrom`/`TryInto` return\n");
    std::printf("      `Result`. There is NO safe-Rust equivalent of reinterpret_cast or\n");
    std::printf("      const_cast — the UB-prone casts are impossible without `unsafe`.\n");
    std::printf("    - TypeScript `as`: COMPILE-TIME ONLY, fully ERASED at runtime (no\n");
    std::printf("      check, no conversion, no emitted code). It is a hint to the type\n");
    std::printf("      checker, not a value transformation.\n");

    check("(double)5 == static_cast<double>(5) for a numeric conversion", cd == sd);
    check("C-style (float*)&int equals reinterpret_cast<float*>(&int) (not dereffed)",
          cstyle == named);
    check("named casts are preferred over the C-style cast (documented rule)", true);
}

}  // namespace

int main() {
    std::printf("casts.cpp — Phase 2 bundle.\n");
    std::printf("The FOUR named casts + why the C-style cast is avoided.\n");
    std::printf("Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
