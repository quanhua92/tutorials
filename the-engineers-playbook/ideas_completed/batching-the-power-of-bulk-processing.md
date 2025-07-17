# Batching: The Power of Bulk Processing 🛒


* **`01-concepts-01-the-core-problem.md`**: Performing many small operations, like individual network requests or database writes, is inefficient. Each operation has a fixed overhead (network latency, transaction setup) that dominates the actual work.
* **`01-concepts-02-the-guiding-philosophy.md`**: Amortize fixed costs over multiple operations. Batching is the simple but powerful technique of collecting multiple individual items or operations into a single group (a batch) and processing that group as a single unit.
* **`01-concepts-03-key-abstractions.md`**: The `batch size`, `batching window` (time-based), and the `throughput vs. latency` trade-off. **Analogy**: A pizza delivery driver. It's wildly inefficient to deliver one pizza at a time. Instead, the driver waits to collect several orders going to the same neighborhood and delivers them all in one trip. The cost of the trip is amortized across many pizzas.
* **`02-guides-01-batching-database-inserts.md`**: A practical guide comparing two approaches. First, inserting 1,000 rows into a database one by one in a loop. Second, inserting all 1,000 rows in a single `INSERT` statement. The performance difference will be dramatic.
* **`03-deep-dive-01-the-throughput-vs-latency-curve.md`**: This is the fundamental trade-off of batching. Batching always increases **throughput** (more work done per second). However, it also increases **latency** for the first item in a batch, as it has to wait for the batch to be filled or for a time window to expire. This deep dive explains how to choose a batch size by understanding this critical curve.

---
