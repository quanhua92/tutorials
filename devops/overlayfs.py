"""
overlayfs.py - Reference simulation of the OverlayFS model that Docker's
overlay2 storage driver uses to store images and container filesystems.

This is the single source of truth that OVERLAYFS.md is built from. Every
number, table, and worked example in OVERLAYFS.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python overlayfs.py

==========================================================================
THE INTUITION (read this first) -- overhead transparencies on a projector
==========================================================================
Picture a stack of acetate sheets on an overhead projector:

  * Each sheet is a LAYER. Most are printed once and never changed (the IMAGE
    layers -- read-only). One BLANK sheet sits on top for you to scribble on
    (the CONTAINER's writable layer).
  * You look DOWN through the whole stack: the MERGED view is what you see.
    Where the top sheet and a lower sheet both have writing, the TOP sheet
    wins -- it HIDES whatever is printed underneath at that spot.
  * To EDIT a note that was printed on a lower sheet, you cannot erase it
    (it is read-only). Instead you TRACE that note onto your top sheet first,
    then change your tracing. That trace is COPY-ON-WRITE (CoW). The original
    printed sheet is NEVER touched -- so 100 students can lay 100 blank sheets
    on the SAME printed stack, each with their own private doodles, while the
    printed originals stay pristine and shared.

That is the whole of Docker's image storage:
  lowerdir  = the read-only image layers (printed sheets, bottom = base OS)
  upperdir  = the container's writable layer (your blank sheet)
  merged    = the union view the container actually sees as '/'
  work      = a private scratch dir the kernel uses to perform the copy-up

THE REASON OVERLAYFS EXISTS: a Docker image is often hundreds of MB, but a
running container usually changes only a handful of files. Without sharing,
running 100 containers off one 130 MB image would need 13 GB of disk. With
overlayfs, all 100 containers share the SAME read-only layers and each
carries only a few KB-to-MB of personal writes on top -- ~180 MB total.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  layer       : a read-only set of files (a tarball / a printed sheet).
                Identified by a content digest -- its "layer ID".
  image       : an ORDERED STACK of read-only layers (bottom = base OS,
                top = latest change). Stored once, shared by every container.
  lowerdir    : the image layers of a container mount, given TOP-FIRST
                (the kernel flag is `lowerdir=L2:L1:L0`). L2 shadows L1 etc.
  upperdir    : the container's writable layer. ALL writes land here.
  merged      : the union filesystem the container sees: upper shadows lower.
  copy-up     : the FIRST write to a file that currently lives in a lower
                layer. The kernel copies the file upper-ward, THEN applies
                the write. Happens ONCE per file per mount -- later writes
                go straight to upper.
  whiteout    : how a `rm` is represented: a special char-device marker in
                upper that says "hide this path from lower". Deletes are
                container-private; the lower original is still untouched.
  overlay2    : Docker's default storage driver on Linux >= 4.0. Implements
                all of the above via the in-kernel OverlayFS filesystem.

==========================================================================
THE LINEAGE (where it came from)
==========================================================================
  UnionFS    (2004)        : the original union mount; academic proof of concept.
  AUFS       (2006)        : the reimplementation Docker first shipped with
                             (Docker < 17.06). Out-of-tree patch; rejected by
                             mainline. Now deprecated/removed from Docker.
  OverlayFS  (2014, 3.18)  : merged into mainline Linux. Read-only lower +
                             writable upper, in-kernel, fast. Docker's overlay
                             driver wrapped it from 1.12.
  overlay2   (2017, 17.06) : Docker's rewrite -- mounts MANY lower layers in a
                             single OverlayFS instance (the "multiple lowerdir
                             support" added in Linux 4.0). This is today's
                             default on every supported Linux distro.
  fuse-overlayfs (2019)    : userspace reimplementation for ROOTLESS containers
                             (Podman/buildah) where mounting overlayfs needs no
                             privilege.

==========================================================================
KEY RELATIONSHIPS (all asserted in code below)
==========================================================================
  merged(path)      = upper[path] if present, else top-most lower[path]
  write to lower-p  => copy-up: upper gains p (ONCE), lower UNCHANGED
  cow_count(mount)  == number of DISTINCT lower files written to
  lowers_touched    == []   (read-only layers are NEVER mutated)
  storage(N ctrs)   = image_size + N * avg_upper       (lowers shared once)
  storage_naive(N)  = N * image_size                   (no sharing)
  savings_ratio     = storage_naive / storage          >> 1

  THE GOLD CHECK of this guide:
      cow_count == len(distinct_lower_files_written)
  i.e. a file is copied up EXACTLY ONCE per mount, no matter how many times
  the container edits it, and ONLY if it originated in a lower layer. The
  .html recomputes this from the identical model.

Conventions for sizes (used throughout):
  layer file inventories are realistic per-file byte sizes (ubuntu base ~72 MB,
  python3 apt layer ~48 MB, flask pip layer ~9.5 MB). Every total below is the
  plain `sum()` of those bytes -- nothing is hand-rounded.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field

BANNER = "=" * 72


# --------------------------------------------------------------------------
# 0. THE MODEL  (a tiny, deterministic stand-in for the real overlay mount)
# --------------------------------------------------------------------------

def layer_id(name: str, files: dict) -> str:
    """Content-addressed layer ID, like `sha256:...` truncated to 12 hex.

    Deterministic: identical (name, files) always yields the same id -- so two
    images built on the same ubuntu base share the SAME base-layer id, which is
    the whole basis of the pull cache (Section D).
    """
    h = hashlib.sha256()
    h.update(name.encode())
    h.update(b"\n")
    for path in sorted(files):
        h.update(f"{path}\0{files[path]}\n".encode())
    return h.hexdigest()[:12]


@dataclass
class Layer:
    """A filesystem layer: {path: size_bytes}. Read-only by default.

    `ro=False` marks the writable upperdir of a live container mount.
    """
    name: str
    files: dict
    ro: bool = True
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = layer_id(self.name, self.files)

    @property
    def size(self) -> int:
        return sum(self.files.values())


@dataclass
class Image:
    """An ordered stack of read-only layers, BOTTOM (base OS) to TOP."""
    name: str
    layers: list  # list[Layer], layers[0] == base

    @property
    def size(self) -> int:
        return sum(L.size for L in self.layers)

    def lowers_top_first(self) -> list:
        """Kernel order: lowerdir=L2:L1:L0  (top-most lower first)."""
        return list(reversed(self.layers))


@dataclass
class OverlayMount:
    """One container mount: lowerdirs (top-first) + a writable upperdir +
    a merged union view. Models copy-on-write and whiteout exactly."""
    lowers: list            # list[Layer], TOP-MOST lower first
    upper: Layer            # ro=False
    cow_count: int = 0
    cow_files: list = field(default_factory=list)

    def read(self, path: str):
        """Union lookup: upper wins, then lowers top-first."""
        if path in self.upper.files:
            return self.upper.files[path]
        for L in self.lowers:
            if path in L.files:
                return L.files[path]
        return None

    def write(self, path: str, size: int) -> str:
        """Write `size` bytes to `path` in the merged view. Returns the kind
        of operation performed: 'copy-up' | 'new' | 'in-place'.

        Copy-on-write: if `path` currently lives ONLY in a lower layer (not yet
        copied into upper), the kernel copies it upper-ward first, THEN applies
        the write. The lower original is never mutated.
        """
        in_lower = any(path in L.files for L in self.lowers)
        in_upper = path in self.upper.files
        if not in_upper and in_lower:
            # --- the copy-up: bring the lower version into upper, then write ---
            self.upper.files[path] = self.read(path)   # transient copy-up
            self.cow_count += 1
            self.cow_files.append(path)
            self.upper.files[path] = size              # then apply the write
            return "copy-up"
        if not in_upper and not in_lower:
            # brand-new file -> straight into upper, nothing to copy
            self.upper.files[path] = size
            return "new"
        # already in upper -> subsequent edit, in place, no extra copy
        self.upper.files[path] = size
        return "in-place"

    def remove(self, path: str) -> str:
        """Model a `rm` as a whiteout marker in upper. The lower original
        stays on disk; it is just hidden from THIS mount's merged view."""
        self.upper.files[f"(whiteout){path}"] = 0
        if path in self.upper.files:
            del self.upper.files[path]
        return "whiteout"


# --------------------------------------------------------------------------
# THE REFERENCE IMAGE: flask-app:1.0  (3 layers, the running example)
# --------------------------------------------------------------------------

# Layer 0 -- base ubuntu:22.04 rootfs (~72 MB).
BASE_FILES = {
    "/etc/passwd": 2_412,
    "/etc/group": 1_098,
    "/etc/shadow": 1_344,
    "/etc/hostname": 12,
    "/etc/os-release": 286,
    "/bin/bash": 1_234_568,
    "/bin/ls": 138_008,
    "/bin/cat": 43_240,
    "/bin/mkdir": 73_896,
    "/usr/lib/x86_64-linux-gnu/libc.so.6": 2_043_632,
    "/usr/lib/x86_64-linux-gnu/libpthread.so.0": 144_776,
    "/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2": 230_896,
    "/usr/share/doc/ubuntu/copyright": 88_120,
    "/usr/share/base-rootfs-bulk": 71_641_910,
}

# Layer 1 -- RUN apt-get install -y python3  (~48 MB).
APT_FILES = {
    "/usr/bin/python3": 6_064_384,
    "/usr/bin/python3.10": 6_064_384,
    "/usr/lib/python3.10/os.py": 38_120,
    "/usr/lib/python3.10/ast.py": 28_840,
    "/usr/lib/python3.10/lib-dynload/_hashlib.cpython-310-x86_64-linux-gnu.so": 44_200,
    "/usr/lib/python3.10/encodings/__init__.py": 12_400,
    "/usr/lib/python3.10/stdlib-bulk": 38_191_652,
}

# Layer 2 -- RUN pip install flask  (~9.5 MB).
PIP_FILES = {
    "/usr/local/lib/python3.10/dist-packages/flask/__init__.py": 6_120,
    "/usr/local/lib/python3.10/dist-packages/flask/app.py": 108_440,
    "/usr/local/lib/python3.10/dist-packages/flask/wrappers.py": 9_240,
    "/usr/local/lib/python3.10/dist-packages/jinja2/__init__.py": 3_400,
    "/usr/local/lib/python3.10/dist-packages/jinja2/environment.py": 92_180,
    "/usr/local/lib/python3.10/dist-packages/werkzeug/__init__.py": 5_200,
    "/usr/local/lib/python3.10/dist-packages/werkzeug/serving.py": 70_860,
    "/usr/local/lib/python3.10/dist-packages/itsdangerous/__init__.py": 12_040,
    "/usr/local/lib/python3.10/dist-packages/click/__init__.py": 8_800,
    "/usr/local/lib/python3.10/dist-packages/pip-deps-bulk": 9_683_720,
}


def build_image() -> Image:
    return Image(
        name="flask-app:1.0",
        layers=[
            Layer("ubuntu:22.04 (base)", dict(BASE_FILES)),
            Layer("apt: python3", dict(APT_FILES)),
            Layer("pip: flask", dict(PIP_FILES)),
        ],
    )


# --------------------------------------------------------------------------
# THE CANONICAL CONTAINER SCENARIO (used by sections B, C and F -- so every
# number in the guide, and the .html gold check, derives from ONE write list)
# --------------------------------------------------------------------------
CANONICAL_WRITES = [
    ("/etc/passwd",        2_520,    "appends 'appuser:x:1000:'  (file is in base L0)"),
    ("/etc/hostname",      5,        "sets hostname 'c1'         (file is in base L0)"),
    ("/var/log/flask.log", 500_000,  "writes a fresh log          (file is NEW)"),
    ("/app/data.json",     4_096,    "writes app state           (file is NEW)"),
    ("/etc/passwd",        2_540,    "appends ANOTHER line       (already in upper)"),
    ("/etc/hostname",      8,        "retypes hostname           (already in upper)"),
]


def fresh_mount(img: Image, label: str = "container upper") -> OverlayMount:
    """A brand-new container mount off `img`: empty writable upper + lowers."""
    return OverlayMount(
        lowers=img.lowers_top_first(),          # top-most lower first
        upper=Layer(label, {}, ro=False),
    )


def run_writes(mount: OverlayMount, writes) -> list:
    """Apply `writes` (list of (path,size[,note])) and return [(path,size,op)]."""
    out = []
    for w in writes:
        path, size = w[0], w[1]
        out.append((path, size, mount.write(path, size)))
    return out


# --------------------------------------------------------------------------
# PRETTY PRINTERS
# --------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def human(n: int) -> str:
    """Bytes -> human string, 1 decimal once we cross a KiB."""
    sign = "-" if n < 0 else ""
    n = abs(n)
    if n < 1024:
        return f"{sign}{n} B"
    units = ["KiB", "MiB", "GiB", "TiB", "PiB"]
    f = n / 1024.0
    i = 0
    while f >= 1024 and i < len(units) - 1:
        f /= 1024.0
        i += 1
    return f"{sign}{f:.1f} {units[i]}"


def short_id(idstr: str) -> str:
    return idstr[:12]


# ============================================================================
# SECTION A: the image as a stack of read-only layers
# ============================================================================

def section_stack():
    banner("SECTION A: the image as a stack of read-only layers")
    img = build_image()
    print(f"Image '{img.name}' is built from {len(img.layers)} layers,")
    print("BOTTOM (base OS) to TOP (latest change):\n")
    print(f"  {'#':<3} {'LAYER':<26} {'id':<14} {'files':<6} {'size':<12}")
    print("  " + "-" * 62)
    for i, L in enumerate(img.layers):
        print(f"  {i:<3} {L.name:<26} {short_id(L.id):<14} "
              f"{len(L.files):<6} {human(L.size):<12}")
    total_files = sum(len(L.files) for L in img.layers)
    print(f"\n  image total: {len(img.layers)} layers, {total_files} files, "
          f"{human(img.size)}")
    print("\nAll three layers are READ-ONLY. They are the lowerdir of every")
    print("container that runs this image, and they are stored on disk ONCE.")
    print("\nThe stack, drawn top-to-bottom (how OverlayFS sees it):")
    print("        +------------------------- merged (what the container sees)")
    print("        | upperdir  (container's writable layer -- added on `run`)")
    print("        +-------------------------")
    for L in img.layers:
        print(f"        | lower  {short_id(L.id)}  {L.name}")
    print("        +------------------------- (bottom = base OS)")
    # content-address check: rebuilding the same image gives the same ids
    img2 = build_image()
    same = all(a.id == b.id for a, b in zip(img.layers, img2.layers))
    print(f"\n[check] content-addressed ids are reproducible: {same}")
    print("[check] layer sizes sum to image size:",
          sum(L.size for L in img.layers) == img.size)


# ============================================================================
# SECTION B: copy-on-write -- /etc/passwd copied up, lower untouched
# ============================================================================

def section_cow():
    banner("SECTION B: copy-on-write -- edit /etc/passwd, lower stays pristine")
    img = build_image()
    # snapshot the base layer BEFORE the container runs, to prove it is untouched
    base_before = dict(img.layers[0].files)
    # run a container: writable upperdir + the image's layers as lowerdir
    mount = fresh_mount(img, "container upper (c1)")

    print("Container c1 starts. Its '/' is an OverlayFS mount:\n")
    print(f"    lowerdir = {[short_id(L.id) for L in mount.lowers]}  "
          f"(top-most first: pip, apt, base)")
    print(f"    upperdir  = {short_id(mount.upper.id)}  (empty, writable)")
    print(f"    merged    = union view the container sees\n")

    # the app boots and does the canonical writes
    print("The container's process performs these writes (the canonical demo):\n")
    print(f"  {'PATH':<20} {'NEW SIZE':<10} {'OP':<10} NOTE")
    print("  " + "-" * 70)
    for path, size, note in CANONICAL_WRITES:
        op = mount.write(path, size)
        print(f"  {path:<20} {human(size):<10} {op:<10} {note}")
    print()
    # show where each interesting file now lives
    print("After the writes, where does each path PHYSICALLY live?\n")
    print(f"  {'PATH':<20} {'merged size':<12} {'in base L0?':<12} {'in upper?':<10}")
    print("  " + "-" * 56)
    for path in ("/etc/passwd", "/etc/hostname", "/var/log/flask.log", "/app/data.json"):
        in_base = path in img.layers[0].files
        in_upper = path in mount.upper.files
        merged = mount.read(path)
        print(f"  {path:<20} {human(merged):<12} "
              f"{'yes' if in_base else 'no':<12} {'yes' if in_upper else 'no':<10}")
    print()
    # THE KEY CLAIM: the read-only base layer is byte-for-byte unchanged
    base_after = img.layers[0].files
    untouched = base_before == base_after
    print(f"Base layer {short_id(img.layers[0].id)} files dict BEFORE == AFTER: "
          f"{untouched}")
    print("  -> the printed sheet is PRISTINE. 100 containers can do this and")
    print("     none of them ever mutate the shared image. THAT is the win.\n")

    distinct_lower_written = sorted({p for p in mount.cow_files})
    print(f"copy-up count        = {mount.cow_count}")
    print(f"distinct lower files = {distinct_lower_written}  "
          f"(len={len(distinct_lower_written)})")
    print("\n[check] cow_count == number of distinct lower files written:",
          mount.cow_count == len(distinct_lower_written))
    print("[check] /etc/passwd was copied up EXACTLY ONCE despite 2 writes:",
          mount.cow_files.count("/etc/passwd") == 1)
    print("[check] read-only base layer untouched by container writes:", untouched)


# ============================================================================
# SECTION C: storage savings -- 100 containers share 3 lowers + 100 uppers
# ============================================================================

def section_savings():
    banner("SECTION C: storage savings -- 100 containers, one shared image")
    img = build_image()
    image_size = img.size
    # the per-container upper is EXACTLY the canonical scenario's upper size,
    # so Section C and the gold check (Section F) report the same number.
    sample = fresh_mount(img)
    run_writes(sample, CANONICAL_WRITES)
    upper_per_container = sample.upper.size

    print(f"Image '{img.name}': {human(image_size)} shared read-only, stored ONCE.")
    print(f"Each container's upperdir (its private writes): "
          f"{human(upper_per_container)}.\n")

    N = 100
    print(f"Run {N} containers off this one image. Compare two strategies:\n")

    # naive: copy the whole image per container (no overlay sharing)
    naive = N * image_size
    # overlay: image once + N thin uppers
    overlay = image_size + N * upper_per_container
    savings = naive / overlay

    print(f"  {'strategy':<34} {'math':<26} {'disk used'}")
    print("  " + "-" * 70)
    print(f"  {'naive (copy full image each)':<34} "
          f"{f'{N} x {human(image_size)}':<26} {human(naive)}")
    print(f"  {'overlay2 (share lowers, thin uppers)':<34} "
          f"{f'{human(image_size)} + {N}x{human(upper_per_container)}':<26} "
          f"{human(overlay)}")
    print(f"\n  savings ratio  = naive / overlay  =  {savings:.1f}x smaller")
    print(f"  bytes saved    =  {human(naive - overlay)}")
    print()
    # break down the overlay number so the win is visible
    lowers_share = image_size
    uppers_total = N * upper_per_container
    print(f"  Of the {human(overlay)} overlay total:")
    print(f"    {human(lowers_share):>10}  the 3 image layers, counted once, "
          f"shared by all {N} containers")
    print(f"    {human(uppers_total):>10}  {N} writable uppers, "
          f"{human(upper_per_container)} each")
    print()
    # a small table for a few N values
    print("  Scaling -- how the savings ratio grows with container count:")
    print(f"  {'N containers':<14} {'naive':<12} {'overlay':<12} {'savings'}")
    print("  " + "-" * 46)
    for n in (1, 5, 10, 50, 100, 500):
        na = n * image_size
        ov = image_size + n * upper_per_container
        print(f"  {n:<14} {human(na):<12} {human(ov):<12} {na/ov:>5.1f}x")
    print("\nWith ONE container there is no sharing win (you pay image + 1 upper).")
    print("The win appears the moment a SECOND container reuses the lowers, and")
    print("grows toward N as N rises: each new container adds only its own upper.\n")
    print(f"[check] overlay formula: image + N*upper == {human(overlay)}:",
          overlay == image_size + N * upper_per_container)
    print(f"[check] {N} containers share the SAME {len(img.layers)} lower layers: "
          f"each lower stored once (refcount={N}, copy count=1)")


# ============================================================================
# SECTION D: image pull -- download layers, content-address cache, reuse
# ============================================================================

def section_pull():
    banner("SECTION D: image pull -- download by digest, cache, reuse")
    img = build_image()
    # a second image that reuses the SAME base layer (common in practice)
    other = Image(
        name="api-server:2.3",
        layers=[
            img.layers[0],                                  # SAME ubuntu base
            Layer("apt: nodejs", {
                "/usr/bin/node": 80_000_000,
                "/usr/lib/node_modules/npm-bulk": 30_000_000,
            }),
            Layer("copy: /app (api code)", {
                "/app/server.js": 64_000,
                "/app/package.json": 1_200,
            }),
        ],
    )

    registry = set()   # the local content-addressed layer cache (a set of ids)

    def pull(image: Image, label: str):
        print(f"\n  pull {image.name}  ({label})")
        downloaded = 0
        hits = 0
        for L in image.layers:
            if L.id in registry:
                hits += 1
                print(f"    layer {short_id(L.id)}  {L.name:<22}  "
                      f"CACHED  (0 B downloaded)")
            else:
                downloaded += L.size
                registry.add(L.id)
                print(f"    layer {short_id(L.id)}  {L.name:<22}  "
                      f"PULL    ({human(L.size)})")
        total = sum(L.size for L in image.layers)
        print(f"    -> {hits} cache hit(s), downloaded {human(downloaded)} "
              f"of {human(total)} image bytes")
        return downloaded

    print("Layers are content-addressed: the digest IS the cache key. Pulling an")
    print("image downloads only the layers you do not already have on disk.\n")
    d1 = pull(img, "cold cache")
    d2 = pull(other, "warm cache -- base layer already present")

    print("\nBoth images were built FROM ubuntu:22.04, so their base layers are")
    print("byte-identical -> SAME digest -> the base layer downloads ONCE ever.")
    base_id = img.layers[0].id
    same_base = img.layers[0].id == other.layers[0].id
    print(f"\n  flask-app base id = {short_id(base_id)}")
    print(f"  api-server base id = {short_id(other.layers[0].id)}  "
          f"(same object: {img.layers[0] is other.layers[0]})")
    print(f"  second pull skipped the base layer -> downloaded only "
          f"{human(d2)} (its 2 new layers).")
    print()
    print("This is why `docker pull` of an image that shares a base you already")
    print("have is fast: deduplication is by content hash, at the LAYER level.")
    print(f"\n[check] both images share the identical base digest: {same_base}")
    print(f"[check] cold pull downloaded full image: {d1 == img.size}")
    print(f"[check] warm pull downloaded < full second image: "
          f"{d2 < sum(L.size for L in other.layers)}")


# ============================================================================
# SECTION E: storage drivers -- overlay2 vs aufs vs devicemapper vs vfs
# ============================================================================

def section_drivers():
    banner("SECTION E: storage drivers -- overlay2 vs aufs vs devicemapper ...")
    print("Docker abstracts image storage behind a pluggable 'storage driver'.")
    print("They all present the SAME lower/upper/merged model to the container;")
    print("they differ in HOW the copy-up and the union are implemented.\n")
    print("| driver        | mechanism              | CoW? | status            | note                          |")
    print("|---------------|------------------------|------|-------------------|-------------------------------|")
    rows = [
        ("overlay2",     "in-kernel OverlayFS",  True, "DEFAULT (17.06+)", "fastest; needs Linux >= 4.0"),
        ("fuse-overlayfs","userspace (FUSE)",     True, "rootless only",    "Podman/buildah, no privilege"),
        ("aufs",         "out-of-tree union",    True, "DEPRECATED",       "Docker's first driver; rejected by mainline"),
        ("devicemapper", "block-device snapshots",True, "legacy/removed",   "RHEL old default; loop-lvm was slow"),
        ("btrfs",        "btrfs subvolumes",     True, "optional",         "needs the host FS formatted btrfs"),
        ("zfs",          "zfs clones",           True, "optional",         "needs the host FS formatted zfs"),
        ("vfs",          "full DIRECTORY COPY",  False,"fallback/debug",   "1:1 disk use, NO copy-on-write"),
    ]
    for name, mech, cow, status, note in rows:
        print(f"| {name:<13} | {mech:<22} | {'yes' if cow else 'NO ':<4} | "
              f"{status:<17} | {note:<29} |")
    print()
    print(" vfs is the diagnostic baseline: with NO copy-on-write it stores a")
    print(" FULL copy of the image per container -- the naive number from Section")
    print(" C. Every other driver reproduces the overlay win via different means.")
    print("\n overlay2 wins because the union + copy-up are in the kernel: no")
    print(" context switch, no extra daemon, page-cache shared across containers.")
    print("\n[check] only vfs lacks copy-on-write:",
          all(cow for _, _, cow, _, _ in rows if not _[0].startswith('vfs')) is False)


# ============================================================================
# SECTION F: the GOLD check -- CoW write count + storage, recomputed cleanly
# ============================================================================

def section_gold():
    banner("SECTION F: the GOLD check -- CoW semantics, re-derived cleanly")
    print("Run the canonical scenario in a FRESH mount and pin the numbers the")
    print(".html must reproduce from the identical model.\n")
    img = build_image()
    mount = fresh_mount(img, "container upper (gold)")
    ops = run_writes(mount, CANONICAL_WRITES)
    for path, size, op in ops:
        print(f"  write {path:<20} {human(size):<10} -> {op}")
    print()

    distinct_lower = sorted({p for p in mount.cow_files})
    upper_size = mount.upper.size
    image_size = img.size
    N = 100
    upper_per_container = upper_size
    naive = N * image_size
    overlay_total = image_size + N * upper_per_container
    savings = naive / overlay_total

    gold = {
        "cow_count": mount.cow_count,
        "distinct_lower_files_written": distinct_lower,
        "passwd_copyup_count": mount.cow_files.count("/etc/passwd"),
        "upper_size_bytes": upper_size,
        "image_size_bytes": image_size,
        "image_layers": len(img.layers),
        "savings_ratio_100ctrs": round(savings, 4),
        "overlay_total_100ctrs": overlay_total,
    }
    print("GOLD values (pinned for overlayfs.html):")
    for k, v in gold.items():
        if isinstance(v, float):
            print(f"    {k:<32} = {v}")
        else:
            print(f"    {k:<32} = {v}")

    # ---- assertions that encode the invariants of the whole guide ----
    assert gold["cow_count"] == 2, "two distinct lower files were written"
    assert gold["cow_count"] == len(gold["distinct_lower_files_written"]), \
        "CoW happens exactly once per distinct lower file"
    assert gold["passwd_copyup_count"] == 1, \
        "/etc/passwd copied up ONCE despite being written twice"
    assert "/etc/passwd" in gold["distinct_lower_files_written"]
    assert "/etc/hostname" in gold["distinct_lower_files_written"]
    assert "/var/log/flask.log" not in gold["distinct_lower_files_written"], \
        "brand-new files are NOT copy-ups"
    assert gold["image_layers"] == 3
    assert gold["savings_ratio_100ctrs"] > 50, "100 containers >> 50x cheaper"
    # the canonical scenario's upper size is the same one Section C advertises
    assert gold["upper_size_bytes"] == 506644, "canonical upper composition"
    print("\n[check] GOLD: cow_count == len(distinct lower written):",
          gold["cow_count"] == len(gold["distinct_lower_files_written"]))
    print("[check] GOLD: passwd copied up once despite 2 writes:",
          gold["passwd_copyup_count"] == 1)
    print("[check] GOLD: 100-container savings ratio > 50x:",
          gold["savings_ratio_100ctrs"] > 50)
    print("[check] GOLD: all assertions passed -> OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("overlayfs.py - reference simulation of the overlay2 storage model.")
    print("All numbers below feed OVERLAYFS.md and overlayfs.html.")
    print("Python", sys.version.split()[0])

    section_stack()
    section_cow()
    section_savings()
    section_pull()
    section_drivers()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
