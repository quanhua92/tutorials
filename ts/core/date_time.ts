// date_time.ts — Phase 5 bundle (Standard Library Essentials).
//
// GOAL (one line): show, by printing every value, that JS's Date is LEGENDARILY
// bad — months are 0-indexed (January=0), it is MUTABLE (setMonth mutates in
// place), it conflates wall-clock and monotonic time (no clean separation), its
// getters split into a LOCAL family and a UTC family (the local one depends on
// the machine TZ), and it has NO timezone object beyond UTC+offset — pinning
// each gotcha as a check()'d invariant on FIXED dates, then contrasting with
// performance.now() (a monotonic-ish high-res timer) and the Temporal proposal
// (the stage-3 modern fix).
//
// This is the GROUND TRUTH for DATE_TIME.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle exists — and why it is the cross-language headline):
// JS's Date (1995) inherited a 0-indexed month, a mutable state, and a single
// "wall-clock millisecond" model that mixes two DIFFERENT clocks — the civil
// calendar (which jumps on DST/timezone edits) and a monotonic counter (which
// never goes backwards). Go and Rust both SPLIT these cleanly: Go's `time.Time`
// carries a separate monotonic reading (Time has BOTH; Sub/Since use monotonic),
// and Rust has `Instant` (monotonic, for measuring durations) vs `SystemTime`
// (wall clock, for absolute instants). JS gave us ONE object — Date — that does
// wall clock only, mutates in place, and ships no TZ type, so every JS dev hits
// the 0-month bug, the local-vs-UTC getter bug, and the "compare with ===" bug.
// performance.now() (ES2015 / W3C High Resolution Time) is the partial fix for
// DURATIONS (a monotonic-ish timer). The Temporal proposal (stage 3) is the
// long-term fix: immutable, typed (Instant/PlainDateTime/ZonedDateTime), and
// tz-aware — but it is NOT in Node stable yet, so it is documented here, not run.
//
// DETERMINISM (THE key caveat, per HOW_TO_RESEARCH §4.2 rule 2): wall-clock "now"
// is non-reproducible. We therefore:
//   - construct EVERY date from FIXED inputs: new Date(0), new Date(isoString),
//     new Date(ms), new Date(Date.UTC(year, month, ...)). NEVER new Date() /
//     Date.now() for a printed value.
//   - assert the UTC getters (getUTCMonth/getUTCDate/...) — they are deterministic
//     in EVERY timezone. The LOCAL getters (getMonth/getDate/getHours/...) and
//     getTimezoneOffset() are machine-TZ dependent, so they are PRINTED (with a
//     note) and proved by a TZ-invariant relationship, but their absolute values
//     are NOT hard-asserted (they would break on a machine in a different TZ).
//   - the ONE machine-invariant that captures the local-vs-UTC split is asserted:
//     localMinutesOfDay ≡ utcMinutesOfDay − getTimezoneOffset() (mod 24h), which
//     holds on every machine and PROVES the two families read different clocks.
//   - performance.now() readings are NEVER printed as asserted numbers (they vary
//     run to run); only the TYPE and the MONOTONIC INCREASE (r2 > r1) is checked.
//   - Temporal is detected at runtime (present? no) — the detection is printed;
//     no Temporal API is called (it is not in Node stable).
//
// Run:
//     pnpm exec tsx date_time.ts   (or: just run date_time)

import { performance } from "node:perf_hooks";

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// ============================================================================
// Section A — Constructors + the 0-indexed-month gotcha + Date is MUTABLE
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Constructors + 0-indexed months + Date is MUTABLE");

  // The FOUR constructor forms (and the ONE forbidden form). Each is constructed
  // from FIXED inputs (never `new Date()` / Date.now() for a printed value).
  console.log("Date constructor forms (all FIXED inputs — never `new Date()`):");
  console.log(`  new Date(0)                          -> epoch ms = ${new Date(0).getTime()}`);
  console.log(`  new Date(0).toISOString()            -> ${new Date(0).toISOString()}`);
  console.log(`  new Date(1718447400000)              -> ${new Date(1718447400000).toISOString()}`);
  console.log(`  new Date("2024-06-15T10:30:00Z")      -> ${new Date("2024-06-15T10:30:00Z").toISOString()}`);
  console.log(`  Date.UTC(2024, 5, 15, 10, 30, 0)     -> epoch ms = ${Date.UTC(2024, 5, 15, 10, 30, 0)}`);
  console.log(`  new Date(Date.UTC(2024,5,15,10,30,0))-> ${new Date(Date.UTC(2024, 5, 15, 10, 30, 0)).toISOString()}`);
  console.log("  new Date()  /  Date.now()            -> FORBIDDEN here (wall-clock now is non-reproducible)");

  check("new Date(0).getTime() === 0 (epoch)", new Date(0).getTime() === 0);
  check('new Date(0).toISOString() === "1970-01-01T00:00:00.000Z"', new Date(0).toISOString() === "1970-01-01T00:00:00.000Z");
  check('new Date("2024-06-15T10:30:00Z").toISOString() === "2024-06-15T10:30:00.000Z"', new Date("2024-06-15T10:30:00Z").toISOString() === "2024-06-15T10:30:00.000Z");
  check("Date.UTC(2024,5,15,10,30,0) === 1718447400000 (ms)", Date.UTC(2024, 5, 15, 10, 30, 0) === 1718447400000);

  // ---- THE most famous JS Date gotcha: MONTHS ARE 0-INDEXED ----------------
  // The component constructor new Date(year, month, day, ...) takes month 0..11
  // where 0 = January. getMonth() / getUTCMonth() return 0..11 the same way.
  // (day/hours/minutes/seconds/ms are 1-indexed or 0-indexed-from-the-natural-
  // zero as usual; ONLY the month is shifted — the legacy of an old syscall.)
  console.log("");
  console.log("THE GOTCHA — months are 0-INDEXED (January = 0, December = 11):");
  console.log(`  new Date(2024, 0, 1)  -> getMonth() = ${new Date(2024, 0, 1).getMonth()}   (0 = JANUARY)`);
  console.log(`  new Date(2024, 5, 15) -> getMonth() = ${new Date(2024, 5, 15).getMonth()}   (5 = JUNE)`);
  console.log(`  new Date(2024, 11, 25)-> getMonth() = ${new Date(2024, 11, 25).getMonth()}  (11 = DECEMBER)`);
  console.log(`  new Date(Date.UTC(2024, 5, 15, 12, 0, 0)).getUTCMonth() = ${new Date(Date.UTC(2024, 5, 15, 12, 0, 0)).getUTCMonth()}   (5 = JUNE, via UTC)`);
  check("new Date(2024, 0, 1).getMonth() === 0 (January is month 0)", new Date(2024, 0, 1).getMonth() === 0);
  check("new Date(2024, 5, 15).getMonth() === 5 (June is month 5)", new Date(2024, 5, 15).getMonth() === 5);
  check("new Date(2024, 11, 25).getMonth() === 11 (December is month 11)", new Date(2024, 11, 25).getMonth() === 11);
  check("new Date(Date.UTC(2024,5,15,12)).getUTCMonth() === 5 (June via UTC)", new Date(Date.UTC(2024, 5, 15, 12, 0, 0)).getUTCMonth() === 5);

  // ---- Date is MUTABLE: the set*() methods mutate IN PLACE -----------------
  // Unlike essentially every other "value" type in a modern language, Date has
  // NO immutable variant: setMonth/setFullYear/setDate/.../setUTCMonth all
  // change the SAME object. Aliasing a Date and then setX-ing it is a shared-
  // mutability bug class (🔗 VALUE_VS_REFERENCE): every alias sees the change.
  console.log("");
  console.log("Date is MUTABLE — set*() mutates the SAME object (shared-mutability trap):");
  const d = new Date(Date.UTC(2024, 5, 15, 12, 0, 0));
  const alias = d; // alias SHARES d — same object, no copy
  console.log(`  d.toISOString() before setUTCMonth(0) -> ${d.toISOString()}`);
  d.setUTCMonth(0); // mutate d IN PLACE
  console.log(`  d.toISOString() after  setUTCMonth(0) -> ${d.toISOString()}`);
  console.log(`  alias.toISOString() (untouched)       -> ${alias.toISOString()}   <-- the ALIAS sees the change!`);
  check("Date is mutable: d mutated by setUTCMonth(0)", d.getUTCMonth() === 0);
  check("mutating d is visible through the alias (shared reference)", alias.getUTCMonth() === 0);
  check("d === alias (same object, no copy)", d === alias);
}

// ============================================================================
// Section B — getTime() (epoch ms) + LOCAL vs UTC getters + ISO/toString/toJSON
// ============================================================================

function sectionB(): void {
  sectionBanner("B — getTime() (epoch ms) + LOCAL vs UTC getters + toISOString/toString/toJSON");

  // A Date is, internally, a single number: milliseconds since the Unix epoch
  // (1970-01-01T00:00:00Z) in UTC. getTime() returns that number; valueOf()
  // returns the SAME number (so relational ops < > coerce Dates to their ms).
  const d = new Date(Date.UTC(2024, 5, 15, 10, 30, 0)); // 2024-06-15T10:30:00Z
  console.log(`fixed instant: new Date(Date.UTC(2024, 5, 15, 10, 30, 0))`);
  console.log(`  d.getTime()   = ${d.getTime()}   (ms since 1970-01-01T00:00:00Z)`);
  console.log(`  d.valueOf()   = ${d.valueOf()}   (SAME number; drives <,>, arithmetic)`);
  console.log(`  d.getTime() === d.valueOf() -> ${d.getTime() === d.valueOf()}`);
  check("d.getTime() === 1718447400000 (epoch ms)", d.getTime() === 1718447400000);
  check("d.getTime() === d.valueOf() (relational ops coerce to this)", d.getTime() === d.valueOf());

  // ---- THE LOCAL vs UTC split: two getter families for every field ----------
  // getFullYear/getMonth/getDate/getHours/... read LOCAL time (machine TZ).
  // getUTCFullYear/getUTCMonth/getUTCDate/getUTCHours/... read UTC (deterministic).
  // On a machine whose TZ differs from UTC, the two families return DIFFERENT
  // values for the same instant. The UTC family is deterministic everywhere;
  // the local family is machine-TZ dependent (printed here, NOT hard-asserted).
  console.log("");
  console.log("Two getter families — LOCAL (machine-TZ dependent) vs UTC (deterministic):");
  console.log(`  d.getUTCFullYear() = ${d.getUTCFullYear()}   d.getFullYear()    = ${d.getFullYear()}   (LOCAL)`);
  console.log(`  d.getUTCMonth()    = ${d.getUTCMonth()}   (June)   d.getMonth()       = ${d.getMonth()}   (LOCAL)`);
  console.log(`  d.getUTCDate()     = ${d.getUTCDate()}            d.getDate()        = ${d.getDate()}            (LOCAL)`);
  console.log(`  d.getUTCHours()    = ${d.getUTCHours()}            d.getHours()       = ${d.getHours()}            (LOCAL)`);
  console.log(`  d.getUTCMinutes()  = ${d.getUTCMinutes()}            d.getMinutes()     = ${d.getMinutes()}            (LOCAL)`);
  console.log(`  d.getTimezoneOffset() = ${d.getTimezoneOffset()}  (LOCAL offset in minutes; machine-TZ dependent)`);
  console.log("  NOTE: the LOCAL values above depend on THIS machine's timezone.");
  console.log("        The UTC values are deterministic in every timezone.");

  // The UTC getters are the SAFE pinned values (assert them — they never vary):
  check("d.getUTCFullYear() === 2024 (UTC, deterministic)", d.getUTCFullYear() === 2024);
  check("d.getUTCMonth() === 5 (June, UTC, deterministic)", d.getUTCMonth() === 5);
  check("d.getUTCDate() === 15 (UTC, deterministic)", d.getUTCDate() === 15);
  check("d.getUTCHours() === 10 (UTC, deterministic)", d.getUTCHours() === 10);
  check("d.getUTCMinutes() === 30 (UTC, deterministic)", d.getUTCMinutes() === 30);

  // The ONE machine-invariant that PROVES the local family reads a different
  // (shifted) clock than the UTC family — holds on EVERY machine:
  //   localMinutesOfDay ≡ utcMinutesOfDay − getTimezoneOffset() (mod 24h)
  const utcMinOfDay = d.getUTCHours() * 60 + d.getUTCMinutes();
  const localMinOfDay = d.getHours() * 60 + d.getMinutes();
  const offset = d.getTimezoneOffset();
  const diff = ((localMinOfDay - utcMinOfDay + offset) % 1440 + 1440) % 1440;
  console.log(`  localMinOfDay(${localMinOfDay}) − utcMinOfDay(${utcMinOfDay}) + offset(${offset}) ≡ ${diff} (mod 1440)`);
  check("local ≡ UTC − getTimezoneOffset (mod 24h) — proves the two families differ by the offset", diff === 0);
  check("typeof getTimezoneOffset() === 'number'", typeof offset === "number");

  // ---- Serialization: toISOString (UTC, ISO-8601) vs toString (local) --------
  // toISOString() ALWAYS emits UTC in the ISO-8601 format "...Z" — deterministic.
  // toString() emits a LOCAL, human-readable form — includes the machine TZ name
  // and offset, so it is machine-TZ dependent (printed, NOT asserted).
  // toJSON() returns the SAME string as toISOString() (🔗 JSON — Date serializes
  // to an ISO string and does NOT revive through JSON.parse without a reviver).
  console.log("");
  console.log("Serialization — toISOString (UTC, deterministic) vs toString (LOCAL, machine-TZ):");
  console.log(`  d.toISOString() -> ${d.toISOString()}   (ALWAYS UTC ISO-8601, ends in Z)`);
  console.log(`  d.toJSON()      -> ${d.toJSON()}   (=== toISOString; 🔗 JSON)`);
  console.log(`  d.toString()    -> ${d.toString()}   (LOCAL; machine-TZ dependent)`);
  console.log(`  d.toUTCString() -> ${d.toUTCString()}   (UTC, human form)`);
  check('d.toISOString() === "2024-06-15T10:30:00.000Z" (UTC ISO-8601)', d.toISOString() === "2024-06-15T10:30:00.000Z");
  check("d.toJSON() === d.toISOString() (Date serializes to ISO string)", d.toJSON() === d.toISOString());
  check("JSON.stringify(d) === quoted toISOString()", JSON.stringify(d) === `"${d.toISOString()}"`);
}

// ============================================================================
// Section C — Parsing (ISO reliable, non-ISO impl-dependent) + comparison + duration
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Parsing + Date comparison (getTime, NOT ==) + duration math");

  // ---- Parsing: ISO-8601 is RELIABLE; non-ISO is implementation-dependent ----
  // Date.parse(isoString) -> epoch ms. ISO-8601 (with the Z/offset) is spec'd
  // and deterministic. A date-only or non-ISO string ("06/15/2024", "June 15,
  // 2024") is implementation-dependent — engines DISAGREE on whether it is UTC
  // or local, so it is a portability trap (never rely on it across engines).
  console.log("Parsing — ISO-8601 is RELIABLE; non-ISO is implementation-dependent:");
  console.log(`  Date.parse("2024-06-15T10:30:00.000Z") -> ${Date.parse("2024-06-15T10:30:00.000Z")}`);
  console.log(`  new Date("2024-06-15T10:30:00.000Z").getTime() -> ${new Date("2024-06-15T10:30:00.000Z").getTime()}`);
  console.log(`  Date.parse("not a date") -> ${Date.parse("not a date")}   (NaN on unparseable input)`);
  console.log(`  new Date("not a date").toString() -> ${new Date("not a date")}   (Invalid Date sentinel)`);
  console.log(`  new Date("not a date").getTime() -> ${new Date("not a date").getTime()}   (NaN — detect with Number.isNaN)`);
  console.log("  WARNING: new Date('06/15/2024') and new Date('June 15, 2024') are NON-ISO and");
  console.log("  implementation-dependent (UTC vs local differs across engines) — avoid them.");
  check('Date.parse("2024-06-15T10:30:00.000Z") === 1718447400000', Date.parse("2024-06-15T10:30:00.000Z") === 1718447400000);
  check('new Date("2024-06-15T10:30:00.000Z").getTime() === 1718447400000', new Date("2024-06-15T10:30:00.000Z").getTime() === 1718447400000);
  check('Date.parse("not a date") is NaN', Number.isNaN(Date.parse("not a date")));
  check('new Date("not a date").toString() === "Invalid Date"', new Date("not a date").toString() === "Invalid Date");
  check("invalid Date.getTime() is NaN (detect with Number.isNaN, NOT ===)", Number.isNaN(new Date("not a date").getTime()));

  // ---- THE comparison trap: two Dates are === by IDENTITY, not value --------
  // `===` on objects compares references. Two distinct Date objects with the
  // SAME epoch ms are NOT === (different references). Compare with getTime()
  // (or valueOf, since relational <,>,<=,>= coerce via valueOf). This is the
  // same value-vs-reference rule from VALUES_TYPES_COERCION, applied to Date.
  console.log("");
  console.log("Comparison trap — two Dates are === by IDENTITY, not value (use getTime()):");
  const d1 = new Date(Date.UTC(2024, 5, 15, 10, 30, 0));
  const d2 = new Date(Date.UTC(2024, 5, 15, 10, 30, 0)); // SAME instant, DIFFERENT object
  console.log(`  d1.getTime() === d2.getTime() -> ${d1.getTime() === d2.getTime()}   (same VALUE)`);
  console.log(`  d1 === d2                     -> ${d1 === d2}   (IDENTITY: distinct objects)`);
  console.log(`  Object.is(d1, d2)             -> ${Object.is(d1, d2)}   (also identity)`);
  console.log(`  d1 <= d2 (relational)         -> ${d1 <= d2}   (coerces via valueOf -> epoch ms)`);
  check("d1.getTime() === d2.getTime() (compare Dates by VALUE via getTime)", d1.getTime() === d2.getTime());
  check("d1 === d2 is false (=== compares IDENTITY, not value)", (d1 === d2) === false);
  check("Object.is(d1, d2) is false (identity)", Object.is(d1, d2) === false);
  check("d1 <= d2 (relational ops coerce Date to epoch ms via valueOf)", d1 <= d2);

  // ---- Duration math: subtract two getTime() (ms), then divide --------------
  // Durations are just NUMBERS (ms). Subtract two epoch-ms readings, then divide
  // by 1000 (s) / 60000 (min) / 3600000 (h) / 86400000 (day). NEVER subtract
  // Date objects directly and trust the result type — `d2 - d1` coerces both via
  // valueOf to ms and yields a number, which works, but getTime()-getTime() is
  // the explicit, readable form.
  console.log("");
  console.log("Duration math — subtract two getTime() (epoch ms), then divide:");
  const start = new Date(Date.UTC(2024, 5, 15, 10, 0, 0)); // 10:00 UTC
  const end = new Date(Date.UTC(2024, 5, 15, 12, 0, 0)); // 12:00 UTC (2h later)
  const ms = end.getTime() - start.getTime();
  console.log(`  start = ${start.toISOString()}`);
  console.log(`  end   = ${end.toISOString()}`);
  console.log(`  end.getTime() - start.getTime() = ${ms} ms`);
  console.log(`  /1000  -> ${ms / 1000} s`);
  console.log(`  /60000 -> ${ms / 60000} min`);
  console.log(`  /3600000 -> ${ms / 3600000} h`);
  check("duration === 7200000 ms (2 hours)", ms === 7200000);
  check("duration / 3600000 === 2 (hours)", ms / 3600000 === 2);
  check("duration / 60000 === 120 (minutes)", ms / 60000 === 120);
}

// ============================================================================
// Section D — Timezones: NO TZ object, getTimezoneOffset, Intl.DateTimeFormat
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Timezones: no TZ object; getTimezoneOffset; Intl.DateTimeFormat");

  // Date has NO real timezone object. A Date is an instant (epoch ms); the ONLY
  // timezone it "knows" is the HOST machine's local zone (used by the LOCAL
  // getters) and UTC (used by the getUTC* getters + toISOString). There is no
  // way to attach an arbitrary IANA zone ("America/New_York") to a Date. The
  // two escape hatches:
  //   - getTimezoneOffset() -> the LOCAL zone's offset in minutes (machine-TZ
  //     dependent; can be non-integer where zones had :30/:45 offsets; changes
  //     across DST for zones with DST).
  //   - Intl.DateTimeFormat with a `timeZone` option -> FORMATS an instant in
  //     any IANA zone (deterministic given the zone + a fixed instant + locale).
  const d = new Date(Date.UTC(2024, 5, 15, 10, 30, 0)); // 2024-06-15T10:30:00Z
  console.log("Date has NO timezone object — only LOCAL zone + UTC. Two escape hatches:");
  console.log(`  d.getTimezoneOffset() = ${d.getTimezoneOffset()}   (LOCAL offset, minutes; machine-TZ dependent)`);
  console.log("  NOTE: this is THIS machine's offset, NOT the zone of `d` (a Date has no zone).");

  // Intl.DateTimeFormat with a FIXED timeZone renders the SAME instant in any
  // IANA zone. Given a fixed instant + fixed zone + fixed locale, the output is
  // deterministic (stable ICU data) — so it IS assertable.
  console.log("");
  console.log("Intl.DateTimeFormat with a FIXED timeZone (deterministic given instant+zone+locale):");
  const nyFull = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(d);
  const nyTime = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(d);
  const tokyoTime = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tokyo",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(d);
  console.log(`  instant (UTC): ${d.toISOString()}`);
  console.log(`  America/New_York (full): ${nyFull}`);
  console.log(`  America/New_York (time): ${nyTime}   <- 10:30 UTC = 06:30 EDT (UTC-4 in summer)`);
  console.log(`  Asia/Tokyo       (time): ${tokyoTime}   <- 10:30 UTC = 19:30 JST (UTC+9, no DST)`);
  check('Intl NY full === "Sat, Jun 15, 2024, 6:30 AM EDT"', nyFull === "Sat, Jun 15, 2024, 6:30 AM EDT");
  check('Intl NY time === "6:30 AM EDT"', nyTime === "6:30 AM EDT");
  check('Intl Tokyo time === "7:30 PM GMT+9"', tokyoTime === "7:30 PM GMT+9");

  // The SAME instant renders at DIFFERENT wall-clock times in different zones —
  // and Intl handles DST automatically (NY is EDT = UTC-4 in June; Tokyo has no
  // DST so it is JST = UTC+9 year-round). Date alone cannot do this.
  console.log("");
  console.log("The SAME instant renders at different wall-clock times per zone (Intl handles DST):");
  console.log("  Date alone CANNOT format in an arbitrary zone — Intl.DateTimeFormat is the only");
  console.log("  built-in way. (For a typed, zone-aware DATE OBJECT, see the Temporal proposal, §E.)");
  check("Intl NY (06:30) differs from Tokyo (19:30) for the same UTC instant", nyTime !== tokyoTime);
}

// ============================================================================
// Section E — performance.now() (monotonic) + Temporal preview + cross-language
// ============================================================================

function sectionE(): void {
  sectionBanner("E — performance.now() (monotonic) + Temporal preview + cross-language");

  // ---- performance.now(): a high-resolution MONOTONIC-ISH timer for DURATIONS -
  // Date measures WALL-CLOCK milliseconds since the epoch — a civil clock that
  // can jump (NTP syncs, DST, user edits, leap-second smear). It is the WRONG
  // tool for measuring a DURATION. performance.now() returns a high-resolution
  // timestamp (DOMHighResTimeStamp, ms with sub-ms fraction) whose ORIGIN is
  // process/page start and which is MONOTONIC — it never goes backwards. Use it
  // to measure durations: read it twice and subtract. NEVER use it as an
  // absolute wall-clock (it is not since the epoch) and NEVER assert its value
  // (the reading is run-dependent); only the TYPE and the monotonic INCREASE.
  const r1 = performance.now();
  // a tiny bit of work to guarantee r2 > r1 even on a fast machine
  let busy = 0;
  for (let i = 0; i < 100_000; i++) busy += i;
  const r2 = performance.now();
  const elapsed = r2 - r1;
  console.log("performance.now() — a high-resolution MONOTONIC timer for DURATIONS:");
  console.log(`  typeof performance.now() -> ${typeof r1}   (DOMHighResTimeStamp)`);
  console.log(`  reading #2 > reading #1  -> ${r2 > r1}   (monotonic: never goes backwards)`);
  console.log("  elapsed (r2 - r1)        -> a non-negative DURATION in ms (value is run-dependent; NOT printed/asserted)");
  console.log("  NOTE: the absolute readings above are RUN-dependent and are NOT asserted;");
  console.log("        only the TYPE (number) and the monotonic INCREASE (r2 > r1) are pinned.");
  // touch `busy` so noUnusedLocals is satisfied
  check("typeof performance.now() === 'number'", typeof r1 === "number");
  check("performance.now() is monotonic: r2 > r1 (after a busy loop)", r2 > r1);
  check("elapsed duration is a non-negative finite number", typeof elapsed === "number" && elapsed >= 0 && Number.isFinite(elapsed));
  check("busy-loop accumulator is a number (no dead code)", typeof busy === "number");

  // Date is the WRONG duration tool: subtracting two Dates COERCES via valueOf
  // (epoch ms) which works, but Date readings can jump on a clock change; only
  // performance.now() is monotonic. Cross-language: Go's time.Since/Now() use a
  // MONOTONIC reading stored inside the Time; Rust splits Instant (monotonic)
  // from SystemTime (wall). JS gives you Date (wall, mutable) + performance.now
  // (monotonic) as TWO SEPARATE globals with no unified type.
  console.log("");
  console.log("Why Date is the WRONG duration tool (and performance.now is the right one):");
  console.log("  - Date = wall clock (epoch ms): can JUMP on NTP/DST/user edits. Mutable. No TZ.");
  console.log("  - performance.now() = monotonic counter from process start: never goes backwards.");
  console.log("  - JS gives you TWO separate globals with NO unified type (unlike Go/Rust).");

  // ---- The Temporal proposal (stage 3): the modern fix (NOT in Node stable) -
  // Temporal is the stage-3 TC39 proposal that REPLACES Date with immutable,
  // typed, tz-aware types: Temporal.Instant (a UTC instant), Temporal.PlainDateTime
  // (a wall-clock date+time with NO zone), Temporal.ZonedDateTime (instant +
  // IANA zone + calendar), Temporal.Duration (a typed duration), etc. It fixes
  // EVERY gotcha above: months would be... still 0-indexed in PlainDate but the
  // types prevent the local/UTC confusion (PlainDateTime has no zone; Instant
  // is always UTC; ZonedDateTime carries the zone). It is NOT enabled by default
  // in Node (gated behind --harmony-temporal / a polyfill), so it is DETECTED
  // here, not called.
  const temporalPresent: boolean = "Temporal" in globalThis;
  console.log("");
  console.log("The Temporal proposal (stage 3) — the modern, immutable, typed, tz-aware fix:");
  console.log(`  "Temporal" in globalThis -> ${temporalPresent}   (NOT enabled by default in Node)`);
  console.log("  Temporal.Instant       — a UTC instant (like Date but immutable)");
  console.log("  Temporal.PlainDateTime — a wall-clock date+time with NO zone (no local/UTC trap)");
  console.log("  Temporal.ZonedDateTime — instant + IANA zone + calendar (the type Date never had)");
  console.log("  Temporal.Duration      — a typed duration (fields, not a bare ms number)");
  console.log("  (Not run here: Temporal is gated behind --harmony-temporal / a polyfill in Node.)");
  check('typeof globalThis.Temporal === "undefined" (Temporal not enabled by default in Node)', temporalPresent === false);

  // ---- The cross-language headline (printed, not executed) -----------------
  console.log("");
  console.log("Cross-language time model — who separates MONOTONIC from WALL cleanly:");
  console.log("  JS   : Date = wall (mutable, ms-since-epoch, no TZ object). performance.now =");
  console.log("         monotonic, but a SEPARATE global (no unified type). CAUTIONARY TALE.");
  console.log("  Go   : time.Time carries BOTH a wall AND a monotonic reading; time.Since/Now()");
  console.log("         use the MONOTONIC field automatically. Duration is a typed ns count. DONE RIGHT.");
  console.log("  Rust : Instant = MONOTONIC (measure durations); SystemTime = WALL (absolute instant).");
  console.log("         Two SEPARATE types — the clean split JS conflated in one Date object. DONE RIGHT.");
  console.log("  => Go and Rust cleanly separate monotonic-from-wall; JS conflated them in Date.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("date_time.ts — Phase 5 bundle (Standard Library Essentials).");
  console.log("JS's Date is LEGENDARILY bad: 0-indexed months, MUTABLE, local-vs-UTC getters,");
  console.log("no TZ object, identity-vs-value comparison. performance.now is the monotonic");
  console.log("timer; Temporal (stage 3) is the modern fix. Every value below is computed by");
  console.log("this file from FIXED dates; the .md guide pastes it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("DETERMINISM: no Date.now()/new Date() here — every date is a FIXED input. UTC");
  console.log("getters are asserted (deterministic everywhere); LOCAL getters/getTimezoneOffset");
  console.log("are machine-TZ dependent (printed + proved by a TZ-invariant, not hard-asserted).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
