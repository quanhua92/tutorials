# Publish-Subscribe: Real-Time Messaging with Redis

**Source:** [03-publish-subscribe.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/03-publish-subscribe.rs)

## The Core Concept: Why This Example Exists

**The Problem:** You need real-time messaging between different parts of your application or between different applications entirely. Traditional request-response patterns don't work when you need to broadcast data to multiple consumers or when you don't know who needs the data in advance.

**The Solution:** Redis PubSub enables asynchronous messaging where publishers send messages to channels without knowing who (if anyone) is listening. Subscribers listen to channels and receive messages as they arrive. Fred provides two approaches: using regular clients with message handlers, or specialized `SubscriberClient` instances that automatically manage subscription state across reconnections.

Think of it like a radio broadcast - the radio station (publisher) transmits on a frequency (channel) and anyone with a radio tuned to that frequency (subscriber) receives the broadcast, even if the broadcaster doesn't know who's listening.

## Practical Walkthrough: Code Breakdown

### Basic PubSub with Regular Clients

```rust
let publisher_client = Builder::default_centralized()
  .with_performance_config(|config| {
    config.broadcast_channel_capacity = 64;
  })
  .build()?;
let subscriber_client = publisher_client.clone_new();
```

This creates two clients from the same configuration:
- `publisher_client` will send messages to Redis channels
- `subscriber_client` will receive messages from Redis channels
- `clone_new()` creates a new client with identical configuration but separate connections
- The broadcast channel capacity controls the buffer size for message handling

### Message Handling

```rust
let _message_task = subscriber_client.on_message(|message| async move {
  println!("{}: {}", message.channel, message.value.convert::<i64>()?);
  Ok::<_, Error>(())
});
```

The `on_message()` handler:
- Spawns a background task that processes incoming messages
- Each message contains the channel name and the value
- `message.value.convert::<i64>()` demonstrates type-safe message conversion
- The handler is an async function, allowing for complex processing

### Publishing Messages

```rust
for idx in 0 .. 50 {
  let _: () = publisher_client.publish("foo", idx).await?;
  sleep(Duration::from_secs(1)).await;
}
```

Publishing is straightforward:
- `publish()` sends a message to a named channel
- Any subscribers to channel "foo" will receive the message
- The publisher doesn't know or care if anyone is listening
- Messages are sent immediately and not persisted by Redis

### Advanced: SubscriberClient

```rust
let subscriber = Builder::default_centralized()
  .with_performance_config(|config| {
    config.broadcast_channel_capacity = 64;
  })
  .build_subscriber_client()?;

let _resubscribe_task = subscriber.manage_subscriptions();
```

`SubscriberClient` provides enhanced subscription management:
- `build_subscriber_client()` creates a client specialized for subscriptions
- `manage_subscriptions()` automatically re-subscribes to channels after reconnections
- This solves the problem of losing subscriptions when network connections are interrupted

### Subscription Management

```rust
subscriber.subscribe("foo").await?;
subscriber.psubscribe(vec!["bar*", "baz*"]).await?;
subscriber.ssubscribe("abc{123}").await?;

println!("Subscriber channels: {:?}", subscriber.tracked_channels());
println!("Subscriber patterns: {:?}", subscriber.tracked_patterns());
println!("Subscriber shard channels: {:?}", subscriber.tracked_shard_channels());
```

Three types of subscriptions are supported:
- **Regular channels:** `subscribe("foo")` - exact channel name matching
- **Pattern subscriptions:** `psubscribe(["bar*"])` - wildcard pattern matching  
- **Shard channels:** `ssubscribe("abc{123}")` - Redis Cluster sharded channels

The client tracks all active subscriptions and can restore them automatically.

### Stream-Based Message Processing

```rust
let mut message_stream = subscriber.message_rx();
let _subscriber_task = tokio::spawn(async move {
  while let Ok(message) = message_stream.recv().await {
    println!("Recv {:?} on channel {}", message.value, message.channel);
  }
  Ok::<_, Error>(())
});
```

Alternative to callback-based handling:
- `message_rx()` returns a broadcast receiver stream
- Manual task spawning gives you more control over message processing
- This approach is useful when you need custom error handling or backpressure

## Mental Model: Thinking in PubSub

**The Radio Broadcasting Analogy:** Redis PubSub works exactly like radio broadcasting:

```
Publishers (Radio Stations)          Redis Server (Broadcasting Tower)
        ↓                                      ↓
   publish("weather", "sunny")          Channel: "weather"
   publish("news", "headlines")         Channel: "news"
        ↓                                      ↓
                            Subscribers (Radio Listeners)
                               ↙        ↓        ↘
                         Listener1  Listener2  Listener3
                        (weather)   (news)    (weather + news)
```

1. **Decoupled Communication:** Publishers and subscribers don't know about each other. A publisher sends to a channel; any number of subscribers (including zero) might receive it.

2. **Real-Time Delivery:** Messages are delivered immediately when published. There's no queuing or persistence - if no one is listening when you broadcast, the message is lost.

3. **Pattern Matching:** Pattern subscriptions (`bar*`) let you subscribe to multiple related channels at once, like scanning radio frequencies.

**Why PubSub is Designed This Way:**
- **Scalability:** One publisher can reach unlimited subscribers without performance degradation
- **Loose Coupling:** Publishers and subscribers can be developed, deployed, and scaled independently
- **Real-Time:** No polling required - messages arrive immediately when published
- **Simple:** No complex message queuing semantics - just publish and receive

**Key Considerations:**
- **No Persistence:** Messages are lost if no subscribers are active
- **No Ordering Guarantees:** In cluster setups, message order isn't guaranteed across shards
- **Connection Sensitivity:** Subscriptions are lost when connections drop (hence SubscriberClient's auto-resubscribe feature)

**When to Use Each Approach:**
- **Regular Client + on_message():** Simple pub/sub scenarios where connection stability is good
- **SubscriberClient:** Production scenarios where you need guaranteed re-subscription after network issues
- **Direct message_rx():** When you need custom message processing logic or error handling

**Further Exploration:** Set up multiple subscriber processes and observe how messages are delivered to all of them. Try pattern subscriptions with different wildcards. Experiment with connection interruptions and see how SubscriberClient handles re-subscription.

This example demonstrates Redis PubSub's power for real-time, decoupled communication, with Fred providing both simple interfaces and production-ready reliability features.