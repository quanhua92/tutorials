# Fred.rs Tutorials

A comprehensive tutorial series for the Fred Redis client library, designed to take you from basic concepts to production-ready implementations.

## Philosophy

These tutorials follow the **Feynman Teaching Method** - explaining complex concepts through simple analogies and building deep, intuitive understanding. Each tutorial focuses on the "why" behind Redis patterns, not just the "how."

## Learning Path

### 🚀 **Getting Started**
Start here if you're new to Fred or want to understand the fundamentals:

1. **[Basic Redis Client](01-basic-redis-client.md)**
   - Your first connection to Redis
   - Client configuration and initialization
   - Type-safe command execution
   - Error handling patterns

2. **[Client Pools](02-client-pools.md)**
   - Scaling connections for high throughput
   - Round-robin load balancing
   - When to use pools vs single clients

### 📡 **Communication Patterns**
Learn Redis's core communication paradigms:

3. **[Publish-Subscribe](03-publish-subscribe.md)**
   - Real-time messaging patterns
   - Channel subscriptions and message handling
   - Surviving network interruptions
   - Regular clients vs SubscriberClient

4. **[Redis Streams](06-redis-streams.md)**
   - Event-driven architecture with persistence
   - Producer-consumer patterns
   - Message replay and ordering guarantees
   - Task communication in async applications

### ⚡ **Performance & Consistency**
Master Redis's advanced execution patterns:

5. **[Transactions](04-transactions.md)**
   - Atomic operations with MULTI/EXEC
   - When to use transactions vs alternatives
   - Type-safe result handling

6. **[Pipelining](05-pipelining.md)**
   - Optimizing network round-trips
   - Batch command execution
   - Error handling in pipelines

7. **[Lua Scripting](07-lua-scripting.md)**
   - Server-side logic execution
   - Atomic complex operations
   - Script caching and management
   - Redis Functions for modern deployments

### 🔍 **Data Discovery & Management**
Learn to work with large keyspaces efficiently:

8. **[Scanning Keys](08-scanning-keys.md)**
   - Safe keyspace iteration
   - Memory-conscious vs high-throughput scanning
   - Cluster scanning patterns
   - Custom cursor management

### 🏭 **Production Deployment**
Advanced features for real-world applications:

9. **[Advanced Features](09-advanced-features.md)**
   - TLS security configuration
   - Sentinel high availability
   - Monitoring and debugging tools
   - Dynamic connection scaling
   - Web framework integration
   - JSON data handling
   - Custom protocol access

## Tutorial Structure

Each tutorial follows a consistent three-part structure:

### **Part 1: The Core Concept**
- **The Problem**: What real-world challenge does this feature solve?
- **The Solution**: How Redis and Fred address this problem
- **Mental Framework**: High-level understanding before diving into code

### **Part 2: Practical Walkthrough**
- **Code Analysis**: Line-by-line explanation of example code
- **Key Concepts**: Important patterns and techniques demonstrated
- **Type Safety**: How Fred's Rust interface provides compile-time guarantees

### **Part 3: Mental Models & Deep Dives**
- **Analogies**: Real-world comparisons to make abstract concepts concrete
- **Design Rationale**: Why Redis and Fred work the way they do
- **Further Exploration**: Experiments and modifications to deepen understanding

## How to Use These Tutorials

### **If You're New to Redis:**
Start with tutorials 1-2 to understand basic concepts, then explore communication patterns (3-4) before diving into performance features.

### **If You Know Redis But Not Fred:**
Focus on the "Practical Walkthrough" sections to see Fred's Rust-specific patterns, especially type safety and async handling.

### **If You're Building Production Applications:**
Start with the basics but quickly move to tutorials 7-9, which cover patterns essential for production deployments.

### **If You're Performance-Focused:**
Tutorials 5-6 (Pipelining, Scripting) and sections of tutorial 9 (Dynamic Pools, Replica Scaling) will be most relevant.

## Example Code

All tutorial examples are based on the actual example files in the Fred repository at `/examples/`. You can run any example with:

```bash
cargo run --example basic
cargo run --features="subscriber-client" --example pubsub
cargo run --features="i-all" --example scan
```

## Key Concepts Covered

- **Type Safety**: How Fred leverages Rust's type system for Redis operations
- **Async Patterns**: Tokio integration and concurrent operation handling
- **Error Handling**: Robust error management in distributed systems
- **Performance**: Connection pooling, pipelining, and scaling strategies
- **Production Readiness**: Security, monitoring, and operational concerns
- **Protocol Understanding**: When to use low-level vs high-level interfaces

## Troubleshooting

If you encounter issues while following these tutorials:

1. **Check Feature Flags**: Many examples require specific Cargo features
2. **Redis Version**: Some features require specific Redis versions
3. **Network Setup**: Ensure Redis is accessible at the configured endpoints
4. **Dependencies**: Verify all required dependencies are in your Cargo.toml

## Contributing

Found an error or want to improve a tutorial? The tutorial source files are in `/docs/tutorials/` and follow standard Markdown formatting.

## Further Learning

After completing these tutorials, explore:
- **[Fred API Documentation](https://docs.rs/fred)** for comprehensive API reference
- **[Redis Documentation](https://redis.io/docs/)** for deeper Redis concepts
- **[Example Applications](../examples/)** for complete implementations
- **[Integration Tests](../tests/)** for advanced usage patterns

---

*These tutorials are designed to build lasting understanding, not just immediate functionality. Take time to experiment with the concepts and build your intuition for when and how to apply each pattern.*