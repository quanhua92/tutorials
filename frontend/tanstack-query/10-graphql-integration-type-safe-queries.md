# GraphQL Integration: Type-Safe Queries

> **Based on**: [`examples/react/basic-graphql-request`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/basic-graphql-request)

## The Core Concept: Why This Example Exists

**The Problem:** GraphQL promises better API design with precise data fetching, strong typing, and powerful developer tools. However, integrating GraphQL with React state management often requires complex Apollo Client setup, custom caching logic, and verbose boilerplate. Developers want GraphQL's query power with simpler state management and caching.

**The Solution:** TanStack Query is **transport-agnostic** - it works with any async function, including GraphQL queries. By combining Query's intelligent caching and state management with GraphQL's precise data fetching, you get the best of both worlds: **GraphQL's query power with Query's superior caching and developer experience**.

The key insight: **TanStack Query treats GraphQL queries like any other async function**, while providing all the caching, background updates, and state management features you need. This creates a lightweight, flexible alternative to heavyweight GraphQL clients.

## Practical Walkthrough: Code Breakdown

Let's examine the GraphQL integration patterns from `examples/react/basic-graphql-request/src/index.tsx`:

### 1. GraphQL Client Setup

```tsx
import { gql, request } from 'graphql-request'

const endpoint = 'https://graphqlzero.almansi.me/api'

type Post = {
  id: number
  title: string
  body: string
}
```

**What's happening:** Using `graphql-request`, a minimal GraphQL client that focuses purely on making requests. The `gql` template tag provides syntax highlighting and GraphQL tooling support.

**Why graphql-request:** It's lightweight (no complex client setup), works perfectly with TanStack Query's async function pattern, and provides TypeScript integration without heavyweight dependencies.

### 2. Typed GraphQL Query Functions

```tsx
function usePosts() {
  return useQuery({
    queryKey: ['posts'],
    queryFn: async () => {
      const {
        posts: { data },
      } = await request<{ posts: { data: Array<Post> } }>(
        endpoint,
        gql`
          query {
            posts {
              data {
                id
                title
              }
            }
          }
        `,
      )
      return data
    },
  })
}
```

**What's happening:** The GraphQL query is wrapped in a standard async function that TanStack Query can cache and manage. TypeScript generics provide full type safety for both the GraphQL response and the returned data.

**Why this pattern:** Query doesn't need to understand GraphQL - it just needs an async function. This keeps Query's API simple while enabling any GraphQL client or pattern to work seamlessly.

### 3. Field Selection and Data Shape

```tsx
gql`
  query {
    posts {
      data {
        id
        title  # Only requesting id and title for list view
      }
    }
  }
`
```

**What's happening:** GraphQL's field selection allows requesting only the data needed for each component. The list view only needs `id` and `title`, reducing payload size.

**Why field selection matters:** Smaller payloads mean faster network requests and better performance. GraphQL enables component-driven data requirements - each component requests exactly what it needs.

### 4. Dynamic GraphQL Queries with Variables

```tsx
function usePost(postId: number) {
  return useQuery({
    queryKey: ['post', postId],
    queryFn: async () => {
      const { post } = await request<{ post: Post }>(
        endpoint,
        gql`
        query {
          post(id: ${postId}) {  # Direct variable interpolation
            id
            title
            body  # Full post content for detail view
          }
        }
        `,
      )
      return post
    },
    enabled: !!postId,
  })
}
```

**What's happening:** The `postId` parameter is dynamically interpolated into the GraphQL query. The detail view requests additional fields (`body`) that the list view doesn't need.

**Why this works:** Simple template literal interpolation is often sufficient for basic variable injection. For complex scenarios, you can use GraphQL variables with the `request` function's variables parameter.

### 5. Cache-Aware UI with GraphQL

```tsx
style={
  queryClient.getQueryData(['post', post.id])
    ? { fontWeight: 'bold', color: 'green' }
    : {}
}
```

**What's happening:** The same cache inspection patterns work with GraphQL queries. Components can check if detail data is already cached and provide visual feedback.

**Why this matters:** GraphQL queries benefit from the same intelligent caching as REST APIs. Previously viewed posts load instantly, while background refetching keeps data fresh.

## Mental Model: GraphQL as Smart Async Functions

### Transport Agnostic Philosophy

TanStack Query's power comes from being transport-agnostic:

```
REST API:     fetch('/api/posts') → Promise<Post[]>
GraphQL:      request(gql`...`) → Promise<Post[]>  
gRPC:         client.getPosts() → Promise<Post[]>
LocalStorage: JSON.parse(...)  → Post[]

All work identically with TanStack Query!
```

This means you can migrate between data fetching approaches without changing your state management logic.

### GraphQL Query Composition

```
Component Data Requirements:
PostList: id, title (minimal data for list)
PostDetail: id, title, body, author (full data for details)

GraphQL Queries:
['posts'] → list query with minimal fields
['post', id] → detail query with full fields

Cache Structure:
Different query keys = Different cache entries
Perfect for different data shapes per component
```

### Type Safety Flow

```
GraphQL Schema → TypeScript Types → Query Response Types → Component Props

type Post = {          // From GraphQL schema
  id: number
  title: string  
  body: string
}

request<{ post: Post }> // Typed request
  ↓
useQuery<Post>         // Typed hook
  ↓  
{ data }: Post         // Typed component data
```

Full type safety from GraphQL schema to component rendering.

### Why It's Designed This Way: Flexibility Over Opinionation

Traditional GraphQL clients bundle everything:
```
Apollo Client = GraphQL Client + Cache + State Management + UI Integration
```

TanStack Query + GraphQL client separates concerns:
```
graphql-request = Pure GraphQL client
TanStack Query = Cache + State Management  
React = UI Integration
```

This separation enables:
- **Choice of GraphQL client** (Apollo, Relay, graphql-request, custom)
- **Incremental adoption** (migrate from REST without changing cache logic)  
- **Smaller bundles** (no heavyweight GraphQL client requirements)
- **Familiar patterns** (same Query patterns work with any transport)

### Advanced GraphQL Patterns

**GraphQL Variables**: For complex dynamic queries:
```tsx
const { data } = useQuery({
  queryKey: ['posts', filters],
  queryFn: () => request(
    endpoint,
    gql`
      query GetPosts($filters: PostFilters!) {
        posts(filters: $filters) {
          data { id title }
        }
      }
    `,
    { filters }
  )
})
```

**Fragment Composition**: Reusable GraphQL fragments:
```tsx
const POST_FRAGMENT = gql`
  fragment PostFields on Post {
    id
    title
    body
    author { name }
  }
`

const POST_QUERY = gql`
  query GetPost($id: ID!) {
    post(id: $id) {
      ...PostFields
    }
  }
  ${POST_FRAGMENT}
`
```

**Optimistic Updates with GraphQL**: Same patterns work with GraphQL mutations:
```tsx
const updatePostMutation = useMutation({
  mutationFn: ({ id, title }) => request(
    endpoint,
    gql`
      mutation UpdatePost($id: ID!, $title: String!) {
        updatePost(id: $id, input: { title: $title }) {
          id title
        }
      }
    `,
    { id, title }
  ),
  onMutate: async ({ id, title }) => {
    // Optimistic update
    queryClient.setQueryData(['post', id], old => ({ ...old, title }))
  }
})
```

**Error Handling**: GraphQL-specific error patterns:
```tsx
const { data, error } = useQuery({
  queryKey: ['posts'],
  queryFn: async () => {
    try {
      return await request(endpoint, POSTS_QUERY)
    } catch (error) {
      // Handle GraphQL errors vs network errors
      if (error.response?.errors) {
        throw new Error(error.response.errors[0].message)
      }
      throw error
    }
  }
})
```

### GraphQL-Specific Caching Strategies

**Normalized Caching**: Manually normalize GraphQL responses:
```tsx
const { data } = useQuery({
  queryKey: ['posts'],
  queryFn: fetchPosts,
  select: (data) => {
    // Cache individual posts for instant detail views
    data.posts.forEach(post => {
      queryClient.setQueryData(['post', post.id], post)
    })
    return data.posts
  }
})
```

**Smart Query Keys**: Include GraphQL operation info:
```tsx
// Include operation name and important variables in key
const queryKey = ['posts', 'GetPostsWithAuthor', { includeAuthor: true }]
```

**Field-Level Invalidation**: Invalidate based on GraphQL fields:
```tsx
// After updating a post
queryClient.invalidateQueries({ 
  queryKey: ['posts'], // Invalidate list
  exact: false 
})
queryClient.invalidateQueries({ 
  queryKey: ['post', postId] // Invalidate specific post
})
```

### Further Exploration

Experiment with GraphQL + TanStack Query patterns:

1. **Schema Exploration**: Try different GraphQL APIs and observe field selection benefits
2. **Type Generation**: Use tools like `graphql-codegen` for automatic TypeScript generation
3. **Performance Comparison**: Compare payload sizes between REST and GraphQL approaches
4. **Error Scenarios**: Test GraphQL-specific error handling (schema errors vs network errors)

**Advanced Challenges**:

1. **Subscription Integration**: How would you integrate GraphQL subscriptions with TanStack Query for real-time updates?

2. **Batch Queries**: How would you implement query batching to combine multiple GraphQL requests?

3. **Cache Normalization**: How would you implement Apollo-style normalized caching with TanStack Query?

4. **Persisted Queries**: How would you implement persisted queries for better performance?

**Real-World Applications**:
- **Modern Web Apps**: Leverage GraphQL's precise data fetching with Query's superior DX
- **Microservice Architectures**: Use GraphQL gateways with consistent caching patterns
- **Performance-Critical Apps**: Minimize payload sizes with field selection + intelligent caching
- **Type-Safe Applications**: Full end-to-end type safety from schema to UI
- **Legacy Migration**: Gradually adopt GraphQL while keeping existing caching patterns

GraphQL + TanStack Query creates a powerful, flexible foundation for modern data fetching that combines GraphQL's query capabilities with Query's proven caching and state management patterns. This approach enables teams to adopt GraphQL incrementally while maintaining familiar, battle-tested patterns for state management.