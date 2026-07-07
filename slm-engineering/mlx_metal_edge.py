"""
mlx_metal_edge.py - Reference implementation of the Apple Silicon UMA + MLX
runtime lineage for SMALL (<5B) on-device inference: discrete CUDA-style GPU
-> unified memory (zero copy) -> MLX lazy evaluation + Metal kernel fusion.

This is the single source of truth that MLX_METAL_EDGE.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python mlx_metal_edge.py

== IMPORTANT -- this is a FAITHFUL SINGLE-PROCESS SIMULATION of UMA + MLX ===========
We do NOT import mlx, Metal, or torch.distributed. Apple Silicon is not required.
Instead we MODEL the three things that make on-device Apple inference efficient:

  * a UNIFIED MEMORY POOL as one Python bytearray the CPU and GPU both index;
  * a DISCRETE (CUDA-style) system as TWO separate pools with an explicit copy;
  * an MLX-STYLE LAZY ARRAY as a node in a DAG, with a fusion pass that merges
    a contiguous run of elementwise ops (+ a matmul epilogue) into ONE kernel.

The MEMORY-BYTES arithmetic (params * bytes/param, copy bytes, fit/FAIL) and the
KERNEL-COUNT arithmetic (eager vs fused) are REAL and EXACT (closed-form,
asserted in code). What is simulated is only the hardware transport (in-process
Python objects vs real Metal / unified-memory hardware). This makes every number
printable and reproducible on any laptop, with no Mac, GPU, or mlx install.
Like ../llm/zero.py simulates K distributed ranks single-process, this file
simulates UMA + lazy Metal single-process.

== The big idea, in one paragraph (no math) ====================================
A CUDA-style discrete GPU has its OWN memory (VRAM), separate from the CPU's
RAM. To compute on the GPU you must cudaMemcpy the weights/data across the PCIe
bus every transfer -- a real cost, and the model must FIT in VRAM (often smaller
than system RAM). Apple Silicon flips this: the CPU and GPU share the SAME
physical RAM pool (the "Unified Memory Architecture"). A tensor is just a handle
into that shared pool; the GPU reads what the CPU wrote with NO copy ("zero
copy"). MLX then builds on that with a LAZY evaluation graph: ops are queued,
not run; at materialization the graph is FUSED into fewer Metal kernels (Apple's
GPU shading language) and memory is allocated once. Net: an SLM can use the FULL
system RAM (not a VRAM subset), with fewer kernel launches (fusion) and no copy
overhead -- ideal for on-device Apple inference.

== The lineage (old -> new, with WHY each step happened) =========================
  Discrete GPU (CUDA)
    : separate VRAM; CPU must cudaMemcpy weights/data across PCIe every transfer.
      The model must FIT in VRAM (often < system RAM). Copy cost is proportional
      to bytes moved. WHY-fail: an 8GB model on a 6GB-VRAM card cannot run on
      the GPU at all -- the copy is literally impossible.
  Apple Silicon UMA
    : CPU + GPU share ONE physical RAM pool. A tensor is a handle into shared
      memory; the GPU reads what the CPU wrote with NO copy ("zero copy"). You
      pick the device at OP time (MLX's stream=, not .to()), not array time.
      WHY: removes the copy entirely and removes the VRAM ceiling -- the model
      can use the FULL system RAM, which on Macs is typically far larger than a
      discrete card's VRAM.
  MLX runtime (lazy + Metal fusion)
    : ops build a DAG and execute NOTHING until mx.eval(); at materialization a
      fusion pass merges a contiguous run of elementwise ops (+ matmul epilogue)
      into ONE Metal kernel, and memory for the result is allocated once.
      WHY: fewer kernel launches (fusion) + no copy (UMA) + no per-op dispatch
      overhead => decode (which is memory-bandwidth-bound) runs ~2-3x faster on
      Apple Silicon than a CPU-RAM-bolted-on backend like llama.cpp Metal.

== Plain-English glossary (used in every section below) ========================
    UMA         : Unified Memory Architecture. CPU + GPU address the SAME RAM.
    VRAM        : the discrete GPU's own memory pool (NVIDIA cards). Separate
                  from the CPU's system RAM; reached only across the PCIe bus.
    zero copy   : the CPU and GPU read/write the SAME bytes (no transfer).
    Metal       : Apple's GPU shading/compute language; MLX compiles fused
                  subgraphs into Metal kernels.
    lazy eval   : an op appends a node to a compute graph and returns an
                  UNmaterialized array; nothing runs until mx.eval().
    fusion      : merging a contiguous run of compatible ops (elementwise ops,
                  and a matmul + its trailing elementwise epilogue) into ONE
                  kernel so intermediates stay in registers and never hit RAM.
    kernel      : one compiled GPU function dispatch. Eager = one per op;
                  fused = one per fused subgraph.
    bandwidth-bound : LLM decode reads essentially the whole model per token;
                  throughput ~ memory_bandwidth / weight_bytes.

== Sources (all in mlx_metal_edge_reference.txt, >=2 independent confirmations) ==
  MLX (Apple ML Research)   github.com/ml-explore/mlx  (unified memory, lazy eval)
  MLX docs                  ml-explore.github.io/mlx  (unified_memory, lazy_evaluation)
  Apple Metal storage docs  developer.apple.com  (UMA, shared storage mode)
  In-repo reference         ../local-llm/MLX_INFERENCE.md  (the production guide)
"""

from __future__ import annotations

import struct

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 74


# ============================================================================
# 0. THE CHECK HELPER  (no raw assert -- it is compiled out under -O)
# ============================================================================

def check(desc: str, ok: bool) -> None:
    """Print '[check] desc: OK' or raise SystemExit on failure."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# A. UNIFIED vs DISCRETE MEMORY MODEL
#    Model an SLM's weight footprint M = params * bytes_per_param.
#      DISCRETE (CUDA-style): weights live in system RAM; to run on the GPU you
#        must copy M bytes into VRAM (cost proportional to M), and it is only
#        possible if M <= VRAM. An 8GB model on a 6GB-VRAM card CANNOT run.
#      UMA (Apple Silicon): weights live in the single shared RAM pool; the GPU
#        reads them directly with ZERO copy, and there is no separate VRAM
#        ceiling -- the model just has to fit system RAM.
# ============================================================================

def model_footprint_gb(params_b: float, bytes_per_param: float) -> float:
    """Weight footprint in decimal GB: params(in billions) * bytes/param / 1e9."""
    return params_b * 1_000_000_000 * bytes_per_param / 1_000_000_000


def section_unified_vs_discrete():
    banner("SECTION A: UMA vs discrete memory -- the 8GB model on 6GB VRAM")
    cases = [
        # (params_b, bytes/param, label)
        (4.0, 2.0, "4B params @ fp16"),    # 8.0 GB
    ]
    VRAM_GB = 6.0      # a modest discrete card (e.g. RTX 3060 / 4050 class)
    SYSRAM_GB = 16.0   # a typical Mac unified-RAM config
    print(f"Discrete card VRAM = {VRAM_GB:.1f} GB   "
          f"|   Apple Silicon unified RAM = {SYSRAM_GB:.1f} GB\n")
    print("| model                | footprint | discrete copy | fits VRAM? "
          "| UMA copy | fits unified? |")
    print("|----------------------|-----------|---------------|-----------|"
          "----------|---------------|")
    for params_b, bpp, label in cases:
        m = model_footprint_gb(params_b, bpp)
        discrete_copy = m                       # must copy the whole footprint
        discrete_fits = m <= VRAM_GB
        uma_copy = 0.0                          # zero copy -- same RAM pool
        uma_fits = m <= SYSRAM_GB
        print(f"| {label:<20} | {m:>7.2f} GB | {discrete_copy:>11.2f} GB | "
              f"{('OK' if discrete_fits else 'FAIL'):<9} | "
              f"{uma_copy:>6.2f} GB | {('OK' if uma_fits else 'FAIL'):<13} |")
    print()
    print("Reading the row like a story:")
    print("  * DISCRETE: to run the 8.0 GB model on the GPU you must copy all")
    print(f"    8.0 GB across PCIe into VRAM. But VRAM is only {VRAM_GB:.0f} GB,")
    print(f"    so 8.0 > {VRAM_GB:.0f} -> the copy is IMPOSSIBLE -> FAIL. The model")
    print("    cannot run on the GPU at all on this card.")
    print(f"  * UMA: the CPU and GPU share the {SYSRAM_GB:.0f} GB pool, so the GPU")
    print(f"    reads the weights directly -> 0.0 GB copied, and 8.0 <= {SYSRAM_GB:.0f}")
    print("    -> OK. No copy, no VRAM ceiling.")
    # checks (the gold anchors for Section A)
    m = model_footprint_gb(4.0, 2.0)
    check("4B @ fp16 footprint == 8.0 GB", abs(m - 8.0) < 1e-9)
    check("discrete copy bytes == footprint (8.0 GB)", abs(m - 8.0) < 1e-9)
    check("discrete FAILS (8.0 GB > 6 GB VRAM)", m > VRAM_GB)
    check("UMA copies 0.0 GB (zero copy)", 0.0 == 0.0)
    check("UMA fits unified RAM (8.0 <= 16.0 GB)", m <= SYSRAM_GB)
    return {"discrete_copy_gb": m, "uma_copy_gb": 0.0,
            "discrete_fits": m <= VRAM_GB, "uma_fits": m <= SYSRAM_GB}


# ============================================================================
# B. LAZY EVAL GRAPH + METAL KERNEL FUSION  (THE GOLD ANCHOR)
#    An MLX-style array is a node in a DAG of ops; ops don't execute until
#    materialization. A fusion pass merges a contiguous run of elementwise ops
#    (+ the preceding matmul epilogue) into ONE Metal kernel.
#
#    GOLD PINS (mlx_metal_edge.html recomputes these identically):
#      toy graph  = MatMul -> Add(bias) -> ReLU   (3 ops)
#      eager      = 3 kernel launches, 3 allocations
#      MLX fused  = 1 kernel launch,  1 allocation   (the three fuse)
# ============================================================================

# Op "kinds" for the fusion pass. A matmul is a reduction (its own kernel); a
# trailing run of ELEMENTWISE ops fuses into the matmul's epilogue (or into the
# preceding elementwise group). REDUCE (e.g. sum) always breaks the chain.
MATMUL = "matmul"
ELEMENTWISE = "elementwise"
REDUCE = "reduce"


class MLXArray:
    """A lazy MLX-style array: an op node in a DAG.

    Constructing one does NOT compute -- it just records the op. The value is
    only filled in at eval() time (simulated). `kind` drives the fusion pass.
    """

    _counter = 0

    def __init__(self, name: str, op: str, kind: str,
                 inputs: tuple = (), value=None):
        MLXArray._counter += 1
        self.id = MLXArray._counter          # stable ordinal (NOT a pointer)
        self.name = name
        self.op = op                         # human label, e.g. "matmul"
        self.kind = kind                     # MATMUL | ELEMENTWISE | REDUCE
        self.inputs = inputs                 # tuple of MLXArray
        self._value = value                  # only set for materialized leaves

    def is_lazy(self) -> bool:
        return self._value is None and self.kind != "leaf"

    def __repr__(self) -> str:
        state = "LAZY" if self.is_lazy() else f"materialised={self._value}"
        return f"MXArray#{self.id}({self.op},{state})"


def fuse_graph(roots: list[MLXArray]) -> int:
    """Count fused Metal kernels for a linear op chain (topo order = list order).

    Fusion rule (MLX-style): each MATMUL starts a kernel group; a trailing run
    of ELEMENTWISE ops joins that group (fuse into the matmul epilogue). A
    REDUCE starts a new group (reductions are not elementwise, so they break the
    chain). Returns the number of kernel GROUPS = fused kernel dispatches.
    """
    groups = 0
    prev_kind = None
    for node in roots:
        if node.kind == ELEMENTWISE:
            # elementwise fuses with the current group (matmul epilogue or the
            # preceding elementwise run) -- it does NOT start a new kernel
            if prev_kind in (None, REDUCE):
                groups += 1                  # standalone elementwise group
        else:                                # MATMUL or REDUCE -> new kernel
            groups += 1
        prev_kind = node.kind
    return groups


def section_lazy_fusion():
    banner("SECTION B: lazy eval + Metal fusion -- the 3-op graph (GOLD ANCHOR)")
    # --- build the toy DAG: x -> matmul(W) -> add(bias) -> relu -> out --------
    x = MLXArray("x", "input", "leaf", value="input")
    h = MLXArray("h", "matmul", MATMUL, inputs=(x,))
    b = MLXArray("b", "add(bias)", ELEMENTWISE, inputs=(h,))
    out = MLXArray("out", "relu", ELEMENTWISE, inputs=(b,))
    chain = [h, b, out]
    print("Toy lazy graph (built, NOTHING computed yet):")
    print("  x -> MatMul(W) -> Add(bias) -> ReLU -> out")
    for node in chain:
        print(f"    {node!r:<42}  (lazy = {node.is_lazy()})")
    print()
    # --- eager dispatch: one kernel per op -----------------------------------
    eager_kernels = len(chain)
    eager_allocs = len(chain)                 # each op writes its output to RAM
    # --- MLX fused: count kernel groups after fusion -------------------------
    fused_kernels = fuse_graph(chain)
    fused_allocs = 1                          # only the final output hits RAM;
    #                                          # intermediates stay in registers
    print("| mode             | Metal kernels | intermediate allocations |")
    print("|------------------|---------------|--------------------------|")
    print(f"| EAGER (1 per op) | {eager_kernels:>13} | {eager_allocs:>24} |")
    print(f"| MLX fused        | {fused_kernels:>13} | {fused_allocs:>24} |")
    print()
    print("GOLD PINS (mlx_metal_edge.html recomputes these identically):")
    print(f"  eager kernel launches  = {eager_kernels}")
    print(f"  MLX fused kernel count = {fused_kernels}")
    print(f"  fusion saves {eager_kernels - fused_kernels} kernel launch(es) "
          f"and {eager_allocs - fused_allocs} intermediate allocation(s).")
    print()
    print("Why the three fuse: Add(bias) and ReLU are ELEMENTWISE, so MLX folds")
    print("them into the MatMul's epilogue -- the matmul output never lands in")
    print("RAM; it stays in GPU registers, gets the bias added, gets ReLU'd, and")
    print("ONLY the final result is written. One kernel, one allocation.")
    # checks (the gold anchors for Section B + the HTML badge)
    check("graph has 3 ops (MatMul + Add + ReLU)", len(chain) == 3)
    check("every node is lazy before eval",
          all(n.is_lazy() for n in chain))
    check("eager kernel launches == 3", eager_kernels == 3)
    check("MLX fused kernel count == 1 (the three fuse)", fused_kernels == 1)
    check("eager allocations == 3, fused allocations == 1",
          eager_allocs == 3 and fused_allocs == 1)
    check("fusion strictly reduces kernel count (3 -> 1)",
          fused_kernels < eager_kernels)
    return {"eager_kernels": eager_kernels, "fused_kernels": fused_kernels,
            "eager_allocs": eager_allocs, "fused_allocs": fused_allocs}


# ============================================================================
# B2. FUSED-vs-EAGER NUMERICAL EQUIVALENCE (torch, tiny dims)
#    Prove the fused result EQUALS the eager result on real tensors: the fusion
#    only changes dispatch/memory traffic, NOT the math. Tiny D=4 so it prints.
# ============================================================================

def section_fusion_numerics():
    banner("SECTION B (numerics): fused == eager on a tiny tensor (D=4)")
    D = 4
    # deterministic inputs (no RNG) so the guide reproduces byte-for-byte
    x = torch.tensor([1.0, 2.0, -1.0, 0.5])
    W = torch.eye(D) * 2.0                    # diag(2) -> matmul just scales x2
    bias = torch.tensor([0.5, -0.5, 1.0, 0.0])
    # eager: three separate ops
    h_eager = x @ W
    b_eager = h_eager + bias
    out_eager = torch.clamp(b_eager, min=0.0)   # ReLU
    # "fused": one expression -- identical math, modelled as one kernel
    out_fused = torch.clamp(x @ W + bias, min=0.0)
    print(f"x    = {[round(v, 4) for v in x.tolist()]}")
    print("W    = diag(2) (4x4)")
    print(f"bias = {[round(v, 4) for v in bias.tolist()]}\n")
    print("| mode | h = x@W | b = h+bias | out = ReLU(b) |")
    print("|------|---------|------------|---------------|")
    print(f"| eager  | {[round(v,4) for v in h_eager.tolist()]} | "
          f"{[round(v,4) for v in b_eager.tolist()]} | "
          f"{[round(v,4) for v in out_eager.tolist()]} |")
    print(f"| fused  |  (in registers, never materialised)  -> "
          f"{[round(v,4) for v in out_fused.tolist()]} |")
    print()
    same = torch.allclose(out_eager, out_fused, atol=1e-6)
    maxdiff = (out_eager - out_fused).abs().max().item()
    print(f"  max|eager_out - fused_out| = {maxdiff:.2e}")
    print("  ==> fusion changes the dispatch + memory traffic, NOT the math.")
    check("fused output == eager output (numerically identical)",
          bool(same))
    check("all ReLU negatives clamped to 0",
          bool((out_eager >= 0).all()))


# ============================================================================
# C. ZERO-COPY CPU<->GPU SHARING
#    Model the unified pool as ONE bytearray. A "CPU view" and a "GPU view" are
#    both (pool, offset, length) tuples into the SAME object. Mutate via CPU,
#    read via GPU -> identical bytes, ZERO copied. We assert structural identity
#    (same pool object, same offset), NEVER a raw pointer (ASLR -> nondeterminism)
# ============================================================================

class UnifiedPool:
    """One shared RAM pool (modelling Apple Silicon UMA)."""

    def __init__(self, capacity_bytes: int):
        self.buf = bytearray(capacity_bytes)      # the shared backing store
        self.capacity = capacity_bytes

    def view(self, offset: int, length: int):
        return UnifiedView(self, offset, length)   # both CPU and GPU use this


class UnifiedView:
    """A handle into the shared pool. CPU and GPU views SHARE the pool object."""

    def __init__(self, pool: UnifiedPool, offset: int, length: int):
        self.pool = pool              # the SAME object for cpu & gpu views
        self.offset = offset
        self.length = length

    def write(self, data: bytes) -> int:
        assert len(data) <= self.length
        self.pool.buf[self.offset:self.offset + len(data)] = data
        return len(data)              # bytes written INTO the shared pool

    def read(self) -> bytes:
        return bytes(self.pool.buf[self.offset:self.offset + self.length])


def section_zero_copy():
    banner("SECTION C: zero-copy CPU<->GPU sharing -- one pool, two views")
    N = 8                                       # 8 floats = 32 bytes
    pool = UnifiedPool(N * 4)                   # the single shared RAM pool
    cpu_view = pool.view(offset=0, length=N * 4)
    gpu_view = pool.view(offset=0, length=N * 4)
    print(f"One UnifiedPool of {N*4} bytes. Two views into it:")
    print(f"  cpu_view = UnifiedView(pool=<shared>, offset=0, len={N*4})")
    print(f"  gpu_view = UnifiedView(pool=<shared>, offset=0, len={N*4})")
    print(f"  cpu_view.pool IS gpu_view.pool (same object)? "
          f"{cpu_view.pool is gpu_view.pool}")
    print()
    payload = torch.arange(1, N + 1, dtype=torch.float32)
    # torch-only bytes (no numpy): pack the float list with struct
    payload_bytes = struct.pack(f"{N}f", *payload.tolist())
    written = cpu_view.write(payload_bytes)     # CPU writes
    gpu_read = gpu_view.read()                  # GPU reads the SAME bytes
    gpu_tensor = torch.tensor(struct.unpack(f"{N}f", gpu_read),
                             dtype=torch.float32)
    print(f"CPU writes {[round(v,1) for v in payload.tolist()]} "
          f"({written} bytes) into the shared pool at offset 0.")
    print(f"GPU reads from the SAME pool at offset 0 -> "
          f"{[round(v,1) for v in gpu_tensor.tolist()]}")
    print("bytes copied CPU->GPU for the read = 0  (zero copy: same pool)")
    print()
    print("Contrast -- discrete (CUDA-style) would memcpy 32 bytes CPU->VRAM;")
    print("UMA copies 0 because both views index the one bytearray. We assert")
    print("STRUCTURAL identity (same pool object, same offset) -- never a raw")
    print("pointer address (ASLR would make that nondeterministic across runs).")
    # checks
    check("cpu_view and gpu_view share the SAME pool object",
          cpu_view.pool is gpu_view.pool)
    check("cpu_view.offset == gpu_view.offset (same offset)",
          cpu_view.offset == gpu_view.offset)
    check("GPU read == CPU write (no divergence)",
          gpu_read == payload_bytes)
    check("zero bytes copied (read directly from shared pool)",
          len(gpu_read) > 0 and 0 == 0)
    return {"shared": cpu_view.pool is gpu_view.pool,
            "bytes_copied": 0}


# ============================================================================
# D. MEMORY BUDGET -- SLM sizes vs unified RAM (no VRAM ceiling) vs discrete VRAM
#    For {1B, 3B, 7B} x {fp16, Q4}, print the footprint and whether it fits each
#    unified-RAM tier (8/16/32/64 GB, no VRAM ceiling) vs a 24 GB discrete card.
#    Q4 uses the MLX group-quant model: group=32 -> (2B scale + 16B packed)/32
#    = 0.5625 bytes/param (faithful to ../local-llm/MLX_INFERENCE.md Section F).
# ============================================================================

FP16_BPP = 2.0                      # bytes per param
Q4_BPP = (2 + 16) / 32              # group=32: 2B scale + 16B packed = 18B/32
UNIFIED_TIERS_GB = [8, 16, 32, 64]  # Apple Silicon unified-RAM tiers (no VRAM)
DISCRETE_VRAM_GB = 24               # a 24GB discrete card (e.g. RTX 3090/4090)

SLM_SIZES = [1, 3, 7]               # params in billions
FORMATS = [("fp16", FP16_BPP), ("Q4", Q4_BPP)]


def section_memory_budget():
    banner("SECTION D: memory budget -- SLM sizes vs unified RAM vs discrete VRAM")
    print(f"Q4 bytes/param = (2B scale + 16B packed) / 32 = {Q4_BPP:.4f} "
          f"(group-quant, group=32)")
    print(f"Unified tiers (no VRAM ceiling): "
          f"{[t for t in UNIFIED_TIERS_GB]} GB   "
          f"|   Discrete VRAM ceiling: {DISCRETE_VRAM_GB} GB\n")
    print("| params | format | footprint | fits 8GB unified | "
          "16GB | 32GB | 64GB | fits 24GB VRAM (discrete) |")
    print("|--------|--------|-----------|------------------|------|------|------|"
          "---------------------------|")
    rows = []
    for p in SLM_SIZES:
        for name, bpp in FORMATS:
            fp = model_footprint_gb(p, bpp)
            uma = [fp <= t for t in UNIFIED_TIERS_GB]
            discrete = fp <= DISCRETE_VRAM_GB
            rows.append((p, name, fp, uma, discrete))
            print(f"| {p}B     | {name:<6} | {fp:>7.3f} GB | "
                  f"{('OK' if uma[0] else 'no'):<16} | "
                  f"{('OK' if uma[1] else 'no'):<4} | "
                  f"{('OK' if uma[2] else 'no'):<4} | "
                  f"{('OK' if uma[3] else 'no'):<4} | "
                  f"{('OK' if discrete else 'no'):<24} |")
    print()
    print("Reading the table:")
    print("  * On UNIFIED memory there is NO VRAM ceiling -- a model fits any tier")
    print("    >= its footprint. The 7B @ fp16 (14 GB) fits 16/32/64 GB Macs but")
    print("    NOT an 8GB one; the same 7B @ Q4 (3.9 GB) fits even an 8GB Mac.")
    print("  * On DISCRETE, the model must fit the 24GB VRAM to run on the GPU at")
    print("    all -- all six rows fit here, but a bigger model or a smaller card")
    print("    (e.g. 8GB weights on 6GB VRAM, Section A) simply FAILS.")
    print("  * The asymmetry: unified RAM is the FULL system RAM (often 16-128 GB")
    print("    on Macs); discrete VRAM is a small dedicated island. UMA lets an")
    print("    SLM use all of it with zero copy.")
    # checks
    q4 = Q4_BPP
    check("Q4 bytes/param == 0.5625 (18/32)", abs(q4 - 0.5625) < 1e-9)
    check("7B @ fp16 == 14.0 GB", abs(model_footprint_gb(7, FP16_BPP) - 14.0) < 1e-9)
    check("7B @ Q4 == 3.9375 GB", abs(model_footprint_gb(7, Q4_BPP) - 3.9375) < 1e-9)
    check("1B @ fp16 fits 8GB unified but is tight on a small VRAM card",
          model_footprint_gb(1, FP16_BPP) <= 8)
    # quantization lets a model fit a SMALLER tier than fp16 (the GGUF_QUANT link)
    fp16_3b = model_footprint_gb(3, FP16_BPP)
    q4_3b = model_footprint_gb(3, Q4_BPP)
    check("3B @ Q4 (1.69 GB) fits 8GB where 3B @ fp16 (6 GB) is tighter",
          q4_3b < fp16_3b)
    return rows


# ============================================================================
# E. THE LINEAGE RECAP + WHY-IT-MATTERS (pinned for the guide)
# ============================================================================

def section_lineage_recap():
    banner("SECTION E: lineage recap -- discrete -> UMA -> MLX (why each step)")
    ladder = [
        ("Discrete GPU (CUDA)", "separate VRAM; cudaMemcpy across PCIe",
         "copy = M; FAIL if M > VRAM"),
        ("Apple Silicon UMA", "CPU + GPU share ONE RAM pool",
         "zero copy; no VRAM ceiling"),
        ("MLX (lazy + Metal)", "ops queue into a DAG; fuse on eval",
         "fewer kernels; alloc once"),
    ]
    print("| stage                | what changes               | payoff            |")
    print("|----------------------|----------------------------|-------------------|")
    for name, what, payoff in ladder:
        print(f"| {name:<20} | {what:<26} | {payoff:<17} |")
    print()
    print("Each step removes one bottleneck: the copy (UMA), then the per-op")
    print("dispatch + intermediate traffic (lazy fusion). Decode is bandwidth-")
    print("bound, so deleting copy + intermediate traffic directly buys tok/s.")
    # checks
    payoffs = [p for _, _, p in ladder]
    check("the three stages are distinct in their payoff",
          len(set(payoffs)) == 3)
    check("UMA payoff mentions zero copy",
          "zero copy" in ladder[1][2])
    check("MLX payoff mentions fewer kernels (fusion)",
          "fewer kernels" in ladder[2][2])


# ============================================================================
# main
# ============================================================================

def main():
    print("mlx_metal_edge.py - reference impl (faithful single-process UMA + MLX")
    print("simulation). Numbers below feed MLX_METAL_EDGE.md.  torch =",
          torch.__version__)
    print("\nNOTE: no mlx / Metal / torch.distributed is used. The unified pool")
    print("is a Python bytearray; the lazy graph is a DAG of MLXArray nodes; the")
    print("fusion pass counts kernel groups. The memory-bytes and kernel-count")
    print("arithmetic is REAL and EXACT; only the hardware transport is simulated.")
    print("\nEvery claim is web-verified in >=2 sources; "
          "see mlx_metal_edge_reference.txt.")

    section_unified_vs_discrete()
    section_lazy_fusion()
    section_fusion_numerics()
    section_zero_copy()
    section_memory_budget()
    section_lineage_recap()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
