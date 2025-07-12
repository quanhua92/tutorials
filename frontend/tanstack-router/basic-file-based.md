# File-Based Routing: Routes as Files, Structure as Folders

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/basic-file-based)**

## The Core Concept: Why This Example Exists

**The Problem:** While programmatic routing provides powerful control, it can become unwieldy for large applications. Developers often struggle with finding routes in massive route tree configurations, and the mental overhead of maintaining centralized route definitions grows with application size. Additionally, many developers are familiar with file-based routing from frameworks like Next.js and expect that convenience.

**The TanStack Solution:** File-based routing transforms your file system into your route structure. Instead of creating routes programmatically and assembling them into a tree, you simply create files in a `routes/` folder and TanStack Router automatically generates the route tree for you. Think of it like organizing your house: instead of writing a blueprint listing every room, you simply build the rooms where they logically belong.

This approach maintains all the power of TanStack Router (type safety, data loading, error boundaries) while providing the convenience and mental model of "folder = URL segment."

---

## Practical Walkthrough: Code Breakdown

### The Minimal Entry Point (`main.tsx:1-27`)

```tsx
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { routeTree } from './routeTree.gen'

const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  defaultStaleTime: 5000,
  scrollRestoration: true,
})
```

Notice how dramatically simpler this is compared to programmatic routing. There's no route definition code at all! The `routeTree` is imported from a generated file (`routeTree.gen.ts`) that TanStack Router creates automatically by scanning your `routes/` folder.

The mental shift is profound: instead of *building* a route tree, you *discover* it from your file structure.

### The Root Route Foundation (`routes/__root.tsx`)

```tsx
export const Route = createRootRoute({
  component: RootComponent,
  notFoundComponent: () => (
    <div>
      <p>This is the notFoundComponent configured on root route</p>
      <Link to="/">Start Over</Link>
    </div>
  ),
})
```

The `__root.tsx` file is special - it defines the foundational route that wraps your entire application. The double underscore prefix (`__`) is a naming convention that indicates "this is a special route file, not a URL segment."

This file serves the same purpose as the root route in programmatic routing, but its location in the file system makes it immediately obvious that it's the application foundation.

### Simple Page Routes (`routes/index.tsx`)

```tsx
export const Route = createFileRoute('/')({
  component: Home,
})

function Home() {
  return (
    <div className="p-2">
      <h3>Welcome Home!</h3>
    </div>
  )
}
```

Here's the core file-based routing pattern:

1. **File location determines URL**: `routes/index.tsx` becomes the `/` route
2. **createFileRoute('/')**: Explicitly declares this file handles the `/` path
3. **Export the Route**: TanStack Router finds and incorporates this route automatically

The beauty is in the simplicity: want a new page? Create a new file. Want to organize routes? Create folders.

### Layout Routes with Data Loading (`routes/posts.route.tsx`)

```tsx
export const Route = createFileRoute('/posts')({
  loader: fetchPosts,
  component: PostsLayoutComponent,
})
```

Files ending in `.route.tsx` are **layout routes** - they provide structure and can load data, but they're designed to have child routes. The URL `/posts` will show this component, but it's also a container for nested routes like `/posts/123`.

The `loader: fetchPosts` demonstrates that file-based routes maintain all the data loading capabilities of programmatic routes.

### Dynamic Routes (`routes/posts.$postId.tsx`)

```tsx
export const Route = createFileRoute('/posts/$postId')({
  loader: async ({ params: { postId } }) => fetchPost(postId),
  errorComponent: PostErrorComponent,
  notFoundComponent: () => <p>Post not found</p>,
  component: PostComponent,
})
```

The file name `posts.$postId.tsx` creates a dynamic route where `$postId` is a parameter. This file handles URLs like `/posts/123`, `/posts/abc`, etc.

Key insights:
- **File name pattern**: `$` prefix indicates a dynamic segment
- **Parameter extraction**: The `postId` parameter is automatically available in loaders and components
- **Error handling**: Each route can still define custom error boundaries
- **Path declaration**: `createFileRoute('/posts/$postId')` must match the file's intended path

### Pathless Layouts (`routes/_pathlessLayout.tsx`)

```tsx
export const Route = createFileRoute('/_pathlessLayout')({
  component: LayoutComponent,
})
```

Files starting with `_` are **pathless layouts** - they provide component structure without creating URL segments. The underscore prefix is a file naming convention that translates to the router concept of pathless routes.

This enables complex layouts where multiple URLs share the same visual structure without that structure being reflected in the URL.

---

## Mental Model: Thinking in File-Based Routing

### The File System as Route Tree

Instead of building a route tree with code, your folder structure *is* your route tree:

```
routes/
├── __root.tsx                  → Root layout (special)
├── index.tsx                   → / (homepage)
├── posts.route.tsx             → /posts (layout route)
├── posts.index.tsx             → /posts (index page)
├── posts.$postId.tsx           → /posts/:postId (dynamic route)
├── _pathlessLayout.tsx         → pathless layout
├── _pathlessLayout.route-a.tsx → /route-a (using pathless layout)
└── _pathlessLayout.route-b.tsx → /route-b (using pathless layout)
```

This maps to the following route structure:
```
RootRoute
├── IndexRoute (/)
├── PostsLayoutRoute (/posts)
│   ├── PostsIndexRoute (/posts/)
│   └── PostRoute (/posts/$postId)
└── PathlessLayoutRoute (_pathlessLayout)
    ├── RouteA (/route-a)
    └── RouteB (/route-b)
```

### File Naming Conventions as Routing Grammar

TanStack Router uses file naming conventions to express routing concepts:

1. **`__` prefix**: Special routes (like `__root.tsx`)
2. **`_` prefix**: Pathless layouts that don't create URL segments
3. **`$` prefix**: Dynamic parameters (like `$postId`)
4. **`.route.` suffix**: Layout routes designed to have children
5. **`.index.` infix**: Index routes that match the parent's exact path
6. **Dots as nesting**: `_layout.route-a.tsx` means route-a uses _layout

Think of these conventions as a routing language written in file names.

### The Generated Route Tree

TanStack Router scans your `routes/` folder and generates `routeTree.gen.ts`:

```tsx
// This file is generated automatically
export const routeTree = rootRoute.addChildren([
  indexRoute,
  postsLayoutRoute.addChildren([
    postsIndexRoute,
    postRoute,
  ]),
  pathlessLayoutRoute.addChildren([
    routeARoute,
    routeBRoute,
  ]),
])
```

This generated file contains the same route tree structure you would write manually in programmatic routing, but it's derived from your file system. The best of both worlds: the convenience of file-based organization with the power of programmatic routing.

### When to Choose File-Based vs Programmatic

**File-Based Routing** excels when:
- You want rapid development and clear organization
- Your routes map naturally to pages/sections
- Your team is familiar with Next.js or similar frameworks
- You prefer convention over configuration

**Programmatic Routing** excels when:
- You need complex conditional routing logic
- Routes are generated dynamically based on data
- You're building a highly customized routing experience
- You need granular control over route tree construction

### Type Safety Across the File System

Even with file-based routing, TanStack Router maintains complete type safety:

```tsx
// In any component, links are fully typed
<Link
  to="/posts/$postId"
  params={{ postId: "123" }}  // TypeScript knows this parameter exists
>
  View Post
</Link>
```

The generated route tree provides TypeScript with complete knowledge of your application's routing structure, regardless of whether you defined it programmatically or through files.

### Further Exploration

Experiment with these concepts to deepen your understanding:

1. **Create a nested structure**: Add a folder like `routes/dashboard/` with several routes inside. See how the folder structure translates to URL structure.

2. **Play with pathless layouts**: Create a `_adminLayout.tsx` file and several routes that use it. Notice how the layout appears in your components but not in URLs.

3. **Dynamic routes with constraints**: Try creating `routes/users.$userId.tsx` and experiment with type safety when navigating to user pages.

4. **Compare the generated tree**: Look at `routeTree.gen.ts` after making changes to your file structure. See how file organization translates to route tree construction.

The power of file-based routing is in its predictability: if you can navigate your file system, you can understand your application's routing structure. It's routing that matches the way developers naturally think about organizing code.