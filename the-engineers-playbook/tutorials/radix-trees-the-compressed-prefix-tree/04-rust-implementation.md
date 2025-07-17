# Rust Implementation: A Complete Radix Tree

This implementation demonstrates a full-featured radix tree in Rust, showcasing the key concepts through clean, idiomatic code.

## Core Data Structure

```rust
use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct RadixTree<T> {
    root: RadixNode<T>,
}

#[derive(Debug, Clone)]
struct RadixNode<T> {
    // The compressed path stored on the edge leading to this node
    prefix: String,
    // Optional value if this node represents a complete key
    value: Option<T>,
    // Children nodes, indexed by their first character
    children: HashMap<char, RadixNode<T>>,
}

impl<T> RadixNode<T> {
    fn new(prefix: String) -> Self {
        Self {
            prefix,
            value: None,
            children: HashMap::new(),
        }
    }
    
    fn new_with_value(prefix: String, value: T) -> Self {
        Self {
            prefix,
            value: Some(value),
            children: HashMap::new(),
        }
    }
}
```

## Core Operations

### Initialization

```rust
impl<T> RadixTree<T> {
    pub fn new() -> Self {
        Self {
            root: RadixNode::new(String::new()),
        }
    }
}

impl<T> Default for RadixTree<T> {
    fn default() -> Self {
        Self::new()
    }
}
```

### Insert Operation

The insert operation is the most complex, requiring path splitting when prefixes partially match:

```rust
impl<T> RadixTree<T> {
    pub fn insert(&mut self, key: &str, value: T) {
        self.insert_recursive(&mut self.root, key, value);
    }
    
    fn insert_recursive(&mut self, node: &mut RadixNode<T>, key: &str, value: T) {
        // Find how much of the key matches the node's prefix
        let common_length = find_common_prefix(&node.prefix, key);
        
        match common_length {
            // No common prefix - this shouldn't happen at root, but handle gracefully
            0 if node.prefix.is_empty() => {
                // We're at root with empty prefix
                let first_char = key.chars().next().unwrap();
                
                if let Some(child) = node.children.get_mut(&first_char) {
                    // Delegate to existing child
                    self.insert_recursive(child, key, value);
                } else {
                    // Create new child
                    let new_child = RadixNode::new_with_value(key.to_string(), value);
                    node.children.insert(first_char, new_child);
                }
            }
            
            // Partial match - need to split the node
            partial if partial < node.prefix.len() => {
                // Split the current node
                let old_prefix = node.prefix.clone();
                let old_value = node.value.take();
                let old_children = std::mem::take(&mut node.children);
                
                // Update current node with common prefix
                node.prefix = old_prefix[..partial].to_string();
                
                // Create child for the old suffix
                let old_suffix = &old_prefix[partial..];
                let old_first_char = old_suffix.chars().next().unwrap();
                let old_child = RadixNode {
                    prefix: old_suffix.to_string(),
                    value: old_value,
                    children: old_children,
                };
                node.children.insert(old_first_char, old_child);
                
                // Handle the remaining key
                let remaining_key = &key[partial..];
                if remaining_key.is_empty() {
                    // Key ends at split point
                    node.value = Some(value);
                } else {
                    // Key continues beyond split point
                    let new_first_char = remaining_key.chars().next().unwrap();
                    let new_child = RadixNode::new_with_value(remaining_key.to_string(), value);
                    node.children.insert(new_first_char, new_child);
                }
            }
            
            // Complete match of node's prefix
            complete if complete == node.prefix.len() => {
                let remaining_key = &key[complete..];
                
                if remaining_key.is_empty() {
                    // Key ends exactly at this node
                    node.value = Some(value);
                } else {
                    // Key continues beyond this node
                    let first_char = remaining_key.chars().next().unwrap();
                    
                    if let Some(child) = node.children.get_mut(&first_char) {
                        self.insert_recursive(child, remaining_key, value);
                    } else {
                        let new_child = RadixNode::new_with_value(remaining_key.to_string(), value);
                        node.children.insert(first_char, new_child);
                    }
                }
            }
            
            _ => unreachable!("Common length cannot exceed node prefix length"),
        }
    }
}

// Helper function to find common prefix length
fn find_common_prefix(a: &str, b: &str) -> usize {
    a.chars()
        .zip(b.chars())
        .take_while(|(ca, cb)| ca == cb)
        .count()
}
```

### Search Operation

```rust
impl<T> RadixTree<T> {
    pub fn get(&self, key: &str) -> Option<&T> {
        self.get_recursive(&self.root, key)
    }
    
    fn get_recursive(&self, node: &RadixNode<T>, key: &str) -> Option<&T> {
        // Check if key matches this node's prefix
        if !key.starts_with(&node.prefix) {
            return None;
        }
        
        let remaining_key = &key[node.prefix.len()..];
        
        if remaining_key.is_empty() {
            // Key ends at this node
            node.value.as_ref()
        } else {
            // Key continues - look for matching child
            let first_char = remaining_key.chars().next().unwrap();
            if let Some(child) = node.children.get(&first_char) {
                self.get_recursive(child, remaining_key)
            } else {
                None
            }
        }
    }
    
    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }
}
```

### Prefix Search Operations

```rust
impl<T> RadixTree<T> {
    // Find all keys that start with the given prefix
    pub fn keys_with_prefix(&self, prefix: &str) -> Vec<String> {
        let mut results = Vec::new();
        if let Some(node) = self.find_node_for_prefix(prefix) {
            self.collect_keys(node, prefix, &mut results);
        }
        results
    }
    
    fn find_node_for_prefix(&self, prefix: &str) -> Option<&RadixNode<T>> {
        let mut current = &self.root;
        let mut remaining = prefix;
        
        loop {
            // Check if remaining prefix matches current node's prefix
            let common_len = find_common_prefix(&current.prefix, remaining);
            
            if common_len < current.prefix.len() {
                // Partial match - prefix doesn't exist in tree
                return None;
            }
            
            remaining = &remaining[common_len..];
            
            if remaining.is_empty() {
                // Found the node representing our prefix
                return Some(current);
            }
            
            // Move to appropriate child
            let first_char = remaining.chars().next().unwrap();
            if let Some(child) = current.children.get(&first_char) {
                current = child;
            } else {
                return None;
            }
        }
    }
    
    fn collect_keys(&self, node: &RadixNode<T>, current_prefix: &str, results: &mut Vec<String>) {
        let full_prefix = format!("{}{}", current_prefix, node.prefix);
        
        // If this node has a value, it represents a complete key
        if node.value.is_some() {
            results.push(full_prefix.clone());
        }
        
        // Recurse into children
        for child in node.children.values() {
            self.collect_keys(child, &full_prefix, results);
        }
    }
}
```

## Usage Examples

```rust
fn main() {
    let mut tree = RadixTree::new();
    
    // Insert some programming terms
    tree.insert("developer", "A person who writes code");
    tree.insert("development", "The process of creating software");
    tree.insert("devotion", "Dedication to a cause");
    tree.insert("device", "A piece of hardware");
    tree.insert("design", "The planning phase of creation");
    
    // Basic lookups
    println!("developer: {:?}", tree.get("developer"));
    println!("development: {:?}", tree.get("development"));
    println!("nonexistent: {:?}", tree.get("nonexistent"));
    
    // Prefix searches
    println!("Keys starting with 'dev':");
    for key in tree.keys_with_prefix("dev") {
        println!("  {}", key);
    }
    
    // Check containment
    println!("Contains 'design': {}", tree.contains_key("design"));
    println!("Contains 'designer': {}", tree.contains_key("designer"));
}
```

## Performance Characteristics

### Time Complexity
- **Insert**: O(k) where k is the key length
- **Search**: O(k) where k is the key length  
- **Prefix search**: O(k + m) where k is prefix length, m is number of results

### Space Complexity
- **Best case**: O(n) where n is number of unique keys
- **Worst case**: O(n × k) where k is average key length
- **Typical case**: Significant compression due to shared prefixes

## Testing the Implementation

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_basic_operations() {
        let mut tree = RadixTree::new();
        
        tree.insert("test", 42);
        tree.insert("testing", 100);
        tree.insert("tester", 200);
        
        assert_eq!(tree.get("test"), Some(&42));
        assert_eq!(tree.get("testing"), Some(&100));
        assert_eq!(tree.get("tester"), Some(&200));
        assert_eq!(tree.get("nonexistent"), None);
    }
    
    #[test]
    fn test_prefix_splitting() {
        let mut tree = RadixTree::new();
        
        tree.insert("test", 1);
        tree.insert("tea", 2);
        
        assert_eq!(tree.get("test"), Some(&1));
        assert_eq!(tree.get("tea"), Some(&2));
        assert_eq!(tree.get("te"), None);
    }
    
    #[test]
    fn test_prefix_search() {
        let mut tree = RadixTree::new();
        
        tree.insert("apple", 1);
        tree.insert("application", 2);
        tree.insert("apply", 3);
        tree.insert("banana", 4);
        
        let mut results = tree.keys_with_prefix("app");
        results.sort();
        
        assert_eq!(results, vec!["apple", "application", "apply"]);
    }
}
```

## Key Implementation Insights

### Path Compression Strategy
The implementation stores compressed paths as `String` objects on edges, not in nodes. This aligns with the radix tree philosophy of minimizing nodes.

### Dynamic Restructuring
The most complex aspect is handling insertions that require splitting existing compressed paths. The implementation carefully preserves the tree structure while reorganizing nodes.

### Memory Efficiency
Using `HashMap<char, RadixNode<T>>` for children provides O(1) child lookup while maintaining the compressed structure. In production, this could be optimized further with arrays for small alphabets.

This implementation demonstrates all the key concepts of radix trees while remaining readable and maintainable—exactly what you'd want in production code.