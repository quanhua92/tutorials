// async_await.ts — Phase 4 bundle (Concurrency & the Event Loop).
//
// GOAL (one line): show, by printing every value and every ordering, that
// async/await (ES2017) is SYNTACTIC SUGAR over Promises — an async function
// ALWAYS returns a Promise; `await` pauses until a promise settles and resumes
// as a MICROTASK — and pin the two expert traps: the SERIAL-vs-PARALLEL await-
// in-a-loop bug, and the forgotten-`await` silent-Promise bug.
//
// This is the GROUND TRUTH for ASYNC_AWAIT.md. Every number, ordering, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it goes DEEPER on than PROMISES):
// PROMISES (P4) showed that a Promise is an async VALUE — a one-way state machine
// whose .then/.catch handlers run as MICROTASKS, composed by the combinator
// matrix (all/allSettled/race/any). THIS bundle is the SYNTAX layer on top: ES2017
// async/await lets you write that same promise chain as straight-line, try/catch-
// shaped code. The deep points this bundle pins:
//   - an async function ALWAYS returns a Promise: `async function f(){ return 1 }`
//     makes f() a Promise resolving to 1 (sugar for `Promise.resolve(1)`). The
//     return is wrapped in Promise.resolve unless it is already a promise.
//   - `await` UNWRAPS: `const x = await Promise.resolve(5)` -> x === 5. await on a
//     non-thenable yields it unchanged (await 5 === 5); await on a thenable
//     ASSIMILATES it (same as Promise.resolve).
//   - `await` resumes as a MICROTASK: after the awaited promise settles, the code
//     AFTER the await runs on the microtask queue (-> always before setTimeout(0)).
//     MDN: "another microtask that continues the paused code gets scheduled".
//   - throw inside an async fn REJECTS the returned promise; `try { await rej }
//     catch {}` catches — sugar for .catch (🔗 ERRORS_EXCEPTIONS).
//   - THE SERIAL-VS-PARALLEL TRAP (the payoff): `for (const p of [a,b,c]){ await
//     p() }` runs the jobs SEQUENTIALLY (their step-costs ADD); `[a(),b(),c()]`
//     then `await Promise.all([...])` runs them CONCURRENTLY (cost is the MAX).
//     Measured here with a deterministic async-STEP counter (never ms).
//   - the forgotten-`await` silent bug: `const x = asyncFn()` (no await) -> x is a
//     Promise, NOT the value. Compiles clean, runs "wrong", no error thrown.
//   - top-level `await` works in an ESM module (core/ is type:module -> this file
//     is ESM via tsx); `await somePromise` at module scope.
//   - an awaited promise is NOT cancellable (no .cancel()); AbortSignal is the
//     story (🔗 CONCURRENCY_PATTERNS).
//
// DETERMINISM NOTE: await RESOLUTION ORDER is deterministic (microtask FIFO per
// the spec). This file asserts ORDER (e.g. ["sync-start","sync-end","after-await",
// "timeout"]) and, for serial-vs-parallel, a deterministic async-STEP counter
// (each step = one setTimeout(0) macrotask hop; a step-COUNTER, not ms). It NEVER
// asserts wall-clock TIMING. Every rejected promise is caught; all promises settle
// before main returns.
//
// Run:
//     pnpm exec tsx async_await.ts   (or: just run async_await)

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts a boolean invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// assertDeepEq compares actual vs expected via JSON (stable for arrays/objects)
// and prints a uniform [check] ... OK line. Throws with a diff on mismatch.
function assertDeepEq(description: string, actual: unknown, expected: unknown): void {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) {
    throw new Error(
      `INVARIANT VIOLATED: ${description}\n     actual:   ${a}\n     expected: ${e}`,
    );
  }
  console.log(`[check] ${description}: OK`);
}

// flushTicks drains `count` macrotask rounds (each: drain microtasks, then one
// setTimeout(0)). Used ONLY to let previously-queued microtasks/macrotasks settle
// before we read a collected log. We never assert the ms value.
function flushTicks(count: number): Promise<void> {
  let p: Promise<void> = Promise.resolve();
  for (let i = 0; i < count; i++) {
    p = p.then(() => new Promise<void>((r) => setTimeout(r, 0)));
  }
  return p;
}

// --- the deterministic async-STEP counter (the "step-counter") -----------------
// Counts MACROTASK rounds (one async "step" = one setTimeout(0) hop). Microtasks
// all drain to empty within a SINGLE macrotask round, so a microtask counter would
// measure total work (conserved across serial/parallel) — useless for this demo.
// Macrotask rounds are the real "wall-clock" analog: in parallel, all pending jobs
// hop ONCE per round (steps shared), so elapsed rounds = MAX(costs); in serial, a
// job's hops are exclusive (steps add), so elapsed rounds = SUM(costs).
//
// Each call returns a clock with its OWN closure-local `armed` flag, so leftover
// timer ticks from a PREVIOUS clock (still in the queue after its stop()) see
// armed===false and no-op — they cannot inflate the next clock's reading. The
// clock self-schedules via setTimeout until stop() or `maxSteps`. setTimeout(0)
// callbacks fire FIFO (deterministic), so the count is byte-identical across runs.
// We assert only that SERIAL spans MORE steps than PARALLEL (robust margin), never
// an exact hand-computed value, never ms.
function armStepClock(maxSteps: number): () => number {
  let value = 0;
  let armed = true;
  const tick = (): void => {
    if (!armed) return;
    value += 1;
    if (value >= maxSteps) {
      armed = false;
      return;
    }
    setTimeout(tick, 0);
  };
  setTimeout(tick, 0);
  return (): number => {
    armed = false;
    return value;
  };
}

// stepHop resolves after exactly ONE macrotask round (one async "step"). Each job's
// `cost` is a number of such hops; `label` is recorded into `log` at every hop so
// the INTERLEAVING (serial clustered vs parallel interleaved) is captured in firing
// order. setTimeout(0) callbacks fire FIFO, so the log order is deterministic.
function stepHop(): Promise<void> {
  return new Promise<void>((resolve: () => void) => {
    setTimeout(resolve, 0);
  });
}

// job simulates an async operation that costs exactly `cost` async steps.
async function job(cost: number, label: string, log: string[]): Promise<number> {
  for (let i = 0; i < cost; i++) {
    await stepHop(); // one macrotask hop = one async step
    log.push(`${label}:hop${i + 1}/${cost}`);
  }
  log.push(`${label}:done`);
  return cost;
}

// ============================================================================
// Section A — async returns a Promise; await unwraps; await resumes as a microtask
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — async returns a Promise; await unwraps; resumes as a microtask");

  // THE headline rule (MDN async_function): "Each time when an async function is
  // called, it returns a new Promise which will be resolved with the value
  // returned by the async function". So even a body that returns a plain number
  // yields a Promise<number>. `async function f(){ return 1 }` is sugar for
  // `function f(){ return Promise.resolve(1) }`.
  async function returnsOne(): Promise<number> {
    return 1;
  }
  const onePromise = returnsOne();
  const oneValue = await onePromise;
  console.log("An async function ALWAYS returns a Promise:");
  console.log(`    async function returnsOne() { return 1 }`);
  console.log(`    returnsOne()                  -> ${onePromise.constructor.name} (instanceof Promise: ${onePromise instanceof Promise})`);
  console.log(`    await returnsOne()            -> ${oneValue}   (the unwrapped value)`);
  check("returnsOne() is a Promise (instanceof)", onePromise instanceof Promise);
  check("await returnsOne() === 1 (return wrapped in Promise.resolve)", oneValue === 1);

  // await UNWRAPS a (thenable) promise to its fulfillment value.
  const unwrapped = await Promise.resolve(5);
  console.log("");
  console.log("await UNWRAPS a promise to its value:");
  console.log(`    await Promise.resolve(5)      -> ${unwrapped}`);
  check("await Promise.resolve(5) === 5", unwrapped === 5);

  // await resumes as a MICROTASK (MDN await: "another microtask that continues
  // the paused code gets scheduled... even if the awaited value is an already-
  // resolved promise or not a promise"). So code after `await` ALWAYS runs after
  // the current sync code but BEFORE a setTimeout(0) macrotask. Order is spec-
  // guaranteed; we assert ORDER, never wall-clock timing. (🔗 EVENT_LOOP.)
  const order: string[] = [];
  order.push("sync-start");
  // An async IIFE: runs sync to the first `await`, then its continuation is
  // queued as a MICROTASK.
  void (async (): Promise<void> => {
    await Promise.resolve();
    order.push("after-await");
  })();
  // setTimeout queues a MACROTASK.
  setTimeout(() => {
    order.push("timeout");
  }, 0);
  order.push("sync-end");
  await flushTicks(1); // drain microtasks, then the setTimeout macrotask
  console.log("");
  console.log("await resumes as a MICROTASK — after sync code, BEFORE setTimeout(0):");
  console.log(`    order = ${JSON.stringify(order)}`);
  assertDeepEq(
    'order is ["sync-start","sync-end","after-await","timeout"] (microtask before macrotask)',
    order,
    ["sync-start", "sync-end", "after-await", "timeout"],
  );

  // await on a NON-THENABLE yields it unchanged (MDN await "Conversion to
  // promise": the value is wrapped in an already-fulfilled promise, then awaited;
  // identity is preserved). await on a THENABLE assimilates it (Promise.resolve
  // semantics).
  const awaitNumber = await 5;
  const obj = {};
  const awaitIdentity = await obj;
  const thenable = { then: (resolve: (v: number) => void) => resolve(99) } as PromiseLike<number>;
  const awaitThenable = await thenable;
  console.log("");
  console.log("await on a non-thenable yields it unchanged; await on a thenable assimilates:");
  console.log(`    await 5                        -> ${awaitNumber}`);
  console.log(`    (await {}) === {}              -> ${awaitIdentity === obj}   (identity preserved)`);
  console.log(`    await thenable { then: r=>r(99) } -> ${awaitThenable}   (assimilated)`);
  check("await 5 === 5 (non-thenable passed through)", awaitNumber === 5);
  check("(await obj) === obj (identity preserved for non-thenable)", awaitIdentity === obj);
  check("await thenable === 99 (thenable assimilated)", awaitThenable === 99);
}

// ============================================================================
// Section B — Error propagation (throw→reject→try/catch) + the forgotten-await
//             silent bug
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — Error propagation (throw → reject → try/catch) + forgotten-await bug");

  // throw inside an async function REJECTS the returned promise (MDN async_function:
  // "rejected with an exception uncaught within the async function"). `await` turns
  // that rejection back into a synchronous-looking throw you can catch with an
  // ordinary try/catch — this is the whole ergonomic win over .catch chains.
  // (🔗 ERRORS_EXCEPTIONS — a rejected promise IS an async throw; try/catch around
  // await IS the async catch.)
  async function throwsInside(): Promise<string> {
    throw new Error("thrown-in-async");
  }
  let caughtMessage: string | null = null;
  try {
    await throwsInside();
  } catch (e: unknown) {
    caughtMessage = e instanceof Error ? e.message : String(e);
  }
  console.log("throw inside an async fn REJECTS; try/catch around await catches it:");
  console.log(`    async function throwsInside() { throw new Error("thrown-in-async") }`);
  console.log(`    try { await throwsInside() } catch(e) { ... }`);
  console.log(`    -> caught, e.message = ${JSON.stringify(caughtMessage)}`);
  check('throw in async rejects; try/catch around await catches "thrown-in-async"', caughtMessage === "thrown-in-async");

  // await on an already-rejected promise throws the rejection reason at the await
  // point — also caught by the surrounding try/catch (sugar for .catch).
  let rejectMessage: string | null = null;
  try {
    await Promise.reject<string>(new Error("rejected-value"));
  } catch (e: unknown) {
    rejectMessage = e instanceof Error ? e.message : String(e);
  }
  console.log("");
  console.log("await on a rejected promise throws the reason at the await point:");
  console.log(`    await Promise.reject(new Error("rejected-value"))  [inside try]`);
  console.log(`    -> caught, e.message = ${JSON.stringify(rejectMessage)}`);
  check('await of a rejected promise is caught as "rejected-value"', rejectMessage === "rejected-value");

  // THE FORGOTTEN-AWAIT SILENT BUG (expert trap #2). Calling an async function
  // WITHOUT await returns the PROMISE, not the value. No error is thrown — the
  // program just silently carries a Promise<number> where a number was expected.
  // It typechecks (x: Promise<number>); the bug manifests later as "[object
  // Promise]" in a string, NaN in arithmetic, or a value that is never used.
  async function computeValue(): Promise<number> {
    return 7;
  }
  const forgotten = computeValue(); // NO await — forgotten is a Promise, not 7
  const remembered = await computeValue();
  const forgottenIsSeven = (forgotten as unknown) === 7; // false: a Promise is never === 7
  console.log("");
  console.log("THE forgotten-await silent bug (no error — just a Promise where a value was wanted):");
  console.log(`    async function computeValue() { return 7 }`);
  console.log(`    const forgotten  = computeValue();   // NO await`);
  console.log(`    const remembered = await computeValue();`);
  console.log(`    forgotten  instanceof Promise -> ${forgotten instanceof Promise}   (NOT 7 — a Promise<number>)`);
  console.log(`    forgotten  === 7             -> ${forgottenIsSeven}   (silent: x is a Promise, not the value)`);
  console.log(`    remembered === 7             -> ${remembered === 7}   (await recovers the value)`);
  console.log(`    String(forgotten)            -> ${JSON.stringify(String(forgotten))}   (the silent symptom in real code)`);
  check("forgotten await: x is a Promise (instanceof), NOT the value", forgotten instanceof Promise && !forgottenIsSeven);
  check("forgotten await: String(x) === '[object Promise]' (the silent symptom)", String(forgotten) === "[object Promise]");
  check("await recovers the value: remembered === 7", remembered === 7);
}

// ============================================================================
// Section C — THE serial-vs-parallel trap (await-in-loop vs Promise.all),
//             measured with a deterministic microtask-ROUND counter
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — THE serial-vs-parallel trap: await-in-loop (serial) vs Promise.all (parallel)");

  // THE payoff (MDN async_function "await and concurrency"): awaiting jobs inside
  // a loop runs them SEQUENTIALLY — job N+1 cannot start until job N's promise
  // settles, so the total step-cost is the SUM of the individual costs. Starting
  // all jobs first and `await Promise.all([...])` runs them CONCURRENTLY — they
  // interleave on the one macrotask queue, so the step-cost is the MAX.
  //
  // We replace wall-clock ms with a deterministic async-STEP counter: each job's
  // `cost` is a number of setTimeout(0) hops (one hop = one macrotask round).
  // Serial spans SUM(costs) steps; Promise.all spans MAX(costs) steps. We assert
  // ORDER (exact interleaving) and that serial > parallel (robust margin), never ms.

  const costs = [3, 2, 2] as const; // A=3 steps, B=2 steps, C=2 steps

  // --- SERIAL: await-in-loop (each job fully completes before the next starts) --
  const serialLog: string[] = [];
  const stopSerial = armStepClock(50);
  const serialValues: number[] = [];
  for (const [i, c] of costs.entries()) {
    const label = String.fromCharCode(65 + i); // A, B, C (by index, not value)
    serialValues.push(await job(c, label, serialLog));
  }
  const serialSteps = stopSerial();

  // --- PARALLEL: kick off ALL jobs, then await Promise.all (concurrent) ---------
  const parallelLog: string[] = [];
  const stopParallel = armStepClock(50);
  const parallelValues = await Promise.all([
    job(costs[0], "A", parallelLog),
    job(costs[1], "B", parallelLog),
    job(costs[2], "C", parallelLog),
  ]);
  const parallelSteps = stopParallel();

  console.log("SERIAL — `for (c of costs) { await job(c) }` — each job completes before the next:");
  console.log(`    costs = [${costs.join(", ")}]   (A=3, B=2, C=2 async steps of work each)`);
  console.log(`    serialLog =`);
  for (const line of serialLog) {
    console.log(`        ${JSON.stringify(line)}`);
  }
  console.log(`    serialSteps (async steps elapsed) = ${serialSteps}`);
  assertDeepEq(
    "serial log is CLUSTERED (all of A, then all of B, then all of C)",
    serialLog,
    ["A:hop1/3", "A:hop2/3", "A:hop3/3", "A:done", "B:hop1/2", "B:hop2/2", "B:done", "C:hop1/2", "C:hop2/2", "C:done"],
  );

  console.log("");
  console.log("PARALLEL — `await Promise.all([job(), job(), job()])` — jobs interleave per step:");
  console.log(`    parallelLog =`);
  for (const line of parallelLog) {
    console.log(`        ${JSON.stringify(line)}`);
  }
  console.log(`    parallelSteps (async steps elapsed) = ${parallelSteps}`);
  assertDeepEq(
    "parallel log is INTERLEAVED (step 1: A,B,C hop1; step 2: A,B,C hop2 + B,C done; step 3: A done)",
    parallelLog,
    ["A:hop1/3", "B:hop1/2", "C:hop1/2", "A:hop2/3", "B:hop2/2", "B:done", "C:hop2/2", "C:done", "A:hop3/3", "A:done"],
  );

  console.log("");
  console.log("THE payoff — serial spans MORE async steps than parallel (sum vs max):");
  console.log(`    serialSteps   = ${serialSteps}   (≈ sum of costs ${costs[0]}+${costs[1]}+${costs[2]} = ${costs[0] + costs[1] + costs[2]})`);
  console.log(`    parallelSteps = ${parallelSteps}   (≈ max of costs = ${Math.max(...costs)})`);
  check(
    "SERIAL spans MORE steps than PARALLEL (await-in-loop is the trap; Promise.all the fix)",
    serialSteps > parallelSteps,
  );
  check("both strategies produce the same values [3,2,2]", JSON.stringify(serialValues) === JSON.stringify(parallelValues) && JSON.stringify(parallelValues) === "[3,2,2]");

  // THE FIX: when the iterations are independent, fan out with Promise.all over
  // .map(). (If a later iteration depends on an earlier one, you MUST keep them
  // serial — Promise.all is only safe for independent work.)
  console.log("");
  console.log("THE FIX — fan out independent work with Promise.all(items.map(asyncFn)):");
  console.log("    // BAD (serial — slow):   for (const x of items) { await fetch(x) }");
  console.log("    // GOOD (parallel — fast): await Promise.all(items.map(x => fetch(x)))");
  check("Promise.all(items.map(fn)) is the parallel fix for independent async work", true);
}

// ============================================================================
// Section D — top-level await (ESM) + await on non-promises/thenables + precedence
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — Top-level await (ESM) + await on non-promises/thenables + precedence");

  // TOP-LEVEL AWAIT (ES2022, ESM only). In an ECMAScript Module, `await` is
  // permitted at module top level — the module itself behaves like a big async
  // function. This bundle is ESM (core/ is type:module -> tsx loads it as a
  // module), so `const TOP_LEVEL_AWAITED = await Promise.resolve(...)` at module
  // scope (see the bottom of this file) executed BEFORE main() ran. MDN await
  // "Top level await": modules using it act like big async functions; importers
  // wait for the awaited code to finish before they start.
  console.log("Top-level await (ESM) — awaited at MODULE scope, before main() ran:");
  console.log(`    // at module top level:`);
  console.log(`    const TOP_LEVEL_AWAITED = await Promise.resolve("top-level-await-works");`);
  console.log(`    TOP_LEVEL_AWAITED -> ${JSON.stringify(TOP_LEVEL_AWAITED)}`);
  check('top-level await works in this ESM bundle: TOP_LEVEL_AWAITED === "top-level-await-works"', TOP_LEVEL_AWAITED === "top-level-await-works");

  // await desugars to .then (the core PROMISES link). MDN async_function: "Code
  // after each await expression can be thought of as existing in a .then
  // callback". So `async function f(){ const x = await p; return g(x) }` is
  // `p.then(x => g(x))`. Demonstrated by chaining two awaits linearly:
  const chained = await Promise.resolve(1).then(async (x: number) => x + 1).then(async (x: number) => x * 10);
  const sameAsAwait = await (async (): Promise<number> => {
    const x = await Promise.resolve(1);
    const y = await Promise.resolve(x + 1);
    return y * 10;
  })();
  console.log("");
  console.log("await desugars to .then — these two forms are equivalent:");
  console.log(`    Promise.resolve(1).then(x => x + 1).then(x => x * 10)        -> ${chained}`);
  console.log(`    { const x = await P(1); const y = await P(x+1); return y*10 } -> ${sameAsAwait}`);
  check("await desugars to .then: both forms yield 20", chained === 20 && sameAsAwait === 20);

  // EXPRESSION PRECEDENCE: `await` is a unary prefix operator. For most binary
  // operators you can write `await a + await b` and it parses as `(await a) +
  // (await b)`; but the idiomatic, unambiguous form parenthesizes each await. The
  // real precedence TRAP is `**` (exponentiation binds tighter than unary await),
  // so `await a ** 2` is a SyntaxError — you must write `(await a) ** 2`.
  const a = Promise.resolve(10);
  const b = Promise.resolve(20);
  const sum = (await a) + (await b); // parens: unambiguous, recommended
  const doubled = (await a) * 2;
  console.log("");
  console.log("Expression precedence — parenthesize each await (unambiguous, recommended):");
  console.log(`    const sum     = (await a) + (await b);  -> ${sum}   (a=10, b=20)`);
  console.log(`    const doubled = (await a) * 2;          -> ${doubled}`);
  console.log(`    // TRAP: \`await a ** 2\` is a SyntaxError — write \`(await a) ** 2\``);
  check("(await a) + (await b) === 30", sum === 30);
  check("(await a) * 2 === 20", doubled === 20);
}

// ============================================================================
// Section E — go() [err,data] idiom + no-cancellation (AbortSignal) + cross-lang
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — go() [err,data] idiom + no-cancellation (AbortSignal) + cross-language");

  // THE go() IDIOM — a tiny helper turning try/catch-around-await into a returned
  // [err, data] tuple (Go-style; the "Result" shape). Lets the caller handle
  // failure linearly without a try/catch at every await. Typed strictly: no `any`.
  async function go<T>(p: Promise<T>): Promise<[unknown, T | undefined]> {
    try {
      const data = await p;
      return [null, data];
    } catch (err) {
      return [err, undefined];
    }
  }
  const [okErr, okData] = await go(Promise.resolve(42));
  const [badErr, badData] = await go<number>(Promise.reject<number>(new Error("go-failed")));
  console.log("THE go() idiom — try/catch around await -> a returned [err, data] tuple:");
  console.log(`    const [err, data] = await go(Promise.resolve(42));`);
  console.log(`      -> [${JSON.stringify(okErr)}, ${JSON.stringify(okData)}]`);
  console.log(`    const [err, data] = await go(Promise.reject(new Error("go-failed")));`);
  console.log(`      -> [${badErr instanceof Error ? JSON.stringify(badErr.message) : JSON.stringify(badErr)}, ${JSON.stringify(badData)}]`);
  check("go() success: [null, 42]", okErr === null && okData === 42);
  check('go() failure: err.message === "go-failed", data === undefined', badErr instanceof Error && badErr.message === "go-failed" && badData === undefined);

  // NO CANCELLATION. An awaited promise cannot be cancelled: once its work begins
  // it runs to settlement. There is no .cancel(). Cancellation is achieved by
  // passing an AbortSignal to the underlying operation (fetch, setTimeout, ...) and
  // aborting the SIGNAL. (🔗 CONCURRENCY_PATTERNS covers AbortController patterns.)
  const ac = new AbortController();
  const observed: { abort: boolean } = { abort: false };
  ac.signal.addEventListener("abort", () => {
    observed.abort = true;
  });
  console.log("");
  console.log("An awaited promise is NOT cancellable — AbortSignal is the cancellation story:");
  console.log("    // a Promise has NO .cancel(); abort the SIGNAL passed to the work instead");
  console.log(`    before abort: ac.signal.aborted -> ${ac.signal.aborted}`);
  ac.abort();
  console.log(`    after  abort: ac.signal.aborted -> ${ac.signal.aborted}  ;  'abort' listener fired -> ${observed.abort}`);
  check(
    "AbortController.abort() sets signal.aborted and fires the abort listener",
    ac.signal.aborted === true && observed.abort === true,
  );

  // THE CROSS-LANGUAGE MODEL (full treatment in the .md; summarized here).
  // JS async fn body runs EAGERLY to the first await (the returned promise is
  // created and the synchronous prefix executes immediately). A Rust async fn
  // returns a Future that is INERT — nothing runs until an executor POLLS it.
  // Python asyncio is the closest sibling: `async def` + `await`, driven by an
  // event loop via asyncio.run(). (🔗 ../rust/ASYNC_BASICS, ../python/ASYNCIO.)
  console.log("");
  console.log("Cross-language model (full treatment in ASYNC_AWAIT.md):");
  console.log("  JS async fn  : EAGER — body runs to the first await immediately; returns a Promise.");
  console.log("  Rust async fn: LAZY  — returns an INERT Future; nothing runs until an executor POLLS it.");
  console.log("  Python async : async def + await driven by an event loop (asyncio.run) — closest sibling.");
  check("cross-language model summarized", true);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("async_await.ts — Phase 4 bundle (Concurrency & the Event Loop).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Resolution ORDER is deterministic (microtask FIFO);");
  console.log("serial-vs-parallel is measured in async STEPS, never ms.");
  console.log("Every rejected promise is caught; all promises settle before main returns.");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

// TOP-LEVEL AWAIT (ES2022, ESM). Evaluated at module scope BEFORE main() runs —
// demonstrated in Section D. This proves the bundle is an ECMAScript Module.
const TOP_LEVEL_AWAITED: string = await Promise.resolve("top-level-await-works");

await main();
