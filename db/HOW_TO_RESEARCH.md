# HOW_TO_RESEARCH — Database Internals "Concept-as-a-Bundle" Workflow

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

## 2. The workflow

1. **Research** the concept (textbooks, papers, docs — CLRS, Database System Concepts, PostgreSQL docs).
2. **Write `.py`** — reference impl with `section_*()` functions, each printing a banner + table.
3. **Run + capture** — `python3 name.py > name_output.txt`
4. **Write `.md`** — paste tables verbatim, add mermaid diagrams, worked examples, pitfalls, cheat sheet.
5. **Write `.html`** — recompute in JS, gold-check badge, links to `.md`/`.py`.
6. **Cross-link** siblings 🔗.

## 3. Verification discipline

1. `.py` runs clean; `[check] ... OK` asserts pass.
2. `.md` numbers trace to `> From name.py Section X:` callouts.
3. `.html` gold-check: recompute in JS, show `[check: OK]` badge.
4. `node --check` the extracted `<script>`.

## 4. HTML style (follow `llm/gqa.html`)

- Dark palette: `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- Sliders/buttons to control parameters
- Canvas or SVG for visualizations
- `[check: OK]` gold badge
- Links to `.md` and `.py` in header
- `← all tutorials` link to `../index.html`

## 5. Source material

- **Papers**: cite arXiv IDs or DOI. B-tree (Bayer & McCreight 1972), LSM-tree (O'Neil 1996), MVCC (Bernstein & Goodman 1983), Raft (Ongaro & Ousterhout 2014), etc.
- **Books**: Database System Concepts (Silberschatz), Designing Data-Intensive Applications (Kleppmann).
- **Docs**: PostgreSQL Internals, MySQL docs, RocksDB wiki.
- Every formula/number must be verified against ≥2 authoritative sources.
