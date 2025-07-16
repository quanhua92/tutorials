# Cache Invalidation: One of the Two Hard Things in Computer Science

## The Famous Quote

> "There are only two hard things in Computer Science: cache invalidation and naming things."
> — Phil Karlton

Cache invalidation is the process of removing or updating stale data from a cache. It's hard because you need to balance **consistency** (data accuracy) with **performance** (speed). Every consistency guarantee you add reduces performance.

## The Core Problem

### The Staleness Dilemma

When you cache data, you create a copy. The original data might change, making your cached copy stale:

```python
import time
import threading

class StaleDataDemo:
    """Demonstrate the staleness problem"""
    
    def __init__(self):
        self.database = {"user_123": {"name": "John", "email": "john@example.com"}}
        self.cache = {}
        self.cache_timestamp = {}
    
    def get_user_from_database(self, user_id):
        """Simulate expensive database query"""
        print(f"[DB] Querying database for user {user_id}")
        time.sleep(0.5)  # Simulate slow database
        return self.database.get(user_id)
    
    def get_user_cached(self, user_id):
        """Get user with simple caching"""
        if user_id in self.cache:
            print(f"[CACHE] Cache hit for user {user_id}")
            return self.cache[user_id]
        
        # Cache miss - get from database
        print(f"[CACHE] Cache miss for user {user_id}")
        user = self.get_user_from_database(user_id)
        
        if user:
            self.cache[user_id] = user
            self.cache_timestamp[user_id] = time.time()
        
        return user
    
    def update_user_in_database(self, user_id, new_data):
        """Update user in database (cache becomes stale)"""
        print(f"[DB] Updating user {user_id} in database")
        self.database[user_id] = new_data
        # Cache is now stale!
    
    def demonstrate_staleness(self):
        """Show how cached data becomes stale"""
        print("=== Cache Staleness Demonstration ===")
        
        # First read - cache miss
        user1 = self.get_user_cached("user_123")
        print(f"First read: {user1}")
        
        # Second read - cache hit
        user2 = self.get_user_cached("user_123")
        print(f"Second read: {user2}")
        
        # Update database
        self.update_user_in_database("user_123", {
            "name": "John Smith", 
            "email": "john.smith@example.com"
        })
        
        # Third read - cache hit with stale data!
        user3 = self.get_user_cached("user_123")
        print(f"Third read (stale): {user3}")
        
        # What's actually in the database
        fresh_user = self.get_user_from_database("user_123")
        print(f"Database has: {fresh_user}")

demo = StaleDataDemo()
demo.demonstrate_staleness()
```

**Output:**
```
=== Cache Staleness Demonstration ===
[CACHE] Cache miss for user user_123
[DB] Querying database for user user_123
First read: {'name': 'John', 'email': 'john@example.com'}
[CACHE] Cache hit for user user_123
Second read: {'name': 'John', 'email': 'john@example.com'}
[DB] Updating user user_123 in database
[CACHE] Cache hit for user user_123
Third read (stale): {'name': 'John', 'email': 'john@example.com'}
[DB] Querying database for user user_123
Database has: {'name': 'John Smith', 'email': 'john.smith@example.com'}
```

## Invalidation Strategies

### 1. Time-to-Live (TTL) Invalidation

Automatically expire cache entries after a fixed time:

```python
import time

class TTLCache:
    """Cache with Time-To-Live invalidation"""
    
    def __init__(self, default_ttl=300):  # 5 minutes default
        self.cache = {}
        self.timestamps = {}
        self.ttl_values = {}
        self.default_ttl = default_ttl
        self.stats = {'hits': 0, 'misses': 0, 'expired': 0}
    
    def get(self, key):
        """Get item, checking if it's expired"""
        current_time = time.time()
        
        if key in self.cache:
            # Check if expired
            ttl = self.ttl_values.get(key, self.default_ttl)
            age = current_time - self.timestamps[key]
            
            if age < ttl:
                # Still fresh
                self.stats['hits'] += 1
                return self.cache[key]
            else:
                # Expired - remove from cache
                self.stats['expired'] += 1
                self.remove(key)
        
        self.stats['misses'] += 1
        return None
    
    def put(self, key, value, ttl=None):
        """Store item with optional custom TTL"""
        self.cache[key] = value
        self.timestamps[key] = time.time()
        self.ttl_values[key] = ttl or self.default_ttl
    
    def remove(self, key):
        """Remove item from cache"""
        if key in self.cache:
            del self.cache[key]
            del self.timestamps[key]
            del self.ttl_values[key]
    
    def cleanup_expired(self):
        """Remove all expired items"""
        current_time = time.time()
        expired_keys = []
        
        for key, timestamp in self.timestamps.items():
            ttl = self.ttl_values[key]
            if current_time - timestamp >= ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            self.remove(key)
        
        return len(expired_keys)
    
    def get_stats(self):
        """Get cache statistics"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = self.stats['hits'] / total_requests if total_requests > 0 else 0
        
        return {
            'size': len(self.cache),
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'expired': self.stats['expired'],
            'hit_rate': hit_rate
        }

# Demonstrate TTL cache
def demonstrate_ttl_cache():
    """Show TTL cache in action"""
    cache = TTLCache(default_ttl=2)  # 2 second TTL
    
    print("=== TTL Cache Demonstration ===")
    
    # Store some data
    cache.put("user_123", {"name": "John", "email": "john@example.com"})
    cache.put("user_456", {"name": "Jane", "email": "jane@example.com"})
    
    # Immediate retrieval - should hit
    user = cache.get("user_123")
    print(f"Immediate retrieval: {user}")
    
    # Wait 1 second - should still hit
    time.sleep(1)
    user = cache.get("user_123")
    print(f"After 1 second: {user}")
    
    # Wait 2 more seconds - should expire
    time.sleep(2)
    user = cache.get("user_123")
    print(f"After 3 seconds total: {user}")
    
    # Show statistics
    stats = cache.get_stats()
    print(f"Stats: {stats}")

demonstrate_ttl_cache()
```

### 2. Write-Through Invalidation

Update cache immediately when data changes:

```python
class WriteThroughCache:
    """Cache that updates immediately when data changes"""
    
    def __init__(self, database):
        self.database = database
        self.cache = {}
        self.stats = {'hits': 0, 'misses': 0, 'writes': 0}
    
    def get(self, key):
        """Get item from cache or database"""
        if key in self.cache:
            self.stats['hits'] += 1
            return self.cache[key]
        
        # Cache miss - get from database
        self.stats['misses'] += 1
        value = self.database.get(key)
        
        if value is not None:
            self.cache[key] = value
        
        return value
    
    def put(self, key, value):
        """Write to both cache and database"""
        self.stats['writes'] += 1
        
        # Write to database first
        self.database.put(key, value)
        
        # Update cache
        self.cache[key] = value
    
    def delete(self, key):
        """Delete from both cache and database"""
        self.database.delete(key)
        
        if key in self.cache:
            del self.cache[key]
    
    def invalidate(self, key):
        """Remove from cache (but keep in database)"""
        if key in self.cache:
            del self.cache[key]

# Simulate database
class SimulatedDatabase:
    def __init__(self):
        self.data = {}
    
    def get(self, key):
        print(f"[DB] Reading {key}")
        time.sleep(0.1)  # Simulate slow database
        return self.data.get(key)
    
    def put(self, key, value):
        print(f"[DB] Writing {key}")
        time.sleep(0.1)  # Simulate slow database
        self.data[key] = value
    
    def delete(self, key):
        print(f"[DB] Deleting {key}")
        time.sleep(0.1)  # Simulate slow database
        if key in self.data:
            del self.data[key]

# Demonstrate write-through cache
def demonstrate_write_through():
    """Show write-through cache consistency"""
    db = SimulatedDatabase()
    cache = WriteThroughCache(db)
    
    print("=== Write-Through Cache Demonstration ===")
    
    # Write data
    cache.put("user_123", {"name": "John", "email": "john@example.com"})
    
    # Read from cache
    user = cache.get("user_123")
    print(f"Read from cache: {user}")
    
    # Update data
    cache.put("user_123", {"name": "John Smith", "email": "john.smith@example.com"})
    
    # Read updated data from cache
    user = cache.get("user_123")
    print(f"Read updated data: {user}")
    
    # Cache is always consistent with database
    print(f"Cache stats: {cache.stats}")

demonstrate_write_through()
```

### 3. Write-Back (Write-Behind) Invalidation

Batch updates to reduce database load:

```python
import threading
import queue
import time

class WriteBackCache:
    """Cache that batches writes for better performance"""
    
    def __init__(self, database, batch_size=10, flush_interval=5):
        self.database = database
        self.cache = {}
        self.dirty_keys = set()  # Keys that need to be written
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.write_queue = queue.Queue()
        self.stats = {'hits': 0, 'misses': 0, 'writes': 0, 'flushes': 0}
        
        # Start background flush thread
        self.flush_thread = threading.Thread(target=self._flush_worker, daemon=True)
        self.flush_thread.start()
    
    def get(self, key):
        """Get item from cache or database"""
        if key in self.cache:
            self.stats['hits'] += 1
            return self.cache[key]
        
        # Cache miss - get from database
        self.stats['misses'] += 1
        value = self.database.get(key)
        
        if value is not None:
            self.cache[key] = value
        
        return value
    
    def put(self, key, value):
        """Write to cache, queue for database write"""
        self.stats['writes'] += 1
        
        # Update cache immediately
        self.cache[key] = value
        
        # Mark as dirty for batch write
        self.dirty_keys.add(key)
        self.write_queue.put(key)
        
        # Flush if batch is full
        if len(self.dirty_keys) >= self.batch_size:
            self._flush_dirty_keys()
    
    def _flush_dirty_keys(self):
        """Flush dirty keys to database"""
        if not self.dirty_keys:
            return
        
        self.stats['flushes'] += 1
        print(f"[CACHE] Flushing {len(self.dirty_keys)} dirty keys to database")
        
        # Batch write to database
        for key in list(self.dirty_keys):
            if key in self.cache:
                self.database.put(key, self.cache[key])
        
        self.dirty_keys.clear()
    
    def _flush_worker(self):
        """Background thread to flush dirty keys periodically"""
        while True:
            time.sleep(self.flush_interval)
            if self.dirty_keys:
                self._flush_dirty_keys()
    
    def force_flush(self):
        """Force immediate flush of all dirty keys"""
        self._flush_dirty_keys()
    
    def get_dirty_count(self):
        """Get number of dirty keys"""
        return len(self.dirty_keys)

# Demonstrate write-back cache
def demonstrate_write_back():
    """Show write-back cache batching"""
    db = SimulatedDatabase()
    cache = WriteBackCache(db, batch_size=3, flush_interval=10)
    
    print("=== Write-Back Cache Demonstration ===")
    
    # Write several items quickly
    cache.put("user_1", {"name": "Alice"})
    cache.put("user_2", {"name": "Bob"})
    print(f"Dirty keys: {cache.get_dirty_count()}")
    
    # Third write triggers batch flush
    cache.put("user_3", {"name": "Charlie"})
    print(f"Dirty keys after batch: {cache.get_dirty_count()}")
    
    # Write more items
    cache.put("user_4", {"name": "Dave"})
    cache.put("user_5", {"name": "Eve"})
    print(f"Dirty keys: {cache.get_dirty_count()}")
    
    # Force flush remaining
    cache.force_flush()
    print(f"Dirty keys after force flush: {cache.get_dirty_count()}")
    
    print(f"Cache stats: {cache.stats}")

demonstrate_write_back()
```

### 4. Event-Driven Invalidation

Invalidate cache when specific events occur:

```python
import threading
from typing import Callable, List

class EventDrivenCache:
    """Cache that invalidates based on events"""
    
    def __init__(self):
        self.cache = {}
        self.event_handlers = {}  # event_type -> list of handlers
        self.key_dependencies = {}  # key -> set of events it depends on
        self.stats = {'hits': 0, 'misses': 0, 'invalidations': 0}
        self.lock = threading.RLock()
    
    def get(self, key):
        """Get item from cache"""
        with self.lock:
            if key in self.cache:
                self.stats['hits'] += 1
                return self.cache[key]
            
            self.stats['misses'] += 1
            return None
    
    def put(self, key, value, depends_on_events=None):
        """Store item with optional event dependencies"""
        with self.lock:
            self.cache[key] = value
            
            if depends_on_events:
                self.key_dependencies[key] = set(depends_on_events)
                
                # Register invalidation handlers
                for event_type in depends_on_events:
                    if event_type not in self.event_handlers:
                        self.event_handlers[event_type] = []
                    
                    # Add invalidation handler for this key
                    handler = lambda k=key: self._invalidate_key(k)
                    self.event_handlers[event_type].append(handler)
    
    def _invalidate_key(self, key):
        """Invalidate a specific key"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.stats['invalidations'] += 1
                print(f"[CACHE] Invalidated key: {key}")
    
    def emit_event(self, event_type, event_data=None):
        """Emit an event that may trigger invalidations"""
        print(f"[EVENT] Emitting event: {event_type}")
        
        with self.lock:
            if event_type in self.event_handlers:
                for handler in self.event_handlers[event_type]:
                    handler()
    
    def subscribe_to_event(self, event_type, handler: Callable):
        """Subscribe to an event"""
        with self.lock:
            if event_type not in self.event_handlers:
                self.event_handlers[event_type] = []
            self.event_handlers[event_type].append(handler)
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = self.stats['hits'] / total_requests if total_requests > 0 else 0
            
            return {
                'size': len(self.cache),
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'invalidations': self.stats['invalidations'],
                'hit_rate': hit_rate
            }

# Demonstrate event-driven cache
def demonstrate_event_driven():
    """Show event-driven cache invalidation"""
    cache = EventDrivenCache()
    
    print("=== Event-Driven Cache Demonstration ===")
    
    # Cache user data that depends on user updates
    cache.put("user_profile_123", 
              {"name": "John", "email": "john@example.com"},
              depends_on_events=["user_updated", "user_deleted"])
    
    # Cache user posts that depend on user and post updates
    cache.put("user_posts_123",
              ["Post 1", "Post 2", "Post 3"],
              depends_on_events=["user_updated", "post_created", "post_deleted"])
    
    # Read cached data
    profile = cache.get("user_profile_123")
    posts = cache.get("user_posts_123")
    print(f"Profile: {profile}")
    print(f"Posts: {posts}")
    
    # Emit user update event - should invalidate profile and posts
    cache.emit_event("user_updated", {"user_id": "123"})
    
    # Try to read again - should be cache misses
    profile = cache.get("user_profile_123")
    posts = cache.get("user_posts_123")
    print(f"Profile after update: {profile}")
    print(f"Posts after update: {posts}")
    
    print(f"Cache stats: {cache.get_stats()}")

demonstrate_event_driven()
```

### 5. Distributed Cache Invalidation

Coordinate invalidation across multiple cache instances:

```python
import json
import threading
import uuid
from typing import Dict, Set

class DistributedCache:
    """Cache that coordinates invalidation across instances"""
    
    def __init__(self, node_id=None):
        self.node_id = node_id or str(uuid.uuid4())
        self.cache = {}
        self.other_nodes = {}  # node_id -> node reference
        self.stats = {'hits': 0, 'misses': 0, 'invalidations': 0, 'broadcasts': 0}
        self.lock = threading.RLock()
    
    def add_node(self, node):
        """Add another cache node for coordination"""
        with self.lock:
            self.other_nodes[node.node_id] = node
            node.other_nodes[self.node_id] = self
    
    def get(self, key):
        """Get item from local cache"""
        with self.lock:
            if key in self.cache:
                self.stats['hits'] += 1
                return self.cache[key]
            
            self.stats['misses'] += 1
            return None
    
    def put(self, key, value):
        """Store item in local cache"""
        with self.lock:
            self.cache[key] = value
    
    def invalidate_local(self, key):
        """Invalidate key in local cache only"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                self.stats['invalidations'] += 1
                print(f"[NODE {self.node_id[:8]}] Invalidated key: {key}")
    
    def invalidate_distributed(self, key):
        """Invalidate key across all nodes"""
        with self.lock:
            self.stats['broadcasts'] += 1
            
            # Invalidate locally
            self.invalidate_local(key)
            
            # Broadcast to other nodes
            for node_id, node in self.other_nodes.items():
                print(f"[NODE {self.node_id[:8]}] Broadcasting invalidation of {key} to {node_id[:8]}")
                node.receive_invalidation(key, from_node=self.node_id)
    
    def receive_invalidation(self, key, from_node):
        """Receive invalidation from another node"""
        print(f"[NODE {self.node_id[:8]}] Received invalidation of {key} from {from_node[:8]}")
        self.invalidate_local(key)
    
    def get_stats(self):
        """Get cache statistics"""
        with self.lock:
            total_requests = self.stats['hits'] + self.stats['misses']
            hit_rate = self.stats['hits'] / total_requests if total_requests > 0 else 0
            
            return {
                'node_id': self.node_id[:8],
                'size': len(self.cache),
                'hits': self.stats['hits'],
                'misses': self.stats['misses'],
                'invalidations': self.stats['invalidations'],
                'broadcasts': self.stats['broadcasts'],
                'hit_rate': hit_rate
            }

# Demonstrate distributed cache
def demonstrate_distributed_cache():
    """Show distributed cache invalidation"""
    # Create multiple cache nodes
    node1 = DistributedCache()
    node2 = DistributedCache()
    node3 = DistributedCache()
    
    # Connect nodes
    node1.add_node(node2)
    node1.add_node(node3)
    node2.add_node(node3)
    
    print("=== Distributed Cache Demonstration ===")
    
    # Store same data in all nodes
    for node in [node1, node2, node3]:
        node.put("user_123", {"name": "John", "email": "john@example.com"})
    
    # Verify all nodes have the data
    for i, node in enumerate([node1, node2, node3], 1):
        user = node.get("user_123")
        print(f"Node {i}: {user}")
    
    # Invalidate from node1 - should propagate to all nodes
    print("\nInvalidating from node 1...")
    node1.invalidate_distributed("user_123")
    
    # Verify all nodes have invalidated the data
    print("\nAfter invalidation:")
    for i, node in enumerate([node1, node2, node3], 1):
        user = node.get("user_123")
        print(f"Node {i}: {user}")
    
    # Show statistics
    print("\nNode statistics:")
    for i, node in enumerate([node1, node2, node3], 1):
        stats = node.get_stats()
        print(f"Node {i}: {stats}")

demonstrate_distributed_cache()
```

## Advanced Invalidation Patterns

### 1. Dependency-Based Invalidation

Invalidate caches based on data dependencies:

```python
from typing import Set, Dict, List

class DependencyCache:
    """Cache with dependency tracking"""
    
    def __init__(self):
        self.cache = {}
        self.dependencies = {}  # key -> set of dependencies
        self.dependents = {}    # dependency -> set of keys that depend on it
        self.stats = {'hits': 0, 'misses': 0, 'invalidations': 0}
    
    def get(self, key):
        """Get item from cache"""
        if key in self.cache:
            self.stats['hits'] += 1
            return self.cache[key]
        
        self.stats['misses'] += 1
        return None
    
    def put(self, key, value, depends_on=None):
        """Store item with dependencies"""
        self.cache[key] = value
        
        if depends_on:
            self.dependencies[key] = set(depends_on)
            
            # Update reverse dependencies
            for dep in depends_on:
                if dep not in self.dependents:
                    self.dependents[dep] = set()
                self.dependents[dep].add(key)
    
    def invalidate(self, dependency):
        """Invalidate all items that depend on this dependency"""
        if dependency in self.dependents:
            # Get all keys that depend on this dependency
            dependent_keys = self.dependents[dependency].copy()
            
            print(f"[CACHE] Invalidating {len(dependent_keys)} items due to dependency: {dependency}")
            
            for key in dependent_keys:
                self._invalidate_key(key)
    
    def _invalidate_key(self, key):
        """Invalidate a specific key and clean up dependencies"""
        if key in self.cache:
            del self.cache[key]
            self.stats['invalidations'] += 1
            
            # Clean up dependencies
            if key in self.dependencies:
                for dep in self.dependencies[key]:
                    if dep in self.dependents:
                        self.dependents[dep].discard(key)
                del self.dependencies[key]
    
    def get_dependency_graph(self):
        """Get visualization of dependency graph"""
        graph = {}
        for key, deps in self.dependencies.items():
            graph[key] = list(deps)
        return graph

# Demonstrate dependency-based invalidation
def demonstrate_dependency_cache():
    """Show dependency-based cache invalidation"""
    cache = DependencyCache()
    
    print("=== Dependency-Based Cache Demonstration ===")
    
    # Cache user profile (depends on user data)
    cache.put("user_profile_123", 
              {"name": "John", "email": "john@example.com"},
              depends_on=["user_123"])
    
    # Cache user posts (depends on user data and post data)
    cache.put("user_posts_123",
              ["Post 1", "Post 2"],
              depends_on=["user_123", "posts_by_user_123"])
    
    # Cache user statistics (depends on user data and posts)
    cache.put("user_stats_123",
              {"post_count": 2, "total_likes": 150},
              depends_on=["user_123", "posts_by_user_123"])
    
    # Cache feed (depends on multiple users)
    cache.put("feed_for_456",
              ["Post from John", "Post from Jane"],
              depends_on=["user_123", "user_456"])
    
    # Show dependency graph
    print("Dependency graph:")
    for key, deps in cache.get_dependency_graph().items():
        print(f"  {key} depends on: {deps}")
    
    # Invalidate user_123 - should cascade to profile, posts, and stats
    print("\nInvalidating user_123...")
    cache.invalidate("user_123")
    
    # Check what's left in cache
    print("\nRemaining cache items:")
    for key in ["user_profile_123", "user_posts_123", "user_stats_123", "feed_for_456"]:
        value = cache.get(key)
        status = "CACHED" if value else "INVALIDATED"
        print(f"  {key}: {status}")
    
    print(f"\nCache stats: {cache.stats}")

demonstrate_dependency_cache()
```

### 2. Probabilistic Invalidation

Use probabilistic methods to reduce invalidation overhead:

```python
import random
import time
import math

class ProbabilisticCache:
    """Cache with probabilistic invalidation"""
    
    def __init__(self, base_ttl=300, beta=1.0):
        self.cache = {}
        self.timestamps = {}
        self.base_ttl = base_ttl
        self.beta = beta  # Controls randomness
        self.stats = {'hits': 0, 'misses': 0, 'early_expires': 0}
    
    def get(self, key):
        """Get item with probabilistic expiration"""
        current_time = time.time()
        
        if key in self.cache:
            age = current_time - self.timestamps[key]
            
            # Calculate probability of early expiration
            if age < self.base_ttl:
                # Use exponential decay to calculate expiration probability
                prob_expire = self._calculate_expiration_probability(age)
                
                if random.random() < prob_expire:
                    # Probabilistic early expiration
                    self.stats['early_expires'] += 1
                    self._remove_key(key)
                    self.stats['misses'] += 1
                    return None
                else:
                    # Cache hit
                    self.stats['hits'] += 1
                    return self.cache[key]
            else:
                # Definitely expired
                self._remove_key(key)
                self.stats['misses'] += 1
                return None
        
        self.stats['misses'] += 1
        return None
    
    def put(self, key, value):
        """Store item with timestamp"""
        self.cache[key] = value
        self.timestamps[key] = time.time()
    
    def _calculate_expiration_probability(self, age):
        """Calculate probability of expiration based on age"""
        # Exponential decay function
        # As age approaches TTL, probability approaches 1
        normalized_age = age / self.base_ttl
        return 1 - math.exp(-self.beta * normalized_age)
    
    def _remove_key(self, key):
        """Remove key from cache"""
        if key in self.cache:
            del self.cache[key]
            del self.timestamps[key]
    
    def get_stats(self):
        """Get cache statistics"""
        total_requests = self.stats['hits'] + self.stats['misses']
        hit_rate = self.stats['hits'] / total_requests if total_requests > 0 else 0
        
        return {
            'size': len(self.cache),
            'hits': self.stats['hits'],
            'misses': self.stats['misses'],
            'early_expires': self.stats['early_expires'],
            'hit_rate': hit_rate
        }

# Demonstrate probabilistic cache
def demonstrate_probabilistic_cache():
    """Show probabilistic cache behavior"""
    cache = ProbabilisticCache(base_ttl=10, beta=2.0)
    
    print("=== Probabilistic Cache Demonstration ===")
    
    # Store item
    cache.put("test_key", "test_value")
    
    # Test retrieval over time
    for i in range(20):
        time.sleep(0.5)  # Wait 0.5 seconds
        value = cache.get("test_key")
        age = i * 0.5
        
        status = "HIT" if value else "MISS"
        print(f"Age: {age:.1f}s - {status}")
        
        if not value:
            break
    
    print(f"\nCache stats: {cache.get_stats()}")

demonstrate_probabilistic_cache()
```

## Cache Invalidation Patterns Summary

### When to Use Each Strategy

1. **TTL (Time-to-Live)**
   - **Use when**: Data freshness requirements are time-based
   - **Pros**: Simple, predictable, automatic cleanup
   - **Cons**: May serve stale data, may expire fresh data

2. **Write-Through**
   - **Use when**: Strong consistency is required
   - **Pros**: Always consistent, simple to understand
   - **Cons**: Higher latency for writes, database load

3. **Write-Back**
   - **Use when**: Write performance is critical
   - **Pros**: Better write performance, reduced database load
   - **Cons**: Risk of data loss, eventual consistency

4. **Event-Driven**
   - **Use when**: You have good event system and know when data changes
   - **Pros**: Precise invalidation, good performance
   - **Cons**: Complex to implement, requires event infrastructure

5. **Distributed**
   - **Use when**: Multiple cache instances need coordination
   - **Pros**: Consistent across instances
   - **Cons**: Network overhead, complex coordination

### Best Practices

1. **Start Simple**: Begin with TTL, add complexity only when needed
2. **Monitor Everything**: Track hit rates, invalidation rates, and staleness
3. **Layer Strategies**: Use multiple strategies for different data types
4. **Test Failure Cases**: Ensure system works when invalidation fails
5. **Plan for Scale**: Consider network overhead and coordination complexity

The key insight is that cache invalidation is about balancing **consistency, performance, and complexity**. Every guarantee you add reduces performance, so choose the minimum consistency level that meets your requirements.

The next step is building a production-ready caching system that combines these invalidation strategies with the performance optimizations we've learned.