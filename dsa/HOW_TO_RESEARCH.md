# HOW_TO_RESEARCH — DSA Visualized "Concept-as-a-Bundle" Workflow

> Adapted from `llm/HOW_TO_RESEARCH.md`. Same discipline, different domain.

## 0. The one rule

> **Every concept is a bundle of files that cite each other, all deriving from ONE ground-truth `.py`. Nothing is ever hand-computed.**

A **concept bundle** = `{name}.py` + `{name}_output.txt` + `{NAME}.md` + `{name}.html`.

## 1. The four roles of each file

| File | Role | Hard rules |
|---|---|---|
| **`name.py`** | Ground truth. Clean, runnable reference implementation + `print` of every number the docs need. | Single source of truth. Pure Python (no external deps). Sections printed with banners. |
| **`name_output.txt`** | Captured stdout. Committed so the `.md` can be audited without running. | `python3 name.py > name_output.txt 2>/dev/null` |
| **`NAME}.md`** | Static, rigorous guide. Mermaid diagrams + tables pasted *verbatim* from the `.py` output. | Every number under a `> From name.py Section X:` callout. Cross-refs 🔗. |
| **`name.html`** | Playable companion. Recomputes in JS with the *identical* formula, gold-checked against `.py`. | Single file, zero deps, opens from `file://`. Dark palette. |

## 2. Source material

- **CLRS** (Cormen, Leeson, Rivest, Stein — Introduction to Algorithms, 3rd ed.) is the primary reference.
- **Sedgewick & Wayne** (Algorithms, 4th ed.) for visual intuition.
- Every algorithm/number must be verified against CLRS or another authoritative source.

## 3. HTML style (follow `llm/gqa.html`)

- Dark palette: `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- Canvas/SVG animations for data structure operations
- Step-through controls (play, step, reset)
- `[check: OK]` gold badge
- Links to `.md` and `.py` in header
- `← all tutorials` link to `../index.html`
