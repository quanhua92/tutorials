// root_index_json — ground-truth runnable for "the root index.json" (RFC 0001 §5.2)
// Run: pnpm exec tsx bundles/root_index_json.ts
//
// Teaches the project-wide DATA file. Where slide index.json carries per-slide
// content (fields, voiceover, duration), the ROOT index.json carries everything
// GLOBAL: canvas dims/fps, theme, audio refs, the transition default, and the
// slide ordering spine. It is the single source of truth for "what the video is"
// as a whole. This runnable embeds a deterministic sample, asserts the schema
// invariants, and prints every value ROOT_INDEX_JSON.md cites verbatim.

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

// ---- deterministic sample root index.json (RFC 0001 §5.2, embedded verbatim) ----
// NO FS reads, NO Date.now, NO Math.random. Re-running is byte-identical.
// This is the exact jsonc block from docs/rfc-0001.md §5.2 (comments stripped).

interface Canvas {
  width: number;
  height: number;
  fps: number;
}
interface Music {
  asset: string;
  volume: number;
  loop: boolean;
}
interface Voiceover {
  asset: string;
  auto_generated: boolean;
}
interface Audio {
  music: Music;
  voiceover: Voiceover;
}
interface Theme {
  caption_style: string;
  colors: Record<string, string>;
  fonts: Record<string, string>;
}
interface TransitionDefault {
  type: string;
  duration: number;
}
interface RootIndexJson {
  version: number;
  canvas: Canvas;
  theme: Theme;
  audio: Audio;
  transition_default: TransitionDefault;
  slides: string[];
}

const ROOT: RootIndexJson = {
  version: 1,
  canvas: { width: 1920, height: 1080, fps: 30 },
  theme: { caption_style: "highlight", colors: {}, fonts: {} },
  audio: {
    music: { asset: "sha256:deadbeef", volume: 0.08, loop: true },
    voiceover: { asset: "voiceover.mp3", auto_generated: true },
  },
  transition_default: { type: "crossfade", duration: 0.4 },
  slides: ["slide-0", "slide-1", "slide-2"],
};

// caption_style enum — the four allowed values (AGENTS.md "Slot extras").
const CAPTION_STYLES = ["highlight", "neon", "editorial", "eco-green"];

// the slide folders that MUST exist on disk for root.slides to resolve.
// (cross-ref unit_model.ts Section E: every id resolves to a slide unit folder)
const SLIDE_FOLDERS_ON_DISK = ["slide-0", "slide-1", "slide-2"];

// music bed default volume (AGENTS.md "Preview audio": ext-music volume 0.08).
const MUSIC_DEFAULT_VOLUME = 0.08;

// ---- helpers (deterministic; sorted keys, fixed precision) ----

/** Fixed-precision float (HOW_TO_RESEARCH §STEP 3.1). */
function fix(n: number): string {
  return n.toFixed(6);
}

/** Sorted keys of a string-keyed record (stable iteration). */
function sortedKeys(rec: Record<string, string>): string[] {
  return Object.keys(rec).sort();
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: parse + validate the root index.json schema");
  console.log("  RFC 0001 §5.2 — root index.json carries canvas, theme, audio,");
  console.log("  transition_default, and the slides ordering array.\n");
  console.log("  root index.json (parsed):");
  // print the sample as stable json (sorted object keys are not needed here —
  // we print field-by-field in RFC order so output is deterministic).
  console.log(`    version             = ${ROOT.version}`);
  console.log(`    canvas              = {width:${ROOT.canvas.width}, height:${ROOT.canvas.height}, fps:${ROOT.canvas.fps}}`);
  console.log(`    theme.caption_style = "${ROOT.theme.caption_style}"`);
  console.log(`    theme.colors keys   = [${sortedKeys(ROOT.theme.colors).join(", ")}]`);
  console.log(`    theme.fonts  keys   = [${sortedKeys(ROOT.theme.fonts).join(", ")}]`);
  console.log(`    audio.music         = {asset:"${ROOT.audio.music.asset}", volume:${fix(ROOT.audio.music.volume)}, loop:${ROOT.audio.music.loop}}`);
  console.log(`    audio.voiceover     = {asset:"${ROOT.audio.voiceover.asset}", auto_generated:${ROOT.audio.voiceover.auto_generated}}`);
  console.log(`    transition_default  = {type:"${ROOT.transition_default.type}", duration:${fix(ROOT.transition_default.duration)}}`);
  console.log(`    slides              = [${ROOT.slides.map((s) => `"${s}"`).join(", ")}]`);

  // schema invariants
  check("version is a number", typeof ROOT.version === "number");
  check("canvas has width,height,fps", "width" in ROOT.canvas && "height" in ROOT.canvas && "fps" in ROOT.canvas);
  check("audio has music + voiceover", "music" in ROOT.audio && "voiceover" in ROOT.audio);
  check("slides is an array of strings", Array.isArray(ROOT.slides) && ROOT.slides.every((s) => typeof s === "string"));
}

function sectionB(): void {
  banner("SECTION B: canvas — the video dimensions + frame rate");
  const { width, height, fps } = ROOT.canvas;
  console.log("  canvas = the render + encode dimensions. HF render + ffmpeg mux");
  console.log("  consume these exactly (RFC §10 export pipeline).\n");
  console.log(`    width  = ${width}  (Full HD horizontal, 16:9)`);
  console.log(`    height = ${height} (1080 progressive scan lines)`);
  console.log(`    fps    = ${fps}    (ATSC/DVB standard rate; 24/25/60 also valid)`);
  check("canvas is standard Full HD (1920x1080)", width === 1920 && height === 1080);
  check("canvas.fps is a positive standard rate", fps === 30 || fps === 24 || fps === 25 || fps === 60);
  console.log(`  PINNED: canvas.width = ${width}, canvas.height = ${height}, canvas.fps = ${fps}`);
}

function sectionC(): void {
  banner("SECTION C: theme — caption_style enum + colors/fonts maps");
  const style = ROOT.theme.caption_style;
  console.log("  AGENTS.md \"Slot extras\" — caption_style controls caption CSS.");
  console.log(`  allowed enum: ${CAPTION_STYLES.map((s) => `"${s}"`).join(" | ")}\n`);
  console.log(`    theme.caption_style = "${style}"`);
  check("caption_style is one of the 4 allowed values", CAPTION_STYLES.includes(style));
  // colors/fonts are open maps (brand colors, font stacks) — validated as objects.
  check("theme.colors is an object map", typeof ROOT.theme.colors === "object" && ROOT.theme.colors !== null);
  check("theme.fonts is an object map", typeof ROOT.theme.fonts === "object" && ROOT.theme.fonts !== null);
  console.log("  → caption_style reaches the rendered captions via the caption");
  console.log("    pipeline (cross-ref DATA_BINDING).");
}

function sectionD(): void {
  banner("SECTION D: audio — music bed vs voiceover track");
  const { music, voiceover } = ROOT.audio;
  console.log("  Two distinct tracks, two distinct contracts:\n");
  console.log("    MUSIC BED");
  console.log(`      asset         = "${music.asset}"   (SHA-256 content ref)`);
  console.log(`      volume        = ${fix(music.volume)}  (0..1; AGENTS.md default 0.08)`);
  console.log(`      loop          = ${music.loop}   (bed loops for the whole video)`);
  console.log("    VOICEOVER TRACK");
  console.log(`      asset         = "${voiceover.asset}"   (filename ref, TTS-baked)`);
  console.log(`      auto_generated= ${voiceover.auto_generated}  (edge-tts pipeline produces it)`);
  console.log("      loop          = (implicit false — plays once, drives captions)\n");

  check("music.asset is a SHA-256 content reference", music.asset.startsWith("sha256:"));
  check("music.volume is within [0,1]", music.volume >= 0 && music.volume <= 1);
  check("music loops (loop === true)", music.loop === true);
  check("voiceover.auto_generated is boolean", typeof voiceover.auto_generated === "boolean");
  check("music default volume matches AGENTS.md (0.08)", music.volume === MUSIC_DEFAULT_VOLUME);
  console.log("  → music is content-addressed (dedup free); voiceover is generated");
  console.log("    per-project from slide voiceover.text via the batch TTS pipeline.");
}

function sectionE(): void {
  banner("SECTION E: transition_default — and the per-slide override");
  const td = ROOT.transition_default;
  console.log("  The default transition applied BETWEEN slides (root-owned).\n");
  console.log(`    transition_default.type     = "${td.type}"`);
  console.log(`    transition_default.duration = ${fix(td.duration)} (seconds)`);
  check("transition_default has type + duration", typeof td.type === "string" && typeof td.duration === "number");
  check("transition_default.duration is non-negative", td.duration >= 0);
  console.log("  → a slide index.json MAY override this with its own");
  console.log("    `transition` field (forward-ref SLIDE_INDEX_JSON §5.3).");
}

function sectionF(): void {
  banner("SECTION F: slides — the ordering spine (single source of truth)");
  const slides = ROOT.slides;
  console.log("  slides = an array of slide ids, IN ORDER. This is the spine the");
  console.log("  root index.html host sequences. Every id MUST resolve to a slide");
  console.log("  unit folder (cross-ref unit_model Section E).\n");
  for (let i = 0; i < slides.length; i++) {
    console.log(`    slides[${i}] = "${slides[i]}"  → slides/${slides[i]}/`);
  }
  const allResolve = slides.every((id) => SLIDE_FOLDERS_ON_DISK.includes(id));
  check("every id in root.slides resolves to a slide unit folder", allResolve);
  check("slides has no duplicate ids", new Set(slides).size === slides.length);
  console.log(`  PINNED: slides = [${slides.map((s) => `"${s}"`).join(",")}] (length ${slides.length})`);
  console.log("  → reorder = mutate this array, never move folders on disk.");
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
