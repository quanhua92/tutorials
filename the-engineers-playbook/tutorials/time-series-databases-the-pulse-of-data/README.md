# Time-Series Databases: The Pulse of Data 📈

Time-series databases are specialized systems designed for storing and querying data that changes over time. Unlike traditional relational databases, they treat time as a first-class citizen, optimizing everything around temporal patterns.

## Summary

This tutorial explores how time-series databases solve the unique challenges of temporal data through specialized architectures, compression techniques, and query optimizations. You'll learn why traditional databases struggle with time-series workloads and how purpose-built solutions achieve remarkable efficiency gains.

## Table of Contents

### 📚 Core Concepts
- **[The Core Problem](01-concepts-01-the-core-problem.md)** - Why time-series data breaks traditional databases and the unique characteristics that demand specialized solutions
- **[The Guiding Philosophy](01-concepts-02-the-guiding-philosophy.md)** - How treating time as the primary axis drives every architectural decision in time-series databases  
- **[Key Abstractions](01-concepts-03-key-abstractions.md)** - Understanding timestamps, metrics, tags, and time-based partitioning as the building blocks of temporal data

### 🛠️ Practical Guides
- **[Modeling CPU Usage](02-guides-01-modeling-cpu-usage.md)** - A hands-on guide to structuring server monitoring data for optimal storage and querying performance

### 🔍 Deep Dives
- **[Time-Series Compression](03-deep-dive-01-time-series-compression.md)** - The secret behind 10-20x compression ratios: delta-of-delta encoding, XOR compression, and specialized algorithms

### 💻 Implementation
- **[Rust Implementation](04-rust-implementation.md)** - Build a working time-series compression engine implementing delta-of-delta and XOR compression algorithms

---

**What You'll Learn:**
- Why time-series databases exist and when to use them
- How to model temporal data for maximum efficiency  
- The compression techniques that make massive time-series storage practical
- Implementation details of real compression algorithms used in production systems

**Prerequisites:** Basic understanding of databases and data structures. Rust knowledge helpful for the implementation section but not required for understanding the concepts.