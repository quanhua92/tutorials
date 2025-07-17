# Radix Trees: The Compressed Prefix Tree

A comprehensive tutorial on radix trees (also known as PATRICIA tries or compressed tries), exploring how path compression transforms memory-hungry standard tries into efficient, production-ready data structures.

## Summary

Radix trees solve a fundamental problem with standard tries: memory waste from long chains of single-child nodes. By compressing these chains into single edges labeled with strings, radix trees achieve the same functionality as tries while using dramatically less memory and often delivering better performance.

This tutorial covers the theoretical foundations, practical implementation considerations, and real-world applications—particularly focusing on IP routing tables where radix trees enable the modern internet's packet forwarding infrastructure.

## Table of Contents

### 📋 Core Concepts
- **[The Core Problem](01-concepts-01-the-core-problem.md)**: Understanding memory waste in sparse tries and why single-child node chains are inefficient
- **[The Guiding Philosophy](01-concepts-02-the-guiding-philosophy.md)**: Path compression principles and the express train analogy
- **[Key Abstractions](01-concepts-03-key-abstractions.md)**: Compressed paths, explicit branch nodes, and design invariants

### 🛠️ Practical Guides  
- **[Trie vs Radix Tree](02-guides-01-trie-vs-radix-tree.md)**: Visual comparison showing dramatic memory and performance differences

### 🧠 Deep Dives
- **[IP Routing Tables](03-deep-dive-01-ip-routing-tables.md)**: The killer application for radix trees in network infrastructure and longest prefix matching

### 💻 Implementation
- **[Rust Implementation](04-rust-implementation.md)**: Complete, production-quality radix tree with insertion, search, and prefix operations

---

**Learning Outcome**: After completing this tutorial, you'll understand how radix trees achieve superior memory efficiency through path compression, when to choose them over standard tries, and how to implement them effectively in systems requiring fast prefix-based operations.