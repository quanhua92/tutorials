# Strategic Prefetching: Performance Optimization

> **Based on**: [`examples/react/prefetching`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/prefetching)

## The Core Concept: Why This Example Exists

**The Problem:** Users often experience loading delays when navigating through applications - clicking on list items shows spinners, hovering over navigation shows delays, and predictable user flows feel sluggish. Traditional reactive data fetching waits for user actions before starting requests, creating unnecessary perceived latency.

**The Solution:** **Strategic prefetching** anticipates user behavior and loads data before it's actually needed. TanStack Query's `prefetchQuery` API enables intelligent data preloading based on user interactions, navigation patterns, and predictable workflows, creating near-instant user experiences.

The key insight: **user interactions often follow predictable patterns** - hovering suggests interest, certain navigation flows are common, and some data is likely to be needed soon. By prefetching strategically, you can eliminate loading states for anticipated user actions.

## Practical Walkthrough: Code Breakdown

Let's examine the strategic prefetching patterns from `examples/react/prefetching/src/pages/index.tsx`:

### 1. Hover-Based Prefetching

```tsx
<li
  key={char.id}
  onClick={() => {
    setSelectedChar(char.id)
  }}
  onMouseEnter={async () => {
    await queryClient.prefetchQuery({
      queryKey: ['character', char.id],
      queryFn: () => getCharacter(char.id),
      staleTime: 10 * 1000, // only prefetch if older than 10 seconds
    })

    setTimeout(() => {
      rerender({})
    }, 1)
  }}
>
```

**What's happening:** Mouse hover triggers prefetching of character details. The `staleTime` prevents redundant prefetching of recently fetched data. A forced re-render updates the visual indicator.

**Why hover-based:** Hovering is a strong signal of user intent that doesn't commit to navigation. This creates a window of time to prefetch data before the user clicks.

### 2. Smart Stale Time Configuration

```tsx
staleTime: 10 * 1000, // only prefetch if older than 10 seconds
```

**What's happening:** Prefetching only occurs if the data is older than 10 seconds, preventing unnecessary network requests for recently cached data.

**Why conditional prefetching:** Respects cache efficiency while ensuring timely prefetching. Fresh data doesn't need prefetching, while stale data benefits from background updates.

### 3. Cache-Aware Visual Indicators

```tsx
<div
  style={
    queryClient.getQueryData(['character', char.id])
      ? { fontWeight: 'bold' }
      : {}
  }
>
  {char.id} - {char.name}
</div>
```

**What's happening:** Items that have been prefetched (exist in cache) are visually distinguished with bold text.

**Why visual feedback:** Users benefit from understanding which actions will be instant vs require loading. This builds confidence and improves perceived performance.

### 4. Instant Navigation for Prefetched Data

```tsx
const characterQuery = useQuery({
  queryKey: ['character', selectedChar],
  queryFn: () => getCharacter(selectedChar),
})

// When selectedChar changes:
// - If data was prefetched → instant display (no loading state)
// - If data wasn't prefetched → loading state appears
```

**What's happening:** The same query that handles prefetching also handles actual data display. If data exists in cache (from prefetching), it displays instantly.

**Why reuse queries:** Prefetching and actual queries use identical query keys and functions, ensuring cache hits work seamlessly.

### 5. Forced Re-render for UI Updates

```tsx
const rerender = React.useState(0)[1]

setTimeout(() => {
  rerender({})
}, 1)
```

**What's happening:** A forced re-render after prefetching ensures visual indicators update immediately to show prefetched state.

**Why force re-render:** Prefetching doesn't automatically trigger component re-renders since the component isn't subscribed to the prefetched query. Manual re-render updates visual indicators.

## Mental Model: Predictive Data Loading

### The Prefetching Opportunity Window

```
User Behavior Timeline:
Hover → [Prefetch Window] → Click → Instant Display

Traditional:
Hover → (no action) → Click → Loading → Display

Optimized:
Hover → Prefetch → Click → Instant Display
```

The time between hover and click becomes valuable loading time rather than dead time.

### Cache Warming Strategy

```
Cache States:
Empty → Prefetched → Used
  ↓        ↓        ↓
No Data   Ready    Instant

Prefetching fills the cache proactively:
- Hover events → Warm cache
- Route preloading → Warm cache  
- Predictive patterns → Warm cache
```

### Performance vs Resource Balance

```
Prefetching Decision Matrix:
High Probability + Low Cost = Always Prefetch
High Probability + High Cost = Conditional Prefetch
Low Probability + Low Cost = Maybe Prefetch
Low Probability + High Cost = Don't Prefetch
```

Smart prefetching balances user experience gains against resource consumption.

### Why It's Designed This Way: Perceived Performance

Raw performance vs perceived performance:
```
Raw: Network latency remains the same
Perceived: Users experience instant interactions for predicted actions
```

Prefetching optimizes for **perceived performance** - how fast the app feels to users rather than actual network speeds.

### Advanced Prefetching Patterns

**Route-Based Prefetching**: Load data for likely navigation targets:
```tsx
const useRoutePrefetching = () => {
  const router = useRouter()
  const queryClient = useQueryClient()
  
  useEffect(() => {
    // Prefetch data for common next routes
    const currentRoute = router.pathname
    const nextRoutes = getCommonNextRoutes(currentRoute)
    
    nextRoutes.forEach(route => {
      queryClient.prefetchQuery({
        queryKey: ['route-data', route],
        queryFn: () => fetchRouteData(route),
        staleTime: 5 * 60 * 1000, // 5 minutes
      })
    })
  }, [router.pathname, queryClient])
}
```

**Intersection Observer Prefetching**: Load data as items come into view:
```tsx
const usePrefetchOnView = (items: Item[]) => {
  const queryClient = useQueryClient()
  
  const { ref, inView } = useInView({
    threshold: 0.1,
    triggerOnce: true,
  })
  
  useEffect(() => {
    if (inView) {
      items.forEach(item => {
        queryClient.prefetchQuery({
          queryKey: ['item', item.id],
          queryFn: () => fetchItem(item.id),
        })
      })
    }
  }, [inView, items, queryClient])
  
  return ref
}
```

**Time-Based Prefetching**: Predictive loading based on patterns:
```tsx
const useTimeBasedPrefetching = () => {
  const queryClient = useQueryClient()
  
  useEffect(() => {
    // Prefetch commonly accessed data at specific times
    const now = new Date()
    
    if (now.getHours() === 9) {
      // Morning: prefetch dashboard data
      queryClient.prefetchQuery({
        queryKey: ['dashboard'],
        queryFn: fetchDashboard,
      })
    }
    
    if (now.getDay() === 1) {
      // Monday: prefetch weekly reports
      queryClient.prefetchQuery({
        queryKey: ['weekly-report'],
        queryFn: fetchWeeklyReport,
      })
    }
  }, [queryClient])
}
```

**Adaptive Prefetching**: Learn from user behavior:
```tsx
const useAdaptivePrefetching = () => {
  const [userPatterns, setUserPatterns] = useLocalStorage('user-patterns', {})
  const queryClient = useQueryClient()
  
  const trackUserAction = useCallback((action: string, target: string) => {
    setUserPatterns(prev => ({
      ...prev,
      [action]: [...(prev[action] || []), target].slice(-10) // Keep last 10
    }))
  }, [setUserPatterns])
  
  const prefetchBasedOnPatterns = useCallback((currentContext: string) => {
    const patterns = userPatterns[currentContext] || []
    const commonTargets = getMostCommon(patterns)
    
    commonTargets.forEach(target => {
      queryClient.prefetchQuery({
        queryKey: ['adaptive', target],
        queryFn: () => fetchData(target),
        staleTime: 2 * 60 * 1000, // 2 minutes
      })
    })
  }, [userPatterns, queryClient])
  
  return { trackUserAction, prefetchBasedOnPatterns }
}
```

**Bandwidth-Aware Prefetching**: Respect user's connection:
```tsx
const useBandwidthAwarePrefetching = () => {
  const [connectionType, setConnectionType] = useState<string>()
  
  useEffect(() => {
    if ('connection' in navigator) {
      const conn = (navigator as any).connection
      setConnectionType(conn.effectiveType)
      
      const handleChange = () => setConnectionType(conn.effectiveType)
      conn.addEventListener('change', handleChange)
      return () => conn.removeEventListener('change', handleChange)
    }
  }, [])
  
  const shouldPrefetch = useCallback((dataSize: 'small' | 'medium' | 'large') => {
    if (connectionType === '4g') return true
    if (connectionType === '3g' && dataSize !== 'large') return true
    if (connectionType === '2g' && dataSize === 'small') return true
    return false
  }, [connectionType])
  
  return { shouldPrefetch, connectionType }
}
```

### Prefetching Best Practices

**Resource Management**: Prevent excessive prefetching:
```tsx
const useManagedPrefetching = () => {
  const queryClient = useQueryClient()
  const prefetchQueue = useRef<Set<string>>(new Set())
  const [concurrentPrefetches, setConcurrentPrefetches] = useState(0)
  
  const prefetchWithLimit = useCallback(async (queryKey: QueryKey, queryFn: QueryFunction) => {
    const key = JSON.stringify(queryKey)
    
    // Skip if already prefetching or recently prefetched
    if (prefetchQueue.current.has(key) || concurrentPrefetches >= 3) {
      return
    }
    
    prefetchQueue.current.add(key)
    setConcurrentPrefetches(prev => prev + 1)
    
    try {
      await queryClient.prefetchQuery({ queryKey, queryFn })
    } finally {
      prefetchQueue.current.delete(key)
      setConcurrentPrefetches(prev => prev - 1)
    }
  }, [queryClient, concurrentPrefetches])
  
  return { prefetchWithLimit }
}
```

**Cache Size Management**: Prevent memory bloat:
```tsx
const useCacheSizeLimit = () => {
  const queryClient = useQueryClient()
  
  useEffect(() => {
    const interval = setInterval(() => {
      const cache = queryClient.getQueryCache()
      const queries = cache.getAll()
      
      // If cache is too large, remove least recently used items
      if (queries.length > 100) {
        const lruQueries = queries
          .sort((a, b) => (a.state.dataUpdatedAt || 0) - (b.state.dataUpdatedAt || 0))
          .slice(0, queries.length - 100)
        
        lruQueries.forEach(query => {
          cache.remove(query)
        })
      }
    }, 60 * 1000) // Check every minute
    
    return () => clearInterval(interval)
  }, [queryClient])
}
```

### Performance Monitoring

**Prefetch Success Tracking**: Measure prefetch effectiveness:
```tsx
const usePrefetchAnalytics = () => {
  const analytics = useRef({
    prefetched: 0,
    cacheHits: 0,
    cacheMisses: 0,
  })
  
  const trackPrefetch = useCallback((queryKey: QueryKey) => {
    analytics.current.prefetched++
    console.log('Prefetched:', queryKey)
  }, [])
  
  const trackCacheHit = useCallback((queryKey: QueryKey) => {
    analytics.current.cacheHits++
    console.log('Cache hit:', queryKey, 'Hit rate:', 
      analytics.current.cacheHits / (analytics.current.cacheHits + analytics.current.cacheMisses))
  }, [])
  
  const trackCacheMiss = useCallback((queryKey: QueryKey) => {
    analytics.current.cacheMisses++
    console.log('Cache miss:', queryKey)
  }, [])
  
  return { trackPrefetch, trackCacheHit, trackCacheMiss, analytics: analytics.current }
}
```

### Further Exploration

Experiment with prefetching strategies:

1. **User Behavior Analysis**: Track and analyze common user flows
2. **Performance Metrics**: Measure time-to-interactive for prefetched vs non-prefetched routes
3. **Resource Impact**: Monitor network usage and memory consumption
4. **A/B Testing**: Compare user satisfaction with and without prefetching

**Advanced Challenges**:

1. **Predictive Models**: How would you build ML models to predict user actions for prefetching?

2. **Multi-Step Workflows**: How would you prefetch data for complex, multi-step user journeys?

3. **Collaborative Prefetching**: How would you share prefetch insights across users with similar behavior patterns?

4. **Real-Time Adaptation**: How would you adjust prefetching strategies based on real-time performance metrics?

**Real-World Applications**:
- **E-commerce**: Product detail prefetching based on browsing patterns
- **Content Platforms**: Article/video prefetching for likely next reads
- **Social Media**: Profile and content prefetching for feed interactions
- **Dashboard Applications**: Report and chart prefetching for common workflows
- **Navigation Apps**: Route data prefetching for likely destinations

Strategic prefetching transforms good applications into exceptional ones by eliminating perceived latency for common user actions. Understanding these patterns enables building applications that feel magically responsive, anticipating user needs and delivering instant interactions where users expect them most.