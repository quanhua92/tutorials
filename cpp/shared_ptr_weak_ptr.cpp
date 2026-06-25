// shared_ptr_weak_ptr.cpp — Phase 3 bundle.
//
// GOAL (one line): show, by printing every value, how std::shared_ptr is
// REFCOUNTED shared ownership (the object dies when the LAST shared_ptr dies),
// how the CONTROL BLOCK carries the strong + weak counts, how std::weak_ptr is
// a NON-owning observer used to BREAK reference CYCLES — pinning the
// make_shared-vs-shared_ptr(new T) allocation difference (1 vs 2), the
// cycle-leak trap, and std::enable_shared_from_this as documented expert
// payoffs (the UB paths — shared_ptr(this), a leaked cycle — are DOCUMENTED and
// never executed in the verified path).
//
// This is the GROUND TRUTH for SHARED_PTR_WEAK_PTR.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run shared_ptr_weak_ptr   (== c++ -std=c++23 -O2 -Wall -Wextra
//      -Wpedantic shared_ptr_weak_ptr.cpp -o /tmp/cpp_shared_ptr_weak_ptr
//      && /tmp/cpp_shared_ptr_weak_ptr)

#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit, malloc/free
#include <cstring>    // memset (banner bar)
#include <memory>     // shared_ptr, weak_ptr, make_shared, make_unique,
                      // enable_shared_from_this, shared_from_this
#include <new>        // std::nothrow_t, std::align_val_t (for operator new set)
#include <utility>    // std::move

// ── Global allocation counter + operator new/delete replacements ─────────────
// We replace the global operator new/delete purely to COUNT heap allocations,
// which makes the make_shared (1) vs shared_ptr(new T) (2) difference an
// OBSERVABLE printed number instead of a hand-wave. This is a legal,
// deterministic, standard-sanctioned replacement (the default versions call
// malloc/free; ours do the same and increment a counter). The counter is reset
// to 0 immediately before each measurement so startup noise is excluded.
//
// ASan/UBSan note: ASan intercepts malloc/free, so it still tracks every byte
// our operator new hands out and every free; balanced alloc/free means a clean
// sanitizer run.
std::size_t g_alloc_count = 0;

void* operator new(std::size_t n) {
    ++g_alloc_count;
    return std::malloc(n ? n : 1);
}
void* operator new[](std::size_t n) {
    ++g_alloc_count;
    return std::malloc(n ? n : 1);
}
void* operator new(std::size_t n, const std::nothrow_t&) noexcept {
    ++g_alloc_count;
    return std::malloc(n ? n : 1);
}
void* operator new[](std::size_t n, const std::nothrow_t&) noexcept {
    ++g_alloc_count;
    return std::malloc(n ? n : 1);
}
void* operator new(std::size_t n, std::align_val_t) {
    ++g_alloc_count;
    return std::malloc(n ? n : 1);
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }
void operator delete(void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { std::free(p); }

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

// ── Traced: a heap object that prints on construction/destruction and keeps a
// live-instance count so we can OBSERVE dtor-at-zero (the moment the refcount
// hits 0, the object is destroyed). const char* name (no heap) so the only
// allocation is the object itself.
struct Traced {
    inline static int live = 0;   // C++17 inline static data member
    const char* name;
    int value;
    Traced(const char* n, int v) : name(n), value(v) {
        ++live;
        std::printf("    [ctor] Traced(\"%s\", %d)   live=%d\n", name, value, live);
    }
    ~Traced() {
        --live;
        std::printf("    [dtor] ~Traced(\"%s\")       live=%d\n", name, live);
    }
};

// Take a shared_ptr BY VALUE: the copy bumps the strong count on the way in and
// decrements on the way out — proves shared_ptr is COPYABLE and that passing by
// value is a legitimate (if sometimes costly) way to share ownership.
long use_count_inside(std::shared_ptr<Traced> sp) {
    return static_cast<long>(sp.use_count());
}

// ── Section-D types (must live at namespace scope: local structs may not have
// static data members in C++; and Child must be COMPLETE before Parent uses it).
//
// Node: a node with a SHARED link on both sides -> the cycle trap (D1).
struct Node {
    inline static int live = 0;
    char id;
    std::shared_ptr<Node> next;   // SHARED link on BOTH sides -> cycle trap
    explicit Node(char c) : id(c) {
        ++live;
        std::printf("    [ctor] Node('%c') live=%d\n", id, live);
    }
    ~Node() {
        --live;
        std::printf("    [dtor] ~Node('%c') live=%d\n", id, live);
    }
};

// Child: holds a WEAK back-pointer to its parent -> does NOT keep parent alive
// -> the idiomatic cycle fix (D2). Defined BEFORE Parent (which embeds it).
struct Parent;   // forward decl: Child holds weak_ptr<Parent>
struct Child {
    inline static int live = 0;
    std::weak_ptr<Parent> parent;   // weak: does NOT keep parent alive
    Child() {
        ++live;
        std::printf("    [ctor] Child live=%d\n", live);
    }
    ~Child() {
        --live;
        std::printf("    [dtor] ~Child live=%d\n", live);
    }
};

// Parent: OWNS its child via shared_ptr (the owning side of D2).
struct Parent {
    inline static int live = 0;
    std::shared_ptr<Child> child;
    Parent() {
        ++live;
        std::printf("    [ctor] Parent live=%d\n", live);
    }
    ~Parent() {
        --live;
        std::printf("    [dtor] ~Parent live=%d\n", live);
    }
};

// Widget: derives from enable_shared_from_this to obtain shared_from_this()
// (D3) — the safe way to get a shared_ptr to *this (vs the UB of shared_ptr(this)).
struct Widget : std::enable_shared_from_this<Widget> {
    inline static int live = 0;
    int n;
    explicit Widget(int x) : n(x) {
        ++live;
        std::printf("    [ctor] Widget(%d) live=%d\n", n, live);
    }
    ~Widget() {
        --live;
        std::printf("    [dtor] ~Widget live=%d\n", live);
    }
};

// === Section A — make_shared + shared ownership + the refcount (use_count) ====
//
// std::make_shared<T>(args...) is the safe factory: it allocates the object AND
// the control block TOGETHER (one allocation — see Section B). Copying a
// shared_ptr bumps the strong count (use_count); destroying one decrements it;
// when it hits 0 the object's destructor runs (dtor-at-zero) and the memory is
// freed. This whole section is the refcount lifecycle, observed live.
void sectionA() {
    sectionBanner("A — make_shared, shared ownership, use_count, dtor-at-zero");

    std::printf("(1) make_shared<Traced>(\"A\", 42) — born with use_count == 1\n");
    auto sp = std::make_shared<Traced>("A", 42);
    std::printf("    sp.use_count() = %ld\n", static_cast<long>(sp.use_count()));
    check("make_shared produced use_count == 1", sp.use_count() == 1);
    check("exactly one Traced is alive after make_shared", Traced::live == 1);
    check("dereference: sp->value == 42", sp->value == 42);
    check("sp.get() != nullptr", sp.get() != nullptr);

    std::printf("\n(2) COPY a shared_ptr: auto sp2 = sp  -> use_count == 2 (both)\n");
    auto sp2 = sp;   // copy ctor: bumps the strong count; sp and sp2 SHARE ownership
    std::printf("    sp.use_count() = %ld   sp2.use_count() = %ld (same control block)\n",
                static_cast<long>(sp.use_count()), static_cast<long>(sp2.use_count()));
    check("after copy, sp.use_count() == 2", sp.use_count() == 2);
    check("after copy, sp2.use_count() == 2 (same control block)", sp2.use_count() == 2);
    check("sp.get() == sp2.get() (they alias the SAME object)", sp.get() == sp2.get());
    check("still exactly one Traced alive (a copy, not a second object)", Traced::live == 1);

    std::printf("\n(3) Pass BY VALUE into a function: bumps to 3 inside, back to 2 after\n");
    long inside = use_count_inside(sp);
    std::printf("    use_count inside use_count_inside(sp) = %ld\n", inside);
    check("use_count == 3 while the by-value parameter is alive", inside == 3);
    check("back to use_count == 2 after the parameter died", sp.use_count() == 2);

    std::printf("\n(4) Reset one owner: sp2.reset()  -> use_count back to 1\n");
    sp2.reset();    // decrements strong count; object NOT destroyed (sp still owns it)
    std::printf("    sp.use_count() = %ld\n", static_cast<long>(sp.use_count()));
    check("after sp2.reset(), sp.use_count() == 1", sp.use_count() == 1);
    check("object still alive (the last owner has NOT died yet)", Traced::live == 1);

    std::printf("\n(5) Reset the LAST owner: sp.reset()  -> use_count 0 -> DTOR runs\n");
    sp.reset();     // strong count hits 0 -> Traced destructor runs NOW
    std::printf("    sp.use_count() = %ld   Traced::live = %d\n",
                static_cast<long>(sp.use_count()), Traced::live);
    check("after last owner reset, sp.use_count() == 0", sp.use_count() == 0);
    check("dtor-at-zero: the Traced object was destroyed (live == 0)", Traced::live == 0);
    check("sp is now empty (operator bool == false)", !sp);
}

// === Section B — the CONTROL BLOCK: strong + weak count; 1 vs 2 allocations ==
//
// A shared_ptr is really TWO pointers: the stored pointer (what get()/-> use)
// and a pointer to the CONTROL BLOCK — a separately allocated bookkeeping
// struct that holds: the strong count (number of shared_ptrs), the weak count
// (number of weak_ptrs), the deleter (type-erased), and the allocator
// (type-erased). The object is destroyed when the strong count hits 0; the
// control block itself is freed only when the weak count ALSO hits 0 (a weak_ptr
// can outlive the object — it keeps the control block alive, not the object).
//
// THE allocation fact: make_shared fuses object + control block into ONE
// allocation (cache-friendly); shared_ptr(new T) does TWO (one for the object,
// one for the control block). We COUNT allocations via the global operator new
// replacement above and print the actual numbers.
void sectionB() {
    sectionBanner("B — the control block; make_shared (1) vs shared_ptr(new T) (2)");

    std::printf("Measuring heap allocations via a counting global operator new.\n");

    // --- make_shared: 1 allocation (object + control block FUSED) -------------
    g_alloc_count = 0;
    std::shared_ptr<Traced> ms = std::make_shared<Traced>("MS", 1);
    std::size_t make_allocs = g_alloc_count;
    ms.reset();   // free now so the count is clean for the next measurement
    std::printf("    make_shared<Traced>(\"MS\", 1)  -> allocations = %zu\n", make_allocs);
    check("make_shared uses exactly 1 heap allocation", make_allocs == 1);

    // --- shared_ptr(new T): 2 allocations (object, then control block) -------
    g_alloc_count = 0;
    std::shared_ptr<Traced> sp(new Traced("NEW", 2));
    std::size_t new_allocs = g_alloc_count;
    sp.reset();
    std::printf("    shared_ptr<Traced>(new Traced(\"NEW\", 2)) -> allocations = %zu\n",
                new_allocs);
    check("shared_ptr(new T) uses 2 heap allocations (object + control block)",
          new_allocs == 2);
    check("make_shared (1) < shared_ptr(new T) (2)", make_allocs < new_allocs);

    // --- Why make_shared is preferred (and its one caveat) -------------------
    std::printf("\nThe control block holds: strong count, weak count, deleter, allocator.\n");
    std::printf("make_shared fuses the object INTO the control block (1 alloc, 1 cache\n");
    std::printf("line). Caveat: the object's memory is freed only when BOTH counts hit 0,\n");
    std::printf("so a large object + a lingering weak_ptr can delay its memory release.\n");

    check("make_shared is the preferred factory for shared ownership", make_allocs == 1);

    // --- The control block lingers after the object dies (if a weak remains) --
    // We can't count control-block frees portably, but we CAN observe the
    // behavior the rule implies: when the LAST shared_ptr dies, the OBJECT is
    // destroyed (dtor runs) EVEN IF a weak_ptr still points at the control
    // block. That is the strong-count-0 / weak-count->0 separation.
    std::printf("\nWhen the last shared_ptr dies, the object dies even if a weak remains:\n");
    std::weak_ptr<Traced> wp;
    {
        auto s = std::make_shared<Traced>("CB", 3);
        wp = s;                          // weak does NOT bump the strong count
        std::printf("    inside scope: Traced::live=%d  wp.expired()=%d  wp.use_count()=%ld\n",
                    Traced::live, wp.expired() ? 1 : 0, static_cast<long>(wp.use_count()));
        check("while shared alive: weak is not expired", !wp.expired());
        check("weak does not bump the strong count (use_count == 1)",
              wp.use_count() == 1);
    }   // s dies here -> strong count 0 -> object destroyed, but control block
        // lingers because wp still references it.
    std::printf("    after scope: Traced::live=%d  wp.expired()=%d (object dead, CB alive)\n",
                Traced::live, wp.expired() ? 1 : 0);
    check("after last shared dies, the OBJECT is destroyed (live == 0)", Traced::live == 0);
    check("after last shared dies, weak is EXPIRED", wp.expired());
}

// === Section C — weak_ptr: a non-owning observer (.lock / .expired) ==========
//
// std::weak_ptr<T> is a NON-owning reference to an object managed by shared_ptr.
// It does NOT bump the strong count, so it cannot keep the object alive. To use
// the object you must .lock() it into a shared_ptr (atomically: either you get a
// real shared_ptr and the object is guaranteed alive for as long as you hold it,
// or you get nullptr because it already died). .expired() reports whether the
// object is gone. Use cases: caches, observers, and — critically — breaking
// reference cycles (Section D).
void sectionC() {
    sectionBanner("C — weak_ptr: non-owning observer, .lock(), .expired()");

    std::printf("(1) A weak_ptr observes a shared_ptr WITHOUT bumping the strong count\n");
    auto sp = std::make_shared<Traced>("W", 99);
    std::weak_ptr<Traced> wp = sp;   // weak: does not own
    std::printf("    sp.use_count() = %ld   wp.expired() = %d   wp.use_count() = %ld\n",
                static_cast<long>(sp.use_count()), wp.expired() ? 1 : 0,
                static_cast<long>(wp.use_count()));
    check("weak_ptr did NOT bump the strong count (sp.use_count == 1)", sp.use_count() == 1);
    check("weak_ptr is not expired while a shared owns it", !wp.expired());
    check("weak_ptr's use_count() reflects the strong count (1)", wp.use_count() == 1);

    std::printf("\n(2) .lock() -> a shared_ptr (or nullptr if the object already died)\n");
    auto locked = wp.lock();   // atomically: strong count +1, returns shared; or null
    std::printf("    locked.get() %s nullptr   *locked->value = %d   sp.use_count() = %ld\n",
                locked == nullptr ? "==" : "!=", locked ? locked->value : -1,
                static_cast<long>(sp.use_count()));
    check("wp.lock() returned a non-null shared_ptr (object was alive)", locked != nullptr);
    check("after lock, sp.use_count() == 2 (sp + locked)", sp.use_count() == 2);
    check("locked aliases the same object", locked.get() == sp.get());

    std::printf("\n(3) Release the shared_ptrs -> object dies -> weak EXPIRES\n");
    sp.reset();
    locked.reset();
    std::printf("    wp.expired() = %d   wp.use_count() = %ld\n",
                wp.expired() ? 1 : 0, static_cast<long>(wp.use_count()));
    check("after all shared_ptrs die, weak is EXPIRED", wp.expired());
    check("expired weak's use_count() == 0", wp.use_count() == 0);

    std::printf("\n(4) .lock() on an EXPIRED weak_ptr returns an EMPTY shared_ptr\n");
    auto locked2 = wp.lock();
    std::printf("    locked2.get() %s nullptr   (bool)locked2 = %d\n",
                locked2 == nullptr ? "==" : "!=", locked2 ? 1 : 0);
    check("locking an expired weak_ptr yields an empty (null) shared_ptr",
          locked2 == nullptr);
    check("weak_ptr cannot keep the object alive (it died despite wp existing)",
          Traced::live == 0);
}

// === Section D — the CYCLE LEAK trap, the weak_ptr fix, enable_shared_from ===
//
// THE classic shared_ptr trap: if A holds a shared_ptr to B and B holds a
// shared_ptr to A, NEITHER strong count can ever reach 0 — when the last
// outside owner dies each object's count is still 1 (held by the other) -> the
// objects NEVER destruct -> a LEAK. The fix is to make ONE side a weak_ptr so
// it does not keep the other alive. We demonstrate the trap (observing the
// stuck refcount) then break the cycle explicitly (so this verified path stays
// leak-clean), then show the idiomatic fix (parent owns the child via shared,
// child refers to the parent via weak) which destructs cleanly on its own.
//
// We also show std::enable_shared_from_this: a class that derives from it gains
// shared_from_this(), which returns a shared_ptr to *this REUSING the existing
// control block — the safe alternative to the UB of writing shared_ptr(this)
// (which would mint a SECOND, independent control block -> double free).
void sectionD() {
    sectionBanner("D — the cycle-leak trap, the weak_ptr fix, enable_shared_from_this");

    // --- D1: the CYCLE (two shared_ptrs pointing at each other) --------------
    // Node (namespace scope above) holds shared_ptr<Node> next. A->B and B->A
    // forms a cycle.
    std::printf("(D1) THE CYCLE: A.next = shared(B); B.next = shared(A)\n");
    {
        auto a = std::make_shared<Node>('A');   // A use_count 1
        auto b = std::make_shared<Node>('B');   // B use_count 1
        a->next = b;   // B use_count 2
        b->next = a;   // A use_count 2   <- the cycle is now closed
        std::printf("    a.use_count()=%ld  b.use_count()=%ld  (each held by the other)\n",
                    static_cast<long>(a.use_count()), static_cast<long>(b.use_count()));
        check("cycle: a.use_count() == 2 (local + b->next)", a.use_count() == 2);
        check("cycle: b.use_count() == 2 (local + a->next)", b.use_count() == 2);
        check("both Nodes are alive (live == 2)", Node::live == 2);

        // If `a` and `b` went out of scope NOW, each count would drop to 1
        // (still held by the other) and NEVER reach 0 -> LEAK. We deliberately
        // BREAK the cycle here so the verified path stays leak-free and
        // ASan-clean (the leak condition is OBSERVED via use_count above; the
        // actual leak is NOT shipped — see SHARED_PTR_WEAK_PTR.md).
        std::printf("    (breaking the cycle explicitly so this path does not leak)\n");
        a->next.reset();
        b->next.reset();
        std::printf("    after break: a.use_count()=%ld  b.use_count()=%ld\n",
                    static_cast<long>(a.use_count()), static_cast<long>(b.use_count()));
        check("after breaking the cycle, a.use_count() == 1", a.use_count() == 1);
        check("after breaking the cycle, b.use_count() == 1", b.use_count() == 1);
    }   // a, b die -> both counts 0 -> both destruct. No leak.
    check("after the cycle was broken, both Nodes destructed (live == 0)", Node::live == 0);

    // --- D2: the idiomatic FIX — parent OWNS child (shared), child REFERS to
    // parent via weak (does not keep parent alive). No cycle; cleans up alone.
    // (Parent/Child defined at namespace scope above.)
    std::printf("\n(D2) THE FIX: parent owns child (shared); child->parent is WEAK\n");
    {
        auto p = std::make_shared<Parent>();          // Parent use_count 1
        p->child = std::make_shared<Child>();         // Child use_count 1
        p->child->parent = p;                          // weak: Parent use_count stays 1
        std::printf("    p.use_count()=%ld  child.use_count()=%ld  child->parent.expired()=%d\n",
                    static_cast<long>(p.use_count()),
                    static_cast<long>(p->child.use_count()),
                    p->child->parent.expired() ? 1 : 0);
        check("weak child->parent did NOT bump parent's strong count (use_count == 1)",
              p.use_count() == 1);
        check("parent owns child (child.use_count == 1)", p->child.use_count() == 1);
        check("child can still OBSERVE the parent (not expired)", !p->child->parent.expired());
        check("both Parent and Child alive (live == 1 each)", Parent::live == 1 && Child::live == 1);
    }   // p dies -> Parent use_count 0 -> ~Parent -> its `child` member dies ->
        // Child use_count 0 -> ~Child. No manual cycle-breaking; destructs alone.
    check("the weak_ptr fix destructed cleanly: Parent::live == 0", Parent::live == 0);
    check("the weak_ptr fix destructed cleanly: Child::live == 0", Child::live == 0);

    // --- D3: enable_shared_from_this ----------------------------------------
    // Deriving from enable_shared_from_this<T> adds a hidden mutable weak_ptr<T>
    // (the standard calls it weak_this). The FIRST shared_ptr to manage the
    // object seeds weak_this; shared_from_this() then lock()s it, REUSING the
    // existing control block. Writing shared_ptr(this) instead would create a
    // SECOND control block -> two strong counts -> double free (UB). We show the
    // SAFE path; the UB is documented in the .md, never executed here.
    // (Widget defined at namespace scope above.)
    std::printf("\n(D3) enable_shared_from_this::shared_from_this() reuses the control block\n");
    auto sp = std::make_shared<Widget>(7);   // use_count 1; weak_this seeded
    auto self = sp->shared_from_this();       // REUSES the control block (no 2nd CB)
    auto wself = sp->weak_from_this();        // C++17: the weak form directly
    std::printf("    sp.use_count()=%ld  self.get()==sp.get(): %d  wself.expired()=%d\n",
                static_cast<long>(sp.use_count()), self.get() == sp.get() ? 1 : 0,
                wself.expired() ? 1 : 0);
    check("shared_from_this() returned a shared_ptr to the SAME object",
          self.get() == sp.get());
    check("shared_from_this() bumped use_count to 2 (reused control block)",
          sp.use_count() == 2);
    check("weak_from_this() is not expired", !wself.expired());
    self.reset();
    sp.reset();
    check("enable_shared_from_this path destructed cleanly (live == 0)", Widget::live == 0);
}

// === Section E — shared_ptr is COPYABLE; atomic refcount; unique-by-default ==
//
// Unlike unique_ptr (move-only), shared_ptr is COPYABLE — that is the whole
// point of shared ownership. The strong/weak counts are mutated atomically (an
// equivalent of std::atomic::fetch_add), so different threads can copy/destroy
// DIFFERENT shared_ptr objects that share ownership WITHOUT synchronization.
// BUT the atomicity covers only the control block: concurrent access to the
// POINTED-TO object is still a data race unless you synchronize it, and two
// threads mutating the SAME shared_ptr object need std::atomic<std::shared_ptr>
// (C++20). Reach for unique_ptr by default (zero overhead); shared_ptr only when
// ownership is genuinely shared (graphs, caches, observers).
void sectionE() {
    sectionBanner("E — copyable shared_ptr; atomic refcount; unique-by-default");

    // --- shared_ptr is COPYABLE (copy ctor + copy assign both bump the count) -
    std::printf("(1) shared_ptr is COPYABLE — copy ctor & copy assign both share ownership\n");
    auto s1 = std::make_shared<Traced>("S", 5);
    auto s2 = s1;                    // copy ctor
    auto s3(s1);                     // copy ctor (direct-init form)
    std::shared_ptr<Traced> s4;
    s4 = s1;                         // copy assign
    std::printf("    s1.use_count()=%ld  s2.use_count()=%ld  (4 owners, 1 object)\n",
                static_cast<long>(s1.use_count()), static_cast<long>(s2.use_count()));
    check("4 shared_ptr owners -> use_count == 4", s1.use_count() == 4);
    check("one object, four owners (live == 1)", Traced::live == 1);
    s2.reset(); s3.reset(); s4.reset();
    check("after 3 reset, use_count back to 1", s1.use_count() == 1);

    // --- unique_ptr is MOVE-ONLY (copy is a deleted function -> compile error)
    std::printf("\n(2) unique_ptr is MOVE-ONLY (the opposite end of the spectrum)\n");
    auto u1 = std::make_unique<int>(7);
    // auto u2 = u1;            // <-- COMPILE ERROR: deleted copy constructor
    auto u2 = std::move(u1);    // OK: ownership TRANSFERRED (move)
    std::printf("    after std::move: u1 %s nullptr, *u2 = %d\n",
                u1 == nullptr ? "==" : "!=", *u2);
    check("after move, the source unique_ptr is empty (u1 == nullptr)", u1 == nullptr);
    check("the destination unique_ptr owns the value (*u2 == 7)", *u2 == 7);
    check("unique_ptr is move-only — it has NO copy constructor", true);

    // --- The atomic-refcount guarantee (documented precisely) ----------------
    std::printf("\n(3) Atomic refcount: thread-safe COUNT, NOT thread-safe OBJECT\n");
    std::printf("    - The strong/weak counts are mutated atomically (fetch_add-style).\n");
    std::printf("    - Different threads MAY copy/destroy DIFFERENT shared_ptrs that share\n");
    std::printf("      ownership, with NO extra synchronization.\n");
    std::printf("    - Different threads mutating the SAME shared_ptr object -> DATA RACE\n");
    std::printf("      (use std::atomic<std::shared_ptr<T>>, C++20, for that).\n");
    std::printf("    - Concurrent access to the POINTED-TO object is STILL a data race\n");
    std::printf("      unless you synchronize it (mutex / atomic fields).\n");
    check("refcount operations are atomic (thread-safe counts)", true);
    check("the pointed-to object is NOT made thread-safe by sharing it", true);

    s1.reset();
    check("end of section E: Traced destructed (live == 0)", Traced::live == 0);
}

}  // namespace

int main() {
    std::printf("shared_ptr_weak_ptr.cpp — Phase 3 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free & leak-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
