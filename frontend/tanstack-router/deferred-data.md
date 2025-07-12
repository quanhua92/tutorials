# Deferred Data Loading: Progressive Rendering for Better UX

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/deferred-data)**

## Part 1: The Core Concept

**The Problem:** Traditional route loading creates an all-or-nothing experience where users must wait for all data to load before seeing any content. This becomes problematic when some data loads quickly (like a post title) while other data takes much longer (like comments from a slow API). Users end up staring at loading spinners even when 80% of the content could already be displayed.

**The TanStack Solution:** TanStack Router's deferred data loading allows you to immediately render parts of your page while other data loads progressively in the background. Using the `defer()` function and `<Await>` component, you can create sophisticated loading experiences where fast data renders immediately and slow data streams in as it becomes available.

Think of it like a progressive image load - you see the basic structure immediately, then details fill in as they become available, creating a much more responsive and engaging user experience.

---

## Part 2: Practical Walkthrough

### Deferred Data Pattern (`main.tsx:42-71`)

```tsx
const fetchPost = async (postId: string) => {
  console.info(`Fetching post with id ${postId}...`)

  // Start slow comments request (2 second delay)
  const commentsPromise = new Promise((r) => setTimeout(r, 2000))
    .then(() =>
      axios.get<Array<CommentType>>(
        `https://jsonplaceholder.typicode.com/comments?postId=${postId}`,
      ),
    )
    .then((r) => r.data)

  // Await fast post request (1 second delay)  
  const post = await new Promise((r) => setTimeout(r, 1000))
    .then(() =>
      axios.get<PostType>(
        `https://jsonplaceholder.typicode.com/posts/${postId}`,
      ),
    )
    .then((r) => r.data)

  return {
    post,
    commentsPromise: defer(commentsPromise), // Wrap promise in defer()
  }
}
```

This demonstrates the key deferred data pattern:

- **Fast Data (Awaited)**: The post data is awaited, so it's available immediately when the component renders
- **Slow Data (Deferred)**: Comments are wrapped in `defer()`, creating a deferred promise that renders progressively
- **Mixed Return**: The loader returns both immediate data and deferred promises
- **Non-Blocking**: The route doesn't wait for comments to complete before rendering

### Progressive Component Rendering (`main.tsx:203-242`)

```tsx
function PostComponent() {
  const { post, commentsPromise } = postRoute.useLoaderData()

  return (
    <div className="space-y-2">
      {/* This renders immediately */}
      <h4 className="text-xl font-bold underline">{post.title}</h4>
      <div className="text-sm">{post.body}</div>
      
      {/* This renders progressively */}
      <React.Suspense
        fallback={
          <div className="flex items-center gap-2">
            <Spinner />
            Loading comments...
          </div>
        }
        key={post.id}
      >
        <Await promise={commentsPromise}>
          {(comments) => {
            return (
              <div className="space-y-2">
                <h5 className="text-lg font-bold underline">Comments</h5>
                {comments.map((comment) => {
                  return (
                    <div key={comment.id}>
                      <h6 className="text-md font-bold">{comment.name}</h6>
                      <div className="text-sm italic opacity-50">
                        {comment.email}
                      </div>
                      <div className="text-sm">{comment.body}</div>
                    </div>
                  )
                })}
              </div>
            )
          }}
        </Await>
      </React.Suspense>
    </div>
  )
}
```

This shows the progressive rendering pattern:

- **Immediate Content**: Post title and body render immediately using `post` data
- **Suspense Boundary**: `React.Suspense` handles the loading state for deferred data
- **`<Await>` Component**: Unwraps the deferred promise and provides resolved data
- **Key Prop**: `key={post.id}` ensures Suspense resets when navigating between posts
- **Loading Fallback**: Shows spinner and text while comments load

### Loading State Indicators (`main.tsx:73-85, 156-173`)

```tsx
function Spinner({ show, wait }: { show?: boolean; wait?: `delay-${number}` }) {
  return (
    <div
      className={`inline-block animate-spin px-3 transition ${
        (show ?? true)
          ? `opacity-1 duration-500 ${wait ?? 'delay-300'}`
          : 'duration-500 opacity-0 delay-0'
      }`}
    >
      ⍥
    </div>
  )
}

// Usage with MatchRoute for navigation loading
<MatchRoute
  to={postRoute.to}
  params={{ postId: post.id }}
  pending
>
  {(match) => {
    return <Spinner show={!!match} wait="delay-0" />
  }}
</MatchRoute>
```

The loading indicators provide visual feedback:

- **Smart Spinner**: Only shows after delay to avoid flashing for fast loads
- **Navigation Loading**: `MatchRoute` with `pending` shows loading state during route transitions
- **Smooth Transitions**: CSS transitions prevent jarring loading state changes

### Route Configuration (`main.tsx:187-193`)

```tsx
const postRoute = createRoute({
  getParentRoute: () => postsRoute,
  path: '$postId',
  loader: async ({ params: { postId } }) => fetchPost(postId),
  errorComponent: PostErrorComponent,
  component: PostComponent,
})
```

Route setup for deferred data is straightforward:

- **Standard Loader**: The loader function can return mixed immediate/deferred data
- **Error Handling**: Error boundaries work normally with deferred data
- **Type Safety**: TypeScript correctly infers the loader data types

### Router Settings (`main.tsx:249-254`)

```tsx
const router = createRouter({
  routeTree,
  defaultPreload: 'intent',
  scrollRestoration: true,
})
```

Router configuration supports deferred loading:

- **Intent Preloading**: Starts loading deferred data when users hover over links
- **Scroll Restoration**: Works correctly with progressive rendering

---

## Part 3: Mental Models & Deep Dives

### The Theater Curtain Analogy

Think of deferred data loading like a theater performance:

```
Traditional Loading:
🎭 [Curtain Closed] → Wait for all actors → [Curtain Opens] → Full scene

Deferred Loading:  
🎭 [Curtain Opens] → Main actors perform → Supporting actors join progressively
```

With deferred loading:
- Users see the "main performance" (fast data) immediately
- Additional content (slow data) streams in without interrupting the experience
- The show goes on while scenery changes in the background

### Data Dependency Waterfall vs. Parallel Loading

Traditional sequential loading creates waterfalls:

```tsx
// Waterfall (bad)
async function traditionalLoader() {
  const post = await fetchPost(postId)     // 1 second
  const comments = await fetchComments(postId) // 2 seconds  
  return { post, comments }                // Total: 3 seconds
}
```

Deferred loading enables parallelization:

```tsx
// Parallel (good)
async function deferredLoader() {
  const commentsPromise = fetchComments(postId) // Starts immediately
  const post = await fetchPost(postId)          // 1 second
  return { 
    post,                                       // Available at 1 second
    commentsPromise: defer(commentsPromise)     // Resolves at 2 seconds  
  }
}
```

The key insight: **Start all requests immediately, await only what you need for initial render.**

### The Three Zones of Data Loading

Deferred data creates three distinct zones in your application:

```tsx
function Component() {
  const { fastData, slowDataPromise } = useLoaderData()
  
  return (
    <div>
      {/* Zone 1: Immediate (no loading state) */}
      <h1>{fastData.title}</h1>
      
      {/* Zone 2: Loading (fallback UI) */}
      <Suspense fallback={<Spinner />}>
        
        {/* Zone 3: Progressive (streams in) */}
        <Await promise={slowDataPromise}>
          {(slowData) => <SlowContent data={slowData} />}
        </Await>
        
      </Suspense>
    </div>
  )
}
```

Each zone has different UX characteristics:
- **Zone 1**: Instant gratification, immediate interaction
- **Zone 2**: Manages expectations with clear loading feedback  
- **Zone 3**: Delights users as content progressively appears

### Error Handling in Deferred Data

Deferred data requires thoughtful error handling:

```tsx
// Errors in immediate data fail the entire route
const post = await fetchPost(postId) // Route-level error

// Errors in deferred data are isolated
const commentsPromise = defer(
  fetchComments(postId).catch(error => {
    // Handle error gracefully within the promise
    return { error: error.message, comments: [] }
  })
)
```

This isolation means:
- Fast data errors prevent the page from rendering (appropriate for critical data)
- Slow data errors don't break the whole experience (appropriate for supplementary data)
- Users get a functional page even if some parts fail

### Performance Mental Model

Deferred data optimizes for perceived performance over absolute performance:

```
Metric                | Traditional | Deferred
----------------------|-------------|----------
Time to First Paint   | 3000ms     | 1000ms   ✓
Time to Interactive   | 3000ms     | 1000ms   ✓  
Time to Complete      | 3000ms     | 2000ms   ✓
User Perceived Speed  | Slow       | Fast     ✓
```

The key insight: **Users perceive speed based on when they first see meaningful content, not when everything finishes loading.**

### Deciding What to Defer

Use this decision framework:

```tsx
// Critical for initial render → Await
const user = await fetchUser(userId)         // Page meaningless without user
const permissions = await fetchPermissions() // Security-critical

// Enhances experience → Defer  
const analytics = defer(fetchAnalytics())    // Nice-to-have data
const suggestions = defer(fetchSuggestions()) // Secondary content
const comments = defer(fetchComments())      // User-generated content
```

**Defer data that is:**
- Non-critical for initial understanding
- Slow to load or from unreliable sources
- Enhancing rather than essential
- User-generated or dynamic content

### Cascade vs. Fork Patterns

Two common patterns emerge:

```tsx
// Cascade Pattern: Second request depends on first
async function cascadeLoader() {
  const user = await fetchUser()
  const posts = defer(fetchUserPosts(user.id)) // Depends on user
  return { user, posts }
}

// Fork Pattern: Independent parallel requests  
async function forkLoader() {
  const user = fetchUser()
  const posts = defer(fetchPosts())    // Independent
  const categories = defer(fetchCategories()) // Independent
  return { 
    user: await user, 
    posts, 
    categories 
  }
}
```

Choose cascade when data has dependencies, fork when data is independent.

### Further Exploration

Experiment with these advanced patterns:

1. **Nested Deferred Data**: Defer data within deferred data for multi-level progressive loading.

2. **Conditional Deferring**: Defer different data based on user type, device capability, or connection speed.

3. **Prefetch + Defer**: Combine route prefetching with deferred data for even faster perceived performance.

4. **Error Recovery**: Implement retry mechanisms for failed deferred promises.

5. **Real-time Updates**: Combine deferred data with WebSocket connections for live-updating content.

6. **Cache Integration**: Use deferred data with caching strategies to balance freshness and performance.

The power of deferred data lies in creating applications that feel fast and responsive while still providing rich, complete experiences. Users stay engaged because they see progress immediately, rather than waiting for everything to load before seeing anything at all.