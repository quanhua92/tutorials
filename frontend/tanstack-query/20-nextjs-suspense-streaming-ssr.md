# Next.js Suspense Streaming SSR

> **Based on**: [`examples/react/nextjs-suspense-streaming`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/nextjs-suspense-streaming)

## The Core Concept: Why This Example Exists

**The Problem:** Traditional server-side rendering forces pages to wait for the slowest data source before sending any content to the browser. Users see blank screens while all server requests complete, even when some content could be displayed immediately. Modern applications need **progressive content delivery** where fast content appears instantly while slower content streams in.

**The Solution:** **Suspense streaming with TanStack Query** enables progressive server-side rendering where different parts of the page can be rendered and streamed independently. Fast queries render immediately while slower queries stream in as they complete, creating perceived instant page loads with graceful loading states for slower content.

The key insight: **not all content is equally important or equally fast** - critical above-the-fold content should render immediately while secondary content can stream in progressively without blocking the initial page load.

## Practical Walkthrough: Code Breakdown

Let's examine the streaming patterns from `examples/react/nextjs-suspense-streaming/src/app/page.tsx`:

### 1. Suspense Query with Edge Runtime

```tsx
export const runtime = 'edge' // 'nodejs' (default) | 'edge'

function useWaitQuery(props: { wait: number }) {
  const query = useSuspenseQuery({
    queryKey: ['wait', props.wait],
    queryFn: async () => {
      const path = `/api/wait?wait=${props.wait}`
      const url = baseUrl + path
      
      const res: string = await (
        await fetch(url, {
          cache: 'no-store',
        })
      ).json()
      return res
    },
  })

  return [query.data as string, query] as const
}
```

**What's happening:** `useSuspenseQuery` with Edge Runtime enables fast cold starts and streaming responses. The `cache: 'no-store'` ensures fresh data for each request while maintaining streaming capabilities.

**Why Edge Runtime:** Provides faster cold starts and better streaming support compared to Node.js runtime. Critical for responsive SSR with multiple independent data sources.

### 2. Independent Suspense Boundaries

```tsx
<Suspense fallback={<div>waiting 100....</div>}>
  <MyComponent wait={100} />
</Suspense>
<Suspense fallback={<div>waiting 200....</div>}>
  <MyComponent wait={200} />
</Suspense>
<Suspense fallback={<div>waiting 300....</div>}>
  <MyComponent wait={300} />
</Suspense>
```

**What's happening:** Each component has its own Suspense boundary, allowing them to render independently. Fast components (wait={100}) appear immediately while slower ones (wait={300}) continue loading.

**Why independent boundaries:** Prevents slow content from blocking fast content. Each section of the page can stream at its own pace, creating progressive loading experiences.

### 3. Combined Suspense Coordination

```tsx
<Suspense
  fallback={
    <>
      <div>waiting 800....</div>
      <div>waiting 900....</div>
      <div>waiting 1000....</div>
    </>
  }
>
  <MyComponent wait={800} />
  <MyComponent wait={900} />
  <MyComponent wait={1000} />
</Suspense>
```

**What's happening:** Multiple components share a single Suspense boundary, waiting for all to complete before rendering. The fallback shows placeholders for all pending components.

**Why combined boundaries:** When components are logically related and should appear together, shared boundaries prevent jarring sequential appearances.

### 4. Server Environment Detection

```tsx
function getBaseURL() {
  if (!isServer) {
    return ''
  }
  if (process.env.VERCEL_URL) {
    return `https://${process.env.VERCEL_URL}`
  }
  return 'http://localhost:3000'
}
```

**What's happening:** Detects server vs client environment and constructs appropriate base URLs for API calls. Critical for SSR where relative URLs don't work.

**Why environment detection:** Ensures API calls work correctly in development, production, and deployment environments during both SSR and client-side hydration.

### 5. Streaming-Optimized Component Pattern

```tsx
function MyComponent(props: { wait: number }) {
  const [data] = useWaitQuery(props)
  
  return <div>result: {data}</div>
}
```

**What's happening:** Components are minimal and focused, containing only the logic needed for their specific data requirements. No complex state management or side effects.

**Why minimal components:** Streaming works best with simple, focused components that have clear data dependencies and minimal rendering complexity.

## Mental Model: Progressive Content Delivery

### The Streaming Timeline

```
Traditional SSR:
Server: Wait for ALL data → Render complete page → Send to browser
Browser: Receive complete page → Hydrate → Interactive

Streaming SSR:
Server: Render fast parts → Stream → Render slow parts → Stream
Browser: Receive fast parts → Display → Receive slow parts → Update
```

Content appears progressively rather than all-at-once.

### Suspense Boundary Strategy

```
Page Structure with Streaming:

┌─────────────────────────────────┐
│ Header (instant)                │
├─────────────────────────────────┤
│ ┌─────────┐ ┌─────────┐        │
│ │Fast Data│ │Med Data │        │ ← Independent boundaries
│ │(100ms)  │ │(200ms)  │        │
│ └─────────┘ └─────────┘        │
├─────────────────────────────────┤
│ ┌─────────────────────────────┐ │
│ │     Combined Boundary       │ │ ← Wait for all
│ │ ┌─────┐ ┌─────┐ ┌─────┐   │ │
│ │ │Slow │ │Slow │ │Slow │   │ │
│ │ │800ms│ │900ms│ │1000 │   │ │
│ │ └─────┘ └─────┘ └─────┘   │ │
│ └─────────────────────────────┘ │
└─────────────────────────────────┘
```

### Cache Behavior with Streaming

```
SSR Cache States:
1. Server renders with fresh data
2. Client hydrates with same data (cache populated)
3. Subsequent navigation uses cached data
4. Background refetch updates cache

Streaming Flow:
Server Query → SSR Render → Stream to Client → Hydrate → Cache
```

### Why It's Designed This Way: Perceived Performance

Traditional loading experience:
```
Page Load: Blank → ... → Complete Page (3 seconds)
User Experience: Waiting → Sudden Appearance
```

Streaming loading experience:
```
Page Load: Header → Fast Content → Medium Content → Slow Content
User Experience: Immediate Engagement → Progressive Enhancement
```

Users can start interacting with content immediately.

### Advanced Streaming Patterns

**Priority-Based Streaming**: Critical content first:
```tsx
const useStreamingPriority = (priority: 'high' | 'medium' | 'low') => {
  const query = useSuspenseQuery({
    queryKey: ['priority-data', priority],
    queryFn: async () => {
      // High priority gets faster endpoints/cache
      const endpoint = priority === 'high' 
        ? '/api/fast-data' 
        : '/api/regular-data'
      
      const response = await fetch(endpoint)
      return response.json()
    },
    // High priority gets longer cache time
    staleTime: priority === 'high' ? 10 * 60 * 1000 : 5 * 60 * 1000,
  })
  
  return query.data
}

// Usage with priority-based Suspense
<Suspense fallback={<CriticalSkeleton />}>
  <CriticalSection priority="high" />
</Suspense>
<Suspense fallback={<SecondarySkeleton />}>
  <SecondarySection priority="medium" />
</Suspense>
```

**Conditional Streaming**: Stream based on data importance:
```tsx
const useConditionalStreaming = (dataId: string, isAboveFold: boolean) => {
  if (isAboveFold) {
    // Above-fold content uses suspense (blocking)
    return useSuspenseQuery({
      queryKey: ['critical', dataId],
      queryFn: () => fetchCriticalData(dataId),
    })
  } else {
    // Below-fold content loads in background (non-blocking)
    return useQuery({
      queryKey: ['secondary', dataId],
      queryFn: () => fetchSecondaryData(dataId),
      // Longer stale time for secondary content
      staleTime: 15 * 60 * 1000,
    })
  }
}

// Above-fold: suspends during SSR
<Suspense fallback={<HeroSkeleton />}>
  <HeroSection />
</Suspense>

// Below-fold: loads after hydration
<SecondaryContent /> {/* Uses regular useQuery */}
```

**Nested Streaming**: Hierarchical data dependencies:
```tsx
const useNestedStreaming = (parentId: string, includeChildren: boolean) => {
  // Parent data loads first
  const parentQuery = useSuspenseQuery({
    queryKey: ['parent', parentId],
    queryFn: () => fetchParent(parentId),
  })
  
  // Child data loads conditionally after parent
  const childQuery = useQuery({
    queryKey: ['children', parentId],
    queryFn: () => fetchChildren(parentId),
    enabled: includeChildren && !!parentQuery.data,
  })
  
  return { parent: parentQuery.data, children: childQuery.data }
}

// Nested Suspense boundaries
<Suspense fallback={<ParentSkeleton />}>
  <ParentComponent>
    <Suspense fallback={<ChildrenSkeleton />}>
      <ChildrenComponent />
    </Suspense>
  </ParentComponent>
</Suspense>
```

**Adaptive Streaming**: Adjust based on connection:
```tsx
const useAdaptiveStreaming = (dataSize: 'small' | 'large') => {
  const [connectionType, setConnectionType] = useState<string>()
  
  useEffect(() => {
    if (typeof navigator !== 'undefined' && 'connection' in navigator) {
      const conn = (navigator as any).connection
      setConnectionType(conn.effectiveType)
    }
  }, [])
  
  const shouldDefer = connectionType === '2g' && dataSize === 'large'
  
  if (shouldDefer) {
    // Defer large content on slow connections
    return useQuery({
      queryKey: ['deferred', dataSize],
      queryFn: () => fetchData(dataSize),
      enabled: false, // Load on user interaction
    })
  }
  
  return useSuspenseQuery({
    queryKey: ['immediate', dataSize],
    queryFn: () => fetchData(dataSize),
  })
}
```

**Error Boundary Streaming**: Handle failures gracefully:
```tsx
const StreamingErrorBoundary = ({ children, fallback }: {
  children: React.ReactNode
  fallback: React.ComponentType<{ error: Error }>
}) => {
  return (
    <ErrorBoundary
      fallback={({ error, resetErrorBoundary }) => (
        <div>
          <fallback error={error} />
          <button onClick={resetErrorBoundary}>
            Retry Section
          </button>
        </div>
      )}
    >
      {children}
    </ErrorBoundary>
  )
}

// Usage
<StreamingErrorBoundary fallback={SectionErrorFallback}>
  <Suspense fallback={<SectionSkeleton />}>
    <DataSection />
  </Suspense>
</StreamingErrorBoundary>
```

### Performance Optimization Strategies

**Smart Skeleton Design**: Match content structure:
```tsx
const SmartSkeleton = ({ type }: { type: 'list' | 'card' | 'text' }) => {
  const skeletonConfig = {
    list: { rows: 5, height: '60px' },
    card: { rows: 1, height: '200px' },
    text: { rows: 3, height: '20px' },
  }
  
  const config = skeletonConfig[type]
  
  return (
    <div className="animate-pulse">
      {Array.from({ length: config.rows }).map((_, i) => (
        <div 
          key={i}
          className="bg-gray-300 rounded mb-2"
          style={{ height: config.height }}
        />
      ))}
    </div>
  )
}
```

**Streaming Analytics**: Monitor performance:
```tsx
const useStreamingAnalytics = () => {
  const startTimes = useRef<Record<string, number>>({})
  
  const trackStreamStart = useCallback((sectionId: string) => {
    startTimes.current[sectionId] = Date.now()
  }, [])
  
  const trackStreamComplete = useCallback((sectionId: string) => {
    const startTime = startTimes.current[sectionId]
    if (startTime) {
      const duration = Date.now() - startTime
      console.log(`Section ${sectionId} streamed in ${duration}ms`)
      
      // Send to analytics
      analytics.track('section_stream_complete', {
        sectionId,
        duration,
        timestamp: Date.now(),
      })
    }
  }, [])
  
  return { trackStreamStart, trackStreamComplete }
}
```

### Further Exploration

Experiment with streaming patterns:

1. **Stream Ordering**: Test different content loading orders for optimal UX
2. **Skeleton Accuracy**: Measure how closely skeletons match final content
3. **Performance Metrics**: Track First Contentful Paint, Largest Contentful Paint
4. **User Behavior**: Analyze how users interact with progressively loading content

**Advanced Challenges**:

1. **Multi-Device Streaming**: How would you optimize streaming for different device capabilities?

2. **Personalized Streaming**: How would you stream different content based on user preferences?

3. **Real-Time Streaming**: How would you combine static streaming with real-time updates?

4. **Offline Streaming**: How would you handle streaming when network connectivity is poor?

**Real-World Applications**:
- **News Websites**: Headlines load instantly, detailed content streams in
- **E-commerce**: Product listings appear fast, detailed info loads progressively  
- **Dashboards**: Critical metrics show immediately, detailed charts load later
- **Social Media**: Timeline structure appears fast, content fills in progressively
- **Documentation**: Navigation and headers instant, content sections stream

Suspense streaming with TanStack Query represents the future of server-side rendering - where applications can deliver immediate value while enhancing the experience progressively. Understanding these patterns enables building applications that feel instant while handling complex data requirements gracefully.