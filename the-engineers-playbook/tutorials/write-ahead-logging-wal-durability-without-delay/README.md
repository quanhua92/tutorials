# Write-Ahead Logging (WAL): Durability without Delay ✍️

Write-Ahead Logging is the foundational technique that enables databases to provide strong durability guarantees while maintaining excellent performance. By writing intentions before actions, WAL separates the promise of durability from the complexity of implementation.

## Summary

This tutorial explores how Write-Ahead Logging solves the fundamental tension between durability and performance in database systems. You'll learn why traditional approaches fail under load, how WAL's "intent before action" philosophy enables ACID guarantees, and the specific techniques that make production databases reliable.

## Table of Contents

### 📚 Core Concepts
- **[The Core Problem](01-concepts-01-the-core-problem.md)** - How guaranteeing durability without killing performance creates an impossible dilemma for traditional database approaches
- **[The Guiding Philosophy](01-concepts-02-the-guiding-philosophy.md)** - The "intent before action" philosophy that separates commitment from completion and enables fast, reliable databases
- **[Key Abstractions](01-concepts-03-key-abstractions.md)** - Understanding logs, commit records, and recovery as the building blocks that make WAL practical

### 🛠️ Practical Guides  
- **[Simulating WAL](02-guides-01-simulating-wal.md)** - Build a working WAL database in Python with crash simulation, recovery testing, and banking system demonstrations

### 🔍 Deep Dives
- **[WAL and Transactional Guarantees](03-deep-dive-01-wal-and-transactional-guarantees.md)** - How WAL provides the "D" in ACID and enables atomicity, consistency, and isolation at scale

### 💻 Implementation
- **[Python Implementation](04-python-implementation.md)** - Build a working WAL simulation with crash scenarios and recovery testing
- **[Rust Implementation](04-rust-implementation.md)** - Production-grade WAL system with ACID transactions, concurrent operations, and complete crash recovery

---

**What You'll Learn:**
- Why durability and performance seem mutually exclusive and how WAL resolves this tension
- The philosophical shift from "perfect disk state" to "perfect replay-ability"
- How fsync(), LSNs, and commit protocols provide unbreakable durability guarantees
- Implementation techniques used in PostgreSQL, MySQL, and other production databases

**Prerequisites:** Basic understanding of databases and file systems. Python knowledge helpful for the implementation sections but not required for understanding the concepts.