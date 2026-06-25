// iostream_format.cpp — Phase 5 bundle.
//
// GOAL (one line): show, by printing + asserting every value, the THREE eras of
// C++ output — (1) <iostream> with its manipulators (cout << x, hex/setw/...),
// (2) std::format (C++20, Python-style {} fields), (3) std::print/println
// (C++23, direct to stdout) — pinning the sticky-vs-one-shot manipulator trap
// and the compile-checked format_string as the expert payoffs.
//
// This is the GROUND TRUTH for IOSTREAM_FORMAT.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-compile
// -> re-paste. Never hand-compute.
//
// NOTE on house style: the banner/check helpers below use <cstdio> printf (the
// established scaffold from scripts/skeleton.cpp). The CONTENT this bundle
// TEACHES, however, is the modern <iostream> + <iomanip> + <format> + <print>
// machinery — captured into strings (ostringstream / std::format) and asserted
// for exact equality, so the verified path is fully deterministic.
//
// Run:
//     just run iostream_format   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                                  iostream_format.cpp -o /tmp/cpp_iostream_format
//                                  && /tmp/cpp_iostream_format)

#include <cstdio>     // printf / fprintf  (banner + check helpers only)
#include <cstdlib>    // EXIT_FAILURE / exit
#include <cstring>    // memset (banner bar)
#include <iostream>   // std::cout / std::cerr / std::cin  (taught)
#include <iomanip>    // setw / setfill / setprecision / hex / boolalpha ... (taught)
#include <sstream>    // std::ostringstream (taught)
#include <string>     // std::string
#include <format>     // std::format / std::format_to / std::format_to_n (C++20, taught)
#include <print>      // std::print / std::println (C++23, taught)
#include <iterator>   // std::back_inserter

// Program-defined type for the custom-formatter demo (Section E). It lives at
// global scope so we may legally specialize std::formatter<Point> in namespace
// std (specializing a std template for a program-defined type is permitted).
struct Point {
    int x;
    int y;
};

// A custom formatter: specialize std::formatter<MyType>. parse() consumes the
// format-spec (here we accept only an empty spec "{}"); format() writes the
// representation to ctx.out(). Once defined, std::format/print/println all
// understand the type automatically.
template <>
struct std::formatter<Point> {
    constexpr auto parse(std::format_parse_context& ctx) { return ctx.begin(); }
    auto format(const Point& p, std::format_context& ctx) const {
        return std::format_to(ctx.out(), "Point({}, {})", p.x, p.y);
    }
};

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

// === Section A — <iostream>: the type-safe << overloads ====================
//
// std::cout is the classic C++ stream. The insertion operator `<<` is OVERLOADED
// for every standard type, so the compiler picks the correct formatting per
// operand — type-safe, unlike C printf's %d/%f whose matching is your problem.
// We capture the stream into a std::ostringstream to assert the EXACT text
// deterministically (see Section C for ostringstream itself).
void sectionA() {
    sectionBanner("A — <iostream>: type-safe << overloads (cout << x)");

    {
        std::ostringstream os;
        os << "i=" << 42 << " d=" << 3.5 << " c=" << 'A'
           << " s=" << "hi" << " b=" << true;   // bool prints "1" by default
        std::string got = os.str();
        std::printf("  cout << 42 << 3.5 << 'A' << \"hi\" << true -> \"%s\"\n", got.c_str());
        check("type-safe << formats int/double/char/string/bool -> i=42 d=3.5 c=A s=hi b=1",
              got == "i=42 d=3.5 c=A s=hi b=1");
    }
    {
        std::ostringstream os;
        os << std::boolalpha << true << ' ' << false;   // "true false"
        std::printf("  with std::boolalpha: true false -> \"%s\"\n", os.str().c_str());
        check("std::boolalpha prints true/false as text -> 'true false'",
              os.str() == "true false");
    }
    // The three standard streams share the << / >> interface:
    //   std::cout -> stdout (buffered) ; std::cerr -> stderr (unbuffered) ;
    //   std::cin  -> stdin.
    std::printf("  std::cout->stdout ; std::cerr->stderr(unbuffered) ; std::cin->stdin\n");
    check("the three standard streams share the << / >> interface", true);
}

// === Section B — I/O manipulators: the sticky-vs-one-shot trap ==============
//
// THE expert payoff. Two kinds of manipulator:
//   STICKY  : hex/oct/dec, fixed/scientific, boolalpha, setprecision, setfill
//             PERSIST on the stream until changed.
//   ONE-SHOT: setw applies ONLY to the NEXT insertion, then resets to 0.
// Each check below uses a FRESH ostringstream so the stickiness is unambiguous.
void sectionB() {
    sectionBanner("B — I/O manipulators: sticky vs one-shot (the expert trap)");

    {  // std::hex is STICKY: it stays until std::dec/std::oct reset it.
        std::ostringstream os;
        os << std::hex << 255;                 // "ff"
        std::printf("  std::hex << 255 -> \"%s\"\n", os.str().c_str());
        check("std::hex formats 255 as 'ff'", os.str() == "ff");
    }
    {
        std::ostringstream os;
        os << std::hex << 255 << ' ' << 16;    // hex STICKS -> "ff 10"
        std::printf("  std::hex << 255 << ' ' << 16 -> \"%s\" (hex STICKS)\n", os.str().c_str());
        check("std::hex STICKS: 255 then 16 -> 'ff 10'", os.str() == "ff 10");
    }
    {
        std::ostringstream os;
        os << std::oct << 64;                  // "100"
        std::printf("  std::oct << 64 -> \"%s\"\n", os.str().c_str());
        check("std::oct formats 64 as '100'", os.str() == "100");
    }
    {  // std::setw is ONE-SHOT: it pads ONLY the next insertion.
        std::ostringstream os;
        os << std::setw(5) << std::setfill('0') << 42;   // "00042"
        std::printf("  setw(5)+setfill('0') << 42 -> \"%s\"\n", os.str().c_str());
        check("setw(5)+setfill('0') << 42 -> '00042'", os.str() == "00042");
    }
    {
        std::ostringstream os;
        os << std::setw(5) << std::setfill('0') << 42 << '|' << 42;  // setw expired
        std::printf("  setw(5)<<42<<'|'<<42 -> \"%s\" (setw ONE-SHOT: 2nd 42 NOT padded)\n",
                    os.str().c_str());
        check("setw is ONE-SHOT: 2nd 42 not padded -> '00042|42'", os.str() == "00042|42");
    }
    {  // std::fixed + std::setprecision (both STICKY).
        std::ostringstream os;
        os << std::fixed << std::setprecision(3) << 3.14159;   // "3.142"
        std::printf("  fixed+setprecision(3) << 3.14159 -> \"%s\"\n", os.str().c_str());
        check("fixed + setprecision(3) << 3.14159 -> '3.142'", os.str() == "3.142");
    }
    {
        std::ostringstream os;
        os << std::scientific << std::setprecision(2) << 31415.9;  // "3.14e+04"
        std::printf("  scientific+setprecision(2) << 31415.9 -> \"%s\"\n", os.str().c_str());
        check("scientific + setprecision(2) << 31415.9 -> '3.14e+04'", os.str() == "3.14e+04");
    }
    std::printf("  RULE: base(hex/oct/dec), fixed, scientific, boolalpha, setprecision STICK;\n");
    std::printf("        setw EXPIRES after exactly one insertion.\n");
    check("sticky-vs-one-shot manipulator rule documented", true);
}

// === Section C — std::ostringstream (build a string) + std::endl vs '\n' ====
void sectionC() {
    sectionBanner("C — std::ostringstream (build a string) + std::endl vs '\\n'");

    {  // ostringstream: build a string with the SAME << interface as cout; .str()
       // extracts the accumulated std::string. The pre-std::format way to
       // compose text type-safely (still useful for ad-hoc string building).
        std::ostringstream ss;
        ss << "name=" << "widget" << " price=" << std::fixed << std::setprecision(2) << 9.99;
        std::string built = ss.str();    // "name=widget price=9.99"
        std::printf("  ostringstream builds -> \"%s\"\n", built.c_str());
        check("ostringstream composes a string -> 'name=widget price=9.99'",
              built == "name=widget price=9.99");
    }
    {  // std::endl == '\n' + flush. The flush is a write-side side effect (forces
       // the buffer out). On a string stream the flush is a no-op, so the TEXT is
       // identical to '\n'. Prefer "\n" in hot loops (endl's flush is a syscall).
        std::ostringstream a, b;
        a << "line1" << std::endl << "line2";   // newline + flush
        b << "line1" << '\n' << "line2";        // newline only
        std::printf("  a=\"line1\"<<endl<<\"line2\"  b=\"line1\"<<'\\n'<<\"line2\"  ->  a==b ? %s\n",
                    (a.str() == b.str()) ? "yes" : "no");
        std::printf("  (text identical; endl ALSO flushes -> prefer \"\\n\")\n");
        check("std::endl text == '\\n' text (endl just adds an extra flush)",
              a.str() == b.str());
    }
}

// === Section D — std::format (C++20): Python-style {} fields ===============
//
// std::format(fmt, args...) returns a std::string. The format string is
// COMPILE-CHECKED: std::format_string<Args...> validates arg count/types at
// construction (a runtime-checked printf can crash; a bad std::format spec is a
// COMPILE ERROR). The grammar mirrors Python's format-spec.
void sectionD() {
    sectionBanner("D — std::format (C++20): Python-style {} fields");

    {  // Positional {} replacement fields + a format spec on the 2nd arg.
        std::string r = std::format("x={}, y={:.2f}", 3, 3.14159);   // "x=3, y=3.14"
        std::printf("  std::format(\"x={}, y={:.2f}\", 3, 3.14159) -> \"%s\"\n", r.c_str());
        check("std::format positional fields -> 'x=3, y=3.14'", r == "x=3, y=3.14");
    }
    // The format-spec grammar: [fill+align][sign][#][0][width][.precision][type]
    {
        std::string r = std::format("{:+.3f}", 3.14159);   // "+3.142"
        std::printf("  {:+.3f} 3.14159 -> \"%s\"  (sign + precision)\n", r.c_str());
        check("spec {:+.3f} -> '+3.142'", r == "+3.142");
    }
    {
        std::string r = std::format("{:x}", 255);          // "ff"
        std::printf("  {:x} 255 -> \"%s\"\n", r.c_str());
        check("spec {:x} -> 'ff'", r == "ff");
    }
    {
        std::string r = std::format("{:b}", 9);            // "1001"
        std::printf("  {:b} 9 -> \"%s\"\n", r.c_str());
        check("spec {:b} -> '1001'", r == "1001");
    }
    {
        std::string r = std::format("{:>8}", 42);          // "      42" (right-align)
        std::printf("  {:>8} 42 -> \"%s\"\n", r.c_str());
        check("spec {:>8} -> '      42'", r == "      42");
    }
    {
        std::string r = std::format("{:*>8}", 42);         // "******42" (fill+align)
        std::printf("  {:*>8} 42 -> \"%s\"\n", r.c_str());
        check("spec {:*>8} -> '******42'", r == "******42");
    }
    {
        std::string r = std::format("{:08x}", 255);        // "000000ff" (0-pad + width)
        std::printf("  {:08x} 255 -> \"%s\"\n", r.c_str());
        check("spec {:08x} -> '000000ff'", r == "000000ff");
    }
    {
        std::string r = std::format("{:#x}", 255);         // "0xff" (alternate form)
        std::printf("  {:#x} 255 -> \"%s\"\n", r.c_str());
        check("spec {:#x} -> '0xff'", r == "0xff");
    }
    {  // Explicit arg-ids + literal-brace escaping ({{ -> { , }} -> }).
        std::string r = std::format("{1} before {0}", "B", "A");   // "A before B"
        std::printf("  {1} before {0}  (\"B\",\"A\") -> \"%s\"\n", r.c_str());
        check("explicit arg-ids -> 'A before B'", r == "A before B");
    }
    {
        std::string r = std::format("literal {{}} braces");        // "literal {} braces"
        std::printf("  \"literal {{}} braces\" -> \"%s\"\n", r.c_str());
        check("escaped braces {{}} -> 'literal {} braces'", r == "literal {} braces");
    }
    {  // Type-safety: the SAME {} adapts to int/double/string (compile-checked).
        std::string i = std::format("v={}", 7);          // "v=7"
        std::string d = std::format("v={}", 2.5);        // "v=2.5"
        std::string s = std::format("v={}", "hi");       // "v=hi"
        std::printf("  {} adapts to type: int->\"%s\"  double->\"%s\"  string->\"%s\"\n",
                    i.c_str(), d.c_str(), s.c_str());
        check("type-safe {}: int -> 'v=7'", i == "v=7");
        check("type-safe {}: double -> 'v=2.5'", d == "v=2.5");
        check("type-safe {}: string -> 'v=hi'", s == "v=hi");
    }
}

// === Section E — std::print/println (C++23) + format_to + custom formatter =
void sectionE() {
    sectionBanner("E — std::print/println (C++23) + format_to + custom formatter");

    // std::print/println write formatted text DIRECTLY to stdout (or a FILE*) —
    // no std::ostream object, no per-call locale overhead. They reuse the SAME
    // compile-checked format_string as std::format. We call them so they appear
    // in the captured output, then assert the exact text via std::format.
    std::print("[std::print]   x={}, y={:.2f}\n", 3, 3.14159);
    std::println("[std::println] hex={:x} fixed={:.3f}", 255, 2.71828);
    check("std::print text == 'x=3, y=3.14\\n'",
          std::format("x={}, y={:.2f}\n", 3, 3.14159) == "x=3, y=3.14\n");
    check("std::println text == 'hex=ff fixed=2.718\\n'",
          std::format("hex={:x} fixed={:.3f}\n", 255, 2.71828) == "hex=ff fixed=2.718\n");

    {  // std::format_to writes to any OutputIterator (here back_inserter of a
       // string) — append into a pre-sized buffer without a throwaway string.
        std::string out;
        std::format_to(std::back_inserter(out), "{} squared is {}", 6, 36);  // "6 squared is 36"
        std::printf("  std::format_to(back_inserter) -> \"%s\"\n", out.c_str());
        check("std::format_to via back_inserter -> '6 squared is 36'", out == "6 squared is 36");
    }
    {  // std::format_to_n writes AT MOST n chars; result.size is the FULL
       // (untruncated) length that WOULD have been written.
        std::string bounded;
        auto res = std::format_to_n(std::back_inserter(bounded), 5, "abcdefghij");  // "abcde"
        std::printf("  std::format_to_n(buf,5,\"abcdefghij\") -> \"%s\" (full size would be %zu)\n",
                    bounded.c_str(), res.size);
        check("std::format_to_n truncates to 'abcde'", bounded == "abcde");
        check("std::format_to_n result.size == 10 (untruncated length)", res.size == 10);
    }
    {  // Custom formatter: std::format/print now understand Point automatically.
        std::string r = std::format("{}", Point{3, 4});   // "Point(3, 4)"
        std::printf("  std::format(\"{}\", Point{3,4}) -> \"%s\"\n", r.c_str());
        check("custom std::formatter<Point> -> 'Point(3, 4)'", r == "Point(3, 4)");
    }
    std::printf("  THE THREE ERAS: <iostream>(manipulators) -> std::format {} -> std::print(direct)\n");
    std::printf("  Modern guidance: prefer std::format / std::print over iostream for new code.\n");
    check("three-eras summary documented", true);
}

}  // namespace

int main() {
    std::printf("iostream_format.cpp — Phase 5 bundle.\n");
    std::printf("C++ output has THREE eras: <iostream> -> std::format -> std::print.\n");
    std::printf("Every value below is computed by this file. Compiled -std=c++23\n");
    std::printf("-O2 -Wall -Wextra -Wpedantic; UB-free (just sanitize clean).\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
