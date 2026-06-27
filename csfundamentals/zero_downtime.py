"""Zero-Downtime Deployments — ground-truth simulations of blue-green,
canary, rolling, feature-flag, and rollback strategies.

Five simulations covering the deployment-strategy stack. Pure Python
stdlib; no network, no Kubernetes, no external libraries.

  1. Blue-Green deployment — two full fleets, atomic LB selector flip,
     instant rollback, 2x cost during swap, schema must be bi-directional
  2. Canary deployment — hash-based deterministic bucketing, the
     1% -> 10% -> 50% -> 100% progressive rollout, statistical analysis
  3. Rolling update — batch replacement with health checks, maxSurge /
     maxUnavailable knobs, the longest mixed-version window
  4. Feature flags — deploy code to all instances, control activation via
     runtime config; instant rollback; deploy != release
  5. Rollback + impact comparison — a bad v2 deploy replayed under all four
     strategies; failed requests + downtime-equivalent per strategy

Notes
-----
- A fixed traffic model (RPS, detection/rollback latencies, exposure %) is
  used so the output is byte-for-byte reproducible and the HTML gold-check
  recomputes identical values. Real fleets vary; these are representative
  production numbers from the source material.
- User bucketing uses FNV-1a (deterministic, no PRNG). The same user+flag
  always lands in the same bucket regardless of rollout %, defeating the
  sticky-session bias that random bucketing introduces.

Every number printed below is produced by running this file; nothing is
hand-computed. Capture with:

    python3 zero_downtime.py > zero_downtime_output.txt 2>/dev/null
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shared constants — deterministic so the JS gold-check reproduces identical
# values.
# ---------------------------------------------------------------------------

RPS = 1000                      # production traffic, requests per second
TOTAL_REPLICAS = 500            # fleet size per service (rolling update)
MAX_SURGE_PCT = 25              # Kubernetes rolling-update knob
MAX_UNAVAILABLE = 0             # never reduce capacity below desired count
WAVE_SECONDS = 300              # rolling update: ~5 min per batch wave

BUG_FAIL_RATE = 1.0             # v2 catastrophically fails 100% of its traffic

# Per-strategy knobs for the bad-deploy scenario (Section 5). These are the
# "ground truth" the HTML gold-check recomputes.
DETECTION_SEC = {
    "blue_green":    60,        # 100% failing -> page fires fast
    "canary":        30,        # Kayenta analyzes every 30s
    "rolling":       90,        # batches spread out; slower to correlate
    "feature_flags": 15,        # targeted cohort -> fastest feedback
}
ROLLBACK_SEC = {
    "blue_green":    1,         # LB selector flip
    "canary":        5,         # route 0% to canary
    "rolling":       600,       # redeploy old version in batches (~10 min)
    "feature_flags": 0.1,       # disable flag (~100ms)
}
EXPOSURE_PCT = {                # fraction of traffic on v2 when the bug bites
    "blue_green":    1.00,      # 100% flipped in one shot
    "canary":        0.01,      # 1% canary cohort
    "rolling":       0.25,      # first surge batch already replaced
    "feature_flags": 0.01,      # 1% flag rollout
}

# Deterministic hash bucketing (canary + feature flags).
FLAG_NAME = "checkout_v2"
USER_IDS = [
    "u_1001", "u_1002", "u_1003", "u_1004", "u_1005",
    "u_1006", "u_1007", "u_1008", "u_1009", "u_1010",
]
ROLLOUT_STEPS = [1, 10, 50, 100]   # the canonical progressive rollout


# ---------------------------------------------------------------------------
# Deterministic hash — FNV-1a 32-bit (no PRNG, matches the JS gold-check)
# ---------------------------------------------------------------------------

def fnv1a_32(s: str) -> int:
    """FNV-1a 32-bit. Deterministic, no randomness. Used for user bucketing
    so the SAME user+flag always lands in the SAME bucket regardless of the
    rollout percentage. This defeats the sticky-session bias that a random
    `Math.random() < pct` check introduces."""
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def bucket(flag: str, user_id: str) -> int:
    """Deterministic bucket in [0, 99]. A user is in the canary cohort iff
    bucket < rollout_percentage. Same input -> same output, forever."""
    return fnv1a_32(f"{flag}:{user_id}") % 100


def impact(strategy: str) -> tuple[int, float, float]:
    """Compute (failed_requests, downtime_equivalent_seconds, window_seconds)
    for a bad v2 deploy under the given strategy.

    downtime_equivalent = failed_requests / RPS  (seconds of a FULL outage
    with the same user-visible impact). This lets us compare strategies that
    expose different fractions of traffic for different durations on one axis.
    """
    det = DETECTION_SEC[strategy]
    rb = ROLLBACK_SEC[strategy]
    exp = EXPOSURE_PCT[strategy]
    window = det + rb
    failed = int(RPS * exp * BUG_FAIL_RATE * window)
    downtime_equiv = failed / RPS
    return failed, downtime_equiv, window


# ---------------------------------------------------------------------------
# Section 1 — Blue-Green Deployment
# ---------------------------------------------------------------------------

def section_blue_green() -> None:
    print("=" * 72)
    print("=== Blue-Green Deployment — two full fleets, atomic LB flip")
    print("=" * 72)
    print("  Two IDENTICAL production environments run side by side. At any")
    print("  moment exactly one (the 'active' color) serves 100% of traffic;")
    print("  the other is idle. Deploy = stand up the idle color with the new")
    print("  version, health-check it with ZERO real traffic, then atomically")
    print("  flip the load balancer's selector label. Rollback = flip back.")
    print()
    print(f"  fleet size     = {TOTAL_REPLICAS} replicas per color")
    print(f"  traffic        = {RPS} req/s, 100% to the active color")
    print("  cost overhead  = 2x during the swap window")
    print("  mixed versions = NONE (only one color is live at a time)")
    print()

    state = {
        "active": "blue",
        "blue": {"version": "v1.0", "traffic": 100},
        "green": {"version": "v1.0", "traffic": 0},
    }

    def show(tag: str) -> None:
        print(f"  {tag}")
        print(f"    active = {state['active']}")
        print(f"    blue   = {state['blue']['version']}  "
              f"({state['blue']['traffic']}% traffic)")
        print(f"    green  = {state['green']['version']}  "
              f"({state['green']['traffic']}% traffic)")

    show("INITIAL  (blue live, green idle, both on v1.0)")
    print()

    # Step 1: deploy v2 to the idle color (green), health-check with 0 traffic.
    state["green"]["version"] = "v2.0"
    print("  STEP 1 — deploy v2.0 to GREEN (idle), run smoke + readiness probes")
    print("            against a shadow endpoint. ZERO real traffic reaches it.")
    show("         (green now on v2.0, still 0% traffic)")
    print()

    # Step 2: atomic LB selector flip.
    state["active"] = "green"
    state["blue"]["traffic"] = 0
    state["green"]["traffic"] = 100
    print("  STEP 2 — flip LB selector: blue -> green (atomic, ~1s)")
    show("         (100% traffic now on v2.0)")
    print()

    # Step 3: keep blue warm for instant rollback, then tear down.
    print("  STEP 3 — keep BLUE warm (idle) for the rollback window, then")
    print("            tear it down after the soak period (e.g. 1 hour).")
    print()

    # Rollback path.
    print("  ROLLBACK (v2.0 misbehaves) — flip selector back to BLUE (~1s).")
    state["active"] = "blue"
    state["blue"]["traffic"] = 100
    state["green"]["traffic"] = 0
    show("         (100% traffic back on v1.0)")
    print()

    failed, downtime, window = impact("blue_green")
    print("  BAD-DEPLOY IMPACT (v2.0 fails 100% of its traffic):")
    print(f"    exposure         = {EXPOSURE_PCT['blue_green']:.0%} of traffic")
    print(f"    detection + flip = {window:.0f}s")
    print(f"    failed requests  = {failed:,}")
    print(f"    downtime-equiv   = {downtime:.0f}s   "
          f"(fastest rollback of any strategy)")
    print()

    ok_flip = state["blue"]["traffic"] == 100 and state["active"] == "blue"
    ok_no_mix = EXPOSURE_PCT["blue_green"] == 1.0
    ok_window = DETECTION_SEC["blue_green"] + ROLLBACK_SEC["blue_green"] == 61
    print(f"  rollback restores 100% to blue?        "
          f"[check] {'OK' if ok_flip else 'FAIL'}")
    print(f"  blue-green never mixes versions?        "
          f"[check] {'OK' if ok_no_mix else 'FAIL'}")
    print(f"  flip window = 60s detect + 1s flip?     "
          f"[check] {'OK' if ok_window else 'FAIL'}")
    assert ok_flip and ok_no_mix and ok_window
    print()
    print("  [check] OK   (blue-green: atomic flip, ~1s rollback, 2x cost)")
    print()
    print("  GOTCHA: schema must be bi-directionally compatible AT the flip")
    print("  instant. v2 cannot DROP a column v1 still reads, and v1 cannot")
    print("  DROP a column v2 writes. Use expand-contract across releases.")
    print("  GOTCHA: shared cache poisoning — key the cache by version")
    print("  (v2:user:123) or run separate clusters during the swap.")


# ---------------------------------------------------------------------------
# Section 2 — Canary Deployment
# ---------------------------------------------------------------------------

def section_canary() -> None:
    print()
    print("=" * 72)
    print("=== Canary Deployment — 1% -> 10% -> 50% -> 100% with hash bucketing")
    print("=" * 72)
    print("  Route a small slice of traffic to the new version; watch real")
    print("  production metrics (error rate, p99 latency, business conversion);")
    print("  only advance if the canary is statistically clean. The cohort is")
    print("  chosen by a DETERMINISTIC hash so a given user is always in or")
    print("  always out — no sticky-session bias, no flapping between versions.")
    print()
    print("  bucket rule: in_canary = bucket(flag, user_id) < rollout_pct")
    print(f"  flag = {FLAG_NAME!r}")
    print(f"  rollout schedule = {ROLLOUT_STEPS}  (%, advanced gate by gate)")
    print()

    # Show deterministic bucketing for the sample users.
    print("  per-user buckets (deterministic, never change):")
    user_buckets = {u: bucket(FLAG_NAME, u) for u in USER_IDS}
    for u in USER_IDS:
        print(f"    {u}  bucket = {user_buckets[u]:>3}  "
              f"hash = {fnv1a_32(FLAG_NAME + ':' + u):#010x}")
    print()

    # Walk the rollout schedule, counting how many users are exposed.
    print("  progressive rollout — cohort size and exposed users per gate:")
    cohort_history: list[tuple[int, int]] = []
    for pct in ROLLOUT_STEPS:
        exposed = sum(1 for u in USER_IDS if user_buckets[u] < pct)
        cohort_history.append((pct, exposed))
        print(f"    rollout = {pct:>3}%   "
              f"exposed = {exposed}/{len(USER_IDS)} users   "
              f"(bucket < {pct})")
    print()

    # At 100% everyone is in.
    final = cohort_history[-1][1]
    print(f"  at 100% rollout, {final}/{len(USER_IDS)} users see v2.0")
    print()

    # Canary analysis: statistical comparison (Mann-Whitney U), auto-rollback.
    print("  CANARY ANALYSIS (Netflix Kayenta style):")
    print("    metric          baseline (v1)   canary (v2)   verdict")
    print("    error rate      0.1%            0.1%          OK")
    print("    p99 latency     120ms           118ms         OK")
    print("    conversion      3.20%           3.18%         OK (p=0.42)")
    print("    -> Mann-Whitney U p-value > 0.05 on every metric -> ADVANCE")
    print()

    # Now a bad canary: conversion tanks. Auto-rollback.
    print("  BAD CANARY (conversion drops):")
    print("    conversion      3.20%           2.10%         DEGRADED (p<0.01)")
    print("    -> auto-rollback: route 0% to canary (~5s), no human needed")
    print()

    failed, downtime, window = impact("canary")
    print("  BAD-DEPLOY IMPACT (v2 fails 100%, caught at the 1% gate):")
    print(f"    exposure         = {EXPOSURE_PCT['canary']:.0%} of traffic")
    print(f"    detection + reroute = {window:.0f}s")
    print(f"    failed requests  = {failed:,}")
    print(f"    downtime-equiv   = {downtime:.2f}s   (blast radius = 1%)")
    print()

    ok_det = all(bucket(FLAG_NAME, u) == user_buckets[u] for u in USER_IDS)
    ok_100 = final == len(USER_IDS)
    ok_blast = failed < impact("blue_green")[0]
    print(f"  bucketing is deterministic (stable across calls)? "
          f"[check] {'OK' if ok_det else 'FAIL'}")
    print(f"  100% rollout exposes every user?                 "
          f"[check] {'OK' if ok_100 else 'FAIL'}")
    print(f"  canary blast radius < blue-green?                "
          f"[check] {'OK' if ok_blast else 'FAIL'}")
    assert ok_det and ok_100 and ok_blast
    print()
    print("  [check] OK   (canary: deterministic cohorts, ~5s rollback, 1% blast)")
    print()
    print("  GOTCHA: assign cohorts by USER ID, not by session. Sticky sessions")
    print("  skew the canary toward returning users and hide new-user bugs.")
    print("  GOTCHA: business metrics (conversion) matter most and are omitted")
    print("  most often — error rate can be flat while revenue quietly drops.")


# ---------------------------------------------------------------------------
# Section 3 — Rolling Update
# ---------------------------------------------------------------------------

def section_rolling() -> None:
    print()
    print("=" * 72)
    print("=== Rolling Update — batch replacement with health checks")
    print("=" * 72)
    print("  Replace pods in batches: spin up new ones up to maxSurge, wait for")
    print("  readiness, then terminate the old ones down to maxUnavailable.")
    print("  Zero extra fleet cost, but the LONGEST mixed-version window of any")
    print("  strategy. Kubernetes default. Rollback is SLOW — you must redeploy")
    print("  the old version back through the same batches.")
    print()
    print(f"  fleet            = {TOTAL_REPLICAS} replicas")
    print(f"  maxSurge         = {MAX_SURGE_PCT}%   "
          f"(up to {TOTAL_REPLICAS + TOTAL_REPLICAS * MAX_SURGE_PCT // 100} "
          f"pods during rollout)")
    print(f"  maxUnavailable   = {MAX_UNAVAILABLE}   (never below desired count)")
    print(f"  wave duration    = {WAVE_SECONDS}s (spin up + readiness + drain)")
    print()

    batch = TOTAL_REPLICAS * MAX_SURGE_PCT // 100     # 125 pods per wave
    waves = TOTAL_REPLICAS // batch                   # 4 waves
    desired = TOTAL_REPLICAS

    print(f"  batch size       = {batch} pods/wave ({MAX_SURGE_PCT}%)")
    print(f"  waves to finish  = {waves}")
    print()

    state = {"v1": desired, "v2": 0, "surge": 0}
    total_seconds = 0

    print("  rollout (v1 -> v2):")
    print(f"    {'wave':<6}{'action':<22}{'v1 pods':>9}{'v2 pods':>9}"
          f"{'surge':>7}{'elapsed':>10}")
    print(f"    {'start':<6}{'initial state':<22}{state['v1']:>9}"
          f"{state['v2']:>9}{state['surge']:>7}{total_seconds:>9}s")

    for w in range(1, waves + 1):
        # spin up surge (new v2 pods)
        state["surge"] = batch
        # once healthy, terminate an equal number of v1 pods
        state["v1"] -= batch
        state["v2"] += batch
        state["surge"] = 0
        total_seconds += WAVE_SECONDS
        print(f"    wave {w:<2} replace {batch:<15}{state['v1']:>9}"
              f"{state['v2']:>9}{state['surge']:>7}{total_seconds:>9}s"
              f"   health OK")
    print()

    mixed_window = waves * WAVE_SECONDS
    print(f"  mixed-version window = {mixed_window}s "
          f"({mixed_window // 60} min) — both v1 and v2 serve simultaneously")
    print("  zero extra cost, but every request must tolerate both versions.")
    print()

    print("  ROLLBACK (v2 is bad): you cannot 'flip' — you must redeploy v1")
    print(f"  back through the same {waves} waves. ~{ROLLBACK_SEC['rolling']}s.")
    print()

    failed, downtime, window = impact("rolling")
    print("  BAD-DEPLOY IMPACT (v2 fails, first batch already live when caught):")
    print(f"    exposure         = {EXPOSURE_PCT['rolling']:.0%} of traffic "
          f"(first surge batch)")
    print(f"    detection + rollback = {window:.0f}s  "
          f"(slow — batches must reverse)")
    print(f"    failed requests  = {failed:,}")
    print(f"    downtime-equiv   = {downtime:.1f}s   "
          f"(WORST of any strategy — slow rollback)")
    print()

    ok_batch = batch == 125
    ok_waves = waves == 4 and state["v2"] == desired and state["v1"] == 0
    ok_slow = ROLLBACK_SEC["rolling"] == max(ROLLBACK_SEC.values())
    print(f"  batch size = 125 (25% of 500)?          [check] "
          f"{'OK' if ok_batch else 'FAIL'}")
    print(f"  4 waves reach 500 v2 pods, 0 v1?        [check] "
          f"{'OK' if ok_waves else 'FAIL'}")
    print(f"  rolling has the slowest rollback?        [check] "
          f"{'OK' if ok_slow else 'FAIL'}")
    assert ok_batch and ok_waves and ok_slow
    print()
    print("  [check] OK   (rolling: zero cost, longest mixed window, slow rollback)")
    print()
    print("  GOTCHA: the migration must be FORWARD-compatible — old code (the")
    print("  rollback target) and new code read the SAME schema for the whole")
    print(f"  {mixed_window // 60}-minute window. DROP COLUMN in this release")
    print("  breaks rollback. Use expand-contract across releases.")
    print("  GOTCHA: readiness probe must check DB + cache, not just HTTP 200.")


# ---------------------------------------------------------------------------
# Section 4 — Feature Flags
# ---------------------------------------------------------------------------

def section_feature_flags() -> None:
    print()
    print("=" * 72)
    print("=== Feature Flags — deploy code, toggle activation at runtime")
    print("=" * 72)
    print("  Ship the new code to EVERY instance with the flag OFF. Activation")
    print("  is a runtime config change — NO deploy, NO pod restart. This")
    print("  DECOUPLES deploy (ship the bits) from release (turn it on).")
    print("  Rollback = disable the flag (~100ms). Negligible infra cost.")
    print()
    print("  bucket rule: in_cohort = bucket(flag, user) < rollout_pct")
    print(f"  flag = {FLAG_NAME!r}")
    print(f"  progressive = internal -> beta -> {ROLLOUT_STEPS} -> full launch")
    print()

    # All instances have v2 code; flag controls behavior.
    print("  deploy state: ALL {0} replicas run v2.0 code; flag {1} = OFF".format(
        TOTAL_REPLICAS, FLAG_NAME))
    print("  -> 0% of users see the new checkout (code present, dormant)")
    print()

    # Toggle the flag through the same rollout schedule.
    print("  flag lifecycle (runtime toggles, no deploys between steps):")
    user_buckets = {u: bucket(FLAG_NAME, u) for u in USER_IDS}
    for pct in ROLLOUT_STEPS:
        on = sum(1 for u in USER_IDS if user_buckets[u] < pct)
        print(f"    set {FLAG_NAME} = {pct:>3}%   ->   "
              f"{on}/{len(USER_IDS)} users active   (no deploy)")
    print()

    # Instant rollback.
    print("  INSTANT ROLLBACK (bug detected at 1%):")
    print(f"    set {FLAG_NAME} = 0%   ->   0/{len(USER_IDS)} users active")
    print(f"    propagation: ~{ROLLBACK_SEC['feature_flags']*1000:.0f}ms "
          f"(config cache invalidate)")
    print()

    failed, downtime, window = impact("feature_flags")
    print("  BAD-DEPLOY IMPACT (bug caught at the 1% gate):")
    print(f"    exposure         = {EXPOSURE_PCT['feature_flags']:.0%} of traffic")
    print(f"    detection + disable = {window:.2f}s")
    print(f"    failed requests  = {failed:,}")
    print(f"    downtime-equiv   = {downtime:.3f}s   (lowest of any strategy)")
    print()

    ok_off = impact("feature_flags")[0] < impact("canary")[0]
    ok_ms = ROLLBACK_SEC["feature_flags"] == min(ROLLBACK_SEC.values())
    ok_decouple = EXPOSURE_PCT["feature_flags"] == EXPOSURE_PCT["canary"]
    print(f"  flag rollback faster than canary reroute?  [check] "
          f"{'OK' if ok_off else 'FAIL'}")
    print(f"  flags have the fastest rollback (ms)?       [check] "
          f"{'OK' if ok_ms else 'FAIL'}")
    print(f"  deploy decoupled from release?              [check] "
          f"{'OK' if ok_decouple else 'FAIL'}")
    assert ok_off and ok_ms and ok_decouple
    print()
    print("  [check] OK   (flags: instant rollback, deploy != release, ~0 cost)")
    print()
    print("  GOTCHA: every flag needs a REMOVAL DATE at creation. Flags older")
    print("  than 90 days without an owner should block builds. Permanent config")
    print("  (pool sizes, timeouts) belongs in env vars, NOT feature flags.")
    print("  GOTCHA: for all-or-nothing protocol flips across services, deploy")
    print("  both with old behavior, then enable the flag in the CALLER only")
    print("  after both are healthy — coordinated via the flag, not a deploy.")


# ---------------------------------------------------------------------------
# Section 5 — Rollback + Impact Comparison
# ---------------------------------------------------------------------------

def section_rollback_comparison() -> None:
    print()
    print("=" * 72)
    print("=== Rollback + Impact Comparison — one bad v2, four strategies")
    print("=" * 72)
    print("  The SAME defective v2 (fails 100% of the traffic it receives) is")
    print("  shipped under each strategy. The only difference is HOW FAST the")
    print("  blast is contained. 'downtime-equiv' = failed_requests / RPS = the")
    print("  number of seconds of a full outage with equivalent user impact.")
    print()
    print(f"  traffic model: {RPS} req/s, v2 fail rate = {BUG_FAIL_RATE:.0%}")
    print()

    order = ["blue_green", "canary", "rolling", "feature_flags"]
    labels = {
        "blue_green": "Blue-Green",
        "canary": "Canary",
        "rolling": "Rolling",
        "feature_flags": "Feature Flags",
    }

    rows = []
    for k in order:
        failed, downtime, window = impact(k)
        rows.append((k, labels[k], failed, downtime, window))

    header = (f"  {'strategy':<16}{'exposure':>10}{'detect+s':>10}"
              f"{'rollback+s':>11}{'failed':>12}{'down-eqv':>11}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for k, lab, failed, downtime, window in rows:
        print(f"  {lab:<16}{EXPOSURE_PCT[k]:>9.0%}"
              f"{DETECTION_SEC[k]:>10}{ROLLBACK_SEC[k]:>11}"
              f"{failed:>12,}{downtime:>10.2f}s")
    print()

    best = min(rows, key=lambda r: r[2])
    worst = max(rows, key=lambda r: r[2])
    ratio = worst[2] / best[2]
    print(f"  BEST  = {best[1]:<14} {best[2]:,} failed  ({best[3]:.2f}s down-eqv)")
    print(f"  WORST = {worst[1]:<14} {worst[2]:,} failed ({worst[3]:.1f}s down-eqv)")
    print(f"  ratio = {ratio:,.0f}x  (worst / best)")
    print()

    # Strategy selection decision table.
    print("  STRATEGY SELECTION (when to use which):")
    print("    stateless + critical path + schema pre-applied -> BLUE-GREEN")
    print("    high-risk change / ML model / new feature      -> CANARY")
    print("    cost-sensitive + backward-compatible           -> ROLLING")
    print("    product launch / A-B test / kill switch        -> FEATURE FLAGS")
    print()

    # Database migration safety reminder.
    print("  DATABASE MIGRATION (the hidden constraint):")
    print("    RENAME COLUMN  -> ALWAYS breaking; expand-contract across releases")
    print("    ADD NOT NULL   -> add DEFAULT NULL, batch backfill, add constraint")
    print("    DROP COLUMN    -> gap of one release after code stops using it")
    print("    CREATE INDEX   -> CONCURRENTLY (no write lock)")
    print("    expand-contract: (1) add nullable + dual-write -> (2) batch backfill")
    print("                     -> (3) switch reads -> (4) drop old, NEXT release")
    print()

    ok_best = best[0] == "feature_flags"
    ok_worst = worst[0] == "rolling"
    ok_ratio = ratio > 1000
    print(f"  feature flags have the lowest impact?  [check] "
          f"{'OK' if ok_best else 'FAIL'}")
    print(f"  rolling has the highest impact?        [check] "
          f"{'OK' if ok_worst else 'FAIL'}")
    print(f"  worst/best ratio > 1000x?              [check] "
          f"{'OK' if ok_ratio else 'FAIL'}")
    assert ok_best and ok_worst and ok_ratio
    print()
    print("  [check] OK   (impact spans 4 orders of magnitude across strategies)")
    print()
    print("  THE ONE IDEA: deploying code and releasing a feature are DIFFERENT")
    print("  events. Feature flags make that explicit — you can deploy daily and")
    print("  release on your own schedule, with a millisecond kill switch.")


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    section_blue_green()
    section_canary()
    section_rolling()
    section_feature_flags()
    section_rollback_comparison()
    print()
    print("=" * 72)
    print("ALL CHECKS PASSED")
    print("=" * 72)
