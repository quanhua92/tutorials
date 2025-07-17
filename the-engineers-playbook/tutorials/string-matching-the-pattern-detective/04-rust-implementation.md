# Rust Implementation: Safe and Efficient String Matching

## Why Rust for String Matching?

Rust's emphasis on memory safety and zero-cost abstractions makes it ideal for implementing string matching algorithms. The type system prevents common bugs like buffer overflows, while the performance characteristics match those of C/C++.

## Complete KMP Implementation

```rust
/// Knuth-Morris-Pratt string matching implementation
pub struct KmpSearcher {
    pattern: Vec<u8>,
    failure_function: Vec<usize>,
}

impl KmpSearcher {
    /// Create a new KMP searcher for the given pattern
    pub fn new(pattern: &[u8]) -> Self {
        let failure_function = Self::build_failure_function(pattern);
        Self {
            pattern: pattern.to_vec(),
            failure_function,
        }
    }

    /// Build the failure function (also called prefix function)
    fn build_failure_function(pattern: &[u8]) -> Vec<usize> {
        let m = pattern.len();
        let mut failure = vec![0; m];
        
        if m == 0 {
            return failure;
        }
        
        let mut j = 0; // Length of previous longest prefix suffix
        
        for i in 1..m {
            // Handle mismatches by following failure links
            while j > 0 && pattern[i] != pattern[j] {
                j = failure[j - 1];
            }
            
            // If characters match, increment j
            if pattern[i] == pattern[j] {
                j += 1;
            }
            
            failure[i] = j;
        }
        
        failure
    }

    /// Search for all occurrences of the pattern in the text
    pub fn search(&self, text: &[u8]) -> Vec<usize> {
        let n = text.len();
        let m = self.pattern.len();
        
        if m == 0 {
            return Vec::new();
        }
        
        let mut matches = Vec::new();
        let mut j = 0; // Index for pattern
        
        for i in 0..n {
            // Handle mismatches using failure function
            while j > 0 && text[i] != self.pattern[j] {
                j = self.failure_function[j - 1];
            }
            
            // If characters match, advance in pattern
            if text[i] == self.pattern[j] {
                j += 1;
            }
            
            // Check if we've found a complete match
            if j == m {
                matches.push(i - m + 1);
                // Continue searching using failure function
                j = self.failure_function[j - 1];
            }
        }
        
        matches
    }

    /// Get the failure function for debugging
    pub fn failure_function(&self) -> &[usize] {
        &self.failure_function
    }
}
```

## String-friendly Interface

```rust
/// Convenient interface for string searching
impl KmpSearcher {
    /// Create searcher from string
    pub fn from_str(pattern: &str) -> Self {
        Self::new(pattern.as_bytes())
    }

    /// Search in string
    pub fn search_str(&self, text: &str) -> Vec<usize> {
        self.search(text.as_bytes())
    }
}
```

## Usage Examples

```rust
fn main() {
    // Basic usage
    let searcher = KmpSearcher::from_str("ABCAB");
    let text = "ABCABCABCAB";
    let matches = searcher.search_str(text);
    
    println!("Pattern: ABCAB");
    println!("Text: {}", text);
    println!("Matches at positions: {:?}", matches);
    
    // Show failure function
    println!("Failure function: {:?}", searcher.failure_function());
    
    // Verify matches
    for &pos in &matches {
        let end = pos + 5; // Length of "ABCAB"
        println!("Match at {}: '{}'", pos, &text[pos..end]);
    }
}
```

## Advanced Features

### Iterator-based Search

```rust
/// Iterator over match positions
pub struct KmpMatches<'a> {
    searcher: &'a KmpSearcher,
    text: &'a [u8],
    position: usize,
    pattern_state: usize,
}

impl<'a> KmpMatches<'a> {
    fn new(searcher: &'a KmpSearcher, text: &'a [u8]) -> Self {
        Self {
            searcher,
            text,
            position: 0,
            pattern_state: 0,
        }
    }
}

impl<'a> Iterator for KmpMatches<'a> {
    type Item = usize;

    fn next(&mut self) -> Option<Self::Item> {
        let m = self.searcher.pattern.len();
        
        if m == 0 {
            return None;
        }
        
        while self.position < self.text.len() {
            let current_char = self.text[self.position];
            
            // Handle mismatches
            while self.pattern_state > 0 && 
                  current_char != self.searcher.pattern[self.pattern_state] {
                self.pattern_state = self.searcher.failure_function[self.pattern_state - 1];
            }
            
            // Check for match
            if current_char == self.searcher.pattern[self.pattern_state] {
                self.pattern_state += 1;
            }
            
            self.position += 1;
            
            // Check if we found a complete match
            if self.pattern_state == m {
                let match_pos = self.position - m;
                self.pattern_state = self.searcher.failure_function[self.pattern_state - 1];
                return Some(match_pos);
            }
        }
        
        None
    }
}

impl KmpSearcher {
    /// Return an iterator over matches
    pub fn matches<'a>(&'a self, text: &'a [u8]) -> KmpMatches<'a> {
        KmpMatches::new(self, text)
    }
}
```

### Streaming Search

```rust
/// Stateful searcher for streaming data
pub struct StreamingKmpSearcher {
    pattern: Vec<u8>,
    failure_function: Vec<usize>,
    current_state: usize,
    bytes_processed: usize,
}

impl StreamingKmpSearcher {
    pub fn new(pattern: &[u8]) -> Self {
        let failure_function = KmpSearcher::build_failure_function(pattern);
        Self {
            pattern: pattern.to_vec(),
            failure_function,
            current_state: 0,
            bytes_processed: 0,
        }
    }

    /// Process a chunk of data, returning any matches found
    pub fn process_chunk(&mut self, chunk: &[u8]) -> Vec<usize> {
        let mut matches = Vec::new();
        let m = self.pattern.len();
        
        if m == 0 {
            return matches;
        }
        
        for &byte in chunk {
            // Handle mismatches
            while self.current_state > 0 && byte != self.pattern[self.current_state] {
                self.current_state = self.failure_function[self.current_state - 1];
            }
            
            // Check for match
            if byte == self.pattern[self.current_state] {
                self.current_state += 1;
            }
            
            self.bytes_processed += 1;
            
            // Check for complete match
            if self.current_state == m {
                matches.push(self.bytes_processed - m);
                self.current_state = self.failure_function[self.current_state - 1];
            }
        }
        
        matches
    }

    /// Reset the searcher state
    pub fn reset(&mut self) {
        self.current_state = 0;
        self.bytes_processed = 0;
    }
}
```

## Performance Optimizations

### SIMD-Accelerated Search

```rust
#[cfg(target_arch = "x86_64")]
mod simd {
    use std::arch::x86_64::*;
    
    /// SIMD-accelerated first character search
    pub fn find_first_char_simd(text: &[u8], pattern_first: u8) -> Vec<usize> {
        let mut positions = Vec::new();
        let chunks = text.chunks_exact(16);
        let remainder = chunks.remainder();
        
        unsafe {
            let needle = _mm_set1_epi8(pattern_first as i8);
            
            for (chunk_idx, chunk) in chunks.enumerate() {
                let haystack = _mm_loadu_si128(chunk.as_ptr() as *const __m128i);
                let comparison = _mm_cmpeq_epi8(haystack, needle);
                let mask = _mm_movemask_epi8(comparison);
                
                // Check each bit in the mask
                for bit in 0..16 {
                    if (mask & (1 << bit)) != 0 {
                        positions.push(chunk_idx * 16 + bit);
                    }
                }
            }
        }
        
        // Handle remainder
        for (i, &byte) in remainder.iter().enumerate() {
            if byte == pattern_first {
                positions.push(text.len() - remainder.len() + i);
            }
        }
        
        positions
    }
}
```

## Error Handling

```rust
/// Errors that can occur during string matching
#[derive(Debug, Clone)]
pub enum KmpError {
    EmptyPattern,
    InvalidUtf8,
}

impl std::fmt::Display for KmpError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            KmpError::EmptyPattern => write!(f, "Pattern cannot be empty"),
            KmpError::InvalidUtf8 => write!(f, "Invalid UTF-8 sequence"),
        }
    }
}

impl std::error::Error for KmpError {}

/// Result type for KMP operations
pub type KmpResult<T> = Result<T, KmpError>;

impl KmpSearcher {
    /// Create searcher with error handling
    pub fn try_new(pattern: &[u8]) -> KmpResult<Self> {
        if pattern.is_empty() {
            return Err(KmpError::EmptyPattern);
        }
        Ok(Self::new(pattern))
    }
}
```

## Testing and Benchmarks

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_basic_search() {
        let searcher = KmpSearcher::from_str("ABCAB");
        let matches = searcher.search_str("ABCABCABCAB");
        assert_eq!(matches, vec![0, 6]);
    }

    #[test]
    fn test_no_matches() {
        let searcher = KmpSearcher::from_str("XYZ");
        let matches = searcher.search_str("ABCABCABCAB");
        assert_eq!(matches, vec![]);
    }

    #[test]
    fn test_single_character() {
        let searcher = KmpSearcher::from_str("A");
        let matches = searcher.search_str("ABCABCABCAB");
        assert_eq!(matches, vec![0, 3, 6, 9]);
    }

    #[test]
    fn test_failure_function() {
        let searcher = KmpSearcher::from_str("ABCAB");
        assert_eq!(searcher.failure_function(), &[0, 0, 0, 1, 2]);
    }

    #[test]
    fn test_streaming_search() {
        let mut searcher = StreamingKmpSearcher::new(b"ABCAB");
        
        let matches1 = searcher.process_chunk(b"ABCAB");
        assert_eq!(matches1, vec![0]);
        
        let matches2 = searcher.process_chunk(b"CABCAB");
        assert_eq!(matches2, vec![6]);
    }
}

#[cfg(test)]
mod benchmarks {
    use super::*;
    use std::time::Instant;

    #[test]
    fn benchmark_kmp_vs_naive() {
        let pattern = "ABCAB";
        let text = "ABCAB".repeat(10000);
        
        // KMP benchmark
        let searcher = KmpSearcher::from_str(pattern);
        let start = Instant::now();
        let kmp_matches = searcher.search_str(&text);
        let kmp_time = start.elapsed();
        
        // Naive benchmark
        let start = Instant::now();
        let naive_matches = naive_search(&text, pattern);
        let naive_time = start.elapsed();
        
        println!("KMP: {:?}, Naive: {:?}", kmp_time, naive_time);
        assert_eq!(kmp_matches, naive_matches);
    }

    fn naive_search(text: &str, pattern: &str) -> Vec<usize> {
        let text_bytes = text.as_bytes();
        let pattern_bytes = pattern.as_bytes();
        let mut matches = Vec::new();
        
        for i in 0..=text_bytes.len().saturating_sub(pattern_bytes.len()) {
            if text_bytes[i..i + pattern_bytes.len()] == *pattern_bytes {
                matches.push(i);
            }
        }
        
        matches
    }
}
```

## Key Rust Features Utilized

1. **Memory Safety**: No buffer overflows or memory leaks
2. **Zero-cost Abstractions**: Iterator interface with no runtime overhead
3. **Pattern Matching**: Elegant error handling with `Result` types
4. **Ownership System**: Efficient memory management without garbage collection
5. **SIMD Support**: Hardware acceleration for performance-critical paths

This implementation demonstrates how Rust's features enable both safe and efficient string matching, making it suitable for high-performance applications like search engines and text processing systems.