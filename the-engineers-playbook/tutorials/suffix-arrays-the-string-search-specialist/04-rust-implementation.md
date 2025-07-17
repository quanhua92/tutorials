# Rust Implementation: High-Performance Suffix Arrays

This implementation provides a complete, efficient suffix array library in Rust, focusing on performance, memory safety, and practical usability for real-world text processing applications.

## Project Setup

Create a new Rust project:

```bash
cargo new suffix_arrays
cd suffix_arrays
```

Add dependencies to `Cargo.toml`:

```toml
[package]
name = "suffix_arrays"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1.0", features = ["derive"] }
rayon = "1.7"  # For parallel processing
criterion = { version = "0.5", optional = true }

[dev-dependencies]
criterion = "0.5"
rand = "0.8"

[[bench]]
name = "suffix_array_benchmark"
harness = false

[features]
default = []
benchmarks = ["criterion"]
```

## Core Types and Traits

```rust
// src/types.rs
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;

/// Position in the original text
pub type Position = u32;

/// Rank used in construction algorithms
pub type Rank = u32;

/// A suffix array builder trait
pub trait SuffixArrayBuilder {
    fn build(&self, text: &[u8]) -> SuffixArray;
    fn name(&self) -> &'static str;
}

/// Main suffix array data structure
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SuffixArray {
    /// The original text with sentinel
    text: Vec<u8>,
    /// Suffix array: sorted positions of suffixes
    sa: Vec<Position>,
    /// Optional LCP array for enhanced functionality
    lcp: Option<Vec<u32>>,
}

impl SuffixArray {
    pub fn new(text: Vec<u8>, sa: Vec<Position>) -> Self {
        Self {
            text,
            sa,
            lcp: None,
        }
    }
    
    pub fn with_lcp(mut self, lcp: Vec<u32>) -> Self {
        self.lcp = Some(lcp);
        self
    }
    
    pub fn text(&self) -> &[u8] {
        &self.text
    }
    
    pub fn suffix_array(&self) -> &[Position] {
        &self.sa
    }
    
    pub fn lcp_array(&self) -> Option<&[u32]> {
        self.lcp.as_deref()
    }
    
    pub fn len(&self) -> usize {
        self.sa.len()
    }
    
    pub fn is_empty(&self) -> bool {
        self.sa.is_empty()
    }
    
    /// Get the suffix starting at the i-th position in sorted order
    pub fn get_suffix(&self, rank: usize) -> &[u8] {
        if rank >= self.sa.len() {
            return &[];
        }
        let start_pos = self.sa[rank] as usize;
        &self.text[start_pos..]
    }
    
    /// Find all occurrences of a pattern
    pub fn find(&self, pattern: &[u8]) -> Vec<Position> {
        let (left, right) = self.find_range(pattern);
        (left..=right)
            .map(|i| self.sa[i])
            .filter(|&pos| (pos as usize) < self.text.len().saturating_sub(1)) // Exclude sentinel
            .collect()
    }
    
    /// Count occurrences of a pattern
    pub fn count(&self, pattern: &[u8]) -> usize {
        let (left, right) = self.find_range(pattern);
        if left <= right {
            (right - left + 1).min(
                self.sa.iter()
                    .skip(left)
                    .take(right - left + 1)
                    .filter(|&&pos| (pos as usize) < self.text.len().saturating_sub(1))
                    .count()
            )
        } else {
            0
        }
    }
    
    /// Check if pattern exists in the text
    pub fn contains(&self, pattern: &[u8]) -> bool {
        let (left, right) = self.find_range(pattern);
        left <= right
    }
    
    /// Find the range [left, right] where pattern occurs
    fn find_range(&self, pattern: &[u8]) -> (usize, usize) {
        if pattern.is_empty() {
            return (0, 0);
        }
        
        let left = self.lower_bound(pattern);
        let right = self.upper_bound(pattern);
        
        if left < self.sa.len() && self.suffix_starts_with(left, pattern) {
            (left, right.saturating_sub(1))
        } else {
            (1, 0) // Empty range
        }
    }
    
    /// Binary search for leftmost position where pattern could occur
    fn lower_bound(&self, pattern: &[u8]) -> usize {
        let mut left = 0;
        let mut right = self.sa.len();
        
        while left < right {
            let mid = left + (right - left) / 2;
            
            match self.compare_suffix_with_pattern(mid, pattern) {
                Ordering::Less => left = mid + 1,
                _ => right = mid,
            }
        }
        
        left
    }
    
    /// Binary search for rightmost position where pattern could occur
    fn upper_bound(&self, pattern: &[u8]) -> usize {
        let mut left = 0;
        let mut right = self.sa.len();
        
        while left < right {
            let mid = left + (right - left) / 2;
            
            if self.suffix_starts_with(mid, pattern) {
                left = mid + 1;
            } else {
                match self.compare_suffix_with_pattern(mid, pattern) {
                    Ordering::Less => left = mid + 1,
                    _ => right = mid,
                }
            }
        }
        
        left
    }
    
    /// Compare suffix at rank i with pattern
    fn compare_suffix_with_pattern(&self, rank: usize, pattern: &[u8]) -> Ordering {
        let suffix = self.get_suffix(rank);
        let min_len = suffix.len().min(pattern.len());
        
        for i in 0..min_len {
            match suffix[i].cmp(&pattern[i]) {
                Ordering::Equal => continue,
                other => return other,
            }
        }
        
        suffix.len().cmp(&pattern.len())
    }
    
    /// Check if suffix at rank starts with pattern
    fn suffix_starts_with(&self, rank: usize, pattern: &[u8]) -> bool {
        let suffix = self.get_suffix(rank);
        suffix.len() >= pattern.len() && &suffix[..pattern.len()] == pattern
    }
}

/// Result of suffix array construction with timing information
#[derive(Debug)]
pub struct ConstructionResult {
    pub suffix_array: SuffixArray,
    pub construction_time: std::time::Duration,
    pub algorithm: String,
}
```

## Naive Construction Algorithm

```rust
// src/naive.rs
use crate::types::{Position, SuffixArray, SuffixArrayBuilder};
use std::time::Instant;

/// Naive O(n² log n) suffix array construction
pub struct NaiveBuilder;

impl SuffixArrayBuilder for NaiveBuilder {
    fn build(&self, text: &[u8]) -> SuffixArray {
        if text.is_empty() {
            return SuffixArray::new(vec![0], vec![0]);
        }
        
        // Add sentinel if not present
        let mut text_with_sentinel = text.to_vec();
        if text_with_sentinel.last() != Some(&0) {
            text_with_sentinel.push(0); // Use null byte as sentinel
        }
        
        // Generate all suffixes with their positions
        let mut suffixes: Vec<(Vec<u8>, Position)> = (0..text_with_sentinel.len())
            .map(|i| (text_with_sentinel[i..].to_vec(), i as Position))
            .collect();
        
        // Sort suffixes lexicographically
        suffixes.sort_by(|a, b| a.0.cmp(&b.0));
        
        // Extract positions to create suffix array
        let sa: Vec<Position> = suffixes.into_iter().map(|(_, pos)| pos).collect();
        
        SuffixArray::new(text_with_sentinel, sa)
    }
    
    fn name(&self) -> &'static str {
        "Naive"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_naive_construction() {
        let text = b"banana";
        let builder = NaiveBuilder;
        let sa = builder.build(text);
        
        // Verify suffix array is correct
        assert_eq!(sa.len(), 7); // "banana" + sentinel
        
        // Test pattern search
        let occurrences = sa.find(b"ana");
        assert_eq!(occurrences.len(), 2);
        assert!(occurrences.contains(&1)); // "anana"
        assert!(occurrences.contains(&3)); // "ana"
    }
    
    #[test]
    fn test_empty_text() {
        let builder = NaiveBuilder;
        let sa = builder.build(b"");
        assert_eq!(sa.len(), 1);
    }
    
    #[test]
    fn test_single_character() {
        let builder = NaiveBuilder;
        let sa = builder.build(b"a");
        assert_eq!(sa.len(), 2); // "a" + sentinel
    }
}
```

## Efficient Doubling Algorithm

```rust
// src/doubling.rs
use crate::types::{Position, Rank, SuffixArray, SuffixArrayBuilder};
use std::collections::HashMap;

/// Efficient O(n log n) suffix array construction using doubling strategy
pub struct DoublingBuilder;

impl SuffixArrayBuilder for DoublingBuilder {
    fn build(&self, text: &[u8]) -> SuffixArray {
        if text.is_empty() {
            return SuffixArray::new(vec![0], vec![0]);
        }
        
        // Add sentinel if not present
        let mut text_with_sentinel = text.to_vec();
        if text_with_sentinel.last() != Some(&0) {
            text_with_sentinel.push(0);
        }
        
        let n = text_with_sentinel.len();
        let sa = self.build_doubling(&text_with_sentinel);
        
        SuffixArray::new(text_with_sentinel, sa)
    }
    
    fn name(&self) -> &'static str {
        "Doubling"
    }
}

impl DoublingBuilder {
    fn build_doubling(&self, text: &[u8]) -> Vec<Position> {
        let n = text.len();
        
        // Initial ranking based on single characters
        let mut ranks = self.initial_ranks(text);
        let mut sa: Vec<Position> = (0..n as Position).collect();
        
        let mut length = 1;
        
        while length < n {
            // Create pairs (rank[i], rank[i+length], original_position)
            let mut pairs: Vec<(Rank, Rank, Position)> = (0..n)
                .map(|i| {
                    let first = ranks[i];
                    let second = if i + length < n { ranks[i + length] } else { 0 };
                    (first, second, i as Position)
                })
                .collect();
            
            // Sort pairs lexicographically
            pairs.sort_unstable();
            
            // Assign new ranks based on sorted order
            let mut new_ranks = vec![0; n];
            let mut current_rank = 0;
            
            for i in 0..n {
                if i > 0 && (pairs[i].0, pairs[i].1) != (pairs[i-1].0, pairs[i-1].1) {
                    current_rank += 1;
                }
                new_ranks[pairs[i].2 as usize] = current_rank;
            }
            
            // Update suffix array and ranks
            sa = pairs.into_iter().map(|(_, _, pos)| pos).collect();
            ranks = new_ranks;
            
            // If all ranks are unique, we're done
            if current_rank as usize == n - 1 {
                break;
            }
            
            length *= 2;
        }
        
        sa
    }
    
    fn initial_ranks(&self, text: &[u8]) -> Vec<Rank> {
        // Create character to rank mapping
        let mut chars: Vec<u8> = text.iter().cloned().collect();
        chars.sort_unstable();
        chars.dedup();
        
        let char_to_rank: HashMap<u8, Rank> = chars
            .into_iter()
            .enumerate()
            .map(|(rank, ch)| (ch, rank as Rank))
            .collect();
        
        text.iter().map(|&ch| char_to_rank[&ch]).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_doubling_construction() {
        let text = b"banana";
        let builder = DoublingBuilder;
        let sa = builder.build(text);
        
        // Verify correctness by checking sorted order
        let suffixes: Vec<&[u8]> = sa.suffix_array()
            .iter()
            .map(|&pos| &sa.text()[pos as usize..])
            .collect();
        
        for i in 1..suffixes.len() {
            assert!(suffixes[i-1] <= suffixes[i], 
                "Suffixes not in sorted order: {:?} > {:?}", 
                suffixes[i-1], suffixes[i]);
        }
        
        // Test pattern search
        let occurrences = sa.find(b"ana");
        assert_eq!(occurrences.len(), 2);
    }
    
    #[test]
    fn test_doubling_vs_naive() {
        let text = b"abracadabra";
        
        let naive_sa = NaiveBuilder.build(text);
        let doubling_sa = DoublingBuilder.build(text);
        
        // Both should produce the same suffix array
        assert_eq!(naive_sa.suffix_array(), doubling_sa.suffix_array());
    }
}
```

## LCP Array Construction

```rust
// src/lcp.rs
use crate::types::{Position, SuffixArray};

/// Build LCP (Longest Common Prefix) array efficiently
pub fn build_lcp_array(sa: &SuffixArray) -> Vec<u32> {
    let text = sa.text();
    let suffix_array = sa.suffix_array();
    let n = suffix_array.len();
    
    if n == 0 {
        return Vec::new();
    }
    
    // Build rank array (inverse of suffix array)
    let mut rank = vec![0; n];
    for (i, &pos) in suffix_array.iter().enumerate() {
        rank[pos as usize] = i;
    }
    
    let mut lcp = vec![0; n];
    let mut h = 0; // Height (LCP length)
    
    for i in 0..n {
        if rank[i] > 0 {
            let j = suffix_array[rank[i] - 1] as usize;
            
            // Compare suffixes starting at i and j
            while i + h < text.len() && 
                  j + h < text.len() && 
                  text[i + h] == text[j + h] {
                h += 1;
            }
            
            lcp[rank[i]] = h as u32;
            
            if h > 0 {
                h -= 1;
            }
        }
    }
    
    lcp
}

impl SuffixArray {
    /// Build and attach LCP array
    pub fn build_lcp(&mut self) {
        let lcp = build_lcp_array(self);
        self.lcp = Some(lcp);
    }
    
    /// Find longest repeated substring using LCP array
    pub fn longest_repeated_substring(&self) -> Option<&[u8]> {
        let lcp = self.lcp.as_ref()?;
        
        let (max_lcp_pos, &max_lcp) = lcp
            .iter()
            .enumerate()
            .max_by_key(|(_, &lcp)| lcp)?;
        
        if max_lcp == 0 {
            return None;
        }
        
        let start_pos = self.sa[max_lcp_pos] as usize;
        let end_pos = start_pos + max_lcp as usize;
        
        Some(&self.text[start_pos..end_pos])
    }
    
    /// Find all repeated substrings of at least min_length
    pub fn repeated_substrings(&self, min_length: u32) -> Vec<&[u8]> {
        let lcp = match self.lcp.as_ref() {
            Some(lcp) => lcp,
            None => return Vec::new(),
        };
        
        let mut results = Vec::new();
        
        for (i, &lcp_val) in lcp.iter().enumerate() {
            if lcp_val >= min_length {
                let start_pos = self.sa[i] as usize;
                let end_pos = start_pos + lcp_val as usize;
                
                if end_pos <= self.text.len() {
                    results.push(&self.text[start_pos..end_pos]);
                }
            }
        }
        
        // Remove duplicates
        results.sort_unstable();
        results.dedup();
        results
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doubling::DoublingBuilder;
    use crate::types::SuffixArrayBuilder;
    
    #[test]
    fn test_lcp_construction() {
        let text = b"banana";
        let mut sa = DoublingBuilder.build(text);
        sa.build_lcp();
        
        let lcp = sa.lcp_array().unwrap();
        assert_eq!(lcp.len(), sa.len());
        
        // First LCP should be 0 (no previous suffix)
        assert_eq!(lcp[0], 0);
    }
    
    #[test]
    fn test_longest_repeated_substring() {
        let text = b"banana";
        let mut sa = DoublingBuilder.build(text);
        sa.build_lcp();
        
        let longest = sa.longest_repeated_substring();
        assert!(longest.is_some());
        
        // "ana" should be the longest repeated substring in "banana"
        let longest_str = longest.unwrap();
        assert_eq!(longest_str, b"ana");
    }
}
```

## Enhanced Suffix Array with Advanced Features

```rust
// src/enhanced.rs
use crate::types::{Position, SuffixArray};
use rayon::prelude::*;
use std::collections::HashSet;

impl SuffixArray {
    /// Find approximate matches allowing up to k mismatches
    pub fn approximate_search(&self, pattern: &[u8], max_mismatches: usize) -> Vec<Position> {
        if pattern.is_empty() {
            return Vec::new();
        }
        
        self.suffix_array()
            .par_iter()
            .filter_map(|&pos| {
                let pos_usize = pos as usize;
                if pos_usize >= self.text.len() {
                    return None;
                }
                
                let suffix = &self.text[pos_usize..];
                if suffix.len() < pattern.len() {
                    return None;
                }
                
                let mismatches = pattern
                    .iter()
                    .zip(suffix.iter())
                    .filter(|(a, b)| a != b)
                    .count();
                
                if mismatches <= max_mismatches {
                    Some(pos)
                } else {
                    None
                }
            })
            .collect()
    }
    
    /// Find all unique substrings of given length
    pub fn unique_substrings(&self, length: usize) -> HashSet<Vec<u8>> {
        if length == 0 {
            return HashSet::new();
        }
        
        let mut substrings = HashSet::new();
        
        for &pos in self.suffix_array() {
            let pos_usize = pos as usize;
            if pos_usize + length <= self.text.len() {
                let substring = self.text[pos_usize..pos_usize + length].to_vec();
                substrings.insert(substring);
            }
        }
        
        substrings
    }
    
    /// Find common substrings with another text
    pub fn common_substrings(&self, other: &SuffixArray, min_length: usize) -> Vec<Vec<u8>> {
        let self_substrings = self.unique_substrings(min_length);
        let other_substrings = other.unique_substrings(min_length);
        
        self_substrings
            .intersection(&other_substrings)
            .cloned()
            .collect()
    }
    
    /// Compute suffix array statistics
    pub fn statistics(&self) -> SuffixArrayStats {
        let lcp = self.lcp_array();
        
        let (min_lcp, max_lcp, avg_lcp) = if let Some(lcp) = lcp {
            let min = lcp.iter().cloned().min().unwrap_or(0);
            let max = lcp.iter().cloned().max().unwrap_or(0);
            let avg = if lcp.is_empty() { 
                0.0 
            } else { 
                lcp.iter().sum::<u32>() as f64 / lcp.len() as f64 
            };
            (min, max, avg)
        } else {
            (0, 0, 0.0)
        };
        
        SuffixArrayStats {
            text_length: self.text.len(),
            alphabet_size: self.text.iter().cloned().collect::<HashSet<_>>().len(),
            min_lcp,
            max_lcp,
            avg_lcp,
        }
    }
}

#[derive(Debug)]
pub struct SuffixArrayStats {
    pub text_length: usize,
    pub alphabet_size: usize,
    pub min_lcp: u32,
    pub max_lcp: u32,
    pub avg_lcp: f64,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::doubling::DoublingBuilder;
    use crate::types::SuffixArrayBuilder;
    
    #[test]
    fn test_approximate_search() {
        let text = b"banana";
        let sa = DoublingBuilder.build(text);
        
        // Search for "aba" with 1 mismatch should find "ana"
        let results = sa.approximate_search(b"aba", 1);
        assert!(!results.is_empty());
    }
    
    #[test]
    fn test_unique_substrings() {
        let text = b"banana";
        let sa = DoublingBuilder.build(text);
        
        let substrings = sa.unique_substrings(2);
        assert!(substrings.contains(&b"ba".to_vec()));
        assert!(substrings.contains(&b"an".to_vec()));
        assert!(substrings.contains(&b"na".to_vec()));
    }
}
```

## Performance Benchmarks

```rust
// benches/suffix_array_benchmark.rs
use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use suffix_arrays::*;
use rand::{Rng, SeedableRng};
use rand::rngs::StdRng;

fn generate_text(size: usize, alphabet_size: usize, seed: u64) -> Vec<u8> {
    let mut rng = StdRng::seed_from_u64(seed);
    (0..size)
        .map(|_| rng.gen_range(0..alphabet_size) as u8)
        .collect()
}

fn benchmark_construction(c: &mut Criterion) {
    let mut group = c.benchmark_group("construction");
    
    for size in [1000, 10000, 50000].iter() {
        let text = generate_text(*size, 4, 42); // DNA-like alphabet
        
        group.bench_with_input(
            BenchmarkId::new("naive", size),
            &text,
            |b, text| {
                b.iter(|| {
                    let builder = naive::NaiveBuilder;
                    builder.build(black_box(text))
                })
            },
        );
        
        group.bench_with_input(
            BenchmarkId::new("doubling", size),
            &text,
            |b, text| {
                b.iter(|| {
                    let builder = doubling::DoublingBuilder;
                    builder.build(black_box(text))
                })
            },
        );
    }
    
    group.finish();
}

fn benchmark_search(c: &mut Criterion) {
    let mut group = c.benchmark_group("search");
    
    let text = generate_text(100000, 4, 42);
    let sa = doubling::DoublingBuilder.build(&text);
    
    // Generate random patterns of different lengths
    let patterns: Vec<Vec<u8>> = (0..100)
        .map(|i| generate_text(5 + i % 10, 4, i as u64))
        .collect();
    
    group.bench_function("pattern_search", |b| {
        b.iter(|| {
            for pattern in &patterns {
                let _ = sa.find(black_box(pattern));
            }
        })
    });
    
    group.bench_function("pattern_count", |b| {
        b.iter(|| {
            for pattern in &patterns {
                let _ = sa.count(black_box(pattern));
            }
        })
    });
    
    group.finish();
}

fn benchmark_lcp_construction(c: &mut Criterion) {
    let mut group = c.benchmark_group("lcp_construction");
    
    for size in [1000, 10000, 50000].iter() {
        let text = generate_text(*size, 4, 42);
        let sa = doubling::DoublingBuilder.build(&text);
        
        group.bench_with_input(
            BenchmarkId::new("lcp_build", size),
            &sa,
            |b, sa| {
                b.iter(|| {
                    lcp::build_lcp_array(black_box(sa))
                })
            },
        );
    }
    
    group.finish();
}

criterion_group!(benches, benchmark_construction, benchmark_search, benchmark_lcp_construction);
criterion_main!(benches);
```

## Main Library Interface

```rust
// src/lib.rs
pub mod types;
pub mod naive;
pub mod doubling;
pub mod lcp;
pub mod enhanced;

pub use types::*;
pub use naive::NaiveBuilder;
pub use doubling::DoublingBuilder;

/// Convenience function to build suffix array with default algorithm
pub fn build_suffix_array(text: &[u8]) -> SuffixArray {
    DoublingBuilder.build(text)
}

/// Convenience function to build suffix array with LCP
pub fn build_suffix_array_with_lcp(text: &[u8]) -> SuffixArray {
    let mut sa = DoublingBuilder.build(text);
    sa.build_lcp();
    sa
}

/// Compare different construction algorithms
pub fn benchmark_algorithms(text: &[u8]) -> Vec<ConstructionResult> {
    use std::time::Instant;
    
    let algorithms: Vec<Box<dyn SuffixArrayBuilder>> = vec![
        Box::new(NaiveBuilder),
        Box::new(DoublingBuilder),
    ];
    
    algorithms
        .into_iter()
        .map(|builder| {
            let start = Instant::now();
            let sa = builder.build(text);
            let duration = start.elapsed();
            
            ConstructionResult {
                suffix_array: sa,
                construction_time: duration,
                algorithm: builder.name().to_string(),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_basic_functionality() {
        let text = b"banana";
        let sa = build_suffix_array(text);
        
        assert!(sa.contains(b"ana"));
        assert_eq!(sa.count(b"ana"), 2);
        
        let occurrences = sa.find(b"ana");
        assert_eq!(occurrences.len(), 2);
    }
    
    #[test]
    fn test_with_lcp() {
        let text = b"abracadabra";
        let sa = build_suffix_array_with_lcp(text);
        
        assert!(sa.lcp_array().is_some());
        
        let longest = sa.longest_repeated_substring();
        assert!(longest.is_some());
    }
    
    #[test]
    fn test_empty_and_edge_cases() {
        // Empty text
        let sa = build_suffix_array(b"");
        assert_eq!(sa.len(), 1); // Just sentinel
        
        // Single character
        let sa = build_suffix_array(b"a");
        assert_eq!(sa.len(), 2); // Character + sentinel
        
        // All same characters
        let sa = build_suffix_array(b"aaaa");
        assert!(sa.find(b"aa").len() >= 2);
    }
}
```

## Example Applications

```rust
// src/applications.rs
use crate::types::SuffixArray;
use std::collections::HashMap;

/// DNA sequence analysis
pub mod dna {
    use super::*;
    
    pub fn find_tandem_repeats(sequence: &[u8], min_length: usize) -> Vec<(usize, usize, usize)> {
        let mut sa = crate::build_suffix_array_with_lcp(sequence);
        let lcp = sa.lcp_array().unwrap();
        
        let mut repeats = Vec::new();
        
        for i in 1..sa.len() {
            let lcp_len = lcp[i] as usize;
            if lcp_len >= min_length {
                let pos1 = sa.suffix_array()[i-1] as usize;
                let pos2 = sa.suffix_array()[i] as usize;
                
                // Check if this could be a tandem repeat
                if pos2.saturating_sub(pos1) <= lcp_len * 2 {
                    repeats.push((pos1, pos2, lcp_len));
                }
            }
        }
        
        repeats
    }
    
    pub fn gc_content_analysis(sequence: &[u8]) -> f64 {
        let gc_count = sequence.iter()
            .filter(|&&base| base == b'G' || base == b'C')
            .count();
        
        gc_count as f64 / sequence.len() as f64
    }
}

/// Text analysis and processing
pub mod text {
    use super::*;
    
    pub fn word_frequency(text: &[u8], min_word_length: usize) -> HashMap<Vec<u8>, usize> {
        let sa = crate::build_suffix_array(text);
        
        // Extract words (sequences of alphabetic characters)
        let mut words = HashMap::new();
        let mut current_word = Vec::new();
        
        for &byte in text {
            if byte.is_ascii_alphabetic() {
                current_word.push(byte.to_ascii_lowercase());
            } else {
                if current_word.len() >= min_word_length {
                    *words.entry(current_word.clone()).or_insert(0) += 1;
                }
                current_word.clear();
            }
        }
        
        // Handle last word
        if current_word.len() >= min_word_length {
            *words.entry(current_word).or_insert(0) += 1;
        }
        
        words
    }
    
    pub fn find_palindromes(text: &[u8], min_length: usize) -> Vec<(usize, usize)> {
        let mut palindromes = Vec::new();
        
        for i in 0..text.len() {
            // Odd length palindromes
            let mut left = i;
            let mut right = i;
            
            while left < text.len() && right < text.len() && text[left] == text[right] {
                if right - left + 1 >= min_length {
                    palindromes.push((left, right + 1));
                }
                if left == 0 { break; }
                left -= 1;
                right += 1;
            }
            
            // Even length palindromes
            if i + 1 < text.len() {
                let mut left = i;
                let mut right = i + 1;
                
                while left < text.len() && right < text.len() && text[left] == text[right] {
                    if right - left + 1 >= min_length {
                        palindromes.push((left, right + 1));
                    }
                    if left == 0 { break; }
                    left -= 1;
                    right += 1;
                }
            }
        }
        
        palindromes.sort_unstable();
        palindromes.dedup();
        palindromes
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_dna_analysis() {
        let sequence = b"ATCGATCGATCG";
        let repeats = dna::find_tandem_repeats(sequence, 3);
        assert!(!repeats.is_empty());
        
        let gc_content = dna::gc_content_analysis(sequence);
        assert!(gc_content > 0.0 && gc_content <= 1.0);
    }
    
    #[test]
    fn test_text_analysis() {
        let text = b"hello world hello rust world";
        let words = text::word_frequency(text, 2);
        
        assert_eq!(words.get(&b"hello".to_vec()), Some(&2));
        assert_eq!(words.get(&b"world".to_vec()), Some(&2));
        
        let palindromes = text::find_palindromes(b"racecar madam", 3);
        assert!(!palindromes.is_empty());
    }
}
```

## Demo Application

```rust
// src/main.rs
use suffix_arrays::*;
use std::time::Instant;

fn main() {
    println!("Suffix Array Demo");
    println!("================");
    
    demo_basic_functionality();
    demo_performance_comparison();
    demo_advanced_features();
    demo_real_world_applications();
}

fn demo_basic_functionality() {
    println!("\n--- Basic Functionality ---");
    
    let text = b"banana split";
    let sa = build_suffix_array(text);
    
    println!("Text: {:?}", std::str::from_utf8(text).unwrap());
    println!("Suffix array: {:?}", sa.suffix_array());
    
    // Show sorted suffixes
    println!("\nSorted suffixes:");
    for (i, &pos) in sa.suffix_array().iter().enumerate() {
        let suffix = sa.get_suffix(i);
        if let Ok(suffix_str) = std::str::from_utf8(suffix) {
            println!("  {}: '{}' (from position {})", i, suffix_str, pos);
        }
    }
    
    // Pattern search
    let patterns = [b"an", b"na", b"split"];
    for pattern in &patterns {
        let occurrences = sa.find(pattern);
        if let Ok(pattern_str) = std::str::from_utf8(pattern) {
            println!("Pattern '{}' found at positions: {:?}", pattern_str, occurrences);
        }
    }
}

fn demo_performance_comparison() {
    println!("\n--- Performance Comparison ---");
    
    let sizes = [1000, 10000, 50000];
    
    for &size in &sizes {
        let text: Vec<u8> = (0..size).map(|i| (i % 4) as u8 + b'A').collect();
        
        println!("\nText size: {} characters", size);
        
        let results = benchmark_algorithms(&text);
        
        for result in results {
            println!("  {}: {:.3}ms", 
                result.algorithm, 
                result.construction_time.as_millis());
        }
    }
}

fn demo_advanced_features() {
    println!("\n--- Advanced Features ---");
    
    let text = b"abracadabra";
    let mut sa = build_suffix_array(text);
    sa.build_lcp();
    
    println!("Text: {:?}", std::str::from_utf8(text).unwrap());
    
    // Longest repeated substring
    if let Some(longest) = sa.longest_repeated_substring() {
        if let Ok(longest_str) = std::str::from_utf8(longest) {
            println!("Longest repeated substring: '{}'", longest_str);
        }
    }
    
    // All repeated substrings of length 2+
    let repeated = sa.repeated_substrings(2);
    println!("Repeated substrings (length ≥ 2): {:?}", 
        repeated.iter()
            .filter_map(|s| std::str::from_utf8(s).ok())
            .collect::<Vec<_>>());
    
    // Statistics
    let stats = sa.statistics();
    println!("Statistics: {:?}", stats);
}

fn demo_real_world_applications() {
    println!("\n--- Real-World Applications ---");
    
    // DNA analysis
    let dna_sequence = b"ATCGATCGATCGCGATCGATCG";
    println!("DNA sequence: {:?}", std::str::from_utf8(dna_sequence).unwrap());
    
    let tandem_repeats = applications::dna::find_tandem_repeats(dna_sequence, 3);
    println!("Tandem repeats: {:?}", tandem_repeats);
    
    let gc_content = applications::dna::gc_content_analysis(dna_sequence);
    println!("GC content: {:.2}%", gc_content * 100.0);
    
    // Text analysis
    let text = b"the quick brown fox jumps over the lazy dog the fox is quick";
    let word_freq = applications::text::word_frequency(text, 2);
    
    println!("\nWord frequency analysis:");
    let mut freq_vec: Vec<_> = word_freq.iter().collect();
    freq_vec.sort_by(|a, b| b.1.cmp(a.1));
    
    for (word, count) in freq_vec.iter().take(5) {
        if let Ok(word_str) = std::str::from_utf8(word) {
            println!("  '{}': {} occurrences", word_str, count);
        }
    }
}

#[cfg(test)]
mod integration_tests {
    use super::*;
    
    #[test]
    fn test_large_text_processing() {
        // Generate a large text for testing
        let large_text: Vec<u8> = (0..100000)
            .map(|i| (i % 26) as u8 + b'a')
            .collect();
        
        let start = Instant::now();
        let sa = build_suffix_array_with_lcp(&large_text);
        let construction_time = start.elapsed();
        
        println!("Large text ({} chars) construction time: {:?}", 
            large_text.len(), construction_time);
        
        // Test search performance
        let pattern = b"abcdef";
        let start = Instant::now();
        let occurrences = sa.find(pattern);
        let search_time = start.elapsed();
        
        println!("Search time for pattern: {:?}", search_time);
        println!("Found {} occurrences", occurrences.len());
        
        assert!(construction_time.as_millis() < 5000); // Should be under 5 seconds
        assert!(search_time.as_millis() < 100); // Should be under 100ms
    }
}
```

## Usage Examples

Run the demo:
```bash
cargo run --release
```

Run tests:
```bash
cargo test
```

Run benchmarks:
```bash
cargo bench
```

This implementation provides:

1. **Multiple Construction Algorithms**: Naive O(n² log n) and efficient O(n log n) doubling
2. **LCP Array Support**: For advanced string analysis
3. **Pattern Matching**: Exact, approximate, and range queries
4. **Memory Efficiency**: Careful memory management and optional features
5. **Real-world Applications**: DNA analysis, text processing, and more
6. **Performance Benchmarks**: Comprehensive performance testing
7. **Safety**: Rust's memory safety without garbage collection overhead

The implementation demonstrates how suffix arrays can be both theoretically elegant and practically efficient for real-world text processing applications.

<function_calls>
<invoke name="TodoWrite">
<parameter name="todos">[{"id": "1", "content": "Check PROGRESS.md for suffix arrays tutorial completion status", "status": "completed", "priority": "high"}, {"id": "2", "content": "Create suffix arrays tutorial directory and files if not completed", "status": "completed", "priority": "high"}, {"id": "3", "content": "Update PROGRESS.md for suffix arrays tutorial", "status": "in_progress", "priority": "medium"}]