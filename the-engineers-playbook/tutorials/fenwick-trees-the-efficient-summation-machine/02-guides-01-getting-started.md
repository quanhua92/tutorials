# Getting Started: Building Your First Fenwick Tree

This guide walks you through implementing a Fenwick Tree from scratch, showing each operation step by step with clear examples.

## Prerequisites

Basic understanding of:
- Arrays and indexing
- Binary representation of numbers
- Basic bit operations (`&`, `|`, `~`)

## Step 1: The Basic Structure

Let's start with a simple Fenwick Tree class:

```python
class FenwickTree:
    def __init__(self, size):
        self.size = size
        self.tree = [0] * (size + 1)  # 1-indexed array
    
    def _lowest_set_bit(self, i):
        """Find the lowest set bit using two's complement."""
        return i & -i
    
    def update(self, idx, delta):
        """Add delta to element at idx (1-indexed)."""
        while idx <= self.size:
            self.tree[idx] += delta
            idx += self._lowest_set_bit(idx)
    
    def prefix_sum(self, idx):
        """Get sum of elements from 1 to idx."""
        result = 0
        while idx > 0:
            result += self.tree[idx]
            idx -= self._lowest_set_bit(idx)
        return result
    
    def range_sum(self, left, right):
        """Get sum of elements from left to right (inclusive)."""
        if left == 1:
            return self.prefix_sum(right)
        return self.prefix_sum(right) - self.prefix_sum(left - 1)
```

## Step 2: Understanding the Low-Bit Operation

Let's visualize how `i & -i` works:

```python
def demonstrate_low_bit():
    print("Index | Binary | -Index | Binary | Low-bit | Responsibility")
    print("-" * 60)
    
    for i in range(1, 9):
        neg_i = -i & 0xFF  # Show only 8 bits for clarity
        low_bit = i & -i
        responsibility = low_bit
        
        print(f"{i:5} | {i:06b} | {neg_i:6} | {neg_i:06b} | {low_bit:7} | {responsibility}")

# Output:
# Index | Binary | -Index | Binary | Low-bit | Responsibility
# ------------------------------------------------------------
#     1 | 000001 |   -1 | 111111 |       1 | 1
#     2 | 000010 |   -2 | 111110 |       2 | 2
#     3 | 000011 |   -3 | 111101 |       1 | 1
#     4 | 000100 |   -4 | 111100 |       4 | 4
#     5 | 000101 |   -5 | 111011 |       1 | 1
#     6 | 000110 |   -6 | 111010 |       2 | 2
#     7 | 000111 |   -7 | 111001 |       1 | 1
#     8 | 001000 |   -8 | 111000 |       8 | 8
```

## Step 3: Building from an Array

Let's create a Fenwick Tree from an existing array:

```python
def build_fenwick_tree(arr):
    """Build a Fenwick Tree from array (0-indexed input)."""
    n = len(arr)
    fenwick = FenwickTree(n)
    
    # Method 1: Use update operations (O(n log n))
    for i, val in enumerate(arr):
        fenwick.update(i + 1, val)  # Convert to 1-indexed
    
    return fenwick

# Alternative: O(n) construction
def build_fenwick_tree_fast(arr):
    """Build a Fenwick Tree in O(n) time."""
    n = len(arr)
    tree = [0] * (n + 1)
    
    # Copy array to tree (1-indexed)
    for i in range(n):
        tree[i + 1] = arr[i]
    
    # Build tree bottom-up
    for i in range(1, n + 1):
        parent = i + (i & -i)
        if parent <= n:
            tree[parent] += tree[i]
    
    fenwick = FenwickTree(n)
    fenwick.tree = tree
    return fenwick
```

## Step 4: Step-by-Step Example

Let's trace through building and querying a Fenwick Tree:

```python
def step_by_step_example():
    # Original array: [3, 2, -1, 6, 5, 4, -3, 2]
    arr = [3, 2, -1, 6, 5, 4, -3, 2]
    print(f"Original array: {arr}")
    
    # Build Fenwick Tree
    ft = build_fenwick_tree(arr)
    print(f"Fenwick Tree: {ft.tree[1:]}")  # Skip index 0
    
    # Show what each index stores
    print("\nFenwick Tree contents:")
    for i in range(1, len(ft.tree)):
        responsibility = i & -i
        start = i - responsibility + 1
        print(f"tree[{i}] = {ft.tree[i]:3} (covers range [{start}..{i}])")
    
    # Example queries
    print("\nQueries:")
    print(f"Sum[1..3] = {ft.range_sum(1, 3)}")
    print(f"Sum[4..6] = {ft.range_sum(4, 6)}")
    print(f"Sum[1..8] = {ft.range_sum(1, 8)}")
    
    # Example update
    print(f"\nUpdate: Add 10 to index 3")
    ft.update(3, 10)
    print(f"New sum[1..3] = {ft.range_sum(1, 3)}")
    print(f"New sum[1..8] = {ft.range_sum(1, 8)}")

# Output:
# Original array: [3, 2, -1, 6, 5, 4, -3, 2]
# Fenwick Tree: [3, 5, -1, 10, 5, 9, -3, 18]
# 
# Fenwick Tree contents:
# tree[1] =   3 (covers range [1..1])
# tree[2] =   5 (covers range [1..2])
# tree[3] =  -1 (covers range [3..3])
# tree[4] =  10 (covers range [1..4])
# tree[5] =   5 (covers range [5..5])
# tree[6] =   9 (covers range [5..6])
# tree[7] =  -3 (covers range [7..7])
# tree[8] =  18 (covers range [1..8])
```

## Step 5: Visualizing Operations

### Query Operation Trace

```python
def trace_query(ft, idx):
    """Trace a prefix sum query step by step."""
    print(f"\nTracing prefix_sum({idx}):")
    result = 0
    original_idx = idx
    
    while idx > 0:
        print(f"  idx = {idx} (binary: {idx:08b})")
        print(f"  Add tree[{idx}] = {ft.tree[idx]}")
        result += ft.tree[idx]
        
        low_bit = idx & -idx
        print(f"  Low bit = {low_bit}")
        idx -= low_bit
        print(f"  Next idx = {idx}")
        print()
    
    print(f"Final result: prefix_sum({original_idx}) = {result}")

# Example usage:
# trace_query(ft, 6)
# Output:
# Tracing prefix_sum(6):
#   idx = 6 (binary: 00000110)
#   Add tree[6] = 9
#   Low bit = 2
#   Next idx = 4
#
#   idx = 4 (binary: 00000100)
#   Add tree[4] = 10
#   Low bit = 4
#   Next idx = 0
#
# Final result: prefix_sum(6) = 19
```

### Update Operation Trace

```python
def trace_update(ft, idx, delta):
    """Trace an update operation step by step."""
    print(f"\nTracing update({idx}, {delta}):")
    original_idx = idx
    
    while idx <= ft.size:
        print(f"  idx = {idx} (binary: {idx:08b})")
        print(f"  Update tree[{idx}]: {ft.tree[idx]} + {delta} = {ft.tree[idx] + delta}")
        ft.tree[idx] += delta
        
        low_bit = idx & -idx
        print(f"  Low bit = {low_bit}")
        idx += low_bit
        print(f"  Next idx = {idx}")
        print()

# Example usage:
# trace_update(ft, 3, 5)
# Output:
# Tracing update(3, 5):
#   idx = 3 (binary: 00000011)
#   Update tree[3]: -1 + 5 = 4
#   Low bit = 1
#   Next idx = 4
#
#   idx = 4 (binary: 00000100)
#   Update tree[4]: 10 + 5 = 15
#   Low bit = 4
#   Next idx = 8
#
#   idx = 8 (binary: 00001000)
#   Update tree[8]: 18 + 5 = 23
#   Low bit = 8
#   Next idx = 16
```

## Step 6: Complete Working Example

Here's a complete example you can run:

```python
class FenwickTree:
    def __init__(self, size):
        self.size = size
        self.tree = [0] * (size + 1)
    
    def update(self, idx, delta):
        while idx <= self.size:
            self.tree[idx] += delta
            idx += idx & -idx
    
    def prefix_sum(self, idx):
        result = 0
        while idx > 0:
            result += self.tree[idx]
            idx -= idx & -idx
        return result
    
    def range_sum(self, left, right):
        if left == 1:
            return self.prefix_sum(right)
        return self.prefix_sum(right) - self.prefix_sum(left - 1)
    
    def __str__(self):
        return f"FenwickTree({self.tree[1:]})"

def main():
    # Create and populate Fenwick Tree
    arr = [3, 2, -1, 6, 5, 4, -3, 2]
    ft = FenwickTree(len(arr))
    
    for i, val in enumerate(arr):
        ft.update(i + 1, val)
    
    print(f"Original array: {arr}")
    print(f"Fenwick Tree: {ft}")
    
    # Test queries
    test_cases = [
        (1, 3),   # Sum of first 3 elements
        (4, 6),   # Sum of elements 4-6
        (1, 8),   # Sum of all elements
        (5, 5),   # Single element
    ]
    
    for left, right in test_cases:
        result = ft.range_sum(left, right)
        actual = sum(arr[left-1:right])
        print(f"Sum[{left}..{right}] = {result} (verify: {actual})")
    
    # Test update
    print(f"\nBefore update: Sum[1..8] = {ft.range_sum(1, 8)}")
    ft.update(3, 10)  # Add 10 to element at index 3
    print(f"After adding 10 to index 3: Sum[1..8] = {ft.range_sum(1, 8)}")

if __name__ == "__main__":
    main()
```

## Key Points to Remember

1. **1-indexed**: Fenwick Trees work with 1-indexed arrays (index 0 is unused)
2. **Low-bit operation**: `i & -i` is the fundamental operation for navigation
3. **Update path**: Goes "up" the tree by adding the low bit
4. **Query path**: Goes "down" the tree by subtracting the low bit
5. **Range queries**: Use prefix sums: `sum[i..j] = prefix[j] - prefix[i-1]`

## Common Pitfalls

1. **Off-by-one errors**: Remember the 1-indexed nature
2. **Negative indices**: Never let indices become 0 or negative during operations
3. **Array bounds**: Check that updates don't exceed the tree size
4. **Integer overflow**: Be careful with large sums

## Performance Verification

```python
import time
import random

def benchmark_fenwick_vs_naive():
    n = 100000
    arr = [random.randint(-100, 100) for _ in range(n)]
    
    # Build Fenwick Tree
    ft = FenwickTree(n)
    for i, val in enumerate(arr):
        ft.update(i + 1, val)
    
    # Benchmark queries
    queries = [(random.randint(1, n//2), random.randint(n//2, n)) for _ in range(1000)]
    
    # Fenwick Tree queries
    start = time.time()
    for left, right in queries:
        ft.range_sum(left, right)
    fenwick_time = time.time() - start
    
    # Naive queries
    start = time.time()
    for left, right in queries:
        sum(arr[left-1:right])
    naive_time = time.time() - start
    
    print(f"Fenwick Tree: {fenwick_time:.4f}s")
    print(f"Naive approach: {naive_time:.4f}s")
    print(f"Speedup: {naive_time/fenwick_time:.1f}x")
```

This implementation gives you a solid foundation for understanding and using Fenwick Trees. The next section dives deep into the mathematical magic behind the low-bit operation.