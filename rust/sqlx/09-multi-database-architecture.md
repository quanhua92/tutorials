# Multi-Database Architecture with SQLx

> **Source Code**: [examples/postgres/multi-database](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/postgres/multi-database)

## The Core Concept: Why This Example Exists

**The Problem:** Large applications often need to separate concerns into distinct databases or schemas. You might have an accounts system, a payments processor, and application-specific data that should be managed independently. Each system has its own migrations, schemas, and lifecycle, but they need to work together in a coordinated way.

**The Solution:** This example demonstrates how to structure a multi-database application using SQLx with separate schema ownership, independent migration management, and coordinated transactions across multiple database contexts. It shows how to build modular systems that can be developed and deployed independently while maintaining data consistency.

## Practical Walkthrough: Code Breakdown

### Multi-Database Architecture

```
Main Application (public schema)
├── purchases table
├── Main business logic
└── Coordinates between subsystems

Accounts Subsystem (accounts schema)
├── accounts.account table
├── accounts.session table  
├── Authentication logic
└── Session management

Payments Subsystem (payments schema)
├── payments.payment table
├── Payment processing logic
└── Financial record keeping
```

### Independent `sqlx.toml` Configuration

Each subsystem has its own configuration:

**Main application `sqlx.toml`:**
```toml
[database]
# Uses main database with public schema
migrate.migrations-dir = "src/migrations"
```

**Accounts subsystem `accounts/sqlx.toml`:**
```toml
[database]
# Separate database for accounts
schema = "accounts"
```

**Payments subsystem `payments/sqlx.toml`:**
```toml
[database]
# Separate database for payments
schema = "payments"
```

This separation allows each subsystem to:
- Manage its own migrations independently
- Use different database URLs
- Evolve schemas without affecting other systems
- Be deployed and versioned separately

### Subsystem Manager Pattern (`accounts/src/lib.rs`)

```rust
pub struct AccountsManager {
    db: PgPool,
}

impl AccountsManager {
    pub async fn setup(
        database_url: Url,
        max_connections: u32,
    ) -> Result<Self, Error> {
        let db = PgPoolOptions::new()
            .max_connections(max_connections)
            .connect(database_url.as_str())
            .await?;

        Ok(AccountsManager { db })
    }

    pub async fn create(
        &self,
        email: &str,
        password: String,
    ) -> Result<AccountId, Error> {
        // Hash password in background thread (CPU-intensive)
        let password_hash = tokio::task::spawn_blocking(move || {
            argon2::hash_encoded(password.as_bytes(), salt, &config)
        })
        .await??;

        let account_id = sqlx::query_scalar!(
            r#"
            INSERT INTO accounts.account (email, password_hash)
            VALUES ($1, $2)
            RETURNING account_id
            "#,
            email,
            password_hash
        )
        .fetch_one(&self.db)
        .await?;

        Ok(AccountId(account_id))
    }
}
```

Key patterns:
- **Encapsulated database access**: Each manager owns its database pool
- **Schema-qualified queries**: `accounts.account` explicitly references the schema
- **Background processing**: Password hashing happens in a separate thread
- **Type-safe IDs**: `AccountId` wrapper prevents mixing different ID types

### Cross-System Coordination (`main.rs:48-57`)

```rust
// Main application manages the overall transaction
let mut txn = conn.begin().await?;

let account_id = accounts
    .create(&user_email, user_password.clone())
    .await
    .wrap_err("error creating account")?;

// Could create application-specific records here
// that depend on the account existing

txn.commit().await?;
```

This demonstrates the coordination pattern:
- **Main application** controls the overall transaction
- **Subsystems** handle their own internal operations
- **Coordination points** ensure consistency across systems

### Session Management Pattern (`accounts/src/lib.rs`)

```rust
pub async fn create_session(
    &self,
    email: &str,
    password: String,
) -> Result<Session, Error> {
    // First, verify the password
    let account = sqlx::query!(
        "SELECT account_id, password_hash FROM accounts.account WHERE email = $1",
        email
    )
    .fetch_optional(&self.db)
    .await?
    .ok_or(Error::InvalidCredentials)?;

    // Verify password (in background thread)
    let is_valid = tokio::task::spawn_blocking(move || {
        argon2::verify_encoded(&account.password_hash, password.as_bytes())
    })
    .await??;

    if !is_valid {
        return Err(Error::InvalidCredentials);
    }

    // Create session token
    let session_token = generate_session_token();
    
    sqlx::query!(
        r#"
        INSERT INTO accounts.session (account_id, session_token, expires_at)
        VALUES ($1, $2, $3)
        "#,
        account.account_id,
        session_token,
        expires_at
    )
    .execute(&self.db)
    .await?;

    Ok(Session {
        session_token: SessionToken(session_token),
        account_id: AccountId(account.account_id),
        expires_at,
    })
}
```

Security best practices:
- **Password verification**: Uses secure hashing algorithms
- **Background processing**: Prevents blocking the async runtime
- **Session tokens**: Cryptographically secure random tokens
- **Expiration**: Sessions have defined lifetimes

### Cross-System Data Flow (`main.rs:89-115`)

```rust
// 1. Authenticate using accounts system
let account_id = accounts
    .auth_session(&session.session_token.0)
    .await?
    .ok_or_eyre("session does not exist")?;

// 2. Process payment using payments system
let payment = payments
    .create(account_id, "USD", purchase_amount)
    .await?;

// 3. Record purchase in main application
let purchase_id = sqlx::query_scalar!(
    "insert into purchase(account_id, payment_id, amount) values ($1, $2, $3) returning purchase_id",
    account_id.0,
    payment.payment_id.0,
    purchase_amount
)
.fetch_one(&mut conn)
.await?;
```

This flow demonstrates:
- **Authentication**: Verify user identity through accounts system
- **Payment processing**: Handle financial transaction through payments system
- **Business logic**: Record the relationship in the main application
- **Type safety**: Strong types prevent mixing different ID types

## Mental Model: Thinking in Multi-Database Systems

### Schema Ownership Model

```
Database: example-app
├── Schema: public (main app)
│   ├── purchase table
│   └── Main business logic
├── Schema: accounts 
│   ├── account table
│   ├── session table
│   └── Authentication logic
└── Schema: payments
    ├── payment table
    └── Financial logic
```

Each schema is owned by a specific subsystem, creating clear boundaries and responsibilities.

### The Manager Pattern

```
Application Layer
       ↓
┌─────────────┬─────────────┬─────────────┐
│ MainApp     │ Accounts    │ Payments    │
│ Manager     │ Manager     │ Manager     │
├─────────────┼─────────────┼─────────────┤
│ PgPool      │ PgPool      │ PgPool      │
│ (public)    │ (accounts)  │ (payments)  │
└─────────────┴─────────────┴─────────────┘
       ↓             ↓             ↓
   PostgreSQL   PostgreSQL   PostgreSQL
   (same or     (same or     (same or
   different    different    different
   instance)    instance)    instance)
```

Each manager encapsulates its database operations and provides a clean API to the application layer.

### Transaction Coordination Strategies

**Option 1: Application-Level Coordination** (shown in example)
```rust
// Main app controls overall transaction
let mut txn = main_db.begin().await?;
let result1 = subsystem1.operation().await?;
let result2 = subsystem2.operation().await?;
txn.commit().await?;
```

**Option 2: Saga Pattern** (for distributed databases)
```rust
// Each operation can be compensated
match accounts.create_account().await {
    Ok(account_id) => {
        match payments.create_wallet(account_id).await {
            Ok(_) => Ok(()),
            Err(e) => {
                accounts.delete_account(account_id).await?;
                Err(e)
            }
        }
    }
    Err(e) => Err(e),
}
```

### Migration Management

Each subsystem manages its own migrations:

```bash
# Deploy accounts system
cd accounts && sqlx migrate run

# Deploy payments system  
cd payments && sqlx migrate run

# Deploy main application
sqlx migrate run
```

This allows:
- **Independent deployment** of subsystems
- **Version control** of schema changes per subsystem
- **Rollback capabilities** for individual subsystems
- **Development isolation** - teams can work independently

### Why Multi-Database Architecture Works Well

1. **Separation of Concerns**: Each subsystem has a single responsibility
2. **Independent Scaling**: Database resources can be allocated per subsystem
3. **Team Autonomy**: Different teams can own different subsystems
4. **Technology Flexibility**: Subsystems could use different databases if needed
5. **Security Boundaries**: Different access controls for different data types
6. **Deployment Independence**: Subsystems can be deployed separately

### Further Exploration

To extend this architecture:

1. **Event-Driven Architecture**: Use PostgreSQL `LISTEN/NOTIFY` for subsystem communication
2. **Read Replicas**: Route read-only queries to replica databases
3. **Connection Pooling**: Implement shared connection pools for related subsystems
4. **Distributed Transactions**: Use 2-phase commit for strong consistency
5. **Cross-Schema Views**: Create views that join data across schemas
6. **Monitoring**: Implement per-subsystem metrics and health checks

Example of event-driven communication:
```rust
// In payments subsystem
sqlx::query!("SELECT pg_notify('payment_created', $1)", payment_id)
    .execute(&self.db).await?;

// In main application
let mut listener = PgListener::connect(&database_url).await?;
listener.listen("payment_created").await?;
// Handle payment notifications
```

This architecture demonstrates how SQLx scales from single-database applications to complex, multi-database systems while maintaining type safety and clear separation of concerns.