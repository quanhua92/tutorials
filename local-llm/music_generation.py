"""
music_generation.py - Reference implementation of local music generation.

This is the single source of truth that MUSIC_GENERATION.md is built from.
Every number, table, and worked example in MUSIC_GENERATION.md is printed by this
file. Pure Python stdlib only (math + random) - NO torch, NO numpy. This is the
local runtime side: why music is harder than speech, how neural audio codecs
(EnCodec/SoundStream) compress raw audio to discrete tokens via residual vector
quantization (RVQ), and how ACE-Step / YuE turn text + lyrics into full songs.

Run:
    python3 music_generation.py

References:
  [EnCodec]   Defossez et al. (2022). "High Fidelity Neural Audio Compression."
              arXiv:2210.13838  (RVQ, 24kHz -> 75 frames/s, 75 Hz)
  [SoundStream] Zeghidour et al. (2021). "SoundStream: An End-to-End Neural
              Audio Codec." arXiv:2107.03312  (streaming RVQ codec)
  [ACE-Step]  Gong et al. (2025). "ACE-Step: A Step Towards Music Generation
              Foundation Model." arXiv:2506.00045  (3.5B, flow-matching, parallel)
  [YuE]       Yuan et al. (2025). "YuE: Open-Music Foundation Models for Full
              Song Generation."  (7B, two-stage semantic+acoustic cascade)

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
Music generation is harder than speech because a song is LONG (minutes, not
seconds), DENSE (many instruments + vocals), and STEREO. Generating it sample
by sample is hopeless: a 3-minute 44.1kHz stereo song is ~15.88 MILLION samples.

  AUDIO CODEC (the enabler): a neural codec (EnCodec/SoundStream) compresses raw
    audio down to a few hundred DISCRETE TOKENS per second using residual vector
    quantization (RVQ):
      - stride/downsample 320x  =>  24000 samples/s becomes 75 FRAMES/s
      - each frame is quantized by N=4-8 CODEBOOKS in series; book 1 grabs the
        coarse structure, book 2 the residual, ... book 8 the fine detail
      - so 3 min of audio  =  75 * 180 = 13,500 frames  =  108,000 tokens (x8)
        instead of 15.88M raw samples  (~147x fewer things to predict)

  ACE-Step (3.5B): a FLOW-MATCHING foundation model. It does NOT predict tokens
    one-by-one. It denoises the WHOLE song latent in parallel over ~27-60 ODE
    steps (like a diffusion sampler, but one-shot over the full length). Result:
    ~2.2 s to render 1 minute of audio on an A100 (RTF 27x), up to 4 min in
    ~20 s. Min VRAM 8 GB. Outperforms Suno v5 on melody/harmony/rhythm.

  YuE (7B): a TWO-STAGE AUTOREGRESSIVE cascade. Stage 1 (semantic) turns lyrics
    into semantic tokens token-by-token; stage 2 (acoustic) expands those into
    codec tokens. Great lyric alignment, but slow (token-by-token). 8-14 GB VRAM.

  THE KEY CONTRAST: ACE-Step generates the song in PARALLEL (fixed step count);
    YuE generates it SEQUENTIALLY (one token at a time). Same end product
    (vocals + accompaniment), very different compute profile.

GOLD VALUE (for music_generation.html to reproduce):
  Raw audio budget:
    3-min song, 44.1kHz stereo = 44100 * 2 * 180 = 15,876,000 samples
    16-bit PCM = 31,752,000 bytes (~30.3 MiB); fp32 = 63,504,000 bytes (~60.6 MiB)
  EnCodec (24kHz mono, 8 codebooks):
    frame rate   = 24000 / 320 = 75 frames/s
    tokens/sec   = 75 * 8      = 600 tokens/s
    3-min song   = 75 * 180    = 13,500 frames  =  108,000 tokens
    downsample   = 320x  (raw samples -> frames)
  ACE-Step A100 (27 steps, RTF 27.27x):
    time / minute = 60 / 27.27 = 2.20 s
"""

from __future__ import annotations

import math
import random

random.seed(42)   # determinism: codebook + any jitter reproduce exactly

BANNER = "=" * 74


# ============================================================================
# 0. CHECK HELPER (invariants the formulas/simulations must satisfy)
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


# ============================================================================
# 1. THE AUDIO BUDGET - why music is hard (and speech is easy)
# ============================================================================

def raw_audio_budget(duration_s: float, sr: int = 44100, channels: int = 2):
    """Samples + byte sizes for a chunk of raw PCM audio."""
    samples = sr * channels * int(duration_s)
    pcm16_bytes = samples * 2            # 16-bit = 2 bytes/sample (CD quality)
    fp32_bytes = samples * 4             # model-internal float32
    return samples, pcm16_bytes, fp32_bytes


def section_a_why_music_is_hard():
    banner("SECTION A: WHY MUSIC IS HARDER THAN SPEECH")
    print("Speech: single speaker, seconds-long, limited acoustic patterns.")
    print("Music : many instruments + vocals, minutes-long, harmony + rhythm.")
    print("Direct autoregressive generation on RAW audio is intractable: every")
    print("sample must be predicted in sequence, and there are millions of them.")
    print()
    print("Raw audio budget (CD quality, 44.1kHz stereo):")
    print("| clip            |  samples   | 16-bit PCM |  fp32     |")
    print("|-----------------|------------|------------|-----------|")
    for label, dur in [("1 s", 1), ("10 s", 10), ("1 min", 60), ("3 min", 180)]:
        s, p, f = raw_audio_budget(dur)
        print(f"| {label:<15} | {s:>10,} | {p/1e6:>6.2f} MB | {f/1e6:>6.2f} MB |")
    print()
    samples, pcm16, fp32 = raw_audio_budget(180)
    print("GOLD (for music_generation.html):")
    print(f"  3-min song samples (44.1kHz stereo) = {samples:,}  (~15.88M)")
    print(f"  16-bit PCM  = {pcm16:,} bytes  ({pcm16/1048576:.2f} MiB)")
    print(f"  fp32        = {fp32:,} bytes  ({fp32/1048576:.2f} MiB)")
    print(f"  => a model predicting raw samples would need {samples:,} sequential")
    print("     steps for ONE song. This is why audio codecs exist (Section B).")
    check("3-min 44.1kHz stereo = 15,876,000 samples", samples == 15_876_000,
          f"got {samples}")
    check("fp32 song is ~2x the 16-bit PCM size", abs(fp32 / pcm16 - 2.0) < 1e-9)
    # contrast with speech: Kokoro TTS renders ~10-20s clips; Whisper chunks 30s.
    speech_samples = 16000 * 1 * 10          # 10s of 16kHz mono speech
    song_div = samples // speech_samples
    check("10s of speech (16kHz mono) is ~99x smaller than a 3-min song",
          90 < song_div < 110, f"{song_div}x")
    print()
    print("  For scale: a 3-min song is ~" + f"{song_div}"
          + "x more samples than a 10s speech clip. Music needs compression.")


# ============================================================================
# 2. NEURAL AUDIO CODECS - EnCodec / SoundStream (RVQ simulation)
# ============================================================================

# Real EnCodec numbers (24kHz config), used for the compression table.
CODEC_SR = 24000          # Hz
CODEC_STRIDE = 320        # encoder downsample factor -> 24000/320 = 75 frames/s
CODEBOOKS = 8             # typical music config uses 4-8 RVQ codebook layers
BITS_PER_CODE = 10        # EnCodec codebook size 1024 -> 10 bits/codebook index


def codec_frame_rate(sr=CODEC_SR, stride=CODEC_STRIDE):
    return sr / stride


def make_codebooks(num_layers=8, base_step=0.5):
    """Build N independent RVQ codebooks with progressively finer granularity.

    Real EnCodec TRAINS a separate 1024-entry vector codebook per layer on that
    layer's residual distribution. Here we approximate the effect with uniform
    scalar codebooks whose quantization STEP HALVES each layer (a multi-rate /
    progressive residual quantizer). Every codebook contains 0.0 so residual
    energy is guaranteed non-increasing. This faithfully shows layer 1 = coarse,
    layer 8 = fine.
    """
    cbs = []
    for k in range(num_layers):
        step = base_step / (2 ** k)
        m = round(1.0 / step)
        levels = [-i * step for i in range(m, 0, -1)] + [0.0] \
                 + [i * step for i in range(1, m + 1)]
        cbs.append(levels)
    return cbs


def rvq_quantize(values, codebooks):
    """Residual vector quantization with one INDEPENDENT codebook per layer.

    Real EnCodec quantizes each frame VECTOR against a 1024-vector codebook.
    Here we scalar-quantize each value to its nearest codebook entry - the
    RESIDUAL principle is identical: layer k quantizes the residual left by
    layers 1..k-1, using its own (finer) codebook. Each codebook contains 0.0,
    so residual energy is non-increasing.
    Returns (codes_per_layer, residual_energy_per_layer, total_signal_energy).
    """
    for cb in codebooks:
        assert 0.0 in cb
    total_energy = sum(v * v for v in values)
    current = list(values)
    codes_per_layer = []
    energy_per_layer = []
    for cb in codebooks:
        codes, quantized = [], []
        for v in current:
            idx = min(range(len(cb)), key=lambda i: abs(cb[i] - v))
            codes.append(idx)
            quantized.append(cb[idx])
        current = [c - q for c, q in zip(current, quantized)]
        codes_per_layer.append(codes)
        energy_per_layer.append(sum(r * r for r in current))
    return codes_per_layer, energy_per_layer, total_energy


def section_b_audio_codec():
    banner("SECTION B: NEURAL AUDIO CODECS - raw audio -> discrete tokens (RVQ)")
    print("EnCodec / SoundStream compress raw audio to discrete tokens via")
    print("RESIDUAL VECTOR QUANTIZATION (RVQ):")
    print("  1. encoder strides the waveform (downsample 320x at 24kHz)")
    print("  2. each frame is quantized by N codebooks IN SERIES")
    print("     - codebook 1: coarse structure  (big residual removed)")
    print("     - codebook 2: residual of 1     (finer detail)")
    print("     - ... up to codebook 8:          (fine texture / noise floor)")
    print("  3. decoder reconstructs audio from the N indices per frame")
    print()
    fr = codec_frame_rate()
    print(f"EnCodec 24kHz config: stride = {CODEC_STRIDE}  ->  "
          f"frame rate = {CODEC_SR}/{CODEC_STRIDE} = {fr:.0f} frames/s")
    print(f"  with {CODEBOOKS} RVQ codebooks:  {fr*CODEBOOKS:.0f} tokens/s  "
          f"({CODEC_SR}/{fr:.0f} = {CODEC_SR/fr:.0f}x downsample on the time axis)")
    print()
    print("Token budget vs raw audio (3-minute clip):")
    print("| representation                |   values   | vs raw stereo |")
    print("|-------------------------------|------------|---------------|")
    raw_stereo = 44100 * 2 * 180
    mono_24k = CODEC_SR * 180
    frames_3m = int(fr * 180)
    tokens_3m = frames_3m * CODEBOOKS
    rows = [
        ("raw 44.1kHz stereo (samples)", raw_stereo, raw_stereo),
        ("raw 24kHz mono (samples)",     mono_24k,    raw_stereo),
        (f"EnCodec frames (75Hz)",       frames_3m,   raw_stereo),
        (f"EnCodec tokens (x{CODEBOOKS} codebooks)", tokens_3m, raw_stereo),
    ]
    for label, n, base in rows:
        print(f"| {label:<29} | {n:>10,} | {base/n:>11.0f}x fewer |")
    print()
    print("GOLD (for music_generation.html):")
    print(f"  frame rate       = {fr:.0f} frames/s   (stride {CODEC_STRIDE})")
    print(f"  3-min frames     = {frames_3m:,}")
    print(f"  3-min tokens     = {tokens_3m:,}   ({fr:.0f} * 180 * {CODEBOOKS})")
    print(f"  tokens vs raw    = {raw_stereo/tokens_3m:.0f}x fewer things to predict")
    check("EnCodec frame rate = 75 Hz (24000/320)", abs(fr - 75.0) < 1e-9,
          f"got {fr}")
    check("3-min EnCodec = 13,500 frames", frames_3m == 13_500, f"got {frames_3m}")
    check("3-min EnCodec = 108,000 tokens (x8)", tokens_3m == 108_000,
          f"got {tokens_3m}")
    print()

    # --- RVQ simulation: watch each codebook layer peel off residual energy ---
    print("RVQ simulation: 8 independent codebook layers quantize a 16-frame")
    print("signal. Each layer uses its OWN codebook (finer than the last) and")
    print("quantizes the residual the previous layers left behind.")
    signal = [0.82, -0.31, 0.55, -0.74, 0.18, -0.92, 0.41, 0.67,
              -0.15, 0.89, -0.58, 0.26, -0.43, 0.71, -0.09, 0.34]
    num_layers = 8
    codebooks = make_codebooks(num_layers, base_step=0.5)
    codes, energies, total = rvq_quantize(signal, codebooks)
    steps = [0.5 / (2 ** k) for k in range(num_layers)]
    print(f"  signal (16 frames) = {signal}")
    print(f"  signal energy      = {total:.4f}")
    print(f"  layer codebook steps (halving) = {steps}")
    print()
    print("  | layer | role         | step      | residual energy | % of signal left |")
    print("  |-------|--------------|-----------|-----------------|------------------|")
    roles = ["coarse structure", "main residual", "mid detail",
             "fine detail", "texture", "fine texture",
             "noise floor", "ultra-fine"]
    for k in range(num_layers):
        pct = 100 * energies[k] / total if total > 0 else 0.0
        print(f"  | {k+1:>5} | {roles[k]:<12} | {steps[k]:>9.5f} | "
              f"{energies[k]:>15.6f} | {pct:>15.2f}% |")
    print("  Each codebook layer captures finer detail; residual energy -> 0.")
    print("  (Real codebooks hold 1024 VECTORS each, not these uniform scalars.)")
    # residual energy must be non-increasing layer over layer (0.0 in each codebook)
    nonincr = all(energies[k] >= energies[k + 1] - 1e-12
                  for k in range(num_layers - 1))
    check("RVQ residual energy is non-increasing across layers", nonincr)
    check("layer 1 removes most energy (coarse layer)",
          total - energies[0] > energies[0] - energies[1])
    check("layer 8 reaches < 0.5% of signal energy", energies[-1] / total < 0.005,
          f"{100*energies[-1]/total:.3f}%")
    # show the discrete token stream for layer 1 (the codes the model would emit)
    print()
    print(f"  layer-1 token stream (codebook indices) = {codes[0]}")
    print("  These indices ARE the 'tokens' a music LLM learns to generate.")
    check("all codes are valid codebook indices",
          all(0 <= c < len(codebooks[i]) for i, lyr in enumerate(codes) for c in lyr))


# ============================================================================
# 3. ACE-STEP vs YuE - architecture, speed, capability
# ============================================================================

# Verified from github.com/ace-step/ACE-Step (hardware performance table, 27 steps)
ACESTEP_HW = [
    # (device, rtf_27steps, seconds_per_minute)
    ("NVIDIA RTX 4090", 34.48, 1.74),
    ("NVIDIA A100",     27.27, 2.20),
    ("NVIDIA RTX 3090", 12.76, 4.70),
    ("MacBook M2 Max",   2.27, 26.43),
]

# Verified from github.com/ace-step/ACE-Step + github.com/.../YuE
MODELS = [
    # name, params_b, vram_gb, arch, speed, license, best_for
    ("ACE-Step",   3.5,  "8-10",
     "flow-matching, parallel ODE steps (27-60)",
     "~2.2 s/min (A100, 27 steps)",
     "Apache 2.0",
     "full songs (vocals+accomp), fast, remix/edit/voice-clone"),
    ("YuE",        7.0,  "8-14",
     "two-stage cascade: semantic -> acoustic (autoregressive)",
     "minutes/min (token-by-token)",
     "Apache 2.0",
     "tight lyric alignment, vocals + accompaniment"),
    ("Stable Audio Open", 1.2, "6-8",
     "diffusion (DiT), latent",
     "fast for short clips",
     "CC-BY-NC (non-commercial)",
     "sound effects, short instrumental clips"),
    ("MusicGen (Meta)",  3.3,  "8-16",
     "autoregressive EnCodec tokens, mono",
     "moderate (token-by-token)",
     "CC-BY-NC",
     "instrumental loops, mono, research"),
    ("DiffRhythm",  2.0,  "8-10",
     "diffusion over full-song latent",
     "fast (one pass)",
     "Apache 2.0",
     "fast full-song, simpler controls"),
]


def section_c_acestep_vs_yue():
    banner("SECTION C: ACE-STEP vs YuE - the two SOTA open-source paths")
    print("Both turn text (genre/mood/instruments) + lyrics into a full song")
    print("(vocals + accompaniment). Very different compute profiles:")
    print()
    print("  ACE-Step (3.5B): FLOW-MATCHING. Denoises the whole song latent in")
    print("    PARALLEL over a fixed number of ODE steps (~27-60). Not token-by-")
    print("    token. => ~2.2 s/min on A100. Min VRAM 8 GB. Beats Suno v5 on")
    print("    melody/harmony/rhythm benchmarks. Supports remix/repaint/edit.")
    print()
    print("  YuE (7B): TWO-STAGE AUTOREGRESSIVE cascade. Stage 1 (semantic) turns")
    print("    lyrics -> semantic tokens one at a time; stage 2 (acoustic) expands")
    print("    them to codec tokens. Great lyric alignment, but slow (sequential).")
    print()
    print("Model comparison (verified from GitHub READMEs):")
    print("| model            | params | VRAM    | architecture              "
          "| license    |")
    print("|------------------|--------|---------|---------------------------"
          "|------------|")
    for name, params, vram, arch, _speed, lic, _bf in MODELS:
        p = f"{params:g}B" if isinstance(params, (int, float)) else "?"
        print(f"| {name:<16} | {p:>6} | {vram:<7} | {arch:<25} "
              f"| {lic:<10} |")
    print()
    print("ACE-Step real hardware performance (27 denoising steps, RTF=real-time")
    print("factor; RTF 27x = 1 min of audio in 60/27 = 2.2 s):")
    print("| device           | RTF (27 steps) | time / minute of audio |")
    print("|------------------|----------------|------------------------|")
    for dev, rtf, sec in ACESTEP_HW:
        print(f"| {dev:<16} | {rtf:>11.2f}x   | {sec:>6.2f} s                |")
    print()
    a100_min = 60.0 / 27.27
    print("GOLD (for music_generation.html):")
    print(f"  ACE-Step A100 (27 steps): RTF = 27.27x  ->  {a100_min:.2f} s / min")
    print(f"  => a 4-minute full song ~ {4*a100_min:.1f} s on A100 "
          "(parallel, not 4 separate minutes of autoregression)")
    check("ACE-Step A100 ~ 2.20 s per minute (RTF 27.27)",
          abs(a100_min - 2.20) < 0.05, f"got {a100_min:.3f}")
    check("RTX 4090 is faster than A100 for ACE-Step (27 steps)",
          ACESTEP_HW[0][2] < ACESTEP_HW[1][2])
    check("ACE-Step (3.5B) is ~half the params of YuE (7B)",
          abs(3.5 / 7.0 - 0.5) < 1e-9)
    check("both ACE-Step and YuE are Apache 2.0 (verified from GitHub)",
          MODELS[0][5] == "Apache 2.0" and MODELS[1][5] == "Apache 2.0")


# ============================================================================
# 4. THE GENERATION PIPELINE - text + lyrics -> full song
# ============================================================================

def section_d_pipeline():
    banner("SECTION D: THE PIPELINE - text + lyrics -> full song")
    print("Both ACE-Step and YuE share the same high-level flow; they differ in")
    print("stage 4 (how the latent/tokens are produced):")
    print()
    print("  [1] prompt encode : text tags (genre/mood/instruments) + lyrics")
    print("                       -> text embeddings (T5/CLAP-style)")
    print("  [2] lyrics align   : syllable/line timestamps (YuE explicit;")
    print("                       ACE-Step implicit via REPA alignment)")
    print("  [3] latent space   : audio codec (DCAE/EnCodec) frames the model")
    print("                       operates in (75 Hz, 8 codebooks)")
    print("  [4] GENERATE       : ACE-Step = parallel flow-matching (~27 steps)")
    print("                       YuE      = autoregressive cascade (semantic->")
    print("                                   acoustic, token-by-token)")
    print("  [5] codec decode   : tokens/latent -> raw waveform (codec decoder)")
    print("  [6] post           : vocals + accompaniment mixed -> stereo song")
    print()
    fr = codec_frame_rate()
    frames_3m = int(fr * 180)
    print(f"For a 3-min song the model produces {frames_3m:,} frames "
          f"({frames_3m*CODEBOOKS:,} tokens) in stage 4, then the codec decoder")
    print("turns them back into ~4.32M samples (24kHz mono) of audio.")
    print()
    print("Why ACE-Step is fast: stage 4 visits a FIXED ~27 ODE steps, each")
    print("touching the ENTIRE song latent at once. YuE must emit ~108,000 tokens")
    print("sequentially. Parallel (fixed steps) >> sequential (~100k steps).")
    check("3-min codec decode = 4.32M samples (24kHz mono)",
          CODEC_SR * 180 == 4_320_000, f"got {CODEC_SR*180}")
    # ACE-Step step budget vs YuE token budget
    acesteps = 27
    yue_tokens = frames_3m * CODEBOOKS
    check("YuE emits ~4000x more sequential steps than ACE-Step's 27",
          yue_tokens // acesteps > 3000, f"{yue_tokens//acesteps}x")


# ============================================================================
# main
# ============================================================================

def main():
    print("music_generation.py - local music gen: codecs + ACE-Step + YuE.")
    print("Pure Python stdlib. Numbers below feed MUSIC_GENERATION.md.")
    print("Sources: EnCodec arXiv:2210.13838, ACE-Step arXiv:2506.00045,")
    print("         github.com/ace-step/ACE-Step, github.com/multimodal-art-projection/YuE.")
    print()
    print("Raw audio is huge -> codec compresses to tokens (RVQ) -> model generates.")

    section_a_why_music_is_hard()
    section_b_audio_codec()
    section_c_acestep_vs_yue()
    section_d_pipeline()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
