// utility_types.ts — Phase 2 bundle (TYPE-SYSTEM).
//
// GOAL (one line): pin, with compile-time `expectType<Equal<...>>` and
// `@ts-expect-error` gates plus runtime `check()`s for erasure, that every
// built-in Utility Type (Partial/Pick/Omit/Record/ReturnType/Parameters/
// Awaited/Exclude/Extract/NonNullable/...) is just a MAPPED or CONDITIONAL
// type — and reimplement five of them by hand to prove it.
//
// This is the GROUND TRUTH for UTILITY_TYPES.md. Every type-level claim below is
// pinned by `expectType<Equal<A, B>>("...")` (a tsc ERROR if A≠B) or by an
// `@ts-expect-error` (a tsc ERROR if the next line does NOT fail). Runtime
// `check()`s prove TYPE ERASURE: the utilities emit zero code. Nothing is
// hand-computed — change it -> re-run -> re-paste.
//
// LINEAGE (why this bundle is here): TypeScript ships ~20 built-in "Utility
// Types" — generic type-level functions over types. They are the STDLIB OF THE
// TYPE SYSTEM. The expert payoff is that ALL of them are implemented with just
// two primitives you already met in MAPPED_CONDITIONAL_TYPES: mapped types
// `{ [P in keyof T]: ... }` (Partial/Required/Readonly/Pick/Record) and
// conditional types `T extends U ? X : Y` with `infer` (Exclude/Extract/
// ReturnType/Parameters) plus one recursive conditional (Awaited). keyof /
// typeof / indexed access are the glue that feed them. Knowing BOTH the
// catalog AND how to roll your own is what separates TS users from experts.
//
// Run:
//     pnpm exec tsx utility_types.ts   (or: just run utility_types)

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts a RUNTIME invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
// (The utilities are compile-time only, so check() proves ERASURE: a value of
// type Partial<T> is, at runtime, just a plain object.)
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// === COMPILE-TIME GATES (the type-system evidence layer) ====================
//
// Equal<A,B> is the strictest possible type-level equality test (the trick from
// type-fest / type-challenges): two types are equal IFF these two generic
// function types are mutually assignable, which holds iff A and B are mutually
// assignable with identical structure. `expectType<Equal<A,B>>("...")` turns a
// false Equal into a hard tsc error (the call's type arg must extend `true`),
// so every expectType below is a COMPILE-TIME assertion the .md can rely on.
type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;

// T is the compile-time proof (must extend `true`); `_proof?: T` only exists so T
// is consumed in the signature (otherwise noUnusedLocals flags it). Underscore-
// prefixed params are ignored by noUnusedParameters, and the arg is optional so
// call sites stay clean: `expectType<Equal<A,B>>("A===B")`.
const expectType = <T extends true>(msg: string, _proof?: T): void => {
  console.log(`[check] ${msg}: OK`);
};

// Shared shape for the property-transform / subsetting demos.
interface Todo {
  title: string;
  description: string;
  done: boolean;
}

// ============================================================================
// Section A — Property transforms: Partial / Required / Readonly
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Property transforms: Partial / Required / Readonly");

  // Partial<T>: every property becomes optional (adds `?`). lib.d.ts body:
  //     type Partial<T> = { [P in keyof T]?: T[P]; };
  // That is a MAPPED type (`[P in keyof T]`) + the `?` modifier. This is THE
  // canonical mapped type — every property-transform utility shares this shape.

  // COMPILE-TIME pin (literal-type form): Partial<{a:1;b:2}> is exactly {a?:1;b?:2}.
  expectType<Equal<Partial<{ a: 1; b: 2 }>, { a?: 1; b?: 2 }>>(
    "Partial<{a:1;b:2}> === {a?:1;b?:2}"
  );
  // Same, on the shared Todo shape: every key is now optional.
  expectType<Equal<Partial<Todo>, { title?: string; description?: string; done?: boolean }>>(
    "Partial<Todo> === {title?; description?; done?}"
  );

  // Required<T> is Partial's mirror: it REMOVES `?` via the `-?` modifier.
  //     type Required<T> = { [P in keyof T]-?: T[P]; };
  // Round-trip: Required<Partial<Todo>> recovers Todo exactly.
  expectType<Equal<Required<Partial<Todo>>, Todo>>(
    "Required<Partial<Todo>> === Todo (round-trip)"
  );
  // @ts-expect-error: Required removed `?`, so 'done' is required — missing here.
  const required: Required<{ a?: number; done?: boolean }> = { a: 1 };
  void required; // (reference keeps noUnusedLocals happy; the error is the init)

  // Readonly<T> adds the `readonly` modifier to every property (mapped type again).
  //     type Readonly<T> = { readonly [P in keyof T]: T[P]; };
  const frozen: Readonly<Todo> = { title: "ship", description: "now", done: false };
  // @ts-expect-error: 'title' is readonly — cannot reassign.
  frozen.title = "later";

  // THE EXPERT PAYOFF — reimplement Partial BY HAND as a mapped type, then prove
  // it is byte-for-byte equal to the built-in (Equal<> is the strictest test).
  type PartialHand<T> = { [P in keyof T]?: T[P] };
  expectType<Equal<PartialHand<Todo>, Partial<Todo>>>(
    "hand-rolled PartialHand<T> === built-in Partial<T>"
  );
  expectType<Equal<PartialHand<{ a: 1; b: 2 }>, Partial<{ a: 1; b: 2 }>>>(
    "hand-rolled PartialHand === built-in Partial (literal)"
  );

  // RUNTIME erasure check: a Partial<Todo>-typed value is just a plain object.
  // Partial/Required/Readonly are compile-time only — zero runtime effect.
  const patch: Partial<Todo> = { done: true };
  check("typeof (Partial<Todo>-typed value) === 'object' (erasure)", typeof patch === "object");
  check("Partial-typed value keeps its key at runtime (patch.done === true)", patch.done === true);
}

// ============================================================================
// Section B — Subsetting: Pick / Omit + Record
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Subsetting: Pick / Omit + Record");

  // Pick<T, K>: keep only keys K (a mapped type over the key union K).
  //     type Pick<T, K extends keyof T> = { [P in K]: T[P]; };
  expectType<Equal<Pick<Todo, "title" | "done">, { title: string; done: boolean }>>(
    "Pick<Todo,'title'|'done'> === {title; done}"
  );
  // Pin: Pick<T,"a"> keeps ONLY a.
  expectType<Equal<Pick<{ a: 1; b: 2 }, "a">, { a: 1 }>>(
    "Pick<{a:1;b:2},'a'> === {a:1}"
  );

  const preview: Pick<Todo, "title" | "done"> = { title: "ship", done: false };
  // @ts-expect-error: 'description' was Pick-ed away — not on this type.
  void preview.description;

  // Omit<T, K> is DEFINED in lib.d.ts as Pick<T, Exclude<keyof T, K>> — i.e. it is
  // literally Pick composed with Exclude. That composition is why Omit sits here.
  //     type Omit<T, K extends keyof any> = Pick<T, Exclude<keyof T, K>>;
  expectType<Equal<Omit<Todo, "description">, { title: string; done: boolean }>>(
    "Omit<Todo,'description'> === {title; done}"
  );
  // Pin: Omit<T,"b"> drops b.
  expectType<Equal<Omit<{ a: 1; b: 2 }, "b">, { a: 1 }>>(
    "Omit<{a:1;b:2},'b'> === {a:1}"
  );
  // The lib definition is observable: Pick<Exclude> really IS Omit.
  expectType<
    Equal<Pick<Todo, Exclude<keyof Todo, "description">>, Omit<Todo, "description">>
  >("Pick<T,Exclude<keyof T,K>> === Omit<T,K> (the lib definition)");

  // Record<K, V>: construct a map from keys K to value type V.
  //     type Record<K extends keyof any, T> = { [P in K]: T };
  type Priority = "low" | "med" | "high";
  const counts: Record<Priority, number> = { low: 0, med: 3, high: 9 };
  expectType<Equal<Record<"a" | "b", number>, { a: number; b: number }>>(
    "Record<'a'|'b',number> === {a:number;b:number}"
  );
  check("Record<K,V> value at 'high' === 9 (runtime map)", counts.high === 9);

  // THE EXPERT PAYOFF — reimplement Pick and Record by hand as mapped types.
  type PickHand<T, K extends keyof T> = { [P in K]: T[P] };
  type RecordHand<K extends keyof any, V> = { [P in K]: V };
  expectType<Equal<PickHand<Todo, "title">, Pick<Todo, "title">>>(
    "hand-rolled PickHand === built-in Pick"
  );
  expectType<Equal<RecordHand<Priority, number>, Record<Priority, number>>>(
    "hand-rolled RecordHand === built-in Record"
  );

  // Erasure: a Record-typed value is a plain object at runtime.
  check("typeof (Record-typed value) === 'object' (erasure)", typeof counts === "object");
}

// ============================================================================
// Section C — Function introspection: ReturnType / Parameters / Awaited (infer)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Function introspection: ReturnType / Parameters / Awaited (infer)");

  // ReturnType<F> and Parameters<F> are CONDITIONAL types that use `infer` to pull
  // pieces out of a function signature. They are THE canonical infer examples.
  //     type ReturnType<F extends (...a:any)=>any> = F extends (...a:any)=>infer R ? R : any;
  //     type Parameters<F extends (...a:any)=>any> = F extends (...a:infer P)=>any ? P : never;
  // (The `any` mirrors lib.d.ts verbatim — it is the constraint the stdlib itself
  // uses so the function-signature match succeeds; `unknown` would not match.)

  type Fnum = () => number;
  type Ftwo = (x: number, y: string) => void;

  expectType<Equal<ReturnType<Fnum>, number>>("ReturnType<()=>number> === number");
  expectType<Equal<Parameters<Ftwo>, [x: number, y: string]>>(
    "Parameters<(x:number,y:string)=>void> === [number,string]"
  );
  // Value form: the resolved types are real runtime values.
  const ret: ReturnType<Fnum> = 42;
  const args: Parameters<Ftwo> = [1, "two"];
  check("ReturnType<()=>number> value is a real runtime number", ret === 42);
  check("Parameters<...> tuple value at [1] === 'two'", args[1] === "two");

  // Awaited<T> recursively unwraps nested Promises (a RECURSIVE conditional type).
  // Teaching form:
  //     type Awaited<T> = T extends null|undefined ? T
  //       : T extends Promise<infer R> ? Awaited<R> : T;
  expectType<Equal<Awaited<Promise<Promise<number>>>, number>>(
    "Awaited<Promise<Promise<number>>> === number (recursive unwrap)"
  );
  expectType<Equal<Awaited<Promise<string>>, string>>("Awaited<Promise<string>> === string");
  expectType<Equal<Awaited<number | Promise<string>>, number | string>>(
    "Awaited distributes over unions"
  );

  // THE EXPERT PAYOFF — reimplement ReturnType AND Awaited by hand.
  type ReturnTypeHand<F extends (...args: any) => any> =
    F extends (...args: any) => infer R ? R : any;
  type AwaitedHand<T> = T extends null | undefined
    ? T
    : T extends Promise<infer R>
      ? AwaitedHand<R>
      : T;
  expectType<Equal<ReturnTypeHand<Fnum>, ReturnType<Fnum>>>(
    "hand-rolled ReturnTypeHand === built-in ReturnType"
  );
  expectType<Equal<AwaitedHand<Promise<Promise<number>>>, number>>(
    "hand-rolled AwaitedHand recursively unwraps to number"
  );

  // @ts-expect-error: ReturnType<()=>string> is string, NOT number.
  const wrong: number = "hi" as ReturnType<() => string>;
  void wrong;

  // Erasure: the inferred tuple type is a plain array at runtime.
  check("typeof (Parameters tuple) === 'object' (erasure)", typeof args === "object");
}

// ============================================================================
// Section D — Union ops + keyof / typeof / indexed access + intrinsics
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Union ops (Exclude/Extract/NonNullable) + keyof/typeof/indexed + intrinsics");

  // Exclude / Extract / NonNullable are CONDITIONAL types that DISTRIBUTE over
  // unions (because their type parameter is "naked"). lib.d.ts:
  //     type Exclude<T,U> = T extends U ? never : T;
  //     type Extract<T,U> = T extends U ? T : never;
  //     type NonNullable<T> = T & {};   // current lib (classic conditional form below)
  expectType<Equal<Exclude<"a" | "b" | "c", "b">, "a" | "c">>(
    "Exclude<'a'|'b'|'c','b'> === 'a'|'c'"
  );
  expectType<Equal<Extract<"a" | "b" | "c", "a" | "z">, "a">>(
    "Extract<'a'|'b'|'c','a'|'z'> === 'a'"
  );
  expectType<Equal<NonNullable<string | null>, string>>(
    "NonNullable<string|null> === string"
  );
  expectType<Equal<NonNullable<string[] | null | undefined>, string[]>>(
    "NonNullable<string[]|null|undefined> === string[]"
  );

  // keyof — the union of keys; typeof — lift a value to its type; indexed access
  // — look up a property's type with T["k"]. These three compose into Pick/Record.
  expectType<Equal<keyof Todo, "title" | "description" | "done">>(
    "keyof Todo === 'title'|'description'|'done'"
  );
  expectType<Equal<Todo["title"], string>>("Todo['title'] === string (indexed access)");
  expectType<Equal<Todo["title" | "done"], string | boolean>>(
    "Todo['title'|'done'] === string|boolean"
  );

  const point = { x: 3, y: 4 };
  type Point = typeof point;
  expectType<Equal<Point, { x: number; y: number }>>(
    "typeof {x:3,y:4} === {x:number;y:number}"
  );
  // typeof + indexed access: pull the element type out of an array VALUE.
  const nums = [10, 20, 30];
  expectType<Equal<(typeof nums)[number], number>>(
    "(typeof nums)[number] === number (element type)"
  );

  // Intrinsic string-manipulation types (uppercase/lowercase/capitalize/uncapitalize).
  expectType<Equal<Uppercase<"hello">, "HELLO">>('Uppercase<"hello"> === "HELLO"');
  expectType<Equal<Lowercase<"HELLO">, "hello">>('Lowercase<"HELLO"> === "hello"');
  expectType<Equal<Capitalize<"foo">, "Foo">>('Capitalize<"foo"> === "Foo"');
  expectType<Equal<Uncapitalize<"Foo">, "foo">>('Uncapitalize<"Foo"> === "foo"');

  // THE EXPERT PAYOFF — reimplement Exclude by hand (distributive conditional),
  // and NonNullable in its CLASSIC conditional form (modern lib uses T & {}).
  type ExcludeHand<T, U> = T extends U ? never : T;
  type NonNullableClassic<T> = T extends null | undefined ? never : T;
  expectType<Equal<ExcludeHand<"a" | "b" | "c", "b">, Exclude<"a" | "b" | "c", "b">>>(
    "hand-rolled ExcludeHand === built-in Exclude"
  );
  expectType<Equal<NonNullableClassic<string | null>, string>>(
    "classic NonNullable (conditional) === string"
  );

  // Erasure: keyof/typeof/indexed access produce NO runtime code. `point` is
  // untouched by all the type-level work above.
  check("typeof (typeof-derived object) === 'object' (erasure)", typeof point === "object");
  check("point.x survives all the type-level work unchanged", point.x === 3);
}

// ============================================================================
// Section E — Erasure & the unifying frame: every utility is mapped/conditional
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Erasure & the unifying frame: every utility is mapped/conditional");

  // The whole catalog is built from just THREE type-level primitives:
  //   1. mapped types      { [P in keyof T]?: T[P] }  -> Partial/Required/Readonly/Pick/Record
  //   2. conditional types T extends U ? X : Y (+infer) -> Exclude/Extract/ReturnType/Parameters
  //   3. recursion         -> Awaited (unwraps nested Promises)
  // keyof / typeof / indexed access are the glue that feed them. That is WHY this
  // bundle sits directly atop MAPPED_CONDITIONAL_TYPES.

  // ERASURE proof: build values of every transformed type; at runtime they are
  // all plain JS objects/numbers. TS annotations emit zero instructions.
  const partial: Partial<Todo> = { title: "x" };
  const ro: Readonly<Todo> = { title: "x", description: "y", done: false };
  const picked: Pick<Todo, "title"> = { title: "x" };
  const recorded: Record<"a" | "b", number> = { a: 1, b: 2 };
  const nested: Awaited<Promise<Promise<number>>> = 7;

  // Every compile-time-only construct collapses to an ordinary runtime value.
  check("Partial value typeof === 'object'", typeof partial === "object");
  check("Readonly value typeof === 'object'", typeof ro === "object");
  check("Pick value typeof === 'object'", typeof picked === "object");
  check("Record value typeof === 'object'", typeof recorded === "object");
  check("Awaited-resolved value typeof === 'number'", typeof nested === "number");

  // And the resolved Awaited value IS the unwrapped number, at both layers.
  expectType<Equal<typeof nested, number>>("typeof nested === number (Awaited resolved)");
  check("nested === 7", nested === 7);

  // Composability proof — utilities chain freely (each layer still mapped/conditional).
  type Editable = Partial<Pick<Todo, "title" | "done">>;
  expectType<Equal<Editable, { title?: string; done?: boolean }>>(
    "Partial<Pick<Todo,'title'|'done'>> composes"
  );
  const edit: Editable = { done: true };
  check("composed Partial<Pick<...>> value at .done === true", edit.done === true);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("utility_types.ts — Phase 2 bundle (TYPE-SYSTEM).");
  console.log("Every type-level claim below is pinned by expectType<Equal<...>> (a tsc");
  console.log("error if it fails) or @ts-expect-error (a tsc error if it does NOT fail).");
  console.log("Runtime check()s prove type ERASURE: the utilities emit zero code.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
