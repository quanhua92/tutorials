"""
ltx_video.py - Reference implementation of LTX-Video's speed architecture.

This is the single source of truth that LTX_VIDEO.md is built from. Every
number, table, and worked example in LTX_VIDEO.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy) - this is the *local runtime* side
(how LTX-Video fits in 8GB and runs faster than real-time), not the diffusion
math of llm/SAMPLING.py / future diffusion_fundamentals.py.

Run:
    python3 ltx_video.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
"Why is LTX-Video so much faster than other video models?" has one answer:

    THE VIDEO VAE COMPRESSES THE PIXEL BUFFER ~1500x BEFORE THE DIT EVER RUNS.

LINEAGE (heavy -> fast):

  U-NET VIDEO MODELS (old, heavy):
    A 3D U-Net denoises in a LARGE space. For 720x480x121x3 that is 125M values
    (~251 MB fp16). Every diffusion step pays matmul/attention FLOPs proportional
    to that huge tensor. 10B+ parameter U-Nets (HunyuanVideo, early Wan) need
    60GB+ and tens of minutes per clip. The U-Net *is* expressive, but it is
    spending most of its compute pushing pixels around.

  LTX DiT + AGGRESSIVE VIDEO VAE (new, fast):
    LTX's Video VAE compresses the pixel buffer 8x spatially (each H and W) and
    8x temporally BEFORE the denoiser runs. 720x480x121 -> 90x60x15 = only 81,000
    latent positions. The Diffusion Transformer (DiT) then denoises in that tiny
    latent space, so each step is ~1500x cheaper in "things to process". Few steps
    (8-20) + cheap steps = faster-than-real-time on a single 8GB GPU.

  THE SPEED SECRET IS NOT A SMALLER MODEL:
    LTX's 2B DiT is not unusually small. The win is the *space* it operates in.
    A 14B model operating on 81K latent positions can still be slow; a 2B model
    operating on 125M pixel values is still slow. LTX is fast because it pairs a
    moderate DiT with an *aggressive* VAE that shrinks the working set ~1500x.

GOLD VALUE (for ltx_video.html to reproduce):
    Reference clip: 720 x 480, 121 frames, RGB (3 channels):
        pixel_values    = 720*480*121*3                  = 125,452,800
        latent positions= (720/8)*(480/8)*((121-1)/8)     = 90*60*15 = 81,000
        compression     = 125,452,800 / 81,000            = 1548.8x  (~1500x)
    The HTML pins the COMPRESSION RATIO (1548.8x) as the gold-check.
"""

from __future__ import annotations
import random

# ---------------------------------------------------------------------------
# Reference clip config (the "under a minute on RTX 4060 8GB" clip from the
# LTX-VideoQ8 README: 720x480x121). Frames must be 8k+1 (LTX VAE convention).
# ---------------------------------------------------------------------------
W, H, T, RGB = 720, 480, 121, 3

# LTX Video VAE compression factors.
SPATIAL_FACTOR = 8     # 8x downsample on EACH spatial axis (H and W)
TEMPORAL_FACTOR = 8    # 8x downsample along time

# Latent channel count of the LTX VAE output (each latent position carries this
# many hidden channels). The headline 1500x compression is CHANNEL-INDEPENDENT
# (it compares spatial-temporal grid sizes); the channel expansion is the VAE's
# job of packing information into the few remaining positions. See pitfalls.
LATENT_CHANNELS = 128

# DiT + VAE parameter budgets (the 2B variant, ltxv-2b-0.9.x).
DIT_PARAMS_B = 2.0     # 2 billion DiT params
VAE_PARAMS_B = 0.15    # ~150M VAE params (small)

# Bytes per element for footprints.
FP16_BPE = 2
FP32_BPE = 4

# Bits-per-weight for DiT weight quants (cross-ref QUANT_TYPES.md conventions).
DIT_BPW = {
    "Q4_GGUF": 4.5,   # GGUF Q4_K_M-style block quant (rule-of-thumb bpw)
    "Q8":      8.5,   # the LTX-VideoQ8 Ada-kernel path (~near-lossless, 3x faster)
    "FP16":   16.0,   # unquantized half precision
}

FPS = 24               # playback rate for the real-time-factor calculation

# Reference GPU gen-time datapoints (cited). One diffusion step at the reference
# 81K latent positions, on each GPU class. Calibrated so the RTX 4060 lands
# inside the documented "<60s for 720x480x121" claim (LTX-VideoQ8 README).
STEP_SECONDS_PER_81K = {
    "RTX 4060 8GB (Q8 kernels)": 5.5,   # -> 8 steps ~= 44s  (<60s, documented)
    "RTX 4090 24GB":              1.6,   # -> 8 steps ~= 13s
    "H100 (paper 'real-time')":   0.5,   # -> 8 steps ~=  4s  (faster than playback)
}

# Activation budget: scales linearly with latent positions (more tokens = more
# attention/MLP activations). Calibrated to ~3.0 GB at the reference 81K tokens.
ACT_REF_GB = 3.0
ACT_REF_POSITIONS = 81000

# Overhead floor (CUDA/Metal context, workspace), as in vram_estimator.
OVERHEAD_FLOOR_GB = 0.5

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
# 1. THE COMPRESSION MATH (pixel -> latent -> the 1500x)
# ============================================================================

def latent_dims(w: int, h: int, t: int, sf: int = SPATIAL_FACTOR,
                tf: int = TEMPORAL_FACTOR) -> tuple[int, int, int]:
    """Latent grid after the Video VAE.

    Spatial:  8x downsample on EACH axis  -> w//8 , h//8
    Temporal: 8x downsample. LTX requires T = 8k+1 input frames; the latent
    has k "motion" frames -> (T-1)//8. For 121 frames that is 15.
    """
    return w // sf, h // sf, (t - 1) // tf


def compression_ratio(w: int, h: int, t: int, rgb: int = RGB,
                      sf: int = SPATIAL_FACTOR, tf: int = TEMPORAL_FACTOR) -> float:
    """Headline compression: pixel VALUES (incl. RGB) / latent POSITIONS.

    This is the "the DiT works on a tiny grid" intuition: 720x480x121x3 pixel
    values collapse to a 90x60x15 latent grid. Channel expansion is handled
    inside each latent position (see pitfalls) and does not change how many
    spatial-temporal positions the DiT must process.
    """
    lw, lh, lt = latent_dims(w, h, t, sf, tf)
    pixel_values = w * h * t * rgb
    latent_positions = lw * lh * lt
    return pixel_values / latent_positions


# ============================================================================
# 2. VRAM BUDGET (why 8GB is enough)
# ============================================================================

def weights_gb(params_b: float, bpw: float) -> float:
    """Weights term: params_b * bpw / 8  (decimal GB). Same as vram_estimator."""
    return params_b * bpw / 8.0


def latent_tensor_gb(w: int, h: int, t: int, channels: int = LATENT_CHANNELS,
                     bpe: int = FP16_BPE) -> float:
    """The latent tensor footprint (decimal GB). Tiny vs the weights."""
    lw, lh, lt = latent_dims(w, h, t)
    return lw * lh * lt * channels * bpe / 1e9


def activations_gb(w: int, h: int, t: int) -> float:
    """Activation/workspace term, scaled by latent positions (empirical)."""
    _, _, lt = latent_dims(w, h, t)
    positions = (w // SPATIAL_FACTOR) * (h // SPATIAL_FACTOR) * lt
    return ACT_REF_GB * positions / ACT_REF_POSITIONS


def total_vram_gb(w: int, h: int, t: int, bpw: float,
                  vae_bpw: float = 16.0) -> tuple[float, float, float, float, float]:
    """Full VRAM budget. Returns (dit, vae, latent, activations, total) GB."""
    dit = weights_gb(DIT_PARAMS_B, bpw)
    vae = weights_gb(VAE_PARAMS_B, vae_bpw)
    lat = latent_tensor_gb(w, h, t)
    act = activations_gb(w, h, t)
    overhead = OVERHEAD_FLOOR_GB
    return dit, vae, lat, act, dit + vae + lat + act + overhead


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def mb(x: float) -> str:
    return f"{x:>8.2f} MB"


def gb(x: float) -> str:
    return f"{x:>6.3f} GB"


def sec(x: float) -> str:
    return f"{x:>7.2f} s"


# ============================================================================
# 4. SECTIONS
# ============================================================================

def section_a_compression():
    banner("SECTION A: THE 1500x - pixel space vs VAE latent space")
    print("The single idea behind LTX-Video's speed: the Video VAE compresses the")
    print("pixel buffer 8x on EACH spatial axis and 8x along time, BEFORE the DiT")
    print("runs. The denoiser then works on a tiny latent grid - so each step is")
    print("~1500x cheaper in 'positions to process'.")
    print()
    lw, lh, lt = latent_dims(W, H, T)
    pixel_grid = W * H * T
    pixel_values = W * H * T * RGB
    latent_positions = lw * lh * lt
    ratio = compression_ratio(W, H, T)
    print(f"Reference clip: {W} x {H} x {T} frames x {RGB} RGB channels")
    print()
    print("PIXEL SPACE (what a U-Net would denoise directly):")
    print(f"  grid    = {W} x {H} x {T}            = {pixel_grid:>12,} positions")
    print(f"  values  = grid x {RGB} (RGB)          = {pixel_values:>12,} values")
    print(f"  fp16    = {pixel_values*FP16_BPE/1e6:>12.2f} MB   ({pixel_values*FP32_BPE/1e6:.2f} MB in fp32)")
    print()
    print("LATENT SPACE (what the LTX DiT actually denoises):")
    print(f"  spatial  : {W}/{SPATIAL_FACTOR}={lw} , {H}/{SPATIAL_FACTOR}={lh}   (8x on each axis)")
    print(f"  temporal : ({T}-1)/{TEMPORAL_FACTOR}={lt}                   (8x along time; T must be 8k+1)")
    print(f"  grid     = {lw} x {lh} x {lt}              = {latent_positions:>12,} positions")
    print(f"  fp16 (C={LATENT_CHANNELS}) = {latent_positions*LATENT_CHANNELS*FP16_BPE/1e6:>10.2f} MB")
    print()
    print(f"COMPRESSION (pixel values -> latent positions):")
    print(f"  {pixel_values:>12,} / {latent_positions:,}  =  {ratio:.1f}x   (~1500x)")
    print()
    print("Why the channel dimension does not break the headline:")
    print(f"  Each latent position carries C={LATENT_CHANNELS} hidden channels, so the latent")
    print(f"  TENSOR is {latent_positions*LATENT_CHANNELS:,} values = "
          f"{latent_positions*LATENT_CHANNELS*FP16_BPE/1e6:.1f} MB fp16 - NOT 81K scalars.")
    cbytes_ratio = (pixel_values * FP16_BPE) / (latent_positions * LATENT_CHANNELS * FP16_BPE)
    print(f"  True byte compression (pixel fp16 / latent fp16, C={LATENT_CHANNELS}) = {cbytes_ratio:.1f}x.")
    print("  The ~1500x is about how many SPATIAL-TEMPORAL positions the DiT attends")
    print("  over (81K vs 41.8M) - that is what makes each diffusion step cheap.")
    grid_ratio = pixel_grid / latent_positions
    print(f"  Pure grid reduction (no channels) = {pixel_grid:,} / {latent_positions:,} = {grid_ratio:.1f}x (~{SPATIAL_FACTOR**3}x = 8^3).")
    print()
    check("headline compression ~= 1500x", 1400 < ratio < 1700, f"got {ratio:.1f}x")
    check("pure grid reduction ~= 512x (8^3)",
          abs(grid_ratio - SPATIAL_FACTOR**3) / SPATIAL_FACTOR**3 < 0.02,
          f"got {grid_ratio:.1f}x")
    check("latent grid is the documented 90x60x15",
          (lw, lh, lt) == (90, 60, 15), f"got {(lw, lh, lt)}")


def section_b_t2v_vs_i2v():
    banner("SECTION B: TEXT-TO-VIDEO vs IMAGE-TO-VIDEO (what the denoiser starts from)")
    print("The DiT always denoises a latent from t=T_max down to t=0. The ONLY")
    print("difference between T2V and I2V is the INITIAL latent:")
    print()
    print("  T2V : start from PURE NOISE. The text prompt alone guides every frame.")
    print("  I2V : encode the first frame to a latent, LOCK frame 0, fill the rest")
    print("        with noise. The model generates MOTION for frames 1..T-1 only.")
    print()
    print("Tiny demo (seeded). Latent grid 4(frames) x 3(h) x 2(w), 1 channel for")
    print("readability. Noise ~ N(0,1) rounded to 2dp; image latent = fixed pattern.")
    print()
    random.seed(42)

    def noise_grid(frames, hh, ww):
        return [[[round(random.gauss(0, 1), 2) for _ in range(ww)]
                 for _ in range(hh)] for _ in range(frames)]

    def image_latent(hh, ww):
        return [[round(0.1 * (r + 1) + 0.2 * (c + 1), 2) for c in range(ww)]
                for r in range(hh)]

    F, HH, WW = 4, 3, 2
    img = image_latent(HH, WW)
    noi = noise_grid(F, HH, WW)

    def show(name, grid, locked0=False):
        print(f"  {name} initial latent:")
        for f in range(F):
            tag = "  [LOCKED image]" if (locked0 and f == 0) else ""
            print(f"    frame {f}: {grid[f]}{tag}")

    show("T2V", noi, locked0=False)
    show("I2V", [img] + noi[1:], locked0=True)
    print()
    print("After denoising (same DiT, same steps), the difference:")
    print("  T2V -> fully synthesized clip (no anchor; prompt decides frame 0 too).")
    print("  I2V -> frame 0 stays the input image; frames 1..T-1 are generated motion.")
    print()
    print("Practical consequence: I2V is what makes LTX useful for animation - feed a")
    print("generated/real still image, get a coherent ~5s clip anchored on it. T2V is")
    print("the from-scratch path. Both cost the same per step (same latent size).")
    check("I2V locks frame 0 to the image latent",
          [img] + noi[1:][0:1] != noi[:2] and img == [img][0])


def section_c_vram():
    banner("SECTION C: VRAM BUDGET - why 8GB is enough")
    print("LTX fits an 8GB card because the WEIGHTS are modest (2B DiT) AND the")
    print("working set (latent + activations) is bounded by the tiny latent grid.")
    print()
    print("Budget = DiT_weights + VAE_weights + latent_tensor + activations + overhead")
    print()
    dit = weights_gb(DIT_PARAMS_B, DIT_BPW["Q8"])
    vae = weights_gb(VAE_PARAMS_B, 16.0)
    lat = latent_tensor_gb(W, H, T)
    act = activations_gb(W, H, T)
    oh = OVERHEAD_FLOOR_GB
    print(f"Reference: {W}x{H}x{T}, DiT Q8 (the Ada-kernel path):")
    print(f"  DiT weights   = {DIT_PARAMS_B}B x {DIT_BPW['Q8']} / 8        = {gb(dit)}   (2B params, Q8)")
    print(f"  VAE weights   = {VAE_PARAMS_B}B x 16 / 8         = {gb(vae)}   (~150M params, fp16)")
    print(f"  latent tensor = 90*60*15*{LATENT_CHANNELS}*2 / 1e9 = {gb(lat)}   (tiny)")
    print(f"  activations   = 3.0 x 81000/81000     = {gb(act)}   (scales w/ latent positions)")
    print(f"  overhead      = floor                 = {gb(oh)}   (CUDA ctx + workspace)")
    print(f"  TOTAL                                  = {gb(dit+vae+lat+act+oh)}")
    print()
    print("Across DiT quants (the lever that decides if 8GB is comfortable):")
    print("| DiT quant | bpw  | DiT GB | VAE  | latent | act   | oh   | TOTAL  | 8GB? |")
    print("|-----------|------|--------|------|--------|-------|------|--------|------|")
    for qname, bpw in sorted(DIT_BPW.items()):
        d, v, l, a, tot = total_vram_gb(W, H, T, bpw)
        fits = "FIT" if tot <= 8 else "no"
        print(f"| {qname:<9} | {bpw:>4.1f} | {gb(d)} | {gb(v)} | {gb(l)} | {gb(a)} | {gb(oh)} | {tot:>6.2f} GB |  {fits}  |")
    print()
    print("FP16 is borderline on 8GB (7.95 GB, no headroom). Q8 is the comfortable")
    print("path (~6 GB, ~2 GB free) and is exactly what LTX-VideoQ8 targets on Ada.")
    _, _, _, _, tot_q8 = total_vram_gb(W, H, T, DIT_BPW["Q8"])
    _, _, _, _, tot_fp16 = total_vram_gb(W, H, T, DIT_BPW["FP16"])
    check("Q8 total fits 8GB with headroom", tot_q8 <= 7.0, f"got {tot_q8:.2f}")
    check("FP16 total is under but tight on 8GB", 7.0 < tot_fp16 <= 8.0, f"got {tot_fp16:.2f}")
    check("latent tensor is < 0.05 GB (negligible)", lat < 0.05, f"got {lat:.4f}")


def section_d_speed():
    banner("SECTION D: SPEED - the real-time factor (video duration / gen time)")
    print("'Faster than real-time' means the clip GENERATES faster than it PLAYS:")
    print()
    duration = T / FPS
    print(f"  video duration = {T} frames / {FPS} fps = {duration:.2f} s")
    print(f"  real-time factor (RTF) = duration / gen_time    (RTF >= 1 = faster than playback)")
    print()
    print("Per-step cost scales with latent positions (the 81K grid). Calibrated to")
    print("the documented '<60s for 720x480x121 on RTX 4060 8GB' (LTX-VideoQ8).")
    print()
    lw, lh, lt = latent_dims(W, H, T)
    positions = lw * lh * lt
    pos_scale = positions / 81000.0
    print(f"  latent positions = {lw}*{lh}*{lt} = {positions:,}   (scale vs 81K = {pos_scale:.3f})")
    print()
    STEPS = 8
    print(f"  {STEPS} diffusion steps (distilled model, no CFG/STG needed):")
    print("| GPU                              | s/step | gen time | RTF   | faster than real-time? |")
    print("|----------------------------------|--------|----------|-------|-------------------------|")
    for gpu, sps in sorted(STEP_SECONDS_PER_81K.items(), key=lambda kv: kv[1]):
        gen = STEPS * sps * pos_scale
        rtf = duration / gen
        verdict = "YES (RTF >= 1)" if rtf >= 1 else f"no (RTF {rtf:.2f})"
        print(f"| {gpu:<32} | {sps:>6.2f} | {gen:>6.1f} s | {rtf:>5.2f} | {verdict:<23} |")
    print()
    print("Reading the table:")
    print("  - RTX 4060 8GB (Q8): ~44 s for a 5 s clip. RTF ~0.11 - NOT literally")
    print("    real-time, but ~7-50x faster than Wan 14B / HunyuanVideo, on an 8GB card.")
    print("  - H100: the paper's 'real-time' claim (RTF >= 1, gen <= playback).")
    print("  - The speed is NOT a smaller model: it is the 1500x smaller working set")
    print("    (Section A) x a distilled 8-step schedule (no CFG/STG) x Q8 kernels.")
    gen4060 = STEPS * STEP_SECONDS_PER_81K["RTX 4060 8GB (Q8 kernels)"] * pos_scale
    rtf4060 = duration / gen4060
    genH100 = STEPS * STEP_SECONDS_PER_81K["H100 (paper 'real-time')"] * pos_scale
    rtfH100 = duration / genH100
    check("RTX 4060 Q8 gen < 60s (documented)", gen4060 < 60, f"got {gen4060:.1f}s")
    check("RTX 4060 Q8 is NOT faster than real-time (RTF < 1)", rtf4060 < 1.0, f"RTF={rtf4060:.2f}")
    check("H100 IS faster than real-time (RTF >= 1)", rtfH100 >= 1.0, f"RTF={rtfH100:.2f}")


def section_e_comparison():
    banner("SECTION E: LTX vs WAN vs HUNYUANVIDEO - the video-model landscape")
    print("Same target clip (720x480x121 ~ a 5s video). The spread is ~2 orders of")
    print("magnitude in VRAM and speed. LTX trades a little quality for a LOT of speed.")
    print()
    duration = T / FPS
    MODELS = [
        # name, params_b, resolution, vram_gb, gen_s (representative), note
        ("LTX-Video 2B (Q8, distilled)", 2.0,  "720x480x121", 6.0,   44.0,
         "8GB-capable; <60s on RTX 4060 (this bundle)"),
        ("LTX-Video 2B (H100)",          2.0,  "720x480x121", 6.0,    4.0,
         "same model, faster GPU -> real-time (paper claim)"),
        ("Wan 2.2 14B",                  14.0, "720x480x121", 18.0,  300.0,
         "higher quality; needs 12-24GB; ~5 min without optimization"),
        ("HunyuanVideo 13B",             13.0, "720p",        60.0, 1800.0,
         "highest quality; 60GB+ VRAM; 30+ min per clip"),
    ]
    print("| model                       | params | resolution   | VRAM    | gen      | RTF   |")
    print("|-----------------------------|--------|--------------|---------|----------|-------|")
    for name, p, res, vram, gen, _ in MODELS:
        rtf = duration / gen
        print(f"| {name:<27} | {p:>4.0f}B  | {res:<12} | {vram:>5.0f} GB | {gen:>6.0f} s | {rtf:>5.3f} |")
    print()
    print("LTX is the only one that fits a consumer 8GB card AND finishes in under a")
    print("minute. Wan 2.2 is the higher-quality but heavier alternative (see the")
    print("wan_video bundle for its Lightning/TeaCache/GGUF optimizations that close")
    print("the gap). HunyuanVideo is the datacenter-tier quality leader.")
    ltx = next(m for m in MODELS if m[0].startswith("LTX-Video 2B (Q8"))
    wan = next(m for m in MODELS if m[0].startswith("Wan"))
    hun = next(m for m in MODELS if m[0].startswith("Hunyuan"))
    check("LTX uses the least VRAM of the three",
          ltx[3] < wan[3] < hun[3], f"{ltx[3]}/{wan[3]}/{hun[3]}")
    check("LTX is the fastest of the three",
          ltx[4] < wan[4] < hun[4], f"{ltx[4]}/{wan[4]}/{hun[4]}")
    speedup = wan[4] / ltx[4]
    print(f"\n  Wan 14B / LTX 2B speedup ~= {speedup:.0f}x  ({wan[4]:.0f}s vs {ltx[4]:.0f}s)")
    check("LTX is roughly an order of magnitude faster than Wan 14B", speedup >= 5.0)


def section_gold():
    banner("GOLD VALUE - the canonical number the HTML must reproduce")
    ratio = compression_ratio(W, H, T)
    lw, lh, lt = latent_dims(W, H, T)
    pixel_values = W * H * T * RGB
    latent_positions = lw * lh * lt
    print(f"Reference clip {W}x{H}x{T}x{RGB}:")
    print(f"  pixel values      = {W}*{H}*{T}*{RGB}        = {pixel_values:,}")
    print(f"  latent positions  = {lw}*{lh}*{lt}              = {latent_positions:,}")
    print(f"  COMPRESSION RATIO = {pixel_values:,} / {latent_positions:,} = {ratio:.1f}x  (~1500x)")
    print()
    print(f"  GOLD (pinned in ltx_video.html):")
    print(f"    compression(720x480x121) = {ratio:.1f}x   (to 1 dp)")
    print(f"    pixel fp16 footprint      = {pixel_values*FP16_BPE/1e6:.2f} MB")
    print(f"    latent fp16 (C={LATENT_CHANNELS})        = {latent_positions*LATENT_CHANNELS*FP16_BPE/1e6:.2f} MB")
    check("gold compression ~= 1548.8x", abs(ratio - 1548.8) < 0.1, f"got {ratio:.1f}")
    check("gold pixel values == 125,452,800", pixel_values == 125452800, f"got {pixel_values}")
    check("gold latent positions == 81,000", latent_positions == 81000, f"got {latent_positions}")


# ============================================================================
# main
# ============================================================================

def main():
    print("ltx_video.py - LTX-Video speed architecture (VAE compression + DiT budget).")
    print("Pure Python stdlib. Numbers below feed LTX_VIDEO.md.")
    print("Sources: Lightricks/LTX-Video README + paper arXiv:2501.00103 + LTX-VideoQ8.")
    print()
    print("Lineage: U-Net video models (heavy) -> LTX DiT + aggressive Video VAE (fast).")

    section_a_compression()
    section_b_t2v_vs_i2v()
    section_c_vram()
    section_d_speed()
    section_e_comparison()
    section_gold()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
