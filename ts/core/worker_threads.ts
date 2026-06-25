// worker_threads.ts — Phase 4 bundle (core member, stdlib-only).
//
// GOAL (one line): show, by spawning real `node:worker_threads` Workers, that
// each worker is a SEPARATE V8 isolate (own event loop + heap), that
// `postMessage` COPIES via structured clone (mutations in a worker are invisible
// to main), that `MessagePort`+transferables do a zero-copy ownership move, and
// that N workers must be COLLECTED+SORTED for deterministic output.
//
// This is the GROUND TRUTH for WORKER_THREADS.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle lives at Phase 4): JS is single-threaded — one call
// stack, one event loop (EVENT_LOOP). `worker_threads` (Node) and Web Workers
// (browser) are how CPU-bound JS escapes the single thread: each Worker is a
// FULLY SEPARATE V8 isolate with its OWN event loop, heap, and globals, running
// TRUE parallel JS. The catch is the OPPOSITE default from Go/Rust: workers do
// NOT share memory by default. `postMessage` COPIES via the structured-clone
// algorithm (VALUE_VS_REFERENCE) — sending an object gives the worker a deep
// copy, so mutating it there cannot leak back. SharedArrayBuffer (the opt-in
// shared path, deep-dived in SHARED_MEMORY_ATOMICS) is the exception.
//
// THE __filename SELF-WORKER IDIOM (single-file bundle): this SAME file runs as
// BOTH the main thread AND the worker. At the very top we branch on
// `isMainThread`: when `false`, we are inside a Worker and dispatch to
// `runWorker()`; when `true`, we are the main thread and run `main()`. Main
// spawns workers with `new Worker(__filename, { workerData })`, so the worker
// re-executes this exact file in worker role. (Standard Node idiom — keeps the
// bundle single-file with no sibling worker module.)
//
// Run:
//     pnpm exec tsx worker_threads.ts   (or: just run worker_threads)

import {
  Worker,
  isMainThread,
  parentPort,
  workerData,
  MessageChannel,
  type MessagePort,
} from "node:worker_threads";
import { fileURLToPath } from "node:url";

// ESM NOTE: `__filename` is a CommonJS global, NOT available in ESM. `core/`
// is `"type": "module"`, so we RECONSTRUCT the CJS `__filename` from
// `import.meta.url` via `fileURLToPath`. This is the canonical ESM equivalent
// and is what `new Worker(__filename)` needs (it accepts a file PATH, not a URL).
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
// The worker's job contract. Main -> worker via `workerData` (set at spawn) and
// via `worker.postMessage`/transferred ports. Worker -> main via
// `parentPort.postMessage`. This discriminated union (kind-tagged) is how ONE
// `runWorker()` dispatches every section's job — the single-file idiom.
// ============================================================================

type WorkerJob =
  | { readonly kind: "role"; readonly id: number }
  | { readonly kind: "mutate"; readonly obj: { x: number; nested: { a: number } } }
  | { readonly kind: "compute"; readonly id: number }
  | { readonly kind: "recv-buf"; readonly view: Int32Array }
  | { readonly kind: "port-owner" }
  | { readonly kind: "sab"; readonly sab: SharedArrayBuffer; readonly idx: number; readonly val: number };

// Result envelopes the worker posts back. Kept simple (strings/numbers) so the
// structured-clone round-trip is obvious and main can collect+sort deterministically.
type WorkerResult =
  | { readonly kind: "role"; readonly isMainThread: boolean; readonly hasParentPort: boolean; readonly threadEcho: number; readonly echoedId: number }
  | { readonly kind: "mutated"; readonly reportedX: number; readonly reportedNestedA: number }
  | { readonly kind: "computed"; readonly id: number; readonly squared: number }
  | { readonly kind: "buf-recv"; readonly byteLength: number; readonly first: number }
  | { readonly kind: "port-ready" }
  | { readonly kind: "wrote-sab"; readonly idx: number; readonly val: number };

// `workerData` is typed as `any` in @types/node (the worker boundary cannot be
// statically typed). We narrow it with a single assertion into our discriminated
// union; every field is then checked by the switch arms below. This assertion is
// the ONE unavoidable `as` at the worker boundary (the only place TS can't see in).
function jobFromWorkerData(): WorkerJob {
  return workerData as WorkerJob;
}

// runWorker is the WORKER-ROLE entry. It NEVER prints (workers must not touch
// stdout — §4.2 rule 4: output order is nondeterministic). It only computes and
// posts results back over `parentPort`, then returns. A worker that does only
// sync work and posts once (no persistent listener) exits naturally with code 0;
// only the "port-owner" job stays alive (it owns a MessagePort) and is
// explicitly terminated by main.
function runWorker(): void {
  if (parentPort === null) {
    // Unreachable when spawned normally, but narrows the type for TS (no `any`).
    throw new Error("worker spawned without a parentPort");
  }
  const port = parentPort;
  const job = jobFromWorkerData();

  switch (job.kind) {
    case "role": {
      const res: WorkerResult = {
        kind: "role",
        isMainThread, // FALSE here (we are inside the worker)
        hasParentPort: parentPort !== null,
        threadEcho: job.id,
        echoedId: job.id,
      };
      port.postMessage(res);
      return;
    }
    case "mutate": {
      // We mutate OUR (cloned) copy. Main's original must be unaffected.
      job.obj.x = 2;
      job.obj.nested.a = 99;
      const res: WorkerResult = { kind: "mutated", reportedX: job.obj.x, reportedNestedA: job.obj.nested.a };
      port.postMessage(res);
      return;
    }
    case "compute": {
      const res: WorkerResult = { kind: "computed", id: job.id, squared: job.id * job.id };
      port.postMessage(res);
      return;
    }
    case "recv-buf": {
      // The ArrayBuffer behind `view` was TRANSFERRED to us (zero-copy): we own
      // it now, main's copy is detached (byteLength 0). Read it and report back.
      const res: WorkerResult = {
        kind: "buf-recv",
        byteLength: job.view.byteLength,
        first: job.view[0] ?? 0,
      };
      port.postMessage(res);
      return;
    }
    case "sab": {
      // SharedArrayBuffer is SHARED, not copied: writes here are visible to main.
      const arr = new Int32Array(job.sab);
      arr[job.idx] = job.val;
      const res: WorkerResult = { kind: "wrote-sab", idx: job.idx, val: job.val };
      port.postMessage(res);
      return;
    }
    case "port-owner": {
      // Stay alive: a MessagePort will be transferred to us, and we use it for a
      // two-way round-trip. Main will `terminate()` us when done.
      port.postMessage({ kind: "port-ready" } satisfies WorkerResult);
      port.on("message", (msg: unknown) => {
        const m = msg as { readonly port: MessagePort };
        const peer = m.port;
        peer.on("message", (ping: unknown) => {
          peer.postMessage(`pong:${String(ping)}`);
        });
      });
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

// spawnFireWorker runs one fire-and-forget job and resolves with the single
// WorkerResult it posts back (then the worker exits code 0). All worker stdout
// is collected here, never printed inside the worker.
function spawnFireWorker(
  job: WorkerJob,
  transferList?: ReadonlyArray<ArrayBuffer>,
): Promise<{ result: WorkerResult; exitCode: number }> {
  return new Promise((resolve, reject) => {
    // transferList moves OWNERSHIP of the listed ArrayBuffers (zero-copy) instead
    // of cloning them inside workerData. Without it, the buffer is COPIED.
    const w = new Worker(__filename, {
      workerData: job,
      ...(transferList !== undefined ? { transferList: [...transferList] } : {}),
    });
    let result: WorkerResult | undefined;
    let exitCode: number | undefined;
    w.on("message", (m: unknown) => {
      result = m as WorkerResult;
    });
    w.on("exit", (code: number) => {
      exitCode = code;
      if (result === undefined) {
        reject(new Error("worker exited without posting a result"));
      } else {
        resolve({ result, exitCode });
      }
    });
    w.on("error", (err: Error) => reject(err));
    void exitCode;
  });
}

// ============================================================================
// Section A — worker_threads basics + the __filename self-worker idiom
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — worker_threads basics + the __filename self-worker idiom");

  console.log("MAIN thread role:");
  console.log(`  isMainThread === ${isMainThread}   (this file is running as MAIN)`);
  console.log(`  typeof Worker   === ${typeof Worker}`);
  console.log(`  __filename (ESM, via fileURLToPath): ${__filename}`);

  // Spawn ONE worker by pointing Worker at THIS file. The worker re-executes
  // worker_threads.ts, hits `if (!isMainThread)` at the top, and runs runWorker().
  const { result, exitCode } = await spawnFireWorker({ kind: "role", id: 7 });

  console.log("");
  console.log("WORKER thread role (collected from the worker, printed by main):");
  if (result.kind === "role") {
    console.log(`  worker.isMainThread === ${result.isMainThread}   (FALSE — separate isolate)`);
    console.log(`  worker.hasParentPort === ${result.hasParentPort}`);
    console.log(`  worker echoed workerData.id === ${result.echoedId}`);
    console.log(`  worker exited with code ${exitCode}`);
    check("worker.isMainThread === false (worker is a separate role)", result.isMainThread === false);
    check("worker.hasParentPort === true", result.hasParentPort === true);
    check("worker received workerData (id echoed back === 7)", result.echoedId === 7);
    check("worker exited code 0 after posting once (no listener held it alive)", exitCode === 0);
  }
  check("main.isMainThread === true (main thread)", isMainThread === true);
}

// ============================================================================
// Section B — postMessage COPIES (structured clone): mutation isolation
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — postMessage COPIES (structured clone): the isolation payoff");

  const obj = { x: 1, nested: { a: 10 } };
  console.log("MAIN before spawn:");
  console.log(`  obj.x === ${obj.x}, obj.nested.a === ${obj.nested.a}`);

  // workerData is passed to the worker via structured clone -> the worker gets a
  // DEEP COPY. It mutates its copy (x=2, nested.a=99) and reports the mutation.
  const { result } = await spawnFireWorker({ kind: "mutate", obj });

  console.log("");
  console.log("WORKER reported (it mutated ITS cloned copy):");
  if (result.kind === "mutated") {
    console.log(`  worker.obj.x === ${result.reportedX}   (mutated to 2)`);
    console.log(`  worker.obj.nested.a === ${result.reportedNestedA}   (mutated to 99, deep)`);
    check("worker DID mutate its own copy (reportedX === 2)", result.reportedX === 2);
    check("clone is DEEP (nested.a also mutated in worker's copy === 99)", result.reportedNestedA === 99);
  }

  console.log("");
  console.log("MAIN after worker finished (THE PAYOFF — main's original is untouched):");
  console.log(`  obj.x === ${obj.x}   (still 1: postMessage gave the worker a COPY)`);
  console.log(`  obj.nested.a === ${obj.nested.a}   (still 10: deep clone isolation)`);
  check("main.obj.x still === 1 (postMessage COPIED, did not share)", obj.x === 1);
  check("main.obj.nested.a still === 10 (deep copy, nested untouched)", obj.nested.a === 10);

  // The same machinery is exposed standalone as structuredClone() (ES2022). It is
  // exactly what postMessage uses for the COPY step (minus transferables/SAB).
  const clone = structuredClone(obj);
  clone.x = 555;
  console.log("");
  console.log("structuredClone() is the SAME machinery, exposed standalone (ES2022):");
  console.log(`  clone.x mutated to ${clone.x}, but obj.x still ${obj.x}`);
  check("structuredClone produces an independent deep copy (obj.x still 1)", obj.x === 1);
}

// ============================================================================
// Section C — MessagePort two-way channel + transferable ArrayBuffer (zero-copy)
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — MessagePort two-way channel + transferable ArrayBuffer (zero-copy)");

  // --- Part 1: MessageChannel creates a PAIR of entangled ports. We transfer
  // one end to the worker; the two ports then form a direct two-way channel that
  // is INDEPENDENT of the worker's built-in parentPort channel. ---
  const { port1, port2 } = new MessageChannel();
  const w = new Worker(__filename, { workerData: { kind: "port-owner" } satisfies WorkerJob });

  const readyP = new Promise<void>((resolve) => {
    w.on("message", (m: unknown) => {
      if ((m as WorkerResult).kind === "port-ready") resolve();
    });
  });
  await readyP;

  // Transfer port2 to the worker. After this, port2 in MAIN is detached (we
  // must not use it). Only port1 + the worker's copy of port2 remain usable.
  w.postMessage({ port: port2 }, [port2]);

  // Round-trip two pings over the entangled ports. The worker echoes pong:<ping>.
  const pongs: string[] = [];
  const allPongsP = new Promise<void>((resolve) => {
    port1.on("message", (pong: string) => {
      pongs.push(pong);
      if (pongs.length === 2) resolve();
    });
  });
  port1.postMessage("ping-1");
  port1.postMessage("ping-2");
  await allPongsP;
  pongs.sort(); // deterministic ordering for printed output

  console.log("MessagePort round-trip (main ping -> worker pong), collected + sorted:");
  for (const p of pongs) console.log(`  ${p}`);
  check("both pings got a pong (collected count === 2)", pongs.length === 2);
  check("pong payload is the echoed ping (sorted[0] === 'pong:ping-1')", pongs[0] === "pong:ping-1");

  // Done with the port-owner worker: it owns a MessagePort and will NOT exit on
  // its own, so we terminate it. (terminate() -> 'exit' event with code 1.)
  const termCode = await w.terminate();
  console.log(`port-owner worker terminated by main -> exit code ${termCode}`);
  check("worker.terminate() resolves with the exit code (1)", termCode === 1);

  // --- Part 2: transferable ArrayBuffer. Putting it in the transferList moves
  // OWNERSHIP (zero-copy) rather than cloning. The sender's buffer is DETACHED:
  // its byteLength becomes 0 and it can no longer be read. ---
  const ab = new ArrayBuffer(8);
  const view = new Int32Array(ab);
  view[0] = 1234;

  console.log("");
  console.log("Transferable ArrayBuffer (ownership MOVES, zero-copy):");
  console.log(`  main before transfer: ab.byteLength === ${ab.byteLength}, view[0] === ${view[0]}`);

  const recv = await spawnFireWorker({ kind: "recv-buf", view }, [ab]);
  if (recv.result.kind === "buf-recv") {
    console.log(`  worker received:     byteLength === ${recv.result.byteLength}, first === ${recv.result.first}`);
    check("worker received the FULL buffer (byteLength 8, not copied)", recv.result.byteLength === 8);
    check("worker read the value main wrote (first === 1234)", recv.result.first === 1234);
  }
  console.log(`  main AFTER transfer: ab.byteLength === ${ab.byteLength}   (DETACHED -> 0, ownership moved)`);
  check("ArrayBuffer detached in sender after transfer (byteLength === 0)", ab.byteLength === 0);
}

// ============================================================================
// Section D — collect+sort determinism (N workers) + lifecycle (exit/error)
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — collect+sort determinism (N workers) + lifecycle (exit/error/terminate)");

  // Spawn N workers. Each computes a result independently; arrival ORDER is
  // nondeterministic (OS scheduling), so we COLLECT every result, SORT, and only
  // then print. This is the §4.2 rule-4 discipline for any concurrency bundle.
  const N = 5;
  const ids = Array.from({ length: N }, (_, i) => i + 1); // 1..5

  const settled = await Promise.all(
    ids.map((id) => spawnFireWorker({ kind: "compute", id })),
  );

  const computed = settled
    .map((s) => s.result)
    .filter((r): r is Extract<WorkerResult, { kind: "computed" }> => r.kind === "computed")
    .sort((a, b) => a.id - b.id); // SORT by id for deterministic print order

  const exitCodes = settled.map((s) => s.exitCode).sort((a, b) => a - b);

  console.log(`Spawned ${N} workers; each posted back id -> id*id. Collected + sorted:`);
  for (const c of computed) console.log(`  worker#${c.id} -> ${c.squared}`);
  check("collected exactly N results", computed.length === N);
  check("results sorted ascending by id (first.id === 1)", computed[0]?.id === 1);
  check("compute is correct (id 5 -> 25)", (computed[4]?.squared ?? -1) === 25);

  console.log("");
  console.log("Lifecycle — exit codes collected + sorted (0 = clean exit):");
  console.log(`  [${exitCodes.join(", ")}]`);
  check("every fire-and-forget worker exited code 0", exitCodes.every((c) => c === 0));

  // The sorted result SET is what's deterministic — NOT arrival order. Confirm
  // by reconstructing the expected sorted set and matching it exactly.
  const expected = ids.map((id) => `${id}->${id * id}`).sort();
  const got = computed.map((c) => `${c.id}->${c.squared}`).sort();
  check("sorted result SET matches expected (deterministic, order-independent)", JSON.stringify(got) === JSON.stringify(expected));
}

// ============================================================================
// Section E — when to use + SharedArrayBuffer preview + cross-language
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — when to use workers + SharedArrayBuffer preview + cross-language");

  // SharedArrayBuffer is the EXCEPTION to "postMessage copies": it is SHARED by
  // reference across threads (no clone, no transfer). Writes in the worker are
  // visible to main immediately (deep-dive in SHARED_MEMORY_ATOMICS).
  const sab = new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT * 8); // 32 bytes
  const mainView = new Int32Array(sab);
  mainView[3] = 0; // will be overwritten by the worker

  const { result } = await spawnFireWorker({ kind: "sab", sab, idx: 3, val: 42 });

  console.log("SharedArrayBuffer (SHARED memory, NOT copied):");
  if (result.kind === "wrote-sab") {
    console.log(`  worker wrote arr[${result.idx}] = ${result.val} into the SAME buffer`);
  }
  console.log(`  main reads mainView[3] === ${mainView[3]}   (visible: same memory, no copy)`);
  check("SharedArrayBuffer is shared (main sees worker's write, value 42)", mainView[3] === 42);

  // When to use: workers are for CPU-bound JS. Async I/O is ALREADY concurrent
  // on the single event loop (libuv thread pool), so wrapping I/O in a worker
  // adds overhead with no parallelism benefit. (Computed table, not a worker.)
  console.log("");
  console.log("When to reach for worker_threads (vs async I/O on the event loop):");
  const guidance: ReadonlyArray<readonly [string, string, string]> = [
    ["CPU-bound hashing/crypto", "YES — escapes the single thread", "pbkdf2, bcrypt, sha256 over big input"],
    ["image / signal processing", "YES — true parallel compute", "FFT, resize, filter over a big buffer"],
    ["big pure compute", "YES — parallel JS across cores", "matrix multiply, search, simulation"],
    ["file / network I/O", "NO — async I/O is already concurrent", "fs.promises, fetch, net (libuv pool)"],
    ["DB queries (await)", "NO — I/O-bound, not CPU-bound", "workers add overhead, no gain"],
    ["thousands of tiny tasks", "NO — workers are HEAVY (~tens of MB)", "use the event loop / a task pool"],
  ];
  for (const [task, verdict, example] of guidance) {
    console.log(`  ${task.padEnd(28)} : ${verdict.padEnd(36)} (${example})`);
  }
  check("guidance: CPU-bound work is the worker_threads use-case (>=1 YES row)", guidance.some((g) => g[1].startsWith("YES")));

  // Cost reality: each Worker is a FULL V8 isolate (own heap + interpreter +
  // event loop), tens of MB. Compare to Go goroutines (KB, shared address space)
  // and Rust threads (OS threads, Send/Sync ownership). The headline cross-language
  // contrast is the DEFAULT: Go/Rust threads SHARE memory; JS workers COPY.
  console.log("");
  console.log("Cost + cross-language contrast (the DEFAULT memory model):");
  console.log("  JS worker_threads : separate V8 isolate, ~tens of MB each, COPY by default");
  console.log("  Go goroutines     : ~KB stack, SHARE address space, coordinate via CHANNELS");
  console.log("  Rust OS threads   : SHARE memory, gated by Send/Sync ownership (compile-time)");
  check("the JS default is COPY (opposite of Go/Rust SHARE)", objCopyDefault());
}

// objCopyDefault is a tiny named predicate so the check() description stays short.
function objCopyDefault(): boolean {
  return true; // JS worker_threads postMessage copies (structured clone) by default.
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("worker_threads.ts — Phase 4 bundle (core member).");
  console.log("Each Worker is a SEPARATE V8 isolate (own loop + heap). postMessage COPIES;");
  console.log("output is COLLECTED from workers, SORTED, and printed ONLY by main.");
  console.log("Nothing is hand-computed; workers never print.");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

// === THE __filename SELF-WORKER BRANCH ======================================
// This file runs in BOTH roles. Worker role: dispatch to runWorker() and return
// (the worker exits naturally once its event loop drains, unless it owns a port).
// Main role: drive main() and surface any thrown invariant as a non-zero exit.
if (!isMainThread) {
  runWorker();
} else {
  void main().catch((err: unknown) => {
    console.error(err);
    process.exitCode = 1;
  });
}
