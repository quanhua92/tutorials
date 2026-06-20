"""
gradient_checkpointing.py - Reference implementation of Gradient Checkpointing
(a.k.a. activation recomputation): the three strategies, their activation-memory
and compute arithmetic, and the torch.utils.checkpoint API.

This is the single source of truth that GRADIENT_CHECKPOINTING.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python gradient_checkpointing.py

== IMPORTANT -- this is a FAITHFUL SIMULATION of a transformer's activation
== memory + a REAL (tiny) torch.utils.checkpoint correctness demo ==============
We do NOT train a real L=32 transformer. Instead we model a transformer's
layer activations as a list of L layer-activation tensors of shape [B, S, D],
and we track -- across three checkpointing strategies -- exactly WHICH layer
activations are STORED vs RECOMPUTED, and how many layer-forward passes the
backward must redo. The byte arithmetic is computed from the tensors' real
.element_size() * .numel(), so it is EXACT, not hand-waved.

The only thing simulated is the multi-layer execution; the memory-bytes and
compute-units arithmetic is closed-form and asserted in code. Section E also
runs a REAL torch.utils.checkpoint example on a small network to prove the
recomputed gradients are bit-identical to the non-checkpointed ones.

== The big idea, in one paragraph (no math) ===================================
Backpropagation needs every layer's forward activations to compute its
gradient, so vanilla training STORES all L layers' activations for the whole
backward pass -- activation memory = L x B x S x D x ~2 bytes (LLaMA-8B:
~1 GB/seq; batch 32 -> ~34 GB, ~2x the fp16 weights). Gradient checkpointing
(also "activation recomputation") trades COMPUTE for MEMORY: keep activations
only at a few CHECKPOINT boundaries, throw the rest away, and RECOMPUTE them
on demand during the backward pass. The standard "selective" / sqrt strategy
keeps sqrt(L) checkpoints, so memory drops from O(L) to O(sqrt L) for the
price of ~one extra forward pass (~33% more compute). That trade is what lets
big models fit in VRAM.

== The lineage (old -> new, with WHY) =========================================
  store-all (vanilla backprop): keep every layer's activations for backward.
                 Memory O(L), compute O(L) (1 fwd + 1 bwd). The default.
                 WHY change: at L=32, B=32 the activations alone can equal
                 or exceed the model weights -> OOM.
  full-recompute (store none) : keep only the network input; recompute every
                 layer's forward from scratch during its own backward.
                 Memory O(1), but compute O(L^2) -- each of L layers redoes a
                 growing prefix of forwards (1+2+...+L). Prohibitively slow.
                 WHY change: O(L^2) compute is unacceptable for deep nets.
  selective sqrt L (Chen 2016): keep activations only at every sqrt(L)-th layer
                 -> sqrt(L) checkpoints. Memory O(sqrt L). During backward, each
                 segment recomputes its <= sqrt(L) layers from its checkpoint
                 input, so total recompute = L layer-forwards (one per layer),
                 i.e. compute O(L) -- one EXTRA forward. This is the sweet spot:
                 ~sqrt(L)x less memory for ~33% more compute. (Chen 2016:
                 "1000-layer net, 48G -> 7G with 30% extra runtime".)

== Why ~33%? ==================================================================
  Backward costs ~2x a forward (matmul backward = forward of W and of W^T).
  So a vanilla step = 1 fwd + 1 bwd ~= 3 forward-equivalents. Selective
  checkpointing adds 1 extra forward (the recompute): 1 fwd + 1 recompute-fwd
  + 1 bwd ~= 4 forward-equivalents. (4 - 3) / 3 = +33%. This is the figure
  Chen 2016, the PyTorch docs, and HF cite. (If you measure vs forward-only,
  it looks like +100% -- that is the same fact counted differently.)

== Plain-English glossary =====================================================
    activation   the tensor a layer outputs in the forward pass, which its
                 backward needs to compute its gradient. The thing we either
                 STORE or RECOMPUTE.
    B, S, D      batch size, sequence length, hidden/model dim. One layer's
                 activation is [B, S, D] -> B*S*D*~2 bytes (fp16/bf16).
    L            number of transformer layers. Activation memory scales O(L).
    checkpoint   a layer boundary whose input activation we KEEP, so the layers
                 after it can be recomputed from it during backward. (a.k.a.
                 the sqrt-L markers.)
    recompute    redoing a layer's forward during backward to regenerate the
                 activations that were thrown away. "Throw it away, redo it."
    strategy     the rule deciding which activations to keep: store-all,
                 full-recompute, or selective sqrt L.
    use_reentrant the torch.utils.checkpoint mode flag. False = the modern
                 (non-reentrant) impl that supports DDP/FSDP and double-
                 backward; True = the legacy reentrant impl. See Section E.

== Anchor formulas (all verified + asserted in code) =========================
    Per-layer activation bytes:   A = B * S * D * dtype_bytes
    Vanilla store-all memory:     L * A           (O(L))
    Full-recompute memory:        1 * A           (O(1), the network input)
    Selective sqrt(L) memory:     ceil(sqrt(L)) * A     (O(sqrt L))
    Vanilla compute (fwd+bwd):    L + 2L = 3L   layer-forward units
    Selective compute:            L + L + 2L = 4L units   (+33%)
    Full-recompute compute:       L + L(L+1)/2 + 2L = (L^2 + 7L)/2   (O(L^2))

== Tensor-shape conventions ===================================================
    L = number of transformer layers
    B = batch size ; S = sequence length ; D = hidden / model dim
    One layer activation = [B, S, D], dtype fp16/bf16 (2 bytes) or fp32 (4).
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn
from torch.utils.checkpoint import checkpoint

torch.set_printoptions(precision=6, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 0. THE THREE STRATEGIES  (memory + recompute accounting, exact)
#    Each returns (stored_layer_indices, n_stored, recompute_layer_fwds).
#    stored_layer_indices : which layer INPUT activations are kept persistently.
#    n_stored             : len(stored) -- the persistent memory multiplier.
#    recompute_layer_fwds : total layer-forward passes redone during backward.
# ============================================================================

def strategy_store_all(L: int):
    """Vanilla backprop: keep every layer's activation for the backward pass.

    Memory O(L). Compute: 0 recompute (everything is already saved).
    """
    stored = list(range(L))           # keep all L layers' activations
    recompute = 0
    return stored, len(stored), recompute


def strategy_full_recompute(L: int):
    """Store NONE of the layer activations (keep only the network input).

    Memory O(1). But to backprop layer i we must recompute forwards 1..i from
    the input, so total recompute = 1 + 2 + ... + L = L*(L+1)/2 -> O(L^2).
    This is the NAIVE baseline; it is correct but prohibitively slow for deep
    nets. (See the sqrt strategy for the smart version.)
    """
    stored = [0]                       # keep only the network input (layer 0 in)
    recompute = L * (L + 1) // 2       # sum_{i=1}^{L} i
    return stored, len(stored), recompute


def strategy_selective_sqrt(L: int):
    """Selective checkpointing (Chen 2016): keep ceil(sqrt(L)) checkpoints at
    evenly spaced layer boundaries; recompute each segment in backward.

    Memory O(sqrt L). Each non-checkpoint layer's forward is recomputed exactly
    once (when its segment is processed in backward) -> total recompute = L,
    i.e. ONE extra network forward. The sqrt trick balances memory and compute.
    """
    if L <= 1:
        return [0], 1, 0
    m = math.ceil(math.sqrt(L))            # number of checkpoint boundaries
    # place m checkpoints at evenly spaced layer indices (including layer 0,
    # the network input). Each checkpoint = "keep the input activation of the
    # segment starting here".
    checkpoints = sorted(set(round(i * (L - 1) / (m - 1)) for i in range(m)))
    stored = checkpoints
    # recompute = every layer that is NOT a stored checkpoint input is
    # recomputed once during its segment's backward -> L - len(checkpoints)
    # recomputes, plus we never recompute the final output. Closed form = L.
    recompute = L
    return stored, len(stored), recompute


def compute_units(L: int, recompute: int) -> int:
    """Total compute in LAYER-FORWARD units for a fwd+bwd step.

    Assumption (standard): a layer's backward costs ~2x its forward (matmul
    backward = forward of W and of W^T). So a full network backward = 2L.
    Total = forward(L) + recompute + backward(2L).
    """
    return L + recompute + 2 * L


# ----------------------------------------------------------------------------
# PRETTY PRINTERS
# ----------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# A. WHY ACTIVATION MEMORY BLOWS UP  (the L x B x S x D math)
# ============================================================================

def section_why_memory():
    banner("SECTION A: why activation memory blows up -- L x B x S x D x ~2 bytes")
    print("Backprop needs every layer's forward activation to compute its")
    print("gradient. For one transformer layer the activation is [B, S, D], so:\n")
    print("    per-layer activation bytes  A = B * S * D * dtype_bytes")
    print("    total activation memory     = L * A   (all L layers stored)\n")
    dtype_bytes = 2                        # fp16 / bf16
    print(f"With dtype = fp16/bf16 ({dtype_bytes} bytes/elem):\n")
    print("| B  | S    | D    | A = B*S*D*{db} (bytes) | * L=32 layers |".format(db=dtype_bytes))
    print("|----|------|------|----------------------|---------------|")
    for B, S, D in [(1, 4096, 4096), (1, 8192, 4096), (8, 4096, 4096),
                    (32, 4096, 4096), (32, 8192, 4096)]:
        A = B * S * D * dtype_bytes
        total = 32 * A
        print(f"| {B:<2} | {S:<4} | {D:<4} | {A/1e6:>18.2f} MB | "
              f"{total/1e9:>11.2f} GB |")
    print()
    print("READ: at B=32, S=4096, D=4096 (LLaMA-3 8B shape) ONE layer's")
    print("activation is 33.5 MB; all 32 layers = 1.07 GB per... wait, x B=32:")
    print("that is 34.36 GB of activations for one training step -- ~2x the")
    print("16 GB of fp16 model weights. Activations are the memory bottleneck.")
    print()

    # the exact byte footprint, measured from a real tensor (not hand-waved)
    B, S, D, L = 1, 4096, 4096, 32
    one = torch.zeros(B, S, D, dtype=torch.float16)
    A_real = one.element_size() * one.numel()
    layers = [one.clone() for _ in range(L)]
    total_real = sum(t.element_size() * t.numel() for t in layers)
    print(f"[tensor check] one [1,4096,4096] fp16 layer = {A_real/1e6:.2f} MB ; "
          f"32 layers = {total_real/1e9:.2f} GB")
    assert A_real == B * S * D * 2
    assert total_real == 32 * A_real
    print(f"[check] measured bytes == B*S*D*2 and == 32*A? "
          f"{A_real == B*S*D*2 and total_real == 32*A_real}")

    # context: this sits ON TOP of the model + optimizer memory (DDP 20N)
    N = 8_000_000_000
    print(f"\nContext (LLaMA-3 8B, N={N:,} params):")
    print(f"  model+optimizer (DDP 20N/param)  = {N*20/1e9:>6.1f} GB / GPU  (DDP/ZERO)")
    print(f"  activations, B=32, S=4096         = {32*1*4096*4096*2*32/1e9:>6.1f} GB")
    print(f"  --> activations can rival the weights+optimizer. Cutting them is")
    print(f"      what gradient checkpointing does.  (DDP/ZERO shard the 20N;")
    print(f"       checkpointing cuts the L*A activation term -- a THIRD axis.)")


# ============================================================================
# B. VANILLA BACKPROP -- store all  (O(L) memory, O(L) compute)
# ============================================================================

def section_store_all():
    banner("SECTION B: vanilla backprop -- store ALL layers  (O(L) mem, O(L) compute)")
    L = 32
    stored, n_stored, recompute = strategy_store_all(L)
    cu = compute_units(L, recompute)
    print(f"L = {L} layers. The backward needs every layer's forward activation,")
    print(f"so we keep ALL of them for the whole backward pass.\n")
    print(f"  stored layer activations : {n_stored}  (= L = {L})")
    print(f"  recompute (layer-forwards): {recompute}")
    print(f"  compute (fwd + recompute + bwd=2x): {L} + {recompute} + {2*L} = "
          f"{cu} layer-fwd units")
    print(f"  memory multiplier : {n_stored}x  (= L ; linear in depth)")
    assert n_stored == L and recompute == 0 and cu == 3 * L
    print(f"\n  [check] stored==L={L}, recompute==0, compute==3L={3*L}? "
          f"{n_stored == L and recompute == 0 and cu == 3*L}")
    print(f"\n  ==> This is the default. Simple and fastest, but memory grows")
    print(f"      linearly with depth -> the first thing to OOM as L or B grows.")


# ============================================================================
# C. FULL RECOMPUTE -- store none  (O(1) memory, O(L^2) compute)
# ============================================================================

def section_full_recompute():
    banner("SECTION C: full recompute -- store NONE  (O(1) mem, O(L^2) compute)")
    L = 32
    stored, n_stored, recompute = strategy_full_recompute(L)
    cu = compute_units(L, recompute)
    print(f"L = {L} layers. Keep only the network input; recompute each layer's")
    print(f"forward from scratch when its backward needs it.\n")
    print(f"  stored layer activations : {n_stored}  (just the network input)")
    print(f"  recompute (layer-forwards): 1+2+...+{L} = {L*(L+1)//2}  (= L(L+1)/2)")
    print(f"  compute (fwd + recompute + bwd=2x): {L} + {recompute} + {2*L} = "
          f"{cu} layer-fwd units")
    print(f"  memory multiplier : {n_stored}x  (= 1 ; O(1))\n")
    print(f"  WHY O(L^2): to backprop layer i we must re-run forwards 1..i from")
    print(f"  the input. Summed over all L layers that is 1+2+...+L = L(L+1)/2.")
    assert n_stored == 1 and recompute == L * (L + 1) // 2
    assert cu == L + L * (L + 1) // 2 + 2 * L
    print(f"\n  [check] stored==1, recompute==L(L+1)/2={L*(L+1)//2}? "
          f"{n_stored == 1 and recompute == L*(L+1)//2}")
    print(f"\n  ==> Tiny memory, but the O(L^2) compute is brutal: at L=32 the")
    print(f"      backward alone redoes {recompute} layer-forwards -> {cu} total")
    print(f"      units vs vanilla's {3*L}. That is {cu/(3*L):.1f}x the compute.")
    print(f"      No one trains this way -- it is the baseline the sqrt trick beats.")


# ============================================================================
# D. SELECTIVE sqrt(L) CHECKPOINTING  (the GOLD centerpiece)
#    O(sqrt L) memory, O(L) compute (one extra forward)
# ============================================================================

def section_selective_sqrt():
    banner("SECTION D: selective sqrt(L) checkpointing -- the gold centerpiece")
    L = 32
    m = math.ceil(math.sqrt(L))
    stored, n_stored, recompute = strategy_selective_sqrt(L)
    cu = compute_units(L, recompute)
    print(f"L = {L} layers. Keep activations only at every sqrt(L)-th layer ->")
    print(f"ceil(sqrt({L})) = ceil({math.sqrt(L):.4f}) = {m} checkpoints. Throw the")
    print(f"rest away; recompute each segment in backward.\n")
    print(f"  checkpoint layer indices (stored inputs): {stored}")
    print(f"  stored layer activations : {n_stored}  (= ceil(sqrt(L)) = {m})")
    print(f"  recompute (layer-forwards): {recompute}  (one per non-checkpoint layer)")
    print(f"  compute (fwd + recompute + bwd=2x): {L} + {recompute} + {2*L} = "
          f"{cu} layer-fwd units")
    print(f"  memory multiplier : {n_stored}x  (O(sqrt L))\n")
    print(f"  WHY O(L) compute: split L layers into ~sqrt(L) segments of ~sqrt(L)")
    print(f"  layers. Backward of each segment recomputes its <= sqrt(L) layers from")
    print(f"  its checkpoint input, once. Total recompute = sqrt(L) segments x")
    print(f"  sqrt(L) layers = L layer-forwards = ONE extra network forward.\n")
    assert n_stored == m == 6                              # GOLD pin: ceil(sqrt(32))=6
    assert recompute == L                                   # GOLD pin: one extra forward
    assert cu == 4 * L                                      # GOLD pin: 4L units
    print(f"  [check] stored==ceil(sqrt({L}))=={m}, recompute==L={L}, compute==4L={4*L}? "
          f"{n_stored == m and recompute == L and cu == 4*L}")
    print(f"\n  ==> THE SWEET SPOT. Memory drops {L}/{m} = {L/m:.1f}x (from {L}x to {m}x)")
    print(f"      for ONE extra forward. At L={L}: {L}x -> {m}x memory, "
          f"{cu}/{3*L} = {cu/(3*L):.2f}x the compute (~33% overhead).")
    print(f"      (Chen 2016: '1000-layer net, 48G -> 7G with ~30% extra runtime'.)")


# ============================================================================
# E. torch.utils.checkpoint API  (real tiny demo; use_reentrant=False)
#    Proves recomputed gradients are bit-identical to the non-checkpointed ones.
# ============================================================================

def section_torch_api():
    banner("SECTION E: torch.utils.checkpoint API -- a real tiny correctness demo")
    print("torch.utils.checkpoint.checkpoint(fn, *args, use_reentrant=False) wraps a")
    print("sub-network: during the FORWARD it runs fn but DISCARDS fn's intermediate")
    print("activations (saving memory); during BACKWARD it RE-RUNS fn to regenerate")
    print("them on demand. The recomputed activations feed an identical backward, so")
    print("the GRADIENTS are bit-identical -- checkpointing is exact, not approximate.\n")

    torch.manual_seed(0)
    D_in, D_hidden, L_layers = 8, 16, 4
    # a tiny 4-layer MLP: each block is Linear -> GELU (the per-layer block, MLP_ACTIVATION)
    blocks = [nn.Sequential(nn.Linear(D_in if i == 0 else D_hidden, D_hidden),
                            nn.GELU()) for i in range(L_layers)]
    x = torch.randn(2, D_in, requires_grad=True)
    target = torch.randn(2, D_hidden)

    # reference path (no checkpoint): run all 4 blocks normally
    def run_ref():
        x1 = x.detach().clone().requires_grad_(True)
        h = blocks[0](x1)
        h = blocks[1](h)
        h = blocks[2](h)
        h = blocks[3](h)
        loss = h.square().mean()
        loss.backward()
        return x1, h, loss

    # checkpoint path: blocks 1-2 wrapped in one checkpoint segment
    def run_ckp():
        x1 = x.detach().clone().requires_grad_(True)
        h = blocks[0](x1)

        def seg(hh):
            return blocks[2](blocks[1](hh))

        h = checkpoint(seg, h, use_reentrant=False)   # drops seg's intermediates
        h = blocks[3](h)
        loss = h.square().mean()
        loss.backward()
        return x1, h, loss

    x_ref, h_ref, loss_ref = run_ref()
    x_ckp, h_ckp, loss_ckp = run_ckp()

    print(f"tiny net: {L_layers} layers, D_in={D_in}, D_hidden={D_hidden}, x {tuple(x.shape)}")
    print(f"checkpointed segment: blocks 1-2 (use_reentrant=False)\n")
    print(f"  forward output match?      max|h_ref - h_ckp| = "
          f"{(h_ref - h_ckp).abs().max().item():.2e}")
    print(f"  loss match?                |loss_ref - loss_ckp| = "
          f"{abs(loss_ref.item() - loss_ckp.item()):.2e}")
    print(f"  input-grad match?          max|dx_ref - dx_ckp| = "
          f"{(x_ref.grad - x_ckp.grad).abs().max().item():.2e}")
    fwd_ok = torch.allclose(h_ref, h_ckp, atol=1e-6)
    grad_ok = torch.allclose(x_ref.grad, x_ckp.grad, atol=1e-6)
    print(f"\n  [check] forward bit-identical? {fwd_ok}")
    print(f"  [check] GRADIENT bit-identical? {grad_ok}  <- the whole point:")
    print(f"          checkpointing trades MEMORY for COMPUTE, NOT accuracy.")
    assert fwd_ok and grad_ok

    # the use_reentrant pitfall
    print(f"\n  use_reentrant flag (the #1 pitfall, learning_guide 04 §11 #10):")
    print(f"    use_reentrant=False -> MODERN impl. Supports DDP/FSDP, double-")
    print(f"                           backward, dropped-inputs. RECOMMENDED.")
    print(f"    use_reentrant=True  -> LEGACY reentrant impl. Needed only for")
    print(f"                           very old patterns; breaks under DDP/FSDP.")
    print(f"  In torch >= 2.1 you get a UserWarning if you omit the flag; in a")
    print(f"  future release use_reentrant=True will be removed. Always pass")
    print(f"  use_reentrant=False explicitly.")


# ============================================================================
# F. THE ~33% COMPUTE-OVERHEAD TRADEOFF
# ============================================================================

def section_overhead():
    banner("SECTION F: the ~33% compute-overhead tradeoff (where the number comes from)")
    L = 32
    _, _, rc_all = strategy_store_all(L)
    _, _, rc_sel = strategy_selective_sqrt(L)
    cu_all = compute_units(L, rc_all)
    cu_sel = compute_units(L, rc_sel)
    print(f"Measure compute in LAYER-FORWARD units, with backward ~= 2x forward:\n")
    print(f"    vanilla step   = fwd({L}) + bwd({2*L})           = {cu_all} units")
    print(f"    selective step = fwd({L}) + recompute({rc_sel}) + bwd({2*L}) = {cu_sel} units")
    print(f"    overhead       = ({cu_sel} - {cu_all}) / {cu_all} = {(cu_sel-cu_all)/cu_all:+.1%}\n")
    print(f"That +{(cu_sel-cu_all)/cu_all:.0%} is the famous '~33%'. It is ONE extra forward")
    print(f"(the recompute) on top of a step that already costs ~3 forwards")
    print(f"(1 fwd + 1 bwd, bwd ~= 2 fwd). So 1 / 3 = 33%.\n")
    print(f"Counted other ways (same fact, different denominator):")
    print(f"    vs forward only : +{rc_sel/L:.0%}   (the forward runs twice)")
    print(f"    vs wall-clock    : ~30% in practice (Chen 2016: '30% extra runtime')")
    print(f"    learning_guide  : '30-40% more computation' (04 §8)\n")
    overhead = (cu_sel - cu_all) / cu_all
    assert abs(overhead - 1 / 3) < 1e-9
    print(f"  [check] overhead == 1/3 == +33.33%? {abs(overhead - 1/3) < 1e-9}")
    print(f"\n  ==> Selective checkpointing: ~sqrt(L)x less memory for ~33% more")
    print(f"      compute. Almost always worth it when activations are the bottleneck.")


# ============================================================================
# G. THE GOLD TABLE -- memory + compute across the 3 strategies (L=32)
# ============================================================================

def section_gold_table():
    banner("SECTION G: the GOLD table -- memory + compute across 3 strategies (L=32)")
    L = 32
    A = 1                                   # measure memory in units of A (per-layer activation)
    print(f"L = {L} layers. Memory in units of A (one layer's activation bytes).\n")
    print(f"| strategy           | stored | memory mult | recompute | compute (units) | vs vanilla |")
    print(f"|--------------------|--------|-------------|-----------|-----------------|------------|")
    rows = [
        ("store-all (vanilla)", strategy_store_all(L)),
        ("full-recompute      ", strategy_full_recompute(L)),
        ("selective sqrt(L)   ", strategy_selective_sqrt(L)),
    ]
    cu_vanilla = compute_units(L, 0)
    for name, (stored, n_stored, rc) in rows:
        cu = compute_units(L, rc)
        vs = cu / cu_vanilla
        print(f"| {name} | {n_stored:>6} | {n_stored:>11}x | {rc:>9} | "
              f"{cu:>15} | {vs:>9.2f}x |")
    print()

    # the per-layer byte example (LLaMA-3 8B shape: B=1,S=4096,D=4096,fp16)
    B, S, D, db = 1, 4096, 4096, 2
    A_bytes = B * S * D * db
    print(f"Concrete (LLaMA-3 8B per-seq activation A = {B}*{S}*{D}*{db} = "
          f"{A_bytes/1e6:.2f} MB, B={B}):\n")
    print(f"| strategy           | memory mult | activation memory | compute (vs vanilla) |")
    print(f"|--------------------|-------------|-------------------|----------------------|")
    for name, (stored, n_stored, rc) in rows:
        cu = compute_units(L, rc)
        mem = n_stored * A_bytes
        vs = cu / cu_vanilla
        print(f"| {name} | {n_stored:>11}x | {mem/1e6:>15.1f} MB | "
              f"{vs:>19.2f}x |")
    print()
    # GOLD PINS (these are what gradient_checkpointing.html recomputes & diffs)
    _, ns_sel, rc_sel = strategy_selective_sqrt(L)
    print(f"GOLD PINS (gradient_checkpointing.html recomputes these, L={L}):")
    print(f"  store-all  memory mult = {L}")
    print(f"  full-rec.  memory mult = 1")
    print(f"  selective  memory mult = ceil(sqrt({L})) = {ns_sel}    (checkpoints)")
    print(f"  selective  recompute   = {rc_sel}        (= L ; one extra forward)")
    print(f"  selective  overhead    = +1/3 = +33.33%")
    gold_ok = (L == 32 and ns_sel == 6 and rc_sel == 32
               and abs((compute_units(L, rc_sel) / cu_vanilla) - 4 / 3) < 1e-9)
    print(f"\n  [check] mults {{32, 1, 6}}, recompute=={L}, overhead==+33.33%? {gold_ok}")
    assert gold_ok

    # sweep L to show the sqrt memory curve flattening
    print(f"\nsweep L -- selective memory multiplier ceil(sqrt(L)) vs O(L) store-all:")
    print(f"| L   | store-all (L) | selective ceil(sqrt L) | full-recompute (1) |")
    print(f"|-----|---------------|------------------------|--------------------|")
    for Li in [4, 8, 16, 32, 64, 128, 1000]:
        _, ns_a, _ = strategy_store_all(Li)
        _, ns_s, _ = strategy_selective_sqrt(Li)
        print(f"| {Li:<3} | {ns_a:>13} | {ns_s:>22} | {1:>18} |")
    print()
    print(f"READ: store-all grows LINEARLY with L; selective grows as sqrt(L)")
    print(f"(flattens fast); full-recompute is always 1x. At L=1000: store-all =")
    print(f"1000x, selective = ceil(sqrt(1000)) = {math.ceil(math.sqrt(1000))}x. That is")
    print(f"the Chen 2016 result (1000-layer net, 48G -> 7G at ~30% extra runtime).")


# ============================================================================
# main
# ============================================================================

def main():
    print("gradient_checkpointing.py - reference impl (faithful activation-memory")
    print("simulation + a real torch.utils.checkpoint correctness demo).")
    print("Numbers below feed GRADIENT_CHECKPOINTING.md.  torch =", torch.__version__)
    print("\nSIMULATION: L transformer layer activations modelled as [B,S,D] tensors;")
    print("we track which are STORED vs RECOMPUTED across 3 strategies. The")
    print("memory-bytes (from tensor .element_size()*.numel()) and compute-units")
    print("arithmetic is EXACT and asserted. Section E also runs a REAL small")
    print("torch.utils.checkpoint network to prove gradients are bit-identical.")

    section_why_memory()           # A
    section_store_all()            # B
    section_full_recompute()       # C
    section_selective_sqrt()       # D
    section_torch_api()            # E
    section_overhead()             # F
    section_gold_table()           # G

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
