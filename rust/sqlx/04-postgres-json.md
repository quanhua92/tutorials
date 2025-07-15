# Working with JSON in PostgreSQL and SQLx

> **Source Code**: [examples/postgres/json](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/postgres/json)

## The Core Concept: Why This Example Exists

**The Problem:** Modern applications often need to store semi-structured data that doesn't fit neatly into relational tables. While you could serialize JSON to text columns, you lose the ability to query, index, and validate the data at the database level.

**The Solution:** PostgreSQL's native `JSONB` type provides first-class JSON support with indexing, querying, and data validation. SQLx bridges this perfectly with Rust's type system through `serde` integration, giving you type-safe JSON operations that are verified at compile time.

## Practical Walkthrough: Code Breakdown

### JSONB Schema Design (`migrations/20200824190010_json.sql`)

```sql
CREATE TABLE IF NOT EXISTS people
(
    id     BIGSERIAL PRIMARY KEY,
    person JSONB NOT NULL
);
```

**Why JSONB over JSON?**
- `JSONB` stores JSON in a binary format (faster queries, indexing)
- `JSON` stores text exactly as input (preserves formatting, key order)
- `JSONB` is almost always the right choice for application data

### Rust Struct with Flexible JSON (`main.rs:20-31`)

```rust
#[derive(Deserialize, Serialize)]
struct Person {
    name: String,
    age: NonZeroU8,
    #[serde(flatten)]
    extra: Map<String, Value>,
}

struct Row {
    id: i64,
    person: Json<Person>,
}
```

This design demonstrates a powerful pattern:
- **Required fields**: `name` and `age` have strong types
- **Flexible data**: `extra` captures any additional JSON fields
- **Type safety**: `NonZeroU8` ensures age is valid
- **Serde flatten**: Additional fields are merged at the top level

### JSON Input Processing (`main.rs:40-50`)

```rust
let mut json = String::new();
io::stdin().read_to_string(&mut json)?;

let person: Person = serde_json::from_str(&json)?;
println!(
    "Adding new person: {}",
    &serde_json::to_string_pretty(&person)?
);
```

The application reads raw JSON from stdin and immediately deserializes it into a strongly-typed `Person` struct. Any JSON that doesn't match the expected structure will fail fast with a clear error.

### Storing JSON with Type Safety (`main.rs:62-74`)

```rust
let rec = sqlx::query!(
    r#"
INSERT INTO people ( person )
VALUES ( $1 )
RETURNING id
    "#,
    Json(person) as _
)
.fetch_one(pool)
.await?;
```

The `Json<T>` wrapper tells SQLx to:
1. Serialize the Rust struct to JSON
2. Store it in the `JSONB` column
3. Ensure the parameter type matches the column type at compile time

The `as _` cast helps Rust's type inference system.

### Retrieving JSON with Type Annotations (`main.rs:77-86`)

```rust
let rows = sqlx::query_as!(
    Row,
    r#"
SELECT id, person as "person: Json<Person>"
FROM people
ORDER BY id
    "#
)
.fetch_all(pool)
.await?;
```

The type annotation `"person: Json<Person>"` is crucial:
- It tells SQLx to deserialize the JSONB column into `Json<Person>`
- Without it, SQLx wouldn't know what Rust type to use
- The compile-time verification ensures the JSON structure matches `Person`

### Flexible JSON Handling

Input JSON can have any structure that matches `Person`:

```json
{
  "name": "Alice",
  "age": 30
}
```

Or with extra fields:

```json
{
  "name": "Bob", 
  "age": 25,
  "city": "San Francisco",
  "hobbies": ["programming", "hiking"]
}
```

Both work because `#[serde(flatten)]` captures extra fields in the `extra` map.

## Mental Model: Thinking in PostgreSQL JSON + SQLx

### JSON as a Bridge Between Worlds

```
Rust Structs ←→ Serde ←→ JSON ←→ PostgreSQL JSONB
    ↑                                      ↓
Type Safety                          Indexing & Queries
```

This pipeline gives you:
- **Rust side**: Compile-time type safety, zero-copy deserialization
- **Database side**: Efficient storage, indexing, and JSON-specific queries

### The `Json<T>` Wrapper Pattern

Think of `Json<T>` as a "transport wrapper":

```rust
Person           // Your business logic type
Json<Person>     // Database transport type  
```

The wrapper handles:
- Serialization/deserialization
- Type annotations for SQLx
- Compile-time verification

### PostgreSQL JSON Capabilities

PostgreSQL's JSONB enables powerful operations:

```sql
-- Index on JSON fields
CREATE INDEX idx_person_name ON people USING GIN ((person->>'name'));

-- Query JSON fields
SELECT * FROM people WHERE person->>'name' = 'Alice';

-- Update JSON fields
UPDATE people SET person = jsonb_set(person, '{age}', '31') 
WHERE person->>'name' = 'Alice';
```

SQLx lets you use all of these in compile-time checked queries.

### Schema Evolution Strategy

This pattern enables graceful schema evolution:

1. **Add optional fields**: New JSON properties are automatically captured in `extra`
2. **Promote fields**: Move frequently-used `extra` fields to typed struct fields
3. **Version schemas**: Use JSON to store schema version information

### Why PostgreSQL JSONB + SQLx Works Well

1. **Performance**: JSONB is faster than text-based JSON storage
2. **Flexibility**: Semi-structured data without schema migrations
3. **Type safety**: Rust structs enforce data contracts
4. **Query power**: Full JSON query capabilities with SQL

### Further Exploration

Try these advanced patterns:

1. **JSON Schema Validation**: Use PostgreSQL's JSON schema validation with SQLx
2. **Partial Updates**: Use `jsonb_set` to update specific JSON fields
3. **JSON Indexing**: Create GIN indexes on specific JSON paths for faster queries
4. **Nested Structures**: Design more complex nested JSON schemas with type safety

Example of a more complex structure:

```rust
#[derive(Deserialize, Serialize)]
struct Address {
    street: String,
    city: String,
    country: String,
}

#[derive(Deserialize, Serialize)]  
struct Person {
    name: String,
    age: NonZeroU8,
    addresses: Vec<Address>,
    #[serde(flatten)]
    extra: Map<String, Value>,
}
```

This demonstrates how SQLx and PostgreSQL can handle arbitrarily complex, type-safe JSON structures.