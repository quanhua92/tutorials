// unique_ptr.cpp — Phase 3 bundle.
//
// GOAL (one line): show, by printing every value, how std::unique_ptr<T> is THE
// default smart pointer — EXCLUSIVE ownership (one owner), MOVE-ONLY (copying is
// a compile error; ownership transfers only via std::move), and RAII (its dtor
// calls delete, so no leak, no double-delete, no manual new/delete) — pinning
// make_unique (the exception-safe factory), .get/.reset/.release, custom
// deleters, polymorphic containers (vector<unique_ptr<Base>>), and the zero-
// overhead-vs-raw-pointer invariant.
//
// This is the GROUND TRUTH for UNIQUE_PTR.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-compile ->
// re-paste. Never hand-compute.
//
// Run:
//     just run unique_ptr   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                             unique_ptr.cpp -o /tmp/cpp_unique_ptr
//                             && /tmp/cpp_unique_ptr)

#include <cstdio>          // printf / fprintf
#include <cstdlib>         // EXIT_FAILURE / exit
#include <cstring>         // memset (banner bar)
#include <memory>          // unique_ptr, make_unique, shared_ptr
#include <type_traits>     // is_copy_constructible / is_move_constructible
#include <utility>         // std::move
#include <vector>          // vector<unique_ptr<T>>

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

// Tracked — a value type whose construction/destruction we can COUNT, so we can
// PROVE (not just assert) that a unique_ptr's dtor runs exactly when scope ends.
// Tracked itself has NO manual new/delete in user code — that is the whole
// point: the unique_ptr owns the delete.
struct Tracked {
    int value;
    static inline int live = 0;        // objects currently alive
    static inline int ctor_calls = 0;  // total constructor invocations
    static inline int dtor_calls = 0;  // total destructor invocations
    explicit Tracked(int v) : value(v) { ++live; ++ctor_calls; }
    ~Tracked() { --live; ++dtor_calls; }
    Tracked(const Tracked&) = delete;
    Tracked& operator=(const Tracked&) = delete;
};

// A function-pointer deleter (Section C): a real C-API release hook signature.
// Stored AS a member inside the unique_ptr, so it costs one pointer (unlike a
// stateless function-object deleter, which is free via EBO).
void fp_deleter(Tracked* t) { delete t; }

// Polymorphism types (Section D). Animal has a VIRTUAL destructor — required to
// delete a Derived through a Base* without UB (the #1 unique_ptr gotcha).
struct Animal {
    virtual ~Animal() = default;
    virtual int legs() const = 0;
};
struct Spider : Animal { int legs() const override { return 8; } };
struct Insect : Animal { int legs() const override { return 6; } };

// === Section A — make_unique + exclusive ownership + dtor-deletes (RAII) =======
void sectionA() {
    sectionBanner("A — make_unique + exclusive ownership + RAII dtor");

    const int ctor_before = Tracked::ctor_calls;
    const int dtor_before = Tracked::dtor_calls;
    const int live_before = Tracked::live;

    {
        // std::make_unique<T>(args...) is the safe factory: no raw `new`, and
        // exception-safe (see Section E). It returns a unique_ptr<T> that OWNS
        // the new object — exactly ONE owner (exclusive ownership).
        std::unique_ptr<Tracked> p = std::make_unique<Tracked>(42);

        std::printf("make_unique<Tracked>(42) created ONE owner:\n");
        std::printf("    p->value           = %d   (*p dereferences the owned object)\n", p->value);
        std::printf("    (*p).value         = %d   (equivalent dot form)\n", (*p).value);
        std::printf("    p.get() == nullptr = %s   (.get() borrows the raw ptr; no transfer)\n",
                    p.get() == nullptr ? "true" : "false");
        std::printf("    bool(p)            = %s   (operator bool: owns an object)\n",
                    p ? "true" : "false");
        std::printf("    sizeof(p)          = %zu bytes (= sizeof(T*); zero overhead)\n", sizeof(p));

        check("make_unique produced a non-null owner", p.get() != nullptr);
        check("operator bool is true for a non-empty unique_ptr", static_cast<bool>(p));
        check("*p / p-> access the owned object (value == 42)", p->value == 42 && (*p).value == 42);
        check("Tracked ctor ran exactly once for this make_unique",
              Tracked::ctor_calls - ctor_before == 1);
        check("Tracked dtor has NOT run yet (owner still alive in scope)",
              Tracked::dtor_calls - dtor_before == 0);
        check("exactly one Tracked is now live (exclusive ownership: ONE owner)",
              Tracked::live - live_before == 1);
    }  // <- p's dtor runs HERE: it calls delete on the owned Tracked (RAII).

    std::printf("\nAfter the inner scope closed (p destroyed):\n");
    std::printf("    Tracked dtor ran exactly once at scope exit (RAII)\n");
    std::printf("    Tracked::ctor_calls delta = %d\n", Tracked::ctor_calls - ctor_before);
    std::printf("    Tracked::dtor_calls delta = %d\n", Tracked::dtor_calls - dtor_before);
    std::printf("    Tracked::live delta       = %d   (back to where we started)\n",
                Tracked::live - live_before);

    check("RAII: dtor ran exactly once when the unique_ptr left scope",
          Tracked::dtor_calls - dtor_before == 1);
    check("RAII: no net live objects left (no leak)", Tracked::live == live_before);
    check("ctor and dtor call counts balance (1 each, no double-delete)",
          Tracked::ctor_calls - ctor_before == 1 && Tracked::dtor_calls - dtor_before == 1);
}

// === Section B — MOVE-ONLY: copy deleted; std::move transfers; source null ====
void sectionB() {
    sectionBanner("B — MOVE-ONLY (copy is a compile error; move transfers)");

    // (1) Compile-time fact: the copy ctor/assign are DELETED, so copying a
    //     unique_ptr is a COMPILE ERROR. We assert this via type_traits — the
    //     line `std::unique_ptr<T> q = p;` would not build.
    constexpr bool copy_ok = std::is_copy_constructible<std::unique_ptr<Tracked>>::value;
    constexpr bool move_ok = std::is_move_constructible<std::unique_ptr<Tracked>>::value;
    static_assert(!copy_ok, "unique_ptr MUST be non-copyable (copy ctor is deleted)");
    static_assert(move_ok, "unique_ptr MUST be move-constructible");

    std::printf("(1) Compile-time traits (the copy ban is enforced by the type system):\n");
    std::printf("    is_copy_constructible<unique_ptr<T>> = %s   (copy ctor is DELETED)\n",
                copy_ok ? "true" : "false");
    std::printf("    is_move_constructible<unique_ptr<T>> = %s   (move ctor is fine)\n",
                move_ok ? "true" : "false");
    check("unique_ptr is NOT copy-constructible (copy is a compile error)",
          !std::is_copy_constructible<std::unique_ptr<Tracked>>::value);
    check("unique_ptr IS move-constructible",
          std::is_move_constructible<std::unique_ptr<Tracked>>::value);

    // (2) std::move TRANSFERS ownership: the destination takes the object, the
    //     source becomes EMPTY (.get() == nullptr). No copy, no ctor/dtor.
    std::printf("\n(2) std::move TRANSFERS ownership (source becomes empty):\n");
    auto src = std::make_unique<Tracked>(100);
    Tracked* const raw_before = src.get();   // capture the address to compare after the move
    const int ctor_before = Tracked::ctor_calls;
    const int dtor_before = Tracked::dtor_calls;

    auto dst = std::move(src);   // <-- ownership transfer; NO copy, NO dtor here

    std::printf("    before move: src.get() != nullptr = %s\n", raw_before != nullptr ? "true" : "false");
    std::printf("    after  move: src.get() == nullptr = %s   (source is now EMPTY)\n",
                src.get() == nullptr ? "true" : "false");
    std::printf("    after  move: bool(src)            = %s   (operator bool false)\n",
                src ? "true" : "false");
    std::printf("    after  move: dst->value           = %d   (destination owns it)\n", dst->value);
    std::printf("    after  move: dst.get() == raw     = %s   (SAME address; no copy made)\n",
                dst.get() == raw_before ? "true" : "false");
    std::printf("    ctor/dtor deltas across the move  = %d / %d   (ZERO — move is free)\n",
                Tracked::ctor_calls - ctor_before, Tracked::dtor_calls - dtor_before);

    check("after move, the source is empty (.get() == nullptr)", src.get() == nullptr);
    check("after move, operator bool on the source is false", !src);
    check("after move, the destination owns the object (value == 100)", dst->value == 100);
    check("move did NOT copy: destination holds the SAME address", dst.get() == raw_before);
    check("move did NOT construct or destroy the Tracked (no ctor/dtor delta)",
          Tracked::ctor_calls == ctor_before && Tracked::dtor_calls == dtor_before);
}

// === Section C — .get/.reset/.release + custom deleters =====================
void sectionC() {
    sectionBanner("C — .get/.reset/.release + custom deleters");

    // --- (1) reset(): delete the current object, then optionally reseat. -----
    auto p = std::make_unique<Tracked>(1);
    const int dtor_before_reset = Tracked::dtor_calls;
    p.reset(new Tracked(2));   // deletes the old(1), takes ownership of new(2)
    std::printf("(1) reset(new Tracked(2)):\n");
    std::printf("    p->value = %d   (old object deleted, new one owned)\n", p->value);
    std::printf("    Tracked dtor delta across reset = %d   (the old(1) was deleted)\n",
                Tracked::dtor_calls - dtor_before_reset);
    check("reset replaced the owned object (value now 2)", p->value == 2);
    check("reset deleted the previous object (dtor ran once)",
          Tracked::dtor_calls - dtor_before_reset == 1);

    p.reset();   // delete the owned object, become empty
    std::printf("    p.reset() (no arg): p.get() == nullptr = %s   (emptied, dtor ran again)\n",
                p.get() == nullptr ? "true" : "false");
    check("reset() with no argument empties the unique_ptr", p.get() == nullptr);

    // --- (2) release(): hand back the raw pointer; the unique_ptr no longer ---
    //         owns it. The CALLER now owns it and must eventually delete it.
    //         (This is the burden release() hands you — prefer reset()/scope.)
    auto q = std::make_unique<Tracked>(3);
    Tracked* const raw = q.release();   // q relinquishes ownership; raw is OURS now
    std::printf("\n(2) release():\n");
    std::printf("    q.get() == nullptr = %s   (q released ownership)\n",
                q.get() == nullptr ? "true" : "false");
    std::printf("    raw->value = %d   (caller now owns `raw`; must delete it)\n", raw->value);
    check("release emptied the unique_ptr", q.get() == nullptr);
    check("release handed back a valid raw pointer (value == 3)",
          raw != nullptr && raw->value == 3);
    // The caller is now responsible — we delete it ourselves to avoid a leak
    // (ASan/UBSan require this; a real codebase would pass it to another owner).
    const int dtor_before_manual = Tracked::dtor_calls;
    delete raw;
    std::printf("    caller deleted `raw`: Tracked dtor delta = %d   (no leak)\n",
                Tracked::dtor_calls - dtor_before_manual);
    check("the released pointer was manually deleted (no leak)",
          Tracked::dtor_calls - dtor_before_manual == 1);

    // --- (3) Custom deleter: unique_ptr<T, Deleter> runs YOUR callable, not ---
    //         `delete`. Useful for C-API handles (fclose for FILE*, free for a
    //         malloc'd buffer, SDL_FreeSurface, ...). We PROVE the custom fn ran.
    static int custom_deleter_calls = 0;   // function-local static (program lifetime)
    struct CountingDeleter {
        void operator()(Tracked* t) const {
            ++custom_deleter_calls;
            delete t;   // a real C-API deleter would call its release fn instead
        }
    };
    using CustomPtr = std::unique_ptr<Tracked, CountingDeleter>;
    using FPPtr = std::unique_ptr<Tracked, void (*)(Tracked*)>;

    std::printf("\n(3) Custom deleter (unique_ptr<T, Deleter>):\n");
    std::printf("    sizeof(unique_ptr<T, default_delete>)     = %zu bytes (== raw ptr)\n",
                sizeof(std::unique_ptr<Tracked>));
    std::printf("    sizeof(unique_ptr<T, CountingDeleter>)    = %zu bytes (stateless fn-obj: EBO -> free)\n",
                sizeof(CustomPtr));
    std::printf("    sizeof(unique_ptr<T, void(*)(T*)>)        = %zu bytes (fn-ptr deleter: +1 ptr)\n",
                sizeof(FPPtr));
    check("a stateless function-object deleter adds ZERO bytes over the raw pointer",
          sizeof(CustomPtr) == sizeof(Tracked*));
    check("a function-pointer deleter makes the unique_ptr larger than a raw pointer",
          sizeof(FPPtr) > sizeof(Tracked*));
    {
        CustomPtr cp(new Tracked(7));
        std::printf("    inside scope: cp->value = %d, custom_deleter_calls = %d\n",
                    cp->value, custom_deleter_calls);
        check("custom-deleter unique_ptr owns the object", cp->value == 7);
        check("custom deleter has NOT run yet (still in scope)", custom_deleter_calls == 0);
    }  // <- CountingDeleter::operator() runs here, not the default `delete`.
    std::printf("    after scope:  custom_deleter_calls = %d   (OUR fn ran at exit)\n",
                custom_deleter_calls);
    check("custom deleter ran exactly once at scope exit", custom_deleter_calls == 1);

    // A FUNCTION-POINTER deleter: same idea, but the deleter is stored as a
    // pointer-to-function (the natural fit for a C-API release hook like
    // fclose/free). It costs one extra pointer (no EBO for a non-empty member).
    const int dtor_before_fp = Tracked::dtor_calls;
    {
        FPPtr fp(new Tracked(9), fp_deleter);
        std::printf("    fn-ptr-deleter unique_ptr: fp->value = %d\n", fp->value);
        check("function-pointer-deleter unique_ptr owns the object", fp->value == 9);
    }  // <- fp_deleter(raw) runs here -> it `delete`s the Tracked.
    std::printf("    after scope: Tracked dtor delta via fp_deleter = %d\n",
                Tracked::dtor_calls - dtor_before_fp);
    check("the function-pointer deleter ran (dtor fired once via the hook)",
          Tracked::dtor_calls - dtor_before_fp == 1);
}

// === Section D — containers of unique_ptr + Derived->Base move ===============
void sectionD() {
    sectionBanner("D — containers of unique_ptr + Derived->Base move");

    // (1) vector<unique_ptr<T>>: move-only elements. You cannot copy a unique_ptr
    //     INTO the vector — you std::move it. The vector OWNS each element; when
    //     the vector is destroyed/cleared, every owned object is deleted (RAII
    //     propagates through the container).
    std::vector<std::unique_ptr<Tracked>> v;
    v.push_back(std::make_unique<Tracked>(10));
    v.push_back(std::make_unique<Tracked>(20));
    auto p = std::make_unique<Tracked>(30);
    Tracked* const raw_p = p.get();
    v.push_back(std::move(p));   // move into the vector; p is now empty

    std::printf("(1) vector<unique_ptr<Tracked>> (move-only elements):\n");
    std::printf("    v.size() = %zu\n", v.size());
    std::printf("    v[0]->value = %d, v[1]->value = %d, v[2]->value = %d\n",
                v[0]->value, v[1]->value, v[2]->value);
    std::printf("    source p after move into vector: p.get() == nullptr = %s\n",
                p.get() == nullptr ? "true" : "false");
    check("vector holds 3 unique_ptr elements", v.size() == 3);
    check("the moved-from source is empty after push_back(std::move(p))", p.get() == nullptr);
    check("the vector now owns the moved object (same address)", v[2].get() == raw_p);

    int sum = 0;
    for (const auto& e : v) sum += e->value;
    std::printf("    sum of all owned values = %d\n", sum);
    check("range-for over the vector reads each owned object", sum == 60);

    const int dtor_before_clear = Tracked::dtor_calls;
    v.clear();   // destroys all elements -> each unique_ptr's dtor -> delete its Tracked
    std::printf("    after v.clear(): Tracked dtor delta = %d   (all 3 freed)\n",
                Tracked::dtor_calls - dtor_before_clear);
    check("clearing the vector deleted all 3 owned objects (RAII through the container)",
          Tracked::dtor_calls - dtor_before_clear == 3);

    // (2) Polymorphism: vector<unique_ptr<Base>> holds a HETEROGENEOUS collection.
    //     Virtual dispatch works through the Base*. The Base MUST have a virtual
    //     destructor (otherwise deleting a Derived via a Base* is UB — the #1
    //     unique_ptr gotcha, see the pitfalls table).
    std::vector<std::unique_ptr<Animal>> zoo;
    zoo.push_back(std::make_unique<Spider>());
    zoo.push_back(std::make_unique<Insect>());
    std::printf("\n(2) Polymorphism (vector<unique_ptr<Base>>):\n");
    std::printf("    zoo.size() = %zu\n", zoo.size());
    int total_legs = 0;
    for (const auto& a : zoo) {
        std::printf("    animal->legs() = %d   (virtual dispatch through Base*)\n", a->legs());
        total_legs += a->legs();
    }
    std::printf("    total legs = %d\n", total_legs);
    check("zoo holds 2 polymorphic animals", zoo.size() == 2);
    check("virtual dispatch works through unique_ptr<Base> (8 + 6 == 14)", total_legs == 14);

    // (3) Explicit Derived->Base move conversion: a unique_ptr<Derived> converts
    //     to unique_ptr<Base> via move (the source empties, as with any move).
    std::unique_ptr<Spider> sp = std::make_unique<Spider>();
    std::unique_ptr<Animal> ap = std::move(sp);   // implicit Derived->Base conversion
    std::printf("\n(3) unique_ptr<Derived> -> unique_ptr<Base> move conversion:\n");
    std::printf("    source sp.get() == nullptr = %s\n", sp.get() == nullptr ? "true" : "false");
    std::printf("    target ap->legs() = %d\n", ap->legs());
    check("Derived->Base move emptied the source", sp.get() == nullptr);
    check("the Base unique_ptr now owns the Derived object (legs == 8)", ap->legs() == 8);
}

// === Section E — unique vs shared + zero overhead + cross-language ===========
void sectionE() {
    sectionBanner("E — unique vs shared + zero overhead + cross-language");

    // (1) Zero-overhead: a unique_ptr<T> with the default deleter is EXACTLY as
    //     big as a raw T* — there is no control block, no refcount. shared_ptr
    //     is bigger (it carries a pointer to a heap control block) and costs an
    //     atomic increment/decrement per copy. This is WHY we prefer unique_ptr.
    std::printf("(1) Size: unique_ptr is zero-overhead vs a raw pointer:\n");
    std::printf("    sizeof(Tracked*)                  = %zu\n", sizeof(Tracked*));
    std::printf("    sizeof(unique_ptr<Tracked>)       = %zu   (== raw ptr; default deleter)\n",
                sizeof(std::unique_ptr<Tracked>));
    std::printf("    sizeof(shared_ptr<Tracked>)       = %zu   (2 ptrs: object + control block)\n",
                sizeof(std::shared_ptr<Tracked>));
    check("default-deleter unique_ptr is the same size as a raw pointer",
          sizeof(std::unique_ptr<Tracked>) == sizeof(Tracked*));
    check("shared_ptr is strictly larger than unique_ptr (control-block pointer)",
          sizeof(std::shared_ptr<Tracked>) > sizeof(std::unique_ptr<Tracked>));

    // (2) Prefer unique by default; upgrade to shared when shared is needed.
    //     unique_ptr -> shared_ptr is a one-way implicit move (a shared_ptr can
    //     be built from a unique_ptr&&); shared_ptr -> unique_ptr does NOT exist
    //     (there may be many owners). This makes unique_ptr the safe default.
    std::printf("\n(2) Prefer unique by default (one-way upgrade to shared):\n");
    std::unique_ptr<Tracked> up = std::make_unique<Tracked>(5);
    const int ctor_before = Tracked::ctor_calls;
    std::shared_ptr<Tracked> sp = std::move(up);   // unique -> shared (implicit, one-way)
    std::printf("    unique->shared move: sp->value = %d, sp.use_count() = %ld\n",
                sp->value, sp.use_count());
    std::printf("    source up after move: up.get() == nullptr = %s\n",
                up.get() == nullptr ? "true" : "false");
    std::printf("    Tracked ctor delta across the upgrade = %d   (NO new object; same one)\n",
                Tracked::ctor_calls - ctor_before);
    check("unique_ptr moves INTO shared_ptr (ownership transferred)",
          sp->value == 5 && sp.use_count() == 1);
    check("after the upgrade the source unique_ptr is empty", up.get() == nullptr);
    check("the upgrade did NOT construct a new Tracked (same object, new owner type)",
          Tracked::ctor_calls == ctor_before);

    // (3) make_unique exception safety is DOCUMENTED (not executed here — the
    //     demo would need a throwing ctor inside a try/catch). The hazard is the
    //     unsequenced-evaluation leak in the raw-new form:
    //         f(std::unique_ptr<T>(new T), may_throw());   // CAN leak
    //     vs the safe make_unique form:
    //         f(std::make_unique<T>(), may_throw());       // safe (one bundled op)
    //     The two sub-expressions of the first call are unsequenced relative to
    //     each other: if may_throw() (or the second new) throws AFTER the first
    //     new ran, the first object leaks. make_unique bundles new+construct
    //     into a single expression, closing the interleaving gap. (Sutter, GotW
    //     #56 / N2186; see Sources.)
    std::printf("\n(3) make_unique exception-safety (documented; not executed):\n");
    std::printf("    f(unique_ptr<T>(new T), may_throw());  // CAN leak (unsequenced news)\n");
    std::printf("    f(make_unique<T>(),     may_throw());  // SAFE  (one bundled op)\n");
    std::printf("    => always prefer make_unique over `unique_ptr<T>(new T)`.\n");
    check("make_unique is the exception-safe factory (documented, not run)", true);
}

}  // namespace

int main() {
    std::printf("unique_ptr.cpp — Phase 3 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
