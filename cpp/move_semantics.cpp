// move_semantics.cpp — Phase 3 bundle (Memory, Ownership & Move — the heart).
//
// GOAL (one line): show, by printing every value, how C++11 MOVE SEMANTICS works —
// the value categories (lvalue/prvalue/xvalue) and the rvalue reference T&&,
// std::move (which IS A CAST, not a move), the move constructor that STEALS a
// resource in O(1) and leaves the source VALID-BUT-UNSPECIFIED, RVO/NRVO
// (return-by-value is FREE — zero copies/moves), the noexcept-move rule that
// lets vector reallocate with moves instead of copies, perfect forwarding, and
// the perf payoff — pinning std::move as C++'s opt-in ownership-transfer
// half-step toward Rust's compile-time-enforced move.
//
// This is the GROUND TRUTH for MOVE_SEMANTICS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-compile ->
// re-paste. Never hand-compute.
//
// DETERMINISM: no rand, no clock, no threads, no UB. A moved-FROM object is NEVER
// read for its value (valid-but-unspecified); only its STATE is queried (queries
// without preconditions like .size()/.empty(), or a fresh assignment is applied
// and the fresh value is asserted).
//
// Run:
//     just run move_semantics   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                 move_semantics.cpp -o /tmp/cpp_move_semantics
//                                 && /tmp/cpp_move_semantics)

#include <cstdio>          // printf / fprintf
#include <cstdlib>         // EXIT_FAILURE / exit
#include <cstring>         // memset (banner bar)
#include <string>          // std::string (a resource-owning type: move vs copy)
#include <type_traits>     // is_lvalue_reference / is_nothrow_move_constructible
#include <utility>         // std::move, std::forward
#include <vector>          // vector<string>, vector realloc (noexcept move rule)

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

// === Value-category traits (the decltype((expr)) trick) =======================
//
// decltype((expr))  [NOTE the DOUBLE parentheses] yields:
//   T    if expr is a prvalue  (a temporary: 42, make(), x+1)
//   T&   if expr is an lvalue   (named/addressable: x, *p, arr[i])
//   T&&  if expr is an xvalue   (expiring: std::move(x), static_cast<T&&>(x))
// These three specializations turn that into a clean category test.
template <class T> struct is_prvalue : std::true_type {};   // T  (base)
template <class T> struct is_prvalue<T&> : std::false_type {};
template <class T> struct is_prvalue<T&&> : std::false_type {};

template <class T> struct is_lvalue : std::false_type {};
template <class T> struct is_lvalue<T&> : std::true_type {};   // T&
template <class T> struct is_lvalue<T&&> : std::false_type {};

template <class T> struct is_xvalue : std::false_type {};
template <class T> struct is_xvalue<T&> : std::false_type {};
template <class T> struct is_xvalue<T&&> : std::true_type {};   // T&&

template <class T>
const char* valueCategory() {
    if constexpr (is_prvalue<T>::value) return "prvalue";
    else if constexpr (is_lvalue<T>::value) return "lvalue ";
    else return "xvalue ";
}

// === Tracked — a value type whose constructions/destructions we COUNT ==========
// Separate copy_ctor / move_ctor counters so we can PROVE whether a given
// operation copied (expensive) or moved (cheap). The move ctor sets the source's
// value to a sentinel — but the verified path NEVER reads a moved-from Tracked's
// value (valid-but-unspecified); we only prove the object is still a valid Tracked
// (it can be destroyed or reassigned cleanly).
struct Tracked {
    int value;
    static inline int live = 0;
    static inline int value_ctor = 0;
    static inline int copy_ctor = 0;
    static inline int move_ctor = 0;
    static inline int dtor_calls = 0;

    explicit Tracked(int v) : value(v) { ++live; ++value_ctor; }
    Tracked(const Tracked& o) : value(o.value) { ++live; ++copy_ctor; }
    Tracked(Tracked&& o) noexcept : value(o.value) {
        ++live; ++move_ctor;
        o.value = -1;   // our choice; the verified path never reads it.
    }
    ~Tracked() { --live; ++dtor_calls; }
    Tracked& operator=(const Tracked& o) {
        if (this != &o) value = o.value;
        return *this;
    }
    Tracked& operator=(Tracked&& o) noexcept {
        if (this != &o) { value = o.value; o.value = -1; }
        return *this;
    }
};

// === Section A — Value categories: lvalue / prvalue / xvalue + T&& ============
void sectionA() {
    sectionBanner("A — Value categories: lvalue / prvalue / xvalue + rvalue ref T&&");

    // The three expressions every C++ expert must classify on sight:
    int x = 5;                          // x: a named variable -> lvalue
    int& lref = x;                      // lref: a named lvalue reference -> lvalue
    int&& rref = std::move(x);          // rref: a named rvalue reference -> STILL an lvalue!
    // (A named rvalue reference is an lvalue — the #1 value-category gotcha. Only
    // the expression std::move(x) itself is an xvalue; once you NAME it (rref),
    // using that name is an lvalue expression. This is why a move ctor must
    // std::move its members: inside the ctor, `other` is a named rvalue ref, hence
    // an LVALUE, so member-wise copy would copy unless you re-cast with std::move.)

    // Compile-time proof via decltype((expr)) + the category traits:
    static_assert(is_prvalue<decltype((42))>::value, "42 is a prvalue");
    static_assert(is_lvalue<decltype((x))>::value, "a named variable is an lvalue");
    static_assert(is_lvalue<decltype((lref))>::value, "a named lvalue reference is an lvalue");
    static_assert(is_lvalue<decltype((rref))>::value, "a NAMED rvalue reference is an LVALUE");
    static_assert(is_xvalue<decltype((std::move(x)))>::value, "std::move(x) is an xvalue");
    static_assert(is_prvalue<decltype((x + 1))>::value, "x+1 (arithmetic) is a prvalue");

    std::printf("expression              decltype((expr))   category\n");
    std::printf("-----------------------  ----------------   --------\n");
    std::printf("42                        int               %s\n", valueCategory<decltype((42))>());
    std::printf("x                         int&              %s\n", valueCategory<decltype((x))>());
    std::printf("lref  (int& lref = x)     int&              %s\n", valueCategory<decltype((lref))>());
    std::printf("rref  (int&& rref = ...)  int&              %s\n", valueCategory<decltype((rref))>());
    std::printf("std::move(x)              int&&             %s\n", valueCategory<decltype((std::move(x)))>());
    std::printf("x + 1                     int               %s\n", valueCategory<decltype((x + 1))>());

    check("42 is a prvalue (a temporary literal)", is_prvalue<decltype((42))>::value);
    check("x (a named variable) is an lvalue", is_lvalue<decltype((x))>::value);
    check("a NAMED rvalue reference is an LVALUE (the #1 gotcha)",
          is_lvalue<decltype((rref))>::value);
    check("std::move(x) is an xvalue (an expiring value)",
          is_xvalue<decltype((std::move(x)))>::value);
    check("x + 1 (arithmetic) is a prvalue", is_prvalue<decltype((x + 1))>::value);

    // --- rvalue reference T&& binds to rvalues (prvalues AND xvalues) ---------
    // It does NOT bind to lvalues (that needs T& or const T&).
    int&& binds_prvalue = 10;               // OK: prvalue binds to int&&
    int&& binds_xvalue = std::move(x);      // OK: xvalue binds to int&&
    const int& binds_anything = 10;         // OK: const T& binds to rvalues too
    // int&& bad = x;   // <-- ERROR: lvalue does NOT bind to T&& (commented: would not compile)

    std::printf("\nrvalue reference T&& binding rules:\n");
    std::printf("    int&& r = 10;             // OK: prvalue binds to T&&\n");
    std::printf("    int&& r = std::move(x);   // OK: xvalue binds to T&&\n");
    std::printf("    const int& r = 10;        // OK: const T& also binds to rvalues\n");
    std::printf("    // int&& r = x;           // ERROR: lvalue does NOT bind to T&&\n");

    check("int&& binds to a prvalue (10)", binds_prvalue == 10);
    check("int&& binds to an xvalue (std::move(x) refers to x)", &binds_xvalue == &x);
    check("const int& binds to an rvalue (lifetime-extended)", binds_anything == 10);

    // --- Overload resolution: rvalue -> T&& overload; lvalue -> const T& -------
    // This is HOW std::move selects the move ctor: it casts to T&& (an xvalue), so
    // overload resolution picks the T&& overload (move ctor) over the const T&
    // overload (copy ctor). Proven in Section B by counting copy_ctor vs move_ctor.
    std::printf("\n=> When both T&& and const T& overloads exist, an rvalue selects T&&.\n");
    std::printf("   This is how std::move ENABLES the move: it casts to T&& so the move\n");
    std::printf("   ctor/assign is selected. std::move itself does NOT move anything.\n");
}

// === Section B — std::move IS A CAST + move ctor STEALS + moved-FROM valid =====
void sectionB() {
    sectionBanner("B — std::move IS A CAST (not a move) + move ctor steals O(1)");

    // (1) std::move does NOT move. It is EXACTLY static_cast<T&&>(x) — a cast to
    //     an rvalue reference. The object is UNCHANGED immediately after std::move.
    //     The MOVE happens later, at the assignment/initialization that CONSUMES
    //     the cast (selecting the move ctor).
    int n = 42;
    int&& alias = std::move(n);   // alias is another name for n (same object)
    std::printf("(1) std::move is a CAST — the object is unchanged immediately after:\n");
    std::printf("    int n = 42;  int&& alias = std::move(n);\n");
    std::printf("    &alias == &n      = %s   (same object — std::move created no copy)\n",
                &alias == &n ? "true" : "false");
    std::printf("    n (unchanged)     = %d   (std::move did NOT move anything)\n", n);
    check("std::move is a cast: alias refers to the SAME object as n", &alias == &n);
    check("std::move did NOT change n (it's just a cast): n == 42", n == 42);
    check("std::move is noexcept (a cast cannot throw)", noexcept(std::move(n)));

    // (2) The MOVE happens at the `=` that consumes the cast. Here the move ctor
    //     runs (auto u = std::move(t) selects Tracked(Tracked&&)). Prove it by
    //     counting: a move bumps move_ctor, NOT copy_ctor.
    std::printf("\n(2) The MOVE happens at the assignment (auto u = std::move(t)):\n");
    const int cc0 = Tracked::copy_ctor;
    {
        Tracked t(100);
        const int mc1 = Tracked::move_ctor;
        auto u = std::move(t);   // <-- the MOVE ctor runs HERE (not at std::move)
        std::printf("    Tracked t(100);  auto u = std::move(t);\n");
        std::printf("    move_ctor delta = %d, copy_ctor delta = %d\n",
                    Tracked::move_ctor - mc1, Tracked::copy_ctor - cc0);
        std::printf("    u.value = %d   (destination owns the value)\n", u.value);
        check("the move ctor ran exactly once (auto u = std::move(t))",
              Tracked::move_ctor - mc1 == 1);
        check("the move ctor was selected, NOT the copy ctor (copy delta == 0)",
              Tracked::copy_ctor - cc0 == 0);
        check("the destination received the value (u.value == 100)", u.value == 100);
        // t is now moved-from (value == -1 per our choice, but we DON'T read it).
        // We prove t is still a VALID Tracked by assigning a fresh value:
        t = Tracked(200);   // reassign the moved-from object — must work (valid state)
        check("the moved-FROM Tracked is still USABLE: reassigned to 200", t.value == 200);
        std::printf("    moved-from t reassigned to Tracked(200): t.value = %d (valid state)\n", t.value);
    }

    // (3) Copy vs move: a COPY deep-copies the resource; a MOVE STEALS it (O(1)).
    //     Proven by the copy_ctor vs move_ctor counters.
    std::printf("\n(3) Copy vs move — copy bumps copy_ctor, move bumps move_ctor:\n");
    const int cc1 = Tracked::copy_ctor, mc1 = Tracked::move_ctor;
    {
        Tracked orig(7);
        Tracked cpy = orig;               // lvalue -> COPY ctor
        Tracked mov = std::move(orig);    // xvalue -> MOVE ctor
        std::printf("    Tracked cpy = orig;            -> copy_ctor delta = %d\n",
                    Tracked::copy_ctor - cc1);
        std::printf("    Tracked mov = std::move(orig); -> move_ctor delta  = %d\n",
                    Tracked::move_ctor - mc1);
        check("copying an lvalue bumps copy_ctor (exactly 1)", Tracked::copy_ctor - cc1 == 1);
        check("moving an xvalue bumps move_ctor (exactly 1)", Tracked::move_ctor - mc1 == 1);
        check("the copy received the value (cpy.value == 7)", cpy.value == 7);
        check("the move received the value (mov.value == 7)", mov.value == 7);
        // orig is now moved-from — reassign to prove valid (don't read moved-from value):
        orig = Tracked(0);
        check("moved-from orig is still valid (reassigned cleanly)", orig.value == 0);
    }

    // (4) The MOVED-FROM state: "valid-but-unspecified" (the standard's words).
    //     You may destroy or assign-to a moved-from object, but you must NOT read
    //     its value (it could be anything). Demonstrate on std::vector<std::string>
    //     (whose moved-from state the standard leaves unspecified — libc++/libstdc++
    //     leave it empty, but that is an implementation detail, not a guarantee).
    //     We query only STATE (queries with NO preconditions: .size()/.empty())
    //     and prove the object is reusable by assigning a fresh value.
    std::printf("\n(4) Moved-FROM state: valid-but-unspecified (never read the value):\n");
    {
        std::vector<std::string> v = {"alpha", "beta", "gamma"};
        std::printf("    before move: v.size() = %zu\n", v.size());
        std::vector<std::string> w = std::move(v);   // v is now moved-from
        // v.size() is a query with NO precondition — safe to call, but the value
        // is unspecified (don't assert it). We print it to show it's queryable.
        std::printf("    after  move: v.size() = %zu  (valid query; standard doesn't pin the value)\n",
                    v.size());
        std::printf("                 w.size() = %zu  (destination received the data)\n", w.size());
        // Prove v is still a VALID vector: reassign it and assert the fresh value.
        v = std::vector<std::string>{"fresh"};
        std::printf("    v reassigned: v.size() = %zu, v[0] = \"%s\"  (valid state, reusable)\n",
                    v.size(), v[0].c_str());
        check("moved-from vector is still a VALID object (queryable: .size() ran)", true);
        check("moved-from vector is REUSABLE: reassigned and holds the fresh value",
              v.size() == 1 && v[0] == "fresh");
        check("the destination received the original data (w.size() == 3, w[0] == alpha)",
              w.size() == 3 && w[0] == "alpha");
    }
    std::printf("\n    RULE: after std::move(x), x is valid-but-unspecified. You may:\n");
    std::printf("      - destroy it (its dtor runs cleanly)\n");
    std::printf("      - assign to it (x = fresh_value)\n");
    std::printf("      - call queries with NO preconditions (.size(), .empty())\n");
    std::printf("    You must NOT read its VALUE (it could be anything). Don't: x[0], x.back()\n");
    std::printf("    (those have a precondition !empty() — UB if the moved-from object is empty).\n");
}

// === Section C — RVO/NRVO: return-by-value is FREE (zero copies/moves) ========
namespace rvo_detail {

// Prvalue return: C++17 GUARANTEED copy elision — the Tracked(v) is constructed
// DIRECTLY in the caller's storage. No copy, no move, not even a move ctor call.
Tracked make_prvalue(int v) {
    return Tracked(v);   // prvalue: constructed in place at the call site
}

// NRVO (Named Return Value Optimization): the named local `t` is constructed
// directly in the caller's storage. NRVO is OPTIONAL (unlike prvalue elision)
// but applied by clang/gcc at -O2 for this simple single-return shape.
Tracked make_named_nrvo(int v) {
    Tracked t(v);
    return t;   // NRVO: t IS the return object (same storage)
}

// A sink that takes Tracked BY VALUE (so copy/move ctor runs for the param).
void sink_by_value(Tracked /*param*/) {
    // param is constructed (copy or move) from the caller's argument, then
    // destroyed at function exit. The construction is what we count.
}

}  // namespace rvo_detail

void sectionC() {
    sectionBanner("C — RVO/NRVO: return-by-value is FREE (zero copies, zero moves)");

    using namespace rvo_detail;

    // (1) Prvalue return — GUARANTEED copy elision (C++17). The return expression
    //     Tracked(v) is a prvalue; it is constructed DIRECTLY in the caller's
    //     variable `a`. No copy, no move — the move ctor is never called.
    std::printf("(1) Prvalue return — C++17 GUARANTEED copy elision (zero copy, zero move):\n");
    std::printf("    Tracked make_prvalue(int v) { return Tracked(v); }\n");
    std::printf("    auto a = make_prvalue(11);\n");
    const int vc0 = Tracked::value_ctor, cc0 = Tracked::copy_ctor, mc0 = Tracked::move_ctor;
    auto a = make_prvalue(11);
    std::printf("    -> value_ctor delta = %d, copy_ctor delta = %d, move_ctor delta = %d\n",
                Tracked::value_ctor - vc0, Tracked::copy_ctor - cc0, Tracked::move_ctor - mc0);
    std::printf("    a.value = %d  (constructed in place — no copy, no move)\n", a.value);
    check("prvalue return: exactly ONE value_ctor (the Tracked(v) ran once)",
          Tracked::value_ctor - vc0 == 1);
    check("prvalue return: ZERO copies (guaranteed C++17 copy elision)",
          Tracked::copy_ctor - cc0 == 0);
    check("prvalue return: ZERO moves (the prvalue was constructed in place)",
          Tracked::move_ctor - mc0 == 0);

    // (2) NRVO — Named Return Value Optimization. The named local `t` is
    //     constructed directly in the caller's storage. Optional per the standard
    //     but applied by clang/gcc at -O2. When applied: zero copies, zero moves.
    std::printf("\n(2) NRVO — Named Return Value Optimization (applied at -O2):\n");
    std::printf("    Tracked make_named_nrvo(int v) { Tracked t(v); return t; }\n");
    std::printf("    auto b = make_named_nrvo(22);\n");
    const int vc1 = Tracked::value_ctor, cc1 = Tracked::copy_ctor, mc1 = Tracked::move_ctor;
    auto b = make_named_nrvo(22);
    std::printf("    -> value_ctor delta = %d, copy_ctor delta = %d, move_ctor delta = %d\n",
                Tracked::value_ctor - vc1, Tracked::copy_ctor - cc1, Tracked::move_ctor - mc1);
    std::printf("    b.value = %d  (NRVO: t was constructed directly in b)\n", b.value);
    check("NRVO return: exactly ONE value_ctor (the Tracked t(v) ran once)",
          Tracked::value_ctor - vc1 == 1);
    check("NRVO return: ZERO copies (NRVO applied)", Tracked::copy_ctor - cc1 == 0);
    check("NRVO return: ZERO moves (NRVO applied)", Tracked::move_ctor - mc1 == 0);

    // (3) Contrast: when copy elision CAN'T apply, the move ctor is the fallback.
    //     Passing a named local BY VALUE to a function: an lvalue argument selects
    //     the copy ctor; std::move(lvalue) selects the move ctor.
    std::printf("\n(3) Contrast — no elision possible (pass-by-value into a sink):\n");
    std::printf("    void sink_by_value(Tracked param);  // takes by value\n");
    const int cc2 = Tracked::copy_ctor, vc2 = Tracked::value_ctor;
    {
        Tracked src(33);
        std::printf("    Tracked src(33);\n");
        std::printf("    sink_by_value(src);            // lvalue  -> COPY ctor\n");
        sink_by_value(src);
        std::printf("      copy_ctor delta = %d\n", Tracked::copy_ctor - cc2);
        check("lvalue argument -> COPY ctor (exactly 1)", Tracked::copy_ctor - cc2 == 1);

        std::printf("    sink_by_value(std::move(src)); // xvalue  -> MOVE ctor\n");
        const int mc3 = Tracked::move_ctor;
        sink_by_value(std::move(src));
        std::printf("      move_ctor delta = %d\n", Tracked::move_ctor - mc3);
        check("xvalue argument (std::move) -> MOVE ctor (exactly 1)",
              Tracked::move_ctor - mc3 == 1);
        // src is now moved-from; its dtor runs at scope exit (valid). We never read it.
    }
    check("value_ctor count is stable across the sink calls (just Tracked src(33))",
          Tracked::value_ctor - vc2 == 1);

    std::printf("\n=> Return by value is FREE (RVO/NRVO). The compiler constructs the object\n");
    std::printf("   directly in the caller's storage — no copy, no move, not even a move ctor\n");
    std::printf("   call. You NEVER need to return a pointer or reference to avoid a copy.\n");
    std::printf("   (NRVO is optional per the standard but applied by clang/gcc at -O2.)\n");
}

// === Section D — noexcept move (vector realloc) + perfect forwarding ===========

// Two types identical except their move ctor's noexcept-ness. vector reallocation
// uses std::move_if_noexcept: it MOVES existing elements iff the move ctor is
// noexcept; otherwise it COPIES (for the strong exception guarantee). This is WHY
// move ctors should be noexcept.
struct MoveThrows {
    static inline int copies = 0;
    static inline int moves = 0;
    MoveThrows() = default;
    MoveThrows(const MoveThrows&) { ++copies; }
    MoveThrows(MoveThrows&&) { ++moves; }            // NOT noexcept
    MoveThrows& operator=(const MoveThrows&) { ++copies; return *this; }
    MoveThrows& operator=(MoveThrows&&) { ++moves; return *this; }
};

struct MoveNoThrow {
    static inline int copies = 0;
    static inline int moves = 0;
    MoveNoThrow() = default;
    MoveNoThrow(const MoveNoThrow&) { ++copies; }
    MoveNoThrow(MoveNoThrow&&) noexcept { ++moves; }  // noexcept
    MoveNoThrow& operator=(const MoveNoThrow&) { ++copies; return *this; }
    MoveNoThrow& operator=(MoveNoThrow&&) noexcept { ++moves; return *this; }
};

// A forwarding-reference template (NOT an rvalue reference — T is deduced).
// std::forward<T>(x) casts x back to its original value category: lvalue if an
// lvalue was passed, rvalue if an rvalue was passed. This is PERFECT FORWARDING.
template <class T>
void show_forwarded_category(T&&) {
    if constexpr (std::is_lvalue_reference_v<T>) {
        std::printf("    relay(T&&): T deduced as T&  (lvalue) -> forward -> lvalue  (copy path)\n");
    } else {
        std::printf("    relay(T&&): T deduced as T   (rvalue) -> forward -> rvalue  (move path)\n");
    }
}

void sectionD() {
    sectionBanner("D — noexcept move (vector realloc) + perfect forwarding");

    // Compile-time proof: is_nothrow_move_constructible
    static_assert(std::is_nothrow_move_constructible_v<MoveNoThrow>,
                  "MoveNoThrow's move ctor is noexcept");
    static_assert(!std::is_nothrow_move_constructible_v<MoveThrows>,
                  "MoveThrows's move ctor is NOT noexcept");

    // (1) vector reallocation: MOVE iff noexcept, else COPY.
    //     std::move_if_noexcept returns T&& if the move ctor is noexcept, else
    //     const T& (forcing a copy). This preserves vector's strong exception
    //     guarantee: if a move threw mid-realloc, already-moved elements would be
    //     lost; copying keeps the source intact until success.
    std::printf("(1) vector reallocation: MOVE iff move ctor is noexcept, else COPY:\n");
    std::printf("    MoveNoThrow: is_nothrow_move_constructible = %s\n",
                std::is_nothrow_move_constructible_v<MoveNoThrow> ? "true" : "false");
    std::printf("    MoveThrows:  is_nothrow_move_constructible = %s\n",
                std::is_nothrow_move_constructible_v<MoveThrows> ? "true" : "false");

    // MoveNoThrow: reserve 2, push 3 -> 3rd push triggers realloc. Existing 2
    // elements are RELOCATED via MOVE (noexcept) + 1 new element moved in.
    {
        std::vector<MoveNoThrow> v;
        v.reserve(2);
        v.push_back(MoveNoThrow{});
        v.push_back(MoveNoThrow{});
        const int c_before = MoveNoThrow::copies;
        const int m_before = MoveNoThrow::moves;
        v.push_back(MoveNoThrow{});   // <-- triggers reallocation (capacity 2 -> more)
        const int copy_delta = MoveNoThrow::copies - c_before;
        const int move_delta = MoveNoThrow::moves - m_before;
        std::printf("\n    MoveNoThrow (noexcept move) — 3rd push_back (triggers realloc):\n");
        std::printf("      copies delta = %d  (ZERO — vector MOVED the 2 existing elements)\n", copy_delta);
        std::printf("      moves  delta = %d  (2 relocated + 1 new element moved in)\n", move_delta);
        check("noexcept move: vector reallocated via MOVE (copies delta == 0)", copy_delta == 0);
        check("noexcept move: vector used moves for relocation (moves delta >= 2)",
              move_delta >= 2);
    }

    // MoveThrows: same scenario, but the move ctor may throw -> vector COPIES.
    {
        std::vector<MoveThrows> v;
        v.reserve(2);
        v.push_back(MoveThrows{});
        v.push_back(MoveThrows{});
        const int c_before = MoveThrows::copies;
        const int m_before = MoveThrows::moves;
        v.push_back(MoveThrows{});   // <-- triggers reallocation
        const int copy_delta = MoveThrows::copies - c_before;
        const int move_delta = MoveThrows::moves - m_before;
        std::printf("\n    MoveThrows (throwing move) — 3rd push_back (triggers realloc):\n");
        std::printf("      copies delta = %d  (vector COPIED the 2 existing elements)\n", copy_delta);
        std::printf("      moves  delta = %d  (only the 1 new element was moved in)\n", move_delta);
        check("throwing move: vector reallocated via COPY (copies delta == 2)", copy_delta == 2);
        check("throwing move: only the new element was moved (moves delta == 1)", move_delta == 1);
    }
    std::printf("\n    => Mark your move ctor/assign `noexcept` — or vector will COPY on realloc.\n");
    std::printf("       (This is the #1 perf surprise: a missing noexcept can turn O(N) moves\n");
    std::printf("        into O(N) deep copies.)\n");

    // (2) Perfect forwarding (preview): T&& in a template is a FORWARDING reference.
    //     std::forward<T>(x) preserves the caller's value category. Used by
    //     std::make_unique, std::emplace_back, std::function, etc.
    std::printf("\n(2) Perfect forwarding (preview): T&& in a template + std::forward:\n");
    int val = 5;
    std::printf("    int val = 5;\n");
    std::printf("    relay(val);              // lvalue  -> T = int&  -> forward -> lvalue\n");
    show_forwarded_category(val);
    std::printf("    relay(std::move(val));   // xvalue  -> T = int   -> forward -> rvalue\n");
    show_forwarded_category(std::move(val));
    std::printf("    relay(42);               // prvalue -> T = int   -> forward -> rvalue\n");
    show_forwarded_category(42);
    check("std::move(val) is an xvalue (forwarded as rvalue by std::forward)",
          is_xvalue<decltype((std::move(val)))>::value);
    // val was NOT consumed by show_forwarded_category (it only inspects T) — val unchanged.
    check("val was NOT moved (relay only inspected the category): val == 5", val == 5);
}

// === Section E — Perf payoff (move vector<string>) + cross-language ===========
void sectionE() {
    sectionBanner("E — Perf payoff: move vector<string> is O(1), copy is O(N*size)");

    // Build a vector of N big strings. Total chars = N * SIZE.
    constexpr int N = 100;
    constexpr int SIZE = 1000;
    std::vector<std::string> original(N, std::string(SIZE, 'x'));
    const std::string* const orig_first_addr = &original[0];
    const char* const orig_first_data = original[0].data();
    std::printf("std::vector<std::string> of N=%d strings, each %d chars (= %d total chars):\n",
                N, SIZE, N * SIZE);

    // (1) COPY: each string is deep-copied. O(N * SIZE) char copies.
    //     The destination has its OWN buffer at a DIFFERENT address.
    std::vector<std::string> copied = original;   // copy: O(N * SIZE)
    std::printf("\n(1) COPY (vector<string> = original):\n");
    std::printf("    copied[0].data() == original[0].data() = %s   (DIFFERENT buffers — deep copy)\n",
                copied[0].data() == orig_first_data ? "true" : "false");
    check("copy deep-copied the strings (different data() address)",
          copied[0].data() != orig_first_data);
    check("copy left the source intact (original.size() still == N)", original.size() == N);
    check("copy duplicated all N strings (copied.size() == N)", copied.size() == N);

    // (2) MOVE: the vector's internal buffer POINTER is stolen. O(1) — regardless
    //     of N or string size. Zero char copies. The destination's strings are at
    //     the EXACT SAME addresses as the source's were.
    std::printf("\n(2) MOVE (vector<string> = std::move(original)):\n");
    std::printf("    sizeof(vector<string>) = %zu bytes (3 pointers: begin/end/cap)\n",
                sizeof(std::vector<std::string>));
    std::vector<std::string> moved = std::move(original);   // move: O(1) pointer steal
    std::printf("    moved[0].data() == original's original data() = %s   (SAME buffer — stolen)\n",
                moved[0].data() == orig_first_data ? "true" : "false");
    std::printf("    &moved[0] == original's original &          = %s   (same storage — stolen)\n",
                &moved[0] == orig_first_addr ? "true" : "false");
    check("move stole the SAME buffer (data() address unchanged — zero char copies)",
          moved[0].data() == orig_first_data);
    check("move stole the vector storage (same first-string address)",
          &moved[0] == orig_first_addr);
    check("move preserved all N strings (moved.size() == N)", moved.size() == N);
    // original is now moved-from (valid-but-unspecified). Query .size() (no
    // precondition) to show it's valid, but DON'T assert the value (unspecified).
    std::printf("    original.size() after move = %zu  (valid query; value unspecified — don't assert)\n",
                original.size());
    check("moved-from original is a valid object (.size() ran without precondition breach)", true);
    // Prove it's reusable: reassign.
    original = std::vector<std::string>{"reborn"};
    check("moved-from original is reusable (reassigned cleanly)", original.size() == 1);

    std::printf("\n    => Copying vector<string> of %d strings x %d chars = %d char copies.\n",
                N, SIZE, N * SIZE);
    std::printf("       Moving  vector<string> of %d strings x %d chars = %d char copies (O(1) steal).\n",
                N, SIZE, 0);

    // (3) Cross-language headline: Rust vs C++ move semantics.
    std::printf("\n(3) Cross-language headline (Rust vs C++ move):\n");
    std::printf("    C++ move  = RUNTIME ownership transfer. Moved-from = valid-but-unspecified.\n");
    std::printf("                You CAN keep using the moved-from object (dangerously).\n");
    std::printf("    Rust move = COMPILE-TIME ownership transfer. Moved-from = INVALID.\n");
    std::printf("                The compiler REJECTS any use of the moved-from binding.\n");
    std::printf("    Same idea (cheap ownership transfer); C++ trusts you, Rust enforces.\n");
}

}  // namespace

int main() {
    std::printf("move_semantics.cpp — Phase 3 bundle (Memory, Ownership & Move — the heart).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
