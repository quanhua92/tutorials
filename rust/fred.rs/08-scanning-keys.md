# Scanning Keys: Efficiently Iterating Large Keyspaces

**Source:** [08-scanning-keys.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/08-scanning-keys.rs)

## The Core Concept: Why This Example Exists

**The Problem:** You need to find and process keys in Redis, but you don't know exactly which keys exist. Using `KEYS *` is dangerous in production because it blocks Redis while scanning the entire keyspace. You need a way to iterate through potentially millions of keys without blocking Redis or consuming excessive memory.

**The Solution:** Redis `SCAN` provides cursor-based iteration that breaks the keyspace into pages, allowing you to process keys incrementally without blocking the server. Fred provides multiple scan interfaces: throttled scanning (one page at a time), buffered scanning (concurrent processing), and manual cursor management for custom control.

Think of it like paginating through search results on a website - instead of loading millions of results at once, you process them in manageable chunks.

## Practical Walkthrough: Code Breakdown

### Throttled Scanning: Memory-Conscious Iteration

```rust
async fn scan_throttled(client: &Client) -> Result<(), Error> {
  // Scan all keys matching pattern, returning 10 keys per page
  let mut scan_stream = client.scan("foo*", Some(10), None);
  while let Some(mut page) = scan_stream.try_next().await? {
    if let Some(keys) = page.take_results() {
      for key in keys.into_iter() {
        let value: Value = client.get(&key).await?;
        println!("Scanned {} -> {:?}", key.as_str_lossy(), value);
      }
    }
    
    page.next(); // Control when the next page is fetched
  }
  Ok(())
}
```

Throttled scanning offers precise control:
- `scan("foo*", Some(10), None)` creates a stream that returns 10 keys per page
- `page.take_results()` extracts the keys from the current page
- `page.next()` explicitly requests the next page (otherwise fetched when dropped)
- Memory usage is bounded - only one page of keys in memory at a time

### Buffered Scanning: Maximum Throughput

```rust
async fn scan_buffered(client: &Client) -> Result<(), Error> {
  client
    .scan_buffered("foo*", Some(10), None)
    .try_for_each_concurrent(10, |key| async move {
      let value: Value = client.get(&key).await?;
      println!("Scanned {} -> {:?}", key.as_str_lossy(), value);
      Ok(())
    })
    .await
}
```

Buffered scanning optimizes for throughput:
- `scan_buffered()` returns a stream of individual keys, not pages
- `try_for_each_concurrent(10, ...)` processes up to 10 keys concurrently
- Fred manages the pagination internally, buffering keys for smooth processing
- Higher memory usage but maximum parallelism

### Manual Cursor Management: Full Control

```rust
async fn scan_with_cursor(client: &Client) -> Result<(), Error> {
  let mut cursor: Str = "0".into();
  let mut count = 0;

  loop {
    let (new_cursor, keys): (Str, Vec<Key>) = client.scan_page(cursor, "*", Some(100), None).await?;
    count += keys.len();

    for key in keys.into_iter() {
      let val: Value = client.get(&key).await?;
      println!("Scanned {} -> {:?}", key.as_str_lossy(), val);
    }

    if count >= max_keys || new_cursor == "0" {
      break;
    } else {
      cursor = new_cursor;
    }
  }
  Ok(())
}
```

Manual cursor management provides maximum flexibility:
- `scan_page()` returns both the keys and the next cursor
- Starting cursor is `"0"`, ending cursor is also `"0"` (full circle)
- You control batching, memory usage, and termination conditions
- Useful for custom pagination logic or persistence requirements

### Cluster Scanning: Distributed Keyspaces

```rust
async fn pool_scan_cluster_memory_example(pool: &Pool) -> Result<(), Error> {
  let mut total_size = 0;
  let mut scanner = pool.next().scan_cluster("*", Some(100), None);

  while let Some(mut page) = scanner.try_next().await? {
    if let Some(page) = page.take_results() {
      // Pipeline MEMORY USAGE calls for efficiency
      let pipeline = pool.next().pipeline();
      for key in page.iter() {
        pipeline.memory_usage::<(), _>(key, Some(0)).await?;
      }
      let sizes: Vec<Option<u64>> = pipeline.all().await?;

      for (idx, key) in page.into_iter().enumerate() {
        let size = sizes[idx].unwrap_or(0);
        total_size += size;
      }
    }
    page.next();
  }
  Ok(())
}
```

Cluster scanning handles distributed keyspaces:
- `scan_cluster()` automatically scans all cluster nodes
- Combines results from multiple nodes into a single stream
- Pipelines follow-up operations for efficiency
- Essential for Redis Cluster deployments

## Mental Model: Thinking in Redis Scanning

**The Library Card Catalog Analogy:** Redis SCAN works like searching through a library card catalog:

```
Traditional KEYS:              SCAN with Cursor:
                              
Request all cards at once      Request a drawer of cards
      ↓                              ↓
┌─────────────────────────┐    ┌─────────────────┐
│ All 1M cards delivered │    │ 100 cards + cursor │  
│ (blocks library)        │    │ (library open)  │
└─────────────────────────┘    └─────────────────┘
Memory: 1M cards                Memory: 100 cards
Time: Blocks everything         Time: Interactive
                               
                               Cursor → Next drawer →
                               ┌─────────────────┐
                               │ Next 100 cards │
                               └─────────────────┘
```

1. **Cursor-Based Iteration:** The cursor tracks your position in the keyspace, like a bookmark in a book.

2. **Server-Friendly:** Each SCAN call is quick and doesn't block Redis, allowing other operations to proceed.

3. **Memory Bounded:** You control how many keys to process at once, preventing memory exhaustion.

**Why SCAN is Designed This Way:**

- **Non-blocking:** Redis remains responsive during large keyspace iterations
- **Memory Efficient:** Process keyspaces larger than available memory
- **Resumable:** Can pause and resume scanning using the cursor
- **Pattern Matching:** Built-in pattern filtering reduces network traffic

**SCAN Guarantees and Limitations:**

✅ **Guarantees:**
- All keys present during full scan will be returned
- No false positives (pattern matching is accurate)
- Server remains responsive

❌ **Limitations:**
- Keys added/removed during scan might be missed or seen multiple times
- No guaranteed order of results
- Pattern matching happens server-side (can't use complex regex)

**Choosing the Right Scan Method:**

| Method | Memory Usage | Throughput | Control | Use Case |
|--------|-------------|------------|---------|----------|
| Throttled | Low | Medium | High | Memory-constrained environments |
| Buffered | Medium | High | Medium | Processing all matching keys quickly |
| Manual Cursor | Variable | Variable | Maximum | Custom pagination, persistence |
| Cluster | Low | High | Medium | Redis Cluster deployments |

**Performance Optimization Patterns:**

1. **Pipeline Follow-up Operations:** Group operations on scanned keys using pipelines
2. **Concurrent Processing:** Use `try_for_each_concurrent` for I/O-bound operations on keys  
3. **Pattern Specificity:** Use specific patterns to reduce server-side filtering
4. **Page Size Tuning:** Larger pages reduce round-trips but increase memory usage

**Common SCAN Use Cases:**
- **Cleanup Jobs:** Finding and deleting expired keys with specific patterns
- **Data Migration:** Moving keys between Redis instances
- **Monitoring:** Analyzing key distribution and memory usage
- **Backup:** Iterating through all keys for backup purposes

**Further Exploration:** Benchmark different page sizes and see how they affect throughput vs memory usage. Try scanning during high load to observe how it doesn't block other operations. Experiment with complex patterns and see how server-side filtering affects performance.

This example demonstrates Redis SCAN's power for safe, efficient keyspace iteration, with Fred providing multiple interfaces optimized for different use cases and deployment scenarios.