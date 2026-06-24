//go:build ignore

// time.go — Phase 5 bundle (the time package: Time, Duration, layout, clocks).
//
// GOAL (one line): show, by printing every value, how time.Time, time.Duration,
// the layout reference date, and the wall/monotonic clocks behave.
//
// This is the GROUND TRUTH for TIME.md. Every number, formatted string, and
// Duration below is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// DETERMINISM (critical for this bundle): wall-clock time is non-reproducible,
// so this file NEVER prints a time.Now() VALUE. time.Now() appears only as the
// seed of an elapsed measurement whose asserted result is a CONSTANT Duration
// (n.Add(time.Hour).Sub(n) == 1h0m0s), or as the source of a structural fact
// observable via the == vs Equal difference (a monotonic Time becomes unequal to
// its Round(0)-stripped copy). Every Format/Parse assertion uses FIXED times
// built with time.Date or time.Parse. Timer/After/Ticker sections assert that a
// CHANNEL FIRED (received) and a TICK COUNT (a constant N) — never an elapsed
// duration. Two runs of `just out time` are byte-identical.
//
// Run:
//
//	go run time.go

package main

import (
	"fmt"
	"strings"
	"time"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// sectionA shows time.Duration: it is an int64 count of NANOSECONDS. The common
// durations (Nanosecond..Hour) are constants, and they compose by ordinary
// arithmetic: 1*time.Hour == 60*time.Minute == 3600*time.Second. This is exact
// integer math (no floating point), so equality comparisons are safe.
func sectionA() {
	sectionBanner("A — Duration: an int64 nanosecond count")

	fmt.Printf("type: time.Duration = %T (underlying int64)\n", time.Duration(0))
	fmt.Printf("time.Second       = %d ns   (1e9 nanoseconds)\n", int64(time.Second))
	fmt.Printf("time.Millisecond  = %d ns\n", int64(time.Millisecond))
	fmt.Printf("time.Microsecond  = %d ns\n", int64(time.Microsecond))
	fmt.Printf("time.Nanosecond   = %d ns\n", int64(time.Nanosecond))
	fmt.Printf("time.Minute       = %d ns\n", int64(time.Minute))
	fmt.Printf("time.Hour         = %d ns\n", int64(time.Hour))

	// The constant identities: hours decompose into minutes and seconds exactly.
	fmt.Println("identity chain: 1*time.Hour == 60*time.Minute == 3600*time.Second == 3.6e12 ns")

	// Duration arithmetic is plain int64 math. Add/Sub of durations, scaling by a
	// count, and Time.Sub all yield a Duration. String() formats it readably.
	d := 2*time.Hour + 30*time.Minute + 500*time.Millisecond
	fmt.Printf("d := 2*time.Hour + 30*time.Minute + 500*time.Millisecond\n")
	fmt.Printf("  d.String()      = %q\n", d.String())
	fmt.Printf("  d.Hours()       = %v   (float64)\n", d.Hours())
	fmt.Printf("  d.Minutes()     = %v\n", d.Minutes())
	fmt.Printf("  d.Seconds()     = %v\n", d.Seconds())
	fmt.Printf("  d.Milliseconds()= %d   (int64)\n", d.Milliseconds())

	// Time arithmetic: t.Add(d) -> Time; t.Sub(u) -> Duration. On FIXED times this
	// is deterministic wall-clock arithmetic (Section E explains why fixed times
	// have no monotonic reading and so use the wall clock).
	start := time.Date(2024, 6, 15, 12, 0, 0, 0, time.UTC)
	end := start.Add(d)
	gap := end.Sub(start)
	fmt.Printf("start=Date(2024,6,15,12,0,0,0,UTC); end=start.Add(d); end.Sub(start) = %v\n", gap)

	check("Duration is int64-based", int64(time.Second) == 1_000_000_000)
	check("time.Second == 1e9 nanoseconds", time.Second == 1_000_000_000*time.Nanosecond)
	check("1*time.Hour == 60*time.Minute", 1*time.Hour == 60*time.Minute)
	check("60*time.Minute == 3600*time.Second", 60*time.Minute == 3600*time.Second)
	check("3600*time.Second == 3_600_000*time.Millisecond", 3600*time.Second == 3_600_000*time.Millisecond)
	check("end.Sub(start) equals the added duration", gap == d)
	check("d.String() == \"2h30m0.5s\"", d.String() == "2h30m0.5s")
}

// sectionB shows t.Format(layout): it renders a Time according to a layout
// string, whose tokens are the digits of the CANONICAL REFERENCE TIME
// "Mon Jan 2 15:04:05 MST 2006" (i.e. 1 2 3 4 5 6 7). The famous mnemonic.
// We build the reference instant with time.Date and format it several ways.
func sectionB() {
	sectionBanner("B — Format & the canonical reference layout")

	// The reference instant: Jan 2 15:04:05 2006, UTC. This is THE time the
	// layout tokens are taken from (month=1, day=2, hour=15, min=4, sec=5,
	// year=2006, zone offset=0 here / -7 in the canonical string).
	ref := time.Date(2006, 1, 2, 15, 4, 5, 0, time.UTC)
	fmt.Printf("ref := time.Date(2006, 1, 2, 15, 4, 5, 0, time.UTC)\n")
	fmt.Printf("  ref.Format(\"2006-01-02\")         = %q   (DateOnly)\n", ref.Format("2006-01-02"))
	fmt.Printf("  ref.Format(\"15:04:05\")           = %q   (TimeOnly)\n", ref.Format("15:04:05"))
	fmt.Printf("  ref.Format(\"2006-01-02 15:04:05\") = %q   (DateTime)\n", ref.Format("2006-01-02 15:04:05"))
	fmt.Printf("  ref.Format(time.RFC3339)         = %q\n", ref.Format(time.RFC3339))
	fmt.Printf("  ref.Format(time.UnixDate)        = %q\n", ref.Format(time.UnixDate))

	// Each layout token is a FIXED numeric value drawn from the reference date.
	// Writing your layout = writing what the reference date would look like.
	fmt.Println("token map (the reference date IS the format):")
	fmt.Println("  \"2006\"->year \"06\"->year(2)   \"01\"->month \"1\"->month")
	fmt.Println("  \"02\"->day   \"_2\"->day(sp)    \"15\"->hour(24h) \"03\"->hour(12h)")
	fmt.Println("  \"04\"->minute \"05\"->second    \"PM\"->AM/PM   \"-0700\"->zone offset")

	check("Format DateOnly exact", ref.Format("2006-01-02") == "2006-01-02")
	check("Format TimeOnly exact", ref.Format("15:04:05") == "15:04:05")
	check("Format DateTime exact", ref.Format("2006-01-02 15:04:05") == "2006-01-02 15:04:05")
	check("ref.Format(time.UnixDate) == \"Mon Jan  2 15:04:05 UTC 2006\" (_2 space-pads day)", ref.Format(time.UnixDate) == "Mon Jan  2 15:04:05 UTC 2006")
	check("predefined DateOnly == \"2006-01-02\"", time.DateOnly == "2006-01-02")
}

// sectionC shows time.Parse(layout, value) -> (Time, error): the inverse of
// Format. Parsing the reference string with the reference layout yields the
// reference instant, and Format/Parse are a clean round-trip on FIXED inputs.
func sectionC() {
	sectionBanner("C — Parse: the inverse of Format (round-trip)")

	// Round-trip a date-only string.
	t1, err1 := time.Parse("2006-01-02", "2024-06-15")
	fmt.Printf("time.Parse(\"2006-01-02\", \"2024-06-15\") -> err=%v\n", err1)
	fmt.Printf("  t1.Format(\"2006-01-02\") = %q   (round-trip)\n", t1.Format("2006-01-02"))

	// Round-trip a full RFC3339 timestamp (with zone).
	t2, err2 := time.Parse(time.RFC3339, "2024-06-15T13:45:30Z")
	fmt.Printf("time.Parse(time.RFC3339, \"2024-06-15T13:45:30Z\") -> err=%v\n", err2)
	fmt.Printf("  t2.Format(time.RFC3339) = %q\n", t2.Format(time.RFC3339))

	// Parse returns an error on a malformed value (never a panic).
	_, errBad := time.Parse("2006-01-02", "not-a-date")
	fmt.Printf("time.Parse(\"2006-01-02\", \"not-a-date\") -> err != nil? %v\n", errBad != nil)

	// Parse WITHOUT a location assumes UTC; ParseInLocation pins the zone.
	fmt.Printf("t1 in UTC? %v   (Parse with no zone parses as UTC)\n", t1.Location() == time.UTC)

	check("Parse round-trip date-only", t1.Format("2006-01-02") == "2024-06-15" && err1 == nil)
	check("Parse round-trip RFC3339", t2.Format(time.RFC3339) == "2024-06-15T13:45:30Z" && err2 == nil)
	check("Parse of garbage returns an error", errBad != nil)
	check("Parse with no location yields UTC", t1.Location() == time.UTC)
}

// sectionD drills into the layout MNEMONIC. Parsing the canonical Layout string
// "01/02 03:04:05PM '06 -0700" with ITSELF yields exactly Jan 2, 15:04:05, 2006,
// seven hours west of GMT — proving each token is a fixed numeric placeholder.
func sectionD() {
	sectionBanner("D — The layout mnemonic: 1 2 3 4 5 6 7")

	// The canonical Layout constant parses ITSELF into the reference instant.
	const layout = "01/02 03:04:05PM '06 -0700"
	ref, err := time.Parse(layout, layout)
	fmt.Printf("const layout = %q  (== time.Layout)\n", layout)
	fmt.Printf("ref, _ := time.Parse(layout, layout)  -> err=%v\n", err)
	fmt.Printf("  Year=%d  Month=%d (%v)  Day=%d\n", ref.Year(), int(ref.Month()), ref.Month(), ref.Day())
	fmt.Printf("  Hour=%d  Minute=%d  Second=%d\n", ref.Hour(), ref.Minute(), ref.Second())
	_, off := ref.Zone()
	fmt.Printf("  Zone offset = %d seconds  (== -7h? %v)\n", off, off == -7*60*60)

	// The mnemonic, pinned: each component of the reference instant is the digit
	// token used to FORMAT/PARSE that component.
	fmt.Println("mnemonic \"Mon Jan 2 15:04:05 MST 2006\":")
	fmt.Println("  month=1  day=2  hour=15(=3PM)  min=4  sec=5  year=2006(->\"06\")  zone=-07(=7)")
	fmt.Println("  i.e. the numbers 1 2 3 4 5 6 7 in order map to M D H M S Y Z.")

	check("parsed layout Year == 2006", ref.Year() == 2006)
	check("parsed layout Month == January", ref.Month() == time.January)
	check("parsed layout Day == 2", ref.Day() == 2)
	check("parsed layout Hour == 15 (3PM, 24h)", ref.Hour() == 15)
	check("parsed layout Minute == 4", ref.Minute() == 4)
	check("parsed layout Second == 5", ref.Second() == 5)
	check("parsed layout zone offset == -7h", off == -7*60*60)
	check("time.Layout == \"01/02 03:04:05PM '06 -0700\"", time.Layout == "01/02 03:04:05PM '06 -0700")
}

// sectionE is the expert core: wall clock vs monotonic clock. A Time from
// time.Now() carries BOTH a wall reading and a monotonic reading; comparisons
// and Sub on two such times use the MONOTONIC reading (immune to NTP/clock
// resets). Times from time.Parse / time.Date have NO monotonic reading, so their
// comparisons/Sub fall back to the wall clock.
//
// Determinism: we never PRINT a Now() value. We assert (1) that a fixed elapsed
// measurement via the monotonic clock is an exact constant Duration, and (2) the
// structural fact that Now()'s monotonic reading is STRIPPED by Round(0) — which
// flips the == operator (== compares the monotonic reading too) while Equal()
// still holds (Equal falls back to wall when either side lacks monotonic).
func sectionE() {
	sectionBanner("E — Wall clock vs monotonic clock (the expert core)")

	// --- fixed times: wall-only (no monotonic) --------------------------------
	// Per the docs, time.Date and time.Parse ALWAYS create times with NO
	// monotonic reading. Their comparisons/Sub therefore use the WALL clock.
	a := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	b := a.Add(24 * time.Hour)
	fmt.Printf("a := Date(2024,1,1,...,UTC); b := a.Add(24*time.Hour)\n")
	fmt.Printf("  b.Sub(a)  = %v   (wall-clock arithmetic on fixed times)\n", b.Sub(a))
	fmt.Printf("  b.After(a)= %v   a.Before(b) = %v\n", b.After(a), a.Before(b))
	// A parsed time equals its Round(0)-stripped copy under BOTH == and Equal,
	// because it never had a monotonic reading to strip.
	parsed, _ := time.Parse("2006-01-02", "2024-06-15")
	fmt.Printf("parsed time: t == t.Round(0)? %v   t.Equal(t.Round(0))? %v   (no monotonic to strip)\n",
		parsed == parsed.Round(0), parsed.Equal(parsed.Round(0)))

	// --- Now(): has a monotonic reading ---------------------------------------
	// We do NOT print n. We assert two deterministic consequences of it having a
	// monotonic reading:
	//  (1) monotonic Sub is an EXACT constant — the wall clock is irrelevant.
	//  (2) the == operator sees the monotonic reading, so stripping it (Round(0))
	//      makes n != n.Round(0), while Equal() (wall fallback) still holds.
	n := time.Now()
	elapsed := n.Add(time.Hour).Sub(n) // monotonic reading + exactly 1h
	fmt.Printf("n := time.Now()  (value NOT printed)\n")
	fmt.Printf("  n.Add(time.Hour).Sub(n) = %v   (monotonic: exact, immune to clock resets)\n", elapsed)
	fmt.Printf("  n == n.Round(0)? %v   n.Equal(n.Round(0))? %v   (Round(0) strips the monotonic reading)\n",
		n == n.Round(0), n.Equal(n.Round(0)))

	check("fixed times: b.Sub(a) == 24h (wall arithmetic)", b.Sub(a) == 24*time.Hour)
	check("fixed times: b.After(a) is true", b.After(a))
	check("parsed time has no monotonic: t == t.Round(0)", parsed == parsed.Round(0))
	check("parsed time has no monotonic: t.Equal(t.Round(0))", parsed.Equal(parsed.Round(0)))
	check("Now monotonic: Add(time.Hour).Sub(n) == 1h exactly", elapsed == time.Hour)
	check("Now has monotonic: n != n.Round(0) (== sees the reading)", n != n.Round(0))
	check("Now has monotonic: n.Equal(n.Round(0)) (same instant, wall fallback)", n.Equal(n.Round(0)))
}

// sectionF shows the channel-based time primitives: time.After (one-shot),
// time.Timer/NewTimer (one-shot, Stoppable/Resettable), and time.Ticker
// (repeating). All deliver on a channel; the discipline is to assert the channel
// FIRED (a value was received) and, for tickers, a TICK COUNT — never an elapsed
// duration (which is timing-dependent and would make output non-reproducible).
func sectionF() {
	sectionBanner("F — Timer / After / Ticker: channels over time")

	// time.After(d) returns a <-chan Time that fires ONCE after d. Equivalent to
	// NewTimer(d).C. We block on the receive and assert we got a value — we do
	// NOT print the received Time (it carries a Now() reading).
	afterCh := time.After(time.Millisecond)
	recv, ok := <-afterCh
	fmt.Printf("<-time.After(1ms): received a value? %v   (value NOT printed)\n", ok)
	_ = recv // deliberately not printed; it is a Now()-derived Time

	// time.Timer (NewTimer): one-shot, Stoppable. Stop() returns true if the
	// timer had not yet expired (releases it). Here we stop BEFORE it fires.
	tm := time.NewTimer(time.Hour)
	stopped := tm.Stop()
	fmt.Printf("NewTimer(1h).Stop() before it fires -> stopped (was active)? %v\n", stopped)

	// time.Ticker (NewTicker): REPEATING, delivers on C every d. We collect a
	// FIXED count of ticks (deterministic — the count is our constant N), then
	// Stop() it. We never print the tick Time values.
	ticker := time.NewTicker(time.Millisecond)
	const wantTicks = 5
	got := 0
	for i := 0; i < wantTicks; i++ {
		<-ticker.C // block for each tick; discard the Now()-derived Time
		got++
	}
	ticker.Stop()
	fmt.Printf("NewTicker(1ms): collected %d/%d ticks, then Stop() (tick values NOT printed)\n", got, wantTicks)

	// time.Since / time.Until are sugar over Sub/Now. Since(t) == Now().Sub(t);
	// Until(t) == t.Sub(Now()). We assert only that Stop-on-an-active timer
	// returned true (a structural fact), and the channel/count facts above.
	fmt.Println("idioms: time.Since(start) == time.Now().Sub(start); time.Until(deadline) == deadline.Sub(time.Now())")

	check("time.After channel delivered a value", ok)
	check("NewTimer.Stop() returned true (was still active)", stopped)
	check("Ticker collected exactly wantTicks ticks", got == wantTicks)
}

func main() {
	fmt.Println("time.go — Phase 5 bundle (the time package: Time, Duration, the")
	fmt.Println("layout reference date, and the wall/monotonic clocks). Every value")
	fmt.Println("below is computed by this file; the .md guide pastes it verbatim.")
	fmt.Println("Nothing is hand-computed; no time.Now() VALUE is ever printed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
