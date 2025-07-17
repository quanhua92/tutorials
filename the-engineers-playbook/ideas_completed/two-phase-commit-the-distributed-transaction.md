# Two-Phase Commit: The Distributed Transaction 💱


* **`01-concepts-01-the-core-problem.md`**: How can you update data across multiple databases atomically? If you update database A then database B, what happens if B fails after A succeeds?
* **`01-concepts-02-the-guiding-philosophy.md`**: Prepare then commit. 2PC ensures all participants agree to commit before any of them actually do, providing atomic transactions across distributed resources.
* **`01-concepts-03-key-abstractions.md`**: The `coordinator`, `participants`, `prepare phase`, and `commit phase`. **Analogy**: Planning a group dinner. First, everyone confirms they can attend (prepare). Only after all confirmations does anyone actually book time off work (commit).
* **`02-guides-01-simulating-2pc.md`**: Implement a simple 2PC coordinator that ensures multiple databases either all commit or all abort a distributed transaction.
* **`03-deep-dive-01-the-blocking-problem.md`**: Why 2PC can block indefinitely if the coordinator crashes after prepare but before commit, and how three-phase commit attempts to solve this at the cost of complexity.

---
