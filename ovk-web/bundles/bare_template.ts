// bare_template — ground-truth runnable for "the slide index.html is a bare <template>" (RFC 0001 §5.4–5.5)
// Run: pnpm exec tsx bundles/bare_template.ts
//
// Teaches the single most load-bearing rule about slide HTML in OpenVideoKit:
// a slide's index.html is a BARE <template> element — NO <html>/<head>/<body>
// wrapper, NO data-composition-variables. HyperFrames' runtime extracts
// <template>.content and mounts it; an <html> wrapper breaks that extraction
// and the sub-comp renders BLANK (verified HF v0.7.3 — AGENTS.md).
//
// Determinism: NO fs reads, NO Date.now, NO RNG, NO DOM lib. The "extraction"
// below is a hand-rolled string scanner over a FIXED in-source template — the
// same shape HF's runtime performs on <template>.content (MDN: the <template>
// element's content is an inert DocumentFragment accessed via .content, not
// rendered by default). The interactive bare_template.html uses a REAL browser
// DOMParser to do the same extraction.

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

// ---- FIXED in-source fixtures (the ground truth, RFC 0001 §5.4 / AGENTS.md) ----

// The canonical bare <template> slide. This is RFC §5.4's example — the format
// the editor's per-slide HTML surface edits and export copies VERBATIM into
// compositions/slide-N.html (RFC §10, zero translation).
const BARE_TEMPLATE = `<template>
  <div data-composition-id="__SLIDE_ID__" data-width="1920" data-height="1080">
    <div class="content">
      <h1>__TITLE__</h1>
      <p>__BODY__</p>
    </div>
    <style>
      [data-composition-id="__SLIDE_ID__"] { background: #0a0a14; }
      [data-composition-id="__SLIDE_ID__"] .content { text-align: center; padding-top: 38vh; }
    </style>
    <script>
      var tl = gsap.timeline({ paused: true });
      tl.from('[data-composition-id="__SLIDE_ID__"] .content > *', { opacity: 0, y: 40, duration: 0.4, stagger: 0.1 });
      window.__timelines['__SLIDE_ID__'] = tl;
    </script>
  </div>
</template>`;

// The WRAPPER TRAP: the same content, but the <template> is nested inside a
// full <html><body> document. HF's runtime fails to extract <template>.content
// from this shape → the sub-comp renders BLANK (verified HF v0.7.3,
// AGENTS.md "Why bare <template>"). This is the real authoring mistake an HTML
// editor must refuse to emit / must lint against.
const WRAPPED_TEMPLATE = `<html>
  <body>
    <template>
      <div data-composition-id="__SLIDE_ID__" data-width="1920" data-height="1080">
        <div class="content"><h1>__TITLE__</h1></div>
      </div>
    </template>
  </body>
</html>`;

// ---- minimal deterministic extractors (NO DOM lib — string ops only) ----

/** Extract the inner content of the first <template>...</template> pair. */
function extractTemplateContent(src: string): string {
  const open = src.indexOf("<template");
  const openEnd = src.indexOf(">", open);
  const close = src.indexOf("</template>", openEnd);
  if (open < 0 || openEnd < 0 || close < 0) return "";
  return src.slice(openEnd + 1, close);
}

/** Extract the (first) value of an attribute like data-composition-id="VALUE". */
function extractAttribute(inner: string, attr: string): string {
  const re = new RegExp(attr + "\\s*=\\s*\"([^\"]*)\"");
  const m = inner.match(re);
  return m ? m[1] : "";
}

/** Count opening occurrences of a tag (e.g. "html", "body"). Case-insensitive. */
function countTag(src: string, tag: string): number {
  const re = new RegExp("<\\s*" + tag + "(\\s|>)", "gi");
  return (src.match(re) || []).length;
}

/** Pull every __TOKEN__ placeholder from a string, de-duplicated, in first-seen order. */
function extractPlaceholders(src: string): string[] {
  const re = /__[A-Z0-9_]+__/g;
  const seen: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(src)) !== null) {
    if (!seen.includes(m[0])) seen.push(m[0]);
  }
  return seen;
}

/** Wrapper detector: true if an <html> or <body> tag appears OUTSIDE <template>. */
function hasHtmlWrapper(src: string): boolean {
  const open = src.indexOf("<template");
  const before = open > 0 ? src.slice(0, open) : "";
  return countTag(before, "html") > 0 || countTag(before, "body") > 0;
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: anatomy of a bare <template> slide");
  console.log("  RFC 0001 §5.4 / AGENTS.md 'Layout file format — CRITICAL'");
  console.log("  A slide index.html is a BARE <template> — no <html>/<head>/<body> wrapper.\n");
  for (const line of BARE_TEMPLATE.split("\n")) console.log("    " + line);
  const inner = extractTemplateContent(BARE_TEMPLATE);
  check("source begins with <template> (bare, no <html> before it)",
    BARE_TEMPLATE.trimStart().startsWith("<template"));
  check("extracted content carries data-composition-id=\"__SLIDE_ID__\"",
    extractAttribute(inner, "data-composition-id") === "__SLIDE_ID__");
  check("extracted content carries data-width=\"1920\" data-height=\"1080\"",
    extractAttribute(inner, "data-width") === "1920" &&
    extractAttribute(inner, "data-height") === "1080");
}

function sectionB(): void {
  banner("SECTION B: extraction — what HF mounts (template.content)");
  console.log("  HF docs (Compositions): 'extracts the <template> content, mounts it,");
  console.log("  executes scripts, and registers the timeline.'");
  console.log("  MDN: <template>.content is an inert DocumentFragment, not rendered by default.\n");
  const inner = extractTemplateContent(BARE_TEMPLATE);
  const id = extractAttribute(inner, "data-composition-id");
  console.log(`  extracted data-composition-id = "${id}"`);
  console.log(`  extracted content length     = ${inner.length} chars`);
  check("extracted composition id is the pre-stamp literal __SLIDE_ID__",
    id === "__SLIDE_ID__");
  check("bare source has ZERO <html> tags (the wrapper is absent)",
    countTag(BARE_TEMPLATE, "html") === 0);
  check("bare source has ZERO <body> tags", countTag(BARE_TEMPLATE, "body") === 0);
  console.log(`  PINNED: <html> count = ${countTag(BARE_TEMPLATE, "html")}, ` +
    `<body> count = ${countTag(BARE_TEMPLATE, "body")}, id = "${id}"`);
}

function sectionC(): void {
  banner("SECTION C: the wrapper trap — <html>/<body> around <template> → BLANK");
  console.log("  AGENTS.md: 'An <html> wrapper around <template> causes HF to NOT extract the");
  console.log("  content — the sub-comp renders blank. Verified in HF v0.7.3.'\n");
  const bareHtml = countTag(BARE_TEMPLATE, "html");
  const bareBody = countTag(BARE_TEMPLATE, "body");
  const wrappedHtml = countTag(WRAPPED_TEMPLATE, "html");
  const wrappedBody = countTag(WRAPPED_TEMPLATE, "body");
  console.log(`  bare    source: <html> x${bareHtml}, <body> x${bareBody} → mounts OK`);
  console.log(`  wrapped source: <html> x${wrappedHtml}, <body> x${wrappedBody} → BLANK render trap`);
  check("the wrapped fixture carries a detected <html>/<body> wrapper",
    wrappedHtml > 0 && wrappedBody > 0);
  check("hasHtmlWrapper flags WRAPPED but passes BARE",
    hasHtmlWrapper(WRAPPED_TEMPLATE) === true && hasHtmlWrapper(BARE_TEMPLATE) === false);
  console.log("  → detection rule: an <html>/<body> tag appears OUTSIDE the <template>;");
  console.log("    a lint gate (npx hyperframes lint) should reject this before export.");
}

function sectionD(): void {
  banner("SECTION D: the placeholder set (pre-stamp) — cross-ref DATA_BINDING");
  console.log("  Placeholders are stamped with data BEFORE mount (RFC §5.6).");
  console.log("  Each field id uppercases: field 'title' → __TITLE__.\n");
  const phs = extractPlaceholders(BARE_TEMPLATE);
  for (const p of phs) console.log(`    ${p}`);
  check("__SLIDE_ID__ present (stamped to slide-0, slide-1, ...)",
    phs.includes("__SLIDE_ID__"));
  check("__TITLE__ and __BODY__ present (field placeholders)",
    phs.includes("__TITLE__") && phs.includes("__BODY__"));
  console.log(`  PINNED: ${phs.length} distinct placeholders (all pre-stamp literals).`);
}

function sectionE(): void {
  banner("SECTION E: CSS scoping via [data-composition-id=...] + padding-top:XXvh");
  console.log("  AGENTS.md 'Why NOT flex/absolute centering': HF's sub-comp mounting context");
  console.log("  doesn't reliably support display:flex/align-items or position:absolute +");
  console.log("  transform. The HF pattern is text-align:center + padding-top:XXvh.\n");
  const inner = extractTemplateContent(BARE_TEMPLATE);
  const usesAttrScope = /\[data-composition-id="__SLIDE_ID__"\]/.test(inner);
  const usesVhPad = /padding-top:\s*\d+vh/.test(inner);
  const usesFlex = /display\s*:\s*flex/.test(inner);
  const usesAbsTransform = /position\s*:\s*absolute/.test(inner) &&
    /transform\s*:\s*translate/.test(inner);
  console.log(`  attribute-scoped CSS ([data-composition-id="__SLIDE_ID__"]): ${usesAttrScope}`);
  console.log(`  vertical centering via padding-top:XXvh:                   ${usesVhPad}`);
  console.log(`  display:flex (BANNED by AGENTS.md):                        ${usesFlex}`);
  console.log(`  position:absolute + transform:translate (BANNED):          ${usesAbsTransform}`);
  check("CSS scoped by attribute selector AND centered via padding-top:vh",
    usesAttrScope && usesVhPad);
  check("does NOT use the banned flex / absolute-transform centering",
    !usesFlex && !usesAbsTransform);
}

function sectionF(): void {
  banner("SECTION F: within-slide GSAP timeline → window.__timelines['__SLIDE_ID__']");
  console.log("  The slide builds ITS OWN timeline (within-slide animation) and registers it");
  console.log("  into the global registry under the slide's id. Contrast: BETWEEN-slide");
  console.log("  transitions live in the ROOT index.html (cross-ref UNIT_MODEL Section C).\n");
  const inner = extractTemplateContent(BARE_TEMPLATE);
  const buildsTimeline = /gsap\.timeline\(/.test(inner);
  const registersTimeline = /window\.__timelines\['__SLIDE_ID__'\]/.test(inner);
  console.log(`  builds gsap.timeline(...):                     ${buildsTimeline}`);
  console.log(`  registers window.__timelines['__SLIDE_ID__']:  ${registersTimeline}`);
  check("slide builds a gsap.timeline and registers it under __SLIDE_ID__",
    buildsTimeline && registersTimeline);
  check("registration key is the (stamped) data-composition-id value",
    extractAttribute(inner, "data-composition-id") === "__SLIDE_ID__");
}

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
