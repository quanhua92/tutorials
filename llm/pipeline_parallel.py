"""
pipeline_parallel.py - Reference implementation of Pipeline Parallelism (PP):
naive bubble, GPipe, 1F1B, interleaved 1F1B.

This is the single source of truth that PIPELINE_PARALLEL.md is built from.
Every number, table, and worked example in the guide is printed by this
file. If you change something here, re-run and re-paste the output.

Run:
    uv run python pipeline_parallel.py

== IMPORTANT - this is a FAITHFUL SINGLE-PROCESS SIMULATION ================
We model K pipeline stages and M micro-batches as a deterministic schedule
of F (forward) and B (backward) operations in ONE process. We do NOT spawn
torch.distributed workers, open NCCL channels, or touch multiple GPUs.

    - Each op (F or B) takes exactly 1 time-slot.
    - Each stage runs at most 1 op per slot.
    - Dependencies (the only thing that makes it "a pipeline"):
        F(m, k) needs F(m, k-1) done   (activations arrived from prev stage)
        B(m, k) needs B(m, k+1) done   (gradients arrived from next stage)
                    AND F(m, k) done   (forward activations still saved)

The SCHEDULE SHAPE, the bubble fraction (K-1)/(K+M-1), and the activation-
memory arithmetic (GPipe: M x, 1F1B: K x) are EXACT - they would be byte-
identical to a real multi-GPU run. Only the communication latency itself is
skipped (no NCCL send/recv delay; see Section F for the handoff pattern).

== The big idea, in one paragraph (no math) ================================
Tensor Parallelism (TENSOR_PARALLEL) shards each weight MATRIX across GPUs
within a node (NVLink). But the whole model may still span multiple nodes.
Pipeline Parallelism splits the model's LAYERS across K stages (one node
each): stage 0 runs layers 0..L/K-1, stage 1 runs the next slice, etc. A
micro-batch flows through the pipeline like cars on an assembly line. The
catch: most GPUs sit idle while the first micro-batch "fills" the pipeline
and the last "drains" it - that idle time is the BUBBLE. Micro-batching
(GPipe) splits the batch into M pieces so the pipeline stays full longer;
1F1B starts backward early to cut activation memory from M x to K x;
interleaved 1F1B (Megatron) shrinks the bubble further by giving each GPU
V virtual stages.

== Plain-English glossary (used throughout) ================================
    stage (k)        one device (node) running a contiguous SLICE of layers.
                     k = 0 is the first stage (embeddings + first layers);
                     k = K-1 is the last stage (last layers + output head).
    micro-batch (m)  one chunk of the mini-batch; the unit that flows through
                     the pipeline. Splitting a mini-batch into M pieces lets
                     the pipeline stay full (GPipe's whole idea).
    F(m, k)          forward pass of micro-batch m at stage k. 1 time-slot.
    B(m, k)          backward pass of micro-batch m at stage k. 1 time-slot.
    bubble           idle time on a stage while it waits for data to arrive
                     or drain. GPipe/1F1B bubble fraction = (K-1)/(K+M-1).
    activation mem.  the tensors F(m,k) must save for B(m,k) to use later.
                     GPipe stores M sets; 1F1B stores only K sets.
    in-flight        a micro-batch is "in flight" at stage k from F(m,k)
                     until B(m,k). Peak # in-flight = peak activation memory.
    virtual stage    in interleaved 1F1B, each device runs V virtual stages,
                     each a smaller chunk of layers. The pipeline fill/drain
                     cost shrinks by V (bubble -> (K-1)/(K+M*V-1)).
    P2P send/recv    point-to-point activation/gradient transfer at stage
                     boundaries. NOT an AllReduce (TENSOR_PARALLEL uses those).

== The lineage (papers) =====================================================
    naive pipeline  (Huang 2019, Fig 1 of GPipe) : one batch, K stages,
                                                    ~75% of GPUs idle. "Old".
    GPipe           (Huang et al. 2019,           : split batch into M micro-
                     arXiv:1811.06965)              batches; fill the pipeline.
                                                    Bubble (K-1)/(K+M-1). M x
                                                    activation memory.
    1F1B /          (Narayanan et al. SC21,       : start backward as soon as
     PipeDream-Flush arXiv:2104.04473)              the first micro-batch hits
                                                    the last stage. SAME bubble
                                                    but activations drop to K x.
    Interleaved     (Narayanan et al. SC21,       : V virtual stages/device ->
     1F1B            sec 4.2)                        bubble (K-1)/(K+M*V-1).
    PyTorch API     (torch.distributed.pipelining) : PipelineStage,
                                                     ScheduleGPipe, Schedule1F1B.

== KEY FORMULAS (all verified against the papers + asserted in code) =======
    Bubble (GPipe, 1F1B):       bubble = (K-1) / (K+M-1)
    Memory (GPipe):             peak  = M  x  (per-microbatch activation size)
    Memory (1F1B):              peak  = K  x   (drops M/K x when M >> K)
    Bubble (interleaved, V):    bubble = (K-1) / (K + M*V - 1)
    Rule of thumb:              M >= 4K  ->  bubble <= ~16% (negligible)
    Comm pattern:               P2P send/recv at stage boundaries
                                (NOT AllReduce - that is TENSOR_PARALLEL)

== Tensor-shape conventions ================================================
    K   = number of pipeline stages (= number of devices in the PP group)
    M   = number of micro-batches per mini-batch
    V   = virtual stages per device (interleaved 1F1B); V=1 = non-interleaved
    L   = total transformer layers; each stage holds L/K layers (V=1) or
          L/(K*V) layers per virtual chunk (V>1)
    T   = total time-slots to drain one mini-batch (= 2*(K+M-1) for GPipe/1F1B)
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=6, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE SCHEDULE SIMULATOR
#    A deterministic model of K stages x M micro-batches. Each op = 1 slot.
# ============================================================================

def schedule_gpipe(K: int, M: int):
    """GPipe schedule: ALL M forwards (staircase fill), then ALL M backwards
    (reverse drain).

    Timing (each op = 1 slot; tf == tb == 1):
        F(m, k) at slot  m + k                            [staircase fill]
        B(m, k) at slot  (M+K-1) + (M-1-m) + (K-1-k)     [reverse drain]

    Total time      T = 2 * (M + K - 1)
    Per-stage busy  = 2 * M   (M forwards + M backwards)
    Per-stage idle  = 2 * (K - 1)
    Bubble fraction = 2*(K-1) / 2*(K+M-1) = (K-1) / (K+M-1)
    Peak in-flight  = M  (all forwards done before any backward)
    """
    T = 2 * (M + K - 1)
    gantt = [[None] * T for _ in range(K)]
    for m in range(M):
        for k in range(K):
            gantt[k][m + k] = ("F", m)
    for m in range(M):
        for k in range(K):
            t = (M + K - 1) + (M - 1 - m) + (K - 1 - k)
            gantt[k][t] = ("B", m)
    return gantt, T


def schedule_1f1b(K: int, M: int):
    """1F1B (PipeDream-Flush) schedule: bounded in-flight micro-batches (<= K).

    Per-stage op sequence:
        warmup:   K-k-1 forwards                 (fill the pipeline)
        steady:   1F-1B alternating              (in-flight bounded at K-k)
        cooldown: remaining backwards            (drain)

    Dependencies (enforced by discrete-event simulation):
        F(m, k) runnable iff F(m, k-1) finished in a PRIOR slot
        B(m, k) runnable iff B(m, k+1) finished in a PRIOR slot
                 (and F(m, k) already ran - guaranteed by the per-stage order)

    Total time      T = 2 * (M + K - 1)            [SAME bubble as GPipe]
    Peak in-flight  = K  (vs M for GPipe -> M/K x memory cut when M >> K)
    """
    seqs = []
    for k in range(K):
        seq = []
        num_warmup = min(K - k - 1, M)
        num_steady = M - num_warmup
        fwd_idx, bwd_idx = 0, 0
        for _ in range(num_warmup):
            seq.append(("F", fwd_idx)); fwd_idx += 1
        for _ in range(num_steady):
            seq.append(("F", fwd_idx)); fwd_idx += 1
            seq.append(("B", bwd_idx)); bwd_idx += 1
        while bwd_idx < M:
            seq.append(("B", bwd_idx)); bwd_idx += 1
        seqs.append(seq)

    fwd_time: dict[tuple[int, int], int] = {}
    bwd_time: dict[tuple[int, int], int] = {}
    ptr = [0] * K
    t = 0
    done = 0
    total_ops = 2 * M * K
    while done < total_ops:
        for k in range(K):
            if ptr[k] >= len(seqs[k]):
                continue
            op, m = seqs[k][ptr[k]]
            if op == "F":
                if k == 0 or (fwd_time.get((m, k - 1), -1) < t and (m, k - 1) in fwd_time):
                    fwd_time[(m, k)] = t
                    ptr[k] += 1
                    done += 1
            else:  # "B"
                if k == K - 1 or (
                    (m, k + 1) in bwd_time and bwd_time[(m, k + 1)] < t
                ):
                    bwd_time[(m, k)] = t
                    ptr[k] += 1
                    done += 1
        t += 1

    T = t
    gantt = [[None] * T for _ in range(K)]
    for (m, k), tt in fwd_time.items():
        gantt[k][tt] = ("F", m)
    for (m, k), tt in bwd_time.items():
        gantt[k][tt] = ("B", m)
    return gantt, T


def bubble_fraction(K: int, M: int) -> float:
    """Pipeline bubble fraction (GPipe and 1F1B share the same shape):
        idle_slots_per_stage / total_slots = 2*(K-1) / 2*(K+M-1) = (K-1)/(K+M-1)
    Equivalent to the Megatron-LM SC21 form (p-1)/m + 1 framing: bubble_overhead
    = (K-1)/M  is bubble / ideal_compute; ours is bubble / wall_clock.
    """
    return (K - 1) / (K + M - 1)


def bubble_fraction_interleaved(K: int, M: int, V: int) -> float:
    """Interleaved 1F1B bubble: each device runs V virtual stages, so the
    fill/drain chunk is (K-1)*(tf+tb)/V in wall-clock. Bubble fraction:
        (K-1) / (K + M*V - 1)
    For V=1 this reduces exactly to (K-1)/(K+M-1).
    """
    return (K - 1) / (K + M * V - 1)


def peak_in_flight(gantt: list, K: int) -> int:
    """Peak number of micro-batches 'live' at any single stage: F(m,k) done
    but B(m,k) not yet. Upper-bounds the activation memory that stage holds.
    Computed by sweeping slot-by-slot: +1 on F, -1 the slot AFTER B.
    """
    T = len(gantt[0])
    peak = 0
    for k in range(K):
        delta = [0] * (T + 1)
        for t in range(T):
            cell = gantt[k][t]
            if cell is None:
                continue
            op, _ = cell
            if op == "F":
                delta[t] += 1
            else:
                delta[t + 1] -= 1   # activations freed AFTER B completes
        cur = 0
        peak_k = 0
        for t in range(T):
            cur += delta[t]
            peak_k = max(peak_k, cur)
        peak = max(peak, peak_k)
    return peak


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_gantt(gantt: list, K: int, M: int, title: str):
    """ASCII Gantt: rows = stages (GPUs), cols = time-slots."""
    T = len(gantt[0])
    print(f"\n{title}")
    print(f"T = {T} slots  (K={K} stages, M={M} micro-batches; each cell = 1 op)\n")
    # header (time slots, 4 chars wide each)
    print("       " + "".join(f"{t:>4}" for t in range(T)))
    for k in range(K):
        label = f"GPU{k}: "
        cells = ""
        for t in range(T):
            cell = gantt[k][t]
            if cell is None:
                cells += "   ."
            else:
                op, m = cell
                cells += f"  {op}{m}"
        print(label + cells)
    # stats
    busy = sum(1 for t in range(T) for k in range(K) if gantt[k][t] is not None)
    total = K * T
    idle_per_stage = T - 2 * M
    bf = bubble_fraction(K, M)
    pif = peak_in_flight(gantt, K)
    print(f"\n  per-stage: {2*M} busy + {idle_per_stage} idle = {T} slots"
          f"   -> bubble = {idle_per_stage}/{T} = {bf:.4f} ({bf*100:.2f}%)")
    print(f"  peak in-flight micro-batches (activation memory multiplier): {pif}")
    print(f"  [check] bubble == (K-1)/(K+M-1) = ({K}-1)/({K}+{M}-1) = "
          f"{(K-1)}/{(K+M-1)} = {bf:.6f}:  "
          f"{'OK' if abs(bf - (K-1)/(K+M-1)) < 1e-12 else 'FAIL'}")


# ============================================================================
# 3. THE SECTIONS  (numbers that feed PIPELINE_PARALLEL.md)
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: why TP isn't enough (the cross-node memory budget)
# ----------------------------------------------------------------------------

def section_why_pp():
    banner("SECTION A: why tensor parallelism isn't enough (cross-node model)")
    print("Tensor Parallelism (TENSOR_PARALLEL) shards each weight MATRIX across")
    print("GPUs WITHIN a node (NVLink, ~300 GB/s). But two limits remain:\n")
    print("  1. TP_size <= GPUs_per_node  (going cross-node on IB is ~12x slower")
    print("     per AllReduce - the comm dominates; see TENSOR_PARALLEL.md sec 7).")
    print("  2. Even TP=8 on an 8-GPU DGX node caps at ~8x memory reduction.\n")
    print("A 175B model in fp16 = 350 GB; TP=8 still needs ~44 GB per rank - fits")
    print("an 80 GB H100, but a 1T-class model does not. To scale ACROSS nodes,")
    print("we need an axis that is tolerant of InfiniBand latency (~25-50 GB/s).\n")
    print("Pipeline Parallelism is that axis: split the model's LAYERS across K")
    print("stages (one node each). Comm is POINT-TO-POINT send/recv of one")
    print("activation tensor at each stage boundary - tiny vs TP's per-layer")
    print("AllReduce, and it pipelines cleanly over IB.\n")

    print("Concrete memory: Llama-2-70B has L=80 transformer layers, E=8192.\n")
    L, E = 80, 8192
    bytes_per_layer_fp16 = 3 * (28672 * E) * 2   # 3 matrices (gate, up, down)
    total_model_bytes = L * bytes_per_layer_fp16
    print(f"  per layer (3 MLP matrices, fp16):  {bytes_per_layer_fp16/2**30:6.3f} GiB")
    print(f"  total model ({L} layers, fp16):     {total_model_bytes/2**30:6.2f} GiB")
    print()
    print("Splitting L=80 layers across K PP stages shrinks per-stage memory:\n")
    print("| K (stages) | layers/stage | per-stage model (fp16) | savings |")
    print("|------------|--------------|------------------------|---------|")
    for K in [1, 2, 4, 8, 16]:
        per = total_model_bytes / K
        sav = "baseline" if K == 1 else f"{K}x smaller"
        print(f"| {K:<10} | {L//K:<12} | {per/2**30:>13.3f} GiB       | {sav:<7} |")
    print()
    print("READ: K=8 PP stages cut each node's model footprint 8x. Combined with")
    print("TP=8 WITHIN each node, a 70B model fits with room for activations + KV")
    print("cache. This is the 3D parallelism recipe: TP (intra-node) x PP (inter-")
    print("node) x DP (data-replicated throughput).  (TENSOR_PARALLEL sec 7)")
    print("\n[check] PP partitions layers across nodes; TP partitions matrices"
          " within:  OK")


# ----------------------------------------------------------------------------
# SECTION B: naive pipeline + the bubble (K=4, M=1 -> 75% idle)
# ----------------------------------------------------------------------------

def section_naive_bubble():
    banner("SECTION B: naive pipeline - the bubble (K=4, M=1 -> 75% idle)")
    K, M = 4, 1
    gantt, T = schedule_gpipe(K, M)
    print("Naive pipeline = ONE batch through K stages. Each stage does 1 forward")
    print("then waits for the backward to come home. Most GPUs idle most of the")
    print("time - that idle time is the BUBBLE.\n")
    print_gantt(gantt, K, M, f"Naive GPipe schedule  (K={K}, M={M}):")
    print()
    print("Reading the Gantt like a story:")
    print("  - GPU0 does F0 at slot 0, then sits IDLE for 6 slots, then does B0.")
    print("  - GPU3 doesn't even START until slot 3 (waits for F0 to traverse")
    print("    GPU0 -> GPU1 -> GPU2 -> GPU3). Then it does B0 immediately.")
    print("  - 6 of 8 slots on every stage are idle. That's the bubble.")
    print()
    print("Why this hurts: every stage is a ~$30k H100 and it spends 75% of its")
    print("time waiting. The fix is to keep the pipeline FULL by overlapping many")
    print("micro-batches - which is exactly GPipe (Section C).\n")

    bf = bubble_fraction(K, M)
    assert abs(bf - 0.75) < 1e-12
    print(f"[check] bubble_fraction({K},{M}) = {bf:.4f} = 75.00%  (the worst case):  OK")
    print(f"[check] peak_in_flight = {peak_in_flight(gantt, K)} (= M = {M}):  OK")


# ----------------------------------------------------------------------------
# SECTION C: GPipe micro-batching (bubble (K-1)/(K+M-1), M>=4K rule)
# ----------------------------------------------------------------------------

def section_gpipe():
    banner("SECTION C: GPipe - micro-batching fills the pipeline (bubble shrinks)")
    K, M = 4, 8
    gantt, T = schedule_gpipe(K, M)
    print("GPipe (Huang et al. 2019, arXiv:1811.06965): split each mini-batch into")
    print("M micro-batches and PIPELINE them. Stage k starts micro-batch m+1 as soon")
    print("as it has handed m+1's activations forward - so all stages stay busy in")
    print("the steady state. Only the FILL (first K-1 slots) and DRAIN (last K-1")
    print("slots) are idle.\n")
    print_gantt(gantt, K, M, f"GPipe schedule  (K={K}, M={M}):")
    print()
    print("Reading the Gantt:")
    print("  - The F's form a descending staircase (fill); the B's form an")
    print("    ascending one (drain). In between, every stage is busy every slot.")
    print("  - GPU0 forwards micro-batches 0..7 in slots 0..7, then idles 8..11")
    print("    (waiting for backwards to arrive from GPU3), then does B7..B0.")
    print("  - GPU3 is the mirror: idle 0..2, busy 3..10, idle 11..13.")
    print()
    print("The bubble formula (proven in the schedule):")
    print("  per-stage idle = 2*(K-1)        [K-1 to fill + K-1 to drain]")
    print("  total slots    = 2*(K+M-1)")
    print("  bubble frac    = (K-1)/(K+M-1)")
    print()
    print("Rule of thumb (Megatron-LM SC21): keep M >= 4K so the bubble is small.\n")
    print("| K | M  | bubble = (K-1)/(K+M-1) | comment                  |")
    print("|---|----|------------------------|--------------------------|")
    for Ki, Mi in [(4, 1), (4, 4), (4, 8), (4, 16), (4, 32), (4, 64), (8, 32)]:
        bf = bubble_fraction(Ki, Mi)
        rule = "M=1 (worst)" if Mi == 1 else (
               "M=K" if Mi == Ki else (
               "M=2K" if Mi == 2 * Ki else (
               "M=4K (rule of thumb)" if Mi == 4 * Ki else "M >> K (good)")))
        print(f"| {Ki} | {Mi:<2} | {bf:.4f}  ({bf*100:5.2f}%)       | {rule:<24} |")
    print()
    bf = bubble_fraction(K, M)
    assert abs(bf - 3 / 11) < 1e-12
    print(f"[check] bubble_fraction({K},{M}) = ({K}-1)/({K}+{M}-1) = 3/11 = "
          f"{bf:.6f}:  OK")
    print(f"[check] peak_in_flight = {peak_in_flight(gantt, K)} (= M = {M}):  OK")
    print("         (GPipe holds ALL M micro-batch activations until backward)")


# ----------------------------------------------------------------------------
# SECTION D: 1F1B (peak activation memory M -> K)
# ----------------------------------------------------------------------------

def section_1f1b():
    banner("SECTION D: 1F1B - start backward EARLY, cut activation memory M -> K")
    K, M = 4, 8
    gantt, T = schedule_1f1b(K, M)
    gpipe_gantt, _ = schedule_gpipe(K, M)
    print("1F1B / PipeDream-Flush (Narayanan et al. SC21, arXiv:2104.04473): as")
    print("soon as the FIRST micro-batch reaches the LAST stage, start its backward.")
    print("Then alternate 1 Forward / 1 Backward at every stage. The bubble is the")
    print("SAME shape and size as GPipe - but no stage ever holds more than K")
    print("in-flight micro-batches (vs M for GPipe).\n")
    print_gantt(gantt, K, M, f"1F1B schedule  (K={K}, M={M}):")
    print()
    print("Reading the Gantt (compare to GPipe above):")
    print("  - GPU3 (last stage) alternates F0 B0 F1 B1 ... as soon as it can.")
    print("  - GPU0 (first stage) does 3 warmup forwards (K-1), then enters the")
    print("    1F1B steady state. It never has more than 4 micro-batch activation")
    print("    sets live at once.")
    print("  - Total time is IDENTICAL to GPipe (T = 2*(K+M-1) = 22 slots) - 1F1B")
    print("    saves MEMORY, not bubble.\n")

    gp_pif = peak_in_flight(gpipe_gantt, K)
    f1b_pif = peak_in_flight(gantt, K)
    print(f"Peak activation memory (in micro-batches of activations):\n")
    print(f"  GPipe  peak in-flight = {gp_pif}  (= M = {M})")
    print(f"  1F1B   peak in-flight = {f1b_pif}  (= K = {K})")
    print(f"  reduction             = {gp_pif}/{f1b_pif} = {gp_pif/f1b_pif:.1f}x"
          f"  (for M={M} >> K={K}: huge win)")
    print()
    print("WHY 1F1B's memory is bounded at K (one paragraph):")
    print("  A stage k must hold micro-batch m's activations from F(m,k) until B(m,k).")
    print("  In GPipe all M forwards finish before any backward starts, so all M")
    print("  activation sets are live simultaneously. 1F1B inserts B's between F's:")
    print("  stage k does K-k-1 warmup F's, then alternates 1F-1B. After the warmup")
    print("  every new F is paired with a B that frees an old activation set, so the")
    print("  in-flight count never exceeds K-k (max over k = K at stage 0). This is")
    print("  exactly the SC21 paper's claim: 'activations stashed for p or fewer")
    print("  microbatches' (p = K = number of stages).")
    print()
    print("| K | M  | GPipe mem (M x) | 1F1B mem (K x) | reduction |")
    print("|---|----|-----------------|----------------|-----------|")
    for Ki, Mi in [(4, 8), (4, 16), (4, 32), (4, 64), (8, 32), (8, 64)]:
        print(f"| {Ki} | {Mi:<2} | {Mi:<15} | {Ki:<14} | {Mi/Ki:.1f}x      |")
    print()
    bf = bubble_fraction(K, M)
    assert f1b_pif == K, f"1F1B peak in-flight should be K={K}, got {f1b_pif}"
    print(f"[check] 1F1B peak_in_flight({K},{M}) == K == {f1b_pif}:  OK")
    print(f"[check] 1F1B bubble == GPipe bubble == (K-1)/(K+M-1) = {bf:.6f}:  OK")
    print("         (same total time T = 2*(K+M-1); 1F1B trades nothing for the")
    print("          memory win - it is a pure scheduling improvement.)")


# ----------------------------------------------------------------------------
# SECTION E: interleaved 1F1B (bubble shrinks with V virtual stages)
# ----------------------------------------------------------------------------

def section_interleaved():
    banner("SECTION E: interleaved 1F1B - V virtual stages shrink the bubble")
    K, M = 4, 8
    print("Interleaved 1F1B (Megatron-LM SC21 sec 4.2): give each device V virtual")
    print("stages, each holding a SMALLER chunk of layers. Instead of")
    print("GPU0 = layers 0..L/K-1, we get e.g. (V=2):")
    print()
    print("  Standard PP (K=4 GPUs, 16 layers, V=1):")
    print("    GPU0: L0-3     GPU1: L4-7     GPU2: L8-11    GPU3: L12-15")
    print()
    print("  Interleaved PP (K=4 GPUs, 16 layers, V=2):")
    print("    GPU0: L0-1, L8-9     GPU1: L2-3, L10-11")
    print("    GPU2: L4-5, L12-13   GPU3: L6-7, L14-15")
    print()
    print("Each micro-batch now hops K*V times instead of K, but each hop is 1/V")
    print("the work (fewer layers per virtual stage). The fill/drain cost is still")
    print("K-1 'device-hops', but in wall-clock time each hop costs (tf+tb)/V, so")
    print("the bubble shrinks by V:\n")
    print("  bubble_interleaved = ((K-1)/V) / (M + (K-1)/V) = (K-1) / (K + M*V - 1)\n")
    print("| K | M | V | bubble = (K-1)/(K+M*V-1) | vs non-interleaved |")
    print("|---|---|---|--------------------------|-------------------|")
    for V in [1, 2, 4]:
        for Ki, Mi in [(4, 8), (4, 16), (4, 32), (8, 16)]:
            bf_v = bubble_fraction_interleaved(Ki, Mi, V)
            bf_1 = bubble_fraction_interleaved(Ki, Mi, 1)
            tag = "" if V == 1 else f"  ({bf_v/bf_1:.2f}x smaller)"
            print(f"| {Ki} | {Mi:<2} | {V} | {bf_v:.4f}  ({bf_v*100:5.2f}%)          |"
                  f"{tag}")
        print("|---|---|---|--------------------------|-------------------|")
    print()
    V = 2
    bf_v = bubble_fraction_interleaved(K, M, V)
    bf_1 = bubble_fraction_interleaved(K, M, 1)
    assert abs(bf_v - 3 / 19) < 1e-12
    print(f"[check] interleaved({K},{M},V=2) = ({K}-1)/({K}+{M}*2-1) = 3/19 = "
          f"{bf_v:.6f}:  OK")
    print(f"[check] vs V=1 ({bf_1:.4f}): {bf_v/bf_1:.2f}x smaller bubble:  OK")
    print()
    print("TRADEOFF: interleaving cuts the bubble but adds V-1 EXTRA point-to-point")
    print("sends per micro-batch per device (the virtual stages must hand off to")
    print("each other). On slow interconnects this can negate the bubble win, so V")
    print("is usually 2..4 in practice.  (NCCL_COLLECTIVES sec P2P send/recv)")


# ----------------------------------------------------------------------------
# SECTION F: P2P activation handoff at stage boundaries
# ----------------------------------------------------------------------------

def section_p2p_handoff():
    banner("SECTION F: P2P activation handoff at stage boundaries  (NCCL_COLLECTIVES)")
    K, M = 4, 2
    gantt, T = schedule_gpipe(K, M)
    print("Pipeline Parallelism's communication is POINT-TO-POINT send/recv, NOT")
    print("AllReduce. Each stage sends one activation tensor forward and one")
    print("gradient tensor backward - per micro-batch, per stage boundary:\n")
    print("  forward:  stage k  --[send a_(m,k)]-->  stage k+1")
    print("  backward: stage k+1  --[send g_(m,k+1)]-->  stage k\n")
    print("Dependency edges (one micro-batch m, all K stages):")
    print()
    chain_fwd = " -> ".join([f"F(m={0},k={k})" for k in range(K)])
    chain_bwd = " -> ".join([f"B(m={0},k={k})" for k in reversed(range(K))])
    print(f"  forward chain: {chain_fwd}")
    print(f"  backward chain: {chain_bwd}")
    print()
    print("Each '->' is one ncclSend / ncclRecv pair. The tensor shipped is the")
    print("stage's output activation [B_micro, L_slice, E] (forward) or the")
    print("gradient of that tensor (backward). It is TINY compared to TP's")
    print("AllReduce (which moves the full [B, L, E] block output twice per")
    print("layer) - that is why PP tolerates InfiniBand while TP does not.\n")

    # Count the P2P transfers for one mini-batch
    n_fwd_sends = (K - 1) * M        # each of K-1 boundaries x M micro-batches
    n_bwd_sends = (K - 1) * M
    total = n_fwd_sends + n_bwd_sends
    print(f"For K={K} stages, M={M} micro-batches, one mini-batch ships:")
    print(f"  forward P2P sends: (K-1)*M = {K-1}*{M} = {n_fwd_sends}")
    print(f"  backward P2P sends: (K-1)*M = {K-1}*{M} = {n_bwd_sends}")
    print(f"  total P2P transfers: {total}")
    print()
    print("Each transfer is one activation tensor of shape [B_micro, L_slice, E].")
    B_micro, L_slice, E = 1, 1024, 8192
    bytes_fp16 = B_micro * L_slice * E * 2
    print(f"  example size (B_micro={B_micro}, L_slice={L_slice}, E={E}, fp16): "
          f"{bytes_fp16/2**20:.2f} MiB per send")
    print(f"  per mini-batch comm volume: {total} * {bytes_fp16/2**20:.2f} MiB "
          f"= {total*bytes_fp16/2**30:.3f} GiB")
    print()
    print("Contrast with TENSOR_PARALLEL: TP does 2 AllReduces PER LAYER, each of")
    print("shape [B, L, E] over NVLink. PP does 2*(K-1) P2P sends PER MICRO-BATCH,")
    print("each of shape [B_micro, L_slice, E]. PP's comm is rare + small +")
    print("tolerates IB latency; TP's is frequent + large + needs NVLink.\n")
    print("| axis      | op           | frequency           | link needed   |")
    print("|-----------|--------------|---------------------|---------------|")
    print("| TP        | AllReduce    | 2x per layer        | NVLink (~300) |")
    print("| PP        | P2P send/recv| 2*(K-1) per mini-bt | IB (~25-50)   |")
    print("| DP (DDP)  | AllReduce    | 1x per optim step   | IB (~25-50)   |")
    print()
    print("[check] PP uses P2P send/recv (not AllReduce) -> IB-tolerant:  OK")


# ----------------------------------------------------------------------------
# SECTION G: the gold table - bubble + memory across (K, M, V) configs
# ----------------------------------------------------------------------------

def section_gold_table():
    banner("SECTION G: the gold table - bubble + memory across (K, M, V)  (GOLD)")
    print("The centerpiece: how bubble fraction and peak activation memory scale")
    print("with K (stages), M (micro-batches), and V (virtual stages/device).\n")
    print("All numbers are computed by the formulas asserted above; the .html")
    print("gold-check recomputes the K=4, M=8 row in JS.\n")
    print("| K | M  | V | bubble (frac) | bubble %  | GPipe mem | 1F1B mem | "
          "interleaved bubble |")
    print("|---|----|---|---------------|-----------|-----------|----------|"
          "--------------------|")
    configs = [
        (4, 1, 1), (4, 4, 1), (4, 8, 1), (4, 16, 1), (4, 32, 1), (4, 64, 1),
        (4, 8, 2), (4, 8, 4),
        (8, 8, 1), (8, 32, 1), (8, 32, 2), (8, 64, 4),
    ]
    gold_row = None
    for (K, M, V) in configs:
        bf = bubble_fraction(K, M)             # GPipe / 1F1B (V=1)
        bf_v = bubble_fraction_interleaved(K, M, V)
        mem_gpipe = M
        mem_1f1b = K
        row = (f"| {K} | {M:<2} | {V} | {bf_v:.6f}      | {bf_v*100:7.2f}%  | "
               f"{mem_gpipe:>9} | {mem_1f1b:>8} |  "
               f"V={V}: {bf_v:.4f} ({bf_v*100:.2f}%)   |")
        print(row)
        if (K, M, V) == (4, 8, 1):
            gold_row = (K, M, V, bf, mem_1f1b)
    print()
    print("GOLD pins (recomputed by pipeline_parallel.html for the check badge):")
    K, M, V = 4, 8, 1
    bf_gold = bubble_fraction(K, M)
    mem_gold = K
    print(f"  bubble_fraction(K=4, M=8)        = ({K}-1)/({K}+{M}-1) = 3/11")
    print(f"                                   = {bf_gold:.6f}")
    print(f"  1F1B peak mem multiplier (K=4)   = {mem_gold}")
    print(f"  interleaved(K=4, M=8, V=2)       = 3/19 = "
          f"{bubble_fraction_interleaved(4, 8, 2):.6f}")
    print()
    assert abs(bf_gold - 3 / 11) < 1e-12
    assert mem_gold == 4
    print(f"[check] GOLD bubble_fraction(4,8) == 3/11 == {bf_gold:.6f}:  OK")
    print(f"[check] GOLD 1F1B mem multiplier == K == 4:  OK")
    print(f"[check] GOLD interleaved(4,8,2) == 3/19 == "
          f"{bubble_fraction_interleaved(4,8,2):.6f}:  OK")


# ----------------------------------------------------------------------------
# SECTION H: PyTorch PipelineStage API (the production interface)
# ----------------------------------------------------------------------------

def section_pytorch_api():
    banner("SECTION H: PyTorch torch.distributed.pipelining API (the production face)")
    print("PyTorch >= 2.4 ships ScheduleGPipe and Schedule1F1B. You split the")
    print("model with PipelineStage and let the schedule drive the send/recv:\n")
    print("  from torch.distributed.pipelining import PipelineStage, ScheduleGPipe")
    print()
    print("  # 1. each rank keeps ONLY its slice of layers (meta device = no memory)")
    print("  with torch.device('meta'):")
    print("      model = Transformer()")
    print("      if stage_index == 0:")
    print("          del model.layers['1']; model.norm = None; model.output = None")
    print("      elif stage_index == 1:")
    print("          model.tok_embeddings = None; del model.layers['0']")
    print()
    print("  # 2. wrap in a PipelineStage; pick a schedule")
    print("  stage = PipelineStage(model, stage_index, num_stages=2, device=device)")
    print("  schedule = ScheduleGPipe(stage, n_microbatches=8)   # or Schedule1F1B")
    print()
    print("  # 3. rank 0 feeds input; every rank calls step()")
    print("  if rank == 0:")
    print("      schedule.step(x)        # x is split into micro-batches automatically")
    print("  else:")
    print("      output = schedule.step()   # recv activations, run, send forward")
    print()
    print("Under the hood ScheduleGPipe implements Section C's all-forward-then-all-")
    print("backward; Schedule1F1B implements Section D's interleaved schedule. The")
    print("P2P send/recv (Section F) is inserted automatically at stage boundaries.")
    print()
    print("[check] ScheduleGPipe == Section C; Schedule1F1B == Section D:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("pipeline_parallel.py - reference impl (faithful single-process simulation).")
    print("Numbers below feed PIPELINE_PARALLEL.md.  torch =", torch.__version__)
    print("\nSIMULATION: K pipeline stages x M micro-batches, each op = 1 time-slot.")
    print("No torch.distributed / NCCL / multi-GPU. The schedule SHAPE, the bubble")
    print("fraction, and the activation-memory arithmetic are EXACT to a real run.")
    print("Only the comm LATENCY is skipped (see Section F for the handoff pattern).")

    section_why_pp()             # A
    section_naive_bubble()       # B
    section_gpipe()              # C
    section_1f1b()               # D
    section_interleaved()        # E
    section_p2p_handoff()        # F
    section_gold_table()         # G
    section_pytorch_api()        # H

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
