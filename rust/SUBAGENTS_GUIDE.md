# SUBAGENTS_GUIDE — Delegating Bundle-Building at Scale (Rust)

> A note from past-me to future-me: **how to spin up many `rust/` concept bundles
> in parallel using subagents, without losing rigor.**
>
> This sits **above** [`HOW_TO_RESEARCH.md`](./HOW_TO_RESEARCH.md) (the per-bundle
> workflow). That guide defines *what* a bundle is and *how* to build one. This
> guide defines *how to delegate* that work to many agents at once — the worker
> prompt template, the workspace-manifest discipline, and the verification sweep.
>
> Sister guide: [`../go/SUBAGENTS_GUIDE.md`](../go/SUBAGENTS_GUIDE.md).

```mermaid
graph TD
    ME["YOU (orchestrator)<br/>briefs, manifests, launch, verify — NEVER edit bundles"] -->|add [[bin]] + one prompt each| A1["worker: bundle A"]
    ME --> A2["worker: bundle B"]
    ME --> A3["worker: bundle C ..."]
    ME --> GUIDE["SUBAGENTS_GUIDE.md<br/>(THIS file)"]
    A1 --> WS["shared workspace<br/>rust/ (disjoint member files)"]
    A2 --> WS
    A3 --> WS
    ME -->|after all return| VERIFY["verification sweep<br/>just sweep"]
    style ME fill:#fef9e7,stroke:#f1c40f,stroke-width:3px
    style WS fill:#eafaf1,stroke:#27ae60
    style VERIFY fill:#fdecea,stroke:#c0392b
```

---

## 0. When to use this mode

Use subagent delegation when you need **≥3 concept bundles** built to a uniform
bar. For 1–2 bundles, just build them by hand (follow `HOW_TO_RESEARCH.md`).

**The trap it prevents:** building many things yourself in one session fills
context, quality drifts, and later bundles get sloppy. Subagents each get a
*fresh* context, so bundle #50 is as rigorous as #1.

**The throughput rule:** launch **at most 4 workers per batch** (parallel `Task`
calls in one message). After each batch returns, run `just sweep`, then launch
the next batch of 4.

---

## 1. The mental model: orchestrator + workers (+ the manifest wrinkle)

- **You (the orchestrator)** do NOT write bundle code. Per batch you: (a) **add
  the `[[bin]]` entries** for that batch's bundles to the right member's
  `Cargo.toml` (workers can't), (b) fill one brief per bundle (§3), (c) launch
  workers in parallel — **max 4 per batch**, all `Task` calls in ONE message, (d)
  run the sweep (`just sweep`) after each batch, (e) re-spawn failures.
- **Each worker** owns exactly ONE bundle (its `.rs` + `_output.txt` + `.md`) and
  is told to follow `HOW_TO_RESEARCH.md` to the letter. It is forbidden from
  touching any `Cargo.toml`/`Cargo.lock`, the `Justfile`, `scripts/`,
  `HOW_TO_RESEARCH.md`, `SUBAGENTS_GUIDE.md`, `TODO.md`, any other member folder,
  and any other bundle.
- **The workspace is shared** (`rust/`), but file ownership is disjoint (one
  member per dep-tier; within a batch each worker writes a distinct stem), so
  parallel writes are safe.

> **Manifest wrinkle vs `../go/`:** in Go, a worker just creates `name.go` (no
> manifest entry). In Rust, a bundle **cannot run until its `[[bin]]` is declared**
> in the member `Cargo.toml`. So the orchestrator adds the batch's `[[bin]]`
> entries **before** launching the workers, and the workers create exactly those
> stems' `.rs` files. The member `Cargo.toml` and the `.rs` files stay consistent
> at every batch boundary.

---

## 2. The standard worker prompt (copy this, fill the blanks)

Every worker gets this preamble verbatim, then a per-concept "brief". This is the
single most important artifact in this guide — get it right and the bundles come
back uniform.

```text
You are building ONE "concept bundle" for the Rust learning repo. Work ENTIRELY
inside /Volumes/data/workspace/tutorials/rust/. Do NOT touch any Cargo.toml or
Cargo.lock, the Justfile, HOW_TO_RESEARCH.md, SUBAGENTS_GUIDE.md, TODO.md,
scripts/, or any file that is not part of your assigned bundle. Your bundle lives
in the {MEMBER} member crate.

=== STEP 0: ABSORB THE WORKFLOW (mandatory, do first, in order) ===
1. Read /Volumes/data/workspace/tutorials/rust/HOW_TO_RESEARCH.md IN FULL.
   It is the law: the bundle = {name}.rs (ground truth, a [[bin]] in {MEMBER}) +
   {name}_output.txt (captured stdout) + {NAME}.md (guide). There is NO .html.
   The {MEMBER}/Cargo.toml already declares your [[bin]] — do NOT edit it.
2. Study the canonical model bundle(s) and COPY THEIR STYLE EXACTLY:
   {MODEL_BUNDLES}   # e.g. rust/core/ownership.rs + .md (Phase 1 onward)
   Match: the doc-comment header; the banner()/check() helpers; the section_*()
   print structure of the .rs; the "> From {name}.rs Section X:" verbatim
   callouts + mermaid + pitfalls table + cheat sheet + ## Sources in the .md;
   the three-layer depth (what / why-internals / gotchas). Start from
   scripts/skeleton.rs.

=== STEP 1: MINE THE AUTHORITATIVE SOURCE ===
Read these and quote real code/API/signatures, not paraphrases:
{CITE_SOURCES}   # e.g. "The Rust Book ch.4; the Rust Reference §ownership;
                 #  std::vec::Vec docs; doc.rust-lang.org/nomicon (for unsafe)"

=== STEP 2: FACT-CHECK VIA WEB SEARCH (mandatory, do NOT skip) ===
For every signature, trait bound, edition behavior, and claim: web-search the
official docs (doc.rust-lang.org/book, /reference, /nomicon, /std, /rustc) and
>=1 other authoritative source (Rust Blog, This Week in Rust, Jon Gjengset /
marco19 / Bo Anderson blogs). Verify the EXACT behavior in >=2 places. Record
every URL in a "## Sources" section at the bottom of {NAME}.md.
NEVER guess a signature or a behavior. If you cannot verify a fact, search until
you can, or flag it explicitly in your final report. Start your searches at:
{WEB_ANCHORS}

=== HARD RULES (Rust-specific) ===
- Your file is {MEMBER}/{name}.rs (it is already declared as a [[bin]] — do NOT
  edit any Cargo.toml). Do NOT add a `mod.rs` or a `src/` dir.
- NEVER hand-compute. The .rs prints every value. The .md pastes values verbatim
  under "> From {name}.rs Section X:" callouts.
- DETERMINISM (or _output.txt won't reproduce across runs):
  * HashMap uses a RANDOM seed -> collect keys into a Vec, SORT, then print
    (or use BTreeMap). Never range a HashMap straight to stdout.
  * Pointer addresses (as *const T as usize) vary with ASLR -> NEVER print raw
    addresses as values; assert equality/length/capacity instead.
  * Thread output is nondeterministic -> collect into a Vec (Mutex or channel),
    SORT, print from main() after join. Never print from a thread in sched order.
  * No uncontrolled RNG. The `rand` crate is NOT in any member. If you need
    "random" data, implement a tiny fixed-seed LCG in pure stdlib.
- NO `assert!` for output invariants: use the check(desc, ok) helper (prints
  "[check] ...: OK", panics on failure -> non-zero exit -> the sweep catches it).
- GOFMT/RUSTFMT IS CANON: run `just fmt {name}` before capturing output.
- CLIPPY MUST BE CLEAN: `cargo clippy --bin {name} -- -D warnings` exits 0. Fix
  lints rather than #[allow]-ing them (an #[allow] must be justified in the .md).
- STDLIB-FIRST / tier-correct: use ONLY the deps of the {MEMBER} member
  (core = stdlib only). Do NOT add any dependency or edit Cargo.toml/Cargo.lock.
- Self-contained single file. Tiny-but-complete examples so every value prints
  while every behavior shows. Edition is 2024.
- THREE-LAYER DEPTH in the .md: what (syntax/API) + why (internals) + gotchas.
  MUST end with a pitfalls table + a cheat sheet + ## Sources.

=== DELIVERABLES (exact paths) ===
- /Volumes/data/workspace/tutorials/rust/{MEMBER}/{name}.rs
- /Volumes/data/workspace/tutorials/rust/{MEMBER}/{name}_output.txt
    (produce via:  cd /Volumes/data/workspace/tutorials/rust && just out {name})
- /Volumes/data/workspace/tutorials/rust/{MEMBER}/{NAME}.md

{NAME}.md MUST contain: the lineage/why; mermaid diagrams;
"> From {name}.rs Section X:" verbatim output blocks; a worked smallest-scale
example; a pitfalls table (trap | symptom | fix); a cheat sheet; the ownership/
borrowing/lifetime analysis where relevant; 🔗 cross-references to sibling
bundles; and a "## Sources" section (URLs).

=== VERIFICATION (do ALL of these, then report) ===
Run from /Volumes/data/workspace/tutorials/rust/ :
1. `just check {name}` -> "cargo run: OK", checks printed > 0, "rustfmt: OK",
   "clippy: clean", "output.txt: present".
2. `just out {name}` -> {name}_output.txt non-empty; byte-identical on a 2nd run.
3. Every "[check] ...: OK" line in _output.txt is mirrored verbatim under a
   "> From {name}.rs Section X:" callout in the .md.

=== REPORT BACK (your final message) ===
- The 3 file paths created.
- Check result: how many "[check] ... OK" printed, and the `just check {name}`
  verdict.
- Web sources used (list URLs).
- Any fact you could NOT verify (do not hide uncertainty).

=== YOUR CONCEPT BRIEF ===
Bundle name: {name} / {NAME}
Member: {MEMBER}
Phase: {PHASE_N} ({PHASE_THEME})
Lineage (old -> new / why): {LINEAGE}
Anchor concepts/signatures (verify on web, implement in the .rs, assert):
  {ANCHOR_CONCEPTS}
Suggested .rs sections: {SECTION_LIST}
Suggested mermaid in .md: {MERMAID_IDEAS}
A concrete value the .rs must print (pin it so you can sanity-check):
  {PINNED_VALUE_OR_HOW_TO_DERIVE_IT}
Cross-references to wire up: {SIBLING_LINKS}
```

The `{BLANK}` fields are the only thing that changes between workers. Everything
else is constant.

> **Bootstrap note (Phase 1 only):** the first bundle has no model to copy. Give
> it a richer brief (spell out the banner/check helpers, the callout format, the
> pitfalls columns), then designate it the style anchor for all later workers by
> putting its path in `{MODEL_BUNDLES}`.

---

## 3. Filling the brief — the per-concept fields

| Field | What to put |
|---|---|
| `{MEMBER}` | The dep-tier crate the bundle lives in (`core` / `serde` / `async` / `web` / `db` / `pmacros-demo`). |
| `{MODEL_BUNDLES}` | 1–2 already-shipped bundles to copy style from (Phase 1's anchor onward). |
| `{CITE_SOURCES}` | Real docs refs: `doc.rust-lang.org/book#...`, `/reference`, `/nomicon`, `/std/<module>`. |
| `{WEB_ANCHORS}` | Doc URL + a search phrase, e.g. "Rust borrow checker rules book ch.4; aliasing rules; NLL". |
| `{ANCHOR_CONCEPTS}` | The exact behaviors/signatures to verify & assert, e.g. "at most ONE `&mut` OR many `&` to the same place, never both; a move invalidates the source for non-Copy types". |
| `{SECTION_LIST}` | Suggested teachable points (A: the basic API, B: internals, C: worked example, D: contrast/gotcha). |
| `{PINNED_VALUE}` | A concrete output the .rs must print, so the worker (and you) can sanity-check. |
| `{SIBLING_LINKS}` | Which 🔗 bundles to reference, e.g. "BORROWING (why a move leaves the source unusable)". |

**Rule of thumb:** spend 5 minutes on the brief. A lazy brief → a lazy bundle.

---

## 4. Coordination rules (keep the swarm safe)

1. **Disjoint file ownership.** Each worker writes only its 3 files in its member.
   State the exact paths and forbid edits elsewhere (any `Cargo.toml`/`Cargo.lock`,
   the `Justfile`, `scripts/`, other members, other bundles). Parallel writes are
   safe because stems are distinct.
2. **No manifest/dep edits by workers.** All `Cargo.toml`/`Cargo.lock` are
   read-only to workers. The orchestrator adds the batch's `[[bin]]` entries
   (and any new deps) between/in batches.
3. **Max 4 workers per batch.** Send up to 4 worker `Task` calls in ONE message.
   Sweep, then the next 4.
4. **One concept per worker.** Never let a worker build two bundles.

---

## 5. The verification sweep (do this after EACH batch returns)

Workers self-verify, but you independently re-check the whole batch:

```bash
cd /Volumes/data/workspace/tutorials/rust
just sweep
```

That single command loops every `.rs`, runs it, counts `[check]`s, checks rustfmt
+ clippy (`-D warnings`), and confirms `_output.txt` presence. Then spot-check:
open 2–3 `.md` files, confirm a couple of `> From ... Section X:` callouts match
the corresponding `_output.txt` byte-for-byte. Also run `just module`
(`cargo check --workspace`) once per phase to confirm the manifests are coherent.

**Re-spawn failures.** Any bundle that fails the sweep: re-launch ONE worker for
just that bundle, paste its prior output + the failing check as context, ask it
to fix only the failure. Don't rewrite from scratch unless the whole bundle is
wrong. Common fixes are mapped in `HOW_TO_RESEARCH.md` §9.

---

## 6. Handling style drift (the "improve existing" worker)

When new bundles raise the bar (e.g. they add a value/borrow diagram older
bundles lack), spawn a **style-consistency worker** to backport. Its brief edits
ONLY the named old bundles, changes no computed value (ground truth), and
re-runs `just check` for each. Run it in parallel with new-bundle workers
(disjoint files).

---

## 7. Common failure modes (and the fix)

| Worker symptom | Cause | Fix |
|---|---|---|
| `cargo run` compile error | borrow-checker / wrong API / missing dep | re-spawn with correct `{ANCHOR_CONCEPTS}` + exact signature |
| `clippy` fails `-D warnings` | a lint (needless clone, `unwrap`, redundant closure) | re-spawn: fix the lint; justify any `#[allow]` in the `.md` |
| `_output.txt` differs on re-run | unsorted `HashMap` / unsynced threads / printed address / unseeded LCG | re-spawn citing the DETERMINISM hard rules |
| `[check]` count is 0 | worker skipped invariants | re-spawn, emphasize "add `check(...)` for every invariant" |
| `rustfmt --check` non-empty | worker didn't format | `just fmt {name}`; or re-spawn |
| `cargo check` can't find bin `X` | orchestrator didn't add the `[[bin]]` | add `[[bin]]` to the member Cargo.toml (orchestrator job) |
| Numbers in `.md` don't match `_output.txt` | worker hand-typed | re-spawn, emphasize verbatim; `just out {name}` |
| No `## Sources` | worker skipped web search | re-spawn, make Step 2 non-optional |
| No pitfalls table | junior tutorial | re-spawn, cite the "expert payoff" (`HOW_TO_RESEARCH.md` §3) |
| Worker edited a `Cargo.toml`/another bundle | brief was loose | restore from git; tighten the "do NOT touch" clause |

---

## 8. The batch-run checklist (orchestrator's pre-flight)

Before launching a batch of up to 4 workers:
- [ ] The batch's `[[bin]]` entries are added to the right member's `Cargo.toml`.
- [ ] Any new member crate + its `Cargo.toml` + workspace `members` entry exists.
- [ ] Each worker's 3 file paths are disjoint from every other worker's.
- [ ] Each brief has `{CITE_SOURCES}`, `{WEB_ANCHORS}`, `{ANCHOR_CONCEPTS}`.
- [ ] Each brief has a concrete `{PINNED_VALUE}`.
- [ ] For Phase 1, the first bundle is the style anchor.
- [ ] `just sweep` and `just module` are your post-batch checks.

After the batch returns:
- [ ] `just sweep` green for all bundles in the batch.
- [ ] `just module` reports the workspace coherent.
- [ ] Spot-checked 2–3 `.md` callouts against `_output.txt`.
- [ ] Re-spawned failures (max 4 again).
- [ ] Ticked the boxes in [`TODO.md`](./TODO.md); updated its Progress table.

---

## 9. Why this works (and where it breaks)

- **Fresh context per bundle** → bundle #50 is as rigorous as #1.
- **Disjoint file ownership** → safe parallel writes; no merge conflicts.
- **The constant preamble** → uniform style without micromanaging.
- **The `Justfile` sweep** → one command catches every silent failure: a
  non-deterministic output, a clippy lint, an unformatted file, or a missing
  `_output.txt`.
- **The brief is the leverage** → your judgment is concentrated in 5-minute
  briefs, not 50-minute hand-writes.

Where it breaks: if a brief is vague, the worker guesses; if you skip the sweep,
silent bugs ship. **The brief + the sweep are non-negotiable.** Everything else
is automation.
