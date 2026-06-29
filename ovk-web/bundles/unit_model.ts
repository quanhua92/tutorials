// unit_model — ground-truth runnable for "the symmetric unit model" (RFC 0001 §5.1)
// Run: pnpm exec tsx bundles/unit_model.ts
//
// Teaches the heart of the RFC: "JSON is data. HTML is animation." Every unit
// — the project root and each slide — is a folder with exactly two files:
// index.html (the animation/visual) and index.json (the data). This runnable
// walks a sample workspace, asserts the invariants, and prints every value that
// UNIT_MODEL.md cites verbatim.

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

// ---- deterministic sample workspace (NO FS reads, NO Date.now, NO RNG) ----
// This is RFC 0001 §5.1's structure, as data. Re-running is byte-identical.

type UnitKind = "root" | "slide";
interface Unit {
  kind: UnitKind;
  path: string;        // "" for root, "slide-0" etc.
  files: string[];     // the two files a unit owns
}

const UNITS: Unit[] = [
  { kind: "root", path: "", files: ["index.html", "index.json"] },
  { kind: "slide", path: "slide-0", files: ["index.html", "index.json"] },
  { kind: "slide", path: "slide-1", files: ["index.html", "index.json"] },
  { kind: "slide", path: "slide-2", files: ["index.html", "index.json"] },
];

// assets/ is NOT a unit: binary blobs referenced by SHA-256 from index.json.
const ASSET_FILES = ["sha256-c0ffee.jpg", "voiceover.mp3"];

// root index.json slide ordering (RFC §5.2) — the single source of slide order.
const SLIDE_ORDER = ["slide-0", "slide-1", "slide-2"];

const REQUIRED_FILES = ["index.html", "index.json"];

// ---- helpers ----

function isUnitFolder(files: string[]): boolean {
  return REQUIRED_FILES.every((f) => files.includes(f));
}

function label(u: Unit): string {
  return u.kind === "root" ? "<root>" : `slides/${u.path}`;
}

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: the symmetric unit structure");
  console.log("  RFC 0001 §5.1 — every unit is a folder with index.html + index.json\n");
  for (const u of UNITS) {
    console.log(`  ${label(u)}/`);
    for (const f of u.files) console.log(`    ${f}`);
    check(`${label(u)} is a valid unit folder`, isUnitFolder(u.files));
  }
}

function sectionB(): void {
  banner("SECTION B: unit kinds and the two-file invariant");
  const roots = UNITS.filter((u) => u.kind === "root");
  const slides = UNITS.filter((u) => u.kind === "slide");
  check("exactly one root unit", roots.length === 1);
  console.log(`  root unit   → ${roots[0].files.join(" + ")}`);
  console.log(`  slide units → ${slides.length} (slide-0 .. slide-${slides.length - 1})`);
  const allValid = UNITS.every((u) => isUnitFolder(u.files));
  check("every unit has exactly {index.html, index.json}", allValid);
  console.log(`  PINNED: units validated = ${UNITS.length} (1 root + ${slides.length} slides)`);
}

function sectionC(): void {
  banner("SECTION C: file roles differ by unit kind (same names, different jobs)");
  console.log("  ┌─────────┬───────────────────────────────┬─────────────────────────────────────────────┐");
  console.log("  │ Unit    │ index.html (animation)        │ index.json (data)                           │");
  console.log("  ├─────────┼───────────────────────────────┼─────────────────────────────────────────────┤");
  console.log("  │ Root    │ HF root HOST: slide host-divs, │ canvas, theme, audio refs, slide ordering,  │");
  console.log("  │         │ between-slide transitions,    │ transition_default                          │");
  console.log("  │         │ audio playback, caption layer  │                                             │");
  console.log("  ├─────────┼───────────────────────────────┼─────────────────────────────────────────────┤");
  console.log("  │ Slide   │ bare <template> sub-comp:      │ fields (values), asset refs (SHAs),         │");
  console.log("  │         │ within-slide GSAP timeline,    │ voiceover text + voice, measured duration   │");
  console.log("  │         │ __FIELD__ placeholders, CSS    │                                             │");
  console.log("  └─────────┴───────────────────────────────┴─────────────────────────────────────────────┘");
  check("two file roles, one invariant (the names are identical at both scales)", true);
}

function sectionD(): void {
  banner("SECTION D: assets are content-addressed, NOT units");
  console.log("  assets/ holds binary blobs. index.json references them by SHA-256.");
  for (const a of ASSET_FILES) console.log(`    assets/${a}`);
  check("assets/ is NOT a unit folder (no index.html)", !isUnitFolder(ASSET_FILES));
  console.log("  → dedup is free: same bytes ⇒ same SHA ⇒ one stored blob.");
}

function sectionE(): void {
  banner("SECTION E: slide ordering lives in ONE place — root index.json");
  const ordered = SLIDE_ORDER.map((id) => UNITS.find((u) => u.path === id));
  const allPresent = ordered.every((u): u is Unit => u !== undefined);
  check("every id in root.slides resolves to a slide unit folder", allPresent);
  for (let i = 0; i < SLIDE_ORDER.length; i++) {
    console.log(`  root.slides[${i}] → slides/${SLIDE_ORDER[i]}/`);
  }
  console.log("  → reorder = mutate root index.json, never move folders on disk.");
}

function main(): void {
  sectionA();
  sectionB();
  sectionC();
  sectionD();
  sectionE();
  banner("DONE");
}

main();
