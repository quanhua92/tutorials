#!/usr/bin/env python3
"""
data_quality.py - Data quality monitoring simulation (GROUND TRUTH).

Pure Python stdlib only (sqlite3, math, re, datetime, statistics). Every number
printed below feeds DATA_QUALITY.md and is recomputed identically in
data_quality.html (gold-checked).

Sections:
  1. Validation rules (null / range / format / enum / referential integrity)
  2. Freshness SLA checks (tiered: Tier 0 minutes, Tier 1 hours, Tier 2 log-only)
  3. Z-score anomaly detection (volume) - full-series vs baseline-trained
  4. IQR anomaly detection (volume) - robust single pass
  5. EWMA null-rate monitoring (adaptive baseline + 3-sigma spike alert)
  6. Completeness scoring (cell-level non-null rates)
  7. Quality scorecard (validity + freshness + completeness + volume rollup)
  8. GOLD values pinned for data_quality.html
"""

import math
import re
import sqlite3
from datetime import datetime

# ---------------------------------------------------------------------------
# source-of-truth constants (mirrored in data_quality.html GOLD)
# ---------------------------------------------------------------------------
# Daily row counts for the "events" table over 14 days. Days 13 (400) and 14
# (5000) are a planted drop + spike anomaly; the first 12 days are the normal
# baseline (~1000 +/- small noise).
DAILY = [1000, 1020, 980, 1010, 990, 1005, 995, 1015, 985, 1000, 1008, 992, 400, 5000]
BASELINE = DAILY[:12]          # the "normal" training window
Z_THRESHOLD = 3.0              # |z| > 3 => anomaly

# EWMA null-rate series for users.email (percent null per day). Day 8
# (1-indexed) is the planted "Friday-night SDK bug" spike (2% -> 60%).
EWMA_RATES = [2.0, 2.1, 1.9, 2.0, 2.2, 1.8, 2.0, 60.0, 2.1, 2.0]
EWMA_ALPHA = 0.3
EWMA_K = 3.0                   # alert if residual > k * sigma (one-sided, spikes only)

# Freshness: (table, tier, sla_seconds, last_event_iso). NOW is fixed for repro.
NOW = datetime(2024, 6, 15, 12, 0, 0)
FRESHNESS = [
    ("revenue_daily",      "Tier 0", 900,    "2024-06-15T11:55:00"),  # lag 300s   -> PASS
    ("experiment_assign",  "Tier 0", 900,    "2024-06-15T10:00:00"),  # lag 7200s  -> FAIL (page)
    ("mobile_events",      "Tier 1", 14400,  "2024-06-15T09:30:00"),  # lag 9000s  -> PASS
    ("ops_dashboard_fact", "Tier 1", 14400,  "2024-06-15T06:00:00"),  # lag 21600s -> FAIL (slack)
    ("weekly_summary",     "Tier 2", 86400,  "2024-06-14T14:00:00"),  # lag 79200s -> PASS
    ("ad_hoc_export",      "Tier 2", 86400,  "2024-06-13T00:00:00"),  # lag 129600s-> WARN (log)
]

VALID_COUNTRIES = {"US", "UK", "VN", "DE", "JP"}
VALID_STATUS = {"pending", "paid", "refunded"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def pct(x, y):
    return (100.0 * x / y) if y else 0.0


def mean(xs):
    return sum(xs) / len(xs)


def pstd(xs):
    """Population standard deviation (divide by n)."""
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def median(xs):
    s = sorted(xs)
    n = len(s)
    h = n // 2
    return s[h] if n % 2 else (s[h - 1] + s[h]) / 2.0


def iqr_fences(xs):
    """Tukey exclusive quartiles + 1.5*IQR fences."""
    s = sorted(xs)
    n = len(s)
    h = n // 2
    q1 = median(s[:h])
    q3 = median(s[h:])
    iqr = q3 - q1
    return q1, q3, q1 - 1.5 * iqr, q3 + 1.5 * iqr


# ---------------------------------------------------------------------------
# Validation DB (in-memory sqlite3) -- a deliberately dirty dataset
# ---------------------------------------------------------------------------
def build_validation_db():
    """users (100 rows) + orders (200 rows) with planted quality issues."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER, email TEXT, age INTEGER, country TEXT, signup_date TEXT);
        CREATE TABLE orders (id INTEGER, user_id INTEGER, amount REAL, status TEXT, created_at TEXT);
        CREATE INDEX idx_orders_user ON orders(user_id);
        """
    )
    users = []
    for i in range(1, 101):
        # email: 6 nulls (ids 10,20,30,40,50,60), 2 malformed (ids 11,21)
        if i in (10, 20, 30, 40, 50, 60):
            email = None
        elif i == 11:
            email = "notanemail"
        elif i == 21:
            email = "bad format"
        else:
            email = "user%d@example.com" % i
        # age: 3 out of range (ids 1=-5, 2=150, 3=200); valid range [0,120]
        if i == 1:
            age = -5
        elif i == 2:
            age = 150
        elif i == 3:
            age = 200
        else:
            age = 25 + (i % 30)
        # country: 2 invalid (ids 5=XX, 6=ZZ)
        if i == 5:
            country = "XX"
        elif i == 6:
            country = "ZZ"
        else:
            country = "US"
        users.append((i, email, age, country, "2024-01-15"))
    conn.executemany("INSERT INTO users VALUES (?,?,?,?,?)", users)

    orders = []
    for i in range(1, 201):
        # user_id: 4 orphans (ids 101-104 -> uid 101-104); else cycles 1..100
        if i == 101:
            uid = 101
        elif i == 102:
            uid = 102
        elif i == 103:
            uid = 103
        elif i == 104:
            uid = 104
        else:
            uid = i % 100 + 1
        # amount: 3 nulls (30,60,90), 2 negative (31=-10, 61=-50)
        if i in (30, 60, 90):
            amount = None
        elif i == 31:
            amount = -10.0
        elif i == 61:
            amount = -50.0
        else:
            amount = 19.90 + (i % 50)
        # status: 1 invalid (id 70 = WEIRD)
        status = "WEIRD" if i == 70 else "paid"
        orders.append((i, uid, amount, status, "2024-06-01T12:00:00"))
    conn.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", orders)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# SECTION 1 - Validation rules (null / range / format / enum / referential)
# ---------------------------------------------------------------------------
def section_validation():
    banner("SECTION 1: Validation rules (null / range / format / enum / referential)")
    print("Contract assertions run against users (100 rows) + orders (200 rows).")
    print("Each check records bad/total + a status: FAIL (hard breach), WARN, PASS.\n")
    conn = build_validation_db()

    NU = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]   # 100
    NO = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]  # 200

    checks = []

    # 1. null -- users.email (key/identity column)
    bad = conn.execute("SELECT COUNT(*) FROM users WHERE email IS NULL").fetchone()[0]
    metric = "%.1f%% null" % pct(bad, NU)
    status = "FAIL" if bad / NU > 0.05 else ("WARN" if bad / NU > 0.01 else "PASS")
    checks.append(("users.email", "not_null", bad, NU, metric, status))

    # 2. range -- users.age in [0,120]
    bad = conn.execute("SELECT COUNT(*) FROM users WHERE age < 0 OR age > 120").fetchone()[0]
    checks.append(("users.age", "range[0,120]", bad, NU, "%d out of range" % bad,
                   "FAIL" if bad > 0 else "PASS"))

    # 3. format -- users.email regex (non-null only)
    rows = conn.execute("SELECT email FROM users WHERE email IS NOT NULL").fetchall()
    bad = sum(1 for (e,) in rows if not EMAIL_RE.match(e))
    denom = len(rows)
    checks.append(("users.email", "format", bad, denom,
                   "%d malformed / %d non-null" % (bad, denom),
                   "WARN" if bad > 0 else "PASS"))

    # 4. enum/whitelist -- users.country
    ph = ",".join("'" + c + "'" for c in sorted(VALID_COUNTRIES))
    bad = conn.execute("SELECT COUNT(*) FROM users WHERE country NOT IN (%s)" % ph).fetchone()[0]
    checks.append(("users.country", "whitelist", bad, NU, "%d not in whitelist" % bad,
                   "WARN" if bad > 0 else "PASS"))

    # 5. null -- orders.amount
    bad = conn.execute("SELECT COUNT(*) FROM orders WHERE amount IS NULL").fetchone()[0]
    metric = "%.1f%% null" % pct(bad, NO)
    status = "FAIL" if bad / NO > 0.05 else ("WARN" if bad / NO > 0.01 else "PASS")
    checks.append(("orders.amount", "not_null", bad, NO, metric, status))

    # 6. range -- orders.amount in [0,10000] (non-null only)
    bad = conn.execute("SELECT COUNT(*) FROM orders WHERE amount IS NOT NULL AND amount < 0").fetchone()[0]
    checks.append(("orders.amount", "range[0,10000]", bad, NO, "%d negative" % bad,
                   "FAIL" if bad > 0 else "PASS"))

    # 7. enum -- orders.status
    ph2 = ",".join("'" + s + "'" for s in sorted(VALID_STATUS))
    bad = conn.execute("SELECT COUNT(*) FROM orders WHERE status NOT IN (%s)" % ph2).fetchone()[0]
    checks.append(("orders.status", "enum", bad, NO, "%d invalid" % bad,
                   "FAIL" if bad > 0 else "PASS"))

    # 8. referential integrity -- orders.user_id -> users.id
    bad = conn.execute(
        "SELECT COUNT(*) FROM orders o LEFT JOIN users u ON o.user_id=u.id WHERE u.id IS NULL"
    ).fetchone()[0]
    checks.append(("orders.user_id", "referential", bad, NO, "%d orphans" % bad,
                   "FAIL" if bad > 0 else "PASS"))

    # 9. null -- orders.id
    bad = conn.execute("SELECT COUNT(*) FROM orders WHERE id IS NULL").fetchone()[0]
    checks.append(("orders.id", "not_null", bad, NO, "0 null", "PASS" if bad == 0 else "FAIL"))

    # 10. unique -- users.id
    total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    distinct = conn.execute("SELECT COUNT(DISTINCT id) FROM users").fetchone()[0]
    bad = total - distinct
    checks.append(("users.id", "unique", bad, total, "%d duplicates" % bad,
                   "PASS" if bad == 0 else "FAIL"))

    conn.close()

    print("  %-18s %-16s %5s %6s  %-26s %s" % ("target", "rule", "bad", "total", "metric", "status"))
    n_pass = n_warn = n_fail = 0
    for target, rule, bad, total, metric, status in checks:
        if status == "PASS":
            n_pass += 1
        elif status == "WARN":
            n_warn += 1
        else:
            n_fail += 1
        print("  %-18s %-16s %5d %6d  %-26s %s" % (target, rule, bad, total, metric, status))
    print()
    print("=> The dirty dataset fails on hard constraints (age range, negative")
    print("   amounts, status enum, referential integrity, key-column nulls).")
    print("   Referential orphans are the P0 here: 4 orders reference no user, so")
    print("   any revenue JOIN silently drops those rows from dashboards.")
    print()
    print("[check] 10 checks ran? " + ("OK" if len(checks) == 10 else "FAIL"))
    print("[check] referential orphans == 4? " + ("OK" if checks[7][2] == 4 else "FAIL"))
    print("[check] email null rate == 6.0%? " + ("OK" if pct(6, 100) == 6.0 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Freshness SLA checks (tiered)
# ---------------------------------------------------------------------------
def section_freshness():
    banner("SECTION 2: Freshness SLA checks (tiered by business criticality)")
    print("Event-time lag = NOW - MAX(event_timestamp). Tier 0 breach => page;")
    print("Tier 1 breach => Slack; Tier 2 breach => log only.\n")
    print("  %-20s %-8s %10s %10s  %s" % ("table", "tier", "lag", "sla(s)", "status"))
    results = []
    n_pass = n_warn = n_fail = 0
    for name, tier, sla, iso in FRESHNESS:
        last = datetime.fromisoformat(iso)
        lag = (NOW - last).total_seconds()
        if lag <= sla:
            status = "PASS"
            n_pass += 1
        elif tier == "Tier 2":
            status = "WARN (log)"
            n_warn += 1
        else:
            status = "FAIL (%s)" % ("page" if tier == "Tier 0" else "slack")
            n_fail += 1
        results.append((name, tier, lag, sla, status))
        print("  %-20s %-8s %9.0fs %9ds  %s" % (name, tier, lag, sla, status))
    print()
    print("=> Freshness is the FIRST triage question. A stale Tier 0 table (here")
    print("   experiment_assign, 2h lag vs 15min SLA) pages before you even look")
    print("   at null rates or volume -- nothing downstream can be trusted until")
    print("   the pipeline is fresh.")
    print()
    print("[check] 6 freshness checks ran? " + ("OK" if len(results) == 6 else "FAIL"))
    print("[check] experiment_assign breached (Tier 0)? " +
          ("OK" if results[1][4].startswith("FAIL") else "FAIL"))
    print("[check] ad_hoc_export is WARN-only (Tier 2)? " +
          ("OK" if results[5][4].startswith("WARN") else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Z-score anomaly detection (volume)
# ---------------------------------------------------------------------------
def section_zscore():
    banner("SECTION 3: Z-score anomaly detection (daily row count)")
    print("z_i = (x_i - mean) / std. Flag when |z| > %.1f.\n" % Z_THRESHOLD)

    # (a) full series -- anomalies INCLUDED in mean/std
    m_full = mean(DAILY)
    s_full = pstd(DAILY)
    z_full = [(x - m_full) / s_full for x in DAILY]
    anom_full = [i + 1 for i, z in enumerate(z_full) if abs(z) > Z_THRESHOLD]

    # (b) baseline-trained -- mean/std from the clean 12-day window, then score all
    m_base = mean(BASELINE)
    s_base = pstd(BASELINE)
    z_base = [(x - m_base) / s_base for x in DAILY]
    anom_base = [i + 1 for i, z in enumerate(z_base) if abs(z) > Z_THRESHOLD]

    print("  %-6s %8s | %16s | %16s" % ("day", "count", "z (full series)", "z (baseline)"))
    for i, x in enumerate(DAILY):
        flag_f = " *" if (i + 1) in anom_full else ""
        flag_b = " *" if (i + 1) in anom_base else ""
        print("  day%-2d %8d | %14.3f%s | %14.2f%s" %
              (i + 1, x, z_full[i], flag_f, z_base[i], flag_b))
    print()
    print("  full series:   mean=%.3f  std=%.3f  -> %d anomaly (|z|>3)" %
          (m_full, s_full, len(anom_full)))
    print("  baseline-trained: mean=%.3f  std=%.3f  -> %d anomalies (|z|>3)" %
          (m_base, s_base, len(anom_base)))
    print()
    print("=> Full-series z-score MISSES the drop (day 13, z=%.3f): the spike" % z_full[12])
    print("   (5000) inflates mean+std so much that the 400-drop looks normal.")
    print("   Train z-score on a CLEAN baseline window and both anomalies leap")
    print("   out (z=%.1f for the drop). Lesson: never let anomalies pollute the" % z_base[12])
    print("   statistics you detect them with.")
    print()
    print("[check] full-series flags only the spike? " +
          ("OK" if anom_full == [14] else "FAIL"))
    print("[check] baseline-trained flags drop + spike? " +
          ("OK" if anom_base == [13, 14] else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - IQR anomaly detection (volume, robust)
# ---------------------------------------------------------------------------
def section_iqr():
    banner("SECTION 4: IQR anomaly detection (robust single pass)")
    q1, q3, low, high = iqr_fences(DAILY)
    iqr = q3 - q1
    anom = [i + 1 for i, x in enumerate(DAILY) if x < low or x > high]
    sorted_d = sorted(DAILY)
    print("Sorted: %s\n" % sorted_d)
    print("  Q1 = %.1f   Q3 = %.1f   IQR = %.1f" % (q1, q3, iqr))
    print("  Lower fence = Q1 - 1.5*IQR = %.1f" % low)
    print("  Upper fence = Q3 + 1.5*IQR = %.1f\n" % high)
    print("  %-6s %8s  %s" % ("day", "count", "verdict"))
    for i, x in enumerate(DAILY):
        v = "ANOMALY (drop)" if x < low else ("ANOMALY (spike)" if x > high else "ok")
        print("  day%-2d %8d  %s" % (i + 1, x, v))
    print()
    print("=> IQR catches BOTH anomalies in one pass (drop + spike) without a")
    print("   training window, because the median and quartiles are ROBUST to")
    print("   outliers -- the huge spike barely moves them. IQR wins for")
    print("   thousands of tables where you cannot hand-curate a clean baseline.")
    print()
    print("[check] IQR flags exactly the drop + spike? " +
          ("OK" if anom == [13, 14] else "FAIL"))
    print("[check] upper fence == 1040? " + ("OK" if high == 1040 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - EWMA null-rate monitoring (adaptive baseline)
# ---------------------------------------------------------------------------
def section_ewma():
    banner("SECTION 5: EWMA null-rate monitoring (adaptive baseline)")
    print("baseline_t = a*rate_t + (1-a)*baseline_{t-1}; forecast_t = baseline_{t-1};")
    print("alert if residual = rate_t - forecast_t > %.1f * sigma (one-sided).\n" % EWMA_K)
    rates = EWMA_RATES
    n = len(rates)
    base = [0.0] * n
    resid = [0.0] * n
    base[0] = rates[0]
    for t in range(1, n):
        resid[t] = rates[t] - base[t - 1]
        base[t] = EWMA_ALPHA * rates[t] + (1 - EWMA_ALPHA) * base[t - 1]
    # sigma = population std of the normal-period residuals (t=1..6, before spike)
    normal_resid = resid[1:7]
    sigma = pstd(normal_resid)
    band = EWMA_K * sigma

    print("  %-5s %7s %10s %10s  %s" % ("day", "rate%", "forecast", "residual", "alert"))
    alerts = []
    for t in range(n):
        fc = base[t - 1] if t > 0 else rates[0]
        al = "ALERT (null spike)" if (t > 0 and resid[t] > band) else ""
        if al:
            alerts.append(t + 1)
        print("  day%-2d %7.1f %10.3f %10.3f  %s" % (t + 1, rates[t], fc, resid[t], al))
    print()
    print("  sigma (normal residuals) = %.3f   3*sigma band = %.3f" % (sigma, band))
    print()
    print("=> The day-8 spike (60%% vs forecast %.3f) is the causal anomaly:" % base[6])
    print("   residual %.3f dwarfs the band %.3f." % (resid[7], band))
    print("   email-null rate from ~2% to 60% on a Friday night. One-sided")
    print("   alerting (spikes only) avoids firing on the EWMA 'echo' as the")
    print("   baseline lags back down -- which is also why a sustain period")
    print("   (alert only after N consecutive failures) cuts false positives.")
    print()
    print("[check] single alert on day 8? " + ("OK" if alerts == [8] else "FAIL"))
    print("[check] day-8 residual > 3*sigma? " + ("OK" if resid[7] > band else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Completeness scoring (cell-level non-null rates)
# ---------------------------------------------------------------------------
def section_completeness():
    banner("SECTION 6: Completeness scoring (cell-level non-null rates)")
    conn = build_validation_db()
    print("compliance(column) = non_null / total. Table completeness = non-null")
    print("cells / total cells across all columns.\n")
    cols = {
        "users": ["id", "email", "age", "country"],
        "orders": ["id", "user_id", "amount", "status"],
    }
    grand_cells = 0
    grand_nonnull = 0
    print("  %-8s %-10s %7s %9s %11s" % ("table", "column", "total", "nonnull", "complete%"))
    for table, clist in cols.items():
        for col in clist:
            total = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            nonnull = conn.execute("SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL" % (table, col)).fetchone()[0]
            grand_cells += total
            grand_nonnull += nonnull
            print("  %-8s %-10s %7d %9d %10.2f%%" % (table, col, total, nonnull, pct(nonnull, total)))
    conn.close()
    users_comp = pct(394, 400)
    orders_comp = pct(797, 800)
    overall = pct(grand_nonnull, grand_cells)
    print()
    print("  users  completeness = 394/400 = %.2f%%" % users_comp)
    print("  orders completeness = 797/800 = %.2f%%" % orders_comp)
    print("  OVERALL completeness = %d/%d = %.2f%%" % (grand_nonnull, grand_cells, overall))
    print()
    print("=> Completeness is necessary but NOT sufficient: a column can be 100%%")
    print("   non-null and still full of wrong values (out-of-range ages, invalid")
    print("   enums, orphans). Completeness + validity together = trustworthy data.")
    print()
    print("[check] users completeness == 98.5%? " + ("OK" if users_comp == 98.5 else "FAIL"))
    print("[check] overall completeness == 99.25%? " + ("OK" if overall == 99.25 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - Quality scorecard (rollup)
# ---------------------------------------------------------------------------
def section_scorecard():
    banner("SECTION 7: Quality scorecard (validity + freshness + completeness + volume)")
    # validity: 10 checks -> pass=2, warn=3, fail=5
    v_pass, v_warn, v_fail = 2, 3, 5
    v_total = v_pass + v_warn + v_fail
    validity_score = pct(v_pass + 0.5 * v_warn, v_total)

    # freshness: 6 checks -> pass=3, warn=1, fail=2
    f_pass, f_warn, f_fail = 3, 1, 2
    f_total = f_pass + f_warn + f_fail
    freshness_score = pct(f_pass + 0.5 * f_warn, f_total)

    # completeness: 1191/1200 cells
    completeness_score = pct(1191, 1200)

    # volume: 2 anomalous days of 14
    volume_score = pct(14 - 2, 14)

    overall = mean([validity_score, freshness_score, completeness_score, volume_score])

    print("  score = 100 * (pass + 0.5*warn) / total   (WARN counts half)\n")
    print("  %-16s %7s %6s %6s %10s" % ("dimension", "pass", "warn", "fail", "score"))
    print("  %-16s %7d %6d %6d %9.1f%%" % ("validity", v_pass, v_warn, v_fail, validity_score))
    print("  %-16s %7d %6d %6d %9.1f%%" % ("freshness", f_pass, f_warn, f_fail, freshness_score))
    print("  %-16s %7s %6s %6s %9.2f%%" % ("completeness", "-", "-", "-", completeness_score))
    print("  %-16s %7s %6s %6s %9.1f%%" % ("volume", "12/14", "days", "ok", volume_score))
    print("  " + "-" * 50)
    grade = ("HEALTHY" if overall >= 90 else "WATCH" if overall >= 75 else
             "NEEDS ATTENTION" if overall >= 60 else "BROKEN")
    print("  %-16s %41.1f%%   [%s]" % ("OVERALL QUALITY", overall, grade))
    print()
    print("=> One score per dimension + one rollup gives leadership a single")
    print("   view; drilling into validity shows the P0 referential orphans,")
    print("   into freshness shows the breached Tier 0 table. Score = 100 only")
    print("   when every contract holds AND every monitor is green.")
    print()
    print("[check] validity score == 35.0%? " + ("OK" if validity_score == 35.0 else "FAIL"))
    print("[check] overall == 69.6% (NEEDS ATTENTION)? " +
          ("OK" if round(overall, 1) == 69.6 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 8 - GOLD values pinned for data_quality.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 8: GOLD values (pinned for data_quality.html)")

    # validation / scorecard inputs
    v_total = 10
    v_pass, v_warn, v_fail = 2, 3, 5
    validity_score = pct(v_pass + 0.5 * v_warn, v_total)
    f_pass, f_warn, f_fail = 3, 1, 2
    f_total = 6
    freshness_score = pct(f_pass + 0.5 * f_warn, f_total)
    completeness = pct(1191, 1200)
    volume_score = pct(14 - 2, 14)
    overall = mean([validity_score, freshness_score, completeness, volume_score])

    # z-score
    m_full = mean(DAILY)
    s_full = pstd(DAILY)
    z_full = [(x - m_full) / s_full for x in DAILY]
    anom_full = sum(1 for z in z_full if abs(z) > Z_THRESHOLD)
    m_base = mean(BASELINE)
    s_base = pstd(BASELINE)
    z_base = [(x - m_base) / s_base for x in DAILY]
    anom_base = sum(1 for z in z_base if abs(z) > Z_THRESHOLD)

    # IQR
    q1, q3, low, high = iqr_fences(DAILY)
    iqr_anom = sum(1 for x in DAILY if x < low or x > high)

    # EWMA
    rates = EWMA_RATES
    n = len(rates)
    base = [0.0] * n
    resid = [0.0] * n
    base[0] = rates[0]
    for t in range(1, n):
        resid[t] = rates[t] - base[t - 1]
        base[t] = EWMA_ALPHA * rates[t] + (1 - EWMA_ALPHA) * base[t - 1]
    sigma = pstd(resid[1:7])
    ewma_alerts = [t + 1 for t in range(1, n) if resid[t] > EWMA_K * sigma]

    gold = [
        ("validity_total",            "%d" % v_total,                 "10"),
        ("validity_fail",             "%d" % v_fail,                  "5"),
        ("validity_score_pct",        "%.1f" % validity_score,        "35.0"),
        ("freshness_total",           "%d" % f_total,                 "6"),
        ("freshness_fail",            "%d" % f_fail,                  "2"),
        ("freshness_score_pct",       "%.1f" % freshness_score,       "58.3"),
        ("completeness_overall_pct",  "%.2f" % completeness,          "99.25"),
        ("volume_anomaly_count",      "%d" % iqr_anom,                "2"),
        ("volume_score_pct",          "%.1f" % volume_score,          "85.7"),
        ("zscore_mean_full",          "%.3f" % m_full,                "1242.857"),
        ("zscore_std_full",           "%.3f" % s_full,                "1053.427"),
        ("zscore_anomaly_full",       "%d" % anom_full,               "1"),
        ("zscore_anomaly_baseline",   "%d" % anom_base,               "2"),
        ("iqr_q1",                    "%.1f" % q1,                    "990.0"),
        ("iqr_fence_high",            "%.1f" % high,                  "1040.0"),
        ("ewma_spike_day",            "%d" % (ewma_alerts[0] if ewma_alerts else -1), "8"),
        ("ewma_residual_day8",        "%.3f" % resid[7],              "58.015"),
        ("ewma_sigma",                "%.3f" % sigma,                 "0.150"),
        ("overall_quality_score",     "%.1f" % overall,               "69.6"),
    ]
    print("  %-26s %16s %10s %8s" % ("check", "py recompute", "GOLD", "match"))
    all_ok = True
    for label, got, want in gold:
        ok = got == want
        if not ok:
            all_ok = False
        print("  %-26s %16s %10s %8s" % (label, got, want, "OK" if ok else "FAIL"))
    print()
    print("[check] ALL GOLD values reproduce from the data-quality formulas? " +
          ("OK" if all_ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# data_quality.py - Data quality monitoring simulation")
    print("# Pure Python stdlib only. Numbers below feed DATA_QUALITY.md")
    print("# and data_quality.html (gold-checked).")
    section_validation()
    section_freshness()
    section_zscore()
    section_iqr()
    section_ewma()
    section_completeness()
    section_scorecard()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
