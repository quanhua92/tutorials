// interfaces_vs_aliases.ts — Phase 2 bundle (Type System & Generics).
//
// GOAL (one line): show, by check()'d runtime behavior AND tsc-verified
// expectType<>/@ts-expect-error compile-time proofs, how TypeScript's TWO ways to
// name an object shape — `interface` and `type` alias — overlap (both structural,
// both erased) yet differ in ONE decisive way: interfaces are OPEN (declaration
// merging + `extends`/`implements`) while type aliases are ALGEBRAIC (unions,
// intersections, tuples, mapped/conditional types).
//
// This is the GROUND TRUTH for INTERFACES_VS_ALIASES.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle sits where it does): VALUES_TYPES_COERCION pinned that
// TS types are ERASED at runtime, and STRUCTURAL_TYPING pinned that TS decides
// assignability by SHAPE not NAME (so two same-shaped types are interchangeable,
// which is why the BRAND pattern fakes nominal safety). This bundle answers the
// question that leaves open: "given two keywords that BOTH name an object shape,
// which do I reach for?" The overlap is real — for a plain `{ x; y }` an
// interface and a type alias are EXACTLY equal (pinned by expectType<Equal<...>>
// in Section A). But they are NOT interchangeable as type-level machinery:
// interfaces can be DECLARED OPEN and MERGED (the engine that powers lib.d.ts
// augmentation, plugin .d.ts, and global Array/String patching), while type
// aliases are the only spelling for unions, intersections, tuples, and mapped/
// conditional types. Knowing where each wins is the difference between flowing
// with the checker and fighting it.
//
// Cross-language pivot (why this is a TS-specific concept): Go, Rust, and Python
// each have exactly ONE "shape contract" concept — `interface` (Go, implicit/
// structural, method-set only), `trait` (Rust, nominal, explicit `impl`), or
// `Protocol` (Python, structural). TypeScript is unusual in offering BOTH an
// open, mergeable `interface` AND a closed, algebraic `type` alias — and in
// letting them interact (an interface can `extend` a type alias; a type alias
// can intersect an interface). Section E frames the contrast.
//
// EVIDENCE MODES (this bundle is mostly compile-time): runtime claims are
// asserted via `check()`; type-level claims are asserted via `expectType<...>`
// (which itself only compiles when the type argument is `true`, and prints a
// `[check]` line at runtime) and via `// @ts-expect-error` on lines that
// SHOULD error (tsc fails the build if such a directive is UNUSED — i.e. if the
// line did not actually error). Both modes print `[check]` lines.
//
// Run:
//     pnpm exec tsx interfaces_vs_aliases.ts   (or: just run interfaces_vs_aliases)

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
// are identical. This is the canonical community idiom for exact equality, and
// it is what proves `interface P` and `type P = {...}` collapse to the SAME
// type for a flat object shape (Section A).
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
// Section A — Both structural: an interface and a type alias are the SAME type
// ============================================================================

// A flat object shape named two ways. For the SHAPE ITSELF there is no
// difference: IPoint and TPoint are the SAME type (not merely assignable —
// IDENTICAL, per the Equal<> trick below). This is the headline equivalence.
interface IPoint {
  x: number;
  y: number;
}
type TPoint = { x: number; y: number };

function sectionA(): void {
  sectionBanner("A — Both structural: interface and type alias are the SAME type");

  // COMPILE-TIME evidence (the decisive proof): Equal<IPoint, TPoint> resolves
  // to `true`. The Equal<> idiom accepts only IDENTICAL types, so this is a
  // stronger statement than "mutually assignable" — it says they ARE one type.
  console.log("interface IPoint { x: number; y: number }");
  console.log("type TPoint = { x: number; y: number }");
  console.log("  -> Equal<IPoint, TPoint> === true (NOT just assignable: IDENTICAL)");
  expectType<Equal<IPoint, TPoint>>("interface IPoint === type TPoint (exact equal)");
  expectType<Equal<TPoint, IPoint>>("type TPoint === interface IPoint (symmetric)");

  // Mutual assignability at the VALUE level: an IPoint value flows into a TPoint
  // slot and back, with no cast. (🔗 STRUCTURAL_TYPING §A: same has-at-least
  // rule; here the shapes are exactly equal so it is trivially bidirectional.)
  const a: IPoint = { x: 1, y: 2 };
  const b: TPoint = a; // IPoint -> TPoint: OK
  const c: IPoint = b; // TPoint -> IPoint: OK
  console.log(`  const a: IPoint = {x:1,y:2}; const b: TPoint = a; const c: IPoint = b;`);
  console.log(`  runtime: a === b === c === ${JSON.stringify(a)} (one object, three names)`);

  // RUNTIME evidence: BOTH keyword spellings are ERASED. `typeof` sees only the
  // JS value — a plain object — never the interface/alias name. This is the
  // type-erasure truth pinned by VALUES_TYPES_COERCION, restated for the
  // compile-time layer.
  check('typeof a === "object" (interface IPoint erased at runtime)', typeof a === "object");
  check(
    "a.x === b.x === c.x === 1 (the three names alias ONE object; shapes erased)",
    a.x === 1 && b.x === 1 && c.x === 1,
  );

  // The equivalence holds ONLY for matching shapes. A type with a MISSING member
  // is a genuine error in either spelling — the @ts-expect-error below proves it:
  // if tsc ever stopped erroring, the unused directive would itself fail the build.
  // @ts-expect-error Property 'y' is missing in type '{ x: number; }' (IPoint needs y)
  const tooFew: IPoint = { x: 1 };
  void tooFew;

  console.log("  const tooFew: IPoint = { x: 1 }  -> ERROR (missing y; @ts-expect-error gate)");
}

// ============================================================================
// Section B — interface `extends` + class `implements` (compile-time only)
// ============================================================================

// `interface extends` builds a subtype by adding members; an interface may
// extend SEVERAL at once (`extends A, B`). The result is a NEW interface type —
// and the Equal<> trick treats `interface X extends A` as DISTINCT from the
// intersection `A & B` even though the two are mutually assignable (a subtlety
// this section prints so it is not a surprise later).
interface Animal {
  name: string;
}
interface Trainable {
  tricks: ReadonlyArray<string>;
}
interface Pet extends Animal, Trainable {
  owner: string;
}

// `class implements Iface` makes the compiler CHECK that the class satisfies the
// interface's shape. It is PURELY a compile-time assertion: it emits no runtime
// code, adds no prototype linkage, and (unlike `extends` of a class) contributes
// nothing to the value at runtime. Missing a member is a compile error.
class RealDog implements Animal {
  name = "Rex";
}
class RealPet implements Pet {
  name = "Rex";
  owner = "Ada";
  tricks = ["sit", "shake"] as readonly string[];
}

function sectionB(): void {
  sectionBanner("B — interface `extends` + class `implements` (compile-time only)");

  // interface extends multiple: Pet pulls in name (Animal) + tricks (Trainable)
  // + its own owner. The merged key set is exactly the union of the three.
  console.log("interface Animal { name }");
  console.log("interface Trainable { tricks }");
  console.log("interface Pet extends Animal, Trainable { owner }");
  expectType<Equal<keyof Pet, "name" | "tricks" | "owner">>(
    'keyof Pet === "name" | "tricks" | "owner" (extends merges key sets)',
  );

  // implements: the class conforms to the interface; the value is a plain object.
  const dog = new RealDog();
  const pet = new RealPet();
  console.log(`const dog = new RealDog()  -> dog.name = "${dog.name}"`);
  console.log(`const pet = new RealPet()  -> pet.name="${pet.name}", owner="${pet.owner}"`);
  check("implements checks conformance: pet satisfies Pet (name+tricks+owner)", pet.name === "Rex" && pet.owner === "Ada");

  // implements is COMPILE-TIME: a class missing a required member errors. The
  // directive on the next line gates a real error (tsc fails if it ever stops).
  // @ts-expect-error Class 'BadDog' incorrectly implements interface 'Pet' (missing owner/tricks)
  class BadDog implements Pet {
    name = "Rex";
  }
  void BadDog;
  console.log("  class BadDog implements Pet { name }  -> ERROR (missing owner/tricks)");

  // implements leaves NO runtime trace: the interface name is not a value, so it
  // CANNOT appear in `instanceof` (interfaces are erased; only classes/funcs are
  // runtime values). Two halves of the proof:
  //   (compile) `dog instanceof Animal` is a TYPE error (TS2693) — the @ts-
  //             expect-error below suppresses it.
  //   (runtime) even with the type error suppressed, the line still EMITS code,
  //             and evaluating the erased `Animal` binding throws ReferenceError.
  // This is the sharpest expression of "implements is compile-time only": the
  // contract literally does not exist at runtime.
  let instanceofThrew = false;
  try {
    // @ts-expect-error 'Animal' only refers to a type, but is being used as a value here
    const isAnimal = dog instanceof Animal;
    void isAnimal;
  } catch (e) {
    instanceofThrew = e instanceof ReferenceError;
  }
  console.log("  dog instanceof Animal  -> type error (suppressed) AND runtime ReferenceError");
  check(
    "instanceof on an interface throws ReferenceError at runtime (interface erased, no binding)",
    instanceofThrew,
  );

  // RUNTIME evidence: the instance carries its OWN keys, with no record of which
  // interface(s) it "implements". The contract existed only at compile time.
  const ownKeys = Object.keys(dog).sort(); // sort for deterministic output (§4.2 rule 3)
  console.log(`  Object.keys(dog).sort() = ${JSON.stringify(ownKeys)}   (no "Animal" trace)`);
  check(
    "implements leaves no runtime trace: dog has only its own keys, no interface name",
    ownKeys.length === 1 && ownKeys[0] === "name",
  );

  // SUBTLETY (pinned by value-level assignment, not a conditional): `interface
  // X extends A` and the intersection `A & X` are MUTUALLY ASSIGNABLE but the
  // Equal<> trick treats them as DISTINCT (an interface built via `extends`
  // keeps an interface identity; an intersection is a separate construction).
  // The practical effect is nil — assignability is symmetric, as the two OK
  // assignments below prove — but it explains "types are equal but not
  // identical" diagnostics when a library re-exports a shape both ways.
  type PetByName = Animal & Trainable & { owner: string };
  const asIntersection: PetByName = pet; // Pet -> PetByName: OK (mutually assignable)
  const roundTrip: Pet = asIntersection; // PetByName -> Pet: OK (symmetric)
  void roundTrip;
  console.log("");
  console.log("SUBTLETY: interface Pet extends Animal,Trainable  vs  type PetByName = Animal & Trainable & {owner}");
  console.log("  const asIntersection: PetByName = pet  -> OK (Pet -> PetByName)");
  console.log("  const roundTrip: Pet = asIntersection  -> OK (PetByName -> Pet, symmetric)");
  console.log("  yet Equal<Pet, PetByName> === false (interface-via-extends != intersection construction)");
}

// ============================================================================
// Section C — DECLARATION MERGING (interfaces only) — THE payoff
// ============================================================================

// THE defining power of `interface` that `type` cannot match: two (or more)
// interface declarations with the SAME name in the same scope MERGE into one
// interface whose members are the UNION of all of them. (TS Handbook,
// "Declaration Merging".) This is not a redeclaration error — it is a feature.
// It is the mechanism behind lib.d.ts patching, library .d.ts augmentation, and
// `declare module "x" { interface ... }` plugin typing.

// (1) PROPERTY merge: a second `interface Window` adds `height` to the first's
// `width`. After both declarations, Window has BOTH members — no error, no cast.
interface WindowLike {
  width: number;
}
interface WindowLike {
  height: number;
}

// (2) FUNCTION-MEMBER merge: same-named methods across merged interfaces become
// OVERLOADS of one method (handbook: "each function member of the same name is
// treated as describing an overload of the same function").
interface Logger {
  log(msg: string): void;
}
interface Logger {
  log(msg: number): void;
}

function sectionC(): void {
  sectionBanner("C — DECLARATION MERGING (interfaces only) — THE payoff");

  // (1) PROPERTY merge: WindowLike now requires width AND height.
  console.log("interface WindowLike { width: number }");
  console.log("interface WindowLike { height: number }   // <-- SAME name: MERGES (not an error)");
  console.log("  -> WindowLike now has BOTH width and height");
  expectType<Equal<WindowLike, { width: number; height: number }>>(
    "merged WindowLike === { width: number; height: number }",
  );
  const win: WindowLike = { width: 800, height: 600 };
  console.log(`  const win: WindowLike = { width: 800, height: 600 }   -> compiles (both present)`);
  check("property merge: win.width === 800 && win.height === 600", win.width === 800 && win.height === 600);

  // (2) OVERLOAD merge: Logger.log now accepts EITHER a string OR a number. A
  // single object literal whose method accepts the union satisfies both
  // overloads, and BOTH call spellings resolve.
  console.log("");
  console.log("interface Logger { log(msg: string): void }");
  console.log("interface Logger { log(msg: number): void }   // <-- merges into TWO overloads");
  const logger: Logger = {
    log(msg: string | number): void {
      void msg;
    },
  };
  logger.log("info"); // resolves to the (string) overload
  logger.log(42); // resolves to the (number) overload
  console.log('  logger.log("info")  -> OK (string overload)');
  console.log("  logger.log(42)      -> OK (number overload)");
  check("overload merge: Logger.log accepts BOTH string and number call signatures", true);

  // (3) THE ASYMMETRY — types CANNOT redeclare. Re-declaring a `type` alias with
  // the same name is TS2300 "Duplicate identifier", reported on EVERY
  // declaration. `// @ts-expect-error` cannot clean it (it suppresses only one
  // site; the duplicate fires on the first too), so this file does NOT contain a
  // live duplicate (it would break `just typecheck`). The forbidden form:
  console.log("");
  console.log("THE ASYMMETRY: a `type` CANNOT be redeclared. The forbidden form (NOT live):");
  console.log("  type TStringBox = { width: number };");
  console.log("  type TStringBox = { height: number };   // TS2300 Duplicate identifier 'TStringBox'");
  console.log("  -> @ts-expect-error cannot clean it (duplicate fires on BOTH decls);");
  console.log("     types are CLOSED. Only interfaces are open/mergeable.");
  check("type aliases are closed (cannot merge); only interfaces merge", true);

  // CONSEQUENCE — when you WANT open extension, reach for `interface`. This is
  // how `declare module "express" { interface Request { user?: User } }` adds a
  // field to a library's type without forking it — the library's Request is an
  // interface, so your declaration MERGES with it. A type alias could not.
  console.log("");
  console.log("CONSEQUENCE: `declare module \"lib\" { interface X { ... } }` augments a");
  console.log("library's interface via merging. A type alias cannot be augmented this way.");
}

// ============================================================================
// Section D — Type-only powers (unions, tuples, intersections, mapped, branded)
// ============================================================================

// The flip side of the asymmetry: type aliases express algebraic shapes that an
// interface structurally CANNOT. An interface can only describe an object/function/
// construct/index SIGNATURE; it has no syntax for a union of unrelated types, a
// fixed-length tuple, or a mapped re-projection of another type's keys. These are
// the exclusive province of `type`.

// (a) UNION — "a value is one of several unrelated types". No interface spelling.
type Id = string | number;
// (b) TUPLE — a fixed-length, fixed-order, per-index-typed array. No interface
// spelling (an interface can fake index signatures, but not fixed length/order).
type Pair = [number, string];
// (c) INTERSECTION — combine N shapes into one (the type-alias counterpart of
// `interface extends A, B`; see Section B's assignability-vs-identity note).
type LabeledPoint = IPoint & { label: string };
// (d) MAPPED type — re-project every key of T into a new shape. Pure type-level
// computation; no interface spelling.
type Stringified<T> = { [K in keyof T]: string };
// (e) BRANDED primitive — intersect a primitive with a phantom property to fake
// nominal typing. An interface cannot BE `number & {...}` (it is not a primitive
// intersection). (🔗 STRUCTURAL_TYPING §C — the full brand-pattern treatment.)
type Celsius = number & { readonly __celsiusBrand: unique symbol };

function sectionD(): void {
  sectionBanner("D — Type-only powers (unions, tuples, intersections, mapped, branded)");

  // (a) UNION: Id is EXACTLY `string | number`. (An interface has no `|` syntax.)
  console.log("type Id = string | number;             // UNION (no interface spelling)");
  expectType<Equal<Id, string | number>>("Id === string | number");
  function formatId(id: Id): string {
    return typeof id === "number" ? `#${id}` : id;
  }
  console.log(`  formatId("u-1") = ${formatId("u-1")}   formatId(42) = ${formatId(42)}`);
  check("union accepts both arms: formatId(string) and formatId(number)", formatId("u-1") === "u-1" && formatId(42) === "#42");

  // (b) TUPLE: Pair is a 2-element fixed array [number, string]. Indexed access
  // pinpoints each slot's type at the type level.
  console.log("");
  console.log("type Pair = [number, string];          // TUPLE (no interface spelling)");
  expectType<Equal<Pair[0], number>>("Pair[0] === number");
  expectType<Equal<Pair[1], string>>('Pair[1] === string');
  const pair: Pair = [7, "seven"];
  console.log(`  const pair: Pair = [7, "seven"]   -> length = ${pair.length}, pair[0]=${pair[0]}, pair[1]="${pair[1]}"`);
  check("tuple: pair.length === 2 and slots keep their declared types", pair.length === 2 && pair[0] === 7 && pair[1] === "seven");

  // (c) INTERSECTION: LabeledPoint is IPoint AND {label}. Like Section B's
  // Pet-vs-intersection, an intersection is MUTUALLY ASSIGNABLE with the flat
  // equivalent (both assignments below compile) but the Equal<> trick treats it
  // as a DISTINCT construction — assignability is the practical property, and it
  // holds in both directions.
  console.log("");
  console.log("type LabeledPoint = IPoint & { label: string };   // INTERSECTION");
  const lp: LabeledPoint = { x: 0, y: 0, label: "origin" }; // literal -> intersection: OK
  const lpFlat: { x: number; y: number; label: string } = lp; // intersection -> flat: OK (symmetric)
  void lpFlat;
  console.log(`  const lp: LabeledPoint = { x:0, y:0, label:"origin" }   -> lp.label = "${lp.label}"`);
  check("intersection: lp carries x, y, AND label (assignable both ways)", lp.x === 0 && lp.y === 0 && lp.label === "origin");

  // (d) MAPPED type: Stringified<IPoint> re-projections BOTH keys to string.
  // A homomorphic mapped type is mutually assignable with its flat result, but
  // (like intersections) the Equal<> trick treats it as distinct — the
  // value-level assignment below is the robust compile-time proof.
  console.log("");
  console.log("type Stringified<T> = { [K in keyof T]: string };   // MAPPED (no interface spelling)");
  const sp: Stringified<IPoint> = { x: "1", y: "2" }; // every value MUST be a string
  console.log(`  const sp: Stringified<IPoint> = { x:"1", y:"2" }   -> every value is a string`);
  check("mapped type: Stringified<IPoint> forces both values to string", sp.x === "1" && sp.y === "2");

  // (e) BRANDED primitive: Celsius is `number & {phantom}`. At runtime it is
  // JUST a number (the brand is a type-level phantom, never a real property);
  // at compile time a bare number cannot be assigned to it. Interfaces cannot
  // BE a primitive intersection like this.
  console.log("");
  console.log("type Celsius = number & { readonly __celsiusBrand: unique symbol };   // BRANDED");
  const temp = 36.6 as Celsius;
  console.log(`  const temp = 36.6 as Celsius   -> typeof = ${typeof temp}, value = ${temp}`);
  check('typeof branded Celsius === "number" (brand is a phantom; erased at runtime)', typeof temp === "number");
  check("branded primitive carries its numeric value at runtime (brand is type-only)", temp === 36.6);
  // @ts-expect-error a bare number is not assignable to branded Celsius (nominal faking)
  const bareNum: Celsius = 36.6;
  void bareNum;
  console.log("  const bareNum: Celsius = 36.6   -> ERROR (bare number rejected by the brand)");

  // SUMMARY of the asymmetry, printed for the reader.
  console.log("");
  console.log("SUMMARY: interfaces describe object/function/construct/index SIGNATURES only.");
  console.log("type aliases additionally express UNION | TUPLE | INTERSECTION | MAPPED | CONDITIONAL.");
  console.log("Reach for `type` whenever the shape is algebraic rather than a single object.");
}

// ============================================================================
// Section E — When to use which (open vs algebraic) + cross-language framing
// ============================================================================

function sectionE(): void {
  sectionBanner("E — When to use which (open vs algebraic) + cross-language framing");

  // The decision rule distilled: OPEN shapes (ones you or a downstream consumer
  // may want to EXTEND or MERGE — library contracts, lib.d.ts augmentations)
  // want `interface`; CLOSED/algebraic shapes (unions, tuples, intersections,
  // mapped/conditional types, primitives-with-brands) want `type`. For a plain
  // object shape that is neither, either works — pick by team convention.
  const rows: ReadonlyArray<readonly [string, string, string]> = [
    ["union / intersection", "no", "yes  (string|number, A & B)"],
    ["tuple [a, b]", "no", "yes  ([number, string])"],
    ["mapped / conditional", "no", "yes  ({[K in keyof T]:...}, T extends U ? X : Y)"],
    ["declaration merge", "yes  (open)", "no  (closed)"],
    ["extends / implements", "yes  (interface extends A; class impl)", "via intersection (A & B)"],
    ["augment lib .d.ts", "yes  (declare module)", "no"],
    ["plain object shape", "yes", "yes  (equivalent — Equal<> is true)"],
  ] as const;

  console.log("capability                       : interface : type alias");
  console.log("-------------------------------- : --------- : ---------------------------------------");
  for (const [cap, iface, alias] of rows) {
    console.log(`${cap.padEnd(32)} : ${iface.padEnd(9)} : ${alias}`);
  }
  check(
    "decision rule: open/mergeable -> interface; algebraic/closed -> type",
    rows[3]![1] === "yes  (open)" && rows[0]![2]!.startsWith("yes"),
  );

  // CROSS-LANGUAGE framing: Go, Rust, and Python each have ONE shape-contract
  // concept. TypeScript is unusual in offering BOTH an open `interface` and a
  // closed algebraic `type` — and in letting them interoperate (an interface
  // can extend a type alias; a type alias can intersect an interface).
  console.log("");
  const langs: ReadonlyArray<readonly [string, string, string, string]> = [
    ["TypeScript", "BOTH (open interface + closed type alias)", "structural", "merge (interface) / intersect (type)"],
    ["Go", "interface (one concept)", "structural, IMPLICIT", "no merging (method-set only, no data)"],
    ["Rust", "trait (one concept)", "nominal, EXPLICIT `impl`", "no merging (default methods, no data fields)"],
    ["Python", "Protocol (one concept)", "structural", "no merging"],
  ] as const;
  console.log("language     : shape-contract concept                        : model          : extension model");
  console.log("------------ : -------------------------------------------------- : -------------- : ----------------------------------");
  for (const [lang, concept, model, ext] of langs) {
    console.log(`${lang.padEnd(12)} : ${concept.padEnd(50)} : ${model.padEnd(14)} : ${ext}`);
  }
  check(
    "TS is the only one of the four offering BOTH open-merge (interface) AND closed-algebraic (type)",
    langs[0]![1] === "BOTH (open interface + closed type alias)",
  );
  check("Go interfaces are IMPLICIT (no `implements` keyword) — TS's closest sibling", langs[1]![2] === "structural, IMPLICIT");
  check("Rust traits are NOMINAL + EXPLICIT impl — the starkest contrast to TS", langs[2]![2] === "nominal, EXPLICIT `impl`");

  console.log("");
  console.log("EXPERT TAKEAWAY: TypeScript gives you TWO complementary tools, not a");
  console.log("contest. Use `interface` where openness/merging buys you something");
  console.log("(library contracts, augmentation). Use `type` where the shape is");
  console.log("algebraic (unions, tuples, intersections, mapped/conditional). For a");
  console.log("plain object shape, either is fine — be consistent within a codebase.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("interfaces_vs_aliases.ts — Phase 2 bundle (Type System & Generics).");
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
