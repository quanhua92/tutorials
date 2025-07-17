# Rust Implementation: Building Production-Ready Ring Buffers

Let's build a comprehensive, production-ready ring buffer library in Rust that demonstrates all the concepts we've explored. This implementation will include both lock-based and lock-free variants, extensive testing, and real-world usage examples.

## Project Setup

Create a new Rust project:

```bash
cargo new ring_buffer_lib
cd ring_buffer_lib
```

Add dependencies to `Cargo.toml`:

```toml
[dependencies]
crossbeam = "0.8"
criterion = "0.5"

[dev-dependencies]
tokio = { version = "1.0", features = ["full"] }
rayon = "1.7"

[[bench]]
name = "ring_buffer_bench"
harness = false
```

## Core Traits and Types

Let's start with the fundamental abstractions:

```rust
// src/lib.rs
use std::fmt::Debug;

/// Errors that can occur during ring buffer operations
#[derive(Debug, Clone, PartialEq)]
pub enum RingBufferError {
    BufferFull,
    BufferEmpty,
    InvalidCapacity,
}

/// Result type for ring buffer operations
pub type RingBufferResult<T> = Result<T, RingBufferError>;

/// Common trait for all ring buffer implementations
pub trait RingBuffer<T> {
    /// Create a new ring buffer with the specified capacity
    fn new(capacity: usize) -> Self;
    
    /// Attempt to write an item to the buffer
    fn try_write(&self, item: T) -> RingBufferResult<()>;
    
    /// Attempt to read an item from the buffer
    fn try_read(&self) -> RingBufferResult<T>;
    
    /// Check if the buffer is empty
    fn is_empty(&self) -> bool;
    
    /// Check if the buffer is full
    fn is_full(&self) -> bool;
    
    /// Get the current number of items in the buffer
    fn len(&self) -> usize;
    
    /// Get the capacity of the buffer
    fn capacity(&self) -> usize;
}

/// Statistics about ring buffer performance
#[derive(Debug, Clone)]
pub struct BufferStats {
    pub total_writes: u64,
    pub total_reads: u64,
    pub write_failures: u64,
    pub read_failures: u64,
    pub current_size: usize,
    pub capacity: usize,
}

pub mod basic;
pub mod spsc;
pub mod mpsc;
pub mod benchmarks;

pub use basic::BasicRingBuffer;
pub use spsc::SPSCRingBuffer;
pub use mpsc::MPSCRingBuffer;
```

## Basic Ring Buffer Implementation

Let's start with a simple, lock-based implementation:

```rust
// src/basic.rs
use crate::{RingBuffer, RingBufferError, RingBufferResult, BufferStats};
use std::sync::{Mutex, MutexGuard};

/// A basic ring buffer using mutex for thread safety
pub struct BasicRingBuffer<T> {
    data: Mutex<BasicRingBufferData<T>>,
}

struct BasicRingBufferData<T> {
    buffer: Vec<Option<T>>,
    capacity: usize,
    head: usize,      // Next write position
    tail: usize,      // Next read position  
    count: usize,     // Current number of items
    stats: BufferStats,
}

impl<T> BasicRingBuffer<T> {
    fn with_data<F, R>(&self, f: F) -> R
    where
        F: FnOnce(&mut BasicRingBufferData<T>) -> R,
    {
        let mut data = self.data.lock().unwrap();
        f(&mut *data)
    }
    
    /// Write an item, overwriting the oldest if buffer is full
    pub fn write_overwrite(&self, item: T) {
        self.with_data(|data| {
            if data.count == data.capacity {
                // Buffer full, advance tail to overwrite oldest
                data.tail = (data.tail + 1) % data.capacity;
            } else {
                data.count += 1;
            }
            
            data.buffer[data.head] = Some(item);
            data.head = (data.head + 1) % data.capacity;
            data.stats.total_writes += 1;
        });
    }
    
    /// Peek at the next item without removing it
    pub fn peek(&self) -> RingBufferResult<T>
    where
        T: Clone,
    {
        self.with_data(|data| {
            if data.count == 0 {
                Err(RingBufferError::BufferEmpty)
            } else {
                Ok(data.buffer[data.tail].as_ref().unwrap().clone())
            }
        })
    }
    
    /// Clear all items from the buffer
    pub fn clear(&self) {
        self.with_data(|data| {
            data.head = 0;
            data.tail = 0;
            data.count = 0;
            for slot in &mut data.buffer {
                *slot = None;
            }
        });
    }
    
    /// Get current statistics
    pub fn stats(&self) -> BufferStats {
        self.with_data(|data| data.stats.clone())
    }
    
    /// Get all items as a vector (for debugging)
    pub fn to_vec(&self) -> Vec<T>
    where
        T: Clone,
    {
        self.with_data(|data| {
            let mut result = Vec::new();
            let mut pos = data.tail;
            
            for _ in 0..data.count {
                if let Some(ref item) = data.buffer[pos] {
                    result.push(item.clone());
                }
                pos = (pos + 1) % data.capacity;
            }
            
            result
        })
    }
}

impl<T> RingBuffer<T> for BasicRingBuffer<T> {
    fn new(capacity: usize) -> Self {
        if capacity == 0 {
            panic!("Capacity must be greater than 0");
        }
        
        Self {
            data: Mutex::new(BasicRingBufferData {
                buffer: vec![None; capacity],
                capacity,
                head: 0,
                tail: 0,
                count: 0,
                stats: BufferStats {
                    total_writes: 0,
                    total_reads: 0,
                    write_failures: 0,
                    read_failures: 0,
                    current_size: 0,
                    capacity,
                },
            }),
        }
    }
    
    fn try_write(&self, item: T) -> RingBufferResult<()> {
        self.with_data(|data| {
            if data.count == data.capacity {
                data.stats.write_failures += 1;
                Err(RingBufferError::BufferFull)
            } else {
                data.buffer[data.head] = Some(item);
                data.head = (data.head + 1) % data.capacity;
                data.count += 1;
                data.stats.total_writes += 1;
                data.stats.current_size = data.count;
                Ok(())
            }
        })
    }
    
    fn try_read(&self) -> RingBufferResult<T> {
        self.with_data(|data| {
            if data.count == 0 {
                data.stats.read_failures += 1;
                Err(RingBufferError::BufferEmpty)
            } else {
                let item = data.buffer[data.tail].take().unwrap();
                data.tail = (data.tail + 1) % data.capacity;
                data.count -= 1;
                data.stats.total_reads += 1;
                data.stats.current_size = data.count;
                Ok(item)
            }
        })
    }
    
    fn is_empty(&self) -> bool {
        self.with_data(|data| data.count == 0)
    }
    
    fn is_full(&self) -> bool {
        self.with_data(|data| data.count == data.capacity)
    }
    
    fn len(&self) -> usize {
        self.with_data(|data| data.count)
    }
    
    fn capacity(&self) -> usize {
        self.with_data(|data| data.capacity)
    }
}

unsafe impl<T: Send> Send for BasicRingBuffer<T> {}
unsafe impl<T: Send> Sync for BasicRingBuffer<T> {}
```

## Single Producer Single Consumer (SPSC) Implementation

Now let's implement a high-performance lock-free SPSC ring buffer:

```rust
// src/spsc.rs
use crate::{RingBuffer, RingBufferError, RingBufferResult};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::cell::UnsafeCell;
use std::marker::PhantomData;

/// A lock-free single-producer single-consumer ring buffer
pub struct SPSCRingBuffer<T> {
    buffer: Vec<UnsafeCell<T>>,
    capacity: usize,
    mask: usize,  // capacity - 1 (requires power-of-2 capacity)
    head: AtomicUsize,  // Modified only by producer
    tail: AtomicUsize,  // Modified only by consumer
    _phantom: PhantomData<T>,
}

impl<T> SPSCRingBuffer<T> {
    /// Create a new SPSC ring buffer with power-of-2 capacity
    pub fn with_capacity(capacity: usize) -> Self {
        if !capacity.is_power_of_two() || capacity == 0 {
            panic!("Capacity must be a power of 2 and greater than 0");
        }
        
        let mut buffer = Vec::with_capacity(capacity);
        for _ in 0..capacity {
            buffer.push(UnsafeCell::new(unsafe { std::mem::zeroed() }));
        }
        
        Self {
            buffer,
            capacity,
            mask: capacity - 1,
            head: AtomicUsize::new(0),
            tail: AtomicUsize::new(0),
            _phantom: PhantomData,
        }
    }
    
    /// Producer interface - safe to call from only one thread
    pub struct Producer<'a, T> {
        ring_buffer: &'a SPSCRingBuffer<T>,
    }
    
    /// Consumer interface - safe to call from only one thread
    pub struct Consumer<'a, T> {
        ring_buffer: &'a SPSCRingBuffer<T>,
    }
    
    /// Split the ring buffer into producer and consumer interfaces
    pub fn split(&self) -> (Producer<T>, Consumer<T>) {
        (
            Producer { ring_buffer: self },
            Consumer { ring_buffer: self },
        )
    }
}

impl<T> Producer<'_, T> {
    /// Try to write an item (non-blocking)
    pub fn try_write(&self, item: T) -> RingBufferResult<()> {
        let head = self.ring_buffer.head.load(Ordering::Relaxed);
        let next_head = head.wrapping_add(1);
        
        // Check if buffer is full
        let tail = self.ring_buffer.tail.load(Ordering::Acquire);
        if (next_head & self.ring_buffer.mask) == (tail & self.ring_buffer.mask) {
            return Err(RingBufferError::BufferFull);
        }
        
        // Safe: Only producer writes to head positions
        unsafe {
            std::ptr::write(
                self.ring_buffer.buffer[head & self.ring_buffer.mask].get(),
                item
            );
        }
        
        // Publish the write
        self.ring_buffer.head.store(next_head, Ordering::Release);
        Ok(())
    }
    
    /// Write an item, spinning until space is available
    pub fn write(&self, item: T) {
        while self.try_write(item).is_err() {
            std::hint::spin_loop();
        }
    }
    
    /// Check if buffer is full from producer perspective
    pub fn is_full(&self) -> bool {
        let head = self.ring_buffer.head.load(Ordering::Relaxed);
        let tail = self.ring_buffer.tail.load(Ordering::Acquire);
        (head.wrapping_add(1) & self.ring_buffer.mask) == (tail & self.ring_buffer.mask)
    }
}

impl<T> Consumer<'_, T> {
    /// Try to read an item (non-blocking)
    pub fn try_read(&self) -> RingBufferResult<T> {
        let tail = self.ring_buffer.tail.load(Ordering::Relaxed);
        
        // Check if buffer is empty
        let head = self.ring_buffer.head.load(Ordering::Acquire);
        if (tail & self.ring_buffer.mask) == (head & self.ring_buffer.mask) {
            return Err(RingBufferError::BufferEmpty);
        }
        
        // Safe: Only consumer reads from tail positions
        let item = unsafe {
            std::ptr::read(self.ring_buffer.buffer[tail & self.ring_buffer.mask].get())
        };
        
        let next_tail = tail.wrapping_add(1);
        self.ring_buffer.tail.store(next_tail, Ordering::Release);
        
        Ok(item)
    }
    
    /// Read an item, spinning until one is available
    pub fn read(&self) -> T {
        loop {
            if let Ok(item) = self.try_read() {
                return item;
            }
            std::hint::spin_loop();
        }
    }
    
    /// Check if buffer is empty from consumer perspective
    pub fn is_empty(&self) -> bool {
        let tail = self.ring_buffer.tail.load(Ordering::Relaxed);
        let head = self.ring_buffer.head.load(Ordering::Acquire);
        (tail & self.ring_buffer.mask) == (head & self.ring_buffer.mask)
    }
}

impl<T: Default> RingBuffer<T> for SPSCRingBuffer<T> {
    fn new(capacity: usize) -> Self {
        Self::with_capacity(capacity)
    }
    
    fn try_write(&self, item: T) -> RingBufferResult<()> {
        let (producer, _) = self.split();
        producer.try_write(item)
    }
    
    fn try_read(&self) -> RingBufferResult<T> {
        let (_, consumer) = self.split();
        consumer.try_read()
    }
    
    fn is_empty(&self) -> bool {
        let tail = self.tail.load(Ordering::Relaxed);
        let head = self.head.load(Ordering::Acquire);
        (tail & self.mask) == (head & self.mask)
    }
    
    fn is_full(&self) -> bool {
        let head = self.head.load(Ordering::Relaxed);
        let tail = self.tail.load(Ordering::Acquire);
        (head.wrapping_add(1) & self.mask) == (tail & self.mask)
    }
    
    fn len(&self) -> usize {
        let head = self.head.load(Ordering::Acquire);
        let tail = self.tail.load(Ordering::Acquire);
        (head.wrapping_sub(tail)) & self.mask
    }
    
    fn capacity(&self) -> usize {
        self.capacity
    }
}

// Safety: SPSC ring buffer is safe to send between threads
// Each end (producer/consumer) is used by only one thread
unsafe impl<T: Send> Send for SPSCRingBuffer<T> {}
unsafe impl<T: Send> Sync for SPSCRingBuffer<T> {}
```

## Multiple Producer Single Consumer (MPSC) Implementation

Let's implement an MPSC ring buffer that allows multiple producers:

```rust
// src/mpsc.rs
use crate::{RingBuffer, RingBufferError, RingBufferResult};
use std::sync::atomic::{AtomicUsize, AtomicU64, Ordering};
use std::cell::UnsafeCell;
use std::marker::PhantomData;

/// A lock-free multiple-producer single-consumer ring buffer
pub struct MPSCRingBuffer<T> {
    buffer: Vec<UnsafeCell<T>>,
    capacity: usize,
    mask: usize,
    head: AtomicU64,     // Packed: generation (upper 32) + position (lower 32)
    tail: AtomicUsize,   // Modified only by consumer
    _phantom: PhantomData<T>,
}

impl<T> MPSCRingBuffer<T> {
    pub fn with_capacity(capacity: usize) -> Self {
        if !capacity.is_power_of_two() || capacity == 0 || capacity > u32::MAX as usize {
            panic!("Capacity must be a power of 2, greater than 0, and fit in u32");
        }
        
        let mut buffer = Vec::with_capacity(capacity);
        for _ in 0..capacity {
            buffer.push(UnsafeCell::new(unsafe { std::mem::zeroed() }));
        }
        
        Self {
            buffer,
            capacity,
            mask: capacity - 1,
            head: AtomicU64::new(0),
            tail: AtomicUsize::new(0),
            _phantom: PhantomData,
        }
    }
    
    fn pack_head(position: usize, generation: u32) -> u64 {
        ((generation as u64) << 32) | (position as u64 & 0xFFFFFFFF)
    }
    
    fn unpack_head(packed: u64) -> (usize, u32) {
        let position = (packed & 0xFFFFFFFF) as usize;
        let generation = (packed >> 32) as u32;
        (position, generation)
    }
    
    /// Producer interface for MPSC - can be cloned and used from multiple threads
    #[derive(Clone)]
    pub struct Producer<T> {
        ring_buffer: std::sync::Arc<MPSCRingBuffer<T>>,
    }
    
    /// Consumer interface for MPSC - must be used from only one thread
    pub struct Consumer<T> {
        ring_buffer: std::sync::Arc<MPSCRingBuffer<T>>,
    }
    
    /// Create producer and consumer interfaces
    pub fn into_split(self) -> (Producer<T>, Consumer<T>) {
        let arc = std::sync::Arc::new(self);
        (
            Producer { ring_buffer: arc.clone() },
            Consumer { ring_buffer: arc },
        )
    }
}

impl<T> Producer<T> {
    /// Try to write an item from any producer thread
    pub fn try_write(&self, item: T) -> RingBufferResult<()> {
        const MAX_RETRIES: usize = 100;
        let mut retries = 0;
        
        loop {
            let head_packed = self.ring_buffer.head.load(Ordering::Relaxed);
            let (head_pos, head_gen) = MPSCRingBuffer::<T>::unpack_head(head_packed);
            
            let next_pos = head_pos.wrapping_add(1);
            let next_gen = if (next_pos & self.ring_buffer.mask) == 0 {
                head_gen.wrapping_add(1)
            } else {
                head_gen
            };
            let next_head_packed = MPSCRingBuffer::<T>::pack_head(next_pos, next_gen);
            
            // Check if buffer is full
            let tail = self.ring_buffer.tail.load(Ordering::Acquire);
            if (next_pos & self.ring_buffer.mask) == (tail & self.ring_buffer.mask) {
                return Err(RingBufferError::BufferFull);
            }
            
            // Try to claim this position
            match self.ring_buffer.head.compare_exchange_weak(
                head_packed,
                next_head_packed,
                Ordering::Release,
                Ordering::Relaxed,
            ) {
                Ok(_) => {
                    // Successfully claimed position, write the data
                    unsafe {
                        std::ptr::write(
                            self.ring_buffer.buffer[head_pos & self.ring_buffer.mask].get(),
                            item
                        );
                    }
                    return Ok(());
                }
                Err(_) => {
                    // Another thread beat us, retry
                    retries += 1;
                    if retries >= MAX_RETRIES {
                        // Avoid infinite spinning under extreme contention
                        std::thread::yield_now();
                        retries = 0;
                    }
                    continue;
                }
            }
        }
    }
    
    /// Write an item, blocking until successful
    pub fn write(&self, item: T) {
        while let Err(RingBufferError::BufferFull) = self.try_write(item) {
            std::hint::spin_loop();
        }
    }
    
    /// Check if buffer appears full (may race with consumer)
    pub fn is_full(&self) -> bool {
        let head_packed = self.ring_buffer.head.load(Ordering::Relaxed);
        let (head_pos, _) = MPSCRingBuffer::<T>::unpack_head(head_packed);
        let tail = self.ring_buffer.tail.load(Ordering::Acquire);
        (head_pos.wrapping_add(1) & self.ring_buffer.mask) == (tail & self.ring_buffer.mask)
    }
}

impl<T> Consumer<T> {
    /// Try to read an item from the single consumer thread
    pub fn try_read(&self) -> RingBufferResult<T> {
        let tail = self.ring_buffer.tail.load(Ordering::Relaxed);
        
        // Check if buffer is empty
        let head_packed = self.ring_buffer.head.load(Ordering::Acquire);
        let (head_pos, _) = MPSCRingBuffer::<T>::unpack_head(head_packed);
        
        if (tail & self.ring_buffer.mask) == (head_pos & self.ring_buffer.mask) {
            return Err(RingBufferError::BufferEmpty);
        }
        
        // Safe: Only consumer reads from tail positions
        let item = unsafe {
            std::ptr::read(self.ring_buffer.buffer[tail & self.ring_buffer.mask].get())
        };
        
        let next_tail = tail.wrapping_add(1);
        self.ring_buffer.tail.store(next_tail, Ordering::Release);
        
        Ok(item)
    }
    
    /// Read an item, blocking until available
    pub fn read(&self) -> T {
        loop {
            if let Ok(item) = self.try_read() {
                return item;
            }
            std::hint::spin_loop();
        }
    }
    
    /// Check if buffer is empty
    pub fn is_empty(&self) -> bool {
        let tail = self.ring_buffer.tail.load(Ordering::Relaxed);
        let head_packed = self.ring_buffer.head.load(Ordering::Acquire);
        let (head_pos, _) = MPSCRingBuffer::<T>::unpack_head(head_packed);
        (tail & self.ring_buffer.mask) == (head_pos & self.ring_buffer.mask)
    }
}

impl<T: Default> RingBuffer<T> for MPSCRingBuffer<T> {
    fn new(capacity: usize) -> Self {
        Self::with_capacity(capacity)
    }
    
    fn try_write(&self, item: T) -> RingBufferResult<()> {
        // For trait compatibility - in practice use the split interfaces
        let (producer, _) = self.clone().into_split();
        producer.try_write(item)
    }
    
    fn try_read(&self) -> RingBufferResult<T> {
        // For trait compatibility - in practice use the split interfaces  
        let (_, consumer) = self.clone().into_split();
        consumer.try_read()
    }
    
    fn is_empty(&self) -> bool {
        let tail = self.tail.load(Ordering::Relaxed);
        let head_packed = self.head.load(Ordering::Acquire);
        let (head_pos, _) = Self::unpack_head(head_packed);
        (tail & self.mask) == (head_pos & self.mask)
    }
    
    fn is_full(&self) -> bool {
        let head_packed = self.head.load(Ordering::Relaxed);
        let (head_pos, _) = Self::unpack_head(head_packed);
        let tail = self.tail.load(Ordering::Acquire);
        (head_pos.wrapping_add(1) & self.mask) == (tail & self.mask)
    }
    
    fn len(&self) -> usize {
        let head_packed = self.head.load(Ordering::Acquire);
        let (head_pos, _) = Self::unpack_head(head_packed);
        let tail = self.tail.load(Ordering::Acquire);
        (head_pos.wrapping_sub(tail)) & self.mask
    }
    
    fn capacity(&self) -> usize {
        self.capacity
    }
}

impl<T> Clone for MPSCRingBuffer<T> {
    fn clone(&self) -> Self {
        // Create a new buffer with same capacity
        Self::with_capacity(self.capacity)
    }
}
```

## Comprehensive Test Suite

Let's create thorough tests for our implementations:

```rust
// tests/integration_tests.rs
use ring_buffer_lib::*;
use std::thread;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[test]
fn test_basic_ring_buffer() {
    let buffer = BasicRingBuffer::new(4);
    
    // Test basic operations
    assert!(buffer.is_empty());
    assert!(!buffer.is_full());
    assert_eq!(buffer.len(), 0);
    
    // Fill the buffer
    for i in 0..4 {
        buffer.try_write(i).unwrap();
    }
    
    assert!(!buffer.is_empty());
    assert!(buffer.is_full());
    assert_eq!(buffer.len(), 4);
    
    // Try to write when full
    assert_eq!(buffer.try_write(99), Err(RingBufferError::BufferFull));
    
    // Read all items
    for i in 0..4 {
        assert_eq!(buffer.try_read().unwrap(), i);
    }
    
    assert!(buffer.is_empty());
    assert_eq!(buffer.try_read(), Err(RingBufferError::BufferEmpty));
}

#[test]
fn test_overwrite_behavior() {
    let buffer = BasicRingBuffer::new(3);
    
    // Fill buffer
    buffer.write_overwrite(1);
    buffer.write_overwrite(2);
    buffer.write_overwrite(3);
    
    // Overwrite oldest
    buffer.write_overwrite(4);
    
    // Should contain [2, 3, 4] in that order
    let items = buffer.to_vec();
    assert_eq!(items, vec![2, 3, 4]);
}

#[test]
fn test_spsc_ring_buffer() {
    let buffer = SPSCRingBuffer::with_capacity(8);
    let (producer, consumer) = buffer.split();
    
    // Test from single thread first
    producer.try_write(42).unwrap();
    assert_eq!(consumer.try_read().unwrap(), 42);
    
    // Test multithreaded
    let handle = thread::spawn(move || {
        for i in 0..1000 {
            producer.write(i);
        }
    });
    
    let mut received = Vec::new();
    for _ in 0..1000 {
        received.push(consumer.read());
    }
    
    handle.join().unwrap();
    
    // Verify order
    for (i, &value) in received.iter().enumerate() {
        assert_eq!(value, i);
    }
}

#[test]
fn test_mpsc_ring_buffer() {
    let buffer = MPSCRingBuffer::with_capacity(64);
    let (producer, consumer) = buffer.into_split();
    
    const NUM_PRODUCERS: usize = 4;
    const ITEMS_PER_PRODUCER: usize = 1000;
    
    // Spawn multiple producer threads
    let mut handles = Vec::new();
    for thread_id in 0..NUM_PRODUCERS {
        let producer = producer.clone();
        let handle = thread::spawn(move || {
            for i in 0..ITEMS_PER_PRODUCER {
                let value = thread_id * ITEMS_PER_PRODUCER + i;
                producer.write(value);
            }
        });
        handles.push(handle);
    }
    
    // Consumer reads all items
    let mut received = Vec::new();
    for _ in 0..(NUM_PRODUCERS * ITEMS_PER_PRODUCER) {
        received.push(consumer.read());
    }
    
    // Wait for all producers
    for handle in handles {
        handle.join().unwrap();
    }
    
    // Verify we got all expected values (order may vary due to concurrency)
    received.sort();
    let expected: Vec<_> = (0..(NUM_PRODUCERS * ITEMS_PER_PRODUCER)).collect();
    assert_eq!(received, expected);
}

#[test]
fn test_stress_concurrent_access() {
    let buffer = Arc::new(BasicRingBuffer::new(1024));
    const NUM_THREADS: usize = 8;
    const OPERATIONS_PER_THREAD: usize = 10000;
    
    let mut handles = Vec::new();
    
    // Spawn writer threads
    for _ in 0..(NUM_THREADS / 2) {
        let buffer = buffer.clone();
        let handle = thread::spawn(move || {
            for i in 0..OPERATIONS_PER_THREAD {
                while buffer.try_write(i).is_err() {
                    thread::yield_now();
                }
            }
        });
        handles.push(handle);
    }
    
    // Spawn reader threads
    for _ in 0..(NUM_THREADS / 2) {
        let buffer = buffer.clone();
        let handle = thread::spawn(move || {
            let mut count = 0;
            while count < OPERATIONS_PER_THREAD {
                if buffer.try_read().is_ok() {
                    count += 1;
                }
                thread::yield_now();
            }
        });
        handles.push(handle);
    }
    
    // Wait for all threads
    for handle in handles {
        handle.join().unwrap();
    }
    
    let stats = buffer.stats();
    println!("Stress test stats: {:?}", stats);
}

#[test]
fn test_memory_usage() {
    // Test that our buffers don't leak memory
    let buffer = SPSCRingBuffer::with_capacity(1024);
    let (producer, consumer) = buffer.split();
    
    // Allocate some test data
    for i in 0..10000 {
        let data = vec![i; 100]; // 100 integers per item
        if producer.try_write(data).is_err() {
            // Buffer full, read some items
            for _ in 0..512 {
                if consumer.try_read().is_err() {
                    break;
                }
            }
        }
    }
    
    // Drain the buffer
    while consumer.try_read().is_ok() {}
    
    // If we get here without OOM, memory management is working
}

#[test]
fn test_performance_characteristics() {
    const ITEMS: usize = 1_000_000;
    
    // Test SPSC performance
    let buffer = SPSCRingBuffer::with_capacity(1024);
    let (producer, consumer) = buffer.split();
    
    let start = Instant::now();
    
    let producer_handle = thread::spawn(move || {
        for i in 0..ITEMS {
            producer.write(i);
        }
    });
    
    let consumer_handle = thread::spawn(move || {
        for _ in 0..ITEMS {
            consumer.read();
        }
    });
    
    producer_handle.join().unwrap();
    consumer_handle.join().unwrap();
    
    let duration = start.elapsed();
    let ops_per_sec = ITEMS as f64 / duration.as_secs_f64();
    
    println!("SPSC throughput: {:.0} ops/sec", ops_per_sec);
    
    // Should be very fast (millions of ops/sec on modern hardware)
    assert!(ops_per_sec > 1_000_000.0);
}
```

## Real-World Usage Examples

Let's create practical examples showing how to use our ring buffers:

```rust
// examples/audio_processor.rs
use ring_buffer_lib::SPSCRingBuffer;
use std::thread;
use std::time::{Duration, Instant};

/// Simulated audio sample
#[derive(Debug, Clone, Copy)]
struct AudioSample {
    left: f32,
    right: f32,
    timestamp: u64,
}

/// Audio processing pipeline using SPSC ring buffer
fn audio_processor_example() {
    const SAMPLE_RATE: usize = 44100; // 44.1 kHz
    const BUFFER_SIZE: usize = 4096;   // ~93ms buffer at 44.1 kHz
    
    let buffer = SPSCRingBuffer::with_capacity(BUFFER_SIZE);
    let (producer, consumer) = buffer.split();
    
    println!("Starting audio processing pipeline...");
    
    // Audio input thread (producer)
    let input_handle = thread::spawn(move || {
        let mut timestamp = 0;
        let start_time = Instant::now();
        
        loop {
            // Simulate reading from audio interface
            let sample = AudioSample {
                left: (timestamp as f32 * 0.001).sin(),   // 1 kHz sine wave
                right: (timestamp as f32 * 0.002).sin(),  // 2 kHz sine wave
                timestamp,
            };
            
            // Try to write sample
            if producer.try_write(sample).is_err() {
                println!("Warning: Audio input buffer overflow!");
                // In real audio code, you might drop samples or apply backpressure
            }
            
            timestamp += 1;
            
            // Simulate real-time audio (sleep until next sample)
            let target_time = start_time + Duration::from_nanos(
                (timestamp * 1_000_000_000) / SAMPLE_RATE as u64
            );
            
            if let Some(sleep_time) = target_time.checked_duration_since(Instant::now()) {
                thread::sleep(sleep_time);
            }
            
            // Run for 1 second
            if timestamp >= SAMPLE_RATE {
                break;
            }
        }
        
        println!("Audio input thread finished");
    });
    
    // Audio processing thread (consumer)
    let processing_handle = thread::spawn(move || {
        let mut samples_processed = 0;
        let mut total_amplitude = 0.0;
        
        while samples_processed < SAMPLE_RATE {
            if let Ok(sample) = consumer.try_read() {
                // Simple audio processing: calculate amplitude
                let amplitude = (sample.left * sample.left + sample.right * sample.right).sqrt();
                total_amplitude += amplitude;
                samples_processed += 1;
                
                // Simulate some processing time
                if samples_processed % 1000 == 0 {
                    println!("Processed {} samples, avg amplitude: {:.3}", 
                             samples_processed, 
                             total_amplitude / samples_processed as f32);
                }
            } else {
                // No samples available, avoid busy waiting
                thread::sleep(Duration::from_micros(100));
            }
        }
        
        println!("Audio processing thread finished");
        println!("Average amplitude: {:.3}", total_amplitude / samples_processed as f32);
    });
    
    input_handle.join().unwrap();
    processing_handle.join().unwrap();
}

fn main() {
    audio_processor_example();
}
```

## Benchmarking Suite

Finally, let's create comprehensive benchmarks:

```rust
// benches/ring_buffer_bench.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use ring_buffer_lib::*;
use std::thread;
use std::sync::Arc;

fn bench_basic_operations(c: &mut Criterion) {
    let mut group = c.benchmark_group("basic_operations");
    
    for capacity in [64, 256, 1024, 4096].iter() {
        group.bench_with_input(
            BenchmarkId::new("basic_write_read", capacity),
            capacity,
            |b, &capacity| {
                let buffer = BasicRingBuffer::new(capacity);
                b.iter(|| {
                    for i in 0..capacity/2 {
                        buffer.try_write(black_box(i)).unwrap();
                    }
                    for _ in 0..capacity/2 {
                        black_box(buffer.try_read().unwrap());
                    }
                });
            },
        );
        
        group.bench_with_input(
            BenchmarkId::new("spsc_write_read", capacity),
            capacity,
            |b, &capacity| {
                let buffer = SPSCRingBuffer::with_capacity(capacity);
                let (producer, consumer) = buffer.split();
                
                b.iter(|| {
                    for i in 0..capacity/2 {
                        producer.try_write(black_box(i)).unwrap();
                    }
                    for _ in 0..capacity/2 {
                        black_box(consumer.try_read().unwrap());
                    }
                });
            },
        );
    }
    
    group.finish();
}

fn bench_concurrent_throughput(c: &mut Criterion) {
    let mut group = c.benchmark_group("concurrent_throughput");
    
    group.bench_function("spsc_throughput", |b| {
        b.iter(|| {
            const ITEMS: usize = 10000;
            let buffer = SPSCRingBuffer::with_capacity(1024);
            let (producer, consumer) = buffer.split();
            
            let producer_handle = thread::spawn(move || {
                for i in 0..ITEMS {
                    while producer.try_write(i).is_err() {
                        std::hint::spin_loop();
                    }
                }
            });
            
            let consumer_handle = thread::spawn(move || {
                for _ in 0..ITEMS {
                    while consumer.try_read().is_err() {
                        std::hint::spin_loop();
                    }
                }
            });
            
            producer_handle.join().unwrap();
            consumer_handle.join().unwrap();
        });
    });
    
    group.bench_function("mpsc_throughput", |b| {
        b.iter(|| {
            const ITEMS_PER_PRODUCER: usize = 2500;
            const NUM_PRODUCERS: usize = 4;
            
            let buffer = MPSCRingBuffer::with_capacity(1024);
            let (producer, consumer) = buffer.into_split();
            
            let mut handles = Vec::new();
            
            for _ in 0..NUM_PRODUCERS {
                let producer = producer.clone();
                let handle = thread::spawn(move || {
                    for i in 0..ITEMS_PER_PRODUCER {
                        while producer.try_write(i).is_err() {
                            std::hint::spin_loop();
                        }
                    }
                });
                handles.push(handle);
            }
            
            let consumer_handle = thread::spawn(move || {
                for _ in 0..(NUM_PRODUCERS * ITEMS_PER_PRODUCER) {
                    while consumer.try_read().is_err() {
                        std::hint::spin_loop();
                    }
                }
            });
            
            for handle in handles {
                handle.join().unwrap();
            }
            consumer_handle.join().unwrap();
        });
    });
    
    group.finish();
}

criterion_group!(benches, bench_basic_operations, bench_concurrent_throughput);
criterion_main!(benches);
```

## Running the Complete Implementation

To run this complete implementation:

```bash
# Run tests
cargo test

# Run benchmarks  
cargo bench

# Run the audio processing example
cargo run --example audio_processor

# Check for memory leaks with valgrind (Linux)
valgrind --tool=memcheck cargo test

# Profile with perf (Linux)
perf record --call-graph dwarf cargo bench
perf report
```

This implementation demonstrates all the key concepts we've covered:

1. **Multiple implementations**: Basic (lock-based), SPSC (lock-free), and MPSC (lock-free with CAS)
2. **Memory safety**: Proper use of `UnsafeCell` and atomic operations
3. **Performance optimization**: Power-of-2 sizes, bitwise operations, cache-friendly layouts
4. **Real-world applicability**: Audio processing example, comprehensive testing
5. **Production readiness**: Error handling, statistics, benchmarking

The ring buffer is a perfect example of how understanding low-level details enables building high-performance, reliable systems. By embracing constraints (fixed size, potential data loss), we achieve predictable performance and resource usage that makes ring buffers indispensable for real-time systems.