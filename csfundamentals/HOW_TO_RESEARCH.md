# HOW_TO_RESEARCH — CS Fundamentals "Concept-as-a-Bundle" Workflow

> Adapted from `interview/HOW_TO_RESEARCH.md`.

## 0. The one rule

> **Every concept is a bundle of files that cite each other, all deriving from ONE
> ground-truth `.py`. Nothing is ever hand-computed.**

A **concept bundle** = `{name}.py` + `{name}_output.txt` + `{NAME}.md` + `{name}.html`.

## 1. Focus

This folder covers **core CS fundamentals** beyond DSA: probabilistic data structures,
networking protocols, OS scheduling, concurrency, authentication, and infrastructure patterns.

**15 bundles. Python only.**

## 2. Source material

The interview-prep repo at `/Users/quan/workspace/interview-prep/cs_fundamentals/`:

```
cs_fundamentals/
  ├── bloom_filters/           checklist.md, discussion.md
  ├── back_of_envelope/        checklist.md, discussion.md
  ├── geohashing/              checklist.md, discussion.md
  ├── load_balancer/           checklist.md, discussion.md
  ├── concurrency/             checklist.md, discussion.md
  ├── operating_systems/       checklist.md, discussion.md
  ├── computer_networking/     checklist.md, discussion.md
  ├── auth_systems/            checklist.md, discussion.md
  ├── api_gateway/             checklist.md, discussion.md
  ├── api_security/            checklist.md, discussion.md
  ├── idempotency_patterns/    checklist.md, discussion.md
  ├── zero_downtime/           checklist.md, discussion.md
  ├── multi_region/            checklist.md, discussion.md
  ├── realtime_protocols/      checklist.md, discussion.md
  └── system_security/         checklist.md, discussion.md
```

## 3. The four roles of each file

| File | Role | Hard rules |
|---|---|---|
| **`name.py`** | Ground truth. Implements the concept (bloom filter, geohash encoder, LB algorithm, scheduler). | Pure Python stdlib. `if __name__ == "__main__"` with `===` banners. |
| **`name_output.txt`** | Captured stdout. | `python3 name.py > name_output.txt 2>/dev/null` |
| **`NAME}.md`** | Concept guide. How it works, math, tradeoffs, real-world usage. | Numbers from `_output.txt`. Mermaid diagrams. |
| **`name.html`** | Interactive simulation. User manipulates inputs, sees concept in action. | Dark palette. Cyan accent `#00bcd4`. Gold-checked against `.py`. |

## 4. The `.md` structure

```markdown
# [Concept Name]

> **Companion code:** [`name.py`](https://github.com/quanhua92/tutorials/blob/main/csfundamentals/name.py).
> **Live demo:** [`name.html`](./name.html)

---

## 0. TL;DR — the one idea
> **The analogy:** [plain-English mental model]

[mermaid diagram of the concept]

## 1. How It Works
[step-by-step explanation with code snippets]

## 2. The Math
> From name.py Section X:
[formulas + computed values]

## 3. Tradeoffs
| Option | Pros | Cons |
|---|---|---|

## 4. Real-World Usage
[systems that use this concept]

### Killer Gotchas
```

## 5. The `.html` style

- **Dark palette:** `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- **Accent:** cyan `#00bcd4`
- **Interactive simulation:** sliders, buttons to step through
- **`[check: OK]` gold badge** — recompute known value in JS, compare to `.py`
- **`← all tutorials`** link to `./index.html` (csfundamentals dashboard, NOT `../index.html`)
- **`.md` and `.py` links** must use full GitHub URLs: `https://github.com/quanhua92/tutorials/blob/main/csfundamentals/<STEMUP>.md`
- **Zero external dependencies**

## 6. Bundle catalog

| # | Stem | Concept | Key Visualization |
|---|---|---|---|
| 01 | `bloom_filters` | Bloom Filters | Bit array with k hashes + FPR slider |
| 02 | `back_of_envelope` | Back-of-Envelope | Throughput/storage calculator |
| 03 | `geohashing` | Geohashing | Grid subdivision on a map |
| 04 | `load_balancer` | Load Balancer | LB algorithms (round-robin, least-conn, weighted) |
| 05 | `concurrency` | Concurrency | Race condition visualizer (threads interleaving) |
| 06 | `operating_systems` | Operating Systems | Process scheduling (FCFS, SJF, RR) |
| 07 | `computer_networking` | Computer Networking | TCP handshake + packet flow |
| 08 | `auth_systems` | Auth Systems | OAuth/JWT flow diagram |
| 09 | `api_gateway` | API Gateway | Request routing + rate limiting + auth chain |
| 10 | `api_security` | API Security | OWASP threats + mitigations |
| 11 | `idempotency_patterns` | Idempotency | Duplicate detection + idempotency keys |
| 12 | `zero_downtime` | Zero Downtime | Blue-green / canary deployment toggles |
| 13 | `multi_region` | Multi-Region | Active-active vs active-passive replication |
| 14 | `realtime_protocols` | Realtime Protocols | WebSocket vs SSE vs polling comparison |
| 15 | `system_security` | System Security | Defense-in-depth layers |

## 7. Verification discipline

```bash
python3 name.py > /dev/null 2>&1 && echo "PY OK"
python3 -c "import re;open('/tmp/_j.js','w').write(re.search(r'<script>(.*)</script>',open('name.html').read(),re.S).group(1))"
node --check /tmp/_j.js && echo "JS OK"
```

## 8. Common bugs to AVOID

- **`const` reassignment:** NEVER `const x = []; x = x.concat(...)`. Use `let` or `.push()`.
- **Array `.join(", ")` spaces:** gold-check needs `.join(",")` without spaces.
- **Relative links:** `.md` and `.py` links MUST be full GitHub URLs.
- **Back-link:** `.html` must link to `./index.html` (csfundamentals dashboard).
