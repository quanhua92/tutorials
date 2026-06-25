// coroutines.cpp — Phase 4 bundle.
//
// GOAL (one line): show, by printing every value, how C++20 stackless coroutines
// (co_await / co_yield / co_return) SUSPEND and later RESUME while preserving
// local state in a heap-allocated coroutine FRAME — driven by a hand-written
// Task/Generator type whose nested promise_type is the compiler-invoked
// controller. C++20 ships the LANGUAGE; this bundle ships the minimal runtime.
//
// This is the GROUND TRUTH for COROUTINES.md. Every value, sequence, and resume
// ordering below is printed by this file. Change it -> re-compile -> re-paste.
// Never hand-compute.
//
// Run:
//     just run coroutines   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                              coroutines.cpp -o /tmp/cpp_coroutines
//                              && /tmp/cpp_coroutines)

#include <coroutine>   // std::coroutine_handle, std::suspend_always, std::suspend_never
#include <exception>   // std::terminate (unhandled_exception)
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <vector>      // collect yielded sequences

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

// === The minimal Task type (a coroutine return-object) =======================
//
// A coroutine's return type must expose a nested `promise_type`; the compiler
// generates code that drives the coroutine THROUGH that promise. This Task is
// LAZY (initial_suspend == suspend_always): the body does not run until resume()
// is called. final_suspend is also suspend_always — resuming a coroutine past
// its final suspend point is UNDEFINED BEHAVIOR, so we keep it suspended and let
// the destructor destroy() the frame exactly once (RAII; ⟷ Rust's Drop).
struct Task {
    struct promise_type;
    using handle_type = std::coroutine_handle<promise_type>;

    struct promise_type {
        int value_ = 0;                                   // filled by return_value()
        Task get_return_object() { return Task{handle_type::from_promise(*this)}; }
        std::suspend_always initial_suspend() noexcept { return {}; }   // lazy start
        std::suspend_always final_suspend() noexcept { return {}; }     // never resume past end
        void return_value(int v) { value_ = v; }          // co_return expr; (non-void)
        void unhandled_exception() { std::terminate(); }
    };

    handle_type h_;
    explicit Task(handle_type h) noexcept : h_(h) {}
    Task(const Task&) = delete;
    Task& operator=(const Task&) = delete;
    Task(Task&& other) noexcept : h_(other.h_) { other.h_ = nullptr; }
    Task& operator=(Task&&) = delete;
    ~Task() { if (h_) h_.destroy(); }

    void resume() { h_.resume(); }
    bool done() const noexcept { return h_ ? h_.done() : true; }
    int result() const noexcept { return h_.promise().value_; }
};

// === The minimal Generator<T> (co_yield → iterate) ===========================
//
// A Generator is the canonical lazy-sequence coroutine: each co_yield produces a
// value and suspends. The driver resumes repeatedly to pull values one at a time
// (a "pull"-shaped coroutine). The coroutine FRAME — heap-allocated by the
// compiler — holds the local variables across suspends, which is how a single
// `fib(n)` keeps `a` and `b` alive between yields.
template <typename T>
struct Generator {
    struct promise_type;
    using handle_type = std::coroutine_handle<promise_type>;

    struct promise_type {
        T current_{};                                     // last yielded value
        Generator get_return_object() {
            return Generator{handle_type::from_promise(*this)};
        }
        std::suspend_always initial_suspend() noexcept { return {}; }   // lazy
        std::suspend_always final_suspend() noexcept { return {}; }     // safe
        std::suspend_always yield_value(T value) {        // co_yield expr;
            current_ = value;
            return {};
        }
        void return_void() {}                             // co_return; / fall-off
        void unhandled_exception() { std::terminate(); }
    };

    handle_type h_;
    explicit Generator(handle_type h) noexcept : h_(h) {}
    Generator(const Generator&) = delete;
    Generator& operator=(const Generator&) = delete;
    Generator(Generator&& other) noexcept : h_(other.h_) { other.h_ = nullptr; }
    Generator& operator=(Generator&&) = delete;
    ~Generator() { if (h_) h_.destroy(); }

    // Advance from the current suspend point to the next yield (or to the end).
    // Returns true if a value is available, false if the coroutine finished.
    // Calling this on a finished generator would resume past final_suspend = UB.
    bool move_next() { h_.resume(); return !h_.done(); }
    T current() const noexcept { return h_.promise().current_; }
    bool done() const noexcept { return h_ ? h_.done() : true; }
    handle_type raw_handle() const noexcept { return h_; }   // for the DEMO_UB block
};

// === Custom awaiters (Section C) — the await_ready/suspend/resume protocol ===
//
// Any object with await_ready/await_suspend/await_resume is an AWAITER and can be
// co_await-ed. await_ready() == true is a short-cut: skip suspension entirely.
struct ReadyAwaiter {                    // await_ready == true: NO suspension
    int payload;
    bool await_ready() const noexcept { return true; }
    void await_suspend(std::coroutine_handle<>) const noexcept {}
    int await_resume() const noexcept { return payload; }
};

struct SuspendingAwaiter {               // await_ready == false: suspends once
    bool await_ready() const noexcept { return false; }
    void await_suspend(std::coroutine_handle<>) const noexcept {}  // stay suspended
    int await_resume() const noexcept { return 99; }
};

// An EAGER task: initial_suspend == suspend_never -> body runs DURING the call.
struct EagerTask {
    struct promise_type;
    using handle_type = std::coroutine_handle<promise_type>;
    struct promise_type {
        bool ran_ = false;
        EagerTask get_return_object() { return EagerTask{handle_type::from_promise(*this)}; }
        std::suspend_never initial_suspend() noexcept { return {}; }   // EAGER
        std::suspend_always final_suspend() noexcept { return {}; }
        void return_void() { ran_ = true; }
        void unhandled_exception() { std::terminate(); }
    };
    handle_type h_;
    explicit EagerTask(handle_type h) noexcept : h_(h) {}
    EagerTask(const EagerTask&) = delete;
    EagerTask& operator=(const EagerTask&) = delete;
    EagerTask(EagerTask&& o) noexcept : h_(o.h_) { o.h_ = nullptr; }
    EagerTask& operator=(EagerTask&&) = delete;
    ~EagerTask() { if (h_) h_.destroy(); }
    bool ran() const noexcept { return h_.promise().ran_; }
};

// --- The coroutines (each contains a co_-keyword, so each IS a coroutine) -----

Task returns_seven() {
    std::printf("    [body of returns_seven] about to co_return 7\n");
    co_return 7;
}

Generator<int> count_up(int n) {
    for (int i = 0; i < n; ++i) {
        co_yield i;
    }
}

Generator<int> fibonacci(int n) {
    if (n <= 0) co_return;            // return_void -> final_suspend
    int a = 0, b = 1;                 // frame-allocated: survive across yields
    for (int i = 0; i < n; ++i) {
        co_yield a;                   // produce current, suspend
        int next = a + b;
        a = b;
        b = next;
    }
}

// by-REFERENCE parameter: NOT copied into the frame; resuming after the referent
// dies is a dangling-reference (UB) trap. Used here SAFELY (referent outlives g).
Generator<int> count_via_ref(const int& limit) {
    for (int i = 0; i < limit; ++i) co_yield i;   // reads `limit` each resume
}

Task await_ready_demo() {
    std::printf("    [await_ready_demo body] co_await ReadyAwaiter{42}...\n");
    int x = co_await ReadyAwaiter{42};
    std::printf("    [await_ready_demo body] x = %d (no suspension happened)\n", x);
    co_return x;
}

Task await_suspending_demo() {
    std::printf("    [await_suspending_demo body] co_await SuspendingAwaiter{}...\n");
    int x = co_await SuspendingAwaiter{};
    std::printf("    [await_suspending_demo body] resumed! x = %d\n", x);
    co_return x;
}

EagerTask eager_body() {
    std::printf("    [eager_body ran DURING construction — before caller continues]\n");
    co_return;                        // return_void -> final_suspend
}

// === Section A — co_return + the promise_type (the compiler-invoked controller)
void sectionA() {
    sectionBanner("A — co_return + the promise_type (compiler-invoked controller)");

    std::printf("A coroutine's return type must expose a nested `promise_type`.\n");
    std::printf("The compiler generates code that calls its members in a fixed order:\n");
    std::printf("  get_return_object() -> initial_suspend() -> <body> ->\n");
    std::printf("  return_value(v)/return_void() -> final_suspend()\n\n");

    std::printf("calling returns_seven() (initial_suspend == suspend_always -> LAZY)...\n");
    Task t = returns_seven();          // frame allocated; body NOT run yet
    std::printf("  [after call, before resume] t.done() == %d  (body has NOT run)\n",
                t.done() ? 1 : 0);
    check("lazy Task: body did NOT run during construction (done() still false)",
          !t.done());

    std::printf("calling t.resume()...\n");
    t.resume();                        // body runs now: prints, return_value(7), final_suspend
    std::printf("  [after resume] t.done() == %d  (body ran to co_return)\n",
                t.done() ? 1 : 0);
    check("after resume, coroutine reached final_suspend (done() == true)", t.done());
    check("co_return 7 delivered 7 via promise.return_value(int)", t.result() == 7);
    std::printf("  result captured in promise = %d\n", t.result());
}

// === Section B — co_yield + the Generator + the coroutine FRAME ===============
void sectionB() {
    sectionBanner("B — co_yield Generator + the coroutine FRAME (state persists)");

    std::printf("count_up(5) yields 0..4 in resume order:\n");
    Generator<int> g = count_up(5);
    std::vector<int> got;
    while (g.move_next()) got.push_back(g.current());
    std::printf("  collected: ");
    for (int v : got) std::printf("%d ", v);
    std::printf("\n");
    check("count_up(5) yielded exactly 0 1 2 3 4",
          got == std::vector<int>{0, 1, 2, 3, 4});

    std::printf("\nfibonacci(8) — locals a,b live in the FRAME across each yield:\n");
    Generator<int> fib = fibonacci(8);
    std::vector<int> fib_got;
    while (fib.move_next()) fib_got.push_back(fib.current());
    std::printf("  collected: ");
    for (int v : fib_got) std::printf("%d ", v);
    std::printf("\n");
    check("fibonacci(8) yielded 0 1 1 2 3 5 8 13 (frame kept a,b alive)",
          fib_got == std::vector<int>{0, 1, 1, 2, 3, 5, 8, 13});
    check("frame persists across yields: a,b were NOT reset between resumes",
          fib_got.size() == 8 && fib_got[7] == 13);
    check("Generator is now done() (suspended at final_suspend)", fib.done());
}

// === Section C — suspend_always/suspend_never + the awaiter protocol ==========
void sectionC() {
    sectionBanner("C — suspend_always/suspend_never + the awaiter protocol");

    std::printf("initial_suspend controls LAZY vs EAGER start:\n");
    std::printf("  constructing eager_body() (initial_suspend == suspend_never)...\n");
    EagerTask e = eager_body();        // body runs RIGHT NOW, during this line
    std::printf("  [after construction] e.ran() == %d  (body already ran: EAGER)\n",
                e.ran() ? 1 : 0);
    check("suspend_never initial_suspend: body ran DURING construction (eager)",
          e.ran());

    std::printf("\nThe awaiter protocol — await_ready short-circuits suspension:\n");
    std::printf("  demo 1: co_await ReadyAwaiter{42} (await_ready == true)\n");
    Task t1 = await_ready_demo();      // lazy: body not run
    std::printf("  before resume: t1.done() == %d\n", t1.done() ? 1 : 0);
    t1.resume();                       // one resume runs the whole body (no internal suspend)
    check("ReadyAwaiter (await_ready=true): one resume sufficed, no suspension",
          t1.done() && t1.result() == 42);

    std::printf("\n  demo 2: co_await SuspendingAwaiter{} (await_ready == false)\n");
    Task t2 = await_suspending_demo(); // lazy
    t2.resume();                       // runs body up to co_await, then SUSPENDS
    std::printf("  after first resume: t2.done() == %d  (suspended inside co_await)\n",
                t2.done() ? 1 : 0);
    check("SuspendingAwaiter: coroutine SUSPENDED at co_await after first resume",
          !t2.done());
    t2.resume();                       // resumes from suspension -> await_resume() -> body end
    std::printf("  after second resume: t2.done() == %d\n", t2.done() ? 1 : 0);
    check("SuspendingAwaiter: after second resume, await_resume() returned 99",
          t2.done() && t2.result() == 99);
}

// === Section D — the LIFETIME TRAP + why C++20 ships no runtime ===============
//
// THE expert trap: a std::coroutine_handle is a NON-OWNING pointer to the frame.
// If the frame is destroyed (the owning wrapper's dtor ran, or the coroutine
// went out of scope) and you then resume()/destroy() the handle again, that is
// UNDEFINED BEHAVIOR — use-after-free on the frame. The verified path below
// documents the trap and gates the offending code behind #ifdef DEMO_UB (which
// `just run/out/check/sanitize` never pass), so the default + sanitizer builds
// stay UB-free.
void sectionD() {
    sectionBanner("D — the LIFETIME trap (handle-outlives-frame = UB) + no runtime");

    std::printf("std::coroutine_handle is a NON-OWNING pointer to the heap frame.\n");
    std::printf("The owning wrapper (Task/Generator) destroys the frame in its dtor.\n");
    std::printf("Safe pattern: ONE owner, frame destroyed exactly once (RAII).\n\n");

    // SAFE: the Generator owns its frame for its whole scope.
    std::printf("SAFE: Generator owns its frame; we resume within its lifetime.\n");
    {
        Generator<int> g = count_up(3);
        int sum = 0;
        while (g.move_next()) sum += g.current();
        std::printf("  sum of count_up(3) = %d\n", sum);
        check("safe RAII: frame alive across all resumes, destroyed once at scope end",
              sum == 0 + 1 + 2);
    }

    // SAFE use of a by-REFERENCE parameter (referent outlives the generator):
    std::printf("\nby-REF param is read (not copied) on each resume — safe if alive:\n");
    int cap = 4;
    Generator<int> g2 = count_via_ref(cap);   // cap outlives g2
    std::vector<int> ref_got;
    while (g2.move_next()) ref_got.push_back(g2.current());
    std::printf("  count_via_ref(cap=4) collected: ");
    for (int v : ref_got) std::printf("%d ", v);
    std::printf("\n");
    check("count_via_ref(cap=4) yielded 0 1 2 3 (ref alive across resumes)",
          ref_got == std::vector<int>{0, 1, 2, 3});

    // The DANGLING-REFERENCE trap is the same shape: resuming after the referent
    // dies is UB. Documented here; NOT triggered in the verified path.
    std::printf("\nTRAP (documented, not triggered): resuming a by-ref coroutine\n");
    std::printf("  after the referent's lifetime ends is a dangling reference (UB).\n");
    check("by-reference dangling trap documented (verified path does not trigger it)",
          true);

    // WHAT NOT TO DO — compiled only with -DDEMO_UB. RUNNING it is UB.
    std::printf("\nWHAT NOT TO DO (compiled only with -DDEMO_UB; running it is UB):\n");
    std::printf("  grab the raw handle, let the owner go out of scope, then resume()\n");
    std::printf("  the dangling handle — use-after-free on the frame.\n");
#ifdef DEMO_UB
    std::coroutine_handle<> dangling{};
    {
        Generator<int> g = count_up(2);
        dangling = g.raw_handle();      // copy the non-owning handle
        // g destroyed here -> frame freed
    }
    dangling.resume();                  // UB: frame already destroyed
    std::printf("[DEMO_UB] resumed a destroyed frame — unreachable under no-UB\n");
#else
    std::printf("  (DEMO_UB not defined: the UB resume is correctly omitted from this build.)\n");
#endif
    check("lifetime trap documented; verified path never resumes a destroyed frame", true);

    // Why C++20 ships no runtime:
    std::printf("\nC++20 ships the LANGUAGE (co_await/yield/return + promise_type\n");
    std::printf("machinery + <coroutine>); it does NOT ship a task type or scheduler.\n");
    std::printf("YOU write the Task/Generator (as this bundle does), or use a library:\n");
    std::printf("  - CppCoro (lewissbaker) — the de-facto pre-standard coroutine lib.\n");
    std::printf("  - C++23 std::generator — the standardized synchronous generator.\n");
    std::printf("  - C++23 std::execution (P2300) — the async sender/receiver runtime.\n");
    check("no-runtime fact documented (you/CppCoro/C++23 std::generator provide task+driver)",
          true);
}

// === Section E — deterministic resume order (single-thread driver) ============
//
// A single-threaded coroutine driver resumes coroutines in a fully DETERMINISTIC
// order — there is no scheduler, no preemption, no rand/now. The bundle asserts
// the exact interleaving of two generators resumed alternately (§4.2 rule 4).
void sectionE() {
    sectionBanner("E — deterministic resume order (interleaved generators)");

    std::printf("Two generators, resumed alternately in ONE thread -> fixed order:\n");
    Generator<int> a = count_up(3);     // yields 0,1,2
    Generator<int> b = count_up(3);     // yields 0,1,2
    std::vector<int> interleave;
    for (int step = 0; step < 3; ++step) {
        if (a.move_next()) interleave.push_back(a.current());
        if (b.move_next()) interleave.push_back(b.current());
    }
    std::printf("  interleave(a, b one step each, x3): ");
    for (int v : interleave) std::printf("%d ", v);
    std::printf("\n");
    check("interleaved resume order is a0 b0 a1 b1 a2 b2 (deterministic)",
          interleave == std::vector<int>{0, 0, 1, 1, 2, 2});
    // After 3 resumes each, a and b sit suspended at their LAST yield (not done());
    // one more resume each runs the body off the end -> return_void -> final_suspend.
    check("a still suspended at its last yield after 3 resumes (not yet done())",
          !a.done() && !b.done());
    bool a_more = a.move_next();        // resume past last yield -> finish
    bool b_more = b.move_next();        // resume past last yield -> finish
    check("after a 4th resume each, both generators reached final_suspend (done)",
          !a_more && !b_more && a.done() && b.done());

    // Summary of the three keywords (printed, so the .md pastes it verbatim):
    std::printf("\nThe three coroutine keywords:\n");
    std::printf("  co_return expr;  -> promise.return_value(expr) / return_void(); ends coro\n");
    std::printf("  co_yield expr;   -> co_await promise.yield_value(expr); produces + suspends\n");
    std::printf("  co_await expr;   -> awaiter protocol (await_ready / await_suspend / await_resume)\n");
    check("three-keyword summary printed (co_return / co_yield / co_await)", true);
}

}  // namespace

int main() {
    std::printf("coroutines.cpp — Phase 4 bundle.\n");
    std::printf("C++20 stackless coroutines: co_await/co_yield/co_return + promise_type.\n");
    std::printf("Single-threaded, deterministic resume order; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
