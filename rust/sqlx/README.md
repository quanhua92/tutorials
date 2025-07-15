# SQLx Database Toolkit Tutorials

> **Source Repository**: [launchbadge/sqlx](https://github.com/launchbadge/sqlx)

This tutorial series explores SQLx, Rust's async SQL toolkit that provides compile-time checked queries without the complexity of an ORM. These tutorials are based on real examples from the SQLx repository and demonstrate practical patterns for building database-driven applications.

## What is SQLx?

SQLx is a Rust library that lets you write SQL as SQL while providing compile-time verification of your queries. It supports PostgreSQL, MySQL, and SQLite, offering the performance of raw SQL with the safety guarantees of Rust's type system.

## Tutorial Series

### 1. Database Fundamentals
- [**MySQL Todo App**](./01-mysql-todos.md) - Building a CLI todo application with MySQL, covering basic CRUD operations and migrations
- [**PostgreSQL Todo App**](./02-postgres-todos.md) - Same todo app using PostgreSQL, exploring database-specific features
- [**SQLite Todo App**](./03-sqlite-todos.md) - Lightweight SQLite implementation for embedded and local applications

### 2. Advanced PostgreSQL Features
- [**JSON Operations**](./04-postgres-json.md) - Working with JSON data types and queries in PostgreSQL
- [**Listen/Notify**](./05-postgres-listen-notify.md) - Real-time notifications using PostgreSQL's LISTEN/NOTIFY system
- [**Transaction Management**](./06-postgres-transactions.md) - Advanced transaction handling and isolation levels
- [**Query Files**](./07-postgres-query-files.md) - Organizing complex queries in separate SQL files

### 3. Production Applications
- [**Axum Social API**](./08-axum-social-api.md) - Building a RESTful social media API with Axum and PostgreSQL
- [**Multi-Database Architecture**](./09-multi-database-architecture.md) - Designing applications that work across multiple database backends

### 4. Advanced Topics
- [**SQLite Extensions**](./10-sqlite-extensions.md) - Leveraging SQLite's powerful extension ecosystem

## Key Learning Outcomes

By completing these tutorials, you'll understand:

- **Compile-time Query Verification**: How SQLx checks your SQL at compile time
- **Database Migrations**: Managing schema changes across environments
- **Async Database Operations**: Efficient async/await patterns with databases
- **Type Safety**: Mapping SQL types to Rust types safely
- **Connection Management**: Pooling and connection lifecycle management
- **Error Handling**: Robust error handling patterns for database operations
- **Testing Strategies**: Testing database code effectively

## Prerequisites

- Basic Rust knowledge (ownership, async/await, error handling)
- Basic SQL understanding
- Familiarity with at least one database system (MySQL, PostgreSQL, or SQLite)

## Getting Started

Each tutorial is self-contained and includes:
- Problem context and motivation
- Step-by-step code walkthrough
- Key insights and best practices
- Links to the original source code

Start with the [MySQL Todo App](./01-mysql-todos.md) for a gentle introduction to SQLx fundamentals, then explore the advanced topics based on your specific needs.