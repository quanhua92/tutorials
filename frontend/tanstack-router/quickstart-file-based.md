# Quickstart File-Based Routing: Zero-Config Route Discovery

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/quickstart-file-based)**

## The Core Concept: Why This Example Exists

**The Problem:** Setting up routing in React applications traditionally involves tedious manual configuration. You create components, then separately define routes, then wire them together, then maintain the mapping as your app grows. This creates multiple sources of truth and makes refactoring painful. When you rename a file, you must remember to update route definitions in multiple places.

**The TanStack Solution:** File-based routing eliminates the configuration overhead by using your file system as the single source of truth for your application's routes. Like Next.js but more powerful, TanStack Router's file-based system automatically generates type-safe routes from your folder structure, while still giving you the full power of programmatic routing when you need it.

This example demonstrates the minimal setup required to get a fully functional, type-safe router running with automatic route discovery, code splitting, and developer tools. It's the fastest way to start building with TanStack Router while maintaining maximum flexibility for future scaling.

---

## Practical Walkthrough: Code Breakdown

### The Router Plugin Configuration (`vite.config.js:7-9`)

```tsx
export default defineConfig({
  plugins: [
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    react(),
  ],
})
```

The `@tanstack/router-plugin` is the magic that makes file-based routing work:

**`target: 'react'`**: Tells the plugin to generate React-specific route configurations
**`autoCodeSplitting: true`**: Automatically wraps each route in React's `lazy()` for optimal bundle splitting

This plugin watches your `src/routes/` directory and generates `routeTree.gen.ts` whenever you add, remove, or modify route files.

### Generated Route Tree (`main.tsx:4`)

```tsx
import { routeTree } from './routeTree.gen'

const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  scrollRestoration: true,
})
```

The auto-generated route tree replaces hundreds of lines of manual route configuration. The plugin creates a perfectly optimized route tree with:
- **Type Safety**: Full TypeScript inference for all routes and parameters
- **Code Splitting**: Each route loads independently for better performance
- **Tree Shaking**: Only the routes you use are included in your bundle

### Root Route Structure (`routes/__root.tsx:5-7`)

```tsx
export const Route = createRootRoute({
  component: RootComponent,
})
```

File-based routing still uses the same powerful route objects, but the file system determines the route structure:

**File**: `src/routes/__root.tsx`
**Purpose**: Defines the application shell that wraps all other routes
**Convention**: `__root.tsx` is a special filename that creates the root route

The double underscore prefix indicates special file-based routing concepts that don't create URL segments.

### Page Route Creation (`routes/index.tsx:4-6`)

```tsx
export const Route = createFileRoute('/')({
  component: HomeComponent,
})
```

Each route file exports a `Route` object created with `createFileRoute()`:

**`createFileRoute('/')`**: The path must match the file's position in the route tree
**Type Safety**: TypeScript will error if the path doesn't match the file location
**Single Source of Truth**: The file path determines the URL structure

### File Path to URL Mapping

The routing system follows intuitive file-to-URL conventions:

```
src/routes/
├── __root.tsx          → / (wraps all routes)
├── index.tsx           → / (homepage)
├── about.tsx           → /about
├── posts/
│   ├── index.tsx       → /posts
│   └── $postId.tsx     → /posts/:postId
└── users/
    ├── $userId/
    │   └── profile.tsx → /users/:userId/profile
    └── settings.tsx    → /users/settings
```

**Special Conventions**:
- `index.tsx` maps to the parent directory's path
- `$param.tsx` creates dynamic route parameters
- `__file.tsx` creates pathless layouts (structure without URL changes)
- `(group)` folders organize files without affecting URLs

### Automatic Code Generation

When you save a route file, the plugin generates `routeTree.gen.ts`:

```tsx
// Generated automatically - DO NOT EDIT
export const routeTree = {
  __root: {
    path: '/',
    component: () => import('./routes/__root'),
    children: {
      '/': {
        component: () => import('./routes/index'),
      },
      '/about': {
        component: () => import('./routes/about'),
      },
    },
  },
}
```

This generated code:
- **Maintains Type Safety**: Every route is properly typed
- **Enables Tree Shaking**: Unused routes don't bloat your bundle
- **Handles Lazy Loading**: Components load on-demand automatically
- **Provides Hot Reloading**: Changes reflect immediately in development

---

## Mental Model: Convention Over Configuration

### The File System as Router State

Think of your `src/routes/` directory as a visual representation of your application's navigation structure:

```
Routes Folder (File System)     →     User URLs (Browser)
├── __root.tsx                  →     / (layout)
├── index.tsx                   →     / (content)
├── about.tsx                   →     /about
├── blog/                       →     /blog/*
│   ├── index.tsx              →     /blog
│   ├── $slug.tsx              →     /blog/hello-world
│   └── categories/            →     /blog/categories/*
│       ├── index.tsx          →     /blog/categories
│       └── $category.tsx      →     /blog/categories/tech
```

**Benefits of This Mental Model**:
1. **Instant Understanding**: Anyone can look at your file structure and understand your app's routes
2. **Refactoring Confidence**: Move files around and URLs automatically update
3. **Scaling Clarity**: Complex applications remain organized and discoverable

### Progressive Enhancement Strategy

File-based routing follows a progressive enhancement approach:

**Level 1: Basic Routes**
```tsx
// src/routes/about.tsx
export const Route = createFileRoute('/about')({
  component: () => <div>About Page</div>,
})
```

**Level 2: Data Loading**
```tsx
// src/routes/posts/$postId.tsx
export const Route = createFileRoute('/posts/$postId')({
  loader: ({ params }) => fetchPost(params.postId),
  component: PostComponent,
})
```

**Level 3: Advanced Features**
```tsx
// src/routes/admin/$userId.tsx
export const Route = createFileRoute('/admin/$userId')({
  beforeLoad: ({ context }) => requireAuth(context),
  loader: ({ params }) => fetchUser(params.userId),
  errorComponent: AdminErrorComponent,
  pendingComponent: AdminLoadingComponent,
  component: AdminUserComponent,
})
```

Each level adds capability without changing the fundamental file-based structure.

### Migration Patterns

**From Manual Routes**:
```tsx
// Before: Manual route configuration
const routeTree = createRouter({
  routeTree: rootRoute.addChildren([
    indexRoute,
    aboutRoute,
    blogRoute.addChildren([
      blogIndexRoute,
      postRoute,
    ]),
  ]),
})

// After: File-based automatic discovery
const router = createRouter({
  routeTree, // Auto-generated from files
})
```

**Adding File-Based to Existing Apps**:
1. Install `@tanstack/router-plugin`
2. Add plugin to build config
3. Move route components to `src/routes/` with file-based naming
4. Replace manual route tree with generated one
5. TypeScript will guide you through any missing pieces

### Advanced File-Based Patterns

**Pathless Layouts for Shared UI**:
```
src/routes/
├── __root.tsx
├── _auth.tsx                   → Pathless layout (auth wrapper)
├── _auth.dashboard.tsx         → /dashboard (requires auth)
├── _auth.settings.tsx          → /settings (requires auth)
└── login.tsx                   → /login (public)
```

**Route Groups for Organization**:
```
src/routes/
├── (dashboard)/                → Folder grouping (no URL impact)
│   ├── analytics.tsx          → /analytics
│   └── reports.tsx            → /reports
└── (marketing)/               → Different section
    ├── landing.tsx            → /landing
    └── pricing.tsx            → /pricing
```

**Parameterized Nested Routes**:
```
src/routes/
├── users/
│   ├── $userId/
│   │   ├── index.tsx          → /users/:userId
│   │   ├── profile.tsx        → /users/:userId/profile
│   │   └── settings.tsx       → /users/:userId/settings
│   └── index.tsx              → /users
```

### Development Workflow Benefits

**Instant Route Creation**:
1. Create `src/routes/new-page.tsx`
2. Export a route object
3. Link becomes immediately available with full type safety

**Automatic Type Safety**:
```tsx
// TypeScript knows all available routes
<Link to="/posts/$postId" params={{ postId: "123" }} />
//        ^^^^^^^^^^^^^^^^         ^^^^^^
//        Fully typed             Type-checked
```

**Hot Module Reloading**:
- File changes trigger immediate route tree regeneration
- No build restart required
- Route changes reflect instantly in the browser

### Further Exploration

Try these experiments to master file-based routing:

1. **Create Nested Routes**: Add a `posts/$postId/comments.tsx` file and see how the URL structure automatically reflects the file hierarchy.

2. **Experiment with Dynamic Routes**: Create routes with multiple parameters like `users/$userId/projects/$projectId.tsx`.

3. **Add Pathless Layouts**: Create `_layout.tsx` files to add shared UI without changing URLs.

4. **Test Route Groups**: Use parentheses in folder names to organize routes without affecting the URL structure.

5. **Explore Code Splitting**: Check your browser's network tab to see how each route loads independently.

File-based routing transforms route management from a configuration chore into an intuitive, visual development experience that scales beautifully with your application's complexity.