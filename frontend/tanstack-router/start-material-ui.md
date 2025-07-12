# Material-UI with TanStack Start: Enterprise Design System Integration

> **🔗 [View Example Source](https://github.com/TanStack/router/tree/db8ae23adcaa66db1f31446bfbed943e7a7069f5/examples/react/start-material-ui)**

## The Core Concept: Why This Example Exists

**The Problem:** Integrating comprehensive design systems like Material-UI with modern React routing can be challenging. Traditional approaches often result in conflicts between the router's link components and the design system's navigation patterns. CSS-in-JS solutions need proper SSR hydration, theming requires careful provider setup, and maintaining design consistency across routes becomes complex without proper abstractions.

**The TanStack Solution:** TanStack Start provides seamless integration with Material-UI through custom link components and SSR-compatible provider patterns. This example demonstrates how to build production-ready applications that combine TanStack Router's powerful navigation with Material-UI's comprehensive component library and theming system.

You'll learn to create custom link components that maintain Material-UI's design language while leveraging TanStack Router's type safety and performance optimizations. This pattern works with any design system, but Material-UI showcases the complexity of integrating CSS-in-JS, theming, and custom components.

---

## Practical Walkthrough: Code Breakdown

### SSR-Compatible Provider Setup (`routes/__root.tsx:32-43`)

```tsx
function Providers({ children }: { children: React.ReactNode }) {
  const emotionCache = createCache({ key: 'css' })

  return (
    <CacheProvider value={emotionCache}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {children}
      </ThemeProvider>
    </CacheProvider>
  )
}
```

This provider setup handles the complexities of CSS-in-JS with SSR:

**Emotion Cache**: Creates a consistent CSS injection strategy for server and client
**Theme Provider**: Makes Material-UI theme available throughout the application
**CSS Baseline**: Normalizes browser default styles for consistent rendering
**SSR Compatibility**: Ensures styles render correctly on both server and client

### Font Loading Strategy (`routes/__root.tsx:18-20`)

```tsx
export const Route = createRootRoute({
  head: () => ({
    links: [{ rel: 'stylesheet', href: fontsourceVariableRobotoCss }],
  }),
  component: RootComponent,
})
```

**Fontsource Integration**: Variable font loading through CSS URL imports
**Head Management**: TanStack Start automatically injects fonts into document head
**Performance**: Variable fonts reduce file size while maintaining design fidelity
**SSR Ready**: Fonts load on server-side rendering for immediate display

### Custom Link Component (`components/CustomLink.tsx:11-19`)

```tsx
const MUILinkComponent = React.forwardRef<HTMLAnchorElement, MUILinkProps>(
  (props, ref) => <Link ref={ref} {...props} />,
)

const CreatedLinkComponent = createLink(MUILinkComponent)

export const CustomLink: LinkComponent<typeof MUILinkComponent> = (props) => {
  return <CreatedLinkComponent preload={'intent'} {...props} />
}
```

This pattern bridges TanStack Router with Material-UI components:

**`createLink` Function**: Wraps any component to work with TanStack Router's navigation
**Ref Forwarding**: Maintains proper DOM references for Material-UI's styling system
**Type Safety**: Full TypeScript support for both router props and Material-UI props
**Default Preloading**: Optimizes navigation with intent-based prefetching

### Button Link Integration (`components/CustomButtonLink.tsx:11-22`)

```tsx
const MUIButtonLinkComponent = React.forwardRef<
  HTMLAnchorElement,
  MUIButtonLinkProps
>((props, ref) => <Button ref={ref} component="a" {...props} />)

const CreatedButtonLinkComponent = createLink(MUIButtonLinkComponent)

export const CustomButtonLink: LinkComponent<typeof MUIButtonLinkComponent> = (
  props,
) => {
  return <CreatedButtonLinkComponent preload={'intent'} {...props} />
}
```

**Component Polymorphism**: Material-UI's `component="a"` prop transforms Button into an anchor
**Navigation Integration**: Buttons now work seamlessly with TanStack Router
**Consistent API**: Same interface as regular links but with button styling
**Accessibility**: Maintains proper semantic meaning and keyboard navigation

### Styled Component with Router (`components/Header.tsx:4-8`)

```tsx
const StyledCustomLink = styled(CustomLink)(
  ({ theme }) => css`
    color: ${theme.palette.common.white};
  `,
)
```

**Theme Integration**: Direct access to Material-UI theme in styled components
**CSS-in-JS**: Emotion's `css` function provides optimal performance
**Router Compatibility**: Styled components work perfectly with custom link components
**Type Safety**: Full TypeScript support for theme properties

### Theme Configuration (`setup/theme.ts:3-7`)

```tsx
export const theme = createTheme({
  typography: {
    fontFamily: "'Roboto Variable', sans-serif",
  },
})
```

**Variable Font Support**: Configures Material-UI to use loaded variable fonts
**Extensible**: Easy to add custom colors, spacing, and component overrides
**Consistent**: Single source of truth for design tokens across the application

---

## Mental Model: Design System Integration Patterns

### The Component Bridge Strategy

Think of TanStack Router and Material-UI as two sophisticated systems that need bridges to communicate:

```
TanStack Router System          Material-UI System
├── Link Component              ├── Link Component
├── Type Safety                 ├── Theme System
├── Navigation Logic            ├── CSS-in-JS
└── Route Parameters            └── Component Library

              ↕️ Bridge Layer ↕️
        Custom Link Components
        Type-Safe Integration
        Shared Props Interface
```

**Without Bridges**: Components conflict and lose functionality
```tsx
// Broken: Material-UI Link doesn't know about routes
<MUILink href="/about">About</MUILink>

// Broken: TanStack Link doesn't have Material-UI styling
<RouterLink to="/about">About</RouterLink>
```

**With Bridges**: Seamless integration with full feature sets
```tsx
// Perfect: Best of both worlds
<CustomLink to="/about" variant="h6" color="primary">
  About
</CustomLink>
```

### Provider Architecture Strategy

Material-UI and TanStack Start both use provider patterns, creating a layered architecture:

```
<RootDocument>
  <CacheProvider>           ← Emotion CSS cache
    <ThemeProvider>         ← Material-UI theme
      <CssBaseline />       ← Style normalization
      <RouterProvider>      ← TanStack Router
        <AppRoutes />       ← Your application
      </RouterProvider>
    </ThemeProvider>
  </CacheProvider>
</RootDocument>
```

**Layer Responsibilities**:
1. **Cache Provider**: Manages CSS injection order and deduplication
2. **Theme Provider**: Provides design tokens and component customizations
3. **CSS Baseline**: Normalizes browser differences
4. **Router Provider**: Handles navigation state and route matching

### Custom Component Creation Patterns

**Basic Link Wrapper**:
```tsx
const CustomLink = createLink(MUILink)
```

**Enhanced Link with Defaults**:
```tsx
const CustomLink = (props) => {
  const CreatedLink = createLink(MUILink)
  return <CreatedLink preload="intent" {...props} />
}
```

**Polymorphic Button Link**:
```tsx
const ButtonLink = createLink(
  React.forwardRef((props, ref) => (
    <Button ref={ref} component="a" {...props} />
  ))
)
```

**Styled Link Component**:
```tsx
const StyledLink = styled(createLink(MUILink))`
  && {
    color: ${({ theme }) => theme.palette.primary.main};
    text-decoration: none;
    
    &:hover {
      text-decoration: underline;
    }
  }
`
```

### Theme Integration Strategies

**Basic Theme Setup**:
```tsx
const theme = createTheme({
  palette: {
    primary: {
      main: '#1976d2',
    },
  },
})
```

**Router-Aware Theme**:
```tsx
const theme = createTheme({
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          // Custom styles for router buttons
          '&.router-link-active': {
            backgroundColor: 'primary.dark',
          },
        },
      },
    },
  },
})
```

**Dynamic Theme with Router State**:
```tsx
function App() {
  const location = useRouterState({ select: s => s.location })
  const isDarkRoute = location.pathname.startsWith('/dark')
  
  const theme = createTheme({
    palette: {
      mode: isDarkRoute ? 'dark' : 'light',
    },
  })
  
  return <ThemeProvider theme={theme}>...</ThemeProvider>
}
```

### SSR and Hydration Patterns

**Server-Side Rendering Flow**:
```tsx
// 1. Server creates emotion cache
const serverCache = createCache({ key: 'css' })

// 2. Components render with styles
<CacheProvider value={serverCache}>
  <App />
</CacheProvider>

// 3. Styles extracted and sent to client
const css = extractCritical(html)

// 4. Client hydrates with same cache
const clientCache = createCache({ key: 'css' })
```

**Preventing Style Flash**:
```tsx
// Critical CSS inlined in document head
<style dangerouslySetInnerHTML={{ __html: css.css }} />

// Non-critical CSS loaded asynchronously
<link rel="preload" href="/styles.css" as="style" />
```

### Performance Optimization Patterns

**Code Splitting Material-UI**:
```tsx
// Split theme and components
const theme = lazy(() => import('./theme'))
const AppBar = lazy(() => import('@mui/material/AppBar'))

// Preload on intent
<CustomLink to="/dashboard" onMouseEnter={() => import('./Dashboard')}>
  Dashboard
</CustomLink>
```

**Tree Shaking Optimization**:
```tsx
// Bad: Imports entire library
import * as MUI from '@mui/material'

// Good: Import only what you need
import { Button } from '@mui/material/Button'
import { AppBar } from '@mui/material/AppBar'
```

**Bundle Analysis**:
```bash
# Analyze Material-UI impact
npm run build -- --analyze

# Optimize imports
npm install @mui/material-nextjs
```

### Further Exploration

Try these experiments to master design system integration:

1. **Add Active Link Styling**: Create custom link components that show active states using Material-UI's styling system.

2. **Theme Switching**: Implement dark/light mode that persists across navigation and integrates with TanStack Router's search params.

3. **Custom Form Components**: Build form components that combine Material-UI inputs with TanStack Router's search param validation.

4. **Responsive Navigation**: Create a responsive drawer navigation that maintains router state and Material-UI animations.

5. **Icon Integration**: Set up Material-UI icons to work seamlessly with router links and maintain proper accessibility.

This pattern of creating bridge components works with any design system - whether it's Chakra UI, Ant Design, or custom component libraries. The key is understanding how to preserve both the router's navigation capabilities and the design system's styling and behavior patterns.