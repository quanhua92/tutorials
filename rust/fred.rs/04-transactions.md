# Transactions: Atomic Operations in Redis

**Source:** [04-transactions.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/04-transactions.rs)

## The Core Concept: Why This Example Exists

**The Problem:** You need to execute multiple Redis commands as an atomic unit - either all commands succeed, or none of them do. This is crucial for maintaining data consistency when multiple operations must happen together, like transferring money between accounts or updating related data structures.

**The Solution:** Redis transactions use the MULTI/EXEC pattern to queue multiple commands and execute them atomically. Fred's transaction interface (`client.multi()`) creates a transaction builder that collects commands locally, then sends them all to Redis when you call `exec()`. During the transaction, commands return "QUEUED" responses, and the actual results are returned all at once when the transaction commits.

Think of it like writing a shopping list - you collect all the items you need (queue commands), then go through the store and collect everything at once (execute the transaction) rather than making separate trips for each item.

## Practical Walkthrough: Code Breakdown

### Creating a Transaction

```rust
let client = Client::default();
client.init().await?;

let trx = client.multi();
```

Starting a transaction is simple:
- `client.multi()` creates a transaction builder
- This sends the `MULTI` command to Redis, putting the connection in transaction mode
- The transaction builder (`trx`) collects commands until you call `exec()`

### Queuing Commands

```rust
let result: Value = trx.get("foo").await?;
assert!(result.is_queued());
let result: Value = trx.set("foo", "bar", None, None, false).await?;
assert!(result.is_queued());
let result: Value = trx.get("foo").await?;
assert!(result.is_queued());
```

During the transaction, commands are queued rather than executed immediately:
- Each command returns a `Value` that represents "QUEUED" status
- `result.is_queued()` confirms the command was queued successfully
- Commands are stored locally and sent to Redis as a batch
- No actual data operations happen until `exec()` is called

### Executing the Transaction

```rust
let values: (Option<String>, (), String) = trx.exec(true).await?;
println!("Transaction results: {:?}", values);
```

The `exec()` call commits the transaction:
- `exec(true)` executes all queued commands atomically
- The boolean parameter controls whether to return command results
- Results are returned as a tuple matching the types of your queued commands
- If any command fails, the entire transaction fails

## Mental Model: Thinking in Redis Transactions

**The Database Transaction Analogy:** Redis transactions work like database transactions, but with important differences:

```
Regular Commands:          Transaction Commands:
  GET foo                    MULTI
     ↓                       GET foo      ← Queued
  "value"                    SET foo bar  ← Queued  
                             GET foo      ← Queued
  SET foo bar                EXEC
     ↓                          ↓
   "OK"                    [nil, "OK", "bar"]
```

1. **Atomic Execution:** All commands in a transaction execute as a single, indivisible operation. Other clients cannot see intermediate states.

2. **Local Queuing:** Commands are buffered in memory (both in Fred and Redis) until `exec()` is called. This means you can't use the results of one command within the same transaction.

3. **All-or-Nothing:** If any command in the transaction fails syntactically, the entire transaction is discarded. However, runtime errors (like type mismatches) don't abort the transaction - those commands just return errors in the results.

**Why Transactions are Designed This Way:**

1. **Performance:** Batching commands reduces network roundtrips from N commands to 2 commands (MULTI + EXEC)

2. **Atomicity:** Other clients cannot observe your data in an inconsistent intermediate state

3. **Simplicity:** No complex locking mechanisms - transactions either succeed completely or fail completely

**Important Limitations to Understand:**

- **No Conditionals:** You cannot use the result of one command to determine subsequent commands within the same transaction
- **No Rollback:** Unlike SQL databases, Redis doesn't roll back commands that execute successfully but produce unexpected results
- **Connection Bound:** Transactions are tied to a specific connection - you cannot use pooled clients for transactions

**Transaction Use Cases:**
- **Related Updates:** Updating multiple keys that must stay consistent
- **Counters and Metrics:** Incrementing multiple counters atomically  
- **Data Migration:** Moving data between different Redis structures
- **Batch Operations:** Performing many similar operations efficiently

**What Happens During EXEC:**
1. Redis validates that all queued commands are syntactically correct
2. If validation passes, all commands execute sequentially without interruption
3. Results are collected and returned as an array
4. If validation fails, the entire transaction is discarded

**Further Exploration:** Try creating a transaction that transfers a value between two keys (like moving money between accounts). Experiment with what happens when you queue an invalid command. Try using transactions with different data types to see how type safety works with the tuple return type.

This example demonstrates Redis transactions' power for atomic operations, with Fred providing type-safe interfaces that make working with transaction results natural in Rust.