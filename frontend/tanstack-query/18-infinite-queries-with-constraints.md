# Infinite Queries with Constraints

> **Based on**: [`examples/react/infinite-query-with-max-pages`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/infinite-query-with-max-pages)

## The Core Concept: Why This Example Exists

**The Problem:** While infinite queries provide seamless data loading, they can consume excessive memory and network resources in long-running sessions. Users scrolling through thousands of items can overwhelm both client memory and server resources. Applications need **bounded infinite scroll** that provides the UX benefits of continuous loading while maintaining performance and resource constraints.

**The Solution:** TanStack Query's `maxPages` option enables **sliding window infinite queries** where old pages are automatically removed as new pages are added. This creates fixed-memory infinite scroll that maintains constant performance regardless of session length while preserving the seamless user experience.

The key insight: **infinite doesn't mean unlimited** - smart applications balance infinite UX with finite resources by implementing sliding windows, intelligent page management, and strategic cache boundaries.

## Practical Walkthrough: Code Breakdown

Let's examine the constrained infinite query patterns from `examples/react/infinite-query-with-max-pages/src/pages/index.tsx`:

### 1. Max Pages Configuration

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
  queryFn: async ({ pageParam }) => {
    const response = await fetch(`/api/projects?cursor=${pageParam}`)
    return await response.json()
  },
  initialPageParam: 0,
  getPreviousPageParam: (firstPage) => firstPage.previousId ?? undefined,
  getNextPageParam: (lastPage) => lastPage.nextId ?? undefined,
  maxPages: 3, // Key constraint: only keep 3 pages in memory
})
```

**What's happening:** The `maxPages: 3` configuration creates a sliding window of exactly 3 pages. As users scroll forward, old pages are automatically removed; as they scroll backward, newer pages are discarded.

**Why constrain pages:** Prevents memory bloat during extended sessions while maintaining smooth scrolling experience. Users get infinite scroll UX with bounded resource usage.

### 2. Bidirectional Navigation with Constraints

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

**What's happening:** Both forward and backward navigation work seamlessly with page constraints. The UI adapts based on available pages and loading states.

**Why bidirectional constraints:** Users can navigate in both directions while the system maintains the 3-page window. Scrolling forward removes oldest pages; scrolling backward removes newest pages.

### 3. Page Window Management

```tsx
{data.pages.map((page) => (
  <React.Fragment key={page.nextId}>
    {page.data.map((project) => (
      <p key={project.id}>{project.name}</p>
    ))}
  </React.Fragment>
))}
```

**What's happening:** Only the pages within the constraints are rendered. If max pages is 3, only 3 pages worth of data are displayed and in memory.

**Why fragment-based rendering:** Each page maintains its own React Fragment with stable keys, enabling efficient updates when pages are added/removed from the window.

### 4. Loading State Coordination

```tsx
{isFetching && !isFetchingNextPage
  ? 'Background Updating...'
  : null}
```

**What's happening:** Distinguish between page-specific loading (`isFetchingNextPage`) and general background updates (`isFetching` without page specificity).

**Why separate indicators:** Users need different feedback for "loading new content" vs "refreshing existing content" vs "background cache updates."

## Mental Model: Sliding Window Data Management

### The Page Window Concept

```
Infinite Data Stream with 3-Page Window:
[...][Page N-2][Page N-1][Page N][Page N+1][Page N+2][...]
                   ↑
              Current Window

Forward Navigation:
[...][Page N-1][Page N][Page N+1] → [...][Page N][Page N+1][Page N+2]
      (Remove)                                              (Add)

Backward Navigation:
[...][Page N][Page N+1][Page N+2] → [...][Page N-1][Page N][Page N+1]
                        (Remove)    (Add)
```

The window slides through the data stream, maintaining constant memory usage.

### Memory Management Strategy

```
Traditional Infinite Query:
Time 0: [Page 1]
Time 1: [Page 1, Page 2]
Time 2: [Page 1, Page 2, Page 3]
Time 3: [Page 1, Page 2, Page 3, Page 4]  ← Memory grows indefinitely

Constrained Infinite Query (maxPages: 3):
Time 0: [Page 1]
Time 1: [Page 1, Page 2]
Time 2: [Page 1, Page 2, Page 3]
Time 3: [Page 2, Page 3, Page 4]  ← Memory stays constant
```

### Cache Behavior with Constraints

```
Query Cache Structure:
['projects'] → {
  pages: [
    { data: [...], nextId: 20, previousId: 10 },  // Page N
    { data: [...], nextId: 30, previousId: 20 },  // Page N+1  
    { data: [...], nextId: 40, previousId: 30 },  // Page N+2
  ],
  pageParams: [10, 20, 30]  // Current page parameters
}

When fetching Page N+3:
- Page N is automatically removed
- Page N+3 is added
- Window slides forward
```

### Why It's Designed This Way: Sustainable Infinite Scroll

Traditional infinite scroll problems:
```
Long session → Memory usage grows → Performance degrades → App becomes unusable
```

Constrained infinite scroll solution:
```
Long session → Memory usage constant → Performance maintained → App stays responsive
```

This enables infinite scroll for applications that users keep open for extended periods.

### Advanced Constraint Patterns

**Dynamic Page Limits**: Adjust constraints based on device capabilities:
```tsx
const useAdaptivePageLimit = () => {
  const [maxPages, setMaxPages] = useState(3)
  
  useEffect(() => {
    // Adjust based on available memory
    const memoryInfo = (navigator as any).memory
    if (memoryInfo) {
      const totalMemory = memoryInfo.totalJSHeapSize
      const pageLimit = totalMemory > 100 * 1024 * 1024 ? 5 : 3  // 100MB threshold
      setMaxPages(pageLimit)
    }
    
    // Adjust based on screen size
    const screenHeight = window.innerHeight
    const itemsPerPage = Math.floor(screenHeight / 100)  // Assuming 100px per item
    const optimalPages = Math.ceil(itemsPerPage * 2.5)  // Show 2.5 screens worth
    
    setMaxPages(Math.min(optimalPages, 10))  // Cap at 10 pages
  }, [])
  
  return maxPages
}
```

**Content-Aware Constraints**: Different limits for different data types:
```tsx
const useContentAwareInfiniteQuery = (contentType: 'text' | 'images' | 'videos') => {
  const maxPages = useMemo(() => {
    switch (contentType) {
      case 'text': return 10      // Text is lightweight
      case 'images': return 5     // Images need more memory  
      case 'videos': return 2     // Videos are memory-intensive
      default: return 3
    }
  }, [contentType])
  
  return useInfiniteQuery({
    queryKey: ['content', contentType],
    queryFn: ({ pageParam }) => fetchContent(contentType, pageParam),
    maxPages,
    // ... other options
  })
}
```

**Intelligent Page Prioritization**: Keep important pages longer:
```tsx
const useSmartInfiniteQuery = () => {
  const [importantPages, setImportantPages] = useState<Set<number>>(new Set())
  
  return useInfiniteQuery({
    queryKey: ['smart-content'],
    queryFn: ({ pageParam }) => fetchContent(pageParam),
    maxPages: 5,
    // Custom page removal strategy (if supported in future)
    shouldRemovePage: (page, index, pages) => {
      // Don't remove pages marked as important
      if (importantPages.has(page.id)) return false
      
      // Remove least recently accessed pages first
      return page.lastAccessed < Date.now() - 5 * 60 * 1000  // 5 minutes
    }
  })
}
```

**Progressive Quality Loading**: Lower quality for distant pages:
```tsx
const useProgressiveQualityInfinite = () => {
  return useInfiniteQuery({
    queryKey: ['progressive-content'],
    queryFn: ({ pageParam, meta }) => {
      // Adjust quality based on page position
      const quality = meta?.isCurrentPage ? 'high' : 'medium'
      return fetchContent(pageParam, { quality })
    },
    maxPages: 7,
    meta: {
      getCurrentPageIndex: (pages, currentViewport) => {
        // Determine which page is currently in viewport
        return pages.findIndex(page => 
          page.some(item => isInViewport(item, currentViewport))
        )
      }
    }
  })
}
```

### Performance Optimization Strategies

**Virtualization with Constraints**: Combine with virtual scrolling:
```tsx
const useVirtualizedConstrainedInfinite = () => {
  const query = useInfiniteQuery({
    queryKey: ['virtualized-content'],
    queryFn: ({ pageParam }) => fetchContent(pageParam),
    maxPages: 3,  // Only 3 pages in memory
  })
  
  // Virtualize rendering of the constrained pages
  const allItems = query.data?.pages.flatMap(page => page.data) ?? []
  
  return {
    ...query,
    virtualItems: allItems,
    totalEstimatedSize: allItems.length * 100,  // Estimated item height
  }
}
```

**Predictive Page Management**: Prefetch strategically within constraints:
```tsx
const usePredictiveInfinite = () => {
  const query = useInfiniteQuery({
    queryKey: ['predictive-content'],
    queryFn: ({ pageParam }) => fetchContent(pageParam),
    maxPages: 4,
  })
  
  // Prefetch next page when near the end of current window
  useEffect(() => {
    if (query.data && query.hasNextPage) {
      const currentPages = query.data.pages.length
      const maxPages = 4
      
      // If we have room for one more page, prefetch it
      if (currentPages < maxPages) {
        query.fetchNextPage()
      }
    }
  }, [query.data, query.hasNextPage, query.fetchNextPage])
  
  return query
}
```

**Memory Pressure Handling**: React to memory constraints:
```tsx
const useMemoryAwareInfinite = () => {
  const [memoryPressure, setMemoryPressure] = useState(false)
  
  useEffect(() => {
    const checkMemoryPressure = () => {
      const memoryInfo = (navigator as any).memory
      if (memoryInfo) {
        const usedRatio = memoryInfo.usedJSHeapSize / memoryInfo.totalJSHeapSize
        setMemoryPressure(usedRatio > 0.9)  // 90% memory usage
      }
    }
    
    const interval = setInterval(checkMemoryPressure, 5000)  // Check every 5 seconds
    return () => clearInterval(interval)
  }, [])
  
  return useInfiniteQuery({
    queryKey: ['memory-aware-content'],
    queryFn: ({ pageParam }) => fetchContent(pageParam),
    maxPages: memoryPressure ? 2 : 5,  // Reduce pages under memory pressure
    staleTime: memoryPressure ? 0 : 5 * 60 * 1000,  // More aggressive refetching under pressure
  })
}
```

### Further Exploration

Experiment with constraint strategies:

1. **Memory Monitoring**: Track memory usage with different page limits
2. **User Behavior**: Analyze how users interact with constrained infinite scroll
3. **Performance Testing**: Compare performance across different constraint configurations
4. **Content Adaptation**: Test constraints with different content types and sizes

**Advanced Challenges**:

1. **Smart Caching**: How would you implement intelligent page retention based on user behavior patterns?

2. **Cross-Session Persistence**: How would you persist parts of the infinite scroll state across browser sessions?

3. **Collaborative Constraints**: How would you handle infinite scroll constraints in real-time collaborative environments?

4. **Search Integration**: How would you implement constrained infinite scroll for search results with filtering?

**Real-World Applications**:
- **Social Media Feeds**: Prevent memory bloat during long browsing sessions
- **E-commerce Catalogs**: Efficient product browsing with thousands of items
- **Log Viewers**: System logs with memory-bounded infinite scroll
- **Chat Applications**: Message history with sliding window constraints
- **Content Platforms**: Article/video feeds with performance guarantees

Constrained infinite queries represent the evolution of infinite scroll from a novelty feature to a production-ready pattern. Understanding these constraints enables building applications that provide seamless infinite experiences while maintaining the performance and reliability users expect from professional software.