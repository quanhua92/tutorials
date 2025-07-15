# Vue Query: Composition API Integration

> **Based on**: [`examples/vue/basic`](https://github.com/TanStack/query/tree/390424bcdd547d238148e72926f75c181e342976/examples/vue/basic)

## The Core Concept: Why This Example Exists

**The Problem:** Vue's Composition API revolutionized how we build reactive applications, but integrating server state management with Vue's reactivity system requires careful coordination. Developers often struggle with manually managing loading states, handling cache invalidation, and ensuring reactive updates when server data changes.

**The Solution:** TanStack Vue Query bridges the gap between Vue's reactive system and server state management. It provides **Vue-native composables** that automatically integrate with Vue's reactivity, ensuring that server state changes trigger appropriate re-renders while maintaining all the caching and synchronization benefits of TanStack Query.

The key insight: **server state should feel like local reactive state** in Vue applications. Vue Query makes remote data as reactive and easy to use as `ref()` or `reactive()` objects.

## Practical Walkthrough: Code Breakdown

Let's examine the Vue-specific patterns from `examples/vue/basic/`:

### 1. Vue Component Architecture

```vue
<!-- App.vue -->
<script lang="ts">
import { defineComponent, ref } from 'vue'
import Posts from './Posts.vue'
import Post from './Post.vue'

export default defineComponent({
  name: 'App',
  components: { Posts, Post },
  setup() {
    const visitedPosts = ref(new Set())
    const isVisited = (id: number) => visitedPosts.value.has(id)

    const postId = ref(-1)
    const setPostId = (id: number) => {
      visitedPosts.value.add(id)
      postId.value = id
    }

    return { isVisited, postId, setPostId }
  },
})
</script>

<template>
  <Post v-if="postId > -1" :postId="postId" @setPostId="setPostId" />
  <Posts v-else :isVisited="isVisited" @setPostId="setPostId" />
</template>
```

**What's happening:** The root component manages navigation state using Vue's `ref()` reactivity. The `visitedPosts` Set tracks which posts have been viewed, enabling cache-aware UI indicators.

**Why this pattern:** Vue's reactivity naturally complements Query's caching - local state tracks user interactions while Query manages server state. They work together seamlessly.

### 2. Query Integration in Components

```vue
<!-- Posts.vue -->
<script lang="ts">
import { defineComponent } from 'vue'
import { useQuery } from '@tanstack/vue-query'

export default defineComponent({
  name: 'PostsList',
  setup() {
    const { isPending, isError, isFetching, data, error, refetch } = useQuery({
      queryKey: ['posts'],
      queryFn: fetcher,
    })

    return { isPending, isError, isFetching, data, error, refetch }
  },
})
</script>

<template>
  <div v-if="isPending">Loading...</div>
  <div v-else-if="isError">An error has occurred: {{ error }}</div>
  <div v-else-if="data">
    <ul>
      <li v-for="item in data" :key="item.id">
        <a @click="$emit('setPostId', item.id)" :class="{ visited: isVisited(item.id) }">
          {{ item.title }}
        </a>
      </li>
    </ul>
  </div>
</template>
```

**What's happening:** `useQuery` returns reactive refs that automatically trigger Vue re-renders when server state changes. The template directly uses these reactive values with Vue's conditional rendering (`v-if`, `v-else-if`).

**Why this works seamlessly:** Vue Query's returned values are Vue `ref()` objects, making them fully reactive and compatible with Vue's template system and computed properties.

### 3. Props-Based Reactive Queries

```vue
<!-- Post.vue -->
<script lang="ts">
export default defineComponent({
  name: 'PostDetails',
  props: {
    postId: {
      type: Number,
      required: true,
    },
  },
  setup(props) {
    const { isPending, isError, isFetching, data, error } = useQuery({
      queryKey: ['post', props.postId],
      queryFn: () => fetcher(props.postId),
    })

    return { isPending, isError, isFetching, data, error }
  },
})
</script>
```

**What's happening:** The query key includes `props.postId`, making the query reactive to prop changes. When the parent component changes `postId`, Vue Query automatically fetches the new post data.

**Why props work reactively:** Vue Query watches the query key for changes, and since `props.postId` is reactive, query key changes trigger new requests automatically.

### 4. Event-Driven Navigation

```vue
<template>
  <a @click="$emit('setPostId', item.id)" href="#">{{ item.title }}</a>
</template>
```

**What's happening:** Vue's event system (`$emit`) communicates user interactions up the component tree, where parent components update reactive state that triggers new queries.

**Why events over direct mutations:** This follows Vue's unidirectional data flow principles while maintaining clear component boundaries and testability.

### 5. Reactive Style Bindings

```vue
<template>
  <a 
    @click="$emit('setPostId', item.id)"
    :class="{ visited: isVisited(item.id) }"
  >
    {{ item.title }}
  </a>
</template>

<style scoped>
.visited {
  font-weight: bold;
  color: green;
}
</style>
```

**What's happening:** CSS classes reactively update based on cache state. The `isVisited` function checks local state that's coordinated with Query's cache to provide visual feedback.

**Why combine local and server state:** Some UI state (like "visited" indicators) is client-side only but benefits from being coordinated with server data fetching patterns.

## Mental Model: Vue Reactivity + Server State

### Reactive Query State

Think of Vue Query as extending Vue's reactivity system to the network:

```
Vue Reactivity:
ref(localValue) ──→ Reactive Updates ──→ Template Re-render

Vue Query:
useQuery(serverData) ──→ Reactive Updates ──→ Template Re-render
```

Both local refs and query results trigger the same reactive update mechanism.

### Component Communication Pattern

```
App Component (Navigation State)
├── ref(postId) ──→ controls routing
├── ref(visitedPosts) ──→ tracks user behavior
│
├── Posts Component
│   └── useQuery(['posts']) ──→ list data
│   └── emit('setPostId') ──→ navigation events
│
└── Post Component  
    └── useQuery(['post', postId]) ──→ detail data
    └── emit('setPostId', -1) ──→ back navigation
```

### Reactivity Flow

```
1. User clicks post link
   ↓
2. Posts component emits setPostId(42)
   ↓  
3. App component updates postId.value = 42
   ↓
4. Vue reactivity triggers component switch
   ↓
5. Post component mounts with postId prop = 42
   ↓
6. useQuery(['post', 42]) automatically executes
   ↓
7. Query result updates trigger template re-render
```

### Why This Design Works

**Familiar Patterns**: If you know Vue's Composition API, Vue Query feels natural
**Automatic Reactivity**: No manual subscriptions or effect management needed
**Component Isolation**: Each component owns its data requirements
**Declarative**: Templates directly bind to query state without intermediary logic

### Advanced Vue Query Patterns

**Computed Queries**: Combine with Vue's `computed()` for derived server state:
```ts
const selectedPostQuery = computed(() => 
  useQuery(['post', selectedId.value])
)
```

**Watchers**: Use Vue's `watch()` to react to query state changes:
```ts
watch(postsQuery.data, (newPosts) => {
  // React to data changes
})
```

**Provide/Inject**: Share query clients across component trees:
```ts
// Root component
provide('queryClient', queryClient)

// Child component  
const queryClient = inject('queryClient')
```

### Error Boundaries in Vue

Unlike React, Vue doesn't have built-in error boundaries, but you can handle query errors reactively:

```vue
<template>
  <div v-if="postsQuery.isError" class="error-boundary">
    <h2>Something went wrong</h2>
    <p>{{ postsQuery.error.message }}</p>
    <button @click="postsQuery.refetch()">Try Again</button>
  </div>
</template>
```

### Further Exploration

Experiment with Vue-specific patterns:

1. **Reactive Dependencies**: Try using `computed()` values in query keys
2. **Multiple Queries**: Use `useQueries` for parallel data fetching
3. **Global State**: Integrate with Pinia or Vuex for global state coordination
4. **Route Integration**: Combine with Vue Router for URL-driven queries

**Vue-Specific Challenges**:

1. **Dynamic Query Keys**: How would you implement search that's reactive to input changes?
   ```ts
   const searchQuery = ref('')
   const { data } = useQuery({
     queryKey: ['search', searchQuery],
     queryFn: () => searchAPI(searchQuery.value)
   })
   ```

2. **Conditional Queries**: How would you handle queries that should only run under certain conditions?
   ```ts
   const { data } = useQuery({
     queryKey: ['posts'],
     queryFn: fetchPosts,
     enabled: computed(() => user.value.isLoggedIn)
   })
   ```

3. **Form Integration**: How would you coordinate form state with optimistic mutations?

**Real-World Vue Applications**:
- Admin dashboards with reactive filters
- E-commerce with cart state + server product data
- Social apps with real-time feeds
- Content management with draft/published state

Vue Query brings the power of TanStack Query to Vue's reactive ecosystem, creating a seamless development experience where server state feels like natural extension of Vue's built-in reactivity. The patterns you learn here scale from simple data fetching to complex, real-time applications.