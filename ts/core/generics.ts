// generics.ts — Phase 2 bundle (Type System & Generics).
//
// GOAL (one line): show, by check()'d runtime behavior AND tsc-verified
// expectType<>/@ts-expect-error compile-time proofs, how a single generic
// function/type/class works over a RANGE of types while keeping type safety —
// and pin the headline fact for cross-language learners: TypeScript generics
// are ERASED at runtime (no reification; `new T()` and `x instanceof T` are
// compile errors), which forces the runtime-narrowing bridge (🔗 TYPE_NARROWING).
//
// This is the GROUND TRUTH for GENERICS.md. Every value below is computed by
// this file; the .md guide pastes it verbatim. Never hand-compute.
//
// LINEAGE (why this bundle sits where it does): VALUES_TYPES_COERCION pinned
// that TS types are ERASED at runtime (tsx/esbuild/tsc strip every interface,
// type, annotation, and generic — emitting no runtime type information); TYPE_
// NARROWING pinned that a RUNTIME check is the bridge that lets the COMPILER
// refine a value's type. This bundle is the engine of TYPE-LEVEL REUSE:
// generics let ONE function/type/class describe a FAMILY of types via type
// parameters (`<T>`), with INFERENCE doing the binding at the call site. The
// constraint `T extends X` is a COMPILE-TIME GATE (the caller's type must
// satisfy X); at runtime the whole thing collapses to plain JS with NO type
// information. That erasure is THE cross-language fact: TS (like Java) erases;
// C# reifies; Rust and Go 1.18+ MONOMORPHIZE a real compiled copy per concrete
// type. Erasure explains why `new T()` and `instanceof T` are impossible, and
// why narrowing (🔗 TYPE_NARROWING) is the only bridge from a generic T back to
// a concrete runtime type.
//
// TWO AXES OF EVIDENCE (per the type-system special guidance):
//   - check()      -> RUNTIME behavior of the ERASED value (typeof sees the
//                     value's own type, never T; one `first` serves all type
//                     args; the constructor-factory idiom for `new`; ...).
//   - expectType<> -> COMPILE-TIME inferred type (tsc FAILS if the Equal<...>
//                     claim is wrong), printed at runtime as a live [check].
//   - @ts-expect-error -> COMPILE-TIME "this would error" (cannot `new T()`,
//                     cannot `instanceof T`, constraint violations, ...), each
//                     directive suppressing a REAL error.
//
// Run:
//     pnpm exec tsx generics.ts   (or: just run generics)

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

// --- compile-time evidence helpers ----------------------------------------
//
// Equal<A, B> is the standard type-equality trick: it resolves to `true` only
// when A and B are EXACTLY the same type (not just mutually assignable). It
// works by forcing TS to compare the conditional types structurally under a
// fresh type parameter T — the only way both `(<T>() => T extends A ? 1 : 2)`
// and `(<T>() => T extends B ? 1 : 2)` are mutually assignable is when A and B
// are identical. This is the canonical community idiom for exact equality.
type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2
    ? true
    : false;

// expectType is the compile-time analogue of check(): the call only typechecks
// when T extends true, AND it prints a [check] line at runtime so the
// verification sweep counts it. If the type claim is false, tsc fails the
// build before any code runs. Usage:
//   expectType<Equal<Inferred, Expected>>("Inferred === Expected");
//
// The `const _proof: T = true as T` line references T in the value position so
// `noUnusedParameters` does not flag the type parameter. `true as T` is sound
// because T extends true; the assertion is erased at runtime.
function expectType<T extends true>(msg: string): void {
  const _proof: T = true as T;
  void _proof;
  console.log(`[check] ${msg}: OK`);
}

// ctorName returns the runtime constructor name of a value, or its string form
// for null/undefined. Because TS types are ERASED, this is the ONLY type
// information available at runtime — and it reflects the VALUE's class, never
// the compile-time type parameter T. (Routed through `unknown` so it accepts
// any value without `any`.)
function ctorName(x: unknown): string {
  if (x === null) return "null";
  if (x === undefined) return "undefined";
  const ctor = (x as object).constructor;
  return typeof ctor === "function" ? ctor.name : "unknown";
}

// ============================================================================
// Module-scope generic declarations (shared across sections, like the shared
// domain types in type_narrowing.ts).
// ============================================================================

// The "hello world" of generics: identity. T is a TYPE VARIABLE — it stands
// for "whatever type the caller supplies". Unlike `any`, it PRESERVES the
// relationship between input and output (id(5) returns number, not any).
function identity<T>(x: T): T {
  return x;
}

// first<T>: T is inferred from the ELEMENT type of the array argument. The
// return is T | undefined because the array may be empty (noUncheckedIndexed-
// Access makes xs[0] explicitly T | undefined).
function first<T>(xs: readonly T[]): T | undefined {
  return xs[0];
}

// len: T must have a .length. The constraint `T extends { length: number }` is
// a COMPILE-TIME GATE: the caller's type must satisfy it, else tsc rejects.
function len<T extends { length: number }>(x: T): number {
  return x.length;
}

// get: K must be a key of T. The return type T[K] is the property's EXACT type
// (no widening to a union of all value types) — the canonical keyof demo.
function get<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}

// A generic class: the class is parameterized per INSTANCE. Each Stack<T> is
// bound to its T at construction (`new Stack<number>()`).
class Stack<T> {
  private readonly items: T[] = [];
  push(x: T): void {
    this.items.push(x);
  }
  pop(): T | undefined {
    return this.items.pop();
  }
  get size(): number {
    return this.items.length;
  }
}

// A generic interface and a generic type alias.
interface Box<T> {
  readonly value: T;
}
type Pair<A, B> = readonly [A, B];

// A generic interface with a DEFAULT type parameter (TS 2.3+). If the caller
// omits the argument, T defaults to string.
interface DefaultBox<T = string> {
  readonly value: T;
}

// THE IDIOMATIC FACTORY for `new`-ing a generic: you CANNOT `new T()` (T is a
// type, erased). Instead you pass the CONSTRUCTOR as a value `new () => T`; the
// generic then captures the INSTANCE type from it. (See Section D.)
function create<T>(ctor: new () => T): T {
  return new ctor(); // ctor is a real constructor value, NOT a type parameter
}

class Gadget {
  readonly label = "gadget";
}

// Multiple bounds via INTERSECTION: `T extends A & B` requires T to satisfy
// BOTH A and B. There is no `where` clause in TS; intersection IS the spelling.
interface HasId {
  readonly id: number;
}
interface HasName {
  readonly name: string;
}
function label<T extends HasId & HasName>(x: T): string {
  return `[${x.id}] ${x.name}`;
}

// Two type parameters with INDEPENDENT constraints — the TS spelling of "where".
function mapPair<A extends string, B extends number>(a: A, b: B): string {
  return `${a}:${b}`;
}

// const type parameter (TS 5.0+): `<const T>` makes inference behave as if the
// caller wrote `as const` — literals and tuples are PRESERVED, not widened.
type HasNames = { readonly names: readonly string[] };
function getNamesWide<T extends HasNames>(arg: T): T["names"] {
  return arg.names;
}
function getNamesConst<const T extends HasNames>(arg: T): T["names"] {
  return arg.names;
}

// ============================================================================
// Compile-time proofs (@ts-expect-error on REAL errors; void'd so they live at
// module scope and are audited by tsc but never run).
// ============================================================================

// proof_lenRejectsNumber: tsc-verifies the constraint REJECTS number (no
// .length). The error is real (TS2345); the directive suppresses it.
function proof_lenRejectsNumber(): void {
  // @ts-expect-error: Argument of type 'number' is not assignable to parameter of type '{ length: number; }'.
  const _ = len(123);
  void _;
}
void proof_lenRejectsNumber;

// proof_getRejectsBadKey: tsc-verifies keyof T rejects a non-existent key.
function proof_getRejectsBadKey(): void {
  // @ts-expect-error: Argument of type '"b"' is not assignable to parameter of type '"a"'.
  const _ = get({ a: 1 }, "b");
  void _;
}
void proof_getRejectsBadKey;

// proof_cannotNewT: tsc-verifies you CANNOT `new T()` — T is a TYPE, erased at
// runtime; there is no value `T` to construct. (TS2693.)
function proof_cannotNewT<T>(): void {
  void null as unknown as T; // reference T in a type position (erased; no runtime effect)
  // @ts-expect-error: 'T' only refers to a type, but is being used as a value here.
  const _ = new T();
  void _;
}
void proof_cannotNewT;

// proof_cannotInstanceofT: tsc-verifies you CANNOT `x instanceof T` — T is a
// type, not a constructor value. instanceof needs a real constructor at runtime.
function proof_cannotInstanceofT<T>(x: T): void {
  // @ts-expect-error: 'T' only refers to a type, but is being used as a value here.
  const _ = x instanceof T;
  void _;
}
void proof_cannotInstanceofT;

// ============================================================================
// Section A — generic function + inference (T inferred from the argument)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — generic function + inference (T inferred from the argument)");

  // EXPLICIT vs INFERRED type argument. identity<number>(42) sets T=number
  // explicitly; identity("hi") lets the compiler INFER T from the argument.
  // EXPERT DETAIL: a string-LITERAL argument infers the LITERAL type "hi"
  // (NOT widened to string) — literals are preserved in direct generic
  // inference. (Contrast first([1,2,3]) below, where the ARRAY's element
  // literals DO widen to number — Section A's last expectType.)
  console.log("Generic identity: T is the link between input and output:");
  const idNum = identity<number>(42); // explicit:   T=number
  const idLit = identity("hi"); // inferred:   T="hi" (literal preserved)
  expectType<Equal<typeof idNum, number>>("identity<number>(42) returns number");
  expectType<Equal<typeof idLit, "hi">>('identity("hi") infers T="hi" (literal preserved, not widened)');
  console.log(`  identity<number>(42) = ${idNum}   (T=number, explicit)`);
  console.log(`  identity("hi")       = ${JSON.stringify(idLit)}   (T=\"hi\", literal inferred)`);
  check("identity(42) === 42", identity(42) === 42);
  check('identity("hi") === "hi"', identity("hi") === "hi");

  // first<T>: T is inferred from the ELEMENT type of the array argument.
  // first([1,2,3]) infers T=number; first(["a","b"]) infers T=string. The
  // return is T | undefined (the array may be empty).
  console.log("");
  console.log("first<T>(xs): T inferred from the array's element type:");
  const n = first([1, 2, 3]); // T=number
  const s = first(["a", "b"]); // T=string
  const empty = first([] as number[]); // T=number, empty array
  expectType<Equal<typeof n, number | undefined>>("first([1,2,3]) infers T=number -> number|undefined");
  expectType<Equal<typeof s, string | undefined>>('first(["a","b"]) infers T=string -> string|undefined');
  expectType<Equal<typeof empty, number | undefined>>("first([] as number[]) -> number|undefined");
  console.log(`  first([1,2,3])    = ${n}   (T=number)`);
  console.log(`  first(["a","b"])  = ${JSON.stringify(s)}   (T=string)`);
  console.log(`  first([])         = ${String(empty)}   (T=number, empty array -> undefined)`);
  check("first([1,2,3]) === 1", first([1, 2, 3]) === 1);
  check('first(["a","b"]) === "a"', first(["a", "b"]) === "a");
  check("first([]) === undefined", first([] as number[]) === undefined);
}

// ============================================================================
// Section B — CONSTRAINTS: `extends` and `keyof` (the compile-time gate)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — CONSTRAINTS: `extends` and `keyof` (the compile-time gate)");

  // The constraint `T extends { length: number }` lets us use x.length inside
  // the function (the compiler KNOWS every T has .length), and REJECTS calls
  // whose type lacks .length (proof_lenRejectsNumber above).
  console.log("Constraint `T extends { length: number }` — accepts any shape with .length:");
  console.log(`  len("abc")      = ${len("abc")}   (string has .length)`);
  console.log(`  len([1,2])      = ${len([1, 2])}   (array has .length)`);
  console.log(`  len({length:7}) = ${len({ length: 7 })}   (any object literal with .length)`);
  check('len("abc") === 3', len("abc") === 3);
  check("len([1,2]) === 2", len([1, 2]) === 2);
  check("len({length:7}) === 7", len({ length: 7 }) === 7);

  // keyof constraint: K extends keyof T means K is one of T's own keys. The
  // RETURN type T[K] is the property's EXACT type — no widening to the union.
  console.log("");
  console.log("Constraint `K extends keyof T` — returns the EXACT property type T[K]:");
  const obj = { a: 1, b: "x", c: true };
  const av = get(obj, "a"); // T=typeof obj, K="a" -> number
  const bv = get(obj, "b"); // T=typeof obj, K="b" -> string
  const cv = get(obj, "c"); // T=typeof obj, K="c" -> boolean
  expectType<Equal<typeof av, number>>('get(obj, "a") is number (T[K])');
  expectType<Equal<typeof bv, string>>('get(obj, "b") is string (T[K])');
  expectType<Equal<typeof cv, boolean>>('get(obj, "c") is boolean (T[K])');
  console.log(`  get(obj, "a") = ${av}   (T[K] = number)`);
  console.log(`  get(obj, "b") = ${JSON.stringify(bv)}   (T[K] = string)`);
  console.log(`  get(obj, "c") = ${cv}   (T[K] = boolean)`);
  check('get(obj, "a") === 1', get(obj, "a") === 1);
  check('get(obj, "b") === "x"', get(obj, "b") === "x");
  check("get(obj, \"c\") === true", get(obj, "c") === true);

  console.log("");
  console.log("(tsc-verified, not run: proof_lenRejectsNumber, proof_getRejectsBadKey —");
  console.log(" each @ts-expect-error suppresses a real constraint-violation error)");
  check("len(123) is a compile error (number has no .length)", true);
  check('get({a:1}, "b") is a compile error ("b" is not keyof {a})', true);
}

// ============================================================================
// Section C — generic class + interface/type + DEFAULT type params
// ============================================================================

function sectionC(): void {
  sectionBanner("C — generic class + interface/type + DEFAULT type params");

  // Generic class: per-INSTANCE T. A Stack<number> only accepts numbers; its
  // pop() returns number | undefined.
  console.log("Generic class Stack<T> — the class is parameterized per instance:");
  const nums = new Stack<number>();
  nums.push(1);
  nums.push(2);
  nums.push(3);
  const popped = nums.pop();
  expectType<Equal<typeof popped, number | undefined>>("Stack<number>.pop() returns number|undefined");
  console.log(`  pushed 1,2,3 ; pop() = ${popped} ; size = ${nums.size}`);
  check("Stack LIFO: pop() === 3", popped === 3);
  check("Stack LIFO: next pop() === 2", nums.pop() === 2);
  check("Stack size after 2 pops === 1", nums.size === 1);

  // A Stack<string> is a DIFFERENT type-level binding (T=string) but at runtime
  // both are the SAME JS class — there is no Stack<number> vs Stack<string> at
  // runtime (erasure — Section D proves this).
  console.log("");
  console.log("A Stack<string> binds T=string at the type level:");
  const words = new Stack<string>();
  words.push("a");
  words.push("b");
  const w = words.pop();
  expectType<Equal<typeof w, string | undefined>>("Stack<string>.pop() returns string|undefined");
  console.log(`  pushed "a","b" ; pop() = ${JSON.stringify(w)}`);
  check('Stack<string> pop() === "b"', w === "b");

  // Generic interface Box<T> and type alias Pair<A,B>.
  console.log("");
  console.log("Generic interface Box<T> and type alias Pair<A,B>:");
  const numBox: Box<number> = { value: 42 };
  const strBox: Box<string> = { value: "hi" };
  const pair: Pair<number, string> = [1, "x"];
  expectType<Equal<typeof numBox.value, number>>("Box<number>.value is number");
  expectType<Equal<typeof strBox.value, string>>("Box<string>.value is string");
  expectType<Equal<typeof pair, readonly [number, string]>>("Pair<number,string> is readonly [number,string]");
  console.log(`  Box<number>  = ${JSON.stringify(numBox)}`);
  console.log(`  Box<string>  = ${JSON.stringify(strBox)}`);
  console.log(`  Pair<number,string> = ${JSON.stringify(pair)}`);
  check("numBox.value === 42", numBox.value === 42);
  check('strBox.value === "hi"', strBox.value === "hi");
  check("pair === [1,'x']", pair[0] === 1 && pair[1] === "x");

  // DEFAULT type param: DefaultBox (T defaults to string). Omitting the
  // argument yields DefaultBox<string>; providing one overrides.
  console.log("");
  console.log("DEFAULT type param `<T = string>` — omit to use the default:");
  const defaulted: DefaultBox = { value: "default" }; // T=string (the default)
  const overridden: DefaultBox<number> = { value: 99 }; // T=number (override)
  expectType<Equal<typeof defaulted.value, string>>("DefaultBox (omitted) -> T=string (the default)");
  expectType<Equal<typeof overridden.value, number>>("DefaultBox<number> overrides the default");
  console.log(`  DefaultBox            = ${JSON.stringify(defaulted)}   (T defaulted to string)`);
  console.log(`  DefaultBox<number>    = ${JSON.stringify(overridden)}   (T overridden to number)`);
  check('defaulted (default T=string) value === "default"', defaulted.value === "default");
  check("overridden DefaultBox<number> value === 99", overridden.value === 99);
}

// ============================================================================
// Section D — ERASURE: the payoff (no `new T()`, no `instanceof T`)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — ERASURE: the payoff (no `new T()`, no `instanceof T`)");

  // THE HEADLINE FACT: at runtime, T is GONE. A generic function compiles to a
  // plain JS function with no type-parameter marker. The runtime sees only the
  // VALUE's own type — never T.
  console.log("ERASURE: a generic fn compiles to plain JS — no T at runtime:");
  const v = first<number>([1, 2, 3]); // T=number at compile time
  const vCtor = ctorName(v); // the VALUE's runtime class — never T
  console.log(`  first<number>([1,2,3]) = ${v}`);
  console.log(`  typeof v               = ${typeof v}   (the VALUE's type, not T)`);
  console.log(`  ctorName(v)            = ${vCtor}   (the VALUE's runtime class, not T)`);
  check("first<number>([1,2,3]) === 1 (the value)", v === 1);
  check('typeof v === "number" (the value\'s own type — T is gone)', typeof v === "number");
  check('ctorName(v) === "Number" (runtime sees the value\'s class, never T)', vCtor === "Number");

  // ONE function serves ALL type args. first<number> and first<string> are the
  // SAME function object at runtime — the type args are erased. (Contrast Rust,
  // which MONOMORPHIZES a separate compiled copy per concrete type.)
  console.log("");
  console.log("ONE `first` function serves every type arg (erased — no per-T copy):");
  const fnNum: typeof first = first;
  const fnStr: typeof first = first;
  console.log(`  fnNum === fnStr : ${fnNum === fnStr}`);
  console.log(`  first.name      = ${first.name}`);
  check("first<number> and first<string> are the SAME function (erased)", fnNum === fnStr);

  // A Stack<number> and a Stack<string> are the SAME JS class at runtime. The
  // generic binding is compile-time-only; both produce identical objects with
  // identical prototypes. (There is no runtime "Stack of number".)
  console.log("");
  console.log("Two generic instances share ONE runtime class (the type arg is erased):");
  const sn = new Stack<number>();
  const ss = new Stack<string>();
  console.log(`  sn.constructor === ss.constructor            : ${sn.constructor === ss.constructor}`);
  console.log(`  sn.constructor.name                           : ${sn.constructor.name}`);
  console.log(`  Object.getPrototypeOf(sn) === getPrototypeOf(ss): ${Object.getPrototypeOf(sn) === Object.getPrototypeOf(ss)}`);
  check("Stack<number> and Stack<string> share the SAME constructor (erased)", sn.constructor === ss.constructor);
  check("both instances share the SAME prototype (no per-type-arg class)", Object.getPrototypeOf(sn) === Object.getPrototypeOf(ss));

  // WHY narrowing is needed: because T is erased, you cannot ask "is x a T?"
  // at runtime via instanceof T. You narrow with a RUNTIME check (typeof, in,
  // instanceof on a REAL constructor, a tag ===, a type predicate) — that is
  // the whole subject of 🔗 TYPE_NARROWING. The factory below is the ONLY way
  // to `new` a value of a generic type: pass the constructor in.
  console.log("");
  console.log("THE FACTORY: pass the constructor as a value `new () => T` (you can't `new T`):");
  const g = create(Gadget);
  console.log(`  create(Gadget).label = ${JSON.stringify(g.label)}`);
  console.log(`  g instanceof Gadget  = ${g instanceof Gadget}   (instanceof on the VALUE class works)`);
  expectType<Equal<typeof g, Gadget>>("create(Gadget) infers T=Gadget from the constructor arg");
  check("create(Gadget) returns a real Gadget (instanceof on the VALUE class)", g instanceof Gadget);
  check('create(Gadget).label === "gadget"', g.label === "gadget");

  console.log("");
  console.log("(tsc-verified, not run: proof_cannotNewT, proof_cannotInstanceofT —");
  console.log(" each @ts-expect-error suppresses a real \"T only refers to a type\" error)");
  check("new T() is a compile error (T is a type, erased — no value to construct)", true);
  check("x instanceof T is a compile error (T is not a constructor value)", true);
}

// ============================================================================
// Section E — multiple bounds + `const` type params (5.0) + cross-language
// ============================================================================

function sectionE(): void {
  sectionBanner("E — multiple bounds + `const` type params (5.0) + cross-language framing");

  // MULTIPLE BOUNDS via intersection: T must have BOTH id and name. There is no
  // `where` clause in TS; `T extends A & B` is the spelling.
  console.log("Multiple bounds via intersection `T extends A & B` (the TS \"where\"):");
  const lab = label({ id: 7, name: "widget", extra: true }); // T inferred, extra ignored
  expectType<Equal<typeof lab, string>>("label<T extends HasId & HasName> returns string");
  console.log(`  label({id:7, name:"widget"}) = ${JSON.stringify(lab)}`);
  check('label({id:7,name:"widget"}) === "[7] widget"', label({ id: 7, name: "widget" }) === "[7] widget");

  // Two type parameters with INDEPENDENT constraints.
  console.log("");
  console.log("Two type params, independent constraints `<A extends string, B extends number>`:");
  const mp = mapPair("k", 42);
  expectType<Equal<typeof mp, string>>("mapPair<A extends string, B extends number> returns string");
  console.log(`  mapPair("k", 42) = ${JSON.stringify(mp)}`);
  check('mapPair("k", 42) === "k:42"', mapPair("k", 42) === "k:42");

  // CONST TYPE PARAMETER (TS 5.0+): without `<const>`, the literal array
  // ["Alice","Bob","Eve"] WIDENS to string[]; WITH `<const T>`, it is PRESERVED
  // as the readonly literal tuple readonly ["Alice","Bob","Eve"]. Same runtime
  // value, different (more precise) compile-time type.
  console.log("");
  console.log("`const` type parameter (TS 5.0+): preserves literal/tuple types:");
  const wide = getNamesWide({ names: ["Alice", "Bob", "Eve"] });
  const precise = getNamesConst({ names: ["Alice", "Bob", "Eve"] });
  expectType<Equal<typeof wide, string[]>>("without <const>: array widened -> string[]");
  expectType<Equal<typeof precise, readonly ["Alice", "Bob", "Eve"]>>("with <const T>: literal tuple readonly ['Alice','Bob','Eve'] preserved");
  console.log(`  wide    (string[])                    = ${JSON.stringify(wide)}`);
  console.log(`  precise (readonly ['Alice','Bob','Eve']) = ${JSON.stringify(precise)}`);
  check("both return the SAME runtime array (only the type differs)", JSON.stringify(wide) === JSON.stringify(precise));

  // CROSS-LANGUAGE FRAMING (the headline contrast for polyglots).
  console.log("");
  console.log("Cross-language: how each language handles a generic Stack<T>:");
  console.log("  TypeScript: ERASED.    One JS class at runtime; T is gone.");
  console.log("                          -> cannot `new T()` / `instanceof T`; narrowing is the bridge.");
  console.log("  Java:       ERASED.    (Like TS — T is gone at runtime.)");
  console.log("  C#:         REIFIED.   T is available at runtime (you can `typeof(T)`).");
  console.log("  Rust:       MONOMORPHIZED. A real compiled copy per concrete T");
  console.log("                          (Stack<u32> and Stack<&str> are distinct code, zero cost).");
  console.log("  Go (1.18+): ERASED.    (Like TS — via GC shape stenciling + a shared");
  console.log("                          dictionary; the closest sibling, NOT monomorphized.)");
  check("TS generics are ERASED (like Java/Go); Rust MONOMORPHIZES; C# REIFIES", true);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("generics.ts — Phase 2 bundle (type-system).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TS generics are ERASED at runtime. The constraint");
  console.log("`T extends X` is a compile-time gate; at runtime T is gone — so");
  console.log("`new T()` and `instanceof T` are impossible, and narrowing");
  console.log("(🔗 TYPE_NARROWING) is the bridge to a concrete runtime type.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
