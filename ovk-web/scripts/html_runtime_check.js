#!/usr/bin/env node
// html_runtime_check.js — DOM-mock runtime smoke test for bundle .html files.
// `node --check` is syntax-only; this EXECUTES each <script> in a minimal DOM
// sandbox to catch runtime errors (undefined access, wrong arg counts, null
// derefs). SKILL.md §15.2.
//
// Usage: node scripts/html_runtime_check.js [dir]   (default: bundles)
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const dir = process.argv[2] || "bundles";
const cwd = process.cwd();
const absDir = path.isAbsolute(dir) ? dir : path.join(cwd, dir);

let files = [];
try { files = fs.readdirSync(absDir).filter(f => f.endsWith(".html") && f !== "index.html").sort(); }
catch (e) { console.error(`  cannot read ${absDir}: ${e.message}`); process.exit(1); }

const ctxStub = new Proxy({}, { get(_, p) {
  if (p === "measureText") return () => ({ width: 10 });
  if (p === "getImageData") return () => ({ data: new Uint8Array(4) });
  if (p === "createImageData") return () => ({ data: new Uint8Array(4) });
  if (p === "createLinearGradient") return () => ({ addColorStop() {} });
  return typeof p === "string" ? () => {} : undefined;
}});

const fakeEl = new Proxy({}, {
  get(_, p) {
    if (p === "innerHTML" || p === "textContent" || p === "value" || p === "innerText") return "";
    if (p === "style" || p === "dataset") return {};
    if (p === "classList") return { add(){}, remove(){}, toggle(){}, contains(){ return false; } };
    if (p === "querySelector") return () => fakeEl;
    if (p === "querySelectorAll") return () => [];
    if (p === "closest") return () => fakeEl;
    if (p === "getContext") return () => ctxStub;
    if (p === "getBoundingClientRect") return () => ({ width: 800, height: 400, left: 0, top: 0 });
    if (p === "getAttribute") return () => null;
    if (p === "addEventListener" || p === "removeEventListener") return () => {};
    if (p === "appendChild" || p === "append" || p === "prepend") return () => fakeEl;
    if (p === "checked") return true;
    if (p === "selectedIndex") return 0;
    if (p === "options") return [{ value: "", text: "" }];
    if (p === "width" || p === "height") return 800;
    return () => {};
  },
  set() { return true; },
});

let pass = 0, fail = 0;
for (const file of files) {
  const html = fs.readFileSync(path.join(absDir, file), "utf8");
  const scripts = [...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)];
  if (scripts.length === 0) continue;
  const code = scripts.map(m => m[1]).join("\n;\n");
  const sandbox = {
    console: { log() {}, warn() {}, error() {}, info() {}, debug() {} },
    Math, Date, JSON, parseInt, parseFloat, isNaN, isFinite,
    String, Number, Boolean, Array, Object, RegExp, Error, Symbol, Map, Set, WeakMap, WeakSet,
    Uint8Array, Uint16Array, Uint32Array, Float32Array, Float64Array, ArrayBuffer,
    Promise, Reflect, Proxy,
    setTimeout() {}, clearTimeout() {}, setInterval() {}, clearInterval() {},
    requestAnimationFrame() {}, cancelAnimationFrame() {},
    queueMicrotask() {},
    localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    location: { pathname: "/" + file, hash: "", search: "", href: "", replace() {}, reload() {} },
    document: {
      getElementById() { return fakeEl; },
      querySelector() { return fakeEl; },
      querySelectorAll() { return []; },
      createElement() { return fakeEl; },
      createElementNS() { return fakeEl; },
      createTextNode() { return fakeEl; },
      getElementsByClassName() { return []; },
      getElementsByTagName() { return []; },
      addEventListener() {}, removeEventListener() {},
      body: fakeEl, documentElement: fakeEl,
    },
    window: { addEventListener() {}, removeEventListener() {}, requestAnimationFrame() {} },
    navigator: { userAgent: "node" },
    gsap: new Proxy({}, { get() { return () => ({ to(){return this;}, from(){return this;}, set(){return this;}, seek(){return this;}, time(){return 0;}, duration(){return 1;}, kill(){} }); } }),
  };
  sandbox.self = sandbox; sandbox.globalThis = sandbox;
  sandbox.window.document = sandbox.document;
  try {
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox, { filename: file, timeout: 3000 });
    console.log(`  ${file}: RUNTIME OK`);
    pass++;
  } catch (e) {
    console.log(`  ${file}: RUNTIME FAIL — ${e.message}`);
    fail++;
  }
}
console.log(`\n${pass} passed, ${fail} failed out of ${pass + fail}`);
process.exit(fail > 0 ? 1 : 0);
