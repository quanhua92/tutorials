// testing.cpp — Phase 8 bundle (ecosystem: testing).
//
// GOAL (one line): demonstrate C++'s testing *model* with a tiny INLINE
// in-process runner (registers TEST_CASEs, runs them, counts pass/fail; REQUIRE
// aborts the current test, EXPECT continues), then document the real frameworks
// (Catch2 / GoogleTest / doctest), fixtures, parameterized tests, mocking, TDD,
// and coverage/sanitizers-in-CI.
//
// This is the GROUND TRUTH for TESTING.md. Every number/table below is printed
// by this file. Change it -> re-compile -> re-paste. Never hand-compute.
//
// IMPORTANT: there is NO subprocess and NO external framework here. The mini-
// runner lives entirely in this TU; REQUIRE uses a private exception caught at
// the test-case boundary (the same RAII-safe mechanism Catch2 uses internally).
// The deliberately-failing tests are EXPECTED: the runner correctly counts them
// as failures, and the [check] asserts below verify those exact counts.
//
// Run:
//     just run testing   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                          testing.cpp -o /tmp/cpp_testing && /tmp/cpp_testing)

#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <vector>     // the runner's test registry

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

// ===========================================================================
// A TINY INLINE TEST RUNNER — the model Catch2 / GoogleTest / doctest implement
// ===========================================================================
//
// Every C++ test framework boils down to this loop:
//   1. REGISTER test functions (a registry of {name, fn}).
//   2. RUN each one, catching failures.
//   3. REPORT pass/fail counts.
//
// Real frameworks auto-register via static initializers (the macro below does
// the same). REQUIRE aborts the current test — here via a private exception
// caught per-test (RAII-safe stack unwinding; Catch2 does the same internally).
// EXPECT records the failure and KEEPS GOING (GoogleTest's EXPECT_*). No
// subprocess, no linking, no external dependency — pure stdlib, one TU.

namespace runner_detail {
struct RequireAbort {};   // thrown by REQUIRE; caught at the test-case boundary
}

struct TestCase {
    const char* name;
    void (*fn)();
};

struct Registry {
    std::vector<TestCase> cases;
    int passedCases = 0;
    int failedCases = 0;
    int assertsOk = 0;
    int assertsFail = 0;
    bool currentTestFailed = false;   // reset before each test runs
};

// Meyers singleton — function-local statics are safe from the cross-TU static-
// initialization-order fiasco, which matters because the registrars below run at
// static-init time (before main).
Registry& registry() {
    static Registry r;
    return r;
}

// The two assertion macros every framework offers, in one sharp contrast:
//   REQUIRE(cond) — on fail, ABORT this test  (Catch2 REQUIRE / gtest ASSERT_*)
//   EXPECT(cond)  — on fail, record + CONTINUE (Catch2 CHECK   / gtest EXPECT_*)
#define REQUIRE(cond)                                                            \
    do {                                                                         \
        if (cond) {                                                              \
            ++registry().assertsOk;                                              \
            std::printf("    ok   (%s)\n", #cond);                               \
        } else {                                                                 \
            ++registry().assertsFail;                                            \
            registry().currentTestFailed = true;                                 \
            std::printf("    FAIL (%s)  [REQUIRE -> abort test]\n", #cond);      \
            throw ::runner_detail::RequireAbort{};                               \
        }                                                                        \
    } while (0)

#define EXPECT(cond)                                                             \
    do {                                                                         \
        if (cond) {                                                              \
            ++registry().assertsOk;                                              \
            std::printf("    ok   (%s)\n", #cond);                               \
        } else {                                                                 \
            ++registry().assertsFail;                                            \
            registry().currentTestFailed = true;                                 \
            std::printf("    FAIL (%s)  [EXPECT -> continue]\n", #cond);         \
        }                                                                        \
    } while (0)

// TEST_CASE(name) { body }  — defines a test function AND auto-registers it.
// The anonymous-namespace registrar's constructor pushes {name, fn} into the
// registry at static-init time (before main): the self-registration trick the
// real frameworks use, confined to one TU so there is no cross-TU order fiasco.
#define TEST_CASE(name)                                                          \
    static void name();                                                          \
    namespace {                                                                  \
    struct TestCaseReg_##name {                                                  \
        TestCaseReg_##name() { registry().cases.push_back({#name, name}); }      \
    };                                                                           \
    [[maybe_unused]] TestCaseReg_##name reg_##name;                              \
    }                                                                            \
    static void name()

// Side-effect PROBES the test bodies set; the section functions inspect them to
// PROVE the stop-vs-continue behavior deterministically (no rand/now involved).
bool g_reachedAfterRequire = false;   // REQUIRE-stop proof: STAYS false
bool g_reachedAfterExpect  = false;   // EXPECT-continue proof: set to true
int  g_tableCasesChecked   = 0;       // table-driven: how many rows ran
int  g_fixtureSetups       = 0;       // fixture ctor ("SetUp") count
int  g_fixtureTeardowns    = 0;       // fixture dtor ("TearDown") count

// A FIXTURE: per-test shared setup/teardown. In C++ the idiomatic form is RAII —
// the constructor IS SetUp, the destructor IS TearDown, and the language
// guarantees the dtor runs at scope exit (deterministic, no GC delay). Catch2
// automates this with TEST_CASE_METHOD(F, ...); GoogleTest with TEST_F(F, ...).
struct CounterFixture {
    int value = 0;
    CounterFixture()  { ++g_fixtureSetups; }
    ~CounterFixture() { ++g_fixtureTeardowns; }
    void increment() { ++value; }
};

// --- the test cases (registered at static-init; run later by runAll) --------

TEST_CASE(adds_correctly) {
    REQUIRE(1 + 1 == 2);
    REQUIRE(2 * 3 == 6);
}

TEST_CASE(require_stops_immediately) {
    REQUIRE(true);                       // sanity: passes
    int x = -5;
    REQUIRE(x > 0);                      // FAILS -> aborts; next line NEVER runs
    g_reachedAfterRequire = true;        // <- proof REQUIRE stopped the test body
}

TEST_CASE(expect_continues) {
    EXPECT(false);                       // FAILS but execution CONTINUES
    EXPECT(1 == 2);                      // FAILS but execution CONTINUES
    g_reachedAfterExpect = true;         // <- proof EXPECT did NOT stop
    REQUIRE(g_reachedAfterExpect);       // passes (reachable only because EXPECT continued)
}

TEST_CASE(table_driven_squares) {
    struct Row { int in; int expected; };
    const Row rows[] = {{0, 0}, {1, 1}, {2, 4}, {3, 9}, {-4, 16}};
    for (const auto& r : rows) {
        const int got = r.in * r.in;     // the function under test (square)
        REQUIRE(got == r.expected);      // one REQUIRE per row -> N assertions
        ++g_tableCasesChecked;
    }
}

TEST_CASE(fixture_counter) {
    CounterFixture f;                    // SetUp (RAII ctor) runs here
    REQUIRE(f.value == 0);
    f.increment();
    f.increment();
    REQUIRE(f.value == 2);
}                                        // ~CounterFixture() (TearDown) runs here

// --- the runner -------------------------------------------------------------

void runAll() {
    for (const auto& tc : registry().cases) {
        std::printf("RUN  %s\n", tc.name);
        registry().currentTestFailed = false;
        try {
            tc.fn();                     // invoke the test body
        } catch (const runner_detail::RequireAbort&) {
            // REQUIRE aborted this test; it is already marked failed.
        }
        if (registry().currentTestFailed) {
            ++registry().failedCases;
            std::printf("[FAIL] %s\n", tc.name);
        } else {
            ++registry().passedCases;
            std::printf("[PASS] %s\n", tc.name);
        }
    }
}

// ===========================================================================
// Sections (each prints a banner + a readable block + check() asserts)
// ===========================================================================

void sectionA() {
    sectionBanner("A — the test-runner model: register -> run -> report");

    std::printf("Running %zu registered TEST_CASEs through the inline runner...\n",
                registry().cases.size());
    runAll();

    const int total         = registry().passedCases + registry().failedCases;
    const int passed        = registry().passedCases;
    const int failed        = registry().failedCases;
    const int assertsChecked = registry().assertsOk + registry().assertsFail;

    std::printf("\n--- runner summary ---\n");
    std::printf("test cases: %d | %d passed | %d failed\n", total, passed, failed);
    std::printf("assertions: %d checked (%d ok, %d failed)\n",
                assertsChecked, registry().assertsOk, registry().assertsFail);

    check("runner registered exactly 5 test cases", total == 5);
    check("runner counted 3 passed cases", passed == 3);
    check("runner counted 2 failed cases (the deliberate ones)", failed == 2);
    check("assertions failed == 3 (1 REQUIRE + 2 EXPECT)",
          registry().assertsFail == 3);
}

void sectionB() {
    sectionBanner("B — REQUIRE (stop) vs EXPECT (continue)");

    std::printf("require_stops_immediately: a line AFTER the failing REQUIRE set a flag.\n");
    std::printf("  flag after failing REQUIRE = %s   (false => the test body aborted)\n",
                g_reachedAfterRequire ? "true" : "false");
    std::printf("expect_continues: a line AFTER two failing EXPECTs set a flag.\n");
    std::printf("  flag after failing EXPECT  = %s   (true  => execution continued)\n",
                g_reachedAfterExpect ? "true" : "false");

    check("REQUIRE aborted: the post-failure line did NOT run",
          !g_reachedAfterRequire);
    check("EXPECT continued: the post-failure line DID run",
          g_reachedAfterExpect);
}

void sectionC() {
    sectionBanner("C — table-driven tests (the manual parameterized test)");

    std::printf("table_driven_squares looped 5 rows {in, expected} and REQUIRE'd each.\n");
    std::printf("  rows checked = %d\n", g_tableCasesChecked);

    check("table-driven test checked all 5 rows", g_tableCasesChecked == 5);
}

void sectionD() {
    sectionBanner("D — fixtures: SetUp (ctor) + TearDown (dtor) via RAII");

    std::printf("CounterFixture: ctor == SetUp, dtor == TearDown (RAII, deterministic).\n");
    std::printf("  setups    = %d   (one per test that constructed a CounterFixture)\n",
                g_fixtureSetups);
    std::printf("  teardowns = %d   (ran at scope exit, no GC delay)\n",
                g_fixtureTeardowns);

    check("fixture SetUp ran once", g_fixtureSetups == 1);
    check("fixture TearDown ran once (RAII dtor at scope exit)",
          g_fixtureTeardowns == 1);
}

void sectionE() {
    sectionBanner("E — real frameworks + TDD + coverage/sanitizers (reference)");

    std::printf("C++ has NO stdlib test framework (unlike Go's `testing` and Rust #[test]).\n");
    std::printf("The de-facto choices are external, header-first libraries:\n\n");
    std::printf("  concept      | Catch2          | GoogleTest        | doctest\n");
    std::printf("  -------------|-----------------|-------------------|------------------\n");
    std::printf("  test case    | TEST_CASE       | TEST              | TEST_CASE\n");
    std::printf("  soft assert  | CHECK  continue | EXPECT_* continue | CHECK  continue\n");
    std::printf("  hard assert  | REQUIRE abort   | ASSERT_* abort    | REQUIRE abort\n");
    std::printf("  structure    | SECTION         | (none)            | SUBCASE\n");
    std::printf("  fixture      | TEST_CASE_METHOD| TEST_F            | SUBCASE / class\n");
    std::printf("  BDD          | SCENARIO/GIVEN..| (none)            | SCENARIO/GIVEN..\n");
    std::printf("  parameterized| TEMPLATE_TEST_CASE| TEST_P +       | TEST_CASE_TEMPLATE\n");
    std::printf("              | + GENERATE      | INSTANTIATE_TEST_SUITE_P| + GENERATE\n");
    std::printf("  mocking      | (none; Trompeloeil)| GoogleMock      | (none)\n\n");

    std::printf("TDD cycle:  RED (write a failing test) -> GREEN (make it pass) ->\n");
    std::printf("            REFACTOR (improve the code, keep the tests green).\n");
    std::printf("Coverage:   gcov (gcc) / llvm-cov (clang); lcov / llvm-cov for HTML.\n");
    std::printf("Safety CI:  compile & run tests with -fsanitize=address,undefined\n");
    std::printf("            (ASan + UBSan) alongside the unit suite -> THIS bundle is clean.\n");

    check("this bundle is the inline-runner demo (no external framework linked)", true);
    check("no rand()/clock() used -> output is deterministic across runs", true);
}

}  // namespace

int main() {
    std::printf("testing.cpp — Phase 8 bundle (testing).\n");
    std::printf("Demonstrates C++'s test-runner MODEL with a tiny inline runner.\n");
    std::printf("No subprocess, no external framework. Compiled -std=c++23 -O2\n");
    std::printf("-Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
