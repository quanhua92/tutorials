// fetch_http_client.ts — Phase 7 bundle (Async Runtime, HTTP & Realtime).
//
// GOAL (one line): show, by talking to a SELF-CONTAINED ephemeral `node:http`
// server, how the modern promise-based fetch() client behaves — Response
// status/ok/headers, body consumption (text/json, ONE read only), Request/
// Headers, the "HTTP errors are NOT rejections" payoff, AbortController +
// AbortSignal.timeout cancellation, redirect handling, and Response.body as a
// ReadableStream — pinning every claim as a check()'d invariant.
//
// This is the GROUND TRUTH for FETCH_HTTP_CLIENT.md. Every number, header
// value, status code and worked example in the guide is printed by this file.
// Change it -> re-run -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle is where it is): `fetch()` is the WHATWG Fetch
// standard API, shipped as a GLOBAL in Node 18+ (stable since Node 21) and
// backed by undici — the SAME promise-based, streaming-aware API browsers have
// had since 2015. It replaced the callback XMLHttpRequest and the third-party
// `node-fetch` polyfill. fetch() returns a Promise<Response> (🔗 PROMISES /
// ASYNC_AWAIT), is cancelable via AbortController (🔗 CONCURRENCY_PATTERNS),
// and exposes Response.body as a ReadableStream (🔗 STREAMS). This is the
// cross-language analog of Rust's `reqwest` and Go's `net/http` client. The
// SERVER side of the same HTTP wire is 🔗 NODE_HTTP_SERVER.
//
// DETERMINISM: every HTTP demo here spins up a tiny `node:http` server on an
// EPHEMERAL port (0), fetches from `127.0.0.1`, then closes the server (and
// all its open connections) before main() returns — so the process exits 0.
// We assert STATUS codes, header VALUES and body CONTENT (deterministic);
// timings (e.g. the 50ms abort delay) are NEVER printed or asserted.
//
// Run:
//     pnpm exec tsx fetch_http_client.ts   (or: just run fetch_http_client)

import http from "node:http";
import type { AddressInfo } from "node:net";

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// The deterministic bodies the self-contained server hands out. Centralising
// them lets both the server and the asserts reference ONE source of truth.
const HELLO_BODY = "hello, world";
const JSON_BODY = JSON.stringify({ msg: "hi", n: 42 });
const STREAM_BODY = "STREAM-ME-1234567890"; // 20 bytes, reassembled exactly

// startServer brings up the ephemeral self-contained HTTP server used by every
// section. It listens on port 0 (the OS hands back a free port) so two test
// runs — or a sibling bundle running in parallel — never collide. Returns the
// base URL; the caller MUST close() it before returning (see main()).
function startServer(): Promise<{ server: http.Server; base: string }> {
  const server = http.createServer((req, res) => {
    const url = req.url ?? "/";

    // GET routes — deterministic bodies + status codes.
    if (url === "/hello" && req.method === "GET") {
      res.writeHead(200, { "content-type": "text/plain" });
      res.end(HELLO_BODY);
      return;
    }
    if (url === "/json" && req.method === "GET") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON_BODY);
      return;
    }
    if (url === "/stream" && req.method === "GET") {
      res.writeHead(200, { "content-type": "text/plain" });
      res.end(STREAM_BODY);
      return;
    }
    if (url === "/missing" && req.method === "GET") {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("nope");
      return;
    }
    if (url === "/boom" && req.method === "GET") {
      res.writeHead(500, { "content-type": "text/plain" });
      res.end("server error");
      return;
    }
    if (url === "/redirect" && req.method === "GET") {
      res.writeHead(302, { location: "/target" });
      res.end();
      return;
    }
    if (url === "/target" && req.method === "GET") {
      res.writeHead(200, { "content-type": "text/plain" });
      res.end("final");
      return;
    }
    if (url === "/hang" && req.method === "GET") {
      // Intentionally NEVER respond. Drain the request so the socket does not
      // buffer, and rely on the client's abort/timeout to close it. Used to
      // demonstrate cancellation; the connection is force-closed on shutdown.
      req.resume();
      return;
    }

    // POST /echo — read the request body, parse it as JSON, echo it straight
    // back. This is the round-trip used to prove a POSTed JSON body survives
    // the wire intact (Section B).
    if (url === "/echo" && req.method === "POST") {
      const chunks: Buffer[] = [];
      req.on("data", (c: Buffer) => chunks.push(c));
      req.on("end", () => {
        const received = Buffer.concat(chunks).toString("utf8");
        res.writeHead(200, { "content-type": "application/json" });
        // Echo the parsed-then-restringified body so field order is stable.
        res.end(JSON.stringify(JSON.parse(received)));
      });
      return;
    }

    res.writeHead(200, { "content-type": "text/plain" });
    res.end("ok");
  });

  // Await the 'listening' event: server.address() is null until the socket is
  // actually bound. Port 0 => the OS chooses a free ephemeral port, surfaced
  // via server.address() once listening fires.
  return new Promise<{ server: http.Server; base: string }>((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address() as AddressInfo;
      resolve({ server, base: `http://127.0.0.1:${port}` });
    });
  });
}

// closeServer closes the listener AND force-destroys any still-open sockets
// (notably the never-responding /hang connections). Without closeAllConnections
// a hanging request would keep server.close()'s callback from ever firing and
// the process would hang on exit (non-zero). Node 18.2+.
function closeServer(server: http.Server): Promise<void> {
  return new Promise((resolve) => {
    server.close(() => resolve());
    server.closeAllConnections();
  });
}

// ============================================================================
// Section A — fetch basics: Response (status/ok/statusText/headers) + reading
// the body (text/json), and the ONE-READ-ONLY rule.
// ============================================================================

async function sectionA(base: string): Promise<void> {
  sectionBanner("A — fetch basics: Response + reading the body (one read only)");

  // fetch(url) returns a Promise<Response>. `await` resolves once the HEADERS
  // arrive — the BODY is NOT yet read; it streams lazily behind .body.
  const res = await fetch(`${base}/hello`);

  console.log("Response meta (headers arrived; body NOT yet read):");
  console.log(`  res.status     : ${res.status}`);
  console.log(`  res.ok         : ${res.ok}        (ok === status in 200-299)`);
  console.log(`  res.statusText : ${res.statusText}`);
  console.log(`  res.type       : ${res.type}            (basic = same-origin / non-CORS)`);
  console.log(`  res.url (path) : ${new URL(res.url).pathname}`);
  console.log(`  content-type   : ${res.headers.get("content-type")}`);

  check("GET 200 -> res.status === 200", res.status === 200);
  check("GET 200 -> res.ok === true", res.ok === true);
  check('GET 200 -> res.statusText === "OK"', res.statusText === "OK");
  check('res.type === "basic" (non-CORS)', res.type === "basic");
  check('headers.get("content-type") === "text/plain"', res.headers.get("content-type") === "text/plain");

  // Reading the body: .text() returns Promise<string>. This CONSUMES the body
  // — a Response body can be read exactly ONCE (bodyUsed flips to true).
  const text = await res.text();
  console.log("");
  console.log(`  await res.text() === ${JSON.stringify(text)}`);
  check("await res.text() === the server's body", text === HELLO_BODY);
  check("after .text(), res.bodyUsed === true", res.bodyUsed === true);

  // THE one-read-only rule, enforced: a SECOND read throws TypeError
  // ("Body is unusable: Body has already been read"). It does NOT return "".
  let secondReadThrew = false;
  try {
    await res.text();
  } catch {
    secondReadThrew = true;
  }
  check("second res.text() throws (body already consumed)", secondReadThrew === true);

  // .json() parses the body as JSON in one shot. (No manual JSON.parse needed.)
  const resJson = await fetch(`${base}/json`);
  const data = (await resJson.json()) as { msg: string; n: number };
  console.log("");
  console.log("  await res.json() round-trips an object:");
  console.log(`    data.msg === ${JSON.stringify(data.msg)}`);
  console.log(`    data.n   === ${data.n}`);
  check('await res.json().msg === "hi"', data.msg === "hi");
  check("await res.json().n === 42", data.n === 42);
}

// ============================================================================
// Section B — Request + Headers (case-insensitive) + POST with a JSON body.
// ============================================================================

async function sectionB(base: string): Promise<void> {
  sectionBanner("B — Request + Headers (case-insensitive) + POST JSON round-trip");

  // Headers keys are CASE-INSENSITIVE (per the WHATWG spec). Internally undici
  // lowercases keys; .get/.set/.has all normalise. .append joins duplicate
  // keys with ", " (so a header can legitimately have multiple values).
  const h = new Headers();
  h.set("Content-Type", "application/json");
  h.set("X-Custom", "one");
  h.append("X-Custom", "two");

  console.log("Headers (case-insensitive keys; .append joins with ', '):");
  console.log(`  h.get("content-type")  -> ${h.get("content-type")}`);
  console.log(`  h.get("CONTENT-TYPE")  -> ${h.get("CONTENT-TYPE")}   (same value, case-insensitive)`);
  console.log(`  h.get("x-custom")      -> ${JSON.stringify(h.get("x-custom"))}   (.append joined both)`);
  console.log(`  h.has("X-CUSTOM")      -> ${h.has("X-CUSTOM")}`);

  check('Headers keys are case-insensitive: get("content-type") === get("CONTENT-TYPE")', h.get("content-type") === h.get("CONTENT-TYPE"));
  check('h.get("content-type") === "application/json"', h.get("content-type") === "application/json");
  check('h.get("x-custom") === "one, two" (.append joined)', h.get("x-custom") === "one, two");
  check("h.has(\"X-CUSTOM\") === true (case-insensitive)", h.has("X-CUSTOM") === true);

  // A Request object packages url + method + headers + body. fetch() accepts a
  // URL string OR a Request. This decouples "describe the request" from "send
  // it" (the same Request can be inspected/replayed — modulo one-read body).
  const req = new Request(`${base}/echo`, {
    method: "POST",
    headers: h,
    body: JSON.stringify({ x: 1 }),
  });
  console.log("");
  console.log("Request object (url + method + headers + body):");
  console.log(`  req.method : ${req.method}`);
  console.log(`  req.url (path) : ${new URL(req.url).pathname}`);
  check('req.method === "POST"', req.method === "POST");
  check("req.url endsWith '/echo'", req.url.endsWith("/echo"));

  // POST the JSON; the /echo route reads the body and reflects it back. The
  // round-trip proves the body survived the wire byte-for-byte.
  const res = await fetch(req);
  const echoed = (await res.json()) as { x: number };
  console.log("");
  console.log("POST JSON round-trip (server echoed the body back):");
  console.log(`  echoed.x === ${echoed.x}`);
  check("POST status 200", res.status === 200);
  check("POST JSON body round-trips: echoed.x === 1", echoed.x === 1);

  // The full method set is supported via RequestInit.method. GET is default.
  console.log("");
  console.log("Methods (RequestInit.method):");
  const methods: ReadonlyArray<readonly [string, string]> = [
    ["GET", "default; no body"],
    ["POST", "create; has body"],
    ["PUT", "replace; has body"],
    ["PATCH", "partial update; has body"],
    ["DELETE", "remove; body allowed"],
  ];
  for (const [m, note] of methods) {
    const r = new Request(base, { method: m });
    console.log(`  ${m.padEnd(7)} -> req.method === ${r.method}   (${note})`);
    check(`new Request(base,{method:"${m}"}).method === "${m}"`, r.method === m);
  }
}

// ============================================================================
// Section C — THE payoff: HTTP errors are NOT rejections (res.ok === false for
// 4xx/5xx); only NETWORK failures reject (TypeError). fetch does NOT throw on
// HTTP errors — you MUST check res.ok / res.status yourself.
// ============================================================================

async function sectionC(base: string): Promise<void> {
  sectionBanner("C — HTTP errors are NOT rejections; network failures ARE (TypeError)");

  // A 404 RESOLVES a normal Response. res.ok is false, res.status is 404, but
  // the promise did NOT reject — execution continues right past the await.
  const r404 = await fetch(`${base}/missing`);
  console.log("404 (a real HTTP error):");
  console.log(`  r404.status : ${r404.status}`);
  console.log(`  r404.ok     : ${r404.ok}`);
  console.log("  -> the await RESOLVED (fetch did NOT throw on 404)");
  check("404 -> res.status === 404", r404.status === 404);
  check("404 -> res.ok === false", r404.ok === false);
  check("404 resolves (NOT a rejection — we reached this line)", true);

  // Same for 5xx: it is a resolved Response, not a thrown error.
  const r500 = await fetch(`${base}/boom`);
  console.log("");
  console.log("500 (server error):");
  console.log(`  r500.status : ${r500.status}`);
  console.log(`  r500.ok     : ${r500.ok}`);
  console.log("  -> also RESOLVES (check res.ok, do not rely on try/catch)");
  check("500 -> res.status === 500", r500.status === 500);
  check("500 -> res.ok === false", r500.ok === false);

  // Now the case that DOES reject: a NETWORK failure. We bring up an ephemeral
  // server, grab its port, close it, then fetch that (now-dead) port. The
  // connection is refused (ECONNREFUSED) and fetch rejects with a TypeError —
  // NOT an HTTP error, because no HTTP response ever existed.
  const tmp = http.createServer();
  await new Promise<void>((r) => tmp.listen(0, "127.0.0.1", r));
  const { port } = tmp.address() as AddressInfo;
  await new Promise<void>((r) => tmp.close(() => r()));
  let netErr: unknown = null;
  try {
    await fetch(`http://127.0.0.1:${port}/x`);
  } catch (e) {
    netErr = e;
  }
  const err = netErr as Error & { cause?: { code?: string } };
  console.log("");
  console.log("Network failure (ECONNREFUSED on a closed port):");
  console.log(`  throws          : ${err.constructor.name}`);
  console.log(`  err.name        : ${err.name}`);
  console.log(`  err.cause.code  : ${err.cause?.code}`);
  check("network failure rejects with a TypeError", err instanceof TypeError);
  check('network failure err.name === "TypeError"', err.name === "TypeError");
  check('err.cause.code === "ECONNREFUSED"', err.cause?.code === "ECONNREFUSED");

  console.log("");
  console.log("=> THE RULE: fetch rejects ONLY on network/permission failure.");
  console.log("   ALWAYS check res.ok (or res.status) for HTTP errors.");
}

// ============================================================================
// Section D — Cancellation: AbortController (manual abort -> AbortError) and
// AbortSignal.timeout (auto-timeout -> TimeoutError) + redirect handling.
// ============================================================================

async function sectionD(base: string): Promise<void> {
  sectionBanner("D — AbortController (AbortError) + AbortSignal.timeout (TimeoutError) + redirects");

  // 1) MANUAL abort. Pass an AbortSignal in RequestInit; calling .abort() on
  //    the controller rejects the in-flight fetch. The default reason is a
  //    DOMException named "AbortError". (🔗 CONCURRENCY_PATTERNS.)
  const ac = new AbortController();
  const p1 = fetch(`${base}/hang`, { signal: ac.signal });
  setTimeout(() => ac.abort(), 50);
  let abortErr: unknown = null;
  try {
    await p1;
  } catch (e) {
    abortErr = e;
  }
  const aErr = abortErr as DOMException;
  console.log("Manual abort (controller.abort()):");
  console.log(`  throws       : ${aErr?.constructor.name}`);
  console.log(`  err.name     : ${aErr?.name}`);
  check('manual abort -> fetch rejects', abortErr !== null);
  check('manual abort -> err.name === "AbortError"', aErr?.name === "AbortError");
  check("manual abort err is a DOMException", aErr instanceof DOMException);

  // 2) AUTO-timeout via AbortSignal.timeout(ms). This is the modern, built-in
  //    way to put a deadline on a fetch (fetch has NO timeout option of its
  //    own). CRUCIAL EXPERT DISTINCTION: a timeout rejects with a DOMException
  //    named "TimeoutError" — NOT "AbortError". So a handler that only checks
  //    name === "AbortError" will MISS timeouts.
  const p2 = fetch(`${base}/hang`, { signal: AbortSignal.timeout(50) });
  let timeoutErr: unknown = null;
  try {
    await p2;
  } catch (e) {
    timeoutErr = e;
  }
  const tErr = timeoutErr as DOMException;
  console.log("");
  console.log("AbortSignal.timeout(50) (auto-deadline):");
  console.log(`  throws       : ${tErr?.constructor.name}`);
  console.log(`  err.name     : ${tErr?.name}   <-- NOT "AbortError"`);
  check('AbortSignal.timeout -> fetch rejects', timeoutErr !== null);
  check('AbortSignal.timeout -> err.name === "TimeoutError"', tErr?.name === "TimeoutError");
  check("AbortSignal.timeout err is a DOMException", tErr instanceof DOMException);

  // 3) Redirects. redirect: "follow" (the DEFAULT) transparently follows 3xx;
  //    res.redirected === true and res.url is the FINAL url. "manual" returns
  //    the 3xx response itself (status + Location readable). "error" rejects
  //    with a TypeError when a redirect is encountered.
  const followRes = await fetch(`${base}/redirect`);
  const followBody = await followRes.text();
  console.log("");
  console.log('redirect: "follow" (the DEFAULT):');
  console.log(`  res.status    : ${followRes.status}   (followed to /target)`);
  console.log(`  res.redirected: ${followRes.redirected}`);
  console.log(`  res.url (path): ${new URL(followRes.url).pathname}`);
  console.log(`  await text()  : ${JSON.stringify(followBody)}`);
  check('redirect:"follow" -> res.status === 200 (followed)', followRes.status === 200);
  check('redirect:"follow" -> res.redirected === true', followRes.redirected === true);
  check('redirect:"follow" -> final body === "final"', followBody === "final");

  const manualRes = await fetch(`${base}/redirect`, { redirect: "manual" });
  console.log("");
  console.log('redirect: "manual" (hand back the 3xx):');
  console.log(`  res.status                : ${manualRes.status}`);
  console.log(`  res.ok                    : ${manualRes.ok}`);
  console.log(`  res.redirected            : ${manualRes.redirected}`);
  console.log(`  headers.get("location")   : ${manualRes.headers.get("location")}`);
  check('redirect:"manual" -> res.status === 302', manualRes.status === 302);
  check('redirect:"manual" -> res.ok === false', manualRes.ok === false);
  check('redirect:"manual" -> res.redirected === false', manualRes.redirected === false);
  check('redirect:"manual" -> location === "/target"', manualRes.headers.get("location") === "/target");

  let redirErr: unknown = null;
  try {
    await fetch(`${base}/redirect`, { redirect: "error" });
  } catch (e) {
    redirErr = e;
  }
  const rErr = redirErr as Error;
  console.log("");
  console.log('redirect: "error" (reject on redirect):');
  console.log(`  throws       : ${rErr?.constructor.name}`);
  console.log(`  err.name     : ${rErr?.name}`);
  check('redirect:"error" -> fetch rejects on redirect', redirErr !== null);
  check('redirect:"error" -> err.name === "TypeError"', rErr?.name === "TypeError");
}

// ============================================================================
// Section E — Response.body is a ReadableStream (stream chunks). (🔗 STREAMS.)
// Plus the cross-language view: Rust reqwest, Go net/http client.
// ============================================================================

async function sectionE(base: string): Promise<void> {
  sectionBanner("E — Response.body is a ReadableStream (stream chunks)");

  // res.body is a WHATWG ReadableStream<Uint8Array> (null only for opaque/
  // error responses). It lets you process the body CHUNK-BY-CHUNK as it
  // arrives, before the whole thing is buffered — essential for large files
  // and live streams. (🔗 STREAMS covers the stream primitives themselves.)
  const res = await fetch(`${base}/stream`);
  const body = res.body;

  console.log("Response.body (a lazy, chunked stream):");
  console.log(`  res.body === null            : ${body === null}`);
  console.log(`  res.body instanceof ReadableStream : ${body instanceof ReadableStream}`);
  check("res.body is not null", body !== null);
  check("res.body instanceof ReadableStream", body instanceof ReadableStream);

  // Consume the stream with a reader. Each .read() yields {done, value} where
  // value is a Uint8Array of one transport chunk. The number of chunks is NOT
  // deterministic (TCP framing decides), so we assert the REASSEMBLED bytes,
  // the total byte count, and the chunk type — never the chunk count.
  const reader = body!.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    total += value.byteLength;
  }
  const assembled = Buffer.concat(chunks).toString("utf8");

  console.log("");
  console.log("Consumed chunk-by-chunk via reader.read():");
  console.log(`  chunks read            : ${chunks.length}   (framing-dependent; NOT asserted)`);
  console.log(`  every chunk is Uint8Array : ${chunks.every((c) => c instanceof Uint8Array)}`);
  console.log(`  total bytes            : ${total}`);
  console.log(`  reassembled === STREAM_BODY : ${assembled === STREAM_BODY}`);
  check("at least one chunk was read", chunks.length >= 1);
  check("every chunk is a Uint8Array", chunks.every((c) => c instanceof Uint8Array));
  check("total bytes === STREAM_BODY byte length", total === Buffer.byteLength(STREAM_BODY));
  check("reassembled chunks === STREAM_BODY", assembled === STREAM_BODY);

  console.log("");
  console.log("Cross-language (same client shape elsewhere):");
  console.log("  Rust: reqwest::Client -> .send(req).await?.text().await?  (🔗 ../rust/REQWEST_CLIENT.md)");
  console.log("  Go  : http.Client.Do(req) -> *http.Response -> io.ReadAll(body)  (🔗 ../go/NET_HTTP.md)");
}

// ============================================================================
// main — bring up the self-contained server, run every section, shut it down.
// ============================================================================

async function main(): Promise<void> {
  console.log("fetch_http_client.ts — Phase 7 bundle (the modern HTTP client).");
  console.log("Every value below is computed against a self-contained ephemeral");
  console.log("node:http server (port 0); the .md guide pastes it verbatim.");
  console.log("");
  console.log("Node's global fetch() is backed by undici (stable since Node 21).");
  console.log("It returns a Promise<Response> — promise-based, streaming-aware,");

  const { server, base } = await startServer();
  try {
    await sectionA(base);
    await sectionB(base);
    await sectionC(base);
    await sectionD(base);
    await sectionE(base);
  } finally {
    // ALWAYS close: even if a section throws, shut the server (and its open
    // /hang sockets) so the process exits 0 instead of hanging.
    await closeServer(server);
  }
  sectionBanner("DONE — all sections printed");
}

await main();
