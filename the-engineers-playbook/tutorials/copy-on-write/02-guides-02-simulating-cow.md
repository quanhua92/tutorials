# Simulating CoW: Building a Practical Example

## The Scenario: Large Data Processing

Imagine you're building a data analysis system that processes large datasets. Users frequently want to create "branches" of the data to experiment with different transformations, but they rarely modify the original dataset.

## The Traditional Approach (Expensive)

```python
class TraditionalDataset:
    def __init__(self, data):
        self.data = data
    
    def copy(self):
        # Expensive: full deep copy every time
        import copy
        return TraditionalDataset(copy.deepcopy(self.data))
    
    def transform(self, func):
        # Apply transformation in place
        self.data = [func(item) for item in self.data]
        
    def get_data(self):
        return self.data

# Usage - every copy is expensive
large_dataset = list(range(1000000))  # 1 million numbers
original = TraditionalDataset(large_dataset)

# These copies are all expensive
experiment1 = original.copy()  # Full copy
experiment2 = original.copy()  # Full copy  
experiment3 = original.copy()  # Full copy
```

## The CoW Approach (Efficient)

```python
import copy
import time

class CowDataset:
    def __init__(self, data):
        # Wrap data in a shared container
        self._shared_data = {'data': data, 'ref_count': 1}
    
    def copy(self):
        # Cheap: just share the reference
        new_dataset = CowDataset.__new__(CowDataset)
        new_dataset._shared_data = self._shared_data
        
        # Increment reference count
        self._shared_data['ref_count'] += 1
        
        return new_dataset
    
    def _ensure_private_copy(self):
        # Only copy if data is shared
        if self._shared_data['ref_count'] > 1:
            print(f"Triggering copy (was shared by {self._shared_data['ref_count']} references)")
            
            # Create private copy
            old_shared = self._shared_data
            self._shared_data = {
                'data': copy.deepcopy(old_shared['data']),
                'ref_count': 1
            }
            
            # Decrement old reference count
            old_shared['ref_count'] -= 1
        else:
            print("Data already private, modifying in place")
    
    def transform(self, func):
        # Ensure we have private data before modifying
        self._ensure_private_copy()
        self._shared_data['data'] = [func(item) for item in self._shared_data['data']]
    
    def get_data(self):
        return self._shared_data['data']
    
    def get_ref_count(self):
        return self._shared_data['ref_count']

# Usage - copies are cheap until modification
large_dataset = list(range(1000000))  # 1 million numbers
original = CowDataset(large_dataset)

print("Creating copies...")
start_time = time.time()

experiment1 = original.copy()  # Instant
experiment2 = original.copy()  # Instant
experiment3 = original.copy()  # Instant

end_time = time.time()
print(f"Created 3 copies in {end_time - start_time:.6f} seconds")
print(f"Reference count: {original.get_ref_count()}")  # 4
```

## Demonstrating the Copy Trigger

```python
print("\n--- Before any modifications ---")
print(f"Original ref count: {original.get_ref_count()}")      # 4
print(f"Experiment1 ref count: {experiment1.get_ref_count()}") # 4
print(f"All share same data: {original._shared_data is experiment1._shared_data}")  # True

print("\n--- Modifying experiment1 ---")
experiment1.transform(lambda x: x * 2)  # This triggers the copy!

print(f"Original ref count: {original.get_ref_count()}")      # 3
print(f"Experiment1 ref count: {experiment1.get_ref_count()}") # 1
print(f"Still share same data: {original._shared_data is experiment1._shared_data}")  # False

print("\n--- Modifying experiment2 ---")  
experiment2.transform(lambda x: x + 100)  # This also triggers a copy!

print(f"Original ref count: {original.get_ref_count()}")      # 2
print(f"Experiment2 ref count: {experiment2.get_ref_count()}") # 1
```

## Performance Comparison

Let's measure the difference:

```python
def benchmark_traditional():
    data = list(range(100000))
    original = TraditionalDataset(data)
    
    start = time.time()
    copies = [original.copy() for _ in range(10)]
    end = time.time()
    
    return end - start

def benchmark_cow():
    data = list(range(100000))
    original = CowDataset(data)
    
    start = time.time()
    copies = [original.copy() for _ in range(10)]
    end = time.time()
    
    return end - start

traditional_time = benchmark_traditional()
cow_time = benchmark_cow()

print(f"\nPerformance Comparison:")
print(f"Traditional copying: {traditional_time:.4f} seconds")
print(f"CoW copying: {cow_time:.6f} seconds")
print(f"CoW is {traditional_time / cow_time:.0f}x faster")
```

## The Memory Story

Here's what happens in memory:

```python
# Create visualization of memory usage
import sys

def get_size_mb(obj):
    return sys.getsizeof(obj) / (1024 * 1024)

# Traditional approach
data = list(range(100000))
traditional_original = TraditionalDataset(data)
traditional_copies = [traditional_original.copy() for _ in range(5)]

traditional_memory = sum(get_size_mb(copy.data) for copy in traditional_copies)

# CoW approach  
cow_original = CowDataset(data)
cow_copies = [cow_original.copy() for _ in range(5)]

cow_memory = get_size_mb(cow_original.get_data())  # Only one copy of data

print(f"\nMemory Usage:")
print(f"Traditional: ~{traditional_memory:.1f} MB")
print(f"CoW: ~{cow_memory:.1f} MB")
print(f"Memory savings: {traditional_memory / cow_memory:.0f}x less memory")
```

## Key Insights

1. **Copy Performance**: CoW copying is orders of magnitude faster
2. **Memory Efficiency**: Only one copy of data exists until modification
3. **Transparent Behavior**: Users get copy semantics without copy costs
4. **Write Penalty**: First modification pays the full copy cost
5. **Progressive Copying**: Each modification creates only the copies needed

This pattern is so powerful that it's built into operating systems (process forking), databases (MVCC), and even some programming language string implementations.