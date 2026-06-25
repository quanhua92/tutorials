# Pub/Sub: Fan-Out Messaging with Subscribers

**Doc Source:** [redis-plus-plus README — Publish/Subscribe](https://github.com/sewenew/redis-plus-plus#publishsubscribe)

## The Core Concept: Why This Example Exists

**The Problem:** You have producers that emit events (a trade was filled, a sensor reading arrived, a user logged in) and a fluid set of consumers that care about subsets of those events. Point-to-point requests (one `GET` per consumer) don't scale and require consumers to poll. You want **push** delivery: the moment an event is published, every interested subscriber receives it, with Redis doing the routing.

**The Solution:** Redis [Pub/Sub](https://redis.io/docs/manual/pubsub/) is a fire-and-forget fan-out bus. Producers call `PUBLISH channel message`; every client currently `SUBSCRIBE`d to that channel (or matching a `PSUBSCRIBE` pattern) gets a copy. `redis-plus-plus` splits the two roles cleanly: `Redis::publish()` is just another command, but **subscribing is special** — a subscriber holds a dedicated connection and runs a blocking `consume()` loop, because subscribed connections can only receive messages, not run normal commands.

## Practical Walkthrough: Code Breakdown

### The Asymmetry: Publish vs. Subscribe

The README opens by stressing the asymmetry between the two roles:

> You can use `Redis::publish` to publish messages to channels. `Redis` randomly picks a connection from the underlying connection pool, and publishes message with that connection. So you might publish two messages with two different connections.
>
> When you subscribe to a channel with a connection, all messages published to the channel are sent back to that connection. So there's NO `Redis::subscribe` method. Instead, you can call `Redis::subscriber` to create a `Subscriber` and the `Subscriber` maintains a connection to Redis. The underlying connection is a new connection, NOT picked from the connection pool. This new connection has the same `ConnectionOptions` as the `Redis` object.
>
> *(Source: [Publish/Subscribe](https://github.com/sewenew/redis-plus-plus#publishsubscribe))*

This is the single most important design point:
- **Publishing is cheap and stateless** — it reuses the pool like any command.
- **Subscribing is stateful and exclusive** — a subscribed connection is wedged into "subscriber mode" by Redis itself; it can't run `GET`, `SET`, etc. So the library gives it a dedicated object (`Subscriber`) on its own connection.

### Per-Subscriber Connection Options

Because each subscriber owns its own connection, you may want different timeouts per subscriber. The pattern: build multiple `Redis` objects solely to spawn subscribers with different `ConnectionOptions`:

```c++
ConnectionOptions opts1;
opts1.host = "127.0.0.1";
opts1.port = 6379;
opts1.socket_timeout = std::chrono::milliseconds(100);

auto redis1 = Redis(opts1);

// sub1's socket_timeout is 100ms.
auto sub1 = redis1.subscriber();

ConnectionOptions opts2;
opts2.host = "127.0.0.1";
opts2.port = 6379;
opts2.socket_timeout = std::chrono::milliseconds(300);

auto redis2 = Redis(opts2);

// sub2's socket_timeout is 300ms.
auto sub2 = redis2.subscriber();
```
*(Source: [Publish/Subscribe](https://github.com/sewenew/redis-plus-plus#publishsubscribe))*

And the README's reassurance: *"Although the above code creates two `Redis` objects, it has no performance penalty. Because `Redis` object creates connections lazily... and the connection is created only when we call `Redis::subscriber` to create `Subscriber` object."* The `redis1`/`redis2` objects never open pool connections if you only use them to spawn subscribers.

### Registering Callbacks for the Six Message Types

A subscriber can receive six kinds of messages. You wire up callbacks for the ones you care about:

| Message type | Fired when | Callback signature |
| --- | --- | --- |
| `MESSAGE` | a message arrives on a subscribed channel | `void(std::string channel, std::string msg)` |
| `PMESSAGE` | a message matches a `PSUBSCRIBE`d pattern | `void(std::string pattern, std::string channel, std::string msg)` |
| `SUBSCRIBE` | ack for a successful `SUBSCRIBE` | `void(Subscriber::MsgType, OptionalString channel, long long num)` |
| `UNSUBSCRIBE` | ack for `UNSUBSCRIBE` | (same meta callback) |
| `PSUBSCRIBE` | ack for `PSUBSCRIBE` | (same meta callback) |
| `PUNSUBSCRIBE` | ack for `PUNSUBSCRIBE` | (same meta callback) |

Per upstream: `Subscriber::on_message(MsgCallback)`, `Subscriber::on_pmessage(PatternMsgCallback)`, and `Subscriber::on_meta(MetaCallback)`. *"All these callback interfaces pass `std::string` by value, and you can take their ownership (i.e. `std::move`) safely."* The meta callback's `channel` is `OptionalString` because *"if you haven't subscribe/psubscribe to any channel/pattern, and try to unsubscribe/punsubscribe without any parameter... `channel` will be null."*

### The Canonical Consumer Loop

The README's recommended pattern for a subscriber:

```C++
// Create a Subscriber.
auto sub = redis.subscriber();

// Set callback functions.
sub.on_message([](std::string channel, std::string msg) {
            // Process message of MESSAGE type.
        });

sub.on_pmessage([](std::string pattern, std::string channel, std::string msg) {
            // Process message of PMESSAGE type.
        });

sub.on_meta([](Subscriber::MsgType type, OptionalString channel, long long num) {
            // Process message of META type.
        });

// Subscribe to channels and patterns.
sub.subscribe("channel1");
sub.subscribe({"channel2", "channel3"});

sub.psubscribe("pattern1*");

// Consume messages in a loop.
while (true) {
    try {
        sub.consume();
    } catch (const Error &err) {
        // Handle exceptions.
    }
}
```
*(Source: [Examples](https://github.com/sewenew/redis-plus-plus#examples-1))*

The mechanics:
- `subscribe(channel)` / `subscribe({c1, c2})` / `psubscribe(pattern)` register interest — these are control commands sent on the subscriber's connection.
- `consume()` blocks waiting for the next message. When one arrives, it dispatches to whichever callback matches the message type. *"However, if you don't set callback for a specific kind of message, `Subscriber::consume` will consume the received message and discard it."*
- The loop is yours to own. Pub/Sub is a blocking, single-threaded-per-subscriber model.

### Handling Timeouts in the Loop

If you set `ConnectionOptions::socket_timeout`, `consume()` throws `TimeoutError` when no message arrives in time — which is normal, not an error. The idiomatic loop catches it and continues:

```C++
while (true) {
    try {
        sub.consume();
    } catch (const TimeoutError &e) {
        // Try again.
        continue;
    } catch (const Error &err) {
        // Handle other exceptions.
    }
}
```
*(Source: [Consume Messages](https://github.com/sewenew/redis-plus-plus#consume-messages))*

This is how you keep a subscriber alive but still periodically check a "should I shut down?" flag — set a short `socket_timeout`, and each loop iteration is an opportunity to inspect your stop condition.

### Publishing

Publishing needs no special object — it's a normal command on a pooled connection:

```cpp
redis.publish("channel1", "hello world");
redis.publish({"channel2", "payload"});   // initializer-list overload
```

Redis routes the message to every subscriber of `channel1`. If there are zero subscribers, the message is simply dropped (Redis Pub/Sub is **not** durable — see pitfalls).

### Publishing from a Cluster

`RedisCluster` exposes the identical interface: *"use `RedisCluster::publish` to publish messages, and use `RedisCluster::subscriber` to create a subscriber to consume messages."* See [Cluster Pub/Sub](https://github.com/sewenew/redis-plus-plus#publishsubscribe-1) and [`05-cluster.md`](05-cluster.md).

## Mental Model: Thinking in Pub/Sub

**The Radio Broadcast Analogy:** Publishing is a radio transmitter — it shouts into the ether whether or not anyone is tuned in. A subscriber is a radio tuned to a frequency (channel) or a band of frequencies (`PSUBSCRIBE` pattern). Switch off the radio (disconnect) for a second and you miss whatever was broadcast in that gap; there's no replay.

```
                    ┌───────────────┐
   Publisher ──────►│   Redis       │────► Subscriber A (channel1)
   redis.publish    │  Pub/Sub bus  │────► Subscriber B (channel1, channel2)
                    │  (no storage) │────► Subscriber C (pattern: news.*)
                    └───────────────┘
```

1. **Fire-and-forget, not durable.** Redis Pub/Sub has no persistence. If a subscriber is slow, disconnected, or not yet subscribed when a message is published, that message is gone. For durability use **Redis Streams** (`XADD`/`XREAD`) with consumer groups — see the README's [Redis Stream](https://github.com/sewenew/redis-plus-plus#redis-stream) section.

2. **One connection, one role.** A subscribed connection is in subscriber mode and cannot run ordinary commands. That's why the library separates `Subscriber` from `Redis` — and why each `Subscriber` gets its own connection, never a pool connection. *"Subscriber is NOT thread-safe. If you want to call its member functions in multi-thread environment, you need to synchronize between threads manually."*

3. **Back-pressure can kill the subscriber.** If a subscriber's callback is slow, Redis's per-subscriber output buffer fills; once it exceeds `client-output-buffer-limit pubsub`, Redis **force-disconnects** the subscriber and the library throws a non-`ReplyError`/non-`TimeoutError` exception. The README's blunt rule: *"If any of the `Subscriber`'s method throws an exception other than `ReplyError` or `TimeoutError`, you CANNOT use it any more. Instead, you have to destroy the `Subscriber` object, and create a new one."*

**Why It's Designed This Way:** The callback + blocking-`consume()`-loop shape maps directly onto Redis's wire protocol: a subscribed connection only ever receives `MESSAGE`/`PMESSAGE`/`SUBSCRIBE`/... frames, so the library translates each frame type into a callback dispatch. The dedicated-connection rule isn't a library choice — it's Redis's rule, faithfully reflected. Lazy pool creation on the publishing `Redis` object means spawning subscribers is cheap even if you build a throwaway `Redis` just for that purpose.

**Further Exploration:** Build a chat room: one publisher thread writes `chat:general` on keypress, N subscriber threads print incoming messages. Kill a subscriber mid-stream and confirm it loses any messages published while it was down — then re-implement the same demo with `XADD`/`XREADGROUP` (Streams) to see the durability difference. Try a `PSUBSCRIBE` pattern like `user:*:login` and publish to `user:42:login` to watch the pattern match.

## Pitfalls

- **No durability.** Disconnected or slow subscribers miss messages irrecoverably. Need replay/history? Use Streams, not Pub/Sub.
- **Slow callbacks get you killed.** A callback that blocks (DB write, HTTP call) fills Redis's subscriber buffer until Redis disconnects you. Offload slow work to another thread; keep callbacks fast.
- **Reusing a `Subscriber` after a fatal exception.** Per the README, after any exception other than `ReplyError`/`TimeoutError`, the object is dead — destroy and recreate.
- **Calling normal commands on a subscribed connection.** Not allowed by Redis. The library prevents this structurally (no `Redis` interface on `Subscriber`), but if you share the underlying connection manually you'll hit `ERR only (P)SUBSCRIBE / ...`.
- **Single-threaded consume loop.** One `Subscriber` = one thread calling `consume()`. For high fan-in, run multiple `Subscriber`s in multiple `std::thread`s, each with its own connection.
- **Forgetting `socket_timeout` means `consume()` blocks forever.** Then you have no clean shutdown path. Always set a timeout and use the `TimeoutError`-continue pattern to poll a stop flag.
- **`channel` in the meta callback can be null.** It's `OptionalString` for a reason — dereferencing blindly is UB when you `unsubscribe()` with no args.

## Cross-References

- 🔗 **Curriculum bundles:** Pub/Sub is the `CONCURRENCY` bundle's "message passing between threads/processes" case — pair it with `STD_THREAD` (one consumer thread per subscriber), `CONDITION_VARIABLES` (the local in-process analog of "wake up when a message arrives"), and `FUTURES_PROMISES` (single-delivery vs. fan-out delivery semantics).
- 🦀 **Rust sibling:** [`../rust/fred.rs/03-publish-subscribe.md`](../rust/fred.rs/03-publish-subscribe.md) — fred.rs subscribes via an async `on_message` event stream; the fan-out model is identical, the ergonomics differ (async stream vs. blocking `consume()` loop).
- 🟦 **TypeScript sibling:** [`../ts/ioredis/03-pub-sub.md`](../ts/ioredis/03-pub-sub.md) — ioredis exposes `redis.subscribe(channel, (msg) => ...)` event-emitter style; compare to redis-plus-plus's callback registration + explicit `consume()`.
- ⬅️ **Previous:** [`03-transactions.md`](03-transactions.md) — request/response atomicity. **Next:** [`05-cluster.md`](05-cluster.md) — scaling the same primitives across a sharded cluster.
