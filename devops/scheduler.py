"""
scheduler.py - Reference simulation of the Kubernetes default scheduler.

This is the single source of truth that SCHEDULER.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 scheduler.py      (pure stdlib; no dependencies)

=========================================================================
THE INTUITION (read this first) -- the hotel reception assigning rooms
=========================================================================
When you create a Pod, it starts "Pending". The scheduler's job is to pick
exactly ONE node for it (binding). Think of a hotel RECEPTION assigning guests
to rooms: it cannot overbook a room, it honors special requests (a guest who
needs a quiet floor), and it tries to spread guests so no single floor is
packed while others sit empty.

The scheduler does this in TWO PHASES:

  1. FILTER  ("can the pod run here at all?") -- produce the FEASIBLE set.
     For each node, check hard constraints: enough free CPU/memory? does the
     pod tolerate the node's taints? nodeSelector / node affinity match? Any
     'no' -> the node is dropped. Only survivors move on.

  2. SCORE   ("of the feasible nodes, which is best?") -- rank them 0..100 and
     pick the top. The ranking encodes a POLICY. Two opposite ones matter most:
       * LeastAllocated : prefer the LEAST-loaded node  -> SPREADS pods out
       * MostAllocated  : prefer the MOST-loaded node   -> BIN-PACKS pods
                         (fill nodes up so whole nodes can be drained/freed)

THE REASON FOR TWO PHASES: filter is cheap and parallel (hard yes/no per node);
score is where the operator's intent (spread vs pack, affinity, topology) is
expressed. Splitting them keeps the feasible set small before the expensive
ranking runs.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  Filter        : phase 1 -- drop nodes that cannot host the pod. Produces the
                  feasible set. Also called "predicates" in older docs.
  Score         : phase 2 -- rank feasible nodes 0..100; pick the highest.
                  Also called "priorities" in older docs.
  allocatable   : a node's usable CPU/memory (capacity minus system reservations).
  request       : what the pod GUARANTEES it needs (used for scheduling). The
                  scheduler compares free = allocatable - already-requested.
  LeastAllocated: score policy that prefers LEAST-utilized nodes -> SPREADING.
  MostAllocated : score policy that prefers MOST-utilized nodes -> BIN-PACKING.
  taint         : a mark on a node (key=value:effect). effect=NoSchedule repels
                  every pod that does not explicitly TOLERATE it.
  toleration    : a pod's declaration "I am OK running on nodes tainted X".
  antiAffinity  : "don't co-locate me with pods matching label Y" -- spreads
                  replicas across nodes for high availability.
  Cluster
   Autoscaler   : if a pod stays Pending because NO node has room, the autoscaler
                  asks the cloud for a new node, waits for it to join, then the
                  pod is re-scheduled.

KEY FACTS (all asserted in code below):
  * The winner FLIPS between LeastAllocated and MostAllocated for the same pod.
  * LeastAllocated -> spreading (fill many nodes a little).
  * MostAllocated  -> bin-packing (pack few nodes a lot, free the rest).
  * BalancedResourceAllocation: secondary score that prefers cpu & mem equally
    utilized, so a node isn't CPU-heavy / memory-idle.
  * Taints are enforced in FILTER, before scoring -- a tainted node never
    competes for plain pods.

Sources: Kubernetes scheduler docs (kubernetes.io/concepts/scheduling-eviction),
kube-scheduler configuration reference, Borg (Verma et al 2015) for the
"filter then score / two-phase placement" heritage.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 0. THE CLUSTER MODEL -- deterministic, no randomness.
# ============================================================================

NODES = [
    {"name": "node-1", "cpu_alloc": 4, "mem_alloc": 16, "cpu_used": 1,  "mem_used": 4,
     "taints": [], "gpu": False},
    {"name": "node-2", "cpu_alloc": 4, "mem_alloc": 16, "cpu_used": 3,  "mem_used": 10,
     "taints": [], "gpu": False},
    {"name": "node-3", "cpu_alloc": 4, "mem_alloc": 16, "cpu_used": 0,  "mem_used": 0,
     "taints": [], "gpu": False},
    {"name": "node-4", "cpu_alloc": 8, "mem_alloc": 32, "cpu_used": 2,  "mem_used": 8,
     "taints": [], "gpu": False},
    {"name": "gpu-1",  "cpu_alloc": 8, "mem_alloc": 32, "cpu_used": 1,  "mem_used": 4,
     "taints": [{"key": "gpu", "effect": "NoSchedule"}], "gpu": True},
]

# The pod we schedule through Sections A-B: needs 2 CPU + 4 GB, no tolerations.
POD = {"name": "web", "cpu_req": 2, "mem_req": 4, "tolerations": []}


# ============================================================================
# 1. FILTER + SCORE CORE  (the code SCHEDULER.md walks through)
# ============================================================================

def free_cpu(n: dict) -> int:
    return n["cpu_alloc"] - n["cpu_used"]


def free_mem(n: dict) -> int:
    return n["mem_alloc"] - n["mem_used"]


def tolerates(pod: dict, node: dict) -> bool:
    """A pod can run on a node only if every NoSchedule taint is tolerated."""
    tol_keys = {(t["key"], t.get("effect", "NoSchedule"))
                for t in pod["tolerations"]}
    for taint in node["taints"]:
        if taint["effect"] != "NoSchedule":
            continue
        if (taint["key"], taint["effect"]) not in tol_keys:
            return False
    return True


def filter_nodes(nodes: list, pod: dict) -> list:
    """Phase 1: return only nodes that satisfy all hard constraints."""
    out = []
    for n in nodes:
        if free_cpu(n) < pod["cpu_req"]:
            continue
        if free_mem(n) < pod["mem_req"]:
            continue
        if not tolerates(pod, n):
            continue
        out.append(n)
    return out


# --- scorers: utilization is computed AFTER hypothetically placing the pod ---

def util_cpu_after(n: dict, pod: dict) -> float:
    return (n["cpu_used"] + pod["cpu_req"]) / n["cpu_alloc"]


def util_mem_after(n: dict, pod: dict) -> float:
    return (n["mem_used"] + pod["mem_req"]) / n["mem_alloc"]


def score_least_allocated(n: dict, pod: dict) -> float:
    """Prefer LEAST-loaded node -> SPREADING. Higher = more free capacity."""
    free_cpu_frac = 1.0 - util_cpu_after(n, pod)
    free_mem_frac = 1.0 - util_mem_after(n, pod)
    return (free_cpu_frac + free_mem_frac) / 2 * 100


def score_most_allocated(n: dict, pod: dict) -> float:
    """Prefer MOST-loaded node -> BIN-PACKING. Higher = more utilized."""
    return (util_cpu_after(n, pod) + util_mem_after(n, pod)) / 2 * 100


def score_balanced(n: dict, pod: dict) -> float:
    """Prefer cpu & mem equally utilized. Higher = more balanced."""
    diff = abs(util_cpu_after(n, pod) - util_mem_after(n, pod))
    return (1.0 - diff) * 100


def rank(nodes: list, pod: dict, scorer) -> list:
    """Return [(score, name), ...] sorted by score desc, name asc for ties."""
    scored = [(scorer(n, pod), n["name"]) for n in nodes]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: Filter phase
# ----------------------------------------------------------------------------

def section_filter():
    banner("SECTION A: Filter phase -- find feasible nodes")
    print("Pod to schedule:")
    print(f"  name={POD['name']}   requests: {POD['cpu_req']} CPU, "
          f"{POD['mem_req']} GB   tolerations: {POD['tolerations'] or '[]'}\n")
    print("Nodes (allocatable vs currently requested/used):")
    print("  name   cpu(alloc/used/free)   mem(alloc/used/free)   taints")
    for n in NODES:
        print(f"  {n['name']:<6} {n['cpu_alloc']}/{n['cpu_used']}/{free_cpu(n):<2}            "
              f"{n['mem_alloc']}/{n['mem_used']}/{free_mem(n):<2}            "
              f"{n['taints'] or '-'}")
    print()
    feasible = filter_nodes(NODES, POD)
    print("Hard constraints applied (all must pass):")
    print(f"  1. free_cpu >= {POD['cpu_req']}")
    print(f"  2. free_mem >= {POD['mem_req']}")
    print("  3. every NoSchedule taint is tolerated by the pod")
    print()
    print("Per-node verdict:")
    for n in NODES:
        reasons = []
        if free_cpu(n) < POD["cpu_req"]:
            reasons.append(f"cpu short (free {free_cpu(n)} < {POD['cpu_req']})")
        if free_mem(n) < POD["mem_req"]:
            reasons.append(f"mem short (free {free_mem(n)} < {POD['mem_req']})")
        if not tolerates(POD, n):
            reasons.append(f"taint {n['taints']} not tolerated")
        if n in feasible:
            verdict = "FEASIBLE"
        else:
            verdict = "REJECTED (" + "; ".join(reasons) + ")"
        print(f"  {n['name']:<6} -> {verdict}")
    print()
    print(f"Feasible set: {[n['name'] for n in feasible]}")
    print("  (node-2 dropped: only 1 CPU free ; "
          "gpu-1 dropped: taint gpu:NoSchedule, pod has no toleration)")
    return feasible


# ----------------------------------------------------------------------------
# SECTION B: Score phase  (GOLD)
# ----------------------------------------------------------------------------

def section_score(feasible):
    banner("SECTION B: Score phase -- rank feasible nodes  (bin-pack vs spread)")
    print("Three built-in scoring policies (NodeResourcesFit scoring):\n")
    print("  LeastAllocated          : prefer LEAST-loaded node -> SPREADS pods out")
    print("  MostAllocated           : prefer MOST-loaded node  -> BIN-PACKS onto few nodes")
    print("  BalancedResourceAllocation: prefer cpu & mem utilization balanced")
    print()
    print("Scores are 0..100 (higher wins). Utilization is measured AFTER placing")
    print("the pod on that node (i.e. used + request).\n")
    print(f"  {'node':<7}{'LeastAlloc':>12}{'MostAlloc':>12}{'Balanced':>11}"
          f"   cpu_util / mem_util (after)")
    for n in feasible:
        la = score_least_allocated(n, POD)
        ma = score_most_allocated(n, POD)
        ba = score_balanced(n, POD)
        cu = util_cpu_after(n, POD)
        mu = util_mem_after(n, POD)
        print(f"  {n['name']:<7}{la:>12.2f}{ma:>12.2f}{ba:>11.2f}"
              f"   {cu:.3f} / {mu:.3f}")
    print()
    la_rank = rank(feasible, POD, score_least_allocated)
    ma_rank = rank(feasible, POD, score_most_allocated)
    ba_rank = rank(feasible, POD, score_balanced)
    print("Ranked (score desc):")
    print(f"  LeastAllocated -> {[r[1] for r in la_rank]}   "
          f"winner: {la_rank[0][1]:<7} (SPREADING)")
    print(f"  MostAllocated  -> {[r[1] for r in ma_rank]}   "
          f"winner: {ma_rank[0][1]:<7} (BIN-PACKING)")
    print(f"  Balanced       -> {[r[1] for r in ba_rank]}   "
          f"winner: {ba_rank[0][1]}")
    print()
    print("WATCH THE WINNER FLIP: LeastAllocated picks the EMPTIEST feasible node")
    print("(node-3) to spread load; MostAllocated picks the FULLEST feasible node")
    print("(node-1) to pack tightly and leave whole nodes free. Same pod, same")
    print("feasible set, opposite placement -- the only difference is policy.\n")
    gold_least = la_rank[0][1]
    gold_most = ma_rank[0][1]
    print("GOLD (pinned for scheduler.html):")
    print(f"  LeastAllocated winner = {gold_least}")
    print(f"  MostAllocated  winner = {gold_most}")
    print(f"[check] the two policies pick DIFFERENT nodes (spread vs pack)?  "
          f"{'OK' if gold_least != gold_most else 'FAIL'}")
    return la_rank, ma_rank


# ----------------------------------------------------------------------------
# SECTION C: Taints & tolerations
# ----------------------------------------------------------------------------

def section_taints():
    banner("SECTION C: Taints & tolerations -- keeping plain pods off the GPU node")
    gpu = [n for n in NODES if n["name"] == "gpu-1"][0]
    print(f"Node gpu-1 carries a taint: {gpu['taints'][0]}  (effect = NoSchedule)\n")
    print("A NoSchedule taint means: any pod WITHOUT a matching toleration is")
    print("REJECTED from that node during the FILTER phase (Section A). It never")
    print("reaches scoring.\n")
    plain = {"name": "web", "cpu_req": 2, "mem_req": 4, "tolerations": []}
    gpu_pod = {"name": "train", "cpu_req": 2, "mem_req": 4,
               "tolerations": [{"key": "gpu", "effect": "NoSchedule"}]}
    f_plain = filter_nodes(NODES, plain)
    f_gpu = filter_nodes(NODES, gpu_pod)
    on_gpu_plain = any(n["name"] == "gpu-1" for n in f_plain)
    on_gpu_gpupod = any(n["name"] == "gpu-1" for n in f_gpu)
    print("  pod 'web'   (no toleration)   feasible on gpu-1? "
          f"{on_gpu_plain}   -> EXCLUDED")
    print("  pod 'train' (tolerates gpu)   feasible on gpu-1? "
          f"{on_gpu_gpupod}   -> ALLOWED")
    print()
    print("WHY: taints reserve special hardware (GPUs, dedicated/infra nodes) for")
    print("the workloads that explicitly tolerate them, so a plain web pod can")
    print("never accidentally grab an expensive GPU node.\n")
    ok = (not on_gpu_plain) and on_gpu_gpupod
    print(f"[check] toleration correctly gates gpu-1 access?  "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: podAntiAffinity -- spread replicas for HA
# ----------------------------------------------------------------------------

def section_affinity():
    banner("SECTION D: podAntiAffinity -- spread replicas across nodes (HA)")
    print("Goal: 3 replicas of 'web' should land on 3 DIFFERENT nodes, so a single")
    print("node failure kills at most 1 replica. podAntiAffinity tells the")
    print("scheduler: 'avoid (or forbid) a node that already hosts a web pod.'\n")
    print("Simulation: schedule the 3 replicas one at a time onto the Section A")
    print("feasible set {node-1, node-3, node-4}; each placement commits its usage;\n"
          " antiAffinity steers later replicas AWAY from already-hosting nodes.\n")
    # mutable per-node usage so placements accumulate
    state = {n["name"]: dict(n) for n in NODES}
    feasible_names = ["node-1", "node-3", "node-4"]
    web_pod = {"name": "web", "cpu_req": 2, "mem_req": 4, "tolerations": []}
    placement = []
    for rep in range(3):
        hosting = set(placement)
        cand = [state[nm] for nm in feasible_names
                if free_cpu(state[nm]) >= web_pod["cpu_req"]
                and free_mem(state[nm]) >= web_pod["mem_req"]]
        # antiAffinity: PREFER nodes not already hosting a web pod; fall back to all
        spread = [c for c in cand if c["name"] not in hosting] or cand
        # within the spread set, pick the LeastAllocated winner
        ranked = rank(spread, web_pod, score_least_allocated)
        chosen_name = ranked[0][1]
        chosen = state[chosen_name]
        chosen["cpu_used"] += web_pod["cpu_req"]
        chosen["mem_used"] += web_pod["mem_req"]
        placement.append(chosen_name)
        print(f"  replica {rep}: feasible {[c['name'] for c in cand]} ; "
              f"avoid hosting {sorted(hosting) or '{}'} ; "
              f"-> placed on {chosen_name}")
    print()
    distinct = len(set(placement))
    print(f"Placement order: {placement}")
    print(f"Distinct nodes used: {distinct}")
    print()
    print("RESULT: each replica got its OWN node. A node fault now takes down at")
    print("most one replica -- the HA goal of podAntiAffinity.\n")
    print("GOLD (pinned for scheduler.html):")
    print(f"  antiAffinity placement = {placement}")
    print(f"[check] all 3 replicas on distinct nodes (HA)?  "
          f"{'OK' if distinct == 3 else 'FAIL'}")
    return placement


# ----------------------------------------------------------------------------
# SECTION E: Cluster Autoscaler
# ----------------------------------------------------------------------------

def section_autoscaler():
    banner("SECTION E: Cluster Autoscaler -- no feasible node -> add one")
    huge = {"name": "big", "cpu_req": 16, "mem_req": 32, "tolerations": []}
    feas = filter_nodes(NODES, huge)
    print(f"Pod 'big' requests {huge['cpu_req']} CPU / {huge['mem_req']} GB -- more")
    print("free capacity than ANY current node offers.")
    print(f"Filter result: {len(feas)} feasible node(s) -> "
          f"{[n['name'] for n in feas]}\n")
    if not feas:
        print("The pod is now Pending. The Cluster Autoscaler notices a pod stuck")
        print("in Pending due to Insufficient cpu/memory, and reacts:")
        print("  1. requests a new node from the cloud provider (right shape/size)")
        print("  2. waits for the node to boot, join the cluster, and register")
        print("  3. the scheduler re-runs; the pod now finds a feasible node\n")
        new_node = {"name": "node-5", "cpu_alloc": 32, "mem_alloc": 64,
                    "cpu_used": 0, "mem_used": 0, "taints": [], "gpu": False}
        nodes2 = NODES + [new_node]
        feas2 = filter_nodes(nodes2, huge)
        print("After autoscaler adds node-5 (32 CPU / 64 GB allocatable):")
        print(f"  Filter result: {[n['name'] for n in feas2]}")
        print(f"  -> 'big' schedules on {feas2[0]['name']}\n")
        ok = any(n["name"] == "node-5" for n in feas2)
        print(f"[check] autoscaler resolved the Pending pod (node-5 feasible)?  "
              f"{'OK' if ok else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main():
    print("scheduler.py - reference simulation.")
    print("All numbers below feed SCHEDULER.md.")
    print("stdlib only; deterministic.")

    feasible = section_filter()
    section_score(feasible)
    section_taints()
    section_affinity()
    section_autoscaler()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
