# Navigation Blocking: Protecting User Data and Creating Smooth UX

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/navigation-blocking)**

## The Core Concept: Why This Example Exists

**The Problem:** In modern web applications, users frequently work with forms, editors, and other stateful interfaces. Without proper navigation guards, users can accidentally lose unsaved work by clicking a link, using browser navigation, or even refreshing the page. Traditional solutions often require complex manual coordination between components and routing systems.

**The TanStack Solution:** TanStack Router introduces the `useBlocker` hook - a declarative way to intercept navigation attempts and present users with confirmation dialogs. Think of it like a thoughtful assistant that notices when you're about to leave important work behind and asks "Are you sure you want to leave?"

This example demonstrates two powerful blocking patterns: **conditional blocking** (based on form state) and **targeted blocking** (blocking specific navigation paths). The system handles both programmatic navigation and browser events seamlessly.

---

## Practical Walkthrough: Code Breakdown

### The Foundation: Global Navigation Blocking (`main.tsx:21-35`)

```tsx
const { proceed, reset, status } = useBlocker({
  shouldBlockFn: ({ current, next }) => {
    if (
      current.routeId === '/editor-1' &&
      next.fullPath === '/foo/$id' &&
      next.params.id === '123' &&
      next.search.hello === 'world'
    ) {
      return true
    }
    return false
  },
  enableBeforeUnload: false,
  withResolver: true,
})
```

This demonstrates **surgical blocking** - the ability to block only specific navigation patterns. The `shouldBlockFn` receives detailed information about both the current route and the intended destination:

- **current.routeId**: Where the user currently is
- **next.fullPath**: The route pattern they're navigating to
- **next.params**: Dynamic parameters from the URL
- **next.search**: Query parameters

The blocker only activates when all conditions match, giving you precise control over when to interrupt navigation.

### Conditional Blocking with Form State (`main.tsx:146-150`)

```tsx
const { proceed, reset, next, current, status } = useBlocker({
  shouldBlockFn: () => value !== '',
  enableBeforeUnload: () => value !== '',
  withResolver: true,
})
```

This shows **state-based blocking** - protecting users when they have unsaved work. Key features:

- **shouldBlockFn**: Returns `true` when there's text in the input field
- **enableBeforeUnload**: Also protects against browser refresh/close when there's unsaved data
- **withResolver**: Enables the proceed/reset pattern for user confirmation

### The Blocking UI Pattern (`main.tsx:90-108`)

```tsx
{status === 'blocked' && (
  <div className="mt-2">
    <div>
      Are you sure you want to leave editor 1 for /foo/123?hello=world ?
    </div>
    <button
      className="bg-lime-500 text-white rounded p-1 px-2 mr-2"
      onClick={proceed}
    >
      YES
    </button>
    <button
      className="bg-red-500 text-white rounded p-1 px-2"
      onClick={reset}
    >
      NO
    </button>
  </div>
)}
```

When navigation is blocked, the blocker provides:

- **status**: 'blocked' when waiting for user decision
- **proceed**: Function to allow the navigation to continue
- **reset**: Function to cancel the navigation attempt
- **next/current**: Information about the attempted navigation

### Browser Integration (`main.tsx:148`)

```tsx
enableBeforeUnload: () => value !== '',
```

The `enableBeforeUnload` option extends blocking to browser events:
- Browser refresh (F5 or Cmd+R)
- Closing the tab/window
- Navigating away from the page
- Back/forward buttons

This creates a comprehensive protection system that works across all navigation methods.

### Multiple Blocking Contexts (`main.tsx:211-215`)

```tsx
const routeTree = rootRoute.addChildren([
  indexRoute,
  fooRoute,
  editor1Route.addChildren([editor2Route]),
])
```

The example demonstrates blocking in both:
1. **Root component**: Global blocking rules that apply across the app
2. **Editor components**: Component-specific blocking based on local state

This layered approach allows for both global navigation policies and component-specific protections.

---

## Mental Model: Thinking in Navigation Guards

### The Navigation Lifecycle

Think of navigation blocking like a security checkpoint at an airport. Every navigation attempt goes through this process:

```
User Clicks Link
       ↓
Router Initiates Navigation
       ↓
Blockers Evaluate shouldBlockFn
       ↓
  ┌─ Blocked ──→ Show Confirmation UI ──→ User Chooses
  │                                        ↓
  │                              Proceed or Reset
  │                                        ↓
  └─ Not Blocked ────────────────→ Navigation Continues
```

### Blocking Strategies

**1. State-Based Blocking**
```tsx
shouldBlockFn: () => hasUnsavedChanges
```
Protects based on application state - perfect for forms, editors, and data entry.

**2. Path-Based Blocking**
```tsx
shouldBlockFn: ({ current, next }) => 
  current.pathname === '/sensitive' && next.pathname === '/dangerous'
```
Blocks specific navigation patterns - useful for workflow protection or preventing accidental exits from critical flows.

**3. Conditional Blocking**
```tsx
shouldBlockFn: ({ next }) => 
  next.pathname.startsWith('/external') && !userConfirmedExternal
```
Applies business logic to navigation decisions - great for warning about external links or protected areas.

### The Blocker Lifecycle

Understanding when blockers activate helps debug complex scenarios:

1. **Mount**: Blocker registers with the router
2. **Navigation Attempt**: Router calls `shouldBlockFn`
3. **Block Decision**: If true, navigation pauses and status becomes 'blocked'
4. **User Interaction**: User clicks proceed or reset
5. **Resolution**: Navigation continues or cancels
6. **Unmount**: Blocker unregisters when component unmounts

### Why Declarative Blocking?

Traditional imperative navigation handling:
```tsx
// Imperative - scattered throughout components
window.addEventListener('beforeunload', (e) => {
  if (hasChanges) {
    e.preventDefault()
    return 'You have unsaved changes'
  }
})

<Link onClick={(e) => {
  if (hasChanges && !confirm('Leave?')) {
    e.preventDefault()
  }
}} />
```

TanStack Router's declarative approach:
```tsx
// Declarative - centralized and automatic
useBlocker({
  shouldBlockFn: () => hasChanges,
  enableBeforeUnload: true,
})
```

Benefits:
1. **Centralized Logic**: All blocking rules in one place
2. **Automatic Integration**: Works with all navigation methods
3. **Type Safety**: Router knows about blocked states
4. **Consistent UX**: Same confirmation pattern everywhere

### Further Exploration

Try these experiments to deepen your understanding:

1. **Complex Conditions**: Create a blocker that only activates on weekends or after business hours.

2. **Form Integration**: Build a form that blocks navigation until all required fields are filled.

3. **Workflow Protection**: Create a multi-step wizard that prevents users from skipping required steps.

4. **Data Loss Prevention**: Implement a blocker that detects unsaved changes in multiple form fields and shows a detailed summary of what would be lost.

Navigation blocking transforms from a defensive afterthought into a proactive UX tool that protects users while maintaining the fluid feel of a modern single-page application.