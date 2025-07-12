# Kitchen Sink: Complete Router Feature Showcase

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/kitchen-sink)**

## The Core Concept: Why This Example Exists

**The Problem:** Learning a complex framework like TanStack Router can feel overwhelming when features are demonstrated in isolation. Real applications need authentication, nested layouts, search parameters, data mutations, error handling, optimistic updates, and performance optimizations - all working together harmoniously. Most examples show individual features, but don't demonstrate how they compose in a realistic application.

**The TanStack Solution:** The Kitchen Sink example is a **comprehensive demonstration** that showcases virtually every TanStack Router feature working together in a single, realistic application. Think of it as a reference implementation that shows not just what's possible, but how to architect a complete application using router-first patterns.

This example demonstrates authentication flows, complex nested routing, search parameter management, data mutations with optimistic updates, error boundaries, loading states, and performance optimizations - all integrated into a cohesive user experience.

---

## Practical Walkthrough: Code Breakdown

### Authentication Architecture (`main.tsx:637-661`)

```tsx
const authPathlessLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: 'auth',
  beforeLoad: ({ context, location }) => {
    if (context.auth.status === 'loggedOut') {
      throw redirect({
        to: loginRoute.to,
        search: {
          redirect: location.href,
        },
      })
    }
    return { username: auth.username }
  },
})
```

This demonstrates **route-level authentication**:

- **beforeLoad**: Runs before any child routes load
- **Automatic redirects**: Unauthenticated users are sent to login
- **Return destination**: Current URL is preserved for post-login redirect
- **Context injection**: Authenticated user data flows to child routes

The pathless layout pattern means `/profile` automatically gets authentication without changing the URL structure.

### Complex Nested Layouts (`main.tsx:144-180`)

```tsx
const dashboardLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'dashboard',
  component: DashboardLayoutComponent,
})

const invoicesLayoutRoute = createRoute({
  getParentRoute: () => dashboardLayoutRoute,
  path: 'invoices',
  loader: () => fetchInvoices(),
  component: InvoicesLayoutComponent,
})
```

This shows **hierarchical data loading** and **nested UI composition**:

- **Dashboard Layout**: Provides navigation and common UI for all dashboard pages
- **Invoices Layout**: Loads invoice list and provides master-detail interface
- **Data inheritance**: Child routes access parent route data
- **Progressive loading**: Each level loads its relevant data

The result is `/dashboard/invoices/123` which renders Root → Dashboard → Invoices → Invoice components in a nested structure.

### Advanced Search Parameter Management (`main.tsx:431-453`)

```tsx
const usersLayoutRoute = createRoute({
  getParentRoute: () => dashboardLayoutRoute,
  path: 'users',
  validateSearch: z.object({
    usersView: z.object({
      sortBy: z.enum(['name', 'id', 'email']).optional(),
      filterBy: z.string().optional(),
    }).optional(),
  }).parse,
  search: {
    middlewares: [retainSearchParams(['usersView'])],
  },
  loaderDeps: ({ search: { usersView } }) => ({
    filterBy: usersView?.filterBy,
    sortBy: usersView?.sortBy ?? 'name',
  }),
})
```

This demonstrates **sophisticated search parameter handling**:

- **Nested objects**: Complex search parameters with multiple properties
- **Search middlewares**: `retainSearchParams` preserves search state during navigation
- **Loader dependencies**: Search parameters trigger data reloading
- **Type safety**: Full TypeScript support for complex search structures

Users can sort and filter the list, navigate to individual users, and return to find their previous sorting/filtering preserved.

### Optimistic Updates with Mutations (`main.tsx:336-342`)

```tsx
const updateInvoiceMutation = useMutation({
  fn: patchInvoice,
  onSuccess: () => router.invalidate(),
})

// In the component
React.useEffect(() => {
  navigate({
    search: (old) => ({
      ...old,
      notes: notes ? notes : undefined,
    }),
    replace: true,
  })
}, [notes])
```

This shows **real-time UI updates**:

- **Immediate UI feedback**: Notes appear in URL as user types
- **Optimistic updates**: UI updates before server confirmation
- **Automatic invalidation**: Success triggers data refresh
- **URL as state**: Notes are stored in search parameters for shareability

### Dynamic Route Parameters with Validation (`main.tsx:314-333`)

```tsx
const invoiceRoute = createRoute({
  getParentRoute: () => invoicesLayoutRoute,
  path: '$invoiceId',
  params: {
    parse: (params) => ({
      invoiceId: z.number().int().parse(Number(params.invoiceId)),
    }),
    stringify: ({ invoiceId }) => ({ invoiceId: `${invoiceId}` }),
  },
  validateSearch: (search) =>
    z.object({
      showNotes: z.boolean().optional(),
      notes: z.string().optional(),
    }).parse(search),
})
```

Advanced parameter handling includes:

- **Type coercion**: URL string automatically converts to number
- **Validation**: Ensures invoiceId is a positive integer
- **Bidirectional conversion**: Handles both parsing from URL and stringifying for navigation
- **Search parameter validation**: Additional URL state is type-checked

### Error Boundaries and Loading States (`main.tsx:45-48`)

```tsx
function RouterSpinner() {
  const isLoading = useRouterState({ select: (s) => s.status === 'pending' })
  return <Spinner show={isLoading} />
}
```

The example demonstrates **comprehensive loading and error handling**:

- **Global loading indicator**: Shows during any route transition
- **Route-specific pending components**: Custom loading states per route
- **Error boundaries**: Different error UIs for different failure types
- **Graceful degradation**: Application remains functional when individual features fail

### Performance Optimizations (`main.tsx:813-825`)

```tsx
const router = createRouter({
  routeTree,
  defaultPendingComponent: () => <Spinner />,
  defaultErrorComponent: ({ error }) => <ErrorComponent error={error} />,
  context: { auth: undefined! },
  defaultPreload: 'intent',
  scrollRestoration: true,
})
```

Built-in performance features:

- **Intent-based preloading**: Data loads when users hover over links
- **Scroll restoration**: Maintains scroll position during navigation
- **Default components**: Consistent loading and error states
- **Context injection**: Shared services available throughout the app

### Real-time Development Features (`main.tsx:847-932`)

```tsx
function App() {
  const [loaderDelay, setLoaderDelay] = useSessionStorage('loaderDelay', 500)
  const [pendingMs, setPendingMs] = useSessionStorage('pendingMs', 1000)
  
  return (
    <>
      <div className="text-xs fixed w-52 shadow-md bottom-2 left-2">
        {/* Interactive controls for testing performance characteristics */}
      </div>
      <RouterProvider
        router={router}
        defaultPendingMs={pendingMs}
        context={{ auth }}
      />
    </>
  )
}
```

Development-time features:

- **Adjustable delays**: Test application behavior under different network conditions
- **Performance tuning**: Real-time adjustment of loading thresholds
- **Session persistence**: Settings survive page refreshes
- **Visual feedback**: Immediate understanding of performance characteristics

---

## Mental Model: Thinking in Complete Applications

### Architecture Layers

Think of the Kitchen Sink as a demonstration of **layered architecture** where each layer has specific responsibilities:

```
┌─ Authentication Layer ────────────────────┐
│  Handles login/logout, protects routes     │
│  ┌─ Layout Layer ─────────────────────┐   │
│  │  Provides navigation and UI chrome  │   │
│  │  ┌─ Data Layer ──────────────────┐ │   │
│  │  │  Loads and caches data       │ │   │
│  │  │  ┌─ Component Layer ───────┐ │ │   │
│  │  │  │  Renders UI and handles │ │ │   │
│  │  │  │  user interactions      │ │ │   │
│  │  │  └────────────────────────┘ │ │   │
│  │  └──────────────────────────────┘ │   │
│  └───────────────────────────────────┘   │
└──────────────────────────────────────────┘
```

### Feature Integration Patterns

**1. Authentication + Routing**
```tsx
// Authentication wraps protected features
const protectedRoutes = authLayoutRoute.addChildren([
  profileRoute,
  dashboardRoute.addChildren([...])
])

// Public routes remain accessible
const publicRoutes = [loginRoute, indexRoute, ...]
```

**2. Search Parameters + Data Loading**
```tsx
// Search parameters drive data requirements
validateSearch: searchSchema,
loaderDeps: ({ search }) => extractDependencies(search),
loader: ({ deps }) => fetchData(deps),

// Components receive filtered, sorted, paginated data
const data = Route.useLoaderData() // Already processed
```

**3. Optimistic Updates + Error Recovery**
```tsx
// Update UI immediately
const optimisticUpdate = (newData) => {
  setLocalState(newData)
  
  mutation.mutate(newData, {
    onSuccess: () => router.invalidate(),
    onError: () => {
      setLocalState(previousState) // Revert
      showErrorMessage()
    }
  })
}
```

### State Management Philosophy

The Kitchen Sink demonstrates **router-first state management**:

**URL as Single Source of Truth**
```tsx
// Instead of separate state management
const [sortBy, setSortBy] = useState('name')
const [filterBy, setFilterBy] = useState('')

// Use URL as state store
const { usersView } = Route.useSearch()
const navigate = useNavigate()

const updateSort = (sortBy) => 
  navigate({ search: { usersView: { ...usersView, sortBy } } })
```

Benefits:
- **Shareable state**: URLs can be bookmarked and shared
- **Browser integration**: Back/forward buttons work naturally
- **Persistence**: State survives page refreshes
- **Debugging**: Application state is visible in the URL

### Progressive Enhancement Patterns

**1. Start Simple, Add Complexity**
```tsx
// Begin with basic routing
const route = createRoute({
  path: '/users',
  component: UsersPage
})

// Add data loading
const route = createRoute({
  path: '/users',
  loader: () => fetchUsers(),
  component: UsersPage
})

// Add search parameters
const route = createRoute({
  path: '/users',
  validateSearch: searchSchema,
  loader: ({ search }) => fetchUsers(search),
  component: UsersPage
})

// Add authentication
const route = createRoute({
  getParentRoute: () => authLayout,
  path: '/users',
  validateSearch: searchSchema,
  loader: ({ search }) => fetchUsers(search),
  component: UsersPage
})
```

**2. Feature Composition**
```tsx
// Compose features through route hierarchy
const appRoutes = rootRoute.addChildren([
  // Public routes
  indexRoute,
  loginRoute,
  
  // Authenticated routes
  authLayout.addChildren([
    profileRoute,
    
    // Dashboard with nested features
    dashboardLayout.addChildren([
      dashboardIndex,
      
      // Data management
      invoicesLayout.addChildren([...]),
      usersLayout.addChildren([...]),
    ]),
  ]),
  
  // Pathless layouts for shared UI
  pathlessLayout.addChildren([...]),
])
```

### Real-World Application Patterns

**1. Data Consistency**
- Router invalidation ensures data freshness
- Optimistic updates provide immediate feedback
- Error boundaries handle failure gracefully
- Loading states maintain perceived performance

**2. User Experience**
- Intent-based preloading reduces waiting
- Scroll restoration maintains context
- Search parameter persistence preserves work
- Authentication flows are seamless

**3. Developer Experience**
- Type safety across the entire stack
- Centralized routing configuration
- Consistent error handling patterns
- Built-in performance monitoring

### Further Exploration

The Kitchen Sink serves as a **reference implementation** for building complete applications. Try these extensions:

1. **Add Real-time Features**: Integrate WebSocket updates that automatically refresh route data.

2. **Implement Offline Support**: Add service worker integration that caches route data and handles offline scenarios.

3. **Build Progressive Loading**: Implement skeleton screens and progressive data loading for better perceived performance.

4. **Create Feature Flags**: Add a feature flag system that conditionally shows routes and features.

5. **Add Analytics**: Integrate page view tracking and user behavior analytics that work with the router's navigation system.

6. **Implement A/B Testing**: Create a system for testing different route configurations and component variations.

The Kitchen Sink demonstrates that TanStack Router isn't just a routing library - it's a foundation for building complete, production-ready applications with sophisticated user experiences and robust developer tooling.