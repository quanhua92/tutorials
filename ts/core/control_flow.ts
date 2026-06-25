// control_flow.ts — Phase 1 bundle (control flow).
//
// GOAL (one line): show, by printing every value, how TS/JS's control-flow
// statements behave — pinning the sharp edges: switch matches with strict ===
// and has NO automatic fallthrough (the missing-break bug vs legitimate
// empty-case grouping), `for...of` iterates VALUES via the iterator protocol
// while `for...in` iterates enumerable STRING KEYS (and INHERITED prototype
// keys!), and modern code leans on `??` (nullish) vs `||` (truthy) and `?.`
// (optional chaining) — whose subtle difference (`0 ?? 99` vs `0 || 99`) is a
// frequent bug source.
//
// This is the GROUND TRUTH for CONTROL_FLOW.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle is the foundation): JavaScript has the usual
// if/switch/for vocabulary, but with sharp edges that C/Go/Rust do not share:
//   - `switch` matches with strict `===` (NO coercion) and falls through to the
//     next case UNLESS you `break`/`return`/`throw` — the missing-break bug.
//   - `for...in` iterates enumerable STRING KEYS of an object, INCLUDING
//     inherited prototype keys (the prototype-pollution trap). Never `for...in`
//     an array — you get "0","1","2", not values, AND any extra props on the
//     array leak in.
//   - `for...of` (ES2015) iterates VALUES via the iterable/iterator protocol
//     ([Symbol.iterator]() -> next()).
//   - `??` (nullish, ES2020) only fills in for null/undefined; `||` fills in
//     for ANY falsy value — so `0 ?? 99` is `0` but `0 || 99` is `99`. This is
//     THE modern bug source.
//   - `?.` (optional chaining, ES2020) short-circuits to `undefined` instead of
//     throwing on a missing property/method.
//
// Run:
//     pnpm exec tsx control_flow.ts   (or: just run control_flow)

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

// show prints any value deterministically: undefined and NaN (which
// JSON.stringify would render as "undefined"/null) get readable strings.
function show(v: unknown): string {
  if (v === undefined) return "undefined";
  if (typeof v === "number" && Number.isNaN(v)) return "NaN";
  return JSON.stringify(v);
}

// --- operator wrappers (keep literal calls legal under strict mode) ---------
//
// TS const-folds literal operator expressions: `0 ?? 99` is flagged "RHS
// unreachable" (0 is never nullish), `0 || 99` "always falsy", `null && x`
// "always nullish". Routing both operands through `unknown` parameters stops
// the const-fold (the body sees a parameter, not a literal) while the runtime
// operator still does its REAL ?? / || / && work. (Same trick the style anchor
// uses for `looseEq` / `runtimePlus`.) The `as Prim` casts are type-only and
// erased at runtime.
type Prim = number | string | boolean | null | undefined;

function nullish(a: unknown, b: unknown): Prim {
  return (a as Prim) ?? (b as Prim);
}
function or(a: unknown, b: unknown): Prim {
  return (a as Prim) || (b as Prim);
}
function and(a: unknown, b: unknown): Prim {
  return (a as Prim) && (b as Prim);
}

// ============================================================================
// Section A — if / else if / else & the ternary (truthiness drives the branch)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — if / else if / else & the ternary (truthiness drives the branch)");

  // The condition of `if` is NOT required to be boolean — JS runs it through
  // ToBoolean. So the falsy set from VALUES_TYPES_COERCION (false, 0, -0, 0n,
  // "", null, undefined, NaN) all take the else branch; everything else (truthy)
  // takes the if branch. This is the single biggest difference from Go/Rust,
  // where the condition must be a bool. (🔗 VALUES_TYPES_COERCION §C.)

  // A classic: choose a bucket from a numeric value with else-if. The FIRST
  // true branch wins; the rest are skipped.
  function bucketOf(n: number): string {
    if (n < 0) {
      return "negative";
    } else if (n === 0) {
      return "zero";
    } else if (n < 10) {
      return "small";
    } else {
      return "large";
    }
  }
  console.log(`bucketOf(-3)  -> ${bucketOf(-3)}`);
  console.log(`bucketOf(0)   -> ${bucketOf(0)}`);
  console.log(`bucketOf(7)   -> ${bucketOf(7)}`);
  console.log(`bucketOf(42)  -> ${bucketOf(42)}`);
  check('bucketOf(-3) === "negative"', bucketOf(-3) === "negative");
  check('bucketOf(0) === "zero"', bucketOf(0) === "zero");
  check('bucketOf(7) === "small"', bucketOf(7) === "small");
  check('bucketOf(42) === "large"', bucketOf(42) === "large");

  // THE expert trap — truthy-empty values. `if (arr)` is NOT "is the list
  // non-empty?": [] is truthy. `if (str)` skips for "" (correctly falsy), BUT
  // "0" and " " are truthy (non-empty strings). (🔗 VALUES_TYPES_COERCION §C.)
  console.log("");
  console.log("Truthiness drives if-conditions (ToBoolean):");
  console.log(`  Boolean([])  -> ${Boolean([])}        (empty array is TRUTHY — never use \`if (arr)\` for empty)`);
  console.log(`  Boolean("")  -> ${Boolean("")}       (empty string is falsy)`);
  console.log(`  Boolean("0") -> ${Boolean("0")}        ("0" is TRUTHY — non-empty string)`);
  console.log(`  Boolean(0)   -> ${Boolean(0)}        (0 is falsy)`);
  check("Boolean([]) === true (truthy-empty: use .length, not `if (arr)`)", Boolean([]) === true);
  check('Boolean("") === false (empty string is falsy)', Boolean("") === false);
  check('Boolean("0") === true (non-empty string, despite "0")', Boolean("0") === true);
  check("Boolean(0) === false (0 is falsy)", Boolean(0) === false);

  // Ternary: cond ? a : b — an EXPRESSION (not a statement). Chains read
  // right-to-left like else-if, but nesting past 2-3 levels is unreadable.
  const grade = (score: number): string =>
    score >= 90 ? "A" : score >= 80 ? "B" : score >= 70 ? "C" : "F";
  console.log("");
  console.log(`ternary chain: grade(95)=${grade(95)}  grade(85)=${grade(85)}  grade(75)=${grade(75)}  grade(50)=${grade(50)}`);
  check('grade(95) === "A"', grade(95) === "A");
  check('grade(85) === "B"', grade(85) === "B");
  check('grade(75) === "C"', grade(75) === "C");
  check('grade(50) === "F"', grade(50) === "F");
}

// ============================================================================
// Section B — switch: strict === match, no auto-fallthrough (the missing-break
// trap), and legitimate empty-case grouping
// ============================================================================

function sectionB(): void {
  sectionBanner("B — switch: strict ===, no auto-fallthrough, empty-case grouping");

  // (1) switch matches with STRICT === (no coercion). "1" does NOT match case 1;
  // true does NOT match case 1 either (no ToNumber coercion, unlike `==`).
  function strictSwitch(v: unknown): string {
    switch (v) {
      case 1: // number one
        return "number-1";
      case "1": // string "1"
        return "string-1";
      case true: // boolean true
        return "boolean-true";
      default:
        return "no-match";
    }
  }
  console.log(`switch(1)    -> ${strictSwitch(1)}    (number 1 matched case 1)`);
  console.log(`switch("1")  -> ${strictSwitch("1")}   (string "1" matched case "1" — STRICT ===, no coercion)`);
  console.log(`switch(true) -> ${strictSwitch(true)}   (true did NOT match case 1 — no ToNumber coercion)`);
  console.log(`switch(2)    -> ${strictSwitch(2)}    (no case matched -> default)`);
  check('switch(1) === "number-1"', strictSwitch(1) === "number-1");
  check('switch("1") === "string-1" (strict ===: "1" !== 1)', strictSwitch("1") === "string-1");
  check('switch(true) === "boolean-true" (true !== 1, no coercion)', strictSwitch(true) === "boolean-true");
  check('switch(2) === "no-match" (no case -> default)', strictSwitch(2) === "no-match");

  // (2) Legitimate empty-case grouping: adjacent cases with NO body between them
  // share a clause. This is the IDIOMATIC "fall through to shared code" — and
  // TS's noFallthroughCasesInSwitch ALLOWS it (empty case = intent is clear).
  function dayKind(day: string): string {
    switch (day) {
      case "Sat":
      case "Sun": // <-- empty case above falls through here on purpose
        return "weekend";
      case "Mon":
      case "Tue":
      case "Wed":
      case "Thu":
      case "Fri":
        return "weekday";
      default:
        return "unknown";
    }
  }
  console.log("");
  console.log(`dayKind("Sat") -> ${dayKind("Sat")}   (empty case "Sat" fell through to "Sun")`);
  console.log(`dayKind("Wed") -> ${dayKind("Wed")}   (Wed grouped with Mon/Tue/Thu/Fri)`);
  console.log(`dayKind("Sol") -> ${dayKind("Sol")}   (no case -> default)`);
  check('dayKind("Sat") === "weekend" (empty-case grouping)', dayKind("Sat") === "weekend");
  check('dayKind("Wed") === "weekday" (multi-value empty-case grouping)', dayKind("Wed") === "weekday");
  check('dayKind("Sol") === "unknown" (default clause)', dayKind("Sol") === "unknown");

  // (3) THE missing-break trap. In plain JS, a NON-empty case that lacks a
  // break/return/throw FALLS THROUGH into the next case's body. TS's compiler
  // flag `noFallthroughCasesInSwitch` turns the ACCIDENTAL version into a
  // COMPILE ERROR — which is exactly why this function needs @ts-expect-error
  // below to build at all. We trigger the bug on purpose to show the runtime
  // effect: fallthroughSwitch(1) runs BOTH "one" and "two".
  function fallthroughSwitch(v: number): string[] {
    const seen: string[] = [];
    switch (v) {
      // Intentional: case 1 has NO break, so it falls into case 2 at runtime
      // (the missing-break bug). `noFallthroughCasesInSwitch` would otherwise
      // reject this — proving the lint catches the accident. (NB: TS does NOT
      // recognize a `// falls through` comment the way C/eslint do.)
      // @ts-expect-error fallthrough case in switch — intentional, to demo the bug
      case 1:
        seen.push("one");
      case 2:
        seen.push("two");
        break;
      case 3:
        seen.push("three");
        break;
    }
    return seen;
  }
  const from1 = fallthroughSwitch(1); // -> ["one", "two"]  (case 2 ran via fallthrough!)
  const from2 = fallthroughSwitch(2); // -> ["two"]
  console.log("");
  console.log(`fallthroughSwitch(1) -> ${JSON.stringify(from1)}   (missing break RAN case 2!)`);
  console.log(`fallthroughSwitch(2) -> ${JSON.stringify(from2)}   (started at case 2, broke)`);
  check('fallthroughSwitch(1) === ["one","two"] (the missing-break bug)', JSON.stringify(from1) === '["one","two"]');
  check('fallthroughSwitch(2) === ["two"] (case 2 broke, no fallthrough)', JSON.stringify(from2) === '["two"]');

  // (4) `default` runs when no case matched. By convention it is last, but the
  // spec allows it anywhere; only ONE default is allowed per switch.
  function httpLabel(code: number): string {
    switch (code) {
      case 200:
        return "OK";
      case 404:
        return "Not Found";
      case 500:
        return "Server Error";
      default:
        return "other";
    }
  }
  console.log("");
  console.log(`httpLabel(200) -> ${httpLabel(200)}   httpLabel(404) -> ${httpLabel(404)}   httpLabel(302) -> ${httpLabel(302)}`);
  check('httpLabel(200) === "OK"', httpLabel(200) === "OK");
  check('httpLabel(404) === "Not Found"', httpLabel(404) === "Not Found");
  check('httpLabel(302) === "other" (default ran, no case matched)', httpLabel(302) === "other");
}

// ============================================================================
// Section C — for (C-style) + break/continue + labeled loops + while/do-while
// ============================================================================

function sectionC(): void {
  sectionBanner("C — for (C-style), break/continue, labeled loops, while, do-while");

  // (1) Classic C-style for loop with break and continue.
  const evens: number[] = [];
  for (let i = 0; i < 10; i++) {
    if (i % 2 !== 0) continue; // skip odds
    if (i === 8) break; // stop before 8
    evens.push(i);
  }
  console.log(`for + continue + break -> ${JSON.stringify(evens)}   (evens 0,2,4,6; 8 broke)`);
  check("for/continue/break collected [0,2,4,6]", JSON.stringify(evens) === "[0,2,4,6]");

  // (2) LABELED break/continue — the ONLY way to control an OUTER loop from an
  // inner one. A bare `break`/`continue` only affects the INNERMOST loop.
  const grid: ReadonlyArray<ReadonlyArray<number>> = [
    [1, 2, 3],
    [4, 5, 6],
    [7, 8, 9],
  ];
  let foundR = -1;
  let foundC = -1;
  outer: for (let r = 0; r < grid.length; r++) {
    const row = grid[r]!;
    for (let c = 0; c < row.length; c++) {
      if (row[c]! % 2 === 0) {
        foundR = r;
        foundC = c;
        break outer; // exits BOTH loops (bare `break` would exit only the inner)
      }
    }
  }
  const foundVal = grid[foundR]![foundC]!;
  console.log(`labeled break: first even at grid[${foundR}][${foundC}] = ${foundVal}`);
  check("labeled break found grid[0][1] = 2", foundR === 0 && foundC === 1 && foundVal === 2);

  // (3) LABELED continue — skip to the next iteration of the OUTER loop.
  // Keep only the rows whose element-sum is even.
  const evenSumRows: number[] = [];
  rowLoop: for (let r = 0; r < grid.length; r++) {
    const row = grid[r]!;
    let sum = 0;
    for (let c = 0; c < row.length; c++) {
      sum += row[c]!;
    }
    if (sum % 2 !== 0) continue rowLoop; // skip odd-sum rows
    evenSumRows.push(r);
  }
  // row sums: 6 (even), 15 (odd), 24 (even) -> [0, 2]
  console.log(`labeled continue: rows with even element-sum = ${JSON.stringify(evenSumRows)}`);
  check("labeled continue kept rows [0,2]", JSON.stringify(evenSumRows) === "[0,2]");

  // (4) while and do-while. do-while runs the body AT LEAST ONCE, even when the
  // condition is false on the first check — the only loop with that guarantee.
  let w = 0;
  while (w < 3) w++;
  console.log("");
  console.log(`while (w<3) w++  -> w = ${w}`);
  check("while loop reached 3", w === 3);

  let dw = -1;
  let dwIters = 0;
  do {
    dw = -1; // pretend a value
    dwIters++;
  } while (dw > 0); // FALSE on first check, but body already ran once
  console.log(`do { } while (dw>0): ran ${dwIters} time(s)   (body runs once even when condition is false)`);
  check("do-while ran exactly once despite a false condition", dwIters === 1);
}

// ============================================================================
// Section D — for...of (VALUES via the iterator protocol) vs for...in (STRING
// KEYS + the INHERITED prototype-key trap) — THE payoff
// ============================================================================

function sectionD(): void {
  sectionBanner("D — for...of (values) vs for...in (string keys + prototype trap)");

  const nums = [10, 20, 30];

  // (1) for...of iterates VALUES via the iterator protocol (Symbol.iterator ->
  // next()). Over an array this yields the elements themselves.
  const ofValues: number[] = [];
  for (const v of nums) ofValues.push(v);
  console.log(`for...of [10,20,30] -> ${JSON.stringify(ofValues)}   (VALUES: 10, 20, 30)`);
  check("for...of yielded the values [10,20,30]", JSON.stringify(ofValues) === "[10,20,30]");

  // (2) for...in iterates enumerable STRING KEYS — over an ARRAY this yields
  // "0","1","2" (the index STRINGS), NOT the values. (A common beginner mix-up.)
  const inKeys: string[] = [];
  for (const k in nums) inKeys.push(k);
  console.log(`for...in  [10,20,30] -> ${JSON.stringify(inKeys)}   (STRING KEYS: "0","1","2")`);
  check('for...in over array yields string keys ["0","1","2"]', JSON.stringify(inKeys) === '["0","1","2"]');

  // (3) THE prototype-pollution trap: for...in ALSO walks the INHERITED
  // enumerable prototype keys. Any enumerable prop on a prototype in the chain
  // appears in EVERY for...in loop over instances. (🔗 OBJECTS_RECORDS.)
  const proto = { inherited: "leaks-via-for-in" };
  const obj = Object.create(proto);
  obj.own = "own-prop";
  const allKeys: string[] = [];
  for (const k in obj) allKeys.push(k);
  allKeys.sort(); // deterministic: own-vs-inherited order is impl-defined
  console.log("");
  console.log(`for...in over {own} with proto {inherited} -> ${JSON.stringify(allKeys)}`);
  check("for...in sees INHERITED prototype keys (the trap)", allKeys.includes("inherited"));
  check("for...in also sees own keys", allKeys.includes("own"));

  // The fix: Object.keys() returns OWN enumerable keys only (no inherited).
  const ownKeys = Object.keys(obj).sort();
  console.log(`Object.keys(obj).sort() -> ${JSON.stringify(ownKeys)}   (OWN keys only, no inherited)`);
  check('Object.keys() excludes inherited keys (just ["own"])', JSON.stringify(ownKeys) === '["own"]');

  // (4) for...of works on ANY iterable — Map, Set, String — via
  // Symbol.iterator. for...in over a Map/Set is meaningless (they expose no
  // enumerable string-indexed entries), which is another reason never to mix them.
  const map = new Map<string, number>([
    ["a", 1],
    ["b", 2],
  ]);
  const mapEntries: string[] = [];
  for (const [k, v] of map) mapEntries.push(`${k}=${v}`);
  console.log("");
  console.log(`for...of Map -> ${JSON.stringify(mapEntries)}`);
  check('for...of Map yields [["a",1],["b",2]] as entries', JSON.stringify(mapEntries) === '["a=1","b=2"]');

  const set = new Set<string>(["x", "y", "z"]);
  const setVals: string[] = [];
  for (const s of set) setVals.push(s);
  console.log(`for...of Set -> ${JSON.stringify(setVals)}`);
  check('for...of Set yields ["x","y","z"]', JSON.stringify(setVals) === '["x","y","z"]');

  // (5) VALUE-VS-REFERENCE axis (🔗 VALUE_VS_REFERENCE): for...of on an array
  // of OBJECTS hands you a SHARED REFERENCE to each object, NOT a copy. Mutating
  // it mutates the original. (for...in gives a string key, so this trap does
  // not arise there — but `arr[key]` after for...in has the SAME aliasing.)
  const items = [{ n: 1 }, { n: 2 }, { n: 3 }];
  for (const item of items) {
    item.n *= 10; // item ALIASES items[i], not a copy
  }
  console.log("");
  console.log(`for...of mutate items[].n -> ${JSON.stringify(items.map((x) => x.n))}   (shared refs mutated)`);
  check("for...of iterates VALUES (shared refs): mutated to [10,20,30]", JSON.stringify(items.map((x) => x.n)) === "[10,20,30]");

  // (6) THE PAYOFF: never for...in an array. Use for...of (values) or a classic
  // indexed for. for...in over an array gives string indices AND any extra
  // enumerable props someone added to the array object.
  const arrWithExtra: Array<number> & { extra?: string } = [10, 20];
  arrWithExtra.extra = "surprise"; // adding a non-index enumerable prop — DON'T
  const leakedKeys: string[] = [];
  for (const k in arrWithExtra) leakedKeys.push(k);
  leakedKeys.sort();
  console.log("");
  console.log(`for...in over array w/ extra prop -> ${JSON.stringify(leakedKeys)}   (the "extra" key leaked in!)`);
  check('for...in over array picks up extra props (["0","1","extra"])', JSON.stringify(leakedKeys) === '["0","1","extra"]');
  // for...of on the same array yields ONLY the values — the extra prop is invisible.
  const onlyVals: number[] = [];
  for (const v of arrWithExtra) onlyVals.push(v);
  console.log(`for...of  over array w/ extra prop -> ${JSON.stringify(onlyVals)}   (extra prop invisible)`);
  check("for...of on array with extra prop yields only [10,20]", JSON.stringify(onlyVals) === "[10,20]");
}

// ============================================================================
// Section E — ?? (nullish) vs || (truthy) — THE modern trap; && / || return
// the operand VALUE (not boolean) and short-circuit
// ============================================================================

function sectionE(): void {
  sectionBanner("E — ?? (nullish) vs || (truthy) + &&/|| short-circuit return values");

  // ?? (nullish coalescing, ES2020): the RHS runs ONLY when the LHS is null or
  // undefined. So 0, "", false, NaN are PRESERVED (not replaced).
  const nullishCases: ReadonlyArray<readonly [string, unknown, unknown]> = [
    ["0 ?? 99", 0, 0],
    ['"" ?? 99', "", ""],
    ["false ?? 99", false, false],
    ["NaN ?? 99", NaN, NaN],
    ["null ?? 99", null, 99],
    ["undefined ?? 99", undefined, 99],
  ];
  console.log("?? nullish coalescing (RHS only for null/undefined):");
  for (const [label, lhs, expected] of nullishCases) {
    const result = (lhs as number | string | boolean | null | undefined) ?? 99;
    const ok = Object.is(result, expected);
    console.log(`  ${label.padEnd(20)} -> ${show(result)}`);
    check(`${label} -> ${show(expected)}`, ok);
  }

  // || logical OR: the RHS runs when the LHS is ANY falsy value. So 0, "", false,
  // NaN are all REPLACED by the RHS — THE classic bug.
  const orCases: ReadonlyArray<readonly [string, unknown, unknown]> = [
    ["0 || 99", 0, 99],
    ['"" || 99', "", 99],
    ["false || 99", false, 99],
    ["NaN || 99", NaN, 99],
    ["null || 99", null, 99],
    ["undefined || 99", undefined, 99],
    ["42 || 99", 42, 42], // truthy -> kept
  ];
  console.log("");
  console.log("|| logical OR (RHS for ANY falsy — the trap):");
  for (const [label, lhs, expected] of orCases) {
    const result = (lhs as number | string | boolean | null | undefined) || 99;
    const ok = Object.is(result, expected);
    console.log(`  ${label.padEnd(20)} -> ${show(result)}`);
    check(`${label} -> ${show(expected)}`, ok);
  }

  // THE CONTRAST pinned side by side (the headline of this section). The helper
  // calls prevent TS from const-folding the literals; at runtime they ARE the
  // real `??` and `||` operators.
  console.log("");
  console.log('THE contrast (0 and "" preserved by ??, dropped by ||):');
  console.log(`  0 ?? 99  -> ${show(nullish(0, 99))}     vs   0 || 99  -> ${show(or(0, 99))}`);
  console.log(`  "" ?? 99 -> ${show(nullish("", 99))}     vs   "" || 99 -> ${show(or("", 99))}`);
  console.log(`  null ?? 99  -> ${show(nullish(null, 99))}   vs   null || 99  -> ${show(or(null, 99))}`);
  check("0 ?? 99 === 0 (?? preserves 0)", Object.is(nullish(0, 99), 0));
  check("0 || 99 === 99 (|| drops 0) — THE trap", Object.is(or(0, 99), 99));
  check('"" ?? 99 === "" (?? preserves "")', Object.is(nullish("", 99), ""));
  check('"" || 99 === 99 (|| drops "")', Object.is(or("", 99), 99));
  check("null ?? 99 === 99 (null triggers ??)", Object.is(nullish(null, 99), 99));

  // && and || are SHORT-CIRCUIT and RETURN ONE OF THE OPERANDS (not a boolean).
  // They use ToBoolean only to DECIDE which operand to return; the operand
  // value itself is what comes back. This is why `x = a || default` works as a
  // "default value" idiom, and `1 && 2` is `2`, not `true`.
  console.log("");
  console.log("&& and || return the operand VALUE (not boolean):");
  console.log(`  1 && 2     -> ${show(and(1, 2))}    (both truthy -> returns the LAST, 2)`);
  console.log(`  0 && 2     -> ${show(and(0, 2))}    (LHS falsy -> short-circuits to the LHS, 0)`);
  console.log(`  null && 2  -> ${show(and(null, 2))}   (LHS null -> short-circuits, RHS NOT evaluated)`);
  console.log(`  1 || 2     -> ${show(or(1, 2))}    (LHS truthy -> returns the LHS, 1)`);
  console.log(`  0 || 2     -> ${show(or(0, 2))}    (LHS falsy -> returns the RHS, 2)`);
  check("1 && 2 === 2 (returns operand value, not boolean)", Object.is(and(1, 2), 2));
  check("0 && 2 === 0 (short-circuits to falsy LHS)", Object.is(and(0, 2), 0));
  check("null && 2 === null (short-circuits, RHS NOT evaluated)", Object.is(and(null, 2), null));
  check("1 || 2 === 1 (returns the truthy LHS)", Object.is(or(1, 2), 1));
  check("0 || 2 === 2 (returns the RHS)", Object.is(or(0, 2), 2));

  // Prove the RHS is NOT evaluated when the LHS short-circuits (vs IS for ??).
  let sideEffectCount = 0;
  const rhs = (): number => {
    sideEffectCount++;
    return 99;
  };
  const lhsNull: number | null = null;
  void (lhsNull && rhs()); // LHS null -> short-circuits, rhs NOT called
  check("null && rhs(): rhs NOT evaluated (short-circuit)", sideEffectCount === 0);
  void (lhsNull ?? rhs()); // LHS null -> ?? triggers, rhs IS called
  check("null ?? rhs(): rhs IS evaluated (null triggers ??)", sideEffectCount === 1);

  // CAVEAT: ?? CANNOT be mixed unparenthesized with && or || — it is a
  // SyntaxError. You must add parentheses to disambiguate precedence.
  check("(null || undefined) ?? 99 === 99 (parenthesized mixing is OK)", Object.is(nullish(or(null, undefined), 99), 99));
}

// ============================================================================
// Section F — ?. optional chaining (?.prop / ?.method / fn?.()) + the && guard
// idiom; plus the rare comma operator
// ============================================================================

function sectionF(): void {
  sectionBanner("F — ?. optional chaining (property / method / call) + comma operator");

  // ?. short-circuits to `undefined` when the LHS is null/undefined, instead of
  // throwing "cannot read property of undefined". Three forms:
  //   obj?.prop     -> property access (short-circuits if obj is null/undefined)
  //   obj?.[expr]   -> computed property access
  //   fn?.(args)    -> conditional CALL (only invoked if fn is not null/undefined)

  type Nested = { a?: { b?: { c?: number } }; fn?: () => string };

  // (1) Property chaining — short-circuits to undefined at the first null/undef.
  const empty: Nested = {};
  const present: Nested = { a: { b: { c: 42 } } };
  console.log(`empty.a?.b?.c    -> ${show(empty.a?.b?.c)}   (short-circuited at .a)`);
  console.log(`present.a?.b?.c  -> ${show(present.a?.b?.c)}   (walked the whole chain)`);
  check("empty.a?.b?.c === undefined (short-circuit)", empty.a?.b?.c === undefined);
  check("present.a?.b?.c === 42 (full chain walked)", present.a?.b?.c === 42);

  // THE contrast: WITHOUT ?., accessing a property of undefined THROWS TypeError.
  // We catch it to prove the mechanism (commented-out line would crash the run).
  let threw = false;
  try {
    // Intentionally unsafe access to demonstrate the throw ?.' prevents:
    const a = empty.a as { b: { c?: number } }; // a IS undefined at runtime
    void a.b; // undefined.b -> throws TypeError
  } catch (e) {
    threw = e instanceof TypeError;
  }
  console.log(`without ?., undefined.b -> threw TypeError? ${threw}`);
  check("without ?., undefined.b THREW TypeError (vs ?. returning undefined)", threw);

  // (2) Conditional CALL: fn?.(args) only invokes fn when it is not
  // null/undefined; otherwise the whole expression is undefined (no throw).
  const withFn: Nested = { fn: () => "called!" };
  const withoutFn: Nested = {};
  console.log("");
  console.log(`withFn.fn?.()    -> ${show(withFn.fn?.())}`);
  console.log(`withoutFn.fn?.() -> ${show(withoutFn.fn?.())}   (fn missing -> undefined, NO throw)`);
  check('withFn.fn?.() === "called!"', withFn.fn?.() === "called!");
  check("withoutFn.fn?.() === undefined (conditional call)", withoutFn.fn?.() === undefined);

  // (3) The && guard idiom — the PRE-optional-chaining way to safely access.
  // ?. replaces it more concisely; both yield the same result for the
  // null/undefined case, but ?. also handles the SHORT-CIRCUIT without
  // re-evaluating the LHS.
  const maybe: { data?: { value: number } } = {};
  const legacy = maybe.data && maybe.data.value; // undefined (data missing -> && short-circuits)
  const modern = maybe.data?.value; // undefined (same result)
  console.log("");
  console.log(`maybe.data && maybe.data.value -> ${show(legacy)}   (legacy && guard)`);
  console.log(`maybe.data?.value             -> ${show(modern)}   (modern ?.)`);
  check("&& guard and ?. both yield undefined for missing path", legacy === undefined && modern === undefined);

  // (4) Idiomatic combo: ?. + ?? for "drill in, then default".
  const config: { opts?: { retries?: number } } = {};
  const retries = config.opts?.retries ?? 3; // missing -> 3 (NOT 0 || 3 = 3, but ?? is clearer)
  console.log("");
  console.log(`config.opts?.retries ?? 3 -> ${retries}   (drilled with ?., defaulted with ??)`);
  check("config.opts?.retries ?? 3 === 3 (?. + ?? default)", retries === 3);

  // (5) Comma operator (rare): evaluates BOTH operands left-to-right, returns
  // the LAST. Almost never used outside a for-loop's init/post clauses, but it
  // is a real operator. Each operand's side effect runs.
  let counter = 0;
  const commaResult = (counter++, counter++, counter++);
  console.log("");
  console.log(`(c++, c++, c++) -> result=${commaResult}, counter now ${counter}   (returns the LAST operand)`);
  check("comma operator returned the last operand (2)", commaResult === 2);
  check("comma operator evaluated all three (counter now 3)", counter === 3);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("control_flow.ts — Phase 1 bundle (control flow).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Sharp edges pinned: switch has no auto-fallthrough (the missing-break");
  console.log("bug); for...of iterates VALUES, for...in iterates string keys AND");
  console.log("inherited prototype keys; 0 ?? 99 === 0 but 0 || 99 === 99 (THE trap).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionF();
  sectionBanner("DONE — all sections printed");
}

main();
