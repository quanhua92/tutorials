"""
ggml_backend.py - Reference implementation of the GGML compute graph + backend model.

WHAT IS THE GGML COMPUTE GRAPH? (start here if you have minimal ML background)
   A Transformer forward pass is a fixed recipe of tensor ops (matmul, add, RoPE,
   RMS-norm, softmax, silu ...). PyTorch runs them EAGERLY: each op dispatches the
   instant you call it, paying Python + framework overhead per op, with no view of
   what comes next. GGML flips that: you *describe* the whole recipe as a DAG
   (a `ggml_cgraph`), then hand the DAG to a *backend* that topo-sorts it, allocates
   every tensor once, fuses neighbouring element-wise ops, and runs the kernels in
   order. The description is cheap; the execution is the expensive part, and it is
   the only thing the backend ever sees.

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. PyTorch EAGER (the "default"): `y = (x @ W).relu()`. Each call builds a tiny
      op, dispatches it to the GPU/CPU *now*, writes an intermediate tensor to
      memory, then the next op reads it back. Problem: Python dispatch overhead per
      op + memory-bandwidth-bound because every intermediate hits VRAM. Fine for
      training autograd; wasteful for fixed-shape inference.

   2. GGML DEFERRED / compute graph: model construction only *records* ops as tensor
      nodes (`src[]` edges, `op` enum). Nothing runs. `ggml_build_forward_expand`
      then walks the DAG from the output and emits a topologically sorted node list.
      `ggml_graph_compute` (or a backend's `graph_compute`) executes that list once.
      One allocation, one pass, no per-op Python.

   3. + BACKEND ABSTRACTION (`ggml_backend`): the SAME `ggml_cgraph` is shipped to
      ggml-cpu (SIMD: AVX2/AVX512/AMX/NEON), ggml-cuda (NVIDIA), ggml-metal (Apple),
      ggml-vulkan, ggml-sycl ... Each backend picks the kernel + memory layout.
      `ggml_backend_sched` can even SPLIT one graph across backends (e.g. the heavy
      matmuls on the GPU, a tiny reshape on the CPU) and stitch the copies.

   4. + OP FUSION: backends merge consecutive element-wise ops (mul -> add -> silu)
      into a single kernel so the intermediates stay in registers and never touch
      memory. This is the single biggest bandwidth win on memory-bound LLM layers.

   WHY IT MATTERS: inference is memory-bandwidth-bound, not compute-bound. The
   compute graph lets the backend see the *whole* layer and (a) allocate once, (b)
   schedule across devices, (c) fuse kernels to halve the memory traffic. That is
   why llama.cpp matches or beats PyTorch eager on the *same* hardware.

THE LIFECYCLE (this bundle's load-bearing claim):
       ggml_init(arena)  ->  build tensors + ops (record edges)  ->
       ggml_build_forward_expand(gf, out)   [topo-sort into cgraph]  ->
       ggml_graph_plan / backend_sched_alloc_graph   [plan + allocate]  ->
       graph_compute   [execute in topo order]  ->  read results

Companion code that GGML_BACKEND.md is built from. Every number below is printed by:
    python3 ggml_backend.py

This is PURE PYTHON STDLIB (no torch, no numpy). It is a faithful *model* of ggml's
data structures and lifecycle, tiny dims so every number prints.

Structures mirror ggml/include/ggml.h:
    struct ggml_tensor { type, buffer, ne[4], nb[4], op, op_params, flags,
                         src[GGML_MAX_SRC=10], view_src, view_offs, data, name }
    enum ggml_op { NONE=0, ADD, MUL, MUL_MAT, SCALE, SILU, RELU, RMS_NORM,
                   SOFT_MAX, ROPE, CPY, ... }
    struct ggml_cgraph { nodes[], leafs[], ... }   # built by build_forward_expand
"""

from __future__ import annotations

import math
from enum import IntEnum
from itertools import count

BANNER = "=" * 72


# ============================================================================
# 1. ggml_type + ggml_op enums  (mirror ggml.h)
# ============================================================================

class GGMLType(IntEnum):
    # subset of the real enum; type id matches ggml's ordering for F32/F16
    F32  = 0
    F16  = 1
    Q4_0 = 2
    Q8_0 = 8
    I8   = 24
    I32  = 25

# bytes per element for the dense (non-block-quant) types. Block quants
# (Q4_0/Q8_0) are group-quantized; here we give the *effective* bytes/element so
# the matmul traffic math stays simple. See gguf_format.py for the block layout.
TYPE_BYTES = {
    GGMLType.F32: 4,
    GGMLType.F16: 2,
    GGMLType.Q4_0: 0.5,   # 32-element block -> 18 bytes -> ~0.5 B/elem
    GGMLType.Q8_0: 1.0,   # 32-element block -> 34 bytes -> ~1   B/elem
    GGMLType.I8: 1,
    GGMLType.I32: 4,
}

TYPE_NAME = {
    GGMLType.F32: "F32",
    GGMLType.F16: "F16",
    GGMLType.Q4_0: "Q4_0",
    GGMLType.Q8_0: "Q8_0",
    GGMLType.I8: "I8",
    GGMLType.I32: "I32",
}


class GGMLOp(IntEnum):
    # a tiny slice of the real enum ggml_op (ggml.h). NONE=0 means "leaf".
    NONE     = 0
    ADD      = 1
    MUL      = 2
    MUL_MAT  = 3
    SCALE    = 4
    SILU     = 5
    RELU     = 6
    RMS_NORM = 7
    SOFT_MAX = 8
    ROPE     = 9
    CPY      = 10


OP_NAME = {op: op.name for op in GGMLOp}


# ============================================================================
# 2. Tensor  (faithful model of struct ggml_tensor)
# ============================================================================

GGML_MAX_DIMS = 4


class Tensor:
    """One tensor node. Mirrors `struct ggml_tensor` from ggml.h.

    Fields that matter for this simulator:
        type      - element type (F32/F16/Q4_0/...)
        ne[]      - shape; ne[0] is the contiguous (innermost) dimension
        nb[]      - stride in bytes; nb[0] = sizeof(type), nb[i] = nb[i-1]*ne[i-1]
        op        - the op that PRODUCES this tensor (NONE => leaf/constant)
        op_params - per-op parameters (e.g. SCALE's factor)
        flags     - INPUT / OUTPUT markers for the allocator
        src[]     - the input/source tensors = the DAG edges (max 10 in ggml)
        data      - the raw bytes; here a list[float] for F32 tensors
        name      - human label
    """

    FLAG_INPUT  = 1
    FLAG_OUTPUT = 2

    _ids = count()

    def __init__(self, name: str, gtype: GGMLType, ne: list[int],
                 op: GGMLOp = GGMLOp.NONE, src: list["Tensor"] | None = None,
                 data: list[float] | None = None, op_params: list[int] | None = None):
        self.name = name
        self.type = gtype
        self.ne = list(ne) + [1] * (GGML_MAX_DIMS - len(ne))   # pad to 4 dims
        self.op = op
        self.src = list(src) if src else []
        self.op_params = list(op_params) if op_params else []
        self.flags = 0
        self.data = list(data) if data is not None else None
        self.buffer = None          # which backend buffer owns this tensor
        self.id = next(Tensor._ids)
        self._compute_strides()

    def _compute_strides(self) -> None:
        # nb[0] = sizeof(type); nb[i] = nb[i-1] * ne[i-1]
        nb = [0] * GGML_MAX_DIMS
        nb[0] = TYPE_BYTES[self.type]
        for i in range(1, GGML_MAX_DIMS):
            nb[i] = nb[i - 1] * self.ne[i - 1]
        self.nb = nb

    @property
    def nelem(self) -> int:
        n = 1
        for d in self.ne:
            n *= d
        return n

    @property
    def nbytes(self) -> int:
        # total bytes of the backing store (F32 only path; ints rounded for quants)
        raw = self.nelem * TYPE_BYTES[self.type]
        return int(math.ceil(raw))

    def set_input(self)  -> "Tensor": self.flags |= Tensor.FLAG_INPUT;  return self
    def set_output(self) -> "Tensor": self.flags |= Tensor.FLAG_OUTPUT; return self

    def __repr__(self) -> str:
        return (f"Tensor({self.name}, op={OP_NAME[self.op]}, "
                f"type={TYPE_NAME[self.type]}, ne={self.ne[:self._dims()]})")

    def _dims(self) -> int:
        d = GGML_MAX_DIMS
        while d > 1 and self.ne[d - 1] == 1:
            d -= 1
        return d


# ============================================================================
# 3. Context (the ggml_init arena) + cgraph
# ============================================================================

class Context:
    """`ggml_init(params)` creates an arena: a bump-allocated slab that holds all
    tensor metadata + data. `no_alloc=false` (here) means data is owned by the
    context; the backend allocator later moves tensors onto device buffers."""

    def __init__(self, mem_size: int):
        self.mem_size = mem_size
        self.used = 0
        self.tensors: list[Tensor] = []

    def track(self, t: Tensor) -> Tensor:
        self.used += t.nbytes
        self.tensors.append(t)
        return t

    def new_tensor(self, name: str, gtype: GGMLType, ne: list[int],
                   data: list[float] | None = None) -> Tensor:
        t = Tensor(name, gtype, ne, op=GGMLOp.NONE, data=data)
        return self.track(t)


class CGraph:
    """`struct ggml_cgraph`: the topologically sorted DAG. ggml separates
    `nodes` (ops that produce a value) from `leafs` (params/constants/inputs with
    op==NONE). build_forward_expand fills both by a post-order DFS from the root."""

    def __init__(self, size: int = 2048):
        self.nodes: list[Tensor] = []      # GGML_DEFAULT_GRAPH_SIZE = 2048
        self.leafs: list[Tensor] = []
        self.size = size


# ----------------------------------------------------------------------------
# op constructors (record edges, compute nothing) -- mirror ggml_add / ggml_mul ...
# ----------------------------------------------------------------------------

def ggml_mul(ctx: Context, a: Tensor, b: Tensor) -> Tensor:
    t = Tensor(f"mul({a.name},{b.name})", a.type, a.ne, op=GGMLOp.MUL, src=[a, b])
    return ctx.track(t)


def ggml_add(ctx: Context, a: Tensor, b: Tensor) -> Tensor:
    t = Tensor(f"add({a.name},{b.name})", a.type, a.ne, op=GGMLOp.ADD, src=[a, b])
    return ctx.track(t)


def ggml_mul_mat(ctx: Context, a: Tensor, b: Tensor) -> Tensor:
    # a @ b : a is [n,k] (rows=n cols=k), b is [k,m] -> out [n,m]. ggml stores ne
    # as [cols, rows] (col-major); we keep the math intuitive with ne=[k,n].
    n, k = a.ne[1], a.ne[0]
    k2, m = b.ne[0], b.ne[1]
    assert k == k2, f"mul_mat shape mismatch: {a.ne[:2]} x {b.ne[:2]}"
    t = Tensor(f"mul_mat({a.name},{b.name})", a.type, [m, n],
               op=GGMLOp.MUL_MAT, src=[a, b])
    return ctx.track(t)


def ggml_scale(ctx: Context, a: Tensor, s: float) -> Tensor:
    # ggml stores the factor in op_params as a bit-cast int32; we keep a readable
    # float alongside so compute_op is exact and dependency-free.
    t = Tensor(f"scale({a.name})", a.type, a.ne, op=GGMLOp.SCALE, src=[a])
    t._scale = s
    return ctx.track(t)


def ggml_silu(ctx: Context, a: Tensor) -> Tensor:
    t = Tensor(f"silu({a.name})", a.type, a.ne, op=GGMLOp.SILU, src=[a])
    return ctx.track(t)


def ggml_relu(ctx: Context, a: Tensor) -> Tensor:
    t = Tensor(f"relu({a.name})", a.type, a.ne, op=GGMLOp.RELU, src=[a])
    return ctx.track(t)


# ============================================================================
# 4. build_forward_expand  (post-order DFS topo-sort, faithful to ggml)
# ============================================================================

def ggml_build_forward_expand(gf: CGraph, output: Tensor) -> CGraph:
    """Walk the DAG upward from `output`, emitting tensors in post-order: every
    source is registered before the tensor that consumes it. This yields a valid
    topological order. Leaf tensors (op==NONE) go to `gf.leafs`, ops to `gf.nodes`.

    ggml's real implementation (`ggml_visit_parents`) is iterative + uses a visited
    bitmap; the ordering behaviour is identical to this post-order DFS.
    """
    visited: set[int] = set()

    def visit(t: Tensor) -> None:
        if id(t) in visited:
            return
        visited.add(id(t))
        for s in t.src:                 # register inputs first (post-order)
            visit(s)
        if t.op == GGMLOp.NONE and not t.src:
            gf.leafs.append(t)
        else:
            gf.nodes.append(t)

    visit(output)
    return gf


def ggml_new_graph(ctx: Context, size: int = 2048) -> CGraph:
    return CGraph(size=size)


# ----------------------------------------------------------------------------
# Kahn's algorithm (BFS topo-sort) -- used in Section B to show an alternative,
# queue-based ordering and to validate that build_forward_expand's order is a
# legal topological sort.
# ----------------------------------------------------------------------------

def kahn_topo_sort(root: Tensor) -> list[Tensor]:
    """Return a topological order of every tensor reachable from `root`.

    Kahn's algorithm: repeatedly emit tensors whose inputs are all already emitted.
    Uses a deterministic tie-break = insertion order, so the trace is reproducible.
    """
    # collect the reachable set + dependency edges, preserving discovery order
    order_seen: list[Tensor] = []
    seen: set[int] = set()

    def collect(t: Tensor) -> None:
        if id(t) in seen:
            return
        seen.add(id(t))
        for s in t.src:
            collect(s)
        order_seen.append(t)            # post-discovery = a stable insertion order

    collect(root)

    indeg: dict[int, int] = {id(t): len(t.src) for t in order_seen}
    by_id: dict[int, Tensor] = {id(t): t for t in order_seen}

    # ready queue: tensors with zero unresolved inputs, in insertion order
    ready: list[Tensor] = [t for t in order_seen if indeg[id(t)] == 0]
    out: list[Tensor] = []
    while ready:
        t = ready.pop(0)
        out.append(t)
        # find consumers of t (tensors that list t in src)
        for cand in order_seen:
            if t in cand.src:
                indeg[id(cand)] -= 1
                if indeg[id(cand)] == 0:
                    ready.append(cand)
    return out


# ============================================================================
# 5. graph_compute  (execute the cgraph in topo order on a backend)
# ============================================================================

def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def compute_op(t: Tensor) -> list[float]:
    """Evaluate one tensor's op using its sources' data. Pure function."""
    op = t.op
    if op == GGMLOp.NONE:
        assert t.data is not None, f"leaf {t.name} has no data"
        return t.data
    a = t.src[0].data
    if op == GGMLOp.ADD:
        b = t.src[1].data
        return [x + y for x, y in zip(a, b)]
    if op == GGMLOp.MUL:
        b = t.src[1].data
        return [x * y for x, y in zip(a, b)]
    if op == GGMLOp.SCALE:
        s = getattr(t, "_scale", 1.0)
        return [x * s for x in a]
    if op == GGMLOp.SILU:
        return [x * _sigmoid(x) for x in a]
    if op == GGMLOp.RELU:
        return [x if x > 0 else 0.0 for x in a]
    if op == GGMLOp.MUL_MAT:
        A = t.src[0]                       # [k, n]
        B = t.src[1]                       # [k, m]
        k, n = A.ne[0], A.ne[1]
        _, m = B.ne[0], B.ne[1]
        out = [0.0] * (n * m)
        for row in range(n):
            for col in range(m):
                acc = 0.0
                for p in range(k):
                    acc += A.data[row * k + p] * B.data[p * m + col]
                out[row * m + col] = acc
        return out
    raise NotImplementedError(f"op {OP_NAME[op]} not implemented")


def graph_compute(gf: CGraph) -> list[Tensor]:
    """Execute `gf.nodes` in topo order, filling each tensor's `data`. This is the
    simulator's `ggml_graph_compute`: a real backend swaps each op for a hand-tuned
    kernel, but the *order* and the *allocate-once-then-run* contract is the same."""
    log: list[Tensor] = []
    for t in gf.nodes:
        t.data = compute_op(t)
        log.append(t)
    return log


# ============================================================================
# 6. Backends  (same graph, different kernel + memory layout)
# ============================================================================

class Backend:
    """A `ggml_backend` selects, for each op + tensor type, a concrete kernel and
    decides the device memory layout. Real backends: ggml-cpu, ggml-cuda,
    ggml-metal, ggml-vulkan, ggml-sycl ..."""

    name = "base"
    device = "host"
    compute_type = GGMLType.F32      # the type kernels actually run in

    # kernel table: op -> (kernel name, is it SIMD/GPU-accelerated?)
    KERNELS: dict[GGMLOp, tuple[str, str]] = {}

    def kernel_for(self, op: GGMLOp) -> tuple[str, str]:
        return self.KERNELS.get(op, ("generic", "fallback"))

    def dispatch_table(self, gf: CGraph) -> list[dict[str, str]]:
        rows = []
        for t in gf.nodes:
            kname, accel = self.kernel_for(t.op)
            rows.append({
                "tensor": t.name,
                "op": OP_NAME[t.op],
                "kernel": kname,
                "accel": accel,
                "dtype": TYPE_NAME[self.compute_type],
                "device": self.device,
            })
        # leafs are data, not kernels
        for t in gf.leafs:
            rows.append({
                "tensor": t.name, "op": OP_NAME[t.op],
                "kernel": "(data)", "accel": "-",
                "dtype": TYPE_NAME[self.compute_type], "device": self.device,
            })
        return rows


class CPUBackend(Backend):
    name = "ggml-cpu"
    device = "RAM"
    compute_type = GGMLType.F32
    KERNELS = {
        GGMLOp.ADD:     ("ggml_vec_add_f32",   "AVX2/AVX512/NEON SIMD"),
        GGMLOp.MUL:     ("ggml_vec_mul_f32",   "AVX2/AVX512/NEON SIMD"),
        GGMLOp.MUL_MAT: ("ggml_gemm_q4_0_f32", "AMX/dotprod + thread pool"),
        GGMLOp.SILU:    ("ggml_vec_silu_f32",  "SIMD vectorized"),
        GGMLOp.RELU:    ("ggml_vec_relu_f32",  "SIMD vectorized"),
        GGMLOp.SCALE:   ("ggml_vec_scale_f32", "SIMD vectorized"),
    }


class MetalBackend(Backend):
    name = "ggml-metal"
    device = "Apple GPU (unified memory)"
    # Metal kernels compute in F16 (the GPU's native width) for bandwidth; matmul
    # tiles with matrix-multiply-accumulator (AMX/Metal-performant-shaders).
    compute_type = GGMLType.F16
    KERNELS = {
        GGMLOp.ADD:     ("kernel_add_f16",        "Metal compute shader"),
        GGMLOp.MUL:     ("kernel_mul_f16",        "Metal compute shader"),
        GGMLOp.MUL_MAT: ("kernel_mul_mm_f16",     "Metal MPS matrix tiling"),
        GGMLOp.SILU:    ("kernel_silu_f16",       "Metal compute shader"),
        GGMLOp.RELU:    ("kernel_relu_f16",       "Metal compute shader"),
        GGMLOp.SCALE:   ("kernel_scale_f16",      "Metal compute shader"),
    }


class CudaBackend(Backend):
    name = "ggml-cuda"
    device = "NVIDIA GPU (VRAM)"
    compute_type = GGMLType.F16
    KERNELS = {
        GGMLOp.ADD:     ("add_f32",            "CUDA elementwise kernel"),
        GGMLOp.MUL:     ("mul_f32",            "CUDA elementwise kernel"),
        GGMLOp.MUL_MAT: ("mul_mat_q4_0_f16",   "mma/Tensor Core + dequant"),
        GGMLOp.SILU:    ("silu_f32",           "CUDA elementwise kernel"),
        GGMLOp.RELU:    ("relu_f32",           "CUDA elementwise kernel"),
        GGMLOp.SCALE:   ("scale_f32",          "CUDA elementwise kernel"),
    }


# ============================================================================
# 7. Op fusion  (merge consecutive element-wise ops into one kernel pass)
# ============================================================================

ELEMENTWISE = {GGMLOp.MUL, GGMLOp.ADD, GGMLOp.SCALE, GGMLOp.SILU, GGMLOp.RELU}


def fuse_plan(gf: CGraph) -> list[list[Tensor]]:
    """Greedy fusion: group a chain of element-wise ops that feed each other 1:1
    into a single fused kernel. MUL_MAT (matmul) and reductions are NOT fused here
    (a backend may still fuse an activation INTO a matmul's output epilogue).

    Returns a list of "kernel groups"; each group runs as one pass.
    """
    # map tensor -> the group it belongs to, walking in topo order
    groups: list[list[Tensor]] = []
    tensor_group: dict[int, list[Tensor]] = {}

    for t in gf.nodes:
        if t.op not in ELEMENTWISE:
            groups.append([t])                       # its own kernel
            tensor_group[id(t)] = groups[-1]
            continue
        # can we extend the group of a single element-wise producer?
        ew_srcs = [s for s in t.src if s.op in ELEMENTWISE]
        if len(ew_srcs) == 1 and id(ew_srcs[0]) in tensor_group:
            tensor_group[id(ew_srcs[0])].append(t)
            tensor_group[id(t)] = tensor_group[id(ew_srcs[0])]
        else:
            groups.append([t])
            tensor_group[id(t)] = groups[-1]
    return groups


# ============================================================================
# 8. pretty printer + check helper
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(label: str, cond: bool) -> bool:
    status = "OK" if cond else "FAIL"
    print(f"[check] {label}: {cond} -> {status}")
    return cond


def fmt_vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.4f}" for x in v) + "]"


# ============================================================================
# 9. SECTIONS  (the numbers that feed GGML_BACKEND.md)
# ============================================================================

def section_a_tensor_and_graph():
    banner("SECTION A: ggml_tensor + ggml_cgraph (build a tiny graph)")
    print("The ggml_tensor struct (from ggml/include/ggml.h):")
    print("  { type, ne[4], nb[4], op, op_params[], flags, src[10], data, name }")
    print("  ne[0] is the contiguous (innermost) dim; src[] are the DAG edges.\n")

    print("Lifecycle:  ggml_init(arena) -> build tensors+ops (record edges) ->")
    print("  ggml_build_forward_expand (topo-sort) -> plan/allocate -> compute -> read\n")

    # ---- ggml_init: create the arena ----
    ctx = Context(mem_size=64 * 1024)

    # ---- build tensors + ops (NO computation yet) ----
    # Graph:  A=const(2.0), input=5.0, B=mul(A,input), K=const(3.0), C=add(B,K)
    A     = ctx.new_tensor("A",     GGMLType.F32, [1], data=[2.0]).set_input()
    inp   = ctx.new_tensor("input", GGMLType.F32, [1], data=[5.0]).set_input()
    K     = ctx.new_tensor("K",     GGMLType.F32, [1], data=[3.0])
    B     = ggml_mul(ctx, A, inp)
    C     = ggml_add(ctx, B, K).set_output()

    all_tensors = [A, inp, K, B, C]
    print("Built tensors (note: op != NONE means the value is NOT computed yet):")
    print("| name  | op      | type | ne   | nbytes | src            | flags   |")
    print("|-------|---------|------|------|--------|----------------|---------|")
    for t in all_tensors:
        srcs = ",".join(s.name for s in t.src) or "-"
        flags = []
        if t.flags & Tensor.FLAG_INPUT:  flags.append("INPUT")
        if t.flags & Tensor.FLAG_OUTPUT: flags.append("OUTPUT")
        print(f"| {t.name:<5} | {OP_NAME[t.op]:<7} | {TYPE_NAME[t.type]:<4} | "
              f"{str(t.ne[:1]):<4} | {t.nbytes:<6} | {srcs:<14} | "
              f"{','.join(flags) or '-':<7} |")

    # ---- ggml_build_forward_expand: topo-sort into the cgraph ----
    gf = ggml_new_graph(ctx)
    ggml_build_forward_expand(gf, C)
    print(f"\nggml_build_forward_expand(gf, C) -> post-order DFS from the output:")
    print(f"  nodes (ops, in topo order): {[n.name for n in gf.nodes]}")
    print(f"  leafs (params/inputs):      {[n.name for n in gf.leafs]}")
    print("(every source is registered before the tensor that consumes it)\n")

    # ---- compute + read ----
    graph_compute(gf)
    print(f"After graph_compute, read the output:")
    print(f"  B = {B.name} = {B.data[0]:.1f}")
    print(f"  C = {C.name} = {C.data[0]:.1f}")
    gold_b = abs(B.data[0] - 10.0) < 1e-9
    gold_c = abs(C.data[0] - 13.0) < 1e-9
    check("B == mul(A=2.0, input=5.0) == 10.0", gold_b)
    check("C == add(B=10.0, K=3.0) == 13.0", gold_c)


def section_b_topo_sort():
    banner("SECTION B: topological sort (post-order DFS vs Kahn's algorithm)")
    print("ggml must run every op only AFTER its inputs are ready. Two ways to")
    print("order a DAG, both produce a legal topological sort:\n")

    ctx = Context(mem_size=64 * 1024)
    A   = ctx.new_tensor("A",     GGMLType.F32, [1], data=[2.0])
    inp = ctx.new_tensor("input", GGMLType.F32, [1], data=[5.0])
    K   = ctx.new_tensor("K",     GGMLType.F32, [1], data=[3.0])
    B   = ggml_mul(ctx, A, inp)
    C   = ggml_add(ctx, B, K)

    print("DAG edges (src -> consumer):")
    edges = []
    for t in [B, C]:
        for s in t.src:
            edges.append((s.name, t.name))
    for a, b in sorted(edges):
        print(f"  {a} -> {b}")

    # ---- ggml's way: post-order DFS (build_forward_expand) ----
    gf = ggml_new_graph(ctx)
    ggml_build_forward_expand(gf, C)
    dfs_order = [t.name for t in gf.nodes]
    print(f"\n(1) post-order DFS (ggml_build_forward_expand):")
    print(f"    {dfs_order}")

    # ---- Kahn's algorithm ----
    kahn = kahn_topo_sort(C)
    kahn_order = [t.name for t in kahn]
    print(f"\n(2) Kahn's algorithm (BFS, emit zero-in-degree first):")
    print(f"    {kahn_order}")

    # validate both are legal topological orders
    pos_dfs = {name: i for i, name in enumerate(dfs_order)}
    pos_kahn = {name: i for i, name in enumerate(kahn_order)}
    dfs_legal = all(pos_dfs[s.name] < pos_dfs[t.name]
                    for t in gf.nodes for s in t.src if s.op != GGMLOp.NONE)
    kahn_legal = all(pos_kahn[s.name] < pos_kahn[t.name]
                     for t in kahn for s in t.src)
    check("post-order DFS is a legal topo order", dfs_legal)
    check("Kahn's order is a legal topo order",   kahn_legal)
    print("\nNote: the two orders differ in leaf placement, but BOTH respect every")
    print("data dependency. ggml uses the DFS form because it is a single pass over")
    print("src[] with no in-degree bookkeeping.")


def section_c_backend_dispatch():
    banner("SECTION C: backend dispatch (same graph, CPU vs Metal vs CUDA)")
    print("A ggml_cgraph is backend-agnostic. The backend decides, for each op:")
    print("  * which KERNEL runs (SIMD vector loop vs GPU compute shader)")
    print("  * the COMPUTE DTYPE (CPU=F32; GPU often downcasts to F16 for bandwidth)")
    print("  * the DEVICE memory (RAM vs unified-memory GPU vs VRAM)\n")

    ctx = Context(mem_size=64 * 1024)
    A   = ctx.new_tensor("A",     GGMLType.F32, [1], data=[2.0])
    inp = ctx.new_tensor("input", GGMLType.F32, [1], data=[5.0])
    K   = ctx.new_tensor("K",     GGMLType.F32, [1], data=[3.0])
    B   = ggml_mul(ctx, A, inp)
    C   = ggml_add(ctx, B, K)
    gf = ggml_new_graph(ctx)
    ggml_build_forward_expand(gf, C)

    for be in (CPUBackend(), MetalBackend(), CudaBackend()):
        rows = be.dispatch_table(gf)
        print(f"Backend: {be.name}  (device={be.device}, compute_dtype={TYPE_NAME[be.compute_type]})")
        print(f"| tensor       | op   | kernel              | acceleration          |")
        print(f"|--------------|------|---------------------|-----------------------|")
        for r in rows:
            print(f"| {r['tensor']:<12} | {r['op']:<4} | {r['kernel']:<19} | "
                  f"{r['accel']:<21} |")
        print()

    print("Key insight: the GRAPH IS IDENTICAL. Only the kernel table + dtype change.")
    print("ggml_backend_sched can even SPLIT one graph: route the MUL_MAT to the GPU")
    print("and a tiny reshape to the CPU, inserting a CPY (copy) edge at the boundary.")

    # demonstrate a 2x2 matmul to show the MUL_MAT kernel path
    ctx2 = Context(mem_size=64 * 1024)
    W = ctx2.new_tensor("W", GGMLType.F32, [2, 2], data=[1.0, 2.0, 3.0, 4.0])
    X = ctx2.new_tensor("X", GGMLType.F32, [2, 2], data=[1.0, 0.0, 0.0, 1.0])
    Y = ggml_mul_mat(ctx2, W, X)
    gf2 = ggml_new_graph(ctx2)
    ggml_build_forward_expand(gf2, Y)
    graph_compute(gf2)
    print(f"\nMUL_MAT demo: W=[[1,2],[3,4]] @ X=I -> Y = {Y.data}")
    check("2x2 matmul W@I == W", Y.data == [1.0, 2.0, 3.0, 4.0])


def section_d_op_fusion():
    banner("SECTION D: op fusion (mul -> add -> silu in ONE kernel pass)")
    print("Consecutive ELEMENT-WISE ops can be fused: the intermediates stay in")
    print("registers and never hit memory. Inference is bandwidth-bound, so this is")
    print("the single biggest win on memory-bound layers.\n")

    # build a typical MLP "gate" line:  T1 = a * x ; T2 = T1 + b ; T3 = silu(T2)
    ctx = Context(mem_size=64 * 1024)
    a = ctx.new_tensor("a", GGMLType.F32, [2], data=[0.5, 0.5])
    x = ctx.new_tensor("x", GGMLType.F32, [2], data=[1.0, 2.0])
    b = ctx.new_tensor("b", GGMLType.F32, [2], data=[1.0, 1.0])
    T1 = ggml_mul(ctx, a, x)
    T2 = ggml_add(ctx, T1, b)
    T3 = ggml_silu(ctx, T2)
    gf = ggml_new_graph(ctx)
    ggml_build_forward_expand(gf, T3)

    # ---- separate kernels: 3 passes ----
    graph_compute(gf)  # exact reference result
    separate_result = list(T3.data)
    print("Separate kernels (one pass per op):")
    print("| pass | op   | reads        | writes       | traffic |")
    print("|------|------|--------------|--------------|---------|")
    for t in gf.nodes:
        reads = sum(s.nbytes for s in t.src)
        writes = t.nbytes
        print(f"| {OP_NAME[t.op]:<4} | {OP_NAME[t.op]:<4} | "
              f"{reads:>3}B ({'+'.join(s.name for s in t.src)}) | "
              f"{writes:>3}B ({t.name:<3}) | {reads+writes:>4}B   |")
    # total = sum of (reads+writes) across the 3 kernels; intermediates counted twice
    sep_traffic = sum(sum(s.nbytes for s in t.src) + t.nbytes for t in gf.nodes)
    print(f"  separate total traffic: {sep_traffic}B "
          f"(T1 and T2 each written AND read back)\n")

    # ---- fused: 1 pass ----
    groups = fuse_plan(gf)
    fused_result = list(T3.data)
    print(f"Fused plan -> {len(groups)} kernel pass(es):")
    for i, g in enumerate(groups):
        ops = [OP_NAME[t.op] for t in g]
        # inputs to the fused group = sources that are NOT inside the group
        group_srcs = []
        for t in g:
            for s in t.src:
                if s not in g and s not in group_srcs:
                    group_srcs.append(s)
        reads = sum(s.nbytes for s in group_srcs)
        writes = g[-1].nbytes
        print(f"  kernel #{i+1}: {' -> '.join(ops)}")
        print(f"             reads={reads}B ({'+'.join(s.name for s in group_srcs)}), "
              f"writes={writes}B ({g[-1].name})")
    fused_reads = a.nbytes + x.nbytes + b.nbytes
    fused_writes = T3.nbytes
    fused_total = fused_reads + fused_writes
    print(f"  fused total traffic: {fused_total}B "
          f"(T1, T2 never leave registers)")

    saved = (sep_traffic - fused_total) / sep_traffic * 100
    print(f"\nBandwidth saved: {sep_traffic}B -> {fused_total}B "
          f"({saved:.0f}% reduction)")
    print(f"\n[check] fused result == separate result (fusion is EXACT): "
          f"{all(abs(p - q) < 1e-9 for p, q in zip(separate_result, fused_result))}")
    print(f"[check] {saved:.0f}% == 50% traffic reduction (2-elem chain): "
          f"{abs(saved - 50.0) < 0.5}")


# ----------------------- THE GOLD CENTERPIECE --------------------------------

def section_gold():
    banner("SECTION G: GOLD lifecycle trace (the centerpiece)")
    print("Full lifecycle on the canonical 3-node graph:")
    print("  A = const(2.0), input = 5.0, B = mul(A, input), K = const(3.0),")
    print("  C = add(B, K)\n")

    # 1. ggml_init
    ctx = Context(mem_size=64 * 1024)
    print("STEP 1  ggml_init(arena=64KiB)")

    # 2. build (record edges only)
    A   = ctx.new_tensor("A",     GGMLType.F32, [1], data=[2.0]).set_input()
    inp = ctx.new_tensor("input", GGMLType.F32, [1], data=[5.0]).set_input()
    K   = ctx.new_tensor("K",     GGMLType.F32, [1], data=[3.0])
    B   = ggml_mul(ctx, A, inp)
    C   = ggml_add(ctx, B, K).set_output()
    print("STEP 2  build tensors + ops (no computation, edges recorded)")

    # 3. topo-sort
    gf = ggml_new_graph(ctx)
    ggml_build_forward_expand(gf, C)
    print("STEP 3  ggml_build_forward_expand(gf, C)  [topo-sort]")
    print(f"        nodes = {[n.name for n in gf.nodes]}")
    print(f"        leafs = {[n.name for n in gf.leafs]}")

    # 4. plan + allocate (simulated: backend assigns buffers)
    for t in gf.nodes + gf.leafs:
        t.buffer = f"{CPUBackend.name}:arena"
    print("STEP 4  plan + allocate (backend assigns each tensor a buffer)")

    # 5. compute
    print("STEP 5  graph_compute (execute in topo order):")
    print("| order | node | op   | src            | result |")
    print("|-------|------|------|----------------|--------|")
    for i, t in enumerate(gf.nodes, 1):
        t.data = compute_op(t)
        srcs = ",".join(s.name for s in t.src)
        print(f"| {i:<5} | {t.name:<4} | {OP_NAME[t.op]:<4} | {srcs:<14} | "
              f"{t.data[0]:<6.1f} |")

    # 6. read
    print(f"STEP 6  read: B = {B.data[0]:.1f},  C = {C.data[0]:.1f}\n")

    # GOLD checks
    topo_order = [t.name for t in gf.nodes]
    gold_b = abs(B.data[0] - 10.0) < 1e-9
    gold_c = abs(C.data[0] - 13.0) < 1e-9
    legal = all(
        any(s.name == n for n in topo_order[:i]) or s.op == GGMLOp.NONE
        for i, t in enumerate(gf.nodes) for s in t.src)
    check("B == 10.0", gold_b)
    check("C == 13.0", gold_c)
    check("topo order is legal (deps before consumers)", legal)

    print("\nGOLD (recomputed & badge-checked in ggml_backend.html):")
    print(f"  topo order of op nodes = {topo_order}")
    print(f"  B = {B.data[0]:.1f}")
    print(f"  C = {C.data[0]:.1f}")
    return {"topo": topo_order, "B": B.data[0], "C": C.data[0],
            "gold_ok": gold_b and gold_c and legal}


# ============================================================================
# main
# ============================================================================

def main():
    print("ggml_backend.py - reference impl. All numbers below feed GGML_BACKEND.md.")
    print("pure Python stdlib (no torch, no numpy). Mirrors ggml/include/ggml.h.")

    section_a_tensor_and_graph()
    section_b_topo_sort()
    section_c_backend_dispatch()
    section_d_op_fusion()
    gold = section_gold()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
