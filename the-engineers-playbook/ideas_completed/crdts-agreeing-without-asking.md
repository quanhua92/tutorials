# CRDTs: Agreeing Without Asking 🤝


* **`01-concepts-01-the-core-problem.md`**: In distributed systems like a collaborative text editor or a multi-leader database, how can nodes accept updates independently and concurrently without coordination, and still guarantee that they will all eventually converge to the same state?
* **`01-concepts-02-the-guiding-philosophy.md`**: Design data structures with commutative and associative properties. Conflict-free Replicated Data Types (CRDTs) are mathematically designed so that the order in which operations are applied doesn't matter. The final state is the inevitable result of merging all operations.
* **`01-concepts-03-key-abstractions.md`**: The `G-Counter` (a grow-only counter), the `PN-Counter` (allows increments and decrements), and the `G-Set` (a grow-only set). Analogy: A shared grocery list. Two people can add "milk" and "bread" from separate phones. When their lists sync, the result is simply {"milk", "bread"}. The merge operation is a simple union.
* **`02-guides-01-implementing-a-pn-counter.md`**: A guide to building a simple PN-Counter. It shows how each replica maintains a vector of positive and negative counts, and how merging two replicas is a matter of taking the element-wise maximum of their vectors.
* **`03-deep-dive-01-state-based-vs-op-based-crdts.md`**: A deep dive into the two main families of CRDTs. **State-based** (CvRDTs) send their entire state for merging, which is simple but can be large. **Operation-based** (CmRDTs) send the specific operations, which is more efficient but requires stronger guarantees from the transport layer.

---
