# HOW_TO_RESEARCH — per-bundle workflow for ovk-web workers

> Read this before building any bundle. It is the contract every bundle follows.

## What a bundle is

A **bundle** is a set of files teaching ONE RFC 0001 concept:

```
bundles/{name}.ts              ← GROUND TRUTH — runnable, prints every value
bundles/{name}_output.txt      ← captured stdout (committed; re-derivable via `just out {name}`)
bundles/{name}_reference.txt   ← web provenance log (URLs + "Verifies:" lines)
bundles/{NAME}.md              ← static guide; output pasted under "> From {name}.ts Section X:" callouts
bundles/{name}.html            ← interactive, zero-dep, recomputes the SAME logic in JS, gold-checked
```

**The one rule:** every number in the `.md`/`.html` was printed by `{name}.ts` or
recomputed with the identical formula. Nothing is hand-computed.

## Style anchor

Before writing your own bundle, **read `bundles/unit_model.ts` and `UNIT_MODEL.md`
and `unit_model.html` end to end.** They define the house style: the
`banner()`/`check()` helpers, the callout format, the pitfalls table, the
gold-check badge, the header badges, the guide-callout, the table-overflow
wrapper. Copy that style exactly.

## STEP 0 — Absorb

1. Read this file.
2. Read `docs/rfc/0001-product-architecture.md` for your assigned section.
3. Read `AGENTS.md` (root of the OpenVideoKit repo) — it is the export-target
   spec (caption rules, bare-`<template>` format, `__PLACEHOLDER__` convention,
   preview-audio pattern).
4. Study the style anchor bundle (`unit_model`).

## STEP 1 — Mine the source

Quote real signatures/schemas from the RFC and AGENTS.md verbatim into your
runnable's comments and your guide. Never paraphrase a schema field or a CSS
rule — copy it.

## STEP 2 — Web-search (MANDATORY, non-skippable)

Verify every fact in **≥2 independent sources** before asserting it. For this
project the primary sources are:

- RFC 0001: `docs/rfc/0001-product-architecture.md` (in-repo)
- `AGENTS.md` (in-repo)
- HyperFrames CLI docs: https://hyperframes.heygen.com/packages/cli
- GSAP docs: https://gsap.com/docs/v3/
- edge-tts: https://github.com/rany2/edge-tts
- MDN for Web APIs (audio, canvas, DOM): https://developer.mozilla.org/

Log every URL into `{name}_reference.txt`, each with a `Verifies:` line stating
exactly what it confirms. If a fact cannot be verified, **flag it in your final
report** — never hide uncertainty.

## STEP 3 — Build (HARD RULES)

1. **Determinism over everything.** No `Date.now()`, no `Math.random()`
   (unless a fixed-seed LCG/mulberry32), no unseeded RNG, no wall-clock as a
   printed value. Sort map keys before iterating. Print floats at fixed
   precision (`.toFixed(6)`).
2. **Use the `banner()`/`check()` helpers** from `scripts/skeleton.ts`. Do not
   use raw `console.assert` for invariants — `check(desc, ok)` prints
   `[check] desc: OK` and exits non-zero on failure, so the sweep flags it.
3. **Start every runnable with `export {};`** so it is its own module (isolated
   top-level scope). Without it, TS merges `BANNER`/`banner`/`check` across
   files and `tsc --noEmit` fails with "Cannot redeclare".
4. **Your runnable must print ≥2 `[check]` lines.** A bundle with zero checks
   is a junior tutorial; re-spawned.
5. **Capture output:** `just out {name}` → `{name}_output.txt`. Re-run must be
   byte-identical.
6. **Guide callouts paste output verbatim**, under `> From {name}.ts Section X:`.
7. **The `.html` recomputes the SAME formula in JS** and shows a gold-check
   badge: `[check: OK]` (green) / `[check: FAIL]` (red). Pick one concrete value
   the `.ts` prints as the gold value; compare in JS.

## STEP 4 — Author the guide (three-layer depth)

A junior tutorial stops at syntax. Our bar is higher. `NAME.md` answers:

1. **What** — the schema/API + a runnable worked example.
2. **Why** — the mechanism beneath it (internals: why bare `<template>`, why
   `getVariables()` is empty in HF sub-comps, why `position:absolute;inset:0;`
   on host divs, the GIL…).
3. **Gotchas** — the silent-bug traps.

Structure (copy the anchor):
- Header block (one-line goal + `tsx bundles/{name}.ts` run cmd + prerequisites)
- Lineage / why this exists (RFC section ref)
- **≥1 mermaid diagram** (```mermaid fenced; see §15.1 rules)
- `> From {name}.ts Section X:` verbatim callouts
- The "why / internals" section
- 🔗 cross-refs to sibling bundles (each with a one-line *why*)
- **Pitfalls table** (trap | symptom | fix) — NON-NEGOTIABLE
- Cheat sheet
- `## Sources` (web-verified URLs)

## STEP 5 — Self-verify

Run, in order, and ensure each is green:

```bash
just out {name}                # capture stdout (must be byte-stable on re-run)
pnpm exec tsx bundles/{name}.ts # run; exits 0; ≥2 [check] lines
just check                     # tsc --noEmit passes
just lint                      # eslint passes (no warnings)
just mermaid                   # all mermaid blocks in NAME.md render
just htmlcheck                 # DOM-mock runtime test on {name}.html passes
```

Then open `{name}.html` in a browser and confirm the gold-check badge is green.

## STEP 6 — Report back

In your final message, return:
- Paths of every file you wrote.
- The `[check]` count your runnable prints.
- The URLs in `{name}_reference.txt` (≥2, each with a "Verifies:" line).
- Any fact you could NOT verify (flagged, not hidden).

## Mermaid rules (GitHub renders it)

- Dotted arrow with label: `A -.->|label| B`. Never `A -.label.> B`.
- Quote edge labels containing `()`, `{}`, or `/`: `|"GET /{key}"|`.
- Do NOT over-quote: `[("DB")]`, `|simple|` work fine unquoted.

## HTML conventions (non-negotiable)

- Header has two badges: `class="badge md"` (📖 green, → `NAME.md`) and
  `class="badge ts"` (📄 orange, → `{name}.ts`). CSS:
  `.badge.md{background:#1c3a25;color:#27ae60;border-color:#27ae60}`
  `.badge.ts{background:#3a2a14;color:#e67e22;border-color:#e67e22}`.
- A `.guide-callout` div right after `</h1>` linking the guide.
- Every `<table>` wrapped in `<div style="overflow-x:auto;min-width:0">`.
- Zero-dep: no external CSS/JS, no CDN. Inline everything. Inline `<style>`
  + `<script>`. (GSAP is allowed ONLY via a CDN `<script>` for animation-demo
  bundles because it is the runtime the RFC mandates — note the exception in the
  guide. For logic bundles, pure vanilla JS.)
- Gold-check badge recomputes the gold value; green = matches `{name}.ts`.
