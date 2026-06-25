// proxy_reflect.ts — Phase 6 bundle (metaprog member).
//
// GOAL (one line): show, by printing every intercept, how `Proxy` traps the
// fundamental operations on an object (get/set/has/delete/ownKeys/apply/
// construct) and how `Reflect` forwards a trap back to the default behavior —
// JS's runtime METAPROGRAMMING engine, pinned as check()'d invariants.
//
// This is the GROUND TRUTH for PROXY_REFLECT.md. Every intercept, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): JavaScript objects expose a fixed set of
// INTERNAL METHODS ([[Get]], [[Set]], [[HasProperty]], [[Delete]],
// [[OwnPropertyKeys]], [[Call]], [[Construct]], ...). `Proxy` lets a handler
// OVERRIDE those internal methods with TRAPS — so a read, a write, an `in`
// check, a `delete`, an `Object.keys`, even a function CALL or `new`, can all
// be intercepted at RUNTIME, transparently to the caller. `Reflect` is the
// companion object exposing the SAME operations as plain functions, so a trap
// can do its extra work and then FORWARD to the default via Reflect.get/...
// Together they implement validation, logging, virtualization, negative-array
// indexing, and the reactivity that powers Vue 3 / MobX. This is the runtime
// analog of Rust's macro_rules!/proc-macros (COMPILE-TIME codegen — the
// contrast) and the closest sibling of Python's __getattr__/metaclasses
// (runtime interception, same idea).
//
// Run:
//     pnpm exec tsx proxy_reflect.ts   (or: just run proxy_reflect)

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

// A small typed wrapper that runs a thunk and reports whether it threw a
// TypeError — used to observe proxy INVARIANT violations (the proxy engine
// throws TypeError when a trap breaks a language guarantee; e.g. a revoked
// proxy, or a get trap that lies about a non-configurable property).
function expectTypeError(label: string, fn: () => void): boolean {
  try {
    fn();
  } catch (e) {
    if (e instanceof TypeError) {
      console.log(`  ${label}: threw TypeError (observed)`);
      return true;
    }
    console.log(`  ${label}: threw ${e instanceof Error ? e.name : "unknown"} (UNEXPECTED)`);
    return false;
  }
  console.log(`  ${label}: did NOT throw (UNEXPECTED)`);
  return false;
}

// ============================================================================
// Section A — new Proxy(target, {}): the passthrough + the get/set traps
// ============================================================================

function sectionA(): void {
  sectionBanner("A — new Proxy(target, {}): the passthrough + the get/set traps");

  // 1. The PASSTHROUGH: an EMPTY handler {} forwards every operation to the
  //    target unchanged. `new Proxy(target, {})` is observationally identical
  //    to `target` for plain objects. (Caveat: it does NOT work for objects
  //    with internal slots like Map — the proxy is a different identity.)
  const target: Record<string, unknown> = { name: "Alice", age: 30 };
  const passthrough = new Proxy(target, {} satisfies ProxyHandler<typeof target>);
  console.log(`passthrough.name = ${String(passthrough.name)}`); // Alice
  passthrough.age = 31; // forwarded to target (no set trap defined)
  console.log(`target.age after proxy write = ${String(target.age)}`); // 31
  check("passthrough proxy returns target values", passthrough.name === target.name);
  check("passthrough write forwards to target", target.age === 31);

  // 2. The `get` trap: intercept READS. Signature get(target, prop, receiver).
  //    Here we LOG every property read into an array (observability in miniature).
  const reads: string[] = [];
  const logged = new Proxy(
    { x: 1, y: 2 } as Record<string, number>,
    {
      get(t, prop, receiver) {
        reads.push(String(prop));
        return Reflect.get(t, prop, receiver); // forward to the default
      },
    } satisfies ProxyHandler<Record<string, number>>,
  );
  void logged.x;
  void logged.y;
  void logged.x;
  console.log(`reads recorded: ${JSON.stringify(reads)}`); // ["x","y","x"]
  check("get trap records reads in order", JSON.stringify(reads) === JSON.stringify(["x", "y", "x"]));

  // 3. The `set` trap: intercept WRITES — VALIDATE. set(target, prop, value).
  //    Returning `false` tells the engine the assignment FAILED; in STRICT
  //    MODE (ESM is always strict) that makes the assignment THROW TypeError.
  //    (Alternatively, the trap may throw directly.) Reflect.set is only
  //    reached when the value is valid, so the target is never poisoned.
  const person = new Proxy(
    {} as Record<string, unknown>,
    {
      set(t, prop, value: unknown) {
        if (prop === "age") {
          if (typeof value !== "number" || value < 0 || value > 150) {
            return false; // reject — strict-mode assignment will throw
          }
        }
        return Reflect.set(t, prop, value);
      },
    } satisfies ProxyHandler<Record<string, unknown>>,
  );
  person.age = 25; // valid
  console.log(`person.age after valid set = ${String(person.age)}`);
  check("set trap accepts a valid age", person.age === 25);

  // The invalid assignment: set trap returns false -> strict-mode TypeError.
  const rejected = expectTypeError("person.age = 999 (invalid)", () => {
    person.age = 999; // > 150 -> trap returns false -> TypeError
  });
  console.log(`  person.age after rejected write = ${String(person.age)} (unchanged)`);
  check("set trap rejects invalid age (returns false -> strict TypeError)", rejected);
  check("rejected value never landed on the target", person.age === 25);
}

// ============================================================================
// Section B — Reflect.*: the forward-to-default functions
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Reflect.* : the forward-to-default functions");

  // Reflect exposes the SAME operations the proxy traps override, as plain
  // functions. Its headline use: inside a trap, call Reflect.<op> to do the
  // DEFAULT behavior (the thing that would have happened with no trap).

  const o: Record<string, number> = { k: 42 };
  console.log(`Reflect.get(o, "k") = ${Reflect.get(o, "k")}`);
  console.log(`o.k               = ${o.k}`);
  check("Reflect.get(t,'k') === t.k (forward-to-default)", Reflect.get(o, "k") === o.k);

  // Reflect.set RETURNS a boolean (true = success), unlike the `=` operator
  // (which throws on failure in strict mode). That makes it composable inside
  // a trap — you can inspect the result and still return it.
  const ok = Reflect.set(o, "k", 100);
  console.log(`Reflect.set(o,'k',100) -> ${ok}; o.k now ${o.k}`);
  check("Reflect.set returns true on success", ok === true);
  check("Reflect.set actually mutated the target", o.k === 100);

  // Reflect.has === the `in` operator, as a function (checks own + inherited).
  check('Reflect.has(o,"k") === "k" in o', Reflect.has(o, "k") === "k" in o);
  check('Reflect.has(o,"absent") === false', Reflect.has(o, "absent") === false);

  // Reflect.ownKeys: the OWN (not inherited) string + symbol keys, in spec
  // order: integer-like keys ASCENDING, then other strings in insertion order,
  // then symbols in insertion order. (Mirrors Object.getOwnPropertyNames +
  // getOwnPropertySymbols, but in one call.)
  const sym = Symbol("s");
  const withSym: Record<string | symbol, number> = { a: 1, 2: 2 };
  withSym[sym] = 3;
  const keys = Reflect.ownKeys(withSym).map((k) => (typeof k === "symbol" ? k.toString() : String(k)));
  console.log(`Reflect.ownKeys({a:1, 2:2, [Symbol('s')]:3}) = ${JSON.stringify(keys)}`);
  check("Reflect.ownKeys order: integer-key, then string, then symbol", JSON.stringify(keys) === JSON.stringify(["2", "a", "Symbol(s)"]));

  // Reflect.defineProperty / Reflect.deleteProperty — the function forms of
  // Object.defineProperty and `delete`, both returning a boolean.
  const d: Record<string, number> = {};
  const defined = Reflect.defineProperty(d, "frozen", {
    value: 7,
    writable: false,
    configurable: false,
    enumerable: true,
  });
  console.log(`Reflect.defineProperty -> ${defined}; d.frozen = ${d.frozen}`);
  check("Reflect.defineProperty defines a property (returns true)", defined === true && d.frozen === 7);

  const del = Reflect.deleteProperty(d, "frozen"); // non-configurable -> false
  console.log(`Reflect.deleteProperty(non-configurable 'frozen') -> ${del}`);
  check("Reflect.deleteProperty returns false on a non-configurable property", del === false);
  check("non-configurable property still present after the failed delete", d.frozen === 7);
}

// ============================================================================
// Section C — has/deleteProperty/ownKeys traps + apply/construct
// ============================================================================

function sectionC(): void {
  sectionBanner("C — has/deleteProperty/ownKeys traps + apply/construct");

  // `has` trap intercepts the `in` operator: you can HIDE a property.
  const hidden = new Proxy(
    { real: 1 } as Record<string, number>,
    {
      has(t, prop) {
        if (prop === "secret") return false; // pretend it isn't there
        return Reflect.has(t, prop);
      },
    } satisfies ProxyHandler<Record<string, number>>,
  );
  console.log(`"real"   in hidden = ${"real" in hidden}`); // true
  console.log(`"secret" in hidden = ${"secret" in hidden}`); // false
  check('has trap can hide "secret" (returns false)', "secret" in hidden === false);
  check('has trap still reports "real"', "real" in hidden === true);

  // `deleteProperty` trap intercepts `delete`.
  const deleted: string[] = [];
  const deletable = new Proxy(
    { a: 1, b: 2 } as Record<string, number>,
    {
      deleteProperty(t, prop) {
        deleted.push(String(prop));
        return Reflect.deleteProperty(t, prop);
      },
    } satisfies ProxyHandler<Record<string, number>>,
  );
  delete deletable.a;
  console.log(`deletions recorded: ${JSON.stringify(deleted)}`);
  check("deleteProperty trap recorded the delete of 'a'", deleted.includes("a"));
  check("deleted property is gone; sibling survives", "a" in deletable === false && deletable.b === 2);

  // `ownKeys` trap intercepts Object.getOwnPropertyNames / getOwnPropertySymbols
  // / Object.keys (the engine calls [[OwnPropertyKeys]] then filters). It must
  // return an array of string/symbol keys; the engine enforces invariants.
  const keysFired: string[] = [];
  const keyProxy = new Proxy(
    { x: 1, y: 2, z: 3 } as Record<string, number>,
    {
      ownKeys(t) {
        const ks = Reflect.ownKeys(t);
        for (const k of ks) keysFired.push(String(k));
        return ks;
      },
    } satisfies ProxyHandler<Record<string, number>>,
  );
  const ownNames = Object.getOwnPropertyNames(keyProxy);
  console.log(`Object.getOwnPropertyNames(keyProxy) = ${JSON.stringify(ownNames)}`);
  check("ownKeys trap fired for Object.getOwnPropertyNames", keysFired.length > 0);
  check("ownKeys trap forwarded the three own keys", JSON.stringify(ownNames) === JSON.stringify(["x", "y", "z"]));

  // `apply` trap: intercept a function CALL. The target must be a FUNCTION;
  // the proxy is then callable. Signature apply(target, thisArg, argArray).
  const calls: number[][] = [];
  function sum(...args: number[]): number {
    return args.reduce((a, b) => a + b, 0);
  }
  const proxiedSum = new Proxy(
    sum,
    {
      apply(t, thisArg, argArray: unknown[]) {
        calls.push(argArray as number[]);
        return Reflect.apply(t, thisArg, argArray) as number;
      },
    } satisfies ProxyHandler<typeof sum>,
  );
  const r = proxiedSum(1, 2, 3);
  console.log(`proxiedSum(1,2,3) = ${r}`);
  console.log(`calls recorded   = ${JSON.stringify(calls)}`);
  check("apply trap intercepts the function call (forwarded result correct)", r === 6);
  check("apply trap recorded the argument list", JSON.stringify(calls) === JSON.stringify([[1, 2, 3]]));

  // `construct` trap: intercept `new`. Signature construct(target, argArray,
  // newTarget). Reflect.construct(t, argArray, newTarget) is the only way to
  // forward while preserving new.target (important for subclassing).
  const news: number[] = [];
  class Thing {
    constructor(public id: number) {}
  }
  const ProxiedThing = new Proxy(
    Thing,
    {
      construct(t, argArray: unknown[], newTarget) {
        news.push(argArray.length);
        return Reflect.construct(t, argArray, newTarget);
      },
    } satisfies ProxyHandler<typeof Thing>,
  );
  const made = new ProxiedThing(7);
  console.log(`new ProxiedThing(7).id = ${made.id}`);
  check("construct trap intercepts `new` (instance built correctly)", made.id === 7);
  check("construct trap observed the argument count", news[0] === 1);
}

// ============================================================================
// Section D — Proxy.revocable (revoke -> throws) + invariants
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Proxy.revocable (revoke -> throws) + invariants");

  // Proxy.revocable(target, handler) -> { proxy, revoke }. The proxy behaves
  // like a normal proxy until revoke() is called; afterwards ANY operation
  // that would trigger a trap THROWS TypeError. Once revoked it stays revoked
  // (calling revoke() again is a no-op). `typeof` does NOT trigger a trap, so
  // typeof revokedProxy is still "object".
  const { proxy: rp, revoke } = Proxy.revocable(
    { msg: "hi" } as Record<string, string>,
    {
      get(t, prop) {
        return Reflect.get(t, prop);
      },
    } satisfies ProxyHandler<Record<string, string>>,
  );
  console.log(`pre-revoke  proxy.msg = ${rp.msg}`); // hi
  check("revocable proxy works before revoke", rp.msg === "hi");

  revoke();
  const postThrew = expectTypeError("post-revoke read proxy.msg", () => {
    void rp.msg; // any trap -> TypeError
  });
  check("post-revoke: any operation throws TypeError", postThrew);
  check('typeof revoked proxy === "object" (typeof triggers NO trap)', typeof rp === "object");

  // INVARIANTS: the proxy engine ENFORCES language guarantees even inside a
  // trap — a trap cannot lie in a way that would break the language. The
  // classic case: a NON-CONFIGURABLE, NON-WRITABLE data property's `get` trap
  // MUST return the property's real value; returning anything else throws
  // TypeError. This is why Object.freeze'd state stays frozen even behind a
  // proxy, and why Vue 3 can't make a frozen object reactive.
  const frozen: { p: string } = { p: "real" };
  Object.defineProperty(frozen, "p", {
    value: "real",
    writable: false,
    configurable: false,
    enumerable: true,
  });
  const lyingProxy = new Proxy(
    frozen,
    {
      get() {
        return "LIE"; // always returns a DIFFERENT value than the frozen prop
      },
    } satisfies ProxyHandler<{ p: string }>,
  );
  console.log("get trap returns 'LIE' for a non-configurable non-writable 'p':");
  const invariantThrew = expectTypeError("lyingProxy.p", () => {
    void lyingProxy.p; // engine: value mismatch on frozen prop -> TypeError
  });
  check("get-trap invariant: lying about a non-configurable non-writable prop throws", invariantThrew);
}

// ============================================================================
// Section E — Use cases: negative indices, defaults, reactivity (Vue 3 model)
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Use cases: negative indices, defaults, reactivity (Vue 3 model)");

  // 1. NEGATIVE array indexing (Python-style): arr[-1] reads the LAST element.
  //    The get trap rewrites a negative integer index into a positive one.
  const negArr = new Proxy(
    [10, 20, 30] as number[],
    {
      get(t, prop, receiver) {
        if (typeof prop === "string") {
          const n = Number(prop);
          if (Number.isInteger(n) && n < 0) {
            return t[t.length + n]; // -1 -> t[2] (last)
          }
        }
        return Reflect.get(t, prop, receiver); // .length, methods, etc.
      },
    } satisfies ProxyHandler<number[]>,
  );
  console.log(`negArr[-1] = ${negArr[-1]}`); // 30
  console.log(`negArr[-2] = ${negArr[-2]}`); // 20
  console.log(`negArr[0]  = ${negArr[0]}`); // 10
  check("negative index -1 reads the last element", negArr[-1] === 30);
  check("negative index -2 reads the second-to-last", negArr[-2] === 20);
  check("positive index 0 still forwards normally", negArr[0] === 10);
  check("negArr.length forwards via Reflect.get", negArr.length === 3);

  // 2. DEFAULT-VALUE object: reading an absent key returns a default instead
  //    of undefined (a tiny RPC-stub / config-with-defaults pattern).
  const withDefaults = new Proxy(
    { a: 1 } as Record<string, number>,
    {
      get(t, prop) {
        if (prop in t) return Reflect.get(t, prop);
        return 0; // default for any missing key
      },
    } satisfies ProxyHandler<Record<string, number>>,
  );
  console.log(`withDefaults.a      = ${withDefaults.a}`); // 1
  console.log(`withDefaults.absent = ${withDefaults.absent}`); // 0
  check("default-value proxy returns the real value when present", withDefaults.a === 1);
  check("default-value proxy returns 0 when the key is absent", withDefaults.absent === 0);

  // 3. OBSERVABILITY — the mini model of Vue 3 / MobX reactivity. Vue 3 wraps
  //    reactive state in a Proxy: a `get` records WHICH effect depends on the
  //    property ("track"), a `set` re-runs those effects ("trigger"). Here a
  //    single "render" effect subscribes to `count` via the get trap, and is
  //    re-invoked when count is set.
  const subs = new Map<string, Set<string>>(); // prop -> dependent effects
  const effectsRan: string[] = [];
  function track(prop: string, effect: string): void {
    let set = subs.get(prop);
    if (!set) {
      set = new Set();
      subs.set(prop, set);
    }
    set.add(effect);
  }
  function trigger(prop: string): void {
    const set = subs.get(prop);
    if (set) for (const eff of set) effectsRan.push(eff);
  }
  const state = new Proxy(
    { count: 0 } as Record<string, number>,
    {
      get(t, prop) {
        track(String(prop), "render"); // (pretend we're running the render effect)
        return Reflect.get(t, prop);
      },
      set(t, prop, value: number) {
        const ok = Reflect.set(t, prop, value);
        trigger(String(prop));
        return ok;
      },
    } satisfies ProxyHandler<Record<string, number>>,
  );
  void state.count; // render subscribes to count
  state.count = 1; // mutates the target AND re-runs render
  console.log(`reactive effects ran: ${JSON.stringify(effectsRan)}`);
  console.log(`state.count now ${state.count}`);
  check("Vue 3-style proxy: get tracks, set triggers the effect", effectsRan.includes("render"));
  check("reactive set updated the underlying value", state.count === 1);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("proxy_reflect.ts — Phase 6 bundle (metaprog member).");
  console.log("Every intercept below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Proxy traps the FUNDAMENTAL operations on an object (get/set/has/delete/");
  console.log("ownKeys/apply/construct); Reflect forwards a trap back to the default.");
  console.log("No Math.random / Date.now — output is deterministic.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
