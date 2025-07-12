# Basic Devtools Panel: Deep Debugging for Router Applications

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/basic-devtools-panel)**

## The Core Concept: Why This Example Exists

**The Problem:** Complex routing applications can be difficult to debug. When navigation behaves unexpectedly, data doesn't load as expected, or routes don't match properly, developers need visibility into the router's internal state. Traditional browser devtools don't understand router-specific concepts like route trees, loader states, or navigation history.

**The TanStack Solution:** TanStack Router provides specialized devtools that give you X-ray vision into your router's operation. Unlike the floating devtools overlay that sits on top of your app, the `TanStackRouterDevtoolsPanel` can be embedded directly into your application or integrated with browser extension panels.

This example demonstrates how to set up embedded router devtools that work within Shadow DOM environments - perfect for micro-frontends, browser extensions, or applications that need isolated styling. You'll learn to configure the devtools panel to debug route matching, inspect loader data, and monitor navigation performance.

---

## Practical Walkthrough: Code Breakdown

### The Shadow DOM Setup (`main.tsx:59-63`)

```tsx
const element = document.getElementById('app')!
const shadowContainer = element.attachShadow({ mode: 'open' })
const shadowRootElement = document.createElement('div')
shadowContainer.appendChild(shadowRootElement)
```

This example uses Shadow DOM to create an isolated rendering environment. Shadow DOM is crucial for:
- **Style Isolation**: Prevents CSS conflicts between your app and devtools
- **Micro-frontend Architecture**: Each part of your app has its own DOM tree
- **Browser Extension Development**: Extensions often require isolated rendering contexts

### Basic Router Structure (`main.tsx:16-49`)

```tsx
const rootRoute = createRootRoute({
  component: () => (
    <>
      <div className="p-2 flex gap-2">
        <Link to="/">Home</Link> <Link to="/about">About</Link>
      </div>
      <hr />
      <Outlet />
    </>
  ),
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: function Index() {
    return (
      <div className="p-2">
        <h3>Welcome Home!</h3>
        <App />
      </div>
    )
  },
})
```

The example uses a minimal router setup to focus on devtools integration. Notice:
- **Simple Navigation**: Two routes (home and about) to demonstrate route switching
- **Named Components**: Functions have explicit names for better devtools display
- **Embedded Component**: The `App` component is nested within the route structure

### Devtools Panel Integration (`main.tsx:68-71`)

```tsx
<TanStackRouterDevtoolsPanel
  shadowDOMTarget={shadowContainer}
  router={router}
/>
```

The key difference from the floating devtools:

**`TanStackRouterDevtoolsPanel` vs `TanStackRouterDevtools`**:
- **Panel**: Embedded in your application, takes up actual space
- **Floating**: Overlay that appears on top of your app
- **Shadow DOM Support**: Panel version can target specific DOM containers

### Shadow DOM Targeting (`main.tsx:69`)

```tsx
shadowDOMTarget={shadowContainer}
```

This prop tells the devtools panel where to attach its DOM nodes. Without this:
- Devtools would render in the main document
- CSS styles might conflict
- Event handling could break in isolated environments

### Router Registration (`main.tsx:53-57`)

```tsx
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
```

TypeScript module augmentation that:
- Enables type-safe router access throughout your app
- Allows devtools to understand your specific router configuration
- Provides autocomplete for route paths and parameters

---

## Mental Model: Debugging Router Applications

### The Router as a State Machine

Think of TanStack Router as a complex state machine where:

```
Current State = {
  location: "/posts/123",
  matchedRoutes: [rootRoute, postsRoute, postRoute],
  loaderData: { post: {...}, user: {...} },
  pendingNavigations: [],
  searchParams: { filter: "recent" }
}
```

The devtools panel gives you real-time visibility into this state machine, showing you:

1. **Route Tree**: Your application's navigation blueprint
2. **Current Matches**: Which routes are active right now
3. **Loader States**: Data loading progress and results
4. **Navigation History**: Where you've been and pending transitions
5. **Search Params**: URL query parameters and their values

### Debugging Workflow with Devtools

**Route Matching Issues:**
```tsx
// Problem: Link doesn't navigate as expected
<Link to="/posts/123">View Post</Link>

// Debugging with devtools:
// 1. Check "Route Tree" tab - is the route defined?
// 2. Look at "Matched Routes" - which routes are active?
// 3. Inspect "Location" - what's the current URL state?
```

**Data Loading Problems:**
```tsx
// Problem: Component renders before data loads
const postRoute = createRoute({
  loader: ({ params }) => fetchPost(params.postId),
  component: PostComponent,
})

// Debugging with devtools:
// 1. "Loaders" tab shows loading states
// 2. "Data" tab displays loaded values
// 3. "Timeline" shows loading sequence
```

**Performance Issues:**
```tsx
// Problem: Navigation feels slow
const router = createRouter({
  defaultPreload: 'intent',
  defaultStaleTime: 5000,
})

// Debugging with devtools:
// 1. "Timeline" shows preloading activity
// 2. "Cache" tab displays data freshness
// 3. "Performance" metrics highlight bottlenecks
```

### Shadow DOM Integration Patterns

The Shadow DOM setup in this example enables several advanced patterns:

**Micro-frontend Integration:**
```tsx
// Each micro-frontend has its own router + devtools
const createMicrofrontend = (containerId: string) => {
  const container = document.getElementById(containerId)!
  const shadow = container.attachShadow({ mode: 'open' })
  
  return {
    router: createRouter({ routeTree }),
    devtools: <TanStackRouterDevtoolsPanel shadowDOMTarget={shadow} />
  }
}
```

**Browser Extension Development:**
```tsx
// Extension popup with isolated router debugging
const extensionContainer = chrome.extension.getViews()[0].document
const shadowRoot = extensionContainer.createElement('div').attachShadow({ mode: 'open' })

ReactDOM.render(
  <RouterProvider router={router} />,
  <TanStackRouterDevtoolsPanel shadowDOMTarget={shadowRoot} />,
  shadowRoot
)
```

**Component Library Testing:**
```tsx
// Isolated testing environment for router components
const createTestEnvironment = () => {
  const testContainer = document.createElement('div')
  const shadow = testContainer.attachShadow({ mode: 'open' })
  
  return {
    container: testContainer,
    renderWithRouter: (component) => (
      <RouterProvider router={testRouter}>
        {component}
        <TanStackRouterDevtoolsPanel shadowDOMTarget={shadow} />
      </RouterProvider>
    )
  }
}
```

### Advanced Devtools Features

**Real-time Route Inspection:**
- See route parameters change as you navigate
- Monitor search param updates
- Watch loader data refresh cycles

**Performance Profiling:**
- Track navigation timing
- Identify slow loaders
- Monitor preloading effectiveness

**State Debugging:**
- Inspect route context values
- Debug custom route options
- Monitor error boundary states

### Further Exploration

Try these experiments to master router debugging:

1. **Add Complex Data Loading**: Create routes with multiple loaders and watch how the devtools shows their loading sequence.

2. **Experiment with Preloading**: Add hover links and observe how the devtools tracks preloading activity.

3. **Create Error Scenarios**: Add routes that fail loading and see how errors appear in the devtools.

4. **Test Shadow DOM Isolation**: Compare how the devtools behaves with and without Shadow DOM targeting.

The devtools panel transforms router debugging from guesswork into precise inspection. Whether you're building micro-frontends, browser extensions, or complex SPAs, embedded devtools give you the visibility needed to build reliable routing systems.