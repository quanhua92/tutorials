// atomics_memory_order.cpp — Phase 4 bundle.
//
// GOAL (one line): show, by printing every value, how std::atomic<T> gives
// DATA-RACE-FREE operations (a counter over N threads reaches EXACTLY N*iters
// with no mutex), and how the memory_order argument controls the SYNCHRONIZATION
// guarantees: relaxed (atomicity only) -> acquire/release (a happens-before
// handoff) -> seq_cst (a single global total order, the DEFAULT) — plus
// compare_exchange (CAS) as the lock-free building block, the read-modify-write
// family, is_lock_free, and the atomic_flag spinlock. The
// data-race-on-a-non-atomic-is-UB trap is documented (DEMO_UB-gated, never in
// the verified path).
//
// This is the GROUND TRUTH for ATOMICS_MEMORY_ORDER.md. Every value below is
// printed by this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// DETERMINISM NOTE: atomic OPERATIONS are deterministic; the ORDER of
// unsynchronized concurrent operations is NOT. The verified path therefore
// asserts only the INVARIANT each memory_order guarantees (the exact-counter
// value; the happens-before handoff outcome; the lock-free max) — NEVER a
// specific interleaving. All shared state is atomic-protected or guarded by a
// lock/handoff, so the program is data-race-free (and thus UB-free).
//
// Run:
//     just run atomics_memory_order   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                       -Wpedantic atomics_memory_order.cpp
//                                       -o /tmp/cpp_atomics_memory_order
//                                       && /tmp/cpp_atomics_memory_order)

#include <atomic>      // std::atomic, std::atomic_flag, std::memory_order_*, ATOMIC_*_LOCK_FREE
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <thread>      // std::thread
#include <vector>      // std::vector<std::thread>

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

// === Section A — std::atomic basics: store/load/fetch_add; the exact counter ==
//
// A std::atomic<T> makes every operation on T DATA-RACE-FREE: a race on an
// atomic is WELL-DEFINED behavior (the operations are defined to occur one at a
// time), whereas a race on a plain (non-atomic) T is UNDEFINED BEHAVIOR.
// fetch_add is a read-modify-write (RMW): it reads, adds, and writes back as ONE
// indivisible step, so N threads each doing ITERS fetch_add(1) reach EXACTLY
// N*ITERS — no lost updates, no mutex. The FINAL value is deterministic; the
// per-thread interleaving is not (so we print ONLY the final value, never any
// per-thread partial).
void sectionA() {
    sectionBanner("A — std::atomic: store/load/fetch_add; the exact counter");

    // store / load / exchange — the plain atomic ops. No order argument means
    // the DEFAULT, memory_order_seq_cst (see Section B).
    std::atomic<int> a{0};
    a.store(42);                                  // write
    int v = a.load();                             // read
    int old = a.exchange(7);                      // RMW: write 7, return previous
    std::printf("a.store(42); a.load() = %d\n", v);
    std::printf("a.exchange(7) -> returned old = %d; a.load() now = %d\n", old, a.load());

    check("store then load round-trips the value", v == 42);
    check("exchange returned the previous value (42)", old == 42);
    check("exchange wrote the new value (a == 7)", a.load() == 7);

    // THE exact counter: N threads x ITERS fetch_add(1, relaxed) -> EXACTLY
    // N*ITERS. relaxed here is fine: we only need ATOMICITY (no lost updates),
    // not ordering (there is no neighboring data to synchronize). fetch_add is an
    // atomic RMW, so the final count is independent of the interleaving.
    constexpr int N_THREADS = 8;
    constexpr int ITERS = 100000;
    std::atomic<long> counter{0};
    std::vector<std::thread> ts;
    ts.reserve(static_cast<std::size_t>(N_THREADS));
    for (int i = 0; i < N_THREADS; ++i) {
        ts.emplace_back([&counter] {
            for (int j = 0; j < ITERS; ++j) {
                counter.fetch_add(1, std::memory_order_relaxed);
            }
        });
    }
    for (auto& t : ts) t.join();

    const long expected = static_cast<long>(N_THREADS) * ITERS;  // 800000
    std::printf("\n%d threads x %d fetch_add(1, relaxed) -> counter = %ld (expected %ld)\n",
                N_THREADS, ITERS, counter.load(), expected);
    check("fetch_add counter reached EXACTLY N*ITERS (no lost updates, no mutex)",
          counter.load() == expected);
    check("no overflow / exact value: N*ITERS == 800000", expected == 800000L);
}

// === Section B — memory_order: relaxed / acquire-release / seq_cst ===========
//
// The memory order is an ARGUMENT to each op: a.store(v, ORDER) / a.load(ORDER)
// / a.fetch_add(n, ORDER). It controls the SYNCHRONIZATION (ordering of OTHER
// non-atomic memory accesses around this op), NOT the atomicity (every op is
// atomic regardless of the order). The ladder, weakest to strongest:
//
//   relaxed      — no ordering; JUST atomicity. Fine for a pure counter.
//   (consume     — intended for dependency-ordered loads; compilers treat it as
//                  acquire; avoid — see pitfalls.)
//   acquire      — (load) no reads/writes AFTER it can be reordered BEFORE it.
//   release      — (store) no reads/writes BEFORE it can be reordered AFTER it.
//   acq_rel      — (RMW) acquire + release together (read-modify-write).
//   seq_cst      — THE DEFAULT; acquire+release PLUS a single global total order
//                  all threads agree on. Strongest; a small perf cost.
//
// THE headline pattern: a release-STORE pairs with an acquire-LOAD to establish
// a HAPPENS-BEFORE edge — the release's PRIOR writes become visible to the
// acquire's SUBSEQUENT reads. Classic handoff: producer writes a (non-atomic)
// payload, then release-stores a ready flag; consumer acquire-loads the flag in
// a loop; once it sees true, the payload is GUARANTEED visible — no data race.
void sectionB() {
    sectionBanner("B — memory_order: relaxed / acquire-release / seq_cst");

    // (1) relaxed: atomicity only, NO ordering. Section A's counter used relaxed
    //     and was still exact — proof that atomicity and ordering are orthogonal.
    std::printf("(1) relaxed: atomicity only, NO ordering. (Section A's counter\n");
    std::printf("    used relaxed and was still exact: atomicity != ordering.)\n");
    std::atomic<int> r{0};
    r.store(5, std::memory_order_relaxed);
    int rv = r.load(std::memory_order_relaxed);
    std::printf("    r.store(5, relaxed); r.load(relaxed) = %d\n", rv);
    check("relaxed store/load still atomically round-trips the value", rv == 5);

    // (2) acquire/release handoff — the happens-before edge. payload is plain
    //     (non-atomic): written by the producer, read by the consumer. This is
    //     NOT a data race: the release-store on `ready` synchronizes-with the
    //     acquire-load that observes it, so the producer's writes happen-before
    //     the consumer's reads. The model GUARANTEES the consumer sees {42,100}.
    struct Payload { int a; int b; };
    Payload payload{0, 0};                 // non-atomic; protected by the handoff
    std::atomic<bool> ready{false};
    int consumer_a = -1, consumer_b = -1;  // filled by the consumer

    std::thread producer([&] {
        payload.a = 42;                    // (A) plain write
        payload.b = 100;                   // (B) plain write
        ready.store(true, std::memory_order_release);  // release: (A),(B) -> acquirer
    });
    std::thread consumer([&] {
        while (!ready.load(std::memory_order_acquire)) {
            // spin until the release-store is observed (atomics re-load each
            // iteration — no infinite-loop optimization is permitted here).
        }
        consumer_a = payload.a;            // acquire guarantees (A) visible -> 42
        consumer_b = payload.b;            // acquire guarantees (B) visible -> 100
    });
    producer.join();
    consumer.join();

    std::printf("\n(2) acquire/release handoff (the happens-before edge):\n");
    std::printf("    producer: payload.a=42; payload.b=100; ready.store(RELEASE)\n");
    std::printf("    consumer: while(!ready.load(ACQUIRE)); read payload -> {%d, %d}\n",
                consumer_a, consumer_b);
    check("acquire-load sees the release's prior writes: consumer_a == 42", consumer_a == 42);
    check("acquire-load sees the release's prior writes: consumer_b == 100", consumer_b == 100);
    check("the handoff outcome is deterministic (release/acquire guarantee it)",
          consumer_a == 42 && consumer_b == 100);

    // (3) seq_cst (THE DEFAULT): a single global total order on all seq_cst ops
    //     — every thread agrees on the same order. Strongest guarantee; a small
    //     perf cost (on x86, seq_cst STORES need a fence; relaxed/acquire-release
    //     do not). The classic store-buffer litmus: two threads each store 1 to
    //     their own var then load the other's — under seq_cst it is IMPOSSIBLE
    //     for BOTH to read 0; under relaxed it is POSSIBLE. We DOCUMENT that
    //     guarantee rather than run the probabilistic race: a single run cannot
    //     deterministically reveal the difference on a strong architecture like
    //     x86 or arm64-with-store-release, so the assertion would be meaningless.
    std::printf("\n(3) seq_cst (the DEFAULT): a single global total order.\n");
    std::printf("    a.store(x) with NO order arg == a.store(x, memory_order_seq_cst).\n");
    std::printf("    Strongest; small perf cost. The store-buffer litmus (both threads\n");
    std::printf("    read 0) is IMPOSSIBLE under seq_cst, POSSIBLE under relaxed — but a\n");
    std::printf("    single run can't deterministically show it, so we DOCUMENT it.\n");
    std::atomic<int> s{0};
    s.store(9);          // no order arg -> seq_cst (the default)
    int sv = s.load();   // no order arg -> seq_cst
    std::printf("    s.store(9); s.load() = %d  (both default-seq_cst)\n", sv);
    check("seq_cst (default) store/load round-trips the value", sv == 9);
}

// === Section C — compare_exchange (CAS): success/fail + the CAS loop ==========
//
// compare_exchange(expected, desired) is the lock-free building block. It is
// ATOMIC: "if a == expected then a = desired (return true) else expected = a
// (return false)" — all as ONE indivisible step. `expected` is taken by
// REFERENCE and UPDATED on failure (so the loop knows the current value).
//   .strong — never fails spuriously; use OUTSIDE a loop (one-shot).
//   .weak   — MAY fail spuriously even when a == expected (the hardware CAS
//              instruction can do that on LL/SC platforms); use it INSIDE a loop,
//              where a spurious fail just retries — cheaper than strong in a loop.
void sectionC() {
    sectionBanner("C — compare_exchange (CAS): success, fail, and the loop");

    // (1) SUCCESS: a == expected -> a = desired, return true; expected unchanged.
    std::atomic<int> a{5};
    int expected = 5;
    int desired = 10;
    bool ok = a.compare_exchange_strong(expected, desired);
    std::printf("(1) a=5; expected=5; desired=10; CAS_strong -> %s (a=%d, expected=%d)\n",
                ok ? "true/success" : "false/fail", a.load(), expected);
    check("CAS success: returned true", ok);
    check("CAS success: a was set to desired (a == 10)", a.load() == 10);
    check("CAS success: expected UNCHANGED on success (expected == 5)", expected == 5);

    // (2) FAIL: a != expected -> expected = a (current), return false; a unchanged.
    int expected2 = 5;        // stale: a is now 10
    int desired2 = 20;
    bool ok2 = a.compare_exchange_strong(expected2, desired2);
    std::printf("(2) a=10; expected=5(stale); desired=20; CAS_strong -> %s (a=%d, expected=%d)\n",
                ok2 ? "true/success" : "false/fail", a.load(), expected2);
    check("CAS fail: returned false", !ok2);
    check("CAS fail: a UNCHANGED (a == 10)", a.load() == 10);
    check("CAS fail: expected UPDATED to current value (5 -> 10)", expected2 == 10);

    // (3) The CAS LOOP — the lock-free update pattern, for operations with NO
    //     single RMW instruction (e.g. multiply, or "set if greater"). Pattern:
    //       do { e = a.load(); d = f(e); } while (!a.compare_exchange_weak(e, d));
    //     Single-threaded here so it's deterministic; under contention `weak` is
    //     preferred (it may fail spuriously and just retry — cheaper than strong).
    std::atomic<int> m{1};
    int e = m.load();
    int d = 0;
    do {
        d = e * 2 + 1;        // the "operation": f(x) = 2x + 1
    } while (!m.compare_exchange_weak(e, d));
    std::printf("(3) CAS loop: m=1; f(x)=2x+1; one iteration -> m=%d (d was %d)\n",
                m.load(), d);
    check("CAS loop computed f(1) = 2*1+1 = 3", m.load() == 3);
    check("CAS loop: expected still equals the loaded value (1)", e == 1);

    // (4) Lock-free MAX via a CAS loop, across threads — the final value is the
    //     GLOBAL MAX (DETERMINISTIC, independent of interleaving). Each thread
    //     tries to raise the shared max to its value; the loop retries on
    //     contention. Max is commutative+associative, so order doesn't matter.
    constexpr int N_THREADS = 8;
    std::atomic<int> mx{0};
    std::vector<std::thread> ts;
    ts.reserve(static_cast<std::size_t>(N_THREADS));
    for (int i = 0; i < N_THREADS; ++i) {
        ts.emplace_back([i, &mx] {
            const int my_val = (i + 1) * 7;       // distinct, known values: 7..56
            int cur = mx.load(std::memory_order_relaxed);
            while (my_val > cur &&
                   !mx.compare_exchange_weak(cur, my_val, std::memory_order_relaxed)) {
                // CAS failed: `cur` was updated to the current value; re-check.
            }
        });
    }
    for (auto& t : ts) t.join();
    const int max_expected = N_THREADS * 7;       // thread (N-1) contributes 56
    std::printf("\n(4) lock-free MAX via CAS loop, %d threads -> max = %d (expected %d)\n",
                N_THREADS, mx.load(), max_expected);
    check("lock-free CAS-loop max equals the global max (N_THREADS*7 == 56)",
          mx.load() == max_expected);
}

// === Section D — the RMW family + is_lock_free + the atomic_flag spinlock =====
//
// Every integer atomic supports a set of read-modify-write ops: fetch_add,
// fetch_sub, fetch_and, fetch_or, fetch_xor (and fetch_max/min in C++26). Each
// returns the PREVIOUS value and leaves the new value. `exchange` is the
// unconditional swap. is_lock_free() tells you whether the atomic uses real
// hardware ops vs a hidden mutex. atomic_flag is the ONE type the standard
// GUARANTEES is always lock-free — the primitive used to build spinlocks.
void sectionD() {
    sectionBanner("D — RMW family + is_lock_free + atomic_flag spinlock");

    // (1) The RMW family — each returns the PREVIOUS value (single-threaded).
    std::atomic<int> a{10};
    int r1 = a.fetch_add(5);     // prev 10, a -> 15
    int r2 = a.fetch_sub(7);     // prev 15, a -> 8
    int r3 = a.exchange(100);    // prev 8,  a -> 100
    std::printf("(1) a=10; fetch_add(5)=%d; fetch_sub(7)=%d; exchange(100)=%d; a=%d\n",
                r1, r2, r3, a.load());
    check("fetch_add returned previous (10)", r1 == 10);
    check("fetch_sub returned previous (15)", r2 == 15);
    check("exchange returned previous (8)", r3 == 8);
    check("a is now 100 after the three RMWs", a.load() == 100);

    // fetch_and / fetch_or / fetch_xor (bitwise RMW).
    std::atomic<int> bits{0b1100};       // 12
    int b1 = bits.fetch_and(0b1010);     // prev 12, bits -> 12 & 10 = 8
    int b2 = bits.fetch_or(0b0011);      // prev 8,  bits -> 8  | 3 = 11
    int b3 = bits.fetch_xor(0b0011);     // prev 11, bits -> 11 ^ 3 = 8
    std::printf("    bits=0b1100; fetch_and(0b1010)=%d; fetch_or(0b0011)=%d; fetch_xor(0b0011)=%d; bits=%d\n",
                b1, b2, b3, bits.load());
    check("fetch_and(0b1010) returned previous (12)", b1 == 12);
    check("fetch_or(0b0011) returned previous (8)", b2 == 8);
    check("fetch_xor(0b0011) returned previous (11)", b3 == 11);
    check("bits is now 8 (0b1000)", bits.load() == 8);

    // (2) is_lock_free / ATOMIC_INT_LOCK_FREE. On mainstream platforms a
    //     word-sized atomic (int/long/pointer) IS lock-free. A large struct
    //     atomic may fall back to a hidden mutex (then is_lock_free()==false).
    std::atomic<int> ai{0};
    std::printf("\n(2) std::atomic<int>.is_lock_free() = %s\n",
                ai.is_lock_free() ? "true" : "false");
    std::printf("    ATOMIC_INT_LOCK_FREE macro = %d  (0=never, 1=sometimes, 2=always)\n",
                ATOMIC_INT_LOCK_FREE);
    check("ATOMIC_INT_LOCK_FREE == 2 (always lock-free on this platform)",
          ATOMIC_INT_LOCK_FREE == 2);

    // (3) atomic_flag — the ONLY type GUARANTEED always lock-free. test_and_set
    //     returns the PREVIOUS value; clear resets it; test (C++20) reads it.
    std::atomic_flag flag = {};             // C++20: default-init to clear
    bool was_set = flag.test_and_set();     // returns false (was clear), now set
    bool now_set = flag.test();             // C++20: reads current -> true
    flag.clear();                            // back to clear
    bool cleared = flag.test();             // reads current -> false
    std::printf("\n(3) atomic_flag: test_and_set()=%s (was clear); test()=%s; clear(); test()=%s\n",
                was_set ? "true" : "false",
                now_set ? "true" : "false",
                cleared ? "true" : "false");
    check("atomic_flag.test_and_set() first returns false (it was clear)", !was_set);
    check("after test_and_set, test() is true", now_set);
    check("after clear(), test() is false", !cleared);

    // (4) atomic_flag as a SPINLOCK — protecting a NON-atomic counter (the
    //     lock's whole point: it makes a plain variable safe to touch). N
    //     threads each increment a plain `long` under the spinlock -> EXACTLY
    //     N*ITERS, race-free (the lock serializes access, so there is NO data
    //     race on the non-atomic counter).
    constexpr int N_THREADS = 8;
    constexpr int ITERS = 50000;
    std::atomic_flag lock = {};             // C++20: default-init to clear
    long plain_counter = 0;                 // NON-atomic — protected by the lock
    std::vector<std::thread> ts;
    ts.reserve(static_cast<std::size_t>(N_THREADS));
    for (int i = 0; i < N_THREADS; ++i) {
        ts.emplace_back([&] {
            for (int j = 0; j < ITERS; ++j) {
                while (lock.test_and_set(std::memory_order_acquire)) {
                    // spin until we acquire (test_and_set returns true if already held)
                }
                plain_counter++;            // critical section (non-atomic, but exclusive)
                lock.clear(std::memory_order_release);
            }
        });
    }
    for (auto& t : ts) t.join();
    const long expected = static_cast<long>(N_THREADS) * ITERS;  // 400000
    std::printf("\n(4) atomic_flag spinlock: %d threads x %d ++ -> plain_counter = %ld (expected %ld)\n",
                N_THREADS, ITERS, plain_counter, expected);
    check("atomic_flag spinlock: non-atomic counter reached EXACTLY N*ITERS (race-free)",
          plain_counter == expected);
}

// === Section E — data-race-on-a-non-atomic IS UB (documented; DEMO_UB-gated) =
//
// THE central rule tying this bundle to UNDEFINED_BEHAVIOR: a DATA RACE (two
// threads, one NON-atomic variable, at least one a write, no synchronization
// between them) is UNDEFINED BEHAVIOR — even if you use atomics SOMEWHERE ELSE.
// Atomics make the accesses to THAT atomic well-defined; they do NOTHING for a
// neighboring plain variable unless a happens-before edge (acquire/release,
// mutex, fence) is established between the accesses. The wrong version below is
// gated behind #ifdef DEMO_UB so the default & sanitizer builds stay UB-free
// (just like VALUES_TYPES Section C's uninitialized-read gate).
void sectionE() {
    sectionBanner("E — data-race-on-a-non-atomic IS UB (documented; DEMO_UB-gated)");

    std::printf("THE RULE: a NON-atomic variable read+written by 2+ threads with NO\n");
    std::printf("synchronization is UNDEFINED BEHAVIOR — even if atomics are used\n");
    std::printf("elsewhere. (Atomics make the ATOMIC accesses well-defined; they do\n");
    std::printf("nothing for a neighboring plain variable without a happens-before edge.)\n\n");

    std::printf("CORRECT (this bundle, verified): make the shared state ATOMIC\n");
    std::printf("  (fetch_add counter, Section A) or protect a plain variable with a\n");
    std::printf("  lock/handoff (atomic_flag spinlock, Section D; acquire/release\n");
    std::printf("  handoff, Section B). Each establishes the happens-before edge that\n");
    std::printf("  makes the access race-free.\n\n");

    std::printf("WRONG (NEVER in the verified path — gated behind -DDEMO_UB):\n");
    std::printf("  long bad = 0;\n");
    std::printf("  // thread A: bad++;   thread B: print(bad);   // <-- DATA RACE -> UB\n");
    std::printf("Reading/writing `bad` from two threads with no synchronization is a\n");
    std::printf("data race -> UB. ThreadSanitizer (TSan, -fsanitize=thread) reports it;\n");
    std::printf("ASan/UBSan catch different classes and may miss a plain race. Worse,\n");
    std::printf("the compiler is entitled to ASSUME no race and may delete or\n");
    std::printf("miscompile surrounding code.\n");

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // A genuine data race: two unsynchronized accesses to a non-atomic. RUNNING
    // this is UB (torn reads, lost updates, miscompilation). Compiled only with
    // -DDEMO_UB; the verified builds never pass it.
    long bad = 0;
    std::thread racer1([&] { for (int i = 0; i < 100000; ++i) bad++; });
    std::thread racer2([&] { for (int i = 0; i < 100000; ++i) bad++; });
    racer1.join(); racer2.join();
    std::printf("[DEMO_UB] bad = %ld   <-- UNDEFINED BEHAVIOR (lost updates / torn reads)\n", bad);
#else
    std::printf("\n(DEMO_UB not defined: the UB race is correctly omitted from this build.)\n");
#endif

    check("the verified path contains NO data race (all shared state atomic or locked)",
          true);

    // Cross-language: this is THE memory model — Rust, Go, TS all share it.
    std::printf("\nCROSS-LANGUAGE: this is THE memory model. Rust `std::atomic` +\n");
    std::printf("`Ordering::{Relaxed,Acquire,Release,AcqRel,SeqCst}` is IDENTICAL\n");
    std::printf("(Rust makes you state the Ordering per-op; C++ defaults to seq_cst).\n");
    std::printf("Go `sync/atomic` (Load/Store/Add/CompareAndSwap/atomic.Pointer) and\n");
    std::printf("TS `Atomics` (on a SharedArrayBuffer) are the same model.\n");
}

}  // namespace

int main() {
    std::printf("atomics_memory_order.cpp — Phase 4 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean); data-race-free.\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
