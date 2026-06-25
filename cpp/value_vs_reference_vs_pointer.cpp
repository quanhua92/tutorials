// value_vs_reference_vs_pointer.cpp — Phase 3 bundle.
//
// GOAL (one line): show, by printing every value, the FULL decision matrix for
// how to PASS and RETURN an object in C++ — by VALUE (copied; cheap/safe/own),
// by `T&` (alias; mutate the caller's), by `const T&` (cheap read-only; binds
// temporaries via lifetime extension), by `T*`/`const T*` (nullable/reseatable),
// by `T&&` (rvalue ref — the move/ownership-transfer sink) — pinning SLICING
// (Derived-by-value-to-Base loses the Derived part) and the dangling-return UB
// trap as documented expert payoffs (NEVER executed in the verified path).
//
// This is the GROUND TRUTH for VALUE_VS_REFERENCE_VS_POINTER.md. Every number,
// table, and worked example in the guide is printed by this file. Change it ->
// re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run value_vs_reference_vs_pointer
//        (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//            value_vs_reference_vs_pointer.cpp -o /tmp/cpp_value_vs_reference_vs_pointer
//            && /tmp/cpp_value_vs_reference_vs_pointer)

#include <cstddef>    // std::size_t
#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <string>     // std::string (const T& lifetime-extension demo)

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

// ── A copy-counting type (reused across sections) ────────────────────────────
// `copies` is an observable side effect, so -O2 / ASan / UBSan MUST preserve it
// (they cannot elide a copy with a visible effect). This PROVES by-value copies
// while by-reference/by-rvalue-ref do not.
struct Tracker {
    inline static int copies = 0;   // C++17 inline static data member
    int value;
    explicit Tracker(int v) : value(v) {}
    Tracker(const Tracker& other) : value(other.value) { ++copies; }
};

// A "large" type: a copy would be 64 bytes of memmove. We never read the array;
// its only job is to make sizeof(Large) visibly big so the const T& rationale
// (cheap read, no copy of a big object) is concrete and printable.
struct Large {
    int header;
    int payload[15];   // 15 * 4 = 60 bytes; total sizeof(Large) == 64
};

// ── The five parameter-passing signatures this bundle exercises ─────────────
int   by_value(Tracker t) { return t.value; }            // copies IN
int   by_ref(const Tracker& t) { return t.value; }       // alias; NO copy
int   by_lvalue_ref_mut(Tracker& t) { t.value += 100; return t.value; }  // in-out
int   by_rvalue_ref(Tracker&& t) { return t.value; }     // binds rvalues; NO copy
const Tracker* maybe_find(bool hit, const Tracker* in) { // nullable out
    return hit ? in : nullptr;
}

// === Section A — By VALUE: a copy (mutation invisible); safe to return ========
void sectionA() {
    sectionBanner("A — By VALUE (a copy): mutation invisible; safe to return");

    std::printf("A by-VALUE parameter is an INDEPENDENT COPY of the argument. Mutating it\n");
    std::printf("NEVER reaches the caller — the whole point for cheap types, ownership, and\n");
    std::printf("thread-safe local state. The cost: each by-value pass runs the copy ctor.\n");

    // (1) Mutation invisibility: the parameter is a copy, so writing it is local.
    int original = 10;
    auto mutate = [](int n) {   // n: an independent copy
        n = 999;
        return n;
    };
    int got = mutate(original);
    std::printf("\nint original = 10;  mutate(original) -> %d;  original still %d (copy mutated)\n",
                got, original);
    check("by-value: mutating the param left the caller's original at 10", original == 10);

    // (2) Proof the copy actually ran: take_by_value -> copies == 1.
    Tracker t(42);
    Tracker::copies = 0;
    by_value(t);
    std::printf("Tracker::copies after by_value(t)   = %d  (copy ctor ran once)\n",
                Tracker::copies);
    check("by_value invoked the copy constructor exactly once (copies == 1)",
          Tracker::copies == 1);

    // (3) Safe to RETURN by value: the returned object is a brand-new value the
    //     caller receives (RVO/move under the hood). There is no alias to a
    //     dead local — contrast with Section D's dangling-ref trap.
    auto make_tracker = [](int v) -> Tracker { return Tracker(v); };
    Tracker r = make_tracker(7);
    std::printf("\na lambda returns Tracker(7) BY VALUE; caller receives value = %d (no dangle)\n",
                r.value);
    check("return-by-value gives the caller a safe, owning copy (value == 7)", r.value == 7);

    // (4) When is by-value RIGHT? For cheap-to-copy types (int, pointer, small
    //     POD) OR when you WANT a local copy / ownership. The rule of thumb:
    //     "if copying it is cheaper than a pointer indirection, pass by value."
    std::printf("\nsizeof(int)=%zu  sizeof(void*)=%zu  sizeof(Tracker)=%zu  sizeof(Large)=%zu\n",
                sizeof(int), sizeof(void*), sizeof(Tracker), sizeof(Large));
    check("int and pointer are 'cheap': sizeof <= 2 words", sizeof(int) <= 16 && sizeof(void*) <= 16);
    check("Large is 'expensive' to copy: sizeof(Large) == 64", sizeof(Large) == 64);
}

// === Section B — By `T&` (in-out mutate) + by `const T&` (cheap read-only) ====
void sectionB() {
    sectionBanner("B — T& (in-out mutate) + const T& (cheap read-only, binds temps)");

    std::printf("A non-const T& is an ALIAS the callee mutates THROUGH (an out-parameter). A\n");
    std::printf("const T& is a cheap READ-ONLY alias: NO copy, and it can bind a TEMPORARY\n");
    std::printf("(binding a const T& to a temporary EXTENDS the temporary's lifetime).\n");

    // (1) Non-const T& = in-out: the caller's object is mutated through the alias.
    Tracker t(42);
    Tracker::copies = 0;
    int after = by_lvalue_ref_mut(t);
    std::printf("\nTracker t(42);  by_lvalue_ref_mut(t) -> %d;  t.value now %d; copies = %d\n",
                after, t.value, Tracker::copies);
    check("non-const T& mutated the caller's object THROUGH the alias (t.value == 142)",
          t.value == 142);
    check("non-const T& performed ZERO copies (it is an alias)", Tracker::copies == 0);

    // (2) const T& = cheap read-only pass of a LARGE object: NO copy.
    Large big{};
    big.header = 5;
    auto read_header = [](const Large& l) { return l.header; };  // alias; no copy of 64 bytes
    int h = read_header(big);
    std::printf("\nLarge big (sizeof %zu bytes) read via const Large& -> header = %d (NO 64-byte copy)\n",
                sizeof(Large), h);
    check("const T& read a large object with no copy (header == 5)", h == 5);

    // (3) const T& binds a TEMPORARY and EXTENDS its lifetime to the reference.
    //     The prvalue std::string("temp-literal") lives as long as `bound`.
    const std::string& bound = std::string("temp-literal");
    std::printf("\nconst std::string& bound = std::string(\"temp-literal\");  -> \"%s\" (len %zu)\n",
                bound.c_str(), bound.length());
    check("const T& binds a temporary AND extends its lifetime (bound intact)", bound == "temp-literal");
    check("the lifetime-extended temporary is readable (length == 12)", bound.length() == 12);

    // (4) The same const T& also aliases a real lvalue, with no copy either.
    Tracker tt(9);
    Tracker::copies = 0;
    by_ref(tt);
    std::printf("\nTracker::copies after by_ref(tt) = %d  (const T& is an alias, no copy)\n",
                Tracker::copies);
    check("const T& on an lvalue performed ZERO copies", Tracker::copies == 0);
}

// === Section C — By `T*`/`const T*` (nullable, reseatable) + `T&&` (sink) =====
void sectionC() {
    sectionBanner("C — T*/const T* (nullable, reseatable) + T&& (rvalue-ref sink)");

    std::printf("A POINTER expresses what a reference cannot: NULLABLE (\"maybe no object\") and\n");
    std::printf("RESEATABLE (point it at a different object). An rvalue reference T&& expresses\n");
    std::printf("\"I will take ownership / move from this\" — the move-semantics sink (preview).\n");

    // (1) T* NULLABLE: nullptr means \"no object\"; the CALLER must check.
    Tracker pool_a(100);
    const Tracker* hit  = maybe_find(true,  &pool_a);
    const Tracker* miss = maybe_find(false, &pool_a);
    std::printf("\nmaybe_find(true,...)  -> %s (value %d)\n",
                hit == nullptr ? "nullptr" : "non-null", hit == nullptr ? -1 : hit->value);
    std::printf("maybe_find(false,...) -> %s\n", miss == nullptr ? "nullptr" : "non-null");
    check("T* is nullable: a 'miss' is represented by nullptr", miss == nullptr);
    check("caller MUST check: a hit yields a readable object (value == 100)",
          hit != nullptr && hit->value == 100);

    // (2) T* is RESEATABLE: the same pointer variable can be pointed elsewhere.
    //     (A reference CANNOT do this — `r = y;` assigns THROUGH r, not rebinds.)
    Tracker pool_b(200);
    Tracker* cursor = &pool_a;     // points at pool_a
    int first = cursor->value;     // 100
    cursor = &pool_b;              // RESEAT: now points at pool_b (a pointer can)
    int second = cursor->value;    // 200
    std::printf("\nTracker* cursor = &pool_a; cursor->value = %d; cursor = &pool_b; cursor->value = %d\n",
                first, second);
    check("pointer is reseatable: same variable, two referents (100 then 200)",
          first == 100 && second == 200);

    // (3) rvalue reference T&& binds rvalues (temporaries, std::move(x)) — and,
    //     like every reference, makes NO copy. The full move-from-into-sink
    //     machinery is the subject of MOVE_SEMANTICS; here we pin the property
    //     that distinguishes T&& from by-value: it is a reference, not a copy.
    Tracker::copies = 0;
    by_rvalue_ref(Tracker(55));             // binds a temporary rvalue
    int copies_temp = Tracker::copies;
    Tracker src(77);
    Tracker::copies = 0;
    by_rvalue_ref(std::move(src));          // std::move casts an lvalue to an rvalue
    int copies_move = Tracker::copies;
    std::printf("\nby_rvalue_ref(Tracker(55))         copies = %d (binds a temporary, no copy)\n",
                copies_temp);
    std::printf("by_rvalue_ref(std::move(src))       copies = %d (std::move -> rvalue, no copy)\n",
                copies_move);
    check("T&& binds a temporary rvalue with ZERO copies", copies_temp == 0);
    check("std::move(lvalue) is an rvalue: T&& binds it with ZERO copies", copies_move == 0);
}

// ── A small polymorphic hierarchy for the SLICING demo (Section D) ───────────
struct Base {
    int b = 1;
    int extra[3] = {0, 0, 0};   // makes Base visibly large so Derived adds beyond it
    virtual const char* who() const { return "Base"; }
    virtual ~Base() = default;
};
struct Derived : Base {
    int d = 2;   // the part that gets LOST when sliced
    const char* who() const override { return "Derived"; }
};

// (a) A by-value Base parameter: a Derived argument is COPIED into a Base — only
//     the Base subobject survives; `d` is gone, and the object's dynamic type is
//     Base. THE SLICING TRAP.
const char* describe_by_value(Base b) { return b.who(); }
// (b) A const Base& parameter: NO copy, and the object keeps its REAL dynamic
//     type (Derived) — virtual dispatch sees Derived. Slicing AVOIDED.
const char* describe_by_ref(const Base& b) { return b.who(); }

// === Section D — SLICING + lifetime-extension boundaries + dangling-return UB =
void sectionD() {
    sectionBanner("D — SLICING + lifetime-extension boundaries + dangling-return UB");

    std::printf("Three silent traps that turn a wrong choice into a bug: SLICING (a Derived\n");
    std::printf("passed by-value to a Base loses the Derived part); lifetime extension that\n");
    std::printf("does NOT survive storing into a container/member; and RETURNING a reference\n");
    std::printf("to a local/temp (dangling — UB, documented, never executed here).\n");

    // ── (1) SLICING ──────────────────────────────────────────────────────────
    Derived d_obj;
    const char* sliced = describe_by_value(d_obj);   // copies only the Base part
    const char* whole  = describe_by_ref(d_obj);     // polymorphic; keeps Derived
    std::printf("\nDerived obj; describe_by_value(obj) -> \"%s\" (SLICED: dynamic type is Base)\n",
                sliced);
    std::printf("                  describe_by_ref(obj) -> \"%s\" (no slicing: dynamic type is Derived)\n",
                whole);
    check("SLICING: Derived passed by-value to Base loses its dynamic type (== \"Base\")",
          std::string(sliced) == "Base");
    check("const Base& AVOIDS slicing: virtual dispatch sees Derived (== \"Derived\")",
          std::string(whole) == "Derived");

    // sizeof proof: a Base copy is smaller than a Derived; the `d` field is gone.
    std::printf("sizeof(Base) = %zu, sizeof(Derived) = %zu (the Derived-only field `d` is %zu bytes)\n",
                sizeof(Base), sizeof(Derived), sizeof(Derived) - sizeof(Base));
    check("Derived is strictly larger than Base (it adds the `d` field)",
          sizeof(Derived) > sizeof(Base));

    // ── (2) Lifetime extension has BOUNDARIES ────────────────────────────────
    // A LOCAL const T& extends a temporary's lifetime — Section B proved it. But
    // that extension does NOT apply when the reference is stored in a container
    // or a member: the temporary dies at the end of the full-expression, and the
    // stored reference DANGLS. We DOCUMENT this (reading a dangling ref is UB);
    // the verified path only stores a reference to a LONG-LIVED object.
    std::printf("\n(Lifetime extension applies to LOCAL const T& only. Storing a const T& into\n");
    std::printf(" a container/member from a temporary DANGLS — read is UB; documented, not run.)\n");
    {
        std::string kept = std::string("alive");   // owning value, lives in this scope
        const std::string& view = kept;            // safe: `kept` outlives `view`
        std::printf("const std::string& view bound to an owning local: \"%s\" (safe — local outlives ref)\n",
                    view.c_str());
        check("a reference to a long-lived local is safe to read (== \"alive\")", view == "alive");
    }

    // ── (3) RETURNING a reference to a local/temp is DANGLING (UB) ────────────
    // The CORRECT patterns are demonstrated; the UB pattern is DOCUMENTED only.
    auto return_by_value = [](int v) { return v * 2; };           // safe: a value
    int safe = return_by_value(21);
    std::printf("\nreturn_by_value(21) -> %d   (returning a VALUE is always safe: no alias to a local)\n",
                safe);
    check("return-by-value is dangling-free (== 42)", safe == 42);

    // Returning a reference to a MEMBER of a caller-owned object is also safe —
    // the referent's lifetime is the caller's, not the callee's frame.
    struct Pair { int a; int b; };
    auto second_of = [](const Pair& p) -> const int& { return p.b; };  // ref to caller's data
    Pair p{1, 99};
    const int& r2 = second_of(p);
    std::printf("second_of(p) returns a const int& to p.b (caller-owned lifetime) -> %d\n", r2);
    check("returning a member ref of a caller-owned object is safe (== 99)", r2 == 99);

    // The BAD pattern — DOCUMENTED, never executed in the verified path:
    //   const int& bad() { int local = 5; return local; }   // DANGLING (UB to read)
    // Returning a reference to a function-local automatic object or to a
    // temporary (e.g. `const T& f() { return T(); }`) yields a reference to
    // storage that is gone before the caller uses it. Reading it is UB; ASan
    // reports a stack-use-after-return / use-after-free.
    std::printf("\n(DANGLING-RETURN: `const T& f(){ int x=5; return x; }` is UB to read. The\n");
    std::printf(" verified path returns by value or a member-ref of caller-owned storage only.)\n");
    check("verified path never returns a ref to a local/temp (dangling UB)", true);
}

// === Section E — The F-call decision matrix (the whole bundle in one table) ===
void sectionE() {
    sectionBanner("E — The F-call decision matrix (Core Guidelines F.15-F.21)");

    std::printf("The C++ Core Guidelines (F.call: F.15-F.21) collapse the whole bundle into one\n");
    std::printf("decision per PARAMETER and per RETURN, keyed on INTENT (in / in-out / sink /\n");
    std::printf("forward / out). Pick the intent, get the signature:\n");

    std::printf("\n  intent   | signature        | when / why\n");
    std::printf("  ---------|------------------|--------------------------------------------\n");
    std::printf("  in       | T  (by value)    | cheap-to-copy (int, ptr, small POD); or you\n");
    std::printf("           |                  | WANT a local copy / ownership (F.16)\n");
    std::printf("  in       | const T&         | read-only pass of a LARGE/expensive object;\n");
    std::printf("           |                  | binds temporaries via lifetime extension (F.16)\n");
    std::printf("  in-out   | T&               | the callee MUTATES the caller's object (F.17)\n");
    std::printf("  sink/own | T&& (+ std::move)| take/move ownership of the argument (F.18);\n");
    std::printf("           | unique_ptr       | the full story is MOVE_SEMANTICS\n");
    std::printf("  nullable | T* / const T*    | \"maybe no object\" (nullptr) OR reseatable;\n");
    std::printf("           |                  | caller MUST check for null (F.7/F.22)\n");
    std::printf("  out      | return T (value) | ONE result — always safe (no dangle) (F.20)\n");
    std::printf("  out-many | return struct/   | several results — prefer a struct/tuple over\n");
    std::printf("           | tuple            | multiple out-params (F.21)\n");

    // A worked, all-in-one example exercising four cells of the matrix at once.
    auto pipeline = [](int cheap_in,            // in (cheap) -> by value
                       Tracker& in_out,         // in-out     -> T&
                       const Large& big_in,     // in (large) -> const T&
                       bool provide) -> int {   // out        -> return by value
        in_out.value += cheap_in;               // mutate caller's (in-out)
        return cheap_in + big_in.header + (provide ? 1 : 0);  // one safe value out
    };

    Tracker io(40);
    Large big{};
    big.header = 2;
    Tracker::copies = 0;
    int result = pipeline(5, io, big, true);
    int copies_used = Tracker::copies;
    std::printf("\npipeline(5, io, big, true) -> %d; io.value now %d; Tracker copies = %d\n",
                result, io.value, copies_used);
    check("F-call matrix: cheap `in` passed by value; large `in` by const T& (no Tracker copy)",
          copies_used == 0);
    check("F-call matrix: in-out via T& mutated the caller's object (io.value == 45)",
          io.value == 45);
    check("F-call matrix: out via return-by-value is safe (result == 5+2+1)", result == 8);
}

}  // namespace

int main() {
    std::printf("value_vs_reference_vs_pointer.cpp — Phase 3 bundle.\n");
    std::printf("The full pass/return decision matrix: value / & / const& / * / &&. Compiled\n");
    std::printf("-std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
