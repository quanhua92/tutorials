// regex.ts — Phase 5 bundle (Standard Library Essentials).
//
// GOAL (one line): show, by printing every value, how JS's BACKTRACKING RegExp
// engine parses, matches, captures, and replaces — pinning every flag (g/i/m/
// s/u/y/d), named groups, lookahead/lookbehind, backreferences, the stateful
// exec+lastIndex loop, Unicode property escapes (u + v flags), and the
// catastrophic-backtracking (ReDoS) RISK that RE2-based engines (Go/Rust)
// eliminate by design.
//
// This is the GROUND TRUTH for REGEX.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle is the standard-library headline): JavaScript's
// RegExp is a BACKTRACKING engine (PCRE-ish): it explores one path through the
// pattern and, on failure, backs up and tries the next. That gives it
// expressiveness RE2 cannot match — backreferences (\1), lookahead/lookbehind
// (zero-width assertions), and capture groups — at the cost of a worst-case
// EXPONENTIAL time. Craft an input that triggers catastrophic backtracking and
// you have a ReDoS (Regular-expression Denial of Service). Go and Rust made the
// opposite choice: their stdlib regexes (RE2) match in LINEAR time and REFUSE
// backreferences/lookbehind entirely. JS is the outlier — power at the cost of
// safety. The whole bundle is the case study for that trade-off.
//
// Run:
//     pnpm exec tsx regex.ts   (or: just run regex)
//
// DETERMINISM NOTE: regex MATCH RESULTS are deterministic (asserted exact).
// The catastrophic-backtracking section (E) is DOCUMENTED SAFELY: the evil
// pattern is run only on TINY inputs (instant), and the exponential growth is
// shown via the THEORETICAL partition count 2^(n-1) (pure math), never by
// running a pathologically-long input (which would hang the sweep). See §E.

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

// fmtArr renders an exec/match result as a JSON array of its captures (or
// "null"), WITHOUT relying on object key order. RegExpExecArray is array-like;
// Array.from copies the captured strings into a plain string[].
function fmtArr(m: RegExpExecArray | RegExpMatchArray | null): string {
  if (m === null) return "null";
  return JSON.stringify(Array.from(m));
}

// ============================================================================
// Section A — Literal vs constructor, the 7 flags, and the method surface
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Literal vs constructor, the 7 flags, and the method surface");

  // A RegExp literal /pattern/flags is parsed ONCE at compile time. The
  // constructor new RegExp("pattern","flags") parses at RUNTIME from strings —
  // essential when the pattern comes from user input / a config value, but it
  // means you MUST escape regex metacharacters (see §C escapeRegExp) and that
  // backslashes in the pattern string must be DOUBLED ("\d" -> "\\d").
  const literal = /\d{4}-\d{2}/;
  const ctor = new RegExp("\\d{4}-\\d{2}");
  console.log("literal source:", literal.source, " flags:", JSON.stringify(literal.flags));
  console.log("ctor    source:", ctor.source, " flags:", JSON.stringify(ctor.flags));
  check("literal and constructor match the same input", literal.test("2024-06") && ctor.test("2024-06"));
  check("literal source === ctor source", literal.source === ctor.source);

  // The 7 flags (ECMA-262 / MDN). Each changes match SEMANTICS, not the pattern.
  //   g  global          — match all (not just the first); sets up lastIndex
  //   i  ignoreCase      — case-insensitive (uses Unicode default case folding)
  //   m  multiline       — ^ / $ match at each line boundary, not just ends
  //   s  dotAll          — . matches ANY char INCLUDING line terminators (\n)
  //   u  unicode         — unicode mode: correct surrogate handling + \p{}
  //   y  sticky          — match anchored at lastIndex exactly (no skipping)
  //   d  hasIndices      — expose start/end pairs via .indices on the match
  console.log("");
  console.log("Flag effects (each is a check'd invariant):");
  console.log(`  /abc/i      .test("ABC")     -> ${/abc/i.test("ABC")}        (i: case-insensitive)`);
  console.log(`  /^bar$/m    .test("foo\\nbar")-> ${/^bar$/m.test("foo\nbar")}       (m: ^/$ at line bounds)`);
  console.log(`  /^bar$/     .test("foo\\nbar")-> ${/^bar$/.test("foo\nbar")}       (no m: ^/$ only at ends)`);
  console.log(`  /a.b/s      .test("a\\nb")    -> ${/a.b/s.test("a\nb")}        (s: . matches \\n)`);
  console.log(`  /a.b/       .test("a\\nb")    -> ${/a.b/.test("a\nb")}       (no s: . does NOT match \\n)`);
  check("/abc/i is case-insensitive", /abc/i.test("ABC") === true);
  check("m makes ^ match at each line boundary", /^bar$/m.test("foo\nbar") === true);
  check("without m, ^ matches only at the very start", /^bar$/.test("foo\nbar") === false);
  check("s (dotAll): . matches \\n", /a.b/s.test("a\nb") === true);
  check("without s: . does NOT match \\n", /a.b/.test("a\nb") === false);

  // The full flag set, read back from a constructed regex (flags string is
  // always sorted canonically: gim... ). Order in the literal does not matter.
  console.log("");
  console.log("flags are normalized (sorted) regardless of literal order:");
  console.log(`  /x/igy.flags  -> ${JSON.stringify(/x/igy.flags)}`);
  console.log(`  /x/yig.flags  -> ${JSON.stringify(/x/yig.flags)}   (same as above)`);
  check("flags are always sorted canonically", /x/yig.flags === /x/igy.flags);

  // --- String methods vs RegExp methods: the full surface -------------------
  //  String.prototype:  match, matchAll, replace, replaceAll, search, split
  //  RegExp.prototype:  test, exec
  console.log("");
  console.log("String methods vs RegExp methods:");
  console.log(`  match  (no g) -> ${fmtArr("2024-06".match(/(\d{4})-(\d{2})/))}   (full match + captures)`);
  console.log(`  match  (g)    -> ${JSON.stringify("a1 b2".match(/(\w)(\d)/g))}        (g: strings only, groups LOST)`);
  console.log(`  search        -> ${"hello world".search(/\bw/)}   (index of first match, or -1)`);
  console.log(`  split        -> ${JSON.stringify("a,b,,c".split(/,/))}        (regex as separator)`);
  console.log(`  replace      -> ${JSON.stringify("a-a".replace(/-/g, "_"))}        (replace all with g)`);
  console.log(`  replaceAll   -> ${JSON.stringify("a-a-a".replaceAll("-", "_"))}        (replaceAll REQUIRES a global pattern)`);
  console.log(`  test         -> ${/\d/.test("a1b")}   (boolean)`);
  console.log(`  exec         -> ${fmtArr(/\d+/.exec("abc 123"))}   (match array or null)`);
  check("match (no g) returns [full, g1, g2, ...]", "2024-06".match(/(\d{4})-(\d{2})/)?.[2] === "06");
  check("match (g) returns only the full matches (groups lost)", JSON.stringify("a1 b2".match(/(\w)(\d)/g)) === JSON.stringify(["a1", "b2"]));
  check("search returns the match index", "hello world".search(/\bw/) === 6);
  check("split with regex keeps empty fields", JSON.stringify("a,b,,c".split(/,/)) === JSON.stringify(["a", "b", "", "c"]));
  check("exec returns the first match (captured)", fmtArr(/\d+/.exec("abc 123")) === JSON.stringify(["123"]));
}

// ============================================================================
// Section B — Named groups, lookahead/lookbehind, backreferences
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Named groups, lookahead/lookbehind, backreferences");

  // Named capture groups (?<name>...) — ES2018. Accessed via match.groups.name.
  // Far more readable than positional [1], [2], and self-documenting.
  const named = /(?<year>\d{4})-(?<month>\d{2})/.exec("2024-06");
  const groups = named?.groups;
  console.log("named exec:", fmtArr(named));
  console.log(`  groups.year  = ${groups?.year}`);
  console.log(`  groups.month = ${groups?.month}`);
  check("named group year === '2024'", groups?.year === "2024");
  check("named group month === '06'", groups?.month === "06");
  check("named group also available positionally", named?.[1] === "2024");

  // Lookahead (?=...) and negative lookahead (?!...): ZERO-WIDTH — they assert
  // without consuming input. lastIndex/index do not advance past them.
  const ahead = /(\d+)(?= dollars)/.exec("cost 50 dollars");
  console.log("");
  console.log(`lookahead (?= dollars): ${fmtArr(ahead)}   (' dollars' NOT captured)`);
  console.log(`  negative (?!bar) on 'foobar': ${fmtArr(/foo(?!bar)/.exec("foobar"))}`);
  console.log(`  negative (?!bar) on 'foobaz': ${fmtArr(/foo(?!bar)/.exec("foobaz"))}`);
  check("lookahead asserts without consuming", ahead?.[0] === "50" && ahead?.[1] === "50");
  check("negative lookahead rejects 'foobar'", /foo(?!bar)/.exec("foobar") === null);
  check("negative lookahead accepts 'foobaz'", /foo(?!bar)/.exec("foobaz")?.[0] === "foo");

  // Lookbehind (?<=...) and negative lookbehind (?<!...) — ES2018. Also
  // zero-width, but anchored on the LEFT of the match.
  const lb = "$100 and $200".match(/(?<=\$)\d+/g);
  const nlb = "price 9 $10".match(/(?<!\$)\d+/g);
  console.log("");
  console.log(`lookbehind (?<=\\$) on '$100 and $200': ${JSON.stringify(lb)}   (digits after each $)`);
  console.log(`  negative (?<!\\$) on 'price 9 $10': ${JSON.stringify(nlb)}   (9 AND a leaked '0'!)`);
  console.log("    note: '10' is rejected (its '1' IS after $), but the '0' alone");
  console.log("    is preceded by '1' (not $), so it matches — lookbehind subtlety.");
  check("lookbehind matches digits after each $", JSON.stringify(lb) === JSON.stringify(["100", "200"]));
  check("negative lookbehind matches '9' and the leaked '0'", JSON.stringify(nlb) === JSON.stringify(["9", "0"]));

  // Backreference \1 — matches the EXACT text captured by group 1. The feature
  // that makes JS regex a BACKTRACKING engine: matching \1 requires remembering
  // what group 1 captured, which an NFA-only (RE2) engine cannot express.
  const backref = /(\w+)\s\1/.exec("hello hello");
  console.log("");
  console.log(`backreference \\1 on 'hello hello': ${fmtArr(backref)}   (\\1 repeats group 1)`);
  console.log(`backreference \\1 on 'hello world': ${fmtArr(/(\w+)\s\1/.exec("hello world"))}   (no repeat -> no match)`);
  check("backreference matches the repeated word", backref?.[0] === "hello hello" && backref?.[1] === "hello");
  check("backreference fails when the word is not repeated", /(\w+)\s\1/.exec("hello world") === null);

  // \1 compiles fine in JS. (In Go/Rust's RE2 this is a COMPILE ERROR — the
  // starkest cross-language contrast; see §E and the cross-refs in the .md.)
  check("backreference compiles in JS (RE2 would REJECT it)", /(\w)\1/.test("aa") === true);
}

// ============================================================================
// Section C — exec + the stateful lastIndex loop, replace-with-function, escapeRegExp
// ============================================================================

function sectionC(): void {
  sectionBanner("C — exec + the stateful lastIndex loop, replace-with-function, escapeRegExp");

  // exec + g flag = STATEFUL. A global RegExp carries a mutable lastIndex that
  // exec() advances after each match, so the canonical "find all" loop is:
  //     let m; while ((m = re.exec(s)) !== null) { ... }
  // The loop TERMINATES because exec returns null after the last match AND
  // resets lastIndex to 0. This statefulness is also the source of the famous
  // test()/exec() trap below.
  const re = /\d/g;
  const found: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec("a1b2c3")) !== null) {
    found.push(m[0]);
  }
  console.log(`exec+g loop over 'a1b2c3': ${JSON.stringify(found)}   (lastIndex reset to ${re.lastIndex})`);
  check("exec+g loop collects every digit", JSON.stringify(found) === JSON.stringify(["1", "2", "3"]));
  check("exec+g resets lastIndex to 0 after exhausting", re.lastIndex === 0);

  // THE TRAP: reusing a global RegExp across test() (or exec()) calls keeps
  // lastIndex, so alternating true/false on the SAME string is correct JS
  // semantics but almost always a bug.
  const g = /\d/g;
  const t1 = g.test("1a");
  const after1 = g.lastIndex;
  const t2 = g.test("1a");
  const after2 = g.lastIndex;
  console.log("");
  console.log("THE TRAP — reusing a global regex in test():");
  console.log(`  test #1 on '1a': ${t1}   (lastIndex -> ${after1})`);
  console.log(`  test #2 on '1a': ${t2}  (lastIndex -> ${after2})  <-- alternates!`);
  check("global test() is stateful: #1 true", t1 === true);
  check("global test() is stateful: #2 false (lastIndex moved past)", t2 === false);

  // matchAll (ES2020) is the SAFE, stateless replacement for the exec loop: it
  // returns an ITERATOR of RegExpMatchArray and does NOT mutate lastIndex.
  // It REQUIRES the g flag (throws otherwise).
  const all = [..."2024-06 and 2025-01".matchAll(/(?<y>\d{4})-(?<mo>\d{2})/g)];
  console.log("");
  console.log(`matchAll (stateless, g required): ${all.length} matches`);
  console.log(`  [0]: ${all[0]![0]} year=${all[0]!.groups!.y} month=${all[0]!.groups!.mo}`);
  console.log(`  [1]: ${all[1]![0]} year=${all[1]!.groups!.y} month=${all[1]!.groups!.mo}`);
  check("matchAll yields one entry per match", all.length === 2);
  check("matchAll exposes named groups per match", all[0]!.groups!.y === "2024" && all[1]!.groups!.y === "2025");

  // matchAll with the d flag also gives start/end index pairs per match.
  const withIdx = [..."2024-06".matchAll(/(\d{4})-(\d{2})/gd)];
  const idx = withIdx[0]!.indices!;
  console.log(`  matchAll+d indices: ${JSON.stringify(idx)}  groups[2]=[${idx[2]![0]},${idx[2]![1]}]`);
  check("matchAll with d exposes [start,end] pairs", idx[2]![0] === 5 && idx[2]![1] === 7);

  // replace with a FUNCTION: the callback receives (match, p1, p2, ..., offset,
  // string, groups). The function's RETURN value is the replacement text. This
  // is how you do computed replacements (uppercasing a capture, looking up a
  // map, formatting). replaceAll accepts the same callback (with g semantics).
  const swapped = "a1 b2 c3".replace(/(\w)(\d)/g, (_match, p1, p2) => `${p2}${p1}`);
  console.log("");
  console.log(`replace with a function: 'a1 b2 c3'.replace(/(\\w)(\\d)/g, (m,p1,p2) => p2+p1)`);
  console.log(`  -> ${JSON.stringify(swapped)}   (each capture pair swapped)`);
  check("replace function receives positional captures", swapped === "1a 2b 3c");

  // escapeRegExp: when building a regex from RUNTIME strings, metacharacters
  // in the input must be escaped or the user can inject pattern (a mini-ReDoS /
  // correctness hole). The canonical escape (MDN): replace every metachar with
  // a backslash-prefixed copy.
  function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  const userInput = "2+2";
  const escaped = escapeRegExp(userInput);
  console.log("");
  console.log("escapeRegExp (escape metacharacters in runtime input):");
  console.log(`  input:  ${JSON.stringify(userInput)}`);
  console.log(`  escaped:${JSON.stringify(escaped)}`);
  console.log(`  new RegExp(escaped).test('2+2'): ${new RegExp(escaped).test("2+2")}`);
  console.log(`  WITHOUT escaping, new RegExp('2+2').test('2+2'): ${new RegExp("2+2").test("2+2")}  ('+' means '1 or more 2')`);
  check("escaped regex matches the literal string", new RegExp(escaped).test("2+2") === true);
  check("unescaped '2+2' matches '222' too (the '+' quantifier leak)", new RegExp("2+2").test("222") === true);
  check("escaped regex does NOT match '222'", new RegExp(escaped).test("222") === false);
}

// ============================================================================
// Section D — Unicode: the u flag, \p{} property escapes, the emoji trap, the v flag
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Unicode: the u flag, \\p{} property escapes, the emoji trap, the v flag");

  // Without the u flag, JS regex operates on UTF-16 CODE UNITS — so an astral
  // character (emoji, U+10000+) is two surrogate halves, and '.' / char classes
  // can split a pair. The u flag switches to CODE-POINT semantics: each whole
  // code point is one atom, and \p{...} Unicode property escapes become legal.
  const emoji = "😀"; // U+1F600, two UTF-16 code units
  console.log(`astral char '😀': .length === ${emoji.length} (two surrogate code units)`);
  console.log(`  /^.$/.test('😀')    : ${/^.$/.test(emoji)}   (no u: '.' matches ONE surrogate half -> splits the pair)`);
  console.log(`  /^.$/u.test('😀')   : ${/^.$/u.test(emoji)}   (u: '.' matches the WHOLE code point)`);
  check("without u, '.' splits an astral surrogate pair", /^.$/.test(emoji) === false);
  check("with u, '.' matches the whole code point", /^.$/u.test(emoji) === true);

  // \p{...} Unicode property escapes (require u or v). /\p{Letter}/u matches
  // ANY script's letter — far better than [a-zA-Z] for international text.
  console.log("");
  console.log("\\p{} Unicode property escapes (require u or v):");
  console.log(`  /^\\p{Letter}$/u.test('é')   : ${/^\p{Letter}$/u.test("é")}   ('é' IS a Letter in any script)`);
  console.log(`  /^\\p{Letter}$/u.test('5')   : ${/^\p{Letter}$/u.test("5")}   ('5' is NOT a Letter)`);
  console.log(`  /^\\p{Number}$/u.test('5')   : ${/^\p{Number}$/u.test("5")}   ('5' IS a Number)`);
  check("\\p{Letter} matches accented Latin", /^\p{Letter}$/u.test("é") === true);
  check("\\p{Letter} rejects a digit", /^\p{Letter}$/u.test("5") === false);

  // THE EMOJI TRAP: \p{Emoji} matches ASCII digits and '#' too — they carry the
  // Emoji property for historical compatibility (they can be rendered as emoji
  // with a variant selector). To match "actual emoji glyphs" use
  // \p{Emoji_Presentation} (or \p{Extended_Pictographic}).
  console.log("");
  console.log("THE EMOJI TRAP — \\p{Emoji} is broader than you think:");
  console.log(`  /^\\p{Emoji}$/u.test('5')             : ${/^\p{Emoji}$/u.test("5")}   (digits have the Emoji property!)`);
  console.log(`  /^\\p{Emoji}$/u.test('#')             : ${/^\p{Emoji}$/u.test("#")}   ('#' too)`);
  console.log(`  /^\\p{Emoji_Presentation}$/u.test('5'): ${/^\p{Emoji_Presentation}$/u.test("5")}   ('5' is NOT emoji-presented)`);
  console.log(`  /^\\p{Emoji_Presentation}$/u.test('😀'): ${/^\p{Emoji_Presentation}$/u.test(emoji)}   ('😀' IS)`);
  check("\\p{Emoji} matches the digit '5' (the trap)", /^\p{Emoji}$/u.test("5") === true);
  check("\\p{Emoji_Presentation} does NOT match '5'", /^\p{Emoji_Presentation}$/u.test("5") === false);
  check("\\p{Emoji_Presentation} matches '😀'", /^\p{Emoji_Presentation}$/u.test(emoji) === true);

  // The v flag (unicodeSets mode, ES2024) is an UPGRADE to u: it adds set
  // notation inside character classes — subtraction A--[B], intersection A&&B,
  // union — and string-literal members. u and v are MUTUALLY EXCLUSIVE
  // (specifying both is a SyntaxError). v is the modern default for new
  // Unicode-aware patterns.
  //
  // NOTE: the v flag is built via new RegExp (not a /literal/): a v-flag LITERAL
  // is a TS type error unless target >= ES2024, and this bundle compiles under
  // ES2023. Constructing at runtime sidesteps the (parse-time-only) check while
  // the engine still honors v at runtime (Node 20+/V8).
  const vSubtract = new RegExp("[\\p{Letter}--[aeiouAEIOU]]", "v"); // consonants only
  const vIntersect = new RegExp("[\\p{Letter}&&\\p{ASCII}]", "v"); // ASCII letters
  console.log("");
  console.log("the v flag (unicodeSets, ES2024) — set notation in classes:");
  console.log(`  [\\p{Letter}--[aeiouAEIOU]]/v.test('H'): ${vSubtract.test("H")}   (consonant)`);
  console.log(`  [\\p{Letter}--[aeiouAEIOU]]/v.test('e'): ${vSubtract.test("e")}   (subtracted vowel)`);
  console.log(`  [\\p{Letter}&&\\p{ASCII}]/v.test('a'): ${vIntersect.test("a")}   (intersection: ASCII letter)`);
  console.log(`  [\\p{Letter}&&\\p{ASCII}]/v.test('é'): ${vIntersect.test("é")}   (non-ASCII)`);
  check("v flag subtraction removes vowels", vSubtract.test("H") === true && vSubtract.test("e") === false);
  check("v flag intersection: 'a' is ASCII AND Letter", vIntersect.test("a") === true);
  check("v flag intersection: 'é' is NOT ASCII", vIntersect.test("é") === false);

  // u + v together is illegal (v supersedes u).
  let uvThrew = false;
  try {
    new RegExp("x", "uv");
  } catch {
    uvThrew = true;
  }
  console.log(`  new RegExp('x','uv') throws: ${uvThrew}   (v supersedes u; both is a SyntaxError)`);
  check("u and v flags are mutually exclusive", uvThrew === true);
}

// ============================================================================
// Section E — Catastrophic backtracking / ReDoS (DOCUMENTED SAFELY)
//             + the cross-language contrast (Go/Rust RE2)
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Catastrophic backtracking / ReDoS (DOCUMENTED SAFELY) + the RE2 contrast");

  // !!! SAFE BOUND: the evil pattern is run ONLY on TINY inputs below (it
  //     matches/fails in microseconds). The exponential cost is demonstrated
  //     via the THEORETICAL partition count 2^(n-1) (pure arithmetic), NEVER
  //     by running a pathologically-long input — that would hang the sweep. !!!

  // A backtracking engine, on failure, backs up and tries the next path through
  // the pattern. A pattern with OVERLAPPING quantifiers like (a+)+b admits an
  // exponential number of ways to partition a run of a's, so a string that
  // almost-matches then fails ("aaaa...!" with no trailing b) forces the engine
  // to try every partition before concluding failure. This is CATASTROPHIC
  // BACKTRACKING — the root cause of ReDoS.
  const evil = new RegExp("^(a+)+b$");
  console.log("Evil pattern: new RegExp('^(a+)+b$')   (overlapping quantifiers)");
  console.log(`  compiles in JS? ${evil instanceof RegExp}   (JS ACCEPTS it — RE2 would match it in LINEAR time)`);
  console.log(`  .test('aaab')  : ${evil.test("aaab")}   (TINY input: matches, instant)`);
  console.log(`  .test('aaaa!') : ${evil.test("aaaa!")}  (TINY input: fails, instant)`);
  console.log(`  .test('aaaaaa'): ${evil.test("aaaaaa")}  (TINY input: fails, instant — but scales EXPONENTIALLY with n)`);
  check("evil pattern compiles in JS (backtracking engine allows it)", evil instanceof RegExp);
  check("evil pattern matches a tiny 'aaab'", evil.test("aaab") === true);
  check("evil pattern fails a tiny 'aaaa!'", evil.test("aaaa!") === false);

  // The exponential curve, demonstrated by MATH (no pathological run):
  // On a run of n a's followed by a non-b, the engine's WORST CASE is to try
  // every composition (partition) of n — there are exactly 2^(n-1) of them.
  // Doubling n SQUARES the work. This is why a 30-a input (~5.4e8 partitions)
  // hangs a backtracker while RE2 (Go/Rust) finishes in microseconds.
  function compositions(n: number): bigint {
    return 2n ** BigInt(n - 1);
  }
  console.log("");
  console.log("Theoretical worst-case backtrack partitions = 2^(n-1)  (pure math; NOT run):");
  for (const n of [5, 10, 15, 20, 25, 30]) {
    console.log(`  n=${String(n).padStart(2)} a's -> ${compositions(n).toString().padStart(11)} partitions`);
  }
  check("partitions DOUBLE per added 'a' (exponential)", compositions(20) === 2n * compositions(19));
  check("n=25 already ~16.7 million partitions (a hang)", compositions(25) === 16777216n);

  // The cross-language headline: Go and Rust deliberately use RE2 (Russ Cox),
  // which builds the pattern into an NFA simulated in LOCKSTEP — every state at
  // once, one input char at a time. No path is ever revisited, so match time is
  // LINEAR in the input, INDEPENDENT of the pattern. The price: RE2 CANNOT
  // express backreferences (\1) or lookahead/lookbehind — it REFUSES to compile
  // them. JS chose the opposite: full PCRE-ish power, exponential worst case.
  console.log("");
  console.log("Cross-language contrast (the design choice):");
  console.log("  JS RegExp       : BACKTRACKING engine -> supports \\1, lookahead, lookbehind;");
  console.log("                    worst case is EXPONENTIAL (ReDoS-vulnerable).");
  console.log("  Go regexp       : RE2 -> LINEAR time, NO backtracking; REFUSES \\1 / lookaround.");
  console.log("  Rust regex crate: RE2-style -> LINEAR time, NO backtracking; REFUSES \\1 / lookaround.");
  console.log("  => JS \\1 (above, Section B) is ILLEGAL in Go/Rust regex.");
  console.log("  See ../go/REGEXP.md and ../rust (the safety-by-design contrast).");

  // The ReDoS-allowing pattern compiles in JS but a backreference is REJECTED
  // by RE2 in principle (documented, not executed in Go/Rust here).
  check("backreference compiles in JS but is unrepresentable in RE2 (Go/Rust)", /(\w)\1/.test("aa") === true);

  // Mitigations (documented, not all runnable as a single value):
  //  1. Don't run user-influenced regexes on untrusted input without a timeout
  //     (Node has no built-in regex timeout; a worker_thread + AbortController
  //     is the escape hatch — see TIMERS_IO / CONCURRENCY_PATTERNS).
  //  2. Flatten overlapping quantifiers: (a+)+ -> a+ (linear). Use atomic-ish
  //     rewrites or possessive-style alternation.
  //  3. For server-side, consider re2 (the npm binding) or hand the validation
  //     to a Rust/Go microservice.
  console.log("");
  console.log("Mitigations (documented): timeout via worker_thread+AbortController;");
  console.log("  flatten overlapping quantifiers ((a+)+ -> a+); use the `re2` npm");
  console.log("  binding or a Rust/Go validator for untrusted input.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("regex.ts — Phase 5 bundle (Standard Library Essentials).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: JS RegExp is a BACKTRACKING engine (PCRE-ish) — expressive");
  console.log("(\\1, lookaround) but ReDoS-vulnerable. Go/Rust use RE2 (linear, no");
  console.log("backtracking). That trade-off is the headline of this bundle.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
