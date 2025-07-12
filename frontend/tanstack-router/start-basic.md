# TanStack Start Basic: Full-Stack Data Loading and SSR

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/start-basic)**

## The Core Concept: Why This Example Exists

**The Problem:** Real applications need to load data from servers, handle errors gracefully, provide SEO-friendly metadata, and work seamlessly across server and client environments. Traditional client-side React requires complex patterns to achieve these goals: data fetching in components, loading states, error boundaries, and separate SEO solutions. The coordination between server-side rendering and client-side hydration often creates bugs and complexity.

**The TanStack Solution:** TanStack Start elevates data loading to a first-class routing concern, providing server functions that run on the server during SSR and seamlessly transition to the client. Think of it like having API endpoints that are automatically available as TypeScript functions - no REST APIs to build, no client/server data synchronization issues, and no loading states in your components.

This example demonstrates the core TanStack Start pattern: server functions + route loaders + SSR, creating applications that are fast, SEO-friendly, and maintainable.

---

## Practical Walkthrough: Code Breakdown

### Server Functions: The Data Layer (`utils/posts.tsx:10-40`)

```tsx
export const fetchPost = createServerFn()
  .validator((d: string) => d)
  .handler(async ({ data }) => {
    console.info(`Fetching post with id ${data}...`)
    const res = await fetch(
      `https://jsonplaceholder.typicode.com/posts/${data}`,
    )
    if (!res.ok) {
      if (res.status === 404) {
        throw notFound()
      }
      throw new Error('Failed to fetch post')
    }
    
    const post = (await res.json()) as PostType
    return post
  })

export const fetchPosts = createServerFn().handler(async () => {
  console.info('Fetching posts...')
  const res = await fetch('https://jsonplaceholder.typicode.com/posts')
  if (!res.ok) {
    throw new Error('Failed to fetch posts')
  }
  
  const posts = (await res.json()) as Array<PostType>
  return posts.slice(0, 10)
})
```

Server functions are the foundation of TanStack Start's data architecture:

- **createServerFn()**: Creates functions that run on the server during SSR, then become RPC calls on the client
- **Validator pattern**: Type-safe input validation using `.validator()`
- **Error handling**: Server errors (like 404s) are handled automatically by the routing system
- **Automatic serialization**: Return values are automatically serialized/deserialized between server and client

### Route-Level Data Loading (`routes/posts.tsx:4-7`)

```tsx
export const Route = createFileRoute('/posts')({
  loader: async () => fetchPosts(),
  component: PostsComponent,
})
```

Routes declare their data dependencies through loaders:

- **Server execution**: During SSR, the loader runs on the server
- **Client execution**: During client navigation, the loader becomes an RPC call
- **Seamless transition**: The same code works in both environments
- **No loading states**: Components always receive data immediately

### Component Data Access (`routes/posts.tsx:9-11`)

```tsx
function PostsComponent() {
  const posts = Route.useLoaderData()
  // posts is always available - no loading state needed!
}
```

Components access loaded data synchronously:

- **Always available**: Data is guaranteed to be present when component renders
- **Type safety**: TypeScript infers the exact type from the server function
- **No suspense needed**: Data is pre-loaded by the route system

### Dynamic Routes with Parameters (`routes/posts.$postId.tsx:6-7`)

```tsx
export const Route = createFileRoute('/posts/$postId')({
  loader: ({ params: { postId } }) => fetchPost({ data: postId }),
  component: PostComponent,
})
```

Dynamic routes automatically pass parameters to loaders:

- **Parameter extraction**: `postId` is automatically typed and available
- **Server function calls**: Parameters flow seamlessly into server functions
- **Caching**: Multiple requests for the same post are automatically deduplicated

### SEO and Meta Management (`routes/__root.tsx:16-59`)

```tsx
export const Route = createRootRoute({
  head: () => ({
    meta: [
      {
        charSet: 'utf-8',
      },
      {
        name: 'viewport',
        content: 'width=device-width, initial-scale=1',
      },
      ...seo({
        title: 'TanStack Start | Type-Safe, Client-First, Full-Stack React Framework',
        description: `TanStack Start is a type-safe, client-first, full-stack React framework.`,
      }),
    ],
    links: [
      { rel: 'stylesheet', href: appCss },
      { rel: 'apple-touch-icon', sizes: '180x180', href: '/apple-touch-icon.png' },
      { rel: 'icon', type: 'image/png', sizes: '32x32', href: '/favicon-32x32.png' },
    ],
    scripts: [
      {
        src: '/customScript.js',
        type: 'text/javascript',
      },
    ],
  }),
})
```

The `head()` function provides complete control over document metadata:

- **SEO optimization**: Meta tags for search engines and social media
- **Asset management**: CSS and JavaScript files are included automatically
- **Performance**: Critical resources are loaded optimally
- **Customization**: Each route can override or extend head content

### Error Boundaries and 404 Handling (`routes/posts.$postId.tsx:8-12`)

```tsx
export const Route = createFileRoute('/posts/$postId')({
  loader: ({ params: { postId } }) => fetchPost({ data: postId }),
  errorComponent: PostErrorComponent,
  notFoundComponent: () => <NotFound>Post not found</NotFound>,
})
```

Route-level error handling provides granular control:

- **errorComponent**: Handles server function errors and runtime errors
- **notFoundComponent**: Specific handling for 404 cases
- **Error boundaries**: Errors don't crash the entire application

### The Shell Component Pattern (`routes/__root.tsx:62-63`)

```tsx
export const Route = createRootRoute({
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html>
      <head><HeadContent /></head>
      <body>
        {/* Navigation */}
        {children}
        <Scripts />
      </body>
    </html>
  )
}
```

The shell component wraps your entire application:

- **Full HTML control**: You define the complete HTML document structure
- **HeadContent**: Injects head content from route `head()` functions
- **Scripts**: Includes necessary JavaScript for hydration
- **Progressive enhancement**: The shell works with or without JavaScript

---

## Mental Model: Thinking in Server Functions + SSR

### The Server Function Philosophy

Traditional full-stack development requires building APIs:

```tsx
// Traditional approach
// 1. Build API endpoint: /api/posts/:id
app.get('/api/posts/:id', async (req, res) => {
  const post = await fetchPost(req.params.id)
  res.json(post)
})

// 2. Create client function
async function getPost(id: string) {
  const response = await fetch(`/api/posts/${id}`)
  return response.json()
}

// 3. Use in component with loading states
function PostComponent() {
  const [post, setPost] = useState(null)
  const [loading, setLoading] = useState(true)
  
  useEffect(() => {
    getPost(id).then(setPost).finally(() => setLoading(false))
  }, [id])
  
  if (loading) return <Spinner />
  return <div>{post.title}</div>
}
```

TanStack Start collapses this into a single pattern:

```tsx
// Server function (automatically becomes API + client function)
export const fetchPost = createServerFn()
  .validator((id: string) => id)
  .handler(async ({ data: id }) => {
    return await getPostFromDatabase(id)
  })

// Route loader (automatically handles SSR + client transitions)
export const Route = createFileRoute('/posts/$postId')({
  loader: ({ params }) => fetchPost({ data: params.postId }),
  component: PostComponent,
})

// Component (always has data, no loading states)
function PostComponent() {
  const post = Route.useLoaderData() // Always available!
  return <div>{post.title}</div>
}
```

### The SSR-First Mental Model

TanStack Start thinks "SSR-first":

1. **Server renders**: Routes load data and render complete HTML
2. **Client hydrates**: JavaScript makes the page interactive
3. **Client navigates**: Subsequent navigation uses RPC calls for data

This creates applications that are:
- **Fast on first load**: Users see content immediately
- **SEO-friendly**: Search engines see complete HTML
- **Progressively enhanced**: Core functionality works without JavaScript

### The Data Flow Symphony

Understanding how data flows through TanStack Start:

```
1. User visits /posts/123
2. Server runs fetchPost({ data: "123" })
3. Server renders PostComponent with loaded data
4. Browser receives complete HTML with content
5. JavaScript hydrates the page for interactivity
6. User clicks link to /posts/456
7. Client calls fetchPost({ data: "456" }) via RPC
8. Route transitions with new data
```

### Type Safety Across the Stack

Server functions provide end-to-end type safety:

```tsx
// Server function defines the contract
export const fetchPost = createServerFn()
  .validator((id: string) => id)        // Input type
  .handler(async () => ({ title: "" })) // Output type

// Route loader is type-checked
export const Route = createFileRoute('/posts/$postId')({
  loader: ({ params }) => 
    fetchPost({ data: params.postId }), // ✅ TypeScript knows this is string
})

// Component receives typed data
function PostComponent() {
  const post = Route.useLoaderData() // ✅ TypeScript knows this is { title: string }
  return <h1>{post.title}</h1>
}
```

### Error Handling Across Environments

Server functions handle errors consistently:

```tsx
export const fetchPost = createServerFn()
  .handler(async ({ data: id }) => {
    const post = await db.post.findUnique({ where: { id } })
    if (!post) {
      throw notFound() // Becomes 404 in SSR, handled by notFoundComponent in client
    }
    return post
  })
```

The same error handling code works for both SSR and client navigation.

### Further Exploration

Experiment with TanStack Start's full-stack patterns:

1. **Add mutations**: Create server functions that modify data and see how they work across client and server.

2. **Explore nested loading**: Create deeply nested routes with their own loaders and see how data flows through the hierarchy.

3. **Test SSR vs client**: Compare page source (server-rendered) vs dynamically navigated content.

4. **Add middleware**: Experiment with server function middleware for authentication, logging, or validation.

5. **Performance profiling**: Use browser dev tools to see the difference between SSR page loads and client navigation.

6. **SEO testing**: Use tools like Google's Rich Results Test to see how server-rendered content appears to search engines.

TanStack Start represents a paradigm shift from "client-side apps with APIs" to "full-stack React applications." Server functions eliminate the client/server boundary, route loaders eliminate loading states, and SSR provides immediate content delivery - all while maintaining the familiar React development experience.