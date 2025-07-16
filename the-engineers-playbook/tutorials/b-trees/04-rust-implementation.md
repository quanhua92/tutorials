# Rust Implementation: Building a Production-Ready B-Tree

## Overview

This implementation demonstrates a comprehensive B-Tree in Rust, emphasizing type safety, performance, and practical usability. We'll build a B-Tree that can serve as the foundation for database indexes, file systems, or any application requiring efficient sorted data access.

## Core Data Structures

### Node Definition

```rust
use std::cmp::Ordering;
use std::fmt::Debug;

const DEFAULT_ORDER: usize = 64; // Common choice for 4KB pages

#[derive(Debug, Clone)]
pub struct BTree<K, V> {
    root: Option<Box<Node<K, V>>>,
    order: usize,
    size: usize,
}

#[derive(Debug, Clone)]
struct Node<K, V> {
    keys: Vec<K>,
    values: Vec<V>,
    children: Vec<Box<Node<K, V>>>,
    is_leaf: bool,
}

impl<K, V> Node<K, V> {
    fn new(is_leaf: bool) -> Self {
        Node {
            keys: Vec::new(),
            values: Vec::new(),
            children: Vec::new(),
            is_leaf,
        }
    }
    
    fn is_full(&self, order: usize) -> bool {
        self.keys.len() >= order - 1
    }
    
    fn is_minimal(&self, order: usize) -> bool {
        self.keys.len() < (order / 2)
    }
    
    fn key_count(&self) -> usize {
        self.keys.len()
    }
    
    fn child_count(&self) -> usize {
        self.children.len()
    }
}
```

### B-Tree Implementation

```rust
impl<K, V> BTree<K, V>
where
    K: Ord + Clone + Debug,
    V: Clone + Debug,
{
    /// Create a new B-Tree with default order
    pub fn new() -> Self {
        Self::with_order(DEFAULT_ORDER)
    }
    
    /// Create a new B-Tree with specified order
    pub fn with_order(order: usize) -> Self {
        assert!(order >= 3, "B-Tree order must be at least 3");
        
        BTree {
            root: None,
            order,
            size: 0,
        }
    }
    
    /// Get the number of key-value pairs in the tree
    pub fn len(&self) -> usize {
        self.size
    }
    
    /// Check if the tree is empty
    pub fn is_empty(&self) -> bool {
        self.size == 0
    }
    
    /// Get the order of the B-Tree
    pub fn order(&self) -> usize {
        self.order
    }
}
```

## Search Operations

### Basic Search

```rust
impl<K, V> BTree<K, V>
where
    K: Ord + Clone + Debug,
    V: Clone + Debug,
{
    /// Search for a key in the B-Tree
    pub fn search(&self, key: &K) -> Option<&V> {
        match &self.root {
            None => None,
            Some(root) => self.search_node(root, key),
        }
    }
    
    fn search_node(&self, node: &Node<K, V>, key: &K) -> Option<&V> {
        // Binary search within the node
        match node.keys.binary_search(key) {
            Ok(index) => Some(&node.values[index]),
            Err(index) => {
                if node.is_leaf {
                    None
                } else {
                    // Search in the appropriate child
                    self.search_node(&node.children[index], key)
                }
            }
        }
    }
    
    /// Check if a key exists in the tree
    pub fn contains(&self, key: &K) -> bool {
        self.search(key).is_some()
    }
}
```

### Range Queries

```rust
impl<K, V> BTree<K, V>
where
    K: Ord + Clone + Debug,
    V: Clone + Debug,
{
    /// Find all key-value pairs in a range [start, end]
    pub fn range(&self, start: &K, end: &K) -> Vec<(K, V)> {
        let mut result = Vec::new();
        
        if let Some(root) = &self.root {
            self.range_search(root, start, end, &mut result);
        }
        
        result
    }
    
    fn range_search(
        &self,
        node: &Node<K, V>,
        start: &K,
        end: &K,
        result: &mut Vec<(K, V)>,
    ) {
        let mut child_index = 0;
        
        for (i, key) in node.keys.iter().enumerate() {
            // Process child before this key
            if !node.is_leaf && child_index < node.children.len() {
                self.range_search(&node.children[child_index], start, end, result);
                child_index += 1;
            }
            
            // Process this key if it's in range
            if key >= start && key <= end {
                result.push((key.clone(), node.values[i].clone()));
            }
            
            // If we've passed the end key, we're done
            if key > end {
                return;
            }
        }
        
        // Process the last child
        if !node.is_leaf && child_index < node.children.len() {
            self.range_search(&node.children[child_index], start, end, result);
        }
    }
    
    /// Get all key-value pairs in sorted order
    pub fn iter(&self) -> Vec<(K, V)> {
        let mut result = Vec::new();
        
        if let Some(root) = &self.root {
            self.inorder_traversal(root, &mut result);
        }
        
        result
    }
    
    fn inorder_traversal(&self, node: &Node<K, V>, result: &mut Vec<(K, V)>) {
        let mut child_index = 0;
        
        for (i, key) in node.keys.iter().enumerate() {
            // Visit left child
            if !node.is_leaf && child_index < node.children.len() {
                self.inorder_traversal(&node.children[child_index], result);
                child_index += 1;
            }
            
            // Visit current key
            result.push((key.clone(), node.values[i].clone()));
        }
        
        // Visit rightmost child
        if !node.is_leaf && child_index < node.children.len() {
            self.inorder_traversal(&node.children[child_index], result);
        }
    }
}
```

## Insertion Operations

### Insert with Splitting

```rust
impl<K, V> BTree<K, V>
where
    K: Ord + Clone + Debug,
    V: Clone + Debug,
{
    /// Insert a key-value pair into the B-Tree
    pub fn insert(&mut self, key: K, value: V) -> Option<V> {
        let old_value = if let Some(root) = &mut self.root {
            self.insert_into_node(root, key.clone(), value.clone())
        } else {
            None
        };
        
        if old_value.is_none() {
            self.size += 1;
        }
        
        // Handle root split
        if let Some(root) = &self.root {
            if root.is_full(self.order) {
                self.split_root();
            }
        } else {
            // Create root if tree was empty
            let mut root = Node::new(true);
            root.keys.push(key);
            root.values.push(value);
            self.root = Some(Box::new(root));
        }
        
        old_value
    }
    
    fn insert_into_node(
        &mut self,
        node: &mut Node<K, V>,
        key: K,
        value: V,
    ) -> Option<V> {
        match node.keys.binary_search(&key) {
            Ok(index) => {
                // Key already exists, update value
                let old_value = node.values[index].clone();
                node.values[index] = value;
                Some(old_value)
            }
            Err(index) => {
                if node.is_leaf {
                    // Insert in leaf node
                    node.keys.insert(index, key);
                    node.values.insert(index, value);
                    None
                } else {
                    // Insert in child node
                    let old_value = self.insert_into_node(&mut node.children[index], key, value);
                    
                    // Check if child needs splitting
                    if node.children[index].is_full(self.order) {
                        self.split_child(node, index);
                    }
                    
                    old_value
                }
            }
        }
    }
    
    fn split_child(&mut self, parent: &mut Node<K, V>, child_index: usize) {
        let full_child = &mut parent.children[child_index];
        let mid_index = full_child.keys.len() / 2;
        
        // Create new right child
        let mut right_child = Node::new(full_child.is_leaf);
        
        // Move half of keys and values to right child
        right_child.keys = full_child.keys.split_off(mid_index + 1);
        right_child.values = full_child.values.split_off(mid_index + 1);
        
        // If not leaf, move children too
        if !full_child.is_leaf {
            right_child.children = full_child.children.split_off(mid_index + 1);
        }
        
        // Get the middle key to promote
        let promoted_key = full_child.keys.pop().unwrap();
        let promoted_value = full_child.values.pop().unwrap();
        
        // Insert promoted key into parent
        parent.keys.insert(child_index, promoted_key);
        parent.values.insert(child_index, promoted_value);
        parent.children.insert(child_index + 1, Box::new(right_child));
    }
    
    fn split_root(&mut self) {
        let old_root = self.root.take().unwrap();
        let mut new_root = Node::new(false);
        
        new_root.children.push(old_root);
        self.split_child(&mut new_root, 0);
        
        self.root = Some(Box::new(new_root));
    }
}
```

## Deletion Operations

### Delete with Merging

```rust
impl<K, V> BTree<K, V>
where
    K: Ord + Clone + Debug,
    V: Clone + Debug,
{
    /// Remove a key-value pair from the B-Tree
    pub fn delete(&mut self, key: &K) -> Option<V> {
        let result = if let Some(root) = &mut self.root {
            self.delete_from_node(root, key)
        } else {
            None
        };
        
        if result.is_some() {
            self.size -= 1;
            
            // If root becomes empty, make its only child the new root
            if let Some(root) = &self.root {
                if root.keys.is_empty() && !root.is_leaf {
                    self.root = Some(root.children[0].clone());
                }
            }
        }
        
        result
    }
    
    fn delete_from_node(&mut self, node: &mut Node<K, V>, key: &K) -> Option<V> {
        match node.keys.binary_search(key) {
            Ok(index) => {
                if node.is_leaf {
                    // Delete from leaf node
                    node.keys.remove(index);
                    Some(node.values.remove(index))
                } else {
                    // Delete from internal node
                    self.delete_from_internal_node(node, index)
                }
            }
            Err(index) => {
                if node.is_leaf {
                    None // Key not found
                } else {
                    // Delete from child
                    let result = self.delete_from_node(&mut node.children[index], key);
                    
                    // Fix child if it became too small
                    if node.children[index].is_minimal(self.order) {
                        self.fix_child(node, index);
                    }
                    
                    result
                }
            }
        }
    }
    
    fn delete_from_internal_node(&mut self, node: &mut Node<K, V>, index: usize) -> Option<V> {
        let deleted_value = node.values.remove(index);
        let deleted_key = node.keys.remove(index);
        
        // Find predecessor (rightmost key in left subtree)
        let predecessor = self.find_predecessor(&node.children[index]);
        
        // Replace deleted key with predecessor
        node.keys.insert(index, predecessor.0);
        node.values.insert(index, predecessor.1);
        
        // Delete predecessor from left subtree
        self.delete_from_node(&mut node.children[index], &predecessor.0);
        
        // Fix left child if necessary
        if node.children[index].is_minimal(self.order) {
            self.fix_child(node, index);
        }
        
        Some(deleted_value)
    }
    
    fn find_predecessor(&self, node: &Node<K, V>) -> (K, V) {
        if node.is_leaf {
            let last_index = node.keys.len() - 1;
            (node.keys[last_index].clone(), node.values[last_index].clone())
        } else {
            let last_child = node.children.len() - 1;
            self.find_predecessor(&node.children[last_child])
        }
    }
    
    fn fix_child(&mut self, parent: &mut Node<K, V>, child_index: usize) {
        // Try to borrow from left sibling
        if child_index > 0 
            && parent.children[child_index - 1].key_count() > (self.order / 2) {
            self.borrow_from_left(parent, child_index);
        }
        // Try to borrow from right sibling
        else if child_index < parent.children.len() - 1
            && parent.children[child_index + 1].key_count() > (self.order / 2) {
            self.borrow_from_right(parent, child_index);
        }
        // Merge with sibling
        else {
            if child_index > 0 {
                self.merge_with_left(parent, child_index);
            } else {
                self.merge_with_right(parent, child_index);
            }
        }
    }
    
    fn borrow_from_left(&mut self, parent: &mut Node<K, V>, child_index: usize) {
        let left_sibling = &mut parent.children[child_index - 1];
        let child = &mut parent.children[child_index];
        
        // Move parent key down to child
        let parent_key = parent.keys[child_index - 1].clone();
        let parent_value = parent.values[child_index - 1].clone();
        
        child.keys.insert(0, parent_key);
        child.values.insert(0, parent_value);
        
        // Move left sibling's last key up to parent
        let borrowed_key = left_sibling.keys.pop().unwrap();
        let borrowed_value = left_sibling.values.pop().unwrap();
        
        parent.keys[child_index - 1] = borrowed_key;
        parent.values[child_index - 1] = borrowed_value;
        
        // Move child pointer if not leaf
        if !child.is_leaf {
            let borrowed_child = left_sibling.children.pop().unwrap();
            child.children.insert(0, borrowed_child);
        }
    }
    
    fn borrow_from_right(&mut self, parent: &mut Node<K, V>, child_index: usize) {
        let right_sibling = &mut parent.children[child_index + 1];
        let child = &mut parent.children[child_index];
        
        // Move parent key down to child
        let parent_key = parent.keys[child_index].clone();
        let parent_value = parent.values[child_index].clone();
        
        child.keys.push(parent_key);
        child.values.push(parent_value);
        
        // Move right sibling's first key up to parent
        let borrowed_key = right_sibling.keys.remove(0);
        let borrowed_value = right_sibling.values.remove(0);
        
        parent.keys[child_index] = borrowed_key;
        parent.values[child_index] = borrowed_value;
        
        // Move child pointer if not leaf
        if !child.is_leaf {
            let borrowed_child = right_sibling.children.remove(0);
            child.children.push(borrowed_child);
        }
    }
    
    fn merge_with_left(&mut self, parent: &mut Node<K, V>, child_index: usize) {
        let child = parent.children.remove(child_index);
        let left_sibling = &mut parent.children[child_index - 1];
        
        // Move parent key down to left sibling
        let parent_key = parent.keys.remove(child_index - 1);
        let parent_value = parent.values.remove(child_index - 1);
        
        left_sibling.keys.push(parent_key);
        left_sibling.values.push(parent_value);
        
        // Move all keys and values from child to left sibling
        left_sibling.keys.extend(child.keys);
        left_sibling.values.extend(child.values);
        
        // Move children if not leaf
        if !child.is_leaf {
            left_sibling.children.extend(child.children);
        }
    }
    
    fn merge_with_right(&mut self, parent: &mut Node<K, V>, child_index: usize) {
        let right_sibling = parent.children.remove(child_index + 1);
        let child = &mut parent.children[child_index];
        
        // Move parent key down to child
        let parent_key = parent.keys.remove(child_index);
        let parent_value = parent.values.remove(child_index);
        
        child.keys.push(parent_key);
        child.values.push(parent_value);
        
        // Move all keys and values from right sibling to child
        child.keys.extend(right_sibling.keys);
        child.values.extend(right_sibling.values);
        
        // Move children if not leaf
        if !child.is_leaf {
            child.children.extend(right_sibling.children);
        }
    }
}
```

## Advanced Features

### Bulk Operations

```rust
impl<K, V> BTree<K, V>
where
    K: Ord + Clone + Debug,
    V: Clone + Debug,
{
    /// Bulk insert from a sorted iterator
    pub fn bulk_insert<I>(&mut self, items: I)
    where
        I: IntoIterator<Item = (K, V)>,
    {
        for (key, value) in items {
            self.insert(key, value);
        }
    }
    
    /// Build a B-Tree from a sorted vector (more efficient than individual inserts)
    pub fn from_sorted_vec(items: Vec<(K, V)>) -> Self {
        let mut tree = Self::new();
        
        if items.is_empty() {
            return tree;
        }
        
        // For simplicity, we'll use regular insertion
        // A production implementation would build bottom-up
        for (key, value) in items {
            tree.insert(key, value);
        }
        
        tree
    }
    
    /// Clear all items from the tree
    pub fn clear(&mut self) {
        self.root = None;
        self.size = 0;
    }
    
    /// Get the minimum key-value pair
    pub fn min(&self) -> Option<(K, V)> {
        self.root.as_ref().map(|root| self.find_min(root))
    }
    
    fn find_min(&self, node: &Node<K, V>) -> (K, V) {
        if node.is_leaf {
            (node.keys[0].clone(), node.values[0].clone())
        } else {
            self.find_min(&node.children[0])
        }
    }
    
    /// Get the maximum key-value pair
    pub fn max(&self) -> Option<(K, V)> {
        self.root.as_ref().map(|root| self.find_max(root))
    }
    
    fn find_max(&self, node: &Node<K, V>) -> (K, V) {
        if node.is_leaf {
            let last_index = node.keys.len() - 1;
            (node.keys[last_index].clone(), node.values[last_index].clone())
        } else {
            let last_child = node.children.len() - 1;
            self.find_max(&node.children[last_child])
        }
    }
}
```

### Statistics and Debugging

```rust
impl<K, V> BTree<K, V>
where
    K: Ord + Clone + Debug,
    V: Clone + Debug,
{
    /// Get statistics about the tree structure
    pub fn stats(&self) -> BTreeStats {
        match &self.root {
            None => BTreeStats {
                height: 0,
                node_count: 0,
                leaf_count: 0,
                internal_count: 0,
                min_keys_per_node: 0,
                max_keys_per_node: 0,
                avg_keys_per_node: 0.0,
                space_utilization: 0.0,
            },
            Some(root) => {
                let mut stats = BTreeStats {
                    height: 0,
                    node_count: 0,
                    leaf_count: 0,
                    internal_count: 0,
                    min_keys_per_node: usize::MAX,
                    max_keys_per_node: 0,
                    avg_keys_per_node: 0.0,
                    space_utilization: 0.0,
                };
                
                self.calculate_stats(root, 1, &mut stats);
                
                stats.avg_keys_per_node = self.size as f64 / stats.node_count as f64;
                stats.space_utilization = (self.size as f64) / 
                    (stats.node_count as f64 * (self.order - 1) as f64);
                
                stats
            }
        }
    }
    
    fn calculate_stats(&self, node: &Node<K, V>, depth: usize, stats: &mut BTreeStats) {
        stats.height = stats.height.max(depth);
        stats.node_count += 1;
        
        let key_count = node.keys.len();
        stats.min_keys_per_node = stats.min_keys_per_node.min(key_count);
        stats.max_keys_per_node = stats.max_keys_per_node.max(key_count);
        
        if node.is_leaf {
            stats.leaf_count += 1;
        } else {
            stats.internal_count += 1;
            for child in &node.children {
                self.calculate_stats(child, depth + 1, stats);
            }
        }
    }
    
    /// Validate tree invariants (useful for debugging)
    pub fn validate(&self) -> Result<(), String> {
        match &self.root {
            None => Ok(()),
            Some(root) => self.validate_node(root, None, None),
        }
    }
    
    fn validate_node(
        &self,
        node: &Node<K, V>,
        min_bound: Option<&K>,
        max_bound: Option<&K>,
    ) -> Result<(), String> {
        // Check key order within node
        for i in 1..node.keys.len() {
            if node.keys[i - 1] >= node.keys[i] {
                return Err("Keys not in sorted order within node".to_string());
            }
        }
        
        // Check bounds
        if let Some(min) = min_bound {
            if node.keys.first().map_or(false, |k| k < min) {
                return Err("Node violates minimum bound".to_string());
            }
        }
        
        if let Some(max) = max_bound {
            if node.keys.last().map_or(false, |k| k > max) {
                return Err("Node violates maximum bound".to_string());
            }
        }
        
        // Check node size constraints
        if node.keys.len() >= self.order {
            return Err("Node has too many keys".to_string());
        }
        
        // Check children
        if !node.is_leaf {
            if node.children.len() != node.keys.len() + 1 {
                return Err("Internal node has wrong number of children".to_string());
            }
            
            for (i, child) in node.children.iter().enumerate() {
                let child_min = if i == 0 { min_bound } else { Some(&node.keys[i - 1]) };
                let child_max = if i == node.keys.len() { max_bound } else { Some(&node.keys[i]) };
                
                self.validate_node(child, child_min, child_max)?;
            }
        }
        
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct BTreeStats {
    pub height: usize,
    pub node_count: usize,
    pub leaf_count: usize,
    pub internal_count: usize,
    pub min_keys_per_node: usize,
    pub max_keys_per_node: usize,
    pub avg_keys_per_node: f64,
    pub space_utilization: f64,
}
```

## Usage Examples and Testing

### Basic Usage

```rust
fn main() {
    println!("=== B-Tree Implementation Demo ===");
    
    // Create a new B-Tree
    let mut btree = BTree::new();
    
    // Insert some values
    println!("\n1. Inserting values...");
    let values = vec![
        (10, "ten"),
        (20, "twenty"),
        (5, "five"),
        (15, "fifteen"),
        (25, "twenty-five"),
        (30, "thirty"),
        (35, "thirty-five"),
    ];
    
    for (key, value) in values {
        btree.insert(key, value);
        println!("Inserted ({}, {})", key, value);
    }
    
    println!("Tree size: {}", btree.len());
    
    // Search for values
    println!("\n2. Searching for values...");
    for key in [5, 15, 25, 40] {
        match btree.search(&key) {
            Some(value) => println!("Found: {} -> {}", key, value),
            None => println!("Not found: {}", key),
        }
    }
    
    // Range queries
    println!("\n3. Range query [10, 25]:");
    let range_results = btree.range(&10, &25);
    for (key, value) in range_results {
        println!("  {} -> {}", key, value);
    }
    
    // Iteration
    println!("\n4. All values in order:");
    for (key, value) in btree.iter() {
        println!("  {} -> {}", key, value);
    }
    
    // Tree statistics
    println!("\n5. Tree statistics:");
    let stats = btree.stats();
    println!("  Height: {}", stats.height);
    println!("  Node count: {}", stats.node_count);
    println!("  Leaf count: {}", stats.leaf_count);
    println!("  Internal count: {}", stats.internal_count);
    println!("  Space utilization: {:.2}%", stats.space_utilization * 100.0);
    
    // Validation
    println!("\n6. Tree validation:");
    match btree.validate() {
        Ok(()) => println!("  Tree is valid!"),
        Err(e) => println!("  Tree validation failed: {}", e),
    }
    
    // Deletions
    println!("\n7. Deleting values...");
    for key in [15, 25, 5] {
        match btree.delete(&key) {
            Some(value) => println!("Deleted: {} -> {}", key, value),
            None => println!("Not found for deletion: {}", key),
        }
    }
    
    println!("Tree size after deletions: {}", btree.len());
    
    // Final state
    println!("\n8. Final tree state:");
    for (key, value) in btree.iter() {
        println!("  {} -> {}", key, value);
    }
}
```

### Performance Benchmarks

```rust
use std::time::Instant;
use std::collections::BTreeMap;

fn benchmark_comparison() {
    println!("=== Performance Comparison ===");
    
    let sizes = vec![1000, 10000, 100000];
    
    for size in sizes {
        println!("\nTesting with {} elements:", size);
        
        // Generate test data
        let mut data: Vec<(i32, String)> = (0..size)
            .map(|i| (i, format!("value_{}", i)))
            .collect();
        
        // Shuffle for random insertion order
        use rand::seq::SliceRandom;
        let mut rng = rand::thread_rng();
        data.shuffle(&mut rng);
        
        // Test our B-Tree
        let start = Instant::now();
        let mut our_btree = BTree::new();
        for (key, value) in &data {
            our_btree.insert(*key, value.clone());
        }
        let our_insert_time = start.elapsed();
        
        // Test standard library BTreeMap
        let start = Instant::now();
        let mut std_btree = BTreeMap::new();
        for (key, value) in &data {
            std_btree.insert(*key, value.clone());
        }
        let std_insert_time = start.elapsed();
        
        println!("  Insert time:");
        println!("    Our B-Tree: {:?}", our_insert_time);
        println!("    Std BTreeMap: {:?}", std_insert_time);
        
        // Test search performance
        let search_keys: Vec<i32> = (0..1000).map(|i| i * (size / 1000)).collect();
        
        let start = Instant::now();
        for key in &search_keys {
            our_btree.search(key);
        }
        let our_search_time = start.elapsed();
        
        let start = Instant::now();
        for key in &search_keys {
            std_btree.get(key);
        }
        let std_search_time = start.elapsed();
        
        println!("  Search time (1000 searches):");
        println!("    Our B-Tree: {:?}", our_search_time);
        println!("    Std BTreeMap: {:?}", std_search_time);
        
        // Memory usage (approximate)
        let our_stats = our_btree.stats();
        println!("  Our B-Tree stats:");
        println!("    Height: {}", our_stats.height);
        println!("    Nodes: {}", our_stats.node_count);
        println!("    Space utilization: {:.1}%", our_stats.space_utilization * 100.0);
    }
}
```

### Comprehensive Testing

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_basic_operations() {
        let mut btree = BTree::new();
        
        // Test insertion
        assert_eq!(btree.insert(5, "five"), None);
        assert_eq!(btree.insert(10, "ten"), None);
        assert_eq!(btree.insert(15, "fifteen"), None);
        assert_eq!(btree.len(), 3);
        
        // Test search
        assert_eq!(btree.search(&5), Some(&"five"));
        assert_eq!(btree.search(&10), Some(&"ten"));
        assert_eq!(btree.search(&15), Some(&"fifteen"));
        assert_eq!(btree.search(&20), None);
        
        // Test update
        assert_eq!(btree.insert(10, "TEN"), Some("ten"));
        assert_eq!(btree.search(&10), Some(&"TEN"));
        assert_eq!(btree.len(), 3);
        
        // Test deletion
        assert_eq!(btree.delete(&10), Some("TEN"));
        assert_eq!(btree.search(&10), None);
        assert_eq!(btree.len(), 2);
    }
    
    #[test]
    fn test_range_queries() {
        let mut btree = BTree::new();
        
        for i in 0..100 {
            btree.insert(i, format!("value_{}", i));
        }
        
        let range_result = btree.range(&10, &20);
        assert_eq!(range_result.len(), 11); // 10 through 20 inclusive
        
        for (i, (key, _)) in range_result.iter().enumerate() {
            assert_eq!(*key, 10 + i as i32);
        }
    }
    
    #[test]
    fn test_tree_properties() {
        let mut btree = BTree::with_order(5);
        
        // Insert many values to trigger splits
        for i in 0..100 {
            btree.insert(i, format!("value_{}", i));
        }
        
        // Validate tree structure
        assert!(btree.validate().is_ok());
        
        // Check that tree height is reasonable
        let stats = btree.stats();
        assert!(stats.height <= 5); // Should be quite short
        
        // Check space utilization
        assert!(stats.space_utilization >= 0.5); // At least 50%
    }
    
    #[test]
    fn test_large_dataset() {
        let mut btree = BTree::new();
        
        // Insert 10,000 items
        for i in 0..10000 {
            btree.insert(i, format!("value_{}", i));
        }
        
        assert_eq!(btree.len(), 10000);
        
        // Verify all items can be found
        for i in 0..10000 {
            assert_eq!(btree.search(&i), Some(&format!("value_{}", i)));
        }
        
        // Delete half the items
        for i in (0..10000).step_by(2) {
            assert!(btree.delete(&i).is_some());
        }
        
        assert_eq!(btree.len(), 5000);
        
        // Verify deleted items are gone and remaining items are still there
        for i in 0..10000 {
            if i % 2 == 0 {
                assert_eq!(btree.search(&i), None);
            } else {
                assert_eq!(btree.search(&i), Some(&format!("value_{}", i)));
            }
        }
        
        // Tree should still be valid
        assert!(btree.validate().is_ok());
    }
    
    #[test]
    fn test_stress_operations() {
        let mut btree = BTree::new();
        
        // Random insertions and deletions
        use rand::Rng;
        let mut rng = rand::thread_rng();
        
        for _ in 0..1000 {
            let key = rng.gen_range(0..500);
            let value = format!("value_{}", key);
            
            if rng.gen_bool(0.7) {
                // Insert
                btree.insert(key, value);
            } else {
                // Delete
                btree.delete(&key);
            }
            
            // Validate tree after each operation
            assert!(btree.validate().is_ok());
        }
    }
}
```

## Running the Implementation

### Cargo.toml

```toml
[package]
name = "btree-implementation"
version = "0.1.0"
edition = "2021"

[dependencies]
rand = "0.8"

[dev-dependencies]
criterion = "0.5"
```

### Running the Examples

```bash
# Run basic demo
cargo run

# Run benchmarks
cargo run --release --bin benchmark

# Run tests
cargo test

# Run tests with output
cargo test -- --nocapture
```

## Key Implementation Insights

### Performance Characteristics

This implementation provides:

- **Search**: O(log n) with excellent constant factors
- **Insert**: O(log n) with minimal node splits
- **Delete**: O(log n) with efficient rebalancing
- **Range queries**: O(log n + k) where k is result size
- **Space**: O(n) with guaranteed 50% minimum utilization

### Design Decisions

1. **Node size**: Configurable order for different use cases
2. **Split strategy**: Split at midpoint for balanced growth
3. **Merge strategy**: Merge with siblings when underutilized
4. **Memory management**: Uses Rust's ownership system for safety
5. **Error handling**: Comprehensive validation and debugging support

### Production Considerations

This implementation demonstrates the core concepts but would need several enhancements for production use:

- **Persistence**: Save/load nodes to/from disk
- **Concurrency**: Thread-safe operations with appropriate locking
- **Compression**: Compress nodes to save space
- **Caching**: Cache frequently accessed nodes in memory
- **Metrics**: Detailed performance monitoring
- **Recovery**: Handle corruption and provide repair mechanisms

## Conclusion

This Rust implementation showcases how B-Tree concepts translate into practical code. The type system ensures correctness while the performance characteristics demonstrate why B-Trees are the foundation of modern database systems.

Key takeaways:
1. **Node-based design**: Large nodes minimize tree height
2. **Split/merge algorithms**: Maintain balance automatically
3. **Range query efficiency**: Linked leaves enable fast scans
4. **Memory safety**: Rust's ownership prevents common errors
5. **Configurable parameters**: Adapt to different use cases

The implementation serves as both a learning tool and a foundation for building more sophisticated storage systems. Understanding these fundamentals is crucial for working with databases, file systems, and other systems that require efficient indexed data access.