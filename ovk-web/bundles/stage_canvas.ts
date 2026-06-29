// stage_canvas — ground-truth runnable for "the Stage / Canvas surface" (RFC 0001 §7, §8)
// Run: pnpm exec tsx bundles/stage_canvas.ts
//
// Teaches the CENTER panel of the editor (RFC §7 "Stage / Canvas"). The stage
// is a live, REAL-TIME (not frame-accurate) preview of the ACTIVE slide. It:
//   - mounts the active slide's index.html via the SlideRenderer interface (§8, §9.1)
//   - renders at the root canvas dims (1920×1080, aspect 16:9 — RFC §5.2)
//   - scales the canvas to fit the viewport while PRESERVING aspect ratio
//     (object-fit: contain semantics; letterbox, never stretch)
//   - binds to the playhead: local time = clamp(global − slideStart, 0, duration)
//   - swaps the mounted composition when the active slide changes
//
// Determinism: NO fs reads, NO Date.now, NO Math.random, NO wall-clock. All
// inputs are in-source literals; floats print at .toFixed(6). Re-running is
// byte-identical. The companion stage_canvas.html recomputes the SAME math in
// JS and gold-checks one pinned value (aspect === 16/9).

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

// ---- RFC 0001 §9.1 SlideRenderer interface (quoted verbatim) ----
// The stage drives the engine through this interface; preview and export BOTH
// go through it (§9.4 — fidelity drift is "structurally impossible").
const SLIDE_RENDERER_INTERFACE = [
  "interface SlideRenderer:",
  "    load(slide_html, fields, assets)   # mount a slide composition",
  "    render_at(timecode) -> frame       # render at time t (preview or capture)",
  "    duration() -> seconds",
].join("\n");

// ---- RFC 0001 §5.2 root canvas (the dims the stage must render at) ----
const CANVAS = { width: 1920, height: 1080, fps: 30 };

// ---- RFC 0001 §7 "Stage / Canvas" row: binds to the ACTIVE slide ----
// The stage mounts EXACTLY one slide at a time. Switching the active slide
// unmounts the previous composition and mounts the new one through
// SlideRenderer.load() (see Section D).
let ACTIVE_SLIDE_ID: string | null = null;

// ---- canonical host-div (AGENTS.md "Host div format") — the mount point ----
// The slide's bare-<template> index.html is mounted into THIS div. AGENTS.md:
// "position:absolute;inset:0; is REQUIRED on the host div — without it,
// sub-comp content collapses to zero size." (Section F drills into why.)
const HOST_DIV_HTML =
  `<div data-composition-id="slide-0"
     data-composition-src="compositions/slide-0.html"
     data-start="0.5" data-duration="5.0"
     class="clip" style="position:absolute;inset:0;z-index:100;"></div>`;

// ---- sample project timeline (for the playhead + swap demos) ----
// Each slide has a global [start, start+duration) window on the root timeline.
interface Slide {
  id: string;
  start: number;      // global start time (seconds)
  duration: number;   // measured duration (seconds)
}
const PROJECT_SLIDES: Slide[] = [
  { id: "slide-0", start: 0.5, duration: 5.0 },
  { id: "slide-1", start: 5.9, duration: 4.0 },
  { id: "slide-2", start: 10.3, duration: 6.0 },
];

// ---- scale-to-fit math (object-fit: contain semantics, MDN) ----
/**
 * Compute the uniform scale that fits a cw×ch canvas inside a vw×vh viewport
 * while preserving aspect ratio. The limiting axis wins; the canvas is NEVER
 * stretched. The unused viewport area is letterboxed (black bars).
 *   scale = min(vw/cw, vh/ch)
 *   w = cw * scale,  h = ch * scale
 */
function scaleToFit(cw: number, ch: number, vw: number, vh: number): {
  scale: number; w: number; h: number;
} {
  const scale = Math.min(vw / cw, vh / ch);
  return { scale, w: cw * scale, h: ch * scale };
}

// ---- playhead math (RFC §8: "Drives GSAP timelines from the playhead time") ----
/**
 * Convert a GLOBAL playhead time into the ACTIVE slide's LOCAL time, clamped.
 *   local = clamp(globalTime - slideStart, 0, slideDuration)
 * Below 0 (before the slide starts) clamps to 0; past the end clamps to the
 * slide's duration. This is the value the preview engine feeds GSAP's seek().
 */
function localTime(globalTime: number, slideStart: number, slideDuration: number): number {
  const raw = globalTime - slideStart;
  if (raw < 0) return 0;
  if (raw > slideDuration) return slideDuration;
  return raw;
}

/** Pick the slide whose [start, start+duration) contains the global time. */
function activeSlideAt(globalTime: number): Slide | null {
  for (const s of PROJECT_SLIDES) {
    if (globalTime >= s.start && globalTime < s.start + s.duration) return s;
  }
  return null;
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the stage renders the ACTIVE slide via SlideRenderer");
  console.log("  RFC 0001 §7 — 'Stage / Canvas (center) | binds to: active slide |");
  console.log("  job: live preview via SlideRenderer; play/scrub.'");
  console.log("  RFC 0001 §8 — 'Renders the active slide's index.html (the bare");
  console.log("  <template>) in the browser via the SlideRenderer interface.'\n");
  console.log("  SlideRenderer interface (RFC §9.1, verbatim):");
  for (const line of SLIDE_RENDERER_INTERFACE.split("\n")) console.log("    " + line);

  ACTIVE_SLIDE_ID = "slide-0"; // simulate mounting slide-0 as the active slide
  console.log(`\n  ACTIVE_SLIDE_ID = "${ACTIVE_SLIDE_ID}" (mounted via SlideRenderer.load)`);
  check("exactly one active slide is mounted at a time", ACTIVE_SLIDE_ID !== null);
  check("SlideRenderer exposes load() / render_at() / duration()",
    /load\(/.test(SLIDE_RENDERER_INTERFACE) &&
    /render_at\(/.test(SLIDE_RENDERER_INTERFACE) &&
    /duration\(/.test(SLIDE_RENDERER_INTERFACE));
  console.log("  → the stage never renders all slides at once; it renders the ONE");
  console.log("    active slide. Switching slides swaps the mounted composition (Section D).");
}

function sectionB(): void {
  banner("SECTION B: canvas dims, aspect ratio (16:9), and scale-to-fit");
  const { width, height } = CANVAS;
  const aspect = width / height;
  const sixteenNinths = 16 / 9;
  console.log("  RFC 0001 §5.2 + AGENTS.md 'Layout file format': canvas is");
  console.log(`  {width:1920, height:1080} (data-width/data-height on each composition).\n`);
  console.log(`    width  = ${width}`);
  console.log(`    height = ${height}`);
  console.log(`    aspect = width/height = ${fix(aspect)}`);
  console.log(`    16/9                = ${fix(sixteenNinths)}`);
  check("1920/1080 === 16/9 within 1e-6", Math.abs(aspect - sixteenNinths) < 1e-6);
  check("aspect is the standard 16:9 (1.777778)", fix(aspect) === "1.777778");

  console.log("");
  console.log("  Scale-to-fit (MDN object-fit: contain — 'sized to maintain its aspect");
  console.log("  ratio while fitting within the element's content box'). The limiting");
  console.log("  axis wins; the canvas is letterboxed, never stretched:\n");
  console.log("    scale = min(vw/cw, vh/ch);  w = cw*scale;  h = ch*scale\n");
  const cases = [
    { vw: 800, vh: 450, note: "same 16:9 aspect → no letterbox" },
    { vw: 600, vh: 500, note: "taller viewport → letterbox top/bottom" },
    { vw: 1280, vh: 720, note: "same aspect, larger viewport" },
  ];
  for (const c of cases) {
    const r = scaleToFit(width, height, c.vw, c.vh);
    console.log(`    viewport ${c.vw}x${c.vh}: scale=${fix(r.scale)} → canvas ${fix(r.w)}x${fix(r.h)}  (${c.note})`);
  }
  const r0 = scaleToFit(width, height, 800, 450);
  const r1 = scaleToFit(width, height, 600, 500);
  check("800x450 viewport (16:9) → scale 0.416667, canvas 800x450 (fills, no bars)",
    fix(r0.scale) === "0.416667" && fix(r0.w) === "800.000000" && fix(r0.h) === "450.000000");
  check("600x500 viewport (taller) → scale 0.312500, canvas 600x337.5 (letterboxed)",
    fix(r1.scale) === "0.312500" && fix(r1.w) === "600.000000" && fix(r1.h) === "337.500000");
  console.log(`\n  PINNED: aspect = ${fix(aspect)}; fit 1920x1080 into 800x450 → scale ${fix(r0.scale)};`);
  console.log(`  fit into 600x500 → scale ${fix(r1.scale)}, canvas ${fix(r1.w)}x${fix(r1.h)}.`);
}

function sectionC(): void {
  banner("SECTION C: playhead → local time (clamp to [0, slideDuration])");
  console.log("  RFC 0001 §8 — 'Drives GSAP timelines from the playhead time.'");
  console.log("  The stage converts the SHARED global playhead into the ACTIVE slide's");
  console.log("  local time, then seeks the slide's GSAP timeline to it.\n");
  console.log("    local = clamp(globalTime - slideStart, 0, slideDuration)\n");

  const slide = PROJECT_SLIDES[1]; // slide-1: start=5.9, duration=4.0
  const samples = [4.0, 5.9, 7.5, 9.89, 11.0];
  for (const g of samples) {
    const lt = localTime(g, slide.start, slide.duration);
    console.log(`    globalTime=${fix(g)}  →  local=${fix(lt)}   (slide-1: start=${fix(slide.start)}, dur=${fix(slide.duration)})`);
  }
  check("before slide start (global 4.0) clamps UP to local 0",
    localTime(4.0, slide.start, slide.duration) === 0);
  check("after slide end (global 11.0) clamps DOWN to slideDuration (4.0)",
    localTime(11.0, slide.start, slide.duration) === slide.duration);
  const pinned = localTime(7.5, slide.start, slide.duration);
  console.log(`\n  PINNED: globalTime 7.5, slide-1 start 5.9 → local ${fix(pinned)} (GSAP seeks here).`);
  console.log("  → the playhead is SHARED with the timeline panel (🔗 TIMELINE_PANEL).");
}

function sectionD(): void {
  banner("SECTION D: switching slides = swapping the mounted composition");
  console.log("  RFC 0001 §7 — the stage binds to the ACTIVE slide. When the playhead");
  console.log("  crosses into the next slide's [start, start+duration), the active id");
  console.log("  changes and SlideRenderer.load() mounts the new composition (unmounting");
  console.log("  the previous one).\n");
  console.log("  project slides (global timeline windows):");
  for (const s of PROJECT_SLIDES) {
    console.log(`    ${s.id}: [${fix(s.start)}, ${fix(s.start + s.duration)})`);
  }
  console.log("");
  const before = activeSlideAt(7.5);   // inside slide-1
  const after = activeSlideAt(11.0);   // inside slide-2
  const gap = activeSlideAt(5.6);      // in the gap between slide-0 and slide-1
  console.log(`    activeSlideAt(7.5)  = ${before ? before.id : "null"}`);
  console.log(`    activeSlideAt(11.0) = ${after ? after.id : "null"}`);
  console.log(`    activeSlideAt(5.6)  = ${gap ? gap.id : "null"}  (in a gap between slides)`);
  check("active slide swaps when the playhead crosses a slide boundary",
    before !== null && after !== null && before.id !== after.id);
  check("activeSlideAt returns null in a gap (no slide contains the time)",
    gap === null);
  console.log("  → the swap is a mount/unmount via SlideRenderer; BETWEEN-slide");
  console.log("    transitions (crossfade/push) live in the ROOT index.html (RFC §5.1),");
  console.log("    not in the stage. Cross-ref 🔗 BARE_TEMPLATE for the swapped content.");
}

function sectionE(): void {
  banner("SECTION E: real-time, NOT frame-accurate (the decoupling rationale)");
  console.log("  RFC 0001 §8 — 'Real-time, not frame-accurate. That is the point of");
  console.log("  decoupling: the preview is responsive for editing; the export is rigorous.'");
  console.log("  RFC 0001 §11 — visual determinism is enforced at EXPORT, not in preview.\n");

  const fps = CANVAS.fps;
  // PREVIEW: on each browser paint (rAF), the stage seeks GSAP to whatever the
  // playhead reports. dt between paints is variable (browser-paced), so frame
  // indices may REPEAT (slow paint) or SKIP (scrub/fast-forward). This is fine
  // for editing — the preview is responsive, not a frame-accurate capture.
  const previewPlayheadSamples = [0.0, 0.06, 0.09, 0.15, 0.166];
  console.log("  PREVIEW (real-time): stage seeks GSAP to the playhead per paint;");
  console.log("  dt is variable (browser-paced) — frame indices repeat/skip:");
  for (const t of previewPlayheadSamples) {
    const fi = Math.floor(t * fps);
    console.log(`    playhead ${fix(t)}s → seek(${fix(t)}); nearest frame index ${fi}`);
  }

  // EXPORT: render every frame index 0..N-1 exactly once at 1/fps each.
  console.log("");
  console.log(`  EXPORT (frame-accurate): npx hyperframes render steps frame index`);
  console.log(`  0..N-1 at exactly 1/fps = ${fix(1 / fps)}s each (RFC §10, §11):`);
  for (let i = 0; i < 5; i++) {
    const t = i / fps;
    console.log(`    frame[${i}] → render_at(${fix(t)})  (exact, no repeat/skip)`);
  }
  const previewDtsAreVariable =
    previewPlayheadSamples[1] - previewPlayheadSamples[0] !== 1 / fps;
  check("preview sample dt is NOT 1/fps (real-time, variable cadence)",
    previewDtsAreVariable);
  check("export step IS exactly 1/fps (frame-accurate, deterministic)",
    fix(1 / fps) === "0.033333");
  console.log("\n  → preview responsiveness and export rigor are DIFFERENT jobs;");
  console.log("    decoupling them (§8) is what lets the editor stay fast without lying");
  console.log("    about the final video (§10/§11). Cross-ref 🔗 PREVIEW_ENGINE / EXPORT_PIPELINE.");
}

function sectionF(): void {
  banner("SECTION F: why position:absolute;inset:0; on the host div");
  console.log("  AGENTS.md 'Host div format' — the slide composition is mounted INTO this");
  console.log("  div. Quoted rule: 'position:absolute;inset:0; is REQUIRED on the host div");
  console.log("  — without it, sub-comp content collapses to zero size.'\n");
  for (const line of HOST_DIV_HTML.split("\n")) console.log("    " + line);
  console.log("");
  const hasAbsInset = /position:\s*absolute;\s*inset:\s*0/.test(HOST_DIV_HTML);
  const hasCompSrc = /data-composition-src=/.test(HOST_DIV_HTML);
  const hasClassClip = /class="clip"/.test(HOST_DIV_HTML);
  check("host div carries position:absolute;inset:0; (REQUIRED, non-negotiable)",
    hasAbsInset);
  check("host div references the composition (data-composition-src) + class=\"clip\"",
    hasCompSrc && hasClassClip);
  console.log("  → inset:0 stretches the host to fill the scaled canvas; without it the");
  console.log("    mounted <template> content has zero size and the stage shows nothing.");
  console.log("    (HF sub-comp mounting context quirk — AGENTS.md 'Why NOT flex/absolute'.)");
  console.log("    Cross-ref 🔗 BARE_TEMPLATE for the slide HTML mounted into this div.");
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
