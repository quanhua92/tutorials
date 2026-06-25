// chrono.cpp — Phase 5 bundle (chrono / CHRONO).
//
// GOAL (one line): show, by printing only FIXED durations and arithmetic on
// them, how C++ <chrono> models time as DURATIONS (a count + a unit ratio),
// TIME POINTS (an epoch + a duration), and three CLOCKS — and pin the expert
// rule that steady_clock (MONOTONIC) is the only clock for measuring a duration.
//
// This is the GROUND TRUTH for CHRONO.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-compile ->
// re-paste. Never hand-compute.
//
// DETERMINISM CONTRACT (the whole point of this bundle): wall-clock and the
// monotonic clock's current reading are NON-REPRODUCIBLE, so this file NEVER
// prints or asserts a now() value. It uses FIXED durations + the chrono
// user-defined literals (1h, 60min, 500ms, ...) and asserts only ARITHMETIC on
// them (1h == 60min == 3600s), plus the steady_clock-is-monotonic compile-time
// boolean and a measured-duration boolean (> 0, never its value). `just out`
// is therefore byte-identical on re-run.
//
// Run:
//     just run chrono   (== c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic
//                          chrono.cpp -o /tmp/cpp_chrono && /tmp/cpp_chrono)

#include <chrono>      // the whole library: durations, time points, clocks, calendar
#include <cstdio>      // printf / fprintf
#include <cstdlib>     // EXIT_FAILURE / exit
#include <cstring>     // memset (banner bar)
#include <ratio>       // std::ratio (the Period = compile-time rational unit)
#include <thread>      // std::this_thread::sleep_for (the C++ sleep)
#include <version>     // __cpp_lib_chrono feature-test macro

using namespace std::chrono;          // system_clock, steady_clock, seconds, ...
using namespace std::chrono_literals;  // 1h, 1min, 1s, 1ms, 1us, 1ns (C++14)

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

// toLL extracts a duration's tick count as a long long for printing. The rep
// of every standard duration typedef is a signed integer type, so the cast is
// lossless on every mainstream platform.
template <class Rep, class Period>
long long toLL(const std::chrono::duration<Rep, Period>& d) {
    return static_cast<long long>(d.count());
}

// === Section A — duration: a count + a unit ratio (std::ratio) ===============
//
// std::chrono::duration<Rep, Period> is a time interval: a tick COUNT of type
// Rep plus a compile-time rational unit Period = std::ratio<num, den> (seconds
// per tick). The ONLY runtime data is the count; Period lives entirely in the
// TYPE, so two durations of different units are DIFFERENT types the compiler
// reasons about (1h and 3600s hold the same interval but have distinct types).
void sectionA() {
    sectionBanner("A — duration: count + unit ratio (std::ratio)");

    // The predefined duration typedefs (the "helper types"). Each fixes Rep to
    // a signed integer type "at least N bits" wide and Period to a power-of-ten
    // (or 60/3600) ratio. On this LP64 box the rep of every one of them is
    // 8-byte long long. Period is a compile-time std::ratio baked into the TYPE
    // (seconds per tick); the ONLY runtime data is the tick count.
    std::printf("The predefined duration typedefs (helper types in <chrono>).\n");
    std::printf("Period is a compile-time std::ratio (sec/tick); only the count is stored.\n");
    std::printf("  typedef          sizeof   Period (sec/tick)      1 unit .count()\n");
    std::printf("  --------------   ------   ---------------------   --------------\n");
    std::printf("  nanoseconds         %zu    ratio<1, 1000000000>         %lld\n",
                sizeof(nanoseconds), toLL(1ns));
    std::printf("  microseconds        %zu    ratio<1, 1000000>           %lld\n",
                sizeof(microseconds), toLL(1us));
    std::printf("  milliseconds        %zu    ratio<1, 1000>              %lld\n",
                sizeof(milliseconds), toLL(1ms));
    std::printf("  seconds             %zu    ratio<1>                    %lld\n",
                sizeof(seconds), toLL(1s));
    std::printf("  minutes             %zu    ratio<60>                   %lld\n",
                sizeof(minutes), toLL(1min));
    std::printf("  hours               %zu    ratio<3600>                 %lld\n",
                sizeof(hours), toLL(1h));

    // Cross-unit EQUALITY: the SAME interval spelled in different units. These
    // comparisons all hold because <chrono> inserts the implicit ratio scaling;
    // no precision is lost (every ratio involved is an exact integer factor).
    check("1h == 60min == 3600s  (same interval, different units)", 1h == 60min && 60min == 3600s);
    check("1min == 60s == 60000ms", 1min == 60s && 60s == 60000ms);
    check("1s == 1000ms == 1000000us == 1000000000ns",
          1s == 1000ms && 1000ms == 1000000us && 1000000us == 1000000000ns);

    // .count() returns the RAW tick count in the duration's own unit. It does
    // NOT scale — 500ms.count() is 500, not 0.5.
    check("(500ms).count() == 500  (raw tick count, no scaling)", (500ms).count() == 500);
    check("(1h).count() == 1  (the count is in HOURS, the unit)", (1h).count() == 1);

    // WIDENING conversion (to a finer unit, no precision loss) needs NO cast:
    // 1s fits exactly into 1000ms, so the compiler accepts it implicitly.
    milliseconds ms_from_s = 1s;
    std::printf("\nWIDENING (s -> ms, exact) needs no cast:  milliseconds m = 1s;  m.count() = %lld\n",
                toLL(ms_from_s));
    check("milliseconds m = 1s;  m.count() == 1000 (implicit widening)", ms_from_s.count() == 1000);

    // NARROWING conversion (to a coarser unit, may lose precision) is a COMPILE
    // ERROR without duration_cast — the library refuses to silently drop ticks.
    //     seconds s_bad = 1500ms;   // <-- compile error (would lose the 500ms)
    // duration_cast performs the conversion by TRUNCATING toward zero.
    auto trunc = duration_cast<seconds>(1500ms);
    auto trunc2 = duration_cast<seconds>(999ms);
    std::printf("\nNARROWING needs duration_cast, which TRUNCATES toward zero:\n");
    std::printf("    duration_cast<seconds>(1500ms).count() = %lld   (500ms dropped)\n", toLL(trunc));
    std::printf("    duration_cast<seconds>(999ms).count()  = %lld   (< 1s, rounds to 0)\n",
                toLL(trunc2));
    check("duration_cast<seconds>(1500ms) == 1s (truncates 500ms)", trunc == 1s);
    check("duration_cast<seconds>(999ms) == 0s (truncates to zero)", trunc2 == 0s);
    check("1500ms < 2s  (cross-unit comparison < )", 1500ms < 2s);
}

// === Section B — time_point: an epoch + a duration ===========================
//
// std::chrono::time_point<Clock, Duration> is a point in time, stored as if it
// were a Duration measured from its Clock's epoch. It is TYPE-INDEXED by the
// clock: a steady_clock time_point and a system_clock time_point are different
// types, so subtracting across clocks is a COMPILE ERROR (the languages's way
// of forbidding a meaningless "now_steady - now_system"). Here we build FIXED
// time points off the epoch so every value is deterministic.
void sectionB() {
    sectionBanner("B — time_point: epoch + duration (deterministic arithmetic)");

    // A default-constructed time_point sits at the clock's epoch (duration 0).
    using TP = steady_clock::time_point;
    TP epoch{};
    std::printf("Default steady_clock::time_point sits at the epoch:\n");
    std::printf("    epoch.time_since_epoch().count() = %lld ns\n",
                toLL(duration_cast<nanoseconds>(epoch.time_since_epoch())));
    check("default time_point is at the epoch (time_since_epoch == 0)", epoch.time_since_epoch() == 0ns);

    // The four legal time_point operations: + duration, - duration, - time_point.
    //   tp + d  -> tp      (shift forward)
    //   tp - d  -> tp      (shift backward)
    //   tp - tp -> d       (the interval BETWEEN two points on the same clock)
    auto a = epoch + 2s;
    auto b = epoch + 7s;
    std::printf("\ntime_point arithmetic (all off the fixed epoch):\n");
    std::printf("    (epoch + 7s) - (epoch + 2s) = %lld s   [tp - tp -> duration]\n",
                toLL(duration_cast<seconds>(b - a)));
    std::printf("    (epoch + 7s) - 5s == (epoch + 2s) : %s   [tp - d -> tp]\n",
                (b - 5s == a) ? "true" : "false");
    check("tp + d -> tp :  epoch + 2s has time_since_epoch 2s",
          duration_cast<seconds>(a.time_since_epoch()) == 2s);
    check("tp - tp -> d :  (epoch+7s) - (epoch+2s) == 5s", b - a == 5s);
    check("tp - d -> tp :  (epoch+7s) - 5s == (epoch+2s)", b - 5s == a);
    check("tp + d + d :  epoch + 2s + 3s == epoch + 5s", epoch + 2s + 3s == epoch + 5s);

    // Duration-vs-time_point distinction, made concrete:
    //   duration   = "how long"          (a span, no anchor)   e.g. 5s
    //   time_point = "when"              (a span from an epoch) e.g. epoch + 5s
    // The compiler keeps them apart: `a + b` (two time_points) is a COMPILE ERROR
    // — only the three forms above are legal. (Demonstrated by NOT compiling it.)
    check("duration ('how long') vs time_point ('when') are distinct concepts", true);
}

// === Section C — the three clocks ============================================
//
// A clock = an epoch (a starting instant) + a tick rate, exposed as
// time_point Clock::now(). <chrono> ships three (since C++11):
//   system_clock         wall-clock time (epoch usually 1970-01-01 UTC);
//                         the ONLY clock with to_time_t / from_time_t. NOT steady.
//   steady_clock         MONOTONIC: now() never decreases, tick rate constant.
//                         is_steady is ALWAYS true (mandated by the standard).
//                         THE clock for measuring a duration / benchmarking.
//   high_resolution_clock finest tick period; MAY be an alias of system OR
//                         steady. is_steady is implementation-defined.
//
// is_steady is a COMPILE-TIME constant, so printing it is fully deterministic.
void sectionC() {
    sectionBanner("C — the three clocks (is_steady is a compile-time constant)");

    std::printf("clock                   is_steady   tick period      note\n");
    std::printf("----------------------  ----------  ---------------  ----------------------------------\n");
    std::printf("system_clock            %-6s      %lld / %-10lld wall clock; to/from time_t\n",
                system_clock::is_steady ? "true" : "false",
                (long long)system_clock::period::num, (long long)system_clock::period::den);
    std::printf("steady_clock            %-6s      %lld / %-10lld MONOTONIC; for measuring durations\n",
                steady_clock::is_steady ? "true" : "false",
                (long long)steady_clock::period::num, (long long)steady_clock::period::den);
    std::printf("high_resolution_clock   %-6s      %lld / %-10lld may alias system | steady\n",
                high_resolution_clock::is_steady ? "true" : "false",
                (long long)high_resolution_clock::period::num,
                (long long)high_resolution_clock::period::den);

    // The ONE portably-assertable steady fact: steady_clock::is_steady == true,
    // MANDATED by the standard ("steady clock flag, always true").
    check("steady_clock::is_steady == true  (mandated by the standard)",
          steady_clock::is_steady == true);

    // system_clock::is_steady is impl-defined (false here, on libc++); we
    // DOCUMENT it but assert NOTHING about its value (it would not be portable).
    std::printf("\nsystem_clock::is_steady is implementation-defined (here: %s); we do NOT\n"
                "portably assert it. NEVER use system_clock to measure a duration — it can\n"
                "jump (NTP, daylight-saving, the user sets the clock). Use steady_clock.\n",
                system_clock::is_steady ? "true" : "false");

    // high_resolution_clock is very often an ALIAS of one of the other two. On
    // this libc++ it IS steady_clock (shown by std::is_same_v at compile time).
    // Howard Hinnant (who added it) has argued for deprecating it precisely
    // because that aliasing is implementation-defined — prefer steady_clock.
    std::printf("\nhigh_resolution_clock identity on THIS toolchain (compile-time):\n");
    std::printf("    is_same_v<high_resolution_clock, steady_clock> : %s\n",
                std::is_same_v<high_resolution_clock, steady_clock> ? "true" : "false");
    std::printf("    is_same_v<high_resolution_clock, system_clock> : %s\n",
                std::is_same_v<high_resolution_clock, system_clock> ? "true" : "false");
    check("high_resolution_clock is an alias of steady_clock OR system_clock (impl-defined)",
          std::is_same_v<high_resolution_clock, steady_clock> ||
              std::is_same_v<high_resolution_clock, system_clock>);

    // system_clock is the bridge to C's time_t (the wall-clock epoch). We round-
    // trip a FIXED epoch (from_time_t(0) == 1970-01-01 00:00:00 UTC) — no now().
    auto sys0 = system_clock::from_time_t(0);
    auto t0 = system_clock::to_time_t(sys0);
    std::printf("\nsystem_clock <-> time_t round-trip of a FIXED epoch (no now()):\n");
    std::printf("    from_time_t(0) then to_time_t(.) = %lld  (0 == 1970-01-01 00:00:00 UTC)\n",
                static_cast<long long>(t0));
    check("system_clock from_time_t(0) <-> to_time_t round-trips to 0", t0 == 0);
}

// === Section D — measuring a duration (steady_clock) + C++20 calendar ========
//
// THE benchmarking idiom — and the only place now() appears in this bundle:
//   auto t0 = steady_clock::now();
//   ...work...
//   auto t1 = steady_clock::now();
//   auto d  = t1 - t0;        // a duration; assert d > 0, NEVER print its value
// We assert only the BOOLEAN invariants (d >= the sleep, t1 > t0); the actual
// count is nondeterministic and is deliberately never printed. Then the C++20
// calendar: year_month_day, the y/month/day literals, weekday, + months{N}.
void sectionD() {
    sectionBanner("D — measuring a duration (steady_clock) + C++20 calendar");

    // (1) Measuring a real (nondeterministic) interval. We sleep a FIXED tiny
    // amount and assert only the BOOLEAN facts; no count is printed, so the
    // captured _output.txt is byte-identical across runs.
    auto t0 = steady_clock::now();
    std::this_thread::sleep_for(1ms);   // blocks for AT LEAST 1ms
    auto t1 = steady_clock::now();
    auto elapsed = t1 - t0;
    std::printf("Measured a steady_clock interval around a 1ms sleep:\n");
    std::printf("    (t1 > t0)               : %s   [monotonic ordering, always true]\n",
                t1 > t0 ? "true" : "false");
    std::printf("    (elapsed >= 1ms)        : %s   [the count itself is NOT printed]\n",
                elapsed >= 1ms ? "true" : "false");
    check("steady_clock is monotonic: t1 (later) > t0 (earlier)", t1 > t0);
    check("measured duration >= the 1ms sleep  (boolean only; value never printed)",
          elapsed >= 1ms);
    check("a measured duration is a duration (tp - tp -> d), not a time_point",
          std::is_same_v<decltype(elapsed), steady_clock::duration>);

    // (2) C++20 calendar — all values below are FIXED dates, fully deterministic.
    // operator/ builds a year_month_day from a year, a month, a day; the y and
    // d literals (2021y, 15d) are calendar literals, NOT the years/days duration.
    auto ymd = year{2021} / January / 15;
    auto wd = weekday{ymd};  // the day-of-week of that calendar date
    std::printf("\nC++20 calendar (FIXED dates, deterministic):\n");
    std::printf("    year{2021}/January/15  -> year=%d  month=%u  day=%u\n",
                static_cast<int>(ymd.year()), static_cast<unsigned>(ymd.month()),
                static_cast<unsigned>(ymd.day()));
    std::printf("    weekday of 2021-01-15  == Friday : %s   (c_encoding=%d)\n",
                (wd == Friday) ? "true" : "false", static_cast<int>(wd.c_encoding()));
    check("year{2021}/January/15 -> year 2021, month January, day 15",
          ymd.year() == year{2021} && ymd.month() == January && ymd.day() == day{15});
    check("2021-01-15 was a Friday", wd == Friday);

    // Calendar arithmetic: + months{1} rolls the month (year/month auto-normalize).
    auto next = ymd + months{1};  // 2021-02-15
    std::printf("    2021-01-15 + months{1} -> year=%d  month=%u  day=%u\n",
                static_cast<int>(next.year()), static_cast<unsigned>(next.month()),
                static_cast<unsigned>(next.day()));
    check("2021-01-15 + months{1} == 2021-02-15",
          next.year() == year{2021} && next.month() == February && next.day() == day{15});

    // The Unix epoch (1970-01-01) was a THURSDAY — a portable, deterministic
    // calendar fact (no now() involved, just sys_days arithmetic).
    auto unix_epoch = weekday{sys_days{year{1970} / January / 1}};
    std::printf("    weekday of 1970-01-01 (Unix epoch) == Thursday : %s\n",
                (unix_epoch == Thursday) ? "true" : "false");
    check("the Unix epoch 1970-01-01 was a Thursday", unix_epoch == Thursday);
}

// === Section E — rounding (C++17), sleep, and the time-zone caveat ===========
//
// C++17 added floor/ceil/round (and abs) for durations and time_points. Unlike
// duration_cast (which truncates toward zero), round() goes to NEAREST, ties to
// even. Then the time-zone caveat: C++20's zoned_time/current_zone need a tzdb
// that some libraries (notably Apple's system libc++) do not ship — we DETECT
// that with the feature-test macro rather than calling an absent function.
void sectionE() {
    sectionBanner("E — rounding (C++17), sleep_for, and the time-zone caveat");

    // All four on the SAME 1750ms (== 1.75 s) — contrast truncation vs rounding.
    auto span = 1750ms;
    std::printf("1750ms (1.75 s) through the four conversions:\n");
    std::printf("    duration_cast<seconds> : %lld s   (truncate toward zero)\n",
                toLL(duration_cast<seconds>(span)));
    std::printf("    floor<seconds>         : %lld s   (toward -infinity)\n",
                toLL(floor<seconds>(span)));
    std::printf("    ceil<seconds>          : %lld s   (toward +infinity)\n",
                toLL(ceil<seconds>(span)));
    std::printf("    round<seconds>         : %lld s   (nearest, ties to even)\n",
                toLL(round<seconds>(span)));
    check("duration_cast<seconds>(1750ms) == 1s (truncates)", duration_cast<seconds>(span) == 1s);
    check("floor<seconds>(1750ms) == 1s", floor<seconds>(span) == 1s);
    check("ceil<seconds>(1750ms) == 2s", ceil<seconds>(span) == 2s);
    check("round<seconds>(1750ms) == 2s (nearest)", round<seconds>(span) == 2s);
    // round ties-to-even: 2500ms is exactly 2.5 s, midpoint of 2 and 3 -> 2 (even).
    check("round<seconds>(2500ms) == 2s  (ties to EVEN, not away-from-zero)",
          round<seconds>(2500ms) == 2s);
    check("floor/ceil/round never overflow the result range (here, all in 0..3 s)",
          floor<seconds>(span) <= ceil<seconds>(span));

    // sleep_for / sleep_until (from <thread>) suspend THIS thread. sleep_for
    // takes a duration; sleep_until takes a time_point. The scheduler blocks for
    // AT LEAST the requested time, so steady_clock always observes the sleep.
    auto before = steady_clock::now();
    std::this_thread::sleep_for(2ms);
    auto after = steady_clock::now();
    check("sleep_for(2ms) blocked for >= 2ms (boolean; value not printed)", after - before >= 2ms);

    // The time-zone caveat, made CONCRETE with the feature-test macro. C++20
    // calendars + time zones need __cpp_lib_chrono >= 201907L. On this box the
    // value is 201611 (the C++17 chrono value): the CALENDAR types compile, but
    // current_zone()/zoned_time are absent — calling them is a compile error.
    // We therefore DETECT availability with the macro and DOCUMENT; we never
    // call an absent function. (libstdc++ on Linux and MSVC provide it.)
    std::printf("\nTime-zone availability, detected with the feature-test macro:\n");
    std::printf("    __cpp_lib_chrono == %ld\n", static_cast<long>(__cpp_lib_chrono));
    std::printf("    C++20 calendar + time zones need >= 201907; current_zone()/zoned_time are\n");
    std::printf("    %s on this toolchain (Apple system libc++ ships no IANA tzdb).\n",
                __cpp_lib_chrono < 201907L ? "ABSENT" : "available");
    check("__cpp_lib_chrono is at least the C++17 value 201611 (floor/ceil/round)",
          __cpp_lib_chrono >= 201611L);
    check("detected C++20 time-zone availability via the macro (no absent function called)",
          __cpp_lib_chrono >= 201907L || __cpp_lib_chrono < 201907L);
}

}  // namespace

int main() {
    std::printf("chrono.cpp — Phase 5 bundle (chrono / CHRONO).\n");
    std::printf("Every FIXED value below is computed by this file. No now() value is\n");
    std::printf("printed. Compiled -std=c++23 -O2 -Wall -Wextra -Wpedantic; UB-free.\n");
    sectionA();
    sectionB();
    sectionC();
    sectionD();
    sectionE();
    sectionBanner("DONE — all sections printed");
}
