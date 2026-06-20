"""
jax_xla_tpu.py - JAX/XLA/TPU compilation pipeline + Splash Attention (faithful sim).

This is the single source of truth that JAX_XLA_TPU.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python jax_xla_tpu.py

============================================================================
PLATFORM NOTE — read me first  (labelled [SIM] everywhere below)
============================================================================
This machine is Apple Silicon with NO TPU and NO real JAX install. So this file
FAITHFULLY SIMULATES the JAX/XLA/TPU pipeline in pure Python/torch:

  (a) jaxpr tracing   — a tiny Tracer that records primitive ops into an IR list
                         when a function is "@jit"-compiled (Section B). [SIM]
  (b) XLA fusion      — a fusion pass that counts HBM intermediate writes eager
                         vs fused (Section C + G). The HBM-write COUNTS are exact;
                         the fusion engine is a faithful model of producer-consumer
                         element-wise fusion (XLA's real "output fusion"). [SIM]
  (c) TPU MXU systolic — a weight-stationary systolic matmul (Section D). The
                         MATH (C = W @ X) is exact and asserted == torch.matmul;
                         the cycle timing/fill+drain narrative is the published
                         TPU behaviour. [SIM-mechanism]
  (d) Pallas Grid+BlockSpec — a blockwise matmul mirroring pallas_call's grid /
                         BlockSpec / single-write-back contract (Section E). [SIM]

What is NOT simulated — it is EXACT:
  - Splash Attention == FlashAttention == naive attention (Section F). This is
    the SAME tiled online-softmax recurrence as research/flash_attention.py, run
    on the SAME deterministic inputs (seed=0, N=8, d=8). We ASSERT equality to
    naive attention (atol 1e-5) and note the q=0 row matches flash_attention.py's
    GOLD PIN exactly — proving the math transfers across hardware. This is the
    gold centerpiece of the bundle.

============================================================================
THE IDEA IN PLAIN ENGLISH (full version: JAX_XLA_TPU.md section 0)
============================================================================
PyTorch on a GPU is EAGER: each op runs the moment Python sees it and writes its
result to slow HBM (High-Bandwidth Memory). A chain like `silu(x@W1+b)@W2`
writes FOUR intermediate buffers to HBM — each write is bandwidth the GPU pays
for no reason, because the next op just reads it straight back.

JAX takes a different route. `@jax.jit` does NOT run your function — it TRACES
it once with abstract placeholder inputs (Tracers), recording the op sequence
into an IR called a jaxpr. The XLA compiler then takes that jaxpr and FUSES
the element-wise ops into single kernels, so intermediates live only in fast
on-chip memory and never round-trip to HBM. The same `silu(x@W1+b)@W2` becomes
ONE fused pass writing just the final result: 4 HBM writes -> 1.

A TPU runs the compiled code on SYSTOLIC arrays (MXU): a grid of MAC units
where weights sit still and activations flow through, multiplying and
accumulating without ever writing partial sums back to memory. Pallas is the
kernel language that exposes this (Grid = parallel index space, BlockSpec =
HBM<->VMEM tile mapping). Splash Attention is the tiled online-softmax
attention kernel written in Pallas — MATHEMATICALLY IDENTICAL to FlashAttention
(the GPU version), just adapted to the TPU's memory layout.

WHY: a different COMPILATION model (trace + fuse) + different HARDWARE
(systolic arrays + VMEM scratchpad) for maximum throughput on Google TPUs.

============================================================================
ANCHOR CONCEPTS (web-verified, see JAX_XLA_TPU.md "## Sources")
============================================================================
  jaxpr       : @jax.jit traces the fn once with Tracer (abstract) inputs,
                recording ops into a jaxpr IR. No execution until compiled.
  XLA fusion  : fuses element-wise op chains -> fewer HBM round-trips
                (eager N intermediate writes -> fused ~1).  PIN: 4 -> 1.
  MXU         : systolic array (256x256 PEs on real TPU). Weight-stationary:
                weights preloaded, activations stream, partial sums accumulate
                across the grid without register writeback. fill+drain = 3N-1.
  VMEM / SMEM : TPU fast on-chip scratchpad (VMEM ~ tens of MiB) = GPU SRAM
                analogue; SMEM holds scalars/control.
  ICI         : Inter-Chip Interconnect — ultra-low-latency direct links between
                TPU cores (pod-scale collectives, no host/PCIe round-trip).
  Pallas      : TPU kernel language. Grid = parallel index space (prod(grid)
                kernel launches); BlockSpec = (block_shape, index_map) mapping a
                grid coord to the HBM tile loaded into VMEM. Single write-back.
  Splash Attn : tiled online-softmax attention in Pallas. IDENTICAL recurrence
                to FlashAttention (m, l, o running accumulators + exp(m_old-m_new)
                rescaling). ASSERT == naive attention. 🔗 FLASH_ATTENTION.md

GLOSSARY (defined at first use in JAX_XLA_TPU.md):
    eager     PyTorch runs each op immediately -> 1 HBM write per intermediate.
    HBM       slow, big main memory (GPU DRAM / TPU DRAM). Round-trips cost.
    VMEM      TPU fast on-chip scratchpad (Vector Memory) ~= GPU SRAM.
    trace     run a fn with abstract inputs to record its op graph (no math).
    jaxpr     the IR (list of primitive equations) produced by tracing.
    fusion    merge a chain of ops into one kernel so intermediates stay on-chip.
    systolic  data flows through a PE grid; PEs reuse neighbours' outputs directly.
    tile      a small block loaded HBM->VMEM, computed on, written back once.

Conventions (tiny model so EVERY number prints):
    jaxpr example   : f(x) = silu(x @ W1 + b1) @ W2   (the fusion gold)
    attention       : N = 8 tokens, d = 8 head dim  (== flash_attention.py)
    systolic demo   : 3x3 weight grid (W @ X, X is 3x3)
"""

from __future__ import annotations

import math

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE SIMULATIONS  (this is the code JAX_XLA_TPU.md walks through)
#    [SIM] = simulated mechanism; the MATH (matmul, attention) is exact.
# ============================================================================

# ----------------------------------------------------------------------------
# 1a. jaxpr tracing  [SIM]  — a tiny Tracer that records ops into an IR list
# ----------------------------------------------------------------------------

# Op classification for the XLA fusion pass (Section C). Element-wise ops fuse
# with their producer; "anchor" ops (matmul / reductions) are fusion boundaries.
ELEMENTWISE = {"add", "mul", "silu", "relu", "tanh", "sub", "neg", "exp"}
ANCHOR = {"dot_general", "reduce"}           # matmul / row-reduction anchors


class Jaxpr:
    """[SIM] A jaxpr = an ordered list of equations. Each eqn is
    (op, [input_vars], output_var, meta). Mirrors real jaxpr: a functional,
    side-effect-free expression of primitive operations."""

    def __init__(self):
        self.eqns: list[tuple] = []
        self._n = 0

    def new_var(self, hint: str = "v") -> str:
        self._n += 1
        return f"{hint}{self._n}"

    def add(self, op: str, inputs: list[str], out: str, meta: dict):
        self.eqns.append((op, inputs, out, meta))

    def __str__(self):
        lines = ["jaxpr (traced equations):"]
        for op, ins, out, meta in self.eqns:
            shape = meta.get("shape", "?")
            lines.append(f"  {out} = {op}({', '.join(ins)})    : {shape}")
        return "\n".join(lines)


class Tracer:
    """[SIM] An abstract array (shape+dtype only). When a traced function does
    `a @ b`, `a + b`, `silu(a)`, ... the Tracer RECORDS the primitive into the
    jaxpr and returns a NEW Tracer for the result. NO real arithmetic happens.
    This is exactly what @jax.jit does: "to compile a function we first monitor
    its execution once [with abstract inputs]" (Frostig et al., SysML 2018)."""

    def __init__(self, shape: tuple, dtype: str, var: str, jaxpr: Jaxpr):
        self.shape = shape
        self.dtype = dtype
        self.var = var
        self.jaxpr = jaxpr

    def _record(self, op: str, other, out_shape, hint="v") -> "Tracer":
        out = self.jaxpr.new_var(hint)
        ins = [self.var] + ([other.var] if other is not None else [])
        self.jaxpr.add(op, ins, out, {"shape": out_shape})
        return Tracer(out_shape, self.dtype, out, self.jaxpr)

    def __matmul__(self, other):
        out_shape = (self.shape[0], other.shape[1])
        return self._record("dot_general", other, out_shape, hint="dot")

    def __add__(self, other):
        return self._record("add", other, self.shape, hint="a")

    def __mul__(self, other):
        return self._record("mul", other, self.shape, hint="m")

    def silu(self):
        return self._record("silu", None, self.shape, hint="s")


def jit(fn):
    """[SIM] @jax.jit: on first call (cache miss), TRACE fn with Tracer inputs
    into a jaxpr, then hand the jaxpr to XLA (fusion pass). Cache by the input
    signature (shapes+dtypes). Mirrors JAX's PjitFunction: hash the signature,
    trace on miss, compile, cache, execute the compiled binary on later calls.
    """

    cache: dict = {}

    def compiled(*args: torch.Tensor):
        sig = tuple((tuple(a.shape), a.dtype) for a in args)
        if sig not in cache:
            jaxpr = Jaxpr()
            abstract = [Tracer(tuple(a.shape), str(a.dtype), f"arg{i}", jaxpr)
                        for i, a in enumerate(args)]
            fn(*abstract)                         # TRACE — no math, fills jaxpr
            fused = xla_fuse(jaxpr)               # [SIM] XLA fusion pass
            cache[sig] = (jaxpr, fused)
        return cache[sig]

    compiled._cache = cache
    return compiled


# ----------------------------------------------------------------------------
# 1b. XLA fusion  [SIM]  — count HBM intermediate writes eager vs fused
# ----------------------------------------------------------------------------

class FusionPlan:
    """[SIM] The result of an XLA fusion pass over a jaxpr.

    Real XLA groups a producer-consumer chain of ops into "fusion" kernels so
    that intermediate results flow register-to-register (or via VMEM) instead of
    round-tripping to HBM. This class counts the HBM materialization points in
    each regime so the bandwidth win is exact and printable:

    eager_writes  : EAGER PyTorch materializes EVERY op's output to HBM
                    (1 write per equation).
    fused_writes  : under XLA fusion, a variable is written to HBM ONLY IF it is
                    a function output (0 consumers) or a fan-out point (>=2
                    consumers). A straight-line single-user chain stays on-chip
                    end to end, so only the FINAL result is materialized.

    This is the bandwidth-optimal bound fusion drives toward. (Real XLA may keep
    large GEMM anchors as separate kernels, so the literal floor for two matmuls
    is 2 — but the concept we pin is the collapse from N intermediate writes
    toward 1, which is exactly what the lecture's "all ops fused into the GEMM"
    diagrams depict.) The COUNTS printed here are exact for this model.
    """

    def __init__(self, jaxpr: Jaxpr):
        self.eqns = jaxpr.eqns
        # number of consumers per produced variable
        n_users: dict[str, int] = {}
        for op, ins, out, meta in self.eqns:
            for v in ins:
                n_users[v] = n_users.get(v, 0) + 1
        self.n_users = n_users
        self.eager_writes = len(self.eqns)          # every op -> HBM
        self.fused_writes = 0
        self.materialized: list[str] = []
        for op, ins, out, meta in self.eqns:
            users = n_users.get(out, 0)
            if users != 1:                           # 0 = final output, >=2 = fan-out
                self.fused_writes += 1
                self.materialized.append(out)

    def is_materialized(self, var: str) -> bool:
        return self.n_users.get(var, 0) != 1


def xla_fuse(jaxpr: Jaxpr) -> FusionPlan:
    """[SIM] The XLA fusion pass: return a FusionPlan over the jaxpr."""
    return FusionPlan(jaxpr)


# ----------------------------------------------------------------------------
# 1c. TPU MXU systolic matmul  [SIM-mechanism, exact math]
# ----------------------------------------------------------------------------

def systolic_weight_stationary(W: torch.Tensor, X: torch.Tensor) -> torch.Tensor:
    """[SIM] Weight-stationary systolic matmul C = W @ X, the TPU MXU model.

    W[M,K] are the STATIONARY weights (preloaded into the PE grid once and held
    for the whole matmul). X[K,N] are the activations that STREAM in, skewed
    diagonally across cycles. Partial sums accumulate across the K dimension in
    the PEs' local accumulators — NEVER written back to HBM mid-computation.

    The MATH is exact (asserted == torch.matmul); the mechanism (weight reuse,
    streaming activation, in-place accumulation, no intermediate writeback) is
    the published TPU behaviour. For an N x N grid the wall-clock is the
    fill+drain latency 3N-1 cycles (N to fill the diagonal + N to drain).
    """
    M, K = W.shape
    K2, N = X.shape
    assert K == K2, "inner dims must match"
    C = torch.zeros(M, N, dtype=W.dtype)
    for k in range(K):
        # rank-1 outer-product update: weight column W[:,k] (stationary) meets
        # activation row X[k,:] (streaming); accumulate into C in registers.
        C += W[:, k].unsqueeze(1) * X[k, :].unsqueeze(0)
    return C


# ----------------------------------------------------------------------------
# 1d. Pallas Grid + BlockSpec block matmul  [SIM]
# ----------------------------------------------------------------------------

def pallas_block_matmul(X: torch.Tensor, Y: torch.Tensor,
                        bm: int, bk: int, bn: int) -> torch.Tensor:
    """[SIM] Pallas block matmul mirroring pallas_call(grid, BlockSpec).

    Grid = (m//bm, n//bn, k//bk). The M,N axes are PARALLEL (distributed across
    TPU cores); the K axis is SERIAL (each core accumulates). BlockSpec's
    index_map selects the HBM tile loaded into VMEM at each grid coord. The
    output accumulator lives in VMEM for the whole K-loop and is written back
    to HBM exactly ONCE (at the end) — the single-write-back contract.

    Asserted == torch.matmul(X, Y).
    """
    m, k = X.shape
    _, n = Y.shape
    assert m % bm == 0 and k % bk == 0 and n % bn == 0, "dims must divide tiles"
    Z = torch.zeros(m, n, dtype=X.dtype)
    grid_m, grid_n, grid_k = m // bm, n // bn, k // bk
    for i in range(grid_m):                  # parallel axis M
        for j in range(grid_n):              # parallel axis N
            acc = None                       # VMEM accumulator (lives in VMEM)
            for kk in range(grid_k):         # serial reduction axis K
                # BlockSpec index_maps -> HBM slices copied into VMEM
                x_blk = X[i * bm:(i + 1) * bm, kk * bk:(kk + 1) * bk]
                y_blk = Y[kk * bk:(kk + 1) * bk, j * bn:(j + 1) * bn]
                acc = x_blk @ y_blk if acc is None else acc + x_blk @ y_blk
            Z[i * bm:(i + 1) * bm, j * bn:(j + 1) * bn] = acc   # single write-back
    return Z


# ----------------------------------------------------------------------------
# 1e. Splash Attention == FlashAttention == naive attention  (EXACT math)
#     The SAME tiled online-softmax recurrence as research/flash_attention.py.
# ----------------------------------------------------------------------------

def naive_attention(Q: torch.Tensor, K: torch.Tensor, V: torch.Tensor,
                    scale: float) -> torch.Tensor:
    """Naive attention that MATERIALIZES the full [N,N] score matrix in HBM."""
    scores = (Q @ K.T) * scale                        # [N,N] materialized
    m = scores.max(dim=-1, keepdim=True).values
    exp_scores = torch.exp(scores - m)
    l = exp_scores.sum(dim=-1, keepdim=True)
    probs = exp_scores / l
    return probs @ V


def splash_attention(Q: torch.Tensor, K: torch.Tensor, V: torch.Tensor,
                     scale: float, Br: int, Bc: int) -> torch.Tensor:
    """Splash Attention = tiled online-softmax in Pallas (here in torch).

    MATHEMATICALLY IDENTICAL to FlashAttention: tile Q in row-tiles of size Br,
    stream K,V in col-tiles of size Bc through VMEM, carry running (m, l, o)
    per query row, rescale with exp(m_old - m_new) when the running max rises.
    NEVER materializes the [N,N] matrix in HBM. This is the exact recurrence in
    research/flash_attention.py (🔗); running it here proves the math is
    hardware-agnostic — the same numbers fall out on GPU, TPU, or CPU.
    """
    N, d = Q.shape
    O = torch.zeros(N, d, dtype=Q.dtype)
    Tr = (N + Br - 1) // Br
    Tc = (N + Bc - 1) // Bc
    for i in range(Tr):
        r0 = i * Br
        br = min(Br, N - r0)
        q_tile = Q[r0:r0 + br]
        m_i = torch.full((br,), float("-inf"))
        l_i = torch.zeros(br)
        o_i = torch.zeros(br, d, dtype=Q.dtype)
        for j in range(Tc):
            c0 = j * Bc
            bc = min(Bc, N - c0)
            k_tile = K[c0:c0 + bc]
            v_tile = V[c0:c0 + bc]
            s = (q_tile @ k_tile.T) * scale
            rowmax = s.max(dim=-1).values
            m_new = torch.maximum(m_i, rowmax)
            correction = torch.exp(m_i - m_new)
            p = torch.exp(s - m_new.unsqueeze(-1))
            l_i = correction * l_i + p.sum(dim=-1)
            o_i = correction.unsqueeze(-1) * o_i + p @ v_tile
            m_i = m_new
        O[r0:r0 + br] = o_i / l_i.unsqueeze(-1)
    return O


def make_attention_inputs(seed: int = 0):
    """Deterministic Q,K,V — IDENTICAL to research/flash_attention.py make_inputs
    so the q=0 row matches flash_attention.py's GOLD PIN exactly (the 🔗 proof
    that Splash == Flash == naive across hardware)."""
    g = torch.Generator().manual_seed(seed)
    N, d = 8, 8
    Q = torch.round(torch.randn(N, d, generator=g) * 0.5, decimals=2)
    K = torch.round(torch.randn(N, d, generator=g) * 0.5, decimals=2)
    V = torch.round(torch.randn(N, d, generator=g) * 0.5, decimals=2)
    return Q, K, V


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE SECTIONS  (each prints a banner + a markdown-friendly table)
# ============================================================================

def section_a_eager_vs_trace():
    banner("SECTION A: the eager HBM-write problem (why trace at all?)")
    print("PyTorch on a GPU is EAGER: each op runs the moment Python sees it and\n"
          "writes its result to slow HBM. For a chain like\n\n"
          "    h = x @ W1        # dot_general  -> writes [..,d1] to HBM\n"
          "    h = h + b1        # add          -> writes [..,d1] to HBM\n"
          "    h = silu(h)       # silu         -> writes [..,d1] to HBM\n"
          "    y = h @ W2        # dot_general  -> writes [..,d2] to HBM\n\n"
          "that is FOUR intermediate buffers shuttled through HBM. Each write is\n"
          "bandwidth the GPU pays for nothing — the next op reads it straight back.\n"
          "LLM steps are MEMORY-BANDWIDTH bound, so those round-trips dominate.\n")
    print("JAX's answer: do NOT run the function eagerly. TRACE it once with abstract\n"
          "inputs into a jaxpr (Section B), let XLA FUSE the element-wise chain into\n"
          "one kernel (Section C), so intermediates live only in fast on-chip memory.\n")
    print("| regime | op chain silu(x@W1+b1)@W2 | HBM intermediate writes |")
    print("|---|---|---|")
    print("| EAGER (PyTorch) | each op writes its output to HBM | 4 |")
    print("| TRACED + FUSED (JAX/XLA) | element-wise chain fused; only final writes | 1 |")
    print()
    print("=> 4x fewer HBM round-trips for the SAME math. The rest of this file\n"
          "   shows the mechanism (tracing, fusion, systolic, Pallas) and proves the\n"
          "   math is unchanged (Splash == Flash == naive, Section F).")


def section_b_jaxpr_tracing():
    banner("SECTION B: jaxpr tracing  (@jax.jit + Tracer)  [SIM]")
    print("Real JAX: @jax.jit wraps fn in a PjitFunction. On the FIRST call it hashes\n"
          "the input signature; on a cache MISS it traces the fn with abstract Tracer\n"
          "inputs (shapes only, no data), recording each primitive op into a jaxpr.\n"
          "Source: Frostig, Johnson, Leary, 'Compiling machine learning programs via\n"
          "high-level tracing', SysML 2018 — 'to compile we first monitor its\n"
          "execution once in Python'. (NOTE: this is the formal JAX paper; there is\n"
          "NO arXiv id for it — see Sources.)\n")

    # The function we trace: f(x) = silu(x @ W1 + b1) @ W2  (the fusion gold).
    # Written with explicit Tracer ops so it records the jaxpr without doing math.
    # (Same inline trace is reused in Section C for the fusion pass.)
    jaxpr = Jaxpr()
    x = Tracer((1, 4), "f32", "x", jaxpr)
    W1 = Tracer((4, 8), "f32", "W1", jaxpr)
    b1 = Tracer((1, 8), "f32", "b1", jaxpr)
    W2 = Tracer((8, 4), "f32", "W2", jaxpr)
    h = x.__matmul__(W1)        # dot_general
    h = h.__add__(b1)           # add
    h = h.silu()                # silu
    h.__matmul__(W2)            # dot_general  -> fills jaxpr.eqns, no math

    print(f"The traced jaxpr for  f(x) = silu(x @ W1 + b1) @ W2:\n")
    print(jaxpr)
    print()
    n_eqns = len(jaxpr.eqns)
    n_anchor = sum(1 for e in jaxpr.eqns if e[0] in ANCHOR)
    n_ew = sum(1 for e in jaxpr.eqns if e[0] in ELEMENTWISE)
    print(f"[check] traced eqns = {n_eqns}  (anchors={n_anchor}, element-wise={n_ew})")
    assert n_eqns == 4 and n_anchor == 2 and n_ew == 2
    print("[check] jaxpr has 4 eqns (dot, add, silu, dot):  OK")
    print()
    print("Key: the Tracer ran NO real math — it only RECORDED the op sequence.\n"
          "That recording is the input to the XLA fusion pass (Section C). In real\n"
          "JAX this is cached keyed by (shapes, dtypes); a re-call with the same\n"
          "signature skips tracing and runs the already-compiled binary.")


def section_c_xla_fusion():
    banner("SECTION C: XLA fusion  (eager 4 HBM writes -> fused 1)  [SIM]  GOLD")
    print("XLA takes the jaxpr and FUSES producer-consumer chains so intermediates\n"
          "flow register-to-register instead of round-tripping to HBM. The rule this\n"
          "simulation applies (the bandwidth-optimal bound fusion drives toward):\n\n"
          "  EAGER : every op materializes its output to HBM  (1 write per equation).\n"
          "  FUSED : a variable is written to HBM ONLY IF it is the function output\n"
          "          (0 consumers) or a fan-out (>=2 consumers). A straight-line\n"
          "          single-user chain stays on-chip end to end.\n")
    # re-trace f to get a fresh jaxpr + fusion plan
    jaxpr = Jaxpr()
    x = Tracer((1, 4), "f32", "x", jaxpr)
    W1 = Tracer((4, 8), "f32", "W1", jaxpr)
    b1 = Tracer((1, 8), "f32", "b1", jaxpr)
    W2 = Tracer((8, 4), "f32", "W2", jaxpr)
    h = x.__matmul__(W1)
    h = h.__add__(b1)
    h = h.silu()
    h.__matmul__(W2)
    plan = xla_fuse(jaxpr)

    print("The 4 traced equations and where each result lands:\n")
    print("| # | equation                   | kind        | consumers | writes HBM eager? | writes HBM fused? |")
    print("|---|----------------------------|-------------|-----------|------------------|-------------------|")
    for idx, (op, ins, out, meta) in enumerate(plan.eqns):
        users = plan.n_users.get(out, 0)
        kind = "anchor" if op in ANCHOR else "element-wise"
        cons = "0 (output)" if users == 0 else str(users)
        eager = "YES"
        fused = "YES (final output)" if users == 0 else (
            "YES (fan-out)" if users >= 2 else "no (on-chip)")
        print(f"| {idx} | {out} = {op}({', '.join(ins)}){' '*(24-len(out+op+''.join(ins)))} | "
              f"{kind:<11} | {cons:<9} | {eager:<16} | {fused:<17} |")
    print()
    print(f"eager HBM writes  = {plan.eager_writes}   (one per equation)")
    print(f"fused HBM writes  = {plan.fused_writes}   (only final output materialized)")
    print()
    print("[GOLD PIN] eager = 4 HBM writes  ->  XLA-fused = 1 HBM write   (4 -> 1)")
    assert plan.eager_writes == 4 and plan.fused_writes == 1
    print("[check] eager_writes == 4 AND fused_writes == 1:  OK")
    print()
    print("Read it like a story: dot1's result is consumed only by add -> stays\n"
          "on-chip; add's result is consumed only by silu -> stays on-chip; silu's\n"
          "result is consumed only by dot2 -> stays on-chip; dot2 is the final output\n"
          "-> the ONLY thing written to HBM. Four eager round-trips collapse to one.\n")
    print("[SIM note] real XLA keeps large GEMM anchors as separate kernels, so the\n"
          "literal floor for TWO matmuls is 2. The model above pins the concept —\n"
          "collapse N intermediate writes toward 1 — which is what the lecture's\n"
          "'all ops fused into the GEMM' diagrams depict. The HBM-write COUNTS under\n"
          "this model are exact.")
    return dict(eager=plan.eager_writes, fused=plan.fused_writes)


def section_d_tpu_hardware():
    banner("SECTION D: TPU hardware  (MXU systolic, VMEM, ICI)")
    print("A TPU runs the compiled code on hardware that is nothing like a GPU:\n")
    print("| unit | what it is | GPU analogue |")
    print("|---|---|---|")
    print("| MXU | Matrix multiply Unit: a SYSTOLIC array of MAC PEs (256x256 on real")
    print("|     |  TPU). Weights sit STILL; activations flow through and partial sums")
    print("|     |  accumulate across the grid WITHOUT writing back to memory. | tensor")
    print("|     |  |  cores (but data-flow, not SIMT) |")
    print("| VPU | Vector Processing Unit: 8x128 grid doing element-wise ops (exp, add,")
    print("|     |  max, sum) on VREGs. | the SIMT cores doing element-wise work |")
    print("| VMEM| Vector Memory: fast on-chip scratchpad (~tens of MiB) where tiles")
    print("|     |  live. | GPU SRAM / shared memory |")
    print("| SMEM| Scalar Memory: small, holds scalars + control flow. | scalar regs |")
    print("| ICI | Inter-Chip Interconnect: direct low-latency links between TPU cores")
    print("|     |  (pod-scale AllReduce/AllGather, no host/PCIe round-trip). | NVLink |")
    print()
    print("Source: llmsys-12 lecture (TPU Ironwood: 256x256 MXU, ~0.1 GiB VMEM/core,\n"
          "1200 GB/s ICI) + Jouppi et al. TPU v1 (weight-stationary systolic).\n")

    # ---- demonstrate the MXU systolic mechanism on a tiny 3x3 grid ----
    print("MXU weight-stationary systolic on a 3x3 grid (the teaching model):\n")
    g = torch.Generator().manual_seed(7)
    W = torch.round(torch.randn(3, 3, generator=g), decimals=1)
    X = torch.round(torch.randn(3, 3, generator=g), decimals=1)
    print(f"W (stationary weights, 3x3):\n{W}")
    print(f"X (streaming activations, 3x3):\n{X}\n")
    print("Weight-stationary flow: W[:,k] held fixed; X[k,:] streams in at step k;")
    print("partial sum C += W[:,k] (outer) X[k,:] accumulates in the PEs (no HBM writeback):\n")
    C = torch.zeros(3, 3)
    for k in range(3):
        C = C + W[:, k].unsqueeze(1) * X[k, :].unsqueeze(0)
        print(f"  step k={k}: C += W[:,{k}] (x) X[{k},:]  ->  C =\n{C}")
    print()
    ref = W @ X
    print(f"torch.matmul(W, X) reference:\n{ref}")
    diff = (C - ref).abs().max().item()
    print(f"\n[check] max|systolic - matmul| = {diff:.2e}")
    assert torch.allclose(C, ref, atol=1e-5)
    print("[check] weight-stationary systolic == torch.matmul (atol=1e-5):  OK")
    print()
    print("For an N x N grid the wall-clock is the fill+drain latency = 3N-1 cycles\n"
          "(N cycles to fill the diagonal pipeline + N-1 to drain the last partial\n"
          "sums out). For N=256 that is 767 cycles per dense matmul — but each PE\n"
          "reuses its stationary weight 256 times, which is the whole efficiency win.")


def section_e_pallas_grid_blockspec():
    banner("SECTION E: Pallas Grid + BlockSpec  (HBM <-> VMEM tiling)  [SIM]")
    print("Pallas is the TPU kernel language. Three pieces:\n")
    print("  Grid      : the parallel index space. prod(grid) kernel launches. The first")
    print("              axes are PARALLEL (spread across TPU cores); the LAST axis is")
    print("              the SERIAL reduction axis (each core accumulates along it).")
    print("  BlockSpec : (block_shape, index_map) — for each grid coord, which HBM tile")
    print("              gets copied into VMEM. Pallas pipelines the next HBM->VMEM copy")
    print("              while the current tile computes (overlap I/O with compute).")
    print("  kernel    : runs on VMEM refs only; writes the output ref. The output")
    print("              accumulator lives in VMEM for the whole K-loop and is written")
    print("              back to HBM exactly ONCE (single write-back).\n")
    print("Why Pallas? XLA's auto-fusion can leave the MXU idle during softmax's exp/sum")
    print("(the VPU bottlenecks). Pallas gives explicit control over HBM<->VMEM so the")
    print("whole Scale->Softmax->V chain stays on-chip (=> Splash Attention, Section F).\n")

    g = torch.Generator().manual_seed(11)
    X = torch.round(torch.randn(4, 4, generator=g), decimals=1)
    Y = torch.round(torch.randn(4, 4, generator=g), decimals=1)
    bm = bk = bn = 2
    print(f"Block matmul  X(4,4) @ Y(4,4)  with tiles bm=bk=bn={bm}:")
    print(f"  grid = (m//bm, n//bn, k//bk) = ({4//bm},{4//bn},{4//bk})  "
          f"= { (4//bm)*(4//bn)*(4//bk)} kernel launches\n")
    Z = pallas_block_matmul(X, Y, bm, bk, bn)
    print(f"Pallas block result Z:\n{Z}")
    ref = X @ Y
    print(f"torch.matmul(X, Y) reference:\n{ref}")
    diff = (Z - ref).abs().max().item()
    print(f"\n[check] max|pallas_block - matmul| = {diff:.2e}")
    assert torch.allclose(Z, ref, atol=1e-5)
    print("[check] Pallas block matmul == torch.matmul (atol=1e-5):  OK")
    print()
    print("The BlockSpec index_map is the HBM->VMEM mapping; the kernel's output ref")
    print("is the VMEM accumulator; only ONE write-back to HBM happens per output tile.")


def section_f_splash_attention(Q, K, V, scale):
    banner("SECTION F: Splash Attention == FlashAttention == naive  (GOLD centerpiece)")
    print("Splash Attention is the tiled online-softmax attention kernel written in\n"
          "Pallas for the TPU. Its recurrence is MATHEMATICALLY IDENTICAL to\n"
          "FlashAttention (the GPU version): tile Q in row-tiles, stream K,V in\n"
          "col-tiles through VMEM, carry running (m, l, o) per query row, and rescale\n"
          "with exp(m_old - m_new) when the running max rises. The [N,N] score matrix\n"
          "is NEVER written to HBM. (🔗 FLASH_ATTENTION.md — same math, GPU vs TPU.)\n")
    N, d = Q.shape
    print(f"Inputs: N={N}, d={d}, scale=1/sqrt(d)={scale:.4f}, Br=Bc=4 "
          f"(=> Tr={N//4} Q-tiles, Tc={N//4} K/V-tiles)\n")
    print("Anchor recurrence (web-verified — identical to flash_attention.py):")
    print("  m_new = max(m_old, rowmax(s))")
    print("  p     = exp(s - m_new)")
    print("  l_new = exp(m_old - m_new) * l_old + rowsum(p)")
    print("  o_new = exp(m_old - m_new) * o_old + p @ v_tile")
    print("  final: out_row = o / l\n")
    naive = naive_attention(Q, K, V, scale)
    splash = splash_attention(Q, K, V, scale, Br=4, Bc=4)
    diff = (splash - naive).abs().max().item()
    print("Tiled (Splash) output, row q=0:")
    print(f"  [{', '.join(f'{v:+.4f}' for v in splash[0].tolist())}]")
    print("Naive output,          row q=0:")
    print(f"  [{', '.join(f'{v:+.4f}' for v in naive[0].tolist())}]")
    print()
    print(f"[check] max|splash - naive| over all 64 entries = {diff:.2e}")
    assert torch.allclose(splash, naive, atol=1e-5)
    print("[check] Splash Attention == naive attention (atol=1e-5):  OK  (EXACT)")
    print()
    # The cross-bundle identity: q=0 MUST equal flash_attention.py's GOLD PIN
    flash_q0 = [-0.0673, -0.1466, -0.2175, +0.0201, +0.1810,
                -0.1534, +0.2226, -0.0995]
    match = all(abs(splash[0, c].item() - flash_q0[c]) < 5e-4 for c in range(8))
    print(f"[check] Splash q=0 == flash_attention.py GOLD PIN:  {'OK' if match else 'FAIL'}")
    assert match
    print("       (same seed=0 inputs => identical numbers => the math is")
    print("        hardware-agnostic: GPU (Flash), TPU (Splash), CPU (here) agree.)")
    return splash


def section_g_eager_vs_fused_writes(gold):
    banner("SECTION G: eager vs fused HBM-write scaling  (the 4 -> 1 win generalizes)")
    print("The fusion win scales with the LENGTH of the element-wise chain fused.\n"
          "For a chain of E element-wise ops hanging off one matmul anchor, eager\n"
          "writes (E+1) intermediate buffers; XLA fuses them so only the final\n"
          "result writes HBM. The win ratio is (E+1) : 1.\n")
    print("| element-wise ops fused (E) | eager HBM writes | fused HBM writes | win |")
    print("|---|---|---|---|")
    for E in [0, 1, 2, 3, 5, 9]:
        eager = E + 1
        fused = 1
        print(f"| {E} | {eager} | {fused} | {eager}x |")
    print()
    print(f"Our gold f(x)=silu(x@W1+b1)@W2 has E=2 element-wise ops (add, silu) ->\n"
          f"eager {gold['eager']} writes, fused {gold['fused']} write, a {gold['eager']}x win.\n")
    print("Caveat: fusion only helps the MEMORY-BANDWIDTH-bound part. A pure matmul\n"
          "is compute-bound and fuses little. The big real-world win is exactly the\n"
          "attention/MLP epilogues (bias, activation, residual, layernorm) that XLA\n"
          "stitches onto their matmuls — and the extreme case, where the WHOLE softmax\n"
          "stays on-chip, is Splash Attention (Section F), which XLA auto-fusion cannot\n"
          "quite reach (it leaves the MXU idle during exp/sum) — hence Pallas.")
    print()
    print("Put the three regimes side by side:")
    print("| regime | who runs the op chain | HBM writes for silu(x@W1+b1)@W2 |")
    print("|---|---|---|")
    print("| EAGER PyTorch/CUDA | each op launched separately from Python | 4 |")
    print("| JAX + XLA fusion | element-wise chain fused into the matmul kernel | 1 |")
    print("| JAX + Pallas (Splash) | whole softmax stays in VMEM, one write-back | 1 |")
    print()
    print("=> 🔗 CUDA_GRAPHS.md solves the LAUNCH-overhead problem (many kernels -> 1).")
    print("   JAX/XLA fusion solves the MEMORY-bandwidth problem (many HBM writes -> 1).")
    print("   Both collapse 'many small things' into 'one big thing' — different axes.")


# ============================================================================
# main
# ============================================================================

def main():
    print("jax_xla_tpu.py - JAX/XLA/TPU pipeline + Splash Attention (faithful sim).\n"
          "torch =", torch.__version__)
    print("PLATFORM: NO TPU / NO real JAX on this Mac. Tracing, fusion, systolic,\n"
          "and Pallas Grid/BlockSpec are SIMULATED [SIM]; the Splash=Flash online-\n"
          "softmax MATH and the HBM-write COUNTS are EXACT. See JAX_XLA_TPU.md.\n")

    section_a_eager_vs_trace()
    section_b_jaxpr_tracing()
    gold_fusion = section_c_xla_fusion()
    section_d_tpu_hardware()
    section_e_pallas_grid_blockspec()

    Q, K, V = make_attention_inputs(seed=0)
    scale = 1.0 / math.sqrt(Q.shape[1])
    gold_splash = section_f_splash_attention(Q, K, V, scale)

    section_g_eager_vs_fused_writes(gold_fusion)

    banner("GOLD PIN (for JAX_XLA_TPU.md + jax_xla_tpu.html)")
    print(f"Gold 1 (XLA fusion):  eager HBM writes = {gold_fusion['eager']}  ->  "
          f"fused = {gold_fusion['fused']}   (4 -> 1)")
    print(f"Gold 2 (Splash == Flash == naive):  q=0 out[0] = {gold_splash[0,0].item():+.4f}  "
          f"(== flash_attention.py GOLD PIN -0.0673)")

    banner("DONE - all sections printed, all [check] OK")


if __name__ == "__main__":
    main()
