// async_patterns.ts — Phase 7 bundle (Async Runtime, HTTP & Realtime).
//
// GOAL (one line): show, by printing every value, the async PATTERNS real apps
// compose on top of raw promises — AsyncLocalStorage (request-scoped CONTEXT
// that propagates across awaits WITHOUT a parameter, the JS analog of Go's
// context.Context), a bounded backpressure queue, async iterables as streams,
// EventEmitter fan-out, a bounded worker pool, debounce/throttle, and an async
// mutex — all deterministic (step-counts not ms; sorted parallel output).
//
// This is the GROUND TRUTH for ASYNC_PATTERNS.md. Every number, ordering, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it goes DEEPER on than its siblings):
// PROMISES (P4) showed a Promise is an async VALUE; ASYNC_AWAIT (P4) showed the
// syntax layer; CONCURRENCY_PATTERNS (P4) owned the BASICS — the limit(n) pool,
// AbortController/AbortSignal cancellation, an UNBOUNDED async queue, an async
// mutex, and retry. THIS bundle (P7) is the PRODUCTION-ASYNC layer built on top:
//   - AsyncLocalStorage (node:async_hooks): request-scoped context that survives
//     `await` — log a reqId deep in a call tree WITHOUT threading it through
//     every signature. THE PAYOFF, and the JS analog of Go's context.Context.
//     We pin: the store is visible across awaits, ISOLATED per request (two
//     interleaved requests each see their OWN id), and undefined outside run().
//   - the "lost context" problem ALS solves: a plain GLOBAL "context" is CLOB-
//     BERED under concurrency (request A sees request B's id after an await);
//     ALS is implicit-but-safe (unlike globals which break under concurrency).
//   - a BOUNDED queue with BACKPRESSURE: push() AWAITS when the buffer is full
//     (capacity N) — the producer is suspended until a consumer drains a slot.
//     (🔗 CONCURRENCY_PATTERNS had an UNBOUNDED queue; this adds the HWM gate.)
//   - async iterables as STREAMS: async function* + for-await...of, and the
//     duck-typed async-iterator protocol ([Symbol.asyncIterator] -> .next()).
//     (🔗 ITERATORS_GENERATORS owns the SYNC side; this is the async side.)
//   - EventEmitter fan-out (recap): N listeners fire SYNCHRONOUSLY on one emit,
//     in registration order; once() auto-removes. (🔗 CONCURRENCY_PATTERNS owns
//     the deep version incl. the throw/leak traps.)
//   - a bounded WORKER POOL draining a queue (compose limit(n) + the queue).
//   - debounce (coalesce a burst -> 1) and throttle (rate-limit) — driven by a
//     DETERMINISTIC virtual clock (no real timers -> byte-identical output).
//   - an async MUTEX serializing async sections (no two overlap).
//
// Run:
//     pnpm exec tsx async_patterns.ts   (or: just run async_patterns)

import { AsyncLocalStorage } from "node:async_hooks";
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

// tick yields exactly one microtask round — used to flush pending continuations
// (resolved-promise .then handlers, async-section resumes) deterministically.
// We use this INSTEAD of real timers (setTimeout) so output is byte-identical.
const tick = (): Promise<void> => Promise.resolve();

// ============================================================================
// Reusable async primitives (module-level; used by several sections)
// ============================================================================

// AsyncQueue — a producer/consumer queue. BOUNDED: push() SUSPENDS the producer
// when the buffer is at capacity (backpressure); next() awaits when empty.
// close() resolves waiting consumers with `undefined` (a sentinel) so a pool of
// workers can drain until exhausted. The JS analog of Go's buffered channel and
// Rust's tokio mpsc (🔗 ../rust/TOKIO_CHANNELS.md).
class AsyncQueue<T> {
  private buffered: T[] = [];
  private readonly pushWaiters: Array<() => void> = [];
  private readonly pullWaiters: Array<(v: T | undefined) => void> = [];
  private closed = false;
  constructor(private readonly capacity: number = Number.POSITIVE_INFINITY) {}

  async push(v: T): Promise<void> {
    // Hand a waiting consumer the value directly, if any.
    const puller = this.pullWaiters.shift();
    if (puller !== undefined) {
      puller(v);
      return;
    }
    // Room in the buffer -> enqueue immediately (no suspension).
    if (this.buffered.length < this.capacity) {
      this.buffered.push(v);
      return;
    }
    // FULL -> suspend the producer until a consumer frees a slot (backpressure).
    await new Promise<void>((resolve) => {
      this.pushWaiters.push(resolve);
    });
    this.buffered.push(v);
  }

  async next(): Promise<T | undefined> {
    if (this.buffered.length > 0) {
      const v = this.buffered.shift() as T; // length > 0 guarantees a value
      this.freeSlot(); // resume a blocked producer now that a slot opened
      return v;
    }
    if (this.closed) return undefined; // sentinel: queue drained + closed
    // EMPTY -> park the consumer until a producer pushes (or close() fires).
    return new Promise<T | undefined>((resolve) => {
      this.pullWaiters.push(resolve);
    });
  }

  private freeSlot(): void {
    const pusher = this.pushWaiters.shift();
    if (pusher !== undefined) pusher(); // producer resumes and enqueues its value
  }

  close(): void {
    this.closed = true;
    let w = this.pullWaiters.shift();
    while (w !== undefined) {
      w(undefined); // release each parked consumer with the sentinel
      w = this.pullWaiters.shift();
    }
  }

  get size(): number {
    return this.buffered.length;
  }
}

// drainQueue — a bounded WORKER POOL draining a queue: spawn `limit` workers,
// each looping `next()` until the queue closes (sentinel). Tracks max-in-flight
// to prove the concurrency cap holds. Composes limit(n) + the queue.
async function drainQueue<T>(
  queue: AsyncQueue<T>,
  limit: number,
  process: (x: T) => Promise<void>,
): Promise<{ maxInFlight: number }> {
  let active = 0;
  let maxInFlight = 0;
  async function worker(): Promise<void> {
    for (;;) {
      const item = await queue.next();
      if (item === undefined) break; // queue closed and drained
      active += 1;
      if (active > maxInFlight) maxInFlight = active;
      await process(item);
      active -= 1;
    }
  }
  await Promise.all(Array.from({ length: limit }, () => worker()));
  return { maxInFlight };
}

// VirtualClock — a DETERMINISTIC scheduler (no real timers). debounce/throttle
// are timing functions; to keep output byte-identical we advance a virtual clock
// in fixed steps instead of relying on wall-clock setTimeout. setTimeout returns
// an id; clearTimeout cancels. advance(ms) runs every due timer in time order.
class VirtualClock {
  private _now = 0;
  private readonly timers = new Map<number, { at: number; fn: () => void }>();
  private nextId = 1;

  get now(): number {
    return this._now;
  }

  setTimeout(fn: () => void, ms: number): number {
    const id = this.nextId++;
    this.timers.set(id, { at: this._now + ms, fn });
    return id;
  }

  clearTimeout(id: number): void {
    this.timers.delete(id);
  }

  advance(ms: number): void {
    const target = this._now + ms;
    this._now = target;
    const due = [...this.timers.entries()]
      .filter(([, t]) => t.at <= target)
      .sort((a, b) => a[1].at - b[1].at);
    for (const [id, t] of due) {
      this.timers.delete(id);
      t.fn();
    }
  }
}

// makeDebounce — coalesce a burst of calls into ONE trailing call fired `wait`
// after the LAST call. Each call cancels the previous pending timer.
function makeDebounce(fn: (x: number) => void, wait: number, clock: VirtualClock): (x: number) => void {
  let timer: number | undefined;
  return (x: number) => {
    if (timer !== undefined) clock.clearTimeout(timer);
    timer = clock.setTimeout(() => {
      timer = undefined;
      fn(x);
    }, wait);
  };
}

// makeThrottle — rate-limit: fire on the LEADING edge, then at most once per
// `wait` window (a trailing call carries the last argument of the burst).
function makeThrottle(fn: (x: number) => void, wait: number, clock: VirtualClock): (x: number) => void {
  let last = Number.NEGATIVE_INFINITY;
  let timer: number | undefined;
  let pending: number | undefined;
  return (x: number) => {
    if (clock.now >= last + wait) {
      last = clock.now;
      fn(x); // leading edge — immediate
    } else {
      pending = x;
      if (timer !== undefined) clock.clearTimeout(timer);
      const delay = last + wait - clock.now;
      timer = clock.setTimeout(() => {
        timer = undefined;
        last = clock.now;
        if (pending !== undefined) {
          const p = pending;
          pending = undefined;
          fn(p); // trailing edge — the last call of the burst
        }
      }, delay);
    }
  };
}

// AsyncMutex — serializes ASYNC sections. JS is single-threaded so synchronous
// sections never overlap; but async sections (functions that await in the
// middle) CAN interleave at each await. The mutex makes them non-overlapping.
class AsyncMutex {
  private locked = false;
  private readonly waiters: Array<() => void> = [];

  async run<T>(fn: () => Promise<T>): Promise<T> {
    while (this.locked) {
      await new Promise<void>((resolve) => {
        this.waiters.push(resolve);
      });
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

// Two AsyncLocalStorage instances: one carrying a Map (rich context), one a
// plain string (a request id). Each instance is an INDEPENDENT context.
const ctxMap = new AsyncLocalStorage<Map<string, string>>();
const ctxStr = new AsyncLocalStorage<string>();

// ============================================================================
// Section A — AsyncLocalStorage: request-scoped context across awaits (THE
// payoff; ⟷ Go context.Context) + the "lost context" problem it solves.
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — AsyncLocalStorage: request-scoped context across awaits");

  // --- THE payoff: the store is visible across awaits, then gone outside run -
  // run(store, cb) sets the store for cb AND every async operation cb starts;
  // continuations after `await` STILL see it. Outside run() it is undefined.
  const trace: string[] = [];
  const inner = ctxMap.run(new Map([["reqId", "r-1"]]), () => {
    trace.push(`in run():       reqId=${ctxMap.getStore()?.get("reqId") ?? "undefined"}`);
    // Start an async chain INSIDE run(); its continuations run AFTER run()
    // returns, but the store propagates to them (the whole point of ALS).
    return (async () => {
      await tick();
      trace.push(`after await #1: reqId=${ctxMap.getStore()?.get("reqId") ?? "undefined"}`);
      await tick();
      trace.push(`after await #2: reqId=${ctxMap.getStore()?.get("reqId") ?? "undefined"}`);
    })();
  });
  await inner; // settle the async chain
  trace.push(`after run ret'd: reqId=${ctxMap.getStore()?.get("reqId") ?? "undefined"}`);

  console.log("AsyncLocalStorage — the store propagates across awaits, isolates outside run():");
  for (const line of trace) console.log(`  ${line}`);
  check("ALS store is visible INSIDE run() (reqId === r-1)", trace[0] === "in run():       reqId=r-1");
  check("...and SURVIVES the first await (still r-1)", trace[1] === "after await #1: reqId=r-1");
  check("...and SURVIVES the second await (still r-1)", trace[2] === "after await #2: reqId=r-1");
  check("...and is undefined OUTSIDE run() (context exited)", trace[3] === "after run ret'd: reqId=undefined");

  // --- THE "lost context" problem: a GLOBAL is clobbered under concurrency ---
  // Without ALS you would either thread reqId through EVERY function signature
  // (the old way) or stash it in a global. A global is UNSAFE: two interleaved
  // requests share it, so after an `await` request A may see request B's id.
  let globalReqId = "";
  const globalResult: Array<{ req: string; saw: string }> = [];
  const handleGlobal = async (id: string): Promise<void> => {
    globalReqId = id; // set the "context"
    await tick(); // yield — another request can clobber globalReqId here
    globalResult.push({ req: id, saw: globalReqId });
  };
  await Promise.all([handleGlobal("A"), handleGlobal("B")]);
  globalResult.sort((a, b) => a.req.localeCompare(b.req));

  console.log("");
  console.log("The LOST-CONTEXT problem — a plain GLOBAL is clobbered under concurrency:");
  for (const r of globalResult) console.log(`  request ${r.req} saw globalReqId=${r.saw}`);
  check(
    "GLOBAL context is UNSAFE: request A saw request B's id (clobbered at the await)",
    globalResult[0]?.req === "A" && globalResult[0]?.saw === "B",
  );

  // --- ALS is the SAFE fix: each request gets its own isolated store ---------
  const alsResult: Array<{ req: string; saw: string }> = [];
  const handleAls = (id: string): Promise<void> =>
    ctxStr.run(id, async () => {
      await tick(); // yield — but this request's store is its OWN, never shared
      alsResult.push({ req: id, saw: ctxStr.getStore() ?? "none" });
    });
  await Promise.all([handleAls("A"), handleAls("B")]);
  alsResult.sort((a, b) => a.req.localeCompare(b.req));

  console.log("");
  console.log("AsyncLocalStorage FIX — each request sees its OWN id (no clobbering):");
  for (const r of alsResult) console.log(`  request ${r.req} saw ALS store=${r.saw}`);
  check("ALS is SAFE: request A saw its OWN id (A)", alsResult[0]?.req === "A" && alsResult[0]?.saw === "A");
  check("...and request B saw its OWN id (B)", alsResult[1]?.req === "B" && alsResult[1]?.saw === "B");
}

// ============================================================================
// Section B — Bounded queue with BACKPRESSURE + async iterables as streams
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — Bounded queue with BACKPRESSURE + async iterables as streams");

  // --- async iterables as streams: async function* + for-await...of ----------
  async function* numberStream(count: number): AsyncGenerator<number> {
    for (let i = 1; i <= count; i++) {
      await tick(); // simulate an async gap (a tick), no real timer
      yield i * 10;
    }
  }
  const stream: number[] = [];
  for await (const v of numberStream(4)) stream.push(v);
  console.log("for-await over an async generator (async function*):");
  console.log(`  for await (v of numberStream(4)) -> [${stream.join(",")}]`);
  check("async generator yields values via for-await ([10,20,30,40])", stream.join(",") === "10,20,30,40");

  // --- the duck-typed async-iterator protocol ([Symbol.asyncIterator]) -------
  // for-await looks up [Symbol.asyncIterator]() and calls .next() -> Promise<
  // {value, done}>. Any object satisfying this contract is an async iterable.
  function rangeAsync(from: number, to: number): AsyncIterable<number> {
    return {
      [Symbol.asyncIterator]() {
        let cur = from;
        return {
          next(): Promise<IteratorResult<number>> {
            if (cur > to) {
              return Promise.resolve({ value: undefined, done: true } as IteratorResult<number>);
            }
            const value = cur++;
            return Promise.resolve({ value, done: false });
          },
        };
      },
    };
  }
  const ranged: number[] = [];
  for await (const v of rangeAsync(5, 7)) ranged.push(v);
  console.log("");
  console.log("duck-typed async iterable ([Symbol.asyncIterator]() -> .next()):");
  console.log(`  for await (v of rangeAsync(5,7)) -> [${ranged.join(",")}]`);
  check("custom async iterable yields [5,6,7]", ranged.join(",") === "5,6,7");

  // --- BOUNDED queue with BACKPRESSURE (producer SUSPENDS when full) ---------
  const q = new AsyncQueue<string>(2);
  await q.push("a");
  await q.push("b"); // buffer now FULL (capacity 2)
  const blocked = q.push("c"); // full -> producer SUSPENDED (promise pending)
  const probe = { resolved: false };
  blocked.then(() => {
    probe.resolved = true;
  });
  await tick(); // flush microtasks — `blocked` must still be pending
  console.log("");
  console.log("Bounded queue (capacity 2) — producer SUSPENDS when the buffer is full:");
  console.log(`  push('a'), push('b') buffer it; push('c') on a FULL queue -> promise ${probe.resolved ? "resolved" : "PENDING (backpressure)"}`);
  check("push() on a FULL bounded queue is BLOCKED (promise still pending)", probe.resolved === false);
  check("...buffer held at capacity 2 while the producer waits", q.size === 2);

  const first = await q.next(); // drains 'a' -> frees a slot -> unblocks producer
  await tick(); // let the blocked producer's continuation push 'c'
  check("next() returns the head FIFO ('a')", first === "a");
  check("...freeing a slot RESOLVES the blocked producer", probe.resolved === true);

  const second = await q.next();
  const third = await q.next();
  check("consumer receives items IN ORDER [a,b,c]", first === "a" && second === "b" && third === "c");
  console.log(`  consumed in order -> [${first},${second},${third}]`);
}

// ============================================================================
// Section C — EventEmitter fan-out (recap) + bounded worker pool draining a queue
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — EventEmitter fan-out (recap) + bounded worker pool draining a queue");

  // --- EventEmitter fan-out: synchronous dispatch to every registered listener
  const ee = new EventEmitter();
  const hits: string[] = [];
  ee.on("evt", () => hits.push("L1"));
  ee.on("evt", () => hits.push("L2"));
  ee.on("evt", () => hits.push("L3"));
  ee.emit("evt");
  console.log("EventEmitter fan-out — one emit, all listeners fire SYNCHRONOUSLY:");
  console.log(`  on('evt',L1); on('evt',L2); on('evt',L3); emit('evt') -> [${hits.join(",")}]`);
  check("EventEmitter fan-out: 3 listeners fire on one emit", hits.length === 3);
  check("...listeners fire in REGISTRATION order (L1,L2,L3)", hits.join(",") === "L1,L2,L3");
  check("emit() is synchronous — hits filled BEFORE the next line", hits.length === 3);

  // once: fires exactly once, then auto-removes itself.
  let onceCount = 0;
  ee.once("shot", () => onceCount++);
  ee.emit("shot");
  ee.emit("shot");
  check("once() fires exactly once across two emits", onceCount === 1);
  check("once() auto-removes its listener (listenerCount === 0 after firing)", ee.listenerCount("shot") === 0);

  ee.removeAllListeners();
  check("removeAllListeners() clears every event (listenerCount('evt') === 0)", ee.listenerCount("evt") === 0);

  // --- bounded worker pool (limit 2) draining a 6-item queue ----------------
  const q = new AsyncQueue<string>(Number.POSITIVE_INFINITY);
  for (const v of ["a", "b", "c", "d", "e", "f"]) await q.push(v);
  q.close();
  const collected: string[] = [];
  const { maxInFlight } = await drainQueue(q, 2, async (x) => {
    collected.push(x);
    await tick(); // yield so a second worker can run concurrently
  });
  collected.sort();
  console.log("");
  console.log("Bounded worker pool (limit 2) draining a 6-item queue:");
  console.log(`  consumed (sorted) -> [${collected.join(",")}]`);
  console.log(`  max in-flight     -> ${maxInFlight}`);
  check("pool drained all 6 items", collected.length === 6);
  check("pool respected the concurrency limit (max in-flight === 2)", maxInFlight === 2);
  check("...and consumed every item exactly once (no drops, no dups)", new Set(collected).size === 6);
}

// ============================================================================
// Section D — Debounce/throttle (coalesce/rate-limit) + async mutex
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — Debounce/throttle (coalesce/rate-limit) + async mutex");

  // --- debounce: coalesce a burst into ONE trailing call --------------------
  const clock = new VirtualClock();
  const debounced: number[] = [];
  const debounce = makeDebounce((x: number) => debounced.push(x), 100, clock);
  debounce(1);
  debounce(2);
  debounce(3); // a burst — each call cancels the previous pending timer
  clock.advance(99);
  const callsAt99 = debounced.length;
  check("debounce: a burst fires NOTHING before the quiet window elapses", callsAt99 === 0);
  clock.advance(1); // 100 total -> trailing call fires
  check("debounce: after the quiet window, exactly ONE call fires (coalesced)", debounced.length === 1);
  check("...and it fires with the LAST argument (3)", debounced[0] === 3);
  console.log("Debounce (wait 100) — a burst of 3 coalesces into 1 trailing call:");
  console.log(`  d(1);d(2);d(3); advance(99) -> ${callsAt99} call(s); advance(1) -> fired with ${debounced[0]} (total ${debounced.length})`);

  // --- throttle: leading edge fires now, then at most once per window -------
  const clock2 = new VirtualClock();
  const throttled: number[] = [];
  const throttle = makeThrottle((x: number) => throttled.push(x), 100, clock2);
  throttle(1); // t=0: leading edge -> fires immediately
  clock2.advance(10);
  throttle(2); // within window -> schedules a trailing call
  clock2.advance(10);
  throttle(3); // reschedules the trailing to carry the LAST arg
  clock2.advance(10);
  throttle(4); // reschedules again -> trailing will fire with 4
  check("throttle: leading edge fired immediately (1 call so far, arg 1)", throttled.length === 1 && throttled[0] === 1);
  clock2.advance(100); // window elapses -> trailing fires
  check("throttle: after the window, a trailing call fires (total 2)", throttled.length === 2);
  check("...trailing fires with the LAST argument of the burst (4)", throttled[1] === 4);
  console.log("");
  console.log("Throttle (window 100) — leading + trailing: a burst of 4 -> 2 calls:");
  console.log(`  t(1)@0 [leading]; t(2)@10; t(3)@20; t(4)@30; advance(100) -> fired [${throttled.join(",")}]`);

  // --- async mutex: serialize async sections (no two overlap) ---------------
  const mutex = new AsyncMutex();
  const trace: string[] = [];
  const taskA = mutex.run(async () => {
    trace.push("A-enter");
    await tick(); // yield here — WITHOUT the mutex, B could enter now
    trace.push("A-exit");
  });
  const taskB = mutex.run(async () => {
    trace.push("B-enter");
    await tick();
    trace.push("B-exit");
  });
  await Promise.all([taskA, taskB]);
  console.log("");
  console.log("Async mutex — two async sections run NON-overlapping (serialized):");
  console.log(`  trace -> [${trace.join(",")}]`);
  check(
    "mutex serializes: A finishes before B starts (no overlap)",
    trace.join(",") === "A-enter,A-exit,B-enter,B-exit",
  );
}

// ============================================================================
// Section E — Composing the patterns: ALS context across a concurrent pool
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — Composing the patterns: ALS context across a concurrent pool");

  // THE composition: a request-scoped ALS id is visible inside CONCURRENT pool
  // workers — no parameter threading. Each worker awaits (interleaves with the
  // others) yet still reads THIS request's store. This is exactly what makes
  // request-scoped logging/tracing work in a real server (⟷ Go context.Context
  // propagated down a call tree; 🔗 OBSERVABILITY propagates trace IDs this way).
  const ctxReq = new AsyncLocalStorage<string>();
  const seen: string[] = [];
  await ctxReq.run("req-7", async () => {
    const q = new AsyncQueue<string>(Number.POSITIVE_INFINITY);
    for (const t of ["t1", "t2", "t3", "t4", "t5"]) await q.push(t);
    q.close();
    await drainQueue(q, 2, async (label) => {
      await tick(); // yield — workers interleave, but ALS propagates
      seen.push(`${label}:${ctxReq.getStore() ?? "none"}`);
    });
  });
  seen.sort();
  console.log("ALS store visible inside concurrent pool workers (no parameter threading):");
  for (const s of seen) console.log(`  worker ${s}`);
  check(
    "every pool worker saw the request-scoped ALS id (req-7)",
    seen.length === 5 && seen.every((s) => s.endsWith(":req-7")),
  );
  check("ALS store is undefined OUTSIDE run() (context isolated)", ctxReq.getStore() === undefined);
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("async_patterns.ts — Phase 7 bundle (async runtime patterns).");
  console.log("Every value below is computed by this file; the .md guide pastes");
  console.log("it verbatim. All output is deterministic: step-counts not ms,");
  console.log("parallel results sorted, all async settled + listeners removed");
  console.log("before exit (process exits 0).");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

main().catch((e: unknown) => {
  console.error(e);
  process.exit(1);
});
