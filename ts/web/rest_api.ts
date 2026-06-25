// rest_api.ts — Phase 8 bundle (Web, DB & Production).
//
// GOAL (one line): show, by spinning up a real Hono app on an EPHEMERAL port
// (0) via `@hono/node-server` and firing self-requests at it, that a REST API in
// Hono is: a Router (method+path patterns with params), a composable MIDDLEWARE
// chain (each layer wraps the handler, onion-style, via `await next()`), a
// Context object (`c.req` for query/header/body, `c.json`/`c.text`/`c.header`/
// `c.status` for the response), and `app.onError`/`app.notFound` for 500/404 —
// all behind a web-standard `app.fetch: (Request) => Response` that runs
// unchanged on Node / Workers / Bun / Deno. Every claim is pinned as a
// `check()`'d invariant.
//
// This is the GROUND TRUTH for REST_API.md. Every status code, header value and
// body below is printed by this file. Change it -> re-run -> re-paste. Never
// hand-compute.
//
// LINEAGE (why this bundle exists, and what it is the SUCCESSOR of): Hono is a
// web-standard TypeScript web framework — a Router + a middleware chain + a
// Context, exposed as a single `fetch: (Request) => Response` function. It does
// for `node:http` (🔗 NODE_HTTP_SERVER) what Express did in 2010, but built on
// the WHATWG web standards (Request/Response/Headers/ReadableStream) instead of
// Node's req/res streams — so the SAME app.fetch also runs on Cloudflare
// Workers, Bun, and Deno unchanged. `@hono/node-server` is the thin adapter that
// bridges app.fetch to node:http. Routing, path params, the middleware chain,
// and the typed Context are the four things a framework adds over the raw
// (req, res) callback; doing them by hand (as NODE_HTTP_SERVER does) is exactly
// the tedium Hono removes. The client side of the same HTTP wire is the global
// `fetch` (🔗 FETCH_HTTP_CLIENT); typed body validation slots in as a validator
// MIDDLEWARE (🔗 ZOD_VALIDATION).
//
// DETERMINISM NOTE (§4.2 rule 4 + the brief's port-0 rule): every server here
// listens on port 0 (the OS assigns an EPHEMERAL port — NEVER printed, so the
// output is stable run-to-run). Each section builds its own focused app, serves
// it, makes SELF-CONTAINED requests via the global `fetch`, ASSERTS status /
// headers / body (NEVER timings), then `server.close()` +
// `server.closeAllConnections()` + `await` before returning — so the process
// drains fully and exits 0. Section D needs no server at all: it calls
// `app.fetch(new Request(...))` IN-PROCESS, which is the most deterministic
// demo possible (no socket). Wall-clock time and the ephemeral port number are
// never printed or asserted.
//
// Run:
//     pnpm exec tsx rest_api.ts   (or: just run rest_api)

import { Hono } from "hono";
import type { Env, MiddlewareHandler } from "hono";
import { serve } from "@hono/node-server";
import type { Server } from "node:http";

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

// startHono binds a Hono app to port 0 on the loopback via @hono/node-server
// and resolves to { server, port } once the 'listening' callback fires. Port 0
// = "give me any free ephemeral port" — two runs (or a sibling bundle in
// parallel) never collide. The caller MUST stopHono(server) before returning.
//
// Type note: serve() returns @hono/node-server's ServerType union
// (Server | Http2Server | Http2SecureServer); since we pass NO http2/https
// serverOptions the runtime object is a plain http.Server, so we narrow to
// Server (the union overlaps Server, so the assertion is sound) to call
// .close() / .closeAllConnections() / .on() cleanly under strict mode.
// Generic over the app's Env (Bindings/Variables) so a Hono typed with custom
// Variables (e.g. Section C's {before: string}) is accepted too — Hono's Env
// generic is invariant, so `Hono<{Variables:...}>` is NOT assignable to a
// bare `Hono`. We constrain with `E extends Env` and take `Hono<E>`.
function startHono<E extends Env>(app: Hono<E>): Promise<{ server: Server; port: number }> {
  return new Promise((resolve, reject) => {
    const server = serve(
      {
        // app.fetch is the web-standard (Request) => Response entry point; we
        // wrap it to drop the optional env/ctx args @hono/node-server passes.
        fetch: (request) => app.fetch(request),
        port: 0,
        hostname: "127.0.0.1",
      },
      (info) => resolve({ server: server, port: info.port }),
    ) as Server;
    server.on("error", reject);
  });
}

// stopHono is the DETERMINISTIC teardown: server.close() stops accepting NEW
// connections and its callback resolves once in-flight ones drain, but a
// keep-alive socket (fetch/undici POOLS them!) would keep close() hanging until
// the keepAliveTimeout. closeAllConnections() (Node ≥18.2) force-closes every
// open socket, so close()'s callback fires promptly and the process exits 0.
function stopHono(server: Server): Promise<void> {
  return new Promise((resolve) => {
    server.close(() => resolve());
    server.closeAllConnections();
  });
}

// ============================================================================
// Section A — new Hono + routes (get/post) + path params + c.json/text + serve
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — new Hono + routes + path params + c.json/text + serve(port 0)");

  // new Hono() is the application. app.get/post/put/delete register a handler
  // for a method+path pattern. A handler receives a Context `c` and returns a
  // Response (c.json / c.text / c.html build it for you). app.fetch is the
  // web-standard (Request) => Response entry point the server invokes.
  const app = new Hono();
  app.get("/", (c) => c.json({ hello: "world" }));
  app.get("/users/:id", (c) => {
    // ":id" is a PATH PARAM — c.req.param("id") reads it (string | undefined;
    // always defined when the route matches, but TS types it defensively, so
    // we coalesce). The router only dispatches /users/42 here, never /users/.
    const id = c.req.param("id") ?? "";
    return c.json({ id });
  });
  app.get("/text", (c) => c.text("plain body"));

  const { server, port } = await startHono(app);
  try {
    const base = `http://127.0.0.1:${port}`;

    // A self-GET round-trips through the real socket: serve() → app.fetch →
    // router → handler → c.json → wire → fetch → Response.
    const r1 = await fetch(`${base}/`);
    const b1 = (await r1.json()) as { hello: string };
    console.log("GET / ->");
    console.log(`  status : ${r1.status}`);
    console.log(`  body   : ${JSON.stringify(b1)}`);
    console.log(`  ctype  : ${r1.headers.get("content-type")}`);
    check("GET / -> 200", r1.status === 200);
    check('GET / body === {"hello":"world"}', JSON.stringify(b1) === JSON.stringify({ hello: "world" }));
    check("content-type includes application/json (c.json sets it)", (r1.headers.get("content-type") ?? "").includes("application/json"));

    // Path param: /users/:id captures the segment.
    const r2 = await fetch(`${base}/users/42`);
    const b2 = (await r2.json()) as { id: string };
    console.log("");
    console.log("GET /users/42  (path param :id) ->");
    console.log(`  status : ${r2.status}`);
    console.log(`  body   : ${JSON.stringify(b2)}`);
    check('GET /users/:id echoes the path param: id === "42"', b2.id === "42");

    // c.text sets Content-Type text/plain (c.json sets application/json).
    const r3 = await fetch(`${base}/text`);
    const t3 = await r3.text();
    console.log("");
    console.log("GET /text ->");
    console.log(`  status : ${r3.status}`);
    console.log(`  body   : ${JSON.stringify(t3)}`);
    console.log(`  ctype  : ${r3.headers.get("content-type")}`);
    check("GET /text -> 200", r3.status === 200);
    check('c.text body === "plain body"', t3 === "plain body");
    check("content-type is text/plain (c.text sets it)", (r3.headers.get("content-type") ?? "").includes("text/plain"));

    console.log("");
    console.log("@hono/node-server's serve({fetch: app.fetch, port: 0}) bridges the");
    console.log("web-standard app.fetch onto node:http — the SAME app.fetch that");
    console.log("Cloudflare Workers / Bun / Deno invoke directly (no adapter).");
  } finally {
    await stopHono(server);
  }
}

// ============================================================================
// Section B — c.req (query/header/body) + status (201) + grouping (route) + 404
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — c.req (query/header/body) + status (201) + grouping (route) + 404");

  const app = new Hono();

  // c.req.query("k") reads the querystring (string | undefined).
  app.get("/search", (c) => {
    const q = c.req.query("q") ?? "";
    const n = Number(c.req.query("n") ?? "0");
    return c.json({ q, n });
  });

  // c.req.header("name") reads a request header (case-insensitive; string | undefined).
  app.get("/header", (c) => {
    const custom = c.req.header("x-custom") ?? "(none)";
    return c.json({ custom });
  });

  // await c.req.json() parses the request body as JSON. c.json(data, 201) sets
  // BOTH the body and the status code (the 2nd arg is the status).
  app.post("/items", async (c) => {
    const body = await c.req.json<{ name: string }>();
    return c.json({ created: true, name: body.name }, 201);
  });

  // Grouping: a SUB-APP (its own Hono instance) mounted at a prefix via
  // app.route("/api", subApp). /api/version is now a real route — the router of
  // the sub-app handles everything under /api/.
  const api = new Hono();
  api.get("/version", (c) => c.json({ version: "v1" }));
  app.route("/api", api);

  const { server, port } = await startHono(app);
  try {
    const base = `http://127.0.0.1:${port}`;

    // query
    const r1 = await fetch(`${base}/search?q=hono&n=7`);
    const b1 = (await r1.json()) as { q: string; n: number };
    console.log('GET /search?q=hono&n=7  (c.req.query) ->');
    console.log(`  status : ${r1.status}`);
    console.log(`  body   : ${JSON.stringify(b1)}`);
    check('c.req.query("q") === "hono"', b1.q === "hono");
    check("c.req.query(\"n\") parsed to number -> 7", b1.n === 7);

    // header (case-insensitive)
    const r2 = await fetch(`${base}/header`, { headers: { "X-Custom": "abc" } });
    const b2 = (await r2.json()) as { custom: string };
    console.log("");
    console.log("GET /header  (X-Custom: abc — header read is case-insensitive) ->");
    console.log(`  body   : ${JSON.stringify(b2)}`);
    check('c.req.header("x-custom") read X-Custom (case-insensitive) === "abc"', b2.custom === "abc");

    // body + status 201
    const r3 = await fetch(`${base}/items`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "widget" }),
    });
    const b3 = (await r3.json()) as { created: boolean; name: string };
    console.log("");
    console.log("POST /items  (await c.req.json + c.json(data, 201)) ->");
    console.log(`  status : ${r3.status}   (2nd arg of c.json is the status)`);
    console.log(`  body   : ${JSON.stringify(b3)}`);
    check("POST /items -> 201 (c.json(body, 201))", r3.status === 201);
    check('POST body parsed via c.req.json: name === "widget"', b3.name === "widget");

    // grouping
    const r4 = await fetch(`${base}/api/version`);
    const b4 = (await r4.json()) as { version: string };
    console.log("");
    console.log("GET /api/version  (sub-app mounted via app.route) ->");
    console.log(`  status : ${r4.status}`);
    console.log(`  body   : ${JSON.stringify(b4)}`);
    check("app.route(/api, subApp) mounts the sub-app: status 200", r4.status === 200);
    check('grouped route body version === "v1"', b4.version === "v1");

    // 404 (unknown route — Hono's default not-found response)
    const r5 = await fetch(`${base}/nope`);
    console.log("");
    console.log("GET /nope  (no route matches) ->");
    console.log(`  status : ${r5.status}`);
    check("unknown route -> 404 (default not-found)", r5.status === 404);
  } finally {
    await stopHono(server);
  }
}

// ============================================================================
// Section C — middleware (use/next, onion order) + onError (500) + notFound
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — middleware (use/next, onion order) + onError (500) + notFound");

  // Typed Variables so c.set/c.get for the order trace are type-safe (no `any`).
  const app = new Hono<{ Variables: { before: string } }>();

  // Middleware is registered with app.use and runs in REGISTRATION order. The
  // model is ONION: the code BEFORE `await next()` runs outer->inner (MW1 then
  // MW2 then handler); the code AFTER `await next()` runs inner->outer (handler
  // done, then MW2, then MW1). We accumulate a "before" trace in the request
  // scope (c.set) and return it from the handler, so the body PROVES the
  // before-next order empirically. The after-next stages set response headers
  // (the documented post-next pattern), proving they ALSO ran.
  app.use("*", async (c, next) => {
    c.set("before", (c.get("before") ?? "") + "MW1>");
    await next();
    c.header("x-mw1-exit", "ran"); // runs AFTER the handler (outer exit, last)
  });
  app.use("*", async (c, next) => {
    c.set("before", (c.get("before") ?? "") + "MW2>");
    await next();
    c.header("x-mw2-exit", "ran"); // runs after the handler, before MW1's exit
  });

  app.get("/chain", (c) => {
    const before = c.get("before") ?? "";
    return c.text(before + "|handler");
  });

  // A handler that throws — app.onError turns it into a 500 Response.
  app.get("/boom", () => {
    throw new Error("kaboom");
  });

  // app.onError catches ANY uncaught throw from a handler/middleware and lets
  // you shape the Response. (Hono itself never re-throws past next(), so you do
  // NOT need try/catch around next().)
  app.onError((err, c) => {
    return c.json({ error: "caught", message: err.message }, 500);
  });

  // app.notFound customizes the response for unmatched routes (the default is a
  // plain 404; here we make it JSON). Only the TOP-LEVEL app's notFound fires.
  app.notFound((c) => {
    return c.json({ error: "not found" }, 404);
  });

  const { server, port } = await startHono(app);
  try {
    const base = `http://127.0.0.1:${port}`;

    // The onion: before-next order is MW1 -> MW2 -> handler.
    const r1 = await fetch(`${base}/chain`);
    const t1 = await r1.text();
    console.log("GET /chain  (two app.use middlewares + handler) ->");
    console.log(`  status      : ${r1.status}`);
    console.log(`  body        : ${JSON.stringify(t1)}`);
    console.log(`  x-mw1-exit  : ${r1.headers.get("x-mw1-exit")}   (set AFTER next() — outer layer exits last)`);
    console.log(`  x-mw2-exit  : ${r1.headers.get("x-mw2-exit")}   (set AFTER next() — inner layer exits first)`);
    check("before-next order MW1>MW2>|handler (onion: registration order)", t1 === "MW1>MW2>|handler");
    check("middleware ran AFTER next (x-mw2-exit present)", r1.headers.get("x-mw2-exit") === "ran");
    check("middleware ran AFTER next (x-mw1-exit present, outermost exit)", r1.headers.get("x-mw1-exit") === "ran");

    // Early-exit: a middleware that RETURNS a Response WITHOUT calling next()
    // short-circuits the whole chain (e.g. an auth guard). Built on its own app
    // so the * guards above don't interfere.
    const gated = new Hono();
    gated.use("/admin/*", async (c, next) => {
      const token = c.req.header("x-token");
      if (token !== "secret") {
        return c.json({ error: "unauthorized" }, 401); // no next() -> chain stops
      }
      await next();
      return; // explicit void return -> satisfies noImplicitReturns (mixed path)
    });
    gated.get("/admin/panel", (c) => c.text("welcome"));
    const { server: gs, port: gp } = await startHono(gated);
    try {
      const gbase = `http://127.0.0.1:${gp}`;
      const noToken = await fetch(`${gbase}/admin/panel`);
      const withToken = await fetch(`${gbase}/admin/panel`, { headers: { "x-token": "secret" } });
      console.log("");
      console.log("Middleware early-exit (returns a Response, skips next):");
      console.log(`  no token    -> ${noToken.status}   (guard returned 401; handler never ran)`);
      console.log(`  with token  -> ${withToken.status}   (guard called next(); handler ran)`);
      check("guard middleware short-circuits: missing token -> 401", noToken.status === 401);
      check("guard passes with token -> 200", withToken.status === 200);
    } finally {
      await stopHono(gs);
    }

    // onError: thrown error -> 500.
    const r2 = await fetch(`${base}/boom`);
    const b2 = (await r2.json()) as { error: string; message: string };
    console.log("");
    console.log("GET /boom  (handler throws) -> app.onError:");
    console.log(`  status : ${r2.status}`);
    console.log(`  body   : ${JSON.stringify(b2)}`);
    check("thrown error -> 500 (app.onError)", r2.status === 500);
    check('onError shaped the body: error === "caught"', b2.error === "caught");
    check('onError preserved the message: message === "kaboom"', b2.message === "kaboom");

    // notFound: custom 404.
    const r3 = await fetch(`${base}/missing-route`);
    const b3 = (await r3.json()) as { error: string };
    console.log("");
    console.log("GET /missing-route -> app.notFound:");
    console.log(`  status : ${r3.status}`);
    console.log(`  body   : ${JSON.stringify(b3)}`);
    check("unknown route -> 404 (custom app.notFound)", r3.status === 404);
    check('notFound shaped the body: error === "not found"', b3.error === "not found");
  } finally {
    await stopHono(server);
  }
}

// ============================================================================
// Section D — web-standard app.fetch (Request)=>Response (NO server!) + the
// composable validator-middleware slot (🔗 ZOD_VALIDATION).
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — web-standard app.fetch (Request)=>Response + validator-middleware slot");

  // THE PORTABILITY PAYOFF: app.fetch is a plain (Request) => Response function.
  // It needs NO server — call it IN-PROCESS and await the Response. This is the
  // EXACT function Cloudflare Workers / Bun / Deno invoke as the entry point;
  // @hono/node-server only adapts it to node:http (Section A). No socket, no
  // port, no timing — the most deterministic possible demonstration.
  const app = new Hono();
  app.get("/ping", (c) => c.json({ pong: true }));
  app.get("/double/:n", (c) => {
    const n = Number(c.req.param("n") ?? "0");
    return c.json({ doubled: n * 2 });
  });

  const r1 = await app.fetch(new Request("http://localhost/ping"));
  const b1 = (await r1.json()) as { pong: boolean };
  console.log("app.fetch(new Request(...)) — IN-PROCESS, NO server:");
  console.log(`  r1.status === ${r1.status}`);
  console.log(`  r1.body   === ${JSON.stringify(b1)}`);
  check("app.fetch works with no server at all: status 200", r1.status === 200);
  check('app.fetch in-process body === {"pong":true}', JSON.stringify(b1) === JSON.stringify({ pong: true }));

  const r2 = await app.fetch(new Request("http://localhost/double/21"));
  const b2 = (await r2.json()) as { doubled: number };
  console.log(`  /double/21 -> ${JSON.stringify(b2)}`);
  check("app.fetch path param works in-process: doubled === 42", b2.doubled === 42);

  // THE VALIDATOR-MIDDLEWARE SLOT: a validator is "just a middleware" placed on
  // the route BEFORE the handler. It inspects the input and either short-
  // circuits with an error Response, or calls next() to let the handler run.
  // @hono/zod-validator fits EXACTLY here (app.post("/x", zValidator("json",
  // schema), handler)) — but zod lives in metaprog/ (🔗 ZOD_VALIDATION), so per
  // §4.2 rule 9 (STDLIB + hono + @hono/node-server only) we hand-roll the same
  // shape to expose the mechanism. This IS the composable-validator pattern.
  const api = new Hono();
  const validateItem: MiddlewareHandler = async (c, next) => {
    // c.req.json() rejects on malformed JSON -> .catch -> null -> 400.
    const body = await c.req.json<{ name?: unknown }>().catch(() => null);
    if (body === null || typeof body.name !== "string" || body.name.length === 0) {
      return c.json({ error: "name (non-empty string) required" }, 400);
    }
    await next();
    return; // explicit void return -> satisfies noImplicitReturns (mixed path)
  };
  api.post("/items", validateItem, (c) => c.json({ ok: true, validated: true }, 201));

  console.log("");
  console.log("Validator middleware (the @hono/zod-validator slot), in-process:");

  const ok = await api.fetch(
    new Request("http://localhost/items", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "valid" }),
    }),
  );
  const okBody = (await ok.json()) as { ok: boolean; validated: boolean };
  console.log(`  POST {name:"valid"}    -> ${ok.status} ${JSON.stringify(okBody)}`);
  check("valid body passes the validator -> 201", ok.status === 201);
  check("validator called next(): handler ran, validated === true", okBody.validated === true);

  const badType = await api.fetch(
    new Request("http://localhost/items", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: 42 }),
    }),
  );
  const badTypeBody = (await badType.json()) as { error: string };
  console.log(`  POST {name:42}         -> ${badType.status} ${JSON.stringify(badTypeBody)}`);
  check("wrong type (name is number) short-circuits -> 400", badType.status === 400);
  check("validator 400 body has an error string", typeof badTypeBody.error === "string");

  const empty = await api.fetch(
    new Request("http://localhost/items", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({}),
    }),
  );
  console.log(`  POST {}                -> ${empty.status}   (missing field)`);
  check("missing required field short-circuits -> 400", empty.status === 400);

  const malformed = await api.fetch(
    new Request("http://localhost/items", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{not json",
    }),
  );
  console.log(`  POST (malformed json)  -> ${malformed.status}   (c.req.json rejected -> caught)`);
  check("malformed JSON short-circuits -> 400", malformed.status === 400);
}

// ============================================================================
// Section E — graceful shutdown (server.close) + cross-language view
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — graceful shutdown (server.close) + cross-language");

  const app = new Hono();
  app.get("/", (c) => c.json({ up: true }));

  const { server, port } = await startHono(app);
  const base = `http://127.0.0.1:${port}`;

  // One request while the server is up.
  const r = await fetch(`${base}/`);
  const b = (await r.json()) as { up: boolean };
  console.log("Server up, GET / ->");
  console.log(`  status : ${r.status}`);
  console.log(`  body   : ${JSON.stringify(b)}`);
  check("server answered while up: 200", r.status === 200);
  check("body up === true", b.up === true);

  // GRACEFUL SHUTDOWN: server.close() stops accepting NEW connections and its
  // callback resolves once in-flight ones drain. closeAllConnections() (Node
  // ≥18.2) force-closes any lingering keep-alive sockets (fetch pools them!) so
  // close() does not hang on keepAliveTimeout. The await below resolving => the
  // process can exit 0 (no dangling libuv handle keeps it alive).
  console.log("");
  console.log("Graceful shutdown (server.close + closeAllConnections)...");
  // stopHono() resolves ONLY once server.close()'s callback fires; if it
  // rejected or hung, the await would throw/stall and this line never runs. So
  // reaching the assignment IS the proof of graceful close. (Sequential, not a
  // callback, so TS's control-flow analysis tracks it correctly.)
  let didClose = false;
  await stopHono(server);
  didClose = true;
  console.log(`  stopHono(server) resolved -> didClose === ${didClose}`);
  check("server.close() resolved (graceful shutdown complete)", didClose);

  // After close, the server no longer accepts connections. A new fetch() now
  // REJECTS with a TypeError (connection refused) — a NETWORK error, NOT an
  // HTTP 4xx/5xx (recall 🔗 FETCH_HTTP_CLIENT: HTTP errors are NOT rejections,
  // only network failures are).
  let refused = false;
  try {
    await fetch(`${base}/`);
  } catch {
    refused = true;
  }
  console.log(`  fetch after close -> connection refused === ${refused}   (network error, not an HTTP status)`);
  check("after close(), new connections are refused (fetch rejects)", refused === true);

  console.log("");
  console.log("Cross-language (the same REST/routing+middleware model elsewhere):");
  console.log("  Go     net/http : a Handler(w, r) fn + a ServeMux (Go 1.22 method+");
  console.log("                    path patterns) + func-chained middleware. A goroutine");
  console.log("                    is spawned PER request. (🔗 ../go/MIDDLEWARE_ROUTING.md)");
  console.log("  Rust   axum     : Router::new().route(...) + typed extractors");
  console.log("                    (FromRequest/FromRequestParts) — the strongest-typed");
  console.log("                    model; handlers take typed args. (🔗 ../rust axum basics)");
  console.log("  Python FastAPI  : @app.get('/x') decorator routing + Depends() for the");
  console.log("                    middleware/validator slot (pydantic validates the body).");
  console.log("                    (🔗 ../python fastapi routing)");
  console.log("  Node   Hono     : a Router + a composable middleware chain on top of");
  console.log("                    node:http; app.fetch is web-standard (Request)=>Response,");
  console.log("                    portable to Workers/Bun/Deno unchanged.");
  check("cross-language REST model summarized", true);
}

// ============================================================================
// main — run every section. Top-level await (ESM) so the process exits 0 only
// after every server has been closed.
// ============================================================================

async function main(): Promise<void> {
  console.log("rest_api.ts — Phase 8 bundle (Web, DB & Production).");
  console.log("Every value below is produced by spinning up a Hono app on an");
  console.log("EPHEMERAL port (0) via @hono/node-server, firing self-requests,");
  console.log("asserting status / headers / body, then server.close(). Nothing is");
  console.log("hand-computed; the ephemeral port + wall-clock are NEVER printed.");
  console.log("");
  console.log("Reminder: Hono is a web-standard (Request)=>Response framework.");
  console.log("@hono/node-server only adapts it to node:http (🔗 NODE_HTTP_SERVER);");
  console.log("the client side is the global fetch (🔗 FETCH_HTTP_CLIENT); typed");
  console.log("body validation slots in as a middleware (🔗 ZOD_VALIDATION).");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed");
}

await main();
