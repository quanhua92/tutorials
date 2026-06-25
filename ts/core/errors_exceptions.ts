// errors_exceptions.ts — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, how JS's throw/try/catch/
// finally (the Python model, NOT Go's return-error), the Error object +
// subclasses + Error.cause chain, and TypeScript's `never` type actually
// behave — pinning "finally ALWAYS runs", "throw anything (but always throw
// an Error)", and "never = the type of never-returns" as check()'d invariants.
//
// This is the GROUND TRUTH for ERRORS_EXCEPTIONS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle sits where it does): JS has NO checked exceptions
// and NO Result type (unlike Rust). Anything can be thrown (not just Errors);
// errors propagate UP the call stack until a try/catch catches them; `finally`
// ALWAYS runs (even on return/throw); and the Error.cause chain (ES2022) gives
// proper error wrapping. TypeScript layers ONE compile-time concept on top:
// the `never` type, which marks functions that never return (always throw).
// Async errors (rejected promises) are a SEPARATE path — previewed here, owned
// by PROMISES (Phase 4).
//
// Run:
//     pnpm exec tsx errors_exceptions.ts   (or: just run errors_exceptions)

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

// --- shared types/helpers ---------------------------------------------------

// fail is the canonical never-returning function: it ALWAYS throws, so its
// return type is `never` (the bottom type). Used in Section E and as the
// exhaustive-check fallback in switches. TS's control-flow analysis knows
// that code after a `never`-returning call is unreachable.
function fail(msg: string): never {
  throw new Error(msg);
}

// A custom Error subclass (Section B). Subclasses MUST set this.name in the
// constructor — otherwise extending Error leaves .name === "Error" (the
// superclass's prototype default), which breaks logging/error-name switches.
class MyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MyError"; // <-- the gotcha-fix (without this, .name === "Error")
  }
}

// ============================================================================
// Section A — throw ANYTHING + try/catch/finally + finally ALWAYS runs
// ============================================================================

function sectionA(): void {
  sectionBanner("A — throw ANYTHING + try/catch/finally + finally ALWAYS runs");

  // JS lets you throw ANY value — not just Error. `throw "x"` makes the caught
  // binding the STRING "x". This is legal but an ANTI-PATTERN: code that
  // catches expects .name/.message/.stack (which a string lacks). Always
  // throw an Error. (Section D shows the safe normalization pattern.)
  console.log("throw <anything> (legal, but only Error is correct):");

  let caughtStr: unknown;
  try {
    throw "string-thrown";
  } catch (e) {
    caughtStr = e;
  }
  console.log(`  throw "string-thrown" -> caught === "string-thrown"? ${caughtStr === "string-thrown"}`);
  console.log(`  typeof caught value  -> ${typeof caughtStr}   (NOT an Error)`);
  check('throw "x" -> caught value === "x" (a string, anti-pattern)', caughtStr === "string-thrown");
  check("caught string is NOT an instanceof Error", !(caughtStr instanceof Error));

  let caughtNum: unknown;
  try {
    throw 42;
  } catch (e) {
    caughtNum = e;
  }
  console.log(`  throw 42             -> caught === 42?        ${caughtNum === 42}`);
  check("throw 42 -> caught value === 42 (a number)", caughtNum === 42);

  let caughtObj: unknown;
  try {
    throw { code: 7, detail: "oops" };
  } catch (e) {
    caughtObj = e;
  }
  console.log(`  throw {code:7}       -> caught.code === 7?    ${(caughtObj as { code: number }).code === 7}`);
  check("throw {code:7} -> caught object retains .code === 7", (caughtObj as { code: number }).code === 7);

  // Normal try/catch/finally flow (no throw).
  console.log("");
  console.log("try/catch/finally normal flow (no throw):");
  const flow: string[] = [];
  try {
    flow.push("try");
  } catch {
    flow.push("catch"); // skipped — no throw
  } finally {
    flow.push("finally"); // ALWAYS runs
  }
  console.log(`  sequence: ${flow.join(" -> ")}`);
  check("normal flow: try -> finally (catch skipped)", flow.join(",") === "try,finally");

  // finally ALWAYS runs — even when try RETURNS.
  console.log("");
  console.log("finally runs even when try RETURNS:");
  let finallyRanOnReturn = false;
  function tryReturnFinally(): number {
    try {
      return 1;
    } finally {
      finallyRanOnReturn = true; // runs BEFORE the return completes
    }
  }
  const ret = tryReturnFinally();
  console.log(`  try { return 1 } finally { sideEffect() } -> returned ${ret}, sideEffect ran? ${finallyRanOnReturn}`);
  check("finally runs on try-return (before the value escapes)", finallyRanOnReturn && ret === 1);

  // finally ALWAYS runs — even when try THROWS.
  console.log("");
  console.log("finally runs even when try THROWS:");
  let finallyRanOnThrow = false;
  try {
    try {
      throw new Error("inner");
    } finally {
      finallyRanOnThrow = true; // runs before the throw propagates
    }
  } catch {
    // swallow the outer-propagated throw so the section can continue
  }
  console.log(`  try { throw } finally { sideEffect() } -> sideEffect ran? ${finallyRanOnThrow}`);
  check("finally runs on try-throw (before the throw propagates)", finallyRanOnThrow);

  // THE GOTCHA: a return/throw INSIDE finally OVERRIDES the try's return/throw.
  // This is almost never intended — finally should be cleanup-only.
  console.log("");
  console.log("GOTCHA: finally's return OVERRIDES try's return:");
  function finallyOverridesReturn(): string {
    try {
      return "from-try";
    } finally {
      return "from-finally"; // <-- swallows try's return value!
    }
  }
  const overridden = finallyOverridesReturn();
  console.log(`  try { return "from-try" } finally { return "from-finally" } -> "${overridden}"`);
  check('finally return overrides try return (returns "from-finally")', overridden === "from-finally");
}

// ============================================================================
// Section B — Error object + custom subclasses (the .name gotcha, instanceof)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Error object + custom subclasses (the .name gotcha, instanceof)");

  // The Error object: .name, .message, .stack.
  const e = new Error("boom");
  console.log("new Error('boom'):");
  console.log(`  .name    = ${JSON.stringify(e.name)}`);
  console.log(`  .message = ${JSON.stringify(e.message)}`);
  console.log(`  typeof .stack = ${typeof e.stack}`);
  console.log(`  .stack first line = ${JSON.stringify((e.stack ?? "").split("\n")[0])}`);
  check('new Error("boom").message === "boom"', e.message === "boom");
  check('new Error("boom").name === "Error"', e.name === "Error");
  check('Error.prototype.name === "Error"', Error.prototype.name === "Error");
  check('typeof e.stack === "string"', typeof e.stack === "string");
  check('e.stack includes "Error:" (V8 first line: "Error: <msg>")', (e.stack ?? "").includes("Error:"));
  check('e.stack includes "at " (V8 stack-frame prefix)', (e.stack ?? "").includes("at "));

  // Built-in Error subclasses: each has its OWN .name on its prototype.
  console.log("");
  console.log("Built-in Error subclasses (each sets its own .name):");
  const builtins: ReadonlyArray<readonly [string, Error]> = [
    ["TypeError", new TypeError("t")],
    ["RangeError", new RangeError("r")],
    ["SyntaxError", new SyntaxError("s")],
    ["ReferenceError", new ReferenceError("ref")],
    ["URIError", new URIError("u")],
  ];
  for (const [label, err] of builtins) {
    console.log(`  ${label.padEnd(16)} .name=${JSON.stringify(err.name)}  instanceof Error? ${err instanceof Error}`);
    check(`${label}.name === "${label}"`, err.name === label);
    check(`${label} instanceof Error`, err instanceof Error);
  }

  // Custom Error subclass + instanceof.
  console.log("");
  console.log("Custom subclass MyError extends Error:");
  const myErr = new MyError("custom");
  console.log(`  new MyError("custom").name    = ${JSON.stringify(myErr.name)}`);
  console.log(`  new MyError("custom").message = ${JSON.stringify(myErr.message)}`);
  console.log(`  myErr instanceof MyError = ${myErr instanceof MyError}`);
  console.log(`  myErr instanceof Error   = ${myErr instanceof Error}`);
  check('MyError sets .name === "MyError" (the fix)', myErr.name === "MyError");
  check("myErr instanceof MyError", myErr instanceof MyError);
  check("myErr instanceof Error (subclass passes through)", myErr instanceof Error);

  // THE .name GOTCHA: if MyError did NOT set this.name, it would inherit
  // Error.prototype.name === "Error" — losing the subclass identity in logs.
  console.log("");
  console.log("THE .name GOTCHA: subclass WITHOUT this.name = ... :");
  class NamelessError extends Error {} // no this.name assignment
  const nameless = new NamelessError("x");
  console.log(`  new NamelessError("x").name = ${JSON.stringify(nameless.name)}  (inherited "Error" — wrong!)`);
  check('NamelessError without this.name inherits "Error" (the gotcha)', nameless.name === "Error");
  check("but nameless instanceof NamelessError still works", nameless instanceof NamelessError);

  // Conditional catch via instanceof (the "EAFP" — easier to ask forgiveness —
  // pattern): one catch, then instanceof dispatch, then re-throw unknowns.
  console.log("");
  console.log("Conditional handling via instanceof (EAFP style):");
  function risky(n: number): number {
    if (n < 0) throw new RangeError("negative");
    if (n === 0) throw new TypeError("zero");
    return n;
  }
  const handled: string[] = [];
  for (const n of [-1, 0, 5]) {
    try {
      handled.push(`risky(${n})=${risky(n)}`);
    } catch (err) {
      if (err instanceof RangeError) handled.push(`risky(${n})=RangeError:${err.message}`);
      else if (err instanceof TypeError) handled.push(`risky(${n})=TypeError:${err.message}`);
      else throw err; // re-throw unknown errors unchanged
    }
  }
  for (const line of handled) console.log(`  ${line}`);
  check(
    "instanceof dispatches RangeError vs TypeError correctly",
    handled.join("|") === "risky(-1)=RangeError:negative|risky(0)=TypeError:zero|risky(5)=5",
  );
}

// ============================================================================
// Section C — Error.cause chaining (ES2022) + rethrow identity preservation
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Error.cause chaining (ES2022) + rethrow identity preservation");

  // Error.cause (ES2022): new Error("wrap", { cause: orig }) preserves the
  // original error on .cause, so you can ADD context without LOSING the root.
  const root = new Error("disk full");
  const wrapped = new Error("save failed", { cause: root });
  console.log("Error.cause (ES2022):");
  console.log(`  root    = Error("${root.message}")`);
  console.log(`  wrapped = Error("${wrapped.message}", { cause: root })`);
  console.log(`  wrapped.cause === root?  ${wrapped.cause === root}`);
  console.log(`  wrapped.cause.message   = ${JSON.stringify((wrapped.cause as Error).message)}`);
  check("wrapped.cause === root (identity preserved)", wrapped.cause === root);
  check("wrapped.cause.message === root.message", (wrapped.cause as Error).message === root.message);

  // A 3-layer cause chain — walk it by following .cause until non-Error.
  console.log("");
  console.log("Walking a 3-layer cause chain (each .cause is the prior error):");
  const layer0 = new Error("ENOENT: file missing");
  const layer1 = new Error("readConfig failed", { cause: layer0 });
  const layer2 = new Error("boot failed", { cause: layer1 });
  const chain: string[] = [];
  let cursor: unknown = layer2;
  let guard = 0;
  while (cursor instanceof Error && guard < 10) {
    chain.push(`${cursor.name}: ${cursor.message}`);
    cursor = cursor.cause;
    guard++;
  }
  for (const line of chain) console.log(`  ${line}`);
  check("cause chain walks 3 layers deep", chain.length === 3);
  check("cause chain root is the ENOENT error", chain[2] === "Error: ENOENT: file missing");

  // cause can carry ANY value (not just Error) — useful for structured data.
  console.log("");
  console.log("cause can carry structured data (not just an Error):");
  const structured = new Error("validation failed", {
    cause: { code: "E_INVALID", fields: ["email", "age"] },
  });
  const causeFields = (structured.cause as { fields?: string[] }).fields;
  console.log(`  err.cause = ${JSON.stringify(structured.cause)}`);
  check("cause can be a plain object (structured data)", Array.isArray(causeFields) && causeFields.length === 2);

  // RE-THROW: `throw e` (or bare `throw`) in catch preserves the ORIGINAL
  // error's identity AND stack — it does NOT reset the throw site.
  console.log("");
  console.log("Re-throw preserves identity (throw e keeps the original):");
  const original = new Error("original");
  let seenAtInner: unknown;
  let seenAtOuter: unknown;
  function innerThrow(): void {
    try {
      throw original; // throws a specific instance
    } catch (e) {
      seenAtInner = e;
      throw e; // re-throw — identity preserved
    }
  }
  try {
    innerThrow();
  } catch (e) {
    seenAtOuter = e;
  }
  console.log(`  inner caught === original? ${seenAtInner === original}`);
  console.log(`  outer caught === original? ${seenAtOuter === original}`);
  console.log(`  inner caught === outer caught? ${seenAtInner === seenAtOuter}`);
  check("re-thrown error is the SAME identity at inner catch", seenAtInner === original);
  check("re-thrown error is the SAME identity at outer catch", seenAtOuter === original);
  check("inner and outer caught the IDENTICAL object", seenAtInner === seenAtOuter);

  // Contrast: wrapping (throw new Error(..., {cause})) makes a NEW object.
  // Identity changes, but the original is reachable via .cause.
  console.log("");
  console.log("Wrapping makes a NEW object (identity changes; cause preserves root):");
  let wrappedSeen: unknown;
  function innerWrap(): void {
    try {
      throw original;
    } catch (e) {
      throw new Error("wrapped", { cause: e }); // NEW error, original on .cause
    }
  }
  try {
    innerWrap();
  } catch (e) {
    wrappedSeen = e;
  }
  console.log(`  wrapped error === original?      ${(wrappedSeen as Error) === original}`);
  console.log(`  wrapped error.cause === original? ${(wrappedSeen as Error).cause === original}`);
  check("wrapping produces a NEW error (identity differs)", wrappedSeen !== original);
  check("but wrapped.cause === original (root reachable)", (wrappedSeen as Error).cause === original);
}

// ============================================================================
// Section D — catch-without-binding + non-Error normalization + propagation
// ============================================================================

function sectionD(): void {
  sectionBanner("D — catch-without-binding + non-Error normalization + propagation");

  // catch WITHOUT a binding (ES2019): `try { ... } catch { ... }` — omit the
  // variable entirely when you don't inspect the thrown value. Useful for
  // "did it succeed?" checks, and it silences noUnusedLocals on a caught var
  // you'd otherwise ignore.
  console.log("catch without a binding (ES2019):");
  function isValidJSON(text: string): boolean {
    try {
      JSON.parse(text);
      return true;
    } catch {
      return false; // binding omitted — we only care that it threw
    }
  }
  console.log(`  isValidJSON('{"a":1}')  = ${isValidJSON('{"a":1}')}`);
  console.log(`  isValidJSON("not json") = ${isValidJSON("not json")}`);
  check("isValidJSON accepts valid JSON", isValidJSON('{"a":1}') === true);
  check("isValidJSON rejects invalid JSON", isValidJSON("not json") === false);

  // Safe normalization: if you MIGHT receive a non-Error thrown value (from
  // old code, JSON.parse of error envelopes, etc.), normalize it BEFORE use.
  console.log("");
  console.log("Safe normalization (turn any thrown value into an Error):");
  function normalize(thrown: unknown): Error {
    if (thrown instanceof Error) return thrown;
    return new Error(String(thrown), { cause: thrown }); // wrap + preserve
  }
  const cases: ReadonlyArray<readonly [string, unknown]> = [
    ['throw "oops"', "oops"],
    ["throw 42", 42],
    ["throw {code:1}", { code: 1 }],
    ["throw new TypeError('t')", new TypeError("t")],
  ];
  for (const [label, value] of cases) {
    const err = normalize(value);
    const keptCause = value instanceof Error ? err === value : err.cause === value;
    console.log(`  ${label.padEnd(28)} -> ${err.name}: ${JSON.stringify(err.message)}  (cause kept? ${keptCause})`);
    check(`${label} normalizes to an Error`, err instanceof Error);
  }

  // PROPAGATION up the call stack: a throw bubbles up frame by frame until a
  // try/catch catches it. If NONE catches, the Node process exits (preview —
  // see the .md's "uncaught crash" note). Here C throws, B doesn't catch, A
  // catches — proving the up-stack walk.
  console.log("");
  console.log("Propagation: C throws -> B (no catch) -> A catches:");
  function c(): never {
    throw new Error("from-C");
  }
  function b(): void {
    c(); // no try/catch — lets it propagate
  }
  function a(): Error {
    try {
      b();
    } catch (e) {
      return e as Error; // caught here, after skipping B's frame
    }
    return fail("unreachable"); // never reached; fail() returns never
  }
  const propagated = a();
  const stackLines = (propagated.stack ?? "").split("\n");
  console.log(`  a() caught: ${propagated.name}: ${JSON.stringify(propagated.message)}`);
  console.log(`  stack frame count = ${stackLines.length}  (throw site + call chain)`);
  console.log(`  stack mentions function a? ${stackLines.some((l) => l.includes(" a ") || l.includes(".a ") || l.includes("a ("))}`);
  check("propagated error message is 'from-C' (thrown in c, caught in a)", propagated.message === "from-C");
  check("stack recorded the call chain (>1 frame)", stackLines.length > 1);
}

// ============================================================================
// Section E — TypeScript `never`: the type of "never returns"
// ============================================================================

// Compile-time proof that `never` is assignable to every type. This function
// is never called at runtime; it exists so `just typecheck` verifies the
// assignability. The `fail(...)` calls never return, so the assignments are
// type-checked but never executed. If fail()'s return type were `string`
// instead of `never`, the assignments below would be type errors.
function neverIsBottomType(): void {
  const s: string = fail("s"); // never -> string: OK
  const n: number = fail("n"); // never -> number: OK
  const b: boolean = fail("b"); // never -> boolean: OK
  const o: object = fail("o"); // never -> object: OK
  void s;
  void n;
  void b;
  void o;
}
void neverIsBottomType; // reference so noUnusedLocals doesn't flag it

function sectionE(): void {
  sectionBanner("E — TypeScript `never`: the type of 'never returns'");

  // fail()'s return type is `never`. At RUNTIME, calling it throws (identical
  // to any throw). At the TYPE level, `never` means "this function does not
  // return a value — not even undefined."
  console.log("fail(msg): never  —  always throws, returns nothing:");
  let failThrew: unknown;
  try {
    fail("boom from fail()");
  } catch (e) {
    failThrew = e;
  }
  console.log(`  fail("boom from fail()") -> threw: ${(failThrew as Error).name}: ${JSON.stringify((failThrew as Error).message)}`);
  check("fail() throws at runtime (its TYPE is never; runtime behavior = throw)", failThrew instanceof Error);

  // never is the BOTTOM type: assignable to EVERY type. The proof lives in
  // neverIsBottomType() above — tsc verifies it compiles; tsx never runs it.
  console.log("");
  console.log("never is assignable to EVERY type (verified by `just typecheck`):");
  console.log('  (see neverIsBottomType(): `const x: string = fail("...")` typechecks,');
  console.log("   because never is assignable to every type. Not executed at runtime.)");
  check("never is assignable to string/number/boolean/object (tsc-verifiable above)", true);

  // Exhaustive narrowing via never: after a never-returning call, code is
  // unreachable. The classic use is the exhaustive-switch fallback — if a
  // new Shape kind is added later, removing a case makes the default's
  // fail() return-reachable only because never is assignable to number.
  console.log("");
  console.log("Exhaustive narrowing: fail() as the exhaustive-switch fallback:");
  type Shape = { kind: "circle"; r: number } | { kind: "square"; s: number };
  function area(s: Shape): number {
    switch (s.kind) {
      case "circle":
        return Math.PI * s.r * s.r;
      case "square":
        return s.s * s.s;
      default:
        // s is narrowed to `never` here (both union members handled).
        // fail() returns never -> assignable to number -> typechecks.
        return fail("unreachable shape");
    }
  }
  const ca = area({ kind: "circle", r: 2 });
  const sa = area({ kind: "square", s: 3 });
  console.log(`  area({kind:"circle", r:2}) = ${ca.toFixed(6)}  (PI * 4)`);
  console.log(`  area({kind:"square", s:3}) = ${sa}`);
  check("area(circle r=2) = PI * 4 (exhaustive narrowing works)", ca === Math.PI * 4);
  check("area(square s=3) = 9", sa === 9);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("errors_exceptions.ts — Phase 1 bundle.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: JS is throw-based (like Python), NOT return-error (like Go).");
  console.log("Anything can be thrown (always throw an Error); errors propagate up the");
  console.log("call stack until caught; finally ALWAYS runs (even on return/throw).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
