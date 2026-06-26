"""
namespaces.py - Reference model of Linux namespaces, the isolation primitive
behind every container (Docker, Podman, containerd, Kubernetes).

This is the single source of truth that NAMESPACES.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python namespaces.py

==========================================================================
THE INTUITION (read this first) -- the hotel with the magic rooms
==========================================================================
A computer without namespaces has ONE shared reality: every process sees the
same PID list, the same network cards, the same hostname, the same files. That
is like one big open-plan office -- anyone can read anyone's mail.

A namespace is a **per-process pair of glasses**. Put on a different pair and
the world looks different: you see a different PID 1, a different set of
network interfaces, a different hostname. The host (the kernel) still sees the
TRUE, combined picture; each process only sees its own filtered view.

  * A container = a process that has put on SIX different pairs of glasses
    at once (PID, NET, MNT, UTS, IPC, USER). From inside, it looks like a
    fresh machine. From outside (on the host), it is just process 12345.
  * The trick is that nothing is actually COPIED. The kernel keeps ONE table
    and hands each process a filtered LOOK at it. That is why namespaces are
    cheap (a few struct nsproxy pointers per task) vs a VM (a whole second
    kernel).

THE REASON NAMESPACES EXIST: isolation WITHOUT virtualization. You get a
process that BELIEVES it is alone on the machine, while the host keeps one
kernel, one scheduler, one page cache. That belief is what lets you run 200
tenants on one box safely.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  namespace    : a "pair of glasses" -- a filtered view of ONE kernel resource
                 type. Identified by an inode number in /proc/<pid>/ns/.
  nsproxy      : the per-process holder of its 6 current namespaces. Two
                 processes in the "same" namespace share the SAME inode.
  PID ns       : process-id glasses. Inside, the first process renumbers to 1
                 ("init"). The host still calls it 12345.
  NET ns       : network glasses. Own loopback, own eth0, own IP, own routing
                 table, own iptables.
  MNT ns       : mount-point glasses. Own / tree, own overlayfs mounts. What is
                 mounted in a container does not appear in the host's mount tab.
  UTS ns       : hostname glasses. Own hostname + domainname (uname -n).
  IPC ns       : glasses over SysV IPC + POSIX message queues + shared memory.
  USER ns      : uid glasses. UID 0 ("root") inside can map to UID 100000 out-
                 side -- this is the basis of "rootless" containers.
  unshare(2)   : the syscall that takes off your current glasses and puts on a
                 fresh pair for the listed types (CLONE_NEWPID | CLONE_NEWNET | ...).
  clone(2)     : fork + unshare in one step -- create a child that is ALREADY
                 wearing new glasses. This is how runc/containerd spawn a container.

==========================================================================
THE LINEAGE (where it came from)
==========================================================================
  Namespaces entered mainline Linux piecemeal over a decade:
    Mount  (2002, 2.4.19)  : the first. Chroot++, really.
    UTS    (2006, 2.6.19)  : hostname isolation.
    IPC    (2006, 2.6.19)  : SysV message queues / semaphores / shm.
    PID    (2008, 2.6.24)  : the famous one -- process renumbering.
    NET    (2009, 2.6.29)  : Al Viro's network stack isolation; gives containers
                              their own loopback + veth peer.
    USER   (2013, 3.8)     : uid/gid mapping -- the last piece; enables rootless.
    cgroup (2016, 4.6)     : cgroup namespace (bonus 7th, not in the classic 6).

  The composite -- a process wearing all of MNT+UTS+IPC+PID+NET+USER -- is what
  Eric Biederman's work and the LXC project shipped, and what Docker (2013)
  and runc wrapped into a friendly CLI. The OCI runtime spec
  (https://github.com/opencontainers/runc) lists these exact 6 as the
  "linux.namespaces" array in config.json.

KEY PROPERTIES (verified in code, Section F):
    container PID 1  !=  host PID 1         (PID isolation, Section B)
    container eth0   !=  host eth0          (NET isolation, Section C)
    container /etc   !=  host /etc          (MNT isolation, Section D)
    container uid 0  ==  host uid 100000    (USER mapping, Section E)
    isolation        :  for every ns type, ns(container) != ns(host)
                       -> the gold check of this whole guide.

Conventions for inode numbers (used throughout, mirroring a real kernel):
    ns inode pool starts at 0xF0000000 and counts up. The host's initial
    namespaces get the high inodes (e.g. 0xEFFFFFFF), matching the fact that
    /proc/1/ns/* on a real box shows large numbers like 4026531836.
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field

BANNER = "=" * 72

# --------------------------------------------------------------------------
# 0. THE KERNEL MODEL  (a tiny, deterministic stand-in for the real one)
# --------------------------------------------------------------------------
# Every real namespace is identified by a kernel inode number. We mimic that:
# the host's initial namespaces get big inodes, freshly-unshared ones get
# smaller ones counting down from 0xF0000000 -- so you can tell at a glance
# which namespaces are "shared with host" vs "container-private".

NS_TYPES = ("pid", "net", "mnt", "uts", "ipc", "user")  # the classic six

# Host's initial namespaces -- big inodes, like real /proc/1/ns/* (40265318xx).
HOST_NS = {
    "pid": 0xEFFFFFF9,
    "net": 0xEFFFFFFA,
    "mnt": 0xEFFFFFFB,
    "uts": 0xEFFFFFFC,
    "ipc": 0xEFFFFFFD,
    "user": 0xEFFFFFFE,
}

# A monotonic counter for freshly-unshared namespaces (counts DOWN from a high
# base, so container-private inodes look numerically distinct from host ones).
_next_inode = 0xF0000000


def fresh_inode() -> int:
    """Allocate a brand-new namespace inode (mimics kernel ns id allocation)."""
    global _next_inode
    v = _next_inode
    _next_inode += 1
    return v


@dataclass
class Namespace:
    """One namespace instance. inode == identity (two tasks in the same ns
    share the same inode, exactly like /proc/<pid>/ns/<type> symlinks)."""
    type: str
    inode: int
    # type-specific payload
    hostname: str = ""           # UTS
    uid_map: list[tuple[int, int, int]] = field(default_factory=list)  # USER
    net_ifaces: dict = field(default_factory=dict)   # NET: name -> (ip, mask)
    net_routes: list = field(default_factory=list)   # NET: list of (dst, via, dev)
    mounts: list = field(default_factory=list)       # MNT: list of (source, target, fstype)


@dataclass
class Task:
    """A process. `pid` is the GLOBAL pid (what the host sees). `ns` is the
    nsproxy: a dict ns_type -> Namespace. `name` is the comm string."""
    pid: int
    name: str
    ns: dict
    # PID-namespace-local numbering: { pid_ns_inode -> local_pid }
    local_pid: dict = field(default_factory=dict)


@dataclass
class Kernel:
    """The single source of truth -- the host's combined picture. All
    processes live here; each carries its own nsproxy (glasses)."""
    tasks: list = field(default_factory=list)
    namespaces: dict = field(default_factory=dict)  # inode -> Namespace
    next_pid: int = 1

    def add_namespace(self, ns: Namespace) -> Namespace:
        self.namespaces[ns.inode] = ns
        return ns

    def spawn(self, name: str, ns: dict) -> Task:
        t = Task(pid=self.next_pid, name=name, ns=dict(ns), local_pid={})
        self.next_pid += 1
        self.tasks.append(t)
        return t


# Build the host's initial namespaces + the kernel.
def build_kernel(seed: int = 7) -> Kernel:
    """Construct the ground-truth host: init (PID 1), an sshd, and the host's
    own 6 namespaces. Deterministic given `seed`."""
    random.seed(seed)  # only used for cosmetic IP/host assignment; reproducible
    k = Kernel()
    host_ns = {}
    for t in NS_TYPES:
        ns = Namespace(type=t, inode=HOST_NS[t])
        host_ns[t] = ns
        k.add_namespace(ns)
    # host UTS
    host_ns["uts"].hostname = "host-01.dc1"
    # host NET: lo + eth0
    host_ns["net"].net_ifaces = {"lo": ("127.0.0.1", 8), "eth0": ("10.0.0.5", 24)}
    host_ns["net"].net_routes = [
        ("default", "10.0.0.1", "eth0"),
        ("10.0.0.0/24", None, "eth0"),
    ]
    # host MNT: a couple of real mounts
    host_ns["mnt"].mounts = [
        ("/dev/sda1", "/", "ext4"),
        ("proc", "/proc", "proc"),
        ("tmpfs", "/run", "tmpfs"),
    ]
    # host USER: identity map (uid 0 inside == uid 0 outside)
    host_ns["user"].uid_map = [(0, 0, 65536)]
    # init + sshd, both wearing HOST namespaces
    init = k.spawn("systemd", host_ns)
    init.local_pid[HOST_NS["pid"]] = 1
    sshd = k.spawn("sshd", host_ns)
    sshd.local_pid[HOST_NS["pid"]] = sshd.pid
    return k


# --------------------------------------------------------------------------
# unshare / clone: create a fresh set of namespaces for a container
# --------------------------------------------------------------------------
CLONE_NEWNS = 0x00020000   # MNT
CLONE_NEWUTS = 0x04000000  # UTS
CLONE_NEWIPC = 0x08000000  # IPC
CLONE_NEWPID = 0x20000000  # PID
CLONE_NEWNET = 0x40000000  # NET
CLONE_NEWUSER = 0x10000000  # USER
ALL_SIX = CLONE_NEWNS | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWPID | CLONE_NEWNET | CLONE_NEWUSER


def clone_new_container(k: Kernel, flags: int = ALL_SIX, *, cid: str = "c1") -> tuple[dict, Namespace]:
    """clone(2) with the namespace flags -- the syscall runc uses to birth a
    container. Returns a fresh nsproxy (dict ns_type -> Namespace) for the
    child. We also stash the NET/MNT/UTS/USER payload a real runc would set up.

    flags bit pattern (hex) is exactly the kernel's, so the demo in Section F
    reads like a real clone(2) call.
    """
    child_ns: dict = {}
    want = {
        "mnt": bool(flags & CLONE_NEWNS),
        "uts": bool(flags & CLONE_NEWUTS),
        "ipc": bool(flags & CLONE_NEWIPC),
        "pid": bool(flags & CLONE_NEWPID),
        "net": bool(flags & CLONE_NEWNET),
        "user": bool(flags & CLONE_NEWUSER),
    }
    for t in NS_TYPES:
        if want[t]:
            ns = Namespace(type=t, inode=fresh_inode())
            child_ns[t] = ns
            k.add_namespace(ns)
        else:
            # NOT requested: child inherits the host's namespace for this type
            child_ns[t] = k.namespaces[HOST_NS[t]]
    # container UTS
    child_ns["uts"].hostname = f"{cid}.containers.internal"
    # container NET: a veth peer wired to a bridge -- lo + eth0 on a private subnet
    child_ns["net"].net_ifaces = {"lo": ("127.0.0.1", 8), "eth0": ("172.17.0.2", 16)}
    child_ns["net"].net_routes = [
        ("default", "172.17.0.1", "eth0"),
        ("172.17.0.0/16", None, "eth0"),
    ]
    # container MNT: an overlayfs on / -- the classic Docker image layering
    child_ns["mnt"].mounts = [
        ("overlay", "/", "overlay"),
        ("proc", "/proc", "proc"),
        ("tmpfs", "/tmp", "tmpfs"),
    ]
    # container USER: rootless map -- uid 0..65535 inside == uid 100000..165535 outside
    child_ns["user"].uid_map = [(0, 100000, 65536)]
    return child_ns, child_ns["pid"]


# --------------------------------------------------------------------------
# PRETTY PRINTERS
# --------------------------------------------------------------------------
def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def hex_inode(i: int) -> str:
    return f"0x{i:08X}"


# ============================================================================
# SECTION A: the six namespace types at a glance
# ============================================================================
def section_overview():
    banner("SECTION A: the six namespace types (the six pairs of glasses)")
    print("Every namespace isolates ONE category of kernel resource. A container")
    print("wears all six. Without namespaces, every process shares one reality.\n")
    print("| type | clone flag       | isolates                        | what differs vs host      |")
    print("|------|-----------------|---------------------------------|---------------------------|")
    rows = [
        ("PID",  "CLONE_NEWPID",   "process IDs",                   "container's PID 1 != host PID 1"),
        ("NET",  "CLONE_NEWNET",   "network stack",                 "own lo/eth0, IP, routes"),
        ("MNT",  "CLONE_NEWNS",    "mount points",                  "own / tree, overlayfs"),
        ("UTS",  "CLONE_NEWUTS",   "hostname / domainname",         "own uname -n"),
        ("IPC",  "CLONE_NEWIPC",   "SysV IPC, POSIX mqueues, shm",  "own ipcs list"),
        ("USER", "CLONE_NEWUSER",  "uid/gid mapping",               "uid 0 inside == uid 100000 outside"),
    ]
    for t, fl, iso, diff in rows:
        print(f"| {t:<4} | {fl:<15} | {iso:<31} | {diff:<25} |")
    print()
    print("Identity rule (the whole game): two tasks share a namespace iff their")
    print("/proc/<pid>/ns/<type> symlinks point to the SAME inode. We model exactly")
    print("that -- each Namespace has an `inode`, and the gold check compares inodes.")
    print("\nHost's initial namespace inodes (big numbers, like a real box):")
    for t in NS_TYPES:
        print(f"  /proc/1/ns/{t:<4} -> inode {hex_inode(HOST_NS[t])}")


# ============================================================================
# SECTION B: PID namespace -- container sees PID 1, host sees PID 12345
# ============================================================================
def section_pid():
    banner("SECTION B: PID namespace -- 'I am PID 1' (but only in here)")
    k = build_kernel()
    # host has spawned init(1) and sshd(2). Now containerd asks the kernel to
    # clone() a new process tree in a fresh PID ns.
    child_ns, pid_ns = clone_new_container(k, cid="c1")
    # the child's global pid is the next host pid; its LOCAL pid inside the new
    # PID ns is 1 (always -- the first task in a PID ns is renumbered to 1).
    container_init = k.spawn("/bin/sh", child_ns)
    container_init.local_pid[pid_ns.inode] = 1          # inside the ns -> PID 1
    container_init.local_pid[HOST_NS["pid"]] = container_init.pid  # host sees the real pid
    # a child of the container
    sleeper = k.spawn("sleep 600", child_ns)
    sleeper.local_pid[pid_ns.inode] = 2
    sleeper.local_pid[HOST_NS["pid"]] = sleeper.pid
    # a grandchild
    grand = k.spawn("nginx: worker", child_ns)
    grand.local_pid[pid_ns.inode] = 3
    grand.local_pid[HOST_NS["pid"]] = grand.pid

    print("On the HOST (the true, combined view) -- `ps aux` from the host:\n")
    print(f"  {'HOST PID':<9} {'NAME':<14} {'PID-ns inode':<12}  local-pid-in-ns")
    print("  " + "-" * 56)
    for t in k.tasks:
        ns_pid = t.ns["pid"].inode
        lp = t.local_pid.get(ns_pid, t.pid)
        host_lp = t.local_pid.get(HOST_NS["pid"], t.pid)
        tag = "  (host)" if ns_pid == HOST_NS["pid"] else f"  -> inside ns: {lp}"
        print(f"  {t.pid:<9} {t.name:<14} {hex_inode(ns_pid):<12}  host-local={host_lp}{tag}")
    print()
    print(f"INSIDE the container's PID ns (inode {hex_inode(pid_ns.inode)}):")
    print("The kernel hands the container a DIFFERENT pid numbering. The very first")
    print("task in a new PID ns is ALWAYS renumbered to 1 -- so the container's")
    print("'/bin/sh' believes it is the init of a fresh machine.\n")
    print(f"  {'CONTAINER PID':<13} {'NAME':<14} {'== HOST PID (hidden)':<20}")
    print("  " + "-" * 50)
    for t in k.tasks:
        if t.ns["pid"].inode == pid_ns.inode:
            lp = t.local_pid[pid_ns.inode]
            print(f"  {lp:<13} {t.name:<14} {t.pid:<20}")
    print()
    print("THE MAPPING TABLE (what the host must keep, to translate signals):")
    print("  container-local PID  ->  global/host PID")
    for t in k.tasks:
        if t.ns["pid"].inode == pid_ns.inode:
            print(f"    {t.local_pid[pid_ns.inode]:<19} ->  {t.pid}")
    print("\n[check] container's PID 1 is NOT host's PID 1:",
          container_init.pid != 1, "(container init host-pid =", container_init.pid, ")")
    print("[check] isolation: inode(container pid ns) != inode(host pid ns):",
          pid_ns.inode != HOST_NS["pid"], "->",
          f"{hex_inode(pid_ns.inode)} != {hex_inode(HOST_NS['pid'])}")


# ============================================================================
# SECTION C: NET namespace -- separate interfaces, IPs, routing tables
# ============================================================================
def section_net():
    banner("SECTION C: NET namespace -- own loopback, own eth0, own routes")
    k = build_kernel()
    child_ns, _ = clone_new_container(k, cid="c1")
    host_net = k.namespaces[HOST_NS["net"]]
    ctr_net = child_ns["net"]
    print("A NET namespace is a FULL, independent network stack: its own loopback,")
    print("its own interfaces, its own IP addresses, its own routing table, and its")
    print("own iptables. Nothing crosses the boundary except via an explicit bridge")
    print("(docker0) + a veth pair.\n")
    print("HOST's view (inode %s):" % hex_inode(host_net.inode))
    print("  interfaces:")
    for name, (ip, mask) in host_net.net_ifaces.items():
        print(f"    {name:<5} {ip}/{mask}")
    print("  routing table:")
    for dst, via, dev in host_net.net_routes:
        via_s = via if via else "direct"
        print(f"    {dst:<16} via {via_s:<11} dev {dev}")
    print()
    print("CONTAINER's view (inode %s) -- a DIFFERENT stack:" % hex_inode(ctr_net.inode))
    print("  interfaces:")
    for name, (ip, mask) in ctr_net.net_ifaces.items():
        print(f"    {name:<5} {ip}/{mask}")
    print("  routing table:")
    for dst, via, dev in ctr_net.net_routes:
        via_s = via if via else "direct"
        print(f"    {dst:<16} via {via_s:<11} dev {dev}")
    print()
    print("Both stacks call their main interface 'eth0', but the IPs differ")
    print("(10.0.0.5 on host vs 172.17.0.2 in container) and the routing tables are")
    print("unrelated. The container can `ping 127.0.0.1` and hit its OWN loopback,")
    print("completely invisible to the host's loopback -- that is full stack isolation.")
    print("\n[check] isolation: container eth0 IP != host eth0 IP:",
          ctr_net.net_ifaces["eth0"][0] != host_net.net_ifaces["eth0"][0], "->",
          f"{ctr_net.net_ifaces['eth0'][0]} != {host_net.net_ifaces['eth0'][0]}")
    print("[check] isolation: net inodes differ:",
          ctr_net.inode != host_net.inode, "->",
          f"{hex_inode(ctr_net.inode)} != {hex_inode(host_net.inode)}")


# ============================================================================
# SECTION D: MNT namespace -- separate mount tree, overlayfs
# ============================================================================
def section_mnt():
    banner("SECTION D: MNT namespace -- own / tree, the overlayfs trick")
    k = build_kernel()
    child_ns, _ = clone_new_container(k, cid="c1")
    host_mnt = k.namespaces[HOST_NS["mnt"]]
    ctr_mnt = child_ns["mnt"]
    print("A MNT namespace gives a process its OWN mount table -- its OWN view of")
    print("what is mounted on /. The host's `mount` and the container's `mount` show")
    print("DIFFERENT filesystems, even though they share the same physical disk.\n")
    print("HOST's mount table (inode %s):" % hex_inode(host_mnt.inode))
    for src, tgt, fs in host_mnt.mounts:
        print(f"  {src:<12} on {tgt:<8} type {fs}")
    print()
    print("CONTAINER's mount table (inode %s):" % hex_inode(ctr_mnt.inode))
    for src, tgt, fs in ctr_mnt.mounts:
        print(f"  {src:<12} on {tgt:<8} type {fs}")
    print()
    print("The container's '/' is an OVERLAYFS, the core of every Docker image:")
    print("    lowerdir = read-only image layers (ubuntu, then python, then app)")
    print("    upperdir = container's own writable scratch space")
    print("    merged   = the unified view the container sees as '/'")
    print("When the container writes /etc/foo, it lands in upperdir. The image layer")
    print("(lowerdir) is never mutated -- so 100 containers share ONE ubuntu image.")
    print()
    print("A file mounted in the container NEVER shows up in `mount` on the host's")
    print("shell (unless you nsenter the container's MNT ns first). That is MNT")
    print("isolation: same disk, different mount tables.\n")
    print("[check] isolation: container '/' fstype != host '/' fstype:",
          ctr_mnt.mounts[0][2] != host_mnt.mounts[0][2], "->",
          f"{ctr_mnt.mounts[0][2]} != {host_mnt.mounts[0][2]}")
    print("[check] isolation: mnt inodes differ:",
          ctr_mnt.inode != host_mnt.inode, "->",
          f"{hex_inode(ctr_mnt.inode)} != {hex_inode(host_mnt.inode)}")


# ============================================================================
# SECTION E: USER namespace -- UID 0 inside -> UID 100000 outside (rootless)
# ============================================================================
def section_user():
    banner("SECTION E: USER namespace -- 'I am root' (but the host disagrees)")
    k = build_kernel()
    child_ns, _ = clone_new_container(k, cid="c1")
    host_user = k.namespaces[HOST_NS["user"]]
    ctr_user = child_ns["user"]
    print("A USER namespace is a LOOKUP TABLE between uids. The container says")
    print("'uid 0', the kernel looks it up, and on the host it is uid 100000. The")
    print("container has FULL root powers INSIDE its namespace (can bind port 80, can")
    print("kill its own children), but ZERO real privilege OUTSIDE -- it cannot touch")
    print("host /etc/passwd. This is how rootless containers (Podman) work.\n")
    print("uid_map format:  <inside_first> <outside_first> <count>")
    print()
    print("HOST USER ns uid_map (inode %s):" % hex_inode(host_user.inode))
    for inside, outside, count in host_user.uid_map:
        print(f"    uid {inside:<6} -> uid {outside:<6} count {count:<6}  (identity)")
    print()
    print("CONTAINER USER ns uid_map (inode %s):" % hex_inode(ctr_user.inode))
    for inside, outside, count in ctr_user.uid_map:
        print(f"    uid {inside:<6} -> uid {outside:<6} count {count:<6}  (shifted!)")
    print()
    # translate a few uids both ways
    print("Translate some uids through the container's map:")
    for inside in (0, 1, 1000, 65535):
        outside = 100000 + inside   # the single map entry covers all of these
        print(f"    container: 'I am uid {inside:<6}'   host sees: uid {outside}")
    print()
    print("Note the boundary: inside-uid 65536 is NOT covered by the map -- the")
    print("kernel refuses to create such a process (writes 'No mapping' in")
    print("/proc/<pid>/uid_map semantics). That caps a container's identity space.")
    print("\n[check] isolation: container uid 0 != host uid 0:",
          ctr_user.uid_map[0][1] != host_user.uid_map[0][1], "->",
          f"host sees uid {ctr_user.uid_map[0][1]} for container's root")
    print("[check] isolation: user inodes differ:",
          ctr_user.inode != host_user.inode, "->",
          f"{hex_inode(ctr_user.inode)} != {hex_inode(host_user.inode)}")


# ============================================================================
# SECTION F: unshare/clone demo + the gold check (all six at once)
# ============================================================================
def section_unshare_clone():
    banner("SECTION F: unshare(2) / clone(2) -- birthing a container, and the GOLD check")
    k = build_kernel()
    print("Two syscalls create namespaces:\n")
    print("  unshare(flags) : the CALLING process swaps its OWN namespaces for fresh")
    print("                   ones (e.g. `unshare --pid --fork bash`). Used by `unshare`")
    print("                   and by tools that re-self-containerize.\n")
    print("  clone(flags)   : fork() a CHILD that is ALREADY in fresh namespaces.")
    print("                   This is what runc/containerd do. The child wakes up as")
    print("                   PID 1 in a new PID ns with a new network stack, etc.\n")
    print("The flags are bitmasks. To make a full container you OR them all together:")
    print("    ALL_SIX = CLONE_NEWNS | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWPID")
    print("            | CLONE_NEWNET | CLONE_NEWUSER")
    print(f"            = 0x{ALL_SIX:08X}")
    print()

    # Walk each flag bit
    print("Flag bit decode of ALL_SIX = 0x%08X:" % ALL_SIX)
    flag_defs = [
        ("CLONE_NEWNS", CLONE_NEWNS, "mnt"),
        ("CLONE_NEWUTS", CLONE_NEWUTS, "uts"),
        ("CLONE_NEWIPC", CLONE_NEWIPC, "ipc"),
        ("CLONE_NEWUSER", CLONE_NEWUSER, "user"),
        ("CLONE_NEWPID", CLONE_NEWPID, "pid"),
        ("CLONE_NEWNET", CLONE_NEWNET, "net"),
    ]
    for name, val, t in flag_defs:
        on = bool(ALL_SIX & val)
        print(f"    {name:<14} 0x{val:08X}  -> {'ON ' if on else 'off'}  (new {t} ns)")
    print()

    # Now actually clone a full container
    print("clone(child_fn, ALL_SIX) -- runc launches a container with all 6 set:")
    child_ns, pid_ns = clone_new_container(k, flags=ALL_SIX, cid="c1")
    container_init = k.spawn("containerd-shim (PID 1 inside)", child_ns)
    container_init.local_pid[pid_ns.inode] = 1
    container_init.local_pid[HOST_NS["pid"]] = container_init.pid

    # The gold check: for EVERY namespace type, container's inode != host's inode.
    print("GOLD CHECK -- isolation property across all 6 types:")
    print("  A real container must be isolated on EVERY axis, not just some.\n")
    print(f"  {'TYPE':<5} {'host inode':<12} {'container inode':<16} {'isolated?':<10}")
    print("  " + "-" * 46)
    all_isolated = True
    for t in NS_TYPES:
        h_inode = HOST_NS[t]
        c_inode = child_ns[t].inode
        iso = c_inode != h_inode
        all_isolated = all_isolated and iso
        mark = "OK" if iso else "FAIL"
        print(f"  {t.upper():<5} {hex_inode(h_inode):<12} {hex_inode(c_inode):<16} {mark:<10}")
    print()
    verdict = "OK" if all_isolated else "FAIL"
    print(f"[check] all 6 namespaces isolated from host: {verdict}")

    # Pin a gold scalar for namespaces.html: the container-init's host pid AND
    # its container-local pid, plus the count of isolated namespaces. The .html
    # recomputes these from the same model.
    gold = {
        "container_init_host_pid": container_init.pid,
        "container_init_local_pid": container_init.local_pid[pid_ns.inode],
        "isolated_count": sum(1 for t in NS_TYPES if child_ns[t].inode != HOST_NS[t]),
        "total_types": len(NS_TYPES),
        "container_uid0_on_host": child_ns["user"].uid_map[0][1],
        "container_eth0_ip": child_ns["net"].net_ifaces["eth0"][0],
        "container_hostname": child_ns["uts"].hostname,
    }
    print("\nGOLD values (pinned for namespaces.html):")
    for kk, vv in gold.items():
        print(f"    {kk:<28} = {vv}")
    assert gold["isolated_count"] == 6, "all 6 must be isolated for a real container"
    assert gold["container_init_local_pid"] == 1, "container's first process is PID 1"
    assert gold["container_init_host_pid"] != 1, "host must NOT see it as PID 1"
    assert gold["container_uid0_on_host"] == 100000, "rootless uid shift"
    print("[check] gold assertions (PID 1 inside != 1 outside, 6/6 isolated, uid shift): OK")


# ============================================================================
# main
# ============================================================================
def main():
    print("namespaces.py - reference model of Linux namespaces.")
    print("All numbers below feed NAMESPACES.md and namespaces.html.")
    print("Python", sys.version.split()[0])

    section_overview()
    section_pid()
    section_net()
    section_mnt()
    section_user()
    section_unshare_clone()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
