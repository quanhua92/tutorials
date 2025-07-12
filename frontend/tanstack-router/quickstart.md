# Quickstart: Your First TanStack Router Application

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/quickstart)**

## The Core Concept: Why This Example Exists

**The Problem:** Starting with a new routing library can feel overwhelming when you're presented with complex examples featuring authentication, data loading, and advanced patterns. Developers often need a minimal, crystal-clear starting point that demonstrates the absolute essentials without any distractions.

**The TanStack Solution:** The quickstart example strips TanStack Router down to its purest form: two pages, navigation between them, and nothing else. Think of it as learning to walk before running - this example teaches you the fundamental vocabulary and structure that every TanStack Router application shares, regardless of complexity.

This minimal example answers the core question: "What's the absolute minimum code needed to get TanStack Router working?"

---

## Practical Walkthrough: Code Breakdown

### The Complete Application (`main.tsx:1-75`)

The entire quickstart application fits in a single file, making it perfect for understanding the essential patterns:

### Foundation Imports (`main.tsx:1-12`)

```tsx
import React, { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { TanStackRouterDevtools } from '@tanstack/react-router-devtools'
```

This shows the minimal TanStack Router imports:
- **Core routing**: `createRootRoute`, `createRoute`, `createRouter`, `RouterProvider`
- **Navigation**: `Link` for routing-aware navigation
- **Layout**: `Outlet` for rendering child routes
- **Development**: `TanStackRouterDevtools` for debugging

### The Root Route Container (`main.tsx:14-30`)

```tsx
const rootRoute = createRootRoute({
  component: () => (
    <>
      <div className="p-2 flex gap-2">
        <Link to="/" className="[&.active]:font-bold">
          Home
        </Link>{' '}
        <Link to="/about" className="[&.active]:font-bold">
          About
        </Link>
      </div>
      <hr />
      <Outlet />
      <TanStackRouterDevtools />
    </>
  ),
})
```

The root route establishes your application shell:
- **Navigation bar**: Links to all main sections
- **Active state styling**: `[&.active]:font-bold` automatically styles the current page link
- **Content area**: `<Outlet />` renders the current route's component
- **Development tools**: Router devtools for debugging

### Simple Page Routes (`main.tsx:32-50`)

```tsx
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: function Index() {
    return (
      <div className="p-2">
        <h3>Welcome Home!</h3>
      </div>
    )
  },
})

const aboutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/about',
  component: function About() {
    return <div className="p-2">Hello from About!</div>
  },
})
```

Each page route follows the same pattern:
- **Parent relationship**: `getParentRoute: () => rootRoute` establishes hierarchy
- **URL path**: `path: '/'` or `path: '/about'` defines when this route matches
- **Component**: What renders when the route is active

### Route Tree Assembly (`main.tsx:52`)

```tsx
const routeTree = rootRoute.addChildren([indexRoute, aboutRoute])
```

This single line creates your application's routing structure. The `addChildren` method builds a tree where the root route contains the index and about routes as siblings.

### Router Configuration (`main.tsx:54-58`)

```tsx
const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  scrollRestoration: true,
})
```

Router configuration with essential optimizations:
- **Route tree**: The structure you just defined
- **Intent preloading**: Data loads when users hover over links
- **Scroll restoration**: Remembers scroll position during navigation

### Type Safety Setup (`main.tsx:60-64`)

```tsx
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
```

This TypeScript declaration provides complete type safety throughout your application. After this declaration, TypeScript knows about every route, parameter, and search param in your app.

### Application Bootstrap (`main.tsx:66-75`)

```tsx
const rootElement = document.getElementById('app')!
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement)
  root.render(
    <StrictMode>
      <RouterProvider router={router} />
    </StrictMode>,
  )
}
```

Standard React 18 application setup with the router provider at the top level.

---

## Mental Model: Thinking in TanStack Router Fundamentals

### The Essential Pattern

Every TanStack Router application follows this fundamental pattern:

```
1. Create routes (containers for your pages)
2. Assemble routes into a tree (your app's structure)
3. Create a router with that tree (the engine)
4. Provide the router to your React app (make it work)
```

This quickstart example demonstrates this pattern in its purest form without any distractions.

### Routes as Building Blocks

Think of routes like LEGO blocks:

```tsx
// Each route is a block with a specific purpose
const homeBlock = createRoute({ path: '/', component: Home })
const aboutBlock = createRoute({ path: '/about', component: About })

// The root block is the foundation
const foundation = createRootRoute({ component: AppShell })

// Assembly creates the structure
const structure = foundation.addChildren([homeBlock, aboutBlock])
```

### Navigation as Connections

The `Link` component creates connections between your route blocks:

```tsx
// These links create pathways between routes
<Link to="/">Go to home block</Link>
<Link to="/about">Go to about block</Link>
```

TanStack Router automatically handles:
- Active state detection (highlighting current page)
- Type checking (preventing links to non-existent routes)
- Preloading (loading next page before click)

### The Outlet as Portal

The `<Outlet />` component is like a portal that shows the current route's content:

```tsx
// In root route component:
<div>
  <nav>...</nav>
  <Outlet /> {/* Current page appears here */}
</div>
```

When you navigate:
- `/` → `<Outlet />` shows the Index component
- `/about` → `<Outlet />` shows the About component

### Type Safety as Safety Net

The type declaration creates a safety net for your entire application:

```tsx
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
```

After this declaration:
- TypeScript prevents typos in `Link` components
- Autocomplete works for route paths
- Parameters and search params are type-checked

### Further Exploration

Start experimenting with this foundation:

1. **Add a third route**: Create a `/contact` route and add it to the route tree. Notice how little code is needed.

2. **Add route parameters**: Change the about route to `/about/$name` and see how parameters work.

3. **Add search parameters**: Experiment with search params like `/about?tab=bio`.

4. **Break something intentionally**: Try linking to `/nonexistent` and see how TypeScript catches the error.

5. **Explore the devtools**: Open the TanStack Router devtools and navigate around. See how the route tree visualizes your application structure.

The quickstart example is your foundation. Every advanced TanStack Router feature builds on these same fundamental patterns: creating routes, assembling them into trees, and providing navigation between them. Master this simple structure, and you'll understand how the most complex TanStack Router applications work.