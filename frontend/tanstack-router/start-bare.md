# TanStack Start Bare: Full-Stack React Made Simple

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/start-bare)**

## The Core Concept: Why This Example Exists

**The Problem:** Building modern full-stack React applications traditionally requires complex setups with separate frontend and backend configurations, build tools, SSR frameworks, and routing systems. Developers often spend more time configuring tools than building features, and the mental overhead of coordinating client and server code can be overwhelming.

**The TanStack Solution:** TanStack Start provides a unified full-stack React framework that handles SSR, routing, and bundling with minimal configuration. Think of it like Next.js, but built on the foundation of TanStack Router's powerful routing system. The "bare" example strips away all advanced features to show the essential difference between a client-side React app and a full-stack React application.

This example answers the fundamental question: "What's the minimal setup needed to get server-side rendering and full-stack capabilities with TanStack Start?"

---

## Practical Walkthrough: Code Breakdown

### The Full-Stack Foundation (`vite.config.ts:1-15`)

```tsx
import { tanstackStart } from '@tanstack/react-start/plugin/vite'
import { defineConfig } from 'vite'
import tsConfigPaths from 'vite-tsconfig-paths'

export default defineConfig({
  server: {
    port: 3000,
  },
  plugins: [
    tsConfigPaths({
      projects: ['./tsconfig.json'],
    }),
    tanstackStart(),
  ],
})
```

This configuration transforms a simple Vite setup into a full-stack framework:

- **tanstackStart()**: The plugin that enables SSR, file-based routing, and full-stack capabilities
- **tsConfigPaths**: Enables path aliases (like `~/components/Counter`)
- **Server configuration**: Runs on port 3000 with both development and production servers

### The HTML Document Route (`routes/__root.tsx:13-46`)

```tsx
export const Route = createRootRoute({
  head: () => ({
    links: [{ rel: 'stylesheet', href: appCss }],
  }),
  component: RootComponent,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html>
      <head>
        <HeadContent />
      </head>
      <body>
        <div className="p-2 flex gap-2 text-lg">
          <Link to="/">Index</Link>
          <Link to="/about">About</Link>
        </div>
        {children}
        <TanStackRouterDevtools position="bottom-right" />
        <Scripts />
      </body>
    </html>
  )
}
```

This is the key difference from client-side React - the root route renders the entire HTML document:

- **head() function**: Defines `<head>` content like stylesheets and meta tags
- **Full HTML structure**: TanStack Start renders complete HTML documents, not just React components
- **HeadContent component**: Injects head content into the document
- **Scripts component**: Includes necessary JavaScript for hydration

### File-Based Routes (`routes/index.tsx`, `routes/about.tsx`)

```tsx
// routes/index.tsx
export const Route = createFileRoute('/')({
  component: RouteComponent,
})

function RouteComponent() {
  return (
    <main>
      <h1 className="text-3xl text-blue-500 mb-5">Hello world!</h1>
    </main>
  )
}

// routes/about.tsx  
export const Route = createFileRoute('/about')({
  component: RouteComponent,
})

function RouteComponent() {
  return (
    <main>
      <h1>About</h1>
      <Counter />
    </main>
  )
}
```

File-based routing in TanStack Start works identically to TanStack Router, but with full-stack capabilities:

- **Server-side rendering**: These components render on the server first
- **Client hydration**: JavaScript makes them interactive after page load
- **Component imports**: `Counter` component works seamlessly across client and server

### The Router Factory Pattern (`router.tsx:4-14`)

```tsx
export function createRouter() {
  const router = createTanStackRouter({
    routeTree,
    defaultPreload: 'intent',
    defaultErrorComponent: (err) => <p>{err.error.stack}</p>,
    defaultNotFoundComponent: () => <p>not found</p>,
    scrollRestoration: true,
  })

  return router
}
```

TanStack Start uses a router factory instead of direct instantiation:

- **Server/client coordination**: The same router runs on server and client
- **Preloading**: Intent-based preloading works in SSR environments
- **Error handling**: Error boundaries work across server and client rendering

### Interactive Components (`components/Counter.tsx:4-15`)

```tsx
export default function Counter() {
  const [count, setCount] = useState(0)
  return (
    <button
      className="increment"
      onClick={() => setCount(count + 1)}
      type="button"
    >
      Clicks: {count}
    </button>
  )
}
```

Standard React components work without modification in TanStack Start:

- **Server rendering**: The button renders with initial state (count: 0)
- **Client hydration**: JavaScript attaches event handlers and state management
- **Seamless transition**: Users see content immediately, interactivity loads progressively

---

## Mental Model: Thinking in Full-Stack React

### Client-Side vs Full-Stack Architecture

**Traditional Client-Side React:**
```
1. Browser requests index.html
2. Browser downloads React bundle
3. React app starts, shows loading
4. Components mount and fetch data
5. UI updates with content
```

**TanStack Start Full-Stack:**
```
1. Browser requests any URL
2. Server renders React to HTML
3. Browser shows content immediately
4. JavaScript hydrates for interactivity
5. Routing and navigation work instantly
```

### The HTML Document Mental Model

In client-side React, you think in components:
```tsx
function App() {
  return <div>My App</div>
}
```

In TanStack Start, you think in complete documents:
```tsx
function RootDocument() {
  return (
    <html>
      <head>...</head>
      <body>
        <div>My App</div>
        <Scripts />
      </body>
    </html>
  )
}
```

This shift enables:
- **SEO optimization**: Search engines see complete HTML
- **Performance**: Users see content before JavaScript loads
- **Progressive enhancement**: Core functionality works without JavaScript

### The Routing Upgrade

File-based routing gains superpowers in TanStack Start:

```tsx
// Client-side: Routes are JavaScript bundles
routes/about.tsx → /about (after JS loads)

// Full-stack: Routes are server endpoints
routes/about.tsx → /about (immediate HTML response)
```

### The Component Continuity

The beautiful aspect of TanStack Start is component compatibility:

```tsx
// This component works identically in:
function Counter() {
  const [count, setCount] = useState(0)
  return <button onClick={() => setCount(count + 1)}>{count}</button>
}

// 1. Client-side React (useState works on client)
// 2. Server-side rendering (initial render on server)
// 3. Hydration (useState takes over on client)
```

### The Progressive Enhancement Philosophy

TanStack Start embraces progressive enhancement:

1. **Base experience**: HTML and CSS provide core functionality
2. **Enhanced experience**: JavaScript adds interactivity
3. **Optimized experience**: Preloading and caching improve performance

### Development vs Production Modes

The TanStack Start plugin handles both environments:

**Development:**
- Hot module replacement for instant updates
- Server-side rendering with fast refresh
- Development tools and debugging

**Production:**
- Optimized bundles and assets
- Server-side rendering for performance
- Automatic code splitting and preloading

### Further Exploration

Experiment with full-stack concepts:

1. **Add a new route**: Create `routes/contact.tsx` and see how it immediately becomes a server-rendered page.

2. **Explore view source**: Right-click and "View Page Source" to see the server-rendered HTML content.

3. **Test without JavaScript**: Disable JavaScript in your browser and see how much still works.

4. **Add head content**: Experiment with the `head()` function to add meta tags, titles, and links.

5. **Component hydration**: Add `console.log` statements to see when components run on server vs client.

6. **Build for production**: Run the build command and examine the generated files to understand the full-stack architecture.

The bare example demonstrates that TanStack Start maintains the familiar React development experience while adding powerful full-stack capabilities. You write React components the same way, but they automatically gain server-side rendering, improved performance, and better SEO - all with minimal configuration changes.