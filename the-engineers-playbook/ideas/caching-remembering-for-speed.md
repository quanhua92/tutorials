# Caching: Remembering for Speed 🧠


* **`01-concepts-01-the-core-problem.md`**: Some data is expensive to compute or retrieve, but it's needed over and over. Re-doing the work every time is wasteful and slow.
* **`01-concepts-02-the-guiding-philosophy.md`**: Keep a copy close by. The philosophy is to store the results of expensive operations in a faster, closer storage layer (like memory).
* **`01-concepts-03-key-abstractions.md`**: The `cache`, `cache hit`, `cache miss`, and `eviction policy`. Analogy: Keeping commonly used tools on your workbench (cache) instead of in the garage (database). When the bench gets full, you have to decide which tool to put back (eviction).
* **`02-guides-01-simple-memoization.md`**: A guide to implementing a simple cache using a decorator in Python (`@lru_cache`) to speed up a recursive Fibonacci function.
* **`03-deep-dive-01-cache-invalidation.md`**: Explores one of the two hard things in computer science. When and how do you update or remove stale data from the cache? Covers strategies like TTL (Time-To-Live), write-through, and write-back caching.

---
