# Rust Implementation: A Complete Trie with Advanced Features

## Overview

We'll implement a production-quality trie in Rust that demonstrates:
- Memory-safe pointer management
- Generic support for different character sets
- Advanced features like frequency tracking and fuzzy search
- Thread-safe operations
- Performance optimizations

This implementation showcases how Rust's ownership system makes trie implementation both safe and efficient.

## Core Data Structures

```rust
use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::fmt;

#[derive(Debug, Clone)]
pub struct TrieNode {
    children: HashMap<char, Arc<RwLock<TrieNode>>>,
    is_end_of_word: bool,
    word: Option<String>,
    frequency: u32,
}

impl TrieNode {
    pub fn new() -> Self {
        Self {
            children: HashMap::new(),
            is_end_of_word: false,
            word: None,
            frequency: 0,
        }
    }
    
    pub fn is_leaf(&self) -> bool {
        self.children.is_empty()
    }
    
    pub fn child_count(&self) -> usize {
        self.children.len()
    }
}

#[derive(Debug)]
pub struct Trie {
    root: Arc<RwLock<TrieNode>>,
    word_count: usize,
    case_sensitive: bool,
}

impl Default for Trie {
    fn default() -> Self {
        Self::new()
    }
}
```

## Basic Implementation

```rust
impl Trie {
    pub fn new() -> Self {
        Self {
            root: Arc::new(RwLock::new(TrieNode::new())),
            word_count: 0,
            case_sensitive: false,
        }
    }
    
    pub fn with_case_sensitivity(case_sensitive: bool) -> Self {
        Self {
            root: Arc::new(RwLock::new(TrieNode::new())),
            word_count: 0,
            case_sensitive,
        }
    }
    
    fn normalize_word(&self, word: &str) -> String {
        if self.case_sensitive {
            word.to_string()
        } else {
            word.to_lowercase()
        }
    }
    
    pub fn insert(&mut self, word: &str) -> bool {
        self.insert_with_frequency(word, 1)
    }
    
    pub fn insert_with_frequency(&mut self, word: &str, frequency: u32) -> bool {
        let normalized_word = self.normalize_word(word);
        let mut current = self.root.clone();
        
        // Navigate/create path for each character
        for ch in normalized_word.chars() {
            let next = {
                let current_node = current.read().unwrap();
                current_node.children.get(&ch).cloned()
            };
            
            match next {
                Some(node) => current = node,
                None => {
                    let new_node = Arc::new(RwLock::new(TrieNode::new()));
                    {
                        let mut current_node = current.write().unwrap();
                        current_node.children.insert(ch, new_node.clone());
                    }
                    current = new_node;
                }
            }
        }
        
        // Mark end of word and update frequency
        let mut current_node = current.write().unwrap();
        let is_new_word = !current_node.is_end_of_word;
        
        current_node.is_end_of_word = true;
        current_node.word = Some(word.to_string());
        current_node.frequency += frequency;
        
        if is_new_word {
            self.word_count += 1;
        }
        
        is_new_word
    }
    
    pub fn search(&self, word: &str) -> bool {
        self.find_node(&self.normalize_word(word))
            .map(|node| {
                let node = node.read().unwrap();
                node.is_end_of_word
            })
            .unwrap_or(false)
    }
    
    pub fn starts_with(&self, prefix: &str) -> bool {
        self.find_node(&self.normalize_word(prefix)).is_some()
    }
    
    fn find_node(&self, word: &str) -> Option<Arc<RwLock<TrieNode>>> {
        let mut current = self.root.clone();
        
        for ch in word.chars() {
            let next = {
                let current_node = current.read().unwrap();
                current_node.children.get(&ch).cloned()
            };
            
            match next {
                Some(node) => current = node,
                None => return None,
            }
        }
        
        Some(current)
    }
}
```

## Advanced Search Operations

```rust
#[derive(Debug, Clone)]
pub struct SearchResult {
    pub word: String,
    pub frequency: u32,
    pub edit_distance: Option<u32>,
}

impl Trie {
    pub fn get_suggestions(&self, prefix: &str, limit: usize) -> Vec<SearchResult> {
        let normalized_prefix = self.normalize_word(prefix);
        
        match self.find_node(&normalized_prefix) {
            Some(prefix_node) => {
                let mut results = Vec::new();
                self.collect_words(prefix_node, &normalized_prefix, &mut results);
                
                // Sort by frequency (descending) then alphabetically
                results.sort_by(|a, b| {
                    b.frequency.cmp(&a.frequency)
                        .then_with(|| a.word.cmp(&b.word))
                });
                
                results.truncate(limit);
                results
            }
            None => Vec::new(),
        }
    }
    
    fn collect_words(
        &self,
        node: Arc<RwLock<TrieNode>>,
        prefix: &str,
        results: &mut Vec<SearchResult>,
    ) {
        let node_guard = node.read().unwrap();
        
        if node_guard.is_end_of_word {
            if let Some(word) = &node_guard.word {
                results.push(SearchResult {
                    word: word.clone(),
                    frequency: node_guard.frequency,
                    edit_distance: None,
                });
            }
        }
        
        for (ch, child_node) in &node_guard.children {
            let new_prefix = format!("{}{}", prefix, ch);
            self.collect_words(child_node.clone(), &new_prefix, results);
        }
    }
    
    pub fn fuzzy_search(&self, query: &str, max_distance: u32, limit: usize) -> Vec<SearchResult> {
        let normalized_query = self.normalize_word(query);
        let mut results = Vec::new();
        
        self.fuzzy_collect(
            self.root.clone(),
            "",
            &normalized_query,
            max_distance,
            &mut results,
        );
        
        // Sort by edit distance then frequency
        results.sort_by(|a, b| {
            a.edit_distance.unwrap_or(0).cmp(&b.edit_distance.unwrap_or(0))
                .then_with(|| b.frequency.cmp(&a.frequency))
        });
        
        results.truncate(limit);
        results
    }
    
    fn fuzzy_collect(
        &self,
        node: Arc<RwLock<TrieNode>>,
        current_word: &str,
        target: &str,
        max_distance: u32,
        results: &mut Vec<SearchResult>,
    ) {
        let node_guard = node.read().unwrap();
        
        if node_guard.is_end_of_word {
            let distance = edit_distance(current_word, target);
            if distance <= max_distance {
                if let Some(word) = &node_guard.word {
                    results.push(SearchResult {
                        word: word.clone(),
                        frequency: node_guard.frequency,
                        edit_distance: Some(distance),
                    });
                }
            }
        }
        
        // Early termination: if current prefix is already too far from target
        if current_word.len() > target.len() + max_distance as usize {
            return;
        }
        
        for (ch, child_node) in &node_guard.children {
            let new_word = format!("{}{}", current_word, ch);
            self.fuzzy_collect(child_node.clone(), &new_word, target, max_distance, results);
        }
    }
}

fn edit_distance(s1: &str, s2: &str) -> u32 {
    let s1_chars: Vec<char> = s1.chars().collect();
    let s2_chars: Vec<char> = s2.chars().collect();
    let len1 = s1_chars.len();
    let len2 = s2_chars.len();
    
    let mut dp = vec![vec![0u32; len2 + 1]; len1 + 1];
    
    // Initialize base cases
    for i in 0..=len1 {
        dp[i][0] = i as u32;
    }
    for j in 0..=len2 {
        dp[0][j] = j as u32;
    }
    
    // Fill the DP table
    for i in 1..=len1 {
        for j in 1..=len2 {
            if s1_chars[i - 1] == s2_chars[j - 1] {
                dp[i][j] = dp[i - 1][j - 1];
            } else {
                dp[i][j] = 1 + dp[i - 1][j].min(dp[i][j - 1]).min(dp[i - 1][j - 1]);
            }
        }
    }
    
    dp[len1][len2]
}
```

## Deletion and Tree Cleanup

```rust
impl Trie {
    pub fn delete(&mut self, word: &str) -> bool {
        let normalized_word = self.normalize_word(word);
        self.delete_recursive(self.root.clone(), &normalized_word, 0)
    }
    
    fn delete_recursive(
        &mut self,
        node: Arc<RwLock<TrieNode>>,
        word: &str,
        index: usize,
    ) -> bool {
        if index == word.len() {
            let mut node_guard = node.write().unwrap();
            if node_guard.is_end_of_word {
                node_guard.is_end_of_word = false;
                node_guard.word = None;
                node_guard.frequency = 0;
                self.word_count -= 1;
                return node_guard.children.is_empty();
            }
            return false;
        }
        
        let ch = word.chars().nth(index).unwrap();
        let child_node = {
            let node_guard = node.read().unwrap();
            node_guard.children.get(&ch).cloned()
        };
        
        if let Some(child) = child_node {
            let should_delete_child = self.delete_recursive(child.clone(), word, index + 1);
            
            if should_delete_child {
                let mut node_guard = node.write().unwrap();
                node_guard.children.remove(&ch);
                
                // Return true if this node should also be deleted
                return !node_guard.is_end_of_word && node_guard.children.is_empty();
            }
        }
        
        false
    }
}
```

## Statistics and Analysis

```rust
#[derive(Debug)]
pub struct TrieStatistics {
    pub word_count: usize,
    pub node_count: usize,
    pub max_depth: usize,
    pub avg_depth: f64,
    pub memory_efficiency: f64,
}

impl Trie {
    pub fn len(&self) -> usize {
        self.word_count
    }
    
    pub fn is_empty(&self) -> bool {
        self.word_count == 0
    }
    
    pub fn statistics(&self) -> TrieStatistics {
        let mut total_depth = 0;
        let mut max_depth = 0;
        let node_count = self.count_nodes_and_depth(self.root.clone(), 0, &mut total_depth, &mut max_depth);
        
        let avg_depth = if self.word_count > 0 {
            total_depth as f64 / self.word_count as f64
        } else {
            0.0
        };
        
        // Calculate memory efficiency (shared prefixes)
        let total_char_count: usize = self.get_all_words()
            .iter()
            .map(|word| word.len())
            .sum();
        
        let memory_efficiency = if total_char_count > 0 {
            (total_char_count as f64) / (node_count as f64)
        } else {
            0.0
        };
        
        TrieStatistics {
            word_count: self.word_count,
            node_count,
            max_depth,
            avg_depth,
            memory_efficiency,
        }
    }
    
    fn count_nodes_and_depth(
        &self,
        node: Arc<RwLock<TrieNode>>,
        depth: usize,
        total_depth: &mut usize,
        max_depth: &mut usize,
    ) -> usize {
        let node_guard = node.read().unwrap();
        let mut count = 1; // Count this node
        
        if node_guard.is_end_of_word {
            *total_depth += depth;
            *max_depth = (*max_depth).max(depth);
        }
        
        for child in node_guard.children.values() {
            count += self.count_nodes_and_depth(child.clone(), depth + 1, total_depth, max_depth);
        }
        
        count
    }
    
    pub fn get_all_words(&self) -> Vec<String> {
        let mut words = Vec::new();
        self.collect_all_words(self.root.clone(), &mut words);
        words.sort();
        words
    }
    
    fn collect_all_words(&self, node: Arc<RwLock<TrieNode>>, words: &mut Vec<String>) {
        let node_guard = node.read().unwrap();
        
        if node_guard.is_end_of_word {
            if let Some(word) = &node_guard.word {
                words.push(word.clone());
            }
        }
        
        for child in node_guard.children.values() {
            self.collect_all_words(child.clone(), words);
        }
    }
}
```

## Serialization and Persistence

```rust
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{BufReader, BufWriter, Result as IoResult};

#[derive(Serialize, Deserialize)]
struct SerializableTrieNode {
    children: HashMap<char, SerializableTrieNode>,
    is_end_of_word: bool,
    word: Option<String>,
    frequency: u32,
}

impl Trie {
    pub fn save_to_file(&self, filename: &str) -> IoResult<()> {
        let file = File::create(filename)?;
        let writer = BufWriter::new(file);
        
        let serializable_root = self.to_serializable(self.root.clone());
        serde_json::to_writer(writer, &serializable_root)?;
        
        Ok(())
    }
    
    pub fn load_from_file(filename: &str) -> IoResult<Self> {
        let file = File::open(filename)?;
        let reader = BufReader::new(file);
        
        let serializable_root: SerializableTrieNode = serde_json::from_reader(reader)?;
        let mut trie = Trie::new();
        trie.word_count = trie.count_words_in_serializable(&serializable_root);
        trie.root = Arc::new(RwLock::new(trie.from_serializable(serializable_root)));
        
        Ok(trie)
    }
    
    fn to_serializable(&self, node: Arc<RwLock<TrieNode>>) -> SerializableTrieNode {
        let node_guard = node.read().unwrap();
        let mut children = HashMap::new();
        
        for (ch, child) in &node_guard.children {
            children.insert(*ch, self.to_serializable(child.clone()));
        }
        
        SerializableTrieNode {
            children,
            is_end_of_word: node_guard.is_end_of_word,
            word: node_guard.word.clone(),
            frequency: node_guard.frequency,
        }
    }
    
    fn from_serializable(&self, serializable: SerializableTrieNode) -> TrieNode {
        let mut children = HashMap::new();
        
        for (ch, child_serializable) in serializable.children {
            let child_node = Arc::new(RwLock::new(self.from_serializable(child_serializable)));
            children.insert(ch, child_node);
        }
        
        TrieNode {
            children,
            is_end_of_word: serializable.is_end_of_word,
            word: serializable.word,
            frequency: serializable.frequency,
        }
    }
    
    fn count_words_in_serializable(&self, node: &SerializableTrieNode) -> usize {
        let mut count = if node.is_end_of_word { 1 } else { 0 };
        
        for child in node.children.values() {
            count += self.count_words_in_serializable(child);
        }
        
        count
    }
}
```

## Performance Testing and Examples

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Instant;
    
    #[test]
    fn test_basic_operations() {
        let mut trie = Trie::new();
        
        // Test insertion
        assert!(trie.insert("hello"));
        assert!(trie.insert("world"));
        assert!(trie.insert("help"));
        assert!(!trie.insert("hello")); // Duplicate
        
        // Test search
        assert!(trie.search("hello"));
        assert!(trie.search("world"));
        assert!(trie.search("help"));
        assert!(!trie.search("hell"));
        assert!(!trie.search("helping"));
        
        // Test prefix detection
        assert!(trie.starts_with("hel"));
        assert!(trie.starts_with("wor"));
        assert!(!trie.starts_with("xyz"));
        
        assert_eq!(trie.len(), 3);
    }
    
    #[test]
    fn test_suggestions() {
        let mut trie = Trie::new();
        
        let words = vec![
            ("apple", 100),
            ("application", 80),
            ("apply", 60),
            ("appreciate", 40),
            ("app", 200),
        ];
        
        for (word, freq) in words {
            trie.insert_with_frequency(word, freq);
        }
        
        let suggestions = trie.get_suggestions("app", 10);
        assert_eq!(suggestions.len(), 5);
        
        // Should be sorted by frequency
        assert_eq!(suggestions[0].word, "app");
        assert_eq!(suggestions[0].frequency, 200);
    }
    
    #[test]
    fn test_fuzzy_search() {
        let mut trie = Trie::new();
        
        trie.insert("hello");
        trie.insert("world");
        trie.insert("help");
        trie.insert("held");
        
        let results = trie.fuzzy_search("helo", 1, 10);
        assert!(!results.is_empty());
        
        // Should find "hello" and "help" within edit distance 1
        let words: Vec<String> = results.iter().map(|r| r.word.clone()).collect();
        assert!(words.contains(&"hello".to_string()));
        assert!(words.contains(&"help".to_string()));
    }
    
    #[test]
    fn test_deletion() {
        let mut trie = Trie::new();
        
        trie.insert("test");
        trie.insert("testing");
        trie.insert("tester");
        
        assert_eq!(trie.len(), 3);
        assert!(trie.delete("test"));
        assert_eq!(trie.len(), 2);
        assert!(!trie.search("test"));
        assert!(trie.search("testing"));
        assert!(trie.search("tester"));
    }
    
    #[test]
    fn performance_test() {
        let mut trie = Trie::new();
        
        // Insert 10,000 words
        let start = Instant::now();
        for i in 0..10_000 {
            trie.insert(&format!("word{}", i));
        }
        let insert_time = start.elapsed();
        
        println!("Inserted 10,000 words in {:?}", insert_time);
        
        // Test search performance
        let start = Instant::now();
        for i in 0..1_000 {
            trie.search(&format!("word{}", i));
        }
        let search_time = start.elapsed();
        
        println!("1,000 searches in {:?}", search_time);
        
        // Test prefix search performance
        let start = Instant::now();
        for i in 0..100 {
            trie.get_suggestions(&format!("word{}", i), 10);
        }
        let prefix_time = start.elapsed();
        
        println!("100 prefix searches in {:?}", prefix_time);
    }
}

fn main() {
    println!("=== Rust Trie Implementation Demo ===\n");
    
    let mut trie = Trie::new();
    
    // Build a sample autocomplete dictionary
    let words_with_frequencies = vec![
        ("programming", 100),
        ("program", 80),
        ("programmer", 70),
        ("programmatic", 30),
        ("computer", 90),
        ("computing", 60),
        ("computation", 40),
        ("rust", 120),
        ("rusty", 20),
        ("rustacean", 15),
    ];
    
    println!("Building trie with {} words...", words_with_frequencies.len());
    for (word, freq) in &words_with_frequencies {
        trie.insert_with_frequency(word, *freq);
    }
    
    // Display statistics
    let stats = trie.statistics();
    println!("\n=== Trie Statistics ===");
    println!("Words: {}", stats.word_count);
    println!("Nodes: {}", stats.node_count);
    println!("Max depth: {}", stats.max_depth);
    println!("Average depth: {:.2}", stats.avg_depth);
    println!("Memory efficiency: {:.2}x", stats.memory_efficiency);
    
    // Test autocomplete
    println!("\n=== Autocomplete Examples ===");
    let test_prefixes = vec!["prog", "comp", "rust", "xyz"];
    
    for prefix in test_prefixes {
        let suggestions = trie.get_suggestions(prefix, 5);
        println!("\n'{}' → {} suggestions:", prefix, suggestions.len());
        for suggestion in suggestions {
            println!("  {} (freq: {})", suggestion.word, suggestion.frequency);
        }
    }
    
    // Test fuzzy search
    println!("\n=== Fuzzy Search Examples ===");
    let fuzzy_queries = vec!["programing", "compter", "rast"];
    
    for query in fuzzy_queries {
        let results = trie.fuzzy_search(query, 2, 3);
        println!("\nFuzzy search for '{}' → {} results:", query, results.len());
        for result in results {
            println!(
                "  {} (freq: {}, distance: {})",
                result.word,
                result.frequency,
                result.edit_distance.unwrap_or(0)
            );
        }
    }
    
    // Save and load demonstration
    println!("\n=== Persistence Test ===");
    if let Err(e) = trie.save_to_file("trie_data.json") {
        println!("Failed to save trie: {}", e);
    } else {
        println!("Trie saved to trie_data.json");
        
        match Trie::load_from_file("trie_data.json") {
            Ok(loaded_trie) => {
                println!("Trie loaded successfully");
                println!("Loaded trie has {} words", loaded_trie.len());
            }
            Err(e) => println!("Failed to load trie: {}", e),
        }
    }
}
```

## Key Features Demonstrated

### 1. Memory Safety
Rust's ownership system prevents:
- Use-after-free errors
- Double-free errors
- Data races in concurrent access

### 2. Thread Safety
Uses `Arc<RwLock<>>` for safe concurrent access:
- Multiple readers can access simultaneously
- Writers get exclusive access

### 3. Generic Character Support
Handles any Unicode character:
- Not limited to ASCII
- Supports international text

### 4. Advanced Features
- Frequency-based ranking
- Fuzzy search with edit distance
- Tree cleanup during deletion
- Comprehensive statistics
- Serialization support

### 5. Performance Optimizations
- Early termination in fuzzy search
- Efficient memory layout
- Minimized lock contention

## Running the Implementation

Add to `Cargo.toml`:
```toml
[dependencies]
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
```

Compile and run:
```bash
cargo run
cargo test
```

This implementation demonstrates how Rust's type system and ownership model make it possible to build both safe and performant trie data structures, while providing advanced features like fuzzy search and persistence that are commonly needed in production systems.