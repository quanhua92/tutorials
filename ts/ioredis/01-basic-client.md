# Basic ioredis Client: Connect, Get/Set & Expiration

**Doc Source**: [ioredis README — Connect to Redis](https://github.com/redis/ioredis#connect-to-redis) · [Basic Usage](https://github.com/redis/ioredis#basic-usage) · [Expiration](https://github.com/redis/ioredis#expiration) · [Auto-reconnect](https://github.com/redis/ioredis#auto-reconnect)

## The Core Concept: Why This Example Exists

**The Problem:** Your Node.js/TypeScript application needs to talk to a Redis server — read a cached value, write a session key, set a TTL on a lock. The catch is that every Redis command is a **network round-trip**, and Node's event loop means the result arrives *asynchronously*. The classic first-generation client (`node-redis` v3) exposed this as Node-style callbacks: `redis.get(key, (err, val) => ...)`. Callbacks compose badly, swallow errors silently when forgotten, and fight `async`/`await`. You also need the client to **survive transient network failures** — reconnect, replay queued commands, and surface a clean error model — without writing all of that yourself.

**The Solution:** ioredis is a **promise-native** Redis client: every command returns a `Promise` if you omit the trailing callback, so `await redis.get(key)` is the idiomatic form and rejection propagates through `try/catch` like any async value (🔗 [`../PROMISES.md`](../PROMISES.md)). On top of the API ergonomics, ioredis ships a battle-tested reconnection engine (`retryStrategy`), an offline queue that holds commands issued before the socket is `ready`, and `maxRetriesPerRequest` so a downed Redis can't hang a request forever. It is the closest TS analog to Rust's [`fred.rs`](../../rust/fred.rs/01-basic-redis-client.md) — both are high-level, async-first clients that hide RESP protocol parsing and own connection lifecycle.

> **Why ioredis vs node-redis?** ioredis predates and inspired much of the modern Node Redis story. Per the upstream README, ioredis is now in *maintenance* mode and the README itself recommends `node-redis` for **new** projects (it tracks Redis 8 / Redis Stack features). ioredis remains the right pick when you need (a) `Cluster`/`Sentinel` with a mature, field-hardened implementation, (b) transparent autopipelining, or (c) a stable promise API on Node 12+. For learning the *concepts* — pipelining, pub/sub, reconnect — ioredis's API is the clearest in the ecosystem.

## Practical Walkthrough: Code Breakdown

### Creating the Client: Five Ways to Point at Redis

A `Redis` instance opens the TCP connection **eagerly** at construction time (unless `lazyConnect: true`). ioredis accepts several constructor shapes, each resolving to the same internal `RedisOptions`:

```javascript
new Redis();                       // Connect to 127.0.0.1:6379
new Redis(6380);                   // 127.0.0.1:6380
new Redis(6379, "192.168.1.1");    // 192.168.1.1:6379
new Redis("/tmp/redis.sock");      // UNIX domain socket
new Redis({
  port: 6379,
  host: "127.0.0.1",
  username: "default",             // needs Redis >= 6
  password: "my-top-secret",
  db: 0,                           // Defaults to 0
});
```

*Source: [ioredis README — Connect to Redis](https://github.com/redis/ioredis#connect-to-redis)*

Or, the URL form (`redis://` for plaintext, `rediss://` for TLS):

```javascript
// Connect to 127.0.0.1:6380, db 4, using password "authpassword":
new Redis("redis://:authpassword@127.0.0.1:6380/4");

// Username can also be passed via URI.
new Redis("redis://username:authpassword@127.0.0.1:6380/4");
```

*Source: [ioredis README — Connect to Redis](https://github.com/redis/ioredis#connect-to-redis)*

The numeric/port and object forms are convenient for dev; the URL form is what you inject via `process.env.REDIS_URL` in production. All five collapse to the same `RedisOptions` — pick the one your deployment story makes least awkward.

### The Promise-Native Command API

This is the headline reason ioredis displaced callback-style clients. Every command is a method named after the lowercase Redis command, and it returns a `Promise` when you don't hand it a trailing function:

```javascript
const Redis = require("ioredis");
const redis = new Redis();

redis.set("mykey", "value"); // Returns a promise which resolves to "OK" when the command succeeds.

// ioredis supports the node.js callback style
redis.get("mykey", (err, result) => {
  if (err) {
    console.error(err);
  } else {
    console.log(result); // Prints "value"
  }
});

// Or ioredis returns a promise if the last argument isn't a function
redis.get("mykey").then((result) => {
  console.log(result); // Prints "value"
});
```

*Source: [ioredis README — Basic Usage](https://github.com/redis/ioredis#basic-usage)*

In modern TS you `await` it:

```ts
import { Redis } from "ioredis";
const redis = new Redis(process.env.REDIS_URL!);

const value = await redis.get("mykey");   // string | null
await redis.set("mykey", "value");        // resolves to "OK"
```

**The dual-mode contract:** the *last argument* decides the shape. Pass a function → callback mode (the promise is never created). Omit it → promise mode. This is why `redis.get(key, cb)` and `await redis.get(key)` are the same call path internally — there is no separate `promisify` wrapping, no bluebird, no dual API surface.

> 🔗 [`../PROMISES.md`](../PROMISES.md) — the promise this returns is the same state-machine (`pending → fulfilled | rejected`) every other async value in the curriculum uses. A rejected ioredis command behaves exactly like a rejected fetch: `await` re-throws, a missing `.catch()` becomes an `unhandledRejection`. The argument/combinator rules (`.all`, `.allSettled`, ordering) all apply unchanged to arrays of ioredis commands.

### Arguments Are Passed Straight Through

ioredis does not model each Redis command as a typed signature — it forwards arguments verbatim, so any Redis command (including ones added after the client shipped) works:

```javascript
// All arguments are passed directly to the redis server,
// so technically ioredis supports all Redis commands.
// The format is: redis[SOME_REDIS_COMMAND_IN_LOWERCASE](ARGUMENTS_ARE_JOINED_INTO_COMMAND_STRING)
// so the following statement is equivalent to the CLI: `redis> SET mykey hello EX 10`
redis.set("mykey", "hello", "EX", 10);
```

*Source: [ioredis README — Basic Usage](https://github.com/redis/ioredis#basic-usage)*

The trade-off: you trade compile-time argument checking for forward-compatibility with every Redis version. `@types/node` plus ioredis's own `.d.ts` give you the common commands typed; exotic flags fall back to a variadic signature.

### Expiration: TTL via the `EX` Flag or `expire()`

Redis deletes a key after its timeout elapses. ioredis exposes this two ways — inline on `SET`, or as a separate `expire`/`pexpire`/`expireat` call:

```javascript
redis.set("key", "data", "EX", 60);
// Equivalent to redis command "SET key data EX 60", because on ioredis set method,
// all arguments are passed directly to the redis server.
```

*Source: [ioredis README — Expiration](https://github.com/redis/ioredis#expiration)*

The inline `EX` (seconds) / `PX` (milliseconds) form is atomic with the write — there's no window where the key exists without a TTL. Calling `set` then `expire` separately is two round-trips and a tiny race window. Prefer inline when you can.

### Disconnect, Reconnect & `retryStrategy`

ioredis reconnects automatically on socket loss (unless you called `disconnect()`/`quit()`). The `retryStrategy` function controls the backoff:

```javascript
const redis = new Redis({
  // This is the default value of `retryStrategy`
  retryStrategy(times) {
    const delay = Math.min(times * 50, 2000);
    return delay;
  },
});
```

*Source: [ioredis README — Auto-reconnect](https://github.com/redis/ioredis#auto-reconnect)*

Three guarantees from the README worth pinning:

1. **`retryStrategy(times)`** — called on each reconnect attempt; `times` is the attempt count; the returned number is the ms delay. Return anything *not* a number and ioredis stops retrying (the connection stays down until you call `redis.connect()` manually).
2. **Auto-replay** — on reconnect, ioredis re-subscribes to channels (`autoResubscribe`, default `true`) and resends unfulfilled commands like outstanding `brpop`/`blpop` (`autoResendUnfulfilledCommands`, default `true`).
3. **`maxRetriesPerRequest`** — by default pending commands are flushed with an error every **20** retry attempts, so a long Redis outage surfaces as a rejection rather than an infinite hang. Set it to `null` to restore the pre-v4 "wait forever" behavior (rarely what you want in an HTTP server).

There's also `reconnectOnError` for *application-level* errors (not socket drops) — classic use case is ElastiCache failover where the replica returns `READONLY` until promoted:

```javascript
const redis = new Redis({
  reconnectOnError(err) {
    const targetError = "READONLY";
    if (err.message.includes(targetError)) {
      return true; // or `return 1;`
    }
  },
});
```

*Source: [ioredis README — Reconnect on Error](https://github.com/redis/ioredis#reconnect-on-error)*

Return `2` and ioredis will additionally *resend the failed command* after reconnecting.

### Connection Events & `status`

The instance is an `EventEmitter` (🔗 [`../CONCURRENCY_PATTERNS.md`](../CONCURRENCY_PATTERNS.md) for the EventEmitter model) emitting lifecycle events:

| Event | When it fires |
| :--- | :--- |
| `connect` | TCP connection established to Redis |
| `ready` | Server says it's ready to take commands (after `LOADING` etc.) |
| `error` | Connection error — emitted *silently* unless you attach a listener (no crash) |
| `close` | Established connection closed |
| `reconnecting` | After `close`, before a retry; arg is the delay in ms |
| `end` | After `close` when no more retries will happen |

`redis.status` is a synchronous string (`"wait"`, `"connecting"`, `"connect"`, `"ready"`, `"close"`, `"reconnecting"`, `"end"`) — useful for health checks without subscribing to events.

> **Pitfall — the silent `error` event.** Node's EventEmitter throws if `error` is emitted with no listener. ioredis *suppresses* this specifically so an unmonitored client doesn't crash your process — but that means a connection failure can go entirely unnoticed in dev. Attach `redis.on("error", console.error)` (or a real logger) in every environment.

> **Pitfall — eager connect + missing Redis in dev.** `new Redis()` connects on construction. If nothing is listening on `127.0.0.1:6379`, the client flips into `reconnecting` and your first `await redis.get(...)` waits up to `maxRetriesPerRequest` attempts (~20 × backoff) before rejecting. Use `lazyConnect: true` and an explicit `await redis.connect()` if you want to fail fast at startup instead.

## Mental Model: Thinking in ioredis

**The Phone Line Analogy:** The `Redis` instance is an always-on phone line to the server. `set`/`get` are sentences you speak into it; the `Promise` is "I'll get back to you when they reply." If the line drops, ioredis redials on a backoff schedule and, once reconnected, finishes the sentences that were cut off.

```
Your async code            ioredis client                Redis server
  await redis.get(k)  ──►  RESP: GET k\r\n        ──►   lookup
                          ◄──  RESP: bulk-string  ◄──   reply
  (resumes with value) ◄── resolves the Promise
                              │
                   on socket drop: retryStrategy(times) → delay
                   on reconnect:   replay queued cmds, re-subscribe
```

1. **Promise-native, callback-compatible.** The trailing-argument rule (`fn` → callback, else → promise) means ioredis is one API that serves both styles. In 2024+ code you always `await`.

2. **Connection is a managed resource.** You don't reconnect, you don't parse RESP, you don't track sequence numbers. `retryStrategy` + `maxRetriesPerRequest` + offline queue are the three knobs that decide how a degraded Redis shows up to your handlers.

3. **Commands are pass-through.** Lowercase Redis command name + spread args. Forward-compatible forever; you give up per-command TS arg-typing to get it.

**Why it's designed this way:** the promise-native surface aligns ioredis with `async`/`await` without forcing it (callbacks still work for legacy code), the eager-connect + offline-queue combo means "just construct and use" works even when Redis is briefly unavailable, and `retryStrategy` as a *function* (not a static config object) lets you encode arbitrary backoff curves — linear, exponential, jittered — per deployment. fred.rs ([`../../rust/fred.rs/01-basic-redis-client.md`](../../rust/fred.rs/01-basic-redis-client.md)) makes the same design choices in Rust: builder-configured connection, `init().await`, `on_error`/`on_reconnect` handlers, strongly-typed replies.

> **Cross-language note:** Rust's [`fred.rs`](../../rust/fred.rs/01-basic-redis-client.md) is ioredis's closest analog — both wrap RESP in a high-level, async, reconnect-aware client with cluster/sentinel/pipeline/pub-sub. **Go has no Redis client in its standard library**; the ecosystem default is [`github.com/redis/go-redis/v9`](https://github.com/redis/go-redis) (third-party), which mirrors ioredis's promise-native ergonomics via Go's context-and-error returns rather than Promises.

**Further exploration:** construct a client with `lazyConnect: true`, wire `redis.on("error", ...)` and `redis.on("reconnect", delay => ...)`, then `await redis.connect()` and observe the event sequence. Kill the Redis process mid-session and watch the client move through `close → reconnecting → ready` while commands issued during the outage replay on reconnect.
