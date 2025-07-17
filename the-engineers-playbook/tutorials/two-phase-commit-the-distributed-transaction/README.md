# Two-Phase Commit: The Distributed Transaction

## Summary

Two-Phase Commit (2PC) is a distributed algorithm that ensures atomicity across multiple independent systems. It solves the fundamental problem of coordinating transactions across distributed resources by using a "prepare then commit" approach.

The protocol operates through two distinct phases: first, a coordinator asks all participants if they can commit a transaction (prepare phase), and then, based on unanimous agreement, instructs all participants to either commit or abort (commit phase). This ensures that all participants make the same decision, maintaining system consistency.

While elegant in its simplicity, 2PC has a critical limitation: it can block indefinitely if the coordinator fails at the wrong time. This blocking problem makes it unsuitable for high-availability systems but still valuable in controlled environments where strong consistency is paramount.

## Table of Contents

### 1. Core Concepts
- **[The Core Problem](01-concepts-01-the-core-problem.md)** - Understanding the distributed transaction challenge and why it's hard to solve
- **[The Guiding Philosophy](01-concepts-02-the-guiding-philosophy.md)** - The "prepare then commit" approach and fundamental trade-offs  
- **[Key Abstractions](01-concepts-03-key-abstractions.md)** - Coordinators, participants, and transaction logs that make 2PC work

### 2. Practical Guides
- **[Simulating 2PC](02-guides-01-simulating-2pc.md)** - Building a working Two-Phase Commit implementation to understand the mechanics

### 3. Deep Dives
- **[The Blocking Problem](03-deep-dive-01-the-blocking-problem.md)** - Why 2PC can block indefinitely and how to handle coordinator failures

### 4. Implementation
- **[Rust Implementation](04-rust-implementation.md)** - Production-ready 2PC system with persistence, recovery, and error handling

---

## Quick Start

If you're new to distributed transactions, start with [The Core Problem](01-concepts-01-the-core-problem.md) to understand what 2PC solves and why it's needed.

For hands-on learning, jump to [Simulating 2PC](02-guides-01-simulating-2pc.md) to build your own implementation.

To understand the protocol's limitations, read [The Blocking Problem](03-deep-dive-01-the-blocking-problem.md).

For production use, see the [Rust Implementation](04-rust-implementation.md) for a complete, robust system.

## Key Takeaways

1. **2PC ensures atomicity** across distributed systems through unanimous voting
2. **The blocking problem** is 2PC's fundamental limitation - it can halt indefinitely
3. **Proper recovery mechanisms** are essential for production 2PC systems
4. **Modern alternatives** like Saga pattern exist for scenarios where blocking is unacceptable
5. **Use 2PC when** strong consistency is more important than high availability