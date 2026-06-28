"""
vram_estimator.py - Reference implementation of the LLM-inference VRAM budget.

This is the single source of truth that VRAM_ESTIMATOR.md is built from. Every
number, table, and worked example in VRAM_ESTIMATOR.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy) - this is the *local runtime* side
(how big a .gguf is once it is resident on your GPU), not the engine internals
of llm/kv_cache.py.

Run:
    python3 vram_estimator.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
"Will this model fit on my GPU?" is a sum of exactly three terms:

    VRAM = WEIGHTS + KV_CACHE + OVERHEAD

LINEAGE (rule-of-thumb -> exact):

  RULE OF THUMB (old):
    model_size_GB ~= params_in_billions * bits_per_weight / 8
    e.g. a "7B Q4" model is roughly 7 * 4 / 8 = 3.5 GB.
    Good for a 5-second guess, but it IGNORES context. A 7B at 3.5 GB of
    weights balloons to 8+ GB once you actually decode 32k tokens, because the
    KV cache grows LINEARLY with context length. The rule of thumb silently
    under-counts the real budget on long contexts.

  EXACT FORMULA (this file):
    weights    = params * bpw / 8                          (bytes/1e9 -> GB)
    kv_cache   = n_layers * 2 * n_ctx * n_kv_heads * head_dim * bpe / 1e9
    overhead   = max(0.5, 0.10 * weights)                  GB
    total      = weights + kv_cache + overhead

  Why each term:
    WEIGHTS    - the .gguf file itself, once resident. Dominated by bits/weight
                 (the quant type). Cross-ref QUANT_TYPES.md.
    KV_CACHE   - one K and one V tensor PER LAYER, sized by the number of tokens
                 decoded so far (n_ctx). The factor 2 = K+V. GQA models use
                 n_kv_heads (small), NOT n_heads, so their cache is far smaller
                 than a plain multi-head model of the same size. Cross-ref
                 llm/KV_CACHE.py and kv_cache_quant.
    OVERHEAD   - context buffers, compute workspace, CUDA/Metal launch state,
                 activations. Roughly a 0.5 GB floor or ~10% of weights, whichever
                 is larger. The least-deterministic term; tune up if you OOM.

GOLD VALUE (for VRAM_ESTIMATOR.html to reproduce):
    Llama-3-8B, Q4_K_M (4.5 bpw), 4096 context, FP16 KV:
        weights = 8.03 * 4.5 / 8                = 4.516875 GB  (~4.52 GB)
        kv      = 32*2*4096*8*128*2 / 1e9       = 0.536871 GB
        over    = max(0.5, 0.10*4.516875)       = 0.500000 GB
        total                                       = 5.553746 GB  (~5.55 GB)
    The HTML pins the WEIGHTS term (4.52 GB) as the gold-check.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Bits-per-weight for the quant types we estimate (see QUANT_TYPES.md).
# NOTE: Q4_K_M is quoted as ~4.84 bpw at the *model* level (mixed layer types),
# but for VRAM rule-of-thumb estimation we use the pure-Q4_K block bpw of 4.5.
# The exact on-disk size is always model.gguf file size; this is an estimate.
# ---------------------------------------------------------------------------
BPW = {
    "Q4_K_M": 4.5,   # rule-of-thumb bpw (pure Q4_K block; real _M is ~4.84)
    "Q8_0":   8.5,   # near-lossless int8 + fp16 scale per 32-weight block
    "FP16":   16.0,  # unquantized half precision, 2 bytes/weight
}

# Bytes-per-element of the KV cache tensor (the precision the cache is stored in).
KV_BPE = {
    "FP16": 2,   # 2 bytes per K/V element (the llama.cpp default)
    "Q8":   1,   # quantizing the KV cache to Q8_0 halves it (see kv_cache_quant)
}

# ---------------------------------------------------------------------------
# Hardcoded model configs (verified against each model's config.json).
#   params     : parameter count in BILLIONS (e.g. 8.03 = 8.03e9)
#   layers     : n_layers (transformer blocks)
#   n_heads    : total query heads
#   n_kv_heads : key/value heads (GQA; == n_heads for plain multi-head attention)
#   head_dim   : dimension of one head (== dim / n_heads)
# ---------------------------------------------------------------------------
MODELS = {
    # The reference / gold model. GQA: 32 query heads, only 8 KV heads -> 4x cache cut.
    "Llama-3-8B":   {"params": 8.03,  "layers": 32, "n_heads": 32, "n_kv_heads": 8,  "head_dim": 128, "dim": 4096},
    # Strong GQA: 28 query heads, 4 KV heads -> 7x cache cut. Small but long-context.
    "Qwen2.5-7B":   {"params": 7.62,  "layers": 28, "n_heads": 28, "n_kv_heads": 4,  "head_dim": 128, "dim": 3584},
    # Plain multi-head attention: n_kv_heads == n_heads (no GQA). Contrast cache size.
    "Llama-2-13B":  {"params": 13.02, "layers": 40, "n_heads": 40, "n_kv_heads": 40, "head_dim": 128, "dim": 5120},
    # Heavy GQA: 64 query heads, only 8 KV heads -> 8x cache cut. Big model, modest cache.
    "Llama-3-70B":  {"params": 70.0,  "layers": 80, "n_heads": 64, "n_kv_heads": 8,  "head_dim": 128, "dim": 8192},
}

# Common consumer/prosumer GPUs by VRAM (nominal; real usable ~90% after OS/CUDA ctx).
GPUS = [8, 12, 16, 24]

BANNER = "=" * 74


# ============================================================================
# 0. CHECK HELPER (invariants the formulas must satisfy)
# ============================================================================

def check(label: str, cond: bool, detail: str = ""):
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


# ============================================================================
# 1. THE THREE TERMS (the exact formula, term by term)
# ============================================================================

def model_weights_gb(params_b: float, bpw: float) -> float:
    """Weights term: params * bits_per_weight / 8  (in GB, decimal).

    The 1e9 from params and the 1e9 to bytes->GB cancel, so:
        weights_GB = params_in_billions * bpw / 8
    This is the size of the resident .gguf weights (the dominant term).
    """
    return params_b * bpw / 8.0


def kv_cache_gb(n_layers: int, n_ctx: int, n_kv_heads: int,
                head_dim: int, bpe: int) -> float:
    """KV cache term (in GB, decimal).

        bytes = n_layers * 2 * n_ctx * n_kv_heads * head_dim * bytes_per_element
        GB    = bytes / 1e9

    Factor 2 = the K tensor and the V tensor (both stored).
    n_kv_heads, NOT n_heads: GQA models share KV across query-head groups, so the
    cache scales with the (small) KV head count, not the (large) query head count.
    """
    bytes_total = n_layers * 2 * n_ctx * n_kv_heads * head_dim * bpe
    return bytes_total / 1e9


def overhead_gb(weights_gb: float) -> float:
    """Overhead term (in GB): context buffers + compute workspace + activations.

    Modeled as a 0.5 GB floor OR ~10% of weights, whichever is larger. The least
    exact term - if you OOM at the edge, bump this (or quantize the KV cache).
    """
    return max(0.5, 0.10 * weights_gb)


def total_vram_gb(params_b: float, bpw: float,
                  n_layers: int, n_ctx: int, n_kv_heads: int,
                  head_dim: int, kv_bpe: int = 2) -> tuple[float, float, float, float]:
    """Full VRAM budget. Returns (weights, kv, overhead, total) in GB."""
    w = model_weights_gb(params_b, bpw)
    k = kv_cache_gb(n_layers, n_ctx, n_kv_heads, head_dim, kv_bpe)
    o = overhead_gb(w)
    return w, k, o, w + k + o


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def gb(x: float) -> str:
    """Format GB with 2 decimals + the unit."""
    return f"{x:>6.2f} GB"


# ============================================================================
# 3. SECTIONS
# ============================================================================

def section_a_weights():
    banner("SECTION A: WEIGHTS term - params x bpw / 8 (the dominant cost)")
    print("The weights term is the size of the resident .gguf tensors. It dwarfs")
    print("everything else at short context and is set ENTIRELY by the quant type.")
    print()
    print("Formula (the rule of thumb, made exact):")
    print("  weights_GB = params_in_billions * bits_per_weight / 8")
    print("  (the 1e9 from params and the 1e9 bytes->GB cancel)")
    print()
    print("bpw per quant type (cross-ref QUANT_TYPES.md):")
    print("| quant   | bpw  | bytes/weight | note                              |")
    print("|---------|------|--------------|-----------------------------------|")
    for name, bpw in sorted(BPW.items()):
        print(f"| {name:<7} | {bpw:>4.1f} | {bpw/8:>12.4f} | "
              f"{'rule-of-thumb (pure Q4_K block)' if name=='Q4_K_M' else ''}"
              f"{'near-lossless int8 block' if name=='Q8_0' else ''}"
              f"{'unquantized half precision' if name=='FP16' else ''}".rstrip())
    print()
    print("Worked: Llama-3-8B (8.03B params) across the three quants:")
    print("| quant   | params | bpw  | weights_GB |")
    print("|---------|--------|------|------------|")
    p = MODELS["Llama-3-8B"]["params"]
    for name, bpw in sorted(BPW.items()):
        w = model_weights_gb(p, bpw)
        print(f"| {name:<7} | {p:>6.2f} | {bpw:>4.1f} | {w:>10.4f} |")
    print()
    gold_w = model_weights_gb(8.03, 4.5)
    print("GOLD (for VRAM_ESTIMATOR.html):")
    print(f"  Llama-3-8B Q4_K_M weights = 8.03 * 4.5 / 8 = {gold_w:.6f} GB  (~4.52 GB)")
    check("Q4_K_M weights ~= 4.52 GB", abs(gold_w - 4.516875) < 1e-6,
          f"got {gold_w:.6f}")
    check("FP16 is ~2x Q8_0 weights",
          abs(model_weights_gb(p, 16.0) / model_weights_gb(p, 8.5) - 16.0/8.5) < 1e-9)
    print()
    print("The quant type is the single biggest lever on the weights term (and")
    print("hence on the whole budget at short context). Cutting 16->4.5 bpw shrinks")
    print("the resident weights ~3.5x with modest quality loss (see QUANT_TYPES.md).")


def section_b_kv_cache():
    banner("SECTION B: KV CACHE term - the part that scales with context")
    print("The KV cache stores, for every token decoded so far, the K and V vectors")
    print("of every KV head in every layer. It grows LINEARLY with n_ctx, which is")
    print("why long-context models eat VRAM that the rule-of-thumb never predicted.")
    print()
    print("Formula:")
    print("  bytes = n_layers * 2 * n_ctx * n_kv_heads * head_dim * bytes_per_element")
    print("           ^^^^^^^^  ^        ^^^^^^^^^^   ^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^")
    print("           per layer K+V      GQA heads    head width   FP16=2, Q8=1")
    print("  GB    = bytes / 1e9")
    print()
    print("Worked: Llama-3-8B (32 layers, 8 KV heads, head_dim=128), FP16 KV (2 B/E):")
    m = MODELS["Llama-3-8B"]
    print(f"  @   4096 ctx: 32*2*4096*8*128*2   = "
          f"{32*2*4096*8*128*2:>13,} bytes = {kv_cache_gb(m['layers'],4096,m['n_kv_heads'],m['head_dim'],2):.6f} GB")
    print(f"  @  32768 ctx: 32*2*32768*8*128*2  = "
          f"{32*2*32768*8*128*2:>13,} bytes = {kv_cache_gb(m['layers'],32768,m['n_kv_heads'],m['head_dim'],2):.6f} GB")
    kv4 = kv_cache_gb(m['layers'], 4096, m['n_kv_heads'], m['head_dim'], 2)
    kv32 = kv_cache_gb(m['layers'], 32768, m['n_kv_heads'], m['head_dim'], 2)
    print(f"  -> context x8 (4k->32k) => KV x{kv32/kv4:.1f} (strictly linear in n_ctx)")
    print()
    print("GQA is the multiplier that decides HOW FAST the cache grows. Compare the")
    print("KV head ratio (n_heads / n_kv_heads) for each model:")
    print("| model        | n_heads | n_kv_heads | GQA ratio | KV@4K (FP16) | KV@32K (FP16) |")
    print("|--------------|---------|------------|-----------|--------------|---------------|")
    for name in sorted(MODELS):
        mc = MODELS[name]
        row_kv4 = kv_cache_gb(mc['layers'], 4096, mc['n_kv_heads'], mc['head_dim'], 2)
        row_kv32 = kv_cache_gb(mc['layers'], 32768, mc['n_kv_heads'], mc['head_dim'], 2)
        ratio = mc['n_heads'] / mc['n_kv_heads']
        print(f"| {name:<12} | {mc['n_heads']:>7} | {mc['n_kv_heads']:>10} | "
              f"{ratio:>6.1f}x   | {row_kv4:>10.4f} GB | {row_kv32:>11.4f} GB |")
    print()
    print("Llama-2-13B uses plain multi-head attention (ratio 1x) so its KV cache is")
    print("HUGE relative to its size - 13B MHA caches more than 70B GQA at the same ctx.")
    l2 = MODELS["Llama-2-13B"]
    l3 = MODELS["Llama-3-70B"]
    kv_l2 = kv_cache_gb(l2['layers'], 32768, l2['n_kv_heads'], l2['head_dim'], 2)
    kv_l3 = kv_cache_gb(l3['layers'], 32768, l3['n_kv_heads'], l3['head_dim'], 2)
    print(f"  Llama-2-13B @32K FP16 KV = {kv_l2:.3f} GB   vs   Llama-3-70B @32K FP16 KV = {kv_l3:.3f} GB")
    check("70B GQA KV < 13B MHA KV at 32K", kv_l3 < kv_l2,
          f"70B={kv_l3:.3f} vs 13B={kv_l2:.3f}")
    check("KV is linear in context (32K/4K == 8x)",
          abs(kv32 / kv4 - 8.0) < 1e-9)
    print()
    print("KV-cache quantization (Q8, 1 B/E) HALVES this term. Cross-ref kv_cache_quant.")
    kv32_q8 = kv_cache_gb(m['layers'], 32768, m['n_kv_heads'], m['head_dim'], 1)
    print(f"  Llama-3-8B @32K: FP16 KV = {kv32:.3f} GB, Q8 KV = {kv32_q8:.3f} GB (-50%)")


def section_c_overhead():
    banner("SECTION C: OVERHEAD term - context buffers + compute workspace")
    print("The third term is everything that is neither weights nor KV: activations,")
    print("the compute workspace (scratch buffers for the matmuls / attention), the")
    print("CUDA/Metal context, and OS/display reservation on consumer cards.")
    print()
    print("Formula (the least-exact term - it is a rule of thumb):")
    print("  overhead_GB = max(0.5, 0.10 * weights_GB)")
    print("  (a ~0.5 GB floor for small models, ~10% of weights for large ones)")
    print()
    print("| model        | quant   | weights_GB | 10%    | overhead_GB |")
    print("|--------------|---------|------------|--------|-------------|")
    for name in sorted(MODELS):
        p = MODELS[name]["params"]
        for qname, bpw in sorted(BPW.items()):
            w = model_weights_gb(p, bpw)
            o = overhead_gb(w)
            src = "floor" if o == 0.5 else "10%"
            print(f"| {name:<12} | {qname:<7} | {w:>10.4f} | {0.10*w:>6.3f} | "
                  f"{o:>9.4f}  ({src}) |")
    print()
    print("Why a FLOOR: even a tiny model needs context buffers + a CUDA/Metal")
    print("context (~0.3-0.5 GB). Why a PERCENTAGE: activation + workspace tensors")
    print("scale with the matmul sizes, which scale with the weights.")
    print()
    print("If you OOM right at the edge, the overhead term is the first place to")
    print("blame: quantize the KV cache, drop --parallel-context / batch size, or add")
    print("a few hundred MB of slack to this estimate.")


def section_d_comparison():
    banner("SECTION D: COMPARISON TABLE - the full VRAM budget at a glance")
    print("Every (model, quant, context) combo, broken into the three terms.")
    print("Weights shrink with the quant; KV is fixed by model+ctx; overhead floats.")
    print()
    for ctx_label, ctx in [("4096 ctx (short)", 4096), ("32768 ctx (long)", 32768)]:
        print(f"=== {ctx_label}  (FP16 KV, 2 B/E) ===")
        print("| model        | quant   | weights | KV     | overhd | TOTAL  |")
        print("|--------------|---------|---------|--------|--------|--------|")
        for name in sorted(MODELS):
            m = MODELS[name]
            kv = kv_cache_gb(m['layers'], ctx, m['n_kv_heads'], m['head_dim'], 2)
            for qname, bpw in sorted(BPW.items()):
                w = model_weights_gb(m['params'], bpw)
                o = overhead_gb(w)
                tot = w + kv + o
                print(f"| {name:<12} | {qname:<7} | {w:>6.2f}GB | {kv:>5.2f}GB | "
                      f"{o:>5.2f}GB | {tot:>5.2f}GB |")
        print()
    print("Read the table downward: quantizing 16->4.5 bpw cuts the TOTAL at 4K ctx")
    print("by ~3.5x, but at 32K ctx the (quant-invariant) KV term limits the win.")
    l3 = MODELS["Llama-3-8B"]
    fp16_4k = total_vram_gb(l3['params'], 16.0, l3['layers'], 4096,
                            l3['n_kv_heads'], l3['head_dim'])[3]
    q4_4k = total_vram_gb(l3['params'], 4.5, l3['layers'], 4096,
                          l3['n_kv_heads'], l3['head_dim'])[3]
    fp16_32k = total_vram_gb(l3['params'], 16.0, l3['layers'], 32768,
                             l3['n_kv_heads'], l3['head_dim'])[3]
    q4_32k = total_vram_gb(l3['params'], 4.5, l3['layers'], 32768,
                           l3['n_kv_heads'], l3['head_dim'])[3]
    print(f"  Llama-3-8B: FP16->Q4_K_M saves {fp16_4k-q4_4k:.2f} GB at 4K, "
          f"but only {fp16_32k-q4_32k:.2f} GB at 32K (KV term is fixed).")
    check("quantization saves more at short ctx than long ctx",
          (fp16_4k - q4_4k) > (fp16_32k - q4_32k))


def section_e_decision():
    banner("SECTION E: 'WILL IT FIT?' - decision matrix vs common GPUs")
    print("For Q4_K_M (the default local quant), does each (model, context) fit on a")
    print("given GPU? A check means TOTAL VRAM <= nominal GPU VRAM. Real usable VRAM")
    print("is ~90% of nominal (OS/display + CUDA context); leave headroom.")
    print()
    gpu_hdr = " | ".join(f"{g}GB" for g in GPUS)
    print(f"| model        | ctx    | total(Q4_K_M) | {gpu_hdr} |")
    print("|--------------|--------|---------------|" + "|".join(["--------"] * len(GPUS)) + "|")
    for name in sorted(MODELS):
        m = MODELS[name]
        for ctx_label, ctx in [("4K", 4096), ("32K", 32768)]:
            _, _, _, tot = total_vram_gb(m['params'], 4.5, m['layers'], ctx,
                                         m['n_kv_heads'], m['head_dim'])
            marks = "   |   ".join(
                " FIT " if tot <= g else "  no " for g in GPUS)
            print(f"| {name:<12} | {ctx_label:<6} | {tot:>11.2f} GB |  {marks}  |")
    print()
    print("Reading the matrix:")
    l3 = MODELS["Llama-3-8B"]
    t4 = total_vram_gb(l3['params'], 4.5, l3['layers'], 4096,
                       l3['n_kv_heads'], l3['head_dim'])[3]
    t32 = total_vram_gb(l3['params'], 4.5, l3['layers'], 32768,
                        l3['n_kv_heads'], l3['head_dim'])[3]
    print(f"  - Llama-3-8B Q4_K_M @4K  = {t4:.2f} GB -> fits an 8GB card (barely).")
    print(f"  - Llama-3-8B Q4_K_M @32K = {t32:.2f} GB -> needs 12GB+ (KV dominates).")
    print(f"  - Llama-3-70B Q4_K_M @4K = "
          f"{total_vram_gb(MODELS['Llama-3-70B']['params'],4.5,MODELS['Llama-3-70B']['layers'],4096,MODELS['Llama-3-70B']['n_kv_heads'],MODELS['Llama-3-70B']['head_dim'])[3]:.2f} GB"
          f" -> needs 2x24GB or CPU offload (see gpu_offload).")
    check("Llama-3-8B Q4_K_M @4K fits 8GB", t4 <= 8, f"total={t4:.2f}")
    check("Llama-3-8B Q4_K_M @32K does NOT fit 8GB", t32 > 8, f"total={t32:.2f}")
    check("Llama-3-8B Q4_K_M @32K fits 12GB", t32 <= 12, f"total={t32:.2f}")
    check("Llama-3-70B Q4_K_M @4K does NOT fit 24GB",
          total_vram_gb(MODELS['Llama-3-70B']['params'],4.5,MODELS['Llama-3-70B']['layers'],4096,MODELS['Llama-3-70B']['n_kv_heads'],MODELS['Llama-3-70B']['head_dim'])[3] > 24)


def section_gold():
    banner("GOLD VALUE - the canonical number the HTML must reproduce")
    m = MODELS["Llama-3-8B"]
    w, k, o, t = total_vram_gb(m['params'], 4.5, m['layers'], 4096,
                               m['n_kv_heads'], m['head_dim'], 2)
    print("Llama-3-8B, Q4_K_M (4.5 bpw), 4096 context, FP16 KV:")
    print(f"  weights  = 8.03 * 4.5 / 8                  = {w:.6f} GB")
    print(f"  kv_cache = 32*2*4096*8*128*2 / 1e9         = {k:.6f} GB")
    print(f"  overhead = max(0.5, 0.10*{w:.4f})            = {o:.6f} GB")
    print(f"  TOTAL                                       = {t:.6f} GB")
    print()
    print(f"  GOLD (pinned in VRAM_ESTIMATOR.html):")
    print(f"    weights(Llama-3-8B, Q4_K_M) = {w:.2f} GB   (to 2 dp)")
    print(f"    total (Llama-3-8B, Q4_K_M, 4K) = {t:.2f} GB   (to 2 dp)")
    check("gold weights ~= 4.52 GB", abs(w - 4.516875) < 1e-6)
    check("gold total > 5 and < 6 GB", 5.0 < t < 6.0, f"total={t:.4f}")


# ============================================================================
# main
# ============================================================================

def main():
    print("vram_estimator.py - LLM-inference VRAM budget (weights + KV cache + overhead).")
    print("Pure Python stdlib. Numbers below feed VRAM_ESTIMATOR.md.")
    print("Sources: llama.cpp memory math + the per-model config.json head/layer counts.")
    print()
    print("Lineage: rule-of-thumb (params*B/8) -> exact (weights + KV + overhead).")

    section_a_weights()
    section_b_kv_cache()
    section_c_overhead()
    section_d_comparison()
    section_e_decision()
    section_gold()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
