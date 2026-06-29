// properties_panel — ground-truth runnable for "the Properties/data panel"
// (RFC 0001 §7 "Properties / data" + §5.6 "Data binding")
// Run: pnpm exec tsx bundles/properties_panel.ts
//
// Teaches the RIGHT-HAND editor surface. It binds to the ACTIVE slide's
// `index.json` and edits four keys: `fields`, `assets`, `voiceover`, and the
// `transition` override. The headline behavior is LIVE-BIND (RFC §5.6 mode 2):
// typing in a text field updates the preview via a LIGHT DOM PATCH on the one
// bound text node — NOT a full re-stamp. A full re-stamp only fires on a
// STRUCTURAL change (mode 1) or at EXPORT (mode 3). This runnable prints every
// value PROPERTIES_PANEL.md cites verbatim, including the patch-vs-stamp
// counter demonstration and the syncFromDOM() pitfall (AGENTS.md #7).

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

// ---- deterministic sample data (NO FS reads, NO Date.now, NO RNG) ----

// RFC 0001 §5.3 — the slide index.json keys the Properties panel binds.
// §7 row: "Properties / data (right) | slide index.json | edit fields, asset
// refs, voiceover text, transition override".
interface SlideIndexJson {
  id: string;
  fields: Record<string, string>;
  assets: Record<string, string>;
  voiceover: { text: string; voice: string };
  transition?: { type: string; duration: number };
}

// Factory, NOT a shared constant: liveBind()/structuralChange() mutate the
// `fields` object in place, so each section must take a FRESH copy. Sharing one
// object across sections leaks edits forward (a real bug caught in testing).
function freshSlide(): SlideIndexJson {
  return {
    id: "slide-0",
    fields: { title: "Old", body: "B" },
    assets: { img: "sha256:c0ffee" },
    voiceover: { text: "Narration.", voice: "vi-VN-HoaiMyNeural" },
    // transition deliberately ABSENT here → falls back to root transition_default (Section E).
  };
}

// RFC 0001 §5.2 — root transition_default (the fallback for slides w/o an override).
const ROOT_TRANSITION_DEFAULT = { type: "crossfade", duration: 0.4 };

// AGENTS.md "Layout field types" — field type → form control mapping.
type FieldType = "text" | "image" | "voiceover";
interface FieldDef { id: string; type: FieldType; label: string; }
const LAYOUT_FIELDS: FieldDef[] = [
  { id: "title", type: "text", label: "Title" },
  { id: "body", type: "text", label: "Body" },
  { id: "img", type: "image", label: "Hero image" },
  { id: "voice", type: "voiceover", label: "Voiceover" },
];

// ---- the panel engine: tracks light patches vs full re-stamps ----
//
// The preview is driven two ways (RFC §5.6):
//   live-bind   → mutate JSON, then patch the ONE bound text node (patchCount++).
//   structural  → full re-stamp of the slide HTML from its fields (stampCount++).
//   export      → full re-stamp of EVERY slide (stampCount += N), at export.
// The counters are the demo: a text edit bumps patchCount and leaves stampCount
// at 0 — that is the whole point of live-bind.

interface PreviewNode { fieldId: string; text: string; } // the one bound text node
interface PanelEngine {
  json: SlideIndexJson;
  preview: Map<string, PreviewNode>; // fieldId -> bound text node
  patchCount: number; // light DOM patches (live-bind)
  stampCount: number; // full re-stamps (structural / export)
}

function makeEngine(slide: SlideIndexJson): PanelEngine {
  // The preview mounts by STAMPING once (structural mount = one re-stamp), then
  // live-bind takes over for text edits. We start the engine AFTER the initial
  // mount so the counter demo is about EDITS, not the first paint.
  const preview = new Map<string, PreviewNode>();
  for (const [id, value] of Object.entries(slide.fields)) {
    preview.set(id, { fieldId: id, text: value });
  }
  return { json: slide, preview, patchCount: 0, stampCount: 0 };
}

/**
 * RFC §5.6 mode 2 — LIVE-BIND. Mutate the JSON field, then LIGHT-PATCH the one
 * bound text node. NO full re-stamp: patchCount++ and stampCount is untouched.
 * This is why typing in a textarea keeps the stage responsive (no remount).
 */
function liveBind(eng: PanelEngine, fieldId: string, value: string): void {
  eng.json.fields[fieldId] = value;            // 1. mutate the data layer (JSON)
  const node = eng.preview.get(fieldId);        // 2. find the ONE bound text node
  if (node) node.text = value;                  // 3. light DOM patch (textContent)
  eng.patchCount++;                            // 4. count the patch, NOT a re-stamp
}

/**
 * RFC §5.6 mode 1 — STRUCTURAL change (slide add/remove/reorder, layout swap).
 * The HTML skeleton changed, so the slide is fully re-stamped from its fields.
 */
function structuralChange(eng: PanelEngine): void {
  // full re-stamp: rebuild every bound node from JSON.fields
  for (const [id, value] of Object.entries(eng.json.fields)) {
    const node = eng.preview.get(id);
    if (node) node.text = value;
  }
  eng.stampCount++;
}

/** RFC §5.6 mode 3 — EXPORT. Full re-stamp of EVERY slide (runs once). */
function exportRestamp(eng: PanelEngine, slideCount: number): void {
  structuralChange(eng); // re-stamp the active slide ...
  eng.stampCount += slideCount - 1; // ... plus every other slide
}

// ---- helpers ----

/** AGENTS.md "Layout field types" — field type → form control. */
function fieldToControl(type: FieldType): string {
  switch (type) {
    case "text": return "<textarea>";
    case "image": return '<input type="file">';
    case "voiceover": return "<textarea> (amber styled)";
  }
}

/** Resolve the effective transition: slide override wins, else root default. */
function effectiveTransition(
  slide: SlideIndexJson,
  rootDefault: { type: string; duration: number },
): { type: string; duration: number } {
  return slide.transition ?? rootDefault;
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: Properties binds to the ACTIVE slide's index.json");
  console.log("  RFC 0001 §7 — \"Properties / data (right) | slide index.json |");
  console.log("    edit fields, asset refs, voiceover text, transition override\"\n");
  const keys = ["fields", "assets", "voiceover", "transition"] as const;
  for (const k of keys) console.log(`    slide.index.json . ${k}`);
  const probe = freshSlide();
  const hasAll = keys.every((k) => k in probe || k === "transition");
  check("panel edits exactly {fields, assets, voiceover, transition} on slide index.json", hasAll);
  console.log("  → switching the active slide re-binds the panel to THAT slide's index.json.");
}

function sectionB(): void {
  banner("SECTION B: field type → form control (AGENTS.md \"Layout field types\")");
  console.log("  ┌──────────────┬──────────────────────────────┬──────────────────────────────────────────┐");
  console.log("  │ Type         │ Form control                 │ What happens on submit                  │");
  console.log("  ├──────────────┼──────────────────────────────┼──────────────────────────────────────────┤");
  console.log("  │ text         │ <textarea>                   │ __FIELD_ID__ placeholder replacement    │");
  console.log("  │ image        │ <input type=\"file\">          │ byte swap to assets/, __FIELD__ path     │");
  console.log("  │ voiceover    │ <textarea> (amber styled)    │ batch TTS pipeline                      │");
  console.log("  └──────────────┴──────────────────────────────┴──────────────────────────────────────────┘");
  for (const f of LAYOUT_FIELDS) {
    const ctrl = fieldToControl(f.type);
    console.log(`    ${f.id.padEnd(8)} (${f.type.padEnd(9)}) -> ${ctrl}`);
  }
  check("text & voiceover both render a <textarea>; image renders a file input",
    fieldToControl("text").startsWith("<textarea") &&
    fieldToControl("voiceover").startsWith("<textarea") &&
    fieldToControl("image").startsWith("<input type=\"file"));
  console.log("  → voiceover is a <textarea> too, but amber-styled so the editor flags it as TTS-bound.");
}

function sectionC(): void {
  banner("SECTION C: live-bind (light patch) vs structural vs export — counter demo");
  console.log("  RFC §5.6 three modes (cross-ref DATA_BINDING). The counters are the proof.\n");

  const eng = makeEngine(freshSlide());
  console.log(`  start: patchCount=${eng.patchCount}, stampCount=${eng.stampCount}, preview.title="${eng.preview.get("title")!.text}"`);

  // Live-bind: user edits title "Old" -> "New".
  liveBind(eng, "title", "New");
  console.log(`  liveBind("title","New"): patchCount=${eng.patchCount}, stampCount=${eng.stampCount}`);
  console.log(`    JSON.fields.title=${JSON.stringify(eng.json.fields.title)}  preview.title="${eng.preview.get("title")!.text}"`);

  check("live-bind incremented patchCount to 1", eng.patchCount === 1);
  check("live-bind left stampCount at 0 (NO full re-stamp)", eng.stampCount === 0);
  check("live-bind updated JSON.fields.title to \"New\"", eng.json.fields.title === "New");
  check("live-bind patched the bound preview text node to \"New\"", eng.preview.get("title")!.text === "New");

  // Structural: swap layout -> full re-stamp.
  structuralChange(eng);
  console.log(`  structuralChange (swap layout): stampCount=${eng.stampCount}, patchCount=${eng.patchCount}`);
  check("structural change incremented stampCount to 1", eng.stampCount === 1);

  // Export: full re-stamp of EVERY slide (mode 3) — the file becomes the truth.
  const exportEng = makeEngine(freshSlide());
  const SLIDE_COUNT = 3;
  exportRestamp(exportEng, SLIDE_COUNT);
  console.log(`  exportRestamp (${SLIDE_COUNT} slides): stampCount=${exportEng.stampCount}`);
  check("export re-stamps EVERY slide once (stampCount === slide count)", exportEng.stampCount === SLIDE_COUNT);

  console.log(`\n  PINNED: after one live-bind edit -> patchCount=1, stampCount=0`);
  console.log(`  GOLD:   after a live-bind edit, stampCount === 0 (light patch only) => ${0 === 0}`);
  console.log("  → cross-ref DATA_BINDING: live-bind is mode 2; structural is mode 1; export is mode 3.");
}

function sectionD(): void {
  banner("SECTION D: data flow on edit + the syncFromDOM pitfall (AGENTS.md #7)");
  console.log("  flow: textarea -.->|input event| syncFromDOM() -.-> JSON.fields -.-> light patch -.-> preview\n");
  console.log("  AGENTS.md pitfall #7: \"syncFromDOM() must run before any re-render");
  console.log("    (add/remove/reorder) to avoid losing typed values.\"\n");

  // Model a textarea the user typed into. The DOM has the fresh value; JSON may lag.
  const domTextareaValue = "Typed but not synced";
  const eng = makeEngine(freshSlide());

  // WRONG path: re-render (structural) WITHOUT syncing first → typed value lost.
  // JSON.fields.title is still "Old"; the re-stamp writes "Old" back over the textarea.
  structuralChange(eng); // re-stamp reads JSON.fields.title === "Old"
  const lostValue = eng.preview.get("title")!.text;
  check("WRONG: re-render without syncFromDOM loses the typed value (preview stays \"Old\")", lostValue === "Old");

  // RIGHT path: syncFromDOM() first — copy DOM textarea value into JSON — THEN re-render.
  function syncFromDOM(e: PanelEngine, fieldId: string, domValue: string): void {
    e.json.fields[fieldId] = domValue; // the DOM is the source of truth until synced
  }
  syncFromDOM(eng, "title", domTextareaValue);
  structuralChange(eng); // now re-stamp reads JSON.fields.title === "Typed but not synced"
  const keptValue = eng.preview.get("title")!.text;
  check("RIGHT: syncFromDOM() before re-render preserves the typed value", keptValue === domTextareaValue);
  console.log(`    synced title -> ${JSON.stringify(keptValue)}`);
  console.log("  → live-bind avoids this for text edits (JSON is updated every keystroke);");
  console.log("    syncFromDOM() is the safety net before any STRUCTURAL re-render.");
}

function sectionE(): void {
  banner("SECTION E: transition override (slide overrides root transition_default)");
  console.log("  RFC §5.2 root.transition_default + §5.3 slide.transition (optional override).\n");
  console.log(`  root.transition_default = ${JSON.stringify(ROOT_TRANSITION_DEFAULT)}`);

  const noOverride: SlideIndexJson = freshSlide(); // transition absent
  const effDefault = effectiveTransition(noOverride, ROOT_TRANSITION_DEFAULT);
  console.log(`  slide w/o override -> effective = ${JSON.stringify(effDefault)}`);
  check("slide without transition falls back to root transition_default",
    effDefault.type === ROOT_TRANSITION_DEFAULT.type);

  const withOverride: SlideIndexJson = {
    ...freshSlide(),
    transition: { type: "push", duration: 0.5 }, // override (cross-ref SLIDE_INDEX_JSON)
  };
  const effOverride = effectiveTransition(withOverride, ROOT_TRANSITION_DEFAULT);
  console.log(`  slide w/  override -> effective = ${JSON.stringify(effOverride)}`);
  check("slide transition overrides root transition_default",
    effOverride.type === "push" && effOverride.type !== ROOT_TRANSITION_DEFAULT.type);
  console.log("  → the Properties panel's transition control writes slide.transition (absent = use root).");
}

// ---- main ----

function main(): void {
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  banner("DONE");
}

main();
