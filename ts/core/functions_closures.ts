// functions_closures.ts — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how TS/JS functions are
// first-class objects (typeof "function"), how the classic `function` binds
// `this` at the CALL SITE while the ES2015 arrow captures `this` LEXICALLY,
// and how closures capture variables BY REFERENCE (a live binding) — pinning
// the detached-method `this` loss and the loop-var capture trap as check()'d
// invariants.
//
// This is the GROUND TRUTH for FUNCTIONS_CLOSURES.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): in JS, functions are first-class OBJECTS
// (callable, with .name/.length properties) — they can be assigned, passed as
// arguments, returned from functions, and stored in data structures. The
// classic `function` binds `this` DYNAMICALLY at the CALL SITE: `obj.method()`
// -> obj; a bare `fn()` -> undefined in strict mode (and ESM is ALWAYS
// strict). The ES2015 arrow function instead captures `this` LEXICALLY from
// the enclosing scope — never re-bound by call/apply/bind. Closures (a
// function bundled with its captured lexical environment) capture variables
// BY REFERENCE: a LIVE binding that sees later mutations, and the basis of
// state encapsulation (counter factories), the IIFE module pattern, and the
// famous loop-variable capture trap (previewed here, owned by
// SCOPE_HOISTING).
//
// RUNTIME NOTE (tsx/esbuild): this file's source is ESM ("type": "module"),
// but `tsx` runs it via an esbuild CJS transform. The transform's wrapper
// function sets the module's top-level `this` to an empty object `{}` (== the
// CJS module.exports) and is NON-strict by default — so the file opens with a
// `"use strict"` prologue to force strict mode in function bodies (matching
// native ESM semantics, where bare classic calls yield `this === undefined`).
// The top-level `this` itself remains `{}` under tsx (it would be `undefined`
// under native ESM); Section B observes and pins this honestly.
//
// Run:
//     pnpm exec tsx functions_closures.ts   (or: just run functions_closures)

"use strict";

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
// Module-scope setup (intentionally BEFORE some declarations, to demonstrate
// hoisting of function DECLARATIONS in Section A).
// ============================================================================

// (1) Hoisting proof: a function DECLARATION is callable BEFORE its textual
// position — the binding is hoisted to the top of the scope at parse time.
// (A function EXPRESSION assigned to `const` would be in the TDZ here and
// throw ReferenceError — see Section A and SCOPE_HOISTING for the deep dive.)
const hoistedBeforeText: string = hoistedDecl();

function hoistedDecl(): string {
  return "from declaration (hoisted)";
}

// (2) Function EXPRESSION + ARROW assigned to a const. Both are evaluated at
// their textual position (NOT hoisted) — accessing them earlier would throw.
const exprFn = function (): string {
  return "from expression";
};
const arrowFn = (): string => "from arrow";

// (3) applyTwice takes a function VALUE as an argument — proof functions are
// first-class: they can be passed around like any other value.
function applyTwice<T>(f: (x: T) => T, x: T): T {
  return f(f(x));
}

// (4) Module top-level `this`. Under native ESM this is `undefined`; under
// tsx's CJS-wrapper transform it is an empty object `{}` (see the file header
// note). Either way, it is NOT globalThis and it is NOT the receiver of any
// later method call — and an arrow defined here captures THIS value (the
// principle that matters, demonstrated in Section B).
const moduleThis: unknown = this;

// A top-level arrow captures the enclosing scope's `this` (the moduleThis
// above). The arrow NEVER creates its own `this` binding — call/apply/bind
// on it are silently no-ops on `this` (Section B/E).
const topArrow = (): unknown => this;

// (5) An object literal does NOT create a `this` scope of its own — only
// classic methods (shorthand or expression) inside it do. So an ARROW used
// as an object property captures the SURROUNDING scope's `this` (here, the
// moduleThis), NOT the object. This is THE headline trap.
const obj: {
  v: number;
  classic(): number;
  classicExpr: () => number;
  arrow: () => unknown;
} = {
  v: 1,
  // Method shorthand — a classic function. `this` is bound at the CALL SITE
  // to the receiver (obj when called as obj.classic()).
  classic(): number {
    return this.v;
  },
  // Classic function expression as a property — same binding rule.
  classicExpr: function (): number {
    return this.v;
  },
  // Arrow as a property — `this` is LEXICAL (captured from the enclosing
  // scope = moduleThis). NOT obj, no matter how it is called.
  arrow: (): unknown => this,
};

// (6) A standalone classic function with an explicit TS `this` parameter.
// The `this` param is TYPE-ONLY (erased at runtime); TS uses it to type-check
// the call site. At runtime, `this` is whatever the call site provides.
function readV(this: { v: number }): number {
  return this.v;
}

// (7) makeCounter returns a closure that captures the variable `n` BY
// REFERENCE. Each call of the returned closure increments and returns the
// SAME `n` (a live binding, not a snapshot). The captured `n` escapes to the
// heap and survives as long as the closure is reachable (see GARBAGE_COLLECTION).
function makeCounter(): () => number {
  let n = 0;
  return (): number => {
    n += 1;
    return n;
  };
}

// ============================================================================
// Section A — First-class: functions are objects (declaration/expression/arrow)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — First-class: functions are objects (decl / expr / arrow)");

  // typeof for the three forms — ALL are "function". A function is a callable
  // OBJECT: it has its own properties (.name, .length; classics also have a
  // .prototype — arrows do NOT).
  console.log("form                : typeof   : .name                  : .length");
  console.log("------------------- : -------- : ---------------------- : -------");
  console.log(
    `function decl       : ${typeof hoistedDecl}   : ${hoistedDecl.name.padEnd(22)} : ${hoistedDecl.length}`,
  );
  console.log(`function expression : ${typeof exprFn}   : ${exprFn.name.padEnd(22)} : ${exprFn.length}`);
  console.log(`arrow expression    : ${typeof arrowFn}   : ${arrowFn.name.padEnd(22)} : ${arrowFn.length}`);

  check('typeof function declaration === "function"', typeof hoistedDecl === "function");
  check('typeof function expression === "function"', typeof exprFn === "function");
  check('typeof arrow expression === "function"', typeof arrowFn === "function");

  // Hoisting: a function DECLARATION is callable before its textual position.
  console.log("");
  console.log(
    `hoistedDecl() called BEFORE its textual position -> "${hoistedBeforeText}"`,
  );
  check("function declaration is hoisted (callable before textual position)", hoistedBeforeText === "from declaration (hoisted)");

  // Higher-order function: pass a function VALUE as an argument.
  const sq = (n: number): number => n * n;
  const r = applyTwice(sq, 3); // sq(sq(3)) === sq(9) === 81
  console.log("");
  console.log(`applyTwice(n => n*n, 3) -> ${r}   (sq(sq(3)) === 81)`);
  check("HOF: applyTwice(sq, 3) === 81", r === 81);

  // Array.prototype.map is the canonical HOF: it takes a callback (function
  // value) and applies it to each element. This is first-class in action.
  const doubled = [1, 2, 3].map((x) => x * 2);
  console.log(`[1,2,3].map(x => x*2)    -> ${JSON.stringify(doubled)}`);
  check("[1,2,3].map(x => x*2) deep-equals [2,4,6]", JSON.stringify(doubled) === JSON.stringify([2, 4, 6]));

  // Functions are objects: they have OWN properties.
  check("function has .name (it is an object)", typeof hoistedDecl.name === "string");
  check("function has .length (declared param count)", typeof hoistedDecl.length === "number");

  // Arrow functions have NO .prototype (cannot be used as constructors).
  check('"prototype" in arrowFn === false (arrow is not a constructor)', "prototype" in arrowFn === false);
  check('"prototype" in exprFn === true (classic IS a constructor)', "prototype" in exprFn === true);
}

// ============================================================================
// Section B — this: classic (call-site) vs arrow (lexical)  [THE payoff]
// ============================================================================

function sectionB(): void {
  sectionBanner("B — this: classic (call-site) vs arrow (lexical)");

  // The module top-level `this` value. Under tsx's CJS-wrapper transform it
  // is an empty object {}; under native ESM it would be `undefined`. Either
  // way, the arrow defined at module scope captures THIS value, and ignores
  // any later .call thisArg — the principle this section pins.
  const moduleThisIsUndefined = moduleThis === undefined;
  const moduleThisIsEmptyObj =
    typeof moduleThis === "object" &&
    moduleThis !== null &&
    moduleThis !== globalThis &&
    Object.keys(moduleThis as object).length === 0;
  const moduleThisDesc = moduleThisIsUndefined
    ? "undefined (native ESM)"
    : moduleThisIsEmptyObj
      ? "[empty object] (tsx/esbuild CJS wrapper; native ESM would be undefined)"
      : String(moduleThis);
  console.log(`module top-level this -> ${moduleThisDesc}`);
  check(
    "module top-level this is the module scope's this (NOT globalThis)",
    moduleThis !== globalThis,
  );

  // Top-level arrow captures moduleThis; .call cannot rebind it.
  console.log("");
  console.log("Top-level arrow (lexical capture of moduleThis):");
  console.log(`  topArrow() === moduleThis ? ${topArrow() === moduleThis}   (arrow captures enclosing this)`);
  console.log(`  topArrow.call({x: 1}) === moduleThis ? ${topArrow.call({ x: 1 }) === moduleThis}   (thisArg IGNORED)`);
  check("top-level arrow captures moduleThis (lexical)", topArrow() === moduleThis);
  check("arrow ignores .call(thisArg)", topArrow.call({ x: 1 }) === moduleThis);

  // Classic bare call in strict mode: `this === undefined`. (Strict mode is
  // forced by the file's "use strict" prologue; without it, a bare classic
  // call would fall back to globalThis — the pre-ES5 default.)
  function classicBare(this: unknown): unknown {
    return this;
  }
  console.log("");
  console.log("Classic function — `this` is determined by the CALL SITE:");
  console.log(`  classicBare() -> ${String(classicBare())}   (strict mode: bare call -> this === undefined)`);
  console.log(`  classicBare.call({x: 7}) -> ${JSON.stringify(classicBare.call({ x: 7 }))}   (explicit this via .call)`);
  check("classic bare call in strict mode: this === undefined", classicBare() === undefined);
  check("classic .call(thisArg) sets this for one call", classicBare.call({ x: 7 }) as object !== undefined);

  // Object literal: classic method (this = receiver) vs arrow property
  // (this = lexical moduleThis, NOT the receiver).
  console.log("");
  console.log("Object literal — classic method vs arrow PROPERTY:");
  console.log(`  obj.classic()     -> ${obj.classic()}   (classic: this bound to obj at call site)`);
  console.log(`  obj.classicExpr() -> ${obj.classicExpr()}   (function-expression property: same rule)`);
  console.log(`  obj.arrow() === obj ? ${obj.arrow() === obj}   (arrow: this is LEXICAL, NOT obj)`);
  check("obj.classic() === 1 (classic this is the receiver)", obj.classic() === 1);
  check("obj.classicExpr() === 1 (function expression same rule)", obj.classicExpr() === 1);
  check("obj.arrow() !== obj (arrow this is lexical, not the receiver)", obj.arrow() !== obj);

  // Arrow DEFINED INSIDE a classic method captures the method's `this`
  // (the receiver). This is the "auto-bind" benefit MDN describes — the
  // arrow inside the method body sees the same `this` the method does.
  const receiver = {
    v: 42,
    method(): () => number {
      const inner = (): number => this.v; // arrow captures method's this (= receiver)
      return inner;
    },
  };
  const arrowFromMethod = receiver.method();
  console.log("");
  console.log("Arrow DEFINED INSIDE a classic method captures the method's this:");
  console.log(`  receiver.method() returns an arrow; calling it -> ${arrowFromMethod()}   (auto-bound to receiver)`);
  check("arrow inside method captures method's this (auto-bind)", arrowFromMethod() === 42);

  // THE headline trap: detaching a classic method from its receiver loses
  // `this`. In strict mode, a bare `m()` sets `this` to undefined, so
  // reading this.v throws TypeError.
  console.log("");
  console.log("Detached method loses `this` (strict mode -> TypeError):");
  const detached: () => number = obj.classic; // strip the this-type for the bare call
  let detachedThrew = false;
  let detachedErrName = "";
  try {
    detached();
  } catch (e) {
    detachedThrew = true;
    detachedErrName = (e as Error).name;
  }
  console.log(`  const m = obj.classic; m() -> threw ${detachedErrName}   (this === undefined in strict)`);
  check(
    "detached classic method throws TypeError (this === undefined in strict)",
    detachedThrew && detachedErrName === "TypeError",
  );

  // .bind on a classic function permanently fixes `this` (deep dive in E).
  const boundTo99 = readV.bind({ v: 99 });
  console.log("");
  console.log(`  readV.bind({v: 99})() -> ${boundTo99()}   (classic this permanently bound)`);
  check("bind permanently fixes classic this (preview — Section E)", boundTo99() === 99);
}

// ============================================================================
// Section C — Closures capture BY REFERENCE (live binding); counter factory
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Closures capture BY REFERENCE (live binding, not a snapshot)");

  // (1) Counter factory: persistent state across calls. The captured `n`
  // survives every call of the returned closure — it is shared BY REFERENCE.
  const c = makeCounter();
  const a = c();
  const b = c();
  const d = c();
  console.log(`const c = makeCounter();`);
  console.log(`c() -> ${a}   c() -> ${b}   c() -> ${d}   (captured n persists — BY REFERENCE)`);
  check("counter factory: c() -> 1, 2, 3 (closure state persists)", a === 1 && b === 2 && d === 3);

  // (2) Capture-by-reference means LATER mutation is visible: the closure
  // holds a live binding to `x`, not a snapshot of x's value at creation.
  let x = 1;
  const readX = (): number => x;
  console.log("");
  console.log(`let x = 1; const f = () => x;`);
  console.log(`f()       -> ${readX()}   (captures the BINDING, not the value)`);
  x = 2;
  console.log(`x = 2; f() -> ${readX()}   (LATER mutation is seen — live binding)`);
  check("capture-by-reference: f() reflects later mutation of captured var", readX() === 2);

  // (3) Two independent counters: each call to makeCounter creates a FRESH
  // `n`, so c1 and c2 close over two distinct cells.
  const c1 = makeCounter();
  const c2 = makeCounter();
  c1();
  c1();
  const v1 = c1();
  const v2 = c2();
  console.log("");
  console.log(`c1() x2; then c1() -> ${v1}; c2() -> ${v2}   (each factory call: fresh captured n)`);
  check("two counters are independent: c1 -> 3, c2 -> 1", v1 === 3 && v2 === 1);

  // (4) IIFE module pattern (pre-ESM): an immediately-invoked function
  // expression creates a private scope; the returned object's methods close
  // over the private state. The private variable is unreachable from outside.
  const mod = (function () {
    let privateCount = 0;
    function changeBy(delta: number): void {
      privateCount += delta;
    }
    return {
      increment: (): void => {
        changeBy(1);
      },
      decrement: (): void => {
        changeBy(-1);
      },
      value: (): number => privateCount,
    };
  })();
  mod.increment();
  mod.increment();
  mod.decrement();
  console.log("");
  console.log(`IIFE module: inc, inc, dec -> value() = ${mod.value()}   (private state via closure)`);
  check("IIFE module pattern: private state via closure (inc,inc,dec -> 1)", mod.value() === 1);
  check("IIFE module: privateCount is unreachable from outside", !("privateCount" in mod));
}

// ============================================================================
// Section D — Default params + rest params vs the `arguments` object
// ============================================================================

// Default params are evaluated AT CALL TIME (when omitted or explicitly
// undefined). They are NOT a constant snapshot baked in at definition.
function withDefault(a: number, b: number = 10): number {
  return a + b;
}

// Rest params (...nums) collect remaining args into a REAL Array (with .map,
// .reduce, etc). This is the modern replacement for the `arguments` object.
function sumRest(...nums: number[]): number {
  return nums.reduce((acc, n) => acc + n, 0);
}

// A classic (non-arrow) function has an `arguments` object: array-LIKE (has
// .length + integer indices, IS iterable) but NOT a real Array (no .map).
// We declare a rest param (...nums) so TS accepts variadic calls; inside, we
// compare `arguments` (array-LIKE) head-to-head with `nums` (a REAL Array).
function inspectArgs(
  ...nums: number[]
): {
  length: number;
  first: number;
  argumentsIsArray: boolean;
  restIsArray: boolean;
  spreadWorks: boolean;
} {
  // arguments is only in scope inside a non-arrow function. It is iterable
  // (has Symbol.iterator), so [...arguments] produces a real Array.
  const arr = [...arguments];
  return {
    length: arguments.length,
    first: arguments[0] as number,
    argumentsIsArray: Array.isArray(arguments),
    restIsArray: Array.isArray(nums), // rest is a REAL Array — the contrast
    spreadWorks: arr.length === arguments.length,
  };
}

// Arrow functions have NO `arguments` of their own. An arrow defined inside a
// classic function inherits the classic function's `arguments` (it is a
// lexical lookup, exactly like `this`).
function outer(n: number): number {
  const inner = (): number => (arguments[0] as number) + n; // arrow borrows outer's arguments
  return inner();
}

function sectionD(): void {
  sectionBanner("D — Default params + rest params vs the `arguments` object");

  // Default params: triggered by omission OR an explicit undefined.
  console.log("Default params (b = 10):");
  console.log(`  withDefault(1)             -> ${withDefault(1)}   (b defaulted to 10)`);
  console.log(`  withDefault(1, 20)         -> ${withDefault(1, 20)}   (b provided)`);
  console.log(`  withDefault(1, undefined)  -> ${withDefault(1, undefined)}   (explicit undefined -> default)`);
  check("default param: withDefault(1) === 11 (b defaulted)", withDefault(1) === 11);
  check("default param: withDefault(1, 20) === 21 (b provided)", withDefault(1, 20) === 21);
  check("default param: explicit undefined triggers default", withDefault(1, undefined) === 11);

  // Rest params: collect into a REAL array.
  console.log("");
  console.log("Rest params (...nums: number[]):");
  console.log(`  sumRest(1, 2, 3)  -> ${sumRest(1, 2, 3)}   (nums is a real array)`);
  console.log(`  sumRest()         -> ${sumRest()}   (zero args -> empty array)`);
  check("rest params: sumRest(1,2,3) === 6", sumRest(1, 2, 3) === 6);
  check("rest params: sumRest() === 0 (empty array)", sumRest() === 0);

  // The `arguments` object (classic functions only): array-LIKE, not Array.
  // Contrast with the rest param `nums`, which IS a real Array.
  console.log("");
  console.log("arguments object (classic functions only — array-LIKE, not Array):");
  const argsInfo = inspectArgs(7, 8, 9);
  console.log(
    `  inspectArgs(7,8,9): length=${argsInfo.length}, first=${argsInfo.first},`,
  );
  console.log(
    `    Array.isArray(arguments)=${argsInfo.argumentsIsArray}, Array.isArray(rest)=${argsInfo.restIsArray}, [...arguments] works=${argsInfo.spreadWorks}`,
  );
  check("arguments.length === 3 (call had 3 args)", argsInfo.length === 3);
  check("arguments[0] === 7", argsInfo.first === 7);
  check("Array.isArray(arguments) === false (array-LIKE, not Array)", argsInfo.argumentsIsArray === false);
  check("Array.isArray(rest) === true (rest param IS a real Array)", argsInfo.restIsArray === true);
  check("[...arguments] works (arguments IS iterable)", argsInfo.spreadWorks === true);

  // Arrow has NO own arguments — it inherits the enclosing function's.
  console.log("");
  console.log("Arrow has NO own arguments — inherits the enclosing function's:");
  console.log(`  function outer(n) { const inner = () => arguments[0] + n; return inner(); }`);
  console.log(`  outer(7) -> ${outer(7)}   (inner sees outer's arguments[0] === 7)`);
  check("arrow inherits enclosing function's arguments: outer(7) === 14", outer(7) === 14);
}

// ============================================================================
// Section E — call / apply / bind + TS function types
// ============================================================================

// Classic function with an explicit TS `this` parameter. The this-param is
// TYPE-ONLY (erased at runtime); at runtime `this` is whatever the call site
// provides. call/apply/bind let us set it explicitly.
function describe(this: { label: string }, suffix: string): string {
  return this.label + suffix;
}

// A TS function TYPE: the signature of a callback. The `this: void` here is a
// TS idiom meaning "this function must NOT be called as a method" — it
// prevents this-binding bugs at COMPILE time (calling obj.cb() would error).
type Callback = (this: void, x: number) => string;

function sectionE(): void {
  sectionBanner("E — call / apply / bind + TS function types");

  // .call(thisArg, ...args): invoke ONCE with an explicit this + spread args.
  const viaCall = describe.call({ label: "A" }, "!");
  // .apply(thisArg, [args]): same as call but args passed as an array.
  const viaApply = describe.apply({ label: "B" }, ["?"]);
  console.log(`describe.call({label:"A"}, "!")   -> ${viaCall}`);
  console.log(`describe.apply({label:"B"}, ["?"]) -> ${viaApply}`);
  check(".call sets this for one call", viaCall === "A!");
  check(".apply sets this for one call (args as array)", viaApply === "B?");

  // .bind(thisArg): returns a NEW function with `this` PERMANENTLY bound.
  // Subsequent .call on the bound function CANNOT rebind this.
  const bound = describe.bind({ label: "C" });
  const boundThenCall = bound.call({ label: "X" }, "#");
  console.log("");
  console.log(`const bound = describe.bind({label:"C"});`);
  console.log(`bound(".")              -> ${bound(".")}   (this permanently C)`);
  console.log(`bound.call({label:"X"}) -> ${boundThenCall}   (.call CANNOT rebind a bound fn)`);
  check(".bind returns a new fn with permanently-bound this", bound(".") === "C.");
  check("a bound function ignores a later .call thisArg", boundThenCall === "C#");

  // TS function types: a callback signature. `this: void` flags "do not call
  // as a method" — compile-time safety.
  const numToString: Callback = (x) => String(x);
  console.log("");
  console.log(`type Callback = (this: void, x: number) => string;`);
  console.log(`const fn: Callback = (x) => String(x);  fn(42) -> ${JSON.stringify(numToString(42))}`);
  check("TS function type as callback signature: fn(42) === '42'", numToString(42) === "42");

  // Arrow functions IGNORE call/apply/bind thisArg (their this is lexical).
  console.log("");
  console.log("Arrow functions IGNORE .bind(thisArg) — this remains lexical:");
  const arrowBound = topArrow.bind({ x: 99 });
  console.log(
    `  topArrow.bind({x: 99})() === moduleThis ? ${arrowBound() === moduleThis}   (arrow this still moduleThis)`,
  );
  check("arrow ignores .bind(thisArg) — this remains lexical", arrowBound() === moduleThis);

  // new on an arrow function THROWS — arrows have no [[Construct]] internal
  // slot and no .prototype property (Section A asserted the latter).
  console.log("");
  console.log("Arrow functions CANNOT be constructors (no [[Construct]] slot):");
  type Ctor = new () => unknown;
  let newArrowThrew = false;
  let newArrowErr = "";
  try {
    new (topArrow as unknown as Ctor)();
  } catch (e) {
    newArrowThrew = true;
    newArrowErr = (e as Error).name;
  }
  console.log(`  new (topArrow)() -> threw ${newArrowErr}`);
  check("new on an arrow throws TypeError", newArrowThrew && newArrowErr === "TypeError");
}

// ============================================================================
// Section F — Loop-var-capture trap (PREVIEW — deep dive in SCOPE_HOISTING)
// ============================================================================

function sectionF(): void {
  sectionBanner("F — Loop-var capture trap (PREVIEW — deep dive in SCOPE_HOISTING)");

  // `var` is FUNCTION-scoped: the for-loop shares ONE `i` across all
  // iterations. Every closure created in the loop captures the SAME binding,
  // so by the time they run, i === 3 (the value after the loop ended).
  const varFns: Array<() => number> = [];
  for (var i = 0; i < 3; i++) {
    varFns.push((): number => i);
  }
  const varResults = varFns.map((f) => f());
  console.log(`for (var i = 0; i < 3; i++) fns.push(() => i);`);
  console.log(`varResults -> ${JSON.stringify(varResults)}   (all see the SAME final i === 3)`);
  check(
    "var loop: every closure sees the final i (=== 3)",
    JSON.stringify(varResults) === JSON.stringify([3, 3, 3]),
  );

  // `let` is BLOCK-scoped: the for-let-loop creates a FRESH binding of `j`
  // PER ITERATION (specified by ECMA-262 §14.1.2). Each closure captures its
  // own 0, 1, 2. (Same fix Go 1.22+ applied to its loop variable.)
  const letFns: Array<() => number> = [];
  for (let j = 0; j < 3; j++) {
    letFns.push((): number => j);
  }
  const letResults = letFns.map((f) => f());
  console.log(`for (let j = 0; j < 3; j++) fns.push(() => j);`);
  console.log(`letResults -> ${JSON.stringify(letResults)}   (FRESH j per iteration — closure-friendly)`);
  check(
    "let loop: each closure captures its own per-iteration j",
    JSON.stringify(letResults) === JSON.stringify([0, 1, 2]),
  );
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("functions_closures.ts — Phase 1 bundle.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TypeScript types are ERASED at runtime (tsx/tsc strip them).");
  console.log('A function is a callable OBJECT — typeof "function" — first-class.');
  console.log("`this` is a runtime binding: classic = call-site; arrow = lexical.");
  console.log("Closures capture variables BY REFERENCE (a live binding).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionF();
  sectionBanner("DONE — all sections printed");
}

main();
