"""
container_runtime.py - Reference model of the container runtime stack: the
high-level vs low-level split, the Docker dockerd -> containerd -> runc layers,
the OCI Runtime Spec (config.json) that hands off between them, the overlayfs
snapshotter that assembles rootfs from image layers, the Kubernetes CRI
interface, and the alternative isolation runtimes (Kata / gVisor / Firecracker).

This is the single source of truth that CONTAINER_RUNTIME.md is built from.
Every layer table, OCI spec, snapshot chain, and CRI call in the guide is
printed by this file. If you change something here, re-run and re-paste the
output into the guide.

Run:
    python3 container_runtime.py

============================================================================
THE INTUITION (read this first) - the general contractor and the framer
============================================================================
Running a container is two DIFFERENT jobs, and the industry split them:

  * the HIGH-LEVEL runtime (containerd / CRI-O): the GENERAL CONTRACTOR. It
    pulls images, extracts layers, assembles the rootfs, keeps the container
    alive, talks to Kubernetes. Lots of bookkeeping, very little syscall
    privilege.
  * the LOW-LEVEL runtime (runc): the FRAMER. Given a bundle directory
    (rootfs + config.json) it does the ONE privileged thing: clone(CLONE_NEW*)
    to make the namespaces, write cgroups, chroot/pivot_root, and exec the
    process. Then it mostly waits.

The contract between them is the OCI RUNTIME SPEC - a config.json describing
"here is the rootfs, here are the process args, here are the namespaces, here
are the mounts; now run it." runc is OBLIVIOUS to images, registries, networks,
or Kubernetes. containerd is OBLIVIOUS to namespaces/cgroups (it asks runc).
That clean seam is the whole reason Docker, containerd, CRI-O, Podman, and
Kubernetes can all share one runc.

Docker's own stack is four nested layers, each a separate process:

    docker CLI  ->  dockerd  ->  containerd  ->  containerd-shim  ->  runc

The CLI is just an HTTP client. dockerd owns the user-facing API, image builds,
volumes, networks. containerd owns image storage + lifecycle. The SHIM is the
trick that keeps a container alive even if containerd restarts: runc exits
right after exec, so the shim becomes the container's parent (reaper, signal
forwarder) and is itself supervised by containerd.

============================================================================
HOW IT ACTUALLY RUNS (the lifecycle, concretely)
============================================================================
  docker run nginx
    1. CLI POSTs /containers/create + /containers/start to dockerd.
    2. dockerd asks containerd to create the container with a fully-formed OCI
       bundle (rootfs path + config.json).
    3. containerd PULLS the image if missing: downloads the manifest, then each
       LAYER blob (a tar.gz), and feeds each to the SNAPSHOTTER. The snapshotter
       stacks layers with overlayfs: every layer is a readonly `lowerdir`, the
       container's writes go to a fresh `upperdir`. The merged view = rootfs.
    4. containerd spawns a containerd-shim (one per container).
    5. The shim execs `runc create` with the bundle; runc:
         - clone()s with CLONE_NEWPID|NEWNET|NEWNS|...  -> the namespaces
         - sets up the cgroup (CPU/memory/pids limits)
         - pivot_root into rootfs, sets up mounts (/proc, /sys, /dev/...)
         - exec's the process args (e.g. ["nginx","-g","daemon off;"])
       runc then EXITS. The shim is now the container process's parent.
    6. The container runs. The shim forwards signals, reaps the zombie on exit,
       and reports status to containerd -> dockerd -> CLI.

Kubernetes replaces dockerd with the CRI (Container Runtime Interface) gRPC:
kubelet -> CRI (containerd's CRI plugin, or CRI-O) -> OCI (runc). Same runc,
same OCI spec, different general contractor on top.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
   OCI                : Open Container Initiative. Two specs: the IMAGE spec
                        (how an image tarball is laid out) and the RUNTIME spec
                        (config.json + rootfs bundle). runc implements the latter.
   config.json        : the OCI runtime spec file. Describes root, process,
                        mounts, linux.namespaces, linux.cgroupsPath, seccomp.
                        This is the handoff between high-level and low-level.
   rootfs / root.path : the filesystem the container sees as "/". Assembled by
                        stacking image layers (overlayfs) into one merged dir.
   bundle             : a directory containing config.json + rootfs/. That is
                        ALL runc needs: `runc run <id>` from inside the bundle.
   namespaces         : Linux isolation primitives (clone CLONE_NEW*). pid/net/
                        ipc/uts/mnt/cgroup each hide part of the system. runc
                        creates them from the spec's linux.namespaces list.
   cgroups            : control groups - resource accounting/limits (CPU, memory,
                        pids, blkio). Set from linux.resources + cgroupsPath.
   layer              : a filesystem delta (tar.gz) in an image. Stacked by the
                        snapshotter; each is content-addressed by SHA256.
   snapshotter        : containerd's component that stacks layers into a rootfs.
                        overlayfs = lowerdir (readonly layers) + upperdir (writes).
   containerd         : the high-level runtime CNCF graduated project. Owns image
                        pull, snapshot, lifecycle. Used by Docker and K8s.
   containerd-shim    : a tiny per-container supervisor. Becomes the container's
                        parent after runc exits; decouples container lifetime
                        from containerd's lifetime.
   runc               : the low-level OCI reference runtime. Creates namespaces
                        + cgroups, execs the process. The only truly privileged
                        piece in the stack.
   CRI                : Kubernetes Container Runtime Interface - a gRPC service
                        (RuntimeService + ImageService) kubelet calls. Implemented
                        by containerd's cri plugin and CRI-O.
   gVisor / runsc     : alternative low-level runtime. A user-space kernel
                        intercepts syscalls (via ptrace or KVM), so the container
                        never touches the host kernel directly. Stronger isolation.
   Kata Containers    : alternative runtime. Each pod runs in a lightweight VM
                        (QEMU), giving hardware-level isolation with a guest kernel.
   Firecracker        : Amazon's microVM (rust). Minimal device model, ~125ms boot;
                        powers Lambda/Fargate. Integrated via firecracker-containerd.

============================================================================
THE LINEAGE (sources)
============================================================================
   OCI Runtime Spec (opencontainers/runtime-spec) : config.json schema - root,
                        process, mounts, linux.namespaces, linux.cgroupsPath.
   OCI Image Spec (opencontainers/image-spec)     : manifest + layer layout.
   runc (opencontainers/runc)                     : the reference OCI runtime,
                        spun out of libcontainer in 2015.
   containerd (containerd/containerd)             : high-level runtime, donated
                        by Docker to CNCF (2017), graduated 2019.
   Kubernetes CRI (kubernetes/cri-api)            : RuntimeService + ImageService
                        gRPC; kubelet -> CRI -> OCI.
   Kata Containers (kata-containers)              : VM-isolated containers.
   gVisor (google/gvisor)                         : user-space kernel sandbox.
   Firecracker (firecracker-microvm/firecracker)  : microVM, AWS.

KEY INVARIANTS (all asserted/printed below):
   OCI spec fields   : root.path == merged rootfs dir; process.args == image CMD;
                        linux.namespaces == {pid,ipc,uts,mnt,net,cgroup};
                        cgroupsPath names the resource limit group.
   overlay mount     : lowerdir = image layers (readonly, joined by ':'),
                        upperdir = container's writable snapshot,
                        workdir  = overlayfs internal work dir.
   stack seam        : runc consumes ONLY config.json+rootfs; it never sees
                        images/registries/networks. containerd never touches
                        namespaces/cgroups directly (it asks runc).
   CRI -> OCI        : every CRI CreateContainer compiles to one OCI bundle +
                        one runc invocation (possibly via a shim).

Conventions: OCI specs are plain dicts (JSON-serializable); layers are content
digests (strings). Fully deterministic; the .html replays these exact specs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

BANNER = "=" * 72

OCI_VERSION = "1.0.2"

# The namespaces `runc spec` emits by default (the OCI baseline a default
# Docker/containerd container creates). user namespace is ADDED only with
# --userns-remap, so it is absent from the default set.
DEFAULT_NAMESPACES = ["pid", "ipc", "uts", "mnt", "net", "cgroup"]


# ============================================================================
# 1. THE OCI RUNTIME SPEC GENERATOR (config.json)
# ============================================================================

def _default_mounts() -> list[dict]:
    """The mount table a default Docker container gets. Bind-mounted config
    files (resolv.conf / hostname / hosts) are how per-container DNS and the
    hostname reach the container's /etc without modifying the image layer."""
    return [
        {"destination": "/proc",            "type": "proc",    "source": "proc",    "options": ["nosuid","noexec","nodev"]},
        {"destination": "/dev",             "type": "tmpfs",   "source": "tmpfs",   "options": ["nosuid","strictatime","mode=755","size=65536k"]},
        {"destination": "/dev/pts",         "type": "devpts",  "source": "devpts",  "options": ["nosuid","noexec","newinstance","ptmxmode=0666","mode=0620","gid=5"]},
        {"destination": "/sys",             "type": "sysfs",   "source": "sysfs",   "options": ["nosuid","noexec","nodev","ro"]},
        {"destination": "/sys/fs/cgroup",   "type": "cgroup",  "source": "cgroup",  "options": ["nosuid","noexec","nodev","relatime","ro"]},
        {"destination": "/dev/mqueue",      "type": "mqueue",  "source": "mqueue",  "options": ["nosuid","noexec","nodev"]},
        {"destination": "/dev/shm",         "type": "tmpfs",   "source": "shm",     "options": ["nosuid","noexec","nodev","mode=1777","size=65536k"]},
        {"destination": "/etc/resolv.conf", "type": "bind",    "source": "/var/lib/docker/containers/CONTAINER_ID/resolv.conf", "options": ["rbind","rprivate"]},
        {"destination": "/etc/hostname",    "type": "bind",    "source": "/var/lib/docker/containers/CONTAINER_ID/hostname",    "options": ["rbind","rprivate"]},
        {"destination": "/etc/hosts",       "type": "bind",    "source": "/var/lib/docker/containers/CONTAINER_ID/hosts",       "options": ["rbind","rprivate"]},
    ]


def gen_oci_spec(
    name: str,
    rootfs_path: str,
    args: list[str],
    env: list[str] | None = None,
    namespaces: list[str] | None = None,
    mounts: list[dict] | None = None,
    cgroups_path: str | None = None,
    readonly_root: bool = False,
    uid: int = 0,
    gid: int = 0,
) -> dict:
    """Build an OCI Runtime Spec (config.json) dict.

    This is exactly the document containerd hands to runc. runc consumes ONLY
    this + rootfs: it never sees images, registries, or networks. Defaults
    mirror `runc spec` + Docker's mount table.
    """
    ns = namespaces if namespaces is not None else list(DEFAULT_NAMESPACES)
    spec = {
        "ociVersion": OCI_VERSION,
        "root": {"path": rootfs_path, "readonly": readonly_root},
        "process": {
            "terminal": False,
            "user": {"uid": uid, "gid": gid},
            "args": list(args),
            "env": list(env) if env else [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "HOSTNAME=" + name,
            ],
            "cwd": "/",
            "capabilities": {
                "bounding":   ["CAP_NET_BIND_SERVICE"],
                "effective":  ["CAP_NET_BIND_SERVICE"],
                "permitted":  ["CAP_NET_BIND_SERVICE"],
            },
            "noNewPrivileges": True,
        },
        "hostname": name,
        "mounts": mounts if mounts is not None else _default_mounts(),
        "linux": {
            "namespaces": [{"type": t} for t in ns],
            "cgroupsPath": cgroups_path or f"/docker/{name}",
            "resources": {
                "memory": {"limit": 536870912},     # 512 MiB
                "cpu":    {"shares": 1024},
                "pids":   {"limit": 2048},
            },
            "seccomp": {"defaultAction": "SCMP_ACT_ERRNO"},
        },
    }
    return spec


def print_spec(spec: dict, title: str = "config.json"):
    """Pretty-print an OCI spec, truncating long option lists for readability."""
    print(f"{title}  (ociVersion {spec['ociVersion']}):\n")
    print(json.dumps(spec, indent=2))
    print()


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 2. THE SNAPSHOTTER - stack image layers into a rootfs via overlayfs
# ============================================================================

@dataclass
class ImageLayer:
    """One layer of a container image: a content-addressed filesystem delta."""
    digest: str        # sha256:...
    size_bytes: int
    command: str       # the Dockerfile step that produced it


@dataclass
class Image:
    """An image = a manifest pointing at an ordered list of layers."""
    name: str
    layers: list[ImageLayer]

    def total_size(self) -> int:
        return sum(l.size_bytes for l in self.layers)


OVERLAY_ROOT = "/var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots"


def snapshot_paths(idx: int) -> dict:
    """The on-disk layout containerd's overlayfs snapshotter uses for snapshot
    number `idx`: fs/ holds the filesystem tree, work/ is overlayfs internal."""
    base = f"{OVERLAY_ROOT}/{idx}"
    return {"fs": f"{base}/fs", "work": f"{base}/work"}


def build_overlay_mount(image: Image, active_idx: int) -> dict:
    """Compose the overlayfs mount that becomes the container's rootfs.

    containerd model: every IMAGE layer is a readonly lowerdir (in order), and
    the container's writes go to a fresh ACTIVE snapshot (upperdir/workdir).
    The merged mount is what root.path in the OCI spec points at.

    Returns: { lowerdir: [...], upperdir, workdir, mount_opts: str, rootfs }
    """
    lower = []
    for i, layer in enumerate(image.layers, start=1):
        lower.append(snapshot_paths(i)["fs"])    # readonly layers, bottom->top
    active = snapshot_paths(active_idx)
    opts = (
        f"lowerdir={':'.join(lower)},"
        f"upperdir={active['fs']},"
        f"workdir={active['work']}"
    )
    merged = f"{OVERLAY_ROOT}/{active_idx}/merged"
    return {
        "lowerdir": lower,
        "upperdir": active["fs"],
        "workdir": active["work"],
        "mount_opts": opts,
        "rootfs": merged,
        "layer_count": len(image.layers),
    }


# ============================================================================
# 3. THE RUNTIME STACK - each layer, its role, and what it talks to
# ============================================================================

@dataclass
class RuntimeLayer:
    """One layer of the Docker/K8s runtime stack."""
    name: str
    kind: str            # 'cli' | 'high' | 'shim' | 'low'
    role: str
    consumes: str        # what it receives from the layer above
    produces: str        # what it passes down
    pid_scope: str       # is it a long-lived daemon or per-container?


def docker_stack() -> list[RuntimeLayer]:
    """docker CLI -> dockerd -> containerd -> containerd-shim -> runc."""
    return [
        RuntimeLayer("docker", "cli",
                     "user-facing REST/CLI client",
                     "typed commands (run/build/pull)",
                     "HTTP REST calls to dockerd",
                     "exits after each command"),
        RuntimeLayer("dockerd", "high",
                     "daemon: API, image build, volumes, networks, auth",
                     "REST requests from the CLI",
                     "containerd API calls (image pull, container create)",
                     "1 long-lived daemon per host"),
        RuntimeLayer("containerd", "high",
                     "image management, snapshotter, lifecycle, CRI plugin",
                     "containerd API + image refs",
                     "an OCI bundle (config.json + rootfs) + shim spawn",
                     "1 long-lived daemon per host"),
        RuntimeLayer("containerd-shim", "shim",
                     "per-container supervisor: parent, signal fwd, reaper",
                     "the OCI bundle + container id",
                     "execs runc create; then owns the process",
                     "1 per container (outlives runc)"),
        RuntimeLayer("runc", "low",
                     "OCI runtime: namespaces, cgroups, pivot_root, exec",
                     "config.json + rootfs bundle",
                     "a running container process; then EXITS",
                     "exits immediately after exec"),
    ]


# ============================================================================
# 4. KUBERNETES CRI - the gRPC seam kubelet -> CRI -> OCI
# ============================================================================

@dataclass
class CRIMethod:
    service: str         # 'RuntimeService' | 'ImageService'
    method: str
    args: str
    returns: str


def cri_methods() -> list[CRIMethod]:
    """The CRI gRPC methods kubelet calls. Each maps to the runtime's job."""
    return [
        CRIMethod("ImageService",   "PullImage",          "{image, auth}",          "{image_ref}"),
        CRIMethod("ImageService",   "ListImages",         "{filter}",               "{images[]}"),
        CRIMethod("ImageService",   "ImageStatus",        "{image}",                "{image_info}"),
        CRIMethod("RuntimeService", "RunPodSandbox",      "{config}",               "{pod_sandbox_id}"),
        CRIMethod("RuntimeService", "CreateContainer",    "{sandbox_id,config}",    "{container_id}"),
        CRIMethod("RuntimeService", "StartContainer",     "{container_id}",         "{}"),
        CRIMethod("RuntimeService", "StopContainer",      "{container_id,timeout}", "{}"),
        CRIMethod("RuntimeService", "RemoveContainer",    "{container_id}",         "{}"),
        CRIMethod("RuntimeService", "ListContainers",     "{filter}",               "{containers[]}"),
        CRIMethod("RuntimeService", "ContainerStatus",    "{container_id}",         "{status}"),
        CRIMethod("RuntimeService", "ExecSync",           "{container_id,cmd}",     "{stdout,stderr}"),
    ]


# ============================================================================
# 5. ALTERNATIVE RUNTIMES - runc vs gVisor vs Kata vs Firecracker
# ============================================================================

@dataclass
class AltRuntime:
    name: str
    isolation: str       # what boundary the workload crosses
    boundary: str        # the kernel the container sees
    boot: str            # cold-start cost
    tradeoff: str


def alt_runtimes() -> list[AltRuntime]:
    return [
        AltRuntime("runc", "namespaces + cgroups",
                   "shares the HOST kernel",
                   "~immediate (fork/exec)",
                   "lowest overhead; weakest isolation (kernel vuln = container escape)"),
        AltRuntime("gVisor (runsc)", "user-space kernel (ptrace/KVM)",
                   "a PARAVIRTUALIZED kernel (gofer + Sentry)",
                   "tens of ms",
                   "intercepts syscalls; strong app isolation; some syscall incompat"),
        AltRuntime("Kata Containers", "hardware VM (QEMU)",
                   "a GUEST kernel inside a lightweight VM",
                   "100-250 ms (VM boot)",
                   "hardware-grade isolation; near-native perf; heavier memory"),
        AltRuntime("Firecracker", "microVM (Rust, minimal devices)",
                   "a GUEST kernel in a tiny VM",
                   "~125 ms (boot)",
                   "minimal device model; very dense; powers Lambda/Fargate"),
        AltRuntime("crun", "namespaces + cgroups (C impl)",
                   "shares the HOST kernel",
                   "~immediate (faster than runc)",
                   "drop-in runc replacement; smaller/faster; same threat model"),
    ]


# ============================================================================
# 6. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: the runtime stack - docker CLI -> dockerd -> containerd -> runc
# ----------------------------------------------------------------------------

def section_a():
    banner("SECTION A: the runtime stack - 4 layers, 4 processes")
    print("`docker run nginx` does NOT call one program. It walks a stack of")
    print("specialised layers, each handing a SMALLER, more privileged job down:\n")
    print("  | layer            | kind  | role                                   "
          "| consumes -> produces          | lifetime        |")
    print("  |------------------|-------|----------------------------------------"
          "|-------------------------------|-----------------|")
    for L in docker_stack():
        print(f"  | {L.name:<16} | {L.kind:<5} | {L.role:<38} "
              f"| {L.consumes[:15]:<15}-> {L.produces[:13]:<13} | {L.pid_scope:<15} |")
    print()
    print("Each downward arrow is a NARROWER contract:")
    print('  CLI      -> dockerd       : HTTP REST (typed commands)')
    print("  dockerd  -> containerd    : containerd gRPC API (image ref + config)")
    print("  containerd -> shim        : an OCI bundle (config.json + rootfs)")
    print("  shim     -> runc          : `runc create <id>` from the bundle")
    print()
    print("KEY SEAM: runc receives ONLY config.json + rootfs. It has no idea an")
    print("image, registry, or network exists. containerd never creates a single")
    print("namespace - it asks runc. That seam is why Docker, containerd, CRI-O,")
    print("and Podman all share ONE runc.\n")

    stack = docker_stack()
    assert [L.name for L in stack] == \
        ["docker", "dockerd", "containerd", "containerd-shim", "runc"]
    assert stack[-1].kind == "low" and stack[-1].pid_scope.startswith("exits")
    print("[check] 5 layers, runc is the low-level (OCI) one that exits after "
          "exec: OK")


# ----------------------------------------------------------------------------
# SECTION B: the OCI runtime spec (config.json) - the handoff document
# ----------------------------------------------------------------------------

def section_b():
    banner("SECTION B: the OCI runtime spec (config.json) - the handoff")
    print("The contract between containerd and runc is a single JSON file. runc")
    print("consumes it and creates exactly what it says - nothing more.\n")
    spec = gen_oci_spec(
        name="nginx",
        rootfs_path="/var/lib/docker/overlay2/7f3a/merged",
        args=["nginx", "-g", "daemon off;"],
        env=["PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
             "NGINX_VERSION=1.25.3", "HOSTNAME=nginx"],
        cgroups_path="/docker/nginx",
    )
    print_spec(spec, "nginx container config.json")
    print("The fields runc actually ACTS on:")
    print(f"  root.path          -> pivot_root target (the merged rootfs)")
    print(f"  process.args       -> the exec'd command: {spec['process']['args']}")
    print(f"  linux.namespaces   -> clone(CLONE_NEW*) flags: "
          f"{[n['type'] for n in spec['linux']['namespaces']]}")
    print(f"  linux.cgroupsPath  -> the resource-limit group: "
          f"{spec['linux']['cgroupsPath']}")
    print(f"  mounts             -> {len(spec['mounts'])} mounts set up before exec")
    print(f"  linux.resources    -> memory/cpu/pids limits written to cgroupsPath")
    print()
    print("Give the SAME bundle to ANY OCI runtime (runc, crun, runsc, kata) and")
    print("you get the same container with a different isolation boundary (Sec E).\n")

    # checks
    assert spec["ociVersion"] == OCI_VERSION
    assert spec["root"]["path"] == "/var/lib/docker/overlay2/7f3a/merged"
    assert spec["process"]["args"] == ["nginx", "-g", "daemon off;"]
    assert [n["type"] for n in spec["linux"]["namespaces"]] == DEFAULT_NAMESPACES
    assert spec["linux"]["cgroupsPath"] == "/docker/nginx"
    print("[check] root.path, process.args, 6 namespaces, cgroupsPath all set: OK")


# ----------------------------------------------------------------------------
# SECTION C: containerd snapshotter - stack layers into rootfs
# ----------------------------------------------------------------------------

def section_c():
    banner("SECTION C: image pull + snapshotter - layers stack into rootfs")
    print("An image is a manifest pointing at N ordered LAYERS (each a tar.gz")
    print("delta, content-addressed by SHA256). containerd's snapshotter stacks")
    print("them with overlayfs: image layers are readonly lowerdirs, the")
    print("container's writes go to a fresh upperdir. The merged view = rootfs.\n")

    nginx = Image("nginx:1.25", layers=[
        ImageLayer("sha256:a1b2c3...", 28_000_000, "FROM debian:bookworm"),
        ImageLayer("sha256:d4e5f6...", 52_000_000, "RUN apt-get update && apt-get install -y nginx"),
        ImageLayer("sha256:g7h8i9...", 8_000_000,  "CMD [\"nginx\",\"-g\",\"daemon off;\"]"),
    ])
    print(f"image {nginx.name}: {len(nginx.layers)} layers, "
          f"{nginx.total_size()/1e6:.0f} MB total\n")
    print("  | # | digest        | size MB | Dockerfile step                                |")
    print("  |---|---------------|---------|------------------------------------------------|")
    for i, L in enumerate(nginx.layers, 1):
        print(f"  | {i} | {L.digest[:13]:<13} | {L.size_bytes/1e6:<7.0f} "
              f"| {L.command:<46} |")
    print()

    # snapshot chain: 3 image layers -> snapshots 1,2,3; container active = 4
    mount = build_overlay_mount(nginx, active_idx=4)
    print("containerd prepares one snapshot per layer, then a fresh ACTIVE")
    print("snapshot (#4) for the container's own writes:\n")
    print("  snapshot 1  (layer 1, readonly)   -> lowerdir")
    print("  snapshot 2  (layer 2, readonly)   -> lowerdir")
    print("  snapshot 3  (layer 3, readonly)   -> lowerdir")
    print("  snapshot 4  (ACTIVE, read-write)  -> upperdir + workdir\n")
    print("The merged overlay mount becomes root.path in config.json:\n")
    print("  mount -t overlay overlay -o \\")
    print(f"    {mount['mount_opts']} \\")
    print(f"    {mount['rootfs']}")
    print(f"\n  lowerdir count = {len(mount['lowerdir'])}  (one per image layer)")
    print(f"  upperdir       = {mount['upperdir']}  (container writes land here)")
    print(f"  workdir        = {mount['workdir']}  (overlayfs internal)")

    # checks
    assert mount["layer_count"] == 3
    assert len(mount["lowerdir"]) == 3
    assert mount["lowerdir"][0] == f"{OVERLAY_ROOT}/1/fs"
    assert mount["lowerdir"][-1] == f"{OVERLAY_ROOT}/3/fs"
    assert mount["upperdir"] == f"{OVERLAY_ROOT}/4/fs"
    assert mount["mount_opts"].startswith("lowerdir=") and "upperdir=" in mount["mount_opts"]
    print("\n[check] 3 lowerdirs (image layers) + 1 upperdir (active), overlay "
          "opts well-formed: OK")


# ----------------------------------------------------------------------------
# SECTION D: Kubernetes CRI - kubelet -> CRI -> OCI
# ----------------------------------------------------------------------------

def section_d():
    banner("SECTION D: Kubernetes CRI - kubelet -> CRI gRPC -> OCI (runc)")
    print("On a node, kubelet does NOT call dockerd. It speaks the CRI gRPC to a")
    print("pluggable runtime (containerd's cri plugin, or CRI-O). The CRI shim")
    print("compiles each request down to an OCI bundle + a runc call.\n")
    print("  kubelet --[CRI gRPC]--> containerd/cri (or CRI-O) --[OCI bundle]--> runc\n")
    print("  | service          | method           | args                      "
          "| returns          |")
    print("  |------------------|------------------|---------------------------"
          "|------------------|")
    for m in cri_methods():
        print(f"  | {m.service:<16} | {m.method:<16} | {m.args:<25} "
              f"| {m.returns:<16} |")
    print()
    print("Trace: a pod with one nginx container\n")
    print("  kubelet: PullImage('nginx:1.25')              -> CRI pulls via containerd")
    print("  kubelet: RunPodSandbox(podConfig)             -> CRI sets up the pod netns")
    print("  kubelet: CreateContainer(sandbox, nginxConfig)-> CRI builds config.json")
    print("  kubelet: StartContainer(nginx_id)             -> CRI: runc create + start")
    print("  kubelet: ContainerStatus(nginx_id)            -> CRI: reports via shim")
    print()
    print("Same runc, same OCI spec, same namespaces - just a different general")
    print("contractor (CRI plugin) above it. dockershim (Docker's CRI bridge) was")
    print("REMOVED in Kubernetes 1.24; containerd/CRI-O are now the defaults.\n")

    services = {m.service for m in cri_methods()}
    assert services == {"RuntimeService", "ImageService"}
    has = {m.method for m in cri_methods()}
    assert {"PullImage", "RunPodSandbox", "CreateContainer", "StartContainer"} <= has
    print("[check] CRI exposes RuntimeService + ImageService, incl. the 4 core "
          "lifecycle calls: OK")


# ----------------------------------------------------------------------------
# SECTION E: alternative runtimes - different isolation boundaries
# ----------------------------------------------------------------------------

def section_e():
    banner("SECTION E: alternative runtimes - swap the isolation boundary")
    print("Because runc consumes a GENERIC OCI bundle, you can swap the low-level")
    print("runtime for a different isolation model without changing the app or")
    print("the high-level stack:\n")
    print("  | runtime         | isolation                    | kernel the container sees "
          "        | cold start      | trade-off                              |")
    print("  |-----------------|------------------------------|-----------------------------------"
          "|-----------------|----------------------------------------|")
    for r in alt_runtimes():
        print(f"  | {r.name:<15} | {r.isolation:<28} | {r.boundary:<33} "
              f"| {r.boot:<15} | {r.tradeoff:<38} |")
    print()
    print("All four accept the SAME config.json. The difference is HOW the process")
    print("is walled off from the host:\n")
    print("  runc      : the process runs directly on the host kernel, just hidden")
    print("              by namespaces. A host kernel CVE = a container escape.")
    print("  gVisor    : syscalls are intercepted by a user-space 'Sentry' kernel;")
    print("              the container never issues raw host syscalls.")
    print("  Kata      : the container runs inside a real VM (QEMU) with its own")
    print("              guest kernel -> hardware-enforced isolation.")
    print("  Firecracker: like Kata but a stripped-down microVM (Rust, ~minimal")
    print("              devices) optimized for boot speed and density.\n")
    print("Trade-off axis: isolation strength  vs  boot time + memory density.")
    print("runc wins on density; Kata/Firecracker win on defense-in-depth.\n")

    names = {r.name for r in alt_runtimes()}
    assert {"runc", "gVisor (runsc)", "Kata Containers", "Firecracker"} <= names
    shares_host = [r for r in alt_runtimes() if "HOST" in r.boundary]
    vms = [r for r in alt_runtimes() if "VM" in r.isolation]
    assert "runc" in shares_host[0].name
    assert len(vms) >= 2
    print("[check] runc shares host kernel; >=2 VM-isolated runtimes listed: OK")


# ----------------------------------------------------------------------------
# GOLD: a full OCI spec + overlay mount pinned for the .html
# ----------------------------------------------------------------------------

def section_gold():
    banner("GOLD: pinned OCI spec + overlay mount - the .html reproduces these")
    nginx = Image("nginx:1.25", layers=[
        ImageLayer("sha256:a1b2c3...", 28_000_000, "FROM debian:bookworm"),
        ImageLayer("sha256:d4e5f6...", 52_000_000, "RUN apt-get install -y nginx"),
        ImageLayer("sha256:g7h8i9...", 8_000_000,  "CMD nginx"),
    ])
    mount = build_overlay_mount(nginx, active_idx=4)
    spec = gen_oci_spec(
        name="nginx",
        rootfs_path=mount["rootfs"],
        args=["nginx", "-g", "daemon off;"],
        cgroups_path="/docker/nginx",
    )

    print("GOLD spec fields (pinned for container_runtime.html):\n")
    gold = {
        "ociVersion":        spec["ociVersion"],
        "root_path":         spec["root"]["path"],
        "root_readonly":     spec["root"]["readonly"],
        "process_args":      spec["process"]["args"],
        "hostname":          spec["hostname"],
        "namespaces":        [n["type"] for n in spec["linux"]["namespaces"]],
        "ns_count":          len(spec["linux"]["namespaces"]),
        "mounts_count":      len(spec["mounts"]),
        "mount_dests":       [m["destination"] for m in spec["mounts"]],
        "cgroupsPath":       spec["linux"]["cgroupsPath"],
        "mem_limit":         spec["linux"]["resources"]["memory"]["limit"],
    }
    for k, v in gold.items():
        shown = v if not isinstance(v, list) or len(v) <= 6 else \
            f"{v[:3]} ... ({len(v)} total)"
        print(f"  {k:<16} = {shown}")
    print()
    print("GOLD overlay mount (pinned for container_runtime.html):\n")
    omount = {
        "lowerdir_count": len(mount["lowerdir"]),
        "lowerdirs":      mount["lowerdir"],
        "upperdir":       mount["upperdir"],
        "workdir":        mount["workdir"],
        "mount_opts":     mount["mount_opts"],
        "rootfs":         mount["rootfs"],
    }
    print(f"  lowerdir count = {omount['lowerdir_count']}")
    for d in omount["lowerdirs"]:
        print(f"    {d}")
    print(f"  upperdir = {omount['upperdir']}")
    print(f"  workdir  = {omount['workdir']}")
    print(f"  rootfs   = {omount['rootfs']}")
    print()
    print("GOLD summary (the .html recomputes these from the same logic):\n")
    print("  | field            | gold value                                    |")
    print("  |------------------|-----------------------------------------------|")
    rows = [
        ("ociVersion",          gold["ociVersion"]),
        ("root.path",           gold["root_path"]),
        ("process.args",        " ".join(gold["process_args"])),
        ("linux.namespaces",    ",".join(gold["namespaces"])),
        ("namespace count",     gold["ns_count"]),
        ("mounts count",        gold["mounts_count"]),
        ("cgroupsPath",         gold["cgroupsPath"]),
        ("overlay lowerdirs",   gold["ns_count"] and f"{omount['lowerdir_count']} (image layers)"),
        ("overlay upperdir",    "active snapshot (container writes)"),
    ]
    for k, v in rows:
        print(f"  | {k:<16} | {str(v):<45} |")

    # ---- assert all GOLD ----
    assert gold["ociVersion"] == "1.0.2"
    assert gold["process_args"] == ["nginx", "-g", "daemon off;"]
    assert gold["namespaces"] == ["pid", "ipc", "uts", "mnt", "net", "cgroup"]
    assert gold["ns_count"] == 6
    assert gold["mounts_count"] == 10
    assert gold["cgroupsPath"] == "/docker/nginx"
    assert omount["lowerdir_count"] == 3
    assert omount["lowerdirs"][0] == f"{OVERLAY_ROOT}/1/fs"
    assert omount["upperdir"] == f"{OVERLAY_ROOT}/4/fs"
    print("\n[check] all GOLD spec fields + overlay mount reproduce from the "
          "generators: OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("container_runtime.py - reference model. All specs feed "
          "CONTAINER_RUNTIME.md.")
    print("pure Python stdlib ; deterministic OCI-spec + snapshot model.")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
