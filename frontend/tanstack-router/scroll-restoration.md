# Scroll Restoration: Preserving User Context Across Navigation

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/scroll-restoration)**

## Part 1: The Core Concept

**The Problem:** When users navigate through web applications, they expect their scroll position to be preserved intelligently. If they scroll down a long list, click on an item, then navigate back, they expect to return to the same scroll position - not back to the top. However, different navigation patterns require different scroll behaviors: sometimes you want to restore position (back navigation), sometimes you want to start fresh (new navigation), and sometimes you need granular control over specific scrollable elements.

**The TanStack Solution:** TanStack Router provides comprehensive scroll restoration that automatically handles the common cases while giving you fine-grained control when needed. The router automatically restores scroll position for back/forward navigation, resets for fresh navigation, and provides `useElementScrollRestoration` for complex scenarios like virtualized content or multiple scrollable areas.

Think of it like a smart bookmark system that remembers not just which page you were on, but exactly where you were looking on that page, creating a seamless browsing experience that feels natural and user-friendly.

---

## Part 2: Practical Walkthrough

### Router-Level Scroll Restoration (`main.tsx:194-198`)

```tsx
const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  scrollRestoration: true, // Enable automatic scroll restoration
})
```

This simple setting enables intelligent scroll behavior:

- **Automatic Back/Forward**: When users navigate back or forward, scroll position is restored
- **Fresh Navigation Reset**: When users click new links, scroll resets to top
- **Browser Integration**: Works with browser back/forward buttons
- **Zero Configuration**: Works out of the box for most common scenarios

### Link-Level Scroll Control (`__root.tsx:30-32`)

```tsx
<Link to="/about" resetScroll={false}>
  About (No Reset)
</Link>
```

Individual links can override default scroll behavior:

- **`resetScroll={false}`**: Maintains current scroll position when navigating
- **Selective Control**: Choose which links should reset scroll vs. maintain position
- **UX Customization**: Useful for tabs, filters, or related content navigation
- **Override Defaults**: Per-link control takes precedence over router settings

### Programmatic Scroll Restoration (`main.tsx:100-119`)

```tsx
function ByElementComponent() {
  // We need a unique ID for manual scroll restoration on a specific element
  // It should be as unique as possible for this element across your app
  const scrollRestorationId = 'myVirtualizedContent'

  // We use that ID to get the scroll entry for this element
  const scrollEntry = useElementScrollRestoration({
    id: scrollRestorationId,
  })

  // Let's use TanStack Virtual to virtualize some content!
  const virtualizerParentRef = React.useRef<HTMLDivElement>(null)
  const virtualizer = useVirtualizer({
    count: 10000,
    getScrollElement: () => virtualizerParentRef.current,
    estimateSize: () => 100,
    // We pass the scrollY from the scroll restoration entry to the virtualizer
    // as the initial offset
    initialOffset: scrollEntry?.scrollY,
  })
```

Manual scroll restoration for complex scenarios:

- **Unique IDs**: Each scrollable element needs a unique identifier across the app
- **`useElementScrollRestoration`**: Hook that manages scroll state for specific elements
- **Virtualization Support**: Works seamlessly with libraries like TanStack Virtual
- **Initial Offset**: Restored scroll position can be used as initial state for complex components

### Scroll Target Marking (`main.tsx:152-158`)

```tsx
<div
  ref={virtualizerParentRef}
  // We pass the scroll restoration ID to the element
  // as a custom attribute that will get picked up by the
  // scroll restoration watcher
  data-scroll-restoration-id={scrollRestorationId}
  className="flex-1 border rounded-lg overflow-auto relative"
>
```

Elements can be marked for automatic scroll tracking:

- **`data-scroll-restoration-id`**: Attribute that router watches for scroll events
- **Automatic Tracking**: Router automatically saves scroll position for marked elements
- **Ref Integration**: Works with React refs for component integration
- **Multiple Elements**: Multiple scrollable areas can be tracked independently

### Complex Layout with Multiple Scroll Areas (`main.tsx:122-186`)

```tsx
function ByElementComponent() {
  return (
    <div className="p-2 h-[calc(100vh-41px)] flex flex-col">
      <div>Hello from By-Element!</div>
      <div className="h-full min-h-0 flex gap-4">
        
        {/* First scrollable area - automatic restoration */}
        <div className="border rounded-lg p-2 overflow-auto flex-1 space-y-2">
          {Array.from({ length: 50 }).map((_, i) => (
            <div key={i} className="h-[100px] p-2 rounded-lg bg-gray-200">
              About Item {i + 1}
            </div>
          ))}
        </div>
        
        {/* Multiple independent scrollable areas */}
        <div className="flex-1 overflow-auto flex flex-col gap-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <div key={i} className="flex-1 border rounded-lg p-2 overflow-auto">
              <div className="space-y-2">
                {Array.from({ length: 50 }).map((_, i) => (
                  <div key={i} className="h-[100px] p-2 rounded-lg bg-gray-200">
                    About Item {i + 1}
                  </div>
                ))}
              </div>
            </div>
          ))}
          
          {/* Virtualized content with manual restoration */}
          <div className="flex-1 flex flex-col min-h-0">
            <div className="font-bold">Virtualized</div>
            <div
              ref={virtualizerParentRef}
              data-scroll-restoration-id={scrollRestorationId}
              className="flex-1 border rounded-lg overflow-auto relative"
            >
              {/* Virtualized content */}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
```

This demonstrates handling complex layouts:

- **Mixed Approach**: Some areas use automatic restoration, others use manual control
- **Independent Areas**: Multiple scroll areas tracked separately
- **Layout Aware**: Restoration works with flexbox and complex CSS layouts
- **Performance Optimized**: Only tracks elements that need restoration

### Route Loading and Scroll (`main.tsx:46-48, 71-73, 96-98`)

```tsx
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  loader: () => new Promise((r) => setTimeout(r, 500)), // Simulated loading
  component: IndexComponent,
})
```

Scroll restoration works with route loading:

- **Loading Delays**: Restoration waits for route loading to complete
- **Async Components**: Works with components that load data asynchronously
- **Progressive Rendering**: Scroll position restored after content is rendered
- **Error Handling**: Scroll behavior continues working even if routes error

---

## Part 3: Mental Models & Deep Dives

### The Photo Album Analogy

Think of scroll restoration like browsing a physical photo album:

```
Traditional Web (No Restoration):
📖 [Page 50] → Close book → [Start from Page 1 again] ❌

Smart Restoration:
📖 [Page 50] → Close book → [Bookmark automatically placed] → [Reopen to Page 50] ✓
```

Just like you'd want a bookmark to remember your place in a book, users expect web apps to remember where they were looking.

### The Context Preservation Hierarchy

Scroll restoration operates on multiple levels:

```
1. Global Window Scroll (Automatic)
   ├── Router handles window.scrollY for back/forward
   ├── Resets for fresh navigation
   └── Works with browser navigation

2. Element-Specific Scroll (Semi-Automatic)  
   ├── data-scroll-restoration-id marks elements
   ├── Router tracks these elements automatically
   └── Useful for sidebars, content areas

3. Component-Controlled Scroll (Manual)
   ├── useElementScrollRestoration hook
   ├── Full control over save/restore logic
   └── Required for virtualized content
```

Each level serves different use cases, from simple page scrolling to complex application layouts.

### Navigation Pattern Recognition

The router intelligently recognizes different navigation patterns:

```tsx
// Fresh Navigation (Reset Scroll)
<Link to="/new-page">New Content</Link>
// Result: Scroll to top

// Related Navigation (Maybe Preserve)  
<Link to="/posts/page-2">Next Page</Link>
// Result: Depends on use case

// Back Navigation (Restore Position)
history.back()
// Result: Restore previous position

// Tab-like Navigation (Preserve Position)
<Link to="/posts" resetScroll={false}>Posts Tab</Link>
// Result: Keep current position
```

Understanding these patterns helps you choose the right scroll behavior for each interaction.

### Memory Management for Scroll Positions

The router manages scroll position memory efficiently:

```
Memory Strategy:
├── Limited History: Only store recent positions
├── Route-Based: Key positions by route path + search params
├── Element-Based: Separate storage for each tracked element
└── Cleanup: Remove stale entries when routes unmount
```

This prevents memory bloat while maintaining good user experience.

### Scroll Restoration Timing

Understanding when restoration happens:

```
Navigation Timeline:
1. User clicks link
2. Route starts loading
3. Component begins rendering
4. Content reaches stable layout
5. 🎯 Scroll position restored
6. User sees correct position
```

The timing ensures that:
- Content is ready before scrolling
- Layout shifts don't interfere with restoration
- Users see the intended position, not flashes or jumps

### Integration with Loading States

Scroll restoration coordinates with loading patterns:

```tsx
// Pattern 1: Restore after loading
function Component() {
  const data = useLoaderData() // Route loader
  // Scroll restored after loader completes
  return <div>{data.content}</div>
}

// Pattern 2: Restore during progressive loading
function Component() {
  const { fastData, slowPromise } = useLoaderData()
  // Scroll restored after fastData, before slowPromise
  return (
    <div>
      <div>{fastData.title}</div>
      <Suspense fallback={<Spinner />}>
        <Await promise={slowPromise}>
          {(slowData) => <div>{slowData.content}</div>}
        </Await>
      </Suspense>
    </div>
  )
}
```

This ensures scroll restoration doesn't interfere with loading UX.

### Virtualization and Infinite Scroll

Special considerations for advanced scrolling patterns:

```tsx
// Virtualized Lists
const virtualizer = useVirtualizer({
  count: items.length,
  getScrollElement: () => parentRef.current,
  estimateSize: () => 50,
  initialOffset: scrollEntry?.scrollY, // 🎯 Restore virtual position
})

// Infinite Scroll  
function useInfiniteScroll() {
  const scrollEntry = useElementScrollRestoration({ id: 'infinite-list' })
  
  useEffect(() => {
    if (scrollEntry?.scrollY) {
      // May need to load additional pages to reach restored position
      loadPagesToPosition(scrollEntry.scrollY)
    }
  }, [scrollEntry])
}
```

These patterns require coordination between scroll restoration and the underlying data loading.

### Accessibility and Scroll Restoration

Scroll restoration should work with accessibility features:

```tsx
// Screen Reader Friendly
function Component() {
  const announceRef = useRef()
  
  useLayoutEffect(() => {
    // Announce when scroll position is restored
    if (wasScrollRestored) {
      announceRef.current.textContent = 'Returned to previous position'
    }
  }, [wasScrollRestored])
  
  return (
    <div>
      <div ref={announceRef} aria-live="polite" className="sr-only" />
      {/* Content */}
    </div>
  )
}

// Focus Management
function Component() {
  useEffect(() => {
    // Don't steal focus if scroll was restored
    if (!wasScrollRestored) {
      focusHeading()
    }
  }, [wasScrollRestored])
}
```

Ensuring scroll restoration enhances rather than interferes with accessibility.

### Further Exploration

Experiment with these advanced patterns:

1. **Smooth Scroll Integration**: Combine scroll restoration with CSS `scroll-behavior: smooth` for animated restoration.

2. **Mobile-Specific Patterns**: Handle pull-to-refresh and other mobile scroll behaviors alongside restoration.

3. **Performance Monitoring**: Track scroll restoration performance and success rates in production.

4. **Cross-Tab Restoration**: Explore restoring scroll positions across browser tabs or sessions.

5. **Conditional Restoration**: Implement business logic that determines when restoration should or shouldn't happen.

6. **Integration with Page Transitions**: Coordinate scroll restoration with view transitions for sophisticated UX.

The power of scroll restoration lies in creating applications that feel continuous and context-aware. Users can explore content confidently, knowing they can always return to exactly where they left off, creating a browsing experience that feels natural and respectful of their attention and progress.