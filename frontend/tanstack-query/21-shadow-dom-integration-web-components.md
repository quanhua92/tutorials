# Shadow DOM Integration: Web Components

> **Based on**: [`examples/react/shadow-dom`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/shadow-dom)

## The Core Concept: Why This Example Exists

**The Problem:** Modern applications often need to integrate with existing websites, embed widgets in third-party sites, or create truly isolated components that won't conflict with host page styles and scripts. Traditional React applications struggle with style isolation and global state conflicts when embedded in complex environments.

**The Solution:** **Shadow DOM integration with TanStack Query** enables creating fully isolated React applications that can be embedded anywhere while maintaining their own data fetching, caching, and styling. This enables building embeddable widgets, micro-frontends, and library components that work reliably regardless of the host environment.

The key insight: **isolation is key to reusability** - components that manage their own data, styles, and behavior can be embedded in any context without conflicts or dependencies on host page state.

## Practical Walkthrough: Code Breakdown

Let's examine the Shadow DOM patterns from `examples/react/shadow-dom/src/main.tsx`:

### 1. Shadow Root Creation

```tsx
const appRoot = document.getElementById('root')

if (appRoot) {
  const queryClient = new QueryClient()
  const shadowRoot = appRoot.attachShadow({ mode: 'open' })
  const root = ReactDOM.createRoot(shadowRoot)
```

**What's happening:** A Shadow DOM is attached to the host element, creating an isolated DOM tree. React renders into this shadow root instead of the main document tree.

**Why Shadow DOM:** Provides complete style and script isolation. CSS from the host page cannot affect the component, and the component's styles cannot leak out.

### 2. Isolated QueryClient

```tsx
const queryClient = new QueryClient()

root.render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <div style={{ width: '100vw', padding: '30px' }}>
        <h2>Dog Breeds</h2>
        <DogList />
      </div>
    </QueryClientProvider>
  </React.StrictMode>
)
```

**What's happening:** The QueryClient is created within the Shadow DOM scope, ensuring data fetching and caching remain isolated from any other TanStack Query instances on the page.

**Why isolated client:** Prevents cache conflicts and ensures the component's data management doesn't interfere with the host application's data layer.

### 3. DevTools Shadow Integration

```tsx
<ReactQueryDevtools
  initialIsOpen={false}
  buttonPosition="bottom-left"
  shadowDOMTarget={appRoot.shadowRoot!}
/>
```

**What's happening:** React Query DevTools is explicitly configured to work within the Shadow DOM by targeting the shadow root instead of the document root.

**Why shadow target:** DevTools need to render within the isolated environment to access the component's query state and provide proper debugging capabilities.

### 4. Self-Contained Styling

```tsx
<div
  style={{
    width: '100vw',
    padding: '30px',
  }}
>
```

**What's happening:** Styles are applied inline or through style objects rather than external CSS classes, ensuring they work regardless of host page styling.

**Why inline styles:** External stylesheets might not work across Shadow DOM boundaries. Inline styles guarantee consistent appearance.

## Mental Model: Isolated Component Ecosystems

### The Isolation Boundary

```
Host Page Environment:
┌─────────────────────────────────────────┐
│ Host CSS, JS, State                     │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ Shadow DOM Boundary                 │ │
│ │                                     │ │
│ │ ┌─────────────────────────────────┐ │ │
│ │ │ React App                       │ │ │
│ │ │ - QueryClient                   │ │ │
│ │ │ - Component State               │ │ │
│ │ │ - Isolated Styles               │ │ │
│ │ │ - Data Layer                    │ │ │
│ │ └─────────────────────────────────┘ │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

Complete isolation prevents conflicts and dependencies.

### Data Flow in Shadow DOM

```
Component Data Lifecycle:
1. Shadow DOM creates isolated QueryClient
2. Components fetch data independently
3. Cache remains separate from host
4. Data updates don't affect host page
5. Component can be unmounted cleanly
```

### Cross-Boundary Communication

```
Safe Communication Patterns:
Host → Shadow: Props/Attributes
Shadow → Host: Custom Events
Both: Message passing APIs

Avoid:
- Global state sharing
- Direct DOM manipulation
- Style dependencies
- Script dependencies
```

### Why It's Designed This Way: Embeddable Components

Traditional embedding problems:
```
Embed Component → Style Conflicts → Broken Appearance
Embed Component → Script Conflicts → Runtime Errors  
Embed Component → State Conflicts → Unpredictable Behavior
```

Shadow DOM solution:
```
Embed Component → Isolated Environment → Predictable Behavior
```

### Advanced Shadow DOM Patterns

**Multiple Shadow Components**: Multiple isolated components on one page:
```tsx
class QueryWidget extends HTMLElement {
  private queryClient: QueryClient
  private root: Root
  
  constructor() {
    super()
    this.queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          // Widget-specific defaults
          staleTime: 5 * 60 * 1000,
          retry: 2,
        },
      },
    })
  }
  
  connectedCallback() {
    const shadowRoot = this.attachShadow({ mode: 'open' })
    this.root = ReactDOM.createRoot(shadowRoot)
    
    this.root.render(
      <QueryClientProvider client={this.queryClient}>
        <WidgetComponent {...this.getProps()} />
      </QueryClientProvider>
    )
  }
  
  disconnectedCallback() {
    this.root.unmount()
    this.queryClient.clear()
  }
  
  private getProps() {
    return {
      apiKey: this.getAttribute('api-key'),
      theme: this.getAttribute('theme'),
      // Convert HTML attributes to React props
    }
  }
}

customElements.define('query-widget', QueryWidget)
```

**Host Communication**: Safe data exchange:
```tsx
const useShadowCommunication = () => {
  const [hostData, setHostData] = useState<any>(null)
  
  useEffect(() => {
    // Listen for host messages
    const handleMessage = (event: MessageEvent) => {
      if (event.source === window.parent) {
        setHostData(event.data)
      }
    }
    
    window.addEventListener('message', handleMessage)
    return () => window.removeEventListener('message', handleMessage)
  }, [])
  
  const sendToHost = useCallback((data: any) => {
    // Send data to host
    const event = new CustomEvent('widget-data', { 
      detail: data,
      bubbles: true, // Crosses shadow boundary
    })
    document.dispatchEvent(event)
  }, [])
  
  return { hostData, sendToHost }
}
```

**Style Inheritance**: Controlled style adoption:
```tsx
const useShadowStyles = (shadowRoot: ShadowRoot) => {
  useEffect(() => {
    // Adopt specific host styles
    const hostFontFamily = getComputedStyle(document.body).fontFamily
    const hostColorScheme = getComputedStyle(document.body).colorScheme
    
    const styleSheet = new CSSStyleSheet()
    styleSheet.insertRule(`
      :host {
        font-family: ${hostFontFamily};
        color-scheme: ${hostColorScheme};
      }
    `)
    
    shadowRoot.adoptedStyleSheets = [styleSheet]
  }, [shadowRoot])
}
```

**Dynamic Widget Loading**: Load widgets on demand:
```tsx
const useDynamicWidget = () => {
  const loadWidget = useCallback(async (
    containerId: string,
    widgetConfig: WidgetConfig
  ) => {
    const container = document.getElementById(containerId)
    if (!container) return
    
    // Create shadow DOM
    const shadowRoot = container.attachShadow({ mode: 'open' })
    
    // Create isolated query client
    const queryClient = new QueryClient(widgetConfig.queryOptions)
    
    // Load widget code dynamically
    const { WidgetComponent } = await import('./widgets/WidgetComponent')
    
    // Render in shadow DOM
    const root = ReactDOM.createRoot(shadowRoot)
    root.render(
      <QueryClientProvider client={queryClient}>
        <WidgetComponent {...widgetConfig.props} />
      </QueryClientProvider>
    )
    
    return { root, queryClient, cleanup: () => root.unmount() }
  }, [])
  
  return { loadWidget }
}
```

**Cross-Widget State Sync**: Coordinate between widgets:
```tsx
const useCrossWidgetSync = (widgetId: string) => {
  const queryClient = useQueryClient()
  
  useEffect(() => {
    // Listen for cross-widget events
    const handleWidgetSync = (event: CustomEvent) => {
      const { sourceWidget, data, queryKey } = event.detail
      
      if (sourceWidget !== widgetId) {
        // Update local cache with data from other widgets
        queryClient.setQueryData(queryKey, data)
      }
    }
    
    document.addEventListener('widget-sync', handleWidgetSync)
    return () => document.removeEventListener('widget-sync', handleWidgetSync)
  }, [queryClient, widgetId])
  
  const syncToOtherWidgets = useCallback((queryKey: unknown[], data: any) => {
    // Broadcast data to other widgets
    const event = new CustomEvent('widget-sync', {
      detail: { sourceWidget: widgetId, data, queryKey },
      bubbles: true,
    })
    document.dispatchEvent(event)
  }, [widgetId])
  
  return { syncToOtherWidgets }
}
```

### Security and Isolation Best Practices

**Secure Data Handling**: Protect sensitive information:
```tsx
const useSecureQuery = (apiKey: string) => {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: async (data: any) => {
      // Validate API key is from trusted source
      if (!isValidApiKey(apiKey)) {
        throw new Error('Invalid API key')
      }
      
      // Make secure request
      const response = await fetch('/api/secure-endpoint', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${apiKey}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(data),
      })
      
      return response.json()
    },
    onSuccess: (data) => {
      // Don't expose sensitive data to host
      const publicData = sanitizeData(data)
      
      // Update cache with public data only
      queryClient.setQueryData(['public-data'], publicData)
    },
  })
}
```

**Content Security**: Prevent XSS and data leaks:
```tsx
const useSafeContent = () => {
  const sanitizeContent = useCallback((content: string) => {
    // Use DOMPurify or similar to sanitize HTML
    return DOMPurify.sanitize(content)
  }, [])
  
  const validateOrigin = useCallback((event: MessageEvent) => {
    const allowedOrigins = ['https://trusted-domain.com']
    return allowedOrigins.includes(event.origin)
  }, [])
  
  return { sanitizeContent, validateOrigin }
}
```

### Further Exploration

Experiment with Shadow DOM integration:

1. **Performance Impact**: Measure overhead of Shadow DOM isolation
2. **Browser Compatibility**: Test across different browsers and versions
3. **Bundle Size**: Optimize for minimal footprint in host pages
4. **Accessibility**: Ensure Shadow DOM components remain accessible

**Advanced Challenges**:

1. **Micro-Frontend Architecture**: How would you coordinate multiple Shadow DOM micro-frontends?

2. **Theme System**: How would you create a themeable widget system with Shadow DOM?

3. **Analytics Integration**: How would you track user interactions across Shadow DOM boundaries?

4. **Performance Monitoring**: How would you monitor performance of embedded Shadow DOM components?

**Real-World Applications**:
- **Embeddable Widgets**: Chat widgets, payment forms, social media embeds
- **Third-Party Integrations**: Analytics dashboards, booking systems, maps
- **Micro-Frontends**: Independent team-owned components in larger applications
- **White-Label Components**: Reusable components for multiple brands
- **Browser Extensions**: Content scripts that don't interfere with host pages

Shadow DOM integration with TanStack Query enables creating truly portable, reusable components that can be embedded anywhere without conflicts. Understanding these patterns is essential for building modern embeddable applications and component libraries.