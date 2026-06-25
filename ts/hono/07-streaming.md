# Streaming Responses: SSE, `streamText`, and the `StreamingApi`

**Doc Source**: [Hono — Streaming Helper (`hono/streaming`)](https://hono.dev/docs/helpers/streaming)

## The Core Concept: Why This Example Exists

**The Problem:** The default HTTP model assumes the server computes the whole response, then sends it. That breaks for three increasingly common cases: (1) **large or slow payloads** — AI token streams, log tails, generated reports — where you want the client to render the first bytes while the server is still producing the rest; (2) **live updates** — stock prices, build logs, server-clock ticks — where the server keeps pushing without the client re-polling; (3) **arbitrary byte streams** — piping a `ReadableStream` from a fetch, a file, or a transform pipeline straight to the response. Doing this by hand means wrangling `Transfer-Encoding: chunked`, `Content-Type` headers, the SSE wire format (`data: ...\n\n`), backpressure, and abort detection — and getting any of it wrong silently breaks the client.

**The Solution:** Hono's Streaming Helper (`hono/streaming`) gives three primitives that hide the wire format and let you write `await stream.write(...)` in a single async callback:

- **`streamSSE(c, cb)`** — Server-Sent Events. Sets `Content-Type: text/event-stream`, handles the `id:`/`event:`/`data:` framing, and reconnect-with-`Last-Event-ID`.
- **`streamText(c, cb)`** — chunked `text/plain` with `nosniff` (the AI-token / log-tail case).
- **`stream(c, cb)`** — a generic `StreamingApi` over `Uint8Array` for arbitrary binary or text.

All three take the same shape: a callback that receives a `stream` object you `await`-write to. They share an `onAbort` hook and an inline error handler — because, as the docs warn, *"`app.onError` will not be triggered"* once the stream has started (the `200` headers are already on the wire).

Think of these helpers as **a faucet you control from `async` code**: turn it on with `streamSSE(c, ...)`, pour bytes with `await stream.writeSSE(...)`, sleep with `await stream.sleep(1000)`, and stop when the client closes the connection (`stream.aborted`). The faucet handles the plumbing; you handle the water.

## Practical Walkthrough: Code Breakdown

### `streamSSE` — Server-Sent Events

The flagship helper for one-way server push. The official example sends a clock tick every second:

```ts
import { streamSSE } from 'hono/streaming'

const app = new Hono()
let id = 0

app.get('/sse', async (c) => {
  return streamSSE(c, async (stream) => {
    while (!stream.aborted) {
      const message = `It is ${new Date().toISOString()}`
      await stream.writeSSE({
        data: message,
        event: 'time-update',
        id: String(id++),
      })
      await stream.sleep(1000)
    }
  })
})
```

*Source: [hono.dev/docs/helpers/streaming#streamsse](https://hono.dev/docs/helpers/streaming#streamsse)*

What this does on the wire — `writeSSE` serializes the object to the SSE text format (`event: time-update\n` + `id: <n>\n` + `data: It is 2026-06-25T...\n` + `\n`). The browser's `EventSource` parses it back into events. The full SSE format (one-way vs. WebSocket decision, `Last-Event-ID` reconnect, the `\n\n` framing) is covered in 🔗 [`../WEBSOCKETS_SSE.md`](../WEBSOCKETS_SSE.md) — this file is the *server-side Hono* view of it.

Key helpers on the SSE stream object:
- **`stream.writeSSE({ data, event, id })`** — emits one event. `event` and `id` are optional.
- **`stream.sleep(ms)`** — `await`-able delay that respects abort (returns early if the client disconnects).
- **`stream.aborted`** — boolean; loop on `while (!stream.aborted)` rather than `while (true)`, or you'll keep writing into a closed socket.
- **`stream.onAbort(() => ...)`** — cleanup hook for releasing resources.

### `streamText` — chunked text/plain

For token-by-token text output (LLM streaming, log tails). Sets three headers automatically — `Content-Type: text/plain`, `Transfer-Encoding: chunked`, `X-Content-Type-Options: nosniff`:

```ts
import { streamText } from 'hono/streaming'

app.get('/streamText', (c) => {
  return streamText(c, async (stream) => {
    await stream.writeln('Hello')    // writes "Hello\n"
    await stream.sleep(1000)
    await stream.write(`Hono!`)      // writes "Hono!" (no newline)
  })
})
```

*Source: [hono.dev/docs/helpers/streaming#streamtext](https://hono.dev/docs/helpers/streaming#streamtext)*

> ⚠️ **Pitfall — Cloudflare Workers + Wrangler.** The docs note streaming "may not work well on Wrangler." The fix is to force-disable compression so the bytes flush instead of buffering:
>
> ```ts
> app.get('/streamText', (c) => {
>   c.header('Content-Encoding', 'Identity')
>   return streamText(c, async (stream) => {
>     // ...
>   })
> })
> ```
>
> *Source: [hono.dev/docs/helpers/streaming#streamtext](https://hono.dev/docs/helpers/streaming#streamtext)*

### `stream` — arbitrary `StreamingApi`

The most general form. You write `Uint8Array` chunks, or pipe another `ReadableStream` through directly:

```ts
import { stream } from 'hono/streaming'

app.get('/stream', (c) => {
  return stream(c, async (stream) => {
    stream.onAbort(() => {
      console.log('Aborted!')
    })
    await stream.write(new Uint8Array([0x48, 0x65, 0x6c, 0x6c, 0x6f]))  // "Hello"
    await stream.pipe(anotherReadableStream)                            // pipe-through
  })
})
```

*Source: [hono.dev/docs/helpers/streaming#stream](https://hono.dev/docs/helpers/streaming#stream)*

Underneath, these helpers return a standard `Response` whose `body` is a `ReadableStream` (🔗 [`../STREAMS.md`](../STREAMS.md)). That means `await stream.pipe(other)` is the same backpressure-aware pipe you'd build by hand with `ReadableStream.pipeThrough` — the producer pauses when the consumer is slow, exactly as covered in the backpressure section of 🔗 [`../ASYNC_PATTERNS.md`](../ASYNC_PATTERNS.md).

### The error path: a *third* handler, not `app.onError`

This is the sharpest edge in the streaming API and the docs flag it explicitly. **Once the streaming callback has started, the response status and headers are already flushed — they cannot be replaced.** So if your callback throws, Hono will **not** route it through `app.onError` (which assumes it can still rewrite the whole response). Instead, you supply an inline error handler as the **third argument** to the helper:

```ts
app.get('/stream', (c) => {
  return stream(
    c,
    async (stream) => {
      stream.onAbort(() => {
        console.log('Aborted!')
      })
      await stream.write(new Uint8Array([0x48, 0x65, 0x6c, 0x6c, 0x6f]))
      await stream.pipe(anotherReadableStream)
    },
    (err, stream) => {
      stream.writeln('An error occurred!')
      console.error(err)
    }
  )
})
```

*Source: [hono.dev/docs/helpers/streaming#error-handling](https://hono.dev/docs/helpers/streaming#error-handling)*

The official warning, verbatim:

> If the callback function of the streaming helper throws an error, the `onError` event of Hono will not be triggered. `onError` is a hook to handle errors before the response is sent and overwrite the response. However, when the callback function is executed, the stream has already started, so it cannot be overwritten.

The stream is closed automatically after the error callback runs. This is the **streaming-specific** chapter of the error story started in 🔗 [`./05-error-handling.md`](./05-error-handling.md) — read both.

### Choosing between SSE, streamText, and raw stream

```mermaid
graph TD
    A[Need to push data after first byte?] -->|No| B["Return a normal Response<br/>(c.json / c.text)"]
    A -->|Yes| C{Consumer protocol?}
    C -->|Browser EventSource<br/>or one-way live feed| D[streamSSE<br/>text/event-stream]
    C -->|Plain text stream<br/>(LLM tokens, logs)| E[streamText<br/>chunked text/plain]
    C -->|Binary or arbitrary| F[stream<br/>StreamingApi]
    C -->|Bidirectional, full-duplex| G["Use WebSockets instead<br/>🔗 WEBSOCKETS_SSE"]
    D --> H{Need backpressure / abort?}
    E --> H
    F --> H
    H -->|Yes| I["Use stream.sleep, stream.aborted,<br/>stream.onAbort — handled for you"]
```

## Cross-References

> 🔗 [`../WEBSOCKETS_SSE.md`](../WEBSOCKETS_SSE.md) — owns the **protocol-level** treatment this file *uses*: the SSE wire format (`event:`/`id:`/`data:`/`\n\n`), `Last-Event-ID` reconnect semantics, and the **one-way SSE vs. bidirectional WebSocket** decision tree. This file is the *Hono API* surface; that file is the *HTTP* surface.
>
> 🔗 [`../STREAMS.md`](../STREAMS.md) — the `ReadableStream` / `WritableStream` / `pipeThrough` primitives that `stream()` and `stream.pipe()` are built on. A `stream` helper response *is* a `Response` whose `body` is a `ReadableStream`.
>
> 🔗 [`../ASYNC_PATTERNS.md`](../ASYNC_PATTERNS.md) — backpressure: the producer-consumer contract that keeps a fast `stream.write` loop from OOMing when the client is slow. The `StreamingApi` honors this automatically; you should still `await` every write rather than fire-and-forget.
>
> 🔗 [`./05-error-handling.md`](./05-error-handling.md) — the **other** half of the error story. Non-streaming handlers funnel through `app.onError`; streaming callbacks use the inline third-argument handler. You need both.
>
> 🔗 [`../OBSERVABILITY.md`](../OBSERVABILITY.md) — `stream.onAbort` is the right place to emit an "aborted" span / metric; without it a client disconnect looks identical to a successful completion in your logs.
>
> 🔗 [`../../rust/axum/07-websockets-and-real-time-communication.md`](../../rust/axum/07-websockets-and-real-time-communication.md) — axum uses `axum::response::sse::Sse` (a streaming `IntoResponse`) for the SSE case and `tokio_stream::StreamExt` for arbitrary streaming. Same shape (`Stream<Item = Result<Event, E>>`), Rust's ownership model replaces Hono's `await`-write loop.
>
> 🔗 [`../../go/STREAMING_WEBSOCKETS.md`](../../go/STREAMING_WEBSOCKETS.md) — Go's `net/http` lets you flush chunked bytes manually via `http.Flusher`; SSE is typically hand-rolled (`fmt.Fprintf(w, "data: %s\n\n", msg); f.Flush()`). Hono's `streamSSE` is the framework doing that for you.
