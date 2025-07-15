# Real-Time Data with Auto-Refetching

> **Based on**: [`examples/react/auto-refetching`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/auto-refetching)

## The Core Concept: Why This Example Exists

**The Problem:** Modern applications need to display live, changing data - stock prices, chat messages, collaborative document edits, system monitoring dashboards. Users expect to see updates from other users or systems automatically, without manually refreshing the page. Implementing real-time updates manually requires complex WebSocket management, polling logic, and coordination between user actions and background updates.

**The Solution:** TanStack Query's **auto-refetching** capabilities transform any data source into a live, reactive feed using simple configuration options. The `refetchInterval` feature creates **intelligent polling** that automatically synchronizes data across browser tabs, handles network interruptions gracefully, and coordinates with user mutations seamlessly.

The key insight: **treat data as a living stream rather than static snapshots**. Auto-refetching makes server state feel as reactive as local state, creating applications that naturally stay synchronized with rapidly changing backend data.

## Practical Walkthrough: Code Breakdown

Let's examine the real-time synchronization patterns from `examples/react/auto-refetching/src/pages/index.tsx`:

### 1. Interval-Based Auto-Refetching

```tsx
const [intervalMs, setIntervalMs] = React.useState(1000)

const { status, data, error, isFetching } = useQuery({
  queryKey: ['todos'],
  queryFn: async (): Promise<Array<string>> => {
    const response = await fetch('/api/data')
    return await response.json()
  },
  refetchInterval: intervalMs, // Refetch every intervalMs milliseconds
})
```

**What's happening:** The `refetchInterval` option automatically triggers a background refetch every 1000ms (1 second). The interval is dynamic - users can adjust the polling speed in real-time.

**Why this pattern:** Polling creates predictable, consistent data freshness without requiring WebSocket infrastructure. It's simple to implement, works with any HTTP API, and provides guaranteed maximum data staleness.

### 2. Dynamic Interval Control

```tsx
<label>
  Query Interval speed (ms):{' '}
  <input
    value={intervalMs}
    onChange={(ev) => setIntervalMs(Number(ev.target.value))}
    type="number"
    step="100"
  />
</label>
```

**What's happening:** Users can control the polling frequency, from rapid updates (100ms) to slower, battery-conscious intervals (5000ms+). The query automatically adapts to the new interval.

**Why user control matters:** Different scenarios need different refresh rates. Real-time trading needs rapid updates, while status dashboards can poll less frequently. User control also enables performance tuning and battery optimization.

### 3. Visual Fetching Feedback

```tsx
<span
  style={{
    display: 'inline-block',
    width: 10,
    height: 10,
    background: isFetching ? 'green' : 'transparent',
    transition: !isFetching ? 'all .3s ease' : 'none',
    borderRadius: '100%',
    transform: 'scale(2)',
  }}
/>
```

**What's happening:** A green dot appears whenever `isFetching` is true, providing immediate visual feedback about background network activity.

**Why visual feedback:** Users need to understand when data is live vs stale. Visual indicators build confidence in real-time behavior and help debug connectivity issues.

### 4. Mutations with Auto-Refresh Coordination

```tsx
const addMutation = useMutation({
  mutationFn: (add: string) => fetch(`/api/data?add=${add}`),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['todos'] }),
})

const clearMutation = useMutation({
  mutationFn: () => fetch(`/api/data?clear=1`),
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['todos'] }),
})
```

**What's happening:** Mutations trigger immediate cache invalidation via `invalidateQueries`, forcing a fresh fetch that bypasses the normal polling interval.

**Why immediate invalidation:** User actions should show immediate results. Don't make users wait for the next polling cycle to see their changes - invalidation ensures instant feedback while maintaining background synchronization.

### 5. Form Integration with Real-Time Updates

```tsx
<form
  onSubmit={(event) => {
    event.preventDefault()
    addMutation.mutate(value, {
      onSuccess: () => {
        setValue('') // Clear form immediately
      },
    })
  }}
>
  <input
    placeholder="enter something"
    value={value}
    onChange={(ev) => setValue(ev.target.value)}
  />
</form>
```

**What's happening:** Form submissions trigger mutations that immediately clear the input field, providing instant feedback while the background polling continues to synchronize changes from other users.

**Why clear immediately:** Creates responsive UX where user actions feel instant, while the polling system handles multi-user synchronization in the background.

## Mental Model: Live Data Streams

### The Polling Heartbeat

Think of auto-refetching as creating a **heartbeat** for your data:

```
Time:     0s    1s    2s    3s    4s    5s
Polling:  ↓     ↓     ↓     ↓     ↓     ↓
          Fetch Fetch Fetch Fetch Fetch Fetch

User Action at 2.5s:
          ↓     ↓   ↓ ↓     ↓     ↓     ↓
          Fetch Fetch M F   Fetch Fetch Fetch
                     ↑ ↑
                     Mutation + Immediate Fetch
```

The regular heartbeat ensures consistent data freshness, while user actions trigger immediate updates.

### Multi-Tab Synchronization

Auto-refetching creates **automatic cross-tab synchronization**:

```
Tab A: User adds item → Mutation → Cache invalidation
Tab B: Background polling (1s later) → Sees new item

Result: All tabs stay synchronized automatically
```

This eliminates the need for complex cross-tab communication or WebSocket management.

### Network Resilience

```
Network States:
Online:  ✓ Polling active, mutations work
Offline: ✗ Polling paused, mutations queued  
Online:  ✓ Polling resumes, mutations process, data syncs
```

Query automatically handles network interruptions by pausing polls when offline and resuming when connectivity returns.

### Why It's Designed This Way: Simplicity with Power

Traditional real-time approaches require complex infrastructure:
```
WebSockets + Event Management + Connection Handling + Fallbacks
```

Auto-refetching provides real-time behavior with simple HTTP:
```
Periodic HTTP Requests + Smart Caching + Automatic Error Handling
```

This approach works with any existing REST API without backend changes.

### Advanced Auto-Refetching Patterns

**Focus-Based Refetching**: Only poll when the user is actively viewing the app:
```tsx
const { data } = useQuery({
  queryKey: ['live-data'],
  queryFn: fetchData,
  refetchInterval: isWindowFocused ? 1000 : false, // Stop when not focused
})
```

**Conditional Polling**: Only poll when certain conditions are met:
```tsx
const { data } = useQuery({
  queryKey: ['status'],
  queryFn: fetchStatus,
  refetchInterval: (data) => {
    return data?.status === 'processing' ? 500 : false // Only poll while processing
  },
})
```

**Exponential Backoff**: Slow down polling when errors occur:
```tsx
const { data } = useQuery({
  queryKey: ['data'],
  queryFn: fetchData,
  refetchInterval: (data, query) => {
    return query.state.error ? Math.min(30000, 1000 * 2 ** query.state.errorUpdateCount) : 1000
  },
})
```

**Visibility API Integration**: Pause polling when tab is hidden:
```tsx
React.useEffect(() => {
  const handleVisibilityChange = () => {
    setIsVisible(!document.hidden)
  }
  document.addEventListener('visibilitychange', handleVisibilityChange)
  return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
}, [])

const { data } = useQuery({
  queryKey: ['live-data'],
  queryFn: fetchData,
  refetchInterval: isVisible ? 1000 : false,
})
```

### Performance Considerations

**Battery Impact**: Frequent polling drains mobile batteries. Consider:
- Longer intervals for mobile devices
- Pause polling when app is backgrounded
- Use WebSockets for high-frequency updates

**Network Usage**: Polling generates consistent traffic. Optimize by:
- Implementing server-side change detection (ETags, Last-Modified)
- Using WebSockets for bandwidth-sensitive applications
- Adjusting intervals based on actual change frequency

**Server Load**: Many clients polling can overwhelm servers. Consider:
- Rate limiting on the server side
- Implementing jitter to spread requests
- Using WebSockets or Server-Sent Events for high-scale scenarios

### Further Exploration

Experiment with real-time patterns:

1. **Multi-Tab Testing**: Open multiple tabs and see changes propagate
2. **Network Simulation**: Use DevTools to simulate offline/online transitions
3. **Performance Monitoring**: Watch network requests and battery usage
4. **Interval Optimization**: Find the right balance between freshness and performance

**Advanced Challenges**:

1. **Collaborative Editing**: How would you implement real-time collaborative text editing with conflict resolution?

2. **Live Dashboards**: Build a monitoring dashboard with multiple data sources, each with different refresh requirements.

3. **Chat Applications**: Combine auto-refetching with optimistic updates for a responsive chat experience.

4. **Gaming Leaderboards**: Implement real-time leaderboards that update smoothly without jarring re-sorts.

**Real-World Applications**:
- **Financial Trading**: Live stock prices, order books, portfolio values
- **Monitoring Dashboards**: System metrics, error rates, user activity
- **Collaborative Tools**: Document editing, design collaboration, project management
- **Social Media**: Live feeds, notification counts, activity streams
- **IoT Dashboards**: Sensor data, device status, environmental monitoring

Auto-refetching transforms static web applications into dynamic, responsive interfaces that feel native and alive. Understanding these patterns enables building applications that naturally stay synchronized with changing data while maintaining excellent user experience and performance characteristics.