// captions_karaoke — ground-truth runnable for "word-level karaoke captions"
//   (AGENTS.md "Caption styling — CRITICAL RULES"; RFC 0001 §5.2, §7, §10)
// Run: pnpm exec tsx bundles/captions_karaoke.ts
//
// Teaches the karaoke-caption pipeline whose export contract is FIXED by
// AGENTS.md "Caption styling — CRITICAL RULES": each word of the voiceover is
// timed by CHAR RATIO and highlighted by a GSAP DIRECT COLOR TWEEN. The whole
// point of this bundle is the BANNED patterns — NEVER animate
// transform/scale/font-size/text-shadow on `.word--active`, and NEVER use
// GSAP's `className` toggle. Determinism hard rules apply
// (HOW_TO_RESEARCH.md STEP 3): no Date.now/Math.random/wall-clock/FS; floats
// printed at fixed precision `.toFixed(6)`.

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

/** Fixed-precision float formatter (deterministic output). */
function fix(n: number): string {
  return n.toFixed(6);
}

// ===========================================================================
// AGENTS.md verbatim contracts (the source of truth this runnable enforces)
// ===========================================================================

// AGENTS.md "The correct caption pattern" — the GSAP DIRECT COLOR tween:
//   tl.to(wordSelector, { color: '#ffea00', duration: 0.15, ease: 'power2.out' }, wordStart);
//   tl.to(wordSelector, { color: 'rgba(255,255,255,0.4)', duration: 0.15, ease: 'power2.in' }, wordEnd);
const ACTIVE_COLOR = "#ffea00"; // AGENTS.md `.word--active` color (yellow)
const DIM_COLOR = "rgba(255,255,255,0.4)"; // AGENTS.md base `.word` color (dim white)
const EMPHASIS_COLOR = "#4ade80"; // AGENTS.md `.word--emphasis` (STATIC — never animated)
const TWEEN_DUR = 0.15; // AGENTS.md highlight tween duration (seconds)

// RFC 0001 §5.2 — `theme.caption_style` enum (the 4 caption palettes).
const CAPTION_STYLES = ["highlight", "neon", "editorial", "eco-green"] as const;
type CaptionStyle = (typeof CAPTION_STYLES)[number];

// RFC 0001 §7 / AGENTS.md "Root index.html markers" — where captions are injected:
//   <!-- CAPTION_LAYER -->  → caption HTML (phrase + word spans)
//   /* CAPTION_CSS */        → caption CSS (selected by theme.caption_style)
//   // CAPTION_TIMELINE     → GSAP word-by-word highlight JS
const MARKERS = {
  layer: "<!-- CAPTION_LAYER -->",
  css: "/* CAPTION_CSS */",
  timeline: "// CAPTION_TIMELINE",
} as const;

// ===========================================================================
// Banned-pattern detectors — THE HEART OF THIS BUNDLE
// ===========================================================================

// AGENTS.md "What NOT to do" — these tokens, inside a `.word--active` rule,
// cause visual layout shift ("jumping"). They are BANNED on the active state.
// (transform/scale are legal ELSEWHERE — e.g. host-div canvas scaling in
// stage_canvas — so we scope the lint to `.word--active` blocks.)
const BANNED_CSS_TOKENS = ["transform", "scale(", "font-size", "text-shadow"] as const;

interface LintResult {
  ok: boolean;
  hits: string[];
}

/** Scan a CSS string; flag banned tokens ONLY inside `.word--active { ... }`
 *  blocks. Returns ok=false if any banned token is found there. */
function lintCaptionCSS(css: string): LintResult {
  const hits: string[] = [];
  const blockRe = /\.word--active\s*\{([^}]*)\}/g;
  let m: RegExpExecArray | null;
  while ((m = blockRe.exec(css)) !== null) {
    const body = m[1];
    for (const tok of BANNED_CSS_TOKENS) {
      if (body.includes(tok)) hits.push(`.word--active contains "${tok}"`);
    }
  }
  return { ok: hits.length === 0, hits };
}

/** Flag the banned GSAP `className` toggle in caption timeline JS.
 *  AGENTS.md "Why className toggle is banned": the className plugin reads
 *  computed styles before/after and tweens the diff — it snaps, picks up
 *  unintended property changes, and fights the CSS `transition` on the element. */
function lintCaptionJS(js: string): LintResult {
  const hits: string[] = [];
  if (/\bclassName\s*:/.test(js)) {
    hits.push("className tween — use a direct property tween (color/opacity) instead");
  }
  return { ok: hits.length === 0, hits };
}

/** Validate a caption_style value against the RFC §5.2 enum. */
function isValidCaptionStyle(s: string): s is CaptionStyle {
  return (CAPTION_STYLES as readonly string[]).includes(s);
}

// ===========================================================================
// Word splitting + per-word timing (CHAR RATIO) — AGENTS.md pipeline step 2
// ===========================================================================

interface WordTiming {
  i: number;
  text: string;
  chars: number; // character count, ignoring spaces
  ratio: number; // chars / totalChars  (the ratios sum to 1.0)
  start: number; // seconds, caption-timeline time
  dur: number; // seconds
  end: number; // seconds = start + dur
}

/** AGENTS.md voiceover pipeline → `captions.build_captions()` step 2:
 *  "Estimate per-word timing by char ratio".
 *    word i duration = sentenceDur * (wordChars / totalChars)
 *    word i start    = sentenceStart + cumulativePreviousDurations
 *  The ratios are an exact partition of 1.0, so durations sum to sentenceDur. */
function timeWordsByCharRatio(
  sentence: string,
  sentenceStart: number,
  sentenceDur: number,
): WordTiming[] {
  const words = sentence.split(/\s+/).filter((w) => w.length > 0);
  const totalChars = words.reduce((s, w) => s + w.length, 0);
  let cursor = sentenceStart;
  return words.map((w, i) => {
    const ratio = w.length / totalChars;
    const dur = sentenceDur * ratio;
    const t: WordTiming = {
      i,
      text: w,
      chars: w.length,
      ratio,
      start: cursor,
      dur,
      end: cursor + dur,
    };
    cursor += dur;
    return t;
  });
}

// ===========================================================================
// Caption HTML + GSAP timeline generators (the CORRECT output)
// ===========================================================================

/** `<!-- CAPTION_LAYER -->` → a phrase of word spans. Emphasis is a STATIC
 *  class (`.word--emphasis`) — it is colored once, never animated. */
function buildCaptionHtml(timings: WordTiming[], emphasisIdx: number[] = []): string {
  const spans = timings.map((t) => {
    const cls = emphasisIdx.includes(t.i) ? "word word--emphasis" : "word";
    return `  <span class="${cls}" data-i="${t.i}">${t.text}</span>`;
  });
  return `<div class="caption-phrase">\n${spans.join("\n")}\n</div>`;
}

/** `// CAPTION_TIMELINE` → GSAP DIRECT COLOR TWEEN per word (AGENTS.md correct
 *  pattern). Two tweens per word: color → ACTIVE at wordStart, color → DIM at
 *  wordEnd. NO transform, NO className. */
function buildCaptionTimelineJs(timings: WordTiming[]): string {
  const lines: string[] = ["var tl = gsap.timeline({ paused: true });"];
  for (const t of timings) {
    const sel = `'[data-i="${t.i}"]'`;
    lines.push(
      `tl.to(${sel}, { color: '${ACTIVE_COLOR}', duration: ${fix(TWEEN_DUR)}, ease: 'power2.out' }, ${fix(t.start)});`,
    );
    lines.push(
      `tl.to(${sel}, { color: '${DIM_COLOR}', duration: ${fix(TWEEN_DUR)}, ease: 'power2.in' }, ${fix(t.end)});`,
    );
  }
  return lines.join("\n");
}

// ===========================================================================
// PINNED sample — "Eco bottles save the planet" (5 words, 23 chars, 4.6s)
// ===========================================================================

const PINNED_SENTENCE = "Eco bottles save the planet";
const PINNED_SENTENCE_START = 0.0; // caption timeline begins at 0; the slide's
//   data-start offset is applied separately by SCENE_TRANSITIONS (out of scope).
const PINNED_SENTENCE_DUR = 4.6; // seconds (measured voiceover duration)

// ===========================================================================
// Sections
// ===========================================================================

function sectionA(): void {
  banner("SECTION A: word splitting + per-word timing (char ratio)");
  console.log("  AGENTS.md captions.build_captions() step 2: \"Estimate per-word timing by char ratio\"\n");
  const timings = timeWordsByCharRatio(PINNED_SENTENCE, PINNED_SENTENCE_START, PINNED_SENTENCE_DUR);
  console.log(`  sentence = "${PINNED_SENTENCE}"`);
  console.log(`  words = ${timings.length}, totalChars = ${timings.reduce((s, t) => s + t.chars, 0)} (ignoring spaces)\n`);
  console.log("  ┌───────┬───────┬────────┬────────────┬────────────┬────────────┬────────────┐");
  console.log("  │ word  │ chars │ ratio  │ start (s)  │ dur (s)    │ end (s)    │ emphasis?  │");
  console.log("  ├───────┼───────┼────────┼────────────┼────────────┼────────────┼────────────┤");
  const emphasis = [1, 4]; // "bottles", "planet"
  for (const t of timings) {
    const emph = emphasis.includes(t.i) ? "YES" : "—";
    console.log(
      `  │ ${t.text.padEnd(5)} │ ${String(t.chars).padEnd(5)} │ ${fix(t.ratio).padEnd(6)} │ ${fix(t.start).padEnd(10)} │ ${fix(t.dur).padEnd(10)} │ ${fix(t.end).padEnd(10)} │ ${emph.padEnd(10)} │`,
    );
  }
  console.log("  └───────┴───────┴────────┴────────────┴────────────┴────────────┴────────────┘");
  const ratioSum = timings.reduce((s, t) => s + t.ratio, 0);
  const durSum = timings.reduce((s, t) => s + t.dur, 0);
  check("char-ratios sum to 1.0 (exact partition)", Math.abs(ratioSum - 1) < 1e-9);
  check("per-word durations sum to sentenceDur", Math.abs(durSum - PINNED_SENTENCE_DUR) < 1e-9);
  console.log(`  PINNED: ratioSum = ${fix(ratioSum)}   durSum = ${fix(durSum)} (=== ${fix(PINNED_SENTENCE_DUR)})`);
}

function sectionB(): void {
  banner("SECTION B: the CORRECT GSAP direct-color-tween pattern");
  console.log("  AGENTS.md \"The correct caption pattern\" (verbatim):");
  console.log("    tl.to(wordSelector, { color: '#ffea00', duration: 0.15, ease: 'power2.out' }, wordStart);");
  console.log("    tl.to(wordSelector, { color: 'rgba(255,255,255,0.4)', duration: 0.15, ease: 'power2.in' }, wordEnd);\n");
  const timings = timeWordsByCharRatio(PINNED_SENTENCE, PINNED_SENTENCE_START, PINNED_SENTENCE_DUR);
  const js = buildCaptionTimelineJs(timings);
  console.log(`  // CAPTION_TIMELINE  (two direct-color tweens per word):\n${js.split("\n").map((l) => "    " + l).join("\n")}`);
  check("timeline uses DIRECT color tweens (no className)", lintCaptionJS(js).ok);
  check("timeline tweens the ACTIVE color exactly once per word", js.split("\n").filter((l) => l.includes(ACTIVE_COLOR)).length === timings.length);
}

function sectionC(): void {
  banner("SECTION C: BANNED CSS on .word--active + the detector (layout shift)");
  console.log("  AGENTS.md \"What NOT to do\" — these on `.word--active` cause layout shift / jumping:");
  console.log("    transform: scale(1.15);   font-size: 56px;   text-shadow: 0 0 30px rgba(255,234,0,0.6);\n");
  // CORRECT base style — AGENTS.md verbatim.
  const correctCss = [
    ".caption-phrase .word { display: inline-block; font-size: 48px; color: rgba(255,255,255,0.4);",
    "  transition: color 0.2s ease; text-shadow: 0 4px 20px rgba(0,0,0,0.8); }",
    ".caption-phrase .word--emphasis { color: #4ade80; }",
    ".caption-phrase .word--active { color: #ffea00; }",
  ].join("\n");
  // BANNED active style — AGENTS.md verbatim.
  const bannedCss = [
    ".caption-phrase .word--active {",
    "  transform: scale(1.15);",
    "  font-size: 56px;",
    "  text-shadow: 0 0 30px rgba(255,234,0,0.6);",
    "}",
  ].join("\n");
  const rOk = lintCaptionCSS(correctCss);
  const rBad = lintCaptionCSS(bannedCss);
  check("lintCaptionCSS PASSES on the correct base style (no banned tokens in .word--active)", rOk.ok);
  check("lintCaptionCSS FAILS on the banned .word--active (transform/scale/font-size/text-shadow)", !rBad.ok && rBad.hits.length >= 3);
  console.log(`  correctCss lint → ok=${rOk.ok}  hits=${JSON.stringify(rOk.hits)}`);
  console.log(`  bannedCss   lint → ok=${rBad.ok}  hits=${JSON.stringify(rBad.hits)}`);
}

function sectionD(): void {
  banner("SECTION D: why GSAP className toggle is BANNED + the detector");
  console.log("  AGENTS.md \"Why className toggle is banned\":");
  console.log("    tl.to(word, { className: '+=word--active', duration: 0.05 }, start);   // ← BANNED\n");
  const bannedJs = "tl.to('[data-i=\"0\"]', { className: '+=word--active', duration: 0.05 }, 0.0);";
  const correctJs = "tl.to('[data-i=\"0\"]', { color: '#ffea00', duration: 0.15 }, 0.0);";
  const rBad = lintCaptionJS(bannedJs);
  const rOk = lintCaptionJS(correctJs);
  check("lintCaptionJS FAILS on the className toggle", !rBad.ok);
  check("lintCaptionJS PASSES on the direct color tween", rOk.ok);
  console.log("  className plugin pitfalls (AGENTS.md):");
  console.log("    1. reads computed styles before/after → animates unintended property changes");
  console.log("    2. duration 0.05 is too short to see → an instant SNAP, not a tween");
  console.log("    3. conflicts with the CSS `transition` on the same element");
}

function sectionE(): void {
  banner("SECTION E: caption HTML structure (phrase + word spans; base + emphasis)");
  console.log("  <!-- CAPTION_LAYER --> → phrase of word spans. Emphasis is STATIC, not animated.\n");
  const timings = timeWordsByCharRatio(PINNED_SENTENCE, PINNED_SENTENCE_START, PINNED_SENTENCE_DUR);
  const html = buildCaptionHtml(timings, [1, 4]); // "bottles", "planet" emphasized
  console.log(html.split("\n").map((l) => "    " + l).join("\n"));
  const spanCount = (html.match(/<span/g) || []).length;
  const emphCount = (html.match(/word--emphasis/g) || []).length;
  check("caption layer has one span per word", spanCount === timings.length);
  check("emphasis is a static class, never the animated .word--active", !html.includes("word--active") && emphCount === 2);
  console.log(`  base style (AGENTS.md): display:inline-block; color:${DIM_COLOR}; transition:color .2s ease; text-shadow:0 4px 20px rgba(0,0,0,.8)`);
  console.log(`  emphasis (AGENTS.md): .word--emphasis { color: ${EMPHASIS_COLOR}; }   ← static, NOT animated`);
}

function sectionF(): void {
  banner("SECTION F: caption_style enum (RFC 0001 §5.2) + marker injection sites");
  console.log("  RFC 0001 §5.2: theme.caption_style ∈ { highlight, neon, editorial, eco-green }\n");
  // Only `highlight` is fully pinned by AGENTS.md (active #ffea00). The other
  // three are enum members whose palette is template-defined — NOT spec-pinned.
  const styleInfo: Array<{ name: CaptionStyle; active: string | null; specPinned: boolean }> = [
    { name: "highlight", active: ACTIVE_COLOR, specPinned: true },
    { name: "neon", active: null, specPinned: false },
    { name: "editorial", active: null, specPinned: false },
    { name: "eco-green", active: null, specPinned: false },
  ];
  for (const s of styleInfo) {
    const active = s.active === null ? "(template-defined)" : s.active;
    const pin = s.specPinned ? "spec-pinned (AGENTS.md)" : "enum-only";
    console.log(`  ${s.name.padEnd(11)} active=${active.padEnd(12)} ${pin}`);
  }
  check("caption_style enum has exactly the 4 RFC §5.2 members", CAPTION_STYLES.length === 4);
  check("isValidCaptionStyle accepts each member + rejects a bogus one",
    CAPTION_STYLES.every(isValidCaptionStyle) && !isValidCaptionStyle("karaoke"));
  console.log(`\n  injection markers (RFC §7 / AGENTS.md "Root index.html markers"):`);
  console.log(`    ${MARKERS.layer}   → caption HTML`);
  console.log(`    ${MARKERS.css}             → caption CSS (selected by theme.caption_style)`);
  console.log(`    ${MARKERS.timeline}      → GSAP word-highlight timeline`);
  console.log("  pipeline (RFC §10 step 4): captions.build_captions() → layer + timeline;");
  console.log("    data-duration / DUR auto-updated to the measured voiceover length.");
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
