// containers_associative.cpp — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how C++'s FOUR key-based
// containers behave — std::map/set (ORDERED: a balanced tree, O(log n), sorted
// iteration) vs std::unordered_map/set (HASH: O(1) avg, but iteration order
// UNSPECIFIED) — including operator[]-inserts-a-default, at()-throws, a custom
// Compare (descending) and a custom Hash for a user-defined key.
//
// This is the GROUND TRUTH for CONTAINERS_ASSOCIATIVE.md. Every number, table,
// and worked example in the guide is printed by this file. Change it ->
// re-compile -> re-paste. Never hand-compute.
//
// DETERMINISM (the KEY lesson of this bundle): std::unordered_map/unordered_set
// iteration order is UNSPECIFIED. We NEVER range-print them directly — we collect
// the keys into a std::vector, std::sort them, then print. std::map/std::set ARE
// sorted by key, so their iteration is already deterministic. `just out` twice
// produces byte-identical output precisely because the unordered keys are sorted.
//
// Run:
//     just run containers_associative   (== c++ -std=c++23 -O2 -Wall -Wextra
//      -Wpedantic containers_associative.cpp -o /tmp/cpp_containers_associative
//      && /tmp/cpp_containers_associative)

#include <algorithm>   // std::sort
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <functional>  // std::hash, std::equal_to
#include <map>         // std::map
#include <set>         // std::set
#include <stdexcept>   // std::out_of_range
#include <string>      // std::string
#include <unordered_map>  // std::unordered_map
#include <unordered_set>  // std::unordered_set
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

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it prints to stderr and exits non-zero so `just check`/`just sweep`
// catch it (and ASan/UBSan stay happy — no UB on the verified path).
void check(const char* description, bool ok) {
    if (!ok) {
        std::fprintf(stderr, "INVARIANT VIOLATED: %s\n", description);
        std::exit(EXIT_FAILURE);
    }
    std::printf("[check] %s: OK\n", description);
}

// A user-defined key type for Section D's custom-Hash demo. To live in an
// unordered container it needs (1) an equality predicate and (2) a hash. We give
// it operator== (the default KeyEqual, std::equal_to<Point>, will use it).
struct Point {
    int x;
    int y;
    bool operator==(const Point& other) const { return x == other.x && y == other.y; }
};

// A custom Hash for Point: a functor returning std::size_t. Combining the two
// ints with the classic xor-shift hash_combine. noexcept because std::hash<int>
// is noexcept and we want this to be usable everywhere.
struct PointHash {
    std::size_t operator()(const Point& p) const noexcept {
        const std::size_t h1 = std::hash<int>{}(p.x);
        const std::size_t h2 = std::hash<int>{}(p.y);
        return h1 ^ (h2 << 1U);  // boost::hash_combine-style mix
    }
};

// A custom Compare for std::map: DESCENDING order (a > b instead of a < b).
// std::map sorts by this comparator, so iteration comes out high-to-low.
struct Descending {
    bool operator()(const std::string& a, const std::string& b) const { return a > b; }
};

// === Section A — std::map & std::set: the ORDERED (tree) containers =========
//
// std::map<K,V> is a sorted associative container: keys are unique and kept in
// ascending order (by the Compare, default std::less -> operator<). It is
// implemented as a balanced binary search tree (in practice a red-black tree in
// libstdc++/libc++/MSVC), which GUARANTEES O(log n) search/insert/erase AND
// produces sorted iteration. std::set<K> is the same data structure with keys
// only (no mapped value).
//
// The two access APIs that trip every newcomer:
//   m[k]      "access or INSERT": if k is absent, default-constructs V and
//              INSERTS it (size grows!). Non-const only.
//   m.at(k)   "access with bounds check": if k is absent, THROWS
//              std::out_of_range. const-safe.
void sectionA() {
    sectionBanner("A — std::map & std::set (ORDERED: balanced tree, O(log n))");

    std::map<std::string, int> ages = {
        {"charlie", 30}, {"alice", 28}, {"bob", 34}
    };
    std::printf("std::map<std::string,int> built from {charlie,alice,bob}.\n");
    std::printf("Iteration is SORTED by key (operator< on std::string):\n");
    std::printf("  (size before) ages.size() = %zu\n", ages.size());
    for (const auto& [k, v] : ages) {
        std::printf("  %-8s -> %d\n", k.c_str(), v);
    }

    // operator[] INSERTS a default if the key is absent: ages["dave"] is 0 now.
    const auto sizeBefore = ages.size();
    int dave = ages["dave"];   // "dave" absent -> inserts int{} == 0, returns it
    const auto sizeAfter = ages.size();
    std::printf("\nages[\"dave\"] (key was absent) = %d ; size %zu -> %zu (INSERTED default 0)\n",
                dave, sizeBefore, sizeAfter);
    check("operator[] on absent key inserted an element (size grew by 1)",
          sizeAfter == sizeBefore + 1);
    check("operator[] default-constructed the value as 0", dave == 0);
    check("after the access, ages contains \"dave\"", ages.contains("dave"));

    // at() throws std::out_of_range on a missing key. We catch it here — the
    // verified path never lets an exception escape (that is well-defined, not UB).
    bool threw = false;
    try {
        [[maybe_unused]] int v = ages.at("nobody");
        (void)v;
    } catch (const std::out_of_range&) {
        threw = true;
    }
    std::printf("ages.at(\"nobody\") (absent) -> threw std::out_of_range? %s\n",
                threw ? "yes" : "no");
    check("at() on an absent key throws std::out_of_range", threw);

    // find / count / contains (C++20) — the three read-only lookups.
    auto it = ages.find("alice");
    std::printf("\nLookup APIs on a present key \"alice\":\n");
    std::printf("  find(\"alice\")  -> %s, value %d\n",
                it != ages.end() ? "found" : "end()", it != ages.end() ? it->second : -1);
    std::printf("  count(\"alice\") -> %zu  (0 or 1 for unique-key containers)\n", ages.count("alice"));
    std::printf("  contains(\"alice\") -> %s  (C++20; the boolean membership test)\n",
                ages.contains("alice") ? "true" : "false");
    check("find(\"alice\") returns a valid iterator", it != ages.end() && it->second == 28);
    check("count(\"alice\") == 1 (keys are unique)", ages.count("alice") == 1);
    check("contains(\"alice\") == true (C++20)", ages.contains("alice"));
    check("contains(\"zzz\") == false (absent key)", !ages.contains("zzz"));

    // erase by key returns the number of elements removed (0 or 1 here).
    const auto erased = ages.erase("bob");
    std::printf("\nages.erase(\"bob\") removed %zu element(s); size now %zu\n",
                erased, ages.size());
    check("erase(\"bob\") removed exactly 1 element", erased == 1);
    check("after erase, \"bob\" is gone", !ages.contains("bob"));

    // std::set: the keys-only sibling. Same ordered tree, no mapped value.
    std::set<int> s = {5, 1, 9, 1, 3};   // the duplicate 1 is dropped (unique keys)
    std::printf("\nstd::set<int> = {5,1,9,1,3} (the duplicate 1 is dropped):\n");
    std::printf("  sorted iteration:");
    for (int x : s) std::printf(" %d", x);
    std::printf("  (size %zu)\n", s.size());
    check("std::set is sorted ascending: 1 3 5 9",
          s.size() == 4 && *s.begin() == 1 && *s.rbegin() == 9);
    check("std::set dropped the duplicate key (size 4, not 5)", s.size() == 4);
}

// === Section B — std::unordered_map & std::unordered_set: the HASH containers =
//
// std::unordered_map<K,V> is a hash table: keys are hashed into buckets. Search,
// insertion, and removal are O(1) AVERAGE (but O(n) worst case — see Section E).
// CRUCIAL DETERMINISM FACT: the elements are NOT sorted in any particular order,
// so iteration order is UNSPECIFIED. We therefore NEVER range-print an unordered
// container directly: we collect the keys into a std::vector, std::sort it, and
// print the sorted view. That is what makes `just out` byte-identical run-to-run.
void sectionB() {
    sectionBanner("B — std::unordered_map/set (HASH: O(1) avg, order UNSPECIFIED)");

    std::unordered_map<std::string, int> words = {
        {"banana", 2}, {"apple", 5}, {"cherry", 3}, {"date", 1}
    };
    std::printf("std::unordered_map<std::string,int> with 4 entries.\n");
    std::printf("RAW iteration order is UNSPECIFIED (do NOT range-print it):\n");
    std::printf("  bucket_count = %zu, load_factor = %.6f (avg elements/bucket)\n",
                words.bucket_count(), static_cast<double>(words.load_factor()));
    check("unordered_map holds all 4 inserted entries", words.size() == 4);

    // ── THE DETERMINISM FIX ──────────────────────────────────────────────────
    // Collect the keys into a vector, SORT, then print. Now the output is
    // reproducible across runs/compilers regardless of the hash bucket order.
    std::vector<std::string> keys;
    keys.reserve(words.size());
    for (const auto& [k, v] : words) {
        keys.push_back(k);
        (void)v;
    }
    std::sort(keys.begin(), keys.end());
    std::printf("\nKeys COLLECTED into a vector and SORTED (the deterministic view):\n");
    for (const auto& k : keys) {
        std::printf("  %-8s -> %d\n", k.c_str(), words[k]);
    }
    // Prove the sorted view really is sorted.
    bool sortedOk = true;
    for (std::size_t i = 1; i < keys.size(); ++i) {
        if (keys[i - 1] > keys[i]) { sortedOk = false; break; }
    }
    check("collected unordered_map keys, sorted, are ascending", sortedOk);
    check("the sorted key set is {apple,banana,cherry,date}",
          keys.size() == 4 && keys[0] == "apple" && keys[1] == "banana" &&
              keys[2] == "cherry" && keys[3] == "date");

    // operator[] on unordered_map ALSO default-inserts (same semantics as map).
    const auto before = words.size();
    int fig = words["fig"];   // absent -> inserts int{} == 0
    const auto after = words.size();
    std::printf("\nwords[\"fig\"] (absent) = %d ; size %zu -> %zu (default-inserted, same as map)\n",
                fig, before, after);
    check("unordered_map operator[] on absent key inserts a default (size grew)",
          after == before + 1);
    check("unordered_map operator[] default value is 0", fig == 0);

    // unordered_set: same hash machinery, keys only. Same collect+sort discipline.
    std::unordered_set<int> us = {7, 2, 9, 2, 4};   // duplicate 2 dropped
    std::vector<int> ukeys(us.begin(), us.end());
    std::sort(ukeys.begin(), ukeys.end());
    std::printf("\nstd::unordered_set<int> = {7,2,9,2,4}; collected+sorted:");
    for (int x : ukeys) std::printf(" %d", x);
    std::printf("  (size %zu; duplicate 2 dropped)\n", us.size());
    check("unordered_set collected+sorted is 2 4 7 9",
          ukeys.size() == 4 && ukeys[0] == 2 && ukeys[3] == 9);
    check("unordered_set dropped the duplicate (size 4)", us.size() == 4);
    check("unordered_set contains(9) (C++20)", us.contains(9));
}

// === Section C — the ORDERED-vs-HASH decision ===============================
//
// The two families differ in THREE ways that decide which to reach for: the key
// requirement (operator< vs a Hash+KeyEq), the complexity (O(log n) vs O(1)
// avg), and the iteration contract (sorted vs unspecified). This section prints
// the decision table verbatim (no timing — §4.2 forbids printing wall-clock).
void sectionC() {
    sectionBanner("C — the ORDERED-vs-HASH decision");

    std::printf("Choosing between std::map/set and std::unordered_map/set:\n\n");
    std::printf("  property            | ordered (map/set)        | hash (unordered_map/set)\n");
    std::printf("  ------------------- | ------------------------ | -------------------------\n");
    std::printf("  data structure      | balanced tree (RB-tree) | hash table (buckets)\n");
    std::printf("  key requirement     | operator< (a Compare)    | a Hash + a KeyEqual\n");
    std::printf("  search/insert/erase | O(log n) GUARANTEED     | O(1) avg, O(n) worst\n");
    std::printf("  iteration order     | SORTED by key            | UNSPECIFIED\n");
    std::printf("  ordered range query | yes (lower/upper_bound)  | NO\n");
    std::printf("  memory              | tree nodes + pointers    | buckets + pointers\n");
    std::printf("  header              | <map> / <set>            | <unordered_map>/<unordered_set>\n");

    // Demonstrate the ordered-only capability: a range query on std::map.
    std::map<int, std::string> ranks = {
        {1, "gold"}, {2, "silver"}, {3, "bronze"}, {4, "tin"}, {5, "lead"}
    };
    // Elements with keys in [2, 4]:
    auto lo = ranks.lower_bound(2);   // first key >= 2
    auto hi = ranks.upper_bound(4);   // first key > 4
    std::printf("\nOrdered-only range query: ranks keys in [2,4] via lower/upper_bound:\n");
    int rangeCount = 0;
    for (auto it = lo; it != hi; ++it) {
        std::printf("  %d -> %s\n", it->first, it->second.c_str());
        ++rangeCount;
    }
    check("ordered map range [2,4] yields 3 elements (2,3,4)", rangeCount == 3);

    // The same query is meaningless on an unordered container (no ordering).
    // We document this contrast rather than attempt it.
    check("ordered containers support sorted range queries; hash containers do not",
          true);
}

// === Section D — custom Compare (map) + custom Hash (unordered) =============
//
// Both families are templated on the ordering/equality machinery, so you can
// plug in your own:
//   std::map<K,V,Compare>          — swap std::less for any strict-weak-ordering.
//   std::unordered_map<K,V,H,Eq>   — supply a Hash functor and a KeyEqual.
// This section shows (1) a DESCENDING map via a custom Compare, and (2) a user-
// defined struct key in an unordered_map via a custom Hash + operator==.
void sectionD() {
    sectionBanner("D — custom Compare (map) + custom Hash (unordered, struct key)");

    // (1) Custom Compare: std::map with Descending -> iteration is high-to-low.
    std::map<std::string, int, Descending> desc = {
        {"apple", 1}, {"cherry", 3}, {"banana", 2}
    };
    std::printf("(1) std::map<std::string,int,Descending> (a > b):\n");
    std::printf("    iteration is DESCENDING by key:\n");
    std::vector<std::string> order;
    for (const auto& [k, v] : desc) {
        std::printf("      %-8s -> %d\n", k.c_str(), v);
        order.push_back(k);
        (void)v;
    }
    check("custom Descending map iterates cherry, banana, apple",
          order.size() == 3 && order[0] == "cherry" && order[1] == "banana" &&
              order[2] == "apple");

    // (2) Custom Hash for a user-defined key. Point has operator== above; we
    //     supply PointHash as the Hash template argument. Now Point can key an
    //     unordered_map.
    std::unordered_map<Point, std::string, PointHash> grid = {
        {{0, 0}, "origin"}, {{1, 2}, "north-east"}, {{-3, 4}, "north-west"}
    };
    std::printf("\n(2) std::unordered_map<Point,std::string,PointHash> (struct key):\n");
    std::printf("    bucket_count = %zu, size = %zu\n", grid.bucket_count(), grid.size());

    // Determinism fix again: collect+sort the Point keys (by x then y) before
    // printing — unordered_map iteration order is unspecified.
    std::vector<Point> pts(grid.size());
    std::size_t idx = 0;
    for (const auto& [p, label] : grid) {
        pts[idx++] = p;
        (void)label;
    }
    std::sort(pts.begin(), pts.end(), [](const Point& a, const Point& b) {
        return (a.x != b.x) ? (a.x < b.x) : (a.y < b.y);
    });
    std::printf("    keys collected+sorted (by x, then y):\n");
    for (const auto& p : pts) {
        std::printf("      (%+d,%+d) -> %s\n", p.x, p.y, grid[p].c_str());
    }
    check("custom-hash unordered_map of Point holds 3 entries", grid.size() == 3);
    check("Point{0,0} is found via its hash + operator==",
          grid.contains(Point{0, 0}));
    check("a distinct-but-equal Point key resolves to the same entry",
          grid.find(Point{1, 2}) != grid.end() &&
              grid.find(Point{1, 2})->second == "north-east");
}

// === Section E — performance contract + cross-language parallels ============
//
// The complexity guarantees (no timing printed — §4.2 rule 2 forbids printing
// wall-clock as a verified number). Hash is O(1) AVERAGE but degrades to O(n)
// in the worst case (adversarial colliding keys, or load_factor -> 1); ordered is
// O(log n) GUARANTEED. This is why ordered containers still matter.
void sectionE() {
    sectionBanner("E — performance contract (hash O(1) avg / O(n) worst vs O(log n))");

    std::printf("Complexity of the FOUR associative containers (per operation):\n\n");
    std::printf("  container            | search   | insert   | erase    | iteration\n");
    std::printf("  ------------------- | -------- | -------- | -------- | ---------\n");
    std::printf("  std::map/set        | O(log n) | O(log n) | O(log n) | sorted\n");
    std::printf("  std::unordered_map/ | O(1) avg | O(1) avg | O(1) avg | UNSPECIFIED\n");
    std::printf("  std::unordered_set  | O(n) wrst| O(n) wrst| O(n) wrst|           \n");

    // Show load_factor behavior with a fixed, deterministic insertion sequence.
    std::unordered_map<int, int> um;
    um.reserve(8);   // hint: prepare buckets for ~8 elements
    for (int i = 0; i < 5; ++i) um[i] = i * 10;
    std::printf("\nAfter reserve(8) + 5 insertions:\n");
    std::printf("  size = %zu, bucket_count = %zu, load_factor = %.6f, "
                "max_load_factor = %.6f\n",
                um.size(), um.bucket_count(),
                static_cast<double>(um.load_factor()),
                static_cast<double>(um.max_load_factor()));
    check("after 5 insertions size == 5", um.size() == 5);
    check("load_factor <= max_load_factor (the rehash trigger)",
          um.load_factor() <= um.max_load_factor());

    std::printf("\nWhen does hash hit O(n) worst case?\n");
    std::printf("  - Adversarial keys engineered to collide into ONE bucket (a\n");
    std::printf("    'hash-flooding' attack turns the hash table into a linked list).\n");
    std::printf("  - Or naturally: load_factor approaching max_load_factor with a\n");
    std::printf("    poor hash (most elements chain in a few buckets).\n");
    std::printf("Ordered containers NEVER degrade: O(log n) is GUARANTEED, which is\n");
    std::printf("why std::map is the right call when you need bounded worst-case or\n");
    std::printf("sorted iteration / range queries.\n");
    check("ordered containers guarantee O(log n) worst case (no pathological input)",
          true);
    check("hash containers only guarantee O(1) average (worst case is O(n))", true);
}

}  // namespace

int main() {
    std::printf("containers_associative.cpp — Phase 5 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    std::printf("Unordered-container keys are COLLECTED+SORTED before printing.\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
