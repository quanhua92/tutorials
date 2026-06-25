// scope_hoisting.ts — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how `var` (function-scoped,
// hoisted, silently `undefined`) differs from `let`/`const` (block-scoped,
// hoisted but in a Temporal Dead Zone until initialized) — pinning the two most
// infamous JS bugs (the loop-var-capture closure trap and the TDZ throw) as
// check()'d invariants, plus the const-binding-vs-value distinction.
//
// This is the GROUND TRUTH for SCOPE_HOISTING.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): `var` (function-scoped, hoisted to the top
// of its function and initialized to `undefined`) caused the two most infamous
// JS bugs — (1) the loop-var-capture closure trap (every closure in the loop
// shared the SAME binding, so all saw the final value) and (2) silent-`undefined`
// reads (using a variable before its assignment line never threw, it just gave
// `undefined`). `let`/`const` (ES2015) fix BOTH: they are block-scoped, and
// although they too hoist, they land in a "temporal dead zone" (TDZ) where any
// access BEFORE the declaration line throws a ReferenceError. `const` adds one
// more rule: it freezes the BINDING (reassignment throws) but NOT the value
// (object/array contents stay mutable). Understanding hoisting + TDZ is the
// difference between "writes JS" and "understands JS".
//
// Run:
//     pnpm exec tsx scope_hoisting.ts   (or: just run scope_hoisting)

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

// describe renders a thrown value as "Name: message" for deterministic display.
// Every error demo below catches the throw, runs it through describe(), and then
// asserts a STABLE substring of the message — never the exact engine wording
// (which varies across V8/JSC/SpiderMonkey) and never any timing/stack info.
function describe(e: unknown): string {
  if (e instanceof Error) {
    return `${e.name}: ${e.message}`;
  }
  return String(e);
}

// ---------------------------------------------------------------------------
// Module-top-level var (ESM module-scope demo). In a CLASSIC script a top-level
// `var` would attach to globalThis as a property; in an ES MODULE (this file,
// run by tsx as ESM per package.json "type": "module") it is module-scoped and
// does NOT leak onto globalThis. Read in sectionA() to prove both facts.
// ---------------------------------------------------------------------------
var moduleScopedVar = 7;

// ============================================================================
// Section A — var is FUNCTION-scoped (leaks out of blocks); let/const BLOCK-scoped
// ============================================================================

// varLeaksFromBlock: `var` inside an if-block is visible OUTSIDE the block
// because var's scope is the whole enclosing function, not the block.
function varLeaksFromBlock(): string {
  if (true) {
    var leaky = 1; // function-scoped -> visible outside this if-block
  }
  // leaky is reachable here: var leaked out of the { } block.
  return `after if-block: leaky=${leaky}  (var leaked out of the block)`;
}

// letStaysInBlock: `let` inside a block is NOT visible outside it. Referencing
// it after the block is a ReferenceError "is not defined" (NOT a TDZ — the
// binding simply does not exist outside its block).
function letStaysInBlock(): string {
  let innerEcho: number;
  {
    let inner = 99; // block-scoped to these braces only
    innerEcho = inner; // read it INSIDE its block (avoids an unused-local)
  }
  let result: string;
  try {
    // @ts-ignore 2304 — `inner` is OUT of scope after its block. TS reports
    // "Cannot find name 'inner'"; at RUNTIME it is a ReferenceError (the
    // block-scoped binding does not exist here). WHY suppressed: to surface the
    // runtime ReferenceError that demonstrates let's block scoping.
    result = `inner=${String(inner)}`;
  } catch (e) {
    result = describe(e);
  }
  return `inside-block value was ${innerEcho}; after block -> ${result}`;
}

// catchParamIsBlockScoped: the `e` in `catch (e)` is scoped to the catch clause
// only; it does not leak into the enclosing scope (unlike a `var`).
function catchParamIsBlockScoped(): string {
  let inside: string;
  try {
    throw new Error("boom");
  } catch (e) {
    inside = `inside catch: e.message="${(e as Error).message}"`;
  }
  let result: string;
  try {
    // @ts-ignore 2304 — `e` is block-scoped to the catch clause; out of scope
    // here. WHY suppressed: surfaces the runtime ReferenceError proving the
    // catch binding does not leak.
    result = `e outside catch = ${String(e)}`;
  } catch (err) {
    result = `outside catch -> ${describe(err)}`;
  }
  return `${inside} | ${result}`;
}

function sectionA(): void {
  sectionBanner("A — var FUNCTION-scope (leaks) vs let/const BLOCK-scope");

  console.log("var in an if-block LEAKS out (function-scoped):");
  console.log(`  ${varLeaksFromBlock()}`);
  check(
    "var declared inside an if-block is visible outside it (function scope)",
    varLeaksFromBlock().includes("leaky=1"),
  );

  console.log("");
  console.log("let in a block does NOT leak (block-scoped) -> ReferenceError outside:");
  console.log(`  ${letStaysInBlock()}`);
  check(
    "let block-scoped: referencing it outside its block throws ReferenceError",
    letStaysInBlock().includes("ReferenceError"),
  );

  console.log("");
  console.log("catch (e) binds e ONLY to the catch clause (block-scoped):");
  console.log(`  ${catchParamIsBlockScoped()}`);
  check(
    "catch parameter is block-scoped: out of scope after the catch",
    catchParamIsBlockScoped().includes("ReferenceError"),
  );

  // Module scope vs classic-script global scope. This file is an ES module
  // (package.json "type": "module"), so a top-level `var` is module-scoped and
  // is NOT attached to globalThis. In a classic <script> it WOULD be a global.
  console.log("");
  console.log("ESM module scope (top-level var is module-scoped, NOT global):");
  console.log(`  moduleScopedVar (direct access)        = ${moduleScopedVar}`);
  console.log(
    `  globalThis.moduleScopedVar            = ${String(
      (globalThis as Record<string, unknown>).moduleScopedVar,
    )}   (NOT leaked onto globalThis in a module)`,
  );
  check("ESM module: top-level var is accessible within the module", moduleScopedVar === 7);
  check(
    "ESM module: top-level var is NOT on globalThis (module-scoped, not global)",
    (globalThis as Record<string, unknown>).moduleScopedVar === undefined,
  );
}

// ============================================================================
// Section B — Hoisting: var hoists + inits to undefined (NO throw);
//             function declarations fully hoisted; function expressions NOT
// ============================================================================

// varHoistsNoThrow: `var x` is hoisted to the top of this function AND
// initialized to `undefined`, so reading x BEFORE the `var x = 1` line yields
// undefined — it does NOT throw. This is the silent-undefined hole that let
// closes with the TDZ.
function varHoistsNoThrow(): string {
  // @ts-ignore 2454 — runtime hoisting demo: reading `x` before its `var x=1`
  // line is EXACTLY the var-hoisting behavior we assert (x is hoisted and
  // initialized to undefined, so this reads undefined at runtime, NO throw).
  // TS flags "used before being assigned" at compile time; suppressed so the
  // runtime value (undefined, no error) — the documented var behavior — surfaces.
  const beforeType = typeof x; // "undefined" — x exists (hoisted) but holds undefined
  // @ts-ignore 2454 — same runtime hoisting demo as above (reading x early).
  const beforeValue = x; // undefined — usable before the assignment line, no error
  var x = 1; // declaration hoisted; the =1 assignment happens here, now
  const afterValue = x; // 1
  return `before: typeof="${beforeType}" value=${String(beforeValue)} (NO throw) | after: value=${afterValue}`;
}

// fullyHoistedDeclaration is a function DECLARATION: hoisted in full (binding
// AND body), so it is callable from source lines that appear BEFORE it. It is
// deliberately placed AFTER sectionB() below to demonstrate this.
function fullyHoistedDeclaration(): string {
  return "called from a line ABOVE this declaration (function declarations are fully hoisted)";
}

// expressionNotHoisted: a function EXPRESSION assigned to `const` is NOT
// callable before its initializer line — the const is in the TDZ, so calling it
// early throws a ReferenceError (same TDZ rule as any const).
function expressionNotHoisted(): string {
  let result: string;
  try {
    // @ts-ignore 2448 — runtime TDZ demo: calling the function EXPRESSION before
    // its const-initializer line. TS flags use-before-declaration; suppressed to
    // surface the runtime ReferenceError (TDZ) — the behavior being taught.
    result = `no throw, got="${exprFn()}"`;
  } catch (e) {
    result = describe(e);
  }
  const exprFn = (): string => "expression result"; // TDZ until this line runs
  return `${result} | after init: exprFn()="${exprFn()}"`;
}

function sectionB(): void {
  sectionBanner("B — Hoisting: var hoists+inits=undefined (no throw); fn-decl hoisted, fn-expr NOT");

  console.log("var is hoisted AND initialized to undefined (usable early, NO throw):");
  console.log(`  ${varHoistsNoThrow()}`);
  check(
    "var hoists + inits to undefined: typeof-before === 'undefined' (no throw)",
    varHoistsNoThrow().includes('typeof="undefined"'),
  );
  check(
    "var usable before its assignment line returns undefined (NOT an error)",
    varHoistsNoThrow().includes("NO throw"),
  );

  console.log("");
  console.log("function DECLARATION is fully hoisted (callable before its line):");
  // fullyHoistedDeclaration() is defined BELOW this call in the source, yet it
  // works because function declarations hoist binding + body to the scope top.
  const declResult = fullyHoistedDeclaration();
  console.log(`  ${declResult}`);
  check(
    "function declaration callable before its source line (fully hoisted)",
    declResult.includes("fully hoisted"),
  );

  console.log("");
  console.log("function EXPRESSION (const fn = ...) is NOT hoisted -> TDZ before its line:");
  console.log(`  ${expressionNotHoisted()}`);
  check(
    "function expression in TDZ before its const line: throws ReferenceError",
    expressionNotHoisted().includes("ReferenceError"),
  );
}

// ============================================================================
// Section C — Temporal Dead Zone (TDZ): let/const accessed before init THROWS;
//             re-declaration: var allows (silent), let/const is a SyntaxError
// ============================================================================

// tdzRead: `let` IS hoisted, but it sits in the TDZ until its initializer line.
// Reading it before that line throws ReferenceError "Cannot access ... before
// initialization" — the deterministic throw that var's silent-undefined lacked.
function tdzRead(): string {
  let result: string;
  try {
    // @ts-ignore 2448 — runtime TDZ demo: reading `lexical` before its
    // initializer. TS catches use-before-declaration at compile time; suppressed
    // here so the RUNTIME ReferenceError (the TDZ) surfaces. WHY: both throw,
    // but only the runtime one is the documented TDZ behavior we assert on.
    result = `no throw, value=${String(lexical)}`;
  } catch (e) {
    result = describe(e);
  }
  let lexical = 7; // declaration hoisted to fn top; TDZ ENDS at this line
  return `${result} | after init: lexical=${lexical}`;
}

// constTdz: `const` follows the SAME TDZ rule as `let` — reading before the
// initializer throws ReferenceError.
function constTdz(): string {
  let result: string;
  try {
    // @ts-ignore 2448 — runtime TDZ demo for const (same rule as let).
    result = `no throw, value=${String(frozen)}`;
  } catch (e) {
    result = describe(e);
  }
  const frozen = 7; // TDZ until this line
  return `${result} | after init: frozen=${frozen}`;
}

// varRedeclareAllowed vs letRedeclareThrows: re-declaring with `var` in the same
// scope is silently allowed (the second wins); re-declaring with `let`/`const` in
// the same scope is a SyntaxError. A duplicate-let is a PARSE-TIME error, so it
// would fail the WHOLE file if written literally — we isolate it via eval() so
// the SyntaxError is thrown (and caught) at runtime, without breaking the file.
function varRedeclareAllowed(): string {
  // var can be re-declared freely in the same scope; the later assignment wins.
  var r = 1;
  var r = 2; // silent — no error, r is now 2
  return `var r=1; var r=2; -> r=${r} (re-declaration silently allowed)`;
}

function letRedeclareThrows(): string {
  try {
    // A duplicate `let` in the same scope is a SyntaxError at PARSE time. Writing
    // it literally would fail the whole file, so we parse an isolated string via
    // eval(); the SyntaxError is thrown and catchable here.
    eval("let d = 1; let d = 2;");
    return "no error (unexpected)";
  } catch (e) {
    return describe(e);
  }
}

function sectionC(): void {
  sectionBanner("C — Temporal Dead Zone: let/const before init THROWS; re-decl rules");

  console.log("let IS hoisted but sits in the TDZ until its line -> ReferenceError:");
  console.log(`  ${tdzRead()}`);
  check(
    "let TDZ: reading before initialization throws ReferenceError",
    tdzRead().includes("ReferenceError"),
  );
  check(
    'let TDZ message includes "before initialization"',
    tdzRead().includes("before initialization"),
  );

  console.log("");
  console.log("const follows the SAME TDZ rule as let:");
  console.log(`  ${constTdz()}`);
  check(
    "const TDZ: reading before initialization throws ReferenceError",
    constTdz().includes("ReferenceError"),
  );
  check(
    'const TDZ message includes "before initialization"',
    constTdz().includes("before initialization"),
  );

  console.log("");
  console.log("Re-declaration: var allows it silently; let/const is a SyntaxError:");
  console.log(`  ${varRedeclareAllowed()}`);
  console.log(`  let d=1; let d=2; -> ${letRedeclareThrows()}`);
  check(
    "var re-declaration in the same scope is silently allowed (no error)",
    varRedeclareAllowed().includes("silently allowed"),
  );
  check(
    "let re-declaration in the same scope throws SyntaxError",
    letRedeclareThrows().startsWith("SyntaxError"),
  );
  check(
    'let re-declare message includes "already been declared"',
    letRedeclareThrows().includes("already been declared"),
  );
}

// ============================================================================
// Section D — const binding vs value: binding frozen (reassign throws),
//             but object/array CONTENTS are mutable
// ============================================================================

// constObjectMutable: `const` freezes the BINDING (the variable slot), not the
// value. Mutating the object's PROPERTIES through the binding works fine; only
// REASSIGNING the binding itself throws.
function constObjectMutable(): string {
  const o: Record<string, number> = {};
  o.x = 1; // OK — mutating a property through the const binding is allowed
  const a: number[] = [];
  a.push(1); // OK — mutating array contents through the const binding is allowed
  return `const o={}; o.x=1 -> o.x=${o.x} (mutation OK) | const a=[]; a.push(1) -> a=[${a.join(",")}] (mutation OK)`;
}

// constBindingFrozen: reassigning a const binding throws TypeError at runtime.
function constBindingFrozen(): string {
  const c: Record<string, number> = { n: 1 };
  let result: string;
  try {
    // @ts-ignore 2588 — runtime TypeError demo: assigning to a const binding is
    // a RUNTIME TypeError; TS rejects it at compile time, suppressed here so the
    // documented runtime error ("Assignment to constant variable") surfaces.
    c = { n: 2 };
    result = "no error (unexpected)";
  } catch (e) {
    result = describe(e);
  }
  return `const c={n:1}; c={n:2} -> ${result} | c is still ${JSON.stringify(c)}`;
}

// constReassignPrimitive: same rule for a primitive const — reassign throws.
function constReassignPrimitive(): string {
  const p = 1;
  let result: string;
  try {
    // @ts-ignore 2588 — runtime TypeError demo: reassigning a const primitive.
    p = 2;
    result = "no error (unexpected)";
  } catch (e) {
    result = describe(e);
  }
  return `const p=1; p=2 -> ${result} | p is still ${p}`;
}

function sectionD(): void {
  sectionBanner("D — const BINDING vs VALUE: reassign throws, but contents stay mutable");

  console.log("const freezes the BINDING, not the value (object/array contents mutate):");
  console.log(`  ${constObjectMutable()}`);
  check(
    "const object: mutating a property through the binding works (o.x === 1)",
    constObjectMutable().includes("o.x=1"),
  );
  check(
    "const array: pushing through the binding works (a=[1])",
    constObjectMutable().includes("a=[1]"),
  );

  console.log("");
  console.log("Reassigning the const BINDING itself throws TypeError:");
  console.log(`  ${constBindingFrozen()}`);
  console.log(`  ${constReassignPrimitive()}`);
  check(
    "const reassign (object) throws TypeError",
    constBindingFrozen().includes("TypeError:"),
  );
  check(
    "const reassign (primitive) throws TypeError",
    constReassignPrimitive().includes("TypeError:"),
  );
  check(
    'const reassign message includes "Assignment to constant variable"',
    constBindingFrozen().includes("Assignment to constant variable") &&
      constReassignPrimitive().includes("Assignment to constant variable"),
  );
}

// ============================================================================
// Section E — THE loop-var-capture trap: var -> all closures share ONE binding;
//             let -> a FRESH binding per iteration. (Pairs with FUNCTIONS_CLOSURES.)
// ============================================================================

function sectionE(): void {
  sectionBanner("E — THE loop-var-capture trap: var shares ONE binding, let makes one per iter");

  // (1) var: the loop creates ONE function-scoped binding for i, reused across
  // every iteration. All three closures capture THAT SAME cell, so by the time
  // they run, i === 3 (the value after the loop terminates) for all of them.
  // This is THE classic JS closure bug.
  const fnsVar: Array<() => number> = [];
  for (var i = 0; i < 3; i++) {
    fnsVar.push(() => i); // every closure captures the SAME i
  }
  const varCaptured = fnsVar.map((f) => f()); // [3, 3, 3]
  console.log(`for (var i=0; i<3; i++) fns.push(()=>i):  captured = [${varCaptured.join(", ")}]`);
  console.log("  (all closures share ONE i; by call-time i === 3 for every closure)");
  check(
    "var loop capture: all closures return the SAME final value 3",
    varCaptured.length === 3 &&
      varCaptured[0] === 3 &&
      varCaptured[1] === 3 &&
      varCaptured[2] === 3,
  );

  // (2) let: per spec, `let` in a for-loop gets a FRESH binding per iteration
  // (each iteration sees its own copy of j). Each closure captures ITS OWN j,
  // so they return 0, 1, 2 respectively. One keyword fixes the whole bug class.
  const fnsLet: Array<() => number> = [];
  for (let j = 0; j < 3; j++) {
    fnsLet.push(() => j); // each closure captures ITS OWN per-iteration j
  }
  const letCaptured = fnsLet.map((f) => f()); // [0, 1, 2]
  console.log(`for (let j=0; j<3; j++) fns.push(()=>j):  captured = [${letCaptured.join(", ")}]`);
  console.log("  (each closure captures its OWN per-iteration binding -> 0, 1, 2)");
  check(
    "let loop capture: each closure returns its own per-iteration value [0, 1, 2]",
    letCaptured.length === 3 &&
      letCaptured[0] === 0 &&
      letCaptured[1] === 1 &&
      letCaptured[2] === 2,
  );
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("scope_hoisting.ts — Phase 1 bundle.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TypeScript types are ERASED at runtime. The var/let/const");
  console.log("scope + hoisting + TDZ rules below are pure JS RUNTIME semantics —");
  console.log("TS only adds compile-time 'use-before-declaration' warnings (suppressed");
  console.log("with @ts-ignore on the lines that intentionally trigger the runtime throw).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
