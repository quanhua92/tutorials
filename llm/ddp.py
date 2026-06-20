"""
ddp.py - Reference implementation of Distributed Data Parallel (DDP) training.

This is the single source of truth that DDP.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python ddp.py

== IMPORTANT — this is a FAITHFUL SINGLE-PROCESS SIMULATION of K=2 DDP ranks ==
We do NOT spawn processes, use torch.distributed, or call NCCL. Instead we hold
two FULL model replicas as separate leaf tensors and implement AllReduce as an
explicit Python average loop. The MATH is bit-for-bit identical to real DDP;
only the EXECUTION MODEL differs (one process instead of K). This makes every
number printable and reproducible on a laptop, with no GPU or cluster required.

== The big idea, in one paragraph (no math) ==================================
One GPU is not fast enough and its per-step batch is too small. DDP copies the
WHOLE model onto every GPU; each GPU eats a DIFFERENT mini-batch, runs forward
+ backward to get LOCAL gradients, then AllReduces (averages) those gradients
so every GPU ends up with the IDENTICAL gradient. Because every GPU now sees
the same gradient and starts from the same weights, the optimizer step is
identical on every GPU -> the replicas NEVER drift. Wrap that with gradient
accumulation (fake a big batch by summing many small ones), mixed precision
(fp16 forward / fp32 master weights), and a cosine+warmup learning rate, and
you can train big models fast and reproducibly.

== The DDP algorithm (per optimizer step) =====================================
    1. Every rank holds a FULL replica of the parameters  (identical init).
    2. Each rank runs fwd + bwd on its OWN mini-batch  -> local gradient g_k.
    3. AllReduce: every rank ends up with  avg = mean_k(g_k).
    4. Every rank runs the SAME optimizer step on avg  -> parameters stay equal.

== Plain-English glossary (used in every section below) ======================
    rank (k)      one GPU / one replica, numbered 0..K-1.
    world_size(K) how many replicas (= how many GPUs) run in parallel.
    mini-batch    the chunk of data ONE rank processes in one forward pass.
    gradient (g)  the per-parameter derivative of the loss; what the optimizer
                  subtracts (scaled by the learning rate) to improve the model.
    AllReduce     a collective op: every rank contributes a tensor and every
                  rank ends up with the SAME result (here: the average).
    optimizer step the update  W <- W - lr * g  (SGD) or the Adam equivalent.
    replica drift the (undesired) situation where ranks' params diverge. DDP's
                  whole job is to make drift mathematically impossible.
    effective batch the total number of samples one optimizer step 'sees':
                  bs_per_gpu * grad_accum_steps * world_size.

== Tensor-shape conventions ===================================================
    B    = per-GPU (micro-)batch size
    E_in = input feature dim of the tiny demo model
    E_out= output feature dim
    W    = weight matrix, shape [E_in, E_out]
    x    = one rank's input batch, shape [B, E_in]
    t    = one rank's target batch,  shape [B, E_out]
"""

from __future__ import annotations

import math

import torch

torch.set_printoptions(precision=6, sci_mode=False)

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# 0. THE TINY DEMO MODEL + DDP PRIMITIVES
#    A single linear layer (no bias) with MSE loss. Small enough that every
#    gradient entry is printable; complete enough that all DDP behaviour shows.
# ----------------------------------------------------------------------------

E_IN = 4     # input feature dim
E_OUT = 3    # output feature dim
B = 2        # per-GPU micro-batch size
K = 2        # world size (number of replicas we simulate)


def forward(x: torch.Tensor, W: torch.Tensor) -> torch.Tensor:
    """y = x @ W   (linear layer, no bias)."""
    return x @ W


def mse_loss(y: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Mean-squared error, averaged over ALL elements (batch and features).

    Averaging (not summing) is what makes the AllReduce-AVERAGE of per-rank
    gradients equal to the single-GPU gradient on the concatenated batch
    (Section B proves this)."""
    return ((y - target) ** 2).mean()


def local_grad(x: torch.Tensor, W: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Run fwd+bwd on ONE rank's mini-batch; return dL/dW (detached).

    This is exactly what each GPU computes locally before AllReduce."""
    Wc = W.detach().clone().requires_grad_(True)
    y = forward(x, Wc)
    loss = mse_loss(y, target)
    loss.backward()
    return Wc.grad.detach()


def allreduce_avg(grads: list[torch.Tensor]) -> list[torch.Tensor]:
    """Faithful single-process simulation of NCCL AllReduce (average).

    Real DDP: every rank sends its gradient, they are summed and divided by
    world_size, and the result is broadcast back so every rank holds the SAME
    averaged gradient. We do the same explicitly:

        avg = (g_0 + g_1 + ... + g_{K-1}) / K

    and hand every rank an identical copy. Returns K identical tensors.
    """
    assert len(grads) > 0
    avg = grads[0].clone()
    for g in grads[1:]:
        avg = avg + g
    avg = avg / len(grads)
    return [avg.clone() for _ in grads]


def sgd_step(W: torch.Tensor, grad: torch.Tensor, lr: float) -> torch.Tensor:
    """Vanilla SGD update:  W_new = W - lr * grad.  (detached, no autograd)."""
    return (W - lr * grad).detach()


# ----------------------------------------------------------------------------
# 1. PRETTY PRINTERS
# ----------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_vec(v, nd=6):
    return "[" + ", ".join(f"{x:+.{nd}f}" for x in v.tolist()) + "]"


# ----------------------------------------------------------------------------
# 2. SECTIONS  (the numbers that feed DDP.md)
# ----------------------------------------------------------------------------

def make_data():
    """Deterministic, seeded inputs + identical-init replicas.

    Both replicas start from the SAME W (seeded g_w) -- this models DDP
    broadcasting rank 0's weights to everyone at construction time. The two
    ranks then get DIFFERENT mini-batches (seeded g_data) -- this is the
    'data parallel' split."""
    g_w = torch.Generator().manual_seed(0)
    W0 = (torch.randn(E_IN, E_OUT, generator=g_w) * 0.1)
    W1 = W0.clone()                       # identical init (DDP broadcast)

    g_data = torch.Generator().manual_seed(42)
    X0 = torch.randn(B, E_IN, generator=g_data)
    T0 = torch.randn(B, E_OUT, generator=g_data)
    X1 = torch.randn(B, E_IN, generator=g_data)   # DIFFERENT mini-batch
    T1 = torch.randn(B, E_OUT, generator=g_data)
    return W0, W1, X0, T0, X1, T1


def section_algorithm(W0, W1, X0, T0, X1, T1):
    banner("SECTION A: the DDP step -- local grads -> AllReduce -> averaged grad")
    print(f"world_size K = {K}   (we simulate {K} replicas in ONE process)\n")
    print("Both replicas start IDENTICAL (DDP broadcasts rank 0's weights):\n")
    print(f"  W (rank 0) = {fmt_vec(W0.reshape(-1))}")
    print(f"  W (rank 1) = {fmt_vec(W1.reshape(-1))}")
    same_init = torch.allclose(W0, W1)
    print(f"\n  [check] W0 == W1 at init?  {same_init}")
    assert same_init, "replicas must start identical"

    print(f"\nEach rank gets a DIFFERENT mini-batch (B={B}, E_in={E_IN}):")
    print(f"  X0 (rank 0 batch, row 0) = {fmt_vec(X0[0])}")
    print(f"  X1 (rank 1 batch, row 0) = {fmt_vec(X1[0])}")
    diff_batch = not torch.allclose(X0, X1)
    print(f"\n  [check] X0 != X1 (different data)?  {diff_batch}")
    assert diff_batch, "ranks must see different data"

    print("\n--- STEP 1+2: each rank runs fwd+bwd on its OWN batch -> local grad ---")
    g0 = local_grad(X0, W0, T0)
    g1 = local_grad(X1, W1, T1)
    print(f"\n  g0 (rank 0 local grad) = {fmt_vec(g0.reshape(-1))}")
    print(f"  g1 (rank 1 local grad) = {fmt_vec(g1.reshape(-1))}")
    print("\n  These differ, because the batches differ. Left alone, the two")
    print("  replicas would take different steps and DRIFT apart.\n")

    print("--- STEP 3: AllReduce (average) -- every rank gets the SAME grad ---")
    [g0_avg, g1_avg] = allreduce_avg([g0, g1])
    print(f"\n  avg = (g0 + g1) / 2 = {fmt_vec(g0_avg.reshape(-1))}")
    print(f"  rank 0 now holds     = {fmt_vec(g0_avg.reshape(-1))}")
    print(f"  rank 1 now holds     = {fmt_vec(g1_avg.reshape(-1))}")
    synced = torch.allclose(g0_avg, g1_avg)
    print(f"\n  [check] both ranks hold the IDENTICAL averaged grad?  {synced}")
    assert synced, "AllReduce must give every rank the same gradient"
    return g0, g1, g0_avg


def section_why_sync_keeps_identical(W0, W1, X0, T0, X1, T1, g0, g1, g_avg):
    banner("SECTION B: WHY AllReduce keeps replicas identical (the proof)")
    print("Claim: DDP on K=2 GPUs with batches X0, X1 is MATHEMATICALLY EQUAL to\n"
          "single-GPU training on the CONCATENATED batch [X0; X1]. Because the\n"
          "loss is a MEAN, the gradient of the mean-of-two-halves equals the\n"
          "average of the two half-gradients. So AllReduce-AVERAGE reconstructs\n"
          "exactly the gradient one big GPU would have computed.\n")

    # single-GPU reference: concatenate the two batches
    Xcat = torch.cat([X0, X1], dim=0)
    Tcat = torch.cat([T0, T1], dim=0)
    g_single = local_grad(Xcat, W0, Tcat)
    print(f"Single-GPU grad on cat([X0;X1]) (batch {2*B}) = "
          f"{fmt_vec(g_single.reshape(-1))}")
    print(f"DDP averaged grad (AllReduce of g0,g1)        = "
          f"{fmt_vec(g_avg.reshape(-1))}")
    eq = torch.allclose(g_avg, g_single, atol=1e-6)
    maxd = (g_avg - g_single).abs().max().item()
    print(f"\n  [check] DDP avg grad == single-GPU grad?  {eq}   "
          f"(max|diff| = {maxd:.2e})")
    assert eq, "DDP averaged grad must equal single-GPU concatenated grad"

    print("\n--- Consequence: the optimizer step is identical everywhere ---")
    lr = 0.1
    W0_new = sgd_step(W0, g_avg, lr)
    W1_new = sgd_step(W1, g_avg, lr)
    W_single = sgd_step(W0, g_single, lr)
    print(f"\n  lr = {lr}")
    print(f"  W0 after step (rank 0) = {fmt_vec(W0_new.reshape(-1))}")
    print(f"  W1 after step (rank 1) = {fmt_vec(W1_new.reshape(-1))}")
    print(f"  single-GPU after step  = {fmt_vec(W_single.reshape(-1))}")
    r01 = torch.allclose(W0_new, W1_new, atol=1e-6)
    r_single = torch.allclose(W0_new, W_single, atol=1e-6)
    print(f"\n  [check] rank0 == rank1 after step?         {r01}   (no drift)")
    print(f"  [check] rank0 == single-GPU after step?    {r_single}  (DDP==1 big GPU)")
    assert r01 and r_single

    print("\n  ==> Identical averaged grad  +  identical start  +  identical step")
    print("      ==> replicas are BIT-IDENTICAL after every step. Drift is")
    print("      mathematically impossible. That is the whole point of DDP.")
    # gold pins for the .html
    print("\n  GOLD pins (used by ddp.html gold-check badge):")
    print(f"    avg_grad[0,0]      = {g_avg[0, 0].item():+.6f}")
    print(f"    W_after_step[0,0]  = {W0_new[0, 0].item():+.6f}   "
          f"(lr={lr})")
    return lr, g_avg, W0_new


def section_grad_accumulation(W0):
    banner("SECTION C: gradient accumulation -- faking a big batch, syncing once")
    print("effective_batch = bs_per_gpu * grad_accum_steps * world_size\n")
    accum = 2                      # micro-steps per rank before one optimizer update
    eff = B * accum * K
    print(f"  B={B}  accum={accum}  world_size={K}  ->  effective batch = "
          f"{B}*{accum}*{K} = {eff} samples / optimizer step\n")

    g_d = torch.Generator().manual_seed(7)
    # 4 micro-batches: rank0 gets ma, mb ; rank1 gets mc, md
    batches = []
    for _ in range(accum * K):
        batches.append((torch.randn(B, E_IN, generator=g_d),
                        torch.randn(B, E_OUT, generator=g_d)))

    print("The require_backward_grad_sync trick (from nanoGPT/train.py):")
    print("  only the LAST micro-step triggers AllReduce; earlier micro-steps")
    print("  accumulate locally with NO cross-rank communication. This avoids")
    print(f"  doing {accum}x AllReduces when 1x suffices.\n")

    # --- DDP path: accumulate locally (loss /= accum), AllReduce only at end ---
    rank_batches = [batches[0:accum], batches[accum:]]   # rank0, rank1
    local_accum = [torch.zeros_like(W0), torch.zeros_like(W0)]
    for rank in range(K):
        for (xb, tb) in rank_batches[rank]:
            # loss /= accum  <=>  accumulate (1/accum) of each micro-grad
            local_accum[rank] = local_accum[rank] + local_grad(xb, W0, tb) / accum
    [g_ddp0, _] = allreduce_avg(local_accum)   # single AllReduce at the end

    # --- single-GPU reference: the full effective batch (8 samples) ---
    Xall = torch.cat([xb for (xb, _) in batches], dim=0)
    Tall = torch.cat([tb for (_, tb) in batches], dim=0)
    g_ref = local_grad(Xall, W0, Tall)

    print(f"  DDP:  sum_k (sum_micro local_grad/accum) then AllReduce-avg")
    print(f"        = {fmt_vec(g_ddp0.reshape(-1))}")
    print(f"  single-GPU on all {eff} samples = {fmt_vec(g_ref.reshape(-1))}")
    eq = torch.allclose(g_ddp0, g_ref, atol=1e-6)
    print(f"\n  [check] accumulated+synced grad == single-GPU {eff}-sample grad? "
          f"{eq}  (max|diff|={( g_ddp0 - g_ref).abs().max().item():.2e})")
    assert eq
    print("\n  ==> Gradient accumulation + a single final AllReduce is EXACTLY")
    print("      equivalent to one giant batch. effective_batch math holds.")


def section_amp_and_scaler():
    banner("SECTION D: AMP + GradScaler -- fp16 forward, fp32 master, loss scaling")
    print("Mixed precision (Micikevicius et al. 2017, arXiv:1710.03740):\n"
          "  - forward + backward in fp16 (fast, half the memory)\n"
          "  - keep an fp32 MASTER copy of weights (accumulates tiny updates)\n"
          "  - fp16 has a TINY range [6e-5, 65504]: small gradients UNDERFLOW to 0\n"
          "  - GradScaler multiplies the LOSS by a big constant (e.g. 2^16) so the\n"
          "    backward gradients are pushed up into fp16's representable range,\n"
          "    then divides them back before the optimizer step.\n"
          "  - bfloat16 shares fp32's EXPONENT range -> no underflow -> no scaler.\n")

    print("| grad (fp32)    | fp16(grad) | survived? | bf16(grad) |")
    print("|----------------|------------|-----------|------------|")
    for val in [1e-3, 1e-5, 1e-7, 1e-8]:
        f = torch.tensor(val, dtype=torch.float32)
        f16 = f.to(torch.float16)
        bf = f.to(torch.bfloat16)
        survived = "YES" if f16.item() != 0.0 else "NO (underflow!)"
        print(f"| {val:<14.0e} | {f16.item():<10.3e} | {survived:<9} | "
              f"{bf.item():<10.3e} |")
    print("\n  Notice: 1e-8 rounds to 0.0 in fp16 but survives in bf16. fp16's\n"
          "  smallest subnormal is ~6e-8, so anything smaller vanishes silently.")

    print("\n--- How GradScaler rescues an underflowing gradient ---")
    g_true = torch.tensor([1e-8], dtype=torch.float32)   # the real gradient
    scale = 2.0 ** 16                                       # = 65536
    print(f"  true grad      = {g_true[0].item():.3e}  (fp32)")
    g16_naive = g_true.to(torch.float16)
    print(f"  fp16(grad)     = {g16_naive[0].item():.3e}  <-- LOST (underflow to 0)")
    g_scaled = (g_true * scale).to(torch.float16)
    print(f"  scale = 2^16   = {scale:.0f}")
    print(f"  fp16(grad*scale)= {g_scaled[0].item():.3e}  <-- SURVIVES")
    g_recovered = (g_scaled.float() / scale)
    print(f"  unscale back   = {g_recovered[0].item():.3e}  <-- recovered ~true grad")
    rec_ok = abs(g_recovered.item() - g_true.item()) < 1e-9
    print(f"\n  [check] scaled->fp16->unscaled recovers the true grad?  {rec_ok}")
    assert rec_ok

    print("\n--- The full fp16 step flow (nanoGPT/train.py) ---")
    print("  loss_scaled = loss * S                          # scale up")
    print("  scaler.scale(loss_scaled).backward()            # grads ~Sx bigger")
    print("  scaler.unscale_(optimizer)                      # divide grads back")
    print("  clip_grad_norm_(...)                            # clip on true grads")
    print("  scaler.step(optimizer)                          # skips if inf/nan")
    print("  scaler.update()                                 # adapt S for next step")
    print("\n  bf16 path: drop the scaler entirely (torch.amp.autocast(dtype=bf16)).")


def section_cosine_lr():
    banner("SECTION E: cosine LR + linear warmup (nanoGPT get_lr)")
    print("Linear scaling rule (Goyal et al. 2017, arXiv:1706.02677): when you\n"
          "multiply the batch size by K, scale the peak LR by K, and WARM UP\n"
          "linearly from 0 to avoid early-training instability. Then cosine-decay\n"
          "peak -> min_lr for a smooth landing (Chinchilla: decay_iters ~= max_iters).\n")
    peak = 1.0          # readable peak (real nanoGPT: 6e-4)
    min_lr = 0.1
    warmup = 10
    decay_iters = 50

    def get_lr(it):
        if it < warmup:
            return peak * (it + 1) / (warmup + 1)         # linear warmup
        if it > decay_iters:
            return min_lr                                   # hold at min past decay
        r = (it - warmup) / (decay_iters - warmup)
        coeff = 0.5 * (1.0 + math.cos(math.pi * r))        # 1.0 -> 0.0
        return min_lr + coeff * (peak - min_lr)

    print("| it | phase        |     lr |")
    print("|----|--------------|--------|")
    sample_its = [0, 2, 4, 6, 8, 10, 15, 25, 35, 45, 50, 55]
    for it in sample_its:
        if it < warmup:
            phase = "warmup (linear)"
        elif it > decay_iters:
            phase = "hold @ min_lr"
        else:
            phase = "cosine decay"
        print(f"| {it:>2} | {phase:<12} | {get_lr(it):.4f} |")
    print(f"\n  peak={peak}, min_lr={min_lr}, warmup={warmup}, decay_iters={decay_iters}")
    # sanity: last warmup step ~ peak*warmup/(warmup+1); cosine starts AT peak at
    # it=warmup; cosine ends at min_lr at it=decay_iters; holds at min_lr after.
    assert abs(get_lr(warmup - 1) - peak * warmup / (warmup + 1)) < 1e-9
    assert abs(get_lr(warmup) - peak) < 1e-9
    assert abs(get_lr(decay_iters) - min_lr) < 1e-9
    assert abs(get_lr(55) - min_lr) < 1e-9
    print("\n  [check] warmup ramps 0->~peak, cosine starts @peak ends @min_lr, holds after: OK")


def section_memory():
    banner("SECTION F: the 20-bytes/param memory breakdown (mixed-precision Adam)")
    print("Per parameter, DDP mixed-precision training stores:\n")
    rows = [
        ("fp16 parameters",   2, "the model weights used in the fp16 forward"),
        ("fp16 gradients",    2, "computed in the fp16 backward"),
        ("fp32 master params",4, "optimizer's master copy (Micikevicius 2017)"),
        ("fp32 grad copy",    4, "upcast fp16 grad for the optimizer"),
        ("fp32 Adam momentum",4, "first moment (beta1 running avg)"),
        ("fp32 Adam variance",4, "second moment (beta2 running avg)"),
    ]
    total = 0
    print("| component           | bytes/param | why                                   |")
    print("|---------------------|-------------|---------------------------------------|")
    for name, b, why in rows:
        total += b
        print(f"| {name:<19} | {b:>11} | {why:<37} |")
    print(f"| {'TOTAL':<19} | {total:>11} | {'~16N effective (20N raw)':<37} |")
    print()
    print("Concrete sizes (DDP = this is REPLICATED on every GPU):")
    print("| model        | params    | bytes/param | per-GPU (DDP) |")
    print("|--------------|-----------|-------------|---------------|")
    for name, n in [("tiny demo W", E_IN * E_OUT), ("GPT-2 small", 124_000_000),
                    ("LLaMA-3 8B", 8_000_000_000), ("GPT-3 175B", 175_000_000_000)]:
        gb = n * total / (1024 ** 3)
        print(f"| {name:<12} | {n:>9,} | {total:>11} | {gb:>11.2f} GB |")
    print()
    print("  [check] total = 2+2+4+4+4+4 = 20 bytes/param")
    assert total == 20
    print("  --> DDP replicates ALL 20N bytes on every GPU. That redundancy is")
    print("      exactly what ZeRO-1/2/3 eliminate by sharding these states. 🔗")
    print("      (🔗 QUANTIZATION attacks the 2-byte fp16 weight; ZeRO attacks the")
    print("       16-byte optimizer/grad/master redundancy. Orthogonal axes.)")


def section_gold_recap(W0, W1, X0, T0, X1, T1, lr_ref, g_avg_ref, W_after_ref):
    banner("SECTION G: worked 2-GPU DDP sim -- GOLD recap (pinned for ddp.html)")
    print("The canonical tiny run, all numbers recomputed here so the .html can\n"
          "gold-check against them.\n")
    # recompute from scratch to be self-contained
    g0 = local_grad(X0, W0, T0)
    g1 = local_grad(X1, W1, T1)
    [g_avg, _] = allreduce_avg([g0, g1])
    W_after = sgd_step(W0, g_avg, lr_ref)
    print(f"  init W[0,:]        = {fmt_vec(W0[0])}")
    print(f"  local grad g0[0,:] = {fmt_vec(g0[0])}")
    print(f"  local grad g1[0,:] = {fmt_vec(g1[0])}")
    print(f"  AllReduce avg[0,:] = {fmt_vec(g_avg[0])}")
    print(f"  W after step[0,:]  = {fmt_vec(W_after[0])}   (lr={lr_ref})")
    print()
    print(f"  PINNED GOLD (html recomputes & diffs these):")
    print(f"    avg_grad[0,0]      = {g_avg[0, 0].item():+.6f}")
    print(f"    avg_grad[1,2]      = {g_avg[1, 2].item():+.6f}")
    print(f"    W_after_step[0,0]  = {W_after[0, 0].item():+.6f}")
    print(f"    W_after_step[1,2]  = {W_after[1, 2].item():+.6f}")
    # cross-check against the values section B produced
    ok = (torch.allclose(g_avg, g_avg_ref, atol=1e-6)
          and torch.allclose(W_after, W_after_ref, atol=1e-6))
    print(f"\n  [check] recap == Section B values?  {ok}")
    assert ok


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main():
    print("ddp.py - reference impl (faithful single-process K=2 simulation).\n"
          "Numbers below feed DDP.md.  torch =", torch.__version__)
    print("\nNOTE: no torch.distributed / NCCL is used. Two replicas are held as\n"
          "separate tensors and AllReduce is an explicit average. The math is\n"
          "identical to real DDP; only the execution model is simplified.")

    W0, W1, X0, T0, X1, T1 = make_data()

    g0, g1, g_avg = section_algorithm(W0, W1, X0, T0, X1, T1)
    lr_ref, g_avg_ref, W_after_ref = section_why_sync_keeps_identical(
        W0, W1, X0, T0, X1, T1, g0, g1, g_avg)
    section_grad_accumulation(W0)
    section_amp_and_scaler()
    section_cosine_lr()
    section_memory()
    section_gold_recap(W0, W1, X0, T0, X1, T1, lr_ref, g_avg_ref, W_after_ref)

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
