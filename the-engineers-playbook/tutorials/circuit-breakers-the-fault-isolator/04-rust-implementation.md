# Rust Implementation: Production-Ready Circuit Breaker

## Complete Implementation

Here's a fully-featured, production-ready circuit breaker implementation in Rust:

```rust
use std::collections::VecDeque;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;
use tokio::time::timeout;

#[derive(Debug, Clone, PartialEq)]
pub enum CircuitState {
    Closed,
    Open,
    HalfOpen,
}

#[derive(Debug, Clone)]
pub struct CircuitBreakerConfig {
    pub failure_threshold: f64,
    pub success_threshold: u32,
    pub timeout: Duration,
    pub max_concurrent_requests: u32,
    pub request_timeout: Duration,
    pub minimum_requests: u32,
    pub sliding_window_size: u32,
}

impl Default for CircuitBreakerConfig {
    fn default() -> Self {
        Self {
            failure_threshold: 0.5,
            success_threshold: 3,
            timeout: Duration::from_secs(30),
            max_concurrent_requests: 100,
            request_timeout: Duration::from_secs(10),
            minimum_requests: 10,
            sliding_window_size: 100,
        }
    }
}

#[derive(Debug)]
pub struct CircuitBreakerMetrics {
    pub state: CircuitState,
    pub failure_count: u32,
    pub success_count: u32,
    pub total_requests: u64,
    pub rejected_requests: u64,
    pub error_rate: f64,
    pub average_response_time: Duration,
    pub last_failure_time: Option<Instant>,
    pub state_duration: Duration,
}

#[derive(Debug)]
pub enum CircuitBreakerError<E> {
    CircuitOpen,
    Timeout,
    TooManyRequests,
    ServiceError(E),
}

struct RequestRecord {
    timestamp: Instant,
    duration: Duration,
    success: bool,
}

struct CircuitBreakerState {
    state: CircuitState,
    failure_count: u32,
    success_count: u32,
    last_failure_time: Option<Instant>,
    last_state_change: Instant,
    request_history: VecDeque<RequestRecord>,
    total_requests: u64,
    rejected_requests: u64,
}

pub struct CircuitBreaker {
    state: Arc<RwLock<CircuitBreakerState>>,
    config: CircuitBreakerConfig,
    semaphore: Arc<Semaphore>,
}

impl CircuitBreaker {
    pub fn new(config: CircuitBreakerConfig) -> Self {
        let semaphore = Arc::new(Semaphore::new(config.max_concurrent_requests as usize));
        
        Self {
            state: Arc::new(RwLock::new(CircuitBreakerState {
                state: CircuitState::Closed,
                failure_count: 0,
                success_count: 0,
                last_failure_time: None,
                last_state_change: Instant::now(),
                request_history: VecDeque::new(),
                total_requests: 0,
                rejected_requests: 0,
            })),
            config,
            semaphore,
        }
    }

    pub async fn call<F, Fut, T, E>(&self, operation: F) -> Result<T, CircuitBreakerError<E>>
    where
        F: FnOnce() -> Fut,
        Fut: std::future::Future<Output = Result<T, E>>,
    {
        // Check if request should be allowed
        if !self.should_allow_request() {
            self.increment_rejected_requests();
            return Err(CircuitBreakerError::CircuitOpen);
        }

        // Acquire semaphore permit for concurrency control
        let _permit = self.semaphore.try_acquire()
            .map_err(|_| CircuitBreakerError::TooManyRequests)?;

        let start_time = Instant::now();
        
        // Execute operation with timeout
        let result = timeout(self.config.request_timeout, operation()).await;
        
        let duration = start_time.elapsed();
        
        match result {
            Ok(Ok(response)) => {
                self.record_success(duration);
                Ok(response)
            }
            Ok(Err(error)) => {
                self.record_failure(duration);
                Err(CircuitBreakerError::ServiceError(error))
            }
            Err(_) => {
                self.record_failure(duration);
                Err(CircuitBreakerError::Timeout)
            }
        }
    }

    fn should_allow_request(&self) -> bool {
        let state = self.state.read().unwrap();
        
        match state.state {
            CircuitState::Closed => true,
            CircuitState::Open => self.should_attempt_reset(&state),
            CircuitState::HalfOpen => true,
        }
    }

    fn should_attempt_reset(&self, state: &CircuitBreakerState) -> bool {
        state.last_state_change.elapsed() >= self.config.timeout
    }

    fn record_success(&self, duration: Duration) {
        let mut state = self.state.write().unwrap();
        
        state.success_count += 1;
        state.total_requests += 1;
        
        let record = RequestRecord {
            timestamp: Instant::now(),
            duration,
            success: true,
        };
        
        self.add_request_record(&mut state, record);
        
        match state.state {
            CircuitState::HalfOpen => {
                if state.success_count >= self.config.success_threshold {
                    self.transition_to_closed(&mut state);
                }
            }
            CircuitState::Closed => {
                // Reset failure count on success
                state.failure_count = 0;
            }
            _ => {}
        }
    }

    fn record_failure(&self, duration: Duration) {
        let mut state = self.state.write().unwrap();
        
        state.failure_count += 1;
        state.total_requests += 1;
        state.last_failure_time = Some(Instant::now());
        
        let record = RequestRecord {
            timestamp: Instant::now(),
            duration,
            success: false,
        };
        
        self.add_request_record(&mut state, record);
        
        match state.state {
            CircuitState::Closed => {
                if self.should_open_circuit(&state) {
                    self.transition_to_open(&mut state);
                }
            }
            CircuitState::HalfOpen => {
                self.transition_to_open(&mut state);
            }
            _ => {}
        }
    }

    fn should_open_circuit(&self, state: &CircuitBreakerState) -> bool {
        if state.request_history.len() < self.config.minimum_requests as usize {
            return false;
        }
        
        let recent_requests = self.get_recent_requests(&state);
        if recent_requests.len() < self.config.minimum_requests as usize {
            return false;
        }
        
        let failure_count = recent_requests.iter().filter(|r| !r.success).count();
        let error_rate = failure_count as f64 / recent_requests.len() as f64;
        
        error_rate >= self.config.failure_threshold
    }

    fn get_recent_requests(&self, state: &CircuitBreakerState) -> Vec<&RequestRecord> {
        let cutoff_time = Instant::now() - Duration::from_secs(60); // Last 60 seconds
        
        state.request_history
            .iter()
            .filter(|record| record.timestamp >= cutoff_time)
            .collect()
    }

    fn add_request_record(&self, state: &mut CircuitBreakerState, record: RequestRecord) {
        state.request_history.push_back(record);
        
        // Keep only recent records
        while state.request_history.len() > self.config.sliding_window_size as usize {
            state.request_history.pop_front();
        }
        
        // Also remove old records
        let cutoff_time = Instant::now() - Duration::from_secs(300); // Keep last 5 minutes
        while let Some(front) = state.request_history.front() {
            if front.timestamp >= cutoff_time {
                break;
            }
            state.request_history.pop_front();
        }
    }

    fn transition_to_closed(&self, state: &mut CircuitBreakerState) {
        state.state = CircuitState::Closed;
        state.failure_count = 0;
        state.success_count = 0;
        state.last_state_change = Instant::now();
        
        tracing::info!("Circuit breaker transitioned to CLOSED");
    }

    fn transition_to_open(&self, state: &mut CircuitBreakerState) {
        state.state = CircuitState::Open;
        state.success_count = 0;
        state.last_state_change = Instant::now();
        
        tracing::warn!("Circuit breaker transitioned to OPEN");
    }

    fn transition_to_half_open(&self, state: &mut CircuitBreakerState) {
        state.state = CircuitState::HalfOpen;
        state.success_count = 0;
        state.last_state_change = Instant::now();
        
        tracing::info!("Circuit breaker transitioned to HALF-OPEN");
    }

    fn increment_rejected_requests(&self) {
        let mut state = self.state.write().unwrap();
        state.rejected_requests += 1;
    }

    pub fn get_metrics(&self) -> CircuitBreakerMetrics {
        let state = self.state.read().unwrap();
        let recent_requests = self.get_recent_requests(&state);
        
        let error_rate = if recent_requests.len() > 0 {
            let failures = recent_requests.iter().filter(|r| !r.success).count();
            failures as f64 / recent_requests.len() as f64
        } else {
            0.0
        };
        
        let average_response_time = if recent_requests.len() > 0 {
            let total_duration: Duration = recent_requests.iter().map(|r| r.duration).sum();
            total_duration / recent_requests.len() as u32
        } else {
            Duration::from_secs(0)
        };
        
        CircuitBreakerMetrics {
            state: state.state.clone(),
            failure_count: state.failure_count,
            success_count: state.success_count,
            total_requests: state.total_requests,
            rejected_requests: state.rejected_requests,
            error_rate,
            average_response_time,
            last_failure_time: state.last_failure_time,
            state_duration: state.last_state_change.elapsed(),
        }
    }

    pub fn get_state(&self) -> CircuitState {
        self.state.read().unwrap().state.clone()
    }
}

impl<E: std::fmt::Display> std::fmt::Display for CircuitBreakerError<E> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CircuitBreakerError::CircuitOpen => write!(f, "Circuit breaker is open"),
            CircuitBreakerError::Timeout => write!(f, "Request timed out"),
            CircuitBreakerError::TooManyRequests => write!(f, "Too many concurrent requests"),
            CircuitBreakerError::ServiceError(e) => write!(f, "Service error: {}", e),
        }
    }
}

impl<E: std::error::Error> std::error::Error for CircuitBreakerError<E> {}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time::{sleep, Duration};

    #[tokio::test]
    async fn test_circuit_breaker_basic_functionality() {
        let config = CircuitBreakerConfig {
            failure_threshold: 0.5,
            minimum_requests: 3,
            timeout: Duration::from_secs(1),
            ..Default::default()
        };
        
        let circuit_breaker = CircuitBreaker::new(config);
        
        // Test successful requests
        for _ in 0..5 {
            let result = circuit_breaker.call(|| async { 
                Ok::<_, String>("success".to_string()) 
            }).await;
            assert!(result.is_ok());
        }
        
        assert_eq!(circuit_breaker.get_state(), CircuitState::Closed);
        
        // Test failing requests
        for _ in 0..3 {
            let result = circuit_breaker.call(|| async { 
                Err::<String, _>("failure".to_string()) 
            }).await;
            assert!(matches!(result, Err(CircuitBreakerError::ServiceError(_))));
        }
        
        // Circuit should now be open
        assert_eq!(circuit_breaker.get_state(), CircuitState::Open);
        
        // Test that requests are rejected
        let result = circuit_breaker.call(|| async { 
            Ok::<_, String>("success".to_string()) 
        }).await;
        assert!(matches!(result, Err(CircuitBreakerError::CircuitOpen)));
    }

    #[tokio::test]
    async fn test_circuit_breaker_recovery() {
        let config = CircuitBreakerConfig {
            failure_threshold: 0.5,
            minimum_requests: 2,
            timeout: Duration::from_millis(100),
            success_threshold: 2,
            ..Default::default()
        };
        
        let circuit_breaker = CircuitBreaker::new(config);
        
        // Force circuit to open
        for _ in 0..2 {
            let _ = circuit_breaker.call(|| async { 
                Err::<String, _>("failure".to_string()) 
            }).await;
        }
        
        assert_eq!(circuit_breaker.get_state(), CircuitState::Open);
        
        // Wait for timeout
        sleep(Duration::from_millis(150)).await;
        
        // First request should work (half-open)
        let result = circuit_breaker.call(|| async { 
            Ok::<_, String>("success".to_string()) 
        }).await;
        assert!(result.is_ok());
        
        // Second successful request should close the circuit
        let result = circuit_breaker.call(|| async { 
            Ok::<_, String>("success".to_string()) 
        }).await;
        assert!(result.is_ok());
        
        assert_eq!(circuit_breaker.get_state(), CircuitState::Closed);
    }

    #[tokio::test]
    async fn test_circuit_breaker_concurrency_limit() {
        let config = CircuitBreakerConfig {
            max_concurrent_requests: 2,
            ..Default::default()
        };
        
        let circuit_breaker = Arc::new(CircuitBreaker::new(config));
        
        // Start 3 concurrent requests
        let cb1 = circuit_breaker.clone();
        let cb2 = circuit_breaker.clone();
        let cb3 = circuit_breaker.clone();
        
        let handle1 = tokio::spawn(async move {
            cb1.call(|| async { 
                sleep(Duration::from_millis(100)).await;
                Ok::<_, String>("success".to_string()) 
            }).await
        });
        
        let handle2 = tokio::spawn(async move {
            cb2.call(|| async { 
                sleep(Duration::from_millis(100)).await;
                Ok::<_, String>("success".to_string()) 
            }).await
        });
        
        // Small delay to ensure first two requests acquire semaphore
        sleep(Duration::from_millis(10)).await;
        
        let handle3 = tokio::spawn(async move {
            cb3.call(|| async { 
                Ok::<_, String>("success".to_string()) 
            }).await
        });
        
        let results = tokio::join!(handle1, handle2, handle3);
        
        // First two should succeed
        assert!(results.0.unwrap().is_ok());
        assert!(results.1.unwrap().is_ok());
        
        // Third should fail with TooManyRequests
        let result3 = results.2.unwrap();
        assert!(matches!(result3, Err(CircuitBreakerError::TooManyRequests)));
    }
}
```

## Usage Examples

### HTTP Client with Circuit Breaker

```rust
use reqwest::Client;
use serde_json::Value;

struct HttpService {
    client: Client,
    circuit_breaker: CircuitBreaker,
}

impl HttpService {
    fn new() -> Self {
        let config = CircuitBreakerConfig {
            failure_threshold: 0.6,
            timeout: Duration::from_secs(30),
            request_timeout: Duration::from_secs(5),
            ..Default::default()
        };
        
        Self {
            client: Client::new(),
            circuit_breaker: CircuitBreaker::new(config),
        }
    }
    
    async fn get_user(&self, id: u64) -> Result<Value, Box<dyn std::error::Error>> {
        let url = format!("https://api.example.com/users/{}", id);
        
        match self.circuit_breaker.call(|| {
            let client = self.client.clone();
            let url = url.clone();
            
            async move {
                client.get(&url)
                    .send()
                    .await?
                    .json::<Value>()
                    .await
            }
        }).await {
            Ok(user) => Ok(user),
            Err(CircuitBreakerError::CircuitOpen) => {
                // Return cached or default response
                Ok(serde_json::json!({
                    "id": id,
                    "name": "Unknown User",
                    "cached": true
                }))
            }
            Err(e) => Err(Box::new(e)),
        }
    }
}
```

### Database Connection with Circuit Breaker

```rust
use sqlx::{Pool, Postgres};

struct DatabaseService {
    pool: Pool<Postgres>,
    circuit_breaker: CircuitBreaker,
}

impl DatabaseService {
    fn new(pool: Pool<Postgres>) -> Self {
        let config = CircuitBreakerConfig {
            failure_threshold: 0.4,
            timeout: Duration::from_secs(60),
            minimum_requests: 5,
            ..Default::default()
        };
        
        Self {
            pool,
            circuit_breaker: CircuitBreaker::new(config),
        }
    }
    
    async fn get_user(&self, id: i64) -> Result<Option<User>, sqlx::Error> {
        self.circuit_breaker.call(|| {
            let pool = self.pool.clone();
            
            async move {
                sqlx::query_as!(
                    User,
                    "SELECT id, name, email FROM users WHERE id = $1",
                    id
                )
                .fetch_optional(&pool)
                .await
            }
        }).await
        .map_err(|e| match e {
            CircuitBreakerError::ServiceError(sql_err) => sql_err,
            _ => sqlx::Error::PoolTimedOut,
        })
    }
}
```

### Metrics and Monitoring

```rust
use prometheus::{Counter, Gauge, Histogram, Registry};

struct CircuitBreakerMonitor {
    state_gauge: Gauge,
    requests_counter: Counter,
    rejections_counter: Counter,
    error_rate_gauge: Gauge,
    response_time_histogram: Histogram,
}

impl CircuitBreakerMonitor {
    fn new(registry: &Registry, service_name: &str) -> Self {
        let state_gauge = Gauge::new(
            format!("circuit_breaker_state_{}", service_name),
            "Current state of the circuit breaker"
        ).unwrap();
        
        let requests_counter = Counter::new(
            format!("circuit_breaker_requests_total_{}", service_name),
            "Total number of requests"
        ).unwrap();
        
        let rejections_counter = Counter::new(
            format!("circuit_breaker_rejections_total_{}", service_name),
            "Total number of rejected requests"
        ).unwrap();
        
        let error_rate_gauge = Gauge::new(
            format!("circuit_breaker_error_rate_{}", service_name),
            "Current error rate"
        ).unwrap();
        
        let response_time_histogram = Histogram::new(
            format!("circuit_breaker_response_time_{}", service_name),
            "Response time distribution"
        ).unwrap();
        
        registry.register(Box::new(state_gauge.clone())).unwrap();
        registry.register(Box::new(requests_counter.clone())).unwrap();
        registry.register(Box::new(rejections_counter.clone())).unwrap();
        registry.register(Box::new(error_rate_gauge.clone())).unwrap();
        registry.register(Box::new(response_time_histogram.clone())).unwrap();
        
        Self {
            state_gauge,
            requests_counter,
            rejections_counter,
            error_rate_gauge,
            response_time_histogram,
        }
    }
    
    fn update_metrics(&self, circuit_breaker: &CircuitBreaker) {
        let metrics = circuit_breaker.get_metrics();
        
        let state_value = match metrics.state {
            CircuitState::Closed => 0.0,
            CircuitState::Open => 1.0,
            CircuitState::HalfOpen => 0.5,
        };
        
        self.state_gauge.set(state_value);
        self.error_rate_gauge.set(metrics.error_rate);
        self.response_time_histogram.observe(metrics.average_response_time.as_secs_f64());
    }
}
```

This implementation provides:

1. **Thread-safe state management** with RwLock
2. **Configurable parameters** for different environments
3. **Comprehensive metrics** for monitoring
4. **Timeout handling** for requests
5. **Concurrency control** with semaphores
6. **Sliding window** for request tracking
7. **Proper error handling** with custom error types
8. **Extensive testing** with various scenarios

The circuit breaker is now ready for production use in high-throughput, distributed systems.