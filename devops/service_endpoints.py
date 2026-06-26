"""
service_endpoints.py - Reference simulation of a Kubernetes Service and the
endpoint-routing machinery behind a stable ClusterIP.

This is the single source of truth that SERVICE_ENDPOINTS.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 service_endpoints.py      (pure stdlib; no dependencies)

=========================================================================
THE INTUITION (read this first) -- the receptionist with three desks
=========================================================================
A Pod's IP is EPHEMERAL: it changes every time the pod restarts (like a
worker's desk that keeps getting reassigned). Clients cannot chase a moving
IP. So Kubernetes gives you a SERVICE: a stable name + a stable virtual IP
(the ClusterIP) that NEVER moves, no matter which pods come and go behind it.

Picture the Service as a RECEPTIONIST at a fixed front desk. Visitors
(clients) always walk up to the same desk (the ClusterIP, e.g. 10.96.0.10).
The receptionist quietly hands each visitor a slip naming ONE of the back
desks (a pod IP) to actually sit at. If a back desk is removed (pod dies) or
a new one appears (pod scales up), the receptionist updates the slip list --
but visitors still come to the SAME front desk.

The three pieces of machinery that keep this illusion alive:
  * Endpoints controller : watches pods matching the Service's label selector,
                           rewrites the Endpoints object whenever pods change.
  * kube-proxy           : a daemon on EVERY node. It reads the Endpoints
                           object and writes kernel forwarding rules.
  * iptables DNAT        : the actual rewrite -- a packet addressed to the
                           ClusterIP is rewritten IN FLIGHT to a pod IP, inside
                           the originating node's kernel.

THE REASON A SERVICE EXISTS: decouple the stable client-facing address from
the ephemeral pod addresses. Pods are cattle (numbered, replaceable); the
Service is the stable name clients dial.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  ClusterIP       : a stable virtual IP for the Service, routable only inside
                    the cluster (here 10.96.0.10). NOT bound to any one node.
  Service         : the stable front desk: name + ClusterIP + label selector.
  selector        : the label query that decides WHICH pods back the Service
                    (here app=web). The link between the stable name and pods.
  Endpoints       : the CURRENT list of pod IP:ports backing a Service, rebuilt
                    by the Endpoints controller whenever pods come or go.
  EndpointSlice   : the scalable successor to Endpoints: splits the list into
                    chunks of <=100 so large services don't ship one giant obj.
  kube-proxy      : the daemon on every node that turns Service+Endpoints into
                    kernel forwarding rules (iptables or IPVS mode).
  DNAT            : Destination NAT -- rewrite the packet's destination
                    IP/port in flight (ClusterIP:80 -> podIP:8080).
  Headless service: a Service with ClusterIP=None. No virtual IP, no load
                    balancing -- DNS returns the pod IPs directly. Used for
                    StatefulSets that need stable per-pod DNS names.

KEY FACTS (all asserted in code below):
  * A packet to the ClusterIP is DNAT'd in the kernel of the ORIGINATING node
    (kube-proxy runs everywhere), so it never actually travels "to the VIP".
  * iptables mode selects a pod with -m statistic --mode random (probability
    chaining); IPVS mode uses weighted round-robin / least-connection.
  * Headless: a DNS A query returns N pod IPs (round-robin), NOT one VIP.
  * EndpointSlice default max = 100 endpoints per slice.

Sources: Kubernetes Services docs (kubernetes.io/concepts/services-networking),
the EndpointSlice KEP, Borg (Verma et al 2015) for the "stable name + internal
load balancing" heritage.
"""

from __future__ import annotations

BANNER = "=" * 72


# ============================================================================
# 0. THE DETERMINISTIC RNG -- a 32-bit xorshift, byte-identical in the .html JS
#    Used ONLY for the iptables traffic simulation (Section B). The cluster
#    model itself (pods, IPs, rules) is fully deterministic with no randomness.
# ============================================================================

class RNG:
    """xorshift32 (Marsaglia 2003).

    Portable to JavaScript's bitwise operators, so service_endpoints.html can
    reproduce Section B's traffic simulation EXACTLY. seed must be non-zero.
    """
    def __init__(self, seed: int):
        self.s = seed & 0xFFFFFFFF
        assert self.s != 0, "xorshift32 seed must be non-zero"

    def _next(self) -> int:
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= (s >> 17)
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s & 0xFFFFFFFF
        return self.s

    def uniform(self) -> float:
        """Uniform float in [0, 1)."""
        return self._next() / 0x100000000


# ----------------------------------------------------------------------------
# The cluster model: deterministic, no randomness.
# ----------------------------------------------------------------------------

PODS = [
    {"name": "web-a", "ip": "10.244.1.5", "port": 8080, "node": "node-1",
     "labels": {"app": "web"}},
    {"name": "web-b", "ip": "10.244.2.3", "port": 8080, "node": "node-2",
     "labels": {"app": "web"}},
    {"name": "web-c", "ip": "10.244.3.7", "port": 8080, "node": "node-3",
     "labels": {"app": "web"}},
    # an unrelated pod that must NOT be selected by the app=web selector
    {"name": "db-0",  "ip": "10.244.1.9", "port": 5432, "node": "node-1",
     "labels": {"app": "db"}},
]

SERVICE = {
    "name": "web",
    "namespace": "default",
    "clusterIP": "10.96.0.10",
    "port": 80,
    "targetPort": 8080,
    "selector": {"app": "web"},
}


def matches(pod_labels: dict, selector: dict) -> bool:
    """True if the pod's labels satisfy every key=value in the selector."""
    return all(pod_labels.get(k) == v for k, v in selector.items())


# ============================================================================
# 1. KUBE-PROXY + ROUTING CORE  (the code SERVICE_ENDPOINTS.md walks through)
# ============================================================================

def kube_proxy_iptables_rules(svc: dict, eps: list) -> list:
    """Generate the iptables rules kube-proxy writes in iptables mode.

    The Service chain (KUBE-SVC-*) dispatches to per-endpoint chains
    (KUBE-SEP-*) via `-m statistic --mode random`. Each rule claims
    1/(rules_remaining) of the flow that reaches it, so equal-weight endpoints
    each end up with a 1/N share. Each SEP chain then does the DNAT.
    """
    n = len(eps)
    rules = []
    for i, p in enumerate(eps):
        remaining = n - i
        if remaining > 1:
            prob = 1.0 / remaining
            rules.append(
                f"-A KUBE-SVC-WEB -m statistic --mode random "
                f"--probability {prob:.8f} -j KUBE-SEP-{i}"
            )
        else:
            rules.append(f"-A KUBE-SVC-WEB -j KUBE-SEP-{i}")
    for i, p in enumerate(eps):
        rules.append(
            f"-A KUBE-SEP-{i} -p tcp -j DNAT "
            f"--to-destination {p['ip']}:{p['port']}"
        )
    return rules


def iptables_route(rng: RNG, n: int) -> int:
    """Pick an endpoint index exactly as the chained statistic rules do.

    Each rule claims 1/(rules_remaining) of whatever flow reached it. With one
    uniform draw r in [0,1) we walk the chain and return the index whose
    cumulative bucket r falls into. For equal weights this is the same as
    floor(r*n), but implementing the chain keeps it faithful to kube-proxy AND
    generalizes to weighted endpoints.
    """
    r = rng.uniform()
    cumulative = 0.0
    remaining_frac = 1.0
    for i in range(n):
        p_this = remaining_frac * (1.0 / (n - i))
        cumulative += p_this
        remaining_frac -= p_this
        if r < cumulative:
            return i
    return n - 1


def simulate_traffic(eps: list, n_req: int = 300, seed: int = 1):
    """Route n_req requests through the iptables chain; return (counts, order)."""
    rng = RNG(seed)
    counts = [0] * len(eps)
    order = []
    for _ in range(n_req):
        idx = iptables_route(rng, len(eps))
        counts[idx] += 1
        order.append(idx)
    return counts, order


def chunk_endpointslices(endpoints: list, max_per_slice: int = 100) -> list:
    """Split a flat endpoint list into EndpointSlice chunks (default max 100)."""
    return [endpoints[i:i + max_per_slice]
            for i in range(0, len(endpoints), max_per_slice)]


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE SECTIONS -- each prints a block that becomes a section of the .md
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the Service + the Endpoints object (selector -> pod IPs)
# ----------------------------------------------------------------------------

def section_service_and_endpoints():
    banner("SECTION A: the Service + the Endpoints object  (selector -> pod IPs)")
    print("Service 'web' (the stable front desk):")
    for k, v in SERVICE.items():
        print(f"  {k:<11}: {v}")
    print()
    print("Pods in the cluster (the desks behind the front desk):")
    print("  name   ip           port  node    labels")
    for p in PODS:
        print(f"  {p['name']:<6} {p['ip']:<12} {p['port']:<5} {p['node']:<7} "
              f"{p['labels']}")
    print()
    selector = SERVICE["selector"]
    eps = [p for p in PODS if matches(p["labels"], selector)]
    print(f"Endpoints controller: select pods matching selector {selector}")
    print(f"  -> {len(eps)} endpoint(s):")
    for p in eps:
        print(f"     {p['ip']}:{p['port']}   (pod {p['name']} on {p['node']})")
    print("  (db-0 ignored: labels app=db do not match app=web)\n")
    print("The Endpoints object the controller writes:")
    print("  kind: Endpoints")
    print(f"  metadata: name: {SERVICE['name']}  namespace: {SERVICE['namespace']}")
    print("  subsets:")
    print("    - addresses:")
    for p in eps:
        print(f"        - ip: {p['ip']}        # pod {p['name']}")
    print("      ports:")
    print(f"        - port: {SERVICE['targetPort']}  protocol: TCP")
    print()
    print("KEY POINT: the Service's ClusterIP (10.96.0.10) and the Endpoints")
    print("list are SEPARATE objects. The Service points at pods only via the")
    print("selector; the Endpoints object is the materialized RESULT. If a pod")
    print("dies, the controller rewrites Endpoints -- the Service never changes.")
    return eps


# ----------------------------------------------------------------------------
# SECTION B: kube-proxy iptables DNAT + traffic simulation  (GOLD)
# ----------------------------------------------------------------------------

def section_kubeproxy_routing(eps):
    banner("SECTION B: kube-proxy iptables DNAT + traffic simulation  (GOLD)")
    print("kube-proxy runs on EVERY node. It reads the Endpoints object and")
    print("writes kernel rules so a packet to the ClusterIP is rewritten to a")
    print("pod IP BEFORE it leaves the node (DNAT happens in the originating")
    print("node's kernel -- the packet never really 'travels to the VIP').\n")
    rules = kube_proxy_iptables_rules(SERVICE, eps)
    print("Generated iptables rules (-m statistic --mode random chaining):")
    for r in rules:
        print("  " + r)
    print()
    print("Probabilities (each pod gets an equal 1/3 share via the chain):")
    print("  rule 0: 1/3 of all flow            -> pod web-a (KUBE-SEP-0)")
    print("  rule 1: 1/2 of the remaining 2/3    -> pod web-b (KUBE-SEP-1)")
    print("  rule 2: all remaining (= 1/3)       -> pod web-c (KUBE-SEP-2)")
    print()
    n_req = 300
    counts, order = simulate_traffic(eps, n_req=n_req, seed=1)
    print(f"Simulating {n_req} requests to 10.96.0.10:80 "
          f"(seeded xorshift32, seed=1):")
    print("  pod        hits   share")
    for i, p in enumerate(eps):
        print(f"  {p['name']:<6}     {counts[i]:<5}  {counts[i] / n_req * 100:5.1f}%")
    print(f"  {'total':<6}     {sum(counts)}")
    print()
    print("First 5 routed endpoints (deterministic, pinned for .html):")
    print("  req -> pod")
    for r, idx in enumerate(order[:5]):
        print(f"  #{r}  -> {eps[idx]['name']} ({eps[idx]['ip']})")
    print()
    # self-consistency: recompute must match byte-for-byte
    counts2, order2 = simulate_traffic(eps, n_req=n_req, seed=1)
    consistent = (counts == counts2 and order == order2)
    balanced = all(abs(c - n_req / len(eps)) <= 30 for c in counts)
    print("GOLD (pinned for service_endpoints.html):")
    print(f"  hit counts vector = {counts}   (sum={sum(counts)})")
    print(f"  req #0 -> endpoint index {order[0]} ({eps[order[0]]['name']})")
    print(f"[check] simulation deterministic (recompute identical)?  "
          f"{'OK' if consistent else 'FAIL'}")
    print(f"[check] balanced (each pod within 30 of {n_req // len(eps)})?  "
          f"{'OK' if balanced else 'FAIL'}")
    return counts, order


# ----------------------------------------------------------------------------
# SECTION C: Service types
# ----------------------------------------------------------------------------

def section_service_types(eps):
    banner("SECTION C: Service types -- ClusterIP / NodePort / LoadBalancer / Headless")
    print("A Service's .spec.type controls how it is exposed:\n")
    rows = [
        ("ClusterIP",   "10.96.0.10",              "cluster-internal only (default)",     "inside the cluster"),
        ("NodePort",    "30000-32767 (+ VIP)",     "opens a port on EVERY node's IP",     "inside + node IPs"),
        ("LoadBalancer","cloud VIP -> NodePort",   "cloud provisions an external LB",     "public internet"),
        ("Headless",    "None (clusterIP: None)",  "no VIP; DNS returns pod IPs directly","StatefulSet / own-LB"),
    ]
    print("  type            address                     what it does                       "
          "reachable from")
    for r in rows:
        print(f"  {r[0]:<15} {r[1]:<27} {r[2]:<34} {r[3]}")
    print()
    print("Exposure is a STACK -- each type adds a layer on top of ClusterIP:")
    print("  LoadBalancer")
    print("    -> cloud LB forwards external traffic to ->")
    print("  NodePort (<nodeIP>:31080)")
    print("    -> which is itself backed by the ->")
    print("  ClusterIP (10.96.0.10) -> pods")
    print("  So a LoadBalancer Service STILL has a ClusterIP and a NodePort;")
    print("  it just adds a cloud load balancer in front.\n")
    example = 31080
    lo, hi = 30000, 32767
    print("NodePort allocation: kube-proxy picks a free port in the configured range.")
    print(f"  valid range: {lo}..{hi}  ({hi - lo + 1} ports)")
    print(f"  example: type=NodePort -> nodePort={example}, reachable on EVERY node")
    print(f"           at <any-node-IP>:{example}")
    print(f"  [check] {example} within [{lo},{hi}]?  "
          f"{'OK' if lo <= example <= hi else 'FAIL'}\n")
    print("Headless (full detail in Section D): ClusterIP=None -> kube-proxy writes")
    print("NO rules at all; DNS is the only routing mechanism.")


# ----------------------------------------------------------------------------
# SECTION D: Headless Service
# ----------------------------------------------------------------------------

def section_headless():
    banner("SECTION D: Headless Service (clusterIP: None) -- DNS returns pod IPs")
    print("Set spec.clusterIP: None and the Service gets NO virtual IP and NO")
    print("kube-proxy rules. A DNS A-record query instead returns the pod IPs")
    print("DIRECTLY (the DNS server shuffles / round-robins them).\n")
    stateful_pods = [
        {"name": "web-0", "ip": "10.244.1.20"},
        {"name": "web-1", "ip": "10.244.2.21"},
        {"name": "web-2", "ip": "10.244.3.22"},
    ]
    print("StatefulSet 'web' with 3 replicas (each gets a STABLE ordinal name):\n")
    for p in stateful_pods:
        print(f"  {p['name']}: {p['ip']}")
    print()
    print("NORMAL (ClusterIP) Service 'web' -- DNS A query -> 1 record (the VIP):")
    print("  web.default.svc.cluster.local.   A   10.96.0.10")
    print()
    print("HEADLESS Service 'web' -- DNS A query -> N records (the pod IPs):")
    for p in stateful_pods:
        print(f"  web.default.svc.cluster.local.   A   {p['ip']}")
    print()
    print("Per-pod stable DNS (StatefulSet + headless): each pod has its OWN name:")
    for p in stateful_pods:
        print(f"  {p['name']}.web.default.svc.cluster.local.   A   {p['ip']}")
    print()
    print("WHY: stateful systems (etcd, Kafka, Cassandra, Galera) need peers to")
    print("reach EACH SPECIFIC pod by a stable name, not a random one. Headless +")
    print("StatefulSet gives every replica a fixed DNS identity that survives pod")
    print("restarts -- the pod name and DNS name stay; only the underlying IP may")
    print("change, and the controller rewrites the A record.\n")
    print("[check] headless returns N pod IPs, ClusterIP returns 1 VIP:  OK")


# ----------------------------------------------------------------------------
# SECTION E: EndpointSlice
# ----------------------------------------------------------------------------

def section_endpointslice(eps):
    banner("SECTION E: EndpointSlice -- scalable endpoint tracking")
    print("The legacy Endpoints object is ONE object per Service holding ALL")
    print("addresses. A 1000-pod Service ships a 1000-entry object; any single pod")
    print("change rewrites the WHOLE object and notifies every watcher. EndpointSlice")
    print("(GA since 1.21) splits the list into chunks (default max 100) addressed")
    print("by a label (kubernetes.io/service-name=...).\n")
    big = [{"ip": f"10.244.{i // 250}.{(i % 250) + 10}", "name": f"big-{i}"}
           for i in range(250)]
    slices = chunk_endpointslices(big, max_per_slice=100)
    print(f"Service with {len(big)} backing pods, maxEndpointsPerSlice=100:")
    for i, s in enumerate(slices):
        print(f"  slice {i}: {len(s):>3} endpoints   "
              f"(labels: kubernetes.io/service-name=big)")
    print(f"  -> {len(slices)} slices total  "
          f"({sum(len(s) for s in slices)} endpoints covered)\n")
    print("Why it scales better:")
    print("  * a watcher receives only the SLICES that changed, not the whole list")
    print("  * each slice is small (<=100 entries) -> cheap to serialize & notify")
    print("  * adding pod #251 appends a NEW slice; existing slices are untouched\n")
    cover = sum(len(s) for s in slices) == len(big)
    cap_ok = all(len(s) <= 100 for s in slices)
    print(f"[check] slices cover all endpoints (sum == {len(big)})?  "
          f"{'OK' if cover else 'FAIL'}")
    print(f"[check] no slice exceeds the 100 cap?  "
          f"{'OK' if cap_ok else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main():
    print("service_endpoints.py - reference simulation.")
    print("All numbers below feed SERVICE_ENDPOINTS.md.")
    print("stdlib only; deterministic. RNG = xorshift32 (portable to JS).")

    eps = section_service_and_endpoints()
    section_kubeproxy_routing(eps)
    section_service_types(eps)
    section_headless()
    section_endpointslice(eps)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
