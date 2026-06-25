// shared_memory_atomics.ts — Phase 4 bundle (core member, stdlib-only).
//
// GOAL (one line): show, by writing to a SharedArrayBuffer from real
// `node:worker_threads` Workers, that SAB is SHARED (not copied) across threads,
// that plain parallel writes DATA-RACE (lost updates), and that Atomics
// (add/load/store/compareExchange/wait/notify) makes shared-memory concurrency
// DETERMINISTIC and correct.
//
// This is the GROUND TRUTH for SHARED_MEMORY_ATOMICS.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle lives at Phase 4): worker_threads (WORKER_THREADS) is
// how JS escapes the single thread — but `postMessage` COPIES via structured
// clone, so workers are ISOLATED by default. SharedArrayBuffer (SAB) is the ONE
// exception: a SAB passed via workerData is SHARED by reference (the SAME bytes
// are visible to main and every worker, no copy). With shared memory come DATA
// RACES (lost updates) — and Atomics is the stdlib primitive that fixes them:
// atomic read-modify-write (add/sub/exchange/compareExchange), ordered
// load/store, and the futex-like wait/notify. SAB + Atomics is the ONLY real
// shared-memory parallelism primitive in JS — the direct analog of Go's
// sync/atomic + memory model and Rust's AtomicUsize/Ordering.
//
// THE __filename SELF-WORKER IDIOM (single-file bundle): this SAME file runs as
// BOTH the main thread AND the worker (see the branch at the bottom). Main
// spawns workers with `new Worker(__filename, { workerData })`; the worker
// re-executes this file, hits `if (!isMainThread)`, and dispatches to
// runWorker(). The SharedArrayBuffer is passed via workerData — structured
// clone SHARES it (same backing memory), it is NOT copied.
//
// DETERMINISM DISCIPLINE: Workers NEVER print (§4.2 rule 4). They only WRITE to
// the SharedArrayBuffer. Main reads the SAB AFTER all workers join (Promise.all
// of exits) and prints. Atomics operations are deterministic, so the printed
// atomic results are byte-identical across runs. The plain-write DATA RACE is
// nondeterministic; we run it and bound it (<= N*iters) but do NOT print its
// exact racy value (it varies per run) — see Section B.
//
// Run:
//     pnpm exec tsx shared_memory_atomics.ts   (or: just run shared_memory_atomics)

import {
  Worker,
  isMainThread,
  workerData,
} from "node:worker_threads";
import { fileURLToPath } from "node:url";

// ESM NOTE: `__filename` is a CommonJS global, NOT available in ESM. `core/` is
// `"type": "module"`, so we RECONSTRUCT the CJS `__filename` from
// `import.meta.url` via `fileURLToPath`. This is what `new Worker(__filename)`
// needs (it accepts a file PATH, not a URL).
const __filename = fileURLToPath(import.meta.url);

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

// ============================================================================
// SAB layout: one SharedArrayBuffer backs an Int32Array view. Named slot index
// keeps the worker/main protocol readable. Every int32 slot is Atomics-accessible.
// ============================================================================
const SLOT_VALUE = 0; // the cell workers race on / write to

// ============================================================================
// The worker's job contract. Main -> worker via `workerData` (set at spawn).
// Workers write their results into the SharedArrayBuffer and EXIT — they never
// post a message and never print. Main reads the SAB after the worker joins.
// ============================================================================

type WorkerJob =
  // Section A: write val into SAB[idx]; proves the write is VISIBLE to main.
  | { readonly kind: "write-shared"; readonly sab: SharedArrayBuffer; readonly idx: number; readonly val: number }
  // Section B: do `view[SLOT_VALUE] += 1` iters times with PLAIN (racy) writes.
  | { readonly kind: "race-plain"; readonly sab: SharedArrayBuffer; readonly iters: number }
  // Section C: do `Atomics.add(view, SLOT_VALUE, 1)` iters times (atomic RMW).
  | { readonly kind: "atomic-add"; readonly sab: SharedArrayBuffer; readonly iters: number }
  // Section D: Atomics.wait on cell 0 (futex), then record outcome + seen value.
  | { readonly kind: "waiter"; readonly sab: SharedArrayBuffer };

// `workerData` is typed as `any` in @types/node (the worker boundary cannot be
// statically typed). We narrow it with a single assertion into our discriminated
// union; every field is then checked by the switch arms below. This is the ONE
// unavoidable `as` at the worker boundary (the only place TS can't see in).
function jobFromWorkerData(): WorkerJob {
  return workerData as WorkerJob;
}

// runWorker is the WORKER-ROLE entry. It NEVER prints (workers must not touch
// stdout — §4.2 rule 4: output order is nondeterministic). It only WRITES to the
// SharedArrayBuffer, then returns — the worker exits naturally with code 0 once
// its event loop drains (no persistent listener holds it alive).
function runWorker(): void {
  const job = jobFromWorkerData();
  const view = new Int32Array(job.sab);

  switch (job.kind) {
    case "write-shared": {
      // Plain write into shared memory. Visible to main because SAB is SHARED
      // (structured clone of a SAB shares the backing bytes, no copy).
      view[job.idx] = job.val;
      return;
    }
    case "race-plain": {
      // PLAIN read-modify-write: `view[0] += 1` is THREE steps (load, add,
      // store) with NO atomicity. Concurrent workers clobber each other's stores
      // -> LOST UPDATES. The final value is nondeterministic. (`?? 0` is a
      // type-only guard; at runtime the slot is always a real int32.)
      for (let i = 0; i < job.iters; i++) {
        view[SLOT_VALUE] = (view[SLOT_VALUE] ?? 0) + 1;
      }
      return;
    }
    case "atomic-add": {
      // Atomics.add is an atomic read-modify-write: load+add+store happen as ONE
      // indivisible op. No updates can be lost. Returns the OLD value (ignored
      // here; Section E observes the return on the main thread).
      for (let i = 0; i < job.iters; i++) {
        Atomics.add(view, SLOT_VALUE, 1);
      }
      return;
    }
    case "waiter": {
      // Futex handoff. Atomics.wait blocks the CALLING thread while cell 0 === 0.
      // Main will change cell 0 -> 7 and Atomics.notify. wait() returns:
      //   "ok"        -> we were blocked and main's notify woke us
      //   "not-equal" -> cell already != 0 when we called wait (main changed it
      //                  first) -> the value change IS the signal, no block
      //   "timed-out" -> failsafe (must NOT happen: main always signals)
      // Record the outcome code + the value observed AFTER waking into the SAB.
      const RESULT = 1; // slot for wait() outcome code (1=ok, 2=not-equal, 3=timed-out)
      const SEEN = 2; // slot for the value observed after waking
      const res = Atomics.wait(view, SLOT_VALUE, 0, 5000);
      let code: number;
      if (res === "ok") code = 1;
      else if (res === "not-equal") code = 2;
      else code = 3; // "timed-out"
      Atomics.store(view, RESULT, code);
      Atomics.store(view, SEEN, Atomics.load(view, SLOT_VALUE));
      return;
    }
    default: {
      // Exhaustiveness guard: if a new job kind is added to WorkerJob without a
      // case, this line becomes a compile error (TS narrows `job` to `never`).
      const _exhaustive: never = job;
      void _exhaustive;
      return;
    }
  }
}

// ============================================================================
// main-thread helpers
// ============================================================================

// spawnWorkerExit spawns one worker with the given job (the SharedArrayBuffer is
// passed via workerData — shared, not copied) and resolves with its exit code
// once it joins. The worker writes its results into the SAB; main reads them
// after join. No message is exchanged — the SAB IS the channel.
function spawnWorkerExit(job: WorkerJob): Promise<number> {
  return new Promise((resolve, reject) => {
    const w = new Worker(__filename, { workerData: job });
    w.on("exit", (code: number) => resolve(code));
    w.on("error", (err: Error) => reject(err));
  });
}

// ============================================================================
// Section A — SharedArrayBuffer is SHARED (not copied); worker write visible
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — SharedArrayBuffer is SHARED (not copied): worker write visible to main");

  // A SharedArrayBuffer is a fixed-length block of RAW bytes, sharable across
  // threads. A typed-array VIEW (Int32Array) overlays it: reads/writes go to the
  // shared backing memory. byteLength is in BYTES; Int32Array.BYTES_PER_ELEMENT
  // === 4, so 8 int32 slots == 32 bytes.
  const byteLen = Int32Array.BYTES_PER_ELEMENT * 8;
  const sab = new SharedArrayBuffer(byteLen);
  const view = new Int32Array(sab);

  console.log("SharedArrayBuffer + Int32Array view (created on MAIN):");
  console.log(`  sab.byteLength          === ${sab.byteLength}`);
  console.log(`  view.length             === ${view.length}   (32 bytes / 4 per int32)`);
  console.log(`  view[SLOT_VALUE] before === ${view[SLOT_VALUE] ?? 0}`);
  check("sab.byteLength === 32 (8 int32 slots * 4 bytes)", sab.byteLength === 32);
  check("view.length === 8", view.length === 8);

  // Spawn ONE worker. The SAB travels via workerData; structured clone SHARES it
  // (the worker's SAB is the SAME backing memory as main's). The worker writes
  // 42 into slot 0 with a PLAIN write. After it joins, main reads 42 — no copy,
  // no message. THE HEADLINE: a worker write to SAB is visible to main.
  const WRITE_VAL = 42;
  const exit = await spawnWorkerExit({ kind: "write-shared", sab, idx: SLOT_VALUE, val: WRITE_VAL });
  const seen = view[SLOT_VALUE] ?? 0;

  console.log("");
  console.log("Worker wrote view[0] = 42 into the SAME buffer (passed via workerData):");
  console.log(`  main reads view[0]      === ${seen}   (visible: shared memory, NO copy)`);
  console.log(`  worker exited code       ${exit}`);
  check("worker write to SAB is VISIBLE to main (view[0] === 42)", seen === WRITE_VAL);
  check("worker exited code 0", exit === 0);

  // THE CONTRAST with ArrayBuffer (deep-dive: WORKER_THREADS §B/§C): a plain
  // ArrayBuffer is COPIED on postMessage (or, if listed in transferList, its
  // ownership MOVES and the sender's is DETACHED to byteLength 0). A
  // SharedArrayBuffer is neither copied nor detached — main's reference stays
  // valid and points at the SAME bytes the worker mutated.
  console.log("");
  console.log("After passing the SAB to a worker, main's reference is STILL valid:");
  console.log(`  sab.byteLength still    === ${sab.byteLength}   (NOT detached — SAB is shared)`);
  check("main's SAB is NOT detached after passing (byteLength still 32)", sab.byteLength === 32);
}

// ============================================================================
// Section B — the DATA RACE: plain (non-atomic) += loses updates
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — the DATA RACE: plain (non-atomic) += loses updates (nondeterministic)");

  const N = 4; // workers
  const ITERS = 1000; // increments per worker
  const EXPECTED = N * ITERS; // 4000 — what a CORRECT counter would reach

  // Each worker does `view[0] += 1` ITERS times with PLAIN writes. Because `+= 1`
  // is load+add+store (3 separate steps, NOT atomic), concurrent workers clobber
  // each other's stores -> LOST UPDATES. The final value is NONDETERMINISTIC.
  const sab = new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT * 4);
  const view = new Int32Array(sab);

  console.log(`Spawning ${N} workers; each does view[0] += 1 x ${ITERS} with PLAIN writes:`);
  console.log("  (plain += is load+add+store — NOT atomic; concurrent stores clobber)");
  const exits = await Promise.all(
    Array.from({ length: N }, () => spawnWorkerExit({ kind: "race-plain", sab, iters: ITERS })),
  );

  // Read the racy total. The workers have all JOINED, so a single read here is
  // safe. (Atomics.load for clarity; a plain read would also be fine post-join.)
  const racy = Atomics.load(view, SLOT_VALUE);

  console.log("");
  console.log(`Expected (CORRECT counter): ${EXPECTED}`);
  console.log(`Plain-write race final value: NONDETERMINISTIC (lost updates) — bounded in [0, ${EXPECTED}]`);
  console.log("  (exact value NOT printed: it varies per run — run `just run` again to see it change)");

  // DETERMINISTIC bounds (hold for EVERY run, so output stays byte-identical):
  // the racy total can NEVER exceed EXPECTED (each of the N*ITERS increments
  // lands at most once; lost updates only reduce it) and can never go below 0
  // (starts at 0, only increments). We deliberately do NOT assert the exact racy
  // value — it is the definition of a data race.
  check(`racy total <= N*iters (never exceeds a correct counter, ${EXPECTED})`, racy <= EXPECTED);
  check("racy total >= 0 (starts at 0, only increments)", racy >= 0);
  check(`all ${N} racy workers exited code 0`, exits.every((c) => c === 0) && exits.length === N);
}

// ============================================================================
// Section C — Atomics.add/load/store (DETERMINISTIC) + compareExchange (CAS)
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — Atomics.add/load/store (deterministic) + compareExchange (CAS)");

  const N = 4;
  const ITERS = 1000;
  const EXPECTED = N * ITERS; // 4000

  // --- Part 1: Atomics.add is an atomic read-modify-write. N workers each add
  // 1 ITERS times. Because add is INDIVISIBLE, NO update is lost -> the final
  // total is EXACTLY N*ITERS, every run. THIS is the payoff that fixes the
  // Section B race. -----------------------------------------------------------
  const sab = new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT * 4);
  const view = new Int32Array(sab);

  console.log(`Atomics.add — atomic read-modify-write (N=${N} workers x ${ITERS} adds each):`);
  const exits = await Promise.all(
    Array.from({ length: N }, () => spawnWorkerExit({ kind: "atomic-add", sab, iters: ITERS })),
  );
  const atomicTotal = Atomics.load(view, SLOT_VALUE);

  console.log(`  Expected (N*iters): ${EXPECTED}`);
  console.log(`  Atomics.add total : ${atomicTotal}   (EXACT — no lost updates, every run)`);
  check(`Atomics.add total === N*iters (${EXPECTED}, deterministic)`, atomicTotal === EXPECTED);
  check(`all ${N} atomic workers exited code 0`, exits.every((c) => c === 0) && exits.length === N);

  // --- Part 2: Atomics.store / Atomics.load — single-cell atomic ops with
  // cross-thread ordering (sequentially consistent by default). store returns
  // the value stored; load returns the current value. ------------------------
  console.log("");
  console.log("Atomics.store / Atomics.load — ordered single-cell ops:");
  const stored = Atomics.store(view, 1, 1234);
  const loaded = Atomics.load(view, 1);
  console.log(`  Atomics.store(view, 1, 1234) -> ${stored}   (returns the stored value)`);
  console.log(`  Atomics.load(view, 1)        -> ${loaded}`);
  check("Atomics.store returns the value stored (1234)", stored === 1234);
  check("Atomics.load reads back the stored value (1234)", loaded === 1234);

  // --- Part 3: Atomics.compareExchange — the CAS (compare-and-swap) primitive.
  // If view[idx] === expected, write `value` and return expected (the old). Else
  // do NOT write and return the current value. CAS is the building block for
  // every lock-free algorithm (mutexes, lock-free stacks, channels, ...).
  // Demonstrated on the MAIN thread (no race) so both arms are deterministic. --
  console.log("");
  console.log("Atomics.compareExchange — CAS (compare-and-swap):");

  // Success: cell starts at 5; CAS(expected=5, value=10). Old 5 === expected 5,
  // so the swap happens; returns the old value 5.
  Atomics.store(view, 2, 5);
  const casOk = Atomics.compareExchange(view, 2, 5, 10);
  const afterOk = Atomics.load(view, 2);
  console.log("  start view[2]=5; compareExchange(view,2, expected=5, value=10)");
  console.log(`    -> returned ${casOk} (old matched expected -> SWAPPED), view[2] now ${afterOk}`);
  check("CAS success: returned old (5) when expected matched", casOk === 5);
  check("CAS success: cell updated to 10", afterOk === 10);

  // Failure: cell is now 10; CAS(expected=5, value=99). Current 10 !== 5, so NO
  // swap; returns the current value 10; cell stays 10.
  const casFail = Atomics.compareExchange(view, 2, 5, 99);
  const afterFail = Atomics.load(view, 2);
  console.log("  start view[2]=10; compareExchange(view,2, expected=5, value=99)");
  console.log(`    -> returned ${casFail} (old != expected -> NO swap), view[2] still ${afterFail}`);
  check("CAS failure: returned current (10) when expected did NOT match", casFail === 10);
  check("CAS failure: cell UNCHANGED (still 10, no write)", afterFail === 10);
}

// ============================================================================
// Section D — Atomics.wait / Atomics.notify (futex-like synchronization)
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — Atomics.wait / Atomics.notify (futex-like synchronization)");

  // Atomics.wait blocks the CALLING thread until notified (or the cell's value
  // differs from the expected, or a timeout elapses). Browsers FORBID wait on
  // the main thread (it throws TypeError — the main thread cannot block); Node
  // technically allows it but doing so BLOCKS the event loop (EVENT_LOOP), which
  // is almost always wrong. So the idiom is: a WORKER waits, MAIN (or another
  // worker) notifies. This bundle follows the idiom.
  //
  // Deterministic handoff via the CONDITION-VARIABLE pattern: the worker waits
  // while cell 0 === 0; main STORES a new value (0 -> 7) then NOTIFYs. Two valid
  // outcomes, BOTH a correct handoff:
  //   "ok"        — worker was blocked; main's notify woke it.
  //   "not-equal" — worker hadn't waited yet; when it called wait, cell != 0, so
  //                 wait returned immediately (the value change IS the signal).
  // In BOTH cases the worker proceeds and OBSERVES the new value. A third,
  // "timed-out", is a failsafe that must NOT happen here.

  const sab = new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT * 4);
  const view = new Int32Array(sab);

  const NOTIFY_VAL = 7;
  const RESULT_IDX = 1; // worker writes its wait() outcome code here
  const SEEN_IDX = 2; // worker writes the value it observed after waking here

  console.log("Atomics.wait/notify handoff (worker waits on cell 0; main sets 7 + notifies):");
  console.log("  (browsers forbid wait on main; Node allows it but blocks the event loop -> WORKER waits)");

  // Spawn the waiter. It will Atomics.wait(view, 0, 0) — block while cell 0===0.
  const exitP = spawnWorkerExit({ kind: "waiter", sab });

  // Give the worker a moment to reach Atomics.wait. The handoff is correct
  // REGARDLESS of timing (value-change + notify), so this introduces NO
  // flakiness — it just biases toward the "ok" (woken-by-notify) path. The
  // Promise.race resolves at 30ms (the worker is blocked, so it won't exit first).
  await Promise.race([exitP, new Promise<void>((r) => setTimeout(r, 30))]);

  // Change the condition (0 -> 7), then wake any waiter.
  Atomics.store(view, SLOT_VALUE, NOTIFY_VAL);
  const woken = Atomics.notify(view, SLOT_VALUE, 1);

  const exit = await exitP;

  const code = Atomics.load(view, RESULT_IDX);
  const seen = Atomics.load(view, SEEN_IDX);

  console.log("  main: Atomics.store(view, 0, 7) then Atomics.notify(view, 0, 1)");
  console.log(`  worker observed view[0] === ${seen} after waking (handoff OK)`);
  console.log(`  worker exit code: ${exit}`);
  // DETERMINISTIC: regardless of the "ok" vs "not-equal" path, the worker always
  // observes main's new value (7) and never times out. The exact wake path and
  // notify count are timing-dependent, so we assert only the guaranteed outcome.
  check("wait/notify handoff: worker observed main's value (7)", seen === NOTIFY_VAL);
  check("wait/notify handoff: worker did NOT time out (wait returned ok or not-equal)", code === 1 || code === 2);
  check("waiter worker exited code 0", exit === 0);
  // Atomics.notify always returns a non-negative count (0 if no one was waiting
  // yet, 1 if the waiter was blocked). The exact count is timing-dependent.
  check("Atomics.notify returned a non-negative count (spec guarantee)", woken >= 0);
}

// ============================================================================
// Section E — memory ordering (seq-consistent default) + cross-language
// ============================================================================

function sectionE(): void {
  sectionBanner("E — memory ordering (sequentially consistent by default) + cross-language");

  // THE JS MEMORY MODEL: Atomics operations are SEQUENTIALLY CONSISTENT by
  // default — the STRONGEST ordering. Every thread agrees on a single total
  // order of all atomic ops, and no plain read/write can be reordered around an
  // atomic op in a way visible across threads. (Rust forces you to CHOOSE the
  // ordering — SeqCst/Acquire/Release/Relaxed; JS spares you the choice by
  // always using the strongest, at some performance cost.)
  //
  // Plain (non-atomic) reads/writes have NO cross-thread ordering guarantee —
  // that is precisely the Section B data race. The fix is ALWAYS Atomics.

  const sab = new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT * 4);
  const view = new Int32Array(sab);

  // The Atomics API surface. Every RMW op returns the OLD value (letting you
  // build lock-free algorithms on compareExchange + add).
  console.log("The Atomics API surface (all seq-consistent; RMW ops return the OLD value):");
  const api: ReadonlyArray<readonly [string, string]> = [
    ["Atomics.load(ta, i)", "atomic read (ordered)"],
    ["Atomics.store(ta, i, v)", "atomic write (ordered); returns v"],
    ["Atomics.add(ta, i, v)", "atomic RMW; returns OLD value"],
    ["Atomics.sub(ta, i, v)", "atomic RMW; returns OLD value"],
    ["Atomics.and/or/xor(ta, i, v)", "atomic bitwise RMW; returns OLD"],
    ["Atomics.exchange(ta, i, v)", "atomic swap; returns OLD value"],
    ["Atomics.compareExchange(ta, i, e, v)", "CAS; returns OLD (swaps only if old===e)"],
    ["Atomics.wait(ta, i, v, t?)", "block while ta[i]===v (futex); worker-side"],
    ["Atomics.notify(ta, i, count)", "wake up to count waiters; returns # woken"],
    ["Atomics.isLockFree(n)", "true if size-n ops are hardware-atomic"],
  ];
  for (const [sig, desc] of api) {
    console.log(`  ${sig.padEnd(34)} ${desc}`);
  }

  // add returns the OLD value (observed here on main, sequentially):
  Atomics.store(view, 0, 100);
  const oldBeforeAdd = Atomics.add(view, 0, 5); // returns 100 (old); cell now 105
  const afterAdd = Atomics.load(view, 0);
  console.log("");
  console.log("Atomics.add returns the OLD value (atomic read-modify-write):");
  console.log(`  store(view,0,100); add(view,0,5) -> returned ${oldBeforeAdd}; cell now ${afterAdd}`);
  check("Atomics.add returns the OLD value (100)", oldBeforeAdd === 100);
  check("cell is now 105 after the add", afterAdd === 105);

  // exchange: atomic swap, returns the OLD value.
  const oldEx = Atomics.exchange(view, 0, 999);
  console.log(`  exchange(view,0,999) -> returned ${oldEx} (old); cell now ${Atomics.load(view, 0)}`);
  check("Atomics.exchange returns OLD (105) and swaps to 999", oldEx === 105 && Atomics.load(view, 0) === 999);

  // isLockFree: int32 (size-4) ops are hardware-atomic on every mainstream V8.
  const lockFree = Atomics.isLockFree(4);
  console.log(`  Atomics.isLockFree(4) -> ${lockFree}   (int32 ops are natively atomic in V8)`);
  check("Atomics.isLockFree(4) === true (int32 is natively atomic)", lockFree === true);

  // The headline cross-language contrast: the SAME shared-memory concurrency
  // model, three surface syntaxes. JS hides the ordering choice; Go and Rust
  // expose it (Rust makes it a compile-time parameter).
  console.log("");
  console.log("Cross-language — shared-memory concurrency primitives:");
  const xlang: ReadonlyArray<readonly [string, string]> = [
    ["JS SharedArrayBuffer + Atomics", "shared mem; Atomics seq-consistent by default (no ordering choice)"],
    ["Go sync/atomic", "atomic Int32/Pointer/Uintptr + CAS; explicit happens-before memory model"],
    ["Rust std::sync::atomic", "AtomicUsize etc.; you MUST pick Ordering (SeqCst/Acq/Rel/Relaxed)"],
  ];
  for (const [lang, model] of xlang) {
    console.log(`  ${lang.padEnd(30)} : ${model}`);
  }
  check("all three languages model shared-memory atomics (3 rows)", xlang.length === 3);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("shared_memory_atomics.ts — Phase 4 bundle (core member).");
  console.log("SharedArrayBuffer is the ONLY shared-memory primitive in JS. Workers write to");
  console.log("the SAB (NEVER print); main reads after all join. Atomics make the results");
  console.log("DETERMINISTIC; plain writes DATA-RACE. Nothing is hand-computed.");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

// === THE __filename SELF-WORKER BRANCH ======================================
// This file runs in BOTH roles. Worker role: dispatch to runWorker() and return
// (the worker exits naturally once its event loop drains). Main role: drive
// main() and surface any thrown invariant as a non-zero exit.
if (!isMainThread) {
  runWorker();
} else {
  void main().catch((err: unknown) => {
    console.error(err);
    process.exitCode = 1;
  });
}
