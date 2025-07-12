# TanStack Start with React Query: Server-Client Data Synchronization

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/start-basic-react-query)**

## The Core Concept: Why This Example Exists

**The Problem:** Modern applications need sophisticated data management that works seamlessly between server and client. Traditional approaches force you to choose between server-side rendering with no client-side caching, or client-side data fetching with no SSR benefits. Coordinating between server rendering, client hydration, cache invalidation, optimistic updates, and real-time data becomes exponentially complex as applications grow.

**The TanStack Solution:** TanStack Start + React Query creates **unified data architecture** where server-side rendering, client-side caching, and real-time updates work together automatically. Think of it like having a single data layer that intelligently decides whether to fetch from server, serve from cache, or update in real-time, while maintaining consistency between server rendering and client interactivity.

This example demonstrates how React Query's powerful caching and synchronization capabilities integrate with TanStack Start's server functions to create applications that are both fast on first load (SSR) and responsive during interaction (client-side caching).

---

## Practical Walkthrough: Code Breakdown

### Query Client Integration (`router.tsx:8-16`)

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      gcTime: 1000 * 60 * 30,   // 30 minutes
    },
  },
})

export const router = createRouter({
  routeTree,
  context: { queryClient },
})
```

The foundation integrates React Query with the router:

- **Shared query client**: Same instance used for SSR and client-side caching
- **Router context**: Query client available to all routes and components
- **Default caching**: 5-minute stale time with 30-minute garbage collection
- **Type safety**: Router context is typed to include queryClient

### Server-Side Query Integration (`routes/posts.route.tsx`)

```tsx
export const Route = createFileRoute('/posts')({
  loader: ({ context }) => {
    // Server-side query execution
    return context.queryClient.ensureQueryData(postsQueryOptions())
  },
  component: PostsLayout,
})

// Query options define the data fetching strategy
export const postsQueryOptions = () => ({
  queryKey: ['posts'],
  queryFn: async () => {
    // This runs on both server and client
    return await fetchPosts()
  },
  staleTime: 1000 * 60 * 5, // 5 minutes
})
```

Server-side integration provides:

- **ensureQueryData**: Fetches data if not in cache, uses cache if available
- **Query options pattern**: Reusable query definitions for server and client
- **Automatic hydration**: Server data automatically populates client cache
- **Cache deduplication**: Same query won't run twice during SSR

### Client-Side Cache Usage (`routes/posts.index.tsx`)

```tsx
import { useSuspenseQuery } from '@tanstack/react-query'
import { postsQueryOptions } from './posts.route'

function PostsIndex() {
  // Client-side cache access - data is already available from SSR
  const { data: posts } = useSuspenseQuery(postsQueryOptions())
  
  return (
    <div>
      {posts.map(post => (
        <PostCard key={post.id} post={post} />
      ))}
    </div>
  )
}
```

Client-side usage benefits:

- **Suspense integration**: No loading states needed if data is cached
- **Automatic revalidation**: Stale data refetches in background
- **Optimistic updates**: UI updates immediately, syncs with server later
- **Error boundaries**: React Query errors integrate with route error handling

### Dynamic Route with Prefetching (`routes/posts.$postId.tsx`)

```tsx
export const Route = createFileRoute('/posts/$postId')({
  loader: ({ context, params }) => {
    // Parallel loading of post and related data
    return Promise.all([
      context.queryClient.ensureQueryData(postQueryOptions(params.postId)),
      context.queryClient.prefetchQuery(commentsQueryOptions(params.postId)),
    ])
  },
  component: PostDetail,
})

function PostDetail() {
  const { postId } = Route.useParams()
  
  // Primary data - guaranteed to be available
  const { data: post } = useSuspenseQuery(postQueryOptions(postId))
  
  // Prefetched data - may be loading
  const { data: comments, isLoading } = useQuery(commentsQueryOptions(postId))
  
  return (
    <div>
      <h1>{post.title}</h1>
      <p>{post.content}</p>
      
      {isLoading ? (
        <CommentsLoading />
      ) : (
        <CommentsList comments={comments} />
      )}
    </div>
  )
}
```

Advanced loading patterns:

- **ensureQueryData**: Critical data loads before route renders
- **prefetchQuery**: Optional data starts loading but doesn't block rendering
- **Parallel loading**: Multiple queries execute simultaneously
- **Progressive enhancement**: Core content shows immediately, details fill in

### Mutation with Cache Updates (`components/AddPostForm.tsx`)

```tsx
function AddPostForm() {
  const queryClient = useQueryClient()
  
  const addPostMutation = useMutation({
    mutationFn: async (newPost) => {
      return await createPost(newPost)
    },
    onMutate: async (newPost) => {
      // Optimistic update
      await queryClient.cancelQueries({ queryKey: ['posts'] })
      
      const previousPosts = queryClient.getQueryData(['posts'])
      
      queryClient.setQueryData(['posts'], (old) => [
        ...old,
        { ...newPost, id: 'temp-' + Date.now() }
      ])
      
      return { previousPosts }
    },
    onError: (err, newPost, context) => {
      // Revert optimistic update on error
      queryClient.setQueryData(['posts'], context.previousPosts)
    },
    onSettled: () => {
      // Refetch to sync with server
      queryClient.invalidateQueries({ queryKey: ['posts'] })
    },
  })
  
  return (
    <form onSubmit={(e) => {
      e.preventDefault()
      const formData = new FormData(e.target)
      addPostMutation.mutate({
        title: formData.get('title'),
        content: formData.get('content'),
      })
    }}>
      {/* Form fields */}
    </form>
  )
}
```

Sophisticated mutation patterns:

- **Optimistic updates**: UI updates immediately for perceived performance
- **Error recovery**: Failed mutations revert to previous state
- **Cache invalidation**: Successful mutations trigger data refresh
- **Conflict resolution**: Server data takes precedence over optimistic updates

### Real-time Data Integration (`routes/users.route.tsx`)

```tsx
export const Route = createFileRoute('/users')({
  loader: ({ context }) => {
    return context.queryClient.ensureQueryData(usersQueryOptions())
  },
  component: UsersPage,
})

function UsersPage() {
  const { data: users } = useSuspenseQuery(usersQueryOptions())
  
  // Real-time updates via server-sent events
  useEffect(() => {
    const eventSource = new EventSource('/api/users/stream')
    
    eventSource.onmessage = (event) => {
      const update = JSON.parse(event.data)
      
      queryClient.setQueryData(['users'], (oldUsers) => {
        return oldUsers.map(user => 
          user.id === update.id ? { ...user, ...update } : user
        )
      })
    }
    
    return () => eventSource.close()
  }, [])
  
  return <UsersList users={users} />
}
```

Real-time synchronization:

- **Server-sent events**: Live updates from server to client
- **Cache updates**: Real-time data updates React Query cache
- **UI reactivity**: Components automatically re-render with new data
- **Connection management**: Cleanup prevents memory leaks

---

## Mental Model: Thinking in Unified Data Architecture

### The Data Flow Cycle

Think of TanStack Start + React Query as a unified data pipeline that operates across the client-server boundary:

```
Server Render → Client Hydration → User Interaction → Cache Update → Server Sync
     ↓              ↓                    ↓              ↓             ↓
Initial Data    Cache Populated    Optimistic Update  UI Response   Data Consistency
```

### Caching Strategy Layers

**1. Server-Side Caching (SSR)**
```tsx
// Route loader ensures data is available for initial render
loader: ({ context }) => {
  return context.queryClient.ensureQueryData(queryOptions())
}

// First page load has no loading states
function Component() {
  const { data } = useSuspenseQuery(queryOptions()) // Data already available
  return <div>{data.title}</div>
}
```

**2. Client-Side Caching (Navigation)**
```tsx
// Subsequent navigations use cached data
const { data, isStale } = useQuery(queryOptions())

// Stale data shows immediately, fresh data loads in background
if (isStale) {
  // Background refetch happening
}
```

**3. Optimistic Caching (Mutations)**
```tsx
onMutate: async (newData) => {
  // Update cache immediately for responsive UI
  queryClient.setQueryData(queryKey, (old) => updateFunction(old, newData))
  
  // Server sync happens in background
}
```

### Query Organization Patterns

**1. Query Options as Single Source of Truth**
```tsx
// Define query behavior once, use everywhere
export const postQueryOptions = (id: string) => ({
  queryKey: ['posts', id],
  queryFn: () => fetchPost(id),
  staleTime: 1000 * 60 * 5,
  select: (post) => ({
    ...post,
    formattedDate: formatDate(post.createdAt)
  })
})

// Use in route loader
loader: ({ context, params }) => 
  context.queryClient.ensureQueryData(postQueryOptions(params.id))

// Use in component
const { data: post } = useSuspenseQuery(postQueryOptions(params.id))

// Use in prefetching
queryClient.prefetchQuery(postQueryOptions(nextId))
```

**2. Hierarchical Cache Management**
```tsx
// Parent route loads list data
const postsRoute = createRoute({
  loader: ({ context }) => 
    context.queryClient.ensureQueryData(postsQueryOptions())
})

// Child route loads detail data
const postRoute = createRoute({
  getParentRoute: () => postsRoute,
  loader: ({ context, params }) => {
    // List is already cached from parent
    // Only load detail if not cached
    return context.queryClient.ensureQueryData(postQueryOptions(params.id))
  }
})

// Components access both parent and child data
function PostDetail() {
  const posts = useQuery(postsQueryOptions()) // From parent
  const post = useSuspenseQuery(postQueryOptions(params.id)) // From this route
}
```

**3. Cross-Route Cache Coordination**
```tsx
// Mutations update multiple related queries
const deletePostMutation = useMutation({
  mutationFn: deletePost,
  onSuccess: (deletedPost) => {
    // Remove from list cache
    queryClient.setQueryData(['posts'], (old) => 
      old.filter(post => post.id !== deletedPost.id)
    )
    
    // Remove detail cache
    queryClient.removeQueries(['posts', deletedPost.id])
    
    // Update user's post count
    queryClient.setQueryData(['users', deletedPost.authorId], (user) => ({
      ...user,
      postCount: user.postCount - 1
    }))
  }
})
```

### Performance Optimization Strategies

**1. Intelligent Prefetching**
```tsx
// Route-based prefetching
<Link 
  to="/posts/$postId" 
  params={{ postId: '123' }}
  onMouseEnter={() => {
    queryClient.prefetchQuery(postQueryOptions('123'))
  }}
>
  View Post
</Link>

// Intersection observer prefetching
const { ref, inView } = useInView()

useEffect(() => {
  if (inView) {
    queryClient.prefetchQuery(nextPageQueryOptions())
  }
}, [inView])
```

**2. Background Synchronization**
```tsx
// Keep data fresh with background updates
const useLiveData = (queryOptions) => {
  const query = useQuery(queryOptions)
  
  useEffect(() => {
    const interval = setInterval(() => {
      queryClient.invalidateQueries({ queryKey: queryOptions.queryKey })
    }, 30000) // Refresh every 30 seconds
    
    return () => clearInterval(interval)
  }, [])
  
  return query
}
```

**3. Memory Management**
```tsx
// Configure garbage collection
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5,  // 5 minutes fresh
      gcTime: 1000 * 60 * 30,    // 30 minutes before cleanup
      retry: (failureCount, error) => {
        // Custom retry logic based on error type
        if (error.status === 404) return false
        return failureCount < 3
      }
    }
  }
})
```

### Why TanStack Start + React Query?

**Traditional Data Fetching:**
- Separate server rendering and client data management
- Manual cache synchronization
- Complex loading state management
- Inconsistent error handling
- Performance trade-offs between SSR and SPA

**Unified Data Architecture:**
- Seamless server-to-client data flow
- Automatic cache hydration and synchronization
- Built-in optimistic updates and background syncing
- Consistent error boundaries across server and client
- Best of both SSR and SPA performance

### Further Exploration

Try these experiments to deepen your understanding:

1. **Infinite Queries**: Implement pagination with `useInfiniteQuery` for large datasets.

2. **Real-time Sync**: Add WebSocket integration that automatically updates React Query cache.

3. **Offline Support**: Configure React Query to work offline with background sync when connection returns.

4. **Error Recovery**: Build sophisticated error handling that retries failed queries with exponential backoff.

5. **Performance Monitoring**: Add query performance tracking and cache hit rate monitoring.

6. **Complex Mutations**: Implement multi-step workflows that coordinate multiple API calls and cache updates.

The combination of TanStack Start and React Query represents the evolution toward **unified data architecture** - where server-side rendering, client-side caching, real-time updates, and optimistic interactions work together seamlessly to create applications that are both performant and responsive.