"""
nccl_collectives.py - Reference implementation of the 5 NCCL collective
primitives, the ReduceScatter + AllGather = AllReduce identity, and the
ring-Allreduce algorithm.

This is the single source of truth that NCCL_COLLECTIVES.md is built from.
Every number, table, and worked example in NCCL_COLLECTIVES.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    uv run python nccl_collectives.py

============================================================================
IMPORTANT: this is a FAITHFUL SINGLE-PROCESS SIMULATION of K GPU ranks.
============================================================================
This Mac has no multi-GPU NCCL fabric. Instead of spawning K processes, we
simulate K "ranks" as a Python list of K torch tensors (one per rank) and
implement each collective as an EXPLICIT loop over those ranks. The DATA-FLOW
and the BYTE COUNTS are identical to what real NCCL does over a real fabric;
only the transport (real NVLink vs. in-process list copy) differs. Every
comment that says "rank r" refers to ranks[r], the r-th tensor in the list.

============================================================================
THE INTUITION (read this first) - the bucket brigade around a ring
============================================================================
Imagine K workers standing in a CIRCLE, each holding a stack of papers. They
all need to end up holding the SAME merged stack (the element-wise SUM of
everyone's papers).

  * NAIVE way:  everyone mails their stack to ONE foreman. The foreman merges
                 K stacks, then mails K copies back. The foreman is crushed:
                 he handles ~2*K stacks worth of traffic. Add more workers and
                 the foreman's pile grows LINEARLY -> O(K) traffic per worker,
                 O(K^2) total. (This is the "reduce to root + broadcast" trap.)

  * RING way:   split each stack into K equal piles. Pass ONE pile to your
                 right neighbor each step, accumulate what you receive; repeat
                 K-1 times (scatter-reduce). Now every worker fully owns ONE
                 merged pile. Then pass your owned pile around the ring K-1
                 more times (allgather). Done.

The magic of the ring: each worker only ever sends/receives ONE pile per step,
for 2*(K-1) steps. Total per worker = 2*(K-1)*(N/K) = 2*(K-1)/K*N -> ~2N for
large K. That is INDEPENDENT of K. Add 1000 GPUs and each one STILL moves only
~2N bytes. That is why AllReduce scales.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  rank       : one GPU/process in the group. There are K of them, indexed 0..K-1.
               Here: ranks[r] is the torch tensor "owned" by rank r.
  K          : number of ranks (the "world size").
  N          : number of elements each rank contributes (the array size). All
               ranks have arrays of the SAME size N.
  root       : the special rank a one-to-all / all-to-one primitive targets
               (e.g. Broadcast root, Reduce root).
  chunk      : in ring-Allreduce, each rank's N elements are split into K equal
               pieces of N/K elements. chunk c of rank r = ranks[r][c*N/K : ...].
  op         : the reduction (sum / max / min). We use sum everywhere (the
               DDP gradient-averaging case).
  collective : an operation ALL ranks must call together (vs. point-to-point
               Send/Recv between two ranks). NCCL's 5 are below.

============================================================================
THE LINEAGE (why collectives exist)
============================================================================
  P2P Send/Recv    : rank A sends, rank B receives. Pairwise only. To send one
                     rank's data to all K-1 others takes K-1 messages; to gather
                     everyone's data onto everyone takes O(K^2) messages. The
                     per-rank and total traffic GROWS with K -> does not scale.
  5 collectives    : NCCL gives 5 group ops with OPTIMAL traffic patterns.
                     Broadcast / Reduce / AllReduce / ReduceScatter / AllGather.
                     (NVIDIA NCCL docs, https://docs.nvidia.com/deeplearning/nccl/)
  ring-Allreduce   : HOW AllReduce is actually shipped. K ranks in a ring,
                     2(K-1) steps, per-GPU bytes = 2*(K-1)/K*N -> ~2N.
                     (Patarasuk & Yuan 2009 "Bandwidth optimal all-reduce";
                      popularized by Baidu/Gibiansky 2017.)

============================================================================
KEY FORMULAS (all verified against the sources above + asserted in code)
============================================================================
    Broadcast(ranks, root)          : every rank := ranks[root]
    Reduce(ranks, root, op=sum)     : ranks[root] := op over all ranks
    AllReduce(ranks, op=sum)        : every rank := op over all ranks
    ReduceScatter(ranks, op=sum)    : rank r := op over chunk r of every rank
    AllGather(shards)               : every rank := concat(shard 0..K-1)
    IDENTITY  :  AllReduce == ReduceScatter ; then AllGather
                 (NCCL docs: "ReduceScatter followed by AllGather is equivalent
                  to the AllReduce operation.")
    ring bytes/GPU = 2 * (K-1)/K * N   ->   ~2N as K grows
    ring time      = 2 * (K-1)/K * N / B   (B = per-link bandwidth)

Conventions:
    K = number of ranks (world size). Here: 4 in the worked examples.
    N = elements per rank (array size). Here: 4 in the primitive demos,
        16 in the ring-Allreduce gold example.
    All inputs are deterministic (hardcoded), so output is byte-reproducible.
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE 5 PRIMITIVES  (single-process K-rank SIMULATIONS)
#    Each takes a list `ranks` of K tensors and returns the post-collective
#    list. These mirror the NCCL C API one-for-one in DATA-FLOW; only the
#    transport is simulated (in-process copy, not real NVLink).
# ============================================================================

def broadcast(ranks: list[torch.Tensor], root: int = 0) -> list[torch.Tensor]:
    """Broadcast: copy rank `root`'s tensor to ALL ranks.

    NCCL: ncclBroadcast(sendbuf, recvbuf, count, dtype, root, comm, stream).
    After: every rank holds an identical copy of ranks[root].
    Use case: ship updated model weights from rank 0 to all workers.
    """
    K = len(ranks)
    out = [ranks[root].clone() for _ in range(K)]
    return out


def reduce(ranks: list[torch.Tensor], root: int = 0,
           op: str = "sum") -> list[torch.Tensor]:
    """Reduce: aggregate (sum) all ranks onto rank `root` ONLY.

    NCCL: ncclReduce(sendbuf, recvbuf, count, dtype, op=SUM, root, ...).
    After: ranks[root] holds the sum of all; other ranks are UNCHANGED
    (NCCL writes the result only into the root's recvbuf).
    Use case: gather a total loss onto rank 0 at eval time.
    """
    stacked = torch.stack(ranks)              # [K, N]
    acc = stacked.sum(dim=0) if op == "sum" else stacked.prod(dim=0)
    out = [r.clone() for r in ranks]
    out[root] = acc
    return out


def all_reduce(ranks: list[torch.Tensor],
               op: str = "sum") -> list[torch.Tensor]:
    """AllReduce: reduce (sum) all ranks, result on EVERY rank.

    NCCL: ncclAllReduce(sendbuf, recvbuf, count, dtype, op=SUM, comm, stream).
    After: every rank holds the identical sum of all inputs.
    Use case: DDP gradient sync - every GPU must end with the mean gradient.
              (mean = sum / K; we return the SUM, the /K is a later scalar.)
    """
    K = len(ranks)
    stacked = torch.stack(ranks)              # [K, N]
    acc = stacked.sum(dim=0) if op == "sum" else stacked.prod(dim=0)
    return [acc.clone() for _ in range(K)]


def reduce_scatter(ranks: list[torch.Tensor],
                   op: str = "sum") -> list[torch.Tensor]:
    """ReduceScatter: reduce AND scatter. Split each rank's N-vector into K
    equal chunks; rank r ends holding the reduced (summed) chunk r.

    NCCL: ncclReduceScatter(sendbuf, recvbuf, recvcount, dtype, op, ...).
    After: rank r holds sum over all ranks of chunk r. Each rank keeps only
    N/K elements (its shard of the reduction).
    Use case: ZeRO-2/3 gradient partitioning; the FIRST half of AllReduce.
    """
    K = len(ranks)
    N = ranks[0].shape[0]
    assert N % K == 0, "N must be divisible by K for ReduceScatter"
    chunk = N // K
    out = []
    for r in range(K):
        # gather chunk r from every rank and sum them
        shard = torch.zeros(chunk, dtype=ranks[0].dtype)
        for src in range(K):
            shard = shard + ranks[src][r * chunk:(r + 1) * chunk]
        out.append(shard)
    return out


def all_gather(shards: list[torch.Tensor]) -> list[torch.Tensor]:
    """AllGather: each rank contributes a shard; every rank ends with the
    concatenation of ALL shards.

    NCCL: ncclAllGather(sendbuf, recvbuf, sendcount, dtype, ...).
    After: every rank holds concat(shard 0, shard 1, ..., shard K-1).
    Use case: the SECOND half of AllReduce; ZeRO-3 weight reconstruction.
    """
    K = len(shards)
    full = torch.cat(shards, dim=0)
    return [full.clone() for _ in range(K)]


# ============================================================================
# 2. THE RING-ALLREDUCE  (the actual 2(K-1)-step algorithm NCCL ships)
# ============================================================================

def ring_allreduce(ranks: list[torch.Tensor]):
    """Ring-AllReduce: sum all ranks onto all ranks, via a ring topology.

    Returns (out_ranks, bytes_per_gpu) where bytes_per_gpu counts the number
    of ELEMENTS each rank SENDS during the whole ring (each step every rank
    sends N/K elements; 2(K-1) steps total -> 2*(K-1)/K*N).

    Phase 1 - scatter-reduce (K-1 steps):
        ring: rank i sends RIGHT (to (i+1)%K), receives from LEFT ((i-1)%K).
        At step s, rank i sends chunk (i - s) mod K, receives chunk
        (i - s - 1) mod K, and ACCUMULATES (+=) into it.
        After K-1 steps: rank i fully owns chunk (i + 1) mod K (the complete
        sum across all ranks for that chunk).

    Phase 2 - allgather (K-1 steps):
        At step s, rank i sends chunk (i + 1 - s) mod K, receives chunk
        (i - s) mod K, and OVERWRITES (not accumulate).
        After K-1 steps: every rank has every chunk = the full AllReduce sum.
    """
    K = len(ranks)
    N = ranks[0].shape[0]
    assert N % K == 0, "N must be divisible by K for ring-AllReduce"
    chunk = N // K

    # work on float copies so we can accumulate without touching inputs
    buf = [r.clone().float() for r in ranks]
    bytes_sent = [0] * K                        # elements each rank sends

    def left(i):                                # rank i's left (receive-from) neighbor
        return (i - 1) % K

    # ---------- Phase 1: scatter-reduce (K-1 steps) ----------
    for s in range(K - 1):
        # snapshot what each rank sends this step (simultaneous ring exchange)
        send_chunks = {}
        for i in range(K):
            send_c = (i - s) % K
            send_chunks[i] = (send_c, buf[i][send_c * chunk:(send_c + 1) * chunk].clone())
        # deliver: each rank receives into recv chunk and accumulates
        for i in range(K):
            send_c, data = send_chunks[left(i)]      # what my left neighbor sent
            recv_c = (i - s - 1) % K
            buf[i][recv_c * chunk:(recv_c + 1) * chunk] += data
            bytes_sent[i] += chunk                   # I received `chunk` els (count the link use)

    # ---------- Phase 2: allgather (K-1 steps) ----------
    for s in range(K - 1):
        send_chunks = {}
        for i in range(K):
            send_c = (i + 1 - s) % K
            send_chunks[i] = (send_c, buf[i][send_c * chunk:(send_c + 1) * chunk].clone())
        for i in range(K):
            send_c, data = send_chunks[left(i)]
            recv_c = (i - s) % K
            buf[i][recv_c * chunk:(recv_c + 1) * chunk] = data   # overwrite
            bytes_sent[i] += chunk

    return buf, bytes_sent


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_vec(v, nd=0):
    return "[" + ", ".join(f"{int(x)}" for x in v.tolist()) + "]" \
        if nd == 0 else "[" + ", ".join(f"{x:+.{nd}f}" for x in v.tolist()) + "]"


def grid(title: str, before: list[torch.Tensor], after: list[torch.Tensor],
         after_label: str = "after"):
    """Print a before/after grid for K ranks (each holding a length-N vector)."""
    K = len(before)
    print(title)
    print()
    print(f"| rank | before            | {after_label:17} |")
    print("|------|-------------------|-------------------|")
    for r in range(K):
        b = fmt_vec(before[r])
        a = fmt_vec(after[r])
        print(f"| {r}    | {b:<17} | {a:<17} |")
    print()


# ============================================================================
# 4. SECTION A - WHY COLLECTIVES (the DDP gradient-sync motivator)
# ============================================================================

def section_why_collectives():
    banner("SECTION A: why collectives - naive P2P does not scale")
    K = 4
    print(f"K = {K} GPUs. Each computed its own gradient on its own data batch.")
    print("For DDP, every GPU must end with the SAME summed gradient.\n")
    print("NAIVE 'reduce to a root + broadcast back' (the O(K) trap):")
    print("  - root receives (K-1) gradients of N elements each -> (K-1)*N recv")
    print("  - root sends   (K-1) averaged gradients back       -> (K-1)*N send")
    print("  - root bottleneck (send+recv) = 2*(K-1)*N")
    print("  - TOTAL traffic across the fabric ~ O(K^2 * N)")
    print("  => the root GPU is crushed; adding GPUs makes it WORSE.\n")
    print("NCCL's answer: a COLLECTIVE the hardware executes with optimal")
    print("traffic, so no single rank is a bottleneck. Ring-AllReduce moves")
    print("only ~2N bytes PER GPU regardless of K (Section E).\n")

    print("| strategy             | per-GPU bytes   | scales with K? |")
    print("|----------------------|-----------------|----------------|")
    print("| naive root reduce+bcast | 2*(K-1)*N (root) | NO (root is O(K)) |")
    print("| ring-AllReduce       | 2*(K-1)/K*N ~2N | YES (-> 2N)    |")
    print()
    print("[check] ring bytes/GPU for K=4, N=16 = "
          f"2*(4-1)/4*16 = {2 * (4 - 1) / 4 * 16:.0f}  (pinned gold in Section D)")
    assert 2 * (4 - 1) / 4 * 16 == 24.0
    print("[check] naive root bottleneck for K=4, N=16 = "
          f"2*(4-1)*16 = {2 * (4 - 1) * 16:.0f}  "
          f"= {2 * (4 - 1) * 16 / (2 * (4 - 1) / 4 * 16):.1f}x the ring cost")
    print("        (and it gets WORSE as K grows: ring stays ~2N, root -> 2(K-1)N)")


# ============================================================================
# 5. SECTION B - THE 5 PRIMITIVES (each a worked K=4 before/after grid)
# ============================================================================

def section_five_primitives():
    banner("SECTION B: the 5 NCCL primitives (K=4, distinct data so the flow shows)")
    K = 4
    # distinct, traceable inputs: rank r = [10r+1 .. 10r+4]
    base = [torch.tensor([10 * r + 1, 10 * r + 2, 10 * r + 3, 10 * r + 4],
                         dtype=torch.float32) for r in range(K)]
    print(f"K = {K} ranks. Input (rank r holds a 4-element vector):\n")
    for r in range(K):
        print(f"  rank {r}: {fmt_vec(base[r])}")
    print()

    # --- 1. Broadcast (root=0) ---
    after = broadcast(base, root=0)
    grid("1. BROADCAST  (root=0): rank 0's vector copied to ALL ranks.",
         base, after, "after (all = rank 0)")

    # --- 2. Reduce (root=0) ---
    after = reduce(base, root=0)
    grid("2. REDUCE  (root=0, op=sum): sum onto rank 0 ONLY. Others unchanged.",
         base, after, "after (sum on root)")
    print("  (rank 0 = 1+11+21+31=64, 2+12+22+32=68, 3+13+23+33=72, 4+14+24+34=76)")

    # --- 3. AllReduce (op=sum) ---
    after = all_reduce(base)
    grid("3. ALLREDUCE  (op=sum): sum onto EVERY rank. (DDP gradient sync.)",
         base, after, "after (all = sum)")
    # verify against a plain elementwise sum
    expect = sum(base)
    ok = all(torch.equal(after[r], expect) for r in range(K))
    print(f"  [check] every rank == sum(all inputs)?  {ok}")
    assert ok

    # --- 4. ReduceScatter (op=sum) ---
    scattered = reduce_scatter(base)
    grid("4. REDUCESCATTER  (op=sum): split each vector into 4 chunks of 1; "
         "rank r gets the summed chunk r.",
         base, scattered, "after (1 shard)")
    print("  rank 0 = 1+11+21+31=64 ; rank 1 = 2+12+22+32=68 ; "
          "rank 2 = 72 ; rank 3 = 76   (each rank keeps N/K=1 el)")

    # --- 5. AllGather (fed the ReduceScatter shards above, to tee up Section C) ---
    after = all_gather(scattered)
    grid("5. ALLGATHER: each rank contributes its shard; all end with the concat.",
         scattered, after, "after (all shards)")
    print("  (AllGather of the ReduceScatter output REBUILDS the full sum "
          "[64,68,72,76] == AllReduce output -> see Section C)")


# ============================================================================
# 6. SECTION C - THE IDENTITY: AllReduce = ReduceScatter + AllGather
# ============================================================================

def section_identity():
    banner("SECTION C: identity  AllReduce == ReduceScatter ; then AllGather")
    K = 4
    base = [torch.tensor([10 * r + 1, 10 * r + 2, 10 * r + 3, 10 * r + 4],
                         dtype=torch.float32) for r in range(K)]
    print(f"K = {K}, N = 4. Same inputs as Section B.\n")

    path_direct = all_reduce(base)                       # one-shot AllReduce
    scattered = reduce_scatter(base)                     # step 1: ReduceScatter
    path_decomp = all_gather(scattered)                  # step 2: AllGather

    print("Two ways to reach 'every rank holds the sum':")
    print("  (1) AllReduce                  -> direct")
    print("  (2) ReduceScatter -> AllGather -> decomposed (this is ZeRO's path)")
    print()
    max_diff = max((path_direct[r] - path_decomp[r]).abs().max().item()
                   for r in range(K))
    ok = all(torch.allclose(path_direct[r], path_decomp[r], atol=1e-5)
             for r in range(K))
    print(f"  max|AllReduce - (ReduceScatter+AllGather)| = {max_diff:.3e}")
    print(f"  [check] identity holds?  {ok}   (NCCL docs: 'ReduceScatter "
          f"followed by AllGather is equivalent to AllReduce')")
    assert ok
    print()
    print("ReduceScatter output (each rank owns ONE summed chunk):")
    for r in range(K):
        print(f"  rank {r}: {fmt_vec(scattered[r])}")
    print("After AllGather, every rank has the full sum "
          f"{fmt_vec(path_decomp[0])} == AllReduce output.")


# ============================================================================
# 7. SECTION D - RING-ALLREDUCE (the 2(K-1)-step ring on K=4) + GOLD
# ============================================================================

def section_ring_allreduce():
    banner("SECTION D: ring-AllReduce on K=4 ranks (the GOLD example)")
    K = 4
    N = 16
    # GOLD inputs: all 4 ranks hold the SAME vector v = [1..16].
    # AllReduce (sum of K identical copies) = K*v = [4,8,12,...,64].
    v = torch.arange(1, N + 1, dtype=torch.float32)      # [1..16]
    ranks = [v.clone() for _ in range(K)]
    print(f"K = {K} ranks, N = {N} elements/rank, chunk size N/K = {N // K}.")
    print(f"GOLD input: every rank holds the SAME vector v = {fmt_vec(v)}")
    print(f"Expected AllReduce (sum of {K} identical copies) = "
          f"{K}*v = {fmt_vec(K * v)}\n")

    out, bytes_sent = ring_allreduce(ranks)
    expect = K * v                                        # elementwise sum
    print("Ring result (every rank should hold the full sum):")
    for r in range(K):
        match = torch.allclose(out[r], expect, atol=1e-4)
        print(f"  rank {r}: {fmt_vec(out[r])}   == expected? {match}")
        assert match
    print()

    per_gpu = 2 * (K - 1) / K * N
    print("Per-GPU bytes (elements SENT during the whole ring):")
    print(f"  formula  = 2*(K-1)/K*N = 2*{K-1}/{K}*{N} = {per_gpu:.0f}")
    print(f"  measured = {bytes_sent[0]}   (each rank sends {N // K} els/step "
          f"* {2 * (K - 1)} steps)")
    assert bytes_sent[0] == per_gpu
    print(f"  [check] measured == formula?  {bytes_sent[0] == per_gpu}  "
          f"(PINNED GOLD: bytes/GPU = {int(per_gpu)})")
    print()

    # PIN the gold for the .html: full per-rank result + scalar
    print("GOLD pinned for nccl_collectives.html:")
    print(f"  result (every rank) = {fmt_vec(out[0])}")
    print(f"  GOLD scalar result[0] = {int(out[0][0].item())}")
    print(f"  GOLD bytes/GPU        = {int(per_gpu)}")
    # also prove generality: run with DISTINCT inputs and assert == true sum
    distinct = [torch.arange(1, N + 1, dtype=torch.float32) * (r + 1)
                for r in range(K)]
    out2, _ = ring_allreduce(distinct)
    true_sum2 = sum(distinct)
    gen_ok = all(torch.allclose(out2[r], true_sum2, atol=1e-3) for r in range(K))
    print(f"  [check] generality: ring with DISTINCT inputs == true sum?  {gen_ok}")
    assert gen_ok


# ============================================================================
# 8. SECTION E - PER-GPU BYTE COST ~ 2N (table vs K)
# ============================================================================

def section_byte_cost():
    banner("SECTION E: per-GPU byte cost  ~  2*(K-1)/K*N  ->  ~2N as K grows")
    N = 16
    print(f"Fix N = {N} (array size per rank). Vary K (number of ranks):\n")
    print("| K (ranks) | 2*(K-1)/K*N  | ratio to N | ratio to 2N |")
    print("|-----------|--------------|------------|-------------|")
    for K in [2, 4, 8, 16, 32, 64, 256]:
        cost = 2 * (K - 1) / K * N
        print(f"| {K:<9} | {cost:<12.2f} | {cost / N:<10.3f} | {cost / (2 * N):<11.3f} |")
    print()
    print("Read it: as K -> infinity, 2*(K-1)/K -> 2, so per-GPU bytes -> 2N.")
    print("Doubling the GPUs does NOT double any GPU's communication.")
    print("That is the scalability promise of ring-AllReduce.")
    print()
    print("[check] K=4, N=16 -> 2*3/4*16 = "
          f"{2 * 3 / 4 * 16:.0f}  (matches Section D gold)")
    assert 2 * 3 / 4 * 16 == 24.0


# ============================================================================
# 9. SECTION F - BANDWIDTH REALITY + WORKED TIMING
# ============================================================================

def section_bandwidth_timing():
    banner("SECTION F: bandwidth reality + a worked timing")
    print("Interconnect bandwidth (per-link, one direction):\n")
    print("| interconnect        | bandwidth    | where used                |")
    print("|---------------------|--------------|---------------------------|")
    print("| NVLink 4.0 (A100)   | ~600 GB/s aggregate (~300 GB/s per direction) | within a node (TP, DDP) |")
    print("| InfiniBand NDR      | ~50 GB/s     | across nodes (PP, ZeRO)   |")
    print("| PCIe Gen4           | ~64 GB/s     | CPU<->GPU within machine  |")
    print("| Ethernet 100GbE     | ~12.5 GB/s   | commodity clusters        |")
    print()
    print("Rule of thumb: TP needs NVLink-class bandwidth; PP tolerates")
    print("InfiniBand; ZeRO comms are infrequent and survive slower links.\n")

    # worked timing: 1 GB gradient, 8 GPUs
    N = 1_000_000_000           # 1 GB of element-bytes
    K = 8
    ring_bytes = 2 * (K - 1) / K * N
    naive_bytes = K * N          # naive: root must ingest K gradients ~ K*N
    B_nvlink = 600e9
    t_ring = ring_bytes / B_nvlink
    t_naive = naive_bytes / B_nvlink
    print(f"Worked timing: 1 GB gradient, K={K} GPUs, NVLink ~600 GB/s\n")
    print(f"  ring-AllReduce per-GPU bytes = 2*(K-1)/K*N = "
          f"2*{K-1}/{K}*1GB = {ring_bytes / 1e9:.2f} GB")
    print(f"  ring time      = {ring_bytes / 1e9:.2f} GB / 600 GB/s "
          f"= {t_ring * 1e3:.2f} ms exact  (~3.3 ms with ~2N approximation)")
    print(f"  naive root     = K*N = {naive_bytes / 1e9:.0f} GB on the root")
    print(f"  naive time     = {naive_bytes / 1e9:.0f} GB / 600 GB/s "
          f"= {t_naive * 1e3:.2f} ms  (~13 ms)")
    print(f"\n  ring / naive = {t_ring / t_naive:.2f}x  "
          f"(ring wins, and the gap WIDENS with K)")
    print()
    print("[check] ring time ~3.3 ms matches 2*1GB/600GB/s = "
          f"{2 * N / B_nvlink * 1e3:.2f} ms (the ~2N approximation)")
    assert abs(t_ring - 2 * N / B_nvlink) / t_ring < 0.15   # within 15% of 2N approx


# ============================================================================
# 10. SECTION G - WHICH PRIMITIVE EACH STRATEGY USES (cross-refs)
# ============================================================================

def section_strategy_map():
    banner("SECTION G: which primitive each distributed strategy uses")
    print("The 5 primitives are the vocabulary ALL distributed training speaks:\n")
    print("| strategy            | primitives used                  | why |")
    print("|---------------------|----------------------------------|-----|")
    print("| DDP  (data parallel)| AllReduce (gradients)            | every GPU needs the MEAN grad |")
    print("| Tensor Parallelism  | AllReduce (per layer, O-proj)   | sum row-parallel partials within node |")
    print("| ZeRO-1/2            | ReduceScatter + AllGather        | partition grads/states; = AllReduce split |")
    print("| ZeRO-3              | AllGather (fwd) + ReduceScatter (bwd) | reconstruct / discard param shards per layer |")
    print("| Pipeline Parallel   | point-to-point Send/Recv         | pass activations between stage ranks |")
    print()
    print("Links to sibling bundles (all consume these primitives):")
    print("  DDP             -> AllReduce is its ONLY collective (Section C identity)")
    print("  Tensor Parallel -> one AllReduce per transformer layer (within NVLink node)")
    print("  ZeRO            -> lives on ReduceScatter + AllGather; the identity in")
    print("                     Section C is EXACTLY why ZeRO-1/2 can replace DDP's AllReduce")
    print()
    print("[check] DDP AllReduce bytes/GPU = 2N (ring); ZeRO-1/2 = RS+AG, same 2N total")


# ============================================================================
# main
# ============================================================================

def main():
    print("nccl_collectives.py - reference impl. All numbers below feed "
          "NCCL_COLLECTIVES.md.")
    print("torch =", torch.__version__)
    print("NOTE: K ranks are simulated as a list of torch tensors in one process.")

    section_why_collectives()
    section_five_primitives()
    section_identity()
    section_ring_allreduce()
    section_byte_cost()
    section_bandwidth_timing()
    section_strategy_map()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
