# Heap Data Structures: The Priority Expert 👑


* **`01-concepts-01-the-core-problem.md`**: You have a dynamic collection of items, and your primary need is to always be able to find and remove the item with the highest (or lowest) priority or value instantly.
* **`01-concepts-02-the-guiding-philosophy.md`**: Maintain a "weakly" sorted tree. A heap is a tree-based structure (usually implemented as an array) that satisfies the **Heap Property**: every parent node is more important (e.g., greater than) its children. This ensures the most important item is always at the root.
* **`01-concepts-03-key-abstractions.md`**: The `Heap Property` (min-heap or max-heap), `sift-up` (or bubble-up), and `sift-down` (or heapify). Analogy: A corporate org chart organized by salary. The CEO is at the top (root). Everyone's salary is higher than their direct reports. You don't know who has the 5th highest salary, but you know instantly who has the highest.
* **`02-guides-01-building-a-priority-queue.md`**: A guide to implementing a priority queue using a heap. Show how `add` and `pop_highest` operations work by adding an element to the end and sifting it up, or by swapping the root with the last element and sifting it down.
* **`03-deep-dive-01-why-an-array.md`**: Why is this tree structure almost always implemented using a flat array? This dive explains the simple arithmetic `(parent = (i-1)/2, children = 2i+1, 2i+2)` that allows for efficient tree traversal without any explicit pointers, making heaps very cache-friendly.

---
