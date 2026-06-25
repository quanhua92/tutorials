// closures_capture.ts — Phase 3 bundle.
//
// GOAL (one line): show, by printing every value, that a JS closure is a
// function + its CAPTURED environment, that capture is ALWAYS BY REFERENCE (a
// live binding), and how that one fact produces the counter factory, the module
// pattern, the loop-var trap (and the pre-`let` IIFE fix), and the
// retention-as-a-leak pattern — then contrast JS's single implicit capture mode
// against Rust's explicit Fn / FnMut / FnOnce + `move`.
//
// This is the GROUND TRUTH for CLOSURES_CAPTURE.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it goes DEEPER on than P1):
// FUNCTIONS_CLOSURES (P1) introduced first-class functions, `this` binding, and
// the closure *basics* (a closure = fn + lexical env; the counter factory; that
// arrows capture lexical `this`). THIS bundle (P3) does NOT re-teach `this` or
// first-class functions. Instead it goes DEEPER on the CAPTURE/RETENTION
// mechanics that P1 only gestured at:
//   - capture is BY REFERENCE (a LIVE binding), never by value, never by move;
//   - the module pattern = closure-enforced privacy (pre-`#private`);
//   - the loop-var trap at full depth — `var` makes ONE shared slot ([3,3,3]),
//     `let` makes a per-iteration slot ([0,1,2]), and the pre-`let` IIFE fix
//     synthesized per-iteration capture by hand;
//   - capture & RETENTION: a closure keeps a large captured object alive even
//     after its outer function returns — the canonical JS leak pattern
//     (🔗 GARBAGE_COLLECTION);
//   - the idioms built on capture (memoize / once / curry) and the
//     cross-language capture model (JS always by-ref; Rust Fn/FnMut/FnOnce +
//     `move` makes capture mode EXPLICIT and typed).
//
// Run:
//     pnpm exec tsx closures_capture.ts   (or: just run closures_capture)

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

// fmtList prints a number[] as the compact "[0,1,2]" form used throughout.
function fmtList(xs: readonly number[]): string {
  return "[" + xs.join(",") + "]";
}

// ============================================================================
// Section A — Closure = function + captured environment; capture BY REFERENCE
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Closure = function + captured environment; capture BY REFERENCE");

  // A closure is "the combination of a function bundled together (enclosed)
  // with references to its surrounding state (the lexical environment)" (MDN).
  // Concretely: when an inner function is CREATED, it keeps a reference to the
  // environment (the variable bindings) of the scope it was defined in. That
  // environment stays alive as long as the closure is reachable.

  // --- The makeAdder factory (MDN's canonical example) ---------------------
  // add5 and add10 share the SAME function body, but each closed over a
  // DIFFERENT lexical environment (x=5 vs x=10). Two independent captures.
  function makeAdder(x: number): (y: number) => number {
    return (y: number): number => x + y;
  }
  const add5 = makeAdder(5);
  const add10 = makeAdder(10);
  console.log("makeAdder: two closures, same body, different captured env:");
  console.log(`  add5 = makeAdder(5);  add5(2)  -> ${add5(2)}    (x captured = 5)`);
  console.log(`  add10 = makeAdder(10); add10(2) -> ${add10(2)}   (x captured = 10)`);
  check("add5(2) === 7  (captured x = 5)", add5(2) === 7);
  check("add10(2) === 12 (captured x = 10)", add10(2) === 12);

  // --- THE key mechanic: capture is BY REFERENCE (a LIVE binding) -----------
  // The closure does NOT snapshot the value at creation time. It captures the
  // VARIABLE (the binding). So a mutation of that variable AFTER the closure
  // was created is VISIBLE to the closure. This is the single fact that
  // separates JS/TS capture from "capture by value" languages.
  let x = 1;
  const readX = (): number => x; // captures the BINDING `x`, not the value 1
  console.log("");
  console.log("Capture BY REFERENCE (the binding is LIVE):");
  console.log(`  let x = 1; const readX = () => x;`);
  console.log(`  readX()  -> ${readX()}   (value at creation)`);
  x = 2; // mutate AFTER the closure was created
  console.log(`  x = 2;   // mutate AFTER closure creation`);
  console.log(`  readX()  -> ${readX()}   (closure sees the NEW value — live binding)`);
  check("capture is BY REFERENCE: readX() === 2 after x = 2", readX() === 2);

  // --- The stateful counter factory (P1 introduced it; here we pin WHY) -----
  // `n` is a LOCAL of makeCounter. Once makeCounter returns, `n` has no name
  // anyone outside can reach — but the returned closure STILL references it, so
  // the engine keeps `n` alive on the heap. Each call mutates the SAME `n`
  // (live binding), so the count persists and advances across calls.
  function makeCounter(): () => number {
    let n = 0;
    return (): number => ++n;
  }
  const c = makeCounter();
  const v1 = c();
  const v2 = c();
  const v3 = c();
  console.log("");
  console.log("Counter factory — `n` survives makeCounter's return (closure RETAINS it):");
  console.log(`  c() -> ${v1}`);
  console.log(`  c() -> ${v2}`);
  console.log(`  c() -> ${v3}`);
  check("counter persists: first three calls are 1, 2, 3", v1 === 1 && v2 === 2 && v3 === 3);

  // --- Closure scope chain: a closure sees ALL enclosing scopes -------------
  // MDN: "closures have access to all outer scopes." Each nested function
  // closes over the whole chain (block -> function -> ... -> global), not just
  // its immediate parent.
  const e = 10;
  function sumChain(a: number): (b: number) => (c: number) => (d: number) => number {
    return (b: number): ((c: number) => (d: number) => number) =>
      (c: number): ((d: number) => number) =>
        (d: number): number => a + b + c + d + e;
  }
  const chained = sumChain(1)(2)(3)(4);
  console.log("");
  console.log("Closure scope chain — each level captures the whole enclosing chain:");
  console.log(`  sumChain(1)(2)(3)(4) -> ${chained}   (1+2+3+4+10; e captured from global)`);
  check("scope chain: sumChain(1)(2)(3)(4) === 20", chained === 20);
}

// ============================================================================
// Section B — The module pattern: closure-enforced privacy (pre-#private)
// ============================================================================

function sectionB(): void {
  sectionBanner("B — The module pattern: closure-enforced privacy (pre-#private)");

  // Before ES2022 `#private` fields, JS had NO native private state on objects.
  // The workaround — used by every pre-class library — was the MODULE PATTERN:
  // an IIFE (Immediately Invoked Function Expression) creates a private
  // lexical environment, and returns an object whose methods CLOSE OVER that
  // environment. The private variables are reachable ONLY through those
  // methods. This is data hiding / encapsulation built entirely on capture.

  // --- Factory form (modern, no IIFE needed): createBank -------------------
  interface Bank {
    deposit(amount: number): void;
    withdraw(amount: number): void;
    getBalance(): number;
  }
  function createBank(): Bank {
    let balance = 0; // PRIVATE: only the closures below can touch it
    return {
      deposit(amount: number): void {
        balance += amount;
      },
      withdraw(amount: number): void {
        balance -= amount;
      },
      getBalance(): number {
        return balance;
      },
    };
  }

  const bank = createBank();
  bank.deposit(100);
  bank.withdraw(30);
  console.log("Module pattern — `balance` is PRIVATE (closure-enforced):");
  console.log(`  bank.deposit(100); bank.withdraw(30);`);
  console.log(`  bank.getBalance()  -> ${bank.getBalance()}`);
  check("module state: bank.getBalance() === 70", bank.getBalance() === 70);

  // PROOF of privacy: `balance` is NOT a property of the returned object. It
  // lives only inside the factory's lexical environment, reachable solely via
  // the methods that closed over it. There is no `bank.balance`.
  const ownKeys = Object.keys(bank).sort();
  console.log("");
  console.log("Proof of privacy — balance is NOT an own property of `bank`:");
  console.log(`  Object.keys(bank).sort() -> ${JSON.stringify(ownKeys)}`);
  console.log(`  "balance" in bank        -> ${"balance" in bank}`);
  check('"balance" is NOT a property of bank (closure-private)', "balance" in bank === false);
  check(
    'bank own keys are exactly [deposit,getBalance,withdraw] (no balance)',
    JSON.stringify(ownKeys) === JSON.stringify(["deposit", "getBalance", "withdraw"].sort()),
  );

  // --- IIFE form (the classic module pattern) ------------------------------
  // The IIFE runs ONCE, builds the private environment, and returns the public
  // API. The three returned methods share ONE lexical environment (one
  // privateCounter, one changeBy) — exactly MDN's "shared lexical environment"
  // counter example.
  const modCounter = (function (): {
    increment(): void;
    decrement(): void;
    value(): number;
  } {
    let privateCounter = 0;
    function changeBy(val: number): void {
      privateCounter += val;
    }
    return {
      increment(): void {
        changeBy(1);
      },
      decrement(): void {
        changeBy(-1);
      },
      value(): number {
        return privateCounter;
      },
    };
  })();
  modCounter.increment();
  modCounter.increment();
  modCounter.decrement();
  console.log("");
  console.log("IIFE module — three methods share ONE private lexical environment:");
  console.log(`  modCounter.increment(); increment(); decrement();`);
  console.log(`  modCounter.value() -> ${modCounter.value()}`);
  check("IIFE module shared env: modCounter.value() === 1", modCounter.value() === 1);

  // --- Independence: each factory call makes a SEPARATE private env --------
  // MDN: "the two counters maintain their independence... Each closure
  // references a different version of the privateCounter variable." This is the
  // flip side of by-reference capture: each call's environment is its own
  // object on the heap, so two counters do NOT share state.
  const a1 = createBank();
  const a2 = createBank();
  a1.deposit(50);
  console.log("");
  console.log("Independence — each factory call = a separate private environment:");
  console.log(`  a1 = createBank(); a2 = createBank(); a1.deposit(50);`);
  console.log(`  a1.getBalance() -> ${a1.getBalance()}   a2.getBalance() -> ${a2.getBalance()}`);
  check("counters are independent: a2.getBalance() === 0 (not affected by a1)", a2.getBalance() === 0);
}

// ============================================================================
// Section C — The loop-var capture trap: var [3,3,3] vs let [0,1,2]; IIFE fix
// ============================================================================

function sectionC(): void {
  sectionBanner("C — The loop-var capture trap: var [3,3,3] vs let [0,1,2]; the IIFE fix");

  // This is the most famous closure bug in JS. 🔗 SCOPE_HOISTING owns the
  // var/let SCOPE mechanics (hoisting, TDZ, block vs function scope). HERE we
  // focus only on the CLOSURE-CAPTURE consequence and the historical IIFE fix.

  // --- var: ONE shared binding for the whole loop -> all closures see final i
  // `var i` is FUNCTION-scoped and hoisted, so there is exactly ONE slot `i`.
  // Every closure pushed in the loop closes over that SAME slot. By the time
  // the closures RUN (after the loop), `i` is 3 — so every closure returns 3.
  function varLoop(): number[] {
    const fns: Array<() => number> = [];
    for (var i = 0; i < 3; i++) {
      fns.push((): number => i); // every closure captures the SAME `i`
    }
    return fns.map((fn): number => fn());
  }
  const varResult = varLoop();
  console.log("var: ONE shared loop binding -> every closure sees the FINAL value:");
  console.log(`  for (var i = 0; i < 3; i++) fns.push(() => i);`);
  console.log(`  fns.map(fn => fn()) -> ${fmtList(varResult)}`);
  check("var loop-var trap: result is [3,3,3]", fmtList(varResult) === "[3,3,3]");

  // --- let: a FRESH per-iteration binding -> each closure captures its own i
  // `let i` in a `for` header creates a NEW binding on EACH iteration
  // (per-iteration binding). So each closure closes over a DIFFERENT slot,
  // holding that iteration's value of i. The bug vanishes.
  function letLoop(): number[] {
    const fns: Array<() => number> = [];
    for (let i = 0; i < 3; i++) {
      fns.push((): number => i); // each iteration captures its OWN `i`
    }
    return fns.map((fn): number => fn());
  }
  const letResult = letLoop();
  console.log("");
  console.log("let: a FRESH per-iteration binding -> each closure captures its own value:");
  console.log(`  for (let i = 0; i < 3; i++) fns.push(() => i);`);
  console.log(`  fns.map(fn => fn()) -> ${fmtList(letResult)}`);
  check("let per-iteration binding: result is [0,1,2]", fmtList(letResult) === "[0,1,2]");

  // --- The pre-`let` IIFE fix: synthesize per-iteration capture by hand -----
  // Before `let` existed (ES2015), the ONLY way to fix this was to wrap the
  // body in an IIFE that takes `i` as an ARGUMENT. Function parameters are
  // per-invocation bindings, so each iteration's IIFE gets its OWN `j`, and the
  // inner closure captures THAT `j`. This is "capture by value" simulated via
  // an extra function call — exactly the pattern pre-ES2015 code used everywhere.
  function iifeFixLoop(): number[] {
    const fns: Array<() => number> = [];
    for (var i = 0; i < 3; i++) {
      // The IIFE's parameter `j` is a fresh binding per call.
      (function (j: number): void {
        fns.push((): number => j);
      })(i);
    }
    return fns.map((fn): number => fn());
  }
  const iifeResult = iifeFixLoop();
  console.log("");
  console.log("Pre-`let` IIFE fix — a fresh parameter binding per iteration:");
  console.log(`  for (var i = 0; i < 3; i++) { (function (j) { fns.push(() => j); })(i); }`);
  console.log(`  fns.map(fn => fn()) -> ${fmtList(iifeResult)}`);
  check("IIFE fix yields [0,1,2] (per-call parameter binding)", fmtList(iifeResult) === "[0,1,2]");

  // --- The general lesson: capture is over the BINDING, and bindings nest ----
  // IIFE works because a function CALL creates a new environment. `let` works
  // because a block creates a new environment. Both give the closure a
  // distinct binding to close over. The bug was never "closures are broken" —
  // it was "var gave every closure the same binding."
  check(
    "let-fix and IIFE-fix are behaviorally identical (both [0,1,2])",
    fmtList(letResult) === fmtList(iifeResult),
  );
}

// ============================================================================
// Section D — Capture & RETENTION: a closure keeps a large object alive (leak)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Capture & RETENTION: a closure keeps a large object alive (leak)");

  // The flip side of by-reference capture: as long as a closure is reachable,
  // EVERY binding it closed over is also reachable, and therefore NOT
  // collectable by the GC. This is the canonical accidental-retention leak
  // pattern. 🔗 GARBAGE_COLLECTION owns V8's reachability / collector; HERE we
  // demonstrate the REACHABILITY precondition for retention (provable without
  // running the GC, which is nondeterministic).

  // makeBig builds a deterministically-filled array (no Math.random / Date.now).
  function makeBig(size: number): number[] {
    const a: number[] = new Array(size);
    for (let i = 0; i < size; i++) {
      a[i] = i;
    }
    return a;
  }

  // --- The leak pattern: closing over MORE than you use --------------------
  // This factory builds a big object, then returns a closure that only reads
  // `big.length`. But the closure references `big` (the whole array), so `big`
  // is retained for the closure's entire reachable lifetime — even though the
  // closure never reads a single element. The outer function has RETURNED; the
  // only thing keeping `big` alive is the closure's captured reference.
  function makeLeakyReader(): () => number {
    const big = makeBig(1000); // a 1000-element array
    return (): number => big.length; // closes over `big` (the whole array)
  }
  const leaky = makeLeakyReader(); // makeLeakyReader has returned; `big` has no name
  console.log("Leak pattern — closure closes over a big object it barely uses:");
  console.log("  function makeLeakyReader() {");
  console.log("    const big = makeBig(1000);      // 1000-element array");
  console.log("    return () => big.length;         // closes over the WHOLE `big`");
  console.log("  }");
  console.log(`  const leaky = makeLeakyReader();  // outer fn has returned`);
  console.log(`  leaky() -> ${leaky()}   // \`big\` is STILL alive (retained by the closure)`);
  check("retention: leaky() === 1000 (closure keeps `big` alive after return)", leaky() === 1000);

  // --- The fix: capture only the PRIMITIVE you need ------------------------
  // If the closure closes over `len` (a number primitive) instead of `big`
  // (the array), then `big` has NO remaining reference once the factory returns
  // and becomes eligible for collection. The closure still works, but it no
  // longer pins a large structure on the heap.
  function makeLeanReader(): () => number {
    const big = makeBig(1000);
    const len = big.length; // capture the PRIMITIVE length
    return (): number => len; // closes over `len`, NOT `big`
  }
  const lean = makeLeanReader();
  console.log("");
  console.log("Fix — capture only the primitive you need (`big` becomes collectable):");
  console.log("  function makeLeanReader() {");
  console.log("    const big = makeBig(1000);");
  console.log("    const len = big.length;        // destructure the needed value");
  console.log("    return () => len;               // closes over `len`, NOT `big`");
  console.log("  }");
  console.log(`  const lean = makeLeanReader();`);
  console.log(`  lean() -> ${lean()}   // same answer; \`big\` is no longer referenced`);
  check("lean reader: lean() === 1000 (same answer, no big-object retention)", lean() === 1000);

  // --- Reachability is the precondition (provable; GC timing is not) -------
  // We CANNOT prove `big` was freed (collection timing is engine-dependent and
  // nondeterministic — see §4.2 rule 1/2). But we CAN prove the STRUCTURAL
  // precondition: the leaky closure holds a path to a 1000-element object, the
  // lean one does not. "Reachable from a root => retained" is the rule; the
  // leaky closure is that root for `big`.
  console.log("");
  console.log("Reachability is the precondition (GC timing is NOT asserted here):");
  console.log("  leaky holds a captured reference to a 1000-element array -> it is reachable");
  console.log("  lean  holds only a captured number               -> the array is NOT reachable from it");
  check(
    "both readers agree on length (1000); only the leaky one retains the array",
    leaky() === lean() && leaky() === 1000,
  );

  // --- Shared-mutability via capture (the by-reference consequence) --------
  // Because capture is by reference, two closures over the SAME object see each
  // other's mutations. This is the 🔗 VALUE_VS_REFERENCE bug class expressed
  // through closures: an object captured by a closure is a SHARED reference.
  const shared = { count: 0 };
  const increment = (): void => {
    shared.count += 1;
  };
  const readCount = (): number => shared.count;
  increment();
  increment();
  console.log("");
  console.log("Shared mutability via capture (by-reference consequence):");
  console.log("  const shared = { count: 0 };");
  console.log("  const increment = () => { shared.count += 1; };");
  console.log("  const readCount = () => shared.count;");
  console.log(`  increment(); increment(); readCount() -> ${readCount()}`);
  check("two closures over one object see the same mutations (shared reference)", readCount() === 2);
}

// ============================================================================
// Section E — Idioms built on capture + the cross-language capture model
// ============================================================================

// --- memoize: a result cache held in a closure ------------------------------
// The cache Map is captured by the returned function. A repeat call with the
// same key returns the cached value WITHOUT re-running `fn`. Deterministic and
// observable: we count how many times the underlying fn actually ran.
function memoize<A extends string, R>(fn: (a: A) => R, calls: { count: number }): (a: A) => R {
  const cache = new Map<A, R>();
  return (a: A): R => {
    const hit = cache.get(a);
    if (hit !== undefined) {
      return hit;
    }
    calls.count += 1; // only real (cache-miss) calls increment this
    const r = fn(a);
    cache.set(a, r);
    return r;
  };
}

// --- once: run a function exactly once, cache the first result --------------
// The `done` flag and the cached result live in the closure. Every later call
// returns the FIRST result without re-invoking fn.
function once<A extends unknown[], R>(fn: (...a: A) => R, calls: { count: number }): (...a: A) => R {
  const cell: { done: boolean; value: R | undefined } = { done: false, value: undefined };
  return (...a: A): R => {
    if (!cell.done) {
      calls.count += 1;
      cell.value = fn(...a);
      cell.done = true;
    }
    return cell.value as R; // type-only assertion (erased at runtime)
  };
}

function sectionE(): void {
  sectionBanner("E — Idioms built on capture + the cross-language capture model");

  // --- memoize: cache via closure ------------------------------------------
  const heavyCalls = { count: 0 };
  const squareCached = memoize(
    (n: string): number => Number(n) * Number(n),
    heavyCalls,
  );
  const m1 = squareCached("12");
  const m2 = squareCached("12"); // cache hit — fn NOT re-run
  const m3 = squareCached("5"); // cache miss — fn runs
  console.log("memoize — a result cache held in a closure:");
  console.log(`  squareCached("12") -> ${m1}`);
  console.log(`  squareCached("12") -> ${m2}   (cache HIT: fn not re-run)`);
  console.log(`  squareCached("5")  -> ${m3}   (cache MISS: fn runs)`);
  console.log(`  underlying fn actually ran ${heavyCalls.count} time(s)`);
  check("memoize: 12*12 === 144", m1 === 144);
  check("memoize: repeat call returns cached 144", m2 === 144);
  check("memoize: fn ran exactly twice (2 unique keys: 12 and 5)", heavyCalls.count === 2);

  // --- once: run-once via a closure flag -----------------------------------
  const initCalls = { count: 0 };
  const initialize = once((): string => "initialized", initCalls);
  const o1 = initialize();
  const o2 = initialize();
  const o3 = initialize();
  console.log("");
  console.log("once — run exactly once, cache the first result (flag in closure):");
  console.log(`  initialize() -> ${JSON.stringify(o1)}`);
  console.log(`  initialize() -> ${JSON.stringify(o2)}   (cached; fn NOT re-run)`);
  console.log(`  initialize() -> ${JSON.stringify(o3)}   (cached; fn NOT re-run)`);
  console.log(`  underlying fn actually ran ${initCalls.count} time(s)`);
  check('once: every call returns the first result "initialized"', o1 === "initialized" && o2 === o1 && o3 === o1);
  check("once: fn ran exactly once across three calls", initCalls.count === 1);

  // --- curry / partial application: nested closures ------------------------
  // Each partial application is a closure over the arguments captured so far.
  function add(a: number): (b: number) => (c: number) => number {
    return (b: number): ((c: number) => number) => (c: number): number => a + b + c;
  }
  const addOne = add(1); // capture a=1
  const addOneTwo = addOne(2); // capture b=2 (a still 1)
  const curried = addOneTwo(3); // 1 + 2 + 3
  console.log("");
  console.log("curry / partial application — nested closures capture args step by step:");
  console.log(`  add(1)(2)(3)       -> ${add(1)(2)(3)}`);
  console.log(`  const addOne = add(1); addOne(2)(3) -> ${addOne(2)(3)}   (partial application)`);
  console.log(`  addOneTwo(3)       -> ${curried}`);
  check("curry: add(1)(2)(3) === 6", add(1)(2)(3) === 6);
  check("curry: partial application addOne(2)(3) === 6", addOne(2)(3) === 6);

  // --- `this` recap (brief; P1 owns detail) --------------------------------
  // An arrow function captures lexical `this` (it is a closure over `this`);
  // a classic `function` does NOT — its `this` is determined by the CALL SITE.
  // When a classic function is DETACHED from its object and called bare, its
  // `this` is undefined in strict mode (the famous this-loss trap; see P1).
  // Here we only pin the arrow side: the arrow inside `tickArrow` closes over
  // the method's `this`, so `this.n` resolves to `counter.n`.
  const counter = {
    n: 0,
    tickArrow: function (): number {
      const inner = (): number => ++this.n; // arrow captures lexical `this`
      return inner();
    },
  };
  console.log("");
  console.log("`this` recap — arrow captures lexical this (a closure over `this`):");
  console.log("  const counter = { n: 0, tickArrow() { const inner = () => ++this.n; return inner(); } };");
  const tickResult = counter.tickArrow();
  console.log(`  counter.tickArrow() -> ${tickResult}   (arrow closed over method \`this\` == counter)`);
  check("arrow captures lexical this: counter.tickArrow() === 1", tickResult === 1);

  // --- Cross-language capture model (JS vs Rust) ---------------------------
  // JS has exactly ONE capture mode: by reference (a live binding). There is no
  // choice, no annotation, no compile-time ownership. Rust makes capture
  // EXPLICIT and TYPED via three traits, plus the `move` keyword. This is THE
  // contrast that makes "JS closures always capture by ref" vivid.
  console.log("");
  console.log("Cross-language capture model — JS (one implicit mode) vs Rust (explicit + typed):");
  console.log("  JS:  capture is ALWAYS by reference (a live binding). No choice, no");
  console.log("       annotation, no move. The captured variable stays alive as long as");
  console.log("       the closure is reachable (the Section D retention rule).");
  console.log("  Rust Fn    : captures by shared reference (&T)        — callable many times");
  console.log("  Rust FnMut : captures by mutable reference (&mut T)   — callable many times, may mutate");
  console.log("  Rust FnOnce: captures by MOVE (owns T)               — callable exactly ONCE");
  console.log("  Rust `move` keyword: forces every capture to be BY VALUE (a move),");
  console.log("       overriding the compiler's by-ref default. JS has NO equivalent.");
  check(
    "JS capture mode is singular (by-reference); Rust exposes 3 traits + move",
    true, // documented language-design fact; not executable across languages here
  );
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("closures_capture.ts — Phase 3 bundle.");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: a closure is a function + the variables it CAPTURED. JS");
  console.log("captures BY REFERENCE (a live binding) — never by value, never by move.");
  console.log("That one fact drives every section below (counter, module, loop trap,");
  console.log("retention leak) and contrasts with Rust's explicit Fn/FnMut/FnOnce.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
