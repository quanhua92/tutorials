"""
kubelet_probes.py - Reference simulation of the three Kubernetes health probes
(liveness, readiness, startup), their failure semantics, and the
misconfigurations that cause cascading container restarts.

This is the single source of truth that KUBELET_PROBES.md is built from. Every
timeline, table, and restart count in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python kubelet_probes.py

============================================================================
THE INTUITION (read this first) - the doctor and the triage nurse
============================================================================
A pod runs containers. The KUBELET (the agent on each node) asks each container
three kinds of yes/no health questions on a fixed schedule. Each question is a
"probe":

  * LIVENESS  : "Are you STILL ALIVE?"  Stop answering -> KILL + RESTART.
                Like a doctor checking a pulse: no pulse, resuscitate (restart).
  * READINESS : "Are you READY FOR TRAFFIC?"  No -> pull you OUT of the Service's
                endpoint list (clients stop sending requests). DO NOT restart.
                Like a triage nurse routing patients away from a closed desk.
  * STARTUP   : "Have you FINISHED BOOTING?"  Asked FIRST; while it has not
                succeeded, liveness AND readiness are DISABLED (so a slow app,
                e.g. a JVM, is not killed mid-boot). Once it succeeds it is done
                forever and liveness/readiness take over.

The kubelet asks these by one of three METHODS (the "handler"):
  * httpGet    : HTTP GET /healthz -> status 200-399 = pass.    (most common)
  * tcpSocket  : open a TCP connection to :port -> connected = pass.
  * exec       : run a command inside the container -> exit 0 = pass.

THE GOLD QUESTION this bundle answers: given a probe schedule and an app that
goes unhealthy for a known window, HOW MANY TIMES does the container restart?
That number is deterministic, and kubelet_probes.html recomputes it live.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  kubelet             the agent on each node that runs pods and fires probes.
  liveness probe      "still alive?"  -> failureThreshold breached = KILL+RESTART
  readiness probe     "ready for traffic?" -> fail = remove from Service endpoints
                      (NOT a restart). Recovery re-adds the pod to endpoints.
  startup probe       "booted yet?" -> gates liveness/readiness until it succeeds.
  Service             a stable virtual IP/DNS that load-balances across READY pods.
  endpoints           the live list of ready pod IPs a Service forwards traffic to.
  failureThreshold    consecutive fails before action (liveness/startup: kill;
                      readiness: pull from endpoints).
  periodSeconds       seconds between probe invocations.
  initialDelaySeconds wait this long after container start before the first probe.
  successThreshold    consecutive successes needed to flip back to healthy/ready.

Reference docs: kubernetes.io "Configure Liveness, Readiness and Startup Probes".
============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Tuple

BANNER = "=" * 72

ProbeHealth = Callable[[int], bool]
# (time, kind, tag, t_rel, extra)


# ============================================================================
# 1. THE MODEL  (ProbeSpec + a deterministic time-stepped kubelet simulator)
# ============================================================================

@dataclass
class ProbeSpec:
    """One probe as you would write it under a container in a Pod manifest.

    `kind`    : which of the three probe families this is.
    `handler` : how the kubelet physically asks the question.
    """
    kind: str               # "liveness" | "readiness" | "startup"
    handler: str            # "http" | "tcp" | "exec"
    initial_delay: int      # initialDelaySeconds
    period: int             # periodSeconds
    failure_threshold: int  # failureThreshold
    success_threshold: int = 1
    # http handler specifics (shown for realism; the sim reduces any handler to
    # a single pass/fail health function, exactly as the kubelet does).
    path: str = "/healthz"
    port: int = 8080


@dataclass
class ContainerState:
    restart_count: int = 0
    ready: bool = False
    started: bool = True    # False only when a startup probe is still gating
    start_time: int = 0     # absolute second of the most recent (re)start


def run_pod(
    liveness: ProbeSpec | None,
    readiness: ProbeSpec | None,
    startup: ProbeSpec | None,
    liveness_health: ProbeHealth,
    readiness_health: ProbeHealth,
    startup_health: ProbeHealth,
    horizon: int,
    step: int = 1,
) -> Tuple[List[tuple], ContainerState]:
    """Deterministic, time-stepped simulation of ONE pod from t=0..horizon.

    The kubelet rule implemented here (matches k8s docs):
      * A probe FIRES at  t_rel = initial_delay + k*period  (k = 0,1,2,...).
      * Only ONE family is "active" at a time while booting: if a startup probe
        exists and has not succeeded, liveness AND readiness are disabled.
      * liveness/startup : failureThreshold consecutive fails  -> KILL + RESTART
        (container restart_count++, start_time reset, counters cleared).
      * readiness        : failureThreshold consecutive fails  -> NOT ready
        (pod leaves the Service endpoints; NO restart). successThreshold
        consecutive successes after that -> READY again (pod re-joins endpoints).

    Returns (events, state). Each event is a tuple whose 3rd element `tag`
    is one of: OK, FAIL, RESTART, STARTED, READY, NOT_READY.
    """
    state = ContainerState(started=(startup is None))
    consec_fail = {"startup": 0, "liveness": 0, "readiness": 0}
    consec_ok = {"startup": 0, "liveness": 0, "readiness": 0}
    events: List[tuple] = []

    def fires(spec: ProbeSpec | None, t_rel: int) -> bool:
        if spec is None:
            return False
        return (t_rel >= spec.initial_delay
                and (t_rel - spec.initial_delay) % spec.period == 0)

    t = 0
    while t <= horizon:
        restart_now = False
        t_rel = t - state.start_time

        # Which probes are due at THIS tick? (computed from state BEFORE acting)
        due: List[str] = []
        if startup is not None and not state.started and fires(startup, t_rel):
            due.append("startup")
        if state.started:
            if fires(liveness, t_rel):
                due.append("liveness")
            if fires(readiness, t_rel):
                due.append("readiness")

        for kind in due:
            spec = {"startup": startup, "liveness": liveness,
                    "readiness": readiness}[kind]
            hfn = {"startup": startup_health, "liveness": liveness_health,
                   "readiness": readiness_health}[kind]
            ok = hfn(t_rel)
            if ok:
                consec_fail[kind] = 0
                consec_ok[kind] += 1
                events.append((t, kind, "OK", t_rel, None))
                if kind == "startup" and not state.started \
                        and consec_ok[kind] >= spec.success_threshold:
                    state.started = True
                    events.append((t, "startup", "STARTED", t_rel, None))
                    # liveness/readiness begin fresh from here
                    for k in ("liveness", "readiness"):
                        consec_fail[k] = 0
                        consec_ok[k] = 0
                if kind == "readiness" and not state.ready \
                        and consec_ok[kind] >= spec.success_threshold:
                    state.ready = True
                    events.append((t, "readiness", "READY", t_rel, None))
            else:
                consec_ok[kind] = 0
                consec_fail[kind] += 1
                events.append((t, kind, "FAIL", t_rel, consec_fail[kind]))
                if kind in ("liveness", "startup") \
                        and consec_fail[kind] >= spec.failure_threshold:
                    state.restart_count += 1
                    events.append((t, kind, "RESTART", t_rel,
                                   state.restart_count))
                    restart_now = True
                    break  # container is dead; ignore any other probe this tick
                if kind == "readiness" and state.ready \
                        and consec_fail[kind] >= spec.failure_threshold:
                    state.ready = False
                    events.append((t, "readiness", "NOT_READY", t_rel, None))

        if restart_now:
            state.start_time = t
            state.started = (startup is None)
            state.ready = False
            for k in ("startup", "liveness", "readiness"):
                consec_fail[k] = 0
                consec_ok[k] = 0
        t += step

    return events, state


# ----------------------------------------------------------------------------
# Health functions: a "window" where the app returns unhealthy (http 500 /
# tcp-refused / exec!=0). All deterministic, all functions of t_rel.
# ----------------------------------------------------------------------------

def window_health(t_rel: int, bad_window: tuple | None = None) -> bool:
    """Healthy (pass) EXCEPT inside bad_window = (start, end) seconds, relative
    to the current container start. Returns True = pass (200 / ok / exit 0)."""
    if bad_window is None:
        return True
    return not (bad_window[0] <= t_rel < bad_window[1])


def boot_health(t_rel: int, boot_done: int) -> bool:
    """Probe passes only once the app has finished booting at t_rel >= boot_done.
    Models a slow-starting JVM / heavy-init service."""
    return t_rel >= boot_done


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_timeline(events: List[tuple], highlight_tags=("RESTART", "NOT_READY",
                                                        "READY", "STARTED")):
    """Print a probe event log as a compact timeline."""
    print(f"  {'t(s)':>5}  {'t_rel':>5}  {'probe':<10} {'result':<10} note")
    print(f"  {'----':>5}  {'-----':>5}  {'----------':<10} {'----------':<10} "
          "----")
    for ev in events:
        t, kind, tag, t_rel, extra = ev
        mark = " <==" if tag in highlight_tags else ""
        note = "" if extra is None else f"consec_fail={extra}" \
            if tag == "FAIL" else f"restart #{extra}"
        if tag in ("READY", "NOT_READY", "STARTED"):
            note = tag.lower().replace("_", " ")
        print(f"  {t:>5}  {t_rel:>5}  {kind:<10} {tag:<10} {note}{mark}")


# ============================================================================
# 3. SECTIONS
# ============================================================================

def section_a_kinds_and_handlers():
    banner("SECTION A: the three probe KINDS x three HANDLERS")
    print("A probe = (a KIND, a HANDLER). The KIND decides what a failure DOES;")
    print("the HANDLER decides how the question is physically ASKED.\n")
    print("KINDS (what a failure triggers):")
    print("| kind      | on failureThreshold breached           | restarts? |")
    print("|-----------|----------------------------------------|-----------|")
    print("| liveness  | KILL container + RESTART it            |    YES    |")
    print("| readiness | remove pod from Service endpoints     |    NO     |")
    print("| startup   | KILL + RESTART (boot took too long)   |    YES    |")
    print()
    print("HANDLERS (how pass/fail is measured - all reduce to one bool):")
    print("| handler   | mechanism                          | pass if          |")
    print("|-----------|------------------------------------|------------------|")
    print("| httpGet   | HTTP GET <path> on :<port>          | status 200-399   |")
    print("| tcpSocket | open TCP to :<port>                 | connection ok    |")
    print("| exec      | run command inside the container    | exit code 0      |")
    print()
    print("KEY DISTINCTION: liveness is about the CONTAINER (deadlock? restart")
    print("it). readiness is about the NETWORK (can clients reach it? route")
    print("around it). startup is a one-shot gate so slow boots are not punished.")


def section_b_liveness():
    banner("SECTION B: LIVENESS - HTTP GET /healthz every 10s, 3 fails => restart")
    spec = ProbeSpec("liveness", "http", initial_delay=0, period=10,
                     failure_threshold=3, path="/healthz", port=8080)
    print("Manifest fragment:")
    print("  livenessProbe:")
    print("    httpGet: { path: /healthz, port: 8080 }")
    print(f"    initialDelaySeconds: {spec.initial_delay}")
    print(f"    periodSeconds: {spec.period}")
    print(f"    failureThreshold: {spec.failure_threshold}")
    print()
    print("App goes unhealthy during the RELATIVE window t_rel in [40, 70):")
    print("  /healthz returns 500 for t_rel in [40,70), 200 otherwise.\n")

    def health(tr):
        return window_health(tr, (40, 70))

    events, state = run_pod(spec, None, None, health, health, health, horizon=95)
    print_timeline(events)
    print()
    print("READING THE TIMELINE:")
    print("  t=0,10,20,30 : probe OK (app healthy).")
    print("  t=40,50,60   : three CONSECUTIVE fails => failureThreshold=3 hit at")
    print("                 t=60 => kubelet KILLS the container and restarts it.")
    print(f"  => restart_count = {state.restart_count}  (gold value for the .html)")
    print()
    # independent check: time of restart == initial_delay + (FT-1)*period after
    # the FIRST failure tick (40).
    first_fail = 40
    expected_restart_tick = first_fail + (spec.failure_threshold - 1) * spec.period
    restart_ticks = [e[0] for e in events if e[2] == "RESTART"]
    print("FORMULA: restart tick = first_fail + (failureThreshold-1)*period")
    print(f"       = {first_fail} + ({spec.failure_threshold}-1)*{spec.period}"
          f" = {expected_restart_tick}")
    print(f"[check] sim restart tick {restart_ticks} == [{expected_restart_tick}]: "
          f"{'OK' if restart_ticks == [expected_restart_tick] else 'FAIL'}")
    assert state.restart_count == 1, "liveness scenario must restart exactly once"
    assert restart_ticks == [60]
    return state.restart_count, restart_ticks


def section_c_readiness():
    banner("SECTION C: READINESS - fail => leave Service endpoints (no restart)")
    spec = ProbeSpec("readiness", "http", initial_delay=0, period=10,
                     failure_threshold=1, success_threshold=1, path="/ready",
                     port=8080)
    print("Manifest fragment (note: failureThreshold=1 - pull fast, don't wait):")
    print("  readinessProbe:")
    print("    httpGet: { path: /ready, port: 8080 }")
    print(f"    periodSeconds: {spec.period}   failureThreshold: {spec.failure_threshold}")
    print()
    print("App is NOT ready during t_rel in [20, 50), ready otherwise.\n")

    def health(tr):
        return window_health(tr, (20, 50))

    events, state = run_pod(None, spec, None, health, health, health, horizon=60)
    print_timeline(events)
    print()
    print("ENDPOINT / TRAFFIC MEMBERSHIP over time (single pod):")
    print("  [ 0, 20) : READY    -> in Service endpoints   -> gets traffic")
    print("  [20, 50) : NOT READY-> removed from endpoints -> NO traffic (no restart!)")
    print("  [50, 60) : READY    -> re-added to endpoints  -> traffic resumes")
    ready_events = [e for e in events if e[2] in ("READY", "NOT_READY")]
    print(f"[check] state transitions: {[(e[0], e[2]) for e in ready_events]}")
    assert state.restart_count == 0, "readiness must NEVER restart"
    assert state.ready is True, "pod should be ready again by t=60"
    print("[check] readiness restart_count == 0 (it never restarts): OK")
    print()
    # 3-replica traffic rerouting snapshot
    print("TRAFFIC RE-ROUTING with 3 replicas (pod-B goes not-ready at t=20):")
    replicas = {"A": True, "B": True, "C": True}
    for t_step, who_down in [(10, None), (30, "B"), (55, None)]:
        if who_down:
            replicas[who_down] = False
        else:
            replicas = {k: True for k in replicas}
        up = [k for k, v in replicas.items() if v]
        share = {k: (100 / len(up) if v else 0) for k, v in replicas.items()}
        print(f"  t={t_step:>2}: endpoints={up}  "
              f"traffic% = "
              + ", ".join(f"{k}={share[k]:.0f}%" for k in sorted(replicas)))
    print("  => B's share is spread across A and C while B is sick. No restart.")


def section_d_startup():
    banner("SECTION D: STARTUP - protect a slow-booting JVM from liveness")
    print("A JVM app needs ~45s to boot. Its /healthz does not answer 200 until")
    print("t_rel >= 45. Compare two configs for the SAME slow app:\n")
    boot_done = 45
    liveness = ProbeSpec("liveness", "http", 0, 10, 3, path="/healthz")
    startup = ProbeSpec("startup", "http", 0, 10, 6, path="/startup")

    def lh(tr):
        return boot_health(tr, boot_done)

    def sh(tr):
        return boot_health(tr, boot_done)

    print("(1) NO startup probe (BAD): liveness runs from t=0, app still booting")
    ev1, st1 = run_pod(liveness, None, None, lh, lh, lh, horizon=60)
    print_timeline(ev1)
    print("   => liveness fails at t=0,10,20 -> 3 fails -> RESTART at t=20.")
    print(f"   => restart_count = {st1.restart_count}  (killed DURING boot!)\n")

    print("(2) WITH startup probe (GOOD): it gates liveness until boot succeeds")
    ev2, st2 = run_pod(liveness, None, startup, lh, lh, sh, horizon=60)
    print_timeline(ev2)
    print("   => startup keeps failing (allowed, FT=6 => up to ~60s grace) until")
    print(f"      it passes at t_rel=50; THEN liveness wakes up. restart_count = "
          f"{st2.restart_count}\n")
    print("MANIFEST fragment for the good config:")
    print("  startupProbe:   { httpGet: { path: /startup },"
          " failureThreshold: 6, periodSeconds: 10 }")
    print("  livenessProbe:  { httpGet: { path: /healthz },"
          " failureThreshold: 3, periodSeconds: 10 }")
    print()
    assert st1.restart_count >= 1 and st2.restart_count == 0, \
        "no-startup must crash-loop (>=1); with-startup must be 0"
    print(f"[check] restarts: no-startup={st1.restart_count} (crash-loop, "
          f"boot resets each restart), with-startup={st2.restart_count} "
          f" -> startup probe saved the boot: OK")
    return st1.restart_count, st2.restart_count


def section_e_misconfigs():
    banner("SECTION E: common misconfigurations that cascade")
    print("MISCONFIG 1 - too-aggressive liveness during a slow deploy/rollout.")
    print("  initialDelay=0, period=10, FT=3, app boots in ~45s => killed at t=20")
    print("  (same as Section D case 1). FIX: add a startup probe, OR raise")
    print("  initialDelaySeconds above the known boot time.\n")

    print("MISCONFIG 2 - sharing ONE endpoint between liveness AND readiness.")
    print("  If /health serves both, a slow-under-load response trips BOTH:")
    print("    readiness fail -> pod leaves endpoints (load shifts to others)")
    print("    liveness  fail -> pod is KILLED + RESTARTED (cold start -> even")
    print("                       slower -> MORE load on survivors -> they trip")
    print("                       too). This is the classic 'cascading restart'.")

    def lh(tr):
        return window_health(tr, (20, 60))  # app slow/sick under load

    shared_liveness = ProbeSpec("liveness", "http", 0, 10, 3, path="/health")
    shared_readiness = ProbeSpec("readiness", "http", 0, 10, 1, path="/health")
    ev, st = run_pod(shared_liveness, shared_readiness, None, lh, lh, lh,
                     horizon=60)
    restarts = [e[0] for e in ev if e[2] == "RESTART"]
    notready = [e[0] for e in ev if e[2] == "NOT_READY"]
    print("  sim (3 replicas, all share /health, all hit the same load spike):")
    print(f"    pod leaves endpoints at t={notready} AND restarts at t={restarts}")
    print(f"    restart_count={st.restart_count}. Leaving endpoints + restarting")
    print("    at once is the signature of the shared-endpoint anti-pattern.\n")
    print("  FIX: split them. readiness=/ready (cheap, fast), liveness=/healthz")
    print("  (deeper check, higher FT). They measure DIFFERENT things.\n")

    print("MISCONFIG 3 - liveness FT=1. A single transient hiccup (GC pause,")
    print("  one slow DB query) => immediate kill. Always use FT>=2 for liveness.")


def section_f_tuning_and_gold():
    banner("SECTION F: tuning (initialDelay/period/failureThreshold) + GOLD")
    print("Time-to-ACTION (restart for liveness/startup) measured from the FIRST")
    print("failing probe:")
    print("  action_tick = first_fail_tick + (failureThreshold - 1) * periodSeconds")
    print("Time-to-action is what you are really tuning. Bigger window = more")
    print("tolerant, but slower to recover a truly dead container.\n")
    print("| initialDelay | period | failureThreshold | tolerance window  |")
    print("|-------------|--------|------------------|-------------------|")
    rows = [(0, 10, 1), (0, 10, 3), (30, 10, 3), (0, 5, 3), (0, 10, 6)]
    for d, p, ft in rows:
        tol = (ft - 1) * p
        print(f"| {d:<11} | {p:<6} | {ft:<16} | {tol}s after 1st fail |")
    print()
    # ---- GOLD: independent re-derivation of the liveness scenario restarts ----
    print("GOLD re-derivation (must match Section B sim, and the .html):")
    # Scenario: unhealthy window [40,70), liveness period=10 FT=3, init=0.
    # Probes fire at 0,10,...,; first fail at 40; restart at 40+(3-1)*10 = 60.
    # After restart the window is relative to the new start, so abs [100,130)
    # which is beyond horizon 95 => no 2nd restart. => exactly 1 restart.
    gold_restarts = 1
    gold_restart_tick = 40 + (3 - 1) * 10
    # re-run the canonical sim

    def lh(tr):
        return window_health(tr, (40, 70))

    spec = ProbeSpec("liveness", "http", 0, 10, 3)
    ev, st = run_pod(spec, None, None, lh, lh, lh, horizon=95)
    sim_tick = [e[0] for e in ev if e[2] == "RESTART"]
    ok = (st.restart_count == gold_restarts and sim_tick == [gold_restart_tick])
    print(f"  expected: restart_count={gold_restarts}, tick=[{gold_restart_tick}]")
    print(f"  sim     : restart_count={st.restart_count}, tick={sim_tick}")
    print(f"  [check] GOLD match: {'OK' if ok else 'FAIL'}")
    assert ok, "GOLD mismatch in Section F"
    print(f"\nGOLD scalar for the .html: restart_count = {st.restart_count}, "
          f"restart_tick = {gold_restart_tick}")
    return st.restart_count, gold_restart_tick


# ============================================================================
# main
# ============================================================================

def main():
    print("kubelet_probes.py - reference simulation. All output feeds "
          "KUBELET_PROBES.md.")
    section_a_kinds_and_handlers()
    section_b_liveness()
    section_c_readiness()
    section_d_startup()
    section_e_misconfigs()
    section_f_tuning_and_gold()
    banner("DONE - all sections printed; all [check]s asserted")


if __name__ == "__main__":
    main()
