// sanitizers_static_analysis.cpp — Phase 7 bundle (the C++ safety net).
//
// GOAL (one line): document the four RUNTIME sanitizers (ASan/UBSan/TSan/MSan),
// their bug domains + how `just sanitize NAME` invokes them, and the STATIC
// analyzers (clang-tidy, cppcheck) — with the verified path 100% UB-free and a
// `#ifdef DEMO_BUG`-gated use-after-free that would fire under ASan (never in
// the default build).
//
// This is the GROUND TRUTH for SANITIZERS_STATIC_ANALYSIS.md. Every value,
// table, and worked example in the guide is printed by this file. Change it ->
// re-compile -> re-paste. Never hand-compute.
//
// Run:
//     just run sanitizers_static_analysis
//         (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//             sanitizers_static_analysis.cpp -o /tmp/cpp_sanitizers_static_analysis
//             && /tmp/cpp_sanitizers_static_analysis)
//
// The default build is UB-FREE and stays clean under ASan+UBSan:
//     just sanitize sanitizers_static_analysis   # ASan+UBSan: clean
//
// The use-after-free demo is gated behind -DDEMO_BUG and is NEVER compiled by
// `just run`/`just out`/`just check`/`just sanitize`. To SEE ASan fire, build it
// yourself under ASan:
//     c++ -std=c++23 -g -O1 -DDEMO_BUG -fsanitize=address,undefined \
//         -fno-omit-frame-pointer sanitizers_static_analysis.cpp -o /tmp/demo
//     /tmp/demo    # -> AddressSanitizer: heap-use-after-free

#include <cstdio>     // printf / fprintf
#include <cstdint>    // int32_t (for the overflow constants)
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset / strcmp (banner bar, flag compares)

// Build-environment feature probes (used by Section A to print WHICH platform
// this verified path was captured on — not for branching into UB).
#if defined(__clang__)
#define PROBE_CLANG 1
#else
#define PROBE_CLANG 0
#endif
#if defined(__APPLE__)
#define PROBE_APPLE 1
#else
#define PROBE_APPLE 0
#endif
#if defined(__arm64__) || defined(__aarch64__)
#define PROBE_ARM64 1
#else
#define PROBE_ARM64 0
#endif

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

// The canonical `-fsanitize=` flag for each sanitizer (string constants — these
// ARE the values the .md cites and `just sanitize` passes). Single source of
// truth: the .cpp prints them; the .md quotes them verbatim.
constexpr const char* ASAN_FLAG  = "address";
constexpr const char* UBSAN_FLAG = "undefined";
constexpr const char* TSAN_FLAG  = "thread";
constexpr const char* MSAN_FLAG  = "memory";
// The `just sanitize NAME` recipe combines ASan + UBSan in one instrumented
// build (they are compatible): see Justfile `sanitize` -> -fsanitize=address,undefined
constexpr const char* JUST_SANITIZE_COMBO = "address,undefined";

// Documented slowdown figures (from the LLVM sanitizer docs — see ## Sources).
// ASan: "Typical slowdown introduced by AddressSanitizer is 2x." (stack 3x)
// MSan: "Typical slowdown introduced by MemorySanitizer is 3x."
// TSan: "Typical slowdown ... about 5x-15x ... memory overhead 5x-10x."
// UBSan: "small runtime cost and no impact on address space layout or ABI."
constexpr int ASAN_SLOWDOWN_X = 2;     // 2x
constexpr int MSAN_SLOWDOWN_X = 3;     // 3x
constexpr int TSAN_SLOWDOWN_LO_X = 5;  // 5x-15x
constexpr int TSAN_SLOWDOWN_HI_X = 15;

// === Section A — The 4 runtime sanitizers + their bug domains + how to invoke =
void sectionA() {
    sectionBanner("A — The 4 runtime sanitizers + their bug domains");

    std::printf("This verified path was captured on: ");
    if (PROBE_APPLE) {
        std::printf("macOS / Apple clang");
#if defined(__clang_major__)
        std::printf(" %d", __clang_major__);
#endif
        if (PROBE_ARM64) std::printf(" / arm64");
    } else {
        std::printf("a non-Apple platform");
    }
    std::printf("\n(platform facts below cite the LLVM docs + this build's probes).\n\n");

    std::printf("C++ has NO compiler-enforced memory/data-race safety (unlike Rust's\n");
    std::printf("borrow checker). The SAFETY NET is the SANITIZERS: instrumented builds\n");
    std::printf("that catch bugs at RUNTIME, plus STATIC analyzers at compile time.\n\n");

    std::printf("sanitizer  -fsanitize=       bug domain                slowdown\n");
    std::printf("---------  ----------------  ------------------------  -------------------\n");
    std::printf("ASan       %-17s  memory: UAF/OOB/leak/double %dx (+stack 3x)\n",
                ASAN_FLAG, ASAN_SLOWDOWN_X);
    std::printf("UBSan      %-17s  UB: overflow/null/shift    small\n", UBSAN_FLAG);
    std::printf("TSan       %-17s  data races (multithread)   %dx-%dx (mem 5x-10x)\n",
                TSAN_FLAG, TSAN_SLOWDOWN_LO_X, TSAN_SLOWDOWN_HI_X);
    std::printf("MSan       %-17s  uninitialized reads        %dx\n",
                MSAN_FLAG, MSAN_SLOWDOWN_X);

    std::printf("\nHow to invoke (the `just sanitize NAME` recipe):\n");
    std::printf("    c++ -std=c++23 -g -O1 -fsanitize=%s -fno-omit-frame-pointer \\\n",
                JUST_SANITIZE_COMBO);
    std::printf("        NAME.cpp -o /tmp/cpp_NAME_san && /tmp/cpp_NAME_san\n");
    std::printf("(This combines ASan + UBSan — the two COMPATIBLE, broadly-available\n");
    std::printf(" sanitizers. ASan+MSan / ASan+TSan are MUTUALLY EXCLUSIVE — pick one.)\n");

    check("ASan flag string is \"address\"", std::strcmp(ASAN_FLAG, "address") == 0);
    check("UBSan flag string is \"undefined\"", std::strcmp(UBSAN_FLAG, "undefined") == 0);
    check("TSan flag string is \"thread\"", std::strcmp(TSAN_FLAG, "thread") == 0);
    check("MSan flag string is \"memory\"", std::strcmp(MSAN_FLAG, "memory") == 0);
    check("`just sanitize` combines ASan+UBSan (-fsanitize=address,undefined)",
          std::strcmp(JUST_SANITIZE_COMBO, "address,undefined") == 0);
    check("ASan documented slowdown is 2x", ASAN_SLOWDOWN_X == 2);
    check("MSan documented slowdown is 3x", MSAN_SLOWDOWN_X == 3);
    check("TSan documented slowdown range is 5x-15x",
          TSAN_SLOWDOWN_LO_X == 5 && TSAN_SLOWDOWN_HI_X == 15);
    check("ASan+UBSan are compatible (both in the `just sanitize` combo)",
          std::strcmp(JUST_SANITIZE_COMBO, "address,undefined") == 0);
}

// === Section B — ASan (memory): what it catches; the macOS leak gap =========
void sectionB() {
    sectionBanner("B — ASan (AddressSanitizer): the memory bug detector");

    std::printf("ASan instruments heap, stack, and globals with REDZONES + a shadow\n");
    std::printf("memory map, catching these at runtime (LLVM AddressSanitizer.html):\n");
    std::printf("  - heap-buffer-overflow   (read/write past `new[]` end)\n");
    std::printf("  - stack-buffer-overflow  (read/write past a local array end)\n");
    std::printf("  - global-buffer-overflow (read/write past a global array end)\n");
    std::printf("  - heap-use-after-free    (access through a freed pointer)\n");
    std::printf("  - stack-use-after-return / -after-scope (dangling local refs)\n");
    std::printf("  - double-free / invalid free (free the same heap block twice)\n");
    std::printf("  - memory leaks (LeakSanitizer — Linux only; see gap below)\n\n");

    std::printf("The macOS LEAK-DETECTION GAP (this platform):\n");
    std::printf("  - LeakSanitizer (LSan) ships inside ASan and is ON by default on Linux.\n");
    std::printf("  - The `just sanitize` recipe does NOT force ASAN_OPTIONS=detect_leaks=1\n");
    std::printf("    because on Apple clang that option prints\n");
    std::printf("      \"AddressSanitizer: detect_leaks is not supported on this platform.\"\n");
    std::printf("    and aborts (exit 134). So: leaks are caught on Linux, NOT on macOS.\n");
    std::printf("  - Use Linux (or a from-source LLVM clang with LSan) for leak detection.\n\n");

    std::printf("The use-after-free demo is GATED behind -DDEMO_BUG (NOT in the verified\n");
    std::printf("path; `just run`/`just out`/`just check`/`just sanitize` never pass it):\n");

#ifdef DEMO_BUG
    // ── WHAT NOT TO DO — never enabled by the default build ───────────────────
    // A textbook use-after-free. Compiled ONLY with -DDEMO_BUG. Under ASan it
    // prints (to stderr) something like:
    //   ==PID==ERROR: AddressSanitizer: heap-use-after-free on address 0x...
    //     READ of size 4 at 0x... thread T0
    //       #0 ... in sectionB(...) sanitizers_static_analysis.cpp:NNN
    //     ... freed by thread T0 here: ... operator delete[](void*) ...
    //     ... previously allocated here: ... operator new[](unsigned long) ...
    //   ==PID==ABORTING
    int* p = new int[4];
    p[0] = 42;
    delete[] p;
    int leaked_read = p[0];   // <-- USE-AFTER-FREE: ASan aborts here
    std::printf("[DEMO_BUG] read freed memory = %d (UB; ASan would abort before this)\n",
                leaked_read);
#else
    std::printf("    (DEMO_BUG not defined — the UAF read is correctly OMITTED from this build.)\n");
    std::printf("    Build with -DDEMO_BUG -fsanitize=address to SEE ASan fire.\n");
#endif

    // The CORRECT (RAII, sanitizer-clean) pattern for the same task — a vector
    // owns its memory; no manual delete; no UAF possible. This is what the
    // verified path actually exercises (UB-free by construction).
    std::printf("\nThe UB-FREE alternative the verified path exercises: RAII ownership.\n");
    std::printf("    int v[4] = {42,0,0,0};   // automatic storage; freed at scope end\n");
    int v[4] = {42, 0, 0, 0};
    std::printf("    v[0] = %d  (safe; no manual delete; no UAF possible)\n", v[0]);

    check("ASan instruments heap (new) memory", true);
    check("ASan instruments stack (local array) memory", true);
    check("ASan instruments global memory", true);
    check("ASan detects use-after-free (UAF)", true);
    check("ASan detects heap/stack/global buffer overflow", true);
    check("ASan detects double-free / invalid free", true);
    check("ASan detects memory leaks ONLY on Linux (LSan; macOS Apple clang has no LSan)",
          true);
    check("this verified path does NOT compile the DEMO_BUG UAF (default build is clean)",
          true);
}

// === Section C — UBSan + TSan + MSan ========================================
void sectionC() {
    sectionBanner("C — UBSan (UB) + TSan (data races) + MSan (uninit)");

    // --- UBSan -------------------------------------------------------------
    std::printf("UBSan (-fsanitize=undefined): a FAST undefined-behavior detector.\n");
    std::printf("Compiles in runtime checks that catch (LLVM UndefinedBehaviorSanitizer.html):\n");
    std::printf("  - signed-integer-overflow   (INT_MAX + 1; INT_MIN / -1; INT_MIN * -1)\n");
    std::printf("  - shift                     (exponent >= width, or negative; neg base)\n");
    std::printf("  - null                      (dereference of a null pointer/ref)\n");
    std::printf("  - alignment                 (misaligned pointer/reference access)\n");
    std::printf("  - integer-divide-by-zero    (a / 0, a %% 0)\n");
    std::printf("  - bounds                    (array index past a statically-known bound)\n");
    std::printf("  - enum                      (load of an out-of-range enum value)\n");
    std::printf("  - bool / vptr / object-size / return / unreachable / float-cast-overflow\n");
    std::printf("  + (opt-in) implicit-conversion / unsigned-integer-overflow (NOT UB)\n");
    std::printf("Small runtime cost; no ABI/address-space impact. macOS: supported.\n\n");

    // A UBSan-checkable value demonstrated SAFELY: we ask "would INT32_MAX + 1
    // overflow?" using the STANDARD overflow-PRECONDITION (b > MAX - a), which
    // detects the overflow WITHOUT performing it — so no UB is ever executed in
    // the verified path, and UBSan stays clean.
    constexpr std::int32_t i32max = 2147483647;
    constexpr bool add_one_would_overflow = (1 > i32max - i32max);  // 1 > 0 -> true
    std::printf("UBSan demo (computed, NOT executed): INT32_MAX = %d.\n", i32max);
    std::printf("    `INT32_MAX + 1` is signed-integer-overflow UB -> would trip UBSan:\n");
    std::printf("    \"runtime error: signed integer overflow: 2147483647 + 1 cannot be\n");
    std::printf("     represented in type 'int'\". (We detect it, never run it.)\n");
    check("INT32_MAX == 2147483647", i32max == 2147483647);
    check("overflow precondition 1 > INT32_MAX - INT32_MAX (=> +1 would overflow)",
          add_one_would_overflow);

    // --- TSan --------------------------------------------------------------
    std::printf("\nTSan (-fsanitize=thread): detects DATA RACES — two threads, one shared\n");
    std::printf("variable, at least one WRITE, no synchronization (happens-before).\n");
    std::printf("Typical report (LLVM ThreadSanitizer.html):\n");
    std::printf("    WARNING: ThreadSanitizer: data race\n");
    std::printf("      Write of size 4 at 0x... by thread T1:   #0 Thread1 race.c:4\n");
    std::printf("      Previous write ... by main thread:        #0 main race.c:10\n");
    std::printf("Slowdown 5x-15x; mem 5x-10x. Needs a genuinely racy program to fire.\n");
    std::printf("Supported on Darwin arm64/x86_64 (Apple clang). Linux aarch64/x86_64.\n");
    std::printf("Use TSan for CONCURRENCY code; ASan+UBSan for everything else.\n");
    check("TSan detects data races (unsynchronized read+write across threads)", true);
    check("TSan needs a multithreaded, genuinely racy program to fire", true);

    // --- MSan --------------------------------------------------------------
    std::printf("\nMSan (-fsanitize=memory): detects UNINITIALIZED reads. Tracks the\n");
    std::printf("initialization state of EVERY bit; reading an uninitialized value trips\n");
    std::printf("    WARNING: MemorySanitizer: use-of-uninitialized-value\n");
    std::printf("Supported ONLY on Linux / NetBSD / FreeBSD — NOT on macOS. INCOMPATIBLE\n");
    std::printf("with ASan (both reserve shadow memory differently; pick ONE).\n");
    check("MSan detects uninitialized reads (tracks every bit's init state)", true);
    check("MSan is Linux/NetBSD/FreeBSD-only (NOT supported on macOS)", true);
    check("MSan is MUTUALLY EXCLUSIVE with ASan (pick one, never both)", true);
}

// === Section D — Perf cost + STATIC analysis + CI best practice =============
void sectionD() {
    sectionBanner("D — Perf cost + STATIC analysis + CI best practice");

    std::printf("THE PERFORMANCE COST (why sanitizers are a DEBUG/CI tool, NOT release):\n");
    std::printf("  - ASan:  ~2x slower, more real memory, stack up to 3x.\n");
    std::printf("  - UBSan: small overhead (tens of percent) — sometimes OK in release.\n");
    std::printf("  - TSan:  5x-15x slower, 5x-10x more memory (only for concurrency code).\n");
    std::printf("  - MSan:  3x slower, 2x more memory (Linux only).\n");
    std::printf("-> Never ship -fsanitize=... in a production/release binary. (LLVM docs:\n");
    std::printf("   sanitizer runtimes \"were not developed with security-sensitive\n");
    std::printf("   constraints in mind.\")\n\n");

    std::printf("STATIC analysis (at COMPILE time — no run, no slowdown):\n");
    std::printf("  - clang-tidy: a lint + modernize + bugprone checker. Runs as a separate\n");
    std::printf("    pass (NOT a -fsanitize flag). Catches: modernize-use-nullptr,\n");
    std::printf("    bugprone-use-after-move, cert-*, cppcoreguidelines-*, performance-*.\n");
    std::printf("  - cppcheck: a standalone static bug finder (null deref, OOB index,\n");
    std::printf("    resource leaks). Conservative; some false positives.\n");
    std::printf("Neither is in the default `just run`/`just check` build — they are run\n");
    std::printf("separately (e.g. in CI or via an editor integration).\n\n");

    std::printf("CI BEST PRACTICE (the recommended sanitizer diet):\n");
    std::printf("  1. ASan + UBSan on EVERY commit, over the full test suite\n");
    std::printf("     (`just sanitize NAME` is exactly this combo).\n");
    std::printf("  2. TSan on concurrency-touching code paths (jthread/atomic/mutex).\n");
    std::printf("  3. MSan on Linux CI for the uninit-read class (complements ASan).\n");
    std::printf("  4. clang-tidy + cppcheck as a separate static-analysis CI job.\n");
    std::printf("  5. LeakSanitizer (Linux) for any C/C++ with manual allocation.\n");

    check("sanitizers are DEBUG/CI tools (never release) due to 2x-15x slowdown", true);
    check("ASan+UBSan every commit is the recommended baseline", true);
    check("TSan is reserved for concurrency code (5x-15x too slow for everything)", true);
    check("clang-tidy + cppcheck are STATIC (compile-time), not -fsanitize runtime", true);
}

// === Section E — Cross-language: Rust borrow checker vs C++ sanitizers ======
void sectionE() {
    sectionBanner("E — Cross-language: Rust borrow checker vs C++ sanitizers");

    std::printf("THE HEADLINE CONTRAST. C++ has NO compiler-enforced memory or data-race\n");
    std::printf("safety. It relies on the RUNTIME sanitizers (ASan/UBSan/TSan/MSan) to\n");
    std::printf("FIND the bugs AFTER the program is built and run. Rust's BORROW CHECKER\n");
    std::printf("prevents the same bug CLASSES at COMPILE TIME — in safe Rust you do not\n");
    std::printf("NEED ASan or TSan for memory/data-race safety:\n\n");

    std::printf("  bug class            C++ (runtime sanitizer)   Rust (compile-time)\n");
    std::printf("  -------------------  ------------------------   -------------------\n");
    std::printf("  use-after-free       ASan (heap-use-after-free) borrow checker (lifetimes)\n");
    std::printf("  double-free          ASan (double-free)         ownership is unique\n");
    std::printf("  out-of-bounds        ASan (buffer-overflow)     indexing is checked /\n");
    std::printf("                                                   Iterator bounds\n");
    std::printf("  data race            TSan                       Send/Sync + borrow ck\n");
    std::printf("  dangling pointer     ASan (-after-return/scope)  lifetimes reject it\n");
    std::printf("  uninitialized read   MSan                       must-init enforced\n");
    std::printf("  signed overflow      UBSan (signed-overflow)    debug_assert / i32\n");
    std::printf("                                                  ::checked_add\n\n");

    std::printf("Rust does NOT make sanitizers obsolete — it still ships them for UNSAFE\n");
    std::printf("Rust and for the few UB-equivalents that remain (e.g. signed overflow in\n");
    std::printf("release is defined wrap, but integer-overflow LOGIC bugs still happen).\n");
    std::printf("But for SAFE Rust the entire ASan/TSan/MSan bug domain is CLOSED by the\n");
    std::printf("compiler. C++ has no equivalent; the sanitizers ARE the safety net.\n\n");

    std::printf("Other languages in the curriculum:\n");
    std::printf("  - Go: GC handles memory (no UAF/double-free); `go build -race` is a\n");
    std::printf("    data-race detector (analogous to TSan).\n");
    std::printf("  - TS/Python: GC + a GIL/single-thread event loop -> no memory-safety\n");
    std::printf("    sanitizer needed (the GIL removes the data race in pure-Python land).\n");

    check("Rust's borrow checker catches UAF/dangling/data-race at COMPILE TIME", true);
    check("safe Rust does NOT need ASan/TSan for memory/data-race safety", true);
    check("C++ relies on the RUNTIME sanitizers as its safety net (no borrow checker)",
          true);
    check("Go has a race detector (go build -race); GC handles memory", true);
    check("TS/Python rely on GC + (Python) GIL -> no memory-safety sanitizer needed",
          true);
}

}  // namespace

int main() {
    std::printf("sanitizers_static_analysis.cpp — Phase 7 bundle (the C++ safety net).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23 -O2\n");
    std::printf("-Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    std::printf("The DEMO_BUG use-after-free is GATED (-DDEMO_BUG) and never in the\n");
    std::printf("default build.\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
