# Adaptive Data Structures: The Self-Optimizer  chameleon 🦎


* **`01-concepts-01-the-core-problem.md`**: The best data structure for a task often depends on the access pattern, which may not be known in advance or can change over time. How can a data structure modify itself to become more efficient for the workload it actually experiences?
* **`01-concepts-02-the-guiding-philosophy.md`**: Change structure based on usage. An adaptive data structure dynamically alters its internal layout or strategy in response to the sequence of operations performed on it, aiming to improve future performance.
* **`01-concepts-03-key-abstractions.md`**: `Self-optimization`, the `access pattern`, and `heuristics` (like move-to-front). **Analogy**: A self-organizing toolbox. After a week of plumbing work, the pipe wrenches and cutters have naturally moved from the bottom drawer to the top tray for easier access. The toolbox adapts to the job being done.
* **`02-guides-01-the-splay-tree.md`**: A guide focusing on the Splay Tree as a classic example. It visually demonstrates how accessing a node causes a series of rotations that bring that node all the way to the root, making it and its neighbors faster to access next time.
* **`03-deep-dive-01-amortized-analysis.md`**: Explores the performance guarantees of adaptive structures. A single operation on a Splay Tree can be slow, but any sequence of M operations is guaranteed to be fast *on average*. This introduces the concept of **amortized analysis**, which is key to understanding their power.

---
