// timeline_panel — ground-truth runnable for "the Timeline editor surface" (RFC 0001 §7)
// Run: pnpm exec tsx bundles/timeline_panel.ts
//
// Teaches the bottom panel of the editor. The single most important idea
// (RFC §5.5): the timeline is a *VIEW* over `(slide order + measured
// durations)` — NOT a rich structure the editor persists. Reordering slides
// mutates the `slides` array in root index.json; it never moves folders on
// disk. It is explicitly NOT a multi-track NLE (RFC §3 Non-Goals).
//
// This runnable embeds a deterministic sample, computes the cumulative-start
// (prefix-sum) timeline math via reduce, performs a reorder swap, and prints
// every value TIMELINE_PANEL.md cites verbatim.

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

// ---- deterministic sample (RFC 0001 §5.2 root + §5.3 slide duration) ----
// NO FS reads, NO Date.now, NO Math.random. Re-running is byte-identical.
// slide folder → MEASURED duration (from each slide index.json §5.3).
const DURATIONS: Record<string, number> = {
  "slide-0": 4.0,
  "slide-1": 5.0,
  "slide-2": 3.0,
};

// root index.json §5.2 — the single source of slide ORDER. This is the ONLY
// thing reorder mutates.
let order: string[] = ["slide-0", "slide-1", "slide-2"];

// inter-slide gap (seconds). 0 here for the PINNED example; the voiceover
// pipeline default is 0.8 (AGENTS.md "Smart timing": prev_end + gap_between_slides).
const GAP_BETWEEN_SLIDES = 0.0;

// RFC §7 Editor Surfaces — Timeline row, quoted verbatim:
//   "Timeline (bottom) | binds to root index.json (slide order) + each slide
//    duration | reorder slides, see per-slide durations, audio lane"

// ---- helpers (deterministic; sorted keys, fixed precision) ----

/** Fixed-precision float (HOW_TO_RESEARCH §STEP 3.1). */
function fix(n: number): string {
  return n.toFixed(6);
}

/** Sorted keys of a string-keyed record (stable iteration). */
function sortedKeys(rec: Record<string, number>): string[] {
  return Object.keys(rec).sort();
}

/**
 * Cumulative start times = prefix sums of durations (Gantt-style; verified
 * via MDN Array.prototype.reduce). start[i] = sum(dur[0..i-1]) + i*gap.
 * Implemented with reduce: the accumulator is "where the next clip begins".
 */
function cumulativeStarts(durations: number[], gap: number): number[] {
  const starts: number[] = [];
  durations.reduce<number>((acc, dur, i) => {
    starts[i] = acc; // this clip starts at the running sum
    return acc + dur + gap; // next clip starts after this one + inter-slide gap
  }, 0);
  return starts;
}

/** Total video length = last clip end = sum(dur) + (n-1)*gap. */
function totalDuration(durations: number[], gap: number): number {
  if (durations.length === 0) return 0;
  const starts = cumulativeStarts(durations, gap);
  return starts[starts.length - 1] + durations[durations.length - 1];
}

/** The slide-clip lane, built purely from (order, durations, gap). */
interface Clip {
  id: string;
  start: number;
  duration: number;
}
interface TimelineView {
  slideClips: Clip[];
  total: number;
  audio: { music: { loop: boolean; volume: number }; voiceoverSpan: number };
}

/** timeline = view(order, durations) → rendered lanes. The panel's whole job. */
function buildView(
  slideOrder: string[],
  durations: Record<string, number>,
  gap: number,
): TimelineView {
  const durs = slideOrder.map((id) => durations[id]);
  const starts = cumulativeStarts(durs, gap);
  const total = totalDuration(durs, gap);
  return {
    slideClips: slideOrder.map((id, i) => ({ id, start: starts[i], duration: durs[i] })),
    total,
    // RFC §5.2 audio model + AGENTS.md "Preview audio": music loops (volume
    // 0.08); voiceover is ONE track spanning the measured total.
    audio: { music: { loop: true, volume: 0.08 }, voiceoverSpan: total },
  };
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the timeline is a VIEW, not a persisted structure");
  console.log("  RFC 0001 §5.5 — \"The editor's 'timeline' panel is a *view* over");
  console.log("  (slide order + measured durations) — not a rich structure it persists.\"\n");
  console.log("  signature:  view(slideOrder: string[], durations: Record<id,number>) → lanes\n");
  const view = buildView(order, DURATIONS, GAP_BETWEEN_SLIDES);
  for (const c of view.slideClips) {
    console.log(
      `    clip ${c.id}  start=${fix(c.start)}  dur=${fix(c.duration)}  end=${fix(c.start + c.duration)}`,
    );
  }
  console.log(`    total = ${fix(view.total)}`);
  const pure =
    view.total === totalDuration(order.map((id) => DURATIONS[id]), GAP_BETWEEN_SLIDES);
  check("timeline is a pure view (output derived solely from order + durations)", pure);
  console.log("  → the panel persists NOTHING of its own; it reads two existing files.");
}

function sectionB(): void {
  banner("SECTION B: cumulative-start computation (prefix sums) — worked example");
  console.log("  start[i] = sum(dur[0..i-1]) + i*gap. With gap = 0:\n");
  const durs = order.map((id) => DURATIONS[id]);
  const starts = cumulativeStarts(durs, GAP_BETWEEN_SLIDES);
  const total = totalDuration(durs, GAP_BETWEEN_SLIDES);
  console.log(`    order      = [${order.map((o) => `"${o}"`).join(", ")}]`);
  console.log(`    durations  = [${durs.join(", ")}]`);
  console.log(`    cum Starts = [${starts.map((s) => fix(s)).join(", ")}]`);
  console.log(`    total      = ${fix(total)}\n`);
  check(
    "cumulative starts === [0, 4, 9] (prefix sums of [4,5,3])",
    starts.length === 3 && starts[0] === 0 && starts[1] === 4 && starts[2] === 9,
  );
  check("total === 12.0 (sum of durations, gap 0)", total === 12.0);
  console.log(`  PINNED: starts = [0, 4.0, 9.0], total = 12.0`);
}

function sectionC(): void {
  banner("SECTION C: reorder = mutate root.slides (folders NEVER move)");
  console.log("  Reorder swaps the ORDER array. Folders on disk are stable handles.\n");
  const foldersBefore = sortedKeys(DURATIONS).join(",");

  // BEFORE
  const before = buildView(order, DURATIONS, GAP_BETWEEN_SLIDES);
  console.log("  BEFORE:");
  console.log(`    root.slides = [${order.map((o) => `"${o}"`).join(", ")}]`);
  console.log(
    `    cum Starts  = [${before.slideClips.map((c) => fix(c.start)).join(", ")}]  total=${fix(before.total)}`,
  );

  // REORDER: swap slide-0 ↔ slide-2 (indices 0 and 2)
  const reordered = [...order];
  [reordered[0], reordered[2]] = [reordered[2], reordered[0]];
  order = reordered; // this is the ONLY mutation; it would write back to root index.json

  // AFTER
  const after = buildView(order, DURATIONS, GAP_BETWEEN_SLIDES);
  console.log("  AFTER (swap slide-0 ↔ slide-2):");
  console.log(`    root.slides = [${order.map((o) => `"${o}"`).join(", ")}]`);
  console.log(
    `    cum Starts  = [${after.slideClips.map((c) => fix(c.start)).join(", ")}]  total=${fix(after.total)}`,
  );

  const foldersAfter = sortedKeys(DURATIONS).join(",");
  console.log(`\n    folders on disk (before): ${foldersBefore}`);
  console.log(`    folders on disk (after) : ${foldersAfter}  ← UNCHANGED\n`);
  check(
    "reorder: new cumulative starts === [0, 3, 8]",
    after.slideClips[0].start === 0 &&
      after.slideClips[1].start === 3 &&
      after.slideClips[2].start === 8,
  );
  check("reorder: total is invariant (12.0 === 12.0)", before.total === after.total);
  check("reorder: folders on disk unchanged", foldersBefore === foldersAfter);
  console.log("  → undo/redo is a JSON array mutation, not a filesystem operation.");
}

function sectionD(): void {
  banner("SECTION D: audio lane — music loop + voiceover (one track)");
  console.log("  RFC §5.2 audio + AGENTS.md \"Preview audio\":\n");
  const view = buildView(order, DURATIONS, GAP_BETWEEN_SLIDES);
  console.log("    MUSIC BED");
  console.log(`      loop   = ${view.audio.music.loop}   (bed loops for the whole video)`);
  console.log(`      volume = ${fix(view.audio.music.volume)}  (0..1; AGENTS.md default 0.08)`);
  console.log("    VOICEOVER TRACK");
  console.log(`      span   = ${fix(view.audio.voiceoverSpan)}  (ONE track, spans measured total)`);
  console.log("      loop   = false  (plays once; its measured length drives captions)\n");
  check("music loops (loop === true)", view.audio.music.loop === true);
  check("voiceover span === measured total", view.audio.voiceoverSpan === view.total);
  console.log("  → per-slide duration comes from each slide index.json `duration`");
  console.log("    (MEASURED by the ffprobe + concat pipeline; cross-ref SLIDE_INDEX_JSON).");
}

function sectionE(): void {
  banner("SECTION E: why a view, not a structure (small stable data layer)");
  console.log("  RFC §5.5: the timeline is NOT persisted. The ONLY timeline-related state");
  console.log("  in JSON is: (1) root.slides[] (order) + (2) each slide's `duration`.\n");
  // Demonstrate the data layer is unchanged by building the view twice.
  const v1 = buildView(order, DURATIONS, GAP_BETWEEN_SLIDES);
  const v2 = buildView(order, DURATIONS, GAP_BETWEEN_SLIDES);
  const stable = v1.total === v2.total && v1.slideClips.length === v2.slideClips.length;
  check("view is recomputable from the same two inputs (deterministic)", stable);
  console.log("  → small + stable data layer = ideal target for AI Tier-1 edits (RFC 0002):");
  console.log("    a small model just reorders slides[] or tweaks a duration; the panel");
  console.log("    re-derives the rest. No timeline JSON to parse or corrupt.");
}

function sectionF(): void {
  banner("SECTION F: NON-GOAL — this is NOT a multi-track NLE");
  console.log("  RFC §3 Non-Goals (verbatim):");
  console.log('    "Full multi-track NLE (Premiere/Resolve class). Scene-based only."\n');
  // The model is a single sequential scene lane: each clip starts where the
  // previous ended (no overlapping tracks, no parallel clips).
  const view = buildView(order, DURATIONS, GAP_BETWEEN_SLIDES);
  let sequential = true;
  for (let i = 1; i < view.slideClips.length; i++) {
    const prev = view.slideClips[i - 1];
    const cur = view.slideClips[i];
    if (cur.start < prev.start + prev.duration) sequential = false;
  }
  const oneLane = view.slideClips.every((c) => c.duration > 0);
  check("single sequential scene lane (no overlapping clips)", sequential && oneLane);
  console.log("  → no parallel tracks, no J/L cuts, no keyframed opacity lanes.");
  console.log("    One slide at a time, back to back. That is the entire timeline model.");
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
