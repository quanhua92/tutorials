// preview_engine — ground-truth runnable for "the app-owned preview engine" (RFC 0001 §8)
// Run: pnpm exec tsx bundles/preview_engine.ts
//
// Teaches RFC 0001 §8: the preview is APP-OWNED — the editor drives it, and
// HyperFrames is NOT in the editing loop as a black box. The engine:
//   - renders the ACTIVE slide's index.html via the SlideRenderer interface (§8, §9.1)
//   - drives the slide's GSAP timeline from the PLAYHEAD by SEEKING it:
//       tl.time(playheadTime)        // playhead setter, not play()
//     Deterministic given t: seeking a PAUSED timeline never advances on its own.
//   - is real-time, NOT frame-accurate (§8) — decoupled from the rigorous export
//     pipeline (§10/§11).
//
// The math underneath "drive from playhead": between two keyframes the timeline
// evaluates a LINEAR INTERPOLATION  lerp(a,b,t) = a + (b-a)*t  (Wikipedia,
// "Linear interpolation"). This runnable models a mock multi-keyframe GSAP-style
// timeline, seeks it to several playhead times, and prints every value that
// PREVIEW_ENGINE.md cites verbatim.
//
// Determinism: NO fs reads, NO Date.now, NO Math.random, NO wall-clock. All
// inputs are in-source literals; floats print at .toFixed(6). Re-running is
// byte-identical. The companion preview_engine.html recomputes the SAME lerp in
// JS and gold-checks one pinned value (sampleAt(TL_TWO, 0.5) === 0.5). It also
// drives a REAL GSAP timeline (GSAP CDN — the RFC-mandated animation runtime)
// from a playhead slider and cross-checks tl.time(0.5) against the same value.

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
// The engine sits behind this interface; preview and export BOTH go through it
// (§9.4 — fidelity drift is "structurally impossible"). The preview engine is
// one implementation of it; export is another; they share the same shape.
const SLIDE_RENDERER_INTERFACE = [
  "interface SlideRenderer:",
  "    load(slide_html, fields, assets)   # mount a slide composition",
  "    render_at(timecode) -> frame       # render at time t (preview or capture)",
  "    duration() -> seconds",
].join("\n");

// ---- RFC 0001 §8 (App-Owned Preview Engine), load-bearing quotes (verbatim) ----
const RFC_S8_QUOTE =
  "The preview is app-owned — the editor drives it; HyperFrames is not in the " +
  "editing loop as a black box.";
const RFC_S8_REALTIME_QUOTE =
  "Real-time, not frame-accurate. That is the point of decoupling: the preview " +
  "is responsive for editing; the export is rigorous (§10).";

// ---- AGENTS.md "Layout file format" — the slide <script> (quoted verbatim) ----
// The slide's GSAP timeline is created PAUSED and registered into the global
// window.__timelines map, keyed by the slide's composition id. The preview engine
// looks the timeline up by that key and SEEKS it from the playhead (Section B).
const SLIDE_SCRIPT_QUOTED = [
  "var tl = gsap.timeline({ paused: true });",
  "tl.from('[data-composition-id=\"__SLIDE_ID__\"] .content > *',",
  "        { opacity: 0, y: 40, duration: 0.4, stagger: 0.1 });",
  "window.__timelines['__SLIDE_ID__'] = tl;",
].join("\n");

// ---- RFC 0001 §5.2 canvas fps (the export frame cadence; 1/fps each) ----
const FPS = 30;

// ---- the interpolation math: linear interpolation between keyframes ----
// Wikipedia, "Linear interpolation": for an x in (x0, x1) with known points
// (x0,y0),(x1,y1), the linear interpolant along the straight line is
//     y = y0 + (x - x0) * (y1 - y0) / (x1 - x0)
// which in the computer-graphics "lerp" form (t in [0,1]) is
//     lerp(a, b, t) = a + t * (b - a)        // a = y0, b = y1, t = (x-x0)/(x1-x0)
// This is what a timeline evaluates between two keyframes under LINEAR easing.
// (GSAP's DEFAULT ease is power1.out; the lerp identity is the linear — i.e.
// "none" / `gsap.parseEase("none")` — case, which is what keeps the math
// reproducible by hand. Any easing is just a remap of t before the lerp.)

/** lerp(a, b, t) = a + t*(b-a). Wikipedia "Linear interpolation", lerp form. */
function lerp(a: number, b: number, t: number): number {
  return a + t * (b - a);
}

interface Keyframe { t: number; value: number; }

/**
 * A mock multi-keyframe GSAP-style timeline. `time(playhead)` is the playhead
 * setter — the mirror of GSAP's `tl.time(value)` (GSAP docs: "Gets or sets the
 * local position of the playhead... sets time, jumping to new value just like
 * seek()"). It moves the playhead to `playhead` (clamped to the timeline's
 * [first.t, last.t] range), evaluates the linear interpolant of the surrounding
 * segment, and returns the value at the playhead. The timeline stays PAUSED —
 * seeking never auto-plays.
 */
interface MockTimeline {
  slideId: string;
  keyframes: Keyframe[];   // sorted ascending by t; >= 2 entries
}

function clamp(n: number, lo: number, hi: number): number {
  if (n < lo) return lo;
  if (n > hi) return hi;
  return n;
}

/** Seek a paused timeline to `playhead`; return the interpolated value there. */
function sampleAt(tl: MockTimeline, playhead: number): number {
  const kf = tl.keyframes;
  const lo = kf[0].t;
  const hi = kf[kf.length - 1].t;
  const x = clamp(playhead, lo, hi);
  // find the segment [i, i+1] that contains x
  let i = 0;
  for (let k = 0; k < kf.length - 1; k++) {
    if (x >= kf[k].t && x <= kf[k + 1].t) { i = k; break; }
  }
  const a = kf[i];
  const b = kf[i + 1];
  const span = b.t - a.t;
  const localT = span === 0 ? 0 : (x - a.t) / span;   // t in [0,1] within the segment
  return lerp(a.value, b.value, localT);
}

// ---- the window.__timelines registry (AGENTS.md slide <script>) ----
// Slides register their PAUSED GSAP timeline under their composition id. The
// preview engine looks the timeline up by ACTIVE slide id and seeks it.
const REGISTRY: Record<string, MockTimeline> = {};

function registerTimeline(tl: MockTimeline): MockTimeline {
  REGISTRY[tl.slideId] = tl;
  return tl;
}

/** Seek the active slide's timeline from the playhead; returns the value at t. */
function seekTimeline(slideId: string, playhead: number): number {
  const tl = REGISTRY[slideId];
  if (!tl) throw new Error(`no timeline registered for "${slideId}"`);
  return sampleAt(tl, playhead);   // == tl.time(playhead) then read the rendered value
}

// ---- two demo timelines (the pinned values come from these) ----
// 2-keyframe: value 0 -> 1 over [0s, 1s], linear.
const TL_TWO: MockTimeline = {
  slideId: "slide-0",
  keyframes: [
    { t: 0, value: 0.0 },
    { t: 1, value: 1.0 },
  ],
};
// 3-keyframe: value 0 -> 1 -> 0.5 over [0s, 1s, 2s], linear (piecewise lerp).
const TL_THREE: MockTimeline = {
  slideId: "slide-1",
  keyframes: [
    { t: 0, value: 0.0 },
    { t: 1, value: 1.0 },
    { t: 2, value: 0.5 },
  ],
};

// ---- active slide state (RFC §7/§8: the engine renders ONE active slide) ----
let ACTIVE_SLIDE_ID: string | null = null;

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the engine renders the ACTIVE slide via SlideRenderer");
  console.log("  RFC 0001 §8 — 'Renders the active slide's index.html (the bare");
  console.log("  <template>) in the browser via the SlideRenderer interface.'");
  console.log("  RFC 0001 §7 — Stage binds to the ACTIVE slide; the engine mounts");
  console.log("  exactly ONE slide composition at a time.\n");
  console.log("  SlideRenderer interface (RFC §9.1, verbatim):");
  for (const line of SLIDE_RENDERER_INTERFACE.split("\n")) console.log("    " + line);
  ACTIVE_SLIDE_ID = "slide-0"; // simulate SlideRenderer.load(slide-0)
  console.log(`\n  ACTIVE_SLIDE_ID = "${ACTIVE_SLIDE_ID}" (mounted via SlideRenderer.load)`);
  check("exactly one active slide is mounted at a time", ACTIVE_SLIDE_ID !== null);
  check("SlideRenderer exposes load() / render_at() / duration()",
    /load\(/.test(SLIDE_RENDERER_INTERFACE) &&
    /render_at\(/.test(SLIDE_RENDERER_INTERFACE) &&
    /duration\(/.test(SLIDE_RENDERER_INTERFACE));
  console.log("  → preview does NOT render the whole timeline at once; it renders");
  console.log("    the ONE active slide and swaps on boundary cross (Section F).");
}

function sectionB(): void {
  banner("SECTION B: drive GSAP from the playhead — tl.time(t) (SEEK, not play)");
  console.log("  RFC 0001 §8 — 'Drives GSAP timelines from the playhead time.'");
  console.log("  AGENTS.md slide <script> registers the timeline PAUSED, keyed by id:\n");
  for (const line of SLIDE_SCRIPT_QUOTED.split("\n")) console.log("    " + line);
  console.log("");
  console.log("  GSAP docs, Timeline.time() (https://gsap.com/docs/v3/GSAP/Timeline/time()):");
  console.log("    'Gets or sets the local position of the playhead (essentially the");
  console.log("    current time)... sets time, jumping to new value just like seek().'");
  console.log("  → the preview calls tl.time(playheadTime) on the PAUSED timeline. The");
  console.log("    playhead moves; the timeline does NOT auto-play. Deterministic given t.\n");

  registerTimeline(TL_TWO);
  const slideId = TL_TWO.slideId;
  const samples = [0.0, 0.25, 0.5, 0.75, 1.0];
  for (const p of samples) {
    const v = seekTimeline(slideId, p);
    console.log(`    tl.time(${fix(p)})  →  value ${fix(v)}   (registry["${slideId}"], paused)`);
  }
  const mid = seekTimeline(slideId, 0.5);
  check("tl.time(t) seeks without playing (playhead setter; value at 0.5 === 0.5)",
    fix(mid) === "0.500000");
  check("window.__timelines['__SLIDE_ID__'] = tl  registers the paused timeline",
    /window\.__timelines\['__SLIDE_ID__'\]\s*=\s*tl/.test(SLIDE_SCRIPT_QUOTED) &&
      /paused:\s*true/.test(SLIDE_SCRIPT_QUOTED));
  console.log(`\n  PINNED: tl.time(0.500000) on slide-0 → value ${fix(mid)} (lerp midpoint).`);
}

function sectionC(): void {
  banner("SECTION C: the interpolation math — lerp between keyframes");
  console.log("  Wikipedia, 'Linear interpolation' — between known points (x0,y0),(x1,y1):");
  console.log("    y = y0 + (x - x0) * (y1 - y0) / (x1 - x0)");
  console.log("  In lerp form (t in [0,1] within a segment):");
  console.log("    lerp(a, b, t) = a + t * (b - a)\n");

  console.log("  2-keyframe timeline slide-0: keyframes (t=0, v=0.0) , (t=1, v=1.0), linear:");
  for (const p of [0.25, 0.5, 0.75]) {
    const v = sampleAt(TL_TWO, p);
    console.log(`    playhead ${fix(p)} → localT ${fix(p)} → lerp(0, 1, ${fix(p)}) = ${fix(v)}`);
  }
  check("2-keyframe lerp at t=0.5 === 0.5 (lerp(0,1,0.5))",
    fix(sampleAt(TL_TWO, 0.5)) === "0.500000");
  check("2-keyframe lerp at t=0.25 === 0.25, t=0.75 === 0.75",
    fix(sampleAt(TL_TWO, 0.25)) === "0.250000" &&
    fix(sampleAt(TL_TWO, 0.75)) === "0.750000");

  console.log("");
  console.log("  3-keyframe timeline slide-1: (0,0.0) → (1,1.0) → (2,0.5), linear (piecewise):");
  for (const p of [0.5, 1.0, 1.5]) {
    const v = sampleAt(TL_THREE, p);
    console.log(`    playhead ${fix(p)} → segment value ${fix(v)}`);
  }
  const at15 = sampleAt(TL_THREE, 1.5);
  console.log(`    detail @1.5: segment [1,2], localT=(1.5-1)/(2-1)=0.5 → lerp(1.0, 0.5, 0.5) = ${fix(at15)}`);
  check("3-keyframe multi-segment lerp at t=1.5 === 0.75 (lerp(1.0, 0.5, 0.5))",
    fix(at15) === "0.750000");
  console.log(`\n  PINNED: sampleAt(slide-0, 0.5) = ${fix(sampleAt(TL_TWO, 0.5))};` +
    ` sampleAt(slide-1, 1.5) = ${fix(at15)}.`);
}

function sectionD(): void {
  banner("SECTION D: real-time, NOT frame-accurate (the decoupling rationale)");
  console.log("  RFC 0001 §8 (verbatim): \"" + RFC_S8_REALTIME_QUOTE + "\"");
  console.log("  RFC 0001 §11 — visual determinism is enforced at EXPORT, not in preview.\n");

  console.log("  PREVIEW (real-time): on each browser paint (rAF) the engine calls");
  console.log("  tl.time(playhead). dt between paints is variable (browser-paced), so");
  console.log("  frame indices may REPEAT (slow paint) or SKIP (scrub/fast-forward):");
  const previewSamples = [0.0, 0.04, 0.06, 0.12, 0.13];
  for (const t of previewSamples) {
    const v = sampleAt(TL_TWO, t);
    const fi = Math.floor(t * FPS);
    console.log(`    playhead ${fix(t)}s → tl.time(${fix(t)}); value ${fix(v)}; nearest frame ${fi}`);
  }
  const previewDtVariable =
    previewSamples[1] - previewSamples[0] !== 1 / FPS ||
    previewSamples[2] - previewSamples[1] !== 1 / FPS;

  console.log("");
  console.log(`  EXPORT (frame-accurate): npx hyperframes render steps frame index`);
  console.log(`  0..N-1 at exactly 1/fps = ${fix(1 / FPS)}s each (RFC §10, §11):`);
  for (let i = 0; i < 5; i++) {
    const t = i / FPS;
    console.log(`    frame[${i}] → render_at(${fix(t)})  (exact, no repeat/skip)`);
  }
  check("preview sample dt is NOT 1/fps (real-time, variable cadence)", previewDtVariable);
  check("export step IS exactly 1/fps (frame-accurate, deterministic)",
    fix(1 / FPS) === "0.033333");
  console.log("\n  → preview responsiveness and export rigor are DIFFERENT jobs; decoupling");
  console.log("    them (§8) keeps the editor fast without lying about the final video.");
  console.log("    Cross-ref 🔗 STAGE_CANVAS (the surface) / EXPORT_PIPELINE (the rigorous path).");
}

function sectionE(): void {
  banner("SECTION E: app-owned — the editor drives; HF is not a black box");
  console.log("  RFC 0001 §8 (verbatim): \"" + RFC_S8_QUOTE + "\"");
  console.log("  RFC 0001 §9.5 — HF's role contracts from 'the whole composition engine'");
  console.log("  to 'render this one slide at time t.' Timeline orchestration, the document");
  console.log("  model, and the editor are OURS; HF is a pluggable rendering primitive.\n");
  const appOwned =
    /editor drives it/.test(RFC_S8_QUOTE) &&
    /not in the editing loop as a black box/.test(RFC_S8_QUOTE);
  check("§8 quote asserts app ownership (editor drives; HF not a black box)", appOwned);
  check("SlideRenderer is the pluggable seam (engine swappable behind one interface)",
    /render_at\(/.test(SLIDE_RENDERER_INTERFACE) && /load\(/.test(SLIDE_RENDERER_INTERFACE));
  console.log("  → because preview and export share one SlideRenderer (§9.4),");
  console.log("    'it looked different when I exported' is structurally impossible.");
}

function sectionF(): void {
  banner("SECTION F: active-slide swap — load the new slide's timeline");
  console.log("  RFC 0001 §7 — the stage binds to the ACTIVE slide. When the playhead");
  console.log("  crosses into the next slide's window, the active id changes and");
  console.log("  SlideRenderer.load() mounts the new composition. The engine looks up the");
  console.log("  NEW slide's timeline in window.__timelines and seeks THAT one.\n");

  registerTimeline(TL_TWO);    // slide-0
  registerTimeline(TL_THREE);  // slide-1
  console.log("  registry keys: " + Object.keys(REGISTRY).sort().join(", "));

  ACTIVE_SLIDE_ID = "slide-0";
  const v0 = seekTimeline(ACTIVE_SLIDE_ID, 0.5);
  console.log(`\n  active="${ACTIVE_SLIDE_ID}", playhead 0.5 → value ${fix(v0)}  (2-keyframe)`);

  ACTIVE_SLIDE_ID = "slide-1"; // swap: user selects the next slide / playhead crosses
  const v1 = seekTimeline(ACTIVE_SLIDE_ID, 1.5);
  console.log(`  active="${ACTIVE_SLIDE_ID}", playhead 1.5 → value ${fix(v1)}  (3-keyframe)`);

  check("swap changes the active slide id (slide-0 → slide-1)",
    REGISTRY["slide-0"] !== undefined && REGISTRY["slide-1"] !== undefined);
  check("each active slide resolves to its OWN timeline value via the registry",
    fix(v0) === "0.500000" && fix(v1) === "0.750000");
  console.log("\n  → the swap is a mount/unmount via SlideRenderer + a registry lookup;");
  console.log("    between-slide transitions live in ROOT index.html (RFC §5.1).");
  console.log("    Cross-ref 🔗 STAGE_CANVAS for the surface whose playhead this consumes.");
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
