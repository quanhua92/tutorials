# Optimistic Updates: Building Responsive UIs

> **Based on**: [`examples/react/optimistic-updates-ui`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/optimistic-updates-ui)

## The Core Concept: Why This Example Exists

**The Problem:** Traditional form submissions create frustrating user experiences - users click "Submit," then wait while staring at a disabled button or loading spinner. If the submission fails, they lose context and must retry from scratch. This stop-and-wait pattern makes web apps feel sluggish compared to native applications.

**The Solution:** **Optimistic updates** assume success and immediately show the expected result in the UI, while simultaneously sending the request to the server. If the server confirms success, nothing changes (the user already sees the result). If it fails, the UI reverts and provides clear recovery options.

TanStack Query's mutation system makes optimistic updates reliable by automatically handling the complex coordination between UI state, server requests, and error recovery. The key insight: **show users the world they expect, then reconcile with reality.**

## Practical Walkthrough: Code Breakdown

Let's examine the optimistic UI patterns from `examples/react/optimistic-updates-ui/src/pages/index.tsx`:

### 1. The Mutation Setup

```tsx
const addTodoMutation = useMutation({
  mutationFn: async (newTodo: string) => {
    const response = await fetch('/api/data', {
      method: 'POST',
      body: JSON.stringify({ text: newTodo }),
      headers: { 'Content-Type': 'application/json' },
    })
    if (!response.ok) {
      throw new Error('Something went wrong.')
    }
    return await response.json()
  },
  onSettled: () => queryClient.invalidateQueries({ queryKey: ['todos'] }),
})
```

**What's happening:** `useMutation` separates the actual server request (`mutationFn`) from the side effects (`onSettled`). When the mutation completes (success or failure), it invalidates the todos query to refetch fresh data.

**Why `onSettled` not `onSuccess`:** Using `onSettled` ensures data is refetched regardless of mutation outcome, guaranteeing the UI eventually shows truth from the server.

### 2. Optimistic UI Rendering

```tsx
<ul>
  {todoQuery.data.items.map((todo) => (
    <li key={todo.id}>{todo.text}</li>
  ))}
  {addTodoMutation.isPending && (
    <li style={{ opacity: 0.5 }}>{addTodoMutation.variables}</li>
  )}
  {addTodoMutation.isError && (
    <li style={{ color: 'red' }}>
      {addTodoMutation.variables}
      <button onClick={() => addTodoMutation.mutate(addTodoMutation.variables)}>
        Retry
      </button>
    </li>
  )}
</ul>
```

**What's happening:** The UI shows three distinct states:
- **Real todos**: From the server (`todoQuery.data.items`)
- **Pending todo**: Optimistically shown while request is in-flight (dimmed)
- **Failed todo**: Shown in error state with retry option (red)

**Why `addTodoMutation.variables`:** The mutation stores the submitted data, allowing the UI to display what the user tried to add, even during loading or error states.

### 3. Form Submission Flow

```tsx
<form
  onSubmit={(e) => {
    e.preventDefault()
    setText('')          // Clear input immediately
    addTodoMutation.mutate(text)  // Trigger optimistic update
  }}
>
  <input
    type="text"
    onChange={(event) => setText(event.target.value)}
    value={text}
  />
  <button disabled={addTodoMutation.isPending}>Create</button>
</form>
```

**What's happening:** The form clears immediately on submit (`setText('')`), giving instant feedback that the action was received. The button disables during pending state to prevent double-submission.

**Why clear immediately:** This creates the illusion of instant success - users can immediately start typing their next todo while the previous one processes in the background.

### 4. Multi-State Feedback System

```tsx
{todoQuery.isSuccess && (
  <>
    <div>
      Updated At: {new Date(todoQuery.data.ts).toLocaleTimeString()}
    </div>
    {/* todo list */}
    {todoQuery.isFetching && <div>Updating in background...</div>}
  </>
)}
```

**What's happening:** Multiple feedback layers operate simultaneously:
- **Data freshness**: Timestamp shows when data was last updated
- **Background activity**: Indicator when refetching occurs
- **Mutation state**: Visual feedback for pending/error states

**Why layer feedback:** Users need different types of information - immediate action feedback, system state awareness, and data currency indicators.

### 5. Error Recovery Pattern

```tsx
{addTodoMutation.isError && (
  <li style={{ color: 'red' }}>
    {addTodoMutation.variables}
    <button
      onClick={() =>
        addTodoMutation.mutate(addTodoMutation.variables)
      }
    >
      Retry
    </button>
  </li>
)}
```

**What's happening:** Failed items remain visible with clear error indication and one-click retry functionality. The same variables are reused for the retry attempt.

**Why preserve failed state:** Users need to see what failed and have an easy path to recovery. Hiding failed attempts creates confusion and forces users to remember and re-enter data.

## Mental Model: The Optimistic UI State Machine

### Three-Layer Reality

Think of optimistic updates as managing three layers of reality:

```
Layer 1: User Intent     [What user wants to happen]
         ↓
Layer 2: Optimistic UI   [What we show immediately]  
         ↓
Layer 3: Server Truth    [What actually happened]
```

Query coordinates these layers, ensuring the UI eventually converges on server truth while maintaining responsive feedback.

### State Flow Visualization

```
User submits form:
1. Intent: "Add 'Buy milk'"
2. UI: Immediately show "Buy milk" (dimmed)
3. Network: POST request to server
4. Success: Remove dimming, show normal todo
   OR
   Failure: Show red + retry button

Background: Query refetches to reconcile with server
```

### Why Optimistic Updates Work

**Psychology**: Users expect their actions to have immediate visible effects. Delays create doubt ("Did my click register?")

**Performance**: Optimistic updates eliminate the perceived latency of round-trip server requests

**Error Recovery**: When failures happen, context is preserved (user sees what failed and can easily retry)

### The Mutation State Lifecycle

```
Idle → Pending → Success → Idle
  ↓              ↑
  └─→ Error ────┘
      (with retry)
```

Each state has distinct UI representation:
- **Idle**: Normal form
- **Pending**: Disabled submit, optimistic content shown
- **Success**: Brief flash, then normal state
- **Error**: Clear indication, retry option, preserved context

### Advanced Patterns

**Multiple Concurrent Mutations**: Each mutation tracks independently - users can submit multiple todos and each shows its own state

**Optimistic Reordering**: New items can be shown at the top of the list optimistically, then reordered when server confirms

**Conditional Optimism**: Complex mutations might only show optimistic updates for likely-to-succeed cases

### Further Exploration

Experiment with these scenarios to understand optimistic behavior:

1. **Network Simulation**: Use DevTools to simulate slow/failing networks
2. **Rapid Submissions**: Try submitting multiple todos quickly
3. **Error Recovery**: Trigger failures and test the retry flow
4. **Background Sync**: Watch how `invalidateQueries` refetches after mutations

**Advanced Challenge**: How would you implement **optimistic deletion** of todos? Consider:
- Immediate removal from UI
- Undo functionality during network request
- Recovery if deletion fails
- Handling of dependent data

**Real-World Application**: This pattern scales to complex scenarios like:
- Social media posts with likes/comments
- E-commerce cart updates
- Collaborative document editing
- Real-time messaging

The optimistic update pattern transforms every user interaction from a request-response cycle into an immediate, confidence-building experience. Understanding this pattern is crucial for building modern, responsive web applications that feel native and fluid.