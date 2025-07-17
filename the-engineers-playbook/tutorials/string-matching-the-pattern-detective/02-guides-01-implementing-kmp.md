# Implementing the Knuth-Morris-Pratt Algorithm

## Getting Started: The Big Picture

The KMP algorithm consists of two phases:
1. **Build the failure function**: Analyze the pattern to determine skip distances
2. **Search with skipping**: Use the failure function to avoid redundant comparisons

Let's walk through building KMP step by step, starting with a simple example.

## Phase 1: Building the Failure Function

The failure function tells us where to continue searching after a mismatch. For pattern "ABCAB":

```
Pattern: A B C A B
Index:   0 1 2 3 4
f(i):    0 0 0 1 2
```

### The Algorithm

```python
def build_failure_function(pattern):
    m = len(pattern)
    failure = [0] * m
    j = 0  # length of previous longest prefix suffix
    
    for i in range(1, m):
        while j > 0 and pattern[i] != pattern[j]:
            j = failure[j - 1]
        
        if pattern[i] == pattern[j]:
            j += 1
        
        failure[i] = j
    
    return failure
```

### Walking Through the Example

Let's trace through "ABCAB":

**i = 1**: Compare 'B' with 'A' (position 0)
- No match, j stays 0
- failure[1] = 0

**i = 2**: Compare 'C' with 'A' (position 0)
- No match, j stays 0
- failure[2] = 0

**i = 3**: Compare 'A' with 'A' (position 0)
- Match! j becomes 1
- failure[3] = 1

**i = 4**: Compare 'B' with 'B' (position 1)
- Match! j becomes 2
- failure[4] = 2

The failure function captures the pattern's self-similarity: "AB" appears at both the beginning and end.

## Phase 2: Searching with KMP

Now we use the failure function to search efficiently:

```python
def kmp_search(text, pattern):
    n = len(text)
    m = len(pattern)
    
    if m == 0:
        return []
    
    failure = build_failure_function(pattern)
    matches = []
    j = 0  # index for pattern
    
    for i in range(n):  # index for text
        while j > 0 and text[i] != pattern[j]:
            j = failure[j - 1]
        
        if text[i] == pattern[j]:
            j += 1
        
        if j == m:
            matches.append(i - m + 1)
            j = failure[j - 1]
    
    return matches
```

## Example: Finding "ABCAB" in "ABCABCABCAB"

Let's trace through the search:

```
Text:    A B C A B C A B C A B
Pattern: A B C A B
         ^
         i=0, j=0: Match A, j=1
```

```
Text:    A B C A B C A B C A B
Pattern: A B C A B
           ^
           i=1, j=1: Match B, j=2
```

```
Text:    A B C A B C A B C A B
Pattern: A B C A B
             ^
             i=2, j=2: Match C, j=3
```

```
Text:    A B C A B C A B C A B
Pattern: A B C A B
               ^
               i=3, j=3: Match A, j=4
```

```
Text:    A B C A B C A B C A B
Pattern: A B C A B
                 ^
                 i=4, j=4: Match B, j=5 (FOUND MATCH!)
```

After finding a match, we use the failure function to continue searching:
- j = failure[4] = 2
- We can skip ahead because "AB" appears at the end of our pattern

## The Key Insight: Why This Works

The magic happens in this line:
```python
j = failure[j - 1]
```

When we encounter a mismatch, instead of starting over, we jump to the position indicated by the failure function. This position represents the longest prefix of the pattern that's also a suffix of what we've matched so far.

## Visualizing the Skip

When searching for "ABCAB" in "ABCABCABCAB":

```
Text:    A B C A B C A B C A B
Pattern: A B C A B
                 ^
                 Mismatch here (C vs B)
```

Instead of starting over at position 1:
```
Text:    A B C A B C A B C A B
Pattern:   A B C A B
           ^
           Don't do this!
```

We jump to position 2 (failure[3] = 1 means we can skip 2 positions):
```
Text:    A B C A B C A B C A B
Pattern:     A B C A B
             ^
             Jump here instead!
```

## Time Complexity Analysis

- **Preprocessing**: O(m) - we visit each pattern character at most twice
- **Searching**: O(n) - each text character is examined at most once
- **Total**: O(n + m) - linear in the input size

The key insight is that the inner while loop doesn't increase the overall complexity. Though we might "back up" in the pattern, we never back up in the text, ensuring linear time.

## A Complete Example

```python
def kmp_demo():
    text = "ABCABCABCAB"
    pattern = "ABCAB"
    
    print(f"Text: {text}")
    print(f"Pattern: {pattern}")
    
    failure = build_failure_function(pattern)
    print(f"Failure function: {failure}")
    
    matches = kmp_search(text, pattern)
    print(f"Matches found at positions: {matches}")
    
    # Verify matches
    for pos in matches:
        print(f"Match at {pos}: '{text[pos:pos+len(pattern)]}'")

kmp_demo()
```

Output:
```
Text: ABCABCABCAB
Pattern: ABCAB
Failure function: [0, 0, 0, 1, 2]
Matches found at positions: [0, 6]
Match at 0: 'ABCAB'
Match at 6: 'ABCAB'
```

## Common Pitfalls

1. **Off-by-one errors**: Remember that the failure function is zero-indexed
2. **Empty pattern**: Handle the edge case where the pattern is empty
3. **After finding a match**: Use the failure function to continue searching, don't start over

## Real-World Applications

This same algorithm is used in:
- **Text editors** for find/replace operations
- **grep** and other search utilities
- **DNA sequence analysis** in bioinformatics
- **Network intrusion detection** systems

The KMP algorithm proves that with the right preprocessing, we can search through massive texts efficiently, making it a cornerstone of modern text processing systems.