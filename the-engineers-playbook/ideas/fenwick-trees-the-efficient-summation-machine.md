# Fenwick Trees: The Efficient Summation Machine ➕


* **`01-concepts-01-the-core-problem.md`**: Addresses the same problem as Segment Trees (fast range queries and point updates) but asks: "Can we achieve this with a much simpler data structure and less memory?"
* **`01-concepts-02-the-guiding-philosophy.md`**: Leverage binary representations for responsibility. A Fenwick Tree (or Binary Indexed Tree) is a simple array where each index is "responsible" for the sum of a range determined by its binary properties. This allows for hierarchical summation without an explicit tree structure.
* **`01-concepts-03-key-abstractions.md`**: The `implicit tree`, `prefix sums`, and the `low-bit` operation. Analogy: A chain of command where each manager's "total report" covers a group of subordinates whose size is a power of two. To get a total for a specific range, you only need to talk to a few managers.
* **`02-guides-01-getting-started.md`**: A guide implementing a Fenwick Tree with an array in your favorite language. Show the `update` and `query` functions that rely on bitwise operations (`i & -i`).
* **`03-deep-dive-01-the-magic-of-low-bit.md`**: A deep dive into the bit manipulation that makes Fenwick Trees work. It explains why adding or subtracting the "last set bit" of an index allows you to efficiently navigate the implicit tree structure up or down.

---
