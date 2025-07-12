# Framer Motion with Router: Smooth Navigation Animations

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/with-framer-motion)**

## The Core Concept: Why This Example Exists

**The Problem:** Modern web applications need smooth, delightful transitions between pages to feel native and polished. However, traditional routing systems make it difficult to animate page transitions because routes are treated as discrete states rather than smooth transitions. Users expect the fluid animations they see in mobile apps, but web routing has historically been jarring and instantaneous.

**The TanStack Solution:** TanStack Router's architecture enables sophisticated page transition animations by giving you precise control over when components mount, unmount, and update during navigation. Unlike traditional routers that abruptly swap components, TanStack Router can coordinate with animation libraries like Framer Motion to create seamless transitions.

This example demonstrates how to integrate Framer Motion's `AnimatePresence` with TanStack Router to create smooth page transitions, nested route animations, and context-aware animation patterns. You'll learn to handle exit animations, prevent layout thrashing, and create professional-grade navigation experiences.

---

## Practical Walkthrough: Code Breakdown

### Animation Configuration (`main.tsx:48-68`)

```tsx
export const mainTransitionProps = {
  initial: { y: -20, opacity: 0, position: 'absolute' },
  animate: { y: 0, opacity: 1, damping: 5 },
  exit: { y: 60, opacity: 0 },
  transition: {
    type: 'spring',
    stiffness: 150,
    damping: 10,
  },
} as const

export const postTransitionProps = {
  initial: { y: -20, opacity: 0 },
  animate: { y: 0, opacity: 1, damping: 5 },
  exit: { y: 60, opacity: 0 },
  transition: {
    type: 'spring',
    stiffness: 150,
    damping: 10,
  },
} as const
```

These animation configurations define the motion characteristics for different route levels:

**Main Transitions**: Used for top-level page changes
- **initial**: Component enters from above with opacity fade
- **animate**: Settles into final position with smooth spring
- **exit**: Leaves downward with fade out
- **position: 'absolute'**: Prevents layout shift during transitions

**Post Transitions**: Simpler animations for nested route changes
- No absolute positioning to avoid conflicts with parent layouts
- Subtle vertical movement for smooth content swapping

### Root Route Animation Setup (`main.tsx:70-107`)

```tsx
const rootRoute = createRootRoute({
  component: () => {
    const matches = useMatches()
    const match = useMatch({ strict: false })
    const nextMatchIndex = matches.findIndex((d) => d.id === match.id) + 1
    const nextMatch = matches[nextMatchIndex]

    return (
      <>
        {/* Navigation */}
        <AnimatePresence mode="wait">
          <Outlet key={nextMatch.id} />
        </AnimatePresence>
      </>
    )
  },
})
```

This sophisticated setup enables route-level animations:

**Route Match Detection**: 
- `useMatches()`: Gets all currently active routes
- `useMatch()`: Gets the current route context
- `nextMatch.id`: Identifies which child route is active

**AnimatePresence Configuration**:
- **`mode="wait"`**: Ensures exit animation completes before enter animation starts
- **`key={nextMatch.id}`**: Tells Framer Motion when to trigger transitions
- Each route change gets a unique key, triggering animation cycles

### Page-Level Animation Components (`main.tsx:112-119`)

```tsx
const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: () => {
    return (
      <motion.div className="p-2" {...mainTransitionProps}>
        <h3>Welcome Home!</h3>
      </motion.div>
    )
  },
})
```

Every page component wraps its content in `motion.div` with the transition props. This creates:
- **Consistent Enter/Exit**: Same animation timing across all pages
- **Performance Optimization**: Framer Motion handles GPU acceleration
- **Layout Preservation**: Absolute positioning prevents content jumping

### Nested Route Animations (`main.tsx:125-156`)

```tsx
const postsLayoutRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'posts',
  component: () => {
    const posts = postsLayoutRoute.useLoaderData()
    return (
      <motion.div className="p-2 flex gap-2" {...mainTransitionProps}>
        <ul className="list-disc pl-4">
          {/* Post links */}
        </ul>
        <hr />
        <AnimatePresence>
          <Outlet />
        </AnimatePresence>
      </motion.div>
    )
  },
})
```

This demonstrates **multi-level animation coordination**:

1. **Parent Route Animation**: The posts layout animates in as a complete unit
2. **Child Route Animation**: The `<Outlet />` content animates independently
3. **No Mode Restriction**: Nested `AnimatePresence` doesn't use `mode="wait"` for faster transitions

### Individual Post Animations (`main.tsx:171-180`)

```tsx
const postRoute = createRoute({
  getParentRoute: () => postsLayoutRoute,
  path: '$postId',
  component: () => {
    const post = postRoute.useLoaderData()
    return (
      <motion.div className="space-y-2" {...postTransitionProps}>
        <h4 className="text-xl font-bold underline">{post.title}</h4>
        <div className="text-sm">{post.body}</div>
      </motion.div>
    )
  },
})
```

Child route animations use different transition props:
- **No Absolute Positioning**: Fits within parent layout
- **Subtle Motion**: Less dramatic than page-level transitions
- **Content-Aware**: Animation speed matches content complexity

---

## Mental Model: Coordinating Router and Animation States

### The Animation Lifecycle Pipeline

Think of navigation animations as a carefully choreographed dance between three systems:

```
User Navigation Intent
        ↓
Router State Change
        ↓
Framer Motion Animation
        ↓
DOM Update Complete
```

**Traditional Routing**: Instant DOM swapping
```tsx
// Jarring experience
<Route path="/page1" component={Page1} />
<Route path="/page2" component={Page2} />
// User clicks → Component instantly changes
```

**Animated Routing**: Orchestrated transitions
```tsx
// Smooth experience
<AnimatePresence mode="wait">
  <Outlet key={routeId} />
</AnimatePresence>
// User clicks → Exit animation → Route change → Enter animation
```

### Key Management Strategy

The most crucial concept is using the correct `key` for `AnimatePresence`:

**Wrong Approach**: Using URL as key
```tsx
// Problem: Query params or hash changes trigger unnecessary animations
<Outlet key={location.pathname} />
```

**Correct Approach**: Using route match ID
```tsx
// Solution: Only animate on actual route changes
<Outlet key={nextMatch.id} />
```

This ensures animations only trigger for meaningful navigation changes, not minor URL updates.

### Animation Performance Patterns

**Layout Thrashing Prevention**:
```tsx
// Bad: Causes layout recalculation during animation
initial: { height: 0 }
animate: { height: 'auto' }

// Good: Use transforms for better performance
initial: { y: -20, opacity: 0 }
animate: { y: 0, opacity: 1 }
```

**GPU Acceleration**:
```tsx
// Automatically GPU-accelerated properties
const goodProps = {
  initial: { x: -100, opacity: 0, scale: 0.9 },
  animate: { x: 0, opacity: 1, scale: 1 },
}

// Forces CPU rendering
const badProps = {
  initial: { left: -100, top: 0 },
  animate: { left: 0, top: 0 },
}
```

### Advanced Animation Patterns

**Data-Dependent Animations**:
```tsx
const postRoute = createRoute({
  loader: ({ params }) => fetchPost(params.postId),
  component: () => {
    const post = postRoute.useLoaderData()
    
    // Animation varies based on content
    const animationProps = post.featured 
      ? { ...mainTransitionProps, initial: { scale: 0.8 } }
      : postTransitionProps
    
    return <motion.div {...animationProps}>{post.title}</motion.div>
  },
})
```

**Loading State Animations**:
```tsx
const routeWithLoader = createRoute({
  loader: async ({ params }) => {
    // Show loading animation while data loads
    const data = await fetchData(params.id)
    return data
  },
  pendingComponent: () => (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      Loading...
    </motion.div>
  ),
  component: DataComponent,
})
```

**Error State Animations**:
```tsx
const errorRoute = createRoute({
  errorComponent: ({ error }) => (
    <motion.div
      initial={{ x: -300, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ type: 'spring', stiffness: 100 }}
    >
      <h2>Oops! {error.message}</h2>
    </motion.div>
  ),
})
```

### Browser Performance Considerations

**Reduced Motion Preference**:
```tsx
const useReducedMotion = () => {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const Component = () => {
  const shouldReduceMotion = useReducedMotion()
  
  const transitionProps = shouldReduceMotion
    ? { initial: { opacity: 0 }, animate: { opacity: 1 } }
    : mainTransitionProps
  
  return <motion.div {...transitionProps}>Content</motion.div>
}
```

**Memory Management**:
```tsx
// Clean up animations on unmount
useEffect(() => {
  return () => {
    // Framer Motion handles cleanup automatically
    // But you can add custom cleanup here
  }
}, [])
```

### Further Exploration

Try these experiments to master router animations:

1. **Custom Animation Sequences**: Create different animations for forward vs. backward navigation using browser history.

2. **Shared Element Transitions**: Animate elements that persist across routes (like headers or sidebars).

3. **Touch Gestures**: Integrate pan gestures for mobile-style navigation animations.

4. **Loading Indicators**: Create custom loading animations that coordinate with route data loading.

5. **A/B Testing**: Create multiple animation variants and test user preferences.

The combination of TanStack Router's predictable state management with Framer Motion's animation primitives creates opportunities for incredibly sophisticated navigation experiences that rival native applications.