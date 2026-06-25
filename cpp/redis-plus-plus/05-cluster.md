# Redis Cluster: Sharded Client with MOVED/ASK Redirections

**Doc Source:** [redis-plus-plus README — Redis Cluster](https://github.com/sewenew/redis-plus-plus#redis-cluster) and the [Cluster example in Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started)

## The Core Concept: Why This Example Exists

**The Problem:** A single Redis instance caps out at the RAM/CPU of one machine and gives you no horizontal write scale. To go beyond that, Redis Cluster shards your keyspace across N master nodes (each with optional replicas). But sharding moves a problem onto the client: every key lives on exactly one node, so the client must compute *which* node for each command, follow redirections when the cluster is mid-reshard, and refuse operations that span multiple shards.

**The Solution:** `redis-plus-plus` ships a `RedisCluster` class with an API intentionally parallel to `Redis`. You point it at **any one** master node; it issues `CLUSTER SLOTS`, builds an in-memory *slot → node* map, hashes every key to a slot (CRC16, the Redis Cluster hash), and sends each command to the right node. If the cluster has moved a slot (`MOVED`) or is mid-migration (`ASK`), the client follows the redirect transparently and refreshes its map.

## Practical Walkthrough: Code Breakdown

### Connecting: One Seed Node Is Enough

You only specify one master's host/port. The library discovers the rest:

```C++
// Set a master node's host & port.
ConnectionOptions connection_options;
connection_options.host = "127.0.0.1";  // Required.
connection_options.port = 7000; // Optional. The default port is 6379.
connection_options.password = "auth"; // Optional. No password by default.

// Automatically get other nodes' info,
// and connect to every master node with a single connection.
RedisCluster cluster1(connection_options);

ConnectionPoolOptions pool_options;
pool_options.size = 3;

// For each master node, maintains a connection pool of size 3.
RedisCluster cluster2(connection_options, pool_options);
```
*(Source: [Connection](https://github.com/sewenew/redis-plus-plus#connection-1))*

The URI form also works:

```C++
// Specify a master node's host & port.
RedisCluster cluster3("tcp://127.0.0.1:7000");

// Use default port, i.e. 6379.
RedisCluster cluster4("tcp://127.0.0.1");
```
*(Source: [Connection](https://github.com/sewenew/redis-plus-plus#connection-1))*

Note the tradeoff the README calls out: with a URI you *"can only use default `ConnectionPoolOptions`, i.e. pool of size 1, and CANNOT specify password."* For real workloads, use the `ConnectionOptions` constructor.

Three hard constraints from the [Note](https://github.com/sewenew/redis-plus-plus#note-1) section:
- **TCP only** — `RedisCluster` cannot use Unix Domain Sockets; doing so throws.
- **All nodes share the same password.**
- **`ConnectionOptions::db` is ignored** — [Redis Cluster supports only database 0](https://redis.io/topics/cluster-spec#implemented-subset).

### Same API as `Redis` — Almost

Once connected, day-to-day commands look identical to the non-cluster client. From the Getting Started example:

```cpp
    // ***** Redis Cluster *****

    // Create a RedisCluster object, which is movable but NOT copyable.
    auto redis_cluster = RedisCluster("tcp://127.0.0.1:7000");

    // RedisCluster has similar interfaces as Redis.
    redis_cluster.set("key", "value");
    val = redis_cluster.get("key");
    if (val) {
        std::cout << *val << std::endl;
    }   // else key doesn't exist.
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

The library hashes `"key"` → slot → node, picks a pooled connection to that node, and runs the command. But two categories of commands **cannot** work transparently, per [Interfaces](https://github.com/sewenew/redis-plus-plus#interfaces):

> - Not support commands without key as argument, e.g. `PING`, `INFO`.
> - Not support Lua script without key parameters.
>
> Since there's no key parameter, `RedisCluster` has no idea on to which node these commands should be sent.

The workaround is `RedisCluster::redis(hash_tag)`, which returns a plain `Redis` pinned to the node that owns the hash-tag's slot:

```cpp
// Create a Redis object with hash-tag.
// It connects to the Redis instance that holds the given key, i.e. hash-tag.
auto r = redis_cluster.redis("hash-tag");

// And send command without key parameter to the server.
r.command("client", "setname", "connection-name");
```
*(Source: [Examples](https://github.com/sewenew/redis-plus-plus#examples-2))*

This is also how you run multi-key commands that must all land on one node.

### Hash Tags: Forcing Keys to One Slot

Multi-key operations (`MGET`, `MSET`, the `src`/`dst` of `RENAME`, pipeline/transaction batches) only work if every key hashes to the **same** slot. Redis Cluster's [hash tags](https://redis.io/topics/cluster-spec#keys-hash-tags) let you force that: only the substring inside `{...}` participates in the slot computation.

```cpp
    // Keys with hash-tag.
    redis_cluster.set("key{tag}1", "val1");
    redis_cluster.set("key{tag}2", "val2");
    redis_cluster.set("key{tag}3", "val3");

    std::vector<OptionalString> hash_tag_res;
    redis_cluster.mget({"key{tag}1", "key{tag}2", "key{tag}3"},
            std::back_inserter(hash_tag_res));
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

All three keys share the `{tag}` substring, so all three map to the same slot and the cross-key `MGET` is legal. Without the tag, `MGET` across different slots would throw `CROSSSLOT` from Redis.

### Pipelines and Transactions in a Cluster

Because a pipeline or transaction must run on a single connection to a single node, the cluster variants take a **hash-tag** to pin the node:

```C++
Pipeline RedisCluster::pipeline(const StringView &hash_tag, bool new_connection = true);

Transaction RedisCluster::transaction(const StringView &hash_tag, bool piped = false, bool new_connection = true);
```
*(Source: [Pipeline and Transaction](https://github.com/sewenew/redis-plus-plus#pipeline-and-transaction))*

From the Getting-Started example:

```cpp
    // Pipeline.
    auto pipe = redis_cluster.pipeline("counter");
    auto replies = pipe.incr("{counter}:1").incr("{counter}:2").exec();

    // Transaction.
    auto tx = redis_cluster.transaction("key");
    replies = tx.incr("key").get("key").exec();
```
*(Source: [Getting Started](https://github.com/sewenew/redis-plus-plus#getting-started))*

The `"counter"` hash-tag picks the node; both keys `"{counter}:1"` and `"{counter}:2"` must hash to that same node (they do, because of the shared `{counter}` tag). Mismatch and the command will fail server-side.

### MOVED/ASK Redirection Handling

Cluster topologies shift: slots get resharded, nodes join/leave, replicas get promoted. When you send a command to the wrong node, Redis replies with a redirection:

- **`MOVED <slot> <ip:port>`** — the slot has permanently moved. A complete client must re-issue the command to the new node and update its slot map.
- **`ASK <slot> <ip:port>`** — the slot is mid-migration; the next command (only) must be sent to the new node after a one-shot `ASKING`.

The README's [Details](https://github.com/sewenew/redis-plus-plus#details) section is unequivocal:

> `redis-plus-plus` is able to handle both [MOVED](https://redis.io/topics/cluster-spec#moved-redirection) and [ASK](https://redis.io/topics/cluster-spec#ask-redirection) redirections, so it's a complete Redis Cluster client.

And it handles failover too:

> - When the master is down, *redis-plus-plus* losts connection to it. In this case, if you try to send commands to this master, *redis-plus-plus* will try to update slot-node mapping from other nodes...
> - When the new master has been elected, the slot-node mapping will be updated by the cluster.

Plus, *"Since redis-plus-plus 1.3.13, it also updates the slot-node mapping every `ClusterOptions::slot_map_refresh_interval` time interval (by default, it updates every 10 seconds)."* So the map self-heals on three triggers: a redirection, a failed-node reconnect, and a periodic background refresh.

### Reading from Replicas

For read-heavy workloads you can opt into possibly-stale reads from replicas:

```C++
RedisCluster cluster(connection_options, pool_options, Role::SLAVE);

auto val = cluster.get("key");
```
*(Source: [Read From Replica](https://github.com/sewenew/redis-plus-plus#read-from-replica))*

Caveats: *"you can only send readonly commands... If you try to send a write command, e.g. `set`, `hset`, *redis-plus-plus* will throw an exception."* The library sends `READONLY` to the replicas for you — don't do it manually.

## Mental Model: Thinking in Redis Cluster

**The Mail-Sorting Office Analogy:** A non-cluster `Redis` is a single post office — every letter goes to the same building. A `RedisCluster` is a city-wide network of post offices (16384 mail routes = slots), and your envelope's ZIP code (the slot, computed from the key) determines which building handles it. `RedisCluster` is your automatic mail-forwarding service: it knows the route map, and when a route gets reassigned (`MOVED`), it relabels and re-sends without bothering you.

```
            ┌──────────────────────────────┐
   key ───► │ CRC16(key) mod 16384 = slot  │ ───► slot → node map ───►  Node holding that slot
            └──────────────────────────────┘                              │
                                                                         │ (if wrong node)
                                                                         ▼
                                                            MOVED/ASK ◄──── ────► follow redirect,
                                                                                            refresh map
```

1. **The slot map is the source of truth.** `RedisCluster` keeps a `slot → {host, port}` table in memory, populated by `CLUSTER SLOTS` at startup and kept fresh via redirects + the 10s periodic refresh. Commands are O(1) — hash, lookup, send.

2. **Keys are isolated by slot.** Any operation touching more than one slot is rejected by Redis (`CROSSSLOT`). Hash tags (`{tag}`) are the *only* way to colocate keys for multi-key commands. Design your key namespace around this from day one — retrofitting hash tags onto a live system is painful.

3. **`RedisCluster::redis()` returns a non-thread-safe object.** Per upstream: *"the returned `Redis` object, **IS NOT THREAD SAFE!**. Also, when using the returned `Redis` object, if it throws exception, you need to destroy it, and create a new one."* Use it in the thread that created it, and throw it away on error.

**Why It's Designed This Way:** `RedisCluster` mirrors the `Redis` API so that single-key code ports verbatim — the sharding is invisible for the common case. The divergences (hash-tag parameters on pipeline/transaction, the `redis()` escape hatch for keyless commands) exist precisely because the cluster protocol forces them: Redis Cluster *requires* the client to know which node a command targets, and keyless commands have no such signal. Handling MOVED/ASK in the client (rather than erroring out) is what makes the library "complete" by the official cluster spec.

**Further Exploration:** Spin up a local 3-master, 3-replica cluster (the [`redis-cli --cluster create`](https://redis.io/docs/manual/scaling/) one-liner) and use `CLUSTER KEYSLOT mykey` to predict which node holds a key. Then run `redis-cli -c` (cluster mode) and `redis-cli` (non-cluster) against the same node to see a `MOVED` reply firsthand. With `RedisCluster`, write 10,000 random keys and watch the per-node key distribution with `CLUSTER COUNTKEYSINSLOT`.

## Pitfalls

- **`CROSSSLOT` errors.** Any multi-key command spanning >1 slot fails. Either use hash tags, or split into per-slot batches.
- **No DB selection.** `ConnectionOptions::db` is silently ignored — Cluster only allows DB 0.
- **`PING`/`INFO`/`FLUSHALL` without a target.** `RedisCluster` can't route them; use `redis_cluster.redis("some-key")` to pin a node, or loop over all nodes yourself.
- **Mixing `Role::SLAVE` with writes.** Throws. Replicas are read-only by design; don't try.
- **Hash-tag typos.** `{user:42}:profile` vs `{user:42}:cart` share a slot; `{user:42}:profile` vs `{user:43}:cart` do **not** (different tag content). A typo silently splits your data across nodes and you'll see it only as `CROSSSLOT`.
- **Treating `redis_cluster.redis(tag)` as thread-safe.** It isn't — keep it on one thread and recreate after any exception.
- **Forgetting that Cluster Pub/Sub is global.** `PUBLISH`/`SUBSCRIBE` work, but published messages are forwarded to all nodes, so a single channel isn't sharded. For per-slot message routing use **sharded Pub/Sub** (`SPUBLISH`/`SSUBSCRIBE`, Redis 7.0+) via the generic command interface.
- **Different node passwords.** All nodes must share one password; mixed-credential clusters won't work with `RedisCluster`.

## Cross-References

- 🔗 **Curriculum bundles:** Cluster ties together the whole `CONCURRENCY` bundle — connection pooling per node (`STD_THREAD`), redirect-driven async-style state updates (compare to `FUTURES_PROMISES`), and the hashing math (a CRC16, conceptually adjacent to `ATOMICS_MEMORY_ORDER`'s "atomic → derived computation" patterns). The redirect loop is a real-world analog of condition-variable wait/notify.
- 🦀 **Rust sibling:** [`../rust/fred.rs/`](../rust/fred.rs/) — fred.rs is cluster-aware with the same MOVED/ASK handling and slot-map refresh; compare the in-memory slot-map update strategies.
- 🟦 **TypeScript sibling:** [`../ts/ioredis/05-cluster.md`](../ts/ioredis/05-cluster.md) — ioredis exposes `new Cluster([{host, port}])` with the same seed-node + auto-discovery model; cross-language comparison highlights that the Redis Cluster spec (not the client) dictates most behavior.
- ⬅️ **Previous:** [`04-pub-sub.md`](04-pub-sub.md) — fan-out messaging; in a cluster, `publish`/`subscribe` work globally but aren't sharded per slot.
