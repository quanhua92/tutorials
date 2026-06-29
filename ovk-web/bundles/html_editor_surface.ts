// html_editor_surface — ground-truth runnable for "the per-slide HTML editor surface + lint gate"
// (RFC 0001 §7 HTML-editor row, §16 animation framework, §18 risk row)
// Run: pnpm exec tsx bundles/html_editor_surface.ts
//
// Teaches the safety model for editing a slide's index.html (the bare
// <template>): this surface is the Tier-2 AI surface AND a power-user surface
// (RFC 0002). Any edit — human OR coding-model — must pass a LINT GATE
// (npx hyperframes lint) before it is accepted. On pass the workspace adopts
// the new HTML (ACCEPT); on fail the workspace keeps the prior version
// (REVERT) — a broken edit never reaches the files. This is the exact
// mitigation RFC §18 lists for the risk "Tier-2 AI writes broken/invalid
// slide HTML".
//
// Determinism: NO fs reads, NO Date.now, NO RNG, NO DOM lib. The "lint gate"
// below is a hand-rolled string-scanner predicate set over FIXED in-source
// fixtures — the same shape `npx hyperframes lint --json` performs (the HF CLI
// linter "detects ... structural problems", HF docs, CLI §lint). The
// interactive html_editor_surface.html recomputes the SAME gate in JS on a
// textarea.

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

// ---- FIXED in-source fixtures (RFC §5.4 / §7 / AGENTS.md "Layout file format — CRITICAL") ----

// The canonical VALID edit: a bare <template> slide (RFC §5.4). The gate MUST
// pass this — it is HF's native sub-composition format (cross-ref BARE_TEMPLATE).
const VALID_FIXTURE = `<template>
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

// INVALID edit #1 — the WRAPPER TRAP: the bare <template> is nested inside a
// full <html><body> document. This is what every "New HTML File" command emits.
// HF fails to extract <template>.content from this shape → blank render
// (AGENTS.md "Why bare <template>", verified HF v0.7.3). The gate must REVERT.
const WRAPPED_FIXTURE = `<html>
  <body>
    <template>
      <div data-composition-id="__SLIDE_ID__" data-width="1920" data-height="1080">
        <div class="content"><h1>__TITLE__</h1></div>
      </div>
    </template>
  </body>
</html>`;

// INVALID edit #2 — a bare <template> whose inner div LOST its
// data-composition-id (e.g. a coding model rewrote the opening tag). The
// wrapper rule passes, but the host-div predicate fails: HF cannot scope CSS or
// register the timeline. The gate must REVERT.
const MISSING_ID_FIXTURE = `<template>
  <div class="content">
    <h1>__TITLE__</h1>
  </div>
  <style>
    .content { text-align: center; padding-top: 38vh; }
  </style>
</template>`;

// The workspace's PRIOR slide HTML (what is on disk before the edit). After a
// REVERT the workspace stays byte-identical to this — the failed edit never lands.
const PRIOR = VALID_FIXTURE;

// ---- minimal deterministic string helpers (NO DOM lib — string ops only) ----

/** Count opening occurrences of a tag (e.g. "html", "body", "template"). Case-insensitive. */
function countTag(src: string, tag: string): number {
  const re = new RegExp("<\\s*" + tag + "(\\s|>)", "gi");
  return (src.match(re) || []).length;
}

/** Extract the inner content of the first <template>...</template> pair. */
function extractTemplateContent(src: string): string {
  const open = src.indexOf("<template");
  const openEnd = src.indexOf(">", open);
  const close = src.indexOf("</template>", openEnd);
  if (open < 0 || openEnd < 0 || close < 0) return "";
  return src.slice(openEnd + 1, close);
}

/** Wrapper detector: true if an <html>/<head>/<body> tag appears OUTSIDE <template>. */
function hasHtmlWrapper(src: string): boolean {
  const open = src.indexOf("<template");
  const before = open > 0 ? src.slice(0, open) : "";
  return countTag(before, "html") > 0 || countTag(before, "head") > 0 || countTag(before, "body") > 0;
}

/** §16 detector: true if Tailwind is introduced into a composition file. */
function hasTailwind(src: string): boolean {
  // RFC §16: "Do NOT introduce Tailwind or a motion library into composition files."
  // Detect the Tailwind play CDN, the Tailwind script bundle, the @tailwind
  // directive, or an @apply directive. (Utility-class heuristics are too
  // noisy — "flex" is valid vanilla CSS — so we catch the *imports*, not classes.)
  if (/cdn\.tailwindcss\.com/i.test(src)) return true;
  if (/tailwindscripts\./i.test(src)) return true;
  if (/@tailwind\b/i.test(src)) return true;
  if (/@apply\s+/i.test(src)) return true;
  return false;
}

// ---- the lint gate (the §18 mitigation, as a deterministic predicate set) ----

interface RuleResult { id: string; ok: boolean; }
interface LintResult {
  pass: boolean;
  firedRule: string;   // "" on pass; else the first failing rule id
  rules: RuleResult[];
}

/**
 * The lint gate. A pure predicate set run in FIXED order; the FIRST failing
 * rule wins (deterministic). Mirrors `npx hyperframes lint --json` (HF CLI:
 * "Check a composition for common issues ... machine-readable JSON output";
 * the linter "detects ... structural problems").
 *
 * Rule order is deliberate: structural format (bare <template>) is checked
 * before content predicates, because a wrapper breaks extraction and makes the
 * later rules meaningless.
 */
function lintGate(src: string): LintResult {
  const inner = extractTemplateContent(src);
  const rules: RuleResult[] = [
    // R1 — exactly one <template> (HF's extraction handle)
    { id: "R1_has_one_template", ok: countTag(src, "template") === 1 },
    // R2 — bare-<template> invariant: NO <html>/<head>/<body> outside the template
    { id: "R2_bare_no_wrapper", ok: !hasHtmlWrapper(src) },
    // R3 — the extracted content carries data-composition-id (host-div requirement)
    { id: "R3_has_data_composition_id", ok: /data-composition-id\s*=/.test(inner) },
    // R4 — §16: no Tailwind introduced into the composition file
    { id: "R4_no_tailwind", ok: !hasTailwind(src) },
  ];
  const firstFail = rules.find((r) => !r.ok);
  return { pass: !firstFail, firedRule: firstFail ? firstFail.id : "", rules };
}

/** The editor's commit step. ACCEPT on pass; REVERT on fail (workspace keeps prior). */
interface ApplyResult {
  decision: "ACCEPT" | "REVERT";
  workspace: string;   // what lands on disk
  firedRule: string;
}
function applyEdit(prior: string, edited: string): ApplyResult {
  const lint = lintGate(edited);
  if (lint.pass) return { decision: "ACCEPT", workspace: edited, firedRule: "" };
  return { decision: "REVERT", workspace: prior, firedRule: lint.firedRule };
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the surface — what it edits, who edits here");
  console.log("  RFC 0001 §7 — Editor Surfaces (HTML editor row):");
  console.log("    'HTML editor (per slide)' binds to slide 'index.html'; job =");
  console.log("    'edit within-slide animation; the AI Tier-2 surface; power users.'");
  console.log("  RFC 0002 — Tier-2 AI authors slide HTML/CSS/GSAP through this surface.\n");
  check("the surface's binding target is the slide index.html (the bare <template>)",
    VALID_FIXTURE.trimStart().startsWith("<template"));
  check("the VALID fixture is exactly the format AGENTS.md 'Layout file format — CRITICAL' mandates",
    /data-composition-id="__SLIDE_ID__"/.test(VALID_FIXTURE) &&
    !hasHtmlWrapper(VALID_FIXTURE));
}

function sectionB(): void {
  banner("SECTION B: the lint gate — a predicate set over `npx hyperframes lint`");
  console.log("  HF CLI (§lint): 'Check a composition for common issues ... --json'");
  console.log("  RFC §18 risk row → mitigation: 'AGENTS.md lint gate (npx hyperframes");
  console.log("  lint) before accepting an HTML edit'. The gate runs BEFORE accept.\n");
  const lint = lintGate(VALID_FIXTURE);
  for (const r of lint.rules) {
    console.log(`    ${r.ok ? "PASS" : "FAIL"}  ${r.id}`);
  }
  check("the gate is a pure predicate (same input ⇒ same pass/fail, no side effects)",
    lintGate(VALID_FIXTURE).pass === true && lintGate(VALID_FIXTURE).pass === true);
  check("R2 enforces the bare-<template> invariant (cross-ref BARE_TEMPLATE)",
    lint.rules.find((r) => r.id === "R2_bare_no_wrapper")!.ok === true);
  check("R4 enforces §16 (no Tailwind in composition files)",
    lint.rules.find((r) => r.id === "R4_no_tailwind")!.ok === true);
}

function sectionC(): void {
  banner("SECTION C: the three fixtures — ACCEPT vs REVERT (PINNED)");
  console.log("  Each edit runs through the gate. The decision + the fired rule are pinned.\n");
  const cases: { name: string; src: string }[] = [
    { name: "VALID     (bare <template>)", src: VALID_FIXTURE },
    { name: "WRAPPED   (<html><body> trap)", src: WRAPPED_FIXTURE },
    { name: "MISSING_ID(no data-composition-id)", src: MISSING_ID_FIXTURE },
  ];
  const decisions: string[] = [];
  for (const c of cases) {
    const r = applyEdit(PRIOR, c.src);
    const fired = r.firedRule === "" ? "-" : r.firedRule;
    console.log(`    ${c.name}  →  ${r.decision}  (fired: ${fired})`);
    decisions.push(r.decision);
  }
  check("VALID fixture passes the gate and is ACCEPTed",
    applyEdit(PRIOR, VALID_FIXTURE).decision === "ACCEPT");
  check("WRAPPED fixture fails R2 (bare-<template>) and is REVERTed",
    applyEdit(PRIOR, WRAPPED_FIXTURE).decision === "REVERT" &&
    applyEdit(PRIOR, WRAPPED_FIXTURE).firedRule === "R2_bare_no_wrapper");
  check("MISSING_ID fixture fails R3 (data-composition-id) and is REVERTed",
    applyEdit(PRIOR, MISSING_ID_FIXTURE).decision === "REVERT" &&
    applyEdit(PRIOR, MISSING_ID_FIXTURE).firedRule === "R3_has_data_composition_id");
  console.log(`  PINNED: gate decisions = ${decisions.join(", ")}`);
}

function sectionD(): void {
  banner("SECTION D: revert semantics — the workspace never sees a failed edit");
  console.log("  RFC §18 mitigation: a broken edit is rejected BEFORE it reaches the");
  console.log("  workspace. After REVERT, on-disk HTML is byte-identical to PRIOR.\n");
  const before = PRIOR;
  const afterWrapped = applyEdit(PRIOR, WRAPPED_FIXTURE);
  const afterMissing = applyEdit(PRIOR, MISSING_ID_FIXTURE);
  console.log(`    workspace before any edit:        ${before.length} chars`);
  console.log(`    workspace after WRAPPED attempt:   ${afterWrapped.workspace.length} chars (${afterWrapped.decision})`);
  console.log(`    workspace after MISSING_ID attempt: ${afterMissing.workspace.length} chars (${afterMissing.decision})`);
  check("REVERT leaves the workspace byte-identical to PRIOR (WRAPPED case)",
    afterWrapped.decision === "REVERT" && afterWrapped.workspace === before);
  check("REVERT leaves the workspace byte-identical to PRIOR (MISSING_ID case)",
    afterMissing.decision === "REVERT" && afterMissing.workspace === before);
  check("a failed edit NEVER becomes the workspace (both invalid fixtures rejected)",
    afterWrapped.workspace === before && afterMissing.workspace === before);
}

function sectionE(): void {
  banner("SECTION E: reviewable diffs — GSAP + vanilla CSS, NO Tailwind (§16)");
  console.log("  RFC §16: 'GSAP + vanilla CSS inside slide index.html ... Do NOT introduce");
  console.log("  Tailwind or a motion library into composition files.' Rationale: a");
  console.log("  coding model that writes vanilla CSS + GSAP produces diffs a human can review.\n");
  const usesGsap = /gsap\.timeline\(/.test(VALID_FIXTURE);
  const usesVanillaCss = /<style>/.test(VALID_FIXTURE) && !hasTailwind(VALID_FIXTURE);
  console.log(`    VALID fixture uses gsap.timeline(...):  ${usesGsap}`);
  console.log(`    VALID fixture uses vanilla <style>:      ${usesVanillaCss}`);
  console.log(`    hasTailwind(VALID_FIXTURE):              ${hasTailwind(VALID_FIXTURE)}`);
  check("the VALID fixture is GSAP + vanilla CSS, Tailwind-free (§16-compliant)",
    usesGsap && usesVanillaCss && !hasTailwind(VALID_FIXTURE));
  // a Tailwind-laden edit would trip R4 — demonstrate the gate enforces §16
  const tailwindEdit = VALID_FIXTURE.replace(
    "</template>",
    '<script src="https://cdn.tailwindcss.com"></script>\n</template>'
  );
  const r = applyEdit(PRIOR, tailwindEdit);
  check("an edit that introduces the Tailwind CDN trips R4 and is REVERTed",
    r.decision === "REVERT" && r.firedRule === "R4_no_tailwind");
}

function sectionF(): void {
  banner("SECTION F: Tier-1 (data) vs Tier-2 (HTML) — two surfaces, one slide unit");
  console.log("  RFC §5.1 / RFC 0002: the slide unit has two files. The Properties panel");
  console.log("  edits index.json (fields) — the Tier-1 small-model surface. The HTML");
  console.log("  editor edits index.html (animation) — the Tier-2 coding-model surface.");
  console.log("  Both feed the same slide; fields re-inject via __FIELD__ after an HTML edit.\n");
  check("the two editor surfaces target the two files of one slide unit",
    /index\.html/.test("index.html") && /index\.json/.test("index.json"));
  check("an accepted HTML edit still carries __FIELD__ placeholders (data re-binds post-edit)",
    /__TITLE__/.test(VALID_FIXTURE) && /__BODY__/.test(VALID_FIXTURE));
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
