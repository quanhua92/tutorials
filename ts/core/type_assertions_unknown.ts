// type_assertions_unknown.ts — Phase 2 bundle (Type System & Generics).
//
// GOAL (one line): show, by check()'d runtime behavior AND tsc-verified
// expectType<>/@ts-expect-error compile-time proofs, the four ways to relate a
// value to a type the compiler can't (or won't) infer — `as` (a forced,
// UNCHECKED assertion that can LIE), `any` (the type-system OFF switch), the
// `unknown` TOP type (safe because you MUST narrow), and `satisfies`/`as const`
// (the modern, conformance-preserving choices) — plus `never`, the BOTTOM type.
//
// This is the GROUND TRUTH for TYPE_ASSERTIONS_UNKNOWN.md. Every value below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// LINEAGE (why this bundle sits here): STRUCTURAL_TYPING showed HOW the compiler
// decides "is X assignable to Y" (by shape). This bundle is about the FOUR
// ESCAPE HATCHES you reach for when the compiler CANNOT or WILL NOT infer the
// type you know to be true — and their wildly different SAFETY PROFILES:
//   - `as`         TELLS the compiler. Emits NO runtime check. Can LIE.
//   - `any`        opts OUT of ALL checking. Silences errors AND defeats safety.
//   - `unknown`    the TOP type. Accepts any value, but you MUST narrow to use it.
//   - `satisfies`  CHECKS conformance, PRESERVES the narrow type (TS 4.9).
//   - `as const`   asserts the narrowest literal/readonly type.
//   - `never`      the BOTTOM type (empty set); the exhaustiveness tool.
// TypeScript types are ERASED at runtime (tsx/esbuild/tsc strip them), so `as`
// and `satisfies` emit NO code — only `typeof`/`instanceof`/guards run. That
// erasure is WHY an assertion can lie: it changes the compile-time view but
// leaves the runtime value untouched. The expert rule this bundle pins:
//   prefer `unknown` + narrowing over `any`;  prefer `satisfies` over `as`;
//   prefer a type PREDICATE (`x is T`) over `as T` (🔗 TYPE_NARROWING).
//
// EVIDENCE MODES (this bundle is compile-time focused): runtime claims are
// asserted via `check()`; type-level claims are asserted via `expectType<...>`
// (which only compiles when the type argument is `true`, and prints a `[check]`
// line at runtime) and via `// @ts-expect-error` on lines that SHOULD error
// (tsc fails the build if such a directive is UNUSED — i.e. if the line did not
// actually error). The TYPECHECK IS CANON; both modes print `[check]` lines.
//
// Run:
//     pnpm exec tsx type_assertions_unknown.ts   (or: just run type_assertions_unknown)

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
  (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;

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

// readCachePort narrows the Port union (number | { host; port }) to its port
// number. Used in §D to read cfgAnn.cache.port — the annotation widened
// cfgAnn.cache to Port, so direct .port access is a compile error without
// narrowing. This IS the narrowing the bundle recommends over `as`.
function readCachePort(c: { db: number | { host: string; port: number }; cache: number | { host: string; port: number } }): unknown {
  return typeof c.cache === "number" ? c.cache : c.cache.port;
}

// Result is the discriminated union for §E's exhaustive-switch demo. The `ok`
// literal is the discriminant; after both cases return, the default branch sees
// the value as `never` — the basis of the exhaustiveness check.
type Result = { ok: true; value: number } | { ok: false; error: string };

// ============================================================================
// Section A — `as`: a forced assertion, UNCHECKED at runtime (it can LIE)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — `as`: a forced assertion, UNCHECKED at runtime (it can LIE)");

  // `expr as T` TELLS the compiler "trust me, this is T". It emits NO runtime
  // check (it is erased like every other type construct), so the runtime value
  // is left EXACTLY as it was. When you are right, `as` is a convenient narrowing
  // tool; when you are wrong, the compiler is silenced and the lie propagates.

  // (1) The LEGITIMATE use: narrow a union to the arm you have checked.
  const maybe: string | number = 42;
  const asNum = maybe as number; // OK: number overlaps with string|number
  console.log("const maybe: string | number = 42;");
  console.log("const asNum = maybe as number;            -> OK (number overlaps string|number)");
  console.log(`  asNum = ${asNum}   (typeof ${typeof asNum})`);
  expectType<Equal<typeof asNum, number>>("typeof asNum === number (union narrowed by `as`)");
  check("asNum === 42 at runtime (value unchanged by the assertion)", asNum === 42);

  // (2) THE OVERLAP RULE (handbook "Type Assertions"): `as` is allowed ONLY
  // between types that OVERLAP (one is assignable to the other in some
  // direction). Asserting between DISJOOT types is a compile error — TS suspects
  // you are wrong. number and string are disjoint primitives, so this errors:
  console.log("");
  console.log("THE OVERLAP RULE: `as` is allowed only between overlapping types.");
  console.log("  123 as string   -> ERROR (number and string do not overlap)");
  // @ts-expect-error Conversion of type 'number' to type 'string' may be a mistake — neither overlaps.
  const disjoint = 123 as string;
  void disjoint;

  // (3) THE DOUBLE-ASSERTION ESCAPE HATCH: route through `unknown` (which
  // overlaps EVERYTHING) to force any assertion through. This is how `as`
  // defeats the overlap rule — and it is a loaded footgun: it compiles even
  // when the assertion is a flat lie.
  const forced = 123 as unknown as string; // compiles (unknown overlaps all)
  console.log("  123 as unknown as string -> COMPILES (the escape hatch; loaded footgun)");
  console.log(`  forced = ${JSON.stringify(forced)}   (typeof ${typeof forced} — runtime value is a NUMBER)`);
  expectType<Equal<typeof forced, string>>("TS believes forced === string (the escape hatch lied)");
  check('typeof forced === "number" at runtime (escape hatch does NOT change the value)', typeof forced === "number");

  // (4) THE LIE — a realistic function boundary. `as` changes the COMPILE-TIME
  // type but emits NO runtime check, so the runtime value passes through
  // unchanged. Here a function promises `number`, the caller passes a string
  // (e.g. from an untyped source), and `as number` inside silences the compiler.
  // The result: TS is certain it is a number; V8 is holding a string.
  const liedTo = asNumber("hello");
  console.log("");
  console.log("THE LIE (a realistic function boundary):");
  console.log("  function asNumber(x: unknown): number { return x as number; }");
  console.log('  const liedTo = asNumber("hello");');
  console.log("    TS type of liedTo : number   (the compiler TRUSTS the assertion)");
  console.log(`    runtime typeof     : ${typeof liedTo}   (THE LIE — runtime value unchanged)`);
  expectType<Equal<typeof liedTo, number>>("TS believes liedTo === number (compile-time view)");
  check('typeof liedTo === "string" at runtime (the assertion LIED — value untouched)', typeof liedTo === "string");

  // The double-evidence payoff: the SAME variable `liedTo` is `number` to tsc
  // (expectType above) and `"string"` to typeof (check above). That gap IS the
  // danger of `as`: it is a promise the compiler cannot verify and the runtime
  // cannot enforce.
}

// asNumber is the demonstration of an assertion that LIES. It accepts unknown
// (the safe top type) and returns number via a bare `as` — UNCHECKED at runtime.
// Called with a string, it returns type number but the value is the string.
function asNumber(x: unknown): number {
  return x as number; // compiles (unknown overlaps number); UNCHECKED at runtime
}

// ============================================================================
// Section B — `any`: opts out of ALL checking (the danger)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — any: opts out of ALL checking (the danger)");

  // `any` is the type-system OFF switch. A value typed `any` is assignable TO
  // and FROM every type, with NO checks on either side. The compiler treats it
  // as "I promise this is fine" — and silently drops all safety, including
  // autocompletion. The result is code that COMPILES but THROWS at runtime.
  //
  // NOTE: this section deliberately writes the `any` token to SHOW the danger.
  // The rest of the bundle (and the house rule) forbids `any`; `unknown` (§C)
  // is the safe replacement.

  // (1) any silences the compiler: nonsense operations COMPILE without error.
  let danger: any = 1; // a number, typed any
  let anyThrew = false;
  let anyErrorName = "";
  try {
    // .toUpperCase() on a number makes no sense — but `any` suppresses the
    // error, so this COMPILES. At runtime the number has no such method and
    // V8 throws a TypeError.
    danger.toUpperCase();
  } catch (e) {
    anyThrew = true;
    anyErrorName = e instanceof Error ? e.name : "Unknown";
  }
  console.log("let danger: any = 1;                       // a number, typed any (the off switch)");
  console.log("danger.toUpperCase();                       // COMPILES (any allows it), then:");
  console.log(`  runtime -> threw ${anyErrorName}   (number has no .toUpperCase)`);
  check("any: danger.toUpperCase() threw at runtime (compiler was silenced)", anyThrew);
  check('any throw is a TypeError', anyErrorName === "TypeError");
  check('runtime typeof danger === "number" (the real value underneath any)', typeof danger === "number");

  // (2) any defeats BOTH directions of checking. Assigning a number-typed-any
  // to a `string` slot COMPILES — and at runtime the slot holds a number. This
  // is how `any` leaks invalid values silently through the type system.
  const leaked: string = danger; // OK (any assignable to string); runtime value is 1
  console.log("");
  console.log("const leaked: string = danger;             // COMPILES, but at runtime:");
  console.log(`  typeof leaked === ${typeof leaked}   (a number sitting in a string slot)`);
  expectType<Equal<typeof leaked, string>>("TS believes leaked === string (any leaked through)");
  check('typeof leaked === "number" at runtime (a number in a string-typed slot)', typeof leaked === "number");

  // The expert verdict: `any` is a CONTAGIOUS escape — it propagates through
  // every assignment, returning `any` and erasing types downstream. Prefer
  // `unknown` (§C): same "I don't know the type" intent, but it FORCES you to
  // narrow before use, so the compiler stays in the loop.
}

// ============================================================================
// Section C — `unknown`: the safe TOP type (you MUST narrow)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — unknown: the safe TOP type (you MUST narrow)");

  // `unknown` is the TOP type: EVERY value is assignable TO unknown, but NOTHING
  // is usable THROUGH unknown without first narrowing. It is the type-safe
  // replacement for `any` — same "I don't know the type yet" intent (e.g. the
  // output of JSON.parse or a foreign boundary), but the compiler REFUSES to let
  // you touch the value until you have proven (via a runtime check) what it is.

  // (1) unknown accepts any value (everything is assignable TO the top type).
  const u1: unknown = 1;
  const u2: unknown = "hello";
  const u3: unknown = { a: 1 };
  const u4: unknown = [1, 2, 3];
  const u5: unknown = null;
  console.log("unknown accepts ANY value (everything assignable TO the top type):");
  console.log(`  const u1: unknown = 1;        // ${typeof u1}`);
  console.log(`  const u2: unknown = "hello";  // ${typeof u2}`);
  console.log(`  const u3: unknown = { a: 1 }; // ${typeof u3}`);
  console.log(`  const u4: unknown = [1,2,3];  // ${typeof u4}`);
  console.log(`  const u5: unknown = null;     // ${typeof u5}`);
  check("unknown accepts number", typeof u1 === "number");
  check("unknown accepts string", typeof u2 === "string");
  check("unknown accepts object", typeof u3 === "object");
  check("unknown accepts array (typeof object)", typeof u4 === "object");
  check("unknown accepts null (typeof object — the lie)", typeof u5 === "object");

  // (2) But NOTHING is usable THROUGH unknown — the compiler REFUSES until you
  // narrow. Compare with §B: `any` allowed `.toUpperCase()` to compile (and
  // throw); `unknown` stops you at COMPILE time, before any code runs.
  console.log("");
  console.log("Through unknown, NOTHING is usable without narrowing:");
  console.log("  u2.toUpperCase();  -> COMPILE ERROR (Object is of type 'unknown')");
  // @ts-expect-error Object is of type 'unknown' — must narrow before use.
  u2.toUpperCase();

  // (3) Narrowing makes it usable — and SAFE. After a `typeof` check, TS
  // narrows `unknown` to the checked type along that branch (🔗 TYPE_NARROWING).
  let upper = "";
  if (typeof u2 === "string") {
    upper = u2.toUpperCase(); // OK: u2 narrowed to string inside the branch
  }
  console.log("  if (typeof u2 === 'string') u2.toUpperCase();  -> OK after narrowing");
  console.log(`  narrowed result: ${JSON.stringify(upper)}`);
  check("unknown narrowed via typeof: u2.toUpperCase() === 'HELLO' after the check", upper === "HELLO");

  // (4) THE unknown-vs-any CONTRAST, side by side. Same intent ("untyped
  // boundary"), opposite safety: any disables checking on BOTH reads and
  // writes; unknown disables USE until you prove the type.
  console.log("");
  console.log("unknown vs any — the contrast (same intent, opposite safety):");
  console.log("                   any                          unknown");
  console.log("  assign TO it:    any value (1,'x',{})         any value (1,'x',{})   [same]");
  console.log("  read FROM it:    ANY operation COMPILES      NOTHING compiles until narrowed");
  console.log("  assign FROM it:  assignable to any type      assignable ONLY to unknown/any");
  const fromAny: unknown = dangerAny(); // a value typed any
  // fromAny is unknown; assigning it onward requires unknown/any target:
  const passthrough: unknown = fromAny; // OK: unknown assignable to unknown
  void passthrough;
  expectType<Equal<typeof fromAny, unknown>>("a value typed any, read as unknown, is unknown");
  check("unknown is a safe SINK for any-typed values (no info lost, no use allowed)", fromAny !== undefined);
}

// dangerAny returns a value typed `any`, to contrast how `unknown` receives it.
// (Deliberately any-typed to show the any -> unknown sink; see §B for the danger.)
function dangerAny(): any {
  return 42;
}

// ============================================================================
// Section D — `satisfies` + `as const`: the modern, conformance-preserving choices
// ============================================================================

function sectionD(): void {
  sectionBanner("D — satisfies + as const: preserve the narrow type (TS 4.9+)");

  // Three ways to relate a value to a type (the expert taxonomy):
  //   const a = v as T         TELL the compiler v is T   (unchecked, can lie — §A)
  //   const b: T = v           CHECK v conforms to T, WIDEN b's type to T
  //   const c = v satisfies T  CHECK v conforms to T, PRESERVE c's narrow type
  // `satisfies` (TS 4.9) is the modern safe choice: it gives you a conformance
  // CHECK (so typos/shape errors are caught) WITHOUT throwing away the precise
  // per-property type the way an annotation would.

  type Port = number | { host: string; port: number };
  type Config = { db: Port; cache: Port };

  // satisfies: each property keeps its NARROW inferred type (db stays number,
  // cache stays the object shape) WHILE being checked against Config.
  const cfgSat = {
    db: 5432,
    cache: { host: "redis", port: 6379 },
  } satisfies Config;
  // annotation: every property is WIDENED to Config's declared type (Port).
  const cfgAnn: Config = {
    db: 5432,
    cache: { host: "redis", port: 6379 },
  };

  console.log("type Port = number | { host: string; port: number };");
  console.log("type Config = { db: Port; cache: Port };");
  console.log("const cfgSat = { db: 5432, cache: { host:'redis', port:6379 } } satisfies Config;");
  console.log("const cfgAnn: Config = { db: 5432, cache: { host:'redis', port:6379 } };");
  console.log("  typeof cfgSat.db    === number                       (satisfies: PRESERVED)");
  console.log("  typeof cfgSat.cache === { host: string; port: number } (satisfies: PRESERVED)");
  console.log("  typeof cfgAnn.db    === Port (the union)             (annotation: WIDENED)");
  console.log("  typeof cfgAnn.cache === Port (the union)             (annotation: WIDENED)");

  // COMPILE-TIME evidence (tsc fails if any claim is wrong):
  expectType<Equal<typeof cfgSat.db, number>>(
    "satisfies preserves cfgSat.db === number",
  );
  expectType<Equal<typeof cfgSat.cache, { host: string; port: number }>>(
    "satisfies preserves cfgSat.cache === { host: string; port: number }",
  );
  expectType<Equal<typeof cfgAnn.db, Port>>(
    "annotation widens cfgAnn.db === Port (the union)",
  );
  expectType<Equal<typeof cfgAnn.cache, Port>>(
    "annotation widens cfgAnn.cache === Port (the union)",
  );

  // THE PAYOFF: because satisfies preserved cfgSat.db as `number`, you can use
  // it DIRECTLY. cfgAnn.db was widened to `Port` (number | object), so the SAME
  // access is a compile error until you narrow.
  const dbPortDirect: number = cfgSat.db; // OK: cfgSat.db === number
  console.log("");
  console.log("THE PAYOFF — satisfies keeps downstream usage type-safe:");
  console.log("  const dbPortDirect: number = cfgSat.db;   -> OK (cfgSat.db === number)");
  console.log("  cfgAnn.db.toFixed();                      -> ERROR (cfgAnn.db === Port, must narrow)");
  // @ts-expect-error Property 'toFixed' does not exist on type '{ host: string; port: number }' (cfgAnn.db widened to Port).
  cfgAnn.db.toFixed();
  check("satisfies: cfgSat.db usable directly as number (=== 5432)", dbPortDirect === 5432);

  // RUNTIME evidence: satisfies emits NO code (it is a pure typecheck-time
  // operator). The two objects are byte-identical at runtime. (cfgAnn.cache is
  // typed as the Port UNION, so we narrow it via cfgSat — whose cache type was
  // PRESERVED to the object shape — before reading .port.)
  const annCachePort = readCachePort(cfgAnn); // cfgAnn.cache is Port; narrow inside
  check(
    "satisfies emits no code: cfgSat.db === cfgAnn.db === 5432 at runtime",
    cfgSat.db === cfgAnn.db && cfgSat.db === 5432,
  );
  check(
    "satisfies emits no code: cfgSat.cache.port === cfgAnn cache port === 6379",
    cfgSat.cache.port === 6379 && annCachePort === 6379,
  );

  // ---- as const: assert the NARROWEST literal/readonly type ----------------
  //
  // `expr as const` makes every literal as narrow as possible AND every property
  // `readonly`. On an array it produces a readonly TUPLE of literals; on an
  // object it produces a fully-readonly object of literal types. Like `as` and
  // `satisfies`, it emits NO runtime code (it is erased).
  const tuple = [1, 2] as const;
  const obj = { kind: "ok", code: 200 } as const;
  console.log("");
  console.log("as const — assert the narrowest literal/readonly type:");
  console.log("  const tuple = [1, 2] as const;            -> typeof tuple === readonly [1, 2]");
  console.log('  const obj = { kind: "ok", code: 200 } as const;  -> { readonly kind: "ok"; readonly code: 200 }');
  expectType<Equal<typeof tuple, readonly [1, 2]>>("as const: [1, 2] -> readonly [1, 2]");
  expectType<Equal<typeof obj, { readonly kind: "ok"; readonly code: 200 }>>(
    'as const: object -> { readonly kind: "ok"; readonly code: 200 }',
  );
  // as const is TYPE-ONLY — it does NOT call Object.freeze at runtime. The
  // array is still a mutable plain array; only the TYPE is readonly.
  console.log("  as const is TYPE-ONLY — it does NOT Object.freeze at runtime.");
  console.log(`  Object.isFrozen(tuple) === ${Object.isFrozen(tuple)}   (readonly type, mutable value)`);
  check("as const is type-only: tuple is NOT frozen at runtime", Object.isFrozen(tuple) === false);
  check("as const runtime values unchanged: tuple[0] === 1, tuple[1] === 2", tuple[0] === 1 && tuple[1] === 2);

  // 🔗 STRUCTURAL_TYPING §B has the canonical `satisfies` palette example
  // (per-key union preservation); this section adds the annotation-widening
  // contrast and the `as const` tuple case.
}

// ============================================================================
// Section E — `never` (the BOTTOM type) + THE RULE: prefer narrowing over `as`
// ============================================================================

function sectionE(): void {
  sectionBanner("E — never (bottom type) + THE RULE: prefer a guard over `as`");

  // `never` is the BOTTOM type — the EMPTY SET of values. No value has type
  // never. It is the dual of `unknown` (the TOP type, which holds every value).
  // It arises in three places, each useful:
  //   (1) the return type of a function that NEVER returns (throws / loops);
  //   (2) the empty intersection (string & number === never — 🔗 UNIONS_INTERSECTIONS);
  //   (3) the unreachable branch of an exhaustive switch (the exhaustiveness tool).

  // (1) A function returning `never` never returns — it either throws or runs
  // forever. Because there is no value of type never, `never` is assignable to
  // EVERY type (the empty set fits anywhere), so `return fail(...)` typechecks
  // inside any function regardless of its return type.
  console.log("(1) never-returning functions (throw or loop forever):");
  console.log("  function fail(msg: string): never { throw new Error(msg); }");
  console.log("  never is assignable to EVERY type (the empty set fits anywhere).");
  expectType<Equal<ReturnType<typeof fail>, never>>("ReturnType<typeof fail> === never");

  // (2) The empty intersection: two disjoint types intersected yield never.
  // (Full treatment: 🔗 UNIONS_INTERSECTIONS §C.)
  type EmptyIntersection = string & number;
  console.log("");
  console.log("(2) The empty intersection:");
  console.log("  type EmptyIntersection = string & number;   -> never (no value is both)");
  expectType<Equal<EmptyIntersection, never>>("string & number === never (empty intersection)");

  // (3) Exhaustive switch: after every case is handled, the remaining value is
  // `never`. Routing it through a `never`-parameter function (`fail` here) is
  // the standard exhaustiveness check — add a union member without a case and
  // the `default` branch stops being `never`, so `fail(r)` becomes a compile
  // error. This is the JS/TS analog of Rust's exhaustive `match`.
  console.log("");
  console.log("(3) Exhaustive switch (never is the exhaustiveness tool):");
  console.log("  type Result = { ok: true; value: number } | { ok: false; error: string };");
  console.log("  function handle(r: Result): string {");
  console.log("    switch (r.ok) {");
  console.log("      case true:  return `value=${r.value}`;");
  console.log("      case false: return `error=${r.error}`;");
  console.log("      default:    return fail(`unexpected: ${r}`);  // r is never here");
  console.log("    }");
  console.log("  }");
  const r1 = handle({ ok: true, value: 7 });
  const r2 = handle({ ok: false, error: "boom" });
  console.log(`  handle({ ok: true, value: 7 })       -> ${JSON.stringify(r1)}`);
  console.log(`  handle({ ok: false, error: "boom" }) -> ${JSON.stringify(r2)}`);
  check('never exhaustiveness: handle({ok:true,value:7}) === "value=7"', r1 === "value=7");
  check('never exhaustiveness: handle({ok:false,error:"boom"}) === "error=boom"', r2 === "error=boom");

  // (4) THE RULE — the expert takeaway for the whole bundle. Prefer `unknown`
  // + a runtime guard over `any`; prefer a type PREDICATE (`x is T`) over `as T`.
  // A predicate narrows via a REAL runtime check (🔗 TYPE_NARROWING), so it is
  // the SAFE alternative to the unchecked `as`.
  console.log("");
  console.log("(4) THE RULE — prefer a type PREDICATE over `as`:");
  console.log("  function isNumberGuard(x: unknown): x is number { return typeof x === 'number'; }");
  console.log("  function safeDouble(x: unknown): number {");
  console.log("    if (isNumberGuard(x)) return x * 2;   // SAFE: narrowed by a runtime check");
  console.log("    throw new TypeError(`expected number, got ${typeof x}`);");
  console.log("  }");
  console.log("  // Contrast: `return (x as number) * 2;` would COMPILE for any value and LIE.");
  const doubled = safeDouble(21);
  console.log(`  safeDouble(21) -> ${doubled}   (predicate narrowed x to number)`);
  check("type predicate (safe alt to `as`): safeDouble(21) === 42", doubled === 42);
  // The predicate IS a runtime check the compiler can see: after isNumberGuard,
  // x is number with NO assertion needed.
  expectType<Equal<Parameters<typeof isNumberGuard>[0], unknown>>(
    "isNumberGuard accepts unknown (the safe top type)",
  );

  // THE TYPE LATTICE, summarized. unknown (top) and never (bottom) bracket the
  // lattice; any is the escape that SKIPS it (dangerous); as/satisfies are the
  // two assertion operators (forced vs conformance-preserving). See the .md's
  // mermaid diagram for the full picture.
  check(
    "unknown is the TOP type, never is the BOTTOM type (this bundle's spine)",
    true,
  );
}

// fail is a never-returning function: it always throws, so its return type is
// never. Used in §E as the exhaustiveness sink (never is assignable to every
// type, so `return fail(...)` typechecks inside any function).
function fail(msg: string): never {
  throw new Error(msg);
}

// isNumberGuard is a user-defined type PREDICATE — the SAFE alternative to `as`.
// The body is an ordinary typeof check; the `x is number` RETURN TYPE annotation
// is what makes TS narrow the caller's argument in the true branch. (🔗 TYPE_NARROWING.)
function isNumberGuard(x: unknown): x is number {
  return typeof x === "number";
}

// safeDouble uses the predicate to narrow unknown -> number with NO `as`. This
// is the recommended pattern: accept unknown, narrow with a guard, then use.
function safeDouble(x: unknown): number {
  if (isNumberGuard(x)) {
    return x * 2; // x narrowed to number by the predicate — safe, no assertion
  }
  throw new TypeError(`expected number, got ${typeof x}`);
}

// handle demonstrates never as the exhaustiveness tool. After both cases of the
// Result discriminated union return, the default branch sees r as never; routing
// it through fail() (which returns never, assignable to string) both documents
// unreachability and enforces exhaustiveness at compile time.
function handle(r: Result): string {
  switch (r.ok) {
    case true:
      return `value=${r.value}`;
    case false:
      return `error=${r.error}`;
    default:
      // r is `never` here — every case is handled. fail() returns never, which
      // is assignable to the string return type. If a new Result variant is
      // added, r stops being never here and this line becomes a compile error.
      return fail(`unexpected: ${JSON.stringify(r)}`);
  }
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("type_assertions_unknown.ts — Phase 2 bundle (Type System & Generics).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TypeScript types are ERASED at runtime (tsx/tsc strip them).");
  console.log("So `as`, `satisfies`, and `as const` emit NO code — only the runtime");
  console.log("checks (typeof / instanceof / type predicates) actually execute.");
  console.log("That erasure is WHY an assertion can lie: it changes the compile-time");
  console.log("view but leaves the runtime value untouched.");
  console.log("");
  console.log("Two evidence modes: check() = RUNTIME verdict; expectType<>/");
  console.log("@ts-expect-error = COMPILE-TIME verdict (the typecheck is canon).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
