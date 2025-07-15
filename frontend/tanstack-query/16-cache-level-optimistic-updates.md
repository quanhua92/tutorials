# Cache-Level Optimistic Updates

> **Based on**: [`examples/react/optimistic-updates-cache`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/optimistic-updates-cache)

## The Core Concept: Why This Example Exists

**The Problem:** While UI-level optimistic updates show pending states in the interface, **cache-level optimistic updates** go deeper - they immediately modify the actual cached data that all components consuming that query will see. This creates more seamless experiences where the optimistic change is reflected everywhere that data is used, but requires more sophisticated error handling and rollback mechanisms.

**The Solution:** TanStack Query's **cache manipulation APIs** (`setQueryData`, `cancelQueries`, `invalidateQueries`) enable direct cache updates during mutations. Combined with the mutation lifecycle hooks (`onMutate`, `onError`, `onSettled`), this creates optimistic updates that immediately reflect across your entire application while providing robust error recovery.

The key insight: **treat the cache as the authoritative source of truth that can be optimistically updated, then reconciled with server reality**. This creates truly responsive applications where user actions feel instant regardless of network conditions.

## Practical Walkthrough: Code Breakdown

Let's examine the cache-level optimistic update patterns from `examples/react/optimistic-updates-cache/src/pages/index.tsx`:

### 1. Mutation with Cache Manipulation

```tsx
const addTodoMutation = useMutation({
  mutationFn: async (newTodo: string) => {
    const response = await fetch('/api/data', {
      method: 'POST',
      body: JSON.stringify({ text: newTodo }),
      headers: { 'Content-Type': 'application/json' },
    })
    return await response.json()
  },
  // Mutation lifecycle hooks handle cache updates
  onMutate: async (newTodo: string) => { /* Cache update logic */ },
  onError: (err, variables, context) => { /* Rollback logic */ },
  onSettled: () => { /* Reconciliation logic */ },
})
```

**What's happening:** The mutation function handles the server request, while the lifecycle hooks (`onMutate`, `onError`, `onSettled`) manage cache state. This separation enables sophisticated optimistic update logic.

**Why separate concerns:** The server request logic remains clean while cache management is handled declaratively through lifecycle hooks.

### 2. Optimistic Cache Updates (onMutate)

```tsx
onMutate: async (newTodo: string) => {
  setText('')
  // Cancel any outgoing refetch
  // (so they don't overwrite our optimistic update)
  await queryClient.cancelQueries(todoListOptions)

  // Snapshot the previous value
  const previousTodos = queryClient.getQueryData(todoListOptions.queryKey)

  // Optimistically update to the new value
  if (previousTodos) {
    queryClient.setQueryData(todoListOptions.queryKey, {
      ...previousTodos,
      items: [
        ...previousTodos.items,
        { id: Math.random().toString(), text: newTodo },
      ],
    })
  }

  return { previousTodos }
},
```

**What's happening:** Three critical steps for safe optimistic updates:
1. **Cancel ongoing queries** to prevent race conditions
2. **Snapshot current cache state** for potential rollback
3. **Optimistically update cache** with expected result

**Why this sequence:** Race conditions between optimistic updates and background refetches can cause data loss. Canceling queries and snapshotting state ensures safe recovery.

### 3. Error Recovery (onError)

```tsx
onError: (err, variables, context) => {
  if (context?.previousTodos) {
    queryClient.setQueryData<Todos>(['todos'], context.previousTodos)
  }
},
```

**What's happening:** When mutations fail, restore the cache to its pre-optimistic state using the snapshot from `onMutate`.

**Why restore cache:** Failed mutations should leave no trace in the cache. Users should see the state as if the optimistic update never happened.

### 4. Reconciliation (onSettled)

```tsx
onSettled: () => queryClient.invalidateQueries({ queryKey: ['todos'] }),
```

**What's happening:** After mutation completion (success or failure), invalidate the cache to fetch fresh data from the server.

**Why always invalidate:** Regardless of optimistic update success/failure, the server is the source of truth. Invalidation ensures eventual consistency.

### 5. Query Options Pattern

```tsx
const todoListOptions = queryOptions({
  queryKey: ['todos'],
  queryFn: fetchTodos,
})

// Used in both query and cache operations
const { isFetching, ...queryInfo } = useQuery(todoListOptions)
await queryClient.cancelQueries(todoListOptions)
const previousTodos = queryClient.getQueryData(todoListOptions.queryKey)
```

**What's happening:** Query options are defined once and reused across queries and cache operations, ensuring consistency.

**Why centralize options:** Prevents mismatched query keys between queries and cache operations, which would break optimistic updates.

## Mental Model: Cache as Mutable State Store

### The Optimistic Update Lifecycle

```
Cache-Level Optimistic Update Flow:

1. User Action → Trigger Mutation
2. onMutate → Cancel Queries + Snapshot + Update Cache
3. UI Re-renders → Shows Optimistic State (instantly)
4. Server Request → In background
5a. Success → onSettled → Invalidate → Fresh Data
5b. Error → onError → Restore Snapshot → onSettled → Invalidate
```

The cache becomes a sophisticated state machine that coordinates optimistic updates with server reconciliation.

### Cache State Transitions

```
Cache State Machine:
Initial State → Optimistic State → Server Reality

Example:
todos: [A, B, C] → todos: [A, B, C, D] → todos: [A, B, C, D'] (server version)
                      ↑ Optimistic        ↑ Reconciled
                   
If error:
todos: [A, B, C] → todos: [A, B, C, D] → todos: [A, B, C] → fresh server data
                      ↑ Optimistic        ↑ Rollback      ↑ Reconciliation
```

### Race Condition Prevention

```
Without cancelQueries:
1. User adds todo → Optimistic update → Cache: [A, B, C, D]
2. Background refetch completes → Cache: [A, B, C] (overwrites optimistic)
3. User confused - their action disappeared

With cancelQueries:
1. User adds todo → Cancel ongoing queries → Optimistic update → Cache: [A, B, C, D]
2. No race condition - optimistic update preserved
3. Invalidation after mutation → Fresh data with server changes
```

### Why It's Designed This Way: Global Consistency

UI-level optimistic updates affect single components:
```
Component A: Shows optimistic state
Component B: Shows stale state (inconsistency)
```

Cache-level optimistic updates affect all consumers:
```
Component A: Shows optimistic state
Component B: Shows optimistic state (consistency)
All consumers of ['todos'] query see the same optimistic state
```

### Advanced Cache Optimistic Patterns

**Complex Object Updates**: Handle nested data structures:
```tsx
onMutate: async (updatedUser) => {
  await queryClient.cancelQueries(['users'])
  
  const previousUsers = queryClient.getQueryData(['users'])
  const previousUser = queryClient.getQueryData(['user', updatedUser.id])
  
  // Update both list and detail caches
  if (previousUsers) {
    queryClient.setQueryData(['users'], 
      previousUsers.map(user => 
        user.id === updatedUser.id ? { ...user, ...updatedUser } : user
      )
    )
  }
  
  if (previousUser) {
    queryClient.setQueryData(['user', updatedUser.id], {
      ...previousUser,
      ...updatedUser
    })
  }
  
  return { previousUsers, previousUser }
}
```

**Optimistic Deletions**: Remove items optimistically:
```tsx
const deleteTodoMutation = useMutation({
  mutationFn: (todoId) => fetch(`/api/todos/${todoId}`, { method: 'DELETE' }),
  onMutate: async (todoId) => {
    await queryClient.cancelQueries(['todos'])
    
    const previousTodos = queryClient.getQueryData(['todos'])
    
    if (previousTodos) {
      queryClient.setQueryData(['todos'], {
        ...previousTodos,
        items: previousTodos.items.filter(todo => todo.id !== todoId)
      })
    }
    
    return { previousTodos }
  },
  onError: (err, todoId, context) => {
    if (context?.previousTodos) {
      queryClient.setQueryData(['todos'], context.previousTodos)
    }
  },
  onSettled: () => {
    queryClient.invalidateQueries(['todos'])
  }
})
```

**Batch Optimistic Updates**: Handle multiple related updates:
```tsx
const batchUpdateMutation = useMutation({
  mutationFn: (updates) => Promise.all(updates.map(update => updateItem(update))),
  onMutate: async (updates) => {
    // Cancel all affected queries
    const queryKeysToCancel = updates.map(update => ['item', update.id])
    await Promise.all(queryKeysToCancel.map(key => queryClient.cancelQueries(key)))
    
    // Snapshot all affected data
    const snapshots = {}
    for (const update of updates) {
      snapshots[update.id] = queryClient.getQueryData(['item', update.id])
    }
    
    // Apply all optimistic updates
    for (const update of updates) {
      const previous = snapshots[update.id]
      if (previous) {
        queryClient.setQueryData(['item', update.id], { ...previous, ...update })
      }
    }
    
    return { snapshots }
  },
  onError: (err, updates, context) => {
    // Restore all snapshots
    if (context?.snapshots) {
      for (const update of updates) {
        const snapshot = context.snapshots[update.id]
        if (snapshot) {
          queryClient.setQueryData(['item', update.id], snapshot)
        }
      }
    }
  },
  onSettled: (data, error, updates) => {
    // Invalidate all affected queries
    const queryKeysToInvalidate = updates.map(update => ['item', update.id])
    queryKeysToInvalidate.forEach(key => queryClient.invalidateQueries(key))
  }
})
```

**Conditional Optimistic Updates**: Smart optimism based on context:
```tsx
const smartMutation = useMutation({
  mutationFn: addTodo,
  onMutate: async (newTodo) => {
    // Only do optimistic updates for likely-to-succeed scenarios
    const userHasGoodConnection = navigator.connection?.effectiveType === '4g'
    const userHasAuth = getCurrentUser()?.authenticated
    
    if (!userHasGoodConnection || !userHasAuth) {
      return { skipOptimistic: true }
    }
    
    // Proceed with optimistic update only if conditions are favorable
    await queryClient.cancelQueries(['todos'])
    const previousTodos = queryClient.getQueryData(['todos'])
    
    if (previousTodos) {
      queryClient.setQueryData(['todos'], optimisticallyAddTodo(previousTodos, newTodo))
    }
    
    return { previousTodos }
  },
  onError: (err, variables, context) => {
    if (!context?.skipOptimistic && context?.previousTodos) {
      queryClient.setQueryData(['todos'], context.previousTodos)
    }
  }
})
```

### Error Handling Strategies

**Granular Error Recovery**: Different strategies for different errors:
```tsx
onError: (error, variables, context) => {
  if (error.status === 409) {
    // Conflict - show merge UI instead of rollback
    showConflictResolution(variables, context?.previousTodos)
  } else if (error.status === 403) {
    // Permission error - rollback and show auth prompt
    if (context?.previousTodos) {
      queryClient.setQueryData(['todos'], context.previousTodos)
    }
    showAuthPrompt()
  } else {
    // Generic error - standard rollback
    if (context?.previousTodos) {
      queryClient.setQueryData(['todos'], context.previousTodos)
    }
    showErrorToast(error.message)
  }
}
```

**Partial Failure Handling**: When batch operations partially succeed:
```tsx
onError: (error, variables, context) => {
  if (error.partialSuccess) {
    // Some items succeeded, update cache to reflect partial success
    const succeededItems = error.succeededItems
    const failedItems = error.failedItems
    
    // Only rollback failed items
    const currentCache = queryClient.getQueryData(['todos'])
    const correctedCache = {
      ...currentCache,
      items: currentCache.items.filter(item => 
        !failedItems.find(failed => failed.tempId === item.id)
      )
    }
    
    queryClient.setQueryData(['todos'], correctedCache)
  } else {
    // Total failure - full rollback
    if (context?.previousTodos) {
      queryClient.setQueryData(['todos'], context.previousTodos)
    }
  }
}
```

### Further Exploration

Experiment with cache-level optimistic patterns:

1. **Complex Relationships**: Try optimistic updates with normalized data structures
2. **Error Scenarios**: Test various failure modes and recovery strategies
3. **Performance**: Measure the impact of cache operations on large datasets
4. **Multi-User**: Handle optimistic updates in collaborative environments

**Advanced Challenges**:

1. **Conflict Resolution**: How would you handle optimistic updates when multiple users modify the same data?

2. **Undo/Redo**: How would you implement undo/redo functionality with optimistic updates?

3. **Offline Queue**: How would you queue optimistic updates when offline and replay them when online?

4. **Real-time Integration**: How would you coordinate optimistic updates with real-time subscriptions?

**Real-World Applications**:
- **Collaborative Editing**: Document editing with immediate visual feedback
- **Social Media**: Instant likes, comments, and shares with eventual consistency
- **E-commerce**: Cart updates and inventory changes with optimistic feedback
- **Project Management**: Task updates that reflect immediately across all views
- **Communication Apps**: Message sending with instant display and delivery confirmation

Cache-level optimistic updates represent the pinnacle of responsive user interface design - creating applications that feel instant and reliable while maintaining data integrity and providing graceful error recovery. Understanding these patterns enables building applications that rival native app responsiveness while providing the flexibility and reach of web technologies.