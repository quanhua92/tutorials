# React via CDN

> **Companion demo:** [`react_via_cdn.html`](./react_via_cdn.html) — open in a browser.
> Rendered-ground-truth: NO `.js`. Every fact below is proven by the live demo
> (the compiled output, the rendered DOM, `React.version`).

---

## 0. TL;DR — the one idea

> **The analogy:** the browser only speaks **JavaScript + the DOM** — it has no
> idea what `<h1>Hello</h1>` *inside your script* means. React closes that gap in
> two moves. (1) **JSX** is sugar: Babel rewrites `<App/>` into a plain function
> call `React.createElement(App)`, which returns a plain object — a **React
> element**, the description of a node. (2) **React DOM** walks that tree of
> element objects and produces real DOM nodes. So React builds a **tree of
> elements from JSX and reconciles it into the DOM**; the CDN + Babel playground
> lets you try that pipeline with **zero build step**.

```mermaid
graph LR
    JSX["JSX you write<br/>&lt;App/&gt;"] -->|Babel.transform<br/>runtime: classic| CE["React.createElement(...)<br/>plain function calls"]
    CE --> EL["element tree<br/>plain JS objects<br/>{ type, props, children }"]
    EL -->|createRoot().render()| DOM["real DOM nodes<br/>inside #root"]
    REACT["react@19.2.7<br/>(runtime: createElement,<br/>hooks)"] -.supplies.-> CE
    RDC["react-dom@19.2.7/client<br/>(renderer: createRoot)"] -.supplies.-> DOM
    style JSX fill:#eaf2f8,stroke:#2980b9
    style EL fill:#eafaf1,stroke:#27ae60,stroke-width:3px
    style DOM fill:#fef9e7,stroke:#f1c40f
    style REACT fill:#f4ecf7,stroke:#8e44ad
    style RDC fill:#f4ecf7,stroke:#8e44ad
```

Three CDN scripts do all of it — nothing else:

| CDN script | role | what it gives you |
|---|---|---|
| `react@19.2.7` <br/><sub>esm.sh `?dev`</sub> | **the runtime** | `React.createElement`, hooks (`useState`), `React.version` |
| `react-dom@19.2.7/client` <br/><sub>esm.sh `?dev`</sub> | **the DOM renderer** | `createRoot` — the React 19 mount API (replaces `ReactDOM.render`) |
| `@babel/standalone@8.0.3` <br/><sub>jsDelivr</sub> | **the compiler** | `Babel.transform(src,{presets:[['react',{runtime:'classic'}]]})` → `React.createElement` |

---

## 1. How it works (the three-script playground)

You need **three** things, each from a CDN, because the browser supplies none of
them natively:

**1. React — the runtime.** The `react` package is *just* the rules for defining
components and describing UI as element objects. It knows nothing about the
browser. It gives you `React.createElement` and the hooks.

**2. React DOM — the renderer.** `react-dom/client` is the part that actually
talks to the browser. Its `createRoot(domNode)` returns a root whose `.render()`
turns an element tree into real DOM nodes. **React 19 mounts with
`createRoot(...).render(...)`** — the legacy `ReactDOM.render(...)` is gone.

**3. Babel Standalone — the compiler.** JSX is not valid JavaScript. Babel reads
your JSX string and emits `React.createElement(...)` calls, in the browser, at
runtime.

```html
<!-- the three CDN scripts (the playground's only externals) -->
<script src="https://cdn.jsdelivr.net/npm/@babel/standalone@8.0.3/babel.min.js"></script>

<script type="module">
  import React        from "https://esm.sh/react@19.2.7?dev";
  import { createRoot } from "https://esm.sh/react-dom@19.2.7/client?dev";
  window.React = React;          // expose so compiled JSX can see them
  window.createRoot = createRoot;
</script>
```

> **Why `import` and not a UMD `<script src>`?** See the headline gotcha below:
> **React 19 dropped UMD builds**. The old
> `unpkg.com/react@19/umd/react.development.js` returns 404 — that path simply
> does not exist any more. The live demo loads React 19 as an ES module via
> `esm.sh` (the React-team-recommended ESM CDN) using a dynamic `import()`.

The demo's `<textarea id="jsx-source">` holds this JSX:

```jsx
function App() {
  const [n, setN] = React.useState(0);
  return (
    <div className="card">
      <h1>Hello, React</h1>
      <p>Babel compiled this JSX; React {React.version} rendered it.</p>
      <button onClick={() => setN(n + 1)}>clicked {n} times</button>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App/>);
```

---

## 2. The mechanism — JSX → element tree → DOM

The demo reads the `<textarea>`'s text and runs it through
`Babel.transform(src, { presets: [['react', { runtime: 'classic' }]] })`.
The **classic** runtime emits `React.createElement` (referencing the
`window.React` global); Babel 8's *default* `automatic` runtime would instead
emit `import … from "react/jsx-runtime"`, which can't resolve at runtime here —
so classic is forced. (That is a killer gotcha; see below.)

> From `react_via_cdn.html` — Babel's compiled output (the element-tree code):
> ```js
> function App() {
>   const [n, setN] = React.useState(0);
>   return React.createElement("div", { className: "card" },
>     React.createElement("h1", null, "Hello, React"),
>     React.createElement("p", null, "Babel compiled this JSX; React ", React.version, " rendered it."),
>     React.createElement("button", { onClick: () => setN(n + 1) }, "clicked ", n, " times")
>   );
> }
> createRoot(document.getElementById("root")).render(React.createElement(App, null));
> ```

Each `React.createElement(type, props, ...children)` returns a **plain object** —
a React element. `App()` returns a tree of them. That object tree is the
intermediate representation React actually works with; the DOM does not exist
yet. `createRoot(#root).render(<App/>)` then walks the tree and produces the
real DOM.

> From `react_via_cdn.html` — the rendered result inside `#root`:
> ```
> #root.children.length = 1            (the .card div is mounted)
> #root.textContent   includes "Hello, React"
> React.version        = "19.2.7"
> [check] React rendered into #root (child + “Hello, React”): OK
> ```

The gold-check pins exactly those facts: it polls `#root` (via
`requestAnimationFrame`, up to ~2 s, because React + Babel load asynchronously)
and asserts **`#root.children.length >= 1` AND the text contains `"Hello,
React"`**. Click the button in the rendered card and `n` updates — that
`useState` re-render is live proof a real React runtime is driving the DOM, not
a static snapshot.

---

## 3. How *this* bundle keeps `just check` green

Babel's convenience hook auto-compiles `<script type="text/babel">` tags. But
that block contains **JSX, which is not valid plain JavaScript**, so the repo's
`just check` — which runs `node --check` on *every* extracted `<script>` — would
fail on it. The demo therefore **does not** use a `text/babel` script. Instead:

- the JSX lives in a plain `<textarea id="jsx-source">` (RCDATA keeps `<App/>`
  literal; `.value` returns the exact source),
- a classic `<script>` reads it and calls `Babel.transform(...)` itself,
- React 19 is loaded with a dynamic **`import()`** (legal in classic scripts, so
  `node --check` passes) and assigned to `window`.

Net effect: the only inline `<script>` blocks are valid plain JS, and the JSX
never appears inside a `<script>`. `just check react_via_cdn` → **OK**.

---

## Killer Gotchas

| Trap | Symptom | Fix |
|---|---|---|
| **React 19 dropped UMD** | `unpkg.com/react@19/umd/react.development.js` → 404; "React is not defined" | load React 19 as ESM from `esm.sh` (or another ESM CDN) and assign it to `window` yourself |
| **`ReactDOM.render` is gone in React 19** | "ReactDOM.render is not a function" / nothing renders | use `import { createRoot } from 'react-dom/client'` → `createRoot(node).render(<App/>)` |
| **Need BOTH `react` AND `react-dom`** | "Target container is not a DOM element" / no renderer | `react` is just the runtime; `react-dom/client` is what writes to the DOM. Two scripts, always. |
| **Babel 8 defaults to `automatic` runtime** | compiled output has `import … from "react/jsx-runtime"` → fails to resolve in a no-bundler eval | pass `presets:[['react',{runtime:'classic'}]]` so it emits `React.createElement` against your `window.React` |
| **JSX won't compile without Babel seeing it** | raw `<h1>` in a normal `<script>` → `SyntaxError: Unexpected token '<'` | put JSX where Babel compiles it: a `text/babel` script, or feed the source string to `Babel.transform` |
| **Babel-in-browser is SLOW and not for production** | multi-megabyte download + a compile pass on every load; big perf hit | this is a **prototyping/learning** workflow only. Ship a real build (Vite/webpack) that pre-compiles JSX. |
| **CDN load is async** | asserting the DOM right after the tags returns empty | poll with `requestAnimationFrame` (the demo waits ~2 s) before ever reporting FAIL |

### Cheat sheet

```js
// React 19, no build step — load ESM from esm.sh (UMD was removed in React 19)
import React          from "https://esm.sh/react@19.2.7?dev";
import { createRoot } from "https://esm.sh/react-dom@19.2.7/client?dev";
// <script src="https://cdn.jsdelivr.net/npm/@babel/standalone@8.0.3/babel.min.js">

// JSX  ->  React.createElement(...)   (force CLASSIC runtime in Babel 8)
const out = Babel.transform(jsxSource, { presets: [["react", { runtime: "classic" }]] });

// React 19 mount API (no more ReactDOM.render)
createRoot(document.getElementById("root")).render(<App/>);

// a React element is just a plain object:  { type, props, children }
```

---

## 🔗 Cross-refs

- **next:** `react_components_props` — once React mounts, components + props are
  how you parameterise the element tree.
- **foundations phase** — the DOM React renders into *is* the box model from
  [`foundations/box_model.html`](../foundations/box_model.html). React produces
  the very nodes whose edges that bundle measures.

---

## Sources

Exact CDN URLs (pinned, web-verified ≥2 ways — see verification notes):

- **`https://esm.sh/react@19.2.7?dev`** — React 19 runtime. `curl` → HTTP 200,
  `content-type: application/javascript`, resolves to
  `react@19.2.7/es2022/react.development.mjs`. Version confirmed via
  `npm view react dist-tags` → `latest: 19.2.7`.
- **`https://esm.sh/react-dom@19.2.7/client?dev`** — React DOM renderer; exports
  `createRoot`. `curl` → HTTP 200, resolves to `react-dom@19.2.7` +
  `client.development.mjs`.
- **`https://cdn.jsdelivr.net/npm/@babel/standalone@8.0.3/babel.min.js`** —
  Babel compiler. `curl` → HTTP 200, 2.45 MB; exposes global `Babel` with
  `Babel.version === "8.0.3"` and `Babel.transform`. (unpkg redirects the
  versionless URL to `@8.0.3` too.)

Behavioural claims:

- React team — *React 19 Upgrade Guide* (UMD removal): Ricky Hanlon, quoted in
  Peter Kellner, "Running React 19 From a CDN and using esm.sh"
  https://peterkellner.net/2024-05-10-running-react-19-from-a-cdn-and-using-esmsh/ —
  "Starting with React 19, React will no longer produce UMD builds… we recommend
  using an ESM-based CDN such as esm.sh."
- React — GitHub issue #31867, "[React 19] npm install react -- missing umd
  module" (the `umd/` folder is absent from the npm package)
  https://github.com/facebook/react/issues/31867
- React — *createRoot* reference (React 19 mount API; `ReactDOM.render` removed)
  https://react.dev/reference/react-dom/client/createRoot
- React — *Add React to an Existing Project*
  https://react.dev/learn/add-react-to-an-existing-project
- tripu — "React 19 with JSX, pure client (no build)" (ESM + window-globals +
  Babel pattern): https://blog.tripu.info/react-19
- JSer.dev — "Try out React 19 in ESM without build tools"
  https://jser.dev/2024-07-01-esm-react/
- Babel — *babel-standalone* (`Babel.transform`, `text/babel` auto-hook)
  https://babeljs.io/docs/babel-standalone/
- esm.sh — https://esm.sh/
