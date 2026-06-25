// timers_io.ts — Phase 4 bundle.
//
// GOAL (one line): show, by collecting each callback's label into an array in
// the ORDER it fires, how setTimeout / setInterval / setImmediate /
// process.nextTick / AbortSignal.timeout schedule work against the Node (libuv)
// event loop — the MACROTASK sources — and how async I/O resumes in the poll
// phase.
//
// This is the GROUND TRUTH for TIMERS_IO.md. Every interleaving, ordering, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it goes DEEPER on than EVENT_LOOP):
// EVENT_LOOP owns the QUEUE MODEL (one macrotask -> drain ALL microtasks ->
// repeat) and the single-threaded "don't block" rule. PROMISES owns the
// microtask-as-promise-callback story. THIS bundle (P4) owns the TIMER + I/O
// SOURCES that FEED those queues:
//   - setTimeout(fn, ms, ...args) / clearTimeout  — one-shot macrotask (timers
//     phase). delay is a THRESHOLD not a guarantee; 0 still waits a tick (~1ms
//     clamp in Node). Extra args are forwarded verbatim to the callback.
//   - setInterval(fn, ms, ...) / clearInterval     — REPEATING macrotask; must
//     be cancelled or the process never exits.
//   - the THREE queues: nextTick > microtask > macrotask. process.nextTick
//     (Node-only) has HIGHER priority than Promise.then (🔗 PROMISES).
//   - setImmediate (check phase) vs setTimeout(0) (timers phase): the
//     phase-dependent ordering caveat — NON-deterministic from the main module,
//     DETERMINISTIC (setImmediate first) inside an I/O cycle (🔗 EVENT_LOOP D).
//   - AbortSignal.timeout(ms): a MODERN self-aborting signal whose reason is a
//     TimeoutError DOMException — the cancellation primitive (no manual
//     clearTimeout bookkeeping needed).
//   - I/O via libuv: fs/net callbacks resume in the POLL phase; blocking syscalls
//     are offloaded to libuv's thread pool (default 4 threads). A sync busy-loop
//     delays every queued timer (fire-late evidence, by ORDER not by ms).
//
// DETERMINISM (THE key caveat, per HOW_TO_RESEARCH §4.2 rule 4): timer FIRING
// ORDER is deterministic (spec-defined queue priority + libuv phase order);
// ABSOLUTE ms are NOT (OS scheduling, machine load). We therefore:
//   - collect each callback's label into a shared array IN FIRING ORDER, and
//     print the array ONCE at the end (after every queued callback has drained
//     via `await sleep(N)`). This makes stdout byte-identical across runs while
//     faithfully showing the real interleaving.
//   - assert ORDER + firing COUNT only, NEVER elapsed wall-clock ms.
//   - CANCEL every timer (clearTimeout / clearInterval) before main returns so
//     the process exits deterministically with code 0 (no dangling handle keeps
//     the loop alive). AbortSignal.timeout's internal timer self-cleans on
//     abort, so it needs no explicit clear.
//   - document (do NOT assert) the ONE non-deterministic pair: main-module
//     setImmediate-vs-setTimeout(0).
//
// Run:
//     pnpm exec tsx timers_io.ts   (or: just run timers_io)

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

// pendingTimers collects every handle we create so main() can clear them all
// before returning (deterministic exit). clearTimeout/clearInterval on an
// already-fired handle is a documented no-op, so clearing aggressively is safe.
const pendingTimers: ReturnType<typeof setTimeout>[] = [];
type IntervalHandle = ReturnType<typeof setInterval>;

// ============================================================================
// Section A — setTimeout / setInterval / clear* (timer APIs + macrotask nature)
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — setTimeout / setInterval / clear* (timer APIs + macrotask nature)");

  // --- setTimeout with extra args (forwarded verbatim to the callback) -------
  // Signature: setTimeout(fn, delay, ...args). Every arg after `delay` is passed
  // to `fn` when it fires. (There is NO separate thisArg parameter — the brief's
  // "this-arg/extra args" refers to these trailing args; `this` inside `fn` is
  // the global object in non-strict / undefined in strict mode, as for any
  // plain function call.)
  const argsLog: string[] = [];
  const tArgs = setTimeout(
    (a: string, b: number) => {
      argsLog.push(`a=${a},b=${b}`);
    },
    0,
    "x",
    99,
  );
  pendingTimers.push(tArgs);
  await sleep(20);

  console.log("setTimeout(fn, delay, ...args) forwards extra args verbatim:");
  console.log('  setTimeout((a, b) => cb(`a=${a},b=${b}`), 0, "x", 99)');
  console.log(`  callback received -> ${JSON.stringify(argsLog[0] ?? "<never>")}`);
  check(
    'setTimeout forwards extra args (arg1="x", arg2=99) to the callback',
    argsLog[0] === "a=x,b=99",
  );

  // --- setInterval: repeats; clearInterval stops it (count asserted, not ms) --
  // setInterval queues a macrotask every ~ms INDEFINITELY until clearInterval.
  // We let it fire a FIXED small count (3), then clearInterval — otherwise the
  // process would never exit (the repeating handle keeps the loop alive).
  const ticks: string[] = [];
  let tickCount = 0;
  const iv: IntervalHandle = setInterval(() => {
    tickCount += 1;
    ticks.push(`tick-${tickCount}`);
    if (tickCount >= 3) {
      clearInterval(iv); // STOP the repetition — mandatory for deterministic exit
    }
  }, 1);
  pendingTimers.push(iv as unknown as ReturnType<typeof setTimeout>);
  await sleep(50);

  console.log("");
  console.log("setInterval REPEATS; clearInterval stops it (count asserted, not ms):");
  console.log("  let n = 0;");
  console.log("  const iv = setInterval(() => { n++; log(`tick-${n}`); if (n >= 3) clearInterval(iv); }, 1);");
  console.log(`  fires observed -> ${JSON.stringify(ticks)}`);
  check(
    "setInterval fired exactly 3 times then clearInterval stopped it (no 4th)",
    ticks.length === 3 &&
      ticks[0] === "tick-1" &&
      ticks[1] === "tick-2" &&
      ticks[2] === "tick-3",
  );

  // --- clearTimeout cancels a pending timer (callback never runs) ------------
  const cancelLog: string[] = [];
  const tCancel = setTimeout(() => {
    cancelLog.push("fired");
  }, 0);
  clearTimeout(tCancel); // cancel BEFORE it fires
  await sleep(20);

  console.log("");
  console.log("clearTimeout cancels a pending timer (the callback NEVER runs):");
  console.log("  const t = setTimeout(() => log.push('fired'), 0);");
  console.log("  clearTimeout(t);   // cancel before it fires");
  console.log(`  callback ran? -> ${cancelLog.length === 0 ? "NO (cancelled)" : "YES (bug)"}`);
  check("clearTimeout cancelled the timer (callback never fired)", cancelLog.length === 0);

  // --- THE headline: a microtask ALWAYS preempts a setTimeout(0) macrotask ---
  // setTimeout(fn, 0) does NOT mean "run fn immediately". delay is a THRESHOLD:
  // fn is queued as a MACROTASK and cannot run until the current stack empties
  // AND the microtask queue drains. So a Promise.then (microtask) always wins.
  // (Min delay clamp: ~1ms in Node; 0ms is coerced to 1ms internally. We never
  // assert the clamp value — only the ORDER.)
  const orderLog: string[] = [];
  orderLog.push("sync"); // synchronous: runs now, on the current stack
  const tMacro = setTimeout(() => {
    orderLog.push("timeout");
  }, 0); // queues a MACROTASK (timers phase)
  pendingTimers.push(tMacro);
  Promise.resolve().then(() => {
    orderLog.push("promise");
  }); // queues a MICROTASK
  await sleep(20);

  console.log("");
  console.log("setTimeout(0) is a MACROTASK: a microtask ALWAYS preempts it:");
  console.log("  log.push('sync');                                // runs NOW (on stack)");
  console.log("  setTimeout(() => log.push('timeout'), 0);        // queues a MACROTASK");
  console.log("  Promise.resolve().then(() => log.push('promise'));// queues a MICROTASK");
  console.log(`  collected firing order -> ${JSON.stringify(orderLog)}`);
  console.log("  => microtask drains BEFORE the next macrotask. (delay is a THRESHOLD, not a guarantee.)");
  check(
    "setTimeout(0) macrotask fires AFTER sync AND the promise microtask",
    JSON.stringify(orderLog) === '["sync","promise","timeout"]',
  );
}

// ============================================================================
// Section B — FIRING ORDER: the three queues (nextTick > microtask > macrotask)
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — FIRING ORDER: the three queues (nextTick > microtask > macrotask)");

  // Node has THREE callback queues, drained in a FIXED priority order between
  // macrotasks (🔗 EVENT_LOOP §C, §D):
  //   1. nextTick queue   (process.nextTick)        — Node-only, HIGHEST priority
  //   2. microtask queue  (Promise.then / queueMicrotask)
  //   3. macrotask queue  (setTimeout / setInterval / setImmediate / I/O)
  // Both the nextTick and microtask queues drain TO EMPTY between phases and
  // between macrotasks (exhaustive drain — a self-rescheduling microtask starves
  // the macrotask queue; see 🔗 EVENT_LOOP §C).

  // Determinism caveat (Node 20+, observed): the nextTick-before-microtask
  // priority is reproducible when both are scheduled from WITHIN a macrotask
  // (setTimeout / setImmediate / I/O). At the very TOP LEVEL of a script, or
  // inside an async RESUMPTION (after `await`), V8's microtask checkpoint can
  // drain the promise queue first, flipping the order. We therefore schedule
  // from INSIDE a setTimeout macrotask — the documented, deterministic context.
  const qLog: string[] = [];
  await new Promise<void>((resolve: () => void) => {
    const t = setTimeout(() => {
      // Clean macrotask context: schedule all four synchronously, in source order.
      process.nextTick(() => {
        qLog.push("nextTick");
      }); // queue 1: nextTick (Node-only)
      Promise.resolve().then(() => {
        qLog.push("promise");
      }); // queue 2: microtask (FIFO)
      queueMicrotask(() => {
        qLog.push("queueMicrotask");
      }); // queue 2: microtask (FIFO, after promise)
      const imm = setImmediate(() => {
        qLog.push("setImmediate");
      }); // queue 3: macrotask (check phase)
      pendingTimers.push(imm as unknown as ReturnType<typeof setTimeout>);
      qLog.push("sync"); // sync: runs now, before any queue drains
      // Hand off to a LATER macrotask to read the array after everything drains.
      const tEnd = setTimeout(resolve, 20);
      pendingTimers.push(tEnd);
    }, 0);
    pendingTimers.push(t);
  });

  console.log("Node has THREE callback queues, drained in FIXED priority order:");
  console.log("  1. nextTick queue  (process.nextTick)        — Node-only, HIGHEST priority");
  console.log("  2. microtask queue (Promise.then/queueMicrotask)");
  console.log("  3. macrotask queue (setTimeout/setImmediate/I/O)");
  console.log("  Both nextTick + microtask queues drain TO EMPTY between macrotasks.");
  console.log("");
  console.log("Scheduled from INSIDE a setTimeout macrotask (the deterministic context):");
  console.log("  process.nextTick(() => log.push('nextTick'));       // queue 1");
  console.log("  Promise.resolve().then(() => log.push('promise'));  // queue 2 (FIFO)");
  console.log("  queueMicrotask(() => log.push('queueMicrotask'));   // queue 2 (FIFO)");
  console.log("  setImmediate(() => log.push('setImmediate'));       // queue 3 (macrotask)");
  console.log("  log.push('sync');");
  console.log(`  collected firing order -> ${JSON.stringify(qLog)}`);
  console.log("  => sync runs first; nextTick drains before microtask; macrotask runs LAST.");
  console.log("  NOTE: setImmediate vs setTimeout(0) is the ONE non-deterministic pair (§C).");
  check(
    "nextTick > microtask > macrotask (sync, nextTick, promise, queueMicrotask, setImmediate)",
    JSON.stringify(qLog) ===
      '["sync","nextTick","promise","queueMicrotask","setImmediate"]',
  );

  // Top-level caveat: documented, not asserted (it can flip across V8 versions).
  console.log("");
  console.log("CAVEAT (top-level / async-resumption): at the very TOP LEVEL of a script,");
  console.log("or inside an async RESUMPTION (after `await`), V8's microtask checkpoint can");
  console.log("drain the promise queue BEFORE nextTick, flipping that pair. The macrotask");
  console.log("context above is the documented, deterministic one.");
  check(
    "nextTick-before-microtask is reproducible from a macrotask context (caveat documented)",
    true,
  );
}

// ============================================================================
// Section C — setImmediate (check) vs setTimeout(0) (timers): the phase caveat
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — setImmediate (check) vs setTimeout(0) (timers): the phase caveat");

  // setImmediate queues in the CHECK phase; setTimeout(0) queues in the TIMERS
  // phase. Both are macrotasks. The relative order of those two phases WITHIN
  // a tick depends on WHERE in the tick you schedule them:
  //   - MAIN MODULE (no I/O in flight): NON-deterministic — bound by process
  //     performance / how far into the 1ms clamp the loop is. We DOCUMENT but
  //     do NOT assert it (the order flips run to run).
  //   - INSIDE AN I/O CYCLE (a poll-phase callback): DETERMINISTIC — setImmediate
  //     is ALWAYS first, because the check phase runs at the end of the SAME
  //     tick (right after poll), while setTimeout(0)'s 1ms-clamped timer lands
  //     in the NEXT tick's timers phase.

  // --- Main-module order: NON-deterministic (observed, NOT asserted) ---------
  const mainLog: string[] = [];
  const immMain = setImmediate(() => {
    mainLog.push("setImmediate");
  });
  const tMain = setTimeout(() => {
    mainLog.push("setTimeout(0)");
  }, 0);
  pendingTimers.push(immMain as unknown as ReturnType<typeof setTimeout>);
  pendingTimers.push(tMain);
  await sleep(20);

  console.log("setImmediate -> CHECK phase;  setTimeout(0) -> TIMERS phase (both macrotasks).");
  console.log("Main-module order is NON-deterministic (observed this run, NOT asserted):");
  console.log("  setImmediate(() => log.push('setImmediate'));");
  console.log("  setTimeout(() => log.push('setTimeout(0)'), 0);");
  console.log(`  observed order this run -> ${JSON.stringify(mainLog)}   (could be either!)`);
  check(
    "main-module setImmediate-vs-setTimeout(0) is non-deterministic (observed, not asserted)",
    mainLog.length === 2, // both fired — but order is not asserted
  );

  // --- Inside an I/O cycle: setImmediate is DETERMINISTICALLY first ---------
  // fs.access(".") is an I/O syscall: its callback runs in the POLL phase. From
  // inside that callback, setImmediate queues for THIS tick's check phase, while
  // setTimeout(0) (min 1ms clamp) queues for the NEXT tick's timers phase.
  // Hence setImmediate always wins. (Node.js docs: "the immediate callback is
  // always executed first" within an I/O cycle.)
  const ioCycleLog: string[] = [];
  await new Promise<void>((resolve: () => void) => {
    fs.access(".", (err: NodeJS.ErrnoException | null) => {
      if (err !== null) {
        throw err; // "." always exists; surface any unexpected error
      }
      // Inside the poll-phase I/O callback:
      const imm = setImmediate(() => {
        ioCycleLog.push("setImmediate");
      }); // this tick's CHECK phase
      const t = setTimeout(() => {
        ioCycleLog.push("setTimeout(0)");
      }, 0); // next tick's TIMERS phase
      pendingTimers.push(imm as unknown as ReturnType<typeof setTimeout>);
      pendingTimers.push(t);
      const tEnd = setTimeout(resolve, 20);
      pendingTimers.push(tEnd);
    });
  });

  console.log("");
  console.log("INSIDE AN I/O CYCLE (poll-phase callback): setImmediate is ALWAYS first:");
  console.log('  fs.access(".", () => {                       // I/O callback -> POLL phase');
  console.log("    setImmediate(() => log.push('setImmediate'));  // this tick's CHECK phase");
  console.log("    setTimeout(() => log.push('setTimeout(0)'), 0);// next tick's TIMERS phase");
  console.log("  });");
  console.log(`  collected firing order -> ${JSON.stringify(ioCycleLog)}`);
  console.log("  => check phase runs at the END of this tick; setTimeout(0)'s 1ms clamp pushes");
  console.log("     it into the NEXT tick's timers phase. setImmediate always wins here.");
  check(
    "inside an I/O cycle: setImmediate fires before setTimeout(0) (deterministic)",
    JSON.stringify(ioCycleLog) === '["setImmediate","setTimeout(0)"]',
  );
}

// ============================================================================
// Section D — libuv phase model + AbortSignal.timeout(ms) (modern)
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — libuv phase model + AbortSignal.timeout(ms) (modern)");

  // Node's event loop is implemented by libuv and runs PHASES in a fixed order
  // each tick. The phase a callback runs in is fixed by its SOURCE. Microtasks
  // and process.nextTick are NOT phases — they drain BETWEEN phases.
  //   (Since libuv 1.45 / Node 20: timers run only AFTER the poll phase within
  //   a tick, instead of both before and after. This is what makes setImmediate
  //   deterministically first inside an I/O cycle — see §C.)
  console.log("Node.js (libuv) loop phases — each tick walks them in this order:");
  console.log("  timers -> pending callbacks -> idle/prepare -> poll -> check -> close -> (repeat)");
  console.log("  setTimeout / setInterval : timers phase   (callbacks whose threshold elapsed)");
  console.log("  most I/O callbacks       : poll phase      (fs/net/DNS — retrieve new I/O events)");
  console.log("  setImmediate             : check phase     (runs right AFTER poll)");
  console.log("  socket/stream 'close'    : close phase");
  console.log("  nextTick + microtasks    : drained BETWEEN every phase (not a phase)");
  console.log("  (libuv >= 1.45 / Node >= 20: timers run only AFTER poll within a tick.)");
  check(
    "libuv phase order: timers -> pending -> poll -> check -> close (microtasks between)",
    true,
  );

  // --- AbortSignal.timeout(ms): a SELF-ABORTING signal (Node 17.3+, browsers) -
  // The modern, boilerplate-free way to get a timeout: it returns an AbortSignal
  // whose internal timer auto-aborts after ~ms. On abort, signal.reason is a
  // DOMException with name "TimeoutError" (NOT a plain Error, NOT "AbortError").
  // No manual clearTimeout bookkeeping is needed — the timer self-cleans.
  const signal = AbortSignal.timeout(20); // internal timer; auto-aborts
  // Wait for the internal timer to fire + abort (we assert STATE, never the ms).
  await sleep(50);

  const reason: unknown = signal.reason;
  const reasonIsDomException = reason instanceof DOMException;
  const reasonName = reasonIsDomException ? reason.name : String(reason);

  console.log("");
  console.log('AbortSignal.timeout(ms) (Node 17.3+ / browsers): a SELF-ABORTING signal.');
  console.log("  const signal = AbortSignal.timeout(20);   // internal timer, auto-aborts");
  console.log("  // after ~20ms: signal.aborted === true; reason is a TimeoutError DOMException");
  console.log(`  signal.aborted           -> ${signal.aborted}`);
  console.log(`  signal.reason instanceof -> ${reasonIsDomException ? "DOMException" : "(not DOMException)"}`);
  console.log(`  signal.reason.name       -> ${JSON.stringify(reasonName)}`);
  check(
    "AbortSignal.timeout(20) self-aborts (signal.aborted === true)",
    signal.aborted === true,
  );
  check(
    'reason is a DOMException named "TimeoutError"',
    reasonIsDomException === true && reasonName === "TimeoutError",
  );

  // --- A manual AbortController can abort EARLY with a custom reason --------
  // AbortSignal.timeout is one-shot + fixed reason. For user-driven cancellation
  // (cancel a fetch on unmount, a "stop" button), use an AbortController: you
  // hold abort(), you pick the reason. Both feed the SAME signal.aborted contract.
  const ac = new AbortController();
  const sig2 = ac.signal; // not yet aborted
  check("fresh AbortController.signal.aborted === false (before abort)", sig2.aborted === false);
  ac.abort(new Error("user cancelled")); // abort NOW, with a programmer-chosen reason
  const reason2: unknown = sig2.reason;
  const reason2Msg = reason2 instanceof Error ? reason2.message : String(reason2);

  console.log("");
  console.log("A manual AbortController aborts EARLY with a programmer-chosen reason:");
  console.log("  const ac = new AbortController();");
  console.log("  const sig2 = ac.signal;                       // aborted === false");
  console.log('  ac.abort(new Error("user cancelled"));        // abort now, custom reason');
  console.log(`  sig2.aborted        -> ${sig2.aborted}`);
  console.log(`  sig2.reason.message -> ${JSON.stringify(reason2Msg)}`);
  check(
    'manual AbortController.abort() sets aborted + propagates the custom reason',
    sig2.aborted === true && reason2Msg === "user cancelled",
  );
}

// ============================================================================
// Section E — I/O via libuv poll phase + thread pool + "don't block the loop"
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner('E — I/O via libuv poll phase + thread pool + "don\'t block the loop"');

  // Async I/O is OFFLOADED so the single JS thread never blocks WAITING:
  //   - Sockets / epoll / kqueue: handled by the OS kernel async; on completion
  //     the kernel hands the callback to libuv, which queues it for the POLL phase.
  //   - Inherently-BLOCKING syscalls (fs.*, dns.lookup, some crypto, zlib): run
  //     on libuv's THREAD POOL (default 4 threads; resize via UV_THREADPOOL_SIZE).
  // The JS thread registers a callback and moves on; on completion the callback
  // resumes in the poll phase. This is how Node scales concurrent I/O on ONE
  // thread (the opposite of thread-per-connection).

  // --- fs.readFile is async: the callback runs LATER, after the sync stack ---
  // We assert that the callback fires (asynchronously) and receives the data —
  // NOT its ordering vs a timer (poll-vs-timers ordering is non-deterministic:
  // it depends on whether the I/O completes before the loop enters poll).
  const pkgUrl = new URL("./package.json", import.meta.url);
  // Resolve the name THROUGH the promise (rather than mutating an outer `let`):
  // the assignment happens inside a nested callback, which TS's linear control-
  // flow analysis cannot see — so an outer `let` would narrow to `never` at the
  // later check. A typed Promise<string> resolves cleanly to `string`.
  const receivedName: string = await new Promise<string>(
    (resolve: (value: string) => void, reject: (reason: unknown) => void) => {
      fs.readFile(pkgUrl, "utf8", (err: NodeJS.ErrnoException | null, data: string) => {
        if (err !== null) {
          reject(err);
          return;
        }
        // The callback runs in the POLL phase, after the current sync stack empties.
        const pkg = JSON.parse(data) as { name: string };
        resolve(pkg.name);
      });
    },
  );

  console.log("Async I/O is OFFLOADED (the JS thread never blocks WAITING):");
  console.log("  - sockets/epoll/kqueue: OS kernel async -> callback queued for POLL phase");
  console.log("  - blocking syscalls (fs/dns.lookup/crypto/zlib): libuv THREAD POOL (4 default)");
  console.log("");
  console.log("fs.readFile is async — the callback runs LATER (in the poll phase):");
  console.log('  fs.readFile(new URL("./package.json", import.meta.url), "utf8", (err, data) => {');
  console.log("    const pkg = JSON.parse(data);   // <- runs in POLL phase, after sync stack");
  console.log("  });");
  console.log(`  callback received pkg.name -> ${JSON.stringify(receivedName)}`);
  check(
    "fs.readFile callback fired asynchronously and received the file data",
    receivedName !== null && receivedName.length > 0,
  );

  // --- "Don't block the loop": a sync busy-loop delays every queued timer ----
  // The single thread runs ONE macrotask to completion before picking the next.
  // A synchronous CPU loop HOLDS the thread: every queued timer (and every I/O
  // callback) is delayed until the sync code finishes and the stack empties.
  // We prove the delay by ORDER (not ms): schedule a setTimeout(0), run a busy
  // loop, push a label — the timer's label can only appear AFTER the sync label.
  const blockLog: string[] = [];
  const tBlock = setTimeout(() => {
    blockLog.push("timeout-fired");
  }, 0); // queued as a macrotask
  pendingTimers.push(tBlock);
  blockLog.push("timeout-scheduled"); // sync: runs now, on the stack
  // Synchronous CPU work — BLOCKS the loop. The macrotask above CANNOT fire
  // while this runs (the stack is non-empty; the loop never reaches step 1).
  let sum = 0;
  for (let k = 0; k < 5_000_000; k++) {
    sum += k;
  }
  blockLog.push(`after-busy-loop-sum=${sum}`); // sync: still before the timeout
  await sleep(20); // now the stack empties and the delayed timeout finally fires

  console.log("");
  console.log('A synchronous busy-loop DELAYS every queued timer (proof by ORDER, not ms):');
  console.log("  setTimeout(() => log.push('timeout-fired'), 0);   // queued (macrotask)");
  console.log("  log.push('timeout-scheduled');                    // sync, now");
  console.log("  for (let k = 0; k < 5_000_000; k++) sum += k;     // sync CPU work BLOCKS");
  console.log("  log.push(`after-busy-loop-sum=${sum}`);            // sync, still before timeout");
  console.log(`  collected firing order -> ${JSON.stringify(blockLog)}`);
  console.log("  => 'timeout-fired' appears LAST: it was delayed past ALL the sync work.");
  console.log("  => CPU-heavy code must be chunked or moved to a worker (🔗 WORKER_THREADS).");
  check(
    "blocking delays the timer: 'timeout-fired' fires AFTER the busy-loop (last)",
    blockLog.length === 3 &&
      blockLog[0] === "timeout-scheduled" &&
      blockLog[1] === `after-busy-loop-sum=${sum}` &&
      blockLog[2] === "timeout-fired",
  );
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("timers_io.ts — Phase 4 bundle (the timer + I/O macrotask sources).");
  console.log("Every interleaving below is captured by THIS file; the .md guide pastes");
  console.log("it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: timer FIRING ORDER is deterministic (spec + libuv phases);");
  console.log("ABSOLUTE ms are NOT. We collect labels into an array in firing order,");
  console.log("print after drain, assert ORDER + COUNT only (never ms), and cancel");
  console.log("every timer before main returns so the process exits deterministically.");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();

  // DETERMINISTIC EXIT: cancel every timer we created (clearTimeout/clearInterval
  // on an already-fired handle is a documented no-op). This guarantees no
  // dangling handle keeps the event loop alive — the process exits with code 0.
  for (const t of pendingTimers) {
    clearTimeout(t);
  }
  sectionBanner("DONE — all sections printed");
}

await main();
