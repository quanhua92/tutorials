# Bloom Filters: The Space-Efficient Gatekeeper 🚪


* **`01-concepts-01-the-core-problem.md`**: You need to check if an item exists in a massive set, but you don't have enough memory to store the entire set.
* **`01-concepts-02-the-guiding-philosophy.md`**: Use a probabilistic bit array. Instead of storing the items, we use multiple hash functions to flip bits in a fixed-size array. This "fingerprint" can tell us if an item is *definitely not* in the set, or *probably* is.
* **`01-concepts-03-key-abstractions.md`**: The `bit array`, multiple `hash functions`, and the concept of `false positives` (but no false negatives). Analogy: A security guard who doesn't know every employee's face but knows a few distinct features of each. If you lack those features, you're definitely not an employee. If you have them, you might be, or you might just be a look-alike.
* **`02-guides-01-getting-started.md`**: Practical guide to using a Bloom filter library to check for previously seen articles in a web crawler, avoiding expensive database lookups.
* **`03-deep-dive-01-calculating-size-and-error.md`**: How do you choose the size of the bit array and the number of hash functions based on your expected number of items and desired false positive rate? Provides the formulas and intuition behind them.

---
