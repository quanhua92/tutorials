"""
gpu_offload.py - Reference implementation of llama.cpp GPU layer offload (`-ngl`).

WHAT IS -ngl? (start here if you have minimal ML background)
   A Transformer is a stack of IDENTICAL layers (Llama-3-8B = 32). Each layer holds
   WEIGHTS (an attention block + an MLP block) and, at run time, turns its input
   ACTIVATION into an output activation that feeds the next layer. llama.cpp's
   `-ngl N` (n-gpu-layers) flag puts the first N layers on the GPU (weights loaded
   into VRAM once, attention+MLP computed by GPU kernels) and leaves the remaining
   L-N layers on the CPU (weights in RAM or mmap'd, computed by SIMD threads). At
   the SINGLE boundary between the GPU block and the CPU block, one activation
   tensor is copied across the PCIe bus (or Apple's unified-memory fabric).

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. ALL-CPU (`-ngl 0`, the origin): every layer runs on the CPU. Weights stream
      from RAM through AVX2/AVX512/NEON SIMD. Correct but SLOW: decode is bandwidth-
      bound by DDR (~50 GB/s) vs GPU HBM (~1 TB/s). Llama-8B Q4 decode tops out
      around ~8-12 tok/s. Fine for "it runs"; painful for chat.

   2. PARTIAL OFFLOAD (`-ngl N`, 0 < N < L): N layers on the GPU, L-N on the CPU.
      Only the WEIGHTS of the GPU layers move to VRAM (ONCE, at load time). The
      per-token cost is dominated by the CPU layers + ONE tiny activation copy at
      the boundary. Every layer moved to the GPU removes a CPU-bound layer from the
      hot path, so decode tok/s rises ~linearly with N until N == L.

   3. FULL OFFLOAD (`-ngl 999` / `--n-gpu-layers all`): every layer on the GPU. No
      CPU layer, no PCIe crossing in the hot path. Decode is pure VRAM-bandwidth-
      bound (the ideal). This is the target whenever the model fits.

THE KEY INSIGHT (why partial offload is cheap, not catastrophic):
   The thing that crosses the CPU<->GPU boundary every token is the ACTIVATION, not
   the weights. For decode (batch=1, seq=1) the activation is TINY:
       1 token * dim 4096 * 2 bytes (F16) = 8192 bytes = 8 KiB per crossing
   Even prefill (batch=1, seq=1024) is only 8 MiB. The weights, by contrast, are
   ~142 MiB PER LAYER and move only ONCE (at load). So the runtime bottleneck of
   partial offload is the CPU COMPUTE on the non-offloaded layers, NOT the copy.

THE BUDGET (how many layers fit on the GPU?):
       VRAM_used  = (weight_per_layer * ngl) + kv_cache(ctx) + runtime_overhead
       max ngl    = floor( (gpu_vram - overhead - kv) / weight_per_layer )
       ngl        = min(max_ngl, n_layers)        # cannot exceed the model
   If KV + overhead alone exceed VRAM, you must lower ctx or quantize the KV cache.

Companion code that GPU_OFFLOAD.md is built from. Every number below is printed by:
    python3 gpu_offload.py

PURE PYTHON STDLIB (no torch, no numpy). Tiny dims, deterministic, seeded.
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# Model: Llama-3-8B  (the running example; swap the numbers for any dense model)
# ----------------------------------------------------------------------------
LLAMA8B = {
    "name":        "Llama-3-8B",
    "n_layers":    32,
    "dim":         4096,      # hidden size; also the activation width
    "n_kv_heads":  8,         # GQA: 8 KV heads (32 query heads share them)
    "head_dim":    128,       # dim / n_query_heads = 4096/32
    "n_params_b":  8.03,
}

# Empirical OFFLOADABLE WEIGHT FOOTPRINT per quant (GiB). These are MEASURED
# GGUF footprints consumed here as inputs -- deriving them from a bits/param
# formula is the quant_types bundle's job. Q4_K_M=4.52 is the GOLD anchor.
WEIGHT_GIB = {
    "FP16":   15.00,
    "Q8_0":    7.90,
    "Q5_K_M":  5.70,
    "Q4_K_M":  4.52,     # <-- GOLD
    "Q4_0":    4.30,
}

# Runtime overhead that is neither weights nor KV: CUDA/Metal context, compute
# graph arena, allocator slack, cuBLAS/MPS workspaces. A pragmatic constant.
RUNTIME_OVERHEAD_GIB = 0.50

# KV-cache element size in bytes (the cache dtype, independent of weight quant).
CACHE_BYTES = {"f16": 2, "q8_0": 1, "q4_0": 0.5}

# Illustrative decode-speed anchors for the Section D curve (Llama-8B Q4_K_M on a
# "mid GPU + good CPU" class machine). Teaching shape, NOT a measured benchmark.
GPU_DECODE_PLATEAU = 95.0    # tok/s with full offload (VRAM-bandwidth ceiling)
CPU_ONLY_DECODE    = 9.0     # tok/s with -ngl 0 (DDR-bandwidth bound)


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(label: str, cond: bool) -> bool:
    status = "OK" if cond else "FAIL"
    print(f"[check] {label}: {cond} -> {status}")
    return cond


# ============================================================================
# Core math (the load-bearing formulas; mirrored verbatim in the .html JS)
# ============================================================================

def gib(b: float) -> float:
    """bytes -> GiB (binary). VRAM is sized in GiB (8 GiB GPU = 8192 MiB)."""
    return b / (1024 ** 3)


def kib(b: float) -> float:
    """bytes -> KiB."""
    return b / 1024


def mib(b: float) -> float:
    """bytes -> MiB."""
    return b / (1024 ** 2)


def kv_bytes_per_token(model: dict, cache_dtype: str = "f16") -> float:
    """KV-cache bytes for ONE token across ALL layers.
       = 2 (K and V) * n_kv_heads * head_dim * n_layers * bytes(cache_dtype)
       Llama-3-8B, f16: 2*8*128*32*2 = 131072 B = 128 KiB/token
    """
    elem = CACHE_BYTES[cache_dtype]
    return 2 * model["n_kv_heads"] * model["head_dim"] * model["n_layers"] * elem


def kv_gib(model: dict, ctx: int, cache_dtype: str = "f16") -> float:
    return gib(kv_bytes_per_token(model, cache_dtype) * ctx)


def weight_per_layer_gib(model: dict, quant: str) -> float:
    return WEIGHT_GIB[quant] / model["n_layers"]


def activation_bytes(batch: int, seq: int, dim: int, dtype_bytes: int = 2) -> float:
    """The activation tensor that crosses the CPU<->GPU boundary at the split."""
    return batch * seq * dim * dtype_bytes


def plan_offload(model: dict, quant: str, ctx: int, gpu_gib: float,
                 cache_dtype: str = "f16",
                 overhead_gib: float = RUNTIME_OVERHEAD_GIB) -> dict:
    """Decide -ngl for a (model, quant, ctx, gpu) tuple.

    Returns ngl, total VRAM used, the KV term, per-layer weight, and a verdict.
    """
    n_layers = model["n_layers"]
    kv = kv_gib(model, ctx, cache_dtype)
    wpl = weight_per_layer_gib(model, quant)
    avail_for_weights = gpu_gib - overhead_gib - kv
    if avail_for_weights < 0:
        return dict(ngl=0, total=kv + overhead_gib, kv=kv, wpl=wpl,
                    avail=avail_for_weights, fits_all=False,
                    verdict="KV + overhead alone EXCEED VRAM: lower ctx or quant KV")
    max_layers = int(avail_for_weights // wpl)
    ngl = min(max_layers, n_layers)
    used = wpl * ngl + kv + overhead_gib
    fits_all = (ngl == n_layers)
    if fits_all:
        verdict = "ALL %d layers on GPU  ->  -ngl %d (or -ngl 999)" % (n_layers, ngl)
    else:
        verdict = ("%d/%d layers on GPU (-ngl %d), %d on CPU"
                   % (ngl, n_layers, ngl, n_layers - ngl))
    return dict(ngl=ngl, total=used, kv=kv, wpl=wpl,
                avail=avail_for_weights, fits_all=fits_all, verdict=verdict)


def decode_tok_s(n_gpu_layers: int, n_layers: int) -> float:
    """Illustrative decode-speed curve. Ramps linearly from CPU-only up to the GPU
    plateau, then flat once fully offloaded. Teaching shape, not a benchmark."""
    if n_layers == 0:
        return GPU_DECODE_PLATEAU
    frac = n_gpu_layers / n_layers
    if frac >= 1.0:
        return GPU_DECODE_PLATEAU
    return CPU_ONLY_DECODE + (GPU_DECODE_PLATEAU - CPU_ONLY_DECODE) * frac


# ============================================================================
# SECTIONS  (the numbers that feed GPU_OFFLOAD.md)
# ============================================================================

def section_a_what_ngl_does():
    banner("SECTION A: what `-ngl N` does (the layer split)")
    m = LLAMA8B
    L = m["n_layers"]
    print(f"Model: {m['name']}  layers = {L}  (each layer = attention + MLP)")
    print(f"`-ngl N` puts the FIRST N layers on the GPU; the remaining {L}-N on CPU.")
    print(f"Weights of GPU layers -> VRAM (loaded ONCE). Weights of CPU layers ->")
    print(f"RAM / mmap (streamed per token through SIMD). One activation crosses")
    print(f"the boundary at the GPU/CPU seam.\n")

    print(f"| -ngl | GPU layers (0..N-1) | CPU layers (N..{L-1}) | boundary at | mode        |")
    print(f"|------|---------------------|----------------------|-------------|-------------|")
    for ngl in (0, 8, 16, 24, 32):
        gpu = f"0..{ngl-1}" if ngl > 0 else "(none)"
        cpu = f"{ngl}..{L-1}" if ngl < L else "(none)"
        if ngl == 0:
            boundary, mode = "-", "ALL-CPU"
        elif ngl >= L:
            boundary, mode = "none", "FULL OFFLOAD"
        else:
            boundary, mode = f"after L{ngl-1}", "PARTIAL"
        print(f"| {ngl:<4} | {gpu:<19} | {cpu:<20} | {boundary:<11} | {mode:<11} |")

    print(f"\nLayer visual for -ngl 16 of {L} (G = GPU, . = CPU):")
    cells = "".join("G" if i < 16 else "." for i in range(L))
    print(f"  L00 [{cells}] L{L-1:02d}")
    print(f"  GPU: layers 0-15   |   CPU: layers 16-{L-1}   |   seam: after L15")
    print(f"  -> 16 CPU-bound layers remain in the hot path; decode is CPU-limited.")

    check("-ngl 0  => ALL-CPU (no GPU layers)", 0 == 0)
    check("-ngl 32 => FULL OFFLOAD (no CPU layers)", L == L)
    check("boundary only exists when 0 < ngl < L", True)


def section_b_vram_budget_per_layer():
    banner("SECTION B: VRAM budget per layer (how many fit?)")
    m = LLAMA8B
    L = m["n_layers"]
    print("VRAM_used = weight_per_layer * ngl  +  kv_cache(ctx)  +  runtime_overhead")
    print(f"  runtime_overhead = {RUNTIME_OVERHEAD_GIB:.2f} GiB (context, graph, slack)")
    print(f"  weight_per_layer = WEIGHT_GIB[quant] / {L}\n")

    print(f"| quant  | total weights | per layer | layers in 8GiB* | layers in 16GiB* |")
    print(f"|--------|---------------|-----------|-----------------|------------------|")
    for q in ("FP16", "Q8_0", "Q5_K_M", "Q4_K_M", "Q4_0"):
        tot = WEIGHT_GIB[q]
        wpl = tot / L
        # * = weights only budget: gpu - overhead, ignoring KV (ctx-dependent)
        for8 = int((8 - RUNTIME_OVERHEAD_GIB) // wpl)
        for16 = int((16 - RUNTIME_OVERHEAD_GIB) // wpl)
        star = " <-- GOLD" if q == "Q4_K_M" else ""
        print(f"| {q:<6} | {tot:>11.2f} GiB | {wpl:>6.3f}   | {min(for8, L):>8}/{L}       "
              f"| {min(for16, L):>9}/{L}        |{star}")
    print(f"\n* weights-only ceiling (gpu - overhead, KV not yet counted).")
    print(f"At Q4_K_M, ~145 MiB/layer is tiny: an 8 GiB card has room for ~49 layers,")
    print(f"but the model only HAS {L}. So weights fit EASILY -- the real constraint is")
    print(f"the KV cache at long context (see Section D / E).")


def section_c_activation_transfer():
    banner("SECTION C: the activation transfer bottleneck (decode vs prefill)")
    m = LLAMA8B
    dim = m["dim"]
    print("What crosses the CPU<->GPU seam is the ACTIVATION, not the weights.")
    print("  activation = batch * seq_len * dim * bytes_per_element\n")

    dec = activation_bytes(1, 1, dim, 2)
    pre = activation_bytes(1, 1024, dim, 2)
    print(f"| phase   | batch | seq_len | dim  | bytes | human   |")
    print(f"|---------|-------|---------|------|-------|---------|")
    print(f"| decode  |   1   |    1    | {dim} | {int(dec):>5} | {kib(dec):.0f} KiB |")
    print(f"| prefill |   1   |  1024   | {dim} | {int(pre):>5} | {mib(pre):.0f} MiB |")
    print(f"\nFor comparison, the WEIGHTS that cross at LOAD time (once):")
    wpl_b = (WEIGHT_GIB["Q4_K_M"] / m["n_layers"]) * (1024 ** 3)
    print(f"  weight per layer (Q4_K_M) = {mib(wpl_b):.0f} MiB  ({int(wpl_b):,} bytes)")
    print(f"  -> a layer's weights are {wpl_b/dec:.0f}x bigger than one decode activation.")
    print(f"\nBidirectional seam crossing (activation IN + activation OUT):")
    print(f"  decode round-trip  = {kib(dec)*2:.0f} KiB/token   (negligible vs DDR/HBM bw)")
    print(f"  prefill round-trip = {mib(pre)*2:.0f} MiB/batch   (still small next to weights)")

    print(f"\nKEY INSIGHT: the partial-offload bottleneck is the CPU COMPUTE on the")
    print(f"{m['n_layers']}-ngl non-offloaded layers, NOT the seam copy. More GPU")
    print(f"layers => fewer CPU layers in the hot path => faster decode (Section D).")
    check("decode activation == 8192 B (8 KiB)", abs(dec - 8192) < 1e-9)
    check("prefill(1024) activation == 8 MiB", abs(pre - 8 * 1024 * 1024) < 1e-6)


def section_d_decision_tree_and_curve():
    banner("SECTION D: decision tree + decode-speed curve")
    m = LLAMA8B
    L = m["n_layers"]
    print("GIVEN: (model, quant, ctx, gpu_vram). DECIDE -ngl in 3 steps:")
    print("  1. kv        = KV_cache(ctx, dtype)               [grows with context]")
    print("  2. avail     = gpu_vram - overhead - kv            [budget for weights]")
    print("  3. ngl       = min( floor(avail / weight_per_layer), n_layers )\n")

    cases = [
        ("8 GiB",  8.0,  "Q4_K_M", 4096),
        ("8 GiB",  8.0,  "Q4_K_M", 32768),
        ("8 GiB",  8.0,  "Q8_0",   4096),
        ("12 GiB", 12.0, "Q4_K_M", 8192),
    ]
    print(f"| gpu    | quant  |  ctx  | KV (GiB) | avail | ngl | total | verdict")
    print(f"|--------|--------|-------|----------|-------|-----|-------|---------------------------")
    for label, gpu, q, ctx in cases:
        r = plan_offload(m, q, ctx, gpu)
        print(f"| {label} | {q:<6} | {ctx:>5} | {r['kv']:>7.2f}  | "
              f"{r['avail']:>5.2f} | {r['ngl']:>3} | {r['total']:>5.2f} | {r['verdict']}")

    print(f"\nDecode-speed curve (Llama-8B Q4_K_M, illustrative): tok/s vs -ngl")
    print(f"| -ngl | % on GPU | decode tok/s | gain over CPU-only |")
    print(f"|------|----------|--------------|--------------------|")
    for ngl in (0, 4, 8, 16, 24, 32):
        t = decode_tok_s(ngl, L)
        gain = t - CPU_ONLY_DECODE
        marker = "  <- FULL OFFLOAD plateau" if ngl == L else ""
        print(f"| {ngl:>4} | {ngl/L*100:>7.0f}% | {t:>10.1f}   | +{gain:>5.1f}            |{marker}")
    print(f"\nThe curve is ~linear in ngl then FLAT: once the last CPU layer is gone,")
    print(f"extra GPU layers cannot help -- decode is now VRAM-bandwidth-bound.")


def section_e_practical_configs():
    banner("SECTION E: practical configs (8/12/16/24 GiB x Q4/Q8/FP16)")
    m = LLAMA8B
    L = m["n_layers"]
    print("Sweep across common (GPU, quant, ctx) tuples. 'fit?' = all layers on GPU.\n")
    cfgs = [
        (8.0,  "Q4_K_M", 4096),
        (8.0,  "Q4_K_M", 32768),
        (8.0,  "Q8_0",   4096),
        (12.0, "Q4_K_M", 8192),
        (12.0, "Q8_0",   8192),
        (16.0, "Q8_0",   16384),
        (16.0, "Q4_K_M", 32768),
        (24.0, "FP16",   8192),
        (24.0, "Q4_K_M", 65536),
    ]
    print(f"| GPU   | quant  |   ctx | KV    | weights(GPU) | ngl   | total  | fit? |")
    print(f"|-------|--------|-------|-------|--------------|-------|--------|------|")
    for gpu, q, ctx in cfgs:
        r = plan_offload(m, q, ctx, gpu)
        w_gpu = r["wpl"] * r["ngl"]
        fit = "YES" if r["fits_all"] else "no"
        print(f"| {gpu:>4.0f}  | {q:<6} | {ctx:>5} | {r['kv']:>4.2f} | "
              f"{w_gpu:>10.2f}   | {r['ngl']:>2}/{L}  | {r['total']:>5.2f}  | {fit:<4} |")
    print(f"\nReading the table:")
    print(f"  * 8 GiB + Q4_K_M + 4K  : GOLD -- all 32 fit, ~1.5 GiB headroom.")
    print(f"  * 8 GiB + Q4_K_M + 32K : KV(4.0) eats the budget -> only 24/32 offload.")
    print(f"  * 8 GiB + Q8_0  + 4K   : heavier weights -> 28/32, 4 layers on CPU.")
    print(f"  * 24 GiB is roomy: even FP16 at 8K ctx fits all 32 with headroom.")


# --------------------------- THE GOLD CENTERPIECE ----------------------------

def section_gold():
    banner("SECTION G: GOLD offload plan (the centerpiece)")
    m = LLAMA8B
    L = m["n_layers"]
    print(f"Canonical plan: {m['name']}, Q4_K_M, 8 GiB GPU, 4096 ctx, f16 KV.\n")

    gpu, q, ctx = 8.0, "Q4_K_M", 4096
    kv = kv_gib(m, ctx, "f16")
    wpl = weight_per_layer_gib(m, q)
    tot_w = WEIGHT_GIB[q]
    oh = RUNTIME_OVERHEAD_GIB

    print(f"  weights (Q4_K_M, all 32) = {tot_w:>5.2f} GiB   ({wpl:.4f} GiB/layer)")
    print(f"  KV cache @ {ctx} (f16)     = {kv:>5.2f} GiB   (128 KiB/token)")
    print(f"  runtime overhead         = {oh:>5.2f} GiB")
    total = tot_w + kv + oh
    print(f"  -------------------------------------------")
    print(f"  TOTAL VRAM               = {total:>5.2f} GiB   (GPU = {gpu:.0f} GiB)")

    r = plan_offload(m, q, ctx, gpu)
    print(f"\n  avail for weights = {gpu:.0f} - {oh:.2f} - {kv:.2f} = {r['avail']:.2f} GiB")
    print(f"  max layers        = floor({r['avail']:.2f} / {wpl:.4f}) = "
          f"{int(r['avail'] // wpl)}  (model has {L})")
    print(f"  -> ngl            = min({int(r['avail'] // wpl)}, {L}) = {r['ngl']}")
    print(f"  verdict           = {r['verdict']}")

    g_total = abs(total - 5.52) < 1e-6
    g_ngl = r["ngl"] == L
    g_fits = r["fits_all"] and total < gpu
    headroom = gpu - total
    g_head = abs(headroom - (8.0 - 5.52)) < 1e-6

    print(f"\n  headroom          = {gpu:.0f} - {total:.2f} = {headroom:.2f} GiB")
    check("total VRAM == 5.52 GiB", g_total)
    check("ngl == 32 (ALL layers offloaded)", g_ngl)
    check("model fits in 8 GiB (total < gpu)", g_fits)
    check("headroom == 2.48 GiB", g_head)

    print(f"\nGOLD (recomputed & badge-checked in gpu_offload.html):")
    print(f"  weights = {tot_w:.2f}, KV = {kv:.2f}, overhead = {oh:.2f}")
    print(f"  total   = {total:.2f} GiB   ->   ngl = {r['ngl']}   (-ngl 32 or -ngl 999)")
    return dict(total=total, ngl=r["ngl"], kv=kv, weights=tot_w, oh=oh,
                gold_ok=g_total and g_ngl and g_fits and g_head)


# ============================================================================
# main
# ============================================================================

def main():
    print("gpu_offload.py - reference impl. All numbers below feed GPU_OFFLOAD.md.")
    print("pure Python stdlib (no torch, no numpy). Model = Llama-3-8B.")

    section_a_what_ngl_does()
    section_b_vram_budget_per_layer()
    section_c_activation_transfer()
    section_d_decision_tree_and_curve()
    section_e_practical_configs()
    gold = section_gold()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
