# Default Query Function: Simplified Setup

> **Based on**: [`examples/react/default-query-function`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/default-query-function)

## The Core Concept: Why This Example Exists

**The Problem:** In larger applications, you often find yourself writing similar query functions repeatedly - most API calls follow predictable patterns based on the endpoint URL. Writing individual `queryFn` for each `useQuery` creates boilerplate code and inconsistent error handling across your application.

**The Solution:** TanStack Query's **default query function** feature allows you to define a single, globally configured query function that receives the query key and automatically handles data fetching. This creates a **convention-over-configuration** approach where query keys directly map to API endpoints.

The key insight: **query keys should be self-descriptive enough to drive data fetching**. Instead of treating query keys as arbitrary cache identifiers, design them as semantic API endpoint descriptors that your default query function can interpret.

## Practical Walkthrough: Code Breakdown

Let's examine the default query function pattern from `examples/react/default-query-function/src/index.tsx`:

### 1. Default Query Function Definition

```tsx
type QueryKey = string[]

const defaultQueryFn = async ({ queryKey }: { queryKey: QueryKey }) => {
  const response = await fetch(
    `https://jsonplaceholder.typicode.com${queryKey[0]}`,
  )
  return await response.json()
}
```

**What's happening:** The default query function receives the full query key as an argument. The first element (`queryKey[0]`) is treated as the API endpoint path, which gets appended to the base API URL.

**Why this pattern:** By making query keys semantic (like `['/posts']` or `['/posts/42']`), the query function can automatically construct the correct API URL without duplicating URL logic across components.

### 2. Global Configuration

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      queryFn: defaultQueryFn,
    },
  },
})
```

**What's happening:** The default query function is configured once at the `QueryClient` level, making it available to all queries throughout the application.

**Why global configuration:** This ensures consistent data fetching behavior across your entire app and eliminates the need to import and specify query functions in every component.

### 3. Simplified Query Usage

```tsx
// Posts list - just pass the endpoint as query key
const { status, data, error, isFetching } = useQuery<Array<Post>>({
  queryKey: ['/posts'],
})

// Individual post - query key describes the endpoint
const { status, data, error, isFetching } = useQuery<Post>({
  queryKey: [`/posts/${postId}`],
  enabled: !!postId,
})
```

**What's happening:** Components no longer need to specify `queryFn` - they only provide the query key that describes what data they need. The default query function automatically handles the fetching.

**Why this is powerful:** Components become more declarative, focusing on *what* data they need rather than *how* to fetch it. This reduces coupling between components and data fetching logic.

### 4. Cache-Aware UI Indicators

```tsx
style={
  queryClient.getQueryData([`/posts/${post.id}`])
    ? { fontWeight: 'bold', color: 'green' }
    : {}
}
```

**What's happening:** Since query keys are predictable and semantic, components can easily check for cached data using the same key pattern.

**Why this works:** Consistent query key patterns enable UI features like cache indicators, prefetching, and selective invalidation to work reliably across the application.

## Mental Model: Query Keys as API Descriptors

### Semantic Query Key Design

Instead of arbitrary cache keys:
```tsx
// ❌ Arbitrary keys requiring custom query functions
useQuery({ queryKey: ['posts-list'], queryFn: fetchPosts })
useQuery({ queryKey: ['post-detail', id], queryFn: () => fetchPost(id) })
```

Use semantic endpoint descriptors:
```tsx
// ✅ Self-describing keys that drive automatic fetching
useQuery({ queryKey: ['/posts'] })
useQuery({ queryKey: [`/posts/${id}`] })
```

### URL Construction Logic

The default query function acts as a URL router:

```
Query Key           →  API Request
['/posts']          →  GET /posts
['/posts/42']       →  GET /posts/42
['/users/1/posts']  →  GET /users/1/posts
```

This creates a direct, predictable mapping between component data needs and API endpoints.

### Centralized Configuration Benefits

```
Single Source of Truth:
├── Base URL configuration
├── Authentication headers
├── Error handling
├── Response transformation
├── Request/response interceptors
└── Timeout and retry logic
```

All query behavior is centralized, making it easy to modify globally without touching individual components.

### Why It's Designed This Way: Convention Over Configuration

Traditional approach requires repetitive setup:
```tsx
// ❌ Repetitive configuration
const postsQuery = useQuery({
  queryKey: ['posts'],
  queryFn: async () => {
    const response = await fetch('/api/posts')
    if (!response.ok) throw new Error('Failed to fetch')
    return response.json()
  }
})
```

Default query function approach:
```tsx
// ✅ Convention-based simplicity
const postsQuery = useQuery({ queryKey: ['/posts'] })
```

### Advanced Default Query Function Patterns

**Parameter Handling**: Extended query keys can include parameters:
```tsx
const defaultQueryFn = async ({ queryKey }) => {
  const [endpoint, ...params] = queryKey
  
  if (params.length > 0) {
    const searchParams = new URLSearchParams(params[0])
    return fetch(`${baseURL}${endpoint}?${searchParams}`)
  }
  
  return fetch(`${baseURL}${endpoint}`)
}

// Usage
useQuery({ queryKey: ['/posts', { page: 1, limit: 10 }] })
```

**HTTP Method Detection**: Query keys can encode HTTP methods:
```tsx
const defaultQueryFn = async ({ queryKey }) => {
  const [method, endpoint, data] = queryKey
  
  return fetch(`${baseURL}${endpoint}`, {
    method: method.toUpperCase(),
    body: data ? JSON.stringify(data) : undefined,
    headers: { 'Content-Type': 'application/json' }
  })
}

// Usage  
useQuery({ queryKey: ['GET', '/posts'] })
useMutation({ mutationKey: ['POST', '/posts', newPost] })
```

**Authentication Integration**: Centralized auth header management:
```tsx
const defaultQueryFn = async ({ queryKey }) => {
  const token = getAuthToken()
  
  return fetch(`${baseURL}${queryKey[0]}`, {
    headers: {
      Authorization: token ? `Bearer ${token}` : undefined,
      'Content-Type': 'application/json'
    }
  })
}
```

### Error Handling Strategies

**Global Error Handling**: Default query functions enable consistent error handling:
```tsx
const defaultQueryFn = async ({ queryKey }) => {
  const response = await fetch(`${baseURL}${queryKey[0]}`)
  
  if (!response.ok) {
    if (response.status === 401) {
      // Global auth error handling
      redirectToLogin()
      throw new Error('Authentication required')
    }
    
    if (response.status >= 500) {
      // Global server error handling
      logErrorToService(response)
      throw new Error('Server error occurred')
    }
    
    throw new Error(`Request failed: ${response.statusText}`)
  }
  
  return response.json()
}
```

### Further Exploration

Experiment with default query function patterns:

1. **Parameter Encoding**: Try different ways to encode query parameters in query keys
2. **Response Transformation**: Add global response transformation logic
3. **Environment Configuration**: Use different base URLs for development/production
4. **Type Safety**: Add TypeScript types for your query key patterns

**Advanced Challenges**:

1. **GraphQL Integration**: How would you design a default query function for GraphQL?
   ```tsx
   const defaultQueryFn = async ({ queryKey }) => {
     const [query, variables] = queryKey
     return graphqlClient.request(query, variables)
   }
   ```

2. **REST Resource Patterns**: How would you handle RESTful resource patterns?
   ```tsx
   // Support patterns like:
   useQuery({ queryKey: ['/users', userId, '/posts'] })
   // → GET /users/123/posts
   ```

3. **Caching Strategies**: How would you implement per-endpoint cache configurations?

4. **Multi-API Support**: How would you handle multiple API services in one app?

**Real-World Applications**:
- Microservice architectures with consistent API patterns
- Generated API clients that follow predictable conventions  
- Large applications needing centralized data fetching logic
- Teams wanting to standardize data fetching practices

The default query function pattern scales from simple applications to complex, multi-team projects where consistency and maintainability are crucial. It's particularly powerful when combined with code generation tools that can automatically create query keys based on your API specification.