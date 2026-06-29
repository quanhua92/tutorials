// visual_determinism — ground-truth runnable for "visual, not byte-identical, determinism" (RFC 0001 §11)
// Run: pnpm exec tsx bundles/visual_determinism.ts
//
// Teaches the determinism contract of OpenVideoKit:
//   - §11: "Visual determinism, not byte-identical." Same input → visually
//     equivalent output across re-renders; minor byte differences (encoder /
//     browser non-determinism) are ALLOWED.
//   - §3 Non-Goals: byte-identical determinism is explicitly a NON-GOAL (but is
//     tighten-able later without rearchitecting — see §11's last paragraph).
//   - §11: "Cache keying and 'did this edit change the output' diffs use
//     perceptual hashing, not byte hashing."
//   - §9.3: FFmpeg with fixed params is near-byte-deterministic; the variable
//     part is BROWSER CAPTURE, which only matters once the own-renderer ships.
//
// Determinism hard rules (HOW_TO_RESEARCH §STEP 3): NO fs reads, NO Date.now,
// NO Math.random, NO wall-clock. The "frames" are FIXED in-source 8×8 grayscale
// matrices (0..255). aHash (average hash) is computed deterministically; floats
// print at .toFixed(6). Re-running is byte-identical. The companion
// visual_determinism.html recomputes the SAME aHash + Hamming logic in JS and
// gold-checks one pinned value: distance between two IDENTICAL frames === 0.

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

// ---- RFC 0001 §11 (quoted VERBATIM from docs/rfc-0001.md) ----
const RFC_S11 = [
  "## 11. Determinism",
  "",
  "**Visual determinism**, not byte-identical.",
  "",
  "- Same input → visually equivalent output across re-renders. Minor byte",
  "  differences (encoder/browser non-determinism) are allowed.",
  "- FFmpeg with fixed params is near-byte-deterministic; the variable part is",
  "  browser capture, which only matters once we ship our own renderer.",
  '- Cache keying and "did this edit change the output" diffs use **perceptual',
  "  hashing**, not byte hashing.",
  "",
  "Byte-identical determinism is a non-goal. If it ever becomes required (e.g.,",
  "for CI gate precision), it can be tightened later (pin Chromium, force CPU",
  "rasterization, full asset preload) without rearchitecting.",
].join("\n");

// ---- RFC 0001 §3 Non-Goals (the byte-identical line, verbatim) ----
const RFC_S3_NONGOAL_BYTE = "Byte-identical determinism (visual determinism suffices — see §11).";

// ---- RFC 0001 §9.3 (own-renderer = headless Chromium + FFmpeg) ----
const RFC_S93_OWN_RENDERER =
  "Headless-Chromium frame capture + FFmpeg encode/mux, targeting visual determinism (§11).";

// ---- the aHash algorithm (VERBATIM from JohannesBuchner/imagehash average_hash) ----
// Source: https://github.com/JohannesBuchner/imagehash  (imagehash/__init__.py)
//   image = image.convert("L").resize((hash_size, hash_size), ANTIALIAS)  # grayscale + 8x8
//   avg = mean(pixels)                                                    # mean luminescence
//   diff = pixels > avg                                                   # 64-bit hash
// And Hamming distance (__sub__): count_nonzero(h1.flatten() != h2.flatten())
const AHASH_STEPS = [
  "1. reduce size     -> resize to 8x8 (hash_size=8 -> 64-bit hash)",
  "2. reduce color    -> convert to grayscale ('L'): one luma value 0..255 per cell",
  "3. compute mean    -> avg = mean(all 64 luma values)",
  "4. threshold       -> bit = 1 if pixel > avg else 0   (strictly greater than)",
].join("\n");

const HASH_SIZE = 8; // 8x8 grid -> 64-bit hash
const CACHE_THRESHOLD = 5; // distance <= 5 -> cache HIT (visually equivalent)

// ===========================================================================
// FIXED in-source "frames" — 8x8 grayscale matrices (0..255). NO FS reads,
// NO Date.now, NO Math.random. These stand in for two captured preview frames.
// Design: DARK=30, BRIGHT=200 keeps means clean (115 exactly for A and C) so
// the threshold `pixel > mean` has zero boundary ambiguity.
//   Frame A   = vertical split   (left dark, right bright)
//   Frame A'  = byte-for-byte identical copy of A
//   Frame B   = A with ONE cell changed: A[0][0] 30 -> 250  (1-pixel encoder jitter)
//   Frame C   = horizontal split (top dark, bottom bright) -> different content
// ===========================================================================
const DARK = 30;
const BRIGHT = 200;

function vSplit(): number[][] {
  return Array.from({ length: HASH_SIZE }, () => [DARK, DARK, DARK, DARK, BRIGHT, BRIGHT, BRIGHT, BRIGHT]);
}
function hSplit(): number[][] {
  const f: number[][] = [];
  for (let r = 0; r < HASH_SIZE; r++) f.push(Array(HASH_SIZE).fill(r < 4 ? DARK : BRIGHT));
  return f;
}

const FRAME_A: number[][] = vSplit();
const FRAME_A_PRIME: number[][] = FRAME_A.map((row) => row.slice());
const FRAME_B: number[][] = FRAME_A.map((row) => row.slice());
FRAME_B[0][0] = 250; // one cell perturbed (simulates encoder/browser non-determinism)
const FRAME_C: number[][] = hSplit();

// ---- aHash + Hamming distance (the perceptual-hashing toolkit) ----

/** Mean of all 64 cells (the aHash threshold). */
function mean(frame: number[][]): number {
  let sum = 0;
  for (const row of frame) for (const v of row) sum += v;
  return sum / (HASH_SIZE * HASH_SIZE);
}

/** aHash: 8x8 bit grid (1 iff pixel > mean). Deterministic — pure function of frame. */
function aHash(frame: number[][]): number[][] {
  const avg = mean(frame);
  return frame.map((row) => row.map((v) => (v > avg ? 1 : 0)));
}

/** Hamming distance between two equal-length bit grids = count of differing bits. */
function hamming(h1: number[][], h2: number[][]): number {
  let d = 0;
  for (let r = 0; r < HASH_SIZE; r++) {
    for (let c = 0; c < HASH_SIZE; c++) {
      if (h1[r][c] !== h2[r][c]) d++;
    }
  }
  return d;
}

/** Population count (number of 1-bits) — proves the hash is balanced. */
function popcount(h: number[][]): number {
  let n = 0;
  for (const row of h) for (const b of row) n += b;
  return n;
}

/** Hex string of a bit grid, row-major, 16 hex chars for 64 bits (nibble-by-nibble). */
function toHex(h: number[][]): string {
  const bits = h.flat().map(String).join("");
  const nibbles = bits.match(/.{4}/g) ?? [];
  return nibbles.map((n) => parseInt(n, 2).toString(16)).join("");
}

/** ASCII render of a bit grid: '#' = 1 (above mean), '.' = 0 (below mean). */
function renderBits(h: number[][]): string[] {
  return h.map((row) => "  " + row.map((b) => (b === 1 ? "#" : ".")).join(" "));
}

// ---- cache decision (RFC §11: "did this edit change the output?") ----
type CacheDecision = "HIT" | "MISS";
function cacheDecision(distance: number): CacheDecision {
  return distance <= CACHE_THRESHOLD ? "HIT" : "MISS";
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: visual determinism, NOT byte-identical (RFC §11 + §3)");
  console.log("  RFC 0001 §11 — Determinism (verbatim):\n");
  for (const line of RFC_S11.split("\n")) console.log("    " + line);
  console.log("");
  console.log("  RFC 0001 §3 Non-Goals — the byte-identical line (verbatim):");
  console.log(`    "${RFC_S3_NONGOAL_BYTE}"\n`);

  const saysVisual = /Visual determinism\*\*, not byte-identical/.test(RFC_S11);
  const byteIsNonGoal = /Byte-identical determinism is a non-goal/.test(RFC_S11);
  const listedAsNonGoal = /Byte-identical determinism/.test(RFC_S3_NONGOAL_BYTE);
  check("§11 opens with 'Visual determinism, not byte-identical'", saysVisual);
  check("§11 declares byte-identical a non-goal (tighten-able later)", byteIsNonGoal);
  check("§3 Non-Goals lists byte-identical determinism (defers to §11)", listedAsNonGoal);
  console.log("  → the contract is VISUAL equivalence across re-renders, not byte equality.");
  console.log("    Minor byte diffs (encoder / browser non-determinism) are allowed by design.");
}

function sectionB(): void {
  banner("SECTION B: where non-determinism enters (FFmpeg stable; browser capture is the variable part)");
  console.log("  RFC §11 bullet: 'FFmpeg with fixed params is near-byte-deterministic; the");
  console.log("  variable part is browser capture, which only matters once we ship our own");
  console.log("  renderer.'\n");
  console.log("  RFC §9.3 (own-renderer, verbatim):");
  console.log(`    "${RFC_S93_OWN_RENDERER}"\n`);

  const ffmpegStable = /FFmpeg with fixed params is near-byte-deterministic/.test(RFC_S11);
  const browserIsVariable = /browser capture, which only matters once we ship our own renderer/.test(RFC_S11);
  const ownRendererMentionsChromium = /Headless-Chromium/.test(RFC_S93_OWN_RENDERER);
  check("FFmpeg (fixed params) is the near-byte-deterministic half", ffmpegStable);
  check("browser capture is the variable half — own-renderer only (§9.3)", browserIsVariable && ownRendererMentionsChromium);
  console.log("  → today (HF POC, §9.2) the determinism surface is HF's own pipeline. The");
  console.log("    browser-capture variable only enters when the own-renderer (§9.3) ships.");
  console.log("    Cross-ref 🔗 SLIDE_RENDERER_INTERFACE (§9.3 is where determinism engineering lands).");
}

function sectionC(): void {
  banner("SECTION C: perceptual hashing (aHash) — downscale → grayscale → mean → threshold");
  console.log("  RFC §11: cache keying + 'did this edit change the output?' diffs use");
  console.log("  PERCEPTUAL hashing, not byte hashing. The algorithm below is aHash");
  console.log("  (average hash), verbatim recipe from JohannesBuchner/imagehash:\n");
  for (const line of AHASH_STEPS.split("\n")) console.log("    " + line);
  console.log(`\n  GRID = ${HASH_SIZE}x${HASH_SIZE} -> ${HASH_SIZE * HASH_SIZE}-bit hash\n`);

  const meanA = mean(FRAME_A);
  const hashA = aHash(FRAME_A);
  console.log(`  Frame A (vertical split: left=${DARK}, right=${BRIGHT})`);
  console.log(`    mean(A)            = ${fix(meanA)}  (== 115 exactly: 32*30+32*200 = 7360; /64)`);
  console.log(`    popcount(aHash(A)) = ${popcount(hashA)}  (32 above mean, 32 below — balanced)`);
  console.log(`    hex(aHash(A))      = ${toHex(hashA)}`);
  console.log(`    aHash(A) bit grid  (# = above mean, . = below mean):`);
  for (const line of renderBits(hashA)) console.log(line);

  check("mean(A) === 115.000000 (clean threshold, no boundary ambiguity)", meanA === 115);
  check(`aHash(A) is a ${HASH_SIZE * HASH_SIZE}-bit hash (8x8 grid)`, hashA.length === 8 && hashA[0].length === 8);
  check("aHash is DETERMINISTIC: aHash(A) computed twice is byte-identical",
    JSON.stringify(aHash(FRAME_A)) === JSON.stringify(aHash(FRAME_A)));
  console.log("  → aHash reduces a frame to a 64-bit fingerprint of its luminance structure.");
  console.log("    Two visually-similar frames → small Hamming distance; different → large.");
}

function sectionD(): void {
  banner("SECTION D: Hamming distance — 'how different are two hashes' (count of differing bits)");
  console.log("  Hamming distance (Wikipedia): 'the number of positions at which the");
  console.log("  corresponding symbols are different.' For binary strings, equals the");
  console.log("  population count (number of 1s) of a XOR b. Identical hashes -> 0.\n");

  const hA = aHash(FRAME_A);
  const hAp = aHash(FRAME_A_PRIME);
  const hB = aHash(FRAME_B);
  const hC = aHash(FRAME_C);

  const dAA = hamming(hA, hA);
  const dAAp = hamming(hA, hAp);
  const dAB = hamming(hA, hB);
  const dAC = hamming(hA, hC);

  console.log(`    hex(A)  = ${toHex(hA)}`);
  console.log(`    hex(A') = ${toHex(hAp)}   (byte-identical copy of A)`);
  console.log(`    hex(B)  = ${toHex(hB)}   (A with cell[0][0] flipped across the mean)`);
  console.log(`    hex(C)  = ${toHex(hC)}   (horizontal split — different content)`);
  console.log("");
  console.log(`    distance(A, A)  = ${dAA}   (same object)`);
  console.log(`    distance(A, A') = ${dAAp}   (IDENTICAL frames)`);
  console.log(`    distance(A, B)  = ${dAB}   (1 cell changed -> SMALL)`);
  console.log(`    distance(A, C)  = ${dAC}   (different layout -> LARGE)`);

  check("IDENTICAL frames -> Hamming distance === 0", dAAp === 0);
  check("1 cell changed -> small Hamming distance (=== 1)", dAB === 1);
  check("different content -> large Hamming distance (32 of 64 bits differ)", dAC === 32 && dAC > dAB);
  console.log("  → Hamming distance is the right metric for VISUAL equivalence: it is");
  console.log("    insensitive to tiny byte diffs (B ≈ A) but catches real changes (C ≠ A).");
}

function sectionE(): void {
  banner("SECTION E: the cache decision — perceptual-hash diff below threshold -> HIT");
  console.log("  RFC §11 use case: 'did this edit change the output?' Diff the perceptual");
  console.log(`  hashes; if Hamming distance <= threshold (${CACHE_THRESHOLD}), the frames are`);
  console.log("  visually equivalent -> cache HIT (reuse the rendered output, no re-render).");
  console.log("  Above threshold -> cache MISS (re-render).\n");

  const pairs: Array<[string, number]> = [
    ["A vs A' (identical)", hamming(aHash(FRAME_A), aHash(FRAME_A_PRIME))],
    ["A vs B  (1 cell)   ", hamming(aHash(FRAME_A), aHash(FRAME_B))],
    ["A vs C  (different)", hamming(aHash(FRAME_A), aHash(FRAME_C))],
  ];
  for (const [label, d] of pairs) {
    const dec = cacheDecision(d);
    console.log(`    distance ${label} = ${String(d).padStart(2)}  ->  cache ${dec}`);
  }
  console.log("");

  const hitIdentical = cacheDecision(hamming(aHash(FRAME_A), aHash(FRAME_A_PRIME))) === "HIT";
  const hitOneCell = cacheDecision(hamming(aHash(FRAME_A), aHash(FRAME_B))) === "HIT";
  const missDifferent = cacheDecision(hamming(aHash(FRAME_A), aHash(FRAME_C))) === "MISS";
  check(`identical + 1-cell jitter -> cache HIT (distance <= ${CACHE_THRESHOLD})`, hitIdentical && hitOneCell);
  check(`different content -> cache MISS (distance > ${CACHE_THRESHOLD})`, missDifferent);
  console.log("  → this is why byte hashing is the WRONG tool: a 1-byte encoder diff would");
  console.log("    force a byte-hash MISS and a wasted re-render. aHash says 'visually same'");
  console.log("    -> HIT -> skip the render. Cross-ref 🔗 EXPORT_PIPELINE (the render we cache).");
}

function sectionF(): void {
  banner("SECTION F: the tightening path — byte-identical CAN be tightened later, no rearchitect");
  console.log("  RFC §11 (last paragraph, verbatim): 'Byte-identical determinism is a non-goal.");
  console.log("  If it ever becomes required (e.g., for CI gate precision), it can be tightened");
  console.log("  later (pin Chromium, force CPU rasterization, full asset preload) without");
  console.log("  rearchitecting.'\n");

  // The three tightening levers the RFC names — extracted from the verbatim text.
  const levers = ["pin Chromium", "force CPU rasterization", "full asset preload"];
  console.log("  tightening levers (from §11):");
  for (const lv of levers) console.log(`    - ${lv}`);
  console.log("");

  // The verbatim quote hard-wraps mid-phrase ("force CPU\nrasterization"); collapse
  // whitespace before substring testing so the check is wrap-agnostic.
  const s11Flat = RFC_S11.replace(/\s+/g, " ");
  const allLeversInText = levers.every((lv) => s11Flat.includes(lv));
  const noRearchitect = /without rearchitecting/.test(s11Flat);
  check("§11 names all three tightening levers (Chromium pin / CPU raster / full preload)", allLeversInText);
  check("§11 guarantees tightening needs NO rearchitecture ('without rearchitecting')", noRearchitect);
  console.log("  → visual determinism is the v1 bar; byte-identical is a LATER, additive");
  console.log("    tightening (a CI precision knob), not a redesign. The SlideRenderer seam");
  console.log("    (§9) is untouched either way. Cross-ref 🔗 STAGE_CANVAS (real-time preview");
  console.log("    can stay non-frame-accurate without breaking this export-time contract).");
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
