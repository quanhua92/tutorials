# Lazy & Suspense — split the bundle, load code on demand

> **Companion demo:** [`lazy_suspense.html`](./lazy_suspense.html) — open in a browser.
> **React version:** 19.2.7 via ESM CDN + Babel standalone.

---

## 0. TL;DR — the one idea

> **The analogy:** a static `import Foo from './Foo'` is a set menu — you pay for
> every dish up front, even the ones you'll never order. `React.lazy` is à la carte:
> the menu lists the dish, but the kitchen only cooks it the moment you actually
> order `<Foo/>`. `<Suspense>` is the "coming right up" sign on the table while you wait.

```mermaid
graph TD
    A["app boots — main chunk only"] -->|user navigates to route| B["&lt;LazyRoute/&gt; renders"]
    B -->|load() called ONCE| C["dynamic import('./route')"]
    C -->|network: chunk streams| S["&lt;Suspense fallback&gt; paints (Loading…)"]
    S -->|chunk resolves| R["React caches result, retries subtree"]
    R -->|"reads .default"| D["real route UI paints"]
    D -->|revisit later| CACHE["chunk already cached → instant, no fallback"]
    style C fill:#fef9e7,stroke:#f1c40f,stroke-width:2px
    style S fill:#eaf2f8,stroke:#2980b9
    style D fill:#eafaf1,stroke:#27ae60
    style CACHE fill:#eafaf1,stroke:#27ae60
```

`React.lazy(load)` wraps a function that returns a `Promise` (a dynamic `import()`).
The returned component **throws that promise** during render until it resolves;
`<Suspense>` catches the thrown thenable, shows its `fallback`, and re-renders the
subtree once the chunk is ready. React calls `load()` **at most once** and caches
both the promise and its resolved value — so the second visit is instant. The net
effect: users download only the code for the view they're actually looking at, not
your entire app, on the first paint.

---

## 1. How it works — the lazy + Suspense contract

### The canonical pattern

```jsx
import { lazy, Suspense } from 'react';

// load() returns the dynamic import() promise. Called once, result cached.
const MarkdownEditor = lazy(() => import('./MarkdownEditor'));

function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <MarkdownEditor />   {/* suspends until the chunk downloads, then renders */}
    </Suspense>
  );
}
```

Two pieces, each with one job:

| Piece | Job |
|-------|-----|
| `lazy(load)` | Turn `() => import('./X')` into a component that **suspends** until the chunk resolves, then renders the module's **`.default`** export. |
| `<Suspense fallback>` | Catch the thrown import promise, paint `fallback`, and retry the subtree on resolution. |

`React.lazy` is **the code-splitting mechanism** — it decides *what* loads late.
`<Suspense>` is **the loading mechanism** — it decides *what to show* while it
loads. (The throw-promise internals of Suspense are covered in depth in
[`suspense_patterns`](./suspense_patterns.html); this bundle focuses on `lazy`.)

### What `load()` must return

```javascript
// load() returns a Promise (or any thenable) that resolves to a module
// whose .default is a valid React component type.
const LazyX = lazy(() => import('./X'));
//                            ^^^^^^^^^^^^^^
//   resolves to { default: function X(props){...} }   ← lazy reads .default
```

React renders the resolved module's **`.default`** property as the component. That
`.default` may be a function, a `memo(...)` component, or a `forwardRef(...)`. The
Promise and its resolution are **cached** — React will never call `load()` twice
for the same `lazy` component.

### The simulation in the companion demo

Real dynamic `import()` needs ES-module chunks that a bundler (Vite, webpack,
Rollup) emits. In a CDN + Babel-eval sandbox there are no chunks to fetch, so
`fakeLazy()` reproduces the **exact contract** with a `setTimeout`-based promise:

```javascript
function fakeLazy(loadFn, delay) {
  let status = 'pending';   // module-level cache — mirrors React.lazy's internal cache
  let Comp = null;
  let suspender = null;     // the cached promise (referentially stable!)
  function start() {
    if (!suspender) {
      suspender = new Promise((resolve) => {
        setTimeout(() => { Comp = loadFn(); status = 'success'; resolve(); }, delay);
      });
    }
    return suspender;
  }
  return function LazyWrapper(props) {
    if (status === 'success') return React.createElement(Comp, props); // reads .default
    throw start();   // THE throw — real React.lazy does exactly this internally
  };
}
```

The `throw start()` line is the whole trick. Real `React.lazy`'s internal wrapper
does the same thing: while the import is pending, it throws the promise; Suspense
catches it, paints the fallback, and retries after resolution. Only the "network"
in the demo is faked — the Suspense fallback → resolved transition is genuine.

---

## 2. Mechanism — inside the reconciler (the dynamic-import lifecycle)

```mermaid
sequenceDiagram
    participant U as User
    participant T as &lt;LazyRoute/&gt;
    participant L as React.lazy wrapper
    participant S as &lt;Suspense&gt;
    participant N as Bundler chunk (network)
    participant D as DOM

    U->>T: navigates (or toggles) → setState shows route
    T->>L: render begins
    L->>L: cache miss → call load() = import('./route')
    L-->>S: THROWS the import promise (pending)
    Note over S: reconciler: thrown value is a thenable → suspension
    S->>D: commit fallback ("Loading…")
    L->>N: dynamic import request in flight
    Note over N: chunk streams over network…
    N-->>L: module resolves { default: Route }
    Note over L: cache .default (status='success')
    S->>T: retry the suspended subtree
    T->>L: render begins again
    L->>L: cache HIT → status 'success'
    L-->>T: React.createElement(Route, props)  // reads .default
    T-->>S: real element tree
    S->>D: commit route UI
    Note over U,D: later: revisit route → cache HIT, no throw, no fallback, instant
```

1. **Render begins.** `<LazyRoute/>` is mounted for the first time (a route switch,
   a tab toggle, a conditional `show && <LazyX/>`).
2. **Cache miss → load.** The lazy wrapper has never resolved, so it calls `load()`
   (the `() => import('./route')` factory) for the first and only time. The promise
   is cached.
3. **Throw.** While pending, the wrapper **throws the promise**.
4. **Suspend.** React's error handler sees a thenable (`typeof thrown.then === 'function'`)
   and treats it as a suspension, not an error. It walks up to the nearest
   `<Suspense>` and commits its `fallback`.
5. **Resolve + cache.** The chunk downloads; the module resolves. React caches the
   resolved `.default` and the wrapper flips its internal status to success.
6. **Retry.** React re-renders the suspended subtree. Now the wrapper hits its
   cache, skips the throw, and returns the real component.
7. **Revisit.** On any later mount, the wrapper's cache is already populated → no
   throw, no fallback, no network — the render is synchronous and instant.

> **React 19 note:** `createRoot()` enables Suspense natively. The throw-promise
> path for `lazy` is on by default in every React 18+ app — no flags, no
> `unstable_` APIs. A rejected `load()` promise is **re-thrown as an error** and
> bubbles past Suspense to the nearest `<ErrorBoundary>` (see §5).

---

## 3. Route-level splitting — where lazy pays off the most

The highest-leverage use of `React.lazy` is at **route boundaries**. Each route
becomes its own chunk; the initial bundle contains only the shell (router, layout,
landing route) plus whatever is above the fold. Heavy routes — a dashboard, a
charting editor, a settings page — load on demand.

```jsx
import { lazy, Suspense } from 'react';

const Dashboard = lazy(() => import('./routes/Dashboard'));
const Settings  = lazy(() => import('./routes/Settings'));
const Editor    = lazy(() => import('./routes/Editor'));

function App() {
  const route = useRoute();               // e.g. a tiny hand-rolled router
  return (
    <Layout>
      <Suspense fallback={<PageSpinner />}>
        {route === 'dashboard' && <Dashboard />}
        {route === 'settings'  && <Settings  />}
        {route === 'editor'    && <Editor    />}
      </Suspense>
    </Layout>
  );
}
```

Why route boundaries (not every component)? Splitting has a cost: a chunk request
adds a network round-trip on first visit. Split too finely and you trade bundle
size for waterfall latency. Routes are the natural unit because:

- A route is a **user intent boundary** — the user explicitly asked for this view,
  so a brief loading state is expected and acceptable.
- Routes are **mutually exclusive** — you rarely render two heavy routes at once,
  so the chunks don't stack up.
- The shell stays tiny and interactive while the route streams in.

> Frameworks bake this in: TanStack Router's `createLazy` / route `component`
> import and Next.js's App Router both wrap route components in `lazy` +
  `<Suspense>` automatically. The dedicated bundle
> [`router_code_splitting`](./TODO.md) (planned) covers the router-specific
> splitting APIs in depth.

---

## 4. Nested Suspense boundaries — isolate the loading region

```jsx
<Suspense fallback={<PageSpinner />}>
  <Header />
  <Main />
  <Suspense fallback={<ChartSpinner />}>
    <LazyChart />      {/* only this suspends → only the chart shows a spinner */}
  </Suspense>
</Suspense>
```

When `<LazyChart/>` suspends, React shows `<ChartSpinner/>` — **not** the outer
`<PageSpinner/>`. `<Header/>` and `<Main/>` stay mounted and interactive. The
**nearest** Suspense ancestor wins, so you can isolate a loading region to a
single widget instead of blanking the whole page. Only a suspension with **no**
`<Suspense>` ancestor bubbles all the way to the root (whose implicit fallback is
nothing — a blank screen).

This pairs naturally with code splitting: put a tight `<Suspense>` around each lazy
widget so a slow chunk only blocks that one panel.

---

## 5. Named-exports gotcha — lazy reads `.default` only

`React.lazy` reads the resolved module's **`.default`** property. Dynamic
`import()` of a module with **named** exports gives you `{ Named }` — there is no
`.default`, so lazy renders `undefined` and throws *"Element type is invalid"*.

```javascript
// ManyComponents.js
export function MyComponent() { /* ... */ }     // named export — NO .default
```

```javascript
// ❌ BREAKS: lazy reads .default, which is undefined here
const MyComponent = lazy(() => import('./ManyComponents'));

// ✅ FIX: add a re-export module that aliases the named export as the default
//   ManyComponents.default.js
//   export { MyComponent as default } from './ManyComponents';
const MyComponent = lazy(() => import('./ManyComponents.default'));

// ✅ or fix it inline in the load function (one-off)
const MyComponent = lazy(() =>
  import('./ManyComponents').then(m => ({ default: m.MyComponent }))
);
```

The re-export module is the idiomatic fix: it keeps `lazy()` calls clean and works
with any bundler's code splitting. The inline `.then()` rewrite is fine for a
one-off but can confuse some bundlers' static analysis of the chunk boundary.

---

## 6. Preload patterns — hide the network behind intent

You don't have to wait until render to start the chunk download. Because `load()`
is just a dynamic `import()`, you can kick it off early on a **user-intent** signal
(hover, focus, pointerdown) so the chunk is already in flight (or resolved) by the
time the component renders — no visible fallback at all.

```jsx
const LazySettings = lazy(() => import('./routes/Settings'));

function NavItem() {
  // Fire the import the moment the user shows intent — before the click.
  const warm = () => { import('./routes/Settings'); };   // shares the module cache
  return (
    <a
      href="/settings"
      onPointerEnter={warm}
      onFocus={warm}
      onClick={(e) => { e.preventDefault(); navigate('/settings'); }}
    >
      Settings
    </a>
  );
}
```

Why this works: the module cache is keyed by the **module specifier**
(`'./routes/Settings'`), not by who called `import()`. The eager `import()` in
`warm` and the `import()` inside `lazy` resolve to the **same** cached promise. So
by the time `<LazySettings/>` renders, `load()` returns the already-resolved module
and there's no suspension. This is the single most effective latency hack for
code splitting — trade a little bandwidth (a speculative fetch) for a perceived
instant load.

> **Route-level prefetching** formalizes this: TanStack Router and Next.js can
> preload a route's chunk during link hover or on a short idle timer. The pattern
> above is the hand-rolled version of the same idea.

---

## 7. Bundle analysis — measure before you split

Splitting blind can make things worse (more requests, waterfall latency). Measure
first:

- **webpack-bundle-analyzer / Vite's `build.rollupOptions.output` stats** — show
  every chunk and its size. Look for one or two giant modules dominating the main
  bundle; those are your prime `lazy` candidates.
- **Coverage tab (Chrome DevTools)** — shows JS bytes loaded vs. bytes actually
  executed on the initial route. Unused bytes = code that should be split out.
- **Network waterfall** — after splitting, confirm chunks load in **parallel**,
  not serially. A chain of `lazy` components that depend on each other can
  re-introduce a waterfall. Nested `<Suspense>` + preloading (§6) flattens it.

Rule of thumb: split at route boundaries first (biggest wins), then at clearly
optional widgets (a settings dialog, a heavy chart, a rich-text editor). Don't
split tiny components — the request overhead exceeds the bytes saved.

---

## Killer Gotchas

| Trap | Symptom | Fix |
|------|---------|-----|
| **No `<Suspense>` ancestor** | App goes blank while the chunk loads (or React errors "Suspense … not found") | Every `<LazyComponent/>` must be inside a `<Suspense>`. A suspension with no boundary bubbles to the root. |
| **Named-export module** | *"Element type is invalid: expected a function but got: undefined"* | `lazy` reads `.default`. Re-export as default (`export { Named as default }`) or remap inline: `.then(m => ({ default: m.Named }))`. |
| **Declaring `lazy` inside a component** | The lazy component's internal state resets on every parent re-render; the chunk re-throws | Declare `lazy(...)` at **module top level**, never inside another component. |
| **Rejected `load()` promise** | The error flies past `<Suspense>` and crashes the tree | A rejection becomes a real thrown **error**, not a suspension. Wrap `<Suspense>` in an `<ErrorBoundary>` to catch it. |
| **Splitting too finely** | More total bytes (per-chunk overhead) and a request waterfall; slower than the original bundle | Split at route boundaries, not every component. Measure with a bundle analyzer before and after. |
| **Expecting `lazy` to fetch data** | The chunk loads but the screen stays empty | `lazy` only loads **code**. It does nothing for data. Pair with a data layer (React Query, SWR, `use(promise)`) inside its own `<Suspense>`. |
| **Re-suspend flicker on revisit** | Users expect instant revisit but see the fallback again | The chunk is cached, so revisit is instant — unless you remount with a new `key` or the module cache was evicted. Don't key-flip lazy subtrees. |
| **Waterfall of nested lazy** | Chunk A loads, renders `<LazyB/>`, which loads chunk B, then `<LazyC/>`… serial | Preload dependent chunks (§6) on intent, or hoist the `<Suspense>` so all three load under one fallback in parallel. |
| **SSR / hydration mismatch** | Server can't `import()` the chunk synchronously; fallback vs. real markup differs | Render a stable fallback on both server and client, or use a framework with first-class lazy SSR (Next.js, Remix). Pure `lazy` is a client-only API. |
| **Thinking `lazy` starts the fetch** | You render `<LazyX/>` inside `<Suspense>` and nothing loads until render | `load()` runs only when React tries to **render** the lazy component. To fetch earlier, call `import('./X')` eagerly (§6 preload). |

### Cheat sheet

```jsx
// 1. Basic code split — split a route/widget into its own chunk
const LazyX = lazy(() => import('./X'));
<Suspense fallback={<Spinner />}><LazyX /></Suspense>

// 2. Named-export module — lazy needs a .default, so re-export
//    X.default.js:  export { Named as default } from './X';
const Named = lazy(() => import('./X.default'));

// 3. Nested boundaries — isolate loading to one region
<Suspense fallback={<Outer />}>
  <Static />
  <Suspense fallback={<InnerSpinner />}><LazyWidget /></Suspense>
</Suspense>

// 4. Preload on intent — hide network behind hover/focus
const onWarm = () => import('./routes/Settings');   // shares the module cache
<a onPointerEnter={onWarm} onFocus={onWarm}>Settings</a>

// 5. Fail gracefully — a rejected chunk is a thrown error, not a suspension
<ErrorBoundary fallback={<Err />}>
  <Suspense fallback={<Spinner />}><LazyRisky /></Suspense>
</ErrorBoundary>

// 6. Declare lazy at module top level — NEVER inside a component
const LazyEditor = lazy(() => import('./Editor'));   // ✅ top level
function Page() { return <Suspense ...><LazyEditor /></Suspense>; }
```

---

## 🔗 Cross-references

- [`suspense_patterns`](./suspense_patterns.html) — the **loading** mechanism. `React.lazy` is the code-splitting trigger; this bundle covers the throw-promise contract `<Suspense>` uses to catch it, plus `use(promise)` for data. "Suspense handles loading — React.lazy is the code-splitting mechanism."
- [`use_transition`](./use_transition.html) — `useTransition` + Suspense keeps the **old** route visible while the lazy chunk for the new route loads (no fallback flash on navigation). Wrap the route `setState` in `startTransition`.
- [`router_code_splitting`](./TODO.md) *(planned)* — route-level splitting with TanStack Router's `createLazy` and route `component` imports; framework-managed `<Suspense>` boundaries at route nodes.
- [`virtual_lists`](./TODO.md) *(planned)* — a complementary performance bundle: lazy/streamed list rows. Where `lazy` splits a *component*, virtualization splits a *large list* — both avoid doing work the user can't see yet.
- [`error_boundaries`](./error_boundaries.html) — the mandatory partner for lazy chunks that can fail to load: Suspense catches thrown **promises**, ErrorBoundary catches the thrown **error** when a chunk rejects (or fails to download).

---

## Sources

1. **React Docs — `lazy`**: https://react.dev/reference/react/lazy (signature `lazy(load)`; `load` returns a Promise/thenable resolved value cached, React renders the resolved `.default`; "Using this pattern requires that the lazy component you're importing was exported as the `default` export"; declare at top level; rejection throws to the nearest Error Boundary; must be wrapped in `<Suspense>`)
2. **React Docs — `<Suspense>`**: https://react.dev/reference/react/Suspense ("Suspense will automatically switch to `fallback` when children suspends, and back to children when the data is ready"; nearest-boundary-wins for nested Suspense; `React.lazy` components suspend while their code loads)
3. **React Docs — Code Splitting with `lazy` (usage example)**: https://react.dev/reference/react/lazy#suspense-for-code-splitting (the canonical `lazy(() => import('./MarkdownPreview.js'))` + `<Suspense fallback={<Loading/>}>` pattern; chunk is cached after first load so revisiting shows no loading state)
4. **MDN — Dynamic `import()`**: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Operators/import (the spec mechanism `lazy` builds on: returns a Promise resolving to the module namespace object whose `.default` is the default export; module specifiers are cached per realm)
5. **Epic React — How Suspense Works Under the Hood**: https://www.epicreact.dev/how-react-suspense-works-under-the-hood-throwing-promises-and-declarative-async-ui-plbrh (the throw-promise mechanism `React.lazy`'s internal wrapper uses: "in JavaScript, you can synchronously stop a function by throwing; React leverages this to pause rendering until the [chunk] is ready")
