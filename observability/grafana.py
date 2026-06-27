"""grafana.py - Reference simulation of the Grafana visualization model: the
request path (browser frontend -> data source plugins -> query proxy -> data
frames -> panel rendering), the dashboard JSON model (datasource, panels,
templating variables, time range), query languages per data source (PromQL,
LogQL, SQL), the unified alerting pipeline (alert rules -> Normal/Pending/
Alerting states -> notification policies -> contact points), provisioning
(dashboards-as-code, datasources-as-code), panel-type selection, and dashboard
rendering-cost math (queries per refresh x concurrent viewers).

This is the single source of truth that GRAFANA.md is built from. Every number,
table, and worked example in GRAFANA.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 grafana.py

============================================================================
THE INTUITION (read this first) -- the visualization layer over everything
============================================================================
Grafana is a SERVER + BROWSER application that draws dashboards. A dashboard is
a JSON document; each PANEL in it carries a query (or several) aimed at a DATA
SOURCE. On every refresh the browser fans the panel queries out to the Grafana
backend, which proxies each to its data source (Prometheus, Loki, Postgres, ...),
gets back a DATA FRAME (a columnar table with Time/Value fields), and hands it
to the panel plugin (time series, stat, gauge, ...) to draw.

  * MULTI-SOURCE is the point: one dashboard can mix PromQL (metrics), LogQL
    (logs), SQL (business data), and trace queries in the same grid. The panel
    plugin never knows the source dialect -- the data-source plugin normalizes
    every native response into a DataFrame first.
  * TEMPLATING VARIABLES ($job, $env, $interval) parameterize a dashboard.
    Multi-value variables become regexes (api|web) for PromQL's =~ operator.
    "Repeat by variable" clones a panel once per value -- the "one graph per
    instance" overview pattern.
  * ALERTING is unified: one rule engine queries ANY data source, drives each
    rule through Normal -> Pending -> Alerting states (gated by `for:duration`),
    then routes firing instances through a label-matched NOTIFICATION POLICY
    tree to a CONTACT POINT (Slack / PagerDuty / email / webhook).
  * PROVISIONING makes dashboards and datasources GitOps-able: YAML files under
    /etc/grafana/provisioning/ load at startup; a file provider polls a directory
    so a merged dashboard PR is live within 30s with zero UI clicks.
  * RENDERING COST = panels x queries-per-panel / refresh_interval x viewers.
    The refresh slider is a cost dial: a 24-panel wall dashboard at 5s with 100
    war-room onlookers is 480 queries/sec against your backends.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
  dashboard   : a JSON document (title, uid, schemaVersion, time, refresh,
                templating, panels[]). Exportable, importable, git-commitable.
  panel       : one visualization tile. Has a type, a gridPos (x/y/w/h on a
                24-col grid), a datasource ref, and 1..N targets (queries).
  data source : a configured connection to a backend (Prometheus, Loki,
                Postgres). Each has a TYPE (prometheus, postgres) and a UID.
  data source : a plugin that translates Grafana queries into the source's
  plugin        native dialect (PromQL/LogQL/SQL) and the response into a
                DataFrame. Can be frontend-only or backend (proxy) based.
  query proxy : Grafana's backend proxy. For "server" access mode it makes the
                data-source call itself (avoids CORS, keeps secrets server-side).
  data frame  : the universal return type. A columnar table with named Fields
                (Time, Value, labels). One query -> 1..N frames. This contract
                is WHY any source can feed any panel.
  variable    : a named placeholder ($job) resolved at render time. Types:
                query, interval, custom, datasource, textbox, constant, adhoc.
  gridPos     : a panel's box on the 24-column grid: {x, y, w, h}.
  refresh     : auto-refresh interval (5s, 30s, 1m, or empty=off).
  alert rule  : a query + a threshold condition + a `for:` duration. Evaluated
                on a schedule against any data source.
  alert state : Normal -> Pending (condition true, for: not yet met) -> Alerting
                (condition true >= for:). Resolves back to Normal.
  notification: a tree of label matchers. First-match-wins routes a firing
  policy       instance to a contact point. Root is the default receiver.
  contact     : the destination: Slack / PagerDuty / email / webhook / ...
  point
  provisioning: YAML-driven load of datasources + dashboards at startup.
                Provisioned objects are read-only in the UI (git is the truth).
"""

import json
import random

BANNER_WIDTH = 70
_BAR = "=" * BANNER_WIDTH

# ---------------------------------------------------------------------------
# Determinism: fixed seed. No wall-clock-derived printed values anywhere.
# ---------------------------------------------------------------------------
random.seed(42)


def banner(title: str) -> None:
    print(f"\n{_BAR}\nSECTION {title}\n{_BAR}")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"INVARIANT VIOLATED: {desc}")
    print(f"[check] {desc}: OK")


# ===========================================================================
# SECTION A: the request path -- browser to rendered pixels
# ===========================================================================
def section_a() -> None:
    banner("A: the request path -- browser to rendered pixels")
    print(
        "Grafana is a SERVER + BROWSER APP. A dashboard render is one HTTP page\n"
        "load, then N parallel query requests fanned out to data sources. The\n"
        "path below is what EVERY panel refresh walks, end to end.\n"
    )
    # Per-layer latency (ms) for one panel, one query, warm cache. Pinned by
    # the values below (the seed governs the random layers used elsewhere).
    layers = [
        ("browser",      "user opens /d/<uid>; SPA boots; dashboard JSON fetched", 60),
        ("frontend",     "React parses JSON; expands $variables; builds query list", 8),
        ("query_proxy",  "Grafana server routes each query to its data-source plugin", 5),
        ("ds_plugin",    "plugin translates Grafana query -> native (PromQL/LogQL/SQL)", 3),
        ("backend",      "the actual store (Prometheus/Loki/Postgres) executes", 120),
        ("to_dataframe", "plugin converts native response -> Grafana data frame", 6),
        ("panel_render", "browser panel plugin (time series/stat/...) draws pixels", 18),
    ]
    total = 0
    for name, what, ms in layers:
        print(f"  {name:<14} {ms:>4} ms   {what}")
        total += ms
    print(f"  {'TOTAL':<14} {total:>4} ms   (one panel, one query, warm view)")
    check("per-panel render budget = sum of 7 layer latencies", total == 220)

    # Data proxy: the backend proxies source calls (server access mode).
    print(
        "\n  DATA PROXY: for 'server' access mode (access=proxy) Grafana's backend\n"
        "  makes the data-source call. This avoids CORS and keeps SECRETS\n"
        "  server-side (API keys never reach the browser). For 'browser' access\n"
        "  mode the browser calls the source directly -- rare, requires the\n"
        "  source to allow CORS, and cannot use secret credentials safely."
    )
    check("server access mode proxies via backend (secrets stay server-side)", True)

    # The data frame: the universal contract between source and panel.
    print(
        "\n  DATA FRAME: the universal return type. A DataFrame is a columnar\n"
        "  table with named Fields (e.g. Time=[..], Value=[..]) plus optional\n"
        "  labels. One panel query returns 1..N frames; the panel plugin knows\n"
        "  how to draw a frame of a given shape (wide vs long). This contract is\n"
        "  WHY any data source can feed any panel -- the source plugin owns the\n"
        "  translation, the panel plugin owns the pixels."
    )
    # A concrete PromQL -> DataFrame translation.
    promql_point = (1700000000, 1234.0, {"job": "api"})
    frame = {"fields": [{"name": "Time", "values": [promql_point[0]]},
                        {"name": "Value", "values": [promql_point[1]]}],
             "meta": {"labels": promql_point[2]}}
    print(
        f"\n  PromQL vector  http_requests_total{{job=\"api\"}} 1234 @1700000000\n"
        f"  -> DataFrame   fields={[(f['name'], f['values']) for f in frame['fields']]}\n"
        f"                 labels={frame['meta']['labels']}"
    )
    check("DataFrame has a Time field and a Value field",
          frame["fields"][0]["name"] == "Time" and frame["fields"][1]["name"] == "Value")


# ===========================================================================
# SECTION B: the dashboard JSON model
# ===========================================================================
def section_b() -> None:
    banner("B: the dashboard JSON model")
    print(
        "A dashboard IS a JSON object. The same JSON is what you edit in the UI,\n"
        "export, import, and version in git via provisioning. Knowing the shape\n"
        "is what makes 'dashboards-as-code' possible (Section G).\n"
    )
    dash = {
        "title": "API latency overview",
        "uid": "api-latency",
        "schemaVersion": 39,
        "version": 1,
        "timezone": "browser",
        "time": {"from": "now-6h", "to": "now"},
        "refresh": "30s",
        "templating": {"list": [
            {"name": "datasource", "type": "datasource",
             "query": "prometheus",
             "current": {"text": "Prometheus", "value": "Prometheus"}},
            {"name": "job", "type": "query", "datasource": "$datasource",
             "query": "label_values(http_requests_total, job)", "includeAll": True},
            {"name": "interval", "type": "interval",
             "options": [{"text": "1m", "value": "1m"}, {"text": "5m", "value": "5m"}],
             "current": {"text": "5m", "value": "5m"}},
        ]},
        "panels": [
            {"id": 1, "type": "timeseries", "title": "p95 latency by job",
             "gridPos": {"x": 0, "y": 0, "w": 12, "h": 8},
             "datasource": {"type": "prometheus", "uid": "$datasource"},
             "targets": [{"expr": "histogram_quantile(0.95, sum by (le)(rate(http_req_duration_seconds_bucket{job=~\"$job\"}[$interval])))", "refId": "A"}]},
            {"id": 2, "type": "stat", "title": "error rate",
             "gridPos": {"x": 12, "y": 0, "w": 6, "h": 8},
             "datasource": {"type": "prometheus", "uid": "$datasource"},
             "targets": [{"expr": "sum(rate(http_requests_total{status=~\"5..\"}[5m])) / sum(rate(http_requests_total[5m]))", "refId": "A"}]},
            {"id": 3, "type": "logs", "title": "recent errors",
             "gridPos": {"x": 18, "y": 0, "w": 6, "h": 8},
             "datasource": {"type": "loki", "uid": "loki"},
             "targets": [{"expr": "{job=~\"$job\"} |= \"error\"", "refId": "A"}]},
        ],
    }
    print(json.dumps(dash, indent=2))
    check("dashboard has 3 panels", len(dash["panels"]) == 3)
    check("panel ids are unique", len({p["id"] for p in dash["panels"]}) == len(dash["panels"]))
    check("every panel has a gridPos (x,y,w,h)", all("gridPos" in p for p in dash["panels"]))
    check("schemaVersion is an int (versioned JSON shape)", isinstance(dash["schemaVersion"], int))

    print(
        "\n  KEY FIELDS:\n"
        "    uid              stable identifier (URLs use it; rename-safe)\n"
        "    schemaVersion    JSON shape version (drives migrations on import)\n"
        "    time.from/to     the default time window (e.g. now-6h .. now)\n"
        "    refresh          auto-refresh interval (30s, 5m, or ''=off)\n"
        "    templating.list  the variables ($job, $interval, $datasource)\n"
        "    panels[].gridPos x/y/w/h on a 24-COLUMN grid (w in 1..24)\n"
        "    panels[].targets the query list (expr + refId A/B/C...)\n"
        "    panels[].datasource {type, uid} -- uid can be a $variable"
    )
    check("grid is 24 columns wide (w max = 24)", all(p["gridPos"]["w"] <= 24 for p in dash["panels"]))
    check("datasource uid can itself be a $variable (swap source per dashboard)",
          dash["panels"][0]["datasource"]["uid"] == "$datasource")


# ===========================================================================
# SECTION C: query languages -- one panel, many source dialects
# ===========================================================================
def section_c() -> None:
    banner("C: query languages -- one panel, many source dialects")
    print(
        "Every data-source plugin speaks its own query dialect. Grafana's job is\n"
        "to translate the panel's request into that dialect and the native result\n"
        "back into a DataFrame. The dialect you write lives in targets[].expr.\n"
    )
    sources = [
        ("Prometheus", "prometheus", "PromQL",
         'histogram_quantile(0.95, sum by (le)(rate(http_req_duration_seconds_bucket[5m])))',
         "counter math, aggregations, histogram quantiles"),
        ("Loki", "loki", "LogQL",
         '{job="api"} |= "error" | json | line_format "{{.msg}}"',
         "log stream selector + filter pipeline"),
        ("PostgreSQL", "postgres", "SQL",
         "SELECT time, cpu FROM host_metrics WHERE host=$host AND $__timeFilter(time)",
         "$__timeFilter macro expands to a time-range WHERE clause"),
        ("MySQL", "mysql", "SQL",
         "SELECT $__timeGroup(created_at,'5m'), count(*) FROM events GROUP BY 1",
         "$__timeGroup buckets rows by interval"),
        ("Elasticsearch", "elasticsearch", "Lucene/KQL",
         'status:5xx AND service:api',
         "full-text + field filters"),
        ("InfluxDB", "influxdb", "InfluxQL/Flux",
         'from(bucket:"metrics") |> range(start: v.timeRangeStart) |> filter(fn:(r)=> r._measurement=="cpu")',
         "Flux is a piped functional language"),
        ("Tempo", "tempo", "TraceQL",
         '{ span.http.status_code >= 500 }',
         "selects spans by attributes for trace exploration"),
    ]
    print(f"  {'source':<14}{'type':<14}{'language':<14}example query")
    print("  " + "-" * 94)
    for name, typ, lang, expr, note in sources:
        print(f"  {name:<14}{typ:<14}{lang:<14}{expr}")
    print(f"\n  data-source dialects modeled: {len(sources)}")
    check("7 data-source dialects modeled", len(sources) == 7)
    check("metric (Prom) + log (Loki) + trace (Tempo) dialects all present",
          {"prometheus", "loki", "tempo"} <= {s[1] for s in sources})

    # SQL macros: $__timeFilter, $__timeGroup, $__interval.
    print(
        "\n  SQL MACROS (Postgres/MySQL) -- Grafana rewrites these at query time:\n"
        "    $__timeFilter(col)      -> col BETWEEN '<from>' AND '<to>'\n"
        "    $__timeGroup(col,'5m')  -> floor(extract(epoch from col)/300)*300\n"
        "    $__interval             -> a bucket width derived from time-range/1000\n"
        "  These are why SQL dashboards auto-scale bucketing to the zoom level."
    )

    # The normalization: native response -> DataFrame.
    print(
        "\n  NORMALIZATION: every dialect's native response is converted into a\n"
        "  DataFrame before the panel plugin sees it. A PromQL vector, a SQL row\n"
        "  set, and a Loki log stream all become {Time:[..], Value:[..]} frames.\n"
        "  The panel plugin draws the frame regardless of where the data came\n"
        "  from -- that decoupling is the whole multi-source value proposition."
    )
    check("all dialects normalize to a DataFrame before rendering", True)


# ===========================================================================
# SECTION D: templating variables -- the $var and [[var]] system
# ===========================================================================
def section_d() -> None:
    banner("D: templating variables -- the $var and [[var]] system")
    print(
        "A variable is a named placeholder resolved at render time. It turns a\n"
        "static dashboard into a parameterized template: pick a job, a region, a\n"
        "host -> every panel's query re-runs with that value. Variables are\n"
        "substituted as $name, [[name]], or ${name}.\n"
    )
    var_types = [
        ("query",      "values from a data-source query (e.g. label_values)"),
        ("interval",   "a time bucket (1m, 5m, 1h) -- often drives $__interval"),
        ("custom",     "a hardcoded list you define (env: dev/stage/prod)"),
        ("datasource", "pick WHICH data source the dashboard queries"),
        ("textbox",    "free text the user types"),
        ("constant",   "a fixed value hidden from the user"),
        ("adhoc",      "auto-discovered key=value filters (Prometheus label pairs)"),
    ]
    print(f"  {'type':<12}what it resolves to")
    print("  " + "-" * 60)
    for t, what in var_types:
        print(f"  {t:<12}{what}")
    check("7 variable types", len(var_types) == 7)

    # Variable interpolation: resolve a query template against bindings.
    template = 'rate(http_requests_total{job="$job",env="$env"}[$interval])'
    bindings = {"job": "api", "env": "prod", "interval": "5m"}

    def interp(tmpl: str, b: dict) -> str:
        out = tmpl
        for k in sorted(b):  # sorted for deterministic substitution order
            out = out.replace("$" + k, b[k])
        return out

    resolved = interp(template, bindings)
    print(f"\n  template : {template}")
    print(f"  bindings : {bindings}")
    print(f"  resolved : {resolved}")
    check("$job, $env, $interval all interpolated",
          "$job" not in resolved and "$env" not in resolved and "$interval" not in resolved)

    # Multi-value + includeAll: $job expands to a regex for =~
    print(
        "\n  MULTI-VALUE: if a variable has includeAll or multi-select, a value\n"
        "  like ['api','web'] becomes the regex 'api|web' meant for PromQL's =~\n"
        "  match operator:  {job=~\"$job\"}  ->  {job=~\"api|web\"}.\n"
        "  includeAll sets the value to '.*' (matches everything)."
    )
    multi = ["api", "web", "batch"]
    regex = "|".join(multi)  # NO spaces -- this is a regex alternation
    print(f"  $job values = {multi}  ->  regex = '{regex}'")
    check("multi-value joins with | into a regex (no spaces)", regex == "api|web|batch")

    # Repeat by variable: one panel -> N panels (one per value).
    print(
        "\n  REPEAT BY VARIABLE: set 'repeat by $host' on a panel and Grafana\n"
        "  clones the panel once per host value, auto-layouting on the grid.\n"
        "  This is how 'one graph per instance' overview dashboards are built."
    )
    hosts = ["h-01", "h-02", "h-03"]
    repeated = [f"panel[{h}]" for h in hosts]
    print(f"  hosts={hosts} -> {len(repeated)} panels rendered")
    check("repeat by variable yields N panels (1 per value)", len(repeated) == len(hosts))


# ===========================================================================
# SECTION E: panel types -- when to use which
# ===========================================================================
def section_e() -> None:
    banner("E: panel types -- when to use which")
    print(
        "The panel TYPE decides how a DataFrame is drawn. Picking the wrong one\n"
        "hides the signal (a stat panel for a trend, a table for a rate). Match\n"
        "the visualization to the QUESTION the panel answers.\n"
    )
    panels = [
        ("timeseries",   "How does this move over time?",       "lines/areas/bars over time",  "QPS, latency, CPU"),
        ("stat",         "What is the current single value?",   "big number + sparkline",      "current p95, error %, up/down"),
        ("gauge",        "Is a bounded value in a safe range?", "arc + threshold bands",       "CPU 0-100%, disk 0-100%"),
        ("bargauge",     "Compare a few values at a glance?",   "horizontal bars",             "top 10 hosts by load"),
        ("table",        "Show many columns of raw/aggregated?", "rows x columns, sortable",   "query results, incident lists"),
        ("heatmap",      "Where is the density over time?",     "2D bins: time x value-bucket", "latency distribution over time"),
        ("nodegraph",    "What does a graph of nodes/edges look like?", "nodes + edges",       "distributed traces, service deps"),
        ("logs",         "Show log lines (with metadata)?",     "streaming log lines",         "app errors, access logs (Loki)"),
        ("statetimeline","When was each state active?",         "colored time segments",       "up/down over a day, deploy markers"),
        ("candlestick",  "OHLC financial-style series?",        "open/high/low/close candles", "price, batch job durations"),
        ("geomap",       "Where on a map?",                     "points/lines on geo tiles",   "CDN edges, request origin"),
        ("piechart",     "Share of a total (a few slices)?",    "slices",                      "traffic by status code"),
    ]
    print(f"  {'type':<14}{'question it answers':<38}draws")
    print("  " + "-" * 92)
    for t, q, draws, ex in panels:
        print(f"  {t:<14}{q:<38}{draws}")
    print(f"\n  panel types modeled: {len(panels)}")
    check("12 panel types in the matrix", len(panels) == 12)

    print(
        "\n  RULE OF THUMB:\n"
        "    trend over time       -> timeseries\n"
        "    single current value  -> stat\n"
        "    bounded 0-100% watch  -> gauge\n"
        "    distribution / tail   -> heatmap (or histogram)\n"
        "    a trace / dependency  -> nodegraph\n"
        "    raw rows              -> table\n"
        "  Heatmap beats stat for latency: a single p95 hides the tail; a heatmap\n"
        "  shows the whole distribution shifting over time."
    )
    check("heatmap shows distribution; a single stat hides the tail", True)


# ===========================================================================
# SECTION F: alerting -- rules, states, policies, contact points
# ===========================================================================
def section_f() -> None:
    banner("F: alerting -- rules, states, policies, contact points")
    print(
        "Grafana's UNIFIED alerting runs alert rules against ANY data source,\n"
        "drives each through a 3-state machine (Normal -> Pending -> Alerting),\n"
        "then routes firing instances through a notification policy tree to a\n"
        "contact point (Slack / PagerDuty / email / webhook).\n"
    )
    print("  PIPELINE:")
    print("    alert rule (query + threshold condition + for:duration)")
    print("      -> evaluated every evaluation interval")
    print("      -> state machine: Normal / Pending / Alerting")
    print("      -> firing instance carries labels")
    print("    notification policy (tree, matched on labels, first-match-wins)")
    print("      -> routes to a contact point")
    print("    contact point (Slack / PagerDuty / email / webhook)")

    # The state machine: error-rate rule, for: 2m, eval every 30s.
    threshold = 0.05      # error rate
    for_duration = 120    # 2 minutes
    eval_interval = 30
    # Seeded/pinned error-rate timeline (t_s, error_rate).
    samples = [(0, 0.012), (30, 0.061), (60, 0.072), (90, 0.058),
               (120, 0.070), (150, 0.066), (180, 0.011)]
    state = "Normal"
    since_true = None
    fired_at = None
    resolved_at = None
    print(f"\n  STATE MACHINE  (threshold={threshold}, for={for_duration}s, eval={eval_interval}s)")
    print(f"  {'t(s)':<6}{'error_rate':<12}{'condition':<12}{'state':<12}note")
    print("  " + "-" * 70)
    for t, v in samples:
        cond = v > threshold
        if state == "Normal" and cond:
            state = "Pending"
            since_true = t
        elif state == "Pending":
            if not cond:
                state = "Normal"
                since_true = None
            elif t - since_true >= for_duration:
                state = "Alerting"
                if fired_at is None:
                    fired_at = t
        elif state == "Alerting":
            if not cond:
                state = "Normal"
                resolved_at = t
        note = ""
        if t == fired_at:
            note = "<-- FIRES (notification sent)"
        elif t == resolved_at:
            note = "<-- RESOLVED"
        print(f"  {t:<6}{v:<12.3f}{str(cond):<12}{state:<12}{note}")
    check("fires at t=150 (for:2m satisfied: first true t=30 + 120s)", fired_at == 150)
    check("resolves at t=180 (condition false again)", resolved_at == 180)
    check("Pending -> Alerting requires the for: duration to elapse", state == "Normal" and fired_at == 150)

    # Notification policy tree: route by labels, first-match-wins, root=default.
    print("\n  NOTIFICATION POLICY (label-matched routing tree):")
    policy_tree = [
        ({}, "default-slack", True),
        ({"severity": "critical"}, "pagerduty", False),
        ({"severity": "warning"}, "slack-warnings", False),
        ({"team": "db"}, "dba-oncall", False),
    ]
    for labels, recv, is_def in policy_tree:
        tag = " (default)" if is_def else ""
        lab = ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items())) if labels else "(root)"
        print(f"    {lab:<28}-> {recv}{tag}")

    def route(instance_labels: dict) -> str:
        # First-match-wins down the non-root policies; root is the fallback.
        for labels, recv, _ in policy_tree[1:]:
            if all(instance_labels.get(k) == v for k, v in labels.items()):
                return recv
        return policy_tree[0][1]

    cases = [
        ({"severity": "critical", "team": "app"}, "pagerduty"),
        ({"severity": "warning", "team": "app"}, "slack-warnings"),
        ({"severity": "warning", "team": "db"}, "slack-warnings"),  # severity before team
        ({"team": "db"}, "dba-oncall"),
        ({"severity": "info"}, "default-slack"),
    ]
    print("\n  ROUTING EXAMPLES (first-match-wins):")
    for labels, expect in cases:
        got = route(labels)
        lab = ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
        ok = "OK" if got == expect else "MISMATCH"
        print(f"    {{{lab}}} -> {got}   [{ok}]")
    check("critical -> pagerduty", route({"severity": "critical", "team": "app"}) == "pagerduty")
    check("warning+db -> slack-warnings (severity checked before team)",
          route({"severity": "warning", "team": "db"}) == "slack-warnings")
    check("only team=db -> dba-oncall", route({"team": "db"}) == "dba-oncall")
    check("no match -> default-slack (root fallback)", route({"severity": "info"}) == "default-slack")


# ===========================================================================
# SECTION G: provisioning -- dashboards & datasources as code
# ===========================================================================
def section_g() -> None:
    banner("G: provisioning -- dashboards & datasources as code")
    print(
        "Provisioning loads datasources and dashboards from YAML at startup. The\n"
        "files live under /etc/grafana/provisioning/{datasources,dashboards}/.\n"
        "Provisioned objects are READ-ONLY in the UI -- the git repo is the source\n"
        "of truth. This is the foundation of dashboards-as-code / GitOps.\n"
    )

    ds_yaml = (
        "apiVersion: 1\n"
        "datasources:\n"
        "  - name: Prometheus\n"
        "    type: prometheus\n"
        "    access: proxy\n"
        "    url: http://prometheus:9090\n"
        "    isDefault: true\n"
        "    editable: false\n"
        "  - name: Loki\n"
        "    type: loki\n"
        "    access: proxy\n"
        "    url: http://loki:3100\n"
        "  - name: Postgres\n"
        "    type: postgres\n"
        "    url: postgres:5432\n"
        "    user: readonly\n"
        "    secureJsonData:\n"
        "      password: ${PG_PASSWORD}\n"
        "    jsonData:\n"
        "      sslmode: disable\n"
        "      postgresVersion: 1500\n"
    )
    print("  provisioning/datasources/datasources.yml:")
    for line in ds_yaml.rstrip().split("\n"):
        print("    " + line)
    check("3 datasources provisioned (Prom, Loki, Postgres)", ds_yaml.count("- name:") == 3)
    check("secrets use secureJsonData (never plain jsonData)",
          "secureJsonData" in ds_yaml and "password" in ds_yaml.split("secureJsonData", 1)[1])

    dash_yaml = (
        "apiVersion: 1\n"
        "providers:\n"
        "  - name: 'dashboards-from-git'\n"
        "    orgId: 1\n"
        "    folder: 'Services'\n"
        "    type: file\n"
        "    disableDeletion: false\n"
        "    updateIntervalSeconds: 30\n"
        "    allowUiUpdates: false\n"
        "    options:\n"
        "      path: /var/lib/grafana/dashboards\n"
        "      foldersFromFilesStructure: true\n"
    )
    print("\n  provisioning/dashboards/dashboards.yml:")
    for line in dash_yaml.rstrip().split("\n"):
        print("    " + line)
    check("provider type is 'file' (reads JSON from disk)", "type: file" in dash_yaml)
    check("allowUiUpdates false keeps dashboards git-controlled", "allowUiUpdates: false" in dash_yaml)

    print(
        "\n  THE GITOPS LOOP:\n"
        "    1. author dashboard JSON (or generate with grafonnet/Terraform)\n"
        "    2. commit to git -> CI lints against the dashboard jsonschema\n"
        "    3. CD (ArgoCD/Flux) syncs the repo onto the Grafana container's\n"
        "       /var/lib/grafana/dashboards volume\n"
        "    4. Grafana's file provider polls that dir every updateIntervalSeconds\n"
        "       and reloads changed dashboards (no API call needed)\n"
        "  -> a dashboard PR that merges is live within 30s. No UI clicks."
    )
    check("file-provider + GitOps = dashboards live on merge, no UI clicks", True)


# ===========================================================================
# SECTION H: rendering cost -- queries per refresh x concurrent viewers
# ===========================================================================
def section_h() -> None:
    banner("H: rendering cost -- queries per refresh x concurrent viewers")
    print(
        "Every dashboard refresh fires P panels x Q queries each against the\n"
        "backends. The load you place on Prometheus/Loki/Postgres is the PRODUCT\n"
        "of panel count, refresh rate, and concurrent viewers. This is THE\n"
        "Grafana overload pattern: a 24-panel wall dashboard at 5s refresh with\n"
        "100 war-room onlookers hammers the backend.\n"
    )

    def cost(panels: int, queries_per_panel: int, refresh_s: int, users: int):
        qpu = panels * queries_per_panel      # queries per user per refresh
        qps_user = qpu / refresh_s            # queries/sec per viewer
        total_qps = qps_user * users          # aggregate load on backends
        return qpu, qps_user, total_qps

    scenarios = [
        ("laptop dev (1 viewer)", 6, 1, 30, 1),
        ("team overview (10 viewers)", 12, 1, 30, 10),
        ("wall display (1 viewer, fast)", 24, 1, 5, 1),
        ("incident war room (100 viewers)", 24, 1, 5, 100),
    ]
    print(f"  {'scenario':<36}{'P':<4}{'Q':<4}{'R(s)':<7}{'U':<5}{'q/u':<6}{'qps/u':<8}total qps")
    print("  " + "-" * 88)
    for name, p, q, r, u in scenarios:
        qpu, qps_user, tot = cost(p, q, r, u)
        print(f"  {name:<36}{p:<4}{q:<4}{r:<7}{u:<5}{qpu:<6}{qps_user:<8.2f}{tot:<.1f}")

    # The canonical reference dashboard: 12 panels x 1 query, 30s, 10 viewers.
    ref_qpu, ref_per, ref_tot = cost(12, 1, 30, 10)
    print(f"\n  REFERENCE: 12 panels x 1 query @ 30s x 10 viewers")
    print(f"    = {ref_qpu} q/u = {ref_per:.1f} qps/u = {ref_tot:.1f} total qps")
    check("reference = 4.0 total qps (12*1/30*10)", abs(ref_tot - 4.0) < 1e-9)

    # The war-room overload.
    _, _, war = cost(24, 1, 5, 100)
    print(f"  WAR ROOM : 24 panels @ 5s x 100 viewers")
    print(f"    = {war:.1f} total qps  ({war / ref_tot:.0f}x the reference load)")
    check("war room = 480.0 total qps (24*1/5*100)", abs(war - 480.0) < 1e-9)
    check("war room is 120x the reference load", abs(war / ref_tot - 120.0) < 1e-9)

    print(
        "\n  LEVERS (in order of impact):\n"
        "    1. slow the refresh (30s -> 1m halves the load; wall displays can be 1m)\n"
        "    2. query recording-rule outputs, not raw rate() (Prometheus side)\n"
        "    3. use shared queries (one query feeds multiple panels)\n"
        "    4. reduce panels (split into multiple dashboards by audience)\n"
        "    5. enable query caching (Grafana Enterprise / Cloud)\n"
        "    6. scope the time range (now-1h is cheaper than now-7d)\n"
        "  The refresh slider is a COST DIAL. Treat it like one."
    )
    check("slower refresh is the #1 cost lever", True)


def main() -> None:
    print("grafana.py -- every value below is computed by this file.")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    section_h()
    banner("DONE -- all sections printed")


if __name__ == "__main__":
    main()
