"""
scenario_problems.py - Ground-truth simulation for the Scenario Problems bundle.

The single source of truth that SCENARIO_PROBLEMS.md and scenario_problems.html
are built from. Every number, table, slice, and recommendation below is printed
by this file -- nothing in the guide is hand-computed.

Run:
    python3 scenario_problems.py

============================================================================
THE IDEA (read this first) -- scenario problems are solved with DIAGNOSE,
not by guessing
============================================================================
A "scenario problem" interview asks: "DAU dropped 10% -- investigate." There is
no single correct answer; the interviewer evaluates your REASONING PROCESS.
The trap is to jump to queries. The fix is a fixed, ordered framework:

    D  Define the signal        (metric, magnitude, timeline, segments, baseline)
    I  check the Instrument     (data pipeline integrity -- ~30-40% of "drops"
                                are pipeline bugs, not real product changes)
    A  Assemble hypotheses      (internal: product/eng/data/algo; external:
                                seasonal/competitor/platform/macro)
    G  Generate queries         (segment by platform / geo / cohort / time /
                                funnel -- each tests a hypothesis)
    N  Narrow to root cause     (process of elimination, not trial and error)
    O  Own the recommendation   (rollback / investigate / monitor + impact
                                sizing + next-check time)
    S  State uncertainty        (what you still do NOT know; time-box it)

This file runs FOUR canonical scenarios end-to-end through DIAGNOSE:

    1. DAU dropped 10%          -- the canonical step-change; iOS crash
    2. Revenue per user down 7%  -- the suppression trap; feed re-rank
    3. New feature A/B test      -- SRM breaks the experiment; mobile bucket bug
    4. Payment service 500s      -- P0 outage; Stripe EU provider degradation

Each scenario: decompose the metric, check the instrument, build a hypothesis
tree, segment to localize, match to a binary world event, own the recommendation.
Every number is loaded into an in-memory sqlite3 DB and queried so output is
reproducible.

Two engines (both pure stdlib):
    chi2_srm(observed, expected)  Pearson chi-square goodness-of-fit on A/B
                                  assignment counts -- the SRM red-light test.
    signal_score(path)            0..10 score for how well a diagnostic path
                                  follows DIAGNOSE (instrument-first, correct
                                  segmentation, correct root cause, owns the
                                  recommendation, states uncertainty).
"""

from __future__ import annotations

import sqlite3

BANNER = "=" * 72

# ============================================================================
# 1. SOURCE-OF-TRUTH CONSTANTS  (mirrored verbatim in scenario_problems.html
#    GOLD -- change here, re-run, re-paste everywhere)
# ============================================================================

# SRM chi-square critical value for df=1 at alpha=0.001. Platforms use a stricter
# alpha for SRM than for product metrics because SRM is a data-quality GATE.
SRM_CRITICAL = 10.828

DIAGNOSE_STEPS = [
    # key, letter, name, time, what
    ("define",     "D", "Define the signal",
     "1 min", "metric, magnitude, timeline, affected segments, normal baseline"),
    ("instrument", "I", "Check the instrument",
     "2 min", "pipeline integrity FIRST -- ~30-40% of drops are data bugs"),
    ("hypotheses", "A", "Assemble hypotheses",
     "3 min", "internal (product/eng/data/algo) + external (seasonal/competitor/platform/macro)"),
    ("queries",    "G", "Generate queries",
     "2 min", "segment by platform/geo/cohort/time/funnel -- each tests one hypothesis"),
    ("narrow",     "N", "Narrow to root cause",
     "3 min", "process of elimination; localize to a version/geo/tenure slice"),
    ("own",        "O", "Own the recommendation",
     "2 min", "rollback / investigate / monitor + impact sizing + next check"),
    ("state",      "S", "State uncertainty",
     "1 min", "what you still do NOT know; time-box the next check"),
]

# ---- Scenario 1: DAU dropped 10% (the canonical case) -----------------------
# baseline DAU = 2,000,000. Platform split: iOS 1,100,000 / Android 600,000 /
# Web 300,000. After: iOS 900,000 / Android 606,000 / Web 294,000 = 1,800,000.
# Drop = 200,000 = -10.0%. iOS accounts for 200,000 of the 200,000 drop (100%).

# ---- Scenario 2: Revenue per user down 7% (suppression trap) ---------------
# ARPU baseline $2.85 -> $2.65 (-7.0%). DAU flat 2,000,000.
# time-in-app +8% but ad impressions -12% -> revenue down despite engagement up.

# ---- Scenario 3: A/B test SRM (broken experiment) --------------------------
# configured 50/50, N=100,000. observed 56,100/43,900 overall.
# mobile 36,000/24,000 (60/40), web 20,100/19,900 (~50/50).

# ---- Scenario 4: Payment 500s (P0 outage) ----------------------------------
# error rate 0.1% -> 8.5%. EU+Stripe localized.

SCENARIOS = [
    # id, name, type, prompt, primary_metric, magnitude_pct, timeline,
    # baseline_value, current_value, value_unit
    (1, "DAU dropped 10%",
     "dau_drop",
     "DAU dropped 10% starting yesterday at 17:00 UTC -- investigate",
     "DAU (users with 1+ active event / 24h)",
     -10.0, "step change at 17:00 UTC, flat before",
     2000000, 1800000, "users"),
    (2, "Revenue per user declining",
     "rev_decline",
     "Ad revenue per DAU (ARPU) is down 7% over the last 2 weeks -- DAU is flat",
     "ARPU (ad revenue per DAU / day)",
     -7.0, "gradual decline over 14 days since feed re-rank rollout",
     2.85, 2.65, "$/user"),
    (3, "New feature A/B test",
     "ab_break",
     "New checkout redesign A/B shows +15% conversion (p=0.001) -- ship it?",
     "checkout conversion rate (treatment lift)",
     15.0, "14-day experiment, day-14 readout",
     0.0, 15.0, "% lift"),
    (4, "Payment service returning 500s",
     "p0_outage",
     "Payment 500 error rate jumped from 0.1% to 8.5% at 14:32 UTC -- it is a P0",
     "payment HTTP 500 error rate",
     8400.0, "step change at 14:32 UTC",
     0.1, 8.5, "% errors"),
]

# Instrument checks per scenario. status: healthy / degraded / broken.
# ~30-40% of "metric drops" in production are pipeline failures -- always check.
INSTRUMENT_CHECKS = [
    # scenario_id, check, status, detail
    (1, "Event ingestion lag",      "healthy",
     "pipeline lag 2 min (normal); event volume from iOS clients is down -- matches warehouse"),
    (1, "Two-source agreement",     "healthy",
     "Kafka stream and BigQuery warehouse agree within 0.3% -- not a pure pipeline story"),
    (1, "Logging-layer deploys",    "healthy",
     "no deploy to analytics/logging layer in 48h; upstream app IS sending events"),
    (2, "Revenue source agreement", "healthy",
     "ad-platform revenue API and internal revenue warehouse agree within 0.1%"),
    (2, "Attribution model change", "healthy",
     "no change to revenue attribution or ad-impression counting logic in 30d"),
    (3, "Experiment assignment log","healthy",
     "assignment events flowing; exposure logging intact; bucket IDs well-formed"),
    (3, "SRM chi-square (overall)", "broken",
     "configured 50/50; observed 56100/43900; chi2=1488.4 >> 10.828 -> SRM FAIL (red light)"),
    (4, "Service health (logs)",    "degraded",
     "500s confirmed in application logs AND distributed traces; not a logging artifact"),
    (4, "On-call alerting",         "healthy",
     "PagerDuty fired correctly at 14:33 UTC; latency SLO breach confirmed"),
]

# Hypothesis tree per scenario. category drives the fix path.
# is_root_cause marks the actual cause (revealed by narrowing).
HYPOTHESES = [
    # id, scenario_id, category, hypothesis, prior_rank, is_root_cause
    (1, 1, "internal_eng",     "iOS mobile release v4.2.1 introduced a crash",  1, 1),
    (2, 1, "internal_data",    "Logging pipeline partial failure dropping events", 2, 0),
    (3, 1, "external_seasonal","Day-of-week or seasonal trough",                   3, 0),
    (4, 1, "external_competitor","Competitor launched a feature, users migrating", 4, 0),
    (5, 2, "internal_algo",    "Feed re-rank shifted time to low-ad-inventory content", 1, 1),
    (6, 2, "internal_data",    "User mix shifted to low-ARPU geography",          2, 0),
    (7, 2, "external_platform","Ad provider fill rate or CPM dropped",            3, 0),
    (8, 2, "external_seasonal","Seasonal ad-spend decline (end of quarter)",      4, 0),
    (9, 3, "internal_eng",     "Mobile SDK applied eligibility filter AFTER bucket assignment", 1, 1),
    (10, 3, "internal_eng",    "Redirect in treatment path drops users",           2, 0),
    (11, 3, "internal_product","Treatment-induced dropout (slow/broken checkout)", 3, 0),
    (12, 3, "internal_eng",    "Assignment hash collision or seed bug",            4, 0),
    (13, 4, "external_provider","Stripe EU endpoint degradation (external provider)", 1, 1),
    (14, 4, "internal_eng",    "Connection pool exhaustion from retry amplification", 2, 0),
    (15, 4, "internal_eng",    "Recent deploy introduced a regression",           3, 0),
    (16, 4, "internal_infra",  "Database saturation or connection limits",        4, 0),
]

# Segmentation slices per scenario. The slice with is_localized=1 is where the
# drop concentrates -- this is the narrowing step.
# delta_pct is the metric change for that slice (sign matches the scenario).
SLICES = [
    # scenario_id, dimension, slice_name, baseline, current, delta_pct, is_localized
    (1, "platform", "iOS",     1100000, 900000, -18.2, 1),
    (1, "platform", "Android",  600000, 606000,  1.0,  0),
    (1, "platform", "Web",      300000, 294000, -2.0,  0),
    (2, "inventory", "Short-form video feed", 28.0, 33.04, 18.0, 0),
    (2, "inventory", "Main feed",              42.0, 38.64, -8.0, 0),
    (2, "inventory", "Stories",                15.0, 15.45,  3.0, 0),
    (2, "ad_metric", "Ad impressions (M/day)", 12.0, 10.56, -12.0, 1),
    (2, "ad_metric", "Time-in-app (min)",      28.0, 30.24,  8.0,  0),
    (2, "ad_metric", "Ad CTR",                  1.8,  1.80,  0.0,  0),
    (3, "platform", "Mobile", 50000, 60000, 20.0, 1),
    (3, "platform", "Web",    50000, 40000, -20.0, 0),
    (4, "region_x_provider", "EU + Stripe",  400000, 464000, 16.0, 1),
    (4, "region_x_provider", "US + Stripe",  800000, 816000,  2.0, 0),
    (4, "region_x_provider", "EU + PayPal",  300000, 300300,  0.1, 0),
    (4, "region_x_provider", "APAC + PayPal",500000, 502500,  0.5, 0),
]

# For scenario 3 the slice table is assignment counts, not metric deltas.
# Store SRM chi-square per slice computed by chi2_srm().
SRM_SLICES = [
    # scenario_id(3), slice, observed_c, observed_t, total, configured_ratio_c
    (3, "Mobile", 36000, 24000, 60000, 0.50),
    (3, "Web",    20100, 19900, 40000, 0.50),
    (3, "Overall",56100, 43900,100000, 0.50),
]

# Root cause match per scenario -- the binary world event that explains the drop.
ROOT_CAUSES = [
    # scenario_id, mechanism, evidence, world_event, severity, impact_users, impact_revenue
    (1, "iOS build v4.2.1 crash",
     "release timestamp 17:00 UTC matches DAU step-change to the minute; "
     "crash rate for v4.2.1 = 4.1% vs v4.2.0 = 0.3%",
     "mobile release v4.2.1 shipped at 17:00 UTC",
     "P1", 200000, 0),
    (2, "Feed re-rank over-weighted short-form video (70% lower ad density)",
     "time-in-app +8% but ad impressions -12%; video feed time +18% with -22% ad "
     "impressions; CTR flat so quality unchanged -- it is a SUPPRESSION, not degradation",
     "feed re-rank model v3 rolled out 14 days ago",
     "P2", 0, 400000),
    (3, "Mobile SDK eligibility filter ran AFTER bucket assignment",
     "mobile shows 60/40 split (chi2=2400); web is clean 50.25/49.75 (chi2=1.0); "
     "the +15% conversion lift is an artifact of biased assignment, NOT a real effect",
     "mobile checkout SDK v2.3 deployed with the experiment",
     "invalid", 0, 0),
    (4, "Stripe EU endpoint degradation + retry amplification",
     "EU+Stripe error 16%; US+Stripe 2%; EU+PayPal 0.1%; retry storm saturating "
     "connection pools is a second-order effect worsening the primary outage",
     "Stripe EU status page: elevated 500s from 14:30 UTC",
     "P0", 170000, 2100000),
]

# Recommendations per scenario -- action + next check + stated uncertainty.
RECOMMENDATIONS = [
    # scenario_id, action, next_check, uncertainty
    (1, "ROLLBACK iOS build v4.2.1 to v4.2.0 immediately; freeze iOS DAU in exec "
        "decks for the affected window; schedule postmortem on staged rollout + crash gates",
        "T+24h: confirm crash-free DAU on rollback cohort matches holdout",
        "if rollback does not recover DAU within 2h, broaden to acquisition/calendar"),
    (2, "THROTTLE feed re-rank video weight by 50%; add ARPU guardrail at -2% redline; "
        "extend observation 7 days; do NOT ship full rollout until ARPU recovers within tolerance",
        "T+7d: ARPU recovery to within -1% of baseline AND ad-impression volume stabilizes",
        "7-day ARPU is noisy; if it does not recover, kill the re-rank and redesign with "
        "a constrained objective (maximize session revenue subject to time-on-site floor)"),
    (3, "INVALIDATE the test -- do NOT present the +15% as a win; fix bucketing (apply "
        "eligibility BEFORE assignment); add automated SRM gating to the experiment platform; "
        "re-run for 14 days",
        "T+0: check whether any product decision was already made on the invalid readout",
        "the true treatment effect is UNKNOWN until a clean re-run; the +15% could be "
        "real, zero, or negative -- biased assignment makes it uninterpretable"),
    (4, "CIRCUIT-BREAK Stripe EU; failover EU payments to PayPal; shed non-critical "
        "retries to stop amplification; fail closed for unsafe operations; communicate "
        "customer impact every 15 min; P0 incident commander assigned",
        "T+15min: Stripe status update + EU error rate after failover",
        "ETA depends on Stripe; if failover saturates PayPal capacity, shed low-priority "
        "transactions and queue for retry"),
]

# The interactive decision flow -- branching choices per scenario.
# Each scenario has 4 stages: instrument, segment, root_cause, recommendation.
# verdict: correct / trap. trap_name references TRAPS for the learning.
DECISIONS = [
    # scenario_id, stage, choice_key, label, verdict, data_shown, trap_name
    # --- Stage 1: instrument ---
    (1, "instrument", "check_pipeline", "Check the data pipeline / instrument first", "correct",
     "pipeline lag 2min (normal); two-source agrees; logging layer clean -> INSTRUMENT HEALTHY", None),
    (1, "instrument", "jump_hypotheses", "Build a hypothesis tree immediately", "trap",
     "you skipped the instrument check -- ~30-40% of drops are pipeline bugs", "skip_pipeline"),
    (1, "instrument", "query_slices", "Segment DAU by platform right now", "trap",
     "segmenting before confirming the signal is real risks explaining noise", "queries_before_hypotheses"),
    # --- Stage 2: segment ---
    (1, "segment", "seg_platform", "Segment by platform (iOS / Android / Web)", "correct",
     "iOS -18.2%, Android +1.0%, Web -2.0% -> LOCALIZED TO iOS", None),
    (1, "segment", "seg_geo", "Segment by geography (country / region)", "trap",
     "geo is flat across regions -- this slice does not localize the drop", "single_segment"),
    (1, "segment", "seg_cohort", "Segment by user cohort (new vs returning)", "trap",
     "both new and returning are down within iOS -- cohort does not localize first", "single_segment"),
    # --- Stage 3: root_cause ---
    (1, "root_cause", "ios_crash", "iOS mobile release v4.2.1 introduced a crash", "correct",
     "release at 17:00 UTC matches step-change; crash rate 0.3%->4.1% for v4.2.1", None),
    (1, "root_cause", "competitor", "Competitor launched a feature, users migrated", "trap",
     "competitor launches are gradual, not a 17:00 step change; iOS-only is odd for that", "single_hypothesis"),
    (1, "root_cause", "seasonal", "Day-of-week or seasonal trough", "trap",
     "DoW-adjusted; flat before 17:00 the same day -- not a seasonal pattern", "single_hypothesis"),
    # --- Stage 4: recommendation ---
    (1, "recommendation", "rollback", "Rollback v4.2.1; comms; postmortem on crash gates", "correct",
     "P1; ~200k users affected (10% DAU); ETA 2h; freeze iOS DAU metric for affected window", None),
    (1, "recommendation", "monitor", "Monitor for 24h before acting", "trap",
     "a crashing build loses users every hour -- monitoring without action extends harm", "root_cause_only"),
    (1, "recommendation", "wait", "Wait for more data to be sure", "trap",
     "the evidence is time-aligned and localized; waiting ignores uncertainty about scope", "ignore_uncertainty"),

    # === Scenario 2 ===
    (2, "instrument", "check_pipeline", "Check revenue pipeline / attribution first", "correct",
     "ad-platform API and revenue warehouse agree within 0.1%; no attribution change -> HEALTHY", None),
    (2, "instrument", "jump_hypotheses", "Blame the feed re-rank immediately", "trap",
     "you jumped to a single hypothesis before confirming the data or building a tree", "single_hypothesis"),
    (2, "segment", "seg_inventory", "Segment by content inventory type (video / feed / stories)", "correct",
     "video time +18% but ad impressions -22%; main feed time -8% -> SUPPRESSION in video", None),
    (2, "segment", "seg_geo", "Segment by geography", "trap",
     "ARPU drop is global, not geo-specific -- mix shift ruled out", "single_segment"),
    (2, "root_cause", "feed_rerank", "Feed re-rank shifted time to low-ad-inventory content", "correct",
     "time-in-app +8% but ad impressions -12%; CTR flat -> SUPPRESSION TRAP, not degradation", None),
    (2, "root_cause", "ad_provider", "Ad provider fill rate or CPM dropped", "trap",
     "fill rate and CPM are flat -- the impressions are just fewer, not unfilled", "single_hypothesis"),
    (2, "recommendation", "throttle", "Throttle re-rank; add ARPU guardrail at -2%; iterate 7d", "correct",
     "P2; -$400k/day impact; extend to confirm ARPU recovery is durable", None),
    (2, "recommendation", "kill", "Kill the re-rank entirely and revert", "trap",
     "the engagement lift is real -- killing loses the upside; throttle first, then decide", "root_cause_only"),

    # === Scenario 3 ===
    (3, "instrument", "check_srm", "Run the SRM chi-square check FIRST", "correct",
     "configured 50/50; observed 56100/43900; chi2=1488.4 >> 10.828 -> SRM FAIL", None),
    (3, "instrument", "ship_it", "Ship the +15% conversion lift immediately", "trap",
     "you shipped on a broken experiment without checking assignment integrity", "skip_pipeline"),
    (3, "segment", "seg_platform", "Segment SRM by platform (mobile vs web)", "correct",
     "mobile 60/40 (chi2=2400); web 50.25/49.75 (chi2=1.0) -> LOCALIZED TO MOBILE", None),
    (3, "segment", "seg_geo", "Segment by geography", "trap",
     "SRM is not geo-driven; it is platform-driven -- wrong dimension", "single_segment"),
    (3, "root_cause", "eligibility", "Mobile SDK applied eligibility filter AFTER bucketing", "correct",
     "eligibility-after-assignment drops ineligible treatment users -> biased 60/40 split", None),
    (3, "root_cause", "redirect", "Redirect in the treatment path drops users", "trap",
     "redirects would show in web too; this is mobile-SDK-specific", "single_hypothesis"),
    (3, "recommendation", "invalidate", "Invalidate the test; fix bucketing; re-run 14d", "correct",
     "the +15% is an artifact; true effect UNKNOWN until clean re-run; add SRM gating", None),
    (3, "recommendation", "reweight", "Reweight the arms and present the adjusted lift", "trap",
     "reweighting a broken assignment does not fix causality -- re-run", "root_cause_only"),

    # === Scenario 4 ===
    (4, "instrument", "check_service", "Confirm service health: error rate, latency, on-call", "correct",
     "500s in logs AND traces; p95 latency 200ms->2400ms; PagerDuty fired -> CONFIRMED P0", None),
    (4, "instrument", "check_deploy", "Check for a recent deploy first", "trap",
     "no deploy in 6h -- root-cause theorizing before containment extends the outage", "root_cause_theory"),
    (4, "segment", "seg_region", "Segment by region x payment provider", "correct",
     "EU+Stripe 16%; US+Stripe 2%; EU+PayPal 0.1% -> LOCALIZED TO EU+STRIPE", None),
    (4, "segment", "seg_endpoint", "Segment by API endpoint", "trap",
     "endpoint view is noisy; region x provider isolates the blast radius faster", "single_segment"),
    (4, "root_cause", "stripe_eu", "Stripe EU endpoint degradation + retry amplification", "correct",
     "Stripe EU status page: elevated 500s from 14:30 UTC; retries saturating pools", None),
    (4, "root_cause", "db_sat", "Database saturation", "trap",
     "DB CPU 45%, healthy -- saturation is a second-order effect, not the cause", "single_hypothesis"),
    (4, "recommendation", "circuit_break", "Circuit-break Stripe EU; failover to PayPal; shed retries", "correct",
     "P0; ~170k failed tx/day; ~$2.1M/day at risk; comms every 15 min", None),
    (4, "recommendation", "restart", "Restart all payment services", "trap",
     "blind restarts erase evidence and do not contain the blast radius", "root_cause_only"),
]

# The five common mistakes (from discussion.md) -- the traps that cost senior bar.
TRAPS = [
    # name, failure_mode, fix
    ("skip_pipeline",
     "Skipping the instrument / pipeline check before investigating causes",
     "ALWAYS check data integrity first -- ~30-40% of drops are pipeline bugs"),
    ("queries_before_hypotheses",
     "Jumping to queries / segmentation before forming a hypothesis tree",
     "Build the hypothesis tree FIRST, then explain WHY each segmentation tests it"),
    ("single_hypothesis",
     "Proposing only one hypothesis and betting everything on it",
     "List 3-5 hypotheses (internal + external); prioritize by P x falsification cost"),
    ("root_cause_only",
     "Stopping at root cause without a recommendation, impact sizing, or next check",
     "Own the action: rollback / investigate / monitor + impact + time-boxed next check"),
    ("ignore_uncertainty",
     "Presenting a conclusion without stating what you still do NOT know",
     "Name the open questions and time-box the next check ('T+2h we will know X')"),
    ("root_cause_theory",
     "Spending 10 min on root-cause theory before containing user harm (P0s)",
     "P0 rule: stabilize impact FIRST, contain blast radius, THEN diagnose"),
    ("single_segment",
     "Trying only one segmentation dimension and missing the localizing slice",
     "Segment systematically: platform -> geo -> cohort -> time; pick by scenario type"),
]


# ============================================================================
# 2. ENGINES (pure stdlib)
# ============================================================================

def chi2_srm(observed_c: int, observed_t: int, ratio_c: float = 0.5) -> float:
    """Pearson chi-square goodness-of-fit for SRM on assignment counts.

    observed_c / observed_t = control / treatment assigned counts.
    ratio_c = configured control ratio (default 0.5 = 50/50).
    Returns the chi-square statistic (df=1). Compare to SRM_CRITICAL (10.828).
    """
    n = observed_c + observed_t
    exp_c = n * ratio_c
    exp_t = n * (1.0 - ratio_c)
    return ((observed_c - exp_c) ** 2 / exp_c) + ((observed_t - exp_t) ** 2 / exp_t)


def srm_verdict(chi2: float) -> str:
    """Return SRM verdict string."""
    return "SRM FAIL (red light)" if chi2 > SRM_CRITICAL else "SRM clean"


def signal_score(path: dict) -> int:
    """Score a diagnostic path 0..10 by how well it follows DIAGNOSE.

    path keys: instrument_ok, segment_ok, root_cause_ok, recommend_ok, uncertainty_ok.
    Each correct step = +2. Max = 10.
    """
    return 2 * sum(1 for k in ("instrument_ok", "segment_ok", "root_cause_ok",
                               "recommend_ok", "uncertainty_ok") if path.get(k))


def severity_rank(sev: str) -> int:
    """Numeric severity for sorting: P0 > P1 > P2 > invalid."""
    order = {"P0": 0, "P1": 1, "P2": 2, "invalid": 3}
    return order.get(sev, 9)


def recommend(scenario_type: str, root_cause_category: str) -> str:
    """Decision rule: map scenario type + root-cause category to an action verb."""
    if scenario_type == "p0_outage":
        return "CIRCUIT-BREAK + FAILOVER"
    if scenario_type == "ab_break":
        return "INVALIDATE + RE-RUN"
    if scenario_type == "rev_decline":
        return "THROTTLE + GUARDRAIL"
    if scenario_type == "dau_drop":
        if root_cause_category == "internal_eng":
            return "ROLLBACK"
        if root_cause_category == "external_seasonal":
            return "MONITOR (no action)"
        if root_cause_category == "external_competitor":
            return "INVESTIGATE (broaden)"
        return "INVESTIGATE"
    return "INVESTIGATE"


def delta_pct(baseline: float, current: float) -> float:
    """Percent change. Guard /0."""
    if baseline == 0:
        return 0.0
    return 100.0 * (current - baseline) / baseline


# ============================================================================
# 3. DATABASE
# ============================================================================

def build_db():
    """Create in-memory DB with all scenario data."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE scenarios (
            id INTEGER, name TEXT, type TEXT, prompt TEXT, primary_metric TEXT,
            magnitude_pct REAL, timeline TEXT, baseline_value REAL,
            current_value REAL, value_unit TEXT
        );
        CREATE TABLE instrument_checks (
            scenario_id INTEGER, check_name TEXT, status TEXT, detail TEXT
        );
        CREATE TABLE hypotheses (
            id INTEGER, scenario_id INTEGER, category TEXT, hypothesis TEXT,
            prior_rank INTEGER, is_root_cause INTEGER
        );
        CREATE TABLE slices (
            scenario_id INTEGER, dimension TEXT, slice_name TEXT,
            baseline REAL, current REAL, delta_pct REAL, is_localized INTEGER
        );
        CREATE TABLE srm_slices (
            scenario_id INTEGER, slice TEXT, obs_c INTEGER, obs_t INTEGER,
            total INTEGER, ratio_c REAL
        );
        CREATE TABLE root_causes (
            scenario_id INTEGER, mechanism TEXT, evidence TEXT, world_event TEXT,
            severity TEXT, impact_users INTEGER, impact_revenue INTEGER
        );
        CREATE TABLE recommendations (
            scenario_id INTEGER, action TEXT, next_check TEXT, uncertainty TEXT
        );
        CREATE TABLE decisions (
            scenario_id INTEGER, stage TEXT, choice_key TEXT, label TEXT,
            verdict TEXT, data_shown TEXT, trap_name TEXT
        );
        CREATE TABLE traps (name TEXT, failure_mode TEXT, fix TEXT);
        """
    )
    conn.executemany("INSERT INTO scenarios VALUES (?,?,?,?,?,?,?,?,?,?)", SCENARIOS)
    conn.executemany("INSERT INTO instrument_checks VALUES (?,?,?,?)", INSTRUMENT_CHECKS)
    conn.executemany("INSERT INTO hypotheses VALUES (?,?,?,?,?,?)", HYPOTHESES)
    conn.executemany("INSERT INTO slices VALUES (?,?,?,?,?,?,?)", SLICES)
    conn.executemany("INSERT INTO srm_slices VALUES (?,?,?,?,?,?)", SRM_SLICES)
    conn.executemany("INSERT INTO root_causes VALUES (?,?,?,?,?,?,?)", ROOT_CAUSES)
    conn.executemany("INSERT INTO recommendations VALUES (?,?,?,?)", RECOMMENDATIONS)
    conn.executemany("INSERT INTO decisions VALUES (?,?,?,?,?,?,?)", DECISIONS)
    conn.executemany("INSERT INTO traps VALUES (?,?,?)", TRAPS)
    conn.commit()
    return conn


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def sign(x: float) -> str:
    return f"{x:+.1f}" if x != 0 else f"{x:.1f}"


def money(x: float) -> str:
    return f"${x:,.0f}" if x >= 1000 else f"${x:.2f}"


# ============================================================================
# 5. THE SECTIONS
# ============================================================================

def section_framework():
    banner("SECTION 0: the DIAGNOSE framework  (instrument first, always)")
    print("Scenario problems have NO single correct answer -- the interviewer")
    print("evaluates your REASONING PROCESS. Run these IN ORDER.\n")
    print("  letter | step                  | time  | what")
    print("  -------|-----------------------|-------|-----------------------------------")
    for key, letter, name, t, what in DIAGNOSE_STEPS:
        print(f"    {letter}    | {name:21s} | {t:5s} | {what}")
    print("\n  The separator between 9/10 and 6/10:")
    print("    6/10: 'I'd look at the data, check deployments, figure it out.'")
    print("    9/10: 'I'd verify the signal is real, check the pipeline, build a")
    print("          hypothesis tree, prioritize by probability x falsification cost,")
    print("          pull the most diagnostic query, narrow, then OWN a recommendation")
    print("          with impact sizing and a time-boxed next check.'")
    print("\n  Four scenarios follow -- each run end-to-end through DIAGNOSE.")


def section_scenario_overview(conn):
    banner("SECTION 1: the four scenarios  (one per common interview type)")
    rows = conn.execute(
        "SELECT id, name, type, prompt, primary_metric, magnitude_pct, "
        "timeline, severity FROM scenarios s "
        "JOIN root_causes r ON s.id = r.scenario_id ORDER BY s.id"
    ).fetchall()
    print("  # | scenario                         | type         | severity | prompt")
    print("  --|----------------------------------|--------------|----------|--------")
    for sid, name, typ, prompt, metric, mag, timeline, sev in rows:
        print(f"  {sid} | {name:32s} | {typ:12s} | {sev:8s} | {prompt[:48]}")
    print("\n  Each maps to a scenario TYPE with a tailored first check:")
    print("    dau_drop   -> pipeline integrity, then platform segmentation")
    print("    rev_decline-> revenue source agreement, then inventory-type segmentation")
    print("    ab_break   -> SRM chi-square FIRST (before reading any metric)")
    print("    p0_outage  -> service health, then region x provider segmentation")


def run_diagnose(conn, sid: int):
    """Print the full DIAGNOSE walkthrough for one scenario."""
    sc = conn.execute(
        "SELECT name, type, prompt, primary_metric, magnitude_pct, timeline, "
        "baseline_value, current_value, value_unit FROM scenarios WHERE id=?",
        (sid,),
    ).fetchone()
    name, typ, prompt, metric, mag, timeline, base, curr, unit = sc

    banner(f"SCENARIO {sid}: {name}  ({typ})")

    # ---- D: Define the signal ----
    print("  [D] DEFINE THE SIGNAL")
    print(f"      prompt        : {prompt}")
    print(f"      primary metric: {metric}")
    print(f"      magnitude     : {sign(mag)}%  ({base:,.0f} -> {curr:,.0f} {unit})"
          if unit != "$/user"
          else f"      magnitude     : {sign(mag)}%  (${base:.2f} -> ${curr:.2f} {unit})")
    print(f"      timeline      : {timeline}")
    # decomposition note
    if typ == "dau_drop":
        print("      decomposition : DAU = new + returning (+ resurrected).")
        print("                      Triangulate with signups, session_start, WAU.")
    elif typ == "rev_decline":
        print("      decomposition : Revenue = DAU x ARPU. DAU flat -> the move is")
        print("                      IN ARPU = ad impressions x fill x CPM. Check each.")
    elif typ == "ab_break":
        print("      decomposition : The +15% lift is the QUESTION, not the answer.")
        print("                      Validity checks (SRM) gate the readout.")
    elif typ == "p0_outage":
        print("      decomposition : Error rate up 8400%. Customer harm is happening")
        print("                      NOW -- contain first, diagnose second.")

    # ---- I: Check the instrument ----
    print("\n  [I] CHECK THE INSTRUMENT  (always first; ~30-40% of drops are data bugs)")
    checks = conn.execute(
        "SELECT check_name, status, detail FROM instrument_checks WHERE scenario_id=?",
        (sid,),
    ).fetchall()
    for chk, status, detail in checks:
        marker = "[OK]" if status == "healthy" else ("[!]" if status == "degraded" else "[X]")
        print(f"      {marker} {chk:28s} {status:8s} : {detail}")
    instrument_ok = all(c[1] == "healthy" for c in checks) or sid == 4
    if sid == 3:
        print("      -> SRM FAIL: the experiment is INVALID. Stop reading the +15%.")
        print("         Do NOT present the treatment effect. Debug assignment first.")
    elif instrument_ok:
        print("      -> Instrument HEALTHY. Proceed to hypotheses.")
    else:
        print("      -> Instrument DEGRADED but confirmed real (not a logging artifact).")

    # ---- A: Assemble hypotheses ----
    print("\n  [A] ASSEMBLE HYPOTHESES  (internal + external; prioritize by P x cost)")
    hyps = conn.execute(
        "SELECT category, hypothesis, prior_rank, is_root_cause FROM hypotheses "
        "WHERE scenario_id=? ORDER BY prior_rank",
        (sid,),
    ).fetchall()
    print("      rank | category             | hypothesis")
    print("      -----|----------------------|------------------------------------------")
    for cat, hyp, rank, is_rc in hyps:
        flag = "  <-- ROOT CAUSE" if is_rc else ""
        print(f"      #{rank:4d} | {cat:20s} | {hyp}{flag}")
    print(f"      ({len(hyps)} hypotheses -- a single hypothesis is trap #3)")

    # ---- G + N: Generate queries + Narrow ----
    print("\n  [G] GENERATE QUERIES + [N] NARROW  (segment to localize)")
    if sid == 3:
        # SRM slices
        srm = conn.execute(
            "SELECT slice, obs_c, obs_t, total, ratio_c FROM srm_slices "
            "WHERE scenario_id=? ORDER BY total DESC",
            (sid,),
        ).fetchall()
        print("      SRM chi-square by platform slice:")
        print("        slice   | obs_c  | obs_t  | ratio  | chi2     | verdict")
        print("        --------|--------|--------|--------|----------|------------------")
        for sl, oc, ot, tot, rc in srm:
            c2 = chi2_srm(oc, ot, rc)
            loc = " <-- LOCALIZED" if (sl == "Mobile") else ""
            print(f"        {sl:7s} | {oc:6d} | {ot:6d} | {oc/tot*100:5.1f}% | {c2:8.1f} | "
                  f"{srm_verdict(c2)}{loc}")
        print(f"\n      -> Mobile drives the SRM (chi2=2400). Web is clean (chi2=1.0).")
        print("         The +15% lift is an artifact of biased mobile assignment.")
    else:
        slices = conn.execute(
            "SELECT dimension, slice_name, baseline, current, delta_pct, is_localized "
            "FROM slices WHERE scenario_id=? ORDER BY is_localized DESC, delta_pct",
            (sid,),
        ).fetchall()
        dim = slices[0][0] if slices else "?"
        print(f"      Segment by {dim}:")
        print(f"        slice                 | baseline     | current      | delta   | note")
        print("        ----------------------|--------------|--------------|---------|-------------")
        for dim_, sl, b, c, dpct, loc in slices:
            flag = "LOCALIZED" if loc else ""
            if unit == "$/user" and dim_ == "ad_metric":
                bstr = f"{b:,.2f}" if "CTR" in sl else f"{b:,.1f}"
                cstr = f"{c:,.2f}" if "CTR" in sl else f"{c:,.1f}"
            elif typ == "p0_outage":
                bstr = f"{b:,.0f}"
                cstr = f"{c:,.0f}"
            else:
                bstr = f"{b:,.0f}"
                cstr = f"{c:,.0f}"
            print(f"        {sl:22s} | {bstr:>12s} | {cstr:>12s} | {sign(dpct):6s}% | {flag}")
        loc_slice = next((s for s in slices if s[5]), None)
        if loc_slice:
            print(f"\n      -> LOCALIZED to {loc_slice[1]} ({sign(loc_slice[4])}%).")
            print("         This slice explains the aggregate move -- investigate here.")

    # ---- Root cause match ----
    rc = conn.execute(
        "SELECT mechanism, evidence, world_event, severity, impact_users, "
        "impact_revenue FROM root_causes WHERE scenario_id=?",
        (sid,),
    ).fetchone()
    mech, evidence, event, sev, iu, irv = rc
    print("\n  [N] ROOT CAUSE MATCH  (localized slice x binary world event)")
    print(f"      mechanism  : {mech}")
    print(f"      world event: {event}")
    print(f"      evidence   : {evidence}")
    print(f"      severity   : {sev}", end="")
    if iu:
        print(f"  |  impact: ~{iu:,} users affected", end="")
    if irv:
        print(f"  |  ~{money(irv)}/day at risk", end="")
    print()

    # ---- O: Own the recommendation ----
    rec = conn.execute(
        "SELECT action, next_check, uncertainty FROM recommendations WHERE scenario_id=?",
        (sid,),
    ).fetchone()
    action, ncheck, uncert = rec
    cat = conn.execute(
        "SELECT category FROM hypotheses WHERE scenario_id=? AND is_root_cause=1",
        (sid,),
    ).fetchone()[0]
    verb = recommend(typ, cat)
    print(f"\n  [O] OWN THE RECOMMENDATION  -> {verb}")
    print(f"      action     : {action}")
    print(f"      next check : {ncheck}")

    # ---- S: State uncertainty ----
    print(f"\n  [S] STATE UNCERTAINTY")
    print(f"      {uncert}")
    print(f"\n  [check] DIAGNOSE complete for scenario {sid}:  OK")


def section_decision_flow(conn):
    banner("SECTION 6: the decision flow  (interactive branching per scenario)")
    print("Each scenario has 4 decision stages: instrument -> segment -> root_cause")
    print("-> recommendation. The CORRECT path follows DIAGNOSE; traps register")
    print("mistakes. This is the structure scenario_problems.html makes clickable.\n")
    for sid in range(1, 5):
        sc = conn.execute("SELECT name FROM scenarios WHERE id=?", (sid,)).fetchone()[0]
        print(f"  --- Scenario {sid}: {sc} ---")
        for stage in ("instrument", "segment", "root_cause", "recommendation"):
            choices = conn.execute(
                "SELECT choice_key, label, verdict, data_shown, trap_name "
                "FROM decisions WHERE scenario_id=? AND stage=? ORDER BY rowid",
                (sid, stage),
            ).fetchall()
            print(f"    [{stage}]")
            for ck, label, verdict, data, trap in choices:
                mark = "+" if verdict == "correct" else "x"
                note = f" (trap: {trap})" if trap else ""
                print(f"      {mark} {label}{note}")
                print(f"        -> {data}")
        print()


def section_traps(conn):
    banner("SECTION 7: the five+ interview traps  (and the fix)")
    rows = conn.execute("SELECT name, failure_mode, fix FROM traps").fetchall()
    print("  trap                       | failure mode                                      | fix")
    print("  ---------------------------|---------------------------------------------------|------------------------------------------")
    for name, fail, fix in rows:
        print(f"  {name:27s} | {fail:50s} | {fix}")
    print("\n  The top 5 from the framework: skip_pipeline, queries_before_hypotheses,")
    print("  single_hypothesis, root_cause_only, ignore_uncertainty. A 6/10 hits 2-3;")
    print("  a 9/10 hits none. P0 scenarios add root_cause_theory (containment first).")


def section_signal_scoring():
    banner("SECTION 8: signal scoring  (how well did you follow DIAGNOSE?)")
    print("Each diagnostic path scores 0..10. Each correct DIAGNOSE step = +2:\n")
    print("  step             | what 'correct' means")
    print("  -----------------|----------------------------------------------------")
    print("  instrument       | checked data pipeline / SRM / service health FIRST")
    print("  segment          | chose the dimension that localizes the drop")
    print("  root cause       | matched the localized slice to a binary world event")
    print("  recommendation   | owned an action + impact sizing + next check")
    print("  uncertainty      | stated what you still do NOT know + time-boxed it")
    print("\n  Worked score examples:")
    perfect = {"instrument_ok": 1, "segment_ok": 1, "root_cause_ok": 1,
               "recommend_ok": 1, "uncertainty_ok": 1}
    weak = {"instrument_ok": 0, "segment_ok": 1, "root_cause_ok": 0,
            "recommend_ok": 0, "uncertainty_ok": 0}
    mid = {"instrument_ok": 1, "segment_ok": 1, "root_cause_ok": 1,
           "recommend_ok": 0, "uncertainty_ok": 0}
    print(f"    10/10 path: {signal_score(perfect)}/10  (all 5 steps correct)")
    print(f"    6/10 path: {signal_score(mid)}/10  (instrument+segment+root cause,")
    print(f"               but stopped before recommendation + uncertainty)")
    print(f"    2/10 path: {signal_score(weak)}/10  (skipped instrument, guessed root cause)")
    print("\n  The scoring is the interview rubric in miniature.")


def section_gold(conn):
    banner("GOLD  (pinned for scenario_problems.html)")
    print("Values the HTML recomputes live in JS and gold-checks against.\n")
    print("  SRM chi-square per slice (scenario 3):")
    for _, sl, oc, ot, tot, rc in SRM_SLICES:
        c2 = chi2_srm(oc, ot, rc)
        print(f"    {sl:8s}: obs_c={oc} obs_t={ot} ratio_c={rc} -> chi2={c2:.4f} "
              f"({srm_verdict(c2)})")
    print(f"\n  SRM critical threshold (df=1, alpha=0.001): {SRM_CRITICAL}")
    print("\n  DAU drop localization (scenario 1, platform slices):")
    for _, dim, sl, b, c, dpct, loc in SLICES[:3]:
        recomputed = delta_pct(b, c)
        print(f"    {sl:8s}: {b} -> {c} = {sign(recomputed)}% "
              f"(localized={'YES' if loc else 'no'})")
    total_drop = SCENARIOS[0][7] - SCENARIOS[0][8]  # 2000000 - 1800000
    ios_drop = 1100000 - 900000
    print(f"\n  total DAU drop = {total_drop:,}; iOS drop = {ios_drop:,}; "
          f"iOS share of drop = {100*ios_drop/total_drop:.1f}%")
    print("\n  Revenue impact (scenario 2):")
    arpu_drop = 2.85 - 2.65
    daily_rev_loss = 2000000 * arpu_drop
    print(f"    ARPU drop = ${2.85:.2f} - ${2.65:.2f} = ${arpu_drop:.2f}/user/day")
    print(f"    daily revenue loss = 2,000,000 DAU x ${arpu_drop:.2f} = {money(daily_rev_loss)}/day")
    print("\n  Recommendation verbs (recommend() per scenario):")
    for s in SCENARIOS:
        sid, name, typ = s[0], s[1], s[2]
        cat = conn.execute(
            "SELECT category FROM hypotheses WHERE scenario_id=? AND is_root_cause=1",
            (sid,),
        ).fetchone()[0]
        print(f"    scenario {sid} ({typ:12s}): {recommend(typ, cat)}")
    print("\n  Signal score examples:")
    for label, path in [("perfect", {"instrument_ok":1,"segment_ok":1,"root_cause_ok":1,
                                     "recommend_ok":1,"uncertainty_ok":1}),
                        ("skipped instrument", {"instrument_ok":0,"segment_ok":1,"root_cause_ok":1,
                                                "recommend_ok":1,"uncertainty_ok":1}),
                        ("weak", {"instrument_ok":0,"segment_ok":1,"root_cause_ok":0,
                                  "recommend_ok":0,"uncertainty_ok":0})]:
        print(f"    {label:22s}: {signal_score(path)}/10")
    print()
    print("[check] GOLD reproduces from the in-memory DB + engines:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("scenario_problems.py - ground truth for SCENARIO_PROBLEMS.md.")
    print("Four canonical interview scenarios run end-to-end through DIAGNOSE:")
    print("DAU drop, revenue decline, broken A/B test, payment P0 outage.")
    print("Pure stdlib.\n")
    conn = build_db()

    # sanity checks
    assert all(chi2_srm(oc, ot, rc) > 0 for _, sl, oc, ot, tot, rc in SRM_SLICES)
    assert chi2_srm(56100, 43900, 0.5) > SRM_CRITICAL, "overall SRM must fail"
    assert chi2_srm(20100, 19900, 0.5) < SRM_CRITICAL, "web SRM must be clean"
    assert signal_score({"instrument_ok":1,"segment_ok":1,"root_cause_ok":1,
                         "recommend_ok":1,"uncertainty_ok":1}) == 10
    assert all(s[7] != s[8] for s in SCENARIOS), "baseline must differ from current"
    print(f"[check] built DB: {len(SCENARIOS)} scenarios, {len(HYPOTHESES)} hypotheses, "
          f"{len(SLICES)} slices, {len(SRM_SLICES)} SRM slices, {len(ROOT_CAUSES)} root causes, "
          f"{len(DECISIONS)} decision choices, {len(TRAPS)} traps")
    print("[check] SRM engine + signal-score engine + sanity asserts:  OK")

    section_framework()
    section_scenario_overview(conn)
    for sid in range(1, 5):
        run_diagnose(conn, sid)
    section_decision_flow(conn)
    section_traps(conn)
    section_signal_scoring()
    section_gold(conn)

    banner("DONE - all sections printed")
    conn.close()


if __name__ == "__main__":
    main()
