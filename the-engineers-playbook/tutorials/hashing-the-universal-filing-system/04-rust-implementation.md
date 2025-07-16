# Rust Implementation: Building a Production-Ready Hash Table

Let's implement a hash table from scratch in Rust, focusing on memory safety, performance, and idiomatic code. This implementation will demonstrate key concepts while showcasing Rust's unique approach to systems programming.

## Project Setup

Create a new Rust project:

```bash
cargo new hash_table_tutorial
cd hash_table_tutorial
```

Add this to your `Cargo.toml`:

```toml
[package]
name = "hash_table_tutorial"
version = "0.1.0"
edition = "2021"

[dependencies]
```

## Basic Hash Table Structure

```rust
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::mem;

pub struct HashTable<K, V> {
    buckets: Vec<Vec<(K, V)>>,
    size: usize,
    len: usize,
    max_load_factor: f64,
}

impl<K, V> HashTable<K, V>
where
    K: Hash + Eq + Clone,
    V: Clone,
{
    pub fn new() -> Self {
        Self::with_capacity(16)
    }
    
    pub fn with_capacity(capacity: usize) -> Self {
        let size = capacity.max(16);
        Self {
            buckets: vec![Vec::new(); size],
            size,
            len: 0,
            max_load_factor: 0.75,
        }
    }
    
    fn hash(&self, key: &K) -> usize {
        let mut hasher = DefaultHasher::new();
        key.hash(&mut hasher);
        hasher.finish() as usize % self.size
    }
    
    fn load_factor(&self) -> f64 {
        self.len as f64 / self.size as f64
    }
    
    pub fn len(&self) -> usize {
        self.len
    }
    
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
}
```

## Core Operations

### Insert/Update Operation

```rust
impl<K, V> HashTable<K, V>
where
    K: Hash + Eq + Clone,
    V: Clone,
{
    pub fn insert(&mut self, key: K, value: V) -> Option<V> {
        // Check if we need to resize before inserting
        if self.load_factor() > self.max_load_factor {
            self.resize();
        }
        
        let index = self.hash(&key);
        let bucket = &mut self.buckets[index];
        
        // Check if key already exists
        for (existing_key, existing_value) in bucket.iter_mut() {
            if existing_key == &key {
                return Some(mem::replace(existing_value, value));
            }
        }
        
        // Key doesn't exist, insert new entry
        bucket.push((key, value));
        self.len += 1;
        None
    }
}
```

### Lookup Operation

```rust
impl<K, V> HashTable<K, V>
where
    K: Hash + Eq + Clone,
    V: Clone,
{
    pub fn get(&self, key: &K) -> Option<&V> {
        let index = self.hash(key);
        let bucket = &self.buckets[index];
        
        for (existing_key, existing_value) in bucket {
            if existing_key == key {
                return Some(existing_value);
            }
        }
        
        None
    }
    
    pub fn get_mut(&mut self, key: &K) -> Option<&mut V> {
        let index = self.hash(key);
        let bucket = &mut self.buckets[index];
        
        for (existing_key, existing_value) in bucket {
            if existing_key == key {
                return Some(existing_value);
            }
        }
        
        None
    }
}
```

### Remove Operation

```rust
impl<K, V> HashTable<K, V>
where
    K: Hash + Eq + Clone,
    V: Clone,
{
    pub fn remove(&mut self, key: &K) -> Option<V> {
        let index = self.hash(key);
        let bucket = &mut self.buckets[index];
        
        for (i, (existing_key, _)) in bucket.iter().enumerate() {
            if existing_key == key {
                let (_, value) = bucket.swap_remove(i);
                self.len -= 1;
                return Some(value);
            }
        }
        
        None
    }
}
```

## Resizing Implementation

```rust
impl<K, V> HashTable<K, V>
where
    K: Hash + Eq + Clone,
    V: Clone,
{
    fn resize(&mut self) {
        let old_buckets = mem::replace(&mut self.buckets, vec![Vec::new(); self.size * 2]);
        let old_size = self.size;
        
        self.size *= 2;
        self.len = 0; // Will be recalculated during reinsertion
        
        // Rehash all elements
        for bucket in old_buckets {
            for (key, value) in bucket {
                // Use internal insert to avoid triggering another resize
                let index = self.hash(&key);
                self.buckets[index].push((key, value));
                self.len += 1;
            }
        }
        
        println!("Resized from {} to {} buckets", old_size, self.size);
    }
}
```

## Iterator Implementation

```rust
pub struct HashTableIter<'a, K, V> {
    buckets: &'a [Vec<(K, V)>],
    bucket_index: usize,
    item_index: usize,
}

impl<'a, K, V> Iterator for HashTableIter<'a, K, V> {
    type Item = (&'a K, &'a V);
    
    fn next(&mut self) -> Option<Self::Item> {
        loop {
            if self.bucket_index >= self.buckets.len() {
                return None;
            }
            
            let bucket = &self.buckets[self.bucket_index];
            
            if self.item_index < bucket.len() {
                let item = &bucket[self.item_index];
                self.item_index += 1;
                return Some((&item.0, &item.1));
            }
            
            // Move to next bucket
            self.bucket_index += 1;
            self.item_index = 0;
        }
    }
}

impl<K, V> HashTable<K, V>
where
    K: Hash + Eq + Clone,
    V: Clone,
{
    pub fn iter(&self) -> HashTableIter<K, V> {
        HashTableIter {
            buckets: &self.buckets,
            bucket_index: 0,
            item_index: 0,
        }
    }
}
```

## Advanced Features

### Custom Hash Function

```rust
pub struct HashTableWithCustomHash<K, V, H> {
    buckets: Vec<Vec<(K, V)>>,
    size: usize,
    len: usize,
    hasher: H,
    max_load_factor: f64,
}

pub trait SimpleHasher<K> {
    fn hash(&self, key: &K, table_size: usize) -> usize;
}

struct StringHasher;

impl SimpleHasher<String> for StringHasher {
    fn hash(&self, key: &String, table_size: usize) -> usize {
        let mut hash = 0usize;
        for byte in key.bytes() {
            hash = hash.wrapping_mul(31).wrapping_add(byte as usize);
        }
        hash % table_size
    }
}
```

### Thread-Safe Version with Parking Lot

Add to `Cargo.toml`:
```toml
[dependencies]
parking_lot = "0.12"
```

```rust
use parking_lot::RwLock;
use std::sync::Arc;

pub struct ConcurrentHashTable<K, V> {
    inner: Arc<RwLock<HashTable<K, V>>>,
}

impl<K, V> ConcurrentHashTable<K, V>
where
    K: Hash + Eq + Clone,
    V: Clone,
{
    pub fn new() -> Self {
        Self {
            inner: Arc::new(RwLock::new(HashTable::new())),
        }
    }
    
    pub fn insert(&self, key: K, value: V) -> Option<V> {
        self.inner.write().insert(key, value)
    }
    
    pub fn get(&self, key: &K) -> Option<V> {
        self.inner.read().get(key).cloned()
    }
    
    pub fn remove(&self, key: &K) -> Option<V> {
        self.inner.write().remove(key)
    }
    
    pub fn len(&self) -> usize {
        self.inner.read().len()
    }
}

impl<K, V> Clone for ConcurrentHashTable<K, V> {
    fn clone(&self) -> Self {
        Self {
            inner: Arc::clone(&self.inner),
        }
    }
}
```

## Performance Optimizations

### Memory Pool for Reduced Allocations

```rust
use std::cell::RefCell;

struct MemoryPool<T> {
    pool: RefCell<Vec<T>>,
}

impl<T> MemoryPool<T> {
    fn new() -> Self {
        Self {
            pool: RefCell::new(Vec::new()),
        }
    }
    
    fn get(&self) -> Option<T> {
        self.pool.borrow_mut().pop()
    }
    
    fn return_item(&self, item: T) {
        self.pool.borrow_mut().push(item);
    }
}

// Usage in hash table for bucket recycling
pub struct PooledHashTable<K, V> {
    buckets: Vec<Vec<(K, V)>>,
    size: usize,
    len: usize,
    bucket_pool: MemoryPool<Vec<(K, V)>>,
}
```

### SIMD-Optimized Hash Function

```rust
// Note: This requires nightly Rust and specific CPU features
#[cfg(target_feature = "sse2")]
use std::arch::x86_64::*;

#[cfg(target_feature = "sse2")]
unsafe fn simd_hash(data: &[u8]) -> u32 {
    let mut hash = 0u32;
    let chunks = data.chunks_exact(16);
    let remainder = chunks.remainder();
    
    for chunk in chunks {
        let vector = _mm_loadu_si128(chunk.as_ptr() as *const __m128i);
        // SIMD hash computation here
        // This is a simplified example
        let sum = _mm_sad_epu8(vector, _mm_setzero_si128());
        hash = hash.wrapping_add(_mm_extract_epi16(sum, 0) as u32);
    }
    
    // Handle remainder bytes
    for &byte in remainder {
        hash = hash.wrapping_mul(31).wrapping_add(byte as u32);
    }
    
    hash
}
```

## Complete Example and Tests

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_basic_operations() {
        let mut table = HashTable::new();
        
        // Test insertion
        assert_eq!(table.insert("key1".to_string(), 100), None);
        assert_eq!(table.insert("key2".to_string(), 200), None);
        assert_eq!(table.len(), 2);
        
        // Test retrieval
        assert_eq!(table.get(&"key1".to_string()), Some(&100));
        assert_eq!(table.get(&"key3".to_string()), None);
        
        // Test update
        assert_eq!(table.insert("key1".to_string(), 150), Some(100));
        assert_eq!(table.get(&"key1".to_string()), Some(&150));
        
        // Test removal
        assert_eq!(table.remove(&"key1".to_string()), Some(150));
        assert_eq!(table.get(&"key1".to_string()), None);
        assert_eq!(table.len(), 1);
    }
    
    #[test]
    fn test_resize_behavior() {
        let mut table = HashTable::with_capacity(4);
        
        // Fill beyond load factor threshold
        for i in 0..10 {
            table.insert(format!("key{}", i), i);
        }
        
        // Verify all items are still accessible after resize
        for i in 0..10 {
            assert_eq!(table.get(&format!("key{}", i)), Some(&i));
        }
    }
    
    #[test]
    fn test_iterator() {
        let mut table = HashTable::new();
        table.insert("a".to_string(), 1);
        table.insert("b".to_string(), 2);
        table.insert("c".to_string(), 3);
        
        let mut items: Vec<_> = table.iter().collect();
        items.sort_by_key(|(k, _)| k.clone());
        
        assert_eq!(items.len(), 3);
        assert_eq!(items[0], (&"a".to_string(), &1));
        assert_eq!(items[1], (&"b".to_string(), &2));
        assert_eq!(items[2], (&"c".to_string(), &3));
    }
}

fn main() {
    let mut phonebook = HashTable::new();
    
    // Add contacts
    phonebook.insert("Alice Johnson".to_string(), "555-0123".to_string());
    phonebook.insert("Bob Smith".to_string(), "555-0456".to_string());
    phonebook.insert("Carol Davis".to_string(), "555-0789".to_string());
    
    // Look up numbers
    if let Some(number) = phonebook.get(&"Alice Johnson".to_string()) {
        println!("Alice's number: {}", number);
    }
    
    // Iterate through all contacts
    println!("\nAll contacts:");
    for (name, number) in phonebook.iter() {
        println!("{}: {}", name, number);
    }
    
    println!("Total contacts: {}", phonebook.len());
}
```

## Running and Testing

```bash
# Run the example
cargo run

# Run tests
cargo test

# Run with optimizations
cargo run --release

# Run tests with output
cargo test -- --nocapture
```

## Key Rust Features Demonstrated

1. **Ownership and Borrowing**: Safe memory management without garbage collection
2. **Generic Types**: `HashTable<K, V>` works with any hashable key type
3. **Trait Bounds**: Ensuring types implement required functionality
4. **Error Handling**: Using `Option<T>` for potentially missing values
5. **Zero-Cost Abstractions**: High-level code that compiles to efficient machine code
6. **Memory Safety**: No null pointer dereferences or buffer overflows
7. **Thread Safety**: Optional concurrent version using `RwLock`

This implementation demonstrates how Rust's type system and ownership model enable building high-performance, memory-safe data structures without sacrificing expressiveness or safety.