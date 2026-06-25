// __STEM__.ts — bundle.
//
// GOAL (one line): TODO.
//
// This is the GROUND TRUTH for __STEM_UPPER__.md. Every value below is computed
// by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// Run:
//     pnpm exec tsx __STEM__.ts   (or: just run __STEM__)

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// TODO: sectionA, sectionB, ... each prints a banner + a readable block + checks.

function main(): void {
  console.log("__STEM__.ts — bundle.");
  console.log("Every value below is computed by this file.");
  // sectionA();
  sectionBanner("DONE — all sections printed");
}

main();
