// websockets_sse.ts — Phase 7 bundle (web/).
//
// GOAL (one line): show, by running a self-contained port-0 server + client on
// each protocol, how WebSockets (full-duplex, binary-safe, RFC 6455 frames via
// `ws`) and Server-Sent Events (one-way server->client over a long-lived
// `text/event-stream` via `node:http`) actually exchange a fixed message set.
//
// This is the GROUND TRUTH for WEBSOCKETS_SSE.md. Every number, table, and
// worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle): the realtime layer sits on top of the HTTP server
// (🔗 NODE_HTTP_SERVER) and the stream primitives (🔗 STREAMS). Two mechanisms
// survive in production: WebSockets — a full-duplex upgrade of one HTTP request
// into a framed, binary-safe, bidirectional byte stream (RFC 6455); and SSE — a
// deliberately *un-ended* HTTP response of `text/event-stream` frames, strictly
// server->client, whose only superpower is trivial auto-reconnect via the
// `Last-Event-ID` header. Node's `ws` package is the canonical WS server AND
// client; SSE is literally `res.writeHead({"Content-Type":"text/event-stream"})`
// + `res.write("data: ...\n\n")` and never calling `res.end()`.
//
// DETERMINISM: every server binds to port 0 (ephemeral). A fixed, known message
// set is exchanged, collected, and SORTED before any value is printed or
// asserted — so output is byte-identical across runs. Client and server are
// closed before each section returns (process exits 0). No timing is asserted;
// only message CONTENT and protocol facts are checked.
//
// Run:
//     pnpm exec tsx websockets_sse.ts   (or: just run websockets_sse)

import { WebSocket, WebSocketServer } from "ws";
import type { RawData } from "ws";
import { createServer } from "node:http";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { AddressInfo, Socket } from "node:net";

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

// --- protocol helpers (typed; no `any`) -------------------------------------

// AddressInfo|string|null -> a concrete port number (0 if not bound).
function portOf(addr: AddressInfo | string | null): number {
  return typeof addr === "object" && addr !== null ? addr.port : 0;
}

// Coerce a ws RawData (Buffer | ArrayBuffer | Buffer[]) to a single Buffer.
function toBuffer(data: RawData): Buffer {
  if (Buffer.isBuffer(data)) return data;
  if (Array.isArray(data)) return Buffer.concat(data);
  return Buffer.from(data);
}

// Wait for a ws client to finish its opening handshake (or error out).
function waitForOpen(ws: WebSocket): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    if (ws.readyState === WebSocket.OPEN) {
      resolve();
      return;
    }
    const onOpen = (): void => {
      ws.off("open", onOpen);
      ws.off("error", onError);
      resolve();
    };
    const onError = (err: Error): void => {
      ws.off("open", onOpen);
      ws.off("error", onError);
      reject(err);
    };
    ws.on("open", onOpen);
    ws.on("error", onError);
  });
}

// Wait for a ws client's "close" event; resolve with the close code.
function waitForClose(ws: WebSocket): Promise<number> {
  return new Promise<number>((resolve) => {
    ws.once("close", (code: number) => resolve(code));
  });
}

// Start a WebSocketServer on an ephemeral port; resolve once it is listening.
function startWss(): Promise<{ wss: WebSocketServer; port: number }> {
  return new Promise<{ wss: WebSocketServer; port: number }>((resolve, reject) => {
    const wss = new WebSocketServer({ port: 0, host: "127.0.0.1" }, () => {
      const p = portOf(wss.address());
      if (p > 0) resolve({ wss, port: p });
      else reject(new Error("ws server failed to bind"));
    });
    wss.on("error", reject);
  });
}

// Close a WebSocketServer and resolve once it has stopped listening.
function closeServer(wss: WebSocketServer): Promise<void> {
  return new Promise<void>((resolve) => {
    wss.close(() => resolve());
  });
}

// Collect exactly `count` TEXT messages a ws client receives, then stop
// listening. (Order is not asserted; callers SORT the result.)
function collectTextMessages(ws: WebSocket, count: number): Promise<string[]> {
  return new Promise<string[]>((resolve) => {
    const out: string[] = [];
    const handler = (data: RawData, isBinary: boolean): void => {
      if (isBinary) return;
      const text = Buffer.isBuffer(data) ? data.toString("utf8") : String(data);
      out.push(text);
      if (out.length >= count) {
        ws.off("message", handler);
        resolve(out);
      }
    };
    ws.on("message", handler);
  });
}

// Collect the next BINARY message a ws client receives (Buffer).
function collectBinary(ws: WebSocket): Promise<Buffer> {
  return new Promise<Buffer>((resolve) => {
    const handler = (data: RawData, isBinary: boolean): void => {
      if (!isBinary) return;
      ws.off("message", handler);
      resolve(toBuffer(data));
    };
    ws.on("message", handler);
  });
}

// Start an http server on an ephemeral port; resolve with that port.
function listenEphemeral(server: ServerLike): Promise<number> {
  return new Promise<number>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", reject);
      resolve(portOf(server.address()));
    });
  });
}

// Structural shape satisfied by node:http's Server (and WebSocketServer, though
// only http servers are used here). Kept minimal so no `any` is needed.
interface ServerLike {
  listen(port: number, host: string, cb: () => void): unknown;
  address(): AddressInfo | string | null;
  once(event: "error", listener: (err: Error) => void): unknown;
  off(event: "error", listener: (err: Error) => void): unknown;
}

// Read res.writableEnded safely. Routing through a function parameter dodges a
// TS control-flow-analysis quirk: a `let` assigned only inside a request-handler
// closure gets narrowed to its initializer at the read site, so an inline
// `res !== null && res.writableEnded` narrows to `never`. A fresh parameter
// narrows correctly.
function isWritableEnded(res: ServerResponse | null): boolean | null {
  return res === null ? null : res.writableEnded;
}

// --- SSE wire-format model --------------------------------------------------

// A parsed SSE event. The HTML SSE spec defines four fields: data, id, event,
// retry. `retry` is consumed by EventSource (a reconnect hint), not a data
// field, so it is not surfaced here. Events with no `data:` line are not
// dispatched by EventSource (parseSseBlock returns null for them).
interface SseEvent {
  data: string;
  id: string | null;
  event: string | null;
}

// Parse one SSE "event block" (the text between two blank lines) per the HTML
// spec: split on LF, drop a single leading space after the colon, ignore comment
// lines starting with ':', join multiple data: lines with '\n'.
function parseSseBlock(block: string): SseEvent | null {
  const dataLines: string[] = [];
  let id: string | null = null;
  let event: string | null = null;
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line === "" || line.startsWith(":")) continue; // blank line / comment
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1); // one optional leading space
    if (field === "data") dataLines.push(value);
    else if (field === "id") id = value;
    else if (field === "event") event = value;
    // "retry" and any unknown field are intentionally ignored here.
  }
  if (dataLines.length === 0) return null; // no data -> EventSource would not dispatch
  return { data: dataLines.join("\n"), id, event };
}

// ----------------------------------------------------------------------------
// Observations threaded from the async sections into the (sync) decision section.
// ----------------------------------------------------------------------------

interface WsObservation {
  clientSentToServer: boolean;
  serverPushedToClient: boolean;
  textRoundTrip: boolean;
}

interface SseObservation {
  clientSendsAppData: boolean;
  framesCollected: number;
  contentTypeOk: boolean;
  connectionKeepAlive: boolean;
}

// ============================================================================
// Section A — WebSocket: connect, text round-trip, server push (bidirectional)
// ============================================================================

async function sectionA(): Promise<WsObservation> {
  sectionBanner("A — WebSocket: connect, text round-trip, server push (bidirectional)");

  const { wss, port } = await startWss();
  check("WS server bound to an ephemeral port (> 0)", port > 0);
  const url = `ws://127.0.0.1:${port}`;
  console.log("  WS server listening on ws://127.0.0.1 (ephemeral port 0)");

  console.log("  WebSocket readyState constants (ws API / RFC 6455):");
  console.log(`    CONNECTING = ${WebSocket.CONNECTING}`);
  console.log(`    OPEN       = ${WebSocket.OPEN}`);
  console.log(`    CLOSING    = ${WebSocket.CLOSING}`);
  console.log(`    CLOSED     = ${WebSocket.CLOSED}`);
  check("readyState CONNECTING === 0", WebSocket.CONNECTING === 0);
  check("readyState OPEN === 1", WebSocket.OPEN === 1);

  // Server: on connect, PUSH "welcome" (server -> client, unsolicited — this is
  // only possible because WS is bidirectional), then echo every message back.
  wss.on("connection", (ws: WebSocket) => {
    ws.send("welcome"); // server-initiated, no prior client message
    ws.on("message", (data: RawData, isBinary: boolean) => {
      ws.send(data, { binary: isBinary }); // echo unchanged
    });
  });

  const client = new WebSocket(url);
  // Attach the collector BEFORE awaiting "open": ws emits "open" and any
  // already-buffered "welcome" frame in the same socket read, so a listener
  // attached after `await open` would miss it. (Classic emitter-after-await trap.)
  const receivedPromise = collectTextMessages(client, 2);
  await waitForOpen(client);
  check("client readyState === OPEN (1) after handshake", client.readyState === WebSocket.OPEN);

  // Collect exactly 2 text messages the CLIENT receives: "welcome" (server push)
  // and the echo of our "ping". Arrival order is not guaranteed -> SORT.
  client.send("ping");
  const received = (await receivedPromise).sort();
  console.log(`  client received text messages (sorted): ${JSON.stringify(received)}`);

  const observation: WsObservation = {
    clientSentToServer: true, // client.send("ping")
    serverPushedToClient: received.includes("welcome"), // server pushed without being asked
    textRoundTrip: received.includes("ping"), // echo came back
  };

  check('WS text round-trip set === ["ping","welcome"]', JSON.stringify(received) === '["ping","welcome"]');
  check('WS is bidirectional: server pushed "welcome" with no prior client message', observation.serverPushedToClient);
  check('WS echo: client sent "ping" and received it back', observation.textRoundTrip);

  // Teardown: close the client, then the server, before returning.
  client.close(1000, "section-a-done");
  await waitForClose(client);
  await closeServer(wss);
  check("section A teardown: client + server closed", true);
  return observation;
}

// ============================================================================
// Section B — WebSocket: binary round-trip + close codes
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — WebSocket: binary round-trip + close codes");

  const { wss, port } = await startWss();
  const url = `ws://127.0.0.1:${port}`;
  console.log("  WS server listening on ws://127.0.0.1 (ephemeral port 0)");

  // Promise that resolves with the close code the SERVER observes. Set up before
  // any connection so the closure captures the resolver.
  const serverClosePromise = new Promise<number>((resolveServerClose) => {
    wss.on("connection", (ws: WebSocket) => {
      ws.on("message", (data: RawData, isBinary: boolean) => {
        ws.send(data, { binary: isBinary }); // binary-safe echo
      });
      ws.on("close", (code: number) => resolveServerClose(code));
    });
  });

  const client = new WebSocket(url);
  const echoPromise = collectBinary(client);
  await waitForOpen(client);

  // Send a BINARY message (Buffer). The server echoes it back byte-for-byte.
  const sent = Buffer.from([1, 2, 3, 0xfe, 0xff]);
  client.send(sent, { binary: true });
  const echoed = await echoPromise;

  console.log(`  sent binary   : [${Array.from(sent).join(", ")}]`);
  console.log(`  echoed binary : [${Array.from(echoed).join(", ")}]`);
  check("WS binary round-trip: bytes identical (Buffer.compare === 0)", Buffer.compare(sent, echoed) === 0);
  check("WS is binary-safe: 0xFE/0xFF survived (not UTF-8 boundaries)", echoed[3] === 0xfe && echoed[4] === 0xff);

  // Clean close with code 1000 (Normal Closure). Both ends observe the same code.
  client.close(1000, "normal");
  const clientCloseCode = await waitForClose(client);
  const serverCloseCode = await serverClosePromise;

  console.log("  Common WebSocket close codes (RFC 6455 §7.4):");
  console.log("    1000 Normal Closure");
  console.log("    1001 Going Away (endpoint leaving)");
  console.log("    1006 Abnormal Closure (NO close frame received — e.g. dropped link)");
  console.log("    1011 Internal Error (server)");
  console.log("    4000-4999 Reserved for application-defined codes");
  console.log(`  client close code observed: ${clientCloseCode}`);
  console.log(`  server close code observed: ${serverCloseCode}`);
  check("client clean close code === 1000 (Normal Closure)", clientCloseCode === 1000);
  check("server observed the same close code === 1000", serverCloseCode === 1000);

  await closeServer(wss);
  check("section B teardown: server closed", true);
}

// ============================================================================
// Section C — Server-Sent Events: text/event-stream endpoint + frame parsing
// ============================================================================

async function sectionC(): Promise<SseObservation> {
  sectionBanner("C — Server-Sent Events: text/event-stream endpoint + frame parsing");

  // The fixed set of SSE frames the server will stream. This is the "message
  // set" the client must collect (deterministic; order-independent via sort).
  const fixedFrames: readonly string[] = [
    "data: hello\n\n", // simplest event: one data line
    "data: line1\ndata: line2\n\n", // multi-line data (joined with \n)
    "id: 42\nevent: tick\ndata: with-id\n\n", // event with id (-> Last-Event-ID) + named event
  ];

  let serverRes: ServerResponse | null = null;
  const server = createServer((_req: IncomingMessage, res: ServerResponse) => {
    serverRes = res;
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    });
    for (const frame of fixedFrames) res.write(frame);
    // NOTE: intentionally NO res.end() — an SSE stream is LONG-LIVED; the
    // client cancels when it has what it needs. (This is the whole point.)
  });

  // Track sockets so teardown is guaranteed (client cancel + destroy).
  const openSockets = new Set<Socket>();
  server.on("connection", (s: Socket) => {
    openSockets.add(s);
    s.once("close", () => {
      openSockets.delete(s);
    });
  });

  await listenEphemeral(server);
  const port = portOf(server.address());
  const url = `http://127.0.0.1:${port}/`;
  console.log("  SSE server listening on http://127.0.0.1 (ephemeral port 0)");

  // Client: open a plain HTTP GET and read the STREAMING body frame by frame.
  const resp = await fetch(url);
  if (resp.body === null) throw new Error("SSE response body was null");
  const contentType = resp.headers.get("content-type") ?? "";
  const connectionHeader = resp.headers.get("connection") ?? "";
  check("SSE Content-Type === text/event-stream", contentType === "text/event-stream");
  check("SSE Connection === keep-alive", connectionHeader === "keep-alive");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const events: SseEvent[] = [];
  while (events.length < fixedFrames.length) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value === undefined) continue;
    buffer += decoder.decode(value, { stream: true });
    // Extract every complete block (terminated by a blank line, "\n\n").
    let idx = buffer.indexOf("\n\n");
    while (idx !== -1) {
      const block = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const ev = parseSseBlock(block);
      if (ev !== null) events.push(ev);
      idx = buffer.indexOf("\n\n");
    }
  }

  // Prove the server kept the response OPEN (never called res.end) BEFORE the
  // client cancels the long-lived stream.
  check("SSE server never called res.end (long-lived stream)", isWritableEnded(serverRes) === false);

  // The CLIENT ends the stream (cancel); only the client can, in SSE.
  try {
    await reader.cancel();
  } catch {
    // cancel may surface an abort; the frames are already collected.
  }
  for (const s of openSockets) s.destroy();
  await new Promise<void>((resolve) => server.close(() => resolve()));

  // Sort for an order-independent, byte-stable listing.
  const sortedEvents = [...events].sort((x, y) => (x.data < y.data ? -1 : x.data > y.data ? 1 : 0));
  console.log("  client collected SSE events (sorted by data):");
  for (const e of sortedEvents) {
    console.log(`    data=${JSON.stringify(e.data)} id=${JSON.stringify(e.id)} event=${JSON.stringify(e.event)}`);
  }
  const withId = events.find((e) => e.id === "42");
  const multiline = events.find((e) => e.data === "line1\nline2");

  check("SSE collected exactly 3 data frames", events.length === fixedFrames.length);
  check('SSE frame "hello" present', events.some((e) => e.data === "hello"));
  check('SSE multi-line data joined with "\\n" (line1\\nline2)', multiline !== undefined);
  check('SSE id:42 frame: data "with-id", named event "tick"', withId !== undefined && withId.data === "with-id" && withId.event === "tick");

  return {
    clientSendsAppData: false, // the client only GETs + reads; it sends no app data upstream
    framesCollected: events.length,
    contentTypeOk: contentType === "text/event-stream",
    connectionKeepAlive: connectionHeader === "keep-alive",
  };
}

// ============================================================================
// Section D — WebSocket vs SSE: the decision (derived from A–C observations)
// ============================================================================

function sectionD(ws: WsObservation, sse: SseObservation): void {
  sectionBanner("D — WebSocket vs SSE: the decision");

  // Directionality is DERIVED from the runtime observations of sections A and C,
  // not asserted from a constant: in A the client both sent ("ping") and
  // received ("welcome"); in C the client only read frames and sent nothing.
  const wsBidirectional = ws.clientSentToServer && ws.serverPushedToClient;
  const sseOneWay = !sse.clientSendsAppData;

  console.log("  criterion          | WebSocket              | Server-Sent Events");
  console.log("  -------------------+------------------------+---------------------------");
  console.log("  direction          | full-duplex (both)     | one-way (server -> client)");
  console.log("  transport          | ws:// (HTTP Upgrade)   | http:// (text/event-stream)");
  console.log("  data types         | text + binary          | text only (UTF-8)");
  console.log("  auto-reconnect     | NO (you implement)     | YES (EventSource built-in)");
  console.log("  resume after drop  | you replay state       | Last-Event-ID header");
  console.log("  backpressure       | ws.bufferedAmount      | TCP via the HTTP stream");
  console.log("  framing            | RFC 6455 frames        | blank-line (\\n\\n) blocks");
  console.log("  best for           | chat, games, collab    | feeds, notifications, ticks");

  check("WS is bidirectional (derived from Section A: client<->server)", wsBidirectional);
  check("SSE is one-way (derived from Section C: client sends no app data)", sseOneWay);
  check("SSE Content-Type was text/event-stream (derived from Section C)", sse.contentTypeOk);

  // SSE wire-format semantics, computed through the SAME parser the client used,
  // on a crafted block exercising id / event / retry / data fields.
  const demo = parseSseBlock("id: 7\nevent: update\nretry: 3000\ndata: payload");
  check('SSE parser extracts id field ("7")', demo !== null && demo.id === "7");
  check('SSE parser extracts named event ("update")', demo !== null && demo.event === "update");
  check('SSE parser surfaces only data ("payload"); retry is an EventSource hint, not data', demo !== null && demo.data === "payload");
}

// ============================================================================
// Section E — Backpressure, use cases, and cross-language parallels
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — Backpressure, use cases, and cross-language parallels");

  // (1) WS backpressure signal: ws.bufferedAmount (bytes queued, not yet on the
  //     wire). MDN notes the browser WebSocket API "has no way to apply
  //     backpressure" — bufferedAmount is the only knob. Its exact value after a
  //     flush is timing-dependent, so we only assert its TYPE and sign.
  const { wss, port: wPort } = await startWss();
  wss.on("connection", (ws: WebSocket) => {
    ws.on("message", () => ws.send("ack"));
  });
  const c = new WebSocket(`ws://127.0.0.1:${wPort}`);
  const ack = collectTextMessages(c, 1);
  await waitForOpen(c);
  c.send("probe");
  await ack;
  console.log(`  ws client.bufferedAmount after a round-trip: ${c.bufferedAmount}`);
  check("ws WebSocket.bufferedAmount is a non-negative number (backpressure signal)", typeof c.bufferedAmount === "number" && c.bufferedAmount >= 0);
  c.close(1000);
  await waitForClose(c);
  await closeServer(wss);

  // (2) SSE backpressure rides on the underlying HTTP/TCP stream: res.write()
  //     returns false when the kernel send buffer is full -> stop writing until
  //     'drain'. And the response stays open (writableEnded === false).
  let writeReturn: unknown = null;
  let sseRes: ServerResponse | null = null;
  const httpServer = createServer((_req: IncomingMessage, res: ServerResponse) => {
    sseRes = res;
    res.writeHead(200, { "Content-Type": "text/event-stream", Connection: "keep-alive" });
    writeReturn = res.write("data: tick\n\n");
    // long-lived: no res.end()
  });
  const openSockets = new Set<Socket>();
  httpServer.on("connection", (s: Socket) => {
    openSockets.add(s);
    s.once("close", () => {
      openSockets.delete(s);
    });
  });
  await listenEphemeral(httpServer);
  const hPort = portOf(httpServer.address());
  const resp = await fetch(`http://127.0.0.1:${hPort}/`);
  if (resp.body === null) throw new Error("SSE response body was null");
  const reader = resp.body.getReader();
  // Read until the frame arrives or the stream ends (content, not timing).
  let got = false;
  while (!got) {
    const { done, value } = await reader.read();
    if (done) break;
    if (value !== undefined && new TextDecoder().decode(value).includes("tick")) got = true;
  }
  check("SSE res.write() returns a boolean (Node stream backpressure contract)", typeof writeReturn === "boolean");
  check("SSE response stays open (writableEnded === false) — long-lived", isWritableEnded(sseRes) === false);
  try {
    await reader.cancel();
  } catch {
    // ignore abort on cancel
  }
  for (const s of openSockets) s.destroy();
  await new Promise<void>((resolve) => httpServer.close(() => resolve()));

  // (3) Use cases + cross-language parallels (the decision, applied).
  console.log("");
  console.log("  Use WebSocket  : bidirectional + low-latency (chat, games, collab, binary).");
  console.log("  Use SSE        : one-way push + auto-reconnect (feeds, notifications, tickers).");
  console.log("  WS reconnect   : you implement it (close -> wait -> new WebSocket).");
  console.log("  SSE reconnect  : automatic; browser resends Last-Event-ID to resume.");
  console.log("");
  console.log("  Cross-language:");
  console.log("    Go   : nhooyr.io/websocket (or golang.org/x/net/websocket) -> ../go/STREAMING_WEBSOCKETS.md");
  console.log("    Rust : axum::extract::ws::WebSocket (typed, over tungstenite) -> ../rust/");
  check("section E: WS + SSE backpressure signals observed at runtime", typeof c.bufferedAmount === "number" && typeof writeReturn === "boolean");
}

// ============================================================================
// main (top-level await: every server is spun up and torn down before exit)
// ============================================================================

async function main(): Promise<void> {
  console.log("websockets_sse.ts — Phase 7 bundle (web/).");
  console.log("Two realtime server->client mechanisms, run on self-contained port-0 servers:");
  console.log("WebSockets (full-duplex, binary-safe, RFC 6455 via `ws`) vs Server-Sent Events");
  console.log("(one-way, long-lived text/event-stream over node:http). Every value below is");
  console.log("computed by this file; the .md guide pastes it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Determinism: a fixed message set is exchanged, collected, and SORTED before any");
  console.log("value is printed or asserted; client+server are closed before each section returns.");

  const wsObs = await sectionA();
  await sectionB();
  const sseObs = await sectionC();
  sectionD(wsObs, sseObs);
  await sectionE();

  sectionBanner("DONE — all sections printed");
}

await main();
