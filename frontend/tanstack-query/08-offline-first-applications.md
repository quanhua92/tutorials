# Offline-First Applications: Building Resilient UIs

> **Based on**: [`examples/react/offline`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/offline)

## The Core Concept: Why This Example Exists

**The Problem:** Modern web applications are expected to work reliably regardless of network conditions. Users don't want to lose their work when networks are spotty, nor do they want to see blank screens when briefly offline. Traditional web apps fail gracefully at best, catastrophically at worst, when networks become unavailable.

**The Solution:** **Offline-first architecture** treats network availability as an enhancement, not a requirement. TanStack Query provides the foundation for this approach by automatically pausing mutations when offline, resuming them when connectivity returns, and intelligently managing cached data to provide immediate feedback even without network access.

The key insight: **offline isn't an edge case, it's a fundamental state** that needs first-class support. Query's offline handling transforms network interruptions from app-breaking failures into transparent background operations.

## Practical Walkthrough: Code Breakdown

Let's examine the offline-first patterns from `examples/react/offline/src/App.tsx`:

### 1. Offline-Aware Query Client Configuration

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      gcTime: 1000 * 60 * 60 * 24, // 24 hours
      staleTime: 2000,
      retry: 0, // Don't retry failed requests automatically
    },
  },
  mutationCache: new MutationCache({
    onSuccess: (data) => toast.success(data.message),
    onError: (error) => toast.error(error.message),
  }),
})
```

**What's happening:** Extended garbage collection time (24 hours) ensures data remains available for longer periods offline. Setting `retry: 0` prevents endless retry loops when genuinely offline.

**Why these settings:** Offline-first apps need to balance data freshness with availability. Longer cache times provide more offline content, while disabling automatic retries prevents battery drain and network spam.

### 2. Mutation Defaults for Persistence

```tsx
queryClient.setMutationDefaults(movieKeys.all(), {
  mutationFn: async ({ id, comment }) => {
    await queryClient.cancelQueries({ queryKey: movieKeys.detail(id) })
    return api.updateMovie(id, comment)
  },
})
```

**What's happening:** Default mutation functions ensure that paused mutations can resume after page reloads. Without this, refreshing the page would lose pending offline mutations.

**Why cancellation first:** Cancel ongoing queries before mutations to prevent race conditions between optimistic updates and server responses when coming back online.

### 3. Persistence with Resume Logic

```tsx
<PersistQueryClientProvider
  client={queryClient}
  persistOptions={{ persister }}
  onSuccess={() => {
    queryClient.resumePausedMutations().then(() => {
      queryClient.invalidateQueries()
    })
  }}
>
```

**What's happening:** After restoring cached data from localStorage, automatically resume any mutations that were paused due to being offline, then invalidate queries to get fresh data.

**The sequence matters:**
1. Restore cache from localStorage
2. Resume paused mutations (process offline actions)
3. Invalidate queries (fetch fresh data when online)

### 4. Router Integration with Offline Awareness

```tsx
loader: ({ params: { movieId } }) =>
  queryClient.getQueryData(movieKeys.detail(movieId)) ??
  (onlineManager.isOnline() && !isRestoring
    ? queryClient.fetchQuery({
        queryKey: movieKeys.detail(movieId),
        queryFn: () => api.fetchMovie(movieId),
      })
    : undefined),
```

**What's happening:** Route loaders check for cached data first, only fetching from the network if online and not currently restoring from persistence.

**Why this pattern:** Prevents route-level loading failures when offline, allowing navigation between cached content while avoiding network requests that would fail.

### 5. Multi-State UI Feedback

```tsx
function Detail() {
  const { updateMovie, movieQuery } = useMovie(movieId)
  
  return (
    <div>
      {updateMovie.isPaused
        ? 'mutation paused - offline'
        : updateMovie.isPending && 'updating...'}
    </div>
  )
}
```

**What's happening:** Different UI states for different mutation scenarios:
- `isPaused`: Mutation is queued, waiting for network connectivity
- `isPending`: Mutation is actively being processed
- Success/Error: Standard completion states

**Why distinguish paused vs pending:** Users need to understand whether their action succeeded, is processing, or is waiting for connectivity. Each state requires different expectations and potential actions.

### 6. Graceful Offline Fallbacks

```tsx
if (movieQuery.isPaused) {
  return "We're offline and have no data to show :("
}
```

**What's happening:** When completely offline with no cached data, provide clear messaging rather than infinite loading states or cryptic errors.

**Why explicit offline messaging:** Users understand network issues better than technical error messages. Clear offline indicators set appropriate expectations.

## Mental Model: The Offline-First State Machine

### Network States and Data Flow

```
Online State Machine:
Online ────────► Offline ────────► Online
  ↓               ↓                 ↓
Fetch Fresh    Use Cache      Resume + Fetch
  ↓               ↓                 ↓  
Show Data      Pause Mutations   Process Queue
```

Query automatically transitions between these states based on network availability, ensuring the app remains functional throughout.

### Cache Layers for Offline Resilience

```
Data Availability Hierarchy:
1. Fresh Data (just fetched)
2. Stale Data (cached, older than staleTime)  
3. Persisted Data (from localStorage)
4. No Data (truly offline, never cached)
```

The app gracefully degrades through these layers, always trying to show something useful to the user.

### Mutation Queue Management

```
Offline Mutation Queue:
[Update Movie A] → [Add Comment B] → [Delete Item C]
       ↓
When Online: Process in order, handle failures gracefully
```

Mutations queue automatically when offline and process sequentially when connectivity returns, maintaining data consistency.

### Why It's Designed This Way: Progressive Enhancement

Traditional approach - network dependency:
```
User Action → Network Request → Success/Failure
              ↓ (if offline)
              Total Failure
```

Offline-first approach - graceful degradation:
```
User Action → Optimistic Update → Queue Mutation → Background Sync
              ↓ (always)           ↓ (when offline)  ↓ (when online)
              Immediate Feedback   Queued for Later  Server Sync
```

### Advanced Offline Patterns

**Conflict Resolution**: Handle conflicts when multiple clients modify the same data offline:
```tsx
const updateMovie = useMutation({
  mutationFn: api.updateMovie,
  onError: (error) => {
    if (error.status === 409) { // Conflict
      // Show conflict resolution UI
      showConflictResolution(error.conflictData)
    }
  }
})
```

**Selective Sync**: Allow users to control what syncs when bandwidth is limited:
```tsx
const priorityMutations = mutations.filter(m => m.meta?.priority === 'high')
await processMutations(priorityMutations)
```

**Background Sync**: Use service workers for sync when the main app isn't open:
```tsx
// In service worker
self.addEventListener('sync', (event) => {
  if (event.tag === 'query-sync') {
    event.waitUntil(resumePausedMutations())
  }
})
```

### Error Recovery Strategies

**Optimistic Recovery**: Show success, handle errors in background:
```tsx
const mutation = useMutation({
  mutationFn: api.updateData,
  onMutate: async (newData) => {
    // Show optimistic update immediately
    return optimisticUpdate(newData)
  },
  onError: (err, newData, context) => {
    // Revert optimistic update, show error
    revertOptimisticUpdate(context)
  }
})
```

**Retry Strategies**: Intelligent retry with exponential backoff:
```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    mutations: {
      retry: (failureCount, error) => {
        if (error.status === 404) return false // Don't retry not found
        if (failureCount < 3) return true      // Retry up to 3 times
        return false
      },
      retryDelay: attemptIndex => Math.min(1000 * 2 ** attemptIndex, 30000)
    }
  }
})
```

### Further Exploration

Experiment with offline behavior:

1. **Network Simulation**: Use DevTools to simulate offline/online transitions
2. **Persistence Testing**: Refresh the page while offline and observe data restoration
3. **Mutation Queuing**: Perform multiple actions offline, then go online
4. **Conflict Handling**: Simulate concurrent edits from multiple clients

**Advanced Challenges**:

1. **Real-time Sync**: How would you handle real-time data updates (WebSocket, SSE) in offline-first apps?

2. **Large Data Sets**: How would you handle offline sync for apps with millions of records?

3. **Partial Sync**: How would you implement selective synchronization for bandwidth-limited scenarios?

4. **Collaborative Editing**: How would you build Google Docs-style collaborative editing with offline support?

**Real-World Applications**:
- Field service apps (technicians in areas with poor connectivity)
- Healthcare apps (critical data access regardless of network)
- Travel apps (offline maps, itineraries, booking confirmations)
- Creative tools (photo editing, writing apps that can't lose work)
- Point-of-sale systems (must continue operating during network outages)

The offline-first approach transforms web applications from network-dependent services into robust, resilient tools that work reliably in any connectivity scenario. Understanding these patterns is essential for building applications that users can trust with important data and critical workflows.