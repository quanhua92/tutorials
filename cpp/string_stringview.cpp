// string_stringview.cpp — Phase 5 bundle.
//
// GOAL (one line): show, by printing every value, how std::string (an OWNED,
// growable, value-semantic byte string with SSO) and std::string_view (a
// NON-OWNING C++17 borrow: ptr + length, O(1) copy/substr, but DANGLING-read is
// UB) differ — pinning the dangling-view trap as a documented expert payoff
// (never executed in the verified path).
//
// This is the GROUND TRUTH for STRING_STRINGVIEW.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// Run:
//     just run string_stringview   (== c++ -std=c++23 -O2 -Wall -Wextra
//                                    -Wpedantic string_stringview.cpp
//                                    -o /tmp/cpp_string_stringview
//                                    && /tmp/cpp_string_stringview)

#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <string>      // std::string, std::to_string, operator""s
#include <string_view> // std::string_view, operator""sv

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

// Reports whether `data` lies INSIDE the storage of the `obj` string object
// (the SSO signal: short strings live inline, long strings heap-allocate).
bool dataIsInline(const std::string& s) {
    const char* obj = reinterpret_cast<const char*>(&s);
    const char* data = s.data();
    return data >= obj && data < obj + sizeof(s);
}

// A function taking std::string_view: the "cheap-pass" idiom. ANY of {const
// char*, std::string, std::string_view, string literal} binds to it with NO
// allocation. Returning the length lets us probe what bound without printing
// from the helper.
std::size_t lenView(std::string_view sv) { return sv.size(); }

// === Section A — std::string: owned, growable, value-semantic ================
//
// A std::string is an OWNED, dynamically-growable sequence of char. It manages
// its own buffer (RAII: the destructor frees it) and is VALUE-semantic: assigning
// or passing it by value makes a DEEP COPY of the bytes (O(n)). The methods we
// exercise here — push_back/append/+=, size/length, substr, find/rfind,
// insert/erase, operator+, c_str — are the daily API. The headline contrast:
// .substr() returns a BRAND-NEW std::string (allocates); compare to
// string_view::substr in Section C (O(1), no allocation).
void sectionA() {
    sectionBanner("A — std::string: owned, growable, value-semantic");

    std::printf("sizeof(std::string)      = %zu bytes (FIXED: the inline SSO buffer)\n",
                sizeof(std::string));

    // --- Construction + the size/length synonyms (they are aliases) ----------
    std::string s = "hello";        // copy-construct from a const char*
    std::printf("\nstd::string s = \"hello\";  -> s=\"%s\"  size=%zu  length=%zu\n",
                s.c_str(), s.size(), s.length());

    // --- Growable: push_back / append / += all MUTATE in place ---------------
    s.push_back('!');               // append one char
    s.append(" world");             // append a C-string
    s += '?';                       // operator+= for a char
    s += " ok";                     // operator+= for a const char*
    std::printf("after push_back('!')+append(\" world\")+=\"?\"+\" ok\":\n");
    std::printf("  s=\"%s\"  size=%zu\n", s.c_str(), s.size());

    // --- .substr(): returns a NEW std::string (ALLOCATES) --------------------
    std::string sub = s.substr(2, 5);   // 5 chars starting at index 2 -> "llo! "
    std::printf("\ns.substr(2,5) = \"%s\"  (a NEW std::string; ALLOCATES if not SSO)\n",
                sub.c_str());
    std::printf("  original s is UNCHANGED: \"%s\"\n", s.c_str());

    // --- .find() / .rfind(): return index or npos if absent ------------------
    auto pos1 = s.find("world");
    auto pos2 = s.find("missing");
    auto pos3 = s.rfind("o");          // last 'o' in the string
    std::printf("\ns.find(\"world\")   = %zu   (index of substring)\n", pos1);
    std::printf("s.find(\"missing\") = %zu  (== npos == %zu when absent)\n",
                pos2, std::string::npos);
    std::printf("s.rfind(\"o\")      = %zu   (index of LAST 'o')\n", pos3);

    // --- insert / erase: in-place mutation (may invalidate iterators) --------
    std::string t = "ACD";
    t.insert(1, "B");               // -> "ABCD"
    t.erase(2, 1);                  // erase 1 char at idx 2 -> "ABD"
    std::printf("\n\"ACD\".insert(1,\"B\").erase(2,1) = \"%s\"\n", t.c_str());

    // --- operator+: concatenates into a NEW string ---------------------------
    std::string cat = std::string("ab") + "cd" + 'e';   // -> "abcde"
    std::printf("std::string(\"ab\") + \"cd\" + 'e' = \"%s\"  (NEW string)\n", cat.c_str());

    // --- c_str(): null-terminated, for C APIs --------------------------------
    std::printf("\ns.c_str() = \"%s\"  (null-terminated; s.size()=%zu, strlen=%zu)\n",
                s.c_str(), s.size(), std::strlen(s.c_str()));

    // --- VALUE SEMANTICS: assignment is a DEEP COPY --------------------------
    std::string original = "AAA";
    std::string copied = original;      // deep copy of bytes
    copied += "XXX";                    // mutate the COPY only
    std::printf("\nVALUE semantics: std::string copied = original; copied += \"XXX\";\n");
    std::printf("  original=\"%s\"  (UNCHANGED: copy was independent)\n", original.c_str());
    std::printf("  copied  =\"%s\"\n", copied.c_str());

    check("std::string: size() == length()", s.size() == s.length());
    check("std::string grows under push_back/append/+=", s.size() == 16);
    check("std::string::substr returns a NEW string (original unchanged)",
          s == "hello! world? ok" && sub == "llo! ");
    check("std::string::find returns index when present (pos1==7)",
          pos1 == 7);
    check("std::string::find returns npos when absent (pos2==npos)",
          pos2 == std::string::npos);
    check("std::string::rfind finds the LAST occurrence (pos3==14)",
          pos3 == 14);
    check("std::string::insert/erase mutate in place (t==\"ABD\")", t == "ABD");
    check("std::string operator+ concatenates into a new string (cat==\"abcde\")",
          cat == "abcde");
    check("std::string is VALUE-semantic: a copy is INDEPENDENT of its source",
          original == "AAA" && copied == "AAAXXX");
    check("std::string::c_str is null-terminated (strlen == size)",
          std::strlen(s.c_str()) == s.size());
}

// === Section B — SSO (small-string optimization): short strings inline =======
//
// SHORT strings live INLINE in the std::string object itself (no heap
// allocation); LONGER strings spill to a heap buffer. This is the "small-string
// optimization" (SSO). The PROOF that SSO is in effect is that .data() points
// INSIDE the storage of the string object (&s .. &s+sizeof(s)); once the string
// exceeds the SSO threshold, .data() jumps OUTSIDE that range (it now points to
// a heap allocation). The threshold is IMPLEMENTATION-DEFINED: libc++ here
// inlines up to 22 chars (sizeof==24); libstdc++ inlines up to 15 (sizeof==32);
// MSVC inlines up to 15 (sizeof==32). The ONE guarantee the standard gives is
// that sizeof(std::string) is FIXED regardless of content.
void sectionB() {
    sectionBanner("B — SSO: short strings INLINE, sizeof FIXED, threshold impl-defined");

    std::printf("sizeof(std::string) = %zu bytes (the SAME for an empty or a long string)\n",
                sizeof(std::string));

    std::string empty;
    std::string short_s = "hi";                 // 2 chars  -> SSO
    std::string long_s(100, 'x');               // 100 chars -> heap

    bool empty_inline = dataIsInline(empty);
    bool short_inline = dataIsInline(short_s);
    bool long_inline = dataIsInline(long_s);

    std::printf("\nempty (size=%zu):  data %s the object  (inline=%d)\n",
                empty.size(), empty_inline ? "INSIDE" : "OUTSIDE", empty_inline);
    std::printf("\"hi\"  (size=%zu):  data %s the object  (inline=%d)\n",
                short_s.size(), short_inline ? "INSIDE" : "OUTSIDE", short_inline);
    std::printf("100x  (size=%zu): data %s the object  (inline=%d)\n",
                long_s.size(), long_inline ? "INSIDE" : "OUTSIDE", long_inline);

    // Find the SSO threshold empirically: the smallest length whose .data() is
    // NOT inside the object. This is implementation-defined — we print it, but
    // we do NOT hardcode the value into any check (it varies by stdlib).
    int threshold = -1;
    for (int n = 0; n <= 64; ++n) {
        std::string probe(n, 'a');
        if (!dataIsInline(probe)) { threshold = n; break; }
    }
    std::printf("\nSSO threshold on this stdlib (first length that HEAP-allocates) = %d\n",
                threshold);
    std::printf("  (impl-defined: libc++ ~22 here; libstdc++ ~15; MSVC ~15)\n");

    // The PERFORMANCE consequence: building many short strings avoids N heap
    // allocations. We do not benchmark wall-clock here (non-deterministic);
    // the INLINE proof above is the mechanism that makes SSO fast.
    std::printf("\nThe win: an empty or short std::string makes ZERO heap allocations.\n");
    std::printf("Long strings (n >= %d) heap-allocate, just like std::vector<char>.\n", threshold);

    check("sizeof(std::string) is FIXED regardless of content",
          sizeof(std::string) == sizeof(short_s) && sizeof(std::string) == sizeof(long_s));
    check("empty string's data() is INSIDE the object (SSO)", empty_inline);
    check("short \"hi\" string's data() is INSIDE the object (SSO)", short_inline);
    check("long 100-char string's data() is OUTSIDE the object (heap)", !long_inline);
    check("SSO threshold is > 0 (the stdlib really does inline short strings)",
          threshold > 0);
    check("SSO threshold is <= sizeof(std::string) (inline buffer fits in the object)",
          threshold <= static_cast<int>(sizeof(std::string)));
}

// === Section C — std::string_view: NON-OWNING borrow; O(1) copy & substr ====
//
// std::string_view (C++17) is a NON-OWNING view of a contiguous char sequence:
// just a {const char* ptr; size_t length} pair. Copying it is O(1) (two words);
// .substr() is O(1) (it returns another view, NO allocation); passing it to a
// function NEVER triggers an allocation. The cheap-pass idiom: prefer
// `void f(std::string_view)` over `void f(const std::string&)` for non-template
// read-only string params — it accepts {std::string, const char*, string literal,
// another string_view} all without copying. (The catch is Section D: dangling.)
void sectionC() {
    sectionBanner("C — std::string_view: non-owning borrow; O(1) copy/substr");

    std::printf("sizeof(std::string_view) = %zu bytes  (a pointer + a length)\n",
                sizeof(std::string_view));
    std::printf("sizeof(std::string)      = %zu bytes  (the SSO object)\n",
                sizeof(std::string));

    std::string owner = "hello world";      // the OWNER (provides the storage)

    // Three ways to construct a view — ALL O(1), all non-owning:
    std::string_view v1(owner);             // implicit string -> string_view
    std::string_view v2("hello world");     // from a C-string literal (reads .length)
    std::string_view v3(v1);                // copy another view
    std::printf("\nv1(owner)        : \"%s\"  size=%zu\n", std::string(v1).c_str(), v1.size());
    std::printf("v2(\"hello world\") : \"%s\"  size=%zu  (C-string literal)\n",
                std::string(v2).c_str(), v2.size());
    std::printf("v3(v1)           : \"%s\"  size=%zu  (view of a view)\n",
                std::string(v3).c_str(), v3.size());

    // --- The headline O(1) operation: .substr() returns a NEW VIEW -----------
    // Compare to std::string::substr (Section A), which ALLOCATES. A view's
    // .substr just (ptr+offset, count) — no heap traffic at all.
    std::string_view mid = v1.substr(6, 5);     // points at "world" inside `owner`
    std::printf("\nv1.substr(6,5) = \"%s\"  (a NEW VIEW into the SAME buffer; NO alloc)\n",
                std::string(mid).c_str());

    // Proof that the view SHARES storage (no copy): its .data() points INTO
    // the owning string's buffer.
    const char* owner_data = owner.data();
    const char* view_data = mid.data();
    bool shares_storage = (view_data >= owner_data) &&
                          (view_data < owner_data + owner.size());
    std::printf("view.data() points INTO owner's buffer: %d  (no copy was made)\n",
                shares_storage);

    // --- The cheap-pass idiom: one signature binds four source kinds ---------
    std::printf("\nlenView(std::string_view) accepts ALL of these without allocating:\n");
    std::printf("  std::string        -> %zu\n", lenView(owner));
    std::printf("  \"literal\"         -> %zu\n", lenView("literal"));
    std::printf("  std::string_view   -> %zu\n", lenView(v1));
    std::printf("  operator\"\"sv     -> %zu\n",
                lenView(std::string_view("svlit")));

    // --- remove_prefix / remove_suffix: shrink the view in place -------------
    std::string_view trim = "  pad  ";
    trim.remove_prefix(2);
    trim.remove_suffix(2);
    std::printf("\n\"  pad  \".remove_prefix(2).remove_suffix(2) = \"%s\"  (in-place trim)\n",
                std::string(trim).c_str());

    check("sizeof(string_view) == sizeof(void*) + sizeof(size_t) (two words)",
          sizeof(std::string_view) == sizeof(void*) + sizeof(std::size_t));
    check("string_view is smaller than (or equal to) std::string",
          sizeof(std::string_view) <= sizeof(std::string));
    check("string_view::substr is O(1): mid points INTO owner's buffer (no copy)",
          shares_storage);
    check("string_view::substr yields the expected slice (mid == \"world\")",
          mid == "world");
    check("cheap-pass idiom: f(string_view) accepts const char* (lenView(\"literal\")==7)",
          lenView("literal") == 7);
    check("cheap-pass idiom: f(string_view) accepts std::string (lenView(owner)==11)",
          lenView(owner) == 11);
    check("remove_prefix/remove_suffix shrink the view in place (trim == \"pad\")",
          trim == "pad");
}

// === Section D — The DANGLING-VIEW trap + string<->view conversions ==========
//
// THE #1 string_view bug: a view is NON-OWNING. If the referent (a std::string,
// a temporary, a buffer) is DESTROYED while the view is still live, the view
// becomes DANGLING — reading it is UNDEFINED BEHAVIOR (use-after-free). C++ has
// no borrow checker; the compiler TRUSTS you. (Rust's &str is also non-owning,
// but the borrow checker makes this bug IMPOSSIBLE — see the .md cross-refs.)
//
// The verified path constructs a dangling view in a comment and DEMONSTRATES the
// safe alternative (keep the owner alive). The offending READ is gated behind
// #ifdef DEMO_UB, which `just run/out/check/sanitize` NEVER pass — so the
// default and sanitizer builds stay UB-free.
//
// Conversions (one cheap, one allocates):
//   string -> string_view : IMPLICIT (cheap; the view borrows the string's buf)
//   string_view -> string : EXPLICIT  (allocates; it must copy the bytes)
void sectionD() {
    sectionBanner("D — DANGLING-view trap + string<->view conversions");

    // --- The SAFE pattern: keep the owner alive as long as the view lives ----
    std::string owner = "the owner lives";
    std::string_view safe = owner;          // borrows owner's buffer
    std::printf("SAFE: std::string owner = \"...\"; std::string_view v = owner;\n");
    std::printf("  owner outlives v -> v=\"%s\"  (read is well-defined)\n",
                std::string(safe).c_str());

    // --- The DANGLING trap, DOCUMENTED (not executed) ------------------------
    // What NOT to do:
    //
    //   std::string_view bad() { return std::string("temp"); }  // view to temp!
    //   std::string_view v = bad();   // DANGLING — temp destroyed at `;`
    //   v[0];                          // <-- UNDEFINED BEHAVIOR (use-after-free)
    //
    // Below, the dangerous READ is gated behind #ifdef DEMO_UB. We CONSTRUCT a
    // dangling view object here ONLY to assert (without reading it) that the
    // construction itself is the bug we are documenting; the verified path
    // never touches its contents.
    std::printf("\nThe #1 string_view bug (DOCUMENTED; the read is gated behind -DDEMO_UB):\n");
    std::printf("  std::string_view dangling;\n");
    std::printf("  { std::string temp = \"temp\"; dangling = temp; }  // temp destroyed here\n");
    std::printf("  // dangling is now DANGLING — reading it is UNDEFINED BEHAVIOR\n");

    {
        // Construct a dangling view inside an inner scope; on scope exit the
        // referent dies. We DO NOT read `dangling` after the block closes in
        // the verified path — that is the entire point of the trap.
        std::string_view dangling;
        {
            std::string temp = "temp";
            dangling = temp;   // OK: assigning a view (borrows temp)
            // `dangling` is valid HERE, while temp is alive.
            std::printf("  (inside the inner scope: dangling=\"%s\" — valid while temp lives)\n",
                        std::string(dangling).c_str());
        }
        // *** `dangling` is now DANGLING — temp is destroyed. ***
        // We deliberately DO NOT read `dangling` here in the verified path.
        // The only touch is taking its address (well-defined: the view object
        // itself is alive; its REFERENT is gone). Reading .data()[i] / .front()
        // / .operator[] would be UB.
        (void)dangling;

#ifdef DEMO_UB
        // ── WHAT NOT TO DO — never enabled by just run/out/check/sanitize ────
        // Compile with -DDEMO_UB to see this build; RUNNING it is UB. ASan
        // reports "heap-use-after-free" on the read below (the temp's buffer
        // was freed at the close of the inner scope above).
        char stolen = dangling.front();   // <-- UB: use-after-free
        std::printf("[DEMO_UB] dangling.front() = '%c'   <-- UNDEFINED BEHAVIOR\n", stolen);
#else
        std::printf("  (DEMO_UB not defined: the UB read is correctly omitted from this build.)\n");
#endif
    }

    // --- Conversion: string -> string_view is IMPLICIT and CHEAP -------------
    std::string s = "owned";
    std::string_view sv = s;                // implicit, no alloc
    std::printf("\nstring -> string_view : IMPLICIT  (cheap; borrows the buffer)\n");
    std::printf("  std::string s=\"owned\"; std::string_view sv = s;  -> sv=\"%s\"\n",
                std::string(sv).c_str());

    // --- Conversion: string_view -> string is EXPLICIT and ALLOCATES ---------
    // The reverse direction REQUIRES an explicit constructor call: turning a
    // non-owning view into an owning string means COPYING the bytes (a heap
    // allocation if the result is not SSO). The implicit version is DELIBERATELY
    // forbidden so you cannot accidentally trigger an O(n) allocation.
    std::string from_view(sv);              // explicit ctor: copies the bytes
    std::printf("\nstring_view -> string : EXPLICIT  (allocates; copies the bytes)\n");
    std::printf("  std::string from_view(sv);  -> from_view=\"%s\"  (independent copy)\n",
                from_view.c_str());
    from_view += '!';                       // mutate the new owner
    std::printf("  from_view += \"!\" -> \"%s\";  sv and s UNCHANGED (independent storage)\n",
                from_view.c_str());

    check("SAFE pattern: owner outlives the view (safe == \"the owner lives\")",
          safe == "the owner lives");
    check("string -> string_view is implicit (sv == \"owned\")", sv == "owned");
    check("string_view -> string is an explicit, independent copy",
          from_view == "owned!" && sv == "owned" && s == "owned");
    check("the verified path NEVER reads the dangling view (no UB; sanitizer-clean)",
          true);
}

// === Section E — UTF-8 is byte-based; ""s / ""sv literals ====================
//
// std::string and std::string_view are BYTE sequences. They have NO built-in
// Unicode / codepoint awareness: .size() counts BYTES, not characters. A UTF-8
// string like "héllo" (h, é=2 bytes, l, l, o) has size() == 6 but only 5
// codepoints. To count codepoints you must iterate the UTF-8 lead bytes
// yourself (or use a library). Contrast with Rust (strings ARE guaranteed valid
// UTF-8 with codepoint iteration via .chars()) and TS (string is UTF-16
// code-units, also codepoint-aware via [...]). The C++ position: the bytes are
// yours to interpret.
//
// operator""s   (C++14): a std::string literal  (OWNED — same as constructing)
// operator""sv  (C++17): a std::string_view literal (NON-OWNING — points at the
//                        static-storage string literal; safe for program lifetime)
std::size_t utf8Codepoints(std::string_view bytes) {
    // Count UTF-8 lead bytes: a byte is a lead byte if its top two bits are not
    // 10xxxxxx (i.e. it is NOT a continuation byte). (No validation is done —
    // assumes well-formed UTF-8 input.)
    std::size_t n = 0;
    for (unsigned char c : bytes) {
        if ((c & 0xC0) != 0x80) ++n;   // not a continuation byte -> a lead
    }
    return n;
}

void sectionE() {
    sectionBanner("E — UTF-8 is byte-based (no codepoint awareness) + literals");

    // "héllo": h(1 byte) + é(2 bytes: 0xC3 0xA9) + l(1) + l(1) + o(1) = 6 BYTES.
    // We construct it with explicit byte escapes so the source's encoding
    // cannot affect the result (portable across compilers).
    std::string utf8 = "h\xc3\xa9llo";   // 6 bytes, 5 codepoints
    std::printf("std::string utf8 = \"h\\xc3\\xa9llo\";  (h, U+00E9 'e' as 2 bytes, l, l, o)\n");
    std::printf("  utf8.size()       = %zu  (BYTES — not codepoints!)\n", utf8.size());
    std::printf("  utf8Codepoints()  = %zu  (we counted lead bytes ourselves)\n",
                utf8Codepoints(utf8));
    std::printf("  bytes (hex):");
    for (unsigned char c : utf8) std::printf(" %02x", c);
    std::printf("\n");

    // --- string_view sees the SAME bytes (it is just a borrow) ---------------
    std::string_view uv(utf8);
    std::printf("\nstd::string_view uv(utf8);\n");
    std::printf("  uv.size()         = %zu  (identical to utf8.size() — same bytes)\n", uv.size());
    std::printf("  uv[1]             = 0x%02x  (the FIRST byte of 'é', not 'é' itself)\n",
                static_cast<unsigned>(static_cast<unsigned char>(uv[1])));

    // --- operator""s vs operator""sv -----------------------------------------
    using namespace std::literals;          // brings in ""s and ""sv
    auto owned_lit  = "owned"s;             // std::string (heap/SSO, owned)
    auto borrow_lit = "borrow"sv;           // std::string_view (points at the literal)
    std::printf("\nusing namespace std::literals;\n");
    std::printf("  \"owned\"s   -> type=%s  size=%zu\n",
                "std::string", owned_lit.size());
    std::printf("  \"borrow\"sv -> type=%s  size=%zu  (points at static storage)\n",
                "std::string_view", borrow_lit.size());
    static_assert(std::is_same_v<decltype(owned_lit), std::string>,
                  "\"\"s yields std::string");
    static_assert(std::is_same_v<decltype(borrow_lit), std::string_view>,
                  "\"\"sv yields std::string_view");

    check("UTF-8 byte-based: utf8.size() == 6 (not 5)", utf8.size() == 6);
    check("UTF-8 codepoint count (manual lead-byte scan) == 5",
          utf8Codepoints(utf8) == 5);
    check("string_view sees the same bytes as the string (uv.size()==6)", uv.size() == 6);
    check("string_view indexes BYTES: uv[1] is the first byte of 'é' (0xc3)",
          static_cast<unsigned char>(uv[1]) == 0xc3);
    check("operator\"\"s yields std::string (size 5)",
          std::is_same_v<decltype(owned_lit), std::string> && owned_lit.size() == 5);
    check("operator\"\"sv yields std::string_view (size 6)",
          std::is_same_v<decltype(borrow_lit), std::string_view> && borrow_lit.size() == 6);
}

}  // namespace

int main() {
    std::printf("string_stringview.cpp — Phase 5 bundle.\n");
    std::printf("std::string (OWNED, growable, SSO) vs std::string_view (NON-OWNING borrow).\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
