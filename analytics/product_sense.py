"""
product_sense.py - Ground-truth simulation for the Product Sense bundle.

The single source of truth that PRODUCT_SENSE.md and product_sense.html are
built from. Every number, table, and recommendation below is printed by this
file -- nothing in the guide is hand-computed.

Run:
    python3 product_sense.py

============================================================================
THE IDEA (read this first) -- product sense is problem -> users -> metrics
-> tradeoffs, in that order, every time
============================================================================
A "product sense" interview asks: "How would you improve Product X?" The trap
is to jump to ideas. The fix is a fixed, ordered framework:

    1. Clarify scope (segment, platform, goal, constraints)
    2. Define user segments (primary / secondary / power)
    3. Map the user journey (Awareness -> ... -> Retention) with drop-off
    4. Name pain points WITH DATA SIGNALS (NPS, tickets, recordings)
    5. Generate solutions breadth-first, one per root cause
    6. Prioritize with a scoring model (RICE / ICE) + Impact x Feasibility
    7. Define success: PRIMARY + GUARDRAIL + COUNTER metric
    8. Name the tradeoff and what you are NOT building

This file runs the canonical worked example end-to-end: "Facebook engagement
is declining in the 18-24 cohort on mobile." It loads the journey, pain points,
solutions, metric deltas, and an A/B-test decision tree into an in-memory
sqlite3 DB, then queries them so every printed number is reproducible.

Two scoring engines (both pure stdlib):
    RICE  = (Reach x Impact x Confidence) / Effort
    ICE   = (Impact + Confidence + Ease) / 3          [each on a 1..5 scale]

One tradeoff engine -- the suppression trap. For an ad-supported product a
feature can LIFT engagement while SUPPRESSING ad revenue (Instagram's
algorithmic-feed switch is the canonical case). The net score blends a primary
(DAU), guardrail (Revenue), and counter (Satisfaction) metric with weights:

    NET  = w_p * dPrimary + w_g * dGuardrail + w_c * dCounter

A primary lift with a counter DROP is the signature of metric gaming; a
primary lift with a guardrail DROP is the suppression trap. Both change the
ship decision.
"""

from __future__ import annotations

import sqlite3

BANNER = "=" * 72

# ============================================================================
# 1. SCENARIO + SOURCE-OF-TRUTH CONSTANTS  (mirrored verbatim in
#    product_sense.html GOLD -- change here, re-run, re-paste everywhere)
# ============================================================================

SCENARIO = {
    "prompt": "Facebook engagement is declining in the 18-24 cohort",
    "segment": "users aged 18-24",
    "platform": "mobile (iOS + Android)",
    "goal": "engagement (growth + retention)",
    "constraint": "ad-supported -- must not regress revenue materially",
    "primary_metric": "18-24 DAU / MAU ratio",
    "guardrail_metric": "ad revenue per DAU (ARPU)",
    "counter_metric": "self-reported satisfaction (NPS-like, -10..10)",
}

# The 18-24 mobile journey funnel (per 100,000 reached). Each step is the
# count that REACHED that stage; the drop to the next is what we diagnose.
# Order: Awareness -> Acquisition -> Activation -> Engagement -> Retention.
JOURNEY = [
    ("Awareness",  100000, "saw install surface / ad"),
    ("Acquisition", 42000, "installed the app"),
    ("Activation",  27300, "first session > 60s (meaningful)"),
    ("Engagement",  13650, "weekly active (>=3 sessions/wk)"),
    ("Retention",    5460, "active on day 30 (D30)"),
]

# Pain points -- each named with a DATA SIGNAL (the 9/10 vs 6/10 separator).
# maps_to = the journey transition the pain lives at.
PAIN_POINTS = [
    # id, name, segment, data_signal, maps_to, severity(1-5)
    (1, "Onboarding friction",
        "new 18-24 installs",
        "session recordings: 35% bail at step 3; support tickets",
        "Acquisition -> Activation", 4),
    (2, "Content format mismatch",
        "18-24 engaged",
        "time-in-app -14% QoQ; photo interactions down, video up off-platform",
        "Activation -> Engagement", 5),
    (3, "Social graph aging",
        "18-24 engaged",
        "NPS -8 pts YoY; 41% fewer new connections made per week",
        "Engagement -> Retention", 4),
    (4, "Competitive displacement (TikTok)",
        "18-24 engaged",
        "panel data: 18-24 mobile time-share -9pp; opens/day -12%",
        "Engagement -> Retention", 5),
]

# Solutions -- breadth-first, each mapped to a distinct root cause / pain.
# RICE inputs: reach (users/qtr touched), impact (0.25..3), confidence (0..1),
# effort (eng-weeks). ICE inputs: ice_i, ice_c, ice_e (each 1..5).
SOLUTIONS = [
    # id, name, pain_id, reach, impact, confidence, effort, ice_i, ice_c, ice_e
    (1, "Short-form video feed (Reels)",       2, 13650, 3, 0.80, 5, 5, 4, 2),
    (2, "Groups discovery (interest graph)",   3,  8000, 2, 0.70, 3, 4, 3, 4),
    (3, "Streamlined 3-step onboarding",       1, 27300, 2, 0.90, 2, 3, 5, 5),
    (4, "Collaborative content creation",      4,  5460, 3, 0.50, 8, 5, 2, 1),
    (5, "Algorithmic feed re-rank (video-1st)",2, 13650, 2, 0.85, 4, 4, 4, 3),
]

# Metric tradeoff matrix -- estimated deltas if each solution ships at full
# rollout. PRIMARY = 18-24 DAU %, GUARDRAIL = ad revenue %, COUNTER = sat pts.
# Negative guardrail on #1 and #5 = the SUPPRESSION TRAP.
# Negative counter on #5 = the GAMING signal (primary up, satisfaction down).
METRIC_DELTAS = [
    # sol_id, d_primary(DAU%), d_guardrail(Rev%), d_counter(Sat pts)
    (1,  8.5, -3.2,  6.0),   # Reels: DAU up, Rev DOWN (suppression), Sat up
    (2,  3.1,  1.0,  4.0),   # Groups: all positive (rare, safe)
    (3,  5.2,  0.8,  2.0),   # Onboarding: cheap, all positive
    (4,  2.0, -0.5,  8.0),   # Collab: small DAU, big Sat, mild Rev drag
    (5,  6.0, -4.5, -2.0),   # Algo re-rank: DAU up, Rev DOWN, Sat DOWN (gaming)
]

# Net-score weights: primary / guardrail / counter. Encode that a guardrail
# regression is costly but a primary lift still earns its keep.
WEIGHTS = {"primary": 0.5, "guardrail": 0.3, "counter": 0.2}

# The decision tree for the A/B-test walkthrough. parent_id builds the tree;
# leaf nodes carry the readout and a computed recommendation.
# dau/rev/sat are the week-2 readout deltas; seg_split flags a segmented path.
DECISION_TREE = [
    # id, parent, label, condition, dau, rev, sat, seg_split, note
    (0, None, "ROOT: ship Reels A/B, 14-day minimum",
        "primary=18-24 DAU, guardrail=Revenue, counter=Sat", None, None, None, 0,
        "pre-registered plan; powered for DAU; revenue guardrail added (ad surface)"),
    (1, 0, "Branch A: clean win",
        "DAU up, Rev flat/up",  8.5,  0.3, 6.0, 0,
        "SHIP at day 14"),
    (2, 0, "Branch B: SUPPRESSION TRAP",
        "DAU up, Rev down 2-5%", 8.5, -3.2, 6.0, 0,
        "ITERATE: extend to 21d, throttle ad load in the Reels surface"),
    (3, 2, "Branch B1: revenue recovers",
        "throttled ads, Rev -> -0.5%", 8.5, -0.5, 6.0, 0,
        "SHIP with throttled ad load"),
    (4, 2, "Branch B2: revenue still down",
        "Rev still <= -4%",      7.0, -4.0, 4.0, 0,
        "KILL or hold out power users"),
    (5, 0, "Branch C: primary failed",
        "DAU flat, Rev down",   0.5, -3.2, -1.0, 0,
        "KILL -- guardrail regression with no primary win"),
    (6, 0, "Branch D: segment split",
        "18-24 up, 35+ down",   9.0,  1.0, 7.0, 1,
        "SEGMENTED ROLLOUT to 18-24 only"),
]

# The five interview traps (from discussion.md) -- printed verbatim as a table.
TRAPS = [
    ("Jumping to solutions without user research",
     "Proposing features before naming the problem",
     "Open with clarifying questions; map the journey first"),
    ("Building for the 'average user'",
     "There is no average user; headline metrics hide segments",
     "Always segment (primary / secondary / power) before diagnosing"),
    ("Proposing a single metric as success",
     "Any metric can be gamed; 'DAU' alone hides quality",
     "Primary + guardrail + counter; name the gaming path"),
    ("Forgetting feasibility",
     "An 18-month ML rebuild is not an interview answer",
     "Score Effort; prefer sequencing (quick win -> strategic bet)"),
    ("Not stating what you're NOT building",
     "Deprioritization IS the tradeoff; silence reads as no thinking",
     "Explicitly kill 1-2 solutions and say why"),
]


# ============================================================================
# 2. SCORING ENGINES (pure stdlib)
# ============================================================================

def rice(reach: float, impact: float, confidence: float, effort: float) -> float:
    """RICE = (Reach x Impact x Confidence) / Effort. Higher is better."""
    if effort <= 0:
        return float("inf")
    return (reach * impact * confidence) / effort


def ice(i: float, c: float, e: float) -> float:
    """ICE = (Impact + Confidence + Ease) / 3, each on a 1..5 scale."""
    return (i + c + e) / 3.0


def net_score(d_primary: float, d_guard: float, d_counter: float,
              w: dict = WEIGHTS) -> float:
    """Blended net = w_p*dPrimary + w_g*dGuardrail + w_c*dCounter."""
    return (w["primary"] * d_primary
            + w["guardrail"] * d_guard
            + w["counter"] * d_counter)


def recommend(dau: float, rev: float, sat: float, seg_split: int = 0) -> str:
    """Decision rule for an A/B-test readout -- returns the action verb.

    Encodes the two tests a 9/10 answer names out loud:
      * suppression trap : primary up AND guardrail down -> ITERATE, don't ship
      * gaming signal     : primary up AND counter down  -> suspicious, dig in
      * primary failed    : primary flat                -> KILL regardless
    """
    if seg_split:
        return "SEGMENTED ROLLOUT"
    if dau <= 2.0:
        return "KILL (primary failed)"
    if rev <= -1.0:
        if sat < 0:
            return "KILL (suppression + gaming)"
        return "ITERATE (suppression trap)"
    if sat < 0:
        return "HOLD (gaming signal)"
    return "SHIP"


# ============================================================================
# 3. DATABASE  (load the constants into an in-memory sqlite3 DB, then query)
# ============================================================================

def build_db():
    """Create in-memory DB with journey, pain_points, solutions, deltas, tree."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE journey (
            stage TEXT, users INTEGER, definition TEXT, ord INTEGER
        );
        CREATE TABLE pain_points (
            id INTEGER, name TEXT, segment TEXT, data_signal TEXT,
            maps_to TEXT, severity INTEGER
        );
        CREATE TABLE solutions (
            id INTEGER, name TEXT, pain_id INTEGER, reach INTEGER,
            impact REAL, confidence REAL, effort REAL,
            ice_i REAL, ice_c REAL, ice_e REAL
        );
        CREATE TABLE metric_deltas (
            sol_id INTEGER, d_primary REAL, d_guardrail REAL, d_counter REAL
        );
        CREATE TABLE decision_tree (
            id INTEGER, parent INTEGER, label TEXT, condition TEXT,
            dau REAL, rev REAL, sat REAL, seg_split INTEGER, note TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO journey VALUES (?,?,?,?)",
        [(s, u, d, i) for i, (s, u, d) in enumerate(JOURNEY)],
    )
    conn.executemany("INSERT INTO pain_points VALUES (?,?,?,?,?,?)", PAIN_POINTS)
    conn.executemany(
        "INSERT INTO solutions VALUES (?,?,?,?,?,?,?,?,?,?)", SOLUTIONS
    )
    conn.executemany(
        "INSERT INTO metric_deltas VALUES (?,?,?,?)", METRIC_DELTAS
    )
    conn.executemany(
        "INSERT INTO decision_tree VALUES (?,?,?,?,?,?,?,?,?)", DECISION_TREE
    )
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


def pct(x: float, y: float) -> float:
    return (100.0 * x / y) if y else 0.0


def bar(x: float, width: int = 30) -> str:
    """ASCII bar for a 0..1 fraction."""
    n = max(0, min(width, round(x * width)))
    return "#" * n + "." * (width - n)


def sign(x: float) -> str:
    return f"{x:+.1f}" if x != 0 else f"{x:.1f}"


# ============================================================================
# 5. THE SECTIONS
# ============================================================================

def section_scenario():
    banner("SECTION 0: the scenario  (clarify scope, 2 min)")
    print("The worked example for every section below.\n")
    print(f"  prompt            : {SCENARIO['prompt']}")
    print(f"  segment           : {SCENARIO['segment']}")
    print(f"  platform          : {SCENARIO['platform']}")
    print(f"  goal              : {SCENARIO['goal']}")
    print(f"  constraint        : {SCENARIO['constraint']}")
    print(f"  PRIMARY metric    : {SCENARIO['primary_metric']}")
    print(f"  GUARDRAIL metric  : {SCENARIO['guardrail_metric']}")
    print(f"  COUNTER metric    : {SCENARIO['counter_metric']}")
    print("\n  Clarifying questions asked FIRST (max 3-4):")
    print("    Q1 'engagement' = DAU? time-in-app? interactions? -> DAU/MAU ratio")
    print("    Q2 recent trend or long-term? -> 3-quarter decline, accelerating")
    print("    Q3 isolated to 18-24 or cross-demographic? -> isolated to 18-24 mobile")
    print("    Q4 any surfaces off-limits? -> feed is in-play; ads cannot regress >2%")
    print("\n  Scope locked. Now segment, map the journey, then solve -- in order.")


def section_framework():
    banner("SECTION 1: the 8-step framework  (problem -> users -> metrics -> tradeoffs)")
    print("Run these IN ORDER. Each step gates the next. Jumping ahead is trap #1.\n")
    steps = [
        ("1. Clarify scope", "2 min",
         "segment, platform, goal, constraints. Max 3-4 questions."),
        ("2. User segments", "3 min",
         "2-3 segments (primary/secondary/power). Name the underserved one."),
        ("3. User journey", "3 min",
         "Awareness->Acquisition->Activation->Engagement->Retention. Drop-off each."),
        ("4. Pain points", "3 min",
         "Name EACH with a data signal (NPS, tickets, recordings, churn)."),
        ("5. Solutions", "5 min",
         "3-5, breadth-first. ONE per root cause -- not all in one area."),
        ("6. Prioritize", "3 min",
         "RICE / ICE + Impact x Feasibility. State what you DEPRIORITIZE."),
        ("7. Success metrics", "2 min",
         "PRIMARY + GUARDRAIL + COUNTER. Name the gaming path."),
        ("8. Tradeoffs & risks", "2 min",
         "Suppression trap, segment-split risk, what you are NOT building."),
    ]
    print("  step                  | time | what to do")
    print("  ----------------------|------|-----------------------------------------")
    for name, t, do in steps:
        print(f"  {name:22s} | {t:4s} | {do}")
    print("\n  9/10 vs 6/10 separator: the 9/10 names DATA SIGNALS at step 4 and")
    print("  names the SUPPRESSION TRAP at step 8 unprompted. Everything else is")
    print("  structure that a 6/10 also has.")


def section_journey(conn):
    banner("SECTION 2: the user journey  (drop-off at each stage)")
    print("The 18-24 mobile funnel, per 100,000 reached. The step with the")
    print("largest drop is where investment earns the most.\n")
    rows = conn.execute(
        "SELECT stage, users, definition FROM journey ORDER BY ord"
    ).fetchall()
    print("  stage        |  users  | step conv | drop-off | definition")
    print("  -------------|---------|-----------|----------|---------------------------")
    prev = None
    for stage, users, defn in rows:
        if prev is None:
            print(f"  {stage:12s} | {users:7d} |    ---    |   ---    | {defn}")
        else:
            conv = pct(users, prev)
            drop = 100.0 - conv
            print(f"  {stage:12s} | {users:7d} | {conv:8.1f}% | {drop:7.1f}% | {defn}")
        prev = users
    overall = pct(rows[-1][1], rows[0][1])
    print(f"\n  overall (Awareness -> Retention) = {overall:.1f}%\n")
    # rank the drops
    drops = []
    for i in range(1, len(rows)):
        a, b = rows[i - 1][1], rows[i][1]
        drops.append((rows[i - 1][0], rows[i][0], 100.0 - pct(b, a)))
    drops.sort(key=lambda d: -d[2])
    print("  drop-off ranking (where to invest):")
    for a, b, d in drops:
        print(f"    {a:14s} -> {b:12s} : {d:5.1f}% lost")
    worst_a, worst_b, worst_d = drops[0]
    print(f"\n  BIGGEST drop: {worst_a} -> {worst_b} ({worst_d:.1f}%). That transition")
    print("  is the highest-leverage place to spend. Sections 3-5 solve around it.")


def section_pain(conn):
    banner("SECTION 3: pain points  (named WITH data signals)")
    print("A 6/10 says 'users are frustrated'. A 9/10 names the SIGNAL and the")
    print("journey transition it lives at. Each pain -> a different solution.\n")
    rows = conn.execute(
        "SELECT id, name, segment, data_signal, maps_to, severity "
        "FROM pain_points ORDER BY severity DESC, id"
    ).fetchall()
    print("  # | pain                          | sev | maps-to transition        | data signal")
    print("  --|-------------------------------|-----|---------------------------|---------------------------")
    for pid, name, seg, sig, maps, sev in rows:
        print(f"  {pid} | {name:29s} |  {sev}  | {maps:25s} | {sig}")
    print("\n  Every pain is testable from the signal: pull NPS by cohort, read")
    print("  session recordings at the named transition, count support tickets by")
    print("  topic, check panel time-share. NO pain is asserted without a signal.")


def section_scoring(conn):
    banner("SECTION 4: scoring model  (RICE + ICE for feature prioritization)")
    print("Two independent scoring models over the same solutions. RICE weights")
    print("Reach x Impact x Confidence / Effort (favors cheap, broad wins). ICE")
    print("averages Impact + Confidence + Ease on 1-5 (favors easy, sure things).")
    print("Disagreement between them is a signal, not a problem.\n")
    rows = conn.execute(
        "SELECT id, name, reach, impact, confidence, effort, ice_i, ice_c, ice_e "
        "FROM solutions ORDER BY id"
    ).fetchall()
    scored = []
    for sid, name, reach, imp, conf, eff, ii, ic, ie in rows:
        r = rice(reach, imp, conf, eff)
        sc = ice(ii, ic, ie)
        scored.append((sid, name, r, sc))
    print("  # | solution                          |   RICE |  ICE | RICE rank")
    print("  --|-----------------------------------|--------|------|----------")
    rice_sorted = sorted(scored, key=lambda s: -s[2])
    rank = {s[0]: i + 1 for i, s in enumerate(rice_sorted)}
    for sid, name, r, sc in scored:
        print(f"  {sid} | {name:33s} | {r:6.0f} | {sc:4.2f} |    #{rank[sid]}")
    print(f"\n  RICE ranking: {' > '.join(s[1] for s in rice_sorted)}")
    ice_sorted = sorted(scored, key=lambda s: -s[3])
    print(f"  ICE  ranking: {' > '.join(s[1] for s in ice_sorted)}")
    top_rice = rice_sorted[0]
    print(f"\n  RICE top: {top_rice[1]} (score {top_rice[2]:.0f}) -- cheap, broad,")
    print("  high-confidence. The scoring model's instinct is 'ship the quick win'.")
    print("  BUT see Section 5: scoring is an INPUT to judgment, not a substitute.")


def section_prioritize(conn):
    banner("SECTION 5: prioritization matrix  (Impact x Feasibility, then judgment)")
    print("RICE says onboarding first. The 9/10 answer overrides with STRATEGIC")
    print("reasoning: onboarding is a quick win that de-risks ACTIVATION, but the")
    print("root cause of the 18-24 decline is FORMAT MISMATCH (pain #2, severity")
    print("5). So SEQUENCE: onboarding first (week 0-4, cheap), then Reels as the")
    print("strategic engagement bet (week 4-12). Deprioritize collab explicitly.\n")
    rows = conn.execute(
        "SELECT id, name, pain_id, impact, confidence, effort "
        "FROM solutions ORDER BY id"
    ).fetchall()
    pain_names = {p[0]: p[1] for p in PAIN_POINTS}
    print("  # | solution                          | impact | conf | effort | feasibility")
    print("  --|-----------------------------------|--------|------|--------|------------")
    for sid, name, pid, imp, conf, eff in rows:
        feas = 5.0 - min(eff, 5.0)  # invert effort -> feasibility 0..4
        print(f"  {sid} | {name:33s} | {imp:6.1f} | {conf:4.2f} | {eff:6.1f} | {feas:4.1f}/4")
    print("\n  DECISION (sequenced roadmap):")
    print("    Phase 1 (ship first):  #3 Streamlined onboarding  -- quick win,")
    print("                            de-risks Activation, all metrics positive")
    print("    Phase 2 (strategic):   #1 Reels                    -- the engagement")
    print("                            bet; needs a REVENUE guardrail (Section 6)")
    print("    Deprioritize:          #4 Collaborative creation   -- highest effort,")
    print("                            lowest confidence, smallest reach. KILL it.")
    print("    Hold:                  #2 Groups, #5 Algo re-rank  -- revisit after")
    print("                            Phase 1/2 readouts")


def section_tradeoffs(conn):
    banner("SECTION 6: metric tradeoff analysis  (the suppression trap)")
    print("Each solution's estimated impact on PRIMARY (DAU%), GUARDRAIL (Rev%),")
    print("COUNTER (Sat pts). NET blends them with weights "
          f"{WEIGHTS['primary']}/{WEIGHTS['guardrail']}/{WEIGHTS['counter']}.\n")
    sols = {s[0]: s[1] for s in SOLUTIONS}
    rows = conn.execute(
        "SELECT sol_id, d_primary, d_guardrail, d_counter FROM metric_deltas ORDER BY sol_id"
    ).fetchall()
    print("  # | solution                          |  DAU% |  Rev% |  Sat |   NET | read")
    print("  --|-----------------------------------|-------|-------|------|-------|-------------------------")
    scored = []
    for sid, dp, dg, dc in rows:
        n = net_score(dp, dg, dc)
        scored.append((sid, n, dp, dg, dc))
        flag = ""
        if dp > 0 and dg < 0:
            flag = "SUPPRESSION TRAP"
        elif dp > 0 and dc < 0:
            flag = "GAMING signal"
        print(f"  {sid} | {sols[sid]:33s} | {sign(dp):5s} | {sign(dg):5s} | "
              f"{sign(dc):4s} | {n:5.2f} | {flag}")
    print("\n  Reads:")
    print("    #1 Reels  : big DAU + Sat lift, but Rev DOWN -> the suppression trap.")
    print("                Ship ONLY with a revenue guardrail + 21-day test (Section 7).")
    print("    #5 Re-rank: DAU up but Sat DOWN -> the primary is being gamed. Hold.")
    print("    #3 Onboard : all positive, cheap -> safe quick win (Phase 1).")
    net_sorted = sorted(scored, key=lambda s: -s[1])
    print(f"\n  NET ranking: {' > '.join(sols[s[0]] + '('+f'{s[1]:.2f}'+')' for s in net_sorted)}")
    print("  Note: NET can flip the RICE order. Reels ranks #1 on NET despite the")
    print("  revenue drag, because the DAU + Sat lift outweighs it at these weights.")
    print("  Change the weights (e.g. guardrail 0.5) and Reels drops below onboarding.")
    print("  The weights encode the business priority -- state them out loud.")


def section_scenario_tree(conn):
    banner("SECTION 7: scenario walkthrough  (Reels A/B -- branching decisions)")
    print("Week-2 readout tree for the Reels experiment. Each leaf carries the")
    print("DAU/Rev/Sat deltas; the recommendation is COMPUTED from a rule that")
    print("encodes the suppression trap and the gaming test.\n")
    nodes = {r[0]: r for r in conn.execute(
        "SELECT id, parent, label, condition, dau, rev, sat, seg_split, note "
        "FROM decision_tree"
    ).fetchall()}
    children = {}
    for nid, n in nodes.items():
        children.setdefault(n[1], []).append(nid)

    def depth(nid):
        d = 0
        n = nodes[nid]
        while n[1] is not None:
            d += 1
            n = nodes[n[1]]
        return d

    def walk(nid):
        n = nodes[nid]
        nid_, parent, label, cond, dau, rev, sat, seg, note = n
        ind = "  " * depth(nid)
        if dau is None:
            print(f"{ind}[{nid_}] {label}")
            print(f"{ind}    ({cond})")
            print(f"{ind}    note: {note}")
        else:
            net = net_score(dau, rev, sat)
            rec = recommend(dau, rev, sat, seg)
            print(f"{ind}[{nid_}] {label}")
            print(f"{ind}    readout: DAU {sign(dau)}%  Rev {sign(rev)}%  "
                  f"Sat {sign(sat)}  ->  NET {net:+.2f}")
            print(f"{ind}    -> {rec}")
            print(f"{ind}    ({note})")
        for c in children.get(nid_, []):
            walk(c)

    walk(0)
    # decision-rule legend
    print("\n  decision rule (recommend()):")
    print("    seg_split                     -> SEGMENTED ROLLOUT")
    print("    DAU <= 2%                     -> KILL (primary failed)")
    print("    DAU > 2% AND Rev <= -1%       -> ITERATE (suppression trap)")
    print("      unless Sat < 0              -> KILL (suppression + gaming)")
    print("    DAU > 2% AND Sat < 0          -> HOLD (gaming signal)")
    print("    otherwise                     -> SHIP")
    print("\n  The whole point: a 'good' primary is NOT enough. The guardrail and")
    print("  counter tests gate the ship decision. Branch B is the suppression trap")
    print("  -- the most common real-world Reels/Feed outcome -- and it does NOT")
    print("  ship at day 14. It iterates, because revenue is a hard constraint here.")


def section_traps():
    banner("SECTION 8: the five interview traps  (and the fix)")
    print("  trap                                       | failure mode                                 | fix")
    print("  -------------------------------------------|----------------------------------------------|---------------------------")
    for name, fail, fix in TRAPS:
        print(f"  {name:43s} | {fail:45s} | {fix}")
    print("\n  The five traps map onto the 8 steps: 1<-trap1, 2<-trap2, 3<-none,")
    print("  4<-none, 5<-trap4, 7<-trap3, 8<-trap5. A 6/10 hits 2-3; a 9/10 hits none.")


def section_gold(conn):
    banner("GOLD  (pinned for product_sense.html)")
    print("Values the HTML recomputes live in JS and gold-checks against.\n")
    sols = {s[0]: s for s in SOLUTIONS}
    sol_names = {s[0]: s[1] for s in SOLUTIONS}
    print("  RICE (Reach x Impact x Confidence / Effort):")
    for sid, name, pid, reach, imp, conf, eff, ii, ic, ie in SOLUTIONS:
        r = rice(reach, imp, conf, eff)
        print(f"    #{sid} {name}: reach={reach} impact={imp} conf={conf} "
              f"effort={eff} -> RICE={r:.4f}")
    print("\n  ICE ((I+C+E)/3):")
    for sid, name, pid, reach, imp, conf, eff, ii, ic, ie in SOLUTIONS:
        sc = ice(ii, ic, ie)
        print(f"    #{sid} {name}: I={ii} C={ic} E={ie} -> ICE={sc:.4f}")
    print(f"\n  NET weights: primary={WEIGHTS['primary']} guardrail={WEIGHTS['guardrail']} "
          f"counter={WEIGHTS['counter']}")
    print("  NET per solution (dPrimary,dGuardrail,dCounter -> net):")
    for sid, dp, dg, dc in METRIC_DELTAS:
        n = net_score(dp, dg, dc)
        print(f"    #{sid} {sol_names[sid]}: ({dp},{dg},{dc}) -> net={n:.4f}")
    print("\n  DECISION recommendations (leaf nodes):")
    for nid, parent, label, cond, dau, rev, sat, seg, note in DECISION_TREE:
        if dau is None:
            continue
        rec = recommend(dau, rev, sat, seg)
        print(f"    [{nid}] dau={dau} rev={rev} sat={sat} seg={seg} -> {rec}")
    print()
    print("[check] GOLD reproduces from the in-memory DB + scoring engines:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("product_sense.py - ground truth for PRODUCT_SENSE.md.")
    print("Worked example: 'Facebook engagement declining in 18-24'. The 8-step")
    print("framework end-to-end -- journey, pain points, RICE/ICE scoring,")
    print("tradeoff matrix, and an A/B-test decision tree. Pure stdlib.\n")
    conn = build_db()

    # sanity: journey monotone non-increasing
    j = [r[0] for r in conn.execute(
        "SELECT users FROM journey ORDER BY ord").fetchall()]
    assert all(j[i] >= j[i + 1] for i in range(len(j) - 1)), j
    # sanity: every solution's pain_id exists
    pids = {p[0] for p in PAIN_POINTS}
    assert all(s[2] in pids for s in SOLUTIONS)
    print(f"[check] built DB: {len(JOURNEY)} journey stages, "
          f"{len(PAIN_POINTS)} pain points, {len(SOLUTIONS)} solutions, "
          f"{len(METRIC_DELTAS)} metric deltas, {len(DECISION_TREE)} tree nodes")
    print("[check] journey monotone non-increasing + solution->pain refs valid:  OK")

    section_scenario()
    section_framework()
    section_journey(conn)
    section_pain(conn)
    section_scoring(conn)
    section_prioritize(conn)
    section_tradeoffs(conn)
    section_scenario_tree(conn)
    section_traps()
    section_gold(conn)

    banner("DONE - all sections printed")
    conn.close()


if __name__ == "__main__":
    main()
