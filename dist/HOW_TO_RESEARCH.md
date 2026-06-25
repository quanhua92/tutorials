# HOW_TO_RESEARCH — Distributed Systems "Concept-as-a-Bundle" Workflow

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

- **Papers**: cite arXiv IDs or DOI. Raft (Ongaro & Ousterhout 2014), Paxos (Lamport 1998/2001), PBFT (Castro & Liskov 1999), CAP (Brewer 2000 / Gilbert & Lynch 2002), CRDTs (Shapiro et al 2011), Spanner (Pang et al 2012), Dynamo (DeCandia et al 2007), Chord (Stoica et al 2001), Gossip protocols (Jelasity et al 2007).
- **Books**: Designing Data-Intensive Applications (Kleppmann), Distributed Systems (Tanenbaum & Van Steen).
- Every formula/number must be verified against ≥2 authoritative sources.

## 3. HTML style (follow `llm/gqa.html`)

- Dark palette: `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- Sliders/buttons to control parameters
- Canvas or SVG for visualizations
- `[check: OK]` gold badge
- Links to `.md` and `.py` in header
- `← all tutorials` link to `../index.html`
