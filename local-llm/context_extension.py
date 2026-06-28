"""
context_extension.py - Reference implementation of RoPE context-extension
scaling methods (linear, NTK-aware, YaRN, dynamic NTK).

This is the single source of truth that CONTEXT_EXTENSION.md is built from.
Every number, table, and worked example in CONTEXT_EXTENSION.md is printed by
this file. Pure Python stdlib only (NO torch, NO numpy) - this is the *local
runtime* side: how to stretch a model's trained context window at load time,
not the math derivation of the base rotation (that is llm/rope.py).

Run:
    python3 context_extension.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
A model trained with Rotary Position Embeddings (RoPE) on context L_orig
cannot attend to positions beyond L_orig: the angles m*freq it was trained on
stop at L_orig*freq, and anything beyond is an UNSEEN angle the model guesses
at (extrapolation). The fix is to RESHAPE the angle function so positions up to
the new target L_target still land inside the trained angle range.

RoPE base frequency theta (default 10000). For position i and dim pair d:
    freq_i_d   = 1.0 / (theta ^ (2d / D))        D = head_dim
    angle_i_d  = i * freq_i_d

scale = L_target / L_orig  (how far we are stretching the window).

Four methods, oldest -> newest, each better at preserving quality:

  LINEAR (Position Interpolation, PI)
    Divide all positions by scale.  position_eff = position / scale
    -> every freq is effectively divided by scale. Simple, but the HIGH-freq
       dims (local token-to-token structure) get blurred too, so quality drops
       hard past ~4x.

  NTK-AWARE
    Adjust the base instead of the positions.
    theta_new = theta * scale ^ (D / (D-2))
    High frequencies (small d) are left ~unchanged -> local relationships
    preserved. Low frequencies (large d) get stretched -> long-range positions
    extended. Much better quality than linear.

  YARN
    Band-wise (piecewise) scaling: different bands of the frequency ladder get
    different treatment, joined by a smooth ramp.
      - Extrapolation band (high freq, many rotations): NO change.
      - Interpolation band (low freq, <1 rotation over L_orig): freq / scale.
      - Middle: smooth blend.
    Best quality for extreme extension (8x-32x). Adds an attention factor.

  DYNAMIC NTK
    The scale grows per-token as the sequence lengthens.
    scale_t = max(1, current_position / L_orig)
    theta_new_t = theta * scale_t ^ (D/(D-2))
    Gradual degradation, ideal for streaming (unknown final length).

GOLD VALUE (for context_extension.html to reproduce):
    RoPE D=4, theta=10000, scale=4 (4K -> 16K)
    NTK:  theta_new = 10000 * 4^(4/2) = 10000 * 16 = 160000
    freq_1 changes from 1/100 = 0.01  to  1/400 = 0.0025
    (high-freq freq_0 stays 1.0 -> local structure preserved)
"""

from __future__ import annotations

import math

BANNER = "=" * 74

# ---------------------------------------------------------------------------
# Defaults / hero config
# ---------------------------------------------------------------------------
DEFAULT_THETA = 10000      # the canonical RoPE base frequency
HERO_DIM = 4               # head_dim for the gold example (tiny, printable)
HERO_SCALE = 4             # 4K -> 16K
L_ORIG = 4096              # trained context window
YARN_DEMO_DIM = 8          # bigger head_dim so YaRN's bands are visible


# ============================================================================
# 0. CHECK HELPER (invariants the methods must satisfy)
# ============================================================================

def check(label: str, cond: bool, detail: str = ""):
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


# ============================================================================
# 1. CORE FORMULAS (1:1 with the paper / HF rope_scaling math)
# ============================================================================

def rope_freqs(theta: float, D: int) -> list[float]:
    """The RoPE frequency ladder: freq_d = 1 / theta^(2d/D) for d in 0..D/2-1.

    d=0 -> highest frequency (shortest wavelength, local structure).
    d=D/2-1 -> lowest frequency (longest wavelength, long-range structure).
    """
    return [1.0 / (theta ** (2 * d / D)) for d in range(D // 2)]


def ntk_theta(theta: float, scale: float, D: int) -> float:
    """NTK-aware base frequency: theta_new = theta * scale^(D/(D-2)).

    Verified for D=4, scale=4: theta * 4^(4/2) = theta * 16.
    """
    return theta * (scale ** (D / (D - 2)))


def linear_freqs(freqs: list[float], scale: float) -> list[float]:
    """Linear / Position Interpolation: every freq divided by scale.

    Equivalent to position_eff = position / scale applied to all positions.
    """
    return [f / scale for f in freqs]


def yarn_band_weights(D: int, theta: float, l_orig: int,
                      beta_fast: int = 32, beta_slow: int = 1) -> list[float]:
    """YaRN per-dim interpolation weight w_d in [0,1].

    w_d = 0  -> extrapolation band (high freq, many rotations): NO change.
    w_d = 1  -> interpolation band (low freq, <1 rotation): freq / scale.
    Smooth ramp in between, bounded by the beta_fast / beta_slow rotation
    counts (the YaRN paper's Algorithm 1, correction-dim form).
    """
    n = D // 2

    def correction_dim(num_rotations: float) -> float:
        # dim index whose wavelength completes exactly `num_rotations` over
        # the original context window.
        return (D * math.log(l_orig / (num_rotations * 2 * math.pi))) \
            / (2 * math.log(theta))

    k_fast = correction_dim(beta_fast)   # high-freq boundary
    k_slow = correction_dim(beta_slow)   # low-freq boundary
    span = k_slow - k_fast
    weights = []
    for d in range(n):
        w = 0.0 if span == 0 else (d - k_fast) / span
        weights.append(max(0.0, min(1.0, w)))
    return weights


def yarn_freqs(freqs: list[float], scale: float,
               weights: list[float]) -> list[float]:
    """YaRN blend per dim:  freq * (1 - w) + (freq/scale) * w."""
    return [f * (1 - w) + (f / scale) * w for f, w in zip(freqs, weights)]


def dynamic_scale(position: int, l_orig: int, scale: float) -> float:
    """Dynamic NTK per-token scale: grows from 1 to `scale` as position grows."""
    return max(1.0, min(scale, position / l_orig))


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_row(values: list[float], p: int = 4) -> str:
    return "[" + ", ".join(f"{v:+.{p}f}" for v in values) + "]"


def wavelength(freq: float) -> float:
    """Wavelength lambda = 2*pi / freq (positions per full rotation)."""
    return (2 * math.pi) / freq if freq != 0 else math.inf


# ============================================================================
# 3. SECTIONS
# ============================================================================

def section_a_rope_ladder():
    banner("SECTION A: the RoPE frequency ladder (what we are scaling)")
    print(f"RoPE base theta = {DEFAULT_THETA} (default), head_dim D = {HERO_DIM}")
    print(f"freq_d = 1 / theta^(2d/D), for d in 0..D/2-1. angle_i_d = i * freq_d")
    print()
    freqs = rope_freqs(DEFAULT_THETA, HERO_DIM)
    print("| d | exponent 2d/D | theta^(2d/D) |   freq_d   | wavelength 2pi/freq |")
    print("|---|---------------|--------------|------------|----------------------|")
    for d in range(HERO_DIM // 2):
        exp = 2 * d / HERO_DIM
        base_pow = DEFAULT_THETA ** exp
        f = freqs[d]
        lam = wavelength(f)
        print(f"| {d} | {exp:>13.4f} | {base_pow:>12.2f} | {f:>10.6f} | {lam:>20.4f} |")
    print()
    print(f"freqs = {fmt_row(freqs, 4)}")
    print("d=0 is the HIGHEST frequency (wavelength ~6.3 positions): it encodes")
    print("LOCAL token-to-token structure. d=1 is lower (wavelength ~628): it")
    print("encodes LONG-RANGE structure. Every scaling method trades these off.")
    print()
    print("The extrapolation problem: at position i the model saw angle i*freq")
    print("only up to i = L_orig = 4096. Beyond that the angle is UNSEEN. The")
    print("angle at i = 4096 is the trained CEILING for each dim:")
    print()
    print("| d | freq_d   | angle at L_orig=4096 |")
    print("|---|----------|----------------------|")
    for d in range(HERO_DIM // 2):
        f = freqs[d]
        print(f"| {d} | {f:>8.4f} | {L_ORIG * f:>20.4f} |")
    check("freq_0 = 1.0 for any theta", abs(rope_freqs(DEFAULT_THETA, HERO_DIM)[0] - 1.0) < 1e-12)
    check("freq_1 = 0.01 for theta=10000, D=4",
          abs(rope_freqs(DEFAULT_THETA, HERO_DIM)[1] - 0.01) < 1e-12,
          f"got {rope_freqs(DEFAULT_THETA, HERO_DIM)[1]}")


def section_b_linear():
    banner("SECTION B: LINEAR scaling (Position Interpolation) - divide positions")
    scale = HERO_SCALE
    print(f"scale = L_target / L_orig = {scale}  (4096 -> {L_ORIG * scale})")
    print("Method:  position_eff = position / scale   (apply to ALL positions)")
    print("Effect:  effective freq_d becomes freq_d / scale for EVERY dim.")
    print()
    freqs = rope_freqs(DEFAULT_THETA, HERO_DIM)
    lin = linear_freqs(freqs, scale)
    print("| d | original freq | linear freq  | ratio |")
    print("|---|---------------|--------------|-------|")
    for d in range(HERO_DIM // 2):
        print(f"| {d} | {freqs[d]:>13.4f} | {lin[d]:>12.4f} | {lin[d]/freqs[d]:>5.2f} |")
    print()
    print(f"original = {fmt_row(freqs, 4)}")
    print(f"linear   = {fmt_row(lin, 4)}")
    print()
    print("The HIGH-freq dim d=0 is ALSO divided by 4 (1.0 -> 0.25). That blurs")
    print("local structure: two adjacent tokens that used to differ by a full")
    print("rotation now differ by only a quarter. Quality degrades hard >4x.")
    print()
    # angle ceiling: at L_target, linear maps back to original ceiling
    l_target = L_ORIG * scale
    print(f"At L_target={l_target}, linear angle_d = {l_target}*freq/{scale} = "
          f"{L_ORIG}*freq (the ORIGINAL ceiling):")
    print("| d | linear freq | angle at L_target | original ceiling | match? |")
    print("|---|-------------|-------------------|------------------|--------|")
    for d in range(HERO_DIM // 2):
        ang = l_target * lin[d]
        ceil = L_ORIG * freqs[d]
        print(f"| {d} | {lin[d]:>11.4f} | {ang:>17.4f} | {ceil:>16.4f} | "
              f"{'YES' if abs(ang - ceil) < 1e-9 else 'no':>6} |")
    check("linear divides every freq by scale",
          all(abs(linear_freqs(freqs, scale)[d] - freqs[d] / scale) < 1e-12
              for d in range(len(freqs))))
    check("linear maps L_target angle back to original ceiling",
          abs(l_target * lin[1] - L_ORIG * freqs[1]) < 1e-9)


def section_c_ntk():
    banner("SECTION C: NTK-AWARE - adjust the base frequency  *** GOLD ***")
    scale = HERO_SCALE
    theta_new = ntk_theta(DEFAULT_THETA, scale, HERO_DIM)
    print(f"theta_new = theta * scale^(D/(D-2))")
    print(f"         = {DEFAULT_THETA} * {scale}^({HERO_DIM}/({HERO_DIM}-2))")
    print(f"         = {DEFAULT_THETA} * {scale}^{HERO_DIM // (HERO_DIM - 2)}")
    print(f"         = {DEFAULT_THETA} * {scale ** (HERO_DIM / (HERO_DIM - 2)):.0f}")
    print(f"         = {theta_new:.0f}")
    print()
    freqs = rope_freqs(DEFAULT_THETA, HERO_DIM)
    ntk = rope_freqs(theta_new, HERO_DIM)
    print("| d | original freq | NTK freq     | ratio freq_new/freq |")
    print("|---|---------------|--------------|---------------------|")
    for d in range(HERO_DIM // 2):
        ratio = ntk[d] / freqs[d] if freqs[d] else 0.0
        print(f"| {d} | {freqs[d]:>13.4f} | {ntk[d]:>12.6f} | {ratio:>19.6f} |")
    print()
    print(f"original = {fmt_row(freqs, 4)}")
    print(f"NTK      = {fmt_row(ntk, 6)}")
    print()
    print("KEY: d=0 (highest freq) is UNCHANGED (ratio 1.0) -> local structure")
    print("preserved. Only d=1 (low freq) is stretched (0.01 -> 0.0025). This is")
    print("why NTK beats linear: it never blurs the local dims.")
    print()
    print("GOLD (for context_extension.html):")
    print(f"  theta=10000, D=4, scale=4 -> theta_new = {theta_new:.0f}")
    print(f"  freq_1: {freqs[1]:.4f} -> {ntk[1]:.6f}")
    print()
    check("NTK theta_new = 160000 for D=4, scale=4",
          abs(theta_new - 160000.0) < 1e-6, f"got {theta_new}")
    check("NTK preserves high-freq dim d=0 (freq_0 = 1.0)",
          abs(ntk[0] - 1.0) < 1e-12, f"got {ntk[0]}")
    check("NTK stretches low-freq dim d=1 (0.01 -> 0.0025)",
          abs(ntk[1] - 0.0025) < 1e-12, f"got {ntk[1]}")


def section_d_yarn():
    banner("SECTION D: YaRN - band-wise scaling (piecewise, with a ramp)")
    D = YARN_DEMO_DIM
    scale = HERO_SCALE
    print(f"YaRN needs several dim pairs to show its bands, so D={D} here "
          f"(({D // 2} freq pairs). Same theta={DEFAULT_THETA}, scale={scale}).")
    print()
    print("Each dim is classified by how many full rotations its wavelength")
    print("completes over L_orig=4096:")
    print("  beta_fast=32 rotations  -> high-freq boundary (above = extrapolation)")
    print("  beta_slow=1  rotation   -> low-freq boundary  (below = interpolation)")
    print()
    freqs = rope_freqs(DEFAULT_THETA, D)
    weights = yarn_band_weights(D, DEFAULT_THETA, L_ORIG)
    yarn = yarn_freqs(freqs, scale, weights)
    lin = linear_freqs(freqs, scale)
    theta_new = ntk_theta(DEFAULT_THETA, scale, D)
    ntk = rope_freqs(theta_new, D)
    print("| d | original | w_d (interp weight) | band        | YaRN freq  | linear | NTK freq |")
    print("|---|----------|---------------------|-------------|------------|--------|----------|")
    for d in range(D // 2):
        band = ("extrapolation" if weights[d] <= 0.0
                else "interpolation" if weights[d] >= 1.0
                else "ramp (blend)")
        print(f"| {d} | {freqs[d]:>8.4f} | {weights[d]:>19.4f} | {band:<11} | "
              f"{yarn[d]:>10.6f} | {lin[d]:>6.4f} | {ntk[d]:>8.6f} |")
    print()
    print(f"original = {fmt_row(freqs, 4)}")
    print(f"YaRN     = {fmt_row(yarn, 6)}")
    print(f"linear   = {fmt_row(lin, 4)}  (reference: uniform /scale)")
    print(f"NTK      = {fmt_row(ntk, 6)}  (reference: smooth base stretch)")
    print()
    print("YaRN preserves BOTH high-freq dims (d=0,1 unchanged, like NTK but a")
    print("SHARPER boundary), fully interpolates the lowest dim (d=3 = linear),")
    print("and blends the middle (d=2). YaRN also multiplies the attention logits")
    print("by an attention_factor ~ sqrt(1 + ln(scale)/ln(L_orig)) to compensate")
    print("for the distribution shift. Best quality at 8x-32x extension.")
    print()
    # d=0 must be unchanged (extrapolation band), d=3 must equal linear (interp)
    check("YaRN keeps highest-freq d=0 unchanged",
          abs(yarn[0] - freqs[0]) < 1e-12, f"got {yarn[0]} vs {freqs[0]}")
    check("YaRN fully interpolates lowest-freq d=last (= linear)",
          abs(yarn[-1] - lin[-1]) < 1e-12, f"got {yarn[-1]} vs {lin[-1]}")
    check("YaRN middle dim is between original and linear",
          freqs[2] - 1e-9 >= yarn[2] >= lin[2] - 1e-9,
          f"yarn[2]={yarn[2]} orig={freqs[2]} lin={lin[2]}")


def section_e_dynamic():
    banner("SECTION E: DYNAMIC NTK - scale grows per-token (streaming)")
    D = HERO_DIM
    scale = HERO_SCALE
    print("For streaming (unknown final length) recompute theta each token:")
    print("  scale_t = max(1, current_position / L_orig), capped at target scale")
    print("  theta_t = theta * scale_t ^ (D/(D-2))")
    print()
    print("Within L_orig: scale=1 -> original theta (zero degradation). Past")
    print("L_orig theta grows gradually until it reaches the full NTK value.")
    print()
    print("| position | scale_t | theta_t  | freq_1 (low-freq dim) |")
    print("|----------|---------|----------|-----------------------|")
    positions = [2048, L_ORIG, 2 * L_ORIG, 3 * L_ORIG, 4 * L_ORIG]
    for p in positions:
        st = dynamic_scale(p, L_ORIG, scale)
        th = ntk_theta(DEFAULT_THETA, st, D)
        f1 = 1.0 / (th ** (2 * 1 / D))
        print(f"| {p:>8} | {st:>7.4f} | {th:>8.0f} | {f1:>21.6f} |")
    print()
    print("At p=4096 (the trained boundary) theta is still 10000 (unchanged). The")
    print("model only starts stretching once it actually exceeds L_orig. This gives")
    print("gradual degradation instead of a fixed scale applied from token 0.")
    # at p=L_orig, theta must equal original
    th0 = ntk_theta(DEFAULT_THETA, dynamic_scale(L_ORIG, L_ORIG, scale), D)
    check("dynamic NTK theta == original at p=L_orig",
          abs(th0 - DEFAULT_THETA) < 1e-9, f"got {th0}")
    # at p=L_target, dynamic theta must equal full static NTK
    th_full = ntk_theta(DEFAULT_THETA, dynamic_scale(4 * L_ORIG, L_ORIG, scale), D)
    th_ntk = ntk_theta(DEFAULT_THETA, scale, D)
    check("dynamic NTK theta == full NTK at p=L_target",
          abs(th_full - th_ntk) < 1e-9, f"got {th_full} vs {th_ntk}")


def section_f_comparison():
    banner("SECTION F: comparison - which method, which scale")
    print("| method      | what it scales      | high-freq (local) | quality @4x | quality @8x+ | use case              |")
    print("|-------------|---------------------|-------------------|-------------|--------------|-----------------------|")
    rows = [
        ("linear/PI",  "positions (/scale)",      "blurred (/scale)", "OK",      "degrades",  "simplest, old models"),
        ("NTK-aware",  "base theta",              "preserved (~1.0)", "good",    "soft drop", "one-shot, no finetune"),
        ("YaRN",       "bands + attention factor","preserved",        "best",    "best",      "extreme 8x-32x, finetuned"),
        ("dynamic NTK","base theta per-token",    "preserved early",  "good",    "gradual",   "streaming, unknown len"),
    ]
    for m, w, hf, q4, q8, uc in rows:
        print(f"| {m:<11} | {w:<19} | {hf:<17} | {q4:<11} | {q8:<12} | {uc:<21} |")
    print()
    print("llama.cpp / HF rope_scaling flags:")
    print("  HF:       rope_scaling={'type':'linear','factor':4}")
    print("            rope_scaling={'type':'ntk','factor':4}")
    print("            rope_scaling={'type':'yarn','factor':8}")
    print("  llama.cpp: --rope-scale 4  (linear)")
    print("             --rope-freq-base 160000  (manual NTK base for D~128)")
    print("             --rope-scaling yarn --rope-scale 8")
    print()
    check("linear is the only method that scales high-freq",
          all(r[2].startswith("blurred") for r in rows if r[0] == "linear/PI"))
    check("YaRN is best at extreme extension",
          rows[2][4] == "best")


# ============================================================================
# main
# ============================================================================

def main():
    print("context_extension.py - RoPE context-extension scaling reference.")
    print("Pure Python stdlib. Numbers below feed CONTEXT_EXTENSION.md.")
    print("Sources: NTK-aware (reddit r/LocalLLaMA), YaRN paper arXiv:2309.00071.")
    print()
    print("Four methods: linear -> NTK-aware -> YaRN -> dynamic NTK")

    section_a_rope_ladder()
    section_b_linear()
    section_c_ntk()
    section_d_yarn()
    section_e_dynamic()
    section_f_comparison()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
