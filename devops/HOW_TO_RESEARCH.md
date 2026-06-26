# HOW_TO_RESEARCH — DevOps / Cloud Native "Concept-as-a-Bundle" Workflow

> Adapted from `llm/HOW_TO_RESEARCH.md`. Same discipline, different domain.

## 0. The one rule

> **Every concept is a bundle of files that cite each other, all deriving from ONE ground-truth `.py`. Nothing is ever hand-computed.**

A **concept bundle** = `{name}.py` + `{name}_output.txt` + `{NAME}.md` + `{name}.html`.

## 1. Key difference from algorithm topics

DevOps concepts are more **system architecture** than algorithmic. The `.py` serves as a **simulation or model** (e.g., simulating container namespace isolation, modeling K8s scheduler bin-packing). The `.html` is an **interactive architecture diagram** rather than an algorithm animation.

## 2. Source material

- **Docs**: Docker docs, Kubernetes docs (kubernetes.io), CNCF landscape, Terraform docs.
- **Books**: Kubernetes Patterns (Bilgin Ibryam & Roland Huss), Designing Distributed Systems (Brendan Burns).
- **Specs/Papers**: OCI spec, CNI spec, Borg (Verma et al 2015), Kubernetes (Burns et al 2016).

## 3. HTML style (follow `llm/gqa.html`)

- Dark palette: `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- Interactive architecture diagrams (boxes, arrows, flow)
- Step-through controls where applicable
- `[check: OK]` gold badge
- `← all tutorials` link to `../index.html`
