// runtimes_node_bun_deno.ts — Phase 8 bundle (the runtime question).
//
// GOAL (one line): feature-detect the CURRENT runtime (Node, here), print the
// Node+V8+libuv facts that are observable now, and DOCUMENT the Bun/Deno facts
// that can't be run in this workspace — the honest "Node vs Bun vs Deno".
//
// This is the GROUND TRUTH for RUNTIMES_NODE_BUN_DENO.md. Every number, table,
// and worked example in the guide is printed by this file. Change it -> re-run
// -> re-paste. Never hand-compute.
//
// LINEAGE (why this bundle exists): TypeScript/JavaScript has THREE production
// runtimes — Node (V8 + libuv, the incumbent and this curriculum's target),
// Bun (JavaScriptCore, native TS, an all-in-one toolchain), and Deno (V8,
// secure-by-default permissions, web-standard-first). They share the LANGUAGE
// (ECMAScript) and an increasingly shared web-API surface (fetch / Streams /
// Web Crypto) but differ in ENGINE (V8 vs JSC), STDLIB shape, and TOOLCHAIN.
// This bundle is the expert payoff on the runtime question: it asserts the
// facts observable RIGHT NOW (we run UNDER Node — process.versions.v8, the
// absence of Bun/Deno globals, the presence of the web APIs) and documents the
// rest (Bun's JSC, Deno's permissions) which cannot be executed here.
//
// DETERMINISM NOTE: this bundle runs UNDER NODE (the workspace runtime). Every
// printed value is stable for the installed Node build — process.versions.*
// and process.features.* are constants of the binary, not of the clock or a
// PRNG. The only machine-specific datum (the absolute path of the tsx loader)
// is reduced to a boolean BEFORE printing, so `just out` is byte-identical.
//
// Run:
//     pnpm exec tsx runtimes_node_bun_deno.ts   (or: just run runtimes_node_bun_deno)

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

// --- runtime globals narrow ------------------------------------------------
//
// Bun and Deno inject a top-level global (`Bun`, `Deno`) that does NOT exist
// under @types/node, so a bare `typeof Bun` is a tsc error. We widen
// globalThis through `as unknown as {...}` — a TYPE-ONLY cast that EMITS NO
// CODE (assertions are erased by tsx/tsc) — so the runtime `typeof` check
// reflects the REAL current global, which is `undefined` here under Node.
// No `any`: the members are concrete optional shapes.
const runtimeGlobals = globalThis as unknown as {
  Bun?: { readonly version: string };
  Deno?: { readonly version: { readonly deno: string } };
};

// detectRuntime is THE feature-detection idiom: it returns which of the three
// production runtimes is hosting this process, in priority order. Under Node
// both Bun and Deno are absent, so it falls through to "node".
function detectRuntime(): "node" | "bun" | "deno" {
  if (typeof runtimeGlobals.Bun !== "undefined") return "bun";
  if (typeof runtimeGlobals.Deno !== "undefined") return "deno";
  return "node";
}

// ============================================================================
// Section A — Detect the current runtime (the feature-detection idiom)
// ============================================================================

function sectionA(): void {
  sectionBanner("A — Detect the current runtime (the feature-detection idiom)");

  // The three signals, observed at runtime. Under this workspace all of:
  //   typeof Bun  === "undefined"
  //   typeof Deno === "undefined"
  //   process.versions.node is a string
  // hold simultaneously -> we are unambiguously on Node.
  console.log("Runtime feature-detection signals (observed NOW):");
  console.log(`  typeof Bun            : ${typeof runtimeGlobals.Bun}`);
  console.log(`  typeof Deno           : ${typeof runtimeGlobals.Deno}`);
  console.log(`  typeof process        : ${typeof process}`);
  console.log(`  process.versions.node : ${process.versions.node}`);
  console.log(`  detectRuntime()       : ${detectRuntime()}`);

  check("typeof Bun === \"undefined\" (not running under Bun)", typeof runtimeGlobals.Bun === "undefined");
  check("typeof Deno === \"undefined\" (not running under Deno)", typeof runtimeGlobals.Deno === "undefined");
  check("typeof process === \"object\" (Node exposes the process global)", typeof process === "object");
  check("typeof process.versions.node === \"string\" (we ARE on Node)", typeof process.versions.node === "string");
  check("detectRuntime() === \"node\" under this workspace", detectRuntime() === "node");

  // The expert note: `typeof X === "undefined"` is the SAFE existence probe —
  // it returns "undefined" for an undeclared global WITHOUT throwing, whereas a
  // bare `Bun` reference would throw ReferenceError in Node. This is the same
  // property that makes `typeof undeclaredVar === "undefined"` the canonical
  // feature-detect (see VALUES_TYPES_COERCION Section A, the 8 typeof strings).
  console.log("");
  console.log("Note: `typeof X === \"undefined\"` never throws even for an undeclared");
  console.log("global — that is WHY it is the feature-detection idiom. A bare `Bun`");
  console.log("reference would throw ReferenceError here; `typeof Bun` returns");
  console.log("\"undefined\" safely.");
}

// ============================================================================
// Section B — Node: V8 + libuv (the incumbent) & the native-TS path
// ============================================================================

function sectionB(): void {
  sectionBanner("B — Node: V8 + libuv (the incumbent) & the native-TS path");

  // Node = the V8 JavaScript engine + libuv (the event loop) + a large C++ core
  // (fs/net/crypto/...). The engine version and the libuv version are both
  // exposed on process.versions — these are CONSTANTS of the installed binary,
  // so they are deterministic across `just out` runs on this Node.
  console.log("Node's engine stack (from process.versions — constants of this binary):");
  console.log(`  process.versions.node : ${process.versions.node}   <- the Node.js release`);
  console.log(`  process.versions.v8   : ${process.versions.v8}   <- the JS ENGINE (V8)`);
  console.log(`  process.versions.uv   : ${process.versions.uv}   <- libuv (the event loop)`);

  check("typeof process.versions.v8 === \"string\" (V8 is the engine)", typeof process.versions.v8 === "string");
  check("typeof process.versions.uv === \"string\" (libuv is bundled)", typeof process.versions.uv === "string");
  check("process.versions.v8 starts with a digit (a real semver-ish version)", /[0-9]/.test(process.versions.v8.charAt(0)));

  // The event loop is libuv's (not V8's). V8 runs JS; libuv polls the OS and
  // feeds callbacks back to V8. The full queue model is 🔗 EVENT_LOOP; here we
  // only pin the version, which proves libuv is the loop in this process.
  console.log("");
  console.log("Why Node is this curriculum's target (documented):");
  console.log("  - V8 + libuv internals are PUBLIC and documented (v8.dev, nodejs.org);");
  console.log("    the loop (🔗 EVENT_LOOP) and GC (🔗 GARBAGE_COLLECTION) bundles are");
  console.log("    Node-accurate because V8/Orinoco are the real engine.");
  console.log("  - Largest ecosystem (npm) and the most stable, best-documented runtime.");
  console.log("  - Mature CJS/ESM interop and a stable, versioned stdlib (node:*).");

  // --- native TypeScript execution under Node --------------------------------
  // Node 22.6 added --experimental-strip-types; 22.18.0+ strips types by
  // DEFAULT for erasable-only syntax (no enum/param-properties/namespaces);
  // process.features.typescript exposes the mode. But this workspace routes
  // every run through `tsx` (esbuild) via the Justfile for cross-version
  // stability — detectable from process.execArgv. We print only a BOOLEAN of
  // the latter (the loader path is machine-specific -> would break determinism).
  const tsMode: "strip" | "transform" | false = process.features.typescript;
  const runsViaTsx: boolean = process.execArgv.some((arg) => arg.includes("tsx"));

  console.log("");
  console.log("Native TypeScript execution (the Node path, observed NOW):");
  console.log(`  process.features.typescript : ${String(tsMode)}   <- "strip" = Node can erase types`);
  console.log(`  running via tsx (loader)?   : ${runsViaTsx}   <- the Justfile uses tsx, not bare node`);

  check("process.features.typescript === \"strip\" (Node's native type-stripping is on)", tsMode === "strip");
  check("this workspace run is routed through tsx (process.execArgv contains tsx)", runsViaTsx === true);

  console.log("");
  console.log("Node strips types but does NOT type-check: `node file.ts` runs after erasing");
  console.log("erasable syntax, then `tsc --noEmit` is a SEPARATE gate (🔗 BUILD_TOOLING).");
  console.log("This bundle is run by `tsx` (esbuild), which likewise erases types without");
  console.log("type-checking — the workspace's typecheck gate is `just typecheck`.");
}

// ============================================================================
// Section C — Bun: JavaScriptCore + all-in-one toolchain (DOCUMENTED)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — Bun: JavaScriptCore + all-in-one toolchain (DOCUMENTED)");

  // Bun CANNOT be run in this workspace (we asserted typeof Bun === "undefined"
  // in Section A). Everything below is DOCUMENTED from bun.sh/docs — it is not
  // asserted by check() because no Bun global exists to observe here.
  console.log("Bun facts (DOCUMENTED — not executable under Node; typeof Bun === \"undefined\"):");
  console.log("  Engine        : JavaScriptCore (JSC, Apple's) — NOT V8. Different GC and");
  console.log("                  JIT internals from Node/Deno (🔗 GARBAGE_COLLECTION caveat).");
  console.log("  TypeScript    : runs .ts / .tsx / .jsx NATIVELY — no tsx, no build step.");
  console.log("  Toolchain     : all-in-one — runtime + bundler + test runner (`bun test`)");
  console.log("                  + package manager (`bun install`). One binary does all four.");
  console.log("  Startup       : faster cold start than Node (JSC + a Zig-written core).");
  console.log("  Node compat   : implements Node-API so native addons built for Node run");
  console.log("                  unmodified; npm-package compat is high but not 100%.");
  console.log("");
  console.log("Implication for THIS curriculum: a bundle teaching V8 internals");
  console.log("(the Orinoco GC, the ignition/turbofan pipeline) is Node/Deno-accurate;");
  console.log("under Bun those internals are JSC's and differ. The LANGUAGE semantics");
  console.log("(values, coercion, closures, the prototype chain, async) are identical,");
  console.log("because all three run ECMAScript — only the engine + stdlib differ.");
}

// ============================================================================
// Section D — Deno: V8 + permissions + web-standard-first (DOCUMENTED)
// ============================================================================

function sectionD(): void {
  sectionBanner("D — Deno: V8 + permissions + web-standard-first (DOCUMENTED)");

  // Deno CANNOT be run in this workspace (typeof Deno === "undefined"). The
  // facts below are DOCUMENTED from docs.deno.com.
  console.log("Deno facts (DOCUMENTED — not executable under Node; typeof Deno === \"undefined\"):");
  console.log("  Engine        : V8 (the SAME engine as Node) — so V8-internal bundles");
  console.log("                  (🔗 GARBAGE_COLLECTION) are Deno-accurate too.");
  console.log("  TypeScript    : runs .ts NATIVELY — type-stripping is built in.");
  console.log("  Permissions   : secure-by-default. A script has NO file/net/env access");
  console.log("                  unless granted: --allow-read, --allow-net, --allow-env,");
  console.log("                  --allow-run ... or --allow-all (-A). Node/Bun grant all.");
  console.log("  Stdlib        : a `Deno.*` namespace + web-standard-first (fetch, Web");
  console.log("                  Streams, Web Crypto as the primary surface), NOT node:*.");
  console.log("  npm compat    : can import npm packages via `npm:` specifiers; node:*");
  console.log("                  compat layer exists, but the native idiom is web-standard.");
  console.log("");
  console.log("Shared with Node: the V8 engine and (increasingly) the web APIs. Differing:");
  console.log("the permission model (Deno asks; Node grants) and the stdlib entry point");
  console.log("(Deno.* + web standard vs node:*). The event loop is V8+libuv-equivalent");
  console.log("(🔗 EVENT_LOOP) — Deno uses its own scheduler over V8 + Tokio (Rust).");
}

// ============================================================================
// Section E — Shared web APIs (convergence) + which to pick + the V8/JSC caveat
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Shared web APIs (convergence) + which to pick + V8/JSC caveat");

  // The convergence story: fetch, Request/Response/Headers, the Web Streams,
  // URL, and Web Crypto are implemented by ALL THREE runtimes as globals. We
  // assert their presence under Node (Node 18+ added them as globals); the
  // same globals exist under Bun and Deno — that IS the web-standard surface.
  const webApis: ReadonlyArray<readonly [string, unknown]> = [
    ["fetch", typeof fetch],
    ["Request", typeof Request],
    ["Response", typeof Response],
    ["Headers", typeof Headers],
    ["ReadableStream", typeof ReadableStream],
    ["URL", typeof URL],
    ["crypto.subtle", typeof crypto?.subtle],
    ["queueMicrotask", typeof queueMicrotask],
  ];

  console.log("Shared web APIs (present as globals under Node — same names in Bun/Deno):");
  for (const [name, kind] of webApis) {
    console.log(`  ${name.padEnd(18)} -> ${String(kind)}`);
  }
  for (const [name, kind] of webApis) {
    check(`typeof ${name} is defined (web-standard API present under Node)`, kind !== "undefined");
  }

  // The "which to pick" decision — DOCUMENTED (no runtime verdict; a judgement).
  console.log("");
  console.log("Which to pick (DOCUMENTED decision matrix — the honest expert answer):");
  console.log("  Pick NODE  when: you want stability + the largest ecosystem + the most");
  console.log("                documented internals. The safe default (this curriculum).");
  console.log("  Pick BUN   when: startup speed and an all-in-one toolchain matter most");
  console.log("                (scripts, CLIs, monorepos). Accept JSC-vs-V8 internals.");
  console.log("  Pick DENO  when: a permission/security model or web-standard-first");
  console.log("                stdlib is the priority (sandboxed tooling, edge).");

  // The V8-vs-JSC internals caveat — the single most important engine fact.
  console.log("");
  console.log("The V8-vs-JSC internals caveat (DOCUMENTED):");
  console.log("  - Node AND Deno run V8  -> V8-internal bundles (Orinoco GC, the ignition/");
  console.log("    turbofan JIT, the 🔗 EVENT_LOOP over libuv/Tokio) describe them BOTH.");
  console.log("  - Bun runs JavaScriptCore -> its GC and JIT differ. A 'how V8 GC works'");
  console.log("    lesson is Node/Deno-accurate but NOT Bun-accurate (🔗 GARBAGE_COLLECTION).");
  console.log("  - The shared CORE across all three is ECMAScript + the web APIs above:");
  console.log("    values, coercion, closures, prototypes, async, fetch, Streams, Crypto.");
}

// ============================================================================
// main
// ============================================================================

function main(): void {
  console.log("runtimes_node_bun_deno.ts — Phase 8 bundle (the runtime question).");
  console.log("Asserts the Node+V8+libuv facts observable NOW; DOCUMENTS Bun/Deno.");
  console.log("Every value below is computed by this file; the .md guide pastes it");
  console.log("verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: this bundle runs UNDER NODE. Bun/Deno globals are absent here,");
  console.log("so their facts are documented (not check()'d) — we assert only what is");
  console.log("observable in this process (process.versions, the web APIs).");
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

main();
