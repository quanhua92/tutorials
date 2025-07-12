# Search Validator Adapters: Type-Safe URL Parameters Across Validation Libraries

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/search-validator-adapters)**

## The Core Concept: Why This Example Exists

**The Problem:** Modern applications rely heavily on URL search parameters for filtering, sorting, pagination, and maintaining application state. However, these parameters arrive as strings from the URL and need validation, type conversion, and default values. Different teams prefer different validation libraries (Zod, Valibot, ArkType), but want consistent type safety and developer experience.

**The TanStack Solution:** TanStack Router provides **validator adapters** - a plugin system that allows any validation library to integrate seamlessly with the router's type system. Think of it like having different languages all speaking to the same translation service - whether you use Zod's object schemas, Valibot's function chains, or ArkType's type syntax, the router understands them all.

This example demonstrates three popular validation libraries working identically with the router, showcasing how validation choice becomes a team preference rather than a technical constraint.

---

## Practical Walkthrough: Code Breakdown

### Zod Integration (`users/zod.index.tsx:33-37`)

```tsx
export const Route = createFileRoute({
  validateSearch: zodValidator(
    z.object({
      search: fallback(z.string().optional(), undefined),
    }),
  ),
  // ... rest of route config
})
```

Zod integration uses the `zodValidator` adapter to wrap standard Zod schemas. Key features:

- **zodValidator**: Adapter function that translates Zod schemas into router validators
- **fallback**: Provides default values when validation fails or parameters are missing
- **z.string().optional()**: Defines the search parameter as an optional string

The result is fully typed search parameters that your components can use safely.

### Valibot Integration (`users/valibot.index.tsx:29-32`)

```tsx
export const Route = createFileRoute({
  validateSearch: v.object({
    search: v.fallback(v.optional(v.string(), ''), ''),
  }),
  // ... rest of route config
})
```

Valibot works directly with the router without an adapter, demonstrating native integration:

- **v.object**: Creates an object schema
- **v.fallback**: Provides default values with functional composition
- **v.optional**: Makes the parameter optional with a default
- **v.string()**: Validates as string type

Valibot's functional approach integrates naturally with TanStack Router's validation system.

### ArkType Integration (`users/arktype.index.tsx:31-36`)

```tsx
const search = type({
  search: 'string = ""',
})

export const Route = createFileRoute({
  validateSearch: search,
  // ... rest of route config
})
```

ArkType uses TypeScript-like syntax that reads almost like documentation:

- **type()**: Creates a type definition using ArkType's syntax
- **'string = ""'**: Defines a string with a default value of empty string
- Direct assignment to `validateSearch` without wrapper

The syntax is remarkably concise while maintaining full type safety.

### Consistent Usage Pattern (`users/zod.index.tsx:11-13`)

```tsx
const search = Route.useSearch({
  select: (search) => search.search ?? '',
})
```

Regardless of which validator you choose, the usage in components remains identical:

- **Route.useSearch()**: Hook to access validated search parameters
- **select**: Optional transformation of the search object
- **Full type safety**: TypeScript knows the exact shape of search parameters

### Data Loading Integration (`users/zod.index.tsx:38-43`)

```tsx
loaderDeps: (opt) => ({ search: opt.search }),
loader: (opt) => {
  opt.context.queryClient.ensureQueryData(
    usersQueryOptions(opt.deps.search.search ?? ''),
  )
},
```

All validators integrate seamlessly with the router's data loading system:

- **loaderDeps**: Declares which search parameters the loader depends on
- **Automatic reloading**: When search parameters change, the loader reruns
- **Type safety**: The loader receives fully typed and validated parameters

### Component Implementation (`users/zod.index.tsx:16-29`)

```tsx
return (
  <>
    <Header title="Zod" />
    <Content>
      <Search
        search={search}
        onChange={(search) => navigate({ search: { search }, replace: true })}
      />
      <React.Suspense>
        <Users search={search} />
      </React.Suspense>
    </Content>
  </>
)
```

The component code is identical across all three validation approaches:
- Same props interface
- Same navigation patterns  
- Same data flow
- Same TypeScript experience

---

## Mental Model: Thinking in Validation Adapters

### The Adapter Pattern

Think of validation adapters like electrical outlets - different countries use different plug shapes, but they all deliver the same electricity. The adapter ensures compatibility:

```
URL Params (strings) → Validator Library → Router Type System → Your Components
     ↓                      ↓                    ↓                ↓
"?search=john"     Zod/Valibot/ArkType    { search: string }   Typed Props
```

### Validation Philosophy Comparison

**Zod: Schema-First**
```tsx
z.object({
  search: fallback(z.string().optional(), undefined),
  page: z.number().int().positive().default(1),
  sortBy: z.enum(['name', 'date', 'status']).default('name')
})
```
- Object-oriented schema definition
- Rich ecosystem of refinements and transformations
- Explicit error handling with detailed messages

**Valibot: Function-First**
```tsx
v.object({
  search: v.fallback(v.optional(v.string()), ''),
  page: v.fallback(v.pipe(v.string(), v.transform(Number), v.integer(), v.minValue(1)), 1),
  sortBy: v.fallback(v.picklist(['name', 'date', 'status']), 'name')
})
```
- Functional composition approach
- Smaller bundle size through tree-shaking
- Pipeline-style transformations

**ArkType: Type-First**
```tsx
type({
  search: 'string = ""',
  page: 'integer >= 1 = 1',
  sortBy: '"name" | "date" | "status" = "name"'
})
```
- TypeScript-native syntax
- Extremely concise definitions
- Compile-time optimizations

### When to Choose Each Validator

**Choose Zod when:**
- You want the most mature ecosystem
- You need complex custom validations
- Your team prefers object-oriented APIs
- You're migrating from other schema validators

**Choose Valibot when:**
- Bundle size is critical
- You prefer functional programming patterns
- You want the latest validation innovations
- You need custom pipeline transformations

**Choose ArkType when:**
- You want the most concise syntax
- Performance is paramount
- You prefer TypeScript-native approaches
- You're building type-heavy applications

### Validation Strategies

**1. Progressive Enhancement**
```tsx
// Start simple
validateSearch: z.object({
  q: z.string().optional()
})

// Add complexity as needed
validateSearch: z.object({
  q: z.string().min(2).max(100).optional(),
  category: z.enum(['all', 'posts', 'users']).default('all'),
  page: z.coerce.number().int().positive().default(1),
  sortBy: z.enum(['relevance', 'date', 'popularity']).default('relevance')
})
```

**2. Shared Schemas**
```tsx
// Define once, use everywhere
export const searchParamsSchema = z.object({
  filters: z.object({
    status: z.enum(['active', 'inactive', 'pending']).optional(),
    dateRange: z.object({
      start: z.string().datetime().optional(),
      end: z.string().datetime().optional()
    }).optional()
  }).optional()
})

// Use in multiple routes
export const Route = createFileRoute('/users/')({
  validateSearch: searchParamsSchema,
})
```

**3. Migration Strategy**
```tsx
// Gradually migrate from one validator to another
const legacyValidator = z.object({ /* old schema */ })
const newValidator = v.object({ /* new schema */ })

// Use feature flags or route-by-route migration
validateSearch: useNewValidator ? newValidator : zodValidator(legacyValidator)
```

### Type Safety Benefits

All three approaches provide the same TypeScript benefits:

```tsx
// Fully typed search parameters
const search = Route.useSearch() // TypeScript knows the exact shape

// Type-safe navigation
navigate({ 
  search: { 
    search: 'john',    // ✅ Valid
    page: 1,          // ✅ Valid
    invalid: 'nope'   // ❌ TypeScript error
  }
})

// Compile-time validation
<Link search={{ search: 123 }} /> // ❌ TypeScript error: number not assignable to string
```

### Further Exploration

Try these experiments to deepen your understanding:

1. **Complex Validation**: Add multiple search parameters with different types (numbers, enums, arrays) using each validator.

2. **Error Handling**: Implement custom error boundaries that handle validation failures gracefully.

3. **Performance Testing**: Compare bundle sizes and runtime performance across the three validators.

4. **Migration Path**: Build a route that accepts both old and new search parameter formats during a gradual migration.

5. **Custom Adapters**: Create an adapter for a different validation library (like Joi or Yup) following the same pattern.

The validator adapter system transforms validation from a architectural constraint into a team preference, allowing you to choose the right tool while maintaining consistent type safety and developer experience across your entire application.