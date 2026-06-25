// mapped_conditional_types.ts — Phase 2 bundle (type-system).
//
// GOAL (one line): show, by tsc-verified expectType<>/@ts-expect-error compile-time
// proofs AND a few check()'d runtime erasure facts, how Mapped types
// (`[K in keyof T]...`), Conditional types (`T extends U ? X : Y`), `infer`, and
// Template Literal types (`` `${A}${B}` ``) turn TypeScript's type system into a
// small PURE-FUNCTIONAL PROGRAMMING LANGUAGE evaluated entirely at compile time —
// and then ERASED, leaving plain objects/strings at runtime.
//
// This is the GROUND TRUTH for MAPPED_CONDITIONAL_TYPES.md. Every value below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// LINEAGE (why this bundle sits where it does): VALUES_TYPES_COERCION pinned that
// TS types are ERASED at runtime; STRUCTURAL_TYPING pinned assignability by shape;
// INTERFACES_VS_ALIASES showed the `type` alias is the ALGEBRAIC keyword (the only
// spelling for unions, intersections, tuples — AND for mapped/conditional types).
// This bundle is what that last point BUYS you: once you have a generic alias you
// can write a type that MAPS over another type's keys (`[K in keyof T]`), BRANCHES
// on a subtype test (`T extends U ? X : Y`), CAPTURES sub-structure (`infer`), and
// SPLICES strings (`` `${A}${B}` ``). That is exactly the machinery every Utility
// Type is built from (Partial/Pick/Omit/Record/ReturnType are all mapped or
// conditional types — see Section E), and it is the foundation of schema→type
// derivation (zod's `z.infer` in Phase 6).
//
// Cross-language pivot: this is TypeScript's "macro power". Rust gets compile-time
// codegen two ways — declarative `macro_rules!` (pattern→template) and procedural
// macros (functions over the syntax tree). TS has NO runtime macros; its analog is
// entirely at the TYPE LEVEL: a mapped type is a type-level `for` loop, a
// conditional type is a type-level `if`, `infer` is a type-level `let`/capture.
// The output is never executed — it is consulted by the assignability checker and
// then thrown away (🔗 ../rust/MACRO_RULES.md, ../rust/PROC_MACROS.md).
//
// EVIDENCE MODES (this bundle is almost entirely compile-time):
//   - check()      -> RUNTIME erasure facts (template-literal types erase to plain
//                     strings; readonly leaves no descriptor trace; mapped output
//                     is a plain object).
//   - expectType<> -> COMPILE-TIME type equality (tsc FAILS if the Equal<...> claim
//                     resolves to `false`), printed at runtime as a live [check].
//   - @ts-expect-error -> COMPILE-TIME "this WOULD error", each directive gating a
//                     REAL error (tsc fails the build if such a directive is ever
//                     UNUSED — i.e. if the line stopped erroring).
//
// Run:
//     pnpm exec tsx mapped_conditional_types.ts   (or: just run mapped_conditional_types)

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
// Equal<A, B> is the standard type-equality trick: it resolves to the literal
// `true` ONLY when A and B are the SAME type (not merely mutually assignable). It
// works by forcing TS to compare the conditional types structurally under a fresh
// type parameter T — the only way `(<T>() => T extends A ? 1 : 2)` and
// `(<T>() => T extends B ? 1 : 2)` are mutually assignable is when A and B are
// identical. This is the canonical community idiom for EXACT equality (used by
// type-fest, tsd, effect, io-ts) and it is what pins every type-level claim below.
type Equal<A, B> =
  (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;

// expectType is the compile-time analogue of check(): the call only typechecks
// when T extends true, AND it prints a [check] line at runtime so the
// verification sweep counts it. If the type claim is false, tsc fails the build
// before any code runs. Usage:
//   expectType<Equal<Inferred, Expected>>("Inferred === Expected");
//
// `true as T` is a sound downcast (T extends true, and true's only subtype is
// true itself); it is erased at runtime. The `_proof` binding references T in a
// value position so `noUnusedParameters` does not flag the type parameter.
function expectType<T extends true>(msg: string): void {
  const _proof: T = true as T;
  void _proof;
  console.log(`[check] ${msg}: OK`);
}

// ============================================================================
// Section A — Mapped types: a type-level `for` loop over a type's keys
// ============================================================================

// The headline form: iterate `keyof T` and REWRITE each property's VALUE type.
// `Stringify<T>` replaces every property's type with `string`, keeping the keys.
// This is literally how the built-in `Record`-like transforms work.
type Stringify<T> = { [K in keyof T]: string };

// Modifiers: the two property modifiers `readonly` and `?` can be ADDED (`+`,
// the default) or REMOVED (`-`) during the map. These four spellings reimplement
// four of the built-in Utility Types by hand (see Section E).
type Mutable<T> = { -readonly [K in keyof T]: T[K] }; // strip readonly (-> Mutable)
type Concrete<T> = { [K in keyof T]-?: T[K] }; // strip optional (-> Required)
type ReadonlyAll<T> = { +readonly [K in keyof T]: T[K] }; // add readonly (-> Readonly)
type OptionalAll<T> = { [K in keyof T]+?: T[K] }; // add optional (-> Partial)

function sectionA(): void {
  sectionBanner("A — Mapped types: a type-level `for` loop over a type's keys");

  // Stringify rewrites VALUE types but preserves KEYS. The Equal<> proof says the
  // result is IDENTICAL to { a: string; b: string } — a brand-new object type
  // derived mechanically from the input.
  type Src = { a: number; b: boolean };
  type Str = Stringify<Src>;
  console.log("type Stringify<T> = { [K in keyof T]: string }");
  console.log("  Stringify<{ a: number; b: boolean }>");
  console.log("    -> { a: string; b: string }   (keys preserved, value type rewritten)");
  expectType<Equal<Str, { a: string; b: string }>>(
    "Stringify<{a:number;b:boolean}> === {a:string;b:string}",
  );
  // The NEGATIVE proof (gated by @ts-expect-error): the result is NOT the input.
  // A string-typed property is not assignable to a number-typed slot.
  // @ts-expect-error Type 'string' is not assignable to type 'number'.
  const wrongValue: { a: number } = {} as Str;
  void wrongValue;
  console.log("  const wrongValue: { a: number } = (Stringify result)  -> ERROR (string not number)");

  // --- modifier: strip readonly ------------------------------------------------
  // `Mutable<T>` peels `readonly` off every key. At runtime, readonly is GONE
  // entirely (it is a compile-time modifier that emits no code and sets no
  // `writable:false` on the property descriptor). The descriptor check below is
  // the runtime half of that proof; the assignment to `unlocked.id` is the
  // compile-time half (it typechecks ONLY because readonly was stripped).
  type Locked = { readonly id: string };
  type Unlocked = Mutable<Locked>;
  console.log("");
  console.log("type Mutable<T> = { -readonly [K in keyof T]: T[K] }");
  console.log("  Mutable<{ readonly id: string }>");
  console.log("    -> { id: string }   (readonly STRIPPED)");
  expectType<Equal<Unlocked, { id: string }>>("Mutable<{readonly id}> === {id} (readonly removed)");
  // This next line would error on the readonly original; it compiles here.
  const unlocked: Unlocked = { id: "x" };
  unlocked.id = "y"; // OK: readonly was stripped
  // Contrast — the SAME assignment on a readonly-typed value is a real error:
  const locked: Locked = { id: "x" };
  // @ts-expect-error Cannot assign to 'id' because it is a read-only property.
  locked.id = "z";
  void locked;
  console.log("  unlocked.id = 'y'  -> OK (Mutable stripped readonly)");
  console.log("  locked.id = 'z'    -> ERROR (@ts-expect-error gate: readonly blocks it)");
  // RUNTIME half: readonly leaves NO trace. The descriptor is writable:true.
  const desc = Object.getOwnPropertyDescriptor(unlocked, "id");
  check(
    "readonly leaves NO runtime trace: descriptor.writable !== false (it's a compile-time modifier)",
    desc?.writable !== false,
  );

  // --- modifier: strip optional (`-?`) ----------------------------------------
  // `Concrete<T>` removes optionality. The Equal<> proof: `{ id: string; name: string }`
  // (no `?`), even though the source `name` was optional.
  type MaybeUser = { id: string; name?: string };
  type RequiredUser = Concrete<MaybeUser>;
  console.log("");
  console.log("type Concrete<T> = { [K in keyof T]-?: T[K] }");
  console.log("  Concrete<{ id: string; name?: string }>");
  console.log("    -> { id: string; name: string }   (optionality STRIPPED)");
  expectType<Equal<RequiredUser, { id: string; name: string }>>(
    "Concrete<{id;name?}> === {id;name} (optional removed)",
  );
  // The inverse proof: the result is NOT optional. A value WITHOUT `name` no
  // longer satisfies the concrete type — a real error the directive gates.
  // @ts-expect-error Property 'name' is missing in type '{ id: string; }' but required in type '{ id: string; name: string; }'.
  const missingName: RequiredUser = { id: "1" };
  void missingName;
  console.log("  const missingName: RequiredUser = { id: '1' }  -> ERROR (name now required)");

  // --- modifiers: ADD readonly / ADD optional (`+readonly`, `+?`) -------------
  // The `+` prefix is the default and usually omitted; spelling it makes the
  // symmetry with `-` explicit. These reimplement `Readonly` and `Partial`.
  type RO = ReadonlyAll<{ x: number }>;
  type Opt = OptionalAll<{ x: number }>;
  expectType<Equal<RO, { readonly x: number }>>("ReadonlyAll<{x}> === {readonly x}");
  expectType<Equal<Opt, { x?: number }>>("OptionalAll<{x}> === {x?}");
  console.log("");
  console.log("type ReadonlyAll<T> = { +readonly [K in keyof T]: T[K] }  -> adds readonly");
  console.log("type OptionalAll<T> = { [K in keyof T]+?: T[K] }          -> adds optional");
  console.log("  (+ is the default; - is the noteworthy direction.)");
}

// ============================================================================
// Section B — Conditional types: a type-level `if`, + distributivity
// ============================================================================

// The form mirrors a JS ternary: `T extends U ? TrueType : FalseType`. When the
// check type (left of `extends`) is ASSIGNABLE to the target (right), the true
// branch wins; otherwise the false branch. The power comes from using it inside a
// GENERIC — TS defers the branch until T is known.
type IsString<T> = T extends string ? true : false;

// Distributive vs non-distributive: when the CHECK type is a NAKED generic
// parameter (bare `T`, not `[T]`) and T is a UNION, the conditional runs ONCE PER
// union member and unions the results. Wrapping both sides in `[...]` (a 1-tuple)
// DISABLES distribution — the union is tested whole.
type ToArray<T> = T extends unknown ? T[] : never; // NAKED T -> distributes
type ToArrayNonDist<T> = [T] extends [unknown] ? T[] : never; // [T] -> no distribution

function sectionB(): void {
  sectionBanner("B — Conditional types: a type-level `if`, + distributivity");

  // IsString: a deferred branch. Given a concrete literal it resolves to a
  // literal boolean TYPE (true/false), not a runtime value. Both arms pinned.
  console.log("type IsString<T> = T extends string ? true : false");
  console.log('  IsString<"x">  -> true');
  console.log("  IsString<42>   -> false");
  expectType<Equal<IsString<"x">, true>>('IsString<"x"> === true');
  expectType<Equal<IsString<42>, false>>("IsString<42> === false");

  // DISTRIBUTIVITY — the headline trap. `ToArray<string | number>` does NOT yield
  // `(string | number)[]`; it distributes into `ToArray<string> | ToArray<number>`
  // = `string[] | number[]` (an array of ALL strings OR an array of ALL numbers).
  // That is a STRICTER, more useful type: it forbids a mixed array.
  type Dist = ToArray<string | number>;
  console.log("");
  console.log("type ToArray<T> = T extends unknown ? T[] : never   // NAKED T -> distributes");
  console.log("  ToArray<string | number>");
  console.log("    -> string[] | number[]   (NOT (string|number)[])");
  expectType<Equal<Dist, string[] | number[]>>(
    "ToArray<string|number> distributes to string[] | number[]",
  );
  // Disable distribution with a 1-tuple: `[T] extends [unknown]`. Now the whole
  // union is tested at once, yielding the flat `(string | number)[]`.
  type NonDist = ToArrayNonDist<string | number>;
  console.log("");
  console.log("type ToArrayNonDist<T> = [T] extends [unknown] ? T[] : never   // [T] -> no distribution");
  console.log("  ToArrayNonDist<string | number>");
  console.log("    -> (string | number)[]   (tested whole, NOT distributed)");
  expectType<Equal<NonDist, (string | number)[]>>(
    "ToArrayNonDist<string|number> === (string|number)[] (distribution disabled)",
  );

  // RUNTIME-visible consequence of the difference: `(string|number)[]` accepts a
  // mixed array; `string[] | number[]` does NOT (it must be all-one-or-the-other),
  // so assigning a genuinely mixed array to it is a real error the directive gates.
  const mixed: (string | number)[] = [1, "a", 2];
  // @ts-expect-error Type '(string | number)[]' is not assignable to type 'string[] | number[]'.
  const asEither: string[] | number[] = mixed;
  void asEither;
  console.log("  const mixed: (string|number)[] = [1,'a',2];");
  console.log("  const asEither: string[]|number[] = mixed  -> ERROR (mixed array is neither all-string nor all-number)");

  // DISTRIBUTIVITY IS USUALLY WHAT YOU WANT. The classic application is FILTERING
  // a union: `Exclude<U, M>` is literally `U extends M ? never : U` — distribute,
  // drop the matching member (=> never, which vanishes from a union), keep the
  // rest. Pinned by hand here:
  type MyExclude<U, M> = U extends M ? never : U;
  type Kept = MyExclude<"a" | "b" | "c", "b">;
  expectType<Equal<Kept, "a" | "c">>('MyExclude<"a"|"b"|"c", "b"> === "a"|"c" (distributive filter)');
  console.log("");
  console.log('type MyExclude<U, M> = U extends M ? never : U   // = the built-in Exclude');
  console.log('  MyExclude<"a"|"b"|"c", "b">  -> "a" | "c"   (the "b" arm became never and vanished)');
}

// ============================================================================
// Section C — `infer`: a type-level capture (reimplement ReturnType)
// ============================================================================

// The payoff of conditional types: in the TRUE branch you can introduce a NEW
// generic variable with `infer` and BIND it to a piece of the matched structure.
// `GetReturnType` matches "any function" and captures its return type as `R`.
//
// NOTE: the official handbook spelling is `(...args: never[]) => infer R` — NOT
// `any[]`. `never` is the bottom type (assignable to everything), so a function
// typed with `never[]` params accepts ANY argument list, while avoiding `any`
// entirely (this bundle's hard rule). This IS the implementation of the built-in
// `ReturnType<T>` — the Equal<> proof below shows the two are identical.
type GetReturnType<T> = T extends (...args: never[]) => infer R ? R : never;

// `infer` also works inside tuple/array structure: match `(infer E)[]` to peel the
// element type out of an array type.
type ElementOf<T> = T extends (infer E)[] ? E : never;

// And inside a generic wrapper: unwrap a Promise (a minimal `Awaited`).
type Unwrap<T> = T extends Promise<infer U> ? U : T;

// Declare an overloaded function (three call signatures) for the overload-infer
// caveat demo below.
declare function overloaded(x: string): number;
declare function overloaded(x: number): string;
declare function overloaded(x: string | number): string | number;

function sectionC(): void {
  sectionBanner("C — `infer`: a type-level capture (reimplement ReturnType)");

  // GetReturnType: capture a function's return type. The hand-rolled version is
  // IDENTICAL to the built-in ReturnType (Equal<> proof).
  const fn = (): number => 42;
  type R1 = GetReturnType<typeof fn>;
  type R1Builtin = ReturnType<typeof fn>;
  console.log("type GetReturnType<T> = T extends (...args: never[]) => infer R ? R : never");
  console.log("  GetReturnType<() => number>  -> number");
  expectType<Equal<R1, number>>("GetReturnType<()=>number> === number");
  expectType<Equal<R1, R1Builtin>>("hand-rolled GetReturnType === built-in ReturnType (identical)");

  // `infer` can also fail to match: a non-function falls to the false branch
  // (`never` here). This is the conditional acting as a type-level guard.
  type R2 = GetReturnType<number>;
  expectType<Equal<R2, never>>("GetReturnType<number> === never (number is not a function -> false branch)");
  console.log("  GetReturnType<number>  -> never   (false branch: number is not callable)");

  // ElementOf: infer inside an array/tuple. Bind `E` to the element, return it.
  type E1 = ElementOf<number[]>;
  type E2 = ElementOf<string>;
  console.log("");
  console.log("type ElementOf<T> = T extends (infer E)[] ? E : never");
  console.log("  ElementOf<number[]>  -> number");
  console.log("  ElementOf<string>    -> never   (string is not an array)");
  expectType<Equal<E1, number>>("ElementOf<number[]> === number");
  expectType<Equal<E2, never>>("ElementOf<string> === never");

  // Unwrap: infer inside a generic wrapper (Promise). A minimal Awaited.
  type U1 = Unwrap<Promise<boolean>>;
  type U2 = Unwrap<string>;
  console.log("");
  console.log("type Unwrap<T> = T extends Promise<infer U> ? U : T");
  console.log("  Unwrap<Promise<boolean>>  -> boolean");
  console.log("  Unwrap<string>            -> string   (not a Promise -> passes through)");
  expectType<Equal<U1, boolean>>("Unwrap<Promise<boolean>> === boolean");
  expectType<Equal<U2, string>>("Unwrap<string> === string (passthrough)");

  // EXPERT CAVEAT (from the handbook): when the source type has MULTIPLE call
  // signatures (an overloaded function), `infer` resolves against the LAST
  // signature only — "presumably the most permissive catch-all case". Overload
  // resolution based on argument types is NOT performed. The pinned result:
  type OverRet = GetReturnType<typeof overloaded>;
  console.log("");
  console.log("declare function overloaded(x: string): number;");
  console.log("declare function overloaded(x: number): string;");
  console.log("declare function overloaded(x: string|number): string|number;  // LAST signature");
  console.log("  GetReturnType<typeof overloaded>  -> string | number   (picks the LAST signature)");
  expectType<Equal<OverRet, string | number>>(
    "infer on an overloaded fn picks the LAST signature -> string|number",
  );

  // RUNTIME erasure: `GetReturnType` and friends leave NO runtime trace. The
  // captured `R` was a compile-time phantom; `fn` is a plain JS arrow function.
  check('typeof fn === "function" (ReturnType/infer leave no runtime trace)', typeof fn === "function");
  check("fn() === 42 (the captured return type was compile-time only)", fn() === 42);
}

// ============================================================================
// Section D — Template literal types + intrinsics + key remapping via `as`
// ============================================================================

// Template literal types splice literal-string types with the SAME syntax as JS
// template strings, but in TYPE position. A union in a slot CROSS-MULTIPLIES.
type Greeting = `hello ${string}`;

// The four INTRINSIC string-manipulation types (built into the compiler — not in
// any .d.ts — and NOT locale-aware; they call the JS runtime string methods).
//   Uppercase<S> / Lowercase<S>           -> s.toUpperCase() / toLowerCase()
//   Capitalize<S> / Uncapitalize<S>       -> s.charAt(0).toUpperCase()+s.slice(1)
// (Source: the TS handbook quotes the compiler's own `applyStringMapping`.)

// KEY REMAPPING via `as` (TS 4.1+): inside a mapped type the key can be RENAMED
// with `as NewKey`, usually built from the old key via a template literal + an
// intrinsic. Producing `never` for a key DROPS it — a type-level filter.
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};
type RemoveKind<T> = { [K in keyof T as Exclude<K, "kind">]: T[K] };

function sectionD(): void {
  sectionBanner("D — Template literal types + intrinsics + key remapping via `as`");

  // A template literal type produces a NEW string-literal type by concatenation.
  // `Greeting` is a PATTERN type: it matches any string starting with "hello ".
  type World = "world";
  type Hello = `hello ${World}`;
  expectType<Equal<Hello, "hello world">>('`hello ${"world"}` === "hello world"');
  // A pattern type narrows via `extends`: test whether a candidate literal matches.
  type MatchesGreeting<S extends string> = S extends Greeting ? true : false;
  console.log("type Greeting = `hello ${string}`   (a PATTERN type)");
  console.log('type Hello = `hello ${"world"}`     -> "hello world"');
  expectType<Equal<MatchesGreeting<"hello world">, true>>('..."hello world" matches `hello ${string}`');
  expectType<Equal<MatchesGreeting<"hi world">, false>>('..."hi world" does NOT match the pattern');

  // A union in a slot CROSS-MULTIPLIES into the cartesian product of strings.
  type Lang = "en" | "ja";
  type Locale = `${Lang}_id`;
  console.log("");
  console.log('type Lang = "en" | "ja"');
  console.log("type Locale = `${Lang}_id`   // union cross-multiplies");
  console.log('  -> "en_id" | "ja_id"');
  expectType<Equal<Locale, "en_id" | "ja_id">>('`${"en"|"ja"}_id` === "en_id"|"ja_id"');

  // The four intrinsics — each is the type-level twin of a JS string method.
  console.log("");
  console.log("Intrinsic string types (compiler-built, NOT locale-aware):");
  expectType<Equal<Uppercase<"hello">, "HELLO">>('Uppercase<"hello"> === "HELLO"');
  expectType<Equal<Lowercase<"HELLO">, "hello">>('Lowercase<"HELLO"> === "hello"');
  expectType<Equal<Capitalize<"hello">, "Hello">>('Capitalize<"hello"> === "Hello"');
  expectType<Equal<Uncapitalize<"Hello">, "hello">>('Uncapitalize<"Hello"> === "hello"');

  // KEY REMAPPING via `as` — rename every key `K` to `get${Capitalize<K>}`. This
  // is how a schema can derive a "getters" or "event-name" type mechanically.
  type LazyPerson = Getters<{ name: string; age: number }>;
  console.log("");
  console.log("type Getters<T> = { [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K] }");
  console.log("  Getters<{ name: string; age: number }>");
  console.log('    -> { getName: () => string; getAge: () => number }   (keys RENAMED)');
  expectType<Equal<keyof LazyPerson, "getName" | "getAge">>(
    "Getters<{name;age}> renames keys to getName|getAge",
  );
  // The value type travels with the rename: getName returns string, getAge number.
  expectType<Equal<GetReturnType<LazyPerson["getName"]>, string>>(
    "LazyPerson.getName () -> string (value type travels with the renamed key)",
  );
  expectType<Equal<GetReturnType<LazyPerson["getAge"]>, number>>(
    "LazyPerson.getAge () -> number",
  );
  // The `string & K` intersection is required: `keyof T` is `string|number|symbol`,
  // but `Capitalize` needs a string. The intersection narrows to the string part.

  // FILTERING via `as never` (or `Exclude`): a key whose `as` clause yields
  // `never` is DROPPED from the result. This is the type-level "delete a field".
  type Kindless = RemoveKind<{ kind: "circle"; radius: number }>;
  console.log("");
  console.log('type RemoveKind<T> = { [K in keyof T as Exclude<K, "kind">]: T[K] }');
  console.log('  RemoveKind<{ kind: "circle"; radius: number }>');
  console.log('    -> { radius: number }   ("kind" DROPPED via Exclude -> never)');
  expectType<Equal<Kindless, { radius: number }>>('RemoveKind drops the "kind" key -> {radius:number}');

  // RUNTIME erasure (the headline fact for template literals): a value typed by a
  // template-literal type is a PLAIN STRING at runtime. The fancy type is gone.
  const ev: `${string}Changed` = "valueChanged";
  check('typeof ev === "string" (template-literal type ERASES to a plain string)', typeof ev === "string");
  check('ev === "valueChanged" (the literal value survives; only the TYPE vanished)', ev === "valueChanged");
  console.log("");
  console.log('const ev: `${string}Changed` = "valueChanged";');
  console.log('  typeof ev -> "string"   (template-literal type erased at runtime)');
}

// ============================================================================
// Section E — Putting it together: reimplement the Utility Types by hand
// ============================================================================

// Every mapped/conditional mechanism above is exactly how TS's own Utility Types
// are defined in lib.d.ts. Reimplementing four of them by hand is the proof that
// there is no magic — and the cross-language framing (this is TS's "macro power").
type MyPartial<T> = { [K in keyof T]+?: T[K] };
type MyRequired<T> = { [K in keyof T]-?: T[K] };
type MyReadonly<T> = { readonly [K in keyof T]: T[K] };
type MyPick<T, K extends keyof T> = { [P in K]: T[P] };
type MyRecord<K extends PropertyKey, V> = { [P in K]: V };
type MyReturnType<T extends (...args: never[]) => unknown> = T extends (...args: never[]) => infer R ? R : never;

function sectionE(): void {
  sectionBanner("E — Putting it together: reimplement the Utility Types by hand");

  type User = { id: number; name: string; email: string };

  // MyPartial = Partial. Adding `?` to every key.
  type PUser = MyPartial<User>;
  console.log("type MyPartial<T> = { [K in keyof T]+?: T[K] }");
  console.log("  MyPartial<{ id; name; email }>");
  console.log("    -> { id?: number; name?: string; email?: string }   (=== built-in Partial)");
  expectType<Equal<PUser, Partial<User>>>("MyPartial<User> === Partial<User>");
  expectType<Equal<PUser, { id?: number; name?: string; email?: string }>>(
    "MyPartial result is the all-optional shape",
  );

  // MyRequired = Required. Stripping `?` (`-?`).
  type RUser = MyRequired<{ id: number; name?: string }>;
  console.log("");
  console.log("type MyRequired<T> = { [K in keyof T]-?: T[K] }");
  console.log("  MyRequired<{ id: number; name?: string }>");
  console.log("    -> { id: number; name: string }   (=== built-in Required)");
  expectType<Equal<RUser, Required<{ id: number; name?: string }>>>(
    "MyRequired<{id;name?}> === Required<{id;name?}>",
  );

  // MyReadonly = Readonly. Adding `readonly`.
  type ROUser = MyReadonly<User>;
  console.log("");
  console.log("type MyReadonly<T> = { readonly [K in keyof T]: T[K] }");
  console.log("  MyReadonly<User>  -> { readonly id; readonly name; readonly email }   (=== Readonly)");
  expectType<Equal<ROUser, Readonly<User>>>("MyReadonly<User> === Readonly<User>");

  // MyPick = Pick. Iterate a SUBSET of keys (`K extends keyof T`, then `[P in K]`).
  type PickUser = MyPick<User, "id" | "name">;
  console.log("");
  console.log("type MyPick<T, K extends keyof T> = { [P in K]: T[P] }");
  console.log('  MyPick<User, "id" | "name">  -> { id: number; name: string }   (=== Pick)');
  expectType<Equal<PickUser, Pick<User, "id" | "name">>>('MyPick<User,"id"|"name"> === Pick<User,"id"|"name">');
  expectType<Equal<PickUser, { id: number; name: string }>>("MyPick result is the projected subset");

  // MyRecord = Record. Build an object type from a key union + a value type.
  type RecUser = MyRecord<"a" | "b", number>;
  console.log("");
  console.log('type MyRecord<K extends PropertyKey, V> = { [P in K]: V }');
  console.log('  MyRecord<"a"|"b", number>  -> { a: number; b: number }   (=== Record)');
  expectType<Equal<RecUser, Record<"a" | "b", number>>>('MyRecord<"a"|"b",number> === Record<"a"|"b",number>');

  // MyReturnType = ReturnType. The infer payoff from Section C, now as a Utility.
  type RtUser = MyReturnType<() => User>;
  console.log("");
  console.log("type MyReturnType<T> = T extends (...args: never[]) => infer R ? R : never");
  console.log("  MyReturnType<() => User>  -> User   (=== ReturnType)");
  expectType<Equal<RtUser, ReturnType<() => User>>>("MyReturnType<()=>User> === ReturnType<()=>User>");
  expectType<Equal<RtUser, User>>("MyReturnType<()=>User> === User");

  // THE CROSS-LANGUAGE FRAMING. All of the above is COMPILE-TIME codegen: a
  // mapped type is a type-level `for`, a conditional is a type-level `if`, `infer`
  // is a type-level capture. Rust achieves the same "derive code from a schema"
  // goal with two different mechanisms; TS has neither runtime macros NOR a
  // syntax-tree API — its entire codegen power lives in the type checker and is
  // ERASED before execution.
  console.log("");
  console.log("CROSS-LANGUAGE: this is TS's compile-time codegen.");
  console.log("  mapped   ~ a type-level `for` loop over keys");
  console.log("  conditional ~ a type-level `if` (with union distribution)");
  console.log("  infer    ~ a type-level `let`/capture");
  console.log("  Rust analog: ../rust/MACRO_RULES.md (declarative) + ../rust/PROC_MACROS.md (procedural).");

  // FINAL ERASURE PROOF: a value typed by a hand-rolled mapped type is a plain
  // object at runtime — the entire derivation left zero trace.
  const partialUser: MyPartial<User> = { id: 1 };
  const keys = Object.keys(partialUser).sort();
  check(
    "MyPartial<User> value is a plain object: keys === [\"id\"] (derivation erased)",
    JSON.stringify(keys) === '["id"]',
  );
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("mapped_conditional_types.ts — Phase 2 bundle (type-system).");
  console.log("Mapped + conditional + infer + template-literal types: TS's");
  console.log("type-level PROGRAMMING LANGUAGE — computed at compile time, then ERASED.");
  console.log("");
  console.log("Reminder (pinned by VALUES_TYPES_COERCION): TS types are ERASED at runtime.");
  console.log("So every claim below is proven by tsc (expectType<>/@ts-expect-error); the");
  console.log("few runtime check()s assert ERASURE (template-literal -> plain string, etc.).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
