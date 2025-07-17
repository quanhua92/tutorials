# Graph Traversal: Navigating the Network 🕸️


* **`01-concepts-01-the-core-problem.md`**: How do you systematically explore all nodes in a graph, find paths between nodes, or determine if nodes are connected? Random wandering through a graph is inefficient and may miss nodes entirely.
* **`01-concepts-02-the-guiding-philosophy.md`**: Visit nodes methodically using a frontier. The core idea is to maintain a boundary between explored and unexplored territory, systematically expanding this frontier until the goal is reached or all reachable nodes are visited.
* **`01-concepts-03-key-abstractions.md`**: The `frontier` (queue for BFS, stack for DFS), `visited set`, and `traversal order`. **Analogy**: Exploring a cave system. BFS is like exploring all rooms at the current depth before going deeper (breadth-first). DFS is like following one tunnel as far as possible before backtracking (depth-first).
* **`02-guides-01-getting-started.md`**: Implement BFS and DFS to find if there's a path between two nodes in a social network graph.
* **`03-deep-dive-01-applications-and-trade-offs.md`**: When to use BFS vs DFS. BFS finds shortest paths in unweighted graphs and explores neighbors first. DFS uses less memory and is better for detecting cycles or topological sorting.

---
