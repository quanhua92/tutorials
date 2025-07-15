# React Router Navigation Patterns

> **Based on**: [`examples/react/react-router`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/react-router)

## The Core Concept: Why This Example Exists

**The Problem:** Modern single-page applications need seamless navigation between routes while maintaining efficient data fetching. Traditional approaches either fetch data after navigation (creating loading delays) or complex state management (creating tight coupling). Users expect instant navigation with immediate data availability, especially for predictable routes and search interactions.

**The Solution:** **Router-integrated data fetching** combines React Router's navigation system with TanStack Query's caching to create truly seamless navigation. By using loaders to prefetch data and Suspense to coordinate loading states, applications can achieve instant navigation while maintaining clean separation between routing and data concerns.

The key insight: **navigation and data fetching are complementary concerns** - when users navigate, they're expressing intent for specific data. Smart applications use navigation events as data prefetching opportunities.

## Practical Walkthrough: Code Breakdown

Let's examine the router integration patterns from `examples/react/react-router/src/routes/root.tsx`:

### 1. Query Options Factory Pattern

```tsx
const contactListQuery = (q?: string) =>
  queryOptions({
    queryKey: ['contacts', 'list', q ?? 'all'],
    queryFn: () => getContacts(q),
  })
```

**What's happening:** A factory function creates consistent query configurations that can be reused across loaders and components. The query key includes the search parameter for proper cache segregation.

**Why factory pattern:** Ensures query keys and functions remain consistent between route loaders and component queries. Prevents cache misses due to key mismatches.

### 2. Router Loader Integration

```tsx
export const loader =
  (queryClient: QueryClient) =>
  async ({ request }: LoaderFunctionArgs) => {
    const url = new URL(request.url)
    const q = url.searchParams.get('q') ?? ''
    await queryClient.ensureQueryData(contactListQuery(q))
    return { q }
  }
```

**What's happening:** The route loader extracts search parameters and ensures the corresponding data is available in the cache before navigation completes. It returns minimal data needed for the route.

**Why ensureQueryData:** Guarantees data is available when the component renders, eliminating loading states for navigation. Only fetches if data isn't already cached.

### 3. Suspense Query in Components

```tsx
const { q } = useLoaderData() as Awaited<ReturnType<ReturnType<typeof loader>>>
const { data: contacts } = useSuspenseQuery(contactListQuery(q))
```

**What's happening:** The component uses the same query configuration as the loader. Since the loader ensured data availability, `useSuspenseQuery` returns immediately without suspending.

**Why Suspense query:** Provides type-safe access to guaranteed data while maintaining React's concurrent rendering benefits. No loading states needed.

### 4. Loading State Coordination

```tsx
const searching = useIsFetching({ queryKey: ['contacts', 'list'] }) > 0
const navigation = useNavigation()

<input
  className={searching ? 'loading' : ''}
  onChange={(event) => {
    debouncedSubmit(event.currentTarget.form)
  }}
/>
```

**What's happening:** Combines TanStack Query's `useIsFetching` with React Router's `useNavigation` to provide comprehensive loading feedback for both searches and navigation.

**Why combined indicators:** Users need different feedback for "searching" vs "navigating." This pattern provides specific, contextual feedback.

### 5. Debounced Search with Automatic Navigation

```tsx
const debouncedSubmit = useDebounce(submit, 500)

onChange={(event) => {
  debouncedSubmit(event.currentTarget.form)
}}
```

**What's happening:** Search input is debounced and automatically submits the form, triggering navigation which in turn triggers data fetching through the loader.

**Why automatic submit:** Creates seamless search-as-you-type experience. Each search updates the URL, triggering appropriate data fetching and caching.

### 6. Navigation-Aware UI States

```tsx
<NavLink
  to={`contacts/${contact.id}`}
  className={({ isActive, isPending }) =>
    isActive ? 'active' : isPending ? 'pending' : ''
  }
>
```

**What's happening:** Links provide visual feedback for both current active state and pending navigation state, creating responsive UI during navigation.

**Why pending states:** Users get immediate feedback that their navigation action is being processed, even before the new route renders.

## Mental Model: Navigation as Data Intent

### The Router-Query Bridge

```
User Action → Router State → Data Intent → Cache State → UI Update

Navigation Event:
1. User clicks link/submits form
2. Router prepares navigation
3. Loader identifies data needs
4. Query ensures data availability
5. Navigation completes with instant data
```

Navigation becomes a declaration of data requirements rather than just route changes.

### Cache-Aware Navigation Strategy

```
Navigation Types by Cache State:

Cached Data Available:
User navigates → Instant display → Background update (if stale)

No Cached Data:
User navigates → Loader fetches → Navigation completes → Instant display

Search/Filter:
User types → Debounced submit → Loader ensures data → Results display
```

Different navigation scenarios require different cache strategies.

### URL as Single Source of Truth

```
URL State ↔ Query Keys ↔ Cache State

URL: /contacts?q=john
Query Key: ['contacts', 'list', 'john']
Cache: Contains filtered contacts

URL: /contacts/123
Query Key: ['contact', '123'] 
Cache: Contains specific contact
```

The URL and cache state stay synchronized through consistent query key strategies.

### Why It's Designed This Way: Predictable Performance

Traditional navigation problems:
```
Navigate → Loading Spinner → Data Fetch → Display
```

Router-integrated navigation solution:
```
Navigate → (Background Data Ensure) → Instant Display
```

This creates predictable, fast navigation regardless of cache state.

### Advanced Router Integration Patterns

**Route-Based Prefetching**: Load data for likely next routes:
```tsx
const useRoutePrefetching = () => {
  const location = useLocation()
  const queryClient = useQueryClient()
  
  useEffect(() => {
    // Prefetch data for common navigation paths
    const currentPath = location.pathname
    const likelyRoutes = getPredictedRoutes(currentPath)
    
    likelyRoutes.forEach(route => {
      // Prefetch route data
      queryClient.prefetchQuery(getRouteQuery(route))
    })
  }, [location.pathname, queryClient])
}
```

**Search State Persistence**: Maintain search across navigation:
```tsx
const useSearchPersistence = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  
  const updateSearch = useCallback((newSearch: string) => {
    // Update URL
    setSearchParams(prev => ({
      ...Object.fromEntries(prev),
      q: newSearch
    }))
    
    // Prefetch search results
    queryClient.prefetchQuery(contactListQuery(newSearch))
  }, [setSearchParams, queryClient])
  
  return { search: searchParams.get('q') ?? '', updateSearch }
}
```

**Nested Route Data Loading**: Coordinate parent-child data dependencies:
```tsx
// Parent route loader
export const parentLoader = (queryClient: QueryClient) => 
  async ({ params }: LoaderFunctionArgs) => {
    const { orgId } = params
    
    // Ensure organization data
    await queryClient.ensureQueryData(organizationQuery(orgId))
    
    // Prefetch common child data
    await Promise.all([
      queryClient.prefetchQuery(projectsQuery(orgId)),
      queryClient.prefetchQuery(membersQuery(orgId))
    ])
    
    return { orgId }
  }

// Child route can assume parent data exists
export const childLoader = (queryClient: QueryClient) =>
  async ({ params }: LoaderFunctionArgs) => {
    const { orgId, projectId } = params
    
    // Parent ensures org data, child ensures project data
    await queryClient.ensureQueryData(projectQuery(orgId, projectId))
    
    return { projectId }
  }
```

**Error Boundary Integration**: Handle route-level errors:
```tsx
const RouteErrorBoundary = () => {
  const error = useRouteError()
  const queryClient = useQueryClient()
  
  useEffect(() => {
    if (isRouteErrorResponse(error) && error.status === 404) {
      // Clear related cache entries for 404s
      queryClient.removeQueries({ 
        queryKey: ['resource', error.data?.resourceId],
        exact: false 
      })
    }
  }, [error, queryClient])
  
  return <div>Route Error: {error.statusText}</div>
}
```

**Optimistic Navigation**: Update UI before server confirmation:
```tsx
const useOptimisticNavigation = () => {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  
  const optimisticNavigate = useCallback(async (
    to: string, 
    optimisticData?: any
  ) => {
    if (optimisticData) {
      // Set optimistic data in cache
      const queryKey = getQueryKeyForRoute(to)
      queryClient.setQueryData(queryKey, optimisticData)
    }
    
    // Navigate immediately
    navigate(to)
    
    // Background validation
    try {
      await queryClient.refetchQueries({ queryKey: getQueryKeyForRoute(to) })
    } catch (error) {
      // Handle optimistic failure
      navigate(-1) // Go back
      throw error
    }
  }, [navigate, queryClient])
  
  return { optimisticNavigate }
}
```

**Dynamic Import with Data**: Code split routes with coordinated data loading:
```tsx
const useLazyRouteWithData = (routeId: string) => {
  const queryClient = useQueryClient()
  
  const loadRouteWithData = useCallback(async () => {
    // Load route code and data in parallel
    const [routeModule, routeData] = await Promise.all([
      import(`./routes/${routeId}`),
      queryClient.fetchQuery(getRouteQuery(routeId))
    ])
    
    return { component: routeModule.default, data: routeData }
  }, [routeId, queryClient])
  
  return { loadRouteWithData }
}
```

### Performance Optimization Strategies

**Smart Loader Strategies**: Optimize what loaders fetch:
```tsx
export const smartLoader = (queryClient: QueryClient) =>
  async ({ request, params }: LoaderFunctionArgs) => {
    const url = new URL(request.url)
    const fromClient = url.searchParams.get('client') === 'true'
    
    if (fromClient) {
      // Client-side navigation - data might be cached
      const cachedData = queryClient.getQueryData(routeQuery(params.id))
      if (cachedData && !isStale(cachedData)) {
        return { fromCache: true }
      }
    }
    
    // Server-side or stale data - ensure fresh data
    await queryClient.ensureQueryData(routeQuery(params.id))
    return { fromCache: false }
  }
```

**Background Route Updates**: Keep route data fresh:
```tsx
const useBackgroundRouteUpdates = () => {
  const location = useLocation()
  const queryClient = useQueryClient()
  
  useEffect(() => {
    const routeQueries = getQueriesForRoute(location.pathname)
    
    // Refresh route data in background
    routeQueries.forEach(query => {
      queryClient.refetchQueries({ 
        queryKey: query.queryKey,
        type: 'active' // Only refetch if components are using it
      })
    })
  }, [location.pathname, queryClient])
}
```

### Further Exploration

Experiment with router integration patterns:

1. **Navigation Analytics**: Track user flow patterns and optimize prefetching
2. **Route-Specific Cache Policies**: Different stale times for different route types
3. **Progressive Loading**: Load critical data first, defer secondary data
4. **Cross-Route State**: Share data between related routes efficiently

**Advanced Challenges**:

1. **Multi-Step Workflows**: How would you coordinate data loading across multi-step forms with navigation?

2. **Parallel Route Loading**: How would you handle routes that need multiple independent data sources?

3. **Route-Based Permissions**: How would you integrate authorization with data loading at the route level?

4. **Offline Navigation**: How would you handle navigation and data loading when offline?

**Real-World Applications**:
- **Admin Dashboards**: Complex navigation with immediate data availability
- **E-commerce Platforms**: Product browsing with instant category switches
- **Content Management**: Document navigation with seamless editing transitions
- **Social Applications**: Profile navigation with instant content loading
- **Business Applications**: Report navigation with immediate data visualization

Router integration with TanStack Query represents the evolution of single-page applications from route-centric to data-centric navigation. Understanding these patterns enables building applications that feel more like native applications - instant, responsive, and predictable.