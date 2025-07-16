# Ring Buffers: The Circular Conveyor Belt 🔄


* **`01-concepts-01-the-core-problem.md`**: You have a producer of data and a consumer of data that operate at slightly different speeds. How do you buffer the data in a fixed amount of memory without constant allocations, ensuring old data is overwritten?
* **`01-concepts-02-the-guiding-philosophy.md`**: Use a fixed-size array and pointers that wrap around. A ring buffer uses a static array and two pointers, a `head` (for writing) and a `tail` (for reading). When a pointer reaches the end of the array, it wraps back to the beginning.
* **`01-concepts-03-key-abstractions.md`**: The `buffer`, `head` pointer, `tail` pointer, and the concept of `overwriting`. Analogy: A circular conveyor belt of a fixed size. A producer puts items on, a consumer takes them off. If the producer is faster, it will eventually replace the oldest items the consumer hasn't picked up yet.
* **`02-guides-01-implementing-a-logger.md`**: A practical guide to creating a simple logger that keeps only the last N log messages in memory using a ring buffer.
* **`03-deep-dive-01-lock-free-ring-buffers.md`**: Explores how ring buffers are central to high-performance, concurrent systems. With careful use of atomic operations on the head and tail pointers, one producer and one consumer can communicate without any locks.

---
