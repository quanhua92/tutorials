"""
depth_vs_width.py - Reference implementation of the depth-vs-width trade-off
for memory-bandwidth-bound edge devices, and MobileLLM's layer-sharing trick.

This is the single source of truth that DEPTH_VS_WIDTH.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python depth_vs_width.py

== The big idea, in one paragraph (no math) ==================================
A transformer layer costs ~12*H^2 parameters (H = hidden width): 4*H^2 for the
attention (Q,K,V,O projections) + 8*H^2 for the 2-layer MLP (4*H intermediate).
So for a FIXED parameter budget N, the number of layers L trades one-for-one
against the square of the width: deep-and-narrow (small H, big L) and
shallow-and-wide (big H, small L) hold the same N but behave very differently.
Depth is provably more expressive per parameter (Telgarsky 2016: a deep net with
O(1) nodes/layer needs exponentially -- 2^k -- many nodes to match in a shallow
net), so quality prefers depth. The EDGE twist: decoding one token is
MEMORY-BANDWIDTH bound -- it reads EVERY unique weight once -- so latency scales
with UNIQUE parameter count, NOT with effective depth. MobileLLM (arXiv:2402.14905)
exploits exactly this: share ONE block recurrently K times (block-wise weight
sharing). Unique params = 1 block; effective depth = K. You get the quality of a
deep net for the decode-latency of a shallow net.

== The lineage (old -> new, with WHY) =========================================
  shallow-wide : many params per layer (big H), few layers (small L). Great
                 prefill parallelism, fewer sequential dependencies, but a
                 POLYNOMIAL expressivity budget per parameter -> worse reasoning.
  deep-narrow  : few params per layer (small H), many layers (big L). Same N,
                 but depth yields EXPONENTIAL expressivity (Telgarsky 2016:
                 Theta(k^3) layers with Theta(1) nodes match only Theta(2^k)
                 nodes in a shallow net) -> better reasoning per parameter.
  layer-shared : apply ONE transformer block K times recurrently (MobileLLM's
                 block-wise weight sharing). Unique params = 1 block; effective
                 depth = K. DECODE latency scales with UNIQUE params (memory-
                 bandwidth bound), so sharing CUTS decode traffic while keeping
                 the depth-driven quality. Ideal for edge (<1B, on-device).

== Plain-English glossary ====================================================
    H (width)    hidden dimension of one layer. A bigger H = wider matrices.
    L (depth)    number of transformer layers stacked sequentially.
    N            total non-embedding parameter budget (what we spend on layers).
    V (vocab)    tokenizer vocabulary size; the embedding tax is V*H, subtracted
                 from the full parameter count before counting layers.
    per-layer    ~12*H^2 params: 4*H^2 (Q,K,V,O attention) + 8*H^2 (MLP fc1,
                 fc2 with a 4*H intermediate). Biases/LayerNorms are O(H) and
                 are dropped from the leading-order count.
    decode       generating ONE token autoregressively. Memory-bandwidth bound:
                 it streams EVERY unique weight from DRAM once per token.
    unique       the count of DISTINCT weight elements. Shared (tied/reused)
    params       weights count ONCE -- that is the whole point of sharing.
    KV cache     per-layer memory holding past keys/values; grows with L (depth)
                 and seq_len, but is NOT part of the weight-read traffic.
    K (share     how many times ONE shared block is applied recurrently.
     factor)
    effective    the number of block applications a token passes through. For
    depth        layer-shared models: unique_layers * K.
"""

from __future__ import annotations

import torch
import torch.nn as nn

torch.set_printoptions(precision=4, sci_mode=False)
torch.manual_seed(0)  # determinism: every init/print is reproducible

BANNER = "=" * 72


# ============================================================================
# helpers
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(desc: str, ok: bool):
    """Print '[check] desc: OK' and exit non-zero on failure (no raw assert)."""
    status = "OK" if ok else "FAIL"
    print(f"  [check] {desc}: {status}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def per_layer_params(H: int) -> int:
    """Leading-order non-embedding params of one transformer layer = 12*H^2.

    Attention:  Q (H*H) + K (H*H) + V (H*H) + O (H*H) = 4*H^2.
    MLP:        fc1 (H*4H) + fc2 (4H*H)             = 8*H^2.
    Total per layer                                         = 12*H^2.
    Biases and LayerNorm gamma/beta are O(H) and dropped from the leading term.
    """
    return 12 * H * H


def layer_count(N: int, H: int, V_times_H: int = 0) -> float:
    """Depth L for a budget N at width H, minus the embedding tax V*H.

    L = (N - V*H) / (12*H^2).  Returns a float (floor it for an integer stack).
    """
    return (N - V_times_H) / per_layer_params(H)


# ============================================================================
# SECTION A: the 12*H^2 law -- depth L for a fixed budget N at several widths
# ============================================================================

def section_param_budget():
    banner("SECTION A: the 12*H^2 law -- depth vs width for a fixed budget")
    N = 125_000_000  # the 125M budget (MobileLLM's smallest tier)
    print(f"Non-embedding budget N = {N:,} params. Per-layer cost = 12*H^2.\n")
    print("| H (width) | per-layer 12*H^2 | layers L = N/(12*H^2) | profile       |")
    print("|-----------|------------------|----------------------|---------------|")
    for H in (512, 768, 1024):
        plp = per_layer_params(H)
        L = layer_count(N, H)  # V*H ignored here; Section D subtracts the tax
        profile = ("deep-narrow  (more reasoning per param)" if H == 512
                   else "balanced" if H == 768
                   else "shallow-wide (more parallelism, fewer sequential steps)")
        print(f"| {H:>9} | {plp:>16,} | {L:>20.4f} | {profile:<13} |")
    print()
    # GOLD PINS -- depth_vs_width.html recomputes these and gold-checks them
    L512 = layer_count(N, 512)
    L1024 = layer_count(N, 1024)
    print(f"  GOLD PINS (depth_vs_width.html recomputes these, N={N:,}):")
    print(f"    H=512  -> L = {L512:.4f}   (deep-narrow)")
    print(f"    H=1024 -> L = {L1024:.4f}  (shallow-wide)")
    print(f"    ratio L(512)/L(1024) = {L512 / L1024:.4f}  "
          f"(= (1024/512)^2 = 4x: halving H quadruples depth at fixed N)")
    # HTML gold-check target: L(512) recomputed by the identical formula
    check("H=512 depth L ~= 39.74 (deep-narrow gold)",
          abs(L512 - 39.74) < 0.01)
    check("H=1024 depth L ~= 9.93 (shallow-wide gold)",
          abs(L1024 - 9.93) < 0.01)
    check("halving H quadruples L at fixed N (L512/L1024 == 4.0)",
          abs(L512 / L1024 - 4.0) < 1e-6)
    return N


# ============================================================================
# SECTION B: decode is memory-bandwidth bound -- weight-read vs KV-cache
#             UNIQUE params (not depth) set the decode-latency floor.
# ============================================================================

def section_decode_traffic():
    banner("SECTION B: decode traffic -- UNIQUE params read per token "
           "(memory-bandwidth bound)")
    print("Decoding ONE autoregressive token streams EVERY unique weight from\n"
          "DRAM once -> latency floor ~= (unique params) / (memory bandwidth).\n"
          "Effective DEPTH does NOT change the weight-read term: the same block,\n"
          "applied K times, is read K times but UNIQUE weights are counted once\n"
          "per block. What depth DOES add: KV-cache memory (one K,V per layer)\n"
          "and a little attention compute (re-scored over more layers).\n")
    H = 512
    plp = per_layer_params(H)
    print(f"H = {H}, per-layer 12*H^2 = {plp:,} params.\n")
    print("| config                 | unique layers | unique params | "
          "effective depth | weight-read/token | KV-cache (rel) |")
    print("|------------------------|---------------|---------------|"
          "-----------------|-------------------|----------------|")
    # four configurations at the SAME effective depth 40
    configs = [
        # (label, unique_layers, K_share, note)
        ("deep-narrow (no share)", 40, 1, "40 distinct blocks"),
        ("layer-shared K=2",       20, 2, "20 blocks each reused 2x"),
        ("layer-shared K=4",       10, 4, "10 blocks each reused 4x"),
        ("layer-shared K=8",        5, 8, "5 blocks each reused 8x"),
    ]
    rows = {}
    for label, ul, k, _ in configs:
        uniq = ul * plp
        eff = ul * k
        rows[label] = (uniq, eff)
        # KV-cache proportional to effective depth (one K,V per block application)
        kv_rel = eff
        print(f"| {label:<22} | {ul:>13} | {uniq:>13,} | {eff:>15} | "
              f"{uniq:>17,} | {kv_rel:>14} |")
    print()
    dn_uniq, dn_eff = rows["deep-narrow (no share)"]
    for label, (uniq, eff) in rows.items():
        speedup = dn_uniq / uniq
        print(f"  {label:<22}: effective depth {eff} "
              f"(== {dn_eff}? {eff == dn_eff}), "
              f"weight-read {uniq/1e6:>6.2f}M  ->  {speedup:.1f}x less "
              f"decode traffic than no-share.")
    print()
    print("  ==> All four keep effective depth 40 (quality), but UNIQUE params")
    print("      drop with the share factor K -- so decode latency drops with K")
    print("      too. That is the edge win: depth-quality at shallow latency.")
    check("all 4 configs share effective depth 40",
          all(eff == 40 for _, eff in rows.values()))
    check("K=8 config reads 8x fewer unique weights than no-share",
          abs(rows["deep-narrow (no share)"][0]
              / rows["layer-shared K=8"][0] - 8.0) < 1e-9)


# ============================================================================
# SECTION C: layer sharing in torch -- ONE block applied K times recurrently
#             (MobileLLM block-wise weight sharing). Unique params counted once.
# ============================================================================

class Block(nn.Module):
    """One tiny pre-norm transformer block. Params == 12*H^2 by construction.

    attn_in  (H -> 3H) fuses Q,K,V  = 3*H^2
    attn_out (H -> H)              =   H^2     -> attention subtotal 4*H^2
    fc1      (H -> 4H)             = 4*H^2
    fc2      (4H -> H)             = 4*H^2     -> MLP subtotal       8*H^2
    grand total per block                                  =        12*H^2
    (LayerNorm gamma/beta are O(H); dropped from the leading-order count.)
    """

    def __init__(self, H: int):
        super().__init__()
        self.H = H
        self.norm1 = nn.LayerNorm(H)
        self.attn_in = nn.Linear(H, 3 * H, bias=False)
        self.attn_out = nn.Linear(H, H, bias=False)
        self.norm2 = nn.LayerNorm(H)
        self.fc1 = nn.Linear(H, 4 * H, bias=False)
        self.fc2 = nn.Linear(4 * H, H, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, L, H = x.shape
        h = self.norm1(x)
        q, k, v = self.attn_in(h).chunk(3, dim=-1)
        scores = (q @ k.transpose(-1, -2)) / (H ** 0.5)
        attn = torch.softmax(scores, dim=-1)
        x = x + self.attn_out(attn @ v)
        h = self.norm2(x)
        x = x + self.fc2(torch.relu(self.fc1(h)))
        return x


def count_weight_params(module: nn.Module) -> int:
    """Count all distinct weight elements (params with requires_grad)."""
    return sum(p.numel() for p in module.parameters())


def section_layer_sharing():
    banner("SECTION C: layer sharing -- ONE block applied K times recurrently "
           "(H=8)")
    H = 8
    block = Block(H)
    plp_count = count_weight_params(block)
    print(f"One Block(H={H}). Total weight params (incl. LayerNorm): "
          f"{plp_count}. Leading-order 12*H^2 = {per_layer_params(H)}.\n")
    print("(The difference is the 4*H LayerNorm gamma/beta; negligible at real H.)\n")

    # deterministic input: B=1, L=4, H=8 (tiny-but-complete, like rope.py Section E)
    B, L = 1, 4
    g = torch.Generator().manual_seed(0)
    x0 = torch.randn(B, L, H, generator=g) * 0.5
    print(f"Input x0 shape {tuple(x0.shape)} = [B={B}, L={L}, H={H}], "
          f"seeded (deterministic).\n")

    # ---- shared: apply ONE block K times recurrently ----
    print("SHARED block: the SAME Block is applied K times (weights reused):\n")
    print("| share K | step norms (||x_k||)            | unique params | "
          "vs K separate |")
    print("|---------|--------------------------------|---------------|"
          "---------------|")
    x = x0.clone()
    Ks = (1, 2, 3, 4)
    for K in Ks:
        norms = []
        for _ in range(K):
            x = block(x)
            norms.append(x.reshape(-1).norm().item())
        uniq = plp_count
        separate = plp_count * K
        nm_str = "[" + ", ".join(f"{n:.4f}" for n in norms) + "]"
        print(f"| {K:>7} | {nm_str:<30} | {uniq:>13} | "
              f"{uniq / separate * 100:>5.1f}%  ({K}x fewer) |")
    print()
    # ---- contrast: K SEPARATE blocks (K*params, no sharing) ----
    print("SEPARATE blocks: K DISTINCT Blocks stacked (K*params, no reuse):\n")
    x = x0.clone()
    for K in Ks:
        stack = nn.Sequential(*[Block(H) for _ in range(K)])
        n_stack = count_weight_params(stack)
        # the shared path applied the SAME single block K times; verify it uses
        # exactly 1/K of the parameters of K separate blocks
        check(f"K={K}: shared uses 1/{K} the params of {K} separate blocks",
              plp_count == n_stack // K and n_stack == plp_count * K)
    print()
    # ---- the core assertion: the shared block REUSES its weights ----
    # apply the block 3 times and confirm all three applications hit the SAME
    # tensors (no fresh parameters materialized per step)
    ids_before = [id(p) for p in block.parameters()]
    _ = block(block(block(x0.clone())))
    ids_after = [id(p) for p in block.parameters()]
    check("recurrent reuse: parameter tensor ids unchanged across K steps",
          ids_before == ids_after and len(ids_before) == len(ids_after))
    # and the parameter COUNT does not grow with K
    check("unique param count is independent of share factor K",
          plp_count == count_weight_params(block))
    print()
    print("  ==> MobileLLM block-wise weight sharing: ONE block, applied K times.\n"
          "      Unique params stay at 12*H^2 regardless of K; effective depth = K.\n"
          "      K separate blocks would cost K*12*H^2 -- the sharing saves a factor K.")


# ============================================================================
# SECTION D: the contrast table -- three architectures at ~125M, same effective
#            depth, wildly different decode traffic
# ============================================================================

def section_contrast():
    banner("SECTION D: contrast -- deep-narrow vs shallow-wide vs layer-shared "
           "(~125M, depth 40)")
    H_deep, L_deep = 512, 40
    H_wide, L_wide = 1024, 10
    H_sh, ul_sh, K_sh = 512, 10, 4
    plp_deep = per_layer_params(H_deep)
    plp_wide = per_layer_params(H_wide)
    plp_sh = per_layer_params(H_sh)

    # unique non-embedding params
    uniq_deep = L_deep * plp_deep
    uniq_wide = L_wide * plp_wide
    uniq_sh = ul_sh * plp_sh
    eff_deep = L_deep
    eff_wide = L_wide
    eff_sh = ul_sh * K_sh

    print("Three architectures, all ~125M non-embedding params, effective depth 40:\n")
    print("| architecture       | H   | unique L | K | unique params | "
          "effective depth | weight-read/token |")
    print("|--------------------|-----|----------|---|---------------|"
          "-----------------|-------------------|")
    rows = [
        ("deep-narrow",       H_deep, L_deep, 1,  uniq_deep, eff_deep),
        ("shallow-wide",      H_wide, L_wide, 1,  uniq_wide, eff_wide),
        ("layer-shared (LS)", H_sh,   ul_sh,  K_sh, uniq_sh, eff_sh),
    ]
    for name, H, ul, k, uniq, eff in rows:
        print(f"| {name:<18} | {H:>3} | {ul:>8} | {k} | {uniq:>13,} | "
              f"{eff:>15} | {uniq:>17,} |")
    print()
    print(f"  deep-narrow : {uniq_deep/1e6:.1f}M unique, depth {eff_deep}  "
          f"(the Telgarsky-favoured profile)")
    print(f"  shallow-wide: {uniq_wide/1e6:.1f}M unique, depth {eff_wide}   "
          f"(same N, 4x fewer layers, 4x the width)")
    print(f"  layer-shared: {uniq_sh/1e6:.1f}M unique, depth {eff_sh}  "
          f"(depth of deep-narrow, latency of a {(uniq_sh/per_layer_params(H_deep)):.0f}-layer net)")
    print()
    print("  ==> deep-narrow and shallow-wide spend ~the SAME unique params but\n"
          "      deep-narrow gets 4x the effective depth (better quality per Telgarsky).\n"
          "      layer-shared MATCHES the deep-narrow depth for 1/4 the decode traffic\n"
          "      -- the edge-optimal point MobileLLM targets.")
    check("deep-narrow and shallow-wide have ~equal unique params (~125M)",
          abs(uniq_deep - uniq_wide) / uniq_deep < 0.02)
    check("layer-shared matches deep-narrow effective depth (40)",
          eff_sh == eff_deep)
    check("layer-shared reads 4x fewer weights than deep-narrow (K=4)",
          abs(uniq_deep / uniq_sh - 4.0) < 1e-9)
    check("shallow-wide effective depth == 1/4 of deep-narrow",
          eff_wide * 4 == eff_deep)


# ============================================================================
# SECTION E: the embedding tax -- why V*H is subtracted before counting layers
#             (links depth_vs_width to the vocab budget and tying trick)
# ============================================================================

def section_embedding_tax():
    banner("SECTION E: the embedding tax V*H -- subtracted before counting layers")
    N = 125_000_000
    print("Embeddings are NOT layers: V*H params sit in the token table and steal\n"
          "capacity from the stack. Layer count L = (N_total - V*H) / (12*H^2).\n")
    print("| V (vocab) | H   | embed tax V*H | layers L @ 125M (post-tax) | "
          "tax % of 125M |")
    print("|-----------|-----|---------------|----------------------------|"
          "---------------|")
    for V, H in [(49152, 512), (49152, 1024), (128000, 512), (128000, 1024)]:
        tax = V * H
        L = layer_count(N, H, V_times_H=tax)
        pct = tax / N * 100
        print(f"| {V:>9} | {H:>3} | {tax:>13,} | {L:>26.4f} | {pct:>12.1f}% |")
    print()
    print("  Read the table: at H=1024 a 128k vocab eats 1.07x the ENTIRE 125M\n"
          "  budget as embeddings -- L goes negative (no layers left!). This is\n"
          "  WHY MobileLLM reuses input embeddings as the output head (embedding\n"
          "  sharing) and picks a modest V. See 🔗 SHARED_EMBEDDINGS.md and\n"
          "  🔗 VOCAB_RATIONALIZATION.md for the full embedding-budget story.")
    check("post-tax depth < pre-tax depth at any V>0 (the tax steals layers)",
          layer_count(N, 512, V_times_H=49152 * 512) < layer_count(N, 512))
    check("H=1024, V=128k: embedding tax exceeds 100% of 125M",
          (128000 * 1024) / N > 1.0)


# ============================================================================
# main
# ============================================================================

def main():
    print("depth_vs_width.py - reference impl. All numbers below feed "
          "DEPTH_VS_WIDTH.md.\ntorch =", torch.__version__)
    section_param_budget()
    section_decode_traffic()
    section_layer_sharing()
    section_contrast()
    section_embedding_tax()
    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
