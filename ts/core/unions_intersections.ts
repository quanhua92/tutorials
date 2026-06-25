// unions_intersections.ts — Phase 2 bundle (Type-System: algebraic types).
//
// GOAL (one line): show, by printing every value AND type-checking every claim,
// how TypeScript's union (`|`, one-of) and intersection (`&`, all-of) types
// compose — culminating in discriminated unions, the exhaustive `never`-default
// switch (the compile-time completeness guarantee), and the distributive
// conditional over unions.
//
// This is the GROUND TRUTH for UNIONS_INTERSECTIONS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle sits here): VALUES_TYPES_COERCION pinned that TS's
// static types are ERASED at runtime — `interface`/`type`/annotations leave no
// trace, and the runtime `typeof` operator sees only JS primitives. This bundle
// climbs UP the type system: `|` and `&` are TS's ALGEBRAIC type formers
// (union = OR over value sets, intersection = AND over required members). They
// are compile-only constructs; their payoff is exactly what `tsc` ACCEPTS and
// REJECTS. We make that payoff falsifiable two ways:
//   (1) runtime `check()` — for what the types erase to (the surviving values).
//   (2) compile-time `expectType<Equal<…>>` + `@ts-expect-error` — each
//       directive suppresses a REAL `tsc` error, and an UNUSED directive is
//       itself a `tsc` error, so the type system's verdict is pinned in source.
// `tsc --noEmit` (the typecheck gate) is CANON: if it passes, every claim below
// is the actual compiler's verdict, not a paraphrase.
//
// Run:
//     pnpm exec tsx unions_intersections.ts   (or: just run unions_intersections)
//     pnpm exec tsc --noEmit -p tsconfig.json (the compile-time gate; must pass)

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts a runtime invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// --- compile-time test helpers (erased at runtime; the `tsc` gate is canon) ---
//
// Equal<A,B> is the standard higher-order type-equality test (cf. type-challenges):
// two function signatures `(<T>() => T extends A ? 1 : 2)` and
// `(<T>() => T extends B ? 1 : 2)` are structurally equal IFF A and B are the
// SAME type. expectType<M>(msg) only compiles when M extends `true` — so a FALSE
// type-equality claim is a COMPILE error (not a silent log line). At runtime the
// type arguments erase and it merely prints the [check] line.
type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends (<T>() => T extends B ? 1 : 2) ? true : false;
function expectType<T extends true>(msg: string): void {
  // T is read here so `noUnusedParameters` does not flag it; the real gate is the
  // call site — expectType<Equal<...>>(...) fails to COMPILE when the equality is
  // false. At runtime the type args erase and this just prints the [check] line.
  void (undefined as unknown as T);
  console.log(`[check] ${msg}: OK`);
}

// ============================================================================
// Section A — Union `|` (one-of) + literal unions + only-common-members
// ============================================================================
//
// A union `A | B` means "a value of this type is one of A's values OR one of B's
// values" — a union over VALUE SETS. The catch: without NARROWING you may only
// touch the members COMMON to every variant (the "intersection of properties"
// that the handbook's hats analogy explains).

function sectionA(): void {
  sectionBanner("A — Union `|` (one-of) + literal unions + only-common-members");

  type S = string | number;
  const a1: S = "hello";
  const a2: S = 42;

  console.log("type S = string | number;");
  console.log('  const a1: S = "hello";   // OK  — string is a member');
  console.log("  const a2: S = 42;        // OK  — number is a member");
  console.log("  const a3: S = true;      // ERR — boolean is NOT a member");

  // Rejected assignment: `true` is in neither member's value set. The helper
  // takes the value as an ARGUMENT (no unused local is left behind).
  function takesS(_s: S): void {}
  takesS("ok");
  // @ts-expect-error Argument of type 'boolean' is not assignable to parameter of type 'string | number'.
  takesS(true);

  // Only COMMON members survive on a union without narrowing. Both `string`
  // and `number` have `.toString()`, so it is safe; only `string` has
  // `.toUpperCase()`, so it is REJECTED on the whole union.
  function common(s: S): string {
    return s.toString();
  }
  // `s.toUpperCase()` is REJECTED on the union: 'number' has no such method.
  // (Function params are NOT narrowed by the caller, so `s` stays `string | number`.)
  function toUpperBlocked(s: S): void {
    // @ts-expect-error Property 'toUpperCase' does not exist on type 'string | number'. Property 'toUpperCase' does not exist on type 'number'.
    s.toUpperCase();
  }
  toUpperBlocked("hi"); // runtime: "hi".toUpperCase() -> "HI" (discarded; no error)

  console.log("  .toString() on S        // OK  — common to BOTH members");
  console.log(`    common(7) -> ${JSON.stringify(common(7))}`);
  console.log("  .toUpperCase() on S     // ERR — 'number' has no such method");

  // Literal unions: a closed set of string/number literals. Typos become
  // compile errors instead of silent runtime bugs.
  type Dir = "left" | "right" | "up" | "down";
  const d: Dir = "left";
  function takesDir(_d: Dir): void {}
  takesDir("right");
  // @ts-expect-error Argument of type '"sideways"' is not assignable to parameter of type '"left" | "right" | "up" | "down"'.
  takesDir("sideways");

  console.log('type Dir = "left" | "right" | "up" | "down";');
  console.log('  takesDir("right");     // OK');
  console.log('  takesDir("sideways");  // ERR — "sideways" is not a member');

  // `boolean` is itself a 2-member literal union: `true | false`.
  type Bool = true | false;
  const b: Bool = true;
  expectType<Equal<Bool, boolean>>("true | false === boolean (boolean IS a 2-member union)");

  console.log("type Bool = true | false; // boolean === true | false");

  check("string | number accepts a string", a1 === "hello");
  check("string | number accepts a number", a2 === 42);
  check(".toString() is common to both union members", common(123) === "123");
  check('literal union Dir accepts "left"', d === "left");
  check("boolean === true | false", b === true);
}

// ============================================================================
// Section B — Intersection `&` (all-of) + string & number === never
// ============================================================================
//
// An intersection `A & B` means "a value of this type satisfies ALL of A's
// requirements AND ALL of B's requirements" — required members ACCUMULATE.
// The payoff: intersecting two DISJOINT primitives (string & number) yields
// `never`, because no value is simultaneously a string and a number.

function sectionB(): void {
  sectionBanner("B — Intersection `&` (all-of) + string & number === never");

  type A = { x: number };
  type B = { y: number };
  type C = A & B; // requires BOTH x and y

  const c1: C = { x: 1, y: 2 };
  function takesC(_c: C): void {}
  takesC({ x: 1, y: 2 });
  // @ts-expect-error Property 'y' is missing in type '{ x: number; }' but required in type '{ y: number; }'.
  takesC({ x: 1 });

  console.log("type A = { x: number }; type B = { y: number }; type C = A & B;");
  console.log("  takesC({ x: 1, y: 2 }); // OK  — has BOTH x and y");
  console.log("  takesC({ x: 1 });       // ERR — 'y' is missing");
  console.log(`  const c1: C = {x:1,y:2} -> x=${c1.x}, y=${c1.y} (both present)`);

  check("A & B requires both x and y", c1.x === 1 && c1.y === 2);

  // THE PAYOFF: intersecting disjoint primitives yields `never`.
  type Disjoint = string & number;

  expectType<Equal<Disjoint, never>>("string & number === never (no value is both)");

  function takesNever(_n: Disjoint): void {}
  // @ts-expect-error Argument of type 'string' is not assignable to parameter of type 'never'.
  takesNever("hello");
  void takesNever; // mark used: its only call is error-suppressed above

  console.log("type Disjoint = string & number;");
  console.log("  Disjoint === never         // expectType<Equal<Disjoint, never>> == true");
  console.log('  takesNever("hello");       // ERR — "hello" not assignable to never');
}

// ============================================================================
// Section C — Discriminated unions (the tagged-variant idiom) + tag narrowing
// ============================================================================
//
// A DISCRIMINATED union is a union where every member carries a common property
// (the DISCRIMINANT, conventionally `kind`/`type`) typed as a UNIQUE literal.
// Checking the discriminant NARROWS the union to the matching member, unlocking
// that member's specific props. This is the direct analog of Rust's `enum`
// (a tagged union) — see ../rust/STRUCTS_ENUMS.md.

function sectionC(): void {
  sectionBanner("C — Discriminated unions (tagged variant) + tag narrowing");

  type Shape =
    | { kind: "circle"; r: number }
    | { kind: "square"; s: number };

  const circle: Shape = { kind: "circle", r: 5 };
  const square: Shape = { kind: "square", s: 3 };

  // WITHOUT narrowing: a member-specific prop is rejected (the 'square' member
  // has no `r`). Function params are NOT narrowed by the caller, so `s` stays
  // the full `Shape` union.
  function rBeforeNarrow(s: Shape): void {
    // @ts-expect-error Property 'r' does not exist on type 'Shape'. Property 'r' does not exist on type '{ kind: "square"; s: number; }'.
    s.r;
  }
  rBeforeNarrow(circle); // runtime: reads circle.r (5), discards; no error

  // WITH narrowing on the `kind` tag: member-specific props unlock.
  function radius(s: Shape): number {
    if (s.kind === "circle") {
      return s.r; // OK — narrowed to { kind: "circle"; r: number }
    }
    return 0;
  }

  console.log('type Shape = { kind: "circle"; r: number } | { kind: "square"; s: number };');
  console.log("  const circle: Shape = { kind: 'circle', r: 5 };");
  console.log("  const square: Shape = { kind: 'square', s: 3 };");
  console.log("  s.r (no narrowing)                // ERR — 'square' member has no 'r'");
  console.log("  if (s.kind === 'circle') s.r;     // OK  — tag narrows to circle");
  console.log(`  radius(circle) -> ${radius(circle)}`);
  console.log(`  radius(square) -> ${radius(square)}   (falls through to the else -> 0)`);

  // The discriminant is a RUNTIME value too: types erase, but the `kind` field
  // (a real string) survives — that is what makes the runtime `if`/`switch`
  // sound. (Cf. VALUES_TYPES_COERCION: the static type vanishes; the data stays.)
  const shapes: Shape[] = [circle, square];
  console.log("  runtime tags (the `kind` field survives type erasure):");
  for (const sh of shapes) {
    console.log(`    kind = ${JSON.stringify(sh.kind)}`);
  }

  check("circle.kind === 'circle'", circle.kind === "circle");
  check("radius(circle) === 5 (r unlocked after narrowing)", radius(circle) === 5);
  check("radius(square) === 0 (no r on square)", radius(square) === 0);
  check("discriminant 'kind' survives type erasure", circle.kind === "circle" && square.kind === "square");
}

// ============================================================================
// Section D — Exhaustive switch via the `never` default (completeness guarantee)
// ============================================================================
//
// When a switch covers every variant of a discriminated union, the `default`
// branch is UNREACHABLE — `s` has type `never` there. Assigning `s` to `never`
// compiles fine ONLY while every case is handled. Add a new variant and forget a
// case: the `never` assignment becomes a COMPILE error. That is the
// completeness guarantee — THE payoff of discriminated unions. (Rust enforces
// the same property on `match` at compile time; see ../rust/STRUCTS_ENUMS.md.)

function sectionD(): void {
  sectionBanner("D — Exhaustive switch via the `never` default (completeness guarantee)");

  type Shape =
    | { kind: "circle"; r: number }
    | { kind: "square"; s: number };

  // Every case handled -> the default is `never` -> the assignment compiles.
  function area(s: Shape): number {
    switch (s.kind) {
      case "circle":
        return Math.PI * s.r * s.r;
      case "square":
        return s.s * s.s;
      default: {
        // s is `never` here (exhaustive). Adding a variant makes THIS line error.
        const _: never = s;
        return _;
      }
    }
  }

  const circle: Shape = { kind: "circle", r: 5 };
  const square: Shape = { kind: "square", s: 3 };

  console.log("THE PAYOFF — exhaustive `never`-default switch:");
  console.log("  function area(s: Shape): number {");
  console.log("    switch (s.kind) {");
  console.log('      case "circle": return Math.PI * s.r * s.r;');
  console.log('      case "square": return s.s * s.s;');
  console.log("      default: { const _: never = s; return _; }  // s is `never` here");
  console.log("    }");
  console.log("  }");
  console.log(`  area(circle) -> ${area(circle).toFixed(4)}  (Math.PI * 25)`);
  console.log(`  area(square) -> ${area(square).toFixed(4)}  (9)`);

  check("area(circle) === Math.PI * 25", Math.abs(area(circle) - Math.PI * 25) < 1e-9);
  check("area(square) === 9", area(square) === 9);

  // Adding a variant WITHOUT updating the switch: the `never` assignment CATCHES
  // the missing case at compile time. The @ts-expect-error proves the error.
  type ShapeWithTriangle =
    | { kind: "circle"; r: number }
    | { kind: "square"; s: number }
    | { kind: "triangle"; base: number; height: number };

  function areaIncomplete(s: ShapeWithTriangle): number {
    switch (s.kind) {
      case "circle":
        return Math.PI * s.r * s.r;
      case "square":
        return s.s * s.s;
      default: {
        // @ts-expect-error Type '{ kind: "triangle"; base: number; height: number; }' is not assignable to type 'never'.
        const _: never = s;
        return _;
      }
    }
  }
  void areaIncomplete; // demo only (the @ts-expect-error above is the evidence)

  console.log("");
  console.log("Adding a 'triangle' variant WITHOUT a matching case:");
  console.log("  default: { const _: never = s; }   // COMPILE ERROR (caught!)");
  console.log('  -> "Type \'{ kind: \'triangle\'; ... }\' is not assignable to type \'never\'"');
  console.log("  This is the compile-time COMPLETENESS guarantee.");
}

// ============================================================================
// Section E — Distributive conditional types over unions
// ============================================================================
//
// A conditional type over a NAKEN type parameter DISTRIBUTES over a union input:
// it runs once per member and unions the results. Wrapping both sides of
// `extends` in `[...]` (a tuple) DISABLES distribution — the union is checked as
// one whole. (Full treatment: MAPPED_CONDITIONAL_TYPES.)

function sectionE(): void {
  sectionBanner("E — Distributive conditional types over unions");

  // Naked `T` on the left of `extends` => DISTRIBUTIVE over unions.
  type ToArray<T> = T extends any ? T[] : never;
  // Tuple-wrapped `[T]`/`[any]` => NON-distributive (union checked as one).
  type ToArrayNonDist<T> = [T] extends [any] ? T[] : never;

  type Dist = ToArray<string | number>; // string[] | number[]
  type NonDist = ToArrayNonDist<string | number>; // (string | number)[]

  expectType<Equal<Dist, string[] | number[]>>("ToArray<string|number> distributes -> string[] | number[]");
  expectType<Equal<NonDist, (string | number)[]>>("ToArrayNonDist<string|number> does NOT distribute -> (string|number)[]");

  console.log("type ToArray<T> = T extends any ? T[] : never;            // naked T -> distributes");
  console.log("type ToArrayNonDist<T> = [T] extends [any] ? T[] : never; // tuple-wrapped -> no distribution");
  console.log("");
  console.log("  ToArray<string | number>        === string[] | number[]   (distributed per member)");
  console.log("  ToArrayNonDist<string | number> === (string | number)[]   (union checked as one)");

  // The two are observably DIFFERENT at the type level: a MIXED array fits
  // `(string | number)[]` but NOT `string[] | number[]`.
  type Mixed = (string | number)[];
  type Separated = string[] | number[];

  const mixed: Mixed = ["a", 1]; // OK — mixed array fits the unified union
  function takesSeparated(_arr: Separated): void {}
  takesSeparated(["a", "b"]); // OK — all strings
  // @ts-expect-error Type '(string | number)[]' is not assignable to type 'string[] | number[]'. Type 'string' is not assignable to type 'number'.
  takesSeparated(["a", 1]);

  console.log("");
  console.log("  The two are DIFFERENT (observable at the type level):");
  console.log("    string[] | number[]  accepts ['a','b'] OR [1,2],  NOT ['a', 1]   (mixed)");
  console.log("    (string | number)[]  accepts ['a','b'], [1,2], AND ['a', 1]      (mixed OK)");

  check("(string|number)[] accepts a mixed array at runtime", mixed.length === 2 && mixed[0] === "a" && mixed[1] === 1);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("unions_intersections.ts — Phase 2 bundle (Type-System: algebraic types).");
  console.log("Every value below is computed by this file; the .md guide pastes it");
  console.log("verbatim. Every type claim is additionally pinned by the `tsc` gate:");
  console.log("`expectType<Equal<...>>` (compile error if false) and `@ts-expect-error`");
  console.log("(compile error if the suppressed error DISAPPEARS). Nothing is hand-waved.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
