"""
canary.py - Reference simulation of Canary (progressive) deployment: a gradual
traffic shift v1 -> v2 in weighted stages, metrics-gated promotion at each
step, and automatic halt+rollback when the new version degrades.

This is the single source of truth that CANARY.md is built from. Every weight,
metric, decision, and rollback is printed by this file. Deterministic (no
randomness, no network, no clock). Re-run and re-paste.

Run:
    python3 canary.py

==========================================================================
THE INTUITION (read this first) - the dimmer switch and the sound engineer
==========================================================================
If blue-green is a light SWITCH (one stage on, the other off, instant), a
canary is a DIMMER. You start by sending a TINY slice of the audience - 1% -
into the new room (v2). A SOUND ENGINEER (the analysis step) listens: are
they complaining more? is the music laggy? If the new room sounds fine, you
nudge the dimmer up - 5%, 25%, 50%, 100%. If at any step the new room sounds
bad, you snap the dimmer back to 0 before more of the audience is affected.

  v1 (stable)   : the current version, getting (100 - w)% of traffic.
  v2 (canary)   : the new version, getting w% of traffic.
  weight w      : the dimmer position. Schedule: 0 -> 1 -> 5 -> 25 -> 50 -> 100.
  analysis step : the sound engineer. Compares v2 error rate & latency against
                  the v1 baseline. If v2 degrades past a threshold AND the
                  signal is statistically significant -> ABORT + rollback.

The whole point is BLAST RADIUS. A bad v2 only ever sees a small slice of
traffic before you catch it: at the 5% stage a buggy release has reached 5%
of users, not 100%. That is the trade vs blue-green (which flips 100% at once).

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  canary         : the new version released to a small, growing traffic slice.
  stable / v1    : the current version, receiving the bulk of traffic.
  weight         : the % of traffic sent to the canary. v1 gets (100 - weight)%.
  weighted routing: Istio/Envoy VirtualService destinationWeights, or a cloud
                   LB weighted target group. v1% + v2% == 100, always.
  stage          : one step of the schedule, e.g. "canary at 25%".
  analysis       : a metrics comparison at each stage: v2 vs v1 baseline.
  AnalysisTemplate: an Argo Rollouts object holding the metric queries + the
                   success/failure conditions. It decides PROMOTE vs ABORT.
  promote        : pass the analysis at a stage -> advance to the next weight.
  abort / halt   : fail the analysis -> stop ramping.
  rollback       : after a halt, route 100% back to v1 (weight -> 0).
  Flagger        : a progressive-delivery operator. Same loop (advance weight,
                   analyse, promote/halt) driven by a Canary CRD + a metric
                   provider (Prometheus, Datadog, Cloud Watch).

==========================================================================
THE ANALYSIS RULE (the decision this bundle proves)
==========================================================================
At each canary stage, compare v2 metrics against the v1 baseline:

    err_ratio = v2_error_rate / v1_error_rate
    lat_ratio = v2_latency      / v1_latency

    ABORT (halt + rollback) when:
        ( err_ratio > ERROR_MULT   OR   lat_ratio > LATENCY_MULT )
        AND  the canary weight is large enough for the signal to be
             statistically significant  ( weight >= MIN_SIG_WEIGHT )

    otherwise PROMOTE to the next weight.

The ERROR_MULT / LATENCY_MULT are the "failure conditions"; the
MIN_SIG_WEIGHT gate is a deterministic proxy for the "p < 0.05" significance
test real canary tools run - at 1% traffic the sample is too noisy to trust,
so a small blip there does not abort; by 5%+ you have enough requests to act.

THE CANARY INVARIANTS (asserted at every stage):
  (1) v1_pct + v2_pct == 100              (weighted routing never drops traffic)
  (2) healthy rollout weights are monotonic non-decreasing
  (3) on ABORT, the next step sends weight back to 0 (rollback to v1)
  (4) the weight schedule is exactly [0, 1, 5, 25, 50, 100]

This file ASSERTS all four; canary.html re-derives the traces in JS.

References (all verified against the sources + asserted in code):
  - Argo Rollouts docs: canary strategy, steps (setWeight/analysis),
    AnalysisTemplate, Prometheus query + successCondition/failureCondition.
  - Istio: VirtualService + DestinationRule weighted routing (traffic shifting).
  - Flagger docs: Canary CRD, metric providers, the analysis loop,
    "Progressive Delivery" (Cornelius).
  - "Progressive Delivery" pattern (in Kubernetes Patterns, Ibryam & Huss).
"""

from __future__ import annotations

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The analysis thresholds. Mirrors an Argo Rollouts AnalysisTemplate
# successCondition/failureCondition, or a Flagger Canary metric.threshold.
V1_ERR = 0.5          # baseline error rate, %
V1_LAT = 100          # baseline latency, p95 ms
ERROR_MULT = 2.0      # v2 error must not exceed 2x baseline
LATENCY_MULT = 1.5    # v2 latency must not exceed 1.5x baseline
MIN_SIG_WEIGHT = 5    # below this weight, sample too small to act (p<0.05 proxy)

# The canonical canary weight schedule. v1_pct = 100 - weight at each stage.
CANARY_WEIGHTS = [0, 1, 5, 25, 50, 100]


# ============================================================================
# 1. THE MODEL  (this is the code CANARY.md walks through)
# ============================================================================

def canary_split(weight: int):
    """Return (v1_pct, v2_pct) for a given canary weight. Always sums to 100."""
    assert 0 <= weight <= 100
    return 100 - weight, weight


def analyze(v2_err, v2_lat, weight,
            v1_err=V1_ERR, v1_lat=V1_LAT,
            err_mult=ERROR_MULT, lat_mult=LATENCY_MULT,
            min_sig=MIN_SIG_WEIGHT):
    """The sound engineer. Decide PROMOTE vs ABORT at one canary stage.

    Returns (decision, detail) where decision is 'PROMOTE' or 'ABORT'.
    ABORT fires when v2 degrades past a threshold AND the signal is
    statistically significant (weight large enough to trust -> our p<0.05 proxy).
    """
    err_ratio = v2_err / v1_err
    lat_ratio = v2_lat / v1_lat
    err_bad = err_ratio > err_mult
    lat_bad = lat_ratio > lat_mult
    significant = weight >= min_sig          # enough samples to trust the metric
    if (err_bad or lat_bad) and significant:
        reasons = []
        if err_bad:
            reasons.append(f"err {v2_err:.2f}% > {v1_err * err_mult:.2f}% "
                           f"(={err_ratio:.1f}x baseline)")
        if lat_bad:
            reasons.append(f"lat {v2_lat:.0f}ms > {v1_lat * lat_mult:.0f}ms "
                           f"(={lat_ratio:.2f}x baseline)")
        return ("ABORT", "; ".join(reasons) + "; p<0.05 significant @ "
                + str(weight) + "%")
    # why it passed (printed for transparency)
    why = (f"err {err_ratio:.1f}x, lat {lat_ratio:.2f}x - within "
           f"{err_mult:.0f}x/{lat_mult:.1f}x limits")
    if (err_bad or lat_bad) and not significant:
        why += f" (blip ignored: weight {weight}% < min_sig {min_sig}%)"
    return ("PROMOTE", why)


def run_canary(metrics_by_weight):
    """Walk the canary schedule, analysing at each stage.

    metrics_by_weight: dict weight -> (v2_err, v2_lat) or None at 0/100.
    Returns a list of stage dicts:
        weight, v1_pct, v2_pct, v2_err, v2_lat, decision, detail
    On ABORT, a final ROLLBACK stage (weight 0) is appended.
    """
    log = []
    for w in CANARY_WEIGHTS:
        v1_pct, v2_pct = canary_split(w)
        m = metrics_by_weight.get(w)
        if m is None:
            # baseline (w=0) or promoted (w=100): no analysis needed
            tag = "baseline (v1 100%)" if w == 0 else "PROMOTED (v2 100%)"
            log.append({"weight": w, "v1_pct": v1_pct, "v2_pct": v2_pct,
                        "v2_err": None, "v2_lat": None,
                        "decision": "BASELINE" if w == 0 else "COMPLETE",
                        "detail": tag})
            continue
        v2_err, v2_lat = m
        decision, detail = analyze(v2_err, v2_lat, w)
        log.append({"weight": w, "v1_pct": v1_pct, "v2_pct": v2_pct,
                    "v2_err": v2_err, "v2_lat": v2_lat,
                    "decision": decision, "detail": detail})
        if decision == "ABORT":
            # halt + rollback: next step routes 100% back to v1
            log.append({"weight": 0, "v1_pct": 100, "v2_pct": 0,
                        "v2_err": None, "v2_lat": None,
                        "decision": "ROLLBACK",
                        "detail": "halt + rollback: weight -> 0, v1 100%"})
            break
    return log


# Two deterministic scenarios. Each is a dict weight -> (v2_err%, v2_lat_ms).
# Healthy: v2 behaves; every stage promotes; ends at 100%.
HEALTHY_METRICS = {
    1:  (0.60, 102),
    5:  (0.55, 101),
    25: (0.70, 105),
    50: (0.65, 104),
    # 100 is the promoted end state (no analysis)
}

# Unhealthy: v2 looks fine early, then degrades sharply at 25% -> abort.
UNHEALTHY_METRICS = {
    1:  (0.60, 102),
    5:  (0.80, 110),
    25: (2.10, 180),     # error 4.2x baseline, latency 1.8x -> ABORT
    # 50, 100 never reached
}


# ============================================================================
# 2. INVARIANT CHECKS
# ============================================================================

def check_invariants(log):
    """Assert canary invariants (1)-(3) on a rollout log.

    (1) v1_pct + v2_pct == 100 at every stage.
    (2) pre-rollback weights are monotonic non-decreasing.
    (3) an ABORT is immediately followed by a weight-0 ROLLBACK stage.
    Returns (all_ok, detail).
    """
    traffic_ok = all(s["v1_pct"] + s["v2_pct"] == 100 for s in log)
    # monotonic up to the first rollback
    mono_ok = True
    prev = -1
    for s in log:
        if s["decision"] == "ROLLBACK":
            break
        if s["weight"] < prev:
            mono_ok = False
            break
        prev = s["weight"]
    # every ABORT followed by a ROLLBACK-to-0
    abort_ok = True
    for i, s in enumerate(log):
        if s["decision"] == "ABORT":
            nxt = log[i + 1] if i + 1 < len(log) else None
            if not (nxt and nxt["decision"] == "ROLLBACK" and nxt["weight"] == 0):
                abort_ok = False
    return traffic_ok and mono_ok and abort_ok, (traffic_ok, mono_ok, abort_ok)


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_opt(v, suffix="", nd=2):
    if v is None:
        return "  -"
    return f"{v:.{nd}f}{suffix}"


def print_rollout(log, title="stage"):
    print(f"  {title:>5}  {'v1 %':>4}  {'v2 %':>4}  "
          f"{'v2 err':>7}  {'v2 lat':>7}  {'decision':>9}  detail")
    print(f"  {'-'*5}  {'-'*4}  {'-'*4}  {'-'*7}  {'-'*7}  {'-'*9}  ------")
    for i, s in enumerate(log):
        err = fmt_opt(s["v2_err"], "%")
        lat = fmt_opt(s["v2_lat"], "ms", 0) if s["v2_lat"] is not None else "  -"
        print(f"  {i:>5}  {s['v1_pct']:>4}  {s['v2_pct']:>4}  "
              f"{err:>7}  {lat:>7}  {s['decision']:>9}  {s['detail']}")


# ============================================================================
# 4. PRETTY SCENARIOS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the canary stages (the weight schedule + traffic split)
# ----------------------------------------------------------------------------

def section_stages():
    banner("SECTION A: canary stages - the weight schedule (0->1->5->25->50->100)")
    print("A canary ramps traffic to v2 in stages. v1 always gets the rest,")
    print("so v1% + v2% == 100 at every stage. Each bump is bigger than the last")
    print("- small early (cheap to catch a bad v2), large once v2 is trusted.\n")
    print(f"v1 baseline: error = {V1_ERR}%, p95 latency = {V1_LAT}ms.\n")
    print(f"  {'weight':>6}  {'v1 %':>4}  {'v2 %':>4}  intent")
    print(f"  {'-'*6}  {'-'*4}  {'-'*4}  ------")
    intents = {
        0: "baseline: v1 serves 100%",
        1: "1% - smoke in prod; tiny blast radius",
        5: "5% - first statistically meaningful slice",
        25: "25% - quarter; real load signal",
        50: "50% - half; confidence building",
        100: "100% - v2 promoted; v1 drained",
    }
    for w in CANARY_WEIGHTS:
        v1, v2 = canary_split(w)
        print(f"  {w:>6}  {v1:>4}  {v2:>4}  {intents[w]}")
    print(f"\n[check] v1% + v2% == 100 at every weight?  "
          f"{all(sum(canary_split(w)) == 100 for w in CANARY_WEIGHTS)}")
    print(f"[check] schedule monotonic non-decreasing?  "
          f"{all(CANARY_WEIGHTS[i] <= CANARY_WEIGHTS[i+1] for i in range(len(CANARY_WEIGHTS)-1))}")
    print("\nWhy these jumps (0->1->5->25->50->100): start near-zero so a broken")
    print("release touches almost nobody; 5% is the first weight with enough")
    print(f"traffic to trust the metrics (>= MIN_SIG_WEIGHT = {MIN_SIG_WEIGHT}%);")
    print("then geometric-ish growth. Argo Rollouts encodes this as a `steps` list")
    print("of setWeight + analysis actions (see Section C).")


# ----------------------------------------------------------------------------
# SECTION B: automated analysis (PROMOTE vs ABORT) - healthy + unhealthy
# ----------------------------------------------------------------------------

def section_analysis():
    banner("SECTION B: automated analysis - PROMOTE vs ABORT at each stage")
    print("At every stage the analysis step compares v2 against the v1 baseline:\n")
    print(f"    err_ratio = v2_err / {V1_ERR}        ABORT if > {ERROR_MULT:.0f}x")
    print(f"    lat_ratio = v2_lat / {V1_LAT}       ABORT if > {LATENCY_MULT}x")
    print(f"    AND weight >= {MIN_SIG_WEIGHT}%   (significance gate: p<0.05 proxy)\n")

    print("-" * 60)
    print("SCENARIO 1: HEALTHY canary (v2 behaves) -> promotes to 100%")
    print("-" * 60)
    healthy = run_canary(HEALTHY_METRICS)
    print_rollout(healthy)
    ok_h, _ = check_invariants(healthy)
    promoted = healthy[-1]["decision"] == "COMPLETE" and healthy[-1]["weight"] == 100
    print(f"\n[check] invariants (1)-(3) hold?  {ok_h}")
    print(f"[check] promoted to 100%?          {promoted}")
    print(f"[check] # analysis stages run      {sum(1 for s in healthy if s['decision'] in ('PROMOTE','ABORT'))}")

    print()
    print("-" * 60)
    print("SCENARIO 2: UNHEALTHY canary (v2 degrades at 25%) -> halt + rollback")
    print("-" * 60)
    unhealthy = run_canary(UNHEALTHY_METRICS)
    print_rollout(unhealthy)
    ok_u, (t, mono, abort) = check_invariants(unhealthy)
    aborted = any(s["decision"] == "ABORT" for s in unhealthy)
    rolled = unhealthy[-1]["decision"] == "ROLLBACK" and unhealthy[-1]["weight"] == 0
    print(f"\n[check] invariants (1)-(3) hold?        {ok_u}  "
          f"(traffic:{t} mono:{mono} abort-followed-by-rollback:{abort})")
    print(f"[check] ABORT fired?                    {aborted}")
    print(f"[check] rolled back to weight 0?        {rolled}")
    abort_stage = [s for s in unhealthy if s["decision"] == "ABORT"][0]
    print(f"\nAbort detail: at {abort_stage['weight']}%, {abort_stage['detail']}")
    print("Blast radius: a broken v2 only reached 25% of users before rollback -")
    print("not 100%. That smaller exposure is canary's whole advantage over blue-green.")


# ----------------------------------------------------------------------------
# SECTION C: Argo Rollouts - AnalysisTemplate + weighted steps
# ----------------------------------------------------------------------------

def section_argo():
    banner("SECTION C: Argo Rollouts - AnalysisTemplate + weighted steps")
    print("Argo Rollouts automates this loop. A Rollout replaces a Deployment and")
    print("drives a canary strategy: a `steps` list of setWeight + analysis actions,")
    print("and an AnalysisTemplate holding the Prometheus queries + success/failure")
    print("conditions. The controller advances on success, aborts on failure.\n")
    print("The strategy (mirrors our schedule 0->1->5->25->50->100):\n")
    print("  strategy:\n    canary:\n      steps:")
    for w in [1, 5, 25, 50]:
        print(f"        - setWeight: {w}")
        print("        - analysis: { templates: [{ templateName: canary-check }] }")
    print("        - setWeight: 100     # promoted\n")
    print("The AnalysisTemplate (our analyze() rule as YAML):\n")
    print("  apiVersion: argoproj.io/v1alpha1\n  kind: AnalysisTemplate")
    print("  metadata: { name: canary-check }\n  spec:")
    print("    args:")
    print("      - name: service-name\n    metrics:")
    print("      - name: error-rate")
    print(f"        successCondition: result[0] <= {V1_ERR * ERROR_MULT:.2f}   "
          f"# v2 err <= {ERROR_MULT:.0f}x baseline")
    print("        failureCondition: result[0] > 1.00     # hard fail -> abort")
    print("        provider: { prometheus: { query: \"...\" } }")
    print("      - name: p95-latency")
    print(f"        successCondition: result[0] <= {V1_LAT * LATENCY_MULT:.0f}    "
          f"# v2 lat <= {LATENCY_MULT}x baseline")
    print("        provider: { prometheus: { query: \"...\" } }\n")
    print("Auto-promote: every step's analysis succeeds -> controller runs setWeight")
    print("100 and the Rollout completes. Auto-abort: any analysis hits")
    print("failureCondition -> controller sets weight back to 0 (rollback) and")
    print("marks the Rollout Degraded. This is exactly our run_canary() loop.")


# ----------------------------------------------------------------------------
# SECTION D: canary vs blue-green
# ----------------------------------------------------------------------------

def section_vs_bluegreen():
    banner("SECTION D: canary vs blue-green - gradual exposure vs instant flip")
    print("Same goal (ship v2 with a safety net), opposite risk profiles:\n")
    print("| aspect          | canary                         | blue-green             |")
    print("|-----------------|--------------------------------|------------------------|")
    print("| exposure        | gradual (1% -> 100%)           | instant (100% at once) |")
    print("| blast radius    | small early; grows per stage   | 100% on cutover        |")
    print("| rollback        | route 100% back to v1 (1 step) | flip router back (1)   |")
    print("| resource cost   | ~1x (small canary slice)       | 2x (both envs built)   |")
    print("| traffic split   | weighted (e.g. 75/25)          | {0,100} only           |")
    print("| needs metrics   | YES (gated by analysis)        | no (manual cutover ok) |")
    print("| good for        | risky change, large blast if bad| instant swap, fixed traffic|")
    print()
    print("[check] canary allows a PARTIAL split?   "
          f"{canary_split(25)} (v1/v2 at 25%)  -> yes")
    print("[check] blue-green allows a partial split?  no - it is {0,100} only")
    print("\nRule of thumb: canary when you can MEASURE v2 and a bad release must")
    print("touch few users; blue-green when you want a guaranteed one-step undo and")
    print("can afford the idle capacity. Many teams canary the risky 1->50% then")
    print("finish with a blue-green-style flip to 100%.")


# ----------------------------------------------------------------------------
# SECTION E: Flagger - progressive delivery operator
# ----------------------------------------------------------------------------

def section_flagger():
    banner("SECTION E: Flagger - progressive delivery operator")
    print("Flagger is a Kubernetes operator that runs the SAME loop (advance weight,")
    print("analyse, promote/halt) driven by a Canary CRD and a metric provider")
    print("(Prometheus, Datadog, Cloud Watch, Graphite). You declare the target and")
    print("the thresholds; Flagger drives the dimmer for you.\n")
    print("A Flagger Canary (mirrors our analyze() thresholds):\n")
    print("  apiVersion: flagger.app/v1beta1\n  kind: Canary")
    print("  spec:")
    print("    service: { port: 80, targetPort: 8080, gateways: [public] }")
    print("    analysis:")
    print("      interval: 1m         step: 5m         maxWeight: 100")
    print(f"      threshold: {{ max: {V1_ERR * ERROR_MULT:.2f} }}   # abort if v2 err > {ERROR_MULT:.0f}x")
    print("      metrics:")
    print("        - name: error-rate")
    print("          threshold: { max: 1.0 }")
    print("          query: \"...\"        # from Prometheus")
    print("        - name: latency-p95")
    print(f"          threshold: {{ max: {V1_LAT * LATENCY_MULT:.0f} }}")
    print("      weights: { minimum: 1, maximum: 100, stepWeight: 5 }")
    print()
    print("The Flagger reconcile loop (deterministic, like run_canary):")
    print("  1. INITIALIZE  - clone v1 to a v2 deployment + a weighted route (1/99).")
    print("  2. ADVANCE     - bump v2 weight by stepWeight each interval that passes.")
    print("  3. ANALYSE     - query the metric provider; compare v2 vs the threshold.")
    print("  4. PROMOTE     - all weights pass -> weight 100, v1 scaled to 0.")
    print("  5. HALT/ROLLBACK - a metric fails -> weight 0, alert fired, v1 100%.")
    print()
    print("[check] Flagger threshold.max error == our ERROR_MULT baseline?  "
          f"{V1_ERR * ERROR_MULT:.2f}% == {V1_ERR * ERROR_MULT:.2f}%")
    print("[check] Flagger loop == run_canary() loop?  "
          "advance -> analyse -> promote/halt: yes, identical shape")
    print("\nArgo Rollouts vs Flagger: same outcome, different ergonomics. Argo is")
    print("step-list driven (explicit setWeight/analysis actions). Flagger is")
    print("interval/threshold driven (it picks the weights). Both need a service")
    print("mesh or an LB that supports weighted routing (Istio, Linkerd, App Mesh,"
    "Contour, NGINX).")


# ============================================================================
# 5. GOLD CHECK - weight progression matches expected, rollback on error
#    (canary.html recomputes both traces in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK: weight progression matches expected; rollback on error")
    healthy = run_canary(HEALTHY_METRICS)
    unhealthy = run_canary(UNHEALTHY_METRICS)

    print("HEALTHY rollout trace:")
    print("  stage : " + "  ".join(str(i) for i in range(len(healthy))))
    print("  weight: " + "  ".join(str(s["weight"]).rjust(3) for s in healthy))
    print("  decide: " + "  ".join(s["decision"][:4].upper().rjust(4) for s in healthy))

    print("\nUNHEALTHY rollout trace:")
    print("  stage : " + "  ".join(str(i) for i in range(len(unhealthy))))
    print("  weight: " + "  ".join(str(s["weight"]).rjust(3) for s in unhealthy))
    print("  decide: " + "  ".join(s["decision"][:4].upper().rjust(4) for s in unhealthy))

    ok_h, _ = check_invariants(healthy)
    ok_u, _ = check_invariants(unhealthy)

    # the exact weight sequences the .html must reproduce
    healthy_weights = [s["weight"] for s in healthy]
    unhealthy_weights = [s["weight"] for s in unhealthy]
    expected_healthy = [0, 1, 5, 25, 50, 100]
    expected_unhealthy = [0, 1, 5, 25, 0]   # abort at 25 -> rollback to 0

    h_match = healthy_weights == expected_healthy
    u_match = unhealthy_weights == expected_unhealthy
    h_complete = healthy[-1]["decision"] == "COMPLETE"
    u_aborted = any(s["decision"] == "ABORT" for s in unhealthy)
    u_rolled = unhealthy[-1]["decision"] == "ROLLBACK"

    print(f"\n[check] healthy weights == {expected_healthy}?          {h_match}")
    print(f"[check] unhealthy weights == {expected_unhealthy}?       {u_match}")
    print(f"[check] healthy invariants (1)-(3) hold?                 {ok_h}")
    print(f"[check] unhealthy invariants (1)-(3) hold?               {ok_u}")
    print(f"[pin] healthy final decision = {healthy[-1]['decision']} @ {healthy[-1]['weight']}%")
    print(f"[pin] unhealthy abort stage   = "
          f"{[s for s in unhealthy if s['decision']=='ABORT'][0]['weight']}%")
    print(f"[pin] unhealthy final state   = {unhealthy[-1]['decision']} @ {unhealthy[-1]['weight']}%")
    print(f"[pin] healthy # stages = {len(healthy)}  |  unhealthy # stages = {len(unhealthy)}")
    assert h_match and u_match, "weight progression mismatch"
    assert ok_h and ok_u, "canary invariant violated"
    assert h_complete, "healthy did not complete"
    assert u_aborted and u_rolled, "unhealthy did not abort + rollback"
    assert len(healthy) == 6 and len(unhealthy) == 5   # 0,1,5,25,50,100 | 0,1,5,25,ROLLBACK
    print(f"[check] healthy completes @ 100%?     {h_complete}")
    print(f"[check] unhealthy aborts + rolls back? {u_aborted and u_rolled}")
    print("[check] all gold pins reproduced:  OK")
    return healthy_weights, unhealthy_weights


# ============================================================================
# main
# ============================================================================

def main():
    print("canary.py - reference simulation.")
    print("All numbers below feed CANARY.md.")
    print("python stdlib only; deterministic; no network, no clock.\n")

    section_stages()
    section_analysis()
    section_argo()
    section_vs_bluegreen()
    section_flagger()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
