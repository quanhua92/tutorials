// algorithms.cpp — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how `<algorithm>` + `<numeric>`
// expose ~100 generic algorithms over ITERATOR RANGES — sort/find/transform/
// accumulate/partition/unique/copy/minmax — and how C++20 ranges algorithms +
// PROJECTIONS (`ranges::sort(v, {}, &Person::age)`) make them container-agnostic
// and field-aware — pinning the **std::sort is NOT stable** rule and the
// erase-remove idiom as documented expert payoffs (every verified path is
// deterministic: no rand/now, output iterators always have room).
//
// This is the GROUND TRUTH for ALGORITHMS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-compile ->
// re-paste. Never hand-compute.
//
// Run:
//     just run algorithms   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                            algorithms.cpp -o /tmp/cpp_algorithms
//                            && /tmp/cpp_algorithms)

#include <algorithm>   // sort/stable_sort, find/find_if, count, transform, copy/
                       // copy_if, remove, partition/stable_partition, unique,
                       // min_element/max_element/minmax_element, is_sorted,
                       // is_partitioned — AND the C++20 ranges:: overloads.
#include <array>       // std::array (Section E: same algorithm, another range)
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <functional>  // std::greater, std::ranges::greater
#include <iterator>    // std::back_inserter (the safe sink for transform/copy)
#include <numeric>     // std::accumulate (the fold/reduce)
#include <ranges>      // C++20 ranges infrastructure (ranges algorithms live here)
#include <string>      // std::string (Section D: Person.name; Section B: concat)
#include <vector>      // std::vector (+ C++20 std::erase / std::erase_if free fns)

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

// printVec renders a vector<int> as "{ 3, 1, 4, ... }" so output is readable.
void printVec(const char* label, const std::vector<int>& v) {
    std::printf("%s{", label);
    for (std::size_t i = 0; i < v.size(); ++i) {
        std::printf("%d%s", v[i], (i + 1 == v.size()) ? "" : ", ");
    }
    std::printf("}\n");
}

// === Section A — sort (NOT stable) + stable_sort + find/find_if/count =========
//
// std::sort(begin, end) sorts the range IN PLACE in non-descending order. It is
// NOT stable: the relative order of EQUAL elements is UNSPECIFIED (may reorder).
// std::stable_sort is the stable variant (equal elements keep their input order).
//
// DETERMINISM RULE (§4.2): we do NOT assert an exact post-sort order on an
// equal-keyed input under std::sort — that output would be compiler/library-
// dependent. Instead: (1) sort a DISTINCT-value vector and assert ascending;
// (2) demonstrate stability deterministically with std::stable_sort on an
// equal-keyed input (pairs keyed by first, tagged by second) and assert the
// tags survive in input order.
void sectionA() {
    sectionBanner("A — sort (NOT stable) + stable_sort + find/find_if/count");

    // (1) std::sort on DISTINCT values -> ascending (fully deterministic).
    std::vector<int> v = {5, 3, 8, 1, 9, 2, 7, 4, 6};
    printVec("(1) input            ", v);
    std::sort(v.begin(), v.end());
    printVec("    std::sort ->     ", v);
    check("std::sort produced ascending order", std::is_sorted(v.begin(), v.end()));
    check("sorted vector front == 1 (min)", v.front() == 1);
    check("sorted vector back  == 9 (max)", v.back() == 9);

    // (2) STABILITY demo — DETERMINISTIC only via std::stable_sort.
    // Each pair = (key, tag). Keys 1,1,1,2,2 repeat; tags are unique so we can
    // SEE whether equal-key pairs kept their input order.
    using P = std::pair<int, int>;
    std::vector<P> vp = {{1, 10}, {1, 11}, {1, 12}, {2, 20}, {2, 21}};
    std::stable_sort(vp.begin(), vp.end(),
                     [](const P& a, const P& b) { return a.first < b.first; });
    std::printf("(2) stable_sort by key on {1,1,1,2,2} (tags 10,11,12,20,21):\n");
    std::printf("    -> key/tag sequence:");
    for (const auto& p : vp) std::printf(" (%d,%d)", p.first, p.second);
    std::printf("\n");
    // Stable => tags within each equal-key group stay in INPUT order.
    check("stable_sort kept key-1 tags in input order: 10,11,12",
          vp[0].second == 10 && vp[1].second == 11 && vp[2].second == 12);
    check("stable_sort kept key-2 tags in input order: 20,21",
          vp[3].second == 20 && vp[4].second == 21);
    check("std::sort would NOT guarantee this (NOT stable) — documented, not run",
          true);

    // (3) find / find_if / count.
    std::vector<int> f = {3, 1, 4, 1, 5, 9, 2, 6, 5};
    printVec("(3) search source    ", f);

    auto it = std::find(f.begin(), f.end(), 9);   // -> iterator to first 9
    check("std::find(begin,end,9) found 9 (iter != end)", it != f.end() && *it == 9);

    auto neg = std::find(f.begin(), f.end(), 99); // -> end (not present)
    check("std::find(begin,end,99) returned end (absent)", neg == f.end());

    // find_if with a lambda: first element > 5.
    auto gt = std::find_if(f.begin(), f.end(), [](int x) { return x > 5; });
    check("std::find_if(x>5) returned the first such element (9)",
          gt != f.end() && *gt == 9);

    // count(value): std::count returns a SIGNED difference_type — cast to print.
    auto c1 = std::count(f.begin(), f.end(), 1);  // 1 appears twice
    auto c5 = std::count(f.begin(), f.end(), 5);  // 5 appears twice
    std::printf("    count(1)=%ld   count(5)=%ld   (difference_type)\n",
                static_cast<long>(c1), static_cast<long>(c5));
    check("count(1) == 2", c1 == 2);
    check("count(5) == 2", c5 == 2);

    // count_if(pred): count even numbers.
    auto neven = std::count_if(f.begin(), f.end(),
                               [](int x) { return x % 2 == 0; });  // 4,2,6 -> 3
    std::printf("    count_if(even)=%ld\n", static_cast<long>(neven));
    check("count_if(even) == 3 (the values 4,2,6)", neven == 3);
}

// === Section B — transform (map -> back_inserter) + accumulate + copy =========
//
// std::transform(begin, end, outIter, fn) is MAP: applies fn to each element and
// writes the result to outIter. The sink MUST have room — the safe idiom is
// std::back_inserter(aVector), which push_back's as it goes (NO OOB write).
//
// std::accumulate(begin, end, init, op) is FOLD/REDUCE: starts with init, folds
// each element in via op (default op = +  -> SUM). Any binary op works, so
// accumulate also does product, string concat, min-tracking, etc.
void sectionB() {
    sectionBanner("B — transform (map) + accumulate (fold) + copy/copy_if");

    std::vector<int> src = {1, 2, 3, 4, 5};
    printVec("source             ", src);

    // (1) transform: square each element into a NEW vector via back_inserter.
    std::vector<int> squares;                        // empty — back_inserter grows it
    std::transform(src.begin(), src.end(), std::back_inserter(squares),
                   [](int x) { return x * x; });
    printVec("transform(*x) ->   ", squares);
    check("transform produced squares {1,4,9,16,25}",
          squares == std::vector<int>({1, 4, 9, 16, 25}));

    // (2) accumulate — SUM (default op = +).
    int sum = std::accumulate(src.begin(), src.end(), 0);   // 0+1+2+3+4+5 = 15
    std::printf("accumulate(+, init=0) = %d\n", sum);
    check("accumulate sum 1..5 == 15", sum == 15);

    // (3) accumulate — PRODUCT (custom binary op = *).
    int prod = std::accumulate(src.begin(), src.end(), 1,
                               [](int a, int b) { return a * b; });  // 120
    std::printf("accumulate(*, init=1) = %d   (5! = 120)\n", prod);
    check("accumulate product 1..5 == 120", prod == 120);

    // (4) accumulate folding into a STRING — join with commas.
    std::string joined = std::accumulate(
        src.begin(), src.end(), std::string(""),
        [](const std::string& acc, int x) {
            return acc.empty() ? std::to_string(x) : acc + "," + std::to_string(x);
        });
    std::printf("accumulate(string concat) = \"%s\"\n", joined.c_str());
    check("accumulate joined \"1,2,3,4,5\"", joined == "1,2,3,4,5");

    // (5) copy / copy_if — copy all, or only those matching a predicate.
    std::vector<int> all_copy;
    std::copy(src.begin(), src.end(), std::back_inserter(all_copy));
    printVec("copy (all) ->      ", all_copy);
    check("copy reproduced the source", all_copy == src);

    std::vector<int> evens;
    std::copy_if(src.begin(), src.end(), std::back_inserter(evens),
                 [](int x) { return x % 2 == 0; });   // 2,4
    printVec("copy_if(even) ->   ", evens);
    check("copy_if(even) produced {2,4}", evens == std::vector<int>({2, 4}));
}

// === Section C — erase-remove idiom + std::erase (C++20) + partition/unique ===
//
// THE classic C++ idiom: std::remove does NOT shrink the container — it
// reorders so the kept elements are at the front and returns the new logical
// end; you then ERASE the [new_end, old_end) tail. C++20 collapses the two-step
// dance into one free function: std::erase(v, x) / std::erase_if(v, pred).
//
// std::partition (NOT stable; stable_partition is) reorders so the
// predicate-true elements come first. std::unique collapses ADJACENT equal
// elements (so SORT first to dedup fully), returning the new end — pair with
// erase, same as remove. min/max/minmax_element return iterators.
void sectionC() {
    sectionBanner("C — erase-remove + std::erase (C++20) + partition/unique/minmax");

    // (1) THE erase-remove idiom (pre-C++20 two-step).
    std::vector<int> a = {1, 2, 3, 2, 4, 2, 5};
    printVec("(1) before erase-remove(value=2): ", a);
    a.erase(std::remove(a.begin(), a.end(), 2), a.end());
    printVec("    after  erase-remove(value=2): ", a);
    check("erase-remove removed ALL 2s -> {1,3,4,5}",
          a == std::vector<int>({1, 3, 4, 5}));

    // (2) C++20 std::erase / std::erase_if — one call, same effect.
    std::vector<int> b = {1, 2, 3, 2, 4, 2, 5};
    auto removed = std::erase(b, 2);                 // returns count erased
    std::printf("(2) std::erase(b, 2) removed %zu element(s) -> ", removed);
    printVec("", b);
    check("std::erase(b,2) removed all three 2s", removed == 3);
    check("std::erase left {1,3,4,5}", b == std::vector<int>({1, 3, 4, 5}));

    std::vector<int> c = {1, 2, 3, 4, 5, 6, 7, 8};
    auto rm_if = std::erase_if(c, [](int x) { return x % 2 != 0; });  // drop odds
    std::printf("    std::erase_if(c, odd) removed %zu -> ", rm_if);
    printVec("", c);
    check("std::erase_if(odd) kept only evens {2,4,6,8}",
          c == std::vector<int>({2, 4, 6, 8}) && rm_if == 4);

    // (3) partition — put evens first. std::partition is NOT stable; we use
    //     stable_partition here so the evens/odds each keep input order, making
    //     the result DETERMINISTIC (plain partition's intra-group order is
    //     unspecified). We still assert the partition PROPERTY for both.
    std::vector<int> p = {1, 2, 3, 4, 5, 6, 7, 8};
    auto part_pt = std::stable_partition(p.begin(), p.end(),
                                         [](int x) { return x % 2 == 0; });
    printVec("(3) stable_partition(even first): ", p);
    auto n_even = static_cast<std::size_t>(std::distance(p.begin(), part_pt));
    std::printf("    partition point: first %zu elements are even\n", n_even);
    check("is_partitioned(even-first) holds",
          std::is_partitioned(p.begin(), p.end(), [](int x) { return x % 2 == 0; }));
    check("stable_partition kept evens in input order: 2,4,6,8",
          p[0] == 2 && p[1] == 4 && p[2] == 6 && p[3] == 8);
    check("stable_partition kept odds  in input order: 1,3,5,7",
          p[4] == 1 && p[5] == 3 && p[6] == 5 && p[7] == 7);
    check("std::partition (non-stable) would NOT guarantee intra-group order",
          true);

    // (4) unique — collapse ADJACENT duplicates. SORT first so ALL dups become
    //     adjacent; then unique + erase to actually shrink.
    std::vector<int> u = {3, 1, 3, 2, 1, 3, 2, 1};
    std::sort(u.begin(), u.end());                   // {1,1,1,2,2,3,3,3}
    auto new_end = std::unique(u.begin(), u.end());  // collapse adjacents
    u.erase(new_end, u.end());                        // shrink for real
    printVec("(4) sort + unique + erase (dedup): ", u);
    check("unique dedup produced {1,2,3}", u == std::vector<int>({1, 2, 3}));

    // (5) min_element / max_element / minmax_element — return ITERATORS.
    std::vector<int> m = {7, 2, 9, 4, 1, 8, 3};
    printVec("(5) min/max source: ", m);
    auto mn = std::min_element(m.begin(), m.end());
    auto mx = std::max_element(m.begin(), m.end());
    auto mm = std::minmax_element(m.begin(), m.end());   // pair<min,max>
    std::printf("    min=%d  max=%d  (minmax: min=%d max=%d)\n",
                *mn, *mx, *mm.first, *mm.second);
    check("min_element == 1", *mn == 1);
    check("max_element == 9", *mx == 9);
    check("minmax_element matches min/max separately",
          *mm.first == 1 && *mm.second == 9);
}

// === Section D — C++20 ranges algorithms + PROJECTIONS =======================
//
// C++20 added std::ranges:: overloads: they take the WHOLE range (no begin/end
// pair) AND an optional PROJECTION — a callable applied to each element before
// the algorithm runs. A pointer-to-member like &Person::age IS a valid
// projection: ranges::sort(people, {}, &Person::age) sorts the people by age,
// where {} is the placeholder for the default comparator (std::ranges::less).
//
// This is the field-aware sorting/filtering that previously required a custom
// comparator lambda — projections make it a one-liner.
struct Person {
    std::string name;
    int age;
};

void sectionD() {
    sectionBanner("D — C++20 ranges algorithms + projections (sort by field)");

    std::vector<int> v = {5, 3, 8, 1, 9, 2, 7, 4, 6};
    printVec("(1) ranges source       ", v);

    // ranges::sort(v) — takes the WHOLE range, no begin/end pair.
    std::ranges::sort(v);
    printVec("    ranges::sort(v) ->   ", v);
    check("ranges::sort produced ascending order",
          std::is_sorted(v.begin(), v.end()));

    // ranges::find / ranges::count — same, but one-arg-range form.
    auto fit = std::ranges::find(v, 7);
    check("ranges::find(v,7) found 7", fit != v.end() && *fit == 7);
    auto cnt7 = std::ranges::count(v, 7);
    check("ranges::count(v,7) == 1", cnt7 == 1);

    // ranges::transform(v, out, op) — map into a back_inserter sink.
    std::vector<int> doubled;
    std::ranges::transform(v, std::back_inserter(doubled),
                           [](int x) { return x * 2; });
    printVec("    ranges::transform(*2)-> ", doubled);
    check("ranges::transform doubled each (front 2, back 18)",
          doubled.front() == 2 && doubled.back() == 18);

    // (2) PROJECTION — sort people by AGE via pointer-to-member &Person::age.
    //     The {} is the placeholder for the default comparator (ranges::less).
    std::vector<Person> people = {
        {"Ada", 36}, {"Linus", 54}, {"Grace", 85}, {"Alan", 41},
    };
    std::printf("(2) people before: ");
    for (const auto& p : people) std::printf("%s(%d) ", p.name.c_str(), p.age);
    std::printf("\n");

    std::ranges::sort(people, {}, &Person::age);   // {} = default comp; proj=age
    std::printf("    ranges::sort(people, {}, &Person::age) -> ");
    for (const auto& p : people) std::printf("%s(%d) ", p.name.c_str(), p.age);
    std::printf("\n");
    check("projection sorted people by age ascending: Ada36, Alan41, Linus54, Grace85",
          people[0].age == 36 && people[1].age == 41 &&
              people[2].age == 54 && people[3].age == 85);

    // (3) Projection WITH an explicit comparator: sort by age DESCENDING.
    std::ranges::sort(people, std::ranges::greater{}, &Person::age);
    std::printf("    ranges::sort(people, greater, &Person::age) -> ");
    for (const auto& p : people) std::printf("%s(%d) ", p.name.c_str(), p.age);
    std::printf("\n");
    check("projection+greater sorted by age DESCENDING: Grace85..Ada36",
          people[0].age == 85 && people[3].age == 36);

    // (4) Projection with find/count — find the person aged 54 via the age proj.
    auto p54 = std::ranges::find(people, 54, &Person::age);
    check("ranges::find(people, 54, &Person::age) found Linus(54)",
          p54 != people.end() && p54->name == "Linus" && p54->age == 54);
}

// === Section E — Genericity over iterators + execution policies (note) =======
//
// THE defining property of <algorithm>: every algorithm is parameterized by
// ITERATOR, not container. The SAME std::sort compiles and runs over a
// std::vector, a std::array, AND a raw C-array (via pointers) — anything whose
// iterators meet the category (here: random-access). This is why <algorithm>
// "just works" on any sequence you can give it begin/end for.
//
// (Execution policies — std::execution::par / par_unseq, C++17 — are noted but
// NOT exercised: parallel algorithms require linking a backend (Intel TBB on
// most toolchains; Apple clang support is partial), which breaks the
// stdlib-first single-TU discipline. The sequential overload is what every
// prior section used.)
void sectionE() {
    sectionBanner("E — Generic over iterators + execution-policy note");

    // (1) std::sort over THREE different range kinds — same template, same call.
    std::vector<int> vv = {3, 1, 4, 1, 5, 9, 2, 6};
    std::array<int, 8>  aa = {3, 1, 4, 1, 5, 9, 2, 6};
    int                 cc[8] = {3, 1, 4, 1, 5, 9, 2, 6};

    std::sort(vv.begin(), vv.end());
    std::sort(aa.begin(), aa.end());
    std::sort(cc, cc + 8);    // raw pointers are iterators too

    printVec("(1) sort over vector -> ", vv);
    std::printf("    sort over array   -> {");
    for (std::size_t i = 0; i < aa.size(); ++i)
        std::printf("%d%s", aa[i], (i + 1 == aa.size()) ? "" : ", ");
    std::printf("}\n");
    std::printf("    sort over C-array -> {");
    for (int i = 0; i < 8; ++i) std::printf("%d%s", cc[i], (i == 7) ? "" : ", ");
    std::printf("}\n");

    check("std::sort worked over std::vector", std::is_sorted(vv.begin(), vv.end()));
    check("std::sort worked over std::array",  std::is_sorted(aa.begin(), aa.end()));
    check("std::sort worked over raw C-array (via pointers)",
          std::is_sorted(cc, cc + 8));

    // (2) accumulate over a std::array — same generic template.
    int arr_sum = std::accumulate(aa.begin(), aa.end(), 0);  // 1+1+2+3+4+5+6+9 = 31
    std::printf("(2) accumulate over the std::array -> %d\n", arr_sum);
    check("accumulate over std::array == 31", arr_sum == 31);

    // (3) Execution-policy NOTE (printed, not run — par/par_unseq need linking).
    std::printf("(3) Execution policies (C++17): std::execution::seq / par /\n");
    std::printf("    par_unseq parallelize algorithms, but require linking a\n");
    std::printf("    backend (TBB on most toolchains) — NOT exercised here.\n");
    std::printf("    Every prior section used the sequential overload.\n");
    check("execution-policy note printed (par/par_unseq not run; need linking)",
          true);

    // (4) Cross-language contrast (printed):
    std::printf("(4) Cross-language: <algorithm> is GENERIC OVER ITERATORS —\n");
    std::printf("    the same sort/transform/accumulate works on any range whose\n");
    std::printf("    iterators meet the category. Contrast:\n");
    std::printf("      Rust Iterator methods (.map/.filter/.fold) — methods ON the\n");
    std::printf("        trait, generic over the iterator type (compile-time).\n");
    std::printf("      TS array methods (.map/.filter/.reduce) — ARRAY-only, under GC.\n");
    std::printf("      Go — NO <algorithm>; you write the for-loop yourself.\n");
    check("cross-language contrast printed (Rust/TS methods, Go no-lib)", true);
}

}  // namespace

int main() {
    std::printf("algorithms.cpp — Phase 5 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
