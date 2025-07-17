# Distributed Tracing: The Request Detective 🕵️


* **`01-concepts-01-the-core-problem.md`**: In microservice architectures, a single user request might touch dozens of services. When something goes wrong, how do you trace the request path and find bottlenecks?
* **`01-concepts-02-the-guiding-philosophy.md`**: Propagate context across service boundaries. Each request gets a unique trace ID that follows it through every service, with each service recording its portion of the work.
* **`01-concepts-03-key-abstractions.md`**: The `trace`, `span`, and `context propagation`. **Analogy**: A package delivery system where each handler scans the package. The tracking number (trace ID) lets you see the complete journey and how long each step took.
* **`02-guides-01-opentelemetry-basics.md`**: Instrument a simple microservice application to generate traces, showing how to visualize request flow and timing.
* **`03-deep-dive-01-sampling-strategies.md`**: The cost of tracing everything vs. the risk of missing important traces, exploring adaptive sampling and tail-based sampling strategies.

---
