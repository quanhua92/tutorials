# Indexing: The Ultimate Table of Contents 📖


* **`01-concepts-01-the-core-problem.md`**: Searching for a row in a database table by a non-primary key value requires a full table scan, which is incredibly slow for large tables.
* **`01-concepts-02-the-guiding-philosophy.md`**: Create a shortcut. An index is a separate data structure (often a B-Tree) that stores column values and pointers to the original rows, presorted for fast lookups.
* **`01-concepts-03-key-abstractions.md`**: `Index`, `indexed column`, `query planner`, and the `write penalty`. Analogy: The index at the back of a textbook. Instead of reading the whole book to find a topic, you look it up in the index and go directly to the right page number.
* **`02-guides-01-using-an-index.md`**: A practical SQL guide. Run a `SELECT` query on a large table with a `WHERE` clause, use `EXPLAIN` to show the full table scan, add an index, and run `EXPLAIN` again to show the fast index scan.
* **`03-deep-dive-01-the-cost-of-indexing.md`**: Indexes aren't free. This deep dive explains the trade-off: faster reads vs. slower writes and increased storage space. Every `INSERT`, `UPDATE`, or `DELETE` now has to update the indexes too.

---
