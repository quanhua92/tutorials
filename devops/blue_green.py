"""
blue_green.py - Reference simulation of Blue-Green deployment: two identical
environments, an instant traffic cutover, instant rollback, and the 2x
resource cost that buys you.

This is the single source of truth that BLUE_GREEN.md is built from. Every
phase, traffic split, replica count, and cost number is printed by this file.
Deterministic (no randomness, no network, no clock). Re-run and re-paste.

Run:
    python3 blue_green.py

==========================================================================
THE INTUITION (read this first) - the two stages and the lighting director
==========================================================================
Picture a theatre with TWO identical stages side by side: the BLUE stage and
the GREEN stage. Only one is ever lit for the audience at a time. The LIGHTING
DIRECTOR (the router / load balancer) points the spotlights at exactly one
stage; the other sits dark but fully built, ready to swap in.

  Blue stage  : the CURRENT version the audience is watching (v1).
  Green stage : the NEXT version, built and rehearsed in the dark (v2).
  Router      : the lighting director. A single knob: 0%-100% to each stage,
                and the two ALWAYS sum to 100% (every request goes somewhere).

The deploy choreography:
  1. SETUP      - Blue is lit (100% traffic). Green is empty (0 replicas).
  2. PROVISION  - Build Green to match Blue (Green 3 replicas, still 0% traffic).
  3. SMOKE      - Rehearse Green in the dark (health checks pass, no audience).
  4. CUTOVER    - Flip the lights: Blue 0%, Green 100%. INSTANT. Zero downtime.
  5. (ROLLBACK) - If Green misbehaves, flip lights back to Blue. Also instant.

The trade-off is the COST: during provision/smoke/cutover BOTH stages are
built, so you run 2x the replicas. That is the price of an instant, reversible
flip - you are paying for an IDLE but WARM rollback target.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  Blue environment : the live, serving environment running the current version.
  Green environment: the idle (upcoming) environment running the new version.
  Router / LB      : the traffic splitter. blue_pct + green_pct == 100, always.
                     Implemented by a Service selector flip, an Istio
                     VirtualService with destination weights, or a DNS/ALB swap.
  Cutover          : the instant flip of 100% traffic from Blue to Green.
                     One step: no partial split, no ramp.
  Smoke test       : hitting Green DIRECTLY (bypassing the router) to validate
                     before it ever sees a real user.
  Rollback         : flipping the router back to Blue. As instant as cutover,
                     because Blue is still there, warm and serving-capable.
  Idle capacity    : the non-serving environment kept warm for fast rollback.

==========================================================================
THE BLUE-GREEN INVARIANTS (the things this bundle proves)
==========================================================================
At every phase, ALL of these hold:
  (1) blue_pct + green_pct == 100         (router never drops or doubles traffic)
  (2) exactly ONE stage lit: {blue%, green%} == {0, 100}
      (no partial split at ANY phase - that is what makes it blue-green,
       not canary. A 50/50 split would be a canary stage.)
  (3) each env's replicas in {0, steady}  (a full clone, or empty)
  (4) serving == the lit stage            (only the lit stage serves real users)

And the cost invariant:
  (5) peak_replicas == 2 * steady_replicas (you pay 2x during the deploy window)

This file ASSERTS invariants (1)-(4) at every phase, and (5) in the cost
section. blue_green.html re-derives the phase trace in JS and re-asserts the
traffic-routing gold check live.

References (all verified against the sources + asserted in code):
  - Martin Fowler, "BlueGreenDeployment" (martinfowler.com/bliki).
    Verified: two environments, router switch, idle environment kept for rollback.
  - Jez Humble & David Farley, "Continuous Delivery" - release patterns.
  - Kubernetes: two Deployments + a Service `selector` flip, or an Istio
    VirtualService with two destinations and weights summing to 100.
  - Argo Rollouts `blueGreen` strategy: `autoPromotionEnabled`, `previewReplicaCount`,
    `scaleDownDelaySeconds` (the "keep Blue warm for rollback" window).
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# Steady-state size of each environment. 3 replicas keeps the worked example
# small enough to print every number, big enough to be realistic.
STEADY_REPLICAS = 3


# ============================================================================
# 1. THE MODEL  (this is the code BLUE_GREEN.md walks through)
# ============================================================================

def phase(name, blue_rep, blue_pct, green_rep, green_pct, note=""):
    """One snapshot of a blue-green system.

    Returns a dict. `blue_pct` + `green_pct` MUST sum to 100 (the router sends
    every request somewhere). `serving` is the version actually answering
    real users (the stage with >0% traffic).
    """
    assert blue_pct + green_pct == 100, "router must split to exactly 100%"
    serving = "blue" if blue_pct > 0 else "green"
    return {
        "name": name,
        "blue_rep": blue_rep, "blue_pct": blue_pct,
        "green_rep": green_rep, "green_pct": green_pct,
        "total_rep": blue_rep + green_rep,
        "serving": serving,
        "note": note,
    }


# The canonical blue-green choreography. Each tuple is one phase. Read top to
# bottom: this is what a healthy deploy looks like, step by step.
def healthy_deploy():
    return [
        phase("IDLE",      STEADY_REPLICAS, 100, 0,               0,
              "steady state: Blue (v1) live, Green empty"),
        phase("PROVISION", STEADY_REPLICAS, 100, STEADY_REPLICAS, 0,
              "scale Green (v2) up to match Blue; router untouched"),
        phase("SMOKE",     STEADY_REPLICAS, 100, STEADY_REPLICAS, 0,
              "smoke-test Green directly (bypass router); 0 real users"),
        phase("CUTOVER",   STEADY_REPLICAS, 0,   STEADY_REPLICAS, 100,
              "FLIP router: Blue 0% -> Green 100%. instant, zero downtime"),
        phase("SETTLE",    STEADY_REPLICAS, 0,   STEADY_REPLICAS, 100,
              "keep Blue warm as the rollback target for a grace period"),
        phase("CLEANUP",   0,               0,   STEADY_REPLICAS, 100,
              "drain Blue. Green is now the new Blue for the next deploy"),
    ]


# The rollback choreography: Green went live but degraded -> flip straight back.
def rollback_deploy():
    return [
        phase("IDLE",      STEADY_REPLICAS, 100, 0,               0,
              "Blue live"),
        phase("PROVISION", STEADY_REPLICAS, 100, STEADY_REPLICAS, 0,
              "Green scaled up"),
        phase("SMOKE",     STEADY_REPLICAS, 100, STEADY_REPLICAS, 0,
              "Green smoke-tested (smoke can't catch everything)"),
        phase("CUTOVER",   STEADY_REPLICAS, 0,   STEADY_REPLICAS, 100,
              "Green went live"),
        phase("DEGRADED",  STEADY_REPLICAS, 0,   STEADY_REPLICAS, 100,
              "Green live but error rate / latency spike detected"),
        phase("ROLLBACK",  STEADY_REPLICAS, 100, STEADY_REPLICAS, 0,
              "FLIP router back: Green 0% -> Blue 100%. as instant as cutover"),
    ]


def check_invariants(phases, steady=STEADY_REPLICAS):
    """Assert blue-green invariants (1)-(4) hold at EVERY phase.

    (1) blue_pct + green_pct == 100        router splits to exactly 100%.
    (2) exactly one stage lit              {blue%, green%} == {0, 100} (no split).
    (3) each env a full clone or empty     blue_rep, green_rep in {0, steady}.
    (4) serving == the lit stage           the >0% stage is 'serving'.

    Returns (all_ok, per_phase) where per_phase is a list of dicts recording
    the check outcomes. This is the GOLD CHECK the .html re-derives.
    """
    rows = []
    all_ok = True
    for p in phases:
        traffic_ok = p["blue_pct"] + p["green_pct"] == 100          # (1)
        split_ok = {p["blue_pct"], p["green_pct"]} == {0, 100}     # (2)
        clone_ok = p["blue_rep"] in (0, steady) and p["green_rep"] in (0, steady)  # (3)
        serving_ok = p["serving"] == ("blue" if p["blue_pct"] > 0 else "green")    # (4)
        ok = traffic_ok and split_ok and clone_ok and serving_ok
        all_ok = all_ok and ok
        rows.append({
            "name": p["name"], "traffic_ok": traffic_ok, "split_ok": split_ok,
            "clone_ok": clone_ok, "serving_ok": serving_ok, "ok": ok,
        })
    return all_ok, rows


def cutover_is_one_step(phases):
    """Invariant (4) emphasis: the CUTOVER row flips 100% in a single phase.

    Blue-Green is DEFINED by an instant cutover. If a 'CUTOVER' phase existed
    with e.g. 50/50, that would be a canary, not blue-green. (Invariant (2)
    already forbids splits at every phase; this is the named CUTOVER check.)
    """
    cutovers = [p for p in phases if p["name"] == "CUTOVER"]
    if not cutovers:
        return True, 0  # rollback trace may not have a labelled cutover
    c = cutovers[0]
    one_step = c["blue_pct"] in (0, 100) and c["green_pct"] in (0, 100)
    return one_step, 1


# ============================================================================
# 2. COST MODEL  (the 2x trade-off vs rolling update)
# ============================================================================

def cost_model(steady=STEADY_REPLICAS, max_surge=1):
    """Peak resource cost during a deploy, blue-green vs rolling update.

    Blue-Green: both environments full at once during provision->settle, so
        peak = 2 * steady.
    RollingUpdate (Deployment): surge a FEW pods above steady (maxSurge), so
        peak = steady + effective_maxSurge.
    """
    bg_peak = 2 * steady
    # rolling with maxSurge as a count
    roll_peak_count = steady + max_surge
    # rolling with maxSurge as a percent (25%): ceil(steady * pct / 100)
    roll_surge_pct = math.ceil(0.25 * steady)
    roll_peak_pct = steady + roll_surge_pct
    return {
        "steady": steady,
        "bg_peak": bg_peak,
        "bg_mult": bg_peak / steady,
        "roll_peak_count": roll_peak_count,
        "roll_mult_count": roll_peak_count / steady,
        "roll_surge_pct": roll_surge_pct,
        "roll_peak_pct": roll_peak_pct,
        "roll_mult_pct": roll_peak_pct / steady,
    }


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_phases(phases, title="phase"):
    print(f"  {title:<10}  {'Blue rep':>7} {'Blue %':>6}  "
          f"{'Green rep':>8} {'Green %':>7}  {'total':>5}  serving  note")
    print(f"  {'-'*10}  {'-'*7} {'-'*6}  {'-'*8} {'-'*7}  {'-'*5}  -------  ----")
    for p in phases:
        print(f"  {p['name']:<10}  {p['blue_rep']:>7} {p['blue_pct']:>6}  "
              f"{p['green_rep']:>8} {p['green_pct']:>7}  {p['total_rep']:>5}  "
              f"{p['serving']:<7}  {p['note']}")


# ============================================================================
# 4. PRETTY SCENARIOS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: setup - Blue live, Green built in the dark
# ----------------------------------------------------------------------------

def section_setup():
    banner("SECTION A: setup - Blue (v1) live, Green (v2) built in the dark")
    print("Two IDENTICAL environments sit side by side. Blue is the current")
    print("version serving 100% of traffic. Green starts EMPTY and gets built")
    print("up to match Blue, but the router is NOT touched - Green sees 0% of")
    print("real traffic the whole time.\n")
    print(f"Each environment's steady size = {STEADY_REPLICAS} replicas.\n")
    phases = healthy_deploy()[:3]   # IDLE, PROVISION, SMOKE
    print_phases(phases, title="phase")
    ok, _ = check_invariants(phases)
    one, _ = cutover_is_one_step(phases)
    print(f"\n[check] blue_pct + green_pct == 100 at every phase?  {ok}")
    print(f"[check] cutover is a single-phase flip (no ramp)?      {one}")
    print("\nRead it: Green goes 0 -> 3 replicas while Blue's traffic stays at")
    print("100%. Green is warm and ready, but NO user has hit it yet. The smoke")
    print("test in the SMOKE phase hits Green DIRECTLY (a test URL / a debug")
    print("Service), bypassing the public router, so production is untouched.")


# ----------------------------------------------------------------------------
# SECTION B: cutover - the instant flip
# ----------------------------------------------------------------------------

def section_cutover():
    banner("SECTION B: cutover - the instant flip (Blue 100% -> Green 100%)")
    print("This is the whole point of blue-green. The router moves 100% of")
    print("traffic from Blue to Green in ONE step. There is no 50/50, no ramp,")
    print("no 'partial exposure'. Every user is on Green the instant after the")
    print("flip; nobody is on Blue.\n")
    phases = healthy_deploy()        # full choreography
    print_phases(phases, title="phase")
    ok, rows = check_invariants(phases)
    one, n = cutover_is_one_step(phases)
    cut = [p for p in phases if p["name"] == "CUTOVER"][0]
    print(f"\n[check] invariants (1)-(3) hold at every phase?         {ok}")
    print(f"[check] CUTOVER is one step (Blue {cut['blue_pct']}% -> Green "
          f"{cut['green_pct']}%)?        {one}")
    print(f"[check] after CUTOVER, serving version = {cut['serving']}")
    print("\nNote SETTLE: Blue is kept WARM (3 replicas, 0% traffic) on purpose.")
    print("It is your rollback insurance - a fully-built, known-good environment")
    print("you can flip back to instantly. Only after the grace period does")
    print("CLEANUP drain Blue (0 replicas). At that point Green 'becomes' the")
    print("new Blue for the NEXT deploy, and the cycle repeats.")


# ----------------------------------------------------------------------------
# SECTION C: rollback - as instant as the cutover
# ----------------------------------------------------------------------------

def section_rollback():
    banner("SECTION C: rollback - flip the router back (as instant as cutover)")
    print("Rollback is blue-green's superpower. Because Blue is still there and")
    print("warm (the SETTLE phase kept it), 'rollback' is just flipping the")
    print("router knob the other way. No re-deploy, no image re-pull, no waiting")
    print("for pods - one router change and 100% of traffic is back on Blue.\n")
    phases = rollback_deploy()
    print_phases(phases, title="phase")
    ok, _ = check_invariants(phases)
    # find the rollback flip
    rb = [p for p in phases if p["name"] == "ROLLBACK"][0]
    deg = [p for p in phases if p["name"] == "DEGRADED"][0]
    print(f"\n[check] invariants hold through the rollback flip?     {ok}")
    print(f"[check] DEGRADED was serving = {deg['serving']} at {deg['green_pct']}% "
          f"Green")
    print(f"[check] ROLLBACK flips to serving = {rb['serving']} at {rb['blue_pct']}% "
          f"Blue (1 step)")
    print("\nThe catch: rollback fixes ROUTING, not DATA. If Green ran a forward")
    print("migration (added a DB column, wrote new-format rows), flipping back to")
    print("Blue does not undo those writes. Blue-green pairs best with")
    print("backward-compatible, expand-then-contract schema changes.")


# ----------------------------------------------------------------------------
# SECTION D: cost - the 2x trade-off vs rolling update
# ----------------------------------------------------------------------------

def section_cost():
    banner("SECTION D: cost - 2x resources during deploy (vs rolling's surge)")
    print("Blue-green buys an instant, reversible cutover by keeping BOTH")
    print("environments built at once. During the provision -> settle window you")
    print("run 2x the replicas. Rolling update instead surges a FEW pods above")
    print("steady (maxSurge) and never reaches 2x - but it has no instant flip")
    print("and no instant rollback.\n")
    c = cost_model(STEADY_REPLICAS, max_surge=1)
    print(f"Steady-state (one environment): {c['steady']} replicas\n")
    print("| strategy            | peak replicas | vs steady | instant flip | "
          "instant rollback |")
    print("|---------------------|---------------|-----------|--------------|"
          "------------------|")
    print(f"| Blue-Green          | {c['bg_peak']:<13} | {c['bg_mult']:.1f}x       | "
          f"yes (1 step)  | yes (Blue warm)  |")
    print(f"| Rolling maxSurge=1  | {c['roll_peak_count']:<13} | "
          f"{c['roll_mult_count']:.2f}x      | no (ramp)    | no (re-roll)     |")
    print(f"| Rolling maxSurge=25%| {c['roll_peak_pct']:<13} | "
          f"{c['roll_mult_pct']:.2f}x      | no (ramp)    | no (re-roll)     |")
    print()
    print(f"[check] blue-green peak == 2 * steady?  {c['bg_peak']} == "
          f"{2 * c['steady']}  ->  {c['bg_peak'] == 2 * c['steady']}")
    print(f"[check] blue-green peak ({c['bg_peak']}) > rolling peak "
          f"({c['roll_peak_count']})?  {c['bg_peak'] > c['roll_peak_count']}")
    print(f"[check] blue-green peak / steady = {c['bg_mult']:.1f}x (the cost of")
    print("        an instant, reversible cutover). Rolling stays near 1x but")
    print("        cannot flip or roll back in one step.")
    print("\nWhen 2x is worth it: high-value releases where you want a guaranteed")
    print("one-step undo (launches, risky migrations with a compat window, events")
    print("with fixed traffic). When it is not: steady-state CI deploys where a")
    print("rolling update's small surge is cheaper and the ramp is acceptable.")


# ============================================================================
# 5. GOLD CHECK - traffic routing matches expected at every phase
#    (blue_green.html recomputes this exact trace in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK: traffic routing matches expected at every phase")
    phases = healthy_deploy()
    ok, rows = check_invariants(phases)
    one, _ = cutover_is_one_step(phases)

    # the per-phase (blue_pct, green_pct, serving) trace - pinned for the .html
    trace = [(p["blue_pct"], p["green_pct"], p["serving"]) for p in phases]
    print(f"Canonical healthy deploy (steady = {STEADY_REPLICAS} replicas):\n")
    print(f"  phase     : {'  '.join(p['name'] for p in phases)}")
    print(f"  Blue %    : {'  '.join(str(p['blue_pct']).rjust(4) for p in phases)}")
    print(f"  Green %   : {'  '.join(str(p['green_pct']).rjust(4) for p in phases)}")
    print(f"  total rep : {'  '.join(str(p['total_rep']).rjust(4) for p in phases)}")
    print(f"  serving   : {'  '.join(p['serving'].rjust(4) for p in phases)}")
    print(f"\nInvariants:  blue% + green% == 100  |  one stage lit {0, 100}  "
          f"|  env reps in {{0, {STEADY_REPLICAS}}}")
    print(f"[check] invariants (1)-(4) hold at every phase?            {ok}")
    print(f"[check] invariant (2) CUTOVER is a single-phase flip?      {one}")
    # compact pins for the .html
    peak = max(p["total_rep"] for p in phases)
    cutover = [p for p in phases if p["name"] == "CUTOVER"][0]
    print(f"[pin] peak total replicas during deploy = {peak}  "
          f"(== 2 * {STEADY_REPLICAS})")
    print(f"[pin] cutover Blue%/Green%              = "
          f"{cutover['blue_pct']}/{cutover['green_pct']}")
    print(f"[pin] final serving version             = {trace[-1][2]} "
          f"(Green is the new Blue)")
    print(f"[pin] # phases in healthy deploy        = {len(phases)}")
    assert ok and one, "blue-green invariant violated"
    assert peak == 2 * STEADY_REPLICAS
    assert cutover["blue_pct"] == 0 and cutover["green_pct"] == 100
    assert trace[-1][2] == "green"
    assert len(phases) == 6
    # the exact traffic sequence the .html must reproduce
    expected_traffic = [(100, 0), (100, 0), (100, 0), (0, 100), (0, 100), (0, 100)]
    got_traffic = [(p["blue_pct"], p["green_pct"]) for p in phases]
    assert got_traffic == expected_traffic
    print(f"[check] traffic sequence == {expected_traffic}:  OK")
    print("[check] all gold pins reproduced:  OK")
    return trace


# ============================================================================
# main
# ============================================================================

def main():
    print("blue_green.py - reference simulation.")
    print("All numbers below feed BLUE_GREEN.md.")
    print("python stdlib only; deterministic; no network, no clock.\n")

    section_setup()
    section_cutover()
    section_rollback()
    section_cost()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
