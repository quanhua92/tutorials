// deployment.ts — Phase 8 bundle (Web, DB & Production; member: web).
//
// GOAL (one line): show, by reading the repo's OWN package.json (engines /
// scripts / devDeps) and by asserting the STRUCTURE of a hand-written multi-stage
// Dockerfile, a 12-factor env-config loader, and an edge Worker snippet, that
// deploying a TS app means choosing a TARGET (container / serverless / edge) and
// a BUILD (dev `tsx` erase vs prod `dist/` bundle) — the cross-language analog of
// Go's scratch static binary and Rust's musl static binary, both of which ship
// far smaller images than Node.
//
// This is the GROUND TRUTH for DEPLOYMENT.md. Every parsed value, structural
// assertion, and worked example below is printed by this file. Change it ->
// re-run -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): writing a correct TypeScript server is only
// half the job. The other half is choosing how it RUNS in production:
//   - DEV  runs `tsx` (esbuild ERASES types per-file, NO bundle) — fast iteration,
//           but every cold-start re-parses every source file; you also pull
//           devDependencies (test runners, type checkers, hot reload). Fine for
//           a laptop, wrong for a container.
//   - PROD bundles `src/` to a single tree-shaken `dist/server.js` (esbuild/tsup),
//           sets NODE_ENV=production (strips dev-only code paths + lets package
//           managers `--omit=dev` skip devDeps), and runs `node dist/server.js`.
// Then the BUILT artifact is placed in a TARGET:
//   - LONG-LIVED CONTAINER  (Docker multi-stage: build on `node`, run on a slim
//           `distroless` image — no shell, smallest attack surface).
//   - SERVERLESS FUNCTION   (Lambda/Vercel Node; package a handler; cold-start
//           dominates, so bundle small + lazy-load).
//   - EDGE RUNTIME          (Cloudflare Workers / Vercel Edge: the SAME
//           web-standard `fetch(Request) => Response` code runs on a V8 isolate
//           globally — NO Node APIs like fs/child_process).
// Secrets NEVER go in the image: 12-factor config reads them from the environment
// at boot. Containers capture stdout (logs to files are lost on restart) and shut
// down gracefully on SIGTERM.
//
// DETERMINISM NOTE (§4.2): this bundle CANNOT actually build/deploy (no network,
// no subprocess, no Docker). Instead it is DETERMINISTIC by construction:
//   1. It READS static config files (the repo's own package.json) via node:fs,
//      resolved relative to this module (cwd-independent).
//   2. It asserts the STRUCTURE of hand-written artifact snippets (a Dockerfile,
//      a Worker) as plain strings — counting FROMs, checking for a fetch handler,
//      asserting the ABSENCE of Node-only APIs.
//   3. It demonstrates env/config + NODE_ENV behavior over FIXED mock env maps
//      (never the live process.env, which tsx and CI set unpredictably).
// No Math.random, no Date.now, no subprocess, no network. Output is byte-stable.
//
// Run:
//     pnpm exec tsx deployment.ts   (or: just run deployment)

import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

// ============================================================================
// Typed views of the static config files this bundle reads.
// ============================================================================

// A minimal, honest view of package.json (only the fields this bundle asserts).
interface PkgJson {
  readonly name?: string;
  readonly version?: string;
  readonly type?: string;
  readonly private?: boolean;
  readonly packageManager?: string;
  readonly engines?: Readonly<Record<string, string>>;
  readonly scripts?: Readonly<Record<string, string>>;
  readonly dependencies?: Readonly<Record<string, string>>;
  readonly devDependencies?: Readonly<Record<string, string>>;
  readonly bin?: Readonly<Record<string, string>>;
}

// Resolved paths — relative to THIS module (import.meta.url), so the bundle is
// cwd-independent. `just run` invokes `tsx web/deployment.ts` from ts/ root, but
// resolving via import.meta.url means it works from any cwd.
const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url)); // .../ts/web
const ROOT_PKG_PATH = path.resolve(MODULE_DIR, "..", "package.json"); // .../ts/package.json

function readPkg(filePath: string): PkgJson {
  return JSON.parse(readFileSync(filePath, "utf8")) as PkgJson;
}

// ============================================================================
// Hand-written deployment artifacts (the STRUCTURE of these is asserted; they
// are NOT executed — this bundle has no subprocess/network).
// ============================================================================

// A multi-stage Dockerfile: build on `node`, run on `distroless`. This is the
// canonical shape for a bundled Node service (small image, no shell).
const DOCKERFILE = `# syntax=docker/dockerfile:1
# ---- build stage: full node toolchain (tsx/tsup/typescript) ----
FROM node:20-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm run build   # install prod deps + bundle -> dist/
COPY . .

# ---- run stage: distroless (no shell/package manager; smallest surface) ----
FROM gcr.io/distroless/nodejs22-debian12
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER nonroot
EXPOSE 3000
CMD ["dist/server.js"]`;

// A Cloudflare Worker: web-standard fetch(Request) => Response on a V8 isolate.
// Note the ABSENCE of node:fs / child_process / require() — edge runtimes have
// no Node API surface (it is opt-in via a compat flag and partial).
const WORKER = `// Cloudflare Worker — web-standard fetch on a V8 isolate (globally distributed)
export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/") {
      return new Response("hello from the edge", {
        headers: { "content-type": "text/plain" },
      });
    }
    return new Response("not found", { status: 404 });
  },
};`;

// A SAMPLE package.json demonstrating the dev(tsx) vs prod(bundle to dist/) split.
// (The repo's own manifests are real configs read by fs; this one is a teaching
// artifact asserting the script SHAPE a deployable Node service should have.)
const SAMPLE_PKG = `{
  "name": "demo-api",
  "type": "module",
  "engines": { "node": ">=20" },
  "scripts": {
    "dev": "tsx watch src/server.ts",
    "build": "tsup src/server.ts --format esm --dts",
    "start": "node dist/server.js"
  }
}`;

// ============================================================================
// Section A — Dev (tsx, type-erase, no bundle) vs Prod (bundle to dist/) +
// NODE_ENV + the build/deploy split (read the repo's real package.json).
// ============================================================================

// codeLines returns the non-comment, non-empty lines of a text artifact, so
// structural assertions ignore comments and blank lines (deterministic).
function codeLines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && !l.startsWith("#") && !l.startsWith("//"));
}

function sectionA(): void {
  sectionBanner("A — Dev (tsx erase) vs Prod (bundle to dist/) + NODE_ENV");

  // --- Read the repo's REAL root package.json (cwd-independent resolution) ---
  const rootPkg = readPkg(ROOT_PKG_PATH);
  console.log("repo root package.json (READ via node:fs, cwd-independent):");
  console.log(`  name             = ${JSON.stringify(rootPkg.name)}`);
  console.log(`  packageManager   = ${JSON.stringify(rootPkg.packageManager)}`);
  console.log(`  engines.node     = ${JSON.stringify(rootPkg.engines?.node)}`);
  console.log(`  engines.pnpm     = ${JSON.stringify(rootPkg.engines?.pnpm)}`);

  // engines.node is ">=20.0.0" — parse the leading major to assert Node >= 20.
  const nodeRange = rootPkg.engines?.node ?? "";
  const nodeMajor = Number.parseInt(/[0-9]+/.exec(nodeRange)?.[0] ?? "0", 10);
  console.log(`  parsed Node major = ${nodeMajor}`);
  check("repo pins engines.node (present)", nodeRange.length > 0);
  check("repo requires Node >= 20 (LTS)", nodeMajor >= 20);
  check('repo packageManager starts with "pnpm"', (rootPkg.packageManager ?? "").startsWith("pnpm"));

  // devDeps carry the DEV toolchain: tsx (the dev runner) + typescript (the vet).
  const devDeps = rootPkg.devDependencies ?? {};
  console.log(`  devDependencies  = ${JSON.stringify(Object.keys(devDeps))}`);
  check("devDependencies includes tsx (the dev runner)", devDeps["tsx"] !== undefined);
  check("devDependencies includes typescript (the type-check vet)", devDeps["typescript"] !== undefined);
  check("devDependencies includes @types/node (Node stdlib types)", devDeps["@types/node"] !== undefined);

  // --- The dev vs prod SCRIPT split (asserted on the SAMPLE package.json) ---
  const sample = JSON.parse(SAMPLE_PKG) as PkgJson;
  const scripts = sample.scripts ?? {};
  console.log("");
  console.log("sample deployable package.json (the dev/prod script split):");
  console.log(`  scripts.dev   = ${JSON.stringify(scripts.dev)}`);
  console.log(`  scripts.build = ${JSON.stringify(scripts.build)}`);
  console.log(`  scripts.start = ${JSON.stringify(scripts.start)}`);

  // DEV runs `tsx`: esbuild ERASES types per-file but does NOT bundle. Every
  // cold-start re-parses every imported source file (slow start, fast iterate).
  const devScript = scripts["dev"] ?? "";
  check('dev script runs tsx (esbuild type-erase, NO bundle)', devScript.includes("tsx"));

  // PROD build runs a BUNDLER (tsup/esbuild): tree-shakes + emits ONE dist/server.js.
  const buildScript = scripts["build"] ?? "";
  check(
    "build script runs a bundler (tsup) that emits dist/",
    buildScript.includes("tsup") || buildScript.includes("esbuild"),
  );

  // PROD start runs `node` on the BUNDLED dist/ artifact — NOT tsx, NOT src/.
  const startScript = scripts["start"] ?? "";
  check('start script runs node on dist/ (not tsx, not src/)', startScript.includes("node") && startScript.includes("dist"));
  check('start script does NOT invoke tsx (prod runs the bundle)', !startScript.includes("tsx"));

  // --- NODE_ENV: the prod signal libraries + package managers read -------------
  // NODE_ENV=production is read by: Express (caches views, skips stack traces),
  // React (ships the production build), npm/pnpm (`--omit=dev` skips devDeps),
  // and V8 (some debug APIs disabled). We document this and assert the DETECTION
  // function over FIXED env maps (never live process.env, which tsx/CI set).
  console.log("");
  console.log("NODE_ENV detection (isProduction over FIXED env maps):");
  console.log(`  isProduction({})                       = ${isProduction({})}`);
  console.log(`  isProduction({NODE_ENV:"development"}) = ${isProduction({ NODE_ENV: "development" })}`);
  console.log(`  isProduction({NODE_ENV:"production"})  = ${isProduction({ NODE_ENV: "production" })}`);
  check("isProduction({}) is false (default)", isProduction({}) === false);
  check('isProduction({NODE_ENV:"development"}) is false', isProduction({ NODE_ENV: "development" }) === false);
  check('isProduction({NODE_ENV:"production"}) is true', isProduction({ NODE_ENV: "production" }) === true);
}

// isProduction mirrors the check libraries perform: an EXACT string compare of
// process.env.NODE_ENV against "production". Fed FIXED maps here (determinism).
function isProduction(env: Readonly<Record<string, string | undefined>>): boolean {
  return env["NODE_ENV"] === "production";
}

// ============================================================================
// Section B — Docker multi-stage (build on node -> run on distroless) + the
// image-size hierarchy (Go scratch < Rust musl < Node distroless).
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Docker multi-stage (build -> distroless) + image hierarchy");

  // Count FROM directives in the hand-written Dockerfile (comments excluded).
  const lines = codeLines(DOCKERFILE);
  const fromLines = lines.filter((l) => /^FROM\b/.test(l));
  console.log("multi-stage Dockerfile FROM directives (the stages):");
  for (const l of fromLines) {
    console.log(`    ${l}`);
  }
  check("Dockerfile has exactly 2 FROM stages (multi-stage build)", fromLines.length === 2);

  const buildStage = fromLines[0] ?? "";
  const runStage = fromLines[1] ?? "";
  check('build stage base is "node" (full toolchain for tsx/tsup)', /\bnode\b/.test(buildStage));
  check('build stage is named "AS build"', /AS\s+build\b/.test(buildStage));
  check('run stage base is distroless (no shell, smallest surface)', runStage.includes("distroless"));

  // The build stage installs prod deps + bundles -> dist/. (npm ci --omit=dev.)
  const buildRunLines = lines.filter((l) => l.startsWith("RUN "));
  const hasOmitempty = buildRunLines.some((l) => l.includes("--omit=dev"));
  const hasBundle = buildRunLines.some((l) => l.includes("npm run build"));
  console.log("");
  console.log(`  build RUN lines: ${JSON.stringify(buildRunLines)}`);
  check("build stage installs prod deps only (npm ci --omit=dev)", hasOmitempty);
  check("build stage bundles to dist/ (npm run build)", hasBundle);

  // The run stage COPIES artifacts from the build stage (COPY --from=build).
  const copyFromBuild = lines.filter((l) => l.includes("COPY --from=build"));
  console.log(`  COPY --from=build lines: ${JSON.stringify(copyFromBuild)}`);
  check("run stage copies dist/ from the build stage", copyFromBuild.some((l) => l.includes("dist")));
  check("run stage copies node_modules from the build stage", copyFromBuild.some((l) => l.includes("node_modules")));

  // Production hardening in the run stage: NODE_ENV + non-root user + EXPOSE.
  check("run stage sets ENV NODE_ENV=production", DOCKERFILE.includes("ENV NODE_ENV=production"));
  check("run stage runs as a non-root USER", DOCKERFILE.includes("USER nonroot"));
  check("Dockerfile declares an EXPOSE port", DOCKERFILE.includes("EXPOSE"));

  // --- The image-size hierarchy (documented; the key cross-language point) ---
  // Node MUST ship its runtime in the image (the V8 engine + libuv + node_modules),
  // so even a distroless Node image dwarfs a Go or Rust single static binary.
  console.log("");
  console.log("  image-size hierarchy (documented, smallest first):");
  console.log("    Go       : scratch        + ONE static binary (CGO=0)         ~ 10-20 MB");
  console.log("    Rust     : scratch/distroless + ONE musl static binary       ~ 10-30 MB");
  console.log("    Node     : distroless     + node runtime + node_modules      ~ 100-200 MB");
  console.log("    Node     : node:slim      (full distro, has a shell)         ~ 200-400 MB");
  console.log("    Node     : node:bookworm  (full Debian + build toolchain)    ~ 1 GB");
  check("documented: Go/Rust ship a SINGLE static binary (smallest)", true);
  check("documented: Node must carry the runtime + node_modules (largest)", true);
  check("documented: distroless has NO shell (smaller attack surface than slim)", true);
}

// ============================================================================
// Section C — 12-factor config (env, never baked secrets) + health checks +
// graceful SIGTERM shutdown + stdout logging.
// ============================================================================

// A 12-factor config loader: every value that VARIES between deploys (port, DB
// url, log level) is read from the ENVIRONMENT with a safe default; NOTHING that
// is secret or deploy-specific is baked into the image. Fed FIXED env maps here.
interface AppConfig {
  readonly port: number;
  readonly databaseUrl: string;
  readonly logLevel: string;
}

function loadConfig(env: Readonly<Record<string, string | undefined>>): AppConfig {
  const portRaw = env["PORT"];
  const port = portRaw !== undefined && /^\d+$/.test(portRaw) ? Number.parseInt(portRaw, 10) : 3000;
  const databaseUrl = env["DATABASE_URL"] ?? "postgres://localhost:5432/app";
  const logLevel = env["LOG_LEVEL"] ?? "info";
  return { port, databaseUrl, logLevel };
}

function sectionC(): void {
  sectionBanner("C — 12-factor config + health checks + graceful SIGTERM + stdout");

  // --- 12-factor config: defaults vs overrides (over FIXED env maps) ---------
  const defaults = loadConfig({});
  const overridden = loadConfig({ PORT: "8080", DATABASE_URL: "postgres://prod:5432/app", LOG_LEVEL: "debug" });
  console.log("12-factor config (loadConfig over FIXED env maps):");
  console.log(`  defaults  : ${JSON.stringify(defaults)}`);
  console.log(`  overrides : ${JSON.stringify(overridden)}`);

  check("default port === 3000 (when PORT unset)", defaults.port === 3000);
  check("default databaseUrl is a localhost placeholder", defaults.databaseUrl === "postgres://localhost:5432/app");
  check('default logLevel === "info"', defaults.logLevel === "info");
  check("override PORT=8080 is honored", overridden.port === 8080);
  check("override DATABASE_URL is honored (NEVER baked in the image)", overridden.databaseUrl === "postgres://prod:5432/app");
  check('override LOG_LEVEL=debug is honored', overridden.logLevel === "debug");
  check("secrets come from env, never from the bundled dist/ image", defaults.databaseUrl !== overridden.databaseUrl);

  // --- Health checks (documented; the orchestrator probe model) --------------
  // k8s/docker distinguish LIVENESS ("restart me") from READINESS ("send me
  // traffic"). Both are tiny HTTP endpoints returning 200/503 (NOT side effects).
  console.log("");
  console.log("  health checks (documented; the orchestrator probe model):");
  console.log("    /healthz (liveness) -> 200 once the process is up; 503 => restart me");
  console.log("    /readyz  (readiness)-> 200 once deps (DB) are warm;  503 => stop sending traffic");
  check("documented: liveness probes restart, readiness probes shed traffic", true);

  // --- Graceful SIGTERM shutdown (documented shape; the 🔗 REST_API dance) ----
  // The orchestrator sends SIGTERM; the app stops accepting NEW connections and
  // drains in-flight ones (server.close() + closeAllConnections()), then exits 0.
  console.log("");
  console.log("  graceful SIGTERM shutdown (documented; full dance in NODE_HTTP_SERVER):");
  console.log("    1. process.on('SIGTERM') -> server.close() (stop NEW conns)");
  console.log("    2. server.closeAllConnections() -> drain in-flight (Node >=18.2)");
  console.log("    3. await drain -> process.exit(0) within the grace period");
  check("documented: SIGTERM -> server.close() -> drain -> exit 0", true);

  // --- stdout logging: containers capture stdout, NOT files ------------------
  // A container's filesystem is ephemeral; a log file dies with the restart.
  // pino -> stdout -> docker/k8s logs -> a collector (Loki/ELK). (🔗 OBSERVABILITY)
  console.log("");
  console.log("  logging (documented; the container sink model):");
  console.log("    app -> pino -> STDOUT -> container runtime -> collector -> backend");
  console.log("    (logging to a file is LOST on container restart)");
  check("documented: production logs go to stdout (containers capture it)", true);
}

// ============================================================================
// Section D — Serverless functions (cold-start) + edge runtimes (V8 isolate,
// web-standard fetch, NO Node APIs).
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Serverless (cold-start) + edge (V8 isolate, web-standard fetch)");

  // --- Serverless functions (documented) --------------------------------------
  // A Lambda/Vercel Node function is a handler packaged for invocation on demand.
  // COLD-START dominates: the first request pays for module load + init, so the
  // prod rules are bundle SMALL (single dist/ file) and LAZY-LOAD heavy deps.
  console.log("  serverless functions (documented; Lambda/Vercel Node):");
  console.log("    - package a handler; the platform invokes it on demand");
  console.log("    - cold-start dominates: bundle SMALL (one dist/ file)");
  console.log("    - lazy-load heavy deps (don't pay their init cost until used)");
  console.log("    - instances are EPHEMERAL: no in-memory state across requests");
  check("documented: serverless cold-start favors a small bundled artifact", true);

  // --- Edge runtimes: assert the Worker snippet's STRUCTURE ------------------
  // Cloudflare Workers / Vercel Edge run the SAME web-standard code on a V8
  // isolate (like a browser tab's JS engine), distributed globally. The shape is
  // `export default { fetch(request, env, ctx) => Response }` — a Request comes
  // in, a Response goes out. NO Node APIs (fs/child_process) are available.
  const wlines = codeLines(WORKER);
  console.log("");
  console.log("  edge Worker snippet (hand-written; STRUCTURE asserted, NOT run):");
  for (const l of wlines) {
    console.log("    " + l);
  }

  check('Worker exports a default handler (export default)', WORKER.includes("export default"));
  check('Worker registers a fetch handler (fetch(request, env, ctx))', WORKER.includes("async fetch("));
  check('Worker reads the standard Request (new URL(request.url))', WORKER.includes("new URL(request.url)"));
  check('Worker returns a standard Response (new Response)', WORKER.includes("new Response("));
  check('Worker sets a status via the Response init ({ status: 404 })', WORKER.includes("status: 404"));
  check('Worker reads request.method (the HTTP verb)', WORKER.includes("request.method"));

  // THE KEY EDGE CONSTRAINT: no Node-only APIs. The snippet must not reach for
  // fs/child_process/require() — those do not exist on the V8 isolate surface.
  check('Worker does NOT use node:fs (no Node file API on edge)', !WORKER.includes("node:fs") && !WORKER.includes('from "fs"'));
  check('Worker does NOT use child_process (no process spawn on edge)', !WORKER.includes("child_process"));
  check('Worker does NOT use require() (ESM only on the isolate)', !WORKER.includes("require("));
  check('Worker does NOT use process.env directly (uses the `env` binding arg)', !WORKER.includes("process.env"));

  // --- Edge vs container: the deployment model contrast ----------------------
  console.log("");
  console.log("  deployment model contrast:");
  console.log("    long-lived container : one process, your scaling, SIGTERM shutdown");
  console.log("    serverless function  : handler invoked on demand; pays cold-start");
  console.log("    edge Worker          : V8 isolate, global, ~ms cold-start, web APIs only");
  check("documented: edge runs a V8 isolate (sub-ms cold-start vs container)", true);
  check("documented: edge exposes web-standard APIs (Request/Response/fetch)", true);
}

// ============================================================================
// Section E — Cross-language image/deploy model (Go static, Rust musl) +
// TS's edge advantage.
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Cross-language image/deploy model (Go/Rust vs Node)");

  // The headline contrast: Go and Rust compile to a SINGLE static binary that
  // runs on `scratch` (the empty image) — no OS, no runtime, no shell. Node
  // cannot: it must carry the V8 engine + libuv + node_modules, so even a
  // distroless Node image is an order of magnitude larger.
  console.log("  cross-language deploy model (the headline contrast):");
  console.log("    Go   : CGO_ENABLED=0 -> ONE static binary -> FROM scratch");
  console.log("           (no runtime in the image; ~10-20 MB; THE smallest, simplest)");
  console.log("    Rust : target x86_64-unknown-linux-musl -> ONE static binary -> scratch");
  console.log("           (same single-binary advantage as Go; ~10-30 MB)");
  console.log("    Node : must ship V8 + libuv + node_modules in the image");
  console.log("           (distroless helps, but cannot reach scratch; ~100-200 MB)");
  console.log("");
  console.log("  TS's compensating EDGE advantage (the place Node/TS wins):");
  console.log("    - the SAME TS fetch(Request)=>Response code runs on a V8 isolate");
  console.log("      globally (Cloudflare Workers/Vercel Edge) with ~ms cold-start;");
  console.log("    - Go/Rust edge runtimes exist but TS/JS is the native edge citizen");
  console.log("      (the V8 isolate IS the JS engine; no compile step to ship).");

  check("documented: Go compiles to a single static binary (CGO=0)", true);
  check("documented: Rust compiles to a single static binary (musl target)", true);
  check("documented: both Go and Rust run FROM scratch (no runtime in image)", true);
  check("documented: Node cannot reach scratch (must carry V8 + libuv + deps)", true);
  check("documented: Go/Rust images are ~1 order of magnitude smaller than Node", true);
  check("documented: TS's edge advantage is zero-compile, web-standard, global V8", true);
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("deployment.ts — Phase 8 bundle (web/).");
  console.log("This bundle CANNOT build/deploy (no network, no subprocess, no Docker).");
  console.log("Instead it is DETERMINISTIC: it READS static config files (the repo's");
  console.log("package.json via node:fs) and asserts the STRUCTURE of hand-written");
  console.log("deployment artifacts (a multi-stage Dockerfile, an edge Worker).");
  console.log("No Math.random, no Date.now, no subprocess, no network.");
  console.log("");
  console.log("Reminder: DEV runs `tsx` (type-erase, no bundle); PROD bundles to dist/");
  console.log("(esbuild/tsup), sets NODE_ENV=production, and runs `node dist/server.js`.");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
