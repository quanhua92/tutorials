# The Context Object: req, json, text, header, redirect

**Doc Source**: [Hono — Context](https://hono.dev/docs/api/context)

## The Core Concept: Why This Example Exists

**The Problem:** In the bare-metal world (`node:http`, 🔗 [`NODE_HTTP_SERVER`](../NODE_HTTP_SERVER.md)) the request arrives split across two stream objects — `req` (`IncomingMessage`, a Readable) and `res` (`ServerResponse`, a Writable) — and you mutate `res` imperatively: `res.statusCode = 201; res.setHeader('X', 'y'); res.end(body)`. That design has three problems: (1) the request data is scattered (headers on `req.headers`, query on `req.url` un-parsed, body as a stream you must drain); (2) the response is built by **side effect** rather than returned, which makes handlers hard to test and reason about; (3) there is no per-request place to stash values (a parsed user, a db client) for downstream handlers to read.

**The Solution:** Hono collapses all of this into a single **Context** object — `c` — passed to every handler. Per the docs:

> "The `Context` object is instantiated for each request and kept until the response is returned. You can put values in it, set headers and a status code you want to return, and access HonoRequest and Response objects."

The Context is **THE request object**: `c.req` reads the incoming request (params, query, headers, body), the `c.json`/`c.text`/`c.html`/`c.redirect` helpers *build and return* the response, and `c.set`/`c.get` provide a per-request key-value store for passing values between middleware and handlers. The handler **returns** a `Response` rather than mutating one — which is exactly why `app.fetch` is a pure `(Request) => Response` function (🔗 [`01-hello-world.md`](./01-hello-world.md)).

Think of the Context as a **clipboard handed to each person in an assembly line**. Each worker (middleware → handler) can read what's on it (`c.req`, `c.get`), write notes for the next worker (`c.set`), and finally stamp the finished product (`c.json`, `c.status`) before passing it on. Axum's extractors + `(StatusCode, Json(user))` tuple return (🔗 [`../rust/axum/03-extractors-and-responses.md`](../rust/axum/03-extractors-and-responses.md)) is the typed-compile-time cousin; Hono's Context is the runtime-flavored equivalent.

## Practical Walkthrough: Code Breakdown

All snippets below are quoted verbatim from the [Hono Context docs](https://hono.dev/docs/api/context).

### `c.req` — Reading the Incoming Request

`req` is a `HonoRequest` instance and is your read-only view of what the client sent:

```ts
app.get('/hello', (c) => {
  const userAgent = c.req.header('User-Agent')
  // ...
})
```

The Context docs focus on `c.req.header`, and the full `HonoRequest` surface (`.param()`, `.query()`, `.json()`, `.header()`) is detailed in the [HonoRequest docs](https://hono.dev/docs/api/request). In practice you reach for:

- `c.req.param('id')` / `c.req.param()` — path params (🔗 [`02-routing-patterns.md`](./02-routing-patterns.md))
- `c.req.query('q')` / `c.req.query()` — query string
- `c.req.header('User-Agent')` / `c.req.header()` — request headers
- `await c.req.json()` / `await c.req.text()` / `await c.req.parseBody()` — the body

### `c.status()` — Set the HTTP Status Code

> "The default is `200`. You don't have to use `c.status()` if the code is `200`."

```ts
app.post('/posts', (c) => {
  // Set HTTP status code
  c.status(201)
  return c.text('Your post is created!')
})
```

`c.status()` mutates the Context's pending status; the final `Response` carries it. (You can also pass status as the 2nd arg to `c.body`/`c.json`/`c.text` — shown below.)

### `c.header()` — Set Response Headers

```ts
app.get('/', (c) => {
  // Set headers
  c.header('X-Message', 'My custom message')
  return c.text('Hello!')
})
```

### `c.body()` / `c.text()` / `c.json()` / `c.html()` — Build the Response

`c.body()` is the low-level primitive. The docs note:

> "**Note**: When returning text or HTML, it is recommended to use `c.text()` or `c.html()`."

```ts
app.get('/welcome', (c) => {
  c.header('Content-Type', 'text/plain')
  // Return the response body
  return c.body('Thank you for coming')
})
```

`c.body` also takes status + headers positionally, which is equivalent to constructing a raw `Response`:

```ts
app.get('/welcome', (c) => {
  return c.body('Thank you for coming', 201, {
    'X-Message': 'Hello!',
    'Content-Type': 'text/plain',
  })
})
```

The docs make the equivalence to the web-standard `Response` explicit — this is the same object:

```ts
new Response('Thank you for coming', {
  status: 201,
  headers: {
    'X-Message': 'Hello!',
    'Content-Type': 'text/plain',
  },
})
```

The typed-content helpers set `Content-Type` for you:

```ts
// text/plain
app.get('/say', (c) => {
  return c.text('Hello!')
})

// application/json
app.get('/api', (c) => {
  return c.json({ message: 'Hello!' })
})

// text/html
app.get('/', (c) => {
  return c.html('<h1>Hello! Hono!</h1>')
})
```

### `c.redirect()` and `c.notFound()`

```ts
app.get('/redirect', (c) => {
  return c.redirect('/')
})
app.get('/redirect-permanently', (c) => {
  return c.redirect('/', 301)
})
```

> Redirect defaults to status `302`; pass `301` for permanent.

```ts
app.get('/notfound', (c) => {
  return c.notFound()
})
```

`c.notFound()` returns the "Not Found" response and is customizable via `app.notFound()` (the app-level handler).

### `c.res` — The Response Being Built

You can reach the in-progress `Response` object directly — typically in middleware, *after* `await next()`:

```ts
// Response object
app.use('/', async (c, next) => {
  await next()
  c.res.headers.append('X-Debug', 'Debug message')
})
```

This is how middleware post-processes a response (🔗 [`04-middleware.md`](./04-middleware.md)).

### `c.set()` / `c.get()` — The Per-Request Store

> "Get and set arbitrary key-value pairs, with a lifetime of the current request. This allows passing specific values between middleware or from middleware to route handlers."

```ts
app.use(async (c, next) => {
  c.set('message', 'Hono is cool!!')
  await next()
})

app.get('/', (c) => {
  const message = c.get('message')
  return c.text(`The message is "${message}"`)
})
```

**Type safety.** To make `c.get('message')` typed, pass `Variables` as a generic to the `Hono` constructor:

```ts
type Variables = {
  message: string
}

const app = new Hono<{ Variables: Variables }>()
```

Now `c.get('message')` is `string`, not `unknown`. The docs are explicit about the scope:

> "The value of `c.set` / `c.get` are retained only within the same request. They cannot be shared or persisted across different requests."

This is the **per-request store** that replaces passing arguments through middleware by hand. (Axum's `Request` extensions / `State` extractor — 🔗 [`../rust/axum/06-dependency-injection-and-state.md`](../rust/axum/06-dependency-injection-and-state.md) — is the typed compile-time analog.)

### `c.var` — Accessor for Non-Primitive Values

For values that are objects/functions (e.g. a db client or helper injected by middleware), `c.var` reads them off the typed store:

```ts
const result = c.var.client.oneMethod()
```

This pairs with `createMiddleware<{ Variables: {...} }>` so a middleware can inject a method that downstream handlers call type-safely:

```ts
import { createMiddleware } from 'hono/factory'

type Env = {
  Variables: {
    echo: (str: string) => string
  }
}

const app = new Hono()

const echoMiddleware = createMiddleware<Env>(async (c, next) => {
  c.set('echo', (str) => str)
  await next()
})

app.get('/echo', echoMiddleware, (c) => {
  return c.text(c.var.echo('Hello!'))
})
```

### `c.env` — Runtime Bindings (Workers)

On Cloudflare Workers, `c.env` exposes the bindings (KV, D1, R2, secrets) declared in `wrangler.toml`. The same `app` runs on Node, where `c.env` is the adapter's object (e.g. `c.env.incoming` for the raw Node `IncomingMessage`):

```ts
const app = new Hono<{ Bindings: Bindings }>()

app.get('/', async (c) => {
  c.env.MY_KV.get('my-key')
  // ...
})
```

`Bindings` and `Variables` are the two generic slots on `Hono<{ Bindings, Variables }>` — the framework's whole approach to **type-safe per-request data**.

### `c.error` — The Error (in Middleware)

> "If the Handler throws an error, the error object is placed in `c.error`. You can access it in your middleware."

```ts
app.use(async (c, next) => {
  await next()
  if (c.error) {
    // do something...
  }
})
```

This is the observability hook for the post-`next()` phase of middleware.

## Mental Model: One Object, Two Phases

The Context lives for exactly **one request** and is touched in **two phases** — on the way **in** (reading `c.req`, setting up `c.set` values, pre-processing) and on the way **out** (after `await next()`, reading `c.res`/`c.error`, appending headers). The handler sits at the center and *returns* a response rather than mutating `res`.

```mermaid
graph LR
    REQ["Request"] --> C["Context c<br/>(per-request)"]
    C -->|"IN phase"| IN["c.req.param/query/header<br/>c.set('user', ...)<br/>c.status / c.header"]
    IN --> MW["await next() -> handler"]
    MW -->|"OUT phase"| OUT["c.res.headers.append<br/>c.error check"]
    OUT --> RESP["return Response"]
    style C fill:#e7f0ff,stroke:#3178c6,stroke-width:3px
    style MW fill:#eafaf1,stroke:#27ae60
```

**Why it's designed this way.** Putting everything on one object has three payoffs:

- **Discoverability** — every handler gets one argument, `c`, and IDE autocomplete shows you the whole surface (`c.req`, `c.json`, `c.set`, `c.redirect`, ...). No `req`/`res`/`next` three-arg signature to memorize.
- **Return-over-mutation** — handlers `return c.json(...)`, so they are trivially testable: call the handler with a Context, assert on the returned `Response`. (Axum leans even harder on this — its handlers return `impl IntoResponse`.)
- **Per-request isolation** — `c.set`/`c.get` lives only for the current request, so there is no accidental cross-request leakage (a real footgun in global singletons).

### Pitfalls

- **`ContextVariableMap` global augmentation hides `undefined`.** The docs flag this with a warning: augmenting `ContextVariableMap` makes `c.get('result')` type `string` **even in handlers where the middleware that sets it never ran**. Prefer the `Hono<{ Variables }>` generic or `createMiddleware<{ Variables }>` so the type is scoped to where the middleware is actually applied.
- **Forgetting to `return`.** `c.json(...)` builds a `Response`; it does nothing unless you `return` it. `c.status(201)` alone returns `undefined` → an empty response.
- **`c.set` is not shared across requests.** Don't try to use it as a cache or session store — it is torn down with the Context when the response returns. Use `c.env` bindings or an external store for that.
- **Order of `c.status` / `c.header` vs the return.** They can be set in any order before the `return`; the final `Response` reflects whatever was last set.

### Further Exploration

- Write a handler that reads a query param (`c.req.query('name')`) and returns it as JSON with a custom header and `201` status.
- Inject a value in middleware (`c.set('user', {...})`) typed via `Hono<{ Variables }>` and read it in the handler.
- Inspect `c.res` after `await next()` in a middleware and append an `X-Request-Id` header.

### Cross-references

- 🔗 [`NODE_HTTP_SERVER`](../NODE_HTTP_SERVER.md) — the raw `req`/`res` stream pair the Context replaces. There you `res.statusCode = 201; res.setHeader(); res.end()` imperatively; here you `return c.json(..., 201)`.
- 🔗 [`REST_API`](../REST_API.md) — the curriculum bundle that uses `c.req`/`c.json`/`c.header`/`c.status`/`c.set` end-to-end to build a typed REST resource.
- 🔗 [`../rust/axum/03-extractors-and-responses.md`](../rust/axum/03-extractors-and-responses.md) — Axum's typed extractors (`Json(payload): Json<CreateUser>`) and `(StatusCode::CREATED, Json(user))` tuple return. The compile-time cousin of Hono's runtime Context.
- 🔗 [`../rust/axum/06-dependency-injection-and-state.md`](../rust/axum/06-dependency-injection-and-state.md) — Axum `State` / request extensions, the analog of `c.set`/`c.get`/`c.env` for per-request and app-wide values.
- 🔗 [`../go/MIDDLEWARE_ROUTING.md`](../go/MIDDLEWARE_ROUTING.md) — Go's `http.ResponseWriter` + `*http.Request` is the two-object form; Go uses `context.Context` for per-request values (`r.Context().Value(key)`), the cousin of `c.set`/`c.get`.
