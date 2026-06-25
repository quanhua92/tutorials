# Pipelines: Batch Round-Trip Amortization

**Doc Source:** [redis-plus-plus README — Pipeline](https://github.com/sewenew/redis-plus-plus#pipeline) and the [Pipeline example in Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started)

## The Core Concept: Why This Example Exists

**The Problem:** Redis is blindingly fast at executing a single command — sub-microsecond. The thing that kills throughput is **network round-trip time (RTT)**: one `SET` costs you ~0.1 ms of CPU on the server but maybe 1 ms of latency crossing the wire. Fire commands one at a time and you spend 90% of your wall-clock waiting on the network, not on Redis.

**The Solution:** A [Redis pipeline](https://redis.io/topics/pipelining) stuffs many commands into a single TCP send, then reads many replies back in a single TCP recv. `redis-plus-plus` exposes this with a `Pipeline` object: you chain commands on it (they return `*this`, not their reply), and only when you call `exec()` does the whole batch go over the wire. N commands collapse from N RTTs into 1 RTT — order-of-magnitude speedups for bulk loads and read-many patterns.

## Practical Walkthrough: Code Breakdown

### Creating a Pipeline

```cpp
ConnectionOptions connection_options;
ConnectionPoolOptions pool_options;

Redis redis(connection_options, pool_options);

auto pipe = redis.pipeline();
```
*(Source: [Create Pipeline](https://github.com/sewenew/redis-plus-plus#create-pipeline))*

The critical detail from upstream: *"When creating a `Pipeline` object, by default, `Redis::pipeline` method creates a new connection to Redis server. This connection is NOT picked from the connection pool, but a newly created connection."* Pipelines need a dedicated connection because they hold the socket open across the whole batch. That makes construction **expensive** — reuse the `Pipeline` object rather than recreating it per batch.

### Chaining Commands

```cpp
pipe.set("key", "val").incr("num").rpush("list", {0, 1, 2}).command("hset", "key", "field", "value");
```
*(Source: [Send Commands](https://github.com/sewenew/redis-plus-plus#send-commands))*

Every command method on `Pipeline` has the same name and signature as on `Redis`, but the return type is `Pipeline&` instead of the reply. That's what enables the fluent chain. Crucially, *"these commands won't be sent to Redis, until you call `Pipeline::exec`."* They're buffered locally.

### Flushing the Batch

```cpp
pipe.set("key", "val").incr("num");
auto replies = pipe.exec();

// The same as:
replies = pipe.set("key", "val").incr("num").exec();
```
*(Source: [Get Replies](https://github.com/sewenew/redis-plus-plus#get-replies))*

`exec()` does two things in order: send every buffered command, then read every reply. You can also `pipe.discard()` to throw the buffered batch away before it ever hits the network.

### The Full Getting-Started Example

This is the canonical pipeline demo from the README's Getting Started section, showing five different reply types parsed back out of one batch:

```cpp
    // ***** Pipeline *****

    // Create a pipeline.
    auto pipe = redis.pipeline();

    // Send mulitple commands and get all replies.
    auto pipe_replies = pipe.set("key", "value")
                            .get("key")
                            .rename("key", "new-key")
                            .rpush("list", {"a", "b", "c"})
                            .lrange("list", 0, -1)
                            .exec();

    // Parse reply with reply type and index.
    auto set_cmd_result = pipe_replies.get<bool>(0);

    auto get_cmd_result = pipe_replies.get<OptionalString>(1);

    // rename command result
    pipe_replies.get<void>(2);

    auto rpush_cmd_result = pipe_replies.get<long long>(3);

    std::vector<std::string> lrange_cmd_result;
    pipe_replies.get(4, back_inserter(lrange_cmd_result));
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

`exec()` returns a `QueuedReplies` object. You pull replies **by index** with `get<T>(i)`, where `T` matches what the same command would return on a plain `Redis` object:
- `get<bool>(0)` — `SET` returns a status reply parsed as `bool` ("OK" → true).
- `get<OptionalString>(1)` — `GET` may be NULL.
- `get<void>(2)` — `RENAME` returns "OK"; we ignore it.
- `get<long long>(3)` — `RPUSH` returns the new list length.
- `get(i, back_inserter(vec))` — `LRANGE` is an array reply; the output-iterator overload fills a container, exactly like on `Redis`.

There's also a `redisReply& get(std::size_t idx)` overload for replies with no fixed shape — you then parse manually with `reply::parse<T>(...)`.

### The Cheaper Pool-Based Variant (and Why It's Dangerous)

Because creating a fresh connection per pipeline is costly, the library offers `redis.pipeline(false)` to borrow a connection from the pool instead:

```c++
ConnectionOptions connection_options;
ConnectionPoolOptions pool_options;

Redis redis(connection_options, pool_options);

// Create a Pipeline without creating a new connection.
auto pipe = redis.pipeline(false);
```
*(Source: [Create Pipeline Without Creating New Connection](https://github.com/sewenew/redis-plus-plus#create-pipeline-without-creating-new-connection))*

The prototype is `Pipeline pipeline(bool new_connection = true);`. But the README flags this with **all-caps warnings** because the borrowed connection stays pinned until `exec()`/`discard()`/destructor runs. With a default pool of size 1 and `wait_timeout = 0ms`, this deadlocks:

```c++
// By defaul, create a `Redis` object with only ONE connection in pool.
// Also by default, the `ConnectionPoolOptions::wait_timeout` is 0ms,
// which means if the pool is empty, `Redis` method will be blocked until
// the pool is not empty.
Redis redis("tcp://127.0.0.1");

// Create a `Pipeline` with a connection in the underlying pool.
auto pipe = redis.pipeline(false);

// Now the `Pipeline` object fetches a connection from the pool.
pipe.set("key1", "val");

pipe.set("key2", "val");

// Try to send a command with `Redis` object.
// However, the pool is empty, since the `Pipeline` object still holds
// the connection, and this call will be blocked forever.
// DEAD LOCK!!!
redis.get("key");

// NEVER goes here.
pipe.exec();
```
*(Source: [VERY IMPORTANT NOTES](https://github.com/sewenew/redis-plus-plus#very-important-notes))*

The upstream **BEST PRACTICE** for the pool-based form:
- Always set `ConnectionPoolOptions::wait_timeout > 0ms`.
- Avoid slow work between `Pipeline` method calls.
- Chain methods and `exec()` in a single statement.
- Confine the `Pipeline` to a block scope so the connection is released ASAP:

```c++
ConnectionPoolOptions pool_opts;
pool_opts.size = 3;
// Always set `wait_timeout` larger than 0ms.
pool_opts.wait_timeout = std::chrono::milliseconds(50);

auto redis = Redis(opts, pool_opts);

{
    // Better put `Pipeline` related code in a block scope.
    auto pipe = redis.pipeline(false);

    // When `Pipeline::exec` finishes, `Pipeline` releases the connection, and returns it to pool.
    auto replies = pipe.exec();

    // This is even better, i.e. chain `Pipeline` methods with `Pipeline::exec`.
    replies = pipe.set("key1", "val").set("key2", "val").exec();
}
```
*(Source: [VERY IMPORTANT NOTES](https://github.com/sewenew/redis-plus-plus#very-important-notes))*

## Mental Model: Thinking in Pipelines

**The Assembly-Line Analogy:** Plain `Redis` calls are like mailing one letter at a time — write, address, walk to the mailbox, wait for the reply. A `Pipeline` is a courier pouch: you stuff N letters in, hand it over once, and get N reply letters back in one delivery.

```
Per-command (N RTTs):          Pipelined (1 RTT):
  cmd → reply → cmd → reply      cmd, cmd, cmd ─┐
                                   replies ◄─────┘
  = N × (send + server + recv)   = send_all + server_all + recv_all
```

1. **Pipelining is NOT atomic.** A pipeline is a performance optimization only. Other clients can interleave commands between yours, and individual commands inside a pipeline can fail independently. If you need atomicity, you want a **Transaction** (`MULTI`/`EXEC`) — see [`03-transactions.md`](03-transactions.md).

2. **`Pipeline` is NOT thread-safe.** From the README: *"`Pipeline` is NOT thread-safe. If you want to call its member functions in multi-thread environment, you need to synchronize between threads manually."* Each thread should create its own `Pipeline` (or guard access with a mutex).

3. **Failure poisons the object.** *"If any of `Pipeline`'s method throws an exception other than `ReplyError`, the `Pipeline` object enters an invalid state. You CANNOT use it any more, but only destroy the object, and create a new one."* So wrap `exec()` in try/catch and be prepared to throw the `Pipeline` away on a non-`ReplyError` failure.

**Why It's Designed This Way:** Pipelines are deliberately separated from `Redis` so that the "no reply yet, just buffer" semantics can't accidentally leak into ordinary command flow. The fluent chain + indexed `QueuedReplies` keeps the API uniform with `Redis` (same method names, same return types) while letting you batch freely. The two construction modes (`new_connection=true|false`) trade safety for cost — the default is the safe, expensive path.

**Further Exploration:** Write a micro-benchmark that `SET`s 10,000 keys one at a time vs. in a single pipeline of 10,000. Time both with `std::chrono::steady_clock` — you should see a 10–50× difference depending on network latency. Then try `pipeline(false)` with a pool of size 1 and `wait_timeout = 0` to reproduce the deadlock firsthand (in a throwaway test program, obviously).

## Pitfalls

- **Treating pipelines as transactions.** They aren't atomic and aren't isolated. Use [`Transaction`](03-transactions.md) when you need all-or-nothing semantics.
- **Recreating `Pipeline` per request with the default `new_connection=true`.** Each construction opens a fresh TCP connection — you'll spend more time in `connect()` than you save on RTT. Reuse the object, or switch to `pipeline(false)` with proper `wait_timeout`.
- **Deadlock with `pipeline(false)` + pool size 1 + `wait_timeout=0`.** Documented above. Always raise `wait_timeout` off zero when borrowing pool connections.
- **Index drift.** Replies are positional — if you insert a command mid-chain, every `get<T>(i)` after it shifts. Keep the chain and the parse calls visually aligned, or capture `replies.size()` defensively.
- **Mixing `exec()` and `discard()` confusion.** After `discard()`, the buffered commands never run — don't expect replies.

## Cross-References

- 🔗 **Curriculum bundles:** Pipelines are the canonical `CONCURRENCY` optimization that's *not* about threads — it's about overlapping I/O. Pairs with the `BENCHMARKING` module (measure the RTT win) and `STD_THREAD` (each thread owns its own `Pipeline`).
- 🦀 **Rust sibling:** [`../rust/fred.rs/05-pipelining.md`](../rust/fred.rs/05-pipelining.md) — fred.rs pipelines return `Futures` you await as a batch; the batching concept is identical, the ergonomics differ (async vs. synchronous chain).
- 🟦 **TypeScript sibling:** [`../ts/ioredis/02-pipelines-batches.md`](../ts/ioredis/02-pipelines-batches.md) — ioredis `pipeline()` exposes the same chain-then-`exec()` shape; compare `Pipeline` vs `Transaction` semantics across all three clients.
- ⬅️ **Previous:** [`01-basic.md`](01-basic.md) — single-command basics. **Next:** [`03-transactions.md`](03-transactions.md) — same fluent API, but atomic.
