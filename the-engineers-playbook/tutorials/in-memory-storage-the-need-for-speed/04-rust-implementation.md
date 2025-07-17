# Rust Implementation: Building a Mini In-Memory Store

This implementation demonstrates the core concepts of in-memory storage by building a simplified Redis-like key-value store in Rust. We'll focus on the fundamental data structures and operations that make in-memory storage fast.

## Why Rust for This Implementation?

Rust is perfect for demonstrating in-memory storage concepts because:
- **Memory safety** without garbage collection overhead
- **Zero-cost abstractions** that don't hide performance characteristics
- **Explicit control** over memory layout and access patterns
- **Concurrent programming** support for multi-threaded scenarios

## Core Data Structure

Let's start with the foundation—a thread-safe hash map that stores our key-value pairs:

```rust
use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

// Value types our store can hold
#[derive(Clone, Debug)]
pub enum Value {
    String(String),
    Integer(i64),
    List(Vec<String>),
    Set(std::collections::HashSet<String>),
}

// Wrapper for values with expiration
#[derive(Clone, Debug)]
pub struct StoredValue {
    value: Value,
    expires_at: Option<Instant>,
}

// Main in-memory store
pub struct MemoryStore {
    data: Arc<RwLock<HashMap<String, StoredValue>>>,
}

impl MemoryStore {
    pub fn new() -> Self {
        Self {
            data: Arc::new(RwLock::new(HashMap::new())),
        }
    }
}
```

## Basic Operations: Set and Get

The heart of any key-value store is fast get/set operations:

```rust
impl MemoryStore {
    // Set a value with optional expiration
    pub fn set(&self, key: String, value: Value, ttl: Option<Duration>) -> Result<(), String> {
        let expires_at = ttl.map(|duration| Instant::now() + duration);
        
        let stored_value = StoredValue {
            value,
            expires_at,
        };

        // Acquire write lock only for the duration of the insert
        match self.data.write() {
            Ok(mut data) => {
                data.insert(key, stored_value);
                Ok(())
            }
            Err(_) => Err("Failed to acquire write lock".to_string()),
        }
    }

    // Get a value, checking for expiration
    pub fn get(&self, key: &str) -> Result<Option<Value>, String> {
        // Acquire read lock (allows multiple concurrent reads)
        match self.data.read() {
            Ok(data) => {
                match data.get(key) {
                    Some(stored_value) => {
                        // Check if value has expired
                        if let Some(expires_at) = stored_value.expires_at {
                            if Instant::now() > expires_at {
                                return Ok(None); // Expired
                            }
                        }
                        Ok(Some(stored_value.value.clone()))
                    }
                    None => Ok(None),
                }
            }
            Err(_) => Err("Failed to acquire read lock".to_string()),
        }
    }

    // Delete a key
    pub fn delete(&self, key: &str) -> Result<bool, String> {
        match self.data.write() {
            Ok(mut data) => {
                Ok(data.remove(key).is_some())
            }
            Err(_) => Err("Failed to acquire write lock".to_string()),
        }
    }
}
```

## List Operations

Let's implement Redis-style list operations to demonstrate working with complex data types:

```rust
impl MemoryStore {
    // Push to the front of a list
    pub fn lpush(&self, key: String, values: Vec<String>) -> Result<usize, String> {
        match self.data.write() {
            Ok(mut data) => {
                let entry = data.entry(key).or_insert_with(|| StoredValue {
                    value: Value::List(Vec::new()),
                    expires_at: None,
                });

                match &mut entry.value {
                    Value::List(list) => {
                        // Insert at the beginning (reverse order to maintain LIFO)
                        for value in values.into_iter().rev() {
                            list.insert(0, value);
                        }
                        Ok(list.len())
                    }
                    _ => Err("Key is not a list".to_string()),
                }
            }
            Err(_) => Err("Failed to acquire write lock".to_string()),
        }
    }

    // Pop from the front of a list
    pub fn lpop(&self, key: &str) -> Result<Option<String>, String> {
        match self.data.write() {
            Ok(mut data) => {
                match data.get_mut(key) {
                    Some(stored_value) => {
                        match &mut stored_value.value {
                            Value::List(list) => {
                                if list.is_empty() {
                                    Ok(None)
                                } else {
                                    Ok(Some(list.remove(0)))
                                }
                            }
                            _ => Err("Key is not a list".to_string()),
                        }
                    }
                    None => Ok(None),
                }
            }
            Err(_) => Err("Failed to acquire write lock".to_string()),
        }
    }

    // Get a range of list elements
    pub fn lrange(&self, key: &str, start: isize, stop: isize) -> Result<Vec<String>, String> {
        match self.data.read() {
            Ok(data) => {
                match data.get(key) {
                    Some(stored_value) => {
                        match &stored_value.value {
                            Value::List(list) => {
                                let len = list.len() as isize;
                                
                                // Handle negative indices (from end)
                                let start_idx = if start < 0 { 
                                    std::cmp::max(0, len + start) as usize 
                                } else { 
                                    std::cmp::min(start as usize, list.len()) 
                                };
                                
                                let stop_idx = if stop < 0 { 
                                    std::cmp::max(0, len + stop + 1) as usize 
                                } else { 
                                    std::cmp::min(stop as usize + 1, list.len()) 
                                };

                                if start_idx >= stop_idx {
                                    Ok(Vec::new())
                                } else {
                                    Ok(list[start_idx..stop_idx].to_vec())
                                }
                            }
                            _ => Err("Key is not a list".to_string()),
                        }
                    }
                    None => Ok(Vec::new()),
                }
            }
            Err(_) => Err("Failed to acquire read lock".to_string()),
        }
    }
}
```

## Atomic Operations

One of the key advantages of in-memory stores is the ability to perform atomic operations efficiently:

```rust
impl MemoryStore {
    // Atomically increment a counter
    pub fn incr(&self, key: String) -> Result<i64, String> {
        match self.data.write() {
            Ok(mut data) => {
                let entry = data.entry(key).or_insert_with(|| StoredValue {
                    value: Value::Integer(0),
                    expires_at: None,
                });

                match &mut entry.value {
                    Value::Integer(ref mut n) => {
                        *n += 1;
                        Ok(*n)
                    }
                    _ => Err("Key is not an integer".to_string()),
                }
            }
            Err(_) => Err("Failed to acquire write lock".to_string()),
        }
    }

    // Atomically decrement a counter
    pub fn decr(&self, key: String) -> Result<i64, String> {
        match self.data.write() {
            Ok(mut data) => {
                let entry = data.entry(key).or_insert_with(|| StoredValue {
                    value: Value::Integer(0),
                    expires_at: None,
                });

                match &mut entry.value {
                    Value::Integer(ref mut n) => {
                        *n -= 1;
                        Ok(*n)
                    }
                    _ => Err("Key is not an integer".to_string()),
                }
            }
            Err(_) => Err("Failed to acquire write lock".to_string()),
        }
    }
}
```

## Expiration and Cleanup

A background task to clean up expired keys demonstrates how in-memory stores handle automatic data lifecycle:

```rust
use std::thread;
use std::time::Duration;

impl MemoryStore {
    // Start a background thread to clean up expired keys
    pub fn start_expiration_cleanup(&self) {
        let data = Arc::clone(&self.data);
        
        thread::spawn(move || {
            loop {
                thread::sleep(Duration::from_secs(1)); // Check every second
                
                if let Ok(mut store) = data.write() {
                    let now = Instant::now();
                    let mut keys_to_remove = Vec::new();
                    
                    // Collect expired keys
                    for (key, stored_value) in store.iter() {
                        if let Some(expires_at) = stored_value.expires_at {
                            if now > expires_at {
                                keys_to_remove.push(key.clone());
                            }
                        }
                    }
                    
                    // Remove expired keys
                    for key in keys_to_remove {
                        store.remove(&key);
                    }
                }
            }
        });
    }

    // Get statistics about the store
    pub fn stats(&self) -> Result<(usize, usize), String> {
        match self.data.read() {
            Ok(data) => {
                let total_keys = data.len();
                let now = Instant::now();
                let expired_keys = data.values()
                    .filter(|v| v.expires_at.map_or(false, |exp| now > exp))
                    .count();
                
                Ok((total_keys, expired_keys))
            }
            Err(_) => Err("Failed to acquire read lock".to_string()),
        }
    }
}
```

## Usage Example and Benchmarking

Here's how to use our in-memory store and measure its performance:

```rust
fn main() -> Result<(), Box<dyn std::error::Error>> {
    let store = MemoryStore::new();
    
    // Start automatic cleanup of expired keys
    store.start_expiration_cleanup();

    // Basic operations
    store.set("user:1".to_string(), Value::String("Alice".to_string()), None)?;
    store.set("counter".to_string(), Value::Integer(0), None)?;
    store.set("temp".to_string(), Value::String("temporary".to_string()), 
              Some(Duration::from_secs(5)))?;

    // List operations
    store.lpush("recent_users".to_string(), vec!["alice".to_string(), "bob".to_string()])?;
    
    // Atomic operations
    for _ in 0..1000 {
        store.incr("page_views".to_string())?;
    }

    // Performance benchmark
    benchmark_operations(&store)?;
    
    Ok(())
}

fn benchmark_operations(store: &MemoryStore) -> Result<(), String> {
    use std::time::Instant;
    
    let start = Instant::now();
    let operations = 100_000;
    
    // Benchmark SET operations
    for i in 0..operations {
        store.set(format!("bench:{}", i), Value::Integer(i as i64), None)?;
    }
    
    let set_duration = start.elapsed();
    println!("SET: {} ops in {:?} ({:.0} ops/sec)", 
             operations, set_duration, 
             operations as f64 / set_duration.as_secs_f64());

    // Benchmark GET operations
    let start = Instant::now();
    for i in 0..operations {
        store.get(&format!("bench:{}", i))?;
    }
    
    let get_duration = start.elapsed();
    println!("GET: {} ops in {:?} ({:.0} ops/sec)", 
             operations, get_duration, 
             operations as f64 / get_duration.as_secs_f64());

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_operations() {
        let store = MemoryStore::new();
        
        // Test set and get
        store.set("key1".to_string(), Value::String("value1".to_string()), None).unwrap();
        let result = store.get("key1").unwrap();
        assert!(matches!(result, Some(Value::String(s)) if s == "value1"));
        
        // Test delete
        assert!(store.delete("key1").unwrap());
        assert!(store.get("key1").unwrap().is_none());
    }

    #[test]
    fn test_expiration() {
        let store = MemoryStore::new();
        
        // Set with very short TTL
        store.set("temp".to_string(), Value::String("temporary".to_string()), 
                  Some(Duration::from_millis(10))).unwrap();
        
        // Should exist immediately
        assert!(store.get("temp").unwrap().is_some());
        
        // Wait for expiration
        std::thread::sleep(Duration::from_millis(20));
        
        // Should be expired
        assert!(store.get("temp").unwrap().is_none());
    }

    #[test]
    fn test_atomic_operations() {
        let store = MemoryStore::new();
        
        // Test increment
        assert_eq!(store.incr("counter".to_string()).unwrap(), 1);
        assert_eq!(store.incr("counter".to_string()).unwrap(), 2);
        assert_eq!(store.decr("counter".to_string()).unwrap(), 1);
    }
}
```

## Advanced Features: Connection Handling and Protocol

Let's add a simple TCP server to make our store network-accessible:

```rust
use std::net::{TcpListener, TcpStream};
use std::io::{BufRead, BufReader, Write};
use std::thread;

impl MemoryStore {
    // Start a TCP server for network access
    pub fn start_server(&self, addr: &str) -> std::io::Result<()> {
        let listener = TcpListener::bind(addr)?;
        println!("Memory store server listening on {}", addr);
        
        let store = Arc::clone(&self.data);
        
        for stream in listener.incoming() {
            match stream {
                Ok(stream) => {
                    let store_clone = Arc::clone(&store);
                    thread::spawn(move || {
                        if let Err(e) = handle_client(stream, store_clone) {
                            eprintln!("Error handling client: {}", e);
                        }
                    });
                }
                Err(e) => eprintln!("Error accepting connection: {}", e),
            }
        }
        Ok(())
    }
}

// Simple protocol handler
fn handle_client(mut stream: TcpStream, store: Arc<RwLock<HashMap<String, StoredValue>>>) -> std::io::Result<()> {
    let reader = BufReader::new(&stream);
    
    for line in reader.lines() {
        let command = line?;
        let response = process_command(&command, &store);
        
        writeln!(stream, "{}", response)?;
        stream.flush()?;
    }
    
    Ok(())
}

// Process Redis-like commands
fn process_command(command: &str, store: &Arc<RwLock<HashMap<String, StoredValue>>>) -> String {
    let parts: Vec<&str> = command.trim().split_whitespace().collect();
    
    if parts.is_empty() {
        return "ERROR: Empty command".to_string();
    }
    
    match parts[0].to_uppercase().as_str() {
        "SET" => {
            if parts.len() >= 3 {
                let key = parts[1].to_string();
                let value = parts[2..].join(" ");
                
                if let Ok(mut data) = store.write() {
                    data.insert(key, StoredValue {
                        value: Value::String(value),
                        expires_at: None,
                    });
                    "OK".to_string()
                } else {
                    "ERROR: Could not acquire lock".to_string()
                }
            } else {
                "ERROR: SET requires key and value".to_string()
            }
        }
        "GET" => {
            if parts.len() >= 2 {
                let key = parts[1];
                
                if let Ok(data) = store.read() {
                    match data.get(key) {
                        Some(stored_value) => {
                            if let Some(expires_at) = stored_value.expires_at {
                                if Instant::now() > expires_at {
                                    "(nil)".to_string()
                                } else {
                                    format!("{:?}", stored_value.value)
                                }
                            } else {
                                format!("{:?}", stored_value.value)
                            }
                        }
                        None => "(nil)".to_string(),
                    }
                } else {
                    "ERROR: Could not acquire lock".to_string()
                }
            } else {
                "ERROR: GET requires key".to_string()
            }
        }
        "PING" => "PONG".to_string(),
        "INFO" => {
            if let Ok(data) = store.read() {
                format!("keys:{}\nmemory_usage:{}kb", data.len(), data.len() * 64 / 1024)
            } else {
                "ERROR: Could not acquire lock".to_string()
            }
        }
        _ => format!("ERROR: Unknown command '{}'", parts[0]),
    }
}
```

## Performance Optimization: Memory Pool

For high-performance scenarios, we can add a memory pool to reduce allocations:

```rust
use std::collections::VecDeque;
use std::sync::Mutex;

pub struct MemoryPool<T> {
    pool: Mutex<VecDeque<T>>,
    factory: Box<dyn Fn() -> T + Send + Sync>,
}

impl<T> MemoryPool<T> {
    pub fn new<F>(factory: F) -> Self 
    where 
        F: Fn() -> T + Send + Sync + 'static 
    {
        Self {
            pool: Mutex::new(VecDeque::new()),
            factory: Box::new(factory),
        }
    }
    
    pub fn get(&self) -> T {
        if let Ok(mut pool) = self.pool.lock() {
            pool.pop_front().unwrap_or_else(|| (self.factory)())
        } else {
            (self.factory)()
        }
    }
    
    pub fn return_item(&self, item: T) {
        if let Ok(mut pool) = self.pool.lock() {
            if pool.len() < 1000 { // Prevent unbounded growth
                pool.push_back(item);
            }
        }
    }
}

// Usage in our store
impl MemoryStore {
    pub fn with_memory_pool() -> Self {
        Self {
            data: Arc::new(RwLock::new(HashMap::new())),
            // Add memory pool for string allocations if needed
        }
    }
}
```

## Monitoring and Metrics

```rust
use std::sync::atomic::{AtomicU64, Ordering};

pub struct StoreMetrics {
    pub operations_total: AtomicU64,
    pub cache_hits: AtomicU64,
    pub cache_misses: AtomicU64,
    pub expired_keys_cleaned: AtomicU64,
}

impl StoreMetrics {
    pub fn new() -> Self {
        Self {
            operations_total: AtomicU64::new(0),
            cache_hits: AtomicU64::new(0),
            cache_misses: AtomicU64::new(0),
            expired_keys_cleaned: AtomicU64::new(0),
        }
    }
    
    pub fn hit_rate(&self) -> f64 {
        let hits = self.cache_hits.load(Ordering::Relaxed) as f64;
        let total = hits + self.cache_misses.load(Ordering::Relaxed) as f64;
        
        if total > 0.0 {
            hits / total
        } else {
            0.0
        }
    }
}

// Add metrics to our store
impl MemoryStore {
    pub fn get_metrics(&self) -> Result<String, String> {
        // Return JSON-formatted metrics
        Ok(format!(r#"{{
            "operations_total": {},
            "cache_hit_rate": {:.2},
            "memory_usage_mb": {}
        }}"#, 
        1000, // placeholder values
        0.95,
        64))
    }
}
```

## Key Design Decisions

This implementation demonstrates several important concepts:

```mermaid
graph TD
    subgraph "Architecture Overview"
        A[TCP Server<br/>Network Interface] --> B[Command Parser<br/>Protocol Handler]
        B --> C[Memory Store<br/>Core Engine]
        C --> D[Hash Map<br/>O(1) Access]
        C --> E[Expiration Manager<br/>Background Cleanup]
        C --> F[Metrics Collector<br/>Performance Monitoring]
    end
    
    subgraph "Concurrency Model"
        G[Read-Write Locks<br/>Multiple readers,<br/>Single writer] --> H[Short Critical Sections<br/>Minimize contention]
        H --> I[Lock-Free Metrics<br/>Atomic operations]
    end
    
    subgraph "Memory Management"
        J[Inline Storage<br/>Minimize pointer chasing] --> K[Memory Pools<br/>Reduce allocations]
        K --> L[Automatic Cleanup<br/>Expired key removal]
    end
    
    style D fill:#0f9,stroke:#0f9,stroke-width:2px
    style G fill:#0f9,stroke:#0f9,stroke-width:2px
    style J fill:#0f9,stroke:#0f9,stroke-width:2px
```

### 1. Memory Layout Efficiency
- Uses `HashMap` for O(1) average-case access
- Stores values inline to minimize pointer chasing
- Uses `Arc<RwLock<>>` for safe concurrent access
- Memory pools reduce allocation overhead

### 2. Concurrency Model
- **Read-write locks** allow multiple concurrent readers
- **Short critical sections** minimize lock contention
- **Lock-free metrics** using atomic operations
- **Thread-per-connection** model for network access

### 3. Memory Management
- **Automatic cleanup** removes expired keys
- **Clone-on-read** for safety without long-lived locks
- **Explicit TTL handling** with efficient time comparisons
- **Memory pools** for high-frequency allocations

### 4. Performance Characteristics
- **O(1) basic operations** through hash table access
- **Minimal allocations** during common operations
- **Predictable performance** without hidden disk I/O
- **Network protocol** support for real-world usage

## Running the Code

To run this implementation:

```bash
# Create a new Rust project
cargo new memory_store --lib
cd memory_store

# Add to Cargo.toml
[dependencies]
# No external dependencies needed!

# Replace src/lib.rs with the code above
# Add a src/main.rs for the example

# Run the example
cargo run

# Run the tests
cargo test
```

This implementation captures the essence of what makes in-memory storage fast: simple data structures, efficient memory access patterns, and elimination of I/O from the critical path. While simplified compared to production systems like Redis, it demonstrates the core principles that make in-memory storage a powerful tool for high-performance applications.