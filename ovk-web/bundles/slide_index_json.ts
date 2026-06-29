// slide_index_json — ground-truth runnable for "the per-slide index.json" (RFC 0001 §5.3)
// Run: pnpm exec tsx bundles/slide_index_json.ts
//
// Teaches the data file for ONE slide: `id`, `duration` (MEASURED, not authored),
// optional `transition` override, `fields` (bound to __FIELD__), `assets` (SHA refs),
// and `voiceover` (text + voice id). This is the data the editor's Properties
// panel binds to. Every value SLIDE_INDEX_JSON.md cites is printed here.

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

// ---- deterministic sample slide index.json (RFC 0001 §5.3, verbatim shape) ----
// NO FS reads, NO Date.now, NO RNG. Re-running is byte-identical.

interface Transition {
  type: string;
  duration: number;
}

interface Voiceover {
  text: string;
  voice: string;
}

interface SlideIndex {
  id: string;
  duration: number; // MEASURED from voiceover (ffprobe → concat)
  transition?: Transition; // OPTIONAL override of root transition_default
  fields: Record<string, string>; // values bound to __FIELD__
  assets: Record<string, string>; // SHA refs, never blobs
  voiceover: Voiceover; // text + edge-tts voice id
}

// RFC §5.3 sample — keys in RFC document order.
const SAMPLE: SlideIndex = {
  id: "slide-0",
  duration: 5.0, // measured (from voiceover timings)
  transition: { type: "push", duration: 0.5 }, // optional override of transition_default
  fields: { title: "Eco Bottle", body: "Sustainable. Reusable. Beautiful." },
  assets: { img: "sha256:" + "a".repeat(64) },
  voiceover: { text: "Meet the Eco Bottle. Built for the planet.", voice: "vi-VN-HoaiMyNeural" },
};

// root index.json transition_default (RFC §5.2) — what a slide INHERITS without override.
const ROOT_TRANSITION_DEFAULT: Transition = { type: "crossfade", duration: 0.4 };

// Required top-level keys for a slide index.json (transition is OPTIONAL).
const REQUIRED_KEYS = ["id", "duration", "fields", "assets", "voiceover"] as const;

// ---- validators ----

/** A valid edge-tts voice id ends in "Neural" (AGENTS.md pitfall #1). */
function isValidVoiceId(voice: string): boolean {
  return voice.endsWith("Neural");
}

/** A valid asset reference is a SHA-256 content-address string, never an embedded blob. */
function isShaRef(ref: string): boolean {
  return ref.startsWith("sha256:");
}

/** Field id → __FIELD__ placeholder (RFC §5.6: field `title` → `__TITLE__`). */
function placeholder(fieldId: string): string {
  return `__${fieldId.toUpperCase()}__`;
}

/** Sum sentence durations + inter-sentence gaps, rounded to 1 decimal place. */
function measureDuration(sentences: { dur: number }[], gap: number): number {
  const sum =
    sentences.reduce((acc, s) => acc + s.dur, 0) + gap * Math.max(0, sentences.length - 1);
  return Math.round(sum * 10) / 10; // 1 dp — matches voiceover_timings.json precision
}

/** A slide's effective transition = its override, else the root transition_default. */
function effectiveTransition(
  slideTransition: Transition | undefined,
  rootDefault: Transition,
): Transition {
  return slideTransition ?? rootDefault;
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the per-slide index.json schema (RFC 0001 §5.3)");
  console.log("  The data file for ONE slide. Pretty-printed, RFC §5.3 key order:\n");
  console.log(JSON.stringify(SAMPLE, null, 2).replace(/^/gm, "  "));
  const present = (REQUIRED_KEYS as readonly string[]).every((k) => k in SAMPLE);
  check("all required keys present {id, duration, fields, assets, voiceover}", present);
  console.log(`  → transition is OPTIONAL (present here: ${"transition" in SAMPLE})`);
}

function sectionB(): void {
  banner("SECTION B: fields → __FIELD__ stamping (RFC 0001 §5.6)");
  console.log(
    "  Each field id uppercases to its HTML placeholder. Values reach the slide\n  via __FIELD__ string replacement (HF getVariables() returns {} in sub-comps).\n",
  );
  for (const id of Object.keys(SAMPLE.fields)) {
    console.log(`  fields.${id} = ${JSON.stringify(SAMPLE.fields[id])}  →  ${placeholder(id)}`);
  }
  check(
    "title → __TITLE__ and body → __BODY__",
    placeholder("title") === "__TITLE__" && placeholder("body") === "__BODY__",
  );
  console.log("  → see 🔗 DATA_BINDING for the full live-bind vs re-stamp lifecycle.");
}

function sectionC(): void {
  banner("SECTION C: assets are SHA refs, never embedded blobs");
  console.log("  Each asset value is a content-address string; the binary lives in assets/.\n");
  const keys = Object.keys(SAMPLE.assets);
  for (const k of keys) {
    const ref = SAMPLE.assets[k];
    console.log(`  assets.${k} = "${ref.slice(0, 16)}…"  (len ${ref.length})`);
  }
  const allSha = keys.every((k) => isShaRef(SAMPLE.assets[k]));
  check("every asset ref starts with sha256:", allSha);
  const noBlob = keys.every((k) => SAMPLE.assets[k].length < 200);
  check("no embedded base64 blob (refs are short)", noBlob);
  console.log("  → dedup is free: same bytes ⇒ same SHA ⇒ one stored blob (🔗 UNIT_MODEL Section D).");
}

function sectionD(): void {
  banner('SECTION D: voiceover + the edge-tts "Neural" suffix gotcha');
  console.log("  AGENTS.md pitfall #1: edge-tts voice IDs MUST end in 'Neural'.\n");
  const goodVoice = SAMPLE.voiceover.voice; // vi-VN-HoaiMyNeural
  const badVoice = "vi-VN-HoaiMy"; // missing suffix → TTS error
  console.log(`  good: "${goodVoice}"  → isValidVoiceId = ${isValidVoiceId(goodVoice)}`);
  console.log(`  bad : "${badVoice}"  → isValidVoiceId = ${isValidVoiceId(badVoice)}`);
  check("good voice (vi-VN-HoaiMyNeural) accepted", isValidVoiceId(goodVoice));
  check("bad voice (vi-VN-HoaiMy) rejected", !isValidVoiceId(badVoice));
  console.log("  → the editor's Properties panel should validate before TTS runs.");
}

function sectionE(): void {
  banner("SECTION E: duration is MEASURED from voiceover, not authored");
  console.log('  The pipeline (AGENTS.md "Voiceover pipeline") per slide:\n');
  console.log("    voiceover.text  →  split into sentences");
  console.log("    each sentence   →  edge-tts → temp.mp3");
  console.log("    ffprobe each    →  measure ACTUAL duration (seconds)");
  console.log("    ffmpeg concat   →  assets/voiceover.mp3");
  console.log("    sum + gaps      →  measured slide duration\n");
  // deterministic mini-computation: 2 sentences, ffprobe-measured durations
  const sentences = [
    { text: "Meet the Eco Bottle.", dur: 2.3 },
    { text: "Built for the planet.", dur: 2.7 },
  ];
  const gapBetweenSentences = 0.0; // seconds of silence between sentences in THIS slide
  const measured = measureDuration(sentences, gapBetweenSentences);
  console.log(`  sentences = ${JSON.stringify(sentences.map((s) => s.dur))}`);
  console.log(`  gap       = ${gapBetweenSentences}`);
  console.log(
    `  measured  = ${measured.toFixed(1)}  (matches SAMPLE.duration = ${SAMPLE.duration})`,
  );
  check("measured duration === 5.0", measured === SAMPLE.duration && measured === 5.0);
  console.log("  → the user never types a duration; the pipeline measures it.");
}

function sectionF(): void {
  banner("SECTION F: transition override vs inheritance from root transition_default");
  console.log(`  root transition_default = ${JSON.stringify(ROOT_TRANSITION_DEFAULT)}\n`);
  const overrideT = SAMPLE.transition; // present → {push, 0.5}
  const inheritedT: Transition | undefined = undefined; // a slide with NO transition field
  const effA = effectiveTransition(overrideT, ROOT_TRANSITION_DEFAULT);
  const effB = effectiveTransition(inheritedT, ROOT_TRANSITION_DEFAULT);
  console.log(`  slide-0 (has transition)  → effective = ${JSON.stringify(effA)}`);
  console.log(`  slide-1 (no transition)   → effective = ${JSON.stringify(effB)} (inherited)`);
  check(
    "slide with transition uses its override",
    effA.type === "push" && effA.duration === 0.5,
  );
  check(
    "slide without transition inherits root default",
    effB.type === "crossfade" && effB.duration === 0.4,
  );
  console.log("  → omitting transition is a feature: bulk-edit the root default once.");
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
