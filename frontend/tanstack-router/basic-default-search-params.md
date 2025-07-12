# Default Search Parameters: Intelligent URL Defaults

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/basic-default-search-params)**

## Part 1: The Core Concept

**The Problem:** Search parameters in URLs are often required for meaningful navigation, but having empty URLs with no defaults creates poor user experience. When users visit a route without search parameters, you want to provide sensible defaults while maintaining type safety and predictable behavior. Traditional routing solutions either force you to handle undefined search params everywhere or provide no automatic default handling.

**The TanStack Solution:** TanStack Router's `validateSearch` function with Zod's `.catch()` method provides an elegant solution for default search parameters. This approach automatically applies defaults when search parameters are missing or invalid, while maintaining full type safety and seamless integration with the router's search parameter system.

Think of it like having a smart assistant that fills in missing form fields with sensible defaults - users can override them, but they never encounter a broken or incomplete state.

---

## Part 2: Practical Walkthrough

### Search Validation with Defaults (`main.tsx:159-170`)

```tsx
const postRoute = createRoute({
  getParentRoute: () => postsLayoutRoute,
  path: 'post',
  validateSearch: (
    input: {
      postId: number
      color?: 'white' | 'red' | 'green'
    } & SearchSchemaInput,
  ) =>
    z
      .object({
        postId: z.number().catch(1),
        color: z.enum(['white', 'red', 'green']).catch('white'),
      })
      .parse(input),
  // ... rest of route config
})
```

This is the heart of default search parameters in TanStack Router:

- **Zod Schema Definition**: Defines the expected shape and types of search parameters
- **`.catch()` for Defaults**: When validation fails or values are missing, `.catch()` provides fallback values
- **Type Safety**: TypeScript knows exactly what search parameters are available and their types
- **Automatic Coercion**: The router handles converting URL strings to proper types

### Linking with Search Parameters (`main.tsx:124-132`)

```tsx
<Link
  to={postRoute.to}
  search={{
    postId: post.id,
    color: index % 2 ? 'red' : undefined,
  }}
  className="block py-1 px-2 text-green-300 hover:text-green-200"
  activeProps={{ className: '!text-white font-bold' }}
>
  <div>{post.title.substring(0, 20)}</div>
</Link>
```

Links can provide some search parameters while letting others use defaults:

- **Selective Parameters**: Only specify the search params you want to override
- **Undefined Handling**: When `color` is `undefined`, the default from `.catch('white')` applies
- **Type Safety**: TypeScript ensures you can only pass valid search parameter values

### Using Search Parameters in Components (`main.tsx:187-196`)

```tsx
function PostComponent() {
  const post = postRoute.useLoaderData()
  const { color } = postRoute.useSearch()
  return (
    <div className="space-y-2">
      <h4 className="text-xl font-bold">{post.title}</h4>
      <hr className="opacity-20" />
      <div className={`text-sm text-${color}-300`}>{post.body}</div>
    </div>
  )
}
```

Components can confidently use search parameters knowing defaults are always applied:

- **`useSearch()` Hook**: Retrieves validated search parameters with defaults applied
- **No Undefined Checks**: Since defaults are guaranteed, no need for optional chaining or fallbacks
- **Reactive Updates**: Component re-renders when search parameters change

### Loader Dependencies with Search (`main.tsx:171-175`)

```tsx
const postRoute = createRoute({
  // ...
  loaderDeps: ({ search: { postId } }) => ({
    postId,
  }),
  loader: ({ deps: { postId } }) => fetchPost(postId),
  // ...
})
```

Loaders can depend on search parameters and leverage defaults:

- **`loaderDeps`**: Tells the router which search parameters the loader depends on
- **Automatic Reloading**: When `postId` changes, the loader re-runs automatically
- **Default Values**: Even if no `postId` is in URL, the default value (1) triggers the loader

### Router Configuration (`main.tsx:205-210`)

```tsx
const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultStaleTime: 5000,
  scrollRestoration: true,
})
```

Router configuration supports default search parameters seamlessly:

- **`defaultPreload: 'intent'`**: Preloads data when users hover over links
- **`defaultStaleTime`**: Controls how long data stays fresh in cache
- **`scrollRestoration`**: Maintains scroll position during navigation

---

## Part 3: Mental Models & Deep Dives

### The Graceful Degradation Pattern

Default search parameters follow a graceful degradation pattern similar to CSS:

```tsx
// URL: /posts/post (no search params)
// Applied defaults: { postId: 1, color: 'white' }

// URL: /posts/post?postId=5 (partial search params)
// Applied: { postId: 5, color: 'white' } // color defaults to white

// URL: /posts/post?postId=5&color=red (full search params)
// Applied: { postId: 5, color: 'red' } // no defaults needed
```

Think of it like a form with pre-filled fields:
- Users can navigate to any URL state
- Missing information gets filled in automatically
- Users can override defaults by providing explicit values
- The application always has complete, valid data to work with

### The Validation Pipeline

Understanding how search parameter validation works:

```tsx
1. URL: '/posts/post?postId=abc&color=blue'
2. Router extracts: { postId: 'abc', color: 'blue' }
3. Zod validation attempts:
   - z.number().catch(1) on 'abc' → fails → returns 1
   - z.enum(['white','red','green']).catch('white') on 'blue' → fails → returns 'white'
4. Final result: { postId: 1, color: 'white' }
5. Component receives validated, typed data
```

This pipeline ensures:
- **No Runtime Errors**: Invalid data never reaches your components
- **Predictable Behavior**: Same input always produces same output
- **User-Friendly URLs**: Invalid URLs don't break the application

### Design Philosophy: Fail-Safe Defaults

The design philosophy prioritizes user experience over strict validation:

```tsx
// Traditional approach (error-prone)
function Component() {
  const { postId, color } = useSearch()
  
  // Always need to handle undefined cases
  if (!postId) return <div>Missing post ID</div>
  
  const safeColor = color || 'white'
  // ... rest of component
}

// TanStack Router approach (fail-safe)
function Component() {
  const { postId, color } = useSearch()
  
  // postId and color are ALWAYS defined and valid
  // No defensive coding needed
  return <div className={`text-${color}-300`}>...</div>
}
```

This approach follows the principle that applications should be resilient and user-friendly, not brittle.

### Search Parameter Hierarchies

Default search parameters work well with nested routes:

```tsx
// Parent route sets base defaults
const layoutRoute = createRoute({
  validateSearch: z.object({
    theme: z.enum(['light', 'dark']).catch('light'),
  }).parse
})

// Child route extends with additional defaults  
const postRoute = createRoute({
  getParentRoute: () => layoutRoute,
  validateSearch: z.object({
    theme: z.enum(['light', 'dark']).catch('light'),
    postId: z.number().catch(1),
    color: z.enum(['white', 'red', 'green']).catch('white'),
  }).parse
})
```

This enables:
- **Inheritance**: Child routes can access parent route defaults
- **Overrides**: Child routes can override parent defaults
- **Composition**: Complex search schemas built from simpler ones

### URL Normalization Strategy

Consider how defaults affect URL structure:

```tsx
// Strategy 1: Keep defaults in URL (explicit)
// User visits: /posts/post
// Router redirects to: /posts/post?postId=1&color=white

// Strategy 2: Hide defaults in URL (clean)
// User visits: /posts/post
// URL stays: /posts/post
// Component receives: { postId: 1, color: 'white' }
```

TanStack Router uses Strategy 2 by default, keeping URLs clean while providing robust defaults internally.

### Further Exploration

Experiment with these advanced patterns:

1. **Conditional Defaults**: Create defaults that depend on other search parameters:
   ```tsx
   validateSearch: (input) => {
     const theme = input.theme || 'light'
     return {
       theme,
       color: input.color || (theme === 'dark' ? 'white' : 'black')
     }
   }
   ```

2. **Context-Aware Defaults**: Use route context to provide smarter defaults:
   ```tsx
   validateSearch: (input, { context }) => {
     return z.object({
       userId: z.number().catch(context.currentUser?.id || 1)
     }).parse(input)
   }
   ```

3. **Storage-Backed Defaults**: Persist user preferences as defaults:
   ```tsx
   validateSearch: (input) => {
     const saved = localStorage.getItem('preferences')
     const defaults = saved ? JSON.parse(saved) : {}
     
     return z.object({
       sortBy: z.enum(['date', 'title']).catch(defaults.sortBy || 'date')
     }).parse(input)
   }
   ```

4. **Dynamic Default Updates**: Change defaults based on application state and automatically update URLs when needed.

5. **Search Parameter Migrations**: Handle backwards compatibility when search parameter schemas evolve over time.

The power of default search parameters lies in creating resilient, user-friendly applications where URLs always lead to meaningful, complete application states.