"""
deployment_replicaset.py - Reference simulation of the Kubernetes
Deployment -> ReplicaSet -> Pods hierarchy, rolling updates (maxSurge /
maxUnavailable), rollback, strategy choice (RollingUpdate vs Recreate), and
ReplicaSet self-healing.

This is the single source of truth that DEPLOYMENT_REPLICASET.md is built from.
Every replica count, rollout step, and worked example is printed by this file.
Deterministic (no randomness, no network, no clock). Re-run and re-paste.

Run:
    python3 deployment_replicaset.py

==========================================================================
THE INTUITION (read this first) - the foreman, the crew chiefs, and the workers
==========================================================================
A Deployment is a FOREMAN holding a blueprint ("I want 3 replicas of web:v2").
It never touches workers directly. Instead it hires a CREW CHIEF (a ReplicaSet)
per blueprint version, and each crew chief keeps exactly the right number of
WORKERS (Pods) on the floor.

  Deployment  : the foreman. Holds desired replica count + pod template (the
                blueprint, e.g. image:tag). Owns ReplicaSets. Drives rollouts.
  ReplicaSet  : a crew chief. Owns a SET of Pods matched by a selector, and
                ENFORCES "actual == desired" - if a Pod dies, it makes a new one.
                This is the self-healing layer.
  Pod         : a worker. The actual running process. Disposable.

The NON-OBVIOUS parts this file drills into:
  1. ROLLING UPDATE is interleaved: the new ReplicaSet scales UP while the old
     one scales DOWN, never crossing two guardrails at once:
       - total pods   <= replicas + maxSurge        (don't over-provision)
       - available    >= replicas - maxUnavailable  (don't drop below capacity)
     (Section B)
  2. ROLLBACK is the same machinery in reverse: the previous ReplicaSet becomes
     the target and re-scales up while the current one drains. (Section C)
  3. STRATEGY choice: RollingUpdate (default, zero-downtime, two versions
     briefly coexist) vs Recreate (kill ALL old first, THEN make new - has a
     downtime window but guarantees only one version runs). (Section D)
  4. SELF-HEALING is the ReplicaSet's job, NOT the Deployment's: if a Pod
     disappears (node loss, crash, eviction), the ReplicaSet reconcile loop
     notices desired != actual and creates a replacement. (Section E)

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  Deployment    : the foreman workload object. Owns ReplicaSets. You `kubectl
                  apply` a Deployment, not Pods.
  ReplicaSet (RS): enforces a stable set of replica Pods at any given target
                  count. Created/owned by a Deployment. This is the layer that
                  does self-healing.
  Pod           : one running instance. Disposable; named pod-template-hash to
                  bind it to its ReplicaSet.
  replicas      : the desired Pod count the Deployment/RS tries to maintain.
  pod-template-hash: a hash of the Pod template, appended to RS + Pod names.
                  Each revision (image tag change) gets a NEW hash -> a NEW RS.
  revisionHistoryLimit: how many old ReplicaSets the Deployment keeps (default
                  10) - these are what `rollout undo` scales back up.
  maxSurge      : how many EXTRA pods (above `replicas`) may exist during a
                  RollingUpdate. int or percent. Governs scale-UP speed.
  maxUnavailable: how many pods may be UNAVAILABLE (below replicas) during a
                  RollingUpdate. int or percent. Governs scale-DOWN speed.
                  Set both to 0 for "zero downtime, zero capacity loss" updates
                  (requires spare capacity = maxSurge).
  available     : a pod that is Running AND has passed its readiness probe.
                  Only `available` pods count toward serving traffic.

==========================================================================
THE TWO ROLLING-UPDATE GUARDRAILS (the invariant this bundle proves)
==========================================================================
During a RollingUpdate, the Deployment controller NEVER violates EITHER:
    (1)  total_pods        <= replicas + maxSurge
    (2)  available_pods    >= replicas - maxUnavailable

Guardrail (1) bounds resource cost; guardrail (2) bounds downtime. The new RS
scales up (bounded by 1) and the old RS scales down (as much as availability
allows) every reconcile pass. With readiness lag, this produces the classic
interleaved sawtooth: up-one, down-one, up-one, down-one.

This file ASSERTS both guardrails hold at EVERY step of the canonical rollout -
that is the GOLD CHECK, and deployment_replicaset.html re-derives it in JS.

References (all verified against the docs + asserted in code):
    Pod lifecycle / readiness: kubernetes.io/.../pod-lifecycle
    Deployment strategy:       kubernetes.io/.../deployment-strategy
    Rolling back:              kubernetes.io/docs/concepts/.../deployment/#rolling-back
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE MODELS  (this is the code DEPLOYMENT_REPLICASET.md walks through)
# ============================================================================

def rolling_update(desired, max_surge, max_unavailable, ready_lag=1, max_steps=60):
    """Simulate a RollingUpdate rollout, step by step.

    Conventions
    -----------
    - The OLD ReplicaSet starts at `desired` replicas, all ready.
    - The NEW ReplicaSet starts at 0 and is the rollout target.
    - `ready_lag`: a Pod created at step s becomes available (ready) at step
      s + ready_lag. Models image-pull + probe time.
    - Each reconcile step: surge the new RS up by ONE (if room under maxSurge),
      then scale the old RS down AS MUCH AS availability allows (bounded by
      maxUnavailable). This is the safe, one-at-a-time surge the controller uses.

    Guardrails (never violated):
        total     <= desired + max_surge
        available >= desired - max_unavailable

    Returns (steps, max_total, min_available) where each step is a dict:
        step, old, new, old_ready, new_ready, total, available, action
    """
    max_total = desired + max_surge
    min_avail = max(desired - max_unavailable, 0)
    old = desired
    new_pods = []                       # creation steps of new-RS pods

    def new_ready(now):
        return sum(1 for s in new_pods if s + ready_lag <= now)

    def snap(step, action):
        nr = new_ready(step)
        return {
            "step": step, "old": old, "new": len(new_pods),
            "old_ready": old, "new_ready": nr,
            "total": old + len(new_pods), "available": old + nr,
            "action": action,
        }

    steps = [snap(0, "start: OLD rs at desired, NEW rs at 0")]
    step = 0
    while (len(new_pods) < desired or old > 0
           or (old + new_ready(step)) < desired) and step < max_steps:
        step += 1
        avail = old + new_ready(step)
        total = old + len(new_pods)
        action = "wait (no room / not enough availability)"

        # 1) surge the NEW rs up by one if there is headroom under maxSurge
        surged = False
        if len(new_pods) < desired and total < max_total:
            new_pods.append(step)
            avail = old + new_ready(step)
            surged = True

        # 2) scale the OLD rs down as far as availability allows (>= min_avail)
        downscaled = 0
        while avail > min_avail and old > 0:
            old -= 1
            avail -= 1
            downscaled += 1

        parts = []
        if surged:
            parts.append(f"surge NEW +1 (total {old + len(new_pods)} <= {max_total})")
        if downscaled:
            parts.append(f"scale OLD -{downscaled} (avail {avail} >= {min_avail})")
        if parts:
            action = " + ".join(parts)

        steps.append(snap(step, action))
    return steps, max_total, min_avail


def recreate_update(desired, ready_lag=1):
    """Simulate the Recreate strategy: kill ALL old pods, THEN create new ones.

    There is a DOWNTIME window: a step where 0 pods are available. This is the
    trade-off vs RollingUpdate - guaranteed single-version, at the cost of an
    outage. Used when two versions cannot coexist (schema migration, singleton).
    """
    old = desired
    new_pods = []
    steps = [{"step": 0, "old": old, "new": 0, "available": old,
              "action": "start: v1 at desired"}]
    step = 0
    # phase 1: kill all old (no new created yet)
    while old > 0:
        step += 1
        old -= 1
        steps.append({"step": step, "old": old, "new": 0, "available": old,
                      "action": "Recreate: scale v1 -1 (kill before create)"})
    # phase 2: create all new
    avail = 0
    while len(new_pods) < desired:
        step += 1
        new_pods.append(step)
        avail = sum(1 for s in new_pods if s + ready_lag <= step)
        steps.append({"step": step, "old": 0, "new": len(new_pods),
                      "available": avail,
                      "action": "Recreate: scale v2 +1 (create after kill)"})
    # settle: wait for the last pods to become ready
    while avail < desired:
        step += 1
        avail = sum(1 for s in new_pods if s + ready_lag <= step)
        steps.append({"step": step, "old": 0, "new": desired,
                      "available": avail, "action": "settle: readiness catching up"})
    return steps


def self_heal(desired, death_steps):
    """Model ReplicaSet self-healing.

    death_steps : list of step indices at which a Pod dies.
    The ReplicaSet reconcile loop notices desired != actual on the next step
    and creates a replacement, restoring actual == desired.
    Returns events: (step, desired, actual, event).
    """
    events = []
    actual = desired
    events.append((0, desired, actual, "steady state: replicas match desired"))
    for ds in sorted(death_steps):
        actual -= 1
        events.append((ds, desired, actual,
                       "pod died (node loss / crash / eviction)"))
        actual += 1
        events.append((ds + 1, desired, actual,
                       f"RS reconcile: desired={desired} != actual={actual - 1} "
                       f"-> create 1 replacement"))
    return events


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_rollout(steps, max_total, min_avail, old_label="v1", new_label="v2"):
    print(f"  {'step':>4}  {old_label+' RS':>7}  {new_label+' RS':>7}  "
          f"{'total':>5}  {'avail':>5}  action")
    print(f"  {'----':>4}  {'-'*7:>7}  {'-'*7:>7}  {'-'*5:>5}  {'-'*5:>5}  ------")
    for s in steps:
        print(f"  {s['step']:>4}  {s['old']:>7}  {s['new']:>7}  "
              f"{s['total']:>5}  {s['available']:>5}  {s['action']}")


def guardrail_check(steps, max_total, min_avail):
    """Return (ok_total, ok_avail) - both guardrails hold at every step."""
    ok_total = all(s["total"] <= max_total for s in steps)
    ok_avail = all(s["available"] >= min_avail for s in steps)
    return ok_total, ok_avail


# ============================================================================
# 3. PRETTY SCENARIOS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the hierarchy Deployment -> ReplicaSet -> Pods
# ----------------------------------------------------------------------------

def section_hierarchy():
    banner("SECTION A: Deployment -> ReplicaSet -> Pods  (the hierarchy)")
    desired = 3
    print(f"A Deployment named 'web' wants {desired} replicas of image 'web:v1'.")
    print("It does NOT create Pods directly. It creates ONE ReplicaSet per pod")
    print("template revision (named with a pod-template-hash), and that ReplicaSet")
    print("creates and owns the Pods.\n")
    pods = [f"web-{h}-abcd{i}" for i, h in zip(range(desired), ["7b9c"] * desired)]
    rs = "web-7b9c"
    print(f"  Deployment: web              (desired: {desired}, template: image=web:v1)")
    print(f"    └─ ReplicaSet: {rs}        (selector: app=web, template-hash=7b9c)")
    for p in pods:
        print(f"         └─ Pod: {p}      (labels: app=web, pod-template-hash=7b9c)")
    print(f"\nOwnership chain:  Deployment web  --owns-->  RS {rs}  --owns-->  {desired} Pods")
    print("Each object owns the one below it. The pod-template-hash ties a Pod to")
    print("ITS ReplicaSet, and a new image tag -> a new hash -> a NEW ReplicaSet.\n")
    print("Who does what:")
    print("  Deployment : holds desired count + pod template; drives rollouts.")
    print("  ReplicaSet : enforces actual == desired; SELF-HEALS lost pods (Section E).")
    print("  Pod        : the disposable worker; the only thing that actually runs.")


# ----------------------------------------------------------------------------
# SECTION B: rolling update (interleaved, guardrailed)
# ----------------------------------------------------------------------------

def section_rolling_update():
    banner("SECTION B: RollingUpdate - interleaved scale up/down, two guardrails")
    print("On a template change (e.g. image web:v1 -> web:v2) the Deployment creates")
    print("a NEW ReplicaSet (new hash) and rolls pods from the old RS to the new one.")
    print("The controller NEVER violates either guardrail:\n")
    print("  (1) total     <= replicas + maxSurge          (bound resource cost)")
    print("  (2) available >= replicas - maxUnavailable    (bound downtime)\n")
    print("Canonical scenario: replicas=3, maxSurge=1, maxUnavailable=0, ready_lag=1.\n")

    desired, surge, unavail = 3, 1, 0
    steps, max_total, min_avail = rolling_update(desired, surge, unavail)
    print(f"Guardrails: total <= {max_total}, available >= {min_avail}\n")
    print_rollout(steps, max_total, min_avail)
    ok_t, ok_a = guardrail_check(steps, max_total, min_avail)
    print(f"\n[check] total <= replicas+maxSurge ({max_total}) at every step?  {ok_t}")
    print(f"[check] available >= replicas-maxUnavailable ({min_avail}) at every step?  {ok_a}")
    print("\nRead the sawtooth: the v2 RS surges +1 (total hits 4), then once that")
    print("pod is ready the v1 RS scales -1 (avail stays 3). Repeat until v1=0.")
    print("=> zero downtime (avail never below 3), at the cost of 1 extra pod (surge).")
    return steps, max_total, min_avail


# ----------------------------------------------------------------------------
# SECTION C: rollback (same machinery, reverse direction)
# ----------------------------------------------------------------------------

def section_rollback():
    banner("SECTION C: Rollback - undo rolls back to the PREVIOUS ReplicaSet")
    print("`kubectl rollout undo` makes the PREVIOUS ReplicaSet the target and")
    print("re-runs the SAME interleaved rollout, just with the roles swapped:")
    print("the current RS scales down while the previous one scales back up.\n")
    desired, surge, unavail = 3, 1, 0
    steps, max_total, min_avail = rolling_update(desired, surge, unavail)
    print("Rolling from v2 (current) BACK to v1 (previous) - same trace, swapped labels:\n")
    print(f"Guardrails: total <= {max_total}, available >= {min_avail}\n")
    print_rollout(steps, max_total, min_avail, old_label="v2", new_label="v1")
    ok_t, ok_a = guardrail_check(steps, max_total, min_avail)
    print(f"\n[check] guardrails hold during rollback too?  total:{ok_t}  avail:{ok_a}")
    print("\nWhy this works: the Deployment keeps old ReplicaSets up to")
    print("revisionHistoryLimit (default 10). Each RS is a complete snapshot of a")
    print("revision, so 'undo' = re-point the target at an existing RS and roll.")


# ----------------------------------------------------------------------------
# SECTION D: strategy RollingUpdate vs Recreate
# ----------------------------------------------------------------------------

def section_strategy():
    banner("SECTION D: strategy - RollingUpdate (default) vs Recreate")
    print("spec.strategy.type picks the rollout strategy:\n")
    print("  RollingUpdate (default): interleave up/down. Two versions briefly")
    print("    coexist. Zero downtime IF maxUnavailable=0 (needs spare capacity = surge).")
    print("  Recreate: kill ALL old pods FIRST, then create new. Guaranteed single")
    print("    version, but there is a DOWNTIME window (0 pods available).\n")

    desired = 3
    print(f"Recreate, replicas={desired} - watch the 'avail' column hit 0:\n")
    rc = recreate_update(desired)
    print(f"  {'step':>4}  {'v1 RS':>5}  {'v2 RS':>5}  {'avail':>5}  action")
    print(f"  {'----':>4}  {'-'*5:>5}  {'-'*5:>5}  {'-'*5:>5}  ------")
    for s in rc:
        print(f"  {s['step']:>4}  {s['old']:>5}  {s['new']:>5}  {s['available']:>5}  {s['action']}")
    downtime = [s for s in rc if s["available"] == 0]
    print(f"\n[check] Recreate has a downtime step (avail == 0)?  {bool(downtime)}")
    print("Use Recreate only when two versions CANNOT coexist: a breaking DB schema")
    print("migration, a singleton that must own a resource exclusively, or a job")
    print("that rejects duplicate runs. Otherwise prefer RollingUpdate.")


# ----------------------------------------------------------------------------
# SECTION E: ReplicaSet self-healing
# ----------------------------------------------------------------------------

def section_self_heal():
    banner("SECTION E: ReplicaSet self-healing - actual == desired, always")
    print("Self-healing is the ReplicaSet's job (not the Deployment's). Its")
    print("reconcile loop constantly compares desired vs actual. If a Pod")
    print("disappears - node loss, crash, eviction, manual delete - the RS sees")
    print("desired != actual and creates a replacement to restore the count.\n")
    desired = 3
    deaths = [3, 7]
    ev = self_heal(desired, deaths)
    print(f"  {'step':>4}  {'desired':>7}  {'actual':>6}  event")
    print(f"  {'----':>4}  {'-'*7:>7}  {'-'*6:>6}  -----")
    for step, d, a, desc in ev:
        print(f"  {step:>4}  {d:>7}  {a:>6}  {desc}")
    print("\nKey points:")
    print("  - The Deployment is not involved; the RS reconciles on its own.")
    print("  - Replacement is a NEW Pod (new name, same template-hash) - the dead")
    print("    one is gone for good. Stateful workloads use a StatefulSet instead,")
    print("    where a replacement keeps the same sticky identity.")
    print("  - This is why you almost never `kubectl run` a bare Pod in prod:")
    print("    a bare Pod has no ReplicaSet, so if it dies nothing recreates it.")


# ============================================================================
# 4. GOLD CHECK - available stays >= (replicas - maxUnavailable) during rollout
#    (deployment_replicaset.html recomputes this exact trace in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK: available >= replicas - maxUnavailable at EVERY rollout step")
    desired, surge, unavail = 3, 1, 0
    steps, max_total, min_avail = rolling_update(desired, surge, unavail)
    ok_t, ok_a = guardrail_check(steps, max_total, min_avail)

    # the per-step (old, new, available) trace - pinned for the .html
    trace = [(s["old"], s["new"], s["available"]) for s in steps]
    print(f"Canonical rollout (replicas={desired}, maxSurge={surge}, "
          f"maxUnavailable={unavail}):\n")
    print(f"  step  : {'  '.join(str(s['step']) for s in steps)}")
    print(f"  OLD   : {'  '.join(str(s['old']) for s in steps)}")
    print(f"  NEW   : {'  '.join(str(s['new']) for s in steps)}")
    print(f"  avail : {'  '.join(str(s['available']) for s in steps)}")
    print(f"\nGuardrails:  total <= {max_total}   |   available >= {min_avail}")
    print(f"[check] total guardrail holds every step?       {ok_t}")
    print(f"[check] available guardrail holds every step?    {ok_a}")
    # compact pins for the .html
    min_seen = min(s["available"] for s in steps)
    max_total_seen = max(s["total"] for s in steps)
    print(f"[pin] min available seen during rollout = {min_seen}  (>= {min_avail})")
    print(f"[pin] max total seen during rollout      = {max_total_seen}  (<= {max_total})")
    print(f"[pin] # reconcile steps to complete      = {len(steps) - 1}")
    print(f"[pin] final state                        = v1:{trace[-1][0]} v2:{trace[-1][1]} "
          f"avail:{trace[-1][2]}")
    assert ok_t and ok_a, "guardrail violated during rollout"
    assert min_seen == 3 and max_total_seen == 4
    assert len(steps) - 1 == 6
    assert trace[-1] == (0, 3, 3)
    print("[check] all gold pins reproduced:  OK")
    return trace


# ============================================================================
# main
# ============================================================================

def main():
    print("deployment_replicaset.py - reference simulation.")
    print("All numbers below feed DEPLOYMENT_REPLICASET.md.")
    print("python stdlib only; deterministic; no network, no clock.\n")

    section_hierarchy()
    section_rolling_update()
    section_rollback()
    section_strategy()
    section_self_heal()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
