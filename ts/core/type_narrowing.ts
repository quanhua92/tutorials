// type_narrowing.ts — Phase 2 bundle (type-system).
//
// GOAL (one line): show, by check()'d runtime operator behavior AND tsc-verified
// expectType<>/@ts-expect-error compile-time proofs, how a RUNTIME check
// (typeof / in / instanceof / a literal-tag === / truthiness / assignment /
// return / throw) tells the COMPILER the value's type in the following branch —
// "narrowing", the bridge between TS's erased types and JS's runtime.
//
// This is the GROUND TRUTH for TYPE_NARROWING.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// LINEAGE (why this bundle sits where it does): TypeScript types are ERASED at
// runtime — tsx/esbuild/tsc strip every interface/type/annotation, emitting no
// runtime type information. So the static type system can only refine a value's
// type at a point if it PIGGYBACKS on a construct that actually executes:
// `typeof`, `instanceof`, the `in` operator, a `===` against a literal "tag", a
// truthiness test, an assignment, a `return`, or a `throw`. The process of
// refining a declared type to a more specific one along the control flow is
// "narrowing". It is how TS achieves type safety WITHOUT any runtime type info —
// and it is the JS analog of Rust's exhaustive `match` and Python's structural
// `match`/`case` (🔗 ../rust/PATTERN_MATCHING.md, ../python).
//
// TWO AXES OF EVIDENCE in this bundle (per the type-system special guidance):
//   - check()      -> RUNTIME operator behavior (typeof null === "object", the
//                     prototype chain instanceof walks, the `in` key search...).
//   - expectType<> -> COMPILE-TIME narrowed type (tsc FAILS if the Equal<...>
//                     claim is wrong), printed at runtime as a live [check].
//   - @ts-expect-error -> COMPILE-TIME "this would error WITHOUT narrowing",
//                     each directive suppressing a REAL error.
//
// Run:
//     pnpm exec tsx type_narrowing.ts   (or: just run type_narrowing)

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts a RUNTIME invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// --- compile-time narrowing toolkit -----------------------------------------
//
// Equal<A,B> is the standard type-equality trick: it resolves to the literal
// `true` only when A and B are the same type, else `false`. Used with expectType
// to pin the EXACT narrowed type of a variable at a point in the control flow.
//
// NOTE: inside a narrowing branch, the type query `typeof x` yields the
// NARROWED type of x (e.g. `number` inside `if (typeof x === "number")`), not
// its declared type — that is exactly what makes expectType<Equal<typeof x, T>>
// a faithful witness of narrowing. (Verified empirically against tsc 5.6.)
type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;

// expectType is BOTH a compile-time gate AND a runtime [check]. Its type param T
// must extend the literal `true`; if an Equal<...> claim resolves to `false`,
// tsc FAILS (false is not assignable to `true`) — so every narrowing claim in
// this file is enforced by the compiler, not by hand. At runtime it prints the
// [check] line. (T is "read" via the conditional in the parameter type, keeping
// it legal under noUnusedParameters.)
const expectType = <T extends true>(msg: T extends true ? string : never): void => {
  console.log(`[check] ${msg}: OK`);
};

// --- shared domain types (used across several sections) ---------------------

// A discriminated union: the `kind` literal is the discriminant (Section E).
type Circle = { kind: "circle"; radius: number };
type Square = { kind: "square"; side: number };
type Shape = Circle | Square;

// A shape union for the `in` operator (Section B): members distinguished by a
// METHOD name rather than a tag.
type Fish = { swim: () => void };
type Bird = { fly: () => void };

// A custom Error subclass (Section C) — pairs with ERRORS_EXCEPTIONS catch-unknown.
class ValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ValidationError"; // the subclass-identity fix (see ERRORS_EXCEPTIONS §B)
  }
}

// --- user-defined type guards (Section D — THE payoff) ----------------------

// A type predicate: `paramName is Type`. The body is an ordinary boolean check;
// the RETURN TYPE annotation is what makes TS narrow the caller's argument.
function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

function isFish(pet: Fish | Bird): pet is Fish {
  return "swim" in pet;
}

// --- assertion functions (Section D — narrow OR throw) ----------------------

// `asserts value is T`: if the function returns normally, the caller's value is
// narrowed to T; otherwise it THROWS. The non-null/non-undefined variant is so
// common it has a utility type: NonNullable<T>.
function assertDefined<T>(value: T): asserts value is NonNullable<T> {
  if (value === null || value === undefined) {
    throw new Error(`assertDefined: expected non-null/undefined, got ${String(value)}`);
  }
}

function assertString(value: unknown): asserts value is string {
  if (typeof value !== "string") {
    throw new Error(`assertString: expected string, got ${typeof value}`);
  }
}

// `asserts value` (no `is`): asserts value is TRUTHY. After the call, TS removes
// the falsy arms from value's type (mirrors truthiness narrowing, but eager).
function assertTruthy(value: unknown): asserts value {
  if (!value) {
    throw new Error(`assertTruthy: expected truthy, got ${String(value)}`);
  }
}

// ============================================================================
// Section A — typeof narrowing + blind spots (null/array) + Array.isArray
// ============================================================================

// proof_noGuardErrors: tsc-verifies that WITHOUT a guard, a union-only method
// access is a type error. NOTE: the parameter must be a PARAMETER (not a local
// `const x: string|number = "hi"`) — an assignment narrows the local to string
// on the spot (see Section E), which would hide the error. A parameter keeps
// the full union at entry. (Void'd — pure compile-time demonstration.)
function proof_noGuardErrors(x: string | number): void {
  // @ts-expect-error: Property 'toUpperCase' does not exist on type 'string | number'.
  const upper: string = x.toUpperCase();
  void upper;
}
void proof_noGuardErrors;

// proof_typeofObjectKeepsNull: tsc-verifies the typeof-null LIE in narrowing.
// `typeof x === "object"` does NOT remove `null` from a `T[] | null` union,
// because typeof null === "object". Iterating `strs` in the object branch STILL
// errors ("possibly null") — the canonical TypeScript-handbook proof. (Void'd:
// pure compile-time demonstration.)
function proof_typeofObjectKeepsNull(): void {
  const strs: string[] | null = null;
  if (typeof strs === "object") {
    // @ts-expect-error: 'strs' is possibly 'null' — typeof === "object" cannot
    // rule null out, so iterating it is still a type error. (Null kept in.)
    for (const s of strs) {
      void s;
    }
  }
}
void proof_typeofObjectKeepsNull;

// proof_cantWidenBeyondDeclared: tsc-verifies that an assignment narrows to the
// assigned value, but you can NEVER assign a type outside the DECLARED type.
function proof_cantWidenBeyondDeclared(): void {
  let x: string | number = 1;
  // @ts-expect-error: Type 'boolean' is not assignable to type 'string | number'.
  x = true;
  void x;
}
void proof_cantWidenBeyondDeclared;

function sectionA(): void {
  sectionBanner("A — typeof narrowing + blind spots (null/array) + Array.isArray");

  // typeof returns one of 8 strings; TS treats `typeof x === "<lit>"` as a type
  // guard for the PRIMITIVE arms. The two blind spots below are what makes
  // typeof USELESS for narrowing objects. (Full typeof table: VALUES_TYPES_
  // COERCION §2.)
  console.log("typeof's blind spots (why typeof alone can't narrow objects):");
  console.log(`  typeof null   = ${typeof null}    <- THE LIE: null is a primitive`);
  console.log(`  typeof []     = ${typeof []}    <- arrays report "object"`);
  console.log(`  typeof {}     = ${typeof {}}`);
  console.log(`  typeof "a"    = ${typeof "a"}`);
  console.log(`  typeof 1      = ${typeof 1}`);
  check('typeof null === "object" (THE LIE — typeof CANNOT narrow null)', typeof null === "object");
  check('typeof [] === "object" (typeof CANNOT tell array from object)', typeof [] === "object");
  check('typeof {} === "object"', typeof {} === "object");

  // THE FIXES: Array.isArray (realm-safe) for arrays; `=== null` for null.
  check("Array.isArray([]) === true (the realm-safe array test)", Array.isArray([]) === true);
  check("Array.isArray({}) === false", Array.isArray({}) === false);
  check("Array.isArray(null) === false", Array.isArray(null) === false);

  // Live narrowing proofs — typeof narrows the primitive arms of a union, and
  // narrowing is symmetric (the else branch narrows to what's LEFT).
  console.log("");
  console.log('typeof narrows the PRIMITIVE arms of a union (live expectType):');
  function classify(x: string | number): string {
    if (typeof x === "string") {
      expectType<Equal<typeof x, string>>('typeof === "string" narrows string|number -> string');
      return x.toUpperCase(); // compiles: x is string here
    }
    expectType<Equal<typeof x, number>>("after the string arm is removed, union -> number");
    return x.toFixed(0); // compiles: x is number here
  }
  console.log(`  classify("hi") = ${classify("hi")}`);
  console.log(`  classify(42)   = ${classify(42)}`);

  // Array.isArray narrows T | T[] -> T[] (and the else branch -> T). This is the
  // ONLY reliable way to narrow an array out of a union (typeof [] is "object").
  console.log("");
  console.log("Array.isArray narrows T | T[] (live expectType):");
  function firstOrIt(value: string | string[]): string {
    if (Array.isArray(value)) {
      expectType<Equal<typeof value, string[]>>("Array.isArray narrows string|string[] -> string[]");
      const head = value[0]; // noUncheckedIndexedAccess -> string | undefined
      return head !== undefined ? head : "(empty)";
    }
    expectType<Equal<typeof value, string>>("else branch narrows -> string (the T arm)");
    return value;
  }
  console.log(`  firstOrIt(["a","b"]) = ${firstOrIt(["a", "b"])}`);
  console.log(`  firstOrIt("solo")    = ${firstOrIt("solo")}`);

  console.log("");
  console.log("(tsc-verified, not run: proof_noGuardErrors, proof_typeofObjectKeepsNull,");
  console.log(" proof_cantWidenBeyondDeclared — each @ts-expect-error suppresses a real error)");
  check("typeof can't remove null from a typeof-object branch (tsc proof above)", true);
}

// ============================================================================
// Section B — truthiness + equality + the `in` operator narrowing
// ============================================================================

function sectionB(): void {
  sectionBanner("B — truthiness + equality + the `in` operator narrowing");

  // Truthiness narrowing: `if (x)` removes the falsy arms from the type. For a
  // `string | null | undefined`, after `if (x)` the type is `string` (null,
  // undefined — and "" — are all removed; "" is a string anyway, so the TYPE
  // collapses to string). CAVEAT (VALUES_TYPES_COERCION §4): `if (strs)` also
  // removes the empty string "", which may not be what you intend.
  console.log("Truthiness narrows out the falsy arms:");
  function greet(name: string | null | undefined): string {
    if (name) {
      expectType<Equal<typeof name, string>>("if(name) narrows string|null|undefined -> string");
      return `hi ${name.toUpperCase()}`;
    }
    return "hi stranger";
  }
  console.log(`  greet("Pat") = ${greet("Pat")}`);
  console.log(`  greet(null) = ${greet(null)}`);

  // Equality narrowing: `=== null`, `=== "circle"`, and crucially `== null`
  // (which TS narrows to remove BOTH null and undefined — the nullish idiom).
  console.log("");
  console.log("Equality narrows on === , !== , and == (the nullish idiom):");
  interface Container {
    value: number | null | undefined;
  }
  function doubled(c: Container): number {
    if (c.value != null) {
      // `!= null` removes null AND undefined -> c.value is number
      expectType<Equal<typeof c.value, number>>("c.value != null narrows -> number (both nulls out)");
      return c.value * 2;
    }
    return -1;
  }
  console.log(`  doubled({value:21})      = ${doubled({ value: 21 })}`);
  console.log(`  doubled({value:null})    = ${doubled({ value: null })}`);
  console.log(`  doubled({value:undefined}) = ${doubled({ value: undefined })}`);
  check("== null / != null remove both null and undefined (the nullish idiom)", true);

  // The `in` operator narrowing: `"swim" in animal` narrows to the union members
  // that HAVE (a required or optional) `swim`. RUNTIME: `in` searches the OWN
  // keys AND the prototype chain; throws TypeError if the RHS is not an object.
  console.log("");
  console.log("The `in` operator narrows on a property/method name:");
  const fish: Fish = { swim: () => undefined };
  const bird: Bird = { fly: () => undefined };
  function move(animal: Fish | Bird): string {
    if ("swim" in animal) {
      expectType<Equal<typeof animal, Fish>>('"swim" in animal narrows Fish|Bird -> Fish');
      return "swimming";
    }
    expectType<Equal<typeof animal, Bird>>("else branch -> Bird (Fish removed)");
    return "flying";
  }
  console.log(`  "swim" in fish  = ${"swim" in fish}    -> ${move(fish)}`);
  console.log(`  "swim" in bird  = ${"swim" in bird}   -> ${move(bird)}`);
  check('"swim" in fish === true (in searches own keys)', "swim" in fish === true);
  check('"swim" in bird === false', "swim" in bird === false);

  // `in` also finds INHERITED properties (it walks the prototype chain):
  const protoHolder = Object.create({ inherited: 99 });
  check('"in" finds inherited (prototype-chain) properties', "inherited" in protoHolder === true);

  // `in` THROWS at runtime if the RHS is not an object (null/undefined). tsc
  // forbids the static form `"x" in null` (the RHS must be an object type), so
  // we route a null through an `object`-typed slot via double assertion (NOT
  // `any`) to probe the real runtime behavior the type system can't express.
  let inThrew = false;
  const notAnObject: object = null as unknown as object;
  try {
    void ("x" in notAnObject);
  } catch (e) {
    inThrew = e instanceof TypeError;
  }
  check('"x" in null throws TypeError (RHS must be an object)', inThrew);
}

// ============================================================================
// Section C — instanceof narrowing (Date, Error, custom class) + catch-unknown
// ============================================================================

function sectionC(): void {
  sectionBanner("C — instanceof narrowing (Date/Error/class) + catch-unknown");

  // instanceof narrows to a CLASS. RUNTIME (MDN): `x instanceof C` tests whether
  // C.prototype appears ANYWHERE in x's prototype chain — so a subclass instance
  // is instanceof of every ancestor, all the way up to Object.
  const ve = new ValidationError("bad input");
  console.log("instanceof walks the prototype chain:");
  console.log(`  ve instanceof ValidationError = ${ve instanceof ValidationError}`);
  console.log(`  ve instanceof Error           = ${ve instanceof Error}`);
  console.log(`  ve instanceof Object          = ${ve instanceof Object}`);
  check("ve instanceof ValidationError (its own class)", ve instanceof ValidationError);
  check("ve instanceof Error (parent class — chain walk)", ve instanceof Error);
  check("ve instanceof Object (chain reaches Object.prototype)", ve instanceof Object);

  // instanceof Date narrowing:
  console.log("");
  console.log("instanceof Date narrows Date|string:");
  function label(x: Date | string): string {
    if (x instanceof Date) {
      expectType<Equal<typeof x, Date>>("instanceof Date narrows Date|string -> Date");
      return `year ${x.getUTCFullYear()}`; // compiles: Date method
    }
    expectType<Equal<typeof x, string>>("else branch -> string");
    return x.toUpperCase(); // compiles: string method
  }
  // Fixed date (no Date.now — determinism, §4.2 rule 2).
  const fixed = new Date("2024-01-15T10:30:00Z");
  console.log(`  label(new Date('2024-01-15')) = ${label(fixed)}`);
  console.log(`  label('hello')               = ${label("hello")}`);

  // THE catch-unknown pairing (🔗 ERRORS_EXCEPTIONS §D): since TS 4.4 the catch
  // binding is `unknown`, so you MUST narrow before reading .message/.cause.
  console.log("");
  console.log("catch (e) binds `unknown` — narrow with instanceof:");
  let caughtMessage: string | null = null;
  let caughtClass: string | null = null;
  try {
    throw new ValidationError("bad input");
  } catch (e) {
    if (e instanceof ValidationError) {
      expectType<Equal<typeof e, ValidationError>>("instanceof narrows catch(unknown) -> ValidationError");
      caughtMessage = e.message; // compiles: e is ValidationError
      caughtClass = e.name;
    } else if (e instanceof Error) {
      caughtMessage = e.message;
      caughtClass = e.name;
    }
  }
  console.log(`  caught class   = ${caughtClass}`);
  console.log(`  caught message = ${JSON.stringify(caughtMessage)}`);
  check("instanceof narrows catch-bound unknown to ValidationError", caughtClass === "ValidationError");
  check("narrowed catch binding exposes .message", caughtMessage === "bad input");

  // instanceof vs typeof: instanceof is for OBJECTS (constructed with new, or
  // objects like arrays). Primitives are NOT instances: tsc correctly forbids
  // `"s" instanceof String` statically (the string-primitive LHS is not an
  // object type) — that gotcha is documented in the .md pitfalls instead.
  console.log("");
  console.log("instanceof is for objects (arrays/dates are objects):");
  check("[] instanceof Array === true", [] instanceof Array);
  check("[] instanceof Object === true (Array.prototype chain reaches Object)", [] instanceof Object);
  check("new Date(0) instanceof Date === true", new Date(0) instanceof Date);
}

// ============================================================================
// Section D — TYPE PREDICATES (`x is T`) + assertion functions (`asserts`)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — TYPE PREDICATES (`x is T`) + assertion functions (`asserts`)");

  // THE PAYOFF: a user-defined type guard. The body is an ordinary boolean
  // check; the `value is string` RETURN TYPE is what narrows the caller. Build
  // the guard once, reuse it everywhere.
  console.log("User-defined type predicate `value is string` narrows the caller:");
  function describe(value: unknown): string {
    if (isString(value)) {
      expectType<Equal<typeof value, string>>("isString narrows unknown -> string");
      return `string of length ${value.length}`; // compiles: string
    }
    if (isNumber(value)) {
      expectType<Equal<typeof value, number>>("isNumber narrows unknown -> number");
      return `number ${value.toFixed(0)}`;
    }
    return "something else";
  }
  console.log(`  describe("hi") = ${describe("hi")}`);
  console.log(`  describe(42)   = ${describe(42)}`);
  console.log(`  describe(true) = ${describe(true)}`);
  check("isString is a correct guard for a string", isString("x") === true);
  check("isString rejects a number", isString(1) === false);

  // A predicate narrows BOTH branches: the if-branch -> the asserted type, the
  // else-branch -> the type with the asserted arm REMOVED.
  console.log("");
  console.log("Predicate narrows BOTH branches (Fish kept / Fish removed):");
  function act(pet: Fish | Bird): string {
    if (isFish(pet)) {
      expectType<Equal<typeof pet, Fish>>("isFish narrows Fish|Bird -> Fish");
      return "swim";
    }
    expectType<Equal<typeof pet, Bird>>("else branch -> Bird (Fish removed)");
    return "fly";
  }
  console.log(`  act({swim}) = ${act({ swim: () => undefined })}`);
  console.log(`  act({fly})  = ${act({ fly: () => undefined })}`);

  // Predicates compose with Array.filter: TS widens the filter's callback
  // return to a predicate, so the RESULT array is typed Fish[], not (Fish|Bird)[].
  console.log("");
  console.log("Predicate filters (Fish|Bird)[] -> Fish[]:");
  const zoo: ReadonlyArray<Fish | Bird> = [
    { swim: () => undefined },
    { fly: () => undefined },
    { swim: () => undefined },
  ];
  const onlyFish: Fish[] = zoo.filter(isFish);
  console.log(`  zoo.length=${zoo.length}  onlyFish.length=${onlyFish.length}`);
  expectType<Equal<typeof onlyFish, Fish[]>>("zoo.filter(isFish) is typed Fish[]");
  check("filter(isFish) keeps the 2 Fish", onlyFish.length === 2);

  // ASSERTION FUNCTIONS: `asserts value is T`. If the function returns, the
  // caller's value is narrowed to T; otherwise it THROWS. Narrow-OR-throw is the
  // eager cousin of the predicate (which is a branch, not a throw).
  console.log("");
  console.log("Assertion functions narrow OR throw:");
  function useAsserts(value: unknown): string {
    assertString(value); // returns void; on return, value is string for the rest
    expectType<Equal<typeof value, string>>("assertString narrows unknown -> string for the rest");
    return value.toUpperCase();
  }
  console.log(`  useAsserts("hi") = ${useAsserts("hi")}`);

  let assertStringThrew = false;
  try {
    useAsserts(42);
  } catch (e) {
    assertStringThrew = e instanceof Error;
  }
  check("assertString(42) throws (narrow OR throw)", assertStringThrew);

  // assertDefined narrows to NonNullable<T> — the canonical null/undefined killer.
  console.log("");
  console.log("assertDefined narrows to NonNullable<T>:");
  function useAssertDefined(value: string | null): string {
    assertDefined(value);
    expectType<Equal<typeof value, string>>("assertDefined narrows string|null -> NonNullable<string>=string");
    return value.toUpperCase(); // compiles: null/undefined removed
  }
  console.log(`  useAssertDefined("hi") = ${useAssertDefined("hi")}`);

  let assertDefinedThrew = false;
  try {
    useAssertDefined(null);
  } catch (e) {
    assertDefinedThrew = e instanceof Error;
  }
  check("assertDefined(null) throws", assertDefinedThrew);

  // `asserts value` (no `is`): asserts truthiness — removes falsy arms eagerly.
  console.log("");
  console.log("asserts value (truthiness) narrows eagerly:");
  function useTruthy(value: string | 0 | null): string {
    assertTruthy(value);
    expectType<Equal<typeof value, string>>("assertTruthy narrows (string|0|null) -> string");
    return value;
  }
  console.log(`  useTruthy("ok") = ${useTruthy("ok")}`);

  let assertTruthyThrew = false;
  try {
    useTruthy(0);
  } catch (e) {
    assertTruthyThrew = e instanceof Error;
  }
  check("assertTruthy(0) throws (0 is falsy)", assertTruthyThrew);
}

// ============================================================================
// Section E — control-flow narrowing + discriminated unions + exhaustiveness
// ============================================================================

function sectionE(): void {
  sectionBanner("E — control-flow narrowing + discriminated unions + exhaustiveness");

  // Assignment narrowing: assigning to a `let` re-narrows it to the assigned
  // value's type. But you can NEVER widen beyond the DECLARED type
  // (proof_cantWidenBeyondDeclared above: `x = true` on a `string|number` errors).
  console.log("Assignment re-narrows (but never beyond the declared type):");
  function assignmentFlow(): string {
    let x: string | number | boolean;
    x = "hi";
    expectType<Equal<typeof x, string>>("x = 'hi' narrows -> string");
    const a = x.toUpperCase(); // compiles: string
    x = 42;
    expectType<Equal<typeof x, number>>("x = 42 re-narrows -> number");
    const b = x.toFixed(0); // compiles: number
    return `${a}-${b}`;
  }
  console.log(`  assignmentFlow() = ${assignmentFlow()}`);

  // return / throw narrow the REST of the function: after `if (typeof x ===
  // "string") return;`, the code below has the string arm removed (control-flow
  // analysis — TS tracks reachability).
  console.log("");
  console.log("return / throw narrow the remainder (control-flow analysis):");
  function afterReturn(x: string | number): string {
    if (typeof x === "string") {
      return x.toUpperCase(); // string arm fully handled
    }
    expectType<Equal<typeof x, number>>("after the string-return, union -> number (string removed)");
    return x.toFixed(0);
  }
  console.log(`  afterReturn("hi") = ${afterReturn("hi")}`);
  console.log(`  afterReturn(42)   = ${afterReturn(42)}`);

  // DISCRIMINATED UNION narrowing: when every member shares a property with a
  // UNIQUE literal type (the "discriminant", here `kind`), a `===`/`switch` on
  // that tag narrows to the single matching member. (🔗 UNIONS_INTERSECTIONS.)
  console.log("");
  console.log("Discriminated union: tag literal narrows to one member:");
  function describe(s: Shape): string {
    if (s.kind === "circle") {
      expectType<Equal<typeof s, Circle>>('s.kind === "circle" narrows Shape -> Circle');
      return `circle r=${s.radius}`; // compiles: s.radius
    }
    expectType<Equal<typeof s, Square>>("else branch -> Square");
    return `square side=${s.side}`; // compiles: s.side
  }
  console.log(`  describe(circle r=3) = ${describe({ kind: "circle", radius: 3 })}`);
  console.log(`  describe(square s=4) = ${describe({ kind: "square", side: 4 })}`);

  // The SAME narrowing works in a switch. noFallthroughCasesInSwitch requires a
  // return/break per case — each case narrows `s` to one member automatically.
  console.log("");
  console.log("Discriminated union in a switch (each case auto-narrows):");
  function area(s: Shape): number {
    switch (s.kind) {
      case "circle":
        expectType<Equal<typeof s, Circle>>('case "circle" narrows -> Circle');
        return Math.PI * s.radius * s.radius; // compiles: s.radius
      case "square":
        expectType<Equal<typeof s, Square>>('case "square" narrows -> Square');
        return s.side * s.side; // compiles: s.side
    }
  }
  const circleArea = area({ kind: "circle", radius: 2 });
  const squareArea = area({ kind: "square", side: 3 });
  console.log(`  area(circle r=2) = ${circleArea.toFixed(6)}  (PI * 4)`);
  console.log(`  area(square s=3) = ${squareArea}`);
  check("area(circle r=2) = PI * 4", circleArea === Math.PI * 4);
  check("area(square s=3) = 9", squareArea === 9);

  // EXHAUSTIVENESS via `never`: in the default branch of an exhaustive switch,
  // `s` is narrowed to `never` (every member has been handled). Assigning `never`
  // to a `never`-typed variable typechecks. If a NEW member is later added to
  // Shape, that assignment STOPS typechecking — the compiler TELLS you a case is
  // missing. (The throw-based variant is in ERRORS_EXCEPTIONS §E via `never`.)
  console.log("");
  console.log("Exhaustiveness via `never` (compile-time completeness alarm):");
  function exhaustiveArea(s: Shape): number {
    switch (s.kind) {
      case "circle":
        return Math.PI * s.radius * s.radius;
      case "square":
        return s.side * s.side;
      default: {
        const _exhaustive: never = s; // compiles: s is never here (all members handled)
        expectType<Equal<typeof s, never>>("default branch narrows Shape -> never (exhaustive)");
        return _exhaustive; // never is assignable to number
      }
    }
  }
  console.log(`  exhaustiveArea(circle r=2) = ${exhaustiveArea({ kind: "circle", radius: 2 }).toFixed(6)}`);
  console.log(`  exhaustiveArea(square s=3) = ${exhaustiveArea({ kind: "square", side: 3 })}`);
  console.log('  (add a `triangle` member and `const _exhaustive: never = s` errors ->');
  console.log("   the compiler flags the unhandled case. See TYPE_NARROWING.md pitfalls.)");
  check("exhaustive default narrows Shape to never (tsc-verifiable)", true);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("type_narrowing.ts — Phase 2 bundle (type-system).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TS types are ERASED at runtime. Narrowing is the bridge —");
  console.log("a RUNTIME check (typeof/in/instanceof/tag) tells the COMPILER the");
  console.log("value's type in the branch that follows.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
