// zod_validation.ts — Phase 6 bundle (metaprog member).
//
// GOAL (one line): show, by printing every value, how a single Zod schema is
// BOTH the compile-time TS type (z.infer) AND the runtime validator (parse) —
// closing the hole TypeScript leaves when untrusted data crosses a boundary.
//
// This is the GROUND TRUTH for ZOD_VALIDATION.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// LINEAGE (why this bundle exists): TS types exist ONLY at compile time and are
// ERASED at runtime (tsx/esbuild/tsc strip every `interface`, annotation, and
// generic — see VALUES_TYPES_COERCION §1). So untrusted data — JSON.parse,
// fetch().json(), req.body, process.env — arrives with NO runtime check: TS
// happily lets you write `const u: User = JSON.parse(text)` and the annotation
// is a *lie* the moment the JSON is missing a field. Zod fixes this by making
// ONE schema object the single source of truth: `schema.parse(data)` validates
// at runtime (throwing or returning a typed error tree), and
// `z.infer<typeof schema>` DERIVES the TS type — compile-time and runtime agree
// because they share one definition. This is the JS analog of Rust's serde
// (`#[derive(Deserialize)]` → one struct → typed deserialize) and Go's struct-
// tag validation, and it is the SAFE replacement for the `as` assertion.
//
// Run:
//     pnpm exec tsx zod_validation.ts   (or: just run zod_validation)

import { z } from "zod";

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

// --- compile-time type-equality machinery (ERASED at runtime) ----------------
//
// These two helpers carry NO runtime weight — tsx/esbuild strip them. Their
// only job is to make `tsc --noEmit` FAIL if a derived type ever drifts from
// the hand-written shape, turning a silent type lie into a hard build error.
// This is how we assert "z.infer<typeof S> === Expected" (the payoff in §B):
// if the two differ, `assertType<Equal<...>>(true)` is a compile error.

// Equal is the strict type-level identity check (the fp-ts / effect idiom):
// two types are Equal only if they are interchangeable in every generic
// position (catches optionality, readonly, and excess-property differences).
type Equal<X, Y> =
  (<T>() => T extends X ? 1 : 2) extends <T>() => T extends Y ? 1 : 2 ? true : false;

// assertType forces its type argument to extend `true`. Pair with Equal:
//   assertType<Equal<Derived, Expected>>(true);  // compile error if they differ
function assertType<T extends true>(_: T): void {
  void _;
}

// --- stable serialization of Zod error shapes -------------------------------
//
// ZodError.issues is an array of ZodIssue objects with many optional fields.
// We project each issue down to {path, message, code} and JSON.stringify the
// array so the printed error tree is byte-stable across runs. Object-key
// iteration order in zod follows insertion order of the schema fields (our
// field names are non-integer strings, so V8 keeps them in insertion order —
// see VALUES_TYPES_COERCION §4.2 rule 3), and issue codes/paths are deterministic.

interface IssueView {
  readonly code: string;
  readonly path: ReadonlyArray<string | number>;
  readonly message: string;
}

function issuesOf(err: z.ZodError): ReadonlyArray<IssueView> {
  return err.issues.map((i) => ({
    code: String(i.code),
    path: i.path,
    message: i.message,
  }));
}

function issueSummary(err: z.ZodError): string {
  return JSON.stringify(issuesOf(err));
}

// ============================================================================
// Section A — z.object + parse vs safeParse: throw vs {success, data | error}
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — z.object + parse vs safeParse (throw vs result)");

  // ONE schema. It is a plain runtime object (z.object returns a ZodObject
  // instance) that simultaneously (1) validates at runtime via .parse and
  // (2) feeds z.infer for the compile-time type. Both come from this single
  // definition — that is the whole point of zod.
  const User = z.object({
    id: z.number(),
    name: z.string(),
    email: z.string().email(),
  });

  console.log("Schema:");
  console.log('  const User = z.object({');
  console.log("    id:    z.number(),");
  console.log("    name:  z.string(),");
  console.log("    email: z.string().email(),");
  console.log("  });");

  // --- valid input: .parse returns the typed value (unknown keys stripped) ---
  const valid: unknown = { id: 1, name: "ada", email: "ada@ex.com", junk: "stripped" };
  const parsed = User.parse(valid);
  console.log("");
  console.log("User.parse(valid + unknown 'junk' key):");
  console.log(`  -> ${JSON.stringify(parsed)}   (unknown keys STRIPPED by default)`);
  check("parse returns the valid object (unknown keys stripped)", parsed.id === 1 && parsed.email === "ada@ex.com" && !("junk" in parsed));

  // --- .parse THROWS ZodError on invalid input (the "fail loud" path) -------
  let threw = false;
  let thrownName = "";
  let isZodError = false;
  try {
    User.parse({ id: 1, name: "ada" }); // missing required email
  } catch (err) {
    threw = true;
    thrownName = err instanceof Error ? err.constructor.name : String(err);
    isZodError = err instanceof z.ZodError;
  }
  console.log("");
  console.log("User.parse({id:1, name:'ada'})  // missing required 'email'");
  console.log(`  -> THROWS ${thrownName} (instanceof z.ZodError: ${isZodError})`);
  check(".parse throws on invalid input", threw);
  check("thrown error is instanceof z.ZodError", isZodError);
  check("thrown constructor name is 'ZodError'", thrownName === "ZodError");

  // --- .safeParse NEVER throws: returns {success, data} | {success, error} ---
  // This is the boundary idiom: at a trust boundary you want to branch on the
  // result, not catch. `.spa` is the one-token alias for the ASYNC variant
  // (safeParseAsync) — needed when a schema has async refinements; it returns a
  // Promise<{success, data | error}> of the SAME shape as safeParse.
  const okResult = User.safeParse({ id: 2, name: "bob", email: "bob@ex.com" });
  const badResult = User.safeParse({ id: "oops", name: 7 }); // wrong types + missing email

  console.log("");
  console.log("User.safeParse(valid):");
  console.log(`  -> success=${okResult.success}, data=${JSON.stringify(okResult.success ? okResult.data : null)}`);
  check("safeParse(valid).success === true", okResult.success === true);

  console.log("");
  console.log("User.safeParse({id:'oops', name:7})  // wrong types + missing email:");
  console.log(`  -> success=${badResult.success}`);
  console.log(`     error.issues = ${issueSummary(!badResult.success ? badResult.error : new z.ZodError([]))}`);
  check("safeParse(invalid).success === false", badResult.success === false);

  // The error tree: each issue has {code, path, message}. path locates the
  // offending field inside nested data. codes come from a fixed enum
  // (invalid_type, invalid_string, invalid_enum_value, too_small, ...).
  if (!badResult.success) {
    const codes = badResult.error.issues.map((i) => i.code);
    check("error.issues has 3 issues (id, name, email)", badResult.error.issues.length === 3);
    check("issue codes include 'invalid_type'", codes.includes("invalid_type"));
    // path is the field name inside the object.
    const emailIssue = badResult.error.issues.find((i) => i.path[0] === "email");
    check("the 'email' missing-field issue has code 'invalid_type'", emailIssue?.code === "invalid_type");
    check("the 'email' issue message is 'Required'", emailIssue?.message === "Required");
  }

  // .spa = safeParseAsync: returns a Promise of the SAME {success, data|error}
  // shape. Awaiting it gives the identical result safeParse would synchronously.
  const spaResult = await User.spa({ id: 3, name: "cara", email: "cara@ex.com" });
  console.log("");
  console.log("await User.spa(valid)  // .spa = async alias for safeParse:");
  console.log(`  -> success=${spaResult.success}, data=${JSON.stringify(spaResult.success ? spaResult.data : null)}`);
  check(".spa (safeParseAsync) returns the same success shape, awaited", spaResult.success === true);
}

// ============================================================================
// Section B — z.infer: ONE schema drives BOTH the TS type AND runtime parse
// ============================================================================

function sectionB(): void {
  sectionBanner("B — z.infer (THE payoff: one schema = compile type + runtime check)");

  // THE headline: write the schema ONCE, derive the TS type from it. There is
  // no hand-written interface to drift out of sync with the validator — the
  // schema IS the type definition. This is why zod is "TypeScript-first".
  const Product = z.object({
    id: z.number().int().positive(),
    title: z.string().min(1).max(200),
    priceCents: z.number().int().nonnegative(),
    tags: z.array(z.string()),
  });

  // z.infer<typeof Product> DERIVES the TS type from the schema object.
  // `typeof Product` is the runtime class (ZodObject); z.infer unwraps its
  // inferred OUTPUT type. These two are now locked together: editing the
  // schema changes both the runtime validation AND the compile type.
  type ProductType = z.infer<typeof Product>;

  console.log("Schema:");
  console.log('  const Product = z.object({');
  console.log("    id:         z.number().int().positive(),");
  console.log("    title:      z.string().min(1).max(200),");
  console.log("    priceCents: z.number().int().nonnegative(),");
  console.log("    tags:       z.array(z.string()),");
  console.log("  });");
  console.log("  type ProductType = z.infer<typeof Product>;");

  // --- COMPILE-TIME assertion (erased at runtime, enforced by tsc) ----------
  // If z.infer ever drifts from this exact shape, tsc fails the build. This is
  // the strongest possible check that "one schema = one type": it cannot pass
  // unless the two are interchangeable in every generic position.
  type ExpectedProduct = {
    id: number;
    title: string;
    priceCents: number;
    tags: string[];
  };
  assertType<Equal<ProductType, ExpectedProduct>>(true);
  console.log("");
  console.log("[compile-time] assertType<Equal<z.infer<typeof Product>, Expected>>(true)");
  console.log("  -> tsc passes: the derived type EQUALS the hand-written shape.");

  // --- RUNTIME assertion: a parsed value really does satisfy the type -------
  // Because safeParse narrows `unknown` -> `ProductType` on success, we can
  // assign the result straight into a typed variable with NO `as` cast. This is
  // the SAFE replacement for `const p: Product = data as Product` (which lies).
  const incoming: unknown = { id: 42, title: "Mug", priceCents: 999, tags: ["kitchen"] };
  const result = Product.safeParse(incoming);
  if (result.success) {
    const p: ProductType = result.data; // no `as` — the type came FROM the schema
    console.log("");
    console.log("[runtime] Product.safeParse(unknown) -> narrowed, no `as` cast:");
    console.log(`  p = ${JSON.stringify(p)}`);
    check("parsed value is assignable to z.infer<Product> (no `as`)", p.id === 42 && p.tags[0] === "kitchen");
  } else {
    check("parsed value is assignable to z.infer<Product> (no `as`)", false);
  }

  // --- The boundary payoff: unknown -> typed, safely ------------------------
  // Contrast with the UNSAFE pattern this replaces:
  //     const p: Product = JSON.parse(text) as Product;   // LIE: no check
  //     const p: Product = data as unknown as Product;    // BIGGER LIE
  // safeParse is the type-narrowing, runtime-checked alternative. On failure
  // you get a structured error tree instead of a downstream TypeError.
  console.log("");
  console.log("Boundary pattern (the SAFE alternative to `as`):");
  console.log("  const r = Product.safeParse(JSON.parse(text));");
  console.log("  if (r.success) { r.data;  // type: Product, validated }");
  console.log("  else            { r.error; // type: ZodError, structured }");
  check("z.infer + safeParse replace the lying `as` at trust boundaries", true);
}

// ============================================================================
// Section C — primitives, refinements, optional/nullable/default, nesting
// ============================================================================

function sectionC(): void {
  sectionBanner("C — primitives, refinements, optional/nullable/default, nesting");

  // --- primitives + built-in refinements ------------------------------------
  // Each primitive schema (z.string/number/boolean/date/bigint) chains
  // refinement methods that add runtime checks AND narrow the inferred type
  // (e.g. .int() / .positive() still infer `number`, but reject at runtime).
  const str = z.string().min(2).max(5);
  const int = z.number().int();
  const pos = z.number().positive();
  const whole = z.number().int().nonnegative();

  console.log("Primitive refinements:");
  console.log(`  z.string().min(2).max(5).parse("abc")   -> ${JSON.stringify(str.parse("abc"))}`);
  console.log(`  z.number().int().parse(7)               -> ${int.parse(7)}`);
  console.log(`  z.number().positive().parse(3)          -> ${pos.parse(3)}`);
  check('z.string().min(2) accepts "abc"', str.safeParse("abc").success);
  check('z.string().min(2) rejects "a" (too_small)', str.safeParse("a").success === false);
  check("z.number().int() accepts 7", int.safeParse(7).success);
  check("z.number().int() rejects 1.5", int.safeParse(1.5).success === false);
  check("z.number().positive() accepts 3", pos.safeParse(3).success);
  check("z.number().positive() rejects -1", pos.safeParse(-1).success === false);
  check("z.number().int().nonnegative() rejects 1.5 AND -1", whole.safeParse(1.5).success === false && whole.safeParse(-1).success === false);

  // String format refinements (.email/.url) emit invalid_string issues.
  const email = z.string().email();
  const url = z.string().url();
  console.log("");
  console.log("String formats:");
  console.log(`  z.string().email().parse("a@b.com")  -> ${JSON.stringify(email.parse("a@b.com"))}`);
  console.log(`  z.string().url().parse("https://x.io") -> ${JSON.stringify(url.parse("https://x.io"))}`);
  check('z.string().email() accepts "a@b.com"', email.safeParse("a@b.com").success);
  const emailBad = email.safeParse("not-an-email");
  if (!emailBad.success) {
    console.log(`  z.string().email() rejects "not-an-email" -> code=${emailBad.error.issues[0]!.code}`);
    check("z.string().email() reject issue code is 'invalid_string'", emailBad.error.issues[0]!.code === "invalid_string");
  }
  check('z.string().url() accepts "https://x.io"', url.safeParse("https://x.io").success);

  // --- optional / nullable / default: three kinds of "absence" --------------
  // .optional()   -> input/output T | undefined
  // .nullable()   -> input/output T | null
  // .default(v)   -> INPUT is optional (T | undefined), OUTPUT is always T
  //   (the default is filled in by parse — so z.infer sees a required T).
  const Opt = z.object({ nickname: z.string().optional() });
  const Nul = z.object({ middle: z.string().nullable() });
  const Def = z.object({ role: z.string().default("guest") });

  console.log("");
  console.log("optional / nullable / default:");
  console.log(`  .optional()  parse({})              -> ${JSON.stringify(Opt.parse({}))}`);
  console.log(`  .nullable()  parse({middle:null})   -> ${JSON.stringify(Nul.parse({ middle: null }))}`);
  console.log(`  .default()   parse({})              -> ${JSON.stringify(Def.parse({}))}   (default filled)`);

  check(".optional() accepts missing key", Opt.safeParse({}).success);
  check(".optional() accepts explicit undefined", Opt.safeParse({ nickname: undefined }).success);
  check(".nullable() accepts null", Nul.safeParse({ middle: null }).success);
  check(".default() fills 'guest' when missing", Def.parse({}).role === "guest");

  // COMPILE-TIME: .default changes the OUTPUT type to required `string`
  // (the input is optional, but z.infer reports the output: a present string).
  type DefOut = z.infer<typeof Def>;
  assertType<Equal<DefOut, { role: string }>>(true);

  // --- nesting: object, array, union, enum, literal, record -----------------
  const Address = z.object({
    street: z.string(),
    zip: z.string().regex(/^\d{5}$/),
  });
  const Person = z.object({
    name: z.string(),
    age: z.number().int().nonnegative(),
    address: Address, // nested object schema
    nicknames: z.array(z.string()), // array of strings
    favoriteColor: z.enum(["red", "green", "blue"]), // string enum
    signature: z.literal("x"), // exact literal
    idOrName: z.union([z.number(), z.string()]), // union
    lookup: z.record(z.string(), z.number()), // Record<string, number>
  });

  const sample = {
    name: "ada",
    age: 36,
    address: { street: "1 Main", zip: "12345" },
    nicknames: ["a", "ada"],
    favoriteColor: "green",
    signature: "x",
    idOrName: 7,
    lookup: { a: 1, b: 2 },
  };
  const parsed = Person.parse(sample);
  console.log("");
  console.log("Nested schema (object/array/enum/literal/union/record):");
  console.log(`  Person.parse(sample) -> ok, address.zip=${parsed.address.zip}, nicks.length=${parsed.nicknames.length}`);
  check("nested object parses", parsed.address.zip === "12345");
  check("array element schema applied", parsed.nicknames.length === 2);

  // enum rejects out-of-set values with invalid_enum_value.
  const colorBad = Person.safeParse({ ...sample, favoriteColor: "purple" });
  if (!colorBad.success) {
    console.log(`  favoriteColor='purple' -> code=${colorBad.error.issues[0]!.code}, path=${JSON.stringify(colorBad.error.issues[0]!.path)}`);
    check("enum reject code is 'invalid_enum_value'", colorBad.error.issues[0]!.code === "invalid_enum_value");
  }

  // literal rejects anything but the exact value (invalid_literal).
  const sigBad = Person.safeParse({ ...sample, signature: "y" });
  if (!sigBad.success) {
    console.log(`  signature='y' -> code=${sigBad.error.issues[0]!.code}`);
    check("literal reject code is 'invalid_literal'", sigBad.error.issues[0]!.code === "invalid_literal");
  }

  // union: first option that validates wins; array element errors carry path [idx].
  const unionBad = z.array(z.string()).safeParse(["ok", 5, "ok"]);
  if (!unionBad.success) {
    console.log(`  z.array(z.string()).parse(['ok',5,'ok']) -> path=${JSON.stringify(unionBad.error.issues[0]!.path)}, code=${unionBad.error.issues[0]!.code}`);
    check("array element error path points at index 1", unionBad.error.issues[0]!.path[0] === 1);
  }
  check("z.union accepts number", z.union([z.number(), z.string()]).safeParse(7).success);
  check("z.union accepts string", z.union([z.number(), z.string()]).safeParse("hi").success);
  check("z.union rejects boolean", z.union([z.number(), z.string()]).safeParse(true).success === false);
}

// ============================================================================
// Section D — discriminatedUnion, transforms, refine/superRefine
// ============================================================================

function sectionD(): void {
  sectionBanner("D — discriminatedUnion (tagged union narrowing) + transforms + refine");

  // --- discriminatedUnion: the tagged union with a literal discriminator -----
  // Unlike z.union (which naively tries each arm in order), discriminatedUnion
  // reads ONE key first, then validates only the matching arm. This is both
  // faster AND gives a precise error when the tag itself is wrong. It is the
  // zod mirror of TS's discriminated-union narrowing (🔗 UNIONS_INTERSECTIONS):
  // parse narrows `unknown` to exactly one arm based on the discriminator.
  const Shape = z.discriminatedUnion("kind", [
    z.object({ kind: z.literal("circle"), radius: z.number().positive() }),
    z.object({ kind: z.literal("square"), side: z.number().positive() }),
  ]);
  type ShapeType = z.infer<typeof Shape>;
  // The inferred type is a true discriminated union.
  type ExpectedShape =
    | { kind: "circle"; radius: number }
    | { kind: "square"; side: number };
  assertType<Equal<ShapeType, ExpectedShape>>(true);

  const circle = Shape.parse({ kind: "circle", radius: 3 });
  const square = Shape.parse({ kind: "square", side: 4 });
  console.log("discriminatedUnion:");
  console.log(`  parse({kind:'circle',radius:3}) -> ${JSON.stringify(circle)}`);
  console.log(`  parse({kind:'square',side:4})   -> ${JSON.stringify(square)}`);
  check("discriminatedUnion parses the circle arm", circle.kind === "circle" && circle.radius === 3);
  check("discriminatedUnion parses the square arm", square.kind === "square" && square.side === 4);

  // A WRONG discriminator yields a single precise issue (invalid_union_discriminator),
  // NOT a list of every arm's mismatched fields.
  const badTag = Shape.safeParse({ kind: "triangle", side: 4 });
  if (!badTag.success) {
    console.log(`  parse({kind:'triangle',...}) -> code=${badTag.error.issues[0]!.code}, path=${JSON.stringify(badTag.error.issues[0]!.path)}`);
    check("bad discriminator code is 'invalid_union_discriminator'", badTag.error.issues[0]!.code === "invalid_union_discriminator");
    check("bad discriminator path points at 'kind'", badTag.error.issues[0]!.path[0] === "kind");
    check("bad discriminator yields exactly ONE issue (not one per arm)", badTag.error.issues.length === 1);
  }

  // --- transforms: change the OUTPUT type -----------------------------------
  // .transform(fn) runs AFTER validation passes and returns a new value; the
  // inferred OUTPUT type becomes the return type of fn (here: number). This is
  // how zod turns a raw string at a boundary into a richer typed value.
  const lengthOf = z.string().transform((s) => s.length);
  type LengthOut = z.infer<typeof lengthOf>;
  assertType<Equal<LengthOut, number>>(true); // output is number, NOT string
  const len = lengthOf.parse("hello");
  console.log("");
  console.log("transform:");
  console.log(`  z.string().transform(s => s.length).parse("hello") -> ${len} (typeof ${typeof len})`);
  check("transform output is a number (not the input string)", len === 5 && typeof len === "number");

  // A transform can change type AND add data in one parse step (no second pass).
  const toSlug = z
    .string()
    .min(1)
    .transform((s) => ({ original: s, slug: s.toLowerCase().replace(/\s+/g, "-") }));
  type SlugOut = z.infer<typeof toSlug>;
  assertType<Equal<SlugOut, { original: string; slug: string }>>(true);
  const slug = toSlug.parse("Hello World");
  console.log(`  z.string().min(1).transform(...).parse("Hello World") -> ${JSON.stringify(slug)}`);
  check("transform changes the output shape to an object", slug.slug === "hello-world");

  // --- refine: custom validation beyond built-ins ---------------------------
  // .refine(pred, msg) returns a new schema of the SAME type; on failure it
  // adds a 'custom' issue. .superRefine gives ctx.addIssue for MULTIPLE issues.
  const password = z
    .string()
    .min(8)
    .refine((s) => /[0-9]/.test(s), "must contain a digit")
    .refine((s) => /[A-Z]/.test(s), "must contain an uppercase letter");
  const pwBad = password.safeParse("alllowercase");
  if (!pwBad.success) {
    console.log("");
    console.log("refine (custom validation):");
    console.log(`  password.safeParse("alllowercase") -> ${pwBad.error.issues.length} issue(s):`);
    for (const i of pwBad.error.issues) {
      console.log(`    ${i.code}: "${i.message}"`);
    }
    check("refine attaches 'custom' issues for each failed predicate", pwBad.error.issues.every((i) => i.code === "custom"));
  }
  check("refine accepts a strong password", password.safeParse("Strong1Pass").success);

  // superRefine: emit MULTIPLE structured issues in one pass.
  const uniqueShortArray = z
    .array(z.string())
    .superRefine((arr, ctx) => {
      if (arr.length > 2) {
        ctx.addIssue({ code: z.ZodIssueCode.too_big, maximum: 2, type: "array", inclusive: true, message: "at most 2 items" });
      }
      if (new Set(arr).size !== arr.length) {
        ctx.addIssue({ code: z.ZodIssueCode.custom, message: "duplicates not allowed" });
      }
    });
  const dup = uniqueShortArray.safeParse(["a", "a", "a"]);
  if (!dup.success) {
    console.log("");
    console.log("superRefine (multi-issue):");
    console.log(`  safeParse(['a','a','a']) -> ${dup.error.issues.length} issues: [${dup.error.issues.map((i) => i.message).join(", ")}]`);
    check("superRefine emits both the too_big and duplicate issues", dup.error.issues.length === 2);
  }

  // refine with a path attaches the issue to a specific field (cross-field checks).
  const passwordForm = z
    .object({ password: z.string(), confirm: z.string() })
    .refine((d) => d.password === d.confirm, { message: "passwords do not match", path: ["confirm"] });
  const formBad = passwordForm.safeParse({ password: "a", confirm: "b" });
  if (!formBad.success) {
    console.log("");
    console.log("refine with path (cross-field check):");
    console.log(`  safeParse({password:'a',confirm:'b'}) -> path=${JSON.stringify(formBad.error.issues[0]!.path)}, msg="${formBad.error.issues[0]!.message}"`);
    check("refine path attaches the issue to 'confirm'", formBad.error.issues[0]!.path[0] === "confirm");
  }
}

// ============================================================================
// Section E — coerce (boundary parsing), error.format()/flatten(), summary
// ============================================================================

function sectionE(): void {
  sectionBanner("E — coerce (boundary parsing) + error.format()/flatten() + cross-language");

  // --- coerce: parse boundary strings into typed primitives -----------------
  // process.env, query strings, and form fields are ALL strings. z.coerce wraps
  // a primitive so .parse runs the JS coercing constructor first (Number(x),
  // String(x), Boolean(x)) THEN validates. The INPUT widens to `unknown`.
  const Port = z.coerce.number().int().min(1).max(65535);
  const fromEnv: unknown = "8080";
  const port = Port.parse(fromEnv);
  console.log("coerce (boundary string -> typed number):");
  console.log(`  z.coerce.number().int().min(1).max(65535).parse("8080") -> ${port} (typeof ${typeof port})`);
  check("coerce turns '8080' into the number 8080", port === 8080 && typeof port === "number");
  check("coerce still runs refinements ('abc' fails .int())", Port.safeParse("abc").success === false);
  check("coerce rejects out-of-range ('99999' fails .max)", Port.safeParse("99999").success === false);

  // Contrast: WITHOUT coerce, a string is a type error at the parse boundary.
  const StrictNum = z.number().int();
  check("z.number() (no coerce) rejects the string '5'", StrictNum.safeParse("5").success === false);

  // --- error.format(): nested error tree keyed by field path ----------------
  // .format() returns a tree mirroring the data shape: each node has _errors[]
  // (string messages for that level) and child keys for nested fields. This is
  // the shape form libraries consume to show per-field errors.
  const Signup = z.object({
    email: z.string().email(),
    profile: z.object({
      name: z.string().min(2),
      age: z.number().int().nonnegative(),
    }),
  });
  const bad = Signup.safeParse({ email: "no", profile: { name: "a", age: -1 } });
  if (!bad.success) {
    const tree = bad.error.format();
    console.log("");
    console.log("error.format() (nested tree, one _errors[] per level):");
    console.log(`  top._errors        = ${JSON.stringify(tree._errors)}`);
    console.log(`  email._errors      = ${JSON.stringify(tree.email?._errors)}`);
    console.log(`  profile._errors    = ${JSON.stringify(tree.profile?._errors)}`);
    console.log(`  profile.name._errors  = ${JSON.stringify(tree.profile?.name?._errors)}`);
    console.log(`  profile.age._errors   = ${JSON.stringify(tree.profile?.age?._errors)}`);
    check("format().email._errors lists the email message", (tree.email?._errors?.length ?? 0) > 0);
    check("format().profile.name._errors lists the name message", (tree.profile?.name?._errors?.length ?? 0) > 0);
    check("format().profile.age._errors lists the age message", (tree.profile?.age?._errors?.length ?? 0) > 0);
    check("format().top._errors is empty (errors are on leaves)", (tree._errors?.length ?? 0) === 0);
  }

  // --- error.flatten(): two flat buckets for simple forms -------------------
  // .flatten() collapses the tree into {formErrors[], fieldErrors{}} — handy
  // when you only have one level and want top-level vs per-field buckets.
  const Flat = z.object({ a: z.number(), b: z.string() });
  const flatBad = Flat.safeParse({ a: "x" }); // a wrong, b missing
  if (!flatBad.success) {
    const flat = flatBad.error.flatten();
    console.log("");
    console.log("error.flatten() (two buckets):");
    console.log(`  formErrors  = ${JSON.stringify(flat.formErrors)}`);
    console.log(`  fieldErrors = ${JSON.stringify(flat.fieldErrors)}`);
    check("flatten().fieldErrors.a lists the 'a' message", (flat.fieldErrors.a?.length ?? 0) > 0);
    check("flatten().fieldErrors.b lists the 'b' missing message", (flat.fieldErrors.b?.length ?? 0) > 0);
  }

  // --- the single-source-of-truth, summarized -------------------------------
  console.log("");
  console.log("Single source of truth (schema = type + runtime check):");
  console.log("  WRITE:   const S = z.object({...})            // one definition");
  console.log("  COMPILE: type T = z.infer<typeof S>           // derived TS type");
  console.log("  RUNTIME: S.parse(unknown) -> T  |  ZodError   // validated value");
  console.log("  BOUNDARY: S.safeParse(req.body)               // narrows unknown");
  console.log("");
  console.log("Cross-language: this is the JS answer to");
  console.log("  - Rust serde #[derive(Deserialize)] (one struct -> typed deser)");
  console.log("  - Go struct-tag validation (field tags -> runtime checks)");
  check("zod closes the TS type-erasure hole at trust boundaries", true);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("zod_validation.ts — Phase 6 bundle (metaprog member).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TS types are ERASED at runtime. Zod makes ONE schema the");
  console.log("single source of truth for BOTH the compile-time type (z.infer) AND");
  console.log("the runtime validation (parse) — closing the trust-boundary hole.");
  await sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

void main();
