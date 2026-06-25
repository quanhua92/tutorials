# Streams: XADD/XREAD & Consumer Groups

**Example/Doc Source:** [redis/ioredis README — Streams](https://github.com/redis/ioredis#streams) (see also the [Redis Streams introduction](https://redis.io/docs/latest/develop/data-types/streams/) and [`XADD`](https://redis.io/commands/xadd/), [`XREAD`](https://redis.io/commands/xread/), [`XREADGROUP`](https://redis.io/commands/xreadgroup/))

## The Core Concept: Why This Example Exists

**The Problem:** You need durable, ordered messaging between parts of your system. Pub/Sub is great for live fan-out — but if a subscriber is offline when a message is published, that message is gone forever. You want a **log**: producers append, consumers read at their own pace, replay missed history after a crash, and process the same events with multiple workers without losing any.

**The Solution:** Redis Streams are an append-only log data structure. Producers add entries with `XADD` (each entry gets a monotonic `id` and a set of field/value pairs); consumers read entries with `XREAD`, optionally **blocking** until new data arrives. For durable, multi-consumer processing, a **consumer group** (`XGROUP`/`XREADGROUP`/`XACK`) hands each entry to exactly one consumer in the group and tracks per-consumer progress — giving you at-least-once delivery with a pending-entries list for crash recovery. ioredis exposes every stream command via the same lowercase-method interface (`redis.xadd`, `redis.xread`, `redis.xgroup`, `redis.xreadgroup`, `redis.xack`, …).

Think of a stream as a Kafka-style append-only journal: messages persist with unique IDs, anyone can read from any offset, and consumer groups let a fleet of workers drain the log cooperatively — rather than Pub/Sub's megaphone, which only reaches whoever is listening *right now*.

## Practical Walkthrough: Code Breakdown

### Producing: Append with `XADD`

A stream entry is a set of field/value pairs. ioredis passes arguments straight through to the server, so `redis.xadd(stream, id, field, value, …)` maps directly to the Redis command (from the ioredis README):

```javascript
// Append an entry to "mystream" with an auto-generated id ("*").
redis.xadd("mystream", "*", "randomValue", Math.random());
```

Breaking down the arguments:

- `"mystream"` — the stream key (create-on-write: the stream appears the moment the first entry is added).
- `"*"` — let Redis auto-generate the id in `"<milliseconds>-<sequence>"` form (e.g. `1704862102584-0`). The sequence disambiguates entries added within the same millisecond.
- The remaining positional args are field/value pairs — `("randomValue", Math.random())` here, but you can pass several: `redis.xadd("mystream","*","user","alice","amount","42")`.
- The promise resolves to the generated id string, which you'll often want to keep.

### Consuming: Block-and-Read with `XREAD`

The README's canonical consumer blocks on the stream, processes each batch, then loops using the last-seen id (from the ioredis README):

```javascript
const Redis = require("ioredis");
const redis = new Redis();

const processMessage = (message) => {
  console.log("Id: %s. Data: %O", message[0], message[1]);
};

async function listenForMessage(lastId = "$") {
  // `results` is an array, each element of which corresponds to a key.
  // Because we only listen to one key (mystream) here, `results` only contains
  // a single element. See more: https://redis.io/commands/xread#return-value
  const results = await redis.xread("BLOCK", 0, "STREAMS", "mystream", lastId);
  const [key, messages] = results[0]; // `key` equals to "mystream"

  messages.forEach(processMessage);

  // Pass the last id of the results to the next round.
  await listenForMessage(messages[messages.length - 1][0]);
}

listenForMessage();
```

How this consumer works:

- `redis.xread("BLOCK", 0, "STREAMS", "mystream", lastId)` — `BLOCK 0` means "wait indefinitely until an entry newer than `lastId` exists."
- The `"STREAMS"` sentinel is followed by stream names and **then** the matching starting ids. With one stream you pass one id; with N streams you pass N ids.
- `lastId = "$"` means "only entries that arrive **after** I call this" (live tailing). Pass `"0"` (or a concrete id) to read **history** from the beginning (or from that point) — that's the replay capability Pub/Sub lacks.
- The reply is an array of `[streamKey, [ [id, [field, value, …]], … ]]`. `results[0]` is the first (here only) stream; `messages` is the list of `[id, fields]` pairs.
- After processing, the loop recurses with the newest id it saw, so each round resumes exactly where the last left off.

### Durable, Shared Processing: Consumer Groups

A bare `XREAD` loop gives you persistence and replay, but every reader sees *every* entry — fine for fan-out, wrong for a work queue. Consumer groups change that: the **group** owns a read position, and each entry is delivered to exactly **one** consumer in the group until that consumer acknowledges it. Unacknowledged entries stay in the group's Pending Entries List (PEL), so a crashed consumer's work can be claimed and retried. ioredis exposes each step as a method:

```javascript
const stream = "orders";
const group = "fulfillment";
const consumer = "worker-1";

// 1. Create the group once, starting to read from the very first entry.
//    MKSTREAM ("MK") creates the stream if it doesn't exist yet.
await redis.xgroup("CREATE", stream, group, "0", "MKSTREAM");

// 2. A worker claims and processes entries (block up to 5s for new work).
async function worker() {
  while (true) {
    // ">" means "entries never delivered to anyone in this group".
    const res = await redis.xreadgroup(
      "GROUP", group, consumer,
      "BLOCK", 5000,
      "COUNT", 10,
      "STREAMS", stream, ">"
    );
    if (!res) continue;                       // timed out with no new entries
    const [, entries] = res[0];               // entries: [ [id, [f,v,...]], ... ]
    for (const [id, fields] of entries) {
      await handleOrder(fields);              // your idempotent business logic
      await redis.xack(stream, group, id);    // 3. acknowledge → remove from PEL
    }
  }
}
```

What each piece does:

- **`XGROUP CREATE <stream> <group> <id>`** — registers the group. The starting id (`0` = from the beginning, `$` = only future entries) sets where the group begins. The trailing `"MKSTREAM"` option auto-creates an empty stream so the command won't error on first deploy.
- **`XREADGROUP GROUP <group> <consumer> … STREAMS <stream> >`** — the special id `">"` means "give me entries **never delivered** to *any* consumer in this group." Each delivered entry is recorded under `consumer`'s name in the PEL until acknowledged.
- **`XACK <stream> <group> <id>`** — marks the entry processed and removes it from the PEL. **At-least-once delivery:** if the process dies *after* `XREADGROUP` but *before* `XACK`, the entry stays pending and can be reclaimed (via `XPENDING`/`XCLAIM`) by another consumer after a timeout — so it may be processed twice. Make `handleOrder` idempotent.

### Producer ↔ Consumer Coordination (async)

The README pairs a producer and consumer in the same process; in practice they're separate services, but the async shape is identical:

```javascript
// Producer: one append per order
async function placeOrder(order) {
  const id = await redis.xadd(
    "orders", "*",
    "orderId", order.id,
    "total",   String(order.total),
    "items",   JSON.stringify(order.items)
  );
  return id;                                  // e.g. "1704862102584-0"
}

// Consumers: a pool of workers in the group drain the stream cooperatively
await Promise.all([worker(/* consumer: "worker-1" */), worker(/* "worker-2" */)]);
```

Because the group tracks delivery per consumer, scaling out is just starting more workers with distinct consumer names — Redis hands each entry to one of them automatically.

## Mental Model: Thinking in Redis Streams

**The Append-Only Event Log:**

```
Time →
┌──────────────────────── stream "orders" ────────────────────────┐
│ 1704862102584-0 : { orderId: "A1", total: "42", items: "[...]" } │
│ 1704862103589-0 : { orderId: "A2", total: "9",  items: "[...]" } │
│ 1704862104594-0 : { orderId: "A3", total: "77", items: "[...]" } │
└─────────────────────────────────────────────────────────────────┘
        ↑                                   ↑
   entry id (ms-seq)              structured fields (key/value pairs)

Consumer group "fulfillment"  →  read position + PEL
   worker-1  ◀── A1, A3   (acked: A1; pending: A3 if it crashed)
   worker-2  ◀── A2       (acked: A2)
```

1. **Append-only & monotonic.** Entries are added at the tail with ever-increasing ids and never mutated. Order within a stream is guaranteed.
2. **Structured, multi-field messages.** Unlike a Pub/Sub string blob, each entry carries multiple field/value pairs — no need to JSON-encode if you'd rather not (though you still can).
3. **Flexible read positions.** `$` tails live; `0` replays from the start; any concrete id resumes mid-stream. Consumer groups layer per-group and per-consumer cursors on top.
4. **At-least-once with groups.** Delivery is tracked, not fire-and-forget; unacked work survives a consumer crash and is reclaimable via `XCLAIM`.

**Streams vs. other Redis messaging:**

| Feature | Pub/Sub | Lists (BRPOP) | Streams |
|---|---|---|---|
| Persistence | No | Yes (until popped) | Yes (until trimmed) |
| Multiple consumers, each gets all msg | Yes | No | Yes (no group, or multiple groups) |
| Work-queue: one consumer per msg | — | Yes | Yes (consumer group) |
| Replay / history | No | Limited | Full (read any id/offset) |
| Ordering | No guarantee | FIFO | Time-ordered, monotonic ids |
| Crash recovery | None | Lost on pop | PEL + `XCLAIM` |

**Common Stream Patterns:**
- **Event sourcing / audit log** — append every domain event; reconstruct state by replaying.
- **Reliable task queue** — consumer group draining work with at-least-once + idempotent handlers.
- **Real-time fan-out** — multiple groups (billing, analytics, notifications) each consume the same stream independently.
- **CDC / inter-service messaging** — a durable replacement for Pub/Sub between microservices.

**Entry id format** `1704862102584-0`:
- **Timestamp (ms)** when the entry was added (`1704862102584`).
- **Sequence** within that millisecond (`0`), so two entries in the same ms still order correctly.

**Further Exploration:** add `MAXLEN`/`MINID` trimming to `XADD` (`redis.xadd("orders","MAXLEN","~","10000","*",…)`) to cap memory; use `XPENDING`/`XCLAIM`/`XAUTOCLAIM` to recover a stalled consumer's backlog; try reading from multiple streams in one `XREAD`; experiment with `XREAD` from `"0"` to replay versus `"$"` to tail.

## Pitfalls

- **At-least-once, not exactly-once.** A consumer that dies between `XREADGROUP` and `XACK` leaves the entry pending; when reclaimed it is **redelivered**. Handlers must be idempotent (dedupe by id, or use an idempotency key).
- **`">"` vs a concrete id in `XREADGROUP`.** `">"` = "never delivered to anyone"; passing a real id = "re-read this specific entry" (used with `XCLAIM`/`XAUTOCLAIM`). Mixing them up silently reprocesses or skips.
- **You must `XACK`.** Forgetting it leaves entries in the PEL forever, bloating memory and skewing delivery counts. Build acknowledgement into the same code path as success.
- **Streams grow without bound unless trimmed.** Use `MAXLEN ~ N` (approximate, fast) or `MINID` on `XADD`, or a scheduled `XTRIM`, to bound memory.
- **Blocking `XREAD`/`XREADGROUP` ties up a connection.** Each blocking reader holds a connection; use `BLOCK` with a finite timeout in a loop rather than many infinite `BLOCK 0` readers. (ioredis's `blockingTimeout` option adds a client-side safety net if the socket goes zombie.)
- **Field values are strings.** Redis stream field values are byte-strings — numbers and objects must be stringified (`String(n)` / `JSON.stringify`) on write and parsed on read. ioredis also offers `*Buffer` variants for binary payloads.
- **Consumer groups need a one-time `XGROUP CREATE`.** Re-creating an existing group errors; guard the first deploy (or use `MKSTREAM` to at least bootstrap the stream).
- **Pub/Sub is fire-and-forget (no replay).** Don't reach for Pub/Sub ([`./03-pub-sub.md`](./03-pub-sub.md)) when you need durability — use Streams. Conversely, don't use Streams for ephemeral live push to many transient subscribers when Pub/Sub is cheaper.

## Cross-References

- 🔗 **Curriculum:** [`../ASYNC_PATTERNS.md`](../ASYNC_PATTERNS.md) — producer/consumer and work-queue patterns; [`../WEBSOCKETS_SSE.md`](../WEBSOCKETS_SSE.md) — pushing stream events to browsers over WebSocket/SSE; [`../CONCURRENCY_PATTERNS.md`](../CONCURRENCY_PATTERNS.md) — at-least-once delivery, idempotency, and backpressure; [`../PROMISES.md`](../PROMISES.md) — `await`ing `xadd`/`xread`/`xack`.
- 🔗 **This series:** [`./03-pub-sub.md`](./03-pub-sub.md) — the fire-and-forget alternative Streams replaces when you need durability; [`./04-transactions-multi-exec.md`](./04-transactions-multi-exec.md) and [`./05-cluster.md`](./05-cluster.md) — stream keys are subject to the same cross-slot rules in cluster mode (hash-tag related streams to one node).
- 🔗 **Cross-language:** the Rust analog [`../../rust/fred.rs/06-redis-streams.md`](../../rust/fred.rs/06-redis-streams.md) (fred.rs's `xadd`/`xread_map`/`xgroup_create` — same commands, typed responses). Note: Go's standard library has **no** Redis client at all — stream support exists only via third-party Go drivers (e.g. `go-redis`), so there is no stdlib cross-language sibling here.
