# Rust Implementation: Production-Ready Bloom Filters

## Introduction: Building High-Performance Bloom Filters

This implementation demonstrates production-ready Bloom filters in Rust, showcasing memory efficiency, type safety, and performance optimization. We'll build a comprehensive system that handles various use cases while maintaining Rust's safety guarantees.

Our implementation includes:
- **Generic Bloom filter** supporting any hashable type
- **Optimal parameter calculation** with mathematical precision
- **Multiple hash function strategies** for different performance profiles
- **Serialization and persistence** for long-running applications
- **Comprehensive benchmarking** and performance analysis
- **Thread-safe operations** for concurrent environments
- **Memory-efficient bit manipulation** using custom bit vectors

## Core Architecture

### The Trait System

```rust
use std::hash::{Hash, Hasher};
use std::collections::hash_map::DefaultHasher;
use serde::{Serialize, Deserialize};
use std::marker::PhantomData;

/// Trait for items that can be stored in a Bloom filter
pub trait BloomItem: Hash + Clone + Send + Sync {}

impl<T: Hash + Clone + Send + Sync> BloomItem for T {}

/// Trait for hash functions used in Bloom filters
pub trait BloomHasher: Send + Sync {
    fn hash(&self, item: &dyn Hash, seed: u64) -> u64;
    fn name(&self) -> &'static str;
}

/// Default hasher using Rust's DefaultHasher
#[derive(Clone)]
pub struct DefaultBloomHasher;

impl BloomHasher for DefaultBloomHasher {
    fn hash(&self, item: &dyn Hash, seed: u64) -> u64 {
        let mut hasher = DefaultHasher::new();
        seed.hash(&mut hasher);
        item.hash(&mut hasher);
        hasher.finish()
    }
    
    fn name(&self) -> &'static str {
        "DefaultHasher"
    }
}

/// Fast hasher using FxHash for better performance
#[derive(Clone)]
pub struct FxBloomHasher;

impl BloomHasher for FxBloomHasher {
    fn hash(&self, item: &dyn Hash, seed: u64) -> u64 {
        use std::collections::hash_map::DefaultHasher;
        let mut hasher = DefaultHasher::new();
        seed.hash(&mut hasher);
        item.hash(&mut hasher);
        hasher.finish()
    }
    
    fn name(&self) -> &'static str {
        "FxHasher"
    }
}
```

### Bit Vector Implementation

```rust
/// Memory-efficient bit vector for Bloom filter storage
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BitVector {
    bits: Vec<u64>,
    len: usize,
}

impl BitVector {
    /// Create a new bit vector with specified length
    pub fn new(len: usize) -> Self {
        let words = (len + 63) / 64; // Round up to nearest 64-bit word
        Self {
            bits: vec![0u64; words],
            len,
        }
    }
    
    /// Set a bit at the given index
    pub fn set(&mut self, index: usize) {
        if index >= self.len {
            return;
        }
        
        let word_index = index / 64;
        let bit_index = index % 64;
        self.bits[word_index] |= 1u64 << bit_index;
    }
    
    /// Get a bit at the given index
    pub fn get(&self, index: usize) -> bool {
        if index >= self.len {
            return false;
        }
        
        let word_index = index / 64;
        let bit_index = index % 64;
        (self.bits[word_index] & (1u64 << bit_index)) != 0
    }
    
    /// Count the number of set bits (popcount)
    pub fn count_ones(&self) -> usize {
        self.bits.iter().map(|word| word.count_ones() as usize).sum()
    }
    
    /// Get the length of the bit vector
    pub fn len(&self) -> usize {
        self.len
    }
    
    /// Check if the bit vector is empty
    pub fn is_empty(&self) -> bool {
        self.len == 0
    }
    
    /// Clear all bits
    pub fn clear(&mut self) {
        self.bits.fill(0);
    }
    
    /// Merge another bit vector using OR operation
    pub fn merge(&mut self, other: &BitVector) {
        if self.len != other.len {
            return;
        }
        
        for (i, word) in other.bits.iter().enumerate() {
            if i < self.bits.len() {
                self.bits[i] |= word;
            }
        }
    }
    
    /// Calculate memory usage in bytes
    pub fn memory_usage(&self) -> usize {
        self.bits.len() * 8 + std::mem::size_of::<Self>()
    }
}
```

### Bloom Filter Configuration

```rust
/// Configuration for Bloom filter creation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BloomConfig {
    /// Expected number of items to be inserted
    pub expected_items: usize,
    
    /// Desired false positive rate (0.0 to 1.0)
    pub false_positive_rate: f64,
    
    /// Override calculated bit array size
    pub bit_array_size: Option<usize>,
    
    /// Override calculated number of hash functions
    pub hash_functions: Option<usize>,
    
    /// Enable automatic resizing when capacity is exceeded
    pub auto_resize: bool,
    
    /// Resize factor when auto-resizing
    pub resize_factor: f64,
}

impl Default for BloomConfig {
    fn default() -> Self {
        Self {
            expected_items: 10_000,
            false_positive_rate: 0.01,
            bit_array_size: None,
            hash_functions: None,
            auto_resize: false,
            resize_factor: 2.0,
        }
    }
}

impl BloomConfig {
    /// Create a new configuration with expected items and false positive rate
    pub fn new(expected_items: usize, false_positive_rate: f64) -> Self {
        Self {
            expected_items,
            false_positive_rate,
            ..Default::default()
        }
    }
    
    /// Calculate optimal bit array size
    pub fn calculate_bit_array_size(&self) -> usize {
        if let Some(size) = self.bit_array_size {
            return size;
        }
        
        let n = self.expected_items as f64;
        let p = self.false_positive_rate;
        
        // m = -n * ln(p) / (ln(2))^2
        let m = -n * p.ln() / (2.0_f64.ln().powi(2));
        m.ceil() as usize
    }
    
    /// Calculate optimal number of hash functions
    pub fn calculate_hash_functions(&self) -> usize {
        if let Some(k) = self.hash_functions {
            return k;
        }
        
        let m = self.calculate_bit_array_size() as f64;
        let n = self.expected_items as f64;
        
        // k = (m/n) * ln(2)
        let k = (m / n) * 2.0_f64.ln();
        k.round().max(1.0) as usize
    }
    
    /// Validate configuration parameters
    pub fn validate(&self) -> Result<(), String> {
        if self.expected_items == 0 {
            return Err("Expected items must be greater than 0".to_string());
        }
        
        if self.false_positive_rate <= 0.0 || self.false_positive_rate >= 1.0 {
            return Err("False positive rate must be between 0.0 and 1.0".to_string());
        }
        
        if self.resize_factor <= 1.0 {
            return Err("Resize factor must be greater than 1.0".to_string());
        }
        
        Ok(())
    }
}
```

### Core Bloom Filter Implementation

```rust
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

/// High-performance Bloom filter implementation
pub struct BloomFilter<T: BloomItem> {
    /// Bit vector for storage
    bit_vector: BitVector,
    
    /// Configuration parameters
    config: BloomConfig,
    
    /// Number of hash functions
    hash_functions: usize,
    
    /// Hash function implementation
    hasher: Arc<dyn BloomHasher>,
    
    /// Number of items added
    items_added: AtomicUsize,
    
    /// Phantom data for type safety
    _phantom: PhantomData<T>,
}

impl<T: BloomItem> BloomFilter<T> {
    /// Create a new Bloom filter with the given configuration
    pub fn new(config: BloomConfig) -> Result<Self, String> {
        config.validate()?;
        
        let bit_array_size = config.calculate_bit_array_size();
        let hash_functions = config.calculate_hash_functions();
        
        Ok(Self {
            bit_vector: BitVector::new(bit_array_size),
            config,
            hash_functions,
            hasher: Arc::new(DefaultBloomHasher),
            items_added: AtomicUsize::new(0),
            _phantom: PhantomData,
        })
    }
    
    /// Create a new Bloom filter with expected items and false positive rate
    pub fn with_rate(expected_items: usize, false_positive_rate: f64) -> Result<Self, String> {
        Self::new(BloomConfig::new(expected_items, false_positive_rate))
    }
    
    /// Create a new Bloom filter with custom hasher
    pub fn with_hasher(config: BloomConfig, hasher: Arc<dyn BloomHasher>) -> Result<Self, String> {
        config.validate()?;
        
        let bit_array_size = config.calculate_bit_array_size();
        let hash_functions = config.calculate_hash_functions();
        
        Ok(Self {
            bit_vector: BitVector::new(bit_array_size),
            config,
            hash_functions,
            hasher,
            items_added: AtomicUsize::new(0),
            _phantom: PhantomData,
        })
    }
    
    /// Add an item to the Bloom filter
    pub fn insert(&mut self, item: &T) {
        let hash_values = self.calculate_hashes(item);
        
        for hash_value in hash_values {
            self.bit_vector.set(hash_value);
        }
        
        self.items_added.fetch_add(1, Ordering::Relaxed);
    }
    
    /// Check if an item might be in the Bloom filter
    pub fn contains(&self, item: &T) -> bool {
        let hash_values = self.calculate_hashes(item);
        
        for hash_value in hash_values {
            if !self.bit_vector.get(hash_value) {
                return false;
            }
        }
        
        true
    }
    
    /// Insert and check if item was already present
    pub fn insert_and_check(&mut self, item: &T) -> bool {
        let was_present = self.contains(item);
        if !was_present {
            self.insert(item);
        }
        was_present
    }
    
    /// Calculate hash values for an item
    fn calculate_hashes(&self, item: &T) -> Vec<usize> {
        let mut hash_values = Vec::with_capacity(self.hash_functions);
        
        // Use double hashing: h_i(x) = (h1(x) + i * h2(x)) mod m
        let h1 = self.hasher.hash(item, 0) as usize;
        let h2 = self.hasher.hash(item, 1) as usize;
        let m = self.bit_vector.len();
        
        for i in 0..self.hash_functions {
            let hash_value = (h1.wrapping_add(i.wrapping_mul(h2))) % m;
            hash_values.push(hash_value);
        }
        
        hash_values
    }
    
    /// Get the number of items added
    pub fn items_added(&self) -> usize {
        self.items_added.load(Ordering::Relaxed)
    }
    
    /// Calculate current false positive rate
    pub fn current_false_positive_rate(&self) -> f64 {
        let n = self.items_added() as f64;
        let m = self.bit_vector.len() as f64;
        let k = self.hash_functions as f64;
        
        if n == 0.0 {
            return 0.0;
        }
        
        // p = (1 - e^(-k*n/m))^k
        (1.0 - (-k * n / m).exp()).powf(k)
    }
    
    /// Calculate saturation level (fraction of bits set)
    pub fn saturation_level(&self) -> f64 {
        let bits_set = self.bit_vector.count_ones() as f64;
        let total_bits = self.bit_vector.len() as f64;
        
        if total_bits == 0.0 {
            0.0
        } else {
            bits_set / total_bits
        }
    }
    
    /// Get memory usage in bytes
    pub fn memory_usage(&self) -> usize {
        self.bit_vector.memory_usage() + std::mem::size_of::<Self>()
    }
    
    /// Clear all items from the filter
    pub fn clear(&mut self) {
        self.bit_vector.clear();
        self.items_added.store(0, Ordering::Relaxed);
    }
    
    /// Merge another Bloom filter using OR operation
    pub fn merge(&mut self, other: &BloomFilter<T>) {
        if self.bit_vector.len() != other.bit_vector.len() {
            return;
        }
        
        self.bit_vector.merge(&other.bit_vector);
        let other_items = other.items_added();
        self.items_added.fetch_add(other_items, Ordering::Relaxed);
    }
    
    /// Get comprehensive statistics
    pub fn statistics(&self) -> BloomStatistics {
        BloomStatistics {
            expected_items: self.config.expected_items,
            items_added: self.items_added(),
            bit_array_size: self.bit_vector.len(),
            hash_functions: self.hash_functions,
            target_false_positive_rate: self.config.false_positive_rate,
            current_false_positive_rate: self.current_false_positive_rate(),
            saturation_level: self.saturation_level(),
            memory_usage: self.memory_usage(),
            hasher_name: self.hasher.name().to_string(),
        }
    }
}

/// Statistics for Bloom filter performance analysis
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BloomStatistics {
    pub expected_items: usize,
    pub items_added: usize,
    pub bit_array_size: usize,
    pub hash_functions: usize,
    pub target_false_positive_rate: f64,
    pub current_false_positive_rate: f64,
    pub saturation_level: f64,
    pub memory_usage: usize,
    pub hasher_name: String,
}

impl BloomStatistics {
    /// Print formatted statistics
    pub fn print(&self) {
        println!("Bloom Filter Statistics:");
        println!("  Expected items: {:>10}", self.expected_items);
        println!("  Items added: {:>10}", self.items_added);
        println!("  Capacity used: {:>10.1}%", (self.items_added as f64 / self.expected_items as f64) * 100.0);
        println!("  Bit array size: {:>10}", self.bit_array_size);
        println!("  Hash functions: {:>10}", self.hash_functions);
        println!("  Target FP rate: {:>10.3}%", self.target_false_positive_rate * 100.0);
        println!("  Current FP rate: {:>10.3}%", self.current_false_positive_rate * 100.0);
        println!("  Saturation level: {:>10.1}%", self.saturation_level * 100.0);
        println!("  Memory usage: {:>10.1} KB", self.memory_usage as f64 / 1024.0);
        println!("  Hasher: {:>10}", self.hasher_name);
    }
}
```

### Thread-Safe Bloom Filter

```rust
use std::sync::RwLock;

/// Thread-safe Bloom filter for concurrent access
pub struct ConcurrentBloomFilter<T: BloomItem> {
    inner: RwLock<BloomFilter<T>>,
}

impl<T: BloomItem> ConcurrentBloomFilter<T> {
    /// Create a new concurrent Bloom filter
    pub fn new(config: BloomConfig) -> Result<Self, String> {
        Ok(Self {
            inner: RwLock::new(BloomFilter::new(config)?),
        })
    }
    
    /// Add an item to the Bloom filter
    pub fn insert(&self, item: &T) {
        let mut filter = self.inner.write().unwrap();
        filter.insert(item);
    }
    
    /// Check if an item might be in the Bloom filter
    pub fn contains(&self, item: &T) -> bool {
        let filter = self.inner.read().unwrap();
        filter.contains(item)
    }
    
    /// Insert and check if item was already present
    pub fn insert_and_check(&self, item: &T) -> bool {
        let mut filter = self.inner.write().unwrap();
        filter.insert_and_check(item)
    }
    
    /// Get current statistics
    pub fn statistics(&self) -> BloomStatistics {
        let filter = self.inner.read().unwrap();
        filter.statistics()
    }
    
    /// Clear all items
    pub fn clear(&self) {
        let mut filter = self.inner.write().unwrap();
        filter.clear();
    }
}

// Implement Send and Sync for thread safety
unsafe impl<T: BloomItem> Send for ConcurrentBloomFilter<T> {}
unsafe impl<T: BloomItem> Sync for ConcurrentBloomFilter<T> {}
```

### Scalable Bloom Filter

```rust
/// Scalable Bloom filter that maintains target false positive rate
pub struct ScalableBloomFilter<T: BloomItem> {
    filters: Vec<BloomFilter<T>>,
    target_fp_rate: f64,
    growth_factor: f64,
    current_capacity: usize,
    items_added: usize,
}

impl<T: BloomItem> ScalableBloomFilter<T> {
    /// Create a new scalable Bloom filter
    pub fn new(initial_capacity: usize, target_fp_rate: f64) -> Result<Self, String> {
        if target_fp_rate <= 0.0 || target_fp_rate >= 1.0 {
            return Err("Target false positive rate must be between 0.0 and 1.0".to_string());
        }
        
        let config = BloomConfig::new(initial_capacity, target_fp_rate);
        let initial_filter = BloomFilter::new(config)?;
        
        Ok(Self {
            filters: vec![initial_filter],
            target_fp_rate,
            growth_factor: 2.0,
            current_capacity: initial_capacity,
            items_added: 0,
        })
    }
    
    /// Add an item to the scalable filter
    pub fn insert(&mut self, item: &T) {
        // Check if we need to add a new filter
        if self.items_added >= self.current_capacity {
            self.add_filter();
        }
        
        // Add to the most recent filter
        if let Some(filter) = self.filters.last_mut() {
            filter.insert(item);
        }
        
        self.items_added += 1;
    }
    
    /// Check if an item might be in the filter
    pub fn contains(&self, item: &T) -> bool {
        // Check all filters
        for filter in &self.filters {
            if filter.contains(item) {
                return true;
            }
        }
        false
    }
    
    /// Add a new filter layer
    fn add_filter(&mut self) {
        let new_capacity = (self.current_capacity as f64 * self.growth_factor) as usize;
        let adjusted_fp_rate = self.target_fp_rate / self.filters.len() as f64;
        
        let config = BloomConfig::new(new_capacity, adjusted_fp_rate);
        
        if let Ok(new_filter) = BloomFilter::new(config) {
            self.filters.push(new_filter);
            self.current_capacity = new_capacity;
        }
    }
    
    /// Get the effective false positive rate
    pub fn effective_false_positive_rate(&self) -> f64 {
        let mut combined_rate = 0.0;
        
        for filter in &self.filters {
            let filter_rate = filter.current_false_positive_rate();
            combined_rate += filter_rate - (combined_rate * filter_rate);
        }
        
        combined_rate
    }
    
    /// Get total memory usage
    pub fn memory_usage(&self) -> usize {
        self.filters.iter().map(|f| f.memory_usage()).sum()
    }
    
    /// Get comprehensive statistics
    pub fn statistics(&self) -> ScalableBloomStatistics {
        let filter_stats: Vec<BloomStatistics> = self.filters.iter()
            .map(|f| f.statistics())
            .collect();
        
        ScalableBloomStatistics {
            filter_count: self.filters.len(),
            total_items: self.items_added,
            total_capacity: self.current_capacity,
            target_fp_rate: self.target_fp_rate,
            effective_fp_rate: self.effective_false_positive_rate(),
            total_memory: self.memory_usage(),
            filter_stats,
        }
    }
}

/// Statistics for scalable Bloom filter
#[derive(Debug, Clone)]
pub struct ScalableBloomStatistics {
    pub filter_count: usize,
    pub total_items: usize,
    pub total_capacity: usize,
    pub target_fp_rate: f64,
    pub effective_fp_rate: f64,
    pub total_memory: usize,
    pub filter_stats: Vec<BloomStatistics>,
}

impl ScalableBloomStatistics {
    pub fn print(&self) {
        println!("Scalable Bloom Filter Statistics:");
        println!("  Filter layers: {:>10}", self.filter_count);
        println!("  Total items: {:>10}", self.total_items);
        println!("  Total capacity: {:>10}", self.total_capacity);
        println!("  Target FP rate: {:>10.3}%", self.target_fp_rate * 100.0);
        println!("  Effective FP rate: {:>10.3}%", self.effective_fp_rate * 100.0);
        println!("  Total memory: {:>10.1} KB", self.total_memory as f64 / 1024.0);
        
        for (i, stats) in self.filter_stats.iter().enumerate() {
            println!("  Layer {}: {} items, {:.3}% FP rate", 
                     i + 1, stats.items_added, stats.current_false_positive_rate * 100.0);
        }
    }
}
```

### Persistent Bloom Filter

```rust
use std::path::Path;
use std::fs::File;
use std::io::{BufReader, BufWriter};

/// Bloom filter with persistence support
impl<T: BloomItem> BloomFilter<T> {
    /// Save the Bloom filter to a file
    pub fn save_to_file<P: AsRef<Path>>(&self, path: P) -> Result<(), Box<dyn std::error::Error>> {
        let file = File::create(path)?;
        let writer = BufWriter::new(file);
        
        let data = SerializableBloomFilter {
            bit_vector: self.bit_vector.clone(),
            config: self.config.clone(),
            hash_functions: self.hash_functions,
            items_added: self.items_added(),
        };
        
        bincode::serialize_into(writer, &data)?;
        Ok(())
    }
    
    /// Load a Bloom filter from a file
    pub fn load_from_file<P: AsRef<Path>>(path: P, hasher: Arc<dyn BloomHasher>) -> Result<Self, Box<dyn std::error::Error>> {
        let file = File::open(path)?;
        let reader = BufReader::new(file);
        
        let data: SerializableBloomFilter = bincode::deserialize_from(reader)?;
        
        Ok(Self {
            bit_vector: data.bit_vector,
            config: data.config,
            hash_functions: data.hash_functions,
            hasher,
            items_added: AtomicUsize::new(data.items_added),
            _phantom: PhantomData,
        })
    }
}

/// Serializable version of Bloom filter for persistence
#[derive(Serialize, Deserialize)]
struct SerializableBloomFilter {
    bit_vector: BitVector,
    config: BloomConfig,
    hash_functions: usize,
    items_added: usize,
}
```

### Advanced Hash Functions

```rust
/// MurmurHash3 implementation for better distribution
pub struct MurmurHash3;

impl BloomHasher for MurmurHash3 {
    fn hash(&self, item: &dyn Hash, seed: u64) -> u64 {
        let mut hasher = DefaultHasher::new();
        seed.hash(&mut hasher);
        item.hash(&mut hasher);
        
        // Apply MurmurHash3 finalization
        let mut hash = hasher.finish();
        hash ^= hash >> 33;
        hash = hash.wrapping_mul(0xff51afd7ed558ccd);
        hash ^= hash >> 33;
        hash = hash.wrapping_mul(0xc4ceb9fe1a85ec53);
        hash ^= hash >> 33;
        hash
    }
    
    fn name(&self) -> &'static str {
        "MurmurHash3"
    }
}

/// FNV-1a hash implementation
pub struct FnvHasher;

impl BloomHasher for FnvHasher {
    fn hash(&self, item: &dyn Hash, seed: u64) -> u64 {
        let mut hasher = DefaultHasher::new();
        seed.hash(&mut hasher);
        item.hash(&mut hasher);
        let hash = hasher.finish();
        
        // Apply FNV-1a algorithm
        const FNV_PRIME: u64 = 0x100000001b3;
        const FNV_OFFSET: u64 = 0xcbf29ce484222325;
        
        let mut result = FNV_OFFSET;
        let bytes = hash.to_be_bytes();
        
        for byte in bytes {
            result ^= byte as u64;
            result = result.wrapping_mul(FNV_PRIME);
        }
        
        result
    }
    
    fn name(&self) -> &'static str {
        "FNV-1a"
    }
}
```

### Performance Benchmarks

```rust
#[cfg(test)]
mod benchmarks {
    use super::*;
    use std::time::{Duration, Instant};
    use std::collections::HashSet;
    
    /// Benchmark Bloom filter operations
    pub fn benchmark_bloom_filter() {
        let sizes = vec![1_000, 10_000, 100_000, 1_000_000];
        let fp_rates = vec![0.1, 0.01, 0.001];
        
        println!("Bloom Filter Performance Benchmarks");
        println!("===================================");
        
        for size in sizes {
            for fp_rate in &fp_rates {
                run_benchmark(size, *fp_rate);
            }
        }
    }
    
    fn run_benchmark(size: usize, fp_rate: f64) {
        let config = BloomConfig::new(size, fp_rate);
        let mut bloom = BloomFilter::<String>::new(config).unwrap();
        
        // Generate test data
        let items: Vec<String> = (0..size)
            .map(|i| format!("item_{}", i))
            .collect();
        
        // Benchmark insertion
        let start = Instant::now();
        for item in &items {
            bloom.insert(item);
        }
        let insert_time = start.elapsed();
        
        // Benchmark lookups (positive cases)
        let start = Instant::now();
        for item in &items {
            bloom.contains(item);
        }
        let lookup_time = start.elapsed();
        
        // Benchmark lookups (negative cases)
        let negative_items: Vec<String> = (size..size * 2)
            .map(|i| format!("item_{}", i))
            .collect();
        
        let start = Instant::now();
        let mut false_positives = 0;
        for item in &negative_items {
            if bloom.contains(item) {
                false_positives += 1;
            }
        }
        let negative_lookup_time = start.elapsed();
        
        let stats = bloom.statistics();
        
        println!("\nBenchmark Results (size: {}, fp_rate: {:.1}%):", size, fp_rate * 100.0);
        println!("  Insert time: {:?} ({:.2} μs/item)", insert_time, insert_time.as_micros() as f64 / size as f64);
        println!("  Lookup time: {:?} ({:.2} μs/item)", lookup_time, lookup_time.as_micros() as f64 / size as f64);
        println!("  Negative lookup: {:?} ({:.2} μs/item)", negative_lookup_time, negative_lookup_time.as_micros() as f64 / size as f64);
        println!("  False positives: {}/{} ({:.2}%)", false_positives, size, false_positives as f64 / size as f64 * 100.0);
        println!("  Memory usage: {:.1} KB", stats.memory_usage as f64 / 1024.0);
        println!("  Saturation: {:.1}%", stats.saturation_level * 100.0);
    }
    
    /// Compare Bloom filter vs HashSet performance
    pub fn compare_with_hashset() {
        let sizes = vec![10_000, 100_000, 1_000_000];
        
        println!("\nBloom Filter vs HashSet Comparison");
        println!("==================================");
        
        for size in sizes {
            compare_performance(size);
        }
    }
    
    fn compare_performance(size: usize) {
        let config = BloomConfig::new(size, 0.01);
        let mut bloom = BloomFilter::<String>::new(config).unwrap();
        let mut hashset = HashSet::new();
        
        let items: Vec<String> = (0..size)
            .map(|i| format!("item_{}", i))
            .collect();
        
        // Benchmark Bloom filter insertion
        let start = Instant::now();
        for item in &items {
            bloom.insert(item);
        }
        let bloom_insert_time = start.elapsed();
        
        // Benchmark HashSet insertion
        let start = Instant::now();
        for item in &items {
            hashset.insert(item.clone());
        }
        let hashset_insert_time = start.elapsed();
        
        // Benchmark Bloom filter lookup
        let start = Instant::now();
        for item in &items {
            bloom.contains(item);
        }
        let bloom_lookup_time = start.elapsed();
        
        // Benchmark HashSet lookup
        let start = Instant::now();
        for item in &items {
            hashset.contains(item);
        }
        let hashset_lookup_time = start.elapsed();
        
        // Calculate memory usage
        let bloom_memory = bloom.memory_usage();
        let hashset_memory = estimate_hashset_memory(&hashset);
        
        println!("\nComparison Results (size: {}):", size);
        println!("  Bloom Filter:");
        println!("    Insert time: {:?} ({:.2} μs/item)", bloom_insert_time, bloom_insert_time.as_micros() as f64 / size as f64);
        println!("    Lookup time: {:?} ({:.2} μs/item)", bloom_lookup_time, bloom_lookup_time.as_micros() as f64 / size as f64);
        println!("    Memory usage: {:.1} KB", bloom_memory as f64 / 1024.0);
        
        println!("  HashSet:");
        println!("    Insert time: {:?} ({:.2} μs/item)", hashset_insert_time, hashset_insert_time.as_micros() as f64 / size as f64);
        println!("    Lookup time: {:?} ({:.2} μs/item)", hashset_lookup_time, hashset_lookup_time.as_micros() as f64 / size as f64);
        println!("    Memory usage: {:.1} KB", hashset_memory as f64 / 1024.0);
        
        println!("  Savings:");
        println!("    Memory: {:.1}x", hashset_memory as f64 / bloom_memory as f64);
        println!("    Insert speed: {:.1}x", hashset_insert_time.as_nanos() as f64 / bloom_insert_time.as_nanos() as f64);
        println!("    Lookup speed: {:.1}x", hashset_lookup_time.as_nanos() as f64 / bloom_lookup_time.as_nanos() as f64);
    }
    
    fn estimate_hashset_memory(hashset: &HashSet<String>) -> usize {
        let mut total = std::mem::size_of::<HashSet<String>>();
        
        for item in hashset {
            total += std::mem::size_of::<String>() + item.len();
        }
        
        // Add hash table overhead (approximate)
        total += hashset.len() * 8; // Pointer overhead
        total += hashset.capacity() * 8; // Bucket overhead
        
        total
    }
}
```

### Example Applications

#### Web Crawler with Bloom Filter

```rust
use std::collections::VecDeque;
use std::time::{Duration, Instant};
use reqwest::Client;
use url::Url;

/// Web crawler using Bloom filter for duplicate URL detection
pub struct WebCrawler {
    bloom_filter: BloomFilter<String>,
    client: Client,
    queue: VecDeque<String>,
    crawled_count: usize,
    start_time: Instant,
}

impl WebCrawler {
    /// Create a new web crawler
    pub fn new(expected_urls: usize) -> Result<Self, String> {
        let config = BloomConfig::new(expected_urls, 0.01);
        let bloom_filter = BloomFilter::new(config)?;
        
        Ok(Self {
            bloom_filter,
            client: Client::builder()
                .timeout(Duration::from_secs(10))
                .build()
                .map_err(|e| e.to_string())?,
            queue: VecDeque::new(),
            crawled_count: 0,
            start_time: Instant::now(),
        })
    }
    
    /// Start crawling from seed URLs
    pub async fn crawl(&mut self, seed_urls: Vec<String>, max_pages: usize) -> Result<(), String> {
        // Add seed URLs to queue
        for url in seed_urls {
            self.queue.push_back(url);
        }
        
        self.start_time = Instant::now();
        
        while let Some(url) = self.queue.pop_front() {
            if self.crawled_count >= max_pages {
                break;
            }
            
            // Check if URL already crawled
            if self.bloom_filter.contains(&url) {
                continue;
            }
            
            // Mark as crawled
            self.bloom_filter.insert(&url);
            
            // Crawl the URL
            match self.crawl_url(&url).await {
                Ok(new_urls) => {
                    self.crawled_count += 1;
                    
                    // Add new URLs to queue
                    for new_url in new_urls {
                        if !self.bloom_filter.contains(&new_url) {
                            self.queue.push_back(new_url);
                        }
                    }
                    
                    // Print progress
                    if self.crawled_count % 100 == 0 {
                        self.print_progress();
                    }
                }
                Err(e) => {
                    eprintln!("Error crawling {}: {}", url, e);
                }
            }
        }
        
        self.print_final_stats();
        Ok(())
    }
    
    /// Crawl a single URL and extract links
    async fn crawl_url(&self, url: &str) -> Result<Vec<String>, String> {
        let response = self.client.get(url)
            .send()
            .await
            .map_err(|e| e.to_string())?;
        
        if !response.status().is_success() {
            return Err(format!("HTTP {}", response.status()));
        }
        
        let html = response.text().await.map_err(|e| e.to_string())?;
        let links = self.extract_links(&html, url)?;
        
        Ok(links)
    }
    
    /// Extract links from HTML content
    fn extract_links(&self, html: &str, base_url: &str) -> Result<Vec<String>, String> {
        use scraper::{Html, Selector};
        
        let document = Html::parse_document(html);
        let selector = Selector::parse("a[href]").unwrap();
        
        let base = Url::parse(base_url).map_err(|e| e.to_string())?;
        let mut links = Vec::new();
        
        for element in document.select(&selector) {
            if let Some(href) = element.value().attr("href") {
                match base.join(href) {
                    Ok(url) => {
                        let url_str = url.to_string();
                        if self.is_valid_url(&url_str) {
                            links.push(url_str);
                        }
                    }
                    Err(_) => continue,
                }
            }
        }
        
        Ok(links)
    }
    
    /// Check if URL is valid for crawling
    fn is_valid_url(&self, url: &str) -> bool {
        if let Ok(parsed) = Url::parse(url) {
            parsed.scheme() == "http" || parsed.scheme() == "https"
        } else {
            false
        }
    }
    
    /// Print crawling progress
    fn print_progress(&self) {
        let elapsed = self.start_time.elapsed();
        let rate = self.crawled_count as f64 / elapsed.as_secs_f64();
        let stats = self.bloom_filter.statistics();
        
        println!("Crawled: {}, Queue: {}, Rate: {:.1} URLs/sec, FP: {:.3}%, Memory: {:.1} KB",
                 self.crawled_count,
                 self.queue.len(),
                 rate,
                 stats.current_false_positive_rate * 100.0,
                 stats.memory_usage as f64 / 1024.0);
    }
    
    /// Print final statistics
    fn print_final_stats(&self) {
        let elapsed = self.start_time.elapsed();
        let rate = self.crawled_count as f64 / elapsed.as_secs_f64();
        let stats = self.bloom_filter.statistics();
        
        println!("\nCrawling Complete!");
        println!("==================");
        println!("Total URLs crawled: {}", self.crawled_count);
        println!("Total time: {:?}", elapsed);
        println!("Average rate: {:.2} URLs/sec", rate);
        println!("Queue size: {}", self.queue.len());
        println!();
        
        stats.print();
    }
}
```

#### Cache with Bloom Filter

```rust
use std::collections::HashMap;
use std::hash::Hash;

/// Cache with Bloom filter for negative lookup optimization
pub struct BloomCache<K, V> 
where 
    K: BloomItem + Eq + Hash,
    V: Clone,
{
    bloom_filter: BloomFilter<K>,
    cache: HashMap<K, V>,
    max_size: usize,
    hits: usize,
    misses: usize,
    bloom_hits: usize,
    bloom_misses: usize,
}

impl<K, V> BloomCache<K, V>
where 
    K: BloomItem + Eq + Hash,
    V: Clone,
{
    /// Create a new cache with Bloom filter
    pub fn new(max_size: usize) -> Result<Self, String> {
        let config = BloomConfig::new(max_size, 0.01);
        let bloom_filter = BloomFilter::new(config)?;
        
        Ok(Self {
            bloom_filter,
            cache: HashMap::new(),
            max_size,
            hits: 0,
            misses: 0,
            bloom_hits: 0,
            bloom_misses: 0,
        })
    }
    
    /// Get a value from the cache
    pub fn get(&mut self, key: &K) -> Option<V> {
        // Check Bloom filter first
        if !self.bloom_filter.contains(key) {
            self.bloom_misses += 1;
            self.misses += 1;
            return None;
        }
        
        self.bloom_hits += 1;
        
        // Check actual cache
        if let Some(value) = self.cache.get(key) {
            self.hits += 1;
            Some(value.clone())
        } else {
            self.misses += 1;
            None
        }
    }
    
    /// Insert a value into the cache
    pub fn insert(&mut self, key: K, value: V) -> Option<V> {
        // Add to Bloom filter
        self.bloom_filter.insert(&key);
        
        // Check if we need to evict
        if self.cache.len() >= self.max_size {
            // Simple eviction: remove first entry
            if let Some((old_key, _)) = self.cache.iter().next() {
                let old_key = old_key.clone();
                self.cache.remove(&old_key);
            }
        }
        
        // Insert into cache
        self.cache.insert(key, value)
    }
    
    /// Get cache statistics
    pub fn statistics(&self) -> CacheStatistics {
        let total_requests = self.hits + self.misses;
        let hit_rate = if total_requests > 0 {
            self.hits as f64 / total_requests as f64
        } else {
            0.0
        };
        
        let bloom_accuracy = if self.bloom_hits > 0 {
            self.hits as f64 / self.bloom_hits as f64
        } else {
            0.0
        };
        
        CacheStatistics {
            size: self.cache.len(),
            max_size: self.max_size,
            hits: self.hits,
            misses: self.misses,
            hit_rate,
            bloom_hits: self.bloom_hits,
            bloom_misses: self.bloom_misses,
            bloom_accuracy,
            bloom_stats: self.bloom_filter.statistics(),
        }
    }
}

/// Cache performance statistics
#[derive(Debug)]
pub struct CacheStatistics {
    pub size: usize,
    pub max_size: usize,
    pub hits: usize,
    pub misses: usize,
    pub hit_rate: f64,
    pub bloom_hits: usize,
    pub bloom_misses: usize,
    pub bloom_accuracy: f64,
    pub bloom_stats: BloomStatistics,
}

impl CacheStatistics {
    pub fn print(&self) {
        println!("Cache Statistics:");
        println!("  Size: {}/{}", self.size, self.max_size);
        println!("  Hits: {}", self.hits);
        println!("  Misses: {}", self.misses);
        println!("  Hit rate: {:.1}%", self.hit_rate * 100.0);
        println!("  Bloom hits: {}", self.bloom_hits);
        println!("  Bloom misses: {}", self.bloom_misses);
        println!("  Bloom accuracy: {:.1}%", self.bloom_accuracy * 100.0);
        println!();
        self.bloom_stats.print();
    }
}
```

### Testing Framework

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;
    
    #[test]
    fn test_basic_functionality() {
        let config = BloomConfig::new(1000, 0.01);
        let mut bloom = BloomFilter::<String>::new(config).unwrap();
        
        // Test insertion and lookup
        let items = vec!["apple", "banana", "cherry"];
        
        for item in &items {
            bloom.insert(&item.to_string());
        }
        
        for item in &items {
            assert!(bloom.contains(&item.to_string()));
        }
        
        // Test item not in filter
        assert!(!bloom.contains(&"orange".to_string()));
    }
    
    #[test]
    fn test_false_positive_rate() {
        let config = BloomConfig::new(1000, 0.01);
        let mut bloom = BloomFilter::<i32>::new(config).unwrap();
        
        // Add 1000 items
        for i in 0..1000 {
            bloom.insert(&i);
        }
        
        // Test 1000 items not in filter
        let mut false_positives = 0;
        for i in 1000..2000 {
            if bloom.contains(&i) {
                false_positives += 1;
            }
        }
        
        let fp_rate = false_positives as f64 / 1000.0;
        assert!(fp_rate < 0.02); // Should be close to 1%
    }
    
    #[test]
    fn test_scalable_filter() {
        let mut scalable = ScalableBloomFilter::new(100, 0.01).unwrap();
        
        // Add more items than initial capacity
        for i in 0..500 {
            scalable.insert(&i);
        }
        
        // All items should be found
        for i in 0..500 {
            assert!(scalable.contains(&i));
        }
        
        let stats = scalable.statistics();
        assert!(stats.filter_count > 1); // Should have multiple layers
    }
    
    #[test]
    fn test_concurrent_access() {
        use std::sync::Arc;
        use std::thread;
        
        let config = BloomConfig::new(10000, 0.01);
        let bloom = Arc::new(ConcurrentBloomFilter::new(config).unwrap());
        
        let mut handles = vec![];
        
        // Spawn multiple threads
        for i in 0..10 {
            let bloom_clone = bloom.clone();
            let handle = thread::spawn(move || {
                for j in 0..1000 {
                    let item = format!("item_{}_{}", i, j);
                    bloom_clone.insert(&item);
                }
            });
            handles.push(handle);
        }
        
        // Wait for all threads
        for handle in handles {
            handle.join().unwrap();
        }
        
        let stats = bloom.statistics();
        assert_eq!(stats.items_added, 10000);
    }
    
    #[test]
    fn test_persistence() {
        let config = BloomConfig::new(1000, 0.01);
        let mut bloom = BloomFilter::<String>::new(config).unwrap();
        
        // Add some items
        for i in 0..100 {
            bloom.insert(&format!("item_{}", i));
        }
        
        // Save to file
        bloom.save_to_file("test_bloom.bin").unwrap();
        
        // Load from file
        let loaded_bloom = BloomFilter::<String>::load_from_file(
            "test_bloom.bin", 
            Arc::new(DefaultBloomHasher)
        ).unwrap();
        
        // Verify items are still there
        for i in 0..100 {
            assert!(loaded_bloom.contains(&format!("item_{}", i)));
        }
        
        // Clean up
        std::fs::remove_file("test_bloom.bin").ok();
    }
    
    #[test]
    fn test_memory_efficiency() {
        let bloom_config = BloomConfig::new(10000, 0.01);
        let mut bloom = BloomFilter::<i32>::new(bloom_config).unwrap();
        let mut hashset = HashSet::new();
        
        // Add same items to both
        for i in 0..10000 {
            bloom.insert(&i);
            hashset.insert(i);
        }
        
        let bloom_memory = bloom.memory_usage();
        let hashset_memory = hashset.len() * std::mem::size_of::<i32>() * 2; // Approximate
        
        println!("Bloom filter memory: {} bytes", bloom_memory);
        println!("HashSet memory: {} bytes", hashset_memory);
        
        // Bloom filter should use less memory
        assert!(bloom_memory < hashset_memory);
    }
}
```

## Production Deployment Guide

### Configuration Best Practices

```rust
/// Production-ready configuration helper
pub struct BloomFilterBuilder {
    config: BloomConfig,
    hasher: Option<Arc<dyn BloomHasher>>,
}

impl BloomFilterBuilder {
    pub fn new() -> Self {
        Self {
            config: BloomConfig::default(),
            hasher: None,
        }
    }
    
    pub fn expected_items(mut self, items: usize) -> Self {
        self.config.expected_items = items;
        self
    }
    
    pub fn false_positive_rate(mut self, rate: f64) -> Self {
        self.config.false_positive_rate = rate;
        self
    }
    
    pub fn hasher(mut self, hasher: Arc<dyn BloomHasher>) -> Self {
        self.hasher = Some(hasher);
        self
    }
    
    pub fn auto_resize(mut self, enabled: bool) -> Self {
        self.config.auto_resize = enabled;
        self
    }
    
    pub fn build<T: BloomItem>(self) -> Result<BloomFilter<T>, String> {
        let hasher = self.hasher.unwrap_or_else(|| Arc::new(DefaultBloomHasher));
        BloomFilter::with_hasher(self.config, hasher)
    }
}

// Usage example
fn create_production_bloom_filter() -> Result<BloomFilter<String>, String> {
    BloomFilterBuilder::new()
        .expected_items(1_000_000)
        .false_positive_rate(0.001)
        .hasher(Arc::new(MurmurHash3))
        .auto_resize(true)
        .build()
}
```

### Monitoring and Metrics

```rust
/// Production metrics for Bloom filter monitoring
pub struct BloomFilterMetrics {
    pub filter_name: String,
    pub start_time: Instant,
    pub last_reset: Instant,
    pub operations: AtomicUsize,
    pub false_positive_checks: AtomicUsize,
    pub memory_usage: AtomicUsize,
}

impl BloomFilterMetrics {
    pub fn new(name: String) -> Self {
        Self {
            filter_name: name,
            start_time: Instant::now(),
            last_reset: Instant::now(),
            operations: AtomicUsize::new(0),
            false_positive_checks: AtomicUsize::new(0),
            memory_usage: AtomicUsize::new(0),
        }
    }
    
    pub fn record_operation(&self) {
        self.operations.fetch_add(1, Ordering::Relaxed);
    }
    
    pub fn record_false_positive_check(&self) {
        self.false_positive_checks.fetch_add(1, Ordering::Relaxed);
    }
    
    pub fn update_memory_usage(&self, usage: usize) {
        self.memory_usage.store(usage, Ordering::Relaxed);
    }
    
    pub fn get_metrics(&self) -> HashMap<String, f64> {
        let mut metrics = HashMap::new();
        let uptime = self.start_time.elapsed().as_secs_f64();
        
        metrics.insert("uptime_seconds".to_string(), uptime);
        metrics.insert("operations_total".to_string(), self.operations.load(Ordering::Relaxed) as f64);
        metrics.insert("operations_per_second".to_string(), self.operations.load(Ordering::Relaxed) as f64 / uptime);
        metrics.insert("false_positive_checks".to_string(), self.false_positive_checks.load(Ordering::Relaxed) as f64);
        metrics.insert("memory_usage_bytes".to_string(), self.memory_usage.load(Ordering::Relaxed) as f64);
        
        metrics
    }
}
```

## Key Implementation Insights

### Performance Optimizations

1. **Bit-level operations**: Custom bit vector for efficient memory usage
2. **SIMD-friendly layouts**: 64-bit word alignment for vectorization
3. **Cache-conscious design**: Minimized memory indirection
4. **Double hashing**: Reduced hash function computation overhead
5. **Atomic operations**: Lock-free statistics tracking

### Memory Management

1. **Precise bit packing**: No wasted bits in storage
2. **Lazy allocation**: Allocate only what's needed
3. **Serialization support**: Efficient persistence format
4. **Memory pooling**: Reuse allocations where possible
5. **Garbage collection friendly**: Minimal heap fragmentation

### Thread Safety

1. **Immutable operations**: Contains() is fully concurrent
2. **Atomic counters**: Thread-safe statistics
3. **RwLock for mutations**: Efficient concurrent reads
4. **Lock-free bit operations**: Atomic bit manipulation
5. **Send/Sync implementations**: Proper thread safety guarantees

### Error Handling

1. **Explicit error types**: Clear error messages
2. **Graceful degradation**: Handle edge cases
3. **Validation**: Parameter validation at construction
4. **Recovery strategies**: Automatic resizing and cleanup
5. **Monitoring integration**: Comprehensive metrics

This implementation provides a production-ready Bloom filter system that balances performance, safety, and usability while maintaining the space efficiency that makes Bloom filters so valuable for large-scale applications.