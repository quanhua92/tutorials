"""
rolling_update.py - Reference simulation of the Kubernetes RollingUpdate
strategy: gradually replacing old Pods with new ones, one reconcile pass at a
time, while NEVER breaking two guardrails.

This is the single source of truth that ROLLING_UPDATE.md is built from. Every
pod count, rollout step, and worked example below is printed by this file.
Deterministic (no randomness, no network, no clock). Re-run and re-paste.

Run:
    python3 rolling_update.py

==========================================================================
THE INTUITION (read this first) - the relay race with the handoff zone
==========================================================================
Picture a relay race. You have a team of `replicas` runners all wearing the OLD
jersey (v1). You want every one of them to swap into the NEW jersey (v2) WITHOUT
the team ever dropping below a quorum of runners on the track. You can't just
yank everyone off at once - the baton would hit the floor (downtime).

A RollingUpdate is the coach's plan for that swap, defined by two knobs:

  * maxSurge       : how many EXTRA runners (above `replicas`) may briefly be on
                     the track. Lets the coach put a v2 runner ON before pulling
                     a v1 runner OFF. Costs a little extra capacity (resource).
  * maxUnavailable : how many runners may be OFF the track at once. Lets the
                     coach pull a v1 runner OFF before a v2 runner is ready.
                     Costs a little capacity (availability).

The coach interleaves the swap and is FORBIDDEN from ever breaking EITHER rule:
  (1) runners on track  <= replicas + maxSurge        (never too many people)
  (2) runners ready     >= replicas - maxUnavailable  (never too few ready)

Zero downtime means (2) is tight: with maxUnavailable=0 you always keep ALL
`replicas` ready, paying for it with maxSurge spare pods. With maxUnavailable>0
you accept a brief capacity dip in exchange for cheaper (or zero) surge.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  RollingUpdate  : the DEFAULT Deployment strategy. Replaces pods gradually,
                   v1 -> v2, two versions briefly coexisting. Zero downtime when
                   maxUnavailable=0.
  replicas       : the desired Pod count the Deployment wants on the track.
  maxSurge       : max EXTRA pods (above replicas) allowed DURING the rollout.
                   int OR percent. Percent rounds UP (ceil). Bounds scale-UP.
                   Default 25%. Cannot be 0 when maxUnavailable is 0.
  maxUnavailable : max pods allowed UNAVAILABLE (below replicas) DURING rollout.
                   int OR percent. Percent rounds DOWN (floor). Bounds scale-DOWN
                   (= tolerated downtime). Default 25%. Cannot be 0 when
                   maxSurge is 0.
  available      : a pod that is Running AND has PASSED its readiness probe. Only
                   available pods serve traffic / count toward the quorum.
  readiness gate : a new v2 pod contributes to `available` ONLY after its
                   readiness probe succeeds. Until then it is "pending" - it
                   exists and consumes a slot, but does not serve. With
                   maxUnavailable=0 the controller CANNOT remove a v1 pod until a
                   v2 pod clears this gate (Section C).
  readiness_lag  : model for image-pull + probe time. A pod created at step s
                   passes readiness at step s + readiness_lag.
  rollback       : `kubectl rollout undo` re-points the target at a PREVIOUS
                   ReplicaSet and runs the SAME rollout in reverse (Section D).
  progressDeadlineSeconds : (default 600) if the rollout makes no progress within
                   this window, the Deployment is marked Progressing=False /
                   ProgressDeadlineExceeded and the rollout HALTS (Section E).
  terminating pod : a pod being shut down. K8s does NOT count terminating pods as
                   available, and they linger until terminationGracePeriodSeconds
                   expires (so total resources can briefly exceed replicas+
                   maxSurge).

==========================================================================
THE TWO GUARDRAILS (the invariant this whole bundle proves)
==========================================================================
During a RollingUpdate the Deployment controller NEVER violates EITHER:
    (1)  total_pods     <= replicas + maxSurge
    (2)  available_pods >= replicas - maxUnavailable

(1) bounds resource cost; (2) bounds downtime. Every reconcile pass the
controller (a) PROMOTES v2 pods that just passed readiness, (b) SURGES the new
ReplicaSet up as far as maxSurge headroom allows, then (c) DRAINS old v1 pods as
far as availability allows. With readiness lag this yields the classic
interleaved sawtooth: surge, wait-for-ready, drain, surge, ...

This file ASSERTS both guardrails hold at EVERY step of the canonical rollout -
that is the GOLD CHECK, and rolling_update.html re-derives it in JS.

PERCENT ROUNDING (verified against kubernetes.io deployment docs):
    maxSurge       = ceil(replicas * pct / 100)   # rounds UP
    maxUnavailable = floor(replicas * pct / 100)  # rounds DOWN
So the default 25%/25% on 5 replicas = maxSurge 2, maxUnavailable 1.

References (all verified against the docs + asserted in code):
    Deployment strategy:  kubernetes.io/docs/.../deployment/#strategy
    maxSurge/maxUnavailable rounding + mutual-zero rule:
                          kubernetes.io/docs/.../deployment/#rolling-update-deployment
    Progress deadline / halt: kubernetes.io/docs/.../deployment/#progress-deadline-seconds
    Rolling back:         kubernetes.io/docs/.../deployment/#rolling-back-a-deployment
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 1. THE MODEL  (this is the code ROLLING_UPDATE.md walks through)
# ============================================================================

def pct_to_int(replicas, pct, round_up):
    """Convert a percent to an int pod count, the way Kubernetes does.

    maxSurge rounds UP (ceil); maxUnavailable rounds DOWN (floor).
    Verified against kubernetes.io/docs/concepts/.../deployment/#strategy.
    """
    if round_up:
        return -(-replicas * pct // 100)        # ceil(a/b)
    return replicas * pct // 100                 # floor(a/b)


def rolling_update(replicas, max_surge, max_unavailable, readiness_lag=1,
                   fails_readiness=False, progress_window=4, max_steps=120):
    """Pod-level RollingUpdate simulation (the ground-truth model).

    Each reconcile step, in order:
      (1) PROMOTE: v2 pods created at step s whose s + readiness_lag <= now
          pass their readiness probe and flip pending -> ready (available).
          If `fails_readiness`, they NEVER promote (broken image / bad probe).
      (2) SURGE:   scale the new ReplicaSet UP as far as maxSurge headroom
          allows: create min(replicas+maxSurge - total, replicas - new) pods.
      (3) DRAIN:   terminate old v1 pods while available > replicas -
          maxUnavailable (as many as availability tolerates).

    Guardrails (asserted at every snapshot):
        total     <= replicas + max_surge
        available >= replicas - max_unavailable

    Stall / halt: if pending v2 pods exist and none became ready in the last
        `progress_window` steps, the rollout HALTs (Progressing=False,
        reason=ProgressDeadlineExceeded) - models progressDeadlineSeconds.

    Pod states in the returned grid:
        v1 + "ready"  : old pod, serving.
        v2 + "pend"   : new pod, created but readiness probe not yet passed.
        v2 + "ready"  : new pod, readiness passed, serving.

    Returns dict with: snapshots, max_total, min_avail, halted, halt_reason.
    Each snapshot: {step, action, v1, v2, v2_ready, avail, total, pods}.
    """
    max_total = replicas + max_surge
    min_avail = max(replicas - max_unavailable, 0)

    v1 = [{"v": "v1", "st": "ready", "id": i} for i in range(replicas)]
    v2 = []
    next_id = 0

    def ready_v1():
        return sum(1 for p in v1 if p["st"] == "ready")

    def ready_v2():
        return sum(1 for p in v2 if p["st"] == "ready")

    def total():
        return len(v1) + len(v2)

    def avail():
        return ready_v1() + ready_v2()

    snapshots = []

    def snap(step, action):
        snapshots.append({
            "step": step, "action": action,
            "v1": len(v1), "v2": len(v2),
            "v2_ready": ready_v2(),
            "avail": avail(), "total": total(),
            "pods": [dict(p) for p in v1] + [dict(p) for p in v2],
        })

    snap(0, "start: %d x v1 (ready), 0 x v2" % replicas)
    step = 0
    last_progress = 0                  # last step at which a v2 pod became ready
    halted = False
    halt_reason = ""
    while (len(v2) < replicas or len(v1) > 0 or avail() < replicas) \
            and step < max_steps:
        step += 1
        parts = []

        # (1) PROMOTE - readiness gate
        promoted = 0
        for p in v2:
            if p["st"] == "pend" and not fails_readiness \
                    and p["born"] + readiness_lag <= step:
                p["st"] = "ready"
                promoted += 1
        if promoted:
            parts.append("v2 readiness OK +%d (probe passed)" % promoted)
            last_progress = step

        # (2) SURGE - new ReplicaSet up, bounded by maxSurge headroom
        room = max_total - total()
        create_n = min(room, replicas - len(v2))
        if create_n > 0:
            for _ in range(create_n):
                v2.append({"v": "v2", "st": "pend", "id": next_id, "born": step})
                next_id += 1
            parts.append("surge v2 +%d (total %d <= %d)" %
                         (create_n, total(), max_total))

        # (3) DRAIN - old ReplicaSet down, bounded by maxUnavailable
        down = 0
        while avail() > min_avail and len(v1) > 0:
            v1.pop(0)
            down += 1
        if down:
            parts.append("drain v1 -%d (avail %d >= %d)" %
                         (down, avail(), min_avail))

        action = " | ".join(parts) if parts else "wait (no room / not ready)"
        snap(step, action)

        # stall detection -> halt (progressDeadlineSeconds exceeded)
        pending = sum(1 for p in v2 if p["st"] == "pend")
        if pending > 0 and (step - last_progress) >= progress_window:
            halted = True
            halt_reason = ("no v2 pod became ready in %d steps -> "
                           "ProgressDeadlineExceeded (HALT)" % progress_window)
            break

    return {
        "snapshots": snapshots, "max_total": max_total,
        "min_avail": min_avail, "halted": halted, "halt_reason": halt_reason,
    }


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def pod_cell(p):
    """One grid cell: v1 ready, v2 pending (.), or v2 ready."""
    if p["v"] == "v1":
        return "v1"                       # old, serving
    return "v2" if p["st"] == "ready" else "v2."   # v2 ready / v2 pending


def pod_grid(pods):
    return "[" + "][".join(pod_cell(p) for p in pods) + "]"


def print_rollout(res, show_grid=False):
    """Print the per-step trace. If show_grid, also print the pod grid per step."""
    snaps = res["snapshots"]
    print(f"  {'step':>4}  {'v1':>3}  {'v2':>3}  {'v2rdy':>5}  "
          f"{'total':>5}  {'avail':>5}  action")
    print(f"  {'----':>4}  {'---':>3}  {'---':>3}  {'-----':>5}  "
          f"{'-----':>5}  {'-----':>5}  ------")
    for s in snaps:
        print(f"  {s['step']:>4}  {s['v1']:>3}  {s['v2']:>3}  "
              f"{s['v2_ready']:>5}  {s['total']:>5}  {s['avail']:>5}  "
              f"{s['action']}")
        if show_grid:
            print(f"        grid: {pod_grid(s['pods'])}")
    if res["halted"]:
        print(f"\n  !! HALTED at step {snaps[-1]['step']}: {res['halt_reason']}")


def guardrail_check(res):
    """Return (ok_total, ok_avail) - both guardrails hold at every snapshot."""
    snaps = res["snapshots"]
    max_total = res["max_total"]
    min_avail = res["min_avail"]
    ok_t = all(s["total"] <= max_total for s in snaps)
    ok_a = all(s["avail"] >= min_avail for s in snaps)
    return ok_t, ok_a


def compact_trace(res):
    """One-line summary: OLD, NEW, avail arrays."""
    snaps = res["snapshots"]
    old = "  ".join(str(s["v1"]) for s in snaps)
    new = "  ".join(str(s["v2"]) for s in snaps)
    av = "  ".join(str(s["avail"]) for s in snaps)
    return old, new, av


# ============================================================================
# 3. THE SCENARIOS  (each maps to a section of ROLLING_UPDATE.md)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the canonical rollout - 5 replicas, maxSurge=1, maxUnavailable=1
# ----------------------------------------------------------------------------

def section_canonical():
    banner("SECTION A: canonical rollout - 5 replicas, maxSurge=1, maxUnavailable=1")
    print("Five v1 pods (all ready). We change the image to v2. The Deployment")
    print("creates a NEW ReplicaSet (new pod-template-hash) and rolls pods over,")
    print("one reconcile pass at a time, never breaking either guardrail:\n")
    print("  (1) total     <= replicas + maxSurge       = 5 + 1 = 6")
    print("  (2) available >= replicas - maxUnavailable = 5 - 1 = 4\n")
    res = rolling_update(5, 1, 1)
    print_rollout(res, show_grid=True)
    ok_t, ok_a = guardrail_check(res)
    print(f"\n[check] total <= 6 at every step?     {ok_t}")
    print(f"[check] available >= 4 at every step?  {ok_a}")
    print("\nRead the staircase: every step the new RS surges ONE v2 pod (a spare")
    print("slot opens under maxSurge), and because maxUnavailable=1 the controller")
    print("immediately drains ONE v1 pod. So v1 walks 5->4->3->2->1->0 while v2")
    print("walks 0->1->2->3->4->5 in lockstep. Availability dips to exactly 4")
    print("(= replicas - maxUnavailable) and never lower -> zero outage, one pod")
    print("of tolerated capacity loss, no extra pods left running at the end.")
    print("\nLegend:  [v1] old serving   [v2.] new starting (readiness pending)"
          "\n         [v2] new serving (readiness passed)")
    return res


# ----------------------------------------------------------------------------
# SECTION B: maxSurge / maxUnavailable combos (the knobs)
# ----------------------------------------------------------------------------

def section_combos():
    banner("SECTION B: the knobs - maxSurge & maxUnavailable combos")
    print("These two ints are the ENTIRE tuning surface of a rolling update.\n")
    print("  maxSurge       -> scale-UP speed & extra capacity needed.")
    print("  maxUnavailable -> scale-DOWN speed & capacity you're willing to lose.\n")
    print("Percent values round DIFFERENTLY (kubernetes.io verified):")
    print("  maxSurge rounds UP, maxUnavailable rounds DOWN.\n")

    repl = 5
    d_surge = pct_to_int(repl, 25, round_up=True)
    d_unavail = pct_to_int(repl, 25, round_up=False)
    print(f"Default 25%/25% on {repl} replicas -> "
          f"maxSurge=ceil({repl}*25/100)={d_surge}, "
          f"maxUnavailable=floor({repl}*25/100)={d_unavail}\n")

    cases = [
        ("default 25%/25%", d_surge, d_unavail, "fast & cheap: surge 2, lose 1"),
        ("maxSurge=1, maxUnavailable=0", 1, 0, "zero capacity loss, needs 1 spare"),
        ("maxSurge=0, maxUnavailable=1", 0, 1, "never exceed replicas, lose 1"),
        ("maxSurge=0, maxUnavailable=0", 0, 0, "ILLEGAL: cannot roll (no room)"),
    ]
    print(f"  {'combo':>32}  {'surge':>5}  {'unavail':>7}  "
          f"{'minAvail':>8}  {'maxTotal':>8}  {'steps':>5}  note")
    print(f"  {'-'*32}  {'-'*5}  {'-'*7}  {'-'*8}  {'-'*8}  {'-'*5}  ----")
    for name, sg, un, note in cases:
        if sg == 0 and un == 0:
            print(f"  {name:>32}  {sg:>5}  {un:>7}  {'--':>8}  "
                  f"{'--':>8}  {'stuck':>5}  {note}")
            continue
        res = rolling_update(repl, sg, un)
        steps = len(res["snapshots"]) - 1
        print(f"  {name:>32}  {sg:>5}  {un:>7}  {res['min_avail']:>8}  "
              f"{res['max_total']:>8}  {steps:>5}  {note}")

    print("\nWhat the trade-off looks like (5 replicas):\n")
    for name, sg, un, _ in cases[:3]:
        res = rolling_update(repl, sg, un)
        old, new, av = compact_trace(res)
        print(f"  {name}:")
        print(f"    OLD   : {old}")
        print(f"    NEW   : {new}")
        print(f"    avail : {av}")
        print(f"    guardrails: total<={res['max_total']}, avail>={res['min_avail']}\n")

    print("RULE (verified): maxSurge=0 AND maxUnavailable=0 is REJECTED - the")
    print("controller has neither room to surge nor capacity to spare, so the")
    print("rollout cannot start. At least one of the two must be > 0.")
    print("\nMental model: maxSurge buys SPEED with EXTRA PODS; maxUnavailable")
    print("buys SPEED with LOST CAPACITY. Zero-downtime-with-no-spare is")
    print("impossible - you must spend one or the other.")


# ----------------------------------------------------------------------------
# SECTION C: the readiness gate
# ----------------------------------------------------------------------------

def section_readiness_gate():
    banner("SECTION C: the readiness gate - no v1 dies until a v2 is ready")
    print("A new pod is NOT 'available' just because it is Running. It must PASS")
    print("its readiness probe first. With maxUnavailable=0 this becomes a HARD")
    print("gate: the controller cannot terminate a v1 pod until a v2 pod clears")
    print("readiness, otherwise available would drop below replicas.\n")
    print("Case 1: maxSurge=1, maxUnavailable=0, readiness_lag=1 (snappy probe).\n")
    res = rolling_update(5, 1, 0, readiness_lag=1)
    print_rollout(res)
    ok_t, ok_a = guardrail_check(res)
    print(f"\n[check] total <= 6 at every step?     {ok_t}")
    print(f"[check] available >= 5 at every step?  {ok_a}")
    print("\nNotice the SHAPE differs from Section A: because maxUnavailable=0,")
    print("the drain is BLOCKED until the surged v2 becomes ready. So total")
    print("oscillates 5->6 (surge) ->5 (drain) instead of staying flat, and")
    print("availability holds rock-steady at 5. The readiness probe is literally")
    print("the door the v2 pod must walk through before a v1 pod is shown out.\n")
    print("Case 2: same knobs but readiness_lag=3 (slow probe, e.g. cold start).\n")
    res2 = rolling_update(5, 1, 0, readiness_lag=3)
    print_rollout(res2)
    print("\nA slower probe does NOT change the guardrails - it only STRETCHES the")
    print(f"timeline ({len(res2['snapshots'])-1} steps vs {len(res['snapshots'])-1})."
          " The v2 pod sits 'pending' (v2.) for 3 steps before it is ready, and")
    print("the v1 pod is held alive that whole time. This is why a misconfigured")
    print("readiness probe is the #1 cause of slow rollouts - the gate never opens.")


# ----------------------------------------------------------------------------
# SECTION D: rollback (kubectl rollout undo)
# ----------------------------------------------------------------------------

def section_rollback():
    banner("SECTION D: rollback - kubectl rollout undo reverses the process")
    print("`kubectl rollout undo` does NOT re-download an old image. It re-points")
    print("the rollout target at a PREVIOUS ReplicaSet (kept up to")
    print("revisionHistoryLimit, default 10) and runs the SAME interleaved")
    print("rollout - just with the roles swapped: the now-current v2 RS drains")
    print("while the previous v1 RS surges back. Same guardrails, same shape.\n")
    print("Combined timeline: forward (v1->v2) then undo (v2->v1).\n")
    fwd = rolling_update(5, 1, 1)
    back = rolling_update(5, 1, 1)   # identical shape; labels swap
    fo, fn, fa = compact_trace(fwd)
    print("  FORWARD  v1->v2 :")
    print(f"    v2(new): {fn}")
    print(f"    avail  : {fa}")
    print(f"    guardrails: total<={fwd['max_total']}, avail>={fwd['min_avail']}")
    n = len(fwd["snapshots"])
    print("\n  --- kubectl rollout undo deployment/web ---\n")
    print("  UNDO     v2->v1 :")
    print(f"    v1(new): {fn}")
    print(f"    avail  : {fa}")
    print(f"    guardrails: total<={back['max_total']}, avail>={back['min_avail']}")
    print(f"\nThe undo trace is the forward trace played back: v2 drops {n-1}->0")
    print("while v1 climbs 0->{n-1}. Availability never breaks. Because each RS is"
          "\na full snapshot of a revision, undo is cheap and instant to start -"
          "\nno image re-pull, no template reconstruction, just re-scale.")
    ok_t, ok_a = guardrail_check(back)
    print(f"\n[check] guardrails hold during rollback?  total:{ok_t}  avail:{ok_a}")


# ----------------------------------------------------------------------------
# SECTION E: health monitoring -> halt (progressDeadlineSeconds)
# ----------------------------------------------------------------------------

def section_health_halt():
    banner("SECTION E: health monitoring - bad rollout HALTS (progressDeadline)")
    print("The Deployment WATCHES the rollout. If the new pods keep failing their")
    print("readiness probe (bad image, crash loop, broken config), no v2 pod ever")
    print("becomes available, so the rollout makes no progress. After")
    print("progressDeadlineSeconds (default 600s) the Deployment is marked")
    print("Progressing=False / reason=ProgressDeadlineExceeded and the rollout")
    print("HALTS. The controller stops surging; the old v1 pods keep serving.\n")
    print("Simulated: 5 replicas, maxSurge=1, maxUnavailable=1, but the v2 image")
    print("never passes readiness (fails_readiness=True). Watch it stall:\n")
    res = rolling_update(5, 1, 1, fails_readiness=True, progress_window=4)
    print_rollout(res)
    print(f"\n  halted? {res['halted']}")
    print(f"  reason : {res['halt_reason']}")
    final = res["snapshots"][-1]
    print(f"\nFinal state: v1={final['v1']} (still serving), v2={final['v2']} "
          f"(all stuck 'pending'), available={final['avail']}.")
    print("The service stays UP on the old pods - Kubernetes detected the bad")
    print("release and refused to complete it. This is exactly why you set a")
    print("readiness probe + progressDeadlineSeconds: they turn a bad deploy from")
    print("an outage into an automatic, safe abort. (Higher-level controllers or")
    print("a human can then `kubectl rollout undo` to recover.)")
    print("\nDANGER note: with maxUnavailable>0 the controller may still drain a")
    print("few v1 pods before noticing the failure, so availability can dip to")
    print("replicas-maxUnavailable while it figures out the new pods are dead.")
    print("That capacity dip is the price of a non-zero maxUnavailable during a")
    print("failed rollout - another reason conservative teams set it to 0.")


# ============================================================================
# 4. GOLD CHECK - both guardrails at EVERY step of the canonical rollout
#    (rolling_update.html recomputes this exact trace in JS)
# ============================================================================

def gold_check():
    banner("GOLD CHECK: both guardrails hold at EVERY step of the 5/1/1 rollout")
    res = rolling_update(5, 1, 1)
    ok_t, ok_a = guardrail_check(res)
    old, new, av = compact_trace(res)
    print("Canonical rollout (replicas=5, maxSurge=1, maxUnavailable=1):\n")
    snaps = res["snapshots"]
    print(f"  step  : {'  '.join(str(s['step']) for s in snaps)}")
    print(f"  v1    : {old}")
    print(f"  v2    : {new}")
    print(f"  avail : {av}")
    print(f"\nGuardrails:  total <= {res['max_total']}   |   "
          f"available >= {res['min_avail']}")
    print(f"[check] total <= replicas+maxSurge ({res['max_total']}) every step?"
          f"   {ok_t}")
    print(f"[check] available >= replicas-maxUnavailable ({res['min_avail']}) "
          f"every step?  {ok_a}")
    min_seen = min(s["avail"] for s in snaps)
    max_total_seen = max(s["total"] for s in snaps)
    print(f"[pin] min available seen during rollout = {min_seen}  "
          f"(>= {res['min_avail']})")
    print(f"[pin] max total seen during rollout      = {max_total_seen}  "
          f"(<= {res['max_total']})")
    print(f"[pin] # reconcile steps to complete      = {len(snaps) - 1}")
    print(f"[pin] final state                        = v1:{snaps[-1]['v1']} "
          f"v2:{snaps[-1]['v2']} avail:{snaps[-1]['avail']}")
    assert ok_t and ok_a, "guardrail violated during canonical rollout"
    assert old == "5  4  3  2  1  0  0"
    assert new == "0  1  2  3  4  5  5"
    assert av == "5  4  4  4  4  4  5"
    assert min_seen == 4 and max_total_seen == 5
    assert len(snaps) - 1 == 6
    assert (snaps[-1]["v1"], snaps[-1]["v2"], snaps[-1]["avail"]) == (0, 5, 5)
    # percent rounding gold (kubernetes.io-verified)
    assert pct_to_int(5, 25, True) == 2    # maxSurge 25% of 5 = ceil 1.25 = 2
    assert pct_to_int(5, 25, False) == 1   # maxUnavailable 25% of 5 = floor 1.25 = 1
    assert pct_to_int(1, 25, True) == 1 and pct_to_int(1, 25, False) == 0
    print("[check] all gold pins reproduced:  OK")
    return old, new, av


# ============================================================================
# main
# ============================================================================

def main():
    print("rolling_update.py - reference simulation.")
    print("All numbers below feed ROLLING_UPDATE.md.")
    print("python stdlib only; deterministic; no network, no clock.\n")

    section_canonical()
    section_combos()
    section_readiness_gate()
    section_rollback()
    section_health_halt()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
