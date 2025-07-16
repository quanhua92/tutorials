# Rust Implementation: Building an Adaptive Splay Tree

## Overview

This implementation demonstrates the core concepts of adaptive data structures through a working splay tree in Rust. The code emphasizes clarity and educational value while maintaining efficiency and safety.

## Core Data Structure

```rust
use std::mem;
use std::cmp::Ordering;

#[derive(Debug, Clone)]
pub struct SplayTree<T> {
    root: Option<Box<Node<T>>>,
    size: usize,
}

#[derive(Debug, Clone)]
struct Node<T> {
    value: T,
    left: Option<Box<Node<T>>>,
    right: Option<Box<Node<T>>>,
}

impl<T> Node<T> {
    fn new(value: T) -> Self {
        Node {
            value,
            left: None,
            right: None,
        }
    }
    
    fn into_box(self) -> Box<Self> {
        Box::new(self)
    }
}
```

## Tree Rotations: The Foundation of Adaptation

### Right Rotation (Zig)
```rust
impl<T> SplayTree<T> {
    /// Performs a right rotation on the given node
    /// 
    /// Before:     After:
    ///    y          x
    ///   / \        / \
    ///  x   C  =>  A   y
    /// / \            / \
    ///A   B          B   C
    fn rotate_right(mut y: Box<Node<T>>) -> Box<Node<T>> {
        let mut x = y.left.take().expect("Left child must exist for right rotation");
        y.left = x.right.take();
        x.right = Some(y);
        x
    }
    
    /// Performs a left rotation on the given node
    fn rotate_left(mut x: Box<Node<T>>) -> Box<Node<T>> {
        let mut y = x.right.take().expect("Right child must exist for left rotation");
        x.right = y.left.take();
        y.left = Some(x);
        y
    }
}
```

## The Splay Operation: Where Adaptation Happens

```rust
impl<T: Ord> SplayTree<T> {
    /// Splays the node containing the given value to the root
    /// This is the core adaptive mechanism
    fn splay(&mut self, value: &T) {
        if self.root.is_none() {
            return;
        }
        
        let mut root = self.root.take().unwrap();
        root = Self::splay_node(root, value);
        self.root = Some(root);
    }
    
    fn splay_node(mut node: Box<Node<T>>, value: &T) -> Box<Node<T>> {
        match value.cmp(&node.value) {
            Ordering::Equal => {
                // Found the node - it's already at the root of this subtree
                node
            }
            Ordering::Less => {
                // Value is in the left subtree
                if let Some(left) = node.left.take() {
                    match value.cmp(&left.value) {
                        Ordering::Equal => {
                            // Zig case: target is direct left child
                            node.left = Some(left);
                            Self::rotate_right(node)
                        }
                        Ordering::Less => {
                            // Zig-Zig case: target is in left-left subtree
                            if left.left.is_some() {
                                let left = Self::splay_node(left, value);
                                node.left = Some(left);
                                node = Self::rotate_right(node);
                                Self::rotate_right(node)
                            } else {
                                node.left = Some(left);
                                Self::rotate_right(node)
                            }
                        }
                        Ordering::Greater => {
                            // Zig-Zag case: target is in left-right subtree
                            if left.right.is_some() {
                                let left = Self::splay_node(left, value);
                                node.left = Some(left);
                                node = Self::rotate_right(node);
                                Self::rotate_left(node)
                            } else {
                                node.left = Some(left);
                                Self::rotate_right(node)
                            }
                        }
                    }
                } else {
                    node
                }
            }
            Ordering::Greater => {
                // Value is in the right subtree (symmetric to left case)
                if let Some(right) = node.right.take() {
                    match value.cmp(&right.value) {
                        Ordering::Equal => {
                            // Zig case: target is direct right child
                            node.right = Some(right);
                            Self::rotate_left(node)
                        }
                        Ordering::Greater => {
                            // Zig-Zig case: target is in right-right subtree
                            if right.right.is_some() {
                                let right = Self::splay_node(right, value);
                                node.right = Some(right);
                                node = Self::rotate_left(node);
                                Self::rotate_left(node)
                            } else {
                                node.right = Some(right);
                                Self::rotate_left(node)
                            }
                        }
                        Ordering::Less => {
                            // Zig-Zag case: target is in right-left subtree
                            if right.left.is_some() {
                                let right = Self::splay_node(right, value);
                                node.right = Some(right);
                                node = Self::rotate_left(node);
                                Self::rotate_right(node)
                            } else {
                                node.right = Some(right);
                                Self::rotate_left(node)
                            }
                        }
                    }
                } else {
                    node
                }
            }
        }
    }
}
```

## Public Interface: The Adaptive API

```rust
impl<T: Ord> SplayTree<T> {
    /// Creates a new empty splay tree
    pub fn new() -> Self {
        SplayTree {
            root: None,
            size: 0,
        }
    }
    
    /// Inserts a value into the tree
    /// The inserted value is automatically splayed to the root
    pub fn insert(&mut self, value: T) {
        if self.root.is_none() {
            self.root = Some(Node::new(value).into_box());
            self.size = 1;
            return;
        }
        
        self.root = Some(self.insert_node(self.root.take().unwrap(), value));
        self.splay(&value);
    }
    
    fn insert_node(&mut self, mut node: Box<Node<T>>, value: T) -> Box<Node<T>> {
        match value.cmp(&node.value) {
            Ordering::Less => {
                if let Some(left) = node.left.take() {
                    node.left = Some(self.insert_node(left, value));
                } else {
                    node.left = Some(Node::new(value).into_box());
                    self.size += 1;
                }
            }
            Ordering::Greater => {
                if let Some(right) = node.right.take() {
                    node.right = Some(self.insert_node(right, value));
                } else {
                    node.right = Some(Node::new(value).into_box());
                    self.size += 1;
                }
            }
            Ordering::Equal => {
                // Value already exists - replace it
                node.value = value;
            }
        }
        node
    }
    
    /// Searches for a value in the tree
    /// If found, the value is splayed to the root (adaptation!)
    pub fn search(&mut self, value: &T) -> bool {
        if self.contains_node(&self.root, value) {
            self.splay(value);
            true
        } else {
            false
        }
    }
    
    fn contains_node(&self, node: &Option<Box<Node<T>>>, value: &T) -> bool {
        match node {
            None => false,
            Some(n) => match value.cmp(&n.value) {
                Ordering::Equal => true,
                Ordering::Less => self.contains_node(&n.left, value),
                Ordering::Greater => self.contains_node(&n.right, value),
            }
        }
    }
    
    /// Returns the number of elements in the tree
    pub fn len(&self) -> usize {
        self.size
    }
    
    /// Returns true if the tree is empty
    pub fn is_empty(&self) -> bool {
        self.size == 0
    }
    
    /// Returns the value at the root (most recently accessed)
    pub fn root_value(&self) -> Option<&T> {
        self.root.as_ref().map(|node| &node.value)
    }
}
```

## Demonstrating Adaptation: Usage Examples

```rust
fn main() {
    demonstrate_adaptation();
    demonstrate_access_patterns();
    benchmark_performance();
}

fn demonstrate_adaptation() {
    println!("=== Demonstrating Splay Tree Adaptation ===");
    
    let mut tree = SplayTree::new();
    
    // Insert values
    for value in [50, 30, 70, 20, 40, 60, 80] {
        tree.insert(value);
        println!("Inserted {}, root is now: {:?}", value, tree.root_value());
    }
    
    // Demonstrate adaptation through access patterns
    println!("\nAccessing values in different patterns:");
    
    // Pattern 1: Repeated access to same value
    for _ in 0..3 {
        tree.search(&30);
        println!("Accessed 30, root is: {:?}", tree.root_value());
    }
    
    // Pattern 2: Alternating access
    for value in [70, 20, 70, 20] {
        tree.search(&value);
        println!("Accessed {}, root is: {:?}", value, tree.root_value());
    }
}

fn demonstrate_access_patterns() {
    println!("\n=== Access Pattern Analysis ===");
    
    let mut tree = SplayTree::new();
    
    // Build a tree with many values
    for i in 1..=100 {
        tree.insert(i * 10);
    }
    
    // Pattern 1: Working set (frequently accessing a small subset)
    let working_set = [100, 200, 300, 400, 500];
    println!("Working set pattern:");
    for _ in 0..10 {
        for &value in &working_set {
            tree.search(&value);
        }
    }
    println!("After working set access, root is: {:?}", tree.root_value());
    
    // Pattern 2: Sequential access
    println!("\nSequential access pattern:");
    for i in 1..=10 {
        tree.search(&(i * 10));
    }
    println!("After sequential access, root is: {:?}", tree.root_value());
    
    // Pattern 3: Random access (less benefit from adaptation)
    println!("\nRandom access pattern:");
    use std::collections::HashMap;
    let mut rng = simple_rng();
    let mut access_counts = HashMap::new();
    
    for _ in 0..50 {
        let value = ((rng.next() % 100) + 1) * 10;
        tree.search(&value);
        *access_counts.entry(value).or_insert(0) += 1;
    }
    
    println!("After random access, root is: {:?}", tree.root_value());
    println!("Most accessed values: {:?}", 
             access_counts.iter().max_by_key(|(_, &count)| count));
}

// Simple linear congruential generator for demonstration
struct SimpleRng {
    state: u64,
}

impl SimpleRng {
    fn new() -> Self {
        SimpleRng { state: 1 }
    }
    
    fn next(&mut self) -> u64 {
        self.state = (self.state.wrapping_mul(1664525).wrapping_add(1013904223)) % (1 << 32);
        self.state
    }
}

fn simple_rng() -> SimpleRng {
    SimpleRng::new()
}

fn benchmark_performance() {
    println!("\n=== Performance Comparison ===");
    
    let mut splay_tree = SplayTree::new();
    
    // Insert 1000 values
    for i in 1..=1000 {
        splay_tree.insert(i);
    }
    
    // Benchmark different access patterns
    println!("Benchmarking access patterns...");
    
    // Pattern 1: Frequent access to small subset (should be very fast)
    let start = std::time::Instant::now();
    for _ in 0..1000 {
        splay_tree.search(&500);
        splay_tree.search(&501);
        splay_tree.search(&502);
    }
    let frequent_access_time = start.elapsed();
    
    // Pattern 2: Random access (should be slower)
    let start = std::time::Instant::now();
    let mut rng = simple_rng();
    for _ in 0..1000 {
        let value = (rng.next() % 1000) + 1;
        splay_tree.search(&(value as i32));
    }
    let random_access_time = start.elapsed();
    
    println!("Frequent access time: {:?}", frequent_access_time);
    println!("Random access time: {:?}", random_access_time);
    println!("Adaptation benefit: {:.2}x speedup", 
             random_access_time.as_nanos() as f64 / frequent_access_time.as_nanos() as f64);
}
```

## Key Rust-Specific Considerations

### Memory Safety
The implementation uses `Box<Node<T>>` for heap allocation and maintains Rust's ownership guarantees. The `take()` method is used extensively to move ownership when restructuring the tree.

### Performance Optimizations
```rust
impl<T: Ord> SplayTree<T> {
    /// Optimized search that doesn't allocate if value isn't found
    pub fn contains(&self, value: &T) -> bool {
        self.contains_node(&self.root, value)
    }
    
    /// Peek at root without triggering adaptation
    pub fn peek_root(&self) -> Option<&T> {
        self.root.as_ref().map(|node| &node.value)
    }
    
    /// Get tree statistics for debugging
    pub fn stats(&self) -> TreeStats {
        TreeStats {
            size: self.size,
            depth: self.calculate_depth(&self.root),
            root_value: self.root_value().cloned(),
        }
    }
    
    fn calculate_depth(&self, node: &Option<Box<Node<T>>>) -> usize {
        match node {
            None => 0,
            Some(n) => 1 + std::cmp::max(
                self.calculate_depth(&n.left),
                self.calculate_depth(&n.right)
            ),
        }
    }
}

#[derive(Debug)]
pub struct TreeStats<T> {
    pub size: usize,
    pub depth: usize,
    pub root_value: Option<T>,
}
```

## Testing the Implementation

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_basic_operations() {
        let mut tree = SplayTree::new();
        
        // Test insertion
        tree.insert(5);
        tree.insert(3);
        tree.insert(7);
        assert_eq!(tree.len(), 3);
        
        // Test search with adaptation
        assert!(tree.search(&3));
        assert_eq!(tree.root_value(), Some(&3));
        
        assert!(tree.search(&7));
        assert_eq!(tree.root_value(), Some(&7));
        
        // Test non-existent value
        assert!(!tree.search(&10));
    }
    
    #[test]
    fn test_adaptation_behavior() {
        let mut tree = SplayTree::new();
        
        // Insert values in order
        for i in 1..=10 {
            tree.insert(i);
        }
        
        // Access a value multiple times
        for _ in 0..5 {
            tree.search(&5);
            assert_eq!(tree.root_value(), Some(&5));
        }
        
        // Access a different value
        tree.search(&8);
        assert_eq!(tree.root_value(), Some(&8));
    }
    
    #[test]
    fn test_working_set_performance() {
        let mut tree = SplayTree::new();
        
        // Insert many values
        for i in 1..=100 {
            tree.insert(i);
        }
        
        // Create a working set
        let working_set = [10, 20, 30, 40, 50];
        
        // Access working set multiple times
        for _ in 0..10 {
            for &value in &working_set {
                tree.search(&value);
            }
        }
        
        // The most recently accessed value should be at root
        assert_eq!(tree.root_value(), Some(&50));
    }
}
```

## Running the Code

To run this implementation:

1. Create a new Rust project: `cargo new splay_tree_demo`
2. Replace the contents of `src/main.rs` with the code above
3. Run with: `cargo run`

The output will demonstrate how the splay tree adapts to different access patterns, showing the adaptive behavior in action.

## Key Takeaways

1. **Adaptation is Automatic**: Every search operation triggers adaptation through splaying
2. **Performance Benefits are Real**: Frequently accessed items become much faster to access
3. **Memory Safety**: Rust's ownership system ensures safe tree restructuring
4. **Simplicity**: The core adaptation logic is straightforward despite its power

This implementation demonstrates how adaptive data structures can be both theoretically elegant and practically useful, automatically optimizing themselves for the workloads they encounter.