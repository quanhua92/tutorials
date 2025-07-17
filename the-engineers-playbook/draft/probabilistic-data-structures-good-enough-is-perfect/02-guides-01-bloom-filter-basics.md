# Bloom Filter Basics: Your First Probabilistic Data Structure

## The Problem: Username Availability at Scale

You're building a social platform where users pick usernames. You need to quickly check if a username is already taken. With 100 million existing users, storing all usernames for lookups would require significant memory and database queries.

Enter the Bloom filter: a space-efficient way to answer "Have we seen this username before?" with zero false negatives and a tiny, controllable false positive rate.

## How Bloom Filters Work

### The Structure

A Bloom filter consists of:
1. **A bit array** of size `m` (initially all zeros)
2. **k hash functions** (each maps input to array positions)

```
Bit Array (size m=12):  [0,0,0,0,0,0,0,0,0,0,0,0]
Hash Functions (k=3):   hash1(), hash2(), hash3()
```

### Adding an Item

To add "alice":
1. Compute `hash1("alice") = 2`, `hash2("alice") = 7`, `hash3("alice") = 10`
2. Set bits at positions 2, 7, and 10

```
Before: [0,0,0,0,0,0,0,0,0,0,0,0]
After:  [0,0,1,0,0,0,0,1,0,0,1,0]
```

### Checking for an Item

To check if "alice" exists:
1. Compute the same hash values: positions 2, 7, 10
2. Check if ALL bits at those positions are 1
3. If any bit is 0 → definitely not present
4. If all bits are 1 → probably present

## Step-by-Step Implementation Guide

### Step 1: Choose Your Parameters

```
n = expected number of items (e.g., 1 million usernames)
p = desired false positive rate (e.g., 1% = 0.01)

Calculate optimal parameters:
m = -(n * ln(p)) / (ln(2)^2)  // bit array size
k = (m / n) * ln(2)           // number of hash functions
```

For 1 million items with 1% false positive rate:
- `m ≈ 9,585,059 bits` (about 1.2 MB)
- `k ≈ 7 hash functions`

### Step 2: Implement Hash Functions

Simple approach using a single good hash function:

```python
import hashlib

def get_hashes(item, k, m):
    """Generate k hash values for item, each in range [0, m-1]"""
    # Use two hash values to generate k hashes (double hashing)
    h1 = int(hashlib.md5(item.encode()).hexdigest(), 16) % m
    h2 = int(hashlib.sha1(item.encode()).hexdigest(), 16) % m
    
    hashes = []
    for i in range(k):
        hash_val = (h1 + i * h2) % m
        hashes.append(hash_val)
    return hashes
```

### Step 3: Build the Bloom Filter

```python
class BloomFilter:
    def __init__(self, m, k):
        self.m = m          # bit array size
        self.k = k          # number of hash functions
        self.bits = [0] * m # bit array
        
    def add(self, item):
        """Add item to the filter"""
        for hash_val in get_hashes(item, self.k, self.m):
            self.bits[hash_val] = 1
            
    def contains(self, item):
        """Check if item might be in the filter"""
        for hash_val in get_hashes(item, self.k, self.m):
            if self.bits[hash_val] == 0:
                return False  # Definitely not present
        return True  # Probably present
```

## Practical Example: Username Checker

```python
# Create filter for 1M usernames with 1% false positive rate
username_filter = BloomFilter(m=9585059, k=7)

# Add existing usernames (simulate from database)
existing_users = ["alice", "bob", "charlie", "diana", "eve"]
for username in existing_users:
    username_filter.add(username)

# Check username availability
def is_username_available(username):
    if username_filter.contains(username):
        # Might be taken - check database for certainty
        return check_database(username)  # Expensive operation
    else:
        # Definitely available - no database check needed!
        return True

# Test the system
print(is_username_available("frank"))    # True (no DB check!)
print(is_username_available("alice"))    # False (after DB check)
print(is_username_available("mallory"))  # Might trigger false positive
```

## Performance Benefits

**Without Bloom Filter:**
- Every username check → database query
- 1M checks/day = 1M database queries
- High latency, database load

**With Bloom Filter:**
- 99% of checks for new usernames → instant response
- Only 1% + false positives → database queries
- Massive reduction in database load

## Real-World Optimizations

### Memory-Efficient Bit Storage

Instead of storing each bit as a full integer:

```python
import array

class EfficientBloomFilter:
    def __init__(self, m, k):
        self.m = m
        self.k = k
        # Use bit array - 8 bits per byte
        self.byte_array = array.array('B', [0] * ((m + 7) // 8))
        
    def _set_bit(self, index):
        byte_index = index // 8
        bit_index = index % 8
        self.byte_array[byte_index] |= (1 << bit_index)
        
    def _get_bit(self, index):
        byte_index = index // 8
        bit_index = index % 8
        return bool(self.byte_array[byte_index] & (1 << bit_index))
```

### Handling Hash Collisions

Use double hashing to avoid correlation between hash functions:

```python
def better_hashes(item, k, m):
    """More robust hash generation"""
    h1 = hash(item) % m
    h2 = hash(item[::-1]) % m  # Hash reversed string
    if h2 == 0:
        h2 = 1  # Ensure h2 is never 0
        
    return [(h1 + i * h2) % m for i in range(k)]
```

## Common Pitfalls and Solutions

### Pitfall 1: Wrong Parameter Calculation
**Problem**: Using intuition instead of formulas  
**Solution**: Always calculate m and k using the mathematical formulas

### Pitfall 2: Poor Hash Functions
**Problem**: Using low-quality hash functions that create patterns  
**Solution**: Use cryptographic hash functions or well-tested algorithms

### Pitfall 3: Ignoring False Positives
**Problem**: Treating "probably present" as "definitely present"  
**Solution**: Always have a fallback for false positive cases

## When to Use Bloom Filters

**Excellent for:**
- Caching layers (avoid expensive lookups)
- Duplicate detection in streams
- Database query reduction
- Malware detection (suspicious URLs/files)

**Not suitable for:**
- When you need exact counts
- When false positives are unacceptable
- Very small datasets (overhead not worth it)
- When you need to delete items (standard Bloom filters don't support deletion)

The next section dives deep into tuning these parameters for your specific needs.