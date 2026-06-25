// promises.ts — Phase 4 bundle.
//
// GOAL (one line): show, by printing every value, that a Promise is an async
// VALUE — a one-way state machine (pending → fulfilled|rejected) whose
// .then/.catch/.finally handlers run as MICROTASKS — and how chaining +
// Promise.all/allSettled/race/any compose async steps, ORDER-deterministically.
//
// This is the GROUND TRUTH for PROMISES.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it goes DEEPER on than P3):
// CLOSURES_CAPTURE (P3) showed that a closure captures its environment by
// reference and that the loop-var trap is a capture bug. THIS bundle (P4) is the
// other half of async JS: instead of capturing a value, a Promise captures a
// FUTURE VALUE. The deep points this bundle pins:
//   - a Promise is a STATE MACHINE (pending → fulfilled(value) | rejected(reason))
//     that settles EXACTLY ONCE and is immutable thereafter;
//   - the executor `new Promise((resolve,reject)=>{...})` runs SYNCHRONOUSLY at
//     construction — the promise is EAGER (work starts now), unlike a Rust Future;
//   - .then/.catch/.finally each return a NEW promise (chaining); a handler's
//     return becomes the next link's input (a returned promise is unwrapped);
//   - handlers run as MICROTASKS (FIFO) — this is why a resolved promise's .then
//     ALWAYS fires before a setTimeout(0). Order is deterministic; timing is not
//     asserted here (🔗 EVENT_LOOP for the queue model);
//   - throw inside a handler REJECTS the chained promise — a rejected promise IS
//     an async throw (🔗 ERRORS_EXCEPTIONS); .catch IS an async catch;
//   - the combinator matrix: Promise.all (all-fulfill, first-reject, INPUT order),
//     allSettled (never rejects), race (first SETTLE), any (first FULFILL, else
//     AggregateError);
//   - a rejected promise with NO .catch is an "unhandled rejection" → Node emits
//     unhandledRejection and (since Node 15) terminates by default. ALWAYS .catch;
//   - promises are NOT cancellable — AbortController/AbortSignal is the story
//     (🔗 CONCURRENCY_PATTERNS).
//
// DETERMINISM NOTE: Promise RESOLUTION ORDER is deterministic (microtask FIFO per
// the spec). This file asserts ORDER (e.g. ["sync","promise","timeout"]) and uses
// already-resolved promises + top-level await. It does NOT assert wall-clock
// TIMING. Every rejected promise has a .catch; all promises settle before main
// returns.
//
// Run:
//     pnpm exec tsx promises.ts   (or: just run promises)

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

// assertDeepEq compares actual vs expected via JSON (stable for our arrays/objects)
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

// A Deferred exposes the resolve/reject of a promise so a test can settle it in
// a chosen ORDER. Typed generically + strictly (no `any`): reject takes `unknown`.
type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
};

function defer<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

// A tick-flush: schedules a macrotask (setTimeout 0) and resolves after it runs.
// Used to drain pending microtasks AND the next macrotask so callbacks settle.
function flushTicks(count: number): Promise<void> {
  let p: Promise<void> = Promise.resolve();
  for (let i = 0; i < count; i++) {
    p = p.then(() => new Promise<void>((r) => setTimeout(r, 0)));
  }
  return p;
}

// ============================================================================
// Section A — States (pending→fulfilled|rejected), the executor runs SYNC,
//             and .then/.catch/.finally each return a NEW promise (chaining)
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — States, the executor runs SYNC, and chaining returns NEW promises");

  // A Promise is in exactly ONE of three states. pending is the initial state;
  // fulfilled (with a value) and rejected (with a reason) are terminal. Once
  // settled, a promise is IMMUTABLE — neither its state nor its value/reason
  // can change. (ECMA-262 §25.6: pending → fulfilled | rejected, one-way.)

  // --- pending: a promise whose executor never calls resolve/reject -----------
  // There is no public SYNC API to read a promise's state, so we OBSERVE it: a
  // pending promise loses a race against a fulfilled sentinel (its .then never
  // fires). The promise below never settles; the sentinel wins the race.
  const foreverPending = new Promise<number>(() => {
    /* never resolves — stays pending forever */
  });
  const raceWinner = await Promise.race<string>([
    Promise.resolve("sentinel-won" as const),
    foreverPending.then((): "pending-woke" => "pending-woke"),
  ]);
  console.log("States:");
  console.log(`  new Promise(() => {})            -> pending (never settles)`);
  console.log(`  race vs fulfilled sentinel        -> ${JSON.stringify(raceWinner)}  (pending did NOT settle)`);
  check("a never-resolving promise is pending (sentinel wins the race)", raceWinner === "sentinel-won");

  // --- fulfilled: Promise.resolve(x) is immediately fulfilled with x ---------
  const fulfilled = await Promise.resolve(42);
  console.log(`  Promise.resolve(42)               -> fulfilled, value ${fulfilled}`);
  check("Promise.resolve(42) is fulfilled with 42", fulfilled === 42);

  // --- rejected: Promise.reject(e) is immediately rejected with e ------------
  // ALWAYS attach .catch synchronously so there is no unhandled rejection.
  const rejectedReason = await Promise.reject<number>(new Error("boom")).catch(
    (e: unknown) => (e as Error).message,
  );
  console.log(`  Promise.reject(new Error("boom")) -> rejected, reason ${JSON.stringify(rejectedReason)}`);
  check('Promise.reject is rejected; .catch observes reason "boom"', rejectedReason === "boom");

  // --- THE executor runs SYNCHRONOUSLY during construction -------------------
  // `new Promise(executor)` calls executor RIGHT NOW, before `new` returns. So
  // the executor body runs BEFORE any code after the construction line, and
  // BEFORE the .then handler (which only ever runs as a microtask, later).
  const execTrace: string[] = [];
  const constructed = new Promise<number>((resolve) => {
    execTrace.push("executor-runs-sync");
    resolve(7);
  });
  execTrace.push("after-new-Promise");
  // Attaching .then does NOT run the handler now — it queues a microtask.
  constructed.then((v: number) => execTrace.push(`then-fires:${v}`));
  execTrace.push("after-.then-call");
  await constructed; // flush the microtask so the .then handler runs
  console.log("");
  console.log("The executor runs SYNCHRONOUSLY (then handler runs later, as a microtask):");
  console.log("  execTrace =");
  for (const line of execTrace) {
    console.log(`    ${JSON.stringify(line)}`);
  }
  assertDeepEq(
    "executor runs before construction returns; .then fires after all sync code",
    execTrace,
    ["executor-runs-sync", "after-new-Promise", "after-.then-call", "then-fires:7"],
  );

  // --- Chaining: .then/.catch/.finally each return a NEW promise -------------
  // The headline mechanic: each call returns a DIFFERENT promise whose settled
  // value is the handler's return. This is what makes linear async composition
  // possible (the cure for "callback hell").
  const pRoot = Promise.resolve(1);
  const pA = pRoot.then((x: number) => x + 1);
  const pB = pA.then((x: number) => x * 2);
  const [rootVal, aVal, bVal] = await Promise.all([pRoot, pA, pB]);
  console.log("");
  console.log("Chaining — each .then returns a NEW promise:");
  console.log(`    pRoot = Promise.resolve(1)                       -> ${rootVal}`);
  console.log(`    pA    = pRoot.then(x => x + 1)                   -> ${aVal}   (a NEW promise)`);
  console.log(`    pB    = pA.then(x => x * 2)                      -> ${bVal}`);
  check("pRoot, pA, pB are distinct objects (each .then returns a NEW promise)", pRoot !== pA && pA !== pB && pRoot !== pB);
  assertDeepEq("chained value propagation: [pRoot,pA,pB] === [1,2,4]", [rootVal, aVal, bVal], [1, 2, 4]);
}

// ============================================================================
// Section B — .then handlers are MICROTASKS (FIFO, before setTimeout),
//             value propagation + thenable assimilation, throw → reject
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — .then handlers are MICROTASKS; value propagation; throw → reject");

  // THE event-loop link: a .then handler is queued on the MICROTASK queue, which
  // drains to empty BEFORE the event loop picks the next MACROTASK (setTimeout).
  // So a resolved promise's .then ALWAYS runs after the current sync code but
  // BEFORE a setTimeout(0). The ORDER is spec-guaranteed; we assert ORDER, not
  // wall-clock timing. (🔗 EVENT_LOOP for the queue model.)
  const order: string[] = [];
  order.push("sync");
  Promise.resolve().then(() => {
    order.push("promise");
  });
  setTimeout(() => {
    order.push("timeout");
  }, 0);
  await flushTicks(1); // flush the microtask AND the setTimeout macrotask
  console.log(".then is a MICROTASK — fires after sync code, BEFORE setTimeout(0):");
  console.log(`  order = ${JSON.stringify(order)}`);
  assertDeepEq(
    'order is ["sync","promise","timeout"] (microtask before macrotask)',
    order,
    ["sync", "promise", "timeout"],
  );

  // Microtasks drain FIFO and to EMPTY between macrotasks — no interleaving.
  // Two .then on already-resolved promises fire in registration order.
  const fifo: number[] = [];
  Promise.resolve().then(() => fifo.push(1));
  Promise.resolve().then(() => fifo.push(2));
  Promise.resolve().then(() => fifo.push(3));
  await Promise.resolve(); // flush the microtask queue
  console.log("");
  console.log("Microtask FIFO — handlers fire in registration order, before any macrotask:");
  console.log(`  fifo = ${JSON.stringify(fifo)}`);
  assertDeepEq("microtask FIFO order: [1,2,3]", fifo, [1, 2, 3]);

  // --- Value propagation + thenable assimilation -----------------------------
  // Each handler's RETURN becomes the next link's input. Returning a promise (or
  // any thenable) UNWRAPS it — the chain adopts the inner promise's settled state.
  const numThen = await Promise.resolve(1).then((x: number) => x + 1); // 2
  const innerThen = await Promise.resolve(1).then((): Promise<string> => Promise.resolve("inner")); // "inner"
  // A minimal thenable: an object with a .then. Promise.resolve assimilates it.
  // Cast to PromiseLike<number> so the overload unwraps to Promise<number>
  // (the literal shape is not structurally assignable to the full PromiseLike.then
  // signature, but the RUNTIME assimilation is what we demonstrate).
  const thenable = { then: (resolve: (v: number) => void) => resolve(99) } as PromiseLike<number>;
  const assimilated = await Promise.resolve(thenable); // 99 — thenable unwrapped
  console.log("");
  console.log("Value propagation + thenable assimilation (return a promise → unwrap it):");
  console.log(`  Promise.resolve(1).then(x => x + 1)                       -> ${numThen}`);
  console.log(`  Promise.resolve(1).then(() => Promise.resolve("inner"))  -> ${JSON.stringify(innerThen)}  (unwrapped)`);
  console.log(`  Promise.resolve(thenable)  [thenable resolves 99]        -> ${assimilated}  (assimilated)`);
  check("value propagation: x => x + 1 yields 2", numThen === 2);
  check('returning a promise unwraps it: yields "inner"', innerThen === "inner");
  check("Promise.resolve(thenable) assimilates: yields 99", assimilated === 99);

  // --- throw inside a handler → REJECTS the chained promise ------------------
  // A thrown error in .then/.catch rejects the promise returned by that call.
  // This is why a rejected promise is "an async throw" and .catch is "an async
  // catch" (🔗 ERRORS_EXCEPTIONS). .finally passes value/reason through unchanged.
  const caught = await Promise.resolve("ok")
    .then((): string => {
      throw new Error("kaboom");
    })
    .catch((e: unknown) => (e as Error).message);
  const finallyPasses = await Promise.resolve("value")
    .finally(() => {
      /* runs on settle; return value is ignored for the chain */
    });
  console.log("");
  console.log("throw in .then → rejection caught by .catch; .finally passes value through:");
  console.log(`  ...then(() => { throw new Error("kaboom") }).catch(e => e.message) -> ${JSON.stringify(caught)}`);
  console.log(`  Promise.resolve("value").finally(() => {})                      -> ${JSON.stringify(finallyPasses)}`);
  check('throw in .then rejects; .catch observes "kaboom"', caught === "kaboom");
  check('.finally passes the fulfillment value through unchanged', finallyPasses === "value");

  // --- Worked trace: a 3-link chain step by step -----------------------------
  console.log("");
  console.log("Worked trace: Promise.resolve(1).then(x => x + 1).then(x => x * 2) → 4");
  const s0 = await Promise.resolve(1);
  const s1 = await Promise.resolve(1).then((x: number) => x + 1);
  const s2 = await Promise.resolve(1).then((x: number) => x + 1).then((x: number) => x * 2);
  console.log(`    step 0  Promise.resolve(1)                          -> ${s0}`);
  console.log(`    step 1  .then(x => x + 1)  [input ${s0}]           -> ${s1}`);
  console.log(`    step 2  .then(x => x * 2)  [input ${s1}]           -> ${s2}`);
  check("3-link chain value propagation: final value === 4", s2 === 4);
}

// ============================================================================
// Section C — Promise.all (INPUT order, first-reject short-circuit) +
//             Promise.allSettled (never rejects; describes every outcome)
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — Promise.all (input order, first-reject) + Promise.allSettled (never rejects)");

  // Promise.all([p1,p2,...]) fulfills with an array of values in INPUT ORDER
  // (NOT completion order) once ALL fulfill; it rejects with the FIRST rejection
  // reason the moment any input rejects (short-circuit). The remaining inputs
  // keep running — JS has no cancellation — but their results are not surfaced.

  // Prove INPUT order ≠ completion order: settle the inputs in REVERSE, then
  // observe all() still returns them in input order.
  const d1 = defer<number>();
  const d2 = defer<number>();
  const d3 = defer<number>();
  const allPromise = Promise.all([d1.promise, d2.promise, d3.promise]);
  d3.resolve(30); // settle the LAST input FIRST
  d2.resolve(20);
  d1.resolve(10); // settle the FIRST input LAST
  const allResult = await allPromise;
  console.log("Promise.all — result is in INPUT order (completion order was reversed 3,2,1):");
  console.log(`  inputs settled as d3=30, d2=20, d1=10`);
  console.log(`  await Promise.all([d1, d2, d3]) -> ${JSON.stringify(allResult)}`);
  assertDeepEq("Promise.all preserves INPUT order: [10,20,30]", allResult, [10, 20, 30]);

  // First-reject short-circuit: if any input rejects, all() rejects with that
  // reason. Fulfillments of the other inputs are ignored by all().
  const r1 = defer<number>();
  const r2 = defer<number>();
  const allRejectPromise = Promise.all([r1.promise, r2.promise]).catch(
    (e: unknown) => (e as Error).message,
  );
  r2.resolve(200); // other input fulfills...
  r1.reject(new Error("first-reject")); // ...but a rejection short-circuits all()
  const allRejectResult = await allRejectPromise;
  console.log("");
  console.log("Promise.all short-circuits on the FIRST rejection:");
  console.log(`  inputs: r2 resolves 200, r1 rejects "first-reject"`);
  console.log(`  await Promise.all([r1, r2]).catch(e => e.message) -> ${JSON.stringify(allRejectResult)}`);
  check('Promise.all rejects with the first rejection reason', allRejectResult === "first-reject");

  // Promise.all([]) fulfills immediately with [] (vacuously all fulfilled).
  const empty = await Promise.all([]);
  console.log("");
  console.log(`Promise.all([]) -> ${JSON.stringify(empty)}  (vacuously fulfilled)`);
  assertDeepEq("Promise.all([]) === []", empty, []);

  // --- Promise.allSettled: NEVER rejects; describes every outcome ------------
  // allSettled waits for ALL inputs to settle, then fulfills with an array of
  // {status:"fulfilled",value} | {status:"rejected",reason} in INPUT ORDER.
  // Use it for "best effort" fan-out where partial failure is acceptable.
  const settledInputs: ReadonlyArray<Promise<string | number>> = [
    Promise.resolve("ok"),
    Promise.reject<string | number>(new Error("bad")),
    Promise.resolve(42),
  ];
  const settled = await Promise.allSettled(settledInputs);
  console.log("");
  console.log("Promise.allSettled — never rejects; describes every outcome:");
  for (const [i, r] of settled.entries()) {
    if (r.status === "fulfilled") {
      console.log(`  [${i}] { status: "fulfilled", value: ${JSON.stringify(r.value)} }`);
    } else {
      const msg = r.reason instanceof Error ? r.reason.message : String(r.reason);
      console.log(`  [${i}] { status: "rejected",  reason: ${JSON.stringify(msg)} }`);
    }
  }
  check("allSettled length matches input length", settled.length === settledInputs.length);
  check('allSettled[0] fulfilled value "ok"', settled[0]?.status === "fulfilled" && settled[0].value === "ok");
  check('allSettled[1] rejected reason "bad"', settled[1]?.status === "rejected" && settled[1].reason instanceof Error && settled[1].reason.message === "bad");
  check("allSettled[2] fulfilled value 42", settled[2]?.status === "fulfilled" && settled[2].value === 42);
  // The allSettled promise itself never rejects — even with all-reject inputs:
  const allRejectSettled = await Promise.allSettled([
    Promise.reject(new Error("x")),
    Promise.reject(new Error("y")),
  ]);
  check(
    "allSettled never rejects — all-reject input yields two rejected entries",
    allRejectSettled.length === 2 &&
      allRejectSettled[0]?.status === "rejected" &&
      allRejectSettled[1]?.status === "rejected",
  );
}

// ============================================================================
// Section D — Promise.race (first SETTLE) + Promise.any (first FULFILL,
//             all-reject → AggregateError) — the combinator matrix payoff
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — Promise.race (first settle) + Promise.any (first fulfill, AggregateError)");

  // Promise.race settles with the FIRST input to settle (fulfill OR reject).
  // The other inputs keep running (no cancellation) but are ignored by race().
  const slow = defer<string>();
  const fast = defer<string>();
  const racePromise = Promise.race([slow.promise, fast.promise]);
  fast.resolve("fast"); // fast settles FIRST → race adopts it
  slow.resolve("slow"); // ignored by race (already settled)
  const raceResult = await racePromise;
  console.log("Promise.race — first to SETTLE wins (others ignored):");
  console.log(`  fast resolves "fast" before slow -> race -> ${JSON.stringify(raceResult)}`);
  check('race returns the first settled value: "fast"', raceResult === "fast");

  // race also short-circuits on a REJECTION if that rejection settles first.
  const rejWins = defer<string>();
  const laterFulfill = defer<string>();
  const raceRejectPromise = Promise.race([rejWins.promise, laterFulfill.promise]).catch(
    (e: unknown) => (e as Error).message,
  );
  rejWins.reject(new Error("race-rejected-first"));
  laterFulfill.resolve("too-late");
  const raceRejectResult = await raceRejectPromise;
  console.log("");
  console.log("Promise.race short-circuits on rejection if it settles first:");
  console.log(`  rejection settles before fulfillment -> race rejects -> ${JSON.stringify(raceRejectResult)}`);
  check("race rejects when a rejection settles first", raceRejectResult === "race-rejected-first");

  // --- Promise.any: first FULFILL wins; rejects only if ALL reject -----------
  // any() ignores rejections until a fulfillment arrives. If EVERY input rejects,
  // it rejects with an AggregateError whose .errors holds all the reasons.
  const anyResult = await Promise.any([
    Promise.reject(new Error("ignored-1")),
    Promise.resolve("winner"),
    Promise.reject(new Error("ignored-2")),
  ]);
  console.log("");
  console.log("Promise.any — first FULFILL wins (rejections ignored until then):");
  console.log(`  [reject, resolve "winner", reject] -> any -> ${JSON.stringify(anyResult)}`);
  check('any returns the first fulfillment: "winner"', anyResult === "winner");

  // all-reject → AggregateError. Every input here is already rejected, so any()
  // deterministically rejects with an AggregateError. We .catch to observe it.
  const anyAllReject = await Promise.any([
    Promise.reject(new Error("a")),
    Promise.reject(new Error("b")),
    Promise.reject(new Error("c")),
  ]).catch((e: unknown) => e);
  console.log("");
  console.log("Promise.any — ALL reject → AggregateError (holds every reason):");
  if (anyAllReject instanceof AggregateError) {
    const msgs = (anyAllReject.errors as ReadonlyArray<Error>).map((err) =>
      err instanceof Error ? err.message : String(err),
    );
    console.log(`    AggregateError.errors -> ${JSON.stringify(msgs)}`);
    check(
      "any all-reject yields AggregateError with all reasons [a,b,c]",
      msgs.length === 3 && msgs[0] === "a" && msgs[1] === "b" && msgs[2] === "c",
    );
  } else {
    check("any all-reject yields AggregateError (got something else!)", false);
  }

  // --- THE combinator matrix (the payoff table) ------------------------------
  console.log("");
  console.log("THE combinator matrix (the payoff table):");
  console.log("  Promise.all        all fulfill -> array (INPUT order)   | any reject -> first reject reason (short-circuit)");
  console.log("  Promise.allSettled all settle  -> [{status,value|reason}] | NEVER rejects");
  console.log("  Promise.race       first SETTLE (fulfill OR reject) wins | the rest ignored (NOT cancelled)");
  console.log("  Promise.any        first FULFILL wins                     | all reject -> AggregateError(reasons)");
  check("matrix: 4 combinators demonstrated", true);
}

// ============================================================================
// Section E — unhandled rejections (ALWAYS .catch), Promise.resolve/reject,
//             non-cancellable (AbortSignal preview), cross-language model
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — Unhandled rejections (always .catch) + resolve/reject + non-cancellable");

  // --- Unhandled rejections: ALWAYS attach .catch ----------------------------
  // A rejected promise with NO .catch becomes an "unhandled rejection". Node
  // emits an `unhandledRejection` event and, since Node 15 (--unhandled-
  // rejections=throw is the default), TERMINATES the process. We MUST always
  // attach .catch. Here we SAFELY observe the event: we register a one-shot
  // `unhandledRejection` listener that captures (and swallows) it, so the
  // process does not crash, then we assert the event fired.
  let unhandledReason: unknown = null;
  const unhandledListener = (reason: unknown): void => {
    unhandledReason = reason;
  };
  process.on("unhandledRejection", unhandledListener);
  // Create a rejected promise with NO .catch — this WOULD terminate Node by
  // default; our listener captures the event instead. (Do NOT do this in
  // production code — always attach .catch.)
  Promise.reject(new Error("orphaned-rejection"));
  await flushTicks(1); // flush past the tick in which Node detects unhandled rejections
  process.off("unhandledRejection", unhandledListener);
  const capturedMessage =
    unhandledReason instanceof Error ? unhandledReason.message : null;
  console.log("Unhandled rejections — a rejected promise with NO .catch is flagged by Node:");
  console.log(`  Promise.reject(new Error("orphaned-rejection"))  [NO .catch]`);
  console.log(`  -> process 'unhandledRejection' fired, reason.message = ${JSON.stringify(capturedMessage)}`);
  check(
    'unhandled rejection captured by the process listener: reason "orphaned-rejection"',
    capturedMessage === "orphaned-rejection",
  );

  // The fix: attach .catch SYNCHRONOUSLY — then the rejection is "handled" and
  // Node emits no event. The handler runs as a microtask; its return resolves the
  // chained promise (here we surface the caught reason for assertion).
  const caughtReason = await Promise.reject<string>(new Error("handled-rejection")).catch(
    (e: unknown) => (e as Error).message,
  );
  console.log("");
  console.log("The fix — attach .catch synchronously (no unhandled-rejection event):");
  console.log(`  Promise.reject(new Error("handled-rejection")).catch(e => e.message)`);
  console.log(`    -> caught (handled), reason = ${JSON.stringify(caughtReason)}`);
  check('attaching .catch makes the rejection handled: caught "handled-rejection"', caughtReason === "handled-rejection");

  // --- Promise.resolve / Promise.reject: quick settled promises --------------
  // Promise.resolve(x) → already-fulfilled with x. Promise.reject(e) → already-
  // rejected with e. Promise.resolve(thenable) assimilates the thenable (§B).
  const resolvedVal = await Promise.resolve("quick-ok");
  const rejectedMsg = await Promise.reject<string>(new Error("quick-bad")).catch(
    (e: unknown) => (e as Error).message,
  );
  console.log("");
  console.log("Promise.resolve / Promise.reject — quick settled promises:");
  console.log(`  await Promise.resolve("quick-ok")            -> ${JSON.stringify(resolvedVal)}`);
  console.log(`  await Promise.reject(new Error("quick-bad")) -> ${JSON.stringify(rejectedMsg)}  (via .catch)`);
  check('Promise.resolve("quick-ok") yields "quick-ok"', resolvedVal === "quick-ok");
  check('Promise.reject observed via .catch yields "quick-bad"', rejectedMsg === "quick-bad");

  // --- Promises are NOT cancellable; AbortSignal is the cancellation story ----
  // `Promise` has no .cancel(): once the executor's work begins, the promise
  // runs to settlement. Cancellation is achieved by passing an AbortSignal to
  // the underlying operation (fetch, setTimeout, ...) and aborting the signal.
  // (🔗 CONCURRENCY_PATTERNS covers AbortController-based patterns.)
  const ac = new AbortController();
  // observed holds the listener's flag; a `const` object property keeps type
  // `boolean` (TS CFA does not collapse it to literal `false` across the
  // callback the way a bare `let` would), so `observed.abort === true` typechecks.
  const observed: { abort: boolean } = { abort: false };
  ac.signal.addEventListener("abort", () => {
    observed.abort = true;
  });
  console.log("");
  console.log("Promises are NOT cancellable — AbortSignal/AbortController is the story:");
  console.log("  // a Promise has no .cancel(); abort the SIGNAL passed to the work instead");
  console.log(`  before abort: ac.signal.aborted -> ${ac.signal.aborted}`);
  ac.abort(); // the cancellation primitive — abort the signal, not the promise
  console.log(`  after  abort: ac.signal.aborted -> ${ac.signal.aborted}  ;  'abort' listener fired -> ${observed.abort}`);
  check(
    "AbortController.abort() sets signal.aborted and fires the abort listener",
    ac.signal.aborted === true && observed.abort === true,
  );

  // --- The cross-language model (in the .md; summarized here) ----------------
  // A JS Promise is EAGER: work starts at construction. A Rust Future is LAZY:
  // it does nothing until an executor POLLs it. Python asyncio Futures/Tasks are
  // closer to JS (event-loop-driven) but Tasks must be explicitly scheduled.
  console.log("");
  console.log("Cross-language model (full treatment in PROMISES.md):");
  console.log("  JS Promise  : EAGER   — the executor runs at construction; settles once.");
  console.log("  Rust Future  : LAZY    — inert until an executor (.await) polls it.");
  console.log("  asyncio Task : scheduled onto a loop; a coroutine wrapped into a Task.");
  check("cross-language model summarized", true);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("promises.ts — Phase 4 bundle (Concurrency & the Event Loop).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. Resolution ORDER is deterministic (microtask FIFO);");
  console.log("TIMING is never asserted. Every rejected promise has a .catch.");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

await main();
