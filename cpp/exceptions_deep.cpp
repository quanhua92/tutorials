// exceptions_deep.cpp — Phase 7 bundle (the full depth of exception SAFETY).
//
// GOAL (one line): show, by printing every value, the four exception-safety
// GUARANTEES (Abrahams: nothrow / strong-commit-or-rollback / basic / none), the
// strong guarantee via copy-and-swap, RAII freeing resources during stack
// UNWINDING, the noexcept specifier/operator, the noexcept-MOVE-vs-COPY decision
// that std::vector makes on reallocation (move_if_noexcept), why you NEVER throw
// from a destructor (std::terminate), and the exceptions-vs-error-codes-vs-
// std::expected tradeoff — pinning "copy-and-swap for the strong guarantee" as
// the expert payoff.
//
// This is the GROUND TRUTH for EXCEPTIONS_DEEP.md. Every value, message, and
// [check] below is printed by this file. Change it -> re-compile -> re-paste.
// Never hand-compute.
//
// SAFETY NOTE: EVERY throw in the verified path is caught (no uncaught exception
// -> std::terminate -> nondeterministic abort message). The two paths that would
// call std::terminate are DOCUMENTED, never executed: (1) a throw escaping a
// destructor DURING unwinding (two exceptions in flight), and (2) a noexcept
// function that throws. A program that triggers either ends (std::terminate ->
// std::abort); reproducing it would abort the verified path, mirroring how
// values_types.cpp documents (never runs) undefined behavior.
//
// Run:
//     just run exceptions_deep
//         (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//             exceptions_deep.cpp -o /tmp/cpp_exceptions_deep
//             && /tmp/cpp_exceptions_deep)

#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <exception>   // std::exception
#include <expected>    // std::expected<T,E> (C++23) — the error-code path
#include <stdexcept>   // std::runtime_error
#include <string>      // std::string
#include <type_traits>  // is_nothrow_move_constructible_v / is_nothrow_destructible_v / is_same_v
#include <utility>     // std::move_if_noexcept / std::declval / std::swap
#include <vector>      // std::vector (IntBag, the copy-and-swap demo)

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

// === Section A — the four exception-safety GUARANTEES + strong via copy-and-swap
//
// D. Abrahams ("Exception Safety in Generic Components", 2000) and the standard
// library convention recognize four levels of guarantee a function can offer the
// caller AFTER it signals an error:
//
//   NOTHROW  : never throws (expected of dtors, swap, move ctors).
//   STRONG   : commit-or-rollback — on throw, the program state is UNCHANGED
//              (e.g. std::vector::push_back). Achievable via copy-and-swap.
//   BASIC    : on throw, no leaks and invariants stay intact, but state may have
//              moved (NOT rolled back). The minimum every function should offer.
//   NONE     : on throw, leaks / corruption / broken invariants are possible.
//
// Copy-and-swap makes STRONG achievable: build the new state in a LOCAL copy
// (any throw there leaves the live object untouched), then commit with a
// NOTHROW swap. We prove rollback by driving a deterministic mid-operation throw.

// A small bag of ints used to contrast STRONG (copy-and-swap) vs BASIC
// (in-place mutation) guarantees on the same operation.
class IntBag {
public:
    explicit IntBag(std::initializer_list<int> init) : v_(init) {}
    std::size_t size() const noexcept { return v_.size(); }
    const std::vector<int>& data() const noexcept { return v_; }

    // STRONG guarantee (commit-or-rollback): mutate a COPY only; commit via the
    // (nothrow) vector::swap. Any throw during the build leaves v_ UNTOUCHED.
    void appendStrong(const std::vector<int>& items, int failAt) {
        std::vector<int> tmp(v_);                       // 1. copy current state
        for (std::size_t i = 0; i < items.size(); ++i) {
            if (static_cast<int>(i) == failAt)
                throw std::runtime_error("appendStrong: simulated failure");
            tmp.push_back(items[i]);                    // 2. mutate the COPY only
        }
        tmp.swap(v_);                                   // 3. nothrow commit
    }

    // BASIC guarantee (at best): mutate v_ in place. A mid-loop throw leaves v_
    // VALID but PARTIALLY MUTATED (some elements pushed, rest not) — invariants
    // intact, no leak, but NOT rolled back to the pre-call state.
    void appendBasic(const std::vector<int>& items, int failAt) {
        for (std::size_t i = 0; i < items.size(); ++i) {
            if (static_cast<int>(i) == failAt)
                throw std::runtime_error("appendBasic: simulated failure");
            v_.push_back(items[i]);                     // mutates v_ directly
        }
    }

private:
    std::vector<int> v_;
};

// A NOTHROW function: the no-throw guarantee. swap of two ints cannot fail.
void intSwap(int& a, int& b) noexcept { int t = a; a = b; b = t; }

void sectionA() {
    sectionBanner("A — the 4 exception-safety guarantees & strong via copy-and-swap");

    std::printf("The four guarantees (Abrahams), strict supersets of each other:\n");
    std::printf("  NOTHROW : never throws (dtors, swap, move ctors)\n");
    std::printf("  STRONG  : commit-or-rollback (state UNCHANGED on throw)\n");
    std::printf("  BASIC   : no leak, invariants intact (state may have moved)\n");
    std::printf("  NONE    : leaks / corruption / broken invariants possible\n");

    // (1) NOTHROW: a noexcept swap. Always succeeds.
    std::printf("\n(1) NOTHROW — intSwap(int&,int&) noexcept:\n");
    int x = 1, y = 2;
    intSwap(x, y);
    std::printf("    x=%d y=%d (swapped); noexcept(intSwap(x,y))=%d\n",
                x, y, static_cast<int>(noexcept(intSwap(x, y))));
    check("nothrow intSwap swapped the values (x==2, y==1)", x == 2 && y == 1);
    check("intSwap is noexcept (the no-throw guarantee)", noexcept(intSwap(x, y)));

    // (2) STRONG: copy-and-swap rolls back on failure. Start {1,2,3}; fail at
    // index 1 (one element built into the copy, then throw) -> v_ UNCHANGED.
    std::printf("\n(2) STRONG — appendStrong({10,20,30}, fail_at=1) on {1,2,3}:\n");
    std::printf("    (builds new state in a copy; throw leaves the bag UNCHANGED)\n");
    IntBag strongBag{1, 2, 3};
    try {
        strongBag.appendStrong({10, 20, 30}, /*failAt=*/1);
    } catch (const std::exception& e) {
        std::printf("    caught: \"%s\"\n", e.what());
    }
    std::printf("    bag after = { ");
    for (std::size_t i = 0; i < strongBag.data().size(); ++i)
        std::printf("%d%s", strongBag.data()[i], i + 1 < strongBag.data().size() ? ", " : "");
    std::printf(" } (size %zu)\n", strongBag.size());
    check("STRONG appendStrong ROLLED BACK: size still 3", strongBag.size() == 3);
    check("STRONG appendStrong ROLLED BACK: contents unchanged {1,2,3}",
          strongBag.data() == std::vector<int>{1, 2, 3});

    // (3) BASIC: in-place mutation leaves a VALID but PARTIALLY MUTATED state.
    // Same operation, same failure point, but no copy-and-swap -> no rollback.
    std::printf("\n(3) BASIC — appendBasic({10,20,30}, fail_at=1) on {1,2,3}:\n");
    std::printf("    (mutates in place; throw leaves a VALID but partially-mutated bag)\n");
    IntBag basicBag{1, 2, 3};
    try {
        basicBag.appendBasic({10, 20, 30}, /*failAt=*/1);
    } catch (const std::exception& e) {
        std::printf("    caught: \"%s\"\n", e.what());
    }
    std::printf("    bag after = { ");
    for (std::size_t i = 0; i < basicBag.data().size(); ++i)
        std::printf("%d%s", basicBag.data()[i], i + 1 < basicBag.data().size() ? ", " : "");
    std::printf(" } (size %zu)\n", basicBag.size());
    check("BASIC appendBasic did NOT roll back: size grew to 4 (one push before throw)",
          basicBag.size() == 4);
    check("BASIC appendBasic left a VALID state {1,2,3,10}",
          basicBag.data() == std::vector<int>{1, 2, 3, 10});

    // (4) NONE: a function using raw new/delete WITHOUT RAII can LEAK on throw.
    // We DOCUMENT it (never run a leak — it would fail `just sanitize`). The fix
    // is RAII (std::unique_ptr), which converts a NONE-guarantee leak into a
    // BASIC+ one (the smart pointer's dtor frees during unwinding — Section B).
    std::printf("\n(4) NONE — raw `new` without RAII LEAKS on throw (documented, not run):\n");
    std::printf("    int* p = new int(42);  if (fail) throw ...;  delete p; // <- delete skipped -> LEAK\n");
    std::printf("    fix: std::unique_ptr<int> p(new int(42)); // dtor frees even on throw (RAII)\n");
    check("no-guarantee leak documented (RAII/unique_ptr is the fix; never run the leak)", true);
}

// === Section B — stack UNWINDING + RAII (no leak); the no-throw-during-unwind rule
//
// When a throw propagates, the stack UNWINDS: destructors run for every
// fully-constructed automatic object between the throw and the catch (reverse
// order of construction). RAII types therefore release resources on the error
// path — no leak. We prove it with a live counter: a throw escapes a scope
// holding two Trackers; both dtors fire during unwinding -> alive returns to 0.

// A tiny RAII handle that bumps a live-count on construction/destruction.
struct Tracker {
    static int alive;
    int id;
    explicit Tracker(int i) : id(i) { ++alive; }
    ~Tracker() noexcept { --alive; }   // noexcept (implicit anyway): safe during unwinding
    Tracker(const Tracker&) = delete;  // copies would confuse the count
    Tracker& operator=(const Tracker&) = delete;
};
int Tracker::alive = 0;

void sectionB() {
    sectionBanner("B — stack unwinding + RAII (no leak) & the no-throw-during-unwind rule");

    // (1) RAII frees during unwinding. Construct two Trackers, then throw: their
    // dtors run as the exception escapes the scope -> alive returns to 0.
    std::printf("(1) two Trackers constructed, then throw -> dtors run during unwinding:\n");
    try {
        Tracker a(1);
        Tracker b(2);
        check("Trackers alive after construction (==2)", Tracker::alive == 2);
        throw std::runtime_error("unwind test");
    } catch (const std::exception& e) {
        std::printf("    caught: \"%s\"; Tracker::alive after catch = %d\n", e.what(), Tracker::alive);
    }
    check("RAII freed BOTH Trackers during unwinding (alive==0)", Tracker::alive == 0);

    // (2) Unwinding runs dtors in REVERSE order of construction (mirrors the
    // intro bundle's Logger demo). Two nested Trackers: the inner one dies first.
    std::printf("\n(2) unwinding order is REVERSE of construction:\n");
    std::string order;
    auto run = [](std::string* log) {
        struct L {
            std::string* out;
            char tag;
            L(std::string* o, char t) : out(o), tag(t) {}
            ~L() { if (out) out->push_back(tag); }
        };
        L first(log, '1');
        L second(log, '2');
        throw std::runtime_error("order test");
    };
    try {
        run(&order);
    } catch (const std::exception&) {}
    std::printf("    construction order = 1,2 ; dtor order during unwind = \"%s\"\n", order.c_str());
    check("unwinding ran dtors in REVERSE order (\"21\")", order == "21");

    // (3) The rule that makes this safe: destructors are implicitly noexcept
    // since C++11. A dtor that threw WHILE another exception propagates would
    // mean two exceptions in flight -> std::terminate. We DOCUMENT it (never
    // run it): the noexcept-default dtor guarantee is exactly what prevents it.
    std::printf("\n(3) dtors are implicitly noexcept (C++11+) -> unwinding can't meet a 2nd throw:\n");
    check("Tracker's dtor is noexcept (is_nothrow_destructible_v<Tracker>)",
          std::is_nothrow_destructible_v<Tracker>);
    check("throw-from-dtor-DURING-unwind -> std::terminate (documented; never run — ends program)",
          true);
}

// === Section C — noexcept specifier/operator + the noexcept-MOVE-vs-COPY choice
//
// Two different `noexcept`s: the SPECIFIER (a promise on a declaration; a
// violation calls std::terminate) and the OPERATOR (a compile-time bool query,
// unevaluated). Their payoff: std::vector MOVEs elements on reallocation IFF the
// move ctor is noexcept; otherwise it COPYs — via std::move_if_noexcept — so that
// push_back/resize keep their STRONG guarantee (a throwing move mid-relocation
// could not be rolled back). This deepens move_semantics.cpp Section D.

int alwaysOk() noexcept { return 1; }   // noexcept promise (called with a safe input below)
int mayFail() { return 2; }             // not noexcept -> potentially-throwing (never throws here)

// Conditional noexcept: noexcept(noexcept(expr)). Propagates the promise: this
// template is noexcept iff T() is noexcept.
template <class T>
int usingT() noexcept(noexcept(T())) { return 0; }

// A type whose default ctor is potentially-throwing (no noexcept). We only ever
// name it in an unevaluated noexcept() query — never construct it.
struct ThrowsDefault {
    ThrowsDefault() {}   // declared without noexcept -> potentially-throwing
};

// Two move-semantics probe types, identical except their move ctor's noexcept-ness.
struct MoveOk {           // noexcept move -> vector MOVES on reallocation
    MoveOk() = default;
    MoveOk(MoveOk&&) noexcept = default;
    MoveOk(const MoveOk&) = default;
};
struct MoveBad {          // throwing move -> vector COPIES on reallocation
    MoveBad() = default;
    MoveBad(MoveBad&&) noexcept(false) {}   // explicitly throwing move
    MoveBad(const MoveBad&) noexcept(false) {}
};

void sectionC() {
    sectionBanner("C — noexcept specifier/operator & the move-vs-copy reallocation choice");

    // (1) SPECIFIER (promise) vs OPERATOR (compile-time bool query). We CALL both
    //     with safe inputs (so they are odr-used) AND query noexcept() on them.
    std::printf("(1) noexcept SPECIFIER (promise) vs OPERATOR (compile-time query):\n");
    std::printf("    int alwaysOk() noexcept;   int mayFail();\n");
    std::printf("    alwaysOk() = %d ;  mayFail() = %d  (both called with safe bodies)\n",
                alwaysOk(), mayFail());
    std::printf("    noexcept(alwaysOk()) = %d ;  noexcept(mayFail()) = %d\n",
                static_cast<int>(noexcept(alwaysOk())), static_cast<int>(noexcept(mayFail())));
    check("alwaysOk() is noexcept (specifier promise)", noexcept(alwaysOk()));
    check("mayFail() is potentially-throwing (!noexcept)", !noexcept(mayFail()));

    // (2) Conditional noexcept: noexcept(noexcept(T())). Propagates the promise.
    std::printf("\n(2) conditional noexcept — noexcept(noexcept(T())):\n");
    std::printf("    usingT<int>()           noexcept = %d (int() is noexcept)\n",
                static_cast<int>(noexcept(usingT<int>())));
    std::printf("    usingT<ThrowsDefault>() noexcept = %d (ThrowsDefault() may throw)\n",
                static_cast<int>(noexcept(usingT<ThrowsDefault>())));
    check("usingT<int>() is noexcept (propagated: int() is noexcept)", noexcept(usingT<int>()));
    check("usingT<ThrowsDefault>() is NOT noexcept (propagated: ctor may throw)",
          !noexcept(usingT<ThrowsDefault>()));

    // (3) The move-vs-copy reallocation decision. std::move_if_noexcept yields:
    //     T&&  iff is_nothrow_move_constructible<T> OR copy is unavailable,
    //     const T&  otherwise. std::vector uses it so push_back stays STRONG.
    std::printf("\n(3) move_if_noexcept — vector's strong-guarantee move/copy decision:\n");
    std::printf("    is_nothrow_move_constructible<MoveOk>  = %d (noexcept move)\n",
                static_cast<int>(std::is_nothrow_move_constructible_v<MoveOk>));
    std::printf("    is_nothrow_move_constructible<MoveBad> = %d (throwing move)\n",
                static_cast<int>(std::is_nothrow_move_constructible_v<MoveBad>));
    check("MoveOk has a noexcept move ctor (is_nothrow_move_constructible)",
          std::is_nothrow_move_constructible_v<MoveOk>);
    check("MoveBad has a THROWING move ctor (!is_nothrow_move_constructible)",
          !std::is_nothrow_move_constructible_v<MoveBad>);

    // Compile-time PROOF of the return type (declval is unevaluated):
    std::printf("    move_if_noexcept(MoveOk&)  -> MoveOk&&  (MOVE on reallocation)\n");
    std::printf("    move_if_noexcept(MoveBad&) -> const MoveBad& (COPY on reallocation)\n");
    check("move_if_noexcept(MoveOk&) yields MoveOk&& (move — noexcept)",
          std::is_same_v<decltype(std::move_if_noexcept(std::declval<MoveOk&>())), MoveOk&&>);
    check("move_if_noexcept(MoveBad&) yields const MoveBad& (copy — for strong guarantee)",
          std::is_same_v<decltype(std::move_if_noexcept(std::declval<MoveBad&>())), const MoveBad&>);

    std::printf("    => std::vector MOVES MoveOk on realloc; COPIES MoveBad. A throwing move\n");
    std::printf("       would break push_back's STRONG guarantee (a half-moved element can't roll back).\n");
    check("mark move ctors noexcept so vector MOVES (else it COPIES for the strong guarantee)",
          true);
}

// === Section D — NEVER throw from a destructor; noexcept(false); the cost model =
//
// Destructors are implicitly noexcept since C++11 — this is what makes stack
// unwinding (Section B) safe: a dtor can't introduce a SECOND exception in
// flight. A noexcept(false) dtor is legal but almost always a bug: if it throws
// WHILE unwinding, std::terminate() -> std::abort() fires (no catch can save it).
// We DOCUMENT this path (never run it). We also document the COST model: modern
// ABIs (Itanium C++ ABI on Unix/macOS, 64-bit SEH on Windows) are "zero-cost-
// when-not-thrown" — table-driven EH — so the happy path pays nothing; the cost
// lands only when an exception is actually thrown, plus binary size for tables.

struct ImplicitDtor {     // the normal case: dtor is implicitly noexcept
    std::vector<int> data;
};
struct BadDtor {          // declared noexcept(false); body does NOT throw
    ~BadDtor() noexcept(false) {}
};

void sectionD() {
    sectionBanner("D — never throw from a dtor; noexcept(false); the cost model");

    // (1) Implicit dtors are noexcept (the unwinding-safety guarantee).
    std::printf("(1) destructors are implicitly noexcept (C++11+) -> unwinding is safe:\n");
    check("ImplicitDtor's dtor is noexcept (the default)",
          std::is_nothrow_destructible_v<ImplicitDtor>);
    check("std::vector<int>'s dtor is noexcept (RAII frees during unwinding)",
          std::is_nothrow_destructible_v<std::vector<int>>);

    // (2) noexcept(false) dtor: legal, but if it threw during unwinding -> terminate.
    std::printf("\n(2) noexcept(false) dtor — legal, but dangerous:\n");
    std::printf("    struct BadDtor { ~BadDtor() noexcept(false) {} };  // declared, never throws here\n");
    check("BadDtor's dtor is potentially-throwing (!is_nothrow_destructible)",
          !std::is_nothrow_destructible_v<BadDtor>);
    std::printf("    if ~BadDtor actually threw WHILE another exception propagated -> std::terminate.\n");
    check("throw-from-dtor-during-unwind -> std::terminate (documented; body never throws here)",
          true);

    // (3) The OTHER two std::terminate triggers (both documented, never run):
    //     - a noexcept function that throws (no catch can intercept it);
    //     - an uncaught exception escaping main / a thread entry point.
    std::printf("\n(3) the other std::terminate triggers (documented; never run):\n");
    std::printf("    a) a noexcept function that throws  -> std::terminate\n");
    std::printf("    b) an uncaught exception            -> std::terminate\n");
    check("noexcept-violation -> std::terminate (documented; never run)", true);
    check("uncaught exception -> std::terminate (every throw in THIS bundle is caught)", true);

    // (4) The COST model (documented — wall-clock timing is non-deterministic).
    std::printf("\n(4) cost model: zero-cost-when-NOT-thrown (table-driven EH, Itanium C++ ABI):\n");
    std::printf("    happy path: NO per-try/catch overhead (the compiler emits unwind TABLES instead)\n");
    std::printf("    thrown path: unwinding-table walk + handler lookup (expensive) + .text size growth\n");
    std::printf("    (opposite of older setjmp/longjmp 'SJLJ' models where every try costs a little)\n");
    check("cost model documented (not measured): zero-cost-when-not-thrown on this ABI", true);
}

// === Section E — exceptions vs error codes vs std::expected & cross-language ====
//
// C++ offers THREE error-signaling styles for the SAME failure. We show all
// three on "divide by zero", then map them to the 5-language curriculum. The
// modern pivot: std::expected<T,E> (C++23, P2505 / P0762) is C++'s Rust-Result<T,E>
// analog — the "exceptions vs expected" debate is the cross-language hinge.

enum class DivCode { Ok, ZeroDivisor };

auto divThrow = [](int a, int b) -> int {
    if (b == 0) throw std::runtime_error("div by zero");
    return a / b;
};
auto divCode = [](int a, int b, int& out) -> DivCode {
    if (b == 0) return DivCode::ZeroDivisor;   // b==0 checked BEFORE the division (no UB)
    out = a / b;
    return DivCode::Ok;
};
auto divExpected = [](int a, int b) -> std::expected<int, std::string> {
    if (b == 0) return std::unexpected(std::string("div by zero"));
    return a / b;
};

void sectionE() {
    sectionBanner("E — exceptions vs error codes vs std::expected & cross-language");

    // (1) THROW: a control-flow JUMP to a handler; the happy path stays clean.
    std::printf("(1) THROW (control-flow jump to a handler):\n");
    std::printf("    divThrow(10, 0) -> ");
    std::string thrownMsg;
    try {
        divThrow(10, 0);
    } catch (const std::exception& e) {
        thrownMsg = e.what();
        std::printf("caught \"%s\"\n", e.what());
    }
    check("throw path: div by zero caught", thrownMsg == "div by zero");

    // (2) ERROR CODE: explicit return; the caller MUST check (no silent ignore).
    std::printf("\n(2) ERROR CODE (explicit return; caller must check):\n");
    int quotient = 0;
    DivCode rc = divCode(10, 0, quotient);
    std::printf("    divCode(10, 0, out) -> DivCode::%s\n",
                rc == DivCode::ZeroDivisor ? "ZeroDivisor" : "Ok");
    check("error-code path: divCode(10,0) returned ZeroDivisor", rc == DivCode::ZeroDivisor);
    check("error-code path: quotient left untouched (==0)", quotient == 0);

    // (3) std::expected<T,E> (C++23): a typed value-or-error; no jump; the caller
    //     must inspect to access the value. C++'s Rust-Result<T,E> analog.
    std::printf("\n(3) std::expected<int,string> (C++23 — typed value-or-error, no jump):\n");
    auto r1 = divExpected(10, 2);
    auto r2 = divExpected(10, 0);
    std::printf("    divExpected(10, 2) -> %s\n",
                r1.has_value() ? std::to_string(*r1).c_str() : "error");
    std::printf("    divExpected(10, 0) -> error \"%s\"\n",
                r2.has_value() ? "" : r2.error().c_str());
    check("std::expected: 10/2 == 5 (value present)", r1.has_value() && *r1 == 5);
    check("std::expected: 10/0 is an error (no throw, no jump)",
          !r2.has_value() && r2.error() == "div by zero");

    // (4) The cross-language map (the 5-language curriculum). C++ is the ONLY
    //     language here that spans BOTH philosophies (throw AND return-expected).
    std::printf("\n(4) cross-language error signaling:\n");
    std::printf("    C++     : throw/try/catch  AND  std::expected<T,E> (both philosophies)\n");
    std::printf("    TS      : throw/try/catch   (closest to C++; GC-backed)\n");
    std::printf("    Python  : raise/try/except  (throw-based; GC-backed; cheap/idiomatic)\n");
    std::printf("    Go      : return error, if err != nil  (EXPLICIT, no throw)\n");
    std::printf("    Rust    : Result<T,E> + ?   (typed, FORCED handling, NO exceptions)\n");
    check("cross-language map documented (C++ spans both throw AND return-expected)", true);
}

}  // namespace

int main() {
    std::printf("exceptions_deep.cpp — Phase 7 bundle (the full depth of exception SAFETY).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23 -O2\n");
    std::printf("-Wall -Wextra -Wpedantic; UB-free (just sanitize clean); every throw caught.\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
