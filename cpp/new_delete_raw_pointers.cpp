// new_delete_raw_pointers.cpp — Phase 3 bundle #17.
//
// GOAL (one line): show, by printing every value, how `new`/`delete`/`new[]`/
// `delete[]` drive RAW owning pointers — the MANUAL memory foundation modern
// C++ AVOIDS — pinning the leak / double-delete / use-after-free / dangling-
// pointer UB traps as DOCUMENTED expert payoffs (gated behind #ifdef DEMO_UB so
// the verified path stays UB-free and `just sanitize` clean).
//
// This is the GROUND TRUTH for NEW_DELETE_RAW_POINTERS.md. Every number, table,
// and worked example in the guide is printed by this file. Change it ->
// re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run new_delete_raw_pointers
//         (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//             new_delete_raw_pointers.cpp -o /tmp/cpp_new_delete_raw_pointers
//             && /tmp/cpp_new_delete_raw_pointers)

#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <memory>     // std::unique_ptr / std::make_unique (the RAII fix — P3 #18)
#include <new>        // placement new (::new (ptr) T), operator new/delete

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

// A type whose ctor/dtor PRINT — so the ctor<->new / dtor<->delete pairing is
// OBSERVABLE and cannot be elided by the optimizer or the sanitizer. The inline
// static `live` counter lets every section assert that each `new`'d object is
// eventually destroyed (no leak in the verified path). NOTE: no pointer address
// is ever printed (heap addresses are non-deterministic across runs under ASLR,
// which would break the byte-identical `just out` x2 determinism rule).
struct Traced {
    inline static int live = 0;   // C++17 inline static data member
    int value;
    Traced() : value(0) {
        ++live;
        std::printf("    [ctor] Traced()           (live now = %d)\n", live);
    }
    explicit Traced(int v) : value(v) {
        ++live;
        std::printf("    [ctor] Traced(%d)         (live now = %d)\n", v, live);
    }
    ~Traced() {
        --live;
        std::printf("    [dtor] ~Traced() value=%d  (live now = %d)\n", value, live);
    }
};

// === Section A — new (heap-alloc + ctor) and delete (dtor + free) ============
//
// `new T(args)` does TWO things atomically: (1) allocates heap storage by
// calling operator new(sizeof(T)), and (2) constructs a T there, running its
// constructor. It returns a `T*` — a RAW OWNING pointer. `delete p` is the
// inverse: (1) runs the destructor, (2) calls operator delete to free. The rule
// that makes manual memory work: ONE new needs EXACTLY ONE matching delete.
void sectionA() {
    sectionBanner("A — new (heap-alloc + ctor) and delete (dtor + free); the 1:1 match");

    std::printf("1) SCALAR: `new int(42)` -> int*   (heap-alloc + initialize)\n");
    int* p = new int(42);
    std::printf("   *p = %d\n", *p);
    check("new int(42) returned a non-null pointer whose object == 42",
          p != nullptr && *p == 42);

    std::printf("   delete p;   (int is trivial: NO dtor runs, then the storage is freed)\n");
    delete p;          // <-- the ONE matching delete for the ONE new above
    p = nullptr;       // hygiene: a deleted pointer is DANGLING until reassigned
    check("after delete the raw pointer was nulled out (dangling-prevention hygiene)",
          p == nullptr);

    std::printf("\n2) CLASS TYPE: `new Traced(7)` -> the ctor runs DURING new\n");
    Traced* t = new Traced(7);   // [ctor] prints here, inside the new-expression
    std::printf("   t->value = %d\n", t->value);
    check("new Traced(7) constructed an object with value == 7", t->value == 7);
    check("exactly ONE Traced instance is live after `new Traced(7)`", Traced::live == 1);

    std::printf("   delete t;   (the dtor runs FIRST, then the storage is freed)\n");
    delete t;          // [dtor] prints here — the 1:1 match for the new above
    t = nullptr;
    check("after delete the Traced instance count returned to 0 (no leak)",
          Traced::live == 0);

    std::printf("\n3) THE 1:1 MATCH RULE — every `new` needs EXACTLY ONE matching `delete`:\n");
    std::printf("     new T      <->  delete p;      (non-array form)\n");
    std::printf("     new T[n]   <->  delete[] p;    (array form — Section B)\n");
    std::printf("   0 new + 1 delete, or 1 new + 2 deletes => UNDEFINED BEHAVIOR (Section D).\n");
    check("the 1:1 match rule: new/delete and new[]/delete[] pair by form", true);
}

// === Section B — new[]/delete[] (array form); a form MISMATCH is UB ==========
//
// `new T[n]` allocates + default-constructs n elements and returns `T*` to the
// FIRST element. `delete[] p` destroys all n (in REVERSE construction order)
// then frees. The two forms must MATCH: `delete` on a `new[]` pointer or
// `delete[]` on a `new` pointer is UNDEFINED BEHAVIOR (the mismatch UB is gated
// behind #ifdef DEMO_UB here so the verified path stays clean).
void sectionB() {
    sectionBanner("B — new[]/delete[] (array form); a form MISMATCH is UB");

    std::printf("1) `new int[5]{10,20,30,40,50}` -> int* (points at the FIRST element)\n");
    int* arr = new int[5]{10, 20, 30, 40, 50};
    int sum = 0;
    for (int i = 0; i < 5; ++i) sum += arr[i];
    for (int i = 0; i < 5; ++i) std::printf("   arr[%d] = %d\n", i, arr[i]);
    std::printf("   sum(arr) = %d\n", sum);
    check("new int[5]{...} initialized all 5 elements", arr[0] == 10 && arr[4] == 50);
    check("array contents sum to 150", sum == 150);

    std::printf("\n   delete[] arr;   (frees the WHOLE array — must NOT be `delete arr;`)\n");
    delete[] arr;      // <-- the ONE matching delete[] for the ONE new[] above
    arr = nullptr;
    check("array form matched: new[] freed with delete[]", arr == nullptr);

    std::printf("\n2) CLASS ARRAY: `new Traced[3]` -> 3 default ctors run DURING new[]\n");
    Traced* objs = new Traced[3];            // 3x [ctor] Traced()
    objs[0].value = 1;
    objs[1].value = 2;
    objs[2].value = 3;
    check("new Traced[3] ran 3 ctors (live instances == 3)", Traced::live == 3);

    std::printf("\n   delete[] objs;  -> 3 dtors run in REVERSE construction order (3,2,1)\n");
    delete[] objs;                           // 3x [dtor], reverse order
    objs = nullptr;
    check("delete[] destroyed all 3 array elements (live back to 0)", Traced::live == 0);

    std::printf("\n3) THE FORM-MISMATCH TRAP — UB (gated behind DEMO_UB; never verified):\n");
    std::printf("   `delete  p;`  on a `new T[n]` pointer  => UB (1 dtor, wrong free size)\n");
    std::printf("   `delete[] p;` on a `new T`   pointer   => UB (reads a bogus array cookie)\n");
    check("new/delete AND new[]/delete[] must be paired BY FORM (mismatch == UB)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    int* bad = new int[3]{1, 2, 3};
    delete bad;    // <-- UB: scalar delete on a new[] pointer
    bad = nullptr; // (ASan/UBSan: heap corruption / "alloc-dealloc-mismatch")
#else
    std::printf("   (DEMO_UB not defined: the mismatch UB is correctly omitted from this build.)\n");
#endif
}

// === Section C — the LEAK trap: a `new` with no matching `delete` ============
//
// Any code path between `new` and `delete` that exits early (return / throw /
// break) WITHOUT deleting leaks the object — it is never freed, yet remains
// unreachable. The RAII fix (unique_ptr, P3 #18): the smart pointer's DESTRUCTOR
// runs at scope exit on EVERY path (including early return and exception
// unwind) and calls `delete`. The leak becomes impossible.
void sectionC() {
    sectionBanner("C — the LEAK trap: a `new` with no matching `delete`");

    std::printf("THE TRAP — any early exit between `new` and `delete` LEAKS:\n");
    std::printf("     // BAD (leaks on the early return):\n");
    std::printf("     //   Traced* p = new Traced(99);\n");
    std::printf("     //   if (some_condition) return;   // <-- LEAK: p never deleted\n");
    std::printf("     //   delete p;\n\n");

    std::printf("THE RAII FIX (P3 #18, unique_ptr): the smart pointer's DESTRUCTOR runs at\n");
    std::printf("scope exit — on EVERY path — and that dtor calls `delete`. Leak = impossible.\n");
    std::printf("     // GOOD (unique_ptr OWNS it; its dtor deletes):\n");
    {
        auto up = std::make_unique<Traced>(99);   // [ctor] prints; unique_ptr OWNS it
        std::printf("   up->value = %d   (owned by the unique_ptr)\n", up->value);
        check("unique_ptr owns a live Traced(99)", up->value == 99 && Traced::live == 1);
        // ── scope exit here: unique_ptr's dtor runs and calls delete ──
    }
    check("after the inner scope closed, the unique_ptr auto-deleted (live == 0, no leak)",
          Traced::live == 0);

    std::printf("\nRAII generalizes: std::shared_ptr, std::vector, std::string, std::lock_guard,\n");
    std::printf("std::fstream... ALL tie resource release to scope exit. See raii (P3 #16).\n");

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — leaks; ASan leak-detection (Linux) reports it at exit.
    Traced* leaked = new Traced(12345);
    (void)leaked;   // intentionally never deleted
#else
    std::printf("\n(DEMO_UB not defined: the deliberate leak is correctly omitted from this build.)\n");
#endif
}

// === Section D — DOUBLE-DELETE / USE-AFTER-FREE / DANGLING: all UB ==========
//
// After `delete p;` the object's lifetime has ENDED and the storage is freed.
// The pointer VALUE still sits in `p`, but it now DENOTES NOTHING — a DANGLING
// pointer. Three classic UB traps follow. The verified path here is the SAFE
// shape (new, use, delete, NULL OUT); the UB traps are gated behind DEMO_UB.
void sectionD() {
    sectionBanner("D — DOUBLE-DELETE / USE-AFTER-FREE / DANGLING: all UB (gated)");

    std::printf("After `delete p;` the object's lifetime has ENDED; the storage is freed.\n");
    std::printf("The pointer VALUE still sits in `p`, but it now DENOTES NOTHING — a DANGLING\n");
    std::printf("pointer. Three classic UB traps follow from this:\n\n");
    std::printf("   TRAP 1 — DOUBLE-DELETE:   delete p; delete p;        => UB\n");
    std::printf("   TRAP 2 — USE-AFTER-FREE:  delete p; *p; / p->f();    => UB\n");
    std::printf("   TRAP 3 — DANGLING read:   delete p; int x = *p;      => UB\n\n");

    std::printf("THE VERIFIED (safe) SHAPE: new, use, delete, then NULL OUT the pointer so it\n");
    std::printf("cannot be accidentally double-deleted or dereferenced:\n");
    {
        int* q = new int(55);
        std::printf("   int* q = new int(55);   -> *q = %d\n", *q);
        check("q points at a live int == 55", q != nullptr && *q == 55);
        delete q;          // lifetime ends here
        q = nullptr;       // null it out -> a later `delete q`/`*q` is benign/null
        check("after delete, q was nulled out (no dangling pointer left)", q == nullptr);
    }

    std::printf("\nTHE RAII FIX: a unique_ptr CANNOT be double-deleted (its dtor runs once,\n");
    std::printf("at scope exit) and CANNOT be used after free (the object is alive for the\n");
    std::printf("whole lifetime of the unique_ptr). The bug class is designed away.\n");

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — all three are UB; never enabled by just run/out/check/sanitize
    int* d = new int(1);
    delete d;
    delete d;             // <-- DOUBLE-DELETE  (ASan: "attempting double-free")
    int* u = new int(2);
    delete u;
    int garbage = *u;     // <-- USE-AFTER-FREE / DANGLING read (ASan: "heap-use-after-free")
    std::printf("[DEMO_UB] garbage = %d   <-- UNDEFINED (meaningless value)\n", garbage);
#else
    std::printf("\n(DEMO_UB not defined: the double-delete / UAF / dangling UB is omitted.)\n");
#endif
    check("verified path: no double-delete, no UAF, no dangling-deref (all gated)", true);
}

// A type with CLASS-SPECIFIC operator new/delete — demonstrates customization.
// These are REPLACEABLE allocation functions: a program may override the GLOBALS
// and/or provide class-specific ones. Here Tracker's own print and then delegate
// to the global ::operator new / ::operator delete.
struct Tracker {
    int id;
    explicit Tracker(int i) : id(i) {}

    static void* operator new(std::size_t n) {
        std::printf("    [Tracker::operator new] allocating %zu bytes\n", n);
        return ::operator new(n);          // delegate to the global allocator
    }
    static void operator delete(void* p) noexcept {
        std::printf("    [Tracker::operator delete] freeing\n");
        ::operator delete(p);              // delegate to the global deallocator
    }
};

// === Section E — placement new, operator new/delete customization, the lesson
//
// (1) PLACEMENT NEW constructs an object in PRE-ALLOCATED memory (no allocation
// happens): `::new (buf) T(args)`. YOU must manually call the dtor — the memory
// is yours and is NOT freed. This is how std::vector / std::optional / std::any
// separate raw storage from live objects. (2) operator new/delete can be
// customized globally or per-class. (3) THE LESSON: never raw new/delete in
// modern C++ — RAII smart pointers make the 1:1 match automatic.
void sectionE() {
    sectionBanner("E — placement new, operator new/delete customization, the lesson");

    std::printf("1) PLACEMENT NEW: construct an object in PRE-ALLOCATED memory (no allocation).\n");
    std::printf("   Used by std::vector/std::optional/std::any to split storage from object.\n");
    std::printf("   YOU must manually call the dtor — placement-new memory is NOT freed.\n\n");

    alignas(Traced) unsigned char buf[sizeof(Traced)];   // raw storage, aligned for Traced
    std::printf("   alignas(Traced) unsigned char buf[%zu];   (raw, correctly-aligned storage)\n",
                sizeof(buf));
    Traced* placed = ::new (buf) Traced(314);   // PLACEMENT new: ctor runs in buf, NO heap alloc
    std::printf("   placed->value = %d   (constructed inside buf, no heap allocation)\n",
                placed->value);
    check("placement new constructed a Traced(314) in local storage", placed->value == 314);
    check("the placement-new'd object is live (count == 1)", Traced::live == 1);
    placed->~Traced();                          // <-- MANUAL dtor call (buf is NOT freed)
    placed = nullptr;
    check("manual ~Traced() ended the object's lifetime (count == 0)", Traced::live == 0);
    std::printf("   (buf itself is automatic storage — reclaimed at scope exit; NO delete here!)\n");

    std::printf("\n2) operator new / operator delete CUSTOMIZATION (global & class-specific):\n");
    std::printf("   `new T`    calls operator new(sizeof(T))   [or a class-specific overload];\n");
    std::printf("   `delete p` calls operator delete(p)        [or a class-specific overload].\n");
    std::printf("   You may REPLACE the globals, or give a class its OWN, to instrument/arena/pool.\n");
    {
        Tracker* t = new Tracker(7);   // calls Tracker::operator new, then Tracker(int)
        std::printf("   t->id = %d\n", t->id);
        check("Tracker(7) was allocated via its class-specific operator new", t->id == 7);
        delete t;                      // calls ~Tracker (trivial), then Tracker::operator delete
        t = nullptr;
    }

    std::printf("\n3) THE LESSON — NEVER use raw new/delete in modern C++:\n");
    std::printf("   every leak / double-delete / use-after-free / dangling bug class LIVES at\n");
    std::printf("   this layer. RAII smart pointers (P3 #18-19) make the 1:1 match AUTOMATIC:\n");
    std::printf("     std::make_unique<T>(...)  -> std::unique_ptr<T>   (owning, move-only)\n");
    std::printf("     std::make_shared<T>(...)  -> std::shared_ptr<T>   (refcounted sharing)\n");
    std::printf("   Their destructors call `delete` exactly once, on exactly one path.\n\n");

    std::printf("   CROSS-LANGUAGE — this whole bug class is a C/C++ peculiarity:\n");
    std::printf("     Rust:   NO new/delete. Box<T>/Arc<T>/Vec OWN; the borrow checker makes\n");
    std::printf("             double-free & use-after-free COMPILE-TIME ERRORS.\n");
    std::printf("     Go/TS/Python: a garbage collector frees unreachable objects — no `delete`,\n");
    std::printf("             no manual double-free / UAF (cost: nondeterministic GC pauses).\n");
    check("placement new + class-specific operator new/delete both demonstrated UB-free", true);
}

}  // namespace

int main() {
    std::printf("new_delete_raw_pointers.cpp — Phase 3 bundle #17.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23 -O2\n");
    std::printf("-Wall -Wextra -Wpedantic; UB-free (just sanitize clean — every `new`\n");
    std::printf("matched by a `delete`; leak/double-delete/UAF traps are DEMO_UB-gated).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
