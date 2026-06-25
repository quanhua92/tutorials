// modules_packages.ts — Phase 5 bundle (Standard Library Essentials).
//
// GOAL (one line): show, by printing every value, how JS's two module systems
// (ESM vs CommonJS) are detected, how Node resolves bare specifiers through
// package.json "exports"/"imports", what import.meta exposes, and how dynamic
// import() + top-level await behave — pinning each as a check()'d invariant.
//
// This is the GROUND TRUTH for MODULES_PACKAGES.md. Every value/table below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// LINEAGE (why this bundle exists): JavaScript lived with TWO module systems
// for a decade. CommonJS (require/module.exports) was Node's original —
// synchronous, with module.exports as a single mutable object. ES Modules
// (import/export) are the language standard — statically analyzable, with live
// bindings, asynchronous loading, and import.meta for per-module metadata.
// ESM won the standard war, but interop remains painful: importing a CJS
// module from ESM maps module.exports onto the DEFAULT import (named exports
// are best-effort), __dirname/__filename vanish (they were CJS-wrapper
// globals), and top-level await is ESM-only. Node decides which system a file
// uses by the package.json "type" field and the .mjs/.cjs extensions, and it
// resolves bare specifiers ("zod") through the "exports"/"imports" fields +
// the node_modules upward walk. This is JS's analog of Go modules (MVS) and
// Rust's mod/use/pub + Cargo — but with a DUAL system that neither has.
//
// SINGLE-FILE NOTE: this bundle cannot import a sibling .ts (one bundle = one
// .ts). ESM import/export semantics are therefore demonstrated three ways:
//   (1) a data: URL — a real, resolvable ES module whose source IS the URL,
//       dynamically imported() at runtime (the canonical single-file demo);
//   (2) a dynamic import() of a known built-in ("node:path"), proving bare
//       specifier -> built-in resolution;
//   (3) the bundle's OWN import.meta values (url, resolve), which exist ONLY
//       because this file is evaluated as an ES module (core/ is type:module).
//
// Run:
//     pnpm exec tsx modules_packages.ts   (or: just run modules_packages)

import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

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

// --- Top-level await (ESM only) ---------------------------------------------
// A data: URL module, awaited at the MODULE TOP LEVEL (outside any function).
// This single statement is itself proof the bundle runs as ESM: top-level
// await is a SyntaxError in CommonJS. The resolved value is reused in section B.
const tlaUrl = "data:text/javascript,export const top = 99;";
const TLA = (await import(tlaUrl)) as { top: number };

// ============================================================================
// Section A — ESM syntax (import/export) + import.meta.url
// ============================================================================

function sectionA(): void {
  sectionBanner("A — ESM syntax (import/export) + import.meta.url");

  // ESM import/export forms. A sibling .ts cannot be created (single-file
  // rule), so the SYNTAX -> BINDING mapping is printed here and the bindings
  // themselves are exercised on a data: URL module in Section B.
  console.log("ESM import forms and what each binds:");
  console.log('  import { v }      from "./m.js"   // named import   -> binding "v"');
  console.log('  import def        from "./m.js"   // default import -> def === m.default');
  console.log('  import * as ns    from "./m.js"   // namespace      -> ns.v, ns.default');
  console.log('  import { v as x } from "./m.js"   // aliased named  -> binding "x"');
  console.log('  import "./m.js"                   // side-effect only (no bindings)');
  console.log("");
  console.log("ESM export forms:");
  console.log("  export const v = 1;     // named export");
  console.log("  export default 42;      // default export (at most ONE per module)");
  console.log("  export { a, b };        // named export list (can be re-exported)");
  console.log('  export * from "./m.js"; // re-export all named (collisions -> SyntaxError)');

  // import.meta.url — the module's own file URL. In Node this is a file:// URL
  // pointing at the module's location on disk. Its mere presence is proof of
  // ESM: import.meta is a SyntaxError outside a module.
  const url: string = import.meta.url;
  const parsed = new URL(url);
  console.log("");
  console.log("import.meta (this bundle's own metadata):");
  console.log(`  import.meta.url = ${url}`);
  console.log(`  parsed.protocol = ${parsed.protocol}`);
  console.log(`  parsed.pathname = ${parsed.pathname}`);

  check("import.meta.url starts with 'file://'", url.startsWith("file://"));
  check("import.meta.url contains stem 'modules_packages'", url.includes("modules_packages"));
  check("URL protocol is 'file:'", parsed.protocol === "file:");
  check("URL pathname ends with 'modules_packages.ts'", parsed.pathname.endsWith("modules_packages.ts"));
  check("import.meta.url is a defined string (ESM-only metadata present)", typeof url === "string" && url.length > 0);
}

// ============================================================================
// Section B — Dynamic import() (async, on-demand) + top-level await
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — Dynamic import() (async, on-demand) + top-level await");

  // Dynamic import() is the RUNTIME import form. Unlike static `import` (which
  // is hoisted and must be top-level), import() is an EXPRESSION usable
  // anywhere, returns a Promise, and enables on-demand / code-split loading.
  // Here a data: URL is the imported module — its source is the URL itself.
  const dataUrl =
    "data:text/javascript,export const v = 42; export default 'def'; export const named = 7;";
  console.log("data URL module specifier (a real ES module whose source IS the URL):");
  console.log(`  ${dataUrl}`);

  // import() is ASYNC: it returns a Promise, not the module. Prove it before
  // awaiting. (A non-literal specifier — dataUrl is a variable of type string,
  // not a string literal — makes import() return Promise<any>; we narrow it.)
  const pending: Promise<unknown> = import(dataUrl);
  check("import(specifier) returns a Promise (it is async)", pending instanceof Promise);

  const mod = (await pending) as { v: number; default: string; named: number };
  console.log("");
  console.log("const m = await import(dataUrl)  — the resolved module namespace:");
  console.log(`  m.v       = ${mod.v}        (matches: import { v } from ...)`);
  console.log(`  m.default = ${JSON.stringify(mod.default)}     (matches: import def from ...)`);
  console.log(`  m.named   = ${mod.named}        (matches: import { named } from ...)`);
  check("data-URL dynamic import: m.v === 42 (named export)", mod.v === 42);
  check("data-URL dynamic import: m.default === 'def' (default export)", mod.default === "def");
  check("data-URL dynamic import: m.named === 7 (named export)", mod.named === 7);
  check("namespace object exposes v/default/named keys", "v" in mod && "default" in mod && "named" in mod);

  // Dynamic import of a BUILT-IN via a bare specifier: resolves straight to the
  // built-in (step 1 of the resolution walk, Section E). A literal specifier
  // here is fine — TS resolves "node:path" to its real type, so no narrowing.
  const builtIn = await import("node:path");
  console.log("");
  console.log("Dynamic import of a built-in (bare specifier -> built-in resolution):");
  console.log(`  const p = await import('node:path');   p.sep = ${JSON.stringify(builtIn.sep)}`);
  check("dynamic import of 'node:path' resolves (bare -> built-in)", builtIn.sep === path.sep);
  check("dynamic import('node:path') and static import 'node:path' agree", builtIn.sep === path.sep);

  // Top-level await is ESM-ONLY (a SyntaxError in CommonJS). The bundle already
  // used it at module top level to load { top: 99 } into TLA. Reusing that
  // value here proves the await at module scope actually executed.
  console.log("");
  console.log("Top-level await (ESM only — SyntaxError in CJS):");
  console.log("  At the TOP LEVEL of this file (outside any function):");
  console.log('  const TLA = (await import("data:...export const top = 99;")) as { top: number };');
  console.log(`  TLA.top reached main(): ${TLA.top}`);
  check("top-level await resolved TLA.top === 99 (ESM-only feature works)", TLA.top === 99);
}

// ============================================================================
// Section C — CommonJS vs ECMAScript Modules (how Node decides)
// ============================================================================

function sectionC(): void {
  sectionBanner("C — CommonJS vs ECMAScript Modules (how Node decides)");

  console.log("Two module systems coexist in Node:");
  console.log("");
  console.log("  CJS (CommonJS — Node's original):");
  console.log("    const fs = require('node:fs');          // synchronous, returns module.exports");
  console.log("    module.exports = { x: 1 };              // a single mutable exports object");
  console.log("    exports.y = 2;                          // shorthand for module.exports.y");
  console.log("    __dirname, __filename                   // CJS-wrapper globals (sync, paths)");
  console.log("");
  console.log("  ESM (ECMAScript Modules — the standard):");
  console.log("    import fs from 'node:fs';               // static, hoisted, async-loaded");
  console.log("    export const x = 1; export default 42;  // named + default (live bindings)");
  console.log("    import.meta                             // per-module metadata (url, resolve)");
  console.log("    await ...                               // top-level await (ESM ONLY)");

  console.log("");
  console.log("Determining the module system (Node 'Determining module system'):");
  console.log("  .mjs                              -> ALWAYS ESM (extension wins)");
  console.log("  .cjs                              -> ALWAYS CJS (extension wins)");
  console.log("  .js + nearest pkg 'type':'module'  -> ESM    <-- THIS bundle (core/ is type:module)");
  console.log("  .js + nearest pkg 'type':'commonjs'-> CJS");
  console.log("  .js + no 'type' field              -> CJS by default (syntax detection may flip it)");

  // Runtime evidence that THIS file is ESM. __dirname/__filename are NOT ESM
  // globals — they are injected only by the CommonJS module wrapper. Reaching
  // them through globalThis avoids a TS "cannot find name" error (they are
  // absent from the ESM global type) and lets us read their runtime typeof.
  const g = globalThis as unknown as Record<string, unknown>;
  console.log("");
  console.log("Runtime evidence that THIS bundle is evaluated as ESM:");
  console.log(`  typeof globalThis.__dirname  = ${typeof g.__dirname}   (CJS-only global; absent in ESM)`);
  console.log(`  typeof globalThis.__filename = ${typeof g.__filename}   (CJS-only global; absent in ESM)`);
  console.log(`  typeof import.meta.url       = ${typeof import.meta.url}   (ESM-only metadata)`);

  check("__dirname is undefined in ESM (CJS-only global, absent)", typeof g.__dirname === "undefined");
  check("__filename is undefined in ESM (CJS-only global, absent)", typeof g.__filename === "undefined");
  check("import.meta.url is defined (ESM metadata present)", typeof import.meta.url === "string");
  check("core/ package.json type:module => this .ts evaluates as ESM", import.meta.url.startsWith("file://"));
}

// ============================================================================
// Section D — CJS/ESM interop + the __dirname/__filename fix
// ============================================================================

function sectionD(): void {
  sectionBanner("D — CJS/ESM interop + the __dirname/__filename fix");

  // createRequire bridges INTO CommonJS from ESM: it builds a real CJS
  // require() anchored at this module's URL. The reverse direction — importing
  // a CJS module FROM ESM — maps module.exports onto the ESM DEFAULT import.
  const cjsRequire = createRequire(import.meta.url);
  const cjsPath = cjsRequire("node:path") as { sep: string; delimiter: string };
  console.log("createRequire(import.meta.url) — a CJS require() usable inside ESM:");
  console.log("  const r = createRequire(import.meta.url);");
  console.log(`  r('node:path').sep       = ${JSON.stringify(cjsPath.sep)}`);
  console.log(`  r('node:path').delimiter = ${JSON.stringify(cjsPath.delimiter)}`);
  check("CJS require (via createRequire) returns path.sep", cjsPath.sep === path.sep);
  check("CJS require (via createRequire) returns path.delimiter", cjsPath.delimiter === path.delimiter);

  // The interop rule that bites: importing CJS from ESM.
  console.log("");
  console.log("Interop rule — importing a CJS module FROM ESM:");
  console.log("  import cjsDefault from './legacy.cjs'   // cjsDefault === module.exports (the WHOLE object)");
  console.log("  import { named }   from './legacy.cjs'  // named may be UNDEFINED: CJS has no real");
  console.log("                                          //  named exports; Node static-analysis");
  console.log("                                          //  ('cjs-module-lexer') guesses them.");
  console.log("  => Prefer the default import for CJS modules; destructure AFTERWARD if needed.");

  // The __dirname/__filename fix — reconstruct from import.meta.url.
  // ESM has no __dirname; the standard replacement is fileURLToPath + path.dirname.
  const filename = fileURLToPath(import.meta.url);
  const dirname = path.dirname(filename);
  console.log("");
  console.log("Reconstructing __dirname/__filename in ESM (fileURLToPath + path.dirname):");
  console.log(`  fileURLToPath(import.meta.url) = ${filename}`);
  console.log(`  path.dirname(...)              = ${dirname}`);
  console.log(`  path.basename(filename)        = ${path.basename(filename)}`);
  console.log(`  path.basename(dirname)         = ${path.basename(dirname)}`);

  check("reconstructed filename ends with 'modules_packages.ts'", filename.endsWith("modules_packages.ts"));
  check("reconstructed dirname basename is 'core'", path.basename(dirname) === "core");
  check(
    "filename === path.join(dirname, path.basename(filename)) (round-trip)",
    filename === path.join(dirname, path.basename(filename)),
  );
}

// ============================================================================
// Section E — Node resolution (exports/imports) + circular imports + cross-lang
// ============================================================================

function sectionE(): void {
  sectionBanner("E — Node resolution (exports/imports) + circular imports + cross-lang");

  console.log("Bare specifier resolution walk (Node, modern algorithm):");
  console.log("  1. Built-in?         ('node:fs', 'fs', 'path') -> load the built-in.");
  console.log("  2. Starts with '#'?  -> consult package.json 'imports' (PRIVATE map).");
  console.log("  3. Bare package?     ('zod', '@scope/pkg') -> walk node_modules UPWARD");
  console.log("                          to the nearest match, then:");
  console.log("       a. read its package.json 'exports' (modern, ENCAPSULATING field);");
  console.log("       b. match subpath + conditions (import / require / node / default);");
  console.log("       c. fall back to legacy 'main' if 'exports' is absent.");
  console.log("  4. Relative/absolute?('./', '../', '/', 'file://') -> resolve as a file URL.");
  console.log("     (ESM import does NOT add extensions or resolve directory indexes.)");

  console.log("");
  console.log("package.json 'exports' — subpaths + conditions (modern, encapsulating):");
  console.log('  "exports": {');
  console.log('    ".":        { "import": "./esm/index.mjs", "require": "./cjs/index.cjs" },');
  console.log('    "./feature": "./feature.js",');
  console.log('    "./internal/*": null');
  console.log('  }');
  console.log("  -> import 'pkg'            resolves via '.' using condition 'import'.");
  console.log("  -> import 'pkg/feature'    resolves via './feature'.");
  console.log("  -> import 'pkg/internal/x' THROWS ERR_PACKAGE_PATH_NOT_EXPORTED (null target).");
  console.log("  -> import 'pkg/secret.js'  THROWS (encapsulated: only declared paths are public).");

  console.log("");
  console.log("package.json 'imports' — PRIVATE self-map (must start with '#'):");
  console.log('  "imports": { "#dep": { "node": "dep-native", "default": "./polyfill.js" } }');
  console.log("  -> import '#dep'  (valid ONLY inside this package; maps per condition).");

  console.log("");
  console.log("Specifier kinds:");
  console.log("  bare:      'zod', 'node:fs', '@scope/pkg'    (resolved, not a path)");
  console.log("  relative:  './m.js', '../util.js'            (relative to importer)");
  console.log("  absolute:  '/abs/m.js', 'file:///abs/m.js'   (URL or root path)");

  // import.meta.resolve — Node >= 20.6: a SYNCHRONOUS specifier resolver that
  // returns the resolved URL string using this module's URL as base. Typed on
  // recent @types/node; we intersect defensively so the bundle typechecks on
  // older type packages too.
  const meta = import.meta as ImportMeta & { resolve?: (specifier: string) => string };
  console.log("");
  console.log("import.meta.resolve (Node >= 20.6, synchronous):");
  console.log("  Resolves a specifier to a URL using THIS module's URL as base.");
  if (typeof meta.resolve === "function") {
    const resolvedFs = meta.resolve("node:fs");
    const resolvedSelf = meta.resolve("./modules_packages.ts");
    console.log(`  import.meta.resolve('node:fs')               = ${resolvedFs}`);
    console.log(`  import.meta.resolve('./modules_packages.ts') = ${resolvedSelf}`);
    check(
      "import.meta.resolve('node:fs') returns a non-empty string",
      typeof resolvedFs === "string" && resolvedFs.length > 0,
    );
    check("import.meta.resolve('node:fs') yields a 'node:' URL", resolvedFs.startsWith("node:"));
    check(
      "import.meta.resolve('./modules_packages.ts') yields a 'file:' URL",
      resolvedSelf.startsWith("file:"),
    );
    check(
      "resolved self URL contains the stem 'modules_packages'",
      resolvedSelf.includes("modules_packages"),
    );
  } else {
    console.log("  (import.meta.resolve not available in this runtime)");
    check("import.meta.resolve is a function", false);
  }

  console.log("");
  console.log("Circular imports (the dual-system gotcha):");
  console.log("  ESM: LIVE BINDINGS — a partially-initialized module IS visible to");
  console.log("        its importer. The imported binding exists from the start; its");
  console.log("        value may be undefined until the cycle finishes initializing.");
  console.log("        Mutations through the binding are seen live (no snapshot).");
  console.log("  CJS: module.exports is a cached PARTIAL object at cycle time. A");
  console.log("        require() that hits a cycle returns whatever was on");
  console.log("        module.exports at that instant; properties added LATER may");
  console.log("        be missed depending on import order. The classic CJS trap.");

  console.log("");
  console.log("Cross-language parallels (design contrasts, not executed here):");
  console.log("  Go  modules + go.mod: MVS (Minimal Version Selection) selects the");
  console.log("        MINIMUM version that satisfies all requirements over a version");
  console.log("        graph. Deterministic, no node_modules tree, no dual system.");
  console.log("  Rust mod/use/pub + Cargo: a STATIC module tree with EXPLICIT");
  console.log("        visibility (pub / pub(crate)). One system; the compiler");
  console.log("        builds the whole tree; no require/import duality, no interop.");
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("modules_packages.ts — Phase 5 bundle (Standard Library Essentials).");
  console.log("Every value below is computed by this file; the .md guide pastes it");
  console.log("verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: this bundle runs as an ESM module (core/ package.json is");
  console.log('type:module). import.meta, top-level await, and static import/export');
  console.log("are all ESM features — they would be SyntaxErrors under CommonJS.");
  sectionA();
  await sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionBanner("DONE — all sections printed");
}

// Top-level await of main() — itself a second proof this file is ESM
// (top-level await is forbidden in CommonJS).
await main();
