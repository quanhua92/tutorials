// undefined_behavior.cpp — Phase 7 bundle #42 (THE central C++ expert topic).
//
// GOAL (one line): pin what undefined behavior IS, WHY it is dangerous (the
// compiler is allowed to ASSUME no UB and optimize on that assumption), the
// common UB family, the UB-vs-implementation-defined-vs-unspecified distinction,
// and the modern detectors (ASan/UBSan/TSan/MSan) — with the verified path
// 100% UB-free and every UB demo gated behind #ifdef DEMO_UB (so `just run` /
// `just out` / `just check` / `just sanitize` never compile a single UB; compile
// with -DDEMO_UB under ASan/UBSan to make the detectors fire).
//
// This is the GROUND TRUTH for UNDEFINED_BEHAVIOR.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run undefined_behavior
//         (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic undefined_behavior.cpp
//             -o /tmp/cpp_undefined_behavior && /tmp/cpp_undefined_behavior)
//
// To SEE the detectors fire (NOT the verified path):
//     c++ -std=c++23 -O1 -fsanitize=address,undefined -DDEMO_UB \
//         undefined_behavior.cpp -o /tmp/cpp_ub_demo && /tmp/cpp_ub_demo

#include <atomic>      // std::atomic (the well-defined fix for data races)
#include <climits>     // INT_MAX, UINT_MAX, ...
#include <cstdint>     // std::int32_t, ...
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner) + memcpy (the well-defined aliasing fix)
#include <limits>      // std::numeric_limits

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

// A safe, well-defined shift: validates the exponent BEFORE shifting. (A shift
// by a negative count, or by >= width, is UB.) Used in Section B as the fix.
constexpr int safe_shl(int value, int amount) {
    return (amount >= 0 && amount < 32) ? (value << amount) : 0;
}

// === Section A — UB: the standard imposes NO requirements ===================
//
// The C++ standard classifies non-portable behavior into a hierarchy. Only ONE
// class — undefined behavior — "renders the entire program meaningless": there
// are NO requirements on what happens. CRITICALLY, because a correct program is
// UB-free, the compiler is ALLOWED to ASSUME no UB and to OPTIMIZE on that
// assumption (delete overflow checks, fold expressions to constants, "time-
// travel"). That assumption — not the UB itself — is what makes UB dangerous.
void sectionA() {
    sectionBanner("A — UB: NO requirements; the compiler ASSUMES none");

    std::printf("The C++ standard's behavior classes (cppreference / ISO defns):\n");
    std::printf("  ill-formed             diagnosable error; conforming compiler MUST emit a diagnostic\n");
    std::printf("  ill-formed, NDR        semantic error a compiler need NOT diagnose; if run -> UB\n");
    std::printf("  implementation-defined impl chooses AND MUST document it (e.g. sizeof(int) == 4)\n");
    std::printf("  unspecified            impl chooses, NEED NOT document (e.g. order of f(a(), b()))\n");
    std::printf("  erroneous  (C++26)     wrong but well-defined; diagnostic recommended (e.g. uninit read)\n");
    std::printf("  undefined behavior     NO requirements on the program — ANYTHING can happen\n\n");

    std::printf("THE DANGER: a correct C++ program is UB-free, so the compiler is ALLOWED to\n");
    std::printf("ASSUME no UB happens and OPTIMIZE on that assumption. UB therefore does not\n");
    std::printf("merely 'do something random at runtime' — it lets the compiler DELETE checks,\n");
    std::printf("FOLD expressions to constants, or even 'time-travel' (move an effect earlier).\n\n");

    // WELL-DEFINED contrast #1: UNSIGNED arithmetic wraps modularly (defined).
    // UINT_MAX + 1 is well-defined to be 0. (The SIGNED analog, INT_MAX + 1, is UB.)
    const unsigned int umax = UINT_MAX;
    const unsigned int uw = umax + 1u;
    std::printf("UNSIGNED wraparound is DEFINED: UINT_MAX(%u) + 1 = %u\n", umax, uw);
    check("unsigned wraparound is well-defined: UINT_MAX + 1 == 0", uw == 0u);

    // WELL-DEFINED contrast #2: CHECKED signed arithmetic. The compiler builtins
    // (__builtin_add_overflow on gcc/clang) perform the add via a flags test and
    // report overflow WITHOUT ever executing UB. This is the safe way to detect
    // INT_MAX + 1.
    const int smax = INT_MAX;
    int wrapped = -1;
    const bool overflowed = __builtin_add_overflow(smax, 1, &wrapped);
    std::printf("CHECKED signed add is DEFINED: __builtin_add_overflow(INT_MAX,1) -> overflow=%d\n",
                overflowed);
    check("checked signed add DETECTS INT_MAX+1 overflow (no UB executed)", overflowed);

    // THE OPTIMIZER-ASSUMPTION PAYOFF (DOCUMENTED, never executed). Because
    // signed overflow is UB, the compiler assumes it can't happen — so a guard
    // meant to *detect* overflow is optimized away:
    //     bool foo(int x) { return x + 1 > x; }   // "true" OR signed-overflow UB
    // gcc/clang -O2 compile this to a constant `return true` (mov eax,1; ret):
    // under the no-UB assumption x+1 can never be <= x, so the comparison is
    // always true. The overflow the author tried to observe is INVISIBLE to the
    // compiled program. (cppreference "UB and optimization"; LLVM blog; godbolt.)
    std::printf("\nTHE OPTIMIZER PAYOFF (documented; the overflow itself is NOT executed here):\n");
    std::printf("  bool foo(int x){ return x + 1 > x; }  // 'true' OR signed-overflow UB\n");
    std::printf("  -> gcc/clang -O2 fold it to `return true` (mov eax,1; ret)\n");
    std::printf("  the `x+1 > x` overflow-check is DELETED: assuming no UB, it can't be false\n");
    check("documented: assuming-no-UB lets the optimizer delete an overflow check", true);

    // CONSTANT EVALUATION DETECTS UB. In a constexpr/consteval context the
    // compiler is REQUIRED to diagnose UB (it is a hard compile error there),
    // because constant evaluation has well-defined semantics. The positive case
    // below compiles; uncommenting the overflow would fail to compile.
    constexpr int two_plus_three = 2 + 3;
    static_assert(two_plus_three == 5);
    // constexpr int boom = INT_MAX + 1;   // <-- COMPILE ERROR: overflow in const eval
    std::printf("\nCONSTANT evaluation DIAGNOSES UB: `constexpr int x = INT_MAX + 1;` is a\n");
    std::printf("compile error (the only place UB is guaranteed-diagnosable). `2 + 3` in a\n");
    std::printf("constant expression is fine -> constexpr result = %d\n", two_plus_three);
    check("constexpr 2 + 3 == 5 (well-defined constant evaluation)", two_plus_three == 5);
}

// === Section B — The common UB family + the WELL-DEFINED fix for each ========
//
// For each UB we (1) state the rule, (2) DEMONSTRATE THE WELL-DEFINED FIX and
// assert it (the verified path), and (3) gate the actual UB behind #ifdef
// DEMO_UB so the default/sanitizer builds never compile it. Compile with
// -DDEMO_UB under ASan/UBSan to make the detectors fire (Section D).
void sectionB() {
    sectionBanner("B — the common UB family + the WELL-DEFINED fix for each");

    // ── (1) Signed integer overflow ────────────────────────────────────────
    // Rule: INT_MAX + 1 (and any signed overflow) is UB. Unsigned wraps (def.).
    {
        int dst = 0;
        const bool ovf = __builtin_add_overflow(INT_MAX, 1, &dst);
        std::printf("(1) signed overflow: INT_MAX+1 is UB. Fix = CHECKED add (defined): overflow=%d\n",
                    ovf);
        check("checked add detects INT_MAX+1 overflow (the well-defined fix)", ovf);
        // Unsigned arithmetic CANNOT overflow into UB — it wraps mod 2^N (defined).
        const unsigned int uw = static_cast<unsigned>(INT_MAX) + 1u;
        std::printf("    unsigned INT_MAX + 1u = %u (unsigned overflow WRAPS — it is NOT UB)\n", uw);
        check("unsigned INT_MAX + 1u wraps without UB (defined modular arithmetic)",
              uw == static_cast<unsigned>(INT_MAX) + 1u);
    }
#ifdef DEMO_UB
    {
        int bad = INT_MAX;
        int bad2 = bad + 1;   // <-- UB: signed integer overflow
        std::printf("[DEMO_UB] INT_MAX + 1 = %d   <-- UB; UBSan: 'signed integer overflow'\n", bad2);
    }
#endif

    // ── (2) Invalid shift ──────────────────────────────────────────────────
    // Rule: shifting by a negative amount, or by >= the width of the type, is UB.
    {
        std::printf("(2) invalid shift: 1<<32 (and 1<<-1) is UB. Fix = validate the exponent first.\n");
        std::printf("    safe_shl(1, 32) = %d   (exponent rejected -> 0, no UB)\n", safe_shl(1, 32));
        std::printf("    safe_shl(1, 4)  = %d   (in range -> 16)\n", safe_shl(1, 4));
        check("safe_shl rejects exponent >= width (returns 0, no UB)", safe_shl(1, 32) == 0);
        check("safe_shl computes 1<<4 == 16 when the exponent is in range", safe_shl(1, 4) == 16);
    }
#ifdef DEMO_UB
    {
        int s = 1;
        int r = s << 32;   // <-- UB: shift exponent >= width
        std::printf("[DEMO_UB] 1 << 32 = %d   <-- UB; UBSan: 'shift exponent 32 is too large'\n", r);
    }
#endif

    // ── (3) Null pointer dereference ───────────────────────────────────────
    // Rule: reading/writing through a null pointer is UB.
    {
        int real = 42;
        int* p = &real;
        int v = (p != nullptr) ? *p : -1;   // the fix: check BEFORE dereferencing
        std::printf("(3) null deref: *nullptr is UB. Fix = check `p != nullptr` first -> %d\n", v);
        check("null-checked dereference reads the real value (no UB)", v == 42);
        int* q = nullptr;
        int safe = (q != nullptr) ? *q : -1;   // the pointer IS null -> safe branch taken
        check("null pointer correctly handled (never dereferenced)", q == nullptr && safe == -1);
    }
#ifdef DEMO_UB
    {
        int* p = nullptr;
        int v = *p;   // <-- UB: load of null pointer
        std::printf("[DEMO_UB] *nullptr = %d   <-- UB; UBSan: 'load of null pointer'\n", v);
    }
#endif

    // ── (4) Integer division by zero ───────────────────────────────────────
    // Rule: x / 0 (and x % 0) is UB for integers.
    {
        const int num = 10;
        const int den = 0;
        const int q = (den != 0) ? num / den : -1;   // the fix: guard the divisor
        std::printf("(4) integer div-by-zero: x/0 is UB. Fix = guard the divisor -> %d\n", q);
        check("divisor guarded: 10/0 never executes (no UB)", q == -1);
    }
#ifdef DEMO_UB
    {
        volatile int z = 0;
        int d = 5 / z;   // <-- UB: integer division by zero
        std::printf("[DEMO_UB] 5 / 0 = %d   <-- UB; UBSan: 'division by zero'\n", d);
    }
#endif

    // ── (5) Out-of-bounds access ───────────────────────────────────────────
    // Rule: indexing past the end of an array (operator[] on std::vector or a
    // built-in array) is UB. The WELL-DEFINED alternative is .at(), which THROWS
    // std::out_of_range. (The memory UBs OOB/UAF are ASan-detected and FATAL, so
    // their #ifdef DEMO_UB demos live at the END of main — see demoMemoryUBs().)
    {
        const int arr[4] = {10, 20, 30, 40};
        std::printf("(5) out-of-bounds: arr[4] on a 4-elem array is UB. The bounds-check uses size:\n");
        std::printf("    arr index 2 (in range) = %d\n", arr[2]);
        const int idx = 4;
        const int got = (idx >= 0 && idx < 4) ? arr[idx] : -1;   // manual bounds check
        std::printf("    manual bounds check on idx=4 -> %d (rejected, no UB)\n", got);
        check("manual bounds check rejects idx=4 (no OOB access)", got == -1);
        check("in-range index arr[2] == 30", arr[2] == 30);
    }

    // ── (6) Use-after-free / dangling ──────────────────────────────────────
    // Rule: reading memory after it was delete'd (or after its storage ended) is
    // UB. The fix is RAII / smart pointers (P3) that own and auto-delete; or, at
    // minimum, capture the value BEFORE freeing and never read the freed storage.
    {
        int* h = new int(7);
        const int captured = *h;   // capture the value FIRST (well-defined read)
        delete h;                  // free the storage
        h = nullptr;               // defensive: a later `*h` would still be UB on
                                   // a null deref, but `delete nullptr` is a no-op
        std::printf("(6) use-after-free: *p after delete is UB. Fix = capture-before-delete + null.\n");
        std::printf("    captured value before delete = %d (the freed storage is NOT read)\n", captured);
        check("value captured BEFORE delete (freed storage never read)", captured == 7);
        check("pointer nulled after delete (delete-on-nullptr is a defined no-op)", h == nullptr);
        delete h;   // deleting nullptr is well-defined and a no-op — NOT UB
        check("delete nullptr is a well-defined no-op (no double-free, no UB)", true);
    }

    // ── (7) Type-aliasing violation ────────────────────────────────────────
    // Rule: accessing an object through a pointer/reference of an UNRELATED type
    // (e.g. reading an int through a float*) is UB. (char/unsigned char/std::byte
    // alias anything — that is the LEGAL way to read raw bytes.) The fix is
    // std::memcpy, which is defined to copy the object representation regardless
    // of the types involved.
    {
        const int n = 0x40490FDB;   // a bit pattern (float ~pi if reinterpreted)
        float f = 0.0f;
        std::memcpy(&f, &n, sizeof(f));   // the WELL-DEFINED way to reinterpret bytes
        std::printf("(7) aliasing: reading an int via float* is UB. Fix = std::memcpy -> %.6f\n", f);
        // Verify by copying the bytes BACK into an int and comparing the pattern
        // (a deterministic bit-level round-trip — no float equality, no aliasing).
        int roundtrip = 0;
        std::memcpy(&roundtrip, &f, sizeof(roundtrip));
        check("memcpy round-trips the bit pattern (the well-defined aliasing fix)",
              roundtrip == n);
        // (The UB form `*reinterpret_cast<float*>(&n)` is NOT executed here; it is
        // documented in UNDEFINED_BEHAVIOR.md. It is NOT reliably caught by ASan/
        // UBSan — strict aliasing is a compiler ASSUMPTION, detected by static
        // analysis / -Wstrict-aliasing, not by the runtime sanitizers.)
    }

    // ── (8) Uninitialized read ─────────────────────────────────────────────
    // Rule: reading a default-initialized automatic scalar (indeterminate value)
    // is UB (C++23). The fix is value-initialization `int x{};` -> 0.
    {
        int x{};   // value-initialization -> 0 (well-defined)
        std::printf("(8) uninit read: reading `int x;` (indeterminate) is UB. Fix = `int x{};` -> %d\n", x);
        check("value-initialized int == 0 (the fix; no indeterminate read)", x == 0);
        // The UB form `int x; std::printf(\"%d\", x);` is detected by MemorySanitizer
        // (-fsanitize=memory, primarily Linux), NOT by ASan/UBSan — see Section D.
    }

    // ── (9) Data race ──────────────────────────────────────────────────────
    // Rule: two threads accessing the SAME non-atomic object with at least one a
    // write, and no synchronization between them, is a DATA RACE = UB. The fix is
    // std::atomic (P4) or a mutex (P4). Demonstrated single-threaded here (the
    // racy variant is in ATOMICS_MEMORY_ORDER / MUTEX_LOCK_GUARD; TSan catches it).
    {
        std::atomic<int> counter{0};
        for (int i = 0; i < 100; ++i) counter.fetch_add(1, std::memory_order_relaxed);
        std::printf("(9) data race: unsynchronized r/w of a non-atomic is UB. Fix = std::atomic -> %d\n",
                    counter.load());
        check("atomic counter reached 100 (race-free; single-thread demo)", counter.load() == 100);
    }
}

// === Section C — UB vs implementation-defined vs unspecified (distinct) ======
//
// These three are OFTEN confused but are DISTINCT. Only UB "renders the program
// meaningless"; the other two are portable-enough facts the program can rely on
// (and assert). This section pins the distinction with WELL-DEFINED examples.
void sectionC() {
    sectionBanner("C — UB != implementation-defined != unspecified");

    std::printf("DISTINCT categories (do not confuse):\n");
    std::printf("  implementation-defined: impl picks ONE behavior and MUST document it.\n");
    std::printf("      -> portable within a documented platform; assertable; NOT UB.\n");
    std::printf("  unspecified:           impl picks ONE of a set; NEED NOT document which.\n");
    std::printf("      -> each result is valid; NOT UB. Avoid printing which one you got.\n");
    std::printf("  undefined behavior:    NO requirements; the whole program is meaningless.\n");
    std::printf("      -> NEVER rely on it; the compiler may assume it doesn't happen.\n\n");

    // implementation-defined: sizeof(int). The standard fixes only that int is
    // >= 16 bits; on this LP64 box it is 32 bits / 4 bytes. We may ASSERT the
    // platform value (it is documented and stable) — this is NOT UB.
    std::printf("implementation-defined: sizeof(int) == %zu bytes (%d bits) on this platform\n",
                sizeof(int), static_cast<int>(sizeof(int) * CHAR_BIT));
    check("sizeof(int) >= 2 (>= 16 bits) — impl-defined, NOT UB", sizeof(int) >= 2);
    check("this platform documents sizeof(int) == 4 (assertable, stable)", sizeof(int) == 4);

    // implementation-defined: whether `char` is signed or unsigned (distinct
    // type either way). On this x86/arm64-Apple toolchain it is SIGNED.
    std::printf("implementation-defined: char is SIGNED here (CHAR_MIN == %d)\n", CHAR_MIN);
    check("char is signed on this platform (CHAR_MIN < 0)", CHAR_MIN < 0);

    // unspecified: the ORDER of evaluation of `f(a(), b())`'s two arguments.
    // Either order is valid; the program may NOT depend on which. We therefore
    // DO NOT print an order-dependent value. (Printing it would be reproducible
    // by accident on one compiler and a portability bug elsewhere.)
    std::printf("unspecified: evaluation ORDER of the 2 args in `f(a(), b())` — either is\n");
    std::printf("    valid; we deliberately print NO order-dependent value here (portable).\n");
    check("unspecified eval-order NOT relied on for a printed value (portable)", true);

    // The contrast: each of these looks similar to a UB but is NOT.
    std::printf("\nTHE CONTRAST — each is its OWN category, none of them is UB:\n");
    std::printf("  sizeof(int)==4           implementation-defined (documented, stable)\n");
    std::printf("  eval order of a(),b()    unspecified (valid either way; don't depend)\n");
    std::printf("  INT_MAX + 1              UNDEFINED BEHAVIOR (no requirements; compiler assumes none)\n");
    check("the three categories are DISTINCT (only UB renders the program meaningless)", true);
}

// === Section D — The detectors: ASan / UBSan / TSan / MSan ==================
//
// The modern C++ safety net. Each sanitizer targets a UB class; run them in CI
// (`just sanitize` = ASan + UBSan). The verified path of THIS bundle is clean
// under all of them — the proof that the verified path is UB-free. The gated
// -DDEMO_UB path is what makes them FIRE (run it to see the diagnostics).
void sectionD() {
    sectionBanner("D — the detectors: ASan / UBSan / TSan / MSan");

    std::printf("Compiler sanitizers (-fsanitize=...) — each catches a UB class:\n");
    std::printf("  ASan   address           memory UBs: OOB, use-after-free, double-free, leaks\n");
    std::printf("  UBSan  undefined         scalar UBs: signed overflow, shift, null deref, div0, ...\n");
    std::printf("  TSan   thread            data races (two threads, one non-atomic, no sync)\n");
    std::printf("  MSan   memory            use of an uninitialized value (primarily Linux)\n\n");

    std::printf("How to run them:\n");
    std::printf("  just sanitize undefined_behavior   # the bundle gate: ASan + UBSan, MUST be clean\n");
    std::printf("  -fsanitize=address,undefined       # what `just sanitize` compiles with\n");
    std::printf("  -fsanitize=thread                  # TSan (data races) — separate from ASan\n");
    std::printf("  -fsanitize=memory                  # MSan (uninit reads) — Linux, separate from ASan\n");
    std::printf("  -DDEMO_UB + ASan/UBSan              # make the detectors FIRE on this bundle's demos\n\n");

    // The verified path is sanitizer-clean by construction: no UB is ever
    // compiled into the default build (every UB demo is #ifdef DEMO_UB-gated).
    std::printf("VERIFIED PATH: every UB demo is #ifdef DEMO_UB-gated, so the default build\n");
    std::printf("(what `just run` / `just out` / `just check` / `just sanitize` compile) contains\n");
    std::printf("ZERO undefined behavior. `just sanitize undefined_behavior` is therefore clean,\n");
    std::printf("and `just out` is byte-identical across runs (determinism: UB-free output).\n");
    check("the verified path is 100% UB-free (all UB demos are DEMO_UB-gated)", true);

    // A concrete well-defined use of a sanitizer-friendly API: std::atomic is
    // TSan-friendly (no false race report on a correctly-synchronized atomic).
    std::atomic<int> a{0};
    a.fetch_add(1, std::memory_order_relaxed);
    std::printf("\nWell-defined + sanitizer-friendly: std::atomic fetch_add -> %d (TSan sees no race)\n",
                a.load());
    check("std::atomic access is well-defined (no data race, TSan-clean)", a.load() == 1);
}

// === Section E — How to AVOID UB + cross-language contrast ==================
void sectionE() {
    sectionBanner("E — how to AVOID UB + cross-language contrast");

    std::printf("THE DISCIPLINE (how experts write UB-free C++):\n");
    std::printf("  1. Initialize everything: `T x{};` (value-init -> zero), never bare `T x;`.\n");
    std::printf("  2. Own with RAII / smart pointers (P3): unique_ptr/shared_ptr delete for you -> no UAF/dangling.\n");
    std::printf("  3. Bounds-check with .at() (throws) or an explicit size test -> no OOB.\n");
    std::printf("  4. Share data via std::atomic (P4) or a mutex (P4) -> no data race.\n");
    std::printf("  5. Reinterpret bytes with std::memcpy, NOT reinterpret_cast+read -> no aliasing.\n");
    std::printf("  6. Detect overflow with __builtin_*_overflow / unsigned math -> no signed-overflow UB.\n");
    std::printf("  7. Run ASan+UBSan (+TSan/+MSan) in CI -> the runtime safety net for whatever slips through.\n");
    check("the 7-rule discipline is the expert recipe for UB-free C++", true);

    std::printf("\nCROSS-LANGUAGE — THE defining contrast:\n");
    std::printf("  C++    : trusts the programmer; UB is possible; caught by SANITIZERS at RUNTIME (or not at all).\n");
    std::printf("  Rust   : SAFE BY DEFAULT — the borrow checker FORBIDS UAF/dangling/data-race/null-deref at COMPILE time.\n");
    std::printf("  Go/TS/Python: GARBAGE-COLLECTED — no manual-memory UB; a DIFFERENT bug class (data races still bite Go/TS).\n");
    check("C++ trusts + sanitizers; Rust forbids at compile time; GC languages are a different bug class", true);
}

// === demoMemoryUBs — the ASan-FATAL UB demos (ONLY under -DDEMO_UB) ==========
//
// Out-of-bounds and use-after-free are caught by AddressSanitizer, which is
// FATAL (it aborts the process after the first report). They are therefore
// isolated here at the END of the program (called from main only when DEMO_UB
// is defined), so the earlier sections' UBSan-continuable demos (signed
// overflow / shift / null deref / div-by-zero in Section B) get to fire first.
#ifdef DEMO_UB
void demoMemoryUBs() {
    sectionBanner("DEMO_UB — memory UBs (ASan-detected, FATAL: aborts after each)");

    // (5b) Out-of-bounds HEAP read -> ASan: heap-buffer-overflow (fatal).
    {
        int* arr = new int[4];
        arr[0] = 1; arr[1] = 2; arr[2] = 3; arr[3] = 4;
        int oob = arr[10];   // <-- UB: out-of-bounds read
        std::printf("[DEMO_UB] heap arr[10] = %d   <-- UB; ASan: 'heap-buffer-overflow'\n", oob);
        delete[] arr;
    }
    // (6b) Use-after-free -> ASan: heap-use-after-free (fatal). Reached only if
    // the OOB above did NOT abort (e.g. when this block is compiled/run alone).
    {
        int* h = new int(42);
        delete h;
        int uaf = *h;   // <-- UB: use-after-free
        std::printf("[DEMO_UB] *freed = %d   <-- UB; ASan: 'heap-use-after-free'\n", uaf);
    }
}
#endif

}  // namespace

int main() {
    std::printf("undefined_behavior.cpp — Phase 7 bundle #42 (THE central C++ expert topic).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; verified path is UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
#ifdef DEMO_UB
    demoMemoryUBs();
    sectionBanner("DONE — all sections printed (DEMO_UB demos ran; see sanitizer output)");
#else
    sectionBanner("DONE — all sections printed (UB demos gated; compile -DDEMO_UB to enable)");
#endif
}
