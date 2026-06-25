// arrays_strings.cpp — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how C++'s four sequence
// storage kinds differ — C-array (DECAYS to T* and loses its size),
// std::array<T,N> (size-aware, value-semantic, no decay), std::string (OWNED,
// growable), and std::string_view (NON-OWNING borrow with the dangling-view UB
// trap) — pinning out-of-bounds-as-UB and the dangling-string_view as
// documented expert payoffs (never executed in the verified path).
//
// This is the GROUND TRUTH for ARRAYS_STRINGS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run arrays_strings   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                arrays_strings.cpp -o /tmp/cpp_arrays_strings
//                                && /tmp/cpp_arrays_strings)

#include <array>       // std::array
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar), strlen
#include <stdexcept>   // std::out_of_range
#include <string>      // std::string
#include <string_view> // std::string_view

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

// === Section A — C-style array T[N] =========================================
//
// The ORIGINAL C inheritance: `int arr[5]` is a fixed-size, contiguous block of
// 5 ints. It is an object (not a reference), but C++ makes it NON-copyable
// (assignment / copy-init from another array is ill-formed) and — the famous
// trap — it DECAYS to `int*` on almost every use (passing to a function,
// returning, most expressions), THROWING AWAY its size. `sizeof(arr)` in the
// DEFINING scope is N*sizeof(T); `sizeof(a)` inside `void f(int a[])` is
// sizeof(int*) — the size is GONE. Out-of-bounds `arr[i]` past the end is
// UNDEFINED BEHAVIOR (unchecked; no throw, no trap — the compiler may assume it
// never happens). Documented below, never executed in the verified path.

// A function taking a C-array parameter. In the PARAMETER LIST, the spelling
// `int a[]` is ADJUSTED to `int* a` — array-to-pointer decay happens in the
// declaration itself, so the function NEVER sees the array's size. We write the
// TRUE type `int* a` (writing `int a[]` and then `sizeof(a)` would trip
// -Wsizeof-array-argument — clang pointing at the very bug we teach); `sizeof`
// of a pointer is uncontroversially the pointer size.
std::size_t sizeofDecayedParam(int* a) {
    return sizeof(a);  // sizeof(int*) — the array's size is GONE
}

void sectionA() {
    sectionBanner("A — C-style array T[N]: decays to T*, loses size; OOB is UB");

    int carr[5] = {10, 20, 30, 40, 50};

    std::printf("int carr[5] = {10,20,30,40,50};\n");
    std::printf("  sizeof(carr)                = %zu  (= 5 * sizeof(int)=%zu)\n",
                sizeof(carr), 5 * sizeof(int));
    std::printf("  sizeof(carr)/sizeof(carr[0]) = %zu  (the manual size trick)\n",
                sizeof(carr) / sizeof(carr[0]));
    std::printf("  carr[0]=%d  carr[4]=%d  (valid indices 0..4)\n", carr[0], carr[4]);

    // THE TRAP: pass to a function -> decays to int*. Size is LOST.
    std::printf("\nsizeofDecayedParam(carr) = %zu  (== sizeof(int*)=%zu — size LOST on pass!)\n",
                sizeofDecayedParam(carr), sizeof(int*));

    check("C-array: sizeof(carr) == 5 * sizeof(int)", sizeof(carr) == 5 * sizeof(int));
    check("C-array: sizeof(carr)/sizeof(carr[0]) == 5 (size trick in defining scope)",
          sizeof(carr) / sizeof(carr[0]) == 5);
    check("C-array DECAYS: sizeof(param) == sizeof(int*) (size lost on pass)",
          sizeofDecayedParam(carr) == sizeof(int*));

    // OOB is UB — documented, NOT executed.
    std::printf("\ncarr[5] / carr[99] would be OUT-OF-BOUNDS -> UNDEFINED BEHAVIOR\n");
    std::printf("  (C-arrays have NO bounds check; the verified path never reads OOB.)\n");

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // carr[99] reads 94 ints past the end -> UB. ASan reports a stack-buffer-
    // overflow on the read; the printed value is meaningless (the compiler is
    // entitled to assume this never happens).
    std::printf("[DEMO_UB] carr[99] = %d  <-- UNDEFINED BEHAVIOR (OOB read)\n", carr[99]);
#else
    std::printf("  (DEMO_UB not defined: the OOB read is correctly omitted from this build.)\n");
#endif
    check("C-array OOB access is UB (documented; not executed in verified path)", true);
}

// === Section B — std::array<T,N>: size-aware, value-semantic, no decay =======
//
// std::array (C++11) is a fixed-size wrapper over a C-array: SAME memory layout
// (sizeof == N*sizeof(T), no overhead), but it KNOWS its size (.size()), is a
// TRUE value type (copyable, assignable — element-wise copy), supports .at(i)
// (CHECKED — throws std::out_of_range) AND operator[] (UNCHECKED — OOB is UB),
// iterators, and std::get<i> (compile-time-checked access). Crucially it does
// NOT decay: pass `const std::array<T,N>&` and the size is preserved.

// Passing std::array BY REFERENCE: the size is preserved (no decay).
template <typename T, std::size_t N>
std::size_t arraySize(const std::array<T, N>& a) {
    return a.size();
}

void sectionB() {
    sectionBanner("B — std::array<T,N>: size-aware, .at() throws, no decay");

    std::array<int, 3> a = {1, 2, 3};
    std::printf("std::array<int,3> a = {1,2,3};\n");
    std::printf("  a.size()   = %zu\n", a.size());
    std::printf("  sizeof(a)  = %zu  (= 3 * sizeof(int)=%zu — NO overhead vs C-array)\n",
                sizeof(a), 3 * sizeof(int));
    std::printf("  a[0]=%d  a[1]=%d  a[2]=%d\n", a[0], a[1], a[2]);

    // True VALUE semantics: a real element-wise copy (C-arrays can't do this).
    std::array<int, 3> b = a;  // copy
    b[0] = 99;
    std::printf("\nstd::array<int,3> b = a;  b[0] = 99;  -> a[0]=%d (copy is independent)\n", a[0]);

    // std::get<i> : compile-time bounds-checked access.
    std::printf("std::get<2>(a) = %d  (compile-time-checked index)\n", std::get<2>(a));

    // .at(i) : RUNTIME bounds-checked — throws std::out_of_range on OOB.
    bool threw = false;
    try {
        (void)a.at(99);  // 99 >= size 3 -> throws std::out_of_range
    } catch (const std::out_of_range&) {
        threw = true;
    }
    std::printf("a.at(99) -> threw std::out_of_range: %s  (CHECKED access)\n",
                threw ? "YES" : "no");

    // No decay: passing by reference keeps the size.
    std::printf("arraySize(a) = %zu  (passed by const& — size PRESERVED, no decay)\n",
                arraySize(a));

    // operator[] is UNCHECKED: a[99] is UB — documented, never executed.
    std::printf("\na[99] would be UNCHECKED OOB -> UB (use .at() for checked access)\n");

    check("std::array: a.size() == 3", a.size() == 3);
    check("std::array: sizeof(a) == 3 * sizeof(int) (no overhead vs C-array)",
          sizeof(a) == 3 * sizeof(int));
    check("std::array: copy is independent (b[0]=99 did not change a[0])", a[0] == 1);
    check("std::array: std::get<2>(a) == 3 (compile-time-checked)", std::get<2>(a) == 3);
    check("std::array: a.at(99) threw std::out_of_range (runtime-checked)", threw);
    check("std::array: no decay — arraySize(a) preserved size == 3", arraySize(a) == 3);
    check("std::array: operator[] OOB is UB (documented; not executed)", true);
}

// === Section C — std::string: OWNED, growable, value-semantic; UTF-8=bytes ===
//
// std::string is an OWNED, dynamically-growable sequence of char (bytes). It is
// a TRUE value type: copy construction copies the buffer, assignment rebinds the
// owned buffer. Grows via push_back/append/+=/insert. .size()/.length() give the
// BYTE count. IMPORTANT CAVEAT: there is NO built-in Unicode — a std::string is
// just bytes; a UTF-8 code point like 'e' (U+00E9) is TWO bytes (0xC3 0xA9), and
// .size() counts BYTES, not characters. (Contrast: TS/Rust know about code
// points.)

void sectionC() {
    sectionBanner("C — std::string: OWNED growable; UTF-8 counts BYTES");

    std::string s = "hello";
    std::printf("std::string s = \"hello\";\n");
    std::printf("  s.size()=%zu  s.length()=%zu  (length == size)\n", s.size(), s.length());

    s.push_back('!');
    s.append(" world");
    s += '?';
    std::printf("after s.push_back('!'); s.append(\" world\"); s+='?';\n");
    std::printf("  s = \"%s\"  s.size()=%zu\n", s.c_str(), s.size());

    // Value-semantic copy.
    std::string s2 = s;
    s2[0] = 'X';
    std::printf("\nstd::string s2 = s;  s2[0] = 'X';  -> s[0]='%c' (independent copy)\n", s[0]);

    // Substring + find.
    const std::size_t world_pos = s.find("world");
    std::printf("s.substr(0,5) = \"%s\"   s.find(\"world\") = %zu\n",
                s.substr(0, 5).c_str(), world_pos);

    // UTF-8 is BYTES: 'e-acute' (U+00E9) is 0xC3 0xA9 -> TWO bytes in a string.
    // (Bytes written explicitly so the result is source-encoding-independent.)
    std::string utf8 = "\xc3\xa9";  // U+00E9 LATIN SMALL LETTER E WITH ACUTE
    std::printf("\nstd::string utf8 = \"\\xc3\\xa9\";  (UTF-8 for U+00E9)\n");
    std::printf("  utf8.size() = %zu  (BYTES, not characters — no built-in unicode)\n", utf8.size());
    std::printf("  utf8[0] = 0x%02x  utf8[1] = 0x%02x  (two bytes)\n",
                static_cast<unsigned>(static_cast<unsigned char>(utf8[0])),
                static_cast<unsigned>(static_cast<unsigned char>(utf8[1])));

    // .c_str() : null-terminated const char* (interop with C APIs).
    std::printf("\ns.c_str() -> const char* (null-terminated, C-interop); strlen(s.c_str())=%zu\n",
                std::strlen(s.c_str()));

    check("string: s after appends == \"hello! world?\" (size 13)",
          s == "hello! world?" && s.size() == 13);
    check("string: s.size() == s.length()", s.size() == s.length());
    check("string: copy is independent (s2[0]='X' left s[0]='h')", s[0] == 'h');
    check("string: s.substr(0,5) == \"hello\"", s.substr(0, 5) == "hello");
    check("string: s.find(\"world\") == 7", world_pos == 7);
    check("string: UTF-8 U+00E9 is 2 BYTES (utf8.size()==2)", utf8.size() == 2);
    check("string: utf8 bytes are 0xC3 0xA9",
          static_cast<unsigned char>(utf8[0]) == 0xC3 &&
              static_cast<unsigned char>(utf8[1]) == 0xA9);
    check("string: strlen(s.c_str()) == s.size() (no embedded null)",
          std::strlen(s.c_str()) == s.size());
}

// === Section D — std::string_view (C++17): NON-OWNING borrow; DANGLING trap ==
//
// std::string_view is a (pointer + length) view over a contiguous char range.
// It does NOT own the data — it BORROWS it (⟷ Rust's &str). It is CHEAP to copy
// (just two words) and the idiomatic READ-ONLY function parameter (replaces
// `const std::string&` and `const char*` for read-only text). THE TRAP: because
// it does not own, a string_view MUST NOT OUTLIVE its referent. A string_view
// bound to a TEMPORARY string dangles the instant the temporary dies — reading
// it is UB. Documented below (#ifdef DEMO_UB), never executed in verified path.

void sectionD() {
    sectionBanner("D — std::string_view: NON-OWNING borrow; dangling-view UB trap");

    // From a string LITERAL: the literal has STATIC storage duration (lives for
    // the whole program) -> the view is safe forever.
    std::string_view sv1 = "literal";  // borrows a static-storage string literal
    std::printf("std::string_view sv1 = \"literal\";  (borrows a string literal)\n");
    std::printf("  sv1.size()   = %zu\n", sv1.size());
    std::printf("  sizeof(sv1)  = %zu  (data pointer + length)\n", sizeof(sv1));
    std::printf("  sv1 = \"%.*s\"\n", static_cast<int>(sv1.size()), sv1.data());

    // From a std::string: cheap view over the string's buffer. Valid while the
    // string lives and is not resized/moved.
    std::string s = "hello world";
    std::string_view sv2 = s;  // borrows s's buffer
    std::printf("\nstd::string s = \"hello world\";  std::string_view sv2 = s;\n");
    std::printf("  sv2.size() = %zu   sv2.substr(0,5) = \"%.*s\"\n",
                sv2.size(), static_cast<int>(sv2.substr(0, 5).size()), sv2.substr(0, 5).data());
    std::printf("  sv2 == \"hello world\": %s   (sv2 == s.c_str()): %s\n",
                (sv2 == "hello world") ? "YES" : "no",
                (sv2 == s.c_str()) ? "YES" : "no");

    // sizeof(string_view) is just (data pointer + size) — a non-owning borrow.
    std::printf("\nsizeof(std::string_view) = %zu  (== sizeof(char*)+size_t = %zu — a borrow)\n",
                sizeof(std::string_view), sizeof(const char*) + sizeof(std::size_t));

    // THE DANGLING-VIEW TRAP: a string_view over a TEMPORARY string dangles
    // immediately. Reading it is UB. Documented only; gated behind #ifdef
    // DEMO_UB (never passed by just run/out/check/sanitize).
    std::printf("\nTRAP: std::string_view sv = std::string(\"temp\");  <- DANGLING\n");
    std::printf("  the temporary string dies at the ';'; sv dangles -> reading sv is UB\n");
    std::printf("  (documented only; the verified path never reads a dangling view)\n");

#ifdef DEMO_UB
    // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────────
    // The temporary std::string("temp") is destroyed at the end of this full
    // expression; `bad` now dangles. Reading bad.size()/bad[0] is UB. ASan/UBSan
    // report a use-after-free / stack-use-after-scope.
    std::string_view bad = std::string("temp");  // temp destroyed at the ';'
    std::printf("[DEMO_UB] bad.size()=%zu bad[0]=%c  <-- UB: reading a dangling view\n",
                bad.size(), bad[0]);  // <-- UB
#else
    std::printf("  (DEMO_UB not defined: the dangling-view UB read is correctly omitted.)\n");
#endif

    check("string_view: sv1 (from literal) size == 7", sv1.size() == 7);
    check("string_view: sv2 == \"hello world\"", sv2 == "hello world");
    check("string_view: sv2.substr(0,5) == \"hello\"", sv2.substr(0, 5) == "hello");
    check("string_view: sizeof == sizeof(char*) + sizeof(size_t) (ptr+len)",
          sizeof(std::string_view) == sizeof(const char*) + sizeof(std::size_t));
    check("string_view: dangling-view read is UB (documented; not executed)", true);
}

// === Section E — Decision guide: which sequence kind to use when ============

void sectionE() {
    sectionBanner("E — Decision guide: which sequence kind to use when");

    std::printf("C-array T[N]         : avoid in modern C++; decays & loses size.\n");
    std::printf("std::array<T,N>      : fixed size KNOWN at compile time.\n");
    std::printf("std::string          : you OWN & grow the text.\n");
    std::printf("std::string_view     : READ-ONLY borrow (cheap param); never outlive source.\n");
    std::printf("std::vector<T> (P5)  : size GROWS at runtime. (see ITERATORS_RANGES)\n");

    std::printf("\nOwnership axis (low -> high):\n");
    std::printf("  string_view (borrows, may dangle)  <  C-array (decays, loses size)\n");
    std::printf("  < std::array (owns fixed)  <  std::string (owns, growable)\n");

    // Cross-language one-liners (full treatment in sibling .md guides).
    std::printf("\nCross-language analogues:\n");
    std::printf("  Go slice    = ptr+len+cap, GROWABLE  -> C++ std::vector<T> is the analog\n");
    std::printf("  Rust &str   = NON-OWNING borrow      -> C++ std::string_view is the analog\n");
    std::printf("  Rust String = OWNED, growable        -> C++ std::string is the analog\n");
    std::printf("  JS string   = immutable UTF-16, NO UB -> C++ std::string is mutable bytes\n");

    // A few closing checks pinning the ownership classification.
    check("decision: string_view is non-owning (sizeof small, ~2 words)",
          sizeof(std::string_view) <= 2 * sizeof(void*));
    check("decision: std::array has NO overhead vs C-array (same sizeof)",
          sizeof(std::array<int, 5>) == sizeof(int[5]));
    check("decision: std::string is OWNED (concatenation grows, size reflects)",
          (std::string("ab") + "cd").size() == 4);
}

}  // namespace

int main() {
    std::printf("arrays_strings.cpp — Phase 1 bundle.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
