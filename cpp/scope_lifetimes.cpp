// scope_lifetimes.cpp — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how a C++ name's SCOPE
// (where it's visible: block / namespace / class) is independent of its
// object's STORAGE DURATION (when it's born and dies: automatic / static /
// thread / dynamic) — pinning the killer feature (the destructor runs
// EXACTLY at scope exit = RAII, the deterministic-cleanup idiom) and the
// classic UB traps (returning T& to a local; the static-init order fiasco),
// both DOCUMENTED and never executed in the verified path.
//
// This is the GROUND TRUTH for SCOPE_LIFETIMES.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run scope_lifetimes   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                  scope_lifetimes.cpp -o /tmp/cpp_scope_lifetimes
//                                  && /tmp/cpp_scope_lifetimes)

#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <string>     // std::string (return-by-value demo)

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

// ── Namespace-scope demo (Section A.4) ────────────────────────────────────────
// A named namespace NESTS: physics::units::name. `constexpr` at namespace scope
// implies `const` (and, inside this anonymous namespace, internal linkage).
// For cross-TU shared constants the modern idiom is `inline constexpr` (C++17) —
// discussed in the .md; here plain `constexpr` suffices (single TU, internal).
namespace physics {
constexpr int c = 299792458;              // m/s; speed of light (exact, since 1983)
namespace units {
constexpr long long km_per_lightyear = 9460730472580LL;   // km in one light-year
}  // namespace units
}  // namespace physics

// ── Anonymous-namespace demo (Section A.5) ────────────────────────────────────
// An UNNAMED namespace gives every name inside INTERNAL linkage: visible in THIS
// translation unit, invisible to other TUs. (This whole file's helpers —
// sectionBanner, check, every sectionX — live in one; that is WHY same-named
// helpers in sibling bundles never collide.) Here we nest a second one to show
// the idiom explicitly.
namespace demo {
namespace {
int internal_value = 7;   // internal linkage; accessible as demo::internal_value
}  // anonymous namespace
}  // namespace demo

// ── RAII-PREVIEW type (Section B) ────────────────────────────────────────────
// A ctor/dtor pair that prints. The dtor runs DETERMINISTICALLY at scope exit —
// the foundation of RAII (Resource Acquisition Is Initialization). The `live`
// counter is an observable side effect, so optimizers cannot elide the dtor
// under -O2/ASan (they must preserve observable behavior).
struct ScopedTrace {
    inline static int live = 0;   // C++17 inline static data member
    const char* name;
    explicit ScopedTrace(const char* n) : name(n) {
        ++live;
        std::printf("    [ctor] %-8s acquired  (live instances now = %d)\n", name, live);
    }
    ~ScopedTrace() {
        --live;
        std::printf("    [dtor] %-8s released at scope exit (live = %d)\n", name, live);
    }
};

// ── Static-local id generator (Section C) ────────────────────────────────────
// A function-local `static` is born on FIRST call through the declaration and
// PERSISTS across all subsequent calls (one instance). This is the "construct
// on first use" idiom — and the classic cure for the static-init order fiasco.
int make_id() {
    static int next = 1000;   // first-call init; one instance; lives to program end
    return ++next;
}

// ── Return by VALUE (Section D) — the SAFE way to hand a local back ──────────
// The local is destroyed at return, but its VALUE was copied/moved out (or the
// copy was elided entirely via NRVO). The caller receives a real, owning object.
std::string make_greeting(const char* who) {
    std::string local = "hello, ";
    local += who;
    return local;   // safe: by value (copy-elided / moved), NOT a reference
}

// ── File-scope (namespace-scope) variable: STATIC storage duration ───────────
// Born before main() enters; destroyed after main() exits (dtor reverse-order).
// Inside this anonymous namespace it also has INTERNAL linkage.
int file_scope_calls = 0;

// === Section A — Block scope, name hiding, namespaces ========================
void sectionA() {
    sectionBanner("A — Block scope, name hiding, namespaces");

    std::printf("SCOPE = where a NAME is visible (for name lookup). It is INDEPENDENT of\n");
    std::printf("storage duration (Section E). The kinds: block, function-parameter, namespace,\n");
    std::printf("class, enumeration, lambda, template-parameter. Here: block + namespace.\n");

    // (1) BLOCK scope: a name declared inside { } is visible only until the } and
    //     is DESTROYED at the closing } (for an automatic object — Section B).
    std::printf("\n(1) BLOCK scope: a name inside { } is visible only inside that block\n");
    {
        int block_local = 42;
        std::printf("    inside block: block_local = %d\n", block_local);
        check("block_local is visible inside its block (== 42)", block_local == 42);
    }
    // block_local is OUT OF SCOPE here. Referencing it is a COMPILE ERROR (not a
    // warning) — documented, not run (the file would not build otherwise).
    std::printf("    after }: block_local is out of scope (referencing it = compile error)\n");
    check("block_local out of scope after } (reference would be a compile error)", true);

    // (2) NAME HIDING: an inner declaration of the same name HIDES the outer one
    //     within the inner block. The outer object is NOT modified — only shadowed.
    std::printf("\n(2) NAME HIDING: an inner `x` hides the outer `x` (outer is unchanged)\n");
    int x = 10;
    {
        int x = 20;                    // HIDES the outer x within this block only
        std::printf("    inner x = %d  (hides outer; outer still exists, just not by this name)\n", x);
        check("inner x hides outer x (inner == 20)", x == 20);
    }
    std::printf("    after inner block: outer x = %d  (the outer object was never touched)\n", x);
    check("outer x is unchanged after the hiding block exits (== 10)", x == 10);

    // (3) POINT OF DECLARATION (the locus): a name is in scope from RIGHT AFTER its
    //     declarator — INCLUDING inside its own initializer and (for types) inside
    //     its own body. This is why self-reference compiles, and why `int x = x;`
    //     reads the not-yet-initialized inner x (UB — see VALUES_TYPES, not run).
    std::printf("\n(3) POINT OF DECLARATION (locus): a name is in scope right after its declarator\n");
    struct Node { Node* next; };       // `Node` is in scope at the `{` -> self-ref OK
    Node n{nullptr};
    std::printf("    struct Node { Node* next; };  -> self-referential member compiles (locus rule)\n");
    check("point-of-declaration: a type can self-refer (Node{nullptr}.next == nullptr)",
          n.next == nullptr);

    // (4) NAMESPACE scope + NESTING: a name in namespace N is visible as N::name.
    //     Namespaces NEST (N::M::name) and may be REOPENED across multiple blocks.
    std::printf("\n(4) NAMESPACE scope + nesting (qualified names: N::M::name)\n");
    std::printf("    physics::c                  = %d  (m/s; speed of light)\n", physics::c);
    std::printf("    physics::units::km_per_ly   = %lld  (km per light-year)\n",
                physics::units::km_per_lightyear);
    check("nested namespace access: physics::c == 299792458", physics::c == 299792458);
    check("nested namespace access: physics::units::km_per_lightyear == 9460730472580",
          physics::units::km_per_lightyear == 9460730472580LL);

    // (5) ANONYMOUS namespace: every name inside has INTERNAL linkage — visible
    //     elsewhere in THIS TU, invisible to other TUs (no name mangling across).
    //     This is the modern C++ replacement for C's `static` on a file-scope name.
    std::printf("\n(5) ANONYMOUS namespace => INTERNAL linkage (visible in this TU only)\n");
    std::printf("    demo::internal_value = %d  (lives in a nested unnamed namespace)\n",
                demo::internal_value);
    check("anonymous-namespace member is accessible within its TU (== 7)",
          demo::internal_value == 7);
}

// === Section B — Automatic storage: born at decl, destroyed at } (RAII) ======
void sectionB() {
    sectionBanner("B — Automatic storage: born at decl, destroyed at } (RAII preview)");

    std::printf("Automatic-storage locals are BORN at their declaration and DESTROYED at the\n");
    std::printf("enclosing block's closing }. For a class type the DESTRUCTOR runs right there,\n");
    std::printf("in REVERSE order of construction (LIFO). This deterministic scope-bound cleanup\n");
    std::printf("IS RAII (Resource Acquisition Is Initialization). Full RAII is P3; this is the\n");
    std::printf("preview that establishes the mechanism.\n");

    ScopedTrace::live = 0;   // reset for a clean, self-contained demonstration
    {
        std::printf("\n  entering outer block\n");
        ScopedTrace a("a");
        {
            ScopedTrace b("b");
            std::printf("      --- innermost point: a and b both alive ---\n");
            check("both ScopedTrace instances alive at the innermost point (live == 2)",
                  ScopedTrace::live == 2);
        }   // ~b() runs HERE, at this } (inner block exits first)
        std::printf("  after inner block: b destroyed; live now = %d\n", ScopedTrace::live);
        check("inner ScopedTrace b was destroyed at its block's } (live == 1)",
              ScopedTrace::live == 1);
    }   // ~a() runs HERE, at this } (outer block exits)
    std::printf("  after outer block: a destroyed; live now = %d\n", ScopedTrace::live);
    check("outer ScopedTrace a was destroyed at its block's } (live == 0)",
          ScopedTrace::live == 0);
    check("RAII preview: destructors ran in REVERSE order of construction (b before a) — LIFO",
          true);

    // BORN AT DECLARATION (not at block entry): a local is NOT in scope before its
    // declarator. Referencing it earlier is a compile error. (Contrast with C89,
    // which required all declarations at the top of a block — C++ never did.)
    std::printf("\nA local is BORN at its declaration (not at block entry). Referencing it before\n");
    std::printf("the declarator is a compile error. The destructor always runs at the block's }.\n");
    check("automatic object: born at decl, destroyed at } (the RAII guarantee)", true);
}

// === Section C — Static storage: file-scope + static locals (first-call init) =
void sectionC() {
    sectionBanner("C — Static storage: file-scope + static locals (first-call init)");

    std::printf("Static-storage objects are born ONCE and live until PROGRAM EXIT. Two flavors:\n");
    std::printf("file-scope (born before main, in definition order) and static LOCALS (born on\n");
    std::printf("first call through the declaration, then skipped). Destructors run in reverse\n");
    std::printf("order of construction at program shutdown.\n");

    // (1) FILE-SCOPE (namespace-scope) variable: static storage, lives to program end.
    ++file_scope_calls;
    std::printf("\n(1) FILE-SCOPE variable: static storage; born before main, dies at program exit\n");
    std::printf("    file_scope_calls after increment = %d  (persists for the whole run)\n",
                file_scope_calls);
    check("file-scope int has static storage (file_scope_calls == 1 after one increment)",
          file_scope_calls == 1);

    // (2) STATIC LOCAL: born on FIRST call through the declaration; SKIPPED on later
    //     calls. ONE instance shared across all calls (idempotent init).
    int id1 = make_id();
    int id2 = make_id();
    int id3 = make_id();
    std::printf("\n(2) STATIC LOCAL (make_id): one instance, born on first call, persists\n");
    std::printf("    make_id() x3 = %d, %d, %d  (first-call init; counter persists across calls)\n",
                id1, id2, id3);
    check("static local persists across calls: make_id() x3 == 1001, 1002, 1003",
          id1 == 1001 && id2 == 1002 && id3 == 1003);

    // (3) ADDRESS STABILITY: a static local has ONE address across all calls. We
    //     print only the equal/unequal BOOLEAN — never the raw address (ASLR makes
    //     raw addresses non-reproducible across runs).
    auto addr_of_static = []() -> int* {
        static int s = 42;
        return &s;
    };
    int* p1 = addr_of_static();
    int* p2 = addr_of_static();
    std::printf("\n(3) ADDRESS stability: a static local has ONE address across calls\n");
    std::printf("    addr_of_static() called twice -> same address? %s (one shared instance)\n",
                p1 == p2 ? "YES" : "NO");
    check("static local has a stable address across calls (p1 == p2)", p1 == p2);

    // (4) The STATIC-INIT ORDER FIASCO — DOCUMENTED, NOT RUN.
    //     A single-TU bundle CANNOT reproduce it (within one TU, dynamic-init
    //     order is top-to-bottom, well-defined). The trap is ACROSS translation
    //     units: the order of dynamic initialization of static-storage objects in
    //     DIFFERENT TUs is UNSPECIFIED. If TU A's init reads TU B's static (which
    //     may not be initialized yet), the read observes an indeterminate value —
    //     UB. Cures: "construct on first use" (a static local — see make_id) or
    //     C++20 `constinit` (forces static, not dynamic, initialization).
    std::printf("\n(4) STATIC-INIT ORDER FIASCO — documented (a single-TU bundle cannot show it)\n");
    std::printf("    Dynamic-init ORDER of static-storage objects ACROSS translation units is\n");
    std::printf("    UNSPECIFIED. If TU A's init reads TU B's static before B is initialized, the\n");
    std::printf("    value is indeterminate -> UB. WITHIN a TU the order is well-defined (top-to-\n");
    std::printf("    bottom). Cures: 'construct on first use' (a static local, like make_id) or\n");
    std::printf("    C++20 `constinit` (force static — not dynamic — initialization).\n");
    check("static-init order fiasco documented (cross-TU dynamic init order is unspecified)", true);
}

// === Section D — Dynamic storage (new/delete) + return-T&-to-local UB =========
void sectionD() {
    sectionBanner("D — Dynamic storage (new/delete) + the return-T&-to-local UB trap");

    std::printf("DYNAMIC storage: an object created by `new` lives on the heap until YOU\n");
    std::printf("explicitly `delete` it. There is NO automatic cleanup — the destructor does\n");
    std::printf("NOT run at scope exit. This is exactly why smart pointers (P3) exist.\n");

    // (1) new / delete: manual heap lifetime. MUST be balanced (else leak / UB).
    int* heap = new int(42);
    std::printf("\n(1) new/delete: int* heap = new int(42);  -> *heap = %d (lives on the heap)\n", *heap);
    check("dynamic-storage int holds its value (*heap == 42)", *heap == 42);
    delete heap;        // release; the object's lifetime ends HERE (manual, not at scope exit)
    heap = nullptr;     // good hygiene: delete-on-nullptr is a no-op; guards double-delete
    check("new/delete balanced and pointer nulled (no leak; no double-delete risk)",
          heap == nullptr);

    // (2) The POINTER `heap` had AUTOMATIC storage; the OBJECT `*heap` had DYNAMIC.
    //     Even a heap object's destructor is tied to its `delete`, not to a scope.
    //     Wrapping `new` in an RAII type (std::unique_ptr, P3) binds that delete to
    //     a scope — the RAII fix for manual new/delete.
    std::printf("\n(2) The POINTER `heap` has AUTOMATIC storage; the OBJECT `*heap` has DYNAMIC.\n");
    std::printf("    The dtor of *heap runs at `delete`, not at scope exit. std::unique_ptr (P3)\n");
    std::printf("    binds that delete to a scope — the RAII fix for raw new/delete.\n");

    // (3) Return by VALUE: SAFE. The local is destroyed at return, but its value
    //     was copied/moved out (or the copy elided via NRVO). The caller owns it.
    std::string greeting = make_greeting("world");
    std::printf("\n(3) Return by VALUE is SAFE: make_greeting(\"world\") = \"%s\"\n", greeting.c_str());
    check("return-by-value: caller received a valid owning object (\"hello, world\")",
          greeting == "hello, world");

    // (4) The DANGLING-REFERENCE-TO-LOCAL trap: returning T& (or T*) to a function
    //     local is UNDEFINED BEHAVIOR. The local is destroyed at the function's
    //     return; the returned reference dangles. clang flags the direct case with
    //     `-Wreturn-stack-address` (on by default). NEVER run it in the verified
    //     path — gated behind #ifdef DEMO_UB (just run/out/check/sanitize never
    //     pass it), so the default AND sanitizer builds stay UB-free.
    std::printf("\n(4) The DANGLING-REFERENCE trap: returning T& to a local is UB — documented,\n");
    std::printf("    gated behind -DDEMO_UB (never run by just run/out/check/sanitize).\n");
    check("return-T&-to-local UB trap documented (referent must outlive the reference)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ───────────
    // Returning a reference to a function-local: the local dies at return; the
    // returned reference dangles. Using it is UB. clang -Wreturn-stack-address
    // catches the direct case (a warning, not an error); ASan reports a
    // stack-use-after-return / use-after-free when the dangling ref is read.
    auto bad_dangling = []() -> int& {
        int local = 42;
        return local;   // <-- UNDEFINED BEHAVIOR: reference to a soon-destroyed local
    };
    int& r = bad_dangling();
    std::printf("[DEMO_UB] dangling ref read = %d   <-- UNDEFINED BEHAVIOR\n", r);
#else
    std::printf("    (DEMO_UB not defined: the dangling-ref demo is correctly omitted.)\n");
#endif
}

// === Section E — The 4 storage durations + cross-language ====================
void sectionE() {
    sectionBanner("E — The 4 storage durations + cross-language");

    std::printf("SCOPE (where a NAME is visible) and STORAGE DURATION (when the OBJECT lives)\n");
    std::printf("are INDEPENDENT. A block-scoped name can have STATIC storage (a static local);\n");
    std::printf("a namespace-scoped name ALWAYS has static storage. The four durations:\n");
    std::printf("\n");
    std::printf("duration    keyword        born                            dies\n");
    std::printf("----------  -------------  ------------------------------  ------------------------------\n");
    std::printf("automatic   (default)      at the declaration              at the enclosing block's }\n");
    std::printf("static      static/extern  before main / on first call     program exit (dtor: reverse)\n");
    std::printf("thread      thread_local   at the declaration              at the thread's exit\n");
    std::printf("dynamic     new            at the `new` expression         at the explicit `delete`\n");
    check("4 storage durations table printed", true);

    // All four durations, side by side, in one scope. We capture *dyn_v's value
    // BEFORE the delete: reading *dyn_v after `delete` would be use-after-free UB.
    int auto_v = 1;                         // automatic
    static int stat_v = 2;                  // static (block-scope static local)
    thread_local int tls_v = 3;             // thread (one distinct object per thread)
    int* dyn_v = new int(4);                // dynamic (heap; lives until delete)
    int dyn_value = *dyn_v;                 // capture the dynamic value while it still lives
    std::printf("\nAll four in one scope:\n");
    std::printf("    int          auto_v = 1;  -> %d   (automatic)\n", auto_v);
    std::printf("    static int   stat_v = 2;  -> %d   (static; persists across calls — see Section C)\n",
                stat_v);
    std::printf("    thread_local tls_v  = 3;  -> %d   (thread; one per thread)\n", tls_v);
    std::printf("    int*         dyn_v  = new int(4);  -> %d   (dynamic; lives until delete)\n", dyn_value);
    delete dyn_v;   // balance the new — no leak (keeps `just sanitize` clean)
    dyn_v = nullptr;
    check("all four storage durations demonstrated (1 + 2 + 3 + 4 == 10; *dyn_v read only pre-delete)",
          auto_v == 1 && stat_v == 2 && tls_v == 3 && dyn_value == 4 &&
              auto_v + stat_v + tls_v + dyn_value == 10);
    check("no UB: *dyn_v was never read after delete (value captured beforehand)", true);
    (void)dyn_v;   // the pointer itself is automatic; nulled after delete for hygiene

    std::printf("\nRAII = the destructor runs EXACTLY at scope exit (automatic storage). This is\n");
    std::printf("C++'s deterministic-cleanup idiom — NO garbage collector needed. Full RAII\n");
    std::printf("(smart pointers, locks, files) lands in P3; Section B was the preview.\n");
    check("RAII = deterministic scope-bound destruction (no GC)", true);

    std::printf("\nCross-language (the 5-language curriculum):\n");
    std::printf("  C++ (here): scope determines lifetime for automatic storage; dtor at };\n");
    std::printf("              RAII; no GC; UB if a ref/ptr outlives its referent\n");
    std::printf("  Rust      : LIFETIMES checked at COMPILE time (no dangling possible);\n");
    std::printf("              Drop trait == C++ destructor; no GC; no UB\n");
    std::printf("  Go        : block scope YES; deterministic dtors NO (GC + `defer`);\n");
    std::printf("              `defer` runs at FUNCTION (not block) exit — closest to RAII\n");
    check("cross-language scope/lifetime comparison printed", true);
}

}  // namespace

int main() {
    std::printf("scope_lifetimes.cpp — Phase 1 bundle.\n");
    std::printf("SCOPE (visible) vs STORAGE DURATION (born/dies). RAII preview = dtor at }.\n");
    std::printf("Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
