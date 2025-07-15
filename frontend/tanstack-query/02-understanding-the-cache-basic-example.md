# Understanding the Cache: Multiple Queries & Persistence

> **Based on**: [`examples/react/basic`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/basic)

## The Core Concept: Why This Example Exists

**The Problem:** Real applications don't just fetch single pieces of data - they manage relationships between different data sets, navigate between views, and need to persist data across page reloads. Without proper cache management, users experience unnecessary loading spinners, redundant network requests, and data that disappears when they refresh the page.

**The Solution:** TanStack Query's cache is not just a simple key-value store - it's an intelligent data layer that understands relationships, automatically manages background updates, and can persist across browser sessions. The cache serves as a **single source of truth** for all server state in your application.

This example demonstrates the cache's two most powerful features: **instant cache hits** (returning to previously loaded data shows instantly) and **background synchronization** (keeping cached data fresh without blocking the UI).

## Practical Walkthrough: Code Breakdown

Let's explore the multi-query architecture from `examples/react/basic/src/index.tsx`:

### 1. Enhanced Query Client Configuration

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: 1000 * 60 * 60 * 24, // 24 hours
    },
  },
})
```

**What's happening:** We're extending the garbage collection time to 24 hours, meaning cached data stays in memory much longer than the default 5 minutes.

**Why this matters:** Longer cache retention means better user experience - users can navigate back to previously viewed content and see it instantly, even after extended periods of browsing other parts of the app.

### 2. Cache Persistence Setup

```tsx
const persister = createAsyncStoragePersister({
  storage: window.localStorage,
})

function App() {
  return (
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{ persister }}
    >
      {/* app content */}
    </PersistQueryClientProvider>
  )
}
```

**What's happening:** The `PersistQueryClientProvider` automatically saves cache data to localStorage and restores it on page load.

**Why this design:** Users expect web apps to remember their data across sessions, just like native apps. Cache persistence creates this native-app-like experience while requiring zero additional code in your components.

### 3. Multiple Related Queries

```tsx
// Posts list query
function usePosts() {
  return useQuery({
    queryKey: ['posts'],
    queryFn: async (): Promise<Array<Post>> => {
      const response = await fetch('https://jsonplaceholder.typicode.com/posts')
      return await response.json()
    },
  })
}

// Individual post query
function usePost(postId: number) {
  return useQuery({
    queryKey: ['post', postId],
    queryFn: () => getPostById(postId),
    enabled: !!postId,
  })
}
```

**What's happening:** We have two distinct query patterns:
- `['posts']` - fetches the entire list
- `['post', postId]` - fetches individual posts by ID

**Why separate queries:** This creates a flexible cache structure where list data and detail data are independently cached. You can prefetch individual posts, cache them separately, and display them instantly when users navigate to detail views.

### 4. Smart Cache Indicators

```tsx
<a
  onClick={() => setPostId(post.id)}
  href="#"
  style={
    queryClient.getQueryData(['post', post.id])
      ? { fontWeight: 'bold', color: 'green' }
      : {}
  }
>
  {post.title}
</a>
```

**What's happening:** The UI visually indicates which posts have been cached by checking if `queryClient.getQueryData(['post', post.id])` returns data.

**Why this pattern:** Visual cache indicators help users understand app behavior and provide immediate feedback about which content will load instantly vs. require a network request.

### 5. Conditional Query Execution

```tsx
function usePost(postId: number) {
  return useQuery({
    queryKey: ['post', postId],
    queryFn: () => getPostById(postId),
    enabled: !!postId, // Only run when postId is truthy
  })
}
```

**What's happening:** The `enabled` option prevents the query from running when `postId` is falsy (-1 in this case).

**Why this control:** Conditional queries prevent unnecessary network requests and errors. This pattern is essential for dependent queries or queries that should only run under certain conditions.

### 6. Background Update Indicators

```tsx
<div>{isFetching ? 'Background Updating...' : ' '}</div>
```

**What's happening:** Both the list and detail views show when background updates are occurring, even when cached data is already displayed.

**Why show this:** Transparent background activity builds user trust and helps them understand when they're seeing the freshest possible data.

## Mental Model: The Living Cache

### Cache as a Graph Database

Think of Query's cache as a graph where each query key represents a node:

```
Cache Graph:
['posts'] ──┐
            ├──── Contains references to post IDs
            │
['post', 1] ──── Individual post data
['post', 2] ──── Individual post data  
['post', 3] ──── Individual post data
```

Unlike a simple key-value store, Query's cache understands these relationships and can:
- Automatically invalidate related data
- Provide intelligent cache hits
- Optimize network requests based on existing data

### Stale-While-Revalidate in Action

Here's what happens when you click on a cached post:

```
1. User clicks post link
2. Query checks cache for ['post', 42]
3. Cache hit! → Instantly render cached data
4. Simultaneously → Start background fetch for fresh data
5. When fresh data arrives → Seamlessly update UI
6. User never sees a loading spinner for cached content
```

This pattern eliminates the traditional trade-off between performance (showing stale data) and freshness (always fetching). You get both.

### Why It's Designed This Way: Optimistic UX

Traditional approach - users wait for every navigation:
```
Click → Loading → Content → Click → Loading → Content
```

Query's approach - instant for cached content:
```
Click → Instant Content → Background Update
Click → Instant Content → Background Update
```

This creates a fluid, app-like experience where users rarely wait for content they've seen before.

### Cache Lifecycle Management

Query automatically manages cache lifecycle with three key phases:

1. **Active**: Query is currently being used by a component
2. **Inactive**: No components using this query, but data remains cached
3. **Garbage Collected**: Data is removed after `gcTime` expires

This automatic cleanup prevents memory leaks while maximizing cache hits for user navigation patterns.

### Further Exploration

Try this experiment to understand cache behavior:

1. **Load the app** and navigate to several posts
2. **Refresh the page** - notice data persists due to localStorage
3. **Open DevTools** → Application → Local Storage → see cached data
4. **Navigate between posts** - observe instant loading for visited posts
5. **Watch the network tab** - see background updates even for cached content

**Question to ponder**: How would you handle cache invalidation if you added the ability to edit posts? What queries would need to be invalidated when a post is updated?

Understanding these cache patterns is foundational - they're the building blocks for more complex patterns like optimistic updates, prefetching, and real-time synchronization.