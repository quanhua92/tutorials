# Getting Started: Building Your First Circuit Breaker

## The Scenario: A Flaky HTTP Service

Let's build a circuit breaker for a common real-world scenario: calling an HTTP API that sometimes fails. We'll create a wrapper that protects our application from cascading failures.

## Basic Implementation Structure

Here's the skeleton of our circuit breaker:

```rust
use std::time::{Duration, Instant};
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone, PartialEq)]
pub enum CircuitState {
    Closed,
    Open,
    HalfOpen,
}

pub struct CircuitBreaker<T> {
    state: Arc<Mutex<CircuitState>>,
    failure_count: Arc<Mutex<u32>>,
    success_count: Arc<Mutex<u32>>,
    last_failure_time: Arc<Mutex<Option<Instant>>>,
    failure_threshold: u32,
    timeout: Duration,
    service: T,
}
```

## Step 1: Initialize the Circuit Breaker

```rust
impl<T> CircuitBreaker<T> {
    pub fn new(service: T, failure_threshold: u32, timeout: Duration) -> Self {
        Self {
            state: Arc::new(Mutex::new(CircuitState::Closed)),
            failure_count: Arc::new(Mutex::new(0)),
            success_count: Arc::new(Mutex::new(0)),
            last_failure_time: Arc::new(Mutex::new(None)),
            failure_threshold,
            timeout,
            service,
        }
    }
}
```

## Step 2: Implement the Core Logic

```rust
impl<T> CircuitBreaker<T> {
    pub fn call<F, R, E>(&self, operation: F) -> Result<R, CircuitBreakerError<E>>
    where
        F: FnOnce(&T) -> Result<R, E>,
    {
        // Check if we should allow the request
        match self.should_allow_request() {
            false => return Err(CircuitBreakerError::CircuitOpen),
            true => {}
        }

        // Execute the operation
        match operation(&self.service) {
            Ok(result) => {
                self.on_success();
                Ok(result)
            }
            Err(error) => {
                self.on_failure();
                Err(CircuitBreakerError::ServiceError(error))
            }
        }
    }

    fn should_allow_request(&self) -> bool {
        let state = self.state.lock().unwrap();
        match *state {
            CircuitState::Closed => true,
            CircuitState::Open => self.should_attempt_reset(),
            CircuitState::HalfOpen => true,
        }
    }

    fn should_attempt_reset(&self) -> bool {
        if let Some(last_failure) = *self.last_failure_time.lock().unwrap() {
            last_failure.elapsed() >= self.timeout
        } else {
            false
        }
    }
}
```

## Step 3: Handle Success and Failure

```rust
impl<T> CircuitBreaker<T> {
    fn on_success(&self) {
        let mut state = self.state.lock().unwrap();
        let mut success_count = self.success_count.lock().unwrap();
        let mut failure_count = self.failure_count.lock().unwrap();

        *success_count += 1;
        *failure_count = 0; // Reset failure count on success

        match *state {
            CircuitState::HalfOpen => {
                // Successful request in half-open state closes the circuit
                *state = CircuitState::Closed;
                println!("Circuit breaker: Closed (service recovered)");
            }
            _ => {}
        }
    }

    fn on_failure(&self) {
        let mut state = self.state.lock().unwrap();
        let mut failure_count = self.failure_count.lock().unwrap();
        let mut last_failure_time = self.last_failure_time.lock().unwrap();

        *failure_count += 1;
        *last_failure_time = Some(Instant::now());

        match *state {
            CircuitState::Closed => {
                if *failure_count >= self.failure_threshold {
                    *state = CircuitState::Open;
                    println!("Circuit breaker: Opened (failure threshold exceeded)");
                }
            }
            CircuitState::HalfOpen => {
                // Failure in half-open state opens the circuit again
                *state = CircuitState::Open;
                println!("Circuit breaker: Re-opened (half-open test failed)");
            }
            _ => {}
        }
    }
}
```

## Step 4: Define Error Types

```rust
#[derive(Debug)]
pub enum CircuitBreakerError<E> {
    CircuitOpen,
    ServiceError(E),
}

impl<E: std::fmt::Display> std::fmt::Display for CircuitBreakerError<E> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            CircuitBreakerError::CircuitOpen => write!(f, "Circuit breaker is open"),
            CircuitBreakerError::ServiceError(e) => write!(f, "Service error: {}", e),
        }
    }
}
```

## Step 5: Create an HTTP Service Example

```rust
use std::thread;
use std::time::Duration;

struct HttpService {
    base_url: String,
    failure_rate: f64, // Simulate failure rate for demo
}

impl HttpService {
    fn new(base_url: String, failure_rate: f64) -> Self {
        Self {
            base_url,
            failure_rate,
        }
    }

    fn get_user(&self, id: u64) -> Result<String, String> {
        // Simulate network delay
        thread::sleep(Duration::from_millis(100));

        // Simulate random failures
        if rand::random::<f64>() < self.failure_rate {
            return Err(format!("HTTP 500: Internal Server Error"));
        }

        Ok(format!("{{\"id\": {}, \"name\": \"User {}\"}}", id, id))
    }
}
```

## Step 6: Put It All Together

```rust
fn main() {
    // Create a flaky HTTP service (50% failure rate)
    let http_service = HttpService::new("https://api.example.com".to_string(), 0.5);
    
    // Wrap it with a circuit breaker
    let circuit_breaker = CircuitBreaker::new(
        http_service,
        3, // Open after 3 failures
        Duration::from_secs(5), // Stay open for 5 seconds
    );

    // Simulate multiple requests
    for i in 1..=20 {
        println!("\n--- Request {} ---", i);
        
        match circuit_breaker.call(|service| service.get_user(i)) {
            Ok(user) => println!("Success: {}", user),
            Err(CircuitBreakerError::CircuitOpen) => {
                println!("Circuit breaker is open - using fallback");
                println!("Fallback: {{\"id\": {}, \"name\": \"Cached User {}\"}}", i, i);
            }
            Err(CircuitBreakerError::ServiceError(e)) => {
                println!("Service error: {}", e);
            }
        }

        // Check current state
        let state = circuit_breaker.state.lock().unwrap();
        let failures = circuit_breaker.failure_count.lock().unwrap();
        println!("State: {:?}, Failures: {}", *state, *failures);

        // Wait between requests
        thread::sleep(Duration::from_millis(500));
    }
}
```

## Expected Output

```
--- Request 1 ---
Success: {"id": 1, "name": "User 1"}
State: Closed, Failures: 0

--- Request 2 ---
Service error: HTTP 500: Internal Server Error
State: Closed, Failures: 1

--- Request 3 ---
Service error: HTTP 500: Internal Server Error
State: Closed, Failures: 2

--- Request 4 ---
Service error: HTTP 500: Internal Server Error
Circuit breaker: Opened (failure threshold exceeded)
State: Open, Failures: 3

--- Request 5 ---
Circuit breaker is open - using fallback
Fallback: {"id": 5, "name": "Cached User 5"}
State: Open, Failures: 3

--- Request 6 ---
Circuit breaker is open - using fallback
Fallback: {"id": 6, "name": "Cached User 6"}
State: Open, Failures: 3

[After 5 seconds...]

--- Request 11 ---
Success: {"id": 11, "name": "User 11"}
Circuit breaker: Closed (service recovered)
State: Closed, Failures: 0
```

## Key Observations

1. **Failure Accumulation**: The circuit tracks failures and opens after hitting the threshold
2. **Immediate Rejection**: Once open, requests are rejected immediately without calling the service
3. **Automatic Recovery**: After the timeout, the circuit tests the service and closes if it succeeds
4. **Graceful Degradation**: Your application continues working with fallback responses

## Adding Monitoring

```rust
impl<T> CircuitBreaker<T> {
    pub fn get_metrics(&self) -> CircuitBreakerMetrics {
        let state = self.state.lock().unwrap();
        let failures = self.failure_count.lock().unwrap();
        let successes = self.success_count.lock().unwrap();
        
        CircuitBreakerMetrics {
            state: state.clone(),
            failure_count: *failures,
            success_count: *successes,
            total_requests: *failures + *successes,
            error_rate: if *failures + *successes > 0 {
                *failures as f64 / (*failures + *successes) as f64
            } else {
                0.0
            },
        }
    }
}

#[derive(Debug)]
pub struct CircuitBreakerMetrics {
    pub state: CircuitState,
    pub failure_count: u32,
    pub success_count: u32,
    pub total_requests: u32,
    pub error_rate: f64,
}
```

This basic implementation demonstrates the core concepts of circuit breakers. In production, you'd want to add features like:
- Configurable time windows
- More sophisticated failure detection
- Metrics collection
- Thread-safe state management
- Better error handling

But this foundation gives you the essential behavior: fail fast, recover gracefully, and protect your system from cascading failures.