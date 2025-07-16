# Rust Implementation: Thread-Safe Copy-on-Write

This implementation demonstrates a production-quality Copy-on-Write container in Rust, showcasing memory safety, thread safety, and zero-cost abstractions.

## The Core CoW Structure

```rust
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::ops::Deref;

/// A thread-safe Copy-on-Write container
pub struct Cow<T> 
where 
    T: Clone,
{
    data: Arc<CowInner<T>>,
}

struct CowInner<T> 
where 
    T: Clone,
{
    value: T,
    ref_count: AtomicUsize,
}

impl<T> Cow<T> 
where 
    T: Clone,
{
    /// Create a new CoW container
    pub fn new(value: T) -> Self {
        Self {
            data: Arc::new(CowInner {
                value,
                ref_count: AtomicUsize::new(1),
            }),
        }
    }
    
    /// Create a clone that shares the underlying data
    pub fn clone(&self) -> Self {
        // Increment reference count atomically
        self.data.ref_count.fetch_add(1, Ordering::SeqCst);
        
        Self {
            data: Arc::clone(&self.data),
        }
    }
    
    /// Get a reference to the data (read-only)
    pub fn get(&self) -> &T {
        &self.data.value
    }
    
    /// Get a mutable reference, triggering copy-on-write if shared
    pub fn get_mut(&mut self) -> &mut T {
        // Check if we need to make a private copy
        if self.data.ref_count.load(Ordering::SeqCst) > 1 {
            self.make_private_copy();
        }
        
        // Safe because we either had exclusive access or just made a private copy
        unsafe {
            &mut *(Arc::as_ptr(&self.data) as *mut CowInner<T>).add(0).cast::<CowInner<T>>().as_mut().unwrap().value
        }
    }
    
    /// Force a private copy if data is shared
    fn make_private_copy(&mut self) {
        // Create new private copy
        let new_inner = CowInner {
            value: self.data.value.clone(),
            ref_count: AtomicUsize::new(1),
        };
        
        // Decrement old reference count
        self.data.ref_count.fetch_sub(1, Ordering::SeqCst);
        
        // Replace with private copy
        self.data = Arc::new(new_inner);
    }
    
    /// Get current reference count (for debugging/monitoring)
    pub fn ref_count(&self) -> usize {
        self.data.ref_count.load(Ordering::SeqCst)
    }
    
    /// Check if this instance has exclusive access to the data
    pub fn is_unique(&self) -> bool {
        self.data.ref_count.load(Ordering::SeqCst) == 1
    }
}

impl<T> Drop for Cow<T> 
where 
    T: Clone,
{
    fn drop(&mut self) {
        // Decrement reference count when dropping
        self.data.ref_count.fetch_sub(1, Ordering::SeqCst);
    }
}

// Implement Deref for convenient read access
impl<T> Deref for Cow<T> 
where 
    T: Clone,
{
    type Target = T;
    
    fn deref(&self) -> &Self::Target {
        self.get()
    }
}

// Make Cow cloneable in the traditional sense
impl<T> Clone for Cow<T> 
where 
    T: Clone,
{
    fn clone(&self) -> Self {
        self.clone()
    }
}
```

## Safer Implementation Using Interior Mutability

The above implementation has unsafe code. Here's a safer version using `Rc` and `RefCell`:

```rust
use std::rc::Rc;
use std::cell::RefCell;
use std::ops::Deref;

/// A safer CoW implementation using interior mutability
pub struct SafeCow<T> 
where 
    T: Clone,
{
    data: Rc<RefCell<T>>,
}

impl<T> SafeCow<T> 
where 
    T: Clone,
{
    pub fn new(value: T) -> Self {
        Self {
            data: Rc::new(RefCell::new(value)),
        }
    }
    
    pub fn clone(&self) -> Self {
        Self {
            data: Rc::clone(&self.data),
        }
    }
    
    /// Get read-only access to the data
    pub fn with<R>(&self, f: impl FnOnce(&T) -> R) -> R {
        f(&*self.data.borrow())
    }
    
    /// Get mutable access, triggering copy-on-write if shared
    pub fn with_mut<R>(&mut self, f: impl FnOnce(&mut T) -> R) -> R {
        // Check if we need to copy
        if Rc::strong_count(&self.data) > 1 {
            // Make private copy
            let cloned_data = self.data.borrow().clone();
            self.data = Rc::new(RefCell::new(cloned_data));
        }
        
        f(&mut *self.data.borrow_mut())
    }
    
    pub fn ref_count(&self) -> usize {
        Rc::strong_count(&self.data)
    }
    
    pub fn is_unique(&self) -> bool {
        Rc::strong_count(&self.data) == 1
    }
}
```

## Example Usage

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_basic_cow_behavior() {
        // Create original data
        let mut original = SafeCow::new(vec![1, 2, 3, 4, 5]);
        
        // Create copies (cheap operation)
        let mut copy1 = original.clone();
        let mut copy2 = original.clone();
        
        // All share the same data
        assert_eq!(original.ref_count(), 3);
        assert_eq!(copy1.ref_count(), 3);
        assert_eq!(copy2.ref_count(), 3);
        
        // Read from all copies
        original.with(|data| assert_eq!(data.len(), 5));
        copy1.with(|data| assert_eq!(data[0], 1));
        copy2.with(|data| assert_eq!(data[4], 5));
        
        // Modify copy1 - triggers copy-on-write
        copy1.with_mut(|data| data.push(6));
        
        // Now copy1 has its own data
        assert_eq!(original.ref_count(), 2);  // original and copy2
        assert_eq!(copy1.ref_count(), 1);     // copy1 is now unique
        assert_eq!(copy2.ref_count(), 2);     // original and copy2
        
        // Verify data isolation
        original.with(|data| assert_eq!(data.len(), 5));  // unchanged
        copy1.with(|data| assert_eq!(data.len(), 6));     // has new element
        copy2.with(|data| assert_eq!(data.len(), 5));     // unchanged
    }
    
    #[test]
    fn test_memory_efficiency() {
        let large_vec: Vec<i32> = (0..1_000_000).collect();
        let original = SafeCow::new(large_vec);
        
        // Create many copies
        let copies: Vec<_> = (0..100).map(|_| original.clone()).collect();
        
        // All copies share the same underlying data
        assert_eq!(original.ref_count(), 101);  // original + 100 copies
        
        // Memory usage is still just one copy of the vector
        // (plus small overhead for Rc and RefCell)
    }
    
    #[test]
    fn test_progressive_copying() {
        let mut original = SafeCow::new(String::from("Hello"));
        let mut copy1 = original.clone();
        let mut copy2 = original.clone();
        let mut copy3 = original.clone();
        
        // All shared initially
        assert_eq!(original.ref_count(), 4);
        
        // Modify copy1
        copy1.with_mut(|s| s.push_str(" World"));
        assert_eq!(copy1.ref_count(), 1);     // copy1 now unique
        assert_eq!(original.ref_count(), 3);  // others still shared
        
        // Modify copy2
        copy2.with_mut(|s| s.push_str(" Rust"));
        assert_eq!(copy2.ref_count(), 1);     // copy2 now unique
        assert_eq!(original.ref_count(), 2);  // original and copy3 still shared
        
        // Verify all have different values
        original.with(|s| assert_eq!(s, "Hello"));
        copy1.with(|s| assert_eq!(s, "Hello World"));
        copy2.with(|s| assert_eq!(s, "Hello Rust"));
        copy3.with(|s| assert_eq!(s, "Hello"));  // still shares with original
    }
}
```

## Performance Benchmarks

```rust
#[cfg(test)]
mod benchmarks {
    use super::*;
    use std::time::Instant;
    
    #[test]
    fn benchmark_cow_vs_clone() {
        let large_data: Vec<i32> = (0..1_000_000).collect();
        
        // Benchmark traditional cloning
        let start = Instant::now();
        let traditional_copies: Vec<_> = (0..100)
            .map(|_| large_data.clone())
            .collect();
        let traditional_time = start.elapsed();
        
        // Benchmark CoW
        let original = SafeCow::new(large_data);
        let start = Instant::now();
        let cow_copies: Vec<_> = (0..100)
            .map(|_| original.clone())
            .collect();
        let cow_time = start.elapsed();
        
        println!("Traditional cloning: {:?}", traditional_time);
        println!("CoW cloning: {:?}", cow_time);
        println!("Speedup: {:.1}x", traditional_time.as_nanos() as f64 / cow_time.as_nanos() as f64);
        
        // CoW should be orders of magnitude faster
        assert!(cow_time < traditional_time / 100);
    }
}
```

## Thread-Safe Version

For truly concurrent access, use `Arc` and `Mutex`:

```rust
use std::sync::{Arc, Mutex};

pub struct ThreadSafeCow<T> 
where 
    T: Clone + Send + Sync,
{
    data: Arc<Mutex<T>>,
}

impl<T> ThreadSafeCow<T> 
where 
    T: Clone + Send + Sync,
{
    pub fn new(value: T) -> Self {
        Self {
            data: Arc::new(Mutex::new(value)),
        }
    }
    
    pub fn clone(&self) -> Self {
        Self {
            data: Arc::clone(&self.data),
        }
    }
    
    pub fn with<R>(&self, f: impl FnOnce(&T) -> R) -> R {
        let guard = self.data.lock().unwrap();
        f(&*guard)
    }
    
    pub fn with_mut<R>(&mut self, f: impl FnOnce(&mut T) -> R) -> R {
        if Arc::strong_count(&self.data) > 1 {
            // Make private copy
            let cloned_data = {
                let guard = self.data.lock().unwrap();
                guard.clone()
            };
            self.data = Arc::new(Mutex::new(cloned_data));
        }
        
        let mut guard = self.data.lock().unwrap();
        f(&mut *guard)
    }
    
    pub fn ref_count(&self) -> usize {
        Arc::strong_count(&self.data)
    }
}

unsafe impl<T> Send for ThreadSafeCow<T> where T: Clone + Send + Sync {}
unsafe impl<T> Sync for ThreadSafeCow<T> where T: Clone + Send + Sync {}
```

## Key Implementation Insights

1. **Memory Safety**: Rust's ownership system prevents data races and memory corruption
2. **Zero-Cost Abstractions**: The CoW wrapper adds minimal runtime overhead
3. **Thread Safety**: Multiple approaches available depending on concurrency needs
4. **Type Safety**: Generic implementation works with any cloneable type
5. **RAII**: Automatic cleanup through `Drop` trait implementation

This implementation demonstrates how Rust's type system enables both safe and efficient Copy-on-Write containers suitable for production use.