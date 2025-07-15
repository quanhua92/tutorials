# React Native: Mobile App Patterns

> **Based on**: [`examples/react/react-native`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/react/react-native)

## The Core Concept: Why This Example Exists

**The Problem:** Mobile applications have unique requirements that web applications don't face: app state changes (background/foreground), network connectivity variations, battery constraints, touch-based interactions, and platform-specific behaviors. Standard TanStack Query setup doesn't handle mobile-specific scenarios like pull-to-refresh, app backgrounding, or network state management.

**The Solution:** TanStack Query's **platform-agnostic design** combined with **React Native-specific integrations** creates robust mobile data management. By hooking into React Native's app state, network info, and navigation systems, you can build mobile apps that handle connectivity changes gracefully, refresh data appropriately, and provide native-feeling user experiences.

The key insight: **mobile apps need reactive data management that responds to platform events**, not just user interactions. Apps must intelligently refetch when returning from background, handle network transitions smoothly, and provide touch-friendly refresh patterns.

## Practical Walkthrough: Code Breakdown

Let's examine the React Native integration patterns from `examples/react/react-native/`:

### 1. App State Integration

```tsx
// App.tsx
import { focusManager } from '@tanstack/react-query'

function onAppStateChange(status: AppStateStatus) {
  // React Query already supports in web browser refetch on window focus by default
  if (Platform.OS !== 'web') {
    focusManager.setFocused(status === 'active')
  }
}

export default function App() {
  useAppState(onAppStateChange)
  // ...
}

// useAppState.ts
export function useAppState(onChange: (status: AppStateStatus) => void) {
  useEffect(() => {
    const subscription = AppState.addEventListener('change', onChange)
    return () => {
      subscription.remove()
    }
  }, [onChange])
}
```

**What's happening:** TanStack Query's `focusManager` is connected to React Native's `AppState`, enabling automatic refetching when the app becomes active (returns from background).

**Why this integration:** Mobile users frequently switch between apps. When they return to your app, data should be fresh. This integration ensures data updates when users return without manual refresh.

### 2. Network State Management

```tsx
// useOnlineManager.ts
import NetInfo from '@react-native-community/netinfo'
import { onlineManager } from '@tanstack/react-query'

export function useOnlineManager() {
  React.useEffect(() => {
    // React Query already supports on reconnect auto refetch in web browser
    if (Platform.OS !== 'web') {
      return NetInfo.addEventListener((state) => {
        onlineManager.setOnline(
          state.isConnected != null &&
            state.isConnected &&
            Boolean(state.isInternetReachable),
        )
      })
    }
  }, [])
}
```

**What's happening:** React Native's `NetInfo` API is connected to TanStack Query's `onlineManager`, enabling automatic query pausing/resuming based on network connectivity.

**Why network awareness:** Mobile networks are unreliable. Apps should pause requests when offline and automatically resume when connectivity returns, preventing failed requests and battery drain.

### 3. Navigation-Based Refetching

```tsx
// useRefreshOnFocus.ts
import { useFocusEffect } from '@react-navigation/native'

export function useRefreshOnFocus(refetch: () => void) {
  const enabledRef = React.useRef(false)

  useFocusEffect(
    React.useCallback(() => {
      if (enabledRef.current) {
        refetch()
      } else {
        enabledRef.current = true
      }
    }, [refetch]),
  )
}
```

**What's happening:** React Navigation's `useFocusEffect` triggers query refetching when users navigate to a screen. The `enabledRef` prevents refetching on initial mount.

**Why navigation-based refresh:** Mobile users navigate between screens frequently. Data should be fresh when users return to a screen they've visited before.

### 4. Pull-to-Refresh Integration

```tsx
// useRefreshByUser.ts
export function useRefreshByUser(refetch: () => Promise<unknown>) {
  const [isRefetchingByUser, setIsRefetchingByUser] = React.useState(false)

  async function refetchByUser() {
    setIsRefetchingByUser(true)

    try {
      await refetch()
    } finally {
      setIsRefetchingByUser(false)
    }
  }

  return {
    isRefetchingByUser,
    refetchByUser,
  }
}

// In component
export function MoviesListScreen({ navigation }: Props) {
  const { isPending, error, data, refetch } = useQuery({
    queryKey: ['movies'],
    queryFn: fetchMovies,
  })
  const { isRefetchingByUser, refetchByUser } = useRefreshByUser(refetch)

  return (
    <FlatList
      data={data}
      refreshControl={
        <RefreshControl
          refreshing={isRefetchingByUser}
          onRefresh={refetchByUser}
        />
      }
    />
  )
}
```

**What's happening:** Custom hook manages pull-to-refresh state separately from query loading state. The `RefreshControl` shows native pull-to-refresh UI while `isRefetchingByUser` tracks user-initiated refreshes.

**Why separate refresh state:** Users need different feedback for automatic background refreshes vs manual pull-to-refresh. Native refresh controls require specific state management.

### 5. Mobile-Optimized Query Configuration

```tsx
const queryClient = new QueryClient({
  defaultOptions: { 
    queries: { 
      retry: 2 // Reduced retries for mobile - faster failure detection
    } 
  },
})
```

**What's happening:** Mobile-optimized defaults with fewer retries to fail fast on poor connections and preserve battery life.

**Why mobile-specific defaults:** Mobile networks are different from desktop. Fewer retries prevent hanging requests on poor connections and reduce battery usage.

### 6. Navigation Integration

```tsx
const onListItemPress = React.useCallback(
  (movie: MovieDetails) => {
    navigation.navigate('MovieDetails', {
      movie,
    })
  },
  [navigation],
)
```

**What's happening:** Navigation passes data as parameters, enabling immediate rendering while background queries can update with fresh data.

**Why pass data through navigation:** Provides instant navigation experience. Users see content immediately, while TanStack Query can refetch fresh data in the background.

## Mental Model: Mobile-First Data Management

### The Mobile Data Lifecycle

```
Mobile App States:
Active (foreground) → Background → Inactive → Active
  ↓                    ↓           ↓         ↓
Queries active      Queries pause  Paused   Auto-refetch

Network States:
Online → Offline → Online
  ↓       ↓        ↓
Active   Pause    Resume + Auto-refetch
```

Mobile apps have multiple state dimensions that affect data fetching behavior.

### Touch Interaction Patterns

```
Native Mobile UX:
Pull down → Show refresh spinner → Release → Trigger refetch → Hide spinner

TanStack Query Integration:
Pull gesture → isRefetchingByUser: true → refetch() → isRefetchingByUser: false
```

Mobile interactions require immediate visual feedback with async data updates.

### Battery and Performance Optimization

```
Query Strategy:
- App in background → Pause all queries
- Network unavailable → Queue mutations, pause queries  
- App becomes active → Resume queries + refetch stale data
- Navigation focus → Conditionally refetch based on staleness
```

### Why It's Designed This Way: Native Mobile Experience

Web patterns don't translate directly to mobile:
```
Web: Window focus/blur → Auto-refetch
Mobile: App state changes + Network changes + Navigation → Coordinated refetch strategy
```

Mobile requires **multi-dimensional reactivity** to platform events, not just user interactions.

### Advanced Mobile Patterns

**Smart Background Sync**: Intelligent background data management:
```tsx
const useBackgroundSync = () => {
  const queryClient = useQueryClient()
  
  useEffect(() => {
    const handleAppStateChange = (nextAppState: AppStateStatus) => {
      if (nextAppState === 'background') {
        // Cache critical data before backgrounding
        queryClient.getQueryCache().getAll().forEach(query => {
          if (query.meta?.critical) {
            queryClient.setQueryData(query.queryKey, query.state.data)
          }
        })
      }
    }
    
    const subscription = AppState.addEventListener('change', handleAppStateChange)
    return () => subscription.remove()
  }, [queryClient])
}
```

**Network-Aware Query Configuration**: Adaptive behavior based on connection:
```tsx
const useNetworkAwareQueries = () => {
  const [connectionType, setConnectionType] = useState<string>()
  
  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener(state => {
      setConnectionType(state.type)
      
      // Adjust query behavior based on connection
      const defaultOptions = {
        queries: {
          staleTime: state.type === 'cellular' ? 5 * 60 * 1000 : 1 * 60 * 1000,
          refetchInterval: state.type === 'wifi' ? 30 * 1000 : false,
          retry: state.isInternetReachable ? 3 : 0
        }
      }
      
      queryClient.setDefaultOptions(defaultOptions)
    })
    
    return unsubscribe
  }, [])
}
```

**Offline Queue with Persistence**: Robust offline functionality:
```tsx
const useOfflineQueue = () => {
  const queryClient = useQueryClient()
  const [isOnline, setIsOnline] = useState(true)
  
  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener(state => {
      const online = Boolean(state.isConnected && state.isInternetReachable)
      setIsOnline(online)
      
      if (online) {
        // Process queued mutations when coming back online
        queryClient.resumePausedMutations().then(() => {
          queryClient.invalidateQueries()
        })
      }
    })
    
    return unsubscribe
  }, [queryClient])
  
  return { isOnline }
}
```

**Touch-Optimized Loading States**: Mobile-specific UI patterns:
```tsx
const useTouchFriendlyStates = (query: any) => {
  const [isUserRefreshing, setIsUserRefreshing] = useState(false)
  
  const refreshByUser = async () => {
    setIsUserRefreshing(true)
    
    // Give immediate haptic feedback
    if (Platform.OS === 'ios') {
      // HapticFeedback.impact(HapticFeedback.ImpactFeedbackStyle.Light)
    }
    
    try {
      await query.refetch()
    } finally {
      setIsUserRefreshing(false)
    }
  }
  
  return {
    isUserRefreshing,
    refreshByUser,
    // Show skeleton for initial load, spinner for refresh
    showSkeleton: query.isPending && !isUserRefreshing,
    showRefreshSpinner: isUserRefreshing
  }
}
```

**Platform-Specific Optimizations**: iOS vs Android patterns:
```tsx
const usePlatformOptimizations = () => {
  const queryClient = useQueryClient()
  
  useEffect(() => {
    if (Platform.OS === 'ios') {
      // iOS apps can be terminated quickly - more aggressive caching
      queryClient.setDefaultOptions({
        queries: {
          gcTime: 1000 * 60 * 60 * 24, // 24 hours
          staleTime: 1000 * 60 * 5, // 5 minutes
        }
      })
    } else if (Platform.OS === 'android') {
      // Android background handling - pause queries more aggressively
      queryClient.setDefaultOptions({
        queries: {
          gcTime: 1000 * 60 * 30, // 30 minutes
          staleTime: 1000 * 60 * 2, // 2 minutes
        }
      })
    }
  }, [queryClient])
}
```

### Performance Optimizations

**Memory Management**: Handle large datasets on mobile:
```tsx
// Implement pagination for large lists
const useOptimizedMovieList = () => {
  return useInfiniteQuery({
    queryKey: ['movies'],
    queryFn: ({ pageParam = 0 }) => fetchMovies(pageParam),
    getNextPageParam: (lastPage, pages) => {
      return lastPage.hasMore ? pages.length : undefined
    },
    // Limit cache size on mobile
    maxPages: 10,
  })
}
```

**Image Loading Optimization**: Smart image caching:
```tsx
const useImageCaching = () => {
  const queryClient = useQueryClient()
  
  const prefetchImage = useCallback((url: string) => {
    queryClient.prefetchQuery({
      queryKey: ['image', url],
      queryFn: () => new Promise((resolve) => {
        Image.prefetch(url).then(resolve)
      }),
      staleTime: Infinity, // Images don't change
    })
  }, [queryClient])
  
  return { prefetchImage }
}
```

### Further Exploration

Experiment with mobile-specific patterns:

1. **App State Transitions**: Test backgrounding and foregrounding behavior
2. **Network Variations**: Simulate cellular, WiFi, and offline scenarios
3. **Navigation Patterns**: Deep linking with prefetched data
4. **Platform Differences**: iOS vs Android behavior testing

**Advanced Challenges**:

1. **Push Notifications**: How would you integrate push notifications with query invalidation?

2. **Background App Refresh**: How would you implement background data updates when the app isn't active?

3. **Offline-First**: How would you build a fully offline-capable mobile app with eventual consistency?

4. **Cross-Platform Sync**: How would you sync data between mobile app and web dashboard in real-time?

**Real-World Applications**:
- **Social Media Apps**: Feed updates, offline posting, background sync
- **E-commerce Apps**: Product catalogs, cart persistence, offline browsing
- **News Apps**: Article caching, background updates, offline reading
- **Productivity Apps**: Document sync, offline editing, conflict resolution
- **Chat Applications**: Message caching, offline queueing, real-time sync

React Native + TanStack Query creates powerful mobile applications that feel native, handle network variability gracefully, and provide smooth user experiences across all mobile scenarios. Understanding these patterns is essential for building production-ready mobile applications that users love and depend on.