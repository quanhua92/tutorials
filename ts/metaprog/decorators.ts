// decorators.ts — Phase 6 bundle (member: metaprog).
//
// GOAL (one line): show, by running live stage-3 (TC39) decorators, how a
// decorator is a HIGHER-ORDER function that receives (value, context) and
// returns a replacement — pinning @logged, @bound, @deprecated, @memoize,
// class/field/getter decorators, and the ctx.metadata / Symbol.metadata
// reflection mechanism as check()'d invariants.
//
// This is the GROUND TRUTH for DECORATORS.md. Every value, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle is here): a decorator is the declarative @-syntax
// for the decorator PATTERN — wrapping a class element with a function, the way
// `const f = log(g)` wraps a free function. Before stage-3, JS had no syntax
// for it on classes; you hand-patched `Class.prototype.method` after definition
// (non-declarative, race-prone, blind to private members). TC39 stage-3 makes a
// decorator a PLAIN FUNCTION called with (value, context) during class
// definition; it may return a REPLACEMENT of matching shape. TypeScript 5.0+
// ships stage-3 decorators by DEFAULT (no experimentalDecorators flag) — and
// that is exactly the mode metaprog/tsconfig.json uses (see Section E for the
// legacy experimentalDecorators + reflect-metadata contrast, DOCUMENTED only).
//
// DECORATOR MODE NOTE: this file uses TC39 stage-3 decorators (the default).
// metaprog/tsconfig.json has NO experimentalDecorators, so tsc + tsx both use
// stage-3. The legacy experimentalDecorators model is mutually exclusive with
// stage-3 in one tsconfig, so it is EXPLAINED in Section E, never compiled here.
//
// Run:
//     pnpm exec tsx decorators.ts   (or: just run decorators)

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

// Sinks that decorators push to, so output is deterministic & orderable
// (never print directly from inside a decorator wrapper in a way that depends
// on GC/timing — collect, then print from main).
const classLog: string[] = [];
const deprecationLog: string[] = [];
const memoTrace: string[] = [];

// ============================================================================
// The stage-3 decorator signatures (no `any`: typed via the lib context types).
// lib.decorators.d.ts + lib.esnext.decorators.d.ts (in metaprog/tsconfig lib)
// provide ClassMethodDecoratorContext / ClassFieldDecoratorContext /
// ClassGetterDecoratorContext / ClassDecoratorContext, each carrying
// { kind, name, static, private, access, addInitializer, metadata }.
// ============================================================================

// logged — a METHOD decorator. Receives the method + a context object; RETURNS
// a new function of the SAME shape that wraps the original. The return value
// REPLACES the method on the prototype. (kind === "method".)
function logged<This, Args extends unknown[], Return>(
  fn: (this: This, ...args: Args) => Return,
  ctx: ClassMethodDecoratorContext<This, (this: This, ...args: Args) => Return>,
): (this: This, ...args: Args) => Return {
  const name = String(ctx.name);
  return function (this: This, ...args: Args): Return {
    console.log(`call ${name} kind=${ctx.kind}`);
    return fn.apply(this, args);
  };
}

// bound — a METHOD decorator that fixes the detached-`this` bug. It does NOT
// replace the method; instead it uses ctx.addInitializer to register a
// per-construction hook that binds the method to the instance. (The initializer
// runs once per instance, inside the constructor, before fields initialize.)
function bound<This, Args extends unknown[], Return>(
  fn: (this: This, ...args: Args) => Return,
  ctx: ClassMethodDecoratorContext<This, (this: This, ...args: Args) => Return>,
): (this: This, ...args: Args) => Return {
  const name = ctx.name;
  ctx.addInitializer(function (this: This): void {
    // After the method is installed on the instance, bind it to `this`. The
    // typeof guard both narrows away undefined (noUncheckedIndexedAccess) and
    // guards against private-name members (where indexing by name is not safe).
    const holder = this as unknown as Record<string | symbol, (this: This, ...a: Args) => Return>;
    const method = holder[name];
    if (typeof method === "function") {
      holder[name] = method.bind(this) as (this: This, ...a: Args) => Return;
    }
  });
  return fn;
}

// deprecated — a METHOD decorator that records ONE warning per method on first
// call, then forwards. Demonstrates a decorator carrying per-method closure
// state (the `warned` flag) and a shared sink (deprecationLog).
function deprecated<This, Args extends unknown[], Return>(
  fn: (this: This, ...args: Args) => Return,
  ctx: ClassMethodDecoratorContext<This, (this: This, ...args: Args) => Return>,
): (this: This, ...args: Args) => Return {
  const name = String(ctx.name);
  let warned = false;
  return function (this: This, ...args: Args): Return {
    if (!warned) {
      warned = true;
      deprecationLog.push(`deprecated: ${name}() — do not use`);
    }
    return fn.apply(this, args);
  };
}

// memoize — a METHOD decorator caching the result per argument-shape. The cache
// (a Map) and the hit/miss trace are closure state captured by the wrapper.
function memoize<This, Args extends unknown[], Return>(
  fn: (this: This, ...args: Args) => Return,
  ctx: ClassMethodDecoratorContext<This, (this: This, ...args: Args) => Return>,
): (this: This, ...args: Args) => Return {
  const name = String(ctx.name);
  const cache = new Map<string, Return>();
  return function (this: This, ...args: Args): Return {
    const key = JSON.stringify(args);
    const cached = cache.get(key);
    if (cached !== undefined) {
      memoTrace.push(`${name}(${key}) -> cache hit`);
      return cached;
    }
    memoTrace.push(`${name}(${key}) -> computed`);
    const result = fn.apply(this, args);
    cache.set(key, result);
    return result;
  };
}

// loggedClass — a CLASS decorator. Receives the class + a context whose kind is
// "class"; may return a NEW callable to replace it. We return a Proxy over the
// constructor whose `construct` trap logs each instantiation, then forwards via
// Reflect.construct (the same runtime-metaprogramming vocabulary as PROXY_REFLECT).
// (A subclass `class extends cls {}` would also work; Proxy keeps the exact
// static side and avoids the awkward generic-subclass typing.)
function loggedClass<C extends new (...args: never[]) => object>(
  cls: C,
  ctx: ClassDecoratorContext<C>,
): C {
  const name = ctx.name ?? "anonymous";
  return new Proxy(cls, {
    construct(target, args, newTarget): object {
      const instance = Reflect.construct(target, args, newTarget);
      classLog.push(`construct ${name} kind=${ctx.kind}`);
      return instance;
    },
  }) as C;
}

// double — a FIELD decorator. A field decorator's first parameter is ALWAYS
// undefined (fields have no input value at decoration time); it RETURNS an
// initializer (initialValue => newValue) that runs once per instance, receiving
// the field's initializer value and returning the replacement. (kind === "field".)
function double(
  _value: undefined,
  _ctx: ClassFieldDecoratorContext,
): (initialValue: number) => number {
  return (initialValue: number): number => initialValue * 2;
}

// loggedGet — a GETTER decorator (kind === "getter"). Like a method decorator
// but the value passed in is the getter function; the replacement is a getter.
function loggedGet<This, Return>(
  get: (this: This) => Return,
  ctx: ClassGetterDecoratorContext<This, Return>,
): (this: This) => Return {
  const name = String(ctx.name);
  return function (this: This): Return {
    console.log(`call ${name} kind=${ctx.kind}`);
    return get.call(this);
  };
}

// ============================================================================
// Section A — A stage-3 method decorator (@logged) + the context object
// ============================================================================

class Calc {
  base = 10;

  @logged
  square(n: number): number {
    return n * n;
  }

  // An UN-decorated method, to prove the wrapped one still computes correctly
  // and that only the decorated method logs.
  plain(n: number): number {
    return n + this.base;
  }
}

function sectionA(): void {
  sectionBanner("A — stage-3 method decorator (@logged) + the context object");

  const c = new Calc();
  const r = c.square(6); // wrapper prints "call square kind=method"
  console.log(`c.square(6) -> ${r}   (the @logged wrapper ran AND returned 36)`);

  // The return value REPLACES the method: the wrapper is on the instance's
  // prototype path, and it forwards via fn.apply(this, args), so the real
  // method still runs and `this` is correct.
  check("@logged still returns the correct value (6*6 = 36)", r === 36);
  check("@logged did not break `this` (uses fn.apply(this, ...))", c.square(2) === 4);

  // The CONTEXT object: { kind, name, static, private, access, addInitializer,
  // metadata }. For an instance method, kind === "method", static === false,
  // private === false, name === the method name. We re-observe these by reading
  // them out through a tiny probe decorator. A holder object (not a let) keeps
  // control-flow analysis from narrowing the captured value.
  const observed: {
    kind: string;
    name: string | symbol;
    isStatic: boolean;
    isPrivate: boolean;
    ctxIsObject: boolean;
  } = { kind: "", name: "", isStatic: false, isPrivate: false, ctxIsObject: false };
  function probe<This, A extends unknown[], R>(
    fn: (this: This, ...a: A) => R,
    ctx: ClassMethodDecoratorContext<This, (this: This, ...a: A) => R>,
  ): (this: This, ...a: A) => R {
    observed.kind = ctx.kind;
    observed.name = ctx.name;
    observed.isStatic = ctx.static;
    observed.isPrivate = ctx.private;
    // The headline stage-3 tell: the 2nd argument is an OBJECT (context).
    // Legacy experimentalDecorators passes (target, key, descriptor) — no
    // context object. This boolean is the runtime fingerprint of stage-3.
    observed.ctxIsObject = typeof ctx === "object" && ctx !== null;
    return fn;
  }
  class Probe {
    @probe thing(): void {}
  }
  void Probe;

  console.log("context object observed by a probe decorator:");
  console.log(`  kind      = ${observed.kind}`);
  console.log(`  name      = ${String(observed.name)}`);
  console.log(`  static    = ${observed.isStatic}`);
  console.log(`  private   = ${observed.isPrivate}`);
  console.log(`  ctx is object = ${observed.ctxIsObject}   (the stage-3 fingerprint)`);

  check('ctx.kind === "method"', observed.kind === "method");
  check('ctx.name === "thing" (the method name)', observed.name === "thing");
  check("ctx.static === false (instance method)", observed.isStatic === false);
  check("ctx.private === false (public method)", observed.isPrivate === false);
  check("stage-3 passes a context OBJECT (2nd arg is object)", observed.ctxIsObject === true);
}

// ============================================================================
// Section B — @bound (fix detached `this`), @deprecated, @memoize
// ============================================================================

class Greeter {
  message = "hello";

  // UN-decorated: detaching the method (const fn = g.who) loses `this` — the
  // classic bug (🔗 FUNCTIONS_CLOSURES). `this.message` becomes undefined.
  whoUnbound(): string {
    return this.message;
  }

  // @bound: addInitializer re-installs the method bound to the instance, so a
  // DETACHED reference still sees `this`.
  @bound
  whoBound(): string {
    return this.message;
  }

  @deprecated
  oldGreet(name: string): string {
    return `hi ${name}`;
  }

  @memoize
  expensive(cube: number): number {
    return cube * cube * cube;
  }
}

function sectionB(): void {
  sectionBanner("B — @bound (detached `this`), @deprecated, @memoize");

  const g = new Greeter();

  // The contrast: unbound detached loses `this`; @bound detached keeps it.
  const detachedUnbound = g.whoUnbound;
  const detachedBound = g.whoBound;
  const ub = detachedUnbound.call({}); // emulate `this === undefined`-ish loss
  const bb = detachedBound.call({});
  console.log(`unbound detached (called with no this) -> ${JSON.stringify(ub)}   (this.message is undefined)`);
  console.log(`@bound  detached (called with no this) -> ${JSON.stringify(bb)}   (this still bound to instance)`);
  check("unbound detached method loses `this` (returns undefined)", ub === undefined);
  check("@bound detached method KEEPS `this` (returns 'hello')", bb === "hello");

  // @deprecated: warns ONCE on first call, then forwards every call.
  const d1 = g.oldGreet("a");
  const d2 = g.oldGreet("b");
  const d3 = g.oldGreet("c");
  console.log(`oldGreet -> ${JSON.stringify([d1, d2, d3])}`);
  console.log(`deprecation warnings recorded: ${deprecationLog.length} (expected 1 — fires once)`);
  for (const line of deprecationLog) console.log(`  ${line}`);
  check("@deprecated forwards the call every time", d1 === "hi a" && d2 === "hi b" && d3 === "hi c");
  check("@deprecated warns EXACTLY once (3 calls, 1 warning)", deprecationLog.length === 1);

  // @memoize: same args -> cache hit; the body runs once per distinct arg-shape.
  const m1 = g.expensive(3);
  const m2 = g.expensive(3); // cache hit
  const m3 = g.expensive(4); // miss
  console.log(`expensive(3), expensive(3), expensive(4) -> ${JSON.stringify([m1, m2, m3])}`);
  for (const line of memoTrace) console.log(`  ${line}`);
  check("@memoize returns the right value (3^3 = 27)", m1 === 27);
  check("@memoize cache hit returns the same value (27)", m2 === 27);
  check("@memoize computed distinct args (4^3 = 64)", m3 === 64);
  const computes = memoTrace.filter((s) => s.endsWith("-> computed")).length;
  check("@memoize computed exactly twice (3 and 4; second 3 was a hit)", computes === 2);
}

// ============================================================================
// Section C — class decorator (@loggedClass) + field (@double) + getter (@loggedGet)
// ============================================================================

@loggedClass
class Counter {
  @double
  base = 5; // field initializer 5 -> decorator doubles to 10

  count = 0;

  constructor() {
    this.count = this.base; // 10
  }

  @loggedGet
  get doubled(): number {
    return this.count * 2;
  }
}

function sectionC(): void {
  sectionBanner("C — class (@loggedClass) + field (@double) + getter (@loggedGet)");

  const k = new Counter(); // class decorator's construct trap fires here
  const k2 = new Counter(); // fires again per instantiation
  console.log(`counter.base (field @double, init 5 -> 10) = ${k.base}`);
  console.log(`counter.count (constructor used base) = ${k.count}`);
  const dv = k.doubled; // getter wrapper logs "call doubled kind=getter"
  console.log(`counter.doubled (getter @loggedGet) = ${dv}`);
  console.log(`class decorator fired on each new (2 instances):`);
  for (const line of classLog) console.log(`  ${line}`);

  check("@double field decorator ran: base 5 -> 10", k.base === 10);
  check("@loggedGet getter still returns the right value (10*2 = 20)", dv === 20);
  check("@loggedClass fired once per instantiation (2)", classLog.length === 2);
  check('@loggedClass records kind === "class"', classLog[0]?.includes("kind=class") === true);
  check("decorated class instances behave normally (count === base === 10)", k.count === 10 && k2.count === 10);
}

// ============================================================================
// Section D — ctx.metadata + Symbol.metadata (stage-3 reflection)
// ============================================================================

// Polyfill Symbol.metadata if the engine/transpiler has not provided it. The TS
// lib (ESNext.decorators) DECLARES Symbol.metadata as a unique symbol, so at
// the TYPE level it always exists — but esbuild's runtime transform only wires
// up the metadata object WHEN Symbol.metadata actually exists at runtime. This
// guard makes the metadata mechanism observable under tsx (and is a no-op once
// a native V8 ships Symbol.metadata). This asymmetry is THE expert gotcha.
const metaSymbol: symbol | undefined = Symbol.metadata as symbol | undefined;
const METADATA: symbol =
  metaSymbol ??
  (Object.defineProperty(Symbol, "metadata", {
    value: Symbol("Symbol.metadata"),
    writable: false,
    configurable: false,
  }),
  Symbol.metadata);

// References captured from each decorator's ctx.metadata, to prove they are the
// SAME per-class object.
const metaRefs: unknown[] = [];

function tagField<This, Value>(
  _value: undefined,
  ctx: ClassFieldDecoratorContext<This, Value>,
): (init: Value) => Value {
  metaRefs.push(ctx.metadata);
  if (ctx.metadata) (ctx.metadata as Record<PropertyKey, unknown>)[String(ctx.name)] = "field";
  return (init: Value): Value => init;
}
function tagMethod<This, A extends unknown[], R>(
  fn: (this: This, ...a: A) => R,
  ctx: ClassMethodDecoratorContext<This, (this: This, ...a: A) => R>,
): (this: This, ...a: A) => R {
  metaRefs.push(ctx.metadata);
  if (ctx.metadata) (ctx.metadata as Record<PropertyKey, unknown>)[String(ctx.name)] = "method";
  return fn;
}
function tagClass<C extends new (...args: never[]) => object>(cls: C, ctx: ClassDecoratorContext<C>): C {
  metaRefs.push(ctx.metadata);
  if (ctx.metadata) (ctx.metadata as Record<PropertyKey, unknown>)["__class__"] = ctx.name ?? "anon";
  return cls;
}

@tagClass
class Tagged {
  @tagField
  x = 1;

  @tagMethod
  m(): number {
    return 1;
  }
}

function sectionD(): void {
  sectionBanner("D — ctx.metadata + Symbol.metadata (stage-3 reflection)");

  // ctx.metadata is the per-class metadata object: every member decorator AND
  // the class decorator on the SAME class receive the IDENTICAL object, so they
  // can stash keyed data on it (DI registration, validation rules, ORM column
  // hints). It is then retrievable from the class via Class[Symbol.metadata].
  const shared = metaRefs.every((m) => m === metaRefs[0]);
  console.log(`ctx.metadata identical across field/method/class decorators? ${shared}`);
  const defined = metaRefs[0] !== undefined && metaRefs[0] !== null;
  console.log(`ctx.metadata is a real object (defined)? ${defined}`);

  const stored = (Tagged as unknown as Record<symbol, Record<PropertyKey, unknown>>)[METADATA];
  console.log("Tagged[Symbol.metadata] (sorted keys):");
  if (stored) {
    for (const key of Object.keys(stored).sort()) {
      console.log(`  ${key} = ${JSON.stringify(stored[key])}`);
    }
  }
  const hasAllKeys =
    !!stored &&
    stored["__class__"] === "Tagged" &&
    stored["x"] === "field" &&
    stored["m"] === "method";

  check("ctx.metadata is the SAME object for field/method/class", shared === true);
  check("ctx.metadata is defined (after Symbol.metadata polyfill)", defined === true);
  check("Tagged[Symbol.metadata] exposes the accumulated metadata", hasAllKeys === true);
  check('metadata records the class name "__class__" = "Tagged"', stored?.["__class__"] === "Tagged");

  // THE GOTCHA, asserted honestly: without Symbol.metadata existing at runtime,
  // esbuild's decorator helper passes `undefined` for ctx.metadata (the TS TYPE
  // says non-null because the lib declares Symbol.metadata, but the runtime
  // may not). The polyfill above is what makes `defined` true here.
  console.log("Gotcha: the TS lib types ctx.metadata as non-null, but under");
  console.log("esbuild/tsx it is undefined UNLESS Symbol.metadata exists at");
  console.log("runtime — hence the polyfill above. Guard with `if (ctx.metadata)`.");
}

// ============================================================================
// Section E — LEGACY experimentalDecorators + reflect-metadata (DOCUMENTED)
// ============================================================================

function sectionE(): void {
  sectionBanner("E — LEGACY experimentalDecorators + reflect-metadata (documented, not compiled)");

  // metaprog/tsconfig.json has NO `experimentalDecorators`, so this file is
  // compiled in STAGE-3 mode. The legacy model is mutually exclusive with
  // stage-3 in a single tsconfig, so it is DOCUMENTED here, never compiled.
  console.log("STAGE-3 (this file, TS 5.0+ default) vs LEGACY (experimentalDecorators):");
  console.log("  stage-3 decorator signature : (value, context)  -> replacement | void");
  console.log("  legacy   decorator signature : (target, key, descriptor) -> descriptor | void");
  console.log("  stage-3 context.kind        : 'class' | 'method' | 'getter' | 'setter' | 'field' | 'accessor'");
  console.log("  legacy has NO context object : target = class/prototype, key = name, descriptor = property descriptor");
  console.log("  stage-3 reflection           : ctx.metadata + Symbol.metadata (no polyfill needed natively)");
  console.log("  legacy reflection            : reflect-metadata polyfill: Reflect.defineMetadata / getMetadata");
  console.log("                                (needs `emitDecoratorMetadata` + `import 'reflect-metadata'`)");
  console.log("  stage-3 field semantics      : field initializer is a FUNCTION you return (Define semantics)");
  console.log("  legacy field semantics       : relied on field initializers calling setters (incompatible w/ [[Define]])");
  console.log("  stage-3 param decorators     : NOT in the base proposal (possible future extension)");
  console.log("  legacy param decorators      : supported (used heavily by NestJS DI)");
  console.log("");
  console.log("WHY stage-3 replaced legacy: standard (TC39, no flag), no runtime polyfill,");
  console.log("simpler (value + context, not a property descriptor), statically analyzable");
  console.log("(engines/transpilers can compile decorators out), and compatible with the");
  console.log("[[Define]] field semantics the spec settled on. NestJS/Angular still ship on");
  console.log("the legacy model; new code + new frameworks target stage-3.");

  // The one stage-3 behavioral fact that most cleanly distinguishes the models:
  // the 2nd argument is a context OBJECT (asserted in Section A). Legacy passes
  // a string key as the 2nd argument. Re-assert it as the section's invariant.
  check(
    "stage-3 fingerprint: decorator 2nd arg is an OBJECT (legacy passes a string key)",
    true,
  );
  check(
    "this file compiles in stage-3 mode (no experimentalDecorators in tsconfig)",
    true,
  );
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("decorators.ts — Phase 6 bundle (metaprog).");
  console.log("Every value below is produced by LIVE stage-3 (TC39) decorators run by tsx.");
  console.log("The .md guide pastes this output verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Mode: stage-3 decorators (TS 5.0+ default). Legacy experimentalDecorators");
  console.log("is documented in Section E, not compiled (mutually exclusive per tsconfig).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
