# Sharding: Slicing the Monolith 🍰


* **`01-concepts-01-the-core-problem.md`**: A single server has limits on storage, memory, and CPU. How can a dataset grow beyond the capacity of the most powerful single machine available?
* **`01-concepts-02-the-guiding-philosophy.md`**: Divide and conquer. The philosophy is to split a large database horizontally into smaller, more manageable pieces called shards, and distribute them across multiple servers.
* **`01-concepts-03-key-abstractions.md`**: Explains the `shard key`, the `router` (or query coordinator), and `resharding`. Analogy: A massive library that is split into several smaller, specialized branch libraries across a city. The main directory (router) tells you which branch to visit for a specific book genre (shard key).
* **`02-guides-01-simulating-sharding.md`**: A conceptual guide showing how to distribute user data into different files or tables based on a `user_id` hash, demonstrating how a router would decide where to write or read data.
* **`03-deep-dive-01-choosing-a-shard-key.md`**: This is the most critical decision in sharding. A deep dive into what makes a good shard key (high cardinality, even distribution) and the problems caused by a bad one (hotspots).

---
