# PostgreSQL Todo App: Database-Native Features

> **Source Code**: [examples/postgres/todos](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/postgres/todos)

## The Core Concept: Why This Example Exists

**The Problem:** While the basic CRUD operations are similar across databases, each database has unique features and type systems. PostgreSQL, in particular, offers advanced features like `RETURNING` clauses, proper boolean types, and sophisticated parameter binding that can make applications more efficient and expressive.

**The Solution:** This example demonstrates how SQLx adapts to PostgreSQL's specific features while maintaining the same compile-time safety guarantees. You'll see how PostgreSQL's richer type system and SQL features translate into more natural Rust code.

## Practical Walkthrough: Code Breakdown

### PostgreSQL-Specific Schema (`migrations/20200718111257_todos.sql`)

```sql
CREATE TABLE IF NOT EXISTS todos
(
    id          BIGSERIAL PRIMARY KEY,
    description TEXT    NOT NULL,
    done        BOOLEAN NOT NULL DEFAULT FALSE
);
```

Key PostgreSQL differences from MySQL:
- `BIGSERIAL` auto-generates 64-bit integers (equivalent to `AUTO_INCREMENT BIGINT` in MySQL)
- `BOOLEAN` is a native type that maps directly to Rust's `bool`
- PostgreSQL's `TEXT` type has no length limit

### PostgreSQL Parameter Binding (`main.rs:46-58`)

```rust
let rec = sqlx::query!(
    r#"
INSERT INTO todos ( description )
VALUES ( $1 )
RETURNING id
    "#,
    description
)
.fetch_one(pool)
.await?;
```

Notice the key differences from MySQL:
- **Parameter syntax**: `$1` instead of `?` (PostgreSQL's native parameter format)
- **RETURNING clause**: PostgreSQL can return values from INSERT/UPDATE operations
- **fetch_one()**: Since we're returning data, we fetch the result instead of just executing

### The Power of RETURNING

Compare the MySQL approach:
```rust
// MySQL: Execute then get last_insert_id()
.execute(pool).await?.last_insert_id()
```

With PostgreSQL's approach:
```rust
// PostgreSQL: Get the ID directly from the INSERT
.fetch_one(pool).await?.id
```

PostgreSQL's `RETURNING` clause is more explicit and can return any columns, not just the ID. This is especially powerful for complex operations.

### Native Boolean Handling (`main.rs:87-94`)

```rust
for rec in recs {
    println!(
        "- [{}] {}: {}",
        if rec.done { "x" } else { " " },  // Direct boolean usage!
        rec.id,
        &rec.description,
    );
}
```

Unlike MySQL (which required `rec.done != 0`), PostgreSQL's native `BOOLEAN` type maps directly to Rust's `bool`. This creates more idiomatic Rust code.

### Type System Alignment

The PostgreSQL version demonstrates better type alignment:

| PostgreSQL Type | Rust Type | MySQL Equivalent | MySQL Rust Type |
|----------------|-----------|------------------|-----------------|
| `BIGSERIAL`    | `i64`     | `BIGINT AUTO_INCREMENT` | `u64` |
| `BOOLEAN`      | `bool`    | `BOOLEAN`/`TINYINT(1)` | `i8` |
| `TEXT`         | `String`  | `TEXT`           | `String` |

PostgreSQL's signed integers (`i64`) vs MySQL's unsigned (`u64`) reflect the databases' different design philosophies.

### Parameter Binding Styles

```rust
// PostgreSQL: Numbered parameters
sqlx::query!("UPDATE todos SET done = TRUE WHERE id = $1", id)

// MySQL equivalent would be:
// sqlx::query!("UPDATE todos SET done = TRUE WHERE id = ?", id)
```

PostgreSQL's numbered parameters (`$1`, `$2`, etc.) allow:
- Reusing the same parameter multiple times
- Clear indication of parameter order
- Better support for complex queries

## Mental Model: Thinking in PostgreSQL + SQLx

### PostgreSQL as a "Rich" Database

Think of PostgreSQL as a programming language in its own right:
- **Rich type system**: Arrays, JSON, custom types, enums
- **Advanced SQL features**: CTEs, window functions, RETURNING clauses
- **Extensibility**: Custom functions, operators, and data types

SQLx embraces this richness rather than abstracting it away.

### The RETURNING Pattern

RETURNING transforms INSERT/UPDATE/DELETE from "fire and forget" operations into data-producing queries:

```
Traditional approach:
INSERT → Execute → Query for result

PostgreSQL approach:
INSERT RETURNING → Get result directly
```

This pattern reduces round trips and ensures consistency.

### Type Mapping Philosophy

SQLx aims for the most natural mapping between database and Rust types:
- PostgreSQL `BOOLEAN` → Rust `bool` (perfect match)
- PostgreSQL arrays → Rust `Vec<T>` 
- PostgreSQL `JSON` → `serde_json::Value`

This creates code that feels natural in both contexts.

### Why PostgreSQL + SQLx Works Well

1. **Type richness**: PostgreSQL's sophisticated type system maps well to Rust's type system
2. **SQL expressiveness**: PostgreSQL's advanced SQL features reduce the need for application-level logic
3. **Compile-time verification**: SQLx can verify more sophisticated queries because PostgreSQL provides better introspection

### Further Exploration

Try extending this example with PostgreSQL-specific features:

1. **Add a `created_at TIMESTAMPTZ` column** and see how SQLx handles timezone-aware timestamps
2. **Use an ENUM for todo priority** (`CREATE TYPE priority AS ENUM ('low', 'medium', 'high')`)
3. **Store tags as a PostgreSQL array** (`tags TEXT[]`) and see how it maps to `Vec<String>`

Each of these features would be complex to implement in MySQL but is natural in PostgreSQL, demonstrating how SQLx adapts to each database's strengths.