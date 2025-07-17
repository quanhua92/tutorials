# Ring Buffers: The Circular Conveyor Belt 🔄

Ring buffers are specialized data structures designed for bounded producer-consumer communication. Like a circular conveyor belt of fixed size, they enable efficient buffering between processes that operate at different speeds while using predictable memory and providing excellent performance.

## Summary

This tutorial explores how ring buffers solve the fundamental challenge of buffering data between producers and consumers when they operate at different speeds. You'll learn why traditional unbounded buffers fail in practice, how the circular buffer design enables predictable performance, and the advanced lock-free techniques that make ring buffers essential for high-performance systems.

## Table of Contents

### 📚 Core Concepts
- **[The Core Problem](01-concepts-01-the-core-problem.md)** - Why buffering data between mismatched producers and consumers leads to memory explosion and how ring buffers solve this with fixed-size circular storage
- **[The Guiding Philosophy](01-concepts-02-the-guiding-philosophy.md)** - The design philosophy of embracing constraints to achieve predictability: bounded resources, recency over completeness, and simplicity enabling correctness
- **[Key Abstractions](01-concepts-03-key-abstractions.md)** - Understanding the buffer, head pointer, tail pointer, and overwriting behavior as the building blocks of circular thinking

### 🛠️ Practical Guides
- **[Implementing a Logger](02-guides-01-implementing-a-logger.md)** - Build a practical logging system that keeps only the most recent N log messages, perfect for embedded systems and memory-constrained environments

### 🔍 Deep Dives
- **[Lock-Free Ring Buffers](03-deep-dive-01-lock-free-ring-buffers.md)** - Advanced concurrent programming: how atomic operations, memory ordering, and careful algorithm design enable multiple threads to cooperate without blocking

### 💻 Implementation
- **[Rust Implementation](04-rust-implementation.md)** - Build production-ready ring buffers including basic (lock-based), SPSC (single producer, single consumer), and MPSC (multiple producer, single consumer) variants

---

**What You'll Learn:**
- Why unlimited buffering leads to system crashes and how fixed-size buffers provide reliability
- The trade-offs between data completeness and system predictability
- Lock-free programming techniques using atomic operations and memory ordering
- Real-world applications in audio processing, high-frequency trading, and embedded systems

**Prerequisites:** Basic understanding of data structures and memory management. Knowledge of concurrency concepts helpful for the advanced sections but not required for understanding the core concepts.