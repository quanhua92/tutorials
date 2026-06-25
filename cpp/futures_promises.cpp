// futures_promises.cpp — Phase 4 bundle (Concurrency & the Memory Model).
//
// GOAL (one line): show, by printing every RESULT, how std::async / std::promise /
// std::future / std::packaged_task / std::shared_future form C++'s one-shot async-
// result channel — pinning the launch-policy footgun (default may be deferred =
// NOT concurrent), the get()-twice-is-UB trap, and the destructor-of-a-future-from-
// async-blocks gotcha as DOCUMENTED expert payoffs (never executed in the verified
// path).
//
// This is the GROUND TRUTH for FUTURES_PROMISES.md. Every value below is computed
// by this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// DETERMINISM (§4.2 rule 4): the COMPUTED VALUE is deterministic; COMPLETION ORDER
// is not. So NO worker ever prints, and every assert checks the RESULT (the value
// N computed), never the timing/order. The launch-policy footgun is proven
// deterministically via thread-id == / != comparison (not streamed ids, which are
// impl-defined). Parallel output is COLLECTED + SORTED in main after all get()s.
//
// SAFETY: the shared state IS the synchronization (promise "synchronizes-with" the
// future's wait/get; get()/join() supply the happens-before edge). No raw shared
// state is touched by two threads unsynchronized, so ASan/UBSan (and TSan) are
// clean. The get()-twice UB demo is #ifdef DEMO_UB-gated and never compiled by
// `just run/out/check/sanitize`.
//
// Run:
//     just run futures_promises   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                   futures_promises.cpp -o /tmp/cpp_futures_promises
//                                   && /tmp/cpp_futures_promises)

#include <algorithm>   // std::sort
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar), strcmp
#include <exception>   // std::make_exception_ptr / std::current_exception
#include <future>      // std::async / std::future / std::promise / std::packaged_task / std::shared_future / std::launch
#include <stdexcept>   // std::runtime_error
#include <thread>      // std::thread / std::this_thread::get_id
#include <utility>     // std::pair / std::move
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

// A tiny piece of "work" a worker does. Pure + deterministic so the RESULT
// (never the completion order) is byte-identical across runs.
long long squarePlusOffset(int n, int offset) {
    return static_cast<long long>(n) * n + offset;
}

// === Section A — std::async (the easy API) + future::get() (blocks, returns, rethrows)
//
// std::async(policy, fn, args...) runs fn and returns a std::future<T> that will
// eventually hold the result. future::get() BLOCKS (synchronizes) until the result
// is ready, then returns it (as std::move). After get(), valid() is false; a second
// get() is UB. If fn THREW, get() RETHROWS that exception.
void sectionA() {
    sectionBanner("A — std::async + future::get (blocks, returns value, rethrows)");

    std::printf("std::async(policy, fn, args...) runs fn and returns a future<T>.\n");
    std::printf("future::get() BLOCKS until the result is ready, then returns it.\n");
    std::printf("After get(), valid() == false. A second get() is UNDEFINED BEHAVIOR.\n");
    std::printf("If fn threw, get() RETHROWS that exception.\n");

    // (1) async with launch::async (definitely a new thread): get() returns the value.
    std::printf("\n(1) std::async(launch::async, fn) -> future; get() returns the value.\n");
    std::future<int> f1 = std::async(std::launch::async, [] {
        return static_cast<int>(squarePlusOffset(7, 6));   // 7*7 + 6 == 55
    });
    std::printf("    before get(): f1.valid() = %s\n", f1.valid() ? "true" : "false");
    check("future from async is valid() before get()", f1.valid());
    int v1 = f1.get();                                    // blocks, then returns 55
    std::printf("    f1.get() = %d; after get(): f1.valid() = %s\n",
                v1, f1.valid() ? "true" : "false");
    check("async get() returns the computed value (7*7+6 == 55)", v1 == 55);
    check("after get(), valid() == false (the result was consumed)", !f1.valid());

    // (2) future<void>: the operation signals completion; get() just waits.
    std::printf("\n(2) future<void>: get() just waits (no value carried).\n");
    bool side = false;
    std::future<void> fv = std::async(std::launch::async, [&side] {
        side = true;                                      // happens-before main's get()
    });
    fv.get();                                             // blocks until the worker done
    std::printf("    after fv.get(): worker set side = %s\n", side ? "true" : "false");
    check("future<void>: get() synchronized the worker's write (side == true)", side);

    // (3) EXCEPTION PROPAGATION: if the async fn THROWS, get() RETHROWS it.
    std::printf("\n(3) EXCEPTION PROPAGATION: if the async fn THROWS, get() RETHROWS.\n");
    std::future<int> fe = std::async(std::launch::async, []() -> int {
        throw std::runtime_error("async boom");
    });
    bool rethrown = false;
    bool message_ok = false;
    try {
        (void)fe.get();                                   // rethrows the stored exception
    } catch (const std::runtime_error& e) {
        rethrown = true;
        message_ok = (std::strcmp(e.what(), "async boom") == 0);
        std::printf("    caught at get(): runtime_error(\"%s\")\n", e.what());
    }
    check("an exception thrown in the async fn is rethrown by get()", rethrown);
    check("the rethrown exception carries the original message (\"async boom\")", message_ok);
    check("after a get() that rethrew, valid() == false (still consumed)", !fe.valid());

    // (4) get()-twice is UB (DOCUMENTED, NOT executed in the verified path).
    std::printf("\n(4) get() TWICE is UB (documented; NOT run here).\n");
    std::printf("    After get(), valid() == false. A second get() is undefined behavior:\n");
    std::printf("    \"If valid() is false before the call to this function, the behavior\n");
    std::printf("     is undefined.\" (cppreference, std::future::get).\n");
    std::printf("    // WHAT NOT TO DO (compiled only with -DDEMO_UB):\n");
    std::printf("    //   auto f = std::async(std::launch::async, []{ return 7; });\n");
    std::printf("    //   (void)f.get();\n");
    std::printf("    //   (void)f.get();   // <-- UB: valid() == false\n");
    check("the get()-twice-is-UB trap is documented (not executed)", true);

#ifdef DEMO_UB
    // Would-be UB: a second get() on a consumed future. NEVER compiled by
    // just run/out/check/sanitize. The standard: "If valid() is false before the
    // call to this function, the behavior is undefined."
    auto fd = std::async(std::launch::async, [] { return 7; });
    (void)fd.get();
    (void)fd.get();                                       // <-- UB
#endif
}

// === Section B — std::promise<T> (writer) / std::future<T> (reader) across threads
//
// A promise is the WRITE side; its get_future() returns the paired future (the READ
// side). set_value(x) (or set_exception) fulfills it; the future.get() receives it,
// BLOCKING until the promise makes the shared state ready. The shared state IS the
// synchronization: set_value "synchronizes-with" the return from get()/wait().
void sectionB() {
    sectionBanner("B — std::promise (writer) / std::future (reader) across threads");

    std::printf("std::promise<T> is the WRITER; its get_future() returns the paired\n");
    std::printf("std::future<T> (the READER). set_value(x) / set_exception(e) fulfill it;\n");
    std::printf("future.get() receives it, BLOCKING until the shared state is ready.\n");
    std::printf("The shared state IS the sync: set_value synchronizes-with get().\n");

    // (1) The classic handoff: move the promise into a worker thread; the worker
    //     sets the value; main's get() blocks until ready and receives it.
    std::printf("\n(1) promise -> worker thread -> set_value -> main's get().\n");
    std::promise<long long> p1;
    std::future<long long> f1 = p1.get_future();
    std::thread worker([pr = std::move(p1)]() mutable {
        pr.set_value(squarePlusOffset(9, 10));            // 9*9 + 10 == 91
    });
    long long v1 = f1.get();                              // blocks until set_value -> ready
    worker.join();
    std::printf("    worker set 9*9+10; main got f1.get() = %lld\n", v1);
    check("promise->worker->set_value -> paired future.get() delivers 91 across threads",
          v1 == 91);
    check("after get(), the reader future is invalid (one-shot)", !f1.valid());

    // (2) EXCEPTION PROPAGATION via set_exception: the worker stores an exception
    //     pointer; get() rethrows it. This is the structured way to ferry a thrown
    //     value out of a worker thread.
    std::printf("\n(2) set_exception: the worker stores an exception; get() rethrows.\n");
    std::promise<int> p2;
    std::future<int> f2 = p2.get_future();
    std::thread worker2([pr = std::move(p2)]() mutable {
        try {
            throw std::runtime_error("promise boom");
        } catch (...) {
            pr.set_exception(std::current_exception());   // store the live exception
        }
    });
    bool rethrown = false;
    bool message_ok = false;
    try {
        (void)f2.get();                                   // rethrows the stored exception
    } catch (const std::runtime_error& e) {
        rethrown = true;
        message_ok = (std::strcmp(e.what(), "promise boom") == 0);
        std::printf("    caught at get(): runtime_error(\"%s\")\n", e.what());
    }
    worker2.join();
    check("promise::set_exception -> paired future.get() rethrows across threads",
          rethrown);
    check("the rethrown exception carries the original message (\"promise boom\")",
          message_ok);

    // (3) promise<void> as a stateless SIGNAL / barrier (one-shot event).
    std::printf("\n(3) promise<void> as a one-shot SIGNAL: set_value() with no value.\n");
    std::promise<void> barrier;
    std::future<void> bf = barrier.get_future();
    bool reached = false;
    std::thread worker3([pr = std::move(barrier), &reached]() mutable {
        reached = true;
        pr.set_value();                                   // make ready, no value carried
    });
    bf.get();                                             // blocks until set_value()
    worker3.join();
    std::printf("    main unblocked at bf.get(); worker reached = %s\n",
                reached ? "true" : "false");
    check("promise<void> set_value -> future.get() unblocks (one-shot signal)", reached);

    // (4) THE BROKEN-PROMISE trap (documented). A promise destroyed WITHOUT setting a
    //     value/exception ABANDONS its shared state: it stores a std::future_error
    //     with code std::future_errc::broken_promise, makes the state ready, and the
    //     paired future.get() then THROWS that future_error.
    std::printf("\n(4) THE BROKEN-PROMISE trap (documented; the safe path is shown).\n");
    std::printf("    A promise destroyed WITHOUT set_value/set_exception ABANDONS the\n");
    std::printf("    shared state: it stores std::future_error{broken_promise}, makes it\n");
    std::printf("    ready, and the paired future.get() THROWS. (Demonstrated safely below.)\n");
    bool broke = false;
    std::future<int> f3;
    {
        std::promise<int> p3;
        f3 = p3.get_future();
        // p3 is destroyed at this block's end with NO set_value/set_exception.
    }  // <-- p3 destroyed here -> ABANDONS the shared state: stores
       //     future_error{broken_promise} and MAKES IT READY. f3.get() now throws.
    try {
        (void)f3.get();
    } catch (const std::future_error& fe2) {
        broke = (fe2.code() == std::make_error_code(std::future_errc::broken_promise));
        std::printf("    caught future_error: %s\n", fe2.what());
    }
    check("a promise destroyed without set_value -> get() throws future_error{broken_promise}",
          broke);
}

// === Section C — the launch-policy footgun + get-twice UB + destructor-blocks =====
//
// THE expert payoff. Three traps:
//   (footgun) The DEFAULT policy (async|deferred) is implementation-defined which
//             runs; `deferred` is LAZY — it runs in the CALLING thread on the first
//             wait()/get(), so it is NOT concurrent at all.
//   (UB)      get() twice is UB (after the first, valid()==false).
//   (gotcha)  The destructor of a future OBTAINED FROM std::async BLOCKS until the
//             async op finishes (unless moved/bound to a ref); futures from other
//             sources NEVER block.
//
// The footgun is proven DETERMINISTICALLY here via thread::id == / != comparison
// (the RESULT: did it run in the calling thread?), never via timing or streamed ids.
void sectionC() {
    sectionBanner("C — launch-policy footgun + get-twice UB + destructor-blocks");

    const std::thread::id main_id = std::this_thread::get_id();
    std::printf("THE launch-policy FOOTGUN: the default policy (async|deferred) is\n");
    std::printf("implementation-defined which runs. launch::deferred is LAZY: it runs in\n");
    std::printf("the CALLING thread on the first wait()/get() — NOT concurrent. Proven\n");
    std::printf("below by thread::id == / != (the calling thread is main).\n");

    // (1) launch::async: DEFINITELY a new thread -> captured id != main id.
    std::printf("\n(1) launch::async: DEFINITELY a new thread.\n");
    std::thread::id id_async{};
    {
        std::future<int> f = std::async(std::launch::async, [&id_async] {
            id_async = std::this_thread::get_id();
            return 111;
        });
        int v = f.get();                                  // blocks; triggers nothing lazy
        check("launch::async get() returns the computed value (111)", v == 111);
    }
    std::printf("    worker thread id %s main's id (ran in a NEW thread)\n",
                (id_async != main_id) ? "!=" : "==");
    check("launch::async ran in a DIFFERENT thread (id != main)", id_async != main_id);

    // (2) launch::deferred: LAZY — runs in the CALLING thread on get()/wait().
    //     This is the footgun: a "future" that is actually synchronous.
    std::printf("\n(2) launch::deferred: LAZY — runs in the CALLING thread on get()/wait().\n");
    std::thread::id id_def{};
    {
        std::future<int> f = std::async(std::launch::deferred, [&id_def] {
            id_def = std::this_thread::get_id();
            return 222;
        });
        int v = f.get();                                  // THIS call runs the fn, in main
        check("launch::deferred get() returns the computed value (222)", v == 222);
    }
    std::printf("    deferred fn thread id %s main's id (ran in the CALLING thread)\n",
                (id_def == main_id) ? "==" : "!=");
    check("launch::deferred ran in the CALLING thread (id == main) — NOT concurrent",
          id_def == main_id);

    // (3) DEFAULT policy (async | deferred): implementation-defined which is chosen.
    //     We assert ONLY the value (deterministic); we do NOT assert the thread id
    //     (which policy ran is impl-defined). This is the footgun: you can't tell.
    std::printf("\n(3) DEFAULT policy (async|deferred): impl-defined which runs.\n");
    std::printf("    Assert ONLY the value here (the policy is not portable).\n");
    {
        std::future<int> f = std::async([] { return 333; });   // default policy
        int v = f.get();
        check("default policy get() returns the computed value (333)", v == 333);
    }

    // (4) THE DESTRUCTOR-BLOCKS GOTCHA (documented). A future OBTAINED FROM std::async
    //     that still holds its shared state at destruction BLOCKS until the op finishes.
    //     Futures from OTHER sources (promise/packaged_task) NEVER block. This makes
    //     `std::async(std::launch::async, f); std::async(std::launch::async, g);`
    //     effectively SEQUENTIAL (the first temporary's dtor waits for f before g
    //     starts). There is no safe way to *print* this without timing, so it is
    //     documented; the verified path always calls get() (which invalidates first).
    std::printf("\n(4) THE DESTRUCTOR-BLOCKS GOTCHA (documented; NOT timed here).\n");
    std::printf("    A future OBTAINED FROM std::async whose shared state is still held at\n");
    std::printf("    destruction BLOCKS until the op finishes. Futures from promise /\n");
    std::printf("    packaged_task NEVER block. So this is effectively sequential:\n");
    std::printf("    //   std::async(std::launch::async, []{ f(); });  // temp dtor WAITS\n");
    std::printf("    //   std::async(std::launch::async, []{ g(); });  // ...then g starts\n");
    std::printf("    Fix: hold the future (bind to a name), or std::launch::deferred, or\n");
    std::printf("    std::jthread / a real thread pool for fan-out.\n");
    check("the destructor-blocks gotcha is documented (not executed)", true);

    // (5) get()-twice UB recap (also gated in Section A; re-stated as the headline trap).
    std::printf("\n(5) get() TWICE is UB (recap; #ifdef DEMO_UB gate, never compiled).\n");
    check("get()-twice UB is documented (valid()==false before the 2nd call -> UB)", true);
}

// === Section D — std::packaged_task + std::shared_future + wait()/wait_for() ======
//
// packaged_task wraps a Callable so that INVOKING it fulfills the paired future —
// the bridge between "a function" and "a future". shared_future<T> is the multi-
// reader form: a regular future is ONE-SHOT (get() invalidates it), but a
// shared_future can be get() by MANY readers. wait() blocks without consuming.
void sectionD() {
    sectionBanner("D — std::packaged_task + std::shared_future + wait()/wait_for()");

    std::printf("std::packaged_task wraps a Callable; invoking it (operator()) fulfills\n");
    std::printf("the paired future. std::shared_future<T> is the MULTI-READER future.\n");
    std::printf("wait() blocks WITHOUT consuming (valid() stays true; get() consumes).\n");

    // (1) packaged_task invoked directly: call task(args...) -> future.get() gets result.
    std::printf("\n(1) packaged_task invoked directly.\n");
    std::packaged_task<int(int, int)> task(
        [](int a, int b) { return static_cast<int>(squarePlusOffset(a, b)); });
    std::future<int> tf = task.get_future();
    task(6, 7);                                           // 6*6 + 7 == 43; fulfills tf
    int tv = tf.get();
    std::printf("    task(6,7) fulfilled the future; get() = %d\n", tv);
    check("packaged_task: invoking it fulfills the paired future (6*6+7 == 43)", tv == 43);

    // (2) packaged_task MOVED into a std::thread (the common pattern): run the task on
    //     a worker thread; get() in main retrieves the result across the thread.
    std::printf("\n(2) packaged_task MOVED into a std::thread (common pattern).\n");
    std::packaged_task<long long(int)> task2(
        [](int n) { return squarePlusOffset(n, n); });     // n*n + n
    std::future<long long> tf2 = task2.get_future();
    std::thread tt(std::move(task2), 8);                   // 8*8 + 8 == 72
    tt.join();
    long long tv2 = tf2.get();
    std::printf("    task2(8) ran on a worker; get() = %lld\n", tv2);
    check("packaged_task moved into a thread: get() delivers 8*8+8 == 72 across threads",
          tv2 == 72);

    // (3) shared_future: the MULTI-READER future. future::share() yields a shared_future
    //     that MANY readers can get() (a regular future is one-shot). Each get() returns
    //     the SAME stored value.
    std::printf("\n(3) shared_future: future::share() -> MANY readers can get().\n");
    std::future<int> of = std::async(std::launch::async, [] { return 42; });
    std::shared_future<int> sf = of.share();
    check("after share(), the original future is invalid (state moved to shared_future)",
          !of.valid());
    const int r1 = sf.get();                              // OK
    const int r2 = sf.get();                              // OK again — multi-reader!
    const int r3 = sf.get();                              // OK a third time
    std::printf("    sf.get() x3 = %d, %d, %d (all the same value)\n", r1, r2, r3);
    check("shared_future allows MULTIPLE get() (a regular future does not)",
          r1 == 42 && r2 == 42 && r3 == 42);
    check("shared_future is still valid() after several gets", sf.valid());

    // (4) wait() / wait_for() / wait_until(): check or wait WITHOUT consuming.
    //     wait() blocks until ready and does NOT consume (valid() stays true; get()
    //     still works after). wait_for()/wait_until() return a std::future_status
    //     (deferred / timeout / ready) — we do NOT assert the status here (it depends
    //     on scheduling), only that wait() leaves the future gettable.
    std::printf("\n(4) wait() blocks WITHOUT consuming; wait_for() returns a status.\n");
    std::future<int> wf = std::async(std::launch::async, [] { return 5; });
    wf.wait();                                            // blocks until ready; no consume
    check("after wait(), valid() is STILL true (wait does not consume)", wf.valid());
    int wv = wf.get();
    std::printf("    wf.wait() then wf.get() = %d\n", wv);
    check("wait() then get() returns the computed value (5)", wv == 5);
}

// === Section E — COLLECT + SORT + JOIN: deterministic parallel fan-out ============
//
// Launch N async tasks (launch::async); each returns a deterministic value. The
// COMPUTED VALUEs are deterministic; the COMPLETION ORDER is not. We get() each
// (get() blocks, in arrival-independent index order), pair {input, result}, SORT,
// and print from main. The sorted RESULT set is byte-identical across runs.
void sectionE() {
    sectionBanner("E — COLLECT + SORT + JOIN: deterministic parallel fan-out");

    constexpr int N = 6;
    std::printf("Launch %d tasks with std::async(launch::async); each computes n*n+n.\n", N);
    std::printf("COMPLETION ORDER is nondeterministic; the RESULT SET is not. We get()\n");
    std::printf("each future, pair {n, n*n+n}, SORT, and print -> byte-identical output.\n");

    // Launch all first (so they run concurrently); hold the futures in a vector.
    // NB: a future from async BLOCKS in its destructor if its shared state is still
    // held — but we get() EVERY one below, which invalidates them first (no blocking).
    std::vector<std::future<long long>> futures;
    futures.reserve(static_cast<std::size_t>(N));
    for (int i = 1; i <= N; ++i) {
        futures.push_back(std::async(std::launch::async, [i] {
            return squarePlusOffset(i, i);                // i*i + i
        }));
    }

    // get() each (blocks in index order, independent of completion order), pair+collect.
    std::vector<std::pair<int, long long>> collected;
    collected.reserve(static_cast<std::size_t>(N));
    for (int i = 0; i < N; ++i) {
        collected.emplace_back(i + 1, futures[static_cast<std::size_t>(i)].get());
    }
    std::sort(collected.begin(), collected.end());        // kill any arrival-order noise

    std::printf("\n    sorted results (n, n*n+n):\n");
    for (const auto& [n, r] : collected) {
        std::printf("      n=%d  ->  %lld\n", n, r);
    }
    check("collected exactly N results after all get()s",
          static_cast<int>(collected.size()) == N);

    // Assert the deterministic RESULT SET (the {n, n*n+n} values), never the order.
    bool set_ok = true;
    for (int i = 0; i < N; ++i) {
        const auto& entry = collected[static_cast<std::size_t>(i)];
        int expected_n = i + 1;
        long long expected_r = static_cast<long long>(expected_n) * expected_n + expected_n;
        if (entry.first != expected_n || entry.second != expected_r) {
            set_ok = false;
            break;
        }
    }
    check("the sorted set is the deterministic {n, n*n+n} for n=1..6 (NOT arrival order)",
          set_ok);

    // Spot-check two specific pinned values (2->6, 6->42) as the worked example.
    check("pinned value: n=2 -> 2*2+2 == 6",
          collected[1].first == 2 && collected[1].second == 6);
    check("pinned value: n=6 -> 6*6+6 == 42",
          collected[5].first == 6 && collected[5].second == 42);
}

}  // namespace

int main() {
    std::printf("futures_promises.cpp — Phase 4 bundle (Concurrency & the Memory Model).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free AND race-free (just sanitize clean;\n");
    std::printf("the shared state IS the sync — no raw shared memory is touched).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
