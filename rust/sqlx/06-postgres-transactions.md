# Understanding Database Transactions with SQLx

> **Source Code**: [examples/postgres/transaction](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/postgres/transaction)

## The Core Concept: Why This Example Exists

**The Problem:** In multi-step database operations, you often need all operations to succeed or fail together. Without proper transaction handling, partial failures can leave your database in an inconsistent state. Additionally, concurrent operations can interfere with each other in unexpected ways.

**The Solution:** Database transactions provide ACID guarantees (Atomicity, Consistency, Isolation, Durability). SQLx makes transaction management explicit and type-safe, with automatic rollback on drop and clear patterns for commit vs. rollback scenarios.

## Practical Walkthrough: Code Breakdown

### Transaction Creation and Scoping (`main.rs:31, 44, 56`)

```rust
let mut transaction = pool.begin().await?;
```

This single line:
- Acquires a connection from the pool
- Begins a database transaction (`BEGIN`)
- Returns a `Transaction<'_, Postgres>` that owns the connection
- Sets up automatic rollback if the transaction is dropped without committing

### Working Within Transactions (`main.rs:3-25`)

```rust
async fn insert_and_verify(
    transaction: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    test_id: i64,
) -> Result<(), Box<dyn std::error::Error>> {
    query!(
        r#"INSERT INTO todos (id, description)
        VALUES ( $1, $2 )
        "#,
        test_id,
        "test todo"
    )
    .execute(&mut **transaction)  // Note the double dereference
    .await?;

    // Verify within the same transaction
    let _ = query!(r#"SELECT FROM todos WHERE id = $1"#, test_id)
        .fetch_one(&mut **transaction)
        .await?;

    Ok(())
}
```

Key patterns here:
- **Double dereference**: `&mut **transaction` is needed to access the underlying connection
- **Isolation demonstration**: The SELECT can see the INSERT within the same transaction
- **Transaction passing**: Pass transactions by mutable reference to maintain ownership

### Three Transaction Outcomes

#### 1. Explicit Rollback (`main.rs:27-38`)

```rust
async fn explicit_rollback_example(
    pool: &sqlx::PgPool,
    test_id: i64,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut transaction = pool.begin().await?;

    insert_and_verify(&mut transaction, test_id).await?;

    transaction.rollback().await?;  // Explicit rollback

    Ok(())
}
```

Explicit rollback is useful when:
- You detect a business logic error
- You want to test operations without persisting changes
- You need fine-grained control over transaction lifetime

#### 2. Implicit Rollback (Drop) (`main.rs:40-50`)

```rust
async fn implicit_rollback_example(
    pool: &sqlx::PgPool,
    test_id: i64,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut transaction = pool.begin().await?;

    insert_and_verify(&mut transaction, test_id).await?;

    // Transaction dropped here -> automatic rollback
    Ok(())
}
```

This demonstrates SQLx's safety feature: transactions automatically rollback when dropped unless explicitly committed. This prevents accidental commits.

#### 3. Explicit Commit (`main.rs:52-63`)

```rust
async fn commit_example(
    pool: &sqlx::PgPool,
    test_id: i64,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut transaction = pool.begin().await?;

    insert_and_verify(&mut transaction, test_id).await?;

    transaction.commit().await?;  // Persist changes

    Ok(())
}
```

Only explicit commits persist changes. This makes SQLx transactions safe by default.

### Verification Outside Transactions (`main.rs:81-103`)

```rust
// Check visibility after rollback
let inserted_todo = query!(r#"SELECT FROM todos WHERE id = $1"#, test_id)
    .fetch_one(&pool)  // Using pool, not transaction
    .await;

assert!(inserted_todo.is_err());  // Should not exist after rollback

// Check visibility after commit  
let inserted_todo = query!(r#"SELECT FROM todos WHERE id = $1"#, test_id)
    .fetch_one(&pool)
    .await;

assert!(inserted_todo.is_ok());  // Should exist after commit
```

This verifies transaction isolation: changes are only visible outside the transaction after commit.

## Mental Model: Thinking in Transactions

### The Transaction Boundary

```
Outside Transaction:     [Shared, Persistent State]
                              ↑
                         BEGIN Transaction
                              ↓
Inside Transaction:      [Isolated, Temporary State]
                              ↓
                       COMMIT or ROLLBACK
                              ↓
Outside Transaction:     [Updated or Unchanged State]
```

Everything inside the transaction boundary is isolated from other operations until commit.

### SQLx Transaction Safety

SQLx enforces transaction safety through Rust's type system:

```rust
Transaction<'_, Postgres>  // Owns the connection
  ↓
Drop without commit → Automatic rollback
Explicit commit()   → Changes persisted
Explicit rollback() → Changes discarded
```

This prevents the common mistake of forgetting to commit or rollback.

### Connection Lifecycle in Transactions

```
Pool → acquire() → Connection → begin() → Transaction
                                             ↓
                                        commit()/rollback()
                                             ↓
                                    Connection → back to Pool
```

The transaction owns the connection exclusively, preventing interference from other operations.

### ACID Properties in Practice

**Atomicity**: Either all operations succeed or none do
```rust
// If any operation fails, the entire transaction rolls back
transaction.execute("INSERT ...").await?;
transaction.execute("UPDATE ...").await?;
transaction.execute("DELETE ...").await?;
transaction.commit().await?; // All or nothing
```

**Consistency**: Database constraints are enforced
```rust
// Foreign key constraints, unique constraints, etc. are checked
```

**Isolation**: Concurrent transactions don't interfere
```rust
// Changes in one transaction aren't visible to others until commit
```

**Durability**: Committed changes survive system failures
```rust
// After commit(), changes are written to disk
```

### Error Handling Patterns

```rust
let mut tx = pool.begin().await?;

match risky_operation(&mut tx).await {
    Ok(_) => tx.commit().await?,
    Err(e) => {
        tx.rollback().await?; // Explicit error handling
        return Err(e);
    }
}
```

Or using the `?` operator with automatic rollback:
```rust
let mut tx = pool.begin().await?;
risky_operation(&mut tx).await?; // Auto-rollback on error
tx.commit().await?; // Only reached if everything succeeded
```

### Why SQLx Transactions Work Well

1. **Type safety**: Can't accidentally use wrong connection
2. **Automatic cleanup**: Rollback on drop prevents partial commits
3. **Explicit commits**: Makes transaction boundaries clear
4. **Connection pooling**: Efficient resource management
5. **Async support**: Non-blocking transaction operations

### Further Exploration

Try these advanced transaction patterns:

1. **Nested transactions with savepoints**:
```rust
let mut tx = pool.begin().await?;
let savepoint = tx.begin().await?; // Nested transaction
// ... operations ...
savepoint.rollback().await?; // Rollback to savepoint
tx.commit().await?; // Commit outer transaction
```

2. **Read-only transactions** for consistency:
```rust
let mut tx = pool.begin().await?;
tx.execute("SET TRANSACTION READ ONLY").await?;
// All reads will see consistent snapshot
```

3. **Transaction isolation levels**:
```rust
let mut tx = pool.begin().await?;
tx.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE").await?;
// Highest isolation level
```

4. **Bulk operations with periodic commits**:
```rust
for chunk in data.chunks(1000) {
    let mut tx = pool.begin().await?;
    for item in chunk {
        // Process item
    }
    tx.commit().await?; // Commit each chunk
}
```

This demonstrates how SQLx makes complex transaction patterns safe and ergonomic while preserving the full power of PostgreSQL's transaction system.