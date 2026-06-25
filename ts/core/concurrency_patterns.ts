// concurrency_patterns.ts — Phase 4 bundle.
//
// GOAL (one line): show, by printing every value, the async CONTROL primitives
// JS uses to coordinate work over the single-threaded event loop — a bounded
// concurrency POOL (semaphore), AbortController/AbortSignal CANCELLATION (the JS
// analog of Go's context.Context), EventEmitter fan-out, an async QUEUE, an
// async MUTEX, and RETRY/backoff — all built on top of promises (🔗 PROMISES),
// all result-deterministic.
//
// This is the GROUND TRUTH for CONCURRENCY_PATTERNS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it goes DEEPER on than PROMISES):
// PROMISES (P4) showed that a Promise is an async VALUE — a one-way state machine
// that settles once and propagates through .then/.catch. THIS bundle is about
// async CONTROL: limiting how many promises run at once, propagating
// CANCELLATION across a fan-out of promises, broadcasting values through
// EventEmitter, and serializing async SECTIONS. The deep points this bundle pins:
//   - a concurrency POOL `limit(n)` wraps Promise-returning fns so at most `n`
//     run concurrently — bounded parallelism vs unbounded `Promise.all`. We
//     build it from scratch (the p-limit pattern) and assert max-in-flight;
//   - AbortController/AbortSignal is the cancellation PRIMITIVE: `ac.abort()`
//     sets signal.aborted and fires 'abort' listeners. Observing ops REJECT
//     when their signal aborts. AbortSignal.any([s1,s2]) (Node 20+) aborts when
//     ANY input aborts; AbortSignal.timeout(ms) auto-aborts after a delay;
//   - EventEmitter dispatches listeners SYNCHRONUSLY; a throw in a listener
//     propagates out of emit() and skips the remaining listeners. Forgetting
//     removeListener leaks the closure + its captured refs (🔗 GARBAGE_COLLECTION);
//   - an AsyncQueue (push + async next()) is the JS analog of Go channels / Rust
//     mpsc; an async mutex serializes async SECTIONS (JS is single-threaded so a
//     true mutex is rare, but a mutex over async work is real — p-mutex);
//   - retry/backoff is an async loop with a delay + an attempt cap; we assert a
//     fixed retry count succeeds.
//
// THE CROSS-LANGUAGE HEADLINE: AbortController/AbortSignal is the JS analog of
// Go's `context.Context` — but Go propagates cancellation down a PARENT→CHILD
// TREE (ctx, cancel := context.WithCancel(parent)), while JS broadcasts ONE
// signal to many ops with no built-in parent/child structure. AbortSignal.any
// (Node 20+) composes signals the way context.WithCancel nests them. See
// ../go/CONTEXT.md for the Go side of the analogy.
//
// DETERMINISM (THE key caveat for this bundle, per HOW_TO_RESEARCH §4.2 rule 4):
// every async op below is built on setTimeout/Promise, whose RESOLUTION ORDER is
// deterministic (microtask FIFO per spec; macrotask FIFO per queue). We assert
// result SETS, result ORDER (input order via Promise.all; sort where parallel
// output order could drift), and INVARIANTS (max-in-flight, signal.aborted,
// FIFO queue order). We NEVER assert wall-clock TIMING — every delay is 0ms
// (just a yield) except AbortSignal.timeout(1) which we always await to firing.
// Every promise settles, every listener is removed, every held timer is cleared
// before main returns, so the process exits deterministically with no pending
// handles.
//
// Run:
//     pnpm exec tsx concurrency_patterns.ts   (or: just run concurrency_patterns)

import { EventEmitter } from "node:events";

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

// assertDeepEq compares actual vs expected via JSON (stable for our arrays/
// objects) and prints a uniform [check] ... OK line. Throws with a diff on
// mismatch.
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

// yield0 schedules a 0-ms macrotask and resolves after it runs. The delay is
// zero — we use it only to drive the macrotask queue one tick forward so all
// pending setTimeout(0) callbacks and promise microtasks drain. We never assert
// the (zero) duration; we only assert RESULT/order invariants.
function yield0(): Promise<void> {
  return new Promise<void>((resolve) => setTimeout(resolve, 0));
}

// flushTicks drives the event loop `count` macrotask ticks forward so all
// pending setTimeout(0)/promise work settles. Used before asserting state that
// changes inside a queued callback.
function flushTicks(count: number): Promise<void> {
  let p: Promise<void> = Promise.resolve();
  for (let i = 0; i < count; i++) {
    p = p.then(() => yield0());
  }
  return p;
}

// ============================================================================
// Section A — Concurrency pool / semaphore: limit(n) = bounded parallelism
// ============================================================================

// limit(n) returns a mapper that runs Promise-returning fns with at most `n`
// CONCURRENTLY in flight. Built from scratch (the p-limit pattern): a queue of
// pending jobs + an `active` counter. When a job resolves/rejects, it decrements
// `active` and pulls the next job. No third-party dep — stdlib-first (§4.2 #9).
function limit(n: number): <T>(fn: () => Promise<T>) => Promise<T> {
  let active = 0;
  const waiting: Array<() => void> = [];
  const drain = (): void => {
    while (active < n) {
      const job = waiting.shift();
      if (job === undefined) break;
      active++;
      job();
    }
  };
  return function run<T>(fn: () => Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const start = (): void => {
        fn().then(
          (v: T) => {
            active--;
            resolve(v);
            drain();
          },
          (e: unknown) => {
            active--;
            reject(e);
            drain();
          },
        );
      };
      waiting.push(start);
      drain();
    });
  };
}

async function sectionA(): Promise<void> {
  sectionBanner("A — Concurrency pool / semaphore: limit(n) = bounded parallelism");

  // A tracker that records the high-water mark of CONCURRENT in-flight tasks.
  // Each task bumps `now` on entry and decrements on exit; `max` is the peak.
  const tracker = { now: 0, max: 0 };
  const makeTask = (id: number): (() => Promise<number>) => {
    return (): Promise<number> =>
      new Promise<number>((resolve) => {
        tracker.now++;
        if (tracker.now > tracker.max) tracker.max = tracker.now;
        // 0-ms delay: the work is "one macrotask" (setTimeout 0). The duration
        // is not asserted; only the concurrency INVARIANT (max-in-flight) is.
        setTimeout(() => {
          tracker.now--;
          resolve(id);
        }, 0);
      });
  };

  // --- UNBOUNDED: bare Promise.all fires everything at once ----------------
  // Five tasks with no limiter → all 5 enter their setTimeout(0) before any
  // resolves → max-in-flight === 5. This is the "thundering herd" the pool
  // exists to prevent (e.g. 5 simultaneous DB connections / fetches).
  tracker.now = 0;
  tracker.max = 0;
  const ids = [1, 2, 3, 4, 5];
  const unbounded = await Promise.all(ids.map((id) => makeTask(id)()));
  console.log("UNBOUNDED — bare Promise.all over 5 tasks (no limiter):");
  console.log(`  await Promise.all([t1..t5])         -> ${JSON.stringify(unbounded)}`);
  console.log(`  max-in-flight                       -> ${tracker.max}   (all 5 fired at once)`);
  check("unbounded Promise.all: max-in-flight === 5", tracker.max === 5);
  assertDeepEq("unbounded Promise.all result (input order) [1,2,3,4,5]", unbounded, [1, 2, 3, 4, 5]);

  // --- BOUNDED: limit(2) caps concurrency at 2 -----------------------------
  // The same 5 tasks through `limit(2)`: only 2 enter their setTimeout(0) at a
  // time; as each resolves, the pool pulls the next. max-in-flight === 2. THE
  // payoff: the SAME result set with bounded resource use.
  tracker.now = 0;
  tracker.max = 0;
  const runBounded = limit(2);
  const bounded = await Promise.all(ids.map((id) => runBounded(makeTask(id))));
  console.log("");
  console.log("BOUNDED — same 5 tasks through limit(2):");
  console.log(`  await Promise.all(ids.map(id => limit2(makeTask(id)))) -> ${JSON.stringify(bounded)}`);
  console.log(`  max-in-flight                       -> ${tracker.max}   (capped at 2)`);
  check("limit(2) bounds concurrency: max-in-flight === 2", tracker.max === 2);
  assertDeepEq("limit(2) result set (input order) [1,2,3,4,5]", bounded, [1, 2, 3, 4, 5]);

  // --- limit(1) === serial execution ---------------------------------------
  // A pool of size 1 is a serial queue: tasks run strictly one at a time, in
  // submission order. (This is the degenerate case — equivalent to a for-await
  // loop, but composes with Promise.all the same way.)
  tracker.now = 0;
  tracker.max = 0;
  const runOne = limit(1);
  const serial = await Promise.all(ids.map((id) => runOne(makeTask(id))));
  console.log("");
  console.log("limit(1) === serial execution (degenerate pool of size 1):");
  console.log(`  await Promise.all(ids.map(id => limit1(makeTask(id)))) -> ${JSON.stringify(serial)}`);
  console.log(`  max-in-flight                       -> ${tracker.max}`);
  check("limit(1) serializes: max-in-flight === 1", tracker.max === 1);
  assertDeepEq("limit(1) result set (input order) [1,2,3,4,5]", serial, [1, 2, 3, 4, 5]);

  // --- THE takeaway --------------------------------------------------------
  console.log("");
  console.log("THE takeaway: limit(n) bounds CONCURRENCY without changing the RESULT set.");
  console.log("  Promise.all  = unbounded fan-out (fires everything at once)");
  console.log("  limit(n) + Promise.all = bounded fan-out (at most n in flight; same results)");
  check("pool/semaphore demonstrated (unbounded, limit(2), limit(1))", true);
}

// ============================================================================
// Section B — AbortController / AbortSignal: cancellation + propagation +
//             AbortSignal.any + AbortSignal.timeout (THE Go-context analog)
// ============================================================================

// cancellableOp is the canonical "abortable async work" pattern: register an
// 'abort' listener on the signal; do work via setTimeout(0); whichever fires
// first wins. If the signal is ALREADY aborted (a common case), reject
// synchronously. We MUST clearTimeout + removeEventListener on the other path
// so no handle/listener leaks (deterministic exit, §4.2).
function cancellableOp(signal: AbortSignal, id: number): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    // `handle` is declared with `let` (not `const`) so onAbort can read it
    // safely even on the pre-aborted path, where the timer is never started.
    let handle: ReturnType<typeof setTimeout> | undefined;
    const cleanup = (): void => {
      if (handle !== undefined) clearTimeout(handle);
      signal.removeEventListener("abort", onAbort);
    };
    const onAbort = (): void => {
      cleanup();
      reject(signal.reason);
    };
    const onDone = (): void => {
      cleanup();
      resolve(`op${id}:done`);
    };
    if (signal.aborted) {
      onAbort();
      return;
    }
    signal.addEventListener("abort", onAbort);
    handle = setTimeout(onDone, 0);
  });
}

async function sectionB(): Promise<void> {
  sectionBanner("B — AbortController/AbortSignal + propagation + any + timeout");

  // --- The primitive: AbortController.abort() flips signal.aborted ----------
  const ac = new AbortController();
  check("new AbortController().signal.aborted === false", ac.signal.aborted === false);
  ac.abort(new Error("user-cancelled"));
  check("after ac.abort(reason): signal.aborted === true", ac.signal.aborted === true);
  // The reason is preserved on the signal. Cast reason through `unknown` (the
  // DOM lib types it loosely); narrow with instanceof for a typed message.
  const reason = ac.signal.reason as unknown;
  check(
    "abort reason is preserved on signal.reason",
    reason instanceof Error && reason.message === "user-cancelled",
  );

  // ac.abort() with NO argument installs a default AbortError reason.
  const acDefault = new AbortController();
  acDefault.abort();
  const defaultReason = acDefault.signal.reason as unknown;
  check(
    'ac.abort() with no arg → default reason.name === "AbortError"',
    defaultReason instanceof Error && defaultReason.name === "AbortError",
  );

  // --- An observing op rejects when its signal aborts ----------------------
  // Path 1: signal aborts AFTER the op starts → the op's 'abort' listener
  // rejects it. We start the op, abort on the next tick, await.
  const acLate = new AbortController();
  const latePromise = cancellableOp(acLate.signal, 1).catch(
    (e: unknown) => `caught:${(e as Error).message}`,
  );
  acLate.abort(new Error("late-cancelled"));
  const lateResult = await latePromise;
  console.log("");
  console.log("Op rejects when its signal aborts (listener fires):");
  console.log(`  cancellableOp(ac.signal, 1); ac.abort(new Error("late-cancelled"))`);
  console.log(`  -> ${JSON.stringify(lateResult)}  (op rejected, never resolved "done")`);
  check('observing op rejects on late abort: "caught:late-cancelled"', lateResult === "caught:late-cancelled");

  // Path 2: signal is ALREADY aborted when the op starts → synchronous reject.
  const acPre = new AbortController();
  acPre.abort(new Error("pre-cancelled"));
  const preResult = await cancellableOp(acPre.signal, 2).catch(
    (e: unknown) => `caught:${(e as Error).message}`,
  );
  console.log("");
  console.log("Op rejects SYNCHRONOUSLY when given an already-aborted signal:");
  console.log(`  ac.abort(...); cancellableOp(ac.signal, 2) -> ${JSON.stringify(preResult)}`);
  check('pre-aborted signal → op rejects synchronously: "caught:pre-cancelled"', preResult === "caught:pre-cancelled");

  // Path 3: signal never aborts → op resolves normally.
  const acOk = new AbortController();
  const okResult = await cancellableOp(acOk.signal, 3);
  console.log("");
  console.log("Op resolves normally when the signal never aborts:");
  console.log(`  cancellableOp(ac.signal, 3)            -> ${JSON.stringify(okResult)}`);
  check('op resolves when not aborted: "op3:done"', okResult === "op3:done");
  // Cleanup: abort the unused controller so no listener/timer lingers.
  acOk.abort();

  // --- Cancellation PROPAGATION: one signal → many ops ---------------------
  // THE Go-context analog: a single abort cascades to every op sharing the
  // signal. We fan out 3 ops on ONE controller, abort once, observe all 3
  // reject with the same reason. (Go does this with parent→child ctx tree;
  // JS does it with one signal referenced by many ops — same semantics,
  // flatter structure.)
  const acFan = new AbortController();
  const fanOps = [1, 2, 3].map((id) =>
    cancellableOp(acFan.signal, id).catch((e: unknown) => `op${id}:${(e as Error).message}`),
  );
  acFan.abort(new Error("parent-cancelled"));
  const fanResults = await Promise.all(fanOps);
  console.log("");
  console.log("Cancellation PROPAGATION — one abort cascades to many ops (the Go-context analog):");
  console.log(`  3 ops share one signal; ac.abort(new Error("parent-cancelled"))`);
  console.log(`  results (input order) -> ${JSON.stringify(fanResults)}`);
  assertDeepEq(
    "one abort rejects all 3 sharing ops with the same reason",
    fanResults,
    ["op1:parent-cancelled", "op2:parent-cancelled", "op3:parent-cancelled"],
  );

  // --- AbortSignal.any([s1,s2]) (Node 20+) — aborts when ANY input aborts ---
  // The combinator: combine many signals into one that aborts as soon as ANY
  // input aborts, with that input's reason. Composes cancellation the way Go's
  // context.WithCancel nests ctx trees.
  const c1 = new AbortController();
  const c2 = new AbortController();
  const combined = AbortSignal.any([c1.signal, c2.signal]);
  check("AbortSignal.any: combined.aborted === false before any input aborts", combined.aborted === false);
  c1.abort(new Error("c1-cancelled"));
  check("AbortSignal.any: combined.aborted === true after c1.abort()", combined.aborted === true);
  check(
    "AbortSignal.any: combined.reason === c1's reason (first-to-abort wins)",
    combined.reason === c1.signal.reason,
  );
  // c2 never needs to abort — the combined signal is already settled by c1.

  // --- AbortSignal.timeout(ms) — auto-abort after a delay (🔗 TIMERS_IO) ----
  // A signal that aborts itself after `ms`. The reason is a TimeoutError. We
  // must AWAIT its firing (the internal timer keeps the loop alive until it
  // fires) — flushTicks(1) drains past the 1ms timer.
  const timed = AbortSignal.timeout(1);
  check("AbortSignal.timeout(1): not aborted at construction", timed.aborted === false);
  await flushTicks(1);
  const timedReason = timed.reason as unknown;
  check("AbortSignal.timeout(1): aborted === true after firing", timed.aborted === true);
  check(
    'AbortSignal.timeout reason.name === "TimeoutError"',
    timedReason instanceof Error && timedReason.name === "TimeoutError",
  );
  console.log("");
  console.log("AbortSignal.any([s1,s2]) (Node 20+) + AbortSignal.timeout(ms):");
  console.log('  AbortSignal.any([s1,s2]) -> aborts when ANY input aborts (first-to-abort reason wins)');
  console.log("  AbortSignal.timeout(ms) -> auto-aborts after ms; reason.name === \"TimeoutError\"");
  check("AbortSignal.any + AbortSignal.timeout demonstrated", true);
}

// ============================================================================
// Section C — EventEmitter: emit/on/once/off, SYNCHRONOUS dispatch,
//             throw-in-listener, and the listener-leak trap
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — EventEmitter: emit/on/once/off, sync dispatch, throw, leak trap");

  // --- emit/on: synchronous fan-out ----------------------------------------
  const ee = new EventEmitter();
  const received: string[] = [];
  ee.on("event", (x: string) => received.push(x));
  ee.emit("event", "a");
  ee.emit("event", "b");
  console.log("emit/on — emit dispatches SYNCHRONOUSLY to every registered listener:");
  console.log(`  on("event", x => received.push(x)); emit("event","a"); emit("event","b");`);
  console.log(`  received -> ${JSON.stringify(received)}`);
  assertDeepEq('emit fires on() listeners: received === ["a","b"]', received, ["a", "b"]);

  // --- SYNCHRONOUS dispatch: emit returns BEFORE the next line -------------
  // The trace proves the listener ran DURING emit() — `after-emit` is pushed
  // only after the listener already pushed "sync" into `received`.
  const syncTrace: string[] = [];
  const syncReceived: string[] = [];
  const eeSync = new EventEmitter();
  eeSync.on("e", (x: string) => {
    syncReceived.push(x);
    syncTrace.push(`listener-ran:${x}`);
  });
  syncTrace.push("before-emit");
  eeSync.emit("e", "sync");
  syncTrace.push("after-emit");
  console.log("");
  console.log("emit() is SYNCHRONOUS — the listener runs DURING emit(), before the next line:");
  console.log(`  trace    -> ${JSON.stringify(syncTrace)}`);
  console.log(`  received -> ${JSON.stringify(syncReceived)}`);
  assertDeepEq(
    'sync dispatch: listener runs during emit() (["before-emit","listener-ran:sync","after-emit"])',
    syncTrace,
    ["before-emit", "listener-ran:sync", "after-emit"],
  );

  // --- once: fires exactly once, then auto-removes -------------------------
  const eeOnce = new EventEmitter();
  let onceCount = 0;
  eeOnce.once("oneshot", () => onceCount++);
  eeOnce.emit("oneshot");
  eeOnce.emit("oneshot");
  check("once() fires exactly once across two emits", onceCount === 1);
  check("once() auto-removes the listener (listenerCount === 0 after firing)", eeOnce.listenerCount("oneshot") === 0);

  // --- off / removeListener: removes a specific listener -------------------
  const eeOff = new EventEmitter();
  let offCount = 0;
  const handler = (): void => {
    offCount++;
  };
  eeOff.on("e", handler);
  eeOff.emit("e");
  eeOff.off("e", handler); // `off` is an alias for `removeListener`
  eeOff.emit("e");
  check("off() removes the listener: only the first emit fires (count === 1)", offCount === 1);
  check("off === removeListener (alias)", eeOff.off === eeOff.removeListener);

  // --- removeAllListeners: clears all listeners for an event ---------------
  const eeAll = new EventEmitter();
  let allCount = 0;
  eeAll.on("e", () => allCount++);
  eeAll.on("e", () => allCount++);
  check("two listeners registered on 'e': listenerCount === 2", eeAll.listenerCount("e") === 2);
  eeAll.emit("e");
  eeAll.removeAllListeners("e");
  eeAll.emit("e");
  check("removeAllListeners('e') clears them: post-emit count stays at 2", allCount === 2);
  check("...listenerCount('e') === 0 after removeAllListeners", eeAll.listenerCount("e") === 0);

  // --- THROW in a listener: propagates SYNCHRONOUSLY out of emit() ---------
  // A listener that throws halts emit(): the throw propagates up to the caller
  // of emit(), and listeners registered AFTER the thrower are NOT called. We
  // wrap emit() in try/catch to observe the throw without crashing the process.
  const eeThrow = new EventEmitter();
  let secondCalled = false;
  eeThrow.on("boom", () => {
    throw new Error("listener-threw");
  });
  eeThrow.on("boom", () => {
    secondCalled = true;
  });
  let thrown: Error | null = null;
  try {
    eeThrow.emit("boom");
  } catch (e) {
    thrown = e as Error;
  }
  console.log("");
  console.log("THROW in a listener — propagates SYNCHRONOUSLY out of emit(); rest are skipped:");
  console.log(`  on("boom", () => { throw new Error("listener-threw") }); on("boom", () => second++)`);
  console.log(`  try { emit("boom") } catch -> ${thrown ? JSON.stringify(thrown.message) : "null"}`);
  console.log(`  second listener called -> ${secondCalled}`);
  check(
    'throw in listener propagates from emit(): caught "listener-threw"',
    thrown !== null && thrown.message === "listener-threw",
  );
  check("...subsequent listeners NOT called after a throw", secondCalled === false);

  // --- THE listener-leak trap (🔗 GARBAGE_COLLECTION) ----------------------
  // Forgetting removeListener keeps the listener — and the CLOSURE it captures
  // — alive for as long as the emitter lives. In a long-lived emitter (a
  // socket, a stream, a global bus) this is a classic leak: each "register on
  // request, forget to unregister" piles up listeners + their captured refs.
  // The symptom is observable here WITHOUT GC: the listener keeps FIRING on
  // later emits. The fix: removeListener, or use addEventListener with the
  // AbortSignal `signal` option (abort to unsubscribe — modern idiom).
  const eeLeak = new EventEmitter();
  const leakedBuf: number[] = [];
  const attach = (requestId: number): void => {
    // BUGGY: registers a listener per request, never removes it. Each closure
    // captures `requestId` and the `leakedBuf` array forever.
    eeLeak.on("data", (payload: number) => {
      leakedBuf.push(requestId * 1000 + payload);
    });
  };
  attach(1);
  eeLeak.emit("data", 7); // listener for req 1 fires
  attach(2); // BUG: req 1's listener is STILL attached
  eeLeak.emit("data", 8); // BOTH listeners fire — req 1 sees data meant for req 2
  console.log("");
  console.log("Listener-leak trap — forgetting removeListener keeps the closure firing:");
  console.log('  attach(1); emit("data",7); attach(2); emit("data",8);  // req1 listener NEVER removed');
  console.log(`  leakedBuf -> ${JSON.stringify(leakedBuf)}   (req1 listener fires on req2's data)`);
  check(
    "leak symptom: req1 listener fires on req2's emit (1008 should not be here)",
    leakedBuf.length === 3 && leakedBuf[0] === 1007 && leakedBuf[1] === 1008 && leakedBuf[2] === 2008,
  );
  // The fix (demonstrated): keep the handler ref and removeListener when done.
  const eeFix = new EventEmitter();
  const fixedBuf: number[] = [];
  const attachFixed = (requestId: number): (() => void) => {
    const ondata = (payload: number): void => {
      fixedBuf.push(requestId * 1000 + payload);
    };
    eeFix.on("data", ondata);
    return () => eeFix.off("data", ondata); // return an unsubscribe fn
  };
  const detach1 = attachFixed(1);
  eeFix.emit("data", 7);
  detach1(); // THE fix: remove req 1's listener before req 2 starts
  attachFixed(2);
  eeFix.emit("data", 8);
  console.log(`  FIX: detach1() before attachFixed(2) -> fixedBuf = ${JSON.stringify(fixedBuf)}`);
  assertDeepEq("fix: removeListener isolates requests ([1007, 2008])", fixedBuf, [1007, 2008]);

  // --- Cleanup: remove ALL listeners so no closure retains captured state --
  ee.removeAllListeners();
  eeSync.removeAllListeners();
  eeOnce.removeAllListeners();
  eeOff.removeAllListeners();
  eeAll.removeAllListeners();
  eeThrow.removeAllListeners();
  eeLeak.removeAllListeners();
  eeFix.removeAllListeners();
  check("EventEmitter: emit/on/once/off/removeAllListeners + throw + leak demonstrated", true);
}

// ============================================================================
// Section D — Async queue (producer/consumer) + async mutex (brief)
// ============================================================================

// An AsyncQueue is the JS analog of Go's unbuffered/buffered channel and Rust's
// mpsc: push() enqueues a value; next() awaits the next value in FIFO order.
// Built from a value buffer + a resolver queue (the classic "promise per
// waiting consumer" pattern). Stdlib-only.
class AsyncQueue<T> {
  private buffered: T[] = [];
  private resolvers: Array<(v: T) => void> = [];

  push(value: T): void {
    // If a consumer is already awaiting, hand the value to it; else buffer.
    const resolve = this.resolvers.shift();
    if (resolve !== undefined) {
      resolve(value);
    } else {
      this.buffered.push(value);
    }
  }

  next(): Promise<T> {
    // If a value is already buffered, return it; else queue a resolver.
    const value = this.buffered.shift();
    if (value !== undefined) {
      return Promise.resolve(value);
    }
    return new Promise<T>((resolve) => {
      this.resolvers.push(resolve);
    });
  }

  get pending(): number {
    return this.buffered.length;
  }
}

// An AsyncMutex serializes ASYNC sections. JS is single-threaded so a true
// thread-mutex is unnecessary (no two sync sections ever overlap); but async
// sections (functions that await in the middle) CAN interleave at each await.
// The mutex ensures only one async section is in the critical section at a
// time. Built from a `locked` flag + a waiter queue (the p-mutex pattern).
class AsyncMutex {
  private locked = false;
  private waiters: Array<() => void> = [];

  async run<T>(fn: () => Promise<T>): Promise<T> {
    while (this.locked) {
      await new Promise<void>((resolve) => this.waiters.push(resolve));
    }
    this.locked = true;
    try {
      return await fn();
    } finally {
      this.locked = false;
      const next = this.waiters.shift();
      if (next !== undefined) next();
    }
  }
}

async function sectionD(): Promise<void> {
  sectionBanner("D — Async queue (producer/consumer) + async mutex");

  // --- AsyncQueue FIFO: push BEFORE next() (values buffered) ---------------
  const q1 = new AsyncQueue<string>();
  q1.push("a");
  q1.push("b");
  const n1 = await q1.next();
  const n2 = await q1.next();
  console.log("AsyncQueue FIFO — push() before next() (values buffered):");
  console.log(`  push("a"); push("b"); await next(); await next()`);
  console.log(`  -> ${JSON.stringify(n1)}, ${JSON.stringify(n2)}`);
  check("FIFO: push(a),push(b) → next()=a, next()=b", n1 === "a" && n2 === "b");

  // --- AsyncQueue: next() BEFORE push() (consumer awaits producer) ---------
  // THE channel-like property: a consumer that calls next() before any value is
  // pushed AWAITs (returns a pending promise); when a producer pushes, the
  // pending promise resolves. This is exactly Go's unbuffered channel rendezvous.
  const q2 = new AsyncQueue<string>();
  const awaitedEarly = q2.next(); // pending — no value yet
  q2.push("late"); // producer arrives; pending consumer resolves
  const n3 = await awaitedEarly;
  console.log("");
  console.log("AsyncQueue — next() BEFORE push() (consumer awaits producer):");
  console.log(`  const p = next();   // pending`);
  console.log(`  push("late");       // producer resolves the pending consumer`);
  console.log(`  await p -> ${JSON.stringify(n3)}`);
  check('next() before push() resolves when value arrives: "late"', n3 === "late");

  // --- AsyncQueue: ordering preserved across mixed push/next ---------------
  const q3 = new AsyncQueue<number>();
  q3.push(1);
  q3.push(2);
  const early1 = q3.next(); // 1 (buffered)
  const early2 = q3.next(); // 2 (buffered)
  const early3 = q3.next(); // pending (no value)
  q3.push(3); // resolves early3
  const [r1, r2, r3] = await Promise.all([early1, early2, early3]);
  console.log("");
  console.log("AsyncQueue — mixed push/next preserves FIFO order:");
  console.log(`  push(1); push(2); next(); next(); next(); push(3) -> ${JSON.stringify([r1, r2, r3])}`);
  assertDeepEq("FIFO across mixed push/next: [1,2,3]", [r1, r2, r3], [1, 2, 3]);

  // --- AsyncMutex: serializes async SECTIONS (max-in-section === 1) --------
  // Three async sections try to enter; the mutex lets only one in at a time.
  // Without the mutex, all three would interleave at the `await yield0()` and
  // max-in-section would be 3; WITH it, max-in-section === 1 and the SECTION
  // order is start/end strictly serialized.
  const m = new AsyncMutex();
  let inSection = 0;
  let maxInSection = 0;
  const sectionOrder: string[] = [];
  const ids2 = [1, 2, 3];
  await Promise.all(
    ids2.map((id) =>
      m.run(async () => {
        inSection++;
        if (inSection > maxInSection) maxInSection = inSection;
        sectionOrder.push(`start${id}`);
        await yield0(); // an await inside the critical section
        sectionOrder.push(`end${id}`);
        inSection--;
      }),
    ),
  );
  console.log("");
  console.log("AsyncMutex — serializes async SECTIONS (max-in-section === 1):");
  console.log(`  3 sections via mutex.run(async () => { ... await yield0() ... })`);
  console.log(`  max-in-section -> ${maxInSection}`);
  console.log(`  section order  -> ${JSON.stringify(sectionOrder)}`);
  check("mutex serializes async sections: max-in-section === 1", maxInSection === 1);
  assertDeepEq(
    "mutex section order strictly serialized: [start1,end1,start2,end2,start3,end3]",
    sectionOrder,
    ["start1", "end1", "start2", "end2", "start3", "end3"],
  );

  check("async queue + async mutex demonstrated", true);
}

// ============================================================================
// Section E — Retry / backoff + cross-language model
// ============================================================================

// retry runs `fn` up to `attempts` times. On a rejection it waits `delayMs`
// (fixed backoff — a real impl uses exponential) and tries again. If every
// attempt rejects, it rejects with the LAST error. Built from scratch.
async function retry<T>(fn: () => Promise<T>, attempts: number, delayMs: number): Promise<T> {
  let lastError: unknown;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (e) {
      lastError = e;
      if (i < attempts - 1) {
        await new Promise<void>((resolve) => setTimeout(resolve, delayMs));
      }
    }
  }
  throw lastError;
}

async function sectionE(): Promise<void> {
  sectionBanner("E — Retry / backoff + cross-language model");

  // --- retry: succeeds after N-1 failures (fixed attempt cap) --------------
  // The task fails on attempts 1 and 2, succeeds on attempt 3. retry(fn, 5, 0)
  // tries up to 5 times → returns "ok" on the 3rd. We assert calls === 3.
  let succeedAfter = 2; // succeed once `calls` exceeds this
  let calls = 0;
  const result = await retry(async () => {
    calls++;
    if (calls <= succeedAfter) throw new Error(`fail-${calls}`);
    return "ok";
  }, 5, 0);
  console.log("Retry/backoff — succeeds after 2 failures (3rd attempt), 5-attempt cap:");
  console.log(`  retry(fn, attempts=5, delayMs=0); fn throws on calls 1,2; returns "ok" on call 3`);
  console.log(`  -> result ${JSON.stringify(result)}; total calls = ${calls}`);
  check('retry succeeds on 3rd attempt: result "ok", calls === 3', result === "ok" && calls === 3);

  // --- retry: exhausts the cap → rejects with the LAST error ----------------
  let alwaysCalls = 0;
  const err = await retry(async () => {
    alwaysCalls++;
    throw new Error(`always-${alwaysCalls}`);
  }, 3, 0).catch((e: unknown) => (e as Error).message);
  console.log("");
  console.log("Retry/backoff — exhausts attempt cap → rejects with the LAST error:");
  console.log(`  retry(fnThatAlwaysThrows, attempts=3, delayMs=0)`);
  console.log(`  -> caught ${JSON.stringify(err)}; total calls = ${alwaysCalls}`);
  check(
    'retry rejects with last error after cap: "always-3", calls === 3',
    err === "always-3" && alwaysCalls === 3,
  );

  // --- Cross-language model (full treatment in CONCURRENCY_PATTERNS.md) -----
  // THE headline: AbortController is the JS analog of Go's context.Context.
  // Go propagates cancellation down a PARENT→CHILD tree (WithCancel(parent));
  // JS broadcasts one signal to many ops with no built-in tree. AbortSignal.any
  // (Node 20+) composes signals the way context.WithCancel nests them.
  console.log("");
  console.log("Cross-language model (full treatment in CONCURRENCY_PATTERNS.md):");
  console.log("  JS AbortController : cancellation BROADCAST — one signal → many ops;");
  console.log("                       AbortSignal.any([s1,s2]) composes (Node 20+).");
  console.log("  Go context.Context : cancellation TREE — parent → children propagation;");
  console.log("                       context.WithCancel(parent) nests (⟷ AbortSignal.any).");
  console.log("  Go worker pool     : goroutines + channels; JS: limit(n) + Promise.all.");
  console.log("  Rust tokio mpsc    : bounded multi-producer/single-consumer channel;");
  console.log("                       JS AsyncQueue is the analog (push/next, FIFO).");
  check("cross-language model summarized", true);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("concurrency_patterns.ts — Phase 4 bundle (Concurrency & the Event Loop).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. We assert result SETS/ORDER and invariants (max-in-flight,");
  console.log("signal.aborted, FIFO order) — never wall-clock timing. Every promise");
  console.log("settles, every listener is removed, every held timer is cleared before");
  console.log("main returns, so the process exits deterministically with no handles.");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

await main();
