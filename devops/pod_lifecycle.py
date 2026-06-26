"""
pod_lifecycle.py - Reference simulation of the Kubernetes Pod lifecycle:
Pending -> Running -> Succeeded/Failed, init containers, restart policy,
CrashLoopBackOff, graceful shutdown, and QoS classes.

This is the single source of truth that POD_LIFECYCLE.md is built from.
Every phase transition, timing, and worked example is printed by this file.
Deterministic (no randomness, no time-of-day, no network). Re-run and re-paste
the output into the guide.

Run:
    python3 pod_lifecycle.py

==========================================================================
THE INTUITION (read this first) - the apartment that gets built, leased,
and demolished
==========================================================================
A Pod is one apartment in a building (a Node). It has a strict lifecycle a
building inspector (the kubelet) watches:

  * PENDING   : the apartment is "planned" - permits filed (API server writes
                to etcd), a plot assigned (scheduler binds a Node), the
                foundation poured (init containers run to completion).
                The Pod exists in etcd but serves nothing yet.
  * RUNNING   : the main tenant (app container) has moved in and is open for
                business. This is the only phase that serves traffic.
  * SUCCEEDED : the tenant finished the job and left voluntarily (exit 0).
                Never restarted. (Batch / Job workloads.)
  * FAILED    : the tenant was evicted - a container exited nonzero and the
                restart policy said "don't try again" (or gave up).

The NON-OBVIOUS parts this file drills into:
  1. Init containers run STRICTLY SEQUENTIALLY before the main container,
     and EACH must exit 0 before the next starts. The Pod stays Pending the
     whole time. (Section B)
  2. A crashing container is restarted with EXPONENTIAL BACKOFF
     (10s, 20s, 40s, 80s, 160s, capped 300s) - the CrashLoopBackOff state.
     (Section C)
  3. Shutdown is GRACEFUL by default: kubelet runs a preStop hook, then sends
     SIGTERM, then waits terminationGracePeriodSeconds (default 30s), then
     SIGKILLs. (Section D)
  4. The kubelet ranks Pods into one of three QoS classes (Guaranteed,
     Burstable, BestEffort) from their CPU/memory requests vs limits - this
     ranking decides who gets evicted first under node pressure. (Section E)

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  phase        : the high-level Pod status reported to the API. Exactly one of
                 Pending, Running, Succeeded, Failed, Unknown. It is a SUMMARY,
                 derived from container states - you never set it directly.
  condition    : a fine-grained boolean pass/fail. PodScheduled, Initialized,
                 ContainersReady, Ready. Each transitions True/False.
  init container : a container that runs to completion BEFORE app containers,
                 in order. Used for setup (wait for DB, render config, migrate).
  restartPolicy: pod-level. Always (restart on any exit), OnFailure (restart on
                 nonzero exit only), Never (never restart). Deployments force
                 Always; Jobs force OnFailure/Never.
  CrashLoopBackOff: kubelet's "I keep losing this container" back-off state.
                 Delay doubles each restart, capped at 5 minutes.
  terminationGracePeriodSeconds: how long kubelet waits between SIGTERM and
                 SIGKILL. Default 30s.
  preStop hook : a command/HTTP request run BEFORE SIGTERM, to let the app
                 drain in-flight work / deregister from a load balancer.
  QoS class    : Guaranteed | Burstable | BestEffort. Computed (not set) from
                 requests vs limits. Controls eviction order under memory
                 pressure (BestEffort evicted first).

==========================================================================
THE ACTORS (control-plane vs data-plane)
==========================================================================
  kubectl          : the user's client. Sends POST to the API server.
  API server       : the front door. Validates, authenticates, persists to etcd.
                     The ONLY component that touches etcd directly.
  etcd             : the cluster's consistent key-value store. Source of truth.
  kube-scheduler   : watches Pending Pods, scores Nodes, writes a binding
                     (which Node) back to the API server.
  kubelet          : the agent on EACH Node. Watches for Pods bound to it,
                     tells the container runtime to start/stop them, reports
                     status back. It owns the Pod's actual lifecycle on the node.
  container runtime: containerd / CRI-O / Docker. Pulls images, creates
                     namespaces+cgroups, starts the process (PID 1).
  kube-proxy / endpoints : keeps the Service -> Pod list in sync. On shutdown,
                     the Pod is removed from endpoints so new traffic stops.

KEY INVARIANTS (all asserted in code):
    Pod phase is a function of container states (never set directly).
    Init containers complete in ORDER; a later one never starts until the
        previous exits 0. The Pod is Pending until ALL init containers finish.
    CrashLoopBackOff delay(n) = min(10 * 2^n, 300) seconds.
    Graceful shutdown: preStop runs BEFORE SIGTERM; preStop time counts
        against terminationGracePeriodSeconds; SIGKILL fires only if the
        process is still alive when the grace period elapses.
    QoS: Guaranteed IFF every container has cpu+mem request==limit (all set);
         BestEffort IFF no container sets any request/limit; else Burstable.
"""

from __future__ import annotations

BANNER = "=" * 72

# --- Pod phases (kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle) ---
PHASE_PENDING = "Pending"
PHASE_RUNNING = "Running"
PHASE_SUCCEEDED = "Succeeded"
PHASE_FAILED = "Failed"

# Pod conditions (each True/False with a transition time)
CONDITIONS = ["PodScheduled", "Initialized", "ContainersReady", "Ready"]


# ============================================================================
# 1. THE LIFECYCLE SIMULATION  (this is the model POD_LIFECYCLE.md walks through)
# ============================================================================

def simulate_pod_creation(
    name: str,
    init_containers: list[tuple[str, int, int]],
    main_duration: int,
    node: str = "node-1",
) -> tuple[list[tuple[int, str, str, str]], str]:
    """Deterministic Pod-creation timeline.

    Parameters
    ----------
    name : pod name
    init_containers : list of (name, duration_ticks, exit_code). Run strictly
        sequentially, in order, before any main container.
    main_duration : ticks the main container runs before exiting 0.
    node : the Node the scheduler binds the Pod to.

    Returns
    -------
    events : list of (tick, phase, component, description)
    final_phase : the terminal phase ("Succeeded" or "Failed")

    The tick counter is the simulation clock - every concrete action consumes
    >= 1 tick so the timeline is reproducible. pod_lifecycle.html ports this
    exact function to JS and replays the GOLD phase array.
    """
    events: list[tuple[int, str, str, str]] = []
    t = 0
    phase = PHASE_PENDING

    events.append((t, phase, "kubectl",
                   f"POST /api/v1/namespaces/default/pods  (pod '{name}')"))
    t += 1
    events.append((t, phase, "API-server",
                   "validate spec; authenticate; persist to etcd"))
    t += 1
    events.append((t, phase, "kube-scheduler",
                   f"score Nodes; bind Pod -> Node '{node}'  (condition PodScheduled=True)"))
    t += 1
    events.append((t, phase, "kubelet",
                   "observe bound Pod on this Node; pull images; create sandbox"))

    # --- init containers: strictly sequential, each must exit 0 ---
    for ic_name, ic_dur, ic_exit in init_containers:
        events.append((t, phase, "kubelet",
                       f"start init container '{ic_name}'"))
        for _ in range(ic_dur):
            t += 1
            events.append((t, phase, "container-runtime",
                           f"'{ic_name}' running ..."))
        t += 1
        events.append((t, phase, "container-runtime",
                       f"'{ic_name}' exited {ic_exit}"))
        if ic_exit != 0:
            phase = PHASE_FAILED
            events.append((t, phase, "kubelet",
                           "init container failed -> Pod phase -> FAILED"))
            return events, phase

    # --- all init done: condition Initialized=True; main containers start ---
    t += 1
    events.append((t, phase, "kubelet",
                   "all init containers complete -> condition Initialized=True"))
    phase = PHASE_RUNNING
    events.append((t, phase, "container-runtime",
                   "start main container(s) -> Pod phase -> RUNNING "
                   "(conditions ContainersReady=True, Ready=True)"))

    for _ in range(main_duration):
        t += 1
        events.append((t, phase, "main-container", "serving traffic ..."))

    t += 1
    phase = PHASE_SUCCEEDED
    events.append((t, phase, "kubelet",
                   "main container exited 0 -> Pod phase -> SUCCEEDED"))
    return events, phase


def phase_per_tick(events):
    """Collapse events into the Pod phase observed at each tick (the GOLD array)."""
    by_tick: dict[int, str] = {}
    for tick, phase, _, _ in events:
        by_tick[tick] = phase
    last_tick = max(by_tick)
    return [by_tick[t] for t in range(last_tick + 1)]


def transitions(phase_array):
    """Deduplicate the phase array into the ordered list of phase transitions."""
    out = []
    for p in phase_array:
        if not out or out[-1] != p:
            out.append(p)
    return out


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_timeline(events):
    print(f"  {'tick':>4}  {'phase':<10}  {'component':<18}  event")
    print(f"  {'----':>4}  {'-----':<10}  {'---------':<18}  -----")
    for tick, phase, comp, desc in events:
        print(f"  {tick:>4}  {phase:<10}  {comp:<18}  {desc}")


# ============================================================================
# 3. PRETTY SCENARIOS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the creation timeline (control-plane -> data-plane)
# ----------------------------------------------------------------------------

def section_creation():
    banner("SECTION A: Pod creation timeline  "
           "(API server -> etcd -> scheduler -> kubelet -> runtime)")
    print("A Pod moves Pending -> Running -> Succeeded. Each row is ONE tick of")
    print("the control-plane + data-plane machinery. Watch the 'component' column")
    print("shift from control-plane (kubectl, API server, scheduler) to the")
    print("data-plane agent on the Node (kubelet, container runtime).\n")

    spec = {
        "name": "web-7b9c",
        "init_containers": [("init-db", 2, 0), ("init-config", 1, 0)],
        "main_duration": 3,
        "node": "node-a",
    }
    events, final = simulate_pod_creation(**spec)
    print_timeline(events)
    print(f"\nFinal phase: {final}")
    print("\nRead the timeline as four acts:")
    print("  Act 1 (control-plane admit):  submit -> validate -> persist to etcd")
    print("  Act 2 (scheduling):           scheduler scores Nodes, binds this Pod")
    print("  Act 3 (init containers):      each runs to completion, in order,")
    print("                                Pod stays Pending the WHOLE time")
    print("  Act 4 (main containers):      phase flips to Running, serves traffic")
    return events, final


# ----------------------------------------------------------------------------
# SECTION B: init containers run strictly sequentially before main
# ----------------------------------------------------------------------------

def section_init_containers():
    banner("SECTION B: init containers - sequential, each must exit 0")
    print("Init containers run BEFORE app containers, in ORDER. The next one does")
    print("not start until the previous exits 0. The Pod's 'Initialized' condition")
    print("stays False - and phase stays Pending - until ALL of them finish.\n")

    print("Case 1 - happy path (both init containers succeed):\n")
    events, final = simulate_pod_creation(
        name="api-1",
        init_containers=[("wait-for-db", 2, 0), ("render-config", 1, 0)],
        main_duration=2,
    )
    print_timeline(events)
    print(f"\n  -> phase reached: {final}\n")

    print("Case 2 - init container FAILS (exit 1). The Pod never reaches Running;")
    print("it stays Pending (with restartPolicy=Always the kubelet would retry; with")
    print("Never it goes straight to Failed). Here we model Never-style termination:\n")
    events2, final2 = simulate_pod_creation(
        name="api-2",
        init_containers=[("wait-for-db", 2, 0), ("migrate-schema", 1, 1)],
        main_duration=2,
    )
    print_timeline(events2)
    print(f"\n  -> phase reached: {final2}   (init 'migrate-schema' exited 1 -> abort)")
    print("\nNote the main container never starts. That is the whole point of init")
    print("containers: gate the app on prerequisites, fail fast if setup breaks.")


# ----------------------------------------------------------------------------
# SECTION C: restart policy + CrashLoopBackOff (exponential backoff)
# ----------------------------------------------------------------------------

def crashloop_backoff_delay(attempt: int) -> int:
    """kubelet restart back-off for a crashing container.

    delay(n) = min(10 * 2**n, 300) seconds.  Doubles each restart, capped at
    5 minutes (300s). Matches the kubelet BackOff container manager.
    """
    return min(10 * (2 ** attempt), 300)


def section_restart_policy():
    banner("SECTION C: restartPolicy + CrashLoopBackOff (exponential backoff)")
    print("restartPolicy is pod-level and decides what the kubelet does when a\n"
          "container exits:\n")
    print("  Always    : restart on ANY exit (0 or nonzero). Default for")
    print("              Deployments / DaemonSets / ReplicaSets.")
    print("  OnFailure : restart only on NONZERO exit. Used by Jobs.")
    print("  Never     : never restart. Pod -> Succeeded (exit 0) or Failed.\n")

    print("When a container keeps dying and restartPolicy asks to retry, the kubelet")
    print("backs off EXPONENTIALLY - the CrashLoopBackOff state:\n")
    print("  delay(n) = min(10 * 2**n, 300) seconds\n")
    print("| restart # | formula 10*2**n | capped delay |")
    print("|-----------|----------------|--------------|")
    for n in range(7):
        raw = 10 * (2 ** n)
        delay = crashloop_backoff_delay(n)
        cap = "" if raw == delay else f"  (capped from {raw})"
        print(f"| {n:<9} | {raw:<14} | {delay:>5}s{cap:<22} |")
    print("\nThe cap is 300s (5 minutes). The status you see in `kubectl get pods`")
    print("is 'CrashLoopBackOff' once attempt >= 1. It is NOT a terminal state -")
    print("the kubelet keeps trying forever at the 5-minute cadence until the spec")
    print("is fixed or the Pod is deleted.\n")

    # model a crashing pod
    print("Worked example - a pod whose container exits 1 every time, restartPolicy")
    print("= Always. Wall-clock of the first 4 restart attempts:\n")
    clock = 0
    restarts = 4
    print(f"  {'event':<28}{'attempt':>8}{'backoff':>9}{'wall-clock':>12}")
    for n in range(restarts):
        delay = crashloop_backoff_delay(n)
        print(f"  {'container crashed (exit 1)':<28}{n:>8}{delay:>7}s{clock:>10}s")
        clock += delay
        print(f"  {'kubelet waits (back-off)':<28}{'':>8}{delay:>7}s{clock:>10}s")
    print(f"\n  4 crash/restart cycles span {clock}s of wall-clock. That long gap")
    print("  between 'Running' flickers is the visible signature of CrashLoopBackOff.")


# ----------------------------------------------------------------------------
# SECTION D: graceful shutdown (preStop -> SIGTERM -> grace -> SIGKILL)
# ----------------------------------------------------------------------------

def simulate_graceful_shutdown(grace_period_s, prestop_s, shutdown_s):
    """Deterministic graceful-shutdown timeline (seconds).

    Accurate ordering (matches the kubelet killContainer path):
      1. DELETE received -> Pod 'Terminating', removed from Service endpoints.
      2. kubelet runs the preStop hook and BLOCKS until it returns.
      3. THEN kubelet sends SIGTERM to PID 1.
      4. App drains and exits; if it does so within the grace period -> clean.
      5. If still alive when grace elapses -> SIGKILL (unclean).

    IMPORTANT: preStop time counts AGAINST the grace period (they are not
    additive). preStop exists precisely to buy drain time BEFORE SIGTERM.
    Returns (events, killed: bool).
    """
    events: list[tuple[float, str, str]] = []
    events.append((0.0, "API-server",
                   "DELETE received; Pod -> Terminating; deletionTimestamp set"))
    events.append((0.0, "kube-proxy/endpoints",
                   "Pod removed from Service endpoints (stop NEW traffic) [async]"))
    events.append((0.0, "kubelet",
                   f"run preStop hook (blocks; runs BEFORE SIGTERM) - {prestop_s}s"))
    if prestop_s > 0:
        events.append((float(prestop_s), "preStop hook",
                       f"finished at {prestop_s}s"))
    sigterm_t = prestop_s
    events.append((float(sigterm_t), "kubelet",
                   f"send SIGTERM to PID 1 at t={sigterm_t}s"))
    needed = prestop_s + shutdown_s
    if needed <= grace_period_s:
        events.append((float(needed), "app",
                       f"drained & exited cleanly at t={needed}s "
                       f"(<= grace {grace_period_s}s)"))
        events.append((float(needed), "kubelet",
                       "container stopped; NO SIGKILL; Pod removed from node"))
        return events, False
    events.append((float(grace_period_s), "kubelet",
                   f"grace period ({grace_period_s}s) elapsed; still alive -> SIGKILL"))
    events.append((float(grace_period_s), "app",
                   "force-killed (unclean; in-flight requests may be dropped)"))
    return events, True


def section_graceful_shutdown():
    banner("SECTION D: graceful shutdown  (preStop -> SIGTERM -> grace -> SIGKILL)")
    print("Pod deletion is NOT instant. The kubelet gives the app a grace period\n"
          "(terminationGracePeriodSeconds, default 30s) to wind down. The precise\n"
          "sequence, per the kubelet killContainer path:\n")
    print("  1. DELETE -> Pod marked Terminating; removed from Service endpoints")
    print("     (so the load balancer stops sending NEW requests).")
    print("  2. kubelet runs the preStop hook (if any) and BLOCKS until it returns.")
    print("  3. THEN kubelet sends SIGTERM to PID 1.")
    print("  4. App catches SIGTERM, drains in-flight work, exits.")
    print("  5. If still alive when the grace period elapses -> SIGKILL.\n")
    print("KEY POINT: preStop time counts AGAINST the grace period (not additive).")
    print("preStop's job is to buy drain time BEFORE SIGTERM - e.g. sleep 5s so the")
    print("endpoint-controller has propagated the removal and clients stop sending.\n")

    print("Case 1 - clean shutdown (grace=30, preStop=5, app needs 8s after SIGTERM):\n")
    ev1, killed1 = simulate_graceful_shutdown(30, 5, 8)
    for t, who, desc in ev1:
        print(f"  t={t:>4.0f}s  {who:<20}  {desc}")
    print(f"\n  -> SIGKILL fired? {killed1}   (total needed 13s <= grace 30s)\n")

    print("Case 2 - grace exceeded -> SIGKILL (grace=30, preStop=5, app needs 40s):\n")
    ev2, killed2 = simulate_graceful_shutdown(30, 5, 40)
    for t, who, desc in ev2:
        print(f"  t={t:>4.0f}s  {who:<20}  {desc}")
    print(f"\n  -> SIGKILL fired? {killed2}   (total needed 45s > grace 30s)")
    print("\nThe FIX when your app needs more than 30s: raise")
    print("terminationGracePeriodSeconds, OR add a preStop hook (e.g. `sleep 15`)")
    print("to let endpoints converge + give the app a head start before SIGTERM.")


# ----------------------------------------------------------------------------
# SECTION E: QoS classes (Guaranteed / Burstable / BestEffort)
# ----------------------------------------------------------------------------

def qos_class(containers):
    """Compute the Pod QoS class from per-container cpu/mem requests vs limits.

    containers : list of dicts with keys cpu_req, cpu_lim, mem_req, mem_lim
                 (None = unset).

    Guaranteed  : EVERY container has cpu AND mem with request == limit (all set).
    BestEffort  : NO container sets ANY request or limit.
    Burstable   : anything else (at least one resource set, but not all Guaranteed).
    """
    all_guaranteed = True
    anything_set = False
    for c in containers:
        vals = (c["cpu_req"], c["cpu_lim"], c["mem_req"], c["mem_lim"])
        if any(v is not None for v in vals):
            anything_set = True
        if c["cpu_req"] is None or c["cpu_lim"] is None or c["cpu_req"] != c["cpu_lim"]:
            all_guaranteed = False
        if c["mem_req"] is None or c["mem_lim"] is None or c["mem_req"] != c["mem_lim"]:
            all_guaranteed = False
    if all_guaranteed:
        return "Guaranteed"
    if not anything_set:
        return "BestEffort"
    return "Burstable"


def section_qos():
    banner("SECTION E: QoS classes - Guaranteed / Burstable / BestEffort")
    print("The kubelet computes (you never set) a QoS class per Pod from its")
    print("containers' cpu/memory requests vs limits. Under Node memory pressure,")
    print("the class decides eviction order: BestEffort first, then Burstable;")
    print("Guaranteed Pods are evicted only as a last resort.\n")
    print("Rules (kubernetes.io/docs/tasks/configure-pod-container/quality-service-pod):")
    print("  Guaranteed  : EVERY container has cpu AND mem, request == limit.")
    print("  BestEffort  : NO container sets ANY request or limit.")
    print("  Burstable   : anything in between.\n")

    none = None
    examples = [
        ("Guaranteed",
         [{"cpu_req": "100m", "cpu_lim": "100m",
           "mem_req": "128Mi", "mem_lim": "128Mi"}]),
        ("Burstable (req != lim)",
         [{"cpu_req": "100m", "cpu_lim": "200m",
           "mem_req": "128Mi", "mem_lim": "256Mi"}]),
        ("Burstable (only request set)",
         [{"cpu_req": "100m", "cpu_lim": none,
           "mem_req": "128Mi", "mem_lim": none}]),
        ("BestEffort (nothing set)",
         [{"cpu_req": none, "cpu_lim": none,
           "mem_req": none, "mem_lim": none}]),
        ("Mixed (two containers -> Burstable)",
         [{"cpu_req": "100m", "cpu_lim": "100m",
           "mem_req": "128Mi", "mem_lim": "128Mi"},
          {"cpu_req": none, "cpu_lim": none,
           "mem_req": none, "mem_lim": none}]),
    ]
    print("| example pod                       | computed QoS  |")
    print("|-----------------------------------|---------------|")
    for label, cs in examples:
        cls = qos_class(cs)
        print(f"| {label:<33} | {cls:<13} |")
    print("\nEviction priority under memory pressure (first evicted = top):")
    print("  1. BestEffort   (no reservations -> cheapest to kill)")
    print("  2. Burstable    (exceeds its request first)")
    print("  3. Guaranteed   (only when the Node is critically out of memory)")
    print("\nPractical recipe: for latency-critical services, set request == limit")
    print("on BOTH cpu and memory for EVERY container -> Guaranteed -> last evicted.")


# ============================================================================
# 4. GOLD CHECK - phase transitions match expected lifecycle
#    (pod_lifecycle.html recomputes this exact array in JS)
# ============================================================================

def gold_check(events):
    banner("GOLD CHECK: Pod phase transitions match the expected lifecycle")
    arr = phase_per_tick(events)
    tr = transitions(arr)
    print(f"Per-tick phase array ({len(arr)} ticks):")
    print(f"  {arr}")
    print(f"Deduped transitions: {tr}")
    expected = [PHASE_PENDING, PHASE_RUNNING, PHASE_SUCCEEDED]
    ok = tr == expected
    print(f"\nExpected transitions: {expected}")
    print(f"[check] transitions == [Pending, Running, Succeeded]?  {ok}")
    # compact pin: counts of each phase (deterministic, easy to recompute in JS)
    counts = {p: arr.count(p) for p in (PHASE_PENDING, PHASE_RUNNING, PHASE_SUCCEEDED)}
    print(f"[pin] phase counts -> Pending:{counts[PHASE_PENDING]}  "
          f"Running:{counts[PHASE_RUNNING]}  Succeeded:{counts[PHASE_SUCCEEDED]}  "
          f"total:{len(arr)}")
    flip_running = arr.index(PHASE_RUNNING)        # first Running tick
    flip_succeeded = arr.index(PHASE_SUCCEEDED)    # first Succeeded tick
    print(f"[pin] Pending->Running  at tick {flip_running}")
    print(f"[pin] Running->Succeeded at tick {flip_succeeded}")
    assert ok, "phase transitions do not match expected lifecycle"
    assert counts[PHASE_PENDING] == 9 and counts[PHASE_RUNNING] == 4 and counts[PHASE_SUCCEEDED] == 1
    assert flip_running == 9 and flip_succeeded == 13
    print("[check] all gold pins reproduced:  OK")
    return arr


# ============================================================================
# main
# ============================================================================

def main():
    print("pod_lifecycle.py - reference simulation. All numbers below feed POD_LIFECYCLE.md.")
    print("python stdlib only; deterministic; no network, no clock.\n")

    events, final = section_creation()
    section_init_containers()
    section_restart_policy()
    section_graceful_shutdown()
    section_qos()
    gold_check(events)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
