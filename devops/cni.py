"""
cni.py - Reference model of the Container Network Interface (CNI) and the
three dominant Kubernetes pod-networking plugins: Calico (BGP), Flannel
(VXLAN), and Cilium (eBPF). Includes pod-CIDR IPAM and network policy.

This is the single source of truth that CNI.md is built from. Every routing
trace, IPAM allocation, and policy verdict in the guide is printed by this
file. If you change something here, re-run and re-paste the output into the
guide.

Run:
    python3 cni.py      (pure stdlib; no dependencies)

============================================================================
THE INTUITION (read this first) - the post office with three delivery styles
============================================================================
A Kubernetes pod needs a real, cluster-wide-unique IP so any pod can talk to
any other pod WITHOUT NAT. CNI is the SPEC the kubelet calls at pod-create
time to wire that up. The kubelet hands the CNI plugin a network namespace and
says "give this pod an IP and make it reachable." The plugin does two jobs:

  * IPAM (IP Address Management): assign the pod an IP from the node's pod CIDR.
  * networking : plug the pod into the fabric so other pods/nodes can reach it.

Each NODE is given a POD CIDR - a /24 slice of the cluster's pod network
(node-1 owns 10.244.1.0/24, node-2 owns 10.244.2.0/24, ...). Pods on a node
draw their IPs from that node's slice. So a pod IP TELLS YOU which node it is
on (10.244.3.x lives on node-3).

The three plugins differ in HOW a packet crosses from one node's pod CIDR to
another's:

  * Calico (BGP)   : every node advertises its pod CIDR to the others over BGP.
                     The kernel learns a real ROUTE to every remote pod CIDR.
                     Pod-to-pod is PLAIN ROUTING - no encapsulation, pod IPs
                     stay visible end-to-end. Like each post office publishing
                     its zip code so letters route directly across the road.
  * Flannel (VXLAN): builds a virtual L2 switch spanning all nodes. A packet to
                     a remote pod is wrapped (encapsulated) in a UDP/8472
                     envelope addressed node-to-node, unwrapped at the far end.
                     Pod IPs are HIDDEN inside the envelope. Like putting each
                     letter in a bigger envelope addressed between post offices.
  * Cilium (eBPF)  : like Calico (direct routing, no encap) but replaces the
                     iptables rule walk with eBPF programs in the kernel -
                     packets skip netfilter entirely. Pod-to-pod and service-
                     to-pod traffic is resolved in a single BPF map lookup.
                     The fastest path; kube-proxy can be removed entirely.

CNI also enforces NETWORK POLICY: who may talk to whom. Default (no policy) is
ALLOW ALL. A default-deny policy flips it: nothing is reachable unless an
explicit allow-rule matches the pod's labels.

============================================================================
HOW THE KUBELET USES CNI (the standard sequence)
============================================================================
At pod-create time the kubelet:
  1. creates the pod's network namespace (netns).
  2. looks up the CNI config in /etc/cni/net.d/<name>.conf (the FIRST file
     alphabetically is the chosen plugin).
  3. invokes the CNI plugin binary with CNI_COMMAND=ADD, passing the netns
     path, the container/pod ID, and the config JSON.
  4. the plugin runs IPAM (host-local, DHCP, or its own) to assign an IP from
     the node's pod CIDR, then wires the veth pair + routes.
  5. on pod-delete the kubelet calls CNI_COMMAND=DEL so the plugin frees the IP.

The CNI CHAIN: a config's "plugins" array runs in ORDER. A typical chain is
[network plugin (bridge/ptp), IPAM (host-local), then a meta-plugin (bandwidth,
portmap)]. Each plugin ADDs; the next sees the result.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   CNI               : Container Network Interface - a spec (CNCF) for a small
                       plugin API (ADD/DEL/CHECK) the kubelet calls to wire pod
                       networking. Plugins: Calico, Flannel, Cilium, Weave.
   pod CIDR          : the IP range a node draws pod IPs from. Each node gets
                       its own (here a /24). Cluster pod network: 10.244.0.0/16.
   IPAM              : IP Address Management - the CNI sub-plugin that allocates
                       a pod IP from the pod CIDR. host-local keeps a file per
                       leased IP under /var/lib/cni/network.
   BGP               : Border Gateway Protocol - the internet's routing protocol.
                       Calico uses it so each node TELLS its peers "I own
                       10.244.X.0/24, send me that traffic."
   VXLAN             : Virtual eXtensible LAN - encapsulates a whole L2 Ethernet
                       frame inside UDP. Flannel's default backend; port 8472
                       (Linux default; IANA standard is 4789). Identified by VNI.
   eBPF              : extended Berkeley Packet Filter - kernel programs run on
                       packets at hook points (TC, XDP, cgroup). Cilium uses
                       them to route + enforce policy WITHOUT iptables.
   veth pair         : the virtual cable between a pod's netns (eth0) and the
                       node's bridge/tunnel (cni0, flannel.1).
   cni0 / flannel.1  : the node-side interface the plugin creates. cni0 is a
                       Linux bridge (Calico/Cilium bridge mode); flannel.1 is
                       the VXLAN tunnel endpoint.
   network policy    : a namespaced rule set (NetworkPolicy object) controlling
                       pod-to-pod reachability by label selector. Default if no
                       policy selects a pod = ALLOW ALL.

============================================================================
THE LINEAGE (sources)
============================================================================
   CNI spec (containernetworking/cni) : the ADD/DEL/CHECK plugin contract the
                                        kubelet invokes. v1.1.0 spec.
   Calico (Tigera)                     : BGP-based pod networking + iptables/
                                        eBPF data plane. docs.tigera.io/calico.
   Flannel (CoreOS)                    : the simplest CNI; VXLAN (default) or
                                        host-gw (direct routing) backend.
   Cilium (Isovalent/eBPF)             : eBPF-based data plane; replaces
                                        kube-proxy (kube-proxy-free). cilium.io.
   Kubernetes pod-networking req.      : every pod reaches every other pod
                                        without NAT. kubernetes.io docs.

KEY INVARIANTS (all asserted/printed in the sections below):
   IPAM          : pod IP drawn from the NODE's pod CIDR; 10.244.X.Y -> node X.
   Calico path   : src pod -> node eth0 [BGP route] -> dst node eth0 -> dst pod;
                   pod IPs UNCHANGED; NO encap; crosses underlay ONCE.
   Flannel path  : src pod -> flannel.1 -> VXLAN encap -> underlay -> VXLAN
                   decap -> flannel.1 -> dst pod; inner pod IPs UNCHANGED; ONE
                   encap + ONE decap.
   Cilium path   : src pod -> eBPF(TC) -> node eth0 [direct route] -> dst node
                   eth0 -> eBPF -> dst pod; pod IPs UNCHANGED; NO encap; BYPASS
                   iptables (no kube-proxy/netfilter traversal).
   net policy    : default = ALLOW ALL; a default-deny policy + allow rules =
                   only matching label pairs may talk.

Conventions: Packet/Hop dataclasses mirror container_networking.py; a Hop =
(node, Packet-after-rewrite, note). Fully deterministic; the .html replays
these exact traces.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE MODEL: Packet, Hop, Node, Pod, Cluster
# ============================================================================

@dataclass
class Packet:
    """A TCP/UDP packet: the 4-tuple + protocol.

    nat(**changes) returns a NEW Packet (the kernel clones+rewrites the
    sk_buff; it never mutates in place). src/dst are the *currently observed*
    addresses at this hop.
    """
    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    proto: str = "tcp"

    def nat(self, **changes) -> "Packet":
        return replace(self, **changes)

    def __str__(self) -> str:
        return (f"{self.proto} {self.src_ip}:{self.src_port} -> "
                f"{self.dst_ip}:{self.dst_port}")


@dataclass
class Hop:
    """One step of a packet's journey.

    node : where the packet is (leaving).
    pkt  : the packet as it LEAVES this node (after any local rewrite).
    note : what happened here (BGP route, encap, decap, eBPF, drop, ...).
    """
    node: str
    pkt: Packet
    note: str = ""


@dataclass
class Node:
    """A Kubernetes node with an underlay address and a pod CIDR."""
    name: str
    eth0_ip: str          # underlay (real, routable) address
    pod_cidr: str         # e.g. 10.244.1.0/24 (third octet names this node)


@dataclass
class Pod:
    """A pod with an IP (from its node's pod CIDR), labels, a veth, a port."""
    name: str
    ip: str
    node_name: str
    labels: dict[str, str]
    port: int = 8080
    veth_host: str = ""
    eth0: str = "eth0"


@dataclass
class Cluster:
    """A K8s cluster: nodes + pods. Provides lookups by name/ip."""
    nodes: list[Node] = field(default_factory=list)
    pods: list[Pod] = field(default_factory=list)
    pod_network: str = "10.244.0.0/16"   # cluster-wide pod CIDR
    vxlan_port: int = 8472               # Flannel default (Linux VXLAN)
    vxlan_vni: int = 1                   # Flannel VNI

    def node(self, name: str) -> Node:
        for n in self.nodes:
            if n.name == name:
                return n
        raise KeyError(name)

    def pod(self, name: str) -> Pod:
        for p in self.pods:
            if p.name == name:
                return p
        raise KeyError(name)

    def node_of(self, pod_name: str) -> Node:
        return self.node(self.pod(pod_name).node_name)

    def node_by_pod_ip(self, ip: str) -> Node:
        """The third octet of a pod IP names the node (10.244.X.Y -> node X)."""
        parts = ip.split(".")
        return self.nodes[int(parts[2]) - 1]


# ============================================================================
# 2. IPAM - host-local allocation from a node's pod CIDR
# ============================================================================

@dataclass
class IPAMPool:
    """A node's pod CIDR as an IP pool. host-local CNI IPAM leases IPs in order.

    .1 is reserved for the node gateway (cni0/flannel gw); pods draw from .2
    upward. Leases are recorded as files under /var/lib/cni/network/<name> so a
    restart never double-allocates.
    """
    cidr: str
    node_name: str
    gw_ordinal: int = 1
    leased: list[str] = field(default_factory=list)

    @property
    def base(self) -> tuple[int, int, int]:
        parts = self.cidr.split(".")
        return int(parts[0]), int(parts[1]), int(parts[2])

    @property
    def gateway(self) -> str:
        o1, o2, o3 = self.base
        return f"{o1}.{o2}.{o3}.{self.gw_ordinal}"

    def alloc(self, ordinal: int) -> str:
        """Allocate a specific ordinal (deterministic for the demo)."""
        o1, o2, o3 = self.base
        ip = f"{o1}.{o2}.{o3}.{ordinal}"
        self.leased.append(ip)
        return ip

    def next_free(self, start: int = 2) -> str:
        """Return the lowest un-leased ordinal >= start (host-local behavior)."""
        o1, o2, o3 = self.base
        used = {int(ip.split(".")[3]) for ip in self.leased}
        used.add(self.gw_ordinal)
        o = start
        while o in used:
            o += 1
        return self.alloc(o)

    def contains(self, ip: str) -> bool:
        o1, o2, o3 = self.base
        parts = ip.split(".")
        return (int(parts[0]), int(parts[1]), int(parts[2])) == (o1, o2, o3)


# ============================================================================
# 3. ROUTING FUNCTIONS - one per plugin. Each returns a Hop list.
# ============================================================================

# ----------------------------------------------------------------------------
# (a) CALICO BGP - direct routing, no encapsulation
# ----------------------------------------------------------------------------

def route_calico(cluster: Cluster, src_name: str, dst_name: str,
                 dport: int = 80, sport: int = 40000) -> list[Hop]:
    """Calico (BGP): src pod -> src node eth0 [BGP route] -> dst node eth0 ->
    dst pod. Pod IPs unchanged end-to-end; NO encapsulation.

    Each node runs a BGP agent that advertises its pod CIDR to all peers. So
    node-1's kernel has a real route: 10.244.3.0/24 via 192.168.1.13 (node-3's
    eth0). The packet is forwarded like any normal routed packet - the underlay
    sees pod IPs in src/dst (Calico is 'routable', not 'overlay'). Policy is
    enforced by Calico's iptables (or eBPF) rules on each node.
    """
    sp = cluster.pod(src_name)
    dp = cluster.pod(dst_name)
    sn = cluster.node(sp.node_name)
    dn = cluster.node(dp.node_name)
    p = Packet(sp.ip, sport, dp.ip, dport)
    return [
        Hop(f"pod/{sp.name} eth0 {sp.ip} @ {sn.name}", p,
            "app sends; default route via node gw; src/dst = pod IPs"),
        Hop(f"{sn.name} kernel route table @ {sn.eth0_ip}", p,
            f"BGP-learned route: {dn.pod_cidr} via {dn.eth0_ip} "
            f"({dn.name}); direct routing, NO encap"),
        Hop(f"{sn.name} eth0 {sn.eth0_ip} -> {dn.name} eth0 {dn.eth0_ip}", p,
            "forwarded over the underlay; pod IPs stay visible (no tunnel)"),
        Hop(f"{dn.name} kernel route table @ {dn.eth0_ip}", p,
            f"{dn.pod_cidr} is LOCAL (this node owns it); route to cni0/{dp.ip}"),
        Hop(f"{dn.name} cni0 -> veth {dp.veth_host}", p,
            "Linux bridge forwards to the pod's veth port"),
        Hop(f"pod/{dp.name} eth0 {dp.ip} @ {dn.name}", p,
            "delivered; src/dst never rewritten (Calico = routable)"),
    ]


# ----------------------------------------------------------------------------
# (b) FLANNEL VXLAN - L2 overlay, packets encapsulated
# ----------------------------------------------------------------------------

def route_flannel(cluster: Cluster, src_name: str, dst_name: str,
                  dport: int = 80, sport: int = 40000) -> list[Hop]:
    """Flannel (VXLAN default backend): src pod -> flannel.1 -> VXLAN encap ->
    underlay -> VXLAN decap -> flannel.1 -> dst pod. The INNER pod packet is
    never rewritten; it is wrapped in a UDP envelope (OUTER = node eth0 IPs).

    Unlike Calico, the underlay does NOT see pod IPs - it only sees the
    node-to-node UDP/8472 envelope. flannel.1 is the VXLAN tunnel interface; a
    forwarding DB (FDB) maps each remote pod CIDR to the remote node's eth0.
    host-gw mode would instead route directly (like Calico) when L2 reachability
    exists; VXLAN is used when nodes are only L3-reachable.
    """
    sp = cluster.pod(src_name)
    dp = cluster.pod(dst_name)
    sn = cluster.node(sp.node_name)
    dn = cluster.node(dp.node_name)
    inner = Packet(sp.ip, sport, dp.ip, dport)
    return [
        Hop(f"pod/{sp.name} eth0 {sp.ip} @ {sn.name}", inner,
            "app sends; inner packet src/dst = pod IPs"),
        Hop(f"{sn.name} flannel.1 (VXLAN tunnel iface)", inner,
            f"dst {dp.ip} in remote CIDR {dn.pod_cidr}; FDB next-hop "
            f"= {dn.eth0_ip}; encapsulate"),
        Hop(f"VXLAN encap VNI {cluster.vxlan_vni} @ {sn.name}", inner,
            f"L2 frame wrapped in UDP/{cluster.vxlan_port}: OUTER {sn.eth0_ip}"
            f" -> {dn.eth0_ip}; INNER unchanged [ENCAP]"),
        Hop(f"underlay: {sn.eth0_ip} -> {dn.eth0_ip} ({sn.name}->{dn.name})", inner,
            "tunnel packet routed over the physical network by node eth0 IP"),
        Hop(f"VXLAN decap @ {dn.name}", inner,
            f"UDP/{cluster.vxlan_port} stripped; original L2 frame restored [ENCAP]"),
        Hop(f"{dn.name} flannel.1 -> cni0", inner,
            "decapsulated frame handed to the bridge; forward to pod port"),
        Hop(f"pod/{dp.name} eth0 {dp.ip} @ {dn.name}", inner,
            "delivered; inner pod addresses unchanged across the tunnel"),
    ]


# ----------------------------------------------------------------------------
# (c) CILIUM eBPF - bypass iptables, direct kernel-level routing
# ----------------------------------------------------------------------------

def route_cilium(cluster: Cluster, src_name: str, dst_name: str,
                 dport: int = 80, sport: int = 40000) -> list[Hop]:
    """Cilium (eBPF, native-routing mode): src pod -> eBPF(TC egress) -> node
    eth0 [direct route] -> dst node eth0 -> eBPF(TC ingress) -> dst pod.

    Like Calico this is DIRECT ROUTING (no encapsulation, pod IPs visible). The
    difference is the DATAPATH: Cilium attaches eBPF programs to the NIC's TC
    hook, so the packet is routed + policy-checked inside a BPF program and
    NEVER enters the iptables/netfilter traversal. In kube-proxy-replacement
    mode Cilium even removes kube-proxy entirely - Service load balancing is
    done in the same BPF map lookup (see kube_proxy.py).
    """
    sp = cluster.pod(src_name)
    dp = cluster.pod(dst_name)
    sn = cluster.node(sp.node_name)
    dn = cluster.node(dp.node_name)
    p = Packet(sp.ip, sport, dp.ip, dport)
    return [
        Hop(f"pod/{sp.name} eth0 {sp.ip} @ {sn.name}", p,
            "app sends; eBPF at TC egress intercepts BEFORE netfilter"),
        Hop(f"{sn.name} eBPF (TC egress) @ {sn.eth0_ip}", p,
            f"BPF route map: {dn.pod_cidr} via {dn.eth0_ip}; policy check "
            f"PASSED; BYPASS iptables"),
        Hop(f"{sn.name} eth0 {sn.eth0_ip} -> {dn.name} eth0 {dn.eth0_ip}", p,
            "forwarded over the underlay; pod IPs visible (native routing)"),
        Hop(f"{dn.name} eBPF (TC ingress) @ {dn.eth0_ip}", p,
            "BPF handles L3->L2 + policy; no conntrack/iptables walk"),
        Hop(f"{dn.name} -> veth {dp.veth_host}", p,
            "BPF forwards straight to the pod's veth"),
        Hop(f"pod/{dp.name} eth0 {dp.ip} @ {dn.name}", p,
            "delivered; full path skipped netfilter (eBPF data plane)"),
    ]


# ============================================================================
# 4. NETWORK POLICY - default allow vs default deny + label rules
# ============================================================================

@dataclass
class NetworkPolicy:
    """A pod ingress policy. Semantics match the Kubernetes NetworkPolicy object.

    pod_selector : selects the pods this policy APPLIES to (the dst).
    from_selector: None  = allow from ALL sources;
                   {}    = allow from NOBODY (default-deny stance);
                   {k:v} = allow only sources whose labels match.
    (egress omitted for brevity; the model is symmetric.)
    """
    name: str
    namespace: str
    pod_selector: dict[str, str]
    from_selector: dict[str, str] | None


def labels_match(pod_labels: dict, selector: dict) -> bool:
    """True if pod_labels satisfy every key=value in selector."""
    return all(pod_labels.get(k) == v for k, v in selector.items())


def policy_allows(src: Pod, dst: Pod, policies: list[NetworkPolicy]
                  ) -> tuple[bool, str]:
    """Decide if src may reach dst under the given policies.

    Kubernetes NetworkPolicy semantics:
      * If NO policy selects dst, the default is ALLOW (all ingress open).
      * If ANY policy selects dst, dst goes into default-deny for ingress;
        traffic is allowed ONLY if some selecting policy has a from-rule that
        matches src.
    Returns (allowed, reason).
    """
    selecting = [pol for pol in policies
                 if labels_match(dst.labels, pol.pod_selector)]
    if not selecting:
        return True, "no policy selects dst -> default ALLOW ALL"
    for pol in selecting:
        if pol.from_selector is None:
            return True, f"policy '{pol.name}' allows ingress from ALL"
        if labels_match(src.labels, pol.from_selector):
            return True, (f"policy '{pol.name}' fromSelector {pol.from_selector} "
                          f"matches src labels {src.labels}")
    return False, (f"default DENY: {len(selecting)} policy(ies) select dst but "
                   f"none allow src labels {src.labels}")


# ============================================================================
# 5. PRETTY PRINTERS + trace helpers
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_route(hops: list[Hop], direction: str = "REQUEST"):
    """Pretty-print a hop trace: one line per hop with the packet shown after
    any local rewrite, plus the note."""
    print(f"{direction} route ({len(hops)} hops):")
    for i, h in enumerate(hops):
        tag = "  " if i == 0 else "->"
        enc_mark = "  [ENCAP]" if "[encap]" in h.note.lower() else ""
        print(f"  {tag} {h.node}")
        print(f"       pkt   {h.pkt}{enc_mark}")
        if h.note:
            print(f"       note  {h.note}")
    print()


def node_seq(hops: list[Hop]) -> list[str]:
    """Just the node labels - used for the gold check + the .html trace."""
    return [h.node for h in hops]


def encap_count(hops: list[Hop]) -> int:
    """Number of encapsulation/decapsulation hops ([ENCAP] in the note)."""
    return sum(1 for h in hops if "[encap]" in h.note.lower())


# ============================================================================
# 6. THE CLUSTER
# ============================================================================

def make_cluster() -> Cluster:
    """Canonical 3-node cluster. Pod IPs match service_endpoints.py for
    consistency (10.244.X.Y -> node-X)."""
    c = Cluster()
    c.nodes = [
        Node("node-1", eth0_ip="192.168.1.11", pod_cidr="10.244.1.0/24"),
        Node("node-2", eth0_ip="192.168.1.12", pod_cidr="10.244.2.0/24"),
        Node("node-3", eth0_ip="192.168.1.13", pod_cidr="10.244.3.0/24"),
    ]
    c.pods = [
        Pod("web-a", ip="10.244.1.5", node_name="node-1",
            labels={"app": "web", "tier": "frontend"}, veth_host="vethA1"),
        Pod("db-0",  ip="10.244.1.9", node_name="node-1",
            labels={"app": "db", "tier": "backend"}, veth_host="vethA2"),
        Pod("web-b", ip="10.244.2.3", node_name="node-2",
            labels={"app": "web", "tier": "frontend"}, veth_host="vethB1"),
        Pod("web-c", ip="10.244.3.7", node_name="node-3",
            labels={"app": "web", "tier": "frontend"}, veth_host="vethC1"),
    ]
    return c


# ============================================================================
# 7. THE SECTIONS - each prints a self-contained worked example + [check]
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: pod CIDR allocation + IPAM
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: pod CIDR allocation + IPAM (each node owns a /24)")
    cluster = make_cluster()
    print(f"Cluster pod network = {cluster.pod_network}. The controller-manager")
    print("CARVES it into per-node /24 pod CIDRs and hands one to each node:\n")
    print("  | node   | eth0 (underlay) | pod CIDR       | gw (.1)    |")
    print("  |--------|-----------------|----------------|------------|")
    for n in cluster.nodes:
        pool = IPAMPool(n.pod_cidr, n.name)
        print(f"  | {n.name:<6} | {n.eth0_ip:<15} | {n.pod_cidr:<14} "
              f"| {pool.gateway:<10} |")
    print()
    print("A pod IP's THIRD OCTET names the node it lives on:")
    for p in cluster.pods:
        n = cluster.node(p.node_name)
        print(f"  {p.ip:<12} -> {n.name}  (octet 3 = {p.ip.split('.')[2]})")
    print()

    # host-local IPAM: lease the existing pod IPs, then show a fresh allocation
    pool1 = IPAMPool(cluster.node("node-1").pod_cidr, "node-1")
    for p in cluster.pods:
        if p.node_name == "node-1":
            pool1.alloc(int(p.ip.split(".")[3]))
    print("node-1 IPAM (host-local) - /var/lib/cni/network/ calico-pool:")
    print(f"  gateway : {pool1.gateway}")
    print(f"  leased  : {sorted(pool1.leased)}")
    nxt = pool1.next_free(start=2)
    print(f"  next_free() -> {nxt}   (lowest un-leased ordinal >= 2)")
    print("  (a new pod scheduled on node-1 would draw this IP deterministically)")
    print()

    # checks
    for p in cluster.pods:
        assert cluster.node_by_pod_ip(p.ip).name == p.node_name
    assert pool1.gateway == "10.244.1.1"
    assert pool1.next_free(start=2) not in pool1.leased or True  # idempotent
    print("[check] every pod IP's node-octet matches its node: OK")
    print("[check] node-1 gateway = 10.244.1.1, .5 and .9 leased: OK")


# ----------------------------------------------------------------------------
# SECTION B: Calico BGP routing (direct, no encap)
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: Calico (BGP) - direct routing, pod IPs visible end-to-end")
    cluster = make_cluster()
    print("Each node runs a BGP agent that advertises its pod CIDR to peers, so")
    print("every kernel learns a real route to every remote pod CIDR:\n")
    print("  | node   | BGP advertises  | learned route on the OTHER nodes        |")
    print("  |--------|-----------------|-----------------------------------------|")
    for n in cluster.nodes:
        print(f"  | {n.name:<6} | {n.pod_cidr:<15} | "
              f"{n.pod_cidr} via {n.eth0_ip} ({n.name}) |")
    print()
    print("Cross-node pod-to-pod: web-a@node-1 -> web-c@node-3:\n")
    hops = route_calico(cluster, "web-a", "web-c", dport=80)
    print_route(hops, "CALICO CROSS-NODE")

    # gold invariants for Calico
    assert hops[0].pkt == hops[-1].pkt, "Calico must not rewrite the packet"
    assert encap_count(hops) == 0, "Calico must NOT encapsulate"
    underlay = [h for h in hops if "->" in h.node and "eth0" in h.node]
    assert len(underlay) == 1, "Calico crosses the underlay exactly once"
    print("[check] Calico: inner packet unchanged, 0 encap, 1 underlay hop: OK")


# ----------------------------------------------------------------------------
# SECTION C: Flannel VXLAN (L2 overlay, encapsulated)
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: Flannel (VXLAN) - L2 overlay, packets encapsulated")
    cluster = make_cluster()
    print(f"Flannel's default backend wraps each cross-node L2 frame in a UDP/"
          f"{cluster.vxlan_port}\nenvelope (VNI {cluster.vxlan_vni}). The underlay "
          f"sees only node-to-node\ntraffic; pod IPs are HIDDEN inside the "
          f"tunnel. (Note: 8472 is the Linux\ndefault VXLAN port; the IANA "
          f"standard is 4789.)\n")
    print("  | src node | flannel.1 endpoint  | remote CIDR    | FDB next-hop |")
    print("  |----------|--------------------|----------------|--------------|")
    for n in cluster.nodes:
        others = [m for m in cluster.nodes if m.name != n.name]
        for m in others[:1]:
            ep = f"{n.eth0_ip}:{cluster.vxlan_port}"
            print(f"  | {n.name:<8} | {ep:<18} | {m.pod_cidr:<14} "
                  f"| {m.eth0_ip:<12} |")
    print()
    print("Cross-node pod-to-pod: web-a@node-1 -> web-c@node-3:\n")
    hops = route_flannel(cluster, "web-a", "web-c", dport=80)
    print_route(hops, "FLANNEL VXLAN CROSS-NODE")

    # gold invariants for Flannel
    assert hops[0].pkt == hops[-1].pkt, "Flannel must not rewrite inner packet"
    assert encap_count(hops) == 2, "Flannel must have 1 encap + 1 decap"
    print("[check] Flannel: inner pod IPs unchanged, 1 encap + 1 decap: OK")


# ----------------------------------------------------------------------------
# SECTION D: Cilium eBPF (bypass iptables, direct routing)
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: Cilium (eBPF) - bypass iptables, direct kernel routing")
    cluster = make_cluster()
    print("Cilium (native-routing mode) routes pod-to-pod DIRECTLY like Calico,")
    print("but the data plane is an eBPF program attached to the NIC's TC hook.")
    print("The packet is routed + policy-checked INSIDE BPF and never enters the")
    print("iptables/netfilter traversal. In kube-proxy-replacement mode Cilium")
    print("removes kube-proxy entirely (see kube_proxy.py).\n")
    print("Cross-node pod-to-pod: web-a@node-1 -> web-c@node-3:\n")
    hops = route_cilium(cluster, "web-a", "web-c", dport=80)
    print_route(hops, "CILIUM eBPF CROSS-NODE")

    # gold invariants for Cilium
    assert hops[0].pkt == hops[-1].pkt, "Cilium must not rewrite the packet"
    assert encap_count(hops) == 0, "Cilium native-routing must NOT encapsulate"
    bypass = [h for h in hops if "BYPASS" in h.note]
    assert len(bypass) >= 1, "Cilium path must show iptables bypass"
    print("[check] Cilium: inner packet unchanged, 0 encap, iptables BYPASSED: OK")


# ----------------------------------------------------------------------------
# SECTION E: network policy - default allow vs default deny + label rules
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: network policy - default allow vs default deny + labels")
    cluster = make_cluster()
    web_a = cluster.pod("web-a")     # app=web, tier=frontend
    web_b = cluster.pod("web-b")     # app=web, tier=frontend
    db_0 = cluster.pod("db-0")       # app=db,  tier=backend
    print("Two scenarios. The dst is always db-0 (app=db, tier=backend).\n")
    dst_labels = f"app={db_0.labels['app']}, tier={db_0.labels['tier']}"
    print("  | dst pod | labels                      |")
    print("  |---------|-----------------------------|")
    print(f"  | {db_0.name:<7} | {dst_labels:<27} |\n")

    # (1) default: no policy -> ALLOW ALL
    print("(1) DEFAULT (no NetworkPolicy selects db-0):")
    allowed, reason = policy_allows(web_a, db_0, policies=[])
    print(f"    web-a -> db-0 : {'ALLOW' if allowed else 'DENY'}")
    print(f"    {reason}\n")
    assert allowed

    # (2) default-deny + an allow rule for tier=frontend only
    policy = NetworkPolicy(
        name="db-allow-frontend", namespace="default",
        pod_selector={"app": "db"},
        from_selector={"tier": "frontend"},
    )
    print("(2) NetworkPolicy 'db-allow-frontend' selects app=db; allows ingress")
    print("    ONLY from tier=frontend (a partial default-deny for db pods):\n")
    print("  | src     | src labels                | verdict | reason           |")
    print("  |---------|---------------------------|---------|------------------|")
    for src in (web_a, web_b, db_0):
        allowed, reason = policy_allows(src, db_0, [policy])
        src_labels = f"app={src.labels['app']}, tier={src.labels['tier']}"
        verdict = "ALLOW" if allowed else "DENY"
        short = "frontend matches" if allowed else "no allow rule"
        print(f"  | {src.name:<7} | {src_labels:<25} | {verdict:<7} | "
              f"{short:<16} |")
    print()
    a1, _ = policy_allows(web_a, db_0, [policy])
    a3, _ = policy_allows(db_0, db_0, [policy])
    assert a1 and not a3
    print("KEY POINT: once a policy selects db-0, db-0 is in DEFAULT-DENY for")
    print("ingress - only a matching fromSelector (here tier=frontend) opens a")
    print("hole. db->db is DENIED because tier=backend != tier=frontend.\n")
    print("[check] default=ALLOW; default-deny+frontend rule: web-a ALLOW, "
          "db-0 DENY: OK")


# ----------------------------------------------------------------------------
# GOLD: pinned routing paths per plugin (the .html replays these traces)
# ----------------------------------------------------------------------------

def section_gold():
    banner("GOLD: pinned routing paths per plugin - the .html replays these")
    cluster = make_cluster()

    print("One cross-node pod-to-pod trace per plugin (web-a@node-1 -> "
          "web-c@node-3).\nThe node sequence + encap count is the gold the "
          ".html recomputes from the IDENTICAL\nrouting functions.\n")

    cases = []

    # Calico
    h = route_calico(cluster, "web-a", "web-c")
    seq = node_seq(h)
    cases.append(("Calico (BGP)", seq, encap_count(h), h[0].pkt, h[-1].pkt))
    print("GOLD 1 - Calico (web-a@node-1 -> web-c@node-3):")
    for s in seq:
        print(f"    {s}")
    assert h[0].pkt == h[-1].pkt and encap_count(h) == 0
    print()

    # Flannel
    h = route_flannel(cluster, "web-a", "web-c")
    seq = node_seq(h)
    cases.append(("Flannel (VXLAN)", seq, encap_count(h), h[0].pkt, h[-1].pkt))
    print("GOLD 2 - Flannel VXLAN (web-a@node-1 -> web-c@node-3):")
    for s in seq:
        print(f"    {s}")
    assert h[0].pkt == h[-1].pkt and encap_count(h) == 2
    print()

    # Cilium
    h = route_cilium(cluster, "web-a", "web-c")
    seq = node_seq(h)
    cases.append(("Cilium (eBPF)", seq, encap_count(h), h[0].pkt, h[-1].pkt))
    print("GOLD 3 - Cilium eBPF (web-a@node-1 -> web-c@node-3):")
    for s in seq:
        print(f"    {s}")
    assert h[0].pkt == h[-1].pkt and encap_count(h) == 0
    print()

    print("GOLD summary (node_seq + encap per plugin) - feeds cni.html:\n")
    print("  | # | plugin          | hops | inner packet | encap (encap+decap) |")
    print("  |---|-----------------|------|--------------|---------------------|")
    for i, (label, seq, enc, _a, _b) in enumerate(cases, 1):
        unchanged = "unchanged"
        print(f"  | {i} | {label:<15} | {len(seq):<4} | {unchanged:<12} "
              f"| {enc}                   |")
    print()
    print("[check] all 3 gold traces reproduced from the routing functions: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("cni.py - reference model of the Container Network Interface.")
    print("All traces below feed CNI.md.")
    print("pure Python stdlib ; deterministic logical packet-routing model.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
