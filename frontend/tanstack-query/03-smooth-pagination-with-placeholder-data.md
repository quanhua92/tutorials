# Smooth Pagination with Placeholder Data

> **Based on**: [`examples/react/pagination`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/pagination)

## The Core Concept: Why This Example Exists

**The Problem:** Traditional pagination creates jarring user experiences - clicking "Next Page" shows a loading spinner, the previous page's content disappears, and users lose context while waiting for new data. This creates an unnatural, stop-start navigation flow that feels broken compared to modern app experiences.

**The Solution:** TanStack Query's `placeholderData` feature enables **seamless pagination** by keeping the previous page visible while the next page loads in the background. Combined with strategic prefetching, this creates a fluid browsing experience where users never see loading spinners for pagination.

The key insight is treating pagination not as separate requests, but as **progressive disclosure** of a continuous data stream. Each page is cached independently, enabling instant backwards navigation and intelligent prefetching for forwards navigation.

## Practical Walkthrough: Code Breakdown

Let's examine the pagination mechanics from `examples/react/pagination/src/pages/index.tsx`:

### 1. Stateful Pagination Query

```tsx
function Example() {
  const [page, setPage] = React.useState(0)

  const { status, data, error, isFetching, isPlaceholderData } = useQuery({
    queryKey: ['projects', page],
    queryFn: () => fetchProjects(page),
    placeholderData: keepPreviousData,
    staleTime: 5000,
  })
}
```

**What's happening:** The query key includes the current page (`['projects', page]`), making each page a separate cache entry. When `page` changes, Query treats this as a new request.

**The magic of `keepPreviousData`:** Instead of showing a loading state, Query returns the previous page's data as a placeholder while fetching the new page. The `isPlaceholderData` flag indicates when you're seeing stale data.

**Why `staleTime: 5000`:** Pages remain fresh for 5 seconds, preventing unnecessary refetches when users quickly navigate back and forth.

### 2. The Fetch Function Pattern

```tsx
const fetchProjects = async (
  page = 0,
): Promise<{
  projects: Array<{ name: string; id: number }>
  hasMore: boolean
}> => {
  const response = await fetch(`/api/projects?page=${page}`)
  return await response.json()
}
```

**What's happening:** The server returns both the page data AND metadata about whether more pages exist.

**Why include `hasMore`:** This enables smart UI state management - you can disable the "Next Page" button when you've reached the end, preventing unnecessary requests and improving UX.

### 3. Intelligent Prefetching

```tsx
React.useEffect(() => {
  if (!isPlaceholderData && data?.hasMore) {
    queryClient.prefetchQuery({
      queryKey: ['projects', page + 1],
      queryFn: () => fetchProjects(page + 1),
    })
  }
}, [data, isPlaceholderData, page, queryClient])
```

**What's happening:** When a new page loads successfully (not placeholder data) and more pages exist, automatically prefetch the next page.

**Why this timing:** Prefetching only after real data arrives prevents cascade loading and ensures you're prefetching based on current, not stale, pagination state.

**The prefetch advantage:** When users click "Next Page," the data is likely already cached, creating instant page transitions.

### 4. Smart UI State Management

```tsx
<button
  onClick={() => {
    setPage((old) => (data?.hasMore ? old + 1 : old))
  }}
  disabled={isPlaceholderData || !data?.hasMore}
>
  Next Page
</button>
```

**What's happening:** The Next Page button is disabled when:
- Currently showing placeholder data (preventing rapid clicks during loading)
- No more pages exist (based on server metadata)

**Why prevent clicks during placeholder state:** Rapid pagination can create confusing states where multiple requests are in-flight and placeholder data becomes unreliable.

### 5. Dual Loading Indicators

```tsx
{status === 'pending' ? (
  <div>Loading...</div>
) : (
  <div>
    {data.projects.map((project) => (
      <p key={project.id}>{project.name}</p>
    ))}
  </div>
)}

{isFetching ? <span> Loading...</span> : null}
```

**What's happening:** Two distinct loading states:
- `status === 'pending'`: Initial load (no cached data exists)
- `isFetching`: Background loading while showing placeholder data

**Why this separation:** Users need different feedback for "waiting for content" vs. "content is updating." The first blocks interaction, the second is informational.

## Mental Model: Pagination as a Window

### The Sliding Window Concept

Think of pagination not as discrete pages, but as a **sliding window** over a continuous data stream:

```
Data Stream: [A][B][C][D][E][F][G][H][I][J]...

Window Position:
Page 0: [A][B][C]
Page 1:    [B][C][D] (B,C stay visible during transition)
Page 2:       [C][D][E] (C,D stay visible during transition)
```

Each page transition slides the window, but `keepPreviousData` ensures content remains visible during the slide.

### Cache Structure for Pagination

```
Query Cache:
├── ['projects', 0] → {projects: [...], hasMore: true}
├── ['projects', 1] → {projects: [...], hasMore: true}  
├── ['projects', 2] → {projects: [...], hasMore: false}
└── ...
```

Each page is independently cached, enabling:
- **Instant backwards navigation** (cache hits)
- **Smart prefetching** (next page prediction)
- **Memory efficiency** (old pages can be garbage collected)

### The Prefetch Strategy

Query's prefetching creates a **read-ahead buffer**:

```
User is viewing Page 1:
├── Page 0: Cached ✓
├── Page 1: Active ✓
├── Page 2: Prefetched ✓ (ready for instant access)
└── Page 3: Not loaded (will prefetch when user reaches page 2)
```

This creates the illusion of infinite, instant scrolling within a paginated structure.

### Why It's Designed This Way: Cognitive Load Reduction

Traditional pagination breaks user flow:
```
Content → Loading → Different Content (context lost)
```

Query's placeholder approach maintains context:
```
Content → Same Content + Background Loading → Smooth Transition
```

Users maintain their mental model of the data while new information loads progressively.

### Handling Edge Cases

**Rapid Navigation:** `isPlaceholderData` prevents double-clicks from causing state confusion
**Network Failures:** Previous data remains visible, with clear error indication
**End of Data:** `hasMore` prevents infinite loading attempts
**Memory Management:** Old pages naturally expire from cache based on `gcTime`

### Further Exploration

Try these experiments to understand pagination behavior:

1. **Rapid Clicking**: Try clicking Next/Previous rapidly - notice how the UI stays responsive
2. **Network Throttling**: Set slow 3G and observe how content stays visible during transitions
3. **Cache Inspection**: Use DevTools to see how each page creates a separate cache entry
4. **Prefetch Timing**: Watch the Network tab to see when prefetching occurs

**Advanced Challenge**: How would you implement **infinite scroll** using these same pagination primitives? Think about how `useInfiniteQuery` might build on these concepts.

The pagination pattern you've learned here is foundational for many advanced data loading patterns - understanding the interplay between cache keys, placeholder data, and prefetching will serve you well in building responsive, user-friendly interfaces.