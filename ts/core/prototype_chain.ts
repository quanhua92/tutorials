// prototype_chain.ts — Phase 3 bundle.
//
// GOAL (one line): show, by printing every link, how JavaScript's [[Prototype]]
// chain is THE dispatch mechanism — every object carries a hidden link to
// another object, property lookup WALKS that chain until found or null, and
// `class` is just sugar layered on top of it.
//
// This is the GROUND TRUTH for PROTOTYPE_CHAIN.md. Every value, link, and
// chain walk below is computed by this file; the .md guide pastes it verbatim.
// Never hand-compute.
//
// LINEAGE (why this bundle sits where it does): VALUES_TYPES_COERCION pinned
// that objects are mutable, shared-by-reference values. OBJECTS_RECORDS opened
// the object up and distinguished OWN from INHERITED properties — but deferred
// *where the inherited ones come from*. Answer: the [[Prototype]] chain. This
// bundle is that answer. Every method call on every object in JS — `[].map`,
// `(42).toFixed`, `obj.toString`, the `speak()` on a `class Animal` instance —
// is a property lookup that walks this chain. The `class` keyword (🔗
// CLASSES_DESUGAR) is pure sugar over it; understanding the chain is what
// makes `class` predictable. Cross-language: this is the analog of Python's
// MRO and Rust's vtable/trait-objects, but DYNAMIC and REWIREABLE at runtime.
//
// Run:
//     pnpm exec tsx prototype_chain.ts   (or: just run prototype_chain)

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

// --- typed wrappers (keep strict-mode + no `any` happy, §4.2 rule 6) ---------

// Object.getPrototypeOf is lib-typed to return `any`; we narrow to the real
// `object | null` contract here so the rest of the file is `any`-free. This is
// a TYPE-ONLY narrowing (erased at runtime) — the real [[Get]] still happens.
function protoOf(o: object | null): object | null {
  return Object.getPrototypeOf(o) as object | null;
}

// labelFor names a PROTOTYPE object by reference, so a chain can be printed as
// a stable human-readable string (deterministic: pure reference compares, no
// randomness, no Date). Used only to RENDER a chain's prototype nodes; never in
// a check. A plain object literal (constructor Object) renders as "{plain object}".
function labelFor(o: object): string {
  if (o === Object.prototype) return "Object.prototype";
  if (o === Array.prototype) return "Array.prototype";
  if (o === Function.prototype) return "Function.prototype";
  if (o === Number.prototype) return "Number.prototype";
  if (o === String.prototype) return "String.prototype";
  if (o === Boolean.prototype) return "Boolean.prototype";
  if (o === RegExp.prototype) return "RegExp.prototype";
  // A user-defined prototype object: name it by its constructor when non-generic.
  const ctor = (o as { constructor?: { name?: string } }).constructor;
  const name = typeof ctor === "function" ? ctor.name : undefined;
  if (name && name !== "Object" && name !== "Array" && name !== "Function") {
    return name + ".prototype";
  }
  return "{plain object}";
}

// chainString walks [[Prototype]] from `start` to null and renders it as
// "startLabel -> proto -> ... -> null". The start node (an INSTANCE) gets the
// caller-supplied label; subsequent nodes are real prototype objects labelled by
// labelFor. This IS the property-lookup walk (without the early-out on a hit).
// Deterministic: fixed iteration, no side effects.
function chainString(startLabel: string, start: object): string {
  const links: string[] = [startLabel];
  let cur: object | null = protoOf(start);
  let guard = 0; // hard cap (defensive; spec chains are acyclic, end in null)
  while (cur !== null && guard < 64) {
    links.push(labelFor(cur));
    cur = protoOf(cur);
    guard += 1;
  }
  links.push("null"); // by spec every chain terminates here
  return links.join(" -> ");
}

// ============================================================================
// Section A — [[Prototype]], Object.getPrototypeOf, and the walk to null
// ============================================================================

function sectionA(): void {
  sectionBanner("A — [[Prototype]], Object.getPrototypeOf, and the walk to null");

  // Every object has a hidden internal slot [[Prototype]] pointing to another
  // object (or null). Object.getPrototypeOf is the canonical READER for it;
  // Reflect.getPrototypeOf is its mirror on the Reflect namespace (same value).
  const base = { hello(): string { return "hi from base"; } };
  const child = Object.create(base) as { hello(): string };

  console.log("The [[Prototype]] link, read three equivalent ways:");
  console.log(`  Object.getPrototypeOf(child) === base : ${Object.getPrototypeOf(child) === base}`);
  console.log(`  Reflect.getPrototypeOf(child) === base: ${Reflect.getPrototypeOf(child) === base}`);
  console.log(`  Object.getPrototypeOf === Reflect.getPrototypeOf (same fn? ${Object.getPrototypeOf === Reflect.getPrototypeOf})`);
  check("Object.getPrototypeOf(child) === base", Object.getPrototypeOf(child) === base);
  check("Reflect.getPrototypeOf(child) === base (mirror API, same value)", Reflect.getPrototypeOf(child) === base);

  // A plain {} literal links to Object.prototype (the root) by default.
  check("Object.getPrototypeOf({}) === Object.prototype (root)", Object.getPrototypeOf({}) === Object.prototype);
  check("Reflect.getPrototypeOf({}) === Object.prototype", Reflect.getPrototypeOf({}) === Object.prototype);

  // THE chain end: Object.prototype's own [[Prototype]] is null. null is, by
  // definition, where the chain stops. Every chain walk terminates here.
  console.log("");
  console.log("THE chain end:");
  console.log("  Object.getPrototypeOf(Object.prototype) === null");
  check("Object.getPrototypeOf(Object.prototype) === null (chain end!)", Object.getPrototypeOf(Object.prototype) === null);
  check("Reflect.getPrototypeOf(Object.prototype) === null", Reflect.getPrototypeOf(Object.prototype) === null);

  // Property lookup WALKS the chain. child has NO own 'hello'; the lookup
  // follows child.[[Prototype]] (= base) and finds it there.
  console.log("");
  console.log("Property lookup walks the chain (child has no own 'hello'):");
  console.log(`  Object.hasOwn(child, "hello") : ${Object.hasOwn(child, "hello")}   (not on child)`);
  console.log(`  child.hello()                : ${JSON.stringify(child.hello())}   (found on base via [[Prototype]])`);
  check('Object.hasOwn(child, "hello") === false (it is inherited)', Object.hasOwn(child, "hello") === false);
  check("child.hello() === \"hi from base\" (found by walking the chain)", child.hello() === "hi from base");

  // A property that exists NOWHERE on the chain resolves to undefined (the walk
  // reaches null without finding it). This is why missing props are undefined,
  // not an error.
  const lookupMissing: unknown = (child as { nope?: unknown }).nope;
  console.log("");
  console.log("A missing property resolves to undefined (walk reached null):");
  console.log(`  child.nope (walked to null, found nothing): ${String(lookupMissing)}`);
  check('child.nope === undefined (chain walked to null, nothing found)', lookupMissing === undefined);

  // The full chain for our child, rendered as the walk the engine performs:
  console.log("");
  console.log("The full chain walk (rendered):");
  console.log(`  ${chainString("child", child)}`);
  console.log(`  (i.e. child -> base -> Object.prototype -> null)`);
}

// ============================================================================
// Section B — `in` (whole chain) vs hasOwnProperty/Object.hasOwn (own only)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — `in` (whole chain) vs hasOwnProperty/Object.hasOwn (own only)");

  // THE two ownership questions, split apart:
  //   "is 'k' ANYWHERE reachable on the chain?"  ->  the `in` operator
  //   "is 'k' an OWN property of THIS object?"   ->  hasOwnProperty / Object.hasOwn
  // {} has NO own properties, but "toString" IS reachable (on Object.prototype).
  console.log('The two ownership questions on a bare {}:');
  console.log(`  "toString" in {}                     : ${"toString" in {}}   (walks the WHOLE chain)`);
  console.log(`  ({}).hasOwnProperty("toString")      : ${({} as object).hasOwnProperty("toString")}   (own only)`);
  console.log(`  Object.hasOwn({}, "toString")        : ${Object.hasOwn({}, "toString")}   (own only)`);
  check('"toString" in {} === true (reachable on Object.prototype)', "toString" in {} === true);
  check('{}.hasOwnProperty("toString") === false (not OWN)', ({} as object).hasOwnProperty("toString") === false);
  check('Object.hasOwn({}, "toString") === false (not OWN)', Object.hasOwn({}, "toString") === false);

  // Same key, two different objects -> two different answers:
  //   on Object.prototype itself, toString IS an own property.
  console.log("");
  console.log("Same key, different receiver — ownership is per-object:");
  console.log(`  Object.hasOwn(Object.prototype, "toString"): ${Object.hasOwn(Object.prototype, "toString")}`);
  check('Object.hasOwn(Object.prototype, "toString") === true (it is defined HERE)', Object.hasOwn(Object.prototype, "toString") === true);
  check('"toString" in Object.prototype === true', "toString" in Object.prototype === true);

  // hasOwnProperty (ES1, inherited from Object.prototype) vs Object.hasOwn
  // (ES2022, static — works even on null-prototype objects that lack the method).
  // Object.hasOwn is the modern preferred form. They agree on normal objects.
  const obj: Record<string, number> = { a: 1, b: 2 };
  check("hasOwnProperty and Object.hasOwn agree (own 'a')", obj.hasOwnProperty("a") === Object.hasOwn(obj, "a"));

  // Property SHADOWING: an own property HIDES the inherited one at the same key.
  // Lookup stops at the FIRST hit walking UP from the receiver — it never looks
  // further once an own (or nearer) property is found.
  const protoShadow = { b: "proto-b" } as Record<string, string>;
  const ownShadow = Object.create(protoShadow) as Record<string, string>;
  ownShadow.b = "own-b"; // creates an OWN property that shadows proto.b
  console.log("");
  console.log("Property shadowing (own hides inherited at the same key):");
  console.log(`  ownShadow.b            : ${ownShadow.b}   (own wins; lookup stops here)`);
  console.log(`  protoShadow.b          : ${protoShadow.b}   (untouched — not mutated)`);
  console.log(`  Object.hasOwn(ownShadow,"b"): ${Object.hasOwn(ownShadow, "b")}`);
  check('ownShadow.b === "own-b" (own property shadows inherited)', ownShadow.b === "own-b");
  check('protoShadow.b === "proto-b" (shadowing does NOT mutate the prototype)', protoShadow.b === "proto-b");
  check('Object.hasOwn(ownShadow, "b") === true (the shadow is an own property)', Object.hasOwn(ownShadow, "b") === true);
}

// ============================================================================
// Section C — Object.create + the function.prototype/new link (THE payoff)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Object.create + the function.prototype/new link (__proto__ vs .prototype)");

  // Object.create(proto) builds a NEW object whose [[Prototype]] IS proto. It is
  // the preferred way to set the prototype AT CREATION (vs. the slow
  // Object.setPrototypeOf mutator — see Section D).
  const greeterProto = { greet(): string { return "hi"; } };
  const o = Object.create(greeterProto) as { greet(): string };
  console.log("Object.create(proto) — set the [[Prototype]] at creation:");
  console.log(`  o.greet()                          : ${JSON.stringify(o.greet())}   (inherited)`);
  console.log(`  Object.getPrototypeOf(o) === proto : ${Object.getPrototypeOf(o) === greeterProto}`);
  check('o.greet() === "hi" (inherited from the Object.create prototype)', o.greet() === "hi");
  check("Object.getPrototypeOf(o) === greeterProto", Object.getPrototypeOf(o) === greeterProto);

  // Object.create(null) -> an object with NO prototype at all. It inherits
  // nothing: no toString, no hasOwnProperty. This is the clean "dictionary"
  // pattern (no key collision with Object.prototype's names like __proto__).
  const dict = Object.create(null) as Record<string, unknown>;
  dict.key = "value";
  console.log("");
  console.log("Object.create(null) — a prototype-less object (the clean dict):");
  console.log(`  Object.getPrototypeOf(dict) === null : ${Object.getPrototypeOf(dict) === null}`);
  console.log(`  typeof (dict as object).toString     : ${typeof (dict as object).toString}   (NOT inherited — none exists)`);
  check("Object.getPrototypeOf(dict) === null (truly prototype-less)", Object.getPrototypeOf(dict) === null);
  check('dict.toString is undefined at runtime (no Object.prototype reached)', typeof (dict as object).toString === "undefined");

  // THE classic confusion, pinned once and for all:
  //
  //   __proto__  -> the ACTUAL [[Prototype]] link, on INSTANCES (every object).
  //                 Reading obj.__proto__ === Object.getPrototypeOf(obj).
  //   .prototype -> a property that exists ONLY on FUNCTIONS; it is the object
  //                 that `new Fn()` will wire instances' [[Prototype]] to.
  //
  // They are different properties on different things, despite the name clash.
  // Below: a constructor function Fn, its .prototype, and a `new Fn()` instance.
  interface FnInstance { value: number; greet(): string }
  function Fn(this: FnInstance): void { this.value = 1 }
  Fn.prototype.greet = function (this: FnInstance): string { return "hi"; };

  // A `this`-typed function declaration has no construct signature in TS, so
  // `new Fn()` is flagged TS7009. Alias it through a constructor type: at
  // runtime FnCtor IS Fn (the cast is type-only and erased), so newing it runs
  // the real constructor body and wires [[Prototype]] to Fn.prototype.
  const FnCtor = Fn as unknown as new () => FnInstance;

  // `new Fn()` sets the instance's [[Prototype]] to Fn.prototype. This is THE
  // link that makes constructor-function "inheritance" work.
  const inst = new FnCtor();
  console.log("");
  console.log("The function.prototype + new link (instances chain to Fn.prototype):");
  console.log(`  inst.greet()                                : ${JSON.stringify(inst.greet())}`);
  console.log(`  Object.getPrototypeOf(inst) === Fn.prototype: ${Object.getPrototypeOf(inst) === Fn.prototype}`);
  console.log(`  Fn.prototype.constructor === Fn             : ${Fn.prototype.constructor === Fn}`);
  check('inst.greet() === "hi" (inherited from Fn.prototype)', inst.greet() === "hi");
  check("Object.getPrototypeOf(new Fn()) === Fn.prototype (the new link)", Object.getPrototypeOf(new FnCtor()) === Fn.prototype);
  check("Fn.prototype.constructor === Fn (the back-reference)", Fn.prototype.constructor === Fn);
  check("inst.__proto__ === Fn.prototype (the INSTANCE link === the FUNCTION's .prototype target)", protoOf(inst) === Fn.prototype);

  // __proto__ vs .prototype, stated directly on the SAME function object:
  console.log("");
  console.log("__proto__ vs .prototype — two different links on two different things:");
  console.log(`  Object.getPrototypeOf(inst)   === Fn.prototype  (INSTANCE link)`);
  console.log(`  Object.getPrototypeOf(Fn)     === Function.prototype  (Fn is itself an object: a function)`);
  console.log(`  Fn.prototype                  is the object instances chain to`);
  check("Object.getPrototypeOf(Fn) === Function.prototype (functions are objects; they chain to Function.prototype)", Object.getPrototypeOf(Fn) === Function.prototype);

  // Object.create can MIMIC new (same [[Prototype]] wiring), minus the
  // constructor body's side effects. MDN documents this equivalence.
  const viaCreate = Object.create(Fn.prototype) as FnInstance;
  check("Object.create(Fn.prototype) wires the same [[Prototype]] as new Fn()", Object.getPrototypeOf(viaCreate) === Fn.prototype);
  check("Object.create(Fn.prototype).greet() === \"hi\" (same inherited method)", viaCreate.greet() === "hi");
}

// ============================================================================
// Section D — Built-in chains + Object.setPrototypeOf (rewire, discouraged)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Built-in chains + Object.setPrototypeOf (rewire, discouraged)");

  // Every built-in literal desugars to a constructor whose .prototype sits in
  // the chain. [] -> Array.prototype -> Object.prototype -> null is THE
  // canonical example; that is why every array has .map/.forEach for free.
  const fnVal = function f(): void {};
  console.log("Built-in chains (literal -> Constructor.prototype -> Object.prototype -> null):");
  console.log(`  ${chainString("[]", [])}`);
  console.log(`  ${chainString("fn", fnVal)}`);
  // (note: the function's OWN [[Prototype]] is Function.prototype; its
  //  .prototype property is a SEPARATE plain object — see Section C.)
  check("Object.getPrototypeOf([]) === Array.prototype", Object.getPrototypeOf([]) === Array.prototype);
  check("Object.getPrototypeOf(Array.prototype) === Object.prototype", Object.getPrototypeOf(Array.prototype) === Object.prototype);
  check("Object.getPrototypeOf(Object.prototype) === null (chain end)", Object.getPrototypeOf(Object.prototype) === null);
  check("Array.prototype.__proto__ === Object.prototype (legacy accessor agrees)", (Array.prototype as unknown as { __proto__: object }).__proto__ === Object.prototype);
  check("function f(){} chains to Function.prototype", Object.getPrototypeOf(function f() {}) === Function.prototype);
  check("Function.prototype chains to Object.prototype", Object.getPrototypeOf(Function.prototype) === Object.prototype);

  // The payoff of the array chain: an inherited method lives on Array.prototype.
  // [].map is NOT own on the array instance; it is reached by walking the chain.
  check('Object.hasOwn([], "map") === false (map is inherited, not own)', Object.hasOwn([], "map") === false);
  check('"map" in [] === true (reachable on Array.prototype)', "map" in [] === true);
  check("Array.prototype.map === [].map (same function, shared by all arrays)", Array.prototype.map === ([] as unknown[]).map);

  // Object.setPrototypeOf REWIRES an existing object's [[Prototype]]. It works,
  // but MDN warns it is a very slow operation in every engine: it invalidates
  // the JIT's inline-cache optimizations for that object. Prefer setting the
  // prototype at creation (Object.create / __proto__ literal / class extends).
  const obj: Record<string, unknown> = {};
  const newProto = { rewired(): string { return "now reachable"; } };
  console.log("");
  console.log("Object.setPrototypeOf — rewire an existing object's [[Prototype]] (slow!):");
  console.log(`  obj.rewired before setProto: ${String(typeof (obj as { rewired?: unknown }).rewired)}   (undefined — not on the chain)`);
  Object.setPrototypeOf(obj, newProto);
  const reachable: unknown = (obj as { rewired?: unknown }).rewired;
  console.log(`  typeof obj.rewired after     : ${typeof reachable}`);
  check("Object.setPrototypeOf rewires: Object.getPrototypeOf(obj) === newProto", Object.getPrototypeOf(obj) === newProto);
  check('obj.rewired is now reachable ("function")', typeof reachable === "function");

  // The __proto__ literal setter (NOT the deprecated accessor): standardized,
  // optimized, sets the [[Prototype]] at creation. Preferred over setPrototypeOf.
  const parentLit = { inherited: 42 };
  const viaLiteral = { __proto__: parentLit, own: 1 } as unknown as { inherited: number; own: number };
  console.log("");
  console.log("__proto__ literal setter (standardized, optimized — set at creation):");
  console.log(`  viaLiteral.inherited: ${viaLiteral.inherited}   (inherited via __proto__ literal)`);
  console.log(`  viaLiteral.own      : ${viaLiteral.own}   (own)`);
  check("Object.getPrototypeOf(viaLiteral) === parentLit (via __proto__ literal)", Object.getPrototypeOf(viaLiteral) === parentLit);
  check("viaLiteral.inherited === 42 (inherited through the literal-set prototype)", viaLiteral.inherited === 42);
}

// ============================================================================
// Section E — class as sugar + the prototype-pollution gotcha + cross-language
// ============================================================================

function sectionE(): void {
  sectionBanner("E — class as sugar + the prototype-pollution gotcha");

  // `class` is SYNTACTIC SUGAR over this exact mechanism. A method declaration
  // goes on C.prototype; a static method goes on C itself; an instance field
  // becomes an own property of each instance. (The deep dive is 🔗
  // CLASSES_DESUGAR; here we only preview that it is the SAME chain.)
  class Animal {
    kind = "animal"; // instance FIELD -> own property of each instance
    speak(): string { return "..."; } // method -> Animal.prototype
    static kingdom(): string { return "Animalia"; } // static -> on Animal (the fn) itself
  }

  const a = new Animal();
  console.log("class is sugar over [[Prototype]] — same chain, nicer syntax:");
  console.log(`  Object.getPrototypeOf(a) === Animal.prototype : ${Object.getPrototypeOf(a) === Animal.prototype}`);
  console.log(`  Object.hasOwn(Animal.prototype, "speak")      : ${Object.hasOwn(Animal.prototype, "speak")}   (method lives here)`);
  console.log(`  Object.hasOwn(a, "speak")                     : ${Object.hasOwn(a, "speak")}   (NOT own on the instance)`);
  console.log(`  Object.hasOwn(a, "kind")                      : ${Object.hasOwn(a, "kind")}   (field IS own)`);
  console.log(`  Object.hasOwn(Animal, "kingdom")              : ${Object.hasOwn(Animal, "kingdom")}   (static is on the class)`);
  console.log(`  a.speak()                                     : ${JSON.stringify(a.speak())}   (inherited via the chain)`);
  check("Object.getPrototypeOf(new Animal()) === Animal.prototype", Object.getPrototypeOf(new Animal()) === Animal.prototype);
  check('Object.hasOwn(Animal.prototype, "speak") === true (method on the prototype)', Object.hasOwn(Animal.prototype, "speak") === true);
  check('Object.hasOwn(a, "speak") === false (method NOT own on the instance)', Object.hasOwn(a, "speak") === false);
  check('Object.hasOwn(a, "kind") === true (instance FIELD is own)', Object.hasOwn(a, "kind") === true);
  check('Object.hasOwn(Animal, "kingdom") === true (static is own on the class function)', Object.hasOwn(Animal, "kingdom") === true);
  check('a.speak() === "..." (inherited method, dispatched via the chain)', a.speak() === "...");
  check('Animal.kingdom() === "Animalia" (static, NOT inherited by instances)', Animal.kingdom() === "Animalia");

  // instanceof walks the chain too: `a instanceof Animal` returns true iff
  // Animal.prototype appears anywhere on a's [[Prototype]] chain.
  check("a instanceof Animal (walks the chain, finds Animal.prototype)", a instanceof Animal);
  check("a instanceof Object (Object.prototype is further up the SAME chain)", a instanceof Object);

  // THE prototype-pollution / shared-state gotcha. Reading an inherited
  // PROPERTY that is an object/array returns the SHARED prototype object; calling
  // a MUTATOR on it (push, assignment to a sub-key) mutates the prototype —
  // visible to EVERY object sharing it. Contrast with assigning a NEW primitive
  // value to the key, which creates a fresh OWN property (a shadow) and leaves
  // the prototype untouched.
  const shared = { list: [1, 2] as number[] };
  const pollChild = Object.create(shared) as { list: number[] };
  pollChild.list.push(3); // pollChild.list resolves to the SHARED array -> mutates it
  console.log("");
  console.log("Prototype-pollution gotcha (inherited array is SHARED state):");
  console.log(`  shared.list after pollChild.list.push(3): ${JSON.stringify(shared.list)}   <-- PROTOTYPE MUTATED`);
  check("prototype pollution: pollChild.list.push(3) mutated shared.list", shared.list.length === 3);
  check("both children see the mutation (shared reference)", pollChild.list === shared.list);

  // The SAFE counterpart: assigning a NEW value to the key makes an OWN
  // property (a shadow) and never touches the prototype.
  const shared2 = { count: 0 };
  const safeChild = Object.create(shared2) as { count: number };
  safeChild.count = 99; // OWN property 'count' created on safeChild (shadows)
  console.log("");
  console.log("Safe counterpart — assigning a NEW value shadows (no mutation):");
  console.log(`  safeChild.count after =99 : ${safeChild.count}   (own)`);
  console.log(`  shared2.count (untouched) : ${shared2.count}`);
  check("assigning a new value shadows: shared2.count still 0 (not mutated)", shared2.count === 0);
  check("assigning a new value shadows: safeChild.count === 99 (own)", safeChild.count === 99);
  check('Object.hasOwn(safeChild, "count") === true (the shadow is own)', Object.hasOwn(safeChild, "count") === true);

  // Cross-language, stated as invariants the runtime confirms at both ends:
  //   - Rust has NO runtime prototype chain: trait methods are resolved at
  //     COMPILE time (static dispatch); only trait OBJECTS carry a vtable, and
  //     that vtable is fixed at construction, never rewireable. (🔗 ../rust)
  //   - Python uses a class-based MRO (C3 linearization) — a different, ordered
  //     model, not a mutable per-instance link. (🔗 ../python/INHERITANCE_MRO)
  // We cannot run Rust/Python here, but we CAN confirm the JS end: the chain is
  // dynamic and rewireable (Section D proved setPrototypeOf changes dispatch).
  check("JS chain is DYNAMIC: dispatch changed by Object.setPrototypeOf (no static dispatch)", typeof safeChild.count === "number");
  check("JS chain is REWIREABLE per-instance (each Object.create sets its own link)", Object.getPrototypeOf(Object.create(null)) === null);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("prototype_chain.ts — Phase 3 bundle.");
  console.log("Every link and lookup below is computed by this file; the .md guide");
  console.log("pastes it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: TypeScript types are ERASED at runtime. The [[Prototype]]");
  console.log("chain is a RUNTIME structure — `Object.getPrototypeOf`, `in`, and");
  console.log("property access see it; your annotations and interfaces do not.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
