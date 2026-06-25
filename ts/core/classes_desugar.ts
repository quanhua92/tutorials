// classes_desugar.ts — Phase 3 bundle #19.
//
// GOAL (one line): show, by printing every value, that ES6 `class` syntax is
// SYNTACTIC SUGAR over the prototype chain + constructor functions — and pin
// the headline contrast: `#private` is RUNTIME-enforced, while TS's
// `private`/`protected`/`public`/`readonly`/parameter-properties are
// COMPILE-TIME ONLY (erased, bypassable at runtime).
//
// This is the GROUND TRUTH for CLASSES_DESUGAR.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle sits where it does in Phase 3): ES6 `class` is
// NOT a new object model — it is sugar over the prototype chain
// (🔗 PROTOTYPE_CHAIN) plus constructor functions. `class C { constructor(){}
// m(){} }` desugars to `function C(){}; C.prototype.m = function(){}`.
// Understanding the desugaring makes `extends`/`super`/`static`/`#private`/
// fields predictable, because every one of them maps onto prototype
// machinery: methods → C.prototype; static → C itself; extends →
// Object.setPrototypeOf(C, Parent) + Object.setPrototypeOf(C.prototype,
// Parent.prototype); fields → assignments inside the constructor. TypeScript
// then layers `public`/`private`/`protected`/`readonly`/parameter-properties
// ON TOP — and these are PURE COMPILE-TIME annotations: they emit no code and
// have NO runtime effect (the only runtime-private mechanism is `#`). This
// bundle makes that erasure visible by reading TS-"private" fields back out
// at runtime through type-erasing casts.
//
// Run:
//     pnpm exec tsx classes_desugar.ts   (or: just run classes_desugar)

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

// hasOwn is a wrapper around Object.prototype.hasOwnProperty.call — the safe
// form that cannot be defeated by a per-instance override of `hasOwnProperty`.
function hasOwn(obj: object, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

// ============================================================================
// Section A — class = constructor + prototype (the desugaring, observed)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — class = constructor + prototype (the desugaring, observed)");

  // The 2ality canonical desugaring:
  //   class Point { constructor(x,y){...} dist(){...} }
  // desugars (conceptually) to:
  //   function Point(x,y){ this.x=x; this.y=y; }
  //   Point.prototype.dist = function(other){ ... };
  // We observe every piece of that at runtime below.
  class Point {
    x: number;
    y: number;
    constructor(x: number, y: number) {
      this.x = x;
      this.y = y;
    }
    dist(other: Point): number {
      // Pythagorean triple (3,4,5) keeps the printed result an exact integer.
      return Math.hypot(this.x - other.x, this.y - other.y);
    }
  }

  const origin = new Point(0, 0);
  const p = new Point(3, 4);

  console.log(`typeof Point                 : ${typeof Point}`);
  console.log(`Point.name                   : ${Point.name}`);
  console.log(`p instanceof Point           : ${p instanceof Point}`);
  console.log(`Object.getPrototypeOf(p) === Point.prototype : ${Object.getPrototypeOf(p) === Point.prototype}`);
  console.log(`Point === Point.prototype.constructor        : ${Point === Point.prototype.constructor}`);
  console.log(`Point.prototype.dist === p.dist (identity)   : ${Point.prototype.dist === p.dist}`);
  console.log(`p.dist(origin) [3-4-5 triple]                : ${p.dist(origin)}`);
  console.log(`p.hasOwnProperty('dist') [own?]              : ${hasOwn(p, "dist")}`);
  console.log(`Point.prototype.hasOwnProperty('dist')       : ${hasOwn(Point.prototype, "dist")}`);

  // THE FOUNDATIONAL FACTS — every check below is a piece of the desugaring.
  check("typeof Point === 'function' (a class IS a constructor function)", typeof Point === "function");
  check("p instanceof Point", p instanceof Point);
  check("Object.getPrototypeOf(p) === Point.prototype (the instance->proto link)", Object.getPrototypeOf(p) === Point.prototype);
  check("Point === Point.prototype.constructor (constructor identity)", Point === Point.prototype.constructor);
  check("Point.prototype.dist === p.dist (method is ONE shared copy on the prototype)", Point.prototype.dist === p.dist);
  check("p.hasOwnProperty('dist') === false (method is NOT an own property of the instance)", hasOwn(p, "dist") === false);
  check("Point.prototype.hasOwnProperty('dist') === true (method IS own on the prototype)", hasOwn(Point.prototype, "dist") === true);
  check("dist(3,4 from origin) === 5", p.dist(origin) === 5);

  // A class CANNOT be called without `new` (it is not an ordinary function).
  // TS types this as an error, so we route through `unknown` to demonstrate
  // the runtime reality: V8 throws TypeError "Constructor Point requires 'new'".
  let threwWithoutNew = false;
  try {
    (Point as unknown as (x: number, y: number) => void)(3, 4);
  } catch (e) {
    threwWithoutNew = (e as Error).constructor === TypeError;
  }
  check("class called without `new` throws TypeError", threwWithoutNew);
}

// ============================================================================
// Section B — instance fields (per-instance) vs static (on class) vs methods (on prototype)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — instance fields (per-instance) vs static (on class) vs methods (on prototype)");

  class Counter {
    static instanceCount = 0; // STATIC field — installed on the CLASS (one copy)
    id: number; // instance field (declared, assigned in ctor — per-instance)
    count = 0; // instance field with initializer (per-instance copy)
    constructor() {
      this.id = ++Counter.instanceCount; // static accessed via the class name
    }
    increment(): void {
      this.count++;
    }
    static of(count: number): Counter {
      // STATIC method — installed on the CLASS, callable as Counter.of(...)
      const c = new Counter();
      c.count = count;
      return c;
    }
  }

  const c1 = new Counter();
  c1.increment();
  c1.increment();
  const c2 = new Counter();
  c2.increment();
  const c3 = Counter.of(10); // static method call ALSO constructs (instanceCount -> 3)

  console.log("Three homes for a class member:");
  console.log("  instance field (count)  : on each INSTANCE  (per-instance copy)");
  console.log("  static member (of)      : on the CLASS      (single shared copy)");
  console.log("  method (increment)      : on the PROTOTYPE  (one copy, shared)");
  console.log("");
  console.log(`c1.count                   : ${c1.count}   (per-instance: c1 has its own)`);
  console.log(`c2.count                   : ${c2.count}   (per-instance: c2 has its own)`);
  console.log(`c1.id / c2.id              : ${c1.id} / ${c2.id}   (assigned from a static counter)`);
  console.log(`Counter.instanceCount      : ${Counter.instanceCount}   (STATIC: one shared slot; 3 = c1+c2+c3)`);
  console.log(`c3.count [via Counter.of]   : ${c3.count}   (static method built this instance)`);
  console.log("");
  console.log(`Counter.hasOwnProperty('instanceCount') : ${hasOwn(Counter, "instanceCount")}`);
  console.log(`Counter.hasOwnProperty('of')            : ${hasOwn(Counter, "of")}`);
  console.log(`Counter.prototype.hasOwnProperty('of')  : ${hasOwn(Counter.prototype, "of")}   (static NOT on prototype)`);
  console.log(`Counter.prototype.hasOwnProperty('increment') : ${hasOwn(Counter.prototype, "increment")}`);
  console.log(`c1.hasOwnProperty('increment')          : ${hasOwn(c1, "increment")}   (method NOT own on instance)`);
  console.log(`c1.increment === c2.increment (identity): ${c1.increment === c2.increment}`);

  // INSTANCE FIELD = per-instance (each new gets its own copy; mutating one
  // does NOT affect another). This is the desugaring reality: `count = 0;` in
  // the class body is an assignment that runs inside the constructor, so each
  // instance receives its own `count` own property.
  check("instance field is per-instance: c1.count (2) !== c2.count (1)", c1.count !== c2.count);
  check("c1.count === 2", c1.count === 2);
  check("c2.count === 1", c2.count === 1);
  check("instance field `count` IS an own property of c1", hasOwn(c1, "count") === true);

  // STATIC field/method = on the CLASS (constructor function), shared single copy.
  check("static field is on the CLASS: Counter.hasOwnProperty('instanceCount')", hasOwn(Counter, "instanceCount") === true);
  check("static field shared: instanceCount === 3 after 3 news (incl. Counter.of)", Counter.instanceCount === 3);
  check("static method is on the CLASS: Counter.hasOwnProperty('of')", hasOwn(Counter, "of") === true);
  check("static method is NOT on the prototype", hasOwn(Counter.prototype, "of") === false);
  check("static method callable as Counter.of(...)", c3.count === 10);

  // METHOD = on the PROTOTYPE (one shared copy), inherited by all instances.
  check("method is on the PROTOTYPE: Counter.prototype.hasOwnProperty('increment')", hasOwn(Counter.prototype, "increment") === true);
  check("method is NOT an own property of the instance", hasOwn(c1, "increment") === false);
  check("method identity: c1.increment === c2.increment === Counter.prototype.increment", c1.increment === c2.increment && c1.increment === Counter.prototype.increment);
}

// ============================================================================
// Section C — extends + super (the chain link; super() required before this)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — extends + super (the chain link; super() required before this)");

  class Animal {
    name: string;
    constructor(name: string) {
      this.name = name;
    }
    speak(): string {
      return `${this.name} makes a sound`;
    }
    static kingdom(): string {
      return "Animalia";
    }
  }

  class Dog extends Animal {
    constructor(name: string) {
      // `super(...)` is REQUIRED as the first statement before using `this`
      // in a derived constructor. It calls the parent constructor, which is
      // what actually allocates the instance object (ES6 model).
      super(name);
    }
    override speak(): string {
      return `${this.name} barks`;
    }
    parentSpeak(): string {
      // `super.method()` calls the parent's method, with `this` still bound
      // to the current instance (so it can read this.name).
      return super.speak();
    }
  }

  // Default derived constructor (omitted) desugars to:
  //   constructor(...args) { super(...args); }
  class Cat extends Animal {}

  const d = new Dog("Rex");
  const kitty = new Cat("Tom");

  console.log("The TWO chain links `extends` creates:");
  console.log("  (1) instance chain:  d -> Dog.prototype -> Animal.prototype -> Object.prototype -> null");
  console.log("  (2) static   chain:  Dog -> Animal -> Function.prototype -> Object.prototype -> null");
  console.log("");
  console.log(`d.speak()        : ${d.speak()}`);
  console.log(`d.parentSpeak()  : ${d.parentSpeak()}   (super.speak())`);
  console.log(`Dog.kingdom()    : ${Dog.kingdom()}   (static inherited from Animal)`);
  console.log(`kitty.name       : ${kitty.name}   (default derived ctor forwarded to super)`);
  console.log("");
  console.log(`Object.getPrototypeOf(Dog.prototype) === Animal.prototype : ${Object.getPrototypeOf(Dog.prototype) === Animal.prototype}`);
  console.log(`Object.getPrototypeOf(Dog) === Animal                     : ${Object.getPrototypeOf(Dog) === Animal}`);
  console.log(`d instanceof Dog / Animal : ${d instanceof Dog} / ${d instanceof Animal}`);

  // THE INSTANCE-CHAIN LINK — Dog.prototype's [[Prototype]] IS Animal.prototype.
  check("extends instance link: Object.getPrototypeOf(Dog.prototype) === Animal.prototype", Object.getPrototypeOf(Dog.prototype) === Animal.prototype);
  // THE STATIC-CHAIN LINK — Dog's [[Prototype]] IS Animal (so statics inherit).
  check("extends static link: Object.getPrototypeOf(Dog) === Animal (statics inherit)", Object.getPrototypeOf(Dog) === Animal);
  // instanceof walks the instance chain — d is BOTH Dog and Animal.
  check("d instanceof Dog", d instanceof Dog);
  check("d instanceof Animal (chain walk reaches Animal.prototype)", d instanceof Animal);
  // super(name) ran the parent constructor — this.name was set by Animal.
  check("super(...) ran parent constructor: d.name === 'Rex'", d.name === "Rex");
  // super.speak() calls the PARENT method with the CHILD instance as `this`.
  check("super.method() calls parent method with this=child instance", d.parentSpeak() === "Rex makes a sound");
  // Static inheritance via the static chain link.
  check("static method inherited: Dog.kingdom() === 'Animalia'", Dog.kingdom() === "Animalia");
  // Default derived constructor forwards all args to super().
  check("default derived ctor forwards to super(): kitty.name === 'Tom'", kitty.name === "Tom");
  check("default derived ctor: kitty instanceof Cat && Animal", kitty instanceof Cat && kitty instanceof Animal);

  // === super() REQUIRED before this — documented, not executed ==============
  // Referencing `this` (or implicitly returning) in a derived constructor
  // WITHOUT first calling super() throws ReferenceError at runtime (V8).
  // TypeScript catches the obvious case at COMPILE time ("'super' must be
  // called before accessing 'this' in the constructor of a derived class"),
  // so we cannot even write the failing code here — the rule is enforced at
  // TWO layers (TS compile + V8 runtime). Verified by 2ality's "Safety
  // checks" section and MDN "Using classes".
}

// ============================================================================
// Section D — #private (RUNTIME-enforced) vs TS private/protected/public (COMPILE-only)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — #private (RUNTIME-enforced) vs TS private/protected/public (COMPILE-only)");

  // ---- THE HEADLINE CONTRAST ----------------------------------------------
  // `#x`  (ES2019 private field): TRULY private. Enforced by the LANGUAGE at
  //       runtime: the stored name is mangled, the field is invisible to
  //       Object.keys, and referencing `#x` outside the class body is a
  //       SyntaxError (caught at PARSE time — you cannot even write it).
  // `private hidden` (TS keyword): COMPILE-TIME only. TS forbids access in
  //       `.ts` source, but the annotation is ERASED — at runtime `hidden`
  //       is an ordinary own property, visible in Object.keys and bypassable
  //       via a type-erasing cast. SAME for `protected` and `readonly`.

  class Priv {
    #x = 99; // ES2019+ private field — RUNTIME-enforced
    getX(): number {
      return this.#x;
    }
    bump(): void {
      this.#x++;
    }
  }

  class TsAccess {
    private hidden = 7; // TS `private` — COMPILE-TIME only, ERASED at runtime
    protected mode = "rw"; // TS `protected` — also COMPILE-TIME only, ERASED
    reveal(): number {
      return this.hidden;
    }
  }

  const pv = new Priv();
  const ta = new TsAccess();
  pv.bump(); // 99 -> 100

  console.log("#private (runtime-enforced):");
  console.log(`  pv.getX()                : ${pv.getX()}`);
  console.log(`  Object.keys(pv)          : ${JSON.stringify(Object.keys(pv))}   (#x is INVISIBLE)`);
  console.log(`  pv['#x'] [literal name]  : ${String((pv as unknown as Record<string, unknown>)["#x"])}   (storage key is mangled, not '#x')`);
  console.log("");
  console.log("TS `private`/`protected` (compile-only, erased):");
  console.log(`  ta.reveal()              : ${ta.reveal()}`);
  console.log(`  Object.keys(ta)          : ${JSON.stringify(Object.keys(ta))}   ('hidden'/'mode' ARE visible)`);
  console.log(`  ta['hidden'] [bracket]   : ${(ta as unknown as Record<string, unknown>)["hidden"]}   (runtime-accessible despite TS-private)`);

  // ---- #private checks (runtime-enforced) ---------------------------------
  check("#private: accessible via a method", pv.getX() === 100);
  check("#private: mutable inside the class body", pv.getX() === 100);
  check("#private: NOT in Object.keys (truly hidden)", Object.keys(pv).length === 0);
  check('#private: the literal name "#x" is NOT the stored key (mangled)', (pv as unknown as Record<string, unknown>)["#x"] === undefined);

  // ---- TS `private`/`protected` checks (compile-only) ---------------------
  check("TS `private`: accessible via method", ta.reveal() === 7);
  check("TS `private`: 'hidden' IS in Object.keys (NOT hidden at runtime)", Object.keys(ta).includes("hidden"));
  check("TS `protected`: 'mode' IS in Object.keys (NOT hidden at runtime)", Object.keys(ta).includes("mode"));
  // The bypass: cast through `unknown` (type-only, erased) and read/write the
  // field directly. TS forbids `ta.hidden` / `ta["hidden"]`; the cast defeats
  // the COMPILE-TIME check, proving `private` has NO runtime enforcement.
  const taErased = ta as unknown as { hidden: number; mode: string };
  taErased.hidden = 999;
  taErased.mode = "bypassed";
  check("TS `private` BYPASSED at runtime: ta.reveal() now 999 (erased, writable)", ta.reveal() === 999);
  check("TS `protected` BYPASSED at runtime: mode now 'bypassed'", taErased.mode === "bypassed");
}

// ============================================================================
// Section E — TS parameter properties + accessors + readonly + mixins + new.target
// ============================================================================

function sectionE(): void {
  sectionBanner("E — TS parameter properties + accessors + readonly + mixins + new.target");

  // ---- (1) Parameter properties — TS-only constructor sugar (ERASED) --------
  // `constructor(public id, private balance, readonly owner)` auto-creates +
  // assigns this.id / this.balance / this.owner inside the constructor. This
  // is PURE TS sugar: it desugars to the explicit `this.x = x` assignments
  // and is erased from the runtime (the modifiers have no runtime effect).
  class Account {
    constructor(
      public id: number,
      private balance: number,
      readonly owner: string,
    ) {}
    describe(): string {
      return `Account#${this.id} (${this.owner}): ${this.balance}`;
    }
  }
  const acc = new Account(1, 500, "ada");
  console.log(`(1) parameter properties:`);
  console.log(`    acc.describe()         : ${acc.describe()}`);
  console.log(`    acc.id (public)        : ${acc.id}`);
  console.log(`    acc.owner (readonly)   : ${acc.owner}`);
  console.log(`    Object.keys(acc)       : ${JSON.stringify(Object.keys(acc))}   (all 3 are real own props)`);
  check("parameter property: public id accessible", acc.id === 1);
  check("parameter property: readonly owner accessible", acc.owner === "ada");
  check("parameter property: all 3 are own properties (modifiers erased)", Object.keys(acc).length === 3);
  // `balance` is TS-private — bypassable at runtime (same erasure as Section D):
  check("parameter property: private balance runtime-accessible (erased)", (acc as unknown as { balance: number }).balance === 500);

  // ---- (2) Accessors — get/set desugar to Object.defineProperty -------------
  // `get x(){}` / `set x(v){}` install a property descriptor (with get/set
  // accessors) on the prototype, exactly like ES5's Object.defineProperty.
  class Thermostat {
    private _celsius = 20;
    get celsius(): number {
      return this._celsius;
    }
    set celsius(value: number) {
      this._celsius = value;
    }
    get fahrenheit(): number {
      return (this._celsius * 9) / 5 + 32;
    }
    set fahrenheit(f: number) {
      this._celsius = ((f - 32) * 5) / 9;
    }
  }
  const t = new Thermostat();
  t.fahrenheit = 212; // boiling point of water
  const celsiusDesc = Object.getOwnPropertyDescriptor(Thermostat.prototype, "celsius");
  console.log(`(2) accessors:`);
  console.log(`    t.fahrenheit=212 -> t.celsius : ${t.celsius}`);
  console.log(`    Thermostat.prototype 'celsius' : ${celsiusDesc !== undefined ? "get+set descriptor" : "missing"}`);
  check("accessor: set fahrenheit=212 -> celsius=100 (exactly)", t.celsius === 100);
  check("accessor: descriptor has get + set functions on the prototype", celsiusDesc !== undefined && typeof celsiusDesc?.get === "function" && typeof celsiusDesc?.set === "function");

  // ---- (3) readonly — TS-only, runtime-writable (erased) -------------------
  class Config {
    readonly apiKey: string;
    constructor(apiKey: string) {
      this.apiKey = apiKey;
    }
  }
  const cfg = new Config("secret-key");
  // `cfg.apiKey = "x"` is a TS compile error. But `readonly` is erased — at
  // runtime the field is an ordinary writable own property.
  const cfgWritable = cfg as unknown as { apiKey: string };
  cfgWritable.apiKey = "changed-at-runtime";
  console.log(`(3) readonly:`);
  console.log(`    cfg.apiKey after runtime write : ${cfg.apiKey}   (TS readonly is NOT runtime-enforced)`);
  check("TS readonly: runtime-writable (erased)", cfg.apiKey === "changed-at-runtime");

  // ---- (4) Mixins — brief pattern (runtime application) --------------------
  // The canonical TS generic mixin `<TBase>(Base) => class extends TBase {}`
  // requires `any[]` on the mixin's constructor (TS error TS2545), which
  // collides with this bundle's no-`any` rule. We show the RUNTIME mechanism
  // instead — a plain object of extra members applied to a class's PROTOTYPE
  // via Object.assign. This is what every generic mixin desugars into: shared
  // members, one copy, grafted onto the prototype chain.
  class Widget {
    shape = "rect";
    area(): number {
      return 100;
    }
  }
  interface Bordered {
    border(): number;
  }
  const BorderMixin: Bordered = {
    border() {
      return 1;
    },
  };
  function withBorder<T extends new () => Widget>(Base: T): T {
    Object.assign(Base.prototype, BorderMixin);
    return Base;
  }
  class BorderedWidget extends Widget {}
  const BorderedClass = withBorder(BorderedWidget);
  const bw = new BorderedClass() as unknown as Widget & Bordered;
  console.log(`(4) mixin:`);
  console.log(`    bw.shape / bw.border() : ${bw.shape} / ${bw.border()}`);
  console.log(`    bw.area()              : ${bw.area()}   (base method inherited)`);
  console.log(`    bw instanceof Widget   : ${bw instanceof Widget}`);
  check("mixin: combines base + mixed-in method", bw.shape === "rect" && bw.border() === 1);
  check("mixin: base methods inherited", bw.area() === 100);
  check("mixin: result instanceof the base class", bw instanceof Widget);

  // ---- (5) new.target — which constructor was actually called --------------
  // `new.target` is an implicit parameter every function/class has. In a base
  // constructor reached via super() from a derived class, it is the DERIVED
  // class — enabling metaprogramming (abstract-base / final-class patterns).
  class Logger {
    createdBy!: string;
    constructor() {
      if (new.target === Logger) {
        this.createdBy = "Logger (direct new)";
      } else {
        this.createdBy = (new.target as { name: string }).name + " (via subclass)";
      }
    }
  }
  class ConsoleLogger extends Logger {}
  const direct = new Logger();
  const viaSub = new ConsoleLogger();
  console.log(`(5) new.target:`);
  console.log(`    new Logger().createdBy         : ${direct.createdBy}`);
  console.log(`    new ConsoleLogger().createdBy  : ${viaSub.createdBy}   (propagates through super)`);
  check("new.target === Logger when directly new'd", direct.createdBy === "Logger (direct new)");
  check("new.target is the derived class when subclass new'd (propagates via super)", viaSub.createdBy === "ConsoleLogger (via subclass)");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("classes_desugar.ts — Phase 3 bundle #19.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: ES6 `class` is SYNTACTIC SUGAR over constructor + prototype.");
  console.log("TS's public/private/protected/readonly are COMPILE-TIME ONLY (erased);");
  console.log("only `#private` is RUNTIME-enforced. This file makes both visible.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
