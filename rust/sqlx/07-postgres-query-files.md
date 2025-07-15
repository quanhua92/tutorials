# Organizing SQL with External Query Files

> **Source Code**: [examples/postgres/files](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/postgres/files)

## The Core Concept: Why This Example Exists

**The Problem:** As applications grow, SQL queries become more complex and numerous. Embedding large SQL queries as strings in Rust code creates several issues: poor syntax highlighting, difficulty with version control diffs, reduced maintainability, and limited collaboration with SQL-focused team members.

**The Solution:** SQLx provides `query_file!` macros that load SQL from external files while maintaining all compile-time verification benefits. This separates concerns cleanly: SQL files contain pure SQL that can be managed by database specialists, while Rust code focuses on application logic and type safety.

## Practical Walkthrough: Code Breakdown

### Database Schema with Relationships (`migrations/20220712221654_files.sql`)

```sql
CREATE TABLE IF NOT EXISTS users
(
    id       BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts
(
    id      BIGSERIAL PRIMARY KEY,
    title   TEXT NOT NULL,
    body    TEXT NOT NULL,
    user_id BIGINT NOT NULL
        REFERENCES users (id) ON DELETE CASCADE
);
```

This schema demonstrates:
- **Foreign key relationships**: `posts.user_id` references `users.id`
- **Cascade deletion**: Deleting a user removes their posts
- **Normalization**: Users and posts are separate entities

### Complex Query in External File (`queries/insert_seed_data.sql`)

```sql
-- seed some data to work with
WITH inserted_users_cte AS (
    INSERT INTO users (username)
        VALUES ('user1'),
               ('user2')
        RETURNING id as "user_id"
)
INSERT INTO posts (title, body, user_id)
VALUES ('user1 post1 title', 'user1 post1 body', (SELECT user_id FROM inserted_users_cte FETCH FIRST ROW ONLY)),
       ('user1 post2 title', 'user1 post2 body', (SELECT user_id FROM inserted_users_cte FETCH FIRST ROW ONLY)),
       ('user2 post1 title', 'user2 post2 body', (SELECT user_id FROM inserted_users_cte OFFSET 1 LIMIT 1));
```

This demonstrates advanced PostgreSQL features:
- **Common Table Expressions (CTEs)**: `WITH` clause for temporary result sets
- **RETURNING clause**: Get inserted IDs for use in subsequent operations
- **Subqueries**: Reference CTE results in the main INSERT
- **Complex data seeding**: Create related records in a single statement

### JOIN Query in External File (`queries/list_all_posts.sql`)

```sql
SELECT p.id as "post_id",
       p.title,
       p.body,
       u.id as "author_id",
       u.username as "author_username"
FROM users u
         JOIN posts p on u.id = p.user_id;
```

Key patterns:
- **Column aliases**: Rename columns for clearer Rust struct mapping
- **Table aliases**: `u` for users, `p` for posts
- **JOIN relationships**: Link users to their posts

### Using External Files with Type Safety (`main.rs:33-36`)

```rust
// Execute a complex query from file
query_file!("queries/insert_seed_data.sql")
    .execute(&pool)
    .await?;
```

`query_file!` provides the same compile-time verification as `query!`:
- **SQL syntax validation**: File is parsed at compile time
- **Table/column verification**: Checked against your database schema
- **Parameter type checking**: (if the query had parameters)

### Mapping to Custom Structs (`main.rs:4-11, 39-41`)

```rust
#[derive(FromRow)]
struct PostWithAuthorQuery {
    pub post_id: i64,
    pub title: String,
    pub body: String,
    pub author_id: i64,
    pub author_username: String,
}

let posts_with_authors = query_file_as!(PostWithAuthorQuery, "queries/list_all_posts.sql")
    .fetch_all(&pool)
    .await?;
```

`query_file_as!` combines external SQL files with custom struct mapping:
- **FromRow derivation**: Automatically maps database columns to struct fields
- **Type verification**: Ensures query results match struct definition
- **Field naming**: Struct fields must match column names (or aliases)

### Display Implementation (`main.rs:13-27`)

```rust
impl Display for PostWithAuthorQuery {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            r#"
            post_id: {},
            title: {},
            body: {},
            author_id: {},
            author_username: {}
        "#,
            self.post_id, self.title, self.body, self.author_id, self.author_username
        )
    }
}
```

This enables clean output formatting while keeping the struct focused on data representation.

## Mental Model: Thinking in Query Files

### Separation of Concerns

```
SQL Files                    Rust Code
├── queries/                 ├── main.rs
│   ├── insert_seed_data.sql │   ├── struct definitions
│   └── list_all_posts.sql   │   ├── business logic
└── migrations/              │   └── error handling
    └── *.sql               
```

This organization allows:
- **SQL specialists** to focus on query optimization
- **Rust developers** to focus on application logic
- **Version control** to track SQL changes clearly
- **Code reviews** to evaluate SQL and Rust separately

### Compile-Time File Integration

```
Build Time:
┌─────────────────┐    ┌──────────────┐    ┌──────────────┐
│ SQL Files       │ →  │ SQLx Macros  │ →  │ Generated    │
│ + Database      │    │ + Validation │    │ Rust Code    │
│ Schema          │    │              │    │              │
└─────────────────┘    └──────────────┘    └──────────────┘
```

The query files are embedded at compile time, so there's no runtime file reading overhead.

### FromRow vs Anonymous Structs

```rust
// Anonymous struct (query!)
let result = query!("SELECT id, title FROM posts").fetch_all(&pool).await?;
// result[0].id, result[0].title

// Named struct (query_as!)  
let result = query_file_as!(PostQuery, "queries/posts.sql").fetch_all(&pool).await?;
// result[0].id, result[0].title - same access, but with named type
```

Named structs provide:
- **Better documentation** through explicit type names
- **Reusability** across multiple functions
- **Enhanced IDE support** with autocomplete and type hints

### Query Organization Strategies

**By Feature:**
```
queries/
├── users/
│   ├── create_user.sql
│   ├── find_by_email.sql
│   └── update_profile.sql
└── posts/
    ├── create_post.sql
    └── list_with_authors.sql
```

**By Complexity:**
```
queries/
├── simple/
│   ├── get_user.sql
│   └── get_post.sql
├── joins/
│   └── posts_with_authors.sql
└── complex/
    └── analytics_report.sql
```

### Why External Query Files Work Well

1. **SQL syntax highlighting**: IDEs provide full SQL support in .sql files
2. **Database tool integration**: DB clients can execute files directly
3. **Team collaboration**: SQL experts can work independently
4. **Version control clarity**: SQL changes are isolated and clear
5. **Reusability**: Queries can be shared across different functions
6. **Testing**: SQL files can be tested independently

### Performance Considerations

External query files have **zero runtime overhead**:
- Files are embedded at compile time
- No file I/O during execution
- Same performance as inline queries
- All compile-time verification benefits retained

### Further Exploration

Try these patterns to leverage external query files effectively:

1. **Parameterized queries in files**:
```sql
-- queries/find_user_posts.sql
SELECT * FROM posts WHERE user_id = $1 AND created_at > $2
```

```rust
query_file_as!(Post, "queries/find_user_posts.sql", user_id, since_date)
    .fetch_all(&pool).await?
```

2. **Complex analytics queries**:
```sql
-- queries/user_analytics.sql
WITH user_stats AS (
    SELECT 
        u.id,
        u.username,
        COUNT(p.id) as post_count,
        AVG(LENGTH(p.body)) as avg_post_length
    FROM users u
    LEFT JOIN posts p ON u.id = p.user_id
    GROUP BY u.id, u.username
)
SELECT * FROM user_stats ORDER BY post_count DESC;
```

3. **Query composition**: Build larger queries from smaller, reusable components

4. **Environment-specific queries**: Different query files for different deployment environments

This approach demonstrates how SQLx enables clean separation between SQL expertise and Rust application development while maintaining full type safety and performance.