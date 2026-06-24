# SUBAGENTS_GUIDE — Delegating Bundle-Building at Scale (Go)

> A note from past-me to future-me: **how to spin up many `go/` concept bundles in
> parallel using subagents, without losing rigor.**
>
> This sits **above** [`HOW_TO_RESEARCH.md`](./HOW_TO_RESEARCH.md) (which is the
> per-bundle workflow). That guide defines *what* a bundle is and *how* to build
> one. This guide defines *how to delegate* that work to many agents at once —
> the worker prompt template, the coordination rules, and the verification sweep.
>
> Sister guide: [`../llm/SUBAGENTS_RESEARCH_GUIDE.md`](../llm/SUBAGENTS_RESEARCH_GUIDE.md)
> — the same delegation discipline for LLM-systems bundles.

```mermaid
graph TD
    ME["YOU (orchestrator)<br/>write briefs, launch, verify — NEVER edit bundles"] -->|one prompt each| A1["worker: bundle A"]
    ME --> A2["worker: bundle B"]
    ME --> A3["worker: bundle C ..."]
    ME --> GUIDE["SUBAGENTS_GUIDE.md<br/>(THIS file)"]
    A1 --> WS["shared workspace<br/>go/ (disjoint files)"]
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
bar. For 1–2 bundles, just build them by hand (follow `HOW_TO_RESEARCH.md`) —
the overhead of writing tight prompts and running a verification sweep isn't
worth it. The moment you're doing a whole phase (Phase 1, Phase 2…), delegate.

**The trap it prevents:** when you build many things yourself in one session,
context fills up, quality drifts, and the later bundles get sloppy. Subagents
each get a *fresh* context, so bundle #52 is as rigorous as bundle #1.

**The throughput rule:** launch **at most 4 workers per batch** (parallel
`Task` calls in one message). After each batch returns, run `just sweep`, then
launch the next batch of 4. This keeps the swarm observable and failures
isolated.

---

## 1. The mental model: orchestrator + workers

- **You (the orchestrator)** do NOT write bundle code. You: (a) write the worker
  prompt template (§2), (b) fill one brief per bundle (§3), (c) launch workers in
  parallel — **max 4 per batch**, all `Task` calls in ONE message, (d) run the
  verification sweep (`just sweep`) after each batch, (e) re-spawn any worker
  that failed verification.
- **Each worker** owns exactly ONE bundle (its `.go` + `_output.txt` + `.md`) and
  is told to follow `HOW_TO_RESEARCH.md` to the letter. It is forbidden from
  touching any other bundle's files, the `Justfile`, `go.mod`/`go.sum`,
  `scripts/`, `HOW_TO_RESEARCH.md`, `SUBAGENTS_GUIDE.md`, and `TODO.md`.
- **The workspace is shared** (`go/`), but file ownership is disjoint, so
  parallel writes are safe.

---

## 2. The standard worker prompt (copy this, fill the blanks)

Every worker gets this preamble verbatim, then a per-concept "brief". This is the
single most important artifact in this guide — get it right and the bundles come
back uniform.

```text
You are building ONE "concept bundle" for the Go learning repo. Work ENTIRELY
inside /Volumes/data/workspace/tutorials/go/. Do NOT touch any file that is not
part of your assigned bundle, and do NOT edit go.mod, go.sum, Justfile,
HOW_TO_RESEARCH.md, SUBAGENTS_GUIDE.md, TODO.md, or anything under scripts/.

=== STEP 0: ABSORB THE WORKFLOW (mandatory, do first, in order) ===
1. Read /Volumes/data/workspace/tutorials/go/HOW_TO_RESEARCH.md IN FULL.
   It is the law: the bundle = {name}.go (ground truth) +
   {name}_output.txt (captured stdout) + {NAME}.md (guide). There is NO .html.
2. Study the canonical model bundle(s) and COPY THEIR STYLE EXACTLY:
   {MODEL_BUNDLES}   # e.g. go/values_types_zero.go + .md (Phase 1 onward)
   Match: the //go:build ignore FIRST line; the banner()/sectionBanner()/
   check() helpers; the section_*() print structure of the .go; the
   "> From {name}.go Section X:" verbatim callouts + mermaid + pitfalls table +
   cheat sheet + ## Sources in the .md; the three-layer depth
   (what / why-internals / gotchas). Start from scripts/skeleton.go.

=== STEP 1: MINE THE AUTHORITATIVE SOURCE ===
Read these and quote real code/API/signatures, not paraphrases:
{CITE_SOURCES}   # e.g. "go.dev/ref/spec §Variables; effective go; pkg.go.dev"

=== STEP 2: FACT-CHECK VIA WEB SEARCH (mandatory, do NOT skip) ===
For every signature, version, and behavioral claim: web-search the official docs
(go.dev/ref/spec, go.dev/ref/mem, go.dev/blog/*, pkg.go.dev) and >=1 other
authoritative source (Dave Cheney / rhys Hiltner / Cockroach / Ardan blogs).
Verify the EXACT behavior in >=2 places. Record every URL in a "## Sources"
section at the bottom of {NAME}.md.
NEVER guess a signature or a number. If you cannot verify a fact, search until
you can, or flag it explicitly in your final report. Start your searches at:
{WEB_ANCHORS}

=== HARD RULES (Go-specific) ===
- FIRST line of {name}.go MUST be exactly: //go:build ignore  (then a blank
  line, then the doc comment + package main). Without it the whole module breaks
  (redeclared main). This is non-negotiable.
- NEVER hand-compute. The .go prints every value. The .md pastes values verbatim
  under "> From {name}.go Section X:" callouts.
- DETERMINISM (or _output.txt won't reproduce):
  * Map iteration is randomized -> SORT keys before printing (slices.Sort).
  * Goroutine output is nondeterministic -> collect into a slice, SORT, print
    from main() after all goroutines join. Never fmt.Print directly from a
    goroutine.
  * Seeded RNG only (math/rand/v2 with a fixed seed). Never derive a printed
    value from time.Now().
- NO `assert`: use the check(description, ok) helper (prints "[check] ...: OK",
  panics on failure -> non-zero exit -> the sweep catches it).
- GOFMT IS CANON: run `just fmt {name}` (gofmt + goimports) before capturing
  output. Unformatted code fails verification.
- GO VET MUST PASS: `go vet {name}.go` exits 0. Note vet fails on diagnostics
  like a fmt.Println with a redundant trailing \n — use Println WITHOUT \n.
- STDLIB-FIRST: use ONLY the deps already in go.mod for this phase
  (Phase 1-5 are pure stdlib). Do NOT add any dependency or edit go.mod/go.sum.
  If you "need" another lib, implement from scratch (more educational) or flag it.
- Self-contained single file (no sibling-package imports). Tiny-but-complete
  examples so every value prints while every behavior shows.
- VALUE-VS-POINTER is a teaching axis: when a section touches a type, the .md
  must say whether receiver/arg is a value or pointer, whether it copies or
  aliases, and whether it escapes to the heap.

=== DELIVERABLES (exact paths) ===
- /Volumes/data/workspace/tutorials/go/{name}.go
- /Volumes/data/workspace/tutorials/go/{name}_output.txt
    (produce via:  just out {name}     # == go run {name}.go > {name}_output.txt 2>/dev/null)
- /Volumes/data/workspace/tutorials/go/{NAME}.md

{NAME}.md MUST contain: the lineage old->new with WHY each step happened (for
ecosystem bundles) or the mechanism (for language bundles); mermaid diagrams;
"> From {name}.go Section X:" verbatim output blocks; a worked smallest-scale
example; a pitfalls table (trap | symptom | fix); a cheat sheet; the value-vs-
pointer analysis where relevant; cross-references to sibling bundles; and a
"## Sources" section (URLs).

=== VERIFICATION (do ALL of these, then report) ===
Run from /Volumes/data/workspace/tutorials/go/ :
1. `just check {name}` -> "go run: OK", checks printed > 0, gofmt: OK, go vet: OK.
2. `just out {name}` -> {name}_output.txt non-empty; byte-identical on a 2nd run.
3. Every "[check] ...: OK" line in _output.txt is mirrored verbatim under a
   "> From {name}.go Section X:" callout in the .md.

=== REPORT BACK (your final message) ===
- The 3 file paths created.
- Check result: how many "[check] ... OK" printed, and `just check` verdict.
- Web sources used (list URLs).
- Any fact you could NOT verify (do not hide uncertainty).

=== YOUR CONCEPT BRIEF ===
Bundle name: {name} / {NAME}
Phase: {PHASE_N} ({PHASE_THEME})
Lineage (old -> new): {LINEAGE}
Anchor concepts/signatures (verify on web, implement in the .go, assert):
  {ANCHOR_CONCEPTS}
Suggested .go sections: {SECTION_LIST}
Suggested mermaid in .md: {MERMAID_IDEAS}
A concrete value the .go must print (pin it so you can sanity-check):
  {PINNED_VALUE_OR_HOW_TO_DERIVE_IT}
Cross-references to wire up: {SIBLING_LINKS}
```

The `{BLANK}` fields are the only thing that changes between workers. Everything
else is constant — that's what keeps the bundles uniform.

> **Bootstrap note (Phase 1 only):** the very first bundle has no model to copy.
> Give it a richer brief (spell out the banner style, the callout format, the
> pitfalls-table columns), then designate it the style anchor for all later
> workers by putting its path in `{MODEL_BUNDLES}`.

---

## 3. Filling the brief — the per-concept fields

For each concept you delegate, you (orchestrator) fill in:

| Field | What to put |
|---|---|
| `{MODEL_BUNDLES}` | 1–2 already-shipped bundles to copy style from (Phase 1's first bundle onward). |
| `{CITE_SOURCES}` | Real docs refs: `go.dev/ref/spec#...`, `go.dev/ref/mem`, `go.dev/blog/...`, `pkg.go.dev/<pkg>`. |
| `{WEB_ANCHORS}` | Official doc URL + a search phrase, e.g. "go memory model go.dev/ref/mem; happens-before channels; Dave Cheney channel axioms". |
| `{ANCHOR_CONCEPTS}` | The exact behaviors/signatures to verify & assert, e.g. "a nil interface value == nil only when BOTH type and value are nil; a typed nil pointer stored in an interface is NOT nil". |
| `{SECTION_LIST}` | Suggested teachable points (A: the basic API, B: internals, C: worked example, D: contrast/gotcha). |
| `{PINNED_VALUE}` | A concrete output the .go must print, so the worker (and you) can sanity-check. |
| `{SIBLING_LINKS}` | Which 🔗 bundles to reference, e.g. "ESCAPE_ANALYSIS (why a pointer receiver arg may escape to the heap)". |

**Rule of thumb:** spend 5 minutes on the brief. A lazy brief → a lazy bundle.
The brief is where your judgment as orchestrator actually lives.

---

## 4. Coordination rules (keep the swarm safe)

1. **Disjoint file ownership.** Each worker writes only its 3 files. State the
   exact paths in the prompt and forbid edits elsewhere (including `Justfile`,
   `go.mod`, `scripts/`, and all other bundles). This makes parallel writes safe.
2. **No dependency edits.** `go.mod` / `go.sum` are read-only to workers. If a
   worker "needs" another lib, it implements from scratch — or you add the dep
   between batches (and run `go mod tidy`).
3. **Max 4 workers per batch.** Send up to 4 worker `Task` calls in ONE message.
   After they return + you sweep, launch the next 4. Independent file ownership =
   safe concurrency; small batches = observable, recoverable failures.
4. **One concept per worker.** Never let a worker build two bundles — context
   splits and both degrade. A huge concept is still one worker with a richer brief.

---

## 5. The verification sweep (do this after EACH batch returns)

Workers self-verify, but you independently re-check the whole batch. Run it with
the Justfile (it loops every `.go`, runs it, counts `[check]`s, checks gofmt +
`go vet`, and confirms `_output.txt` presence):

```bash
cd /Volumes/data/workspace/tutorials/go
just sweep
```

That single command is the whole sweep. Then spot-check: open 2–3 `.md` files,
confirm a couple of `> From ... Section X:` callouts match the corresponding
`_output.txt` values byte-for-byte. Also run `just module` once per phase to
confirm every new bundle carries the `//go:build ignore` tag.

**Re-spawn failures.** Any bundle that fails the sweep: re-launch ONE worker for
just that bundle, paste its prior output + the failing check as context, and ask
it to fix only the failure. Don't rewrite from scratch unless the whole bundle is
wrong. Common fixes are mapped in §7.

---

## 6. Handling style drift (the "improve existing" worker)

When new bundles raise the bar (e.g. they add a `## Sources` section, or a
value-vs-pointer analysis, that older bundles lack), spawn a **style-consistency
worker** to backport. Its brief:

```text
Bring the EXISTING bundles up to the current house style. Edit ONLY:
  {OLD_BUNDLE_PATHS}   # the specific files to backport
Do NOT change any computed value (they are ground truth — the .go output). Do
NOT touch the new bundles. Conformance checklist per bundle:
  - .md has a "## Sources" section with go.dev URLs.
  - .md has the value-vs-pointer analysis where relevant.
  - .md cross-references the new sibling bundles where relevant (links).
  - .go / .md style matches the new bundles (banners, callouts, pitfalls table).
  - .go still has //go:build ignore as the first line; gofmt clean; go vet passes.
Verify: re-run `just check {name}` for each (must still pass); report what changed.
```

Run this worker **in parallel** with the new-bundle workers — it edits disjoint
files (the old bundles), so there's no conflict.

---

## 7. Common failure modes (and the fix)

| Worker symptom | Cause | Fix |
|---|---|---|
| `go run: FAILED` (compile error) | bad logic / wrong API / missing import | re-spawn with the correct `{ANCHOR_CONCEPTS}` + exact signature |
| `go vet: FAIL` | a diagnostic, e.g. `Println` with redundant `\n`, or unreachable code | re-spawn: use `Println` WITHOUT `\n`; remove dead code; the sweep's vet line shows the file:line |
| `_output.txt` differs on re-run | unsorted map / unsynced goroutine output / unseeded RNG / `time.Now()` | re-spawn citing the DETERMINISM hard rules (sort keys; serialize goroutine output; seed RNG) |
| `[check]` count is 0 | worker skipped invariants | re-spawn, emphasize "add a `check(...)` for every invariant" |
| `gofmt: NEEDS FORMAT` | worker didn't format | run `just fmt {name}`; or re-spawn with "format before capture" |
| `module` recipe: "MISSING tag: X" | a bundle lacks `//go:build ignore` as first line | re-spawn citing the non-negotiable first-line rule |
| Numbers in `.md` don't match `_output.txt` | worker hand-typed a table | re-spawn, emphasize "paste verbatim under callouts"; run `just out {name}` to regenerate |
| No `## Sources` | worker skipped web search | re-spawn, make Step 2 non-optional |
| No pitfalls table | worker wrote a junior tutorial | re-spawn, cite the "expert payoff" (HOW_TO_RESEARCH.md §3) |
| Worker edited another bundle's file (or go.mod/Justfile) | brief was loose | restore from git; tighten the "do NOT touch" clause |

---

## 8. The batch-run checklist (orchestrator's pre-flight)

Before launching a batch of up to 4 workers:
- [ ] `go.mod` has the phase's deps (Phase 1–5: none); `go build`/`just module` clean.
- [ ] Each worker's 3 file paths are disjoint from every other worker's in the batch.
- [ ] Each brief has `{CITE_SOURCES}`, `{WEB_ANCHORS}`, `{ANCHOR_CONCEPTS}`.
- [ ] Each brief has a concrete `{PINNED_VALUE}` (or a way to derive it).
- [ ] For Phase 1, the first bundle is designated the style anchor (ship it solo or first).
- [ ] `just sweep` and `just module` are your post-batch checks.

After the batch returns:
- [ ] `just sweep` green for all bundles in the batch.
- [ ] `just module` reports all bundles tagged.
- [ ] Spot-checked 2–3 `.md` callouts against `_output.txt`.
- [ ] Re-spawned any failures (max 4 again).
- [ ] Ticked the boxes in [`TODO.md`](./TODO.md); updated its Progress table.

---

## 9. Why this works (and where it breaks)

- **Fresh context per bundle** → bundle #52 is as rigorous as #1. (This is the
  whole point; it's why hand-building many in one session degrades.)
- **Disjoint file ownership** → safe parallel writes; no merge conflicts.
- **The constant preamble** → uniform style without you micromanaging each.
- **The `Justfile` sweep** → one command (`just sweep`) catches every silent
  failure: a worker that reported OK but shipped a non-deterministic output, a
  vet warning, a missing `//go:build ignore`, or an unformatted file.
- **The brief is the leverage** → your judgment is concentrated in 5-minute
  briefs, not 50-minute hand-writes.

Where it breaks: if a brief is vague, the worker guesses; if you skip the sweep,
silent bugs ship. **The brief + the sweep are non-negotiable.** Everything else
is automation.
