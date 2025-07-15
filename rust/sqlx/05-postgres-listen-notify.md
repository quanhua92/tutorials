# Real-time Communication with PostgreSQL LISTEN/NOTIFY

> **Source Code**: [examples/postgres/listen](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/postgres/listen)

## The Core Concept: Why This Example Exists

**The Problem:** Many applications need real-time communication between different parts of the system. Traditional solutions like Redis pub/sub or message queues add infrastructure complexity and potential points of failure. Sometimes you need real-time updates but don't want to introduce additional dependencies.

**The Solution:** PostgreSQL's `LISTEN/NOTIFY` provides a built-in pub/sub system that works within your existing database connection. SQLx makes this feature accessible through async streams, allowing you to build real-time applications with just PostgreSQL and Rust.

## Practical Walkthrough: Code Breakdown

### Setting Up the Listener (`main.rs:20-34`)

```rust
let mut listener = PgListener::connect_with(&pool).await?;

listener.listen_all(vec!["chan0", "chan1", "chan2"]).await?;
```

`PgListener` is SQLx's interface to PostgreSQL's notification system:
- **Dedicated connection**: Listeners need their own connection (can't share with queries)
- **Multiple channels**: A single listener can subscribe to multiple notification channels
- **Async interface**: Integrates naturally with Tokio's async ecosystem

### Concurrent Notification Producer (`main.rs:22-30`)

```rust
let notify_pool = pool.clone();
let _t = tokio::spawn(async move {
    let mut interval = tokio::time::interval(Duration::from_secs(2));

    while !notify_pool.is_closed() {
        interval.tick().await;
        notify(&notify_pool).await;
    }
});
```

This pattern demonstrates real-world usage:
- **Separate task**: Notifications are sent from a different async task
- **Periodic sending**: Simulates regular application events
- **Pool sharing**: The notification sender uses the regular connection pool

### Two Ways to Receive Notifications

#### Method 1: Direct `recv()` (`main.rs:37-45`)

```rust
loop {
    let notification = listener.recv().await?;
    println!("[from recv]: {notification:?}");

    counter += 1;
    if counter >= 3 {
        break;
    }
}
```

Direct reception is simple and works well for straightforward listening loops.

#### Method 2: Stream Interface (`main.rs:50-69`)

```rust
let mut stream = listener.into_stream();

loop {
    tokio::select! {
        res = stream.try_next() => {
            if let Some(notification) = res? {
                println!("[from stream]: {notification:?}");
            } else {
                break;
            }
        },
        _ = timeout.as_mut() => {
            break;
        }
    }
}
```

The stream interface enables:
- **Timeout handling**: Using `tokio::select!` for graceful timeouts
- **Integration with other streams**: Compose with other async operations
- **Backpressure handling**: Standard stream backpressure mechanisms

### Smart Notification Sending (`main.rs:76-108`)

```rust
// language=PostgreSQL
let res = sqlx::query(
    r#"
-- this emits '{ "payload": N }' as the actual payload
select pg_notify(chan, json_build_object('payload', payload)::text)
from (
         values ('chan0', $1),
                ('chan1', $2),
                ('chan2', $3)
     ) notifies(chan, payload)
    "#,
)
.bind(COUNTER.fetch_add(1, Ordering::SeqCst))
.bind(COUNTER.fetch_add(1, Ordering::SeqCst))
.bind(COUNTER.fetch_add(1, Ordering::SeqCst))
.execute(pool)
.await;
```

This demonstrates several advanced patterns:
- **Batch notifications**: Send to multiple channels in one query
- **JSON payloads**: Use PostgreSQL's JSON functions to structure data
- **Parameterized notifications**: Use bind parameters for dynamic content
- **pg_notify() function**: Preferred over `NOTIFY` statement for flexibility

### Message Buffering (`main.rs:47-48`)

```rust
// Prove that we are buffering messages by waiting for 6 seconds
listener.execute("SELECT pg_sleep(6)").await?;
```

This line demonstrates that PostgreSQL buffers notifications while the listener is busy. Messages sent during the sleep are delivered when the listener resumes.

## Mental Model: Thinking in PostgreSQL LISTEN/NOTIFY

### PostgreSQL as a Message Broker

```
Traditional Architecture:
[App1] → [Redis/RabbitMQ] ← [App2]
         [Another service to manage]

PostgreSQL LISTEN/NOTIFY:
[App1] → [PostgreSQL] ← [App2]
         [Already in your stack]
```

LISTEN/NOTIFY turns your database into a lightweight message broker, eliminating the need for separate infrastructure.

### Channel-Based Communication

Think of channels like radio frequencies:

```
Channel "user_updates"    →  [Listener A, Listener B]
Channel "order_events"    →  [Listener C]
Channel "system_alerts"   →  [Listener A, Listener D]
```

Each channel is independent, and listeners can subscribe to multiple channels.

### The Two Notification Methods

**NOTIFY statement** (avoid in application code):
```sql
NOTIFY channel_name, 'payload';  -- Channel name lowercased, no parameters
```

**pg_notify() function** (recommended):
```sql
SELECT pg_notify('Channel_Name', 'payload');  -- Preserves case, accepts parameters
```

The function approach is better because:
- Supports bind parameters
- Preserves channel name case
- Can be used in complex queries

### Delivery Guarantees

PostgreSQL LISTEN/NOTIFY provides:
- **At least once delivery**: Messages will be delivered if the listener is connected
- **No durability**: Messages are lost if no listeners are connected
- **Connection scoped**: Subscriptions end when the connection closes
- **Transaction aware**: Notifications are sent only when transactions commit

### Performance Characteristics

LISTEN/NOTIFY is designed for:
- **Low-latency notifications** (typically milliseconds)
- **Small payloads** (up to 8KB per notification)
- **Moderate volume** (thousands, not millions, of notifications per second)
- **Coordination and alerts** rather than bulk data transfer

### Why PostgreSQL LISTEN/NOTIFY + SQLx Works Well

1. **Zero additional infrastructure**: Works with your existing PostgreSQL setup
2. **ACID integration**: Notifications respect transaction boundaries
3. **Type safety**: SQLx brings compile-time verification to notification payloads
4. **Async integration**: Natural fit with Rust's async/await ecosystem

### Further Exploration

Try these patterns to deepen your understanding:

1. **Trigger-based notifications**: Create database triggers that send notifications on data changes
```sql
CREATE OR REPLACE FUNCTION notify_user_change() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('user_updates', json_build_object('user_id', NEW.id, 'action', TG_OP)::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER user_update_trigger 
    AFTER INSERT OR UPDATE OR DELETE ON users
    FOR EACH ROW EXECUTE FUNCTION notify_user_change();
```

2. **Structured payloads with serde**: Use JSON payloads with typed Rust structs
```rust
#[derive(Serialize, Deserialize)]
struct UserEvent {
    user_id: i64,
    action: String,
    timestamp: DateTime<Utc>,
}
```

3. **Multiple listener coordination**: Build patterns where multiple listeners coordinate work
4. **Graceful shutdown**: Handle application shutdown while ensuring no notifications are lost

This demonstrates how PostgreSQL's LISTEN/NOTIFY can replace complex message queue infrastructure while providing strong consistency guarantees and seamless integration with your existing database operations.