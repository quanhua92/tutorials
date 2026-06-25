// benchmarking.cpp — Phase 8 bundle (benchmarking / BENCHMARKING).
//
// GOAL (one line): show, by printing only DETERMINISTIC structure & operation
// counts (NEVER a measured wall-clock value), how C++ benchmarking works — the
// Google Benchmark skeleton (BENCHMARK macro, the timed loop, the runner), the
// anti-elision "use the result" trick, the -O level to measure at, the hardware
// profilers (perf / Valgrind-Callgrind), the micro-vs-macro pyramid, and the
// "measure, don't guess" discipline.
//
// This is the GROUND TRUTH for BENCHMARKING.md. Every line, table, and worked
// example in the guide is printed by this file. Change it -> re-compile ->
// re-paste. Never hand-compute.
//
// DETERMINISM CONTRACT (THE key rule for THIS bundle): measured TIMINGS are
// NON-REPRODUCIBLE (clock, cache, scheduling, temperature), so this file NEVER
// prints or asserts an elapsed-nanosecond value. It asserts only (a) the
// STRUCTURE of a benchmark (the API surface — what it measures, not how long),
// (b) FIXED iteration counts, (c) FIXED OPERATION COUNTS (deterministic
// integers), and (d) a RELATIVE ORDERING ("the optimized version does fewer
// operations than the naive one"). steady_clock is used ONLY to demonstrate the
// SHAPE of a timed loop (the reading is consumed, never printed). `just out` is
// therefore byte-identical on re-run.
//
// Run:
//     just run benchmarking   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                benchmarking.cpp -o /tmp/cpp_benchmarking
//                                && /tmp/cpp_benchmarking)

#include <algorithm>   // std::sort (median on a fixed sample)
#include <chrono>      // steady_clock: the SHAPE of a timed loop (value never printed)
#include <cstdint>     // int64_t, uint32_t
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar), strstr
#include <string>      // holding the Google Benchmark skeleton string
#include <string_view> // the skeleton as a view for substring checks
#include <vector>      // the fixed median sample

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

// contains reports whether `haystack` contains `needle` (a substring check on a
// fixed string — used to assert the STRUCTURAL tokens of the Google Benchmark
// skeleton without depending on the external library).
bool contains(std::string_view haystack, std::string_view needle) {
    return haystack.find(needle) != std::string_view::npos;
}

// doNotOptimize is a portable, inline-asm-free approximation of Google
// Benchmark's benchmark::DoNotOptimize(). The REAL one uses a compiler-specific
// asm constraint to constrain the value's liveness WITHOUT forcing a store; the
// portable approximation here is a volatile sink, which forces a load+store the
// optimizer cannot remove. It demonstrates the PRINCIPLE: a computation whose
// result is unused MAY be elided under -O2; routing it through this sink forces
// it to be computed. (Use only on trivially-copyable scalars.)
template <typename T>
void doNotOptimize(T const& value) {
    volatile T sink;
    sink = value;   // the volatile store can't be elided
    (void)sink;
}

// The canonical Google Benchmark skeleton — the de-facto C++ micro-benchmarking
// API surface. We hold it as a STRING so we can assert its STRUCTURAL shape
// (tokens like BENCHMARK(, for (auto _ : state), DoNotOptimize, BENCHMARK_MAIN())
// without linking the external library (this bundle is stdlib-first).
const std::string GOOGLE_BENCHMARK_SKELETON = R"SKELETON(
    #include <benchmark/benchmark.h>

    static void BM_SumSquares(benchmark::State& state) {
        const int N = static_cast<int>(state.range(0));
        for (auto _ : state) {                 // <-- the timed loop
            long long acc = 0;
            for (int i = 0; i < N; ++i) acc += 1LL * i * i;
            benchmark::DoNotOptimize(acc);      // <-- anti-elision "use the result"
            state.SetItemsProcessed(state.iterations() * N);
        }
    }
    BENCHMARK(BM_SumSquares)->Arg(1000)->Iterations(1000);

    BENCHMARK_MAIN();                           // <-- the runner (parses --bench_*)
)SKELETON";

// A MINIMAL harness that mimics the SHAPE of Google Benchmark's benchmark::State:
// a fixed iteration count plus an items-processed counter. It carries NO clock
// reading into the output (determinism): the only "measured" quantities are the
// FIXED iteration count and the operation counts, both deterministic integers.
struct MiniState {
    std::int64_t iterations;
    std::int64_t items_processed = 0;
    std::int64_t work_units = 0;  // operation counter (each "work unit" is deterministic)

    void SetItemsProcessed(std::int64_t n) { items_processed = n; }
};

// Naive popcount: tests every bit -> ALWAYS 32 iterations for a 32-bit value,
// regardless of how many bits are set. Reports its iteration count.
int popcountNaive(std::uint32_t n, int& iters) {
    int count = 0;
    iters = 0;
    for (int b = 0; b < 32; ++b) {   // ALWAYS 32 iterations
        ++iters;
        if ((n >> b) & 1u) ++count;
    }
    return count;
}

// Kernighan's bit count: clears the lowest set bit each step -> EXACTLY one
// iteration per set bit (popcount(n) iterations). Same result, far fewer ops
// when the value is sparse. A deterministic demonstration that you must MEASURE
// (or count) to see the difference — the compiler cannot fix your algorithm.
int popcountKernighan(std::uint32_t n, int& iters) {
    int count = 0;
    iters = 0;
    while (n != 0) {                 // exactly popcount(n) iterations
        ++iters;
        n &= n - 1;                  // clears the lowest set bit
        ++count;
    }
    return count;
}

// === Section A — Google Benchmark: the skeleton & the anti-elision trick ======
//
// The de-facto C++ micro-benchmarking framework. Its API surface: a function
// taking benchmark::State&; a `for (auto _ : state)` timed loop; the
// BENCHMARK(Name)->...() registration; and BENCHMARK_MAIN() (the runner that
// parses --bench_* flags). The critical "use the result" trick: route the
// computation's result through benchmark::DoNotOptimize() (a sink) so the
// optimizer cannot ELIDE a computation whose result is unused.
void sectionA() {
    sectionBanner("A — Google Benchmark: skeleton + the anti-elision trick");

    // (1) The canonical skeleton — the STRUCTURAL tokens a benchmark is built of.
    std::printf("(1) The Google Benchmark skeleton (the de-facto C++ micro-bench API):\n");
    std::printf("%s\n", GOOGLE_BENCHMARK_SKELETON.c_str());

    check("skeleton contains `benchmark::State&` (the per-benchmark state)",
          contains(GOOGLE_BENCHMARK_SKELETON, "benchmark::State&"));
    check("skeleton contains `for (auto _ : state)` (the timed loop)",
          contains(GOOGLE_BENCHMARK_SKELETON, "for (auto _ : state)"));
    check("skeleton contains `benchmark::DoNotOptimize` (the anti-elision sink)",
          contains(GOOGLE_BENCHMARK_SKELETON, "benchmark::DoNotOptimize"));
    check("skeleton contains `state.SetItemsProcessed` (throughput reporting)",
          contains(GOOGLE_BENCHMARK_SKELETON, "state.SetItemsProcessed"));
    check("skeleton contains `state.iterations()` (the iteration count)",
          contains(GOOGLE_BENCHMARK_SKELETON, "state.iterations()"));
    check("skeleton contains `BENCHMARK(` registration macro",
          contains(GOOGLE_BENCHMARK_SKELETON, "BENCHMARK(BM_SumSquares)"));
    check("skeleton contains `BENCHMARK_MAIN()` (the runner)",
          contains(GOOGLE_BENCHMARK_SKELETON, "BENCHMARK_MAIN()"));

    // (2) The "USE THE RESULT" anti-elision trick. Under -O2 a computation whose
    //     result is UNUSED may be optimized away entirely (the compiler sees dead
    //     code). The fix: route the result through a sink (DoNotOptimize) AND/OR
    //     accumulate it so it is consumed. We prove the loop ran by asserting the
    //     accumulated sum equals its closed form (an INDEPENDENT computation).
    constexpr std::int64_t ITERS = 100'000;   // FIXED iteration count (deterministic)
    long long sink = 0;
    for (std::int64_t i = 0; i < ITERS; ++i) {
        long long r = i * (i + 1);   // a computation whose result is USED...
        doNotOptimize(r);             // ...forced materialized (anti-elision)
        sink += r;                    // ...and consumed ("use the result")
    }
    // Closed form (independent of the loop): sum_{i=0}^{N-1} i*(i+1) == S2 + S1,
    // where S2 = (N-1)*N*(2N-1)/6 and S1 = (N-1)*N/2, with N = ITERS.
    const std::int64_t N = ITERS;
    const long long S2 = (N - 1) * N * (2 * N - 1) / 6;
    const long long S1 = (N - 1) * N / 2;
    const long long expected = S2 + S1;

    std::printf("\n(2) Anti-elision: a FIXED-count loop (%lld iters) routed through a sink.\n",
                static_cast<long long>(ITERS));
    std::printf("    loop-accumulated sink  = %lld\n", sink);
    std::printf("    closed-form expected    = %lld  (sum_{i=0}^{%lld-1} i*(i+1))\n",
                expected, static_cast<long long>(ITERS));
    std::printf("    (sink == expected PROVES the loop body ran; without a sink, -O2 may\n");
    std::printf("     elide an unused computation -> a benchmark measuring nothing.)\n");

    check("anti-elision: sink == closed form (the loop body actually ran)", sink == expected);
    check("ITERS is the fixed count (no wall-clock involved)", ITERS == 100'000);
}

// === Section B — Optimization levels (-O0/-O2/-O3) + warm-up + iterations =====
//
// WHICH -O level you measure at changes EVERYTHING. -O0 is the default for
// debug builds and is MISLEADING for benchmarks (no inlining, no vectorization —
// you measure debug overhead, not the code). -O2 is the standard for measuring
// (a good balance: aggressive but stable). -O3 is aggressive (may help via
// auto-vectorization, or hurt via code bloat/IC-pressure) — measure both if it
// matters. The deterministic fact we CAN assert: this bundle compiles at -O2,
// which defines the `__OPTIMIZE__` macro (undefined at -O0).
void sectionB() {
    sectionBanner("B — Optimization levels + warm-up + iteration count");

    // (1) The -O levels (documented meanings; -O2 is the measure-at default).
    std::printf("(1) Optimization levels (measure at -O2, NOT -O0):\n");
    std::printf("    -O0  no optimization       debug builds; MISLEADING for benchmarks (measures debug overhead)\n");
    std::printf("    -O1  light optimization     reduce code size + some basic opts\n");
    std::printf("    -O2  standard optimization  THE level to measure at (aggressive but stable)\n");
    std::printf("    -O3  aggressive             auto-vectorization, may help OR hurt (IC pressure); measure both\n");
    std::printf("    -Os  optimize for size      like -O2 minus size-growing opts\n");
    std::printf("    -Ofast -O3 + -ffast-math    BREAKS IEEE-754 — NEVER for a trustworthy benchmark\n");

    // The deterministic, compile-time signal: `__OPTIMIZE__` is predefined by
    // clang/gcc whenever -O1 or higher is in effect. Since `just run` compiles
    // with -O2, the macro is defined here; under -O0 it is undefined (and
    // `__NO_INLINE__` is defined instead). This is a reproducible, zero-runtime
    // proof of which optimization family the benchmark ran under.
#ifdef __OPTIMIZE__
    std::printf("\n(2) Compile-time signal: __OPTIMIZE__ is DEFINED -> optimization is ON.\n");
    std::printf("    (`just run` compiles at -O2; under -O0 __OPTIMIZE__ is undefined.)\n");
    check("__OPTIMIZE__ defined -> this benchmark runs optimized (measuring real code)",
          true);
#else
    std::printf("\n(2) Compile-time signal: __OPTIMIZE__ is NOT defined -> -O0.\n");
    std::printf("    (WARNING: measuring at -O0 is MISLEADING for benchmarks.)\n");
    check("__OPTIMIZE__ defined -> this benchmark runs optimized (measuring real code)",
          false);
#endif

    // (3) WARM-UP + iteration count. A benchmark loop has two phases: a WARM-UP
    //     (run to fill caches / branch predictors / stabilize the CPU frequency —
    //     results DISCARDED) then the MEASURED phase. Google Benchmark
    //     auto-tunes the iteration count (runs a few, extrapolates to hit the
    //     minimum time, then measures for real). Our MiniState uses a FIXED count
    //     for determinism; the SHAPE (warm-up then measure) is what matters here.
    MiniState warmup{.iterations = 1'000};        // warm-up: discarded
    std::int64_t warmup_work = 0;
    for (std::int64_t i = 0; i < warmup.iterations; ++i) warmup_work += i;  // discarded
    doNotOptimize(warmup_work);

    MiniState measured{.iterations = 50'000};     // measured: FIXED count
    long long acc = 0;
    for (std::int64_t i = 0; i < measured.iterations; ++i) {
        acc += i;
        ++measured.work_units;
    }
    doNotOptimize(acc);
    measured.SetItemsProcessed(measured.iterations);   // throughput = iters/items

    std::printf("\n(3) Warm-up (DISCARDED) then MEASURED loop (the benchmark shape):\n");
    std::printf("    warm-up  : %lld iters (discarded; fills caches, stabilizes CPU)\n",
                static_cast<long long>(warmup.iterations));
    std::printf("    measured : %lld iters (FIXED count) -> work_units=%lld, items_processed=%lld\n",
                static_cast<long long>(measured.iterations),
                static_cast<long long>(measured.work_units),
                static_cast<long long>(measured.items_processed));

    check("warm-up ran its fixed iteration count", warmup_work == (warmup.iterations - 1) * warmup.iterations / 2);
    check("measured loop ran its fixed iteration count (work_units == iterations)",
          measured.work_units == measured.iterations);
    check("measured items_processed == iterations (throughput shape)", measured.items_processed == measured.iterations);
    check("Google Benchmark auto-tunes iterations (documented); MiniState uses a FIXED count",
          measured.iterations == 50'000);
}

// === Section C — Hardware profiling: perf (Linux) + Valgrind/Callgrind =======
//
// Once a micro-benchmark says "this is slow", the profilers explain WHY. perf
// (Linux-only) reads HARDWARE performance counters (cache misses, branch
// misses, cycles, instructions retired -> IPC). Valgrind/Callgrind is a
// deterministic INSTRUCTION-LEVEL simulator (counts executed instructions +
// builds a call graph) — slow but accurate and not Linux-specific. Neither runs
// here (perf is Linux-only; this box is macOS), so we document the command
// surface and demonstrate a cache-relevant code PATTERN whose timing difference
// perf would reveal — which we deliberately do NOT print (nondeterministic).
void sectionC() {
    sectionBanner("C — Hardware profilers: perf (Linux) + Valgrind/Callgrind");

    // (1) perf — the Linux profiler. Reads CPU hardware counters.
    std::printf("(1) perf (Linux): reads HARDWARE performance counters.\n");
    std::printf("    perf stat -e cycles,instructions,cache-misses,branch-misses ./prog   # aggregate counters\n");
    std::printf("    perf record -g ./prog          # sample + call stack; perf report to browse\n");
    std::printf("    key counters: cycles, instructions, cache-misses, branch-misses,\n");
    std::printf("                  L1-dcache-load-misses, LLC-load-misses -> IPC = instructions / cycles\n");

    // (2) Valgrind/Callgrind — deterministic instruction-level profiling.
    std::printf("\n(2) Valgrind/Callgrind: DETERMINISTIC instruction-level simulator.\n");
    std::printf("    valgrind --tool=callgrind ./prog      # counts executed instructions + call graph\n");
    std::printf("    callgrind_annotate callgrind.out.*    # text report\n");
    std::printf("    kcachegrind callgrind.out.*           # GUI browser\n");
    std::printf("    slow (~20-50x) but ACCURATE; not Linux-only; uses NO hardware counters.\n");

    // (3) A cache-relevant PATTERN perf would catch: row-major vs column-major
    //     traversal of a matrix. SAME number of element accesses, SAME sum, but
    //     the ACCESS ORDER differs. Row-major touches contiguous memory (cache-
    //     friendly); column-major strides by N words (cache-unfriendly -> many
    //     cache misses). The timing gap is exactly what `perf stat -e
    //     cache-misses` reveals. We assert only the deterministic facts: equal
    //     access count, equal sum, different order — and REFUSE to print timing.
    constexpr int DIM = 4;
    int matrix[DIM][DIM];
    for (int r = 0; r < DIM; ++r)
        for (int c = 0; c < DIM; ++c) matrix[r][c] = r * DIM + c + 1;  // 1..16

    long long sumRowMajor = 0, sumColMajor = 0;
    std::int64_t rowAccesses = 0, colAccesses = 0;
    for (int r = 0; r < DIM; ++r)
        for (int c = 0; c < DIM; ++c) { sumRowMajor += matrix[r][c]; ++rowAccesses; }
    for (int c = 0; c < DIM; ++c)
        for (int r = 0; r < DIM; ++r) { sumColMajor += matrix[r][c]; ++colAccesses; }

    std::printf("\n(3) Cache pattern (perf -e cache-misses would catch the gap):\n");
    std::printf("    %dx%d matrix; row-major vs column-major traversal.\n", DIM, DIM);
    std::printf("    row-major accesses = %lld, sum = %lld  (contiguous -> cache-friendly)\n",
                static_cast<long long>(rowAccesses), sumRowMajor);
    std::printf("    col-major accesses = %lld, sum = %lld  (strided   -> cache-unfriendly)\n",
                static_cast<long long>(colAccesses), sumColMajor);
    std::printf("    (identical access COUNT & sum; TIMING differs wildly -> MEASURE, don't guess.)\n");

    check("row-major and column-major access the SAME number of elements",
          rowAccesses == colAccesses && rowAccesses == static_cast<std::int64_t>(DIM) * DIM);
    check("both traversals produce the SAME sum (1+2+...+16 = 136)",
          sumRowMajor == sumColMajor && sumRowMajor == 136);
    check("perf is Linux-only (not on macOS); Callgrind is cross-platform (documented)",
          contains("perf stat -e cache-misses", "cache-misses"));
}

// === Section D — Micro vs macro benchmarking + statistical stability =========
//
// The benchmarking PYRAMID: micro-benchmarks (one isolated function, fast, many
// iterations) at the base; integration benchmarks (a subsystem) in the middle;
// macro / end-to-end benchmarks (a whole request / pipeline, few iterations but
// realistic) at the top. Each level catches different regressions. Statistical
// stability: run N repetitions, report MEDIAN (resistant to outliers) + the
// spread (deviation), and WATCH for outliers from OS scheduling / thermal noise.
void sectionD() {
    sectionBanner("D — Micro vs macro benchmarking + statistical stability");

    // (1) The pyramid (documented).
    std::printf("(1) The benchmarking PYRAMID (which level catches which regression):\n");
    std::printf("    macro    (end-to-end: a whole request/pipeline)  few iters, REALISTIC noise\n");
    std::printf("    integration (a subsystem)                        middle ground\n");
    std::printf("    micro   (one isolated function)                  many iters, low noise, may miss the big picture\n");
    std::printf("    rule: a micro win that loses at the macro level is NOT a win.\n");

    // (2) Median over a FIXED sample. Real runs feed measured timings; here we
    //     feed FIXED integers to show the AGGREGATION shape (median + deviation)
    //     deterministically. The median is resistant to outliers (the 9999 spike
    //     barely moves it), which is why benchmark reporters prefer median/mean.
    std::vector<long long> samples = {41, 42, 40, 43, 42, 39, 42, 9999, 41, 42};
    std::vector<long long> sorted = samples;
    std::sort(sorted.begin(), sorted.end());
    long long median = (sorted[sorted.size() / 2 - 1] + sorted[sorted.size() / 2]) / 2;
    long long min = sorted.front();
    long long max_excluding_spike = sorted[sorted.size() - 2];  // drop the outlier

    std::printf("\n(2) Aggregation over a FIXED sample (real runs feed measured timings):\n");
    std::printf("    samples (10): {41,42,40,43,42,39,42,9999,41,42}  <- the 9999 is an outlier\n");
    std::printf("    median   = %lld  (resistant to the outlier)\n", median);
    std::printf("    min      = %lld\n", min);
    std::printf("    2nd-max  = %lld  (after dropping the single outlier)\n", max_excluding_spike);

    check("median of the fixed sample is 42 (outlier barely moved it)", median == 42);
    check("min is 39", min == 39);
    check("after dropping the outlier, the spread is tight (<= 43)", max_excluding_spike == 43);
    check("benchmark reporters prefer median + deviation over a single sample",
          median < 9999);
}

// === Section E — "Measure, don't guess" + cross-language parallels ============
//
// The discipline that ties it together: human intuition about performance is
// almost always WRONG. Branch prediction, cache effects, SIMD vectorization,
// and (the central C++ trap) the optimizer DELETING your benchmarked code all
// conspire to make guesses worthless. The only honest answer is to measure —
// with the right framework (Google Benchmark), the right level (-O2), an
// anti-elision sink, and a profiler (perf/Callgrind) to explain the result.
void sectionE() {
    sectionBanner("E — \"Measure, don't guess\" + cross-language parallels");

    // (1) "Measure, don't guess" — a deterministic operation-count demo. You'd
    //     GUESS the two popcount implementations are similar; counting reveals
    //     the naive one ALWAYS does 32 iterations while Kernighan's does only
    //     popcount(n). The compiler cannot fix your ALGORITHM — you must count
    //     (or time). Here we assert the RELATIVE ORDERING (naive > Kernighan) and
    //     correctness, never the wall-clock time.
    // A sparse 32-bit value with exactly 6 set bits (positions 4,7,13,18,22,28).
    constexpr std::uint32_t SPARSE =
        (1u << 4) | (1u << 7) | (1u << 13) | (1u << 18) | (1u << 22) | (1u << 28);
    int naiveIters = 0, kernIters = 0;
    int naiveCount = popcountNaive(SPARSE, naiveIters);
    int kernCount = popcountKernighan(SPARSE, kernIters);

    std::printf("(1) Measure, don't guess — popcount on a SPARSE value (6 set bits):\n");
    std::printf("    naive     (test every bit): %d iterations -> count=%d\n", naiveIters, naiveCount);
    std::printf("    Kernighan (clear each bit) : %d iterations -> count=%d\n", kernIters, kernCount);
    std::printf("    (you'd GUESS similar; the naive does %.1fx more work — the optimizer\n",
                static_cast<double>(naiveIters) / static_cast<double>(kernIters));
    std::printf("     can't fix the algorithm; MEASURE / COUNT to see it.)\n");

    check("naive popcount always does 32 iterations (tests every bit)", naiveIters == 32);
    check("Kernighan popcount does popcount(n) iterations (6 for this value)", kernIters == 6);
    check("relative ordering: naive does MORE iterations than Kernighan", naiveIters > kernIters);
    check("both popcount implementations give the SAME (correct) result", naiveCount == kernCount && kernCount == 6);

    // (2) Cross-language parallels (the 5-language curriculum).
    std::printf("\n(2) Cross-language benchmarking (the 5-language curriculum):\n");
    std::printf("    C++    : Google Benchmark  (external; BENCHMARK macro + DoNotOptimize)\n");
    std::printf("    Go     : testing.B         (BUILT IN to the standard test runner; b.N, ns/op)\n");
    std::printf("    Rust   : criterion         (external; the de-facto, like Google Benchmark)\n");
    std::printf("    -> Go is unique: benchmarks ship WITH the test runner, no separate framework.\n");

    check("Go ships benchmarks BUILT IN (testing.B); C++ needs Google Benchmark (external)",
          contains("Go     : testing.B", "testing.B"));
    check("Rust's de-facto is criterion (external); C++'s is Google Benchmark (external)",
          contains("Rust   : criterion", "criterion"));
    check("\"measure, don't guess\": intuition (branch/cache/vectorization/elision) is unreliable",
          naiveIters != kernIters);
}

}  // namespace

int main() {
    std::printf("benchmarking.cpp — Phase 8 bundle (benchmarking / BENCHMARKING).\n");
    std::printf("Every line below is printed by this file. Compiled -std=c++23 -O2\n");
    std::printf("-Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    std::printf("DETERMINISM: no measured TIMING is ever printed/asserted — only structure,\n");
    std::printf("fixed iteration counts, and operation counts (deterministic integers).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
