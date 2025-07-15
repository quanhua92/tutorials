# Getting Started: Your First Query

> **Based on**: [`examples/react/simple`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/simple)

## The Core Concept: Why This Example Exists

**The Problem:** Modern web applications need to fetch data from APIs, manage loading states, handle errors, and keep data fresh. Without a proper data management solution, developers end up writing repetitive boilerplate code for each API call, manually managing loading states, and struggling with cache invalidation.

**The Solution:** TanStack Query transforms this complexity into a simple, declarative API. At its heart, Query operates on a fundamental principle: **treat server state as a cache that automatically stays fresh**. Instead of manually orchestrating fetch calls and managing their lifecycle, you describe *what* data you need, and Query handles *how* to get it, cache it, and keep it synchronized.

The guiding philosophy is "stale-while-revalidate" - show cached data immediately (even if it's stale), then fetch fresh data in the background and update the UI when ready. This creates instant-feeling interfaces while ensuring data freshness.

## Practical Walkthrough: Code Breakdown

Let's examine the essential building blocks from `examples/react/simple/src/index.tsx`:

### 1. Setting Up the Query Foundation

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Example />
    </QueryClientProvider>
  )
}
```

**What's happening:** The `QueryClient` is your data management engine. It holds the cache, manages request lifecycles, and orchestrates all query behavior. The `QueryClientProvider` makes this client available throughout your React component tree via context.

**Why this design:** This follows React's context pattern, allowing any component deep in your tree to access the query client without prop drilling. The client is typically created once at your app's root and shared globally.

### 2. Your First Query

```tsx
function Example() {
  const { isPending, error, data, isFetching } = useQuery({
    queryKey: ['repoData'],
    queryFn: async () => {
      const response = await fetch('https://api.github.com/repos/TanStack/query')
      return await response.json()
    },
  })
}
```

**What's happening:** `useQuery` takes two essential pieces:
- `queryKey`: A unique identifier for this data (think of it as a cache key)
- `queryFn`: The function that actually fetches the data

The hook returns several pieces of state that represent the current status of your request.

**Why this works:** The query key serves as both a cache identifier and a dependency array. When the key changes, Query knows to refetch. When the key stays the same, Query can return cached data instantly.

### 3. Handling Query States

```tsx
if (isPending) return 'Loading...'
if (error) return 'An error has occurred: ' + error.message

return (
  <div>
    <h1>{data.full_name}</h1>
    <p>{data.description}</p>
    <div>{isFetching ? 'Updating...' : ''}</div>
  </div>
)
```

**What's happening:** Query provides distinct states for different phases:
- `isPending`: Initial loading (no cached data exists)
- `error`: Something went wrong
- `data`: The successfully fetched data
- `isFetching`: Any time a request is in flight (including background updates)

**Why this granularity:** The distinction between `isPending` and `isFetching` is crucial. You want to show a spinner only on initial load (`isPending`), but maybe just a subtle indicator during background updates (`isFetching`).

### 4. Development Tools Integration

```tsx
import { ReactQueryDevtools } from '@tanstack/react-query-devtools'

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ReactQueryDevtools />
      <Example />
    </QueryClientProvider>
  )
}
```

**What's happening:** The devtools provide a visual interface to inspect your queries, their states, and cached data.

**Why include this:** Query's cache behavior can seem magical at first. The devtools make it transparent, helping you understand when queries run, what data is cached, and why certain behaviors occur.

## Mental Model: Thinking in TanStack Query

### The Cache-First Mindset

Think of TanStack Query as an intelligent cache that sits between your components and your API. Here's the mental model:

```
[Component] ←→ [Query Cache] ←→ [API Server]
```

When you call `useQuery`:

1. **Cache Check**: Query first looks in its cache using your `queryKey`
2. **Instant Return**: If data exists, return it immediately (even if stale)
3. **Background Sync**: Simultaneously fetch fresh data from the server
4. **Smart Update**: When fresh data arrives, update the cache and re-render components

This is fundamentally different from traditional approaches where you either wait for the network or manually manage cache invalidation.

### Query Keys as Dependencies

Query keys work like React's dependency arrays, but for server data:

```tsx
// These are different queries with separate cache entries
useQuery({ queryKey: ['user', 1], queryFn: () => fetchUser(1) })
useQuery({ queryKey: ['user', 2], queryFn: () => fetchUser(2) })
useQuery({ queryKey: ['posts', { page: 1 }], queryFn: () => fetchPosts(1) })
```

When any part of the query key changes, Query treats it as a new request. This makes data fetching reactive to your component's state.

### Why It's Designed This Way: Declarative Data Fetching

Traditional imperative approach:
```tsx
// ❌ Manual lifecycle management
useEffect(() => {
  setLoading(true)
  fetchRepo()
    .then(setData)
    .catch(setError)
    .finally(() => setLoading(false))
}, [])
```

TanStack Query's declarative approach:
```tsx
// ✅ Describe what you need, not how to get it
const { data, isPending, error } = useQuery({
  queryKey: ['repo'],
  queryFn: fetchRepo
})
```

The declarative approach reduces bugs, eliminates boilerplate, and makes data requirements explicit and composable.

### Further Exploration

Try this experiment to deepen your understanding:

1. **Network Throttling**: Open DevTools → Network → Throttle to "Slow 3G"
2. **Tab Switching**: Load the page, switch to another tab, then return
3. **Observe**: Notice how Query automatically refetches when you return to the tab

**Question to ponder**: Why does Query refetch when you return to the tab? What user problem does this solve?

This automatic "focus refetching" ensures your users always see fresh data when they return to your app, creating a responsive, desktop-app-like experience in the browser.