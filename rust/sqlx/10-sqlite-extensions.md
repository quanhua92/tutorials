# Extending SQLite with Custom Functions and Extensions

> **Source Code**: [examples/sqlite/extension](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/sqlite/extension)

## The Core Concept: Why This Example Exists

**The Problem:** While SQLite is incredibly capable, sometimes you need functionality that's not built into the core engine. You might need specialized string processing, mathematical functions, network operations, or domain-specific calculations. Writing these in application code means multiple round trips and reduced performance.

**The Solution:** SQLite supports extensions that can add custom functions, collations, and virtual tables directly to the database engine. SQLx provides seamless integration with SQLite extensions, allowing you to use enhanced SQL capabilities while maintaining compile-time verification and type safety.

## Practical Walkthrough: Code Breakdown

### Extension Configuration for Development (`sqlx.toml`)

```toml
[database]
extensions = [
    { name = "ipaddr", path = "/tmp/sqlite3-lib/ipaddr" }
]
```

This configuration:
- **Loads the extension for SQLx CLI**: Enables `sqlx migrate` and `query!` macro verification
- **Specifies the extension path**: Can be absolute path or just the name if in library search path
- **Enables compile-time checking**: SQLx can verify queries that use extension functions

### Runtime Extension Loading (`main.rs:10-28`)

```rust
let opts = SqliteConnectOptions::from_str(&std::env::var("DATABASE_URL")?)?
    // Load extension at runtime for application execution
    .extension("/tmp/sqlite3-lib/ipaddr");

let db = SqlitePool::connect_with(opts).await?;
```

Key insights:
- **Dual configuration**: `sqlx.toml` for development, `SqliteConnectOptions` for runtime
- **Environment flexibility**: Development and production can use different extension paths
- **Path options**: Full path or just extension name if in system library path
- **Connection-level loading**: Extensions are loaded per connection/pool

### Schema Using Extension Functions (`migrations/20250203094951_addresses.sql`)

```sql
create table addresses (address text, family integer);

-- The `ipfamily` function is provided by the ipaddr extension
insert into addresses (address, family) values
  ('fd04:3d29:9f41::1', ipfamily('fd04:3d29:9f41::1')),  -- IPv6
  ('10.0.0.1', ipfamily('10.0.0.1')),                    -- IPv4
  ('10.0.0.2', ipfamily('10.0.0.2')),
  ('fd04:3d29:9f41::2', ipfamily('fd04:3d29:9f41::2'));
```

The `ipfamily()` function:
- **Returns 4 for IPv4 addresses**
- **Returns 6 for IPv6 addresses**
- **Provided by the ipaddr extension**
- **Available in both migrations and application queries**

### Using Extension Functions in Application Code (`main.rs:37-43`)

```rust
query!(
    "insert into addresses (address, family) values (?1, ipfamily(?1))",
    "10.0.0.10"
)
.execute(&db)
.await?;
```

This demonstrates:
- **Compile-time verification**: SQLx validates the `ipfamily()` function exists
- **Parameter binding**: The same IP address is used for both columns
- **Type safety**: SQLx ensures the function returns the expected type
- **Runtime execution**: The extension function runs inside the SQLite engine

### Extension Download Script (`download-extension.sh`)

```bash
#!/bin/bash
# Download and prepare the ipaddr extension

mkdir -p /tmp/sqlite3-lib
wget -O /tmp/sqlite3-lib/ipaddr.so \
  https://github.com/nalgeon/sqlean/releases/download/0.21.5/ipaddr.so
```

Production considerations:
- **Version pinning**: Specific extension versions for reproducibility
- **Dependency management**: Extensions are external dependencies
- **Platform specificity**: Extensions are compiled for specific platforms
- **Security**: Verify extension sources and checksums

## Mental Model: Thinking in SQLite Extensions

### Extension Architecture

```
Application Code
       ↓
SQLx + compile-time verification
       ↓
SQLite Engine + Loaded Extensions
       ↓
Extension Functions Available in SQL
```

Extensions become part of the SQL language, available everywhere SQL is used.

### Development vs Runtime Configuration

```
Development Time               Runtime
┌─────────────┐               ┌─────────────┐
│ sqlx.toml   │ ──────────→   │ Application │
│ extensions  │               │ .extension()│
│             │               │             │
│ • CLI tools │               │ • Runtime   │
│ • query!()  │               │ • Actual DB │
│ • migrate   │               │             │
└─────────────┘               └─────────────┘
```

Both configurations can be different, allowing flexibility across environments.

### Extension Function Categories

**Built-in SQLite Functions:**
```sql
SELECT length('hello'), upper('world'), datetime('now');
```

**Extension Functions:**
```sql
-- ipaddr extension
SELECT ipfamily('192.168.1.1'), iphost('192.168.1.1/24');

-- Other common extensions
SELECT uuid4();                    -- uuid extension
SELECT json_extract(data, '$.id'); -- JSON1 extension (often built-in)
SELECT regexp('pattern', text);    -- regexp extension
```

### Common SQLite Extensions

1. **ipaddr**: IP address manipulation functions
2. **uuid**: UUID generation and validation
3. **regexp**: Regular expression support
4. **sqlean**: Collection of useful functions (math, text, stats)
5. **FTS5**: Full-text search (often built-in)
6. **R*Tree**: Spatial indexing (often built-in)

### Loading Strategies

**Static Loading** (shown in example):
```rust
let opts = SqliteConnectOptions::new()
    .extension("extension_name");
```

**Dynamic Loading** (runtime conditional):
```rust
let mut opts = SqliteConnectOptions::new();
if std::env::var("ENABLE_EXTENSIONS").is_ok() {
    opts = opts.extension("optional_extension");
}
```

**Multiple Extensions**:
```rust
let opts = SqliteConnectOptions::new()
    .extension("ipaddr")
    .extension("uuid")
    .extension("regexp");
```

### Error Handling with Extensions

```rust
// Extension loading can fail
let result = SqlitePool::connect_with(opts).await;
match result {
    Ok(pool) => { /* Extension loaded successfully */ },
    Err(sqlx::Error::Database(db_err)) => {
        // Might be extension not found, incompatible version, etc.
        eprintln!("Database error: {}", db_err);
    },
    Err(e) => {
        eprintln!("Other error: {}", e);
    }
}
```

### Security Considerations

Extensions run with full database privileges:
- **Trust the source**: Only use extensions from trusted sources
- **Verify checksums**: Ensure extension integrity
- **Limit permissions**: Run SQLite with minimal system permissions
- **Test thoroughly**: Extensions can crash or corrupt the database
- **Version control**: Pin specific extension versions

### Why SQLite Extensions Work Well with SQLx

1. **Compile-time verification**: SQLx validates extension functions exist
2. **Type safety**: Extension functions are type-checked like built-in functions
3. **Performance**: Functions run in-process, no serialization overhead
4. **Flexibility**: Different environments can load different extensions
5. **Ecosystem**: Rich ecosystem of available extensions

### Further Exploration

Try these extension patterns:

1. **Custom business logic**:
```sql
-- Extension provides domain-specific calculations
SELECT calculate_shipping_cost(weight, distance, priority);
```

2. **Data validation**:
```sql
-- Extension validates complex data formats
INSERT INTO users (email) VALUES (?)
WHERE validate_email(?) = 1;
```

3. **Performance optimization**:
```sql
-- Extension provides optimized algorithms
SELECT optimized_distance(lat1, lon1, lat2, lon2);
```

4. **Integration functions**:
```sql
-- Extension calls external APIs or services
SELECT geocode_address('123 Main St, City, State');
```

### Creating Custom Extensions

For Rust developers, consider creating custom extensions:
```rust
// Using the sqlite-loadable crate
use sqlite_loadable::prelude::*;

#[sqlite_entrypoint]
pub fn sqlite3_extension_init(db: *mut sqlite3) -> Result<()> {
    define_scalar_function(
        db,
        "double_number",
        1,
        |ctx, args| {
            let value: i64 = args.get(0)?;
            ctx.set_result(value * 2);
            Ok(())
        },
        FunctionFlags::UTF8 | FunctionFlags::DETERMINISTIC,
    )?;
    Ok(())
}
```

This demonstrates how SQLite extensions provide a powerful way to extend database capabilities while maintaining SQLx's compile-time safety guarantees and seamless integration with your Rust applications.