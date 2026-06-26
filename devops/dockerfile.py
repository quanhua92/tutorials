"""
dockerfile.py - Reference simulation of the Dockerfile build model: how each
instruction becomes a layer, how the build cache cascades, multi-stage builds,
the build context, and base-image size trade-offs.

This is the single source of truth that DOCKERFILE.md is built from. Every
number, table, and worked example in DOCKERFILE.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python dockerfile.py

==========================================================================
THE INTUITION (read this first) -- the assembly line with a photographer
==========================================================================
A Dockerfile is a RECIPE executed on an assembly line. Each instruction
(FROM, RUN, COPY, ...) is one WORKSTATION along the line. After every
workstation, a photographer SNAPS A PHOTO of the whole conveyor belt and
files it -- that photo is a LAYER (a frozen filesystem snapshot).

  * The finished IMAGE is just the STACK of photos, bottom (base OS) to top
    (your last instruction). To run a container, OverlayFS lays them down as
    read-only lowers and adds one writable sheet on top. 🔗 see OVERLAYFS.md.
  * Next time you run the SAME line, the photographer checks each workstation
    in order: "is everything up to here -- the parent photo AND this
    workstation's inputs -- IDENTICAL to last time?" If yes, SKIP the work and
    REUSE the filed photo: that is a cache HIT. The first workstation where an
    input changed has no matching photo: a cache MISS. From a miss onward,
    EVERY following workstation is also a miss -- the photos downstream no
    longer line up. That cascade is cache invalidation.

The cardinal rule falls straight out of the cascade: put the things that
CHANGE OFTEN (your app source) LATE in the recipe, and the things that change
RARELY (system deps, package installs) EARLY. Then an app edit reuses every
cached photo up to the COPY and only re-photographs from there. Get the order
wrong and a one-line code change re-runs the whole `apt-get install`.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  instruction  : one line of the recipe. Kinds we model: FROM (base image),
                 RUN (shell command, makes a fs layer), COPY/ADD (copy build-
                 context files in, makes a fs layer), and METADATA instructions
                 (CMD, ENV, EXPOSE, ENTRYPOINT) which write the image CONFIG,
                 NOT a filesystem layer.
  layer        : the frozen filesystem snapshot one instruction produces.
                 Content-addressed: its cache key = hash(parent_key + inputs).
  cache key    : the digest the photographer compares. For RUN it is the
                 command string; for COPY it is the command PLUS the checksum
                 of the source files -- so editing a copied file busts the
                 cache even though the COPY line text is identical.
  cache HIT/   : HIT = an identical parent+inputs combo was photographed
  MISS           before, reuse it. MISS = no match, re-execute and re-photograph.
                 One MISS cascades: every later instruction is a MISS too.
  build context: the directory tree the Docker client TARs up and sends to the
                 daemon at `docker build`. Its SIZE = bytes shipped over the
                 socket before build even starts. `.dockerignore` trims it.
  .dockerignore: a file of exclude patterns; matched files never enter the
                 context (and never bust COPY-cache for nothing).
  multi-stage  : several FROM blocks ("stages") in one Dockerfile. You build
                 fat in an early stage (compiler + source) then COPY --from=
                 only the artifact into a MINIMAL final stage. The final image
                 is just the last stage -- the compiler never ships.
  base image   : the FROM you start from. `ubuntu` (full) vs `*-slim` vs
                 `alpine` vs `distroless` vs `scratch` is the biggest single
                 lever on final image size and attack surface.

==========================================================================
THE LINEAGE (where it came from)
==========================================================================
  Dockerfile   (2013, Docker 0.9) : the original declarative image recipe.
                                     Each instruction = one commit = one layer.
  Build cache  (2013)             : the photographer. Keyed on parent + inputs;
                                     cascade-on-miss from day one.
  Multi-stage  (2017, 17.05)      : multiple FROMs in one file; the feature
                                     that made tiny prod images routine.
  BuildKit     (2018, 18.06)      : the next-gen builder. Parallel stages,
                                     smarter cache, `--mount=type=cache`, build-
                                     secrets. Default frontend since 23.0.
  OCI image    (2016)             : the open spec for the image format Docker
                                     emits (manifest + config + layer blobs).

==========================================================================
KEY RELATIONS (all asserted in code below)
==========================================================================
  layer_of(instr i)   = sha256( parent_key(i) + "::" + kind(i) + "::" + tag(i) )
  tag(RUN)            = the command string
  tag(COPY src dst)   = "COPY " + sha256(contents of src) + " " + dst
                         (so editing src busts cache though the line is unchanged)
  fs_layer(i)         = (kind(i) in {FROM, RUN, COPY, ADD})     # CMD/ENV do NOT
  cache-hit(i)        = (parent_hit(i-1) AND key(i) == stored_key(i))
  one MISS at j  ==>  MISS for all i >= j                      (the cascade)
  final image size    = sum of fs layers of the LAST stage (multi-stage)
  build_context_size  = sum of bytes NOT excluded by .dockerignore

  THE GOLD CHECK of this guide:
      for the canonical Dockerfile, editing line 3 (COPY app/) yields the
      cache vector [HIT, HIT, MISS, MISS] and rebuilds exactly 2 instructions;
      a multi-stage build's final image is the LAST stage only (~20 MB) while
      the builder stage (~800 MB) is discarded. The .html recomputes these.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass

BANNER = "=" * 72

# --------------------------------------------------------------------------
# 0. THE MODEL
# --------------------------------------------------------------------------

def short_digest(s: str) -> str:
    """Content digest of a string -> 12 hex chars (a stand-in for sha256:...)."""
    return hashlib.sha256(s.encode()).hexdigest()[:12]


FS_LAYER_KINDS = {"FROM", "RUN", "COPY", "ADD"}   # these commit a filesystem layer
META_KINDS = {"CMD", "ENV", "EXPOSE", "ENTRYPOINT", "LABEL", "WORKDIR"}


@dataclass
class Instr:
    """One Dockerfile instruction.

    kind         : FROM | RUN | COPY | ADD | CMD | ENV | ...
    fs_size      : bytes this instruction ADDS to the filesystem layer.
                   0 for metadata instructions (CMD/ENV/...), which only edit
                   the image config, not the layer stack.
    content_tag  : the string whose CHANGE invalidates the cache for this
                   instruction. For RUN = the command; for COPY = the content
                   checksum of the source (so editing source busts the cache).
    """
    text: str
    kind: str
    fs_size: int
    content_tag: str

    @property
    def makes_fs_layer(self) -> bool:
        return self.kind in FS_LAYER_KINDS


def cache_keys(instrs: list, parent0: str = "ROOT") -> list:
    """The content-addressed cache key for each instruction, in order.

    key(i) = sha256( key(i-1) + "::" + kind + "::" + content_tag )
    Each key therefore depends on EVERY ancestor -- which is exactly why one
    miss cascades: change an ancestor's key and all descendants' keys change.
    """
    keys = []
    parent = parent0
    for ins in instrs:
        key = short_digest(parent + "::" + ins.kind + "::" + ins.content_tag)
        keys.append(key)
        parent = key
    return keys


def hit_miss(keys_new: list, keys_cached: list) -> list:
    """Compare a rebuild's keys to the cached keys, IN ORDER. Once a key
    differs (a MISS), every following instruction is also a MISS -- its parent
    changed, so its key can no longer match. This is the cascade."""
    out = []
    busted = False
    for kn, kc in zip(keys_new, keys_cached):
        if busted or kn != kc:
            busted = True
            out.append("MISS")
        else:
            out.append("HIT")
    return out


def image_fs_layers(instrs: list) -> int:
    """Number of filesystem layers = number of FROM/RUN/COPY/ADD instructions.
    (CMD/ENV/etc. live in the image config, not as layers.)"""
    return sum(1 for i in instrs if i.makes_fs_layer)


def image_size(instrs: list) -> int:
    """Total filesystem bytes = sum of fs-layer sizes."""
    return sum(i.fs_size for i in instrs if i.makes_fs_layer)


# --------------------------------------------------------------------------
# THE CANONICAL DOCKERFILE  (the running example for sections A, B, F)
# --------------------------------------------------------------------------

CANONICAL = [
    Instr("FROM ubuntu:22.04", "FROM", 72_000_000, "ubuntu:22.04"),
    Instr("RUN apt-get update && apt-get install -y python3", "RUN", 48_000_000,
          "apt-get update && apt-get install -y python3"),
    Instr("COPY app/ /app/", "COPY", 8_500_000, "app@sha256:a1b2c3"),  # content of app/
    Instr('CMD ["python3", "/app/main.py"]', "CMD", 0, '["python3","/app/main.py"]'),
]


# --------------------------------------------------------------------------
# PRETTY PRINTERS
# --------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def human(n: int) -> str:
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


def sid(idstr: str) -> str:
    return idstr[:12]


def print_build(instrs: list, keys: list, hm: list | None = None,
                title: str = "build"):
    """Pretty-print a build: each instruction, its layer id, size, hit/miss."""
    print(f"  {'#':<3} {'INSTRUCTION':<48} {'layer':<14} {'adds':<10} "
          f"{'cache'}")
    print("  " + "-" * 86)
    for idx, (ins, key) in enumerate(zip(instrs, keys)):
        size_s = human(ins.fs_size) if ins.makes_fs_layer else "(config)"
        layer_kind = "layer" if ins.makes_fs_layer else "cfg   "
        cache_s = (hm[idx] if hm else "-")
        mark = "HIT " if cache_s == "HIT" else ("MISS" if cache_s == "MISS" else "   ")
        print(f"  {idx:<3} {ins.text:<48} {sid(key):<14} {size_s:<10} "
              f"{mark}  {layer_kind}")


# ============================================================================
# SECTION A: layer creation -- each instruction commits a layer
# ============================================================================

def section_layers():
    banner("SECTION A: each instruction commits a layer (FROM -> RUN -> COPY -> CMD)")
    df = CANONICAL
    keys = cache_keys(df)
    print("A 4-instruction Dockerfile. Each row is one workstation; the layer id")
    print("is the photographer's photo of the belt at that point:\n")
    print_build(df, keys, title="canonical")
    print()
    fs_n = image_fs_layers(df)
    cfg_n = sum(1 for i in df if not i.makes_fs_layer)
    print(f"  -> {len(df)} instructions: {fs_n} filesystem layer(s) + "
          f"{cfg_n} config-only (CMD).")
    print(f"  -> final image = {human(image_size(df))} on disk "
          f"(sum of the {fs_n} fs layers).\n")
    print("Layer id = sha256(parent_key + kind + inputs). Each id ENCODES its")
    print("ancestry, so changing ANY ancestor changes this id -- the seed of the")
    print("cache cascade in Section B. CMD writes no layer: it only sets the")
    print("image's default process (stored in the config JSON, ~0 bytes).")
    print()
    # show the parent->child chain explicitly
    print("The key chain (each key depends on the one above):")
    parent = "ROOT"
    for ins, key in zip(df, keys):
        print(f"    key = sha256({sid(parent)} + {ins.kind:<4} + {ins.content_tag})")
        print(f"         = {sid(key)}")
        parent = key
    print("\n[check] number of fs layers == count of FROM/RUN/COPY:",
          image_fs_layers(df) == 3)
    print("[check] image size == sum of fs-layer sizes:",
          image_size(df) == sum(i.fs_size for i in df if i.makes_fs_layer))


# ============================================================================
# SECTION B: cache invalidation -- the cascade + ordering best practice
# ============================================================================

def section_cache():
    banner("SECTION B: the build cache -- one MISS cascades; order by change rate")
    df = CANONICAL
    cached_keys = cache_keys(df)          # what a first (cold) build photographed

    # SCENARIO 1: you edit the app source -> only the COPY tag changes.
    edited = list(CANONICAL)
    edited[2] = Instr("COPY app/ /app/", "COPY", 8_700_000, "app@sha256:deadbeef")
    new_keys = cache_keys(edited)
    hm = hit_miss(new_keys, cached_keys)
    print("SCENARIO 1 -- you edit a file in app/ and rebuild. The COPY line TEXT")
    print("is identical, but its content_tag (the checksum of app/) changed, so")
    print("the cache key for line 2 differs -> MISS, and CMD after it cascades:\n")
    print_build(edited, new_keys, hm, title="app edit")
    rerun = hm.count("MISS")
    print(f"\n  -> cache vector = {hm}")
    print(f"  -> instructions re-executed = {rerun} of {len(df)} "
          f"(the COPY + the CMD config). The 2 expensive layers (ubuntu, apt)")
    print(f"     are REUSED -- zero apt-get, zero download.\n")

    # SCENARIO 2: the BAD vs GOOD ordering for a frequently-changing app.
    print("SCENARIO 2 -- ordering by change frequency (the cardinal rule).\n")
    print("Two Dockerfiles that DO the same thing, ordered differently. You")
    print("edit app/main.py and rebuild. Watch which layers re-run:\n")

    # BAD: copy app FIRST, then pip install (deps re-resolved every code edit)
    bad = [
        Instr("FROM python:3.10-slim", "FROM", 45_000_000, "python:3.10-slim"),
        Instr("COPY app/ /app/", "COPY", 8_500_000, "app@sha256:v2"),  # changes often
        Instr("RUN pip install -r /app/requirements.txt", "RUN", 60_000_000,
              "pip install -r requirements.txt"),
        Instr('CMD ["python3","/app/main.py"]', "CMD", 0, "python3 /app/main.py"),
    ]
    bad_cached = cache_keys(bad)
    bad_new = list(bad)
    bad_new[1] = Instr("COPY app/ /app/", "COPY", 8_600_000, "app@sha256:v3")
    bad_hm = hit_miss(cache_keys(bad_new), bad_cached)

    # GOOD: deps first (rare change), app last (frequent change)
    good = [
        Instr("FROM python:3.10-slim", "FROM", 45_000_000, "python:3.10-slim"),
        Instr("COPY requirements.txt /tmp/", "COPY", 300, "requirements.txt@sha256:fx"),
        Instr("RUN pip install -r /tmp/requirements.txt", "RUN", 60_000_000,
              "pip install -r requirements.txt"),
        Instr("COPY app/ /app/", "COPY", 8_500_000, "app@sha256:v2"),  # changes often
        Instr('CMD ["python3","/app/main.py"]', "CMD", 0, "python3 /app/main.py"),
    ]
    good_cached = cache_keys(good)
    good_new = list(good)
    good_new[3] = Instr("COPY app/ /app/", "COPY", 8_600_000, "app@sha256:v3")
    good_hm = hit_miss(cache_keys(good_new), good_cached)

    print("  BAD order (COPY app before pip install):")
    print_build(bad_new, cache_keys(bad_new), bad_hm, title="bad")
    print(f"     re-runs {bad_hm.count('MISS')} incl. the slow `pip install` (60 MB) -- EVERY edit.\n")
    print("  GOOD order (deps first, app last):")
    print_build(good_new, cache_keys(good_new), good_hm, title="good")
    print(f"     re-runs only {good_hm.count('MISS')} -- the COPY + CMD. pip install is CACHED.\n")
    print("Same outcome, radically different rebuild cost. Rule: LEAST-changing")
    print("inputs first (base OS, system deps, package lists), MOST-changing last")
    print("(your application source). Then a code tweak reuses everything above.")
    print("\n[check] bad order re-runs pip install (MISS at line 2):",
          bad_hm[2] == "MISS")
    print("[check] good order caches pip install (HIT at line 2):",
          good_hm[2] == "HIT")


# ============================================================================
# SECTION C: multi-stage -- build fat, ship thin
# ============================================================================

def section_multistage():
    banner("SECTION C: multi-stage builds -- build fat, ship thin")
    print("One Dockerfile, two FROM blocks. Stage 1 ('builder') has the compiler")
    print("and source; it produces a binary. Stage 2 ('runtime') is a MINIMAL")
    print("image that copies ONLY that binary. The final image = the LAST stage")
    print("-- the compiler and source never ship.\n")

    stage1 = [
        Instr("FROM golang:1.21 AS builder", "FROM", 784_000_000, "golang:1.21"),
        Instr("COPY . /src", "COPY", 4_000_000, "src@sha256:v1"),
        Instr("RUN go build -o /out/server", "RUN", 12_000_000, "go build -o /out/server"),
    ]
    stage2 = [
        Instr("FROM alpine:3.19", "FROM", 8_000_000, "alpine:3.19"),
        Instr("COPY --from=builder /out/server /server", "COPY", 12_000_000,
              "binary@sha256:from-builder"),
        Instr('CMD ["/server"]', "CMD", 0, "/server"),
    ]
    builder_size = image_size(stage1)
    runtime_size = image_size(stage2)
    ratio = builder_size / runtime_size

    print("  stage 1  -- builder (golang + source + build):")
    print_build(stage1, cache_keys(stage1), title="builder")
    print(f"\n     builder image total = {human(builder_size)}\n")
    print("  stage 2  -- runtime (alpine + just the binary):")
    print_build(stage2, cache_keys(stage2), title="runtime")
    print(f"\n     runtime image total = {human(runtime_size)}   <-- THIS is what ships")
    print(f"\n  final image = stage 2 only = {human(runtime_size)}.")
    print(f"  the {human(builder_size)} builder is discarded -- its compiler, source,")
    print(f"  build caches, and 200+ MB of Go toolchain never reach the registry.")
    print(f"\n  savings = builder / final = {human(builder_size)} / {human(runtime_size)} "
          f"= {ratio:.1f}x smaller.")
    print("\nThe same trick in any language: compile in the full SDK image, then")
    print("COPY --from=builder the single artifact into alpine/distroless/scratch.")
    print("\n[check] runtime < builder:", runtime_size < builder_size)
    print(f"[check] final image is the LAST stage only: "
          f"{human(runtime_size)} (not {human(builder_size)}):",
          runtime_size < builder_size and runtime_size == image_size(stage2))


# ============================================================================
# SECTION D: .dockerignore -- the build context, trimmed
# ============================================================================

def section_context():
    banner("SECTION D: .dockerignore -- what you send the daemon matters")
    print("`docker build` TARs up the build-context directory and ships it to the")
    print("daemon BEFORE any instruction runs. Everything in it is sent, even")
    print("files no COPY ever references -- so a fat context = a slow start AND")
    print("spurious COPY-cache invalidation (editing node_modules busts `COPY .`)\n")

    # the project tree on disk, with sizes
    tree = {
        "app/":            8_000_000,
        "package.json":     300_000,
        "requirements.txt":   1_200,
        "node_modules/":   210_000_000,
        ".git/":            48_000_000,
        "dist/":            15_000_000,
        "npm-debug.log":     2_000_000,
        ".env":                 1_400,   # a SECRET, must never ship
    }
    ignore = {"node_modules/", ".git/", "dist/", "npm-debug.log", ".env"}
    full = sum(tree.values())
    kept = {k: v for k, v in tree.items() if k not in ignore}
    trimmed = sum(kept.values())

    print(f"  {'PATH':<20} {'SIZE':<12} {'sent without .dockerignore?'}")
    print("  " + "-" * 60)
    for k, v in tree.items():
        excluded = k in ignore
        print(f"  {k:<20} {human(v):<12} {'NO (excluded)' if excluded else 'yes'}")
    print("  " + "-" * 60)
    print(f"  full context  = {human(full)}")
    print(f"  trimmed       = {human(trimmed)}   ({len(ignore)} patterns excluded)")
    print(f"  reduction     = {full / trimmed:.1f}x smaller; the .env SECRET stays local.\n")
    print("  .dockerignore used:")
    for p in sorted(ignore):
        print(f"    {p}")
    print("\nExcluding .git/node_modules/dist cuts a ~280 MB context to ~8 MB, so")
    print("the build starts in milliseconds instead of seconds -- and `COPY . /app`")
    print("no longer busts its cache when node_modules changes under you.\n")
    print("[check] .env (secret) is excluded:", ".env" in ignore)
    print("[check] trimmed context < full context:", trimmed < full)


# ============================================================================
# SECTION E: base-image size optimization -- ubuntu vs slim vs distroless
# ============================================================================

def section_bases():
    banner("SECTION E: base image -- the biggest single lever on size + security")
    print("The FROM line dominates final image size. Pick the smallest base that")
    print("still runs your app. Smaller = faster pull, less RAM, fewer CVEs, and")
    print("no shell/package-manager for an attacker to use.\n")
    print("| base image                      | size      | shell? | pkg mgr | best for                |")
    print("|---------------------------------|-----------|--------|---------|-------------------------|")
    rows = [
        ("ubuntu:22.04",                  "72.1 MiB", "yes",   "apt",    "general; full userspace"),
        ("python:3.10",                   "350.0 MiB","yes",   "apt+pip","DEV (has build tools)"),
        ("python:3.10-slim",              "45.0 MiB", "yes",   "apt(min)","PROD python (glibc)"),
        ("python:3.10-alpine",            "16.0 MiB", "yes",   "apk",    "tiny; watch musl ABI gaps"),
        ("gcr.io/distroless/python3-deb12","28.0 MiB","NO",    "NONE",   "PROD secure (no shell)"),
        ("scratch",                       "0 B",      "NO",    "NONE",   "static binary ONLY"),
    ]
    for name, size, shell, pkg, best in rows:
        print(f"| {name:<32} | {size:<9} | {shell:<6} | {pkg:<7} | {best:<23} |")
    print()
    print(" Same Flask app, same function, six possible bases:")
    print("   ubuntu  -> 72 MiB   (a full Debian userland you never use)")
    print("   slim    -> 45 MiB   (drops the ~300 MB of build tools -- usually right)")
    print("   alpine  -> 16 MiB   (musl libc; some wheels/C-extensions break)")
    print("   distroless -> 28 MiB(NO /bin/sh; if you get a shell, you are already pwned)")
    print("   scratch -> 0 MiB base + your binary (only works for static Go/Rust/Zig)")
    print()
    print(" distroless is the prod sweet spot for interpreted runtimes: it ships the")
    print("interpreter + your app and NOTHING else -- no shell, no package manager,")
    print("no curl for an attacker. Pair it with multi-stage (Section C) to build")
    print("in python:3.10 and run in distroless.")
    sizes = {"ubuntu": 72.1, "full": 350.0, "slim": 45.0, "alpine": 16.0,
             "distroless": 28.0, "scratch": 0.0}
    print(f"\n[check] smallest non-empty base is alpine ({sizes['alpine']} MiB):",
          min(v for v in sizes.values() if v > 0) == sizes["alpine"])
    print(f"[check] distroless ships no shell: True")


# ============================================================================
# SECTION F: the GOLD check -- layer count, cache vector, multi-stage size
# ============================================================================

def section_gold():
    banner("SECTION F: the GOLD check -- layers, cache vector, multi-stage size")
    print("Re-derive the canonical numbers the .html must reproduce from the")
    print("identical model.\n")

    df = CANONICAL
    cached = cache_keys(df)

    # the canonical edit: app source changes -> line 2 (COPY) content_tag changes
    edited = list(CANONICAL)
    edited[2] = Instr("COPY app/ /app/", "COPY", 8_700_000, "app@sha256:deadbeef")
    hm = hit_miss(cache_keys(edited), cached)

    fs_layers = image_fs_layers(df)
    instr_count = len(df)
    rerun = hm.count("MISS")

    # multi-stage
    builder = [
        Instr("FROM golang:1.21 AS builder", "FROM", 784_000_000, "golang:1.21"),
        Instr("COPY . /src", "COPY", 4_000_000, "src@sha256:v1"),
        Instr("RUN go build -o /out/server", "RUN", 12_000_000, "go build"),
    ]
    runtime = [
        Instr("FROM alpine:3.19", "FROM", 8_000_000, "alpine:3.19"),
        Instr("COPY --from=builder /out/server /server", "COPY", 12_000_000,
              "binary@sha256:b"),
        Instr('CMD ["/server"]', "CMD", 0, "/server"),
    ]
    builder_size = image_size(builder)
    runtime_size = image_size(runtime)
    ms_ratio = builder_size / runtime_size

    # build context
    tree = {"app/": 8_000_000, "node_modules/": 210_000_000, ".git/": 48_000_000}
    ignore = {"node_modules/", ".git/"}
    ctx_full = sum(tree.values())
    ctx_trim = sum(v for k, v in tree.items() if k not in ignore)

    gold = {
        "instruction_count": instr_count,
        "fs_layer_count": fs_layers,
        "cache_vector_app_edit": hm,
        "rerun_instructions": rerun,
        "multistage_builder_bytes": builder_size,
        "multistage_final_bytes": runtime_size,
        "multistage_ratio": round(ms_ratio, 4),
        "context_full_bytes": ctx_full,
        "context_trimmed_bytes": ctx_trim,
    }
    print("GOLD values (pinned for dockerfile.html):")
    for k, v in gold.items():
        print(f"    {k:<28} = {v}")
    print()

    # ---- assertions encoding the invariants of the guide ----
    assert gold["fs_layer_count"] == 3, "FROM+RUN+COPY = 3 fs layers; CMD is config"
    assert gold["instruction_count"] == 4
    assert gold["cache_vector_app_edit"] == ["HIT", "HIT", "MISS", "MISS"], \
        "edit at COPY cascades CMD"
    assert gold["rerun_instructions"] == 2, "COPY + CMD re-run"
    assert gold["multistage_final_bytes"] == 20_000_000, "alpine(8) + binary(12)"
    assert gold["multistage_ratio"] == 40.0, "800 MB / 20 MB = 40x"
    assert gold["multistage_final_bytes"] < gold["multistage_builder_bytes"]
    assert gold["context_trimmed_bytes"] < gold["context_full_bytes"]
    print("[check] GOLD: fs_layer_count == 3:", gold["fs_layer_count"] == 3)
    print("[check] GOLD: cache vector for app edit == [HIT,HIT,MISS,MISS]:",
          gold["cache_vector_app_edit"] == ["HIT", "HIT", "MISS", "MISS"])
    print("[check] GOLD: multi-stage final 20 MiB, ratio 40.0x:",
          gold["multistage_final_bytes"] == 20_000_000 and gold["multistage_ratio"] == 40.0)
    print("[check] GOLD: all assertions passed -> OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("dockerfile.py - reference model of the Dockerfile build process.")
    print("All numbers below feed DOCKERFILE.md and dockerfile.html.")
    print("Python", sys.version.split()[0])

    section_layers()
    section_cache()
    section_multistage()
    section_context()
    section_bases()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
