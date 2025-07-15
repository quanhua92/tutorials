# React Suspense: Concurrent UI Patterns

> **Based on**: [`examples/react/suspense`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/suspense)

## The Core Concept: Why This Example Exists

**The Problem:** Traditional data fetching creates imperative loading states scattered throughout components - `if (isPending) return <Loading />` appears everywhere, error handling becomes repetitive, and coordinating multiple loading states creates complex conditional rendering. This imperative approach makes it difficult to create consistent, smooth user experiences.

**The Solution:** **React Suspense** transforms data fetching into a **declarative pattern** where loading and error states are handled by boundary components, not individual data-consuming components. TanStack Query's `useSuspenseQuery` integrates seamlessly with React's concurrent features, enabling **fetch-as-you-render** patterns that optimize perceived performance.

The key insight: **Suspense treats async operations as render-blocking dependencies**, just like how components suspend for lazy-loaded code. This creates consistent, coordinated loading experiences across your entire application.

## Practical Walkthrough: Code Breakdown

Let's examine the Suspense integration patterns from `examples/react/suspense/`:

### 1. Suspense Query Setup

```tsx
import { useSuspenseQuery } from '@tanstack/react-query'

export default function Projects({ setActiveProject }) {
  const { data, isFetching } = useSuspenseQuery({
    queryKey: ['projects'],
    queryFn: fetchProjects,
  })

  return (
    <div>
      <h1>TanStack Repositories {isFetching ? <Spinner /> : null}</h1>
      {data.map((project) => (
        <p key={project.full_name}>{project.name}</p>
      ))}
    </div>
  )
}
```

**What's happening:** `useSuspenseQuery` never returns loading states - it suspends the component when data isn't available. The component always receives `data` as a guaranteed non-null value.

**Why this is powerful:** Components become simpler and more focused. No conditional rendering for loading states, no null checks for data - just render the actual content.

### 2. Suspense Boundary Declaration

```tsx
{showProjects ? (
  <React.Suspense fallback={<h1>Loading projects...</h1>}>
    {activeProject ? (
      <Project
        activeProject={activeProject}
        setActiveProject={setActiveProject}
      />
    ) : (
      <Projects setActiveProject={setActiveProject} />
    )}
  </React.Suspense>
) : null}
```

**What's happening:** The `Suspense` boundary catches suspension from any child component that uses `useSuspenseQuery`. The `fallback` is shown while any child is loading.

**Why boundaries work:** Suspense promotes **separation of concerns** - data-consuming components focus on rendering, boundary components handle loading states.

### 3. Error Boundary Integration

```tsx
<QueryErrorResetBoundary>
  {({ reset }) => (
    <ErrorBoundary
      fallbackRender={({ error, resetErrorBoundary }) => (
        <div>
          There was an error!{' '}
          <Button onClick={() => resetErrorBoundary()}>Try again</Button>
          <pre style={{ whiteSpace: 'normal' }}>{error.message}</pre>
        </div>
      )}
      onReset={reset}
    >
      <React.Suspense fallback={<h1>Loading projects...</h1>}>
        {/* Suspending components */}
      </React.Suspense>
    </ErrorBoundary>
  )}
</QueryErrorResetBoundary>
```

**What's happening:** `QueryErrorResetBoundary` coordinates with React's `ErrorBoundary` to handle both query errors and provide reset functionality. When users click "Try again," it resets both the error boundary and any failed queries.

**Why this coordination:** Error boundaries naturally complement Suspense - just as Suspense centralizes loading states, error boundaries centralize error states. The reset coordination ensures clean recovery.

### 4. Strategic Prefetching with Suspense

```tsx
<Button
  onClick={() => {
    // Prefetch the project query
    queryClient.prefetchQuery({
      queryKey: ['project', project.full_name],
      queryFn: () => fetchProject(project.full_name),
    })
    setActiveProject(project.full_name)
  }}
>
  Load
</Button>
```

**What's happening:** Before navigating to a detail view, prefetch the data so the `useSuspenseQuery` in the detail component can resolve immediately without suspending.

**Why prefetch with Suspense:** Suspense works best when data is already available. Strategic prefetching eliminates loading states entirely, creating instant navigation experiences.

### 5. Code Splitting Integration

```tsx
const Projects = lazy(() => import('./components/Projects'))
const Project = lazy(() => import('./components/Project'))

// Later in render:
<React.Suspense fallback={<h1>Loading projects...</h1>}>
  {activeProject ? (
    <Project /> // May suspend for code OR data
  ) : (
    <Projects /> // May suspend for code OR data
  )}
</React.Suspense>
```

**What's happening:** The same Suspense boundary handles both code splitting (lazy components) and data fetching (`useSuspenseQuery`). Users see one consistent loading state regardless of what's being loaded.

**Why this unification:** Suspense treats all async dependencies uniformly - whether it's JavaScript bundles or API data, the same declarative pattern applies.

### 6. Query Configuration for Suspense

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 0, // Disable retries for cleaner error boundaries
    },
  },
})
```

**What's happening:** Disabling automatic retries allows errors to surface quickly to error boundaries, creating more predictable Suspense behavior.

**Why this configuration:** Suspense + Error Boundaries work best with predictable error timing. Long retry cycles can create confusing UX where errors appear much later than expected.

## Mental Model: Declarative Async Dependencies

### Suspense as Async Coordination

Think of Suspense as React's built-in async coordinator:

```
Traditional Pattern:
Component → Check Loading → Render Loading OR Render Data

Suspense Pattern:  
Component → Assume Data Available → Render Data
Boundary → Handle Loading State
```

Components become **optimistic** - they assume their dependencies are ready and focus purely on rendering.

### The Suspension Flow

```
1. Component renders
2. useSuspenseQuery checks cache
3a. Cache hit → Return data, continue rendering
3b. Cache miss → Throw promise, suspend component
4. Suspense boundary catches suspension
5. Fallback UI renders
6. Promise resolves → Component re-renders with data
```

This flow is automatic and consistent across all Suspense-enabled components.

### Error Boundary Coordination

```
Error Boundary + Query Error Reset:
Error Occurs → Error Boundary Catches → Shows Error UI
User Clicks Retry → Reset Error Boundary + Reset Queries → Re-render
```

The coordination ensures both UI state and query state reset together, preventing inconsistent states.

### Why It's Designed This Way: Declarative UI Architecture

**Imperative Approach** (traditional):
```tsx
function MyComponent() {
  if (loading) return <Loading />
  if (error) return <Error error={error} />
  return <Content data={data} />
}
```

**Declarative Approach** (Suspense):
```tsx
// Boundary level
<ErrorBoundary fallback={<Error />}>
  <Suspense fallback={<Loading />}>
    <MyComponent />
  </Suspense>
</ErrorBoundary>

// Component level  
function MyComponent() {
  const { data } = useSuspenseQuery(...)
  return <Content data={data} />  // Always has data!
}
```

Suspense promotes **separation of concerns** and **component composability**.

### Advanced Suspense Patterns

**Nested Suspense Boundaries**: Fine-grained loading control:
```tsx
<Suspense fallback={<AppShell />}>
  <Header />
  <Suspense fallback={<ContentSkeleton />}>
    <MainContent />
    <Suspense fallback={<SidebarSkeleton />}>
      <Sidebar />
    </Suspense>
  </Suspense>
</Suspense>
```

**Suspense with Transitions**: Smooth loading states:
```tsx
const [isPending, startTransition] = useTransition()

const navigate = (page) => {
  startTransition(() => {
    setCurrentPage(page) // May trigger Suspense
  })
}

return (
  <div>
    {isPending && <ProgressBar />}
    <Suspense fallback={<PageSkeleton />}>
      <CurrentPage />
    </Suspense>
  </div>
)
```

**Suspense Query Options**: Optimize for Suspense:
```tsx
const { data } = useSuspenseQuery({
  queryKey: ['data'],
  queryFn: fetchData,
  staleTime: 5 * 60 * 1000, // 5 minutes - avoid suspending for stale data
})
```

**Parallel Data Loading**: Multiple suspense queries:
```tsx
function Dashboard() {
  // These all load in parallel and all must resolve before component renders
  const { data: user } = useSuspenseQuery({ queryKey: ['user'], queryFn: fetchUser })
  const { data: posts } = useSuspenseQuery({ queryKey: ['posts'], queryFn: fetchPosts })  
  const { data: stats } = useSuspenseQuery({ queryKey: ['stats'], queryFn: fetchStats })
  
  return <DashboardContent user={user} posts={posts} stats={stats} />
}
```

### Performance Considerations

**Waterfall Prevention**: Use prefetching to avoid sequential loading:
```tsx
// ❌ Creates waterfall
function App() {
  return (
    <Suspense fallback={<Loading />}>
      <UserProfile /> {/* Suspends, loads user */}
      <UserPosts />   {/* Then suspends, loads posts */}
    </Suspense>
  )
}

// ✅ Parallel loading
function App() {
  // Prefetch both queries
  useEffect(() => {
    queryClient.prefetchQuery(['user'])
    queryClient.prefetchQuery(['posts'])
  }, [])
  
  return (
    <Suspense fallback={<Loading />}>
      <UserProfile />
      <UserPosts />
    </Suspense>
  )
}
```

**Suspense Granularity**: Balance loading coordination vs. progressive disclosure:
- **Coarse boundaries**: Fewer loading states, longer wait times
- **Fine boundaries**: More loading states, incremental rendering

### Further Exploration

Experiment with Suspense patterns:

1. **Boundary Placement**: Try different Suspense boundary granularities
2. **Error Recovery**: Test error boundary reset functionality
3. **Prefetching Strategies**: Implement strategic prefetching for smooth navigation
4. **Code + Data**: Combine lazy loading with data fetching

**Advanced Challenges**:

1. **Stream Rendering**: How would you implement streaming server-side rendering with Suspense?

2. **Progressive Enhancement**: How would you gracefully degrade Suspense on older browsers?

3. **Complex Dependencies**: How would you handle components that depend on multiple async resources?

4. **Performance Optimization**: How would you implement intelligent prefetching based on user behavior?

**Real-World Applications**:
- **Modern SPAs**: Clean, declarative loading states throughout the application
- **Dashboard Applications**: Coordinated loading of multiple data sources  
- **E-commerce Sites**: Smooth product browsing with instant navigation
- **Content Platforms**: Progressive loading of articles, media, and user data
- **Admin Interfaces**: Complex forms with dependent data loading

React Suspense + TanStack Query creates a powerful foundation for building modern, responsive applications that feel native and smooth. The declarative approach eliminates much of the complexity traditionally associated with async state management while enabling sophisticated loading and error handling patterns.