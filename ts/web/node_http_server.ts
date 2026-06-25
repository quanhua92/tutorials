// node_http_server.ts — Phase 7 bundle (Async Runtime, HTTP & Realtime).
//
// GOAL (one line): show, by spinning up a real `node:http` server on an
// EPHEMERAL port (0) and firing self-requests at it, that
// `http.createServer((req, res) => {...})` is the lowest-level HTTP server in
// Node — a callback per request where `req` (IncomingMessage) is a Readable
// stream of the request and `res` (ServerResponse) is a Writable stream for the
// response — pinning routing, the body-stream read, the chunked write, header
// lowercasing, status codes, graceful `server.close()`, and the one-thread
// concurrency model as `check()`'d invariants.
//
// This is the GROUND TRUTH for NODE_HTTP_SERVER.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run ->
// re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists, and what it is the FOUNDATION of):
// `node:http`'s `createServer((req, res) => {...})` is the substrate every Node
// web framework builds on. Express / Hono / Fastify (🔗 REST_API) add a ROUTER
// (method+path matching with params) and a MIDDLEWARE chain ON TOP of this exact
// callback; under the hood each request still arrives as one (req, res) pair
// dispatched by the event loop. Doing it by hand teaches the three things a
// framework hides from you:
//   1. ROUTING — `node:http` ships NO router. You switch on `req.method` +
//      `req.url` yourself. (Go's net/http has the same shape: a Handler fn +
//      a ServeMux you register patterns on — 🔗 ../go/NET_HTTP.md, the model.)
//   2. STREAMING — `req` is a Readable STREAM (the request body arrives in
//      chunks) and `res` is a Writable STREAM (you `.write()` chunks, then
//      `.end()`). Nothing is buffered for you. (🔗 STREAMS — req/res ARE the
//      legacy Node stream API.)
//   3. THE EVENT LOOP — one thread dispatches every (req, res) callback. There
//      is no thread-per-request (that's Go's goroutine-per-request, or the
//      classic Apache worker-pool). Node scales via non-blocking I/O: while one
//      request waits on a socket read, the loop serves the next. (🔗 EVENT_LOOP.)
//
// DETERMINISM NOTE (§4.2 rule 4 + the brief's port-0 rule): every server in this
// file listens on port 0 (the OS assigns an EPHEMERAL port — never printed, so
// output is stable). Each section makes a SELF-CONTAINED request via the global
// `fetch` (Node ≥18, backed by undici), ASSERTS status / headers / body (never
// timings), then `server.close()` + `server.closeAllConnections()` + `await`
// before returning — so the process drains fully and exits 0. The ephemeral port
// number and wall-clock time are NEVER printed. Resolution ORDER is deterministic
// (the loop is single-threaded; Promise.all resolves in input order).
//
// Run:
//     pnpm exec tsx node_http_server.ts   (or: just run node_http_server)

import http from "node:http";
import http2 from "node:http2";

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts a boolean invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// listen(server) binds to port 0 on the loopback and resolves to the EPHEMERAL
// port the OS assigned. Port 0 = "give me any free port" — never a fixed port
// (which could collide with a sibling process or a stale server).
function listen(server: http.Server): Promise<number> {
  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      if (addr !== null && typeof addr === "object") {
        resolve(addr.port);
      } else {
        reject(new Error("server.address() did not return an AddressInfo"));
      }
    });
  });
}

// stop(server) is the DETERMINISTIC teardown: `server.close()` stops accepting
// NEW connections and resolves once all CURRENT ones have drained — but a
// keep-alive socket (fetch/undici pools them!) would keep `close()` hanging
// until the keepAliveTimeout. `closeAllConnections()` (Node ≥18.2.0) force-
// closes every socket, so `close()`'s callback fires promptly and the process
// exits 0. Per the Node docs, closeAllConnections() is called AFTER close().
function stop(server: http.Server): Promise<void> {
  return new Promise((resolve) => {
    server.close(() => resolve());
    server.closeAllConnections();
  });
}

// reqUrl / reqMethod extract the always-present-at-runtime url/method as plain
// strings. @types/node types IncomingMessage.url and .method as `string |
// undefined` (they are unset on the CLIENT side of an IncomingMessage); on the
// server side they are always set, so we coalesce to "" for safe switch/compare.
function reqUrl(req: http.IncomingMessage): string {
  return req.url ?? "";
}
function reqMethod(req: http.IncomingMessage): string {
  return req.method ?? "";
}

// oneStrHeader pulls a single-string header value out of req.headers (whose
// values are `string | string[] | undefined`). Only headers we send once are
// read this way; duplicate/repeated headers would arrive as string[].
function oneStrHeader(req: http.IncomingMessage, name: string): string {
  const v = req.headers[name];
  return typeof v === "string" ? v : "";
}

// ============================================================================
// Section A — createServer: IncomingMessage (req) + ServerResponse (res)
// ============================================================================
//
// `http.createServer(requestListener)` returns an http.Server (a subclass of
// net.Server). The requestListener is `(req, res) => {...}` — invoked ONCE per
// request, on the event loop's main thread. `req` (http.IncomingMessage) is a
// Readable stream carrying the request line + headers + body; `res`
// (http.ServerResponse) is a Writable stream you fill and `.end()`. This
// section pins the round-trip: a self-request returns status 200 + the body we
// wrote, and the handler sees the method / url / header we sent.

function sectionA(): Promise<void> {
  sectionBanner("A — createServer: IncomingMessage (req) + ServerResponse (res)");

  // The handler captures what it sees (for assertion AFTER the self-request
  // resolves — by then the handler has run, because fetch only resolves once
  // res.end() was called and the full body arrived).
  const seen: { method: string; url: string; xdemo: string } = {
    method: "",
    url: "",
    xdemo: "",
  };

  const server = http.createServer((req: http.IncomingMessage, res: http.ServerResponse) => {
    seen.method = reqMethod(req);
    seen.url = reqUrl(req);
    seen.xdemo = oneStrHeader(req, "x-demo");
    res.statusCode = 200;
    res.setHeader("Content-Type", "text/plain");
    res.end("hello-from-server");
  });

  return (async () => {
    const port = await listen(server);
    console.log("http.createServer((req, res) => {...}) -> an http.Server;");
    console.log("server.listen(0) bound to an EPHEMERAL port (the number is");
    console.log("OS-assigned and intentionally NOT printed, for determinism).");

    // Self-request: the global fetch (Node >= 18, undici-backed) plays the
    // CLIENT. We send a custom header to prove header round-trip.
    const response = await fetch(`http://127.0.0.1:${port}/`, {
      headers: { "x-demo": "hello" },
    });
    const body: string = await response.text();

    console.log("");
    console.log("What the HANDLER saw (IncomingMessage):");
    console.log(`  req.method                          = ${JSON.stringify(seen.method)}`);
    console.log(`  req.url                             = ${JSON.stringify(seen.url)}`);
    console.log(`  req.headers["x-demo"]               = ${JSON.stringify(seen.xdemo)}`);
    console.log("");
    console.log("What the CLIENT saw (the Response we built with ServerResponse):");
    console.log(`  res.statusCode  -> response.status  = ${response.status}`);
    console.log(`  res.setHeader("Content-Type"...)    = ${JSON.stringify(response.headers.get("content-type"))}`);
    console.log(`  res.end(body)    -> response.text() = ${JSON.stringify(body)}`);

    check('req.method === "GET"', seen.method === "GET");
    check('req.url === "/"', seen.url === "/");
    check('req.headers["x-demo"] === "hello" (header round-trips)', seen.xdemo === "hello");
    check("res.statusCode 200 round-trips to response.status", response.status === 200);
    check('setHeader("Content-Type") round-trips', response.headers.get("content-type") === "text/plain");
    check('res.end(body) round-trips verbatim', body === "hello-from-server");

    await stop(server);
    check("server closed (section A teardown)", true);
  })();
}

// ============================================================================
// Section B — Hand routing (method + url switch) + status codes
// ============================================================================
//
// `node:http` ships NO router. Routing is a hand-rolled switch on `req.method`
// + `req.url` — exactly the thing Express/Hono/Fastify replace with a path-
// matcher (🔗 REST_API). Status codes are set by assigning `res.statusCode`
// (201 Created, 404 Not Found, ...). This section pins four routes diverging
// by method + path, including a 404 fallthrough.

function sectionB(): Promise<void> {
  sectionBanner("B — Hand routing (method + url switch) + status codes");

  const server = http.createServer((req: http.IncomingMessage, res: http.ServerResponse) => {
    const method = reqMethod(req);
    const url = reqUrl(req);
    if (method === "GET" && url === "/users") {
      res.statusCode = 200;
      res.end("users-list");
      return;
    }
    if (method === "GET" && url === "/posts") {
      res.statusCode = 200;
      res.end("posts-list");
      return;
    }
    if (method === "POST" && url === "/users") {
      res.statusCode = 201; // 201 Created
      res.end("created");
      return;
    }
    // fallthrough: nothing matched -> 404
    res.statusCode = 404;
    res.end("not-found");
  });

  return (async () => {
    const port = await listen(server);
    console.log("No built-in router: a switch on req.method + req.url is the");
    console.log("whole routing layer. Each branch sets res.statusCode + body.");

    const r1 = await fetch(`http://127.0.0.1:${port}/users`);
    const r2 = await fetch(`http://127.0.0.1:${port}/posts`);
    const r3 = await fetch(`http://127.0.0.1:${port}/users`, { method: "POST" });
    const r4 = await fetch(`http://127.0.0.1:${port}/nope`);

    const b1 = await r1.text();
    const b2 = await r2.text();
    const b3 = await r3.text();
    const b4 = await r4.text();

    console.log("");
    console.log("route                   -> status  body");
    console.log("-----------------------   ------   -----------");
    console.log(`GET  /users             ->   ${r1.status}     ${JSON.stringify(b1)}`);
    console.log(`GET  /posts             ->   ${r2.status}     ${JSON.stringify(b2)}`);
    console.log(`POST /users             ->   ${r3.status}     ${JSON.stringify(b3)}`);
    console.log(`GET  /nope (fallthrough)->   ${r4.status}     ${JSON.stringify(b4)}`);

    check('GET /users -> 200 "users-list"', r1.status === 200 && b1 === "users-list");
    check('GET /posts -> 200 "posts-list" (different route, different body)', r2.status === 200 && b2 === "posts-list");
    check('POST /users -> 201 "created" (method distinguishes from GET /users)', r3.status === 201 && b3 === "created");
    check('GET /nope -> 404 "not-found" (no match -> fallthrough)', r4.status === 404 && b4 === "not-found");

    await stop(server);
    check("server closed (section B teardown)", true);
  })();
}

// ============================================================================
// Section C — Request body (req is a Readable stream) + streaming response
// ============================================================================
//
// Two streams in one callback. (1) READING the body: `req` is a Readable
// stream — the body is NOT handed to you whole; you collect `data` chunks and
// assemble on `end` (or use `req.on("readable")` / async iteration). (2) WRITING
// the response: `res.write(chunk)` can be called MANY times before `res.end()`
// — this is how large files and Server-Sent Events stream without buffering the
// whole payload in memory. This section reads a POST body and replies with a
// multi-chunk streamed response.

function sectionC(): Promise<void> {
  sectionBanner("C — Request body (req is a Readable stream) + streaming response");

  const server = http.createServer((req: http.IncomingMessage, res: http.ServerResponse) => {
    if (reqMethod(req) === "POST" && reqUrl(req) === "/echo") {
      // req is a Readable stream: collect the body chunk-by-chunk.
      const chunks: Buffer[] = [];
      req.on("data", (chunk: Buffer) => {
        chunks.push(chunk);
      });
      req.on("end", () => {
        const received: string = Buffer.concat(chunks).toString("utf8");
        res.setHeader("Content-Type", "text/plain");
        // Streaming the RESPONSE: multiple res.write() calls before res.end().
        res.write("chunk1\n");
        res.write("chunk2\n");
        res.end("echoed:" + received);
      });
      return;
    }
    res.statusCode = 404;
    res.end("not-found");
  });

  return (async () => {
    const port = await listen(server);
    console.log("req is a Readable STREAM: the POST body arrives as `data` chunks,");
    console.log("assembled on `end`. res is a Writable STREAM: res.write() can be");
    console.log("called many times before res.end() — that is response streaming.");

    const response = await fetch(`http://127.0.0.1:${port}/echo`, {
      method: "POST",
      body: "ping",
    });
    const body: string = await response.text();
    const lines: string[] = body.split("\n");

    console.log("");
    console.log("POST /echo with body \"ping\" -> streamed response:");
    console.log(`  full response body = ${JSON.stringify(body)}`);
    console.log(`  split on "\\n"      = [${lines.map((l) => JSON.stringify(l)).join(", ")}]`);
    console.log("  (chunk1 and chunk2 were two separate res.write() calls; the");
    console.log("   final line is res.end() with the echoed request body.)");

    check("request body read from the req stream and echoed", body.endsWith("echoed:ping"));
    check("response was STREAMED (>=2 res.write() chunks before end)", lines.length >= 3 && lines[0] === "chunk1" && lines[1] === "chunk2");
    check("streamed response reassembles to the exact bytes", body === "chunk1\nchunk2\nechoed:ping");

    await stop(server);
    check("server closed (section C teardown)", true);
  })();
}

// ============================================================================
// Section D — Headers (case-insensitive) + graceful server.close() + errors
// ============================================================================
//
// Three production concerns in one section:
//   - HEADERS: Node lowercases all INCOMING header NAMES (values are untouched).
//     So a client sending `X-Mixed-Case` is read as `req.headers["x-mixed-case"]`;
//     the original-case key is ABSENT. (HTTP field names are case-insensitive per
//     RFC 9110; HTTP/2 RFC 9113 mandates lowercase on the wire.)
//   - GRACEFUL CLOSE: `server.close()` stops accepting NEW connections and
//     resolves once current ones drain; `closeAllConnections()` (Node >=18.2)
//     force-closes keep-alive sockets so the close resolves promptly.
//   - ERROR HANDLING: a throw INSIDE the request handler must be caught there
//     (the production pattern: try/catch -> 500). An UNCAUGHT throw destroys the
//     socket but does NOT crash the server — documented below, not executed
//     (executing it would emit nondeterministic stderr noise).

function sectionD(): Promise<void> {
  sectionBanner("D — Headers (case-insensitive) + graceful server.close() + errors");

  const seen: { lower: string; original: string } = { lower: "", original: "" };

  const server = http.createServer((req: http.IncomingMessage, res: http.ServerResponse) => {
    const url = reqUrl(req);

    // Header names arrive LOWERCASED. We sent "X-Mixed-Case: works".
    seen.lower = oneStrHeader(req, "x-mixed-case");
    // The original-case key is NOT a property of req.headers:
    seen.original = typeof req.headers["X-Mixed-Case"] === "undefined" ? "absent" : "present";

    if (url === "/broken") {
      // The recommended pattern: catch errors IN the handler -> 500.
      // (An UNCAUGHT throw would destroy this socket but leave the server up;
      // we don't execute that here to keep output deterministic.)
      try {
        throw new Error("boom");
      } catch {
        res.statusCode = 500;
        res.end("error-caught");
        return;
      }
    }

    res.setHeader("X-Response-Header", "resp");
    res.statusCode = 200;
    res.end("ok");
  });

  return (async () => {
    const port = await listen(server);
    console.log("Header NAMES are lowercased by Node: a client's `X-Mixed-Case`");
    console.log("is read as req.headers[\"x-mixed-case\"]; the original-case key");
    console.log("is absent. HTTP field names are case-insensitive (RFC 9110).");

    // 1) header lowercasing + response header round-trip
    const r1 = await fetch(`http://127.0.0.1:${port}/`, {
      headers: { "X-Mixed-Case": "works" },
    });
    await r1.text();
    console.log("");
    console.log(`  sent header "X-Mixed-Case: works":`);
    console.log(`    req.headers["x-mixed-case"]   = ${JSON.stringify(seen.lower)}`);
    console.log(`    req.headers["X-Mixed-Case"]   = ${JSON.stringify(seen.original)} (original case NOT stored)`);
    console.log(`    res.setHeader round-trip      = ${JSON.stringify(r1.headers.get("x-response-header"))}`);

    check('incoming header name lowercased: "x-mixed-case" === "works"', seen.lower === "works");
    check('original-case key "X-Mixed-Case" is absent (Node lowercases)', seen.original === "absent");
    check('outgoing res.setHeader round-trips to the client', r1.headers.get("x-response-header") === "resp");

    // 2) error handling: a caught throw -> 500, server stays up
    const r2 = await fetch(`http://127.0.0.1:${port}/broken`);
    const b2 = await r2.text();
    console.log("");
    console.log(`  GET /broken (handler throws, caught -> 500):`);
    console.log(`    status = ${r2.status}  body = ${JSON.stringify(b2)}`);
    check("caught throw in handler -> 500 (recommended pattern)", r2.status === 500 && b2 === "error-caught");

    // 3) the server SURVIVED the error: a normal request still works
    const r3 = await fetch(`http://127.0.0.1:${port}/`);
    await r3.text();
    check("server still serves after an in-handler error (no crash)", r3.status === 200);

    // 4) graceful close: server.listening flips to false after stop()
    console.log("");
    console.log("  graceful close: server.close() + closeAllConnections() + await");
    console.log(`    server.listening before close = ${server.listening}`);
    await stop(server);
    console.log(`    server.listening after  close = ${server.listening}`);
    check("server.listening === false after graceful close", server.listening === false);
  })();
}

// ============================================================================
// Section E — http2 (brief) + the non-blocking one-thread-scales model
// ============================================================================
//
// http2 (the binary-framed protocol): `http2.createSecureServer` (h2 over TLS,
// the normal case) and `http2.createServer` (plaintext h2c, mostly for testing)
// are the framed/multiplexed siblings of http.createServer. We do NOT run a live
// h2 server here (TLS cert setup + h2 client complexity would add nondeterminism
// without teaching more) — we verify the API surface and document the model.
//
// THE SCALING MODEL: `node:http` runs on ONE thread (the V8 main thread + the
// libuv event loop). Each (req, res) callback is dispatched on that thread; no
// new thread is spawned per request. While one callback awaits a socket read,
// the loop serves the next — non-blocking I/O is how Node scales. We prove it by
// firing 3 concurrent requests at the same server and showing all resolve.

function sectionE(): Promise<void> {
  sectionBanner("E — http2 (brief) + the non-blocking one-thread-scales model");

  // Verify the http2 API surface (createSecureServer is the TLS h2 entry point).
  console.log("http2 — the binary-framed, multiplexed sibling of node:http:");
  console.log(`  typeof http2.createServer       = ${typeof http2.createServer}`);
  console.log(`  typeof http2.createSecureServer = ${typeof http2.createSecureServer}`);
  console.log("  (h2 runs over TLS in production via createSecureServer; a single");
  console.log("   TCP connection multiplexes many concurrent streams.)");
  check('typeof http2.createServer === "function"', typeof http2.createServer === "function");
  check('typeof http2.createSecureServer === "function"', typeof http2.createSecureServer === "function");

  const server = http.createServer((req: http.IncomingMessage, res: http.ServerResponse) => {
    // Echo the path so each concurrent request is distinguishable.
    res.statusCode = 200;
    res.end("r:" + reqUrl(req));
  });

  return (async () => {
    const port = await listen(server);
    console.log("");
    console.log("Non-blocking I/O on ONE thread: fire 3 requests CONCURRENTLY");
    console.log("(Promise.all). The single-threaded loop interleaves them; none");
    console.log("blocks another. (Contrast: Go spawns a goroutine per request.)");

    const paths: ReadonlyArray<string> = ["/0", "/1", "/2"];
    const responses: Response[] = await Promise.all(
      paths.map((p) => fetch(`http://127.0.0.1:${port}${p}`)),
    );
    const bodies: string[] = await Promise.all(responses.map((r) => r.text()));
    // Sort for deterministic print order (Promise.all already preserves input
    // order, but sorting makes the invariant explicit and stable).
    const sorted: string[] = [...bodies].sort();

    console.log("");
    console.log("3 concurrent requests, response bodies (sorted):");
    for (const b of sorted) {
      console.log(`  ${JSON.stringify(b)}`);
    }

    check("all 3 concurrent requests resolved", bodies.length === 3);
    check("every concurrent request got 200", responses.every((r) => r.status === 200));
    check(
      "concurrent bodies are exactly {r:/0, r:/1, r:/2}",
      sorted.join(",") === "r:/0,r:/1,r:/2",
    );

    await stop(server);

    console.log("");
    console.log("Cross-language (the model Node's http approximates):");
    console.log("  Go     net/http : a Handler(w, r) fn + a ServeMux you register");
    console.log("                    patterns on — the CLEANEST stdlib HTTP model.");
    console.log("                    Each request runs on its own goroutine.");
    console.log("  Rust   hyper/axum: axum builds on hyper — a typed, extractive");
    console.log("                    model (handlers take typed extractors) far");
    console.log("                    richer than node:http's raw req/res streams.");
    console.log("  Node   node:http: one (req,res) callback per request, dispatched");
    console.log("                    on the single-threaded event loop (no goroutine).");
    check("cross-language HTTP model summarized", true);
    check("server closed (section E teardown)", true);
  })();
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("node_http_server.ts — Phase 7 bundle (Async Runtime, HTTP & Realtime).");
  console.log("Every value below is produced by spinning up a real `node:http`");
  console.log("server on an EPHEMERAL port (0), firing self-requests, asserting");
  console.log("status / headers / body, then closing. Nothing is hand-computed;");
  console.log("the ephemeral port + wall-clock time are NEVER printed.");
  console.log("");
  console.log("Reminder: node:http ships NO router and NO body parser — routing is");
  console.log("a switch on req.method + req.url, and the body is a Readable stream.");
  console.log("That is precisely what Express / Hono / Fastify add on top (REST_API).");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

await main();
