# Circuit Breakers: The Fault Isolator 🔌


* **`01-concepts-01-the-core-problem.md`**: When a service is failing, continuing to send it requests wastes resources, increases latency, and can cause cascading failures throughout the system.
* **`01-concepts-02-the-guiding-philosophy.md`**: Fail fast when a service is unhealthy. A circuit breaker monitors the error rate and "opens" to immediately reject requests when a service is failing, giving it time to recover.
* **`01-concepts-03-key-abstractions.md`**: The `states` (closed, open, half-open), `failure threshold`, and `timeout`. **Analogy**: An electrical circuit breaker. When too much current flows (too many errors), it trips (opens) to prevent damage. After cooling down, you can try to reset it (half-open state).
* **`02-guides-01-basic-circuit-breaker.md`**: Implement a circuit breaker wrapper for HTTP requests, showing state transitions and recovery behavior.
* **`03-deep-dive-01-tuning-and-patterns.md`**: How to set thresholds, timeout durations, and implement advanced patterns like slow-start recovery and request hedging.

---
