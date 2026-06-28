# brief_checklist — filling the briefs + orchestrator pre-flight + failure dispatch

> The brief is where your judgment as orchestrator lives. **Spend 5 minutes per
> brief; fill every `{BLANK}` before launch.** A lazy brief → a lazy bundle.
> Companion to `worker_prompt_template.md` and `SKILL.md`.

---

## 1. The per-concept `{BLANK}` fields (fill one set per worker)

| Field | What to put | Example |
|---|---|---|
| `{SECTION}` | The repo subfolder. | `rust` / `go` / `systemdesign` |
| `{MEMBER}` | The dep-tier crate / pnpm member, or empty if flat. | `core` (rust) / `web` (ts) / `` (go, python) |
| `{MEMBER_PATH}` | `{SECTION}/{MEMBER}/` or `{SECTION}/`. | `rust/core/` or `go/` |
| `{MODEL_BUNDLES}` | 1–2 already-shipped bundles to copy style from (the style anchor onward). | `rust/core/ownership.rs + OWNERSHIP.md` |
| `{CITE_SOURCES}` | Real docs refs to mine — not paraphrases. | `doc.rust-lang.org/book ch.4; /reference §ownership; std::vec::Vec docs` |
| `{WEB_ANCHORS}` | Official doc URL + a search phrase to start Step 2. | `Rust borrow checker rules book ch.4; aliasing rules; NLL` |
| `{ANCHOR_CONCEPTS}` | The exact behaviors/signatures to verify & assert. | `at most ONE &mut OR many & to one place; a move invalidates the source for non-Copy types` |
| `{SECTION_LIST}` | Suggested runnable teachable points (A/B/C/D). | `A: basic API, B: internals, C: worked example, D: contrast/gotcha` |
| `{MERMAID_IDEAS}` | Diagrams the `.md` should contain. | `ownership flow; borrow-checker decision; scheduler state` |
| `{PINNED_VALUE}` | A concrete output the runnable MUST print — sanity anchor for worker & you. | `Vec capacity after 5 pushes on empty == 8` |
| `{SIBLING_LINKS}` | Which 🔗 bundles to reference, each with a one-line why. | `BORROWING (why a move leaves the source unusable)` |
| `{LINEAGE}` | old→new with WHY (ecosystem bundles) or the mechanism (language bundles). | `done-channel → context.Context (Go 1.7): one cancel cascades the whole tree` |
| `{PHASE_N}` / `{PHASE_THEME}` | The phase this bundle belongs to (from `TODO.md`). | `Phase 4 (Concurrency & the Memory Model)` |

**Rule of thumb:** if you can't fill `{ANCHOR_CONCEPTS}` and `{PINNED_VALUE}`,
you don't understand the concept well enough to delegate it — research it first.

---

## 2. Orchestrator pre-flight checklist (before launching a batch of ≤4)

- [ ] **Paths disjoint.** Each worker's files are disjoint from every other
      worker's in the batch (different stems). This is what makes parallel writes
      safe.
- [ ] **Manifests ready** (language wrinkle): the orchestrator added the batch's
      `[[bin]]` entries (Rust member `Cargo.toml`), deps (`go.mod` /
      `package.json`), or pnpm member dir. Workers cannot edit manifests.
- [ ] **Every brief has** `{CITE_SOURCES}`, `{WEB_ANCHORS}`,
      `{ANCHOR_CONCEPTS}`, and a concrete `{PINNED_VALUE}`.
- [ ] **Style anchor shipped** (Phase 1 / new section): the first bundle exists
      and its path is in every later brief's `{MODEL_BUNDLES}`.
- [ ] **Sweep tooling ready**: `just sweep` (or the equivalent loop) + the
      language gate (`just typecheck` for ts, `just module` for rust/go,
      `just sanitize` for cpp) will run after the batch.
- [ ] **All ≤4 `Task` calls drafted in ONE message** (parallel launch — one
      message, multiple tool calls).

---

## 3. Determinism hard rules (with code — the things that break reproducibility)

These are the recurring traps across all languages. Cite them when re-spawning a
worker whose `_output.txt` drifted. **Goal: byte-identical output on re-run.**

### 3.1 Map / unordered iteration is randomized

**Wrong (output differs every run):**
```go
m := map[string]int{"b": 1, "a": 2}
for k, v := range m { fmt.Println(k, v) }   // random order
```

**Right (sort keys first):**
```go
keys := make([]string, 0, len(m))
for k := range m { keys = append(keys, k) }
slices.Sort(keys)
for _, k := range keys { fmt.Println(k, m[k]) }
```
(Rust/C++: collect `HashMap`/`unordered_map` keys into a `Vec`/`vector`, `sort`,
print — or use `BTreeMap`/`std::map` which ARE ordered.)

### 3.2 Thread / goroutine / async output interleaves nondeterministically

**Wrong (lines in different order each run):**
```go
for i := 0; i < 3; i++ {
    go func(i int) { fmt.Println("worker", i) }(i)
}
```

**Right (collect, sort, print from main after join):**
```go
var wg sync.WaitGroup
out := make(chan string, 3)
for i := 0; i < 3; i++ {
    wg.Add(1)
    go func(i int) { defer wg.Done(); out <- fmt.Sprintf("worker %d", i) }(i)
}
wg.Wait(); close(out)
got := []string{}
for s := range out { got = append(got, s) }
sort.Strings(got)
for _, s := range got { fmt.Println(s) }
```

### 3.3 Unseeded RNG / wall-clock as a printed value

**Wrong:** `rand.Intn(n)` unseeded, `time.Now().Unix()`, `Date.now()`,
`std::chrono::system_clock::now()`, `Math.random()`.

**Right:** fixed seed only.
```python
import random
random.seed(42)          # Python
```
```rust
let mut rng = rand::rng(); rng.seed(rand::SeedableRng::seed_from_u64(42)); // or a hand-rolled LCG
```
```cpp
std::mt19937 rng(42);    // C++
```
Wall-clock may appear only as un-verified context, never as a verified number.

### 3.4 Raw pointer address printed

**Wrong:** `printf("%p", (void*)x)` or `x as *const T as usize` as a value —
varies with ASLR each run.

**Right:** assert structural facts, never the address.
```rust
check("two refs point at the same place", std::ptr::eq(a, b));
check("Vec len == 4, cap >= 4", v.len() == 4 && v.capacity() >= 4);
```

### 3.5 Float drift

**Right:** print to fixed precision if cross-run/cross-compiler drift is possible.
```ts
console.log((0.1 + 0.2).toFixed(6));   // not 0.30000000000000004
```
Never use `-ffast-math` (breaks IEEE-754 determinism).

### 3.6 No raw `assert()` for output invariants

Use a `check(desc, ok)` helper that prints `[check] desc: OK` and panics /
exits non-zero on failure, so the sweep flags it. Plain `assert` is compiled out
under `-DNDEBUG`/`-O2` in some setups — unreliable as a gate. Every skeleton in
`worker_prompt_template.md` §5 ships this helper.

---

## 4. Failure → fix dispatch table (after the sweep)

Workers self-verify, but you independently re-check the whole batch. When a
bundle fails, map the symptom and re-spawn ONE worker for just that bundle:
paste its prior output + the failing check, ask it to fix ONLY the failure.
Don't rewrite from scratch unless the whole bundle is wrong.

| Worker symptom | Cause | Fix |
|---|---|---|
| compile/run fails | borrow-checker / wrong API / missing import / wrong signature | re-spawn with correct `{ANCHOR_CONCEPTS}` + exact signature |
| lint/typecheck/warnings fail (`gofmt`/`clippy`/`ruff`/`tsc`/`-Wall`) | a lint, an `any` leak, unformatted code, unused var | fix the cause; never suppress (`-Wno`/`#[allow]`/`any`) without orchestrator-approved reason noted in `.md` |
| `_output.txt` differs on re-run | nondeterminism (see §3) | re-spawn citing the DETERMINISM hard rules |
| `[check]` count is 0 | worker skipped invariants | re-spawn, emphasize "add a `check(...)` for every invariant" |
| gold-check `[check: FAIL]` in `.html` | JS formula drifted from runnable | re-spawn: copy the runnable's formula verbatim into JS |
| `node --check` fails on `.html` `<script>` | unbalanced brace / JS typo | usually a 1-line fix; re-spawn with the error |
| ASan/UBSan reports issues (cpp) | a real bug — **UB** (use-after-free, OOB, overflow, leak) | re-spawn — correctness failure, not a nit; fix the UB |
| Numbers in `.md` ≠ `_output.txt` | worker hand-typed a table | regenerate via capture, paste verbatim under callouts |
| No `{name}_reference.txt` / `## Sources` | worker skipped web search | re-spawn, make Step 2 non-optional; require the provenance file with >=2 URLs + "Verifies:" lines |
| No pitfalls table | junior tutorial, no expert payoff | re-spawn, cite the three-layer depth rule (SKILL.md §12) |
| Relative links in `.html`/`.md` | `.md`/runnable links must be full GitHub URLs; back-link must be `./index.html` | re-spawn citing the HTML-family rule |
| `cargo check` can't find bin `X` (rust) | orchestrator didn't add `[[bin]]` | add `[[bin]] name="X" path="X.rs"` to the member Cargo.toml (orchestrator job) |
| `main redeclared` (go) | missing `//go:build ignore` first line | re-spawn citing the non-negotiable first-line rule |
| Worker edited another bundle/manifest | brief was loose | restore from git; tighten the "do NOT touch" clause |

---

## 5. Post-flight (after the batch is green)

- [ ] Sweep + language gate green for all bundles in the batch.
- [ ] Spot-checked 2–3 `.md` `> From … Section X:` callouts vs `_output.txt`
      byte-for-byte.
- [ ] Each bundle's `{name}_reference.txt` exists with >=2 URLs and a "Verifies:"
      line per entry.
- [ ] For the interactive flavor, opened 1–2 `.html` in a browser; `[check: OK]`
      badge is green.
- [ ] Re-spawned any failures (max 4 again).
- [ ] Ticked the boxes in `TODO.md`; updated its Progress table.
- [ ] **Style drift:** if new bundles raised the bar (e.g. added a `## Sources`
      section or a value/borrow diagram older bundles lack), queue a
      **style-consistency worker** to backport the old bundles. Its brief edits
      ONLY the named old bundles, changes no computed value (ground truth), and
      re-runs the gate for each. Runs in parallel with the next batch (disjoint
      files → no conflict).

---

## 6. Worked example — orchestrating a batch end to end

Suppose `TODO.md` says the next Phase-1 Rust bundles are `ownership`,
`borrowing`, `lifetimes`, `copy_clone`. The orchestrator:

1. **Adds the `[[bin]]` entries** to `rust/core/Cargo.toml` (workers can't):
   ```toml
   [[bin]]
   name = "ownership"
   path = "ownership.rs"
   # ...borrowing, lifetimes, copy_clone
   ```
2. **Fills 4 briefs** (5 min each). For `ownership` (see the filled brief in
   `worker_prompt_template.md` §7). For `borrowing`, `{ANCHOR_CONCEPTS}` =
   `at most ONE &mut OR many & to one place, never both; a &T is Copy`;
   `{SIBLING_LINKS}` = `OWNERSHIP (why a reference lets you use without owning)`.
   Etc.
3. **Pre-flight:** 4 disjoint stems, manifests ready, each brief has a pinned
   value + web anchors. Style anchor = `ownership` (ship it first if none exist).
4. **Launches 4 `Task` calls in ONE message** — the constant Rust preamble + each
   brief.
5. **Runs `just sweep` + `just module`** when all return.
6. **Re-spawns** e.g. `lifetimes` if clippy failed (`needless_clone`) — paste the
   clippy output, ask it to fix only that.
7. **Ticks `TODO.md`**, spot-checks `OWNERSHIP.md` callouts vs
   `ownership_output.txt`.

That's the whole job. The orchestrator touched no bundle file directly — only
manifests, briefs, and the sweep.
