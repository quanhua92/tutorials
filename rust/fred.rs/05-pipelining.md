# Pipelining: Optimizing Network Round-Trips

**Source:** [05-pipelining.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/05-pipelining.rs)

## The Core Concept: Why This Example Exists

**The Problem:** Network latency kills performance when you need to execute many Redis commands sequentially. If each command waits for a response before sending the next one, you're paying the full round-trip time for every single command. With 50 commands and 1ms network latency, you're looking at 50ms just waiting for the network.

**The Solution:** Redis pipelining lets you send multiple commands without waiting for responses, then read all the responses at once. Fred's pipeline interface (`client.pipeline()`) queues commands locally and sends them as a batch, dramatically reducing total execution time. Unlike transactions, pipelined commands are not atomic - they execute independently, but without network round-trip delays between them.

Think of it like mailing multiple letters - instead of walking to the mailbox for each letter individually, you collect all your letters and make one trip to mail them all at once.

## Practical Walkthrough: Code Breakdown

### Creating and Using a Pipeline

```rust
let client = Client::default();
client.init().await?;

let pipeline = client.pipeline();
// Commands are queued in memory
let result: Value = pipeline.incr("foo").await?;
assert!(result.is_queued());
let result: Value = pipeline.incr("foo").await?;
assert!(result.is_queued());
```

Creating a pipeline is straightforward:
- `client.pipeline()` creates a pipeline builder
- Commands called on the pipeline are queued locally, not sent immediately
- Each command returns a `Value` indicating it was queued successfully
- `result.is_queued()` confirms the command is waiting to be sent

### Retrieving All Results

```rust
// Send the pipeline and return all the results in order
let (first, second): (i64, i64) = pipeline.all().await?;
assert_eq!((first, second), (1, 2));
```

The `all()` method:
- Sends all queued commands to Redis at once
- Waits for all responses and returns them as a tuple
- Results are returned in the same order commands were queued
- Type inference works with tuples matching your command sequence

### Getting Only the Last Result

```rust
let pipeline = client.pipeline();
let _: () = pipeline.incr("foo").await?;
let _: () = pipeline.incr("foo").await?;
assert_eq!(pipeline.last::<i64>().await?, 2);
```

The `last()` method:
- Executes all commands but only returns the result of the final command
- Useful when you only care about the final state after a series of operations
- Still more efficient than executing commands individually
- Type annotation is required since we're discarding intermediate results

### Error Handling in Pipelines

```rust
let pipeline = client.pipeline();
let _: () = pipeline.incr("foo").await?;
let _: () = pipeline.hgetall("foo").await?; // This will result in a WRONGTYPE error
let results = pipeline.try_all::<i64>().await;
assert_eq!(results[0].clone().unwrap(), 1);
assert!(results[1].is_err());
```

The `try_all()` method:
- Returns a `Vec<Result<T, Error>>` instead of failing on the first error
- Allows you to handle errors for individual commands within the pipeline
- Commands that succeed still return their results
- Commands that fail return their specific errors

## Mental Model: Thinking in Pipelining

**The Assembly Line Analogy:** Pipelining works like an assembly line for network requests:

```
Without Pipelining:           With Pipelining:
Send CMD1 → Wait → Recv1      Send CMD1, CMD2, CMD3 → Wait → Recv1, Recv2, Recv3
Send CMD2 → Wait → Recv2      
Send CMD3 → Wait → Recv3      

Total Time: 3 × RTT           Total Time: 1 × RTT
```

1. **Batched Network I/O:** Instead of three round-trips, you make one round-trip with three commands. This is especially powerful when network latency is high (like cross-region connections).

2. **Independent Execution:** Unlike transactions, pipelined commands execute independently. If command 2 fails, commands 1 and 3 still execute normally.

3. **Preserved Ordering:** Redis guarantees that responses come back in the same order you sent commands, making result handling predictable.

**Why Pipelining is Designed This Way:**

- **Performance:** Reduces network overhead from O(n) round-trips to O(1) round-trips
- **Simplicity:** No complex atomic semantics - just batched execution
- **Flexibility:** You can mix different types of commands in a single pipeline
- **Error Isolation:** Individual command failures don't affect other commands in the pipeline

**When to Use Pipelining vs Transactions:**

| Use Pipelining When: | Use Transactions When: |
|---------------------|------------------------|
| You want maximum performance | You need atomicity |
| Commands are independent | Commands must all succeed or all fail |
| Some commands may fail but that's okay | Data consistency is critical |
| You're doing bulk operations | You're updating related data |

**Performance Impact:**
- **Local Network:** 2-3x speedup for many small commands
- **High Latency Networks:** 10x+ speedup possible
- **CPU-bound Commands:** Less benefit since network isn't the bottleneck

**Pipeline Patterns:**

1. **Bulk Loading:** Use `all()` when loading lots of data
2. **Final State:** Use `last()` when you only care about the end result
3. **Mixed Operations:** Use `try_all()` when some commands might fail
4. **Fire and Forget:** Pipeline with no result collection for maximum throughput

**Further Exploration:** Benchmark pipeline performance vs individual commands with varying network latencies. Try mixing different command types in a single pipeline. Experiment with error handling by intentionally creating commands that fail.

This example demonstrates how pipelining can dramatically improve performance by optimizing network usage, with Fred providing flexible interfaces for different result handling needs.