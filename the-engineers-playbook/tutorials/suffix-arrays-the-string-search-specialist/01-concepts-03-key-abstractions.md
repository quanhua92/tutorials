# Key Abstractions: The Building Blocks of Suffix Arrays

## The Suffix Abstraction

A **suffix** is the most fundamental abstraction in suffix array theory. It represents a contiguous substring that extends from some position to the end of the text.

### Mathematical Definition
For a text T of length n, the suffix starting at position i is:
```
Suffix_i = T[i..n-1] = T[i]T[i+1]...T[n-1]
```

### Properties of Suffixes
1. **Complete Coverage**: Every character in the text is the start of exactly one suffix
2. **Hierarchical Structure**: Suffix_i+1 is Suffix_i with its first character removed
3. **Unique Representation**: Each suffix is uniquely identified by its starting position

### Example: Suffixes of "banana"
```
Text: b a n a n a
Pos:  0 1 2 3 4 5

Suffix_0: "banana"  (positions 0-5)
Suffix_1: "anana"   (positions 1-5)  
Suffix_2: "nana"    (positions 2-5)
Suffix_3: "ana"     (positions 3-5)
Suffix_4: "na"      (positions 4-5)
Suffix_5: "a"       (position 5)
```

## The Array Abstraction

The **suffix array** abstracts away the actual suffix strings, storing only their starting positions in sorted lexicographical order.

### Definition
For a text T of length n, the suffix array SA is a permutation of [0, 1, 2, ..., n-1] such that:
```
T[SA[0]..] < T[SA[1]..] < T[SA[2]..] < ... < T[SA[n-1]..]
```

Where < denotes lexicographical ordering.

### The Integer Array Representation
```python
class SuffixArray:
    def __init__(self, text):
        self.text = text
        self.sa = self._build_suffix_array()
    
    def get_suffix(self, sa_index):
        """Get the suffix at position sa_index in sorted order"""
        start_pos = self.sa[sa_index]
        return self.text[start_pos:]
    
    def get_original_position(self, sa_index):
        """Get the original position of the sa_index-th suffix"""
        return self.sa[sa_index]
```

### Space Efficiency
- **Naive storage**: O(n²) space for all suffix strings
- **Suffix array**: O(n) space for position indices only
- **Memory savings**: Factor of n improvement

## The Lexicographical Ordering Abstraction

**Lexicographical order** (dictionary order) is the foundation that makes binary search possible on suffixes.

### Formal Definition
String A comes before string B lexicographically if:
1. A is a proper prefix of B, OR
2. At the first position i where A[i] ≠ B[i], we have A[i] < B[i]

### Implementation
```python
def lexicographical_compare(text, pos1, pos2):
    """Compare suffixes starting at pos1 and pos2"""
    i, j = pos1, pos2
    
    while i < len(text) and j < len(text):
        if text[i] < text[j]:
            return -1  # suffix at pos1 < suffix at pos2
        elif text[i] > text[j]:
            return 1   # suffix at pos1 > suffix at pos2
        i += 1
        j += 1
    
    # One suffix is prefix of the other
    if i == len(text):  # suffix at pos1 is shorter
        return -1
    else:               # suffix at pos2 is shorter
        return 1
```

### Example: Ordering Suffixes of "banana"
```
Original suffixes:     Lexicographically sorted:
0: "banana"           1: "a"        (from position 5)
1: "anana"            2: "ana"      (from position 3)
2: "nana"             3: "anana"    (from position 1)  
3: "ana"              4: "banana"   (from position 0)
4: "na"               5: "na"       (from position 4)
5: "a"                6: "nana"     (from position 2)

Suffix Array: [5, 3, 1, 0, 4, 2]
```

## The Range Query Abstraction

Once suffixes are sorted, pattern matching becomes a **range finding** problem in the suffix array.

### Pattern Occurrence Range
For a pattern P, its occurrences correspond to a contiguous range in the suffix array:
```
[left, right] where all suffixes SA[left] to SA[right] start with pattern P
```

### Binary Search Bounds
```python
def find_pattern_range(suffix_array, text, pattern):
    """Find the range [left, right] of pattern occurrences"""
    
    def suffix_starts_with_pattern(sa_index, pattern):
        start_pos = suffix_array[sa_index]
        return text[start_pos:start_pos + len(pattern)] == pattern
    
    # Find leftmost occurrence
    left = binary_search_left(suffix_array, pattern, suffix_starts_with_pattern)
    
    # Find rightmost occurrence  
    right = binary_search_right(suffix_array, pattern, suffix_starts_with_pattern)
    
    return left, right

def get_all_occurrences(suffix_array, text, pattern):
    """Get all starting positions where pattern occurs"""
    left, right = find_pattern_range(suffix_array, text, pattern)
    return [suffix_array[i] for i in range(left, right + 1)]
```

### Range Query Benefits
- **Exact matching**: Find all occurrences of a pattern
- **Counting**: Count occurrences without listing them
- **Prefix matching**: Find all strings with a given prefix
- **Range queries**: Find all patterns between two lexicographical bounds

## The LCP (Longest Common Prefix) Abstraction

The **LCP array** stores the length of the longest common prefix between adjacent suffixes in the sorted order.

### Definition
```
LCP[i] = length of longest common prefix between suffix SA[i-1] and suffix SA[i]
```

### Example: LCP Array for "banana"
```
Suffix Array: [5, 3, 1, 0, 4, 2]
Suffixes:     ["a", "ana", "anana", "banana", "na", "nana"]

LCP Array: [0, 1, 3, 0, 0, 2]
           |  |  |   |  |  |
           -  a  ana -  -  na
```

Explanation:
- LCP[0] = 0 (no previous suffix)
- LCP[1] = 1 ("a" and "ana" share "a")  
- LCP[2] = 3 ("ana" and "anana" share "ana")
- LCP[3] = 0 ("anana" and "banana" share nothing)
- LCP[4] = 0 ("banana" and "na" share nothing)
- LCP[5] = 2 ("na" and "nana" share "na")

### LCP Applications
- **Efficient construction**: Some algorithms use LCP for faster building
- **String matching**: Optimized pattern searching
- **Compression**: Identify repeated substrings
- **Similarity analysis**: Measure text similarity

## The Sentinel Character Abstraction

A **sentinel character** (usually '$' or null character) is appended to ensure proper suffix ordering.

### Purpose
1. **Unique suffix lengths**: Prevents one suffix from being a prefix of another
2. **Deterministic ordering**: Ensures stable sort results
3. **Algorithm simplification**: Many algorithms assume unique suffixes

### Example with Sentinel
```
Without sentinel "banana":          With sentinel "banana$":
Suffixes: ["banana", "anana",       Suffixes: ["banana$", "anana$",
           "nana", "ana",                     "nana$", "ana$", 
           "na", "a"]                         "na$", "a$", "$"]

Problem: "a" is prefix of "ana"     Solution: All suffixes unique
```

### Implementation Considerations
```python
def add_sentinel(text, sentinel='$'):
    """Add sentinel character smaller than all text characters"""
    return text + sentinel

def remove_sentinel_from_results(positions, text_length):
    """Filter out sentinel position from search results"""
    return [pos for pos in positions if pos < text_length]
```

## The Construction Algorithm Abstraction

Suffix array construction algorithms form a hierarchy of complexity and efficiency:

### Naive Construction: O(n² log n)
```python
def naive_suffix_array(text):
    """Simple but slow construction"""
    suffixes = [(text[i:], i) for i in range(len(text))]
    suffixes.sort()  # O(n² log n) due to string comparisons
    return [pos for suffix, pos in suffixes]
```

### Efficient Construction: O(n log n)
```python
def efficient_suffix_array(text):
    """More efficient using rank-based sorting"""
    # Use character ranks instead of string comparisons
    # Double the comparison length iteratively
    # Reduces string comparison overhead
    pass  # Implementation details in advanced algorithms
```

### Linear Construction: O(n)
Advanced algorithms like SA-IS, DC3 achieve linear time:
- **SA-IS**: Induced sorting with type classification
- **DC3**: Divide-and-conquer with recursive construction
- **Skew Algorithm**: Another linear-time approach

## The Query Interface Abstraction

A well-designed suffix array provides multiple query interfaces:

### Basic Interface
```python
class SuffixArray:
    def find(self, pattern):
        """Find all occurrences of pattern"""
        pass
    
    def count(self, pattern):
        """Count occurrences of pattern"""
        pass
    
    def exists(self, pattern):
        """Check if pattern exists"""
        pass
```

### Advanced Interface
```python
class AdvancedSuffixArray:
    def find_prefix(self, prefix):
        """Find all strings with given prefix"""
        pass
    
    def find_range(self, start_pattern, end_pattern):
        """Find all strings in lexicographical range"""
        pass
    
    def longest_common_substring(self, other_text):
        """Find longest common substring with another text"""
        pass
    
    def repeated_substrings(self, min_length):
        """Find all repeated substrings of minimum length"""
        pass
```

## The Enhanced Suffix Array Abstraction

Modern implementations often bundle related arrays for enhanced functionality:

### The Suffix Array Bundle
```python
class EnhancedSuffixArray:
    def __init__(self, text):
        self.text = text + '$'  # Add sentinel
        self.sa = self._build_suffix_array()
        self.lcp = self._build_lcp_array()
        self.rank = self._build_rank_array()
    
    def _build_rank_array(self):
        """Inverse of suffix array: rank[i] = position of suffix i in SA"""
        rank = [0] * len(self.sa)
        for i, pos in enumerate(self.sa):
            rank[pos] = i
        return rank
```

### Benefits of Enhancement
- **Faster queries**: Precomputed auxiliary information
- **More operations**: Support for complex string algorithms
- **Better constants**: Optimized memory access patterns

## The Generic Algorithm Abstraction

Suffix arrays enable a family of string algorithms through generic patterns:

### Pattern: Range-Based Search
```python
def generic_range_search(suffix_array, text, condition_func):
    """Generic search using any condition function"""
    left = binary_search_left_condition(suffix_array, condition_func)
    right = binary_search_right_condition(suffix_array, condition_func)
    return range(left, right + 1)
```

### Pattern: LCP-Based Analysis
```python
def generic_lcp_analysis(suffix_array, lcp_array, analysis_func):
    """Generic analysis using LCP information"""
    results = []
    for i in range(len(lcp_array)):
        if analysis_func(lcp_array[i], i):
            results.append(suffix_array[i])
    return results
```

## Memory Access Pattern Abstractions

Understanding memory access patterns is crucial for performance:

### Sequential Access (Fast)
```python
# Good: Sequential access to suffix array
for i in range(len(suffix_array)):
    process(suffix_array[i])
```

### Random Access (Slower)
```python
# Potentially slower: Random access to original text
for sa_index in suffix_array:
    process(text[sa_index:])  # Random memory access
```

### Cache-Friendly Design
- **Locality of reference**: Group related operations
- **Prefetching**: Access patterns that enable hardware prefetching
- **Data layout**: Organize data to minimize cache misses

## The Abstraction Hierarchy

Understanding how these abstractions build upon each other:

```
Level 4: Applications (Search engines, Bioinformatics)
Level 3: Algorithms (Pattern matching, Compression)
Level 2: Data Structures (Enhanced suffix arrays, LCP arrays)
Level 1: Core Abstractions (Suffix array, Lexicographical order)
Level 0: Primitives (Arrays, Binary search, String comparison)
```

Each level abstracts away complexity from the levels below while providing powerful building blocks for the levels above.

These abstractions work together to transform the complex problem of text searching into a collection of well-understood, efficient operations on simple data structures. The beauty lies not in any single abstraction, but in how they compose to create a powerful and elegant solution to fundamental string processing problems.