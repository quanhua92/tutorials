// __STEM__.cpp — bundle.
//
// GOAL (one line): TODO.
//
// This is the GROUND TRUTH for __STEM_UPPER__.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     just run __STEM__          (or: c++ -std=c++23 -O2 -Wall -Wextra __STEM__.cpp -o /tmp/x && /tmp/x)

#include <cstdio>     // printf / fprintf
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (for the banner bar)

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

// === REPLACE THE DEMO SECTION BELOW WITH YOUR REAL SECTIONS ===
// Each section: prints a sectionBanner, a readable block of values, then
// check() asserts for every invariant. Delete this demo once you add your own.

void sectionA() {
    sectionBanner("A — DEMO (replace me)");
    constexpr int two = 1 + 1;
    std::printf("1 + 1 = %d\n", two);
    check("1 + 1 == 2", two == 2);
}

}  // namespace

int main() {
    std::printf("__STEM__.cpp — bundle.\n");
    std::printf("Every value below is computed by this file.\n");
    sectionA();
    sectionBanner("DONE — all sections printed");
}
