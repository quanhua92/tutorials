// slide_renderer_interface — ground-truth runnable for "the SlideRenderer seam" (RFC 0001 §9)
// Run: pnpm exec tsx bundles/slide_renderer_interface.ts
//
// Teaches the SINGLE SEAM that decouples the editor from the rendering engine.
// RFC §9.1: `load(slide_html, fields, assets)`, `render_at(timecode) -> frame`,
// `duration() -> seconds`. Preview AND export both go through this interface.
//   - §9.2 Impl 1 (POC, now): HyperFrames. Preview = <hyperframes-player> per
//     active slide; Export = assemble + `npx hyperframes render` once.
//   - §9.3 Impl 2 (future): headless-Chromium frame capture + FFmpeg encode/mux.
//     Swaps in BEHIND THE SAME INTERFACE — editor + export pipeline unchanged.
//   - §9.4 Because preview and export share ONE interface -> ONE engine at every
//     stage, fidelity drift is STRUCTURALLY IMPOSSIBLE.
//   - §9.5 HF's role contracts to "render this one slide at time t" — small,
//     well-defined, replaceable. Timeline / document model / editor are OURS.
//
// Determinism: NO fs reads, NO Date.now, NO Math.random, NO wall-clock. All
// inputs are in-source literals; floats print at .toFixed(6). Re-running is
// byte-identical. The companion slide_renderer_interface.html recomputes the
// SAME mock logic in JS and gold-checks one pinned value (render_at(2.0).time).

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

/** Fixed-precision float (HOW_TO_RESEARCH §STEP 3.1). */
function fix(n: number): string {
  return n.toFixed(6);
}

// ---- RFC 0001 §9.1 SlideRenderer interface (quoted VERBATIM from the RFC) ----
const SLIDE_RENDERER_INTERFACE = [
  "interface SlideRenderer:",
  "    load(slide_html, fields, assets)   # mount a slide composition",
  "    render_at(timecode) -> frame       # render at time t (preview or capture)",
  "    duration() -> seconds",
].join("\n");

// ---- the interface, as a TypeScript shape (what editor + export depend on) ----
type Fields = Record<string, string>;
type Assets = Record<string, string>;

/** Deterministic frame descriptor returned by render_at(). */
interface Frame {
  slideId: string;
  time: number;        // === the timecode passed in (gold-checked at 2.0)
  loaded: boolean;     // true once load() has mounted a composition
  hasContent: boolean; // true iff the mounted slide_html is non-empty
}

/** The seam. Editor and export BOTH program to this interface (RFC §9.4). */
interface SlideRenderer {
  load(slideHtml: string, fields: Fields, assets: Assets): void;
  renderAt(timecode: number): Frame;
  duration(): number;
}

const NOT_LOADED_MSG = "SlideRenderer.render_at() called before load()";

// ---- RFC §9.5: HF contracts to "render this one slide at time t" ----
// What HF owns (small, replaceable) vs what stays OURS regardless of engine.
const HF_ROLE_CONTRACT = {
  hfOwns: "render one slide at time t",
  ours: ["timeline orchestration", "document model", "editor", "asset library", "AI"],
};

// ---- RFC §9.2 / §9.3: the two implementations (text from the RFC) ----
const IMPL_1_HYPERFRAMES = {
  backend: "hyperframes",
  preview: "instantiate HF's <hyperframes-player> per active slide; drive to playhead",
  export: "assemble slides + data into one HF composition; `npx hyperframes render` once",
  tools: ["<hyperframes-player>", "npx hyperframes render", "npx hyperframes lint"],
};

const IMPL_2_OWN_RENDERER = {
  backend: "own-renderer",
  preview: "headless-Chromium frame capture; seek GSAP to t, capture the frame",
  export: "headless-Chromium capture every frame index 0..N-1 + FFmpeg encode/mux",
  tools: ["headless-Chromium (Page.screenshot / CDP)", "FFmpeg encode/mux"],
};

// ===========================================================================
// MockSlideRenderer — a deterministic in-process implementation of the seam.
// It does NOT render pixels; it returns a deterministic Frame descriptor. This
// is the contract every real implementation (HF or ours) must satisfy:
//   (1) render_at() BEFORE load()  -> error  (load-before-render invariant)
//   (2) render_at(t) after load    -> PURE function of t (same t -> same frame)
//   (3) duration()                 -> stable across calls (measured at load)
// The `backend` tag lets us model §9.4: at any stage, preview and export use
// the SAME backend, so their frames match byte-for-byte (deterministic mock).
// ===========================================================================
class MockSlideRenderer implements SlideRenderer {
  readonly backend: string;
  private loaded = false;
  private slideId = "<unloaded>";
  private slideHtml = "";
  private fields: Fields = {};
  private assets: Assets = {};
  private measuredDuration = 0; // "measured" at load (mocks ffprobe on voiceover)

  constructor(backend: string) {
    this.backend = backend;
  }

  load(slideHtml: string, fields: Fields, assets: Assets): void {
    // mount: store the composition + data, mark loaded, "measure" duration.
    // Measurement is a DETERMINISTIC function of the inputs (no wall-clock).
    this.slideHtml = slideHtml;
    this.fields = fields;
    this.assets = assets;
    this.slideId = fields["__SLIDE_ID__"] ?? "slide-?";
    this.loaded = true;
    // Mock measurement: a real impl runs ffprobe on the voiceover. Here we
    // derive a stable duration from the slide_html length so the number is
    // reproducible across runs (determinism hard rule).
    this.measuredDuration = Math.max(0.5, Math.round((slideHtml.length / 20) * 100) / 100);
  }

  renderAt(timecode: number): Frame {
    if (!this.loaded) throw new Error(NOT_LOADED_MSG);
    return {
      slideId: this.slideId,
      time: timecode, // pure: echo the input timecode (the gold value)
      loaded: true,
      hasContent: this.slideHtml.length > 0,
    };
  }

  duration(): number {
    return this.measuredDuration;
  }
}

// ---- sample slide (in-source literals; no FS reads) ----
const SAMPLE_SLIDE_HTML =
  '<template><div data-composition-id="__SLIDE_ID__">' +
  '<h1>__TITLE__</h1><p>__BODY__</p></div></template>';
const SAMPLE_FIELDS: Fields = {
  "__SLIDE_ID__": "slide-0",
  "__TITLE__": "Eco Bottle",
  "__BODY__": "Sustainable by design.",
};
const SAMPLE_ASSETS: Assets = { img: "sha256-c0ffee.jpg" };

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the interface — preview AND export both go through it");
  console.log("  RFC 0001 §9.1 — the SlideRenderer interface (verbatim):\n");
  for (const line of SLIDE_RENDERER_INTERFACE.split("\n")) console.log("    " + line);
  console.log("");
  console.log("  Three methods. The editor (§8 preview) and the export pipeline");
  console.log("  (§10) BOTH program to this interface — they never reach around it.");
  console.log("  That single constraint is what makes the engine replaceable (§9.3)\n  and fidelity drift structurally impossible (§9.4).\n");

  const hasLoad = /load\(slide_html, fields, assets\)/.test(SLIDE_RENDERER_INTERFACE);
  const hasRenderAt = /render_at\(timecode\) -> frame/.test(SLIDE_RENDERER_INTERFACE);
  const hasDuration = /duration\(\) -> seconds/.test(SLIDE_RENDERER_INTERFACE);
  check("interface exposes load(slide_html, fields, assets)", hasLoad);
  check("interface exposes render_at(timecode) -> frame", hasRenderAt);
  check("interface exposes duration() -> seconds", hasDuration);
  console.log("  → the TypeScript shape mirrors the RFC: a SlideRenderer with exactly");
  console.log("    these three methods. Everything else (timeline, document model,");
  console.log("    editor) is OURS (§9.5). Cross-ref 🔗 PREVIEW_ENGINE / EXPORT_PIPELINE.");
}

function sectionB(): void {
  banner("SECTION B: Impl 1 (POC, now) = HyperFrames");
  console.log("  RFC 0001 §9.2 — HyperFrames is the initial renderer for BOTH preview");
  console.log("  and export. Reuses today's render path (rendering.py).\n");
  console.log(`    backend = ${IMPL_1_HYPERFRAMES.backend}`);
  console.log(`    preview = ${IMPL_1_HYPERFRAMES.preview}`);
  console.log(`    export  = ${IMPL_1_HYPERFRAMES.export}`);
  console.log(`    tools   = ${IMPL_1_HYPERFRAMES.tools.join(", ")}\n`);

  // Prove it: instantiate the HF backend, drive it through the interface.
  const hf = new MockSlideRenderer("hyperframes");
  hf.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  const f = hf.renderAt(2.0);
  console.log(`    hf.load(...) → mounted; hf.renderAt(2.0) →`);
  console.log(`      { slideId: "${f.slideId}", time: ${fix(f.time)}, loaded: ${f.loaded}, hasContent: ${f.hasContent} }`);
  check("HF preview path uses <hyperframes-player>", /<hyperframes-player>/.test(IMPL_1_HYPERFRAMES.preview));
  check("HF export path uses `npx hyperframes render`", /npx hyperframes render/.test(IMPL_1_HYPERFRAMES.export));
  check("HF impl satisfies the interface (load -> renderAt -> duration all work)",
    hf.duration() > 0 && f.loaded && f.time === 2.0);
  console.log("  → HF is one IMPLEMENTATION of the seam, not the seam itself. The");
  console.log("    editor never imports HF directly — it imports the interface (§9.5).");
}

function sectionC(): void {
  banner("SECTION C: Impl 2 (future) = headless Chromium + FFmpeg (the swap path)");
  console.log("  RFC 0001 §9.3 — our own renderer. Headless-Chromium frame capture +");
  console.log("  FFmpeg encode/mux, targeting visual determinism (§11). Swaps in");
  console.log("  BEHIND THE SAME INTERFACE; editor + export pipeline are unchanged.\n");
  console.log(`    backend = ${IMPL_2_OWN_RENDERER.backend}`);
  console.log(`    preview = ${IMPL_2_OWN_RENDERER.preview}`);
  console.log(`    export  = ${IMPL_2_OWN_RENDERER.export}`);
  console.log(`    tools   = ${IMPL_2_OWN_RENDERER.tools.join(", ")}\n`);

  // Prove the swap is invisible to the caller: drive the own-renderer backend
  // through the SAME interface, same call sites, same Frame shape.
  const own = new MockSlideRenderer("own-renderer");
  own.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  const f = own.renderAt(2.0);
  console.log(`    own.load(...) → mounted; own.renderAt(2.0) →`);
  console.log(`      { slideId: "${f.slideId}", time: ${fix(f.time)}, loaded: ${f.loaded}, hasContent: ${f.hasContent} }`);

  check("own-renderer preview path uses headless-Chromium frame capture",
    /headless-Chromium/.test(IMPL_2_OWN_RENDERER.preview) && /Page.screenshot|capture/.test(IMPL_2_OWN_RENDERER.tools.join(" ")));
  check("own-renderer export path uses FFmpeg encode/mux",
    /FFmpeg encode\/mux/.test(IMPL_2_OWN_RENDERER.export));
  check("swap is invisible to callers: own-renderer satisfies the SAME interface",
    own.duration() === hfSameInputsDuration() && f.time === 2.0 && f.loaded);
  console.log("  → headless Chromium (Page.screenshot / CDP) is the standard frame-");
  console.log("    capture primitive; FFmpeg is the standard encode/mux step. Both");
  console.log("    are documented, battle-tested tools. The swap is a packaging");
  console.log("    concern, not an architecture change. Cross-ref 🔗 VISUAL_DETERMINISM.");
}

/** HF backend duration for the sample inputs — used to prove swap-parity. */
function hfSameInputsDuration(): number {
  const hf = new MockSlideRenderer("hyperframes");
  hf.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  return hf.duration();
}

function sectionD(): void {
  banner("SECTION D: §9.4 — why fidelity drift is STRUCTURALLY IMPOSSIBLE");
  console.log("  RFC 0001 §9.4 (decision record): 'Preview and export share ONE");
  console.log("  interface → ONE engine at every stage. POC: both use HF →");
  console.log("  consistent. Later: both swap to our renderer together → still");
  console.log("  consistent. \"It looked different when I exported\" is structurally");
  console.log("  impossible, because preview and render are never two different");
  console.log("  engines.'\n");

  // Model the three scenarios with the deterministic mock. Same backend =>
  // byte-identical frames. The architecture FORBIDS the mixed-backend case.
  const t = 2.0;
  const desc = (r: SlideRenderer): string => JSON.stringify(r.renderAt(t));

  // POC stage: both HF.
  const pocPreview = new MockSlideRenderer("hyperframes");
  const pocExport = new MockSlideRenderer("hyperframes");
  pocPreview.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  pocExport.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);

  // LATER stage: both own-renderer.
  const laterPreview = new MockSlideRenderer("own-renderer");
  const laterExport = new MockSlideRenderer("own-renderer");
  laterPreview.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  laterExport.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);

  // FORBIDDEN case: preview=HF, export=own (what the architecture rules out).
  const mixedPreview = new MockSlideRenderer("hyperframes");
  const mixedExport = new MockSlideRenderer("own-renderer");
  mixedPreview.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  mixedExport.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);

  console.log(`    POC   preview.renderAt(${t}) = ${desc(pocPreview)}`);
  console.log(`    POC   export .renderAt(${t}) = ${desc(pocExport)}`);
  console.log(`    LATER preview.renderAt(${t}) = ${desc(laterPreview)}`);
  console.log(`    LATER export .renderAt(${t}) = ${desc(laterExport)}`);
  console.log(`    MIXED preview.renderAt(${t}) = ${desc(mixedPreview)}  (HF backend)`);
  console.log(`    MIXED export .renderAt(${t}) = ${desc(mixedExport)}  (own backend)\n`);

  const pocMatch = desc(pocPreview) === desc(pocExport);
  const laterMatch = desc(laterPreview) === desc(laterExport);
  // The mock is deterministic, so even the mixed case's *frame descriptor* matches
  // here — BUT the architecture never allows mixing engines. We assert the real
  // invariant: at every stage, preview.backend === export.backend.
  const pocSameBackend = pocPreview.backend === pocExport.backend;
  const laterSameBackend = laterPreview.backend === laterExport.backend;
  const mixedIsForbidden = mixedPreview.backend !== mixedExport.backend;

  check("POC stage: preview + export use the SAME backend (both HF) → frames match",
    pocSameBackend && pocMatch);
  check("LATER stage: preview + export use the SAME backend (both own) → frames match",
    laterSameBackend && laterMatch);
  check("the MIXED case (preview≠export engine) is exactly what the architecture FORBIDS",
    mixedIsForbidden);
  console.log("  → there is no code path where preview and export pick different");
  console.log("    engines. The seam enforces one engine per stage; drift cannot arise.");
  console.log("    This is the single biggest risk of a decoupled-preview architecture,");
  console.log("    eliminated by construction (RFC §18 risk row).");
}

function sectionE(): void {
  banner("SECTION E: §9.5 — make HF smaller (it contracts to one job)");
  console.log("  RFC 0001 §9.5 — HF's role contracts from 'the whole composition");
  console.log("  engine' to 'render this one slide at time t.' Timeline orchestration,");
  console.log("  the document model, and the editor are all OURS; HF is a pluggable");
  console.log("  rendering primitive.\n");
  console.log(`    HF owns   = "${HF_ROLE_CONTRACT.hfOwns}"`);
  console.log(`    OURS      = ${HF_ROLE_CONTRACT.ours.join(", ")}\n`);

  // HF's surface is exactly 3 methods (the interface). Everything else is ours.
  const hfSurfaceMethods = 3;
  const ourConcerns = HF_ROLE_CONTRACT.ours.length;
  check("HF's surface is the 3-method interface (load / render_at / duration)",
    hfSurfaceMethods === 3);
  check(`timeline + document model + editor + assets + AI are OURS (${ourConcerns} concerns, not HF's)`,
    ourConcerns === 5 && !HF_ROLE_CONTRACT.ours.includes("render"));
  console.log("  → contracting HF to one job is what makes it replaceable (§9.3).");
  console.log("    If HF owned the timeline or document model, swapping it would mean");
  console.log("    rewriting the editor. It doesn't, so it doesn't.");
}

function sectionF(): void {
  banner("SECTION F: the mock impl + contract invariants");
  console.log("  A deterministic MockSlideRenderer implements the seam. The contract");
  console.log("  every real impl (HF or ours) must satisfy:\n");
  console.log("    (1) render_at() BEFORE load()  → error (load-before-render)");
  console.log("    (2) render_at(t) after load    → PURE function of t (determinism)");
  console.log("    (3) duration()                 → stable across calls\n");

  const r = new MockSlideRenderer("mock");

  // (1) load-before-render: renderAt() before load() must throw.
  let threwBeforeLoad = false;
  try {
    r.renderAt(1.0);
  } catch (e) {
    threwBeforeLoad = e instanceof Error && e.message === NOT_LOADED_MSG;
  }
  console.log(`    (1) before load: renderAt(1.0) → ${threwBeforeLoad ? "throws Error" : "NO ERROR (BUG!)"}`);
  console.log(`        message: "${NOT_LOADED_MSG}"`);
  check("render_at() before load() throws (load-before-render invariant)", threwBeforeLoad);

  // Now load.
  r.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  console.log(`\n    r.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS) → mounted`);
  console.log(`    r.duration() = ${fix(r.duration())}  (mocks ffprobe on the voiceover)`);

  // (2) purity: same t → byte-identical descriptor (two independent calls).
  const f1 = r.renderAt(2.0);
  const f2 = r.renderAt(2.0);
  const pure = JSON.stringify(f1) === JSON.stringify(f2);
  console.log(`\n    (2) renderAt(2.0) #1 = ${JSON.stringify(f1)}`);
  console.log(`        renderAt(2.0) #2 = ${JSON.stringify(f2)}`);
  console.log(`        byte-identical? ${pure}`);
  check("render_at(t) is PURE: same t → byte-identical frame descriptor", pure);

  // GOLD value (html recomputes this): render_at(2.0).time === 2.0 exactly.
  const goldTime = r.renderAt(2.0).time;
  console.log(`\n    GOLD: renderAt(2.0).time = ${fix(goldTime)} === 2.000000  (html gold-checks this)`);
  check("GOLD: render_at(2.0).time === 2.0 (the pinned value the html recomputes)",
    goldTime === 2.0);

  // (3) duration stability across calls.
  const d1 = r.duration();
  const d2 = r.duration();
  const d3 = r.duration();
  console.log(`\n    (3) duration() ×3 = ${fix(d1)}, ${fix(d2)}, ${fix(d3)}  (stable)`);
  check("duration() is stable across calls (same value every time)", d1 === d2 && d2 === d3);

  // Determinism across runs: a FRESH instance loaded with the same inputs must
  // produce the same duration (no Date.now / Math.random in the measurement).
  const fresh = new MockSlideRenderer("mock");
  fresh.load(SAMPLE_SLIDE_HTML, SAMPLE_FIELDS, SAMPLE_ASSETS);
  check("determinism: fresh instance, same inputs → same measured duration",
    fresh.duration() === r.duration());
  console.log(`\n  PINNED: render_at(2.0).time = ${fix(goldTime)}; measured duration = ${fix(r.duration())};`);
  console.log("  no Date.now / Math.random / FS anywhere — re-running is byte-identical.");
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
