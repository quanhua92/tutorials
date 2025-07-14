# Basic Redis Client: Your First Connection to Redis

**Source:** [01-basic-redis-client.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/01-basic-redis-client.rs)

## The Core Concept: Why This Example Exists

**The Problem:** You have a Rust application and need to connect to a Redis database to store and retrieve data. You need a reliable, async connection that can handle errors gracefully and convert Redis responses to native Rust types.

**The Solution:** Fred provides a builder pattern for creating Redis clients with comprehensive configuration options. Think of it like setting up a telephone line to Redis - you configure the connection parameters, establish the line, and then you can have conversations (send commands) through it. Fred handles the complexity of the Redis protocol, connection management, and type conversions, letting you focus on your application logic.

## Practical Walkthrough: Code Breakdown

Let's examine how the basic example demonstrates Fred's fundamental concepts:

### Configuration and Client Creation

```rust
let config = Config::from_url("redis://username:password@foo.com:6379/1")?;
let client = Builder::from_config(config)
  .with_connection_config(|config| {
    config.connection_timeout = Duration::from_secs(5);
    config.tcp = TcpConfig {
      nodelay: Some(true),
      ..Default::default()
    };
  })
  .build()?;
```

This code creates a Redis client using Fred's builder pattern:
- `Config::from_url()` parses a Redis connection URL and extracts connection parameters
- `Builder::from_config()` starts the builder pattern for client configuration  
- `with_connection_config()` allows fine-tuning of TCP-level settings like timeouts and socket options
- The builder pattern lets you configure multiple aspects before calling `.build()`

### Connection Initialization

```rust
client.init().await?;
```

The `init()` method establishes the actual connection to Redis. This is separate from client creation because:
- It allows you to configure event handlers before connecting
- It returns a task handle that you can manage if needed
- It's an async operation that might fail, so it's explicit

### Event Handling

```rust
client.on_error(|(error, server)| async move {
  println!("{:?}: Connection error: {:?}", server, error);
  Ok(())
});

client.on_reconnect(|server| async move {
  println!("Reconnected to {}", server);
  Ok(())
});
```

Fred provides event handlers for connection lifecycle events:
- `on_error()` handles connection errors and allows custom recovery logic
- `on_reconnect()` triggers when Fred successfully reconnects after a disconnection
- These handlers are async functions that run in response to connection events

### Type-Safe Redis Operations

```rust
// Automatic type inference
let foo: Option<String> = client.get("foo").await?;

// Setting with options
let _: () = client
  .set("foo", "bar", Some(Expiration::EX(1)), Some(SetOptions::NX), false)
  .await?;

// Explicit type specification
println!("Foo: {:?}", client.get::<Option<String>, _>("foo").await?);
```

Fred converts Redis responses to Rust types automatically:
- Type inference works when the return type is clear from context
- Complex operations like `SET` with expiration and options are strongly typed
- Turbofish syntax (`<Option<String>, _>`) can specify response types explicitly

## Mental Model: Thinking in Fred

**The Telephone Exchange Analogy:** Think of Fred as operating a telephone exchange between your Rust application and Redis. 

```
Your App  →  Fred Client  →  Network  →  Redis Server
   ↑             ↑            ↑           ↑
   |         Connection     TCP Socket    Database
   |         Manager       with Protocol  Storage
   |                       Handling
Type-safe
Commands
```

1. **The Client as a Smart Translator:** Fred translates between Rust types and Redis protocol. When you call `client.get::<String, _>("key")`, Fred knows to send `GET key` and parse the response as a string.

2. **Connection as a Managed Resource:** Unlike a raw TCP connection, Fred's client manages reconnection, error recovery, and protocol state automatically. You don't worry about RESP frame parsing or connection drops.

3. **Async by Design:** Every Redis operation returns a Future, matching Redis's network-bound nature. This lets your application handle thousands of concurrent Redis operations efficiently.

**Why It's Designed This Way:** Fred separates configuration, connection, and operation phases because Redis applications often need:
- Different connection settings per environment (timeouts, TLS, auth)
- Event handlers for monitoring and debugging
- Graceful handling of network interruptions
- Type safety without sacrificing performance

**Further Exploration:** Try modifying the connection timeout to 1 second and observe how it affects connection establishment. Or experiment with different Redis data types like hashes or lists using Fred's typed interfaces.

This example demonstrates Fred's core philosophy: provide a type-safe, async interface that handles Redis complexity while feeling natural to Rust developers.