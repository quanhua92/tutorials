#!/usr/bin/env python3
"""
north_star_metrics.py - North Star Metric simulation (GROUND TRUTH).

Pure Python stdlib only (sqlite3). Every number printed below feeds
NORTH_STAR_METRICS.md and is recomputed identically in north_star_metrics.html
(gold-checked).

Product: a podcast streaming app.
NSM    : Weekly Active Engaged Listeners (WAEL) = unique users who listened
         >= 30 min in the past 7 days.

Sections:
  1. NSM definition (WAEL; the >=30min engagement threshold)
  2. Metric tree decomposition (NSM -> L1 drivers -> L2 inputs; multiplicative + cohort)
  3. Guardrail & counter-metrics (the four-layer measurement stack)
  4. Leading vs lagging indicators (time-horizon map)
  5. Goodhart's Law simulation (genuine lift vs autoplay gaming)
  6. Metric cadence hierarchy (who owns what, how often)
  7. GOLD values pinned for north_star_metrics.html
"""

import sqlite3

# ---------------------------------------------------------------------------
# source-of-truth constants (mirrored in north_star_metrics.html GOLD)
# ---------------------------------------------------------------------------
PRODUCT = "podcast streaming app"
ENGAGED_THRESHOLD_SEC = 1800   # 30 minutes => "engaged" weekly listener

# weekly-listen-time buckets for the 32,000 weekly active users:
# (lo_sec, hi_sec, count, label)
LISTEN_BUCKETS = [
    (0,    300,  5000, "0-5min"),
    (300,  900,  4800, "5-15min"),
    (900,  1800, 3800, "15-30min"),
    (1800, 3600, 6200, "30-60min"),
    (3600, 7200, 5400, "60-120min"),
    (7200, 14400, 6800, "120min+"),
]
# representative listen_sec per bucket (seeded into per-user rows)
BUCKET_SEC = [150, 600, 1350, 2700, 5400, 9000]

WAU = sum(b[2] for b in LISTEN_BUCKETS)                                  # 32,000
WAEL = sum(b[2] for b in LISTEN_BUCKETS if b[0] >= ENGAGED_THRESHOLD_SEC)  # 18,400

# new vs returning split (of the 32,000 WAU)
NEW_ACTIVE = 4000
NEW_ENGAGED = 2480           # 62.0% activation
RETURNING_ACTIVE = WAU - NEW_ACTIVE     # 28,000
RETURNING_ENGAGED = WAEL - NEW_ENGAGED  # 15,920

# content-quality + counter-metric counters (explicit, pinned)
TOTAL_EP_STARTED = 136400
TOTAL_EP_COMPLETED = 95200
TOTAL_SKIPS = 12200
TOTAL_SHARERS = 1040

# guardrail / system metrics (explicit)
P99_LATENCY_MS = 640
P99_LATENCY_TARGET_MS = 800
ERROR_RATE_PCT = 0.21
ERROR_RATE_TARGET_PCT = 0.50
CHURN_PCT = 2.1
CHURN_TARGET_PCT = 3.0

# Goodhart's Law scenarios: (name, wael_delta_pct, skip_delta_pp, share_delta_pp)
GOODHART = [
    ("A genuine lift",   12.0, -1.2, +0.4),
    ("B autoplay gaming", 18.0, +4.8, -0.6),
]
# decision rule thresholds (counter-metric guardrails)
SKIP_BREACH_PP = 1.0     # skip rate must not rise more than +1.0pp
SHARE_BREACH_PP = -0.1   # share rate must not fall below -0.1pp

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def pct(x, y):
    return (100.0 * x / y) if y else 0.0


def ascii_bar(value, vmax, width=30):
    n = int(round(width * value / vmax)) if vmax else 0
    return "#" * n


def build_db():
    """In-memory sqlite with one row per weekly active user. Reproduces
    WAU == 32,000 and WAEL == 18,400 exactly."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE weekly_listening (
          user_id INTEGER PRIMARY KEY,
          is_new INTEGER,
          listen_sec INTEGER
        );
        CREATE INDEX idx_new ON weekly_listening(is_new);
        """
    )
    rows = []
    uid = 0
    # non-engaged buckets are generated first (uid 1..13,600), then engaged
    # (uid 13,601..32,000); is_new is assigned so the cohort split reproduces
    # exactly NEW_ACTIVE / NEW_ENGAGED / RETURNING_* above.
    for bidx, (lo, hi, count, label) in enumerate(LISTEN_BUCKETS):
        sec = BUCKET_SEC[bidx]
        engaged = lo >= ENGAGED_THRESHOLD_SEC
        for _ in range(count):
            uid += 1
            is_new = 0
            if (not engaged) and uid <= 1520:
                is_new = 1
            if engaged and 13601 <= uid <= 16080:
                is_new = 1
            rows.append((uid, is_new, sec))
    conn.executemany("INSERT INTO weekly_listening VALUES (?, ?, ?)", rows)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# SECTION 1 - NSM definition
# ---------------------------------------------------------------------------
def section_definition():
    banner("SECTION 1: North Star Metric definition (Weekly Active Engaged Listeners)")
    print(f"Product: {PRODUCT}.")
    print("NSM = Weekly Active Engaged Listeners (WAEL): unique users who listened")
    print(f"      >= {ENGAGED_THRESHOLD_SEC // 60} min ({ENGAGED_THRESHOLD_SEC}s) in the past 7 days.\n")
    conn = build_db()
    row = conn.execute(
        """
        SELECT
          COUNT(*) AS wau,
          SUM(CASE WHEN listen_sec >= ? THEN 1 ELSE 0 END) AS wael
        FROM weekly_listening WHERE listen_sec > 0
        """,
        (ENGAGED_THRESHOLD_SEC,),
    ).fetchone()
    conn.close()
    wau, wael = row
    eng_rate = pct(wael, wau)
    biggest = max(b[2] for b in LISTEN_BUCKETS)
    print("Listen-time distribution of the weekly active users:")
    for lo, hi, count, label in LISTEN_BUCKETS:
        bar = ascii_bar(count, biggest, width=30)
        mark = "  <-- engagement threshold (30 min)" if (lo < ENGAGED_THRESHOLD_SEC <= hi) else ""
        print(f"  {label:<9} {count:>6,}  {pct(count, wau):>5.1f}%  {bar}{mark}")
    print()
    print(f"WAU  (weekly active, > 0 min)  = {wau:>7,}")
    print(f"WAEL (engaged, >= 30 min)      = {wael:>7,}")
    print(f"Engagement rate = WAEL / WAU   = {eng_rate:.1f}%")
    print()
    print("=> WAEL counts VALUE DELIVERED, not revenue or raw presence. A user who opens")
    print("   the app and dismisses a notification is active but NOT engaged; WAEL filters")
    print("   them out. Cadence = weekly, matching the podcast listening habit (not DAU).")
    print()
    print("[check] SQL reproduces WAU == 32,000? " + ("OK" if wau == WAU else "FAIL"))
    print("[check] SQL reproduces WAEL == 18,400? " + ("OK" if wael == WAEL else "FAIL"))
    print("[check] engagement rate == 57.5%? " + ("OK" if round(eng_rate, 1) == 57.5 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Metric tree decomposition
# ---------------------------------------------------------------------------
def section_tree():
    banner("SECTION 2: Metric tree decomposition (NSM -> L1 drivers -> L2 inputs)")
    conn = build_db()
    row = conn.execute(
        """
        SELECT
          SUM(CASE WHEN is_new=1 THEN 1 ELSE 0 END) AS new_active,
          SUM(CASE WHEN is_new=1 AND listen_sec >= ? THEN 1 ELSE 0 END) AS new_engaged,
          SUM(CASE WHEN is_new=0 THEN 1 ELSE 0 END) AS ret_active,
          SUM(CASE WHEN is_new=0 AND listen_sec >= ? THEN 1 ELSE 0 END) AS ret_engaged
        FROM weekly_listening WHERE listen_sec > 0
        """,
        (ENGAGED_THRESHOLD_SEC, ENGAGED_THRESHOLD_SEC),
    ).fetchone()
    conn.close()
    new_a, new_e, ret_a, ret_e = row
    new_rate = pct(new_e, new_a)
    ret_rate = pct(ret_e, ret_a)
    eng = pct(WAEL, WAU)

    print("L0 NSM = WAEL = 18,400   (weekly, leadership)\n")
    print("Multiplicative decomposition:")
    print(f"    WAEL  =  WAU  x  Engagement Rate")
    print(f"          =  {WAU:,}  x  {eng:.1f}%")
    print(f"          =  {int(round(WAU * eng / 100.0)):,}\n")

    print("Additive (cohort) decomposition:")
    print("    WAEL  =  New engaged  +  Returning engaged")
    print(f"          =  {new_a:,} x {new_rate:.1f}%  +  {ret_a:,} x {ret_rate:.2f}%")
    print(f"          =  {new_e:,}  +  {ret_e:,}")
    print(f"          =  {new_e + ret_e:,}\n")

    print("L1 product-area drivers (daily, owned by PMs):")
    print(f"    activation rate (new)    = {new_rate:.1f}%   <- onboarding team")
    print(f"    engagement rate (ret)    = {ret_rate:.2f}%  <- retention team")
    print(f"    completion rate          = {pct(TOTAL_EP_COMPLETED, TOTAL_EP_STARTED):.2f}%  <- content team")
    print(f"    discovery -> start rate  = {pct(TOTAL_EP_STARTED, WAU):.1f}% ep/user  <- discovery team")
    print()
    print("L2 feature-level input metrics (hourly/daily, owned by feature eng):")
    print("    search CTR, autoplay-rate, episode-start rate, playlist-save rate")
    print()
    print("Causal attribution chain (how a feature reaches the NSM):")
    print("    Feature: autoplay toggle")
    print("      -> L2  autoplay-rate      +8.0%   (40% -> 48%)")
    print("      -> L1  completion rate    +3.2 pp (69.79% -> 73.0%)")
    print("      -> NSM WAEL               +2.1%   (18,400 -> 18,787)")
    print()
    print("=> Each driver is owned by ONE team and is independently A/B-testable. A good")
    print("   tree is exhaustive-but-not-redundant: drivers cover the variance in WAEL")
    print("   without overlapping (no double-counted team incentives).")
    print()
    mult_ok = int(round(WAU * eng / 100.0)) == WAEL
    add_ok = (new_e + ret_e) == WAEL
    print("[check] WAU x Engagement == WAEL (18,400)? " + ("OK" if mult_ok else "FAIL"))
    print("[check] New + Returning engaged == WAEL? " + ("OK" if add_ok else "FAIL"))
    print("[check] new activation == 62.0%? " + ("OK" if round(new_rate, 1) == 62.0 else "FAIL"))
    print("[check] returning engagement == 56.86%? " + ("OK" if round(ret_rate, 2) == 56.86 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Guardrail & counter-metrics (four-layer stack)
# ---------------------------------------------------------------------------
def section_guardrails():
    banner("SECTION 3: Guardrail & counter-metrics (four-layer measurement stack)")
    completion = pct(TOTAL_EP_COMPLETED, TOTAL_EP_STARTED)
    skip = pct(TOTAL_SKIPS, TOTAL_EP_STARTED)
    share = pct(TOTAL_SHARERS, WAU)
    print("Layer 01  North Star Metric : WAEL = 18,400")
    print("Layer 02  Driver Tree       : WAU, activation, completion, discovery")
    print("Layer 03  Guardrail Metrics : checked in EVERY A/B test + launch decision")
    print("Layer 04  Counter-Metrics   : expose whether a WAEL lift is real or gamed\n")
    print(f"  {'guardrail':<22} {'current':>11} {'target':>11} {'status':>8}  rationale")
    rows = [
        ("skip rate",         skip,             15.0,                 "%",  "<=", "listening is real, not bot skipping"),
        ("p99 start latency", P99_LATENCY_MS,   P99_LATENCY_TARGET_MS, "ms", "<=", "system health; slow starts lose listeners"),
        ("error rate (5xx)",  ERROR_RATE_PCT,   ERROR_RATE_TARGET_PCT, "%",  "<=", "infra health; errors block playback"),
        ("voluntary churn",   CHURN_PCT,        CHURN_TARGET_PCT,      "%",  "<=", "user-wellbeing floor"),
    ]
    all_ok = True
    for name, cur, tgt, unit, op, why in rows:
        ok = cur <= tgt
        if not ok:
            all_ok = False
        print(f"  {name:<22} {cur:>9.2f}{unit} {tgt:>9.2f}{unit} {'OK' if ok else 'BREACH':>8}  {why}")
    print()
    print(f"  counter-metric: share rate = {share:.2f}%   ({TOTAL_SHARERS:,} sharers / {WAU:,} WAU)")
    print("    -> if WAEL rises but share rate FALLS, the extra listening is low-quality")
    print("       (autoplay, accidental plays). That is Goodhart's Law in action.")
    print()
    print("=> A feature that lifts WAEL but breaches ANY guardrail does NOT ship. The")
    print("   counter-metric is designed AT THE SAME TIME as the NSM, before any team has")
    print("   an incentive to game it.")
    print()
    print("[check] all guardrails within target? " + ("OK" if all_ok else "FAIL"))
    print("[check] completion rate == 69.79%? " + ("OK" if round(completion, 2) == 69.79 else "FAIL"))
    print("[check] skip rate == 8.94%? " + ("OK" if round(skip, 2) == 8.94 else "FAIL"))
    print("[check] share rate == 3.25%? " + ("OK" if round(share, 2) == 3.25 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Leading vs lagging indicators
# ---------------------------------------------------------------------------
def section_leading_lagging():
    banner("SECTION 4: Leading vs lagging indicators (time-horizon map)")
    print("A LEADING indicator moves BEFORE the outcome and lets you act within a sprint.")
    print("A LAGGING indicator confirms an outcome that already happened (the scoreboard).")
    print("Pair them so you can course-correct before revenue moves.\n")
    rows = [
        ("leading",    "episode start rate",      "same day",    "WAEL next week",           "L2"),
        ("leading",    "new-user activation %",   "same week",   "WAEL in 2-4 weeks",        "L1"),
        ("leading",    "search CTR",              "same day",    "discovery -> engagement",  "L2"),
        ("coincident", "WAEL (the NSM)",          "this week",   "IS the outcome",           "L0"),
        ("coincident", "completion rate",         "this week",   "content quality now",      "L1"),
        ("lagging",    "premium conversion",      "+3-6 months", "monetization of WAEL",     "revenue"),
        ("lagging",    "monthly churn",           "past month",  "retention already realized", "guardrail"),
        ("lagging",    "MRR",                     "this month",  "revenue realized",         "revenue"),
    ]
    print(f"  {'type':<12} {'metric':<24} {'moves':<14} {'signal':<28} {'layer':<10}")
    for t, m, mv, sig, lay in rows:
        print(f"  {t:<12} {m:<24} {mv:<14} {sig:<28} {lay:<10}")
    print()
    print("=> Leading indicators let teams course-correct WITHIN a sprint; lagging")
    print("   indicators are the scoreboard. Revenue (premium conversion, MRR) is lagging")
    print("   by months, which is EXACTLY why it must NOT be the NSM.")
    print()
    rev_lagging = all(r[0] == "lagging" for r in rows if r[4] == "revenue")
    wael_coincident = any(r[0] == "coincident" and r[1].startswith("WAEL") for r in rows)
    n_lead = sum(1 for r in rows if r[0] == "leading")
    n_lag = sum(1 for r in rows if r[0] == "lagging")
    print("[check] all revenue metrics are lagging? " + ("OK" if rev_lagging else "FAIL"))
    print("[check] WAEL is coincident (the NSM itself)? " + ("OK" if wael_coincident else "FAIL"))
    print(f"[check] leading ({n_lead}) + lagging ({n_lag}) both present? " +
          ("OK" if n_lead >= 2 and n_lag >= 2 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Goodhart's Law simulation
# ---------------------------------------------------------------------------
def section_goodhart():
    banner("SECTION 5: Goodhart's Law simulation (genuine lift vs autoplay gaming)")
    print('"When a measure becomes a target, it ceases to be a good measure."')
    print("Decision rule: SHIP only if WAEL rises AND counter-metrics hold:\n")
    print(f"    WAEL delta       > 0")
    print(f"    skip-rate delta  <= +{SKIP_BREACH_PP:.1f} pp")
    print(f"    share-rate delta >= {SHARE_BREACH_PP:+.1f} pp\n")
    print(f"  {'scenario':<20} {'WAEL':>7} {'skip d':>9} {'share d':>9}  {'verdict':<10}")
    results = []
    for name, wael_d, skip_d, share_d in GOODHART:
        ok_skip = skip_d <= SKIP_BREACH_PP
        ok_share = share_d >= SHARE_BREACH_PP
        verdict = "SHIP" if (wael_d > 0 and ok_skip and ok_share) else "REJECT"
        results.append(verdict)
        print(f"  {name:<20} {wael_d:>+6.1f}% {skip_d:>+8.1f}pp {share_d:>+8.1f}pp  {verdict:<10}")
    print()
    print("=> Scenario A lifts WAEL +12% with skip FALLING and share RISING => genuine.")
    print("   Scenario B lifts WAEL +18% (bigger!) but skip spikes +4.8pp and share drops")
    print("   => autoplay inflated the listening. The counter-metrics catch the gaming the")
    print("   NSM alone would reward. This is why every NSM needs a counter-metric.")
    print()
    print("[check] Scenario A ships? " + ("OK" if results[0] == "SHIP" else "FAIL"))
    print("[check] Scenario B rejected? " + ("OK" if results[1] == "REJECT" else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Metric cadence hierarchy
# ---------------------------------------------------------------------------
def section_cadence():
    banner("SECTION 6: Metric cadence hierarchy (who owns what, how often)")
    rows = [
        ("L0", "NSM",       "WAEL",                         "weekly",    "leadership",    "is the company healthy?"),
        ("L1", "product",   "WAU / activation / completion", "daily",    "PMs",           "is my product area healthy?"),
        ("L2", "feature",   "search CTR / autoplay rate",    "hourly",   "feature eng",   "did my feature move the lever?"),
        ("GR", "guardrail", "p99 latency / error rate",      "real-time", "SRE / on-call", "is the system floor holding?"),
    ]
    print(f"  {'level':<5} {'kind':<10} {'metric':<32} {'cadence':<10} {'owner':<14} question")
    for lvl, kind, m, cad, owner, q in rows:
        print(f"  {lvl:<5} {kind:<10} {m:<32} {cad:<10} {owner:<14} {q}")
    print()
    print("=> Cadence matches decision speed: guardrails are real-time (a latency spike")
    print("   must page on-call within minutes); the NSM is weekly (slow enough to see real")
    print("   trend above noise, fast enough to course-correct within a sprint). Daily L1")
    print("   metrics are noisy for a product this size, so the NSM rolls them up weekly.")
    print()
    print("[check] NSM cadence == weekly? " + ("OK" if rows[0][3] == "weekly" else "FAIL"))
    print("[check] guardrail cadence == real-time? " + ("OK" if rows[3][3] == "real-time" else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for north_star_metrics.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 7: GOLD values (pinned for north_star_metrics.html)")
    eng = pct(WAEL, WAU)
    new_rate = pct(NEW_ENGAGED, NEW_ACTIVE)
    ret_rate = pct(RETURNING_ENGAGED, RETURNING_ACTIVE)
    completion = pct(TOTAL_EP_COMPLETED, TOTAL_EP_STARTED)
    skip = pct(TOTAL_SKIPS, TOTAL_EP_STARTED)
    share = pct(TOTAL_SHARERS, WAU)
    gold = [
        ("wau",                f"{WAU}",                "32000"),
        ("wael",               f"{WAEL}",               "18400"),
        ("engagement_rate",    f"{eng:.1f}",            "57.5"),
        ("new_active",         f"{NEW_ACTIVE}",         "4000"),
        ("new_engaged",        f"{NEW_ENGAGED}",        "2480"),
        ("new_activation",     f"{new_rate:.1f}",       "62.0"),
        ("returning_active",   f"{RETURNING_ACTIVE}",   "28000"),
        ("returning_engaged",  f"{RETURNING_ENGAGED}",  "15920"),
        ("returning_eng",      f"{ret_rate:.2f}",       "56.86"),
        ("completion_rate",    f"{completion:.2f}",     "69.79"),
        ("skip_rate",          f"{skip:.2f}",           "8.94"),
        ("share_rate",         f"{share:.2f}",          "3.25"),
        ("p99_latency_ms",     f"{P99_LATENCY_MS}",     "640"),
        ("error_rate_pct",     f"{ERROR_RATE_PCT:.2f}", "0.21"),
        ("churn_pct",          f"{CHURN_PCT:.1f}",      "2.1"),
        ("goodhart_a_verdict", "SHIP",                  "SHIP"),
        ("goodhart_b_verdict", "REJECT",                "REJECT"),
    ]
    print(f"  {'check':<22} {'py recompute':>14} {'GOLD':>10} {'match':>7}")
    all_ok = True
    for label, got, want in gold:
        ok = got == want
        if not ok:
            all_ok = False
        print(f"  {label:<22} {got:>14} {want:>10} {'OK' if ok else 'FAIL':>7}")
    print()
    print("[check] ALL GOLD values reproduce from the NSM formulas? " +
          ("OK" if all_ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# north_star_metrics.py - North Star Metric simulation")
    print("# Pure Python stdlib only. Numbers below feed NORTH_STAR_METRICS.md")
    print("# and north_star_metrics.html (gold-checked).")
    section_definition()
    section_tree()
    section_guardrails()
    section_leading_lagging()
    section_goodhart()
    section_cadence()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
