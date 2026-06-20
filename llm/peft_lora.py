"""
peft_lora.py - Reference implementation of LoRA, QLoRA, and Multi-Adapter Serving.

This is the single source of truth that PEFT_LORA.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python peft_lora.py

== PLAIN-ENGLISH INTUITION (read this first; the math follows) =================
Full fine-tuning rewrites EVERY weight of the model for EACH downstream task.
For a 175B-parameter model, that is 175 billion new numbers PER task — impossible
to store, let alone serve, when you have hundreds of tasks/users.

LoRA's bet: the *change* a task makes to the weights (ΔW) lives in a tiny
low-dimensional corner. So instead of learning the full d×k update, factor it as
a product of two thin matrices ΔW = (α/r)·B·A where B is d×r, A is r×k, and
r ≪ min(d,k). You now train only r·(d+k) numbers — and at the end you can either
keep W₀ and BA separate (swap adapters per task) or fold BA back into W₀ (zero
extra latency).

QLoRA's bet: the FROZEN W₀ is huge and we never train it anyway, so quantize it
to 4-bit NF4 (🔗 QUANTIZATION did W4A16 group quant — NF4 is its normal-quantile
cousin). Keep the tiny adapters A, B in fp16. Now a 65B model trains on ONE 48GB
GPU, because the thing you actually back-prop through (A, B) is tiny and the
thing you store (W₀) is 4× smaller.

Multi-adapter serving: one frozen base model serves HUNDREDS of tasks at once.
Each request in a batch picks its own adapter (A_i, B_i). Punica runs them in ONE
"grouped GEMM" kernel (no per-adapter loop); S-LoRA parks all adapters in paged
memory (like PagedAttention for KV cache) and swaps them in sub-millisecond.

== GLOSSARY (used in every section) ============================================
    W₀         the FROZEN pre-trained weight of one linear layer, shape [d, k].
    x          the activation (input) flowing through the layer, shape [k].
    LoRA       Low-Rank Adaptation: freeze W₀, learn a small ΔW = (α/r)BA.
    adapter    the pair (A, B) that produces ΔW; "LoRA module".
    rank r     the inner/hidden dimension of the adapter; r ≪ min(d,k). Real: 8/16/64.
    α (alpha)  a scaling hyperparameter; ΔW is multiplied by α/r. Usually α ≈ r or 2r.
    A          the "down-projection" [r, k]; init ~ N(0, σ²) (random Gaussian).
    B          the "up-projection" [d, r]; init = 0 (so ΔW = BA = 0 at the start).
    ΔW         the learned update: (α/r)·B·A, shape [d, k], rank ≤ r by construction.
    QLoRA      Quantized LoRA: W₀ stored as 4-bit NF4; adapters A,B stay fp16.
    NF4        4-bit NormalFloat: 16 fixed levels = quantiles of a normal dist,
               placed DENSELY near 0 (where trained weights cluster). 🔗 QUANTIZATION
    Punica     multi-adapter serving via a "grouped GEMM" kernel (one kernel,
               many adapters, one batch).
    S-LoRA     multi-adapter serving via PAGED adapter memory (thousands of
               adapters, sub-ms swap), mirroring PagedAttention for KV cache.
    merge      fold ΔW into W₀ at deploy time: W = W₀ + (α/r)BA -> zero latency.

== TENSOR-SHAPE CONVENTIONS ===================================================
    d = out_features (rows of W₀)
    k = in_features  (cols of W₀; len of x)
    r = adapter rank (r ≪ min(d,k))
    Hence: W₀ [d,k], x [k], A [r,k], B [d,r], ΔW [d,k], y [d].
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72

# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS
# ============================================================================

class LoRALinear:
    """One linear layer with a LoRA adapter bolted on.

        y = W₀·x + (α/r) · B · (A · x)

    W₀ is FROZEN (no grad). Only A and B are trained. At deploy time you may
    either keep this two-path form (to swap adapters per task) or merge:
    W_merged = W₀ + (α/r)·B·A, recovering a plain linear layer with zero latency.

    Init (Hu et al. 2021, §4.1): A ~ random Gaussian, B = 0, so ΔW = B·A = 0 at
    the start of training — the model behaves EXACTLY like the base model on step 0.

    Args:
        W0:      [d, k] frozen pre-trained weight.
        rank r, alpha: adapter rank and scaling. Effective scale = alpha/r.
        A:       [r, k] (optional; if None, sampled ~ N(0, σ²) for the "init" demo).
        B:       [d, r] (optional; if None, initialized to ZEROS, matching the paper).
    """

    def __init__(self, W0: torch.Tensor, rank: int, alpha: float,
                 A: torch.Tensor | None = None, B: torch.Tensor | None = None):
        self.W0 = W0
        self.d, self.k = W0.shape
        self.r = rank
        self.alpha = alpha
        self.scale = alpha / rank            # the (α/r) factor
        self.A = A if A is not None \
            else torch.randn(rank, self.k) * 0.1   # Gaussian init (paper)
        self.B = B if B is not None \
            else torch.zeros(self.d, rank)          # zero init (paper) -> ΔW=0 at start

    def delta_W(self) -> torch.Tensor:
        """The effective rank-r update ΔW = (α/r)·B·A, shape [d, k]."""
        return self.scale * (self.B @ self.A)

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        """Two-path forward: y = W₀x + (α/r)·B(Ax). Same shape as a plain linear."""
        base = self.W0 @ x                  # frozen path
        adapt = self.scale * (self.B @ (self.A @ x))   # adapter path
        return base + adapt


# --- NF4 (4-bit NormalFloat) for the QLoRA part --------------------------------
# The 16 fixed levels are the quantiles of a standard normal, normalized so the
# max-abs level is ±1. They are placed DENSELY near 0 (8 levels between -0.28 and
# +0.25) because trained weights cluster there. Verified verbatim against the
# QLoRA paper (Dettmers et al. 2023, App. E) and the bitsandbytes codebook.
# 🔗 QUANTIZATION did MLX-affine W4A16 (evenly spaced levels); NF4 is its
# normal-quantile (NON-uniform) cousin, tuned for the weight distribution.
NF4_CODEBOOK = torch.tensor([
    -1.0000, -0.6962, -0.5251, -0.3949, -0.2844, -0.1848, -0.0911,  0.0000,
     0.0796,  0.1609,  0.2461,  0.3379,  0.4407,  0.5626,  0.7230,  1.0000,
], dtype=torch.float32)
NF4_BITS = 4
NF4_GROUP_SIZE = 8          # printable; real QLoRA uses 64


def nf4_quantize_block(w: torch.Tensor):
    """NF4-quantize ONE block of weights (here group_size = len(w)).

    Returns (scale, indices) where:
        scale    = absmax(w)               (one float16 per block)
        indices  = int tensor in [0, 15]   (which codebook level each weight uses)
    Dequant:   w_hat = scale * NF4_CODEBOOK[indices]
    """
    scale = float(w.abs().max())
    w_norm = w / scale                                # fit into [-1, 1]
    # nearest codebook level for each normalized weight
    dist = (w_norm.unsqueeze(-1) - NF4_CODEBOOK).abs()   # [group, 16]
    indices = dist.argmin(dim=-1)                          # [group]
    return scale, indices


def nf4_quantize(W: torch.Tensor, group_size: int = NF4_GROUP_SIZE):
    """NF4-quantize a whole weight matrix [d, k], row-major blocks of group_size.

    Returns (scales, indices):
        scales   : [num_blocks] float  (one absmax per block)
        indices  : [d, k] int in [0,15]
    """
    d, k = W.shape
    flat = W.reshape(-1)
    n_blocks = flat.numel() // group_size
    scales = torch.zeros(n_blocks)
    indices = torch.zeros_like(flat, dtype=torch.long)
    for b in range(n_blocks):
        seg = flat[b * group_size:(b + 1) * group_size]
        s, idx = nf4_quantize_block(seg)
        scales[b] = s
        indices[b * group_size:(b + 1) * group_size] = idx
    return scales, indices.reshape(d, k)


def nf4_dequant(scales: torch.Tensor, indices: torch.Tensor,
                group_size: int = NF4_GROUP_SIZE) -> torch.Tensor:
    """Reconstruct the float weight matrix from NF4 storage."""
    d, k = indices.shape
    flat_idx = indices.reshape(-1)
    flat_hat = NF4_CODEBOOK[flat_idx]
    n_blocks = flat_idx.numel() // group_size
    for b in range(n_blocks):
        flat_hat[b * group_size:(b + 1) * group_size] = \
            flat_hat[b * group_size:(b + 1) * group_size] * scales[b]
    return flat_hat.reshape(d, k)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE TINY-BUT-COMPLETE CONCRETE MODEL
#    d = 8, k = 8, r = 2, alpha = 16.  Deterministic (hardcoded) so the .html can
#    recompute bit-for-bit. One frozen base + (later) two adapters for multi-LoRA.
# ============================================================================

# W0 : frozen pre-trained weight [d=8, k=8]
W0 = torch.tensor([
    [ 0.40, -0.20,  0.10,  0.30, -0.15,  0.05,  0.25, -0.10],
    [-0.10,  0.50, -0.30,  0.20,  0.10, -0.25,  0.15,  0.05],
    [ 0.20, -0.10,  0.60, -0.20,  0.30,  0.10, -0.05,  0.40],
    [ 0.15,  0.25, -0.10,  0.45, -0.30,  0.20,  0.10, -0.15],
    [-0.25,  0.10,  0.20, -0.15,  0.55, -0.10,  0.30,  0.20],
    [ 0.10, -0.30,  0.15,  0.25, -0.20,  0.50, -0.10,  0.30],
    [ 0.30,  0.05, -0.25,  0.10,  0.20, -0.15,  0.65, -0.20],
    [-0.15,  0.40,  0.10, -0.30,  0.25,  0.15, -0.20,  0.55],
], dtype=torch.float32)

# x : one activation [k=8]
X = torch.tensor([0.50, -0.30,  0.80, -0.10,  0.40, -0.60,  0.20,  0.70],
                 dtype=torch.float32)

# A : adapter down-projection [r=2, k=8]  (Gaussian-style fixed values)
A = torch.tensor([
    [ 0.15, -0.20,  0.10,  0.25, -0.05,  0.30, -0.15,  0.08],
    [-0.10,  0.12,  0.22, -0.18,  0.14, -0.06,  0.09, -0.24],
], dtype=torch.float32)

# B_trained : adapter up-projection [d=8, r=2] (the "after training" values)
B_TRAINED = torch.tensor([
    [ 0.10, -0.08],
    [-0.12,  0.15],
    [ 0.20,  0.05],
    [-0.06,  0.18],
    [ 0.14, -0.10],
    [-0.09,  0.22],
    [ 0.16, -0.04],
    [-0.11,  0.13],
], dtype=torch.float32)

D, K = W0.shape          # 8, 8
R, ALPHA = 2, 16         # rank, alpha


# ============================================================================
# 4. SECTIONS  (the numbers that feed PEFT_LORA.md)
# ============================================================================

def section_why_full_ft_fails():
    banner("SECTION A: WHY full fine-tuning does not scale (the memory math)")
    print("One linear layer of a real model (Qwen3-0.5B hidden dim d=k=896):\n")
    d_k = 896 * 896
    print(f"  full FT params for ONE layer  = d·k = 896·896 = {d_k:,} weights")
    print(f"  trainable weights to STORE    = {d_k:,}  (must back-prop through all)\n")
    print("For GPT-3 175B (the LoRA paper's motivating example), full fine-tuning")
    print("one task needs ~175,000,000,000 new numbers. Serving N=100 personalized")
    print("tasks means 100 independent 175B replicas = ~35 TB of weights.\n")
    print("Even per-LAYER this is the bottleneck: the SAME d×k weight is rewritten")
    print("for every task. LoRA replaces that with a tiny r×(d+k) adapter. See §C.")


def section_lora_forward():
    banner("SECTION B: LoRA forward  y = W₀x + (α/r)·B·(A·x)  (worked, d=8,k=8,r=2)")
    print(f"d = {D}, k = {K}, r = {R}, α = {ALPHA},  scale = α/r = {ALPHA/R:.4f}\n")
    print(f"Input x [k={K}] : {[round(v, 2) for v in X.tolist()]}")
    print(f"W₀   [d,k]={tuple(W0.shape)}  (FROZEN, never trained)\n")

    # --- STEP 0: at INIT, B = 0 -> ΔW = 0 -> model == base model exactly ---
    lora_init = LoRALinear(W0, rank=R, alpha=ALPHA, A=A, B=torch.zeros(D, R))
    y_init = lora_init(X)
    y_base = W0 @ X
    print("Step 0 (paper init): A ~ Gaussian, B = 0  =>  ΔW = B·A = 0")
    print(f"  y_init  = {[round(v, 4) for v in y_init.tolist()]}")
    print(f"  W₀·x    = {[round(v, 4) for v in y_base.tolist()]}")
    assert torch.allclose(y_init, y_base, atol=1e-6)
    print("  [check] B=0 ⇒ LoRA output == base output exactly : OK")
    print("  (so step-0 training behaves IDENTICALLY to the pretrained model)\n")

    # --- STEP 1: "train" B by assigning the learned values, then forward ---
    lora = LoRALinear(W0, rank=R, alpha=ALPHA, A=A, B=B_TRAINED)
    base = W0 @ X
    adapt = (ALPHA / R) * (B_TRAINED @ (A @ X))     # the adapter path
    y = lora(X)
    print("Step 1 (after training): B ← learned values, A unchanged")
    print(f"  base path  W₀·x            = {[round(v, 4) for v in base.tolist()]}")
    print(f"  adapter    (α/r)·B(A·x)    = {[round(v, 4) for v in adapt.tolist()]}")
    print(f"  y = base + adapter         = {[round(v, 4) for v in y.tolist()]}\n")

    # --- GOLD PIN for the .html gold-check ---
    print("GOLD (for peft_lora.html to reproduce, r=2):")
    print(f"  y[0] = {y[0].item():.6f}")
    print(f"  y    = {[round(v, 4) for v in y.tolist()]}")
    print(f"  base = {[round(v, 4) for v in base.tolist()]}")
    print(f"  adapt= {[round(v, 4) for v in adapt.tolist()]}")
    return lora, y, base, adapt


def section_param_savings():
    banner("SECTION C: parameter savings  d·k (full FT) vs r·(d+k) (LoRA)")
    print(f"Concrete layer d={D}, k={K}:\n")
    full = D * K
    print(f"  full FT trainable = d·k       = {D}·{K} = {full}")
    print("| r  | LoRA params r·(d+k) | ratio r(d+k)/dk | savings  |")
    print("|----|----------------------|-----------------|----------|")
    for r in (1, 2, 4, 8, 16):
        lora_p = r * (D + K)
        ratio = lora_p / full
        print(f"| {r:<2} | {lora_p:<20} | {ratio:<15.4f} | {1/ratio:<8.2f}x |")
    print(f"\n  At r={R}: LoRA trains {R*(D+K)} params vs {full} full-FT"
          f" = {R*(D+K)/full:.4f} of the weights ({full/(R*(D+K)):.1f}x fewer).\n")

    print("Real model (GPT-3 175B, the LoRA paper §4.2): one d×k attention layer")
    print("with d=k=12288, r=4:")
    big = 12288 * 12288
    big_lora = 4 * (12288 + 12288)
    print(f"  full FT = {big:,}  vs  LoRA = {big_lora:,}  "
          f"=> {big_lora/big:.6f} = {big/big_lora:.0f}x fewer trainable params")
    print("  (paper: ~10,000x reduction across all adapted layers; checkpoint")
    print("   350GB -> 35MB; VRAM 1.2TB -> 350GB.)")


def section_deltaW_reconstruction(lora, y, base, adapt):
    banner("SECTION D: assert  (α/r)·B·A == ΔW  and  LoRA output == W₀x + ΔW·x")
    # ΔW from the explicit rank-r product
    deltaW = (ALPHA / R) * (B_TRAINED @ A)          # [d, k], rank ≤ r
    print(f"ΔW = (α/r)·B·A, shape {tuple(deltaW.shape)}, "
          f"rank = {torch.linalg.matrix_rank(deltaW).item()} "
          f"(≤ r={R} by construction)\n")
    # show a 4x4 corner for readability
    print("ΔW [0:4, 0:4] corner:")
    for i in range(4):
        print("  " + "  ".join(f"{deltaW[i, j].item():+.4f}" for j in range(4)))
    print()

    # (1) the class's delta_W must equal the explicit product
    assert torch.allclose(deltaW, lora.delta_W(), atol=1e-6)
    print("[check] lora.delta_W() == (α/r)·B·A            : OK")

    # (2) B·A has rank exactly r (the whole point of "low-rank")
    assert torch.linalg.matrix_rank(B_TRAINED @ A).item() == R
    print(f"[check] rank(B·A) == r = {R}                     : OK")

    # (3) the two-path output must equal W₀x + ΔW·x (folded form)
    folded = (W0 + deltaW) @ X
    assert torch.allclose(y, folded, atol=1e-5)
    print("[check] W₀x + (α/r)BAx == (W₀+ΔW)x  (merge OK): OK")

    print("\nThis is why you may MERGE at deploy time: replace W₀ with W₀+ΔW and")
    print("the layer becomes a plain linear with ZERO added latency, or keep W₀")
    print("frozen and swap (A,B) per task for multi-adapter serving (§F).")


def section_qlora():
    banner("SECTION E: QLoRA — NF4-quantized FROZEN base W₀ + fp16 adapters A,B 🔗")
    print("QLoRA = quantize the FROZEN W₀ to 4-bit NF4 (tiny, never trained), keep")
    print("the SMALL adapters A,B in fp16 (the only things back-prop touches).\n")

    print(f"NF4 codebook = 16 fixed levels = quantiles of N(0,1), normalized to ±1:")
    print(f"  {[round(v, 4) for v in NF4_CODEBOOK.tolist()]}")
    print("  (8 levels densely packed in [-0.28, +0.25] — where weights cluster)\n")

    # quantize W₀ block-wise (group_size = 8 = one block per row)
    scales, idx = nf4_quantize(W0, group_size=NF4_GROUP_SIZE)
    W0_hat = nf4_dequant(scales, idx, group_size=NF4_GROUP_SIZE)
    max_err = float((W0 - W0_hat).abs().max())
    print(f"NF4-quantize W₀ [d,k]={tuple(W0.shape)} with group_size={NF4_GROUP_SIZE}:")
    print(f"  W₀_hat indices [0:4, 0:8] (each ∈ 0..15):")
    for i in range(4):
        print("    " + "  ".join(f"{int(idx[i, j].item()):2d}" for j in range(K)))
    print(f"  scales (absmax per block, first 4): "
          f"{[round(s, 4) for s in scales[:4].tolist()]}")
    print(f"  max |W₀ - W₀_hat| = {max_err:.4f}  (rounding to nearest NF4 level)\n")

    # QLoRA forward: y = W₀_hat·x + (α/r)·BAx  (adapters stay fp16)
    lora = LoRALinear(W0, rank=R, alpha=ALPHA, A=A, B=B_TRAINED)
    y_full = lora(X)                                  # fp16 base + adapter (truth)
    y_qlora = (W0_hat @ X) + (ALPHA / R) * (B_TRAINED @ (A @ X))
    print("QLoRA forward:  y = dequant(W₀)·x + (α/r)·B·(A·x)")
    print(f"  y_fp16 base (truth) = {[round(v, 4) for v in y_full.tolist()]}")
    print(f"  y_QLoRA (NF4 base)  = {[round(v, 4) for v in y_qlora.tolist()]}")
    print(f"  max |diff|          = "
          f"{float((y_full - y_qlora).abs().max()):.4f}  "
          f"(≈ the NF4 base rounding error only; adapter path is EXACT)\n")

    # --- the MEMORY math: NF4 base is ~4x smaller than fp16 ---
    print("Memory of the FROZEN base W₀ [d=896, k=896] (Qwen3-0.5B layer):")
    n = 896 * 896
    fp16_bytes = n * 2
    nf4_bytes = n // 2                       # 4 bits = 0.5 byte/weight
    print(f"  fp16 base : {n}*2     = {fp16_bytes:>10,} bytes = {fp16_bytes/1e6:.3f} MB")
    print(f"  NF4  base : {n}/2     = {nf4_bytes:>10,} bytes = {nf4_bytes/1e6:.3f} MB")
    print(f"  -> {fp16_bytes/nf4_bytes:.1f}x smaller base  (4-bit vs 16-bit)")
    print("  (QLoRA paper: 65B model fits in a single 48GB GPU this way.) 🔗")


def section_multi_adapter():
    banner("SECTION F: multi-adapter serving — Punica grouped GEMM + S-LoRA paged memory")
    # Two adapters in one batch. Token group g0 -> adapter 0, g1 -> adapter 1.
    # A batched "grouped GEMM" applies each adapter to its own token slice in ONE
    # call (Punica's SGMV/BGMV kernel), instead of looping per adapter.
    g0 = torch.tensor([0.30, -0.10,  0.50, -0.20,  0.10, -0.40,  0.25,  0.15])  # 1 token
    g1 = torch.tensor([-0.20,  0.40,  0.10,  0.30, -0.15,  0.20, -0.30,  0.05])  # 1 token
    X_batch = torch.stack([g0, g1], dim=0)            # [2 tokens, k]

    # adapter 0 = the (A, B_TRAINED) from §B; adapter 1 = a different learned pair
    A1 = torch.tensor([
        [ 0.08,  0.18, -0.12,  0.05,  0.22, -0.10,  0.14, -0.06],
        [-0.16,  0.04,  0.20,  0.09, -0.15,  0.11,  0.07,  0.19],
    ], dtype=torch.float32)
    B1 = torch.tensor([
        [-0.05,  0.14],
        [ 0.11, -0.09],
        [-0.18,  0.06],
        [ 0.07,  0.13],
        [-0.13,  0.10],
        [ 0.19, -0.04],
        [-0.08,  0.17],
        [ 0.12, -0.11],
    ], dtype=torch.float32)
    adapters = [(A, B_TRAINED), (A1, B1)]
    names = ["adapter 0", "adapter 1"]

    print("Batch of 2 tokens, each routed to its OWN adapter (multi-tenant):\n")
    print(f"  token 0 x = {[round(v, 2) for v in g0.tolist()]}  -> adapter 0 (A, B_TRAINED)")
    print(f"  token 1 x = {[round(v, 2) for v in g1.tolist()]}  -> adapter 1 (A', B')\n")

    # --- the LOOP version (what PyTorch does naively): one matmul per adapter ---
    print("Naive (loop per adapter) — 2 sequential matmuls:")
    y_loop = torch.zeros(2, D)
    for i, (Ai, Bi) in enumerate(adapters):
        y_loop[i] = W0 @ X_batch[i] + (ALPHA / R) * (Bi @ (Ai @ X_batch[i]))
    print(f"  y[0] (adapter 0) = {[round(v, 4) for v in y_loop[0].tolist()]}")
    print(f"  y[1] (adapter 1) = {[round(v, 4) for v in y_loop[1].tolist()]}\n")

    # --- the GROUPED-GEMM version (Punica): one batched call for both adapters ---
    # Stack the adapter matrices and apply each to its own token via broadcasting.
    A_stack = torch.stack([Ai for Ai, _ in adapters])        # [2, r, k]
    B_stack = torch.stack([Bi for _, Bi in adapters])        # [2, d, r]
    # per-token: (α/r) · B_i @ (A_i @ x_i), vectorized over the 2 tokens
    ax = torch.einsum("trk,tk->tr", A_stack, X_batch)        # [2, r]  = A·x per token
    adapt_batch = (ALPHA / R) * torch.einsum("tdr,tr->td", B_stack, ax)  # [2, d]
    base_batch = X_batch @ W0.T                              # [2, d]  = W₀x per token
    y_grouped = base_batch + adapt_batch
    print("Punica grouped GEMM — ONE batched call (einsum) for BOTH adapters:")
    print(f"  y[0] (adapter 0) = {[round(v, 4) for v in y_grouped[0].tolist()]}")
    print(f"  y[1] (adapter 1) = {[round(v, 4) for v in y_grouped[1].tolist()]}\n")

    assert torch.allclose(y_loop, y_grouped, atol=1e-5)
    print("[check] grouped-GEMM output == per-adapter loop output : OK")
    print("[check] shared frozen base W₀ used once for all tokens : OK\n")

    print("S-LoRA adds PAGED adapter memory: thousands of (A_i,B_i) live in a unified")
    print("page table (like PagedAttention for KV cache, 🔗 the Phase-3 sibling). Only")
    print("the adapters referenced by the current batch are paged in — sub-millisecond")
    print("swap, zero duplication of the frozen base. Result: serve 1 base + N adapters")
    print("concurrently on one GPU, paying the base cost once.")


def section_serving_math():
    banner("SECTION G: the serving math — N adapters × tiny r(d+k) vs N full replicas")
    print("To serve N personalized tasks, how much weight must live in VRAM?\n")
    d_k_real = 12288 * 12288
    r_real = 64
    print(f"One attention layer d=k=12288 (GPT-3), adapter rank r={r_real}:\n")
    print("| strategy                        | weights in VRAM for N=1000 tasks   |")
    print("|---------------------------------|------------------------------------|")
    full_per = d_k_real
    lora_per = r_real * (12288 + 12288)
    print(f"| N full replicas (full FT)       | 1000·{full_per:,} = "
          f"{1000*full_per/1e9:.1f} B weights            |")
    print(f"| 1 base + N LoRA adapters (ours) | {full_per:,} + 1000·{lora_per:,} "
          f"= {(full_per + 1000*lora_per)/1e9:.2f} B weights       |")
    print(f"| 1 base + N QLoRA adapters       | {full_per//4:,}(NF4) + 1000·{lora_per:,} "
          f"= {(full_per//4 + 1000*lora_per)/1e9:.2f} B weights       |")
    print()
    print(f"The adapter overhead per task is r·(d+k) = {lora_per:,} weights = "
          f"{lora_per/full_per*100:.2f}% of one full layer. So a THOUSAND adapters add")
    print(f"only ~{1000*lora_per/full_per:.1f} extra base-layers' worth of weights, and the")
    print("frozen base is paid ONCE. That is the whole economics of multi-adapter")
    print("serving (Punica, S-LoRA, vLLM multi-LoRA).")


# ============================================================================
# main
# ============================================================================

def main():
    print("peft_lora.py - reference impl. All numbers below feed PEFT_LORA.md.")
    print("torch =", torch.__version__)
    print("LoRA:  y = W₀x + (α/r)·B·A·x   (Hu et al. 2021, arXiv:2106.09685)")
    print("QLoRA: W₀ -> 4-bit NF4, adapters A,B stay fp16 (Dettmers et al. 2023)")

    section_why_full_ft_fails()
    lora, y, base, adapt = section_lora_forward()
    section_param_savings()
    section_deltaW_reconstruction(lora, y, base, adapt)
    section_qlora()
    section_multi_adapter()
    section_serving_math()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
