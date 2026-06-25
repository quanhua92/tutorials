# Basic Redis Client: Your First Connection to Redis

**Doc Source:** [redis-plus-plus README — Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started) and [Connection](https://github.com/sewenew/redis-plus-plus#connection)

## The Core Concept: Why This Example Exists

**The Problem:** You have a C++ application and need to talk to a Redis server — store a value, read it back, maybe fan it out across a few data structures. You want a client that speaks the Redis serialization protocol (RESP) for you, manages TCP connections, and exposes a type-safe, STL-flavored API instead of raw protocol bytes.

**The Solution:** `redis-plus-plus` is a wrapper over [hiredis](https://github.com/redis/hiredis) (the canonical C Redis client). You instantiate a single `Redis` object with a connection URI, and that object owns a **connection pool** to the server. Every command (`set`, `get`, `rpush`, ...) maps to a member function with the same lowercase name. Think of the `Redis` object as a managed telephone exchange: you configure it once, hand it around to every thread that needs it, and it silently reconnects, pools, and translates RESP replies into native C++ types (`OptionalString`, `bool`, `long long`, ...).

## Practical Walkthrough: Code Breakdown

Let's walk through the canonical Getting-Started example from the official README. Every snippet below is quoted verbatim from upstream.

### Creating the Client Object

```cpp
#include <sw/redis++/redis++.h>

using namespace sw::redis;

try {
    // Create an Redis object, which is movable but NOT copyable.
    auto redis = Redis("tcp://127.0.0.1:6379");
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

That single constructor does a lot behind the scenes:
- `Redis` is **movable but NOT copyable** — you cannot accidentally duplicate the underlying pool, but you can hand ownership off with `std::move`.
- The URI form is `tcp://[[username:]password@]host[:port][/db]`. The `scheme` and `host` are required; `port` defaults to `6379`, `db` defaults to `0`.
- No connection is opened yet. As the README's [Lazily Create Connection](https://github.com/sewenew/redis-plus-plus#lazily-create-connection) section stresses, *"Connections in the pool are lazily created... it connects to the server only when you try to send command."*

### String Commands and Optional Returns

```cpp
    // ***** STRING commands *****

    redis.set("key", "val");
    auto val = redis.get("key");    // val is of type OptionalString. See 'API Reference' section for details.
    if (val) {
        // Dereference val to get the returned value of std::string type.
        std::cout << *val << std::endl;
    }   // else key doesn't exist.
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

Two things deserve attention here:
- `redis.get("key")` returns an **`OptionalString`** (`Optional<std::string>`). Redis replies `GET` with a *NULL Bulk String* when the key is missing, and `Optional<T>` is exactly the right C++ shape for "value-or-nothing." In C++17 builds it aliases `std::optional`; in C++11/14 builds the library ships its own [simple `Optional`](https://github.com/sewenew/redis-plus-plus/blob/master/src/sw/redis%2B%2B/cxx11/cxx_utils.h).
- The `Optional` converts to `bool` for the existence check, and you dereference with `*val` to read the string. This is the pattern you'll repeat for every command whose reply may be NULL.

### STL-Flavored Collection Commands

The library leans hard on the STL so you can stream Redis replies into ordinary containers:

```cpp
    // ***** LIST commands *****

    // std::vector<std::string> to Redis LIST.
    std::vector<std::string> vec = {"a", "b", "c"};
    redis.rpush("list", vec.begin(), vec.end());

    // Redis LIST to std::vector<std::string>.
    vec.clear();
    redis.lrange("list", 0, -1, std::back_inserter(vec));

    // ***** HASH commands *****

    redis.hset("hash", "field", "val");

    // std::unordered_map<std::string, std::string> to Redis HASH.
    std::unordered_map<std::string, std::string> m = {
        {"field1", "val1"},
        {"field2", "val2"}
    };
    redis.hmset("hash", m.begin(), m.end());

    // Redis HASH to std::unordered_map<std::string, std::string>.
    m.clear();
    redis.hgetall("hash", std::inserter(m, m.begin()));
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

The idiom is always the same: pass a **pair of iterators** (or an `std::initializer_list`) for input, and an **output iterator** (`std::back_inserter`, `std::inserter`) for array replies. The compiler deduces the element type from your container, so `lrange` fills a `vector<string>` while `zrangebyscore` can fill either a `vector<string>` (names only) or a `vector<pair<string,double>>` (members + scores) depending on the inserter you hand it.

### Connection Options: The Builder Alternative

The URI form is convenient but limited. For full control — pool sizing, timeouts, RESP3, TLS — build a `ConnectionOptions` plus an optional `ConnectionPoolOptions`:

```cpp
ConnectionOptions connection_options;
connection_options.host = "127.0.0.1";  // Required.
connection_options.port = 6666; // Optional. The default port is 6379.
connection_options.password = "auth";   // Optional. No password by default.
connection_options.db = 1;  // Optional. Use the 0th database by default.

// Optional. Timeout before we successfully send request to or receive response from redis.
// By default, the timeout is 0ms, i.e. never timeout and block until we send or receive successfuly.
// NOTE: if any command is timed out, we throw a TimeoutError exception.
connection_options.socket_timeout = std::chrono::milliseconds(200);

// Connect to Redis server with a single connection.
Redis redis1(connection_options);

ConnectionPoolOptions pool_options;
pool_options.size = 3;  // Pool size, i.e. max number of connections.

// Optional. Max time to wait for a connection. 0ms by default, which means wait forever.
// Say, the pool size is 3, while 4 threds try to fetch the connection, one of them will be blocked.
pool_options.wait_timeout = std::chrono::milliseconds(100);

// Optional. Max lifetime of a connection. 0ms by default, which means never expire the connection.
// If the connection has been created for a long time, i.e. more than `connection_lifetime`,
// it will be expired and reconnected.
pool_options.connection_lifetime = std::chrono::minutes(10);

// Connect to Redis server with a connection pool.
Redis redis2(connection_options, pool_options);
```
*(Source: [Connection](https://github.com/sewenew/redis-plus-plus#connection))*

Defaults worth memorising:
- **Pool size defaults to 1.** If you omit `ConnectionPoolOptions`, you get exactly one connection shared by every thread.
- **`socket_timeout` defaults to `0ms`** — block forever. The README explicitly warns: *"if you set `ConnectionOptions::socket_timeout`, and try to call blocking commands, e.g. `Redis::brpop`... you must ensure that `ConnectionOptions::socket_timeout` is larger than the timeout specified with these blocking commands."*
- **`wait_timeout` defaults to `0ms`** — wait forever for a free pool slot. Leaving this at zero is the #1 source of "my app hung" reports.

## Mental Model: Thinking in redis-plus-plus

**The Telephone Exchange Analogy:** A `Redis` object is a small switchboard wired to one Redis endpoint.

```
Your threads  →  Redis object  →  ConnectionPool (size N)  →  Redis server
     ↑                 ↑                    ↑                     ↑
   share it       movable,          lazily-created,         RESP over TCP
   safely         NOT copyable       auto-reconnecting       (hiredis under the hood)
```

1. **The `Redis` object IS the pool.** You do not manage connections yourself. Each `redis.get(...)` borrows a connection from the pool, runs the command, and returns the connection. The object is thread-safe — share one instance across all your worker threads.

2. **Reconnection is automatic and invisible.** From the [Connection Failure](https://github.com/sewenew/redis-plus-plus#connection-failure) section: *"Even when you get an exception, i.e. the connection is broken, you don't need to create a new `Redis` object. You can reuse the `Redis` object to send commands, and the `Redis` object will try to reconnect to server automatically."*

3. **Reuse, don't recreate.** Constructing a `Redis` object is comparatively expensive (it sets up the pool machinery). The README puts this bluntly:

   ```cpp
   // This is GOOD practice.
   auto redis = Redis("tcp://127.0.0.1");
   for (auto idx = 0; idx < 100; ++idx) {
       // Reuse the Redis object in the loop.
       redis.set("key", "val");
   }

   // This is VERY BAD! It's very inefficient.
   // NEVER DO IT!!!
   for (auto idx = 0; idx < 100; ++idx) {
       // Create a new Redis object for each iteration.
       auto redis = Redis("tcp://127.0.0.1");
       redis.set("key", "val");
   }
   ```
   *(Source: [Reuse Redis object As Much As Possible](https://github.com/sewenew/redis-plus-plus#reuse-redis-object-as-much-as-possible))*

**Why It's Designed This Way:** `redis-plus-plus` mirrors the philosophy of hiredis (thin, fast) while adding the C++ ergonomics hiredis lacks: RAII connection management, STL iterators, `Optional<T>` for NULL replies, and exception-based error propagation. The lazy-pool + auto-reconnect design means a `Redis` object behaves like a reliable long-lived service handle rather than a fragile socket.

**Further Exploration:** Try changing `pool_options.size` to match your thread count and benchmark with the test program's `-b` mode: `./build/test/test_redis++ -h host -p port -b -t thread_num -s connection_pool_size`. Then build a tiny two-thread program that calls `redis.incr("counter")` in a tight loop and watch that — unlike hand-rolled sockets — no extra wiring is needed for thread safety.

## Pitfalls

- **Forgetting `Optional<T>`.** `get`, `hget`, `lpop` all return `Optional<...>`. Dereferencing a missing value is UB; always check `if (val)` first.
- **`bool` returns are not success flags.** `redis.expire(...)` returns `false` when the key is absent, *not* when the command failed. A command failure is always a thrown `Error`. See [Boolean Return Value](https://github.com/sewenew/redis-plus-plus#boolean-return-value).
- **C++ standard mismatch.** Build `redis-plus-plus` and your app with the **same** `-std=` (default is C++17 since v1.3.0). Mixing standards is a classic link/ABI headache.
- **Blocking commands + tiny `socket_timeout`.** `brpop` with a 5s timeout needs `socket_timeout > 5s` or you'll get spurious `TimeoutError`.
- **Multiple hiredis installs.** The README opens with a shouty warning: *"DO NOT INSTALL MULTIPLE VERSIONS OF HIREDIS."* It produces silent, weird crashes.

## Cross-References

- 🔗 **Curriculum bundles:** This pairs with `STD_THREAD` (P4) — the `Redis` object is thread-safe and meant to be shared across `std::thread`s — and the broader `CONCURRENCY` bundle (mutex/condition_variable/futures), since the pool internally coordinates waiting threads.
- 🦀 **Rust sibling:** [`../rust/fred.rs/01-basic-redis-client.md`](../rust/fred.rs/01-basic-redis-client.md) — fred.rs is the closest analog: same concept (one client object, builder config, `Optional` returns), but async-by-default and uses `Builder::from_config` instead of a URI constructor.
- 🟦 **TypeScript sibling:** [`../ts/ioredis/01-basic-client.md`](../ts/ioredis/01-basic-client.md) — ioredis exposes the same `new Redis("redis://...")` + `redis.get/set` shape; compare how each language models "the reply might be null" (TS `null`, Rust `Option`, C++ `Optional`).
- ➡️ **Next in this series:** [`02-pipelines.md`](02-pipelines.md) shows how to batch N commands into a single round-trip once you're comfortable with single-command calls.
