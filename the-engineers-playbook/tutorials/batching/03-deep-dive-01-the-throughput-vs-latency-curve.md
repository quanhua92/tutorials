# The Throughput vs. Latency Curve: Understanding the Fundamental Trade-off

## Introduction: The Heart of Batching

The throughput-latency curve is the most important concept in batching systems. It represents the fundamental trade-off that defines how batching works: as you increase batch size or batching window, throughput improves but latency increases. Understanding this curve is crucial for designing efficient systems and making informed trade-offs.

This deep dive explores the mathematical foundations, practical implications, and optimization strategies for navigating this critical relationship.

## The Mathematical Foundation

### Basic Relationships

The throughput-latency relationship follows predictable mathematical patterns:

```
Throughput = Work_Completed / Time_Taken
          = Batch_Size / (Fixed_Cost + Batch_Size × Variable_Cost)

Latency = Wait_Time + Processing_Time
        = Batching_Window + (Fixed_Cost + Batch_Size × Variable_Cost)

Efficiency = Throughput × (1 - Latency_Penalty)
```

### The Curve Equation

The throughput curve as a function of batch size follows a rectangular hyperbola:

```
T(n) = n / (F + n × V)

Where:
- T(n) = Throughput with batch size n
- F = Fixed cost per batch
- V = Variable cost per item
- n = Batch size

As n → ∞, T(n) → 1/V (theoretical maximum)
```

### The Latency Function

Latency grows more complex due to queuing effects:

```
L(n) = W + P(n)
     = W + (F + n × V)

Where:
- L(n) = Total latency with batch size n
- W = Average waiting time in queue
- P(n) = Processing time for batch of size n
- F = Fixed processing cost
- V = Variable cost per item
```

## Visualizing the Curve

### The Classic Shape

The throughput-latency curve has a characteristic shape:

```
Throughput
    ^
    |     •••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••• (asymptotic maximum)
    |   •••
    |  ••
    | ••
    |••
    |
    +–––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––> Latency

Three regions:
1. Steep rise (small batches): Large gains for small latency increases
2. Diminishing returns (medium batches): Moderate gains for moderate latency increases  
3. Asymptotic (large batches): Minimal gains for large latency increases
```

### Real-World Example: Database Inserts

Let's model a real database insert scenario:

```python
import numpy as np
import matplotlib.pyplot as plt
from typing import Tuple, List

class ThroughputLatencyModel:
    """Model throughput-latency trade-offs for batching systems."""
    
    def __init__(self, fixed_cost: float, variable_cost: float, 
                 base_latency: float = 0.0):
        self.fixed_cost = fixed_cost        # Fixed cost per batch (ms)
        self.variable_cost = variable_cost  # Variable cost per item (ms)
        self.base_latency = base_latency    # Base latency (queuing, etc.)
    
    def throughput(self, batch_size: int) -> float:
        """Calculate throughput (items/second) for given batch size."""
        processing_time = self.fixed_cost + batch_size * self.variable_cost
        return (batch_size / processing_time) * 1000  # Convert ms to seconds
    
    def latency(self, batch_size: int, wait_time: float = 0.0) -> float:
        """Calculate latency (ms) for given batch size."""
        processing_time = self.fixed_cost + batch_size * self.variable_cost
        return self.base_latency + wait_time + processing_time
    
    def efficiency(self, batch_size: int, latency_penalty_factor: float = 0.001) -> float:
        """Calculate efficiency considering latency penalty."""
        tput = self.throughput(batch_size)
        lat = self.latency(batch_size)
        penalty = 1 - (lat * latency_penalty_factor)
        return tput * max(0, penalty)
    
    def generate_curve(self, max_batch_size: int = 1000) -> Tuple[List[int], List[float], List[float]]:
        """Generate throughput-latency curve data."""
        batch_sizes = list(range(1, max_batch_size + 1))
        throughputs = [self.throughput(size) for size in batch_sizes]
        latencies = [self.latency(size) for size in batch_sizes]
        
        return batch_sizes, throughputs, latencies

# Example: Database insert operations
db_model = ThroughputLatencyModel(
    fixed_cost=10.0,      # 10ms connection + transaction setup
    variable_cost=0.1,    # 0.1ms per record insert
    base_latency=2.0      # 2ms base latency
)

# Generate data
batch_sizes, throughputs, latencies = db_model.generate_curve(1000)

# Find key points
max_throughput_idx = np.argmax(throughputs)
efficient_point = np.argmax([db_model.efficiency(size) for size in batch_sizes])

print(f"Database Insert Analysis:")
print(f"Maximum throughput: {throughputs[max_throughput_idx]:.1f} items/sec at batch size {batch_sizes[max_throughput_idx]}")
print(f"Most efficient point: batch size {batch_sizes[efficient_point]} (efficiency: {db_model.efficiency(batch_sizes[efficient_point]):.1f})")
print(f"Latency at efficient point: {latencies[efficient_point]:.1f}ms")
```

## The Three Regions of the Curve

### Region 1: The Steep Climb (Small Batches)

**Characteristics:**
- Batch sizes: 1-50 items
- Throughput gains: 50-500% per doubling
- Latency increases: Minimal
- Efficiency: Rapidly improving

**Mathematical behavior:**
```
For small n where n << F/V:
T(n) ≈ n/F (approximately linear)
Slope = 1/F (very steep)

Example with F=10ms, V=0.1ms:
- Batch size 1: 100 items/sec
- Batch size 10: 909 items/sec (9x improvement)
- Batch size 50: 4,545 items/sec (45x improvement)
```

**Strategy:** Aggressive batching is highly beneficial in this region.

### Region 2: Diminishing Returns (Medium Batches)

**Characteristics:**
- Batch sizes: 50-500 items
- Throughput gains: 10-100% per doubling
- Latency increases: Moderate
- Efficiency: Slowly improving

**Mathematical behavior:**
```
For medium n where n ≈ F/V:
T(n) ≈ n/(F + nV) (hyperbolic)
Slope decreasing as 1/(F + nV)²

Example with F=10ms, V=0.1ms:
- Batch size 50: 4,545 items/sec
- Batch size 100: 6,667 items/sec (47% improvement)
- Batch size 500: 9,091 items/sec (100% improvement from 50)
```

**Strategy:** Careful optimization needed, considering latency requirements.

### Region 3: Asymptotic Approach (Large Batches)

**Characteristics:**
- Batch sizes: 500+ items
- Throughput gains: 1-10% per doubling
- Latency increases: Significant
- Efficiency: May be decreasing

**Mathematical behavior:**
```
For large n where n >> F/V:
T(n) ≈ 1/V (approaching asymptote)
Slope ≈ F/(F + nV)² (very small)

Example with F=10ms, V=0.1ms:
- Batch size 500: 9,091 items/sec
- Batch size 1000: 9,524 items/sec (5% improvement)
- Batch size 5000: 9,901 items/sec (9% improvement from 500)
```

**Strategy:** Avoid unless latency is not a concern.

## Factors That Shape the Curve

### Fixed Cost Impact

Higher fixed costs create steeper curves:

```python
def compare_fixed_costs():
    """Compare curves with different fixed costs."""
    
    models = [
        ThroughputLatencyModel(fixed_cost=1.0, variable_cost=0.1),   # Low fixed cost
        ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.1),  # Medium fixed cost
        ThroughputLatencyModel(fixed_cost=100.0, variable_cost=0.1)  # High fixed cost
    ]
    
    batch_sizes = list(range(1, 201))
    
    for i, model in enumerate(models):
        throughputs = [model.throughput(size) for size in batch_sizes]
        print(f"Fixed cost {model.fixed_cost}ms:")
        print(f"  Batch 1: {throughputs[0]:.1f} items/sec")
        print(f"  Batch 10: {throughputs[9]:.1f} items/sec")
        print(f"  Batch 100: {throughputs[99]:.1f} items/sec")
        print(f"  Improvement factor (1→100): {throughputs[99]/throughputs[0]:.1f}x")
        print()

compare_fixed_costs()
```

**Key insight:** Higher fixed costs make batching more beneficial.

### Variable Cost Impact

Higher variable costs flatten the curve:

```python
def compare_variable_costs():
    """Compare curves with different variable costs."""
    
    models = [
        ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.01),  # Low variable cost
        ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.1),   # Medium variable cost
        ThroughputLatencyModel(fixed_cost=10.0, variable_cost=1.0)    # High variable cost
    ]
    
    batch_sizes = [1, 10, 100, 1000]
    
    for model in models:
        throughputs = [model.throughput(size) for size in batch_sizes]
        print(f"Variable cost {model.variable_cost}ms:")
        for size, tput in zip(batch_sizes, throughputs):
            print(f"  Batch {size}: {tput:.1f} items/sec")
        print(f"  Max theoretical: {1000/model.variable_cost:.1f} items/sec")
        print()

compare_variable_costs()
```

**Key insight:** Lower variable costs make batching more beneficial and allow larger optimal batch sizes.

## Latency Components

### Queuing Latency

The time spent waiting for a batch to form:

```python
def calculate_queuing_latency(arrival_rate: float, batch_size: int, 
                            batch_timeout: float) -> float:
    """Calculate average queuing latency."""
    
    # Time to fill a batch
    fill_time = batch_size / arrival_rate
    
    # Average wait time depends on arrival pattern
    if fill_time < batch_timeout:
        # Batch fills before timeout
        avg_wait = fill_time / 2  # Average position in batch
    else:
        # Timeout triggers batch processing
        avg_wait = batch_timeout / 2
    
    return avg_wait

# Example: Different arrival rates
arrival_rates = [10, 50, 100, 500, 1000]  # items/second
batch_size = 100
batch_timeout = 0.1  # 100ms

print("Queuing Latency Analysis:")
print(f"Batch size: {batch_size}, Timeout: {batch_timeout*1000}ms")
print("Arrival Rate\tFill Time\tAvg Wait")
print("-" * 40)

for rate in arrival_rates:
    fill_time = batch_size / rate
    avg_wait = calculate_queuing_latency(rate, batch_size, batch_timeout)
    print(f"{rate:>8}/s\t{fill_time*1000:>6.1f}ms\t{avg_wait*1000:>6.1f}ms")
```

### Processing Latency

The time to process the batch once formed:

```python
def calculate_processing_latency(batch_size: int, fixed_cost: float, 
                               variable_cost: float) -> float:
    """Calculate processing latency for a batch."""
    return fixed_cost + batch_size * variable_cost

# Example: Processing latency vs batch size
batch_sizes = [1, 10, 50, 100, 500, 1000]
fixed_cost = 10.0  # 10ms
variable_cost = 0.1  # 0.1ms per item

print("\nProcessing Latency Analysis:")
print("Batch Size\tProcessing Time")
print("-" * 30)

for size in batch_sizes:
    processing_time = calculate_processing_latency(size, fixed_cost, variable_cost)
    print(f"{size:>6}\t{processing_time:>8.1f}ms")
```

## Optimization Strategies

### Finding the Sweet Spot

The optimal batch size depends on your specific requirements:

```python
class BatchOptimizer:
    """Find optimal batch parameters for given constraints."""
    
    def __init__(self, model: ThroughputLatencyModel):
        self.model = model
    
    def find_optimal_batch_size(self, max_latency: float = None, 
                              min_throughput: float = None,
                              optimize_for: str = "efficiency") -> int:
        """Find optimal batch size given constraints."""
        
        best_size = 1
        best_score = 0
        
        for batch_size in range(1, 1001):
            # Check constraints
            if max_latency and self.model.latency(batch_size) > max_latency:
                continue
            
            if min_throughput and self.model.throughput(batch_size) < min_throughput:
                continue
            
            # Calculate score based on optimization goal
            if optimize_for == "throughput":
                score = self.model.throughput(batch_size)
            elif optimize_for == "latency":
                score = -self.model.latency(batch_size)  # Negative because we want minimum
            else:  # efficiency
                score = self.model.efficiency(batch_size)
            
            if score > best_score:
                best_score = score
                best_size = batch_size
        
        return best_size
    
    def analyze_trade_offs(self, batch_sizes: List[int]) -> None:
        """Analyze trade-offs for different batch sizes."""
        
        print("Trade-off Analysis:")
        print("Batch Size\tThroughput\tLatency\tEfficiency")
        print("-" * 50)
        
        for size in batch_sizes:
            throughput = self.model.throughput(size)
            latency = self.model.latency(size)
            efficiency = self.model.efficiency(size)
            
            print(f"{size:>6}\t{throughput:>8.1f}\t{latency:>6.1f}ms\t{efficiency:>8.1f}")

# Example optimization
optimizer = BatchOptimizer(db_model)

# Find optimal for different scenarios
print("Optimization Examples:")
print("\n1. Latency-constrained (max 50ms):")
optimal_latency = optimizer.find_optimal_batch_size(max_latency=50.0, optimize_for="throughput")
print(f"   Optimal batch size: {optimal_latency}")
print(f"   Throughput: {db_model.throughput(optimal_latency):.1f} items/sec")
print(f"   Latency: {db_model.latency(optimal_latency):.1f}ms")

print("\n2. Throughput-constrained (min 5000 items/sec):")
optimal_throughput = optimizer.find_optimal_batch_size(min_throughput=5000.0, optimize_for="latency")
print(f"   Optimal batch size: {optimal_throughput}")
print(f"   Throughput: {db_model.throughput(optimal_throughput):.1f} items/sec")
print(f"   Latency: {db_model.latency(optimal_throughput):.1f}ms")

print("\n3. Efficiency-optimized:")
optimal_efficiency = optimizer.find_optimal_batch_size(optimize_for="efficiency")
print(f"   Optimal batch size: {optimal_efficiency}")
print(f"   Throughput: {db_model.throughput(optimal_efficiency):.1f} items/sec")
print(f"   Latency: {db_model.latency(optimal_efficiency):.1f}ms")
print(f"   Efficiency: {db_model.efficiency(optimal_efficiency):.1f}")

# Analyze trade-offs
print("\n4. Trade-off Analysis:")
optimizer.analyze_trade_offs([1, 10, 50, 100, 200, 500, 1000])
```

### Adaptive Optimization

Dynamic adjustment based on system conditions:

```python
class AdaptiveOptimizer:
    """Dynamically adjust batch size based on system performance."""
    
    def __init__(self, initial_batch_size: int = 100,
                 target_latency: float = 100.0,
                 latency_tolerance: float = 0.2):
        self.batch_size = initial_batch_size
        self.target_latency = target_latency
        self.latency_tolerance = latency_tolerance
        self.performance_history = []
    
    def update_performance(self, actual_latency: float, actual_throughput: float):
        """Update performance metrics and adjust batch size."""
        
        self.performance_history.append({
            'batch_size': self.batch_size,
            'latency': actual_latency,
            'throughput': actual_throughput,
            'timestamp': time.time()
        })
        
        # Keep only recent history
        if len(self.performance_history) > 10:
            self.performance_history.pop(0)
        
        # Adjust batch size based on latency
        latency_ratio = actual_latency / self.target_latency
        
        if latency_ratio > (1 + self.latency_tolerance):
            # Latency too high, reduce batch size
            self.batch_size = max(1, int(self.batch_size * 0.9))
        elif latency_ratio < (1 - self.latency_tolerance):
            # Latency acceptable, try to increase throughput
            self.batch_size = int(self.batch_size * 1.1)
        
        return self.batch_size
    
    def get_recommendations(self) -> dict:
        """Get optimization recommendations based on history."""
        
        if len(self.performance_history) < 3:
            return {"recommendation": "Need more data"}
        
        recent_performance = self.performance_history[-3:]
        avg_latency = sum(p['latency'] for p in recent_performance) / len(recent_performance)
        avg_throughput = sum(p['throughput'] for p in recent_performance) / len(recent_performance)
        
        recommendations = {
            'current_batch_size': self.batch_size,
            'avg_latency': avg_latency,
            'avg_throughput': avg_throughput,
            'latency_status': 'good' if avg_latency <= self.target_latency else 'high',
            'trend': self._analyze_trend()
        }
        
        return recommendations
    
    def _analyze_trend(self) -> str:
        """Analyze performance trend."""
        
        if len(self.performance_history) < 5:
            return "insufficient_data"
        
        recent_throughput = [p['throughput'] for p in self.performance_history[-5:]]
        
        if recent_throughput[-1] > recent_throughput[0]:
            return "improving"
        elif recent_throughput[-1] < recent_throughput[0]:
            return "declining"
        else:
            return "stable"

# Example adaptive optimization
import time

adaptive_optimizer = AdaptiveOptimizer(
    initial_batch_size=50,
    target_latency=75.0,
    latency_tolerance=0.15
)

print("Adaptive Optimization Simulation:")
print("-" * 50)

# Simulate changing conditions
conditions = [
    (100, 50.0),   # Low load
    (500, 60.0),   # Medium load  
    (1000, 80.0),  # High load
    (1500, 120.0), # Very high load
    (300, 45.0)    # Return to normal
]

for i, (load, base_latency) in enumerate(conditions):
    print(f"\nCondition {i+1}: Load={load}, Base Latency={base_latency}ms")
    
    # Simulate 5 measurements under this condition
    for measurement in range(5):
        # Simulate actual performance (with some randomness)
        actual_latency = base_latency + (adaptive_optimizer.batch_size * 0.1) + np.random.normal(0, 5)
        actual_throughput = (adaptive_optimizer.batch_size * load) / actual_latency
        
        # Update optimizer
        new_batch_size = adaptive_optimizer.update_performance(actual_latency, actual_throughput)
        
        print(f"  Measurement {measurement+1}: Latency={actual_latency:.1f}ms, "
              f"Throughput={actual_throughput:.1f}, New Batch Size={new_batch_size}")
    
    # Get recommendations
    recommendations = adaptive_optimizer.get_recommendations()
    print(f"  Recommendations: {recommendations}")
```

## Real-World Curve Shaping Factors

### System Load Impact

System load affects both throughput and latency:

```python
def model_load_impact():
    """Model how system load affects the throughput-latency curve."""
    
    base_model = ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.1)
    
    load_factors = [0.5, 1.0, 1.5, 2.0]  # Load multipliers
    batch_sizes = [1, 10, 50, 100, 500]
    
    print("Load Impact Analysis:")
    print("Load Factor\tBatch Size\tThroughput\tLatency")
    print("-" * 50)
    
    for load in load_factors:
        # Higher load increases both fixed and variable costs
        loaded_model = ThroughputLatencyModel(
            fixed_cost=base_model.fixed_cost * load,
            variable_cost=base_model.variable_cost * load
        )
        
        for batch_size in batch_sizes:
            throughput = loaded_model.throughput(batch_size)
            latency = loaded_model.latency(batch_size)
            print(f"{load:>8.1f}\t{batch_size:>6}\t{throughput:>8.1f}\t{latency:>6.1f}ms")

model_load_impact()
```

### Memory Pressure

Memory constraints can change the optimal batch size:

```python
def model_memory_constraints():
    """Model how memory constraints affect optimal batch size."""
    
    # Memory usage per item (bytes)
    memory_per_item = 1024  # 1KB per item
    available_memory = 100 * 1024 * 1024  # 100MB
    
    max_batch_size = available_memory // memory_per_item
    
    print(f"Memory Constraint Analysis:")
    print(f"Available memory: {available_memory / (1024*1024):.1f}MB")
    print(f"Memory per item: {memory_per_item}B")
    print(f"Maximum batch size: {max_batch_size}")
    
    # Find optimal batch size within memory constraints
    model = ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.1)
    
    best_throughput = 0
    best_batch_size = 1
    
    for batch_size in range(1, min(max_batch_size + 1, 10000)):
        throughput = model.throughput(batch_size)
        if throughput > best_throughput:
            best_throughput = throughput
            best_batch_size = batch_size
    
    print(f"\nOptimal batch size: {best_batch_size}")
    print(f"Optimal throughput: {best_throughput:.1f} items/sec")
    print(f"Memory utilization: {(best_batch_size * memory_per_item) / (1024*1024):.1f}MB")

model_memory_constraints()
```

## Advanced Curve Analysis

### Multi-Dimensional Optimization

Real systems often have multiple competing objectives:

```python
def multi_objective_optimization():
    """Optimize for multiple objectives simultaneously."""
    
    model = ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.1)
    
    # Define weights for different objectives
    weights = {
        'throughput': 0.4,
        'latency': 0.3,      # Negative weight (we want to minimize)
        'memory': 0.2,       # Negative weight (we want to minimize)
        'reliability': 0.1   # Higher batch size might reduce reliability
    }
    
    batch_sizes = range(1, 1001)
    best_score = -float('inf')
    best_batch_size = 1
    
    for batch_size in batch_sizes:
        # Calculate normalized metrics
        throughput = model.throughput(batch_size)
        latency = model.latency(batch_size)
        memory_usage = batch_size * 1024  # 1KB per item
        reliability = 1.0 / (1.0 + batch_size * 0.001)  # Decreases with batch size
        
        # Normalize metrics (simple min-max normalization)
        norm_throughput = throughput / 10000  # Assume max 10k items/sec
        norm_latency = latency / 1000         # Assume max 1000ms
        norm_memory = memory_usage / (1024 * 1024)  # Assume max 1MB
        norm_reliability = reliability  # Already 0-1
        
        # Calculate weighted score
        score = (weights['throughput'] * norm_throughput +
                weights['latency'] * (1 - norm_latency) +  # Invert latency
                weights['memory'] * (1 - norm_memory) +    # Invert memory
                weights['reliability'] * norm_reliability)
        
        if score > best_score:
            best_score = score
            best_batch_size = batch_size
    
    print(f"Multi-Objective Optimization:")
    print(f"Best batch size: {best_batch_size}")
    print(f"Best score: {best_score:.3f}")
    print(f"Throughput: {model.throughput(best_batch_size):.1f} items/sec")
    print(f"Latency: {model.latency(best_batch_size):.1f}ms")
    print(f"Memory: {best_batch_size * 1024 / 1024:.1f}MB")

multi_objective_optimization()
```

## Practical Applications

### Service Level Agreements (SLAs)

Using the curve to meet SLA requirements:

```python
def sla_compliance_analysis():
    """Analyze batch size options for SLA compliance."""
    
    model = ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.1)
    
    # SLA requirements
    sla_requirements = {
        'p99_latency': 200.0,     # 99th percentile latency < 200ms
        'min_throughput': 5000.0,  # Minimum 5000 items/sec
        'availability': 0.999      # 99.9% availability
    }
    
    print("SLA Compliance Analysis:")
    print(f"Requirements: P99 < {sla_requirements['p99_latency']}ms, "
          f"Throughput > {sla_requirements['min_throughput']} items/sec")
    print("-" * 60)
    
    compliant_batch_sizes = []
    
    for batch_size in range(1, 1001):
        throughput = model.throughput(batch_size)
        latency = model.latency(batch_size)
        
        # Estimate P99 latency (assume some variance)
        p99_latency = latency * 1.5  # Simple approximation
        
        meets_latency = p99_latency <= sla_requirements['p99_latency']
        meets_throughput = throughput >= sla_requirements['min_throughput']
        
        if meets_latency and meets_throughput:
            compliant_batch_sizes.append(batch_size)
    
    if compliant_batch_sizes:
        print(f"Compliant batch sizes: {min(compliant_batch_sizes)}-{max(compliant_batch_sizes)}")
        
        # Find optimal within compliant range
        optimal_batch_size = min(compliant_batch_sizes, 
                               key=lambda x: model.latency(x))  # Minimize latency
        
        print(f"Recommended batch size: {optimal_batch_size}")
        print(f"Throughput: {model.throughput(optimal_batch_size):.1f} items/sec")
        print(f"Latency: {model.latency(optimal_batch_size):.1f}ms")
        print(f"Estimated P99: {model.latency(optimal_batch_size) * 1.5:.1f}ms")
    else:
        print("No batch size can meet all SLA requirements!")

sla_compliance_analysis()
```

### Capacity Planning

Using the curve for capacity planning:

```python
def capacity_planning():
    """Use throughput-latency curve for capacity planning."""
    
    model = ThroughputLatencyModel(fixed_cost=10.0, variable_cost=0.1)
    
    # Planning scenarios
    scenarios = [
        {"name": "Current Load", "requests_per_second": 1000},
        {"name": "2x Growth", "requests_per_second": 2000},
        {"name": "5x Growth", "requests_per_second": 5000},
        {"name": "10x Growth", "requests_per_second": 10000}
    ]
    
    print("Capacity Planning Analysis:")
    print("-" * 70)
    
    for scenario in scenarios:
        rps = scenario["requests_per_second"]
        
        print(f"\n{scenario['name']}: {rps} requests/second")
        
        # Find minimum batch size to handle load
        min_batch_size = None
        for batch_size in range(1, 10001):
            throughput = model.throughput(batch_size)
            if throughput >= rps:
                min_batch_size = batch_size
                break
        
        if min_batch_size:
            latency = model.latency(min_batch_size)
            print(f"  Minimum batch size: {min_batch_size}")
            print(f"  Achievable throughput: {model.throughput(min_batch_size):.1f} items/sec")
            print(f"  Resulting latency: {latency:.1f}ms")
            
            # Calculate headroom
            headroom = (model.throughput(min_batch_size) - rps) / rps * 100
            print(f"  Headroom: {headroom:.1f}%")
        else:
            print(f"  Cannot handle {rps} requests/second with current system!")

capacity_planning()
```

## Key Insights and Best Practices

### Understanding the Curve

1. **The curve is predictable**: Given fixed and variable costs, you can model performance
2. **Three distinct regions**: Each requires different optimization strategies
3. **Diminishing returns**: Large batch sizes provide minimal benefits
4. **Context matters**: Optimal batch size depends on your specific requirements

### Optimization Guidelines

1. **Start in Region 1**: Small batches provide huge gains
2. **Tune in Region 2**: Balance latency and throughput requirements
3. **Avoid Region 3**: Unless latency is completely unimportant
4. **Monitor continuously**: System conditions change over time
5. **Consider constraints**: Memory, network, and reliability limits

### Common Mistakes

1. **Ignoring latency**: Focusing only on throughput
2. **One-size-fits-all**: Using the same batch size everywhere
3. **Static optimization**: Not adapting to changing conditions
4. **Neglecting tail latency**: Optimizing for average instead of P99
5. **Overlooking failures**: Not considering how batching affects error handling

## Conclusion

The throughput-latency curve is the mathematical foundation of batching systems. Understanding its shape, regions, and optimization strategies is essential for building efficient systems that meet real-world requirements.

Key takeaways:
1. The curve follows predictable mathematical patterns
2. Three regions require different strategies
3. Optimization requires balancing multiple objectives
4. Real-world factors significantly impact the curve
5. Continuous monitoring and adaptation are essential

Mastering this curve enables you to make informed decisions about batch sizing, meet SLA requirements, and build systems that scale efficiently under varying conditions.