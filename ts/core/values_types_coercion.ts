// values_types_coercion.ts — Phase 1 bundle #1 (STYLE ANCHOR).
//
// GOAL (one line): show, by printing every value, how TS/JS's primitive types,
// typeof, truthiness, and ==/=== coercion behave — pinning the typeof-null lie
// and the famous coercion surprises as check()'d invariants.
//
// This is the GROUND TRUTH for VALUES_TYPES_COERCION.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle is the foundation): TypeScript adds a STATIC type
// system on top of JavaScript's runtime. That static layer is ERASED at runtime
// by tsx / esbuild / tsc --noEmit: `interface`, `type`, annotations and
// generics leave NO trace in the executed code. So at runtime every TS program
// is a plain JS program, and the only type information that survives is what
// the RUNTIME operators `typeof` / `instanceof` can see. Understanding the JS
// runtime value model (7 primitives vs Object; coercion; truthiness; equality)
// is therefore the foundation everything else (SCOPE_HOISTING, VALUE_VS_
// REFERENCE, the event loop) stands on.
//
// Run:
//     pnpm exec tsx values_types_coercion.ts   (or: just run values_types_coercion)

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

// --- typed wrappers (keep comparisons legal under strict mode, no `any`) -----
//
// TS's `==` / `===` require operand types to overlap; routing both sides
// through `unknown` keeps the comparison legal for ANY pair (e.g. [] == false)
// while the runtime operator still does its real coercing/strict work.
// `as number` casts below are TYPE-ONLY and erased at runtime (assertions emit
// no code), so unary + and binary + still perform their full ToNumber /
// ToPrimitive coercion on the original values.

function looseEq(a: unknown, b: unknown): boolean {
  return a == b; // abstract (loose) equality: coerces per ECMA-262
}

function strictEq(a: unknown, b: unknown): boolean {
  return a === b; // strict equality: never coerces
}

// not runs the REAL logical-NOT (ToBoolean then invert). Typed on `unknown` so
// TS cannot const-fold it (it would otherwise flag e.g. `![]` as always-false).
function not(v: unknown): boolean {
  return !v;
}

// runtimePlus runs the REAL binary `+` operator on any two values (ToPrimitive
// then string-concat or numeric-add, exactly as the spec dictates).
function runtimePlus(a: unknown, b: unknown): string | number {
  return (a as number) + (b as number);
}

// toNumber runs the REAL unary `+` operator (the ToNumber abstract operation).
function toNumber(x: unknown): number {
  return +(x as number);
}

// eqRow prints one row of a coercion table and asserts its expected result.
function eqRow(expr: string, actual: boolean, expected: boolean = true): void {
  console.log(`  ${expr.padEnd(26)} -> ${actual}`);
  check(`${expr} === ${expected}`, actual === expected);
}

// legacyIsNaN surfaces the GLOBAL isNaN's coercing behavior. TS types the
// global's parameter as `number`; we widen to `unknown` (type-only cast) to
// demonstrate the real legacy coercion (ToNumber first).
function legacyIsNaN(value: unknown): boolean {
  return globalThis.isNaN(value as number);
}

// ============================================================================
// Section A — The 7 primitives + typeof (and the null lie)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — The 7 primitives + typeof (and the null lie)");

  // One representative value of each of the 7 JS primitive types, plus null
  // (a primitive that typeof MISLABELS), plus an Object, an Array, and a
  // Function (functions are callable objects -> typeof "function").
  const sym = Symbol("id");

  console.log("value               : typeof");
  console.log("------------------- : ----------------");
  console.log(`"hello"             : ${typeof "hello"}`);
  console.log(`42                  : ${typeof 42}`);
  console.log(`0n                  : ${typeof 0n}`);
  console.log(`true                : ${typeof true}`);
  console.log(`undefined           : ${typeof undefined}`);
  console.log(`Symbol("id")        : ${typeof sym}`);
  console.log(`null                : ${typeof null}     <-- THE LIE (null is a primitive)`);
  console.log(`{}                  : ${typeof {}}`);
  console.log(`[]                  : ${typeof []}`);
  console.log(`function () {}      : ${typeof function () {}}`);

  console.log("");
  console.log("typeof returns EXACTLY one of these 8 strings:");
  console.log('  "string"  "number"  "bigint"  "boolean"');
  console.log('  "undefined"  "symbol"  "object"  "function"');
  console.log("There is NO \"null\" return value — null is reported as \"object\".");

  check('typeof "hello" === "string"', typeof "hello" === "string");
  check('typeof 42 === "number"', typeof 42 === "number");
  check('typeof 0n === "bigint"', typeof 0n === "bigint");
  check('typeof true === "boolean"', typeof true === "boolean");
  check('typeof undefined === "undefined"', typeof undefined === "undefined");
  check('typeof Symbol("id") === "symbol"', typeof sym === "symbol");
  check('typeof {} === "object"', typeof {} === "object");
  check('typeof [] === "object"', typeof [] === "object");
  check('typeof function(){} === "function"', typeof function () {} === "function");

  // THE FAMOUS LIE: typeof null === "object". null IS a primitive (the only
  // primitive without a typeof of its own). Legacy bug from 1995: JS values
  // carried a 3-bit type tag, the object tag was 0, and null (the NULL pointer
  // 0x00) shared that 0 tag. A fix was proposed (opt-in) and rejected for
  // backward compatibility — it can never change.
  check('typeof null === "object" (THE LIE)', typeof null === "object");

  // Primitive-vs-object identity (the value-vs-reference axis, in miniature):
  // primitives COPY on assignment; objects SHARE one reference (aliasing).
  // (Full treatment: VALUE_VS_REFERENCE.md.)
  let p = 5;
  const q = p; // q gets a copy of the value 5
  p = 6; // reassigning p does NOT touch q
  check("primitives copy: q stays 5 after p = 6", q === 5);

  const o = { n: 1 };
  const r = o; // r ALIASES o — same object in memory, no copy
  o.n = 2; // mutating through o is visible through r
  check("objects alias: r.n === 2 after o.n = 2 (shared reference)", r.n === 2);
}

// ============================================================================
// Section B — null vs undefined
// ============================================================================

function sectionB(): void {
  sectionBanner("B — null vs undefined");

  // undefined: a variable declared but unassigned, OR an absent property, OR
  //   the implicit return of a function with no `return`.
  // null: an INTENTIONAL absence, assigned by the programmer.

  function returnsNothing(): undefined {
    // intentionally no return statement -> evaluates to undefined
  }

  let unassigned: string | undefined; // declared, never initialized
  const obj: Record<string, number> = { a: 1 }; // key "b" is absent
  const fromFunction = returnsNothing();

  console.log(`declared, unassigned  : ${String(unassigned)}`);
  console.log(`absent property obj.b : ${String(obj.b)}`);
  console.log(`function w/o return   : ${String(fromFunction)}`);
  console.log(`null literal          : ${String(null)}`);
  console.log(`void 0                : ${String(void 0)}   (a safe way to obtain undefined)`);

  // undefined and null are DISTINCT primitives (strict-unequal).
  check("undefined === undefined", undefined === undefined);
  check("null === null", null === null);
  check("undefined !== null (strict)", undefined !== null);
  check("null === undefined is false (strict)", strictEq(null, undefined) === false);

  // The ONE famous loose bridge: null == undefined is true — and ONLY null and
  // undefined loosely equal each other. null does NOT coerce to 0 or "" under
  // == (a common misconception).
  check("null == undefined is true", looseEq(null, undefined) === true);
  check('null == 0 is false (null does NOT coerce to 0 under ==)', looseEq(null, 0) === false);
  check('null == "" is false', looseEq(null, "") === false);
  check("null == false is false", looseEq(null, false) === false);
  check("void 0 === undefined", void 0 === undefined);
}

// ============================================================================
// Section C — Truthiness: the exact falsy set + truthy-empty traps
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Truthiness: the exact falsy set + truthy-empty traps");

  // The COMPLETE list of falsy values (MDN "Falsy"). In a JS runtime there are
  // EIGHT standard falsy values. A 9th, document.all, exists ONLY in browsers
  // (a host-object web-compat hack) and is irrelevant here in Node.
  const falsy: ReadonlyArray<readonly [string, unknown]> = [
    ["false", false],
    ["0", 0],
    ["-0", -0],
    ["0n", 0n],
    ['""', ""],
    ["null", null],
    ["undefined", undefined],
    ["NaN", NaN],
  ];

  console.log("Falsy values (Boolean(x) === false):");
  for (const [label, value] of falsy) {
    console.log(`  ${label.padEnd(12)} -> Boolean -> ${Boolean(value)}`);
    check(`Boolean(${label}) === false`, Boolean(value) === false);
  }

  // EVERYTHING ELSE is truthy. The expert traps are the EMPTY containers and
  // the non-empty strings "0" / "false", which LOOK falsy but are NOT.
  const truthyTraps: ReadonlyArray<readonly [string, unknown]> = [
    ["[] (empty array)", []],
    ["{} (empty object)", {}],
    ['"0" (non-empty string)', "0"],
    ['"false" (non-empty string)', "false"],
    ['" " (whitespace string)', " "],
    ["Infinity", Infinity],
    ["-Infinity", -Infinity],
    ["42", 42],
    ["new Date(0)", new Date(0)],
  ];

  console.log("");
  console.log("Truthy-empty traps (Boolean(x) === true, despite looking empty):");
  for (const [label, value] of truthyTraps) {
    console.log(`  ${label.padEnd(28)} -> Boolean -> ${Boolean(value)}`);
    check(`Boolean(${label}) === true`, Boolean(value) === true);
  }

  // 0 and -0 are BOTH falsy, but they are DISTINCT values. === CANNOT tell
  // them apart; only Object.is (SameValue) can. (NaN is the other value that
  // === gets "wrong": Object.is(NaN, NaN) === true.)
  check("0 === -0 is true (=== cannot distinguish them)", 0 === -0);
  check("Object.is(0, -0) === false (SameValue CAN distinguish them)", Object.is(0, -0) === false);
  check("Object.is(NaN, NaN) === true (=== gets NaN wrong)", Object.is(NaN, NaN) === true);
}

// ============================================================================
// Section D — == (loose, coerces) vs === (strict, no coercion)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — == (loose, coerces) vs === (strict, no coercion)");

  console.log("Loose == coercion table (each pair coerced per ECMA-262 abstract equality):");
  eqRow('0 == ""', looseEq(0, ""));
  eqRow("0 == false", looseEq(0, false));
  eqRow('0 == "0"', looseEq(0, "0"));
  eqRow('"" == false', looseEq("", false));
  eqRow('"0" == false', looseEq("0", false));
  eqRow('"0" == 0', looseEq("0", 0));
  eqRow("null == undefined", looseEq(null, undefined));
  eqRow("NaN == NaN", looseEq(NaN, NaN), false);

  // The notorious object/array coercions (the expert payoff). == reduces each
  // side via ToPrimitive -> ToNumber, so an empty array walks to "" -> 0.
  console.log("");
  console.log("Notorious object/array coercions (ToPrimitive -> ToNumber):");
  eqRow("[] == false", looseEq([], false));
  eqRow("[] == ![]", looseEq([], not([])));
  eqRow("[0] == false", looseEq([0], false));
  eqRow("[null] == 0", looseEq([null], 0)); // [null] -> toString -> "" -> 0
  eqRow('[1,2,3] == "1,2,3"', looseEq([1, 2, 3], "1,2,3"));

  console.log("");
  console.log("Strict === never coerces (the safe default — always prefer ===):");
  eqRow("null === undefined", strictEq(null, undefined), false);
  eqRow('0 === ""', strictEq(0, ""), false);
  eqRow('"0" === 0', strictEq("0", 0), false);

  // Worked smallest-scale example: trace [] == false step by step through the
  // abstract-equality + ToPrimitive algorithm, so the "true" result is no
  // longer magic.
  console.log("");
  console.log("Worked trace: [] == false  (ECMA-262 abstract equality + ToPrimitive)");
  const rhsNum = toNumber(false); // step 1: ToNumber(false) -> 0
  const arr: unknown[] = []; // the LHS operand
  const valueOfResult = arr.valueOf(); // step 2a: valueOf() returns the array itself
  const primStr = arr.toString(); // step 2b: not primitive -> use toString() -> ""
  const lhsNum = toNumber(primStr); // step 3: ToNumber("") -> 0
  console.log(`    1. RHS false  -> ToNumber  -> ${rhsNum}`);
  console.log(`    2. LHS [].valueOf()  -> ${JSON.stringify(valueOfResult)} (not a primitive; ignored)`);
  console.log(`    3. LHS [].toString() -> ${JSON.stringify(primStr)}`);
  console.log(`    4. LHS ""     -> ToNumber  -> ${lhsNum}`);
  console.log(`    5. compare ${lhsNum} == ${rhsNum}  -> ${lhsNum == rhsNum}`);
  check("[] == false === true (the step trace confirms it)", looseEq([], false) === true);
}

// ============================================================================
// Section E — NaN, isNaN vs Number.isNaN, and the abstract operations
// ============================================================================

function sectionE(): void {
  sectionBanner("E — NaN, isNaN vs Number.isNaN, and the abstract operations");

  // NaN is the only value not equal to itself — under BOTH == and ===.
  console.log(`NaN === NaN -> ${strictEq(NaN, NaN)}`);
  console.log(`NaN == NaN  -> ${looseEq(NaN, NaN)}`);
  console.log(`typeof NaN  -> ${typeof NaN}   (NaN IS a number, despite the name "Not-a-Number")`);
  check("NaN === NaN is false (not equal to itself)", strictEq(NaN, NaN) === false);
  check("NaN == NaN is false (loose equality also fails)", looseEq(NaN, NaN) === false);
  check('typeof NaN === "number"', typeof NaN === "number");

  // Number.isNaN (ES2015) does NOT coerce: it returns true ONLY for the actual
  // NaN value. The global isNaN coerces via ToNumber FIRST, so isNaN("foo") is
  // true (Number("foo") is NaN) — a classic false-positive trap.
  console.log("");
  console.log("isNaN vs Number.isNaN (the expert trap):");
  console.log(`  Number.isNaN(NaN)    -> ${Number.isNaN(NaN)}`);
  console.log(`  Number.isNaN("foo")  -> ${Number.isNaN("foo")}   (no coercion: "foo" is not the NaN value)`);
  console.log(`  isNaN("foo")         -> ${legacyIsNaN("foo")}   (global coerces "foo" -> NaN first)`);
  console.log(`  isNaN(undefined)     -> ${legacyIsNaN(undefined)}   (ToNumber(undefined) = NaN)`);
  console.log(`  isNaN("")            -> ${legacyIsNaN("")}   (ToNumber("") = 0, so NOT NaN)`);
  check("Number.isNaN(NaN) === true", Number.isNaN(NaN) === true);
  check('Number.isNaN("foo") === false (no coercion)', Number.isNaN("foo") === false);
  check('isNaN("foo") === true (global coerces first)', legacyIsNaN("foo") === true);
  check('isNaN("") === false (ToNumber("") === 0)', legacyIsNaN("") === false);

  // ToNumber via unary +x — the abstract op that drives ==, -, *, / and the
  // numeric branch of binary +.
  console.log("");
  console.log("ToNumber via unary +x  (drives ==, arithmetic, and the numeric + branch):");
  const toNum: ReadonlyArray<readonly [string, number]> = [
    ['+"5"', toNumber("5")],
    ['+""', toNumber("")],
    ['+"foo"', toNumber("foo")],
    ['+true', toNumber(true)],
    ['+false', toNumber(false)],
    ['+null', toNumber(null)],
    ['+undefined', toNumber(undefined)],
    ['+[]', toNumber([])],
    ['+[5]', toNumber([5])],
    ['+[1,2]', toNumber([1, 2])],
    ['+{}', toNumber({})],
  ];
  for (const [label, value] of toNum) {
    console.log(`  ${label.padEnd(12)} -> ${String(value)}`);
  }
  check('+"" === 0', toNumber("") === 0);
  check('+"foo" is NaN', Number.isNaN(toNumber("foo")));
  check("+[] === 0", toNumber([]) === 0);
  check("+[5] === 5", toNumber([5]) === 5);
  check("+[1,2] is NaN (toString \"1,2\" is not numeric)", Number.isNaN(toNumber([1, 2])));
  check("+{} is NaN", Number.isNaN(toNumber({})));
  check("+null === 0", toNumber(null) === 0);
  check("+undefined is NaN", Number.isNaN(toNumber(undefined)));
  check("+true === 1", toNumber(true) === 1);

  // ToString via String(x) — the abstract op for string contexts. Note how
  // ToString HIDES negative zero (String(-0) === "0").
  console.log("");
  console.log("ToString via String(x):");
  const toStr: ReadonlyArray<readonly [string, string]> = [
    ["String(123)", String(123)],
    ["String(-0)", String(-0)],
    ["String(true)", String(true)],
    ["String(null)", String(null)],
    ["String(undefined)", String(undefined)],
    ["String([])", String([])],
    ["String([1,2])", String([1, 2])],
    ["String([null,undefined])", String([null, undefined])],
    ["String({})", String({})],
    ["String(NaN)", String(NaN)],
    ["String(Symbol('s'))", String(Symbol("s"))],
  ];
  for (const [label, value] of toStr) {
    console.log(`  ${label.padEnd(28)} -> ${JSON.stringify(value)}`);
  }
  check('String(null) === "null"', String(null) === "null");
  check('String([]) === ""', String([]) === "");
  check('String([1,2]) === "1,2"', String([1, 2]) === "1,2");
  check('String({}) === "[object Object]"', String({}) === "[object Object]");
  check('String(-0) === "0" (ToString hides negative zero)', String(-0) === "0");

  // ToPrimitive in action: binary + coerces BOTH operands via ToPrimitive
  // (default hint -> valueOf then toString) before deciding concat vs add.
  console.log("");
  console.log("ToPrimitive in action (binary + coerces both sides):");
  console.log(`  [] + []        -> ${JSON.stringify(runtimePlus([], []))}         (both -> "" -> "")`);
  console.log(`  [] + {}        -> ${JSON.stringify(runtimePlus([], {}))}   ("" + "[object Object]")`);
  console.log(`  [1,2] + [3,4]  -> ${JSON.stringify(runtimePlus([1, 2], [3, 4]))}     ("1,2" + "3,4")`);
  console.log(`  1 + "2"        -> ${JSON.stringify(runtimePlus(1, "2"))}        (number meets string -> concat)`);
  check('[] + [] === ""', runtimePlus([], []) === "");
  check('[] + {} === "[object Object]"', runtimePlus([], {}) === "[object Object]");
  check('[1,2] + [3,4] === "1,23,4"', runtimePlus([1, 2], [3, 4]) === "1,23,4");
  check('1 + "2" === "12"', runtimePlus(1, "2") === "12");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("values_types_coercion.ts — Phase 1 bundle #1 (style anchor).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TypeScript types are ERASED at runtime (tsx/tsc strip them).");
  console.log('So `typeof` (a runtime operator) sees only JS primitives/objects,');
  console.log("never your annotations, interfaces, or generics.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
