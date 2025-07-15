# Building a Production-Ready Social API with SQLx and Axum

> **Source Code**: [examples/postgres/axum-social-with-tests](https://github.com/launchbadge/sqlx/tree/f7ef1ed1e99bd2fd6f29a81b103235517fcc2731/examples/postgres/axum-social-with-tests)

## The Core Concept: Why This Example Exists

**The Problem:** Previous examples show SQLx basics, but real applications need comprehensive solutions: web framework integration, proper authentication, security best practices, comprehensive testing, and production-ready architecture. Bridging the gap between toy examples and production systems requires understanding complex patterns and architectural decisions.

**The Solution:** This example demonstrates a complete social media API built with SQLx and Axum, showcasing advanced patterns including integration testing with `#[sqlx::test]`, proper error handling, security implementations, and real-world database design. It serves as a blueprint for production applications.

## Practical Walkthrough: Code Breakdown

### Project Architecture

```
src/
├── main.rs          # Application entry point & server setup
├── lib.rs           # Public API & module organization
├── password.rs      # Security: Argon2 password hashing
└── http/
    ├── mod.rs       # HTTP router & middleware setup
    ├── error.rs     # Centralized error handling
    ├── user.rs      # User registration & authentication
    └── post/
        ├── mod.rs   # Post creation & listing
        └── comment.rs # Comment functionality
```

This modular structure separates concerns clearly: HTTP handling, business logic, security, and error management.

### Database Schema Evolution (`migrations/`)

#### Users Table (`1_user.sql`)
```sql
CREATE TABLE "user"
(
    user_id      UUID PRIMARY KEY        DEFAULT gen_random_uuid(),
    username     TEXT UNIQUE    NOT NULL CHECK (length(username) <= 20),
    password_hash TEXT          NOT NULL
);

CREATE INDEX user_username ON "user" (username);
```

Key design decisions:
- **UUIDs as primary keys**: Better for distributed systems and security
- **Unique username constraint**: Enforced at database level
- **Password hash storage**: Never store plain text passwords
- **Check constraints**: Validate data at the database level
- **Indexing strategy**: Optimize for common query patterns

#### Posts Table (`2_post.sql`)
```sql
CREATE TABLE post
(
    post_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID             NOT NULL REFERENCES "user" (user_id) ON DELETE CASCADE,
    content    TEXT             NOT NULL CHECK (length(content) <= 2000),
    created_at TIMESTAMPTZ      NOT NULL DEFAULT now()
);

CREATE INDEX post_created_at_desc ON post (created_at DESC);
```

Advanced patterns:
- **Foreign key relationships**: Proper referential integrity
- **Cascade deletion**: Delete posts when user is deleted
- **Timezone-aware timestamps**: `TIMESTAMPTZ` for global applications
- **Descending index**: Optimize for "recent posts first" queries

#### Comments Table (`3_comment.sql`)
```sql
CREATE TABLE comment
(
    comment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id    UUID        NOT NULL REFERENCES post (post_id) ON DELETE CASCADE,
    user_id    UUID        NOT NULL REFERENCES "user" (user_id) ON DELETE CASCADE,
    content    TEXT        NOT NULL CHECK (length(content) <= 500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX comment_post_created_at_desc ON comment (post_id, created_at DESC);
```

Performance optimization:
- **Composite index**: Efficiently query comments for a specific post in chronological order
- **Multiple foreign keys**: Both post and user references for data integrity

### Security Implementation (`password.rs`)

```rust
use argon2::{Argon2, PasswordHash, PasswordHasher, PasswordVerifier};
use rand_core::OsRng;

pub async fn hash(password: &str) -> Result<String, argon2::password_hash::Error> {
    let salt = SaltString::generate(&mut OsRng);
    let argon2 = Argon2::default();
    
    let password_hash = argon2
        .hash_password(password.as_bytes(), &salt)?
        .to_string();
    
    Ok(password_hash)
}

pub async fn verify(password: &str, password_hash: &str) -> Result<bool, argon2::password_hash::Error> {
    let parsed_hash = PasswordHash::new(password_hash)?;
    let argon2 = Argon2::default();
    
    match argon2.verify_password(password.as_bytes(), &parsed_hash) {
        Ok(()) => Ok(true),
        Err(argon2::password_hash::Error::Password) => Ok(false),
        Err(err) => Err(err),
    }
}
```

Security best practices:
- **Argon2**: Industry-standard password hashing algorithm
- **Salt generation**: Each password gets a unique salt
- **Timing attack prevention**: Consistent timing regardless of hash validity
- **Error handling**: Distinguish between verification failure and system errors

### Web Framework Integration (`http/mod.rs`)

```rust
pub fn app(db: PgPool) -> Router {
    Router::new()
        .merge(user::router())
        .merge(post::router())
        .layer(Extension(db))
        .layer(
            ServiceBuilder::new()
                .layer(TraceLayer::new_for_http())
                .layer(CorsLayer::permissive())
        )
}
```

Axum integration patterns:
- **Dependency injection**: Database pool available to all handlers via `Extension`
- **Router composition**: Merge feature-specific routers
- **Middleware layers**: Logging, CORS, and other cross-cutting concerns
- **Service builder**: Composable middleware stack

### Advanced Error Handling (`http/error.rs`)

```rust
#[derive(thiserror::Error, Debug)]
pub enum Error {
    #[error("an internal database error occurred")]
    Sqlx(#[from] sqlx::Error),
    
    #[error("validation error in request body")]
    InvalidEntity(#[from] ValidationErrors),
    
    #[error("{0}")]
    UnprocessableEntity(String),
    
    #[error("{0}")]
    Conflict(String),
}

impl IntoResponse for Error {
    fn into_response(self) -> Response {
        let (status, message) = match self {
            Error::Sqlx(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Internal server error"),
            Error::InvalidEntity(_) => (StatusCode::BAD_REQUEST, "Validation error"),
            Error::UnprocessableEntity(msg) => (StatusCode::UNPROCESSABLE_ENTITY, &msg),
            Error::Conflict(msg) => (StatusCode::CONFLICT, &msg),
        };

        Json(json!({ "error": message })).into_response()
    }
}
```

Production error handling:
- **Structured error types**: Different errors for different scenarios
- **Error conversion**: Automatic conversion from library errors
- **HTTP status mapping**: Proper status codes for different error types
- **Client-safe messages**: Don't leak internal details to API consumers

### Complex Database Operations (`http/post/mod.rs`)

```rust
pub async fn create(
    Extension(db): Extension<PgPool>,
    Json(new_post): Json<NewPost>,
) -> Result<Json<Post>, Error> {
    let post = sqlx::query_as!(
        Post,
        r#"
        INSERT INTO post (user_id, content)
        VALUES ($1, $2)
        RETURNING post_id, user_id, content, created_at
        "#,
        new_post.user_id,
        new_post.content
    )
    .fetch_one(&db)
    .await?;

    Ok(Json(post))
}

pub async fn list(Extension(db): Extension<PgPool>) -> Result<Json<Vec<PostWithUser>>, Error> {
    let posts = sqlx::query_as!(
        PostWithUser,
        r#"
        SELECT p.post_id, p.content, p.created_at, p.user_id, u.username
        FROM post p
        INNER JOIN "user" u ON p.user_id = u.user_id
        ORDER BY p.created_at DESC
        "#
    )
    .fetch_all(&db)
    .await?;

    Ok(Json(posts))
}
```

Advanced SQL patterns:
- **RETURNING clauses**: Get inserted data in single round trip
- **Complex JOINs**: Denormalize data for efficient API responses
- **Ordering optimization**: Use the descending index we created
- **Type-safe results**: `query_as!` maps directly to response structs

### Integration Testing with `#[sqlx::test]`

#### Test Structure
```
tests/
├── common.rs        # Shared utilities
├── user.rs          # User endpoint tests
├── post.rs          # Post endpoint tests
├── comment.rs       # Comment endpoint tests
└── fixtures/        # Pre-populated test data
    ├── users.sql
    ├── posts.sql
    └── comments.sql
```

#### Test Implementation (`tests/post.rs`)
```rust
#[sqlx::test(fixtures("users", "posts"))]
async fn test_list_posts(db: PgPool) {
    let mut app = http::app(db);

    let resp = app
        .borrow_mut()
        .oneshot(Request::get("/v1/post").empty_body())
        .await
        .unwrap();

    assert_eq!(resp.status(), StatusCode::OK);

    let posts: Vec<PostWithUser> = resp.json().await;
    assert_eq!(posts.len(), 2);
    assert_eq!(posts[0].username, "alice");  // Most recent first
}

#[sqlx::test(fixtures("users"))]
async fn test_create_post(db: PgPool) {
    let mut app = http::app(db);

    let resp = app
        .borrow_mut()
        .oneshot(
            Request::post("/v1/post")
                .json(json!({
                    "user_id": "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                    "content": "Hello, world!"
                }))
        )
        .await
        .unwrap();

    assert_eq!(resp.status(), StatusCode::OK);

    let post: Post = resp.json().await;
    assert_eq!(post.content, "Hello, world!");
}
```

Testing excellence:
- **`#[sqlx::test]`**: Each test gets a fresh database
- **Fixtures**: Pre-populated test data from SQL files
- **Integration testing**: Test the full HTTP stack
- **Type-safe assertions**: Use the same structs as production code

## Mental Model: Thinking in Production SQLx

### Database-First Design

```
Database Schema → Rust Types → HTTP API
     ↑              ↑           ↑
 Constraints   Type Safety   Validation
```

This flow ensures consistency from database to API:
1. **Database constraints** prevent invalid data at the source
2. **Rust types** provide compile-time guarantees
3. **HTTP validation** provides user-friendly error messages

### The Testing Philosophy

```
#[sqlx::test] → Fresh Database → Real Integration Test
     ↓               ↓                    ↓
 Isolation       Realistic           Confidence
```

Each test runs against a real database, providing confidence that your application works correctly with actual PostgreSQL behavior.

### Error Boundary Strategy

```
Database Errors → Internal Error Type → HTTP Response
       ↓                  ↓                 ↓
   Implementation    Business Logic    User-Friendly
```

This layered approach prevents internal details from leaking while providing meaningful feedback to API consumers.

### Security Layers

```
Input Validation → Database Constraints → Business Logic → Output Filtering
        ↓                  ↓                   ↓              ↓
   Early Rejection    Data Integrity    Access Control   Safe Responses
```

Defense in depth ensures security at every layer of the application.

### Why This Architecture Works Well

1. **Scalability**: Connection pooling and efficient queries support high load
2. **Maintainability**: Clear module boundaries and comprehensive tests
3. **Security**: Multiple layers of validation and proper password handling
4. **Performance**: Optimized database schema and query patterns
5. **Reliability**: Comprehensive error handling and database constraints

### Further Exploration

To extend this example into a full production system:

1. **Authentication & Authorization**: Add JWT tokens or session management
2. **Rate Limiting**: Prevent abuse with request rate limits
3. **Caching**: Add Redis for frequently accessed data
4. **File Upload**: Extend posts to support image uploads
5. **Real-time Features**: Add WebSocket support for live comments
6. **Monitoring**: Add metrics and health check endpoints
7. **Database Optimization**: Add query analysis and performance monitoring

This example demonstrates that SQLx scales from simple scripts to complex, production-ready applications while maintaining type safety and performance throughout the entire stack.