# Transactions: MULTI/EXEC Atomicity with WATCH

**Doc Source:** [redis-plus-plus README — Transaction](https://github.com/sewenew/redis-plus-plus#transaction) and the [Transaction example in Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started)

## The Core Concept: Why This Example Exists

**The Problem:** You need to move 100 credits from account A to account B. If you `DECR A` then `INCR B` as two separate commands, another client can observe the intermediate state (or worse, the process can crash between them). You need the two operations to be **atomic** — either both run, or neither does — and isolated from concurrent writers.

**The Solution:** Redis [transactions](https://redis.io/topics/transactions) wrap a sequence of commands in `MULTI` ... `EXEC`: the server queues them without running anything, then on `EXEC` it runs the whole batch as one indivisible unit. `redis-plus-plus` exposes this with a `Transaction` object whose API is intentionally identical to `Pipeline` (chain commands, call `exec()`), so `MULTI`/`EXEC` feels like a pipeline that happens to be atomic. For the harder problem — *check a value, then conditionally write it* — Redis offers `WATCH` for optimistic locking, and the library wraps that with a `WatchError` retry loop.

## Practical Walkthrough: Code Breakdown

### Creating a Transaction

```cpp
ConnectionOptions connection_options;
ConnectionPoolOptions pool_options;

Redis redis(connection_options, pool_options);

auto tx = redis.transaction();
```
*(Source: [Create Transaction](https://github.com/sewenew/redis-plus-plus#create-transaction))*

Just like `Pipeline`, the `Transaction` object owns a **freshly created connection** (not a pool connection) with the same `ConnectionOptions` as the parent `Redis`. That's required because the entire `MULTI`/`EXEC` exchange must happen on one socket. Construction is therefore not cheap — reuse the object.

You never send `MULTI` yourself. The README is explicit: *"you don't need to send [MULTI](https://redis.io/commands/multi) command to Redis. `Transaction` will do that for you automatically."*

### Queuing Commands and Committing

```cpp
tx.set("key", "val").incr("num").lpush("list", {0, 1, 2}).command("hset", "key", "field", "val");
```
*(Source: [Send Commands](https://github.com/sewenew/redis-plus-plus#send-commands-1))*

```cpp
auto replies = tx.set("key", "val").incr("num").exec();

tx.set("key", "val").incr("num");

// Discard the transaction.
tx.discard();
```
*(Source: [Execute Transaction](https://github.com/sewenew/redis-plus-plus#execute-transaction))*

`exec()` triggers the server-side `EXEC` — the queued commands run atomically and you get a `QueuedReplies` back (parsed exactly like pipelines' replies, see [`02-pipelines.md`](02-pipelines.md)). `discard()` issues `DISCARD` instead and nothing runs.

### The Canonical Example: Atomic Counters

From the README's Getting Started, a transaction that bumps two counters and reads them back:

```cpp
    // ***** Transaction *****

    // Create a transaction.
    auto tx = redis.transaction();

    // Run multiple commands in a transaction, and get all replies.
    auto tx_replies = tx.incr("num0")
                        .incr("num1")
                        .mget({"num0", "num1"})
                        .exec();

    // Parse reply with reply type and index.
    auto incr_result0 = tx_replies.get<long long>(0);

    auto incr_result1 = tx_replies.get<long long>(1);

    std::vector<OptionalString> mget_cmd_result;
    tx_replies.get(2, back_inserter(mget_cmd_result));
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

The structure mirrors a pipeline exactly: chain by index, parse with `get<T>(i)`. The semantic difference is that between the chained calls and `exec()`, **no other client can interleave** — `num0` and `num1` move together.

### Piped Transactions (Free Performance)

Because transactions always send multiple commands, you can fold the pipelining optimization in for free:

```cpp
// Create a piped transaction
auto tx = redis.transaction(true);
```
*(Source: [Piped Transaction](https://github.com/sewenew/redis-plus-plus#piped-transaction))*

`Redis::transaction(bool piped = false, bool new_connection = true)` — pass `true` and *"all commands are sent to Redis in a pipeline."* Atomicity is preserved; you just avoid paying multiple RTTs while queuing.

### WATCH: Optimistic Locking for Check-And-Set

Atomic batches solve half the problem. The other half is: *read a value, compute a new value, write it — but only if nobody changed it in between.* Redis solves this with [`WATCH`](https://redis.io/topics/transactions#optimistic-locking-using-check-and-set): if a watched key is modified before `EXEC`, the whole transaction is aborted.

The algorithm, straight from the README:

```
WATCH key           // watch a key
val = GET key       // get value of the key
new_val = val + 1   // incr the value
MULTI               // begin the transaction
SET key new_val     // set value only if the value is NOT modified by others
EXEC                // try to execute the transaction.
                    // if val has been modified, the transaction won't be executed.
```
*(Source: [Watch](https://github.com/sewenew/redis-plus-plus#watch))*

The catch: `WATCH`, `GET`, and the `MULTI`/`EXEC` block **must all run on the same connection**. But a `Transaction` object buffers commands and won't give you the `GET` result until `exec()`. The library's escape hatch is `Transaction::redis()`, which returns a `Redis` object **sharing the transaction's connection** so you can run immediate commands (like `WATCH` and `GET`) on the same socket:

```cpp
auto redis = Redis("tcp://127.0.0.1");

// Create a transaction.
auto tx = redis.transaction();

// Create a Redis object from the Transaction object. Both objects share the same connection.
auto r = tx.redis();

// If the watched key has been modified by other clients, the transaction might fail.
// So we need to retry the transaction in a loop.
while (true) {
    try {
        // Watch a key.
        r.watch("key");

        // Get the old value.
        auto val = r.get("key");
        auto num = 0;
        if (val) {
            num = std::stoi(*val);
        } // else use default value, i.e. 0.

        // Incr value.
        ++num;

        // Execute the transaction.
        auto replies = tx.set("key", std::to_string(num)).exec();

        // Transaction has been executed successfully. Check the result and break.

        assert(replies.size() == 1 && replies.get<bool>(0) == true);

        break;
    } catch (const WatchError &err) {
        // Key has been modified by other clients, retry.
        continue;
    } catch (const Error &err) {
        // Something bad happens, and the Transaction object is no longer valid.
        throw;
    }
}
```
*(Source: [Watch](https://github.com/sewenew/redis-plus-plus#watch))*

The pattern to internalize:
1. `tx.redis()` → shared-connection `Redis` handle `r`.
2. `r.watch(key)` — arm the lock.
3. `r.get(key)` — read on the **same** socket.
4. Compute the new value in your C++ code.
5. `tx.set(...).exec()` — the `MULTI`/`EXEC`. If the watched key changed, the library throws `WatchError`; catch it and **loop**.
6. Any other `Error` is fatal to this `Transaction` object — rethrow and let it die.

The README notes the `Transaction` is deliberately created **outside** the loop so you don't pay for a new connection on every retry.

### Pool-Based Transactions (Same Caveats as Pipelines)

`Redis::transaction(bool piped, bool new_connection)` — passing `new_connection=false` borrows a pool connection. The same deadlock rules from [`02-pipelines.md`](02-pipelines.md) apply, plus one transaction-specific warning from upstream: *"Limit the scope of `Redis` object created by `Transaction::redis`, i.e. destroy it ASAP."* If `r` outlives `tx.exec()`, the connection stays checked out and your pool starves. The README's corrected loop creates the `Transaction` *inside* the retry loop precisely so each iteration's `r` and `tx` are destroyed together, releasing the connection:

```cpp
auto redis = Redis(opts, pool_opts);

while (true) {
    try {
        // Create a transaction without creating a new connection.
        auto tx = redis.transaction(false, false);

        // Create a Redis object from the Transaction object. Both objects share the same connection.
        auto r = tx.redis();

        r.watch("key");
        // ... read, compute, exec ...
        break;
    } catch (const WatchError &err) {
        continue;
    } catch (const Error &err) {
        throw;
    }
}
```
*(Source: [Create Transaction Without Creating New Connection](https://github.com/sewenew/redis-plus-plus#create-transaction-without-creating-new-connection))*

## Mental Model: Thinking in Transactions

**The Vault Analogy:** A `Pipeline` is a delivery truck — fast, but other trucks merge onto the highway around it. A `Transaction` is an armored vault: once the door closes (`MULTI`), nothing goes in or out until `EXEC` opens it again, and the contents move as one inseparable load.

```
Transaction timeline (single connection):

  CLIENT                              REDIS
    │  MULTI                            │
    │ ──────────────────────────────►   │  "start queuing"
    │  SET A                            │
    │ ──────────────────────────────►   │  queued
    │  INCR B                           │
    │ ──────────────────────────────►   │  queued
    │  EXEC                             │
    │ ──────────────────────────────►   │  *** runs A then B atomically ***
    │ ◄──────────────────────────────   │  [reply_A, reply_B]
```

1. **`MULTI`/`EXEC` is atomic but NOT rollback-safe.** Redis transactions do not roll back on command errors — if a command inside `EXEC` is syntactically valid but fails at runtime (e.g. type mismatch), the others still run. You must check each reply in the `QueuedReplies`. This is a deliberate Redis design choice, not a library quirk.

2. **`WATCH` is optimistic, not pessimistic.** It doesn't lock anything; it just aborts your `EXEC` if a key changed. The retry loop is mandatory — under contention you'll loop several times. Compare to a mutex: pessimistic locks block waiters, optimistic locking retries losers.

3. **Same object-lifecycle rules as `Pipeline`.** NOT thread-safe; poison-on-non-`WatchError`/non-`ReplyError` exception; reuse rather than recreate. The README: *"`Transacation` is NOT thread-safe... you need to synchronize between threads manually."*

**Why It's Designed This Way:** `Transaction` deliberately reuses the `Pipeline` API because the wire-level shape is nearly identical (queue commands, flush on `exec`). The `tx.redis()` escape hatch is the elegant bit — it lets you issue immediate commands on the transaction's private connection without exposing raw socket control, so `WATCH`/`GET`/`MULTI`/`EXEC` all naturally land on the same socket. The `WatchError`-as-control-flow idiom turns the awkward "did my transaction abort?" check into a clean exception-driven retry.

**Further Exploration:** Implement an atomic "transfer credits between two accounts" function with `WATCH` on both keys, and a concurrent test where two threads hammer the same pair — count how many `WatchError` retries each thread suffers. Then redo it with a Lua script (`redis.eval`) and compare: scripts are atomic and single-RTT, often simpler than `WATCH` loops.

## Pitfalls

- **No rollback on runtime errors.** If command 3 of 5 fails at runtime, commands 1, 2, 4, 5 still committed. Inspect every reply.
- **Forgetting to retry on `WatchError`.** A single `WATCH` without a loop gives you a "maybe-atomic" operation — exactly the bug you were trying to avoid.
- **Using `WATCH` on a different connection than `EXEC`.** It silently never fires. Always go through `tx.redis()` so the `WATCH` and the `MULTI`/`EXEC` share a socket.
- **Letting `r = tx.redis()` outlive `exec()` with `new_connection=false`.** Pool starvation/deadlock — destroy `r` in the same scope as `tx`.
- **Confusing transaction atomicity with durability.** Atomic ≠ persisted to disk. Configure Redis `appendonly`/RDB separately if you need crash durability.
- **Recreating `Transaction` per attempt.** With the default `new_connection=true` you'll reconnect on every retry. Create once, loop inside.

## Cross-References

- 🔗 **Curriculum bundles:** This is the `CONCURRENCY` bundle's "atomicity without locks" lesson — compare `WATCH`/retry to `std::mutex` (pessimistic) and lock-free CAS (`std::atomic::compare_exchange_weak`, covered in `ATOMICS_MEMORY_ORDER`). Also ties to `STD_THREAD` for the concurrent-contention case.
- 🦀 **Rust sibling:** [`../rust/fred.rs/04-transactions.md`](../rust/fred.rs/04-transactions.md) — fred.rs models the same `MULTI`/`EXEC` + `WATCH` semantics; compare how each client surfaces the "transaction aborted" signal (C++ `WatchError` exception vs. Rust `Result`).
- 🟦 **TypeScript sibling:** [`../ts/ioredis/04-transactions-multi-exec.md`](../ts/ioredis/04-transactions-multi-exec.md) — ioredis uses `.multi()` chain + `.exec()` returning an array; same Redis semantics, different language ergonomics.
- ⬅️ **Previous:** [`02-pipelines.md`](02-pipelines.md) — same API minus atomicity. **Next:** [`04-pub-sub.md`](04-pub-sub.md) — leaves request/response entirely for push delivery.
