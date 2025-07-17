# Sampling Strategies: The Art of Intelligent Selection

## The Sampling Dilemma

Imagine you're a quality inspector at a factory producing 1 million widgets per day. You can't inspect every single widget - it would be too expensive and time-consuming. But you need to catch defects before they reach customers.

**The Solution**: Sampling. Inspect a representative subset that gives you confidence about the whole batch.

Distributed tracing faces the same challenge. You can't trace every request in a high-volume system, but you need enough traces to understand system behavior.

## The Cost of 100% Sampling

### The Numbers

A typical microservice architecture might see:
- **10,000 requests per second**
- **50 spans per trace on average**
- **500,000 spans per second**

At 100% sampling, you're generating massive amounts of data:
- **Storage**: 10GB+ per day just for trace data
- **Network**: Constant stream of trace exports
- **CPU**: Overhead from span creation and serialization
- **Memory**: Buffers for trace data

### The Performance Impact

Every traced operation adds overhead:

```rust
// Without tracing
fn process_order(order: Order) -> Result<(), Error> {
    // Just business logic
    validate_order(&order)?;
    save_order(&order)?;
    Ok(())
}

// With tracing (simplified view)
fn process_order(order: Order) -> Result<(), Error> {
    let span = start_span("process_order");
    span.set_tag("order_id", &order.id);
    
    let validate_span = start_span("validate_order");
    validate_order(&order)?;
    validate_span.finish();
    
    let save_span = start_span("save_order");
    save_order(&order)?;
    save_span.finish();
    
    span.finish();
    Ok(())
}
```

Each span creation, tag assignment, and finish call adds microseconds. At scale, this matters.

## Sampling Strategies

### 1. Head-Based Sampling

**The Concept**: Decide whether to trace a request at the very beginning, before any processing happens.

**The Analogy**: Like a bouncer at a club who decides whether to let someone in based on their appearance at the door.

#### Fixed Rate Sampling

```rust
use rand::random;

struct FixedRateSampler {
    rate: f64, // 0.0 to 1.0
}

impl FixedRateSampler {
    fn should_sample(&self) -> bool {
        random::<f64>() < self.rate
    }
}

// Sample 10% of requests
let sampler = FixedRateSampler { rate: 0.1 };
if sampler.should_sample() {
    // Create trace
}
```

**Pros**:
- Simple to implement
- Predictable overhead
- Works across service boundaries

**Cons**:
- Might miss important requests
- No intelligence about request importance
- Fixed overhead regardless of system load

#### Adaptive Sampling

```rust
struct AdaptiveSampler {
    target_rate: f64,
    current_rate: f64,
    requests_seen: u64,
    last_adjustment: Instant,
}

impl AdaptiveSampler {
    fn should_sample(&mut self) -> bool {
        self.requests_seen += 1;
        
        // Adjust sampling rate based on load
        if self.last_adjustment.elapsed() > Duration::from_secs(60) {
            self.adjust_rate();
            self.last_adjustment = Instant::now();
        }
        
        random::<f64>() < self.current_rate
    }
    
    fn adjust_rate(&mut self) {
        let load_factor = self.calculate_load_factor();
        if load_factor > 0.8 {
            // High load, reduce sampling
            self.current_rate *= 0.8;
        } else if load_factor < 0.3 {
            // Low load, increase sampling
            self.current_rate *= 1.2;
        }
        
        // Keep within bounds
        self.current_rate = self.current_rate.min(1.0).max(0.001);
    }
}
```

**Pros**:
- Adapts to system load
- Maintains consistent overhead
- Better resource utilization

**Cons**:
- More complex to implement
- Still might miss important requests
- Requires load monitoring

### 2. Tail-Based Sampling

**The Concept**: Collect all spans for a trace, then decide whether to keep or discard the entire trace based on its characteristics.

**The Analogy**: Like a movie editor who watches the entire film before deciding which scenes to keep in the final cut.

#### Error-Based Sampling

```rust
struct TailSampler {
    buffer: HashMap<String, Vec<Span>>,
    buffer_timeout: Duration,
}

impl TailSampler {
    fn process_span(&mut self, span: Span) {
        let trace_id = span.trace_id.clone();
        
        // Buffer all spans for this trace
        self.buffer.entry(trace_id).or_insert_with(Vec::new).push(span);
        
        // Check if trace is complete and ready for sampling decision
        if self.is_trace_complete(&trace_id) {
            self.make_sampling_decision(&trace_id);
        }
    }
    
    fn make_sampling_decision(&mut self, trace_id: &str) {
        let spans = self.buffer.remove(trace_id).unwrap();
        
        // Sample if any span has an error
        let has_error = spans.iter().any(|span| span.has_error());
        
        // Sample if trace is unusually slow
        let total_duration = spans.iter().map(|s| s.duration()).sum::<Duration>();
        let is_slow = total_duration > Duration::from_secs(5);
        
        // Sample if it's a critical operation
        let is_critical = spans.iter().any(|span| {
            span.operation_name().contains("payment") || 
            span.operation_name().contains("order")
        });
        
        if has_error || is_slow || is_critical {
            // Keep this trace
            self.export_trace(spans);
        } else {
            // Apply probabilistic sampling for normal traces
            if random::<f64>() < 0.01 {
                self.export_trace(spans);
            }
        }
    }
}
```

**Pros**:
- Intelligent sampling based on trace characteristics
- Ensures important traces are always kept
- Can sample based on business logic

**Cons**:
- Requires buffering all spans
- Higher memory usage
- More complex implementation
- Potential for memory leaks

### 3. Hybrid Sampling

**The Concept**: Combine head-based and tail-based sampling for optimal results.

```rust
struct HybridSampler {
    head_sampler: FixedRateSampler,
    tail_sampler: TailSampler,
}

impl HybridSampler {
    fn start_trace(&self, trace_id: &str) -> SamplingDecision {
        // Always sample certain traces at the head
        if self.is_critical_trace(trace_id) {
            return SamplingDecision::Sample;
        }
        
        // Use head-based sampling for fast decision
        if self.head_sampler.should_sample() {
            return SamplingDecision::Sample;
        }
        
        // Buffer for tail-based sampling
        SamplingDecision::Buffer
    }
    
    fn is_critical_trace(&self, trace_id: &str) -> bool {
        // Sample VIP users or critical operations
        trace_id.contains("vip_user") || 
        trace_id.contains("payment_flow")
    }
}
```

## Advanced Sampling Techniques

### 1. Priority-Based Sampling

```rust
#[derive(PartialEq, Eq, PartialOrd, Ord)]
enum TracePriority {
    Low,
    Normal,
    High,
    Critical,
}

struct PrioritySampler {
    sampling_rates: HashMap<TracePriority, f64>,
}

impl PrioritySampler {
    fn should_sample(&self, priority: TracePriority) -> bool {
        let rate = self.sampling_rates.get(&priority).unwrap_or(&0.1);
        random::<f64>() < *rate
    }
}

// Configuration
let mut sampler = PrioritySampler {
    sampling_rates: HashMap::new(),
};
sampler.sampling_rates.insert(TracePriority::Critical, 1.0);  // 100%
sampler.sampling_rates.insert(TracePriority::High, 0.5);     // 50%
sampler.sampling_rates.insert(TracePriority::Normal, 0.1);   // 10%
sampler.sampling_rates.insert(TracePriority::Low, 0.01);     // 1%
```

### 2. User-Based Sampling

```rust
struct UserBasedSampler {
    vip_users: HashSet<String>,
    debug_users: HashSet<String>,
    default_rate: f64,
}

impl UserBasedSampler {
    fn should_sample(&self, user_id: &str) -> bool {
        if self.vip_users.contains(user_id) {
            return true; // Always sample VIP users
        }
        
        if self.debug_users.contains(user_id) {
            return true; // Always sample users we're debugging
        }
        
        // Use default sampling for everyone else
        random::<f64>() < self.default_rate
    }
}
```

### 3. Service-Based Sampling

```rust
struct ServiceBasedSampler {
    service_rates: HashMap<String, f64>,
    default_rate: f64,
}

impl ServiceBasedSampler {
    fn should_sample(&self, service_name: &str) -> bool {
        let rate = self.service_rates.get(service_name).unwrap_or(&self.default_rate);
        random::<f64>() < *rate
    }
}

// Configuration
let mut sampler = ServiceBasedSampler {
    service_rates: HashMap::new(),
    default_rate: 0.1,
};
sampler.service_rates.insert("payment-service".to_string(), 0.5);
sampler.service_rates.insert("user-service".to_string(), 0.2);
sampler.service_rates.insert("logging-service".to_string(), 0.01);
```

## Production Sampling Strategies

### Netflix's Approach

Netflix uses a sophisticated sampling strategy:

1. **100% sampling** for errors and slow requests
2. **1% sampling** for normal requests
3. **Adaptive sampling** based on service load
4. **Special sampling** for A/B tests and feature flags

### Uber's Strategy

Uber's sampling is based on:

1. **Geographic regions** (higher sampling in new markets)
2. **Service criticality** (payment services get higher sampling)
3. **Time of day** (higher sampling during peak hours)
4. **User segments** (higher sampling for enterprise customers)

### Google's Approach

Google uses:

1. **Importance sampling** based on request characteristics
2. **Budget-based sampling** to control costs
3. **Stratified sampling** to ensure representative samples
4. **Reservoir sampling** for bounded memory usage

## Implementation Patterns

### Configuration-Driven Sampling

```rust
#[derive(Deserialize)]
struct SamplingConfig {
    default_rate: f64,
    service_rates: HashMap<String, f64>,
    error_rate: f64,
    slow_request_threshold_ms: u64,
    vip_users: Vec<String>,
}

impl SamplingConfig {
    fn should_sample(&self, context: &SamplingContext) -> bool {
        // Always sample errors
        if context.has_error {
            return random::<f64>() < self.error_rate;
        }
        
        // Always sample slow requests
        if context.duration_ms > self.slow_request_threshold_ms {
            return true;
        }
        
        // VIP user sampling
        if self.vip_users.contains(&context.user_id) {
            return true;
        }
        
        // Service-specific sampling
        let rate = self.service_rates.get(&context.service_name)
            .unwrap_or(&self.default_rate);
        
        random::<f64>() < *rate
    }
}
```

### Dynamic Sampling

```rust
struct DynamicSampler {
    config: Arc<RwLock<SamplingConfig>>,
    metrics: Arc<Metrics>,
}

impl DynamicSampler {
    fn should_sample(&self, context: &SamplingContext) -> bool {
        let config = self.config.read().unwrap();
        
        // Get current system load
        let cpu_usage = self.metrics.cpu_usage();
        let memory_usage = self.metrics.memory_usage();
        
        // Adjust sampling rate based on system load
        let mut adjusted_rate = config.default_rate;
        
        if cpu_usage > 0.8 || memory_usage > 0.8 {
            adjusted_rate *= 0.5; // Reduce sampling under high load
        }
        
        random::<f64>() < adjusted_rate
    }
    
    fn update_config(&self, new_config: SamplingConfig) {
        let mut config = self.config.write().unwrap();
        *config = new_config;
    }
}
```

## Monitoring Your Sampling

### Key Metrics to Track

```rust
struct SamplingMetrics {
    total_requests: Counter,
    sampled_requests: Counter,
    dropped_requests: Counter,
    sampling_rate: Gauge,
    buffer_size: Gauge,
}

impl SamplingMetrics {
    fn record_sampling_decision(&self, decision: SamplingDecision) {
        self.total_requests.inc();
        
        match decision {
            SamplingDecision::Sample => {
                self.sampled_requests.inc();
            }
            SamplingDecision::Drop => {
                self.dropped_requests.inc();
            }
        }
        
        let rate = self.sampled_requests.get() as f64 / self.total_requests.get() as f64;
        self.sampling_rate.set(rate);
    }
}
```

### Alerting on Sampling Issues

```rust
struct SamplingAlerter {
    metrics: SamplingMetrics,
    thresholds: SamplingThresholds,
}

impl SamplingAlerter {
    fn check_sampling_health(&self) {
        let sampling_rate = self.metrics.sampling_rate.get();
        
        if sampling_rate < self.thresholds.min_sampling_rate {
            self.alert("Sampling rate too low - might miss important traces");
        }
        
        if sampling_rate > self.thresholds.max_sampling_rate {
            self.alert("Sampling rate too high - might overload tracing system");
        }
        
        let buffer_size = self.metrics.buffer_size.get();
        if buffer_size > self.thresholds.max_buffer_size {
            self.alert("Tail sampling buffer too large - might cause memory issues");
        }
    }
}
```

## Best Practices

### 1. Start Simple

Begin with fixed-rate head sampling:
```rust
// Start with 1% sampling
let sampler = FixedRateSampler { rate: 0.01 };
```

### 2. Always Sample Errors

```rust
fn should_sample(context: &SamplingContext) -> bool {
    if context.has_error {
        return true;
    }
    
    // Regular sampling logic
    random::<f64>() < 0.01
}
```

### 3. Sample Important Business Operations

```rust
fn should_sample(context: &SamplingContext) -> bool {
    if context.operation_name.contains("payment") ||
       context.operation_name.contains("checkout") ||
       context.operation_name.contains("signup") {
        return true;
    }
    
    // Regular sampling logic
    random::<f64>() < 0.01
}
```

### 4. Monitor and Adjust

```rust
// Regular sampling rate analysis
fn analyze_sampling_effectiveness() {
    let error_coverage = calculate_error_coverage();
    let performance_coverage = calculate_performance_coverage();
    
    if error_coverage < 0.95 {
        increase_error_sampling_rate();
    }
    
    if performance_coverage < 0.80 {
        increase_performance_sampling_rate();
    }
}
```

## Common Pitfalls

### 1. The "Missing Critical Trace" Problem

**Problem**: Fixed sampling might miss the one trace that explains a critical issue.

**Solution**: Always sample errors and slow requests.

### 2. The "Sampling Bias" Problem

**Problem**: Sampling might create biased views of system performance.

**Solution**: Use stratified sampling to ensure representative samples.

### 3. The "Memory Leak" Problem

**Problem**: Tail sampling buffers can grow unbounded.

**Solution**: Implement buffer limits and timeout mechanisms.

### 4. The "Clock Skew" Problem

**Problem**: Distributed systems have clock differences that affect sampling decisions.

**Solution**: Use logical clocks or accept small inconsistencies.

## The Future of Sampling

### Machine Learning-Based Sampling

```rust
struct MLSampler {
    model: TrainedModel,
    features: FeatureExtractor,
}

impl MLSampler {
    fn should_sample(&self, context: &SamplingContext) -> bool {
        let features = self.features.extract(context);
        let prediction = self.model.predict(&features);
        
        // Model predicts probability of this trace being interesting
        prediction > 0.7
    }
}
```

### Continuous Learning

```rust
struct AdaptiveSampler {
    model: OnlineModel,
    feedback_loop: FeedbackLoop,
}

impl AdaptiveSampler {
    fn learn_from_trace(&mut self, trace: &Trace, was_useful: bool) {
        let features = extract_features(trace);
        self.model.update(&features, was_useful);
    }
}
```

---

*Sampling is the art of seeing the forest through the trees. The goal isn't to trace everything, but to trace the right things at the right time.*