# View Transitions: Smooth Navigation with the Web Platform

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/view-transitions)**

## Part 1: The Core Concept

**The Problem:** Traditional web navigation feels jarring and disconnected. When users click a link, the old page disappears instantly and the new page appears immediately, creating a disjointed experience that breaks the illusion of a cohesive application. This abrupt switching lacks the smooth, polished feel users expect from modern applications, especially compared to native mobile apps that excel at seamless transitions.

**The TanStack Solution:** TanStack Router integrates seamlessly with the modern browser View Transitions API to provide smooth, animated transitions between routes. By adding `viewTransition: true` to your router configuration or individual links, you can transform jarring page switches into elegant, animated transitions that maintain visual continuity and create a more polished user experience.

Think of it like turning a flip book (traditional navigation) into a smooth video (view transitions) - the content changes progressively rather than jumping between static states.

---

## Part 2: Practical Walkthrough

### Router-Level View Transitions (`main.tsx:13-40`)

```tsx
const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultStaleTime: 5000,
  scrollRestoration: true,
  /* 
  Using defaultViewTransition would prevent the need to
  manually add `viewTransition: true` to every navigation.

  If defaultViewTransition.types is a function, it will be called with the
  location change info and should return an array of view transition types.
  This is useful if you want to have different view transitions depending on
  the navigation's specifics.

  An example use case is sliding in a direction based on the index of the
  previous and next routes when navigating via browser history back and forth.
  */
  // defaultViewTransition: true
  // OR
  // defaultViewTransition: {
  //   types: ({ fromLocation, toLocation }) => {
  //     let direction = 'none'

  //     if (fromLocation) {
  //       const fromIndex = fromLocation.state.__TSR_index
  //       const toIndex = toLocation.state.__TSR_index

  //       direction = fromIndex > toIndex ? 'right' : 'left'
  //     }

  //     return [`slide-${direction}`]
  //   },
  // },
})
```

This shows the router-level configuration options:

- **Global Default**: `defaultViewTransition: true` enables view transitions for all navigation
- **Custom Logic**: Use a function to apply different transition types based on navigation context
- **Direction Detection**: Compare route indices to determine slide direction for back/forward navigation
- **Selective Application**: Comment shows how to enable different transitions for different routes

### Link-Level View Transitions (`__root.tsx:27, 36`)

```tsx
function RootComponent() {
  return (
    <>
      <div className="p-2 flex gap-2 text-lg border-b">
        <Link
          to="/"
          activeProps={{
            className: 'font-bold',
          }}
          activeOptions={{ exact: true }}
          viewTransition // Enable view transition for this link
        >
          Home
        </Link>{' '}
        <Link
          to="/posts"
          activeProps={{
            className: 'font-bold',
          }}
          viewTransition // Enable view transition for this link
        >
          Posts
        </Link>{' '}
      </div>
      <Outlet />
    </>
  )
}
```

Individual links can opt into view transitions:

- **Per-Link Control**: `viewTransition` prop enables transitions for specific navigation
- **Granular Control**: Choose which navigations should be smooth vs. instant
- **Progressive Enhancement**: Links work normally in browsers without View Transitions API support
- **Consistent Interface**: Same link API whether using global or per-link transitions

### CSS Transition Definitions (Typical CSS file)

```css
/* View Transition API generates these pseudo-elements automatically */

/* Transition the root element */
::view-transition-old(root),
::view-transition-new(root) {
  animation-duration: 0.3s;
  animation-timing-function: ease-in-out;
}

/* Fade transition */
::view-transition-old(root) {
  animation-name: fade-out;
}

::view-transition-new(root) {
  animation-name: fade-in;
}

@keyframes fade-out {
  from { opacity: 1; }
  to { opacity: 0; }
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Slide transitions for directional navigation */
.slide-left::view-transition-old(root) {
  animation-name: slide-out-left;
}

.slide-left::view-transition-new(root) {
  animation-name: slide-in-left;
}

/* More complex transitions can target specific elements */
::view-transition-old(hero),
::view-transition-new(hero) {
  height: 100%;
  right: 0;
  left: auto;
  transform-origin: right center;
}
```

CSS defines the visual behavior of transitions:

- **Automatic Pseudo-elements**: Browser generates `::view-transition-old` and `::view-transition-new`
- **Customizable Animations**: Define any CSS animation for transition effects
- **Element-Specific**: Target specific elements with custom transition names
- **Fallback Support**: Gracefully degrades in browsers without support

### File-Based Route Structure

The example uses file-based routing which automatically enables view transitions:

```
src/routes/
├── __root.tsx     # Root layout with navigation
├── index.tsx      # Home page
└── posts/
    ├── index.tsx  # Posts listing  
    └── $postId.tsx # Individual post
```

File-based routing with view transitions:

- **Automatic Route Generation**: File structure defines routes automatically
- **Consistent Transitions**: All file-based routes can use the same transition configuration
- **Shared Layouts**: Root layout transitions smoothly while nested content changes
- **Type Safety**: Generated route tree maintains full TypeScript support

---

## Part 3: Mental Models & Deep Dives

### The Magic Movie Metaphor

Traditional web navigation is like a slide projector - click, instant change, click, instant change. View transitions are like movie frames - each navigation is a smooth sequence that bridges the gap between states.

```
Traditional Navigation:
[Page A] → *instant* → [Page B]
  ↑                      ↑
 Click                 Appears

View Transition Navigation:  
[Page A] → [Blend Frame 1] → [Blend Frame 2] → [Page B]
  ↑         ↑                 ↑                ↑
 Click    Fade Out         Fade In         Complete
```

The browser automatically generates the in-between frames, creating a cinematic experience.

### Browser Support and Progressive Enhancement

View Transitions follow a progressive enhancement model:

```tsx
// This code works everywhere
<Link to="/posts" viewTransition>
  Posts
</Link>

// Browsers with View Transitions API: Smooth animation
// Browsers without: Normal instant navigation
// Result: Everyone gets working navigation, some get enhanced experience
```

The mental model:
- **Base Experience**: Normal navigation for all browsers
- **Enhanced Experience**: Smooth transitions for supported browsers
- **No JavaScript Required**: View Transitions work at the browser level
- **Future-Proof**: Code remains the same as browser support improves

### The Snapshot and Animate Pattern

Understanding how View Transitions work internally:

```
1. Snapshot Phase:
   - Browser captures screenshot of current page (old)
   - Navigation begins, new page renders
   - Browser captures screenshot of new page (new)

2. Animation Phase:
   - Browser creates temporary overlay
   - Old screenshot fades out
   - New screenshot fades in
   - Overlay removed, real new page visible
```

This happens automatically, but understanding it helps with:
- **Performance Optimization**: Keep transition duration reasonable
- **Visual Debugging**: Understanding what users see during transitions
- **Custom Animations**: Crafting transitions that work with the snapshot system

### Transition Types and Context

Advanced transition patterns based on navigation context:

```tsx
const router = createRouter({
  defaultViewTransition: {
    types: ({ fromLocation, toLocation }) => {
      // No transition for initial load
      if (!fromLocation) return []
      
      // Different transitions based on route relationship
      if (isParentChildNavigation(fromLocation, toLocation)) {
        return ['drill-down']
      }
      
      if (isSiblingNavigation(fromLocation, toLocation)) {
        return ['slide-horizontal']
      }
      
      // Different transitions based on user action
      if (toLocation.state.isBackNavigation) {
        return ['slide-back']
      }
      
      return ['fade']
    }
  }
})
```

This enables sophisticated transition logic:
- **Contextual Animations**: Different transitions for different types of navigation
- **User Intent Recognition**: Distinguish between back/forward vs. fresh navigation
- **Hierarchical Awareness**: Navigate "into" and "out of" sections differently
- **Multiple Transition Types**: Combine multiple animation classes for complex effects

### Performance Considerations

View transitions balance smooth UX with performance:

```
Good for View Transitions:
✓ Text content changes
✓ Layout rearrangements  
✓ Color/theme changes
✓ Adding/removing elements

Challenging for View Transitions:
⚠ Large images changing
⚠ Complex animations during transition
⚠ Heavy JavaScript during transition
⚠ Very different page layouts
```

Mental model: **View transitions work best when the core structure stays similar and content changes.**

### Accessibility and View Transitions

View transitions respect user accessibility preferences:

```css
/* Respect user's motion preferences */
@media (prefers-reduced-motion: reduce) {
  ::view-transition-old(root),
  ::view-transition-new(root) {
    animation-duration: 0.1s;
    animation-timing-function: ease;
  }
}
```

Key accessibility considerations:
- **Motion Sensitivity**: Provide reduced motion alternatives
- **Focus Management**: Ensure focus moves appropriately during transitions
- **Screen Readers**: Transitions don't interfere with assistive technology
- **Keyboard Navigation**: Transitions work with keyboard-only navigation

### Debugging View Transitions

Chrome DevTools provides debugging support:

```
1. Open DevTools → Animations panel
2. Enable "Capture screenshots" 
3. Navigate with view transitions
4. See frame-by-frame breakdown
5. Adjust timing and easing
```

Common debugging scenarios:
- **Flash of Unstyled Content**: Ensure new page styles load before transition
- **Jarring Motion**: Adjust easing curves for smoother feel
- **Performance Issues**: Monitor transition duration vs. navigation speed
- **Browser Compatibility**: Test graceful degradation

### Further Exploration

Experiment with these advanced patterns:

1. **Shared Element Transitions**: Use `view-transition-name` CSS property to transition specific elements smoothly between pages.

2. **Loading State Transitions**: Combine view transitions with loading states for sophisticated loading experiences.

3. **Theme Switching**: Use view transitions for smooth dark/light mode switching.

4. **Route-Specific Animations**: Create different transition styles for different types of routes (modals, full pages, sidebars).

5. **Gesture-Based Transitions**: Integrate view transitions with touch gestures for mobile-native feel.

6. **Performance Monitoring**: Track transition performance and user satisfaction metrics.

The power of view transitions lies in making web applications feel more like native applications - smooth, polished, and delightful to use. They transform the fundamental experience of navigation from a series of abrupt jumps into a fluid, continuous journey through your application.