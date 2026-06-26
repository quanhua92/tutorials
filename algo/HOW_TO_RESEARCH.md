# HOW_TO_RESEARCH — Algorithms in Action "Concept-as-a-Bundle" Workflow

> Adapted from `llm/HOW_TO_RESEARCH.md`. Same discipline, different domain.

## 0. The one rule

> **Every concept is a bundle of files that cite each other, all deriving from ONE ground-truth `.py`. Nothing is ever hand-computed.**

A **concept bundle** = `{name}.py` + `{name}_output.txt` + `{NAME}.md` + `{name}.html`.

## 1. Focus

This folder covers algorithm FAMILIES in action: sorting, caching/eviction, compression, cryptography, and probabilistic/sketching algorithms. Each bundle implements the algorithm from scratch, shows step-by-step execution, and visualizes the process.

## 2. Source material

- CLRS (Introduction to Algorithms), Sedgewick (Algorithms), Knuth (TAOCP Vol 3).
- Papers: Huffman (1952), Lempel-Ziv (1977), Rivest-Shamir-Adleman (1978), Diffie-Hellman (1976), Bloom (1970), Flajolet (HyperLogLog 2007).
- Every formula/number verified against the original paper or CLRS.

## 3. HTML style (follow `llm/gqa.html`)

- Dark palette: `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- Step-through animations (play/pause/step/reset)
- `[check: OK]` gold badge
- `← all tutorials` link to `../index.html`
