# Skip Lists: The Probabilistic Search Tree 🎲


* **`01-concepts-01-the-core-problem.md`**: Balanced binary search trees (like Red-Black trees) offer great search performance ($O(\log n)$) but are complex to implement and hard to make concurrent. Is there a simpler way?
* **`01-concepts-02-the-guiding-philosophy.md`**: Create an express lane. A skip list is a sorted linked list with additional "express lane" pointers that skip over several nodes. These express lanes are added probabilistically.
* **`01-concepts-03-key-abstractions.md`**: The `multi-level linked list` and `probabilistic promotion`. Analogy: A highway system over a local road. To travel a long distance, you take the highway (top-level pointers), then exit to the local roads (base list) when you get close to your destination.
* **`02-guides-01-visualizing-a-search.md`**: A visual guide or simple animation showing a search in a skip list, starting at the top-left, moving across the "express lanes," and dropping down levels as needed.
* **`03-deep-dive-01-why-skip-lists-in-concurrent-systems.md`**: Explores why databases like Redis use skip lists. Their structure allows for simpler, lock-free implementations, making them perform exceptionally well in highly concurrent environments compared to the complex locking required for B-Trees.

---
