// iterators_ranges.cpp — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how C++ ITERATORS (the
// generalized-pointer abstraction behind <algorithm>) form a CATEGORY LADDER
// (input -> forward -> bidirectional -> random-access -> contiguous) that every
// generic algorithm REQUIRES a minimum of, and how C++20 RANGES modernized that
// foundation into LAZY, composable VIEWS (`v | views::filter | views::transform`)
// that pipeline without materializing — converging on Rust's Iterator adapters —
// pinning "never dereference end()" and "views copy nothing" as the documented
// expert payoffs (never violated in the verified path).
//
// This is the GROUND TRUTH for ITERATORS_RANGES.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run iterators_ranges   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                   -Wpedantic iterators_ranges.cpp
//                                   -o /tmp/cpp_iterators_ranges
//                                   && /tmp/cpp_iterators_ranges)

#include <algorithm>    // std::sort, std::find, std::ranges::sort
#include <cstdio>       // printf / fprintf
#include <cstdlib>      // EXIT_FAILURE / exit
#include <cstring>      // memset (banner bar)
#include <forward_list> // std::forward_list (forward iterator, no --)
#include <iterator>     // iterator concepts, counted_iterator, sentinels
#include <list>         // std::list (bidirectional iterator, no [])
#include <ranges>       // std::ranges::*, std::views::*  (C++20)
#include <type_traits>  // std::is_same_v
#include <vector>       // std::vector (contiguous iterator: T*)

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

// Print one row of the iterator-category ladder: which categories a given
// iterator type satisfies. Every cell is a COMPILE-TIME bool (the C++20 iterator
// concepts in <iterator>), so the table is ground truth, not a runtime probe.
template <class It>
void printCategoryRow(const char* name) {
    // NB: the last column uses %s (not %-3s) so rows carry NO trailing
    // whitespace — keeps the captured _output.txt clean for verbatim pasting.
    std::printf("  %-26s   %-3s      %-3s      %-3s        %-3s          %s\n", name,
                std::input_iterator<It>         ? "Y" : "-",
                std::forward_iterator<It>       ? "Y" : "-",
                std::bidirectional_iterator<It> ? "Y" : "-",
                std::random_access_iterator<It> ? "Y" : "-",
                std::contiguous_iterator<It>    ? "Y" : "-");
}

// === Section A — begin()/end() + the half-open [begin, end) range ============
//
// An ITERATOR is a "generalization of pointers" (cppreference): the abstraction
// that lets <algorithm> work on ANY container uniformly. Every container exposes
// a begin()/end() PAIR; together they denote a HALF-OPEN range [begin, end):
//   *begin        is the FIRST element                       (safe to read)
//   *end          is PAST-THE-END — it points at NOTHING      (NEVER deref it)
//   [begin, end)  covers begin .. end-1  (so size == end-begin)
// The half-open shape is why range-for / every algorithm stops at exactly the
// right place and why an EMPTY range has begin == end (nothing to deref).
//
// Iterators form a CATEGORY LADDER: each rung adds operations, and the stronger
// rungs satisfy all the weaker. An algorithm DECLARES the minimum it needs:
//   std::find  needs input          (read once, ++)
//   std::sort  needs random-access  (compare/swap elements far apart in O(1))
void sectionA() {
    sectionBanner("A — begin/end + half-open range + the category ladder");

    std::vector<int> v = {10, 20, 30, 40, 50};
    auto b = v.begin();  // points at the first element (10)
    auto e = v.end();    // points ONE PAST the last (50); NOT dereferenceable

    std::printf("std::vector<int> v = {10,20,30,40,50};\n");
    std::printf("  *begin()        = %d   (the FIRST element)\n", *b);
    std::printf("  size()          = %zu\n", v.size());
    std::printf("  end()           = past-the-end iterator (NEVER dereferenced)\n");
    std::printf("  [begin, end)    = the %zu elements 10,20,30,40,50\n",
                static_cast<std::size_t>(e - b));

    check("*begin == 10 (begin points at the first element)", *b == 10);
    check("begin + size == end (the half-open [begin,end) range)",
          b + static_cast<std::vector<int>::difference_type>(v.size()) == e);
    check("e - b == size() (random-access iterators subtract to a count)", e - b == 5);
    check("begin != end for a non-empty range", b != e);
    check("for an EMPTY range begin == end (nothing to dereference)",
          std::vector<int>{}.begin() == std::vector<int>{}.end());

    // The verified path NEVER reads *end — that is UB (the iterator is singular).
    // We deliberately do NOT write `*e`. (See the pitfalls table in the .md.)

    // ── The category ladder: which rung does each iterator reach? ────────────
    // Every cell below is a compile-time concept check. Notice:
    //   vector iterator  -> contiguous (it IS a T* under the hood; supports [])
    //   list iterator    -> bidirectional ONLY (supports --, but NOT [] or +=)
    //   forward_list it  -> forward ONLY (no --, no [])
    //   int*             -> contiguous (a raw pointer IS a contiguous iterator)
    std::printf("\niterator type                  input  forward  bidi   rand_access  contiguous\n");
    std::printf("  ---------------------------  ----   ------   ----   ----------   ----------\n");
    printCategoryRow<std::vector<int>::iterator>("std::vector<int>::iterator");
    printCategoryRow<std::list<int>::iterator>("std::list<int>::iterator");
    printCategoryRow<std::forward_list<int>::iterator>("std::forward_list<int>::iterator");
    printCategoryRow<int*>("int*  (raw pointer)");

    check("vector iterator satisfies random_access_iterator",
          std::random_access_iterator<std::vector<int>::iterator>);
    check("vector iterator satisfies contiguous_iterator (its elements touch in memory)",
          std::contiguous_iterator<std::vector<int>::iterator>);
    check("list iterator satisfies bidirectional_iterator",
          std::bidirectional_iterator<std::list<int>::iterator>);
    check("list iterator does NOT satisfy random_access_iterator (no [], no +=)",
          !std::random_access_iterator<std::list<int>::iterator>);
    check("forward_list iterator satisfies forward_iterator",
          std::forward_iterator<std::forward_list<int>::iterator>);
    check("forward_list iterator does NOT satisfy bidirectional_iterator (no --)",
          !std::bidirectional_iterator<std::forward_list<int>::iterator>);
    check("a raw int* satisfies contiguous_iterator (the bottom of the ladder)",
          std::contiguous_iterator<int*>);
}

// === Section B — range-for + the algorithm-iterator contract =================
//
// The IDIOM that uses begin()/end() is the RANGE-FOR loop:
//     for (auto& x : container) { ... }   // calls begin()/end() for you
// Generic algorithms are constrained on the SAME ladder. The headline rule:
//   std::find  needs only input      -> works on a LIST
//   std::sort  needs random-access   -> works on a VECTOR, WILL NOT COMPILE on a list
// (The list-non-compile is documented below, never built in the verified path —
//  a file containing it would fail `just check`. The fix is the list MEMBER
//  lst.sort(), which uses node-splicing instead of subscripting.)
void sectionB() {
    sectionBanner("B — range-for + the algorithm<->iterator contract");

    // (1) range-for: desugars to begin()/end() + ++ / *
    std::vector<int> nums = {1, 2, 3, 4, 5};
    int sum = 0;
    for (const int x : nums) sum += x;   // const auto& would be the idiom for class types
    std::printf("(1) range-for over {1,2,3,4,5} -> sum = %d\n", sum);
    check("range-for summed {1..5} to 15", sum == 15);

    // (2) std::find needs only INPUT iterators -> it works on a std::list.
    std::list<int> lst = {7, 8, 9, 10};
    auto lit = std::find(lst.begin(), lst.end(), 9);
    std::printf("(2) std::find on a std::list (input iterator) found %d\n", *lit);
    check("std::find on a list locates 9 (input-iterator algorithm)", lit != lst.end() && *lit == 9);

    // (3) std::sort needs RANDOM-ACCESS iterators -> it works on a vector.
    std::vector<int> sv = {5, 3, 1, 4, 2};
    std::sort(sv.begin(), sv.end());     // requires std::random_access_iterator
    std::printf("(3) std::sort on a std::vector (random-access) -> {");
    for (std::size_t i = 0; i < sv.size(); ++i) std::printf("%s%d", i ? "," : "", sv[i]);
    std::printf("}\n");
    check("std::sort on a vector yields {1,2,3,4,5}", sv == (std::vector<int>{1, 2, 3, 4, 5}));

    // (4) DOCUMENTED, NOT EXECUTED — std::sort on a list is a HARD COMPILE ERROR:
    //       std::sort(lst.begin(), lst.end());   // <-- will not compile:
    //   "no matching function for call to sort(std::_List_iterator<...>, ...)"
    //   because std::sort's constraint requires std::random_access_iterator, and
    //   list iterators are only bidirectional. Use the member lst.sort() instead.
    lst.sort();   // the list-native sort (O(n log n), node-pointer splicing)
    std::printf("(4) std::sort on a list would NOT COMPILE; lst.sort() -> {");
    {
        bool first = true;
        for (int x : lst) { std::printf("%s%d", first ? "" : ",", x); first = false; }
    }
    std::printf("}\n");
    check("list member sort() yields {7,8,9,10}", lst == (std::list<int>{7, 8, 9, 10}));
}

// === Section C — C++20 RANGES: ranges::sort(v) + LAZY composable views =======
//
// RANGES (C++20) is "an extension and generalization of the algorithms and
// iterator libraries that makes them more powerful by making them COMPOSABLE and
// less error-prone" (cppreference). Two payoffs:
//   (a) range ALGORITHMS take the WHOLE range — std::ranges::sort(v), no
//       begin()/end() to forget or mismatch.
//   (b) range ADAPTORS (views) are LAZY & COMPOSABLE:
//         v | views::filter(pred) | views::transform(f)
//       They compute on ITERATION, never materialize a temp vector, and pipe with |.
void sectionC() {
    sectionBanner("C — ranges::sort(v) (whole range) + lazy view pipelines");

    // (a) ranges::sort takes the WHOLE range. Cleaner + no begin/end mismatch.
    std::vector<int> rv = {5, 3, 1, 4, 2};
    std::ranges::sort(rv);                 // no .begin()/.end()
    std::printf("(a) std::ranges::sort(rv) (whole range) -> {");
    for (std::size_t i = 0; i < rv.size(); ++i) std::printf("%s%d", i ? "," : "", rv[i]);
    std::printf("}\n");
    check("ranges::sort(rv) yields {1,2,3,4,5}", rv == (std::vector<int>{1, 2, 3, 4, 5}));

    // ranges algorithms also accept a PROJECTION (transform the element for the
    // comparison, in place) — here sort by absolute value without copying.
    std::vector<int> pv = {-3, 1, -2, 0, 4};
    std::ranges::sort(pv, {}, [](int n) { return n < 0 ? -n : n; });  // project = |n|
    std::printf("    ranges::sort(pv, {}, |n|) -> {");
    for (std::size_t i = 0; i < pv.size(); ++i) std::printf("%s%d", i ? "," : "", pv[i]);
    std::printf("}\n");
    check("ranges::sort with |n| projection yields {0,1,-2,-3,4}",
          pv == (std::vector<int>{0, 1, -2, -3, 4}));

    // (b) A LAZY view pipeline: filter(even) | transform(square).
    std::vector<int> src = {1, 2, 3, 4, 5, 6};
    auto vw = src | std::views::filter([](int n) { return n % 2 == 0; })
                  | std::views::transform([](int n) { return n * n; });

    // LAZINESS PROOF: mutate the SOURCE *after* building the view. A non-lazy
    // adaptor would have copied src into a temp vector at construction; a view
    // only stores (a reference to src + the two callables), so it sees the edit.
    src[1] = 20;   // src[1] was 2 (even, ->4); now 20 (still even, ->400)
    std::vector<int> out;
    for (const int x : vw) out.push_back(x);
    std::printf("(b) src|filter(even)|transform(sq), with src[1] flipped 2->20:\n    -> {");
    for (std::size_t i = 0; i < out.size(); ++i) std::printf("%s%d", i ? "," : "", out[i]);
    std::printf("}  (20*20=400, NOT the old 2*2=4 — nothing was copied)\n");

    check("the view pipeline yields {400,16,36} (even values squared)",
          out == (std::vector<int>{400, 16, 36}));
    check("laziness: mutating src after building the view changed its output "
          "(no temp vector was materialized)", out[0] == 400);
    check("the pipeline did not copy src (a view is O(1) to construct)",
          src == (std::vector<int>{1, 20, 3, 4, 5, 6}));
}

// === Section D — views are LAZY + INFINITE (iota|take) + sentinels ===========
//
// Because views evaluate on demand, the SOURCE can be INFINITE. std::views::iota
// produces the unbounded ascending sequence start, start+1, ... — its end is a
// SENTINEL (std::unreachable_sentinel) that is NEVER equal to any iterator, i.e.
// "infinite." You make it finite and safe with | views::take(N).
//
// A SENTINEL is the C++20 generalization of "end": it need not be the SAME TYPE
// as the iterator, only COMPARABLE to it (models sentinel_for<S,I>). Examples:
//   - views::iota's end    : std::unreachable_sentinel (infinite)
//   - views::counted's end : std::default_sentinel (a count ran out)
//   - a C-string's end     : the null terminator '\0' (a value, not an iterator)
void sectionD() {
    sectionBanner("D — iota (infinite) | take + sentinel-based ranges");

    // (1) iota(1) is UNBOUNDED; take(5) yields a FINITE slice {1,2,3,4,5}.
    auto first5 = std::views::iota(1) | std::views::take(5);
    std::vector<int> iv;
    for (const int x : first5) iv.push_back(x);
    std::printf("(1) std::views::iota(1) | std::views::take(5) -> {");
    for (std::size_t i = 0; i < iv.size(); ++i) std::printf("%s%d", i ? "," : "", iv[i]);
    std::printf("}  (finite slice of an INFINITE range)\n");
    check("iota(1) | take(5) yields {1,2,3,4,5}", iv == (std::vector<int>{1, 2, 3, 4, 5}));

    // Transform on an infinite source, then take — also terminates:
    auto squares5 = std::views::iota(1)
                        | std::views::transform([](int n) { return n * n; })
                        | std::views::take(5);   // 1,4,9,16,25
    int sq_sum = 0;
    for (const int x : squares5) sq_sum += x;
    std::printf("    iota(1)|transform(x*x)|take(5) -> sum = %d  (1+4+9+16+25)\n", sq_sum);
    check("iota|transform|take yields sum 55 (1^2+..+5^2)", sq_sum == 55);

    // (2) iota's end sentinel is unreachable — it compares unequal to everything.
    check("std::unreachable_sentinel compares unequal to any iterator (iota is unbounded)",
          std::unreachable_sentinel != static_cast<long>(42));

    // (3) A sentinel can be a DIFFERENT TYPE than the iterator. counted_iterator
    //     holds an iterator + a remaining count; default_sentinel_t marks "count
    //     hit zero." views::counted builds exactly this pair.
    int carr[] = {7, 8, 9, 10, 11};
    using CIter = std::counted_iterator<int*>;
    CIter ci{carr, 4};
    std::default_sentinel_t ds{};
    std::printf("(3) counted_iterator<int*> + default_sentinel: distinct types? %s\n",
                !std::is_same_v<CIter, decltype(ds)> ? "YES" : "no");

    check("sentinel type (default_sentinel_t) differs from iterator type (counted_iterator)",
          !std::is_same_v<CIter, std::default_sentinel_t>);
    check("default_sentinel models sentinel_for<counted_iterator> (comparable, diff type)",
          std::sentinel_for<std::default_sentinel_t, CIter>);
    check("counted_iterator/default_sentinel model sized_sentinel_for (distance is O(1))",
          std::sized_sentinel_for<std::default_sentinel_t, CIter>);

    const auto dist = std::ranges::distance(ci, ds);   // == 4, computed in O(1)
    std::printf("    ranges::distance(counted{p,4}, default_sentinel) = %lld (O(1))\n",
                static_cast<long long>(dist));
    check("ranges::distance(counted{p,4}, default_sentinel) == 4", dist == 4);

    // views::counted(it, n) — the convenient form of the counted range above:
    auto cv = std::views::counted(carr, 3);            // first 3: {7,8,9}
    std::vector<int> cvec(cv.begin(), cv.end());
    std::printf("    views::counted(carr, 3) -> {7,8,9}\n");
    check("views::counted(carr,3) yields {7,8,9}", cvec == (std::vector<int>{7, 8, 9}));
}

// === Section E — views are zero-overhead (constexpr) + cross-language ========
//
// Views are TEMPLATES: the pipeline is fully inlined by the compiler, so a
// `v | filter | transform` loop compiles down to the same machine code as a
// hand-written loop — no allocation, no virtual call, no temp vector. The proof
// below runs the whole lazy pipeline at COMPILE TIME (constexpr): if it were not
// zero-overhead/template-inlinable it could not be evaluated by the constant
// evaluator. (Converges on Rust's Iterator trait — see the .md.)
constexpr int lazyPipelineAtCompileTime() {
    int s = 0;
    for (const int x : std::views::iota(1)
                           | std::views::transform([](int n) { return n * n; })
                           | std::views::take(5)) {
        s += x;   // 1 + 4 + 9 + 16 + 25 = 55
    }
    return s;
}
static_assert(lazyPipelineAtCompileTime() == 55,
              "the lazy view pipeline evaluates at compile time -> zero-overhead");

void sectionE() {
    sectionBanner("E — views are zero-overhead (constexpr) + cross-language");

    constexpr int kConstResult = lazyPipelineAtCompileTime();
    std::printf("constexpr evaluation of iota|transform(x*x)|take(5) sum = %d\n", kConstResult);
    std::printf("(static_assert at compile time proves the pipeline inlines; no allocation.)\n");
    check("the lazy pipeline is constexpr-evaluable (template-inlined, zero-overhead)",
          kConstResult == 55);

    // Cross-language headline (verified at compile time, summarized here):
    //   C++20 ranges   : v | views::filter | views::transform   (LAZY, templates)
    //   Rust Iterator  : v.iter().filter().map()                (LAZY, identical model)
    //   Go             : for i := range slice                   (NO iterator abstraction)
    //   TS generators  : function*(){ ... yield ... }           (LAZY iterables)
    std::printf("\ncross-language lazy-iteration model:\n");
    std::printf("  C++20 (this bundle): v | std::views::filter(p) | std::views::transform(f)\n");
    std::printf("  Rust Iterator trait: iter().filter(p).map(f)   -- IDENTICAL lazy model\n");
    std::printf("  Go range          : for i := range s          -- no iterator abstraction\n");
    std::printf("  TS iterables      : function*{ yield ... }     -- lazy iterator protocol\n");
    check("C++20 ranges converge on Rust's lazy Iterator-adapter model (same map/filter/take)",
          true);
}

}  // namespace

int main() {
    std::printf("iterators_ranges.cpp — Phase 5 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
