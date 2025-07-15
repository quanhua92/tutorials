# Routes and Handlers: Organizing Your Web Application

**Example Source**: [routes-and-handlers-close-together](https://github.com/tokio-rs/axum/tree/6bc0717b06c665baf9dea57d977363ade062bf17/examples/routes-and-handlers-close-together)

## The Core Concept: Why This Example Exists

**The Problem:** As web applications grow beyond "Hello, World!", you face an organizational challenge. Where do you put your route definitions? How do you keep handlers close to their routes? How do you avoid a massive, unwieldy main function where routes and business logic become tangled together?

**The Solution:** Axum's composable router design enables a pattern where routes and their handlers live together in focused, single-purpose functions. This example demonstrates **modular routing**—a technique where each route becomes a self-contained module that can be easily tested, maintained, and reasoned about independently.

Think of this approach like organizing a large office building. Instead of having one giant room where everyone works, you create specialized departments. Each department (route module) has its own space, its own responsibilities, and its own team members (handlers), but they all connect through common hallways (the main router).

## Practical Walkthrough: Code Breakdown

This example shows how to structure routes for maintainability and clarity:

### The Main Router Assembly

```rust
#[tokio::main]
async fn main() {
    let app = Router::new()
        .merge(root())
        .merge(get_foo())
        .merge(post_foo());

    let listener = tokio::net::TcpListener::bind("127.0.0.1:3000")
        .await
        .unwrap();
    println!("listening on {}", listener.local_addr().unwrap());
    axum::serve(listener, app).await.unwrap();
}
```

The key insight here is **composition through merging**. Rather than defining all routes in one place, we:

1. **Create separate route modules**: Each function (`root()`, `get_foo()`, `post_foo()`) returns a complete `Router`
2. **Merge them together**: `.merge()` combines multiple routers into a single, unified routing table
3. **Keep main() clean**: The main function focuses solely on application assembly and server startup

### Self-Contained Route Modules

Let's examine how each route module is structured:

```rust
fn root() -> Router {
    async fn handler() -> &'static str {
        "Hello, World!"
    }

    route("/", get(handler))
}
```

This pattern follows a crucial principle: **locality of reference**. Everything related to the root route—its path, its HTTP method, and its implementation—lives in one place. Benefits include:

- **Easy to find**: Want to modify the root endpoint? Look in the `root()` function
- **Easy to test**: You can unit test `root()` in isolation
- **Easy to understand**: No mental jumping between files to understand what happens at "/"

### Method-Specific Route Handlers

```rust
fn get_foo() -> Router {
    async fn handler() -> &'static str {
        "Hi from `GET /foo`"
    }

    route("/foo", get(handler))
}

fn post_foo() -> Router {
    async fn handler() -> &'static str {
        "Hi from `POST /foo`"
    }

    route("/foo", post(handler))
}
```

Notice that both functions handle the same path (`/foo`) but different HTTP methods. This demonstrates Axum's ability to **differentiate routes by method**. When these routers are merged, Axum automatically:

- Routes `GET /foo` to the first handler
- Routes `POST /foo` to the second handler
- Returns a "Method Not Allowed" error for other methods on `/foo`

### The Utility Helper Function

```rust
fn route(path: &str, method_router: MethodRouter<()>) -> Router {
    Router::new().route(path, method_router)
}
```

This helper function eliminates boilerplate by wrapping the common pattern of creating a new router with a single route. It's a small detail that demonstrates Rust's emphasis on **eliminating repetition through abstraction**.

## Mental Model: Thinking in Axum

**The Restaurant Analogy:** Imagine running a restaurant. The traditional approach would be having one giant menu where every dish, every price, and every cooking instruction is listed together. The Axum approach is like having specialized stations:

- **Appetizer Station** (`root()`): Handles simple, welcoming dishes
- **Main Course Station** (`get_foo()`): Handles substantial requests
- **Dessert Station** (`post_foo()`): Handles sweet finishes to the meal

Each station knows exactly what it does, has all its tools nearby, and can operate independently. The head chef (main router) coordinates between stations but doesn't need to know every recipe detail.

```mermaid
graph TB
    A[HTTP Request] --> B{Main Router}
    B --> C[root() Module]
    B --> D[get_foo() Module]
    B --> E[post_foo() Module]
    
    C --> C1[Handler: "Hello, World!"]
    D --> D1[Handler: "Hi from GET /foo"]
    E --> E1[Handler: "Hi from POST /foo"]
    
    C1 --> F[Response]
    D1 --> F
    E1 --> F
```

**Why It's Designed This Way:** This organizational pattern scales beautifully. In a real application, you might have:

- `user_routes()` - All user management endpoints
- `product_routes()` - Product catalog operations  
- `order_routes()` - Shopping cart and ordering
- `admin_routes()` - Administrative functions

Each module can grow independently, have its own error handling patterns, and even its own middleware layers.

**Design Philosophy Deep Dive:** Axum's router merging capability reflects a broader principle in system design: **composability over inheritance**. Instead of creating complex hierarchies or requiring framework-specific base classes, Axum lets you build applications by combining simple, pure functions that each do one thing well.

**Further Exploration:** Try extending this pattern:

1. **Add middleware to specific routes**: What if only `post_foo()` needed authentication?
2. **Create nested path groups**: How would you handle `/api/v1/users` and `/api/v1/products`?
3. **Extract modules to separate files**: Move each route function to its own file and import them

The beauty of this approach is that it grows naturally with your application's complexity while maintaining clarity and testability at every level.