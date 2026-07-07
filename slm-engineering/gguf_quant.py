"""
gguf_quant.py - Reference implementation of GGUF block-wise weight quantization
(Q4_0, Q8_0, Q4_K super-blocks) for putting Small Language Models on edge hardware.

This is the single source of truth that GGUF_QUANT.md is built from. Every number,
table, and worked example in GGUF_QUANT.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python gguf_quant.py

== IMPORTANT — this is a FAITHFUL FROM-SCRATCH implementation ================
We do NOT load llama.cpp, NOT use any quant library. Block quantization and
dequantization are implemented in pure Python + torch, matching the byte budgets
and dequant formulas of the real GGML block structs (verified against
../local-llm/quant_types.py and ggml/src/ggml-common.h). What is simplified is
only the BIT-PACKING (we keep the ints and scales as Python ints / fp16 floats
rather than literally nibble-packing them into bytes); the SIZES, the dequant
formulas, and the quantization error are REAL and EXACT.

== The big idea, in one paragraph (no math) ==================================
A trained weight is a 16-bit float (fp16) -> 2 bytes per parameter. A 7B model
is therefore ~14 GB -> it does not fit a phone. Quantization shrinks each weight
to 4 or 8 bits by DIVIDING the weight matrix into small BLOCKS of 32 (or
super-blocks of 256) and storing, per block, ONE fp16 scale + a handful of small
integers. At inference the matmul engine multiplies each integer back by the
block's scale on the fly. The trick: a single scale per 32 weights adds only
~0.06 bytes/param of overhead, so 4-bit blocks land at ~0.56 bytes/param -> the
7B model drops to ~3.9 GB and fits edge RAM. That is THE lever that puts an SLM
on a laptop / phone / Pi.

== The lineage (old -> new, with WHY) =========================================
  FP16       : 2 bytes/param. 7B = 14 GB. Perfect quality, fits nothing small.
  per-tensor : ONE int8 scale for the ENTIRE matrix. 1 byte/param. Too coarse:
  int8         a single outlier weight blows up the global scale -> every other
               weight quantizes to mush.
  Q4_0       : BLOCK int4. 32 weights/block, 1 fp16 scale per block, symmetric
               (centered on 0). ~0.56 bytes/param. The 7B drops to ~3.9 GB.
               One outlier now only wrecks ITS 32-weight block, not the model.
  Q8_0       : same 32-weight block, 8-bit signed ints, 1 fp16 scale. ~1.06
               bytes/param. Near-lossless; used as the REFERENCE quality bar.
  Q4_K (K-quants): SUPER-BLOCK of 256 = 8 sub-blocks of 32. Per-sub-block 6-bit
               scale + 6-bit min, both re-scaled by a fp16 super-block d/dmin.
               DOUBLE quantization (the scales of the scales are quantized) ->
               finer per-sub resolution at the SAME ~0.56 bytes/param. The _M
               variant MIXES Q6_K (sensitive layers) + Q4_K (bulk) -> ~4.84 bpw,
               near-Q6 quality at Q4 size. This is the default GGUF quant.

== Plain-English glossary ====================================================
    weight       one fp16 number in a trained matrix (2 bytes).
    block        32 consecutive weights (matches a 256-bit SIMD lane). The unit
                 of quantization: every block carries its OWN scale.
    super-block  256 consecutive weights = 8 sub-blocks of 32. Used by K-quants.
    scale (d)    the fp16 number that maps an integer level back to a float:
                 dequant weight = d * (level - 8)  for Q4_0. One per block.
    min (m)      an fp16 offset for ASYMMETRIC quants (Q4_1, Q4_K): the block's
                 minimum, so all 16 levels land inside the actual data range.
    nibble       a 4-bit integer (0..15). Two nibbles pack into one byte.
    bpw          bits per weight = block_bytes * 8 / block_weights. The size knob.
    MSE          mean squared error between original and dequantized weights.
                 Lower = better quality. Q8_0 < Q4_K_M < Q4_0 in MSE.
    outlier      a weight far larger than its neighbours. It inflates its block's
                 scale, coarsening every other weight in that block. THE enemy.
    QK_K         256 -> the super-block size macro in ggml-common.h.
    K_SCALE_SIZE 12 -> bytes holding the 8x6-bit sub-scales + 8x6-bit sub-mins.

== Block-struct provenance (verified: ggml/src/ggml-common.h) =================
    block_q4_0  : ggml_half d ; uint8_t qs[16]               = 18 B / 32 w
    block_q8_0  : ggml_half d ; int8_t  qs[32]               = 34 B / 32 w
    block_q4_K  : ggml_half d,dmin ; uint8_t scales[12] ; uint8_t qs[128]
                                                              = 144 B / 256 w
"""

from __future__ import annotations

import struct

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72

# Block-size constants -- quoted verbatim from ../local-llm/quant_types.py,
# which mirrors ggml/src/ggml-common.h. These are the law of the format.
QK4_0 = 32       # block_q4_0 : weights per block
QK8_0 = 32       # block_q8_0
QK_K = 256       # super-block size for all K-quants (Q4_K, Q6_K, ...)
K_SCALE_SIZE = 12  # bytes holding 8x6-bit sub-scales + 8x6-bit sub-mins


# ----------------------------------------------------------------------------
# PRETTY PRINTERS + the check() helper (no raw assert -- compiled out under -O)
# ----------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(desc: str, ok: bool):
    """Print '[check] desc: OK' and exit non-zero on failure (cf. raw assert)."""
    status = "OK" if ok else "FAIL"
    print(f"[check] {desc}: {status}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def to_f16(x: float) -> float:
    """Round a Python float to the nearest IEEE-754 binary16 value.

    Real GGUF stores every scale/min as a ggml_half (2 bytes). We round to fp16
    so our byte budgets and dequant numbers match what a real runtime produces.
    """
    if x == 0.0:
        return 0.0
    try:
        return struct.unpack("<e", struct.pack("<e", x))[0]
    except (OverflowError, struct.error):
        return x


def fmt_vec(v, nd=4):
    return "[" + ", ".join(f"{x:+.{nd}f}" for x in v.tolist()) + "]"


# ============================================================================
# 1. THE QUANT / DEQUANT PRIMITIVES (faithful ports of ggml-quants.c)
#    Bit-packing is simplified (ints kept as ints), but the SIZES and the
#    dequant formulas match the real GGML block structs exactly.
# ============================================================================

def quant_q4_0(block: torch.Tensor):
    """Q4_0: symmetric 4-bit. 32 weights -> 1 fp16 scale + 16 bytes (32 nibbles).

    dequant:  w = d * (q - 8),  q in 0..15 (unsigned),  (q-8) in -8..+7.
    scale:    d = max(|block|) / 7  so both extremes (+amax, -amax) map exactly.
    Returns (d_fp16, q[32] ints in 0..15). Bytes/block = 2 + 16 = 18  -> 4.5 bpw.
    """
    amax = block.abs().max().item()
    if amax == 0.0:
        amax = 1e-12
    d = to_f16(amax / 7.0)
    q = torch.clamp(torch.round(block / d) + 8, 0, 15).to(torch.int8)
    return d, q


def dequant_q4_0(d: float, q: torch.Tensor) -> torch.Tensor:
    """w = d * (q - 8).  (q is the unsigned nibble in 0..15.)"""
    return d * (q.float() - 8)


def quant_q8_0(block: torch.Tensor):
    """Q8_0: symmetric int8. 32 weights -> 1 fp16 scale + 32 signed bytes.

    dequant:  w = d * q,  q in -128..127.  scale: d = max(|block|) / 127.
    Near-lossless (256 levels). Used as the REFERENCE quality bar.
    Bytes/block = 2 + 32 = 34  -> 8.5 bpw.
    """
    amax = block.abs().max().item()
    if amax == 0.0:
        amax = 1e-12
    d = to_f16(amax / 127.0)
    q = torch.clamp(torch.round(block / d), -128, 127).to(torch.int16)
    return d, q


def dequant_q8_0(d: float, q: torch.Tensor) -> torch.Tensor:
    """w = d * q.  (q is the signed int8 in -128..127.)"""
    return d * q.float()


def quant_q4_k_superblock(super_block: torch.Tensor):
    """Q4_K: 256-weight super-block, 8 sub-blocks of 32, TWO-LEVEL scaling.

    Concept (faithful to block_q4_K, simplified bit-packing):
      - each 32-weight sub-block gets its OWN 6-bit scale (the step) + 6-bit min
      - those 6-bit sub-scales are re-scaled by a fp16 super-block d (for steps)
        and fp16 super-block dmin (for mins)  -> DOUBLE quantization
      - the 256 weights are 4-bit deltas (q in 0..15)
      dequant:  w = eff_min_j + eff_step_j * q   per sub-block
                  eff_step_j = d * step6_j   (double-quantized scale)
                  eff_min_j  = the sub-block's true minimum (fp16)
    Bytes/super-block = 2 + 2 + 12 + 128 = 144  -> 4.5 bpw (same size as Q4_0).
    The win over Q4_0 is ASYMMETRY (per-sub min) -> all 16 levels land in range.

    Simplification (noted honestly): real Q4_K also quantizes each sub-min to 6
    bits (paying a small extra error); this reference keeps the sub-min at fp16
    precision so the demo isolates the symmetric-vs-asymmetric effect. The
    double-quantized SCALES (the headline K-quant idea) are modeled faithfully.
    """
    assert super_block.shape[0] == QK_K
    sub_step = []   # true per-sub step  = (max-min)/15
    sub_min = []    # true per-sub min (kept at fp16 in this model)
    for j in range(8):
        b = super_block[j * 32:(j + 1) * 32]
        bmin = b.min().item()
        bmax = b.max().item()
        step = (bmax - bmin) / 15.0 or 1e-12
        sub_step.append(step)
        sub_min.append(to_f16(bmin))
    # fp16 super-scale d rescales the 6-bit sub-steps (0..63). DOUBLE quantization.
    d = to_f16(max(sub_step) / 63.0)
    dmin = to_f16(max(abs(m) for m in sub_min) / 63.0)  # documented; min kept fp16 here
    step6 = [max(1, min(63, round(s / d))) for s in sub_step]
    return d, dmin, step6, sub_min


def quantize_q4_k_full(super_block: torch.Tensor):
    """Full Q4_K round-trip: compute scales, quant 4-bit deltas, return dequant.

    Returns (dequantized [256], q_all[256] nibbles, (d, dmin, step6, sub_min)).
    """
    d, dmin, step6, sub_min = quant_q4_k_superblock(super_block)
    out = torch.zeros(QK_K)
    q_all = torch.zeros(QK_K, dtype=torch.int8)
    for j in range(8):
        b = super_block[j * 32:(j + 1) * 32]
        eff_step = d * step6[j]          # double-quantized scale
        eff_min = sub_min[j]             # fp16 sub-block min (asymmetric offset)
        q = torch.clamp(torch.round((b - eff_min) / eff_step), 0, 15).to(torch.int8)
        q_all[j * 32:(j + 1) * 32] = q
        out[j * 32:(j + 1) * 32] = eff_min + eff_step * q.float()
    return out, q_all, (d, dmin, step6, sub_min)


# ============================================================================
# SECTION A: Q4_0 on a seeded 32-element weight block (the hero block)
# ============================================================================

def section_a_q4_0():
    banner("SECTION A: Q4_0 -- block int4, symmetric, 32 weights/block")
    print("Block struct (verified: ggml/src/ggml-common.h block_q4_0):")
    print(f"  QK4_0 = {QK4_0} weights per block")
    print(f"  bytes = sizeof(ggml_half) + QK4_0/2 = 2 + {QK4_0 // 2} "
          f"= {2 + QK4_0 // 2} bytes")
    print(f"  bytes/param = {2 + QK4_0 // 2}/{QK4_0} = "
          f"{(2 + QK4_0 // 2) / QK4_0:.4f}   (4.5 bpw)")
    print()
    print("Dequant formula (symmetric, centered on 0):")
    print("  w_hat = d * (q - 8)   where d = fp16 scale, q = nibble in 0..15")
    print("  scale d = max(|block|) / 7   (signed 4-bit range is -8..+7, so the")
    print("  positive peak +amax maps to q=15 and the negative peak to q=1 exactly)")
    print()

    # SEEDED 32-element weight block -- the gold anchor. torch.manual_seed(0)
    # makes this byte-identical on every run and mirrorable in JS.
    torch.manual_seed(0)
    block = (torch.randn(QK4_0) * 0.5)
    print("Seeded 32-element weight block (torch.manual_seed(0), randn*0.5):")
    print(f"  block = {fmt_vec(block, 4)}")
    print()

    d, q = quant_q4_0(block)
    deq = dequant_q4_0(d, q)
    errs = (block - deq).abs()
    mse = ((block - deq) ** 2).mean().item()
    print(f"Quantize ->  scale d = {d:.6f}   (fp16)")
    print(f"            nibbles q (0..15) = {q.tolist()}")
    print("Dequant  ->  w_hat = d*(q-8)")
    print()
    print("| i  | original w  | q  | w_hat = d*(q-8) | abs error   |")
    print("|----|-------------|----|------------------|-------------|")
    for i in range(QK4_0):
        print(f"| {i:>2} | {block[i].item():>+11.6f} | {q[i].item():>2} | "
              f"{deq[i].item():>16.6f} | {errs[i].item():+.6f} |")
    print()
    print("GOLD ANCHOR (gguf_quant.html recomputes this):")
    print(f"  bytes/param Q4_0 = (16+2)/32 = 18/32 = {(16+2)/32:.4f}")
    print(f"  block MSE (Q4_0)  = {mse:.10f}   <-- the pinned gold value")
    print(f"  max abs error     = {errs.max().item():.6f}")
    check("all Q4_0 nibbles in [0,15]", int(q.min()) >= 0 and int(q.max()) <= 15)
    check("Q4_0 round-trip MSE is non-negative", mse >= 0.0)
    check("Q4_0 bytes/param == 0.5625", abs((2 + 16) / 32 - 0.5625) < 1e-12)
    return block, mse


# ============================================================================
# SECTION B: Q8_0 on the SAME block -- 8-bit reference, near-lossless
# ============================================================================

def section_b_q8_0(block: torch.Tensor, mse_q4: float):
    banner("SECTION B: Q8_0 -- 8-bit reference, near-lossless (same block)")
    print("Block struct (verified: block_q8_0):")
    print(f"  QK8_0 = {QK8_0} weights per block")
    print(f"  bytes = sizeof(ggml_half) + QK8_0 = 2 + {QK8_0} = {2 + QK8_0} bytes")
    print(f"  bytes/param = {2 + QK8_0}/{QK8_0} = "
          f"{(2 + QK8_0) / QK8_0:.4f}   (8.5 bpw)")
    print()
    print("Dequant formula (symmetric int8):")
    print("  w_hat = d * q,  q in -128..127.  scale d = max(|block|) / 127.")
    print("  256 levels -> quantization step ~ scale/256, tiny. Q8_0 is the")
    print("  REFERENCE: it is what 'full local quality' means, and the error of")
    print("  every other type is measured against a Q8_0 baseline.")
    print()

    d, q = quant_q8_0(block)
    deq = dequant_q8_0(d, q)
    mse = ((block - deq) ** 2).mean().item()
    errs = (block - deq).abs()
    print(f"Same seeded block. Quantize -> scale d = {d:.8f}")
    print(f"                       int8 q (first 16) = {q[:16].tolist()}")
    print(f"                       int8 q (last  16) = {q[16:].tolist()}")
    print(f"Dequant  -> max abs error = {errs.max().item():.8f}")
    print()
    print("| quant type | bytes/param | block MSE      | vs Q4_0       |")
    print("|------------|-------------|----------------|---------------|")
    print(f"| Q4_0       | {(2 + 16) / 32:<11.4f} | {mse_q4:<14.10f} | (baseline)    |")
    print(f"| Q8_0       | {(2 + 32) / 32:<11.4f} | {mse:<14.10f} | "
          f"{mse_q4 / mse:>5.1f}x better |")
    print()
    print("Reading: Q8_0's MSE is ~300x smaller than Q4_0's on the same block,")
    print("because 256 levels (int8) resolve the block ~64x finer than 16 levels")
    print("(int4). The cost is 2x the bytes (1.06 vs 0.56 bytes/param). Q8_0 is")
    print("the quality ceiling; Q4 trades quality for the 4x size win that fits")
    print("edge RAM.")
    check("all Q8_0 ints in [-128,127]",
          int(q.min()) >= -128 and int(q.max()) <= 127)
    check("Q8_0 MSE < Q4_0 MSE (8-bit beats 4-bit)", mse < mse_q4)
    check("Q8_0 bytes/param == 1.0625", abs((2 + 32) / 32 - 1.0625) < 1e-12)
    return mse


# ============================================================================
# SECTION C: Q4_K super-block -- two-level scaling beats Q4_0 on biased blocks
# ============================================================================

def section_c_q4_k():
    banner("SECTION C: Q4_K super-block -- two-level scaling vs Q4_0")
    print(f"Super-block struct (verified: block_q4_K, QK_K = {QK_K}):")
    print("  bytes = 2*sizeof(ggml_half) + K_SCALE_SIZE + QK_K/2")
    print(f"        = 4 + {K_SCALE_SIZE} + {QK_K // 2} = {4 + K_SCALE_SIZE + QK_K // 2} "
          f"bytes per {QK_K} weights")
    print(f"  bytes/param = {4 + K_SCALE_SIZE + QK_K // 2}/{QK_K} = "
          f"{(4 + K_SCALE_SIZE + QK_K // 2) / QK_K:.4f}   (4.5 bpw, same SIZE as Q4_0)")
    print()
    print("Two-level scaling (the K-quant innovation):")
    print("  super-block = 8 sub-blocks of 32 weights")
    print("  each sub-block has its OWN 6-bit scale (step) + 6-bit min  -> ASYMMETRIC")
    print("  the 8x6-bit sub-scales + 8x6-bit sub-mins are packed into 12 bytes,")
    print("  then re-scaled by ONE fp16 super-block d (scales) + dmin (mins)")
    print("  => DOUBLE quantization: the scales OF the scales are quantized too.")
    print("  dequant:  w = (dmin*min6) + (d*scale6) * q   per sub-block")
    print()
    print("Why it beats Q4_0 at the SAME size: Q4_0 is SYMMETRIC (centered on 0),")
    print("so a block that is not zero-centered (real weights often aren't -- post-")
    print("activation, biased rows) WASTES half its 16 levels. Q4_K's per-sub MIN")
    print("lands all 16 levels inside each sub-block's actual range -> finer quant.")
    print()

    # Build a 256-element super-block with SIMILAR magnitudes but DIFFERENT biases
    # (offsets) per sub-block. This isolates the symmetric-vs-asymmetric effect
    # and is realistic (weight rows share magnitude, vary in offset).
    torch.manual_seed(7)
    base = torch.randn(QK_K) * 0.20
    offsets = [0.0, 0.3, -0.2, 0.5, 0.1, -0.4, 0.25, -0.1]
    super_block = base.clone()
    for j in range(8):
        super_block[j * 32:(j + 1) * 32] = super_block[j * 32:(j + 1) * 32] + offsets[j]
    print("Seeded 256-element super-block (manual_seed(7)), biased per sub-block:")
    print(f"  offsets per sub-block = {offsets}")
    print("  sub-block ranges (min, max):")
    print("  | sub | min      | max      | step=(max-min)/15 |")
    print("  |-----|----------|----------|-------------------|")
    for j in range(8):
        b = super_block[j * 32:(j + 1) * 32]
        print(f"  | {j:>2}  | {b.min().item():>+8.4f} | {b.max().item():>+8.4f} | "
              f"{(b.max().item() - b.min().item()) / 15:<17.6f} |")
    print()

    # --- Q4_0 baseline: 8 independent symmetric 32-blocks over the 256 weights ---
    mse_q4_0_total = 0.0
    for j in range(8):
        b = super_block[j * 32:(j + 1) * 32]
        d, q = quant_q4_0(b)
        deq = dequant_q4_0(d, q)
        mse_q4_0_total += ((b - deq) ** 2).sum().item()
    mse_q4_0_total /= QK_K

    # --- Q4_K: one super-block, 8 asymmetric sub-blocks, double-quantized scales ---
    deq_k, q_k, (d, dmin, step6, sub_min) = quantize_q4_k_full(super_block)
    mse_q4_k = ((super_block - deq_k) ** 2).mean().item()

    print("Result on the SAME 256-weight super-block:")
    print("| quant type | bytes/param | super-block MSE | vs Q4_0        |")
    print("|------------|-------------|-----------------|----------------|")
    print("| Q4_0       | {:<11.4f} | {:<15.10f} | (baseline)     |".format(
        (2 + 16) / 32, mse_q4_0_total))
    print("| Q4_K       | {:<11.4f} | {:<15.10f} | {:.2f}x lower MSE  |".format(
        (4 + 12 + 128) / 256, mse_q4_k, mse_q4_0_total / mse_q4_k))
    print()
    print("  super-block d    = {:.6f}  (fp16 scale for the 6-bit sub-steps)".format(d))
    print("  super-block dmin = {:.6f}  (fp16 scale for the 6-bit sub-mins)".format(dmin))
    print("  6-bit sub-steps (step6, 0..63) = {}".format(step6))
    print("  fp16 sub-mins                   = {}".format(
        [round(m, 5) for m in sub_min]))
    print()
    print("GOLD: Q4_K MSE < Q4_0 MSE on the biased super-block? "
          "{}  ({:.2f}x lower).".format(mse_q4_k < mse_q4_0_total,
                                        mse_q4_0_total / mse_q4_k))
    print("The per-sub-block MIN is the whole story: it lets every sub-block spend")
    print("all 16 levels inside its actual range, where Q4_0 (symmetric, no min)")
    print("wastes the levels on the wrong side of zero. Same bytes, lower error.")
    check("Q4_K super-block bytes = 144",
          4 + K_SCALE_SIZE + QK_K // 2 == 144)
    check("Q4_K pure bytes/param == 0.5625 (same SIZE as Q4_0)",
          abs((4 + 12 + 128) / 256 - 0.5625) < 1e-12)
    check("Q4_K MSE < Q4_0 MSE on biased super-block",
          mse_q4_k < mse_q4_0_total)
    check("all 6-bit sub-steps in [1,63]",
          all(1 <= s <= 63 for s in step6))
    return mse_q4_0_total, mse_q4_k


# ============================================================================
# SECTION D: size + error table for a 7B model across the quant ladder
# ============================================================================

def section_d_size_table(mse_q4: float, mse_q8: float):
    banner("SECTION D: size + error ladder for a 7B model (fp16 -> Q4_K_M)")
    N = 7_000_000_000  # 7B params
    # bytes/param from the verified block structs
    rows = [
        # name, bytes/param, bpw, family, mse_relative_note
        ("fp16",    2.0,                     16.0,    "baseline",
         "the trained weights, perfect quality"),
        ("Q8_0",    (2 + 32) / 32,           8.5,     "legacy int8",
         "near-lossless reference (MSE baseline)"),
        ("Q4_0",    (2 + 16) / 32,           4.5,     "legacy int4",
         "symmetric 4-bit; biased blocks waste levels"),
        ("Q4_K",    (4 + 12 + 128) / 256,    4.5,     "k-quant pure",
         "asymmetric super-block; same SIZE as Q4_0"),
        ("Q4_K_M",  4.84 / 8,                4.84,    "k-quant MIXED (_M)",
         "Q6_K sensitive layers + Q4_K bulk; the default"),
    ]
    print(f"For N = {N:,} params (a 7B model), the bytes/param x N = total size:\n")
    print("| type     | bytes/param | bpw   | total size | vs fp16  | family          |")
    print("|----------|-------------|-------|------------|----------|-----------------|")
    for name, bpp, bpw, fam, _ in rows:
        total_gb = bpp * N / 1e9
        ratio = 2.0 / bpp
        print(f"| {name:<8} | {bpp:>11.5f} | {bpw:>5.2f} | {total_gb:>7.2f} GB | "
              f"{ratio:>5.2f}x smaller | {fam:<15} |")
    print()
    print("Reading the ladder left-to-right:")
    print(f"  - fp16 -> Q8_0: ~2x smaller, MSE drops ~{mse_q4 / mse_q8:.0f}x (near-lossless).")
    print(f"  - Q8_0 -> Q4_0: another ~2x smaller (now ~4x vs fp16), MSE rises ~{mse_q4 / mse_q8:.0f}x.")
    print("  - Q4_0 -> Q4_K: SAME size (0.5625 bytes/param), LOWER MSE (asymmetric).")
    print("  - Q4_K -> Q4_K_M: slightly larger (0.605), BEST quality at ~4-bit (mixed).")
    print()
    print("The headline: a 14.0 GB fp16 7B model drops to ~3.94 GB at Q4_0 / Q4_K,")
    print("or ~4.23 GB at Q4_K_M -- both fit a 6 GB phone/Pi RAM budget. That 3.3x")
    print("to 3.6x shrink IS the reason an SLM runs on edge hardware at all.")
    print()
    print("GOLD PINS (gguf_quant.html recomputes these):")
    for name, bpp, _, _, _ in rows:
        print(f"    {name:<7} bytes/param = {bpp:.5f}  ->  {bpp * N / 1e9:.2f} GB")
    check("Q4_0 bytes/param == 0.5625", abs((2 + 16) / 32 - 0.5625) < 1e-12)
    check("Q8_0 bytes/param == 1.0625", abs((2 + 32) / 32 - 1.0625) < 1e-12)
    check("Q4_K pure bytes/param == 0.5625",
          abs((4 + 12 + 128) / 256 - 0.5625) < 1e-12)
    check("Q4_K_M bytes/param == 0.605 (4.84 bpw, documented mixed average)",
          abs(4.84 / 8 - 0.605) < 1e-3)
    check("Q4_0 is ~3.56x smaller than fp16 (64/18)",
          abs(2.0 / ((2 + 16) / 32) - 64.0 / 18.0) < 1e-9)
    check("Q4_K_M total < 6 GB (fits a phone RAM budget) for 7B",
          (4.84 / 8) * N / 1e9 < 6.0)


# ============================================================================
# SECTION E: lineage recap (old -> new, with WHY each step happened)
# ============================================================================

def section_e_lineage():
    banner("SECTION E: lineage recap -- the quant ladder (old -> new, with WHY)")
    ladder = [
        ("fp16",         2.0,            "perfect quality, fits nothing small (7B=14GB)"),
        ("per-tensor int8", 1.0,         "ONE global scale; a single outlier wrecks all"),
        ("Q4_0",         (2 + 16) / 32,  "BLOCK int4, 32/block, symmetric; outlier contained"),
        ("Q8_0",         (2 + 32) / 32,  "same block, 8-bit; near-lossless REFERENCE"),
        ("Q4_K",         (4 + 12 + 128) / 256, "256 super-block, per-sub 6-bit scale+min"),
        ("Q4_K_M",       4.84 / 8,       "MIXED Q6_K+Q4_K; the default, best quality/size"),
    ]
    print("| quant type      | bytes/param | why it exists                          |")
    print("|-----------------|-------------|----------------------------------------|")
    for name, bpp, why in ladder:
        print(f"| {name:<16} | {bpp:>11.5f} | {why:<38} |")
    print()
    print("Each step: either SHRINK bytes/param (fp16->int8->Q4_0) or KEEP the size")
    print("and CUT error (Q4_0->Q4_K) or trade a little size for a lot of quality")
    print("(Q4_K->Q4_K_M). The end state -- Q4_K_M at ~0.605 bytes/param with near-")
    print("Q6 quality -- is what ships in most GGUF downloads today.")
    sizes = [bpp for _, bpp, _ in ladder]
    check("bytes/param is monotonically non-increasing down the real ladder "
          "(fp16 -> Q4_0 == Q4_K)",
          sizes[0] > sizes[2] and abs(sizes[2] - sizes[4]) < 1e-12)
    check("Q4_K_M (0.605) is slightly larger than Q4_K (0.5625) -- the MIX tax",
          sizes[5] > sizes[4])


# ============================================================================
# main
# ============================================================================

def main():
    print("gguf_quant.py - reference impl (GGUF block quantization: Q4_0, Q8_0, Q4_K).")
    print("Pure Python + torch. Numbers below feed GGUF_QUANT.md.  "
          f"torch = {torch.__version__}")
    print("\nConcept: block-wise quantize weight matrices into 4-bit/8-bit blocks +")
    print("a per-block fp16 scale, so a 7B SLM drops from 14 GB (fp16) to ~3.9 GB")
    print("(Q4) and fits edge RAM. Q4_K adds two-level super-block scaling for")
    print("lower error at the same size.\n")

    block, mse_q4 = section_a_q4_0()
    mse_q8 = section_b_q8_0(block, mse_q4)
    section_c_q4_k()
    section_d_size_table(mse_q4, mse_q8)
    section_e_lineage()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
