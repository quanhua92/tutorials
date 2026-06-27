# HOW_TO_RESEARCH — Observability "Concept-as-a-Bundle" Workflow

> Adapted from `interview/HOW_TO_RESEARCH.md` and `concept-builder/SKILL.md`.

## 0. The one rule

> **Every concept is a bundle of files that cite each other, all deriving from ONE
> ground-truth `.py`. Nothing is ever hand-computed.**

A **concept bundle** = `{name}.py` + `{name}_output.txt` + `{NAME}.md` + `{name}.html`.

## 1. Focus

This folder covers **observability**: the three pillars (metrics, logs, traces),
OpenTelemetry, the traditional stack (Prometheus, Loki, Grafana), and
OpenObserve (S3-native, Rust-based, serverless-like).

**10 bundles. Python only.**

Each bundle follows the Day 0 → Day 1 → Day 2 ops format:
- **Day 0**: Deploy/install, configure, verify it's running
- **Day 1**: First data, basic queries, dashboards, indexes
- **Day 2**: Scale, optimize, backup, troubleshoot, upgrade

## 2. Source material

- OpenObserve docs: https://open.feishu.cn/docx/OpenObserve (and openobserve.ai/docs)
- OpenTelemetry docs: https://opentelemetry.io/docs/
- Prometheus docs: https://prometheus.io/docs/
- Loki docs: https://grafana.com/docs/loki/
- Grafana docs: https://grafana.com/docs/grafana/
- Web search for benchmarks, comparisons, and real-world architecture details.

## 3. The four roles of each file

| File | Role | Hard rules |
|---|---|---|
| **`name.py`** | Ground truth. Simulates the system/architecture/algorithm with real math. | Pure Python stdlib. `===` banners. `[check] OK`. Seeded RNG. |
| **`name_output.txt`** | Captured stdout. | `python3 name.py > name_output.txt 2>/dev/null` |
| **`NAME}.md`** | Day 0/1/2 ops guide. Mermaid diagrams, config snippets, decision tables. | Numbers from `_output.txt` verbatim under callouts. Pitfalls table. Sources. |
| **`name.html`** | Interactive companion. Dark palette, sky blue accent. | Zero deps. Gold-check badge. `./index.html` back-link. Full GitHub URLs. |

## 4. The `.md` structure (Day 0/1/2 format)

```markdown
# [Tool/Concept] — Day 0 to Production

> Companion: [name.py](https://github.com/quanhua92/tutorials/blob/main/observability/name.py)
> Live: [name.html](./name.html)

## 0. TL;DR
## 1. Architecture
[mermaid diagram]
## 2. Day 0 — Deploy & Configure
[install commands, config files, verify]
## 3. Day 1 — First Data & Queries
[ingest, query, dashboard, index]
## 4. Day 2 — Scale & Ops
[scale, optimize, backup, troubleshoot, upgrade]
## 5. Cost Analysis (where applicable)
## 6. Comparison (where applicable)
### Killer Gotchas
[pitfalls table]
### Cheat Sheet
## Sources
```

## 5. The `.html` style

- **Dark palette:** `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- **Accent:** sky blue `#0ea5e9`
- **Interactive:** architecture diagrams, cost calculators, query explorers, comparison matrices
- **`[check: OK]` gold badge** — recompute known value in JS, compare to `.py`
- **`← all tutorials`** link to `./index.html` (observability dashboard)
- **`.md` and `.py` links** must use full GitHub URLs: `https://github.com/quanhua92/tutorials/blob/main/observability/<STEMUP>.md`
- **Zero external dependencies**

## 6. Bundle catalog

### Group 1: Foundations (3)

| # | Stem | Topic |
|---|---|---|
| 01 | `observability_fundamentals` | 3 pillars, SLI/SLO/SLA, USE/RED, error budgets, cardinality |
| 02 | `opentelemetry` | OTel API/SDK/Collector, OTLP, instrumentation, context propagation, sampling |
| 03 | `distributed_tracing` | Span/trace model, W3C propagation, head vs tail sampling, trace-to-log |

### Group 2: Traditional Stack (3)

| # | Stem | Topic |
|---|---|---|
| 04 | `prometheus` | TSDB, PromQL, service discovery, federation, recording rules, Alertmanager |
| 05 | `loki` | Log aggregation, LogQL, S3 storage, label indexing |
| 06 | `grafana` | Dashboards, multi-source, alerting, provisioning |

### Group 3: OpenObserve (4)

| # | Stem | Topic |
|---|---|---|
| 07 | `openobserve` | Architecture (Rust/S3), Day 0/1/2, ingest/search/streaming |
| 08 | `openobserve_vs_alternatives` | Cost + perf vs ELK/Quickwit/ClickHouse/Loki/Splunk |
| 09 | `openobserve_ingest` | Pipelines, routing, transforms (VRL), Fluent Bit/Vector → O2 |
| 10 | `openobserve_dashboards` | Dashboards, alerts, reports, RUM, traces UI |

## 7. Verification discipline

```bash
python3 name.py > /dev/null 2>&1 && echo "PY OK"
python3 -c "import re;open('/tmp/_j.js','w').write(re.search(r'<script>(.*)</script>',open('name.html').read(),re.S).group(1))"
node --check /tmp/_j.js && echo "JS OK"
```

## 8. Common bugs to AVOID

- **`const` reassignment:** Use `let` or `var` if reassignment needed.
- **Array `.join(", ")` spaces:** gold-check needs `.join(",")` without spaces.
- **Float comparison:** `.toFixed(1)` on BOTH sides.
- **Relative links:** `.md` and `.py` links MUST be full GitHub URLs.
- **Back-link:** `.html` must link to `./index.html` (observability dashboard).
