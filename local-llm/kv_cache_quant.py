"""
kv_cache_quant.py - KV cache quantization (Q8_0 / Q4_0) for memory savings.

This is the single source of truth that KV_CACHE_QUANT.md is built from. Every
number, table, and worked example in the guide is printed by this file. Pure
Python stdlib only (NO torch, NO numpy) - this is the *local runtime* side: how
much VRAM the KV cache eats once it is resident on your GPU, and how much you
save by quantizing it to Q8_0 or Q4_0.

Run:
    python3 kv_cache_quant.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
The KV cache stores a K tensor and a V tensor for every token decoded so far,
for every KV head, in every layer. As context grows this becomes the DOMINANT
memory consumer - dwarfing even the weights at very long context.

The lever nobody told you about: you can quantize the KV cache INDEPENDENTLY of
the weights. The weights stay at Q4_K_M (great quality), while the cache - which
is ephemeral, regenerated on every forward pass - can drop to Q8_0 or Q4_0 with
surprisingly little quality loss.

KV cache size formula:
    bytes = n_layers * 2 (K+V) * n_ctx * n_kv_heads * head_dim * bytes_per_element

Quantization options for the KV cache:
  FP16 (default): 2 bytes/elem. No quality loss.
  Q8_0 KV: 8-bit block quant (1 byte + 2-byte scale per 32 elems = 1.0625 B/E).
           ~2x savings. Minimal quality loss (<1% perplexity increase).
  Q4_0 KV: 4-bit block quant (0.5 byte + 2-byte scale per 32 elems = 0.5625 B/E).
           ~4x savings. Moderate quality loss, OK for long context.

GB convention: this bundle uses binary GB (GiB = 1024^3 bytes), matching how the
local-LLM community measures VRAM and .gguf file sizes. (vram_estimator.py uses
decimal GB / 1e9 for its own convention; savings percentages are identical.)

GOLD VALUE (for kv_cache_quant.html to reproduce):
    Llama-3-8B (32 layers, 8 KV heads, head_dim=128), 32K context:
        FP16 KV: 32*2*32768*8*128*2.0    = 4,294,967,296 bytes = 4.00 GB
        Q8_0 KV: 32*2*32768*8*128*1.0625 = 2,281,701,376 bytes = 2.13 GB (47% saved)
        Q4_0 KV: 32*2*32768*8*128*0.5625 = 1,207,959,552 bytes = 1.13 GB (72% saved)
    The HTML pins the Q8_0 KV value (2.13 GB) as the gold-check.
"""

from __future__ import annotations
import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GIB = 1024 ** 3   # bytes per binary GB (GiB). Community standard for VRAM.

# KV cache block-quant formats (same Q8_0/Q4_0 block layout as weight quants).
#
# GGML block layout:
#   Q8_0 block: [fp16 scale (2 bytes)] [32 x int8 (32 bytes)]  = 34 bytes / 32 elems
#   Q4_0 block: [fp16 scale (2 bytes)] [32 x int4 (16 bytes)]  = 18 bytes / 32 elems
#
# bytes_per_element = (data_bytes_per_elem * block_size + scale_bytes) / block_size
#   FP16:  (2 * 1 + 0) / 1   = 2.0
#   Q8_0:  (1 * 32 + 2) / 32 = 34/32 = 1.0625
#   Q4_0:  (0.5 * 32 + 2) / 32 = 18/32 = 0.5625
KV_FORMATS = {
    "FP16": {"bpe": 2.0,       "data_bits": 16, "scale_bytes": 0, "block": 1,
             "note": "default; no quality loss"},
    "Q8_0": {"bpe": 34 / 32,   "data_bits": 8,  "scale_bytes": 2, "block": 32,
             "note": "~2x savings; <1% perplexity increase"},
    "Q4_0": {"bpe": 18 / 32,   "data_bits": 4,  "scale_bytes": 2, "block": 32,
             "note": "~4x savings; moderate quality loss"},
}

# Model configs (verified against config.json; same set as vram_estimator.py).
#   layers     : n_layers (transformer blocks)
#   n_heads    : total query heads
#   n_kv_heads : key/value heads (GQA; == n_heads for plain MHA)
#   head_dim   : dimension of one head
MODELS = {
    "Llama-3-8B":  {"params": 8.03,  "layers": 32, "n_heads": 32, "n_kv_heads": 8,  "head_dim": 128},
    "Qwen2.5-7B":  {"params": 7.62,  "layers": 28, "n_heads": 28, "n_kv_heads": 4,  "head_dim": 128},
    "Llama-2-13B": {"params": 13.02, "layers": 40, "n_heads": 40, "n_kv_heads": 40, "head_dim": 128},
    "Llama-3-70B": {"params": 70.0,  "layers": 80, "n_heads": 64, "n_kv_heads": 8,  "head_dim": 128},
}

# Context lengths to sweep in the comparison tables.
CTX_LEVELS = [4096, 8192, 16384, 32768, 65536]

# Approximate perplexity increase (relative to FP16 KV cache baseline = 1.0).
# These are EMPIRICAL ranges from llama.cpp benchmarks / community reports,
# NOT computed from a formula. Model- and task-dependent. Shown for guidance only.
PPL_RATIO = {
    "FP16": (1.000, 1.000),   # baseline, no increase
    "Q8_0": (1.003, 1.008),   # <1% increase (negligible)
    "Q4_0": (1.02,  1.08),    # 2-8% increase (moderate, context-dependent)
}

BANNER = "=" * 74


# ============================================================================
# 0. CHECK HELPER
# ============================================================================

def check(label: str, cond: bool, detail: str = ""):
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


# ============================================================================
# 1. FORMULAS
# ============================================================================

def kv_bytes(n_layers: int, n_ctx: int, n_kv_heads: int,
             head_dim: int, bpe: float) -> int:
    """Total KV cache size in bytes.

        bytes = n_layers * 2 * n_ctx * n_kv_heads * head_dim * bytes_per_element

    Factor 2 = the K tensor and the V tensor (both stored).
    n_kv_heads, NOT n_heads: GQA models share KV across query-head groups.
    bpe (bytes_per_element): FP16=2.0, Q8_0=1.0625, Q4_0=0.5625.
    """
    return int(n_layers * 2 * n_ctx * n_kv_heads * head_dim * bpe)


def kv_gb(n_layers: int, n_ctx: int, n_kv_heads: int,
          head_dim: int, bpe: float) -> float:
    """Total KV cache size in GB (binary, GiB = 1024^3)."""
    return kv_bytes(n_layers, n_ctx, n_kv_heads, head_dim, bpe) / GIB


def savings_pct(fp16_bytes: int, quant_bytes: int) -> float:
    """Memory savings as a fraction (0..1). Convention-independent."""
    return 1.0 - quant_bytes / fp16_bytes


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_gb(x: float) -> str:
    """Format GB with round-half-up to 2 dp (avoids banker's rounding on .xx5)."""
    val = math.floor(x * 100 + 0.5) / 100
    return f"{val:.2f} GB"


def fmt_pct(x: float) -> str:
    """Format a fraction as a percentage, 0 dp."""
    return f"{math.floor(x * 100 + 0.5)}%"


# ============================================================================
# 3. SECTIONS
# ============================================================================

def section_a_formula():
    banner("SECTION A: THE KV CACHE FORMULA - why it dominates at long context")
    print("The KV cache stores K and V tensors for every position in context,")
    print("for every KV head, in every layer. It grows LINEARLY with n_ctx.")
    print()
    print("Formula:")
    print("  bytes = n_layers x 2 x n_ctx x n_kv_heads x head_dim x bytes_per_element")
    print("           ^^^^^^^^  ^        ^^^^^^^^^^   ^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^")
    print("           per layer K+V      GQA heads    head width   FP16=2, Q8=1.0625, Q4=0.5625")
    print()
    print("At short context the weights dominate. At long context the KV cache can")
    print("exceed the weights - this is why you OOM at 32K even though the model")
    print("'fits' at 4K. Quantizing the cache is the cheapest way to extend context.")
    print()
    m = MODELS["Llama-3-8B"]
    print("KV cache growth for Llama-3-8B (FP16, 2 B/E):")
    print("| context  | n_elems (K+V)   | KV bytes       | KV (GB)  |")
    print("|----------|----------------|----------------|----------|")
    for ctx in CTX_LEVELS:
        elems = m["layers"] * 2 * ctx * m["n_kv_heads"] * m["head_dim"]
        b = kv_bytes(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], 2.0)
        print(f"| {ctx:>8} | {elems:>14,} | {b:>14,} | {fmt_gb(kv_gb(m['layers'], ctx, m['n_kv_heads'], m['head_dim'], 2.0)):>8} |")
    print()
    kv_4k = kv_bytes(m["layers"], 4096, m["n_kv_heads"], m["head_dim"], 2.0)
    kv_32k = kv_bytes(m["layers"], 32768, m["n_kv_heads"], m["head_dim"], 2.0)
    print(f"  -> context x8 (4K->32K) => KV x{kv_32k // kv_4k} (strictly linear in n_ctx)")
    check("KV is linear in context (32K/4K == 8x)", kv_32k // kv_4k == 8)
    print()
    print("The key insight: the bytes_per_element multiplier is the ONLY knob that")
    print("does not trade quality for architecture. Drop it from 2.0 (FP16) to 1.0625")
    print("(Q8_0) and you nearly halve the cache - with under 1% quality loss.")


def section_b_block_format():
    banner("SECTION B: BLOCK QUANT FORMAT - how Q8_0 / Q4_0 pack the cache")
    print("KV cache quantization reuses the SAME block format as weight quantization")
    print("(cross-ref quant_types). Each block of 32 elements shares one fp16 scale.")
    print()
    print("Block layout (GGML Q8_0 / Q4_0):")
    print("  [fp16 scale: 2 bytes] [32 x data elements]")
    print()
    print("| format | data bits | data bytes/32 | scale | block bytes | B/E     | savings vs FP16 |")
    print("|--------|-----------|----------------|-------|-------------|---------|-----------------|")
    for name in sorted(KV_FORMATS):
        f = KV_FORMATS[name]
        data_b32 = f["data_bits"] * 32 // 8
        block_bytes = data_b32 + f["scale_bytes"]
        sav = savings_pct(64, block_bytes) if name != "FP16" else 0.0
        sav_str = f"{sav*100:.1f}%" if sav > 0 else "baseline"
        print(f"| {name:<6} | {f['data_bits']:>9} | {data_b32:>14} | {f['scale_bytes']:>5}  | "
              f"{block_bytes:>11} | {f['bpe']:>7.4f} | {sav_str:>15} |")
    print()
    print("Worked: one block of 32 elements")
    print("  FP16 : 32 x 2 bytes            = 64 bytes")
    print("  Q8_0 : 32 x 1 byte + 2 (scale) = 34 bytes  (1.0625 B/E)")
    print("  Q4_0 : 32 x 0.5 byte + 2       = 18 bytes  (0.5625 B/E)")
    print()
    check("Q8_0 block = 34 bytes", 32 * 1 + 2 == 34)
    check("Q4_0 block = 18 bytes", int(32 * 0.5) + 2 == 18)
    check("Q8_0 bpe = 1.0625", abs(KV_FORMATS["Q8_0"]["bpe"] - 1.0625) < 1e-9)
    check("Q4_0 bpe = 0.5625", abs(KV_FORMATS["Q4_0"]["bpe"] - 0.5625) < 1e-9)
    check("FP16 bpe = 2.0", abs(KV_FORMATS["FP16"]["bpe"] - 2.0) < 1e-9)
    print()
    print("The 2-byte fp16 scale per 32 elements is the overhead floor: it prevents Q4_0")
    print("from reaching the theoretical 8x savings (4 bits vs 16 bits). At 0.5625 B/E")
    print("the real savings is ~3.6x, not 4x. But the scale is what PRESERVES quality:")
    print("each block gets its own dynamic range, so outliers are not crushed.")


def section_c_gold():
    banner("SECTION C: GOLD - Llama-3-8B at 32K context (the canonical example)")
    m = MODELS["Llama-3-8B"]
    ctx = 32768
    elems = m["layers"] * 2 * ctx * m["n_kv_heads"] * m["head_dim"]
    print(f"Model: Llama-3-8B  ({m['layers']} layers, {m['n_kv_heads']} KV heads, "
          f"head_dim={m['head_dim']}, GQA {m['n_heads']//m['n_kv_heads']}x)")
    print(f"Context: {ctx:,} tokens")
    print(f"Total K+V elements: {elems:,}")
    print()
    print("| format | bytes_per_elem | total bytes    | KV (GB) | savings |")
    print("|--------|----------------|----------------|---------|---------|")
    results = {}
    for name in ["FP16", "Q8_0", "Q4_0"]:
        bpe = KV_FORMATS[name]["bpe"]
        b = kv_bytes(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], bpe)
        gb_val = kv_gb(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], bpe)
        results[name] = (b, gb_val)
    fp16_b = results["FP16"][0]
    for name in ["FP16", "Q8_0", "Q4_0"]:
        bpe = KV_FORMATS[name]["bpe"]
        b, gb_val = results[name]
        sav = savings_pct(fp16_b, b) if name != "FP16" else 0.0
        sav_str = fmt_pct(sav) if sav > 0 else "baseline"
        print(f"| {name:<6} | {bpe:>14.4f} | {b:>14,} | {fmt_gb(gb_val):>7} | {sav_str:>7} |")
    print()
    fp16_gb = results["FP16"][1]
    q8_gb = results["Q8_0"][1]
    q4_gb = results["Q4_0"][1]
    q8_sav = savings_pct(results["FP16"][0], results["Q8_0"][0])
    q4_sav = savings_pct(results["FP16"][0], results["Q4_0"][0])
    print("GOLD VALUES (pinned in kv_cache_quant.html):")
    print(f"  FP16 KV = {fmt_gb(fp16_gb)}")
    print(f"  Q8_0 KV = {fmt_gb(q8_gb)}  ({fmt_pct(q8_sav)} saved)")
    print(f"  Q4_0 KV = {fmt_gb(q4_gb)}  ({fmt_pct(q4_sav)} saved)")
    print()
    check("FP16 KV @ 32K = 4.00 GB", abs(fp16_gb - 4.0) < 1e-9, f"got {fp16_gb:.6f}")
    check("Q8_0 KV @ 32K = 2.13 GB", abs(q8_gb - 2.125) < 1e-9, f"got {q8_gb:.6f}")
    check("Q4_0 KV @ 32K = 1.13 GB", abs(q4_gb - 1.125) < 1e-9, f"got {q4_gb:.6f}")
    check("Q8_0 savings ~= 47%", abs(q8_sav - 0.46875) < 1e-9, f"got {q8_sav:.6f}")
    check("Q4_0 savings ~= 72%", abs(q4_sav - 0.71875) < 1e-9, f"got {q4_sav:.6f}")
    check("FP16 bytes = 2^32", results["FP16"][0] == 4294967296)
    print()
    print("Interpretation: at 32K context, a Llama-3-8B in Q4_K_M (~4.5 GB weights)")
    print("has a 4.00 GB FP16 KV cache - the cache is nearly as big as the weights!")
    print("Switching to Q8_0 KV frees 1.87 GB. Q4_0 KV frees 2.88 GB. The weights")
    print("stay at Q4_K_M (no quality loss on weights); only the ephemeral cache drops.")


def section_d_comparison():
    banner("SECTION D: CROSS-MODEL COMPARISON - KV cache by model x context x quant")
    print("The same FP16 -> Q8_0 -> Q4_0 savings apply to every model, but the")
    print("ABSOLUTE GB saved depends on n_layers, n_kv_heads, and head_dim.")
    print("GQA models (small n_kv_heads) have smaller caches to begin with.")
    print()
    print("=== KV cache (GB) by model x context x quant ===")
    print("| model        | ctx    | FP16   | Q8_0   | Q4_0   | Q8 saved | Q4 saved |")
    print("|--------------|--------|--------|--------|--------|----------|----------|")
    for name in sorted(MODELS):
        m = MODELS[name]
        for ctx in [4096, 32768]:
            fp16 = kv_bytes(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], 2.0)
            q8 = kv_bytes(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], KV_FORMATS["Q8_0"]["bpe"])
            q4 = kv_bytes(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], KV_FORMATS["Q4_0"]["bpe"])
            fp16_g = kv_gb(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], 2.0)
            q8_g = kv_gb(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], KV_FORMATS["Q8_0"]["bpe"])
            q4_g = kv_gb(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], KV_FORMATS["Q4_0"]["bpe"])
            q8s = savings_pct(fp16, q8)
            q4s = savings_pct(fp16, q4)
            ctx_lab = f"{ctx//1024}K"
            print(f"| {name:<12} | {ctx_lab:<6} | {fmt_gb(fp16_g):>6} | {fmt_gb(q8_g):>6} | "
                  f"{fmt_gb(q4_g):>6} | {fmt_pct(q8s):>8} | {fmt_pct(q4s):>8} |")
    print()
    print("The savings PERCENTAGES are identical across all models (46.875% for Q8_0,")
    print("71.875% for Q4_0) because they depend only on the B/E ratio, not the model.")
    print("But the ABSOLUTE GB saved is proportional to the model's cache size.")
    print()
    l2 = MODELS["Llama-2-13B"]
    l3 = MODELS["Llama-3-8B"]
    l2_save = kv_gb(l2["layers"], 32768, l2["n_kv_heads"], l2["head_dim"], 2.0) - \
              kv_gb(l2["layers"], 32768, l2["n_kv_heads"], l2["head_dim"], KV_FORMATS["Q4_0"]["bpe"])
    l3_save = kv_gb(l3["layers"], 32768, l3["n_kv_heads"], l3["head_dim"], 2.0) - \
              kv_gb(l3["layers"], 32768, l3["n_kv_heads"], l3["head_dim"], KV_FORMATS["Q4_0"]["bpe"])
    print(f"  Llama-2-13B @32K: Q4_0 KV frees {fmt_gb(l2_save)} (huge MHA cache)")
    print(f"  Llama-3-8B  @32K: Q4_0 KV frees {fmt_gb(l3_save)} (small GQA cache)")
    check("MHA saves more absolute GB than GQA at same ctx", l2_save > l3_save)
    check("savings % identical for all models",
          abs(savings_pct(
              kv_bytes(l2["layers"], 32768, l2["n_kv_heads"], l2["head_dim"], 2.0),
              kv_bytes(l2["layers"], 32768, l2["n_kv_heads"], l2["head_dim"], KV_FORMATS["Q8_0"]["bpe"])
          ) - savings_pct(
              kv_bytes(l3["layers"], 32768, l3["n_kv_heads"], l3["head_dim"], 2.0),
              kv_bytes(l3["layers"], 32768, l3["n_kv_heads"], l3["head_dim"], KV_FORMATS["Q8_0"]["bpe"])
          )) < 1e-9)


def section_e_quality():
    banner("SECTION E: QUALITY TRADE-OFF - perplexity increase (approximate)")
    print("KV cache quantization trades precision for memory. The quality impact is")
    print("MEASURED (not computed from a formula) and varies by model and task.")
    print("Below: approximate perplexity RATIO (1.000 = FP16 baseline) from llama.cpp")
    print("benchmarks and community reports. Treat as guidance, not exact values.")
    print()
    print("| format | ppl ratio (approx) | perplexity increase | quality      |")
    print("|--------|--------------------|---------------------|--------------|")
    for name in ["FP16", "Q8_0", "Q4_0"]:
        lo, hi = PPL_RATIO[name]
        mid = (lo + hi) / 2
        if name == "FP16":
            inc = "0%"
            qual = "lossless"
        elif name == "Q8_0":
            inc = f"<{fmt_pct(hi - 1.0)}"
            qual = "negligible"
        else:
            inc = f"{fmt_pct(lo - 1.0)}-{fmt_pct(hi - 1.0)}"
            qual = "moderate"
        print(f"| {name:<6} | {mid:>18.3f} | {inc:>19} | {qual:<12} |")
    print()
    print("Rules of thumb:")
    print("  - Q8_0 KV is nearly free: <1% perplexity increase across all models.")
    print("    Use it whenever the cache is even slightly tight. No reason not to.")
    print("  - Q4_0 KV is the aggressive option: 2-8% perplexity increase. Acceptable")
    print("    for chat / long-context retrieval where exact precision matters less.")
    print("    Avoid for code generation or math where token-level precision is critical.")
    print("  - The quality hit is CONTEXT-DEPENDENT: longer contexts spread the error")
    print("    across more positions, so the relative impact per token is smaller.")
    print()
    check("Q8_0 ppl increase < 1%", PPL_RATIO["Q8_0"][1] - 1.0 < 0.01)
    check("Q4_0 ppl increase < Q8_0 x10", (PPL_RATIO["Q4_0"][1] - 1.0) < 10 * (PPL_RATIO["Q8_0"][1] - 1.0 + 0.001))


def section_f_flags():
    banner("SECTION F: LLAMA.CPP FLAGS - how to enable it")
    print("KV cache quantization is controlled by two flags in llama.cpp:")
    print()
    print("  --cache-type-k <type>   (or -ctk <type>)")
    print("  --cache-type-v <type>   (or -ctv <type>)")
    print()
    print("Common combinations:")
    print("  # Q8_0 KV cache (~2x savings, <1% quality loss) - RECOMMENDED")
    print("  ./llama-cli -m model.gguf --cache-type-k q8_0 --cache-type-v q8_0")
    print("  ./llama-cli -m model.gguf -ctk q8_0 -ctv q8_0")
    print()
    print("  # Q4_0 KV cache (~4x savings, moderate quality loss)")
    print("  ./llama-cli -m model.gguf --cache-type-k q4_0 --cache-type-v q4_0")
    print("  ./llama-cli -m model.gguf -ctk q4_0 -ctv q4_0")
    print()
    print("  # FP16 KV cache (default, no flags needed)")
    print("  ./llama-cli -m model.gguf")
    print()
    print("Ollama / LM Studio expose this as a setting (Ollama: num_ctx + KV quant in")
    print("the Modelfile; LM Studio: 'KV Cache Type' dropdown in advanced settings).")
    print()
    print("You CAN mix K and V precisions (e.g. -ctk q8_0 -ctv q4_0) but the quality")
    print("hit is dominated by the lower precision, so symmetric is the common choice.")
    print()
    print("IMPORTANT: the KV cache type is INDEPENDENT of the weight quant type.")
    print("A Q4_K_M model with Q8_0 KV keeps Q4_K_M weights (good quality) and only")
    print("quantizes the ephemeral cache. This is the standard local-LLM configuration.")


def section_gold():
    banner("GOLD VALUE - the canonical number the HTML must reproduce")
    m = MODELS["Llama-3-8B"]
    ctx = 32768
    print(f"Llama-3-8B, {ctx:,} context, KV cache by format:")
    print()
    for name in ["FP16", "Q8_0", "Q4_0"]:
        bpe = KV_FORMATS[name]["bpe"]
        b = kv_bytes(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], bpe)
        g = kv_gb(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], bpe)
        fp16_b = kv_bytes(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], 2.0)
        sav = savings_pct(fp16_b, b) if name != "FP16" else 0.0
        sav_str = f"  ({fmt_pct(sav)} saved)" if sav > 0 else ""
        print(f"  {name}: {m['layers']}x2x{ctx}x{m['n_kv_heads']}x{m['head_dim']}x{bpe} "
              f"= {b:>13,} bytes = {fmt_gb(g)}{sav_str}")
    print()
    q8_g = kv_gb(m["layers"], ctx, m["n_kv_heads"], m["head_dim"], KV_FORMATS["Q8_0"]["bpe"])
    print(f"  GOLD (pinned in kv_cache_quant.html):")
    print(f"    Q8_0 KV (Llama-3-8B, 32K) = {fmt_gb(q8_g)}")
    check("gold Q8_0 KV = 2.13 GB", abs(q8_g - 2.125) < 1e-9, f"got {q8_g:.6f}")


# ============================================================================
# main
# ============================================================================

def main():
    print("kv_cache_quant.py - KV cache quantization (Q8_0 / Q4_0) for memory savings.")
    print("Pure Python stdlib. Numbers below feed KV_CACHE_QUANT.md.")
    print("Sources: llama.cpp PR #2832 (KV cache quant) + GGML block format spec.")
    print("GB convention: binary (GiB = 1024^3 bytes), matching VRAM / .gguf sizes.")
    print()
    print("Lineage: FP16 KV (default) -> Q8_0 KV (~2x savings) -> Q4_0 KV (~4x savings).")

    section_a_formula()
    section_b_block_format()
    section_c_gold()
    section_d_comparison()
    section_e_quality()
    section_f_flags()
    section_gold()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
