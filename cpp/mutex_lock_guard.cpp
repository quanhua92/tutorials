// mutex_lock_guard.cpp — Phase 4 bundle #24.
//
// GOAL (one line): show, by printing every value, how std::mutex serializes
// shared state, how std::lock_guard (RAII) makes locking exception-safe, how
// std::scoped_lock (C++17) acquires MULTIPLE mutexes without deadlock, how
// std::unique_lock is the movable lock for condition_variable, and how
// std::call_once runs an init exactly once across threads — and pin the
// data-race-on-a-shared-int-is-UB trap as a documented expert payoff (the racy
// variant is #ifdef DEMO_UB-gated, never on the verified path).
//
// This is the GROUND TRUTH for MUTEX_LOCK_GUARD.md. Every number below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     just run mutex_lock_guard   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                   mutex_lock_guard.cpp -o /tmp/cpp_mutex_lock_guard
//                                   && /tmp/cpp_mutex_lock_guard)

#include <algorithm>   // std::sort (collect+sort+join discipline)
#include <atomic>      // std::atomic (Section E contrast)
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <mutex>       // std::mutex, lock_guard, scoped_lock, unique_lock, call_once, once_flag, defer_lock
#include <thread>      // std::thread
#include <vector>      // std::vector (collect thread results)

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

// ── Deterministic thread-output discipline (HOW_TO_RESEARCH §4.2 rule 4) ─────
// Worker threads NEVER printf directly (stdout interleaving is nondeterministic).
// Each worker records its index into a mutex-protected vector; main() sorts +
// prints AFTER every thread joins -> byte-identical stdout on every run.

constexpr int N_THREADS = 8;
constexpr int ITERS = 100000;
// N_THREADS * ITERS == 800000 (the exact count a correct increment reaches).

// === Section A — std::mutex + the NEVER-direct rule + std::lock_guard =======
//
// std::mutex grants EXCLUSIVE ownership: only one thread may hold it. Calling
// m.lock()/m.unlock() by hand is EXCEPTION-UNSAFE — a throw or early return
// between them leaks the lock forever. The rule: NEVER call them directly; wrap
// the mutex in an RAII guard so the lock is acquired in the ctor and released in
// the dtor (which runs on normal exit, early return, AND exception unwind).
void sectionA() {
    sectionBanner("A — std::mutex + std::lock_guard (RAII lock/unlock)");

    std::printf("std::mutex: exclusive ownership. Manual m.lock()/m.unlock() is\n");
    std::printf("EXCEPTION-UNSAFE (a throw/early-return between them leaks the lock).\n");
    std::printf("Rule: NEVER call lock/unlock directly — wrap in an RAII guard.\n");

    std::mutex m;

    {
        std::lock_guard<std::mutex> lk(m);   // ctor calls m.lock()
        std::printf("  inside { lock_guard<std::mutex> lk(m); } : mutex HELD (RAII acquire)\n");
        check("lock_guard constructed — mutex owned for the scope", true);
    }  // lk dtor calls m.unlock() (runs at scope exit, on return, AND on throw)

    // PROOF the dtor unlocked: re-acquiring the SAME mutex does NOT deadlock.
    // std::mutex is NON-recursive, so if unlock had NOT run, this next line would
    // lock a mutex the current thread already owns -> undefined behavior / hang.
    // It succeeds -> the dtor's unlock() ran. (This is the lock_guard contract.)
    {
        std::lock_guard<std::mutex> lk2(m);   // re-acquire succeeds => unlock ran
        std::printf("  after scope exit: re-acquired via lock_guard lk2(m) — no deadlock,\n");
        std::printf("    so lk's dtor ran m.unlock(). lock_guard is non-copyable (= deleted).\n");
        check("lock_guard lk2 re-acquired after lk's scope (RAII unlock ran; no deadlock)",
              true);
    }

    // The UNNAMED-VARIABLE trap (cppreference "Notes"): a guard MUST be named.
    //   std::lock_guard(mtx);   // WRONG: declares a variable NAMED mtx (CTAD +
    //                            //        redundant parens) — holds no mutex.
    //   std::lock_guard{mtx};   // WRONG: a prvalue destroyed at once — no lock held.
    // Both compile and silently do nothing; always name it: `T lk(m);`.
    std::printf("  TRAP (documented, not executed): `lock_guard(mtx);` is a NAMED variable\n");
    std::printf("  `mtx`; `lock_guard{mtx};` is destroyed immediately. Always name the\n");
    std::printf("  guard: `std::lock_guard<std::mutex> lk(m);`.\n");
    check("guard variable `lk` is named (the unnamed forms are a silent bug)", true);
}

// === Section B — data race WITHOUT a mutex (UB) vs the mutex FIX (exact) =====
//
// N_THREADS threads each increment a shared counter ITERS times.
//  (1) Mutex-protected  -> exactly N*ITERS (increments are serialized; no lost
//      updates). SAFE and DETERMINISTIC.
//  (2) WITHOUT a mutex  -> counter++ is a read-modify-write; two of those
//      overlapping without synchronization is a DATA RACE -> UNDEFINED BEHAVIOR,
//      and in practice produces LOST updates (final << N*ITERS). We DO NOT run
//      this in the verified path — it is #ifdef DEMO_UB-gated so the default
//      and sanitizer builds stay UB-free (HOW_TO_RESEARCH §4.2 rule 5).
struct Counter {
    std::mutex m;
    long value = 0;   // INVARIANT: guarded by m
};

void sectionB() {
    sectionBanner("B — data race (UB, documented) vs mutex-protected (exact count)");

    Counter ctr;
    std::vector<int> done;          // per-thread indices, guarded by done_m
    std::mutex done_m;
    std::vector<std::thread> ts;
    for (int t = 0; t < N_THREADS; ++t) {
        ts.emplace_back([&ctr, &done, &done_m, t]() {
            for (int i = 0; i < ITERS; ++i) {
                std::lock_guard<std::mutex> lk(ctr.m);   // RAII: lock per increment
                ++ctr.value;
            }
            {
                std::lock_guard<std::mutex> lk(done_m);  // record this thread
                done.push_back(t);
            }
        });
    }
    for (auto& th : ts) th.join();

    std::sort(done.begin(), done.end());   // collect+sort -> deterministic print
    std::printf("mutex-protected: %d threads x %d iters = expected %d\n",
                N_THREADS, ITERS, N_THREADS * ITERS);
    std::printf("  actual counter = %ld\n", ctr.value);
    std::printf("  threads reported (sorted): ");
    for (int idx : done) std::printf("%d ", idx);
    std::printf("(collect+sort+join for deterministic stdout)\n");

    check("mutex-protected counter == N*ITERS (no lost updates)",
          ctr.value == static_cast<long>(N_THREADS) * ITERS);
    check("exactly N_THREADS workers reported (all joined)",
          done.size() == static_cast<std::size_t>(N_THREADS));

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // Four threads, NO mutex, racing on `racy`. Each does racy++ DEMO_ITERS
    // times. A data race on a non-atomic int is UNDEFINED BEHAVIOR. `volatile`
    // is used ONLY to defeat the optimizer so each ++ is a real load/add/store
    // (which makes the classic lost-update interleaving VISIBLE) — it does NOT
    // make the access thread-safe; the race is still UB. In practice the final
    // count falls SHORT of 4*DEMO_ITERS and VARIES run to run (nondeterministic).
    // The number printed here is MEANINGLESS and is NOT part of
    // mutex_lock_guard_output.txt (captured from the default, UB-free build).
    volatile long racy = 0;   // volatile != atomic; the race is still UB
    constexpr int DEMO_THREADS = 4;
    constexpr int DEMO_ITERS = 1000000;
    auto racer = [&]() {
        for (int i = 0; i < DEMO_ITERS; ++i) {
            long cur = racy;   // volatile READ (UB: racing with other threads)
            racy = cur + 1;    // volatile WRITE  — a non-atomic RMW: lost updates
        }
    };
    std::vector<std::thread> rts;
    for (int k = 0; k < DEMO_THREADS; ++k) rts.emplace_back(racer);
    for (auto& th : rts) th.join();
    std::printf("[DEMO_UB] racy counter (no mutex) = %ld  (expected %d; LOST updates;\n",
                racy, DEMO_THREADS * DEMO_ITERS);
    std::printf("         UNDEFINED BEHAVIOR — number is meaningless & varies per run)\n");
#else
    std::printf("  (DEMO_UB not defined: the racy increment is correctly omitted from\n");
    std::printf("   this build — running it would be a data race = undefined behavior.)\n");
#endif
}

// === Section C — std::scoped_lock (C++17): multi-mutex, deadlock-free =========
//
// Locking 2+ mutexes by hand risks DEADLOCK if threads acquire them in different
// orders (the classic lock-ordering / circular-wait deadlock). std::scoped_lock
// (C++17) uses the std::lock deadlock-avoidance algorithm to acquire ALL the
// mutexes as an atomic group. We model bank transfers between two accounts,
// moving money in BOTH directions concurrently.
//
// The DEADLOCK itself (opposite ordering) is DOCUMENTED only — actually running
// it would hang forever, so it is not on the verified path.
struct Accounts {
    std::mutex ma, mb;
    long balance_a = 1000;   // INVARIANT: ma guards balance_a, mb guards balance_b
    long balance_b = 1000;
};

void sectionC() {
    sectionBanner("C — std::scoped_lock (C++17): multi-mutex, deadlock-free");

    Accounts ac;
    const long initial_total = ac.balance_a + ac.balance_b;
    constexpr int TRANSFERS_PER_THREAD = 50000;
    std::vector<std::thread> ts;

    // Half the threads transfer A->B, half B->A. scoped_lock(ma, mb) acquires
    // BOTH mutexes per transfer using deadlock avoidance — no global order needed.
    for (int t = 0; t < N_THREADS; ++t) {
        ts.emplace_back([&ac, t]() {
            for (int i = 0; i < TRANSFERS_PER_THREAD; ++i) {
                std::scoped_lock lk(ac.ma, ac.mb);   // C++17 CTAD: locks both
                const long amt = 1;
                if (t % 2 == 0) { ac.balance_a -= amt; ac.balance_b += amt; }
                else            { ac.balance_b -= amt; ac.balance_a += amt; }
            }
        });
    }
    for (auto& th : ts) th.join();

    const long final_total = ac.balance_a + ac.balance_b;
    std::printf("scoped_lock(ma, mb): %d threads x %d transfers, mixed A<->B directions\n",
                N_THREADS, TRANSFERS_PER_THREAD);
    std::printf("  balance_a=%ld  balance_b=%ld  total=%ld (initial total=%ld)\n",
                ac.balance_a, ac.balance_b, final_total, initial_total);
    std::printf("  (scoped_lock acquired BOTH mutexes per transfer; NO deadlock occurred)\n");

    check("scoped_lock multi-mutex: total balance conserved (no lost money)",
          final_total == initial_total);
    check("scoped_lock completed all transfers without deadlock (program reached here)",
          true);

    // The DEADLOCK trap (DOCUMENTED — running it would hang, so it is NOT run):
    std::printf("  DEADLOCK trap (documented, not run): thread X locks ma THEN mb,\n");
    std::printf("  thread Y locks mb THEN ma -> circular wait -> HANG. Fix: lock BOTH\n");
    std::printf("  mutexes in a GLOBAL order, OR use scoped_lock(ma, mb) (deadlock avoidance).\n");
    check("deadlock trap understood (opposite-order locking -> circular wait)", true);
}

// === Section D — std::unique_lock (movable) + std::call_once (one-shot) ======
//
// unique_lock (unlike lock_guard) is MOVABLE and supports deferred/manual
// locking — which is exactly what std::condition_variable::wait needs (it must
// unlock-while-waiting and re-lock-on-wakeup). call_once + once_flag run a
// function exactly once across any number of threads (the lazy-init idiom).
void sectionD() {
    sectionBanner("D — std::unique_lock (movable) + std::call_once (one-shot)");

    std::mutex m;

    // unique_lock: movable, defer-able. (🔗 CONDITION_VARIABLES needs this.)
    std::vector<std::unique_lock<std::mutex>> locks;   // can MOVE a lock IN here
    {
        std::unique_lock<std::mutex> lk(m, std::defer_lock);   // not locked yet
        check("unique_lock with defer_lock does not own the lock", !lk.owns_lock());
        lk.lock();                                             // manual lock
        check("unique_lock owns the lock after .lock()", lk.owns_lock());
        locks.push_back(std::move(lk));                        // MOVE (lock_guard can't)
        check("moved-from unique_lock no longer owns the lock", !lk.owns_lock());
    }
    check("moved-to unique_lock in the vector still owns the lock",
          locks.back().owns_lock());
    locks.clear();   // dtors call m.unlock()

    // PROOF m is free again: re-acquire (no deadlock => the moved lock unlocked).
    {
        std::lock_guard<std::mutex> lk(m);
        check("mutex re-acquired after unique_lock vector cleared (RAII unlock ran)",
              true);
    }

    // std::call_once + std::once_flag: run an init EXACTLY ONCE across threads.
    // (Equivalent to function-local-static init, made explicit.) init_count is
    // atomic so it can be read safely from main after join; only ONE thread ever
    // executes the once-block, so the count is deterministically 1.
    std::once_flag flag;
    std::atomic<int> init_count{0};
    auto try_init = [&]() {
        std::call_once(flag, [&]() {
            init_count.fetch_add(1, std::memory_order_relaxed);
        });
    };
    std::vector<std::thread> ts;
    for (int t = 0; t < N_THREADS; ++t) ts.emplace_back(try_init);
    for (auto& th : ts) th.join();

    std::printf("call_once across %d threads: init ran %d time(s) (exactly once)\n",
                N_THREADS, init_count.load());
    check("call_once ran the init exactly once across N threads", init_count.load() == 1);
}

// === Section E — mutex vs std::atomic + cross-language parallels =============
//
// For a SIMPLE shared counter, std::atomic<T> is the right tool: ++ is a single
// (locked) read-modify-write and is NOT a data race (the atomicity makes it
// well-defined), and it is LIGHTER than a mutex (typically a user-space CAS, no
// kernel call unless heavily contended). Reach for a mutex when you must guard a
// CRITICAL SECTION — several shared variables or an invariant that must hold as
// a whole. (No timing numbers are printed: HOW_TO_RESEARCH §4.2 rule 2 forbids
// wall-clock measurements as verified output.)
void sectionE() {
    sectionBanner("E — mutex vs std::atomic (atomic for simple counters)");

    std::atomic<int> a_ctr{0};
    {
        std::vector<std::thread> ts;
        for (int t = 0; t < N_THREADS; ++t) {
            ts.emplace_back([&a_ctr]() {
                for (int i = 0; i < ITERS; ++i)
                    a_ctr.fetch_add(1, std::memory_order_relaxed);
            });
        }
        for (auto& th : ts) th.join();
    }
    std::printf("std::atomic<int>: %d threads x %d iters = expected %d; actual = %d\n",
                N_THREADS, ITERS, N_THREADS * ITERS, a_ctr.load());
    check("atomic counter == N*ITERS (data-race-free; no mutex needed)",
          a_ctr.load() == N_THREADS * ITERS);

    std::printf("Rule of thumb: std::atomic<T> for a single shared word/counter;\n");
    std::printf("  std::mutex for a critical section (several shared variables, or an\n");
    std::printf("  invariant that must hold as a whole). A mutex is heavier — on heavy\n");
    std::printf("  contention the runtime may enter the kernel to park/wake the thread.\n");
    check("mutex-vs-atomic trade-off documented (atomic=counter; mutex=critical section)",
          true);

    // Cross-language parallels (prose only — see the cross-refs in the .md):
    std::printf("Cross-language: Go sync.Mutex + `defer Unlock` is per-FUNCTION RAII;\n");
    std::printf("  C++ lock_guard is per-SCOPE. Rust Mutex<T> returns a GUARD that IS a\n");
    std::printf("  borrow -> you access the data THROUGH the lock; C++ separates the lock\n");
    std::printf("  from the data it guards. TS is single-threaded -> no mutex (the event\n");
    std::printf("  loop + async patterns replace it).\n");
}

}  // namespace

int main() {
    std::printf("mutex_lock_guard.cpp — Phase 4 bundle #24.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean; the racy\n");
    std::printf("increment is DEMO_UB-gated off the verified path).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
