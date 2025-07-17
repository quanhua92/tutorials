# Event Sourcing: The Unforgettable History

Event Sourcing is an architectural pattern that stores the state of an application as a sequence of immutable events rather than just the current state. Instead of updating records in place, every change is captured as an event that describes what happened, when it happened, and any relevant context.

## Summary

Traditional CRUD systems suffer from "state amnesia"—they only know what the data looks like now, not how it got that way. Event Sourcing solves this by treating events as the source of truth. Your application's current state becomes a derived view, calculated by replaying all the events that have occurred.

This approach provides several powerful benefits:
- **Complete audit trail**: Every change is recorded with full context
- **Time travel debugging**: Reconstruct system state at any point in history  
- **Rich business intelligence**: Analyze patterns and behaviors from the event stream
- **Natural scalability**: Multiple optimized read models can be built from the same events

The trade-offs include increased storage requirements, complexity in reading data, and eventual consistency between the event stream and derived views.

## Table of Contents

### Core Concepts
- [**01-concepts-01-the-core-problem.md**](./01-concepts-01-the-core-problem.md) - Why traditional CRUD systems lose valuable business intelligence and how this creates fundamental problems for audit trails, debugging, and data recovery.

- [**01-concepts-02-the-guiding-philosophy.md**](./01-concepts-02-the-guiding-philosophy.md) - The philosophical shift from storing "what is" to storing "what happened"—treating events as immutable facts and deriving current state through event replay.

- [**01-concepts-03-key-abstractions.md**](./01-concepts-03-key-abstractions.md) - The building blocks of Event Sourcing: Events, Event Streams, Projections, Aggregates, and the Event Store, with practical analogies and examples.

### Practical Guides  
- [**02-guides-01-modeling-a-shopping-cart.md**](./02-guides-01-modeling-a-shopping-cart.md) - A hands-on guide that models a shopping cart using events like `CartCreated`, `ItemAdded`, and `CartCheckedOut`, showing how to reconstruct current state and create specialized projections.

### Deep Dives
- [**03-deep-dive-01-event-sourcing-and-cqrs.md**](./03-deep-dive-01-event-sourcing-and-cqrs.md) - Explores the natural partnership between Event Sourcing and CQRS (Command Query Responsibility Segregation), including projection patterns, temporal queries, and advanced optimization techniques.

### Implementation
- [**04-rust-implementation.md**](./04-rust-implementation.md) - A complete, working implementation of an event-sourced shopping cart system in Rust, demonstrating aggregates, event stores, business rule validation, and the repository pattern.

---

## 📈 Next Steps

After mastering event sourcing fundamentals, consider these specialized learning paths based on your career focus:

### 🎯 Recommended Learning Path

**Based on your interests and goals:**

#### For Domain-Driven Design Practitioners
- **Next**: [CQRS: Command Query Responsibility Segregation](../cqrs-command-query-responsibility-segregation/README.md) - The natural companion to event sourcing for separating read and write models
- **Then**: [Saga Pattern: The Distributed Transaction Alternative](../saga-pattern-the-distributed-transaction-alternative/README.md) - Coordinate long-running business processes across multiple aggregates
- **Advanced**: [Domain Events: The Business Language Bridge](../domain-events-the-business-language-bridge/README.md) - Build event-driven domain models that speak business language

#### For Data Engineers
- **Next**: [Append-Only Logs: The Immutable Ledger](../append-only-logs/README.md) - Understand the storage foundations that make event sourcing possible
- **Then**: [Write-Ahead Logging (WAL): Durability without Delay](../write-ahead-logging-wal-durability-without-delay/README.md) - Learn how databases ensure event durability
- **Advanced**: [Materialized Views: The Pre-Calculated Answer](../materialized-views-the-pre-calculated-answer/README.md) - Build efficient read models from event streams

#### For System Architects
- **Next**: [Event Streaming: The Real-Time Data Pipeline](../event-streaming-the-real-time-data-pipeline/README.md) - Scale event sourcing with Apache Kafka and stream processing
- **Then**: [CRDTs: Agreeing Without Asking](../crdts-agreeing-without-asking/README.md) - Build conflict-free event merging for distributed systems
- **Advanced**: [Replication: Don't Put All Your Eggs in One Basket](../replication-dont-put-all-your-eggs-in-one-basket/README.md) - Distribute event stores across multiple nodes

### 🔗 Alternative Learning Paths

- **Transaction Management**: [Two-Phase Commit: The Distributed Transaction](../two-phase-commit-the-distributed-transaction/README.md), [Eventual Consistency: The Art of Agreeing to Disagree](../eventual-consistency-the-art-of-agreeing-to-disagree/README.md)
- **Storage Patterns**: [Delta Compression: Storing Only What Changed](../delta-compression/README.md), [Columnar Storage: Querying at Ludicrous Speed](../columnar-storage/README.md)
- **Real-Time Processing**: [Stream Processing: The Real-Time Analytics Engine](../stream-processing-the-real-time-analytics-engine/README.md), [Complex Event Processing: The Pattern Detective](../complex-event-processing-the-pattern-detective/README.md)

### 📚 Prerequisites for Advanced Topics

- **Foundations Complete**: ✅ You understand event sourcing, aggregates, and event replay
- **Difficulty Level**: Intermediate → Advanced
- **Estimated Time**: 2-3 weeks per next tutorial depending on implementation complexity

Event sourcing is the unforgettable history that captures every change as an immutable event. Master these concepts, and you'll have the power to build systems that never lose context and can reconstruct any historical state.