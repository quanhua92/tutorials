# Client Pools: Scaling Redis Connections

**Source:** [02-client-pools.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/02-client-pools.rs)

## The Core Concept: Why This Example Exists

**The Problem:** A single Redis client can become a bottleneck under high load. When your application needs to perform many concurrent Redis operations, a single connection might not provide enough throughput. You need to distribute the load across multiple connections while maintaining simple, unified access.

**The Solution:** Fred's `RedisPool` creates multiple Redis clients working together as a single logical unit. Think of it like having multiple checkout lanes at a grocery store - customers (your Redis commands) are distributed round-robin across available lanes (client connections) to maximize throughput. The pool presents the exact same interface as a single client, so your code doesn't need to change.

## Practical Walkthrough: Code Breakdown

### Creating a Client Pool

```rust
let pool = Builder::default_centralized().build_pool(5)?;
pool.init().await?;
```

This creates a pool of 5 Redis clients:
- `default_centralized()` creates a builder with default settings for a single Redis server
- `build_pool(5)` creates 5 individual clients instead of a single client
- Each client in the pool maintains its own connection to Redis
- `init()` establishes all 5 connections concurrently

### Unified Interface

```rust
// These commands are distributed round-robin across the 5 clients
assert!(pool.get::<Option<String>, _>("foo").await?.is_none());
let _: () = pool.set("foo", "bar", None, None, false).await?;
assert_eq!(pool.get::<String, _>("foo").await?, "bar");
```

The key insight here is that `RedisPool` implements the same command traits as individual clients:
- Each command (`get`, `set`, `del`) automatically goes to the next client in rotation
- The pool handles load balancing transparently
- Your application code is identical to single-client usage

### Accessing Individual Clients

```rust
let _: () = pool.del("foo").await?;
// Access specific clients for advanced operations
let pipeline = pool.next().pipeline();
let _: () = pipeline.incr("foo").await?;
let _: () = pipeline.incr("foo").await?;
assert_eq!(pipeline.last::<i64>().await?, 2);
```

Sometimes you need access to specific clients:
- `pool.next()` returns the next client in the round-robin rotation
- This is useful for operations that must happen on the same connection (like pipelining)
- Pipelines require a single connection because they batch multiple commands

### Pool Introspection

```rust
for client in pool.clients() {
  println!("{} connected to {:?}", client.id(), client.active_connections());
}
```

Pools provide access to their constituent clients for monitoring:
- `pool.clients()` returns an iterator over all clients in the pool
- Each client has a unique ID and connection status
- This is useful for debugging, monitoring, and health checks

## Mental Model: Thinking in Fred Pools

**The Server Farm Analogy:** Think of a Redis pool like a server farm behind a load balancer:

```
Your App Commands
        ↓
    RedisPool (Load Balancer)
   ↙    ↓    ↓    ↓    ↘
Client1 Client2 Client3 Client4 Client5
   ↓     ↓     ↓     ↓     ↓
         Redis Server
```

1. **Transparent Load Balancing:** The pool distributes commands automatically. You don't need to manually choose which client to use - the pool handles this using round-robin selection.

2. **Connection Multiplexing:** Each client maintains its own connection, so the pool can handle 5x more concurrent operations than a single client. This is particularly valuable for workloads with many concurrent requests.

3. **Fault Tolerance:** If one client's connection fails, the other 4 continue working. The pool automatically retries failed commands on healthy clients.

**Why It's Designed This Way:** Pools solve the "shared resource" problem elegantly:
- **Performance:** Multiple connections increase throughput linearly up to Redis server limits
- **Simplicity:** Same interface as single clients means no code changes needed
- **Isolation:** Operations that need connection affinity (like pipelines) can access specific clients
- **Monitoring:** Pool composition is transparent for debugging

**Connection Affinity Consideration:** Some Redis operations require "stickiness" to a specific connection:
- **Pipelining:** Must use the same connection for batching commands
- **Transactions:** MULTI/EXEC blocks must execute on the same connection  
- **Subscriptions:** PubSub subscriptions are tied to specific connections

This is why Fred allows both pool-level operations (for general commands) and client-level access (for connection-specific operations).

**Further Exploration:** Try creating pools of different sizes and measuring throughput differences. Experiment with mixed workloads - some commands through the pool interface, others through specific clients. Notice how the round-robin distribution affects command ordering.

This example demonstrates Fred's philosophy of scaling without complexity - more performance through parallel connections, but with the same simple interface you already know.