# Union-Find: The Social Network Analyzer 🧑‍🤝‍🧑


* **`01-concepts-01-the-core-problem.md`**: You have a large number of items and a series of connections between them. How can you efficiently determine if any two items are connected, even through a long, indirect path?
* **`01-concepts-02-the-guiding-philosophy.md`**: Group items into sets and assign a representative. The Union-Find data structure maintains a collection of disjoint sets. The `find` operation identifies the representative (or "leader") of an item's set, and the `union` operation merges two sets.
* **`01-concepts-03-key-abstractions.md`**: The `set`, the `representative`, the `union` operation, and the `find` operation. Analogy: A collection of clubs. `find(person)` tells you which club they're in. `union(person_A, person_B)` merges their two clubs into one. Two people are connected if they are in the same club.
* **`02-guides-01-detecting-cycles-in-a-graph.md`**: A classic guide showing how to use Union-Find to determine if adding an edge to a graph would create a cycle.
* **`03-deep-dive-01-the-optimizations-path-compression-and-union-by-rank.md`**: Explains the two crucial optimizations that make Union-Find nearly constant time on average. **Path Compression** flattens the structure during `find`, and **Union by Rank/Size** keeps the trees shallow during `union`.

---
