// value_vs_reference.ts — Phase 3 bundle (core/).
//
// GOAL (one line): show, by printing every value, how TS/JS splits the world
// into primitives (copied by VALUE) and objects (shared by REFERENCE) — pinning
// aliasing, identity (===), the mutate-vs-rebind payoff, and shallow/deep copy
// as check()'d invariants.
//
// This is the GROUND TRUTH for VALUE_VS_REFERENCE.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle is THE foundational cross-language topic): JS has
// exactly two assignment/passing regimes. Primitives (string/number/boolean/
// null/undefined/symbol/bigint) are copied on assignment and passed by VALUE —
// the receiver gets an independent slot. Objects (object/array/function) are
// passed by a SHARED REFERENCE — assignment copies the reference, not the
// object, so two names point at the SAME object and mutation is visible through
// both. JS has NO compile-time help against this shared-mutability bug class:
// no borrow checker (Rust), no value-vs-pointer teaching axis (Go). Every
// section below is explicit about copy-vs-shared because that distinction IS
// the whole game.
//
// Run:
//     pnpm exec tsx value_vs_reference.ts   (or: just run value_vs_reference)

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

// strictEq routes both operands through `unknown` so TS allows comparing ANY
// pair (e.g. {} === []) under strict mode with no `any`. The cast is TYPE-ONLY
// and erased at runtime: the real strict equality operator still runs.
function strictEq(a: unknown, b: unknown): boolean {
  return a === b;
}

// ============================================================================
// Section A — Primitives copy by VALUE (all 7 types)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Primitives copy by VALUE (all 7 types)");

  // Each of the 7 primitive types is copied on assignment: the receiver gets a
  // fresh, independent copy of the VALUE. Mutating the copy never touches the
  // original. (Primitives are also immutable — you cannot change a primitive
  // in place; "mutating" only ever rebinds the name to a new primitive.)

  // number
  let aNum = 1;
  const bNum = aNum; // bNum gets a COPY of the value 1
  aNum = 2; // rebind aNum -> 2 ; bNum is untouched
  console.log(`number : aNum=${aNum}  bNum=${bNum}   (bNum copied 1, aNum rebound to 2)`);
  check("number: bNum === 1 after aNum = 2 (copy, not alias)", bNum === 1);

  // string — immutable primitive. There is no way to "mutate" a string in
  // place; every "mutation" (toUpperCase, +, slice) produces a NEW string.
  let aStr = "hi";
  const bStr = aStr;
  aStr = aStr.toUpperCase(); // produces a new string "HI", rebinds aStr
  console.log(`string : aStr=${JSON.stringify(aStr)}  bStr=${JSON.stringify(bStr)}   (bStr copied "hi")`);
  check('string: bStr === "hi" after aStr = aStr.toUpperCase()', bStr === "hi");

  // boolean
  let aBool = true;
  const bBool = aBool;
  aBool = false;
  console.log(`boolean: aBool=${aBool}  bBool=${bBool}`);
  check("boolean: bBool === true after aBool = false", bBool === true);

  // bigint
  let aBig = 10n;
  const bBig = aBig;
  aBig = 99n;
  console.log(`bigint : aBig=${aBig}  bBig=${bBig}`);
  check("bigint: bBig === 10n after aBig = 99n", bBig === 10n);

  // symbol — every Symbol() call creates a UNIQUE symbol; assignment copies the
  // (opaque) value, so two names holding the same symbol are equal primitives.
  const aSym = Symbol("id");
  const bSym = aSym; // copies the symbol value (NOT a new Symbol() call)
  console.log(`symbol : aSym === bSym -> ${aSym === bSym}   (same symbol value copied)`);
  check("symbol: bSym === aSym (the same symbol primitive is copied)", bSym === aSym);

  // null
  let aNull: null = null;
  let bNull: null = aNull;
  bNull = null; // no other value to rebind to, but the contract holds: copy
  console.log(`null   : aNull=${aNull}  bNull=${bNull}`);
  check("null: aNull === null (primitive, copied by value)", aNull === null);

  // undefined
  let aUndef: undefined = undefined;
  const bUndef = aUndef;
  console.log(`undef  : aUndef=${aUndef}  bUndef=${bUndef}`);
  check("undefined: bUndef === undefined (primitive, copied by value)", bUndef === undefined);

  // Passing a primitive to a function copies it: the function CANNOT mutate
  // the caller's binding. (Reassigning the param is local-only — Section C
  // generalizes this to objects.)
  function bump(n: number): number {
    n = n + 1; // rebinds the LOCAL copy of the parameter
    return n;
  }
  const before = 41;
  const returned = bump(before);
  console.log(`\npass-by-value: bump(${before}) returned ${returned}, caller's before still ${before}`);
  check("primitive arg is copied: before stays 41 after bump(before)", before === 41);
  check("...but the function returned the bumped value 42", returned === 42);
}

// ============================================================================
// Section B — Objects/arrays/functions share by REFERENCE; === is identity
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Objects/arrays/functions share by REFERENCE; === is identity");

  // Assignment of an object does NOT copy the object. It copies the REFERENCE
  // (the handle/address), so two names now point at the SAME heap object.
  // Mutating through either alias is visible through both. THE headline fact.

  // object aliasing — THE pinned example
  const a = { x: 1 };
  const b = a; // b ALIASES a — same object, no copy
  b.x = 2; // mutate through the alias b
  console.log(`object : b = a; b.x = 2;  ->  a.x = ${a.x}   (a sees the mutation — shared object)`);
  check("object: a.x === 2 after b.x = 2 (a and b share ONE object)", a.x === 2);

  // arrays are objects: identical aliasing
  const arrA = [1];
  const arrB = arrA; // alias, not a copy
  arrB.push(2); // mutate through the alias
  console.log(`array  : arrB = arrA; arrB.push(2);  ->  arrA.length = ${arrA.length}, arrA = [${arrA}]`);
  check("array: arrA.length === 2 after arrB.push(2) (arrays are objects)", arrA.length === 2);

  // functions are objects too: assigning / passing a function copies the
  // reference to the same function object.
  function original(): number {
    return 7;
  }
  const aliased = original; // alias the function object
  console.log(`function: aliased === original -> ${aliased === original}; aliased() = ${aliased()}`);
  check("function: aliased === original (same function object, by reference)", aliased === original);

  // === on objects is IDENTITY (same reference), NOT structural equality.
  // Two object literals with identical shape are distinct objects -> not ===.
  console.log("");
  console.log("=== on objects compares IDENTITY (the reference), not structure:");
  const o1 = { x: 1 };
  const o2 = { x: 1 }; // structurally equal but a DIFFERENT object
  const o3 = o1; // same object as o1
  console.log(`  {} === {} (two literals)        -> ${strictEq({ x: 1 }, { x: 1 })}   (distinct objects)`);
  console.log(`  o2 === o1 (same shape)          -> ${strictEq(o2, o1)}   (still distinct objects)`);
  console.log(`  o3 === o1 (o3 = o1 alias)       -> ${strictEq(o3, o1)}   (SAME reference)`);
  console.log(`  [] === [] (two array literals)  -> ${strictEq([], [])}   (distinct arrays)`);
  check("{} === {} is false (=== is identity, not deep equality)", strictEq({}, {}) === false);
  check("[] === [] is false (distinct array objects)", strictEq([], []) === false);
  check("o2 === o1 is false (same shape, different objects)", strictEq(o2, o1) === false);
  check("o3 === o1 is true (same reference — aliased)", strictEq(o3, o1) === true);
  check("a === a is always true (a value is === to itself)", strictEq(o1, o1) === true);

  // This is why ==/=== on objects is useless for "are these equal by value?"
  // — that needs a deep-equal helper. Object.is has the same identity rule.
  check("Object.is(o1, o2) === false (identity, same as === for objects)", Object.is(o1, o2) === false);
  check("Object.is(o1, o3) === true (same reference)", Object.is(o1, o3) === true);
}

// ============================================================================
// Section C — Argument passing: MUTATE the shared object vs REBIND the local
//             (THE payoff distinction)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Argument passing: MUTATE shared object vs REBIND local (THE payoff)");

  // A function receives a COPY OF THE REFERENCE. This has two opposite
  // consequences depending on what the function body does:
  //   (1) MUTATING the shared object -> visible to the caller (same object).
  //   (2) REASSIGNING the parameter  -> LOCAL ONLY (rebinds the copy, caller
  //       still holds the original reference).
  // This single distinction is the source of most JS aliasing bugs.

  interface Box {
    x: number;
  }

  // (1) mutate: writes a field on the SHARED object -> caller sees it.
  function mutate(o: Box): void {
    o.x = 99; // mutates the SAME object the caller holds
  }
  const callerBox: Box = { x: 1 };
  mutate(callerBox);
  console.log(`mutate(callerBox)        -> callerBox.x = ${callerBox.x}   (caller SEES the mutation)`);
  check("mutate(): callerBox.x === 99 (shared object was mutated through the param)", callerBox.x === 99);

  // (2) reassign: binds the LOCAL parameter to a new object -> caller untouched.
  // The param is prefixed `_` because its incoming value is deliberately NOT
  // read — the whole point is that rebinding the local throw it away. (TS
  // convention: a `_`-prefixed param is exempt from noUnusedParameters.)
  function reassign(_o: Box): void {
    _o = { x: 99 }; // rebinds the LOCAL copy of the reference; caller's binding is NOT affected
  }
  const callerBox2: Box = { x: 1 };
  reassign(callerBox2);
  console.log(`reassign(callerBox2)      -> callerBox2.x = ${callerBox2.x}   (caller UNCHANGED — local rebind)`);
  check("reassign(): callerBox2.x === 1 (param rebind is local-only, caller untouched)", callerBox2.x === 1);

  // The same rule for arrays (they are objects). Mutating in place vs
  // reassigning the param — only the former is visible to the caller.
  function pushTo(arr: number[]): void {
    arr.push(999); // mutate the shared array -> visible
  }
  function replaceArr(_arr: number[]): void {
    _arr = [999]; // rebind local param -> NOT visible
  }
  const listA: number[] = [1, 2];
  const listB: number[] = [1, 2];
  pushTo(listA);
  replaceArr(listB);
  console.log(`pushTo(listA)            -> listA = [${listA}]   (mutation visible)`);
  console.log(`replaceArr(listB)        -> listB = [${listB}]   (reassign NOT visible)`);
  check("pushTo(): listA was mutated through the shared reference", listA.length === 3 && listA[2] === 999);
  check("replaceArr(): listB untouched by the local param rebind", listB.length === 2 && listB[1] === 2);

  // Contrast: a PRIMITIVE argument can NEVER be mutated through the param —
  // there is no shared object to write to. The caller's primitive is safe.
  function tryMutateNumber(n: number): void {
    n = n + 1000; // rebinds the LOCAL copy of the primitive value
  }
  const myNum = 5;
  tryMutateNumber(myNum);
  console.log(`\ntryMutateNumber(${myNum}) -> myNum still ${myNum}   (primitive has no shared object to mutate)`);
  check("primitive arg cannot be mutated through the param (no shared object)", myNum === 5);

  // THEREFORE: you cannot write a working swap(a, b) in JS for locals. You can
  // swap two SLOTS of an object/array (you mutate the shared container), but
  // you cannot make the caller's two variable bindings trade values.
  function impossibleSwap(x: number, y: number): void {
    const tmp = x;
    x = y;
    y = tmp; // swaps LOCAL copies only — caller's bindings are untouched
  }
  const p = 1;
  const q = 2;
  impossibleSwap(p, q);
  console.log(`impossibleSwap(p=${p}, q=${q}) -> p=${p}, q=${q}   (caller's locals cannot be swapped by a function)`);
  check("swap() cannot rebind caller's locals (pass-by-value-of-reference)", p === 1 && q === 2);
}

// ============================================================================
// Section D — Shallow copy (spread/Object.assign) vs deep copy (structuredClone)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Shallow copy (spread/Object.assign) vs deep copy (structuredClone)");

  // A SHALLOW copy duplicates ONE level: the top-level object is new, but every
  // nested object reference is COPIED AS A REFERENCE — i.e. still shared with
  // the original. Spread {...o} and Object.assign({}, o) are both shallow.

  interface Nested {
    n: { x: number };
    label: string;
  }

  // spread shallow copy — the nested object `n` is STILL SHARED.
  const originalSpread: Nested = { n: { x: 1 }, label: "a" };
  const spreadCopy: Nested = { ...originalSpread }; // top-level copied
  spreadCopy.label = "b"; // top-level field: independent (original keeps "a")
  spreadCopy.n.x = 2; // NESTED field: SHARED — original sees the mutation
  console.log("spread {...o} — top-level copied, nested SHARED:");
  console.log(`  spreadCopy.label = ${JSON.stringify(spreadCopy.label)}   original.label = ${JSON.stringify(originalSpread.label)}   (independent)`);
  console.log(`  spreadCopy.n.x   = ${spreadCopy.n.x}   original.n.x   = ${originalSpread.n.x}   (SHARED — the bug)`);
  check("spread: top-level label is independent (original.label === 'a')", originalSpread.label === "a");
  check("spread: nested n.x is SHARED (original.n.x === 2 after copy.n.x = 2)", originalSpread.n.x === 2);

  // Object.assign({}, o) is equally shallow. Object.assign MUTATES its first
  // argument (the target) and returns it.
  const assignOriginal: Nested = { n: { x: 1 }, label: "a" };
  const assignTarget: Nested = { n: { x: 1 }, label: "z" }; // a real target object
  const assignResult = Object.assign(assignTarget, assignOriginal);
  console.log("\nObject.assign(target, src) — shallow, and MUTATES the target:");
  console.log(`  assignResult === assignTarget -> ${assignResult === assignTarget}   (returns the same target)`);
  console.log(`  assignTarget.label = ${JSON.stringify(assignTarget.label)}   (target's label overwritten by source)`);
  check("Object.assign returns the (mutated) target (assignResult === assignTarget)", assignResult === assignTarget);
  check("Object.assign overwrote target.label with source's 'a'", assignTarget.label === "a");

  // Array spread [...arr] is also shallow — element objects are shared.
  const arrOriginal = [{ v: 1 }];
  const arrSpread = [...arrOriginal]; // new array, same element reference
  arrSpread[0]!.v = 2; // mutates the SHARED element object
  console.log("\n[...arr] — new array, element objects SHARED:");
  console.log(`  arrOriginal[0].v = ${arrOriginal[0]!.v}   (shared element mutated through the copy)`);
  check("[...arr]: element objects are shared (arrOriginal[0].v === 2)", arrOriginal[0]!.v === 2);

  // DEEP copy via structuredClone (built-in since ES2022 / Node 17). It
  // recursively copies EVERY level — nested objects become independent. It
  // also handles cycles, and preserves Date/Map/Set/RegExp/typed arrays.
  const deepOriginal: { n: { x: number }; list: number[]; when: Date; tags: Set<string> } = {
    n: { x: 1 },
    list: [1, 2],
    when: new Date("2024-01-15T00:00:00Z"),
    tags: new Set(["a", "b"]),
  };
  const deepClone = structuredClone(deepOriginal);
  deepClone.n.x = 99; // mutate the clone's nested object
  deepClone.list.push(3); // mutate the clone's array
  console.log("\nstructuredClone — FULLY independent (nested copied, not shared):");
  console.log(`  deepClone.n.x    = ${deepClone.n.x}   deepOriginal.n.x    = ${deepOriginal.n.x}   (independent)`);
  console.log(`  deepClone.list   = [${deepClone.list}]   deepOriginal.list   = [${deepOriginal.list}]   (independent)`);
  console.log(`  deepClone.when instanceof Date -> ${deepClone.when instanceof Date}   (Date type preserved)`);
  console.log(`  deepClone.tags  instanceof Set  -> ${deepClone.tags instanceof Set}   (Set type preserved)`);
  check("structuredClone: nested n.x is independent (original stays 1)", deepOriginal.n.x === 1);
  check("structuredClone: list is independent (original keeps [1,2])", deepOriginal.list.length === 2);
  check("structuredClone: deepClone.when is a real Date (type preserved)", deepClone.when instanceof Date);
  check("structuredClone: deepClone.tags is a real Set (type preserved)", deepClone.tags instanceof Set);
  check("structuredClone: clone is NOT the same reference as original", deepClone !== deepOriginal);

  // structuredClone handles CYCLIC references without infinite recursion.
  const cyclic: { self?: unknown } = {};
  cyclic.self = cyclic; // cycle: object references itself
  const cyclicClone = structuredClone(cyclic);
  console.log("\nstructuredClone handles cycles:");
  console.log(`  cyclic.self === cyclic            -> ${cyclic.self === cyclic}`);
  console.log(`  cyclicClone.self === cyclicClone  -> ${cyclicClone.self === cyclicClone}   (cycle re-created on the clone)`);
  console.log(`  cyclicClone === cyclic            -> ${cyclicClone === cyclic}   (still a distinct object)`);
  check("structuredClone: cycle re-created on the clone (clone.self === clone)", cyclicClone.self === cyclicClone);
  check("structuredClone: but the clone is a distinct object (clone !== original)", cyclicClone !== cyclic);

  // structuredClone THROWS on non-cloneable values: functions, DOM nodes,
  // property descriptors, etc. This is the DataCloneError.
  interface HasFn {
    fn?: () => void;
  }
  const withFn: HasFn = { fn: () => 1 };
  let threwDataCloneError = false;
  try {
    void structuredClone(withFn);
  } catch (e) {
    threwDataCloneError = e instanceof Error && e.name === "DataCloneError";
  }
  console.log("\nstructuredClone THROWS DataCloneError on functions:");
  console.log(`  structuredClone({ fn: () => 1 }) threw -> ${threwDataCloneError}   (functions are not cloneable)`);
  check("structuredClone: throws DataCloneError on a function value", threwDataCloneError);

  // The JSON round-trip (JSON.parse(JSON.stringify(x))) is the OLD deep-copy
  // hack. It LOSES a lot: Date -> string, Map/Set -> {} or [], undefined ->
  // dropped, functions -> dropped, symbols -> dropped, BigInt -> throws.
  interface MixedBag {
    when: Date;
    bag: Map<string, number>;
    gone: string | undefined;
  }
  const jsonSource: MixedBag = { when: new Date("2024-01-15T00:00:00Z"), bag: new Map([["k", 1]]), gone: undefined };
  const jsonRoundTrip = JSON.parse(JSON.stringify(jsonSource)) as Record<string, unknown>;
  console.log("\nJSON round-trip LOSSES (vs structuredClone):");
  console.log(`  jsonSource.when instanceof Date -> ${jsonSource.when instanceof Date}`);
  console.log(`  jsonRoundTrip.when instanceof Date -> ${jsonRoundTrip.when instanceof Date}   (Date became a string: ${JSON.stringify(jsonRoundTrip.when)})`);
  console.log(`  jsonSource.bag instanceof Map  -> ${jsonSource.bag instanceof Map}`);
  console.log(`  jsonRoundTrip.bag instanceof Map -> ${jsonRoundTrip.bag instanceof Map}   (Map became {})`);
  console.log(`  'gone' in jsonRoundTrip        -> ${"gone" in jsonRoundTrip}   (undefined key was DROPPED)`);
  check("JSON round-trip: Date is NOT preserved (becomes a string)", !(jsonRoundTrip.when instanceof Date));
  check("JSON round-trip: Map is NOT preserved (becomes {})", !(jsonRoundTrip.bag instanceof Map));
  check('JSON round-trip: undefined value is DROPPED (key absent)', !("gone" in jsonRoundTrip));
}

// ============================================================================
// Section E — No pointers: what JS has instead (cross-language framing)
// ============================================================================

function sectionE(): void {
  sectionBanner("E — No pointers: what JS has instead (cross-language framing)");

  // JS references are OPAQUE. Unlike Go (which exposes &/* and pointer types)
  // and C/C++ (pointer arithmetic, dereference), a JS reference is just an
  // object identity you can compare with === — you CANNOT:
  //   - take an address of a variable (there is no & operator)
  //   - dereference a reference (there is no * operator)
  //   - do pointer arithmetic (references are not integers)
  // The ONLY "address-like" operation is === / Object.is (identity).

  // The closest you can get to "boxing" a primitive into a shareable object is
  // `new Object(p)` / `new Number(p)` — but each boxing call produces a DISTINCT
  // wrapper object. So two boxed copies of the SAME primitive are NOT ===.
  const boxedA = new Number(5); // an Object wrapping 5
  const boxedB = new Number(5); // a DIFFERENT Object wrapping 5
  const primA = 5;
  const primB = 5;
  console.log("Boxing a primitive does NOT give a shared identity:");
  console.log(`  primA === primB                 -> ${primA === primB}   (primitives copy/equal by value)`);
  console.log(`  boxedA === boxedB               -> ${boxedA === boxedB}   (distinct wrapper objects)`);
  console.log(`  boxedA.valueOf() === boxedB.valueOf() -> ${boxedA.valueOf() === boxedB.valueOf()}   (same primitive inside)`);
  check("boxed primitives: primA === primB is true (value equality)", primA === primB);
  check("boxed primitives: boxedA === boxedB is FALSE (distinct objects)", boxedA === boxedB === false);
  check("boxed primitives: .valueOf() recovers the equal primitive", boxedA.valueOf() === boxedB.valueOf());

  // typeof confirms the regime: a boxed primitive is typeof "object", not the
  // primitive's own typeof. (The typeof-null lie aside, this is why you never
  // use `new Number`/`new String` in practice — it breaks typeof.)
  console.log(`  typeof 5        -> ${typeof 5}`);
  console.log(`  typeof new Number(5) -> ${typeof new Number(5)}   (boxed -> object, not number)`);
  check('typeof new Number(5) === "object" (boxing changes the runtime type)', typeof new Number(5) === "object");
  check('typeof 5 === "number" (the primitive keeps its type)', typeof 5 === "number");

  // GC reachability (the implied consequence). An object is kept alive for as
  // long as it is REACHABLE from a root (a local, a closure, a global, a
  // listener, a timer). When the last reference is dropped, the object becomes
  // unreachable and the collector may free it. WeakRef is the runtime hook
  // that lets you OBSERVE (not control) reachability — deterministically,
  // while the target is still held, deref() returns it.
  interface Node {
    id: number;
  }
  let target: Node | undefined = { id: 42 };
  const weak = new WeakRef(target); // observe without STRONG-retaining
  const derefWhileReachable = weak.deref();
  console.log("\nGC reachability — a reference is the only thing keeping an object alive:");
  console.log(`  weak.deref() while held -> ${derefWhileReachable !== undefined ? "the object" : "undefined"}   id=${derefWhileReachable?.id}`);
  check("WeakRef.deref() returns the object while it is still reachable", derefWhileReachable !== undefined && derefWhileReachable.id === 42);
  // Drop the last strong reference. We do NOT assert the object was collected
  // (GC timing is nondeterministic and must not be printed as a verified value)
  // — we only demonstrate that reachability is governed by who holds a
  // reference. Full treatment: 🔗 GARBAGE_COLLECTION.
  target = undefined;
  console.log("  (after dropping the last reference, the object becomes unreachable — GC may free it; timing is NOT asserted here)");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("value_vs_reference.ts — Phase 3 bundle (core/).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: the only two regimes are COPY (primitives) and SHARE (objects).");
  console.log("There are no pointer types, no &/*, no address-of — only object identity (===).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
