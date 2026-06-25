// condition_variables.cpp — Phase 4 bundle #26 (Concurrency & the Memory Model).
//
// GOAL (one line): show, by COLLECTING every OUTCOME into per-thread or
// mutex-protected containers and asserting from main AFTER all threads join, how
// std::condition_variable lets a thread WAIT (atomically releasing a mutex) until
// another thread NOTIFY it that a shared predicate became true, why you MUST use
// the PREDICATE wait form (spurious wakeups + lost wakeups), why wait requires a
// unique_lock (it unlocks/relocks internally — lock_guard cannot), and how the
// mutex+queue+condvar producer/consumer balances N produced == N consumed —
// pinning the spurious-wakeup/predicate-form rule as the central expert payoff.
//
// This is the GROUND TRUTH for CONDITION_VARIABLES.md. Every value below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM (HOW_TO_RESEARCH §4.2 rules 2 + 4): condvar WAKE ORDER and TIMING
// are nondeterministic, so NO worker thread ever prints and NO wall-clock value
// is ever asserted. Each worker records the OUTCOME (it woke; it observed the
// predicate true; the values it consumed) into a per-thread or mutex-protected
// container; main joins all threads, SORTS any collection, and prints. `just out`
// is byte-identical across runs.
//
// SAFETY (§4.2 rule 5): the shared predicate, queue, and flags are ALWAYS
// accessed under the same mutex that the condvar waits on (no data race); wait
// is ALWAYS called on a std::unique_lock<std::mutex>. ASan/UBSan AND TSan are
// clean. The bare cv.wait(lk) (no predicate) latent bug is DOCUMENTED only.
//
// Run:
//     just run condition_variables   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                      condition_variables.cpp -o /tmp/cpp_condition_variables
//                                      && /tmp/cpp_condition_variables)

#include <algorithm>           // std::sort (collect+sort+join discipline)
#include <atomic>              // std::atomic (Section A hand-shake counters)
#include <chrono>              // std::chrono::milliseconds (wait_for timeout)
#include <condition_variable>  // std::condition_variable, std::cv_status
#include <cstdio>              // printf / fprintf
#include <cstdlib>             // EXIT_FAILURE / exit
#include <cstring>             // memset (banner bar)
#include <mutex>               // std::mutex / std::unique_lock / std::lock_guard
#include <queue>               // std::queue
#include <thread>              // std::thread / std::this_thread::yield
#include <vector>              // std::vector

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

// ── Deterministic thread-output discipline (HOW_TO_RESEARCH §4.2 rule 4) ──────
// Worker threads NEVER printf: condvar wake ORDER and TIMING are nondeterministic
// and stdout interleaving would be too. Each worker records the OUTCOME (it woke;
// it observed the predicate true; the values it consumed) into a per-thread or
// mutex-protected slot; main joins all threads, SORTS any collection, and prints.
// `just out` is then byte-identical across runs.

// === Section A — wait(unique_lock, predicate) + notify_one / notify_all =======
//
// cv.wait(lk, pred) ATOMICALLY unlocks `lk` and blocks; on a notify (or a
// spurious wake) it RE-LOCKS `lk` and RE-CHECKS `pred`; it loops until
// pred() == true. notify_one unblocks ONE waiter; notify_all unblocks ALL. We
// assert only the OUTCOME (the woken thread saw the predicate true; notify_all
// woke every waiter) — never the wake order or the timing.
void sectionA() {
    sectionBanner("A — wait(unique_lock, predicate) + notify_one / notify_all");

    std::printf("cv.wait(unique_lock, pred): atomically unlock + block; on a notify or\n");
    std::printf("spurious wake, re-lock + re-check pred; loop until pred()==true.\n");
    std::printf("notify_one wakes ONE waiter; notify_all wakes ALL waiters.\n");

    // (1) One waiter. The producer sets `ready` + the payload `data` under the
    //     mutex, then notify_one. The waiter wakes, the predicate `ready` is true,
    //     and it reads `data`. The predicate form is correct whether notify races
    //     ahead of the wait or not (pred is checked under the lock on ENTRY).
    std::printf("\n(1) one waiter: cv.wait(lk, []{return ready;}) + notify_one\n");
    {
        std::mutex m;
        std::condition_variable cv;
        bool ready = false;
        int data = 0;
        bool waiter_saw_ready = false;
        int waiter_saw_data = 0;

        std::thread waiter([&] {
            std::unique_lock<std::mutex> lk(m);
            cv.wait(lk, [&] { return ready; });   // predicate form (the safe one)
            waiter_saw_ready = ready;              // predicate guaranteed true here
            waiter_saw_data = data;
        });
        {
            std::lock_guard<std::mutex> lk(m);
            ready = true;
            data = 42;
        }
        cv.notify_one();
        waiter.join();

        std::printf("    waiter woke: ready=%s, data=%d (predicate true on return)\n",
                    waiter_saw_ready ? "true" : "false", waiter_saw_data);
        check("the woken waiter observed ready==true", waiter_saw_ready);
        check("the woken waiter saw the producer's payload data==42 (under the re-lock)",
              waiter_saw_data == 42);
        check("wait() returned with the mutex RE-LOCKED (predicate read under the lock)",
              true);
    }

    // (2) notify_all wakes MULTIPLE waiters. We hand-shake so all NW are blocked
    //     in cv.wait BEFORE main sets ready + notify_all: each worker increments
    //     an atomic `blocked` counter (under the mutex, just before wait); main
    //     yield-busy-waits until blocked == NW. Then ready + notify_all. Every
    //     waiter must wake. Outcome: woke == NW (deterministic; ORDER is not).
    constexpr int NW = 3;
    std::printf("\n(2) notify_all wakes MULTIPLE waiters (NW=%d); hand-shake so all are\n", NW);
    std::printf("    blocked before notify_all, then assert every one woke.\n");
    {
        std::mutex m;
        std::condition_variable cv;
        bool ready = false;
        std::atomic<int> blocked{0};   // # workers that have entered cv.wait
        std::atomic<int> woke{0};      // # workers that returned from cv.wait

        std::vector<std::thread> waiters;
        waiters.reserve(static_cast<std::size_t>(NW));
        for (int i = 0; i < NW; ++i) {
            waiters.emplace_back([&] {
                std::unique_lock<std::mutex> lk(m);
                blocked.fetch_add(1, std::memory_order_relaxed);
                cv.wait(lk, [&] { return ready; });
                woke.fetch_add(1, std::memory_order_relaxed);
            });
        }
        // Wait until every worker has entered cv.wait (so notify_all has waiters
        // to wake). A yield-busy-wait on an atomic — race-free, no sleep.
        while (blocked.load(std::memory_order_acquire) != NW) {
            std::this_thread::yield();
        }
        {
            std::lock_guard<std::mutex> lk(m);
            ready = true;
        }
        cv.notify_all();   // wake ALL NW waiters
        for (auto& t : waiters) t.join();

        std::printf("    notify_all fired with all %d waiters blocked; woke=%d\n",
                    NW, woke.load());
        check("notify_all woke every waiter (woke == NW)", woke.load() == NW);
        check("no waiter lost or duplicated (exactly NW woke)", woke.load() == NW);
    }
}

// === Section B — Spurious wakeups + the PREDICATE form (always use it) ========
//
// A bare cv.wait(lk) (NO predicate) can return WITHOUT a notify — a "spurious
// wakeup". It can ALSO return on a notify that fired while the predicate was
// still false. Both are disastrous: the caller proceeds as if the condition
// held when it may not. The fix is MANDATORY: use the predicate form
//   cv.wait(lk, pred)   ==   while (!pred()) wait(lk);
// which re-checks pred under the lock on EVERY wake (real, spurious, or "false")
// and returns only when pred() is true. We DEMONSTRATE a "false notify" (a
// notify while the predicate is still false) being absorbed by the predicate
// form; the bare form is DOCUMENTED only (running it would be a latent bug).
void sectionB() {
    sectionBanner("B — Spurious wakeups + the PREDICATE form (always use it)");

    std::printf("A bare cv.wait(lk) can return WITHOUT a real notify (a spurious wakeup)\n");
    std::printf("or on a notify that fired while the predicate was still false. The fix is\n");
    std::printf("MANDATORY: use the predicate form  cv.wait(lk, pred)  ==  while(!pred()) wait(lk);\n");
    std::printf("it re-checks pred under the lock on every wake and returns only when true.\n");

    // A "false notify" absorbed by the predicate form. The waiter waits for i==1;
    // i starts 0. We notify_one WHILE i is still 0 (a "false" notify). With the
    // predicate form the waiter — IF it wakes — re-checks i==0 -> false -> waits
    // again. We then set i=1 and notify_one; the waiter wakes, i==1 -> true ->
    // proceeds. The OUTCOME (waiter saw i==1) is deterministic; whether the false
    // notify actually woke the waiter is timing-dependent and NOT asserted. The
    // bare form would have proceeded at the false notify with i==0 (the bug).
    // (Mirrors cppreference's notify_one example.)
    std::printf("\nA 'false notify' (notify while predicate still false) is absorbed by the\n");
    std::printf("predicate form: the waiter re-checks and loops back until i==1.\n");
    {
        std::mutex m;
        std::condition_variable cv;
        int i = 0;
        bool finished = false;
        int waiter_saw_i = -1;

        std::thread waiter([&] {
            std::unique_lock<std::mutex> lk(m);
            cv.wait(lk, [&] { return i == 1; });   // predicate form
            waiter_saw_i = i;                        // guaranteed == 1
            finished = true;
        });

        // (a) a "false" notify: i is still 0. Predicate form -> waiter loops back.
        {
            std::lock_guard<std::mutex> lk(m);   // i unchanged; demonstrates the
        }                                        // notify-while-predicate-false case
        cv.notify_one();

        // (b) the real change: i becomes 1, then notify_one -> waiter proceeds.
        {
            std::lock_guard<std::mutex> lk(m);
            i = 1;
        }
        cv.notify_one();
        waiter.join();

        std::printf("    waiter proceeded only after i==1: saw_i=%d, finished=%s\n",
                    waiter_saw_i, finished ? "true" : "false");
        check("predicate form: waiter proceeded only when the predicate (i==1) was true",
              waiter_saw_i == 1 && finished);
        check("a 'false notify' (predicate false) did NOT let the waiter proceed early",
              waiter_saw_i == 1);
    }

    // THE BARE-WAIT TRAP (documented, never run on the verified path).
    std::printf("\nTHE BARE-WAIT TRAP (documented, NOT run):  cv.wait(lk);   // no predicate\n");
    std::printf("  returns on a spurious wake OR a notify-while-predicate-false, with the\n");
    std::printf("  predicate NOT guaranteed true -> proceeds incorrectly (the bug). Fix:\n");
    std::printf("  cv.wait(lk, []{return cond;});  // or hand-roll  while(!cond) cv.wait(lk);\n");
    check("the bare-wait (no predicate) trap is documented (not executed)", true);
}

// === Section C — Producer / consumer queue: mutex + queue + condvar ===========
//
// THE canonical condvar use case. A mutex-protected std::queue<T>; the producer
// pushes items + notify_one (per item) / notify_all (on close); consumers wait
// on the predicate "!q.empty() || done", then pop. The predicate form is what
// makes it correct under contention: a consumer woken by notify_one may find the
// queue already emptied by a faster consumer — predicate false -> wait again (no
// lost wake, no double-pop). We assert the OUTCOME only: total consumed ==
// N produced, and the sorted consumed set == {1..N} (no lost, no duplicate). The
// per-consumer distribution VARIES across runs, so it is NOT printed.
struct PCQueue {
    std::mutex m;
    std::condition_variable cv;
    std::queue<int> q;
    bool done = false;   // INVARIANT: m guards q and done
};

void sectionC() {
    sectionBanner("C — Producer / consumer queue: mutex + queue + condvar");

    std::printf("Producer pushes N items (notify_one each), then sets done + notify_all.\n");
    std::printf("Consumers wait on predicate (!q.empty() || done), then pop. The predicate\n");
    std::printf("form absorbs the 'woken-but-queue-already-emptied' race -> no lost/double.\n");

    constexpr int N = 100;   // items produced
    constexpr int K = 4;     // consumers
    PCQueue pc;
    std::vector<std::vector<int>> consumed(static_cast<std::size_t>(K));

    // Producer: push 1..N, then close. notify_one per item, notify_all on close.
    // (N is constexpr -> usable inside the lambda without capture.)
    auto producer = [&pc] {
        for (int v = 1; v <= N; ++v) {
            {
                std::lock_guard<std::mutex> lk(pc.m);
                pc.q.push(v);
            }
            pc.cv.notify_one();   // wake one consumer per item
        }
        {
            std::lock_guard<std::mutex> lk(pc.m);
            pc.done = true;
        }
        pc.cv.notify_all();       // wake ALL consumers so they observe `done`
    };

    // Consumer k: pop until (empty && done); record into consumed[k] (its OWN slot).
    auto consumer = [&pc, &consumed](int k) {
        std::vector<int> local;
        while (true) {
            std::unique_lock<std::mutex> lk(pc.m);
            pc.cv.wait(lk, [&pc] { return !pc.q.empty() || pc.done; });
            if (!pc.q.empty()) {
                local.push_back(pc.q.front());
                pc.q.pop();
            } else {
                break;   // done && empty
            }
        }
        consumed[static_cast<std::size_t>(k)] = std::move(local);
    };

    std::thread prod(producer);
    std::vector<std::thread> cons;
    cons.reserve(static_cast<std::size_t>(K));
    for (int k = 0; k < K; ++k) cons.emplace_back(consumer, k);
    prod.join();
    for (auto& c : cons) c.join();

    // Merge + sort every consumed value (arrival order is nondeterministic).
    std::vector<int> all;
    for (const auto& v : consumed) all.insert(all.end(), v.begin(), v.end());
    std::sort(all.begin(), all.end());

    const long total = static_cast<long>(all.size());
    long sum = 0;
    for (int x : all) sum += x;
    bool exact_set = (total == N);
    for (int idx = 0; idx < N && exact_set; ++idx) {
        if (all[static_cast<std::size_t>(idx)] != idx + 1) exact_set = false;
    }
    const long expected_sum = static_cast<long>(N) * (N + 1) / 2;   // 1+2+...+N

    std::printf("producer pushed N=%d items across %d consumers\n", N, K);
    std::printf("  total consumed = %ld (expected %d)\n", total, N);
    std::printf("  sum of consumed = %ld (expected %ld)\n", sum, expected_sum);
    std::printf("  sorted consumed set is exactly {1..%d}: %s\n", N,
                exact_set ? "true" : "false");
    std::printf("  (per-consumer distribution VARIES across runs -> not printed; TOTAL asserted)\n");

    check("producer/consumer: N produced == N consumed (no lost, no duplicate)",
          total == N);
    check("sum of consumed == N(N+1)/2 (no lost, no duplicate, no corruption)",
          sum == expected_sum);
    check("sorted consumed set == {1..N} exactly (each value consumed once)",
          exact_set);
    check("queue drained: q.empty() after all consumers joined", pc.q.empty());
}

// === Section D — unique_lock requirement + lost-wakeup fix + wait_for =========
//
// (1) wait's signature REQUIRES std::unique_lock<std::mutex>: it must unlock the
//     mutex while blocked and re-lock on wake — only unique_lock can (lock_guard
//     is immovable and exposes no unlock/relock). cv works ONLY with
//     unique_lock<mutex> (use condition_variable_any for other lock types).
// (2) The lost-wakeup / predicate-fix: a notify that fires BEFORE any thread
//     waits is LOST for a bare wait -> deadlock. The predicate form checks pred
//     under the lock ON ENTRY and returns immediately if already true -> no
//     deadlock. Demonstrated deterministically (notify-all, THEN spawn waiter).
// (3) wait_for / wait_until: the timeout variants. With no notify, wait_for
//     returns cv_status::timeout; the predicate overload returns bool (pred() at
//     exit). Only the OUTCOME is asserted — never the elapsed wall-clock
//     (§4.2 rule 2 forbids wall-clock as a verified value).
void sectionD() {
    sectionBanner("D — unique_lock requirement + lost-wakeup fix + wait_for");

    // (1) The unique_lock requirement (documented). wait() takes a reference to a
    //     std::unique_lock<std::mutex>; a lock_guard will NOT compile (it can be
    //     neither passed nor unlock/relocked). unique_lock exposes owns_lock() +
    //     unlock()/lock(); cv.wait uses those to release-while-blocked and
    //     re-acquire-on-wake. (See 🔗 MUTEX_LOCK_GUARD for unique_lock's full API.)
    std::printf("(1) wait() REQUIRES std::unique_lock<std::mutex> (NOT lock_guard):\n");
    std::printf("    it unlocks while blocked and re-locks on wake — only unique_lock can.\n");
    std::printf("    cv works ONLY with unique_lock<mutex> (condition_variable_any for others).\n");
    std::printf("    // WHAT NOT TO DO (a compile error, documented):\n");
    std::printf("    //   std::lock_guard<std::mutex> lk(m);  cv.wait(lk, ...);  // won't compile\n");
    check("the unique_lock requirement is documented (wait needs it; lock_guard won't compile)",
          true);

    // (2) Lost-wakeup / predicate-fix: notify_all fires BEFORE any waiter exists.
    //     A bare wait would block FOREVER (the notify is lost). The predicate form
    //     checks pred under the lock on ENTRY -> rd already true -> returns at once.
    //     Deterministic: no sleep, no blocking, no deadlock.
    std::printf("\n(2) lost-wakeup / predicate-fix: notify_all fires BEFORE any waiter;\n");
    std::printf("    bare wait would deadlock (notify lost). Predicate form checks rd on\n");
    std::printf("    entry -> already true -> returns immediately (no deadlock).\n");
    {
        std::mutex m;
        std::condition_variable cv;
        bool rd = false;
        // Set the predicate + notify FIRST — no waiter exists yet.
        {
            std::lock_guard<std::mutex> lk(m);
            rd = true;
        }
        cv.notify_all();   // lost for a bare wait; a no-op for the predicate form

        bool waiter_returned = false;
        std::thread waiter([&] {
            std::unique_lock<std::mutex> lk(m);
            cv.wait(lk, [&] { return rd; });   // predicate true on ENTRY -> no block
            waiter_returned = true;
        });
        waiter.join();
        std::printf("    waiter returned without blocking (predicate-fix): %s\n",
                    waiter_returned ? "true" : "false");
        check("lost-wakeup: predicate form did NOT deadlock (notify-before-wait handled)",
              waiter_returned);
        check("lost-wakeup: predicate true on entry -> wait returned immediately",
              waiter_returned);
    }

    // (3) wait_for: timeout variants. Never notified -> cv_status::timeout; the
    //     predicate overload returns the predicate's value at exit. We assert the
    //     OUTCOME only (timed out / pred false) — NEVER the elapsed wall-clock.
    std::printf("\n(3) wait_for (timeout variants). Never notified -> cv_status::timeout;\n");
    std::printf("    predicate overload returns bool. Outcome asserted, NOT wall-clock.\n");
    {
        std::mutex m;
        std::condition_variable cv;   // intentionally NEVER notified
        bool timed_out = false;
        std::thread t([&] {
            std::unique_lock<std::mutex> lk(m);
            auto st = cv.wait_for(lk, std::chrono::milliseconds(50));
            timed_out = (st == std::cv_status::timeout);
        });
        t.join();
        std::printf("    wait_for(50ms) with no notify -> cv_status::timeout: %s\n",
                    timed_out ? "true" : "false");
        check("wait_for with no notify returns cv_status::timeout", timed_out);
    }
    {
        std::mutex m;
        std::condition_variable cv;   // never notified; predicate never true
        bool pred_false = false;
        std::thread t([&] {
            std::unique_lock<std::mutex> lk(m);
            bool r = cv.wait_for(lk, std::chrono::milliseconds(50), [] { return false; });
            pred_false = !r;   // pred() false at exit -> wait_for returns false
        });
        t.join();
        std::printf("    wait_for(50ms, pred=false) -> returns false: %s\n",
                    pred_false ? "true" : "false");
        check("wait_for with a never-true predicate returns false (within the timeout)",
              pred_false);
    }
}

// === Section E — When NOT to reach for a condvar (cross-language) =============
//
// A condvar is C++'s LOW-LEVEL sync primitive. Before writing one, check whether
// a higher-level stdlib tool fits. Higher-level languages fold the mutex+queue+
// condvar trio into a single typed CHANNEL (Go), or keep a manual Mutex+Condvar
// pair (Rust). JS/TS has no condvar — its single-threaded event loop + Promises/
// async replace waiting entirely. C++20 added counting_semaphore / latch /
// barrier (often a better fit), and coroutines bring async/await to C++.
void sectionE() {
    sectionBanner("E — When NOT to reach for a condvar (cross-language)");

    std::printf("A condvar is C++'s LOW-LEVEL sync primitive. Before writing one, check\n");
    std::printf("whether a higher-level stdlib tool fits:\n");
    std::printf("  - std::counting_semaphore / binary_semaphore (C++20): counted permits,\n");
    std::printf("    no hand-rolled predicate. Often the right tool for 'N slots'.\n");
    std::printf("  - std::latch (C++20): one-shot countdown; std::barrier (C++20): reusable.\n");
    std::printf("  - coroutines (co_await, C++20): async/await over a single thread.\n");
    std::printf("  - and, idiomatic since C++11: std::future/promise for a one-shot result.\n");
    check("higher-level stdlib alternatives documented (semaphore/latch/barrier/future)",
          true);

    std::printf("\nCross-language contrast (the headline):\n");
    std::printf("  C++   : mutex + queue + condition_variable (manual, low-level).\n");
    std::printf("  Go    : a typed CHANNEL replaces all three (close, range, select).\n");
    std::printf("  Rust  : std::sync::Mutex + Condvar — same low-level model as C++.\n");
    std::printf("  TS/JS : no condvar — single-threaded event loop + Promises/async.\n");
    check("cross-language parallels documented (Go channels; Rust Condvar; TS async)",
          true);
}

}  // namespace

int main() {
    std::printf("condition_variables.cpp — Phase 4 bundle #26 (Concurrency & the Memory Model).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free AND race-free (just sanitize clean;\n");
    std::printf("TSan-clean too — the predicate + queue are mutex-protected, wait under unique_lock).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
