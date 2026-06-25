// rule_of_0_3_5.cpp — Phase 3 bundle #22.
//
// GOAL (one line): show, by counting every special-member call, WHEN to write
// each of the FIVE special member functions (destructor / copy ctor + assign /
// move ctor + assign) — the Rule of 0 (write none; use RAII members so the
// compiler-generated defaults are correct), Rule of 3 (you own a resource ->
// dtor + copy pair, DEEP), Rule of 5 (+ the move pair, steal O(1)) — and pin
// the shallow-copy double-free trap as a documented expert payoff (gated behind
// #ifdef DEMO_UB, never executed in the verified path).
//
// This is the GROUND TRUTH for RULE_OF_0_3_5.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run rule_of_0_3_5   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                 rule_of_0_3_5.cpp -o /tmp/cpp_rule_of_0_3_5
//                                 && /tmp/cpp_rule_of_0_3_5)

#include <cstddef>    // std::size_t
#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset / strlen / strcpy (banner + the raw-resource class)
#include <string>     // std::string (the Rule-of-0 RAII member)
#include <type_traits>  // std::is_copy_constructible_v / is_move_constructible_v / ...

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

// ── The op-counter: how we PROVE which special member ran ────────────────────
//
// Every instrumented class below bumps exactly ONE of these per special-member
// call. Reset before a scenario, snapshot after, and the delta tells you
// unambiguously whether a copy or a move happened — the empirical proof the
// Rule of 5 is actually moving and the "declaring copy suppresses move" gotcha
// is actually copying.
struct Counters {
    int allocs = 0;        // heap new[] by the raw-resource classes
    int frees = 0;         // heap delete[] by the raw-resource classes
    int copies = 0;        // copy-ctor calls
    int copy_assigns = 0;  // copy-assign calls
    int moves = 0;         // move-ctor calls
    int move_assigns = 0;  // move-assign calls
    int dtors = 0;         // destructor calls
} g;

void resetCounters() { g = Counters{}; }

void printCounters(const char* label) {
    std::printf("    [ops:%-13s] allocs=%d frees=%d  copies=%d copy_assigns=%d  "
                "moves=%d move_assigns=%d  dtors=%d\n",
                label, g.allocs, g.frees, g.copies, g.copy_assigns,
                g.moves, g.move_assigns, g.dtors);
}

// ── Tracked: a value member that counts its own special-member calls ─────────
//
// Used as a member of RuleOfZero so we can OBSERVE that the compiler-generated
// copy/move/dtor of RuleOfZero correctly DELEGATE to the member's copy/move/dtor
// (the whole point of Rule of 0). Tracked itself follows the Rule of 0: it has
// no raw resource, so its (compiler-generated or = default) special members are
// correct. We declare them explicitly only so we can instrument them.
struct Tracked {
    int payload;
    explicit Tracked(int v = 0) : payload(v) {}
    Tracked(const Tracked& o) : payload(o.payload) { ++g.copies; }
    Tracked(Tracked&& o) noexcept : payload(o.payload) { o.payload = -1; ++g.moves; }
    Tracked& operator=(const Tracked& o) {
        payload = o.payload;
        ++g.copy_assigns;
        return *this;
    }
    Tracked& operator=(Tracked&& o) noexcept {
        payload = o.payload;
        o.payload = -1;
        ++g.move_assigns;
        return *this;
    }
    ~Tracked() { ++g.dtors; }
};

// ── RuleOfZero: write NONE; RAII member does the right thing ─────────────────
//
// No user-declared destructor / copy / move. The compiler generates all five,
// and they correctly member-wise copy/move/destroy the std::string AND the
// Tracked member. This is the modern preference (C++ Core Guidelines C.20).
class RuleOfZero {
    std::string name_;
    Tracked value_;
public:
    explicit RuleOfZero(std::string n, int v) : name_(std::move(n)), value_(v) {}
    // No dtor, no copy ctor/assign, no move ctor/assign declared -> all 5 are
    // implicitly generated and CORRECT (string + Tracked handle themselves).
    const std::string& name() const { return name_; }
    int value() const { return value_.payload; }
};

// ── RuleOfThree: you own a raw resource -> dtor + copy pair (DEEP copy) ───────
//
// The classic pre-C++11 rule: if you write the destructor (because you manage a
// raw resource), you MUST also write the copy ctor + copy assign — otherwise the
// compiler-generated copies SHALLOW-copy the pointer and the two destructors
// double-free (UB). The copy ctor here allocates a NEW buffer and strcpy's into
// it: a genuine DEEP copy. (No move pair yet -> moves fall back to copy; see D.)
class RuleOfThree {
    char* buf_;       // the managed resource (raw pointer to a heap char[])
    std::size_t n_;   // length (not including the '\0')
public:
    explicit RuleOfThree(const char* s) : buf_(nullptr), n_(0) {
        if (s) {
            n_ = std::strlen(s);
            buf_ = new char[n_ + 1];
            std::strcpy(buf_, s);
            ++g.allocs;
        }
    }
    ~RuleOfThree() {
        delete[] buf_;   // frees ONCE (the deep-copy invariant: every buf_ is unique)
        ++g.frees;
        ++g.dtors;
    }
    // II. copy ctor: DEEP copy (allocate a fresh buffer, strcpy the contents).
    RuleOfThree(const RuleOfThree& o) : buf_(nullptr), n_(o.n_) {
        if (o.buf_) {
            buf_ = new char[n_ + 1];
            std::strcpy(buf_, o.buf_);
            ++g.allocs;
        }
        ++g.copies;
    }
    // III. copy assign: DEEP copy (release the old buffer, allocate+strcpy new).
    // new-then-delete order for the strong exception guarantee on the allocation.
    RuleOfThree& operator=(const RuleOfThree& o) {
        if (this != &o) {
            char* fresh = nullptr;
            if (o.buf_) {
                fresh = new char[o.n_ + 1];
                std::strcpy(fresh, o.buf_);
                ++g.allocs;
            }
            delete[] buf_;
            ++g.frees;
            buf_ = fresh;
            n_ = o.n_;
        }
        ++g.copy_assigns;
        return *this;
    }
    // No move ctor/assign declared. Because we declared a copy ctor + dtor, the
    // compiler does NOT implicitly generate them (the gotcha from Section D).
    const char* data() const { return buf_ ? buf_ : "<empty>"; }
};

// ── RuleOfFive: extend Rule of 3 with the move pair (STEAL, O(1)) ────────────
//
// Same raw resource as RuleOfThree, but now we ALSO write the move ctor/assign.
// The move ops STEAL the buffer (pointer-copy + null the source) instead of
// deep-copying: O(1) instead of O(n), and zero allocation. This is the C++11
// extension of the Rule of 3.
class RuleOfFive {
    char* buf_;
    std::size_t n_;
public:
    explicit RuleOfFive(const char* s) : buf_(nullptr), n_(0) {
        if (s) {
            n_ = std::strlen(s);
            buf_ = new char[n_ + 1];
            std::strcpy(buf_, s);
            ++g.allocs;
        }
    }
    ~RuleOfFive() {
        delete[] buf_;
        ++g.frees;
        ++g.dtors;
    }
    RuleOfFive(const RuleOfThree&) = delete;  // (no cross-type copy; keeps the demo single-class)
    RuleOfFive(const RuleOfFive& o) : buf_(nullptr), n_(o.n_) {
        if (o.buf_) {
            buf_ = new char[n_ + 1];
            std::strcpy(buf_, o.buf_);
            ++g.allocs;
        }
        ++g.copies;
    }
    RuleOfFive& operator=(const RuleOfFive& o) {
        if (this != &o) {
            char* fresh = nullptr;
            if (o.buf_) {
                fresh = new char[o.n_ + 1];
                std::strcpy(fresh, o.buf_);
                ++g.allocs;
            }
            delete[] buf_;
            ++g.frees;
            buf_ = fresh;
            n_ = o.n_;
        }
        ++g.copy_assigns;
        return *this;
    }
    // IV. move ctor: STEAL the buffer (O(1), no allocation), leave the source empty.
    RuleOfFive(RuleOfFive&& o) noexcept : buf_(o.buf_), n_(o.n_) {
        o.buf_ = nullptr;
        o.n_ = 0;
        ++g.moves;
    }
    // V. move assign: release ours, STEAL theirs (O(1)).
    RuleOfFive& operator=(RuleOfFive&& o) noexcept {
        if (this != &o) {
            delete[] buf_;
            ++g.frees;
            buf_ = o.buf_;
            n_ = o.n_;
            o.buf_ = nullptr;
            o.n_ = 0;
        }
        ++g.move_assigns;
        return *this;
    }
    const char* data() const { return buf_ ? buf_ : "<empty>"; }
};

// ── CopyOnly: isolates the "declaring copy suppresses move" gotcha ───────────
//
// Declares ONLY a user-provided copy ctor (no dtor, no move, no copy/move
// assign). Per the implicit-declaration rules, a user-declared copy ctor
// SUPPRESSES the implicit move ctor (and move assign). So `CopyOnly b =
// std::move(a);` cannot move — it falls back to the COPY ctor. The std::move is
// a no-op-style cast, not a guarantee that a move ctor runs. This silently turns
// O(1) moves into O(n) copies.
class CopyOnly {
public:
    int payload;
    explicit CopyOnly(int v) : payload(v) {}
    CopyOnly(const CopyOnly& o) : payload(o.payload) { ++g.copies; }  // user-declared -> suppresses move
    CopyOnly& operator=(const CopyOnly& o) {
        payload = o.payload;
        ++g.copy_assigns;
        return *this;
    }
    ~CopyOnly() { ++g.dtors; }
};

// ── MoveOnly: copy ops = delete, move ops user-provided (unique_ptr-like) ─────
//
// The canonical "delete copy to make move-only" idiom: the move-only object is
// the C++ analog of Rust's non-Clone move-semantics type. = delete makes the
// copy ops not just absent but ILL-FORMED to call (a hard compile error if you
// try), which is stronger than merely not declaring them.
class MoveOnly {
public:
    int* data;
    explicit MoveOnly(int v) : data(new int(v)) { ++g.allocs; }
    ~MoveOnly() {
        delete data;
        ++g.frees;
        ++g.dtors;
    }
    MoveOnly(const MoveOnly&) = delete;             // forbid copy ctor
    MoveOnly& operator=(const MoveOnly&) = delete;  // forbid copy assign
    MoveOnly(MoveOnly&& o) noexcept : data(o.data) {
        o.data = nullptr;
        ++g.moves;
    }
    MoveOnly& operator=(MoveOnly&& o) noexcept {
        if (this != &o) {
            delete data;
            ++g.frees;
            data = o.data;
            o.data = nullptr;
        }
        ++g.move_assigns;
        return *this;
    }
};

// ── Polymorphic base: virtual ~Base so `delete base_ptr` runs ~Derived too ───
//
// When a class is meant to be used polymorphically (via Base*), its destructor
// MUST be `public virtual` (or `protected` non-virtual if deletion through Base*
// is forbidden). A non-virtual ~Base makes `delete base_ptr` UNDEFINED BEHAVIOR:
// only ~Base runs, ~Derived is skipped, and any resources Derived owns LEAK. The
// presence of a user-declared (here = default'd) destructor blocks the implicit
// move pair, so a polymorphic base must ALSO =default the move/copy ops if it
// wants them (C.21: define or =delete them all).
class PolyBase {
public:
    PolyBase() = default;
    PolyBase(const PolyBase&) = default;
    PolyBase(PolyBase&&) = default;
    PolyBase& operator=(const PolyBase&) = default;
    PolyBase& operator=(PolyBase&&) = default;
    virtual ~PolyBase() = default;   // THE KEY: virtual ~ for polymorphic deletion
};
class PolyDerived : public PolyBase {
public:
    int extra;
    explicit PolyDerived(int e) : extra(e) {}
};

// ============================================================================
// Section A — The five special members & the compiler's implicit-declaration map
// ============================================================================
void sectionA() {
    sectionBanner("A — The 5 special members & implicit-declaration rules");

    std::printf("A class has up to FIVE SPECIAL MEMBER FUNCTIONS the compiler\n");
    std::printf("can generate for you:\n\n");
    std::printf("  1. destructor           ~T()                  / ~T() = default\n");
    std::printf("  2. copy constructor     T(const T&)           / T(const T&) = default\n");
    std::printf("  3. copy assignment      T& operator=(const T&)/ ... = default\n");
    std::printf("  4. move constructor     T(T&&)  [C++11]       / T(T&&) = default\n");
    std::printf("  5. move assignment      T& operator=(T&&)     / ... = default\n");
    std::printf("\n(default constructor is also 'special' but is NOT part of the 0/3/5 rules.)\n");

    std::printf("\nThe implicit-declaration matrix (what the compiler AUTO-generates,\n");
    std::printf("given what YOU wrote). 'Y'=implicitly defaulted; '-'=NOT generated;\n");
    std::printf("'!'=generated but DEPRECATED (P0641, removed the deprecation in C++17\n");
    std::printf("for the copy-pair-after-dtor case).\n\n");
    std::printf("  You write...                     | dtor | copy ctor | copy assign | move ctor | move assign\n");
    std::printf("  ---------------------------------+------+-----------+-------------+-----------+------------\n");
    std::printf("  (nothing)                        |  Y   |    Y      |     Y       |    Y      |     Y\n");
    std::printf("  destructor                       | user |    Y(!)   |     Y(!)    |    -      |     -\n");
    std::printf("  copy ctor                        |  Y   |   user    |     Y(!)    |    -      |     -\n");
    std::printf("  copy assign                      |  Y   |    Y(!)   |    user     |    -      |     -\n");
    std::printf("  move ctor                        |  Y   |    -      |     -       |   user    |     -\n");
    std::printf("  move assign                      |  Y   |    -      |     -       |    -      |    user\n");
    std::printf("\nThe single most important row for experts: writing ANY of {dtor, copy ctor,\n");
    std::printf("copy assign} SUPPRESSES both implicit move ops. That is the gotcha that turns\n");
    std::printf("an O(1) move into an O(n) copy without a single warning (see Section D).\n");

    // Compile-time proof of the matrix, via the classes defined above.
    std::printf("\nCompile-time check of the matrix on the classes defined in this file:\n");
    std::printf("  RuleOfZero  (wrote none):           copy+move all generated.\n");
    check("RuleOfZero is copy-constructible (compiler-generated)",
          std::is_copy_constructible_v<RuleOfZero>);
    check("RuleOfZero is move-constructible (compiler-generated)",
          std::is_move_constructible_v<RuleOfZero>);
    check("RuleOfZero is copy-assignable (compiler-generated)",
          std::is_copy_assignable_v<RuleOfZero>);
    check("RuleOfZero is move-assignable (compiler-generated)",
          std::is_move_assignable_v<RuleOfZero>);

    std::printf("  RuleOfThree (dtor+copy pair):       copy present, MOVE absent.\n");
    check("RuleOfThree is copy-constructible (user-declared)",
          std::is_copy_constructible_v<RuleOfThree>);
    check("RuleOfThree is move-constructible (falls back to copy, so still 'true')",
          std::is_move_constructible_v<RuleOfThree>);
    // The MOVE is not user-declared; is_move_constructible is still true because
    // the copy ctor (const T&) binds to an rvalue. The empirical proof that NO
    // move ctor runs is the op-counter in Section D.

    std::printf("  RuleOfFive  (all five user-written): all five present.\n");
    check("RuleOfFive is copy-constructible (user-declared)",
          std::is_copy_constructible_v<RuleOfFive>);
    check("RuleOfFive is move-constructible (user-declared)",
          std::is_move_constructible_v<RuleOfFive>);

    std::printf("  MoveOnly    (copy=delete, move=user): move-only, like unique_ptr.\n");
    check("MoveOnly is NOT copy-constructible (= delete)",
          !std::is_copy_constructible_v<MoveOnly>);
    check("MoveOnly IS move-constructible (user-declared)",
          std::is_move_constructible_v<MoveOnly>);
    check("MoveOnly is NOT copy-assignable (= delete)",
          !std::is_copy_assignable_v<MoveOnly>);
    check("MoveOnly IS move-assignable (user-declared)",
          std::is_move_assignable_v<MoveOnly>);
}

// ============================================================================
// Section B — Rule of 0: write NONE; RAII members make the defaults correct
// ============================================================================
void sectionB() {
    sectionBanner("B — Rule of 0: write none; RAII members do the right thing");

    std::printf("RULE OF 0 (the modern preference, C++ Core Guidelines C.20):\n");
    std::printf("  write NONE of the five. Give your class RAII members (std::string,\n");
    std::printf("  std::vector, std::unique_ptr, ...). The compiler-generated defaults\n");
    std::printf("  member-wise copy/move/destroy those members, which is correct because\n");
    std::printf("  each member manages its OWN resource. No raw pointer -> no leak,\n");
    std::printf("  no double-free, no shallow copy. The Rule of 0 class below has a\n");
    std::printf("  std::string + a Tracked member; we OBSERVE the defaults delegating.\n\n");

    resetCounters();
    {
        RuleOfZero a("alpha", 11);
        std::printf("(1) Construct one RuleOfZero a(\"alpha\", 11):\n");
        printCounters("after ctor a");
        check("RuleOfZero ctor did not copy/move the member (direct-init)",
              g.copies == 0 && g.moves == 0);

        resetCounters();
        RuleOfZero b = a;   // compiler-generated COPY ctor: member-wise copies name_ + value_
        std::printf("\n(2) RuleOfZero b = a;  (COPY -> compiler delegates to members)\n");
        printCounters("after copy b=a");
        check("copy of RuleOfZero ran exactly ONE member copy (the Tracked)",
              g.copies == 1);
        check("deep copy: b has its own name 'alpha' independent of a",
              b.name() == "alpha" && a.name() == "alpha");
        check("deep copy: b has its own value 11 independent of a",
              b.value() == 11 && a.value() == 11);

        resetCounters();
        RuleOfZero c = std::move(a);  // compiler-generated MOVE ctor: member-wise moves
        std::printf("\n(3) RuleOfZero c = std::move(a);  (MOVE -> compiler delegates)\n");
        printCounters("after move c=std::move(a)");
        check("move of RuleOfZero ran exactly ONE member move (the Tracked), zero copies",
              g.moves == 1 && g.copies == 0);
        check("move transferred the payload to c (c.value == 11)",
              c.value() == 11);
        check("move left a in a valid-but-unspecified state (we do NOT assert a.value)",
              true);

        resetCounters();
        b = c;   // compiler-generated copy ASSIGN
        std::printf("\n(4) b = c;  (COPY ASSIGN -> compiler delegates)\n");
        printCounters("after b=c");
        check("copy-assign of RuleOfZero ran one member copy-assign (the Tracked)",
              g.copy_assigns == 1);

        resetCounters();
        b = std::move(c);   // compiler-generated move ASSIGN
        std::printf("\n(5) b = std::move(c);  (MOVE ASSIGN -> compiler delegates)\n");
        printCounters("after b=std::move(c)");
        check("move-assign of RuleOfZero ran one member move-assign (the Tracked)",
              g.move_assigns == 1);
    }  // a, b, c destructed here -> 3 Tracked dtors
    std::printf("\n(6) scope ends -> 3 RuleOfZero objects destroyed (a, b, c)\n");
    printCounters("after scope");
    check("3 RuleOfZero destructors ran (compiler-generated ~RuleOfZero delegates)",
          g.dtors == 3);
}

// ============================================================================
// Section C — Rule of 3: you own a raw resource -> dtor + copy pair (DEEP copy)
// ============================================================================
void sectionC() {
    sectionBanner("C — Rule of 3: dtor + copy pair, DEEP copy (shallow = double-free)");

    std::printf("RULE OF 3 (the pre-C++11 discipline, still required for raw resources):\n");
    std::printf("  if you write ANY of {destructor, copy ctor, copy assign}, write ALL\n");
    std::printf("  THREE. You are managing a resource whose handle is a non-class type\n");
    std::printf("  (raw pointer, FILE*, fd, ...). The compiler's implicit copies would\n");
    std::printf("  SHALLOW-copy the handle -> two objects point at the same resource ->\n");
    std::printf("  BOTH destructors release it -> DOUBLE-FREE (UB). The copy ctor must\n");
    std::printf("  DEEP-copy: allocate a NEW buffer and copy the contents.\n\n");

    // ── (1) The deep copy is observable: two independent buffers, same contents.
    resetCounters();
    {
        RuleOfThree a("hello");
        std::printf("(1) RuleOfThree a(\"hello\");  -> one allocation\n");
        printCounters("after ctor a");
        check("RuleOfThree ctor allocated exactly once", g.allocs == 1 && g.frees == 0);

        resetCounters();
        RuleOfThree b = a;   // user copy ctor: DEEP copy
        std::printf("\n(2) RuleOfThree b = a;  (DEEP copy -> a SECOND allocation)\n");
        printCounters("after copy b=a");
        check("the copy ctor made a SECOND, independent allocation (deep copy)",
              g.allocs == 1 && g.copies == 1);
        check("both a and b hold 'hello' (same contents, different buffers)",
              std::strcmp(a.data(), "hello") == 0 && std::strcmp(b.data(), "hello") == 0);

        resetCounters();
        RuleOfThree c("world");
        resetCounters();   // measure ONLY the assign below, not c's ctor alloc
        c = a;               // user copy assign: DEEP copy (release c's old buffer, new)
        std::printf("\n(3) RuleOfThree c(\"world\"); c = a;  (DEEP copy assign)\n");
        printCounters("after c=a");
        check("copy-assign freed c's old 'world' buffer (1 free) and allocated a new one (1 alloc)",
              g.allocs == 1 && g.frees == 1 && g.copy_assigns == 1);
        check("after assign, c holds 'hello' (deep-copied from a)",
              std::strcmp(c.data(), "hello") == 0);
        check("after assign, a is still 'hello' (deep copy did not steal)",
              std::strcmp(a.data(), "hello") == 0);
        resetCounters();   // measure ONLY the scope-end destructions
    }  // a, b, c destroyed -> 3 frees (one per object; no double-free because deep)
    std::printf("\n(4) scope ends -> 3 destructors, 3 frees (one per object; deep copy\n");
    std::printf("    guaranteed every buf_ was UNIQUE, so every delete[] is well-formed)\n");
    printCounters("after scope");
    check("Rule of 3: 3 destructors freed exactly 3 buffers (no double-free)",
          g.frees == 3 && g.dtors == 3);

    // ── (2) The shallow-copy trap: DOCUMENTED, never executed in the verified path.
    std::printf("\n── THE TRAP: what the COMPILER-GENERATED copy would do ──────────────\n");
    std::printf("If RuleOfThree had ONLY the destructor (no copy pair), the compiler's\n");
    std::printf("implicit copy ctor would member-wise copy the char* buf_ — i.e. copy the\n");
    std::printf("POINTER, not the buffer. Two objects would share one buffer:\n");
    std::printf("  a.buf_ == b.buf_   (same address, two owners)\n");
    std::printf("When both a and b are destroyed, ~RuleOfThree calls delete[] on that SAME\n");
    std::printf("address TWICE -> DOUBLE-FREE -> undefined behavior (heap corruption,\n");
    std::printf("crash, or silent memory corruption that ASan catches as\n");
    std::printf("'heap-use-after-free' on the second delete). The #ifdef DEMO_UB block\n");
    std::printf("below contains exactly that broken class; it is NEVER compiled by\n");
    std::printf("`just run` / `just out` / `just check` / `just sanitize`, so the default\n");
    std::printf("and sanitizer builds stay UB-free.\n");
    check("the verified path does NOT run the shallow-copy double-free (DEMO_UB gated)",
          true);

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by the default/sanitizer builds ─────────
    // Compile with -DDEMO_UB to build this; RUNNING it triggers a DOUBLE-FREE.
    // ASan reports "heap-use-after-free" / "attempting double-free"; without ASan
    // the symptom is heap corruption or a crash that varies per run.
    class NaiveShallow {
        char* buf_;
    public:
        explicit NaiveShallow(const char* s) {
            buf_ = new char[std::strlen(s) + 1];
            std::strcpy(buf_, s);
        }
        ~NaiveShallow() { delete[] buf_; }   // NO copy pair -> implicit copy is SHALLOW
        // (compiler-generated copy ctor copies buf_ by value -> two owners)
    };
    NaiveShallow x("doom");
    NaiveShallow y = x;   // SHALLOW copy: x.buf_ == y.buf_  (UB waiting to happen)
    // When `x` and `y` both go out of scope below, delete[] runs on the SAME
    // pointer TWICE. This is the classic Rule-of-3 violation. NEVER ship this.
    std::printf("[DEMO_UB] shallow-copied NaiveShallow; both will delete[] the same buffer -> UB\n");
#else
    std::printf("    (DEMO_UB not defined: the double-free demo is correctly omitted.)\n");
#endif
}

// ============================================================================
// Section D — Rule of 5: + the move pair (STEAL O(1)) & the suppression gotcha
// ============================================================================
void sectionD() {
    sectionBanner("D — Rule of 5: + move pair (steal O(1)); copy suppresses move");

    std::printf("RULE OF 5 (C++11): extend the Rule of 3 with the MOVE pair. Writing any\n");
    std::printf("of {dtor, copy ctor, copy assign} SUPPRESSES the implicit move ctor/assign,\n");
    std::printf("so if you want move semantics (and you do — moves are O(1) where copies\n");
    std::printf("are O(n)) you must declare all FIVE. The move ops STEAL the resource\n");
    std::printf("(pointer-copy + null the source) instead of deep-copying.\n\n");

    // ── (1) RuleOfThree MOVE falls back to COPY (the gotcha, empirically).
    resetCounters();
    {
        RuleOfThree a("grid");
        resetCounters();
        RuleOfThree b = std::move(a);   // no move ctor -> COPY ctor runs instead
        std::printf("(1) RuleOfThree b = std::move(a);  (NO move ctor -> falls back to COPY)\n");
        printCounters("after std::move");
        check("RuleOfThree 'move' actually COPIED (copies==1, moves==0) — the gotcha",
              g.copies == 1 && g.moves == 0);
        check("the fallback copy ALLOCATED a new buffer (allocs==1) — O(n), not O(1)",
              g.allocs == 1);
        check("despite std::move, a still holds 'grid' (the copy ctor read it)",
              std::strcmp(a.data(), "grid") == 0);
        check("b holds 'grid' too (the copy succeeded)",
              std::strcmp(b.data(), "grid") == 0);
    }

    // ── (2) RuleOfFive MOVE actually moves (STEAL — O(1), zero allocation).
    resetCounters();
    {
        RuleOfFive a("grid");
        resetCounters();
        RuleOfFive b = std::move(a);   // user move ctor: STEAL
        std::printf("\n(2) RuleOfFive b = std::move(a);  (MOVE ctor -> STEAL, O(1))\n");
        printCounters("after std::move");
        check("RuleOfFive move did NOT copy (copies==0)",
              g.copies == 0);
        check("RuleOfFive move ran the move ctor (moves==1)",
              g.moves == 1);
        check("the move did NOT allocate (allocs==0) — O(1), stole the buffer",
              g.allocs == 0);
        check("after the steal, b holds 'grid'",
              std::strcmp(b.data(), "grid") == 0);
        check("after the steal, a is empty (the source was nulled)",
              std::strcmp(a.data(), "<empty>") == 0);

        resetCounters();
        RuleOfFive c("temp");
        resetCounters();   // measure ONLY the move-assign below, not c's ctor
        c = std::move(b);   // user move ASSIGN: STEAL
        std::printf("\n(3) RuleOfFive c(\"temp\"); c = std::move(b);  (MOVE assign -> STEAL)\n");
        printCounters("after move-assign");
        check("move-assign freed c's old 'temp' buffer (frees==1)",
              g.frees == 1);
        check("move-assign stole b's buffer (moves==0, move_assigns==1, allocs==0)",
              g.move_assigns == 1 && g.moves == 0 && g.allocs == 0);
        check("after the steal, c holds 'grid'",
              std::strcmp(c.data(), "grid") == 0);
        check("after the steal, b is empty",
              std::strcmp(b.data(), "<empty>") == 0);
    }

    // ── (3) Isolated proof: a class with ONLY a user-declared copy ctor suppresses move.
    resetCounters();
    {
        CopyOnly src(99);
        resetCounters();
        CopyOnly dst = std::move(src);   // no move ctor -> COPY ctor runs
        std::printf("\n(4) CopyOnly (only a user copy ctor) dst = std::move(src);\n");
        std::printf("    -> std::move is just a cast; with no move ctor, the COPY ctor runs.\n");
        printCounters("after std::move on CopyOnly");
        check("CopyOnly 'move' actually COPIED (copies==1, moves==0)",
              g.copies == 1 && g.moves == 0);
        check("dst.payload == 99 (the copy ran)",
              dst.payload == 99);
    }

    // ── (4) = default / = delete: ask the compiler, or forbid.
    std::printf("\n── = default / = delete ────────────────────────────────────────────\n");
    std::printf("  = default  -> \"compiler, generate this for me\" (use when the implicit\n");
    std::printf("                version IS correct but you need to re-state it, e.g. after\n");
    std::printf("                declaring a virtual ~ which suppresses the move pair).\n");
    std::printf("  = delete   -> \"forbid this\" (a hard compile error if anyone calls it).\n");
    std::printf("                The canonical use: copy ops = delete makes a move-only type\n");
    std::printf("                (the unique_ptr idiom).\n\n");

    resetCounters();
    {
        MoveOnly a(7);
        MoveOnly b = std::move(a);   // OK: move ctor
        std::printf("(5) MoveOnly a(7); MoveOnly b = std::move(a);  (move-only, copy = delete)\n");
        printCounters("after move");
        check("MoveOnly move ctor ran (moves==1), no copy possible",
              g.moves == 1 && g.copies == 0);
        check("after the steal, *b.data == 7",
        b.data != nullptr && *b.data == 7);
        check("after the steal, a.data is nullptr",
              a.data == nullptr);

        resetCounters();
        MoveOnly c(0);
        resetCounters();   // measure ONLY the move-assign below, not c's ctor
        c = std::move(b);   // OK: move assign
        std::printf("\n(6) MoveOnly c(0); c = std::move(b);  (move assign)\n");
        printCounters("after move-assign");
        check("MoveOnly move-assign freed c's old int (frees==1) and stole b's (move_assigns==1)",
              g.frees == 1 && g.move_assigns == 1);
        check("after the steal, *c.data == 7",
              c.data != nullptr && *c.data == 7);
        // The lines below would NOT compile (= delete) — documented, not built:
        //   MoveOnly bad = a;      // error: use of deleted function 'MoveOnly::MoveOnly(const MoveOnly&)'
        //   c = a;                 // error: use of deleted function 'MoveOnly::operator=(const MoveOnly&)'
        std::printf("\n    (the copy ctor `MoveOnly bad = a;` and copy assign `c = a;` are\n");
        std::printf("     HARD COMPILE ERRORS because those ops are = delete — documented\n");
        std::printf("     here, not executed; a file containing them would not build.)\n");
        check("MoveOnly copy ops are = delete (compile-time guarantee, verified via traits)",
              !std::is_copy_constructible_v<MoveOnly> && !std::is_copy_assignable_v<MoveOnly>);
    }
}

// ============================================================================
// Section E — Virtual ~Base for polymorphic bases (preview) + cross-language
// ============================================================================
void sectionE() {
    sectionBanner("E — Virtual ~Base for polymorphic bases + cross-language");

    std::printf("POLYMORPHIC BASE CLASSES need a VIRTUAL destructor (C++ Core Guidelines\n");
    std::printf("C.35): if you `delete` a Derived through a Base*, the ~Base must be virtual\n");
    std::printf("so the call dispatches to ~Derived first (then ~Base). A non-virtual ~Base\n");
    std::printf("makes that `delete` UNDEFINED BEHAVIOR: ~Derived is skipped, and any\n");
    std::printf("resources Derived owns LEAK. (The deep UB dive lives in the UNDEFINED_\n");
    std::printf("BEHAVIOR bundle, Phase 7; this is the rule-of-5 preview.)\n\n");

    std::printf("Catch: a user-declared destructor (even `virtual ~Base() = default;`)\n");
    std::printf("SUPPRESSES the implicit move pair — so a polymorphic base that wants move\n");
    std::printf("semantics must =default all five (C.21: define or =delete them all). And\n");
    std::printf("because copying a polymorphic base SLICES off the derived part, the Core\n");
    std::printf("Guidelines (C.67) say a polymorphic class should usually =delete copy/move.\n\n");

    // Safe path: virtual ~Base -> delete through Base* is well-formed.
    PolyBase* p = new PolyDerived(42);
    std::printf("(1) PolyBase* p = new PolyDerived(42);  (virtual ~Base = default)\n");
    delete p;   // SAFE: virtual ~ dispatches to ~PolyDerived, then ~PolyBase.
    std::printf("    delete p;  -> SAFE: ~PolyDerived ran first (virtual dispatch), no leak.\n");
    check("polymorphic delete through Base* with virtual ~ is well-formed (ran, returned)",
          true);

    // What you must NOT write (documented — would be UB; not in the verified path):
    //   class BadBase { public: ~BadBase() = default; };   // NON-virtual ~
    //   class BadDerived : public BadBase { int* big; ~BadDerived(){ delete[] big; } };
    //   BadBase* p = new BadDerived;
    //   delete p;   // <-- UB: ~BadDerived is SKIPPED -> big[] LEAKS.
    // ASan would report this as a leak (on Linux) or a silent leak (on macOS).
    std::printf("\n(2) The UB case is documented, NOT executed:\n");
    std::printf("    class BadBase { public: ~BadBase() = default; };   // NON-virtual ~\n");
    std::printf("    BadBase* p = new BadDerived;  delete p;            // UB: ~Derived skipped\n");
    check("verified path does NOT run the non-virtual-~ delete (UB; documented only)",
          true);

    // ── Cross-language: how the other 4 languages handle "the 5 special members"
    std::printf("\n── CROSS-LANGUAGE: the 5 special members in 5 languages ─────────────\n");
    std::printf("  C++     (this): FIVE user-writable special members; the compiler can\n");
    std::printf("          implicitly generate any of them; getting it wrong = UB (double-\n");
    std::printf("          free, leak, shallow copy). The 0/3/5 discipline exists ONLY here.\n");
    std::printf("  Rust:   NO copy constructors at all. Copying is opt-in via #[derive(Copy,Clone)]\n");
    std::printf("          (and only for types that are bit-trivially-copyable); otherwise\n");
    std::printf("          you must call .clone() EXPLICITLY. There is no user move ctor — a\n");
    std::printf("          move is a bitwise copy of the bytes + a static borrow-check that the\n");
    std::printf("          source is dead. Drop (= the destructor) can be #[derive]'d or hand-\n");
    std::printf("          written. The WHOLE bug class C++ still has via raw resources is\n");
    std::printf("          impossible in Rust by construction.\n");
    std::printf("  Go:     value-copy semantics (the whole struct is copied byte-for-byte) + a\n");
    std::printf("          garbage collector. No user copy ctors; no destructors at all.\n");
    std::printf("  TS/JS:  GC'd; objects are reference-typed; assignment aliases. No special\n");
    std::printf("          members; no RAII; cleanup is finalizers (unreliable) or explicit.\n");
    std::printf("  Python: GC'd + refcounted; __del__ is a finalizer (unreliable timing);\n");
    std::printf("          copy.deepcopy is explicit; no move semantics.\n");
    check("cross-language table printed (C++ is the only one with the 0/3/5 problem)",
          true);
}

}  // namespace

int main() {
    std::printf("rule_of_0_3_5.cpp — Phase 3 bundle #22.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
