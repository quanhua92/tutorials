# TanStack Start Counter: Server-Side State and Full-Stack Simplicity

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/start-counter)**

## The Core Concept: Why This Example Exists

**The Problem:** Modern web applications often need to share state between client and server, persist data across sessions, and handle server-side operations seamlessly. Traditional approaches require complex coordination between frontend state management, API endpoints, database operations, and client-server synchronization. The boundary between client and server code often creates friction and complexity.

**The TanStack Solution:** TanStack Start enables **unified full-stack development** where server and client code live in the same files, share the same type system, and coordinate automatically. Think of it like having a single codebase that runs everywhere - your "client" code can directly call server functions, and your server state automatically synchronizes with the browser.

This simple counter example demonstrates the fundamental concepts: server functions that persist state, automatic client-server coordination, and the mental model shift from "API thinking" to "function thinking."

---

## Practical Walkthrough: Code Breakdown

### Server Function Definition (`routes/index.tsx:13-22`)

```tsx
const getCount = createServerFn({ method: 'GET' }).handler(() => {
  return readCount()
})

const updateCount = createServerFn({ method: 'POST' })
  .validator((addBy: number) => addBy)
  .handler(async ({ data }) => {
    const count = await readCount()
    await fs.promises.writeFile(filePath, `${count + data}`)
  })
```

Server functions blur the line between client and server:

- **createServerFn**: Defines a function that runs on the server but can be called from the client
- **Method specification**: HTTP method is declared explicitly for optimization
- **Type-safe validation**: The validator ensures the input matches expected types
- **Direct file system access**: Server code can read/write files, access databases, etc.
- **Automatic serialization**: Return values are automatically serialized for client consumption

### Route-Level Data Loading (`routes/index.tsx:24-27`)

```tsx
export const Route = createFileRoute('/')({
  component: Home,
  loader: async () => await getCount(),
})
```

The loader integrates server functions with routing:

- **Server-side execution**: The loader runs on the server during route transitions
- **Automatic caching**: TanStack Start handles caching and invalidation
- **Type inference**: The component automatically knows the loader data type
- **SSR integration**: Data is available immediately on first page load

### Client-Side Server Function Calls (`routes/index.tsx:29-43`)

```tsx
function Home() {
  const router = useRouter()
  const state = Route.useLoaderData()

  return (
    <button
      onClick={() => {
        updateCount({ data: 1 }).then(() => {
          router.invalidate()
        })
      }}
    >
      Add 1 to {state}?
    </button>
  )
}
```

The client seamlessly calls server functions:

- **Direct function calls**: `updateCount({ data: 1 })` looks like a normal function call
- **Automatic networking**: TanStack Start handles HTTP requests transparently
- **Router invalidation**: `router.invalidate()` triggers data refresh
- **Type safety**: TypeScript knows the function signature and return types

### Persistent Server State (`routes/index.tsx:5-11`)

```tsx
const filePath = 'count.txt'

async function readCount() {
  return parseInt(
    await fs.promises.readFile(filePath, 'utf-8').catch(() => '0'),
  )
}
```

Server state persists beyond the request lifecycle:

- **File system persistence**: State is written to disk and survives server restarts
- **Error handling**: Graceful fallback to '0' if file doesn't exist
- **Async operations**: File I/O uses standard Node.js patterns
- **Shared between users**: All clients see the same counter value

### Full Document Structure (`routes/__root.tsx:28-49`)

```tsx
function RootDocument({ children }: { children: React.ReactNode }) {
  return (
    <html>
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  )
}
```

TanStack Start manages the complete HTML document:

- **Full HTML control**: You control the entire document structure
- **HeadContent**: Automatically includes necessary metadata and links
- **Scripts**: Handles client-side hydration and JavaScript loading
- **SSR by default**: The initial page load is server-rendered

---

## Mental Model: Thinking in Full-Stack Functions

### The Function Boundary Shift

Traditional client-server architecture creates artificial boundaries:

```tsx
// Traditional approach - separate client and server
// Client code
const fetchCount = async () => {
  const response = await fetch('/api/count')
  return response.json()
}

const updateCount = async (increment) => {
  await fetch('/api/count', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ increment })
  })
}

// Server code (separate file)
app.get('/api/count', (req, res) => {
  const count = readCountFromFile()
  res.json(count)
})

app.post('/api/count', (req, res) => {
  const { increment } = req.body
  updateCountInFile(increment)
  res.status(200).end()
})
```

TanStack Start unifies this into a single mental model:

```tsx
// Unified approach - functions that happen to run on the server
const getCount = createServerFn({ method: 'GET' }).handler(() => {
  return readCount() // This runs on the server
})

const updateCount = createServerFn({ method: 'POST' })
  .validator((addBy: number) => addBy)
  .handler(async ({ data }) => {
    const count = await readCount()
    await fs.promises.writeFile(filePath, `${count + data}`)
  })

// Client code calls server functions directly
onClick={() => {
  updateCount({ data: 1 }).then(() => {
    router.invalidate()
  })
}}
```

### State Architecture Patterns

**1. Server-First State**
```tsx
// State lives on the server, clients observe it
const getAppState = createServerFn({ method: 'GET' }).handler(async () => {
  return {
    counter: await readCount(),
    lastUpdated: new Date().toISOString(),
    activeUsers: await getActiveUserCount()
  }
})

// Components react to server state changes
function Dashboard() {
  const state = Route.useLoaderData() // Fresh server state
  return <div>Counter: {state.counter}</div>
}
```

**2. Optimistic Updates**
```tsx
// Update UI immediately, sync with server
function Counter() {
  const [optimisticCount, setOptimisticCount] = useState(null)
  const serverCount = Route.useLoaderData()
  const displayCount = optimisticCount ?? serverCount

  const increment = async () => {
    setOptimisticCount(displayCount + 1) // Immediate UI update
    
    try {
      await updateCount({ data: 1 })
      router.invalidate() // Sync with server
      setOptimisticCount(null) // Clear optimistic state
    } catch (error) {
      setOptimisticCount(null) // Revert on error
      showErrorMessage(error)
    }
  }

  return <button onClick={increment}>Count: {displayCount}</button>
}
```

**3. Real-time Sync**
```tsx
// Server functions can push updates to clients
const subscribeToCount = createServerFn({ method: 'GET' }).handler(async () => {
  // Set up server-sent events or WebSocket
  return createEventStream((send) => {
    const interval = setInterval(() => {
      send({ type: 'count', data: readCount() })
    }, 1000)
    
    return () => clearInterval(interval)
  })
})

// Components can subscribe to real-time updates
function LiveCounter() {
  const [count, setCount] = useState(Route.useLoaderData())
  
  useEffect(() => {
    const stream = subscribeToCount()
    stream.addEventListener('count', (event) => {
      setCount(event.data)
    })
    return () => stream.close()
  }, [])
}
```

### Data Flow Patterns

**1. Server → Client (Initial Load)**
```
Server Function (loader) → Route Data → Component Props
```
Data flows from server to client during route transitions.

**2. Client → Server → Client (Updates)**
```
User Interaction → Server Function Call → Server State Change → Router Invalidation → Fresh Data
```
Updates round-trip through the server and refresh the client state.

**3. Server → Multiple Clients (Broadcasting)**
```
Server State Change → WebSocket/SSE → All Connected Clients → UI Updates
```
Changes can propagate to all connected clients for real-time collaboration.

### Why Server Functions vs Traditional APIs?

**Traditional API Development:**
- Separate client and server codebases
- Manual type synchronization
- Complex state management
- Boilerplate HTTP handling
- API versioning challenges

**Server Function Development:**
- Unified codebase with shared types
- Automatic client-server coordination  
- Direct function calls from client
- Built-in type safety
- No API versioning (functions evolve together)

### Scaling Patterns

**1. Database Integration**
```tsx
const getUsers = createServerFn({ method: 'GET' }).handler(async () => {
  const users = await db.user.findMany()
  return users
})

const createUser = createServerFn({ method: 'POST' })
  .validator(userSchema)
  .handler(async ({ data }) => {
    const user = await db.user.create({ data })
    return user
  })
```

**2. Authentication**
```tsx
const getCurrentUser = createServerFn({ method: 'GET' }).handler(async () => {
  const session = await getServerSession()
  if (!session) throw new Error('Unauthorized')
  return session.user
})

const updateProfile = createServerFn({ method: 'POST' })
  .validator(profileSchema)
  .handler(async ({ data }) => {
    const user = await getCurrentUser()
    return await db.user.update({
      where: { id: user.id },
      data
    })
  })
```

**3. Background Jobs**
```tsx
const processReport = createServerFn({ method: 'POST' })
  .validator(reportSchema)
  .handler(async ({ data }) => {
    // Immediate response
    const job = await jobQueue.add('generate-report', data)
    
    // Background processing happens separately
    return { jobId: job.id, status: 'processing' }
  })

const getJobStatus = createServerFn({ method: 'GET' })
  .validator(z.object({ jobId: z.string() }))
  .handler(async ({ data }) => {
    return await jobQueue.getJob(data.jobId)
  })
```

### Further Exploration

Try these experiments to deepen your understanding:

1. **Persistent State**: Replace the file-based storage with a database (SQLite, PostgreSQL) to see how server functions integrate with databases.

2. **Multi-User State**: Add user sessions and make each user have their own counter value.

3. **Real-time Updates**: Implement WebSocket or Server-Sent Events to broadcast counter changes to all connected clients.

4. **Form Integration**: Build a more complex form that collects user input and persists it via server functions.

5. **Error Handling**: Add comprehensive error handling that gracefully handles server failures and network issues.

The counter example demonstrates the fundamental shift from "building APIs" to "building functions" - a mental model that scales from simple interactions to complex full-stack applications while maintaining the simplicity and type safety that makes TanStack Start powerful.