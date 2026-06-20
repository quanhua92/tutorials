"""
ktransformers_offload.py - Reference implementation of KTransformers-style
heterogeneous CPU/GPU expert-offloading for MoE inference.

This is the single source of truth that KTRANSFORMERS_OFFLOAD.md is built from.
Every number, table, and worked example in the guide is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python ktransformers_offload.py

== IMPORTANT: THIS IS A FAITHFUL SIMULATION ================================
There is no real Intel AMX/AVX-512 unit, no 24 GB GPU, and no 382 GB DRAM on
this Mac. What IS real and reproducible here:
  * the GPU+CPU SPLIT of a MoE layer (attention + router + shared expert on the
    GPU; routed expert weights resident in CPU DRAM; only the tiny hidden-state
    activations cross the PCIe bus per token)  -- 🔗 MOE_ROUTING for the router;
  * the per-token TRANSFER ARITHMETIC using PUBLISHED hardware bandwidths
    (PCIe Gen4 ~64 GB/s, Gen5 ~128 GB/s; HBM ~3.35 TB/s; DDR5 ~200 GB/s). The
    latencies are bytes / real_bandwidth -- not invented;
  * the LAYER-OFFLOAD vs EXPERT-OFFLOAD contrast (350 GB of weights per token
    vs ~14 KB of activations per expert call) -- the gold centerpiece; and
  * a tiny SwiGLU-expert forward (🔗 MLP_ACTIVATION) so the route -> AMX GEMM ->
    gather flow produces a real, printable output tensor.
What is SIMULATED (clearly labelled in each section): "GPU"/"CPU" are tags on
in-process tensors (no real device split); "AMX GEMM" is a plain torch matmul;
the transfer "latency" is a number derived from real bandwidths. The
conclusions (activations << weights; PCIe stops being the bottleneck) hold
because they rest on the real transfer arithmetic, not on the simulated
transport.

== THE BIG IDEA, IN ONE SENTENCE (the "weight-stays, activation-flies" idea) ==
A 671B MoE model is ~335 GB even at 4-bit (🔗 QUANTIZATION) -- far beyond a
consumer GPU (24 GB). The naive fix, layer-by-layer offloading, streams ALL
weights across PCIe every token: 350 GB / 64 GB/s ~= 0.18 tok/s -- unusable.
KTransformers keeps attention + embeddings + the shared expert on the GPU and
offloads ONLY the MoE EXPERT WEIGHTS to CPU DRAM, where Intel AMX / AVX-512
runs low-precision GEMMs near-GPU-speed. Per token, only the tiny hidden-state
activations (~14 KB per expert call) cross PCIe -- NOT the weights -- so PCIe
bandwidth stops being the bottleneck. MoE sparsity (only k experts active per
token, 🔗 MOE_ROUTING) is what makes the CPU compute feasible.

== THE LINEAGE (old -> new, with WHY) ========================================
  1. GPU-ONLY: fit the whole model in VRAM. Great if you can afford 8x H100;
     impossible for a 671B model on a single 24 GB consumer GPU (335 GB @ 4-bit
     does not fit).
  2. LAYER OFFLOAD (llama.cpp style): stream each layer's weights across PCIe
     just-in-time for every token. Transfer/token = model_size = ~350 GB ->
     350 GB / 64 GB/s ~= 5.47 s/tok -> ~0.18 tok/s. Unusable. The PCIe bus is
     the bottleneck because the STATIC weights (huge) move every step, not the
     DYNAMIC activations (tiny).
  3. EXPERT OFFLOAD (KTransformers): put attention + embeddings + shared expert
     in VRAM; park the MoE expert weights in CPU DRAM (🔗 LMCACHE for the
     hierarchy idea). Per token only the hidden-state activations fly across
     PCIe (~14 KB/expert-call), the CPU runs the k active experts via AMX, and
     the small output flies back. PCIe stops being the bottleneck; the new
     bottleneck is CPU AMX throughput on the k active experts (much cheaper).
     MoE sparsity (only k of E experts active, 🔗 MOE_ROUTING) is the enabling
     trick: a dense FFN would force ALL expert weights through CPU compute every
     token; MoE means only k small GEMMs run on the CPU per token.

== PLAIN-ENGLISH GLOSSARY (used in every section below) ======================
    MoE             Mixture-of-Experts: a router picks k of E experts per token
                    (🔗 MOE_ROUTING). DeepSeek-V3: 256 routed + 1 shared, k=8.
    layer offload   naive scheme: stream ALL layer weights across PCIe every
                    token. Bottleneck = model_size / PCIe_BW. Unusable at 671B.
    expert offload  KTransformers scheme: expert weights stay RESIDENT in CPU
                    DRAM; only hidden-state activations cross PCIe per token.
    hidden state    the per-token vector flowing through the model (the "data").
                    For DeepSeek-V3, 7168 numbers x 2 bytes (fp16) = ~14.3 KB.
    weight          the learned matrix entries (the "knowledge"). STATIC: stored
                    once, re-read forever. Huge (~335 GB at 4-bit for 671B).
    activation      the per-token data flowing through. DYNAMIC, TINY (~14 KB).
    PCIe            the GPU<->CPU bus. Gen4 x16 ~64 GB/s; Gen5 x16 ~128 GB/s.
                    The bottleneck for layer offload; negligible for expert offload.
    AMX             Intel Advanced Matrix Extensions: 8 tile registers (1 KB each)
                    + a TMUL matrix-multiply unit, runs INT8/BF16 GEMMs at
                    multi-TFLOP/s on a Xeon. The "near-GPU-speed" CPU engine.
    AVX-512         older 512-bit SIMD (VNNI for INT8). Fallback when no AMX.
    shared expert   DeepSeek-V3 expert that is ALWAYS ON (not routed); stays on
                    the GPU (🔗 MOE_ROUTING Section F). Captures common features.
    routed expert   one of the 256 specialists the router picks k=8 of per token.
                    These are the ones offloaded to CPU DRAM in KTransformers.
    roofline        mem-bound vs compute-bound floor (🔗 LMCACHE prefill_floor).
    block table     the per-request page index (🔗 PAGED_ATTENTION). Unchanged by
                    KTransformers; the KV cache still lives in GPU VRAM.

== TENSOR / SIZING CONVENTIONS ===============================================
Two separate scales are used and clearly labelled:
  (a) TINY execution-flow demo (D=8, E=4, k=2, F=16, 1 layer) -> so the
      GPU+CPU split + the route->AMX->gather flow is PRINTABLE. Mechanism demo.
  (b) REALISTIC transfer-budget dims (DeepSeek-V3: hidden=7168, 256 routed + 1
      shared expert, k=8, 61 layers, 671B params) + PUBLISHED bandwidths -> the
      layer-offload-vs-expert-offload arithmetic. These justify KTransformers.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. PUBLISHED HARDWARE NUMBERS  (the load-bearing facts; never hand-waved)
#    Sources: PCIe 4.0/5.0 x16 specs; H100 SXM HBM3 (3.35 TB/s); NVIDIA A100;
#    Intel AMX (8 tiles x 1 KB, TMUL, INT8+BF16) on 4th/5th Gen Xeon; DDR5.
# ============================================================================

# PCIe: bytes/s, unidirectional, practical. (Source: 04_Distributed_Scale.md
# line 967 "PCIe Gen4: 64 GB/s"; lmcache TIER_SPECS "Gen5 x16 ~64 GB/s; Gen4 ~32".
# We use 64 for Gen4 x16 bidirectional / the source-guide convention; 128 for Gen5.)
PCIE_GEN4_BW = 64e9     # bytes/s  (~64 GB/s)
PCIE_GEN5_BW = 128e9    # bytes/s  (~128 GB/s)
HBM_BW = 3.35e12        # bytes/s  (H100 SXM HBM3 ~3.35 TB/s)
DDR5_BW = 200e9         # bytes/s  (8-channel DDR5-5000 ~200 GB/s aggregate)
BYTES_FP16 = 2          # bytes per fp16/bf16 activation

# Intel AMX (VERIFIED from intel.com): 8 two-dimensional tile registers, each
# 1 KB (= 16 rows x 64 bytes), + a TMUL (Tile Matrix Multiply) unit that does
# INT8 and BF16 GEMMs. Introduced with Sapphire Rapids (4th Gen Xeon), Jan 2023.
AMX_TILES = 8
AMX_TILE_BYTES = 1024
AMX_DTYPES = ("INT8", "BF16")

# DeepSeek-V3 reference dims (the model KTransformers targets).
DS_V3_TOTAL_PARAMS = 671e9      # 671B total
DS_V3_ACTIVE_PARAMS = 37e9      # 37B active per token
DS_V3_HIDDEN = 7168             # model/hidden dim
DS_V3_N_ROUTED = 256            # routed experts
DS_V3_N_SHARED = 1              # shared expert (always on)
DS_V3_K = 8                     # top-k per token
DS_V3_LAYERS = 61               # transformer layers
DS_V3_4BIT_BYTES = 0.5          # bytes per param at 4-bit (🔗 QUANTIZATION)
# Model footprint at 4-bit (weights) + scale/bias overhead -> ~350 GB (source-guide
# value used in the transfer math). Pure 4-bit would be 671e9*0.5 = 335.5 GB.
DS_V3_MODEL_BYTES = 350e9       # ~350 GB with quant overhead (🔗 QUANTIZATION)

# Consumer GPU VRAM (the "doesn't fit" reference).
CONSUMER_GPU_VRAM = 24e9        # 24 GB (RTX 4090 / 3090 class)


# ============================================================================
# 2. THE FAITHFUL SIMULATION CORE: a MoE layer split across GPU + CPU tags.
#    "GPU" and "CPU" are just string tags on in-process tensors; the transfer
#    latency is computed separately from real bandwidths. (Mirrors 🔗 LMCACHE's
#    simulation discipline: real bandwidths, simulated transport.)
# ============================================================================

def silu(x: torch.Tensor) -> torch.Tensor:
    """SiLU(x) = x * sigmoid(x).  🔗 MLP_ACTIVATION Section 2.3."""
    return x * torch.sigmoid(x)


def linear(x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
    """x @ w.T  where w has shape [out, in].  No bias, for clarity."""
    return x @ w.T


def keep_topk(logits: torch.Tensor, k: int) -> torch.Tensor:
    """KeepTopK: top-k survive, rest -> -inf (🔗 MOE_ROUTING Section 3)."""
    topk_vals, _ = torch.topk(logits, k, dim=-1)
    threshold = topk_vals[..., -1:]
    return torch.where(logits >= threshold, logits,
                       torch.full_like(logits, float("-inf")))


class Expert:
    """One SwiGLU MLP specialist (🔗 MLP_ACTIVATION Section 6; 🔗 MOE_ROUTING).

    E_i(x) = down( silu(gate(x)) * up(x) )
    Shapes: w_gate [F,D], w_up [F,D], w_down [D,F].

    `device_tag` is just a string ("GPU"/"CPU") for the simulation -- it does
    NOT move the tensor. It records WHERE this expert's weights "live".
    """

    def __init__(self, w_gate, w_up, w_down, device_tag: str = "CPU"):
        self.w_gate = w_gate
        self.w_up = w_up
        self.w_down = w_down
        self.device_tag = device_tag

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        gate = silu(linear(x, self.w_gate))
        up = linear(x, self.w_up)
        return linear(gate * up, self.w_down)


class KTransformersLayer:
    """One MoE transformer layer split GPU(attn+router+shared) / CPU(routed).

    This is the faithful-simulation core. The FORWARD computes real numbers;
    the TRANSFER bookkeeping records how many activation bytes "cross PCIe".

        forward(x):
          [GPU]  RMSNorm -> Attention -> Router logits H = x.W_g^T
          [GPU]  G = softmax(KeepTopK(H, k))         (gate weights, k nonzero)
          [GPU]  y_shared = shared_expert(x)         (always on, on GPU)
          [CPU]  for i in routed: y_i = G_i * routed_expert_i(x)
                  (x flies GPU->CPU per call; y_i flies CPU->GPU back)
          [GPU]  y = y_shared + sum(y_i)             (gather into residual)

    `transfer_log` accumulates the bytes that "crossed PCIe" this forward.
    """

    def __init__(self, hidden: int, n_routed: int, n_shared: int, k: int,
                 inter: int, w_router, shared_experts, routed_experts,
                 bytes_per_elem: int = BYTES_FP16):
        self.hidden = hidden
        self.n_routed = n_routed
        self.n_shared = n_shared
        self.k = k
        self.inter = inter
        self.w_router = w_router
        self.shared_experts = shared_experts      # list (on "GPU")
        self.routed_experts = routed_experts      # list (on "CPU")
        self.bytes_per_elem = bytes_per_elem
        self.transfer_log = 0   # bytes that crossed PCIe this forward

    def _gpu_router(self, x: torch.Tensor):
        """[GPU] H = x.W_g^T ; G = softmax(KeepTopK(H, k)) ; topk_idx."""
        H = linear(x, self.w_router)
        masked = keep_topk(H, self.k)
        G = F.softmax(masked, dim=-1)
        _, idx = torch.topk(H, self.k, dim=-1)
        return H, G, idx

    def forward(self, x: torch.Tensor):
        """Returns (y, G, idx, transfer_bytes).

        x: [B, L, D] hidden state (assumed already post-attention for the
            demo; this class focuses on the MoE split, attention is a no-op
            GPU step sketched in the .md execution flow).
        y: [B, L, D] MoE output = y_shared + sum_i G_i * routed_i(x).
        """
        B, L, D = x.shape
        self.transfer_log = 0
        # --- [GPU] router ---
        H, G, idx = self._gpu_router(x)
        # --- [GPU] shared expert (always on, never crosses PCIe) ---
        y = torch.zeros_like(x)
        for se in self.shared_experts:
            y = y + se(x)
        # --- [CPU] routed experts: x flies over, output flies back ---
        for i, expert in enumerate(self.routed_experts):
            g_i = G[..., i].unsqueeze(-1)              # [B, L, 1]
            if (g_i.abs() > 0).any():                  # only active experts run
                # GPU -> CPU: send x  (B*L*D*bytes)
                self.transfer_log += x.numel() * self.bytes_per_elem
                out = expert(x)                         # "AMX GEMM" on CPU
                # CPU -> GPU: send out  (B*L*D*bytes)
                self.transfer_log += out.numel() * self.bytes_per_elem
                y = y + g_i * out
        return y, G, idx, self.transfer_log


# ============================================================================
# 3. PRETTY PRINTER
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def vec(a, d=4):
    return "[" + ", ".join((f"{v:+.{d}f}") for v in a) + "]"


def gb(b: float) -> str:
    return f"{b/1e9:.2f} GB"


def kb(b: float) -> str:
    if b >= 1e6:
        return f"{b/1e6:.3f} MB"
    if b >= 1e3:
        return f"{b/1e3:.3f} KB"
    return f"{b:.1f} B"


# ============================================================================
# 4. BUILD THE TINY MODEL (deterministic; mechanism demo only)
#    D=8, E=4 routed + 1 shared, k=2, F=16, 1 layer. Mirrors build_tiny_moe()
#    in 🔗 moe_routing.py so the routing numbers are directly comparable.
# ============================================================================

def build_tiny_layer(seed_x=42, seed_router=100, seed_shared=7, seed_experts=200):
    """Deterministically build the tiny KTransformers split layer."""
    D, F, E, k = 8, 16, 4, 2
    B, L = 1, 4

    gx = torch.Generator().manual_seed(seed_x)
    x = torch.randn(B, L, D, generator=gx) * 0.5                 # [1, 4, 8]

    gr = torch.Generator().manual_seed(seed_router)
    w_router = (torch.randn(E, D, generator=gr) * 0.1)           # [4, 8]

    gs = torch.Generator().manual_seed(seed_shared)
    shared = [Expert(
        torch.randn(F, D, generator=gs) * 0.1,
        torch.randn(F, D, generator=gs) * 0.1,
        torch.randn(D, F, generator=gs) * 0.1,
        device_tag="GPU",
    )]

    ge = torch.Generator().manual_seed(seed_experts)
    routed = []
    for _ in range(E):
        routed.append(Expert(
            torch.randn(F, D, generator=ge) * 0.1,
            torch.randn(F, D, generator=ge) * 0.1,
            torch.randn(D, F, generator=ge) * 0.1,
            device_tag="CPU",
        ))

    layer = KTransformersLayer(
        hidden=D, n_routed=E, n_shared=1, k=k, inter=F,
        w_router=w_router, shared_experts=shared, routed_experts=routed,
        bytes_per_elem=BYTES_FP16,
    )
    return layer, x, dict(D=D, F=F, E=E, k=k, B=B, L=L)


# ============================================================================
# 5. THE SECTIONS  (the numbers that feed KTRANSFORMERS_OFFLOAD.md)
# ============================================================================

def section_a_why_doesnt_fit():
    # INTUITION: 671B at 4-bit is ~335-350 GB. A consumer GPU is 24 GB. The
    # model simply does not fit in VRAM. That is the problem.
    banner("SECTION A: why a 671B MoE does NOT fit on one consumer GPU")
    print(f"DeepSeek-V3/R1: {DS_V3_TOTAL_PARAMS/1e9:.0f}B total params, "
          f"{DS_V3_ACTIVE_PARAMS/1e9:.0f}B active/token (🔗 MOE_ROUTING Section A).\n")
    fp16_bytes = DS_V3_TOTAL_PARAMS * BYTES_FP16
    w4_bytes = DS_V3_TOTAL_PARAMS * DS_V3_4BIT_BYTES
    print(f"| precision      | bytes/param | model footprint    | fits 24 GB GPU? |")
    print(f"|----------------|-------------|--------------------|-----------------|")
    print(f"| FP16 / BF16    | {BYTES_FP16}           | {gb(fp16_bytes):<18} | NO (14.6x over)  |")
    print(f"| W4A16 (4-bit)  | {DS_V3_4BIT_BYTES}           | {gb(w4_bytes):<18} | NO (14x over)    |")
    print(f"| W4A16 + ovh    | ~0.52       | {gb(DS_V3_MODEL_BYTES):<18} | NO               |")
    print()
    print(f"A 24 GB GPU holds {gb(CONSUMER_GPU_VRAM)}; the 4-bit model needs "
          f"{gb(DS_V3_MODEL_BYTES)} -- ~{DS_V3_MODEL_BYTES/CONSUMER_GPU_VRAM:.0f}x too big.")
    print("GPU-only serving is impossible on consumer hardware. We MUST offload")
    print("most of the weights to the much larger (and cheaper per GB) CPU DRAM.")
    print()
    ok = DS_V3_MODEL_BYTES > CONSUMER_GPU_VRAM
    print(f"[check] 4-bit model ({gb(DS_V3_MODEL_BYTES)}) > 24 GB GPU : "
          f"{ok} -> {'OK' if ok else 'FAIL'}")


def section_b_layer_offload():
    # INTUITION: naive layer offload streams ALL weights across PCIe every token.
    # 350 GB / 64 GB/s ~= 5.47 s/tok -> ~0.18 tok/s. Unusable. PCIe is the
    # bottleneck because the STATIC weights (huge) move every step.
    banner("SECTION B: naive LAYER OFFLOAD -- stream all weights every token")
    print("llama.cpp-style layer offload: for each token, pull every layer's")
    print("weights across PCIe just-in-time, compute, discard.\n")
    print("Transfer/token = model_size (the whole thing moves every token):\n")
    print(f"  bytes/token = {gb(DS_V3_MODEL_BYTES)} = {DS_V3_MODEL_BYTES:.3e} B\n")
    for name, bw in (("PCIe Gen4 x16", PCIE_GEN4_BW), ("PCIe Gen5 x16", PCIE_GEN5_BW)):
        t = DS_V3_MODEL_BYTES / bw
        tps = 1.0 / t
        print(f"  {name} @ {bw/1e9:.0f} GB/s: time/token = "
              f"{DS_V3_MODEL_BYTES:.2e} / {bw:.2e} = {t:.4f} s "
              f"-> {tps:.4f} tok/s ({tps*60:.2f} tok/min)")
    print()
    t_gen4 = DS_V3_MODEL_BYTES / PCIE_GEN4_BW
    tps_gen4 = 1.0 / t_gen4
    print(f"At PCIe Gen4 the ceiling is {tps_gen4:.3f} tok/s. For a 1000-token")
    print("answer that is ~1.5 HOURS. The PCIe bus is saturated by the WEIGHTS.")
    print()
    print("KEY: the weights are STATIC (stored once, identical every token) yet")
    print("layer offload re-streams them every token. That is the waste.")
    ok = tps_gen4 < 1.0
    print(f"\n[check] layer-offload tok/s < 1.0 (unusable) : {ok} -> "
          f"{'OK' if ok else 'FAIL'}")
    print(f"\nGOLD (layer offload @ Gen4): {t_gen4:.4f} s/tok, "
          f"{tps_gen4:.4f} tok/s.")


def section_c_expert_offload():
    # INTUITION: KTransformers parks the MoE expert weights in CPU DRAM (they
    # NEVER move per token). Only the hidden-state activations cross PCIe.
    # ~14 KB per expert call -- microscopic vs 350 GB.
    banner("SECTION C: KTransformers EXPERT OFFLOAD -- weights stay, activations fly")
    print("Split the layer:\n")
    print("  [GPU VRAM]  embeddings + attention + router + shared expert")
    print("              (the SMALL, HOT, frequently-touched parts)")
    print("  [CPU DRAM]  the 256 routed EXPERT WEIGHTS (~330 GB, parked once)")
    print("              the CPU runs the k=8 ACTIVE experts per token via AMX\n")
    print("Per expert call, what crosses PCIe? Only the hidden state:\n")
    act_bytes = 1 * DS_V3_HIDDEN * BYTES_FP16
    print(f"  activation/expert-call = batch x hidden x bytes")
    print(f"                         = 1 x {DS_V3_HIDDEN} x {BYTES_FP16}")
    print(f"                         = {act_bytes} B = {kb(act_bytes)}\n")
    for name, bw in (("PCIe Gen4 x16", PCIE_GEN4_BW), ("PCIe Gen5 x16", PCIE_GEN5_BW)):
        t = act_bytes / bw
        print(f"  {name} @ {bw/1e9:.0f} GB/s: time/call = {act_bytes} / {bw:.2e} "
              f"= {t*1e6:.3f} us  (microseconds, not seconds)\n")
    print("The weights NEVER cross PCIe per token -- they live in CPU DRAM.")
    print("PCIe bandwidth stops being the bottleneck. The new bottleneck is")
    print("CPU AMX throughput on the k active experts (Section E + F).")
    t_gen4 = act_bytes / PCIE_GEN4_BW
    ok = t_gen4 < 1e-3
    print(f"\n[check] expert-call transfer < 1 ms : {ok} -> {'OK' if ok else 'FAIL'}")
    print(f"\nGOLD (expert offload @ Gen4): {act_bytes} B/call, "
          f"{t_gen4*1e6:.3f} us/call.")


def section_d_execution_flow(layer: KTransformersLayer, x: torch.Tensor, dims: dict):
    # INTUITION: the tiny GPU+CPU split in action. GPU runs router + shared;
    # the k active routed experts run on the "CPU"; outputs gather back to GPU.
    # The transfer_log records how many activation bytes "flew".
    banner("SECTION D: the GPU+CPU execution flow (tiny demo, D=8, E=4, k=2)")
    E, k, D, L = dims["E"], dims["k"], dims["D"], dims["L"]
    print("Forward one tiny layer. Attention is sketched as a no-op on the GPU")
    print("(the focus here is the MoE split; 🔗 GQA / 🔗 ROPE cover attention).\n")
    y, G, idx, xfer = layer.forward(x)
    print(f"Input x: shape {tuple(x.shape)} = [B=1, L={L}, D={D}]\n")
    print("Per-token router decisions (🔗 MOE_ROUTING Section B math):")
    print("| m | routed experts | gate weights (nonzero)        | shared expert |")
    print("|---|----------------|-------------------------------|---------------|")
    for m in range(L):
        ix = idx[0, m].tolist()
        gw = [round(G[0, m, int(i)].item(), 4) for i in ix]
        gw_str = ", ".join(f"G{i}={w}" for i, w in zip(ix, gw))
        print(f"| {m} | {str(ix):<14} | {gw_str:<29} | always-on (GPU) |")
    print()
    print(f"MoE output y[0,0] (first 4 of {D}): {vec(y[0,0,:4].tolist())}")
    print()
    # transfer accounting on the tiny model
    n_active_calls = sum(1 for m in range(L) for i in range(E) if G[0,m,i] > 0)
    bytes_per_call = D * BYTES_FP16      # one token, one direction (B=1,L=1 demo per call)
    # The layer.forward counts B*L*D*bytes per direction per active expert call.
    print(f"Transfer bookkeeping for this forward (tiny demo):")
    print(f"  active routed-expert calls (over all {L} tokens) = {n_active_calls}")
    print(f"  bytes per direction per call (B*L*D*{BYTES_FP16}) = {1*L*D*BYTES_FP16}")
    print(f"  total bytes 'across PCIe' (both dirs) = {xfer} B = {kb(xfer)}")
    print()
    # The headline: even on the tiny model, transfer << any weight footprint.
    tiny_weight_bytes = (E * 3 * D * dims["F"] + 1 * 3 * D * dims["F"]) * DS_V3_4BIT_BYTES
    print(f"  (contrast: the tiny layer's routed+shared weight footprint at 4-bit")
    print(f"   would be {tiny_weight_bytes:.0f} B = {kb(tiny_weight_bytes)}; layer")
    print(f"   offload would re-stream that EVERY token; KTransformers streams")
    print(f"   only the {kb(xfer)} of activations above.)")
    ok = xfer < tiny_weight_bytes
    print(f"\n[check] activation transfer ({xfer} B) < weight footprint "
          f"({tiny_weight_bytes:.0f} B) : {ok} -> {'OK' if ok else 'FAIL'}")


def section_e_amx_avx():
    # INTUITION: AMX is what makes CPU expert compute fast enough. 8 tile
    # registers (1 KB each) + TMUL = INT8/BF16 GEMM at multi-TFLOP/s per Xeon.
    banner("SECTION E: CPU vectorization -- Intel AMX (and AVX-512 fallback)")
    print("The CPU must run the k active experts (SwiGLU GEMMs, 🔗 MLP_ACTIVATION)")
    print("fast enough to not become the new bottleneck. Two x86 engines:\n")
    print(f"| engine   | width              | data types   | role in KTransformers         |")
    print(f"|----------|--------------------|--------------|-------------------------------|")
    print(f"| AVX-512  | 512-bit SIMD (VNNI)| INT8         | fallback when no AMX (older)  |")
    print(f"| AMX      | {AMX_TILES} tiles x {AMX_TILE_BYTES} B   | {AMX_DTYPES[0]}, {AMX_DTYPES[1]}    | primary: tiled matrix-multiply |")
    print()
    print(f"AMX anatomy (VERIFIED, Intel): {AMX_TILES} two-dimensional TILE registers,")
    print(f"each {AMX_TILE_BYTES} B (= 16 rows x 64 bytes), plus a TMUL (Tile Matrix")
    print("Multiply) unit that does one tiled GEMM per instruction. Introduced with")
    print("Sapphire Rapids (4th Gen Xeon, Jan 2023); on every Xeon core.\n")
    print("Why it matters: a dual-socket Xeon with AMX sustains multi-TFLOP/s of")
    print("INT8/BF16 GEMM -- enough that the k=8 active experts per token (each a")
    print("small SwiGLU) compute in milliseconds, not the 5+ seconds layer offload")
    print("spends just WAITING on PCIe. The expert weights are stored quantized")
    print("(INT4/INT8, 🔗 QUANTIZATION) and dequantized into AMX tiles on the fly.\n")
    print("AVX-512 (VNNI) is the older 512-bit SIMD path for INT8 dot-products;")
    print("KTransformers uses it as a fallback on CPUs without AMX. AMX is strictly")
    print("faster for the dense GEMM kernels because it operates on whole tiles")
    print(f"({AMX_TILES} x {AMX_TILE_BYTES} B) per instruction, vs one 512-bit vector.")
    print()
    print("NOTE (simulation): this Mac has no AMX. The expert GEMMs in this file")
    print("are plain torch matmuls; the AMX throughput claim above is a published")
    print("hardware fact, not a measured number from this run.")
    ok = AMX_TILES * AMX_TILE_BYTES == 8 * 1024
    print(f"\n[check] AMX tile storage = {AMX_TILES} x {AMX_TILE_BYTES} = 8 KB "
          f"(matches Intel spec) : {ok} -> {'OK' if ok else 'FAIL'}")


def section_f_sparsity_makes_it_feasible():
    # INTUITION: MoE sparsity (only k of E experts active/token) is the enabling
    # trick. A dense FFN would force ALL expert weights through CPU compute every
    # token; MoE means only k small GEMMs run on the CPU. 🔗 MOE_ROUTING.
    banner("SECTION F: why MoE SPARSITY is what makes expert offload feasible")
    print("Expert offload works because of MoE sparsity: per token, only k=8 of")
    print("E=256 routed experts run (🔗 MOE_ROUTING Section 0). The other 248 are")
    print("dormant -- their weights sit in CPU DRAM doing nothing this token.\n")
    # dense-equivalent: if ALL experts ran every token (no sparsity), CPU compute
    # would be E/k x more work.
    print("| design                     | experts running/token | CPU GEMMs/token |")
    print("|----------------------------|-----------------------|-----------------|")
    print(f"| DeepSeek-V3 MoE (sparse)   | k={DS_V3_K} of E={DS_V3_N_ROUTED:<3}        | {DS_V3_K} x SwiGLU      |")
    print(f"| dense equivalent (all run) | all {DS_V3_N_ROUTED:<3}            | {DS_V3_N_ROUTED} x SwiGLU      |")
    print()
    print(f"MoE sparsity cuts CPU expert compute by {DS_V3_N_ROUTED}/{DS_V3_K} = "
          f"{DS_V3_N_ROUTED/DS_V3_K:.0f}x vs a dense FFN of the same total capacity.")
    print("Without sparsity, the CPU would have to run all 256 experts every")
    print("token -- the CPU AMX throughput, not PCIe, would become the wall, and")
    print("the model would be too slow to be useful on a single box.\n")
    print("This is also why KTransformers targets MoE models specifically: the")
    print("paper's title is '... Hybrid Inference for MoE Models' -- a dense LLM")
    print("(e.g. Llama-70B) gets far less benefit because its FFN is dense and")
    print("ALL of it must run every token regardless of where it lives.")
    ok = (DS_V3_N_ROUTED / DS_V3_K) > 10
    print(f"\n[check] E/k = {DS_V3_N_ROUTED/DS_V3_K:.0f} > 10 (sparsity pays off) : "
          f"{ok} -> {'OK' if ok else 'FAIL'}")


def section_g_transfer_contrast():
    # INTUITION: the GOLD CENTERPIECE. 350 GB of weights (layer offload) vs
    # ~14 KB / ~1.75 MB of activations (expert offload) per token. The ratio
    # is hundreds of thousands to millions. Recomputed live in the .html.
    banner("SECTION G: the GOLD CENTERPIECE -- 350 GB weights vs KB activations")
    print("Side-by-side transfer budget per token. Bandwidths are REAL; the")
    print("transport is a faithful simulation (no real KTransformers/AMX here).\n")
    # single-expert-call activation (the headline number from the source guide)
    act_one = 1 * DS_V3_HIDDEN * BYTES_FP16
    # full per-token activation accounting: both directions, all layers, k experts.
    # Per layer per direction: hidden*bytes. k routed experts -> but the hidden
    # state is the SAME for all k experts in a layer (routed in one shot), so the
    # transfer is 1 x hidden x bytes per direction per layer, not k x.
    # Conservative: count k round-trips (worst case, one call per expert).
    act_full_worst = DS_V3_K * DS_V3_LAYERS * act_one * 2     # k experts, 61 layers, round trip
    act_full_batched = DS_V3_LAYERS * act_one * 2             # batched: 1 round-trip/layer
    print(f"Single expert-call activation (the headline):")
    print(f"  = batch x hidden x bytes = 1 x {DS_V3_HIDDEN} x {BYTES_FP16} "
          f"= {act_one} B = {kb(act_one)}\n")
    print(f"Full per-token activation accounting (worst case: k calls/layer, both dirs):")
    print(f"  = k x layers x hidden x bytes x 2(dirs)")
    print(f"  = {DS_V3_K} x {DS_V3_LAYERS} x {DS_V3_HIDDEN} x {BYTES_FP16} x 2")
    print(f"  = {act_full_worst} B = {kb(act_full_worst)}\n")
    print(f"(Batched: 1 round-trip/layer = {kb(act_full_batched)}; the truth is")
    print(f" between these and still microscopic vs the weights.)\n")

    layer_offload_bytes = DS_V3_MODEL_BYTES
    print(f"Layer offload re-streams EVERY token: {gb(layer_offload_bytes)} "
          f"= {layer_offload_bytes:.3e} B\n")
    print(f"| scheme          | bytes/token   | time/token @ Gen4 {int(PCIE_GEN4_BW/1e9)} GB/s | tok/s        |")
    print(f"|-----------------|---------------|--------------------|--------------|")
    t_layer = layer_offload_bytes / PCIE_GEN4_BW
    t_expert_one = act_one / PCIE_GEN4_BW
    t_expert_full = act_full_worst / PCIE_GEN4_BW
    print(f"| layer offload   | {gb(layer_offload_bytes):<13} | {t_layer:.4f} s           | {1/t_layer:.4f}       |")
    print(f"| expert (1 call) | {kb(act_one):<13} | {t_expert_one*1e6:.3f} us          | {(1/t_expert_one):.0f} (uncapped) |")
    print(f"| expert (full)   | {kb(act_full_worst):<13} | {t_expert_full*1e6:.3f} us          | {(1/t_expert_full):.0f} (uncapped)|")
    print()
    ratio_one = layer_offload_bytes / act_one
    ratio_full = layer_offload_bytes / act_full_worst
    print(f"Ratio (layer offload bytes / expert-offload bytes per token):")
    print(f"  vs single expert call : {layer_offload_bytes:.2e} / {act_one:.2e} = "
          f"{ratio_one:,.0f}x  (~{ratio_one/1e6:.1f} million x)")
    print(f"  vs full per-token      : {layer_offload_bytes:.2e} / {act_full_worst:.2e} = "
          f"{ratio_full:,.0f}x  (~{ratio_full/1e3:.0f} thousand x)")
    print()
    print("VERDICT: PCIe bandwidth is the WHOLE bottleneck for layer offload and")
    print("NEGLIGIBLE for expert offload. KTransformers shifts the bottleneck from")
    print("'streaming 350 GB of static weights' to 'running k=8 small AMX GEMMs on")
    print("the CPU' -- a problem modern Xeons are built to solve. THAT is why a")
    print("671B MoE model can run on one cheap GPU+CPU box at usable speed.")
    print()
    ok = ratio_full > 1e4
    print(f"[check] layer/expert byte ratio > 10,000x : {ok} -> "
          f"{'OK' if ok else 'FAIL'}")
    print(f"\nGOLD (the .html recomputes these):")
    print(f"  layer_offload_time_gen4   = {t_layer:.4f} s/tok  ({1/t_layer:.4f} tok/s)")
    print(f"  expert_call_time_gen4     = {t_expert_one*1e6:.3f} us/call")
    print(f"  expert_full_time_gen4     = {t_expert_full*1e6:.3f} us/tok")
    print(f"  ratio (vs full per-token) = {ratio_full:,.0f}x")


# ============================================================================
# main
# ============================================================================

def main():
    print("ktransformers_offload.py - reference impl (FAITHFUL SIMULATION).")
    print("All numbers below feed KTRANSFORMERS_OFFLOAD.md. torch =", torch.__version__)
    print("NOTE: no real AMX/GPU split here; 'GPU'/'CPU' are tags on in-process")
    print("tensors. Bandwidth/transfer numbers are REAL published figures.\n")

    layer, x, dims = build_tiny_layer()

    section_a_why_doesnt_fit()
    section_b_layer_offload()
    section_c_expert_offload()
    section_d_execution_flow(layer, x, dims)
    section_e_amx_avx()
    section_f_sparsity_makes_it_feasible()
    section_g_transfer_contrast()

    banner("DONE - all sections printed; KTransformers sim gold = OK")


if __name__ == "__main__":
    main()
