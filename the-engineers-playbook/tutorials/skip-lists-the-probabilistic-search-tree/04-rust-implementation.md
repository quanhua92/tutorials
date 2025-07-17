# Rust Implementation: A Complete Skip List

## Overview

We'll implement a complete skip list in Rust that demonstrates:
- Probabilistic level assignment
- Efficient search, insert, and delete operations
- Thread-safe concurrent access
- Memory-safe pointer manipulation
- Performance analysis and testing

This implementation showcases the elegance and practicality of skip lists in a systems programming language.

## Core Data Structures

```rust
use std::sync::{Arc, RwLock};
use std::cmp::Ordering;
use std::fmt;
use rand::Rng;

const MAX_LEVEL: usize = 16;
const PROMOTION_PROBABILITY: f64 = 0.5;

#[derive(Debug)]
struct Node<T> {
    value: T,
    forward: Vec<Option<Arc<RwLock<Node<T>>>>>,
}

impl<T> Node<T> {
    fn new(value: T, level: usize) -> Self {
        let mut forward = Vec::with_capacity(level + 1);
        for _ in 0..=level {
            forward.push(None);
        }
        
        Self { value, forward }
    }
    
    fn level(&self) -> usize {
        self.forward.len() - 1
    }
}

#[derive(Debug)]
pub struct SkipList<T> {
    head: Arc<RwLock<Node<Option<T>>>>,
    max_level: usize,
    length: usize,
}
```

## Implementation Core

```rust
impl<T: Ord + Clone + fmt::Debug> SkipList<T> {
    pub fn new() -> Self {
        let head = Arc::new(RwLock::new(Node::new(None, MAX_LEVEL)));
        
        Self {
            head,
            max_level: 0,
            length: 0,
        }
    }
    
    fn random_level(&self) -> usize {
        let mut level = 0;
        let mut rng = rand::thread_rng();
        
        while level < MAX_LEVEL && rng.gen::<f64>() < PROMOTION_PROBABILITY {
            level += 1;
        }
        
        level
    }
    
    fn find_update_path(&self, target: &T) -> Vec<Arc<RwLock<Node<Option<T>>>>> {
        let mut update = Vec::with_capacity(MAX_LEVEL + 1);
        let mut current = self.head.clone();
        
        for level in (0..=self.max_level).rev() {
            loop {
                let current_node = current.read().unwrap();
                
                if let Some(next_arc) = &current_node.forward[level] {
                    let next_node = next_arc.read().unwrap();
                    
                    if let Some(next_value) = &next_node.value {
                        match next_value.cmp(target) {
                            Ordering::Less => {
                                drop(next_node);
                                drop(current_node);
                                current = next_arc.clone();
                                continue;
                            }
                            _ => break,
                        }
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
            
            update.push(current.clone());
        }
        
        update.reverse();
        update
    }
}
```

## Search Operation

```rust
impl<T: Ord + Clone + fmt::Debug> SkipList<T> {
    pub fn contains(&self, target: &T) -> bool {
        let mut current = self.head.clone();
        
        for level in (0..=self.max_level).rev() {
            loop {
                let current_node = current.read().unwrap();
                
                if let Some(next_arc) = &current_node.forward[level] {
                    let next_node = next_arc.read().unwrap();
                    
                    if let Some(next_value) = &next_node.value {
                        match next_value.cmp(target) {
                            Ordering::Less => {
                                drop(next_node);
                                drop(current_node);
                                current = next_arc.clone();
                                continue;
                            }
                            Ordering::Equal => return true,
                            Ordering::Greater => break,
                        }
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
        }
        
        false
    }
    
    pub fn find(&self, target: &T) -> Option<T> {
        let mut current = self.head.clone();
        
        for level in (0..=self.max_level).rev() {
            loop {
                let current_node = current.read().unwrap();
                
                if let Some(next_arc) = &current_node.forward[level] {
                    let next_node = next_arc.read().unwrap();
                    
                    if let Some(next_value) = &next_node.value {
                        match next_value.cmp(target) {
                            Ordering::Less => {
                                drop(next_node);
                                drop(current_node);
                                current = next_arc.clone();
                                continue;
                            }
                            Ordering::Equal => return Some(next_value.clone()),
                            Ordering::Greater => break,
                        }
                    } else {
                        break;
                    }
                } else {
                    break;
                }
            }
        }
        
        None
    }
}
```

## Insert Operation

```rust
impl<T: Ord + Clone + fmt::Debug> SkipList<T> {
    pub fn insert(&mut self, value: T) -> bool {
        // Check if value already exists
        if self.contains(&value) {
            return false;
        }
        
        let update = self.find_update_path(&value);
        let new_level = self.random_level();
        
        // Update max level if necessary
        if new_level > self.max_level {
            self.max_level = new_level;
        }
        
        // Create new node
        let new_node = Arc::new(RwLock::new(Node::new(Some(value), new_level)));
        
        // Link new node at each level
        for level in 0..=new_level {
            let mut update_node = update[level].write().unwrap();
            
            if level < update_node.forward.len() {
                let next = update_node.forward[level].clone();
                new_node.write().unwrap().forward[level] = next;
                update_node.forward[level] = Some(new_node.clone());
            }
        }
        
        self.length += 1;
        true
    }
}
```

## Delete Operation

```rust
impl<T: Ord + Clone + fmt::Debug> SkipList<T> {
    pub fn remove(&mut self, target: &T) -> bool {
        let update = self.find_update_path(target);
        
        // Find the node to remove
        let current_node = update[0].read().unwrap();
        let target_node = if let Some(next_arc) = &current_node.forward[0] {
            let next_node = next_arc.read().unwrap();
            if let Some(next_value) = &next_node.value {
                if next_value == target {
                    Some(next_arc.clone())
                } else {
                    None
                }
            } else {
                None
            }
        } else {
            None
        };
        
        drop(current_node);
        
        if let Some(target_arc) = target_node {
            let target_level = target_arc.read().unwrap().level();
            
            // Update pointers at each level
            for level in 0..=target_level {
                let mut update_node = update[level].write().unwrap();
                if level < update_node.forward.len() {
                    let target_node = target_arc.read().unwrap();
                    if level < target_node.forward.len() {
                        update_node.forward[level] = target_node.forward[level].clone();
                    }
                }
            }
            
            // Update max level if necessary
            while self.max_level > 0 {
                let head_node = self.head.read().unwrap();
                if head_node.forward[self.max_level].is_some() {
                    break;
                }
                self.max_level -= 1;
            }
            
            self.length -= 1;
            true
        } else {
            false
        }
    }
}
```

## Utility Methods

```rust
impl<T: Ord + Clone + fmt::Debug> SkipList<T> {
    pub fn len(&self) -> usize {
        self.length
    }
    
    pub fn is_empty(&self) -> bool {
        self.length == 0
    }
    
    pub fn to_vec(&self) -> Vec<T> {
        let mut result = Vec::new();
        let mut current = self.head.clone();
        
        while let Some(next_arc) = {
            let current_node = current.read().unwrap();
            current_node.forward[0].clone()
        } {
            let next_node = next_arc.read().unwrap();
            if let Some(value) = &next_node.value {
                result.push(value.clone());
            }
            current = next_arc.clone();
        }
        
        result
    }
    
    pub fn display_structure(&self) {
        println!("Skip List Structure (max level: {}):", self.max_level);
        
        for level in (0..=self.max_level).rev() {
            print!("Level {}: HEAD", level);
            
            let mut current = self.head.clone();
            
            while let Some(next_arc) = {
                let current_node = current.read().unwrap();
                if level < current_node.forward.len() {
                    current_node.forward[level].clone()
                } else {
                    None
                }
            } {
                let next_node = next_arc.read().unwrap();
                if let Some(value) = &next_node.value {
                    print!(" → {:?}", value);
                }
                current = next_arc.clone();
            }
            
            println!(" → NULL");
        }
    }
}
```

## Performance Analysis

```rust
impl<T: Ord + Clone + fmt::Debug> SkipList<T> {
    pub fn analyze_distribution(&self) -> DistributionStats {
        let mut level_counts = vec![0; self.max_level + 1];
        let mut current = self.head.clone();
        
        while let Some(next_arc) = {
            let current_node = current.read().unwrap();
            current_node.forward[0].clone()
        } {
            let next_node = next_arc.read().unwrap();
            let node_level = next_node.level();
            
            for level in 0..=node_level {
                level_counts[level] += 1;
            }
            
            current = next_arc.clone();
        }
        
        DistributionStats {
            total_nodes: self.length,
            max_level: self.max_level,
            level_counts,
        }
    }
}

#[derive(Debug)]
pub struct DistributionStats {
    pub total_nodes: usize,
    pub max_level: usize,
    pub level_counts: Vec<usize>,
}

impl DistributionStats {
    pub fn print_analysis(&self) {
        println!("\n=== Distribution Analysis ===");
        println!("Total nodes: {}", self.total_nodes);
        println!("Max level: {}", self.max_level);
        
        for (level, count) in self.level_counts.iter().enumerate() {
            let percentage = if self.total_nodes > 0 {
                (*count as f64 / self.total_nodes as f64) * 100.0
            } else {
                0.0
            };
            
            let expected = if level == 0 {
                100.0
            } else {
                100.0 * PROMOTION_PROBABILITY.powi(level as i32)
            };
            
            println!(
                "Level {}: {} nodes ({:.1}% actual, {:.1}% expected)",
                level, count, percentage, expected
            );
        }
    }
}
```

## Testing and Examples

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_basic_operations() {
        let mut list = SkipList::new();
        
        // Test insertion
        assert!(list.insert(5));
        assert!(list.insert(2));
        assert!(list.insert(8));
        assert!(list.insert(1));
        assert!(list.insert(7));
        
        // Test duplicate insertion
        assert!(!list.insert(5));
        
        // Test length
        assert_eq!(list.len(), 5);
        
        // Test search
        assert!(list.contains(&5));
        assert!(list.contains(&2));
        assert!(!list.contains(&10));
        
        // Test ordering
        assert_eq!(list.to_vec(), vec![1, 2, 5, 7, 8]);
    }
    
    #[test]
    fn test_deletion() {
        let mut list = SkipList::new();
        
        for i in vec![5, 2, 8, 1, 7, 3, 6] {
            list.insert(i);
        }
        
        assert_eq!(list.len(), 7);
        
        // Remove middle element
        assert!(list.remove(&5));
        assert_eq!(list.to_vec(), vec![1, 2, 3, 6, 7, 8]);
        assert_eq!(list.len(), 6);
        
        // Remove non-existent element
        assert!(!list.remove(&10));
        assert_eq!(list.len(), 6);
        
        // Remove first element
        assert!(list.remove(&1));
        assert_eq!(list.to_vec(), vec![2, 3, 6, 7, 8]);
        
        // Remove last element
        assert!(list.remove(&8));
        assert_eq!(list.to_vec(), vec![2, 3, 6, 7]);
    }
    
    #[test]
    fn test_large_dataset() {
        let mut list = SkipList::new();
        let n = 1000;
        
        // Insert random values
        let mut values: Vec<i32> = (0..n).collect();
        values.shuffle(&mut rand::thread_rng());
        
        for value in &values {
            list.insert(*value);
        }
        
        assert_eq!(list.len(), n);
        
        // Verify all values are present and ordered
        let result = list.to_vec();
        for i in 0..n {
            assert_eq!(result[i], i as i32);
        }
        
        // Test search performance
        for value in &values {
            assert!(list.contains(value));
        }
    }
    
    #[test]
    fn test_distribution() {
        let mut list = SkipList::new();
        
        // Insert many elements
        for i in 0..1000 {
            list.insert(i);
        }
        
        let stats = list.analyze_distribution();
        stats.print_analysis();
        
        // Verify that higher levels have fewer elements
        for level in 1..stats.level_counts.len() {
            assert!(
                stats.level_counts[level] <= stats.level_counts[level - 1],
                "Level {} has more elements than level {}",
                level,
                level - 1
            );
        }
    }
}

fn main() {
    println!("=== Skip List Demo ===\n");
    
    let mut list = SkipList::new();
    
    // Insert some values
    let values = vec![42, 17, 3, 89, 25, 61, 7, 99, 11, 55];
    
    println!("Inserting values: {:?}", values);
    for value in values {
        list.insert(value);
    }
    
    // Display structure
    list.display_structure();
    
    // Show sorted order
    println!("\nSorted order: {:?}", list.to_vec());
    
    // Test search
    println!("\nSearch tests:");
    for target in vec![25, 50, 99, 1] {
        println!("  Contains {}: {}", target, list.contains(&target));
    }
    
    // Remove some elements
    println!("\nRemoving 17 and 89...");
    list.remove(&17);
    list.remove(&89);
    
    println!("After removal: {:?}", list.to_vec());
    
    // Performance test with larger dataset
    println!("\n=== Performance Test ===");
    let mut large_list = SkipList::new();
    
    let start = std::time::Instant::now();
    
    // Insert 10,000 random values
    for _ in 0..10_000 {
        let value = rand::thread_rng().gen_range(0..100_000);
        large_list.insert(value);
    }
    
    let insert_time = start.elapsed();
    println!("Inserted {} elements in {:?}", large_list.len(), insert_time);
    
    // Search performance
    let start = std::time::Instant::now();
    let mut found_count = 0;
    
    for _ in 0..1_000 {
        let target = rand::thread_rng().gen_range(0..100_000);
        if large_list.contains(&target) {
            found_count += 1;
        }
    }
    
    let search_time = start.elapsed();
    println!("Performed 1,000 searches in {:?} (found {})", search_time, found_count);
    
    // Analyze distribution
    let stats = large_list.analyze_distribution();
    stats.print_analysis();
}
```

## Key Implementation Features

### 1. Thread Safety
Uses `Arc<RwLock<>>` for safe concurrent access:
- Multiple readers can access simultaneously
- Writers get exclusive access
- Prevents data races

### 2. Memory Safety
Rust's ownership system prevents:
- Use-after-free bugs
- Double-free errors  
- Dangling pointer access
- Memory leaks

### 3. Probabilistic Promotion
```rust
fn random_level(&self) -> usize {
    let mut level = 0;
    while level < MAX_LEVEL && rng.gen::<f64>() < PROMOTION_PROBABILITY {
        level += 1;
    }
    level
}
```

### 4. Efficient Search Path
The `find_update_path` method efficiently finds insertion/deletion points while maintaining the update vector needed for modifications.

### 5. Self-Balancing
No explicit rebalancing needed—the probabilistic structure naturally maintains good performance characteristics.

## Running the Implementation

Add to `Cargo.toml`:
```toml
[dependencies]
rand = "0.8"
```

Compile and run:
```bash
cargo run
cargo test
```

This implementation demonstrates the elegance of skip lists in Rust:
- **Simple code** compared to balanced trees
- **Predictable performance** characteristics
- **Natural concurrency** support
- **Memory safety** guarantees

The probabilistic approach trades worst-case guarantees for implementation simplicity while maintaining excellent expected performance—making skip lists an ideal choice for many concurrent systems.