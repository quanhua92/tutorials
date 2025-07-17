# B-Trees: The Disk's Best Friend 🌳


* **`01-concepts-01-the-core-problem.md`**: How do databases store and retrieve indexed data on a spinning disk efficiently? Accessing disk is slow, so we must minimize the number of reads.
* **`01-concepts-02-the-guiding-philosophy.md`**: Keep related data close. B-Trees are short and wide, designed to store many keys in a single block (or "page"). This ensures that one disk read fetches a large, useful chunk of the index.
* **`01-concepts-03-key-abstractions.md`**: Explains `nodes`, `keys`, `pointers`, and the tree's `order`. Analogy: A multi-level filing system where each drawer (node) contains many folders (keys) and pointers to other drawers.
* **`02-guides-01-visualizing-a-b-tree.md`**: A guide that walks through inserting keys into a simple B-Tree, showing how nodes split and the tree grows.
* **`03-deep-dive-01-b-trees-vs-binary-search-trees.md`**: Why are B-Trees used in databases instead of simple BSTs? A deep dive into cache lines, disk pages, and access patterns. The mental model is optimizing for "chunky" reads instead of "pointy" reads.

---
