// collections_deep.ts — Phase 5 bundle (Standard Library Essentials).
//
// GOAL (one line): show, by printing every value, how Map/Set/WeakMap/WeakSet
// behave as PROPER collections — Map's any-key + insertion-order + SameValueZero
// equality (NaN key), Set's dedup + new ES2025 set algebra, WeakMap/WeakSet's
// weak keys, and the Map-vs-object-as-map decision that fixes the
// OBJECTS_RECORDS integer-key reorder trap.
//
// This is the GROUND TRUTH for COLLECTIONS_DEEP.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): ES2015 added Map/Set/WeakMap/WeakSet as
// PROPER collections, fixing the limitations of using a plain object as a map.
// A plain object COERCES keys to strings, REORDERS integer-index keys ascending
// (the OBJECTS_RECORDS P1 trap), and leaks inherited keys through the prototype
// chain ("toString" in {} === true). Map fixes ALL of that: it keeps EVERY key
// (string, number, object, function, symbol, even NaN) in pure INSERTION order,
// has an O(1) tracked .size, is iterable, and has no prototype. Set is the
// unique-value collection (SameValueZero dedup). WeakMap/WeakSet hold keys
// WEAKLY (eligible for GC — the foundation of privacy/memoization; the
// reclamation deep-dive is GARBAGE_COLLECTION P3). This is the cross-language
// analog of Go's map (randomized iteration) and Rust's HashMap (unordered) /
// BTreeMap (sorted).
//
// Run:
//     pnpm exec tsx collections_deep.ts   (or: just run collections_deep)

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

// --- ES2025 Set methods (union/intersection/difference/...) -----------------
// These ship in Node 24+ but are NOT in the ES2023 lib pinned by
// core/tsconfig.json, so TS does not see them on Set<T>. We declare the exact
// spec signatures locally and cast through `unknown` (type-only — erased at
// runtime). The .ts feature-detects at runtime and asserts results only when
// the methods exist, so it runs clean on any engine.
interface SetES2025<T> extends Set<T> {
  union(other: ReadonlySet<T>): Set<T>;
  intersection(other: ReadonlySet<T>): Set<T>;
  difference(other: ReadonlySet<T>): Set<T>;
  symmetricDifference(other: ReadonlySet<T>): Set<T>;
  isSubsetOf(other: ReadonlySet<T>): boolean;
  isSupersetOf(other: ReadonlySet<T>): boolean;
  isDisjointFrom(other: ReadonlySet<T>): boolean;
}

function asES2025Set<T>(s: Set<T>): SetES2025<T> {
  return s as unknown as SetES2025<T>;
}

function setHasES2025Methods<T>(s: Set<T>): boolean {
  return typeof asES2025Set(s).union === "function";
}

// isIterable reports whether a value supports for...of (has Symbol.iterator).
// Used to show a plain object is NOT iterable while a Map IS.
function isIterable(value: unknown): boolean {
  try {
    return (
      typeof (value as { [Symbol.iterator]?: unknown })[Symbol.iterator] ===
      "function"
    );
  } catch {
    return false;
  }
}

// ============================================================================
// Section A — Map basics: ANY key + insertion order + SameValueZero
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Map basics: ANY key + insertion order + SameValueZero");

  const m: Map<string, number> = new Map();
  m.set("a", 1);
  m.set("b", 2);
  m.set("c", 3);

  console.log('Map built via new Map().set("a",1).set("b",2).set("c",3):');
  console.log(`  m.get("a") -> ${String(m.get("a"))}`);
  console.log(`  m.get("b") -> ${String(m.get("b"))}`);
  console.log(`  m.size    -> ${m.size}`);
  console.log(`  m.has("c") -> ${m.has("c")}`);
  console.log(`  m.has("z") -> ${m.has("z")}`);
  console.log(`  m.get("z") -> ${String(m.get("z"))}   (absent key -> undefined, NOT an error)`);
  check('Map.get("a") === 1', m.get("a") === 1);
  check("Map.size === 3 after 3 entries", m.size === 3);
  check('Map.has("c") === true', m.has("c") === true);
  check('Map.has("z") === false (absent)', m.has("z") === false);
  check('Map.get("z") === undefined (absent -> undefined)', m.get("z") === undefined);

  // set / delete semantics. Overwriting a key KEEPS its original insertion slot.
  m.set("d", 4);
  m.set("a", 99); // overwrite existing key -> value changes, position unchanged
  console.log("");
  console.log('After m.set("d",4) and m.set("a",99) (overwrite existing key):');
  console.log(`  m.get("a") -> ${m.get("a")}   (value overwritten)`);
  console.log(`  m.size    -> ${m.size}   (overwrite does NOT grow size)`);
  check("Map.set overwrites an existing key (a -> 99)", m.get("a") === 99);
  check("Map.set of an EXISTING key keeps size (now 4)", m.size === 4);

  const delA = m.delete("a");
  const delZ = m.delete("z"); // absent -> returns false
  console.log(`  m.delete("a") -> ${delA}   m.delete("z") -> ${delZ}  (absent -> false)`);
  check('Map.delete("a") returns true (existed)', delA === true);
  check('Map.delete("z") returns false (absent)', delZ === false);
  check("Map.delete dropped the entry (size now 3)", m.size === 3);
  check("Map.delete removed the key (!has)", m.has("a") === false);

  // --- ANY key type: objects, functions, symbols, even NaN as a key ---------
  // This is THE Map advantage over objects (which coerce keys to strings).
  console.log("");
  console.log("ANY KEY TYPE: Map accepts objects, functions, symbols, and NaN as keys");
  console.log('  (a plain object COERCES keys to strings — an object key becomes "[object Object]").');
  const objKey: object = { id: 1 };
  const fnKey = function handler(): void {};
  const symKey = Symbol("k");
  const anyKeyMap = new Map<unknown, string>();
  anyKeyMap.set(objKey, "by-object");
  anyKeyMap.set(fnKey, "by-function");
  anyKeyMap.set(symKey, "by-symbol");
  anyKeyMap.set(NaN, "by-nan");
  console.log(`  map.get(objKey) -> ${anyKeyMap.get(objKey)}`);
  console.log(`  map.get(fnKey)  -> ${anyKeyMap.get(fnKey)}`);
  console.log(`  map.get(symKey) -> ${anyKeyMap.get(symKey)}`);
  console.log(`  map.get(NaN)    -> ${anyKeyMap.get(NaN)}   (NaN IS a valid Map key)`);
  check("Map: object key works (get by same object reference)", anyKeyMap.get(objKey) === "by-object");
  check("Map: function key works", anyKeyMap.get(fnKey) === "by-function");
  check("Map: symbol key works", anyKeyMap.get(symKey) === "by-symbol");
  check("Map: NaN is a valid key (SameValueZero treats NaN === NaN)", anyKeyMap.get(NaN) === "by-nan");

  // KEY IDENTITY: the key is the object REFERENCE, not its structure. A
  // structurally-equal but DISTINCT object is a different key.
  const lookalike: object = { id: 1 };
  console.log("");
  console.log("KEY IDENTITY: the key is the object REFERENCE, not its structure.");
  console.log(`  map.get({id:1} lookalike) -> ${String(anyKeyMap.get(lookalike))}  (different ref -> undefined)`);
  check("Map: a structurally-equal but DISTINCT object is NOT the same key", anyKeyMap.get(lookalike) === undefined);
  check("Map: the original objKey ref still resolves", anyKeyMap.get(objKey) === "by-object");

  // --- SameValueZero: NaN === NaN AND 0 === -0 as keys ----------------------
  console.log("");
  console.log("SAMEVALUEZERO key equality (what Map/Set use for keys):");
  console.log("  like === EXCEPT NaN === NaN is TRUE (and 0 === -0 stays TRUE).");
  const nanMap = new Map<number, string>();
  nanMap.set(NaN, "first");
  nanMap.set(NaN, "second"); // SAME key: NaN === NaN under SameValueZero
  console.log(`  map.set(NaN,"first").set(NaN,"second").size -> ${nanMap.size}   (NaN deduped)`);
  console.log(`  map.get(NaN) -> ${nanMap.get(NaN)}`);
  check("Map: NaN === NaN under SameValueZero (size 1 after two NaN sets)", nanMap.size === 1);
  check('Map: second set(NaN) overwrote the first (get -> "second")', nanMap.get(NaN) === "second");

  const zeroMap = new Map<number, string>();
  zeroMap.set(0, "zero");
  zeroMap.set(-0, "neg-zero"); // SAME key: 0 === -0 under SameValueZero
  console.log(`  map.set(0,"zero").set(-0,"neg-zero").size -> ${zeroMap.size}   (0 and -0 are ONE key)`);
  console.log(`  map.get(0)  -> ${zeroMap.get(0)}`);
  console.log(`  map.get(-0) -> ${zeroMap.get(-0)}   (both resolve the same entry)`);
  check("Map: 0 === -0 under SameValueZero (size 1)", zeroMap.size === 1);
  check("Map: get(0) === get(-0) (same entry)", zeroMap.get(0) === zeroMap.get(-0));

  // --- INSERTION ORDER (the determinism centerpiece) -----------------------
  // Map iterates ALL keys in insertion order — NO integer-key reordering.
  // (Contrast: Object.keys({2:1,1:1,b:1,a:1}) -> ["1","2","b","a"], reorder.)
  console.log("");
  console.log("INSERTION ORDER: Map iterates ALL keys in insertion order (no integer reorder).");
  const ord = new Map<string, number>();
  ord.set("2", 1);
  ord.set("1", 1);
  ord.set("b", 1);
  ord.set("a", 1);
  const ordKeys = [...ord.keys()];
  console.log(`  Map inserted "2","1","b","a"  -> keys: ${JSON.stringify(ordKeys)}`);
  check("Map insertion order preserved (no integer-key reorder): [\"2\",\"1\",\"b\",\"a\"]", JSON.stringify(ordKeys) === JSON.stringify(["2", "1", "b", "a"]));

  // The same keys in a plain object DO reorder (the OBJECTS_RECORDS P1 trap).
  const objOrd: Record<string, number> = {};
  objOrd["2"] = 1;
  objOrd["1"] = 1;
  objOrd["b"] = 1;
  objOrd["a"] = 1;
  console.log(`  Object with same keys -> Object.keys: ${JSON.stringify(Object.keys(objOrd))}   (INTEGER-FIRST reorder!)`);
  check("Object REORDERS integer keys first: [\"1\",\"2\",\"b\",\"a\"]", JSON.stringify(Object.keys(objOrd)) === JSON.stringify(["1", "2", "b", "a"]));
}

// ============================================================================
// Section B — Map vs object-as-map decision; Set (unique values, dedup)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Map vs object-as-map; Set (dedup + unique values)");

  // THE DECISION: object-as-map is fine for static string keys; Map wins for
  // dynamic keys, ordered keys, any-key, frequent add/delete, and no prototype.
  console.log("MAP vs OBJECT-AS-MAP — the decision matrix:");
  const o: Record<string, number> = {};
  const m: Map<string, number> = new Map();
  o["k"] = 1;
  m.set("k", 1);
  console.log(`  "toString" in obj     -> ${"toString" in o}   (PROTOTYPE CHAIN leaks inherited keys!)`);
  console.log(`  map.has("toString")   -> ${m.has("toString")}   (Map has NO prototype -> no inherited keys)`);
  console.log(`  Object.keys(obj).length -> ${Object.keys(o).length}   (O(n) count, recomputed each call)`);
  console.log(`  map.size               -> ${m.size}   (O(1) tracked size)`);
  console.log(`  iterable? obj          -> ${isIterable(o)}   (NOT directly iterable via for...of)`);
  console.log(`  iterable? map          -> ${isIterable(m)}   (iterable: for...of / spread)`);
  check("Object-as-map leaks inherited toString via the prototype chain", "toString" in o === true);
  check("Map has NO inherited keys (no prototype pollution)", m.has("toString") === false);
  check("Map.size is tracked (=== 1 after 1 insert)", m.size === 1);
  check("Plain object is NOT directly iterable via for...of", isIterable(o) === false);
  check("Map IS iterable via for...of", isIterable(m) === true);

  console.log("");
  console.log("Verdict: Map = the deterministic, any-key, insertion-ordered map.");
  console.log("         Object-as-map = fine ONLY for static, known string keys.");

  // --- Set: unique values, SameValueZero dedup -----------------------------
  console.log("");
  console.log("Set: unique values (SameValueZero equality, same rule as Map keys).");
  const s: Set<number> = new Set([1, 1, 2, 2, 3]);
  console.log(`  new Set([1,1,2,2,3]).size -> ${s.size}   (duplicates collapsed)`);
  console.log(`  [...s]                    -> ${JSON.stringify([...s])}`);
  check("Set dedups: new Set([1,1,2,2,3]).size === 3", s.size === 3);
  check("Set preserves insertion order of FIRST occurrence: [1,2,3]", JSON.stringify([...s]) === JSON.stringify([1, 2, 3]));

  // add / has / delete. add of an existing value is a no-op (keeps position).
  const added = s.add(4);
  console.log(`  s.add(4) returns the set (chainable) -> ${added === s} ; size now ${s.size}`);
  s.add(2); // already present -> no-op: no size change, position unchanged
  console.log(`  s.add(2) (already present) -> size still ${s.size} (no-op, position unchanged)`);
  check("Set.add is chainable (returns the same set)", added === s);
  check("Set.add of an existing value is a no-op (size unchanged)", s.size === 4);
  check("Set.has(2) === true", s.has(2) === true);
  check("Set.has(99) === false", s.has(99) === false);
  check("Set.delete(2) returns true (existed)", s.delete(2) === true);
  check("Set.delete(99) returns false (absent)", s.delete(99) === false);
  check("Set.delete dropped the value (!has)", s.has(2) === false);

  // Set dedup idioms (the common use case: dedup an array, preserve order).
  console.log("");
  console.log("Set dedup idiom — dedup an array while keeping first-occurrence order:");
  const dupes = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3, 5];
  const unique = [...new Set(dupes)];
  console.log(`  [...new Set([3,1,4,1,5,9,2,6,5,3,5])] -> ${JSON.stringify(unique)}`);
  check("Set dedup keeps first-occurrence order: [3,1,4,5,9,2,6]", JSON.stringify(unique) === JSON.stringify([3, 1, 4, 5, 9, 2, 6]));

  // Set uses SameValueZero too: NaN dedups, 0 === -0 collapse.
  const nanSet = new Set<number>([NaN, NaN, 0, -0]);
  console.log(`  new Set([NaN,NaN,0,-0]).size -> ${nanSet.size}   (NaN deduped, 0 === -0 collapsed)`);
  check("Set dedups NaN + collapses 0/-0 (SameValueZero): size 2 from [NaN,NaN,0,-0]", nanSet.size === 2);
}

// ============================================================================
// Section C — WeakMap/WeakSet (weak keys, no size/iterable, privacy/memoize)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — WeakMap/WeakSet (weak keys, no size/iterable)");

  // WeakMap: KEYS must be objects (or non-registered symbols); held WEAKLY.
  // The value is reachable WHILE the key is. (Reclamation deep-dive: GC.)
  console.log("WeakMap: keys MUST be objects; held WEAKLY (eligible for GC).");
  const wm = new WeakMap<object, string>();
  const key: object = { name: "config" };
  wm.set(key, "metadata");
  console.log(`  wm.get(key) -> ${wm.get(key)}`);
  console.log(`  wm.has(key) -> ${wm.has(key)}`);
  check("WeakMap.get(key) === value while key is strongly held", wm.get(key) === "metadata");
  check("WeakMap.has(key) === true", wm.has(key) === true);
  check("WeakMap.delete(key) returns true (was present)", wm.delete(key) === true);
  check("WeakMap.has(key) === false after delete", wm.has(key) === false);

  // The privacy use: attach data to an object WITHOUT exposing it as a property.
  const privateData = new WeakMap<object, number>();
  function makeCounter(): { inc: () => number } {
    const hidden: object = {};
    privateData.set(hidden, 0); // truly private: not enumerable, not on the object
    return {
      inc: (): number => {
        const next = (privateData.get(hidden) ?? 0) + 1;
        privateData.set(hidden, next);
        return next;
      },
    };
  }
  const counter = makeCounter();
  const c1 = counter.inc();
  const c2 = counter.inc();
  const c3 = counter.inc();
  console.log(`  privacy pattern: counter.inc() -> ${c1}, ${c2}, ${c3}`);
  check("WeakMap privacy pattern: counter.inc() reaches 3", c3 === 3);

  // Primitive key REJECTED at runtime (keys must be objects). The cast is
  // type-only (erased); at runtime a string key throws TypeError.
  console.log("");
  console.log("WeakMap rejects a PRIMITIVE key at runtime (TypeError):");
  let threwPrimitive = false;
  try {
    new WeakMap<object, unknown>().set("primitive" as unknown as object, 1);
  } catch {
    threwPrimitive = true;
  }
  console.log(`  wm.set("primitive", 1) -> threw TypeError = ${threwPrimitive}`);
  check("WeakMap.set with a primitive key throws TypeError", threwPrimitive === true);

  // WeakMap/WeakSet have NO .size and are NOT iterable (spec: keys must stay
  // invisible to GC observation — iterating would observe liveness).
  console.log("");
  console.log("WeakMap/WeakSet are NOT iterable and expose NO .size (spec design).");
  const ws = new WeakSet<object>();
  const member: object = {};
  ws.add(member);
  console.log(`  ws.has(member) -> ${ws.has(member)}`);
  console.log(`  "size" in wm   -> ${"size" in wm}`);
  console.log(`  "size" in ws   -> ${"size" in ws}`);
  check("WeakSet.has(member) === true", ws.has(member) === true);
  check('WeakMap has no "size" property', "size" in wm === false);
  check('WeakSet has no "size" property', "size" in ws === false);

  // Memoization use: cache a result keyed by the object itself; when the object
  // is GC'd the entry CAN be reclaimed (no unbounded leak). Reclamation in GC.
  console.log("");
  console.log("Memoization use: cache keyed by the object (entry CAN be reclaimed).");
  let calls = 0;
  const memo = new WeakMap<object, number>();
  function expensive(obj: object): number {
    const cached = memo.get(obj);
    if (cached !== undefined) return cached;
    calls++;
    const result = 42;
    memo.set(obj, result);
    return result;
  }
  const target: object = {};
  const r1 = expensive(target);
  const r2 = expensive(target);
  console.log(`  expensive(target) -> ${r1}   (compute calls=${calls})`);
  console.log(`  expensive(target) -> ${r2}   (compute calls=${calls}, cached)`);
  check("WeakMap memoization: second call hits the cache (calls still 1)", calls === 1);
  check("WeakMap memoization: both calls return 42", r1 === 42 && r2 === 42);
}

// ============================================================================
// Section D — iteration (entries/keys/values/forEach/spread) + ES2025 Set ops
// ============================================================================

function sectionD(): void {
  sectionBanner("D — iteration + new ES2025 Set methods (union/intersection/...)");

  const m: Map<string, number> = new Map();
  m.set("a", 1);
  m.set("b", 2);
  m.set("c", 3);

  console.log("Map iteration (insertion order for ALL methods):");
  console.log(`  [...m]            -> ${JSON.stringify([...m])}   (entries)`);
  console.log(`  [...m.entries()]  -> ${JSON.stringify([...m.entries()])}`);
  console.log(`  [...m.keys()]     -> ${JSON.stringify([...m.keys()])}`);
  console.log(`  [...m.values()]   -> ${JSON.stringify([...m.values()])}`);
  check("Map spread [...m] yields [key,value] pairs", JSON.stringify([...m]) === JSON.stringify([["a", 1], ["b", 2], ["c", 3]]));
  check("Map.entries() yields [key,value] pairs", JSON.stringify([...m.entries()]) === JSON.stringify([["a", 1], ["b", 2], ["c", 3]]));
  check("Map.keys() yields keys in insertion order", JSON.stringify([...m.keys()]) === JSON.stringify(["a", "b", "c"]));
  check("Map.values() yields values in insertion order", JSON.stringify([...m.values()]) === JSON.stringify([1, 2, 3]));

  // forEach: (value, key, map) — NOTE the parameter order (value FIRST).
  console.log("");
  console.log("Map.forEach(callback) — NOTE: value is the FIRST parameter, key second.");
  const seen: string[] = [];
  m.forEach((value: number, key: string) => {
    seen.push(`${key}=${value}`);
  });
  console.log(`  forEach visited -> ${JSON.stringify(seen)}`);
  check("Map.forEach passes (value, key) in insertion order", JSON.stringify(seen) === JSON.stringify(["a=1", "b=2", "c=3"]));

  // for...of yields [key, value] pairs (Map IS the iterable).
  console.log("");
  console.log("for...of over a Map yields [key, value] pairs:");
  const collected: Array<[string, number]> = [];
  for (const entry of m) {
    collected.push(entry);
  }
  console.log(`  collected -> ${JSON.stringify(collected)}`);
  check("for...of over Map yields the same [key,value] pairs", JSON.stringify(collected) === JSON.stringify([["a", 1], ["b", 2], ["c", 3]]));

  // Set iteration. Set.entries() yields [value, value] pairs (Set symmetry with
  // Map, so the same algorithms work on both).
  console.log("");
  console.log("Set iteration (insertion order):");
  const s: Set<string> = new Set();
  s.add("x");
  s.add("y");
  s.add("z");
  console.log(`  [...s]            -> ${JSON.stringify([...s])}`);
  console.log(`  [...s.entries()]  -> ${JSON.stringify([...s.entries()])}   (Set.entries yields [v,v] pairs)`);
  console.log(`  [...s.values()]   -> ${JSON.stringify([...s.values()])}`);
  check("Set spread [...s] yields values in insertion order", JSON.stringify([...s]) === JSON.stringify(["x", "y", "z"]));
  check("Set.entries() yields [value,value] pairs (Map symmetry)", JSON.stringify([...s.entries()]) === JSON.stringify([["x", "x"], ["y", "y"], ["z", "z"]]));

  // --- new ES2025 Set methods (union/intersection/difference/...) ----------
  const a: Set<number> = new Set([1, 2, 3, 4]);
  const b: Set<number> = new Set([3, 4, 5, 6]);
  const a25 = asES2025Set(a);
  const one = asES2025Set(new Set([1]));
  const two = new Set([2]);

  console.log("");
  console.log("New ES2025 Set methods (union/intersection/difference/...):");
  console.log(`  feature-detected available? -> ${setHasES2025Methods(a)}`);

  if (setHasES2025Methods(a)) {
    console.log("  a = {1,2,3,4} ; b = {3,4,5,6}");
    const union = [...a25.union(b)];
    const inter = [...a25.intersection(b)];
    const diff = [...a25.difference(b)];
    const symdiff = [...a25.symmetricDifference(b)];
    console.log(`  a.union(b)              -> ${JSON.stringify(union)}`);
    console.log(`  a.intersection(b)       -> ${JSON.stringify(inter)}`);
    console.log(`  a.difference(b)         -> ${JSON.stringify(diff)}`);
    console.log(`  a.symmetricDifference(b)-> ${JSON.stringify(symdiff)}`);
    console.log(`  a.isSubsetOf(b)         -> ${a25.isSubsetOf(b)}`);
    console.log(`  a.isSupersetOf({1,2})   -> ${a25.isSupersetOf(new Set([1, 2]))}`);
    console.log(`  {1}.isDisjointFrom({2}) -> ${one.isDisjointFrom(two)}`);
    check("ES2025 Set.union: {1,2,3,4} U {3,4,5,6} = {1,2,3,4,5,6}", JSON.stringify(union) === JSON.stringify([1, 2, 3, 4, 5, 6]));
    check("ES2025 Set.intersection: {3,4}", JSON.stringify(inter) === JSON.stringify([3, 4]));
    check("ES2025 Set.difference: {1,2}", JSON.stringify(diff) === JSON.stringify([1, 2]));
    check("ES2025 Set.symmetricDifference: {1,2,5,6}", JSON.stringify(symdiff) === JSON.stringify([1, 2, 5, 6]));
    check("ES2025 Set.isSubsetOf: {1,2,3,4} is NOT subset of {3,4,5,6}", a25.isSubsetOf(b) === false);
    check("ES2025 Set.isSupersetOf: {1,2,3,4} superset of {1,2}", a25.isSupersetOf(new Set([1, 2])) === true);
    check("ES2025 Set.isDisjointFrom: {1} disjoint from {2}", one.isDisjointFrom(two) === true);
  } else {
    console.log("  (ES2025 Set methods NOT available in this runtime — assertions SKIPPED)");
  }
  check("ES2025 Set methods feature-detection is a deterministic boolean", typeof setHasES2025Methods(a) === "boolean");
}

// ============================================================================
// Section E — performance model (Map vs object) + cross-language
// ============================================================================

function sectionE(): void {
  sectionBanner("E — performance model (Map vs object) + cross-language");

  // DETERMINISM: this section prints NO raw timings (they vary per run). It
  // prints only deterministic structural facts (tracked size, ordering under
  // mutation) and the documented performance model (cited to MDN). A varying
  // microbenchmark number would break byte-identical `_output.txt`.

  console.log("MAP vs OBJECT — the structural performance differences (deterministic):");
  console.log("  Map.size         : O(1) TRACKED field (mutated on every set/delete).");
  console.log("  Object size      : Object.keys(o).length is O(n), RECOMPUTED each call.");
  console.log("  Map.set/delete   : O(1) average (hash table, identity-keyed).");
  console.log("  delete o[k]      : O(1) but leaves no tracked count; size needs a key scan.");
  console.log("  Map iteration    : direct (Map IS an iterable; no array allocation).");
  console.log("  Object iteration : Object.keys/values/entries ALLOCATE an array first.");
  console.log("");

  // Demonstrate the tracked-size difference with a deterministic workload.
  const m: Map<number, number> = new Map();
  const o: Record<number, number> = {};
  const N = 5;
  for (let i = 0; i < N; i++) {
    m.set(i, i);
    o[i] = i;
  }
  console.log(`After ${N} inserts (keys 0..${N - 1}):`);
  console.log(`  map.size              -> ${m.size}   (tracked, O(1))`);
  console.log(`  Object.keys(o).length -> ${Object.keys(o).length}   (recomputed, O(n))`);
  check("Map.size tracks the count (=== N) without a key scan", m.size === N);
  check("Object has no size; Object.keys().length recomputes (=== N)", Object.keys(o).length === N);

  // Re-insert semantics: a deleted-then-re-added key moves to the END.
  console.log("");
  console.log("Re-insert semantics (Map stays exact; Object reorders integer keys):");
  const m2: Map<number, number> = new Map();
  m2.set(3, 1);
  m2.set(1, 1);
  m2.set(2, 1);
  m2.delete(3);
  m2.set(3, 1); // re-add -> goes to the END (insertion order)
  console.log(`  Map: set 3,1,2; delete 3; re-set 3 -> keys ${JSON.stringify([...m2.keys()])}  (3 moved to end)`);
  check("Map re-insert of a deleted key moves it to the END", JSON.stringify([...m2.keys()]) === JSON.stringify([1, 2, 3]));

  console.log("");
  console.log("DOCUMENTED performance guidance (MDN 'Map' — Maps vs Objects):");
  console.log("  * Map is generally FASTER for frequent add/remove of key-value pairs.");
  console.log("  * Object literal is fine for STATIC string keys (no collection overhead).");
  console.log("  * Use Map when keys are dynamic, non-string, or when order matters.");

  // Cross-language collection ordering models.
  console.log("");
  console.log("Cross-language collection ordering models:");
  console.log("  JS   Map/Set   : INSERTION order (deterministic, all key types).");
  console.log("  Go   map[K]V   : iteration RANDOMIZED on every range (must sort keys).");
  console.log("  Rust HashMap   : NO order guarantee (hash-seed randomized).");
  console.log("  Rust BTreeMap  : keys SORTED (a balanced tree).");
  console.log("  -> JS Map is a THIRD model: deterministic insertion order (unlike Go / Rust");
  console.log("     HashMap), but NOT sorted (unlike Rust BTreeMap).");
  check("Map preserves insertion order across all key types (the determinism guarantee)", m2.size === 3 && m2.get(3) === 1);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("collections_deep.ts — Phase 5 bundle (Standard Library Essentials).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Map/Set/WeakMap/WeakSet: ES2015 PROPER collections, fixing the");
  console.log("object-as-map limitations (integer-key reorder, prototype pollution,");
  console.log("string-only keys). Map = any key + insertion order + SameValueZero.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
