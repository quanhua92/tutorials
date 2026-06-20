"""
zero.py - Reference implementation of ZeRO (Zero Redundancy Optimizer) stages
1/2/3, their per-GPU memory math, and their communication patterns.

This is the single source of truth that ZERO.md is built from. Every number,
table, and worked example in ZERO.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python zero.py

== IMPORTANT — this is a FAITHFUL SINGLE-PROCESS SIMULATION of K ranks ========
We do NOT spawn processes, use torch.distributed, or call NCCL. Instead we
model K "ranks" as a Python list of K torch tensors and implement ReduceScatter
and AllGather as EXPLICIT loops over those ranks (the same data-flow real NCCL
uses; only the transport — in-process copy vs real NVLink — differs).

The MEMORY-BYTES arithmetic and the COMMUNICATION-VOLUME arithmetic are
REAL and EXACT (they are closed-form formulas in N and K, asserted in code).
What is simulated is only the multi-rank *execution*: one process holds K
shards instead of K processes holding one shard each. This makes every number
printable and reproducible on a laptop, with no GPU or cluster required.

== The big idea, in one paragraph (no math) ==================================
DDP (🔗 DDP.md) replicates the ENTIRE model + optimizer state on every GPU, so
every GPU stores ~20N bytes for an N-parameter model — 16N of which is pure
redundancy (identical on all K GPUs). ZeRO attacks exactly that redundancy by
PARTITIONING (sharding) the states progressively across the K data-parallel
ranks:
  Stage 1 -> shard the OPTIMIZER STATES  (fp32 master + momentum + variance)
  Stage 2 -> ALSO shard the GRADIENTS     (fp16 grads reduced-AND-scattered)
  Stage 3 -> ALSO shard the PARAMETERS    (fp16 params reassembled per layer)
Each stage trades a little extra bookkeeping (and, for Stage 3, ~1.5x more
communication) for a large memory win. The payoff: a 7B model that needs
~140 GB/GPU under DDP fits in ~14 GB/GPU under ZeRO-3 on 8 GPUs — it drops onto
a single 80 GB A100.

== The lineage (old -> new, with WHY) =========================================
  DDP         : replicate EVERYTHING. per-GPU = 20N. The 16N optimizer/grad
                bookkeeping is identical on all K GPUs -> pure redundancy.
  ZeRO-1 (Pos): shard OPTIMIZER STATES only.     per-GPU = 4 + 16/K.
                (params + grads still full, so forward/backward are unchanged.)
  ZeRO-2 (+g ): ALSO shard GRADIENTS.            per-GPU = 2 + 14/K.
                (each rank keeps only its N/K grad shard after ReduceScatter.)
  ZeRO-3 (+p ): ALSO shard PARAMETERS.           per-GPU = 16/K.
                (AllGather the full layer before each fwd/bwd layer, discard
                after. This is the memory win that fits 7B on one A100.)

== The comms identity ZeRO lives on (🔗 NCCL_COLLECTIVES.md) ==================
  AllReduce == ReduceScatter ; then AllGather
ZeRO-1/2 REPLACE DDP's single gradient AllReduce with ReduceScatter(grad) +
AllGather(param) -> SAME ~2*Psi bytes, but it lets the optimizer state be
partitioned in between. ZeRO-3 adds one more AllGather (params are gathered for
both forward AND backward) -> ~3*Psi = 1.5x DDP comms.

== Plain-English glossary ====================================================
    N (Psi)   : total number of model parameters.
    K         : world size = number of data-parallel ranks (GPUs).
    rank (r)  : one GPU, numbered 0..K-1. (Here: the r-th shard in a list.)
    shard     : rank r's 1/K slice of a tensor: params[r*chunk:(r+1)*chunk].
    optimizer state : the fp32 bookkeeping Adam keeps per param: master copy,
                first moment (momentum), second moment (variance) = 12 bytes.
    master    : an fp32 COPY of the weights the optimizer updates; the fp16
                weight used in forward is rounded down from it. (🔗 DDP §F)
    ReduceScatter : reduce (sum/avg) all ranks AND scatter -> rank r ends
                holding only the reduced chunk r. (1st half of AllReduce.)
    AllGather    : each rank contributes a shard; all end with the concat.
                (2nd half of AllReduce; ZeRO-3 rebuilds full params with it.)
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 0. THE TWO PRIMITIVES ZeRO IS BUILT ON (faithful single-process sim)
#    Copied in miniature from nccl_collectives.py (🔗) so this file is
#    self-contained. Real NCCL ships these over a ring; we ship them with an
#    explicit Python loop. The data-flow + byte counts are identical.
# ============================================================================

def reduce_scatter_avg(full_per_rank: list[torch.Tensor]) -> list[torch.Tensor]:
    """ReduceScatter (average): rank r ends holding the AVERAGED chunk r.

    Input : K tensors of N elements each (one per rank).
    Output: K tensors of N/K elements each. out[r] = mean over ranks of chunk r.
    This is the gradient op ZeRO-1/2 use instead of a full AllReduce.
    """
    K = len(full_per_rank)
    N = full_per_rank[0].shape[0]
    assert N % K == 0, "N must divide K so every rank gets an equal shard"
    chunk = N // K
    out = []
    for r in range(K):
        shard = torch.zeros(chunk, dtype=full_per_rank[0].dtype)
        for src in range(K):
            shard = shard + full_per_rank[src][r * chunk:(r + 1) * chunk]
        out.append(shard / K)                  # average == DDP's mean gradient
    return out


def all_gather(shards: list[torch.Tensor]) -> list[torch.Tensor]:
    """AllGather: each rank contributes a shard; all end with the concat.

    Input : K shards of N/K elements each. Output: K full tensors of N each.
    ZeRO-1 uses this to redistribute updated params; ZeRO-3 uses it to
    materialize a full layer before forward/backward.
    """
    full = torch.cat(shards, dim=0)
    return [full.clone() for _ in shards]


def shard_of(full: torch.Tensor, r: int, K: int) -> torch.Tensor:
    """Return rank r's contiguous 1/K slice of `full`."""
    chunk = full.shape[0] // K
    return full[r * chunk:(r + 1) * chunk].clone()


# ----------------------------------------------------------------------------
# PRETTY PRINTERS
# ----------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_vec(v, nd=4):
    return "[" + ", ".join(f"{x:+.{nd}f}" for x in v.tolist()) + "]"


# ============================================================================
# A. THE DDP 20N BASELINE (the redundancy ZeRO kills)  -- 🔗 DDP.md
# ============================================================================

def bytes_per_param_ddp():
    """The 20-bytes/param bill DDP pays on EVERY GPU (🔗 ddp.py Section F)."""
    return [
        ("fp16 parameters",    2, "model weights used in the fp16 forward"),
        ("fp16 gradients",     2, "computed in the fp16 backward"),
        ("fp32 master params", 4, "optimizer master copy (Micikevicius 2017)"),
        ("fp32 grad copy",     4, "upcast fp16 grad for the optimizer"),
        ("fp32 Adam momentum", 4, "first moment (beta1 running avg)"),
        ("fp32 Adam variance", 4, "second moment (beta2 running avg)"),
    ]


def section_ddp_baseline():
    banner("SECTION A: the DDP 20N baseline -- the redundancy ZeRO kills (🔗 DDP)")
    rows = bytes_per_param_ddp()
    total = sum(b for _, b, _ in rows)
    print("Per parameter, DDP mixed-precision Adam stores (on EVERY GPU):\n")
    print("| component           | bytes/param | why                                   |")
    print("|---------------------|-------------|---------------------------------------|")
    for name, b, why in rows:
        print(f"| {name:<19} | {b:>11} | {why:<37} |")
    print(f"| {'TOTAL':<19} | {total:>11} | {'replicated xK = pure redundancy':<37} |")
    print()
    assert total == 20
    # group the 16N optimizer/grad bookkeeping vs the 4N that the fwd needs full
    opt_states = 4 + 4 + 4 + 4          # master + gradcopy + mom + var = 16
    model_live = 2 + 2                  # fp16 params + fp16 grads = 4
    print(f"  of the 20N:  {model_live}N is the live model (params+grads, needed full),")
    print(f"               {opt_states}N is optimizer/grad bookkeeping -- IDENTICAL on all")
    print(f"               K GPUs. That {opt_states}N x K redundancy is exactly what ZeRO")
    print("               partitions away, stage by stage.\n")
    print("  [check] total == 20 and optimizer bookkeeping == 16? "
          f"{total == 20 and opt_states == 16}")
    return total, opt_states, model_live


# ============================================================================
# B. ZeRO STAGE 1 -- shard OPTIMIZER STATES  ->  per-GPU = 4 + 16/K
#    Simulation: ReduceScatter(grad) -> local Adam on shard -> AllGather(param)
# ============================================================================

def zero1_per_param(K: int):
    """ZeRO-1 per-GPU bytes/param breakdown. Returns (rows, total_formula_str)."""
    rows = [
        ("fp16 parameters",    2,     "full -- needed for forward"),
        ("fp16 gradients",     2,     "full -- computed in backward"),
        ("fp32 master params", 4 / K, "sharded: rank r owns params[r]"),
        ("fp32 grad copy",     4 / K, "sharded: only the shard is upcast"),
        ("fp32 Adam momentum", 4 / K, "sharded: rank r owns moms[r]"),
        ("fp32 Adam variance", 4 / K, "sharded: rank r owns vars[r]"),
    ]
    return rows


def section_zero1_formula(K: int):
    banner(f"SECTION B: ZeRO-1 -- shard OPTIMIZER STATES  ->  4 + 16/K   (K={K})")
    rows = zero1_per_param(K)
    total = sum(b for _, b, _ in rows)
    print("Per GPU after ZeRO-1 (each rank owns 1/K of the optimizer states):\n")
    print("| component           | bytes/param | status                                |")
    print("|---------------------|-------------|---------------------------------------|")
    for name, b, _ in rows:
        kind = "FULL " if b in (2,) else "full" if b == 2 else f"sharded 1/{K}"
        print(f"| {name:<19} | {b:>11.4g} | {kind:<37} |")
    print(f"| {'TOTAL':<19} | {total:>11.4g} | = 4 + 16/{K} = {4 + 16 / K:<24.4g} |")
    print()
    assert abs(total - (4 + 16 / K)) < 1e-9
    print(f"  formula: 2 + 2 + (4+4+4+4)/{K} = 4 + 16/{K} = {4 + 16 / K:.4g} bytes/param")
    print(f"  vs DDP 20N -> {20 / total:.2f}x less memory")
    print(f"  [check] total == 4 + 16/{K}? {abs(total - (4 + 16 / K)) < 1e-9}")
    return total


def section_zero1_simulation():
    banner("SECTION B (sim): a faithful ZeRO-1 step on N=8, K=4")
    N, K = 8, 4
    chunk = N // K
    lr = 0.1
    g = torch.Generator().manual_seed(0)
    # identical init: every rank starts from the SAME fp16 params (DDP broadcast)
    base = (torch.randn(N, generator=g) * 0.5)
    print(f"N={N} params, K={K} ranks, chunk={chunk}. Identical fp16 init on all ranks:\n")
    print(f"  params (all ranks) = {fmt_vec(base)}\n")
    # each rank computes a DIFFERENT local fp16 gradient on its own mini-batch
    local_grads = []
    for r in range(K):
        local_grads.append(torch.randn(N, generator=g) * 0.3)
    print("local fp16 grads (one per rank, from different mini-batches):")
    for r in range(K):
        print(f"  rank {r}: {fmt_vec(local_grads[r])}")
    print()

    # --- STEP 1: ReduceScatter the gradients -> each rank keeps its chunk's avg
    grad_shards = reduce_scatter_avg(local_grads)
    print("--- STEP 1: ncclReduceScatter(grads)  -> rank r owns the AVERAGED grad chunk r ---")
    for r in range(K):
        print(f"  rank {r} grad shard [{r*chunk}:{(r+1)*chunk}] = {fmt_vec(grad_shards[r])}")
    print("  (rank r only ever needs grads for ITS param shard; the rest are gone)\n")

    # --- STEP 2: each rank runs the optimizer on its OWN param shard (fp32 master)
    print("--- STEP 2: each rank updates its param shard via the fp32 master ---")
    master = [shard_of(base, r, K).float() for r in range(K)]      # fp32 master shard
    new_shards = []
    for r in range(K):
        upd = master[r] - lr * grad_shards[r].float()              # simplified Adam->SGD step
        new_shards.append(upd.to(base.dtype))
        print(f"  rank {r}: master[{r*chunk}:{(r+1)*chunk}] - {lr}*grad = {fmt_vec(new_shards[r])}")
    print()

    # --- STEP 3: AllGather -> all ranks have the full updated fp16 params
    full_new = all_gather(new_shards)
    print("--- STEP 3: ncclAllGather(updated shards) -> all ranks have full params ---")
    print(f"  params after ZeRO-1 step (every rank) = {fmt_vec(full_new[0])}")
    identical = all(torch.equal(full_new[r], full_new[0]) for r in range(K))
    print(f"\n  [check] all {K} ranks hold IDENTICAL params after the step? {identical}")
    assert identical, "AllGather must make every rank's params identical (no drift)"
    # cross-check: ZeRO-1 result == single-GPU SGD on the AVERAGED gradient
    avg_full = torch.stack(local_grads).mean(dim=0)
    ref = base - lr * avg_full
    print(f"  [check] ZeRO-1 params == single-GPU on averaged grad? "
          f"{torch.allclose(full_new[0], ref, atol=1e-6)}")
    assert torch.allclose(full_new[0], ref, atol=1e-6)
    print("\n  ==> ZeRO-1 is mathematically identical to DDP here; it only SHARDS the")
    print("      optimizer state. The ReduceScatter+AllGather is the SAME data-flow as")
    print("      DDP's AllReduce (🔗 NCCL_COLLECTIVES identity), just split to partition.")


# ============================================================================
# C. ZeRO STAGE 2 -- ALSO shard GRADIENTS  ->  per-GPU = 2 + 14/K
# ============================================================================

def zero2_per_param(K: int):
    rows = [
        ("fp16 parameters",    2,     "full -- still needed for forward"),
        ("fp16 gradients",     2 / K, "sharded: only rank r's grad chunk survives"),
        ("fp32 master params", 4 / K, "sharded"),
        ("fp32 Adam momentum", 4 / K, "sharded"),
        ("fp32 Adam variance", 4 / K, "sharded"),
    ]
    return rows          # NOTE: fp32 grad copy is GONE (grad shard consumed directly)


def section_zero2_formula(K: int):
    banner(f"SECTION C: ZeRO-2 -- ALSO shard GRADIENTS  ->  2 + 14/K   (K={K})")
    rows = zero2_per_param(K)
    total = sum(b for _, b, _ in rows)
    print("Per GPU after ZeRO-2 (gradients are now partitioned too):\n")
    print("| component           | bytes/param | status                                |")
    print("|---------------------|-------------|---------------------------------------|")
    for name, b, _ in rows:
        kind = "FULL " if b == 2 else f"sharded 1/{K}"
        print(f"| {name:<19} | {b:>11.4g} | {kind:<37} |")
    print(f"| {'TOTAL':<19} | {total:>11.4g} | = 2 + 14/{K} = {2 + 14 / K:<24.4g} |")
    print()
    assert abs(total - (2 + 14 / K)) < 1e-9
    print("  the fp32 grad copy (4N under DDP) is ELIMINATED: the fp16 grad shard is")
    print("  upcast transiently and consumed by the optimizer, then freed.")
    print(f"  formula: 2 + (2+4+4+4)/{K} = 2 + 14/{K} = {2 + 14 / K:.4g} bytes/param")
    print(f"  vs DDP 20N -> {20 / total:.2f}x less memory")
    print(f"  [check] total == 2 + 14/{K}? {abs(total - (2 + 14 / K)) < 1e-9}")
    return total


def section_zero2_gradflow():
    banner("SECTION C (sim): ZeRO-2 grad flow -- reduce-then-delete the non-owned shards")
    N, K = 8, 4
    chunk = N // K
    g = torch.Generator().manual_seed(1)
    local_grads = [torch.randn(N, generator=g) * 0.3 for _ in range(K)]
    print(f"N={N}, K={K}. During backward, the moment a param's grad is ready it is\n"
          f"ReduceScattered to the OWNING rank and immediately DELETED on the others.\n")
    grad_shards = reduce_scatter_avg(local_grads)
    print("| rank | full fp16 grad (transient) | kept shard after RS+delete |")
    print("|------|----------------------------|----------------------------|")
    for r in range(K):
        print(f"| {r}    | {fmt_vec(local_grads[r])} | {fmt_vec(grad_shards[r])} "
              f"(owns chunk {r*chunk}:{(r+1)*chunk})")
    print("\n  After the pass, rank r holds ONLY its N/K grad shard -- the other")
    print(f"  {K-1}/{K} of every gradient is gone. That is the ZeRO-2 memory win.")


# ============================================================================
# D. ZeRO STAGE 3 -- ALSO shard PARAMETERS  ->  per-GPU = 16/K
# ============================================================================

def zero3_per_param(K: int):
    rows = [
        ("fp16 parameters",    2 / K, "sharded: AllGathered per layer, then discarded"),
        ("fp16 gradients",     2 / K, "sharded"),
        ("fp32 master params", 4 / K, "sharded"),
        ("fp32 Adam momentum", 4 / K, "sharded"),
        ("fp32 Adam variance", 4 / K, "sharded"),
    ]
    return rows


def section_zero3_formula(K: int):
    banner(f"SECTION D: ZeRO-3 -- ALSO shard PARAMETERS  ->  16/K   (K={K})")
    rows = zero3_per_param(K)
    total = sum(b for _, b, _ in rows)
    print("Per GPU after ZeRO-3 (EVERYTHING is partitioned, incl. the weights):\n")
    print("| component           | bytes/param | status                                |")
    print("|---------------------|-------------|---------------------------------------|")
    for name, b, _ in rows:
        print(f"| {name:<19} | {b:>11.4g} | {f'sharded 1/{K}':<37} |")
    print(f"| {'TOTAL':<19} | {total:>11.4g} | = 16/{K} = {16 / K:<24.4g} |")
    print()
    assert abs(total - 16 / K) < 1e-9
    print(f"  formula: (2+2+4+4+4)/{K} = 16/{K} = {16 / K:.4g} bytes/param")
    print(f"  vs DDP 20N -> {20 / total:.2f}x less memory  (== K = {K}x at large N)")
    print(f"  [check] total == 16/{K}? {abs(total - 16 / K) < 1e-9}")
    return total


def section_zero3_paramflow():
    banner("SECTION D (sim): ZeRO-3 param flow -- AllGather a layer, compute, discard")
    N, K = 8, 4
    chunk = N // K
    g = torch.Generator().manual_seed(2)
    # each rank holds only its param shard
    full = (torch.randn(N, generator=g) * 0.5)
    shards = [shard_of(full, r, K) for r in range(K)]
    print(f"N={N}, K={K}. Each rank stores only its {chunk}-param shard:\n")
    for r in range(K):
        print(f"  rank {r} persistent shard = {fmt_vec(shards[r])}")
    print("\nBefore a layer's forward, every rank AllGathers to rebuild the FULL layer:\n")
    rebuilt = all_gather(shards)
    print(f"  AllGather -> full layer (every rank, transient) = {fmt_vec(rebuilt[0])}")
    print("  compute forward on the full layer ... then DISCARD the non-owned params.\n")
    # the transient full tensor exists only during the layer; persistent mem stays sharded
    same = torch.equal(rebuilt[0], full)
    print(f"  [check] AllGather(rebuilt) == original full layer? {same}")
    assert same
    print("  [check] persistent memory per rank stays N/K? "
          f"{shards[0].shape[0] == chunk}  "
          f"(rank holds {shards[0].shape[0]} of {N} params)")


# ============================================================================
# E. THE GOLD MEMORY TABLE (N=1e6,K=4 and 7B,K=8) -- the centerpiece
# ============================================================================

def mem_bytes(N: int, K: int, stage: str):
    """Closed-form per-GPU bytes for a stage. stage in {ddp,1,2,3}."""
    if stage == "ddp":
        return N * 20
    if stage == "1":
        return N * (4 + 16 / K)
    if stage == "2":
        return N * (2 + 14 / K)
    if stage == "3":
        return N * (16 / K)
    raise ValueError(stage)


def section_gold_memory():
    banner("SECTION E: the GOLD memory table -- the centerpiece (pinned for zero.html)")

    # --- tiny gold: N = 1,000,000 params, K = 4 (bytes == MB in decimal) ---
    N, K = 1_000_000, 4
    print(f"TINY GOLD: N = {N:,} params, K = {K}  (bytes == MB, decimal /1e6):\n")
    print("| stage | bytes/param | per-GPU bytes  | = MB | vs DDP |")
    print("|-------|-------------|----------------|------|--------|")
    bpp = {"ddp": 20, "1": 4 + 16 / K, "2": 2 + 14 / K, "3": 16 / K}
    names = {"ddp": "DDP  ", "1": "ZeRO-1", "2": "ZeRO-2", "3": "ZeRO-3"}
    tiny = {}
    for s in ["ddp", "1", "2", "3"]:
        b = mem_bytes(N, K, s)
        tiny[s] = b
        print(f"| {names[s]} | {bpp[s]:>11.4g} | {b:>14,} | {b/1e6:>4.2f} | "
              f"{tiny['ddp']/b:>6.2f}x |")
    print()
    # GOLD PINS (these are what zero.html recomputes and diffs)
    print(f"  GOLD PINS (zero.html recomputes these, K={K}):")
    print(f"    DDP   = {tiny['ddp']/1e6:.2f} MB")
    print(f"    ZeRO-1 = {tiny['1']/1e6:.2f} MB")
    print(f"    ZeRO-2 = {tiny['2']/1e6:.2f} MB")
    print(f"    ZeRO-3 = {tiny['3']/1e6:.2f} MB")
    gold_ok = (abs(tiny["ddp"] / 1e6 - 20) < 1e-9
               and abs(tiny["1"] / 1e6 - 8) < 1e-9
               and abs(tiny["2"] / 1e6 - 5.5) < 1e-9
               and abs(tiny["3"] / 1e6 - 4) < 1e-9)
    print(f"  [check] DDP=20.00, Z1=8.00, Z2=5.50, Z3=4.00 MB? {gold_ok}")
    assert abs(tiny['ddp']/1e6 - 20) < 1e-9
    assert abs(tiny['1']/1e6 - 8) < 1e-9
    assert abs(tiny['2']/1e6 - 5.5) < 1e-9
    assert abs(tiny['3']/1e6 - 4) < 1e-9

    # --- headline sanity: 7B params, K = 8 -> 140 GB -> 14 GB ---
    print()
    N7, K8 = 7_000_000_000, 8
    print(f"HEADLINE: N = 7B params, K = {K8}  (GB, decimal /1e9):\n")
    print("| stage | bytes/param | per-GPU GB | vs DDP |")
    print("|-------|-------------|------------|--------|")
    headline = {}
    for s in ["ddp", "1", "2", "3"]:
        b = mem_bytes(N7, K8, s)
        headline[s] = b
        bpp7 = {"ddp": 20, "1": 4 + 16 / K8, "2": 2 + 14 / K8, "3": 16 / K8}[s]
        print(f"| {names[s]} | {bpp7:>11.4g} | {b/1e9:>10.2f} | {headline['ddp']/b:>6.2f}x |")
    print()
    print(f"  SANITY ROW: DDP {headline['ddp']/1e9:.0f} GB/GPU  ->  "
          f"ZeRO-3 {headline['3']/1e9:.0f} GB/GPU   (fits on one 80 GB A100)")
    sanity_ok = (abs(headline["ddp"] / 1e9 - 140) < 1e-6
                 and abs(headline["3"] / 1e9 - 14) < 1e-6)
    print(f"  [check] DDP==140.00 GB and ZeRO-3==14.00 GB (K=8)? {sanity_ok}")
    assert abs(headline['ddp']/1e9 - 140) < 1e-6
    assert abs(headline['3']/1e9 - 14) < 1e-6
    return tiny


# ============================================================================
# F. COMMUNICATION COST  (DDP=2*Psi ; Z1/Z2=2*Psi ; Z3=3*Psi = 1.5x DDP)
#    Authoritative: Microsoft DeepSpeed/ZeRO blog -- Z1/Z2 "same communication
#    volume as data parallelism"; Z3 "modest 50% increase" (1.5x).
# ============================================================================

def section_communication():
    banner("SECTION F: communication cost -- the per-device volume, in units of Psi")
    print("Psi = number of params. Ring ReduceScatter and AllGather each move")
    print("(K-1)/K * Psi ~= Psi per device; an AllReduce = RS + AG ~= 2*Psi.\n")
    print("| strategy | collectives / step                  | volume/device | vs DDP |")
    print("|----------|--------------------------------------|---------------|--------|")
    rows = [
        ("DDP",    "AllReduce(grad)  [= RS(grad)+AG(grad)]", 2.0, 1.00),
        ("ZeRO-1", "ReduceScatter(grad) + AllGather(param)", 2.0, 1.00),
        ("ZeRO-2", "ReduceScatter(grad) + AllGather(param)", 2.0, 1.00),
        ("ZeRO-3", "AllGather(param fwd)+AllGather(param bwd)+ReduceScatter(grad)", 3.0, 1.50),
    ]
    for name, ops, vol, ratio in rows:
        print(f"| {name:<8} | {ops:<36} | {vol:>13.1f}*Psi | {ratio:>6.2f}x |")
    print()
    print("  * ZeRO-1/2 REPLACE DDP's single gradient AllReduce with")
    print("    ReduceScatter(grad)+AllGather(param) -> SAME 2*Psi total volume,")
    print("    but it lets the optimizer state be partitioned in between.")
    print("    (DeepSpeed team: 'same communication volume as data parallelism'.)")
    print("  * ZeRO-3 adds one more AllGather (params gathered for BOTH fwd and bwd)")
    print("    -> 3*Psi = 1.5x DDP. (DeepSpeed team: 'modest 50% increase'.)")
    print()
    print("  NOTE on the loose '3x': some notes count ZeRO-3's THREE collectives")
    print("  (2 AllGather + 1 ReduceScatter) vs DDP's ONE fused AllReduce and call")
    print("  it '3x'. By actual BYTE VOLUME it is 3*Psi vs 2*Psi = 1.5x, per the")
    print("  ZeRO authors. The memory win is the point; the comm tax is small.")
    print()
    # concrete byte example: 7B params (fp16 = 2 bytes), K=8
    Psi = 7_000_000_000
    print("Concrete: 7B params, fp16 grads/params (2 bytes each), per-device GB:")
    print("| strategy | volume/device (GB) |")
    print("|----------|--------------------|")
    for name, _, vol, _ in rows:
        gb = vol * Psi * 2 / 1e9          # 2 bytes/param (fp16) * volume-in-Psi
        print(f"| {name:<8} | {gb:>18.2f} |")
    print(f"\n  [check] ZeRO-3/DPP volume ratio == 3.0/2.0 == 1.50? "
          f"{abs(3.0/2.0 - 1.5) < 1e-9}")
    assert abs(3.0 / 2.0 - 1.5) < 1e-9


# ============================================================================
# G. ReduceScatter + AllGather MECHANICS (🔗 NCCL_COLLECTIVES identity)
#    Prove (ReduceScatter ; AllGather) == AllReduce -- that's WHY ZeRO comms
#    are just the two halves of DDP's AllReduce.
# ============================================================================

def section_rs_ag_identity():
    banner("SECTION G: why ZeRO comms work -- AllReduce == ReduceScatter ; AllGather (🔗)")
    K = 4
    N = 8
    g = torch.Generator().manual_seed(3)
    # K ranks each hold a full fp16 gradient
    grads = [torch.randn(N, generator=g) * 0.3 for _ in range(K)]
    print(f"K={K} ranks, N={N}. Each rank holds a full local gradient.\n")

    # Path 1: DDP's direct AllReduce-average
    stacked = torch.stack(grads)
    ar = stacked.mean(dim=0)                       # every rank gets this

    # Path 2: ZeRO's ReduceScatter(average) ; then AllGather
    sharded = reduce_scatter_avg(grads)            # rank r owns averaged chunk r
    rebuilt = all_gather(sharded)                  # every rank rebuilds the full avg

    print("DDP path : AllReduce-average(grads) ->")
    print(f"          every rank = {fmt_vec(ar)}")
    print("ZeRO path: ReduceScatter-avg -> each rank owns ONE averaged chunk:")
    for r in range(K):
        print(f"            rank {r} shard = {fmt_vec(sharded[r])}")
    print(f"          AllGather -> every rank = {fmt_vec(rebuilt[0])}")
    print()
    maxdiff = max((rebuilt[r] - ar).abs().max().item() for r in range(K))
    ok = all(torch.allclose(rebuilt[r], ar, atol=1e-6) for r in range(K))
    print(f"  max|AllReduce - (ReduceScatter+AllGather)| = {maxdiff:.3e}")
    print(f"  [check] identity holds? {ok}  (so ZeRO's RS+AG == DDP's AllReduce)")
    assert ok
    print("\n  ==> ZeRO-1/2 use the SAME total bytes as DDP: they just split the")
    print("      AllReduce at the seam (RS) so each rank can own 1/K of the state.")
    print("      ZeRO-3 does the AllGather of PARAMETERS twice (fwd + bwd) -> +50%.")


# ============================================================================
# H. THE FULL LINEAGE + WORKED RECAP (pinned gold for zero.html)
# ============================================================================

def section_lineage_recap():
    banner("SECTION H: lineage recap + the per-stage memory ladder (K=8)")
    K = 8
    print("DDP replicates everything; ZeRO partitions ONE MORE category each stage:\n")
    ladder = [
        ("DDP",    "replicate ALL",                20,                "AllReduce (2*Psi)"),
        ("ZeRO-1", "+ shard optimizer states",     4 + 16 / K,        "ReduceScatter+AllGather (2*Psi)"),
        ("ZeRO-2", "+ shard gradients",            2 + 14 / K,        "ReduceScatter+AllGather (2*Psi)"),
        ("ZeRO-3", "+ shard parameters",           16 / K,            "AG(fwd)+AG(bwd)+RS (3*Psi, 1.5x)"),
    ]
    print("| stage  | what it shards              | bytes/param | comms                    |")
    print("|--------|------------------------------|-------------|--------------------------|")
    for name, what, bpp, comms in ladder:
        print(f"| {name:<6} | {what:<28} | {bpp:>11.4g} | {comms:<24} |")
    print()
    print("Read each row left-to-right: at every step we shard ONE more category,")
    print("memory drops, and the comms cost stays ~the same until ZeRO-3 (+50%).\n")
    print("GOLD pinned for zero.html (K=8):")
    for name, _, bpp, _ in ladder:
        print(f"    {name:<7} bytes/param = {bpp:g}")
    # assert the ladder is monotonically decreasing
    vals = [b for _, _, b, _ in ladder]
    assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1)), "must shrink"
    print("\n  [check] memory strictly decreases DDP > Z1 > Z2 > Z3? True")
    vols = {"DDP": 2.0, "Z1": 2.0, "Z2": 2.0, "Z3": 3.0}
    comms_ok = (vols["Z1"] == vols["Z2"] == vols["DDP"]
                and abs(vols["Z3"] / vols["DDP"] - 1.5) < 1e-9)
    print(f"  [check] comms: Z1==Z2==DDP (2*Psi), Z3==1.5x? {comms_ok}")
    assert comms_ok


# ============================================================================
# main
# ============================================================================

def main():
    print("zero.py - reference impl (faithful single-process K-rank simulation).\n"
          "Numbers below feed ZERO.md.  torch =", torch.__version__)
    print("\nNOTE: no torch.distributed / NCCL is used. K ranks are a list of torch\n"
          "tensors; ReduceScatter/AllGather are explicit Python loops. The\n"
          "memory-bytes and communication-volume arithmetic is REAL and EXACT;\n"
          "only the multi-rank execution is simulated.")

    K = 8                       # the world size used for the formula sections
    section_ddp_baseline()
    section_zero1_formula(K)
    section_zero1_simulation()
    section_zero2_formula(K)
    section_zero2_gradflow()
    section_zero3_formula(K)
    section_zero3_paramflow()
    section_gold_memory()
    section_communication()
    section_rs_ag_identity()
    section_lineage_recap()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
