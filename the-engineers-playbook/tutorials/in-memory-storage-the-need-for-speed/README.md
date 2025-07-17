# In-Memory Storage: The Need for Speed

## Summary

In-memory storage systems eliminate the fundamental performance bottleneck of traditional databases: disk I/O. By keeping data entirely in RAM, these systems achieve microsecond response times and can handle hundreds of thousands of operations per second. This tutorial series explores the core concepts, trade-offs, and implementation strategies that make in-memory storage the backbone of high-performance applications.

From understanding why disk is the enemy of speed to implementing your own Redis-like key-value store in Rust, you'll gain deep insights into the design decisions that enable systems to respond at the speed of thought. We examine the persistence challenge—how to maintain blazing speed while ensuring data durability—and explore practical strategies used by production systems.

Whether you're building real-time analytics, high-frequency trading systems, or simply want to understand why Redis can outperform traditional databases by orders of magnitude, this series provides the foundational knowledge to think about data storage in terms of speed, not just capacity.

## Table of Contents

### Section 1: Core Concepts

- **[The Core Problem: Disk is the Enemy of Speed](01-concepts-01-the-core-problem.md)**  
  Understand the astronomical speed difference between memory and disk access, and why this gap makes in-memory storage not just faster, but fundamentally different.

- **[The Guiding Philosophy: Trading Durability for Speed](01-concepts-02-the-guiding-philosophy.md)**  
  Explore the conscious design choice to optimize for speed above all else, and the mindset shift required to build memory-first systems.

- **[Key Abstractions: The Building Blocks of Memory Speed](01-concepts-03-key-abstractions.md)**  
  Learn the mental models and data structures that make in-memory systems possible: key-value stores, working sets, atomic operations, and the desk vs. filing cabinet analogy.

### Section 2: Practical Guides

- **[Getting Started: Your First In-Memory Database](02-guides-01-getting-started.md)**  
  A hands-on introduction to Redis that demonstrates the speed difference in practice. Install Redis, run your first commands, and experience microsecond response times firsthand.

### Section 3: Deep Dives

- **[The Persistence Problem: When the Power Goes Out](03-deep-dive-01-the-persistence-problem.md)**  
  Examine the fundamental tension between speed and durability. Learn about snapshots, append-only files, replication strategies, and how to choose the right persistence approach for your use case.

### Section 4: Implementation

- **[Rust Implementation: Building a Mini In-Memory Store](04-rust-implementation.md)**  
  Build your own Redis-like key-value store from scratch in Rust. Understand the data structures, concurrency models, and design decisions that make in-memory storage systems fast and reliable.

---

**Learning Objectives:**
- Understand why in-memory storage is orders of magnitude faster than disk-based systems
- Learn the fundamental trade-offs between speed, durability, and capacity
- Master the key abstractions that make in-memory systems possible
- Gain hands-on experience with Redis and understand its design principles
- Explore persistence strategies for different durability requirements
- Implement a working in-memory store to understand the underlying mechanisms

**Prerequisites:**
- Basic understanding of data structures (hash tables, arrays)
- Familiarity with command-line operations
- For the Rust implementation: basic Rust knowledge helpful but not required