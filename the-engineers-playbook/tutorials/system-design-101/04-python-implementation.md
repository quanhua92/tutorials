# Python Implementation: Building System Design Patterns

## Overview

This section provides concrete, working Python implementations of the key system design patterns discussed in this tutorial. Each implementation demonstrates core concepts with practical, runnable code that you can use to understand and experiment with distributed system patterns.

## Implementation 1: Consistent Hashing for Load Distribution

Consistent hashing is fundamental for building scalable distributed systems. This implementation shows how to distribute load evenly across servers while minimizing redistribution when servers are added or removed.

```python
import hashlib
import bisect
from typing import List, Dict, Optional, Any

class ConsistentHashRing:
    """
    Implementation of consistent hashing with virtual nodes for even distribution.
    Used by: Amazon DynamoDB, Apache Cassandra, Memcached
    """
    
    def __init__(self, replicas: int = 150):
        """
        Initialize the hash ring.
        
        Args:
            replicas: Number of virtual nodes per physical server
                     Higher values = better distribution, more memory usage
        """
        self.replicas = replicas
        self.ring: Dict[int, str] = {}  # hash_value -> server_name
        self.sorted_keys: List[int] = []  # Sorted hash values for binary search
        
    def _hash(self, key: str) -> int:
        """Generate consistent hash value for a key"""
        return int(hashlib.md5(key.encode('utf-8')).hexdigest(), 16)
    
    def add_server(self, server: str) -> None:
        """Add a server to the ring with virtual nodes"""
        for i in range(self.replicas):
            # Create virtual node key: "server1:0", "server1:1", etc.
            virtual_key = f"{server}:{i}"
            hash_value = self._hash(virtual_key)
            
            self.ring[hash_value] = server
            bisect.insort(self.sorted_keys, hash_value)
            
        print(f"Added server '{server}' with {self.replicas} virtual nodes")
    
    def remove_server(self, server: str) -> None:
        """Remove a server and all its virtual nodes"""
        keys_to_remove = []
        
        for hash_value, server_name in self.ring.items():
            if server_name == server:
                keys_to_remove.append(hash_value)
        
        for key in keys_to_remove:
            del self.ring[key]
            self.sorted_keys.remove(key)
            
        print(f"Removed server '{server}' and {len(keys_to_remove)} virtual nodes")
    
    def get_server(self, key: str) -> Optional[str]:
        """Get the server responsible for a given key"""
        if not self.ring:
            return None
            
        hash_value = self._hash(key)
        
        # Find the first server clockwise from this hash value
        idx = bisect.bisect_right(self.sorted_keys, hash_value)
        
        # Wrap around if we're past the end
        if idx == len(self.sorted_keys):
            idx = 0
            
        return self.ring[self.sorted_keys[idx]]
    
    def get_servers(self, key: str, count: int) -> List[str]:
        """Get multiple servers for replication (N replicas)"""
        if not self.ring or count <= 0:
            return []
            
        hash_value = self._hash(key)
        servers = []
        seen_servers = set()
        
        idx = bisect.bisect_right(self.sorted_keys, hash_value)
        
        while len(servers) < count and len(seen_servers) < len(set(self.ring.values())):
            if idx >= len(self.sorted_keys):
                idx = 0
                
            server = self.ring[self.sorted_keys[idx]]
            if server not in seen_servers:
                servers.append(server)
                seen_servers.add(server)
                
            idx += 1
            
        return servers
    
    def distribution_stats(self) -> Dict[str, int]:
        """Analyze key distribution across servers (for testing)"""
        # Generate sample keys and see distribution
        sample_keys = [f"key_{i}" for i in range(10000)]
        distribution = {}
        
        for key in sample_keys:
            server = self.get_server(key)
            distribution[server] = distribution.get(server, 0) + 1
            
        return distribution


# Example usage and testing
def test_consistent_hashing():
    """Demonstrate consistent hashing behavior"""
    print("=== Consistent Hashing Demo ===\n")
    
    # Create hash ring
    ring = ConsistentHashRing(replicas=100)
    
    # Add initial servers
    servers = ["server1", "server2", "server3"]
    for server in servers:
        ring.add_server(server)
    
    print("\n--- Initial Distribution ---")
    initial_distribution = ring.distribution_stats()
    for server, count in initial_distribution.items():
        percentage = (count / 10000) * 100
        print(f"{server}: {count} keys ({percentage:.1f}%)")
    
    # Show key mapping
    test_keys = ["user123", "user456", "user789", "session_abc", "session_def"]
    print(f"\n--- Key Mappings ---")
    for key in test_keys:
        server = ring.get_server(key)
        replicas = ring.get_servers(key, 3)
        print(f"'{key}' -> {server} (replicas: {replicas})")
    
    # Add a new server and show redistribution
    print(f"\n--- Adding New Server ---")
    ring.add_server("server4")
    
    print("Distribution after adding server4:")
    new_distribution = ring.distribution_stats()
    for server, count in new_distribution.items():
        percentage = (count / 10000) * 100
        print(f"{server}: {count} keys ({percentage:.1f}%)")
    
    # Calculate redistribution percentage
    moved_keys = 0
    for key in [f"key_{i}" for i in range(10000)]:
        old_server = None
        for s, hash_val in ring.ring.items():
            if hash_val in servers[:3]:  # Original servers
                if ring._hash(key) <= s:
                    old_server = hash_val
                    break
        new_server = ring.get_server(key)
        if old_server != new_server:
            moved_keys += 1
    
    redistribution_percentage = (moved_keys / 10000) * 100
    print(f"\nKeys moved: {moved_keys}/10000 ({redistribution_percentage:.1f}%)")
    print("✅ Ideal: Only ~25% of keys should move when adding 1 server to 3")


if __name__ == "__main__":
    test_consistent_hashing()
```

## Implementation 2: Rate Limiter with Token Bucket Algorithm

Rate limiting is crucial for protecting systems from abuse and ensuring fair resource usage. This implementation uses the token bucket algorithm, which allows burst traffic while maintaining average rate limits.

```python
import time
import threading
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum

class RateLimitResult(Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    QUOTA_EXCEEDED = "quota_exceeded"

@dataclass
class RateLimitInfo:
    allowed: bool
    remaining_tokens: int
    reset_time: float
    result: RateLimitResult

class TokenBucketRateLimiter:
    """
    Token bucket rate limiter implementation.
    Used by: AWS API Gateway, Stripe API, GitHub API
    
    Allows burst traffic up to bucket capacity while maintaining
    steady average rate over time.
    """
    
    def __init__(self, capacity: int, refill_rate: float, refill_period: float = 1.0):
        """
        Initialize rate limiter.
        
        Args:
            capacity: Maximum tokens in bucket (burst capacity)
            refill_rate: Tokens added per refill_period
            refill_period: Time interval for refill (seconds)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_period = refill_period
        
        # Per-user token buckets
        self.buckets: Dict[str, Dict] = {}
        self.lock = threading.RLock()
        
    def _get_current_time(self) -> float:
        """Get current timestamp (mockable for testing)"""
        return time.time()
    
    def _refill_bucket(self, bucket_info: Dict) -> None:
        """Refill tokens based on elapsed time"""
        current_time = self._get_current_time()
        time_elapsed = current_time - bucket_info['last_refill']
        
        if time_elapsed >= self.refill_period:
            # Calculate tokens to add
            periods_elapsed = time_elapsed / self.refill_period
            tokens_to_add = int(periods_elapsed * self.refill_rate)
            
            # Add tokens, respecting capacity
            bucket_info['tokens'] = min(
                self.capacity,
                bucket_info['tokens'] + tokens_to_add
            )
            bucket_info['last_refill'] = current_time
    
    def check_rate_limit(self, user_id: str, tokens_requested: int = 1) -> RateLimitInfo:
        """
        Check if request is allowed and consume tokens if so.
        
        Args:
            user_id: Unique identifier for rate limiting
            tokens_requested: Number of tokens to consume
            
        Returns:
            RateLimitInfo with decision and metadata
        """
        with self.lock:
            current_time = self._get_current_time()
            
            # Initialize bucket if doesn't exist
            if user_id not in self.buckets:
                self.buckets[user_id] = {
                    'tokens': self.capacity,
                    'last_refill': current_time
                }
            
            bucket = self.buckets[user_id]
            
            # Refill tokens based on elapsed time
            self._refill_bucket(bucket)
            
            # Check if enough tokens available
            if bucket['tokens'] >= tokens_requested:
                # Consume tokens
                bucket['tokens'] -= tokens_requested
                return RateLimitInfo(
                    allowed=True,
                    remaining_tokens=bucket['tokens'],
                    reset_time=current_time + self.refill_period,
                    result=RateLimitResult.ALLOWED
                )
            else:
                # Not enough tokens
                return RateLimitInfo(
                    allowed=False,
                    remaining_tokens=bucket['tokens'],
                    reset_time=current_time + self.refill_period,
                    result=RateLimitResult.DENIED
                )
    
    def get_bucket_status(self, user_id: str) -> Optional[Dict]:
        """Get current status of user's token bucket"""
        with self.lock:
            if user_id not in self.buckets:
                return None
                
            bucket = self.buckets[user_id]
            self._refill_bucket(bucket)
            
            return {
                'tokens': bucket['tokens'],
                'capacity': self.capacity,
                'last_refill': bucket['last_refill'],
                'refill_rate': self.refill_rate
            }
    
    def reset_bucket(self, user_id: str) -> None:
        """Reset user's token bucket (admin function)"""
        with self.lock:
            if user_id in self.buckets:
                self.buckets[user_id]['tokens'] = self.capacity
                self.buckets[user_id]['last_refill'] = self._get_current_time()


class DistributedRateLimiter:
    """
    Redis-backed distributed rate limiter for multi-server deployments.
    Extends TokenBucketRateLimiter with Redis backend.
    """
    
    def __init__(self, capacity: int, refill_rate: float, redis_client=None):
        """
        Initialize distributed rate limiter.
        
        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens per second
            redis_client: Redis connection (or mock for demo)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.redis = redis_client or self._create_mock_redis()
        
    def _create_mock_redis(self):
        """Create mock Redis for demonstration"""
        class MockRedis:
            def __init__(self):
                self.data = {}
            
            def hget(self, key, field):
                return self.data.get(key, {}).get(field)
            
            def hset(self, key, field, value):
                if key not in self.data:
                    self.data[key] = {}
                self.data[key][field] = value
            
            def expire(self, key, seconds):
                pass  # Mock implementation
                
        return MockRedis()
    
    def check_rate_limit_distributed(self, user_id: str, tokens_requested: int = 1) -> RateLimitInfo:
        """Distributed rate limiting using Redis Lua script"""
        
        # Lua script for atomic rate limiting
        lua_script = """
        local key = KEYS[1]
        local capacity = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local tokens_requested = tonumber(ARGV[3])
        local current_time = tonumber(ARGV[4])
        
        -- Get current bucket state
        local tokens = redis.call('HGET', key, 'tokens')
        local last_refill = redis.call('HGET', key, 'last_refill')
        
        -- Initialize if doesn't exist
        if not tokens then
            tokens = capacity
            last_refill = current_time
        else
            tokens = tonumber(tokens)
            last_refill = tonumber(last_refill)
        end
        
        -- Refill tokens
        local time_elapsed = current_time - last_refill
        if time_elapsed > 0 then
            local tokens_to_add = math.floor(time_elapsed * refill_rate)
            tokens = math.min(capacity, tokens + tokens_to_add)
            last_refill = current_time
        end
        
        -- Check if request allowed
        if tokens >= tokens_requested then
            tokens = tokens - tokens_requested
            -- Update Redis
            redis.call('HSET', key, 'tokens', tokens)
            redis.call('HSET', key, 'last_refill', last_refill)
            redis.call('EXPIRE', key, 3600)  -- 1 hour TTL
            return {1, tokens}  -- allowed, remaining
        else
            return {0, tokens}  -- denied, remaining
        end
        """
        
        # In real implementation, you'd use redis.eval()
        # For demo, we'll simulate the logic
        current_time = time.time()
        key = f"rate_limit:{user_id}"
        
        # Simulate Lua script execution
        tokens = self.redis.hget(key, 'tokens')
        last_refill = self.redis.hget(key, 'last_refill')
        
        if tokens is None:
            tokens = self.capacity
            last_refill = current_time
        else:
            tokens = int(tokens)
            last_refill = float(last_refill)
        
        # Refill logic
        time_elapsed = current_time - last_refill
        if time_elapsed > 0:
            tokens_to_add = int(time_elapsed * self.refill_rate)
            tokens = min(self.capacity, tokens + tokens_to_add)
            last_refill = current_time
        
        # Check and consume
        if tokens >= tokens_requested:
            tokens -= tokens_requested
            self.redis.hset(key, 'tokens', str(tokens))
            self.redis.hset(key, 'last_refill', str(last_refill))
            self.redis.expire(key, 3600)
            
            return RateLimitInfo(
                allowed=True,
                remaining_tokens=tokens,
                reset_time=current_time + (self.capacity - tokens) / self.refill_rate,
                result=RateLimitResult.ALLOWED
            )
        else:
            return RateLimitInfo(
                allowed=False,
                remaining_tokens=tokens,
                reset_time=current_time + (1 - tokens) / self.refill_rate,
                result=RateLimitResult.DENIED
            )


# Example usage and testing
def test_rate_limiter():
    """Demonstrate rate limiter behavior"""
    print("=== Rate Limiter Demo ===\n")
    
    # Create rate limiter: 10 requests per second, burst of 20
    limiter = TokenBucketRateLimiter(
        capacity=20,      # 20 token burst capacity
        refill_rate=10,   # 10 tokens per second
        refill_period=1.0
    )
    
    user_id = "user123"
    
    print("--- Burst Test (should allow 20 rapid requests) ---")
    allowed_count = 0
    for i in range(25):  # Try 25 requests rapidly
        result = limiter.check_rate_limit(user_id)
        if result.allowed:
            allowed_count += 1
            status = "✅ ALLOWED"
        else:
            status = "❌ DENIED"
        
        print(f"Request {i+1}: {status} (remaining: {result.remaining_tokens})")
        
        if i == 10:  # Show burst exhaustion
            print("  ↳ Burst capacity being consumed...")
        elif i == 19:
            print("  ↳ Burst capacity exhausted, subsequent requests denied")
    
    print(f"\nBurst result: {allowed_count}/25 requests allowed")
    
    print("\n--- Sustained Rate Test (10 RPS) ---")
    print("Waiting for bucket to refill...")
    time.sleep(2)  # Wait for refill
    
    # Test sustained rate
    for i in range(15):
        result = limiter.check_rate_limit(user_id)
        status = "✅ ALLOWED" if result.allowed else "❌ DENIED"
        print(f"Request {i+1}: {status} (remaining: {result.remaining_tokens})")
        time.sleep(0.1)  # 100ms between requests = 10 RPS
    
    print("\n--- Bucket Status ---")
    status = limiter.get_bucket_status(user_id)
    print(f"Current tokens: {status['tokens']}/{status['capacity']}")
    print(f"Refill rate: {status['refill_rate']} tokens/second")


def test_distributed_rate_limiter():
    """Demonstrate distributed rate limiter"""
    print("\n=== Distributed Rate Limiter Demo ===\n")
    
    limiter = DistributedRateLimiter(capacity=5, refill_rate=1)  # 1 RPS, burst 5
    
    user_id = "user456"
    
    print("--- Testing distributed rate limiting ---")
    for i in range(8):
        result = limiter.check_rate_limit_distributed(user_id)
        status = "✅ ALLOWED" if result.allowed else "❌ DENIED"
        print(f"Request {i+1}: {status} (remaining: {result.remaining_tokens})")
        time.sleep(0.5)  # 500ms between requests


if __name__ == "__main__":
    test_rate_limiter()
    test_distributed_rate_limiter()
```

## Implementation 3: Circuit Breaker Pattern

Circuit breakers prevent cascade failures by stopping calls to failing services and allowing them time to recover.

```python
import time
import random
import threading
from enum import Enum
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered

@dataclass
class CircuitBreakerStats:
    """Statistics for monitoring circuit breaker behavior"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    requests_blocked: int = 0
    state_changes: int = 0
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None

class CircuitBreakerOpenException(Exception):
    """Raised when circuit breaker is open"""
    pass

class CircuitBreaker:
    """
    Circuit breaker implementation for fault tolerance.
    Used by: Netflix Hystrix, AWS Lambda, resilience libraries
    
    Prevents cascade failures by stopping calls to failing services.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        expected_exception: type = Exception,
        success_threshold: int = 3
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Failures needed to open circuit
            recovery_timeout: Seconds to wait before trying half-open
            expected_exception: Exception type that counts as failure
            success_threshold: Successes needed to close from half-open
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.success_threshold = success_threshold
        
        # State tracking
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        
        # Statistics
        self.stats = CircuitBreakerStats()
        
        # Thread safety
        self.lock = threading.RLock()
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator usage: @circuit_breaker"""
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)
        return wrapper
    
    def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker.
        
        Args:
            func: Function to execute
            *args, **kwargs: Arguments for function
            
        Returns:
            Function result
            
        Raises:
            CircuitBreakerOpenException: If circuit is open
            Original exception: If function fails in closed/half-open state
        """
        with self.lock:
            self.stats.total_requests += 1
            
            # Check if circuit should transition from open to half-open
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._transition_to_half_open()
                else:
                    self.stats.requests_blocked += 1
                    raise CircuitBreakerOpenException(
                        f"Circuit breaker is OPEN. Last failure: {self.last_failure_time}"
                    )
            
            # Attempt to call the function
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
                
            except self.expected_exception as e:
                self._on_failure()
                raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try half-open state"""
        if self.last_failure_time is None:
            return False
        return time.time() - self.last_failure_time >= self.recovery_timeout
    
    def _on_success(self) -> None:
        """Handle successful function call"""
        self.stats.successful_requests += 1
        self.stats.last_success_time = datetime.now()
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._transition_to_closed()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on any success in closed state
            self.failure_count = 0
    
    def _on_failure(self) -> None:
        """Handle failed function call"""
        self.stats.failed_requests += 1
        self.stats.last_failure_time = datetime.now()
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition_to_open()
        elif self.state == CircuitState.HALF_OPEN:
            # Any failure in half-open immediately goes back to open
            self._transition_to_open()
    
    def _transition_to_open(self) -> None:
        """Transition circuit breaker to OPEN state"""
        self.state = CircuitState.OPEN
        self.stats.state_changes += 1
        print(f"🔴 Circuit breaker OPENED at {datetime.now()}")
    
    def _transition_to_half_open(self) -> None:
        """Transition circuit breaker to HALF_OPEN state"""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.stats.state_changes += 1
        print(f"🟡 Circuit breaker HALF-OPEN at {datetime.now()}")
    
    def _transition_to_closed(self) -> None:
        """Transition circuit breaker to CLOSED state"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.stats.state_changes += 1
        print(f"🟢 Circuit breaker CLOSED at {datetime.now()}")
    
    def get_state(self) -> CircuitState:
        """Get current circuit breaker state"""
        return self.state
    
    def get_stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics"""
        return self.stats
    
    def reset(self) -> None:
        """Manually reset circuit breaker to closed state"""
        with self.lock:
            self._transition_to_closed()


# Example usage with simulated failing service
class UnreliableService:
    """Simulates a service that fails intermittently"""
    
    def __init__(self, failure_rate: float = 0.7):
        self.failure_rate = failure_rate
        self.call_count = 0
    
    def make_request(self, data: str) -> str:
        """Simulate service call that may fail"""
        self.call_count += 1
        
        # Simulate recovery after some time
        if self.call_count > 20:
            self.failure_rate = 0.1  # Much more reliable
        
        if random.random() < self.failure_rate:
            raise ConnectionError(f"Service failed on call {self.call_count}")
        
        return f"Success! Processed: {data} (call #{self.call_count})"


def test_circuit_breaker():
    """Demonstrate circuit breaker behavior"""
    print("=== Circuit Breaker Demo ===\n")
    
    # Create unreliable service and circuit breaker
    service = UnreliableService(failure_rate=0.8)  # 80% failure rate initially
    circuit_breaker = CircuitBreaker(
        failure_threshold=3,    # Open after 3 failures
        recovery_timeout=5.0,   # Try recovery after 5 seconds
        success_threshold=2     # Close after 2 successes
    )
    
    def protected_service_call(data: str) -> str:
        """Service call protected by circuit breaker"""
        return circuit_breaker.call(service.make_request, data)
    
    print("--- Testing with high failure rate (80%) ---")
    
    # Phase 1: Circuit will open due to failures
    for i in range(10):
        try:
            result = protected_service_call(f"request_{i}")
            print(f"✅ Request {i}: {result}")
        except CircuitBreakerOpenException:
            print(f"🚫 Request {i}: Circuit breaker is OPEN - request blocked")
        except Exception as e:
            print(f"❌ Request {i}: Service failed - {e}")
        
        time.sleep(0.5)
    
    print(f"\n--- Circuit State: {circuit_breaker.get_state().value.upper()} ---")
    
    # Phase 2: Wait for recovery timeout
    print(f"\nWaiting {circuit_breaker.recovery_timeout} seconds for recovery timeout...")
    time.sleep(circuit_breaker.recovery_timeout + 1)
    
    print("\n--- Testing recovery (service improved after 20 calls) ---")
    
    # Phase 3: Circuit will go half-open and potentially close
    for i in range(10, 20):
        try:
            result = protected_service_call(f"request_{i}")
            print(f"✅ Request {i}: {result}")
        except CircuitBreakerOpenException:
            print(f"🚫 Request {i}: Circuit breaker is OPEN - request blocked")
        except Exception as e:
            print(f"❌ Request {i}: Service failed - {e}")
        
        time.sleep(1)
    
    # Show final statistics
    stats = circuit_breaker.get_stats()
    print(f"\n--- Final Statistics ---")
    print(f"Total requests: {stats.total_requests}")
    print(f"Successful: {stats.successful_requests}")
    print(f"Failed: {stats.failed_requests}")
    print(f"Blocked: {stats.requests_blocked}")
    print(f"State changes: {stats.state_changes}")
    print(f"Final state: {circuit_breaker.get_state().value.upper()}")


# Advanced: Bulk Circuit Breaker for multiple services
class ServiceRegistry:
    """Registry to manage circuit breakers for multiple services"""
    
    def __init__(self):
        self.circuits: dict[str, CircuitBreaker] = {}
        self.lock = threading.RLock()
    
    def get_circuit(self, service_name: str, **kwargs) -> CircuitBreaker:
        """Get or create circuit breaker for service"""
        with self.lock:
            if service_name not in self.circuits:
                self.circuits[service_name] = CircuitBreaker(**kwargs)
            return self.circuits[service_name]
    
    def call_service(self, service_name: str, func: Callable, *args, **kwargs) -> Any:
        """Call service through its circuit breaker"""
        circuit = self.get_circuit(service_name)
        return circuit.call(func, *args, **kwargs)
    
    def get_all_stats(self) -> dict[str, CircuitBreakerStats]:
        """Get statistics for all services"""
        return {name: circuit.get_stats() for name, circuit in self.circuits.items()}


def test_service_registry():
    """Demonstrate service registry with multiple circuit breakers"""
    print("\n=== Service Registry Demo ===\n")
    
    registry = ServiceRegistry()
    
    # Create different services with different reliability
    payment_service = UnreliableService(failure_rate=0.9)  # Very unreliable
    user_service = UnreliableService(failure_rate=0.3)     # Somewhat reliable
    email_service = UnreliableService(failure_rate=0.1)    # Very reliable
    
    services = {
        "payment": payment_service,
        "user": user_service,
        "email": email_service
    }
    
    print("--- Testing multiple services with different reliability ---")
    
    for i in range(15):
        for service_name, service in services.items():
            try:
                result = registry.call_service(
                    service_name,
                    service.make_request,
                    f"data_{i}"
                )
                print(f"✅ {service_name}: Success")
            except CircuitBreakerOpenException:
                print(f"🚫 {service_name}: Circuit OPEN")
            except Exception:
                print(f"❌ {service_name}: Service failed")
        
        time.sleep(0.2)
    
    # Show stats for all services
    print(f"\n--- Service Statistics ---")
    all_stats = registry.get_all_stats()
    for service_name, stats in all_stats.items():
        circuit = registry.get_circuit(service_name)
        print(f"{service_name.upper()}:")
        print(f"  State: {circuit.get_state().value.upper()}")
        print(f"  Success rate: {stats.successful_requests}/{stats.total_requests}")
        print(f"  Blocked requests: {stats.requests_blocked}")


if __name__ == "__main__":
    test_circuit_breaker()
    test_service_registry()
```

## Running the Examples

To run these implementations:

```bash
# Save each implementation to a separate file
python consistent_hashing.py
python rate_limiter.py  
python circuit_breaker.py

# Or run all examples
python 04-python-implementation.py
```

## Key Takeaways

These implementations demonstrate fundamental patterns used in production systems:

1. **Consistent Hashing**: Enables horizontal scaling with minimal data movement
2. **Rate Limiting**: Protects services from abuse and ensures fair usage
3. **Circuit Breaker**: Prevents cascade failures in distributed systems

Each pattern addresses specific challenges in distributed systems and can be combined to build robust, scalable architectures.

### Production Considerations

When implementing these patterns in production:

- **Monitoring**: Add comprehensive metrics and alerting
- **Configuration**: Make parameters configurable and tunable
- **Persistence**: Use Redis/database for state that needs to survive restarts
- **Testing**: Include chaos engineering to test failure scenarios
- **Documentation**: Document configuration and expected behavior

These patterns form the foundation of reliable distributed systems used by companies like Netflix, Amazon, and Google to serve millions of users reliably.