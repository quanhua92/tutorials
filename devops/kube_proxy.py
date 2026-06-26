"""
kube_proxy.py - Reference simulation of kube-proxy: the daemon that programs
iptables or IPVS rules on EVERY node to load-balance Service (ClusterIP)
traffic to the backing pods.

This is the single source of truth that KUBE_PROXY.md is built from. Every
iptables rule, conntrack flow, IPVS algorithm trace, performance number, and
traffic count in the guide is printed by this file. If you change something
here, re-run and re-paste the output into the guide.

Run:
    python3 kube_proxy.py      (pure stdlib; no dependencies)

    Companion to service_endpoints.py (which covers the Service/Endpoints
    OBJECT + selector). THIS file goes deep on the kube-proxy DATA PLANE: the
    iptables chain structure, conntrack stickiness, IPVS algorithms, the
    O(n)-vs-O(1) performance story, and client-side load balancing.

================================================================================
THE INTUITION (read this first) - the switchboard operator and the two dials
================================================================================
kube-proxy is a DAEMON running on every node. It watches Services + Endpoints
and writes KERNEL RULES so a packet sent to a Service's ClusterIP
(10.96.0.10:80) is rewritten IN FLIGHT to one of the backing pods
(10.244.X.Y:8080). The rewrite happens in the ORIGINATING node's kernel - the
packet never actually "travels to the ClusterIP."

Picture kube-proxy as a SWITCHBOARD OPERATOR on every floor of a building. A
visitor (packet) dials extension 80 (the ClusterIP). The operator intercepts
and re-patches the call to ONE of three desks (pods). The operator has TWO
DIALS - and they are the whole point of this file:

  * the DATA-PLANE dial : iptables (default) vs IPVS. This decides HOW the
                           re-patch is stored in the kernel.
  * the AFFINITY dial    : none (each new call is re-balanced) vs ClientIP
                           (calls from the same visitor keep going to the same
                           desk for a while).

Why two data planes?
  * iptables : the default. kube-proxy writes a CHAIN of rules. To pick a pod it
               uses `-m statistic --mode random` - each rule claims a fraction
               of the flow. Simple, but picking a pod means WALKING the chain
               (O(n) rules). At 10K+ Services that walk gets slow.
  * IPVS     : kube-proxy talks to the kernel's IP Virtual Server (a dedicated
               L4 load balancer built into netfilter). Service lookup is a HASH
               (O(1)), and IPVS ships real schedulers: rr, wrr, lc, wlc, sed...
               Built for the internet's load-balancing scale.

CONNECTION TRACKING (conntrack) is the third piece: once a call is patched to a
desk, EVERY subsequent packet of that SAME call goes to the SAME desk - the
operator does NOT re-roll. The kernel remembers the mapping in the conntrack
table. So "random" applies only to NEW connections; within a connection,
traffic is sticky. (sessionAffinity: ClientIP extends stickiness to NEW
connections from the same client IP.)

================================================================================
HOW THE TWO DATA PLANES ARE STORED (the actual kernel state)
================================================================================
iptables mode (kube-proxy --proxy-mode=iptables) writes, per Service:
  * KUBE-SERVICES : the top dispatch chain. One rule per Service matches its
                    ClusterIP:port and jumps to KUBE-SVC-<hash>.
  * KUBE-SVC-*    : the load-balancer chain. N rules using
                    `-m statistic --mode random --probability p` to split flow
                    across N KUBE-SEP-* chains (equal weights -> p = 1/(N-i)).
  * KUBE-SEP-*    : one per endpoint. Marks the packet (KUBE-MARK-MASQ) and
                    does the DNAT (ClusterIP:port -> podIP:targetPort).

IPVS mode (kube-proxy --proxy-mode=ipvs) calls, per Service:
  * ipvsadm -A -t 10.96.0.10:80 -s <scheduler>      (add the virtual service)
  * ipvsadm -a -t 10.96.0.10:80 -r 10.244.1.5:8080 -m (add a real server,
                                                       masquerade/NAT mode)
  The kernel keeps ONE hash entry per Service (O(1) lookup) + a per-Service
  scheduler that picks a real server.

================================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
================================================================================
   kube-proxy        : the daemon on every node that turns Service+Endpoints
                       into kernel forwarding rules. Runs in iptables or IPVS.
   ClusterIP         : the stable virtual IP clients dial (here 10.96.0.10).
   KUBE-SVC-*        : the per-Service iptables chain that load-balances across
                       endpoints via statistic --mode random.
   KUBE-SEP-*        : the per-endpoint iptables chain that does the DNAT.
   -m statistic      : the iptables module kube-proxy uses for random load
     --mode random    balancing. --probability p claims p of the remaining flow.
   conntrack         : the kernel connection-tracking table. Once a flow is
                       ESTABLISHED, its DNAT is cached - packets skip the
                       statistic chain and hit the SAME backend.
   sessionAffinity   : a Service option. ClientIP makes NEW connections from the
     (ClientIP)        same client IP sticky for a TTL (default 10800s = 3h).
   IPVS              : IP Virtual Server - a kernel L4 load balancer (netfilter).
                       O(1) service lookup; schedulers rr/wrr/lc/wlc/sh/sed/nq.
   scheduler (rr/wrr): round-robin / weighted round-robin - the IPVS algorithm
                       that picks a real server. wrr honors per-endpoint weights.
   O(n) vs O(1)      : iptables walks its rule list linearly (O(rules)); IPVS
                       hashes the Service (O(1)). Matters at thousands of Svcs.
   client-side LB    : skipping kube-proxy entirely - a sidecar (Envoy/Istio)
                       or the app itself (gRPC client-side LB) picks the pod.

================================================================================
THE LINEAGE (sources)
================================================================================
   iptables / netfilter (Rusty Russell): the statistic match, DNAT, conntrack.
   IPVS (Wensong Zhang 1998+)         : the kernel L4 load balancer; schedulers.
   kube-proxy reference                : kubernetes.io, "kube-proxy" + the
                                         iptables/ipvs mode docs.
   Istio / Envoy (Lyft/Google)         : sidecar client-side load balancing.
   gRPC client-side LB                 : grpclb / xDS (pick-first vs round_robin).

KEY INVARIANTS (all asserted/printed in the sections below):
   iptables equal  : -m statistic chain gives each pod an equal 1/N share
                     (rule i claims 1/(N-i) of the remaining flow).
   conntrack       : packets of an ESTABLISHED flow reuse the cached DNAT ->
                     SAME backend, statistic chain SKIPPED.
   sessionAffinity : ClientIP makes NEW connections from the same client IP
                     sticky for the TTL (separate from conntrack).
   IPVS wrr        : deterministic weighted round-robin; proportions ==
                     weight_i / sum(weights) exactly over complete cycles.
   performance     : iptables scan = O(total rules) per packet (avg ~n/2);
                     IPVS lookup = O(1) hash. The crossover is ~thousands of Svcs.

Conventions: RNG = xorshift32 (portable to JS, byte-identical in the .html).
Fully deterministic; the .html replays the same simulations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

BANNER = "=" * 72


# ============================================================================
# 0. THE DETERMINISTIC RNG - xorshift32 (Marsaglia 2003)
#    Portable to JavaScript's bitwise operators so kube_proxy.html reproduces
#    the iptables traffic simulation EXACTLY. seed must be non-zero. Used ONLY
#    for the iptables random routing; IPVS wrr is fully deterministic (no RNG).
# ============================================================================

class RNG:
    """xorshift32. Byte-identical to the JS makeRng() in the .html."""
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
        return self._next() / 0x100000000


# ============================================================================
# 1. THE CLUSTER MODEL - Service + backends (the desks behind the switchboard)
# ============================================================================

SERVICE = {
    "name": "web",
    "clusterIP": "10.96.0.10",
    "port": 80,
    "targetPort": 8080,
}

BACKENDS = [
    {"name": "web-a", "ip": "10.244.1.5", "port": 8080, "node": "node-1"},
    {"name": "web-b", "ip": "10.244.2.3", "port": 8080, "node": "node-2"},
    {"name": "web-c", "ip": "10.244.3.7", "port": 8080, "node": "node-3"},
]

# per-backend weights for IPVS wrr (web-b gets 2x the traffic)
WEIGHTS = [1, 2, 1]


# ============================================================================
# 2. KUBE-PROXY CORE - iptables rules, routing, conntrack, IPVS
# ============================================================================

# ----------------------------------------------------------------------------
# (a) iptables mode: generate the full chain (KUBE-SERVICES -> KUBE-SVC -> SEP)
# ----------------------------------------------------------------------------

def kube_proxy_iptables_chain(svc: dict, backends: list,
                              hash_svc: str = "WEB") -> list[str]:
    """Generate the iptables rules kube-proxy writes for one Service.

    Three tiers:
      KUBE-SERVICES : dispatch - match ClusterIP:port, jump to KUBE-SVC.
      KUBE-SVC-*    : load-balance - statistic --mode random across SEPs.
                      Each rule claims 1/(remaining) of the flow that reaches it,
                      so equal-weight endpoints each get 1/N.
      KUBE-SEP-*    : DNAT - rewrite dst to podIP:targetPort.
    """
    n = len(backends)
    rules = []
    vip = f"{svc['clusterIP']}/32"
    # 1. KUBE-SERVICES dispatch (one rule per Service matches its ClusterIP)
    rules.append(f"-A KUBE-SERVICES -d {vip} -p tcp --dport {svc['port']} "
                 f"-j KUBE-SVC-{hash_svc}")
    # 2. KUBE-SVC-* : statistic random chain (equal weights)
    for i in range(n):
        remaining = n - i
        if remaining > 1:
            prob = 1.0 / remaining
            rules.append(f"-A KUBE-SVC-{hash_svc} -m statistic --mode random "
                         f"--probability {prob:.8f} -j KUBE-SEP-{hash_svc}{i}")
        else:
            rules.append(f"-A KUBE-SVC-{hash_svc} -j KUBE-SEP-{hash_svc}{n-1}")
    # 3. KUBE-SEP-* : DNAT each endpoint
    for i, b in enumerate(backends):
        rules.append(f"-A KUBE-SEP-{hash_svc}{i} -p tcp "
                     f"-j DNAT --to-destination {b['ip']}:{b['port']}")
    return rules


def iptables_route(rng: RNG, n: int) -> int:
    """Pick an endpoint index exactly as the chained statistic rules do.

    Each rule claims 1/(rules_remaining) of whatever flow reached it. With one
    uniform draw r in [0,1) we walk the chain and return the index whose bucket
    r falls into. (Same logic as service_endpoints.py; kept here so this file is
    self-contained and so the .html can re-derive it.)
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


def simulate_iptables(backends: list, n_req: int, seed: int) -> list[int]:
    """Route n_req NEW connections through the iptables chain."""
    rng = RNG(seed)
    counts = [0] * len(backends)
    for _ in range(n_req):
        counts[iptables_route(rng, len(backends))] += 1
    return counts


# ----------------------------------------------------------------------------
# (b) connection tracking: established flows stick to the same backend
# ----------------------------------------------------------------------------

@dataclass
class ConntrackFlow:
    """A tracked connection. Once ESTABLISHED, all packets reuse the cached
    DNAT backend - the statistic chain is skipped (fast path)."""
    key: tuple
    backend_idx: int
    state: str = "ESTABLISHED"


class Conntrack:
    """Model of the kernel conntrack table.

    route(key, picker):
      * known flow  -> reuse the cached backend (ESTABLISHED, sticky).
      * new flow    -> call picker() to choose a backend, record it (NEW).
    The 'key' is the 5-tuple (proto, src_ip, src_port, dst_ip, dst_port).
    """

    def __init__(self):
        self.flows: dict[tuple, ConntrackFlow] = {}

    def route(self, key: tuple, picker) -> tuple[int, str]:
        if key in self.flows:
            return self.flows[key].backend_idx, "ESTABLISHED (conntrack reuse)"
        idx = picker()
        self.flows[key] = ConntrackFlow(key, idx)
        return idx, "NEW (conntrack recorded)"


# ----------------------------------------------------------------------------
# (c) sessionAffinity: ClientIP - new connections from same client IP stick
# ----------------------------------------------------------------------------

class ClientIPAffinity:
    """Model of Service sessionAffinity: ClientIP.

    Independent of conntrack: this makes even NEW connections from the same
    client IP sticky for a TTL (default 10800s = 3h). Implemented by kube-proxy
    as an additional `-m recent` iptables rule (or an IPVS persistence table).
    """

    def __init__(self, ttl: int = 10800):
        self.ttl = ttl
        self.table: dict[str, tuple[int, int]] = {}  # client_ip -> (backend, exp)

    def route(self, client_ip: str, picker) -> tuple[int, str]:
        entry = self.table.get(client_ip)
        if entry is not None:
            return entry[0], (f"AFFINITY hit (ClientIP {client_ip} sticky, "
                              f"TTL {self.ttl}s)")
        idx = picker()
        self.table[client_ip] = (idx, self.ttl)
        return idx, (f"AFFINITY miss -> recorded ClientIP {client_ip} "
                     f"-> backend {idx} (sticky {self.ttl}s)")


# ----------------------------------------------------------------------------
# (d) IPVS mode: weighted round-robin (the ip_vs_wrr scheduler)
# ----------------------------------------------------------------------------

def ipvs_wrr_sequence(weights: list[int], n_steps: int) -> list[int]:
    """The IPVS weighted round-robin scheduler (kernel ip_vs_wrr.c).

    Produces a DETERMINISTIC sequence of backend indices whose long-run
    proportions equal weight_i / sum(weights). No RNG. One full cycle yields
    exactly sum(weights) selections, with backend i chosen weight_i times.
    """
    n = len(weights)
    gcd = weights[0]
    for w in weights[1:]:
        gcd = math.gcd(gcd, w)
    maxw = max(weights)
    seq = []
    i = -1
    cw = 0
    count = 0
    while count < n_steps:
        i = (i + 1) % n
        if i == 0:
            cw -= gcd
            if cw <= 0:
                cw = maxw
                if cw == 0:
                    break
        if weights[i] >= cw:
            seq.append(i)
            count += 1
    return seq


def ipvs_rr_sequence(n: int, n_steps: int) -> list[int]:
    """Plain round-robin (ip_vs_rr): backend = step % n. Deterministic."""
    return [s % n for s in range(n_steps)]


def simulate_ipvs_wrr(weights: list[int], n_req: int) -> list[int]:
    seq = ipvs_wrr_sequence(weights, n_req)
    counts = [0] * len(weights)
    for idx in seq:
        counts[idx] += 1
    return counts


# ----------------------------------------------------------------------------
# (e) performance model: iptables O(n) rule scan vs IPVS O(1) hash lookup
# ----------------------------------------------------------------------------

def iptables_rule_count(n_services: int, endpoints_per_service: int) -> int:
    """Total kube-proxy iptables rules for n_services x E endpoints.
    Per Service: 1 KUBE-SERVICES dispatch + E statistic rules + E DNAT rules.
    """
    return n_services * (1 + 2 * endpoints_per_service)


def iptables_scan_cost(n_services: int, endpoints_per_service: int,
                       svc_position: int) -> int:
    """Rules a packet to the svc_position-th Service must walk before matching.

    KUBE-SERVICES is scanned linearly; a packet to the k-th Service matches on
    the k-th dispatch rule (after k-1 misses), then ONE statistic rule fires.
    Worst case (last Service) = n_services. Average ~ n_services/2.
    """
    return svc_position  # dispatch rules scanned (0-indexed position)


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 4. THE SECTIONS - each prints a self-contained worked example + [check]
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: iptables mode - the full chain + equal-weight simulation
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: iptables mode - the KUBE-SVC/KUBE-SEP chain (equal 1/3)")
    print(f"Service 'web': ClusterIP {SERVICE['clusterIP']}:{SERVICE['port']} "
          f"-> targetPort {SERVICE['targetPort']}\n")
    print("Backends (the desks behind the switchboard):")
    print("  idx  name   ip:port            node")
    for i, b in enumerate(BACKENDS):
        print(f"  {i}    {b['name']:<5} {b['ip']}:{b['port']:<8}  {b['node']}")
    print()
    print("kube-proxy writes a 3-tier iptables chain:\n")
    rules = kube_proxy_iptables_chain(SERVICE, BACKENDS)
    for r in rules:
        print("  " + r)
    print()
    print("The statistic chain gives each pod an EQUAL 1/3 share:")
    print("  rule 0: 1/3 of all flow            -> web-a (KUBE-SEP-WEB0)")
    print("  rule 1: 1/2 of the remaining 2/3    -> web-b (KUBE-SEP-WEB1)")
    print("  rule 2: all remaining (= 1/3)       -> web-c (KUBE-SEP-WEB2)")
    print()
    n_req = 300
    counts = simulate_iptables(BACKENDS, n_req=n_req, seed=42)
    print(f"Simulating {n_req} NEW connections to {SERVICE['clusterIP']}:"
          f"{SERVICE['port']} (seeded xorshift32, seed=42):")
    print("  pod        hits   share")
    for i, b in enumerate(BACKENDS):
        print(f"  {b['name']:<6}     {counts[i]:<5}  {counts[i] / n_req * 100:5.1f}%")
    print(f"  {'total':<6}     {sum(counts)}")
    print()
    balanced = all(abs(c - n_req / len(BACKENDS)) <= n_req * 0.08 for c in counts)
    print(f"GOLD hit counts (pinned for kube_proxy.html) = {counts}")
    print(f"[check] each pod within 8% of {n_req // len(BACKENDS)}?  "
          f"{'OK' if balanced else 'FAIL'}")
    return counts


# ----------------------------------------------------------------------------
# SECTION B: connection tracking - established flows stick (no re-roll)
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: connection tracking - ESTABLISHED flows stick to a backend")
    print("Once a connection's first packet picks a backend, conntrack CACHES the")
    print("DNAT. Every later packet of the SAME connection hits the cached entry")
    print("and goes to the SAME backend - the statistic chain is SKIPPED (the")
    print("kernel fast-paths ESTABLISHED flows). So 'random' applies only to NEW")
    print("connections.\n")
    ct = Conntrack()
    rng = RNG(42)

    def picker() -> int:
        return iptables_route(rng, len(BACKENDS))

    client_ip = "10.0.0.50"

    print(f"Client {client_ip} opens a connection, then sends 4 more packets:")
    print("  pkt#  5-tuple key                                  -> backend  state")
    for pkt_no in range(5):
        src_port = 40000
        key = ("tcp", client_ip, src_port, SERVICE["clusterIP"], SERVICE["port"])
        idx, state = ct.route(key, picker)
        print(f"  #{pkt_no}    {client_ip}:{src_port} -> "
              f"{SERVICE['clusterIP']}:{SERVICE['port']:<13} "
              f"-> {BACKENDS[idx]['name']:<5}  {state}")
    print()
    print("All 5 packets of the connection land on the SAME backend (the first")
    print("packet's pick). Only packet #0 ran the statistic chain.\n")

    print("sessionAffinity: ClientIP extends stickiness to NEW connections:")
    print("  (a second NEW connection from the SAME client IP stays sticky)")
    aff = ClientIPAffinity(ttl=10800)
    for conn_no, src_port in enumerate([40001, 40002], 1):
        idx, state = aff.route(client_ip, picker)
        print(f"  conn#{conn_no} {client_ip}:{src_port} -> "
              f"{BACKENDS[idx]['name']:<5}  {state}")
    print()

    # checks
    assert len(ct.flows) == 1, "one connection = one conntrack flow"
    _idx2, state2 = ct.route(("tcp", client_ip, 40000, SERVICE["clusterIP"],
                              SERVICE["port"]), picker)
    assert state2.startswith("ESTABLISHED"), "cached flow must be ESTABLISHED"
    assert len(aff.table) == 1, "one client IP = one affinity entry"
    print("[check] 1 conntrack flow reused for all 5 packets; 1 affinity entry "
          "for the client IP: OK")


# ----------------------------------------------------------------------------
# SECTION C: IPVS mode - weighted round-robin + schedulers
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: IPVS mode - kernel L4 LB, schedulers (rr, wrr, lc, wlc)")
    print("In IPVS mode kube-proxy talks to the kernel's IP Virtual Server - a")
    print("dedicated L4 load balancer. Service lookup is a HASH (O(1)); the")
    print("scheduler picks a real server. Available schedulers:")
    print("  rr   round-robin            lc   least-connection")
    print("  wrr  weighted round-robin   wlc  weighted least-connection")
    print("  sh   source hashing         sed  shortest expected delay")
    print("  dh   destination hashing    nq   never queue\n")
    print(f"IPVS commands for Service {SERVICE['clusterIP']}:{SERVICE['port']}:")
    print(f"  ipvsadm -A -t {SERVICE['clusterIP']}:{SERVICE['port']} -s wrr")
    for b, w in zip(BACKENDS, WEIGHTS):
        print(f"  ipvsadm -a -t {SERVICE['clusterIP']}:{SERVICE['port']} "
              f"-r {b['ip']}:{b['port']} -m -w {w}")
    print()

    # rr (plain round-robin)
    rr = ipvs_rr_sequence(len(BACKENDS), 6)
    print(f"rr scheduler, first 6 picks: {[BACKENDS[i]['name'] for i in rr]}")
    print()

    # wrr with weights [1,2,1] -> web-b gets 2x
    print(f"weights: web-a={WEIGHTS[0]}, web-b={WEIGHTS[1]}, web-c={WEIGHTS[2]}")
    print(f"  expected proportions: web-a={WEIGHTS[0]}/{sum(WEIGHTS)}="
          f"{WEIGHTS[0]/sum(WEIGHTS)*100:.0f}%, "
          f"web-b={WEIGHTS[1]}/{sum(WEIGHTS)}={WEIGHTS[1]/sum(WEIGHTS)*100:.0f}%, "
          f"web-c={WEIGHTS[2]}/{sum(WEIGHTS)}={WEIGHTS[2]/sum(WEIGHTS)*100:.0f}%")
    wrr = ipvs_wrr_sequence(WEIGHTS, 4)
    print(f"wrr scheduler, first cycle (4 picks = sum of weights): "
          f"{[BACKENDS[i]['name'] for i in wrr]}")
    print()
    n_req = 400  # multiple of sum(weights)=4 -> exact proportions
    counts = simulate_ipvs_wrr(WEIGHTS, n_req)
    print(f"Simulating {n_req} requests through IPVS wrr (deterministic, no RNG):")
    print("  pod        hits   share    expected")
    for i, b in enumerate(BACKENDS):
        exp = WEIGHTS[i] / sum(WEIGHTS) * 100
        print(f"  {b['name']:<6}     {counts[i]:<5}  "
              f"{counts[i] / n_req * 100:5.1f}%   {exp:5.1f}%")
    print(f"  {'total':<6}     {sum(counts)}")
    print()
    exact = all(counts[i] == WEIGHTS[i] * (n_req // sum(WEIGHTS))
                for i in range(len(BACKENDS)))
    print(f"GOLD wrr counts (pinned) = {counts}")
    print(f"[check] wrr proportions EXACTLY match weights over complete cycles?  "
          f"{'OK' if exact else 'FAIL'}")
    return counts, wrr


# ----------------------------------------------------------------------------
# SECTION D: performance - iptables O(n) rule scan vs IPVS O(1) hash lookup
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: performance - iptables O(n) scan vs IPVS O(1) hash")
    print("iptables is a LINEAR rule list. A packet is matched against rules in")
    print("order until one fires. With S Services x E endpoints, kube-proxy")
    print("writes ~S*(2E+1) rules. A packet to the LAST Service walks nearly ALL")
    print("of them before matching. IPVS instead hashes the Service (O(1)).\n")
    print("  | cluster size | Services | ep/Svc | iptables rules | "
          "avg scan | worst scan | IPVS lookup |")
    print("  |--------------|----------|--------|----------------|----------|"
          "------------|-------------|")
    eps = 10
    for n_svc in [100, 1000, 10000, 100000]:
        rules = iptables_rule_count(n_svc, eps)
        avg = n_svc // 2
        worst = n_svc
        print(f"  | {f'{n_svc} Svcs':<12} | {n_svc:<8} | {eps:<6} | "
              f"{rules:<14,} | {avg:<8} | {worst:<10} | O(1) hash   |")
    print()
    print("Read it as: at 10K Services x 10 endpoints, iptables ships ~210K rules")
    print("and a typical packet walks ~5K of them. IPVS does ONE hash lookup.")
    print("That is why IPVS is recommended for clusters with thousands of")
    print("Services. (Cilium's eBPF data plane removes both - see cni.py.)\n")
    # sanity: rule count formula
    assert iptables_rule_count(1000, 10) == 21000
    assert iptables_scan_cost(1000, 10, 999) == 999   # worst = last svc
    print("[check] 1000 Svcs x 10 ep = 21000 rules; worst-case scan = 999: OK")


# ----------------------------------------------------------------------------
# SECTION E: client-side load balancing (no kube-proxy)
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: client-side load balancing - skipping kube-proxy")
    print("kube-proxy load-balances IN THE KERNEL of the originating node. An")
    print("alternative is to load-balance IN THE CLIENT, skipping kube-proxy")
    print("(and the ClusterIP) entirely. Two common forms:\n")
    rows = [
        ("Envoy sidecar (Istio)",
         "proxy container per pod; xDS-discovered cluster; RR / least-request",
         "service mesh; sidecar injected"),
        ("gRPC client-side LB",
         "the gRPC channel balances: pick-first or round_robin over pod IPs",
         "app uses gRPC; no kernel rules"),
    ]
    print("  | approach               | how it picks a pod                          "
          "| when to use             |")
    print("  |------------------------|---------------------------------------------|"
          "-------------------------|")
    for name, how, when in rows:
        print(f"  | {name:<22} | {how:<43} | {when:<23} |")
    print()
    print("Trade-off: client-side LB removes kube-proxy's O(n) cost and the"
          " ClusterIP indirection, but REQUIRES every client to speak the LB"
          " protocol (gRPC) or carry a sidecar (Envoy). Plain HTTP/TCP clients"
          " still need kube-proxy.\n")
    print("With a Headless Service (clusterIP: None), DNS returns the pod IPs")
    print("directly - the client-side LB iterates them. No kube-proxy rules are")
    print("written at all. (See service_endpoints.py Section D for headless.)\n")
    assert "Envoy" in rows[0][0] and "gRPC" in rows[1][0]
    print("[check] two client-side LB paths modeled (Envoy sidecar, gRPC): OK")


# ----------------------------------------------------------------------------
# GOLD: traffic distribution matches expected weights (the bundle's gold-check)
# ----------------------------------------------------------------------------

def section_gold(ipt_counts, wrr_counts, wrr_seq):
    banner("GOLD: traffic distribution matches expected weights")
    print("The bundle's gold-check: traffic distribution matches the EXPECTED")
    print("WEIGHTS for both data planes. The .html recomputes both simulations")
    print("from the IDENTICAL RNG + IPVS functions.\n")

    # iptables equal-weight gold
    n = len(BACKENDS)
    print("GOLD 1 - iptables mode (equal weights, seed=42, 300 reqs):")
    print(f"  counts = {ipt_counts}   (each pod ~{300 // n})")
    ok_ipt = all(abs(c - 300 / n) <= 300 * 0.08 for c in ipt_counts)
    print(f"  [check] within 8% of {300 // n}?  {'OK' if ok_ipt else 'FAIL'}\n")

    # IPVS wrr gold
    print(f"GOLD 2 - IPVS wrr (weights {WEIGHTS}, 400 reqs = 100 cycles):")
    print(f"  counts        = {wrr_counts}")
    print(f"  first cycle   = {[BACKENDS[i]['name'] for i in wrr_seq]}")
    expected = [WEIGHTS[i] * (400 // sum(WEIGHTS)) for i in range(n)]
    print(f"  expected      = {expected}  (weight_i * 100)")
    ok_wrr = wrr_counts == expected
    print(f"  [check] counts == expected?  {'OK' if ok_wrr else 'FAIL'}\n")

    print("GOLD summary (feeds kube_proxy.html):\n")
    ipt_w = "[1,1,1]"
    wrr_w = "[" + ",".join(str(w) for w in WEIGHTS) + "]"
    print("  | # | mode          | weights  | counts            | "
          "expected proportions |")
    print("  |---|---------------|----------|-------------------|"
          "----------------------|")
    print(f"  | 1 | iptables rand | {ipt_w:<8} | {str(ipt_counts):<17} | "
          "~33% / 33% / 33%       |")
    print(f"  | 2 | IPVS wrr      | {wrr_w:<8} | {str(wrr_counts):<17} | "
          "25% / 50% / 25%        |")
    print()
    print("[check] both distributions match expected weights: "
          f"{'OK' if ok_ipt and ok_wrr else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main():
    print("kube_proxy.py - reference simulation of the kube-proxy data plane.")
    print("All numbers below feed KUBE_PROXY.md.")
    print("stdlib only; deterministic. RNG = xorshift32 (portable to JS).")

    ipt_counts = section_a()
    section_b()
    wrr_counts, wrr_seq = section_c()
    section_d()
    section_e()
    section_gold(ipt_counts, wrr_counts, wrr_seq)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
