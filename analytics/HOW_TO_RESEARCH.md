# HOW_TO_RESEARCH — Data Analytics "Concept-as-a-Bundle" Workflow

> Adapted from `interview/HOW_TO_RESEARCH.md`.

## 0. The one rule

> **Every concept is a bundle of files that cite each other, all deriving from ONE
> ground-truth `.py`. Nothing is ever hand-computed.**

A **concept bundle** = `{name}.py` + `{name}_output.txt` + `{NAME}.md` + `{name}.html`.

## 1. Focus

This folder covers **data analytics interview topics**: SQL patterns, funnel analysis,
cohort retention, A/B testing, and product metrics. Each bundle teaches ONE analytics
concept with interactive queries and data visualizations.

**9 bundles. Python only.**

## 2. Source material

The interview-prep repo at `/Users/quan/workspace/interview-prep/data_analytics/`:

```
data_analytics/
  ├── sql_foundations/          checklist.md, discussion.md
  ├── sql_window_functions/     checklist.md, discussion.md
  ├── funnel_analysis/          checklist.md, discussion.md
  ├── cohort_retention/         checklist.md, discussion.md
  ├── experiment_design/        checklist.md, discussion.md
  ├── north_star_metrics/       checklist.md, discussion.md
  ├── product_sense/            checklist.md, discussion.md
  ├── data_quality/             checklist.md, discussion.md
  └── scenario_problems/        checklist.md, discussion.md
```

## 3. The four roles of each file

| File | Role | Hard rules |
|---|---|---|
| **`name.py`** | Ground truth. Creates in-memory sqlite3 DB, seeds sample data, runs queries, prints result tables. | Pure Python stdlib (sqlite3). `if __name__ == "__main__"` with `===` banners. |
| **`name_output.txt`** | Captured stdout. | `python3 name.py > name_output.txt 2>/dev/null` |
| **`NAME}.md`** | Analytics guide. SQL patterns, metric definitions, interpretation tips. | Every number/table from `_output.txt`. Mermaid for data flow. |
| **`name.html`** | Interactive. SQL query explorer, data visualizations (funnel charts, retention heatmaps, sortable tables). | Dark palette. Pink accent `#e91e63`. Gold-checked against `.py`. |

## 4. The `.py` pattern (use sqlite3)

```python
import sqlite3

def build_db():
    """Create in-memory DB with sample data."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, signup_date TEXT, ...);
        CREATE TABLE events (user_id INTEGER, event_type TEXT, ts TEXT, ...);
        INSERT INTO users VALUES ...;
    """)
    return conn

def section_window_functions():
    print("=== Section 1: SQL Window Functions ===\n")
    conn = build_db()
    rows = conn.execute("""
        SELECT user_id, event_date,
               ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY event_date) AS rn,
               LAG(revenue) OVER (PARTITION BY user_id ORDER BY event_date) AS prev_rev
        FROM events
    """).fetchall()
    for r in rows:
        print(f"  user={r[0]} date={r[1]} rn={r[2]} prev_rev={r[3]}")
    conn.close()

if __name__ == "__main__":
    section_window_functions()
    print("\n[check] sample query OK")
```

## 5. The `.html` style

- **Dark palette:** `--bg:#0d1117; --panel:#161b22; --ink:#e6edf3`
- **Accent:** pink `#e91e63`
- **Interactive SQL explorer:** dropdown to select queries, show results table
- **Data visualizations:** funnel bars, retention heatmap grid, sortable columns
- **`[check: OK]` gold badge** — recompute a known metric in JS, compare to `.py`
- **`← all tutorials`** link to `./index.html` (analytics dashboard, NOT `../index.html`)
- **`.md` and `.py` links** must use full GitHub URLs: `https://github.com/quanhua92/tutorials/blob/main/analytics/<STEMUP>.md`
- **Zero external dependencies** — vanilla JS, inline CSS/SVG

## 6. Bundle catalog

| # | Stem | Topic | Key Visualization |
|---|---|---|---|
| 01 | `sql_foundations` | SQL Foundations | JOIN visualizer (INNER/LEFT/RIGHT/CROSS) with Venn-style highlighting |
| 02 | `sql_window_functions` | SQL Window Functions | Table with sliding window highlight (ROW_NUMBER, LAG, SUM OVER) |
| 03 | `funnel_analysis` | Funnel Analysis | Funnel chart with drop-off percentages and conversion rates |
| 04 | `cohort_retention` | Cohort Retention | Retention heatmap grid (cohort × time period) |
| 05 | `experiment_design` | A/B Experiment Design | Sample size calculator + significance checker |
| 06 | `north_star_metrics` | North Star Metrics | Metric tree visualization with upstream/downstream |
| 07 | `product_sense` | Product Sense | Framework cards + scenario walkthrough |
| 08 | `data_quality` | Data Quality | Validation rules + anomaly detection table |
| 09 | `scenario_problems` | Scenario Problems | Interactive case study with branching decisions |

## 7. Verification discipline

1. **`.py` runs clean:** `python3 name.py` exits 0
2. **`_output.txt` matches:** `python3 name.py 2>/dev/null | diff - name_output.txt`
3. **JS syntax:** extract `<script>`, run `node --check`
4. **Gold-check:** `.html` has `[check: OK]` badge

## 8. Common bugs to AVOID

- **`const` reassignment:** NEVER do `const x = []; x = x.concat(...)`. Use `let` or `x.push()`.
- **Array `.join(", ")` spaces:** gold-check comparisons need `.join(",")` without spaces.
- **Relative links:** `.md` and `.py` links MUST be full GitHub URLs.
- **Back-link:** `.html` must link to `./index.html` (analytics dashboard).
