# Basic Programmatic Routing: Building Routes from Code

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/basic)**

## The Core Concept: Why This Example Exists

**The Problem:** React applications need a sophisticated routing system that can handle navigation, data loading, error boundaries, and nested layouts while maintaining type safety and developer experience. Traditional React routing solutions often require developers to choose between simplicity and power, forcing trade-offs that limit scalability.

**The TanStack Solution:** TanStack Router introduces "programmatic routing" - a pattern where you define routes as code objects rather than components. Think of it like building a blueprint before constructing a house. Instead of scattering route definitions throughout your component tree, you create a structured route tree that acts as the single source of truth for your application's navigation structure.

This example demonstrates the fundamental building blocks: route creation, nesting, data loading, error handling, and the powerful concept of "pathless layouts" - routes that provide structure without changing the URL.

---

## Practical Walkthrough: Code Breakdown

### The Foundation: Root Route (`main.tsx:16-26`)

```tsx
const rootRoute = createRootRoute({
  component: RootComponent,
  notFoundComponent: () => {
    return (
      <div>
        <p>This is the notFoundComponent configured on root route</p>
        <Link to="/">Start Over</Link>
      </div>
    )
  },
})
```

Every TanStack Router application starts with a root route. This isn't just the homepage - it's the foundational container that wraps your entire application. The root route defines two critical pieces:

- **component**: The layout that persists across all pages (navigation, footer, etc.)
- **notFoundComponent**: What users see when they navigate to a non-existent route

### The Navigation Shell (`main.tsx:28-71`)

```tsx
function RootComponent() {
  return (
    <>
      <div className="p-2 flex gap-2 text-lg border-b">
        <Link
          to="/"
          activeProps={{ className: 'font-bold' }}
          activeOptions={{ exact: true }}
        >
          Home
        </Link>
        {/* More navigation links */}
      </div>
      <Outlet />
      <TanStackRouterDevtools position="bottom-right" />
    </>
  )
}
```

The root component establishes the application shell. Notice two key elements:
- **`<Outlet />`**: This is where child routes render. Think of it as a placeholder that says "insert the current page here"
- **`activeProps`**: TanStack Router automatically applies these props when the link matches the current URL

### Simple Route Creation (`main.tsx:72-84`)

```tsx
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: IndexComponent,
})
```

This demonstrates the basic route creation pattern. Every route needs:
1. **getParentRoute**: Establishes the hierarchy (this route lives under rootRoute)
2. **path**: The URL pattern that activates this route
3. **component**: What renders when the route is active

### Data Loading Routes (`main.tsx:86-90`)

```tsx
export const postsLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'posts',
  loader: () => fetchPosts(),
}).lazy(() => import('./posts.lazy').then((d) => d.Route))
```

This introduces two powerful concepts:

**Loaders**: Functions that fetch data before the route renders. The data is available immediately when your component mounts - no loading states in your components!

**Lazy Loading**: The `.lazy()` method enables code splitting. The actual component definition lives in a separate file and only loads when needed.

### Dynamic Routes with Error Handling (`main.tsx:102-128`)

```tsx
const postRoute = createRoute({
  getParentRoute: () => postsLayoutRoute,
  path: '$postId',
  errorComponent: PostErrorComponent,
  loader: ({ params }) => fetchPost(params.postId),
  component: PostComponent,
})
```

Dynamic routes use the `$paramName` syntax. This route captures any value after `/posts/` as the `postId` parameter. Key features:

- **params**: Automatically parsed and passed to your loader
- **errorComponent**: Custom error handling for this specific route
- **useLoaderData**: Access the loaded data in your component

### Pathless Layouts: Structure Without URLs (`main.tsx:130-200`)

```tsx
const pathlessLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: '_pathlessLayout',  // Note: 'id' instead of 'path'
  component: PathlessLayoutComponent,
})
```

Pathless layouts are routes that provide component structure without affecting the URL. The `id` starting with `_` is a convention indicating this route doesn't create a URL segment. This enables complex nested layouts where `/route-a` and `/route-b` share the same layout components.

### Building the Route Tree (`main.tsx:202-211`)

```tsx
const routeTree = rootRoute.addChildren([
  postsLayoutRoute.addChildren([postRoute, postsIndexRoute]),
  pathlessLayoutRoute.addChildren([
    nestedPathlessLayout2Route.addChildren([
      pathlessLayoutARoute,
      pathlessLayoutBRoute,
    ]),
  ]),
  indexRoute,
])
```

The route tree is your application's navigation blueprint. This hierarchical structure determines:
- Which components render together
- How URLs are constructed
- Data loading sequences
- Error boundary propagation

### Router Configuration (`main.tsx:214-219`)

```tsx
const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultStaleTime: 5000,
  scrollRestoration: true,
})
```

Router configuration enables performance optimizations:
- **defaultPreload: 'intent'**: Preloads routes when users hover over links
- **defaultStaleTime**: How long data stays fresh before reloading
- **scrollRestoration**: Remembers scroll position during navigation

---

## Mental Model: Thinking in TanStack Router

### The Route Tree as Architecture

Think of TanStack Router like designing a building's architecture. Traditional routing is like deciding room layouts while construction is happening. TanStack Router requires you to create the blueprint first:

```
RootRoute (Foundation + Shell)
├── IndexRoute (Living Room)
├── PostsLayoutRoute (Kitchen)
│   ├── PostsIndexRoute (Kitchen Island)
│   └── PostRoute (Dining Nook)
└── PathlessLayout (Hallway System)
    └── Routes A & B (Connected Rooms)
```

Each route in this tree can have:
- **Structure** (component): What the "room" looks like
- **Data Requirements** (loader): What needs to be prepared before entering
- **Error Handling** (errorComponent): What happens if something goes wrong
- **Access Control** (beforeLoad): Who can enter this "room"

### Why Programmatic Over Component-Based?

Traditional routing embeds navigation logic within components:
```tsx
// Traditional approach - routing scattered in components
<Route path="/posts" component={Posts}>
  <Route path=":id" component={Post} />
</Route>
```

TanStack Router centralizes this logic:
```tsx
// TanStack approach - blueprint first, components second
const routeTree = postsRoute.addChildren([postRoute])
```

This separation provides:
1. **Type Safety**: TypeScript knows every possible route and parameter
2. **Centralized Configuration**: All routing logic in one place
3. **Optimizations**: Router can preload, cache, and optimize based on the complete tree
4. **Testing**: Routes can be tested independently of components

### The Data-First Philosophy

TanStack Router treats data loading as a first-class routing concern. Instead of loading data inside components (causing loading states), data is loaded by the route itself. This creates a "data-ready" component model:

```tsx
// Traditional: Component manages its own loading
function Post() {
  const [post, setPost] = useState(null)
  const [loading, setLoading] = useState(true)
  
  useEffect(() => {
    fetchPost(id).then(setPost).finally(() => setLoading(false))
  }, [id])
  
  if (loading) return <Spinner />
  return <div>{post.title}</div>
}

// TanStack: Route loads data, component receives it ready
const postRoute = createRoute({
  loader: ({ params }) => fetchPost(params.postId),
  component: PostComponent,
})

function PostComponent() {
  const post = postRoute.useLoaderData() // Always ready!
  return <div>{post.title}</div>
}
```

### Further Exploration

Try these experiments to deepen your understanding:

1. **Add a new route**: Create a route for `/about` that loads some data. Notice how you define it in the route tree and how the data flows.

2. **Experiment with pathless layouts**: Add another pathless layout route. See how you can create complex UI structures that don't map directly to URLs.

3. **Break something intentionally**: Remove the `errorComponent` from the `postRoute` and navigate to `/posts/invalid-id`. See how errors bubble up through the route tree.

4. **Explore preloading**: Add `console.log` statements in your loaders, then hover over links with developer tools open. Watch how TanStack Router preloads data before you even click.

The power of TanStack Router emerges from this architectural approach: define your application's structure first, then let the router handle the complex orchestration of data, errors, and navigation automatically.