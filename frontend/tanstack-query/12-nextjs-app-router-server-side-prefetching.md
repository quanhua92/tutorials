# Next.js App Router: Server-Side Prefetching

> **Based on**: [`examples/react/nextjs-app-prefetching`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/nextjs-app-prefetching)

## The Core Concept: Why This Example Exists

**The Problem:** Next.js App Router introduces React Server Components, changing how we think about data fetching and hydration. Traditional SSR patterns don't work with the new server/client component boundary, and developers struggle with properly hydrating TanStack Query data from server-prefetched content while maintaining the benefits of server-side rendering.

**The Solution:** TanStack Query's **HydrationBoundary** combined with App Router's server components creates a powerful pattern for **server-side prefetching with seamless client-side hydration**. This approach enables instant page loads with server-rendered content that smoothly transitions to fully interactive client-side state management.

The key insight: **server components can prefetch and dehydrate query data, while client components can hydrate and take over with full Query functionality**. This creates the best of both worlds - fast initial loads with rich interactive experiences.

## Practical Walkthrough: Code Breakdown

Let's examine the App Router integration patterns from `examples/react/nextjs-app-prefetching/`:

### 1. Server/Client Query Client Management

```tsx
// app/get-query-client.ts
import { QueryClient, isServer } from '@tanstack/react-query'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
      },
      dehydrate: {
        // Include pending queries in dehydration
        shouldDehydrateQuery: (query) =>
          defaultShouldDehydrateQuery(query) ||
          query.state.status === 'pending',
      },
    },
  })
}

let browserQueryClient: QueryClient | undefined = undefined

export function getQueryClient() {
  if (isServer) {
    // Server: always make a new query client
    return makeQueryClient()
  } else {
    // Browser: make a new query client if we don't already have one
    if (!browserQueryClient) browserQueryClient = makeQueryClient()
    return browserQueryClient
  }
}
```

**What's happening:** Different QueryClient instances for server and browser environments. Server gets a new instance per request, browser reuses a singleton to prevent React Suspense issues.

**Why this pattern:** App Router server components run in a different environment from client components. Server-side queries need fresh instances per request, while client-side needs persistence across re-renders.

### 2. Query Options Pattern

```tsx
// app/pokemon.ts
import { queryOptions } from '@tanstack/react-query'

export const pokemonOptions = queryOptions({
  queryKey: ['pokemon'],
  queryFn: async () => {
    const response = await fetch('https://pokeapi.co/api/v2/pokemon/25')
    return response.json()
  },
})
```

**What's happening:** `queryOptions` creates reusable query configurations that work identically on server and client. This ensures consistent caching and data fetching across environments.

**Why queryOptions:** Eliminates duplication between server prefetching and client usage, provides type safety, and ensures identical query behavior regardless of where it's executed.

### 3. Server Component Prefetching

```tsx
// app/page.tsx (Server Component)
import { HydrationBoundary, dehydrate } from '@tanstack/react-query'
import { pokemonOptions } from '@/app/pokemon'
import { getQueryClient } from '@/app/get-query-client'
import { PokemonInfo } from './pokemon-info'

export default function Home() {
  const queryClient = getQueryClient()

  void queryClient.prefetchQuery(pokemonOptions)

  return (
    <main>
      <h1>Pokemon Info</h1>
      <HydrationBoundary state={dehydrate(queryClient)}>
        <PokemonInfo />
      </HydrationBoundary>
    </main>
  )
}
```

**What's happening:** The server component prefetches data using the same query options, then dehydrates the QueryClient state and passes it to the HydrationBoundary.

**Why server prefetching:** Data loads during SSR, so users see content immediately rather than loading spinners. The dehydrated state provides the initial cache for client-side hydration.

### 4. Client Component Hydration

```tsx
// app/pokemon-info.tsx ('use client')
'use client'

import { useSuspenseQuery } from '@tanstack/react-query'
import { pokemonOptions } from '@/app/pokemon'

export function PokemonInfo() {
  const { data } = useSuspenseQuery(pokemonOptions)

  return (
    <div>
      <figure>
        <img src={data.sprites.front_shiny} height={200} alt={data.name} />
        <h2>I'm {data.name}</h2>
      </figure>
    </div>
  )
}
```

**What's happening:** The client component uses `useSuspenseQuery` with the same query options. Since the data was prefetched on the server, this resolves immediately without suspending.

**Why Suspense here:** Even though data is prefetched, using Suspense ensures consistent behavior if the client-side ever needs to refetch (cache expiration, errors, etc.).

### 5. Provider Architecture

```tsx
// app/providers.tsx ('use client')
'use client'
import { QueryClientProvider } from '@tanstack/react-query'
import { getQueryClient } from '@/app/get-query-client'

export default function Providers({ children }) {
  const queryClient = getQueryClient()

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      <ReactQueryDevtools />
    </QueryClientProvider>
  )
}

// app/layout.tsx (Server Component)
export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
```

**What's happening:** The root layout (server component) wraps children with Providers (client component), which sets up the QueryClient for the entire app.

**Why this boundary:** App Router requires the QueryClientProvider to be in a client component, but the layout can be a server component that provides universal structure.

## Mental Model: Server-Client Hydration Bridge

### The Data Flow Architecture

```
Server Environment:
1. Server Component runs
2. QueryClient.prefetchQuery() executes
3. Data loads server-side
4. dehydrate() serializes cache state
5. HTML renders with data + serialized state

Client Environment:
1. HTML with data displays immediately
2. React hydrates
3. HydrationBoundary restores cache state
4. useSuspenseQuery finds cached data
5. Client takes over with full Query features
```

This creates seamless server-to-client handoff with no loading states.

### Query Client Lifecycle

```
Server Request:
new QueryClient() → prefetch → dehydrate → response

Browser Session:
singleton QueryClient → hydrate → interactive features
                ↓
         (persists across navigation)
```

Different lifecycles for different environments, but unified data layer.

### App Router Component Boundaries

```
Server Components:
├── Layout (universal app shell)
├── Page (prefetch data, setup boundaries) 
└── Other server components (static content)

Client Components:
├── Providers (Query setup)
├── Interactive Components (useQuery, mutations)
└── UI Components (user interactions)
```

### Why It's Designed This Way: Progressive Enhancement

Traditional SPA approach:
```
Load JS → Setup Client → Fetch Data → Render Content
(User waits for entire process)
```

App Router + TanStack Query approach:
```
Server: Fetch Data → Render HTML → Send to Browser
Client: Hydrate → Interactive Features Available
(User sees content immediately, interactivity layers on)
```

This creates **perceived instant loading** with **progressive enhancement** to full functionality.

### Advanced App Router Patterns

**Route-Level Prefetching**: Different data per route:
```tsx
// app/user/[id]/page.tsx
export default function UserPage({ params }) {
  const queryClient = getQueryClient()
  
  void queryClient.prefetchQuery(userOptions(params.id))
  void queryClient.prefetchQuery(userPostsOptions(params.id))
  
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <UserProfile userId={params.id} />
      <UserPosts userId={params.id} />
    </HydrationBoundary>
  )
}
```

**Nested Boundaries**: Granular hydration control:
```tsx
<HydrationBoundary state={dehydrate(queryClient, { include: ['user'] })}>
  <UserInfo />
  <HydrationBoundary state={dehydrate(queryClient, { include: ['posts'] })}>
    <UserPosts />
  </HydrationBoundary>
</HydrationBoundary>
```

**Streaming with Suspense**: Progressive data loading:
```tsx
export default function Page() {
  const queryClient = getQueryClient()
  
  void queryClient.prefetchQuery(criticalDataOptions)
  // Don't prefetch non-critical data
  
  return (
    <HydrationBoundary state={dehydrate(queryClient)}>
      <CriticalContent /> {/* Renders immediately */}
      <Suspense fallback={<Skeleton />}>
        <NonCriticalContent /> {/* Loads progressively */}
      </Suspense>
    </HydrationBoundary>
  )
}
```

**Error Boundaries with SSR**: Graceful error handling:
```tsx
export default function Page() {
  const queryClient = getQueryClient()
  
  try {
    await queryClient.prefetchQuery(dataOptions)
  } catch (error) {
    // Handle server-side errors gracefully
    console.error('Prefetch failed:', error)
  }
  
  return (
    <ErrorBoundary fallback={<ErrorPage />}>
      <HydrationBoundary state={dehydrate(queryClient)}>
        <Content />
      </HydrationBoundary>
    </ErrorBoundary>
  )
}
```

### Performance Optimizations

**Selective Dehydration**: Only dehydrate necessary queries:
```tsx
const dehydratedState = dehydrate(queryClient, {
  shouldDehydrateQuery: (query) => {
    return query.queryKey[0] === 'critical-data'
  }
})
```

**Stale Time Configuration**: Prevent unnecessary refetches:
```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes - good for SSR content
    },
  },
})
```

**Bundle Optimization**: Code splitting Query providers:
```tsx
const Providers = dynamic(() => import('./providers'), {
  ssr: false, // Only load client-side
})
```

### Further Exploration

Experiment with App Router patterns:

1. **Route Prefetching**: Implement different prefetching strategies per route
2. **Dynamic Routes**: Handle parameterized routes with dynamic query keys
3. **Layout Prefetching**: Prefetch shared data at layout levels
4. **Error Handling**: Test server-side vs client-side error scenarios

**Advanced Challenges**:

1. **Streaming SSR**: How would you implement progressive data streaming with multiple HydrationBoundaries?

2. **Route Transitions**: How would you handle navigation between routes with different prefetched data?

3. **Real-time Integration**: How would you combine SSR prefetching with real-time subscriptions?

4. **Cache Optimization**: How would you implement intelligent cache warming based on user behavior?

**Real-World Applications**:
- **E-commerce Sites**: Product pages with instant loading + interactive features
- **Content Platforms**: Articles with immediate content + dynamic interactions  
- **Dashboard Applications**: Critical data pre-loaded + real-time updates
- **Social Media**: Timeline content pre-rendered + interactive posting
- **SaaS Applications**: Workspace data pre-loaded + collaborative features

Next.js App Router + TanStack Query represents the cutting edge of React SSR patterns, combining instant loading experiences with powerful client-side state management. Understanding these patterns positions you at the forefront of modern React development practices.