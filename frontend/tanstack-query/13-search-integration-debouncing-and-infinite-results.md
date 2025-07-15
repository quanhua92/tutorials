# Search Integration: Debouncing and Infinite Results

> **Based on**: [`examples/react/algolia`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/algolia)

## The Core Concept: Why This Example Exists

**The Problem:** Search functionality requires careful coordination between user input, network requests, and result display. Without proper management, every keystroke triggers a new API call, creating excessive network traffic, poor performance, and confusing user experiences. Users expect instant feedback while typing, smooth result loading, and the ability to load more results without losing context.

**The Solution:** TanStack Query combined with search services like Algolia creates **intelligent search experiences** that optimize network usage, provide instant visual feedback, and scale to handle large result sets. The `useInfiniteQuery` pattern enables **progressive result loading** while caching ensures that users can navigate search results without re-fetching data.

The key insight: **search is infinite query + conditional execution + smart caching**. By treating search as a stream of paginated results that only executes when needed, you create responsive, efficient search experiences that feel instant and handle large datasets gracefully.

## Practical Walkthrough: Code Breakdown

Let's examine the search integration patterns from `examples/react/algolia/`:

### 1. Custom Search Hook Architecture

```tsx
// useAlgolia.ts
export type UseAlgoliaOptions = {
  indexName: string
  query: string
  hitsPerPage?: number
  staleTime?: number
  gcTime?: number
}

export default function useAlgolia<TData>({
  indexName,
  query,
  hitsPerPage = 10,
  staleTime,
  gcTime,
}: UseAlgoliaOptions) {
  const queryInfo = useInfiniteQuery({
    queryKey: ['algolia', indexName, query, hitsPerPage],
    queryFn: query
      ? ({ pageParam }) => search<TData>({ indexName, query, pageParam, hitsPerPage })
      : skipToken,
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.nextPage,
    staleTime,
    gcTime,
  })

  const hits = queryInfo.data?.pages.map((page) => page.hits).flat()
  return { ...queryInfo, hits }
}
```

**What's happening:** A reusable hook that wraps `useInfiniteQuery` with search-specific logic. The `skipToken` prevents execution when query is empty, and the flattened `hits` array provides a simple interface for consuming components.

**Why this abstraction:** Encapsulates complex infinite query logic behind a simple interface. Components just provide a query string and get back flattened results with loading states.

### 2. Conditional Query Execution

```tsx
queryFn: query
  ? ({ pageParam }) => search<TData>({ indexName, query, pageParam, hitsPerPage })
  : skipToken,
```

**What's happening:** `skipToken` is TanStack Query's way of conditionally disabling queries. When `query` is empty, no network request is made.

**Why conditional execution:** Prevents unnecessary API calls when users haven't entered search terms yet. This is crucial for search UX - don't make requests until there's something to search for.

### 3. Search Function Implementation

```tsx
// algolia.ts
export async function search<TData>({
  indexName,
  query,
  pageParam,
  hitsPerPage = 10,
}: SearchOptions): Promise<{
  hits: Array<Hit<TData>>
  nextPage: number | undefined
}> {
  const client = searchClient(ALGOLIA_APP_ID, ALGOLIA_SEARCH_API_KEY)
  
  const { hits, page, nbPages } = await client.searchSingleIndex<TData>({
    indexName,
    searchParams: { query, page: pageParam, hitsPerPage },
  })

  const nextPage = page + 1 < nbPages ? page + 1 : undefined
  return { hits, nextPage }
}
```

**What's happening:** The search function handles Algolia API integration and transforms the response into the format expected by `useInfiniteQuery`. The `nextPage` calculation determines if more results are available.

**Why this transformation:** TanStack Query expects a consistent interface for pagination. By standardizing the response format, the infinite query logic works with any search provider.

### 4. Query Key Strategy for Search

```tsx
queryKey: ['algolia', indexName, query, hitsPerPage],
```

**What's happening:** The query key includes all parameters that affect results - index, query string, and page size. This ensures different searches get separate cache entries.

**Why include all parameters:** Each unique combination of search parameters should be cached separately. This allows users to switch between different searches and see instant results for previously searched terms.

### 5. Search Input Component

```tsx
// Search.tsx
export default function Search() {
  const [query, setQuery] = React.useState('')

  const handleOnChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    event.preventDefault()
    // It is recommended to debounce this event in prod
    setQuery(event.target.value)
  }

  return (
    <div>
      <input
        onChange={handleOnChange}
        value={query}
        placeholder="Search products"
      />
      <SearchResults query={query} />
    </div>
  )
}
```

**What's happening:** Simple controlled input that passes the current query to the results component. The comment hints at the need for debouncing in production.

**Why separation of concerns:** Keep input handling separate from result display. This makes both components more testable and reusable.

### 6. Results Display with Infinite Loading

```tsx
// SearchResults.tsx
export default function SearchResults({ query = '' }: SearchResultsProps) {
  const {
    hits,
    isLoading,
    isFetching,
    status,
    hasNextPage,
    isFetchingNextPage,
    fetchNextPage,
  } = useAlgolia<Product>({
    indexName: 'bestbuy',
    query,
    hitsPerPage: 5,
    staleTime: 1000 * 30, // 30s
    gcTime: 1000 * 60 * 15, // 15m
  })

  if (!query) return null
  if (isLoading) return <div className="loading">Loading...</div>

  return (
    <div>
      <div className="search-status">
        Status: {status} {isFetching && <span>fetching...</span>}
      </div>
      <div className="search-result">
        {hits && hits.length > 0 ? (
          hits.map((product) => (
            <li key={product.objectID} className="product">
              <span className="product-name">{product.name}</span>
              {product.shortDescription && (
                <>
                  <br />
                  <span className="product-description">
                    {product.shortDescription}
                  </span>
                </>
              )}
              <br />
              <span className="product-price">${product.salePrice}</span>
            </li>
          ))
        ) : (
          <h3>No products found!</h3>
        )}
      </div>
      {hasNextPage && (
        <div className="search-more" onClick={() => fetchNextPage()}>
          more
        </div>
      )}
      {isFetchingNextPage && (
        <div className="search-status">Fetching next page...</div>
      </div>
    </div>
  )
}
```

**What's happening:** The results component shows flattened hits with multiple loading states and a "load more" button for infinite scrolling. Different visual feedback for initial loading vs fetching more results.

**Why multiple loading states:** Users need different feedback for different operations - initial search, background refresh, and loading more results each require distinct UI treatment.

## Mental Model: Search as Reactive Infinite Streams

### The Search Query Lifecycle

```
User Input Flow:
1. User types → query state updates
2. Query key changes → triggers new infinite query
3. First page loads → shows initial results
4. User clicks "more" → loads next page
5. Results append → continuous result stream

Cache Behavior:
Each unique query gets its own cache entry:
['algolia', 'products', 'laptop', 10] → Cached laptop search
['algolia', 'products', 'phone', 10] → Cached phone search
```

### Conditional Execution Pattern

```
Query State:
'' (empty) → skipToken → No request
'a' → Execute search for 'a'
'ap' → Execute search for 'ap' (new cache entry)
'app' → Execute search for 'app' (new cache entry)
```

Each character change creates a new query, but TanStack Query's intelligent caching prevents redundant requests.

### Infinite Search Architecture

```
Search Results Structure:
{
  pages: [
    { hits: [item1, item2, item3], nextPage: 1 },
    { hits: [item4, item5, item6], nextPage: 2 },
    { hits: [item7, item8, item9], nextPage: undefined }
  ]
}

Flattened for UI:
hits = [item1, item2, item3, item4, item5, item6, item7, item8, item9]
```

### Why It's Designed This Way: Performance + UX

Traditional search implementation:
```
Every keystroke → New request → Show loading → Replace results
```

TanStack Query search:
```
Keystroke → Check cache → Instant results OR Fetch → Append to cache
```

This creates **instant-feeling search** for repeated queries while efficiently handling new searches.

### Advanced Search Patterns

**Debounced Search Hook**: Prevent excessive API calls:
```tsx
function useDebouncedSearch(query: string, delay: number = 300) {
  const [debouncedQuery, setDebouncedQuery] = useState(query)
  
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), delay)
    return () => clearTimeout(timer)
  }, [query, delay])
  
  return debouncedQuery
}

// Usage
function Search() {
  const [query, setQuery] = useState('')
  const debouncedQuery = useDebouncedSearch(query)
  
  return <SearchResults query={debouncedQuery} />
}
```

**Search with Filters**: Complex query keys for filtered search:
```tsx
const { hits } = useAlgolia({
  indexName: 'products',
  query: searchTerm,
  filters: {
    category: selectedCategory,
    priceRange: [minPrice, maxPrice],
    inStock: true
  }
})

// Query key includes all filter parameters
queryKey: ['algolia', indexName, query, filters, hitsPerPage]
```

**Prefetch Popular Searches**: Warm cache for common queries:
```tsx
useEffect(() => {
  // Prefetch popular searches
  const popularQueries = ['laptop', 'phone', 'tablet']
  popularQueries.forEach(popularQuery => {
    queryClient.prefetchInfiniteQuery({
      queryKey: ['algolia', 'products', popularQuery, 10],
      queryFn: ({ pageParam }) => search({ 
        indexName: 'products', 
        query: popularQuery, 
        pageParam, 
        hitsPerPage: 10 
      }),
      pages: 1 // Only prefetch first page
    })
  })
}, [])
```

**Search Analytics**: Track search behavior:
```tsx
const useAlgoliaWithAnalytics = (options) => {
  const result = useAlgolia(options)
  
  useEffect(() => {
    if (options.query && result.data) {
      analytics.track('search_performed', {
        query: options.query,
        resultsCount: result.hits?.length || 0,
        index: options.indexName
      })
    }
  }, [options.query, result.data])
  
  return result
}
```

**Optimistic Search Results**: Show immediate feedback:
```tsx
const useOptimisticSearch = (query) => {
  const [optimisticResults, setOptimisticResults] = useState([])
  const searchResults = useAlgolia({ query })
  
  // Show optimistic results immediately, replace with real results when available
  const displayResults = searchResults.data ? searchResults.hits : optimisticResults
  
  const performSearch = useCallback((newQuery) => {
    // Immediately show cached results if available
    const cachedResults = queryClient.getQueryData(['algolia', 'products', newQuery])
    if (cachedResults) {
      setOptimisticResults(cachedResults.pages.flatMap(p => p.hits))
    }
  }, [])
  
  return { ...searchResults, hits: displayResults, performSearch }
}
```

### Performance Optimizations

**Stale Time Configuration**: Balance freshness vs performance:
```tsx
staleTime: 1000 * 30, // 30 seconds - search results stay fresh
gcTime: 1000 * 60 * 15, // 15 minutes - keep in memory for back/forward navigation
```

**Result Virtualization**: Handle large result sets:
```tsx
import { FixedSizeList as List } from 'react-window'

function VirtualizedResults({ hits }) {
  const Row = ({ index, style }) => (
    <div style={style}>
      <ProductItem product={hits[index]} />
    </div>
  )
  
  return (
    <List height={600} itemCount={hits.length} itemSize={100}>
      {Row}
    </List>
  )
}
```

**Intelligent Prefetching**: Predict user behavior:
```tsx
// Prefetch next page when user scrolls near bottom
const { ref, inView } = useInView({ threshold: 0.1 })

useEffect(() => {
  if (inView && hasNextPage && !isFetchingNextPage) {
    fetchNextPage()
  }
}, [inView, hasNextPage, isFetchingNextPage])

// Place ref near bottom of results
<div ref={ref} style={{ height: 1 }} />
```

### Further Exploration

Experiment with search patterns:

1. **Debouncing**: Implement various debouncing strategies
2. **Search Suggestions**: Add autocomplete functionality
3. **Filter Integration**: Complex filtering with multiple parameters
4. **Search Analytics**: Track user search behavior

**Advanced Challenges**:

1. **Typo Tolerance**: How would you handle search suggestions for misspelled queries?

2. **Search Facets**: How would you implement category facets that update based on current search results?

3. **Multi-Index Search**: How would you search across multiple data sources simultaneously?

4. **Collaborative Filtering**: How would you implement "users who searched X also searched Y" functionality?

**Real-World Applications**:
- **E-commerce Sites**: Product search with filtering, sorting, and recommendations
- **Content Platforms**: Article, video, or document search with relevance ranking
- **Directory Applications**: User, company, or location search with faceted navigation
- **Knowledge Bases**: Documentation search with contextual suggestions
- **Social Platforms**: User-generated content search with real-time results

Search functionality is often the primary interface between users and your data. Understanding these patterns enables building search experiences that feel instant, handle large datasets efficiently, and provide the intelligent, responsive interactions users expect from modern applications.