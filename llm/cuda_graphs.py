"""
cuda_graphs.py - Faithful simulation of CUDA Graphs for LLM decode.

This is the single source of truth that CUDA_GRAPHS.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python cuda_graphs.py

============================================================================
PLATFORM NOTE — read me first  (labelled [SIM] everywhere below)
============================================================================
This machine is Apple Silicon with NO CUDA device, so torch.cuda.CUDAGraph
cannot run for real. This file FAITHFULLY SIMULATES the capture/replay
MECHANISM in pure Python (a recorded ordered list of GPU "ops" that is
captured once and replayed verbatim), AND computes the REAL launch-overhead
arithmetic using PUBLISHED figures (~5-20 us per kernel launch on PCIe gen3
GPUs, ~few-us single graph launch, ~50-100 kernels per decode step). The
CONCEPT and the MATH are the point of the repo philosophy (tiny-but-complete,
every number printable). Nothing here pretends to run a real CUDA graph; the
overhead numbers are the real published ones, and the simulation is
deterministic.

============================================================================
THE IDEA IN PLAIN ENGLISH (full version: CUDA_GRAPHS.md section 0)
============================================================================
In EAGER mode every decode step re-issues ~50-100 GPU kernels through the
Python interpreter. Each kernel launch costs ~5-20 us of CPU->GPU overhead
(driver call, argument packing, scheduling). At batch_size=1 with 72 kernels
that is 72 x 10 us = 720 us of PURE launch overhead per step — a large slice
of decode time, wasted entirely on CPU bookkeeping that produces no FLOPs.

CUDA Graphs CAPTURE the kernel sequence once (per batch size) into a graph,
then REPLAY it with a SINGLE GPU call and ~zero Python overhead. The same
72 kernels now cost ~5 us total to launch instead of ~720 us.

WHY: at small/medium batch, launch overhead is a big fraction of decode time;
graphs eliminate it. (At very large batch, compute dominates and graphs help
less — see Section F.)

WHAT THIS FILE PROVES (with numbers):
  - Eager launch overhead = N_kernels x launch_latency   (e.g. 72 x 10 = 720 us)
  - Graph replay overhead ~ single launch                (~5 us)
  - Launch-overhead speedup = N_kernels (e.g. 720/5 = 144x for that component)
  - Total decode-step speedup is more modest (compute is unchanged): for the
    tiny model below ~2x, and for production ms-scale models ~1.1-1.2x,
    matching vLLM's published ~12-17% decode-latency drop at small batch.
  - The win SHRINKS as batch grows: launch overhead is FIXED per step, compute
    grows ~linearly with batch, so overhead's fraction -> 0 at large batch.
  - One graph per batch size is pre-captured; at runtime the smallest captured
    graph >= current batch is selected (graph_bs = [1,2,4,8,16,...]).
  - Replay copies new inputs INTO the graph's PRE-ALLOCATED tensors in-place,
    then graph.replay(); outputs land in pre-allocated output tensors.
  - The slot_mapping.fill_(-1) padding trick marks unused slots when current
    batch < captured batch (connects to PAGED_ATTENTION / KV_CACHE).

ANCHOR FORMULAS (web-verified, see CUDA_GRAPHS.md "## Sources"):
  eager_launch_us  = N_kernels * launch_us_per_kernel
  graph_launch_us  = graph_replay_us          # a single cudaGraphLaunch
  launch_speedup   = eager_launch_us / graph_launch_us
  eager_total_us   = eager_launch_us + compute_us
  graph_total_us   = graph_launch_us + compute_us   # compute identical
  total_speedup    = eager_total_us / graph_total_us

GLOSSARY (defined at first use in CUDA_GRAPHS.md):
    kernel        a GPU function (matmul, layernorm, attention, ...) launched
                  from the CPU.
    launch        the CPU->GPU call that asks the GPU to run a kernel. Costs a
                  few us of driver/driver overhead each time.
    eager mode    PyTorch runs each op as it is encountered -> N launches/step.
    graph         a frozen DAG of GPU ops captured once, replayable as a unit.
    capture       recording the op sequence (with torch.cuda.graph()) - done ONCE.
    replay        re-running the captured sequence with one cudaGraphLaunch call.
    warmup        a throwaway run before capture that primes allocators / JIT;
                  NOT captured.
    decode        generation phase: 1 new token per sequence per step (FIXED shape).
    prefill       first pass over the prompt (VARIABLE length) -> NOT captured.
    graph_bs      the set of batch sizes a graph is pre-captured for.
    graph_vars    the dict of PRE-ALLOCATED input/output tensors the graph reuses.

Conventions (tiny model so EVERY number prints):
    num_layers       = 24     (a small LLM, e.g. Qwen2.5-0.5B has 24 layers)
    kernels/layer    = 3      (simplified bundle: attn_qkv, attn_score, mlp_ffn)
    N_kernels        = 72     (num_layers x kernels/layer)
    launch_us/kernel = 10     (real published mid-range figure, see Sources)
    graph_replay_us  = 5      (single graph launch ~ a few us)
    compute_us/kernel= 8      (illustrative tiny-model value; real decode is
                               bandwidth-bound on weight reads and runs ms-scale)
"""

from __future__ import annotations

import contextlib

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# Published overhead figures (web-verified, see CUDA_GRAPHS.md ## Sources).
# These are the REAL numbers a GPU would show; only the graph mechanism is [SIM].
# ----------------------------------------------------------------------------
LAUNCH_US_PER_KERNEL = 10.0      # ~5-14 us on PCIe gen3 (NVIDIA forums)
GRAPH_REPLAY_US = 5.0            # a single cudaGraphLaunch ~ few us
COMPUTE_US_PER_KERNEL = 8.0      # decode is bandwidth-bound, small per-kernel


# ============================================================================
# 1. THE SIMULATION  (this is the code CUDA_GRAPHS.md walks through)
#    [SIM] = simulated, not a real torch.cuda.CUDAGraph. The MECHANISM (capture
#    a frozen op list once, replay verbatim) and the MATH (real us figures)
#    are the point.
# ============================================================================

class Kernel:
    """One GPU kernel: a name + a (tiny) simulated compute time. The POINT of
    this file is LAUNCH overhead, not compute, so compute is kept small."""

    def __init__(self, name: str, compute_us: float = COMPUTE_US_PER_KERNEL):
        self.name = name
        self.compute_us = compute_us


class DecodeModel:
    """A tiny decode forward pass: num_layers layers, each emitting a FIXED
    sequence of kernels. The kernel sequence is IDENTICAL at every batch size
    (only the data changes) -- THIS is exactly what a graph can capture.

    kernels_per_layer=3 is a simplified bundle of the real ~5-6 ops/layer:
        attn_qkv   : input-norm + Q/K/V projection + RoPE
        attn_score : FlashAttention varlen decode + output projection
        mlp_ffn    : RMSNorm + MLP gate/up + MLP down
    Real models have MORE kernels/layer (so the launch win is even bigger).
    """

    def __init__(self, num_layers: int = 24, kernels_per_layer: int = 3):
        self.num_layers = num_layers
        self.kernels_per_layer = kernels_per_layer
        self.kernels: list[Kernel] = []
        for lyr in range(num_layers):
            self.kernels.append(Kernel(f"L{lyr:02d} attn_qkv"))
            if kernels_per_layer >= 2:
                self.kernels.append(Kernel(f"L{lyr:02d} attn_score"))
            if kernels_per_layer >= 3:
                self.kernels.append(Kernel(f"L{lyr:02d} mlp_ffn"))
            # any extra kernels_per_layer beyond 3 get generic names
            for extra in range(3, kernels_per_layer):
                self.kernels.append(Kernel(f"L{lyr:02d} k{extra}"))
        self.n_kernels = len(self.kernels)

    def forward(self, active_graph: "SimGraph | None" = None):
        """Emit the fixed kernel sequence. If `active_graph` is capturing, each
        kernel is RECORDED into the graph (not launched). Otherwise it is
        'launched' eagerly (we just count)."""
        for kern in self.kernels:
            if active_graph is not None and active_graph.capturing:
                active_graph.ops.append(kern)          # [SIM] record, don't launch
            # eager path: the launch would happen here (counted in latency math)


class SimGraph:
    """[SIM] A captured CUDA graph: a frozen ordered list of GPU kernels +
    references to the PRE-ALLOCATED tensor objects it reads/writes. Built ONCE
    during capture, replayed verbatim any number of times.

    On real hardware this is torch.cuda.CUDAGraph; here it is a plain Python
    list so the capture/replay MECHANISM is fully visible and deterministic.
    """

    def __init__(self, bs: int):
        self.bs = bs
        self.ops: list[Kernel] = []
        self.capturing = False
        self.replay_count = 0
        # pre-allocated fixed tensors the graph reads/writes (real HW: same addrs)
        self.input_ids = torch.zeros(bs, dtype=torch.int64)
        self.positions = torch.zeros(bs, dtype=torch.int64)
        self.slot_mapping = torch.full((bs,), -1, dtype=torch.int32)
        self.outputs = torch.zeros(bs, 64)             # hidden_size stub

    def replay(self) -> int:
        """[SIM] On real HW: ONE cudaGraphLaunch replays ALL ops. Here we walk
        the list (the cost is the single graph-launch latency, not per-op)."""
        self.replay_count += 1
        return len(self.ops)


class GraphStore:
    """Holds one captured SimGraph per batch size, exactly like nano-vllm's
    capture_cudagraph(): graph_bs = [1,2,4,8] + range(16, max_bs+1, 16), and at
    run time we select the smallest captured graph >= current bs.

    Source mirrored: ../nano-vllm/nanovllm/engine/model_runner.py
    """

    def __init__(self, model: DecodeModel, max_bs: int = 32):
        self.model = model
        self.max_bs = max_bs
        self.graph_bs = [1, 2, 4, 8] + list(range(16, max_bs + 1, 16))
        self.graphs: dict[int, SimGraph] = {}
        self._capture_all()

    def _capture_all(self):
        """[SIM] mirrors capture_cudagraph(): for each bs, warmup then capture."""
        # reversed so the largest graph's pool is shared (real HW optimization)
        for bs in reversed(self.graph_bs):
            graph = SimGraph(bs)
            # 1) warmup run (NOT captured) -- primes allocators / cuDNN / JIT
            self.model.forward(active_graph=None)
            # 2) capture the GPU command sequence
            graph.capturing = True
            self.model.forward(active_graph=graph)
            graph.capturing = False
            self.graphs[bs] = graph

    def select_graph_bs(self, current_bs: int) -> int:
        """Smallest captured batch size >= current_bs (mirrors run_model)."""
        return next(x for x in self.graph_bs if x >= current_bs)

    def replay(self, current_bs: int):
        """[SIM] mirrors run_model(): copy new inputs into the pre-allocated
        tensors in-place, fill slot_mapping padding, then graph.replay()."""
        graph_bs = self.select_graph_bs(current_bs)
        graph = self.graphs[graph_bs]
        # in-place updates into the SAME tensor objects the graph captured
        graph.input_ids[:current_bs].copy_(torch.arange(current_bs))
        graph.positions[:current_bs].copy_(torch.arange(current_bs))
        graph.slot_mapping.fill_(-1)                    # -1 = padding
        graph.slot_mapping[:current_bs].copy_(
            torch.arange(current_bs, dtype=torch.int32))
        n_ops = graph.replay()
        return graph_bs, graph, n_ops


# ----------------------------------------------------------------------------
# latency arithmetic (REAL published us figures)
# ----------------------------------------------------------------------------

def eager_launch_us(model: DecodeModel,
                    launch_us: float = LAUNCH_US_PER_KERNEL) -> float:
    """CPU->GPU launch overhead per eager decode step = N_kernels x launch."""
    return model.n_kernels * launch_us


def graph_launch_us(graph_replay_us: float = GRAPH_REPLAY_US) -> float:
    """Launch overhead per graphed decode step = a single graph launch."""
    return graph_replay_us


def compute_us(model: DecodeModel,
               compute_us_per_kernel: float = COMPUTE_US_PER_KERNEL) -> float:
    """The actual GPU compute (bandwidth-bound at decode; identical eager/graph)."""
    return model.n_kernels * compute_us_per_kernel


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

def section_a_the_problem(model: DecodeModel):
    banner("SECTION A: the eager launch-overhead problem (real us arithmetic)")
    n = model.n_kernels
    print(f"Model: num_layers={model.num_layers}, "
          f"kernels_per_layer={model.kernels_per_layer}, "
          f"N_kernels={n}")
    print(f"Published figures: launch={LAUNCH_US_PER_KERNEL:.0f} us/kernel "
          f"(PCIe gen3, NVIDIA forums), "
          f"compute~{COMPUTE_US_PER_KERNEL:.0f} us/kernel (decode bw-bound).\n")
    print("Every eager decode step, the Python interpreter asks the GPU to run")
    print(f"each of the {n} kernels one at a time. Each 'ask' (a kernel launch)")
    print("costs CPU->GPU driver overhead that produces ZERO FLOPs:\n")
    print(f"| per eager decode step          | value (us)  |")
    print(f"|--------------------------------|-------------|")
    print(f"| N_kernels                      | {n:<11} |")
    print(f"| x launch latency per kernel    | {LAUNCH_US_PER_KERNEL:<11.1f} |")
    print(f"| = EAGER LAUNCH OVERHEAD        | {eager_launch_us(model):<11.0f} |")
    print(f"|   (pure CPU bookkeeping, 0 FLOPs) |           |")
    print(f"| + actual compute (unchanged)   | {compute_us(model):<11.0f} |")
    print(f"| = EAGER STEP TOTAL             | {eager_launch_us(model)+compute_us(model):<11.0f} |")
    print()
    frac = eager_launch_us(model) / (eager_launch_us(model) + compute_us(model)) * 100
    print(f"=> {frac:.1f}% of an eager decode step is wasted on launch overhead")
    print(f"   ({eager_launch_us(model):.0f} us out of "
          f"{eager_launch_us(model)+compute_us(model):.0f} us). That is the tax")
    print("   CUDA Graphs delete.")


def section_b_capture(model: DecodeModel):
    banner("SECTION B: capture flow  (warmup -> record -> store)  [SIM]")
    print("CUDA Graph capture records the GPU command sequence ONCE into a frozen\n"
          "graph. Two mandatory phases (skip either and capture is broken):\n")
    print("  1) WARMUP run (NOT captured): runs model() once to prime the memory\n"
          "     allocator, cuDNN/cuBLAS handles, and JIT-compile any PTX. If you\n"
          "     skip this, the graph captures un-initialized lazy state.\n"
          "  2) CAPTURE run: under `with torch.cuda.graph(graph, pool):` every\n"
          "     kernel the model emits is APPENDED to the graph instead of\n"
          "     launched. NO allocation may happen inside the graph.\n")
    # demonstrate the [SIM] capture for bs=1
    graph = SimGraph(bs=1)
    print(f"[SIM] Capturing a graph for bs={graph.bs}:")
    print(f"  ops before warmup : {len(graph.ops)}")
    model.forward(active_graph=None)                   # warmup (not recorded)
    print(f"  ops after warmup  : {len(graph.ops)}   (warmup is NOT captured)")
    graph.capturing = True
    model.forward(active_graph=graph)                  # capture
    graph.capturing = False
    print(f"  ops after capture : {len(graph.ops)}   "
          f"(== N_kernels = {model.n_kernels})\n")
    assert len(graph.ops) == model.n_kernels
    print("[check] captured ops == N_kernels:  OK\n")
    print("First 6 captured ops:")
    for i in range(min(6, len(graph.ops))):
        print(f"  [{i:2d}] {graph.ops[i].name}")
    print(f"  ... ({len(graph.ops) - 6} more)\n")
    print("On real HW, graph.replay() re-issues ALL of these with ONE call. The")
    print("graph now holds a frozen pointer to the SAME input/output tensors; to")
    print("change inputs you copy data INTO them in-place (Section D).")


def section_c_one_graph_per_bs(model: DecodeModel):
    banner("SECTION C: one graph per batch size + selection at replay  [SIM]")
    print("A captured graph is shape-specific: a graph for bs=8 will NOT run a\n"
          "bs=3 batch. So we pre-capture a small set of batch sizes and, at run\n"
          "time, select the SMALLEST captured graph >= the current batch:\n")
    print("Source: ../nano-vllm/.../model_runner.py capture_cudagraph()\n")
    print("    self.graph_bs = [1, 2, 4, 8] + list(range(16, max_bs+1, 16))\n")
    store = GraphStore(model, max_bs=32)
    print(f"Pre-captured graphs (max_bs={store.max_bs}):")
    print(f"| captured bs | captured ops (= N_kernels) |")
    print(f"|-------------|----------------------------|")
    for bs in store.graph_bs:
        g = store.graphs[bs]
        print(f"| {bs:<11} | {len(g.ops):<26} |")
    print()
    print("Selection at run time (current batch -> which graph replays):")
    print("| current bs | selected graph_bs | wasted slots |")
    print("|------------|-------------------|--------------|")
    cases = [1, 2, 3, 5, 8, 10, 17, 24]
    for cur in cases:
        gbs = store.select_graph_bs(cur)
        print(f"| {cur:<10} | {gbs:<17} | {gbs - cur:<12} |")
    print()
    print("Wasted slots (graph_bs - current_bs) are why Section G's -1 padding")
    print("trick exists: the graph always runs `graph_bs` slots, and the unused")
    print("ones must be marked so the attention kernel ignores them.")


def section_d_replay(model: DecodeModel):
    banner("SECTION D: replay = in-place copy + graph.replay()  [SIM]")
    store = GraphStore(model, max_bs=8)
    print("Replay flow (mirrors run_model()): the graph reuses its PRE-ALLOCATED\n"
          "input/output tensors. You OVERWRITE their contents in-place, then call\n"
          "graph.replay(). The graph reads/writes the SAME tensor addresses it\n"
          "captured -- you must NOT replace the tensor object, only its data.\n")
    cur_bs = 3
    gbs, graph, n_ops = store.replay(cur_bs)
    print(f"Replay for current_bs={cur_bs} -> selected graph_bs={gbs}")
    print(f"  graph.input_ids   (captured tensor, shape [{gbs}]):")
    print(f"    data : {graph.input_ids.tolist()}")
    print(f"  graph.positions   (shape [{gbs}]):")
    print(f"    data : {graph.positions.tolist()}")
    print(f"  graph.slot_mapping (shape [{gbs}]):")
    print(f"    data : {graph.slot_mapping.tolist()}   "
          f"(-1 marks the {gbs - cur_bs} padding slots)")
    print(f"  graph.replay() -> re-issued {n_ops} kernels in ONE call\n")
    assert graph.slot_mapping[cur_bs:].tolist() == [-1] * (gbs - cur_bs)
    print("[check] padding slots (>= current_bs) are all -1:  OK")
    assert graph.replay_count == 1
    print(f"[check] replay_count == 1 after one replay:  OK\n")
    print(f"vs EAGER: those {n_ops} kernels would have been {n_ops} separate "
          f"CPU->GPU launches. With the graph it is exactly 1. The per-step")
    print("launch cost drops from N_kernels x launch_us to a single graph "
          "launch (Section F).")


def section_e_limitations():
    banner("SECTION E: limitations (why graphs are decode-only, fixed-shape)")
    print("CUDA Graphs are powerful but strict. Break a rule and you get either a\n"
          "hard error or silent corruption.\n")
    print("| # | rule                                  | why                       |")
    print("|---|---------------------------------------|---------------------------|")
    rows = [
        ("1", "DECODE only, not prefill",
         "prefill length varies per request -> shape not fixed -> cannot capture"),
        ("2", "fixed input shapes",
         "the graph bakes in tensor shapes/strides; changing them = illegal mem access"),
        ("3", "no allocation inside the graph",
         "cudaMalloc is a host call; the graph is pure device work"),
        ("4", "inputs must be the SAME tensor objects",
         "replay reads captured addresses; you overwrite data in-place, never swap tensors"),
        ("5", "warmup before capture is mandatory",
         "skip it and the graph captures un-initialized lazy/cuDNN state"),
        ("6", "bs cap (e.g. >512 falls back to eager)",
         "huge batches are compute-bound anyway; capture cost not worth it"),
    ]
    for n, rule, why in rows:
        print(f"| {n} | {rule:<37} | {why:<25} |")
    print()
    print("Net: graphs accelerate the FIXED-SHAPE, REPETITIVE decode loop. The")
    print("scheduler's continuous batching (🔗 SCHEDULER.md) still runs in Python")
    print("on the CPU; only the model forward inside one decode step is graphed.")


def section_f_speedup_math(model: DecodeModel):
    banner("SECTION F: eager vs captured timeline + speedup math  (GOLD centerpiece)")
    n = model.n_kernels
    eager_launch = eager_launch_us(model)
    graph_launch = graph_launch_us()
    comp = compute_us(model)
    eager_total = eager_launch + comp
    graph_total = graph_launch + comp
    launch_speedup = eager_launch / graph_launch
    total_speedup = eager_total / graph_total
    print(f"N_kernels={n}, launch={LAUNCH_US_PER_KERNEL:.0f} us/kernel, "
          f"graph_replay={GRAPH_REPLAY_US:.0f} us, compute={COMPUTE_US_PER_KERNEL:.0f} us/kernel\n")
    print("Per-step timeline (us), batch=1 decode:\n")
    print("| phase                  | EAGER        | GRAPHED     |")
    print("|------------------------|--------------|-------------|")
    print(f"| launch overhead        | {eager_launch:<12.0f}  | {graph_launch:<11.0f} |")
    print(f"| actual compute (same)  | {comp:<12.0f}  | {comp:<11.0f} |")
    print(f"| STEP TOTAL             | {eager_total:<12.0f}  | {graph_total:<11.0f} |")
    print()
    print("Two different speedups (do not conflate them):\n")
    print(f"| metric                          | value     |")
    print(f"|---------------------------------|-----------|")
    print(f"| LAUNCH-overhead speedup         | {launch_speedup:<9.1f} |   "
          f"({eager_launch:.0f}/{graph_launch:.0f})")
    print(f"| TOTAL step speedup (compute     | {total_speedup:<9.3f} |   "
          f"({eager_total:.0f}/{graph_total:.0f})")
    print(f"|   unchanged)                    |           |")
    print()
    print(f"The launch component is {launch_speedup:.0f}x cheaper; the whole step")
    print(f"is only {total_speedup:.2f}x faster here because compute (the same in")
    print("both) is non-trivial. For production models where per-token WEIGHT")
    print("READING dominates (ms-scale, not us-scale), the total speedup shrinks")
    print("into the ~10-20% decode-latency drop vLLM reports -- the launch tax is")
    print("a fixed us cost that matters most at small batch (see table below).")
    print()
    # ---- the batch-scaling insight: overhead fraction shrinks with batch ----
    print("Batch scaling: launch overhead is FIXED per step; compute grows ~linearly")
    print("with batch. So graphs help MOST at small batch, least at large batch.\n")
    print("| batch | compute grows? | launch (fixed) | launch frac (eager) | "
          "total speedup |")
    print("|-------|----------------|----------------|---------------------|"
          "---------------|")
    for bs in [1, 2, 4, 8, 16, 32, 64]:
        comp_b = comp * bs                  # compute scales with batch
        e_tot = eager_launch + comp_b
        g_tot = graph_launch + comp_b
        frac = eager_launch / e_tot * 100
        sp = e_tot / g_tot
        print(f"| {bs:<5} | {'yes' if bs > 1 else 'baseline':<14} | "
              f"{eager_launch:<14.0f} | {frac:<19.1f} | {sp:<13.3f} |")
    print()
    print("Read the table: at batch=1 the launch overhead is "
          f"{eager_launch/(eager_launch+comp)*100:.1f}% of the step; by batch=64")
    print("it is negligible. This is why serving engines graph the small-batch")
    print("decode path but fall back to eager once batch > the capture cap.\n")
    return dict(n=n, eager_launch=eager_launch, graph_launch=graph_launch,
                comp=comp, eager_total=eager_total, graph_total=graph_total,
                launch_speedup=launch_speedup, total_speedup=total_speedup)


def section_g_slot_mapping_padding(model: DecodeModel):
    banner("SECTION G: the slot_mapping.fill_(-1) padding trick  "
           "(link KV_CACHE / PAGED_ATTENTION)")
    print("When current_bs < graph_bs, the graph still runs `graph_bs` slots. The\n"
          "unused slots' KV-write addresses must be marked so the paged-attention\n"
          "kernel SKIPS them. The convention (from nano-vllm run_model()) is:\n\n"
          "    graph_vars['slot_mapping'].fill_(-1)            # mark ALL padding\n"
          "    graph_vars['slot_mapping'][:bs].copy_(real)     # then write real\n\n"
          "slot_mapping[i] = the physical KV-block slot token i writes into. A\n"
          "value of -1 means 'no token here -- do not write'.\n")
    print("[SIM] captured graph_bs=8, replaying current_bs=3:\n")
    gbs = 8
    cur_bs = 3
    slot_mapping = torch.full((gbs,), -1, dtype=torch.int32)   # fill_(-1)
    real_slots = torch.tensor([4, 17, 9], dtype=torch.int32)   # from block_table
    slot_mapping[:cur_bs].copy_(real_slots)
    print(f"  real_slots (from block_table)  : {real_slots.tolist()}")
    print(f"  graph slot_mapping after fill+copy : {slot_mapping.tolist()}\n")
    print("| slot idx | slot_mapping | token? | kernel action           |")
    print("|----------|--------------|--------|------------------------|")
    for i in range(gbs):
        sm = slot_mapping[i].item()
        if sm >= 0:
            tok = f"token {i}"
            act = f"write KV to physical slot {sm}"
        else:
            tok = "(padding)"
            act = "SKIP (slot == -1)"
        print(f"| {i:<8} | {sm:<12} | {tok:<6} | {act:<22} |")
    print()
    assert slot_mapping[cur_bs:].tolist() == [-1] * (gbs - cur_bs)
    assert slot_mapping[:cur_bs].tolist() == [4, 17, 9]
    print("[check] padding region all -1 AND real region == [4,17,9]:  OK\n")
    print("Without this trick, the padding slots would write garbage KV into")
    print("random physical memory -> silent corruption of OTHER sequences' caches.")
    print("Same -1 sentinel is used for context_lens / block_tables padding.")
    print("-> 🔗 PAGED_ATTENTION.md (slot = block_id x block_size + offset)")
    print("-> 🔗 KV_CACHE.md (the block_table that produces these slot ids)")


# ============================================================================
# main
# ============================================================================

def main():
    print("cuda_graphs.py - faithful CUDA-Graph simulation + real overhead math.\n"
          "torch =", torch.__version__)
    print("PLATFORM: this machine has NO CUDA device. The graph capture/replay\n"
          "MECHANISM is simulated in pure Python [SIM]; the latency figures are\n"
          "the REAL published ones. See CUDA_GRAPHS.md ## Sources.\n")

    model = DecodeModel(num_layers=24, kernels_per_layer=3)

    section_a_the_problem(model)
    section_b_capture(model)
    section_c_one_graph_per_bs(model)
    section_d_replay(model)
    section_e_limitations()
    gold = section_f_speedup_math(model)
    section_g_slot_mapping_padding(model)

    banner("GOLD PIN (for CUDA_GRAPHS.md + cuda_graphs.html)")
    print(f"Pinned numbers (num_layers=24, kernels/layer=3 -> N_kernels={gold['n']}):")
    print(f"  eager_launch_us  = N x launch = {gold['n']} x {LAUNCH_US_PER_KERNEL:.0f} "
          f"= {gold['eager_launch']:.0f} us")
    print(f"  graph_launch_us  = single replay   = {gold['graph_launch']:.0f} us")
    print(f"  launch_speedup   = {gold['eager_launch']:.0f} / {gold['graph_launch']:.0f} "
          f"      = {gold['launch_speedup']:.1f}x   <- gold")
    print(f"  total_speedup    = {gold['eager_total']:.0f} / {gold['graph_total']:.0f} "
          f"(incl compute) = {gold['total_speedup']:.3f}x")

    banner("DONE - all sections printed, all [check] OK")


if __name__ == "__main__":
    main()
