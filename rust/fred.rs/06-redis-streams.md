# Redis Streams: Event-Driven Communication

**Source:** [06-redis-streams.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/06-redis-streams.rs)

## The Core Concept: Why This Example Exists

**The Problem:** You need persistent, ordered messaging between components of your application. Traditional pub/sub is great for real-time notifications, but messages are lost if no one is listening. You need a message log that consumers can read from at their own pace, replay missed messages, and process data in order.

**The Solution:** Redis Streams provide a append-only log data structure where producers add entries with structured data, and consumers read entries sequentially. Think of it like a combination of Apache Kafka and a database table - messages are persisted with unique IDs, consumers can read from any point in the stream, and multiple consumers can process the same data independently.

This example demonstrates using Streams for task communication between async tasks - one task writes data to the stream while another reads it, showcasing real-time producer-consumer patterns.

## Practical Walkthrough: Code Breakdown

### Setting Up Stream Infrastructure

```rust
// Reader task setup
let _: () = client.del("foo").await?;
let _: () = client.xgroup_create("foo", "group", "$", true).await?;
```

Stream initialization requires:
- `del("foo")` ensures we start with a clean stream
- `xgroup_create()` creates a consumer group starting from the end of the stream (`$`)
- Consumer groups allow multiple consumers to share work and track read progress

### Producer: Adding Stream Entries

```rust
for values in VALUES.chunks(2) {
  let id: Str = client
    .xadd("foo", false, None, "*", vec![
      ("field1", values[0]),
      ("field2", values[1]),
    ])
    .await?;
  
  println!("Writer added stream entry with ID: {}", id);
  sleep(Duration::from_secs(1)).await;
}
```

`XADD` adds structured entries to the stream:
- `"foo"` is the stream name
- `false` means don't limit the stream size (no trimming)
- `None` means no maximum length limit
- `"*"` tells Redis to auto-generate an ID (timestamp-sequence format)
- The vector contains field-value pairs that make up the entry's data

### Consumer: Reading Stream Entries

```rust
loop {
  // Call XREAD for new records, blocking up to 10 seconds
  let entry: XReadResponse<Str, Str, Str, Str> = client.xread_map(Some(1), Some(10_000), "foo", "$").await?;
  
  for (key, records) in entry.into_iter() {
    for (id, fields) in records.into_iter() {
      println!("Reader recv {} - {}: {:?}", key, id, fields);
    }
  }
  
  if count * 2 >= VALUES.len() {
    break;
  }
}
```

`XREAD` reads new entries from the stream:
- `Some(1)` limits to 1 stream (can read from multiple streams)
- `Some(10_000)` blocks for up to 10 seconds waiting for new entries
- `"foo"` is the stream name to read from
- `"$"` means "read only new entries since now"
- Returns structured data with stream names, entry IDs, and field-value maps

### Task Coordination

```rust
let reader_task = tokio::spawn(async move { /* reader logic */ });
let writer_task = tokio::spawn(async move { 
  // Give the reader a chance to call XREAD first
  sleep(Duration::from_secs(1)).await;
  /* writer logic */
});

try_join_all([writer_task, reader_task]).await.unwrap();
```

This demonstrates async task coordination:
- Reader starts first and begins blocking on `XREAD`
- Writer waits 1 second to ensure reader is ready
- Both tasks run concurrently using separate Redis clients
- `try_join_all` waits for both tasks to complete

## Mental Model: Thinking in Redis Streams

**The Event Log Analogy:** Redis Streams work like a distributed event log or journal:

```
Time →
┌─────────────────────────────────────────────────────────────┐
│ Stream "foo"                                                │
├─────────────────────────────────────────────────────────────┤
│ 1704862102584-0: {field1: "a", field2: "b"}                │
│ 1704862103589-0: {field1: "c", field2: "d"}                │
│ 1704862104594-0: {field1: "e", field2: "f"}                │
│ 1704862105598-0: {field1: "g", field2: "h"}                │
└─────────────────────────────────────────────────────────────┘
         ↑                                    ↑
    Entry ID                            Structured Data
  (timestamp-seq)                       (field-value pairs)
```

1. **Append-Only Log:** Entries are added to the end and never modified. Each entry gets a unique, monotonically increasing ID.

2. **Structured Messages:** Unlike simple pub/sub messages, stream entries contain multiple fields, making them suitable for complex data.

3. **Multiple Read Patterns:** 
   - **Live Reading:** `XREAD` with `$` gets new entries as they arrive
   - **Historical Reading:** `XREAD` with a specific ID catches up from any point
   - **Consumer Groups:** Multiple consumers share work and track progress

**Why Streams are Designed This Way:**

- **Persistence:** Messages survive restarts and network interruptions
- **Replay:** Consumers can re-read messages or catch up after downtime  
- **Ordering:** Guaranteed message ordering within a single stream
- **Scalability:** Multiple consumers can process messages in parallel
- **Flexibility:** Rich data structure supports complex use cases

**Streams vs Other Redis Messaging:**

| Feature | PubSub | Lists | Streams |
|---------|--------|-------|---------|
| Persistence | No | Yes | Yes |
| Multiple Consumers | Yes | No (blocking) | Yes (groups) |
| Message Structure | Simple | Simple | Rich (fields) |
| Replay/History | No | Limited | Full |
| Ordering | No guarantee | FIFO | Time-ordered |

**Common Stream Patterns:**

1. **Event Sourcing:** Store all application events for audit trails
2. **Task Queues:** Distribute work among multiple workers
3. **Real-time Analytics:** Process events as they happen
4. **Inter-service Communication:** Reliable messaging between microservices

**Entry ID Format:** IDs like `1704862102584-0` contain:
- **Timestamp (ms):** When the entry was added (1704862102584)
- **Sequence Number:** Ensures ordering within the same millisecond (0)

**Further Exploration:** Try using consumer groups with `XREADGROUP` to have multiple consumers share work. Experiment with different starting positions (`0`, specific IDs, `$`). Try adding entries with more complex field structures and see how type conversion works.

This example demonstrates Redis Streams' power for building event-driven architectures with guaranteed delivery, replay capability, and structured data - perfect for microservices communication and data pipeline construction.