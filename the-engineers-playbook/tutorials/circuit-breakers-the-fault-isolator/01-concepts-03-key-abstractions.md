# Key Abstractions: The Building Blocks of Circuit Breakers

## The Circuit State: Your System's Traffic Light

The circuit state is the heart of the pattern. Think of it as a traffic light for your service calls:

### Closed State (Green Light)
```
State: CLOSED
Error Rate: 5% (below threshold)
Recent Requests: ✓✓✓✓✗✓✓✓✓✓
Action: Allow all requests through
```

In the closed state:
- All requests pass through normally
- Success and failure rates are monitored
- The circuit breaker is "invisible" to the application
- This is the default, healthy state

### Open State (Red Light)
```
State: OPEN
Error Rate: 85% (above threshold)
Time Since Opening: 30 seconds
Action: Reject all requests immediately
```

In the open state:
- All requests are immediately rejected
- No actual service calls are made
- A default response or cached data is returned
- The circuit stays open for a configured timeout period

### Half-Open State (Yellow Light)
```
State: HALF-OPEN
Test Request: In progress...
Action: Allow limited requests to test health
```

In the half-open state:
- A small number of requests are allowed through
- If they succeed, the circuit closes
- If they fail, the circuit opens again
- This is the "testing" state

## The Failure Threshold: When to Act

The failure threshold determines when the circuit opens. It's typically expressed as:

### Error Rate Threshold
```
threshold = failed_requests / total_requests
```

**Example configurations:**
- `50%` - Open when half of requests fail (aggressive)
- `70%` - Open when 70% of requests fail (moderate)
- `90%` - Open when 90% of requests fail (conservative)

### Minimum Request Volume
```
minimum_requests = 10  // Need at least 10 requests before evaluating
```

This prevents the circuit from opening due to a single failed request when traffic is low.

### Time Window
```
time_window = 60 seconds  // Evaluate failure rate over last 60 seconds
```

This ensures you're looking at recent failures, not historical ones.

## The Timeout: Recovery Time

The timeout determines how long the circuit stays open before testing recovery:

```
timeout = 30 seconds  // Stay open for 30 seconds, then try half-open
```

**Shorter timeouts (5-10 seconds):**
- Faster recovery
- Risk of oscillation if service is still failing
- Good for transient network issues

**Longer timeouts (60+ seconds):**
- Slower recovery
- More stable behavior
- Good for service deployments or database restarts

## The Request Volume Window: Statistical Significance

Circuit breakers typically use a sliding window to track requests:

### Fixed Window
```
Window: [12:00:00 - 12:00:59]
Requests: 100
Failures: 45
Error Rate: 45%
```

### Sliding Window
```
Current Time: 12:00:30
Window: [11:59:30 - 12:00:30]
Requests: 100
Failures: 45
Error Rate: 45%
```

Sliding windows provide more accurate real-time monitoring.

## The Fallback Strategy: What to Do When Open

When the circuit is open, you need a fallback strategy:

### Static Fallback
```rust
fn get_user_recommendations(user_id: u64) -> Vec<Product> {
    match circuit_breaker.call(|| recommendation_service.get(user_id)) {
        Ok(recommendations) => recommendations,
        Err(_) => vec![
            Product::new("Popular Item 1"),
            Product::new("Popular Item 2"),
            Product::new("Popular Item 3"),
        ]
    }
}
```

### Cache Fallback
```rust
fn get_user_profile(user_id: u64) -> Option<UserProfile> {
    match circuit_breaker.call(|| user_service.get(user_id)) {
        Ok(profile) => {
            cache.put(user_id, profile.clone());
            Some(profile)
        },
        Err(_) => cache.get(user_id)
    }
}
```

### Fail Silent
```rust
fn send_analytics_event(event: Event) {
    let _ = circuit_breaker.call(|| analytics_service.send(event));
    // If it fails, just continue - analytics isn't critical
}
```

## The Recovery Strategy: Testing the Waters

When transitioning from open to half-open, you need a recovery strategy:

### Single Request Test
```
Half-Open → Send 1 request → Success? → Close : Open
```

### Gradual Recovery
```
Half-Open → Send 10% of requests → Success rate > 80%? → Close : Open
```

### Canary Testing
```
Half-Open → Send requests from test users → Monitor carefully → Decide
```

## Implementation Patterns

### Per-Service Circuit Breakers
```rust
struct ServiceCluster {
    user_service: CircuitBreaker<UserService>,
    order_service: CircuitBreaker<OrderService>,
    payment_service: CircuitBreaker<PaymentService>,
}
```

Each service gets its own circuit breaker with its own thresholds and timeouts.

### Per-Operation Circuit Breakers
```rust
struct UserService {
    get_profile: CircuitBreaker<GetProfileOp>,
    update_profile: CircuitBreaker<UpdateProfileOp>,
    delete_user: CircuitBreaker<DeleteUserOp>,
}
```

Different operations on the same service might have different failure characteristics.

### Hierarchical Circuit Breakers
```rust
struct DatabaseCluster {
    primary: CircuitBreaker<PrimaryDB>,
    replica: CircuitBreaker<ReplicaDB>,
    cache: CircuitBreaker<CacheDB>,
}
```

When primary fails, try replica. When replica fails, try cache.

## Metrics and Observability

Circuit breakers should expose key metrics:

### State Metrics
```
circuit_breaker_state{service="user_service"} 0  // 0=closed, 1=open, 2=half-open
circuit_breaker_state{service="order_service"} 1
```

### Request Metrics
```
circuit_breaker_requests_total{service="user_service",state="closed"} 1500
circuit_breaker_requests_total{service="user_service",state="open"} 45
circuit_breaker_failures_total{service="user_service"} 123
```

### Timing Metrics
```
circuit_breaker_state_duration_seconds{service="user_service",state="open"} 32.5
circuit_breaker_last_failure_timestamp{service="user_service"} 1634567890
```

## Configuration Best Practices

### Development Environment
```yaml
failure_threshold: 90%    # High threshold for development
timeout: 5s              # Quick recovery for testing
minimum_requests: 5      # Low volume threshold
```

### Production Environment
```yaml
failure_threshold: 50%    # Lower threshold for production
timeout: 30s             # Longer timeout for stability
minimum_requests: 20     # Higher volume threshold
```

### Critical Services
```yaml
failure_threshold: 30%    # Very sensitive to failures
timeout: 60s             # Longer recovery time
minimum_requests: 10     # Moderate volume threshold
```

These abstractions work together to create a system that can intelligently handle failures, protect resources, and recover automatically. The key is tuning them appropriately for your specific use case and monitoring their behavior in production.