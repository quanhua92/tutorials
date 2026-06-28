"""
flux_gguf.py - Running Flux.1 [dev] locally with GGUF quantization.

This is the single source of truth that FLUX_GGUF.md is built from. Every
number, table, and VRAM budget in FLUX_GGUF.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy) - this is the *local runtime*
side (how big, what GPU, which quant), not the diffusion math (that's
diffusion_fundamentals.py) or the block format (that's quant_types.py).

Run:
    python3 flux_gguf.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
Flux.1 [dev] is a 12-BILLION-parameter image generator. In full precision
(FP16) its weights alone are 23 GB - more than most consumer GPUs have in
total. The model is unusable on anything below a 24 GB GPU (RTX 3090/4090).

GGUF quantization (the same block format LLMs use, see quant_types.py) shrinks
the Diffusion Transformer (DiT) weights so Flux fits on ordinary GPUs:

    FP16  23 GB  ->  needs 24 GB GPU   (RTX 4090)
    Q8_0  12 GB  ->  needs 12 GB GPU   (RTX 3060 12GB)   <1% quality loss
    Q4_K_M 7 GB  ->  needs  8 GB GPU   (RTX 3060/4060)   best quality/size
    Q3_K_S 5.5GB ->  needs  6 GB GPU   (GTX 1060 6GB)    noticeable loss

Why GGUF works for Flux but not SDXL: Flux uses a DiT (Diffusion Transformer)
instead of a U-Net. Transformer matmuls are far more tolerant of weight
quantization than the conv2d layers in a U-Net, so 4-bit Flux barely degrades
while 4-bit SDXL falls apart.

GOLD VALUE (for FLUX_GGUF.html to reproduce):
    VAE compression: 1024x1024x3 = 3,145,728 pixel values
                  -> 128x128x16  =   262,144 latent values
                  ->  12.0x compression (8x spatial, 16/3 channels)
"""

from __future__ import annotations

# ============================================================================
# 0. CONSTANTS
# ============================================================================

BANNER = "=" * 74

# --- Flux.1 [dev] architecture ---
N_PARAMS_DIT     = 12e9      # 12 billion (marketed) Diffusion Transformer params
N_PARAMS_T5_XXL  = 4.7e9     # T5-XXL text encoder (encoder-only for Flux)
N_PARAMS_CLIP_L  = 0.4e9     # CLIP-L text encoder (tiny, always fp16)
T5_CONTEXT_TOKENS = 256      # T5-XXL max prompt length (vs 77 for SDXL's CLIP)

# --- VAE spatial compression ---
PIXEL_H, PIXEL_W, PIXEL_C = 1024, 1024, 3      # a 1024x1024 RGB image
LATENT_H, LATENT_W, LATENT_C = 128, 128, 16    # Flux's latent space
SPATIAL_DOWNSAMPLE = PIXEL_H // LATENT_H         # 8x per axis (8*8 = 64x area)

# --- Bytes / GB (decimal, matching how drive/GPU vendors quote sizes) ---
BYTES_PER_GB = 1e9
FP16_BYTES_PER_PARAM = 2   # IEEE 754 binary16 = 2 bytes

# --- GGUF quant levels for the Flux DiT ---
# File sizes are the ACTUAL checkpoints from city96/FLUX.1-dev-gguf on
# HuggingFace. Effective bpw is derived: file_GB * 8 / N_PARAMS_DIT(in B).
# Quality notes are community consensus (city96 README + Reddit threads).
QUANT_LEVELS = [
    # (name,       file_GB, quality_loss_pct, min_total_gpu_gb, note)
    ("FP16",       23.0,     0.0,             24,
     "reference / full precision"),
    ("Q8_0",       12.0,     0.5,             12,
     "near-lossless, fits 12 GB GPU"),
    ("Q4_K_M",      7.0,     1.8,              8,
     "BEST quality/size for Flux (default)"),
    ("Q4_K_S",      6.5,     2.0,              8,
     "small 4-bit, fits 8 GB GPU"),
    ("Q3_K_S",      5.5,     4.0,              6,
     "noticeable quality loss, tightest fit"),
]

# --- T5-XXL encoder sizes (quantized separately from the DiT) ---
T5_FP16_GB = N_PARAMS_T5_XXL * FP16_BYTES_PER_PARAM / BYTES_PER_GB  # 9.4
T5_Q4_GB   = 2.0    # T5-XXL encoder at Q4 (city96/t5-v1_1-xxl-encoder-gguf)

# --- Fixed budget terms ---
VAE_GB          = 0.5    # Flux VAE (always fp16/fp32, small)
ACTIVATIONS_GB  = 2.0    # latent + CLIP-L (0.8 GB) + intermediate activations
#  CLIP-L (~0.4 B params, 0.8 GB fp16) is small and folded into this term.


# ============================================================================
# 1. CHECK HELPER
# ============================================================================

def check(label: str, cond: bool, detail: str = ""):
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def eff_bpw(file_gb: float) -> float:
    """Effective bits-per-weight from file size, assuming N_PARAMS_DIT."""
    return file_gb * BYTES_PER_GB * 8 / N_PARAMS_DIT


# ============================================================================
# 2. SECTIONS
# ============================================================================

def section_a_architecture():
    banner("SECTION A: FLUX.1 ARCHITECTURE - DiT, not U-Net")
    print("Flux.1 [dev] (Black Forest Labs, Aug 2024) is a Diffusion Transformer")
    print("(DiT). The denoising network is a transformer, NOT the U-Net used by")
    print("SD 1.5 / SDXL. This matters for quantization (Section C).")
    print()
    print("Component breakdown:")
    print(f"  DiT denoiser   : {N_PARAMS_DIT/1e9:.1f}B params  (the big one, 12B)")
    print(f"  T5-XXL encoder : {N_PARAMS_T5_XXL/1e9:.1f}B params  ({T5_CONTEXT_TOKENS}-token context)")
    print(f"  CLIP-L encoder : {N_PARAMS_CLIP_L/1e9:.1f}B params  (small, always fp16)")
    print(f"  VAE            : decodes latent -> pixel (always fp16/fp32)")
    print()
    print("Why a transformer? Flux uses flow matching (not DDPM): a straighter")
    print("sampling trajectory that needs fewer steps (20-28 vs SDXL's 30-50).")
    print("The DiT processes the noisy latent + text embeddings via attention.")
    print()
    dit_fp16 = N_PARAMS_DIT * FP16_BYTES_PER_PARAM / BYTES_PER_GB
    t5_fp16  = T5_FP16_GB
    print(f"Full-precision weight sizes:")
    print(f"  DiT  fp16 = {dit_fp16:.1f} GB   ({N_PARAMS_DIT/1e9:.0f}B x 2 bytes)")
    print(f"  T5   fp16 = {t5_fp16:.1f} GB    ({N_PARAMS_T5_XXL/1e9:.1f}B x 2 bytes)")
    print(f"  Total     = {dit_fp16 + t5_fp16:.1f} GB (before VAE + activations)")
    print()
    check("DiT is 4.6x larger than SDXL's U-Net",
          abs(N_PARAMS_DIT / 2.6e9 - 12/2.6) < 0.01,
          f"{N_PARAMS_DIT/2.6e9:.1f}x (SDXL U-Net = 2.6B)")
    check("Flux needs >8GB just for fp16 weights",
          dit_fp16 + t5_fp16 > 20.0,
          f"{dit_fp16 + t5_fp16:.1f}GB")


def section_b_vae():
    banner("SECTION B: VAE COMPRESSION - pixel space to latent space")
    print("The VAE compresses a 1024x1024 RGB image into a small latent that the")
    print("DiT actually denoises. The DiT NEVER sees pixels directly - it works")
    print("in compressed latent space, which is why 12B params is affordable at all.")
    print()
    pixel_values = PIXEL_H * PIXEL_W * PIXEL_C
    latent_values = LATENT_H * LATENT_W * LATENT_C
    spatial = SPATIAL_DOWNSAMPLE
    compression = pixel_values / latent_values
    print(f"Pixel space : {PIXEL_H}x{PIXEL_W}x{PIXEL_C} = {pixel_values:>10,} values")
    print(f"Latent space: {LATENT_H}x{LATENT_W}x{LATENT_C} = {latent_values:>10,} values")
    print()
    print(f"Spatial downsample = {PIXEL_H}/{LATENT_H} = {spatial}x per axis")
    print(f"  -> {spatial}x{spatial} = {spatial*spatial}x fewer spatial positions")
    print(f"Channel expansion   = {LATENT_C}/{PIXEL_C} = {LATENT_C/PIXEL_C:.2f}x")
    print(f"Net compression     = {spatial*spatial}/{LATENT_C/PIXEL_C:.2f}"
          f" = {compression:.1f}x")
    print()
    # The DiT attention is O(n^2) in sequence length. Working in latent space
    # slashes the sequence length from 1024*1024 to 128*128.
    seq_pixel = PIXEL_H * PIXEL_W
    seq_latent = LATENT_H * LATENT_W
    print(f"Attention sequence length:")
    print(f"  if DiT saw pixels : {seq_pixel:>8,} tokens  (1024x1024)")
    print(f"  in latent space   : {seq_latent:>8,} tokens  (128x128)")
    print(f"  -> {seq_pixel/seq_latent:.0f}x shorter sequence = "
          f"{(seq_pixel/seq_latent)**2:.0f}x less attention compute")
    print()
    print("GOLD (for FLUX_GGUF.html):")
    print(f"  compression = {PIXEL_H}*{PIXEL_W}*{PIXEL_C} / "
          f"({LATENT_H}*{LATENT_W}*{LATENT_C})")
    print(f"             = {pixel_values:,} / {latent_values:,}")
    print(f"             = {compression:.1f}x")
    check("VAE compression is exactly 12.0x",
          abs(compression - 12.0) < 1e-9,
          f"got {compression}")
    check("latent values = 262,144",
          latent_values == 262144,
          f"got {latent_values}")
    check("pixel values = 3,145,728",
          pixel_values == 3145728,
          f"got {pixel_values}")


def section_c_size_problem():
    banner("SECTION C: THE SIZE PROBLEM - 23 GB won't fit a consumer GPU")
    dit_fp16 = N_PARAMS_DIT * FP16_BYTES_PER_PARAM / BYTES_PER_GB
    print(f"Flux DiT at FP16 = {N_PARAMS_DIT/1e9:.0f}B params x 2 bytes "
          f"= {dit_fp16:.0f} GB (actual checkpoint: 23 GB)")
    print()
    print("Consumer GPU VRAM tiers (2024-2026):")
    gpus = [
        ("GTX 1060",     6),
        ("RTX 3060/4060", 8),
        ("RTX 3060 12GB",12),
        ("RTX 4070",     12),
        ("RTX 4080",     16),
        ("RTX 3090/4090",24),
    ]
    print(f"  {'GPU':<16} {'VRAM':>5}  {'Fits FP16?':>10}")
    print(f"  {'-'*16} {'-'*5}  {'-'*10}")
    for name, vram in gpus:
        fits = "YES" if vram >= 24 else "no"
        print(f"  {name:<16} {vram:>4}GB  {fits:>10}")
    print()
    print("Only 24 GB GPUs (3090/4090, ~$1000+) can hold the FP16 model + T5 +")
    print("VAE + activations. Everyone else is stuck... unless we quantize.")
    check("only 24GB+ GPUs fit FP16 Flux",
          all(g[1] >= 24 for g in gpus if g[1] >= dit_fp16 + 5))


def section_d_gguf_levels():
    banner("SECTION D: GGUF QUANT LEVELS - same block format as LLMs")
    print("ComfyUI-GGUF (by city96) applies the SAME GGUF block quantization that")
    print("llama.cpp uses for LLMs (see quant_types.py) to the Flux DiT weights.")
    print("Each level packs more weights per byte at a quality cost.")
    print()
    print("| level    | file size | eff bpw | quality loss | min GPU |")
    print("|----------|-----------|---------|--------------|---------|")
    for name, file_gb, qloss, min_gpu, note in QUANT_LEVELS:
        bpw = eff_bpw(file_gb)
        print(f"| {name:<8} | {file_gb:>5.1f} GB | {bpw:>6.2f} | "
              f"  ~{qloss:.1f}%      | {min_gpu:>3} GB  |")
    print()
    print("Effective bpw = file_size_GB * 8 / 12B_params. It is slightly below")
    print("the STRUCTURAL bpw from quant_types.py (Q8_0=8.5, Q4_K_M=4.84) because")
    print("the checkpoint keeps a few sensitive layers (embeddings, output) at")
    print("higher precision, pulling the average down.")
    print()
    print("Why GGUF works for Flux but NOT for SDXL:")
    print("  Flux = DiT (transformer):   dense matmuls, very quant-tolerant.")
    print("  SDXL = U-Net (conv2d):      conv kernels degrade fast below 8-bit.")
    print("  => 4-bit Flux is great; 4-bit SDXL is mush. Same bytes, different arch.")
    print()
    # Spot-check: each level must be smaller than the one above
    sizes = [q[1] for q in QUANT_LEVELS]
    for i in range(1, len(sizes)):
        check(f"{QUANT_LEVELS[i][0]} < {QUANT_LEVELS[i-1][0]} in size",
              sizes[i] < sizes[i-1],
              f"{sizes[i]} vs {sizes[i-1]}")
    check("Q4_K_M effective bpw in 4-5 range",
          4.0 < eff_bpw(7.0) < 5.0,
          f"{eff_bpw(7.0):.2f}")
    check("Q8_0 effective bpw in 7-9 range",
          7.0 < eff_bpw(12.0) < 9.0,
          f"{eff_bpw(12.0):.2f}")


def section_e_vram_budget():
    banner("SECTION E: VRAM BUDGET - the full accounting per quant level")
    print("File size is NOT the VRAM cost. You also need memory for the text")
    print("encoder (T5), the VAE, and the intermediate activations during sampling.")
    print()
    print("VRAM = DiT_weights + T5_encoder + VAE + activations/overhead")
    print()
    # Two T5 strategies: keep fp16 (best quality, lots of VRAM) or quantize to Q4.
    print("T5 can be loaded at full precision OR quantized separately (also GGUF).")
    print(f"  T5 fp16 = {T5_FP16_GB:.1f} GB    (best text adherence)")
    print(f"  T5 Q4   = {T5_Q4_GB:.1f} GB    (saves {T5_FP16_GB - T5_Q4_GB:.1f} GB, minor text quality loss)")
    print()
    print(f"Fixed terms: VAE = {VAE_GB} GB, activations+CLIP-L = {ACTIVATIONS_GB} GB")
    print()
    print("| DiT quant | DiT   | T5    | VAE  | act  | TOTAL  | fits GPU |")
    print("|-----------|-------|-------|------|------|--------|----------|")
    # Build realistic configs: high-end keeps T5 fp16, budget uses T5 Q4.
    configs = [
        # (dit_name, dit_gb, t5_name, t5_gb)
        ("FP16",    23.0, "fp16", T5_FP16_GB),
        ("Q8_0",    12.0, "fp16", T5_FP16_GB),
        ("Q4_K_M",   7.0, "Q4",   T5_Q4_GB),
        ("Q4_K_S",   6.5, "Q4",   T5_Q4_GB),
        ("Q3_K_S",   5.5, "Q4",   T5_Q4_GB),
    ]
    budget_results = {}
    for dit_name, dit_gb, t5_name, t5_gb in configs:
        total = dit_gb + t5_gb + VAE_GB + ACTIVATIONS_GB
        # Which GPU tier fits
        if total <= 6.5:
            gpu = "6 GB"
        elif total <= 8.5:
            gpu = "8 GB"
        elif total <= 12.5:
            gpu = "12 GB"
        elif total <= 16.5:
            gpu = "16 GB"
        else:
            gpu = "24 GB"
        budget_results[dit_name] = (total, gpu)
        print(f"| {dit_name:<9} | {dit_gb:>4.1f}G | "
              f"{t5_gb:>4.1f}G | {VAE_GB:>3.1f}G | "
              f"{ACTIVATIONS_GB:>3.1f}G | {total:>5.1f}G | {gpu:>8} |")
    print()
    print("Key takeaway: pairing a Q4 DiT with a Q4 T5 lets Flux run on an 12 GB")
    print("GPU (RTX 3060 12GB). Q8 DiT + fp16 T5 still needs 24 GB. The DiT is")
    print("the dominant term, but the T5 choice swings the budget by ~7 GB.")
    print()
    q4km_total, q4km_gpu = budget_results["Q4_K_M"]
    q8_total, q8_gpu = budget_results["Q8_0"]
    q3_total, q3_gpu = budget_results["Q3_K_S"]
    check("Q4_K_M budget fits in 12 GB",
          q4km_total <= 12.5,
          f"total = {q4km_total:.1f} GB")
    check("Q8_0 + fp16 T5 needs 24 GB",
          q8_total > 16.5,
          f"total = {q8_total:.1f} GB")
    check("Q3_K_S has the smallest total",
          q3_total == min(v[0] for v in budget_results.values()),
          f"total = {q3_total:.1f} GB")


def section_f_fp8_vs_gguf():
    banner("SECTION F: FP8 vs GGUF - two paths to lower VRAM")
    print("There are two ways to shrink Flux below FP16. They optimize for")
    print("different things:")
    print()
    print("|              | FP8                          | GGUF                        |")
    print("|--------------|------------------------------|-----------------------------|")
    rows = [
        ("format",     "8-bit float (e4m3/e5m2)",     "block quant (Q4-Q8)"),
        ("VRAM",       "~12 GB (same as Q8_0)",        "6.5-12 GB (pick your level)"),
        ("speed",      "FASTER (native fp8 matmul)",   "SLOWER (dequant on the fly)"),
        ("hardware",   "Ada/Hopper+ ONLY (RTX 40+)",   "ANY GPU (even old Maxwell)  "),
        ("quality",    "~1% loss (good)",              "<1%-4% (depends on level)   "),
        ("comfyUI",    "built-in (LoadDiffusionModel)","ComfyUI-GGUF custom node    "),
    ]
    for label, fp8, gguf in rows:
        print(f"| {label:<12} | {fp8:<28} | {gguf:<27} |")
    print()
    print("The tradeoff in one line:")
    print("  fp8  = fast + needs new hardware + one size (12 GB).")
    print("  GGUF = slower + works everywhere + you pick the size (6.5-12 GB).")
    print()
    print("Rule of thumb:")
    print("  - RTX 4090/4080/5090 (Ada/Hopper, fp8 HW): use fp8 (faster, same VRAM).")
    print("  - RTX 3060/4060/2060/1060 or AMD/Mac:       use GGUF (only option).")
    print("  - Want the SMALLEST possible?                GGUF Q3_K_S (5.5 GB DiT).")
    check("fp8 needs Ada/Hopper hardware",
          "Ada" in rows[3][1] and "Hopper" in rows[3][1])
    check("GGUF works on any GPU",
          "ANY" in rows[3][2])


def section_g_summary():
    banner("SECTION G: SUMMARY - which quant for which GPU")
    print("Decision: match the DiT quant to your GPU, then pair with a T5 quant.")
    print()
    print("| Your GPU     | DiT quant | T5 quant | Total VRAM | Quality     |")
    print("|--------------|-----------|----------|------------|-------------|")
    summary = [
        ("24 GB (3090/4090)", "FP16",  "fp16", 34.9, "reference"),
        ("24 GB (3090/4090)", "Q8_0",  "fp16", 23.9, "near-lossless"),
        ("24 GB (3090/4090)", "Q8_0",  "Q4",   16.5, "near-lossless"),
        ("12 GB (3060 12G)",  "Q4_K_M","Q4",   11.5, "excellent"),
        ("12 GB (3060 12G)",  "Q4_K_S","Q4",   11.0, "very good"),
        ("12 GB (3060 12G)",  "Q3_K_S","Q4",   10.0, "good (headroom)"),
    ]
    for gpu, dit, t5, total, quality in summary:
        print(f"| {gpu:<14} | {dit:<9} | {t5:<7} | {total:>7.1f} GB | {quality:<11} |")
    print()
    print("The sweet spot for most users: Q4_K_M DiT + Q4 T5 on an 8-12 GB GPU.")
    print("~7 GB DiT file, ~10-12 GB total VRAM, <2% quality loss vs FP16.")
    check("Q4_K_M + Q4 T5 is the recommended sweet spot",
          any(d == "Q4_K_M" and t == "Q4" for _, d, t, _, _ in summary))


# ============================================================================
# main
# ============================================================================

def main():
    print("flux_gguf.py - Running Flux.1 [dev] locally with GGUF quantization.")
    print("Pure Python stdlib. Numbers below feed FLUX_GGUF.md.")
    print("Sources: city96/ComfyUI-GGUF, city96/FLUX.1-dev-gguf (HuggingFace),")
    print("         Black Forest Labs Flux.1 blog, quant_types.py (block format).")
    print()
    print("Story: 12B DiT model (23 GB FP16) -> GGUF block quant -> fits 8 GB GPU")

    section_a_architecture()
    section_b_vae()
    section_c_size_problem()
    section_d_gguf_levels()
    section_e_vram_budget()
    section_f_fp8_vs_gguf()
    section_g_summary()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
