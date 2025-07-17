# LSM Trees: Making Writes Fast Again

## Summary

Traditional B-tree-based storage engines optimize for reads but suffer from poor write performance due to random I/O patterns. Log-Structured Merge Trees (LSM Trees) revolutionize database storage by optimizing for write throughput through sequential I/O and deferred organization. This tutorial explores how LSM Trees achieve high write performance and the trade-offs involved.

## Table of Contents

1. [The Core Problem](./01-concepts-01-the-core-problem.md) - Why traditional storage engines struggle with writes
2. [The Guiding Philosophy](./01-concepts-02-the-guiding-philosophy.md) - Sequential writes and immutable data structures
3. [Key Abstractions](./01-concepts-03-key-abstractions.md) - MemTables, SSTables, and compaction processes
4. [Simulating an LSM Tree](./02-guides-01-simulating-an-lsm-tree.md) - Building a simple LSM Tree in Python
5. [Read and Write Amplification](./03-deep-dive-01-read-and-write-amplification.md) - Understanding the performance trade-offs
6. [Rust Implementation](./04-rust-implementation.md) - Complete working LSM Tree implementation