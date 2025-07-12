# tRPC Integration: End-to-End Type Safety with API Calls

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/with-trpc)**

## The Core Concept: Why This Example Exists

**The Problem:** Building full-stack applications traditionally requires maintaining separate type definitions for frontend and backend, manual API documentation, and constant synchronization between client and server code. Route-based data loading can become complex when coordinating with external API calls, cache management, and error handling.

**The TanStack Solution:** TanStack Router integrates seamlessly with tRPC to create **end-to-end type safety** - your API types are automatically shared between client and server, your route loaders can call tRPC procedures directly, and your components receive fully typed data. Think of it like having a single TypeScript project that spans both your browser and server, with the router acting as the intelligent coordinator.

This example demonstrates how tRPC procedures integrate with route loaders, how to share the tRPC client through router context, and how to achieve type safety from database to component without manual type definitions.

---

## Practical Walkthrough: Code Breakdown

### tRPC Client Setup (`trpc.ts:1-13`)

```tsx
import { createTRPCClient, httpBatchLink } from '@trpc/client'
import type { AppRouter } from './server/trpc'

export const trpc = createTRPCClient<AppRouter>({
  links: [
    httpBatchLink({
      url: '/trpc',
    }),
  ],
})
```

This creates the bridge between your frontend and backend:

- **AppRouter type**: Imported from your server, providing complete type information
- **httpBatchLink**: Batches multiple calls into single HTTP requests for performance
- **url: '/trpc'**: Standard tRPC endpoint convention

The client automatically knows about every procedure on your server without manual configuration.

### Router Context Integration (`main.tsx:22-24`)

```tsx
context: {
  trpc,
},
```

By providing tRPC in the router context, it becomes available to all route loaders and components:

- **Global availability**: Every route can access the tRPC client
- **Type safety**: Context is typed, so TypeScript knows tRPC is available
- **Consistent interface**: Same client instance across your entire application

### Route-Level tRPC Integration

```tsx
// In any route file
export const Route = createFileRoute('/posts/')({
  loader: async ({ context }) => {
    const posts = await context.trpc.posts.list.query()
    return { posts }
  },
  component: PostsComponent,
})

function PostsComponent() {
  const { posts } = Route.useLoaderData() // Fully typed!
  // posts is automatically typed based on your tRPC procedure return type
}
```

This pattern provides several benefits:

- **Server-side data loading**: Data is fetched during route transitions
- **Automatic type inference**: Return types flow from server to component
- **Cache integration**: Works with TanStack Router's built-in caching
- **Error boundaries**: tRPC errors are handled by route error components

### Advanced tRPC Patterns (`routes/posts/$postId.tsx`)

```tsx
export const Route = createFileRoute('/posts/$postId')({
  loader: async ({ context, params }) => {
    // Multiple tRPC calls can be batched
    const [post, comments] = await Promise.all([
      context.trpc.posts.byId.query({ id: params.postId }),
      context.trpc.comments.byPost.query({ postId: params.postId })
    ])
    
    return { post, comments }
  },
  errorComponent: ({ error }) => {
    // tRPC errors include detailed type information
    if (error.data?.code === 'NOT_FOUND') {
      return <div>Post not found</div>
    }
    return <div>Something went wrong: {error.message}</div>
  },
  component: PostComponent,
})
```

This demonstrates:
- **Parallel data loading**: Multiple tRPC calls execute simultaneously
- **Parameter passing**: Route parameters flow to tRPC procedures
- **Typed error handling**: tRPC errors include structured error information
- **Performance optimization**: Data loads before component renders

### Mutations with Router Integration

```tsx
function EditPostComponent() {
  const router = useRouter()
  const { post } = Route.useLoaderData()
  
  const updatePost = async (data: UpdatePostInput) => {
    await trpc.posts.update.mutate({
      id: post.id,
      ...data
    })
    
    // Invalidate and refetch the current route
    router.invalidate()
    
    // Or navigate to the updated post
    router.navigate({ to: '/posts/$postId', params: { postId: post.id } })
  }
  
  return (
    <form onSubmit={(e) => {
      e.preventDefault()
      const formData = new FormData(e.target)
      updatePost({ title: formData.get('title') })
    }}>
      {/* Form fields */}
    </form>
  )
}
```

Key mutation patterns:
- **Type-safe mutations**: Input types are enforced by tRPC schemas
- **Router invalidation**: Automatically refetches affected routes
- **Navigation coordination**: Seamless transitions after successful mutations

### Context Integration for Real-time Features

```tsx
// In router context
const router = createRouter({
  routeTree,
  context: {
    trpc,
    // Add subscription client for real-time features
    subscription: trpc.subscription,
  },
})

// In components
function LivePostComponent() {
  const { post } = Route.useLoaderData()
  const [livePost, setLivePost] = React.useState(post)
  
  React.useEffect(() => {
    const subscription = trpc.posts.subscribe.subscribe(
      { id: post.id },
      {
        onData: (updatedPost) => setLivePost(updatedPost),
        onError: (error) => console.error('Subscription error:', error),
      }
    )
    
    return () => subscription.unsubscribe()
  }, [post.id])
  
  return <div>{livePost.title}</div>
}
```

---

## Mental Model: Thinking in End-to-End Types

### The Type Flow

Think of tRPC + TanStack Router like a type-safe pipeline that spans your entire stack:

```
Database Schema → tRPC Procedures → Router Loaders → Components
       ↓              ↓               ↓            ↓
   User Table    posts.list.query()  useLoaderData()  props: User[]
```

Each step maintains and refines type information without manual intervention.

### Architecture Patterns

**1. Data-First Routing**
```tsx
// Routes are organized around data requirements
const routeTree = rootRoute.addChildren([
  postsRoute.addChildren([
    postsListRoute,     // loads: posts.list.query()
    postDetailRoute,    // loads: posts.byId.query() + comments.byPost.query()
    postEditRoute,      // loads: posts.byId.query() for editing
  ]),
  usersRoute.addChildren([
    usersListRoute,     // loads: users.list.query()
    userProfileRoute,   // loads: users.byId.query() + posts.byUser.query()
  ])
])
```

**2. Layered Data Loading**
```tsx
// Parent route loads common data
const dashboardRoute = createRoute({
  loader: async ({ context }) => {
    const [user, notifications] = await Promise.all([
      context.trpc.auth.me.query(),
      context.trpc.notifications.list.query()
    ])
    return { user, notifications }
  }
})

// Child routes access parent data + load specific data
const dashboardPostsRoute = createRoute({
  getParentRoute: () => dashboardRoute,
  loader: async ({ context }) => {
    const posts = await context.trpc.posts.list.query()
    return { posts }
  },
  component: ({ route }) => {
    const { user, notifications } = route.useRouteContext() // From parent
    const { posts } = route.useLoaderData() // From this route
  }
})
```

**3. Error Boundary Integration**
```tsx
const apiRoute = createRoute({
  errorComponent: ({ error }) => {
    // tRPC errors are structured and typed
    if (error.data?.code === 'UNAUTHORIZED') {
      return <LoginRedirect />
    }
    
    if (error.data?.code === 'NOT_FOUND') {
      return <NotFoundPage />
    }
    
    if (error.data?.code === 'INTERNAL_SERVER_ERROR') {
      return <ErrorReporting error={error} />
    }
    
    return <GenericError />
  }
})
```

### Performance Optimizations

**1. Preloading with tRPC**
```tsx
const router = createRouter({
  routeTree,
  defaultPreload: 'intent', // Preload on hover
  context: { trpc },
})

// When users hover over links, tRPC calls execute early
<Link to="/posts/$postId" params={{ postId: '123' }}>
  View Post {/* tRPC call starts on hover */}
</Link>
```

**2. Caching Strategies**
```tsx
const router = createRouter({
  routeTree,
  defaultStaleTime: 5 * 60 * 1000, // 5 minutes
  context: { trpc },
})

// Data stays fresh for 5 minutes, reducing API calls
// tRPC's built-in caching works with router caching
```

**3. Optimistic Updates**
```tsx
const updatePost = async (data: UpdatePostInput) => {
  // Optimistically update the UI
  router.setRouteData('/posts/$postId', (old) => ({
    ...old,
    post: { ...old.post, ...data }
  }))
  
  try {
    await trpc.posts.update.mutate(data)
    // Success - optimistic update was correct
  } catch (error) {
    // Revert optimistic update
    router.invalidate()
    throw error
  }
}
```

### Why tRPC + TanStack Router?

Traditional API integration:
```tsx
// Manual type definitions
interface User {
  id: string
  name: string
  email: string
}

// Manual API calls
const fetchUser = async (id: string): Promise<User> => {
  const response = await fetch(`/api/users/${id}`)
  return response.json() // No type safety
}

// Manual error handling
const UserComponent = () => {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  
  useEffect(() => {
    fetchUser(id)
      .then(setUser)
      .catch(setError)
      .finally(() => setLoading(false))
  }, [id])
  
  if (loading) return <Spinner />
  if (error) return <Error />
  return <UserProfile user={user!} />
}
```

tRPC + TanStack Router:
```tsx
// Types automatically shared from server
export const Route = createFileRoute('/users/$userId')({
  loader: ({ context, params }) => 
    context.trpc.users.byId.query({ id: params.userId }),
  component: UserComponent,
})

function UserComponent() {
  const user = Route.useLoaderData() // Fully typed, always available
  return <UserProfile user={user} />
}
```

Benefits:
1. **Zero manual types**: Server types automatically flow to client
2. **No loading states**: Data is ready when component mounts
3. **Automatic error handling**: Route error boundaries catch tRPC errors
4. **Performance optimization**: Built-in caching and preloading
5. **Developer experience**: Autocomplete, refactoring, and type checking work seamlessly

### Further Exploration

Try these experiments to deepen your understanding:

1. **Real-time Integration**: Add tRPC subscriptions that update route data automatically.

2. **Optimistic Updates**: Implement optimistic mutations that update the UI before server confirmation.

3. **Error Recovery**: Build sophisticated error handling that retries failed tRPC calls or falls back to cached data.

4. **Performance Monitoring**: Add timing and metrics to understand the performance characteristics of your tRPC + Router integration.

5. **Authentication Flow**: Implement login/logout that coordinates between tRPC procedures and router navigation.

The combination of tRPC and TanStack Router eliminates the traditional boundary between frontend and backend development, creating a unified, type-safe development experience that scales from simple data fetching to complex real-time applications.