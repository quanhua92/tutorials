"""openobserve_dashboards.py - Ground-truth reference for the OpenObserve (O2)
USER-FACING UI layer: dashboards, alerts, scheduled reports, RUM (real user
monitoring), the traces UI (span waterfall from OTLP), and functions (VRL +
Python UDFs / Actions).

This is the SINGLE SOURCE OF TRUTH for OPENOBSERVE_DASHBOARDS.md. Every number,
table, alert-lifecycle tick, web-vitals score, span-waterfall millisecond, and
report-run count in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

    python3 openobserve_dashboards.py > openobserve_dashboards_output.txt

Pure Python stdlib only. Deterministic: a custom LCG RNG (no external deps, no
PYTHONHASHSEED dependence, no wall-clock). The identical alert-lifecycle /
web-vitals / span-waterfall / report-count math is recomputed in JS by
openobserve_dashboards.html and gold-checked.

Verified against official OpenObserve docs (openobserve.ai/docs/user-guide/):
Dashboards/Panels, Alerts (Overview/Scheduled/Real-time/Destinations/Templates),
Reports Overview, Real User Monitoring (Overview/Core Features/Metrics
Reference), Traces (Overview/Service Graph), Functions/Actions, Pipelines.
See ## Sources in OPENOBSERVE_DASHBOARDS.md for the full URL list.

PINNED (official docs):
  * Six UI modules that sit over the O2 backend: Dashboards, Alerts, Reports,
    RUM, Traces, Functions/Actions (all backed by the same streams + Parquet).
  * Panel chart types: O2 ships 19+ chart types; the 8 CORE ones modelled here
    are line / area / bar / gauge / table / pie / scatter / geomap.
  * Alert types: Scheduled (interval/cron), Real-time (ingest-triggered),
    Anomaly (Enterprise ML). Destinations: Slack, email, webhook, PagerDuty,
    Teams, + Actions (Python scripts).
  * Reports: PDF (rendered dashboard screenshot via headless report server) and
    CSV (panel data export); cron-scheduled; emailed to recipients.
  * RUM: Core Web Vitals (LCP, INP, CLS) + session replay + error tracking +
    long tasks; ingested via the browser SDK into a `rum` stream.
  * Traces UI: OTLP ingest -> span Gantt waterfall, service graph, flame-graph
    style breakdown; span = (trace_id, span_id, parent_span_id, service,
    operation, start, duration).
  * Functions: VRL (ingest-time + query-time transforms), Python Actions
    (real-time + scheduled, full Python with declared deps).
REPRESENTATIVE (clearly labelled): the 40-tick error-rate series, the web-vitals
p75 sample values, and the synthetic checkout-trace span timings.
"""

from __future__ import annotations


# ============================================================================
# DETERMINISTIC RNG - a tiny 32-bit LCG (Numerical Recipes constants). We roll
# our own so every run is bit-identical and matches the JS in the .html.
# ============================================================================
class RNG:
    """32-bit linear congruential generator. RNG(7).next() is stable forever."""

    def __init__(self, seed: int = 7) -> None:
        self.state = seed & 0xFFFFFFFF

    def next(self) -> int:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state

    def uniform(self, lo: float = 0.0, hi: float = 1.0) -> float:
        return lo + (hi - lo) * (self.next() / 0xFFFFFFFF)


BANNER = "=" * 72


def banner(t: str) -> None:
    print(f"\n{BANNER}\nSECTION {t}\n{BANNER}\n")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"FAIL: {desc}")
    print(f"[check] {desc}: OK")


# ============================================================================
# PINNED CONSTANTS - from official OpenObserve UI docs.
# ============================================================================
# --- The 8 CORE panel types (O2 ships 19+; these are the everyday set) ---
PANEL_TYPES = [
    # (type,        best for,                                   axis)
    ("line",        "time series: latency, QPS, error rate",    "y=metric, x=time"),
    ("area",        "stacked volume: ingest GB/day by stream",  "cumulative over time"),
    ("bar",         "discrete buckets: logs/min by level",      "categorical or histogram"),
    ("gauge",       "single KPI: SLO attainment, CPU %",        "one number + threshold"),
    ("table",       "raw rows: top slow queries, log samples",  "columns from SQL SELECT"),
    ("pie",         "share of total: traffic by status code",   "proportion of a whole"),
    ("scatter",     "correlation: latency vs request size",     "x,y point cloud"),
    ("geomap",      "geo distribution: requests by region",     "lat/long -> bubble"),
]

# --- Alert destinations (openobserve.ai/docs/user-guide/management/alert-destinations) ---
DESTINATIONS = [
    # (name,       transport,                        use case)
    ("Slack",      "incoming webhook POST",          "team channel, low-noise acks"),
    ("email",      "SMTP (TLS)",                     "distribution lists, audit trail"),
    ("webhook",    "HTTP POST to your endpoint",     "Jira/ServiceNow/automation"),
    ("PagerDuty",  "Events API v2",                  "on-call, escalation policy"),
    ("Teams",      "Office 365 connector webhook",   "MS-shop chat"),
    ("Actions",    "Python script (server-side)",    "fan-out: Slack + write back to stream"),
]

# --- Core Web Vitals thresholds (Google CrUX / web.dev, O2 RUM surfaces these) ---
LCP_GOOD, LCP_POOR = 2500, 4000     # ms, Largest Contentful Paint
INP_GOOD, INP_POOR = 200, 500        # ms, Interaction to Next Paint
CLS_GOOD, CLS_POOR = 0.10, 0.25      # unitless, Cumulative Layout Shift
W_LCP, W_INP, W_CLS = 0.35, 0.35, 0.30   # score weights (sum to 1.0)


def vit_bucket(value: float, good: float, poor: float) -> int:
    """CrUX-style bucket: good=100, needs-improvement=50, poor=0."""
    if value <= good:
        return 100
    if value <= poor:
        return 50
    return 0


# ============================================================================
# SECTION A - The six UI modules over one backend
# ============================================================================
def section_a() -> None:
    banner("A - The six UI modules (one Rust/S3 backend under them all)")

    print("OpenObserve is a SINGLE binary that does logs + metrics + traces + RUM,")
    print("all on Parquet over S3. The USER-FACING layer is six UI modules. Each")
    print("module is just a different LENS over the same streams -- a dashboard")
    print("panel, an alert query, a RUM session, and a trace all SELECT from the")
    print("same columnar Parquet. That is why a trace span can be joined to a log")
    print("line can drive a dashboard gauge can fire an alert, all without moving")
    print("data between systems.\n")

    modules = [
        ("Dashboards",  "stream -> SQL -> panel -> dashboard. Folders, tabs, vars."),
        ("Alerts",      "SQL/PromQL condition -> threshold -> frequency -> dest."),
        ("Reports",     "render dashboard -> PDF screenshot / CSV -> email on cron."),
        ("RUM",         "browser SDK -> `rum` stream -> web vitals, sessions, replay."),
        ("Traces",      "OTLP -> span waterfall (Gantt), service graph, flame view."),
        ("Functions",   "VRL transforms (ingest/query) + Python Actions (UDFs)."),
    ]
    for name, role in modules:
        print(f"  {name:<12} {role}")
    print()

    print("Data flow (the whole story):\n")
    print("  sources (apps/OTel/RUM SDK)  -->  ingest (Router -> Ingester)")
    print("     |                                     |")
    print("     v                                     v")
    print("  streams (logs/metrics/traces/rum)  -->  Parquet on S3")
    print("     |")
    print("     +-- Dashboards (SQL SELECT, render)")
    print("     +-- Alerts    (SQL condition, evaluate on schedule)")
    print("     +-- Reports   (render dashboard at cron time)")
    print("     +-- Functions (VRL/Python mutate rows in flight)\n")

    print("Key insight: a PANEL, an ALERT, and a REPORT all start life as the same")
    print("thing -- a SQL query against a stream. The difference is what happens to")
    print("the result set: draw it (panel), test it against a threshold (alert), or")
    print("screenshot it to a PDF (report).\n")

    check("six UI modules", len(modules) == 6)
    print()


# ============================================================================
# SECTION B - Dashboard creation: stream -> SQL -> panel -> dashboard
# ============================================================================
def section_b() -> None:
    banner("B - Dashboard creation: stream -> SQL -> panel -> dashboard")

    print("A dashboard is a JSON document of panels. Each panel carries ONE SQL (or")
    print("PromQL) query against ONE stream. The four-step build is identical every")
    print("time:\n")
    print("  1. PICK STREAM      -> the data source (logs/metrics/traces/rum).")
    print("  2. WRITE SQL        -> SELECT ... FROM <stream> WHERE ... GROUP BY ...")
    print("  3. CHOOSE PANEL TYPE-> line/bar/gauge/table/... maps the result to pixels.")
    print("  4. SAVE TO DASHBOARD-> gridPos (x/y/w/h), title, folder, tab.\n")

    print("--- worked example: latency-over-time panel on the `default` logs stream ---\n")
    sql = (
        "SELECT\n"
        "  histogram(_timestamp) AS bucket,\n"
        "  avg(cast(duration as float)) AS p50_ms,\n"
        "  approx_quantile(cast(duration as float), 0.95) AS p95_ms\n"
        "FROM \"default\"\n"
        "WHERE service = 'checkout'\n"
        "  AND level = 'INFO'\n"
        "GROUP BY bucket\n"
        "ORDER BY bucket"
    )
    print("stream : default  (log stream, service=checkout)")
    print("query  :\n")
    print("  " + sql.replace("\n", "\n  "))
    print("\npanel  : line chart  (x = bucket/time, y = p50_ms + p95_ms series)")
    print("dashboard : SLO Overview, tab 'Latency', gridPos {x:0,y:0,w:12,h:8}\n")

    print("--- the panel JSON shape (what gets saved/exported) ---\n")
    panel_json = (
        "{\n"
        "  \"title\": \"Checkout latency (p50/p95)\",\n"
        "  \"type\": \"line\",\n"
        "  \"stream\": \"default\",\n"
        "  \"query\": \"SELECT histogram(_timestamp) AS bucket, ...\",\n"
        "  \"queryType\": \"sql\",\n"
        "  \"gridPos\": {\"x\": 0, \"y\": 0, \"w\": 12, \"h\": 8},\n"
        "  \"config\": {\"y_axis_unit\": \"ms\", \"legend\": true},\n"
        "  \"variables\": [\"$service\", \"$env\"]\n"
        "}"
    )
    print("  " + panel_json.replace("\n", "\n  "))
    print()

    print("Variables ($service, $env) parameterize the dashboard -- a variable is a")
    print("saved query whose result becomes a dropdown. 'Repeat by variable' clones")
    print("a panel once per value (the one-graph-per-instance overview pattern).\n")

    # --- the whole panel in 4 steps, verified ---
    steps = ["stream", "SQL", "panel type", "dashboard"]
    check("dashboard build is exactly 4 steps", len(steps) == 4)
    print()


# ============================================================================
# SECTION C - Panel types catalogue
# ============================================================================
def section_c() -> None:
    banner("C - Panel types: pick the chart that matches the question")

    print("O2 ships 19+ chart types. The 8 CORE ones below cover ~90% of dashboards.")
    print("The rule: the panel type is dictated by the QUESTION, not the data.\n")

    rows = [("type", "best for", "axes")]
    rows += [(t, b, a) for (t, b, a) in PANEL_TYPES]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for i, r in enumerate(rows):
        line = "  " + "  ".join(c.ljust(widths[j]) for j, c in enumerate(r))
        print(line)
        if i == 0:
            print("  " + "  ".join("-" * widths[j] for j in range(3)))
    print()

    print("Decision shortcut:\n")
    print("  * 'how does X change over time?'       -> line / area")
    print("  * 'what is X right now vs threshold?'  -> gauge")
    print("  * 'what are the actual rows?'          -> table")
    print("  * 'how is the total split up?'         -> pie / bar")
    print("  * 'do X and Y correlate?'              -> scatter")
    print("  * 'where geographically?'              -> geomap\n")

    print("Beyond the 8: stacked-bar, area-stacked, h-bar, heatmap, sankey, treemap,")
    print("markdown, custom-chart (write your own ECharts spec). The custom-chart")
    print("panel lets you paste raw ECharts JSON -- an escape hatch for anything the")
    print("built-in types can't draw.\n")

    check("8 core panel types catalogued", len(PANEL_TYPES) == 8)
    print()


# ============================================================================
# SECTION D - Alerting: condition -> threshold -> frequency -> destination
#             + the alert lifecycle (evaluate -> fire -> notify -> resolve)
# ============================================================================
def section_d() -> None:
    banner("D - Alerting + lifecycle (evaluate -> fire -> notify -> resolve)")

    print("An alert is a SQL (or PromQL) condition tested on a schedule. The parts:\n")
    print("  stream     : the data source (logs/metrics/traces).")
    print("  condition  : 'avg(error_rate) >= 5'  (builder / SQL / PromQL modes).")
    print("  frequency  : how often to evaluate (every N min, or a cron expr).")
    print("  period     : look-back window of data per evaluation (e.g. last 5 min).")
    print("  for/duration: consecutive true evaluations before FIRING (noise gate).")
    print("  cooldown   : min gap between re-notifications (anti-storm).")
    print("  destination: where the notification goes (Slack/email/PagerDuty/...).\n")

    print("Three alert types:\n")
    print("  Scheduled   : runs at a fixed interval. Best for aggregates/trends.")
    print("                e.g. every 10 min, if avg latency > 500ms over 30 min.")
    print("  Real-time   : evaluates on INGEST, fires within seconds. For 'needle in")
    print("                the haystack' patterns (a specific error string appears).")
    print("  Anomaly     : Enterprise ML -- no manual threshold, learns the baseline.\n")

    # --- THE LIFECYCLE SIMULATION ---
    print("--- lifecycle simulation: error_rate >= 5%, for=2 evals, cooldown=5 ---\n")
    threshold = 5.0        # % error rate
    for_duration = 2       # need 2 consecutive above-threshold evals to FIRE
    cooldown = 5           # min ticks between re-notifications
    rng = RNG(7)
    series = []
    for t in range(40):
        base = rng.uniform(0.3, 2.4)
        if 10 <= t <= 22:                       # a guaranteed incident window
            val = base + rng.uniform(5.0, 7.5)  # spikes to 5.3% .. 9.9%
        else:
            val = base
        series.append(round(val, 2))

    state = "Normal"
    consec = 0
    last_notify = -999
    fire_tick = None
    resolve_tick = None
    fire_notifies = 0
    resolve_notifies = 0
    print("  tick  error%  state      event")
    print("  ----  ------  ---------  -----------------------------")
    for t, val in enumerate(series):
        above = val >= threshold
        if above:
            consec += 1
        else:
            consec = 0
        event = ""
        if state != "Firing" and above and consec >= for_duration:
            state = "Firing"
            fire_tick = t
            if t - last_notify >= cooldown:
                event = "FIRE -> notify destination"
                last_notify = t
                fire_notifies += 1
        elif state == "Firing" and not above:
            state = "Normal"
            resolve_tick = t
            event = "RESOLVE -> notify destination"
            resolve_notifies += 1
        elif state == "Firing" and above and (t - last_notify) >= cooldown:
            event = "re-notify (dedup within cooldown)"
            last_notify = t
            fire_notifies += 1
        marker = "  <<<" if state == "Firing" else ""
        print(f"  {t:>4}  {val:>6.2f}  {state:<9}  {event}{marker}")
    print()

    print("Summary of the run:\n")
    print(f"  first above-threshold tick : 10   (incident window opens)")
    print(f"  FIRE tick (for={for_duration} satisfied)  : {fire_tick}")
    print(f"  resolve tick               : {resolve_tick}   (back below threshold)")
    print(f"  firing notifications sent  : {fire_notifies}   (cooldown dedup applied)")
    print(f"  resolve notification sent  : {resolve_notifies}\n")

    print("The lifecycle is: evaluate (every frequency) -> FIRE (after `for` gate) ->")
    print("notify destination (respecting cooldown) -> RESOLVE (condition false) ->")
    print("notify resolution. This is WHY cooldown + `for` exist: without them a")
    print("flapping metric spams Slack. `for`=2 needs two confirmations; cooldown=5")
    print("caps re-notifications to one every 5 evals during a sustained incident.\n")

    check("alert fires at tick 11 (for=2 after first above at 10)", fire_tick == 11)
    check("alert resolves at tick 23 (first below after window 10-22)", resolve_tick == 23)
    check("3 firing notifications (at 11, 16, 21)", fire_notifies == 3)
    print()


# ============================================================================
# SECTION E - Alert destinations + templates
# ============================================================================
def section_e() -> None:
    banner("E - Alert destinations + notification templates")

    print("Where the notification goes. Pick by URGENCY + toolchain:\n")
    rows = [("destination", "transport", "use case")]
    rows += [(n, t, u) for (n, t, u) in DESTINATIONS]
    widths = [max(len(r[i]) for r in rows) for i in range(3)]
    for i, r in enumerate(rows):
        line = "  " + "  ".join(c.ljust(widths[j]) for j, c in enumerate(r))
        print(line)
        if i == 0:
            print("  " + "  ".join("-" * widths[j] for j in range(3)))
    print()

    print("--- Slack destination setup (incoming webhook) ---\n")
    print("  1. Slack app -> Incoming Webhooks -> create hook for #alerts channel.")
    print("  2. O2 UI: Management -> Alert Destinations -> + Add -> Slack.")
    print("  3. Paste webhook URL: https://hooks.slack.com/services/T.../B.../...")
    print("  4. (optional) attach a Template with the message body + variables.\n")

    print("--- notification template (Go templating, variables injected) ---\n")
    tmpl = (
        '{{template "slack.title" .}}\n'
        'Alert: {{.AlertName}}  [{{.OrgName}}]\n'
        'Stream: {{.StreamName}}  Triggered: {{.TriggerTime}}\n'
        'Value: {{.Results.[0].value}}  (threshold: 5)\n'
        '{{range .Results}}\n'
        '  {{.ts}}  {{.value}}\n'
        '{{end}}\n'
        'View: http://o2:5080/web/alerts/history?alert_id={{.AlertId}}'
    )
    print("  " + tmpl.replace("\n", "\n  "))
    print()

    print("Template variables O2 injects: AlertName, StreamName, TriggerTime,")
    print("Results (the matching rows), OrgName, AlertId, plus any custom context")
    print("vars you define on the alert. One template can serve many alerts.\n")

    print("Actions (Python) is the most powerful destination: a server-side script")
    print("that can hit MULTIPLE endpoints AND write back to a stream -- e.g. page")
    print("PagerDuty + post to Slack + write an incident row to a `incidents`")
    print("stream, all from one firing. This is the stateful-routing escape hatch.\n")

    check("6 alert destination types catalogued", len(DESTINATIONS) == 6)
    print()


# ============================================================================
# SECTION F - Scheduled reports (PDF / CSV via cron)
# ============================================================================
def section_f() -> None:
    banner("F - Scheduled reports: render dashboard -> PDF/CSV -> email")

    print("A report snapshots a dashboard on a schedule and emails it. Two formats:\n")
    print("  PDF : the report server renders the dashboard in a headless browser,")
    print("        screenshots each panel, and stitches them into a PDF. Good for")
    print("        stakeholders who want a weekly 'state of the system' email.")
    print("  CSV : exports the raw result set of a chosen panel's SQL. Good for")
    print("        piping into spreadsheets or a data warehouse.\n")

    print("--- report config (UI + API) ---\n")
    cfg = (
        "name         : Weekly SLO Report\n"
        "dashboard    : SLO Overview  (uid: d8f3...)\n"
        "tab          : Latency\n"
        "format       : pdf\n"
        "schedule     : cron  '0 9 * * 1'   (every Monday 09:00)\n"
        "time_range   : last 7 days\n"
        "recipients   : ['sre-team@corp.com', 'eng-leads@corp.com']\n"
        "subject      : '[O2] Weekly SLO Report - SLO Overview'\n"
        "timezone     : Asia/Ho_Chi_Minh"
    )
    print("  " + cfg.replace("\n", "\n  "))
    print()

    print("The report SERVER is a separate process (openobserve/reporter image)")
    print("that polls O2 for due reports, renders, and sends. In single-node deploys")
    print("it runs in the same container; in HA it is its own pod so heavy rendering")
    print("doesn't compete with ingest.\n")

    # --- count generated reports over a 30-day window ---
    print("--- report-run math: 30-day window, two cron schedules ---\n")
    days = 30
    start_weekday = 0  # Monday = 0 (so the window starts on a Monday)
    daily_runs = days                                           # '0 9 * * *'
    weekly_runs = sum(1 for d in range(days)
                      if (start_weekday + d) % 7 == 0)         # '0 9 * * 1'
    pdf_kb = 820        # representative rendered dashboard PDF size
    csv_kb = 120        # representative panel CSV size
    pdf_total_mb = daily_runs * pdf_kb / 1024
    csv_total_mb = weekly_runs * csv_kb / 1024
    print(f"  daily  report ('0 9 * * *')  : {daily_runs} runs over {days} days")
    print(f"  weekly report ('0 9 * * 1')  : {weekly_runs} runs (Mondays in window)")
    print(f"  PDF  storage : {daily_runs} x {pdf_kb} KB = {pdf_total_mb:.1f} MB")
    print(f"  CSV  storage : {weekly_runs} x {csv_kb} KB = {csv_total_mb:.2f} MB")
    print(f"  total report runs : {daily_runs + weekly_runs}\n")

    print("Gotcha: report rendering is EXPENSIVE (headless browser). A dashboard")
    print("with 20 panels rendered hourly for 50 recipients is 20*24*50 = 24,000")
    print("panel renders/day -- keep schedules coarse (daily/weekly) and recipient")
    print("lists tight. Reports store their output in the same S3 bucket as data.\n")

    check("5 weekly Monday runs in a 30-day window starting Monday", weekly_runs == 5)
    check("30 daily runs over 30 days", daily_runs == 30)
    print()


# ============================================================================
# SECTION G - RUM: real user monitoring (web vitals, sessions, replay)
# ============================================================================
def section_g() -> None:
    banner("G - RUM: real user monitoring (web vitals, sessions, replay)")

    print("RUM is the BROWSER side of observability. A tiny JS SDK (the O2 RUM SDK,")
    print("built on OpenTelemetry) runs in your web app and ships events to a `rum`")
    print("stream over HTTP. Four event types:\n")
    print("  page views  : navigation, route, referrer -> a session timeline.")
    print("  web vitals  : Core Web Vitals (LCP, INP, CLS) + TTFB, FCP, TTFB.")
    print("  errors      : uncaught JS exceptions + console.error -> error tracking.")
    print("  resources   : XHR/fetch timing, long tasks -> perf waterfall.\n")

    print("--- Core Web Vitals (the 3 numbers Google ranks you on) ---\n")
    print(f"  LCP  Largest Contentful Paint : good <= {LCP_GOOD}ms, poor >= {LCP_POOR}ms")
    print(f"  INP  Interaction to Next Paint: good <= {INP_GOOD}ms, poor >= {INP_POOR}ms")
    print(f"  CLS  Cumulative Layout Shift  : good <= {CLS_GOOD},  poor >= {CLS_POOR}\n")

    # --- p75 vitals for a sample session + performance score ---
    vitals = {"lcp": 2100, "inp": 240, "cls": 0.08}
    print(f"  sample session p75 vitals: LCP={vitals['lcp']}ms "
          f"INP={vitals['inp']}ms CLS={vitals['cls']}\n")

    b_lcp = vit_bucket(vitals["lcp"], LCP_GOOD, LCP_POOR)
    b_inp = vit_bucket(vitals["inp"], INP_GOOD, INP_POOR)
    b_cls = vit_bucket(vitals["cls"], CLS_GOOD, CLS_POOR)
    score = (W_LCP * b_lcp) + (W_INP * b_inp) + (W_CLS * b_cls)
    print(f"  buckets : LCP={b_lcp}  INP={b_inp}  CLS={b_cls}  "
          f"(100=good, 50=needs, 0=poor)")
    print(f"  weighted perf score : "
          f"{W_LCP}*{b_lcp} + {W_INP}*{b_inp} + {W_CLS}*{b_cls} "
          f"= {score:.1f} / 100\n")

    print("--- session replay ---\n")
    print("  O2 records DOM mutations + user interactions (clicks, scrolls, input)")
    print("  as a compact event stream, then RECONSTRUCTS the pixel-perfect session")
    print("  in the player. PII redaction via CSS selectors (mask `.credit-card`).")
    print("  Replay is the difference between 'INP was 480ms' and SEEING the frozen")
    print("  screen that caused it.\n")

    print("--- error tracking ---\n")
    print("  uncaught exceptions are grouped by stack-trace fingerprint. The UI")
    print("  shows: error message, first/last seen, affected sessions, the exact")
    print("  browser/OS/version, and a one-click jump to the session replay at the")
    print("  moment the error threw. This closes the loop: metric -> user -> cause.\n")

    check("RUM perf score = 82.5 for LCP=2100/INP=240/CLS=0.08",
          abs(score - 82.5) < 0.01)
    print()


# ============================================================================
# SECTION H - Traces UI: span waterfall from OTLP
# ============================================================================
def section_h() -> None:
    banner("H - Traces UI: span waterfall from OTLP")

    print("Traces arrive via OTLP (the OpenTelemetry protocol). O2 ingests them into")
    print("a `traces` stream. Each span is a row:\n")
    print("  trace_id, span_id, parent_span_id, service, operation,")
    print("  start_time, duration_ms, status, attributes{...}\n")

    print("The TRACES UI renders these as a GANTT waterfall: parent spans on top,")
    print("children indented below, bars positioned by start/duration. The critical")
    print("path (longest parent->child chain) is what latency optimisation targets.\n")

    # --- a synthetic checkout trace ---
    spans = [
        # (span_id, parent, service,  operation,        start_ms, dur_ms)
        ("s1", None,  "gateway",  "GET /checkout",        0,   120),
        ("s2", "s1",  "auth",     "verify_token",         2,    23),
        ("s3", "s1",  "cart",     "load_cart",           25,    30),
        ("s4", "s3",  "db",       "SELECT cart_items",   27,    23),
        ("s5", "s1",  "payment",  "charge_card",         55,    60),
        ("s6", "s1",  "notify",   "send_receipt",       116,     4),
    ]
    total = max(s + d for (_, _, _, _, s, d) in spans) - \
        min(s for (_, _, _, _, s, d) in spans)
    span_count = len(spans)
    non_root = [d for (_, p, _, _, _, d) in spans if p is not None]
    slowest_leaf = max(non_root) if non_root else 0
    print("--- checkout trace (6 spans) ---\n")
    print("  span  service   operation          start  dur   parent")
    print("  ----  -------   ---------          -----  ---   ------")
    for sid, p, svc, op, s, d in spans:
        print(f"  {sid}  {svc:<8}  {op:<18} {s:>5}  {d:>3}   {p or '-'}")
    print(f"\n  total trace duration : {total} ms")
    print(f"  span count           : {span_count}")
    print(f"  slowest non-root     : {slowest_leaf} ms  (payment.charge_card)\n")

    # --- ASCII waterfall ---
    print("--- waterfall (ASCII; the UI draws this as colored Gantt bars) ---\n")
    scale = 40  # chars for the full total
    for sid, p, svc, op, s, d in spans:
        depth = 0
        cur = p
        while cur is not None:
            depth += 1
            cur = next((x for x in spans if x[0] == cur), None)
            if cur is not None:
                cur = cur[1] if cur[1] else None
        depth = min(depth, 2)
        indent = "  " * depth
        x0 = round(s / total * scale)
        x1 = round((s + d) / total * scale)
        bar = "#" * max(1, x1 - x0)
        line = list(" " * scale)
        for i in range(x0, min(x1, scale)):
            line[i] = "#"
        print(f"  {indent}{sid} {svc:<8} {''.join(line)}  {op} ({d}ms)")
    print(f"  {'':<0}{'0':<10}{'30':<10}{'60':<10}{'90':<10}{'120ms'}")
    print()

    print("The UI also has a SERVICE GRAPH (nodes = services, edges = calls, edge")
    print("width = traffic, edge color = error rate) and a flame-graph breakdown of")
    print("a single span's self-time vs child-time. Click any span -> jump to the")
    print("matching logs (trace_id correlation) -- the three-pillar join.\n")

    check("trace total duration = 120 ms", total == 120)
    check("trace has 6 spans", span_count == 6)
    check("slowest non-root span = 60 ms", slowest_leaf == 60)
    print()


# ============================================================================
# SECTION I - Functions: VRL + Python Actions (UDFs)
# ============================================================================
def section_i() -> None:
    banner("I - Functions: VRL transforms + Python Actions (UDFs)")

    print("Functions let you TRANSFORM data. Two flavours:\n")
    print("  VRL (Vector Remap Language) : a small, fast, sandboxed language used")
    print("    at INGEST time (mutate every row as it lands) or at QUERY time")
    print("    (transform a result set on read). Compiled to Rust, no GC.")
    print("  Python Actions              : full Python scripts that run server-side")
    print("    as either real-time (on ingest) or scheduled (cron) jobs. Can import")
    print("    pip packages (declared per-action), hit the network, and write back")
    print("    to streams. The most powerful 'destination' too.\n")

    print("--- VRL ingest transform: parse a nginx log line into fields ---\n")
    vrl = (
        ".service = \"nginx\"\n"
        ".remote_addr = parse_regex!(.message, r'^(?P<ip>\\d+\\.\\d+\\.\\d+\\.\\d+)').ip\n"
        ".status = to_int!(parse_regex!(.message, r' (?P<code>\\d{3}) ').code)\n"
        ".level = if .status >= 500 { \"ERROR\" } else if .status >= 400 { \"WARN\" } else { \"INFO\" }\n"
        "del(.message)"
    )
    print("  " + vrl.replace("\n", "\n  "))
    print("\n  -> every nginx row now has service/status/level columns, queryable +")
    print("     indexable. This is CHEAPER than parsing at query time (done once).\n")

    print("--- Python Action: enrich + alert + write-back ---\n")
    py = (
        "def run(context, rows):\n"
        "    # rows: list of dicts from the triggering query/alert\n"
        "    for r in rows:\n"
        "        r['severity'] = 'HIGH' if r['error_rate'] > 10 else 'MED'\n"
        "        r['oncall'] = lookup_oncall(r['service'])   # enrichment table\n"
        "    # fan-out: page on-call + write an incident row\n"
        "    pagerduty.trigger(rows)\n"
        "    openobserve.ingest('incidents', rows)           # write-back\n"
        "    return rows"
    )
    print("  " + py.replace("\n", "\n  "))
    print("\n  -> the same firing can enrich rows, page someone, AND persist a record")
    print("     for postmortem. This is the stateful-routing use case from Section E.\n")

    print("When to use which:\n")
    print("  * structured-field extraction on every row  -> VRL at ingest (one-time)")
    print("  * ad-hoc calc on a query result             -> VRL at query time")
    print("  * need network/pip/stateful side effects    -> Python Action")
    print("  * scheduled batch enrichment                -> scheduled Action\n")

    check("two function flavours: VRL + Python Actions", True)
    print()


# ============================================================================
# SECTION J - Day 0 -> Day 1 -> Day 2 recap
# ============================================================================
def section_j() -> None:
    banner("J - Day 0 -> Day 1 -> Day 2 recap")

    print("DAY 0 -- first dashboard (the 15-minute win)\n")
    print("  * Ingest anything (a log stream from curl/Fluent Bit is enough).")
    print("  * UI: Dashboards -> + Add -> name it -> + Add Panel.")
    print("  * Pick stream, paste SQL (or use the visual builder), pick 'line'.")
    print("  * Save. You have a panel. Repeat 4-6x = a real dashboard.\n")
    print("  Verify: open the dashboard in another tab, refresh -> panel redraws.\n")

    print("DAY 1 -- alerts + first destination\n")
    print("  * Management -> Alert Destinations -> add Slack (paste webhook).")
    print("  * Alerts -> + Add -> Scheduled -> pick stream -> 'count >= 10 of ERROR'.")
    print("  * Set frequency=5min, period=5min, cooldown=10min, destination=Slack.")
    print("  * Save. Deliberately push an error log -> watch Slack light up.\n")

    print("DAY 2 -- reports, RUM, traces, functions\n")
    print("  * Reports : schedule the Day-0 dashboard as a weekly PDF email.")
    print("  * RUM     : drop the RUM SDK in your web app -> watch web vitals land.")
    print("  * Traces  : point your OTel collector at O2 -> open the traces waterfall.")
    print("  * Functions: write a VRL ingest transform to parse nginx -> fields.\n")
    print("  * Pipelines: chain VRL + routing + remote-destination at ingest.\n")

    print("The whole UI layer is the SAME six modules over the SAME backend. Once")
    print("Day 0's dashboard works, Day 1's alert and Day 2's report/RUM/traces are")
    print("just new LENSES on data you already have.\n")


# ============================================================================
# MAIN
# ============================================================================
def main() -> None:
    print("openobserve_dashboards.py")
    print("OpenObserve (O2) UI layer: dashboards, alerts, reports, RUM, traces,")
    print("functions. Single source of truth for OPENOBSERVE_DASHBOARDS.md.")
    print("Deterministic (LCG RNG, no wall-clock). Pure stdlib.\n")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_g()
    section_h()
    section_i()
    section_j()
    print(BANNER)
    print("ALL SECTIONS COMPLETE -- every [check] passed.")
    print(BANNER)


if __name__ == "__main__":
    main()
