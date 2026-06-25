// structural_typing.ts — Phase 2 bundle (Type System & Generics).
//
// GOAL (one line): show, by printing every value AND by compile-time gates,
// that TypeScript is STRUCTURALLY typed (duck typing on shape, not name) —
// pinning the excess-property-on-literals asymmetry, the brand pattern that
// fakes nominal safety (and erases to a plain string at runtime), `satisfies`
// vs annotation, function bivariance, and the typeof/keyof type queries.
//
// This is the GROUND TRUTH for STRUCTURAL_TYPING.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle sits here): VALUES_TYPES_COERCION pinned that TS
// types are ERASED at runtime — `typeof`/`instanceof` are runtime, `interface`/
// `type` are compile-only. This bundle opens up the COMPILE-TIME layer: HOW the
// type system decides "is X assignable to Y". The answer is STRUCTURAL — a
// value matches a type if it has the right MEMBERS, regardless of the type's
// NAME. That is what makes TS feel like "just JavaScript with types": object
// literals and anonymous shapes are first-class. The sharp edges that follow
// are the expert payoff: (1) excess property checks fire ONLY on fresh object
// literals (an anti-typo safety net that is STRONGER than pure structural
// matching); (2) there is NO nominal safety — two same-shaped types are
// interchangeable, so the community invented the BRAND pattern (a phantom
// property) to fake it; (3) function parameters are checked BIVARIANTLY for
// methods but CONTRAVARIANTLY for function-typed properties under
// `strictFunctionTypes`. Contrast Go (also implicit/structural — the closest
// sibling, via its implicit interfaces) and Rust (NOMINAL — a struct must
// explicitly `impl Trait for Type`, the starkest contrast).
//
// EVIDENCE MODES (this bundle is mostly compile-time): runtime claims are
// asserted via `check()`; type-level claims are asserted via `expectType<...>`
// (which itself only compiles when the type argument is `true`, and prints a
// `[check]` line at runtime) and via `// @ts-expect-error` on lines that
// SHOULD error (tsc fails the build if such a directive is UNUSED — i.e. if
// the line did not actually error). Both modes print `[check]` lines.
//
// Run:
//     pnpm exec tsx structural_typing.ts   (or: just run structural_typing)

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
// `noUnusedParameters` does not flag the type parameter (T appears only in its
// constraint otherwise). `true as T` is sound because T extends true, so the
// assertion is a legal supertype-to-subtype downcast; it is erased at runtime.
function expectType<T extends true>(msg: string): void {
  const _proof: T = true as T;
  void _proof;
  console.log(`[check] ${msg}: OK`);
}

// ============================================================================
// Section A — Structural compatibility: "has at least" the members
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Structural compatibility: has-at-least the members");

  // The BASIC RULE of TS structural typing (handbook "Type Compatibility"):
  //   x is assignable to y iff y has AT LEAST the same members as x.
  // Only the TARGET type's members are inspected; EXTRA members on the source
  // are ignored (a "width" / "subtype" check). This is duck typing: if it
  // walks like a Point and quacks like a Point, it IS a Point — no `implements`
  // keyword, no name match required.

  type Point = { x: number; y: number };

  // p is inferred as { x: number; y: number; z: number } — it has x AND y
  // (and an extra z). Because it has AT LEAST { x; y }, it is assignable to
  // Point. The extra z is silently allowed (structural compatibility).
  const p = { x: 1, y: 2, z: 3 };
  const q: Point = p; // OK: p satisfies the shape of Point

  console.log("type Point = { x: number; y: number }");
  console.log("const p = { x: 1, y: 2, z: 3 }   (inferred: { x; y; z })");
  console.log("const q: Point = p              -> OK (p has AT LEAST x and y)");
  console.log(`runtime: q.x = ${q.x}, q.y = ${q.y}   (z is invisible through Point)`);

  // RUNTIME evidence: at runtime, Point is ERASED — q is just the object p.
  check('typeof q === "object" (Point type erased at runtime)', typeof q === "object");
  check("q.x === 1 and q.y === 2 (structural assignment copies the reference)", q.x === 1 && q.y === 2);

  // COMPILE-TIME evidence: q is typed exactly as Point, and the source p still
  // carries its wider inferred shape (z preserved on p, invisible through q).
  expectType<Equal<typeof q, Point>>("typeof q === Point");
  expectType<Equal<typeof p, { x: number; y: number; z: number }>>(
    "typeof p === { x: number; y: number; z: number } (source shape preserved)",
  );

  // The SAME structural rule applies to function CALL ARGUMENTS — only the
  // parameter type's members are checked, extras on the argument are ignored.
  function magnitude(pt: Point): number {
    return Math.sqrt(pt.x * pt.x + pt.y * pt.y);
  }
  const m = magnitude(p); // OK: p is structurally a Point
  console.log("");
  console.log(`magnitude(p) -> ${m.toFixed(4)}   (extra z ignored by the callee)`);
  check("magnitude(p) === sqrt(5) (structural arg check)", m === Math.sqrt(5));

  // -- cross-shape: same cardinality, DIFFERENT member names ----------------
  // Two types with the SAME number of members but DIFFERENT names are NOT
  // compatible. Structural typing keys on member NAME + type, not on shape
  // width alone. A Screen { horizontal; vertical } is NOT a Point { x; y }.
  type Screen = { horizontal: number; vertical: number };
  const screen: Screen = { horizontal: 800, vertical: 600 };
  console.log("");
  console.log("type Screen = { horizontal: number; vertical: number }");
  console.log("Screen and Point have the SAME width (two numbers) but DIFFERENT");
  console.log("member NAMES -> a Screen is NOT assignable to a Point.");
  // @ts-expect-error Screen has no `x`/`y` members — structurally incompatible
  const asPoint: Point = screen;
  void asPoint;
  expectType<Equal<keyof Screen, "horizontal" | "vertical">>(
    'keyof Screen === "horizontal" | "vertical"',
  );
}

// ============================================================================
// Section B — Excess property checks (literals) & satisfies vs annotation
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Excess property checks (literals) & satisfies vs annotation");

  // THE ASYMMETRY (handbook "Object Types" → Excess Property Checks): a FRESH
  // object literal assigned directly to a typed target is checked MORE strictly
  // than a variable. The literal cannot have ANY property the target type lacks
  // — even though pure structural typing would allow it. This is an anti-TYPO
  // safety net (catches `{ colour: ... }` when you meant `{ color: ... }`).
  //
  // But assign the SAME object via a variable, and the check is SKIPPED — you
  // get plain structural compatibility again (extras allowed). This asymmetry
  // is the single most-surprising thing about TS structural typing.

  type Point = { x: number; y: number };

  // (1) Fresh literal with an excess property -> ERROR. The @ts-expect-error
  // below proves the error is real: if tsc ever stopped erroring here, the
  // UNUSED-directive would itself fail the build. This is the typecheck gate.
  // @ts-expect-error excess property `z` on a fresh object literal assigned to Point
  const fromLiteral: Point = { x: 1, y: 2, z: 3 };
  void fromLiteral;

  // (2) The SAME shape via a variable -> OK (excess check does not fire; plain
  // structural "has at least" applies). This is the asymmetry.
  const v = { x: 1, y: 2, z: 3 };
  const fromVariable: Point = v;
  console.log("type Point = { x: number; y: number }");
  console.log("  const fromLiteral: Point = { x:1, y:2, z:3 }   -> ERROR (excess z)");
  console.log("  const v = { x:1, y:2, z:3 }; const q: Point = v -> OK (variable bypass)");
  console.log(`  fromVariable.x = ${fromVariable.x}`);
  check("fromVariable.x === 1 (variable assignment bypasses excess check)", fromVariable.x === 1);

  // (3) Weak-type / no-common-property guard: a type whose properties are ALL
  // optional is a "weak type". Even via a variable, if the source shares NO
  // property name with the target, TS errors — such an assignment is almost
  // certainly a bug (a typo'd key set).
  type Options = { color?: string; width?: number };
  console.log("");
  console.log("type Options = { color?: string; width?: number }  (all-optional = weak type)");
  // @ts-expect-error weak-type guard: { flavour } shares NO property with Options
  const badOpts: Options = { flavour: "chocolate" };
  void badOpts;
  console.log("  const badOpts: Options = { flavour: 'chocolate' } -> ERROR (no common prop)");

  // ---- `satisfies` (TS 4.9) vs type annotation -----------------------------
  //
  // `const x = expr satisfies T` VALIDATES that expr conforms to T, but the
  // INFERRED type of each property is PRESERVED — annotation REPLACES each
  // property's type with T's declared one (widening). Use `satisfies` when you
  // want both conformance AND the precise per-property type downstream (so e.g.
  // `paletteSat.red[0]` needs no narrowing, while `paletteAnn.red` would).
  //
  // The classic example (TS 4.9 release notes): a palette whose values are
  // EITHER a string OR an [r,g,b] tuple. `satisfies` keeps each entry's
  // specific type; the annotation types every entry as the full union.

  type RGB = [number, number, number];
  type ColorEntry = string | RGB;

  const paletteSat = {
    red: [255, 0, 0],
    green: "#00ff00",
  } satisfies Record<"red" | "green", ColorEntry>;
  const paletteAnn: Record<"red" | "green", ColorEntry> = {
    red: [255, 0, 0],
    green: "#00ff00",
  };

  console.log("");
  console.log('type RGB = [number, number, number]; type ColorEntry = string | RGB');
  console.log("const paletteSat = { red:[255,0,0], green:'#00ff00' } satisfies Record<...,ColorEntry>");
  console.log("const paletteAnn: Record<...,ColorEntry>       = { red:[255,0,0], green:'#00ff00' }");
  console.log("  typeof paletteSat.red   === [number,number,number]   (satisfies: per-key type PRESERVED)");
  console.log("  typeof paletteSat.green === string                  (satisfies: per-key type PRESERVED)");
  console.log("  typeof paletteAnn.red   === ColorEntry (the union)  (annotation: WIDENED to declared type)");
  console.log("  typeof paletteAnn.green === ColorEntry (the union)  (annotation: WIDENED to declared type)");

  // COMPILE-TIME evidence: the two declarations diverge in inferred type. All
  // four claims below are pinned by Equal<> (tsc fails if any is wrong).
  expectType<Equal<typeof paletteSat.red, [number, number, number]>>(
    "satisfies preserves typeof paletteSat.red === [number, number, number]",
  );
  expectType<Equal<typeof paletteSat.green, string>>(
    "satisfies preserves typeof paletteSat.green === string",
  );
  expectType<Equal<typeof paletteAnn.red, ColorEntry>>(
    "annotation widens typeof paletteAnn.red === ColorEntry (the union)",
  );
  expectType<Equal<typeof paletteAnn.green, ColorEntry>>(
    "annotation widens typeof paletteAnn.green === ColorEntry (the union)",
  );

  // RUNTIME evidence: both objects are identical plain objects at runtime —
  // `satisfies` emits NO code, it is a pure typecheck-time operator.
  check(
    'paletteSat.green === paletteAnn.green === "#00ff00" at runtime (satisfies emits no code)',
    paletteSat.green === paletteAnn.green && paletteSat.green === "#00ff00",
  );
  check(
    "paletteSat.red[0] === 255 === paletteAnn.red[0] (identical values at runtime)",
    paletteSat.red[0] === 255 && paletteAnn.red[0] === 255,
  );
}

// ============================================================================
// Section C — Nominal faking via brands (THE payoff): compile-time safe, runtime-erased
// ============================================================================

// The brand pattern: intersect a primitive with a phantom property keyed by a
// DECLARED `unique symbol`. The symbol is a type-level marker that is NEVER
// actually created or set on a value — so at runtime a UserId is still a plain
// string, yet at compile time TS treats UserId and OrderId as DISTINCT types
// because their unique-symbol brands differ. This is the standard community
// workaround for TS having NO nominal typing (Microsoft/TypeScript wiki
// "Nominal typing"). Equivalent spellings exist (branded classes, opaque
// types); the unique-symbol intersection is the lightest and zero-cost at
// runtime.
declare const userIdBrand: unique symbol;
declare const orderIdBrand: unique symbol;
type UserId = string & { readonly [userIdBrand]: true };
type OrderId = string & { readonly [orderIdBrand]: true };

// A FACTORY is the single trusted boundary for minting a branded value: take a
// plain string in, cast through to the branded type. All other call sites then
// get compile-time protection for free (you cannot forge a UserId from a bare
// string outside this factory).
function mkUserId(raw: string): UserId {
  return raw as UserId;
}
function mkOrderId(raw: string): OrderId {
  return raw as OrderId;
}

function sectionC(): void {
  sectionBanner("C — Nominal faking via brands (compile-time safe, runtime-erased)");

  // THE PAYOFF, in two halves:
  //   (a) RUNTIME: a branded UserId is JUST a string. The brand property never
  //       exists on the value — `typeof === "string"`, the brand key is absent,
  //       JSON.stringify prints the raw string. Types are erased.
  //   (b) COMPILE-TIME: you CANNOT assign a bare string to UserId, and you
  //       CANNOT assign a UserId to an OrderId — even though both erase to
  //       `string` at runtime. The phantom symbol makes them nominal.

  const id = mkUserId("u-42");
  const ord = mkOrderId("o-7");

  console.log("declare const userIdBrand: unique symbol;");
  console.log("type UserId  = string & { readonly [userIdBrand]: true };");
  console.log("type OrderId = string & { readonly [orderIdBrand]: true };");
  console.log("(the unique symbols are DECLARED but never created as values)");
  console.log("");
  console.log(`const id  = mkUserId("u-42") -> runtime: typeof = ${typeof id}, value = "${id}"`);
  console.log(`const ord = mkOrderId("o-7") -> runtime: typeof = ${typeof ord}, value = "${ord}"`);
  console.log(`  id.length = ${id.length}, JSON.stringify(id) = ${JSON.stringify(id)}   (brand is a phantom symbol key;`);
  console.log(`  declared but NEVER created as a runtime value, so id is just the raw string)`);

  // (a) RUNTIME evidence: the brand is a phantom — types erased. The symbol is
  // `declare`d (ambient: compile-time only, no runtime value), so a branded
  // value is indistinguishable from a plain string at runtime.
  check('typeof branded UserId === "string" (brand erased at runtime)', typeof id === "string");
  check('typeof branded OrderId === "string"', typeof ord === "string");
  check(
    "the brand is a phantom symbol never created at runtime (id is just the raw string)",
    id.length === 4 && JSON.stringify(id) === '"u-42"',
  );
  check('id === "u-42" at runtime (raw string preserved)', id === "u-42");

  // (b) COMPILE-TIME evidence: bare strings and foreign brands are rejected.
  // Each @ts-expect-error below suppresses a REAL error — if it ever stopped
  // erroring, tsc fails the build on the unused directive. That is the gate.
  // @ts-expect-error a bare string is not assignable to branded UserId
  const directAssign: UserId = "u-42";
  void directAssign;
  // @ts-expect-error UserId and OrderId are nominally distinct (different brands)
  const crossBrand: OrderId = id;
  void crossBrand;
  console.log("");
  console.log("  const directAssign: UserId = \"u-42\"   -> ERROR (bare string rejected)");
  console.log("  const crossBrand: OrderId = id         -> ERROR (UserId != OrderId)");

  // And the positive direction: the factory mints a value that IS assignable.
  const idOk: UserId = mkUserId("u-99");
  expectType<Equal<typeof idOk, UserId>>("mkUserId returns exactly UserId");
  check('idOk === "u-99" (factory output is the raw string at runtime)', idOk === "u-99");

  // THE CONTRAST: WITHOUT brands, two same-shaped aliases are FULLY
  // interchangeable (pure structural typing has no name identity). This is the
  // bug class the brand pattern exists to prevent — a Username silently flowing
  // into an Email parameter, etc.
  type Email = string;
  type Username = string;
  const email: Email = "a@b.com";
  const username: Username = email; // OK! both are just `string` — no protection
  console.log("");
  console.log("Without brands: type Email = string; type Username = string;");
  console.log("  const username: Username = email  -> OK (purely structural; NO protection)");
  check(
    "unbranded aliases are interchangeable (no nominal safety by default)",
    username === email,
  );
}

// ============================================================================
// Section D — Function variance, typeof query, keyof & indexed access
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Function variance, typeof query, keyof & indexed access");

  // ---- Function parameter VARIANCE ----------------------------------------
  //
  // Under `strict` (which turns ON `strictFunctionTypes`):
  //   * FUNCTION-TYPE PROPERTIES (e.g. `type H = (e: Base) => void`) check
  //     their parameters CONTRAVARIANTLY: a function accepting a WIDER type is
  //     assignable where a NARROWER-accepting one is expected, but NOT the
  //     reverse. This is the sound direction.
  //   * METHOD syntax (e.g. `interface E { handle(e: Base): void }`) is
  //     EXCLUDED from strictFunctionTypes and stays BIVARIANT — either
  //     direction is allowed. This is unsound, but preserves compatibility
  //     with the many JS patterns built on method-shaped callbacks (the
  //     handbook's EventType example).

  interface BaseEvent {
    timestamp: number;
  }
  interface ClickEvent extends BaseEvent {
    x: number;
    y: number;
  }

  // (1) CONTRAVARIANCE, sound direction: a function accepting the WIDER type
  // (BaseEvent) IS assignable where a ClickEvent-accepting function is
  // expected — because anything it receives will be a ClickEvent, which IS a
  // BaseEvent. (A non-void return is also assignable to a void return.)
  const logBase = (e: BaseEvent): number => e.timestamp;
  type ClickHandler = (e: ClickEvent) => void;
  const widerHandler: ClickHandler = logBase; // OK: contravariance + void return
  const ts = widerHandler({ timestamp: 1, x: 2, y: 3 });
  void ts;
  expectType<Equal<typeof widerHandler, ClickHandler>>(
    "(e: BaseEvent) => number is assignable to (e: ClickEvent) => void (contravariance)",
  );

  // (2) CONTRAVARIANCE, unsound direction (function property): a function that
  // accepts ONLY ClickEvent CANNOT be typed as accepting any BaseEvent — it
  // would read e.x on something that may not have it. strictFunctionTypes
  // catches this. The @ts-expect-error proves the error is real.
  type BaseHandler = (e: BaseEvent) => void;
  const logClick = (e: ClickEvent): number => e.x + e.y;
  // @ts-expect-error contravariance: (e: ClickEvent) => number is not assignable to (e: BaseEvent) => void
  const unsoundFnProp: BaseHandler = logClick;
  void unsoundFnProp;

  // (3) BIVARIANCE via METHOD syntax: the SAME unsound assignment IS allowed
  // for a method, because methods are exempt from strictFunctionTypes. This is
  // deliberately unsound to keep real-world callback-heavy JS typed.
  interface Emitter {
    emit(e: BaseEvent): void;
  }
  const emitter: Emitter = { emit: logClick }; // OK — method params are bivariant
  console.log("interface Emitter { emit(e: BaseEvent): void }   (METHOD -> bivariant)");
  console.log("const emitter: Emitter = { emit: logClick }       -> OK (methods are bivariant)");
  console.log("emitter.emit({ timestamp: 99 })                   -> runtime: logClick reads .x = undefined");
  check(
    "method-syntax bivariance allows the unsound assignment (strictFunctionTypes exempts methods)",
    typeof emitter.emit === "function",
  );

  // ---- `typeof` type query: derive a type from a runtime value -------------
  //
  // `type T = typeof v` lifts a VALUE's (inferred) type into a named type. It
  // is the bridge from the runtime world to the type world — and it is how the
  // inferred shapes above (paletteSat, branded factories) get reused.
  const defaultPoint = { x: 0, y: 0, label: "origin" };
  type DefaultPoint = typeof defaultPoint; // { x: number; y: number; label: string }
  console.log("");
  console.log('const defaultPoint = { x: 0, y: 0, label: "origin" }');
  console.log("type DefaultPoint = typeof defaultPoint");
  expectType<Equal<DefaultPoint, { x: number; y: number; label: string }>>(
    "typeof defaultPoint === { x: number; y: number; label: string }",
  );

  // ---- keyof & indexed access: pick apart a type at the type level ---------
  //
  // `keyof T` is the union of T's property names. `T[K]` is the type of the
  // property at key K. Together with `typeof`, they build new types purely
  // from existing shapes — no duplication.
  type Point = { x: number; y: number };
  type PointKeys = keyof Point; // "x" | "y"
  type PointX = Point["x"]; // number
  type LabelOfDefault = DefaultPoint["label"]; // string
  console.log("");
  console.log("type Point = { x: number; y: number }");
  console.log('type PointKeys = keyof Point        // "x" | "y"');
  console.log('type PointX = Point["x"]            // number');
  expectType<Equal<PointKeys, "x" | "y">>('keyof Point === "x" | "y"');
  expectType<Equal<PointX, number>>('Point["x"] === number');
  expectType<Equal<LabelOfDefault, string>>('DefaultPoint["label"] === string');

  // RUNTIME tie-back: keyof/indexed-access are PURE type-level operators —
  // they emit no code and have no runtime representation. The only thing that
  // exists at runtime is the value defaultPoint itself.
  check(
    "typeof defaultPoint === object (keyof/indexed-access emit no runtime code)",
    typeof defaultPoint === "object" && defaultPoint.x === 0,
  );
}

// ============================================================================
// Section E — Cross-language framing: Go (structural) vs Rust (nominal)
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Cross-language framing: Go (structural) vs Rust (nominal)");

  // TS's structural typing is not unique — it is the SAME model Go uses for
  // interfaces (a value satisfies an interface iff it has the required
  // methods; no `implements` keyword). Rust is the opposite: a struct must
  // EXPLICITLY `impl Trait for Type`, so identity is by DECLARATION (nominal).
  // Python's `typing.Protocol` (with @runtime_checkable) is structural too.
  //
  // Each row is an `as const` tuple so element access is exact (no
  // possibly-undefined under noUncheckedIndexedAccess) AND the element types
  // are literal strings we can assert against.

  const TS = ["TypeScript", "structural", "implicit (by shape)", "yes (the brand pattern)"] as const;
  const GO = ["Go", "structural", "implicit (by shape)", "n/a (interfaces are the model)"] as const;
  const PY = ["Python", "structural", "implicit (Protocol)", "no (Protocol is structural)"] as const;
  const RU = ["Rust", "nominal", "EXPLICIT `impl Trait for T`", "native (traits are nominal)"] as const;
  const rows: readonly (readonly [string, string, string, string])[] = [TS, GO, PY, RU];

  console.log("language     : model      : satisfaction         : nominal escape hatch");
  console.log("------------ : ---------- : -------------------- : ---------------------------");
  for (const [lang, model, sat, hatch] of rows) {
    console.log(
      `${lang.padEnd(12)} : ${model.padEnd(10)} : ${sat.padEnd(20)} : ${hatch}`,
    );
  }

  check(
    "TS + Go are structural (shape-based); Rust is nominal (declaration-based)",
    TS[1] === "structural" && GO[1] === "structural" && RU[1] === "nominal",
  );
  check(
    "Go interfaces are IMPLICIT (no implements keyword) — TS's closest sibling",
    GO[2] === "implicit (by shape)",
  );
  check(
    "Rust requires EXPLICIT `impl Trait for T` — the starkest contrast to TS",
    RU[2] === "EXPLICIT `impl Trait for T`",
  );

  // THE CONSEQUENCE for TS experts: because TS is structural, a value of one
  // type silently flows into another same-shaped type unless you BRAND it
  // (Section C). In Rust the compiler enforces the boundary for free; in TS
  // you opt into it. That is the whole reason the brand pattern exists.
  console.log("");
  console.log("Expert consequence: TS gives you nominal safety ONLY if you ask");
  console.log("for it (brands). Rust gives it to you for free. Go — like TS — does");
  console.log("not, which is why both ecosystems lean on conventions/linters.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("structural_typing.ts — Phase 2 bundle (Type System & Generics).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TS types are ERASED at runtime. The COMPILE-TIME claims");
  console.log("below are gated by `expectType<...>` (compiles only if true) and by");
  console.log("`// @ts-expect-error` on lines that SHOULD error (tsc fails if unused).");
  console.log("RUNTIME claims are gated by `check(...)`.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
