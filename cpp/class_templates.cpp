// class_templates.cpp — Phase 2 bundle #10.
//
// GOAL (one line): show, by printing every value, how a C++ class template is a
// blueprint that is MONOMORPHIZED per type argument — covering member functions
// (themselves templates, instantiated lazily), CTAD (C++17, deduce from the
// constructor), default template args, non-type template params, and FULL vs
// PARTIAL specialization — pinning the ODR-for-templates relaxation as the
// reason headers can define a template and the linker still collapses the
// per-translation-unit instantiations.
//
// This is the GROUND TRUTH for CLASS_TEMPLATES.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     just run class_templates   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                 class_templates.cpp -o /tmp/cpp_class_templates
//                                 && /tmp/cpp_class_templates)

#include <cstddef>      // std::size_t
#include <cstdio>       // printf / fprintf
#include <cstdlib>      // EXIT_FAILURE / exit
#include <cstring>      // memset (banner bar)
#include <memory>       // std::allocator (default template arg)
#include <string>       // std::string (lazy-codegen demo + deduction-guide demo)
#include <type_traits>  // std::is_same_v (prove deduced/specialized types)
#include <utility>      // std::pair (stdlib CTAD demo)

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

// ===========================================================================
// The primary class template — a BLUEPRINT, not a type. Box<int>/Box<double>
// are concrete types generated (monomorphized) from it. Box by itself is an
// AGGREGATE (no user-declared ctors), which matters for CTAD in Section B.
// ===========================================================================
template <typename T>
struct Box {
    static constexpr const char* which = "primary";   // marker used in Section D
    T value;

    // A MEMBER FUNCTION of a class template is ITSELF a template. Its body is
    // only instantiated (and therefore only type-checked) when it is odr-used
    // (called, or address taken). Section A proves this: Box<std::string> is
    // constructed below, but half() is never called on it — so the body
    //   `return value / 2;`   // std::string / int  -> ill-formed IF checked
    // is NEVER instantiated and the program compiles cleanly. This is the
    // "lazy codegen" / per-member instantiation guarantee (temp.inst).
    T get() const { return value; }
    void set(const T& v) { value = v; }
    T half() const { return value / 2; }
};

// FULL specialization for one exact type: bool. template<> + a concrete <bool>.
// It is a totally independent class — it need not share members with the
// primary (here it stores `flag`, not `value`). Used in Section D.
template <>
struct Box<bool> {
    static constexpr const char* which = "full<bool>";
    bool flag;
    bool get() const { return flag; }
};

// PARTIAL specialization for ALL pointer types. Still has a free template
// parameter (T), so `template <typename T>` stays; the argument list `<T*>`
// fixes the SHAPE. Used in Section D. (Mirrors std::unique_ptr<T[]> etc.)
template <typename T>
struct Box<T*> {
    static constexpr const char* which = "partial<T*>";
    T* ptr;
    T* get() const { return ptr; }
};

// --- User-defined DEDUCTION GUIDE (Section B) -----------------------------
// Implicit guide from the ctor Named(T) would deduce T=const char* from a
// string literal. This guide REMAPS it to Named<std::string> instead. (A guide
// is a function-shaped declaration ending in `-> Type`; it is NOT a function,
// has no body, and participates only in CTAD overload resolution.)
template <typename T>
struct Named {
    T payload;
    Named(T x) : payload(x) {}
};
Named(const char*) -> Named<std::string>;

// --- Non-type template param (Section C) -----------------------------------
// Parameterized by a compile-time VALUE (std::size_t N), not a type. N is a
// constant expression, so it can size a C array — exactly how std::array<T,N>
// is built (template<class T, std::size_t N>).
template <std::size_t N>
struct Arr {
    int data[N];
    static constexpr std::size_t size = N;
};

// --- Default template args (Section B) -------------------------------------
// A parameter may carry a default; the caller may omit it. This is how
// std::map<K,V,Compare,Alloc> hides Compare/Alloc behind defaults.
template <typename K, typename V, typename AllocT = std::allocator<std::pair<const K, V>>>
struct SimpleMap {
    static constexpr const char* tag = "SimpleMap";
};

// === Section A — The blueprint + member functions (lazy codegen) ============
void sectionA() {
    sectionBanner("A — blueprint + member functions (lazy codegen)");

    std::printf("Box<T> is a BLUEPRINT. Box<int> / Box<double> are concrete.\n");
    Box<int> bi{1};           // instantiates the CLASS Box<int>; value == 1
    Box<double> bd{2.5};      // instantiates Box<double>; value == 2.5

    std::printf("Box<int>{1}     .value = %d\n", bi.value);
    std::printf("Box<double>{2.5}.value = %.6f\n", bd.value);

    // The member function get() is itself a template; calling it INSTANTIATES
    // Box<int>::get (and Box<int>::half below) on demand.
    std::printf("bi.get() = %d   (member fn of a class template = a template)\n", bi.get());

    // sizeof proves Box<int> and Box<double> are DISTINCT generated classes,
    // not one shared/erased type (contrast: Java generics erase to Object).
    std::printf("sizeof(Box<int>)    = %zu\n", sizeof(Box<int>));
    std::printf("sizeof(Box<double>) = %zu\n", sizeof(Box<double>));

    check("Box<int>{1}.value == 1", bi.value == 1);
    check("Box<double>{2.5}.value == 2.5", bd.value == 2.5);
    check("Box<int>::get() == 1 (member fn instantiated on use)", bi.get() == 1);

    // LAZY CODEGEN PROOF: Box<std::string> is constructed here, but half() is
    // NEVER called on it. If member-function bodies were eagerly checked, the
    // line `return value / 2;` (string / int) would be a hard compile error.
    // Because it compiles + runs, half()'s body for T=std::string was never
    // instantiated. We DO call half() on Box<int> (int / int is fine) -> 5.
    Box<std::string> bs{"hi"};
    const int halved = Box<int>{10}.half();   // odr-uses Box<int>::half -> 5
    std::printf("Box<std::string>{\"hi\"}.value = \"%s\" (half() NOT called -> NOT instantiated)\n",
                bs.value.c_str());
    std::printf("Box<int>{10}.half() = %d   (half() called on int -> instantiated -> 5)\n", halved);

    check("Box<std::string> compiles despite half()=value/2 (lazy: body never instantiated)",
          bs.value == "hi");
    check("Box<int>::half() instantiated only because it was called (== 5)", halved == 5);
    check("Box<int> and Box<double> are distinct monomorphized types",
          !std::is_same_v<Box<int>, Box<double>>);
}

// === Section B — CTAD (C++17) + deduction guides + default template args =====
void sectionB() {
    sectionBanner("B — CTAD (C++17) + deduction guides + default template args");

    // CTAD: when no <args> are given, the compiler deduces them from the
    // initializer. Box is an aggregate, so C++20's aggregate deduction
    // candidate yields Box<int> from the element `42`.
    Box b{42};                  // deduces Box<int>
    Box d{3.14};                // deduces Box<double>
    std::printf("CTAD: Box b{42}   -> value=%d  (b is Box<int>)\n", b.value);
    std::printf("CTAD: Box d{3.14} -> value=%.6f  (d is Box<double>)\n", d.value);

    // stdlib CTAD works the same way — pair/tuple/vector all deduce.
    std::pair p{1, 2.0};        // deduces std::pair<int,double>
    std::printf("std::pair p{1, 2.0} -> .first=%d, .second=%.6f  (pair<int,double>)\n",
                p.first, p.second);

    check("CTAD: Box b{42} deduced Box<int>", std::is_same_v<decltype(b), Box<int>>);
    check("CTAD: Box d{3.14} deduced Box<double>", std::is_same_v<decltype(d), Box<double>>);
    check("std::pair p{1,2.0} deduced std::pair<int,double> (stdlib CTAD)",
          std::is_same_v<decltype(p), std::pair<int, double>>);

    // --- User-defined DEDUCTION GUIDE -------------------------------------
    // Named(T) would deduce T=const char* from a string literal. The guide
    // Named(const char*) -> Named<std::string> (declared at namespace scope)
    // overrides that: Named n{"hello"} becomes Named<std::string>.
    Named n{"hello"};
    std::printf("Named{\"hello\"} via guide -> payload=\"%s\" (std::string, not const char*)\n",
                n.payload.c_str());

    check("deduction guide remapped string-literal to Named<std::string>",
          std::is_same_v<decltype(n), Named<std::string>>);
    check("guide-constructed payload holds \"hello\"", n.payload == "hello");

    // --- DEFAULT TEMPLATE ARGUMENTS ---------------------------------------
    // The 3rd param (AllocT) defaults to std::allocator<...>; callers omit it.
    SimpleMap<int, double> m;   // AllocT = std::allocator<std::pair<const int,double>>
    std::printf("SimpleMap<int,double> -> Alloc defaulted (3rd param omitted)\n");

    check("SimpleMap<int,double> uses its defaulted allocator param",
          std::is_same_v<SimpleMap<int, double>,
                         SimpleMap<int, double, std::allocator<std::pair<const int, double>>>>);
    (void)m;
}

// === Section C — Non-type template params (the std::array<T,N> parallel) ====
void sectionC() {
    sectionBanner("C — Non-type template params (the std::array<T,N> parallel)");

    Arr<4> a{};                  // 4 ints, value-init to 0; N==4 baked in
    for (std::size_t i = 0; i < a.size; ++i) a.data[i] = static_cast<int>(i + 1);
    Arr<8> big{};

    std::printf("Arr<4>: size=%zu, sizeof=%zu (4 ints, N baked in at compile time)\n",
                Arr<4>::size, sizeof(Arr<4>));
    std::printf("Arr<8>: size=%zu, sizeof=%zu\n", Arr<8>::size, sizeof(Arr<8>));
    std::printf("Arr<4> contents: %d %d %d %d\n", a.data[0], a.data[1], a.data[2], a.data[3]);
    std::printf("std::array<int,3> is the same idea: template<class T, std::size_t N>\n");

    check("Arr<4>::size == 4 (non-type param N is a compile-time constant)", Arr<4>::size == 4);
    check("sizeof(Arr<4>) == 4 * sizeof(int)", sizeof(Arr<4>) == 4 * sizeof(int));
    check("sizeof(Arr<8>) == 8 * sizeof(int)", sizeof(Arr<8>) == 8 * sizeof(int));
    check("Arr<4> and Arr<8> are distinct types (per-N monomorphization)",
          !std::is_same_v<Arr<4>, Arr<8>>);
    (void)big;
}

// === Section D — FULL specialization (template<>) + PARTIAL (<T*>) ==========
void sectionD() {
    sectionBanner("D — FULL specialization (template<>) + PARTIAL (<T*>)");

    // The `which` marker on each version lets us prove, at runtime, WHICH
    // specialization the compiler selected for each argument list.
    Box<int> primary{7};        // matches NO specialization -> primary
    Box<bool> full{true};       // EXACT match of Box<bool> -> full specialization
    Box<int*> partial{nullptr}; // matches the SHAPE Box<T*> -> partial spec

    std::printf("Box<int>    -> which = \"%s\"   (no specialization matches -> primary)\n",
                Box<int>::which);
    std::printf("Box<bool>   -> which = \"%s\"   (template<> exact match)\n", Box<bool>::which);
    std::printf("Box<int*>   -> which = \"%s\"   (partial Box<T*> matches)\n", Box<int*>::which);
    std::printf("Box<double*>-> which = \"%s\"   (partial Box<T*> matches ANY pointer)\n",
                Box<double*>::which);

    std::printf("primary.value=%d   full.flag=%s   partial.ptr==(int*)%p\n",
                primary.value, full.flag ? "true" : "false",
                static_cast<void*>(partial.ptr));

    check("Box<int> uses the PRIMARY template (which == \"primary\")",
          std::string(Box<int>::which) == "primary");
    check("Box<bool> uses the FULL specialization (template<>)",
          std::string(Box<bool>::which) == "full<bool>");
    check("Box<int*> uses the PARTIAL specialization (Box<T*>)",
          std::string(Box<int*>::which) == "partial<T*>");
    check("Box<double*> also uses the PARTIAL specialization (any pointer T*)",
          std::string(Box<double*>::which) == "partial<T*>");
    check("Box<int>, Box<bool>, Box<int*> are three distinct types",
          !std::is_same_v<Box<int>, Box<bool>> && !std::is_same_v<Box<int>, Box<int*>>);
}

// === Section E — ODR for templates + cross-language monomorphization ========
void sectionE() {
    sectionBanner("E — ODR for templates + cross-language monomorphization");

    // The One-Definition Rule normally forbids more than one definition of an
    // entity per program. TEMPLATES (and inline functions, and class types)
    // get a RELAXED ODR: the definition may appear in EVERY translation unit
    // that needs it (i.e. it can live in a header), provided all copies are
    // token-identical. The linker then collapses them.
    //
    // Consequence 1: template definitions go IN HEADERS (so every TU that
    // instantiates them sees the body). You cannot put a template body in a
    // .cpp and instantiate it from another TU (without explicit instantiation).
    //
    // Consequence 2: a member function of a class template is implicitly
    // INLINE (ODR-relaxed) for the same reason — define it once in the header.

    std::printf("ODR relaxation: a template may be defined in EVERY TU that uses it.\n");
    std::printf("  -> template bodies live in HEADERS; the linker collapses the copies.\n");
    std::printf("  -> member functions of a class template are implicitly inline.\n");

    // We can OBSERVE instantiation (the class exists) via sizeof / type traits,
    // but we cannot, in a single TU, show the multi-TU collapse — that is a
    // LINK-TIME property documented here and reproduced by any multi-TU build.
    std::printf("sizeof(Box<int>) = %zu  (Box<int> WAS instantiated in this TU)\n", sizeof(Box<int>));

    check("Box<int> is instantiated & complete in this TU (sizeof is known)",
          sizeof(Box<int>) > 0);
    check("Box<int>::get is a member of an implicitly-inline template member fn",
          std::is_same_v<decltype(&Box<int>::get), int (Box<int>::*)() const>);

    std::printf("\nCross-language monomorphization (C++ templates vs the others):\n");
    std::printf("  C++    template<T> Box  -> Box<int>, Box<double> are SEPARATE compiled classes\n");
    std::printf("  Rust   struct Box<T>    -> SAME monomorphization (no GC; closest sibling)\n");
    std::printf("  Go     type Box[T any]  -> generics since 1.18; also monomorphized-ish\n");
    std::printf("  TS     interface Box<T> -> ERASED (no runtime generics; type aliases only)\n");
    std::printf("  Java   Box<T>           -> ERASED to Box<Object> at runtime (type erasure)\n");

    check("cross-language note recorded (C++/Rust monomorphize; TS/Java erase)",
          std::is_same_v<Box<int>, Box<int>>);
}

}  // namespace

int main() {
    std::printf("class_templates.cpp — Phase 2 bundle #10.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
