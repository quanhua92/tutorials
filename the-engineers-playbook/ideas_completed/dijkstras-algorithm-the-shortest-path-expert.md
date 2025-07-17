# Dijkstra's Algorithm: The Shortest Path Expert 🗺️


* **`01-concepts-01-the-core-problem.md`**: In a weighted graph (like a road network with distances), how do you find the shortest path from one node to all others? Trying all possible paths is exponentially expensive.
* **`01-concepts-02-the-guiding-philosophy.md`**: Greedily explore the closest unvisited node. The algorithm maintains a priority queue of nodes ordered by their tentative distance from the source, always processing the closest node next.
* **`01-concepts-03-key-abstractions.md`**: The `distance array`, `priority queue`, and `relaxation`. **Analogy**: Planning a road trip. At each step, you ask "What's the closest city I haven't visited yet?" Once there, you check if it offers shorter routes to other cities than you previously knew.
* **`02-guides-01-implementing-dijkstra.md`**: Build a route finder for a small city map, showing how the algorithm discovers shortest paths to all locations from a starting point.
* **`03-deep-dive-01-negative-weights-and-variants.md`**: Why Dijkstra fails with negative edge weights, and variants like A* that use heuristics to find paths faster by directing the search toward the goal.

---
