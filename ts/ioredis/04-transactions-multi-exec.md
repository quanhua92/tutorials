# Transactions: MULTI/EXEC & Optimistic Locking

**Example/Doc Source:** [redis/ioredis README — Transaction](https://github.com/redis/ioredis#transaction) (see also [Pipelining](https://github.com/redis/ioredis#pipelining) and the [Redis MULTI/EXEC spec](https://redis.io/docs/latest/develop/use/pipelining/transactions/))

## The Core Concept: Why This Example Exists

**The Problem:** You need to run several Redis commands as a single, indivisible unit — either they all take effect together, or none of them do. Without this, a concurrent client can observe your data halfway through a multi-step update, or interleave its own writes between yours. Classic examples: atomically moving units between two counters, or "decrement stock **and** record the sale" that must not be split.

**The Solution:** Redis offers the `MULTI` / `EXEC` transaction. `MULTI` puts the connection into transaction mode; subsequent commands are not executed but **queued** server-side. `EXEC` then runs every queued command back-to-back, with no other client able to sneak a command in between. ioredis leans into this by **reusing its pipeline interface for transactions**: calling `redis.multi()` returns a `Pipeline`-shaped builder, so `redis.multi().set(...).get(...).exec()` reads almost identically to `redis.pipeline()...exec()`. The difference is atomicity — a pipeline is a network optimization (batch, **not** atomic), while a `multi()` wraps the batch in `MULTI`…`EXEC`.

For the "read-modify-write" race (where you need to act on a value *before* you change it), Redis pairs `WATCH` with `MULTI`/`EXEC` for **optimistic locking** — a check-and-set loop that retries when it loses the race.

Think of `MULTI`…`EXEC` as writing a sealed order envelope: you list every step, seal it, then it's carried out as one uninterrupted action. `WATCH` is asking the cashier to abort the whole envelope if the item's price tag changes before they ring it up.

## Practical Walkthrough: Code Breakdown

### A Transaction Looks Like a Pipeline

ioredis deliberately unifies the two APIs. Because `MULTI`/`EXEC` are "almost always used together with pipeline", `redis.multi()` returns a pipeline-like object out of the box (from the ioredis README):

```javascript
redis
  .multi()
  .set("foo", "bar")
  .get("foo")
  .exec((err, results) => {
    // results === [[null, 'OK'], [null, 'bar']]
  });
```

Key points about this shape:

- `redis.multi()` opens the transaction (sends `MULTI` internally) and hands back a builder.
- Each chained command (`set`, `get`, …) is **queued**, not executed. Other clients never see an intermediate state.
- `.exec()` sends `EXEC`. Redis runs the whole queue atomically and returns the results.
- **The results array** is a list of `[err, result]` pairs — one per queued command, in order. `[[null, 'OK'], [null, 'bar']]` means command 0 (`set`) succeeded with `"OK"`, command 1 (`get`) succeeded with `"bar"`. The per-command `err` slot lets a *single* command fail without poisoning the whole array (see Pitfalls).
- `exec()` also returns a **Promise**, so `await redis.multi().set("foo","bar").get("foo").exec()` resolves to the same array.

### Per-Command Callbacks Report `QUEUED`, Not the Result

Here is the one observable difference between `multi` and `pipeline` when you attach a callback to an individual chained command (from the ioredis README):

```javascript
redis
  .multi()
  .set("foo", "bar", (err, result) => {
    // result === 'QUEUED'
  })
  .exec(/* ... */);
```

- In a **pipeline**, the chained-command callback fires with the command's *actual result* once the batch replies.
- In a **transaction**, it fires immediately with the string `"QUEUED"` — because Redis answered `+QUEUED` when it accepted the command into the transaction, long before `EXEC` runs it. The *real* result only comes back from `exec()`.

### Syntax Errors Abort the Whole Transaction (EXECABORT)

If a queued command is malformed at enqueue time, Redis refuses to run any of them and `exec()` rejects (from the ioredis README):

```javascript
redis
  .multi()
  .set("foo")                 // wrong number of arguments → caught at queue time
  .set("foo", "new value")
  .exec((err, results) => {
    // err:
    //  { [ReplyError: EXECABORT Transaction discarded because of previous errors.]
    //    name: 'ReplyError',
    //    message: 'EXECABORT Transaction discarded because of previous errors.',
    //    command: { name: 'exec', args: [] },
    //    previousErrors:
    //     [ { [ReplyError: ERR wrong number of arguments for 'set' command]
    //         name: 'ReplyError',
    //         message: 'ERR wrong number of arguments for \'set\' command',
    //         command: [Object] } ] }
  });
```

This is the **all-or-nothing** guarantee in action: a *compile-time* error (bad arity, unknown command) discards the transaction before `EXEC` executes anything. Note the distinction carefully — see Pitfalls for why *runtime* errors behave differently.

### Opt out of Batching: `{ pipeline: false }`

If you want a true, immediate `MULTI` mode (commands sent one-by-one instead of as a single round-trip), pass `{ pipeline: false }` (from the ioredis README):

```javascript
redis.multi({ pipeline: false });
redis.set("foo", "bar");
redis.get("foo");
redis.exec((err, result) => {
  // result === [[null, 'OK'], [null, 'bar']]
});
```

Here every command is sent to Redis the moment it is issued (still inside the `MULTI` context), and `redis.exec()` closes the transaction. You lose the single-round-trip efficiency but gain the ability to interleave other logic — though you still cannot use one queued command's *result* to decide the next (Redis hasn't executed any of them yet).

### Optimistic Locking with WATCH (Check-and-Set)

`MULTI`/`EXEC` alone can't read a value and branch on it, because queued commands run blind. The Redis-native answer is **WATCH**: mark keys as "interesting"; if *any* of them change (by anyone, including expiry) before your `EXEC`, Redis silently abandons the transaction and `EXEC` returns `null`. ioredis exposes `WATCH` like every other Redis command, via `redis.watch(...)`:

```javascript
// Atomic "transfer": move 1 unit from balance:alice to balance:bob,
// only if alice still has funds. Retry if anyone else touches the keys.
async function transfer(amount) {
  while (true) {
    await redis.watch("balance:alice", "balance:bob");   // start watching
    const alice = Number(await redis.get("balance:alice"));
    if (alice < amount) {
      await redis.unwatch();                              // cancel watch before giving up
      throw new Error("insufficient funds");
    }
    const result = await redis
      .multi()
      .decrby("balance:alice", amount)
      .incrby("balance:bob", amount)
      .exec();                                            // returns null if a watched key changed
    if (result !== null) {
      // result === [[null, integer], [null, integer]] — transaction committed
      return result;
    }
    // result === null → a watched key was modified; loop and retry
  }
}
```

How this check-and-set loop works:

- `WATCH balance:alice balance:bob` arms the lock.
- The plain `GET` runs *outside* the transaction (Redis executes it immediately) so you can read the current value.
- `multi().decrby().incrby().exec()` queues the two writes and commits them atomically.
- If any other client wrote `balance:alice` or `balance:bob` in that window, `exec()` resolves to **`null`** and nothing was applied — loop and try again.
- Always `UNWATCH` on the early-exit path so you don't leave a stale watch on the connection.

### Inline Transactions Inside a Pipeline

ioredis pipelines can embed a `MULTI`/`EXEC` block as a *subset* of a larger batch (from the ioredis README):

```javascript
redis
  .pipeline()
  .get("foo")
  .multi()            // ← begins an inline MULTI
  .set("foo", "bar")
  .get("foo")
  .exec()             // ← closes the inline transaction
  .get("foo")
  .exec();            // ← flushes the whole pipeline
```

This composes the two features: a network-efficient batch that contains an atomic sub-block.

## Mental Model: Thinking in Redis Transactions

**The SQL-Transaction Analogy — and where it breaks:**

```
Standalone Redis:            MULTI/EXEC transaction:
  GET foo                      MULTI
     ↓                         GET foo        ← queued (you cannot read this yet)
  "value"                      SET foo bar    ← queued
  SET foo bar                  EXEC
     ↓                             ↓
   "OK"                      [nil, "OK"]      ← results come back all at once
```

| Concept | SQL (e.g. Postgres) | Redis MULTI/EXEC |
|---|---|---|
| Atomicity | `BEGIN … COMMIT`, full ACID | `MULTI … EXEC`, all-or-nothing **execution** |
| Rollback on runtime error | Yes — the whole txn reverts | **No** — a failing command is skipped, others still apply |
| Read-then-branch inside txn | Yes | **No** — use `WATCH` + retry loop instead |
| Isolation | MVCC snapshots | Commands run sequentially with no interleaving during `EXEC` |

1. **Atomic execution, not atomic rollback.** Redis guarantees the queued commands run without another client cutting in. It does **not** roll back a command that succeeds at queue time but errors at run time (e.g. applying `INCR` to a string value). That run-time error shows up as the `err` half of its `[err, result]` slot while its siblings still committed.

2. **Blind queuing.** Once inside `MULTI`, commands cannot see each other's results — Redis hasn't executed any of them. The only way to make a decision from a value is the `WATCH` → read → `MULTI` → `EXEC` check-and-set pattern.

3. **Connection-bound.** A transaction lives on a single connection. ioredis runs `multi()` on the connection you call it on; you cannot spread one transaction across a pool or (without care) across cluster nodes.

**Transaction vs. Pipeline — choose deliberately** (the sibling [`./02-pipelines-batches.md`](./02-pipelines-batches.md) Pipelines guide covers the batching side):

| Use a **pipeline** when… | Use a **transaction** when… |
|---|---|
| You only want to cut round-trips | You need atomicity (all-or-nothing) |
| Commands are independent | Commands must commit together or not at all |
| Individual failures are fine | Intermediate states must never be observable |
| Bulk import / fan-out writes | Counters, balance transfers, "update related keys" |

**Transaction Use Cases:**
- **Related updates** — keeping two keys in sync (e.g. a value and its index).
- **Counters & metrics** — bumping several gauges atomically.
- **Optimistic concurrency** — `WATCH` a version key, mutate, retry on contention (the CAS loop).
- **Atomic multi-field writes** — building a record from several `HSET`/`SET` steps that must appear together.

## Pitfalls

- **No rollback on run-time errors.** `INCR` on a non-integer returns an error in its `[err, result]` slot, but the rest of the transaction still commits. Syntax/queue-time errors abort everything (`EXECABORT`); run-time errors do not. Don't assume a failing command means "nothing happened."
- **`WATCH` is fragile.** A watched key "changes" on **any** modification — including `EXPIRE`-driven deletion and your *own* earlier writes. Always pair `WATCH` with a retry loop and `UNWATCH` on every non-commit exit path, or use `DISCARD`.
- **`WATCH` ties up the connection.** The watch is held until `EXEC`/`UNWATCH`/`DISCARD` or the connection closes. Don't `WATCH` and then go do slow `await` work on a shared pooled connection.
- **Can't read results mid-transaction.** `redis.multi().get(k).incr(k2).exec()` — you cannot feed `get`'s value into `incr`. Use `WATCH` + a read outside the txn, or a Lua script for true atomic read-modify-write.
- **Cluster cross-slot trap.** In `Redis.Cluster`, a `multi()`/`exec()` (and pipelines) must hit **one node** — every key must hash to the same slot (use a hash tag like `{user1}:profile` / `{user1}:settings`). See the sibling ioredis/05 Cluster guide.
- **Cluster has no `{ pipeline: false }` transactions.** ioredis explicitly forbids `cluster.multi({ pipeline: false })` because it can't know which node to target.
- **`exec()` resolving to `null`** under `WATCH` is *normal* (lock lost), not a crash — handle it by retrying, and make sure your retry path is idempotent.

## Cross-References

- 🔗 **Curriculum:** [`../DATABASE_DRIVERS.md`](../DATABASE_DRIVERS.md) — the SQL transaction analogy (`BEGIN`/`COMMIT`/`ROLLBACK`); [`../CONCURRENCY_PATTERNS.md`](../CONCURRENCY_PATTERNS.md) — optimistic locking, CAS, and retry loops; [`../PROMISES.md`](../PROMISES.md) — `multi().exec()` returns a Promise you `await`.
- 🔗 **This series:** sibling [`./02-pipelines-batches.md`](./02-pipelines-batches.md) — the non-atomic batching primitive this guide contrasts against; [`./05-cluster.md`](./05-cluster.md) — cross-slot transaction constraints.
- 🔗 **Cross-language:** the Rust analog [`../../rust/fred.rs/04-transactions.md`](../../rust/fred.rs/04-transactions.md) (fred.rs's typed `client.multi().exec()` — same `MULTI`/`EXEC` semantics, different ergonomics). Note: Go's standard library ships **no** Redis client — Go relies on third-party drivers (e.g. `go-redis`), so there is no stdlib cross-language sibling here.
