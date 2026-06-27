#!/usr/bin/env python3
"""
funnel_analysis.py - Funnel analysis simulation (GROUND TRUTH).

Pure Python stdlib only (sqlite3). Every number printed below feeds
FUNNEL_ANALYSIS.md and is recomputed identically in funnel_analysis.html
(gold-checked).

Sections:
  1. Multi-step funnel counts + per-step conversion (visit -> signup -> activate -> purchase)
  2. Drop-off analysis + impact ranking
  3. Time-to-convert distribution (P50, P90, histogram)
  4. Funnel comparison (Variant A vs Variant B)
  5. Cohort-segmented funnels (by device)
  6. Simpson's paradox (aggregate vs segment)
  7. GOLD values pinned for funnel_analysis.html
"""

import sqlite3

# ---------------------------------------------------------------------------
# source-of-truth constants (mirrored in funnel_analysis.html GOLD)
# ---------------------------------------------------------------------------
STEP_NAMES = ["visit", "signup", "activate", "purchase"]
MAIN = [100000, 62000, 37200, 11160]      # overall 11.16%
VARIANT_A = [50000, 30000, 18000, 5400]   # overall 10.80%  (control)
VARIANT_B = [50000, 33000, 21450, 7722]   # overall 15.44%  (variant)
MOBILE = [65000, 37700, 21235, 5309]      # overall 8.17%
DESKTOP = [35000, 24300, 15965, 5851]     # overall 16.72%
# time-to-convert intervals for the 11,160 purchasers: (lo_hours, hi_hours, count, label)
TTC_INTERVALS = [
    (0, 1, 1500, "<1h"),
    (1, 6, 3000, "1-6h"),
    (6, 24, 3500, "6-24h"),
    (24, 72, 2000, "1-3d"),
    (72, 168, 800, "3-7d"),
    (168, 336, 360, "7-14d"),
]
# Simpson's paradox: {period: {segment: (visits, conversions)}}
SIMPSON = {
    "p1": {"mobile": (8000, 1200), "desktop": (2000, 560)},   # aggregate 17.6%
    "p2": {"mobile": (4000, 480), "desktop": (6000, 1740)},   # aggregate 22.2%
}

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt(n):
    return "{:,}".format(n)


def pct(x, y):
    return (100.0 * x / y) if y else 0.0


def rates(counts):
    """Step-over-step rates + overall rate for a funnel count vector."""
    step_rates = [pct(counts[i + 1], counts[i]) for i in range(len(counts) - 1)]
    overall = pct(counts[-1], counts[0])
    return step_rates, overall


def ascii_bar(value, vmax, width=34):
    n = int(round(width * value / vmax)) if vmax else 0
    return "#" * n


def build_user_rows():
    """[(user_id, device, max_step), ...] for 100,000 users whose
    device-segmented funnels reproduce MAIN == MOBILE + DESKTOP exactly."""
    mobile_by_step = [
        MOBILE[0] - MOBILE[1], MOBILE[1] - MOBILE[2], MOBILE[2] - MOBILE[3], MOBILE[3],
    ]
    desktop_by_step = [
        DESKTOP[0] - DESKTOP[1], DESKTOP[1] - DESKTOP[2], DESKTOP[2] - DESKTOP[3], DESKTOP[3],
    ]
    rows = []
    uid = 0
    for device, by_step in (("mobile", mobile_by_step), ("desktop", desktop_by_step)):
        for step in range(4):
            for _ in range(by_step[step]):
                uid += 1
                rows.append((uid, device, step))
    return rows


def build_db():
    """In-memory sqlite with users + events. The events pivot reproduces MAIN."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE users (user_id INTEGER PRIMARY KEY, device TEXT, max_step INTEGER);
        CREATE TABLE events (user_id INTEGER, event_type TEXT, ts INTEGER);
        CREATE INDEX idx_events_user ON events(user_id);
        """
    )
    user_rows = build_user_rows()
    conn.executemany("INSERT INTO users VALUES (?, ?, ?)", user_rows)
    ev_rows = []
    for uid, _device, max_step in user_rows:
        for s in range(max_step + 1):
            ev_rows.append((uid, STEP_NAMES[s], s))
    conn.executemany("INSERT INTO events VALUES (?, ?, ?)", ev_rows)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# SECTION 1 - Multi-step funnel counts + per-step conversion
# ---------------------------------------------------------------------------
def section_counts():
    banner("SECTION 1: Multi-step funnel (visit -> signup -> activate -> purchase)")
    print("Events pivoted with MIN(CASE WHEN event_type=... THEN ts END) per user;")
    print("a step counts only if it occurred AFTER the prior step (time ordering).\n")
    conn = build_db()
    row = conn.execute(
        """
        WITH p AS (
          SELECT user_id,
            MIN(CASE WHEN event_type='visit'    THEN ts END) AS visit_at,
            MIN(CASE WHEN event_type='signup'   THEN ts END) AS signup_at,
            MIN(CASE WHEN event_type='activate' THEN ts END) AS activate_at,
            MIN(CASE WHEN event_type='purchase' THEN ts END) AS purchase_at
          FROM events GROUP BY user_id
        )
        SELECT
          COUNT(*) AS visit,
          COUNT(CASE WHEN signup_at   IS NOT NULL AND signup_at   > visit_at    THEN 1 END) AS signup,
          COUNT(CASE WHEN activate_at IS NOT NULL AND activate_at > signup_at   THEN 1 END) AS activate,
          COUNT(CASE WHEN purchase_at IS NOT NULL AND purchase_at > activate_at THEN 1 END) AS purchase
        FROM p
        """
    ).fetchone()
    conn.close()
    counts = list(row)
    step_rates, overall = rates(counts)
    vmax = counts[0]
    print("Funnel counts + step-over-step conversion:")
    for i, name in enumerate(STEP_NAMES):
        bar = ascii_bar(counts[i], vmax)
        if i == 0:
            print(f"  {name:<9} {counts[i]:>7,}  {bar}")
        else:
            sr = step_rates[i - 1]
            print(f"  {name:<9} {counts[i]:>7,}  {bar}  (step {sr:5.1f}%, drop {100 - sr:5.1f}%)")
    print()
    print(f"Overall conversion: {counts[-1]:,} / {counts[0]:,} = {overall:.2f}%")
    print()
    print("=> activate -> purchase is the WORST step (30% step rate, 70% drop),")
    print("   but the biggest absolute leak is visit -> signup (38,000 users lost).")
    print()
    print("[check] SQL pivot reproduces MAIN counts? " +
          ("OK" if counts == MAIN else "FAIL"))
    print("[check] overall conversion == 11.16%? " +
          ("OK" if round(overall, 2) == 11.16 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Drop-off analysis + impact ranking
# ---------------------------------------------------------------------------
def section_dropoff():
    banner("SECTION 2: Drop-off analysis + impact ranking")
    counts = MAIN
    print("At each transition: users lost, drop rate, and users recovered if we")
    print("recovered 10% of the dropped cohort (impact = entering x drop x 0.10).\n")
    rows = []
    for i in range(len(counts) - 1):
        entering = counts[i]
        lost = counts[i] - counts[i + 1]
        drop = 100.0 - pct(counts[i + 1], counts[i])
        impact = entering * (drop / 100.0) * 0.10
        label = f"{STEP_NAMES[i]} -> {STEP_NAMES[i + 1]}"
        rows.append((label, entering, lost, drop, impact))
    print(f"  {'transition':<22} {'entering':>10} {'lost':>10} {'drop %':>9} {'impact@10%':>12}")
    for label, entering, lost, drop, impact in rows:
        print(f"  {label:<22} {entering:>10,} {lost:>10,} {drop:>8.1f}% {impact:>12,.0f}")
    print()
    ranked = sorted(rows, key=lambda r: -r[4])
    print("Priority by IMPACT (not worst conversion rate):")
    for rank, (label, _e, lost, drop, impact) in enumerate(ranked, 1):
        print(f"  {rank}. {label:<22} recover ~{int(impact):,} users  (drop {drop:.1f}%)")
    print()
    print("=> the worst rate (activate -> purchase, 70% drop) is NOT the top priority:")
    print("   visit -> signup wins because 100,000 users enter it. Prioritize absolute")
    print("   users recovered, never the worst percentage alone.")
    print()
    total_impact = sum(r[4] for r in rows)
    print("[check] top-impact step is visit -> signup? " +
          ("OK" if ranked[0][0].startswith("visit") else "FAIL"))
    print("[check] total recoverable (10%) == 8,884 users? " +
          ("OK" if round(total_impact) == 8884 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Time-to-convert distribution
# ---------------------------------------------------------------------------
def percentile_from_intervals(intervals, p):
    total = sum(iv[2] for iv in intervals)
    target = p / 100.0 * total
    cum = 0.0
    for lo, hi, count, _label in intervals:
        if cum + count >= target:
            frac = (target - cum) / count if count else 0.0
            return lo + frac * (hi - lo)
        cum += count
    return intervals[-1][1]


def section_ttc():
    banner("SECTION 3: Time-to-convert distribution (purchasers only)")
    total = sum(iv[2] for iv in TTC_INTERVALS)
    print(f"Time from first visit to purchase for the {total:,} purchasers.\n")
    biggest = max(iv[2] for iv in TTC_INTERVALS)
    print(f"  {'bucket':<8} {'users':>9} {'share':>8}   histogram")
    for lo, hi, count, label in TTC_INTERVALS:
        bar = ascii_bar(count, biggest, width=24)
        print(f"  {label:<8} {count:>9,} {pct(count, total):>7.1f}%   {bar}")
    p50 = percentile_from_intervals(TTC_INTERVALS, 50)
    p90 = percentile_from_intervals(TTC_INTERVALS, 90)
    print()
    print(f"P50 time-to-convert = {p50:.2f} hours")
    print(f"P90 time-to-convert = {p90:.2f} hours  (~{p90 / 24.0:.1f} days)")
    print()
    print(f"=> P90 of {p90 / 24.0:.1f} days signals friction: 1 in 10 purchasers needs")
    print("   more than 3 days. A long P90 points at onboarding/payment friction that")
    print("   the step rates alone cannot see.")
    print()
    print("[check] P50 == 11.55h? " + ("OK" if round(p50, 2) == 11.55 else "FAIL"))
    print("[check] P90 == 77.28h? " + ("OK" if round(p90, 2) == 77.28 else "FAIL"))
    print("[check] TTC buckets sum to purchasers (11,160)? " +
          ("OK" if total == MAIN[-1] else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Funnel comparison (Variant A vs Variant B)
# ---------------------------------------------------------------------------
def section_compare():
    banner("SECTION 4: Funnel comparison (Variant A vs Variant B)")
    a_rates, a_overall = rates(VARIANT_A)
    b_rates, b_overall = rates(VARIANT_B)
    print(f"  {'step':<9} {'A (control)':>14} {'B (variant)':>14}")
    for i, name in enumerate(STEP_NAMES):
        print(f"  {name:<9} {VARIANT_A[i]:>14,} {VARIANT_B[i]:>14,}")
    print()
    print("Step-over-step conversion:")
    print(f"  {'transition':<22} {'A':>10} {'B':>10} {'delta':>9}")
    for i in range(3):
        label = f"{STEP_NAMES[i]} -> {STEP_NAMES[i + 1]}"
        print(f"  {label:<22} {a_rates[i]:>9.1f}% {b_rates[i]:>9.1f}% {b_rates[i] - a_rates[i]:>+8.1f} pp")
    print()
    rel_lift = (b_overall / a_overall - 1.0) * 100.0
    abs_lift = b_overall - a_overall
    print(f"Overall conversion:  A {a_overall:.2f}%   B {b_overall:.3f}%")
    print(f"Absolute lift:  {abs_lift:+.3f} pp      Relative lift:  {rel_lift:+.1f}%")
    print()
    winner = "B" if b_overall > a_overall else "A"
    print(f"=> Variant {winner} wins on overall conversion ({abs_lift:+.3f} pp).")
    print("   Validate with a proper A/B test (sample size, guardrails) before rollout,")
    print("   and ALWAYS check segment-level rates for Simpson's paradox (Section 6).")
    print()
    print("[check] B overall == 15.444%? " +
          ("OK" if round(b_overall, 3) == 15.444 else "FAIL"))
    print("[check] relative lift == 43.0%? " +
          ("OK" if round(rel_lift, 1) == 43.0 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Cohort-segmented funnels (by device)
# ---------------------------------------------------------------------------
def section_segments():
    banner("SECTION 5: Cohort-segmented funnels (by device)")
    print("GROUP BY device on the users table reveals WHERE the drop-offs concentrate.\n")
    conn = build_db()
    rows = conn.execute(
        """
        SELECT device,
          SUM(CASE WHEN max_step >= 0 THEN 1 ELSE 0 END) AS visit,
          SUM(CASE WHEN max_step >= 1 THEN 1 ELSE 0 END) AS signup,
          SUM(CASE WHEN max_step >= 2 THEN 1 ELSE 0 END) AS activate,
          SUM(CASE WHEN max_step >= 3 THEN 1 ELSE 0 END) AS purchase
        FROM users GROUP BY device ORDER BY device
        """
    ).fetchall()
    conn.close()
    print(f"  {'device':<8} {'visit':>8} {'signup':>8} {'activate':>9} {'purchase':>9}")
    seg = {}
    for device, v, s, a, p in rows:
        seg[device] = [v, s, a, p]
        print(f"  {device:<8} {v:>8,} {s:>8,} {a:>9,} {p:>9,}")
    print()
    print("Step-over-step + overall by device:")
    print(f"  {'device':<8} {'visit->up':>10} {'up->act':>9} {'act->buy':>10} {'overall':>10}")
    for device in ("mobile", "desktop"):
        c = seg[device]
        sr, ov = rates(c)
        print(f"  {device:<8} {sr[0]:>9.1f}% {sr[1]:>8.1f}% {sr[2]:>9.1f}% {ov:>9.2f}%")
    print()
    print("=> mobile converts WORSE at every step (overall 8.17% vs desktop 16.72%).")
    print("   The activate -> purchase gap (25.0% mobile vs 36.6% desktop) is the loudest")
    print("   UX signal: mobile checkout/payment has friction worth fixing first.")
    print()
    m, d = seg["mobile"], seg["desktop"]
    sums_ok = all(m[i] + d[i] == MAIN[i] for i in range(4))
    print("[check] mobile + desktop == MAIN at every step? " + ("OK" if sums_ok else "FAIL"))
    print("[check] mobile overall (8.17%) < desktop overall (16.72%)? " +
          ("OK" if rates(m)[1] < rates(d)[1] else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Simpson's paradox (aggregate vs segment)
# ---------------------------------------------------------------------------
def section_simpson():
    banner("SECTION 6: Simpson's paradox (aggregate vs segment)")
    print("Two periods, mobile + desktop. The aggregate 'improves' while mobile")
    print("actually gets WORSE -- the lift came from a traffic-mix shift.\n")
    print(f"  {'':<8} {'Period 1':>22} {'Period 2':>22}")
    for seg in ("mobile", "desktop"):
        v1, c1 = SIMPSON["p1"][seg]
        v2, c2 = SIMPSON["p2"][seg]
        print(f"  {seg:<8} {c1:>5,} / {v1:>5,} ({pct(c1, v1):>4.1f}%)"
              f"   {c2:>5,} / {v2:>5,} ({pct(c2, v2):>4.1f}%)")
    totals = {}
    for period in ("p1", "p2"):
        v = sum(SIMPSON[period][s][0] for s in ("mobile", "desktop"))
        c = sum(SIMPSON[period][s][1] for s in ("mobile", "desktop"))
        totals[period] = (v, c)
    print(f"  {'TOTAL':<8} {totals['p1'][1]:>5,} / {totals['p1'][0]:>5,}"
          f" ({pct(totals['p1'][1], totals['p1'][0]):>4.1f}%)"
          f"   {totals['p2'][1]:>5,} / {totals['p2'][0]:>5,}"
          f" ({pct(totals['p2'][1], totals['p2'][0]):>4.1f}%)")
    print()
    agg1 = pct(totals["p1"][1], totals["p1"][0])
    agg2 = pct(totals["p2"][1], totals["p2"][0])
    mob1 = pct(SIMPSON["p1"]["mobile"][1], SIMPSON["p1"]["mobile"][0])
    mob2 = pct(SIMPSON["p2"]["mobile"][1], SIMPSON["p2"]["mobile"][0])
    agg_lift = agg2 - agg1
    mob_lift = mob2 - mob1
    print(f"Aggregate conversion: {agg1:.1f}% -> {agg2:.1f}%  ({agg_lift:+.1f} pp, looks like a WIN)")
    print(f"Mobile conversion:    {mob1:.1f}% -> {mob2:.1f}%  ({mob_lift:+.1f} pp, WORSE)")
    print()
    mix1 = SIMPSON["p1"]["desktop"][0] / totals["p1"][0] * 100
    mix2 = SIMPSON["p2"]["desktop"][0] / totals["p2"][0] * 100
    print(f"Cause: desktop traffic share rose {mix1:.0f}% -> {mix2:.0f}%. Desktop converts")
    print("higher, so the mix shift -- NOT product improvement -- lifted the aggregate.")
    print("=> ALWAYS segment before claiming causality.")
    print()
    print("[check] aggregate improved (+4.6 pp)? " +
          ("OK" if round(agg_lift, 1) == 4.6 else "FAIL"))
    print("[check] mobile degraded (-3.0 pp)? " +
          ("OK" if round(mob_lift, 1) == -3.0 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for funnel_analysis.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 7: GOLD values (pinned for funnel_analysis.html)")
    _sr, main_overall = rates(MAIN)
    a_overall = pct(VARIANT_A[-1], VARIANT_A[0])
    b_overall = pct(VARIANT_B[-1], VARIANT_B[0])
    rel_lift = (b_overall / a_overall - 1.0) * 100.0
    mob_overall = pct(MOBILE[-1], MOBILE[0])
    desk_overall = pct(DESKTOP[-1], DESKTOP[0])
    mob_buy = pct(MOBILE[-1], MOBILE[-2])
    desk_buy = pct(DESKTOP[-1], DESKTOP[-2])
    p50 = percentile_from_intervals(TTC_INTERVALS, 50)
    p90 = percentile_from_intervals(TTC_INTERVALS, 90)
    simp_p1 = pct(SIMPSON["p1"]["mobile"][1] + SIMPSON["p1"]["desktop"][1],
                  SIMPSON["p1"]["mobile"][0] + SIMPSON["p1"]["desktop"][0])
    simp_p2 = pct(SIMPSON["p2"]["mobile"][1] + SIMPSON["p2"]["desktop"][1],
                  SIMPSON["p2"]["mobile"][0] + SIMPSON["p2"]["desktop"][0])
    gold = [
        ("main_visit",            f"{MAIN[0]}",                  "100000"),
        ("main_purchase",         f"{MAIN[-1]}",                 "11160"),
        ("main_overall_pct",      f"{main_overall:.2f}",         "11.16"),
        ("main_step_signup_pct",  f"{pct(MAIN[1], MAIN[0]):.1f}", "62.0"),
        ("main_step_activate_pct", f"{pct(MAIN[2], MAIN[1]):.1f}", "60.0"),
        ("main_step_purchase_pct", f"{pct(MAIN[3], MAIN[2]):.1f}", "30.0"),
        ("variant_a_overall_pct", f"{a_overall:.2f}",            "10.80"),
        ("variant_b_overall_pct", f"{b_overall:.3f}",            "15.444"),
        ("variant_lift_rel_pct",  f"{rel_lift:.1f}",             "43.0"),
        ("mobile_overall_pct",    f"{mob_overall:.2f}",          "8.17"),
        ("desktop_overall_pct",   f"{desk_overall:.2f}",         "16.72"),
        ("mobile_purchase_rate",  f"{mob_buy:.1f}",              "25.0"),
        ("desktop_purchase_rate", f"{desk_buy:.1f}",             "36.6"),
        ("ttc_p50_hours",         f"{p50:.2f}",                  "11.55"),
        ("ttc_p90_hours",         f"{p90:.2f}",                  "77.28"),
        ("simpson_aggregate_p1",  f"{simp_p1:.1f}",              "17.6"),
        ("simpson_aggregate_p2",  f"{simp_p2:.1f}",              "22.2"),
    ]
    print(f"  {'check':<24} {'py recompute':>14} {'GOLD':>10} {'match':>7}")
    all_ok = True
    for label, got, want in gold:
        ok = got == want
        if not ok:
            all_ok = False
        print(f"  {label:<24} {got:>14} {want:>10} {'OK' if ok else 'FAIL':>7}")
    print()
    print("[check] ALL GOLD values reproduce from the funnel formulas? " +
          ("OK" if all_ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# funnel_analysis.py - Funnel analysis simulation")
    print("# Pure Python stdlib only. Numbers below feed FUNNEL_ANALYSIS.md")
    print("# and funnel_analysis.html (gold-checked).")
    section_counts()
    section_dropoff()
    section_ttc()
    section_compare()
    section_segments()
    section_simpson()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
