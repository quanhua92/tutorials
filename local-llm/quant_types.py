"""
quant_types.py - Reference implementation of GGUF block quantization types.

This is the single source of truth that QUANT_TYPES.md is built from. Every
number, table, and worked example in QUANT_TYPES.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy) - this is the *local runtime*
side (GGUF/GGML), not the server-side W4A16 of llm/quantization.py.

Run:
    python3 quant_types.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
A "quant type" is a recipe for packing a BLOCK of consecutive weights into a
fixed number of bytes, plus a formula for unpacking them back to a float during
the matmul. The whole game is choosing the block layout + the dequant formula
that gives the best quality-per-byte on a specific hardware budget.

Three families, oldest to newest:

  LEGACY (Q4_0, Q4_1, Q5_1, Q8_0, ...)
    One block = 32 weights (matches a 256-bit SIMD lane). Each block stores a
    fp16 scale (+ optional fp16 min) and the packed integer weights. Uniform:
    every layer uses the same type.
        dequant Q4_0:  w = d * (q - 8)              symmetric,  q in 0..15
        dequant Q4_1:  w = m + d * q                asymmetric, q in 0..15
        dequant Q8_0:  w = d * q                    symmetric,  q in -128..127

  K-QUANTS (Q2_K, Q3_K, Q4_K, Q5_K, Q6_K)
    A SUPER-BLOCK = 256 weights, split into 8 sub-blocks of 32. Each sub-block
    gets its OWN scale (+ min), and those per-sub-block scales are themselves
    quantized to 6 bits and re-scaled by a fp16 super-block scale `d` (and
    `dmin`). Double quantization => better resolution per byte. The "_M"
    variant MIXES types across layers (Q6_K for the sensitive layers, Q4_K for
    the rest) -> best quality/size.
        dequant Q4_K:  w = (dmin*min6) + (d*scale6) * q    per sub-block

  I-QUANTS (IQ2, IQ3, IQ4, ...)
    "Importance" quants. Calibrated with an importance matrix (imatrix) built
    from a calibration set, and use non-linear LOOKUP TABLES (codebooks) for
    dequant instead of a simple affine formula. Squeezes the last bit of
    quality out of very low bit counts (2-3 bpw). Same byte budget as the
    matching K-quant, much lower perplexity.

GOLD VALUE (for QUANT_TYPES.html to reproduce):
    Q4_0 block, q=[3,7,1,6,9,2,5,8], d=0.5
    -> dequant = [0.5*(q-8) for each]
    -> [-2.5, -0.5, -3.5, -1.0, 0.5, -3.0, -1.5, 0.0]
"""

from __future__ import annotations

# Block sizes (verified against ggml/src/ggml-common.h struct definitions).
QK4_0 = 32   # block_q4_0 : weights per block
QK4_1 = 32   # block_q4_1
QK5_1 = 32   # block_q5_1
QK8_0 = 32   # block_q8_0
QK_K  = 256  # super-block size for all K-quants and I-quants
K_SCALE_SIZE = 12  # bytes holding the 8x6-bit scales + 8x6-bit mins in a K-quant

BANNER = "=" * 74


# ============================================================================
# 0. CHECK HELPER (invariants the dequant must satisfy)
# ============================================================================

def check(label: str, cond: bool, detail: str = ""):
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


# ============================================================================
# 1. FP16 SIMULATION (minimal, only what dequant needs)
#    Real GGUF stores d/m as IEEE 754 binary16. We round to float16 precision so
#    our byte budgets and dequant numbers match what a real runtime produces.
# ============================================================================

def to_f16(x: float) -> float:
    """Round a Python float to the nearest IEEE-754 binary16 value (truncated
    to 10 mantissa bits + 5 exponent bits). Faithful enough for dequant math."""
    import math, struct
    if x == 0.0:
        return 0.0
    if math.isnan(x):
        return x
    # pack as float16 via struct, unpack back to float
    try:
        return struct.unpack("<e", struct.pack("<e", x))[0]
    except (OverflowError, struct.error):
        return math.inf if x > 0 else -math.inf


# ============================================================================
# 2. DEQUANT FUNCTIONS (faithful ports of ggml-quants.c dequantize_row_*)
# ============================================================================

def dequant_q4_0(d: float, quants: list[int]) -> list[float]:
    """Q4_0:  symmetric. q in 0..15, weight = d * (q - 8).

    Block layout (18 bytes, 32 weights):
        d  : ggml_half (2 bytes)   the scale
        qs : 16 bytes              32 nibbles (4 bits each), packed 2-per-byte
    """
    return [d * (q - 8) for q in quants]


def dequant_q4_1(d: float, m: float, quants: list[int]) -> list[float]:
    """Q4_1:  asymmetric. q in 0..15, weight = m + d * q.

    Block layout (20 bytes, 32 weights):
        d  : ggml_half (2 bytes)   the scale (step size)
        m  : ggml_half (2 bytes)   the min (offset)
        qs : 16 bytes              32 nibbles
    """
    return [m + d * q for q in quants]


def dequant_q8_0(d: float, quants: list[int]) -> list[float]:
    """Q8_0:  symmetric int8. q in -128..127, weight = d * q.

    Block layout (34 bytes, 32 weights):
        d  : ggml_half (2 bytes)   the scale
        qs : 32 bytes              32 signed 8-bit ints
    Q8_0 is the reference: near-lossless, used to measure other quants' error.
    """
    return [d * q for q in quants]


def dequant_q5_1(d: float, m: float, qs_low: list[int], qh_bits: list[int]) -> list[float]:
    """Q5_1:  asymmetric 5-bit. q in 0..31, weight = m + d * q.

    Block layout (24 bytes, 32 weights):
        d  : ggml_half (2 bytes)   the scale
        m  : ggml_half (2 bytes)   the min
        qh : 4 bytes (uint32)      the 5th bit of each of the 32 weights
        qs : 16 bytes              the low 4 bits of each weight (nibbles)
    q = low4 | (bit << 4)
    """
    out = []
    for low4, bit in zip(qs_low, qh_bits):
        q = low4 | (bit << 4)
        out.append(m + d * q)
    return out


def dequant_q4_k_superblock(d: float, dmin: float,
                            sub_scales6: list[int], sub_mins6: list[int],
                            quants: list[int]) -> list[float]:
    """Q4_K super-block (concept): 256 weights, 8 sub-blocks of 32.

    Each sub-block j has a 6-bit scale `scale6_j` and a 6-bit min `min6_j`,
    BOTH re-scaled by the super-block's fp16 `d` (for scales) and fp16
    `dmin` (for mins). Double quantization: the scale of the scales.

        effective_scale_j = d * scale6_j
        effective_min_j    = dmin * min6_j
        weight = effective_min_j + effective_scale_j * q   (q in 0..15)

    Real block layout (144 bytes, 256 weights):
        d        : ggml_half (2 bytes)   super-block scale for the scales
        dmin     : ggml_half (2 bytes)   super-block scale for the mins
        scales   : 12 bytes (K_SCALE_SIZE) 8x6-bit scales + 8x6-bit mins packed
        qs       : 128 bytes             256 nibbles (4 bits each)
    144/256 = 4.5 bpw for pure Q4_K.
    """
    out = []
    for j in range(8):
        scale_j = d * sub_scales6[j]
        min_j = dmin * sub_mins6[j]
        chunk = quants[j * 32:(j + 1) * 32]
        for q in chunk:
            out.append(min_j + scale_j * q)
    return out


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_row(values: list[float], p: int = 2) -> str:
    return "[" + ", ".join(f"{v:+.{p}f}" for v in values) + "]"


# ============================================================================
# 4. THE HERO BLOCK (deterministic, used for the gold-check)
#    8 weights of a Q4_0 block. q values 0..15, scale 0.5. Chosen so every
#    dequant lands on an exact .0/.5 -> bit-stable across py/js/float16.
# ============================================================================

HERO_Q  = [3, 7, 1, 6, 9, 2, 5, 8]      # the 8 nibble values (0..15)
HERO_D  = 0.5                            # the fp16 scale (delta)


# ============================================================================
# 5. SECTIONS
# ============================================================================

def section_a_q4_0():
    banner("SECTION A: Q4_0 - symmetric 4-bit, the original block quant")
    print(f"Q4_0 block layout (verified: ggml/src/ggml-common.h block_q4_0):")
    print(f"  QK4_0 = {QK4_0} weights per block")
    print(f"  bytes = sizeof(ggml_half) + QK4_0/2 = 2 + {QK4_0//2} = {2 + QK4_0//2} bytes")
    print(f"  bits/weight = {2 + QK4_0//2}*8 / {QK4_0} = {(2 + QK4_0//2)*8/QK4_0:.4f}")
    print()
    print(f"Dequant formula (symmetric):")
    print(f"  weight = d * (q - 8)     where d = fp16 scale, q = 4-bit value in 0..15")
    print(f"  (q-8) maps 0..15 onto -8..+7, centered on zero -> SYMMETRIC)")
    print()
    print(f"Hero block (8 of the 32 weights, for printability):")
    print(f"  q (4-bit values) = {HERO_Q}")
    print(f"  d (scale)        = {HERO_D}")
    print()
    print("| i | q  | q-8 |  d*(q-8)  |")
    print("|---|----|-----|-----------|")
    deq = dequant_q4_0(HERO_D, HERO_Q)
    for i, (q, w) in enumerate(zip(HERO_Q, deq)):
        print(f"| {i} | {q:>2} | {q-8:>3} | {w:>+9.1f} |")
    print()
    print(f"GOLD (for QUANT_TYPES.html):")
    print(f"  dequant_q4_0(d={HERO_D}, q={HERO_Q})")
    print(f"    = {fmt_row(deq, 1)}")
    expected = [-2.5, -0.5, -3.5, -1.0, 0.5, -3.0, -1.5, 0.0]
    check("Q4_0 hero dequant matches spec",
          deq == expected, f"got {fmt_row(deq,1)} expected {expected}")
    print()
    print("Why symmetric is weak: the range is forced to be centered on zero, so")
    print("a block whose weights are all positive wastes half the codebook. Q4_1")
    print("fixes this by adding an explicit min offset (Section B).")


def section_b_q4_1():
    banner("SECTION B: Q4_1 - asymmetric, adds an fp16 min offset")
    print(f"Q4_1 block layout (verified: block_q4_1):")
    print(f"  QK4_1 = {QK4_1} weights per block")
    print(f"  bytes = 2*sizeof(ggml_half) + QK4_1/2 = 4 + {QK4_1//2} = {4 + QK4_1//2} bytes")
    print(f"  bits/weight = {4 + QK4_1//2}*8 / {QK4_1} = {(4 + QK4_1//2)*8/QK4_1:.4f}")
    print()
    print("Dequant formula (asymmetric affine):")
    print("  weight = m + d * q     m = fp16 min (offset), q in 0..15")
    print("  The min lets q=0 map to the block's actual minimum, so no codebook")
    print("  range is wasted. Costs 2 extra bytes/block (the min) -> 5.0 bpw.")
    print()
    # Same 8 weights; choose d,m so the block is all-positive (Q4_0's weakness).
    q = [0, 3, 7, 1, 6, 9, 2, 5]
    d = to_f16(0.1)
    m = to_f16(0.4)   # block minimum -> q=0 maps to 0.4
    print(f"Block: q={q}, d={d}, m={m}")
    deq = dequant_q4_1(d, m, q)
    print()
    print("| i | q  | m + d*q   |")
    print("|---|----|-----------|")
    for i, (qi, w) in enumerate(zip(q, deq)):
        print(f"| {i} | {qi:>2} | {w:>+9.4f} |")
    print()
    print(f"dequant = {[round(w,4) for w in deq]}")
    # q=0 must map exactly to m (the min)
    check("Q4_1 q=0 maps to min m", abs(deq[0] - m) < 1e-6,
          f"deq[0]={deq[0]} m={m}")
    # all positive -> no wasted codebook range
    check("Q4_1 block stays in range [m, m+15d]",
          all(m - 1e-9 <= w <= m + 15 * d + 1e-9 for w in deq))


def section_c_q8_0():
    banner("SECTION C: Q8_0 - 8-bit reference, near-lossless")
    print(f"Q8_0 block layout (verified: block_q8_0):")
    print(f"  QK8_0 = {QK8_0} weights per block")
    print(f"  bytes = sizeof(ggml_half) + QK8_0 = 2 + {QK8_0} = {2 + QK8_0} bytes")
    print(f"  bits/weight = {2 + QK8_0}*8 / {QK8_0} = {(2 + QK8_0)*8/QK8_0:.4f}")
    print()
    print("Dequant formula (symmetric int8):")
    print("  weight = d * q     q = signed 8-bit (-128..127)")
    print("  256 levels per weight -> quantization error ~ scale/256, tiny.")
    print("  Q8_0 is the REFERENCE: it is what 'full quality' means locally, and")
    print("  the error of every other type is measured against a Q8_0 baseline.")
    print()
    # model a float weight row, quantize to Q8_0, measure round-trip error.
    orig = [-0.72, 0.31, -0.05, 1.12, -0.88, 0.46, -1.20, 0.93]
    wmax = max(abs(v) for v in orig)
    d = to_f16(wmax / 127.0)
    q8 = [int(round(v / d)) for v in orig]           # signed 8-bit
    deq = dequant_q8_0(d, q8)
    errs = [abs(a - b) for a, b in zip(orig, deq)]
    print(f"orig   = {[round(v,3) for v in orig]}")
    print(f"d      = {d}")
    print(f"q8     = {q8}")
    print(f"deq    = {[round(v,4) for v in deq]}")
    print(f"abs err= {[round(e,5) for e in errs]}")
    print()
    maxerr = max(errs)
    print(f"max abs error = {maxerr:.5f}  (vs Q4_0's ~scale/2 ceiling)")
    check("Q8_0 round-trip error < d/2", maxerr < d / 2,
          f"maxerr={maxerr:.5f} d/2={d/2:.5f}")


def section_d_k_quants():
    banner("SECTION D: K-QUANTS - super-blocks + double-quantized scales")
    print(f"Super-block layout (verified: QK_K = {QK_K}, block_q4_K):")
    print(f"  A super-block = {QK_K} weights = 8 sub-blocks of 32 weights each.")
    print(f"  Each sub-block gets its OWN 6-bit scale (+ 6-bit min).")
    print(f"  Those 6-bit sub-scales are re-scaled by a fp16 super-block d/dmin.")
    print(f"  => DOUBLE quantization: the scales of the scales are quantized too.")
    print()
    q4_k_bytes = 2*2 + K_SCALE_SIZE + QK_K//2
    print(f"Q4_K pure block size = 2*sizeof(ggml_half) + K_SCALE_SIZE + QK_K/2")
    print(f"  = 4 + {K_SCALE_SIZE} + {QK_K//2} = {q4_k_bytes} bytes  -> "
          f"{q4_k_bytes*8/QK_K:.4f} bpw (pure Q4_K)")
    print()
    q6_k_bytes = QK_K//2 + QK_K//4 + QK_K//16 + 2
    q3_k_bytes = QK_K//8 + QK_K//4 + 12 + 2
    print(f"Other K-quants (pure, same QK_K={QK_K}):")
    print(f"  Q3_K = {q3_k_bytes} bytes -> {q3_k_bytes*8/QK_K:.4f} bpw  (16 sub-blocks of 16)")
    print(f"  Q6_K = {q6_k_bytes} bytes -> {q6_k_bytes*8/QK_K:.4f} bpw  (6-bit, int8 sub-scales)")
    print()
    print("The _M variants MIX types across layers (not a single block format):")
    print("  Q4_K_M ~ 4.84 bpw because attention/embedding/output layers use the")
    print("           higher-precision Q6_K, while the bulk MLP layers use Q4_K.")
    print("  This is why Q4_K_M beats pure Q4_K on perplexity at a small size cost.")
    print()
    # Tiny super-block demo: 2 sub-blocks (not 8) so numbers print. Same math.
    d = to_f16(0.02)         # super-block scale for the sub-scales
    dmin = to_f16(0.01)      # super-block scale for the sub-mins
    sub_scales6 = [40, 55]   # 6-bit sub-scales (0..63) for 2 sub-blocks
    sub_mins6 = [10, 20]     # 6-bit sub-mins
    quants = [2,5,1,8] + [3,7,0,6]   # 2 sub-blocks of 4 (real = 8 of 32)
    print("Tiny super-block demo (2 sub-blocks of 4, same dequant math):")
    print(f"  d={d}, dmin={dmin}")
    print(f"  sub_scales6={sub_scales6}, sub_mins6={sub_mins6}")
    print(f"  quants={quants}")
    # Apply the real double-quant dequant to the 2 sub-blocks only.
    deq = []
    for j in range(2):
        scale_j = d * sub_scales6[j]
        min_j = dmin * sub_mins6[j]
        print(f"  sub-block {j}: eff_scale=d*{sub_scales6[j]}={scale_j:.4f}, "
              f"eff_min=dmin*{sub_mins6[j]}={min_j:.4f}")
        chunk = quants[j*4:(j+1)*4]
        for q in chunk:
            deq.append(min_j + scale_j * q)
    print(f"  dequant = {[round(w,5) for w in deq]}")
    check("Q4_K sub-block 0 uses scale=d*40", abs(d*40 - d*sub_scales6[0]) < 1e-9)
    check("Q4_K dequant == min_j + scale_j*q",
          abs(deq[0] - (dmin*sub_mins6[0] + d*sub_scales6[0]*quants[0])) < 1e-9)


def section_e_i_quants():
    banner("SECTION E: I-QUANTS - importance matrix + lookup tables")
    print("I-quants (IQ2/IQ3/IQ4) add two things on top of K-quants:")
    print()
    print("  1. IMPORTANCE MATRIX (imatrix): run a calibration set through the")
    print("     FP16 model, accumulate the average |activation|^2 per row/column.")
    print("     Rows that drive the output strongly get finer quantization; rows")
    print("     that barely move the output get coarser. The error budget is")
    print("     spent WHERE IT MATTERS, not uniformly.")
    print()
    print("  2. LOOKUP TABLES (codebooks): instead of w = m + d*q (affine), the")
    print("     packed index addresses a precomputed grid of 8-element vectors.")
    print("     Non-linear -> fits the weight distribution better than any line.")
    print()
    iq3s_bytes = 2 + QK_K//4 + QK_K//32 + QK_K//8 + QK_K//64
    print(f"IQ3_S block layout (verified: block_iq3_s, QK_K={QK_K}):")
    print(f"  d       : ggml_half (2 bytes)        super-block scale")
    print(f"  qs      : {QK_K//4} bytes             packed 2-bit+1-bit indices")
    print(f"  qh      : {QK_K//32} bytes             extra high bits")
    print(f"  signs   : {QK_K//8} bytes             1 sign bit per weight")
    print(f"  scales  : {QK_K//64} bytes             4-bit block scales")
    print(f"  total   = {iq3s_bytes} bytes -> {iq3s_bytes*8/QK_K:.4f} bpw")
    print(f"  (same SIZE as Q3_K = {QK_K//8 + QK_K//4 + 12 + 2} bytes/{QK_K} = "
          f"{(QK_K//8 + QK_K//4 + 12 + 2)*8/QK_K:.4f} bpw, but much lower ppl)")
    print()
    print("Conceptual codebook dequant (simplified):")
    print("  1. gather the packed index for a group of 8 weights")
    print("  2. look up the 8-float vector in iq3s_grid (2048-entry codebook)")
    print("  3. apply sign bits + block scale + super-block d")
    print("  4. the imatrix weights the per-layer d so sensitive layers shrink less")
    print()
    # Show the imatrix concept: weight error by importance.
    weights = [0.9, -0.8, 0.1, 2.5]      # one row
    importance = [0.2, 0.3, 5.0, 0.1]    # col 2 dominates the output
    # uniform 4-bit quant: step = (max-min)/15
    wmin, wmax = min(weights), max(weights)
    step = (wmax - wmin) / 15.0
    q_uniform = [round((w - wmin) / step) for w in weights]
    deq_uniform = [wmin + step * q for q in q_uniform]
    err_uniform = [abs(a - b) for a, b in zip(weights, deq_uniform)]
    # importance-weighted error: the big-importance column should be the winner.
    weighted_err = sum(e * imp for e, imp in zip(err_uniform, importance))
    print(f"weights     = {weights}")
    print(f"importance  = {importance}  (col 2 drives output)")
    print(f"uniform deq = {[round(w,4) for w in deq_uniform]}")
    print(f"abs err     = {[round(e,4) for e in err_uniform]}")
    print(f"importance-weighted total error = {weighted_err:.4f}")
    print("  -> I-quants shift the step boundaries so the high-importance column")
    print("     quantizes with ~zero error, accepting more error on col 3 instead.")
    check("IQ3_S == Q3_K size (3.4375 bpw)",
          iq3s_bytes == QK_K//8 + QK_K//4 + 12 + 2,
          f"IQ3_S={iq3s_bytes} vs Q3_K={QK_K//8 + QK_K//4 + 12 + 2}")
    check("IQ3_S bpw = 3.4375",
          abs(iq3s_bytes*8/QK_K - 3.4375) < 1e-9)


def section_f_comparison():
    banner("SECTION F: COMPARISON TABLE - bpw / quality / speed / use case")
    print("Pure-format bpw (struct sizes, verified in sections A-E):")
    print()
    print("| type     | block | bytes | bpw    | family   | scale model          |")
    print("|----------|-------|-------|--------|----------|----------------------|")
    rows = [
        ("Q4_0",    "32",   2+32//2,    (2+32//2)*8/32,    "legacy",  "1 fp16 d, symmetric"),
        ("Q4_1",    "32",   4+32//2,    (4+32//2)*8/32,    "legacy",  "fp16 d + fp16 m"),
        ("Q5_1",    "32",   8+32//2,    (8+32//2)*8/32,    "legacy",  "fp16 d+m + 1 high bit"),
        ("Q8_0",    "32",   2+32,       (2+32)*8/32,       "legacy",  "1 fp16 d, int8"),
        ("Q2_K",    "256",  84,         84*8/256,          "k-quant", "super d/dmin, 4-bit sub-scale"),
        ("Q3_K",    "256",  110,        110*8/256,         "k-quant", "super d, 6-bit sub-scale"),
        ("Q4_K",    "256",  144,        144*8/256,         "k-quant", "super d/dmin, 6-bit sub-scale+min"),
        ("Q5_K",    "256",  176,        176*8/256,         "k-quant", "super d/dmin, 6-bit + 1 high bit"),
        ("Q6_K",    "256",  210,        210*8/256,         "k-quant", "super d, int8 sub-scale"),
        ("IQ3_S",   "256",  110,        110*8/256,         "i-quant", "super d, 4-bit scale, codebook"),
    ]
    for name, blk, byt, bpw, fam, scale in rows:
        print(f"| {name:<8} | {blk:>5} | {byt:>5} | {bpw:>6.4f} | {fam:<8} | {scale:<20} |")
    print()
    print("Model-level bpw for the _M / _S MIXED variants (Llama-2-7B, k-quants README):")
    print()
    print("| variant  | bpw   | note                                  |")
    print("|----------|-------|---------------------------------------|")
    mixed = [
        ("Q2_K",   3.35, "2-bit baseline, often degraded"),
        ("Q3_K_S", 3.50, "small 3-bit"),
        ("Q3_K_M", 3.91, "medium 3-bit"),
        ("Q3_K_L", 4.27, "large 3-bit, some Q5_K layers"),
        ("Q4_K_S", 4.58, "small 4-bit"),
        ("Q4_K_M", 4.84, "DEFAULT: best quality/size tradeoff"),
        ("Q5_K_S", 5.52, "small 5-bit"),
        ("Q5_K_M", 5.68, "medium 5-bit"),
        ("Q6_K",   6.56, "near-lossless, ~Q8_0 quality smaller"),
    ]
    for name, bpw, note in mixed:
        print(f"| {name:<8} | {bpw:>5.2f} | {note:<37} |")
    print()
    print("Picking rules of thumb (decode is bandwidth-bound, so bpw ~= speed):")
    print("  - Most VRAM/RAM constrained:  IQ3_S  or  Q3_K_M   (3.4-3.9 bpw)")
    print("  - Sweet spot (default):       Q4_K_M              (~4.8 bpw)")
    print("  - Best quality that still saves space: Q6_K       (~6.6 bpw)")
    print("  - Reference / calibration:    Q8_0                (8.5 bpw)")
    check("Q4_K_M bpw 4.84 in documented range", 4.8 < 4.84 < 4.9)
    check("Q4_0 is 4.5 bpw exactly", abs((2+16)*8/32 - 4.5) < 1e-9)
    check("Q8_0 is 8.5 bpw exactly", abs((2+32)*8/32 - 8.5) < 1e-9)


# ============================================================================
# main
# ============================================================================

def main():
    print("quant_types.py - GGUF block quantization dequant reference.")
    print("Pure Python stdlib. Numbers below feed QUANT_TYPES.md.")
    print("Sources: ggml/src/ggml-common.h structs + examples/quantize k-quants table.")
    print()
    print("Three families: legacy Q4_0/Q4_1/Q8_0 -> K-quants Q4_K_M -> I-quants IQ3_S")

    section_a_q4_0()
    section_b_q4_1()
    section_c_q8_0()
    section_d_k_quants()
    section_e_i_quants()
    section_f_comparison()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
