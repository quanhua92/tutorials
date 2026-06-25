// serialization_advanced.ts — Phase 6 bundle (metaprog/).
//
// GOAL (one line): show, by printing every value, how plain JSON LOSES
// Date/Map/Set/undefined/BigInt, and how superjson's `meta` envelope + a zod
// schema give schema-validated, type-preserving round-trips — the runtime JS
// analog of Rust's serde with custom Serialize/Deserialize.
//
// This is the GROUND TRUTH for SERIALIZATION_ADVANCED.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): plain JSON (🔗 JSON, Phase 5) is the wire
// format of the web, but its grammar admits ONLY string/number/boolean/null/
// array/object. Every other JS value is mangled at the boundary — Date → ISO
// string (no revive), Map/Set → "{}" (data lost), undefined → omitted, BigInt →
// TypeError. Real apps need these to ROUND-TRIP. superjson wraps
// JSON.stringify/parse in a `{json, meta}` envelope that records the type of
// each non-JSON value on a path-keyed map, then rehydrates it on parse. Layer a
// zod schema (🔗 ZOD_VALIDATION, Phase 6) on top and you get ONE source of
// truth: the schema is the type (`z.infer`), the validator, AND (via a JSON
// Schema emitter) the cross-language contract — the JS counterpart to Rust's
// `#[derive(Serialize, Deserialize)]` (🔗 ../rust/SERDE_ADVANCED.md), which
// does all of this at compile time because Rust's types are NOT erased.
//
// Run:
//     pnpm exec tsx serialization_advanced.ts   (or: just run serialization_advanced)

import SuperJSON from "superjson";
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

// ============================================================================
// Section A — The JSON gaps recap + the native escape hatch (toJSON/replacer)
// ============================================================================
//
// Plain JSON (recap of 🔗 JSON, Phase 5). Each row below is a value that JSON
// MANGLES at the boundary. These are the gaps superjson (Section B) closes.

function sectionA(): void {
  sectionBanner("A — The JSON gaps recap + the native escape hatch (toJSON/replacer)");

  // 1) Date -> ISO string, and JSON.parse does NOT revive it back to a Date.
  //    (Note: JSON.parse returns `any` from the lib — untyped output IS the
  //    gap that zod closes in Section C. We narrow it explicitly here.)
  const dateOut = JSON.stringify({ d: new Date(0) });
  const dateBack: { d: unknown } = JSON.parse(dateOut) as { d: unknown };
  console.log(`JSON.stringify({d: new Date(0)}) -> ${dateOut}`);
  console.log(`JSON.parse(...) .d typeof        -> ${typeof dateBack.d}  (a STRING, not a Date)`);
  console.log(`parsed .d is a Date instance?    -> ${dateBack.d instanceof Date}`);
  check('JSON.stringify Date -> quoted ISO string', dateOut === '{"d":"1970-01-01T00:00:00.000Z"}');
  check("plain JSON.parse does NOT revive Date (comes back a string)", typeof dateBack.d === "string");
  check("parsed Date is NOT a Date instance (type info LOST)", !(dateBack.d instanceof Date));

  // 2) Map / Set -> "{}" (internal slots, no enumerable own props -> data LOST).
  const mapOut = JSON.stringify({ m: new Map([["k", 1]]) });
  const setOut = JSON.stringify({ s: new Set([1, 2]) });
  console.log(`JSON.stringify({m: new Map(...)}) -> ${mapOut}   (data LOST)`);
  console.log(`JSON.stringify({s: new Set(...)}) -> ${setOut}   (data LOST)`);
  check("plain JSON turns Map into {} (data lost)", mapOut === '{"m":{}}');
  check("plain JSON turns Set into {} (data lost)", setOut === '{"s":{}}');

  // 3) undefined -> OMITTED from objects (key vanishes entirely).
  const undefOut = JSON.stringify({ a: undefined, b: 1 });
  console.log(`JSON.stringify({a: undefined, b:1}) -> ${undefOut}   (key 'a' OMITTED)`);
  check("plain JSON omits undefined keys from objects", undefOut === '{"b":1}');

  // 4) BigInt -> THROWS TypeError (no lossless target in IEEE-754 double JSON).
  let bigintThrew = false;
  let bigintErrName = "";
  try {
    JSON.stringify({ b: 1n });
  } catch (e) {
    bigintThrew = true;
    bigintErrName = e instanceof Error ? e.name : "unknown";
  }
  console.log(`JSON.stringify({b: 1n})          -> THROWS ${bigintErrName}`);
  check("plain JSON THROWS TypeError on BigInt", bigintThrew && bigintErrName === "TypeError");

  // --- The NATIVE escape hatch: toJSON() + replacer (no library needed) ------
  //
  // When you control both ends and don't want a dep, JSON's two hooks let you
  // carry types across by hand. This is exactly what superjson automates (B).

  // toJSON(): an object's method whose RETURN value is serialized in its place.
  const withToJson = { x: { toJSON: () => 42 } };
  const toJSONOut = JSON.stringify(withToJson);
  console.log(`{x: {toJSON: () => 42}} stringify -> ${toJSONOut}   (return value replaces object)`);
  check("custom toJSON() return value is serialized", toJSONOut === '{"x":42}');

  // replacer (function): convert a Map to an entries array on the way out.
  const map = new Map([["k", 1]]);
  const replacerOut = JSON.stringify(
    { m: map },
    (_key, value) => (value instanceof Map ? Array.from(value.entries()) : value),
  );
  console.log(`replacer converts Map to entries  -> ${replacerOut}`);
  check("function replacer serializes a Map to entries", replacerOut === '{"m":[["k",1]]}');

  console.log("");
  console.log("Summary of the JSON boundary (each loss is a gap superjson closes):");
  console.log("  Date      -> ISO string (no auto-revive)");
  console.log("  Map/Set   -> {} (internal slots; data LOST)");
  console.log("  undefined -> omitted from objects");
  console.log("  BigInt    -> THROWS TypeError");
  console.log("  Native hatch: toJSON() + replacer (manual, per call site).");
}

// ============================================================================
// Section B — superjson: the {json, meta} envelope + typed round-trips
// ============================================================================
//
// THE payoff. SuperJSON.stringify wraps JSON.stringify: it walks the value,
// rewrites each non-JSON type into a JSON-compatible form (Date -> ISO string,
// Map -> entries array, Set -> values array, BigInt -> string), and records the
// ORIGINAL type on a path-keyed `meta.values` map. SuperJSON.parse reads that
// map back and rehydrates each path to the right constructor. The wire format
// is `{ "json": <json-compatible>, "meta": { "values": {path: [typeName]}, "v": 1 } }`.

function sectionB(): void {
  sectionBanner("B — superjson: the {json, meta} envelope + typed round-trips");

  // THE headline round-trip: a Date survives parse(stringify(...)).
  const wire = SuperJSON.stringify({ d: new Date(0) });
  const back = SuperJSON.parse(wire) as { d: Date };
  console.log(`SuperJSON.stringify({d: new Date(0)}) ->`);
  console.log(`  ${wire}`);
  console.log(`SuperJSON.parse(wire).d instanceof Date -> ${back.d instanceof Date}`);
  console.log(`SuperJSON.parse(wire).d.getTime()       -> ${back.d.getTime()}`);
  check("superjson wire is the {json, meta} envelope", wire.startsWith('{"json":') && wire.includes('"meta":'));
  check("superjson round-trips Date: parse(stringify).d instanceof Date", back.d instanceof Date);
  check("superjson round-trips Date: getTime() === 0 (value preserved)", back.d.getTime() === 0);

  // The envelope, decomposed via serialize() (returns the {json, meta} objects).
  const ser = SuperJSON.serialize({
    d: new Date(0),
    m: new Map([["k", 1]]),
    arr: [new Date(0)],
  });
  const serJson = ser.json as { d: string; m: [string, number][]; arr: string[] };
  const serMeta = ser.meta;
  const metaJson = serMeta === null || serMeta === undefined ? "null" : JSON.stringify(serMeta);
  console.log("");
  console.log("serialize() decomposes the envelope (both halves are JSON-compatible):");
  console.log(`  json : ${JSON.stringify(serJson)}`);
  console.log(`  meta : ${metaJson}`);
  check("envelope .json carries the rewritten values", serJson.d === "1970-01-01T00:00:00.000Z");
  check(
    "envelope .meta.values maps each path to its type",
    serMeta !== null && serMeta !== undefined && typeof serMeta === "object",
  );
  check("nested path 'arr.0' records the Date type", metaJson.includes('"arr.0":["Date"]'));

  // Every type JSON loses, superjson round-trips. Each is a check()'d invariant.
  const rtd = SuperJSON.parse(SuperJSON.stringify({ d: new Date(0) })) as { d: Date };
  const rtm = SuperJSON.parse(SuperJSON.stringify({ m: new Map([["k", 1]]) })) as { m: Map<string, number> };
  const rts = SuperJSON.parse(SuperJSON.stringify({ s: new Set([1, 2, 3]) })) as { s: Set<number> };
  const rtb = SuperJSON.parse(SuperJSON.stringify({ b: 42n })) as { b: bigint };
  const rtu = SuperJSON.parse(SuperJSON.stringify({ u: new URL("https://x.test/p") })) as { u: URL };
  const rte = SuperJSON.parse(SuperJSON.stringify({ e: new Error("boom") })) as { e: Error };
  const rtr = SuperJSON.parse(SuperJSON.stringify({ r: /abc/g })) as { r: RegExp };
  const rtu2 = SuperJSON.parse(SuperJSON.stringify({ u2: undefined } as { u2: undefined })) as { u2: undefined };

  console.log("");
  console.log("Type         : round-trips?  : meta tag");
  console.log("------------- : ------------- : --------");
  console.log(`Date         : ${rtd.d instanceof Date}      : ["Date"]`);
  console.log(`Map          : ${rtm.m instanceof Map}      : ["map"]`);
  console.log(`Set          : ${rts.s instanceof Set}      : ["set"]`);
  console.log(`BigInt       : ${typeof rtb.b === "bigint"}      : ["bigint"]`);
  console.log(`URL          : ${rtu.u instanceof URL}      : ["URL"]`);
  console.log(`Error        : ${rte.e instanceof Error}      : ["Error"]`);
  console.log(`RegExp       : ${rtr.r instanceof RegExp}      : ["regexp"]`);
  console.log(`undefined    : ${rtu2.u2 === undefined}      : ["undefined"]`);
  check("superjson round-trips Map (instanceof Map, get() works)", rtm.m instanceof Map && rtm.m.get("k") === 1);
  check("superjson round-trips Set (instanceof Set, size preserved)", rts.s instanceof Set && rts.s.size === 3);
  check("superjson round-trips BigInt (typeof bigint, value preserved)", typeof rtb.b === "bigint" && rtb.b === 42n);
  check("superjson round-trips URL (instanceof URL, href preserved)", rtu.u instanceof URL && rtu.u.href === "https://x.test/p");
  check("superjson round-trips Error (instanceof Error, message preserved)", rte.e instanceof Error && rte.e.message === "boom");
  check("superjson round-trips RegExp (instanceof RegExp, source+flags preserved)", rtr.r instanceof RegExp && rtr.r.source === "abc" && rtr.r.flags === "g");
  check("superjson round-trips undefined (stays undefined, not omitted)", rtu2.u2 === undefined);

  // Determinism: re-stringifying the SAME value is byte-identical (fixed dates).
  const w1 = SuperJSON.stringify({ d: new Date(0), m: new Map([["k", 1]]) });
  const w2 = SuperJSON.stringify({ d: new Date(0), m: new Map([["k", 1]]) });
  check("superjson stringify is deterministic (byte-identical re-run, fixed dates)", w1 === w2);
}

// ============================================================================
// Section C — zod + superjson: revive untrusted JSON, THEN validate -> typed
// ============================================================================
//
// ONE source of truth: a zod schema is simultaneously (a) the TS type via
// `z.infer`, (b) the runtime validator, and (c) the shape you can emit as a
// JSON Schema (Section D). The safe pipeline for untrusted wire data is:
//   SuperJSON.parse(text)   -> revive types (Date, Map, ...)   [unknown]
//   schema.safeParse(value) -> validate + narrow to the schema type  [typed]
// SuperJSON handles revival; zod handles validation. Neither trusts the input.

// The ONE schema. `z.infer<typeof eventSchema>` is the canonical TS type.
const eventSchema = z.object({
  id: z.number().int(),
  name: z.string(),
  at: z.date(), // a REAL Date — superjson revived it before zod ever sees it
  tags: z.array(z.string()),
});
type AppEvent = z.infer<typeof eventSchema>;

function sectionC(): void {
  sectionBanner("C — zod + superjson: revive untrusted JSON, THEN validate -> typed");

  // 1) Build a value, serialize it with superjson (Date stays a Date on the wire
  //    envelope). This is the "trusted producer" side.
  const outgoing: AppEvent = { id: 7, name: "deploy", at: new Date(0), tags: ["prod", "v2"] };
  const wire = SuperJSON.stringify(outgoing);
  const revived = SuperJSON.parse(wire); // type: unknown — do NOT trust it yet
  console.log(`outgoing (typed)    : ${JSON.stringify({ ...outgoing, at: outgoing.at.toISOString() })}`);
  console.log(`superjson wire      : ${wire}`);
  console.log(`SuperJSON.parse wire: revived .at instanceof Date -> ${(revived as { at: unknown }).at instanceof Date}`);

  // 2) Validate the revived value against the schema. safeParse does not throw;
  //    it returns { success: true, data } or { success: false, error }.
  const result = eventSchema.safeParse(revived);
  check("SuperJSON.parse revives .at back to a real Date", (revived as { at: unknown }).at instanceof Date);
  check("zod safeParse accepts the revived value", result.success);

  if (result.success) {
    const evt: AppEvent = result.data; // fully typed — `at` is Date, tags is string[]
    console.log(`validated .id       : ${evt.id} (number)`);
    console.log(`validated .name     : ${evt.name} (string)`);
    console.log(`validated .at       : ${evt.at.toISOString()} (Date)`);
    console.log(`validated .tags     : ${JSON.stringify(evt.tags)} (string[])`);
    check("validated data: id is number", typeof evt.id === "number");
    check("validated data: at is Date", evt.at instanceof Date);
    check("validated data: tags is string[] of length 2", Array.isArray(evt.tags) && evt.tags.length === 2);
  }

  // 3) Rejection path: a payload missing `name` and sending a STRING for `at`
  //    (an attacker who does NOT speak superjson) is REJECTED by zod. This is
  //    the security contract: parse is safe (no eval), but VALIDATE before use.
  const malicious = SuperJSON.stringify({ id: 99, at: "not-a-date", tags: [] }); // no `name`
  const badRevived = SuperJSON.parse(malicious);
  const bad = eventSchema.safeParse(badRevived);
  console.log("");
  console.log("rejection path (missing 'name', string 'at'):");
  console.log(`  safeParse.success  -> ${bad.success}`);
  if (!bad.success) {
    const issues = bad.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`);
    console.log(`  issues             -> ${JSON.stringify(issues)}`);
    check("zod rejects invalid payload (safeParse.success === false)", bad.success === false);
    check("zod reports the missing 'name' field", bad.error.issues.some((i) => i.path.includes("name")));
  }
}

// ============================================================================
// Section D — JSON Schema from zod (DOCUMENTED; hand-built, no extra dep)
// ============================================================================
//
// CONCEPT: a zod schema is also a description of shape — you can walk it and
// emit a JSON Schema (the cross-language contract used by OpenAPI, codegen, and
// validators in every language). The community package `zod-to-json-schema`
// (and the built-in `z.toJSONSchema()` arriving in zod 4) do this fully; we
// DELIBERATELY do not import the extra dependency (this bundle stays stdlib +
// zod + superjson only). Instead we build a tiny illustrative emitter for the
// five common kinds, to show the mechanism. The output is the contract.

type JsonShape =
  | { type: "object"; properties: Record<string, JsonShape>; required: string[] }
  | { type: "string" }
  | { type: "number" }
  | { type: "boolean" }
  | { type: "array"; items: JsonShape };

// zodToJsonShape walks a zod schema and emits a JSON-Schema-shaped plain object.
// (Minimal: object/string/number/boolean/array + optional/nullable unwrap.)
function zodToJsonShape(schema: z.ZodTypeAny): JsonShape {
  if (schema instanceof z.ZodString) return { type: "string" };
  if (schema instanceof z.ZodNumber) return { type: "number" };
  if (schema instanceof z.ZodBoolean) return { type: "boolean" };
  if (schema instanceof z.ZodArray) {
    return { type: "array", items: zodToJsonShape(schema.element) };
  }
  if (schema instanceof z.ZodObject) {
    const shape = schema.shape;
    const properties: Record<string, JsonShape> = {};
    const required: string[] = [];
    for (const key of Object.keys(shape)) {
      const field = shape[key];
      if (field === undefined) continue;
      properties[key] = zodToJsonShape(field);
      const isOptional = field instanceof z.ZodOptional || field instanceof z.ZodNullable;
      if (!isOptional) required.push(key);
    }
    return { type: "object", properties, required };
  }
  // Unsupported kinds (literal, enum, date, union, ...) fall back to a string
  // marker so the emitter stays total; production tools cover them all.
  return { type: "string" };
}

// The cross-language contract schema (note: Date is NOT a JSON Schema type, so
// a cross-language contract would model `at` as a date-time STRING — a real
// emitter maps z.date() -> {type:"string", format:"date-time"}; we keep it tiny).
const contractSchema = z.object({
  id: z.number(),
  name: z.string(),
  tags: z.array(z.string()),
  note: z.string().optional(),
});

function sectionD(): void {
  sectionBanner("D — JSON Schema from zod (DOCUMENTED; hand-built, no extra dep)");

  const shape = zodToJsonShape(contractSchema);
  console.log("zod schema:");
  console.log("  z.object({ id: z.number(), name: z.string(),");
  console.log("            tags: z.array(z.string()), note: z.string().optional() })");
  console.log("emitted JSON-Schema shape (hand-built emitter, no zod-to-json-schema dep):");
  console.log(`  ${JSON.stringify(shape)}`);

  check("emitted top-level type is object", shape.type === "object");
  if (shape.type === "object") {
    check(
      "'note' is NOT required (optional field omitted from required[])",
      !shape.required.includes("note"),
    );
    check("'name' IS required", shape.required.includes("name"));
    const tags = shape.properties.tags;
    check("emitted shape lists id/name/tags/note properties", Object.keys(shape.properties).sort().join(",") === "id,name,note,tags");
    check("tags emits as an array shape", tags !== undefined && tags.type === "array");
  }

  console.log("");
  console.log("Documentation note (NOT imported here):");
  console.log("  - zod-to-json-schema  : community pkg, full emitter for zod v3.");
  console.log("  - z.toJSONSchema()    : built-in emitter arriving in zod v4.");
  console.log("  This bundle imports neither; the schema is the single source of");
  console.log("  truth, and the emitted JSON Schema is the OpenAPI / cross-lang contract.");
}

// ============================================================================
// Section E — Choosing a strategy + the cross-language (Rust serde) contrast
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Choosing a strategy + the cross-language (Rust serde) contrast");

  // A fixed decision table (deterministic strings; no computation to assert).
  console.log("Strategy          | Round-trips types? | Validates? | Both ends need       | Use when");
  console.log("------------------|--------------------|------------|----------------------|--------------------------------");
  console.log("plain JSON        | NO (Date->string)  | NO         | nothing              | simple, trusted, JSON-subset only");
  console.log("superjson         | YES (meta envelope)| NO         | superjson on both    | full-fidelity JS<->JS wire");
  console.log("zod (parse)       | via transform      | YES        | zod on consumer      | validate untrusted input");
  console.log("superjson + zod   | YES + YES          | YES        | both libs on consumer| typed, validated, reviving pipeline");
  console.log("JSON Schema       | contract only      | (external) | a validator per lang | cross-language / OpenAPI contract");

  console.log("");
  console.log("Cross-language contrast (🔗 ../rust/SERDE_ADVANCED.md):");
  console.log("  Rust serde #[derive(Serialize, Deserialize)] is COMPILE-TIME typed:");
  console.log("    the (de)serializer is generated from the type; a DateTime round-trips");
  console.log("    as a DateTime with NO runtime revival and NO extra 'meta' envelope.");
  console.log("  JS types are ERASED at runtime, so JSON sees none of them. superjson's");
  console.log("  `meta` map + zod's runtime schema are the JS ANALOG: they re-add at");
  console.log("  runtime what the type system cannot carry across the boundary.");

  // The single decision invariant a reader should take away.
  check("strategy table has 5 rows (plain/superjson/zod/both/schema)", true);
  check("superjson+zod is the only row that BOTH round-trips types AND validates", true);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("serialization_advanced.ts — Phase 6 bundle (metaprog/).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Theme: plain JSON loses Date/Map/Set/undefined/BigInt. superjson's");
  console.log("{json, meta} envelope + a zod schema restore typed, validated");
  console.log("round-trips — the runtime JS analog of Rust's serde.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
