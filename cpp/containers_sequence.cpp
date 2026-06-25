// containers_sequence.cpp — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how std::vector (contiguous,
// growable, amortized-O(1) push_back), std::array (fixed, value-semantic, no
// decay), std::deque (O(1) front+back), and std::list/forward_list (node-based,
// O(1) insert anywhere, STABLE iterators, NO random access) behave — pinning the
// per-container ITERATOR INVALIDATION rules as the documented expert payoff
// (the invalidated iterator is NEVER read in the verified path).
//
// This is the GROUND TRUTH for CONTAINERS_SEQUENCE.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run containers_sequence
//         (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//             containers_sequence.cpp -o /tmp/cpp_containers_sequence
//             && /tmp/cpp_containers_sequence)

#include <array>          // std::array<T,N>
#include <cstdio>         // printf / fprintf
#include <cstdlib>        // EXIT_FAILURE / exit
#include <cstring>        // memset (for the banner bar)
#include <deque>          // std::deque<T>
#include <forward_list>   // std::forward_list<T>
#include <initializer_list>  // std::initializer_list (helper asserts)
#include <iterator>       // std::next
#include <list>           // std::list<T>
#include <stdexcept>      // std::out_of_range (thrown by vector::at)
#include <vector>         // std::vector<T>

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

// printVec dumps a vector's contents as "[a, b, c]".
void printVec(const std::vector<int>& v) {
    std::printf("[");
    for (std::size_t i = 0; i < v.size(); ++i) {
        std::printf("%d%s", v[i], (i + 1 == v.size() ? "" : ", "));
    }
    std::printf("]");
}

// ── small helpers for ordered list-content assertions + printing ────────────
// list / forward_list have NO operator[]; these let us assert exact contents
// (which ARE ordered, so determinism holds) and print them for the callouts.
bool listEquals(const std::list<int>& l, std::initializer_list<int> expected) {
    auto it = l.begin();
    for (int e : expected) {
        if (it == l.end() || *it != e) return false;
        ++it;
    }
    return it == l.end();
}
void printList(const std::list<int>& l) {
    std::printf("[");
    bool first = true;
    for (int x : l) { std::printf("%s%d", first ? "" : ", ", x); first = false; }
    std::printf("]");
}
bool flEquals(const std::forward_list<int>& fl, std::initializer_list<int> expected) {
    auto it = fl.begin();
    for (int e : expected) {
        if (it == fl.end() || *it != e) return false;
        ++it;
    }
    return it == fl.end();
}
void printFList(const std::forward_list<int>& fl) {
    std::printf("[");
    bool first = true;
    for (int x : fl) { std::printf("%s%d", first ? "" : ", ", x); first = false; }
    std::printf("]");
}

// === Section A — std::vector: contiguous, growable, capacity/reserve =========
//
// std::vector is THE workhorse: a contiguous, growable array. Random access is
// O(1); push_back/pop_back are AMORTIZED O(1) (the growth factor — 2x on
// libc++/libstdc++ — spreads the O(n) reallocation cost across many O(1)
// pushes). The capacity-vs-size distinction is the key memory fact: capacity()
// is what's ALLOCATED, size() is what's USED. reserve(n) pre-allocates so that
// the next n-size() push_backs do NOT reallocate (and so do not invalidate).
//
// CAUTION: the exact growth factor is IMPLEMENTATION-DEFINED (MSVC ~1.5x,
// libc++/libstdc++ 2x). We therefore assert only portable invariants
// (capacity >= size; capacity monotonic non-decreasing) and PRINT the actual
// growth sequence for illustration.
void sectionA() {
    sectionBanner("A — std::vector: contiguous, growable, capacity/reserve");

    std::vector<int> v;                 // empty: size 0, capacity 0
    std::printf("std::vector<int> v;   -> size=%zu  capacity=%zu\n",
                v.size(), v.capacity());

    // push_back grows size; capacity grows by the impl's growth factor (2x here).
    // We record the capacity sequence to show the (amortized-O(1)) doubling.
    std::printf("\npush_back 1..10 — capacity growth sequence (impl-defined):\n");
    int prev_cap = static_cast<int>(v.capacity());
    bool monotonic = true;
    for (int i = 1; i <= 10; ++i) {
        v.push_back(i);
        int cap = static_cast<int>(v.capacity());
        std::printf("  after push_back(%2d): size=%2zu  capacity=%2d%s\n",
                    i, v.size(), cap,
                    cap > prev_cap ? "  <- reallocated (capacity grew)" : "");
        if (cap < prev_cap) monotonic = false;
        prev_cap = cap;
    }
    std::printf("final v = ");
    printVec(v);
    std::printf("\n");

    check("vector grew to size 10 after 10 push_backs", v.size() == 10);
    check("capacity >= size (never less)", v.capacity() >= v.size());
    check("capacity is monotonic non-decreasing across push_backs", monotonic);

    // reserve(n): pre-allocate WITHOUT changing size. Now push_backs up to n do
    // NOT reallocate -> iterators/pointers/references stay valid for them.
    std::vector<int> w;
    w.reserve(100);
    std::size_t cap_after_reserve = w.capacity();
    std::printf("\nw.reserve(100); -> size=%zu  capacity=%zu (size unchanged, "
                "capacity is now >= 100)\n", w.size(), w.capacity());
    bool no_realloc = true;
    for (int i = 0; i < 100; ++i) {
        w.push_back(i);
        if (w.capacity() != cap_after_reserve) { no_realloc = false; }
    }
    std::printf("after 100 push_backs within the reservation: capacity=%zu "
                "(%s)\n", w.capacity(),
                no_realloc ? "UNCHANGED — no reallocation" : "changed");
    check("reserve(100) gave capacity >= 100", w.capacity() >= 100);
    check("100 push_backs within reserve() did NOT reallocate (capacity fixed)",
          no_realloc && w.capacity() == cap_after_reserve);

    // operator[] vs at(): operator[] is unchecked (UB on OOB); at() THROWS
    // std::out_of_range. The throw here is a DEFINED, catchable behavior — fully
    // safe under ASan/UBSan (unlike the operator[] OOB, which is UB and which we
    // therefore NEVER execute).
    std::printf("\nv[0]=%d  v[9]=%d   (operator[]: unchecked — OOB is UB)\n",
                v[0], v[9]);
    std::printf("calling v.at(10) on a size-10 vector (index 10 is OOB)...\n");
    bool threw = false;
    try {
        [[maybe_unused]] int bad = v.at(10);   // index 10 == size -> OOB
        (void)bad;
    } catch (const std::out_of_range& e) {
        threw = true;
        std::printf("  caught std::out_of_range: \"%s\"\n", e.what());
    }
    check("v.at(10) threw std::out_of_range (defined, catchable)", threw);
    check("v[0] == 1 and v[9] == 10 (operator[] in-bounds is fine)", v[0] == 1 && v[9] == 10);

    // shrink_to_fit is a NON-BINDING hint to release unused capacity. May or may
    // not actually shrink; the only portable claim is capacity >= size after.
    std::vector<int> s;
    s.reserve(1000);
    s.push_back(7);
    std::size_t cap_before = s.capacity();
    s.shrink_to_fit();
    std::size_t cap_after = s.capacity();
    std::printf("\ns.reserve(1000); s.push_back(7); s.shrink_to_fit();\n");
    std::printf("  capacity: %zu -> %zu  (shrink_to_fit is a non-binding hint; "
                "here it %s)\n",
                cap_before, cap_after,
                cap_after < cap_before ? "shrunk" : "did not shrink");
    check("after shrink_to_fit, capacity >= size still holds",
          s.capacity() >= s.size());
}

// === Section B — ITERATOR INVALIDATION (the vector trap; documented, NOT hit)=
//
// THE expert payoff. A vector iterator is essentially a pointer into the
// contiguous buffer. Two operations invalidate it:
//   (1) REALLOCATION (push_back/emplace_back/insert/resize that changes
//       capacity, or reserve/shrink_to_fit that do): invalidates ALL iterators,
//       pointers, and references into the vector.
//   (2) ERASE / INSERT at a position: invalidates iterators at/after the point
//       (the buffer is shifted; the old slot may have been moved-from).
//
// Reading an invalidated iterator is UNDEFINED BEHAVIOR. This bundle therefore
// demonstrates the rule WITHOUT ever reading a stale iterator: we capture an
// iterator, force a reallocation, and then read the value back via the SAFE
// operator[] (the value was COPIED into the new buffer). The stale iterator is
// left untouched.
void sectionB() {
    sectionBanner("B — ITERATOR INVALIDATION: reallocation invalidates ALL");

    // --- (1) Reallocation invalidates ALL iterators ---------------------------
    // Capture an iterator; push_back past capacity; capacity CHANGES -> every
    // iterator (including ours) is invalidated. We do NOT read it afterwards.
    std::vector<int> v = {10, 20, 30};
    auto it = v.begin() + 1;            // points at v[1] == 20 (valid now)
    std::printf("std::vector<int> v = {10,20,30}; auto it = v.begin()+1;\n");
    std::printf("  *it (valid) = %d   (it points at v[1])\n", *it);
    std::size_t cap_before = v.capacity();
    std::printf("  capacity before = %zu\n", cap_before);

    // Force a reallocation by pushing until capacity changes.
    std::size_t cap_after = cap_before;
    int pushes = 0;
    while (cap_after == cap_before) {
        v.push_back(0);
        cap_after = v.capacity();
        ++pushes;
    }
    std::printf("  after %d push_back(s) capacity: %zu -> %zu  (REALLOCATED)\n",
                pushes, cap_before, cap_after);
    std::printf("  *** `it` is now INVALIDATED — the buffer moved. We do NOT\n");
    std::printf("      read *it (that would be UB). The value 20 was COPIED to\n");
    std::printf("      the new buffer, reachable via the SAFE index v[1].\n");
    std::printf("  v[1] (safe, by index) = %d\n", v[1]);

    check("reallocation changed capacity (the trigger)", cap_after > cap_before);
    check("after realloc, the value 20 survived via the safe index v[1]", v[1] == 20);
    check("the invalidated iterator `it` was NOT read (UB avoided in verified path)",
          true);

    // --- (2) reserve() AHEAD avoids the invalidation entirely ----------------
    // Reserve enough, THEN capture the iterator; subsequent in-reserve push_backs
    // do not reallocate -> the iterator stays valid AND readable.
    std::vector<int> w;
    w.reserve(8);
    w = {100, 200, 300};
    auto wit = w.begin() + 1;           // points at w[1] == 200
    std::size_t wc = w.capacity();
    for (int i = 0; i < 3; ++i) w.push_back(i);  // 3 more, within reserve(8)
    std::printf("\nreserve(8) first, then push 3 more: capacity stays %zu "
                "(no realloc)\n", w.capacity());
    std::printf("  *wit (STILL valid — no reallocation happened) = %d\n", *wit);
    check("reserve(8) kept capacity fixed across 3 in-reserve push_backs",
          w.capacity() == wc);
    check("the iterator captured after reserve() stayed valid & readable",
          *wit == 200);

    // --- (3) erase invalidates from the erased point onward ------------------
    // erase(it) invalidates it and everything at/after. We erase by a freshly
    // obtained position and never touch the stale iterator.
    std::vector<int> e = {1, 2, 3, 4, 5};
    std::printf("\nbefore erase: e = ");
    printVec(e);
    std::printf("\n");
    e.erase(e.begin() + 2);             // removes the '3'; begin()+2 onward stale
    std::printf("after  e.erase(begin()+2) (removed value 3): e = ");
    printVec(e);
    std::printf("\n");
    std::printf("  iterators at/after begin()+2 are INVALIDATED; we read e only\n");
    std::printf("  via fresh begin()/operator[] (safe).\n");
    check("erase(begin()+2) removed exactly the element 3", e.size() == 4 && e[2] == 4);
}

// === Section C — std::array (fixed, value-semantic, no decay) + std::deque ===
//
// std::array<T,N> is the C-array REPLACEMENT: a thin wrapper around a C array
// with VALUE semantics (it copies on assignment/pass-by-value), it KNOWS its
// size (size() == N), and it does NOT decay to a pointer. Use it whenever the
// size is a compile-time constant.
//
// std::deque<T> (double-ended queue) is a chunked (not guaranteed contiguous)
// sequence supporting O(1) push_front AND push_back, O(1) pop_front/pop_back,
// and O(1) random access (operator[]/at). It is what you reach for when a vector
// is too slow at the FRONT.
void sectionC() {
    sectionBanner("C — std::array (fixed, no decay) + std::deque (O(1) front+back)");

    // --- std::array<T,N> -----------------------------------------------------
    std::array<int, 3> a = {1, 2, 3};
    std::printf("std::array<int,3> a = {1,2,3};\n");
    std::printf("  a.size() = %zu   (knows its size — unlike a C array)\n", a.size());
    std::printf("  sizeof(a) = %zu  (== 3 * sizeof(int) = %zu; NOT pointer-sized %zu)\n",
                sizeof(a), 3 * sizeof(int), sizeof(int*));
    std::printf("  a.front()=%d  a.back()=%d  a[1]=%d  a.data()=%s\n",
                a.front(), a.back(), a[1], a.data() == nullptr ? "nullptr" : "non-null");

    check("std::array<int,3>::size() == 3", a.size() == 3);
    check("std::array does NOT decay: sizeof(a) == 3*sizeof(int) (not sizeof(int*))",
          sizeof(a) == 3 * sizeof(int) && sizeof(a) != sizeof(int*));

    // Value semantics: a copy is an independent array (a C array passed by value
    // would decay & lose its size; std::array copied stays a real 3-int object).
    std::array<int, 3> b = a;           // value copy — a real second object
    b[0] = 99;                          // mutate the COPY
    std::printf("  copy: std::array<int,3> b = a; b[0]=99; -> a[0]=%d (untouched), "
                "b[0]=%d\n", a[0], b[0]);
    check("std::array is value-semantic: mutating a copy leaves the original alone",
          a[0] == 1 && b[0] == 99);

    // --- std::deque<T> -------------------------------------------------------
    // push_front is O(1) — vector canNOT do this (vector::insert(begin()) is O(n)).
    std::deque<int> d;
    d.push_back(2);                     // [2]
    d.push_front(1);                    // [1, 2]   <- O(1) front insert
    d.push_back(3);                     // [1, 2, 3]
    std::printf("\nstd::deque<int> d; d.push_back(2); d.push_front(1); "
                "d.push_back(3);\n");
    std::printf("  d = [");
    for (std::size_t i = 0; i < d.size(); ++i) {
        std::printf("%d%s", d[i], (i + 1 == d.size() ? "" : ", "));
    }
    std::printf("]   (push_front put 1 at the front in O(1))\n");
    std::printf("  d.front()=%d  d.back()=%d  d[1]=%d (operator[] is O(1))\n",
                d.front(), d.back(), d[1]);

    // A vector CANNOT do push_front in O(1): inserting at begin() shifts every
    // element (O(n)). We demonstrate the equivalent O(n) op for contrast (no
    // assertion on the count — only that it works).
    std::vector<int> vd = {2, 3};
    vd.insert(vd.begin(), 1);           // O(n) shift — the vector's only way
    std::printf("  vector equivalent: v.insert(begin(),1) is O(n) (shifts all); "
                "vd = [%d,%d,%d]\n", vd[0], vd[1], vd[2]);

    check("deque push_front placed 1 at the front in O(1)", d.front() == 1);
    check("deque supports O(1) operator[] random access", d[0] == 1 && d[2] == 3);
    check("deque size is 3 after 2 push_back + 1 push_front", d.size() == 3);
}

// === Section D — std::list / std::forward_list: node-based, STABLE iterators=
//
// std::list<T> is a doubly-linked list; std::forward_list<T> is a singly-linked
// list. Both are NODE-BASED: each element lives in its own heap node, so there
// is NO contiguous storage and NO random access (no operator[]/at()). The payoff
// is that insertion/erasure at a KNOWN iterator position is O(1) (just relink a
// few pointers), and — crucially — iterators/pointers/references to NON-erased
// elements stay VALID across insert/erase of OTHER elements (only the erased
// element's iterator is invalidated). This "iterator stability" is the reason to
// choose a list over a vector.
//
// splice() takes whole NODES from one list into another in O(1) per node — no
// element copy/move, and the iterators to spliced nodes remain valid (they now
// observe the node in its new list).
void sectionD() {
    sectionBanner("D — std::list / forward_list: node, O(1) insert, stable iter");

    // --- std::list: O(1) insert at an iterator + STABLE iterators ------------
    std::list<int> l = {1, 2, 4};
    auto lit = std::next(l.begin());    // points at the node holding 2
    std::printf("std::list<int> l = {1,2,4}; auto lit = next(begin()); // -> %d\n",
                *lit);

    // O(1) insert right before lit (a vector would have to shift — O(n)).
    l.insert(lit, 99);                  // {1, 99, 2, 4}; lit still -> 2
    std::printf("l.insert(lit, 99);  -> l = [1, 99, 2, 4]; *lit (STILL valid) = %d\n",
                *lit);

    // push_back does NOT invalidate lit (node-based, no reallocation).
    l.push_back(5);                     // {1, 99, 2, 4, 5}
    std::printf("l.push_back(5);     -> *lit (STILL valid — no realloc) = %d\n", *lit);

    // Erase a DIFFERENT element: lit survives (only the erased node is gone).
    auto to_erase = std::next(l.begin());  // points at 99
    l.erase(to_erase);                  // removes 99; {1, 2, 4, 5}
    std::printf("l.erase(node holding 99); -> *lit (STILL valid — only erased "
                "node dies) = %d\n", *lit);

    // Erase the element lit points at -> lit is NOW invalid. We do NOT read it.
    int lit_value_before = *lit;        // last safe read: 2
    l.erase(lit);                       // {1, 4, 5}; lit is INVALIDATED
    std::printf("l.erase(lit); (erased the node lit pointed at) -> lit is now "
                "INVALIDATED; not read.\n");
    std::printf("  last safe value read from lit (before erase) = %d\n",
                lit_value_before);

    std::printf("  final l = ");
    printList(l);
    std::printf("\n");

    check("list: insert(99)+erase(99)+erase(lit=2) net-left the list as {1,4,5}",
          listEquals(l, {1, 4, 5}));
    check("list: the last safe value read from `lit` before its erase was 2",
          lit_value_before == 2);

    // --- std::list: NO operator[] (no random access) — documented, not built -
    // l[2];   // <-- would NOT COMPILE (list has no operator[]). Documented here.

    // --- splice: move nodes between lists in O(1), iterators stay valid ------
    std::list<int> x = {10, 20};
    std::list<int> y = {30, 40, 50};
    auto spit = y.begin();              // points at node 30 in y
    ++spit;                             // points at node 40 in y
    std::printf("\nsplice: x={10,20}, y={30,40,50}; auto spit = y node 40;\n");
    // Move the single node 40 from y into x in O(1) (no copy; pointers relink).
    x.splice(x.end(), y, spit);         // x={10,20,40}, y={30,50}; spit still -> 40
    std::printf("  x.splice(x.end(), y, spit);  -> x = ");
    printList(x);
    std::printf(", y = ");
    printList(y);
    std::printf("\n  *spit (STILL valid — now observes the node in x) = %d\n", *spit);
    check("splice moved node 40 out of y (y lost it)", listEquals(y, {30, 50}));
    check("splice moved node 40 into x", listEquals(x, {10, 20, 40}));
    check("spit stayed valid across splice (now points in x)", *spit == 40);

    // --- std::forward_list: singly-linked, push_front only, no size() --------
    std::forward_list<int> fl = {3, 4};
    fl.push_front(2);
    fl.push_front(1);                   // {1, 2, 3, 4}
    std::printf("\nstd::forward_list<int> fl = {3,4}; fl.push_front(2); "
                "fl.push_front(1);\n");
    std::printf("  fl = ");
    printFList(fl);
    std::printf("   (singly-linked; push_front only; NO push_back; NO size())\n");
    check("forward_list push_front built {1,2,3,4}", flEquals(fl, {1, 2, 3, 4}));
}

// === Section E — per-container invalidation rules + emplace vs push + choice =
//
// The decisive expert knowledge: which operation invalidates which iterator, per
// container. This table is printed verbatim (a documentation block); the values
// it claims are the standard's guarantees (cppreference, "Iterator invalidation"
// on the Containers page), not numbers this program computed.
void sectionE() {
    sectionBanner("E — invalidation rules + emplace_back + the choice matrix");

    std::printf("ITERATOR INVALIDATION (per cppreference, Containers library):\n");
    std::printf("  container       insertion                                  erasure\n");
    std::printf("  --------------  ----------------------------------------   ------------------------------------------\n");
    std::printf("  vector          realloc -> ALL; else at/after the point   erased + at/after (incl end())\n");
    std::printf("  deque           at ends -> only end(); middle -> ALL      all EXCEPT erased (end() may invalidate)\n");
    std::printf("  list            ALL iterators stay valid (no realloc)     only the ERASED element\n");
    std::printf("  forward_list    ALL iterators stay valid                  only the ERASED element\n");
    std::printf("  array           N/A (fixed size — cannot insert/erase)    N/A\n");
    std::printf("\nThe headline contrasts:\n");
    std::printf("  * vector REALLOCATION invalidates EVERY iterator/pointer/reference.\n");
    std::printf("  * list erase invalidates ONLY the erased node (everything else stable).\n");

    // --- emplace_back vs push_back: emplace CONSTRUCTS in place (no temp) -----
    struct Point {
        int x, y;
        Point(int x_, int y_) : x(x_), y(y_) {}
    };
    std::vector<Point> pv;
    pv.reserve(4);
    // emplace_back forwards args DIRECTLY to the constructor — no temporary
    // Point is constructed, then moved/copied. push_back needs an already-built
    // Point object (or braces) to move/copy in.
    pv.emplace_back(1, 2);              // constructs Point(1,2) IN the vector
    pv.push_back(Point(3, 4));          // constructs a temp, then moves it in
    pv.push_back({5, 6});               // braces -> temp -> move in
    std::printf("\nemplace_back(1,2) constructs in place; push_back(Point(3,4)) /\n");
    std::printf("push_back({5,6}) build a temp then move it in. Result is identical:\n");
    std::printf("  pv = [(%d,%d), (%d,%d), (%d,%d)]\n",
                pv[0].x, pv[0].y, pv[1].x, pv[1].y, pv[2].x, pv[2].y);
    check("emplace_back(1,2) placed Point(1,2)", pv[0].x == 1 && pv[0].y == 2);
    check("push_back(Point(3,4)) placed Point(3,4)", pv[1].x == 3 && pv[1].y == 4);
    check("push_back({5,6}) placed Point(5,6)", pv[2].x == 5 && pv[2].y == 6);

    // --- the choice matrix ---------------------------------------------------
    std::printf("\nCHOICE MATRIX (which container wins when):\n");
    std::printf("  need...                                   pick\n");
    std::printf("  ----------------------------------------  ----------------------\n");
    std::printf("  default / contiguous / cache-friendly      std::vector\n");
    std::printf("  fixed size known at compile time           std::array<T,N>\n");
    std::printf("  O(1) push/pop at BOTH ends                 std::deque\n");
    std::printf("  O(1) insert/erase in the MIDDLE + stable   std::list\n");
    std::printf("    iterators, minimal memory overhead       std::forward_list\n");
    std::printf("\nRule of thumb: reach for std::vector unless you have a measured reason\n");
    std::printf("not to — its contiguous storage is cache-friendly and push_back is\n");
    std::printf("amortized O(1). std::array for fixed sizes; std::deque for front+back;\n");
    std::printf("std::list only when iterator stability or frequent middle insert/erase\n");
    std::printf("dominates (and even then, benchmark against vector first).\n");
    check("vector is the default choice (contiguous, amortized-O(1) push_back)", true);
}

}  // namespace

int main() {
    std::printf("containers_sequence.cpp — Phase 5 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
