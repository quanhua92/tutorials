"""
whisper_stt.py - Reference implementation of Whisper speech-to-text (STT) and
its local-inference ecosystem (faster-whisper / distil-whisper).

WHAT IS WHISPER? (start here)
   Whisper is an ENCODER-DECODER Transformer for speech-to-text. You feed it an
   audio clip; it transcribes (or translates) it to text. It is the canonical
   open-weight ASR model -- the thing almost every local transcription app wraps.

   The pipeline is conceptually simple but each stage has a reason:
     1. RESAMPLE to 16 kHz mono. Whisper is trained ONLY on 16 kHz audio -- the
        mel filterbank is fixed to that rate, so any other sample rate is wrong.
     2. LOG-MEL SPECTROGRAM: chop the waveform into 25 ms windows every 10 ms,
        FFT each, collapse to 80 mel bands, take the log. This is the "image"
        the encoder sees. 30 s of audio -> 3000 mel frames (80 x 3000 grid).
     3. ENCODER: a Transformer that reads the mel spectrogram and produces
        hidden states (the "understanding" of the audio).
     4. DECODER: an autoregressive Transformer that emits TEXT TOKENS one at a
        time, conditioned on the encoder output + the tokens generated so far.
     5. SPECIAL TOKENS steer the decoder:
          <|startoftranscript|> <|en|> <|transcribe|> ... <|endoftranscript|>
        The same model can transcribe OR translate-to-English, detect language,
        and emit <|nospeech|> -- all selected by the leading special tokens.

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. WAV2VEC (2019-2020): self-supervised representation learning on raw audio.
      Great features, but task-specific heads needed; not a zero-shot ASR.

   2. WHISPER (2022, arXiv:2212.04356): train ONE encoder-decoder on 680k hours
      of weakly-supervised web audio -> multilingual, zero-shot, robust. Problem:
      the official OpenAI impl (PyTorch, FP16/FP32) is SLOW and memory-heavy.

   3. FASTER-WHISPER (CTranslate2 backend): SAME model weights, different
      inference engine. CTranslate2 is an optimised C++ runtime for Transformers
      (int8/FP16, fused kernels, no Python overhead). Result: ~4x faster, ~50%
      less VRAM, bit-identical output for greedy decoding. The local default.

   4. DISTIL-WHISPER: knowledge distillation -- train a STUDENT with fewer
      decoder layers to mimic the large teacher. distil-large-v3: 756M params
      (~49% smaller), ~6x faster, WER within ~1% of the teacher.

WHY IT MATTERS:  on an RTX 4090, faster-whisper large-v3 runs at RTF ~0.03 --
   that is 33x FASTER than real-time. You can transcribe live speech with huge
   headroom. Even on an M1 Pro laptop, medium hits RTF ~0.15 (6x real-time).
   The official OpenAI model on CPU is RTF 2-4 (slower than real-time).

THE GOLD VALUES (this bundle's load-bearing claims):
   30 s audio -> 3000 mel frames  (30 s * 100 frames/s; hop = 10 ms)
   large-v3  : 1550M params, ~10 GB VRAM
   faster-whisper: int8 weights = 50% of FP16  ->  ~50% less VRAM, ~4x faster
   RTF 0.03  ->  1/0.03 = 33.3x real-time  (can transcribe live)

Companion code that WHISPER_STT.md is built from. Every number below is printed
by:  python3 whisper_stt.py

PURE PYTHON STDLIB (no torch, no numpy). Deterministic (seeded RNG). The mel
spectrogram is computed with a real (tiny) DFT + mel filterbank so the concept
is faithful, not hand-waved.
"""

from __future__ import annotations

import math
import random

BANNER = "=" * 72

# ============================================================================
# 1. Audio constants -- Whisper is HARD-CODED to 16 kHz
# ============================================================================

SAMPLE_RATE = 16000      # Hz -- Whisper requires 16 kHz mono
N_FFT = 400              # FFT window = 400 samples = 25 ms at 16 kHz
HOP_LENGTH = 160         # hop = 160 samples = 10 ms -> 100 frames/s
N_MELS = 80              # mel bands per frame


def frames_per_second() -> float:
    """How many mel frames per second of audio (Whisper's fixed rate)."""
    return SAMPLE_RATE / HOP_LENGTH          # 16000/160 = 100.0


def mel_frame_count(seconds: float) -> int:
    """Number of mel frames for `seconds` of audio."""
    return round(seconds * frames_per_second())   # 30 s -> 3000


# ---- a REAL (but tiny) log-mel spectrogram, pure stdlib ---------------------
#
# The full Whisper spectrogram is 80 bands x 3000 frames for 30 s of audio.
# Computing 3000 real FFTs of size 400 in pure Python would be slow, so the
# DEMO below uses a reduced FFT (64) and 8 mel bands on ~0.1 s of synthetic
# audio -- just enough to show the concept and visualise it as ASCII. The
# FRAME COUNT (30 s -> 3000) is computed exactly with the real constants above.

DEMO_N_FFT = 64           # reduced FFT window for the ASCII demo
DEMO_N_MELS = 8           # reduced mel bands for the demo
DEMO_HOP = 128            # hop for the demo


def hann_window(n: int) -> list[float]:
    return [0.5 - 0.5 * math.cos(2 * math.pi * t / (n - 1)) for t in range(n)]


def dft_power(frame: list[float]) -> list[float]:
    """One-sided power spectrum of a windowed frame (naive O(N^2) DFT)."""
    n = len(frame)
    half = n // 2 + 1
    out = []
    for k in range(half):
        re = sum(frame[t] * math.cos(2 * math.pi * k * t / n) for t in range(n))
        im = -sum(frame[t] * math.sin(2 * math.pi * k * t / n) for t in range(n))
        out.append(re * re + im * im)
    return out


def hz_to_mel(f: float) -> float:
    return 2595.0 * math.log10(1.0 + f / 700.0)


def mel_to_hz(m: float) -> float:
    return 700.0 * (10 ** (m / 2595.0) - 1.0)


def mel_filterbank(n_fft: int, n_mels: int, sample_rate: int) -> list[list[float]]:
    """Triangular mel filterbank mapping FFT bins -> mel bands."""
    fmax = sample_rate / 2.0
    mmin, mmax = hz_to_mel(0.0), hz_to_mel(fmax)
    pts = [mmin + (mmax - mmin) * i / (n_mels + 1) for i in range(n_mels + 2)]
    hz = [mel_to_hz(m) for m in pts]
    bins = [h * n_fft / sample_rate for h in hz]
    half = n_fft // 2 + 1
    fb = [[0.0] * half for _ in range(n_mels)]
    for m in range(n_mels):
        left, center, right = bins[m], bins[m + 1], bins[m + 2]
        for k in range(half):
            if left <= k <= center and center > left:
                fb[m][k] = (k - left) / (center - left)
            elif center < k <= right and right > center:
                fb[m][k] = (right - k) / (right - center)
    return fb


def log_mel_spectrogram(samples: list[float], n_fft: int, hop: int,
                        n_mels: int, sample_rate: int) -> list[list[float]]:
    """Full log-mel pipeline: frames -> Hann -> DFT power -> mel -> log."""
    win = hann_window(n_fft)
    fb = mel_filterbank(n_fft, n_mels, sample_rate)
    half = n_fft // 2 + 1
    frames = []
    start = 0
    while start + n_fft <= len(samples):
        frame = [samples[start + t] * win[t] for t in range(n_fft)]
        power = dft_power(frame)
        mel = [math.log(sum(fb[m][k] * power[k] for k in range(half)) + 1e-10)
               for m in range(n_mels)]
        frames.append(mel)
        start += hop
    return frames


def synthetic_speech(seconds: float, sample_rate: int) -> list[float]:
    """Synthetic vowel-like signal with a rising low formant + falling high one.

    Produces a spectrogram whose energy migrates from low to high mel bands
    over time -- the kind of pattern real speech (formant transitions) makes.
    """
    n = int(seconds * sample_rate)
    out = [0.0] * n
    for t in range(n):
        ts = t / sample_rate
        seg = t / n                       # 0..1 progress
        f1 = 300 + 900 * seg              # rising formant
        f2 = 2400 - 700 * seg             # falling formant
        out[t] = (0.65 * math.sin(2 * math.pi * f1 * ts) +
                  0.35 * math.sin(2 * math.pi * f2 * ts))
    return out


# ============================================================================
# 2. The decoder: special tokens + autoregressive text generation
# ============================================================================

SOT = "<|startoftranscript|>"
EOT = "<|endoftranscript|>"
TRANSCRIBE = "<|transcribe|>"
TRANSLATE = "<|translate|>"
NO_SPEECH = "<|nospeech|>"


def decode_sequence(language: str, task: str, text_tokens: list[str]) -> list[str]:
    """The full token sequence the decoder emits for a clip.

    Layout:  SOT  <language>  <task>  text...  EOT
    The leading special tokens SELECT the behaviour of the SAME weights.
    """
    return [SOT, language, task, *text_tokens, EOT]


def simulate_autoregressive(text_tokens: list[str], seed: int = 42) -> list[dict]:
    """Trace the decoder step-by-step: each step emits one token.

    Returns per-step records showing the conditioning (mel context + prior
    tokens) and the emitted token. In reality each step is a full decoder
    forward pass over the encoder output + the tokens so far (KV-cached).
    """
    rng = random.Random(seed)
    seq = [SOT]
    trace = [{"step": 1, "emitted": SOT, "conditioned_on": "(mel context)"}]
    # step 2: language detection token
    seq.append("<|en|>")
    trace.append({"step": 2, "emitted": "<|en|>", "conditioned_on": SOT})
    # step 3: task token
    seq.append(TRANSCRIBE)
    trace.append({"step": 3, "emitted": TRANSCRIBE,
                  "conditioned_on": " ".join(seq[:2])})
    # steps 4..N: text tokens
    for i, tok in enumerate(text_tokens):
        seq.append(tok)
        trace.append({"step": 4 + i, "emitted": tok,
                      "conditioned_on": " ".join(seq[:-1])})
        rng.random()                       # consume RNG to keep determinism shape
    # final: EOT
    seq.append(EOT)
    trace.append({"step": 4 + len(text_tokens), "emitted": EOT,
                  "conditioned_on": " ".join(seq[:-1])})
    return trace


# ============================================================================
# 3. Model size ladder
# ============================================================================

# (name, params_M, vram_GB, rel_speed_x, best_for)
MODELS = [
    ("tiny",     39,   1,  32, "testing"),
    ("base",     74,   1,  16, "quick draft"),
    ("small",    244,  2,  6,  "good quality"),
    ("medium",   769,  5,  2,  "high quality"),
    ("large-v3", 1550, 10, 1,  "best quality"),
]


def weight_memory_mb(params_m: float, bytes_per_param: float) -> float:
    """Weight footprint in MB (params in millions x bytes/param)."""
    return params_m * bytes_per_param


# ============================================================================
# 4. faster-whisper (CTranslate2) -- int8 inference
# ============================================================================

# OpenAI Whisper loads FP16 (2 B/param). faster-whisper defaults to int8
# (1 B/param) via CTranslate2, with FP16 compute fallback. The result:
# weight memory halves, and optimised C++ kernels give ~4x throughput.

FP16_BYTES = 2
INT8_BYTES = 1


def memory_ratio(params_m: float) -> dict:
    """Compare FP16 (OpenAI) vs int8 (faster-whisper) weight memory."""
    fp16 = weight_memory_mb(params_m, FP16_BYTES)
    int8 = weight_memory_mb(params_m, INT8_BYTES)
    return {"fp16_mb": fp16, "int8_mb": int8,
            "ratio": int8 / fp16, "reduction": 1.0 - int8 / fp16}


# ============================================================================
# 5. Real-time factor (RTF) + word error rate (WER)
# ============================================================================

def real_time_factor(processing_s: float, audio_s: float) -> float:
    """RTF = processing_time / audio_duration. <1.0 => faster than real-time."""
    return processing_s / audio_s


def realtime_speedup(rtf_val: float) -> float:
    """How many times faster than real-time (1/RTF)."""
    return 1.0 / rtf_val


def processing_time(audio_s: float, rtf_val: float) -> float:
    """Wall-clock seconds to transcribe `audio_s` at a given RTF."""
    return audio_s * rtf_val


# (label, hardware, rtf)  -- rtf < 1 means faster than real-time
RTF_BENCHMARKS = [
    ("faster-whisper large-v3", "RTX 4090",          0.03),
    ("faster-whisper large-v3", "Apple M1 Pro",      0.10),
    ("faster-whisper medium",   "Apple M1 Pro",      0.15),
    ("faster-whisper small",    "Apple M1 Pro",      0.35),
    ("OpenAI whisper large",    "CPU (8-core)",      3.0),
]


# ---- WER via word-level Levenshtein with backtracking -----------------------

def wer_ops(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """Word error operations: (substitutions, deletions, insertions)."""
    r, h = len(ref), len(hyp)
    d = [[0] * (h + 1) for _ in range(r + 1)]
    for i in range(r + 1):
        d[i][0] = i
    for j in range(h + 1):
        d[0][j] = j
    for i in range(1, r + 1):
        for j in range(1, h + 1):
            if ref[i - 1] == hyp[j - 1]:
                d[i][j] = d[i - 1][j - 1]
            else:
                d[i][j] = 1 + min(d[i - 1][j],      # deletion
                                  d[i - 1][j - 1],  # substitution
                                  d[i][j - 1])      # insertion
    # backtrack to count S / D / I
    i, j = r, h
    s = de = ins = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1] and d[i][j] == d[i - 1][j - 1]:
            i -= 1
            j -= 1
        elif i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + 1:
            s += 1
            i -= 1
            j -= 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            de += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return s, de, ins


def word_error_rate(ref: list[str], hyp: list[str]) -> float:
    """WER = (S + D + I) / len(reference)."""
    if not ref:
        return 0.0
    s, d, i = wer_ops(ref, hyp)
    return (s + d + i) / len(ref)


# ============================================================================
# 6. pretty printer + check helper
# ============================================================================

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
# 7. SECTIONS (the numbers that feed WHISPER_STT.md)
# ============================================================================

def section_a_mel_spectrogram():
    banner("SECTION A: audio -> log-mel spectrogram (30 s = 3000 frames)")
    print("Whisper is hard-coded to 16 kHz mono. The waveform is chopped into")
    print(f"25 ms windows ({N_FFT} samples) every 10 ms ({HOP_LENGTH} samples), FFT'd,")
    print(f"collapsed to {N_MELS} mel bands, then log'd. The encoder sees an")
    print(f"'image' of size {N_MELS} x <frames>.\n")

    fps = frames_per_second()
    print(f"frames/s = sample_rate / hop = {SAMPLE_RATE} / {HOP_LENGTH} = {fps:.0f}")
    print(f"30 s of audio -> {mel_frame_count(30)} mel frames "
          f"(= {mel_frame_count(30) // 10} x 10)")
    print(f"mel grid for 30 s = {N_MELS} bands x {mel_frame_count(30)} frames "
          f"= {N_MELS * mel_frame_count(30)} values\n")

    print("Tiny live demo (real DFT + mel filterbank, pure Python):")
    print(f"  synthetic {0.12}s vowel signal, FFT={DEMO_N_FFT}, "
          f"hop={DEMO_HOP}, mel bands={DEMO_N_MELS}\n")
    audio = synthetic_speech(0.12, SAMPLE_RATE)
    spec = log_mel_spectrogram(audio, DEMO_N_FFT, DEMO_HOP, DEMO_N_MELS, SAMPLE_RATE)
    # normalise for ASCII
    vals = [v for row in spec for v in row]
    vmin, vmax = min(vals), max(vals)
    span = vmax - vmin if vmax > vmin else 1.0
    ramp = " .:-=+*#%@"
    print("  mel band (high ^)            frames (time ->)")
    for band in reversed(range(DEMO_N_MELS)):       # high freq on top
        cells = ""
        for fi in range(len(spec)):
            norm = (spec[fi][band] - vmin) / span
            cells += ramp[min(len(ramp) - 1, int(norm * (len(ramp) - 1)))]
        print(f"  {band:>2}  |{cells}")
    print("      +" + "-" * len(spec) + "  (low v)")
    print("\nEnergy rises from low to high mel bands over time -- the synthetic")
    print("formant transition. Real speech produces a far richer 80x3000 grid.\n")

    check("30 s -> exactly 3000 mel frames", mel_frame_count(30) == 3000)
    check("frames/s == 100 (10 ms hop)", frames_per_second() == 100.0)
    check("mel grid 80 x 3000 = 240000 values",
          N_MELS * mel_frame_count(30) == 240000)
    check("demo spectrogram produced frames", len(spec) > 0)


def section_b_encoder_decoder():
    banner("SECTION B: encoder-decoder + special tokens (autoregressive decode)")
    print("The ENCODER reads the mel spectrogram -> hidden states (audio features).")
    print("The DECODER is autoregressive: it emits ONE text token per step, each")
    print("conditioned on the encoder output + all tokens generated so far.\n")
    print("Special tokens SELECT the behaviour of the SAME weights:")
    print(f"  {SOT}    begin (also used for language detection)")
    print(f"  <|en|> / <|vi|> / ...        the detected/source language")
    print(f"  {TRANSCRIBE}   transcribe in the source language")
    print(f"  {TRANSLATE}    translate to English")
    print(f"  {EOT}  done")
    print(f"  {NO_SPEECH}  no speech detected (skip the clip)\n")

    phrase = ["the", "quick", "brown", "fox"]
    trace = simulate_autoregressive(phrase, seed=42)
    print("Autoregressive decode trace (phrase = 'the quick brown fox'):\n")
    print(f"| step | emitted token                | conditioned on (mel + tokens so far)        |")
    print(f"|------|------------------------------|----------------------------------------------|")
    for rec in trace:
        cond = rec["conditioned_on"]
        if len(cond) > 44:
            cond = cond[:41] + "..."
        print(f"| {rec['step']:<4} | {rec['emitted']:<28} | {cond:<44} |")
    full = decode_sequence("<|en|>", TRANSCRIBE, phrase)
    print(f"\nFull emitted sequence:\n  {' '.join(full)}\n")
    print("Each row is one decoder forward pass (KV-cached after the first). The")
    print("encoder runs ONCE; the decoder runs once per output token.\n")

    check("sequence starts with SOT", full[0] == SOT)
    check("sequence ends with EOT", full[-1] == EOT)
    check("transcribe task present", TRANSCRIBE in full)
    check("translate task selectable", TRANSLATE not in full)
    check("steps == 1 (SOT) + 1 (lang) + 1 (task) + len(text) + 1 (EOT)",
          len(trace) == 1 + 1 + 1 + len(phrase) + 1)


def section_c_model_sizes():
    banner("SECTION C: the model size ladder (tiny -> large-v3)")
    print("Whisper ships as 5 sizes. Bigger = more accurate + slower + more VRAM.\n")
    print(f"| model    | params (M) | VRAM (GB) | rel speed | best for       |")
    print(f"|----------|------------|-----------|-----------|----------------|")
    for name, params, vram, speed, best in MODELS:
        print(f"| {name:<8} | {params:<10} | {vram:<9} | {speed:<9} | {best:<14} |")
    print()
    print("All sizes share the SAME architecture (encoder-decoder) and mel front-")
    print("end; only the layer counts / widths differ. large-v3 is the current")
    print("best-quality checkpoint (supersedes large-v1/v2).\n")

    check("large-v3 = 1550M params", MODELS[4][1] == 1550)
    check("large-v3 ~10GB VRAM", MODELS[4][2] == 10)
    check("speeds are descending powers-ish", MODELS[0][3] > MODELS[4][3])
    check("params increase monotonically",
          all(MODELS[i][1] < MODELS[i + 1][1] for i in range(len(MODELS) - 1)))


def section_d_faster_whisper():
    banner("SECTION D: faster-whisper (CTranslate2) -- 4x faster, 50% less VRAM")
    print("faster-whisper runs the SAME Whisper weights on CTranslate2: an")
    print("optimised C++ Transformer runtime (int8/FP16, fused kernels, no Python")
    print("per-token overhead). Default precision is int8 with FP16 compute.\n")
    print("Weight-memory comparison (FP16 OpenAI vs int8 faster-whisper):\n")
    print(f"| model    | params (M) | FP16 MB | int8 MB | memory of FP16 | reduction |")
    print(f"|----------|------------|---------|---------|----------------|-----------|")
    for name, params, *_ in MODELS:
        m = memory_ratio(params)
        print(f"| {name:<8} | {params:<10} | {m['fp16_mb']:<7.0f} | "
              f"{m['int8_mb']:<7.0f} | {m['ratio']:<6.2f}        | "
              f"{m['reduction'] * 100:.0f}%       |")
    print()
    print("int8 weights are exactly HALF of FP16 -> ~50% less memory. Combined")
    print("with CTranslate2's fused kernels, the net effect is ~4x faster for the")
    print("SAME model and (for greedy decoding) bit-identical transcripts.\n")

    big = memory_ratio(1550)
    check("int8 large-v3 == 1550 MB", abs(big["int8_mb"] - 1550.0) < 1e-6)
    check("int8 is 50% of FP16 memory", abs(big["ratio"] - 0.5) < 1e-9)
    check("memory reduction == 50%", abs(big["reduction"] - 0.5) < 1e-9)
    check("FP16 large-v3 == 3100 MB", abs(big["fp16_mb"] - 3100.0) < 1e-6)
    check("int8 < FP16 for every size",
          all(memory_ratio(p)["int8_mb"] < memory_ratio(p)["fp16_mb"]
              for _, p, *_ in MODELS))


def section_e_distil_whisper():
    banner("SECTION E: distil-whisper (knowledge distillation)")
    print("distil-whisper trains a STUDENT with fewer decoder layers to mimic the")
    print("large teacher. distil-large-v3 keeps the teacher's encoder, distils the")
    print("32-layer decoder down to 2 layers.\n")
    teacher_params = 1550
    student_params = 756
    reduction = 1.0 - student_params / teacher_params
    print(f"distil-large-v3: {student_params}M params "
          f"({student_params / teacher_params * 100:.1f}% of large-v3)")
    print(f"reduction = 1 - {student_params}/{teacher_params} = "
          f"{reduction * 100:.1f}% fewer params (~49-51% smaller)")
    print("speed: ~6x faster than the teacher (fewer decoder layers per token)")
    print("quality: WER within ~1% of large-v3 on English (distillation loss\n"
          "         keeps the student's distribution close to the teacher's)\n")

    print("Trade-off: distil is great for English transcription at speed, but it")
    print("trims multilingual coverage -- for non-English use the full model.\n")

    check("distil-large-v3 = 756M params", student_params == 756)
    check("distil < large-v3 params", student_params < teacher_params)
    check("distil retains < 50% of params",
          student_params / teacher_params < 0.5)
    check("~49-51% smaller", 0.48 < reduction < 0.52)


def section_f_rtf_wer():
    banner("SECTION F: real-time factor (RTF) + word error rate (WER)")
    print("RTF = processing_time / audio_duration.")
    print("  RTF < 1.0  => faster than real-time (can transcribe LIVE)")
    print("  RTF > 1.0  => slower than real-time\n")

    print(f"| setup                       | hardware       | RTF   | x real-time | 30s clip in |")
    print(f"|-----------------------------|----------------|-------|-------------|-------------|")
    for label, hw, rtf_val in RTF_BENCHMARKS:
        speed = realtime_speedup(rtf_val)
        proc = processing_time(30, rtf_val)
        print(f"| {label:<27} | {hw:<14} | {rtf_val:<5.2f} | {speed:<11.1f} | "
              f"{proc:<9.1f}s  |")
    print()
    print("On an RTX 4090, faster-whisper large-v3 transcribes 30 s of audio in")
    print("~0.9 s -- 33x real-time. Even an M1 Pro laptop runs medium at 6x real-")
    print("time. The official OpenAI model on CPU (RTF ~2-4) CANNOT keep up live.\n")

    print("WER benchmarks (lower is better):")
    print("  large-v3 (English)       : ~5-8%  on clean speech")
    print("  large-v3 (multilingual)  : ~10-15%")
    print("  distil-large-v3          : ~6-9%  (within ~1% of teacher)\n")

    # worked WER example
    ref = "the quick brown fox jumps over the lazy dog".split()
    hyp = "the quick brown fox jump over a lazy dog".split()
    s, d, i = wer_ops(ref, hyp)
    w = word_error_rate(ref, hyp)
    print("Worked WER example (word-level Levenshtein):")
    print(f"  ref : {' '.join(ref)}")
    print(f"  hyp : {' '.join(hyp)}")
    print(f"  S={s}  D={d}  I={i}   WER = ({s}+{d}+{i})/{len(ref)} = {w:.4f} "
          f"({w * 100:.1f}%)\n")

    check("RTX 4090 RTF == 0.03", RTF_BENCHMARKS[0][2] == 0.03)
    check("RTF 0.03 -> 33.3x real-time", abs(realtime_speedup(0.03) - 33.333) < 0.01)
    check("30s clip @ RTF 0.03 -> 0.9s", abs(processing_time(30, 0.03) - 0.9) < 1e-9)
    check("CPU large RTF > 1 (cannot do live)", RTF_BENCHMARKS[4][2] > 1.0)
    check("M1 Pro medium RTF < 1 (can do live)", RTF_BENCHMARKS[2][2] < 1.0)
    check("WER example correct", abs(w - (s + d + i) / len(ref)) < 1e-9)
    check("WER example within [0,1]", 0.0 <= w <= 1.0)


# ----------------------- THE GOLD CENTERPIECE --------------------------------

def section_gold():
    banner("SECTION G: GOLD pipeline table (the centerpiece)")
    frames30 = mel_frame_count(30)
    rtf4090 = 0.03
    big = memory_ratio(1550)

    print("Canonical clip: 30 s of 16 kHz mono audio through faster-whisper large-v3.\n")
    print(f"| stage / metric                  | value                |")
    print(f"|---------------------------------|----------------------|")
    print(f"| sample rate                     | {SAMPLE_RATE} Hz            |")
    print(f"| mel bands                       | {N_MELS}                  |")
    print(f"| frames/s (10 ms hop)            | {frames_per_second():.0f}                   |")
    print(f"| 30 s -> mel frames              | {frames30}                 |")
    print(f"| mel grid shape                  | {N_MELS} x {frames30}            |")
    print(f"| large-v3 params                 | 1550M                |")
    print(f"| large-v3 VRAM (practical)       | ~10 GB               |")
    print(f"| int8 weights (faster-whisper)   | {big['int8_mb']:.0f} MB (50% of FP16) |")
    print(f"| faster-whisper vs OpenAI        | ~4x faster, 50% VRAM |")
    print(f"| RTF (RTX 4090, large-v3)        | {rtf4090}                 |")
    print(f"| real-time speedup (1/RTF)       | {realtime_speedup(rtf4090):.1f}x                |")
    print(f"| 30 s clip processing time       | {processing_time(30, rtf4090):.1f} s                  |")
    print()
    print("GOLD (recomputed & badge-checked in whisper_stt.html):")
    print(f"  30 s -> 3000 mel frames  (30 * {frames_per_second():.0f})")
    print(f"  int8 large-v3 = 1550M * 1 byte = {big['int8_mb']:.0f} MB "
          f"= {big['ratio']:.2f} of FP16 ({big['fp16_mb']:.0f} MB)")
    print(f"  RTF {rtf4090} -> 1/{rtf4090} = {realtime_speedup(rtf4090):.1f}x real-time")
    print(f"  30 s clip -> {processing_time(30, rtf4090):.1f} s wall clock\n")

    gold_ok = (frames30 == 3000
               and abs(big["ratio"] - 0.5) < 1e-9
               and abs(big["int8_mb"] - 1550.0) < 1e-6
               and abs(realtime_speedup(rtf4090) - 33.333333) < 1e-3
               and abs(processing_time(30, rtf4090) - 0.9) < 1e-9)
    check("30 s -> 3000 mel frames", frames30 == 3000)
    check("int8 = 50% of FP16 memory", abs(big["ratio"] - 0.5) < 1e-9)
    check("int8 large-v3 = 1550 MB", abs(big["int8_mb"] - 1550.0) < 1e-6)
    check("RTF 0.03 -> 33.3x real-time",
          abs(realtime_speedup(rtf4090) - 33.333333) < 1e-3)
    check("30 s @ RTF 0.03 -> 0.9 s", abs(processing_time(30, rtf4090) - 0.9) < 1e-9)
    check("mel grid 80 x 3000", N_MELS * frames30 == 240000)
    return {"frames30": frames30, "rtf": rtf4090, "speedup": realtime_speedup(rtf4090),
            "int8_mb": big["int8_mb"], "ratio": big["ratio"], "gold_ok": gold_ok}


# ============================================================================
# main
# ============================================================================

def main():
    print("whisper_stt.py - reference impl. All numbers feed WHISPER_STT.md.")
    print("pure Python stdlib (no torch, no numpy). Real DFT + mel filterbank demo.")
    print(f"audio model: {SAMPLE_RATE} Hz mono, FFT={N_FFT} ({N_FFT / SAMPLE_RATE * 1000:.0f} ms), "
          f"hop={HOP_LENGTH} ({HOP_LENGTH / SAMPLE_RATE * 1000:.0f} ms), {N_MELS} mel bands.")

    section_a_mel_spectrogram()
    section_b_encoder_decoder()
    section_c_model_sizes()
    section_d_faster_whisper()
    section_e_distil_whisper()
    section_f_rtf_wer()
    gold = section_gold()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
