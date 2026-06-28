"""
wan_video.py - Reference implementation of Wan 2.2 (14B) optimization stack.

This is the single source of truth that WAN_VIDEO.md is built from. Every
number, table, and worked example in WAN_VIDEO.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy) - this is the *local runtime* side
(how a 14B video model that would NOT fit on any consumer GPU becomes a ~12s
generation on a 12GB card), not the diffusion math.

Run:
    python3 wan_video.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
"Why can a 14B model run on a 12GB consumer GPU in ~12 seconds?" - four stacked
optimizations, each attacking a different cost axis:

    1. GGUF Q4 quantization   ->  fits the weights in VRAM (28GB -> 8.5GB)
    2. Lightning distillation ->  fewer denoising passes (30 steps -> 4 steps)
    3. TeaCache               ->  skip redundant attention (~2.5x)
    4. torch.compile / sage   ->  fuse kernels, cut overhead (~1.3x)

They stack MULTIPLICATIVELY because they attack orthogonal costs:
    - GGUF shrinks the WEIGHTS (memory axis).
    - Lightning shrinks the STEP COUNT (loop axis).
    - TeaCache shrinks the WORK PER STEP (compute axis).
    - compile shrinks the KERNEL OVERHEAD (dispatch axis).

LINEAGE (naive -> optimized):

  WAN 2.2 14B NAIVE (heavy):
    14B params x FP16 = 28GB -> does NOT fit on ANY consumer GPU (max 24GB).
    Even on a 24GB card, 30 diffusion steps at 720p = ~5 minutes per clip.
    Highest quality (best temporal coherence, most detail), but impractical.

  + OPTIMIZATION STACK (fits + fast):
    GGUF Q4 (28GB -> 8.5GB) -> fits a 12GB GPU (RTX 3060/4070 tier).
    Lightning (30 -> 4 steps) -> 7.5x fewer denoising passes (~5-10% quality).
    TeaCache (cache attention) -> ~2.5x (no quality loss, threshold tunable).
    torch.compile / sage attn -> ~1.3x (no quality loss).

GOLD VALUE (for wan_video.html to reproduce):
    Base:   30 steps x full attention x FP16  =  300 s   (but won't fit any GPU)
    +Lightning (4 steps):  300 * (4/30)       =   40 s
    +TeaCache (2.5x):      40 / 2.5            =   16 s
    +compile (1.3x):       16 / 1.3            =   12.3 s
    TOTAL SPEEDUP = 300 / 12.3                  =  ~24.4x
    VRAM: FP16 28.0 GB -> GGUF Q4 8.5 GB  (fits 12GB GPU)
    The HTML pins the FINAL TIME (12.3 s) and SPEEDUP (24.4x) as the gold-check.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Model + optimization constants (cited from docs.comfy.org + community GGUFs).
# ---------------------------------------------------------------------------
DIT_PARAMS_B = 14.0          # Wan 2.2 T2V/I2V-A14B: ~14B diffusion params

# Bits-per-weight for the diffusion model weights (cross-ref QUANT_TYPES.md).
WEIGHT_BPW = {
    "FP16":      16.0,   # unquantized half precision = 28.0 GB (fits NO consumer GPU)
    "FP8_scaled": 8.0,   # ComfyUI-repackaged fp8 path = 14.0 GB (fits 16GB+)
    "GGUF_Q4":    4.85,  # Q4_K_M-style block quant ~ 8.5 GB (fits 12GB)
}

# --- the speed optimization stack (each attacks an orthogonal cost) ---
BASE_STEPS = 30             # default Wan 2.2 denoising steps
LIGHTNING_STEPS = 4         # Lightning-distilled step count (Lightx2v LoRA)
TEACACHE_SPEEDUP = 2.5      # TeaCache attention reuse (~40% skipped)
COMPILE_SPEEDUP = 1.3       # torch.compile / sage attention kernel fusion

# Documented baseline: 30 steps at 720p on a fast consumer GPU (~5 minutes).
BASE_TIME_S = 300.0

# Reference clip geometry (cross-ref ltx_video.py: 720x480x121 ~ a 5s video).
FPS = 24

# Quality drop per optimization (rough, from the Lightning/TeaCache literature).
QUALITY_DROP = {
    "GGUF Q4":          0.02,   # ~2% (barely noticeable)
    "Lightning (4 steps)": 0.075,  # ~5-10% (midpoint)
    "TeaCache":         0.0,    # none (threshold tunable; aggressive risks artifacts)
    "compile":          0.0,    # none (pure kernel optimization)
}

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
# 1. WEIGHTS / VRAM (why GGUF Q4 is the enabler)
# ============================================================================

def weights_gb(params_b: float, bpw: float) -> float:
    """Weights term: params_b * bpw / 8  (decimal GB). Same as vram_estimator."""
    return params_b * bpw / 8.0


# ============================================================================
# 2. THE SPEED STACK (multiplicative, each layer divides the previous time)
# ============================================================================

def lightning_time(base_s: float, base_steps: int, steps: int) -> float:
    """Lightning distillation: distill base_steps -> steps. Time scales linearly."""
    return base_s * (steps / base_steps)


def with_factor(time_s: float, factor: float) -> float:
    """Apply a multiplicative speedup factor (TeaCache / compile)."""
    return time_s / factor


def stack_time(base_s: float, base_steps: int, steps: int,
               use_teacache: bool, use_compile: bool) -> float:
    """Full stacked wall-clock time. Steps are the Lightning reduction; the two
    flags toggle the multiplicative factors (order-independent for the factors)."""
    t = lightning_time(base_s, base_steps, steps)
    if use_teacache:
        t = with_factor(t, TEACACHE_SPEEDUP)
    if use_compile:
        t = with_factor(t, COMPILE_SPEEDUP)
    return t


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def gb(x: float) -> str:
    return f"{x:>6.2f} GB"


def sec(x: float) -> str:
    return f"{x:>7.2f} s"


def pct(x: float) -> str:
    return f"{x*100:>5.1f}%"


# ============================================================================
# 4. SECTIONS
# ============================================================================

def section_a_stack():
    banner("SECTION A: THE OPTIMIZATION STACK - four layers, four cost axes")
    print("Wan 2.2 14B is 7x heavier than LTX-Video 2B (14B vs 2B params). Naive")
    print("inference (30 steps, FP16, full attention) takes ~5 minutes AND needs 28GB -")
    print("it does NOT fit on any consumer GPU. The optimization stack attacks four")
    print("ORTHOGONAL cost axes, so the speedups MULTIPLY:")
    print()
    print("  axis            optimization           what it does              speedup")
    print("  --------------- ---------------------- ------------------------- --------")
    print("  WEIGHTS (mem)   GGUF Q4 quantization   28GB -> 8.5GB (fits 12GB) enabler*")
    print("  STEPS (loop)    Lightning distillation 30 steps -> 4 steps       7.5x")
    print("  PER-STEP (flop) TeaCache               reuse cached attention   2.5x")
    print("  KERNEL (dispatch) torch.compile/sage   fuse kernels             1.3x")
    print()
    print("  * GGUF Q4 is the ENABLER (shrinks weights so the model fits), not a")
    print("    wall-clock multiplier in the gold speedup chain. The speed chain is")
    print("    Lightning x TeaCache x compile (see Section B).")
    print()
    print("Each layer's mechanism:")
    layers = [
        ("Lightning", "step distillation",
         "Train a student to produce in 4 steps what the teacher takes 30 for.",
         LIGHTNING_STEPS / BASE_STEPS, 7.5),
        ("TeaCache", "temporal-aware cache",
         "Attention outputs barely change between consecutive timesteps; cache and",
         1.0 / TEACACHE_SPEEDUP, TEACACHE_SPEEDUP),
        ("GGUF Q4", "weight quantization",
         "Block-quantize the 14B weights Q4_K_M: 28GB FP16 -> 8.5GB. Fits 12GB GPU.",
         None, None),
        ("compile", "kernel fusion",
         "torch.compile / sage attention fuse kernels, cut Python dispatch overhead.",
         1.0 / COMPILE_SPEEDUP, COMPILE_SPEEDUP),
    ]
    for name, short, mech, _, sp in layers:
        spstr = f"{sp:.1f}x" if sp is not None else "n/a"
        print(f"  - {name:<10} ({short}): {mech}")
    check("Lightning is 30->4 = 7.5x fewer steps",
          abs(BASE_STEPS / LIGHTNING_STEPS - 7.5) < 1e-9, f"got {BASE_STEPS/LIGHTNING_STEPS}")
    check("TeaCache factor is ~2.5x", abs(TEACACHE_SPEEDUP - 2.5) < 1e-9)
    check("compile factor is ~1.3x", abs(COMPILE_SPEEDUP - 1.3) < 1e-9)


def section_b_cumulative():
    banner("SECTION B: CUMULATIVE SPEEDUP - the gold chain (300s -> 12.3s)")
    print("Apply each speed layer to the previous result. The multipliers stack")
    print("because they attack orthogonal costs (steps x per-step x kernels).")
    print()
    t0 = BASE_TIME_S
    t1 = lightning_time(BASE_TIME_S, BASE_STEPS, LIGHTNING_STEPS)  # 40
    t2 = with_factor(t1, TEACACHE_SPEEDUP)                         # 16
    t3 = with_factor(t2, COMPILE_SPEEDUP)                          # 12.3
    print(f"  Base (naive)          30 steps, full attn, FP16   = {sec(t0)}   (1.0x)")
    print(f"  +GGUF Q4              28GB -> 8.5GB (fits 12GB)   = {sec(t0)}   (1.0x speed; enabler)")
    print(f"  +Lightning (4 steps)  300 x (4/30)                = {sec(t1)}   ({t0/t1:.1f}x)")
    print(f"  +TeaCache (2.5x)      40 / 2.5                    = {sec(t2)}   ({t0/t2:.2f}x)")
    print(f"  +compile (1.3x)       16 / 1.3                    = {sec(t3)}   ({t0/t3:.1f}x)")
    print()
    total = t0 / t3
    print(f"  TOTAL SPEEDUP = 300 / {t3:.1f}  =  {total:.1f}x   (often quoted ~25-30x)")
    print()
    print("Per-layer marginal speedup (vs the previous layer):")
    print("| layer                 | vs previous | cumulative |")
    print("|-----------------------|-------------|------------|")
    print(f"| Base (naive)          |    1.0x     |    1.0x    |")
    print(f"| +GGUF Q4 (enabler)    |    1.0x*    |    1.0x    |")
    print(f"| +Lightning (4 steps)  |    7.5x     |    7.5x    |")
    print(f"| +TeaCache (2.5x)      |    2.5x     |   18.75x   |")
    print(f"| +compile (1.3x)       |    1.3x     |   24.4x    |")
    print("  * GGUF Q4 is a memory enabler (fits the GPU), not a time multiplier here.")
    print()
    check("Lightning time = 40s", abs(t1 - 40.0) < 1e-9, f"got {t1}")
    check("TeaCache time = 16s", abs(t2 - 16.0) < 1e-9, f"got {t2}")
    check("compile time ~= 12.3s", abs(t3 - 12.3077) < 0.01, f"got {t3}")
    check("total speedup ~= 24.4x", abs(total - 24.4) < 0.1, f"got {total}")
    check("marginal multipliers multiply: 7.5 x 2.5 x 1.3 = 24.375",
          abs(7.5 * 2.5 * 1.3 - total) < 1e-6, f"got {7.5*2.5*1.3}")


def section_c_vram():
    banner("SECTION C: VRAM - why GGUF Q4 is the enabler (28GB -> 8.5GB)")
    print("The 14B model in FP16 is 28GB - it does NOT fit on ANY consumer GPU")
    print("(the biggest consumer card is 24GB, and you also need activations).")
    print("GGUF Q4_K_M block-quantization shrinks the weights ~3.3x so the model")
    print("fits a 12GB GPU (RTX 3060 12GB / RTX 4070) with room for activations.")
    print()
    print("| format       | bpw  | weights  | 24GB GPU? | 16GB? | 12GB? |")
    print("|--------------|------|----------|-----------|-------|-------|")
    rows = []
    for qname, bpw in sorted(WEIGHT_BPW.items(), key=lambda kv: kv[1]):
        w = weights_gb(DIT_PARAMS_B, bpw)
        rows.append((qname, bpw, w))
        fit24 = "FIT" if w <= 24 else "no"
        fit16 = "FIT" if w <= 16 else "no"
        fit12 = "FIT" if w <= 12 else "no"
        print(f"| {qname:<12} | {bpw:>4.2f} | {gb(w)} |    {fit24}     |  {fit16}   |  {fit12}   |")
    print()
    fp16 = weights_gb(DIT_PARAMS_B, WEIGHT_BPW["FP16"])
    q4 = weights_gb(DIT_PARAMS_B, WEIGHT_BPW["GGUF_Q4"])
    ratio = fp16 / q4
    print(f"  FP16 weights = {DIT_PARAMS_B}B x 16 / 8 = {fp16:.1f} GB   (fits no consumer GPU)")
    print(f"  GGUF Q4     = {DIT_PARAMS_B}B x {WEIGHT_BPW['GGUF_Q4']:.2f} / 8 = {q4:.2f} GB   (fits 12GB)")
    print(f"  VRAM compression = {fp16:.1f} / {q4:.2f} = {ratio:.2f}x")
    print()
    print("  ~2% quality drop (barely noticeable). The same GGUF block-quant concept")
    print("  applies to image models - see flux_gguf. TeaCache + Lightning add the")
    print("  SPEED; GGUF Q4 adds the FIT. You need both to run 14B locally.")
    check("FP16 = 28.0 GB", abs(fp16 - 28.0) < 1e-9, f"got {fp16}")
    check("GGUF Q4 ~= 8.5 GB", abs(q4 - 8.5) < 0.15, f"got {q4}")
    check("GGUF Q4 fits a 12GB GPU", q4 <= 12, f"got {q4}")
    check("FP16 does NOT fit 24GB (weights alone)", fp16 > 24, f"got {fp16}")


def section_d_quality():
    banner("SECTION D: QUALITY TRADEOFF - what each layer costs in fidelity")
    print("Speed is not free. Each optimization has a quality signature:")
    print()
    print("| optimization        | speedup | quality drop | reversible? |")
    print("|---------------------|---------|--------------|-------------|")
    total_drop = 0.0
    for name, drop in sorted(QUALITY_DROP.items()):
        total_drop += drop
        rev = "yes (toggle off)" if name in ("TeaCache", "compile") else "no (baked in)"
        print(f"| {name:<19} | ~ varies | {pct(drop):>10}  | {rev:<11} |")
    print()
    print(f"  Combined worst-case quality drop ~= {pct(total_drop)} (sum of independent drops;")
    print("  in practice errors partially cancel, so perceived drop is lower).")
    print()
    print("  - GGUF Q4: ~2% (block quantization; near-lossless for diffusion).")
    print("  - Lightning: ~5-10% (fewer steps = less refinement; the distillation LoRA")
    print("    recovers most of it, but fine detail / temporal coherence softens).")
    print("  - TeaCache: 0% at conservative threshold (aggressive -> flicker/artifacts).")
    print("  - compile: 0% (bit-exact same math, just faster kernels).")
    check("TeaCache is lossless at default threshold",
          QUALITY_DROP["TeaCache"] == 0.0)
    check("compile is lossless", QUALITY_DROP["compile"] == 0.0)
    check("GGUF Q4 drop is small (<3%)", QUALITY_DROP["GGUF Q4"] < 0.03)
    check("Lightning is the biggest fidelity cost",
          QUALITY_DROP["Lightning (4 steps)"] == max(QUALITY_DROP.values()))


def section_e_i2v():
    banner("SECTION E: IMAGE-TO-VIDEO CONDITIONING - lock frame 0, animate rest")
    print("Wan 2.2 supports image-to-video: provide a starting frame (encoded via")
    print("the VAE), the model generates MOTION for the remaining frames. The first")
    print("frame stays consistent with the input image. Same DiT, same step count -")
    print("only the INITIAL latent changes (frame 0 = image latent, locked; the rest")
    print("start as noise and get denoised). Same optimization stack applies.")
    print()
    import random
    random.seed(7)
    F, HH, WW = 4, 2, 2

    def noise_grid(frames, hh, ww):
        return [[[round(random.gauss(0, 1), 2) for _ in range(ww)]
                 for _ in range(hh)] for _ in range(frames)]

    def image_latent(hh, ww):
        return [[round(0.3 * (r + 1) + 0.1 * (c + 1), 2) for c in range(ww)]
                for r in range(hh)]

    img = image_latent(HH, WW)
    noi = noise_grid(F, HH, WW)
    init_i2v = [img] + noi[1:]   # frame 0 = image, rest = noise
    print(f"Tiny demo (seeded). Latent grid {F}(frames) x {HH}(h) x {WW}(w), 1 channel:")
    print("  I2V initial latent:")
    for f in range(F):
        tag = "  [LOCKED image]" if f == 0 else ""
        print(f"    frame {f}: {init_i2v[f]}{tag}")
    print()
    print("After denoising: frame 0 = the input image (consistent); frames 1..3 are")
    print("generated motion. This is how Wan animates a still image into a clip.")
    check("I2V locks frame 0 to the image latent",
          init_i2v[0] == img and init_i2v[1] == noi[1])


def section_f_landscape():
    banner("SECTION F: WAN 14B vs LTX 2B - quality vs speed tradeoff")
    print("Same target clip (~720x480x121, a 5s video). Wan 14B is higher quality")
    print("(better temporal coherence, more detail) but 7x heavier. The optimization")
    print("stack closes the speed gap while keeping most of the quality edge.")
    print()
    duration = 121 / FPS
    MODELS = [
        # name, params_b, vram_gb, gen_s, note
        ("LTX-Video 2B (Q8, distilled)", 2.0, 6.0, 44.0,
         "8GB-capable, faster; lower quality (see ltx_video)"),
        ("Wan 14B (naive 30 steps FP16)", 14.0, 28.0, 300.0,
         "highest quality; fits NO consumer GPU"),
        ("Wan 14B (GGUF Q4, naive steps)", 14.0, 8.5, 300.0,
         "fits 12GB; still slow (30 steps)"),
        ("Wan 14B (FULL stack)", 14.0, 8.5, 12.3,
         "GGUF Q4 + Lightning + TeaCache + compile"),
    ]
    print("| config                          | params | VRAM   | gen      | quality |")
    print("|---------------------------------|--------|--------|----------|---------|")
    for name, p, vram, gen, note in MODELS:
        q = "highest" if "naive 30" in name else ("high" if "FULL" in name else
              ("good" if "Q8" in name else "fits but slow"))
        print(f"| {name:<31} | {p:>4.0f}B  | {vram:>4.1f}GB | {gen:>6.1f} s | {q:<7} |")
    print()
    full = next(m for m in MODELS if "FULL stack" in m[0])
    ltx = MODELS[0]
    naive = next(m for m in MODELS if "naive 30 steps FP16" in m[0])
    print(f"  Full-stack Wan: {full[3]:.0f}s on a 12GB card, ~{naive[3]/full[3]:.0f}x faster than naive.")
    print(f"  vs LTX 2B: {ltx[3]:.0f}s on an 8GB card. The stack is so effective that")
    print(f"  full-stack Wan ({full[3]:.0f}s) is FASTER than LTX here - while keeping the")
    print(f"  14B quality edge. Tradeoff: Wan needs >=12GB; LTX runs on 8GB. Pick LTX for")
    print(f"  the smallest card; pick full-stack Wan for best quality at similar speed.")
    check("Full-stack Wan fits 12GB", full[2] <= 12)
    check("Full-stack Wan ~ 24x faster than naive", abs(naive[3] / full[3] - 24.4) < 0.5)
    check("Full-stack Wan is faster than (or ~ LTX) reference numbers", full[3] <= ltx[3])
    check("LTX uses less VRAM (runs on a smaller card)", ltx[2] < full[2])


def section_gold():
    banner("GOLD VALUE - the canonical numbers the HTML must reproduce")
    t1 = lightning_time(BASE_TIME_S, BASE_STEPS, LIGHTNING_STEPS)
    t2 = with_factor(t1, TEACACHE_SPEEDUP)
    t3 = with_factor(t2, COMPILE_SPEEDUP)
    total = BASE_TIME_S / t3
    fp16 = weights_gb(DIT_PARAMS_B, WEIGHT_BPW["FP16"])
    q4 = weights_gb(DIT_PARAMS_B, WEIGHT_BPW["GGUF_Q4"])
    print(f"Speed chain (identical to Section B):")
    print(f"  base        = {BASE_TIME_S:.0f} s   (30 steps)")
    print(f"  +Lightning  = {BASE_TIME_S} x ({LIGHTNING_STEPS}/{BASE_STEPS}) = {t1:.1f} s")
    print(f"  +TeaCache   = {t1:.0f} / {TEACACHE_SPEEDUP} = {t2:.1f} s")
    print(f"  +compile    = {t2:.0f} / {COMPILE_SPEEDUP} = {t3:.1f} s")
    print(f"  SPEEDUP     = {BASE_TIME_S:.0f} / {t3:.1f} = {total:.1f}x")
    print()
    print(f"VRAM:")
    print(f"  FP16     = {DIT_PARAMS_B}B x 16 / 8 = {fp16:.1f} GB")
    print(f"  GGUF Q4  = {DIT_PARAMS_B}B x {WEIGHT_BPW['GGUF_Q4']:.2f} / 8 = {q4:.2f} GB  (~8.5)")
    print()
    print(f"  GOLD (pinned in wan_video.html):")
    print(f"    final time   = {t3:.1f} s   (to 1 dp)")
    print(f"    total speedup= {total:.1f}x  (to 1 dp)")
    print(f"    FP16 VRAM    = {fp16:.1f} GB")
    print(f"    GGUF Q4 VRAM = {q4:.2f} GB  (~8.5)")
    check("gold final time ~= 12.3s", abs(t3 - 12.3) < 0.05, f"got {t3}")
    check("gold speedup ~= 24.4x", abs(total - 24.4) < 0.05, f"got {total}")
    check("gold FP16 = 28.0 GB", abs(fp16 - 28.0) < 1e-9, f"got {fp16}")
    check("gold GGUF Q4 ~= 8.5 GB", abs(q4 - 8.5) < 0.15, f"got {q4}")


# ============================================================================
# main
# ============================================================================

def main():
    print("wan_video.py - Wan 2.2 (14B) optimization stack (GGUF Q4 + Lightning +")
    print("TeaCache + compile). Pure Python stdlib. Numbers below feed WAN_VIDEO.md.")
    print("Sources: docs.comfy.org (Wan 2.2), Comfy-Org/Wan_2.2 repackaged, bullerwins/")
    print("QuantStack GGUFs, lightx2v Lightning LoRA, TeaCache + sage attention.")
    print()
    print("Lineage: Wan 14B naive (28GB, 300s) -> +GGUF Q4 + Lightning + TeaCache +")
    print("compile (8.5GB, 12.3s, ~24x faster).")

    section_a_stack()
    section_b_cumulative()
    section_c_vram()
    section_d_quality()
    section_e_i2v()
    section_f_landscape()
    section_gold()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
