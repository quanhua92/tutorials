# Cluster Mode: Sharding, Slots & Transparent Redirects

**Example/Doc Source:** [redis/ioredis README — Cluster](https://github.com/redis/ioredis#cluster) (see also [Redis Cluster specification](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/))

## The Core Concept: Why This Example Exists

**The Problem:** A single Redis instance tops out where one machine's memory, CPU, and network meet — and a standalone primary is a single point of failure. When your dataset outgrows one node, or you need high availability without an external sentinel layer, you need to spread data across **many** Redis processes while presenting callers with what looks like one logical database.

**The Solution:** Redis Cluster shards data across multiple primaries, each owning a slice of a fixed **16,384 hash-slot** space. Every key is mapped to exactly one slot (`CRC16(key) mod 16384`), and that slot lives on exactly one primary. The cluster keeps replicas for failover. ioredis's `Redis.Cluster` client hides almost all of this: you give it a few seed nodes, it discovers the full topology, and when it hits a `MOVED`/`ASK` redirect (a key living on a node it didn't expect) it transparently re-sends the command to the right node and refreshes its slot map.

Think of it like a post office with thousands of mailboxes: the **address** (key) deterministically maps to one **box** (slot) owned by one **branch** (node). ioredis is the courier that always knows which branch holds the box — and, if a branch reorganizes mid-delivery, reads the "moved" sticker and reroutes without bothering you.

## Practical Walkthrough: Code Breakdown

### Connecting to a Cluster

You don't list every node — just a few seeds so that if one is down the others work. ioredis discovers the rest itself (from the ioredis README):

```javascript
const Redis = require("ioredis");

const cluster = new Redis.Cluster([
  {
    port: 6380,
    host: "127.0.0.1",
  },
  {
    port: 6381,
    host: "127.0.0.1",
  },
]);

cluster.set("foo", "bar");
cluster.get("foo", (err, res) => {
  // res === 'bar'
});
```

How this works under the hood:

- `Redis.Cluster([...startup nodes...])` connects to the first reachable seed.
- It then runs `CLUSTER SLOTS` to learn the full slot→node map and opens pooled connections to every primary (and replicas, per `scaleReads`).
- `cluster.set("foo", ...)` hashes `"foo"` → slot → picks the owning node → issues `SET` there. From your code's perspective it's just `redis.set`.
- The startup list "does not need to enumerate all your cluster nodes … the client will discover other nodes automatically when at least one node is connected."

### Transparent `MOVED` / `ASK` Redirection

During failovers or resharding, a command may land on the wrong node. Redis answers with a `MOVED <slot> <host:port>` (the slot has permanently moved) or `ASK <slot> <host:port>` (temporary, mid-migration). ioredis intercepts these and re-issues the command to the correct node, so application code usually never sees them. The control knob is `maxRedirections`:

- `maxRedirections` (default **16**) caps how many times a single command will be redirected before it fails.
- Related timers: `retryDelayOnFailover` (default `100`ms) waits before retrying when the target node is disconnected, and you should ensure `retryDelayOnFailover * maxRedirections > cluster-node-timeout` so no command fails during a failover.
- After a redirect, ioredis refreshes its slot cache, so subsequent commands for that slot go straight to the new owner.

### Read/Write Splitting with `scaleReads`

A cluster typically has several primaries each with replicas. By default ioredis sends **everything** to primaries. `scaleReads` lets reads fan out (from the ioredis README):

```javascript
const cluster = new Redis.Cluster(
  [
    /* nodes */
  ],
  {
    scaleReads: "slave",
  }
);
cluster.set("foo", "bar"); // This query will be sent to one of the masters.
cluster.get("foo", (err, res) => {
  // This query will be sent to one of the slaves.
});
```

The four modes:

1. `"master"` (default) — all queries to the primary; never reads replicas.
2. `"all"` — writes to primary; reads to primary *or* any replica, randomly.
3. `"slave"` — writes to primary; reads to replicas.
4. a custom `function(nodes, command): node` — pick the read target yourself (the first entry in `nodes` is always the slot's primary).

Caveat the README calls out explicitly: with read splitting, a `get` right after a `set` may return stale data "because of the lag of replication between the master and slaves."

### The Cross-Slot Constraint — and Hash Tags

This is the single biggest behavioral difference from standalone Redis. Quoting the ioredis README's *Transaction and Pipeline in Cluster Mode*:

> 0. All keys in a pipeline should belong to slots served by the same node, since ioredis sends all commands in a pipeline to the same node.
> 1. You can't use `multi` without pipeline (aka `cluster.multi({ pipeline: false })`). This is because … ioredis doesn't know which node the `multi` command should be sent to.

Because a command (or pipeline/transaction) is routed by hashing *one* of its keys to *one* node, any operation touching **multiple keys must have all those keys land in the same slot**. The escape hatch is **hash tags** — the substring inside `{...}` is what gets hashed:

```javascript
// These three keys are forced into the SAME slot (hash tag "{acct1}"),
// so they live on the same node and can be used together:
cluster.mget("{acct1}:profile", "{acct1}:balance", "{acct1}:prefs"); // OK
cluster.multi().incr("{acct1}:balance").hset("{acct1}:profile", "x","y").exec(); // OK

// Without a hash tag, these likely live on DIFFERENT nodes → CROSSSLOT error:
cluster.mget("acct1:balance", "acct2:balance"); // may fail: not the same slot
```

Design your key namespace around the access pattern: group everything you'll touch atomically under one `{tag}`.

### Talking to Specific Nodes: `Cluster#nodes()`

Some commands aren't key-bound (`INFO`, `KEYS`, `FLUSHDB`) — ioredis sends those to a random node. To target many nodes deliberately, fetch the connection list (from the ioredis README):

```javascript
// Send `FLUSHDB` command to all slaves:
const slaves = cluster.nodes("slave");
Promise.all(slaves.map((node) => node.flushdb()));

// Get keys of all the masters:
const masters = cluster.nodes("master");
Promise.all(
  masters.map((node) => node.keys())
);
```

`cluster.nodes(role)` accepts `"master"`, `"slave"`, or `"all"` (default) and returns an array of `Redis` instances — handy for admin sweeps, scatter-gather analytics, or per-node health checks.

### Resilience Knobs Worth Knowing

From the README's option list, the ones that matter most operationally:

- `clusterRetryStrategy(times)` — fired when **no** startup node is reachable; return a ms delay to retry from scratch, or anything non-numeric to give up. You can even rewrite `this.startupNodes` mid-strategy to fail over to a known-good seed list.
- `clusterNodeRetryStrategy(times)` — per-node reconnect (by default ioredis does *not* retry a lost node, it waits for a `MOVED` to refresh slots). Useful for replicas that restart without slot changes.
- `slotsRefreshInterval` — periodic background slot refresh (off by default); `slotsRefreshTimeout` bounds each refresh (default `1000`ms).
- `enableReadyCheck` — gates the `ready` event on `CLUSTER INFO` reporting the cluster is healthy.

## Mental Model: Thinking in Redis Cluster

**The Consistent-Hashing-Free Shard Map:**

```
Keyspace (any string key)
   │  CRC16(key) mod 16384
   ▼
┌──────────────────────── 16,384 hash slots ────────────────────────┐
│ slot 0 …………… slot 5460 │ slot 5461 … slot 10922 │ slot 10923 … 16383 │
│   Node A (primary)     │   Node B (primary)      │   Node C (primary) │
│   + replica A'         │   + replica B'          │   + replica C'     │
└────────────────────────┴─────────────────────────┴────────────────────┘

   ioredis keeps this map in memory; a MOVED reply rewrites it on the fly.
```

1. **Deterministic placement.** A key always belongs to exactly one slot, and a slot to exactly one primary. There is no coordinator hop per command — the client computes the slot locally.

2. **Transparent redirect.** When the client guesses wrong (stale map during a failover/reshard), the server says `MOVED 11921 10.0.0.5:6379`, the client refreshes, and life goes on — `maxRedirections` bounds the chaos.

3. **Replicas give HA + read scale, not write scale.** Writes always go to the owning primary; replicas asynchronously copy. Read-splitting trades freshness for throughput.

**Why Cluster is designed this way:**

- **Horizontal scale** — dataset and write throughput grow with the number of primaries (shards).
- **Built-in HA** — primaries failing over to replicas without an external sentinel, though ioredis also supports [Sentinel](https://github.com/redis/ioredis#sentinel) for non-clustered HA.
- **Client-side routing** — no proxy in the data path, so latency stays low; the slot map is small enough to hold per client.

**Standalone vs. Cluster vs. Sentinel — when to reach for which:**

| Topology | Best for | Trade-off |
|---|---|---|
| `new Redis()` standalone | Single node, simple ops, small dataset | One machine's limits; SPOF |
| Sentinel | HA for a single primary + replicas, no sharding | Extra sentinel processes; not horizontally scalable |
| `Redis.Cluster` | Large dataset / high write throughput, sharded + HA | Cross-slot limits, eventual read consistency, ops complexity |

**Common Cluster Patterns:**
- **Multi-tenant keynamespacing** with hash tags so one tenant's keys co-locate (`{tenant42}:*`).
- **Scatter-gather analytics** via `cluster.nodes("master")` to run an aggregation on every shard.
- **Read-heavy workloads** with `scaleReads: "all"` to offload reads to replicas.
- **Cloud hosting** behind a NAT — use the `natMap` option so internal addresses map to reachable external ones.

## Pitfalls

- **`CROSSSLOT` errors.** Multi-key commands (`MGET`, `MSET`, `SUNION`, pipelines, transactions) across keys in different slots fail — unless a shared hash tag forces them together. This is the #1 surprise migrating standalone code to cluster.
- **No multi-key operations across slots, period** — not even inside a transaction or pipeline. Plan hash tags up front; retrofitting them later means migrating keys.
- **No `cluster.multi({ pipeline: false })`.** ioredis can't route a non-pipelined `MULTI` to a node, so cluster transactions are always pipelined (single round-trip) and must stay single-slot.
- **`KEYS`/`SCAN` are per-node.** They only see the slice of keyspace on the node they hit. Iterate `cluster.nodes()` to cover everything, or use `scanStream` per node.
- **Pub/Sub is cluster-wide** (a channel fans out to all nodes), but `SPUBLISH`/`SSUBSCRIBE` (sharded pub/sub, Redis 7.0+) is slot-bound — mind the distinction.
- **Replication lag on reads.** With `scaleReads` ≠ `"master"`, a read may trail the primary. Don't read-your-writes through replicas for anything consistency-sensitive.
- **Slot-map staleness after a failover.** Rely on `retryDelayOnFailover * maxRedirections > cluster-node-timeout`; otherwise commands can fail during the brief window a node is down.
- **`maxRetriesPerRequest` still applies** to the per-node connections — in cluster mode a long failover can surface as a request error if retries exhaust.

## Cross-References

- 🔗 **Curriculum:** [`../DEPLOYMENT.md`](../DEPLOYMENT.md) — distributed infrastructure, sharding, and high-availability topology; [`../DATABASE_DRIVERS.md`](../DATABASE_DRIVERS.md) — connection pooling and routing in data-layer drivers; [`../OBSERVABILITY.md`](../OBSERVABILITY.md) — tracing `MOVED`/`ASK` via ioredis diagnostics channels.
- 🔗 **This series:** [`./04-transactions-multi-exec.md`](./04-transactions-multi-exec.md) — the cross-slot constraint bites transactions hardest; [`./02-pipelines-batches.md`](./02-pipelines-batches.md) — same single-node routing rule.
- 🔗 **Cross-language:** the Rust analog [`../../rust/fred.rs/`](../../rust/fred.rs/) (fred.rs's clustered client handles the same slot/redirect model). Note: Go's standard library has **no** Redis client at all — cluster support only exists via third-party Go drivers (e.g. `go-redis`), so there is no stdlib cross-language sibling here.
