# Infinite Scroll with Intersection Observer

> **Based on**: [`examples/react/load-more-infinite-scroll`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/load-more-infinite-scroll)

## The Core Concept: Why This Example Exists

**The Problem:** Users expect modern apps to load content seamlessly as they scroll, without clicking "Load More" buttons. However, implementing infinite scroll manually involves complex coordination between scroll events, page boundaries, loading states, and error handling. Performance degrades quickly when not implemented correctly.

**The Solution:** TanStack Query's `useInfiniteQuery` treats infinite scroll as a **continuous data stream** where each "page" is a segment of an unbounded dataset. Combined with the Intersection Observer API, this creates buttery-smooth infinite scroll experiences that handle edge cases automatically.

The key insight: infinite scroll is really **paginated data with automatic page triggers**. By modeling it this way, you get all the benefits of pagination (caching, error recovery, prefetching) with the UX of seamless scrolling.

## Practical Walkthrough: Code Breakdown

Let's examine the infinite scroll mechanics from `examples/react/load-more-infinite-scroll/src/pages/index.tsx`:

### 1. Infinite Query Configuration

```tsx
const {
  status,
  data,
  error,
  isFetching,
  isFetchingNextPage,
  isFetchingPreviousPage,
  fetchNextPage,
  fetchPreviousPage,
  hasNextPage,
  hasPreviousPage,
} = useInfiniteQuery({
  queryKey: ['projects'],
  queryFn: async ({ pageParam }): Promise<{
    data: Array<{ name: string; id: number }>
    previousId: number
    nextId: number
  }> => {
    const response = await fetch(`/api/projects?cursor=${pageParam}`)
    return await response.json()
  },
  initialPageParam: 0,
  getPreviousPageParam: (firstPage) => firstPage.previousId,
  getNextPageParam: (lastPage) => lastPage.nextId,
})
```

**What's happening:** `useInfiniteQuery` extends the basic query pattern with page parameters and bidirectional navigation. Each fetch returns both data and cursors for the next/previous pages.

**Key differences from `useQuery`:**
- `pageParam`: Dynamic parameter passed to each page fetch
- `getNextPageParam`/`getPreviousPageParam`: Functions that extract cursors for adjacent pages
- Returns page management functions (`fetchNextPage`, `hasNextPage`, etc.)

**Why cursor-based pagination:** Cursors (like `nextId: 42`) provide stable pagination that handles real-time data changes better than offset-based pagination (`page: 2`).

### 2. Intersection Observer Integration

```tsx
import { useInView } from 'react-intersection-observer'

function Example() {
  const { ref, inView } = useInView()
  
  React.useEffect(() => {
    if (inView) {
      fetchNextPage()
    }
  }, [fetchNextPage, inView])
}
```

**What's happening:** The `useInView` hook provides a ref and boolean indicating when that element enters the viewport. When the trigger element becomes visible, automatically fetch the next page.

**Why Intersection Observer:** More performant than scroll event listeners, and automatically handles complex scenarios like nested scrollable containers and viewport changes.

### 3. Rendering Flattened Page Data

```tsx
{data.pages.map((page) => (
  <React.Fragment key={page.nextId}>
    {page.data.map((project) => (
      <p key={project.id}>{project.name}</p>
    ))}
  </React.Fragment>
))}
```

**What's happening:** `data.pages` is an array of page objects. Each page contains the fetched items plus pagination metadata. We flatten this into a continuous list while maintaining React keys.

**Why fragment with page keys:** Each page gets its own React Fragment with a stable key (`page.nextId`), enabling efficient re-renders when pages are added/removed.

### 4. Bidirectional Loading Controls

```tsx
<button
  onClick={() => fetchPreviousPage()}
  disabled={!hasPreviousPage || isFetchingPreviousPage}
>
  {isFetchingPreviousPage
    ? 'Loading more...'
    : hasPreviousPage
      ? 'Load Older'
      : 'Nothing more to load'}
</button>

<button
  ref={ref}  // Intersection observer target
  onClick={() => fetchNextPage()}
  disabled={!hasNextPage || isFetchingNextPage}
>
  {isFetchingNextPage
    ? 'Loading more...'
    : hasNextPage
      ? 'Load Newer'
      : 'Nothing more to load'}
</button>
```

**What's happening:** Both manual buttons and automatic scroll triggers coexist. The "Load Newer" button has the intersection observer ref, triggering automatic loading when it becomes visible.

**Why hybrid approach:** Provides both automatic scroll behavior and explicit user control. Users can manually trigger loads if automatic triggering fails or is disabled.

### 5. Granular Loading States

```tsx
{isFetching && !isFetchingNextPage
  ? 'Background Updating...'
  : null}
```

**What's happening:** Distinguish between different types of loading:
- `isFetchingNextPage`: Loading additional content
- `isFetchingPreviousPage`: Loading historical content  
- `isFetching && !isFetchingNextPage`: Background refresh of existing pages

**Why separate these states:** Users need different feedback for "getting more content" vs. "refreshing existing content" vs. "loading historical content."

## Mental Model: Infinite Data Streams

### The Page Window Concept

Think of infinite queries as managing a **sliding window** over an unbounded data stream:

```
Infinite Data Stream:
[...][Page -2][Page -1][Page 0][Page 1][Page 2][...]
                         ↑
                    Current Window
```

The window can expand in both directions:
- **Forward**: `fetchNextPage()` adds pages to the right
- **Backward**: `fetchPreviousPage()` adds pages to the left

### Cache Structure for Infinite Data

```
Query Cache:
['projects'] → {
  pages: [
    { data: [...], nextId: 10, previousId: null },    // Page 0
    { data: [...], nextId: 20, previousId: 10 },      // Page 1  
    { data: [...], nextId: 30, previousId: 20 },      // Page 2
  ],
  pageParams: [0, 10, 20]  // Parameters used to fetch each page
}
```

Unlike regular pagination, all pages accumulate in a single cache entry, creating the continuous stream effect.

### Cursor-Based Navigation

```
Page Boundaries:
Page 0: Items 1-10   (nextId: 10, previousId: null)
Page 1: Items 11-20  (nextId: 20, previousId: 10)
Page 2: Items 21-30  (nextId: 30, previousId: 20)
```

Cursors provide stable references that work even when the underlying data changes (new items added, items deleted, etc.).

### Why It's Designed This Way: Seamless User Experience

Traditional pagination breaks content flow:
```
Page 1 → Click → Loading → Page 2 (context break)
```

Infinite scroll maintains flow:
```
Page 1 → Scroll → Page 1 + Page 2 (continuous context)
```

### Performance Considerations

**Memory Management**: Infinite queries can accumulate large amounts of data. Consider implementing page limits or manual cleanup for very long sessions.

**Render Optimization**: Large lists benefit from virtualization (rendering only visible items). Libraries like `react-window` work well with infinite queries.

**Network Efficiency**: `useInfiniteQuery` automatically deduplicates concurrent requests and handles race conditions.

### Error Handling Patterns

```tsx
// Page-level error handling
{status === 'error' && <div>Error loading initial data</div>}

// Next page error handling  
{hasNextPage && nextPageError && (
  <div>
    Error loading more items
    <button onClick={() => fetchNextPage()}>Retry</button>
  </div>
)}
```

Infinite queries can fail at different levels - initial load, specific page fetches, or background refreshes. Each needs appropriate user feedback.

### Further Exploration

Experiment with these patterns to deepen understanding:

1. **Scroll Performance**: Try with large datasets and observe memory usage
2. **Network Interruption**: Disable network mid-scroll and test recovery
3. **Bidirectional Loading**: Use both previous/next page loading
4. **Viewport Triggers**: Try different intersection observer configurations

**Advanced Challenges**:

1. **Virtual Scrolling**: How would you combine infinite queries with virtualization for million-item lists?

2. **Real-time Updates**: How would you handle new items being added to the beginning of an infinite list?

3. **Search Integration**: How would you implement infinite scroll for search results that can change?

4. **Memory Cleanup**: Implement automatic cleanup of old pages when the list gets too long.

**Real-World Applications**:
- Social media feeds (Twitter, Instagram)
- E-commerce product listings  
- Chat message history
- File explorers with large directories
- Log viewing interfaces

The infinite query pattern scales from simple "load more" buttons to complex, real-time, bidirectional data streams. Understanding these fundamentals enables building sophisticated, performant data-heavy interfaces that feel natural and responsive.