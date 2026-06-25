// objects_records.ts — Phase 1 bundle (Language Foundations).
//
// GOAL (one line): show, by printing every value, how JS objects behave as
// string-keyed records — the integer-like-keys-first iteration trap (the
// determinism centerpiece), own-vs-inherited property checks, property
// descriptors, Object.freeze, the shallow-copy shared-mutability trap, and the
// TypeScript Record<Keys, Type> / index-signature typing layered on top.
//
// This is the GROUND TRUTH for OBJECTS_RECORDS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle sits here): VALUES_TYPES_COERCION pinned that objects
// are mutable, shared-by-reference values (`typeof {} === "object"`). This
// bundle opens the object up: how its string keys are stored and ITERATED (the
// one ordering trap that breaks determinism), how `'in'` differs from
// `hasOwnProperty`/`Object.hasOwn` (own vs inherited — the prototype chain
// leaks in), how property descriptors expose the meta-level
// (writable/enumerable/configurable), and how a SHALLOW copy leaves nested
// objects aliased (the canonical shared-mutability bug, deepened in
// VALUE_VS_REFERENCE). TypeScript then adds Record<Keys, Type> (a closed key
// set) and `[k: string]: V` index signatures (an open key set) on top of the
// same runtime object — types that are ERASED, so the runtime traps below still
// apply verbatim.
//
// Run:
//     pnpm exec tsx objects_records.ts   (or: just run objects_records)

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

// --- typed helpers (keep strict-mode comparisons legal, no `any`) -------------

// dataDescriptor returns an own property's data descriptor with all four flags
// normalized to definite booleans. Object.getOwnPropertyDescriptor yields a
// (possibly undefined) PropertyDescriptor whose individual flags are themselves
// optional (boolean | undefined); this helper collapses both layers so the
// call sites compare clean booleans. It throws if the property is absent (the
// section asserts presence first, so that throw would itself flag a regression).
function dataDescriptor(
  o: object,
  key: PropertyKey,
): { value: unknown; writable: boolean; enumerable: boolean; configurable: boolean } {
  const d = Object.getOwnPropertyDescriptor(o, key);
  if (d === undefined) {
    throw new Error("no descriptor for " + String(key));
  }
  return {
    value: d.value,
    writable: d.writable === true,
    enumerable: d.enumerable === true,
    configurable: d.configurable === true,
  };
}

// tryAssign attempts `o[key] = val` and reports whether it threw. In ESM
// (strict mode — core/package.json is `"type": "module"`), assigning to a
// non-writable OR frozen property THROWS a TypeError; in sloppy mode it would
// silently no-op. We deliberately cast frozen/Readonly objects to a mutable
// Record view here so the RUNTIME guard (not the TS readonly check) is what we
// exercise — that is the behavior under test.
function tryAssign(
  o: Record<string, number>,
  key: string,
  val: number,
): { threw: boolean; msg: string } {
  try {
    o[key] = val;
    return { threw: false, msg: "" };
  } catch (e) {
    return { threw: true, msg: (e as Error).message };
  }
}

// ============================================================================
// Section A — Object literals, computed/spread keys, access, and
//             'in' vs hasOwnProperty vs Object.hasOwn (own vs inherited)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Literals, computed/spread keys, access, own-vs-inherited");

  // Object literal: shorthand {x, y} (var name == key), computed {[expr]: v},
  // and a normal key. Computed keys accept any expression; the key is coerced
  // to a string (a Symbol would become a Symbol-keyed property, not printed by
  // Object.keys which is string-keyed only).
  const x = 10;
  const y = 20;
  const k = "dyn";
  const obj = { x, y, [k + 1]: 30, fixed: 40 };
  console.log(`const obj = { x, y, [k+1]: 30, fixed: 40 }  // shorthand + computed + literal`);
  console.log(`  obj.x = ${obj.x}  obj["dyn1"] = ${obj["dyn1"]}  obj.fixed = ${obj.fixed}`);
  check("shorthand {x} sets obj.x === 10", obj.x === 10);
  check("computed [k+1] sets obj['dyn1'] === 30", obj["dyn1"] === 30);

  // typeof an object literal is "object" (pinned in VALUES_TYPES_COERCION; the
  // value-vs-reference axis starts here — objects are shared references).
  check('typeof {} === "object"', typeof {} === "object");

  // Spread: {...obj} copies own-enumerable string-keyed properties into a NEW
  // object. Later keys win on collision (used for merges — Section E).
  const spread = { ...obj, y: 99 };
  check("spread copies unchanged keys (obj.x === 10 survives)", spread.x === 10);
  check("spread overrides on collision (y === 99)", spread.y === 99);
  check("spread produced a NEW top-level object (not ===)", obj !== spread);

  // Property access: dot o.x and bracket o["x"] agree on a present key. An
  // ABSENT key returns undefined — NOT an error. Under noUncheckedIndexedAccess,
  // bracket access on an index signature is typed `T | undefined`, so the
  // === undefined comparison typechecks (dot access to an index signature is
  // typed `T`, which would make `=== undefined` a "no overlap" type error —
  // bracket is therefore both the dynamic and the type-safe form).
  const rec: Record<string, number> = { a: 1, b: 2 };
  check("dot access present key: rec.a === 1", rec.a === 1);
  check('bracket access present key: rec["b"] === 2', rec["b"] === 2);
  check('absent key returns undefined, not an error: rec["missing"] === undefined', rec["missing"] === undefined);

  // 'in' vs hasOwnProperty vs Object.hasOwn — THE own-vs-inherited distinction.
  // `in` walks the PROTOTYPE CHAIN (so inherited properties match); the two
  // `hasOwn*` checks are OWN-ONLY. Every plain object inherits toString,
  // hasOwnProperty, valueOf, etc. from Object.prototype — so "toString" is `in`
  // {} even though {} has no own "toString".
  const blank: Record<string, never> = {};
  check('"toString" in {} === true  (inherited from Object.prototype)', "toString" in blank === true);
  check('{}.hasOwnProperty("toString") === false  (own-only)', blank.hasOwnProperty("toString") === false);
  check('Object.hasOwn({}, "toString") === false  (own-only, ES2022)', Object.hasOwn(blank, "toString") === false);

  const withOwn = { a: 1 };
  check('"a" in {a:1} === true  (own key)', "a" in withOwn === true);
  check('Object.hasOwn({a:1}, "a") === true  (own key)', Object.hasOwn(withOwn, "a") === true);

  // delete operator: returns true (always — even for a non-existent own,
  // non-configurable would throw in strict mode); the deleted property is then
  // undefined, exactly like an absent key.
  const del: Record<string, number> = { a: 1, b: 2 };
  const delResult = delete del.a;
  check("delete o.a returns true", delResult === true);
  check('after delete, o["a"] === undefined', del["a"] === undefined);
  check("delete dropped the key (Object.keys length 1)", Object.keys(del).length === 1);
}

// ============================================================================
// Section B — ITERATION ORDER: integer-like keys first, ascending (THE TRAP)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — ITERATION ORDER: integer-like keys FIRST, ascending (the trap)");

  // THE headline example. The object is written with insertion order b, a, 2, 1.
  // Object.keys returns ["1","2","b","a"]: integer-like keys ("1","2") come
  // FIRST in ascending numeric order, THEN the remaining string keys ("b","a")
  // in insertion order. This is spec-mandated ([[OwnPropertyKeys]], ES2020+) and
  // is THE determinism trap in §4.2: insertion order is NOT the whole story.
  const o: Record<string, number> = { b: 1, a: 2, 2: 3, 1: 4 };
  const keys = Object.keys(o);
  console.log(`const o = { b: 1, a: 2, 2: 3, 1: 4 }   // written order: b, a, 2, 1`);
  console.log(`Object.keys(o) -> ${JSON.stringify(keys)}`);
  check('Object.keys order is exactly ["1","2","b","a"]', JSON.stringify(keys) === JSON.stringify(["1", "2", "b", "a"]));

  // MDN's canonical array-like example, reproduced verbatim: keys 100, 2, 7
  // come out 2, 7, 100 — ascending numeric, ignoring insertion order entirely.
  const arrayLike: Record<string, string> = { 100: "a", 2: "b", 7: "c" };
  console.log(`Object.keys({100:"a", 2:"b", 7:"c"}) -> ${JSON.stringify(Object.keys(arrayLike))}`);
  check('integer keys ascending: Object.keys -> ["2","7","100"]', JSON.stringify(Object.keys(arrayLike)) === JSON.stringify(["2", "7", "100"]));

  // String-only keys keep pure insertion order (no integer-like key present).
  const strOnly: Record<string, number> = { b: 1, a: 2, c: 3 };
  console.log(`Object.keys({b,a,c}) -> ${JSON.stringify(Object.keys(strOnly))}  (strings: insertion order)`);
  check('string-only keys stay in insertion order ["b","a","c"]', JSON.stringify(Object.keys(strOnly)) === JSON.stringify(["b", "a", "c"]));

  // THE EDGE: "1" is a canonical numeric index (first, ascending); "01" is NOT
  // (leading zero -> ToString(1) is "1", not "01", so "01" is a plain string
  // key). So even though "01" is inserted FIRST, "1" always wins the lead.
  const edge: Record<string, number> = { "01": 1, "1": 2 };
  console.log(`Object.keys({"01":1, "1":2}) -> ${JSON.stringify(Object.keys(edge))}  ("1" is an index; "01" is not)`);
  check('leading-zero edge: Object.keys -> ["1","01"]', JSON.stringify(Object.keys(edge)) === JSON.stringify(["1", "01"]));

  // THE FIX for deterministic output: sort the keys explicitly before printing
  // (or use a Map, which keeps ALL keys in insertion order — see COLLECTIONS_DEEP).
  // Lexicographic sort of ["1","2","b","a"] -> ["1","2","a","b"].
  const sorted = Object.keys(o).sort();
  console.log(`Object.keys(o).sort() -> ${JSON.stringify(sorted)}  (deterministic: the §4.2 rule)`);
  check('sorted keys are exactly ["1","2","a","b"]', JSON.stringify(sorted) === JSON.stringify(["1", "2", "a", "b"]));
}

// ============================================================================
// Section C — Property descriptors (writable/enumerable/configurable) + freeze
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Property descriptors + Object.freeze/seal/preventExtensions");

  // A property is really a DESCRIPTOR with three boolean flags plus a value:
  //   writable     — can the value be reassigned?
  //   enumerable   — does it show up in Object.keys / for...in?
  //   configurable — can the descriptor itself be changed / the prop deleted?
  // A normal literal property defaults to ALL THREE true.
  const lit = { x: 1 };
  const litDesc = dataDescriptor(lit, "x");
  console.log(`literal {x:1} descriptor:`);
  console.log(`  value=${String(litDesc.value)} writable=${litDesc.writable} enumerable=${litDesc.enumerable} configurable=${litDesc.configurable}`);
  check("literal property defaults to writable", litDesc.writable === true);
  check("literal property defaults to enumerable", litDesc.enumerable === true);
  check("literal property defaults to configurable", litDesc.configurable === true);

  // Object.defineProperty defaults EVERY flag to false (the gotcha: omitting a
  // flag does NOT inherit the literal's true defaults — it means false). So a
  // bare {value: 1} descriptor is read-only, hidden, and locked.
  const def: Record<string, number> = {};
  Object.defineProperty(def, "hidden", { value: 1 });
  const defDesc = dataDescriptor(def, "hidden");
  console.log(`Object.defineProperty(def, "hidden", {value: 1}) descriptor:`);
  console.log(`  value=${String(defDesc.value)} writable=${defDesc.writable} enumerable=${defDesc.enumerable} configurable=${defDesc.configurable}`);
  check("defineProperty defaults writable to false", defDesc.writable === false);
  check("defineProperty defaults enumerable to false", defDesc.enumerable === false);
  check("defineProperty defaults configurable to false", defDesc.configurable === false);

  // Consequence of enumerable:false — Object.keys SKIPS the property entirely.
  // (Object.getOwnPropertyNames would still list it; Object.keys is own +
  // enumerable only. This is how built-in methods stay out of your for...in.)
  check("non-enumerable 'hidden' is skipped by Object.keys (length 0)", Object.keys(def).length === 0);

  // Consequence of writable:false — in strict mode (ESM), reassignment THROWS
  // a TypeError. (In sloppy mode it would silently fail — a far worse trap.)
  const ro: Record<string, number> = {};
  Object.defineProperty(ro, "locked", { value: 1, writable: false, enumerable: true, configurable: true });
  const roAttempt = tryAssign(ro, "locked", 99);
  console.log(`assign ro["locked"] = 99 (writable:false, strict mode) -> threw=${roAttempt.threw}`);
  console.log(`  TypeError: ${roAttempt.msg}`);
  check("non-writable assignment throws TypeError in strict mode (ESM)", roAttempt.threw === true);
  check("non-writable value is unchanged after failed assign (ro.locked === 1)", ro.locked === 1);

  // Object.freeze: sets writable:false AND configurable:false on every own
  // property, AND prevents additions (seals the object). isFrozen reports it.
  // Note: freeze is SHALLOW — nested objects are still mutable (Section D).
  const frozenSrc = { a: 1, b: 2 };
  const frozen = Object.freeze(frozenSrc);
  check("Object.isFrozen(frozen) === true", Object.isFrozen(frozen) === true);
  // Cast to a mutable Record view so the RUNTIME guard (not the TS Readonly
  // check) is what rejects the write — that is the behavior under test.
  const frozenView = frozen as unknown as Record<string, number>;
  const frozenAttempt = tryAssign(frozenView, "a", 999);
  check("frozen assignment throws TypeError in strict mode", frozenAttempt.threw === true);
  check("frozen value unchanged after failed assign (frozen.a === 1)", frozen.a === 1);

  // seal: configurable:false on existing props + no new props; but existing
  // values stay WRITABLE, so you can still mutate (just not add/delete/reconfig).
  const sealedSrc = { x: 1 };
  const sealed = Object.seal(sealedSrc);
  check("Object.isSealed(sealed) === true", Object.isSealed(sealed) === true);
  (sealed as { x: number }).x = 5;
  check("sealed ALLOWS mutating an existing value (sealed.x === 5)", sealed.x === 5);

  // preventExtensions: the weakest — only blocks NEW properties; existing ones
  // keep all their flags (writable, configurable, deletable).
  const prevented = Object.preventExtensions<{ y?: number }>({ y: 1 });
  check("Object.isExtensible(prevented) === false", Object.isExtensible(prevented) === false);
}

// ============================================================================
// Section D — Shallow copy: {...o} / Object.assign — nested objects SHARE
//             (the canonical shared-mutability trap)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Shallow copy: nested objects SHARE one reference");

  // Spread / Object.assign copy ONE LEVEL: top-level primitive values are
  // copied into a new object, but nested OBJECT values are copied BY REFERENCE —
  // the copy and the original point at the SAME nested object. Mutating it
  // through either alias is visible through the other. This is the value-vs-
  // reference axis in full force (see VALUE_VS_REFERENCE).
  const a = { top: 1, nested: { x: 1 } };
  const b = { ...a }; // shallow copy
  console.log("const a = { top: 1, nested: { x: 1 } };  const b = { ...a };");
  check("shallow copy is a NEW top-level object (a !== b)", a !== b);

  // Top-level primitive: independent (a real copy of the value 1).
  b.top = 99;
  check("top-level primitive is INDEPENDENT (a.top still 1 after b.top = 99)", a.top === 1);

  // Nested object: SHARED. Mutating b.nested.x reaches into a.nested.x.
  b.nested.x = 42;
  check("nested object is SHARED: a.nested.x === 42 after b.nested.x = 42", a.nested.x === 42);
  check("the nested object is literally the SAME reference (a.nested === b.nested)", a.nested === b.nested);

  // Object.assign is shallow in exactly the same way.
  const c = { nested: { x: 1 } };
  const d = Object.assign({}, c);
  d.nested.x = 7;
  check("Object.assign is also shallow: c.nested.x === 7 after d.nested.x = 7", c.nested.x === 7);

  // A genuine DEEP copy must clone every level. structuredClone (Node 17+) is
  // the stdlib way; hand-rolled JSON.parse(JSON.stringify(o)) loses Dates /
  // undefined / functions / Maps. Deep copying is a later bundle — here we only
  // pin that the shallow copies above are NOT deep.
  const e = { nested: { x: 1 } };
  const deepCopy = structuredClone(e);
  deepCopy.nested.x = 100;
  check("structuredClone is DEEP: e.nested.x still 1 after deepCopy.nested.x = 100", e.nested.x === 1);
}

// ============================================================================
// Section E — TypeScript Record<Keys, Type>, index signatures, and
//             Object.keys/values/entries/fromEntries
// ============================================================================

function sectionE(): void {
  sectionBanner("E — TypeScript Record<Keys,Type>, index signatures, keys/values/entries");

  // Record<Keys, Type> — a CLOSED set of keys (a string-literal union), every
  // key required, all values the same Type. Constructed by the TS utility type
  // as a mapped type; ERASED at runtime (tsx strips it), so it is a plain JS
  // object at runtime. The compiler enforces: every key present, no extra keys
  // (excess-property check on literals), and typed access.
  type Score = Record<"a" | "b" | "c", number>;
  const score: Score = { a: 1, b: 2, c: 3 };
  console.log(`type Score = Record<"a" | "b" | "c", number>;`);
  console.log(`const score: Score = { a: 1, b: 2, c: 3 };`);
  check("Record has exactly the 3 declared keys", Object.keys(score).length === 3);
  check("typed access score.b === 2", score.b === 2);

  // Index signature [k: string]: V — an OPEN set of string keys (any string is
  // allowed), all values V. Less safe than Record: the compiler cannot list the
  // keys, and bracket access is typed `V | undefined` under noUncheckedIndexedAccess.
  const dict: { [k: string]: number } = { x: 1, y: 2 };
  console.log(`const dict: { [k: string]: number } = { x: 1, y: 2 };`);
  check("index signature dot access dict.x === 1", dict.x === 1);
  check("index signature allows ANY string key (dict['anything'] is undefined, not an error)", dict["anything"] === undefined);

  // Object.keys / values / entries observe the SAME iteration order as Section B
  // (integer-like keys ascending, then strings in insertion order). entries
  // pairs them; fromEntries rebuilds an object from pairs (round-trip).
  const r: Record<string, number> = { b: 2, a: 1, 2: 3 };
  const rKeys = Object.keys(r);
  const rValues = Object.values(r);
  const rEntries = Object.entries(r);
  console.log(`const r = { b: 2, a: 1, 2: 3 };`);
  console.log(`Object.keys(r)    -> ${JSON.stringify(rKeys)}`);
  console.log(`Object.values(r)  -> ${JSON.stringify(rValues)}`);
  console.log(`Object.entries(r) -> ${JSON.stringify(rEntries)}`);
  check("keys observe integer-first order: ['2','b','a']", JSON.stringify(rKeys) === JSON.stringify(["2", "b", "a"]));
  check("values follow the SAME key order: [3,2,1]", JSON.stringify(rValues) === JSON.stringify([3, 2, 1]));
  check('entries round-trip via fromEntries: rebuilt["a"] === 1', Object.fromEntries(rEntries)["a"] === 1);

  // Spread merge / Object.assign merge: later sources overwrite earlier on key
  // collision. Useful for defaults-then-overrides.
  const merged = { ...{ a: 1, b: 1 }, ...{ a: 2, c: 3 } };
  console.log(`{ ...{a:1,b:1}, ...{a:2,c:3} } -> ${JSON.stringify(merged)}  (later wins on 'a')`);
  check("spread merge: later source wins on collision (a === 2)", merged.a === 2);
  check("spread merge: earlier-only key kept (b === 1)", merged.b === 1);
  check("spread merge: new key added (c === 3)", merged.c === 3);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("objects_records.ts — Phase 1 bundle (Language Foundations).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: JS objects are string-keyed records shared BY REFERENCE.");
  console.log("TS Record<K,V> / index signatures are ERASED at runtime — the traps");
  console.log("below apply to every TS object too.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
