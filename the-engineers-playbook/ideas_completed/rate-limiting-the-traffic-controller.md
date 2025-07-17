# Rate Limiting: The Traffic Controller 🚦


* **`01-concepts-01-the-core-problem.md`**: Without limits, a single user or bug can overwhelm a service with requests, causing degraded performance or downtime for everyone.
* **`01-concepts-02-the-guiding-philosophy.md`**: Budget requests over time. Rate limiting ensures fair access to resources by limiting how many requests a client can make within a time window.
* **`01-concepts-03-key-abstractions.md`**: The `rate`, `window`, and `limiting algorithm`. **Analogy**: A highway on-ramp meter. During rush hour, it only allows one car to enter every few seconds, preventing the highway from becoming gridlocked.
* **`02-guides-01-implementing-token-bucket.md`**: Build a token bucket rate limiter showing how tokens regenerate over time and requests consume tokens.
* **`03-deep-dive-01-algorithms-comparison.md`**: Compares token bucket, sliding window, and fixed window algorithms, explaining their trade-offs in terms of burstiness, fairness, and implementation complexity.

---
