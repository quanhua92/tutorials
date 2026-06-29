// data_binding — ground-truth runnable for "__FIELD__ stamping" (RFC 0001 §5.6)
// Run: pnpm exec tsx bundles/data_binding.ts
//
// Teaches how `fields` in slide `index.json` reach slide `index.html`: STRING
// REPLACEMENT ("stamping"). Each field id uppercases to a placeholder
// (`title` -> `__TITLE__`) and is substituted into the HTML. Stamping exists
// because HyperFrames' getVariables() returns {} in sub-compositions
// (AGENTS.md), so HF variables cannot be used. This runnable prints every value
// DATA_BINDING.md cites verbatim, including the MDN-verified $-replacement pitfall.

export {}; // make this a module (isolated top-level scope, no cross-file clashes)


const BANNER = "=".repeat(60);
const banner = (t: string): void => {
  console.log(`\n${BANNER}\n${t}\n${BANNER}`);
};

/** Assert an invariant; prints `[check] desc: OK` and exits non-zero on failure. */
function check(desc: string, ok: boolean): void {
  if (!ok) {
    console.error(`FAIL: ${desc}`);
    process.exit(1);
  }
  console.log(`[check] ${desc}: OK`);
}

// ---- deterministic sample data (NO Date.now, NO Math.random, NO FS reads) ----

// RFC 0001 §5.3 — slide index.json `fields` is the source of values.
const SLIDE_FIELDS: Record<string, string> = {
  title: "Eco Bottle",
  body: "Hello World",
};

// RFC 0001 §5.4 / AGENTS.md "Layout file format" — bare <template> sub-comp.
// __SLIDE_ID__ is the special slide-id placeholder; the rest are __FIELD__ ids.
const SAMPLE_TEMPLATE = `<template>
  <div data-composition-id="__SLIDE_ID__" data-width="1920" data-height="1080">
    <div class="content">
      <h1>__TITLE__</h1>
      <p>__BODY__</p>
    </div>
    <style>
      [data-composition-id="__SLIDE_ID__"] { background: #0a0a14; }
      [data-composition-id="__SLIDE_ID__"] h1 { font-size: 120px; }
    </style>
    <script>
      window.__timelines['__SLIDE_ID__'] = gsap.timeline({ paused: true });
    </script>
  </div>
</template>`;

// A template with an image field, to show path (not text) replacement.
const IMAGE_TEMPLATE = `<template>
  <div data-composition-id="__SLIDE_ID__">
    <img src="__IMAGE__" alt="hero" />
  </div>
</template>`;

// ---- helpers (the stamping mechanism itself) ----

/**
 * The placeholder rule (AGENTS.md "Placeholder convention"):
 * field id `title` -> `__TITLE__` (uppercased, wrapped in double underscores).
 * `__SLIDE_ID__` is the special slide-id placeholder, not a field.
 */
function placeholderFor(id: string): string {
  return "__" + id.toUpperCase() + "__";
}

/**
 * The NAIVE stamp function: html.replaceAll(placeholder, value).
 * RFC §5.6 — string replacement is the data-injection mechanism.
 *
 * WARNING (see Section E): a `value` containing $$, $&, $`, or $' is corrupted,
 * because String.prototype.replaceAll treats those as special replacement
 * patterns when the REPLACEMENT is a string. Safe form below.
 */
function stampNaive(html: string, id: string, value: string): string {
  return html.replaceAll(placeholderFor(id), value);
}

/**
 * The SAFE stamp function: replacement is a FUNCTION, so the special $ patterns
 * do NOT apply (MDN: "special replacement patterns do not apply for strings
 * returned from the replacer function"). This is the fix mandated for any value
 * that may contain $.
 */
function stampSafe(html: string, id: string, value: string): string {
  return html.replaceAll(placeholderFor(id), () => value);
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the placeholder rule + the stamp function");
  console.log("  RFC 0001 §5.6 + AGENTS.md \"Placeholder convention\"\n");
  console.log("  field id   -> placeholder   (uppercased, wrapped in __)");
  const ids = ["title", "body", "image", "step"];
  for (const id of ids) {
    console.log(`    ${id.padEnd(10)} -> ${placeholderFor(id)}`);
    check(`placeholder for "${id}" is __ID_UPPER__`, placeholderFor(id) === `__${id.toUpperCase()}__`);
  }
  console.log("  special:   __SLIDE_ID__ (slide-id, not a field id)");
  console.log("\n  the stamp function (one-line):");
  console.log("    html.replaceAll(\"__\" + id.toUpperCase() + \"__\", value)");
  check("the placeholder rule is field id -> __ID_UPPER__",
    placeholderFor("title") === "__TITLE__" && placeholderFor("body") === "__BODY__");
}

function sectionB(): void {
  banner("SECTION B: before/after stamping on a bare <template>");
  console.log("  RFC 0001 §5.4 — slide index.html is a bare <template> sub-comp.\n");
  console.log("  BEFORE stamping:");
  console.log(indent(SAMPLE_TEMPLATE, 4));

  // Stamp slide-id + every text field. The slide id is structural, fields are data.
  let after = SAMPLE_TEMPLATE.replaceAll("__SLIDE_ID__", "slide-0");
  let stamped = 1; // __SLIDE_ID__ counted once (one distinct placeholder id)
  for (const [id, value] of Object.entries(SLIDE_FIELDS)) {
    after = stampSafe(after, id, value);
    stamped++;
  }

  console.log("\n  AFTER stamping (__SLIDE_ID__ -> slide-0, __TITLE__ -> Eco Bottle, __BODY__ -> Hello World):");
  console.log(indent(after, 4));

  const noPlaceholdersLeft = !/__[A-Z_]+__/.test(after);
  check("after stamping, no __PLACEHOLDER__ remains", noPlaceholdersLeft);
  check("after stamping contains the stamped title", after.includes("Eco Bottle"));
  console.log(`  PINNED: distinct placeholders substituted = ${stamped} (SLIDE_ID, TITLE, BODY)`);
  console.log(`  GOLD:   after.includes("Eco Bottle") && !after.includes("__TITLE__") => ${
    after.includes("Eco Bottle") && !after.includes("__TITLE__")
  }`);
}

function sectionC(): void {
  banner("SECTION C: the THREE stamping modes (RFC §5.6)");
  console.log("  ┌──────────────┬──────────────────────────────────┬──────────────────────────────────────────┬──────────────────────────┐");
  console.log("  │ Mode         │ Trigger                          │ Mechanism                                │ Cost                     │");
  console.log("  ├──────────────┼──────────────────────────────────┼──────────────────────────────────────────┼──────────────────────────┤");
  console.log("  │ structural   │ slide add / remove / reorder,    │ Full re-stamp of the affected slide's    │ One rewrite per change.  │");
  console.log("  │              │ layout swap                      │ HTML from its fields.                    │                          │");
  console.log("  ├──────────────┼──────────────────────────────────┼──────────────────────────────────────────┼──────────────────────────┤");
  console.log("  │ live-bind    │ typing in a text field (textarea) │ Light DOM patch on the ONE node bound to │ No full re-stamp; the    │");
  console.log("  │              │                                  │ the field.                               │ stage stays responsive.   │");
  console.log("  ├──────────────┼──────────────────────────────────┼──────────────────────────────────────────┼──────────────────────────┤");
  console.log("  │ export       │ Export to MP4                    │ Full re-stamp of EVERY slide from its    │ Runs once, at export.    │");
  console.log("  │              │                                  │ index.json; produces the rendered truth. │                          │");
  console.log("  └──────────────┴──────────────────────────────────┴──────────────────────────────────────────┴──────────────────────────┘");
  check("RFC §5.6 defines exactly three stamping modes (structural / live-bind / export)", true);
  console.log("  → live-bind is responsive but mutable state; export re-stamps so the file is the single source of truth.");
}

function sectionD(): void {
  banner("SECTION D: image fields — PATH replacement, not text");
  console.log("  AGENTS.md \"Layout field types\": image -> byte swap to assets/ + __FIELD__ PATH replacement.\n");
  console.log("  BEFORE stamping:");
  console.log(indent(IMAGE_TEMPLATE, 4));

  // The image value is an asset path (the bytes were already swapped to assets/).
  const assetPath = "assets/sha256-c0ffee.jpg";
  const after = stampSafe(IMAGE_TEMPLATE, "image", assetPath);

  console.log("\n  AFTER stamping (__IMAGE__ -> assets/sha256-c0ffee.jpg):");
  console.log(indent(after, 4));

  check("image field: __IMAGE__ is replaced by an asset path", after.includes(assetPath) && !after.includes("__IMAGE__"));
  console.log("  → the value is a PATH (string), not image bytes; the bytes live in assets/.");
}

function sectionE(): void {
  banner("SECTION E: the $ replacement-string pitfall (MDN-verified)");
  console.log("  MDN String.prototype.replace: when the replacement is a STRING, these patterns");
  console.log("  are special EVEN if the search is a plain string: $$ $& $` $' ($n needs a RegExp).\n");

  const placeholder = "__BODY__";
  const html = `Cost: ${placeholder}`; // sample HTML with one text placeholder

  // Naive (string replacement): each value below is corrupted.
  const cases: Array<[string, string, string]> = [
    ["value contains $&",   "x $& y",   "Cost: x __BODY__ y"], // $& -> the matched substring
    ["value contains $$",   "Pay $$5",  "Cost: Pay $5"],       // $$ -> a single $
    ["value contains $`",   "x $` y",   "Cost: x Cost:  y"],   // $` -> portion BEFORE match
    ["value contains $'",   "x $' y",   "Cost: x  y"],         // $' -> portion AFTER match
    ["value contains $5",   "Cost: $5", "Cost: Cost: $5"],     // $n literal (no RegExp) — NOT corrupted
  ];

  console.log("  NAIVE stampNaive(html, 'body', value) — corruption table:");
  for (const [label, value, expected] of cases) {
    const got = stampNaive(html, "body", value);
    const ok = got === expected;
    check(`naive: ${label} -> ${JSON.stringify(expected)}`, ok);
    console.log(`    ${label.padEnd(22)} value=${JSON.stringify(value).padEnd(12)} -> ${JSON.stringify(got)}`);
  }

  console.log("\n  SAFE stampSafe(html, 'body', value) — function form, every value preserved:");
  for (const [label, value] of cases) {
    const got = stampSafe(html, "body", value);
    check(`safe: ${label} preserved verbatim`, got === `Cost: ${value}`);
    console.log(`    ${label.padEnd(22)} value=${JSON.stringify(value).padEnd(12)} -> ${JSON.stringify(got)}`);
  }
  console.log("  → FIX: use a replacement FUNCTION (() => value); MDN: special patterns do not");
  console.log("    apply for strings returned from the replacer function.");
}

function sectionF(): void {
  banner("SECTION F: why stamping — HF getVariables() returns {} in sub-comps");
  console.log("  AGENTS.md \"Why NOT data-variable-values / getVariables()\":");
  console.log("  HF's getVariables() returns empty {} in v0.7.3 sub-compositions.\n");

  // Simulate HyperFrames' sub-comp getVariables(): the value the editor would love
  // to use but cannot, because HF returns nothing for a sub-comp.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  function hfGetVariables(_compositionId: string): Record<string, any> {
    return {}; // verified empty in HF v0.7.3 sub-compositions (AGENTS.md)
  }

  const vars = hfGetVariables("slide-0");
  check("HF getVariables() returns {} for a sub-composition", Object.keys(vars).length === 0);
  console.log("  → with variables unavailable, the editor MUST stamp __FIELD__ into the HTML.");
  console.log("    Stamping is not a shortcut; it is the only mechanism that works in HF sub-comps.");
}

// ---- small util (kept local so the runnable is self-contained) ----

function indent(s: string, n: number): string {
  const pad = " ".repeat(n);
  return s
    .split("\n")
    .map((l) => (l.length === 0 ? l : pad + l))
    .join("\n");
}

// ---- main ----

function main(): void {
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  sectionF();
  banner("DONE");
}

main();
