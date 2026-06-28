# worker_prompt_template — the constant worker preamble

> The operational artifact: copy this, substitute the `{BLANK}` and language-knob
> fields, send it as ONE worker's prompt. **Everything outside the `{BLANK}` /
> `{KNOB}` placeholders is constant across all workers** — that uniformity is
> what keeps bundles consistent. The only thing that varies is the brief block.
>
> Companion: `brief_checklist.md` (how to fill the blanks + pre-flight).

---

## 1. Generic paths

These placeholders decouple the template from any specific repo:

| Placeholder | Meaning | Example |
|---|---|---|
| `{PROJECT_ROOT}` | The learning repo root | `/Volumes/data/workspace/tutorials` |
| `{SECTION}` | The subfolder holding this curriculum | `rust`, `go`, `systemdesign` |
| `{MEMBER}` | Dep-tier crate / pnpm member, or empty | `core` (rust), `web` (ts), `` (go/python) |
| `{MEMBER_PATH}` | `{SECTION}/{MEMBER}/` or `{SECTION}/` | `rust/core/` or `go/` |
| `{GITHUB_BASE}` | Base for full URLs in `.html`/`.md` headers | `https://github.com/quanhua92/tutorials/blob/main` |

---

## 2. Language knobs (substitute into the preamble)

| Knob | go | rust | python | ts | cpp | `.html`-family (py + interactive) |
|---|---|---|---|---|---|---|
| `{EXT}` | `.go` | `.rs` | `.py` | `.ts` | `.cpp` | `.py` |
| `{LANG}` | Go | Rust | Python | TypeScript | C++ | Python |
| `{RUN}` | `go run {name}.go` | `cargo run --bin {name}` | `uv run python {name}.py` | `pnpm exec tsx {name}.ts` | `just run {name}` | `python3 {name}.py` |
| `{CAPTURE}` | `go run {name}.go > {name}_output.txt 2>/dev/null` | `cargo run --bin {name} > {name}_output.txt 2>/dev/null` | `uv run python {name}.py > {name}_output.txt 2>/dev/null` | `pnpm exec tsx {name}.ts > {name}_output.txt 2>/dev/null` | `just out {name}` | `python3 {name}.py > {name}_output.txt 2>/dev/null` |
| `{LINT}` | `gofmt -l {name}.go` empty + `go vet {name}.go` exit 0 | `cargo fmt --check` + `cargo clippy --bin {name} -- -D warnings` | `ruff check {name}.py` (+ `mypy {name}.py` for type bundles) | `tsc --noEmit` strict + `noUncheckedIndexedAccess` | `-Wall -Wextra -Wpedantic` clean + ASan/UBSan | `node --check` on extracted `<script>` |
| `{INTERNALS}` | value-vs-pointer, GMP scheduler, escape analysis, memory model | ownership/borrow/lifetime, borrow checker, Send/Sync, unsafe | data model (dunders), CPython internals, refcounting, GIL | value-vs-reference, event loop, type system | value/ref/ptr, RAII, move, templates, **UB** | (per section focus) |
| `{HAS_HTML}` | no | no | no | no | no | **yes** |
| `{ACCENT}` | — | — | — | — | — | teal `#1abc9c` (llm/interview) · emerald `#2ecc71` (systemdesign) · pink `#e91e63` (analytics) · cyan `#00bcd4` (csfundamentals) · amber `#f39c12` (lowleveldesign) |
| `{MANIFEST_RULE}` | first line MUST be `//go:build ignore` | the member `Cargo.toml` already declares your `[[bin]]`; do NOT edit any `Cargo.toml` | do NOT edit `pyproject.toml`/`uv.lock` | run via tsx; never compile a `.js` into source; do NOT edit `package.json`/`tsconfig` | compile to `/tmp`, never in-source | (none) |

---

## 3. The preamble (send this, filled in)

```text
You are building ONE "concept bundle" for the {LANG} learning repo. Work ENTIRELY
inside {PROJECT_ROOT}/{MEMBER_PATH}. Do NOT touch any file that is not part of
your assigned bundle, and do NOT edit any manifest (Cargo.toml, go.mod,
package.json, pnpm-lock.yaml, pyproject.toml, uv.lock, tsconfig*.json), the
Justfile, anything under scripts/, HOW_TO_RESEARCH.md, SUBAGENTS_GUIDE.md,
TODO.md, or any other bundle. {MANIFEST_RULE}

=== STEP 0: ABSORB THE WORKFLOW (mandatory, do first, in order) ===
1. Read {PROJECT_ROOT}/{SECTION}/HOW_TO_RESEARCH.md IN FULL.
   It is the law: the bundle = {name}{EXT} (GROUND TRUTH, prints every value) +
   {name}_output.txt (captured stdout) + {NAME}.md (guide){HTML_CLAUSE}.
2. Study the canonical model bundle(s) and COPY THEIR STYLE EXACTLY:
   {MODEL_BUNDLES}
   Match: the doc-comment header; the banner()/sectionBanner()/check() helpers;
   the section_*() print structure of the runnable file; the
   "> From {name}{EXT} Section X:" verbatim callouts + mermaid + pitfalls table +
   cheat sheet + ## Sources in the .md; the three-layer depth
   (what / why-internals / gotchas). Start from scripts/skeleton{EXT}.

=== STEP 1: MINE THE AUTHORITATIVE SOURCE ===
Read these and quote real code/API/signatures, not paraphrases:
{CITE_SOURCES}

=== STEP 2: FACT-CHECK VIA WEB SEARCH (mandatory, do NOT skip) ===
For every signature, version, formula, and behavioral claim: web-search the
official docs and >=1 other authoritative source. Verify the EXACT fact in >=2
places. NEVER guess a signature or a number. If you cannot verify a fact, search
until you can, or flag it explicitly in your final report. Start your searches at:
{WEB_ANCHORS}

LOG every reference into {name}_reference.txt (a committed provenance file), one
entry per URL, in this exact format so the sweep can grep it:
    [1] <full URL>
        <source name + authority, e.g. "Rust Book ch.4 S1 (official)">
        Verifies: <the exact claim/signature/value this source supports>
    [2] <full URL>
        ...
THEN mirror a trimmed URL list into the "## Sources" section at the bottom of
{NAME}.md (the reader-facing summary). {name}_reference.txt is the full log with
provenance; ## Sources is its public face. Both are mandatory.

=== HARD RULES ({LANG}-specific) ===
- {MANIFEST_RULE}
- NEVER hand-compute. The runnable prints every value. The .md pastes values
  verbatim under "> From {name}{EXT} Section X:" callouts. No orphan numbers.
- DETERMINISM (or _output.txt won't reproduce across runs):
  * Map / unordered container iteration is randomized/unspecified -> collect keys
    into an array, SORT, then print (or use an ordered BTreeMap/Map). Never range
    a map straight to stdout.
  * Thread / goroutine / async output is nondeterministic -> collect into a
    container (Mutex/channel/array), SORT, print from main() after all join.
    Never print from a worker thread in scheduling order.
  * Seeded RNG only (fixed seed). NEVER derive a printed value from wall-clock
    (time.Now() / Date.now() / system_clock::now() / unseeded rand()).
  * Pointer addresses vary with ASLR -> NEVER print a raw address as a value;
    assert structural facts (equality, length, capacity) instead.
  * Floats: print to fixed precision if drift across runs/compilers is possible.
  * Integer overflow: note debug vs release semantics; use checked_*/wrapping_*
    deliberately where relevant, and say so in the .md.
- NO raw assert(): use the check(description, ok) helper (prints
  "[check] desc: OK", panics / exits non-zero on failure -> the sweep catches it).
- LINT/GATE IS CANON: {LINT}. An unformatted file / lint / warning / type error
  is an automatic verification FAIL. Fix the cause; do not suppress (-Wno /
  #[allow] / `any` / eslint-disable) without an orchestrator-approved reason
  noted in the .md.
- STDLIB-FIRST / tier-correct: use ONLY the deps of your member/manifest for this
  phase. Do NOT add any dependency or edit any manifest. If you "need" a lib,
  implement from scratch (more educational) — or flag it.
- Self-contained single file. Tiny-but-complete examples (4-element slice, 3-field
  struct, D=8/L=4) so every value prints while every behavior shows.
- THREE-LAYER DEPTH in the .md: what (syntax/API) + why ({INTERNALS}) + gotchas.
  MUST end with a pitfalls table (trap | symptom | fix) + a cheat sheet + ## Sources.
- VALUE-VS-REFERENCE is a teaching axis where relevant: say whether a receiver/arg
  is copied, aliased (ref/pointer), or owns; whether it escapes to the heap.

=== DELIVERABLES (exact paths) ===
- {PROJECT_ROOT}/{MEMBER_PATH}{name}{EXT}
- {PROJECT_ROOT}/{MEMBER_PATH}{name}_output.txt
    (produce via:  {CAPTURE})
- {PROJECT_ROOT}/{MEMBER_PATH}{name}_reference.txt
    (web provenance log from STEP 2; one [N] entry per URL + what it verifies)
- {PROJECT_ROOT}/{MEMBER_PATH}{NAME}.md
{HTML_DELIVERABLE_CLAUSE}

{NAME}.md MUST contain: the lineage old->new with WHY each step happened (for
ecosystem bundles) or the mechanism (for language bundles); mermaid diagrams
(>=1; ALL diagrams MUST be mermaid fenced blocks — NEVER ASCII art or embedded
images; mermaid renders natively on GitHub/GitLab and stays diffable); "> From
{name}{EXT} Section X:" verbatim output blocks; a worked smallest-scale
example; a pitfalls table (trap | symptom | fix); a cheat sheet; the {INTERNALS}
analysis where relevant; cross-references to sibling bundles (each link with a
one-line WHY it matters); and a "## Sources" section (mirrors {name}_reference.txt;
URLs, web-verified >=2).

=== VERIFICATION (do ALL of these, then report) ===
Run from {PROJECT_ROOT}/{SECTION}/ :
1. {RUN} runs clean; every "[check] ... OK" prints (count > 0).
2. {CAPTURE} -> {name}_output.txt non-empty AND byte-identical on a 2nd run
   (determinism: sorted maps, serialized thread output, seeded RNG, no addresses).
3. {LINT} passes.
4. Every "[check] ... OK" line in _output.txt is mirrored verbatim under a
   "> From {name}{EXT} Section X:" callout in the .md.
5. {name}_reference.txt exists, non-empty, every entry has a URL line AND a
   "Verifies:" line; distinct URLs >= 2 (the >=2-sources mandate).

=== REPORT BACK (your final message) ===
- The file paths created.
- Check result: how many "[check] ... OK" printed, and the {LINT} verdict.
- Web sources used (count; the full provenance list is in {name}_reference.txt).
- Any fact you could NOT verify (do not hide uncertainty).

=== YOUR CONCEPT BRIEF ===
Bundle name: {name} / {NAME}
Section / Member: {SECTION} / {MEMBER}
Phase: {PHASE_N} ({PHASE_THEME})
Lineage (old -> new / why): {LINEAGE}
Anchor concepts/signatures (verify on web, implement, assert):
  {ANCHOR_CONCEPTS}
Suggested runnable sections: {SECTION_LIST}
Suggested mermaid in .md: {MERMAID_IDEAS}
A concrete value the runnable must print (pin it so you can sanity-check):
  {PINNED_VALUE_OR_HOW_TO_DERIVE_IT}
Cross-references to wire up: {SIBLING_LINKS}
```

---

## 4. HTML-family additions (when `{HAS_HTML}` = yes)

Substitute `{HTML_CLAUSE}` → `+ {name}.html (interactive companion, gold-checked)`.

Substitute `{HTML_DELIVERABLE_CLAUSE}` → the `.html` deliverable path, and add
this rule block under HARD RULES:

```text
- {name}.html MUST be a single self-contained file (zero external deps, inline
  <style>+<script>, opens from file://). Dark palette
  (--bg:#0d1117; --panel:#161b22; --ink:#e6edf3) with the {SECTION} accent
  color {ACCENT}. JS that recomputes with the IDENTICAL formula; a [check: OK]
  badge gold-checked against a known runnable value. Header links to the .md and
  the runnable as FULL GitHub URLs ({GITHUB_BASE}/{SECTION}/{STEMUP}.md and
  .../{SECTION}/{stem}{EXT}) — NOT relative links. Back-link to ./index.html
  (the {SECTION} dashboard, NOT ../index.html). Extract the <script> and run
  `node --check` (must pass) before reporting.
- **RUNTIME CHECK (not just syntax):** `node --check` only validates syntax — it
  does NOT execute the code. After `node --check` passes, verify the script runs
  without runtime errors by either (a) opening in a browser and checking the
  console for errors, or (b) running the DOM-mock smoke test from SKILL.md §15.2.
  Common runtime bugs that `node --check` misses: wrong argument count (extra
  unused param shifts all args), accessing properties of undefined (reading
  `.value` from a DOM element that returns empty string, then using it as a
  key/array index), calling a function that was never defined. If any runtime
  error occurs, fix it before reporting.
```

> Relative links in `.html`/`.md` headers are a documented bug class — they must
> be full GitHub URLs. The back-link goes to `./index.html` (the section
> dashboard), never `../index.html` (the repo root).

---

## 5. Skeleton files (the `banner()` + `check()` scaffold per language)

Drop the right one into `{SECTION}/scripts/skeleton{EXT}`. Every bundle starts
from it so output is uniform and verifiable.

### Go — `scripts/skeleton.go`
```go
//go:build ignore

// skeleton.go — copy this to start a bundle. FIRST LINE MUST STAY //go:build ignore.
//
// Run: go run skeleton.go

package main

import (
	"fmt"
	"strings"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

func sectionA() {
	sectionBanner("A: the idea")
	check("example invariant", true)
}

func main() {
	fmt.Println("skeleton.go — every value below is computed by this file.")
	sectionA()
	sectionBanner("DONE — all sections printed")
}
```

### Rust — `scripts/skeleton.rs`
```rust
//! skeleton.rs — copy this to start a bundle. Declared as a [[bin]] in the member
//! Cargo.toml (the orchestrator adds it; do NOT edit Cargo.toml).
//!
//! Run: cargo run --bin skeleton

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar = "=".repeat(BANNER_WIDTH);
    println!("\n{bar}\nSECTION {title}\n{bar}");
}

fn check(desc: &str, ok: bool) {
    if !ok {
        panic!("INVARIANT VIOLATED: {desc}");
    }
    println!("[check] {desc}: OK");
}

fn section_a() {
    banner("A: the idea");
    check("example invariant", true);
}

fn main() {
    println!("skeleton.rs — every value below is computed by this file.");
    section_a();
    banner("DONE — all sections printed");
}
```

### Python — `scripts/skeleton.py`
```python
"""skeleton.py — copy this to start a bundle.

Run: uv run python skeleton.py   (or: python3 skeleton.py)
"""

BANNER_WIDTH = 70
_BAR = "=" * BANNER_WIDTH


def banner(title: str) -> None:
    print(f"\n{_BAR}\nSECTION {title}\n{_BAR}")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"INVARIANT VIOLATED: {desc}")
    print(f"[check] {desc}: OK")


def section_a() -> None:
    banner("A: the idea")
    check("example invariant", True)


def main() -> None:
    print("skeleton.py — every value below is computed by this file.")
    section_a()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
```

### TypeScript — `scripts/skeleton.ts`
```typescript
// skeleton.ts — copy this to start a bundle. Run via tsx (no .js in source).
//
// Run: pnpm exec tsx skeleton.ts

const BANNER_WIDTH = 70;
const BAR = "=".repeat(BANNER_WIDTH);

function sectionBanner(title: string): void {
  console.log(`\n${BAR}\nSECTION ${title}\n${BAR}`);
}

function check(description: string, ok: boolean): void {
  if (!ok) throw new Error(`INVARIANT VIOLATED: ${description}`);
  console.log(`[check] ${description}: OK`);
}

function sectionA(): void {
  sectionBanner("A: the idea");
  check("example invariant", true);
}

function main(): void {
  console.log("skeleton.ts — every value below is computed by this file.");
  sectionA();
  sectionBanner("DONE — all sections printed");
}

main();
```

### C++ — `scripts/skeleton.cpp`
```cpp
// skeleton.cpp — copy this to start a bundle. Compiled to /tmp (never in-source).
//
// Run: c++ -std=c++23 -O2 -Wall -Wextra -Wpedantic skeleton.cpp -o /tmp/x && /tmp/x

#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace {

constexpr int BANNER_WIDTH = 70;

void sectionBanner(const char* title) {
    char bar[BANNER_WIDTH + 1];
    std::memset(bar, '=', BANNER_WIDTH);
    bar[BANNER_WIDTH] = '\0';
    std::printf("\n%s\nSECTION %s\n%s\n", bar, title, bar);
}

void check(const char* description, bool ok) {
    if (!ok) {
        std::fprintf(stderr, "INVARIANT VIOLATED: %s\n", description);
        std::exit(EXIT_FAILURE);
    }
    std::printf("[check] %s: OK\n", description);
}

void sectionA() {
    sectionBanner("A: the idea");
    check("example invariant", true);
}

}  // namespace

int main() {
    std::printf("skeleton.cpp — every value below is computed by this file.\n");
    sectionA();
    sectionBanner("DONE — all sections printed");
}
```

---

## 6. Bootstrap note (Phase 1 / new section only)

The very first bundle has no model to copy. Give it a richer brief: spell out the
`banner()`/`check()` helpers (from the skeleton above), the callout format, the
pitfalls-table columns, and the `{INTERNALS}` axis. Then designate it the
**style anchor** — put its path in every later worker's `{MODEL_BUNDLES}`.

---

## 7. Worked example — a filled brief (Rust, "ownership")

To show how the `{BLANK}` fields become a concrete prompt, here is the brief
block for an imaginary Rust ownership bundle:

```text
=== YOUR CONCEPT BRIEF ===
Bundle name: ownership / OWNERSHIP
Section / Member: rust / core
Phase: Phase 1 (Language Foundations)
Lineage (old -> new / why): n/a (language fundamental) — the root of the
  ownership -> borrowing -> lifetimes -> traits -> smart-pointers -> threads
  -> async expertise chain. Everything in Rust hangs off this.
Anchor concepts/signatures (verify on web, implement, assert):
  - Each value has exactly ONE owner; assigning/transferring MOVES it (non-Copy
    types), leaving the source unusable. Copy types (integers, &T) are bit-copied.
  - `let s2 = s1;` for a String moves -> `s1` is dead afterward (compile error
    on use). For an i32 it copies -> both usable.
  - `Clone` is explicit (`.clone()`); `Copy` is implicit and must be opt-in via
    `#[derive(Copy)]` with all fields Copy.
Suggested runnable sections: A: move vs copy (String vs i32), B: partial moves
  out of a struct, C: Clone vs Copy, D: ownership of function args/returns
Suggested mermaid: an ownership-flow graph (owner -> value -> dropped at scope end)
A concrete value the runnable must print: a 3-field struct, moving one field out,
  then printing the remaining two works but printing the moved one is a
  compile error (assert via check that the remaining two are intact).
Cross-references to wire up: BORROWING (why a reference lets you use a value
  without taking ownership), LIFETIMES (the borrow checker's time axis)
```

Everything above the `=== YOUR CONCEPT BRIEF ===` line is the constant preamble,
identical for every Rust worker. Only this block changes.
