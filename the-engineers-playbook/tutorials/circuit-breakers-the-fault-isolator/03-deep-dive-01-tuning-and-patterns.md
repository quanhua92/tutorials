# Deep Dive: Tuning and Advanced Patterns

## The Art of Threshold Setting

Setting circuit breaker thresholds is more art than science. Too sensitive and you'll have false positives. Too lenient and you won't protect against real failures.

### The Three-Tier Approach

**Tier 1: Critical Services (Conservative)**
```yaml
failure_threshold: 30%
minimum_requests: 20
timeout: 60s
```

These are services that, if they fail, significantly impact user experience. Be conservative:
- Payment processing
- User authentication
- Core business logic

**Tier 2: Important Services (Moderate)**
```yaml
failure_threshold: 50%
minimum_requests: 10
timeout: 30s
```

These services matter but have acceptable fallbacks:
- Recommendation engines
- Search services
- Content personalization

**Tier 3: Non-Critical Services (Aggressive)**
```yaml
failure_threshold: 70%
minimum_requests: 5
timeout: 10s
```

These services are nice-to-have but not essential:
- Analytics
- A/B testing
- Metrics collection

### Dynamic Threshold Adjustment

```rust
struct AdaptiveCircuitBreaker {
    base_threshold: f64,
    current_threshold: f64,
    success_streak: u32,
    failure_streak: u32,
}

impl AdaptiveCircuitBreaker {
    fn adjust_threshold(&mut self, request_volume: u32) {
        // Lower threshold during high traffic (more sensitive)
        if request_volume > 1000 {
            self.current_threshold = self.base_threshold * 0.8;
        }
        // Higher threshold during low traffic (less sensitive)
        else if request_volume < 100 {
            self.current_threshold = self.base_threshold * 1.2;
        }
        
        // Adjust based on recent patterns
        if self.success_streak > 50 {
            self.current_threshold = self.base_threshold * 1.1; // More lenient
        }
        if self.failure_streak > 10 {
            self.current_threshold = self.base_threshold * 0.9; // More strict
        }
    }
}
```

## Advanced Recovery Patterns

### Slow-Start Recovery

Instead of going from open directly to closed, gradually increase traffic:

```rust
struct SlowStartCircuitBreaker {
    recovery_factor: f64,
    max_recovery_requests: u32,
    current_recovery_requests: u32,
}

impl SlowStartCircuitBreaker {
    fn should_allow_request_in_recovery(&mut self) -> bool {
        if self.current_recovery_requests >= self.max_recovery_requests {
            return false;
        }
        
        // Start with 10% of normal traffic, increase gradually
        let allow_probability = 0.1 + (self.recovery_factor * 0.1);
        let should_allow = rand::random::<f64>() < allow_probability;
        
        if should_allow {
            self.current_recovery_requests += 1;
        }
        
        should_allow
    }
    
    fn on_recovery_success(&mut self) {
        self.recovery_factor += 0.1;
        if self.recovery_factor >= 1.0 {
            // Fully recovered, close the circuit
            self.close_circuit();
        }
    }
}
```

### Circuit Breaker Chains

For complex service dependencies, chain circuit breakers:

```rust
struct ServiceChain {
    primary: CircuitBreaker<PrimaryService>,
    fallback: CircuitBreaker<FallbackService>,
    cache: CircuitBreaker<CacheService>,
}

impl ServiceChain {
    fn get_data(&self, key: &str) -> Result<Data, Error> {
        // Try primary first
        if let Ok(data) = self.primary.call(|service| service.get(key)) {
            return Ok(data);
        }
        
        // Try fallback
        if let Ok(data) = self.fallback.call(|service| service.get(key)) {
            return Ok(data);
        }
        
        // Try cache as last resort
        self.cache.call(|service| service.get(key))
    }
}
```

### Request Hedging

Send duplicate requests to increase success probability:

```rust
struct HedgedCircuitBreaker {
    primary: CircuitBreaker<PrimaryService>,
    secondary: CircuitBreaker<SecondaryService>,
    hedge_delay: Duration,
}

impl HedgedCircuitBreaker {
    async fn call_with_hedge<F, R>(&self, operation: F) -> Result<R, Error>
    where
        F: Fn(&Service) -> Result<R, Error> + Send + 'static,
        R: Send + 'static,
    {
        // Start primary request
        let primary_future = self.primary.call_async(operation);
        
        // Wait for hedge delay
        tokio::time::sleep(self.hedge_delay).await;
        
        // If primary hasn't completed, start secondary
        let secondary_future = self.secondary.call_async(operation);
        
        // Return whichever completes first
        tokio::select! {
            result = primary_future => result,
            result = secondary_future => result,
        }
    }
}
```

## Sophisticated Failure Detection

### Composite Health Checks

Don't just count failures - analyze failure types:

```rust
#[derive(Debug, Clone)]
enum FailureType {
    Timeout,
    ConnectionError,
    ServiceError(u16), // HTTP status code
    ParseError,
}

struct IntelligentCircuitBreaker {
    failure_weights: HashMap<FailureType, f64>,
    weighted_failure_score: f64,
    threshold: f64,
}

impl IntelligentCircuitBreaker {
    fn on_failure(&mut self, failure_type: FailureType) {
        let weight = self.failure_weights.get(&failure_type).unwrap_or(&1.0);
        self.weighted_failure_score += weight;
        
        // Different failure types have different impacts
        match failure_type {
            FailureType::Timeout => {
                // Timeouts might indicate overload - be more aggressive
                self.weighted_failure_score += 0.5;
            }
            FailureType::ServiceError(503) => {
                // Service unavailable - definitely open
                self.weighted_failure_score += 2.0;
            }
            FailureType::ServiceError(400..=499) => {
                // Client errors - might not be service's fault
                self.weighted_failure_score += 0.1;
            }
            _ => {}
        }
    }
}
```

### Latency-Based Circuit Breaking

Open the circuit based on response time, not just failures:

```rust
struct LatencyCircuitBreaker {
    latency_threshold: Duration,
    slow_request_count: u32,
    slow_request_threshold: u32,
    request_history: VecDeque<Duration>,
}

impl LatencyCircuitBreaker {
    fn on_request_complete(&mut self, duration: Duration) {
        self.request_history.push_back(duration);
        
        // Keep only last 100 requests
        if self.request_history.len() > 100 {
            self.request_history.pop_front();
        }
        
        // Check if request was slow
        if duration > self.latency_threshold {
            self.slow_request_count += 1;
        }
        
        // Calculate 95th percentile latency
        let mut sorted_latencies: Vec<Duration> = self.request_history.iter().cloned().collect();
        sorted_latencies.sort();
        
        if let Some(p95) = sorted_latencies.get(95) {
            if *p95 > self.latency_threshold * 2 {
                // P95 latency is too high - open circuit
                self.open_circuit();
            }
        }
    }
}
```

## Production Monitoring and Alerting

### Metrics That Matter

```rust
pub struct CircuitBreakerMetrics {
    // State metrics
    pub state: CircuitState,
    pub state_duration: Duration,
    pub state_transitions: u64,
    
    // Request metrics
    pub total_requests: u64,
    pub successful_requests: u64,
    pub failed_requests: u64,
    pub rejected_requests: u64,
    
    // Performance metrics
    pub average_response_time: Duration,
    pub p95_response_time: Duration,
    pub p99_response_time: Duration,
    
    // Health metrics
    pub current_error_rate: f64,
    pub last_failure_time: Option<Instant>,
    pub consecutive_failures: u32,
}
```

### Alert Conditions

```yaml
# High-priority alerts
circuit_breaker_state{service="payment"} == 1  # Payment circuit open
circuit_breaker_error_rate{service="auth"} > 0.1  # Auth error rate > 10%

# Medium-priority alerts
circuit_breaker_state_duration{service="any"} > 300  # Circuit open > 5 minutes
circuit_breaker_rejection_rate{service="any"} > 0.5  # 50% requests rejected

# Low-priority alerts
circuit_breaker_state_transitions{service="any"} > 10  # Circuit flapping
circuit_breaker_p95_latency{service="any"} > 1000  # P95 latency > 1 second
```

## Configuration Management

### Environment-Specific Settings

```rust
#[derive(Deserialize)]
struct CircuitBreakerConfig {
    failure_threshold: f64,
    timeout: Duration,
    minimum_requests: u32,
    
    // Environment-specific overrides
    #[serde(default)]
    development: Option<CircuitBreakerConfig>,
    #[serde(default)]
    staging: Option<CircuitBreakerConfig>,
    #[serde(default)]
    production: Option<CircuitBreakerConfig>,
}

impl CircuitBreakerConfig {
    fn for_environment(&self, env: &str) -> Self {
        let mut config = self.clone();
        
        match env {
            "development" => {
                if let Some(dev_config) = &self.development {
                    config.merge(dev_config);
                }
            }
            "staging" => {
                if let Some(staging_config) = &self.staging {
                    config.merge(staging_config);
                }
            }
            "production" => {
                if let Some(prod_config) = &self.production {
                    config.merge(prod_config);
                }
            }
            _ => {}
        }
        
        config
    }
}
```

### Dynamic Configuration Updates

```rust
struct ConfigurableCircuitBreaker {
    config: Arc<RwLock<CircuitBreakerConfig>>,
    // ... other fields
}

impl ConfigurableCircuitBreaker {
    fn update_config(&self, new_config: CircuitBreakerConfig) {
        let mut config = self.config.write().unwrap();
        *config = new_config;
        
        // Log configuration change
        info!(
            "Circuit breaker config updated: threshold={}, timeout={:?}",
            config.failure_threshold,
            config.timeout
        );
    }
    
    fn get_current_threshold(&self) -> f64 {
        let config = self.config.read().unwrap();
        config.failure_threshold
    }
}
```

## Testing Strategies

### Chaos Engineering

```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_circuit_breaker_under_chaos() {
        let mut service = MockService::new();
        
        // Inject various failure patterns
        service.set_failure_pattern(vec![
            FailureType::Timeout,
            FailureType::ServiceError(500),
            FailureType::ConnectionError,
        ]);
        
        let circuit_breaker = CircuitBreaker::new(service, 0.5, Duration::from_secs(5));
        
        // Send requests and verify circuit behavior
        for i in 0..100 {
            let result = circuit_breaker.call(|s| s.make_request(i));
            // Assert expected behavior based on failure pattern
        }
    }
}
```

### Load Testing

```rust
#[tokio::test]
async fn test_circuit_breaker_under_load() {
    let circuit_breaker = Arc::new(CircuitBreaker::new(
        MockService::new(),
        0.5,
        Duration::from_secs(5),
    ));
    
    // Spawn multiple concurrent requests
    let mut handles = vec![];
    for i in 0..1000 {
        let cb = circuit_breaker.clone();
        let handle = tokio::spawn(async move {
            cb.call(|s| s.make_request(i)).await
        });
        handles.push(handle);
    }
    
    // Wait for all requests to complete
    let results = future::join_all(handles).await;
    
    // Analyze results
    let success_count = results.iter().filter(|r| r.is_ok()).count();
    let failure_count = results.len() - success_count;
    
    println!("Success rate: {:.2}%", success_count as f64 / results.len() as f64 * 100.0);
}
```

## Common Pitfalls and Solutions

### Pitfall 1: Circuit Breaker Thrashing

**Problem**: Circuit opens and closes rapidly
**Solution**: Implement minimum time in each state

```rust
struct StableCircuitBreaker {
    min_closed_time: Duration,
    min_open_time: Duration,
    last_state_change: Instant,
}
```

### Pitfall 2: Thundering Herd on Recovery

**Problem**: All instances try to recover simultaneously
**Solution**: Add jitter to recovery attempts

```rust
fn should_attempt_recovery(&self) -> bool {
    let base_timeout = self.timeout;
    let jitter = Duration::from_millis(rand::random::<u64>() % 1000);
    let actual_timeout = base_timeout + jitter;
    
    self.last_failure_time.elapsed() >= actual_timeout
}
```

### Pitfall 3: Ignoring Fallback Quality

**Problem**: Fallback responses are poor quality
**Solution**: Implement graduated fallbacks

```rust
enum FallbackStrategy {
    RecentCache,      // Last 5 minutes
    StaleCache,       // Last hour
    DefaultResponse,  // Hardcoded response
    Fail,            // Return error
}
```

Circuit breakers are powerful tools, but they require careful tuning and monitoring to be effective. The key is to start with conservative settings and adjust based on observed behavior in production.