# Rust Implementation: Building a Vector Database from Scratch

In this implementation, we'll build a simplified but functional vector database in Rust. This will demonstrate the core concepts and give you hands-on experience with the fundamental operations: inserting vectors, building indexes, and performing similarity searches.

## Prerequisites

- Rust 1.70 or later
- Basic understanding of Rust ownership and borrowing
- Familiarity with vector operations and similarity metrics

## Project Setup

First, create a new Rust project:

```bash
cargo new vector_db_rs
cd vector_db_rs
```

Add dependencies to `Cargo.toml`:

```toml
[package]
name = "vector_db_rs"
version = "0.1.0"
edition = "2021"

[dependencies]
rand = "0.8"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
rayon = "1.7"
```

## Core Data Structures

Let's start by defining our core data structures:

```rust
use std::collections::HashMap;
use serde::{Deserialize, Serialize};

// A vector with metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VectorRecord {
    pub id: String,
    pub vector: Vec<f32>,
    pub metadata: HashMap<String, String>,
}

// Distance metrics supported by our database
#[derive(Debug, Clone, Copy)]
pub enum DistanceMetric {
    Euclidean,
    Cosine,
    DotProduct,
}

// Search result with similarity score
#[derive(Debug, Clone)]
pub struct SearchResult {
    pub record: VectorRecord,
    pub similarity: f32,
    pub distance: f32,
}

// Configuration for our vector database
#[derive(Debug, Clone)]
pub struct VectorDBConfig {
    pub dimension: usize,
    pub distance_metric: DistanceMetric,
    pub index_type: IndexType,
}

#[derive(Debug, Clone)]
pub enum IndexType {
    Flat,      // Linear search (exact)
    LSH,       // Locality-Sensitive Hashing
    HNSW,      // Hierarchical Navigable Small World (simplified)
}
```

## Distance Calculations

Let's implement the distance metrics:

```rust
impl DistanceMetric {
    pub fn calculate(&self, a: &[f32], b: &[f32]) -> f32 {
        match self {
            DistanceMetric::Euclidean => euclidean_distance(a, b),
            DistanceMetric::Cosine => cosine_distance(a, b),
            DistanceMetric::DotProduct => dot_product(a, b),
        }
    }
    
    pub fn is_similarity(&self) -> bool {
        matches!(self, DistanceMetric::Cosine | DistanceMetric::DotProduct)
    }
}

fn euclidean_distance(a: &[f32], b: &[f32]) -> f32 {
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| (x - y).powi(2))
        .sum::<f32>()
        .sqrt()
}

fn cosine_distance(a: &[f32], b: &[f32]) -> f32 {
    let dot_product: f32 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f32 = a.iter().map(|x| x.powi(2)).sum::<f32>().sqrt();
    let norm_b: f32 = b.iter().map(|x| x.powi(2)).sum::<f32>().sqrt();
    
    if norm_a == 0.0 || norm_b == 0.0 {
        0.0
    } else {
        dot_product / (norm_a * norm_b)
    }
}

fn dot_product(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b.iter()).map(|(x, y)| x * y).sum()
}
```

## Flat Index Implementation

Let's start with a simple flat index that performs linear search:

```rust
use rayon::prelude::*;

pub struct FlatIndex {
    vectors: Vec<VectorRecord>,
    config: VectorDBConfig,
}

impl FlatIndex {
    pub fn new(config: VectorDBConfig) -> Self {
        Self {
            vectors: Vec::new(),
            config,
        }
    }
    
    pub fn insert(&mut self, record: VectorRecord) -> Result<(), String> {
        if record.vector.len() != self.config.dimension {
            return Err(format!(
                "Vector dimension {} doesn't match expected dimension {}",
                record.vector.len(),
                self.config.dimension
            ));
        }
        
        self.vectors.push(record);
        Ok(())
    }
    
    pub fn search(&self, query: &[f32], k: usize) -> Result<Vec<SearchResult>, String> {
        if query.len() != self.config.dimension {
            return Err("Query vector dimension mismatch".to_string());
        }
        
        // Calculate distances to all vectors in parallel
        let mut results: Vec<SearchResult> = self.vectors
            .par_iter()
            .map(|record| {
                let distance = self.config.distance_metric.calculate(query, &record.vector);
                let similarity = if self.config.distance_metric.is_similarity() {
                    distance
                } else {
                    -distance // Convert distance to similarity (higher is better)
                };
                
                SearchResult {
                    record: record.clone(),
                    similarity,
                    distance,
                }
            })
            .collect();
        
        // Sort by similarity (descending)
        results.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap());
        
        // Return top k results
        results.truncate(k);
        Ok(results)
    }
    
    pub fn size(&self) -> usize {
        self.vectors.len()
    }
}
```

## LSH Index Implementation

Now let's implement a simple LSH index for approximate search:

```rust
use rand::Rng;
use std::collections::HashMap;

pub struct LSHIndex {
    config: VectorDBConfig,
    hash_tables: Vec<HashMap<Vec<bool>, Vec<usize>>>,
    vectors: Vec<VectorRecord>,
    hyperplanes: Vec<Vec<Vec<f32>>>, // [table][function][dimension]
    num_tables: usize,
    num_functions: usize,
}

impl LSHIndex {
    pub fn new(config: VectorDBConfig, num_tables: usize, num_functions: usize) -> Self {
        let mut rng = rand::thread_rng();
        
        // Generate random hyperplanes for each table
        let mut hyperplanes = Vec::new();
        for _ in 0..num_tables {
            let mut table_hyperplanes = Vec::new();
            for _ in 0..num_functions {
                let hyperplane: Vec<f32> = (0..config.dimension)
                    .map(|_| rng.gen_range(-1.0..1.0))
                    .collect();
                table_hyperplanes.push(hyperplane);
            }
            hyperplanes.push(table_hyperplanes);
        }
        
        Self {
            config,
            hash_tables: vec![HashMap::new(); num_tables],
            vectors: Vec::new(),
            hyperplanes,
            num_tables,
            num_functions,
        }
    }
    
    fn hash_vector(&self, vector: &[f32], table_idx: usize) -> Vec<bool> {
        self.hyperplanes[table_idx]
            .iter()
            .map(|hyperplane| {
                let dot_product: f32 = vector
                    .iter()
                    .zip(hyperplane.iter())
                    .map(|(v, h)| v * h)
                    .sum();
                dot_product >= 0.0
            })
            .collect()
    }
    
    pub fn insert(&mut self, record: VectorRecord) -> Result<(), String> {
        if record.vector.len() != self.config.dimension {
            return Err("Vector dimension mismatch".to_string());
        }
        
        let vector_idx = self.vectors.len();
        
        // Hash the vector and add to all tables
        for table_idx in 0..self.num_tables {
            let hash = self.hash_vector(&record.vector, table_idx);
            self.hash_tables[table_idx]
                .entry(hash)
                .or_insert_with(Vec::new)
                .push(vector_idx);
        }
        
        self.vectors.push(record);
        Ok(())
    }
    
    pub fn search(&self, query: &[f32], k: usize) -> Result<Vec<SearchResult>, String> {
        if query.len() != self.config.dimension {
            return Err("Query vector dimension mismatch".to_string());
        }
        
        // Find candidate vectors from all tables
        let mut candidates = std::collections::HashSet::new();
        
        for table_idx in 0..self.num_tables {
            let hash = self.hash_vector(query, table_idx);
            if let Some(bucket) = self.hash_tables[table_idx].get(&hash) {
                candidates.extend(bucket.iter());
            }
        }
        
        // Calculate exact distances for candidates
        let mut results: Vec<SearchResult> = candidates
            .iter()
            .map(|&idx| {
                let record = &self.vectors[idx];
                let distance = self.config.distance_metric.calculate(query, &record.vector);
                let similarity = if self.config.distance_metric.is_similarity() {
                    distance
                } else {
                    -distance
                };
                
                SearchResult {
                    record: record.clone(),
                    similarity,
                    distance,
                }
            })
            .collect();
        
        // Sort by similarity and return top k
        results.sort_by(|a, b| b.similarity.partial_cmp(&a.similarity).unwrap());
        results.truncate(k);
        
        Ok(results)
    }
    
    pub fn size(&self) -> usize {
        self.vectors.len()
    }
}
```

## Main Vector Database Interface

Now let's create the main vector database that can use different index types:

```rust
pub struct VectorDB {
    config: VectorDBConfig,
    index: Box<dyn VectorIndex>,
}

pub trait VectorIndex {
    fn insert(&mut self, record: VectorRecord) -> Result<(), String>;
    fn search(&self, query: &[f32], k: usize) -> Result<Vec<SearchResult>, String>;
    fn size(&self) -> usize;
}

impl VectorIndex for FlatIndex {
    fn insert(&mut self, record: VectorRecord) -> Result<(), String> {
        FlatIndex::insert(self, record)
    }
    
    fn search(&self, query: &[f32], k: usize) -> Result<Vec<SearchResult>, String> {
        FlatIndex::search(self, query, k)
    }
    
    fn size(&self) -> usize {
        FlatIndex::size(self)
    }
}

impl VectorIndex for LSHIndex {
    fn insert(&mut self, record: VectorRecord) -> Result<(), String> {
        LSHIndex::insert(self, record)
    }
    
    fn search(&self, query: &[f32], k: usize) -> Result<Vec<SearchResult>, String> {
        LSHIndex::search(self, query, k)
    }
    
    fn size(&self) -> usize {
        LSHIndex::size(self)
    }
}

impl VectorDB {
    pub fn new(config: VectorDBConfig) -> Self {
        let index: Box<dyn VectorIndex> = match config.index_type {
            IndexType::Flat => Box::new(FlatIndex::new(config.clone())),
            IndexType::LSH => Box::new(LSHIndex::new(config.clone(), 10, 20)),
            IndexType::HNSW => {
                // For this example, we'll use Flat index as HNSW is complex
                Box::new(FlatIndex::new(config.clone()))
            }
        };
        
        Self { config, index }
    }
    
    pub fn insert(&mut self, record: VectorRecord) -> Result<(), String> {
        self.index.insert(record)
    }
    
    pub fn search(&self, query: &[f32], k: usize) -> Result<Vec<SearchResult>, String> {
        self.index.search(query, k)
    }
    
    pub fn size(&self) -> usize {
        self.index.size()
    }
    
    pub fn batch_insert(&mut self, records: Vec<VectorRecord>) -> Result<(), String> {
        for record in records {
            self.insert(record)?;
        }
        Ok(())
    }
}
```

## Utility Functions

Let's add some utility functions for common operations:

```rust
impl VectorDB {
    pub fn save_to_file(&self, path: &str) -> Result<(), Box<dyn std::error::Error>> {
        // For simplicity, we'll just serialize the vectors
        // In a real implementation, you'd save the index structure
        let vectors: Vec<&VectorRecord> = (0..self.size())
            .map(|i| &self.index.vectors[i])
            .collect();
        
        let serialized = serde_json::to_string_pretty(&vectors)?;
        std::fs::write(path, serialized)?;
        Ok(())
    }
    
    pub fn load_from_file(path: &str, config: VectorDBConfig) -> Result<Self, Box<dyn std::error::Error>> {
        let data = std::fs::read_to_string(path)?;
        let vectors: Vec<VectorRecord> = serde_json::from_str(&data)?;
        
        let mut db = VectorDB::new(config);
        db.batch_insert(vectors)?;
        Ok(db)
    }
}

// Helper function to generate random vectors for testing
pub fn generate_random_vectors(count: usize, dimension: usize) -> Vec<VectorRecord> {
    let mut rng = rand::thread_rng();
    
    (0..count)
        .map(|i| {
            let vector: Vec<f32> = (0..dimension)
                .map(|_| rng.gen_range(-1.0..1.0))
                .collect();
            
            let mut metadata = HashMap::new();
            metadata.insert("id".to_string(), i.to_string());
            
            VectorRecord {
                id: format!("vec_{}", i),
                vector,
                metadata,
            }
        })
        .collect()
}
```

## Example Usage

Finally, let's create a complete example in `main.rs`:

```rust
use std::collections::HashMap;
use vector_db_rs::*;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Create a vector database configuration
    let config = VectorDBConfig {
        dimension: 128,
        distance_metric: DistanceMetric::Cosine,
        index_type: IndexType::Flat,
    };
    
    // Create the database
    let mut db = VectorDB::new(config);
    
    // Generate some test data
    println!("Generating test vectors...");
    let test_vectors = generate_random_vectors(10000, 128);
    
    // Insert vectors
    println!("Inserting {} vectors...", test_vectors.len());
    let start = std::time::Instant::now();
    db.batch_insert(test_vectors)?;
    println!("Insertion took: {:?}", start.elapsed());
    
    // Create a query vector
    let query = vec![0.1; 128];
    
    // Search for similar vectors
    println!("Searching for similar vectors...");
    let start = std::time::Instant::now();
    let results = db.search(&query, 10)?;
    println!("Search took: {:?}", start.elapsed());
    
    // Display results
    println!("\nTop 10 similar vectors:");
    for (i, result) in results.iter().enumerate() {
        println!(
            "{}. ID: {}, Similarity: {:.4}, Distance: {:.4}",
            i + 1,
            result.record.id,
            result.similarity,
            result.distance
        );
    }
    
    // Test with LSH index
    println!("\n--- Testing LSH Index ---");
    let lsh_config = VectorDBConfig {
        dimension: 128,
        distance_metric: DistanceMetric::Cosine,
        index_type: IndexType::LSH,
    };
    
    let mut lsh_db = VectorDB::new(lsh_config);
    let test_vectors = generate_random_vectors(10000, 128);
    
    println!("Inserting vectors into LSH index...");
    let start = std::time::Instant::now();
    lsh_db.batch_insert(test_vectors)?;
    println!("LSH insertion took: {:?}", start.elapsed());
    
    println!("Searching with LSH index...");
    let start = std::time::Instant::now();
    let lsh_results = lsh_db.search(&query, 10)?;
    println!("LSH search took: {:?}", start.elapsed());
    
    println!("\nLSH Top 10 similar vectors:");
    for (i, result) in lsh_results.iter().enumerate() {
        println!(
            "{}. ID: {}, Similarity: {:.4}",
            i + 1,
            result.record.id,
            result.similarity
        );
    }
    
    Ok(())
}
```

## Performance Benchmarks

Let's add a benchmark module to test performance:

```rust
#[cfg(test)]
mod benchmarks {
    use super::*;
    use std::time::Instant;
    
    #[test]
    fn benchmark_flat_vs_lsh() {
        let sizes = vec![1000, 5000, 10000, 50000];
        
        for size in sizes {
            println!("\n--- Benchmark with {} vectors ---", size);
            
            // Test Flat Index
            let flat_config = VectorDBConfig {
                dimension: 128,
                distance_metric: DistanceMetric::Cosine,
                index_type: IndexType::Flat,
            };
            
            let mut flat_db = VectorDB::new(flat_config);
            let test_vectors = generate_random_vectors(size, 128);
            
            let start = Instant::now();
            flat_db.batch_insert(test_vectors.clone()).unwrap();
            let flat_insert_time = start.elapsed();
            
            let query = vec![0.1; 128];
            let start = Instant::now();
            let _flat_results = flat_db.search(&query, 10).unwrap();
            let flat_search_time = start.elapsed();
            
            // Test LSH Index
            let lsh_config = VectorDBConfig {
                dimension: 128,
                distance_metric: DistanceMetric::Cosine,
                index_type: IndexType::LSH,
            };
            
            let mut lsh_db = VectorDB::new(lsh_config);
            
            let start = Instant::now();
            lsh_db.batch_insert(test_vectors).unwrap();
            let lsh_insert_time = start.elapsed();
            
            let start = Instant::now();
            let _lsh_results = lsh_db.search(&query, 10).unwrap();
            let lsh_search_time = start.elapsed();
            
            println!("Flat - Insert: {:?}, Search: {:?}", flat_insert_time, flat_search_time);
            println!("LSH  - Insert: {:?}, Search: {:?}", lsh_insert_time, lsh_search_time);
        }
    }
}
```

## Running the Implementation

To run the implementation:

```bash
# Run the main example
cargo run --release

# Run benchmarks
cargo test benchmarks -- --nocapture
```

## Key Takeaways

This Rust implementation demonstrates:

1. **Core Abstractions**: Vector records, distance metrics, and search results
2. **Multiple Index Types**: Flat (exact) and LSH (approximate) indexes
3. **Trait-based Design**: Flexible architecture that can support different index types
4. **Performance Considerations**: Parallel processing and efficient data structures
5. **Practical Features**: Serialization, batch operations, and benchmarking

## Extensions and Improvements

To make this production-ready, consider adding:

1. **Persistence**: Proper disk-based storage with memory mapping
2. **HNSW Implementation**: A complete hierarchical navigable small world index
3. **Quantization**: Product quantization for memory efficiency
4. **Distributed Support**: Sharding across multiple nodes
5. **Query Optimization**: Query planning and caching
6. **Monitoring**: Metrics and observability features

This implementation provides a solid foundation for understanding how vector databases work under the hood and can serve as a starting point for building more sophisticated systems.