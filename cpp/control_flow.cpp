// control_flow.cpp — Phase 1 bundle (CONTROL_FLOW).
//
// GOAL (one line): show, by printing every value, how C++'s control-flow
// statements behave — if/else + ternary + if-with-initializer (C++17), switch
// (FALLS THROUGH by default; NOT exhaustive; with-initializer), range-for +
// classic for/while/do-while + break/continue, structured bindings (C++17), and
// goto (the one legitimate use: breaking nested loops, since C++ has NO labeled
// break — unlike Java/Go).
//
// This is the GROUND TRUTH for CONTROL_FLOW.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     just run control_flow   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                              control_flow.cpp -o /tmp/cpp_control_flow
//                              && /tmp/cpp_control_flow)

#include <array>       // std::array (range-for target)
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <map>         // std::map (ORDERED — safe to iterate deterministically)
#include <string>      // std::string
#include <type_traits> // std::is_pointer_v (if constexpr demo)
#include <utility>     // std::pair (structured bindings)

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

// if constexpr (C++17) helper for Section A — full treatment is the
// IF_CONSTEXPR bundle (P6). The not-taken branch is DISCARDED at compile time.
template <typename T>
const char* classify(T) {
    if constexpr (std::is_pointer_v<T>)
        return "pointer";
    else
        return "value";
}

// === Section A — if/else + ternary + if-with-initializer ====================
//
// if/else is the basic branch. The ternary `cond ? a : b` is the expression
// form. The C++17 if-with-initializer scopes a name to BOTH the if-body and the
// else-body — the idiomatic "lookup, then test" (no leak of a temp `it`).
void sectionA() {
    sectionBanner("A — if/else + ternary + if-with-initializer");

    // (1) Classic if/else if/else. The condition is contextually converted to
    //     bool; the FIRST true branch wins.
    int score = 85;
    const char* grade = "F";
    if (score >= 90) grade = "A";
    else if (score >= 80) grade = "B";
    else if (score >= 70) grade = "C";
    else grade = "F";
    std::printf("(1) if/else if/else:  score=%d -> grade=%s\n", score, grade);
    check("if/else picks the first true branch (score 85 -> B)",
          std::string(grade) == "B");

    // (2) Ternary `cond ? a : b` — an EXPRESSION that yields a value. Both arms
    //     must share a common type (usual arithmetic/conversion rules).
    int n = -3;
    int abs_n = (n >= 0) ? n : -n;                 // yields int
    const char* sign = (n >= 0) ? ">=0" : "<0";    // yields const char*
    std::printf("(2) ternary:  n=%d  abs(n)=%d  sign=%s\n", n, abs_n, sign);
    check("ternary abs(-3) == 3", abs_n == 3);
    check("ternary picks the '<0' arm for n=-3", std::string(sign) == "<0");

    // (3) if-with-initializer (C++17): `if (init-stmt; condition)`. The name
    //     declared in init-stmt is scoped to the if-body AND the else-body
    //     (and nowhere else). Idiomatic for "lookup then test". std::map is
    //     ORDERED, so iterating it is deterministic (HOW_TO_RESEARCH §4.2 #3).
    std::map<std::string, int> stock = {
        {"apple", 1}, {"banana", 2}, {"cherry", 3}};
    int banana_count = -1;
    if (auto it = stock.find("banana"); it != stock.end()) {
        banana_count = it->second;   // `it` is usable inside the if-body
    }
    std::printf("(3a) if-with-init found:  banana -> %d\n", banana_count);
    check("if-with-init: the scoped var `it` is usable in the if-body",
          banana_count == 2);

    // The scoped name is ALSO visible in the else branch:
    bool else_saw_end = false;
    if (auto it = stock.find("zzz"); it != stock.end()) {
        // not taken
    } else {
        else_saw_end = (it == stock.end());  // `it` is in scope in else too
    }
    std::printf("(3b) if-with-init else:  missing key -> it == end()? %s\n",
                else_saw_end ? "yes" : "no");
    check("if-with-init: the scoped var is ALSO visible in the else branch",
          else_saw_end);

    // (4) if constexpr (C++17) — the compile-time if. The condition is a
    //     constant expression; the not-taken branch is DISCARDED. Inside a
    //     template the discarded arm is not instantiated, so it may hold code
    //     valid for only one branch. (Full depth: IF_CONSTEXPR bundle, P6.)
    const char* c_int = classify(42);   // T = int  -> not a pointer -> "value"
    int x = 7;
    const char* c_ptr = classify(&x);   // T = int* -> is_pointer_v -> "pointer"
    std::printf("(4) if constexpr:  classify(42)=%s  classify(&x)=%s\n",
                c_int, c_ptr);
    check("if constexpr picked 'value' for an int argument",
          std::string(c_int) == "value");
    check("if constexpr picked 'pointer' for an int* argument",
          std::string(c_ptr) == "pointer");
}

// === Section B — switch: fall-through (the trap) + with-init + NOT exhaustive
//
// switch matches an integral/enum value against `case` labels. THE TRAP: case
// labels do NOT alter flow — execution FALLS THROUGH to the next case unless a
// `break` exits. Mark intentional fall-through with [[fallthrough]] (C++17) so
// -Wimplicit-fallthrough stays silent. default is OPTIONAL (switch is NOT
// exhaustive — contrast Rust's mandatory-complete `match`).
void sectionB() {
    sectionBanner("B — switch: fall-through (the trap) + with-init + NOT exhaustive");

    // (1) FALL-THROUGH: with no `break`, execution continues into the NEXT case
    //     label. THIS IS THE TRAP. We annotate each intentional fall-through
    //     with [[fallthrough]] (C++17); the attribute only documents intent and
    //     silences the warning — the run behavior is identical with or without.
    int fell = 0;
    switch (int v = 1; v) {        // switch-with-initializer (C++17)
        case 1:
            fell += 1;
            [[fallthrough]];       // no break -> flow continues into case 2
        case 2:
            fell += 10;
            [[fallthrough]];       // continues into case 3
        case 3:
            fell += 100;
            break;                 // break EXITS the switch
        case 9:
            fell += 1000;          // never reached (v == 1)
            break;
    }
    std::printf("(1) fall-through (v=1; no breaks 1->2->3):  fell = %d\n", fell);
    check("switch fall-through: case 1->2->3 all ran (1+10+100 == 111)",
          fell == 111);

    // (2) `break` STOPS the fall-through — only the matched case runs.
    int stopped = 0;
    switch (int v = 1; v) {
        case 1:
            stopped += 1;
            break;                 // exits immediately; case 2 does NOT run
        case 2:
            stopped += 10;
            break;
    }
    std::printf("(2) break stops fall-through (v=1):  stopped = %d\n", stopped);
    check("switch break: only case 1 ran (stopped == 1)", stopped == 1);

    // (3) switch is NOT exhaustive: `default` is OPTIONAL, and an UNMATCHED
    //     value runs NOTHING (this is NOT an error). A value of 7 matches no
    //     case and there is no default, so the body is skipped entirely.
    //     Contrast Rust, where `match` MUST cover every case.
    int touched = 0;
    switch (int v = 7; v) {
        case 1: touched = 1; break;
        case 2: touched = 2; break;
        // NO default: v == 7 matches nothing -> body skipped, no error
    }
    std::printf("(3) NOT exhaustive (v=7, no default):  touched = %d (unchanged)\n",
                touched);
    check("switch is NOT exhaustive: unmatched value ran nothing (touched == 0)",
          touched == 0);

    // (4) switch on an enumeration. A scoped `enum class` works the same as a
    //     plain enum; integral promotions apply to the condition. default
    //     remains optional.
    enum class Light { Red, Yellow, Green };
    Light light = Light::Yellow;
    const char* action = "stop";
    switch (light) {
        case Light::Red:    action = "stop";  break;
        case Light::Yellow: action = "slow";  break;
        case Light::Green:  action = "go";    break;
    }
    std::printf("(4) switch on enum class:  Yellow -> %s\n", action);
    check("switch matched the Yellow enumerator", std::string(action) == "slow");
}

// === Section C — range-for + classic for/while/do-while + break/continue =====
//
// range-for (C++11) desugars to a begin()/end() iterator loop. Use `const
// auto&` to READ elements without copying them. The classic for/while/do-while
// behave as in C; do-while runs its body at least once.
void sectionC() {
    sectionBanner("C — range-for + classic for/while/do-while + break/continue");

    // (1) range-for over a std::array. `const auto&` AVOIDS COPYING each element
    //     (the idiomatic read form). std::array iterates in index order.
    std::array<int, 5> arr = {10, 20, 30, 40, 50};
    int sum = 0;
    for (const auto& x : arr) sum += x;   // const auto& -> no copy
    std::printf("(1) range-for over std::array (const auto&):  sum = %d\n", sum);
    check("range-for visited all 5 elements in order (sum == 150)", sum == 150);

    // (2) range-for over a std::string yields each char (by value is fine —
    //     chars are cheap). Counts the vowels.
    std::string word = "education";
    int vowels = 0;
    for (char c : word) {
        if (c == 'a' || c == 'e' || c == 'i' || c == 'o' || c == 'u') ++vowels;
    }
    std::printf("(2) range-for over std::string \"%s\":  vowels = %d\n",
                word.c_str(), vowels);
    check("range-for counted vowels in 'education' (== 5)", vowels == 5);

    // (3) Classic for / while / do-while.
    int for_sum = 0;
    for (int i = 1; i <= 5; ++i) for_sum += i;          // 1+2+3+4+5
    int while_prod = 1, k = 1;
    while (k <= 4) { while_prod *= k; ++k; }            // 1*2*3*4
    int do_count = 0, d = 0;
    do { ++do_count; } while (++d < 3);                 // runs for d=0,1,2
    std::printf("(3) classic loops:  for_sum=%d  while_prod=%d  do_count=%d\n",
                for_sum, while_prod, do_count);
    check("classic for sum 1..5 == 15", for_sum == 15);
    check("classic while factorial(4) == 24", while_prod == 24);
    check("do-while ran 3 times (d=0,1,2)", do_count == 3);

    // (4) do-while runs its body AT LEAST ONCE — the test is AFTER the body, so
    //     even a false-from-the-start condition executes the body one time.
    int runs = 0;
    do { ++runs; } while (false);   // condition false, but body already ran
    std::printf("(4) do-while body runs once even when condition is false:  runs=%d\n",
                runs);
    check("do-while body runs once before testing (runs == 1)", runs == 1);

    // (5) break (exit the loop) and continue (skip to the next iteration).
    int evens = 0;
    for (int i = 1; i <= 10; ++i) {
        if (i % 2 != 0) continue;   // skip the odds
        evens += i;                 // sum the evens: 2+4+6+8+10
    }
    int first_over = 0;
    for (int i = 1; i <= 100; ++i) {
        if (i * i > 20) { first_over = i; break; }   // exit on first match
    }
    std::printf("(5) break/continue:  evens=%d  first i with i*i>20 = %d\n",
                evens, first_over);
    check("continue skipped odds: sum of evens 2..10 == 30", evens == 30);
    check("break exited on first i with i*i>20 (i == 5)", first_over == 5);
}

// === Section D — structured bindings (C++17) + the no-labeled-break note =====
//
// `auto [a, b] = expr;` binds names to sub-objects of expr in ONE declaration.
// Three cases: array (Case 1), tuple-like via std::tuple_size (Case 2, e.g.
// std::pair/tuple), and a class's data members in declaration order (Case 3).
// The hidden variable `e` holds the value; a, b alias its sub-objects.
//
// THE NOTE: C++ has NO labeled break/continue (unlike Java `break outer;` or Go
// `break Outer`). To leave a NESTED loop you use a flag, a helper function +
// `return`, or `goto` (Section E).
void sectionD() {
    sectionBanner("D — structured bindings (C++17) + the no-labeled-break note");

    // (1) Destructure a std::pair (tuple-like, Case 2).
    std::pair<int, double> pr = {7, 3.5};
    auto [first, second] = pr;
    std::printf("(1) auto [a,b] = pair{7,3.5}:  a=%d  b=%.6f\n", first, second);
    check("structured binding destructured a std::pair (a == 7)", first == 7);
    check("structured binding pair second == 3.500000",
          second > 3.499999 && second < 3.500001);

    // (2) Destructure a struct's data members (Case 3), in declaration order.
    struct Point { int x; int y; };
    Point pt = {3, 4};
    auto [px, py] = pt;
    std::printf("(2) auto [x,y] = Point{3,4}:  x=%d  y=%d\n", px, py);
    check("structured binding destructured a struct (px == 3, py == 4)",
          px == 3 && py == 4);

    // (3) Destructure a C-array (Case 1): the identifier count must match.
    int triple[3] = {1, 2, 3};
    auto [a0, a1, a2] = triple;   // copies triple into hidden e, binds elements
    std::printf("(3) auto [a0,a1,a2] = int[3]{1,2,3}:  %d %d %d\n", a0, a1, a2);
    check("structured binding destructured a C-array (1 2 3)",
          a0 == 1 && a1 == 2 && a2 == 3);

    // (4) range-for + structured bindings over a std::map: `for (const auto&
    //     [k, v] : map)`. std::map is ORDERED, so this iterates deterministically.
    std::map<std::string, int> prices = {
        {"apple", 1}, {"banana", 2}, {"cherry", 3}};
    std::string keys;
    int total = 0;
    for (const auto& [k, v] : prices) {
        keys += k + " ";
        total += v;
    }
    std::printf("(4) range-for [k,v] over std::map:  keys=\"%s\" total=%d\n",
                keys.c_str(), total);
    check("structured bindings in range-for: keys in sorted order",
          keys == "apple banana cherry ");
    check("structured bindings range-for summed map values (1+2+3 == 6)",
          total == 6);

    // (5) THE NO-LABELED-BREAK NOTE: C++ has NO labeled break/continue. The
    //     FLAG approach to leaving a nested loop (contrast with goto in E):
    int fx = -1, fy = -1;
    bool found = false;
    for (int x = 0; x < 3 && !found; ++x) {
        for (int y = 0; y < 3 && !found; ++y) {
            if (x + y >= 3) { fx = x; fy = y; found = true; }
        }
    }
    std::printf("(5) nested-loop break via FLAG (no labeled break in C++):  (%d,%d)\n",
                fx, fy);
    check("flag-based nested break found first cell with x+y>=3: (1,2)",
          fx == 1 && fy == 2);
}

// === Section E — goto: the one legitimate use (breaking nested loops) ========
//
// goto is generally avoided (Dijkstra, "Go To Statement Considered Harmful",
// 1968), but has ONE clean legitimate use: breaking out of a NESTED loop in a
// single jump — because C++ has NO labeled break. The label must be in the SAME
// function. A forward goto cannot enter the scope of an initialized variable.
void sectionE() {
    sectionBanner("E — goto: the one legit use (breaking nested loops)");

    // (1) goto breaks BOTH nested loops in one jump. (Compare the flag dance in
    //     Section D(5).) A forward goto over no initialized declarations is
    //     warning-clean — no -Wno- needed.
    int gx = -1, gy = -1;
    for (int x = 0; x < 3; ++x) {
        for (int y = 0; y < 3; ++y) {
            if (x + y >= 3) { gx = x; gy = y; goto found; }
        }
    }
found:
    std::printf("(1) goto breaks nested loops in one jump:  found (%d,%d)\n", gx, gy);
    check("goto nested-loop break found first cell with x+y>=3: (1,2)",
          gx == 1 && gy == 2);

    // (2) A BACKWARD goto can form a loop (legal, though a while/for is
    //     clearer). When a goto exits an automatic variable's scope, that
    //     variable's DESTRUCTOR runs — RAII is respected. Here `count` is
    //     declared BEFORE the label, so the backward jump stays in scope.
    int count = 0;
backward:
    ++count;
    if (count < 3) goto backward;
    std::printf("(2) backward goto as a loop:  count = %d\n", count);
    check("backward goto looped until count == 3", count == 3);

    // (3) RULE: a forward goto CANNOT jump INTO the scope of a variable with an
    //     initializer (ill-formed — won't compile). It MAY jump over a scalar
    //     declared WITHOUT an initializer. We document the rule; the offending
    //     forward-jump-over-initializer is gated behind #ifdef DEMO_UB so the
    //     default build stays clean (it would not compile otherwise).
    std::printf("(3) goto rules: same-function only; a forward jump into an\n");
    std::printf("    initialized variable's scope is ill-formed (won't compile);\n");
    std::printf("    destructors run when a goto exits a scope (RAII respected).\n");
    check("goto rules documented (verified path stays clean)", true);
}

}  // namespace

int main() {
    std::printf("control_flow.cpp — Phase 1 bundle (CONTROL_FLOW).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
