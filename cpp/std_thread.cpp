// std_thread.cpp — Phase 4 bundle #1 (Concurrency & the Memory Model).
//
// GOAL (one line): show, by COLLECTING every result into a mutex-protected
// container and printing from main AFTER all threads join, how std::thread spawns
// a 1:1 OS thread, how join()/detach() manage its lifetime, how arguments are
// decayed+moved (std::ref for references), and how a joinable thread destroyed
// without join/detach calls std::terminate — pinning the data-race-is-UB link as
// a documented preview (ATOMICS_MEMORY_ORDER owns the deep dive).
//
// This is the GROUND TRUTH for STD_THREAD.md. Every value below is computed by
// this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// DETERMINISM (§4.2 rule 4): thread OUTPUT ORDER is nondeterministic, so NO
// worker thread ever prints. Every worker pushes its result into a mutex-
// protected container; main SORTS and prints AFTER all threads join. This makes
// `just out` byte-identical across runs.
//
// SAFETY: all shared state is mutex- or join-synchronized, so ASan/UBSan AND TSan
// are clean (no data race). The deliberate racy demo is #ifdef DEMO_RACE-gated
// and never compiled by `just run/out/check/sanitize`.
//
// Run:
//     just run std_thread   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                              std_thread.cpp -o /tmp/cpp_std_thread
//                              && /tmp/cpp_std_thread)

#include <algorithm>   // std::sort
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <mutex>       // std::mutex / std::lock_guard
#include <string>      // std::string
#include <thread>      // std::thread / std::this_thread
#include <utility>     // std::pair
#include <vector>      // std::vector

namespace {

constexpr int BANNER_WIDTH = 70;

// sectionBanner prints a clearly delimited section divider (the house style).
void sectionBanner(const char* title) {
    char bar[BANNER_WIDTH + 1];
    std::memset(bar, '=', BANNER_WIDTH);
    bar[BANNER_WIDTH] = '\0';
    std::printf("\n%s\nSECTION %s\n%s\n", bar, title, bar);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it prints to stderr and exits non-zero so `just check`/`just sweep`
// catch it (and ASan/UBSan stay happy — no throw across the verified path).
void check(const char* description, bool ok) {
    if (!ok) {
        std::fprintf(stderr, "INVARIANT VIOLATED: %s\n", description);
        std::exit(EXIT_FAILURE);
    }
    std::printf("[check] %s: OK\n", description);
}

// A tiny piece of "work" a worker thread does. Pure + deterministic so the
// collect+sort+join output is byte-identical across runs.
long long squarePlusOffset(int n, int offset) {
    return static_cast<long long>(n) * n + offset;
}

// === Section A — spawn + join; joinable(); the destruct-terminate trap ========
//
// std::thread t(fn, args...) spawns a 1:1 OS thread (kernel-scheduled; unlike Go's
// M:N goroutines). t.join() BLOCKS until it finishes AND establishes a happens-
// before edge (main then sees the thread's writes). A joinable thread destroyed
// without join/detach calls std::terminate -> std::abort (no exception).
void sectionA() {
    sectionBanner("A — spawn + join; joinable(); the destruct-terminate trap");

    std::printf("std::thread t(fn, args...); spawns a 1:1 OS thread running fn(args...).\n");
    std::printf("t.join() blocks until t finishes; join SYNCHRONIZES (main then sees the\n");
    std::printf("thread's writes — a happens-before edge). joinable() is true until join/detach.\n");

    // (1) A worker computes a result and pushes it under a mutex. Main NEVER reads
    //     the shared vector until AFTER the join — the join supplies the happens-
    //     before edge that makes the read race-free.
    std::mutex mtx;
    std::vector<long long> results;

    {
        std::thread t([&mtx, &results] {
            long long r = squarePlusOffset(7, 100);   // 7*7 + 100 == 149
            std::lock_guard<std::mutex> lk(mtx);
            results.push_back(r);
        });
        std::printf("\n(1) spawned a worker; before join: t.joinable() = %s\n",
                    t.joinable() ? "true" : "false");
        check("a spawned std::thread is joinable() before join/detach", t.joinable());
        t.join();  // synchronizes: worker writes happen-before main's reads below
        std::printf("    after  join: t.joinable() = %s  (results.size = %zu)\n",
                    t.joinable() ? "true" : "false", results.size());
        check("after join, t.joinable() == false", !t.joinable());
    }  // t destroyed here; safe (not joinable after join)

    // (2) Main reads the worker's result AFTER the join — race-free.
    std::printf("\n(2) main reads the worker's result AFTER join (join = happens-before):\n");
    std::printf("    squarePlusOffset(7, 100) = 7*7 + 100 = %lld\n", results[0]);
    check("the worker ran and pushed 7*7+100 == 149",
          !results.empty() && results[0] == 149);
    check("join synchronizes: main safely reads the worker's write after join",
          results[0] == 149);

    // (3) THE destruct-terminate TRAP (documented, NOT executed in the verified path).
    //     A std::thread that is still joinable when its destructor runs calls
    //     std::terminate -> std::abort. NO exception is thrown; the program dies.
    //     The ONLY safe options at end-of-scope are: join() (wait) or detach()
    //     (release). (std::jthread (C++20) joins on destruction — the RAII fix.)
    std::printf("\n(3) THE destruct-terminate TRAP (documented, NOT run):\n");
    std::printf("    a joinable std::thread destroyed -> std::terminate -> std::abort.\n");
    std::printf("    No exception. Always join() or detach() before end-of-scope, OR use\n");
    std::printf("    std::jthread (C++20), which joins on destruction (the RAII fix).\n");
    std::printf("    // WHAT NOT TO DO (compiled only with -DDEMO_UB):\n");
    std::printf("    //   { std::thread t2([]{}); }  // <- ~thread sees joinable -> terminate\n");
    check("the destruct-terminate trap is documented (not executed)", true);

#ifdef DEMO_UB
    // Would call std::terminate at scope exit. NEVER enabled by just run/out/check/sanitize.
    std::thread t2([]{});
    (void)t2;  // intentionally no join/detach: ~thread -> std::terminate
#endif
}

// === Section B — detach (independent) + passing args (decay+move, std::ref) ===
//
// t.detach() releases the thread to run INDEPENDENTLY; t is no longer joinable and
// no longer has an id. Lifetime peril: a detached thread must not touch destroyed
// state. Arguments are DECAYED + MOVED into the thread (a reference arg needs
// std::ref / std::cref).
void sectionB() {
    sectionBanner("B — detach; passing args (decay+move, std::ref)");

    std::printf("t.detach() releases the thread to run INDEPENDENTLY; t is no longer joinable\n");
    std::printf("and no longer has an id. The thread keeps running until it returns or the\n");
    std::printf("program exits. LIFETIME PERIL: a detached thread must not touch state that\n");
    std::printf("has been destroyed (automatics of the spawning scope, statics at shutdown).\n");

    // (1) Detach demo. The detached worker writes its result + a done flag under a
    //     mutex. Main busy-waits (lock-check-unlock-yield) until done, then reads
    //     the result. Since join() is NOT called, the mutex must supply the
    //     happens-before edge (this is the safe way to sync with a detached thread).
    std::printf("\n(1) detached worker writes a mutex-protected result + done flag;\n");
    std::printf("    main busy-waits (lock-check-unlock-yield) until done -> safe sync.\n");

    std::mutex mtx;
    bool done = false;
    long long detachedResult = 0;

    {
        std::thread t([&mtx, &done, &detachedResult] {
            long long r = squarePlusOffset(11, 7);   // 11*11 + 7 == 128
            std::lock_guard<std::mutex> lk(mtx);
            detachedResult = r;
            done = true;
        });
        std::printf("    before detach: t.joinable() = %s\n", t.joinable() ? "true" : "false");
        t.detach();
        std::printf("    after  detach: t.joinable() = %s, get_id() == default id = %s\n",
                    t.joinable() ? "true" : "false",
                    (t.get_id() == std::thread::id{}) ? "true" : "false");
        check("after detach, t.joinable() == false", !t.joinable());
        check("after detach, t.get_id() == thread::id{} (no associated thread)",
              t.get_id() == std::thread::id{});
    }  // t destroyed here; safe (was detached, not joinable)

    // Main busy-waits for the detached worker. yield() hands the CPU back to the
    // scheduler so the worker can run. Every `done` access is mutex-protected.
    while (true) {
        {
            std::lock_guard<std::mutex> lk(mtx);
            if (done) break;
        }
        std::this_thread::yield();
    }
    std::printf("    main observed done==true; detachedResult = %lld\n", detachedResult);
    check("the detached thread ran; main observed its result via mutex-sync",
          detachedResult == 128);

    // (2) PASSING ARGUMENTS: by default they are DECAYED + MOVED into the thread.
    //     The forwarding is std::decay + std::move (NOT perfect forwarding), so a
    //     `const char*` literal decays, an array decays to a pointer, a top-level
    //     const is dropped, and a reference is NOT forwarded as a reference — to
    //     pass a reference (so the worker can mutate the caller's variable) you
    //     MUST wrap it in std::ref / std::cref.
    std::printf("\n(2) PASSING ARGS: by default DECAYED + MOVED into the thread.\n");
    std::printf("    To pass a reference (so the worker can mutate the caller's variable),\n");
    std::printf("    wrap it in std::ref / std::cref — otherwise it is copied/moved.\n");

    // (2a) By-value std::string arg: the worker receives its OWN copy (the caller's
    //      string is untouched). Mutating the worker's copy changes nothing outside.
    std::string caller_msg = "hello";
    long long worker_local_size = 0;
    {
        std::thread t([&worker_local_size](std::string s) {
            s += " from worker";                  // mutates the worker's LOCAL copy
            worker_local_size = static_cast<long long>(s.size());
        }, caller_msg);                           // caller_msg passed as an ARG -> copy/move
        t.join();
    }
    std::printf("    (2a) caller_msg = \"%s\"; worker appended \" from worker\" to ITS copy.\n",
                caller_msg.c_str());
    std::printf("         caller's string unchanged (size %zu); worker's local size = %lld\n",
                caller_msg.size(), worker_local_size);
    check("by-value std::string arg: caller's string unchanged (worker got a copy)",
          caller_msg == "hello" && caller_msg.size() == 5);
    check("worker's local copy was \"hello from worker\" (size 17)",
          worker_local_size == 17);

    // (2b) std::ref(counter): the worker receives a REFERENCE to the caller's int.
    //      Without std::ref, the int would be copied (and the worker's += 100 would
    //      vanish at thread exit). With std::ref, the caller's int is mutated.
    int counter = 0;
    {
        std::thread t([](int& r) {
            r += 100;
        }, std::ref(counter));
        t.join();
    }
    std::printf("    (2b) int counter = 0; worker did r += 100 with std::ref(counter);\n");
    std::printf("         caller's counter = %d  (std::ref passed a reference)\n", counter);
    check("std::ref passes a reference: worker mutated the caller's counter to 100",
          counter == 100);

    // (3) The LIFETIME PERIL of a detached thread (documented, not run).
    std::printf("\n(3) LIFETIME PERIL of a detached thread (documented, not run):\n");
    std::printf("    If the spawning scope returns before the detached thread finishes, any\n");
    std::printf("    reference/pointer to its automatics dangles -> use-after-free (UB).\n");
    std::printf("    Rule: a detached thread must touch ONLY state whose lifetime it does\n");
    std::printf("    NOT depend on (heap that outlives it, statics, copied-in values).\n");
    check("the detached-thread lifetime peril is documented (not executed)", true);
}

// === Section C — thread::id/get_id + hardware_concurrency + collect+sort+join =
void sectionC() {
    sectionBanner("C — thread::id/get_id, hardware_concurrency, collect+sort+join");

    std::printf("thread::id is the opaque identifier of a thread; get_id() returns it.\n");
    std::printf("Two ids compare equal iff they identify the same thread. The default-\n");
    std::printf("constructed thread::id{} identifies NO thread (a joined/detached thread).\n");
    std::printf("Streaming with operator<< is allowed but impl-defined — we DON'T print the\n");
    std::printf("value here (it varies across runs); we rely on == / != only.\n");

    // (1) Two threads have DIFFERENT ids. We do NOT print the streamed id (it is
    //     impl-defined and varies across runs); only its (in)equality is stable.
    std::thread::id main_id = std::this_thread::get_id();
    std::thread::id worker_id{};
    {
        std::thread t([&worker_id] {
            worker_id = std::this_thread::get_id();
        });
        t.join();
        check("a joined thread's get_id() == thread::id{} (no associated thread)",
              t.get_id() == std::thread::id{});
    }
    std::printf("\n(1) main's get_id() and the worker's get_id() differ (ids NOT shown;\n");
    std::printf("    streamed representation is impl-defined and varies across runs).\n");
    check("main's thread::id != worker's thread::id (two distinct threads)",
          main_id != worker_id);

    // (2) hardware_concurrency(): a HINT at the parallel width (number of concurrent
    //     threads the implementation claims to support). May return 0 if "not
    //     computable or ill-defined." We print but do NOT assert the value (varies
    //     per machine).
    const unsigned int hw = std::thread::hardware_concurrency();
    std::printf("\n(2) std::thread::hardware_concurrency() = %u  (hint; may be 0; not asserted)\n",
                hw);

    // (3) COLLECT + SORT + JOIN — the deterministic-output discipline (§4.2 rule 4).
    //     Spawn N threads; each pushes {input, output} into a mutex-protected
    //     vector; main joins ALL, then SORTS and prints. The arrival order is
    //     nondeterministic; the SORTED output is byte-identical across runs.
    constexpr int N = 6;
    std::mutex mtx;
    std::vector<std::pair<int, long long>> collected;
    collected.reserve(static_cast<std::size_t>(N));

    std::printf("\n(3) COLLECT + SORT + JOIN: spawn %d workers; each pushes {n, n*n+n}\n", N);
    std::printf("    into a mutex-protected vector; main joins all, SORTS, prints.\n");

    std::vector<std::thread> pool;
    pool.reserve(static_cast<std::size_t>(N));
    for (int i = 1; i <= N; ++i) {
        pool.emplace_back([&mtx, &collected, i] {
            long long r = squarePlusOffset(i, i);    // i*i + i
            std::lock_guard<std::mutex> lk(mtx);
            collected.emplace_back(i, r);
        });
    }
    for (auto& th : pool) th.join();
    std::sort(collected.begin(), collected.end());   // kill arrival-order nondeterminism

    std::printf("    sorted results (n, n*n+n):\n");
    for (const auto& [n, r] : collected) {
        std::printf("      n=%d  ->  %lld\n", n, r);
    }
    check("collected exactly N results after all joined",
          static_cast<int>(collected.size()) == N);

    bool sorted_ok = true;
    for (int i = 0; i < N; ++i) {
        const auto& entry = collected[static_cast<std::size_t>(i)];
        int expected_n = i + 1;
        long long expected_r = static_cast<long long>(expected_n) * expected_n + expected_n;
        if (entry.first != expected_n || entry.second != expected_r) {
            sorted_ok = false;
            break;
        }
    }
    check("the sorted set is the deterministic {n, n*n+n} for n=1..6 (NOT arrival order)",
          sorted_ok);
}

// === Section D — the DATA RACE is UB link (preview; ATOMICS owns the deep dive) =
//
// A data race: 2+ threads access the same memory location, at least one is a
// write, and they're unsynchronized. That's UB. ASan/UBSan do NOT catch races;
// TSan (-fsanitize=thread) does. This bundle keeps ALL sharing mutex/join-synced
// so even TSan is clean. The racy demo is #ifdef DEMO_RACE-gated (never compiled).
void sectionD() {
    sectionBanner("D — the data-race-is-UB link (preview; ATOMICS_MEMORY_ORDER owns it)");

    std::printf("A DATA RACE: two+ threads access the SAME memory location, at least one is a\n");
    std::printf("WRITE, and they are NOT synchronized (no mutex, no atomic, no join/happens-\n");
    std::printf("before edge). The C++ standard makes this UNDEFINED BEHAVIOR (§4.2 rule 5).\n");
    std::printf("ASan/UBSan do NOT catch data races — ThreadSanitizer (-fsanitize=thread) does.\n");
    std::printf("This bundle keeps ALL sharing mutex/join-synchronized so even TSan is clean.\n");

    std::printf("\n    // WHAT NOT TO DO (compiled only with -DDEMO_RACE):\n");
    std::printf("    //   int counter = 0;\n");
    std::printf("    //   std::thread t1([&]{ for (int i=0;i<100000;++i) ++counter; });  // UB!\n");
    std::printf("    //   std::thread t2([&]{ for (int i=0;i<100000;++i) ++counter; });  // UB!\n");
    std::printf("    //   t1.join(); t2.join();  // counter < 200000 (lost updates) AND UB.\n");
    std::printf("    // Fix: std::mutex + lock_guard, OR std::atomic<int> (acquire/release).\n");
    check("the data-race-is-UB preview is documented (not executed)", true);

#ifdef DEMO_RACE
    // Would-be UB: two threads ++counter with NO synchronization. NEVER compiled
    // by `just run/out/check/sanitize`. TSan would flag it; the final value is
    // nondeterministic and meaningless (lost updates + the race itself is UB).
    int counter = 0;
    std::thread t1([&counter]{ for (int i = 0; i < 100000; ++i) ++counter; });
    std::thread t2([&counter]{ for (int i = 0; i < 100000; ++i) ++counter; });
    t1.join(); t2.join();
    std::printf("[DEMO_RACE] counter = %d (nondeterministic; lost updates; UB)\n", counter);
#endif

    // The SAFE version (what this bundle does everywhere): mutex-guarded increment.
    {
        std::mutex mtx;
        long long total = 0;
        std::vector<std::thread> pool;
        pool.reserve(4);
        for (int i = 0; i < 4; ++i) {
            pool.emplace_back([&mtx, &total] {
                std::lock_guard<std::mutex> lk(mtx);
                total += 1000;
            });
        }
        for (auto& th : pool) th.join();
        std::printf("\nThe SAFE version (mutex-protected increment): 4 threads * 1000 = %lld\n",
                    total);
        check("mutex-protected increment is race-free: 4*1000 == 4000", total == 4000);
    }
}

}  // namespace

int main() {
    std::printf("std_thread.cpp — Phase 4 bundle #1 (Concurrency & the Memory Model).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free AND race-free (just sanitize clean;\n");
    std::printf("TSan-clean too — all sharing is mutex/join-synchronized).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionBanner("DONE — all sections printed");
}
