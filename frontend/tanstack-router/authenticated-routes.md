# Authenticated Routes: Router-Level Access Control

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/authenticated-routes)**

## The Core Concept: Why This Example Exists

**The Problem:** Most applications need access control - certain pages should only be accessible to logged-in users, and the login/logout flow needs to be seamless. Traditional approaches often involve sprinkling authentication checks throughout components, creating maintenance headaches and potential security gaps. Users expect to be redirected back to their intended destination after logging in, and the app needs to handle both authenticated and unauthenticated states gracefully.

**The TanStack Solution:** TanStack Router treats authentication as a routing concern, not just a component concern. Instead of checking authentication inside components, you define authentication requirements at the route level using `beforeLoad` hooks. Think of it like having a security guard at the entrance to each section of a building - the guard checks credentials before allowing entry, rather than checking after someone is already inside.

This approach creates a declarative, type-safe authentication system where routes themselves define their access requirements, and the router handles redirects, context passing, and state management automatically.

---

## Practical Walkthrough: Code Breakdown

### The Authentication Context (`auth.tsx:12-63`)

```tsx
export interface AuthContext {
  isAuthenticated: boolean
  login: (username: string) => Promise<void>
  logout: () => Promise<void>
  user: string | null
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = React.useState<string | null>(getStoredUser())
  const isAuthenticated = !!user

  const login = React.useCallback(async (username: string) => {
    await sleep(500)
    setStoredUser(username)
    setUser(username)
  }, [])

  const logout = React.useCallback(async () => {
    await sleep(250)
    setStoredUser(null)
    setUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}
```

This establishes the authentication foundation using React Context. Key insights:

- **Simple state management**: Authentication state is just a user value - null means unauthenticated
- **Persistent sessions**: Uses localStorage to maintain login state across browser sessions
- **Async operations**: Login/logout operations are async, simulating real API calls
- **Interface-driven**: The `AuthContext` interface defines the contract for authentication

### Router Context Integration (`main.tsx:10-28`)

```tsx
const router = createRouter({
  routeTree,
  context: {
    auth: undefined!, // This will be set after we wrap the app in an AuthProvider
  },
})

function InnerApp() {
  const auth = useAuth()
  return <RouterProvider router={router} context={{ auth }} />
}

function App() {
  return (
    <AuthProvider>
      <InnerApp />
    </AuthProvider>
  )
}
```

This demonstrates the crucial pattern of making authentication available to routes:

1. **Router context declaration**: The router is configured to expect an `auth` context
2. **Context injection**: The actual auth state is passed via the `context` prop
3. **Provider wrapping**: The AuthProvider wraps the entire app, ensuring auth state is available

The nested component structure (`App` → `AuthProvider` → `InnerApp`) ensures the auth context exists before the router tries to use it.

### Route-Level Access Control (`routes/_auth.tsx:7-19`)

```tsx
export const Route = createFileRoute('/_auth')({
  beforeLoad: ({ context, location }) => {
    if (!context.auth.isAuthenticated) {
      throw redirect({
        to: '/login',
        search: {
          redirect: location.href,
        },
      })
    }
  },
  component: AuthLayout,
})
```

This is the heart of TanStack Router's authentication approach:

- **beforeLoad hook**: Runs before the route component loads, perfect for access control
- **Context access**: The auth context is available as `context.auth`
- **Redirect on failure**: Unauthenticated users are redirected to login
- **Return URL preservation**: The current location is passed as a search parameter for post-login redirect

The `_auth` route is a pathless layout - it doesn't create a URL segment but provides authentication protection for all its child routes.

### Smart Login Route (`routes/login.tsx:12-22`)

```tsx
export const Route = createFileRoute('/login')({
  validateSearch: z.object({
    redirect: z.string().optional().catch(''),
  }),
  beforeLoad: ({ context, search }) => {
    if (context.auth.isAuthenticated) {
      throw redirect({ to: search.redirect || fallback })
    }
  },
  component: LoginComponent,
})
```

The login route demonstrates bidirectional authentication logic:

- **Already authenticated**: If user is logged in, redirect them away from login
- **Search validation**: Uses Zod to validate the `redirect` parameter type-safely
- **Flexible redirection**: After login, users go to their intended destination or a fallback

### The Login Flow (`routes/login.tsx:33-56`)

```tsx
const onFormSubmit = async (evt: React.FormEvent<HTMLFormElement>) => {
  setIsSubmitting(true)
  try {
    evt.preventDefault()
    const data = new FormData(evt.currentTarget)
    const username = data.get('username')?.toString()
    
    await auth.login(username)
    await router.invalidate()
    await sleep(1) // Wait for auth state to update
    await navigate({ to: search.redirect || fallback })
  } finally {
    setIsSubmitting(false)
  }
}
```

This shows the complete login sequence:

1. **Form handling**: Standard form submission with loading states
2. **Authentication call**: Uses the auth context to perform login
3. **Router invalidation**: Tells the router to re-evaluate all routes with new auth state
4. **State synchronization**: Brief wait for state updates to propagate
5. **Smart navigation**: Redirects to intended destination or fallback

### The Logout Flow (`routes/_auth.tsx:26-34`)

```tsx
const handleLogout = () => {
  if (window.confirm('Are you sure you want to logout?')) {
    auth.logout().then(() => {
      router.invalidate().finally(() => {
        navigate({ to: '/' })
      })
    })
  }
}
```

The logout process demonstrates state cleanup:

1. **User confirmation**: Prevents accidental logouts
2. **Auth state clearing**: Uses auth context to clear login state
3. **Router invalidation**: Forces re-evaluation of route access
4. **Safe navigation**: Redirects to a public route

---

## Mental Model: Thinking in Authenticated Routing

### Routes as Security Boundaries

Traditional authentication often looks like this:
```tsx
function Dashboard() {
  const { isAuthenticated } = useAuth()
  
  if (!isAuthenticated) {
    return <Redirect to="/login" />
  }
  
  return <DashboardContent />
}
```

TanStack Router authentication looks like this:
```tsx
const dashboardRoute = createRoute({
  beforeLoad: ({ context }) => {
    if (!context.auth.isAuthenticated) {
      throw redirect({ to: '/login' })
    }
  },
  component: DashboardContent, // Always authenticated when this renders
})
```

The mental shift is from "check inside components" to "check at route boundaries." Routes become security checkpoints rather than components becoming security-aware.

### The Authentication Route Tree

With the `_auth` pathless layout, your route structure creates natural security boundaries:

```
RootRoute (public)
├── IndexRoute (/) → public
├── LoginRoute (/login) → redirects if authenticated
├── AuthLayout (_auth) → requires authentication
│   ├── DashboardRoute (/dashboard) → protected
│   ├── InvoicesLayout (/invoices) → protected
│   │   ├── InvoicesIndex (/invoices/) → protected
│   │   └── InvoiceRoute (/invoices/:id) → protected
```

Any route nested under `_auth` automatically inherits authentication requirements. Adding new protected routes is as simple as placing them under the auth layout.

### Context as the Single Source of Truth

The router context pattern creates a "single source of truth" for authentication:

```tsx
// Anywhere in your route tree, this is always current
const { auth } = useRouteContext()

// In components, this matches the router context
const auth = useAuth()
```

Both hooks return the same auth state because the router context is populated from the React context. This ensures that route-level and component-level authentication logic never get out of sync.

### Type Safety Across Authentication States

TanStack Router provides complete type safety for authenticated routes:

```tsx
// TypeScript knows this route requires authentication
<Link to="/dashboard">Dashboard</Link>

// TypeScript prevents navigation to protected routes from unauthenticated contexts
// (if you've configured your types properly)
```

The type system can even distinguish between authenticated and unauthenticated route contexts, preventing bugs at compile time.

### The Redirect Preservation Pattern

The `redirect` search parameter pattern creates seamless user experiences:

1. User visits `/dashboard` while unauthenticated
2. Router redirects to `/login?redirect=/dashboard`
3. User logs in successfully
4. App navigates to the original destination: `/dashboard`

This works automatically for any protected route and handles complex URLs with parameters and search strings.

### Further Exploration

Experiment with these authentication patterns:

1. **Role-based access**: Extend the auth context to include user roles, then create routes that check for specific permissions.

2. **Route-specific auth**: Create different authentication requirements for different route sections (e.g., admin routes vs user routes).

3. **Token refresh**: Modify the auth context to handle token expiration and automatic refresh.

4. **Protected data loading**: Combine authentication with route loaders to ensure data is only loaded for authenticated users.

5. **Conditional navigation**: Experiment with navigation that changes based on authentication state - different destinations for logged-in vs logged-out users.

The power of TanStack Router's authentication approach is that security becomes a declarative part of your route structure rather than imperative code scattered throughout your components. When authentication is handled at the routing level, it becomes impossible to accidentally render protected content to unauthenticated users.