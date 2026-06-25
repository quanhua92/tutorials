// json.ts — Phase 5 bundle (Standard Library Essentials).
//
// GOAL (one line): show, by printing every value, that JSON.stringify / JSON.parse
// round-trip the JSON SUBSET of JS values (string/number/boolean/null/array/object)
// — while undefined/Function/Symbol are omitted-or-nulled, BigInt and circular
// references THROW, Date collapses to an ISO string (and does NOT revive) unless
// you supply a reviver, Map/Set/RegExp vanish to "{}", and Infinity/NaN become
// null — pinning the replacer/reviver/toJSON hooks, the key-quoting rule, and the
// safe-vs-eval security contract as check()'d invariants.
//
// This is the GROUND TRUTH for JSON.md. Every number, table, and worked example
// in the guide is printed by this file. Change it -> re-run -> re-paste. Never
// hand-compute.
//
// LINEAGE (why this bundle exists): JSON is JavaScript's NATIVE serialization
// format — the name is literally "JavaScript Object Notion." It is the lingua
// franca of HTTP APIs, config files, and persistence. stringify/parse round-trip
// a strict SUBSET of JS values; everything outside that subset is dropped,
// coerced, or throws. This bundle pins the subset, the four hooks (replacer,
// reviver, toJSON, space), the two throwing failure modes (BigInt, circular), and
// the security contract — the cross-language analog of Go's encoding/json (struct
// tags) and Rust's serde (derive), BOTH of which give TYPE-DRIVEN serialization
// that TS's dynamic JSON lacks natively.
//
// Run:
//     pnpm exec tsx json.ts   (or: just run json)

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

// --- typed wrappers (no `any` in OUR code; the stdlib's own signatures use any) -
//
// JSON is inherently untyped: a parsed value's shape is a RUNTIME fact, so the
// stdlib types JSON.parse's return as `any`. We tighten it to `unknown` to FORCE
// narrowing before use — the type-safe discipline for untrusted data. The few
// `as` casts below are TYPE-ONLY (erased at runtime — assertions emit no code)
// and are commented with WHY, applied only to values whose shape we just
// serialized and therefore know exactly.

// parseJSON wraps JSON.parse to return `unknown` instead of `any`, forcing the
// caller to narrow (typeof / Array.isArray / key checks) before touching the
// value. The optional reviver is the parse-time transform hook (see Section B).
function parseJSON(text: string, reviver?: Transform): unknown {
  return JSON.parse(text, reviver);
}

// A replacer (stringify) / reviver (parse) transforms each value depth-first.
// Typed on `unknown` so the body MUST narrow before touching the value (no `any`
// leak). This is assignable to the stdlib's `(this: any, key: string, value: any)
// => any` (params contravariant any->unknown; return covariant unknown->any).
type Transform = (key: string, value: unknown) => unknown;

// ============================================================================
// Section A — The JSON subset: stringify/parse round-trip + what is NOT in JSON
// ============================================================================

function sectionA(): void {
  sectionBanner("A — The JSON subset: round-trip + what is NOT in JSON");

  // The JSON subset: string, number, boolean, null, array, object. A value made
  // ONLY of these round-trips LOSSLESSLY through stringify -> parse.
  const original = { a: 1, b: "x", c: [true, null] };
  const serialized = JSON.stringify(original);
  const roundtrip = parseJSON(serialized);

  console.log(`original              : { a:1, b:"x", c:[true,null] }`);
  console.log(`JSON.stringify(orig)  : ${serialized}`);
  console.log(`typeof serialized     : ${typeof serialized}   (stringify ALWAYS returns a string)`);
  // Re-stringifying the parsed value reproduces the EXACT bytes: insertion-order
  // keys are stable per spec, so the round-trip is byte-identical for the subset.
  const reserialized = JSON.stringify(roundtrip);
  console.log(`re-stringify(parsed)  : ${reserialized}`);
  check("round-trip lossless: re-stringify === original stringify", reserialized === serialized);

  // Field-level equality (narrow the `unknown` parse result to read it safely).
  const rt = roundtrip as { a: unknown; b: unknown; c: unknown[] };
  check("roundtrip.a === 1 (number)", rt.a === 1);
  check('roundtrip.b === "x" (string)', rt.b === "x");
  check("roundtrip.c[0] === true (boolean)", rt.c[0] === true);
  check("roundtrip.c[1] === null", rt.c[1] === null);
  check("roundtrip.c.length === 2", rt.c.length === 2);

  // ---- What is NOT in JSON (every row is a check()'d runtime verdict) --------
  console.log("");
  console.log("Values OUTSIDE the JSON subset (each behavior is the engine's verdict):");

  // undefined / Function / Symbol in an OBJECT -> the key is OMITTED entirely.
  const withHoles = JSON.stringify({
    a: undefined,
    b: function () {},
    c: Symbol("s"),
    d: 1,
  });
  console.log(`  {a:undefined, b:fn, c:Symbol, d:1} -> ${withHoles}   (a/b/c OMITTED; d kept)`);
  check('undefined/fn/Symbol omitted from objects -> \'{"d":1}\'', withHoles === '{"d":1}');

  // The SAME three values in an ARRAY -> become null (NOT omitted: array indices
  // are stable, so the slot is preserved as null).
  const arrWithHoles = JSON.stringify([undefined, function () {}, Symbol("s"), 1]);
  console.log(`  [undefined, fn, Symbol, 1]        -> ${arrWithHoles}   (each -> null; index kept)`);
  check("undefined/fn/Symbol -> null in arrays", arrWithHoles === "[null,null,null,1]");

  // Map / Set / RegExp -> "{}" (only ENUMERABLE OWN string-keyed props survive;
  // these store their data in INTERNAL SLOTS, not own props, so nothing survives).
  const collections = JSON.stringify([new Map([[1, 2]]), new Set([1]), /abc/]);
  console.log(`  [Map, Set, RegExp]                -> ${collections}   (each -> {}; data LOST)`);
  check("Map/Set/RegExp -> {} (internal slots, no own props)", collections === "[{},{},{}]");

  // Infinity / NaN / -Infinity -> null (NOT omitted — they map to the JSON null).
  const specials = JSON.stringify([Infinity, -Infinity, NaN]);
  console.log(`  [Infinity, -Infinity, NaN]        -> ${specials}   (each -> null)`);
  check("Infinity/-Infinity/NaN -> null", specials === "[null,null,null]");

  // Symbol-keyed properties -> ignored ENTIRELY (the replacer cannot recover them).
  const symKey = Symbol("k");
  const symProps = JSON.stringify({ normal: 1, [symKey]: "hidden" });
  console.log(`  {[Symbol(..)]: "hidden"} property -> ${symProps}   (symbol keys NEVER serialized)`);
  check("symbol-keyed properties ignored", symProps === '{"normal":1}');
}

// ============================================================================
// Section B — Date.toJSON: the silent type erasure (and the reviver fix)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Date.toJSON: the silent type erasure (and the reviver fix)");

  // Date implements toJSON(), which returns the same value as toISOString() — an
  // ISO-8601 string in UTC. So JSON.stringify(new Date(0)) is a QUOTED string.
  const epoch = new Date(0);
  const dateStr = JSON.stringify(epoch);
  console.log(`new Date(0)                  -> ${dateStr}`);
  console.log(`typeof (parsed back)         -> ${typeof parseJSON(dateStr)}   <-- a STRING, not a Date!`);
  check('JSON.stringify(new Date(0)) === \'"1970-01-01T00:00:00.000Z"\'', dateStr === '"1970-01-01T00:00:00.000Z"');
  check("Date.toJSON === toISOString (ISO-8601 UTC)", epoch.toJSON() === epoch.toISOString());

  // THE TYPE-ERASURE TRAP: round-tripping a Date through JSON gives back a
  // STRING. JSON carries no type metadata, so parse cannot know "1970-...Z" was
  // ever a Date. instanceof Date is FALSE on the parsed value.
  const wrapped = JSON.stringify({ created: epoch });
  const parsed = parseJSON(wrapped) as { created: unknown };
  console.log(`{created: new Date(0)} -> ${wrapped}`);
  console.log(`parsed.created instanceof Date -> ${parsed.created instanceof Date}   (type info LOST)`);
  console.log(`typeof parsed.created          -> ${typeof parsed.created}`);
  check("parsed Date is NOT a Date instance (type erased)", (parsed.created instanceof Date) === false);
  check("parsed Date is a string", typeof parsed.created === "string");

  // THE FIX: a REVIVER — a function passed to JSON.parse that transforms each
  // value depth-first (most nested first; the root is called LAST with key "").
  // We detect ISO-8601 strings and return new Date(...); everything else passes
  // through unchanged. This is the canonical Date-round-trip pattern.
  const isoPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;
  const dateReviver: Transform = (_key, value) =>
    typeof value === "string" && isoPattern.test(value) ? new Date(value) : value;

  const revived = parseJSON(wrapped, dateReviver) as { created: unknown };
  console.log("");
  console.log(`with reviver: parsed.created instanceof Date -> ${revived.created instanceof Date}`);
  console.log(`with reviver: parsed.created.getTime()       -> ${(revived.created as Date).getTime()}`);
  check("reviver revives ISO string -> Date instance", revived.created instanceof Date);
  check("revived Date.getTime() === 0 (round-trip restored)", (revived.created as Date).getTime() === 0);
}

// ============================================================================
// Section C — The two hooks: replacer (allowlist + transform) + toJSON + space
// ============================================================================

function sectionC(): void {
  sectionBanner("C — The hooks: replacer (allowlist + transform) + toJSON + space");

  const src = { a: 1, b: 2, c: 3, secret: "pw" };

  // (1) Replacer as an ALLOWLIST ARRAY: only the listed string keys survive.
  const allowlisted = JSON.stringify(src, ["a", "c"]);
  console.log(`replacer allowlist ["a","c"]  -> ${allowlisted}   (only a,c kept; b/secret dropped)`);
  check('array replacer is an allowlist -> \'{"a":1,"c":3}\'', allowlisted === '{"a":1,"c":3}');

  // (2) Replacer as a TRANSFORM FUNCTION: called for EVERY value depth-first
  // (the root is called FIRST with key ""; then each property). The return value
  // REPLACES the value; returning undefined OMITS the property.
  const uppercaser: Transform = (_key, value) =>
    typeof value === "string" ? value.toUpperCase() : value;
  const transformed = JSON.stringify({ greet: "hi", n: 3 }, uppercaser);
  console.log(`replacer fn uppercases str    -> ${transformed}`);
  check('function replacer transforms -> \'{"greet":"HI","n":3}\'', transformed === '{"greet":"HI","n":3}');

  // Replacer that FILTERS keys (return undefined to omit):
  const dropSecret: Transform = (key, value) => (key === "secret" ? undefined : value);
  const filtered = JSON.stringify(src, dropSecret);
  console.log(`replacer fn drops "secret"    -> ${filtered}`);
  check("replacer returning undefined omits the key", filtered === '{"a":1,"b":2,"c":3}');

  // (3) toJSON: a method an object defines to CONTROL its own serialization.
  // stringify calls it (passing the key) and serializes the RETURN value instead
  // of the object. Date uses this to emit its ISO string; here a custom toJSON
  // returns a number, which becomes the entire output.
  const customToJSON = JSON.stringify({ toJSON: () => 42 });
  console.log(`{toJSON: ()=>42}              -> ${customToJSON}   (return value replaces the object)`);
  check("custom toJSON return value is serialized", customToJSON === "42");

  // (4) space: pretty-print. number -> N spaces per level (clamped to 10);
  // string -> that string per level (truncated to 10 chars). 2 is conventional.
  const obj2 = { a: 1, b: { c: 2 } };
  const pretty2 = JSON.stringify(obj2, null, 2);
  console.log("space=2 (2-space pretty-print):");
  console.log(pretty2);
  check('space=2 indents nested objects (leading 2-space "a")', pretty2.includes('\n  "a": 1'));

  const prettyTab = JSON.stringify(obj2, null, "\t");
  console.log('space="\\t" (tab indent):');
  console.log(prettyTab);
  check('space="\\t" indents with a tab', prettyTab.includes('\t"a": 1'));
}

// ============================================================================
// Section D — Failure modes: circular/BigInt throw; Infinity/NaN->null; keys
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Failure modes: circular/BigInt throw; key quoting + ordering");

  // (1) Circular reference -> TypeError ("Converting circular structure to JSON").
  // JSON has no object-references, so a cycle cannot be serialized.
  const cyclic: Record<string, unknown> = {};
  cyclic.self = cyclic;
  let circularThrew = false;
  let circularErr = "";
  try {
    JSON.stringify(cyclic);
  } catch (e) {
    circularThrew = true;
    circularErr = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
  }
  console.log(`cyclic object stringify -> ${circularThrew}`);
  console.log(`  error                 -> ${circularErr}`);
  check("circular reference throws TypeError", circularThrew);

  // (2) BigInt -> TypeError ("Do not know how to serialize a BigInt"). BigInt is
  // NOT in the JSON number grammar (JSON numbers are IEEE-754 doubles), so the
  // engine REFUSES rather than silently truncating precision.
  let bigintThrew = false;
  let bigintErr = "";
  try {
    JSON.stringify({ big: 1n });
  } catch (e) {
    bigintThrew = true;
    bigintErr = e instanceof Error ? `${e.name}: ${e.message}` : String(e);
  }
  console.log(`BigInt stringify         -> ${bigintThrew}`);
  console.log(`  error                 -> ${bigintErr}`);
  check("BigInt throws TypeError", bigintThrew);

  // (3) Infinity/NaN -> null (standalone pinned invariant; contrast with BigInt
  // which THROWS — Infinity/NaN do NOT throw, they map to null).
  check('JSON.stringify(Infinity) === "null"', JSON.stringify(Infinity) === "null");
  check('JSON.stringify(NaN) === "null"', JSON.stringify(NaN) === "null");
  check('JSON.stringify(-Infinity) === "null"', JSON.stringify(-Infinity) === "null");
  console.log('Infinity/NaN/-Infinity all -> "null" (see [check]s above)');

  // (4) Key quoting + ordering: ALL keys are double-quoted in JSON output, EVEN
  // valid identifiers (unlike JS object literals, where quotes are optional).
  // Integer-like string keys are reordered ASCENDING NUMERIC (the Object.keys
  // rule), THEN other string keys in insertion order.
  const mixed: Record<string, number | string> = { validIdent: 1, "2": 2, name: "x", "1": 1 };
  const mixedStr = JSON.stringify(mixed);
  console.log(`{validIdent, "2", name, "1"} -> ${mixedStr}`);
  console.log('  (ALL keys double-quoted; integer keys "1","2" reordered ascending first)');
  check('all keys double-quoted; integer keys first', mixedStr === '{"1":1,"2":2,"validIdent":1,"name":"x"}');
}

// ============================================================================
// Section E — Security (parse is safe vs eval) + the cross-language contract
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Security (parse is safe vs eval) + cross-language contract");

  // (1) JSON.parse is a PURE DATA parser: it builds objects/arrays/primitives
  // from text and NEVER executes code. That makes it safe on untrusted input,
  // whereas eval() would RUN any embedded script. JSON's grammar is a strict
  // subset of JS with NO function calls, NO identifiers (true/false/null are
  // keywords), and NO arithmetic — there is nothing to execute.
  const untrusted = '{"evil":"alert(1)","ok":true}';
  const data = parseJSON(untrusted) as { evil: unknown; ok: unknown };
  console.log(`untrusted input: ${untrusted}`);
  console.log(`parsed .evil     -> ${JSON.stringify(data.evil)}   (a plain string; alert was NOT called)`);
  console.log(`parsed .ok       -> ${String(data.ok)}`);
  check("JSON.parse treats alert(1) as a plain string (no execution)", data.evil === "alert(1)");

  // (2) Invalid JSON -> SyntaxError (deterministic). Trailing commas, single
  // quotes, and bare identifiers are NOT legal JSON.
  const malformed: ReadonlyArray<readonly [string, string]> = [
    ["trailing comma", '{"a":1,}'],
    ["single quotes", "{'a':1}"],
    ["bare identifier", "{a:1}"],
    ["trailing junk", "1 2"],
  ];
  console.log("");
  console.log("Malformed inputs (each -> SyntaxError):");
  for (const [label, text] of malformed) {
    let threw = false;
    let errName = "";
    try {
      parseJSON(text);
    } catch (e) {
      threw = true;
      errName = e instanceof Error ? e.name : String(e);
    }
    console.log(`  ${label.padEnd(18)} ${JSON.stringify(text).padEnd(12)} -> ${errName}`);
    check(`${label} throws SyntaxError`, threw && errName === "SyntaxError");
  }

  // (3) Deeply-nested JSON can blow the call stack (RangeError) — the recursion
  // depth is engine/stack-size dependent, so it is documented here rather than
  // pinned to a number. This is the ONE residual risk of parsing hostile JSON.
  console.log("");
  console.log("Note: deeply-nested JSON (e.g. tens of thousands of nested arrays/objects)");
  console.log("can overflow the call stack -> RangeError. Depth is NOT spec'd; cap input");
  console.log("size in production.");

  // Cross-language summary (printed, not executed — these are sibling runtimes).
  console.log("");
  console.log("Cross-language serialization contract:");
  console.log("  JS   : JSON.stringify/parse — DYNAMIC, untyped, no schema at compile time.");
  console.log("         Type info is lost (Date -> string); revival is manual (reviver).");
  console.log("  Go   : encoding/json — struct TAGS drive field mapping; typed at compile time.");
  console.log("  Rust : serde #[derive(Serialize, Deserialize)] — FULLY compile-time typed.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("json.ts — Phase 5 bundle (Standard Library Essentials).");
  console.log("JSON.stringify / JSON.parse round-trip the JSON SUBSET of JS values;");
  console.log("everything outside that subset is dropped, coerced, or throws. Every");
  console.log("value below is computed by this file; the .md guide pastes it verbatim.");
  console.log("");
  console.log("Reminder: JSON has NO type metadata. stringify erases types (Date -> string);");
  console.log("parse returns untyped data. Revival is a manual, opt-in hook (the reviver).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
