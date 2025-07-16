# Simple Memoization: Your First Cache Implementation

## Introduction: The Power of Remembering

Memoization is the simplest and most elegant form of caching. It's the practice of storing the results of expensive function calls and returning the cached result when the same inputs occur again. This guide will take you from basic memoization concepts to production-ready implementations.

We'll use the classic Fibonacci sequence as our example, then expand to real-world applications like database queries, API calls, and complex computations.

## The Problem: Exponential Inefficiency

### The Naive Fibonacci Implementation

Let's start with the classic example of inefficient recursion:

```python
def fibonacci_naive(n):
    """Naive recursive Fibonacci - exponentially slow"""
    if n <= 1:
        return n
    return fibonacci_naive(n-1) + fibonacci_naive(n-2)

# Test the performance
import time

def time_fibonacci(n):
    start = time.time()
    result = fibonacci_naive(n)
    end = time.time()
    print(f"fibonacci_naive({n}) = {result}")
    print(f"Time taken: {end - start:.4f} seconds")
    return result

# Watch it get exponentially slower
for i in [10, 20, 30, 35]:
    time_fibonacci(i)
    print()
```

**Expected output:**
```
fibonacci_naive(10) = 55
Time taken: 0.0001 seconds

fibonacci_naive(20) = 6765
Time taken: 0.0023 seconds

fibonacci_naive(30) = 832040
Time taken: 0.2876 seconds

fibonacci_naive(35) = 9227465
Time taken: 3.4521 seconds
```

### Understanding the Inefficiency

The problem is massive redundant computation:

```python
def fibonacci_with_count(n, call_count=None):
    """Fibonacci with call counting to show redundancy"""
    if call_count is None:
        call_count = {'count': 0}
    
    call_count['count'] += 1
    print(f"  Computing fibonacci({n})")
    
    if n <= 1:
        return n
    
    return (fibonacci_with_count(n-1, call_count) + 
            fibonacci_with_count(n-2, call_count))

# Show the redundancy
print("Computing fibonacci(5):")
result = fibonacci_with_count(5)
print(f"Result: {result}")
print(f"Total function calls: {call_count['count']}")
```

**Output:**
```
Computing fibonacci(5):
  Computing fibonacci(5)
  Computing fibonacci(4)
  Computing fibonacci(3)
  Computing fibonacci(2)
  Computing fibonacci(1)
  Computing fibonacci(0)
  Computing fibonacci(1)
  Computing fibonacci(2)
  Computing fibonacci(1)
  Computing fibonacci(0)
  Computing fibonacci(3)
  Computing fibonacci(2)
  Computing fibonacci(1)
  Computing fibonacci(0)
  Computing fibonacci(1)
Result: 5
Total function calls: 15
```

Notice how `fibonacci(1)` is computed 5 times, `fibonacci(2)` is computed 3 times, etc. This redundancy grows exponentially.

## Solution 1: Manual Memoization

### Building Your Own Cache

Let's implement manual memoization to understand the concept:

```python
def fibonacci_manual_memo(n, memo=None):
    """Fibonacci with manual memoization"""
    if memo is None:
        memo = {}
    
    # Check if result is already cached
    if n in memo:
        print(f"  Cache hit for fibonacci({n})")
        return memo[n]
    
    print(f"  Computing fibonacci({n})")
    
    # Base cases
    if n <= 1:
        result = n
    else:
        result = (fibonacci_manual_memo(n-1, memo) + 
                 fibonacci_manual_memo(n-2, memo))
    
    # Store result in cache
    memo[n] = result
    return result

# Test the memoized version
print("Computing fibonacci(10) with memoization:")
result = fibonacci_manual_memo(10)
print(f"Result: {result}")
print()

# Compare performance
import time

def compare_fibonacci_performance():
    """Compare naive vs memoized Fibonacci"""
    test_values = [10, 20, 30, 35, 40]
    
    print("Performance Comparison:")
    print("=" * 60)
    print(f"{'n':<4} {'Naive Time':<12} {'Memo Time':<12} {'Speedup':<10}")
    print("-" * 60)
    
    for n in test_values:
        # Time naive version (skip large values)
        if n <= 35:
            start = time.time()
            naive_result = fibonacci_naive(n)
            naive_time = time.time() - start
        else:
            naive_time = float('inf')  # Too slow to measure
            naive_result = "Too slow"
        
        # Time memoized version
        start = time.time()
        memo_result = fibonacci_manual_memo(n)
        memo_time = time.time() - start
        
        # Calculate speedup
        if naive_time != float('inf'):
            speedup = naive_time / memo_time
            print(f"{n:<4} {naive_time:<12.4f} {memo_time:<12.4f} {speedup:<10.0f}x")
        else:
            print(f"{n:<4} {'Too slow':<12} {memo_time:<12.4f} {'∞':<10}")

compare_fibonacci_performance()
```

### Enhanced Manual Memoization

Let's add features like cache statistics and size limits:

```python
class MemoizationCache:
    """A reusable memoization cache with statistics"""
    
    def __init__(self, max_size=1000):
        self.cache = {}
        self.max_size = max_size
        self.stats = {
            'hits': 0,
            'misses': 0,
            'evictions': 0
        }
        self.access_order = []  # For LRU eviction
    
    def get(self, key):
        """Get value from cache"""
        if key in self.cache:
            self.stats['hits'] += 1
            # Update access order for LRU
            self.access_order.remove(key)
            self.access_order.append(key)
            return self.cache[key]
        
        self.stats['misses'] += 1
        return None
    
    def put(self, key, value):
        """Store value in cache"""
        if len(self.cache) >= self.max_size and key not in self.cache:
            # Evict least recently used item
            lru_key = self.access_order.pop(0)
            del self.cache[lru_key]
            self.stats['evictions'] += 1
        
        self.cache[key] = value
        
        # Update access order
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)
    
    def get_stats(self):
        """Get cache statistics"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = self.stats['hits'] / total_requests if total_requests > 0 else 0
        
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'evictions': self.stats['evictions'],
            'hit_rate': hit_rate,
            'utilization': len(self.cache) / self.max_size
        }
    
    def clear(self):
        """Clear cache and reset statistics"""
        self.cache.clear()
        self.access_order.clear()
        self.stats = {'hits': 0, 'misses': 0, 'evictions': 0}

# Enhanced Fibonacci with statistics
def fibonacci_with_stats(n, cache=None):
    """Fibonacci with cache statistics"""
    if cache is None:
        cache = MemoizationCache()
    
    # Check cache first
    cached_result = cache.get(n)
    if cached_result is not None:
        return cached_result
    
    # Compute result
    if n <= 1:
        result = n
    else:
        result = (fibonacci_with_stats(n-1, cache) + 
                 fibonacci_with_stats(n-2, cache))
    
    # Store in cache
    cache.put(n, result)
    return result

# Test with statistics
cache = MemoizationCache(max_size=50)

print("Computing fibonacci(40) with statistics:")
result = fibonacci_with_stats(40, cache)
print(f"Result: {result}")

stats = cache.get_stats()
print(f"\nCache Statistics:")
print(f"  Cache size: {stats['size']}/{stats['max_size']}")
print(f"  Hit rate: {stats['hit_rate']:.1%}")
print(f"  Hits: {stats['hits']}")
print(f"  Misses: {stats['misses']}")
print(f"  Evictions: {stats['evictions']}")
print(f"  Utilization: {stats['utilization']:.1%}")
```

## Solution 2: Python's Built-in LRU Cache

### Using functools.lru_cache

Python provides a built-in decorator for memoization:

```python
from functools import lru_cache

@lru_cache(maxsize=128)
def fibonacci_lru(n):
    """Fibonacci with built-in LRU cache"""
    if n <= 1:
        return n
    return fibonacci_lru(n-1) + fibonacci_lru(n-2)

# Test the LRU cache version
print("Testing fibonacci_lru(40):")
start = time.time()
result = fibonacci_lru(40)
end = time.time()

print(f"Result: {result}")
print(f"Time: {end - start:.4f} seconds")

# Check cache statistics
print(f"Cache info: {fibonacci_lru.cache_info()}")
```

### LRU Cache with Custom Parameters

```python
from functools import lru_cache, wraps

def custom_lru_cache(maxsize=128, typed=False):
    """Custom LRU cache decorator with logging"""
    def decorator(func):
        cached_func = lru_cache(maxsize=maxsize, typed=typed)(func)
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Log cache access
            cache_info = cached_func.cache_info()
            
            result = cached_func(*args, **kwargs)
            
            # Log cache statistics periodically
            new_cache_info = cached_func.cache_info()
            if new_cache_info.hits > cache_info.hits:
                print(f"Cache hit for {func.__name__}{args}")
            else:
                print(f"Cache miss for {func.__name__}{args}")
            
            return result
        
        wrapper.cache_info = cached_func.cache_info
        wrapper.cache_clear = cached_func.cache_clear
        return wrapper
    
    return decorator

@custom_lru_cache(maxsize=64)
def fibonacci_custom_lru(n):
    """Fibonacci with custom LRU cache"""
    if n <= 1:
        return n
    return fibonacci_custom_lru(n-1) + fibonacci_custom_lru(n-2)

# Test custom LRU cache
print("Testing custom LRU cache:")
result = fibonacci_custom_lru(10)
print(f"Result: {result}")
print(f"Cache info: {fibonacci_custom_lru.cache_info()}")
```

## Real-World Application: Database Query Memoization

### Memoizing Database Queries

Let's apply memoization to a more realistic scenario:

```python
import sqlite3
import time
from functools import lru_cache

# Setup: Create a sample database
def setup_database():
    """Create sample database with user data"""
    conn = sqlite3.connect(':memory:')
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            email TEXT,
            created_at TIMESTAMP
        )
    ''')
    
    # Insert sample data
    import datetime
    for i in range(10000):
        cursor.execute('''
            INSERT INTO users (username, email, created_at)
            VALUES (?, ?, ?)
        ''', (f'user_{i}', f'user_{i}@example.com', datetime.datetime.now()))
    
    conn.commit()
    return conn

# Database query functions
class UserDatabase:
    def __init__(self, connection):
        self.conn = connection
        self.query_count = 0
    
    def get_user_by_id_uncached(self, user_id):
        """Get user by ID without caching"""
        self.query_count += 1
        cursor = self.conn.cursor()
        
        # Add artificial delay to simulate slow query
        time.sleep(0.01)  # 10ms delay
        
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        return cursor.fetchone()
    
    @lru_cache(maxsize=1000)
    def get_user_by_id_cached(self, user_id):
        """Get user by ID with caching"""
        self.query_count += 1
        cursor = self.conn.cursor()
        
        # Add artificial delay to simulate slow query
        time.sleep(0.01)  # 10ms delay
        
        cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
        return cursor.fetchone()
    
    def get_user_stats(self, user_id):
        """Get user statistics - expensive computation"""
        user = self.get_user_by_id_cached(user_id)
        if not user:
            return None
        
        # Simulate expensive computation
        time.sleep(0.05)  # 50ms delay
        
        return {
            'user_id': user[0],
            'username': user[1],
            'email': user[2],
            'account_age_days': (datetime.datetime.now() - user[3]).days,
            'computed_score': hash(user[1]) % 1000  # Fake score
        }

# Test database caching
def test_database_caching():
    """Test database query caching performance"""
    conn = setup_database()
    db = UserDatabase(conn)
    
    # Test data: some repeated user IDs
    test_user_ids = [1, 2, 3, 1, 4, 2, 5, 1, 3, 6, 7, 1, 2, 8, 9, 1]
    
    print("Testing database query caching:")
    print("=" * 50)
    
    # Test uncached version
    print("Uncached queries:")
    start = time.time()
    uncached_results = []
    for user_id in test_user_ids:
        result = db.get_user_by_id_uncached(user_id)
        uncached_results.append(result)
    uncached_time = time.time() - start
    
    print(f"  Time: {uncached_time:.4f} seconds")
    print(f"  Queries: {db.query_count}")
    
    # Reset query count
    db.query_count = 0
    
    # Test cached version
    print("\nCached queries:")
    start = time.time()
    cached_results = []
    for user_id in test_user_ids:
        result = db.get_user_by_id_cached(user_id)
        cached_results.append(result)
    cached_time = time.time() - start
    
    print(f"  Time: {cached_time:.4f} seconds")
    print(f"  Queries: {db.query_count}")
    print(f"  Cache info: {db.get_user_by_id_cached.cache_info()}")
    
    # Calculate improvements
    speedup = uncached_time / cached_time
    query_reduction = (len(test_user_ids) - db.query_count) / len(test_user_ids)
    
    print(f"\nImprovements:")
    print(f"  Speedup: {speedup:.1f}x")
    print(f"  Query reduction: {query_reduction:.1%}")

test_database_caching()
```

## Advanced Memoization Techniques

### Time-Based Cache Invalidation

```python
import time
from functools import wraps

def timed_cache(ttl_seconds=300):
    """Cache with time-to-live (TTL) expiration"""
    def decorator(func):
        cache = {}
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key
            key = str(args) + str(sorted(kwargs.items()))
            current_time = time.time()
            
            # Check if cached result is still valid
            if key in cache:
                result, timestamp = cache[key]
                if current_time - timestamp < ttl_seconds:
                    print(f"Cache hit for {func.__name__}{args}")
                    return result
                else:
                    print(f"Cache expired for {func.__name__}{args}")
                    del cache[key]
            
            # Compute and cache result
            print(f"Computing {func.__name__}{args}")
            result = func(*args, **kwargs)
            cache[key] = (result, current_time)
            
            return result
        
        wrapper.cache_clear = lambda: cache.clear()
        wrapper.cache_info = lambda: {'size': len(cache), 'ttl': ttl_seconds}
        return wrapper
    
    return decorator

@timed_cache(ttl_seconds=5)  # 5 second TTL
def get_current_weather(city):
    """Simulate expensive weather API call"""
    time.sleep(1)  # Simulate network delay
    return f"Weather in {city}: 72°F, sunny"

# Test time-based caching
print("Testing time-based caching:")
print("=" * 30)

# First call - cache miss
result1 = get_current_weather("New York")
print(f"Result 1: {result1}")

# Second call - cache hit
result2 = get_current_weather("New York")
print(f"Result 2: {result2}")

# Wait for cache to expire
print("Waiting for cache to expire...")
time.sleep(6)

# Third call - cache expired
result3 = get_current_weather("New York")
print(f"Result 3: {result3}")
```

### Conditional Caching

```python
def conditional_cache(condition_func):
    """Cache only when condition is met"""
    def decorator(func):
        cache = {}
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if we should use cache
            if not condition_func(*args, **kwargs):
                print(f"Condition not met, bypassing cache for {func.__name__}")
                return func(*args, **kwargs)
            
            # Use cache
            key = str(args) + str(sorted(kwargs.items()))
            
            if key in cache:
                print(f"Cache hit for {func.__name__}{args}")
                return cache[key]
            
            print(f"Cache miss for {func.__name__}{args}")
            result = func(*args, **kwargs)
            cache[key] = result
            
            return result
        
        wrapper.cache_clear = lambda: cache.clear()
        wrapper.cache_info = lambda: {'size': len(cache)}
        return wrapper
    
    return decorator

# Cache only for expensive computations (n > 20)
@conditional_cache(lambda n: n > 20)
def expensive_computation(n):
    """Expensive computation that we only want to cache for large n"""
    time.sleep(0.1)  # Simulate expensive operation
    return n * n + 2 * n + 1

# Test conditional caching
print("Testing conditional caching:")
print("=" * 30)

# Small n - no caching
result1 = expensive_computation(5)
print(f"Result for 5: {result1}")

result2 = expensive_computation(5)  # Should not use cache
print(f"Result for 5 (repeat): {result2}")

# Large n - caching enabled
result3 = expensive_computation(25)
print(f"Result for 25: {result3}")

result4 = expensive_computation(25)  # Should use cache
print(f"Result for 25 (repeat): {result4}")
```

### Multi-Level Caching

```python
class MultiLevelCache:
    """Multi-level cache with different characteristics"""
    
    def __init__(self):
        # L1: Small, fast cache
        self.l1_cache = {}
        self.l1_max_size = 10
        self.l1_access_order = []
        
        # L2: Larger, slower cache
        self.l2_cache = {}
        self.l2_max_size = 100
        self.l2_access_order = []
        
        # Statistics
        self.stats = {
            'l1_hits': 0,
            'l2_hits': 0,
            'misses': 0
        }
    
    def get(self, key):
        """Get from multi-level cache"""
        # Check L1 first
        if key in self.l1_cache:
            self.stats['l1_hits'] += 1
            self.l1_access_order.remove(key)
            self.l1_access_order.append(key)
            return self.l1_cache[key]
        
        # Check L2
        if key in self.l2_cache:
            self.stats['l2_hits'] += 1
            value = self.l2_cache[key]
            
            # Promote to L1
            self.put_l1(key, value)
            
            # Update L2 access order
            self.l2_access_order.remove(key)
            self.l2_access_order.append(key)
            
            return value
        
        # Cache miss
        self.stats['misses'] += 1
        return None
    
    def put(self, key, value):
        """Put in multi-level cache"""
        # Always put in L1 first
        self.put_l1(key, value)
        
        # Also put in L2
        self.put_l2(key, value)
    
    def put_l1(self, key, value):
        """Put in L1 cache"""
        if len(self.l1_cache) >= self.l1_max_size and key not in self.l1_cache:
            # Evict LRU from L1
            lru_key = self.l1_access_order.pop(0)
            del self.l1_cache[lru_key]
        
        self.l1_cache[key] = value
        if key in self.l1_access_order:
            self.l1_access_order.remove(key)
        self.l1_access_order.append(key)
    
    def put_l2(self, key, value):
        """Put in L2 cache"""
        if len(self.l2_cache) >= self.l2_max_size and key not in self.l2_cache:
            # Evict LRU from L2
            lru_key = self.l2_access_order.pop(0)
            del self.l2_cache[lru_key]
        
        self.l2_cache[key] = value
        if key in self.l2_access_order:
            self.l2_access_order.remove(key)
        self.l2_access_order.append(key)
    
    def get_stats(self):
        """Get cache statistics"""
        total_requests = sum(self.stats.values())
        
        return {
            'l1_hits': self.stats['l1_hits'],
            'l2_hits': self.stats['l2_hits'],
            'misses': self.stats['misses'],
            'l1_hit_rate': self.stats['l1_hits'] / total_requests if total_requests > 0 else 0,
            'l2_hit_rate': self.stats['l2_hits'] / total_requests if total_requests > 0 else 0,
            'overall_hit_rate': (self.stats['l1_hits'] + self.stats['l2_hits']) / total_requests if total_requests > 0 else 0,
            'l1_size': len(self.l1_cache),
            'l2_size': len(self.l2_cache)
        }

def multi_level_memoization(func):
    """Decorator using multi-level cache"""
    cache = MultiLevelCache()
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        key = str(args) + str(sorted(kwargs.items()))
        
        # Check cache
        result = cache.get(key)
        if result is not None:
            return result
        
        # Compute and cache
        result = func(*args, **kwargs)
        cache.put(key, result)
        
        return result
    
    wrapper.cache_stats = lambda: cache.get_stats()
    wrapper.cache_clear = lambda: cache.__init__()
    return wrapper

@multi_level_memoization
def complex_computation(n):
    """Complex computation for testing multi-level cache"""
    time.sleep(0.01)  # Simulate computation time
    return sum(i * i for i in range(n))

# Test multi-level caching
print("Testing multi-level caching:")
print("=" * 30)

# Generate access pattern
access_pattern = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 
                 1, 2, 3, 13, 14, 15, 1, 2, 16, 17, 18, 1]

for n in access_pattern:
    result = complex_computation(n)

# Print statistics
stats = complex_computation.cache_stats()
print(f"L1 hits: {stats['l1_hits']}")
print(f"L2 hits: {stats['l2_hits']}")
print(f"Misses: {stats['misses']}")
print(f"L1 hit rate: {stats['l1_hit_rate']:.1%}")
print(f"L2 hit rate: {stats['l2_hit_rate']:.1%}")
print(f"Overall hit rate: {stats['overall_hit_rate']:.1%}")
print(f"L1 cache size: {stats['l1_size']}/{10}")
print(f"L2 cache size: {stats['l2_size']}/{100}")
```

## Performance Analysis and Optimization

### Benchmarking Different Memoization Strategies

```python
import time
import random
from functools import lru_cache

# Different memoization implementations
def benchmark_memoization_strategies():
    """Benchmark different memoization strategies"""
    
    # Test function
    def expensive_function(n):
        time.sleep(0.001)  # 1ms delay
        return n * n + 2 * n + 1
    
    # Manual memoization
    manual_cache = {}
    def manual_memo(n):
        if n not in manual_cache:
            manual_cache[n] = expensive_function(n)
        return manual_cache[n]
    
    # LRU cache
    @lru_cache(maxsize=1000)
    def lru_memo(n):
        return expensive_function(n)
    
    # Timed cache
    @timed_cache(ttl_seconds=60)
    def timed_memo(n):
        return expensive_function(n)
    
    # Multi-level cache
    @multi_level_memoization
    def multi_level_memo(n):
        return expensive_function(n)
    
    # Test data
    test_data = [random.randint(1, 100) for _ in range(1000)]
    
    strategies = [
        ('No caching', expensive_function),
        ('Manual cache', manual_memo),
        ('LRU cache', lru_memo),
        ('Timed cache', timed_memo),
        ('Multi-level cache', multi_level_memo)
    ]
    
    print("Memoization Strategy Benchmark:")
    print("=" * 50)
    print(f"{'Strategy':<20} {'Time (s)':<10} {'Speedup':<10}")
    print("-" * 50)
    
    baseline_time = None
    
    for name, func in strategies:
        start = time.time()
        
        for n in test_data:
            func(n)
        
        end = time.time()
        elapsed = end - start
        
        if baseline_time is None:
            baseline_time = elapsed
            speedup = 1.0
        else:
            speedup = baseline_time / elapsed
        
        print(f"{name:<20} {elapsed:<10.4f} {speedup:<10.1f}x")
        
        # Clear caches for next test
        if hasattr(func, 'cache_clear'):
            func.cache_clear()
        elif name == 'Manual cache':
            manual_cache.clear()

benchmark_memoization_strategies()
```

### Memory Usage Analysis

```python
import sys
import gc

def analyze_memory_usage():
    """Analyze memory usage of different caching strategies"""
    
    def get_memory_usage():
        """Get current memory usage"""
        return sum(sys.getsizeof(obj) for obj in gc.get_objects())
    
    # Test with different cache sizes
    cache_sizes = [100, 1000, 10000]
    
    print("Memory Usage Analysis:")
    print("=" * 40)
    
    for size in cache_sizes:
        print(f"\nTesting cache size: {size}")
        
        # Manual cache
        manual_cache = {}
        initial_memory = get_memory_usage()
        
        # Fill cache
        for i in range(size):
            manual_cache[f"key_{i}"] = f"value_{i}" * 100  # 100-char string
        
        manual_memory = get_memory_usage() - initial_memory
        
        # LRU cache
        @lru_cache(maxsize=size)
        def lru_test(key):
            return key * 100
        
        lru_initial = get_memory_usage()
        
        # Fill LRU cache
        for i in range(size):
            lru_test(f"key_{i}")
        
        lru_memory = get_memory_usage() - lru_initial
        
        print(f"  Manual cache: {manual_memory / 1024:.1f} KB")
        print(f"  LRU cache: {lru_memory / 1024:.1f} KB")
        print(f"  Memory per item (manual): {manual_memory / size:.1f} bytes")
        print(f"  Memory per item (LRU): {lru_memory / size:.1f} bytes")
        
        # Cleanup
        manual_cache.clear()
        lru_test.cache_clear()

analyze_memory_usage()
```

## Best Practices and Guidelines

### When to Use Memoization

```python
def memoization_guidelines():
    """Guidelines for when to use memoization"""
    
    guidelines = {
        'Good candidates': [
            'Pure functions (no side effects)',
            'Expensive computations',
            'Recursive functions with overlapping subproblems',
            'Functions called repeatedly with same arguments',
            'Database queries with stable results',
            'API calls with infrequent changes'
        ],
        
        'Poor candidates': [
            'Functions with side effects',
            'Random number generators',
            'Time-dependent functions',
            'Functions that modify global state',
            'I/O operations that should always execute',
            'Functions with very large input/output'
        ],
        
        'Considerations': [
            'Memory usage vs computation time trade-off',
            'Cache invalidation strategy',
            'Thread safety requirements',
            'Garbage collection impact',
            'Cache size limits',
            'Monitoring and debugging needs'
        ]
    }
    
    print("Memoization Guidelines:")
    print("=" * 30)
    
    for category, items in guidelines.items():
        print(f"\n{category}:")
        for item in items:
            print(f"  • {item}")

memoization_guidelines()
```

### Production Considerations

```python
class ProductionMemoization:
    """Production-ready memoization decorator"""
    
    def __init__(self, maxsize=1000, ttl=None, typed=False, 
                 stats=True, thread_safe=True):
        self.maxsize = maxsize
        self.ttl = ttl
        self.typed = typed
        self.stats = stats
        self.thread_safe = thread_safe
        
        if thread_safe:
            import threading
            self.lock = threading.RLock()
        else:
            self.lock = None
    
    def __call__(self, func):
        cache = {}
        stats = {'hits': 0, 'misses': 0, 'evictions': 0}
        access_order = []
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key
            key = self._make_key(args, kwargs)
            current_time = time.time()
            
            # Thread safety
            if self.lock:
                with self.lock:
                    return self._get_or_compute(func, cache, stats, access_order, 
                                              key, current_time, args, kwargs)
            else:
                return self._get_or_compute(func, cache, stats, access_order, 
                                          key, current_time, args, kwargs)
        
        wrapper.cache_info = lambda: {
            'size': len(cache),
            'maxsize': self.maxsize,
            'hits': stats['hits'],
            'misses': stats['misses'],
            'evictions': stats['evictions'],
            'hit_rate': stats['hits'] / (stats['hits'] + stats['misses']) if stats['hits'] + stats['misses'] > 0 else 0
        }
        
        wrapper.cache_clear = lambda: self._clear_cache(cache, stats, access_order)
        
        return wrapper
    
    def _make_key(self, args, kwargs):
        """Create cache key"""
        key = str(args)
        if kwargs:
            key += str(sorted(kwargs.items()))
        return key
    
    def _get_or_compute(self, func, cache, stats, access_order, key, current_time, args, kwargs):
        """Get from cache or compute"""
        # Check cache
        if key in cache:
            result, timestamp = cache[key]
            
            # Check TTL
            if self.ttl is None or current_time - timestamp < self.ttl:
                stats['hits'] += 1
                
                # Update access order
                access_order.remove(key)
                access_order.append(key)
                
                return result
            else:
                # Expired
                del cache[key]
                access_order.remove(key)
        
        # Cache miss
        stats['misses'] += 1
        
        # Evict if necessary
        if len(cache) >= self.maxsize:
            lru_key = access_order.pop(0)
            del cache[lru_key]
            stats['evictions'] += 1
        
        # Compute result
        result = func(*args, **kwargs)
        
        # Store in cache
        cache[key] = (result, current_time)
        access_order.append(key)
        
        return result
    
    def _clear_cache(self, cache, stats, access_order):
        """Clear cache"""
        cache.clear()
        access_order.clear()
        stats.update({'hits': 0, 'misses': 0, 'evictions': 0})

# Example usage
@ProductionMemoization(maxsize=500, ttl=300, stats=True)
def production_fibonacci(n):
    """Production-ready memoized Fibonacci"""
    if n <= 1:
        return n
    return production_fibonacci(n-1) + production_fibonacci(n-2)

# Test production memoization
print("Testing production memoization:")
result = production_fibonacci(30)
print(f"fibonacci(30) = {result}")
print(f"Cache info: {production_fibonacci.cache_info()}")
```

## Key Takeaways

### The Memoization Mindset

1. **Identify Expensive Operations**: Look for functions that are called repeatedly with the same arguments
2. **Understand Trade-offs**: Memory usage vs computation time
3. **Choose the Right Strategy**: Manual, LRU, TTL, or multi-level based on your needs
4. **Monitor Performance**: Track hit rates and memory usage
5. **Handle Edge Cases**: Consider cache invalidation and thread safety

### Common Pitfalls

1. **Caching Impure Functions**: Don't cache functions with side effects
2. **Memory Leaks**: Unbounded caches can consume all available memory
3. **Stale Data**: Cached results may become outdated
4. **Thread Safety**: Concurrent access can corrupt cache state
5. **Over-caching**: Not all functions benefit from caching

Simple memoization is often the most effective optimization you can apply to your code. It transforms exponential algorithms into linear ones, reduces database load, and improves user experience—all with minimal code changes.

The next step is understanding cache invalidation, one of the two hard problems in computer science, and exploring advanced caching strategies for production systems.