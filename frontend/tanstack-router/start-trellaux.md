# TanStack Start Trellaux: Full-Stack React with No External Database

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/start-trellaux)**

## The Core Concept: Why This Example Exists

**The Problem:** Building full-stack React applications typically requires setting up complex infrastructure: backend APIs, databases, authentication, state management, and deployment pipelines. This complexity creates barriers for developers who want to prototype ideas quickly or build sophisticated applications without managing external services. Most full-stack frameworks force you to choose between simplicity and power.

**The TanStack Solution:** TanStack Start enables true full-stack development with the simplicity of a single React application. Trellaux demonstrates this by implementing a complete Trello-like kanban board application with real-time optimistic updates, drag-and-drop functionality, and persistent data - all without external databases or backend services.

This example showcases advanced patterns for building production-ready applications: optimistic mutations, query invalidation strategies, file-based routing with SSR, and sophisticated state management that bridges client and server concerns. You'll learn to build complex UIs that feel native and responsive while maintaining data consistency.

---

## Practical Walkthrough: Code Breakdown

### Full-Stack Router Setup (`router.tsx:36-51`)

```tsx
const router = routerWithQueryClient(
  createTanStackRouter({
    routeTree,
    defaultPreload: 'intent',
    defaultErrorComponent: DefaultCatchBoundary,
    defaultNotFoundComponent: () => <NotFound />,
    scrollRestoration: true,
    context: {
      queryClient,
    },
  }),
  queryClient,
)
```

This router configuration demonstrates TanStack Start's full-stack capabilities:

**`routerWithQueryClient`**: Bridges TanStack Router with React Query for unified data management
**Server Context**: The `queryClient` is available on both client and server
**Error Boundaries**: Centralized error handling with fallback components
**Preloading**: Intelligent prefetching for optimal performance

### Query Client with Optimistic Updates (`router.tsx:18-34`)

```tsx
const queryClient: QueryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnReconnect: () => !queryClient.isMutating(),
    },
  },
  mutationCache: new MutationCache({
    onError: (error) => {
      toast(error.message, { className: 'bg-red-500 text-white' })
    },
    onSettled: () => {
      if (queryClient.isMutating() === 1) {
        return queryClient.invalidateQueries()
      }
    },
  }),
})
```

This configuration enables sophisticated data management:

**Smart Reconnection**: Only refetches if no mutations are pending
**Global Error Handling**: All mutation errors automatically show toast notifications
**Automatic Invalidation**: Refreshes data when the last mutation completes
**Request Animation Frame**: Optimizes query scheduling for 60fps performance

### Optimistic Mutation Pattern (`queries.ts:28-53`)

```tsx
export function useCreateColumnMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createColumn,
    onMutate: async (variables) => {
      await queryClient.cancelQueries()
      queryClient.setQueryData(
        boardQueries.detail(variables.data.boardId).queryKey,
        (board) =>
          board
            ? {
                ...board,
                columns: [
                  ...board.columns,
                  {
                    ...variables.data,
                    order: board.columns.length + 1,
                    id: Math.random() + '',
                  },
                ],
              }
            : undefined,
      )
    },
  })
}
```

This pattern demonstrates **optimistic updates** - the UI updates immediately before the server confirms the change:

**Cancel In-Flight Queries**: Prevents stale data from overwriting optimistic updates
**Immediate UI Update**: Users see changes instantly for responsive interactions
**Temporary ID Generation**: Creates placeholder IDs until server responds
**Rollback Ready**: If mutation fails, React Query automatically reverts the optimistic update

### Server-Side Rendering with Data Loading (`routes/boards.$boardId.tsx:6-12`)

```tsx
export const Route = createFileRoute('/boards/$boardId')({
  component: Home,
  pendingComponent: () => <Loader />,
  loader: async ({ params, context: { queryClient } }) => {
    await queryClient.ensureQueryData(boardQueries.detail(params.boardId))
  },
})
```

This demonstrates **universal data loading**:

**SSR Data Prefetching**: Data loads on the server before page renders
**Shared Query Client**: Same query logic works on both client and server
**Loading States**: Graceful fallbacks during client-side navigation
**Hydration Ready**: Server-rendered data seamlessly continues on the client

### Complex State Management (`components/Board.tsx:25-48`)

```tsx
const itemsById = useMemo(
  () => new Map(board.items.map((item) => [item.id, item])),
  [board.items],
)

const columns = useMemo(() => {
  const columnsMap = new Map<string, ColumnWithItems>()

  for (const column of [...board.columns]) {
    columnsMap.set(column.id, { ...column, items: [] })
  }

  // add items to their columns
  for (const item of itemsById.values()) {
    const columnId = item.columnId
    const column = columnsMap.get(columnId)
    invariant(column, 'missing column')
    column.items.push(item)
  }

  return [...columnsMap.values()].sort((a, b) => a.order - b.order)
}, [board.columns, itemsById])
```

This shows **denormalized data management**:

**Entity Maps**: Efficient lookups for related data
**Computed Relationships**: Dynamically associates items with columns
**Performance Optimization**: Memoized calculations prevent unnecessary re-renders
**Type Safety**: Invariant assertions ensure data consistency

### Real-Time UI Updates (`queries.ts:76-97`)

```tsx
export function useUpdateCardMutation() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: updateItem,
    onMutate: async (variables) => {
      await queryClient.cancelQueries()
      queryClient.setQueryData(
        boardQueries.detail(variables.data.boardId).queryKey,
        (board) =>
          board
            ? {
                ...board,
                items: board.items.map((i) =>
                  i.id === variables.data.id ? variables.data : i,
                ),
              }
            : undefined,
      )
    },
  })
}
```

**Granular Updates**: Only the specific item changes, preserving other state
**Immutable Updates**: Creates new objects while maintaining referential equality where possible
**Conflict Resolution**: Server responses override optimistic updates if they differ

---

## Mental Model: Full-Stack State Management

### The Data Flow Pipeline

TanStack Start applications manage state across three layers:

```
Server State (Database/File System)
        ↕️
Query Client Cache (Universal)
        ↕️
Component State (UI)
```

**Traditional Approach**: Each layer maintained separately
```tsx
// Backend API
app.get('/api/boards', handler)

// Frontend State
const [boards, setBoards] = useState([])
useEffect(() => fetch('/api/boards'), [])

// Mutations
const updateBoard = async (data) => {
  await fetch('/api/boards/123', { method: 'PUT', body: data })
  setBoards(boards.map(b => b.id === 123 ? { ...b, ...data } : b))
}
```

**TanStack Start Approach**: Unified data layer
```tsx
// Universal query definition
export const boardQueries = {
  detail: (id: string) => queryOptions({
    queryKey: ['boards', 'detail', id],
    queryFn: () => getBoard({ data: id })
  })
}

// Automatic optimistic updates
const mutation = useMutation({
  mutationFn: updateBoard,
  onMutate: (variables) => {
    // UI updates immediately
    queryClient.setQueryData(['boards', 'detail', id], variables)
  }
})
```

### Optimistic Update Strategies

**Immediate Feedback Pattern**:
```tsx
// User clicks "Add Column"
// 1. UI shows new column instantly (optimistic)
// 2. Request sent to server
// 3. If success: keep optimistic state
// 4. If error: revert and show error
```

**Conflict Resolution**:
```tsx
// Multiple users editing same board
onMutate: (variables) => {
  // Store snapshot for rollback
  const previousData = queryClient.getQueryData(queryKey)
  queryClient.setQueryData(queryKey, variables)
  return { previousData }
},
onError: (err, variables, context) => {
  // Rollback on error
  queryClient.setQueryData(queryKey, context.previousData)
},
onSettled: () => {
  // Always refetch latest from server
  queryClient.invalidateQueries(queryKey)
}
```

### Server-Side Rendering Integration

**Universal Data Loading**:
```tsx
// Same code runs on server and client
const boardRoute = createFileRoute('/boards/$boardId')({
  loader: async ({ params, context: { queryClient } }) => {
    // Loads data on server during SSR
    // Hydrates existing data on client navigation
    await queryClient.ensureQueryData(boardQueries.detail(params.boardId))
  }
})
```

**Hydration Strategy**:
```tsx
// Server renders with data
<div>Board: Design System (loaded on server)</div>

// Client hydrates with same data
// No loading states or flashes
// Seamless transition to interactive
```

### Error Handling Patterns

**Hierarchical Error Boundaries**:
```tsx
// Global error handling
<Router defaultErrorComponent={DefaultCatchBoundary} />

// Route-specific errors
createFileRoute('/boards/$boardId')({
  errorComponent: BoardErrorComponent
})

// Mutation-specific errors
mutationCache: new MutationCache({
  onError: (error) => toast(error.message)
})
```

**Progressive Error Recovery**:
```tsx
// Level 1: Optimistic update fails
onError: () => {
  // Show toast, revert UI, allow retry
}

// Level 2: Route loader fails
errorComponent: ({ error, retry }) => (
  <div>
    <p>Failed to load board: {error.message}</p>
    <button onClick={retry}>Try Again</button>
  </div>
)

// Level 3: Application error
defaultErrorComponent: ({ error }) => (
  <div>Something went wrong: {error.message}</div>
)
```

### Performance Optimization Patterns

**Smart Invalidation**:
```tsx
// Don't refetch while mutations are happening
refetchOnReconnect: () => !queryClient.isMutating()

// Batch invalidations after all mutations complete
onSettled: () => {
  if (queryClient.isMutating() === 1) {
    queryClient.invalidateQueries()
  }
}
```

**Selective Updates**:
```tsx
// Only update specific parts of complex state
queryClient.setQueryData(boardQuery.queryKey, (board) => ({
  ...board,
  items: board.items.map(item => 
    item.id === updatedItem.id ? updatedItem : item
  )
}))
```

**Memory Management**:
```tsx
// Automatic garbage collection of unused queries
defaultOptions: {
  queries: {
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000,   // 10 minutes
  }
}
```

### Further Exploration

Try these experiments to master full-stack state management:

1. **Add Real-Time Collaboration**: Implement WebSocket updates that sync board changes across multiple clients.

2. **Offline Support**: Use React Query's built-in retry mechanisms and the browser's storage APIs for offline functionality.

3. **Complex Mutations**: Create operations that affect multiple entities (like moving a card between columns).

4. **Advanced Optimistic Updates**: Implement drag-and-drop with real-time optimistic reordering.

5. **Error Recovery**: Build sophisticated error handling that gracefully handles network failures and conflicts.

TanStack Start's unified approach to full-stack development eliminates the traditional boundaries between frontend and backend, enabling you to build sophisticated applications with the simplicity and power of React's component model extended across the entire stack.