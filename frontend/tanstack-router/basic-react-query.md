# React Query Integration: Server State Meets Routing

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/basic-react-query)**

## The Core Concept: Why This Example Exists

**The Problem:** Modern applications need sophisticated data management that goes beyond simple route loading. Users expect instant navigation, background updates, optimistic caching, and seamless error recovery. Traditional route loaders provide data for initial loads but lack the advanced caching, background refetching, and error handling capabilities that users expect from modern applications.

**The TanStack Solution:** TanStack Router integrates seamlessly with TanStack Query (formerly React Query) to provide the best of both worlds: route-level data dependencies with advanced server state management. Think of it like having a professional data manager who not only ensures data is ready when you need it, but also keeps it fresh, handles errors gracefully, and provides instant access to cached data.

This integration allows routes to define their data requirements using query options, while TanStack Query handles caching, background updates, error recovery, and optimistic updates automatically.

---

## Practical Walkthrough: Code Breakdown

### Query Client Integration (`main.tsx:25-27, 247-260`)

```tsx
const rootRoute = createRootRouteWithContext<{
  queryClient: QueryClient
}>()({
  component: RootComponent,
})

const queryClient = new QueryClient()

const router = createRouter({
  routeTree,
  defaultPreloadStaleTime: 0, // Important for React Query integration
  context: { queryClient },
})
```

This establishes the foundation for Router + Query integration:

- **Typed context**: The root route is created with TypeScript knowledge of the query client
- **Context injection**: The QueryClient instance is made available to all routes
- **Stale time configuration**: Setting `defaultPreloadStaleTime: 0` ensures routes always check for fresh data

### Query Options Pattern (`posts.ts:35-44`)

```tsx
export const postQueryOptions = (postId: string) =>
  queryOptions({
    queryKey: ['posts', { postId }],
    queryFn: () => fetchPost(postId),
  })

export const postsQueryOptions = queryOptions({
  queryKey: ['posts'],
  queryFn: () => fetchPosts(),
})
```

Query options are the bridge between TanStack Router and TanStack Query:

- **Reusable definitions**: Query options can be used in both route loaders and components
- **Type safety**: TypeScript ensures query keys and functions match throughout the app
- **Hierarchical keys**: The `['posts', { postId }]` pattern enables smart cache invalidation

### Route-Level Data Preloading (`main.tsx:103-105, 121-123`)

```tsx
const postsLayoutRoute = createRoute({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(postsQueryOptions),
}).lazy(() => import('./posts.lazy').then((d) => d.Route))

const postRoute = createRoute({
  loader: ({ context: { queryClient }, params: { postId } }) =>
    queryClient.ensureQueryData(postQueryOptions(postId)),
  component: PostRouteComponent,
})
```

This demonstrates the key integration pattern:

- **ensureQueryData**: Preloads data into the React Query cache if not already present
- **Context access**: Routes access the QueryClient through the router context
- **Parameter integration**: Route parameters seamlessly flow into query options

### Component-Level Query Usage (`posts.lazy.tsx:10-13, main.tsx:152-155`)

```tsx
function PostsLayoutComponent() {
  const postsQuery = useSuspenseQuery(postsQueryOptions)
  const posts = postsQuery.data
  
  return (
    <div>
      {posts.map(post => <PostLink key={post.id} post={post} />)}
    </div>
  )
}

function PostRouteComponent() {
  const { postId } = postRoute.useParams()
  const postQuery = useSuspenseQuery(postQueryOptions(postId))
  const post = postQuery.data
  
  return <div>{post.title}</div>
}
```

Components use the same query options as routes:

- **useSuspenseQuery**: Works seamlessly with route loaders - data is already in cache
- **No loading states needed**: Since routes preload data, components receive it immediately
- **Consistent data access**: Same query options ensure components and routes stay synchronized

### Advanced Error Handling (`main.tsx:126-149`)

```tsx
function PostErrorComponent({ error }: ErrorComponentProps) {
  const router = useRouter()
  const queryErrorResetBoundary = useQueryErrorResetBoundary()

  React.useEffect(() => {
    queryErrorResetBoundary.reset()
  }, [queryErrorResetBoundary])

  return (
    <div>
      <button
        onClick={() => {
          router.invalidate()
        }}
      >
        retry
      </button>
      <ErrorComponent error={error} />
    </div>
  )
}
```

Error boundaries integrate with both Router and Query:

- **Query error reset**: Clears React Query error states when route errors occur
- **Router invalidation**: Re-runs route loaders on retry
- **Coordinated recovery**: Both systems work together for seamless error recovery

### Provider Integration (`main.tsx:274-279`)

```tsx
root.render(
  <QueryClientProvider client={queryClient}>
    <RouterProvider router={router} />
  </QueryClientProvider>
)
```

The provider hierarchy ensures both systems share the same QueryClient instance.

---

## Mental Model: Thinking in Router + Query

### The Data Flow Symphony

Traditional routing with data fetching often creates waterfall loading:
```
1. Navigate to route
2. Route component mounts
3. Component starts data fetch
4. Loading state displays
5. Data arrives, component updates
```

Router + Query integration orchestrates this differently:
```
1. Navigate to route
2. Route loader ensures data is in cache
3. Component mounts with data immediately available
4. Background refetch keeps data fresh
5. Optimistic updates provide instant feedback
```

### Cache as Shared Memory

Think of the React Query cache as shared memory between routes and components:

```tsx
// Route "deposits" data into cache
const route = createRoute({
  loader: ({ context: { queryClient } }) =>
    queryClient.ensureQueryData(postQueryOptions(postId))
})

// Component "withdraws" data from same cache
function PostComponent() {
  const query = useSuspenseQuery(postQueryOptions(postId))
  // Data is instantly available!
}
```

This shared cache enables:
- **Instant navigation**: Data is often already cached from previous visits
- **Background freshness**: Data updates in the background without blocking navigation
- **Optimistic updates**: Mutations can update cache immediately, then sync with server

### Query Options as Contracts

Query options serve as contracts between different parts of your application:

```tsx
export const postQueryOptions = (postId: string) =>
  queryOptions({
    queryKey: ['posts', { postId }],
    queryFn: () => fetchPost(postId),
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000,   // 10 minutes
  })
```

This contract says:
- "Data for this post is identified by `['posts', { postId }]`"
- "Fresh data can be fetched using `fetchPost(postId)`"
- "Data stays fresh for 5 minutes"
- "Cache this data for 10 minutes after last use"

Any code using these options gets the same caching behavior automatically.

### Route Hierarchy and Cache Invalidation

The hierarchical structure of routes maps naturally to query key hierarchies:

```tsx
// Route structure:
/posts                    → ['posts'] query
/posts/123               → ['posts', { postId: '123' }] query
/posts/123/comments      → ['posts', { postId: '123' }, 'comments'] query

// Invalidation patterns:
queryClient.invalidateQueries(['posts'])                    // Invalidates all posts
queryClient.invalidateQueries(['posts', { postId: '123' }]) // Invalidates specific post
```

This hierarchy enables smart cache management where invalidating parent queries also invalidates child queries.

### The Preload + Suspense Pattern

The combination of route preloading and Suspense queries creates a powerful pattern:

1. **Route loader**: Ensures data is in cache before component renders
2. **useSuspenseQuery**: Immediately returns cached data, no loading states needed
3. **Background refetch**: Keeps data fresh automatically
4. **Error boundaries**: Handle both route and query errors gracefully

```tsx
// This pattern eliminates most loading states from your components
function MyComponent() {
  const data = useSuspenseQuery(myQueryOptions)
  // data is ALWAYS available here, no loading state needed!
  return <div>{data.title}</div>
}
```

### Performance Optimizations

The Router + Query integration enables several performance optimizations:

- **Intent-based preloading**: Data loads when users hover over links
- **Parallel data loading**: Multiple queries can load simultaneously during route transitions
- **Background refetching**: Fresh data loads without blocking UI
- **Intelligent caching**: Duplicate requests are deduped automatically

### Further Exploration

Experiment with these advanced patterns:

1. **Dependent queries**: Create routes that load data depending on other data (user → user's posts → post comments).

2. **Optimistic mutations**: Implement mutations that update the cache immediately, then sync with the server.

3. **Infinite queries**: Use `useInfiniteQuery` for paginated data that loads more as users scroll.

4. **Cache prefetching**: Prefetch data for routes users are likely to visit next.

5. **Real-time updates**: Combine with WebSockets to keep cached data synchronized with real-time server updates.

6. **Error recovery strategies**: Implement sophisticated retry logic and offline support.

The power of TanStack Router + TanStack Query integration lies in making complex data management feel simple. Routes declare what data they need, queries handle all the complexity of caching and freshness, and components receive data instantly without worrying about loading states.