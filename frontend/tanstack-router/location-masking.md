# Location Masking: URL Rewriting for Better UX

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/location-masking)**

## Part 1: The Core Concept

**The Problem:** Sometimes the URL structure that works best for your application's internal routing doesn't provide the best user experience. Modal dialogs are a perfect example: you want the modal to have its own URL for deep linking and back-button behavior, but you don't want the URL to change visually when opening a modal. Users expect modals to feel like overlays, not new pages, yet you need the routing benefits of separate routes.

**The TanStack Solution:** TanStack Router's location masking feature allows you to create routes that internally use one URL structure while displaying a different, more user-friendly URL in the browser address bar. Using `createRouteMask`, you can map complex routes to simpler URLs, creating seamless user experiences for modals, overlays, and other UI patterns that benefit from routing but shouldn't expose their implementation details.

Think of it like a theater stage with a scrim - the audience sees a beautiful, simplified view while complex machinery operates behind the scenes to create the experience.

---

## Part 2: Practical Walkthrough

### Route Mask Definition (`main.tsx:310-315`)

```tsx
const photoModalToPhotoMask = createRouteMask({
  routeTree,
  from: '/photos/$photoId/modal',    // Actual route (complex)
  to: '/photos/$photoId',            // Displayed URL (simple)
  params: true,                      // Forward route parameters
})
```

This creates the core masking relationship:

- **`from`**: The internal route that actually handles the request
- **`to`**: The URL that users see in their browser
- **`params: true`**: Route parameters (like `$photoId`) are forwarded between routes
- **Bidirectional**: Works for both navigation to the route and URL generation

### Router Integration (`main.tsx:317-323`)

```tsx
const router = createRouter({
  routeTree,
  routeMasks: [photoModalToPhotoMask], // Register the mask
  defaultPreload: 'intent',
  scrollRestoration: true,
})
```

Masks are registered at the router level:

- **`routeMasks` Array**: Multiple masks can be registered for different patterns
- **Global Effect**: Masks affect all URL generation and navigation throughout the app
- **Transparent Operation**: The rest of your routing code doesn't need to change

### Modal Route Implementation (`main.tsx:211-218`)

```tsx
const photoModalRoute = createRoute({
  getParentRoute: () => photosLayoutRoute,
  path: '$photoId/modal',              // Internal path includes '/modal'
  loader: async ({ params: { photoId } }) => fetchPhoto(photoId),
  errorComponent: PhotoModalErrorComponent,
  component: PhotoModalComponent,
})
```

The actual route is defined normally:

- **Standard Route Definition**: No special syntax needed for masked routes
- **Full Route Features**: Loaders, error handling, and all normal route features work
- **Path Structure**: The internal path can be as complex as needed
- **Component Rendering**: Components render based on the actual route, not the masked URL

### Navigation to Masked Routes (`main.tsx:154-167`)

```tsx
<Link
  to={photoModalRoute.to}           // Links to actual route
  params={{
    photoId: photo.id,
  }}
  // If you want to use a mask, you can do so like this, but
  // it's generally safer to set up a route mask instead.
  // mask={{
  //   to: photoRoute.to,
  //   params: {
  //     photoId: photo.id,
  //   },
  // }}
  className="whitespace-nowrap border rounded-lg shadow-sm flex items-center hover:shadow-lg text-blue-600 hover:scale-[1.1] overflow-hidden transition-all"
>
```

Navigation works with standard Link components:

- **Standard Navigation**: Use normal `to` props pointing to the actual route
- **Parameter Passing**: Route parameters work normally
- **Automatic Masking**: The router automatically applies the mask during navigation
- **Alternative Syntax**: Per-link masking is possible but global masks are preferred

### Modal Component with Navigation (`main.tsx:265-291`)

```tsx
function PhotoModalComponent() {
  const navigate = useNavigate()
  const photo = photoModalRoute.useLoaderData()

  return (
    <Modal
      onOpenChange={(open) => {
        if (!open) {
          navigate({
            to: photosLayoutRoute.to,    // Navigate back to photos list
          })
        }
      }}
    >
      <div className="bg-gray-100 dark:bg-gray-800 p-2 rounded-lg">
        <Link
          to="."
          target="_blank"
          className="text-blue-600 hover:opacity-75 underline"
        >
          Open in new tab (to test de-masking)
        </Link>
        <Photo photo={photo} />
      </div>
    </Modal>
  )
}
```

Modal components can navigate normally:

- **Close Navigation**: When modal closes, navigate to the parent route
- **New Tab Behavior**: Links can open in new tabs, revealing the true URL
- **Standard Hooks**: All normal navigation hooks work within masked routes
- **De-masking**: Opening in new tabs shows the actual URL structure

### Parallel Route Structure (`main.tsx:180-186, 304-308`)

```tsx
// Regular photo route (for direct access)
const photoRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: 'photos/$photoId',
  loader: async ({ params: { photoId } }) => fetchPhoto(photoId),
  errorComponent: PhotoErrorComponent,
  component: PhotoComponent,
})

// Modal photo route (for overlay access)
const photoModalRoute = createRoute({
  getParentRoute: () => photosLayoutRoute,
  path: '$photoId/modal',
  loader: async ({ params: { photoId } }) => fetchPhoto(photoId),
  component: PhotoModalComponent,
})

const routeTree = rootRoute.addChildren([
  photoRoute,                                    // /photos/$photoId
  photosLayoutRoute.addChildren([photoModalRoute]), // /photos/$photoId/modal
  indexRoute,
])
```

The same content can be accessed through different routes:

- **Dual Access Patterns**: Same photo can be viewed as a full page or modal
- **Shared Logic**: Both routes can use the same loader and components
- **Different Contexts**: Modal route renders within photos layout, direct route renders standalone
- **URL Consistency**: Masking makes both access patterns use the same visible URL

---

## Part 3: Mental Models & Deep Dives

### The Theater Stage Metaphor

Location masking is like a theater stage with sophisticated lighting and sets:

```
What the Audience Sees (Masked URL):
🎭 /photos/123
   [Simple, clean scene]

What's Actually Happening Backstage (Real Route):
🎭 /photos/123/modal
   [Complex machinery: modal state, overlay rendering, parent route context]
```

The audience enjoys a seamless experience while complex technical details remain hidden.

### URL Space Mapping

Understanding how masks map URL space:

```tsx
// Without Masking (Exposed Complexity)
/photos/123          → Full page photo
/photos/123/modal    → Modal photo (ugly URL)
/photos/123/edit     → Edit modal (confusing)
/photos/123/share    → Share modal (implementation detail)

// With Masking (Clean Interface)  
/photos/123          → Could be full page OR modal (context-dependent)
/photos/123          → Same URL for all photo interactions
/photos/123          → User doesn't see modal implementation details
```

Masking creates a clean, consistent URL space that hides implementation complexity.

### Context-Dependent Rendering

The same URL can render differently based on navigation context:

```tsx
// Navigation from photos list → Modal overlay
<Link to="/photos/123">Photo</Link>  
// URL: /photos/123
// Renders: Modal over photos list

// Direct URL entry → Full page
window.location.href = "/photos/123"
// URL: /photos/123  
// Renders: Full page photo

// Navigation from external link → Full page
<a href="/photos/123">Photo</a>
// URL: /photos/123
// Renders: Full page photo
```

The router chooses the appropriate route based on navigation context while maintaining URL consistency.

### Masking vs. Redirects

Understanding when to use masking vs. redirects:

```tsx
// Redirect (Changes URL)
/old-photos/123 → redirect → /photos/123
User sees URL change ❌

// Mask (Hides URL)  
/photos/123/modal → mask → /photos/123
User sees clean URL ✓ but route stays internal

// When to use each:
Redirects: Legacy URLs, moved content, SEO
Masks: UI states, modals, implementation details
```

Masking preserves URLs while redirects change them - choose based on user expectations.

### Deep Linking and Sharing

Masked URLs maintain deep linking capabilities:

```tsx
// User shares: /photos/123
// Link works regardless of how it's accessed:

Scenario 1: Shared from modal
→ Recipient opens modal or full page (context-dependent)

Scenario 2: Shared from direct page  
→ Recipient sees full page

Scenario 3: Shared link opened in new tab
→ De-masks to show actual implementation (/photos/123/modal)
```

This ensures sharing works intuitively while preserving technical functionality.

### Back Button Behavior

Masking affects browser history in subtle ways:

```tsx
Navigation Sequence:
1. /photos (Photos list)
2. Click photo → /photos/123 (Masked: /photos/123/modal)
3. Back button → /photos (Returns to list)

// The modal route is in history but appears as clean URL
// Back navigation works as users expect
```

Browser history maintains the user's mental model while preserving routing functionality.

### Performance Considerations

Masking has minimal performance impact:

```tsx
// No Additional Renders: Masking only affects URL display
// No Route Duplication: Each route renders once
// No JavaScript Overhead: Masking happens at router level
// No Network Impact: Same data loading patterns

// However, consider:
// - Multiple routes for same content might duplicate loaders
// - Choose appropriate caching strategies
// - Consider code splitting for different route contexts
```

### Error Handling in Masked Routes

Error handling works normally but consider user experience:

```tsx
// Error in masked route: /photos/123/modal
// User sees error at URL: /photos/123
// Consider showing error context:

function PhotoModalErrorComponent({ error }) {
  return (
    <Modal>
      <div>
        Error loading photo: {error.message}
        <Link to="/photos">Return to Photos</Link>
      </div>
    </Modal>
  )
}
```

Error messages should make sense in the context of the displayed URL.

### SEO and Crawling Implications

Search engines see the actual routes, not masked URLs:

```tsx
// Search engines discover:
/photos/123/modal (actual route)
/photos/123      (regular route)

// Both might index the same content
// Consider:
// - Canonical URLs pointing to the main route
// - robots.txt rules for modal routes  
// - Structured data consistency
```

Plan your SEO strategy considering both visible and actual URL structures.

### Further Exploration

Experiment with these advanced patterns:

1. **Conditional Masking**: Apply different masks based on user authentication, device type, or feature flags.

2. **Nested Masking**: Create multiple layers of URL masking for complex application hierarchies.

3. **Dynamic Masks**: Generate masks programmatically based on application state or user preferences.

4. **A/B Testing**: Use masks to test different URL structures without changing internal routing.

5. **Multi-Tenant Applications**: Use masking to provide tenant-specific URL structures over shared routing.

6. **Progressive Enhancement**: Implement masking as an enhancement that gracefully degrades in unsupported environments.

The power of location masking lies in creating user experiences that prioritize simplicity and intuition while maintaining the full flexibility of complex routing systems. Users interact with clean, predictable URLs while developers benefit from sophisticated routing capabilities that support rich application architectures.