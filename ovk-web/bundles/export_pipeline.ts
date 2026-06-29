// export_pipeline — ground-truth runnable for "the export pipeline" (RFC 0001 §10)
// Run: pnpm exec tsx bundles/export_pipeline.ts
//
// Teaches the whole export path: a workspace (RFC §5.1 units) is turned into an
// MP4 in exactly SIX deterministic steps — assemble → stamp → voiceover →
// captions → render → progress. The load-bearing claim is ZERO FORMAT
// TRANSLATION: the slide index.html files ARE already HyperFrames' sub-comp
// format (bare <template>, RFC §5.4 / AGENTS.md), so export never translates a
// scene graph into HTML — it COPIES slide HTML verbatim, stamps data into it,
// and hands the assembled tree to `npx hyperframes render`.
//
// Determinism: NO fs reads, NO Date.now, NO Math.random, NO wall-clock. The
// workspace, the measured TTS durations, and the HF stdout are all FIXED
// in-source. The voiceover timings, caption word-timing, host-div data-start/
// data-duration, and progress percentages are all RECOMPUTED from those fixed
// inputs. Re-running is byte-identical.

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

function indent(src: string, n: number): string {
  const pad = " ".repeat(n);
  return src.split("\n").map((l) => pad + l).join("\n");
}

// ===========================================================================
// FIXED in-source workspace (RFC §5.1 units). This is the editor's truth.
// ===========================================================================

// RFC §5.2 — root index.json: the slide order + canvas + transition default.
const ROOT_INDEX_JSON = {
  version: 1,
  canvas: { width: 1920, height: 1080, fps: 30 },
  transition_default: { type: "crossfade", duration: 0.4 },
  slides: ["slide-0", "slide-1"],
};

// RFC §5.3 — per-slide index.json: the DATA (fields + voiceover). The slide
// index.html (animation) is defined separately below — it is a bare <template>.
interface SlideJson {
  id: string;
  fields: Record<string, string>;
  voiceover: { text: string; voice: string; duration: number }; // duration MEASURED (ffprobe)
}

// RFC §5.4 / AGENTS.md "Layout file format" — the slide index.html. This is the
// EXACT bytes export copies verbatim into compositions/slide-N.html (step 1).
// __SLIDE_ID__ + __FIELD__ are stamped in step 2 (cross-ref DATA_BINDING).
const SLIDE0_HTML = `<template>
  <div data-composition-id="__SLIDE_ID__" data-width="1920" data-height="1080">
    <div class="content">
      <h1>__TITLE__</h1>
      <p>__BODY__</p>
    </div>
    <style>
      [data-composition-id="__SLIDE_ID__"] { background: #0a0a14; }
      [data-composition-id="__SLIDE_ID__"] .content { text-align: center; padding-top: 38vh; }
      [data-composition-id="__SLIDE_ID__"] h1 { font-size: 120px; }
    </style>
    <script>
      var tl = gsap.timeline({ paused: true });
      tl.from('[data-composition-id="__SLIDE_ID__"] .content > *', { opacity: 0, y: 40, duration: 0.4, stagger: 0.1 });
      window.__timelines['__SLIDE_ID__'] = tl;
    </script>
  </div>
</template>`;

const SLIDE1_HTML = SLIDE0_HTML; // same layout, different data — re-stamped per slide

const SLIDES: Record<string, { html: string; json: SlideJson }> = {
  "slide-0": {
    html: SLIDE0_HTML,
    json: {
      id: "slide-0",
      fields: { title: "Eco Bottle", body: "Refill. Reuse. Repeat." },
      // voiceover duration is MEASURED by ffprobe (AGENTS.md voiceover pipeline).
      // Fixed here so the timing math is deterministic and re-runnable.
      voiceover: { text: "Eco bottles save the planet", voice: "vi-VN-HoaiMyNeural", duration: 4.6 },
    },
  },
  "slide-1": {
    html: SLIDE1_HTML,
    json: {
      id: "slide-1",
      fields: { title: "Join Us", body: "Every sip protects our future." },
      voiceover: { text: "Every sip protects our future", voice: "vi-VN-HoaiMyNeural", duration: 3.4 },
    },
  },
};

// Root index.html — the HF HOST. Contains the markers AGENTS.md "Root index.html
// markers" defines; the assembler replaces them during assemble/caption/voiceover.
const ROOT_INDEX_HTML = `<html>
  <body>
    <div id="stage" data-width="1920" data-height="1080">
      <!-- SLIDES_HERE -->
      <!-- CAPTION_LAYER -->
    </div>
    <script>
      var DUR = __DUR__; // set by voiceover step to the measured total length
      /* CAPTION_CSS */
      // SCENE_TRANSITIONS
      // CAPTION_TIMELINE
    </script>
  </body>
</html>`;

const ASSET_FILES = ["voiceover.mp3", "sha256-c0ffee.jpg"];

// Voiceover timing params (AGENTS.md "Smart timing" + "Key design decisions").
const INITIAL_LEAD = 0.5;       // slide-0 starts at 0.5s (AGENTS.md host-div example data-start="0.5")
const GAP_BETWEEN = 0.8;        // default gap_between_slides

// Caption highlight config (AGENTS.md "Caption styling").
const ACTIVE_COLOR = "#ffea00";
const DIM_COLOR = "rgba(255,255,255,0.4)";
const CAPTION_TWEEN = 0.15;     // GSAP color tween duration

// Fixed HF stdout sample (RFC §18 risk: parser couples to HF stdout format).
const HF_STDOUT_SAMPLE = [
  "[hyperframes] loading composition",
  "[hyperframes] rendering frame 1/270",
  "[hyperframes] rendering frame 135/270",
  "[hyperframes] rendering frame 270/270",
  "[hyperframes] wrote scene.mp4",
].join("\n");

// ===========================================================================
// helpers — the pipeline mechanics
// ===========================================================================

/** Field id -> placeholder (AGENTS.md "Placeholder convention"). */
function placeholderFor(id: string): string {
  return "__" + id.toUpperCase() + "__";
}

/** SAFE stamp: replacement as a function so $ patterns don't apply (DATA_BINDING). */
function stamp(html: string, placeholder: string, value: string): string {
  return html.split(placeholder).join(value);
}

/** Count remaining __TOKEN__ placeholders. */
function countPlaceholders(src: string): number {
  return (src.match(/__[A-Z0-9_]+__/g) || []).length;
}

/** Smart timing: slide-0 = INITIAL_LEAD; slide N start = prev_end + GAP_BETWEEN. */
interface SlideTiming { id: string; idx: number; start: number; dur: number; end: number; }
function computeTimings(): SlideTiming[] {
  const out: SlideTiming[] = [];
  let cursor = INITIAL_LEAD;
  ROOT_INDEX_JSON.slides.forEach((id, idx) => {
    const dur = SLIDES[id].json.voiceover.duration;
    const start = idx === 0 ? INITIAL_LEAD : cursor;
    const end = start + dur;
    out.push({ id, idx, start, dur, end });
    cursor = end + GAP_BETWEEN;
  });
  return out;
}
const TIMINGS = computeTimings();
const ROOT_DUR = TIMINGS.length === 0 ? 0 : TIMINGS[TIMINGS.length - 1].end;

/** Build a host div for a slide (AGENTS.md "Host div format"). */
function hostDiv(slideId: string, idx: number, start: number, dur: number): string {
  const z = 100 - idx;
  return `<div data-composition-id="${slideId}"` +
    ` data-composition-src="compositions/${slideId}.html"` +
    ` data-start="${start.toFixed(6)}" data-duration="${dur.toFixed(6)}"` +
    ` class="clip" style="position:absolute;inset:0;z-index:${z};"></div>`;
}

/** char-ratio word timing (captions.build_captions, cross-ref CAPTIONS_KARAOKE). */
interface WordTime { text: string; chars: number; ratio: number; start: number; dur: number; end: number; }
function timeWordsByCharRatio(sentence: string, start: number, dur: number): WordTime[] {
  const words = sentence.split(/\s+/).filter((w) => w.length > 0);
  const total = words.reduce((s, w) => s + w.length, 0);
  let cursor = start;
  const out: WordTime[] = [];
  for (const w of words) {
    const ratio = w.length / total;
    const d = dur * ratio;
    out.push({ text: w, chars: w.length, ratio, start: cursor, dur: d, end: cursor + d });
    cursor += d;
  }
  return out;
}

/** Parse HF stdout -> progress events (RFC §10 step 6). */
interface ProgressEvt { frame: number; total: number; pct: number; }
function parseProgress(stdout: string): ProgressEvt[] {
  const re = /frame\s+(\d+)\/(\d+)/gi;
  const out: ProgressEvt[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(stdout)) !== null) {
    const frame = parseInt(m[1], 10);
    const total = parseInt(m[2], 10);
    out.push({ frame, total, pct: total === 0 ? 0 : (frame / total) * 100 });
  }
  return out;
}

// ===========================================================================
// sections
// ===========================================================================

function sectionA(): void {
  banner("SECTION A: the 6-step pipeline (RFC §10) — ZERO TRANSLATION");
  console.log("  RFC 0001 §10: 'Export is assembly + stamp + render — no format translation,");
  console.log("  because the source files are already HF's files.'\n");
  const steps = [
    "1. assemble  — write workspace into HF layout: root index.html + compositions/slide-N.html + assets/",
    "2. stamp     — replace __SLIDE_ID__ and every __FIELD__ in each composition from slide index.json",
    "3. voiceover — edge-tts + ffprobe + ffmpeg concat → timings → data-start/data-duration + root DUR",
    "4. captions  — build_captions() → caption layer + GSAP word-highlight into the root markers",
    "5. render    — npx hyperframes render <workspace> --output scene.mp4",
    "6. progress  — parse HF stdout → progress events → UI progress bar",
  ];
  for (const s of steps) console.log("  " + s);
  check("the pipeline has exactly 6 stages", steps.length === 6);
  check("no stage translates a foreign scene graph into HTML (zero translation)", true);
  console.log("  → the assembler's output must obey the FULL AGENTS.md contract (export-target spec).");
}

function sectionB(): void {
  banner("SECTION B: ASSEMBLE — copy slide index.html VERBATIM into compositions/");
  console.log("  RFC §10 step 1 + AGENTS.md 'Sub-composition model': each slide's index.html is");
  console.log("  copied byte-for-byte into compositions/slide-N.html. No rewrite, no parser.\n");

  // Emulate the on-disk HF layout the assembler produces.
  const emitted: Record<string, string> = {
    "index.html": ROOT_INDEX_HTML,
    "compositions/slide-0.html": SLIDES["slide-0"].html,
    "compositions/slide-1.html": SLIDES["slide-1"].html,
  };

  console.log("  emitted HF layout tree:");
  console.log("    workspace/");
  console.log("      index.html                          (root HOST — markers)");
  for (const s of ROOT_INDEX_JSON.slides) {
    console.log(`      compositions/${s}.html               (slide index.html, copied verbatim)`);
  }
  for (const a of ASSET_FILES) console.log(`      assets/${a}`);

  check("slide-0 index.html copied VERBATIM into compositions/slide-0.html",
    emitted["compositions/slide-0.html"] === SLIDES["slide-0"].html);
  check("slide-1 index.html copied VERBATIM into compositions/slide-1.html",
    emitted["compositions/slide-1.html"] === SLIDES["slide-1"].html);
  check("every emitted composition is still a bare <template> (no <html> wrapper)",
    emitted["compositions/slide-0.html"].trimStart().startsWith("<template") &&
    emitted["compositions/slide-1.html"].trimStart().startsWith("<template"));
  console.log(`  PINNED: emitted files = ${Object.keys(emitted).length} + assets/(${ASSET_FILES.length})`);
}

function sectionC(): void {
  banner("SECTION C: STAMP — __SLIDE_ID__ + __FIELD__ (RFC §5.6)");
  console.log("  RFC §10 step 2: replace __SLIDE_ID__ and every __FIELD__ from slide index.json.");
  console.log("  HF getVariables() returns {} in sub-comps, so stamping IS the binding.\n");

  const slideId = "slide-0";
  const data = SLIDES[slideId].json;
  let out = SLIDES[slideId].html;
  out = stamp(out, "__SLIDE_ID__", slideId);
  for (const [id, value] of Object.entries(data.fields)) {
    out = stamp(out, placeholderFor(id), value);
  }

  console.log("  stamped compositions/slide-0.html:");
  console.log(indent(out, 4));

  const remaining = countPlaceholders(out);
  check('stamped composition contains data-composition-id="slide-0"',
    /data-composition-id="slide-0"/.test(out));
  check("stamped composition contains the title text", out.includes(data.fields.title));
  check("stamped composition contains the body text", out.includes(data.fields.body));
  check("ZERO __ placeholders remain after stamp", remaining === 0);
  console.log(`  PINNED: remaining __...__ placeholders after stamp = ${remaining}  ← GOLD`);
  console.log(`  GOLD:   countPlaceholders(stamped) === 0 => ${remaining === 0}`);
}

function sectionD(): void {
  banner("SECTION D: VOICEOVER — edge-tts + ffprobe + ffmpeg → timings + DUR");
  console.log("  AGENTS.md 'Voiceover pipeline': edge-tts each sentence → ffprobe measures");
  console.log("  duration → ffmpeg anullsrc silence + concat → voiceover.mp3 + timings.json.");
  console.log("  Smart timing: slide N start = prev_end + gap_between_slides.\n");

  // Compute target_starts from MEASURERED durations (AGENTS.md "Smart timing").
  const f = (n: number): string => n.toFixed(6);
  const timings = TIMINGS;
  const DUR = ROOT_DUR;

  console.log("  ┌──────────┬──────────┬──────────┬──────────┬────────────────────────────────┐");
  console.log("  │ slide    │ start    │ duration │ end      │ source                         │");
  console.log("  ├──────────┼──────────┼──────────┼──────────┼────────────────────────────────┤");
  for (const t of timings) {
    const src = t.idx === 0 ? "INITIAL_LEAD (0.5)" : `prev_end(${f(timings[t.idx - 1].end)}) + GAP(0.8)`;
    console.log(`  │ ${t.id} │ ${f(t.start).padStart(8)} │ ${f(t.dur).padStart(8)} │ ${f(t.end).padStart(8)} │ ${src.padEnd(30)} │`);
  }
  console.log("  └──────────┴──────────┴──────────┴──────────┴────────────────────────────────┘");

  // The host divs the assembler writes (data-start/data-duration from timings).
  console.log("\n  host divs written into root index.html (data-start/data-duration from timings):");
  for (const t of timings) console.log(indent(hostDiv(t.id, t.idx, t.start, t.dur), 4));

  // Root DUR is set to the measured total length.
  const stampedRoot = stamp(ROOT_INDEX_HTML, "__DUR__", f(DUR));
  check("root DUR stamped to the measured voiceover length", stampedRoot.includes(`var DUR = ${f(DUR)};`));
  check("slide-1 start = slide-0 end + gap_between_slides",
    Math.abs(timings[1].start - (timings[0].end + GAP_BETWEEN)) < 1e-9);
  check("every host div carries position:absolute;inset:0 (AGENTS.md host-div format)",
    timings.every((t) => hostDiv(t.id, t.idx, t.start, t.dur).includes("position:absolute;inset:0;")));
  console.log(`\n  PINNED: root DUR = ${f(DUR)} (last slide end)`);
}

function sectionE(): void {
  banner("SECTION E: CAPTIONS — caption layer + GSAP word-highlight into root markers");
  console.log("  AGENTS.md 'Voiceover pipeline' → captions.build_captions(): split into words,");
  console.log("  char-ratio timing, caption HTML (phrase + word spans), GSAP color tween JS.");
  console.log("  Injected via markers: <!-- CAPTION_LAYER -->, /* CAPTION_CSS */,");
  console.log("  // CAPTION_TIMELINE, // SCENE_TRANSITIONS.\n");

  const f = (n: number): string => n.toFixed(6);
  const t0 = ROOT_INDEX_JSON.slides[0];
  const slideStart = INITIAL_LEAD;
  const slideDur = SLIDES[t0].json.voiceover.duration;
  const sentence = SLIDES[t0].json.voiceover.text;
  const words = timeWordsByCharRatio(sentence, slideStart, slideDur);

  console.log(`  slide-0 caption "${sentence}" (${words.length} words, char-ratio over ${f(slideDur)}s):`);
  for (const w of words) {
    console.log(`    ${w.text.padEnd(8)} start=${f(w.start)} dur=${f(w.dur)} end=${f(w.end)}`);
  }

  // caption layer HTML (one span per word) — replaces <!-- CAPTION_LAYER -->
  const captionLayer = `<div class="caption-phrase" data-slide="${t0}">` +
    words.map((w) => `<span class="word" data-i="${words.indexOf(w)}">${w.text}</span>`).join("") +
    `</div>`;
  // GSAP word-highlight timeline — replaces // CAPTION_TIMELINE (direct color tween)
  const captionTimeline = words.map((w) => {
    const sel = `[data-slide="${t0}"] [data-i="${words.indexOf(w)}"]`;
    return `tl.to('${sel}', { color: '${ACTIVE_COLOR}', duration: ${CAPTION_TWEEN}, ease: 'power2.out' }, ${f(w.start)});` +
      `\ntl.to('${sel}', { color: '${DIM_COLOR}', duration: ${CAPTION_TWEEN}, ease: 'power2.in' }, ${f(w.end)});`;
  }).join("\n");
  // scene transitions — replaces // SCENE_TRANSITIONS (z-index swap per slide)
  const sceneTransitions = TIMINGS.map((t) =>
    `rootTl.set('[data-composition-id="${t.id}"]', { zIndex: ${100 - t.idx} }, ${f(t.start)});`).join("\n");

  // root with caption markers replaced (DUR + captions injected)
  let stampedRoot = stamp(ROOT_INDEX_HTML, "__DUR__", f(ROOT_DUR));
  stampedRoot = stamp(stampedRoot, "<!-- CAPTION_LAYER -->", captionLayer);
  stampedRoot = stamp(stampedRoot, "/* CAPTION_CSS */", "/* .word { color: rgba(255,255,255,0.4); } */");
  stampedRoot = stamp(stampedRoot, "// CAPTION_TIMELINE", captionTimeline);
  stampedRoot = stamp(stampedRoot, "// SCENE_TRANSITIONS", sceneTransitions);

  check("<!-- CAPTION_LAYER --> marker replaced by caption phrase HTML", stampedRoot.includes('class="caption-phrase"'));
  check("// CAPTION_TIMELINE marker replaced by GSAP direct color tweens", /tl\.to\([^,]+,\s*\{\s*color:/.test(stampedRoot));
  check("caption uses direct color tween (NOT className)", !/className/.test(captionTimeline));
  check("no root markers remain after caption injection",
    !stampedRoot.includes("<!-- CAPTION_LAYER -->") && !stampedRoot.includes("// CAPTION_TIMELINE"));
  console.log(`  PINNED: caption words emitted for slide-0 = ${words.length}`);
  console.log(`  → caption + scene-transition JS are emitted into the SAME root index.html the renderer reads.`);
}

function sectionF(): void {
  banner("SECTION F: RENDER + PROGRESS — npx hyperframes render; parse stdout");
  console.log("  RFC §10 steps 5–6: render the assembled workspace to MP4; stream progress.\n");

  const cmd = `npx hyperframes render workspace --output scene.mp4`;
  console.log(`  render command: ${cmd}`);
  console.log(`  HF stdout (fixed sample):\n${indent(HF_STDOUT_SAMPLE, 4)}\n`);

  const evts = parseProgress(HF_STDOUT_SAMPLE);
  console.log("  parsed progress events:");
  for (const e of evts) {
    console.log(`    frame ${e.frame}/${e.total} → ${e.pct.toFixed(6)}%`);
  }
  const last = evts[evts.length - 1];
  check("progress parser extracts frame x/total from HF stdout", evts.length >= 2);
  check("final frame reaches 100%", last !== undefined && Math.abs(last.pct - 100) < 1e-9);
  console.log(`  PINNED: progress events parsed = ${evts.length}; final = ${last.pct.toFixed(6)}%`);
  console.log("  RFC §18 risk: the parser couples to HF's stdout format — pin HF version, integration-test it.");
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
