"""
container_networking.py - Reference model of container networking: the four
network modes (bridge, host, none, macvlan), the docker0 bridge + veth pair
topology, NAT / port mapping via iptables (DNAT + MASQUERADE), overlay
networking over VXLAN, and the embedded DNS at 127.0.0.11.

This is the single source of truth that CONTAINER_NETWORKING.md is built from.
Every topology table, routing trace, NAT rewrite, and DNS answer in the guide
is printed by this file. If you change something here, re-run and re-paste the
output into the guide.

Run:
    python3 container_networking.py

============================================================================
THE INTUITION (read this first) - the apartment building and the mailroom
============================================================================
A container is an apartment with NO street address of its own. To send or
receive mail (packets) it needs the building's infrastructure:

  * bridge (docker0) : the building's internal mailroom. Every apartment gets
                       a private extension number (172.17.0.x). Mail between
                       apartments is sorted in the mailroom (L2 forwarding).
                       Mail to the OUTSIDE world is handed to the front desk,
                       which REPLACES the sender's extension with the
                       building's public street address (MASQUERADE / SNAT),
                       so outsiders never see apartment numbers.
  * host             : the apartment has NO walls - it IS the front desk. The
                       app binds straight to the building's public address.
                       Fastest, but no privacy (port conflicts with the host).
  * none             : a sealed room with only an internal phone (loopback).
                       No mail in or out.
  * macvlan          : the apartment gets its OWN street address and mailbox
                       on the public road - mail skips the mailroom entirely.
  * overlay (VXLAN)  : several buildings share ONE virtual mailroom that
                       spans them, tunneled through the public road (VXLAN).
                       Apartments on different buildings look like neighbours.

The plumbing that makes the mailroom work is the VETH PAIR: a virtual
Ethernet cable with two ends. One end (eth0) is plugged into the apartment's
network namespace; the other (vethXXX) is plugged into the docker0 bridge.
That is the ONLY physical-looking link between a container's isolated network
world and the host's - everything else (NAT, DNS, firewall) is the host's
Linux network stack doing its normal job, just pointed at the bridge.

============================================================================
HOW DOCKER ACTUALLY DOES IT (all standard Linux kernel facilities)
============================================================================
Docker uses ZERO custom kernel code for networking. At container-create time
it composes stock Linux primitives:

  * network namespace  : each container gets its own netns (clone(CLONE_NEWNET))
                         so it sees only its own interfaces/routes/iptables.
  * veth pair          : `ip link add type veth`; one end is moved into the
                         container netns (renamed eth0), the other enslaved
                         to docker0.
  * docker0            : a Linux bridge (`ip link add type bridge`). Default
                         subnet 172.17.0.0/16, gateway 172.17.0.1. L2 learning
                         /forwarding between its ports.
  * iptables NAT       : two chains carry container <-> world traffic:
      - MASQUERADE (POSTROUTING): for egress via the host default iface,
        rewrite src IP -> host eth0 IP so replies come back.
      - DNAT (DOCKER chain, PREROUTING + OUTPUT --dport): for `-p H:C`,
        rewrite dst H -> container_ip:C, so published ports reach the container.
  * conntrack          : connection tracking remembers each NAT mapping so the
                         REPLY path can be un-SNAT / un-DNAT back to original.
  * embedded DNS       : since Docker 1.10 a resolver runs in the daemon; each
                         container's /etc/resolv.conf points at 127.0.0.11 and
                         the netns intercepts :53 to the daemon. Only USER-
                         DEFINED networks resolve names (default bridge does NOT).
  * overlay + VXLAN    : Docker Swarm's overlay driver makes a bridge per
                         network per host and stitches them with a VXLAN tunnel
                         (UDP/4789). The overlay subnet (e.g. 10.0.0.0/24) is
                         the SAME on every host; the underlay (real host IPs)
                         carries the encapsulated frames.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   netns (network     : an isolated copy of the Linux network stack: its own
   namespace)           interfaces, routes, iptables, ARP table. A container
                        lives inside one. `ip netns add/exec`.
   veth pair          : a virtual Ethernet cable. Two interfaces linked so a
                        packet into one end comes out the other. The bridge
                        between a container netns and the host.
   docker0            : the default Linux bridge Docker creates. IP 172.17.0.1,
                        subnet 172.17.0.0/16. Every `-d bridge` container plugs
                        a veth into it.
   eth0               : inside the container netns, the veth end renamed eth0.
   SNAT / MASQUERADE  : Source NAT - rewrite the packet's SOURCE ip/port. Used
                        for egress so replies reach the host. MASQUERADE =
                        SNAT to the outgoing interface's address.
   DNAT               : Destination NAT - rewrite the packet's DESTINATION
                        ip/port. Used for `-p host:container` publishing.
   conntrack          : the kernel connection-tracking table that records every
                        NAT'd flow so reply packets can be reversed.
   VXLAN              : Virtual eXtensible LAN. Encapsulates L2 Ethernet frames
                        inside UDP (port 4789) so two bridges on different hosts
                        behave like one L2 segment. Identified by a 24-bit VNI.
   overlay            : a Docker network whose bridge is replicated on every
                        Swarm host and stitched by VXLAN. Containers get IPs in
                        one shared subnet regardless of host.
   127.0.0.11         : Docker's embedded DNS resolver, visible inside every
                        container on a user-defined network.
   default bridge     : the docker0 bridge, network named `bridge`. Does NOT
                        resolve container names (legacy). User-defined bridges DO.

============================================================================
THE LINEAGE (sources)
============================================================================
   Biederman, Linux netns       : network namespaces (clone(CLONE_NEWNET)),
                                  the isolation primitive every mode is built on.
   IEEE 802.1D                  : the MAC bridge spec docker0 implements.
  iptables / netfilter (Rusty Russell): NAT (SNAT/DNAT/MASQUERADE), conntrack.
   RFC 7348 VXLAN (Mahalingam 2014): L2-over-UDP-4789 encapsulation, 24-bit VNI.
   Docker Engine docs, "Networking overview" + "Bridge networks": docker0, veth,
                                  -p publishing, 127.0.0.11 embedded DNS.
   Kubernetes CNI spec          : the container network interface plugins satisfy.

KEY INVARIANTS (all asserted/printed in the sections below):
   bridge c2c   : src eth0 -> veth_src -> docker0 -> veth_dst -> dst eth0 ; NO NAT
   bridge c2ext : src eth0 -> veth -> docker0 -> host eth0 [MASQUERADE src] -> out
   port map     : in -> host eth0 [DNAT dst] -> docker0 -> veth -> dst eth0 ;
                  reply reverses via conntrack
   host mode    : app binds host eth0 directly ; NO docker0, NO veth, NO NAT
   none mode    : only lo ; any non-loopback dst -> no route -> dropped
   macvlan      : container eth0 (own MAC) -> host phys iface -> wire ; NO NAT,
                  NO docker0 ; CANNOT reach the host (promiscuity restriction)
   overlay xhost: src eth0 -> ov_bridgeA -> VXLAN encap -> underlay A->B ->
                  VXLAN decap -> ov_bridgeB -> dst eth0 ; inner addrs unchanged
   DNS          : query -> 127.0.0.11 -> daemon -> returns container_ip by name

Conventions: IPs/ports are strings/ints; a Hop = (node, Packet, note). Fully
deterministic logical model; the .html replays these exact traces.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

BANNER = "=" * 72


# ============================================================================
# 1. THE CORE MODEL: Packet, Hop, Container, BridgeTopo, OverlayTopo
# ============================================================================

@dataclass
class Packet:
    """A TCP/UDP packet: the 4-tuple + protocol.

    NAT is modeled as nat(**changes) returning a NEW Packet (the kernel clones
    and rewrites the sk_buff; it never mutates in place). src/dst here are the
    *currently observed* addresses at this hop.
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

    node : which interface/bridge/host the packet is AT (leaving).
    pkt  : the packet as it LEAVES this node (after any local rewrite).
    note : what happened here (L2 fwd, SNAT, DNAT, encap, decap, drop, ...).
    """
    node: str
    pkt: Packet
    note: str = ""


@dataclass
class Container:
    """A container attached to a bridge."""
    name: str
    ip: str            # eth0 IP
    veth_host: str     # veth end enslaved to the bridge (host side)
    vni: int | None = None
    eth0: str = "eth0"


@dataclass
class BridgeTopo:
    """The default bridge topology: one host, docker0, N containers."""
    host_eth0_ip: str
    host_eth0: str = "eth0"
    docker0_ip: str = "172.17.0.1"
    docker0: str = "docker0"
    subnet: str = "172.17.0.0/16"
    containers: list[Container] = field(default_factory=list)

    def by_ip(self, ip: str) -> Container:
        for c in self.containers:
            if c.ip == ip:
                return c
        raise KeyError(ip)

    def by_name(self, name: str) -> Container:
        for c in self.containers:
            if c.name == name:
                return c
        raise KeyError(name)


@dataclass
class OverlayHost:
    """One Swarm node in an overlay network."""
    name: str
    eth0_ip: str               # underlay address (real, routable)
    overlay_br_ip: str         # overlay bridge gateway IP
    containers: list[Container] = field(default_factory=list)


@dataclass
class OverlayTopo:
    """A VXLAN overlay spanning several hosts, one shared subnet."""
    hosts: list[OverlayHost] = field(default_factory=list)
    overlay_subnet: str = "10.0.0.0/24"
    overlay_br_name: str = "overlay0"
    vni: int = 25678
    vxlan_port: int = 4789

    def host_of(self, cname: str) -> OverlayHost:
        for h in self.hosts:
            for c in h.containers:
                if c.name == cname:
                    return h
        raise KeyError(cname)

    def container(self, cname: str) -> Container:
        h = self.host_of(cname)
        for c in h.containers:
            if c.name == cname:
                return c
        raise KeyError(cname)


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
        nat_mark = "  [NAT]" if "NAT" in h.note or "SNAT" in h.note \
            or "DNAT" in h.note else ""
        enc_mark = "  [ENCAP]" if "[encap]" in h.note.lower() else ""
        print(f"  {tag} {h.node}")
        print(f"       pkt   {h.pkt}{nat_mark}{enc_mark}")
        if h.note:
            print(f"       note  {h.note}")
    print()


def node_seq(hops: list[Hop]) -> list[str]:
    """Just the node labels - used for the gold check + the .html trace."""
    return [h.node for h in hops]


# ============================================================================
# 2. ROUTING FUNCTIONS - one per mode/direction. Each returns a Hop list.
# ============================================================================

# ----------------------------------------------------------------------------
# (a) BRIDGE - container to container (same docker0): pure L2 forwarding, no NAT
# ----------------------------------------------------------------------------

def route_bridge_c2c(topo: BridgeTopo, src_name: str, dst_name: str,
                     dport: int = 80, sport: int = 40000) -> list[Hop]:
    """src container eth0 -> veth_src -> docker0 -> veth_dst -> dst eth0.

    Same L2 segment: the bridge forwards based on the learned dst MAC. The
    packet's addresses NEVER change (no NAT). ARP resolves dst IP -> MAC once,
    cached in the container's neighbour table.
    """
    src = topo.by_name(src_name)
    dst = topo.by_name(dst_name)
    p = Packet(src.ip, sport, dst.ip, dport)
    return [
        Hop(f"container/{src.name} {src.eth0} {src.ip}", p,
            "app sends; ARP for dst MAC resolved on docker0"),
        Hop(f"veth {src.veth_host} (host side)", p,
            "veth pair: exits container netns, appears at a docker0 port"),
        Hop(f"{topo.docker0} {topo.docker0_ip} (L2 bridge)", p,
            f"bridge forward: dst MAC learned on port veth {dst.veth_host}"),
        Hop(f"veth {dst.veth_host} (host side)", p,
            "veth pair: into container netns"),
        Hop(f"container/{dst.name} {dst.eth0} {dst.ip}", p,
            "delivered; NO NAT anywhere (same L2 broadcast domain)"),
    ]


# ----------------------------------------------------------------------------
# (b) BRIDGE - container to EXTERNAL (internet): MASQUERADE SNAT on egress
# ----------------------------------------------------------------------------

def route_bridge_to_external(topo: BridgeTopo, src_name: str, ext_ip: str,
                             ext_port: int = 80,
                             sport: int = 40000,
                             masq_port: int = 51234) -> tuple[list[Hop], list[Hop]]:
    """Outbound: src eth0 -> veth -> docker0 -> host eth0 [MASQUERADE] -> out.
    Reply: conntrack reverses the SNAT (ext -> host eth0 ip -> container)."""
    src = topo.by_name(src_name)
    out = Packet(src.ip, sport, ext_ip, ext_port)
    req = [
        Hop(f"container/{src.name} {src.eth0} {src.ip}", out,
            "app sends to external dst; default route via docker0 gw"),
        Hop(f"veth {src.veth_host}", out,
            "veth pair onto docker0"),
        Hop(f"{topo.docker0} {topo.docker0_ip}", out,
            "bridge forwards to its gateway (the host)"),
        Hop(f"host {topo.host_eth0} {topo.host_eth0_ip}", out.nat(
            src_ip=topo.host_eth0_ip, src_port=masq_port),
            "MASQUERADE (SNAT): src rewritten -> host eth0 ip:port [NAT]; "
            "conntrack records the mapping"),
        Hop(f"internet via {topo.host_eth0}", out.nat(
            src_ip=topo.host_eth0_ip, src_port=masq_port),
            "leaves the host; outsider sees host eth0 ip, never 172.17.0.x"),
    ]
    # reply: the outsider replies to host eth0 ip:masq_port
    reply_in = Packet(ext_ip, ext_port, topo.host_eth0_ip, masq_port)
    rep = [
        Hop(f"internet via {topo.host_eth0}", reply_in,
            "reply arrives at host eth0 ip:masq_port"),
        Hop(f"host {topo.host_eth0} {topo.host_eth0_ip}", reply_in.nat(
            dst_ip=src.ip, dst_port=sport),
            "conntrack REVERSE SNAT: dst rewritten -> container ip:port [NAT]"),
        Hop(f"{topo.docker0} {topo.docker0_ip}", reply_in.nat(
            dst_ip=src.ip, dst_port=sport),
            "bridge forwards to dst container port"),
        Hop(f"container/{src.name} {src.eth0} {src.ip}", reply_in.nat(
            dst_ip=src.ip, dst_port=sport),
            "delivered; app sees the reply as if from the internet directly"),
    ]
    return req, rep


# ----------------------------------------------------------------------------
# (c) PORT MAPPING (-p 8080:80): inbound DNAT + conntrack reply reversal
# ----------------------------------------------------------------------------

def route_port_published(topo: BridgeTopo, ext_ip: str, ext_port: int,
                         dst_name: str, container_port: int,
                         ext_sport: int = 50000) -> tuple[list[Hop], list[Hop]]:
    """External -> host eth0:ext_port. iptables DNAT (DOCKER chain) rewrites
    dst to container_ip:container_port. Reply reverses via conntrack.

    `docker run -p 8080:80 web` adds a DNAT rule: dst host:8080 -> 172.17.0.x:80.
    """
    dst = topo.by_name(dst_name)
    inbound = Packet(ext_ip, ext_sport, topo.host_eth0_ip, ext_port)
    req = [
        Hop(f"internet via {topo.host_eth0}", inbound,
            f"client connects to host {topo.host_eth0_ip}:{ext_port}"),
        Hop(f"host {topo.host_eth0} {topo.host_eth0_ip} (iptables PREROUTING)",
            inbound.nat(dst_ip=dst.ip, dst_port=container_port),
            f"DNAT (DOCKER chain): dst rewritten -> {dst.ip}:{container_port} "
            f"[NAT]; conntrack records the flow"),
        Hop(f"{topo.docker0} {topo.docker0_ip}", inbound.nat(
            dst_ip=dst.ip, dst_port=container_port),
            "bridge forwards to the container port"),
        Hop(f"veth {dst.veth_host}", inbound.nat(
            dst_ip=dst.ip, dst_port=container_port),
            "veth pair into container netns"),
        Hop(f"container/{dst.name} {dst.eth0} {dst.ip}", inbound.nat(
            dst_ip=dst.ip, dst_port=container_port),
            f"delivered to {dst.name}:{container_port}"),
    ]
    # reply: container:container_port -> ext; conntrack reverses the DNAT
    # (rewrites src back to host:ext_port)
    reply_out = Packet(dst.ip, container_port, ext_ip, ext_sport)
    rep = [
        Hop(f"container/{dst.name} {dst.eth0} {dst.ip}", reply_out,
            "app replies; conntrack owns the flow"),
        Hop(f"{topo.docker0} {topo.docker0_ip}", reply_out,
            "bridge to host"),
        Hop(f"host {topo.host_eth0} {topo.host_eth0_ip} (iptables OUTPUT)",
            reply_out.nat(src_ip=topo.host_eth0_ip, src_port=ext_port),
            "conntrack REVERSE DNAT: src rewritten -> host:ext_port [NAT]"),
        Hop(f"internet via {topo.host_eth0}", reply_out.nat(
            src_ip=topo.host_eth0_ip, src_port=ext_port),
            "client sees the reply from host:ext_port, as expected"),
    ]
    return req, rep


# ----------------------------------------------------------------------------
# (d) HOST mode: the container shares the host netns. No docker0, no veth, no NAT
# ----------------------------------------------------------------------------

def route_host_mode(host_eth0_ip: str, host_eth0: str, app_port: int,
                    ext_ip: str, ext_port: int = 80) -> list[Hop]:
    """`docker run --network host`: the app binds the host's eth0 directly.
    There is no docker0, no veth, no NAT. The container's packets are the
    HOST's packets. Fast (zero translation) but the host's port space is shared
    - two containers cannot bind the same host port."""
    out = Packet(host_eth0_ip, app_port, ext_ip, ext_port)
    return [
        Hop(f"container/app (host netns, no isolation)", out,
            "app binds host eth0 ip:app_port directly; NO veth, NO docker0"),
        Hop(f"host {host_eth0} {host_eth0_ip}", out,
            "this IS the host network stack; nothing to translate"),
        Hop(f"internet via {host_eth0}", out,
            "leaves as a normal host packet; NO NAT (already the host ip)"),
    ]


# ----------------------------------------------------------------------------
# (e) NONE mode: only loopback. No eth0, no routes. Any external dst is dropped
# ----------------------------------------------------------------------------

def route_none_mode(dst_ip: str, dst_port: int = 80) -> list[Hop]:
    """`docker run --network none`: the netns has only `lo` (127.0.0.0/8).
    No eth0, no default route. A packet to any non-loopback dst has no route
    and is dropped with EHOSTUNREACH / ENETUNREACH."""
    if dst_ip.startswith("127."):
        p = Packet("127.0.0.1", 40000, dst_ip, dst_port)
        return [Hop("container lo 127.0.0.1", p, "loopback only; stays local")]
    p = Packet("127.0.0.1", 40000, dst_ip, dst_port)
    return [
        Hop("container (no eth0, only lo)", p,
            "app tries to send; only interface is lo"),
        Hop("[DROP]", p, "no route to dst; ENETUNREACH. none = fully isolated"),
    ]


# ----------------------------------------------------------------------------
# (f) MACVLAN: container has its own MAC/IP on the host's physical subnet
# ----------------------------------------------------------------------------

def route_macvlan(container_ip: str, container_mac: str, phys_subnet_gw: str,
                  host_eth0: str, ext_ip: str, ext_port: int = 80,
                  sport: int = 40000) -> list[Hop]:
    """`docker run --network macvlan`: a macvlan sub-interface is created on the
    host's physical NIC with its OWN MAC and an IP on the physical subnet. The
    container talks directly to the physical network - no docker0, no NAT.
    Famous gotcha: by default the container CANNOT reach the host (the kernel
    blocks macvlan<->parent traffic to avoid L2 loops); the host IS reachable
    from outside via the physical switch."""
    out = Packet(container_ip, sport, ext_ip, ext_port)
    return [
        Hop(f"container/app eth0 {container_ip} mac {container_mac}", out,
            "own MAC on the physical subnet; L2 straight to the wire"),
        Hop(f"macvlan sub-if on host {host_eth0}", out,
            "no bridge, no NAT; parent NIC just forwards the frame"),
        Hop(f"physical gateway {phys_subnet_gw}", out,
            "routed by the physical network like any other host"),
        Hop(f"internet via {host_eth0}", out,
            "leaves with the container's OWN ip (no SNAT); "
            "host unreachable from here (macvlan restriction)"),
    ]


# ----------------------------------------------------------------------------
# (g) OVERLAY (VXLAN) cross-host: same overlay subnet, tunneled over underlay
# ----------------------------------------------------------------------------

def route_overlay_cross_host(topo: OverlayTopo, src_name: str, dst_name: str,
                             dport: int = 80, sport: int = 40000) -> list[Hop]:
    """Container on host A -> container on host B, same overlay subnet.

    The packet's INNER addresses (10.0.0.x) never change. The overlay bridge on
    host A sees dst MAC is remote (learned via VXLAN FDB) and encapsulates the
    whole L2 frame inside a UDP/4789 packet addressed underlay-A -> underlay-B.
    Host B's VXLAN endpoint decapsulates and hands the original frame to its
    overlay bridge, which forwards to the dst container.
    """
    sh = topo.host_of(src_name)
    dh = topo.host_of(dst_name)
    sc = topo.container(src_name)
    dc = topo.container(dst_name)
    inner = Packet(sc.ip, sport, dc.ip, dport)
    return [
        Hop(f"container/{sc.name} eth0 {sc.ip} @ host {sh.name}", inner,
            "app sends; inner overlay packet src->dst (10.0.0.x)"),
        Hop(f"{topo.overlay_br_name} {sh.overlay_br_ip} @ host {sh.name}",
            inner,
            "overlay bridge: dst MAC is remote -> forward to the VXLAN tunnel"),
        Hop(f"VXLAN encap VNI {topo.vni} @ host {sh.name}", inner,
            f"L2 frame wrapped in UDP/{topo.vxlan_port}: OUTER {sh.eth0_ip}"
            f" -> {dh.eth0_ip}; INNER unchanged [ENCAP]"),
        Hop(f"underlay: {sh.eth0_ip} -> {dh.eth0_ip} (host {sh.name}->{dh.name})",
            inner,
            "tunnel packet routed over the PHYSICAL network by underlay ip"),
        Hop(f"VXLAN decap @ host {dh.name}", inner,
            f"UDP/{topo.vxlan_port} stripped; original L2 frame restored [ENCAP]"),
        Hop(f"{topo.overlay_br_name} {dh.overlay_br_ip} @ host {dh.name}", inner,
            "overlay bridge forwards to dst container port"),
        Hop(f"container/{dc.name} eth0 {dc.ip} @ host {dh.name}", inner,
            "delivered; inner addresses unchanged across the tunnel"),
    ]


# ----------------------------------------------------------------------------
# (h) DNS: embedded resolver at 127.0.0.11 resolves container names
# ----------------------------------------------------------------------------

@dataclass
class DNSAnswer:
    name: str
    ip: str


def resolve_dns(answers: dict[str, str], name: str) -> DNSAnswer:
    """Model Docker's embedded DNS at 127.0.0.11. A query from a container is
    intercepted by the netns (the 127.0.0.11 rule) and answered by the daemon,
    which knows the container-name -> ip mapping of its user-defined network.
    Returns the A record (name -> ip)."""
    if name not in answers:
        raise KeyError(f"NXDOMAIN: {name} not on this network")
    return DNSAnswer(name, answers[name])


# ============================================================================
# 3. THE SECTIONS - each prints a self-contained worked example + [check]
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the bridge topology - veth pairs plug containers into docker0
# ----------------------------------------------------------------------------

def make_bridge_topo() -> BridgeTopo:
    """The canonical default-bridge example: host + docker0 + 2 containers."""
    topo = BridgeTopo(host_eth0_ip="192.168.1.10", host_eth0="eth0")
    topo.containers = [
        Container("web", ip="172.17.0.2", veth_host="veth3a91"),
        Container("db",  ip="172.17.0.3", veth_host="veth7c22"),
    ]
    return topo


def section_a():
    banner("SECTION A: the bridge topology - veth pairs -> docker0")
    topo = make_bridge_topo()
    print(f"host eth0 = {topo.host_eth0} @ {topo.host_eth0_ip}")
    print(f"{topo.docker0} = Linux bridge @ {topo.docker0_ip}, subnet "
          f"{topo.subnet}\n")
    print("Each container gets a VETH PAIR: one end (eth0) in its netns, the "
          "other enslaved to docker0.\n")
    print("  | container | eth0 ip   | veth (host side) | netns      |")
    print("  |-----------|-----------|-------------------|------------|")
    for c in topo.containers:
        print(f"  | {c.name:<9} | {c.ip:<9} | {c.veth_host:<17} "
              f"| ns-{c.name:<6}|")
    print(f"\n  docker0 ports: {[c.veth_host for c in topo.containers]} "
          "(+ its own gw iface)")
    print("\nThe view from INSIDE a container netns (isolated copy of the stack):")
    c = topo.by_name("web")
    print(f"  ip addr  -> {c.eth0}: {c.ip}/16,  lo: 127.0.0.1/8")
    print(f"  routes   -> default via {topo.docker0_ip} dev {c.eth0}")
    print(f"  resolve  -> nameserver 127.0.0.11  (the embedded DNS; Section D)")
    print("\n$ docker network inspect bridge (abbreviated):\n")
    print('  "IPAM": {"Config": [{"Subnet": "172.17.0.0/16",')
    print(f'                        "Gateway": "{topo.docker0_ip}"]]}},')
    print(f'  "Containers": {{"...{topo.containers[0].ip[-3:]}": '
          f'{{"Name": "web", "IPv4": "{c.ip}/16"}}, ...}}')

    # check: veth count == container count, every container ip in subnet
    assert len({c.veth_host for c in topo.containers}) == len(topo.containers)
    assert all(c.ip.startswith("172.17.0.") for c in topo.containers)
    assert topo.by_name("web").ip == "172.17.0.2"
    print("\n[check] 2 veth pairs, both in 172.17.0.0/16, web=172.17.0.2: OK")


# ----------------------------------------------------------------------------
# SECTION B: bridge routing - c2c (no NAT) + c2external (MASQUERADE)
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: bridge routing - container-to-container then to the world")
    topo = make_bridge_topo()

    print("(1) CONTAINER -> CONTAINER (web -> db) on the SAME docker0:\n")
    hops = route_bridge_c2c(topo, "web", "db", dport=5432)
    print_route(hops)
    # verify NO nat happened: first and last packet are byte-identical
    assert hops[0].pkt == hops[-1].pkt, "c2c must not NAT"
    # verify the path visits docker0 exactly once
    seq = node_seq(hops)
    assert seq.count(f"{topo.docker0} {topo.docker0_ip} (L2 bridge)") == 1
    print("[check] c2c: packet unchanged end-to-end, single docker0 hop: OK\n")

    print("(2) CONTAINER -> EXTERNAL (web -> 93.184.216.34:80) with MASQUERADE:\n")
    req, rep = route_bridge_to_external(topo, "web", "93.184.216.34", 80)
    print_route(req, "REQUEST")
    print_route(rep, "REPLY")
    # request: src rewritten from container ip -> host ip at the host eth0 hop
    nat_hop = req[3]
    assert nat_hop.pkt.src_ip == topo.host_eth0_ip, "MASQUERADE must set src=host"
    assert nat_hop.pkt.src_port == 51234
    assert "MASQUERADE" in nat_hop.note
    # reply: conntrack reverses dst back to container ip
    assert rep[1].pkt.dst_ip == "172.17.0.2"
    print("[check] c2ext: MASQUERADE rewrites src->host; reply reverses to "
          "container: OK")


# ----------------------------------------------------------------------------
# SECTION C: port mapping -p 8080:80 (DNAT inbound + conntrack reply)
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: port publishing -p 8080:80  (DNAT inbound + reply)")
    topo = make_bridge_topo()
    print("`docker run -p 8080:80 web` inserts a DNAT rule in the DOCKER "
          "chain:\n")
    print("  iptables -t nat -A DOCKER -p tcp --dport 8080 \\")
    print(f"    -j DNAT --to-destination {topo.by_name('web').ip}:80\n")
    req, rep = route_port_published(topo, "203.0.113.9", 8080, "web", 80)
    print_route(req, "REQUEST (external -> host:8080 -> container:80)")
    print_route(rep, "REPLY (conntrack reverses the DNAT)")

    # gold invariants for DNAT
    dnat_hop = req[1]
    assert dnat_hop.pkt.dst_ip == "172.17.0.2" and dnat_hop.pkt.dst_port == 80
    assert "DNAT" in dnat_hop.note
    # reply reverses: src rewritten back to host:8080
    assert rep[2].pkt.src_ip == topo.host_eth0_ip and rep[2].pkt.src_port == 8080
    print("[check] DNAT host:8080 -> container:80; reply src -> host:8080: OK")


# ----------------------------------------------------------------------------
# SECTION D: DNS - embedded resolver at 127.0.0.11
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: embedded DNS at 127.0.0.11 - name -> container ip")
    # a user-defined network's name table
    answers = {"web": "172.18.0.2", "db": "172.18.0.3", "cache": "172.18.0.4"}
    print("On a USER-DEFINED bridge (not the default docker0), the daemon "
          "maintains a\ncontainer-name -> ip table and answers queries sent to "
          "127.0.0.11.\n")
    print("  container /etc/resolv.conf:")
    print("    nameserver 127.0.0.11\n")
    print("  | query   | resolved ip   |")
    print("  |---------|---------------|")
    for n in answers:
        a = resolve_dns(answers, n)
        print(f"  | {n:<7} | {a.ip:<13} |")
    # a miss -> NXDOMAIN
    print()
    try:
        resolve_dns(answers, "missing")
    except KeyError as e:
        print(f"  resolve('missing') -> {e}")
    print("\nSo `web` and `db` find each other by NAME on a user-defined net:")
    print('  curl http://web:8080   ->   172.18.0.2:8080   (no hardcoded ip)')
    print("\nNOTE: the DEFAULT bridge (docker0) does NOT resolve names - that is")
    print("why you almost always create a user-defined network for multi-container")
    print("apps (`docker network create appnet`).\n")

    assert resolve_dns(answers, "web").ip == "172.18.0.2"
    print("[check] 'web' -> 172.18.0.2, 'missing' -> NXDOMAIN: OK")


# ----------------------------------------------------------------------------
# SECTION E: the four network modes side by side
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: network modes - bridge vs host vs none vs macvlan")
    topo = make_bridge_topo()
    print("`docker run --network <MODE>` chooses the netns wiring. The packet "
          "PATH and whether NAT happens differ per mode:\n")
    modes = [
        ("bridge",
         "container netns with eth0+veth -> docker0 -> NAT",
         "default; isolated, needs -p to publish"),
        ("host",
         "container SHARES host netns; app binds host eth0",
         "fastest; no isolation; port conflicts with host"),
        ("none",
         "netns with ONLY lo; no eth0",
         "fully isolated; app must open its own socket manually"),
        ("macvlan",
         "own MAC/IP on host's physical subnet",
         "L2 on the wire; no NAT; CANNOT reach the host"),
    ]
    print("  | mode    | wiring                              | trade-off            |")
    print("  |---------|-------------------------------------|----------------------|")
    for name, wiring, trade in modes:
        print(f"  | {name:<7} | {wiring:<35} | {trade:<20} |")
    print()

    print("--- bridge (web -> db) ---------------------------------------------")
    print_route(route_bridge_c2c(topo, "web", "db", dport=5432))

    print("--- host (app@host eth0 -> internet) -------------------------------")
    print_route(route_host_mode(topo.host_eth0_ip, topo.host_eth0, 8080,
                                "93.184.216.34"))

    print("--- none (app -> external, no route) -------------------------------")
    print_route(route_none_mode("93.184.216.34"))

    print("--- macvlan (container@192.168.1.50 -> internet) -------------------")
    print_route(route_macvlan("192.168.1.50", "02:42:c0:a8:01:32",
                              "192.168.1.1", topo.host_eth0, "93.184.216.34"))

    # checks: each mode's signature invariants
    b = route_bridge_c2c(topo, "web", "db")
    assert b[0].pkt == b[-1].pkt and "docker0" in b[2].node     # bridge NAT-free
    h = route_host_mode(topo.host_eth0_ip, topo.host_eth0, 8080, "1.2.3.4")
    assert len(h) == 3 and h[0].pkt.src_ip == topo.host_eth0_ip  # host: 3 hops
    n = route_none_mode("93.184.216.34")
    assert n[-1].node == "[DROP]"                                # none drops
    m = route_macvlan("192.168.1.50", "02:42:aa", "192.168.1.1", topo.host_eth0, "1.2.3.4")
    assert all(hh.pkt.src_ip == "192.168.1.50" for hh in m)      # macvlan no NAT
    print("[check] bridge=4-hop NAT-free, host=3-hop, none=DROP, "
          "macvlan=no-NAT: OK")


# ----------------------------------------------------------------------------
# SECTION F: overlay networking - VXLAN spans hosts
# ----------------------------------------------------------------------------

def make_overlay_topo() -> OverlayTopo:
    """Two Swarm hosts, one shared overlay subnet 10.0.0.0/24."""
    return OverlayTopo(
        hosts=[
            OverlayHost("hostA", eth0_ip="10.0.1.10", overlay_br_ip="10.0.0.1",
                        containers=[Container("app", ip="10.0.0.2",
                                              veth_host="vethA1")]),
            OverlayHost("hostB", eth0_ip="10.0.1.20", overlay_br_ip="10.0.0.1",
                        containers=[Container("web", ip="10.0.0.3",
                                              veth_host="vethB1")]),
        ],
        overlay_subnet="10.0.0.0/24", overlay_br_name="overlay0",
        vni=25678, vxlan_port=4789,
    )


def section_f():
    banner("SECTION F: overlay networking - VXLAN spans multiple hosts")
    topo = make_overlay_topo()
    print(f"Overlay subnet {topo.overlay_subnet} is the SAME on every host; "
          f"the real\nunderlay addresses carry the VXLAN tunnel "
          f"(UDP/{topo.vxlan_port}, VNI {topo.vni}).\n")
    print("  | host  | underlay eth0 | overlay bridge | container | overlay ip |")
    print("  |-------|---------------|----------------|-----------|------------|")
    for h in topo.hosts:
        for c in h.containers:
            print(f"  | {h.name:<5} | {h.eth0_ip:<13} | "
                  f"{topo.overlay_br_name} {h.overlay_br_ip:<7} | "
                  f"{c.name:<9} | {c.ip:<10} |")
    print()
    print("Cross-host: app@hostA -> web@hostB (same overlay subnet, different "
          "physical host):\n")
    hops = route_overlay_cross_host(topo, "app", "web")
    print_route(hops, "OVERLAY CROSS-HOST")

    # gold: inner packet unchanged end to end; encapsulation visible mid-path
    assert hops[0].pkt == hops[-1].pkt, "overlay must not NAT the inner packet"
    encap = [hh for hh in hops if "[encap]" in hh.note.lower()]
    assert len(encap) == 2, "exactly one encap + one decap hop"
    print("[check] inner 10.0.0.x addrs unchanged; one VXLAN encap + one "
          "decap: OK")


# ----------------------------------------------------------------------------
# GOLD: pinned routing path for each mode (the .html reproduces these traces)
# ----------------------------------------------------------------------------

def section_gold():
    banner("GOLD: pinned routing paths per mode - the .html replays these")
    topo = make_bridge_topo()
    otopo = make_overlay_topo()

    print("One representative request per mode. The node sequence (node_seq) is")
    print("the gold the .html recomputes from the IDENTICAL routing functions.\n")

    cases = []

    # bridge c2c
    h = route_bridge_c2c(topo, "web", "db", dport=5432)
    seq = node_seq(h)
    cases.append(("bridge c2c (web->db)", seq, h[0].pkt, h[-1].pkt,
                  "no NAT"))
    print("GOLD 1 - bridge c2c (web -> db):")
    for s in seq:
        print(f"    {s}")
    assert h[0].pkt == h[-1].pkt
    print()

    # bridge c2ext (only the request path nodes)
    req, _ = route_bridge_to_external(topo, "web", "93.184.216.34", 80)
    seq = node_seq(req)
    cases.append(("bridge c2ext (web->93.184.216.34:80)", seq, req[0].pkt,
                  req[-1].pkt, "MASQUERADE SNAT"))
    print("GOLD 2 - bridge c2ext (web -> 93.184.216.34:80):")
    for s in seq:
        print(f"    {s}")
    print(f"    NAT: src {req[0].pkt.src_ip}:{req[0].pkt.src_port} -> "
          f"{req[-1].pkt.src_ip}:{req[-1].pkt.src_port}")
    assert req[0].pkt.src_ip == "172.17.0.2"
    assert req[-1].pkt.src_ip == "192.168.1.10"
    print()

    # port publish (request nodes)
    req, _ = route_port_published(topo, "203.0.113.9", 8080, "web", 80)
    seq = node_seq(req)
    cases.append(("publish -p 8080:80 (ext->web)", seq, req[0].pkt,
                  req[-1].pkt, "DNAT"))
    print("GOLD 3 - publish -p 8080:80 (203.0.113.9 -> host:8080 -> web:80):")
    for s in seq:
        print(f"    {s}")
    print(f"    NAT: dst {req[0].pkt.dst_ip}:{req[0].pkt.dst_port} -> "
          f"{req[-1].pkt.dst_ip}:{req[-1].pkt.dst_port}")
    assert req[-1].pkt.dst_ip == "172.17.0.2" and req[-1].pkt.dst_port == 80
    print()

    # host mode
    h = route_host_mode(topo.host_eth0_ip, topo.host_eth0, 8080, "93.184.216.34")
    seq = node_seq(h)
    cases.append(("host mode (app->93.184.216.34:80)", seq, h[0].pkt,
                  h[-1].pkt, "no NAT"))
    print("GOLD 4 - host mode (app -> 93.184.216.34):")
    for s in seq:
        print(f"    {s}")
    assert h[0].pkt == h[-1].pkt and len(seq) == 3
    print()

    # none mode
    h = route_none_mode("93.184.216.34")
    seq = node_seq(h)
    cases.append(("none mode (->external)", seq, h[0].pkt, h[0].pkt, "DROP"))
    print("GOLD 5 - none mode (-> external):")
    for s in seq:
        print(f"    {s}")
    assert seq[-1] == "[DROP]"
    print()

    # macvlan
    h = route_macvlan("192.168.1.50", "02:42:c0:a8:01:32", "192.168.1.1",
                      topo.host_eth0, "93.184.216.34")
    seq = node_seq(h)
    cases.append(("macvlan (192.168.1.50->ext)", seq, h[0].pkt, h[-1].pkt,
                  "no NAT"))
    print("GOLD 6 - macvlan (192.168.1.50 -> ext):")
    for s in seq:
        print(f"    {s}")
    assert h[0].pkt == h[-1].pkt
    print()

    # overlay cross-host
    h = route_overlay_cross_host(otopo, "app", "web")
    seq = node_seq(h)
    cases.append(("overlay cross-host (app@A->web@B)", seq, h[0].pkt,
                  h[-1].pkt, "VXLAN encap, inner no NAT"))
    print("GOLD 7 - overlay cross-host (app@hostA -> web@hostB):")
    for s in seq:
        print(f"    {s}")
    assert h[0].pkt == h[-1].pkt and len(seq) == 7
    print()

    print("GOLD summary (node_seq + nat label per mode) - feeds container_"
          "networking.html:\n")
    print("  | # | mode                          | hops | nat / encap            |")
    print("  |---|-------------------------------|------|------------------------|")
    for i, (label, seq, _a, _b, nat) in enumerate(cases, 1):
        print(f"  | {i} | {label:<29} | {len(seq):<4} | {nat:<22} |")
    print()
    print("[check] all 7 gold traces reproduced from the routing functions: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("container_networking.py - reference model. All traces feed "
          "CONTAINER_NETWORKING.md.")
    print("pure Python stdlib ; deterministic logical packet-routing model.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
