# Hashing: The Universal Filing System 🗂️


* **`01-concepts-01-the-core-problem.md`**: Addresses the challenge of finding specific data in a vast collection without a linear scan. Analogy: Finding a specific person's file in a massive, unsorted filing cabinet.
* **`01-concepts-02-the-guiding-philosophy.md`**: Introduces the idea of calculating a location instead of searching for it. The philosophy is to create a direct "address" for each piece of data using a deterministic function.
* **`01-concepts-03-key-abstractions.md`**: Explains the core components: `keys`, `values`, `hash function`, and `buckets`. Analogy: A post office where the hash function is the clerk who instantly tells you which P.O. Box (`bucket`) holds the mail for a specific person (`key`).
* **`02-guides-01-getting-started.md`**: A "hello world" guide to using a hash map (dictionary in Python, `Map` in JavaScript) to create a simple phonebook.
* **`03-deep-dive-01-collision-resolution.md`**: Explores what happens when two keys map to the same bucket. Covers chaining (linked lists in buckets) and open addressing (finding the next empty slot). Analogy: What to do when two people are assigned the same P.O. Box.
* **`03-deep-dive-02-load-factor-and-resizing.md`**: Explains the performance trade-off of how full the hash table gets. Analogy: A parking lot that becomes slow and inefficient as it fills up, eventually needing expansion.

---
