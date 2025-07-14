# Advanced Fred Features: Production-Ready Patterns

**Source:** [09-advanced-features.rs](https://github.com/aembke/fred.rs/tree/f222ad7bfba844dbdc57e93da61b0a5483858df9/examples/09-advanced-features.rs)

## The Core Concept: Why These Examples Exist

**The Problem:** Production Redis deployments require more than basic key-value operations. You need TLS security, high availability through sentinels, monitoring and debugging tools, custom connection management, and integration with web frameworks. Real applications also need efficient handling of blocking operations, JSON data, cluster replicas, and custom scaling policies.

**The Solution:** Fred provides a comprehensive suite of advanced features that address production requirements. This tutorial covers the essential patterns you'll need for deploying Fred in real-world scenarios, from security and monitoring to framework integration and performance optimization.

## Security and Connection Management

### TLS Configuration

```rust
// Feature-gated TLS support
#[cfg(feature = "enable-native-tls")]
let config = Config {
  server: ServerConfig::new_centralized("rediss://127.0.0.1:6380"),
  tls: Some(TlsConfig::default()),
  ..Default::default()
};

#[cfg(feature = "enable-rustls")]
let config = Config {
  server: ServerConfig::new_centralized("rediss://127.0.0.1:6380"),
  tls: Some(TlsConfig::default_rustls()),
  ..Default::default()
};
```

**Key Points:**
- Use `rediss://` URL scheme for TLS connections
- Fred supports both `native-tls` and `rustls` backends
- TLS configuration is feature-gated for smaller binary sizes
- Custom certificate validation is supported for both backends

### Sentinel High Availability

```rust
let config = Config {
  server: ServerConfig::new_sentinel(vec![
    ("sentinel-1.example.com", 26379),
    ("sentinel-2.example.com", 26379),
    ("sentinel-3.example.com", 26379),
  ], "mymaster"),
  ..Default::default()
};
```

**Key Points:**
- Sentinels provide automatic failover for Redis masters
- Configure multiple sentinel nodes for redundancy
- Service name ("mymaster") identifies the Redis service
- Fred automatically discovers the current master through sentinels

## Monitoring and Debugging

### Redis MONITOR Command

```rust
let mut monitor_stream = monitor::run(&client).await?;
while let Some(command) = monitor_stream.next().await {
  match command {
    Ok(cmd) => println!("Monitored: {:?}", cmd),
    Err(e) => println!("Monitor error: {:?}", e),
  }
}
```

**Key Points:**
- `MONITOR` shows all commands processed by Redis in real-time
- Useful for debugging and understanding application Redis usage
- Be cautious in production - monitoring can impact performance
- Stream-based interface allows selective processing

### Connection Events

```rust
// Simple event handlers
client.on_error(|(error, server)| async move {
  println!("Error on {}: {}", server, error);
  Ok(())
});

client.on_reconnect(|server| async move {
  println!("Reconnected to {}", server);
  Ok(())
});

// Stream-based event handling
let mut error_stream = client.error_rx();
let mut reconnect_stream = client.reconnect_rx();

tokio::spawn(async move {
  futures::stream::select_all([error_stream, reconnect_stream])
    .for_each(|event| async move {
      println!("Connection event: {:?}", event);
    })
    .await;
});
```

**Key Points:**
- Two interfaces: callback-based (`on_*`) and stream-based (`*_rx`)
- Stream interface allows combining multiple event types
- Essential for building robust applications that handle network issues
- Events work with both individual clients and pools

## Advanced Data Handling

### Blocking Operations

```rust
let consumer_task = tokio::spawn(async move {
  loop {
    // Block for up to 5 seconds waiting for items
    match consumer.blpop::<Option<(String, String)>, _>("work_queue", 5.0).await? {
      Some((key, value)) => {
        println!("Processing work item: {} -> {}", key, value);
        // Process the work item
      }
      None => {
        println!("No work items available, continuing...");
      }
    }
  }
});

// Producer adds work items
for i in 0..10 {
  producer.rpush("work_queue", format!("task_{}", i)).await?;
}
```

**Key Points:**
- `BLPOP`/`BRPOP` provide efficient producer-consumer patterns
- Blocking operations don't consume CPU while waiting
- Timeout prevents indefinite blocking
- Essential for job queue implementations

### JSON Data Handling

```rust
// serde_json integration
#[derive(Serialize, Deserialize)]
struct User {
  id: u64,
  name: String,
  email: String,
}

let user = User { id: 1, name: "Alice".into(), email: "alice@example.com".into() };
client.set("user:1", &user, None, None, false).await?;
let retrieved: User = client.get("user:1").await?;

// RedisJSON module operations
client.json_set("user:2", "$", &user).await?;
let name: String = client.json_get("user:2", "$.name").await?;
client.json_arrappend("user:2", "$.tags", ["redis", "json"]).await?;
```

**Key Points:**
- `serde-json` feature enables automatic JSON serialization
- RedisJSON module provides native JSON operations in Redis
- JSON path syntax allows efficient partial updates
- Significantly more efficient than string-based JSON handling

## Performance and Scaling

### Dynamic Connection Pools

```rust
struct CustomScalePolicy;

impl PoolScale for CustomScalePolicy {
  fn should_scale_up(&self, client: &Client, metrics: &PoolMetrics) -> Option<usize> {
    if metrics.recent_latency_ms > 100.0 {
      Some(1) // Add one connection if latency is high
    } else {
      None
    }
  }

  fn should_scale_down(&self, client: &Client, metrics: &PoolMetrics) -> Option<usize> {
    if metrics.recent_requests_per_sec < 10.0 && metrics.pool_size > 2 {
      Some(1) // Remove one connection if load is low
    } else {
      None
    }
  }
}

let pool = DynamicPool::new(client, 2, 10, CustomScalePolicy)?;
```

**Key Points:**
- Dynamic pools automatically scale based on load and latency
- Custom scaling policies allow application-specific optimization
- Metrics-driven scaling decisions prevent over/under-provisioning
- Essential for variable workload scenarios

### Replica Read Scaling

```rust
let pool = Builder::default_clustered(vec![
  ("cluster-node-1.example.com", 6379),
  ("cluster-node-2.example.com", 6379),
  ("cluster-node-3.example.com", 6379),
])
.with_config(|config| {
  config.replica = Some(ReplicaConfig {
    lazy_connections: true,
    primary_fallback: true,
    connection_error_count: 3,
    ..Default::default()
  });
})
.build_pool(5)?;

// This read might go to a replica
let value: String = pool.get("readonly_key").await?;
```

**Key Points:**
- Replicas provide read scaling for cluster deployments
- Lazy connections reduce resource usage
- Primary fallback ensures availability during replica failures
- Automatic replica discovery and routing

## Framework Integration

### Web Framework Patterns

```rust
// Axum integration example
#[derive(Clone)]
struct AppState {
  redis: Pool,
}

async fn get_user(
  State(state): State<AppState>,
  Path(id): Path<String>,
) -> Result<Json<User>, StatusCode> {
  match state.redis.hgetall::<User, _>(format!("user:{}", id)).await {
    Ok(user) => Ok(Json(user)),
    Err(_) => Err(StatusCode::NOT_FOUND),
  }
}

async fn increment_counter(
  State(state): State<AppState>,
  Path(key): Path<String>,
) -> Result<Json<i64>, StatusCode> {
  match state.redis.incr::<i64, _>(&key).await {
    Ok(value) => Ok(Json(value)),
    Err(_) => Err(StatusCode::INTERNAL_SERVER_ERROR),
  }
}

let app = Router::new()
  .route("/user/:id", get(get_user))
  .route("/counter/:key", post(increment_counter))
  .with_state(AppState { redis: pool });
```

**Key Points:**
- Connection pools are shared across request handlers
- Error mapping converts Redis errors to HTTP status codes
- State pattern provides clean dependency injection
- Works identically with Actix Web and other frameworks

## Custom Commands and Protocol Handling

### Low-Level Protocol Access

```rust
// Custom command construction
let cmd = cmd!("CUSTOM", "arg1", "arg2");
let result: Value = client.custom(cmd, vec!["key1", "key2"]).await?;

// Raw RESP3 frame handling
let frame = resp3_utils::encode_bytes_array(vec!["GET", "foo"]);
let response: Frame = client.custom_raw(frame, true, false).await?;
```

**Key Points:**
- `cmd!` macro builds custom Redis commands
- Raw frame access for protocol-level control
- Cluster routing can be customized for non-standard commands
- Essential for Redis modules or experimental commands

## Production Configuration Patterns

### Performance Tuning

```rust
let client = Builder::default_centralized()
  .with_performance_config(|config| {
    config.broadcast_channel_capacity = 512;
    config.default_command_timeout = Duration::from_secs(10);
    config.max_command_attempts = 3;
    config.connection_timeout = Duration::from_secs(5);
  })
  .with_connection_config(|config| {
    config.tcp = TcpConfig {
      nodelay: Some(true),
      ..Default::default()
    };
  })
  .build()?;
```

**Key Points:**
- Tuning timeouts prevents hanging operations
- TCP_NODELAY reduces latency for small operations
- Retry attempts handle transient network issues
- Broadcast channel capacity affects pubsub performance

## Mental Model: Production Redis Architecture

Think of advanced Fred features as building blocks for a production-ready Redis architecture:

```
Application Layer
    ↓
┌─────────────────────────────────────────┐
│ Web Framework (Axum/Actix)              │
│ ├─ Connection Pool Management           │
│ ├─ Error Handling & HTTP Mapping       │
│ └─ Request/Response Serialization       │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Fred Client Layer                       │
│ ├─ Dynamic Scaling                      │
│ ├─ Event Monitoring                     │
│ ├─ Custom Commands                      │
│ └─ Performance Tuning                   │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Network & Security Layer                │
│ ├─ TLS Encryption                       │
│ ├─ Sentinel Discovery                   │
│ ├─ Custom DNS Resolution                │
│ └─ Connection Management                │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│ Redis Infrastructure                    │
│ ├─ Cluster Nodes                       │
│ ├─ Read Replicas                       │
│ ├─ Sentinel Monitors                   │
│ └─ TLS Termination                     │
└─────────────────────────────────────────┘
```

**Further Exploration:** Set up a complete production-like environment with TLS, sentinels, and monitoring. Implement custom scaling policies based on your application metrics. Build a complete web API using your preferred framework with proper error handling and connection pooling.

These advanced features transform Fred from a simple Redis client into a comprehensive foundation for production Redis applications, handling security, reliability, performance, and operational concerns that are essential for real-world deployments.