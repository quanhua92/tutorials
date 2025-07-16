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

**Next Steps**: After completing this tutorial, consider exploring related patterns like CQRS, Saga Pattern for distributed transactions, and Event Streaming platforms like Apache Kafka for large-scale event processing.