# Segment Trees: The Range Query Specialist 📏


* **`01-concepts-01-the-core-problem.md`**: Given an array of numbers, you need to answer many queries about the sum (or min, max, etc.) of a given range, e.g., "What is the sum of elements from index 34 to 91?". You also need to be able to update elements. A naive loop for each query is too slow.
* **`01-concepts-02-the-guiding-philosophy.md`**: Pre-compute aggregates for hierarchical blocks. A segment tree is a binary tree where each leaf represents an element of the array. Each internal node represents an aggregate (like the sum) of its children, effectively covering a segment of the original array.
* **`01-concepts-03-key-abstractions.md`**: The `tree`, `nodes` (storing segment results), and the `query/update` logic. Analogy: A regional sales hierarchy. Each salesperson has their daily sales (leaves). Their manager knows the team's total. The regional director knows the sum of all their managers' teams. To get the total for a specific set of sales teams, you just need to ask a few managers, not every salesperson.
* **`02-guides-01-building-a-sum-tree.md`**: A practical guide to taking an array `[1, 3, 5, 7]` and building the corresponding segment tree that can quickly answer sum queries like `sum(1, 3)`.
* **`03-deep-dive-01-logarithmic-power.md`**: A deep dive into the complexity. Why are both updates and queries $O(\log n)$? It's because any given range in the original array can be represented by at most $2 \log n$ nodes in the tree, and an update only affects the $\log n$ nodes in its direct path to the root.

---
