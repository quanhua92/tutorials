// arrays_tuples.ts — Phase 1 bundle.
//
// GOAL (one line): show, by printing every value, that a JS Array is a MUTABLE
// OBJECT (shared-reference semantics, not a value type), that .length is a
// writable property producing sparse holes, that sort() defaults to UTF-16
// LEXICOGRAPHIC order (THE expert trap), and that TS tuple types + TypedArrays
// layer fixed-shape / fixed-numeric constraints on top of the plain-Array
// runtime — pinning each as check()'d invariants.
//
// This is the GROUND TRUTH for ARRAYS_TUPLES.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle is where it is): a JS Array is a special OBJECT —
// "an Array exotic object" in ECMA-262 terms — that owns a `.length` property
// and indexed own-properties `0..length-1`. It is NOT a value type: assigning
// or passing an array copies the REFERENCE, never the storage, so two names can
// alias one array and a push through either is visible through both. That makes
// arrays the canonical shared-mutability object (the whole subject of
// VALUE_VS_REFERENCE). TypeScript adds two compile-time refinements that ERASE
// at runtime: tuple types (`[string, number]`) pin a fixed length and per-index
// type, and TypedArrays (`Uint8Array`) pin a contiguous block of fixed-size
// numbers. At runtime both are still just objects; `Array.isArray` and
// `instanceof` are the runtime witnesses.
//
// Run:
//     pnpm exec tsx arrays_tuples.ts   (or: just run arrays_tuples)

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
// Section A — Array is an OBJECT: typeof, Array.isArray, and mutable aliasing
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Array is an OBJECT: typeof, Array.isArray, mutable aliasing");

  // A JS Array is "an Array exotic Object" (ECMA-262 §7.3): it is an Object
  // with a [[ArrayLength]] internal slot and a magic .length property whose
  // own-indexed properties it tracks. typeof therefore reports "object", same
  // as a plain {} — the runtime cannot tell an array from an object via typeof
  // alone. The CORRECT test is Array.isArray, which checks the [[Class]] /
  // exotic-ness directly (not the duck-typed .length).
  console.log("value                   : typeof       Array.isArray?");
  console.log("----------------------- : ------------  ----------------");
  console.log(`[]                      : ${typeof []}            ${Array.isArray([])}`);
  console.log(`[1, 2, 3]               : ${typeof [1, 2, 3]}            ${Array.isArray([1, 2, 3])}`);
  console.log(`{}                      : ${typeof {}}            ${Array.isArray({})}`);
  console.log(`{ length: 0 }           : ${typeof { length: 0 }}            ${Array.isArray({ length: 0 })}   (array-LIKE, not Array)`);
  console.log(`"abc"                   : ${typeof "abc"}             ${Array.isArray("abc")}   (string is iterable, not Array)`);
  console.log(`null                    : ${typeof null}            ${Array.isArray(null)}`);

  check('typeof [] === "object" (arrays ARE objects)', typeof [] === "object");
  check("Array.isArray([]) === true", Array.isArray([]) === true);
  check("Array.isArray([1,2,3]) === true", Array.isArray([1, 2, 3]) === true);
  check('Array.isArray("abc") === false (string is NOT an array)', Array.isArray("abc") === false);
  check("Array.isArray({ length: 0 }) === false (array-like is NOT Array)", Array.isArray({ length: 0 }) === false);
  check("Array.isArray({}) === false", Array.isArray({}) === false);
  check("Array.isArray(null) === false", Array.isArray(null) === false);

  // THE HEADLINE: arrays are MUTABLE OBJECTS passed by SHARED REFERENCE. `const
  // b = a` does NOT copy storage — b and a are two NAMES for one array object.
  // Mutating through either name is visible through both (aliasing). Contrast
  // with primitives, which copy on assignment (Section A of VALUES_TYPES_COERCION).
  console.log("");
  console.log("Alias demo: const b = a makes b and a ONE object (no copy):");
  const a = [1, 2];
  const b = a; // b ALIASES a — same array object, no new storage
  console.log(`  a = [1, 2]              -> a = ${JSON.stringify(a)}`);
  console.log(`  const b = a            -> b === a ? ${b === a}   (same reference)`);
  b.push(3); // mutating through the alias
  console.log(`  b.push(3)              -> a = ${JSON.stringify(a)}   (mutation visible through a!)`);
  check("arrays alias: b === a (same reference)", b === a);
  check("arrays alias: a.length === 3 after b.push(3)", a.length === 3);
  check("arrays alias: a[2] === 3 (push through alias)", a[2] === 3);

  // Passing an array into a function passes the REFERENCE: the callee's writes
  // to elements are visible to the caller. (This is the shared-mutability bug
  // class — the full treatment is VALUE_VS_REFERENCE.)
  console.log("");
  console.log("Pass-by-reference demo: callee's element write is visible to caller:");
  function pushTwice(arr: number[]): void {
    arr.push(100);
    arr.push(200);
  }
  const original = [0];
  pushTwice(original);
  console.log(`  original = [0]; pushTwice(original) -> original = ${JSON.stringify(original)}`);
  check("pass-by-shared-reference: callee mutated caller's array", original.length === 3 && original[2] === 200);
}

// ============================================================================
// Section B — .length is WRITABLE: truncation + sparse holes + map-skips-holes
// ============================================================================

function sectionB(): void {
  sectionBanner("B — .length is WRITABLE: truncation + sparse holes + map-skips-holes");

  // Unlike a Go slice header (len is a field) or a Rust Vec (len() is a
  // method), a JS array's .length is a WRITABLE OWN-PROPERTY. Setting it
  // smaller TRUNCATES the array (drops high-index elements); setting it larger
  // EXTENDS it with HOLES (sparse slots, not the value undefined).
  const truncate: number[] = [1, 2, 3, 4, 5];
  console.log(`truncate = ${JSON.stringify(truncate)}  (length ${truncate.length})`);
  truncate.length = 1;
  console.log(`truncate.length = 1   -> truncate = ${JSON.stringify(truncate)}  (4 elements dropped)`);
  check("arr.length = 1 truncates the array", truncate.length === 1);
  check("truncated arr[0] === 1", truncate[0] === 1);
  check("truncated arr[1] === undefined (gone)", truncate[1] === undefined);

  // Expanding .length creates HOLES: indexes that don't exist as own
  // properties, but which read back as `undefined`. A hole is NOT the same as
  // the value `undefined` stored at an index — see the `in` / hasOwnProperty
  // distinction below.
  const grow: number[] = [1, 2];
  grow.length = 4;
  console.log("");
  console.log(`grow = [1, 2]; grow.length = 4  -> length ${grow.length}, indexes [${grow.map((v) => v === undefined ? "<hole>" : v).join(", ")}]`);
  check("arr.length = 4 expands the array", grow.length === 4);
  check("expanded index 2 is a HOLE (not an own property)", !(2 in grow));
  check("expanded index 2 reads undefined (holes read as undefined)", grow[2] === undefined);
  check("expanded index 0 still owns its value", 0 in grow && grow[0] === 1);

  // THE SPARSE-ARRAY TRAP: array methods treat HOLES and explicit `undefined`
  // ENTRIES differently. `.map` (and `.forEach`, `.filter`, `.reduce`...)
  // SKIP holes entirely — the callback is never invoked for a hole. But they
  // DO call the callback for an explicit `undefined` value. This is the
  // "sparse vs dense" distinction that bites when you build an array with
  // `new Array(N)` or with `arr.length = N` and then `.map` over it expecting
  // N invocations.
  const sparse: number[] = [];
  sparse[0] = 1;
  sparse[2] = 3; // index 1 is NEVER assigned -> it's a HOLE
  console.log("");
  console.log(`sparse: sparse[0]=1; sparse[2]=3  -> length ${sparse.length}, "1 in sparse" = ${1 in sparse}`);
  let sparseCalls = 0;
  const sparseMapped = sparse.map((x): string => {
    sparseCalls++;
    return `v=${x}`;
  });
  console.log(`sparse.map(...) called the callback ${sparseCalls} times (skipped the hole at index 1)`);
  console.log(`sparseMapped = ${JSON.stringify(sparseMapped)}  (length ${sparseMapped.length}, index 1 is still a hole)`);
  check("sparse map SKIPS the hole: callback called 2 times (not 3)", sparseCalls === 2);
  check("sparse map result preserves length 3", sparseMapped.length === 3);
  check("sparse map result preserves the hole at index 1", !(1 in sparseMapped));
  check("sparse map result owns index 0 and 2", 0 in sparseMapped && 2 in sparseMapped);

  // Contrast: a DENSE array with explicit `undefined` at index 1. The callback
  // IS invoked for the undefined value — 3 calls, no holes.
  const dense: (number | undefined)[] = [1, undefined, 3];
  let denseCalls = 0;
  dense.map((): void => {
    denseCalls++;
  });
  console.log("");
  console.log(`dense = [1, undefined, 3]; dense.map(...) called the callback ${denseCalls} times (visited the undefined)`);
  check("dense with explicit undefined: callback called 3 times", denseCalls === 3);
  check('dense index 1 is an own property ("1 in dense")', 1 in dense);
}

// ============================================================================
// Section C — sort() default is LEXICOGRAPHIC by UTF-16 (THE expert trap)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — sort() default is LEXICOGRAPHIC by UTF-16 (THE expert trap)");

  // ECMA-262 / MDN: "The default sort order is ascending, built upon converting
  // the elements into strings, then comparing their sequences of UTF-16 code
  // unit values." That means [10, 2, 1].sort() becomes [1, 10, 2] — because the
  // STRING "10" sorts before the STRING "2" (the first char "1" < "2"). This is
  // the single most-cited JS array gotcha: sort() WITHOUT a comparator is NOT a
  // numeric sort. NOTE: sort() MUTATES in place AND returns the same array
  // (not a copy) — see Section D.
  const nums = [10, 2, 1, 21];
  const sortedDefault = nums.sort();
  console.log(`[10, 2, 1, 21].sort()  -> [${sortedDefault.join(", ")}]   (LEXICOGRAPHIC, not numeric!)`);
  check("sort() default is lexicographic: [10,2,1,21] -> [1, 10, 2, 21]", sortedDefault.join(",") === "1,10,2,21");
  check("sort() returns the SAME array (mutates in place)", sortedDefault === nums);

  // Worked smallest-scale trace: WHY [10, 2, 1] -> [1, 10, 2]. Each element is
  // ToString'd, then compared char-by-char by UTF-16 code unit.
  console.log("");
  console.log("Worked trace: why [10, 2, 1].sort() -> [1, 10, 2]");
  console.log(`  step 1: ToString each -> ["${String(10)}", "${String(2)}", "${String(1)}"]`);
  console.log(`  step 2: compare UTF-16 code units char-by-char:`);
  console.log(`    "1"  vs "10" : share first char "1" (${("1").charCodeAt(0)}); "1" is shorter   -> "1"  < "10"`);
  console.log(`    "10" vs "2"  : first char "1" (${("1").charCodeAt(0)}) < "2" (${("2").charCodeAt(0)})   -> "10" < "2"`);
  console.log(`  step 3: ascending order  "1" < "10" < "2"  ->  [1, 10, 2]`);
  check('"1".charCodeAt(0) === 49', "1".charCodeAt(0) === 49);
  check('"2".charCodeAt(0) === 50 (so "10" < "2" lexicographically)', "2".charCodeAt(0) === 50);

  // THE FIX: always pass an explicit comparator. For numbers, (a, b) => a - b
  // gives ascending numeric order; (a, b) => b - a gives descending. The
  // comparator must return a number <0, 0, or >0 (NOT a boolean).
  const nums2 = [10, 2, 1, 21];
  nums2.sort((x, y) => x - y); // numeric ascending
  console.log("");
  console.log(`[10, 2, 1, 21].sort((a, b) => a - b)  -> [${nums2.join(", ")}]   (numeric ascending)`);
  check("sort((a,b)=>a-b) gives numeric ascending [1, 2, 10, 21]", nums2.join(",") === "1,2,10,21");

  const nums3 = [10, 2, 1, 21];
  nums3.sort((x, y) => y - x); // numeric descending
  console.log(`[10, 2, 1, 21].sort((a, b) => b - a)  -> [${nums3.join(", ")}]   (numeric descending)`);
  check("sort((a,b)=>b-a) gives numeric descending [21, 10, 2, 1]", nums3.join(",") === "21,10,2,1");

  // Strings sort fine by default — but locale-aware ordering needs
  // localeCompare (e.g. German ä between a and b, not after z):
  const words = ["banana", "cherry", "apple"];
  words.sort();
  console.log("");
  console.log(`["banana","cherry","apple"].sort()  -> [${words.join(", ")}]   (lexicographic works for pure ASCII strings)`);
  check("string sort: [banana,cherry,apple] -> [apple,banana,cherry]", words.join(",") === "apple,banana,cherry");

  // Stability: since ES2019 (V8 has done this since v7.0 / Node 11), sort() is
  // GUARANTEED stable — equal-comparator elements keep their original order.
  const pairs: ReadonlyArray<readonly [string, number]> = [
    ["b", 1],
    ["a", 2],
    ["b", 3],
    ["a", 4],
  ];
  const copy = pairs.map((p) => [p[0], p[1]] as [string, number]);
  copy.sort((x, y) => (x[0] < y[0] ? -1 : x[0] > y[0] ? 1 : 0)); // sort by letter only
  console.log("");
  console.log(`stable sort by letter: [${copy.map((p) => `(${p[0]},${p[1]})`).join(", ")}]   (ties keep input order)`);
  check("sort is stable: (b,1) before (b,3), (a,2) before (a,4)", copy[0]![1] === 2 && copy[1]![1] === 4 && copy[2]![1] === 1 && copy[3]![1] === 3);
}

// ============================================================================
// Section D — MUTATE-in-place vs RETURN-new methods; spread = SHALLOW copy
// ============================================================================

function sectionD(): void {
  sectionBanner("D — MUTATE-in-place vs RETURN-new methods; spread = SHALLOW copy");

  // The single most important method-axis on Array: which methods MUTATE the
  // receiver and which return a NEW array (leaving the source untouched). The
  // mutate-in-place set is the shared-reference bug class made literal.
  const mutating: ReadonlyArray<readonly [string, string]> = [
    ["push(...)",       "append to end, returns new length"],
    ["pop()",           "remove from end, returns removed element"],
    ["shift()",         "remove from start, returns removed element"],
    ["unshift(...)",    "prepend to start, returns new length"],
    ["splice(...)",     "add/remove/replace anywhere, returns removed"],
    ["sort([cmp])",     "sort in place, returns same array"],
    ["reverse()",       "reverse in place, returns same array"],
    ["fill(v,s,e)",     "write v into [s,e), returns same array"],
    ["copyWithin(...)", "copy a range to another range in place"],
  ];
  const returning: ReadonlyArray<readonly [string, string]> = [
    ["map(fn)",      "new array, each element transformed"],
    ["filter(fn)",   "new array, only elements passing the predicate"],
    ["slice(s,e)",   "new array, shallow copy of a range"],
    ["concat(...)",  "new array, this + args flattened one level"],
    ["flat(d=1)",    "new array, sub-arrays flattened up to depth d"],
    ["flatMap(fn)",  "new array, map then flat(1)"],
    ["[...arr]",     "new array, shallow copy via spread"],
  ];
  console.log("MUTATE-in-place methods (the receiver changes; returns are incidental):");
  for (const [name, what] of mutating) {
    console.log(`  ${name.padEnd(16)} ${what}`);
  }
  console.log("");
  console.log("RETURN-new methods (PURE: receiver is never touched):");
  for (const [name, what] of returning) {
    console.log(`  ${name.padEnd(16)} ${what}`);
  }

  // Assert the distinction directly: map() leaves the SOURCE unchanged; the
  // returned array is a different object.
  const src = [1, 2, 3];
  const doubled = src.map((x): number => x * 2);
  console.log("");
  console.log(`src = ${JSON.stringify(src)};  const doubled = src.map(x => x * 2);`);
  console.log(`  src     = ${JSON.stringify(src)}   (unchanged)`);
  console.log(`  doubled = ${JSON.stringify(doubled)}   (a NEW array)`);
  check("map returns a new array (different reference)", doubled !== src);
  check("map leaves source unchanged: src still [1,2,3]", src.length === 3 && src[0] === 1);
  check("map transforms: doubled === [2,4,6]", doubled.length === 3 && doubled[0] === 2 && doubled[2] === 6);

  // push() MUTATES in place; it returns the new length (a number), NOT a new
  // array — a common mistake is `arr = arr.push(x)` which overwrites arr with
  // a number.
  const target = [1];
  const pushReturn = target.push(2, 3);
  console.log("");
  console.log(`target = [1];  const r = target.push(2, 3);`);
  console.log(`  target     = ${JSON.stringify(target)}   (mutated in place)`);
  console.log(`  pushReturn = ${pushReturn}   (push returns the NEW LENGTH, not an array)`);
  check("push mutates: target becomes [1,2,3]", target.length === 3 && target[2] === 3);
  check("push returns the new length (a number, not an array)", pushReturn === 3);

  // SHALLOW COPY via spread: [...arr] creates a NEW outer array, but the
  // element references are shared. For nested arrays/objects, mutating a
  // nested object through the copy is visible in the original — the copy is
  // only one level deep. (Deep copy needs structuredClone or JSON round-trip.)
  const nested: number[][] = [[1, 2], [3, 4]];
  const shallow = [...nested]; // new outer array, SAME inner arrays
  console.log("");
  console.log("Shallow copy via spread: const shallow = [...nested];");
  console.log(`  nested         = ${JSON.stringify(nested)}`);
  console.log(`  shallow        = ${JSON.stringify(shallow)}   (new outer array)`);
  console.log(`  shallow === nested ? ${shallow === nested}   (different outer ref)`);
  console.log(`  shallow[0] === nested[0] ? ${shallow[0] === nested[0]}   (SAME inner ref — shallow!)`);
  shallow[0]![0] = 99; // mutating the shared inner array
  console.log(`  shallow[0][0] = 99  ->  nested = ${JSON.stringify(nested)}   (inner array shared!)`);
  check("spread copy: outer arrays differ (shallow !== nested)", shallow !== nested);
  check("spread copy: inner arrays share (shallow[0] === nested[0])", shallow[0] === nested[0]);
  check("shallow copy leak: mutating nested[0][0] through the copy", nested[0]![0] === 99);

  // The query / search methods — none mutate. at(-1) is the negative-index
  // reader (ES2022); indexOf/includes return booleans/positions; find /
  // findIndex / some / every take predicates; reduce folds.
  const arr = [10, 20, 30, 40, 50];
  console.log("");
  console.log(`arr = ${JSON.stringify(arr)}`);
  console.log(`  arr.at(-1)         = ${arr.at(-1)}    (negative index, reads LAST)`);
  console.log(`  arr.at(-2)         = ${arr.at(-2)}    (second-to-last)`);
  console.log(`  arr.at(0)          = ${arr.at(0)}     (same as arr[0] but no |undefined)`);
  console.log(`  arr.at(99)         = ${String(arr.at(99))}  (out of range -> undefined)`);
  console.log(`  arr.indexOf(30)    = ${arr.indexOf(30)}     (first index of 30)`);
  console.log(`  arr.includes(40)   = ${arr.includes(40)}    (membership)`);
  console.log(`  arr.find(x => x>25)= ${arr.find((x) => x > 25)}    (first matching element)`);
  console.log(`  arr.findIndex(x=>x>25)= ${arr.findIndex((x) => x > 25)}  (first matching index)`);
  console.log(`  arr.some(x => x>40)= ${arr.some((x) => x > 40)}    (at least one matches)`);
  console.log(`  arr.every(x => x>0)= ${arr.every((x) => x > 0)}    (all match)`);
  console.log(`  arr.reduce((a,b)=>a+b, 0) = ${arr.reduce((acc, x) => acc + x, 0)}    (sum)`);
  check("arr.at(-1) returns the last element", arr.at(-1) === 50);
  check("arr.at(-2) returns second-to-last", arr.at(-2) === 40);
  check("arr.at(99) out of range returns undefined", arr.at(99) === undefined);
  check("arr.indexOf(30) === 2", arr.indexOf(30) === 2);
  check("arr.includes(40) === true", arr.includes(40) === true);
  check("arr.find(x => x > 25) === 30", arr.find((x) => x > 25) === 30);
  check("arr.findIndex(x => x > 25) === 2", arr.findIndex((x) => x > 25) === 2);
  check("arr.some(x => x > 40) === true", arr.some((x) => x > 40) === true);
  check("arr.every(x => x > 0) === true", arr.every((x) => x > 0) === true);
  check("arr.reduce((a,b)=>a+b, 0) === 150", arr.reduce((acc, x) => acc + x, 0) === 150);
}

// ============================================================================
// Section E — TS tuples, noUncheckedIndexedAccess narrowing, TypedArrays
// ============================================================================

function sectionE(): void {
  sectionBanner("E — TS tuples, noUncheckedIndexedAccess narrowing, TypedArrays");

  // TypeScript's TUPLE type pins BOTH a fixed length AND a per-index type. At
  // runtime it is STILL a plain Array (tuples are ERASED by tsx/tsc), so
  // Array.isArray(tuple) is true and .length is a normal writable property.
  // The compile-time guarantees are: arr[0] has the EXACT type at position 0
  // (not T | undefined), and arr.length is the literal length.
  type Pair = readonly [string, number]; // readonly tuple: literal length 2
  const p: Pair = ["age", 42];
  const nameTyped: string = p[0]; // exact `string` (no | undefined) — tuple index
  const countTyped: number = p[1]; // exact `number`
  console.log(`type Pair = readonly [string, number];  const p: Pair = ["age", 42];`);
  console.log(`  p[0] = ${JSON.stringify(p[0])}   (type: string, exact)`);
  console.log(`  p[1] = ${p[1]}    (type: number, exact)`);
  console.log(`  p.length = ${p.length}   (literal type 2)`);
  console.log(`  Array.isArray(p) = ${Array.isArray(p)}   (tuple is a plain Array at runtime)`);
  check("tuple p[0] === 'age'", p[0] === "age");
  check("tuple p[1] === 42", p[1] === 42);
  check("tuple length is 2", p.length === 2);
  check("tuple is a plain Array at runtime", Array.isArray(p) === true);
  check("tuple p[0] is typed exactly as string", typeof nameTyped === "string");
  check("tuple p[1] is typed exactly as number", typeof countTyped === "number");

  // Destructuring a tuple keeps the exact per-position types — unlike
  // destructuring a `T[]` (which gives `T | undefined` under
  // noUncheckedIndexedAccess).
  const [k, v] = p; // k: string, v: number — both exact
  console.log("");
  console.log(`const [k, v] = p;  ->  k = ${JSON.stringify(k)} (string), v = ${v} (number)`);
  check("tuple destructuring keeps exact types: k is string", typeof k === "string");
  check("tuple destructuring keeps exact types: v is number", typeof v === "number");

  // noUncheckedIndexedAccess lesson: indexing a `T[]` returns `T | undefined`
  // because the compiler cannot prove the index is in range — even for an
  // obviously-safe in-bounds access. You MUST narrow before using the value.
  const arr: number[] = [10, 20, 30];
  const maybe: number | undefined = arr[5]; // out of range at runtime
  console.log("");
  console.log("noUncheckedIndexedAccess: arr[5] is typed `number | undefined`:");
  console.log(`  arr = ${JSON.stringify(arr)};  const maybe = arr[5];  -> maybe = ${String(maybe)}`);
  check("arr[5] (out of range) is undefined at runtime", maybe === undefined);
  if (maybe !== undefined) {
    check("narrowed branch (number) — NOT taken", false);
  } else {
    check("else branch taken: maybe narrowed to undefined", maybe === undefined);
  }

  // In-bounds access is still typed `T | undefined`; narrow to use it.
  const first: number | undefined = arr[0]; // type says maybe undefined...
  console.log("");
  console.log(`In-bounds but still typed |undefined: const first = arr[0];  -> first = ${first}`);
  check("arr[0] runtime value is 10", first === 10);
  if (first !== undefined) {
    // narrowed to `number` — arithmetic is now type-safe
    check("after narrowing, first + 5 === 15", first + 5 === 15);
  }

  // TypedArrays: fixed-length, fixed-numeric-type, contiguous-memory views
  // (Uint8Array, Int16Array, Int32Array, Float64Array, ...). They are NOT
  // Array exotic objects — no push/pop/shift/unshift/splice; .length is FIXED
  // (writable but the array does NOT grow). Index reads return a plain number
  // (or undefined for OOB under noUncheckedIndexedAccess). Construction COERCES
  // / WRAPS out-of-range values into the element type's range (mod arithmetic
  // for integers).
  const bytes = new Uint8Array([1, 2, 3]);
  console.log("");
  console.log(`const bytes = new Uint8Array([1, 2, 3]);`);
  console.log(`  bytes.length      = ${bytes.length}   (FIXED — no push to grow it)`);
  console.log(`  bytes[0]          = ${bytes[0]}   (a plain number, not a byte object)`);
  console.log(`  typeof bytes      = ${typeof bytes}`);
  console.log(`  bytes instanceof Uint8Array = ${bytes instanceof Uint8Array}`);
  console.log(`  Array.isArray(bytes)        = ${Array.isArray(bytes)}   (NOT an Array exotic)`);
  console.log(`  "push" in bytes             = ${"push" in bytes}   (NO mutating-growth methods)`);
  check("Uint8Array.length is fixed at 3", bytes.length === 3);
  check("bytes[0] === 1 (typed array index returns a number)", bytes[0] === 1);
  check('typeof bytes === "object" (typed arrays are objects)', typeof bytes === "object");
  check("bytes instanceof Uint8Array", bytes instanceof Uint8Array);
  check("Array.isArray(Uint8Array) === false (NOT an Array exotic)", Array.isArray(bytes) === false);
  check('Uint8Array has NO push method (!("push" in bytes))', !("push" in bytes));

  // Wrapping: integer TypedArrays coerce out-of-range inputs by mod arithmetic
  // (Uint8Array wraps to [0, 255]; negative values wrap via two's complement).
  const wrapped = new Uint8Array([300, -5, 256, 0]);
  // 300 -> 300 - 256 = 44 ; -5 -> 256 - 5 = 251 ; 256 -> 0 ; 0 -> 0
  console.log("");
  console.log(`new Uint8Array([300, -5, 256, 0])  -> [${Array.from(wrapped).join(", ")}]   (each wrapped mod 256)`);
  check("Uint8Array wraps 300 -> 44 (300 mod 256)", wrapped[0] === 44);
  check("Uint8Array wraps -5 -> 251 (two's complement)", wrapped[1] === 251);
  check("Uint8Array wraps 256 -> 0", wrapped[2] === 0);
  check("Uint8Array keeps 0", wrapped[3] === 0);

  // Different element widths share the same interface but hold different bit
  // widths over the same backing buffer. Int32Array holds signed 32-bit;
  // Float64Array holds IEEE-754 double.
  const i32 = new Int32Array([1000000, -7]);
  const f64 = new Float64Array([3.14, -0]);
  console.log("");
  console.log(`new Int32Array([1000000, -7]) -> [${i32[0]}, ${i32[1]}]   (signed 32-bit)`);
  console.log(`new Float64Array([3.14, -0])  -> [${f64[0]}, ${f64[1]}]   (IEEE-754 double; note -0 prints as 0)`);
  check("Int32Array holds 32-bit signed values", i32[0] === 1000000 && i32[1] === -7);
  check("Float64Array holds 64-bit float values", f64[0] === 3.14);
  check("Float64Array preserves -0 (only Object.is can tell)", Object.is(f64[1], -0));
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("arrays_tuples.ts — Phase 1 bundle.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: an Array is a MUTABLE OBJECT (passed by shared reference).");
  console.log("TS tuples and TypedArrays are compile-time refinements ERASED at");
  console.log('runtime — Array.isArray / instanceof are the runtime witnesses.');
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
