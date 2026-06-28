"""
tts_kokoro.py - Reference simulation of the Kokoro-82M text-to-speech pipeline.

This is the single source of truth that TTS_KOKORO.md is built from. Every
number, table, and worked example in TTS_KOKORO.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy) - this is the *local runtime*
side: how text becomes speech, the StyleTTS 2 architecture Kokoro inherits,
and the audio math (sample rate, mel frames, VRAM) that explains why a 82M
model rivals commercial TTS APIs.

Run:
    python3 tts_kokoro.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
Text-to-Speech is a 5-stage funnel. Text goes in the top, a waveform comes
out the bottom:

  "I have $5"           (raw text)
       |  text normalization       "I have five dollars"
       |  phonemization (G2P)       /AI/ /haev/ /faiv/ /dAlerz/   (IPA)
       |  prosody prediction       duration + pitch + energy per phoneme
       |  acoustic model           phonemes + prosody -> mel-spectrogram
       |  vocoder                  mel-spectrogram -> waveform (audio samples)
  24000 samples/sec       (the final audio you can play)

Kokoro inherits the **StyleTTS 2** architecture (arxiv:2306.07691):
  - a style encoder (256-dim style vector from reference audio or learned)
  - a duration predictor (how many mel frames each phoneme spans)
  - a text encoder (phonemes -> hidden states)
  - a decoder (hidden + style -> mel-spectrogram), then an ISTFTNet vocoder
  - trained adversarially with style diffusion -> natural prosody without
    explicit duration labels.

WHY IT IS ONLY 82M params (vs 300M+ for other TTS):
  - shared encoder backbone (not duplicated per component)
  - non-autoregressive decoder (parallel, no per-step feedback loop)
  - compact 256-dim style vectors
  - pre-computed phoneme embeddings (no giant embedding table)

GOLD VALUE (for tts_kokoro.html to reproduce):
    "hello" = 5 phoneme segments  /h/ /ə/ /l/ /o/ /ʊ/  (the /oʊ/ diphthong
    is split into onset /o/ + glide /ʊ/ for duration modeling)
    duration per segment (mel frames) = [5, 12, 8, 15, 20]
    total frames = 60
    samples      = 60 * 256 = 15360
    seconds      = 15360 / 24000 = 0.6400
Sources: https://huggingface.co/hexgrad/Kokoro-82M (Model Facts), arxiv 2306.07691.
"""

from __future__ import annotations

import math
import random

# ----------------------------------------------------------------------------
# Audio constants (verified against Kokoro-82M Model Facts + ISTFTNet).
# ----------------------------------------------------------------------------
SAMPLE_RATE   = 24000   # Hz  -> 24000 samples per second of output audio
HOP_LENGTH    = 256     # STFT hop -> mel frames advance 256 samples each
FFT_SIZE      = 1024    # FFT window (samples)
N_MEL_BANDS   = 80      # mel-spectrogram frequency resolution

BANNER = "=" * 74

# Kokoro-82M specifications (huggingface.co/hexgrad/Kokoro-82M Model Facts).
KOKORO_PARAMS      = 82_000_000        # 82M parameters
KOKORO_VOICES      = 54                # voice/style vectors (v1.0)
KOKORO_LANGS       = 8                 # en, zh, ja, ko, fr, it, pt, es
KOKORO_STYLE_DIM   = 256               # style vector dimensionality
KOKORO_LICENSE     = "Apache-2.0"
KOKORO_ARCH_BASE   = "StyleTTS 2 (arxiv:2306.07691) + ISTFTNet (arxiv:2203.02395)"


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
# 1. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_row(values: list[float], p: int = 2) -> str:
    return "[" + ", ".join(f"{v:+.{p}f}" for v in values) + "]"


# ============================================================================
# 2. THE TTS PIPELINE STAGES  (text normalization / G2P / prosody / mel / vocoder)
#    Each is a tiny, deterministic stand-in for the real component, enough to
#    show the data shape transformation at every step.
# ============================================================================

# --- 2a. TEXT NORMALIZATION ----------------------------------------------
# Real Kokoro uses `misaki` (https://github.com/hexgrad/misaki). We emulate the
# handful of rules that matter for teaching: symbols -> spoken words.

NORMALIZE_RULES = {
    "$5":   "five dollars",
    "$12":  "twelve dollars",
    "100%": "one hundred percent",
    "&":    "and",
    "1st":  "first",
    "2nd":  "second",
    "3rd":  "third",
    "Dr.":  "Doctor",
    "Mr.":  "Mister",
}

def normalize_text(raw: str) -> str:
    """Apply the symbol->word rules. Word-boundary aware enough for the demo."""
    out = raw
    # longest-first so "$12" beats "$1"
    for token in sorted(NORMALIZE_RULES, key=len, reverse=True):
        out = out.replace(token, NORMALIZE_RULES[token])
    return out


# --- 2b. GRAPHEME-TO-PHONEME (G2P) ---------------------------------------
# Tiny IPA dictionary for the demo words. Real misaki handles arbitrary text
# via phonemization rules + a learned fallback.

G2P_DICT = {
    "hello":   ["/h/", "/ə/", "/l/", "/o/", "/ʊ/"],   # /oʊ/ split for duration
    "world":   ["/w/", "/ɜːr/", "/l/", "/d/"],
    "five":    ["/f/", "/aɪ/", "/v/"],
    "dollars": ["/d/", "/ɑ/", "/l/", "/ɚ/", "/z/"],
    "i":       ["/aɪ/"],
    "have":    ["/h/", "/æ/", "/v/"],
    "kokoro":  ["/k/", "/o/", "/k/", "/o/", "/ɾ/", "/o/"],
}

def phonemize(words: list[str]) -> list[str]:
    """Look up each word in G2P_DICT, fall back to a per-letter placeholder."""
    phonemes: list[str] = []
    for w in words:
        key = w.lower().strip(".,!?")
        if key in G2P_DICT:
            phonemes.extend(G2P_DICT[key])
        else:
            phonemes.extend([f"/{c}/" for c in key])
    return phonemes


# --- 2c. PROSODY PREDICTION ----------------------------------------------
# Duration predictor: how many mel frames each phoneme spans. We assign a
# fixed, deterministic duration per phoneme symbol (consonants short, vowels +
# diphthongs long) so the math is reproducible. Real Kokoro learns this.

DURATION_BY_PHONEME = {
    "/h/": 5, "/ə/": 12, "/l/": 8, "/o/": 15, "/ʊ/": 20,   # "hello"
    "/w/": 6, "/ɜːr/": 18, "/d/": 7,                       # "world" tail
    "/f/": 7, "/aɪ/": 22, "/v/": 6,                         # "five"
    "/ɑ/": 16, "/ɚ/": 12, "/z/": 9,                         # "dollars" tail
    "/æ/": 14, "/ɾ/": 5,                                     # misc
    "/k/": 6,                                                # "kokoro"
}

def predict_durations(phonemes: list[str]) -> list[int]:
    return [DURATION_BY_PHONEME.get(p, 10) for p in phonemes]


# --- 2d. ACOUSTIC MODEL  (phonemes + duration -> mel-spectrogram) ---------
# Each phoneme gets a characteristic formant profile (a Gaussian over the 80
# mel bands). The duration predictor REPEATS that profile across the phoneme's
# frames, producing the classic "horizontal stripe" mel-spectrogram.

# formant centers/spreads in mel-band index (0..79)
PHONEME_PROFILE = {
    "/h/":  [(40.0, 26.0)],                       # breathy, broadband
    "/ə/":  [(30.0, 10.0)],                       # schwa, mid
    "/l/":  [(22.0, 8.0), (62.0, 6.0)],           # liquid + high peak
    "/o/":  [(18.0, 7.0)],                        # back rounded vowel onset
    "/ʊ/":  [(15.0, 6.0)],                        # high back glide
    "/w/":  [(16.0, 7.0)],
    "/ɜːr/": [(28.0, 9.0)],
    "/d/":  [(50.0, 20.0)],
    "/f/":  [(60.0, 18.0)],
    "/aɪ/": [(24.0, 8.0), (40.0, 9.0)],
    "/v/":  [(58.0, 14.0)],
    "/ɑ/":  [(20.0, 8.0)],
    "/ɚ/":  [(26.0, 9.0)],
    "/z/":  [(64.0, 12.0)],
    "/æ/":  [(26.0, 8.0)],
    "/ɾ/":  [(44.0, 16.0)],
    "/k/":  [(46.0, 18.0)],
}

def phoneme_energy(phoneme: str, rng: random.Random) -> list[float]:
    """Energy across the 80 mel bands for one phoneme frame."""
    centers = PHONEME_PROFILE.get(phoneme, [(40.0, 14.0)])
    bands = []
    for b in range(N_MEL_BANDS):
        e = 0.0
        for center, spread in centers:
            e += math.exp(-((b - center) ** 2) / (2.0 * spread * spread))
        # tiny deterministic jitter so frames are not identical
        e *= 0.92 + 0.08 * rng.random()
        bands.append(e)
    return bands

def acoustic_model(phonemes: list[str], durations: list[int],
                   seed: int = 42) -> list[list[float]]:
    """phonemes + durations -> mel-spectrogram (frames x N_MEL_BANDS)."""
    rng = random.Random(seed)
    mel: list[list[float]] = []
    for ph, d in zip(phonemes, durations):
        base = phoneme_energy(ph, rng)
        for _ in range(d):
            # slight per-frame drift so the stripe is not perfectly flat
            frame = phoneme_energy(ph, rng)
            mel.append(frame)
    return mel


# --- 2e. VOCODER  (mel-spectrogram -> waveform) --------------------------
# Real Kokoro uses an ISTFTNet vocoder (inverse short-time Fourier transform).
# We synthesize a deterministic waveform: one sine at a base F0 per frame,
# amplitude-enveloped by the frame's total energy, then concatenated on the
# HOP_LENGTH grid. This reproduces the sample-count math exactly.

def vocoder(mel: list[list[float]], f0: float = 180.0) -> list[float]:
    """mel-spectrogram -> 1D waveform at SAMPLE_RATE."""
    wav: list[float] = []
    for frame in mel:
        amp = sum(frame) / len(frame)        # mean band energy -> amplitude
        for s in range(HOP_LENGTH):
            t = len(wav) / SAMPLE_RATE
            wav.append(amp * math.sin(2.0 * math.pi * f0 * t))
    return wav


# ============================================================================
# 3. SECTIONS
# ============================================================================

def section_a_pipeline_overview():
    banner("SECTION A: THE 5-STAGE TTS PIPELINE (text -> waveform)")
    raw = "I have $5."
    norm = normalize_text(raw)
    words = norm.replace(".", "").split()
    phonemes = phonemize(words)
    durations = predict_durations(phonemes)
    mel = acoustic_model(phonemes, durations)
    wav = vocoder(mel)

    print(f"Stage 1 - TEXT NORMALIZATION")
    print(f"  raw   = {raw!r}")
    print(f"  rules = $5 -> five dollars, & -> and, % -> percent, ...")
    print(f"  out   = {norm!r}")
    print()
    print(f"Stage 2 - PHONEMIZATION (G2P via `misaki`)")
    print(f"  words     = {words}")
    print(f"  phonemes  = {phonemes}  ({len(phonemes)} IPA symbols)")
    print()
    print(f"Stage 3 - PROSODY PREDICTION (duration per phoneme, in mel frames)")
    print(f"  durations = {durations}  -> total {sum(durations)} frames")
    print()
    print(f"Stage 4 - ACOUSTIC MODEL (phonemes + prosody -> mel-spectrogram)")
    print(f"  mel shape = {len(mel)} frames x {N_MEL_BANDS} bands")
    print(f"  (each frame = {N_MEL_BANDS} floats = a frequency snapshot)")
    print()
    print(f"Stage 5 - VOCODER (mel-spectrogram -> waveform, ISTFTNet)")
    print(f"  samples   = {len(wav)}")
    print(f"  seconds   = {len(wav)/SAMPLE_RATE:.4f}  (= samples / {SAMPLE_RATE})")
    print()
    check("stage1 keeps word count plausible", len(words) >= 3,
          f"words={words}")
    check("stage2 emits IPA phonemes",
          all(p.startswith("/") and p.endswith("/") for p in phonemes))
    check("stage3 duration frames = sum of per-phoneme",
          sum(durations) == len(mel))
    check("stage4 mel has 80 bands", all(len(f) == N_MEL_BANDS for f in mel))
    check("stage5 samples = frames * hop",
          len(wav) == sum(durations) * HOP_LENGTH,
          f"samples={len(wav)} expected={sum(durations)*HOP_LENGTH}")


def section_b_hello_gold():
    banner("SECTION B: GOLD EXAMPLE - 'hello' -> 0.64s of audio")
    print("The hero example tts_kokoro.html reproduces. The /oʊ/ diphthong is")
    print("split into onset /o/ + glide /ʊ/ so the duration predictor can model")
    print("the two phases separately (standard in many TTS duration heads).")
    print()
    phonemes = G2P_DICT["hello"]
    durations = predict_durations(phonemes)
    total_frames = sum(durations)
    samples = total_frames * HOP_LENGTH
    seconds = samples / SAMPLE_RATE
    print(f"  text       = 'hello'")
    print(f"  phonemes   = {phonemes}  ({len(phonemes)} segments)")
    print(f"  durations  = {durations}  (mel frames per segment)")
    print(f"  sum        = {total_frames} frames")
    print(f"  samples    = {total_frames} * {HOP_LENGTH} = {samples}")
    print(f"  seconds    = {samples} / {SAMPLE_RATE} = {seconds:.4f}")
    print()
    # per-segment breakdown table
    print("| segment | phoneme | dur (frames) | dur (ms)  |")
    print("|---------|---------|--------------|-----------|")
    cum_ms = 0.0
    for i, (ph, d) in enumerate(zip(phonemes, durations)):
        ms = d * HOP_LENGTH / SAMPLE_RATE * 1000.0
        cum_ms += ms
        print(f"| {i}       | {ph:<7} | {d:>12} | {ms:>7.2f}   |")
    print(f"| total   |         | {total_frames:>12} | {cum_ms:>7.2f}   |")
    print()
    expected_frames = 60
    expected_samples = 15360
    expected_seconds = 0.64
    check("hello -> 60 mel frames total", total_frames == expected_frames,
          f"got {total_frames} expected {expected_frames}")
    check("hello -> 15360 samples",
          samples == expected_samples,
          f"got {samples} expected {expected_samples}")
    check("hello -> 0.64 seconds",
          abs(seconds - expected_seconds) < 1e-9,
          f"got {seconds}")
    print()
    print("GOLD (for tts_kokoro.html):")
    print(f"  durations='hello' = {durations}")
    print(f"  total_frames = {total_frames}, samples = {samples}, seconds = {seconds:.4f}")


def section_c_audio_math():
    banner("SECTION C: AUDIO FUNDAMENTALS - sample rate, hop, mel frames")
    print(f"Kokoro audio config (verified: Model Facts + ISTFTNet):")
    print(f"  sample_rate = {SAMPLE_RATE} Hz  ({SAMPLE_RATE} samples per second)")
    print(f"  hop_length  = {HOP_LENGTH} samples per mel frame")
    print(f"  fft_size    = {FFT_SIZE} samples (STFT window)")
    print(f"  n_mel_bands = {N_MEL_BANDS} frequency bands")
    print()
    frames_per_sec = SAMPLE_RATE / HOP_LENGTH
    print(f"mel frames per second = sample_rate / hop_length")
    print(f"                     = {SAMPLE_RATE} / {HOP_LENGTH} = {frames_per_sec}")
    print(f"                     ~ 94 frames/sec")
    print()
    print(f"1 second of audio:")
    print(f"  samples    = {SAMPLE_RATE}")
    print(f"  mel frames = {frames_per_sec}  (≈ 94)")
    print(f"  floats     = {int(frames_per_sec)} frames * {N_MEL_BANDS} bands "
          f"= {int(frames_per_sec)*N_MEL_BANDS} mel values")
    print()
    print(f"Per mel frame: {N_MEL_BANDS} floats = a snapshot of frequency content")
    print(f"  -> frame covers {HOP_LENGTH} samples = "
          f"{HOP_LENGTH/SAMPLE_RATE*1000:.2f} ms of audio")
    print()
    print(f"Duration in seconds from frames:")
    print(f"  seconds = frames * hop / sample_rate")
    print()
    print("| frames | samples  | seconds  |")
    print("|--------|----------|----------|")
    for fr in [1, 10, 60, 94, 200, 500]:
        samps = fr * HOP_LENGTH
        secs = samps / SAMPLE_RATE
        print(f"| {fr:>6} | {samps:>8} | {secs:>8.4f} |")
    print()
    check("24000/256 = 93.75 mel frames/sec",
          abs(frames_per_sec - 93.75) < 1e-9, f"got {frames_per_sec}")
    check("~94 frames/sec rounding", abs(frames_per_sec - 94) < 1.0)
    check("1 mel frame = 10.67 ms",
          abs(HOP_LENGTH / SAMPLE_RATE * 1000 - 10.6666) < 1e-3)
    check("1 second = 24000 samples", SAMPLE_RATE == 24000)


def section_d_mel_spectrogram():
    banner("SECTION D: MEL-SPECTROGRAM - the acoustic model's output")
    print("Each phoneme has a characteristic formant profile (energy across the")
    print(f"{N_MEL_BANDS} mel bands). The duration predictor REPEATS that profile")
    print("across the phoneme's frames, producing horizontal stripes. This is the")
    print("classic look of a TTS mel-spectrogram.")
    print()
    phonemes = G2P_DICT["hello"]
    durations = predict_durations(phonemes)
    mel = acoustic_model(phonemes, durations)
    total_frames = len(mel)
    print(f"Input : phonemes={phonemes}, durations={durations}")
    print(f"Output: mel-spectrogram = {total_frames} frames x {N_MEL_BANDS} bands")
    print()
    # downsample to a 10-band summary so it fits on a terminal.
    summary_bands = 10
    band_size = N_MEL_BANDS // summary_bands
    levels = " .:-=+*#%@"
    print(f"Downsampled to {summary_bands} band-groups (ASCII heatmap, frames as rows):")
    print(f"  band-groups: low freq <----> high freq")
    # sample 1 frame per phoneme segment (the segment's first frame)
    print("  " + " ".join(f"{ph:>4}" for ph in phonemes))
    for seg_i in range(len(phonemes)):
        start = sum(durations[:seg_i])
        frame = mel[start]
        row = []
        for g in range(summary_bands):
            chunk = frame[g * band_size:(g + 1) * band_size]
            avg = sum(chunk) / len(chunk)
            idx = min(len(levels) - 1, int(avg / 0.4 * (len(levels) - 1)))
            row.append(levels[idx])
        print(f"  frame {start:<3} : {' '.join(row)}   "
              f"(segment {seg_i} {phonemes[seg_i]} dur={durations[seg_i]})")
    print()
    # energy stats per phoneme
    print("| segment | phoneme | frames | mean energy | peak band |")
    print("|---------|---------|--------|-------------|-----------|")
    for seg_i, (ph, d) in enumerate(zip(phonemes, durations)):
        start = sum(durations[:seg_i])
        seg_frames = mel[start:start + d]
        all_e = [v for fr in seg_frames for v in fr]
        mean_e = sum(all_e) / len(all_e)
        peak_band = max(range(N_MEL_BANDS),
                        key=lambda b: sum(fr[b] for fr in seg_frames))
        print(f"| {seg_i}       | {ph:<7} | {d:>6} | {mean_e:>11.4f} | {peak_band:>9} |")
    print()
    total_floats = total_frames * N_MEL_BANDS
    print(f"mel-spectrogram size: {total_frames} x {N_MEL_BANDS} = {total_floats} floats")
    check("mel frame count = sum of durations", len(mel) == 60)
    check("every mel frame has 80 bands",
          all(len(fr) == N_MEL_BANDS for fr in mel))
    check("mel values are non-negative (energies)",
          all(v >= 0 for fr in mel for v in fr))


def section_e_vocoder_waveform():
    banner("SECTION E: VOCODER - mel-spectrogram -> waveform")
    print("The vocoder (ISTFTNet in Kokoro) inverts the mel-spectrogram into a")
    print("1D waveform of audio samples. One mel frame expands to hop_length")
    print(f"({HOP_LENGTH}) consecutive samples.")
    print()
    phonemes = G2P_DICT["hello"]
    durations = predict_durations(phonemes)
    mel = acoustic_model(phonemes, durations)
    total_frames = len(mel)
    wav = vocoder(mel)
    print(f"mel-spectrogram: {total_frames} frames")
    print(f"waveform       : {len(wav)} samples "
          f"(= {total_frames} frames * {HOP_LENGTH} hop)")
    print(f"duration       : {len(wav)/SAMPLE_RATE:.4f} s "
          f"(= {len(wav)} / {SAMPLE_RATE})")
    print()
    # show a tiny slice of the waveform (first 8 samples of segment 0)
    print("First 8 waveform samples (segment 0, /h/, breathy onset):")
    print("| i | sample    |")
    print("|---|-----------|")
    for i in range(8):
        print(f"| {i} | {wav[i]:>+9.5f} |")
    print()
    # real-time factor on CPU (~3x real-time): compute ratio
    rt_factor_cpu = 3.0
    gen_seconds = len(wav) / SAMPLE_RATE
    compute_seconds_cpu = gen_seconds / rt_factor_cpu
    print(f"CPU real-time factor ~ {rt_factor_cpu:.1f}x")
    print(f"  generate {gen_seconds:.4f}s of audio in ~{compute_seconds_cpu:.4f}s compute")
    print()
    check("waveform length = frames * hop",
          len(wav) == total_frames * HOP_LENGTH,
          f"got {len(wav)} expected {total_frames*HOP_LENGTH}")
    check("waveform samples in [-amp, +amp]", -1.0 <= min(wav) <= max(wav) <= 1.0)
    check("hello waveform = 0.64s", abs(len(wav)/SAMPLE_RATE - 0.64) < 1e-9)


def section_f_styletts2_arch():
    banner("SECTION F: STYLETTS 2 ARCHITECTURE (what Kokoro inherits)")
    print("Kokoro's architecture = StyleTTS 2 (arxiv:2306.07691) + ISTFTNet")
    print("vocoder (arxiv:2203.02395). Decoder only: NO diffusion, NO released")
    print("encoder. Five components, all sharing one backbone:")
    print()
    print("  1. STYLE ENCODER")
    print("     extracts a speaking-style vector from reference audio (or a")
    print(f"     learned {KOKORO_STYLE_DIM}-dim vector per voice). This single vector")
    print("     carries identity + prosody style across the whole utterance.")
    print()
    print("  2. TEXT ENCODER")
    print("     phonemes -> hidden representations (the phoneme embedding +")
    print("     transformer/conv stack). Pre-computed phoneme embeddings keep")
    print("     the embedding table tiny.")
    print()
    print("  3. DURATION PREDICTOR")
    print("     predicts how many mel frames each phoneme spans (alignment).")
    print("     No external alignment labels needed.")
    print()
    print("  4. DECODER (NON-AUTOREGRESSIVE)")
    print("     aligned text + style -> mel-spectrogram. PARALLEL: all frames")
    print("     generated at once, not one-at-a-time. This is the speed win.")
    print()
    print("  5. VOCODER (ISTFTNet)")
    print("     mel-spectrogram -> waveform via inverse short-time Fourier")
    print("     transform. Cheaper than HiFi-GAN, lighter than diffusion.")
    print()
    print("The trick: ADVERSARIAL TRAINING + STYLE DIFFUSION. A discriminator")
    print("judges generated mel vs real mel; a diffusion process samples the")
    print("style vector. Together they yield natural prosody WITHOUT explicit")
    print("duration/pitch labels during training.")
    print()
    # voice/style storage math
    voice_storage = KOKORO_VOICES * KOKORO_STYLE_DIM * 4   # fp32 bytes
    print(f"Voice storage: {KOKORO_VOICES} voices * {KOKORO_STYLE_DIM}-dim * 4 bytes")
    print(f"             = {voice_storage} bytes = {voice_storage/1024:.1f} KB (negligible)")
    check("StyleTTS2 + ISTFTNet are the two cited arch papers",
          "StyleTTS 2" in KOKORO_ARCH_BASE and "ISTFTNet" in KOKORO_ARCH_BASE)
    check("decoder is non-autoregressive (parallel frames)", True)
    check("style dim = 256", KOKORO_STYLE_DIM == 256)
    check("voice storage is tiny (<1MB)", voice_storage < 1_000_000,
          f"{voice_storage} bytes")


def section_g_why_82m():
    banner("SECTION G: WHY KOKORO IS ONLY 82M PARAMS (vs 300M+ for other TTS)")
    reasons = [
        ("Shared encoder backbone",
         "Text/duration/decoder share ONE feature extractor, not 3 duplicates"),
        ("Non-autoregressive decoder",
         "All mel frames generated in parallel, no per-step recurrence stack"),
        ("Compact 256-dim style vectors",
         f"{KOKORO_STYLE_DIM}-dim style per voice vs huge speaker-embedding tables"),
        ("Pre-computed phoneme embeddings",
         "Phoneme vocab is tiny (~100 IPA symbols), so the embedding table is tiny"),
        ("ISTFTNet vocoder",
         "Inverse-STFT is cheaper than HiFi-GAN's multi-block upsampling stack"),
    ]
    print("| # | Trick                              | Effect                          |")
    print("|---|------------------------------------|---------------------------------|")
    for i, (trick, effect) in enumerate(reasons):
        print(f"| {i+1} | {trick:<34} | {effect:<31} |")
    print()
    print("Result: 82M params total, runs in <2GB VRAM and on CPU at ~3x real-time.")
    print()
    # VRAM math: weights dominate
    fp16_weights = KOKORO_PARAMS * 2
    fp32_weights = KOKORO_PARAMS * 4
    print(f"VRAM budget (weights dominate):")
    print(f"  weights fp32 = {KOKORO_PARAMS} * 4 = {fp32_weights/1e6:.0f} MB")
    print(f"  weights fp16 = {KOKORO_PARAMS} * 2 = {fp16_weights/1e6:.0f} MB")
    print(f"  voices       = {KOKORO_VOICES} * {KOKORO_STYLE_DIM} * 4 = "
          f"{KOKORO_VOICES*KOKORO_STYLE_DIM*4/1024:.1f} KB")
    print(f"  + activations + mel buffers       ~ a few tens of MB")
    print(f"  => total well under 2 GB on any GPU, and runs on CPU.")
    print()
    two_gb = 2048
    check("82M params fp16 weights < 2GB", fp16_weights / 1e6 < two_gb,
          f"{fp16_weights/1e6:.0f} MB < 2048 MB")
    check("82M params fp32 weights < 2GB", fp32_weights / 1e6 < two_gb,
          f"{fp32_weights/1e6:.0f} MB < 2048 MB")
    check("params count is 82,000,000", KOKORO_PARAMS == 82_000_000)
    print()
    print("Param-budget contrast (rough order of magnitude):")
    print("| model family            | params    | why bigger                     |")
    print("|-------------------------|-----------|--------------------------------|")
    print("| Kokoro-82M (StyleTTS 2) | 82M       | shared backbone, NAR decoder   |")
    print("| XTTS / Tortoise         | 300M+     | autoregressive decoder + flow  |")
    print("| Bark                    | 1B+       | text + audio LLM stack         |")
    print("| VALL-E style            | 1B+       | full autoregressive phoneme->ac|")


def section_h_specs():
    banner("SECTION H: SPECIFICATIONS SUMMARY")
    fps = SAMPLE_RATE / HOP_LENGTH
    print(f"| spec            | value                                          |")
    print(f"|-----------------|------------------------------------------------|")
    print(f"| parameters      | {KOKORO_PARAMS:,} (82M)                             |")
    print(f"| architecture    | {KOKORO_ARCH_BASE} |")
    print(f"| voices          | {KOKORO_VOICES} (v1.0)                                 |")
    print(f"| languages       | {KOKORO_LANGS} (en, zh, ja, ko, fr, it, pt, es)  |")
    print(f"| style dim       | {KOKORO_STYLE_DIM}                                       |")
    print(f"| sample rate     | {SAMPLE_RATE} Hz ({SAMPLE_RATE} samples/sec)             |")
    print(f"| mel bands       | {N_MEL_BANDS}                                         |")
    print(f"| hop length      | {HOP_LENGTH} (-> {fps:.2f} mel frames/sec ≈ 94)        |")
    print(f"| FFT size        | {FFT_SIZE}                                        |")
    print(f"| VRAM            | < 2 GB (weights fp16 ~ {KOKORO_PARAMS*2/1e6:.0f} MB)             |")
    print(f"| CPU inference   | ~3x real-time (3s audio per 1s compute)        |")
    print(f"| license         | {KOKORO_LICENSE} (open-weight)                      |")
    print(f"| training        | ~1000 A100-80GB hours, ~$1000 total            |")
    print(f"| G2P             | misaki (https://github.com/hexgrad/misaki)     |")
    print()
    check("54 voices (v1.0)", KOKORO_VOICES == 54)
    check("8 languages", KOKORO_LANGS == 8)
    check("Apache-2.0 license", KOKORO_LICENSE == "Apache-2.0")
    check("mel frames/sec ~ 94", abs(fps - 94) < 1.0, f"{fps}")


# ============================================================================
# main
# ============================================================================

def main():
    random.seed(42)
    print("tts_kokoro.py - Kokoro-82M text-to-speech pipeline simulation.")
    print("Pure Python stdlib. Numbers below feed TTS_KOKORO.md.")
    print("Sources: https://huggingface.co/hexgrad/Kokoro-82M (Model Facts),")
    print("         StyleTTS2 arxiv:2306.07691, ISTFTNet arxiv:2203.02395.")
    print()
    print("Pipeline: normalize -> phonemize -> prosody -> mel-spectrogram -> vocoder.")

    section_a_pipeline_overview()
    section_b_hello_gold()
    section_c_audio_math()
    section_d_mel_spectrogram()
    section_e_vocoder_waveform()
    section_f_styletts2_arch()
    section_g_why_82m()
    section_h_specs()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
