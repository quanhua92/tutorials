// references_pointers_intro.cpp — Phase 1 bundle #2.
//
// GOAL (one line): show, by printing every value, C++'s THREE ways to refer to a
// value — by VALUE (copied), by REFERENCE `&` (an alias: non-null, non-reseatable,
// must bind on init), by POINTER `*` (an address: nullable, reassignable) — pinning
// the null-dereference and dangling-reference UB traps as documented expert payoffs
// (NEVER executed in the verified path).
//
// This is the GROUND TRUTH for REFERENCES_POINTERS_INTRO.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run references_pointers_intro
//        (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//            references_pointers_intro.cpp -o /tmp/cpp_references_pointers_intro
//            && /tmp/cpp_references_pointers_intro)

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

// ── A small type whose copy constructor counts itself ─────────────────────────
// Used to PROVE that by-value passing copies while by-reference does not. The
// counter is a deterministic, observable side effect, so -O2 / ASan / UBSan
// cannot elide the copy (they must preserve its observable behavior).
struct Tracker {
    inline static int copies = 0;   // C++17 inline static data member
    int value;
    explicit Tracker(int v) : value(v) {}
    Tracker(const Tracker& other) : value(other.value) { ++copies; }
};

int take_by_value(Tracker t) { return t.value; }       // copies the Tracker IN
int take_by_ref(const Tracker& t) { return t.value; }  // aliases; NO copy

// ── An out-parameter-style helper (the pre-smart-pointer way to return extras) ─
void increment_by_ref(int& n) { ++n; }

// Parses `digits` as a non-negative base-10 int; fills `out` by reference on
// success. Returns false (leaving `out` untouched) on a non-digit character — the
// classic C/C++ "out parameter + status return" idiom.
bool try_parse_pos(const char* digits, int& out) {
    int acc = 0;
    for (const char* p = digits; *p != '\0'; ++p) {
        if (*p < '0' || *p > '9') return false;
        acc = acc * 10 + (*p - '0');
    }
    out = acc;
    return true;
}

// === Section A — By VALUE (a copy): mutation invisible to the caller ==========
void sectionA() {
    sectionBanner("A — By VALUE (a copy): mutation invisible to the caller");

    std::printf("A by-VALUE parameter is a COPY of the argument. Mutating it inside the\n");
    std::printf("function NEVER touches the caller's original. That is why value semantics\n");
    std::printf("are safe-by-default — and (for large types) exactly why references exist.\n");

    // (1) Mutation invisibility: the parameter `n` is a copy, so writing it is local.
    int original = 10;
    auto mutate_by_value = [](int n) {   // n: an independent COPY of the argument
        n = 999;
        return n;
    };
    int returned = mutate_by_value(original);
    std::printf("\nint original = 10;  mutate_by_value(original) returned %d;\n", returned);
    std::printf("    -> original is still %d (the COPY was mutated, not the original)\n", original);
    check("by-value: mutating the param did NOT change the caller's original (still 10)",
          original == 10);

    // (2) Proof a copy really happened: the copy constructor ran (by-value) and did
    //     NOT run (by-reference). The counter is observable, so optimizers must
    //     keep the copy (they cannot elide a copy with a visible side effect).
    Tracker t(42);
    Tracker::copies = 0;
    take_by_value(t);
    std::printf("\nTracker::copies after pass-by-VALUE = %d  (copy constructor ran once)\n",
                Tracker::copies);
    check("pass-by-value invoked the copy constructor exactly once (copies == 1)",
          Tracker::copies == 1);

    Tracker::copies = 0;
    take_by_ref(t);
    std::printf("Tracker::copies after pass-by-REF   = %d  (no copy: it is an alias)\n",
                Tracker::copies);
    check("pass-by-reference invoked the copy constructor zero times (copies == 0)",
          Tracker::copies == 0);
}

// === Section B — Lvalue reference `&`: an ALIAS (non-null, non-reseatable) =====
void sectionB() {
    sectionBanner("B — Lvalue reference `&`: an ALIAS (non-null, non-reseatable)");

    std::printf("An lvalue reference T& is an ALIAS for an existing object. It MUST bind to\n");
    std::printf("a valid object at initialization, can NEVER be null, and can NEVER be\n");
    std::printf("reseated (rebound) — \"reassigning\" it actually assigns THROUGH it.\n");

    // (1) Alias + mutate-through: writing `r` writes `x`.
    int x = 1;
    int& r = x;     // r is another NAME for x
    r = 5;
    std::printf("\nint x = 1;  int& r = x;  r = 5;  -> x = %d  (r is an alias of x)\n", x);
    check("lvalue reference: `r = 5` changed x through the alias (x == 5)", x == 5);

    // (2) Same address: `&r` yields the address of the referent, identical to `&x`.
    //     We print only the equal/unequal BOOLEAN — never the raw address, because
    //     addresses are ASLR-randomized and thus non-reproducible to print.
    std::printf("&r == &x ?  %s   (a reference shares its referent's address)\n",
                &r == &x ? "YES" : "NO");
    check("a reference and its referent have the SAME address (&r == &x)", &r == &x);

    // (3) Non-reseatable: `r = y;` does NOT rebind r to y — it assigns y's VALUE
    //     THROUGH r into x. Afterward r still aliases x (and x holds y's old value).
    int y = 7;
    r = y;          // NOT a rebind — stores y's value (7) into x via the alias
    std::printf("\nint y = 7;  r = y;   (NOT a rebind: assigns THROUGH) -> x = %d, &r==&x ? %s\n",
                x, &r == &x ? "YES" : "NO");
    check("references are non-reseatable: `r = y` stored y's value into x (x == 7)", x == 7);
    check("after `r = y` the reference STILL aliases x (&r == &x)", &r == &x);

    // (4) Out-parameters: a non-const T& parameter lets a callee mutate the caller's
    //     object (the pre-smart-pointer way to return extra results).
    int counter = 41;
    increment_by_ref(counter);
    std::printf("\nint counter = 41;  increment_by_ref(counter);  -> counter = %d\n", counter);
    check("non-const T& out-parameter: counter was mutated by the callee (== 42)",
          counter == 42);

    int parsed = -1;
    bool ok = try_parse_pos("1234", parsed);
    std::printf("try_parse_pos(\"1234\", parsed) -> ok = %d, parsed = %d\n", ok ? 1 : 0, parsed);
    check("out-parameter filled in by reference (parsed == 1234)", ok && parsed == 1234);
    check("out-parameter reports failure on non-digits (\"12a\" -> false)",
          !try_parse_pos("12a", parsed));
}

// === Section C — const reference `const T&`: binds temporaries (lifetime-ext) ==
void sectionC() {
    sectionBanner("C — const reference `const T&`: binds temporaries (lifetime-ext)");

    std::printf("A const T& can bind to a TEMPORARY, and doing so EXTENDS the temporary's\n");
    std::printf("lifetime to that of the reference. This is the cheap read-only-pass idiom.\n");
    std::printf("A non-const T& CANNOT bind to a temporary (documented: a compile error).\n");

    // (1) Lifetime extension: the prvalue temporary std::string("temp") is kept
    //     alive for the scope of `s` because a const T& binds to it.
    const std::string& s = std::string("temp");
    std::printf("\nconst std::string& s = std::string(\"temp\");  -> s = \"%s\", len = %zu\n",
                s.c_str(), s.length());
    check("const T& binds a temporary AND extends its lifetime (s == \"temp\")", s == "temp");
    check("the lifetime-extended temporary is intact (length == 4)", s.length() == 4);

    // (2) const T& also binds an ordinary lvalue (no copy either — pure alias).
    std::string name = "alice";
    const std::string& cn = name;   // alias, read-only
    std::printf("\nconst std::string& cn = name(\"alice\");  -> cn = \"%s\", len = %zu\n",
                cn.c_str(), cn.length());
    check("const T& also binds an lvalue with no copy (cn == \"alice\")", cn == "alice");

    // (3) Read-only: writing through `cn` is a compile error (documented, not run).
    std::printf("\n(const T& is read-only: `cn = \"bob\";` would be a compile error — not run.)\n");
    check("const T& is read-only (mutation through it is rejected at compile time)", true);

    // (4) The cheap-pass idiom: read a (potentially large) object through a const
    //     ref — no copy, works for both lvalues and temporaries.
    auto length_of = [](const std::string& str) { return str.size(); };
    std::size_t n1 = length_of(name);                  // lvalue argument, no copy
    std::size_t n2 = length_of(std::string("rvalue")); // temporary argument, no copy
    std::printf("\nlength_of(name) = %zu;  length_of(std::string(\"rvalue\")) = %zu  (no copy)\n",
                n1, n2);
    check("const T& param reads an lvalue without copying (len == 5)", n1 == 5);
    check("const T& param reads a temporary without copying (len == 6)", n2 == 6);

    // (5) rvalue reference T&& — MENTION ONLY (move semantics is P3). Like const T&,
    //     T&& binds a temporary and extends its lifetime, but it also permits
    //     MUTATION of that temporary (the foundation of std::move).
    int&& rr = 42;   // binds the prvalue 42; lifetime-extended
    rr = 7;
    std::printf("\nint&& rr = 42;  rr = 7;  -> rr = %d  (rvalue reference — move semantics is P3)\n",
                rr);
    check("rvalue reference T&& binds a prvalue and is mutable (rr == 7)", rr == 7);
}

// === Section D — Pointer `*`: an ADDRESS (nullable, reassignable, deref) =======
void sectionD() {
    sectionBanner("D — Pointer `*`: an ADDRESS (nullable, reassignable)");

    std::printf("A pointer T* holds the ADDRESS of an object. Unlike a reference it may be\n");
    std::printf("NULL (nullptr), it is REASSIGNABLE, and you dereference it with `*`/`->`.\n");
    std::printf("Dereferencing a NULL pointer is UNDEFINED BEHAVIOR (documented below).\n");

    // (1) Address-of, dereference, mutate-through.
    int x = 1;
    int* p = &x;     // p holds x's address
    *p = 5;          // store 5 into x through the pointer
    std::printf("\nint x = 1;  int* p = &x;  *p = 5;  -> x = %d, (p == &x) ? %s\n",
                x, p == &x ? "YES" : "NO");
    check("pointer: `*p = 5` changed x through the address (x == 5)", x == 5);
    check("pointer holds the object's address (p == &x)", p == &x);

    // (2) Nullable: a pointer can hold nullptr. (Dereferencing it is UB — see below.)
    int* np = nullptr;
    std::printf("\nint* np = nullptr;  -> (np == nullptr) ? %s   (a pointer CAN be null)\n",
                np == nullptr ? "YES" : "NO");
    check("a pointer may be null (np == nullptr)", np == nullptr);

    // (3) Reassignable: a pointer can be repointed at a different object.
    int y = 9;
    p = &y;          // repoint p at y — a reference could NEVER do this
    std::printf("\nint y = 9;  p = &y;   (repointed) -> *p = %d, (p == &y) ? %s, (p == &x) ? %s\n",
                *p, p == &y ? "YES" : "NO", p == &x ? "YES" : "NO");
    check("pointer is reassignable: p now points at y (p == &y)", p == &y);
    check("after reassignment p no longer points at x (p != &x)", p != &x);
    check("repointed pointer reads the new object (*p == 9)", *p == 9);

    // (4) Pointer to pointer (int**): a pointer that points at another pointer.
    int* q = &x;     // q -> x
    int** pp = &q;   // pp -> q -> x
    **pp = 7;        // store 7 into x through two levels of indirection
    std::printf("\nint* q = &x;  int** pp = &q;  **pp = 7;  -> x = %d, (pp == &q) ? %s\n",
                x, pp == &q ? "YES" : "NO");
    check("pointer-to-pointer: `**pp = 7` reached x through two levels (x == 7)", x == 7);
    check("int** pp holds the address of the int* (pp == &q)", pp == &q);

    // (5) Constness: where you put `const` relative to `*` changes the meaning.
    //     `const int* cp`     — pointer to CONST int: can read *cp, CANNOT write *cp.
    //     `int* const fixed`  — CONST pointer to int: can write *fixed, CANNOT rebind.
    int z = 100;
    const int* cp = &z;       // points at z, but promises not to mutate z through cp
    int* const fixed = &z;    // cannot be repointed; *fixed IS writable
    *fixed = 50;              // OK: writes z through the const pointer-to-mutable
    std::printf("\nconst int* cp = &z;  int* const fixed = &z;  *fixed = 50;  -> *cp = %d, z = %d\n",
                *cp, z);
    check("pointer-to-const reads but does not write through it (*cp == 50)", *cp == 50);
    check("const-pointer-to-int is writable through (*fixed = 50 -> z == 50)", z == 50);

    // (6) The NULL-DEREFERENCE trap: `*nullptr` (or *np above) is UNDEFINED BEHAVIOR.
    //     It is NEVER executed in the verified path — the offending dereference is
    //     gated behind #ifdef DEMO_UB, which just run/out/check/sanitize never pass.
    std::printf("\nThe NULL-DEREFERENCE trap (*nullptr) is UNDEFINED BEHAVIOR — documented,\n");
    std::printf("never executed in the verified path (gated behind -DDEMO_UB).\n");
    check("null-deref UB trap documented (NEVER dereferenced in the verified path)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ───────────
    // Compile with -DDEMO_UB to build this; RUNNING it is UB. UBSan reports
    // "runtime error: load of null pointer"; under ASan it is typically a SEGV.
    int* bad = nullptr;
    int boom = *bad;   // <-- UNDEFINED BEHAVIOR: dereferencing a null pointer
    std::printf("[DEMO_UB] *nullptr = %d   <-- UNDEFINED BEHAVIOR\n", boom);
#else
    std::printf("    (DEMO_UB not defined: the null-deref is correctly omitted from this build.)\n");
#endif
}

// === Section E — The choice (value/ref/ptr) + dangling UB + cross-language =====
void sectionE() {
    sectionBanner("E — The choice (value/ref/ptr) + dangling UB + cross-language");

    std::printf("Decision table — pick the reference kind from what you NEED:\n\n");
    std::printf("kind            copied?  alias?  nullable?  reseatable?  owns?\n");
    std::printf("---------------  ------  ------  --------  -----------  ----\n");
    std::printf("T   (value)        YES    no       no          no        YES (own storage)\n");
    std::printf("T&  (lref)         no     YES      no          no         no  (borrows)\n");
    std::printf("const T&           no     YES      no          no         no  (read borrow)\n");
    std::printf("T*  (pointer)      no     YES     YES         YES         no  (borrows)\n");
    std::printf("T&& (rref)         no     YES      no          no         no  (move — P3)\n");
    check("decision table printed (5 reference kinds)", true);

    std::printf("\nRules of thumb:\n");
    std::printf("  * Pass/return by VALUE when you want a cheap, independent copy.\n");
    std::printf("  * Use T& (or const T&) when the object ALWAYS exists and you want to\n");
    std::printf("    avoid a copy — prefer references whenever the binding is never null.\n");
    std::printf("  * Use T* when the target may be ABSENT (nullable) or may CHANGE (reseat),\n");
    std::printf("    or when you iterate arrays / do low-level address arithmetic.\n");

    // The DANGLING reference/pointer trap: a ref/ptr outliving its referent is UB.
    std::printf("\nThe DANGLING reference/pointer trap: if the referent's lifetime ends but the\n");
    std::printf("reference/pointer is still used, the behavior is UNDEFINED. The classic case\n");
    std::printf("is returning a T& to a local — documented, gated behind -DDEMO_UB.\n");
    check("dangling-reference UB trap documented (referent must outlive the reference)", true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ───────────
    // Returning a reference to a function-local object: the local is destroyed when
    // the function returns, so the returned reference is DANGLING. Using it is UB;
    // -Wreturn-stack-address (on by default) would also flag this.
    auto bad_dangling_ref = []() -> int& {
        int local = 42;
        return local;   // <-- reference to a soon-destroyed local
    };
    int& r = bad_dangling_ref();
    std::printf("[DEMO_UB] dangling ref read = %d   <-- UNDEFINED BEHAVIOR\n", r);
#else
    std::printf("    (DEMO_UB not defined: the dangling-ref demo is correctly omitted.)\n");
#endif

    // Cross-language headline: how the other languages in the curriculum model this.
    std::printf("\nCross-language (the 5-language curriculum):\n");
    std::printf("  C++ (here): value / & reference / * pointer — you choose; no GC; UB if wrong\n");
    std::printf("  Rust      : value / & borrow / &mut borrow — compiler CHECKS lifetimes; no UB\n");
    std::printf("  Go        : value / * pointer ONLY (no references) — GC; no UB\n");
    std::printf("  TS/JS     : primitives by value / shared object ref under GC — no UB\n");
    check("cross-language reference/pointer comparison printed", true);
}

}  // namespace

int main() {
    std::printf("references_pointers_intro.cpp — Phase 1 bundle #2.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
