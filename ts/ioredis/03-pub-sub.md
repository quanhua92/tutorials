# Pub/Sub: Subscribe, Publish & the Subscriber-Mode Contract

**Doc Source**: [ioredis README — Pub/Sub](https://github.com/redis/ioredis#pubsub)

## The Core Concept: Why This Example Exists

**The Problem:** Request-response (GET/SET) is the wrong shape when the producer doesn't know who the consumers are — or when there are many of them, arriving and leaving dynamically. A chat server fanning a message to N connected clients, a cache invalidation broadcast to M app instances, a "user logged in" event any service may want to react to: in all of these, polling ("GET the latest? GET the latest?") is wasteful and a point-to-point queue (one producer → one consumer) doesn't fan out. You want **fire-and-forget broadcast**: drop a message on a named channel, and anyone currently listening gets a copy, with the publisher blissfully unaware of subscriber count.

**The Solution:** Redis Pub/Sub is a server-side fan-out primitive. Publishers call `PUBLISH channel message`; Redis looks up the set of subscribers for that channel and delivers a copy to each. ioredis maps this onto Node's `EventEmitter` so it feels native: `redis.subscribe(channel)` registers interest, and `redis.on("message", (channel, msg) => ...)` receives deliveries. The single hard rule — and the #1 footgun — is that **a connection enters "subscriber mode" the moment it calls `subscribe()`**, and from then on it can *only* run subscription-management commands (`subscribe`/`psubscribe`/`unsubscribe`/`punsubscribe`/`ping`/`quit`). To publish from the same process, you need a **second** `Redis` connection. This is ioredis's direct analog of Rust's [`fred.rs` subscriber client](../../rust/fred.rs/03-publish-subscribe.md), where `SubscriberClient` is a dedicated role that auto-re-subscribes on reconnect.

## Practical Walkthrough: Code Breakdown

### Publisher — Just `publish(channel, msg)`

```javascript
// publisher.js

const Redis = require("ioredis");
const redis = new Redis();

setInterval(() => {
  const message = { foo: Math.random() };
  // Publish to my-channel-1 or my-channel-2 randomly.
  const channel = `my-channel-${1 + Math.round(Math.random())}`;

  // Message can be either a string or a buffer
  redis.publish(channel, JSON.stringify(message));
  console.log("Published %s to %s", message, channel);
}, 1000);
```

*Source: [ioredis README — Pub/Sub](https://github.com/redis/ioredis#pubsub) — `publisher.js`*

Nothing special about a publishing connection — it's an ordinary client whose command happens to be `PUBLISH`. The message payload is a string or a `Buffer`; ioredis does no serialization for you, so `JSON.stringify` (or your codec of choice) is your job. Redis does **not** persist published messages — if no subscriber exists at publish time, the message is gone.

### Subscriber — `subscribe()` + the `"message"` Event

```javascript
// subscriber.js

const Redis = require("ioredis");
const redis = new Redis();

redis.subscribe("my-channel-1", "my-channel-2", (err, count) => {
  if (err) {
    // Just like other commands, subscribe() can fail for some reasons,
    // ex network issues.
    console.error("Failed to subscribe: %s", err.message);
  } else {
    // `count` represents the number of channels this client are currently subscribed to.
    console.log(
      `Subscribed successfully! This client is currently subscribed to ${count} channels.`
    );
  }
});

redis.on("message", (channel, message) => {
  console.log(`Received ${message} from ${channel}`);
});

// There's also an event called 'messageBuffer', which is the same as 'message' except
// it returns buffers instead of strings.
// It's useful when the messages are binary data.
redis.on("messageBuffer", (channel, message) => {
  // Both `channel` and `message` are buffers.
  console.log(channel, message);
});
```

*Source: [ioredis README — Pub/Sub](https://github.com/redis/ioredis#pubsub) — `subscriber.js`*

Two things to internalize:

1. **`subscribe(channels..., cb)`** is a command like any other — it can fail (network) and its callback receives `count` = the total number of channels this client is now subscribed to (not the count you just added). You can also `await redis.subscribe(...)` in promise mode.
2. **Deliveries come through the EventEmitter.** The `"message"` event fires with `(channel, message)` for every `PUBLISH` on a subscribed channel. Use `"messageBuffer"` when payloads are binary — the string variant would corrupt non-UTF-8 bytes.

> 🔗 [`../CONCURRENCY_PATTERNS.md`](../CONCURRENCY_PATTERNS.md) — ioredis *is* an `EventEmitter`, and `redis.on("message", ...)` is exactly the synchronous-listener model that bundle covers: every registered listener is called in registration order on the same event-loop tick, a thrown listener propagates to `process.on('uncaughtException')` unless wrapped, and `prependOnceListener` / `removeListener` behave as documented. The only ioredis-specific twist is that the events are **driven by socket reads**, not by your code calling `.emit()`.

### The Two-Connection Rule

This is the part everyone gets wrong once. A subscribed connection is locked into subscriber mode:

> "It's worth noticing that a connection (aka a `Redis` instance) can't play both roles at the same time. More specifically, when a client issues `subscribe()` or `psubscribe()`, it enters the 'subscriber' mode. From that point, only commands that modify the subscription set are valid. Namely, they are: `subscribe`, `psubscribe`, `unsubscribe`, `punsubscribe`, `ping`, and `quit`. When the subscription set is empty (via `unsubscribe`/`punsubscribe`), the connection is put back into the regular mode."
>
> *Source: [ioredis README — Pub/Sub](https://github.com/redis/ioredis#pubsub)*

If you want pub/sub in the same process, open two connections:

```javascript
const Redis = require("ioredis");
const sub = new Redis();
const pub = new Redis();

sub.subscribe(/* ... */); // From now, `sub` enters the subscriber mode.
sub.on("message" /* ... */);

setInterval(() => {
  // `pub` can be used to publish messages, or send other regular commands (e.g. `hgetall`)
  // because it's not in the subscriber mode.
  pub.publish(/* ... */);
}, 1000);
```

*Source: [ioredis README — Pub/Sub](https://github.com/redis/ioredis#pubsub)*

The `pub` connection is a normal client that *also* happens to publish; it can run `GET`, `HGETALL`, pipelines, transactions, anything. The `sub` connection is walled off until you `unsubscribe` from everything.

### Pattern Subscriptions: `psubscribe` / `"pmessage"`

When you don't know channel names up front (or want one subscription to cover a namespace), subscribe by **glob pattern**:

```javascript
redis.psubscribe("pat?ern", (err, count) => {});

// Event names are "pmessage"/"pmessageBuffer" instead of "message/messageBuffer".
redis.on("pmessage", (pattern, channel, message) => {});
redis.on("pmessageBuffer", (pattern, channel, message) => {});
```

*Source: [ioredis README — Pub/Sub](https://github.com/redis/ioredis#pubsub)*

Note the event arity differs: `"message"` gives `(channel, message)` (2 args), `"pmessage"` gives `(pattern, channel, message)` (3 args — you need the matched pattern to disambiguate when several patterns could match the same channel). The glob syntax is Redis's (`?`, `*`, `[...]`), not regex.

### Auto-Replay of Subscriptions on Reconnect

ioredis silently re-subscribes after a reconnect by default (`autoResubscribe: true`, see [01-basic-client.md](./01-basic-client.md)). That means a momentary network blip doesn't drop your listener permanently — but there *is* a delivery gap during the outage: messages published while the subscriber is disconnected are **lost** (Redis Pub/Sub is fire-and-forget, not a durable log). If you need durability, use Redis **Streams** (`XADD`/`XREAD`) instead — ioredis supports them, but they're a different model.

> **Pitfall — silently lost messages.** Pub/Sub has no persistence and no replay. A subscriber that's slow, disconnected, or crashed misses every message sent during that window. For fan-out that *must not* lose data (job dispatch, audit events), use Streams or an external broker. Pub/Sub is for ephemeral, "best-effort" fan-out: presence, live UI push, cache invalidation where a missed event just means a stale read until the next refresh.
>
> **Pitfall — one slow listener blocks the rest.** Because deliveries are synchronous EventEmitter emissions, a listener that does heavy work (or `await`s without offloading) stalls the next message. Move expensive handling onto a queue / worker thread, or accumulate into a buffer and process in batches.
>
> **Pitfall — trying to `GET` on the subscriber connection.** The moment you `subscribe()`, every non-subscription command throws. The error message is not always obvious in the heat of debugging. If you see "unknown command" or similar on a connection you `subscribe`d to, you've hit the subscriber-mode wall — spin up a second client.

## Mental Model: Thinking in Pub/Sub

**The Radio Tower Analogy:** The publisher is a radio station; the channel name is the frequency; subscribers are radios tuned to that frequency. The station broadcasts whether anyone is listening or not; radios receive only while powered on and tuned in; turn the radio off (disconnect) and you miss everything broadcast during the outage — there's no rewind.

```
Publisher (pub connection)            Redis server              Subscribers (sub connections)
   redis.publish("orders", payload) ──►  channel "orders"  ──┬──► sub1.on("message")   (orders)
                                                            ├──► sub2.on("message")   (orders)
                                                            └──► sub3 psubscribe("ord*")  → pmessage
                          ▲
                          │  pub is a NORMAL client: can also GET/SET/run transactions.
                          │  sub is LOCKED to subscriber mode: only (p)subscribe/(p)unsubscribe/ping/quit.
```

1. **Decoupled fan-out.** The publisher is ignorant of subscribers; zero subscribers is fine (the publish still "succeeds"); a thousand subscribers each get their own copy. This is what makes it scale horizontally for broadcast.

2. **Subscriber mode is a connection state, not a client type (in ioredis).** Unlike fred.rs's dedicated `SubscriberClient`, a plain ioredis `Redis` connection *becomes* a subscriber on `subscribe()` and *reverts* to a normal client when its subscription set empties. You usually don't revert in practice — keep dedicated subscriber connections.

3. **No durability, no ordering across the gap.** Within a stable connection, messages arrive in publish order on each channel. Across a disconnect, the sequence has a hole. Cross-channel ordering is not guaranteed.

**Why it's designed this way:** mapping Pub/Sub onto Node's `EventEmitter` means everything you already know about `.on`/`.off`/`.once`/`prependListener` carries over — the only new primitive is `subscribe(channel)` and the constraint that *one socket can't be both*. The two-connection rule exists because Redis itself enforces subscriber mode at the protocol level (RESP); ioredis is faithfully surfacing a server-side constraint, not inventing one.

> 🔗 [`../WEBSOCKETS_SSE.md`](../WEBSOCKETS_SSE.md) — Redis Pub/Sub is the classic **fan-out backend** behind HTTP SSE and WebSocket servers: each browser client holds an SSE/WebSocket connection to your Node server; on the server you `redis.subscribe(channel)` once (per process) and, in the `"message"` handler, forward the payload to the relevant SSE/WebSocket streams. The browser-facing protocol (SSE `event:`/`data:` framing, WebSocket frames) is what that bundle covers; this file is the Redis-side delivery primitive that feeds it. The two-connection rule matters here: one `sub` connection feeds many SSE/WebSocket clients in the same process.

**When to reach for Pub/Sub vs alternatives:**
- **Pub/Sub** — ephemeral broadcast, presence, real-time UI push, cache invalidation where staleness is tolerable. Best-effort fan-out to N listeners.
- **Streams** (`XADD`/`XREAD`) — durable, replayable, consumer-group log. Use when a missed message is a bug.
- **Lists** (`LPUSH`/`BRPOP`) — point-to-point work queue (one producer → one consumer).
- **An external broker** (NATS, Kafka, RabbitMQ) — when Redis isn't your messaging tier.

> **Cross-language note:** Rust's [`fred.rs`](../../rust/fred.rs/03-publish-subscribe.md) is the exact conceptual sibling — same `publish(channel, msg)` / `on_message(...)` split, plus a dedicated `SubscriberClient` with `manage_subscriptions()` that *automatically re-subscribes* on reconnect (ioredis gets this for free via `autoResubscribe`). Both honor the subscriber-mode constraint at the protocol level. **Go has no stdlib Redis**; `github.com/redis/go-redis/v9` exposes `Subscribe()` returning a `*PubSub` whose `Channel()` yields a `<-chan *Message` — the channel-based delivery maps cleanly onto Go's concurrency model where ioredis uses an EventEmitter.

**Further exploration:** start two subscriber processes (or two `Redis` connections in one process), subscribe both to the same channel, and confirm each receives every publish. Then `psubscribe("user:*")` and publish to `user:login` and `user:logout` — observe the 3-arg `(pattern, channel, message)` signature. Finally, kill the subscriber mid-stream for 5 seconds, publish during the gap, and confirm those messages are **not** redelivered on reconnect (the durability gap).
