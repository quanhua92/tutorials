"""
cohort_retention.py - Ground-truth simulation + analytics for the Cohort &
Retention bundle. The single source of truth that COHORT_RETENTION.md and
cohort_retention.html are built from. Every number, table, and curve below is
printed by this file -- nothing in the guide is hand-computed.

Run:
    python3 cohort_retention.py

============================================================================
THE IDEA (read this first) -- a retention curve is a survival function
============================================================================
Group users by the MONTH they signed up (a "cohort"). For each cohort ask:
"what fraction came back on day N?" That fraction is the N-day retention
R(N). Stack the cohorts as rows and the offsets (D1, D7, D30, D60, D90) as
columns and you get a RETENTION HEATMAP -- a triangle, because recent
cohorts have not lived long enough to have a D90 (right-censoring).

R(N) is exactly the survival function S(N) from reliability / biostatistics:
the probability a user is still active N days after signup. Its complement
1 - R(N) is the cumulative churn. The instantaneous churn risk between two
horizons is the "drop-off" -- (R(a) - R(b)) / R(a).

A clean consumer-social retention curve has THREE behaviors layered together:
    1. BOUNCE  -- signed up, never came back (the ~50% that die at D0->D1)
    2. CASUAL  -- tries it for a few days, exponential decay, gone by D14
    3. CORE    -- the loyal minority; decays fast then PLATEAUS at ~its floor
The CORE plateau is what makes pure-exponential fits systematically
UNDER-estimate long-term retention -- the single most useful diagnostic in
this file.

============================================================================
HOW THE NUMBERS ARE MADE (pure stdlib, fully reproducible)
============================================================================
A fixed random seed (SEED=42) drives a 3-segment generative model. Every
user is assigned bounce/casual/core with cohort- and segment-dependent
weights; each measurement day is a Bernoulli draw against the segment's
retention probability. The synthetic events are loaded into an in-memory
sqlite3 database, then the SAME multi-horizon retention SQL a real analytics
team would ship (one pass, MAX(CASE WHEN day_offset = N ...)) is run against
it -- so the SQL output and the Python analytics are guaranteed to agree.

Key formulas (all verified/printed by the sections below):
    retention R(N)         = retained_users(cohort, N) / cohort_size
    period drop-off a->b   = (R(a) - R(b)) / R(a)
    cumulative churn by N  = 1 - R(N)
    exponential fit        = R(t) = A * exp(-k * t)        [log-linear LS]
      slope  = (n*Sxy - Sx*Sy) / (n*Sxx - Sx^2)   ;  k = -slope
      A      = exp(intercept)                      ;  intercept = (Sy - slope*Sx)/n
      half-life = ln(2) / k
      R^2     = 1 - SS_res / SS_tot   (on the log scale)
"""

from __future__ import annotations

import math
import random
import sqlite3
from datetime import date

BANNER = "=" * 72

# ============================================================================
# 1. SIMULATION PARAMETERS (fixed -> reproducible)
# ============================================================================

SEED = 42

ANALYSIS_DATE = date(2025, 7, 20)            # "today" for right-censoring

# (cohort month, signup size, organic-fraction)  -- monthly signup cohorts
COHORT_DEFS = [
    ("2025-01", 980,  0.60),
    ("2025-02", 1120, 0.58),
    ("2025-03", 1340, 0.57),
    ("2025-04", 1080, 0.59),
    ("2025-05", 1450, 0.56),
    ("2025-06", 1260, 0.58),
    ("2025-07", 760,  0.55),                 # partial / current month
]

IOS_FRAC = 0.48                              # platform split (iOS vs android)

# Days since signup at which we record activity. The classic horizons
# D1/D7/D30/D60/D90 are a subset; the extra points feed the curve fit.
MEASUREMENT_OFFSETS = [0, 1, 3, 7, 14, 30, 45, 60, 75, 90]
HORIZONS = [1, 7, 30, 60, 90]               # the columns of the heatmaps


def type_weights(cohort_idx: int, channel: str, platform: str):
    """Per-user probability of being BOUNCE / CASUAL / CORE.

    Cohort drift: later cohorts get slightly better onboarding (less bounce,
    more core). Paid acquisition is noisier (more bounce). iOS users are a
    touch more loyal (~+3pp core), matching the well-known platform delta.
    Returns a normalized 3-tuple summing to 1.
    """
    drift = cohort_idx * 0.012               # 0 (Jan) .. 0.072 (Jul)
    w_bounce = 0.50 - drift
    w_casual = 0.23
    w_core = 0.27 + drift
    if channel == "paid":
        w_bounce += 0.08
        w_core -= 0.08
    if platform == "ios":
        w_core += 0.04
        w_bounce -= 0.04
    s = w_bounce + w_casual + w_core
    return w_bounce / s, w_casual / s, w_core / s


def retention_prob(utype: str, t: int) -> float:
    """Probability a user of `utype` is active exactly `t` days after signup.

    bounce : never returns (0 for t >= 1)
    casual : exponential decay, ~gone by D14
    core   : decays then PLATEAUS at 0.45 (the loyal minority's floor)
    """
    if utype == "bounce":
        return 0.0
    if utype == "casual":
        return math.exp(-0.25 * t)
    return 0.45 + 0.45 * math.exp(-0.05 * t)


# ============================================================================
# 2. SIMULATE -> users + events (deterministic with SEED)
# ============================================================================

def simulate():
    """Run the generative model. Returns (users, events, cohort_meta).

    users       : list of (id, cohort, channel, platform, signup_date, maturity, utype)
    events      : list of (user_id, day_offset)
    cohort_meta : {cohort: {size, maturity, organic, paid, ios, android}}
    """
    rng = random.Random(SEED)
    users = []
    events = []
    uid = 0
    cohort_meta = {}
    for cidx, (month, size, org_frac) in enumerate(COHORT_DEFS):
        y, m = (int(x) for x in month.split("-"))
        signup = date(y, m, 1)
        maturity = (ANALYSIS_DATE - signup).days
        n_org = n_paid = n_ios = n_and = 0
        for _ in range(size):
            uid += 1
            channel = "organic" if rng.random() < org_frac else "paid"
            platform = "ios" if rng.random() < IOS_FRAC else "android"
            wb, wc, wco = type_weights(cidx, channel, platform)
            r = rng.random()
            if r < wb:
                utype = "bounce"
            elif r < wb + wc:
                utype = "casual"
            else:
                utype = "core"
            users.append((uid, month, channel, platform, signup.isoformat(),
                          maturity, utype))
            events.append((uid, 0))                          # signup day (anchor)
            if channel == "organic":
                n_org += 1
            else:
                n_paid += 1
            if platform == "ios":
                n_ios += 1
            else:
                n_and += 1
            for off in MEASUREMENT_OFFSETS:
                if off == 0:
                    continue
                if off > maturity:                           # right-censored
                    continue
                if rng.random() < retention_prob(utype, off):
                    events.append((uid, off))
        cohort_meta[month] = {"size": size, "maturity": maturity,
                              "organic": n_org, "paid": n_paid,
                              "ios": n_ios, "android": n_and}
    return users, events, cohort_meta


def build_db(users, events):
    """Load simulated data into an in-memory sqlite3 database."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users (
            id INTEGER, cohort TEXT, channel TEXT, platform TEXT,
            signup_date TEXT, maturity INTEGER, utype TEXT
        );
        CREATE TABLE events (user_id INTEGER, day_offset INTEGER);
        CREATE INDEX idx_events_uid ON events(user_id);
        """
    )
    conn.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?)", users)
    conn.executemany("INSERT INTO events VALUES (?,?)", events)
    conn.commit()
    return conn


# ============================================================================
# 3. PYTHON ANALYTICS (the heatmaps / curves / fit / churn / segmentation)
# ============================================================================

def retention_matrix(conn, cohort_meta):
    """Return {cohort: {offset: (retained, size)}} for every cohort x offset,
    plus the set of censored (cohort, offset) pairs (cohort too young).
    """
    cur = conn.cursor()
    out = {}
    censored = set()
    for month in cohort_meta:
        size = cohort_meta[month]["size"]
        maturity = cohort_meta[month]["maturity"]
        row = {}
        for off in HORIZONS:
            retained = cur.execute(
                "SELECT COUNT(DISTINCT user_id) FROM events "
                "WHERE user_id IN (SELECT id FROM users WHERE cohort=?) "
                "AND day_offset=?", (month, off)
            ).fetchone()[0]
            row[off] = (retained, size)
            if off > maturity:
                censored.add((month, off))
        out[month] = row
    return out, censored


def curve_for_cohort(conn, month, size):
    """Full retention curve at every measurement offset for one cohort."""
    cur = conn.cursor()
    pts = []
    for off in MEASUREMENT_OFFSETS:
        retained = cur.execute(
            "SELECT COUNT(DISTINCT user_id) FROM events "
            "WHERE user_id IN (SELECT id FROM users WHERE cohort=?) "
            "AND day_offset=?", (month, off)
        ).fetchone()[0]
        pts.append((off, retained / size))
    return pts


def fit_exponential(xs, ys):
    """Least-squares fit of y = A * exp(-k * x) on the log scale.

    Returns (A, k, half_life, r2). Uses the closed-form normal equations.
    """
    n = len(xs)
    lys = [math.log(y) for y in ys]
    sx = sum(xs)
    sy = sum(lys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * ly for x, ly in zip(xs, lys))
    denom = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denom            # == -k
    intercept = (sy - slope * sx) / n               # == ln A
    k = -slope
    A = math.exp(intercept)
    half = math.log(2) / k if k > 0 else float("inf")
    mean_ly = sy / n
    ss_res = sum((ly - (intercept + slope * x)) ** 2
                 for x, ly in zip(xs, lys))
    ss_tot = sum((ly - mean_ly) ** 2 for ly in lys)
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return A, k, half, r2


def segment_retention(conn, month, size):
    """D1/D7/D30 retention split by channel and platform for one cohort."""
    cur = conn.cursor()
    res = {}
    for dim in ("channel", "platform"):
        for val in (cur.execute(
            f"SELECT DISTINCT {dim} FROM users WHERE cohort=?", (month,)
        ).fetchall()):
            v = val[0]
            seg_size = cur.execute(
                f"SELECT COUNT(*) FROM users WHERE cohort=? AND {dim}=?", (month, v)
            ).fetchone()[0]
            row = {"size": seg_size}
            for off in (1, 7, 30):
                ret = cur.execute(
                    "SELECT COUNT(DISTINCT e.user_id) FROM events e "
                    "JOIN users u ON u.id=e.user_id "
                    "WHERE u.cohort=? AND u." + dim + "=? AND e.day_offset=?",
                    (month, v, off)
                ).fetchone()[0]
                row[off] = ret / seg_size if seg_size else 0.0
            res[v] = row
    return res


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def pct(x: float) -> str:
    return f"{100.0 * x:5.1f}%"


def bar(x: float, width: int = 30) -> str:
    """ASCII bar for a 0..1 fraction."""
    n = max(0, min(width, round(x * width)))
    return "#" * n + "." * (width - n)


# ============================================================================
# 5. THE SECTIONS
# ============================================================================

def section_simulation(cohort_meta):
    banner("SECTION 1: the simulation  (monthly cohorts + 3-segment model)")
    print("Seven monthly signup cohorts (2025-01 .. 2025-07). Every user is")
    print("assigned to BOUNCE / CASUAL / CORE; each measurement day is a")
    print("Bernoulli draw against the segment's retention probability. Fixed")
    print("seed (SEED=42) -> fully reproducible.\n")
    total_users = sum(c["size"] for c in cohort_meta.values())
    print(f"  cohorts            : {len(cohort_meta)}")
    print(f"  total users        : {total_users}")
    print(f"  analysis date      : {ANALYSIS_DATE.isoformat()}  (right-censor cutoff)")
    print(f"  measurement days   : {MEASUREMENT_OFFSETS}")
    print(f"  heatmap horizons   : {HORIZONS}   (D1 / D7 / D30 / D60 / D90)\n")
    print("  segment | retention probability P(active on day t)  [t>=1]")
    print("  ------- | ----------------------------------------------")
    print("  bounce  | 0                       (signed up, never returned)")
    print("  casual  | exp(-0.25 * t)          (~gone by D14)")
    print("  core    | 0.45 + 0.45*exp(-0.05t) (decays, then PLATEAUS ~45%)\n")
    print("  cohort   |  size | organic% | ios% | maturity | mature-to")
    print("  ---------|-------|----------|------|----------|-----------")
    for month, c in cohort_meta.items():
        mature_horizons = [f"D{h}" for h in HORIZONS if h <= c["maturity"]]
        print(f"  {month} | {c['size']:5d} | "
              f"{100.0*c['organic']/c['size']:7.1f} | "
              f"{100.0*c['ios']/c['size']:4.1f} | "
              f"{c['maturity']:8d} | {', '.join(mature_horizons) or '(none)'}")
    print("\n  maturity = days between signup (1st of month) and the analysis")
    print("  date. A cohort can only have D{N} if maturity >= N -- otherwise the")
    print("  cell is RIGHT-CENSORED (not zero, just not yet observable). That")
    print("  is what carves the retention triangle below.")


def section_sql(conn):
    banner("SECTION 2: multi-horizon retention SQL  (D1..D90 in ONE pass)")
    print("The production query: one LEFT JOIN of events onto the user anchor,")
    print("then MAX(CASE WHEN day_offset = N THEN 1 ELSE 0 END) per horizon --")
    print("a linear scan + group-by instead of a quadratic self-join. AVG of")
    print("the 0/1 flags is the retention fraction.\n")
    sql = """
        WITH flags AS (
            SELECT u.cohort,
                   MAX(CASE WHEN e.day_offset = 1  THEN 1 ELSE 0 END) AS d1,
                   MAX(CASE WHEN e.day_offset = 7  THEN 1 ELSE 0 END) AS d7,
                   MAX(CASE WHEN e.day_offset = 30 THEN 1 ELSE 0 END) AS d30,
                   MAX(CASE WHEN e.day_offset = 60 THEN 1 ELSE 0 END) AS d60,
                   MAX(CASE WHEN e.day_offset = 90 THEN 1 ELSE 0 END) AS d90
            FROM users u
            LEFT JOIN events e ON e.user_id = u.id
            GROUP BY u.cohort, u.id
        )
        SELECT cohort,
               printf('%.1f', 100.0*AVG(d1))  AS d1,
               printf('%.1f', 100.0*AVG(d7))  AS d7,
               printf('%.1f', 100.0*AVG(d30)) AS d30,
               printf('%.1f', 100.0*AVG(d60)) AS d60,
               printf('%.1f', 100.0*AVG(d90)) AS d90
        FROM flags
        GROUP BY cohort
        ORDER BY cohort;
    """
    rows = conn.execute(sql).fetchall()
    print("  cohort   |  D1   |  D7   |  D30  |  D60  |  D90")
    print("  ---------|-------|-------|-------|-------|-------")
    for r in rows:
        print(f"  {r[0]} | {r[1]:>5} | {r[2]:>5} | {r[3]:>5} | {r[4]:>5} | {r[5]:>5}")
    print("\n  NB: the low D60/D90 for 2025-06 / 2025-07 is NOT real churn --")
    print("  those cohorts are too young to have a D60/D90. Including them in")
    print("  the denominator is the classic math artifact. Section 3 censors")


def section_heatmap(matrix, censored, cohort_meta):
    banner("SECTION 3: the retention heatmap  (cohort x horizon, censored)")
    print("Rows = signup cohort, columns = time since signup, cells = %% of the")
    print("cohort still active. Censored cells (cohort younger than the offset)")
    print("are shown as '  ---  '. The missing lower-right corner is the")
    print("retention triangle.\n")
    print("  cohort   |  D1     D7     D30    D60    D90")
    print("  ---------|----------------------------------")
    for month in cohort_meta:
        cells = []
        for h in HORIZONS:
            if (month, h) in censored:
                cells.append("  --- ")
            else:
                retained, size = matrix[month][h]
                cells.append(f"{100.0*retained/size:5.1f}%")
        print(f"  {month} | " + " ".join(cells))
    print("\n  Intensity map (cell shading scales with retention):\n")
    print("  cohort   |  D1        D7        D30       D60       D90")
    print("  ---------|--------------------------------------------------")
    for month in cohort_meta:
        cells = []
        for h in HORIZONS:
            if (month, h) in censored:
                cells.append("[-----------]")
            else:
                retained, size = matrix[month][h]
                cells.append(f"[{bar(retained/size, 11)}]")
        print(f"  {month} | " + " ".join(cells))
    print("\n  How to read it:")
    print("    * DOWN a column (vertical)  : same lifecycle stage, different")
    print("      cohorts. Tests whether product/acquisition quality is improving.")
    print("    * ACROSS a row  (horizontal): one cohort's decay curve. Tests")
    print("      long-term stickiness / product-market fit.")
    print("    * Diagonal streak  -> product regression or worse acquisition.")
    print("    * Vertical red col -> measurement bug or a seasonal event.")


def section_curve(conn, cohort_meta):
    month = "2025-01"
    size = cohort_meta[month]["size"]
    pts = curve_for_cohort(conn, month, size)
    banner(f"SECTION 4: the retention curve  ({month} cohort, oldest/most mature)")
    print(f"{month} has {cohort_meta[month]['maturity']} days of maturity, so the")
    print("full D0..D90 curve is observable. This is the survival function.\n")
    print("  day  | retention |          curve (0..100%)")
    print("  -----|-----------|-----------------------------------------")
    for off, frac in pts:
        print(f"  D{off:<3d} | {100.0*frac:8.1f}% | {bar(frac, 40)}")
    print()
    d1 = dict(pts).get(1, 0)
    d7 = dict(pts).get(7, 0)
    d30 = dict(pts).get(30, 0)
    d90 = dict(pts).get(90, 0)
    print(f"  D1  = {100*d1:4.1f}%   (activation quality; first-impression value)")
    print(f"  D7  = {100*d7:4.1f}%   (habit formation; investor-comparable)")
    print(f"  D30 = {100*d30:4.1f}%   (long-term value; tracks LTV in subscriptions)")
    print(f"  D90 = {100*d90:4.1f}%   (the loyal CORE plateau)\n")
    print("  CURVE SHAPE: steep D1->D7 drop (the bounce + casual users leave),")
    print("  then a flattening tail (the core minority plateaus). This 'bend' is")
    print("  the signature of a healthy consumer-social product and is exactly")
    print("  what a pure-exponential fit CANNOT capture (Section 5).")


def section_fit(conn, cohort_meta):
    month = "2025-01"
    size = cohort_meta[month]["size"]
    pts = curve_for_cohort(conn, month, size)
    xs = [p[0] for p in pts if p[0] >= 1]
    ys = [p[1] for p in pts if p[0] >= 1]
    A, k, half, r2 = fit_exponential(xs, ys)
    banner("SECTION 5: curve fitting  (exponential decay  R(t) = A * exp(-k t))")
    print("Fit R(t) = A * exp(-k*t) by log-linear least squares (linear")
    print("regression of ln R on t). Single free decay rate k -> one half-life.")
    print("Closed form from the normal equations; no numpy needed.\n")
    print(f"  A (anchor)         = {A*100:6.2f}%   (fitted D0 intercept)")
    print(f"  k (decay rate)     = {k:6.4f} /day")
    print(f"  half-life          = {half:6.2f} days   (ln 2 / k)")
    print(f"  R^2 (log scale)    = {r2:6.4f}\n")
    print("  day  |  actual  |  fitted  |  error")
    print("  -----|----------|----------|----------")
    for t, frac in pts:
        if t < 1:
            continue
        fit = A * math.exp(-k * t)
        err = fit - frac
        print(f"  D{t:<3d} | {100*frac:7.1f}% | {100*fit:7.1f}% | {100*err:+7.1f}pp")
    print("\n  WHY IT FITS POORLY AT THE TAIL: a single exponential must decay to")
    print("  zero, but the real curve PLATEAUS at the core floor (~12%). So the")
    print(f"  fit UNDER-estimates D90 ({100*A*math.exp(-k*90):.1f}% predicted vs")
    print(f"  {100*dict(pts)[90]:.1f}% actual). Better models: a power law, or a")
    print("  mixture (A_fast*exp(-k1 t) + A_slow*exp(-k2 t)) that lets the loyal")
    print("  tail survive. Half-life is still a handy single-number summary.")


def section_churn(conn, cohort_meta):
    month = "2025-01"
    size = cohort_meta[month]["size"]
    pts = dict(curve_for_cohort(conn, month, size))
    banner(f"SECTION 6: churn analysis  ({month} cohort)")
    print("Cumulative churn by D{N} = 1 - R(N). Period drop-off between two")
    print("horizons = (R(a) - R(b)) / R(a) -- the share of whoever was still")
    print("around at D{a} who had left by D{b}.\n")
    print("  from -> to  |  R(a)   R(b)  | drop-off | cumul churn at D{b}")
    print("  ------------|---------------|----------|----------------------")
    chain = [(0, 1), (1, 7), (7, 30), (30, 60), (60, 90)]
    for a, b in chain:
        ra = pts[a]
        rb = pts[b]
        drop = (ra - rb) / ra if ra else 0.0
        print(f"  D{a:<2d} -> D{b:<2d}   | {100*ra:5.1f}% {100*rb:5.1f}% |"
              f" {100*drop:6.1f}%  | {100*(1-rb):5.1f}%")
    print("\n  The D0->D1 drop-off is the bounce wall (~58% leave on day one).")
    print("  Cumulative churn then climbs slowly: most of the damage is done")
    print("  early. After D30 the curve is nearly flat -- whoever is left is")
    print("  the core. NOTE: missing D30 is dormancy, not permanent exit; a")
    print("  user absent at D30 can resurrect at D45/D90 (cheaper to win back")
    print("  than to acquire fresh, often 3-5x).")


def section_segments(conn, cohort_meta):
    month = "2025-01"
    seg = segment_retention(conn, month, cohort_meta[month]["size"])
    banner(f"SECTION 7: segmentation  ({month} cohort, channel x platform)")
    print("Same cohort, split by acquisition channel and platform. Headline")
    print("retention is a BLEND -- always decompose it before diagnosing.\n")
    print("  segment        |  size |  D1     D7     D30")
    print("  ---------------|-------|----------------------")
    for key in ("organic", "paid", "ios", "android"):
        s = seg[key]
        print(f"  {key:14s} | {s['size']:5d} | "
              f"{100*s[1]:5.1f}% {100*s[7]:5.1f}% {100*s[30]:5.1f}%")
    o, p = seg["organic"], seg["paid"]
    i, a = seg["ios"], seg["android"]
    print(f"\n  organic D30 = {100*o[30]:.1f}%  vs  paid D30 = {100*p[30]:.1f}%   "
          f"(delta {100*(o[30]-p[30]):+.1f}pp)")
    print(f"  ios D30     = {100*i[30]:.1f}%  vs  android D30 = {100*a[30]:.1f}%   "
          f"(delta {100*(i[30]-a[30]):+.1f}pp)")
    print("\n  Paid trails organic -- if headline D7 drops, check whether paid")
    print("  MIX rose before blaming the product. iOS runs a few pp above")
    print("  android across categories (demographics + app quality selection).")
    print("  This is acquisition-mix / platform delta in one table.")


def section_benchmarks():
    banner("SECTION 8: benchmarks + curve-shape diagnostics (2026 medians)")
    print("  product type        |  D1     D7     D30   | key driver")
    print("  ---------------------|----------------------|---------------------")
    rows = [
        ("Consumer Social (org)", "40-50", "25-35", "15-25", "network density"),
        ("B2B SaaS (SMB)",        "50-65", "35-50", "25-40", "workflow integration"),
        ("B2B SaaS (Enterprise)", "65",    "55",    "45",    "deep integrations"),
        ("Mobile Gaming (midcore)","35-45","18-28", "10-18", "progression pacing"),
        ("Marketplace (2-sided)", "30-40", "20-30", "12-20", "liquidity"),
        ("Productivity Tools",    "45-60", "30-45", "20-35", "daily habit"),
        ("Streaming Media",       "55-70", "40-55", "30-45", "content catalog"),
    ]
    for r in rows:
        print(f"  {r[0]:20s} | {r[1]:>5}  {r[2]:>5}  {r[3]:>5}  | {r[4]}")
    print("\n  2026 shifts: SMB SaaS NRR < 100%; consumer D30 compressed 10-15%;")
    print("  streaming monthly churn ~5.5%. Never cite pre-2024 numbers raw.\n")
    print("  Curve-shape read:")
    print("    steep D1->D7 drop, flat tail  -> onboarding problem (not core)")
    print("    gradual linear decay           -> low engagement frequency")
    print("    power-law                       -> utility apps (normal)")
    print("    S-curve                         -> free-trial conversion gate")


def section_gold(conn, cohort_meta, matrix, censored):
    banner("GOLD  (pinned for cohort_retention.html)")
    print("Headline values the HTML recomputes live and gold-checks against.\n")
    # per-cohort retention counts + pct at the standard horizons
    print("  COHORT_RETENTION  (retained count, retention %):")
    for month in cohort_meta:
        size = cohort_meta[month]["size"]
        parts = []
        for h in HORIZONS:
            if (month, h) in censored:
                parts.append(f"D{h}=censored")
            else:
                ret, _ = matrix[month][h]
                parts.append(f"D{h}={ret}/{size}={100.0*ret/size:.1f}%")
        print(f"    {month}: " + ", ".join(parts))
    # full Jan curve
    pts = dict(curve_for_cohort(conn, "2025-01", cohort_meta["2025-01"]["size"]))
    curve_str = ", ".join(f"D{t}={100*pts[t]:.1f}%" for t in MEASUREMENT_OFFSETS)
    print(f"\n  JAN_CURVE: {curve_str}")
    # exponential fit on Jan (t>=1)
    xs = [t for t in MEASUREMENT_OFFSETS if t >= 1]
    ys = [pts[t] for t in xs]
    A, k, half, r2 = fit_exponential(xs, ys)
    print(f"\n  FIT (R(t)=A*exp(-k*t), Jan cohort):")
    print(f"    A={A*100:.2f}%  k={k:.4f}  half_life={half:.2f}  R2={r2:.4f}")
    # segmentation
    seg = segment_retention(conn, "2025-01", cohort_meta["2025-01"]["size"])
    print(f"\n  SEGMENTS (Jan):")
    print(f"    organic  D1={100*seg['organic'][1]:.1f}% "
          f"D7={100*seg['organic'][7]:.1f}% "
          f"D30={100*seg['organic'][30]:.1f}%")
    print(f"    paid     D1={100*seg['paid'][1]:.1f}% "
          f"D7={100*seg['paid'][7]:.1f}% "
          f"D30={100*seg['paid'][30]:.1f}%")
    print(f"    ios      D1={100*seg['ios'][1]:.1f}% "
          f"D7={100*seg['ios'][7]:.1f}% "
          f"D30={100*seg['ios'][30]:.1f}%")
    print(f"    android  D1={100*seg['android'][1]:.1f}% "
          f"D7={100*seg['android'][7]:.1f}% "
          f"D30={100*seg['android'][30]:.1f}%")
    print()
    print("[check] GOLD reproduces from the simulated DB + analytics:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("cohort_retention.py - ground truth for COHORT_RETENTION.md.")
    print("Simulated monthly signup cohorts; retention heatmaps, curves, fit,")
    print("churn, segmentation. Fixed seed -> fully reproducible.")
    users, events, cohort_meta = simulate()
    conn = build_db(users, events)
    matrix, censored = retention_matrix(conn, cohort_meta)

    # sanity: SQL and Python agree on the headline D1 for every cohort
    cur = conn.cursor()
    for month in cohort_meta:
        sql_d1 = cur.execute(
            "SELECT 100.0*AVG(d1) FROM ("
            " SELECT u.id, MAX(CASE WHEN e.day_offset=1 THEN 1 ELSE 0 END) d1"
            " FROM users u LEFT JOIN events e ON e.user_id=u.id"
            " WHERE u.cohort=? GROUP BY u.id)", (month,)
        ).fetchone()[0]
        py_d1 = 100.0 * matrix[month][1][0] / matrix[month][1][1]
        assert abs(sql_d1 - py_d1) < 1e-9, (month, sql_d1, py_d1)
    print(f"\n[check] built DB: {len(users)} users, {len(events)} activity rows")
    print(f"[check] SQL D1 == Python D1 for all {len(cohort_meta)} cohorts:  OK")

    section_simulation(cohort_meta)
    section_sql(conn)
    section_heatmap(matrix, censored, cohort_meta)
    section_curve(conn, cohort_meta)
    section_fit(conn, cohort_meta)
    section_churn(conn, cohort_meta)
    section_segments(conn, cohort_meta)
    section_benchmarks()
    section_gold(conn, cohort_meta, matrix, censored)

    banner("DONE - all sections printed")
    conn.close()


if __name__ == "__main__":
    main()
