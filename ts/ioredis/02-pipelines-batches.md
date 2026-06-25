# Pipelines & Batches: Round-Trip Amortization

**Doc Source**: [ioredis README — Pipelining](https://github.com/redis/ioredis#pipelining) · [Transaction](https://github.com/redis/ioredis#transaction)

## The Core Concept: Why This Example Exists

**The Problem:** Redis is blindingly fast at executing a single command (sub-microsecond). The bottleneck in almost any Redis-backed service is **network round-trip time (RTT)**, not the server. If your handler does `await redis.set(a)` then `await redis.set(b)` then `await redis.set(c)` on a 1 ms-RTT link, you spend ~3 ms waiting on the wire for ~3 µs of actual work — a 1000× waste. The naive `Promise.all([set(a), set(b), set(c)])` doesn't fully fix it either: ioredis still issues each command as a separate write syscall + waits for each reply.

**The Solution:** A **pipeline** batches N commands into a single write to the socket and reads all N replies back in one go — collapsing N round-trips into 1. The upstream README cites a 50%–300% throughput improvement for batches of >5 commands. ioredis exposes this as a fluent builder: `redis.pipeline().set(...).get(...).exec()` returns a `Promise` that resolves to an array of `[err, result]` tuples in submission order. This is the **same conceptual move** Rust's [`fred.rs`](../../rust/fred.rs/02-client-pools.md) makes when it hands you a single client off the pool for pipelining — both are about amortizing RTT, the only difference is *where* the amortization happens (ioredis: command batching; fred.rs pools: connection multiplexing).

> **Pipelines vs MULTI/EXEC (transactions).** A *pipeline* is purely a client-side network optimization — the commands are queued locally, flushed together, but Redis executes them back-to-back with **no atomicity guarantee**: another client's command can land in between. A *transaction* (`redis.multi(...).exec()`) wraps the same fluent API but issues `MULTI ... EXEC`, which makes the queued commands **atomic** (no interleaving) and optionally supports `WATCH`-based optimistic locking. See the note at the end of this file and the ioredis [Transaction](https://github.com/redis/ioredis#transaction) docs. This file covers the **non-transactional pipeline**.

## Practical Walkthrough: Code Breakdown

### Building a Pipeline Imperatively

`redis.pipeline()` returns a `Pipeline` object that accepts every command the parent `Redis` instance does — but instead of sending immediately, it queues. The flush happens when you call `.exec()`:

```javascript
const pipeline = redis.pipeline();
pipeline.set("foo", "bar");
pipeline.del("cc");
pipeline.exec((err, results) => {
  // `err` is always null, and `results` is an array of responses
  // corresponding to the sequence of queued commands.
  // Each response follows the format `[err, result]`.
});
```

*Source: [ioredis README — Pipelining](https://github.com/redis/ioredis#pipelining)*

The **results shape** is the part to internalize: `results` is an array, one entry per queued command, **in submission order** (not completion order — Redis processes the pipeline sequentially). Each entry is a `[err, result]` tuple:

- `err` is `null` unless *that specific command* failed (e.g., wrong type for `LPUSH`).
- `result` is the command's reply (`"OK"` for `SET`, count for `DEL`, etc.).
- The outer `err` callback argument is documented as **always null** — pipeline-level failures (e.g., the socket dropped mid-flush) reject the returned Promise instead.

This per-command `[err, result]` shape exists precisely because a pipeline is *not* a transaction: command #2 can fail while #1 and #3 succeed.

### Chaining + the Promise Form

The same `Pipeline` is chainable, and `.exec()` returns a Promise when you omit the callback — so in modern TS the pipeline reads top-to-bottom:

```javascript
// You can even chain the commands:
redis
  .pipeline()
  .set("foo", "bar")
  .del("cc")
  .exec((err, results) => {});

// `exec` also returns a Promise:
const promise = redis.pipeline().set("foo", "bar").get("foo").exec();
promise.then((result) => {
  // result === [[null, 'OK'], [null, 'bar']]
});
```

*Source: [ioredis README — Pipelining](https://github.com/redis/ioredis#pipelining)*

So `await redis.pipeline().set("foo", "bar").get("foo").exec()` resolves to `[[null, "OK"], [null, "bar"]]` — index 0 is the `SET` reply, index 1 is the `GET` reply.

### Per-Command Callbacks Inside the Chain

Each chained command can also take its own callback, fired when *that command's* reply arrives (still within the single round-trip):

```javascript
redis
  .pipeline()
  .set("foo", "bar")
  .get("foo", (err, result) => {
    // result === 'bar'
  })
  .exec((err, result) => {
    // result[1][1] === 'bar'
  });
```

*Source: [ioredis README — Pipelining](https://github.com/redis/ioredis#pipelining)*

This is occasionally useful (e.g., logging a specific sub-command), but in new code prefer collecting results from the `exec()` array — it's one `await` and keeps the control flow linear.

### The Array Constructor

If you already have commands as data (e.g., generated in a loop), pass a 2D array straight to the constructor:

```javascript
redis
  .pipeline([
    ["set", "foo", "bar"],
    ["get", "foo"],
  ])
  .exec(() => {
    /* ... */
  });
```

*Source: [ioredis README — Pipelining](https://github.com/redis/ioredis#pipelining)*

This is the form you reach for when warming a cache from a list, or when a `SCAN` cursor returns N keys you want to `GET` in one shot.

### Introspecting the Queue: `.length`

```javascript
const length = redis.pipeline().set("foo", "bar").get("foo").length;
// length === 2
```

*Source: [ioredis README — Pipelining](https://github.com/redis/ioredis#pipelining)*

Useful for assertions in tests and for guarding against unbounded pipelines (see pitfalls).

### Autopipelining (Implicit Pipelines)

Beyond the explicit `pipeline()` API, ioredis can transparently pipeline commands issued in the same tick of the event loop — enabled via the `enableAutoPipelining` option. When on, sequential `redis.set(...)` calls in the same microtask batch are auto-coalesced into a pipeline without you writing `.pipeline()`. Opt in only when you've measured per-command overhead; the explicit `pipeline()` form is clearer and is what the README documents as the default mental model.

> 🔗 [`../PROMISES.md`](../PROMISES.md) — `.exec()` returns a single `Promise<[[err, result], ...]>`. That's a Promise of an **array** of **tuples**: `Promise.all` rules don't apply (it's already one settlement), but the ordering invariant (submission order, not completion order) mirrors `Promise.all`'s input-order guarantee. A rejected pipeline (socket-level failure) propagates like any rejected promise — `await` re-throws, missing `.catch()` becomes `unhandledRejection`.

## Mental Model: Thinking in Pipelines

**The Conveyor Belt Analogy:** Without a pipeline, you hand each parcel to the courier and wait for the delivery receipt before handing over the next. With a pipeline, you stack all the parcels on a conveyor belt; the courier takes the whole stack at once and returns a stack of receipts in the same order.

```
N separate awaits (N round-trips):         One pipeline (1 round-trip):

  set(a) ──────► ─► reply                    pipeline
  (wait)              │                       .set(a)
  set(b) ──────► ─► reply                     .set(b)
  (wait)              │                       .set(c)
  set(c) ──────► ─► reply                     .exec() ──► [[null,'OK'],
                                                       │   [null,'OK'],
                                                       │   [null,'OK']]
                  3 × RTT                                1 × RTT
```

1. **RTT amortization is the whole point.** The win is network-bound: 1 syscall write, 1 socket read, regardless of N. On a 1 ms-RTT link, 100 pipelined `SET`s cost ~1 ms total; 100 sequential `await`s cost ~100 ms.

2. **No atomicity.** Redis will happily interleave another client's command between your pipeline's queued commands. If you need "all or nothing / no interleaving," use `redis.multi(...).exec()` (transaction) instead — same fluent API, adds `MULTI`/`EXEC` framing.

3. **Failure granularity is per-command.** The results array's `[err, result]` per-entry shape exists *because* a pipeline is not atomic. A `MULTI`/`EXEC` transaction, by contrast, either runs all commands or none (`EXECABORT` on a syntax error in the queue).

**Why it's designed this way:** the fluent chain (`pipeline().a().b().exec()`) makes the batching *visible* at the call site — you can read "these N commands go in one round-trip" at a glance, which is much safer than a magic global flag. The `[err, result]` tuple array keeps the per-command error surface honest (a pipeline failure isn't all-or-nothing). fred.rs ([`../../rust/fred.rs/02-client-pools.md`](../../rust/fred.rs/02-client-pools.md)) makes the same ergonomic call: pools hand you a single client for connection-affinity operations like pipelining, and the pipeline's `last::<T>()` / `exec()` API mirrors ioredis's results array — both clients treat the batch result as an ordered list.

> **Pitfall — unbounded pipelines.** A pipeline queues commands *in memory* before flushing. Pipelining 100k commands at once spikes your process's RSS and blocks the event loop while serializing. Chunk large batches (the README's own rule of thumb: "a batch of commands, e.g. > 5" implies small batches; thousands should be split into chunks of a few hundred).
>
> **Pitfall — expecting transactional semantics.** `pipeline()` ≠ `multi()`. If two `INCR`s in a pipeline race with another client, you can observe interleaving. Wrap in `redis.multi().incr(...).incr(...).exec()` when atomicity matters (counters, locks, read-modify-write).
>
> **Pitfall — `results` vs `result`.** `await pipeline.exec()` resolves to an **array** of tuples. Writing `const n = (await pipeline.incr("c").exec())` and expecting the number will silently give you the array `[[null, 1]]`. Index in: `(await p.exec())[0][1]`.

> **Cross-language note:** Rust's [`fred.rs`](../../rust/fred.rs/02-client-pools.md) exposes the same pipeline concept (`pipeline.incr().last::<i64>().await`) on a client pulled from the pool — pools exist *so that* connection-affinity operations like pipelines and transactions have a stable socket to batch against. ioredis, being single-threaded JS, pipelines against the one connection you already have. **Go has no stdlib Redis**; `github.com/redis/go-redis/v9` provides `Pipe()` / `TxPipeline()` with the same one-round-trip semantics and a `[]Cmd` result slice analogous to ioredis's `[[err, result], ...]` array.

**Further exploration:** time 100 sequential `await redis.set(k, v)` calls against the same 100 commands in a single `pipeline().exec()`. Then break one command in the middle (e.g. `await pipeline.set("k").exec()` — wrong arg count) and confirm only that entry's `err` is set while the rest succeed; repeat the same with `redis.multi()` to see the contrasting `EXECABORT` all-or-nothing behavior.
