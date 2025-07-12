# TanStack Start Basic Auth: Full-Stack Authentication with Database Integration

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/start-basic-auth)**

## The Core Concept: Why This Example Exists

**The Problem:** Building authentication systems traditionally requires coordinating between frontend forms, backend APIs, database schemas, session management, password hashing, route protection, and user experience flows. Each piece must be implemented separately and carefully integrated, often resulting in security vulnerabilities, inconsistent user experiences, and complex maintenance overhead.

**The TanStack Solution:** TanStack Start enables **unified authentication architecture** where database operations, session management, route protection, and user interface all work together seamlessly. Think of it like having authentication as a first-class feature of your application framework rather than something you bolt on afterward.

This example demonstrates complete authentication flows including user registration, login/logout, session management with Prisma database integration, protected routes with automatic redirects, and server-side authentication checks that work across the entire application.

---

## Practical Walkthrough: Code Breakdown

### Database Schema and Integration (`prisma/schema.prisma`)

```prisma
model User {
  id       String @id @default(cuid())
  email    String @unique
  password String
  
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
}
```

The foundation is a simple but complete user model:

- **Unique email**: Enforced at database level for login identity
- **Hashed passwords**: Never stored in plain text (handled by server functions)
- **CUID identifiers**: Collision-resistant, URL-safe user IDs
- **Timestamps**: Automatic tracking of account creation and updates

### Server-Side Session Management (`utils/session.ts`)

```tsx
export const useAppSession = () => {
  return getWebRequest().getCookieSession({
    name: 'app-session',
    secret: process.env.SESSION_SECRET || 'dev-secret',
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    maxAge: 1000 * 60 * 60 * 24 * 30, // 30 days
  })
}
```

Server-side session handling provides:

- **Secure cookies**: HTTP-only, secure in production
- **Long-lived sessions**: 30-day expiration for good UX
- **Environment-based configuration**: Different security settings for dev/prod
- **Built-in encryption**: Session data is automatically encrypted

### Authentication Route Protection (`routes/__root.tsx:32-38`)

```tsx
export const Route = createRootRoute({
  beforeLoad: async () => {
    const user = await fetchUser()
    return { user }
  },
  // ... rest of route config
})

const fetchUser = createServerFn({ method: 'GET' }).handler(async () => {
  const session = await useAppSession()
  
  if (!session.data.userEmail) {
    return null
  }
  
  return { email: session.data.userEmail }
})
```

Root-level authentication provides:

- **Global user context**: Every route knows if user is authenticated
- **Server-side session reading**: Authentication state comes from secure cookies
- **Automatic injection**: User data flows to all child routes
- **Type safety**: Components know the shape of user data

### Protected Route Implementation (`routes/_authed.tsx`)

```tsx
export const Route = createFileRoute('/_authed')({
  beforeLoad: ({ context }) => {
    if (!context.user) {
      throw redirect({
        to: '/login',
        search: {
          redirect: location.href,
        },
      })
    }
  },
  component: AuthedLayout,
})
```

Protected routes use pathless layout pattern:

- **beforeLoad guard**: Runs before any child routes load
- **Automatic redirects**: Unauthenticated users sent to login
- **Return URL preservation**: Current location saved for post-login redirect
- **Layout inheritance**: Protected routes can share common UI

### Registration Flow (`routes/signup.tsx`)

```tsx
const signupFn = createServerFn({ method: 'POST' })
  .validator(signupSchema)
  .handler(async ({ data }) => {
    const existingUser = await prisma.user.findUnique({
      where: { email: data.email }
    })
    
    if (existingUser) {
      throw new Error('User already exists')
    }
    
    const hashedPassword = await bcrypt.hash(data.password, 10)
    
    const user = await prisma.user.create({
      data: {
        email: data.email,
        password: hashedPassword,
      }
    })
    
    const session = await useAppSession()
    await session.update({ userEmail: user.email })
    
    return { success: true }
  })
```

Secure registration includes:

- **Input validation**: Zod schema ensures proper email/password format
- **Duplicate prevention**: Database uniqueness constraint prevents duplicate accounts
- **Password hashing**: bcrypt with salt rounds for security
- **Automatic login**: New users are immediately signed in
- **Session creation**: Secure cookie session starts immediately

### Login Flow with Redirect Handling (`routes/login.tsx`)

```tsx
const loginFn = createServerFn({ method: 'POST' })
  .validator(loginSchema)
  .handler(async ({ data }) => {
    const user = await prisma.user.findUnique({
      where: { email: data.email }
    })
    
    if (!user || !await bcrypt.compare(data.password, user.password)) {
      throw new Error('Invalid email or password')
    }
    
    const session = await useAppSession()
    await session.update({ userEmail: user.email })
    
    return { success: true }
  })

// In component
React.useEffect(() => {
  if (loginMutation.status === 'success') {
    router.navigate({
      to: redirect || '/',
    })
  }
}, [loginMutation.status, redirect])
```

Comprehensive login flow:

- **Credential verification**: Secure password comparison with bcrypt
- **Timing attack protection**: Same response time for invalid users
- **Session establishment**: Cookie session created on successful login
- **Redirect handling**: Users return to their intended destination
- **Error feedback**: Clear messaging for failed attempts

### Logout Implementation (`routes/logout.tsx`)

```tsx
const logoutFn = createServerFn({ method: 'POST' }).handler(async () => {
  const session = await useAppSession()
  await session.clear()
  
  return redirect({
    to: '/',
  })
})

export const Route = createFileRoute('/logout')({
  beforeLoad: () => logoutFn(),
})
```

Clean logout process:

- **Session clearing**: All session data removed from server
- **Automatic redirect**: Users sent to public area
- **beforeLoad execution**: Logout happens before component renders
- **Cookie cleanup**: Browser cookies are invalidated

### Full-Stack User Experience (`routes/__root.tsx:123-133`)

```tsx
{user ? (
  <>
    <span className="mr-2">{user.email}</span>
    <Link to="/logout">Logout</Link>
  </>
) : (
  <Link to="/login">Login</Link>
)}
```

Seamless UI integration:

- **Conditional rendering**: UI adapts based on authentication state
- **User context**: Authenticated user data available throughout app
- **Consistent navigation**: Login/logout links in global navigation
- **Type safety**: TypeScript knows when user is available

---

## Mental Model: Thinking in Full-Stack Authentication

### The Authentication Stack

Think of TanStack Start authentication as a unified stack where each layer automatically coordinates with the others:

```
┌─ UI Layer ──────────────────────────────┐
│  Login forms, protected components,      │
│  conditional rendering                   │
│  ┌─ Router Layer ────────────────────┐  │
│  │  Route guards, redirects,          │  │
│  │  authentication context           │  │
│  │  ┌─ Session Layer ──────────────┐ │  │
│  │  │  Secure cookies, session     │ │  │
│  │  │  management, CSRF protection │ │  │
│  │  │  ┌─ Database Layer ───────┐  │ │  │
│  │  │  │  User storage, password │  │ │  │
│  │  │  │  hashing, data integrity│  │ │  │
│  │  │  └────────────────────────┘  │ │  │
│  │  └────────────────────────────── │ │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

### Authentication Patterns

**1. Server-First Authentication**
```tsx
// Authentication state comes from the server
const fetchUser = createServerFn({ method: 'GET' }).handler(async () => {
  const session = await useAppSession()
  return session.data.userEmail ? { email: session.data.userEmail } : null
})

// Client components receive authenticated state
function UserProfile() {
  const { user } = Route.useRouteContext() // Always current, from server
  if (!user) return <LoginPrompt />
  return <div>Welcome, {user.email}!</div>
}
```

**2. Route-Level Protection**
```tsx
// Protect entire route trees
const adminRoutes = createRoute({
  id: '_admin',
  beforeLoad: ({ context }) => {
    if (!context.user?.isAdmin) {
      throw redirect({ to: '/unauthorized' })
    }
  }
}).addChildren([
  adminDashboard,
  userManagement,
  systemSettings
])
```

**3. Granular Permissions**
```tsx
// Component-level permission checks
function AdminPanel() {
  const { user } = Route.useRouteContext()
  
  if (!user?.permissions.includes('admin')) {
    return <div>Insufficient permissions</div>
  }
  
  return <AdminDashboard />
}

// Server function permission checks
const deleteUser = createServerFn({ method: 'DELETE' })
  .validator(z.object({ userId: z.string() }))
  .handler(async ({ data }) => {
    const session = await useAppSession()
    const currentUser = await getCurrentUser(session)
    
    if (!currentUser.permissions.includes('delete_users')) {
      throw new Error('Insufficient permissions')
    }
    
    return await prisma.user.delete({ where: { id: data.userId } })
  })
```

### Security Considerations

**1. Password Security**
```tsx
// Always hash passwords with salt
const hashedPassword = await bcrypt.hash(password, 12) // High salt rounds

// Never send passwords to client
const userForClient = {
  id: user.id,
  email: user.email,
  // password: user.password // ❌ Never include password
}
```

**2. Session Security**
```tsx
// Use secure session configuration
const session = getCookieSession({
  name: 'app-session',
  secret: process.env.SESSION_SECRET, // Must be strong, random secret
  httpOnly: true,                     // Prevents XSS attacks
  secure: process.env.NODE_ENV === 'production', // HTTPS only in production
  sameSite: 'lax',                   // CSRF protection
  maxAge: 1000 * 60 * 60 * 24 * 30   // Reasonable expiration
})
```

**3. Input Validation**
```tsx
// Validate all authentication inputs
const loginSchema = z.object({
  email: z.string().email().min(1),
  password: z.string().min(8).max(100),
})

// Sanitize database queries
const user = await prisma.user.findUnique({
  where: { email: data.email }, // Prisma automatically sanitizes
  select: { id: true, email: true } // Only select needed fields
})
```

### Database Integration Patterns

**1. User Management**
```tsx
// Complete user lifecycle
const createUser = async (userData) => {
  return await prisma.user.create({
    data: {
      ...userData,
      password: await bcrypt.hash(userData.password, 12),
      createdAt: new Date(),
    }
  })
}

const updateUser = async (userId, updates) => {
  return await prisma.user.update({
    where: { id: userId },
    data: {
      ...updates,
      updatedAt: new Date(),
    }
  })
}

const deleteUser = async (userId) => {
  // Soft delete pattern
  return await prisma.user.update({
    where: { id: userId },
    data: { deletedAt: new Date() }
  })
}
```

**2. Session Management**
```tsx
// Database-backed sessions for scalability
model Session {
  id        String   @id @default(cuid())
  userId    String
  user      User     @relation(fields: [userId], references: [id])
  token     String   @unique
  expiresAt DateTime
  createdAt DateTime @default(now())
}

// Server function to create sessions
const createSession = async (userId) => {
  const token = crypto.randomBytes(32).toString('hex')
  const expiresAt = new Date(Date.now() + 30 * 24 * 60 * 60 * 1000) // 30 days
  
  return await prisma.session.create({
    data: { userId, token, expiresAt }
  })
}
```

### Why TanStack Start for Authentication?

Traditional authentication requires:
- Separate frontend and backend auth logic
- Manual session synchronization
- Complex redirect handling
- API endpoint protection
- Cookie management
- Password security implementation

TanStack Start provides:
- Unified client-server authentication code
- Automatic session management
- Built-in redirect handling
- Route-level protection
- Secure cookie sessions
- Type-safe authentication flows

### Further Exploration

Try these experiments to deepen your understanding:

1. **Role-Based Access Control**: Add user roles and permissions to control access to different features.

2. **Multi-Factor Authentication**: Implement TOTP or SMS-based two-factor authentication.

3. **Social Login**: Add OAuth integration with Google, GitHub, or other providers.

4. **Password Reset**: Build a complete password reset flow with email verification.

5. **Account Verification**: Add email verification for new user accounts.

6. **Session Management**: Build an admin panel to view and manage active user sessions.

The TanStack Start authentication example demonstrates how modern full-stack frameworks can eliminate the traditional complexity of authentication by providing unified, type-safe patterns that work seamlessly across the entire application stack.