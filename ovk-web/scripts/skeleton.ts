// {NAME} — ground-truth runnable for the "{concept}" concept (RFC 0001 §X)
// Run: pnpm exec tsx bundles/{name}.ts
// Copy this skeleton, fill it in. Determinism hard rules apply (HOW_TO_RESEARCH.md §STEP 3).

export {}; // make this a module (isolated top-level scope)

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

// ---- deterministic sample data (NO Date.now, NO Math.random, NO FS reads) ----

// ---- sections ----

function sectionA(): void {
  banner("SECTION A: <teachable point>");
  // print values + check(...) invariants
  check("describe invariant", true);
}

function main(): void {
  sectionA();
  banner("DONE");
}

main();
