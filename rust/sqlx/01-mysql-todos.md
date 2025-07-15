# Building a CLI Todo App with SQLx and MySQL

> **Source Code**: [examples/mysql/todos](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/mysql/todos)

## The Core Concept: Why This Example Exists

**The Problem:** Most database applications need to perform the fundamental CRUD operations (Create, Read, Update, Delete) safely and efficiently. Writing raw SQL can be error-prone and vulnerable to SQL injection, while heavyweight ORMs can add unnecessary complexity and performance overhead.

**The Solution:** SQLx provides compile-time checked SQL queries that give you the power of raw SQL with the safety of compile-time verification. This todo app demonstrates SQLx's core philosophy: write SQL as SQL, but get Rust-level safety guarantees at compile time.

## Practical Walkthrough: Code Breakdown

### Database Schema (`migrations/20200718111257_todos.sql`)

```sql
CREATE TABLE IF NOT EXISTS todos
(
    id          BIGINT UNSIGNED PRIMARY KEY NOT NULL AUTO_INCREMENT,
    description TEXT    NOT NULL,
    done        BOOLEAN NOT NULL DEFAULT FALSE
);
```

The schema is intentionally simple, showcasing how SQLx handles MySQL's specific types:
- `BIGINT UNSIGNED` for IDs (maps to Rust's `u64`)
- `TEXT` for variable-length strings 
- `BOOLEAN` (which MySQL stores as `TINYINT(1)`, mapping to Rust's `i8`)

### Project Dependencies (`Cargo.toml`)

```toml
[dependencies]
anyhow = "1.0"
sqlx = { path = "../../../", features = [ "mysql", "runtime-tokio", "tls-native-tls" ] }
clap = { version = "4", features = ["derive"] }
tokio = { version = "1.20.0", features = ["rt", "macros"]}
```

Key SQLx features enabled:
- `mysql`: Database driver for MySQL/MariaDB
- `runtime-tokio`: Async runtime integration
- `tls-native-tls`: Secure connections

### Connection Management (`main.rs:20`)

```rust
let pool = MySqlPool::connect(&env::var("DATABASE_URL")?).await?;
```

SQLx uses connection pooling by default. The `MySqlPool` automatically manages multiple database connections, handling connection reuse, timeouts, and cleanup. This single line gives you production-ready connection management.

### The Magic of `query!` Macro

#### Adding a Todo (`main.rs:47-58`)

```rust
let todo_id = sqlx::query!(
    r#"
INSERT INTO todos ( description )
VALUES ( ? )
    "#,
    description
)
.execute(pool)
.await?
.last_insert_id();
```

What makes this special:
- **Compile-time verification**: SQLx connects to your database at build time to verify this SQL is valid
- **Type safety**: The `?` parameter is automatically type-checked against the `description` argument
- **Zero runtime overhead**: No query parsing or building at runtime

#### Updating Records (`main.rs:62-74`)

```rust
let rows_affected = sqlx::query!(
    r#"
UPDATE todos
SET done = TRUE
WHERE id = ?
    "#,
    id
)
.execute(pool)
.await?
.rows_affected();

Ok(rows_affected > 0)
```

The function returns a boolean indicating success by checking `rows_affected`. This pattern is common for validating that operations affected the expected records.

#### Querying Data (`main.rs:78-100`)

```rust
let recs = sqlx::query!(
    r#"
SELECT id, description, done
FROM todos
ORDER BY id
    "#
)
.fetch_all(pool)
.await?;
```

The `query!` macro generates an anonymous struct with fields matching your SELECT columns. Each `rec` has `.id`, `.description`, and `.done` fields with appropriate Rust types.

### MySQL-Specific Considerations (`main.rs:88-96`)

```rust
// NOTE: Booleans in MySQL are stored as `TINYINT(1)` / `i8`
//       0 = false, non-0 = true
for rec in recs {
    println!(
        "- [{}] {}: {}",
        if rec.done != 0 { "x" } else { " " },
        rec.id,
        &rec.description,
    );
}
```

This showcases SQLx's database-specific type mapping. MySQL's `BOOLEAN` type is actually a `TINYINT(1)`, so SQLx maps it to `i8` rather than Rust's `bool`.

## Mental Model: Thinking in SQLx

### The Compile-Time Database Connection

Think of SQLx as having two phases:

```
Compile Time: SQLx ←→ Development Database
Runtime:      Your App ←→ Production Database
```

At compile time, SQLx connects to your development database to:
1. Validate SQL syntax
2. Check that tables and columns exist  
3. Verify parameter types match
4. Generate appropriate Rust types for results

This "time-shifted" approach gives you both flexibility and safety.

### Connection Pools as Resource Managers

SQLx's `Pool` is like a parking garage for database connections:
- **Acquisition**: When you need a connection, the pool either gives you an idle one or creates a new one (up to the limit)
- **Return**: When you're done, the connection goes back to the pool for reuse
- **Cleanup**: The pool automatically closes idle connections and handles failures

### Why It's Designed This Way

SQLx chooses compile-time verification over runtime flexibility because:
1. **Database schemas change infrequently** - most apps have stable schemas
2. **Catching errors early is cheaper** - fixing a type mismatch at compile time vs. in production
3. **Performance matters** - zero-cost abstractions mean no runtime query parsing

### Further Exploration

Try modifying the schema to add a `created_at TIMESTAMP` column. Notice how SQLx will:
1. Require you to update your INSERT query
2. Automatically include the new field in your SELECT results
3. Map MySQL's TIMESTAMP to an appropriate Rust time type

This demonstrates SQLx's core value: your database schema becomes part of your type system.