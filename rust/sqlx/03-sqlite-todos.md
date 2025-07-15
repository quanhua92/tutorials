# SQLite Todo App: Embedded Database Simplicity

> **Source Code**: [examples/sqlite/todos](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/sqlite/todos)

## The Core Concept: Why This Example Exists

**The Problem:** Not every application needs a full database server. Sometimes you want the power of SQL without the operational complexity of PostgreSQL or MySQL. Desktop applications, mobile apps, and simple web services often need an embedded database that "just works."

**The Solution:** SQLite provides a full SQL database as a library, and SQLx makes it feel as natural to use as any other database. This example shows how SQLx handles SQLite's unique characteristics while maintaining the same ergonomic API you'd use with server-based databases.

## Practical Walkthrough: Code Breakdown

### SQLite Schema Simplicity (`migrations/20200718111257_todos.sql`)

```sql
CREATE TABLE IF NOT EXISTS todos
(
    id          INTEGER PRIMARY KEY NOT NULL,
    description TEXT                NOT NULL,
    done        BOOLEAN             NOT NULL DEFAULT 0
);
```

SQLite's approach reflects its embedded nature:
- `INTEGER PRIMARY KEY` automatically becomes an auto-incrementing row ID
- `TEXT` for all string data (SQLite has no length limits)
- `BOOLEAN` is actually stored as integers (0/1), but SQLx handles the mapping

### Connection Acquisition Pattern (`main.rs:46-61`)

```rust
async fn add_todo(pool: &SqlitePool, description: String) -> anyhow::Result<i64> {
    let mut conn = pool.acquire().await?;

    let id = sqlx::query!(/* ... */)
        .execute(&mut *conn)
        .await?
        .last_insert_rowid();

    Ok(id)
}
```

Notice the explicit connection acquisition here. While other functions use the pool directly, this function acquires a specific connection. This demonstrates SQLx's flexibility - you can work at either level.

### SQLite Parameter Binding (`main.rs:49-58`)

```rust
sqlx::query!(
    r#"
INSERT INTO todos ( description )
VALUES ( ?1 )
    "#,
    description
)
```

SQLite uses numbered parameters like `?1`, `?2`, etc. This is similar to PostgreSQL's `$1`, `$2` but with different syntax. SQLx automatically handles the conversion from your Rust variables.

### The `last_insert_rowid()` Method

```rust
.execute(&mut *conn)
.await?
.last_insert_rowid();
```

SQLite provides `last_insert_rowid()` to get the ID of the most recently inserted row. This is SQLite's equivalent to:
- MySQL's `last_insert_id()`
- PostgreSQL's `RETURNING` clause

### Boolean Type Mapping

```rust
for rec in recs {
    println!(
        "- [{}] {}: {}",
        if rec.done { "x" } else { " " },  // Works like PostgreSQL!
        rec.id,
        &rec.description,
    );
}
```

Despite SQLite storing booleans as integers (0/1), SQLx automatically maps them to Rust's `bool` type. Your code looks the same as the PostgreSQL version.

### Embedded Database Connection Strings

SQLite connection strings are quite different:
```
postgresql://user:pass@host:port/database  # Network connection
mysql://user:pass@host:port/database       # Network connection  
sqlite:///path/to/database.db              # File path
sqlite::memory:                            # In-memory database
```

The SQLite versions point to files or use special keywords like `:memory:`.

## Mental Model: Thinking in SQLite + SQLx

### SQLite as a File Format

Think of SQLite not as a database server, but as a sophisticated file format:

```
Regular files:     application → file system → disk
SQLite:           application → SQLite library → file system → disk
Network databases: application → network → database server → disk
```

The SQLite library handles all the database operations locally, which means:
- **No network latency**
- **No connection failures** (beyond disk issues)
- **ACID transactions** even in a single file
- **Concurrent readers** but exclusive writers

### Connection Pooling in SQLite

SQLite's connection pooling is different from server databases:

```
PostgreSQL/MySQL Pool:
[App] ← pool manages → [Conn1, Conn2, Conn3] → Network → [Database Server]

SQLite Pool:
[App] ← pool manages → [Handle1, Handle2, Handle3] → [SQLite Library] → [File]
```

Multiple handles can read simultaneously, but SQLite serializes writes. The pool still provides value for managing concurrent access patterns.

### Type System Philosophy

SQLite has a unique type system called "dynamic typing with type affinity":
- Columns have suggested types, but can store other types
- SQLx enforces the schema types at compile time
- This gives you both SQLite's flexibility and Rust's type safety

### Why SQLite + SQLx Works Well

1. **Zero configuration**: No database server to install or configure
2. **Single file deployment**: Database travels with your application
3. **Full SQL support**: Complex queries, transactions, indexes all work
4. **Type safety**: SQLx adds compile-time guarantees to SQLite's flexibility

### Connection Patterns

SQLx provides multiple ways to work with SQLite:

```rust
// Pool (recommended for most use cases)
let pool = SqlitePool::connect("sqlite:database.db").await?;
sqlx::query!("SELECT * FROM todos").fetch_all(&pool).await?;

// Individual connection
let mut conn = SqliteConnection::connect("sqlite:database.db").await?;
sqlx::query!("SELECT * FROM todos").fetch_all(&mut conn).await?;

// Acquired connection from pool  
let mut conn = pool.acquire().await?;
sqlx::query!("SELECT * FROM todos").fetch_all(&mut *conn).await?;
```

### Further Exploration

Try these SQLite-specific features:

1. **In-memory databases**: Change your DATABASE_URL to `sqlite::memory:` for ultra-fast temporary storage
2. **Attach multiple databases**: Use `ATTACH DATABASE` to work with multiple SQLite files simultaneously
3. **JSON extensions**: Modern SQLite versions have excellent JSON support
4. **Full-text search**: SQLite's FTS5 extension provides powerful search capabilities

Each of these demonstrates how SQLite brings server-database features to an embedded context, and how SQLx makes them accessible with the same ergonomic API.