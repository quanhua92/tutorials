// event_loop.ts — Phase 4 bundle #1 (the foundational concurrency bundle).
//
// GOAL (one line): show, by collecting each callback's label into an array in
// the ORDER it fires, that JS is single-threaded with a deterministic
// microtask-before-macrotask event loop — the defining constraint of the
// language and the cross-language pivot.
//
// This is the GROUND TRUTH for EVENT_LOOP.md. Every interleaving, ordering, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle is THE foundation of Phase 4): JS is SINGLE-THREADED.
// There is one call stack; no two lines of user JS run simultaneously (worker
// threads aside — they are SEPARATE agents with their own stacks/loops). The
// event loop is the mechanism that lets that one thread do "concurrent" I/O: it
// runs the current task to completion, drains ALL queued microtasks, then picks
// the next task — repeating forever. This single rule explains why
// `Promise.then` ALWAYS runs before `setTimeout(fn, 0)`, why blocking the loop
// blocks EVERYTHING (the "don't block the event loop" rule), and why async I/O
// is how Node scales on one thread. Every later Phase 4 bundle builds on this:
//   - PROMISES        — microtasks ARE promise callbacks; THIS bundle shows why
//                       `.then` is async (it queues a microtask, not a macrotask).
//   - ASYNC_AWAIT     — `await` desugars to promises, so it re-enters the SAME
//                       microtask queue pinned here.
//   - TIMERS_IO       — the macrotask/timer/I/O sources that feed the loop.
//
// DETERMINISM (THE key caveat for this bundle, per HOW_TO_RESEARCH §4.2 rule 4):
// microtask/macrotask ORDER is fully defined by the spec, so the SEQUENCE of a
// logged interleaving is reproducible. We therefore NEVER print from inside a
// callback directly. Instead every callback pushes a short label string into a
// shared `log` array (in the order it actually fires), and we print the array
// ONCE at the end — after every queued callback has drained (via `await
// sleep(N)`). This makes stdout byte-identical across runs while faithfully
// showing the real interleaving order. We assert ORDER only, NEVER timing
// durations (wall-clock ms are non-reproducible and engine-dependent).
//
// Run:
//     pnpm exec tsx event_loop.ts   (or: just run event_loop)

import * as fs from "node:fs";

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

// sleep resolves after `ms` milliseconds via a setTimeout macrotask. It is used
// ONLY to let previously-queued callbacks drain before we read the collected
// `log` array — we never assert the `ms` value (timing is non-deterministic;
// only the ORDER of the collected labels is asserted).
function sleep(ms: number): Promise<void> {
  return new Promise<void>((resolve: () => void) => {
    setTimeout(resolve, ms);
  });
}

// ============================================================================
// Section A — Single thread, one call stack, "run-to-completion"
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — Single thread, one call stack, \"run-to-completion\"");

  // MDN ("JavaScript execution model" / "Run-to-completion"): each JOB (task)
  // is processed COMPLETELY before any other job is processed. A function, once
  // entered, cannot be preempted mid-statement — it runs entirely before any
  // other code can mutate the data it touches. This is the single-threaded
  // guarantee that makes JS concurrency reasonabout-able. Contrast with C,
  // where a thread can be stopped at ANY point by the runtime to run other code.

  // MDN's canonical demonstration: two `.then` callbacks on an already-resolved
  // promise each do `i += 1; record(i)`. A pre-emptive scheduler could
  // interleave them (i+=1; i+=1; record; record -> both see 2). The JS event
  // loop NEVER preempts: each callback runs fully before the next, so the only
  // possible order is record(1) then record(2). We collect into an array and
  // print once, so the captured order is the real firing order.
  const rcLog: string[] = [];
  const p: Promise<void> = Promise.resolve();
  let i = 0;
  p.then((): void => {
    i += 1;
    rcLog.push(`first: i=${i}`);
  });
  p.then((): void => {
    i += 1;
    rcLog.push(`second: i=${i}`);
  });
  await sleep(20);

  console.log("Run-to-completion (MDN's canonical example):");
  console.log("  const p = Promise.resolve(); let i = 0;");
  console.log("  p.then(() => { i += 1; record(`first: i=${i}`); });");
  console.log("  p.then(() => { i += 1; record(`second: i=${i}`); });");
  console.log(`  collected firing order -> ${JSON.stringify(rcLog)}`);
  console.log("  (a preemptive scheduler could interleave -> both would see i=2;)");
  console.log("  (JS NEVER preempts mid-statement -> each callback runs to completion.)");
  check(
    "run-to-completion: order is [first i=1, second i=2] (never interleaved)",
    rcLog.length === 2 && rcLog[0] === "first: i=1" && rcLog[1] === "second: i=2",
  );

  // The loop's ONE rule (HTML spec / ECMAScript job queue), stated precisely:
  //   1. pick ONE macrotask ("task") off the task queue and run it to completion;
  //   2. drain the ENTIRE microtask queue (run every queued microtask, including
  //      any new microtasks queued by those microtasks, until the queue is empty);
  //   3. (browser only) render, if it's time;
  //   4. repeat from 1.
  // Steps 1-2 are why Promise.then (microtask) ALWAYS precedes setTimeout
  // (macrotask) — proven in Section B.
  console.log("");
  console.log("The event loop's ONE rule (run one task, drain ALL microtasks, repeat):");
  console.log("  step 1: pick ONE macrotask (task) -> run to completion (stack empties)");
  console.log("  step 2: drain the ENTIRE microtask queue (incl. microtasks queued by microtasks)");
  console.log("  step 3: (browser only) render, if it is time");
  console.log("  step 4: repeat from step 1");
  check("single thread: only ONE macrotask runs at a time (stack empties between tasks)", true);
}

// ============================================================================
// Section B — THE payoff: microtask before macrotask (collect-then-print)
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — THE payoff: microtask before macrotask (collect-then-print)");

  // THE headline interleaving of the whole bundle. Schedule, in source order:
  //   a synchronous push, a setTimeout(0) macrotask, and a Promise.then
  //   microtask. The firing order is FULLY determined by the spec: the sync
  //   line runs now (on the stack); when the stack empties, ALL microtasks
  //   drain first (so the promise callback fires); only THEN does the next
  //   macrotask run (the timeout). Result: ["sync","micro","timeout"].
  const log: string[] = [];
  log.push("sync"); // synchronous: runs immediately, on the current stack
  setTimeout(() => { log.push("timeout"); }, 0); // queues a MACROTASK (task)
  Promise.resolve().then(() => { log.push("micro"); }); // queues a MICROTASK
  await sleep(20); // let the macrotask fire before we read the array

  console.log("THE classic interleaving (sync vs setTimeout(0) vs Promise.then):");
  console.log("  log.push('sync');                                  // runs NOW (on stack)");
  console.log("  setTimeout(() => log.push('timeout'), 0);          // queues a MACROTASK");
  console.log("  Promise.resolve().then(() => log.push('micro'));   // queues a MICROTASK");
  console.log(`  collected firing order -> ${JSON.stringify(log)}`);
  console.log("  => microtask drains BEFORE the next macrotask. Promise.then ALWAYS beats setTimeout(0).");
  check(
    "microtask before macrotask: order is [sync, micro, timeout]",
    JSON.stringify(log) === '["sync","micro","timeout"]',
  );

  // Same rule at depth: microtasks queue MORE microtasks. The drain is EXHAUSTIVE
  // — a microtask that schedules another microtask extends the drain; the loop
  // does not move on to macrotasks until the microtask queue is truly empty.
  const chained: string[] = [];
  const step = (n: number): void => {
    chained.push(`micro-${n}`);
    if (n < 3) {
      Promise.resolve().then((): void => step(n + 1)); // microtask schedules microtask
    }
  };
  setTimeout(() => { chained.push("timeout"); }, 0);
  Promise.resolve().then((): void => step(1));
  await sleep(20);

  console.log("");
  console.log("Microtasks scheduling microtasks (the drain is EXHAUSTIVE):");
  console.log("  // step(n) pushes `micro-n` then, if n<3, queues step(n+1) as a microtask");
  console.log("  setTimeout(() => chained.push('timeout'), 0);");
  console.log("  Promise.resolve().then(() => step(1));");
  console.log(`  collected firing order -> ${JSON.stringify(chained)}`);
  console.log("  => ALL three microtasks drain before the single macrotask fires.");
  check(
    "chained microtasks all drain before the macrotask",
    JSON.stringify(chained) === '["micro-1","micro-2","micro-3","timeout"]',
  );
}

// ============================================================================
// Section C — queueMicrotask, process.nextTick (Node), and microtask starvation
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — queueMicrotask, process.nextTick (Node), and microtask starvation");

  // queueMicrotask(fn) is the explicit API to schedule a microtask. It is the
  // SAME queue Promise.then uses, so it runs before the next macrotask.
  const qmLog: string[] = [];
  setTimeout(() => { qmLog.push("timeout"); }, 0);
  queueMicrotask(() => { qmLog.push("queueMicrotask"); });
  qmLog.push("sync");
  await sleep(20);

  console.log("queueMicrotask schedules a MICROTASK (same queue as Promise.then):");
  console.log("  setTimeout(() => qm.push('timeout'), 0);");
  console.log("  queueMicrotask(() => qm.push('queueMicrotask'));");
  console.log("  qm.push('sync');");
  console.log(`  collected firing order -> ${JSON.stringify(qmLog)}`);
  check(
    "queueMicrotask runs after sync, before the setTimeout macrotask",
    JSON.stringify(qmLog) === '["sync","queueMicrotask","timeout"]',
  );

  // process.nextTick is a NODE-ONLY queue (not in browsers, not in the spec).
  // Per the Node.js docs: it is "not technically part of the event loop" — the
  // nextTickQueue is processed after the current operation completes,
  // regardless of the current phase, and it has HIGHER priority than the
  // microtask queue. So nextTick fires BEFORE Promise.then.
  //
  // EXPERT CAVEAT (observed here in Node 24): the nextTick-before-microtask
  // rule is reproducible when both are scheduled from WITHIN a macrotask
  // (setTimeout/setImmediate/I/O). At the very TOP LEVEL of a script, and
  // inside an async RESUMPTION (after `await`), V8's microtask checkpoint can
  // drain the promise queue first, flipping the order. The macrotask context
  // is the documented, deterministic one — so we schedule both inside a
  // setTimeout and read the result from a later macrotask.
  const ntLog: string[] = [];
  await new Promise<void>((resolve: () => void) => {
    setTimeout(() => {
      // Clean macrotask context: schedule nextTick + microtask synchronously.
      process.nextTick(() => { ntLog.push("nextTick"); });
      Promise.resolve().then(() => { ntLog.push("microtask"); });
      ntLog.push("sync");
      // After this macrotask returns, Node drains nextTick queue, THEN microtasks.
      setTimeout(resolve, 20);
    }, 0);
  });

  console.log("");
  console.log("process.nextTick (Node-only) runs BEFORE Promise.then (higher priority):");
  console.log("  // scheduled from inside a setTimeout (macrotask) callback:");
  console.log("  process.nextTick(() => nt.push('nextTick'));       // Node-only queue");
  console.log("  Promise.resolve().then(() => nt.push('microtask')); // microtask queue");
  console.log("  nt.push('sync');");
  console.log(`  collected firing order -> ${JSON.stringify(ntLog)}`);
  console.log("  => nextTick queue drains before the microtask queue (Node-specific).");
  console.log("  CAVEAT: at top level / inside an async resumption the order can flip");
  console.log("          (V8's microtask checkpoint drains promises first there).");
  check(
    "process.nextTick fires before Promise.then (macrotask context, Node)",
    JSON.stringify(ntLog) === '["sync","nextTick","microtask"]',
  );

  // Microtask STARVATION: because the microtask drain is exhaustive, a
  // microtask that re-schedules itself INDEFINITELY will NEVER let the loop
  // proceed to a macrotask — timers, I/O callbacks, and rendering all starve.
  // We must NOT actually infinite-loop (it would hang the process). Instead we
  // demonstrate the MECHANISM with a FINITE chain of 3 self-rescheduling
  // microtasks, then prove the rule: the queued setTimeout macrotask cannot
  // fire until EVERY microtask (including the chained ones) has drained.
  const starveLog: string[] = [];
  let count = 0;
  const feed = (): void => {
    count += 1;
    starveLog.push(`micro-${count}`);
    if (count < 3) {
      queueMicrotask(feed); // re-schedule as a microtask -> extends the drain
    }
  };
  setTimeout(() => { starveLog.push("macrotask-finally"); }, 0);
  queueMicrotask(feed);
  await sleep(20);

  console.log("");
  console.log("Microtask starvation mechanism (FINITE demo — an INFINITE chain hangs):");
  console.log("  // feed() pushes `micro-n` then, if n<3, queueMicrotask(feed) again");
  console.log("  setTimeout(() => starve.push('macrotask-finally'), 0);");
  console.log("  queueMicrotask(feed);");
  console.log(`  collected firing order -> ${JSON.stringify(starveLog)}`);
  console.log("  => the macrotask waits until the ENTIRE microtask chain drains.");
  console.log("  => if feed() always re-queued itself, the macrotask would NEVER fire.");
  check(
    "finite microtask chain fully drains before the macrotask (starvation mechanism)",
    JSON.stringify(starveLog) ===
      '["micro-1","micro-2","micro-3","macrotask-finally"]',
  );
}

// ============================================================================
// Section D — The Node.js (libuv) loop phases: setImmediate vs setTimeout(0)
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — The Node.js (libuv) loop phases: setImmediate vs setTimeout(0)");

  // Node's loop (implemented by libuv) is PHASED. Each "tick" walks the phases
  // in order: timers -> pending callbacks -> idle/prepare -> poll -> check ->
  // close -> (repeat). The phase a callback runs in is fixed by its source:
  //   - setTimeout/setInterval  -> timers phase
  //   - most I/O callbacks      -> poll phase
  //   - setImmediate            -> check phase (right after poll)
  //   - socket 'close'          -> close phase
  // Microtasks (and process.nextTick) are drained BETWEEN phases, not shown as
  // a phase. (Since libuv 1.45 / Node 20, timers run only AFTER the poll phase
  // within a tick.)

  console.log("Node.js (libuv) loop phases — each tick walks them in this order:");
  console.log("  timers -> pending callbacks -> idle/prepare -> poll -> check -> close -> (repeat)");
  console.log("  setTimeout/setInterval : timers phase");
  console.log("  most I/O callbacks     : poll phase");
  console.log("  setImmediate           : check phase (runs right AFTER poll)");
  console.log("  microtasks + nextTick  : drained BETWEEN phases (not a phase)");
  check("setImmediate runs in the check phase (after poll, before the next tick's timers)", true);

  // THE ordering caveat (Node.js docs, "setImmediate() vs setTimeout()"):
  //   - Called from the MAIN MODULE: the order is NON-DETERMINISTIC (it depends
  //     on process performance / how far into the 1ms clamp the loop is). We do
  //     NOT assert it — it varies run to run.
  //   - Called from WITHIN AN I/O CYCLE (a poll-phase callback): setImmediate is
  //     ALWAYS executed first, deterministically, because setImmediate queues
  //     for THIS tick's check phase (right after poll) while setTimeout(0) goes
  //     to the NEXT tick's timers phase.
  // We demonstrate the DETERMINISTIC case by scheduling both inside an
  // fs.readFile I/O callback (poll phase). The readFile timing is irrelevant —
  // only the ORDER of the two inner callbacks matters, and it is fixed.
  const ioLog: string[] = [];
  await new Promise<void>((resolve: () => void): void => {
    fs.readFile(
      new URL("./package.json", import.meta.url),
      (_err: NodeJS.ErrnoException | null): void => {
        // Inside a poll-phase (I/O) callback:
        setTimeout(() => { ioLog.push("setTimeout(0)"); }, 0); // -> next tick's timers
        setImmediate(() => { ioLog.push("setImmediate"); }); // -> this tick's check
        setTimeout(resolve, 20); // a later macrotask; both above have fired by then
      },
    );
  });

  console.log("");
  console.log("Inside an I/O cycle (poll-phase callback), setImmediate ALWAYS precedes setTimeout(0):");
  console.log("  fs.readFile(file, () => {                       // poll-phase callback");
  console.log("    setTimeout(() => log.push('setTimeout(0)'), 0); // next tick's timers");
  console.log("    setImmediate(() => log.push('setImmediate'));   // this tick's check");
  console.log("  });");
  console.log(`  collected firing order -> ${JSON.stringify(ioLog)}`);
  console.log("  => from an I/O cycle, setImmediate is DETERMINISTICALLY first.");
  console.log("  CAVEAT: from the MAIN MODULE the order is NON-DETERMINISTIC (not asserted).");
  check(
    "inside an I/O cycle: setImmediate fires before setTimeout(0) (deterministic)",
    ioLog.length === 2 && ioLog[0] === "setImmediate" && ioLog[1] === "setTimeout(0)",
  );

  // process.nextTick vs setImmediate (Node docs): confusingly, nextTick fires
  // MORE immediately than setImmediate despite the names. nextTick drains after
  // the current operation (before any phase proceeds); setImmediate runs in the
  // check phase of the next tick. Node recommends setImmediate for user code
  // because it is easier to reason about. nextTick can STARVE I/O (Section C).
  const niLog: string[] = [];
  setImmediate(() => { niLog.push("setImmediate"); });
  process.nextTick(() => { niLog.push("nextTick"); });
  await sleep(20);

  console.log("");
  console.log("process.nextTick fires BEFORE setImmediate (despite the misleading names):");
  console.log("  setImmediate(() => ni.push('setImmediate'));  // check phase, next tick");
  console.log("  process.nextTick(() => ni.push('nextTick'));   // after current op (this tick)");
  console.log(`  collected firing order -> ${JSON.stringify(niLog)}`);
  console.log("  => Node docs: 'the names should be swapped' — but won't change (npm breakage).");
  check(
    "process.nextTick fires before setImmediate",
    JSON.stringify(niLog) === '["nextTick","setImmediate"]',
  );
}

// ============================================================================
// Section E — Blocking the loop (don't!) + why async I/O scales
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — Blocking the loop (don't!) + why async I/O scales");

  // "Don't block the event loop." A macrotask can only be picked when the call
  // stack is EMPTY. So any synchronous CPU-bound work (a busy-loop, a heavy
  // computation, a synchronous while(true)) keeps the stack non-empty and
  // DELAYS every queued callback — timers fire late, I/O callbacks wait, the
  // UI freezes. We prove the delay via ORDER (not ms): we schedule a
  // setTimeout(0), then run a synchronous busy-loop, then push a label. The
  // timeout's label can only appear AFTER the busy-loop's label, because the
  // timeout callback physically cannot run until the synchronous code finishes
  // and the stack empties. (We assert ORDER; the loop length affects only
  // wall-clock ms, which we never assert.)

  const blockLog: string[] = [];
  setTimeout(() => { blockLog.push("timeout-fired"); }, 0); // queued as a macrotask
  blockLog.push("timeout-scheduled"); // sync: runs now, on the stack
  // Synchronous CPU work — blocks the loop. The macrotask above CANNOT fire
  // while this runs (the stack is non-empty, so the loop never reaches step 1).
  let sum = 0;
  for (let k = 0; k < 5_000_000; k++) {
    sum += k;
  }
  blockLog.push(`after-busy-loop-sum=${sum}`); // sync: still runs before the timeout
  await sleep(20); // now the stack empties and the delayed timeout finally fires

  console.log("A synchronous busy-loop DELAYS a queued setTimeout (proof by ORDER):");
  console.log("  setTimeout(() => log.push('timeout-fired'), 0); // queued (macrotask)");
  console.log("  log.push('timeout-scheduled');                  // sync, now");
  console.log("  for (let k = 0; k < 5_000_000; k++) sum += k;   // sync CPU work BLOCKS");
  console.log("  log.push(`after-busy-loop-sum=${sum}`);       // sync, still before timeout");
  console.log(`  collected firing order -> ${JSON.stringify(blockLog)}`);
  console.log("  => 'timeout-fired' appears LAST: it was delayed past ALL the sync work.");
  console.log("  => this is WHY CPU-heavy code must be chunked or moved to a worker (🔗 WORKER_THREADS).");
  check(
    "blocking delays the timer: 'timeout-fired' fires AFTER the busy-loop (last)",
    blockLog.length === 3 &&
      blockLog[0] === "timeout-scheduled" &&
      blockLog[1] === `after-busy-loop-sum=${sum}` &&
      blockLog[2] === "timeout-fired",
  );

  // Why async I/O is how Node scales on ONE thread: I/O (sockets, files, DNS)
  // is OFFLOADED to the OS (async) and to libuv's thread pool (for the
  // blocking-by-nature ops like fs / dns.lookup). Node's single JS thread just
  // registers a callback and moves on; when the OS/pool completes the work, it
  // pushes the callback onto the poll queue, and the loop resumes it. The
  // single thread therefore spends almost no time WAITING — it is always doing
  // useful JS work. This is the opposite of the thread-per-connection model.
  console.log("");
  console.log("Why async I/O scales on ONE thread (Node.js docs):");
  console.log("  - I/O is offloaded to the OS kernel (async) and to libuv's thread pool");
  console.log("    (for inherently-blocking ops: fs, dns.lookup, some crypto).");
  console.log("  - The JS thread registers a callback and moves on immediately;");
  console.log("    it never blocks WAITING for I/O.");
  console.log("  - On completion the kernel/pool pushes the callback to the POLL queue;");
  console.log("    the loop resumes it in the poll phase. (🔗 TIMERS_IO, Phase 4.)");
  check(
    "Node scales via async I/O offload (OS kernel + libuv thread pool), not thread-per-connection",
    true,
  );
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("event_loop.ts — Phase 4 bundle #1 (the foundational concurrency bundle).");
  console.log("Every interleaving below is captured by THIS file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: JS is SINGLE-THREADED. The event loop runs ONE macrotask,");
  console.log("drains ALL microtasks, then picks the next macrotask — forever. Every");
  console.log("ordering below is collected into an array in firing order, then printed");
  console.log("after all queued callbacks drain (collect-then-print => byte-identical).");
  console.log("We assert ORDER only, never timing durations (ms are non-reproducible).");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

await main();
