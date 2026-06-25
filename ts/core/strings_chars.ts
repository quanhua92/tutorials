// strings_chars.ts — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, that a TS/JS string is ONE
// immutable primitive that is an ordered sequence of UTF-16 CODE UNITS — and
// pin why "a".length===1 but "𝔸".length===2, why bracket indexing splits an
// emoji in half, why [...str] differs from str.split(""), and how grapheme
// clusters (Intl.Segmenter) sit above both code units and code points.
//
// This is the GROUND TRUTH for STRINGS_CHARS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): TypeScript has exactly ONE string
// primitive; at runtime it is a JavaScript String. That String is NOT a byte
// array (that is Go) and NOT a UTF-8 sequence — it is an IMMUTABLE sequence of
// 16-bit CODE UNITS (UTF-16). Most characters in the Basic Multilingual Plane
// (U+0000..U+FFFF) fit in one code unit, so `"a".length === 1` "just works".
// But anything outside the BMP — an astral code point like 𝔸 (U+1D538) or an
// emoji like 👋 (U+1F44B) — needs a SURROGATE PAIR (two code units), so its
// `.length` is 2 and `s[0]` returns a broken half. This code-unit / code-point
// / grapheme distinction is the foundation of correct text handling: it is why
// `"𝔸".split("")` corrupts emoji, why `for...of` and `[...s]` behave differently
// from indexing, and why counting "characters" needs Intl.Segmenter.
//
// Run:
//     pnpm exec tsx strings_chars.ts   (or: just run strings_chars)

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

// hexOf formats a code unit/point as "U+XXXX" (>=4 hex digits, uppercased).
function hexOf(n: number): string {
  return "U+" + n.toString(16).toUpperCase().padStart(4, "0");
}

// attemptMutate does the REAL `s[i] = v` assignment. TS marks String's index
// signature readonly (error TS2542), so we route through a type-only cast to a
// writable-index shape; the cast is ERASED at runtime, so the engine still runs
// the genuine string-index assignment. In strict mode (ESM, which tsx/core
// always use) that assignment THROWS — strings are immutable primitives.
function attemptMutate(s: string, i: number, v: string): void {
  (s as unknown as { [k: number]: string })[i] = v;
}

// ============================================================================
// Section A — One primitive, immutable; typeof "string"; literal interning
// ============================================================================

function sectionA(): void {
  sectionBanner("A — One primitive, immutable; typeof \"string\"; literal interning");

  // A string is a PRIMITIVE (one of the 7), not an object. typeof is a runtime
  // operator; it sees only the runtime type, never your annotations.
  console.log("form            : typeof");
  console.log("----------------:--------");
  const tTypeof = typeof `template`;
  console.log('""          : ' + typeof "");
  console.log('"hello"     : ' + typeof "hello");
  console.log('"`template`": ' + tTypeof);
  console.log('"a"+"b"     : ' + typeof ("a" + "b"));
  console.log("String(42)  : " + typeof String(42));

  check('typeof "" === "string"', typeof "" === "string");
  check('typeof "hello" === "string"', typeof "hello" === "string");
  check('typeof `template` === "string"', typeof `template` === "string");

  // A single-quoted literal, double-quoted literal, and template literal with
  // no interpolation are ALL the same primitive value. Template literals with
  // no ${} are just strings.
  check('"s" === `s` (template with no interpolation === literal)', "s" === `s`);
  check("'a' === \"a\" === `a` (all three quote forms are the same value)",
    "a" === "a" && "a" === `a`);

  // String LITERALS are INTERNED: the engine reuses one shared primitive for
  // identical literal text, so two literals with the same content are ===.
  // Built strings are also === by VALUE (strict equality compares primitives
  // by value, never by identity — there is no "identity" for a primitive).
  const built = "ab" + "c";
  check('identical literals are === ("abc" === "abc")', "abc" === "abc");
  check('a built string is === to the same literal ("abc" built === "abc")',
    built === "abc");

  // VALUE SEMANTICS: assigning a string COPIES the value (conceptually). Two
  // variables holding the same string are ===; reassigning one never touches the
  // other. This is the primitive axis of VALUE_VS_REFERENCE.
  let a = "abc";
  const b = a; // b gets the value "abc" (a copy, not an alias)
  a = "xyz"; // reassigning a does NOT change b
  check("strings copy on assignment: b stays \"abc\" after a = \"xyz\"", b === "abc");

  // IMMUTABILITY (1 of 2): str.replace / toUpperCase / slice ALWAYS return a NEW
  // string; the original is never modified in place. You must capture the
  // return value or the work is lost.
  const original = "abc";
  const replaced = original.replace("b", "X");
  console.log(`"abc".replace("b","X") -> ${JSON.stringify(replaced)} (a NEW string)`);
  console.log(`original unchanged     -> ${JSON.stringify(original)} (immutable)`);
  check('"abc".replace("b","X") === "aXc" (returns a new string)', replaced === "aXc");
  check("original is unchanged after .replace", original === "abc");
  // When nothing matches, replace returns a value-=== string (same content);
  // do NOT assume reference-identity — compare by value.
  check('"abc".replace("z","X") === "abc" (no match -> same content)',
    "abc".replace("z", "X") === "abc");

  // IMMUTABILITY (2 of 2): trying to write s[0] = "X" on a primitive string is
  // FORBIDDEN. In sloppy mode it is a silent no-op; in STRICT mode (every ESM
  // module — which is what core/.ts runs as via tsx) it THROWS TypeError.
  let target = "abc";
  let threwTypeError = false;
  try {
    attemptMutate(target, 0, "X");
  } catch (e) {
    threwTypeError = e instanceof TypeError;
  }
  console.log(`attempt target[0]="X" -> threw TypeError? ${threwTypeError}`);
  console.log(`target after attempt  -> ${JSON.stringify(target)} (immutable)`);
  check("s[0]=\"X\" throws TypeError in strict mode (strings are read-only)",
    threwTypeError === true);
  check("target is \"abc\" after the failed mutation", target === "abc");
}

// ============================================================================
// Section B — .length & bracket indexing count UTF-16 CODE UNITS (the trap)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — .length & bracket indexing count UTF-16 CODE UNITS (the trap)");

  // THE foundational fact: a JS String is a sequence of 16-bit CODE UNITS, not
  // "characters". `.length` is the CODE-UNIT count, and `s[i]` is the i-th CODE
  // UNIT. For BMP text this lines up with intuition; for astral text it does not.
  const ascii = "a"; // U+0061 — one BMP code unit
  const mathA = "𝔸"; // U+1D538 — astral, needs a SURROGATE PAIR (2 code units)

  console.log("text   .length   why");
  console.log("----   -------   ---");
  console.log(`"a"    ${String(ascii.length).padStart(5)}    U+0061 fits in one BMP code unit`);
  console.log(`"𝔸"    ${String(mathA.length).padStart(5)}    U+1D538 needs a surrogate pair (2 code units)`);

  check('"a".length === 1 (BMP code unit)', ascii.length === 1);
  check('"𝔸".length === 2 (astral -> surrogate pair)', mathA.length === 2);

  // The surrogate-pair arithmetic, surfaced. U+1D538 is encoded as a HIGH
  // surrogate U+D835 followed by a LOW surrogate U+DD38. Bracket indexing
  // returns each surrogate as a SEPARATE "character" — a broken half-glyph.
  const high = mathA.charAt(0); // the lone high surrogate as a 1-char string
  const low = mathA.charAt(1); // the lone low surrogate as a 1-char string
  console.log("");
  console.log(`"𝔸".charAt(0) -> ${JSON.stringify(high)} (${hexOf(high.charCodeAt(0))}, the HIGH surrogate)`);
  console.log(`"𝔸".charAt(1) -> ${JSON.stringify(low)} (${hexOf(low.charCodeAt(0))}, the LOW surrogate)`);
  console.log("  neither half renders on its own — indexing SPLIT the symbol");

  check('"𝔸".charAt(0) === "\\uD835" (the high surrogate)', high === "\uD835");
  check('"𝔸".charAt(1) === "\\uDD38" (the low surrogate)', low === "\uDD38");
  check('"𝔸"[0] is NOT "𝔸" (indexing returns a half-surrogate)', high !== "𝔸");

  // Worked smallest-scale example: the surrogate-pair formula. An astral code
  // point C (U+10000..U+10FFFF) is split into two 16-bit code units:
  //   high = 0xD800 + ((C - 0x10000) >> 10)
  //   low  = 0xDC00 + ((C - 0x10000) & 0x3FF)
  const C = 0x1d538;
  const highUnit = 0xd800 + ((C - 0x10000) >> 10);
  const lowUnit = 0xdc00 + ((C - 0x10000) & 0x3ff);
  console.log("");
  console.log(`surrogate math for ${hexOf(C)}: high=${hexOf(highUnit)} low=${hexOf(lowUnit)}`);
  check("surrogate formula: high unit === 0xD835", highUnit === 0xd835);
  check("surrogate formula: low unit === 0xDD38", lowUnit === 0xdd38);
  check("String.fromCharCode(0xD835, 0xDD38) === \"𝔸\"",
    String.fromCharCode(0xd835, 0xdd38) === "𝔸");
}

// ============================================================================
// Section C — Code POINTS: codePointAt / fromCodePoint; [...s] vs split("")
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Code POINTS: codePointAt/fromCodePoint; [...s] vs split(\"\")");

  // charCodeAt(i) returns the CODE UNIT at i (16-bit). codePointAt(i) reads the
  // unit at i and, if it is a HIGH surrogate followed by a LOW surrogate,
  // COMBINES them into the full astral code point (up to 21 bits).
  const s = "𝔸";
  const cp = s.codePointAt(0); // 0x1D538 | undefined
  console.log(`"𝔸".charCodeAt(0)   -> ${hexOf(s.charCodeAt(0))} (the CODE UNIT)`);
  console.log(`"𝔸".codePointAt(0) -> ${cp !== undefined ? hexOf(cp) : "undefined"} (the CODE POINT, pair combined)`);
  check('"𝔸".charCodeAt(0) === 0xD835 (the code unit)', s.charCodeAt(0) === 0xd835);
  check('"𝔸".charCodeAt(1) === 0xDD38 (the second code unit)', s.charCodeAt(1) === 0xdd38);
  check('"𝔸".codePointAt(0) === 0x1D538 (the code point)', cp === 0x1d538);

  // The inverse: fromCodePoint builds a string from whole code points (handles
  // astral points correctly by emitting the surrogate pair); fromCharCode only
  // takes 16-bit code units and cannot build an astral symbol from one number.
  console.log("");
  console.log(`String.fromCodePoint(0x1D538)  -> ${JSON.stringify(String.fromCodePoint(0x1d538))}`);
  console.log(`String.fromCharCode(0xD835, 0xDD38) -> ${JSON.stringify(String.fromCharCode(0xd835, 0xdd38))}`);
  console.log(`String.fromCharCode(0x1D538)  -> ${JSON.stringify(String.fromCharCode(0x1d538))} (WRONG: only the low 16 bits 0xD538)`);
  check('String.fromCodePoint(0x1D538) === "𝔸"', String.fromCodePoint(0x1d538) === "𝔸");
  check("String.fromCharCode(0x1D538) !== \"𝔸\" (it truncates to 16 bits)",
    String.fromCharCode(0x1d538) !== "𝔸");

  // === THE HEADLINE GOTCHA ===
  // The string ITERATOR (used by for...of and the spread [...s]) yields CODE
  // POINTS — it walks surrogate pairs. str.split("") does NOT use the iterator;
  // it splits on CODE UNITS and therefore BREAKS astral symbols.
  const codePoints = [...s];
  const codeUnits = s.split("");
  console.log("");
  console.log("THE HEADLINE: same string, two ways to make an array");
  console.log(`  [..."𝔸"].length      -> ${codePoints.length}  (CODE POINTS — iterator combines the pair)`);
  console.log(`  "𝔸".split("").length -> ${codeUnits.length}  (CODE UNITS — pair split in half)`);
  console.log(`  [..."𝔸"]             -> ${JSON.stringify(codePoints)}`);
  console.log(`  "𝔸".split("")        -> ${JSON.stringify(codeUnits)}  (two broken surrogates)`);

  check('[..."𝔸"].length === 1 (the string iterator yields code points)', codePoints.length === 1);
  check('"𝔸".split("").length === 2 (split yields code units — the trap)', codeUnits.length === 2);
  check('for...of yields the whole "𝔸" (iterator combines surrogates)',
    Array.from(s).join("") === s && Array.from(s)[0] === "𝔸");

  // Practical consequence: counting "characters" in user input. "abc".length is
  // fine for ASCII; for any astral text, use [...s].length for a code-point
  // count (and Intl.Segmenter for true grapheme count — Section D).
  check('[..."𝔸"].length is the correct code-point count (use this, not .length)',
    [..."𝔸"].length === 1);
}

// ============================================================================
// Section D — Grapheme clusters: code points joined by ZWJ; Intl.Segmenter
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Grapheme clusters: code points joined by ZWJ; Intl.Segmenter");

  // Above "code unit" and "code point" sits a third level: the GRAPHEME CLUSTER
  // — what a user perceives as one "character". The family emoji "👨‍👩‍👧" is FIVE
  // code points (man, ZWJ, woman, ZWJ, girl) glued together by U+200D ZERO
  // WIDTH JOINER, but it is ONE grapheme. Each emoji code point is astral (2
  // code units), so .length counts 8.
  const family = "👨‍👩‍👧";
  const codePointList = [...family].map((c) => hexOf(c.codePointAt(0) ?? 0));
  console.log(`"👨‍👩‍👧"`);
  console.log(`  .length         = ${family.length}   (8 UTF-16 code units)`);
  console.log(`  [...s].length   = ${[...family].length}   (5 code points)`);
  console.log(`  code points     = ${codePointList.join(" ")}`);
  console.log("                   (👨 + ZWJ + 👩 + ZWJ + 👧 — joined into ONE grapheme)");

  check('"👨‍👩‍👧".length === 8 (UTF-16 code units)', family.length === 8);
  check('[..."👨‍👩‍👧"].length === 5 (code points: man,ZWJ,woman,ZWJ,girl)',
    [...family].length === 5);

  // Intl.Segmenter (Node 16+) segments by user-perceived GRAPHEME clusters per
  // UAX #29 — the ONLY correct way to count "characters" in arbitrary text.
  // The default granularity is "grapheme".
  const segmenter = new Intl.Segmenter("en", { granularity: "grapheme" });
  const graphemes = [...segmenter.segment(family)];
  const firstGrapheme = graphemes[0]?.segment ?? "";
  console.log("");
  console.log(`new Intl.Segmenter().segment("👨‍👩‍👧") -> ${graphemes.length} grapheme cluster(s)`);
  console.log(`  first grapheme  = ${JSON.stringify(firstGrapheme)} (the whole family, one unit)`);
  check('Intl.Segmenter counts "👨‍👩‍👧" as 1 grapheme cluster', graphemes.length === 1);
  check('the single grapheme equals the whole family string', firstGrapheme === family);

  // A combining-mark example: "é" can be ONE code point (U+00E9) or TWO (e +
  // U+0303-style combining mark). Visually identical, different code-unit and
  // code-point counts — only normalization + grapheme segmentation agree.
  const precomposed: string = "\u00e9"; // é, 1 code point
  const decomposed: string = "e\u0301"; // e + combining acute, 2 code points, same glyph
  console.log("");
  console.log(`"\u00e9" (precomposed)   .length=${precomposed.length} codePoints=${[...precomposed].length}`);
  console.log(`"e\u0301" (decomposed) .length=${decomposed.length} codePoints=${[...decomposed].length}`);
  console.log(`  visually the same glyph, but precomposed !== decomposed: ${precomposed === decomposed}`);
  console.log(`  .normalize("NFC") reconciles them: ${precomposed === decomposed.normalize("NFC")}`);
  check("precomposed !== decomposed (different code points, same glyph)",
    precomposed !== decomposed);
  check('.normalize("NFC") makes decomposed === precomposed',
    decomposed.normalize("NFC") === precomposed);
}

// ============================================================================
// Section E — Method greatest hits + tagged template literals (frozen raw)
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Method greatest hits + tagged template literals (frozen raw)");

  // slice supports NEGATIVE indices (counts from the end); substring does NOT
  // (it treats negatives as 0). This is the classic slice/substring quirk.
  console.log("slice / substring negative-index behavior:");
  console.log(`  "abcdef".slice(-2)    -> ${JSON.stringify("abcdef".slice(-2))}   (from the end)`);
  console.log(`  "abcdef".slice(-4,-2) -> ${JSON.stringify("abcdef".slice(-4, -2))}  (range from the end)`);
  console.log(`  "abcdef".substring(-2)-> ${JSON.stringify("abcdef".substring(-2))} (negatives treated as 0)`);
  check('"ab".slice(-1) === "b"', "ab".slice(-1) === "b");
  check('"abcdef".slice(-4,-2) === "cd"', "abcdef".slice(-4, -2) === "cd");
  check('substring(-2) treats negative as 0', "abcdef".substring(-2) === "abcdef");

  // Search & test: includes (boolean) vs indexOf (position or -1); both are
  // code-unit substring scans, NOT regex, case-sensitive.
  console.log("");
  console.log("search / membership:");
  console.log(`  "hello".includes("ell")   -> ${"hello".includes("ell")}`);
  console.log(`  "hello".indexOf("ell")    -> ${"hello".indexOf("ell")}`);
  console.log(`  "hello".indexOf("xyz")    -> ${"hello".indexOf("xyz")}   (absent -> -1)`);
  console.log(`  "hello".startsWith("hel") -> ${"hello".startsWith("hel")}`);
  console.log(`  "hello".endsWith("llo")   -> ${"hello".endsWith("llo")}`);
  check('"hello".includes("ell") === true', "hello".includes("ell") === true);
  check('"hello".indexOf("xyz") === -1', "hello".indexOf("xyz") === -1);
  check('includes is case-sensitive ("Hello".includes("h") === false)',
    "Hello".includes("h") === false);

  // Padding & repetition.
  console.log("");
  console.log("pad / repeat:");
  console.log(`  "x".padStart(3, ".")   -> ${JSON.stringify("x".padStart(3, "."))}`);
  console.log(`  "x".padEnd(3, "-")     -> ${JSON.stringify("x".padEnd(3, "-"))}`);
  console.log(`  "ab".repeat(3)         -> ${JSON.stringify("ab".repeat(3))}`);
  check('"x".padStart(3,".") === "..x"', "x".padStart(3, ".") === "..x");
  check('"ab".repeat(3) === "ababab"', "ab".repeat(3) === "ababab");

  // at(i) (ES2022) accepts a NEGATIVE index and returns the code unit there
  // (still a CODE UNIT — at() does NOT combine surrogate pairs).
  console.log("");
  console.log("at() (ES2022, supports negative index):");
  console.log(`  "abc".at(-1) -> ${JSON.stringify("abc".at(-1))}   (last code unit)`);
  console.log(`  "abc".at(0)  -> ${JSON.stringify("abc".at(0))}`);
  console.log(`  "abc".at(5)  -> ${String("abc".at(5))}   (out of range -> undefined)`);
  check('"abc".at(-1) === "c"', "abc".at(-1) === "c");
  check('"abc".at(5) === undefined (out of range)', "abc".at(5) === undefined);

  // replace (first match) vs replaceAll (every match, ES2021). Both return a
  // NEW string (immutability, Section A).
  console.log("");
  console.log("replace vs replaceAll:");
  console.log(`  "aaa".replace("a","X")    -> ${JSON.stringify("aaa".replace("a", "X"))}   (first only)`);
  console.log(`  "aaa".replaceAll("a","X") -> ${JSON.stringify("aaa".replaceAll("a", "X"))}   (every match)`);
  check('"aaa".replace("a","X") === "Xaa" (first match only)', "aaa".replace("a", "X") === "Xaa");
  check('"aaa".replaceAll("a","X") === "XXX"', "aaa".replaceAll("a", "X") === "XXX");

  // trim family.
  console.log("");
  console.log("trim family:");
  console.log(`  "  hi  ".trim()      -> ${JSON.stringify("  hi  ".trim())}`);
  console.log(`  "  hi  ".trimStart() -> ${JSON.stringify("  hi  ".trimStart())}`);
  console.log(`  "  hi  ".trimEnd()   -> ${JSON.stringify("  hi  ".trimEnd())}`);
  check('"  hi  ".trim() === "hi"', "  hi  ".trim() === "hi");

  // === Tagged template literals ===
  // fn`x${1}y` calls fn(strings, ...values) where `strings` is the array of
  // literal text fragments and `values` are the interpolated expressions.
  // Per spec, the SAME literal always passes the SAME strings object (cached),
  // and BOTH strings and strings.raw are FROZEN (immutable).
  function inspectTag(strings: TemplateStringsArray, ...values: readonly number[]): string {
    return JSON.stringify({
      strings: [...strings],
      raw: [...strings.raw],
      values,
      frozen: Object.isFrozen(strings),
      rawFrozen: Object.isFrozen(strings.raw),
      stringsLen: strings.length, // substitutions + 1, always non-empty
    });
  }
  const tagged = inspectTag`x${1}y${2}z`;
  console.log("");
  console.log("tagged template: inspectTag`x${1}y${2}z`");
  console.log(`  ${tagged}`);
  {
    const r = JSON.parse(tagged) as {
      strings: string[];
      raw: string[];
      values: number[];
      frozen: boolean;
      rawFrozen: boolean;
      stringsLen: number;
    };
    check("tagged: strings === [\"x\",\"y\",\"z\"]", JSON.stringify(r.strings) === JSON.stringify(["x", "y", "z"]));
    check("tagged: values === [1,2]", JSON.stringify(r.values) === JSON.stringify([1, 2]));
    check("tagged: strings array is FROZEN", r.frozen === true);
    check("tagged: strings.raw is FROZEN", r.rawFrozen === true);
    check("tagged: strings.length === substitutions + 1 (3 fragments)", r.stringsLen === 3);
  }
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("strings_chars.ts — Phase 1 bundle.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: a JS String is an IMMUTABLE sequence of UTF-16 CODE UNITS.");
  console.log(".length counts code units (not code points, not graphemes). That");
  console.log("single fact explains every surrogate-pair surprise below.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
