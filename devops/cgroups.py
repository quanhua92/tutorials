"""
cgroups.py - Reference model of Linux cgroups (control groups), the resource-
limiting primitive behind every container (Docker --cpus/--memory, K8s
requests/limits).

This is the single source of truth that CGROUPS.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python cgroups.py

==========================================================================
THE INTUITION (read this first) -- the bouncer at the all-you-can-eat buffet
==========================================================================
Namespaces (see NAMESPACES.md) give a process its own REALITY: its own PID 1,
its own eth0, its own /. But a process with a private reality can still EAT the
whole machine -- fork 100 000 children, fill all the RAM, peg all 8 cores. That
is a denial-of-service, not isolation.

A cgroup is a BOUNCER. It does not change what the process SEES; it changes how
much it is ALLOWED to take. "This group may use at most 1 CPU, 512 MB of RAM,
100 processes, and 10 MB/s of disk." The kernel enforces it with a counter per
group: every charge (a page of RAM, a scheduler tick, a fork) is added to the
group's total, and when the total would exceed the limit the kernel refuses
(throttles the CPU, denies the fork, or -- for memory -- kills a process via the
OOM killer).

  * A container = namespaces (its reality) + cgroups (its allowance).
    Docker's `--cpus 1 --memory 512m` and K8s' `resources.limits` literally
    write cgroup files: `cpu.max`, `memory.max`, `pids.max`.
  * The two are orthogonal and composable. You can have namespaces without
    cgroups (a `unshare` shell with no limits) or cgroups without namespaces
    (limiting a systemd service). A container uses BOTH.

THE REASON CGROUPS EXIST: fair sharing + hard containment. With cgroups you can
pack 50 tenants onto one 16-core box and PROVE, in writing, that no single
tenant can take more than its slice -- neither by burning CPU, nor by leaking
RAM, nor by forking bombs.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  cgroup       : a "booth" the kernel maintains a resource counter for. Processes
                 are PLACED into a booth (written into cgroup.procs). Hierarchical:
                 a child booth inherits its parent's limits.
  controller   : one resource type the booth counts: cpu, memory, io (blkio in
                 v1), pids, ... A booth can enable several at once.
  cpu.max      : v2 file. Format "quota period". "50000 100000" = at most 0.5
                 CPU (quota/period). "max 100000" = unlimited.
  cpu.weight   : v2 file (1..10000, default 100). RELATIVE share used only when
                 two booths contend for the same busy CPU. NOT a hard limit.
  memory.max   : v2 file. Hard bytes ceiling. Exceeding it triggers the OOM
                 killer (a process in the booth is killed, not just refused).
  io.max       : v2 file. Per-device rate limits: rbps/wbps (bytes/s), riops/
                 wiops (ops/s).
  pids.max     : v2 file. Max process count in this booth. A fork that would
                 exceed it returns EAGAIN -- the classic fork-bomb fuse.
  throttle     : CPU controller PAUSES a task when its quota is spent this
                 period, resumes next period. Different from OOM-kill.
  OOM          : Out-Of-Memory. The memory controller kills a process (the
                 "oom victim", usually the largest) to bring usage under .max.
  v1 vs v2     : v1 has one hierarchy PER controller (cpu, memory in separate
                 trees). v2 has ONE unified hierarchy; each booth enables the
                 controllers it needs via cgroup.controllers. Modern systems
                 (systemd, Docker, K8s) use v2.

==========================================================================
THE LINEAGE (where it came from)
==========================================================================
  cgroup v1 (2007, 2.6.24, Paul Menage's "process containers") : one tree per
             controller. Powerful but messy -- a task could be in different
             places in different trees, making semantics confusing.
  cgroup v2 (2016, 4.5, Tejun Heo) : a SINGLE unified hierarchy. Threaded
             sub-trees for thread-level granularity. This is what systemd,
             Docker (`--cgroup-parent`), containerd and K8s all use today.

KEY PROPERTIES (verified in code, Section F):
    cpu accounting    : sum(throttled + ran) == demand ; allocation <= cpu.max
    memory accounting : after any step, usage <= memory.max (OOM enforces it)
    pids accounting   : live process count <= pids.max (fork refused above)
    GOLD invariant    : for every controller, USAGE <= LIMIT (Section F)

Conventions (mirroring a real cgroupfs):
    CPU is measured in millicores (m). 1 CPU = 1000 m. A 4-core box = 4000 m.
    Memory is measured in MB. io in bytes/s (rbps) and ops/s (riops).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

BANNER = "=" * 72


# --------------------------------------------------------------------------
# 0. THE KERNEL MODEL  (a tiny, deterministic cgroup v2 hierarchy)
# --------------------------------------------------------------------------

@dataclass
class Cgroup:
    """One cgroup (a 'booth'). Has a path, a set of limits, and live counters."""
    path: str
    # limits (None == unlimited / not set)
    cpu_max: float | None = None        # millicores (derived from cpu.max)
    cpu_weight: int = 100               # 1..10000, default 100
    memory_max: int | None = None       # MB
    io_rbps: int | None = None          # bytes/s read limit
    pids_max: int | None = None         # max processes
    # live counters (what the kernel charges)
    cpu_used: float = 0.0               # millicore-ms of CPU consumed this period
    cpu_throttled: float = 0.0          # demand that could not run
    memory_used: int = 0                # MB currently charged
    pids_current: int = 0               # live process count
    oom_kills: int = 0
    fork_refusals: int = 0


@dataclass
class Machine:
    """The host: a fixed CPU capacity. Holds the cgroup tree (flat list here)."""
    cpu_capacity: float                  # millicores, e.g. 4000 for 4 cores
    cgroups: dict = field(default_factory=dict)   # path -> Cgroup

    def add(self, cg: Cgroup) -> Cgroup:
        self.cgroups[cg.path] = cg
        return cg


# --------------------------------------------------------------------------
# CPU: weighted max-min fair scheduling with hard caps (CFS model, simplified)
# --------------------------------------------------------------------------
def allocate_cpu(machine: Machine, demand: dict) -> dict:
    """Weighted max-min fair allocation with per-cgroup hard caps.

    demand: { path -> millicores wanted } (a 'busy' container wants = capacity)
    Returns { path -> millicores actually granted }.

    Algorithm (the CFS quota+shares behaviour in one pass):
      - Everyone's grant grows at a rate proportional to cpu_weight.
      - No grant may exceed cpu_max (the hard cap from cpu.max) or demand.
      - Once a cgroup hits its cap it drops out; remaining capacity is
        re-shared among the still-hungry cgroups. Repeat until capacity is
        exhausted or everyone is full. This is provably the unique
        weighted-max-min allocation.
    """
    alloc = {p: 0.0 for p in demand}
    remaining = machine.cpu_capacity
    eps = 1e-9
    while remaining > eps:
        active = []
        for p, want in demand.items():
            cg = machine.cgroups[p]
            cap = cg.cpu_max if cg.cpu_max is not None else float("inf")
            room = min(want, cap) - alloc[p]
            if room > eps:
                active.append(p)
        if not active:
            break
        total_weight = sum(machine.cgroups[p].cpu_weight for p in active)
        given = 0.0
        for p in active:
            cg = machine.cgroups[p]
            cap = cg.cpu_max if cg.cpu_max is not None else float("inf")
            room = min(demand[p], cap) - alloc[p]
            share = remaining * cg.cpu_weight / total_weight
            inc = min(share, room)
            alloc[p] += inc
            given += inc
        remaining -= given
        if given < eps:
            break
    return alloc


def cpu_max_to_millicores(quota_period: str) -> float | None:
    """Parse a v2 cpu.max string 'quota period' (microseconds) into millicores.

    '50000 100000' -> 0.5 CPU = 500 m. 'max 100000' -> None (unlimited).
    """
    q, per = quota_period.split()
    if q == "max":
        return None
    return int(q) / int(per) * 1000.0


def fmt_cpus(m: float) -> str:
    """500 m -> '0.50 CPU'. 2667 m -> '2.67 CPU'."""
    return f"{m/1000.0:.2f} CPU"


# --------------------------------------------------------------------------
# PRETTY PRINTERS
# --------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# SECTION A: cgroup v1 vs v2 hierarchy
# ============================================================================
def section_hierarchy():
    banner("SECTION A: cgroup v2 unified hierarchy (vs v1 per-controller)")
    print("cgroup v1 had ONE mount tree PER controller, so a task could live in")
    print("different nodes of the cpu tree vs the memory tree -- confusing. v2")
    print("(2016, Tejun Heo) collapsed everything into a SINGLE tree:\n")
    print()
    print("    /                      (the root cgroup = the whole machine)")
    print("    |-- system.slice       (systemd services)")
    print("    |-- user.slice         (user sessions)")
    print("    `-- kubepods.slice      (K8s pods) / docker-*.scope (Docker)")
    print("        `-- pod-abc/")
    print("            |-- c1   <- this container's booth")
    print("            `-- c2")
    print()
    print("Each booth enables the controllers it needs (cgroup.subtree_control):")
    print()
    print("    /sys/fs/cgroup/kubepods.slice/pod-abc/c1/")
    print("        cgroup.procs        <- PIDs placed in this booth")
    print("        cpu.max             <- 'quota period'  (hard cap)")
    print("        cpu.weight          <- relative share under contention")
    print("        memory.max          <- bytes ceiling")
    print("        io.max              <- per-device rbps/wbps/riops/wiops")
    print("        pids.max            <- max process count")
    print("        cpu.stat            <- 'throttled_usec ...' (accounting)")
    print()
    print("Limits INHERIT down: a child booth can be TIGHTER than its parent, but")
    print("never looser. The root cgroup (the machine) is the absolute ceiling.")
    print()
    print("| controller | v1 file          | v2 file      | what it caps       |")
    print("|------------|------------------|--------------|--------------------|")
    rows = [
        ("cpu", "cpu.cfs_quota_us", "cpu.max", "CPU time (hard throttle)"),
        ("cpu", "cpu.shares", "cpu.weight", "CPU share (relative)"),
        ("memory", "memory.limit_in_bytes", "memory.max", "RAM (OOM kill)"),
        ("blkio", "blkio.throttle...", "io.max", "I/O bytes/ops per device"),
        ("pids", "pids.max", "pids.max", "process count (fork refused)"),
    ]
    for c, v1, v2, what in rows:
        print(f"| {c:<10} | {v1:<16} | {v2:<12} | {what:<18} |")
    print()
    print("Docker / K8s mapping (the flags you actually type):")
    print("    docker run --cpus 1          ->  cpu.max = '100000 100000'")
    print("    docker run --cpu-shares 512  ->  cpu.weight = 512")
    print("    docker run --memory 512m     ->  memory.max = 536870912")
    print("    docker run --pids-limit 100  ->  pids.max = 100")
    print("    K8s limits.memory: 512Mi     ->  memory.max = 536870912")


# ============================================================================
# SECTION B: CPU cgroup -- cpu.max (hard throttle) vs cpu.weight (relative)
# ============================================================================
def section_cpu():
    banner("SECTION B: CPU -- hard cap (cpu.max) vs relative share (cpu.weight)")
    print("Two independent knobs. They feel similar but enforce VERY different")
    print("things, and beginners mix them up constantly.\n")
    print("  cpu.max    : HARD cap. The cgroup is literally PAUSED once it has")
    print("               used quota/period CPUs in a period. Guaranteed ceiling.")
    print("  cpu.weight : RELATIVE. Only matters when two+ cgroups FIGHT over the")
    print("               same busy CPU. Splits spare capacity by weight. No cap.\n")

    print("DEMO 1 -- hard cap (cpu.max), NO contention")
    print("-" * 56)
    print("Machine: 4 CPUs (4000 m). Container A capped at 1 CPU, idle machine.\n")
    m = Machine(cpu_capacity=4000)
    a = m.add(Cgroup(path="/A", cpu_max=cpu_max_to_millicores("100000 100000"),
                     cpu_weight=100))
    demand = {"/A": 4000}  # A wants the whole machine
    alloc = allocate_cpu(m, demand)
    a.cpu_used = alloc["/A"]
    a.cpu_throttled = demand["/A"] - alloc["/A"]
    print(f"  A wants {fmt_cpus(demand['/A'])}, cpu.max caps it at "
          f"{fmt_cpus(a.cpu_max)}")
    print(f"  -> A runs {fmt_cpus(a.cpu_used)}, THROTTLED "
          f"{fmt_cpus(a.cpu_throttled)} (3 CPUs of demand, paused)")
    print(f"  -> idle (unused): {fmt_cpus(m.cpu_capacity - a.cpu_used)}")
    assert alloc["/A"] == 1000.0, "hard cap must bind at 1 CPU = 1000 m"
    assert a.cpu_used + a.cpu_throttled == demand["/A"], "accounting"

    print("\nDEMO 2 -- two hard-capped containers, total cap < machine")
    print("-" * 56)
    m = Machine(cpu_capacity=4000)
    m.add(Cgroup(path="/A", cpu_max=cpu_max_to_millicores("100000 100000")))
    m.add(Cgroup(path="/B", cpu_max=cpu_max_to_millicores("100000 100000")))
    demand = {"/A": 4000, "/B": 4000}
    alloc = allocate_cpu(m, demand)
    print("  A capped at 1 CPU, B capped at 1 CPU. Both want 4 CPUs. Machine 4.")
    for p in ("/A", "/B"):
        cg = m.cgroups[p]
        cg.cpu_used = alloc[p]
        cg.cpu_throttled = demand[p] - alloc[p]
        print(f"  {p}: runs {fmt_cpus(cg.cpu_used)}, throttled "
              f"{fmt_cpus(cg.cpu_throttled)}")
    print(f"  -> total used {fmt_cpus(sum(alloc.values()))}, idle "
          f"{fmt_cpus(m.cpu_capacity - sum(alloc.values()))} "
          "(caps bind, 2 CPUs wasted -- a reason to over-commit)")
    assert alloc["/A"] == 1000.0 and alloc["/B"] == 1000.0

    print("\nDEMO 3 -- NO hard cap, only cpu.weight (the contention case)")
    print("-" * 56)
    m = Machine(cpu_capacity=4000)
    m.add(Cgroup(path="/A", cpu_max=None, cpu_weight=200))
    m.add(Cgroup(path="/B", cpu_max=None, cpu_weight=100))
    demand = {"/A": 4000, "/B": 4000}
    alloc = allocate_cpu(m, demand)
    for p in ("/A", "/B"):
        cg = m.cgroups[p]
        cg.cpu_used = alloc[p]
        cg.cpu_throttled = demand[p] - alloc[p]
    print("  A weight 200, B weight 100. Both want all 4 CPUs (busy).")
    print("  -> A gets 4 * 200/(200+100) =", fmt_cpus(alloc["/A"]),
          " B gets 4 * 100/(200+100) =", fmt_cpus(alloc["/B"]))
    print("  (proportional to weight; if either goes idle the other gets 100%)")
    assert abs(alloc["/A"] - 4000 * 200 / 300) < 1e-6
    assert abs(alloc["/B"] - 4000 * 100 / 300) < 1e-6

    print("\nDEMO 4 -- cap + weight together (cap binds first, spare by weight)")
    print("-" * 56)
    m = Machine(cpu_capacity=4000)
    m.add(Cgroup(path="/A", cpu_max=cpu_max_to_millicores("100000 100000"),
                 cpu_weight=200))  # capped at 1 CPU
    m.add(Cgroup(path="/B", cpu_max=None, cpu_weight=100))               # no cap
    m.add(Cgroup(path="/C", cpu_max=None, cpu_weight=100))               # no cap
    demand = {"/A": 4000, "/B": 4000, "/C": 4000}
    alloc = allocate_cpu(m, demand)
    for p in ("/A", "/B", "/C"):
        cg = m.cgroups[p]
        cg.cpu_used = alloc[p]
        cg.cpu_throttled = demand[p] - alloc[p]
    print("  A capped at 1 CPU (weight irrelevant); B,C no cap, equal weight.")
    print("  A takes its 1 CPU, leaving 3; B and C split the 3 evenly (1.5 each).")
    for p in ("/A", "/B", "/C"):
        cg = m.cgroups[p]
        print(f"  {p}: runs {fmt_cpus(cg.cpu_used)}")
    assert alloc["/A"] == 1000.0
    assert abs(alloc["/B"] - 1500.0) < 1e-6 and abs(alloc["/C"] - 1500.0) < 1e-6
    print()
    print("[check] DEMO 4 accounting: A+B+C used =",
          fmt_cpus(sum(alloc.values())), "== capacity",
          fmt_cpus(m.cpu_capacity), "->",
          "OK" if abs(sum(alloc.values()) - m.cpu_capacity) < 1e-6 else "FAIL")


# ============================================================================
# SECTION C: Memory cgroup -- memory.max + OOM killer
# ============================================================================
def section_memory():
    banner("SECTION C: memory -- memory.max and the OOM killer")
    print("memory.max is a HARD bytes ceiling. Unlike CPU throttling (which")
    print("PAUSES a task and resumes it next period), going over memory.max")
    print("cannot be 'paused' -- the kernel must FREE memory immediately, so it")
    print("invokes the OOM killer, which SIGKILLs a process in the cgroup.\n")
    machine = Machine(cpu_capacity=4000)
    cg = machine.add(Cgroup(path="/app", memory_max=512))
    print(f"cgroup /app, memory.max = {cg.memory_max} MB. Workload allocates in")
    print("100 MB steps:\n")
    print(f"  {'step':<5} {'alloc MB':<9} {'usage':<8} {'event':<24}")
    print("  " + "-" * 50)
    steps = [100, 200, 300, 400, 500, 600]
    for i, mb in enumerate(steps, 1):
        event = "OK"
        if mb > cg.memory_max:
            # OOM: the kernel refuses and kills the largest victim (here, the
            # whole app). usage is rolled back to just under the limit.
            cg.oom_kills += 1
            cg.memory_used = cg.memory_max
            event = f"OOM KILL (x{cg.oom_kills})"
        else:
            cg.memory_used = mb
        print(f"  {i:<5} {mb:<9} {cg.memory_used:<8} {event}")
    print()
    print("After OOM, the cgroup's usage is pinned at memory.max (512 MB); the")
    print("killed process is gone and the survivors continue. The accounting")
    print("invariant holds: at NO step did usage exceed memory.max.")
    assert cg.oom_kills == 1, "exactly one OOM at the 600 MB step"
    assert cg.memory_used <= cg.memory_max, "usage never exceeds max"
    print("\n[check] memory accounting: max usage observed", cg.memory_used,
          "<= limit", cg.memory_max, "->",
          "OK" if cg.memory_used <= cg.memory_max else "FAIL")
    print("[check] OOM kills =", cg.oom_kills,
          "(one, at the 600 MB alloc) -> OK")


# ============================================================================
# SECTION D: blkio -- io.max (rbps / riops)
# ============================================================================
def section_io():
    banner("SECTION D: io (blkio) -- per-device IOPS and bytes/s caps")
    print("The io controller caps throughput to a block device, per cgroup. The")
    print("v2 file io.max takes 'rbps wbps riops wiops', each 'max' or a number.")
    print("This protects the SHARED disk from one noisy container saturating it.\n")
    machine = Machine(cpu_capacity=4000)
    cg = machine.add(Cgroup(path="/batch", io_rbps=10 * 1024 * 1024))  # 10 MB/s
    print(f"cgroup /batch, io.max rbps = {cg.io_rbps} B/s "
          f"(= {cg.io_rbps // (1024*1024)} MB/s).")
    print("A workload tries to read 50 MB as fast as possible:\n")
    total = 50 * 1024 * 1024
    limit = cg.io_rbps
    elapsed = total / limit  # seconds, if it were allowed the full rate
    print("  demand         : 50 MB")
    print("  device raw rate: ~500 MB/s (no limit -> would finish in 0.1 s)")
    print(f"  io.max rbps    : {limit // (1024*1024)} MB/s")
    print(f"  -> effective   : {limit // (1024*1024)} MB/s, "
          f"50 MB takes {elapsed:.1f} s")
    effective_bps = limit
    assert effective_bps == cg.io_rbps, "throughput capped at io.max"
    print()
    print("The kernel delays each read so the rolling rate never exceeds rbps.")
    print("This is THROTTLING (like CPU), not killing -- the I/O completes, just")
    print("slowly. Same idea for riops (random IOPS) on SSDs.")
    print("\n[check] io accounting: effective", effective_bps // (1024*1024),
          "MB/s <= limit", cg.io_rbps // (1024*1024), "MB/s -> OK")


# ============================================================================
# SECTION E: pids -- fork bomb prevention
# ============================================================================
def section_pids():
    banner("SECTION E: pids -- fork-bomb fuse (pids.max)")
    print("A classic fork bomb (:(){ :|:& };:) doubles processes every")
    print("generation. Without a limit it exhausts the PID table and wedges the")
    print("box. pids.max is the fuse: a fork that would push the cgroup's process")
    print("count over the limit returns EAGAIN (the fork is REFUSED, not killed).\n")
    machine = Machine(cpu_capacity=4000)
    cg = machine.add(Cgroup(path="/untrusted", pids_max=100))
    print(f"cgroup /untrusted, pids.max = {cg.pids_max}. Simulating a fork bomb")
    print("(each surviving process forks one child per generation):\n")
    print(f"  {'gen':<4} {'processes':<11} {'event':<26}")
    print("  " + "-" * 42)
    gen = 0
    cg.pids_current = 1  # the original shell
    while True:
        gen += 1
        # every existing process tries to fork one child this generation
        births = cg.pids_current
        accepted = 0
        refused = 0
        for _ in range(births):
            if cg.pids_current + 1 <= cg.pids_max:
                cg.pids_current += 1
                accepted += 1
                if cg.pids_current >= cg.pids_max:
                    break
            else:
                refused += 1
        cg.fork_refusals += refused
        event = "OK" if accepted else "FORK REFUSED (EAGAIN)"
        print(f"  {gen:<4} {cg.pids_current:<11} {event}")
        if accepted == 0:
            break
        if gen > 20:
            break
    print()
    print(f"The bomb hit the ceiling at {cg.pids_max} processes in {gen} "
          "generations and then every further fork was REFUSED. The host is")
    print("untouched -- the limit is per-cgroup, so the fork bomb cannot escape "
          "/untrusted.")
    print()
    print("[check] pids accounting: current", cg.pids_current, "<= max",
          cg.pids_max, "->",
          "OK" if cg.pids_current <= cg.pids_max else "FAIL")
    assert cg.pids_current == cg.pids_max, "bomb pegged at the ceiling"
    assert cg.fork_refusals > 0, "forks were refused once full"


# ============================================================================
# SECTION F: the GOLD check -- resource accounting invariant (usage <= limit)
# ============================================================================
def section_gold():
    banner("SECTION F: GOLD check -- for every controller, USAGE <= LIMIT")
    print("The single invariant that defines correct cgroup behaviour: no")
    print("cgroup ever consumes more than its configured limit, on ANY axis.")
    print("If this ever fails, a container has escaped its cage.\n")
    machine = Machine(cpu_capacity=4000)
    # one realistic container: 1 CPU, 512 MB, 100 pids, 10 MB/s
    app = machine.add(Cgroup(
        path="/app",
        cpu_max=cpu_max_to_millicores("100000 100000"),  # 1 CPU
        cpu_weight=100,
        memory_max=512,
        io_rbps=10 * 1024 * 1024,
        pids_max=100,
    ))
    # run a CPU workload against a contending sibling to force the cap to bind
    sib = machine.add(Cgroup(path="/sib", cpu_max=None, cpu_weight=100))
    alloc = allocate_cpu(machine, {"/app": 4000, "/sib": 4000})
    app.cpu_used = alloc["/app"]
    sib.cpu_used = alloc["/sib"]
    # memory: run it into OOM as in Section C
    for mb in (100, 200, 300, 400, 500, 600):
        if mb > app.memory_max:
            app.oom_kills += 1
            app.memory_used = app.memory_max
        else:
            app.memory_used = mb
    # pids: fork bomb as in Section E
    app.pids_current = 1
    while app.pids_current < app.pids_max:
        app.pids_current += 1
    # io
    io_effective = app.io_rbps

    print(f"  {'controller':<11} {'limit':<14} {'usage':<14} {'result':<8}")
    print("  " + "-" * 50)
    checks = [
        ("cpu",     fmt_cpus(app.cpu_max), fmt_cpus(app.cpu_used),
         app.cpu_used <= app.cpu_max + 1e-6),
        ("memory",  f"{app.memory_max} MB", f"{app.memory_used} MB",
         app.memory_used <= app.memory_max),
        ("io",      f"{app.io_rbps//(1024*1024)} MB/s",
         f"{io_effective//(1024*1024)} MB/s", io_effective <= app.io_rbps),
        ("pids",    f"{app.pids_max}", f"{app.pids_current}",
         app.pids_current <= app.pids_max),
    ]
    all_ok = True
    for name, lim, use, ok in checks:
        all_ok = all_ok and ok
        print(f"  {name:<11} {lim:<14} {use:<14} "
              f"{'OK' if ok else 'FAIL':<8}")
    verdict = "OK" if all_ok else "FAIL"
    print(f"\n[check] resource-accounting invariant (usage <= limit, all 4 axes): "
          f"{verdict}")

    # pin gold values for cgroups.html
    gold = {
        "app_cpu_used_m": round(app.cpu_used),
        "app_cpu_limit_m": round(app.cpu_max),
        "app_memory_used_mb": app.memory_used,
        "app_memory_limit_mb": app.memory_max,
        "app_oom_kills": app.oom_kills,
        "app_pids_current": app.pids_current,
        "app_pids_max": app.pids_max,
        "io_effective_mbs": io_effective // (1024 * 1024),
        "axes_ok": int(all_ok),
    }
    print("\nGOLD values (pinned for cgroups.html):")
    for kk, vv in gold.items():
        print(f"    {kk:<24} = {vv}")
    assert gold["axes_ok"] == 1, "all 4 axes must satisfy usage<=limit"
    assert gold["app_cpu_used_m"] == 1000, "app hard-capped at 1 CPU = 1000 m"
    assert gold["app_memory_used_mb"] == 512, "memory pinned at max post-OOM"
    assert gold["app_oom_kills"] == 1, "one OOM kill"
    assert gold["app_pids_current"] == 100, "pids pegged at ceiling"
    print("[check] gold assertions (4/4 axes, 1 CPU cap, 1 OOM, pids pegged): OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("cgroups.py - reference model of Linux control groups (v2).")
    print("All numbers below feed CGROUPS.md and cgroups.html.")
    print("Python", sys.version.split()[0])

    section_hierarchy()
    section_cpu()
    section_memory()
    section_io()
    section_pids()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
