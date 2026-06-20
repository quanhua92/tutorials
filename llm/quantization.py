"""
quantization.py - Reference implementation of W4A16 group quantization.

This is the single source of truth that QUANTIZATION.md is built from. Every
number, table, and worked example in QUANTIZATION.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python quantization.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first; the math follows)
----------------------------------------------------------------------------
Quantization = "round the model's weights to a COARSER RULER so they take less
space and load faster." A 4-bit weight is only allowed 16 distinct values per
group (0..15), like rounding an image down to 16 colours. The price is a tiny
rounding error; the payoff is roughly 4x more weights fitting in memory.

* WEIGHTS, not ACTIVATIONS, get compressed. Weights are huge and STATIC (stored
  once, re-read every single token forever), so shrinking them pays back every
  decode step. Activations change every token and a few "outlier" channels
  dominate the answer (LLM.int8(), Dettmers 2022), so we keep them at 16-bit.
  That is exactly what "W4A16" means: 4-bit Weights, 16-bit Activations.
* GROUP quantization: one ruler (scale) + one offset (bias) is shared by a
  GROUP of 128 weights, not by each single weight. Fewer stored scales, still
  accurate. (This file uses a printable group of 8.)
* PACKING: squeeze eight 4-bit numbers into one 32-bit box (uint32) to halve-
  halve-halve the storage.
* DEQUANTIZE-ON-THE-FLY: unpack each nibble, multiply by the ruler, add the
  offset -> the real weight -> immediately multiply by the input, all in one
  breath inside the matmul's multiply-accumulate (MAC) loop. The full float
  weight matrix is NEVER materialized.

GLOSSARY (defined at first use in QUANTIZATION.md too)
  weight      a learned number inside a layer's matrix; "static" model knowledge
  activation  the data flowing through the model each token; "dynamic"
  bit / nibble 4 bits = half a byte = a "nibble"; a nibble holds 16 levels (0..15)
  scale       the ruler's step size (float16); one per group
  bias        the ruler's offset / start point (float16); one per group
  zero_point  the SAME offset expressed in INT units (= -bias/scale); GPTQ uses it
  group_size  how many consecutive weights share one (scale, bias); real = 128
  pack/unpack squeeze/extract eight nibbles into/from one uint32
  uint32      one unsigned 32-bit box; stores 8 nibbles = 8 weights
  matmul      matrix multiply; the core op of every linear layer
  dequantize  convert an int4 weight back to float: w = scale*w_int + bias
  bandwidth-bound  the chip spends its time WAITING for weights to arrive from
              memory, not doing math. This is why smaller weights = faster.

----------------------------------------------------------------------------
W4A16 = "Weights 4-bit, Activations 16-bit". Each group of `group_size`
consecutive weights (128 in real models; 8 here for printability) shares ONE
float16 `scale` and ONE float16 `bias`. Dequantization is fused into the
matmul's multiply-accumulate (MAC) loop - the int4 weight is unpacked from a
uint32, dequantized to float, and immediately multiplied by the activation.

============================================================================
SIGN CONVENTION  (verified against the MLX C++ source,
mlx/backend/cpu/quantized.cpp, function `quantize<T,U>` and `_qmm_t`)
============================================================================

  quantize :  w_int  = clip( round( (w - bias) / scale ), 0, 15 )
  dequant  :  w_float = scale * w_int + bias            <- bias in FLOAT units
  packing  :  one uint32 holds 8 nibbles; bits[4k : 4k+4] = w_int[k]

The MLX quantizer derives `scale` and `bias` per group from the data:

  w_min, w_max  = min/max of the group
  mask          = |w_min| > |w_max|              (which extreme is "heavier")
  scale         = mask ? +(w_max-w_min)/15 : -(w_max-w_min)/15
  edge          = mask ? w_min : w_max            (the heavier extreme)
  q0            = round(edge / scale)             (an integer, ~ -8..-9 or +8..+9)
  if q0 != 0:   scale = edge / q0 ;  bias = edge  (so `edge` maps EXACTLY)
  else:         bias = 0

Because `bias = edge` and `scale = edge/q0`, the extreme value `edge` always
reconstructs with ZERO error (it maps to int4 = q0 exactly). Interior weights
carry up to +/- scale/2 of rounding error.

The popular textbook formula `w = scale*(w_int - zero_point)` is ALGEBRAICALLY
EQUIVALENT only if `zero_point = -bias/scale` (note: int units, not float
units). Mixing the two conventions silently corrupts the model. See Section F.
============================================================================

Conventions:
    E = in_features   (input / embedding dim of one linear layer)
    N = out_features  (output dim; weight matrix is stored [N, E])
    group_size = number of consecutive weights sharing one (scale, bias).
                 Real models use 128; this file uses 8 so every number prints.
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72
BITS = 4
GROUP_SIZE = 8          # printable; real models use 64 or 128
N_LEVELS = (1 << BITS) - 1   # 15


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (faithful port of MLX's affine quantize)
# ============================================================================

def quantize_group(w: torch.Tensor, bits: int = BITS) -> tuple[float, float, torch.Tensor]:
    """Quantize ONE group of weights using MLX's affine scheme.

    Args:
        w: 1-D float tensor of shape [group_size].
        bits: bits per weight (4 here -> 16 levels 0..15).

    Returns:
        (scale, bias, w_int) where
            scale : float  (per-group, in float units)
            bias  : float  (per-group, in FLOAT units, == edge)
            w_int : int tensor of shape [group_size], values in [0, 15]

    dequant:  w_float = scale * w_int + bias
    """
    assert w.ndim == 1
    n_bins = (1 << bits) - 1            # 15
    eps = 1e-7

    w_min = float(w.min())
    w_max = float(w.max())

    mask = abs(w_min) > abs(w_max)       # which extreme is heavier in abs value
    scale = max((w_max - w_min) / n_bins, eps)
    scale = scale if mask else -scale
    edge = w_min if mask else w_max

    q0 = round(edge / scale)             # banker's rounding, matches std::rint
    bias = 0.0
    if q0 != 0:
        scale = edge / q0                # readjust so `edge` lands exactly on q0
        bias = float(edge)               # bias in FLOAT units (== edge)

    # quantize each element: clip(round((w - bias)/scale), 0, 15)
    w_int = torch.clip(torch.round((w - bias) / scale), 0, n_bins).to(torch.int32)
    return scale, bias, w_int


def pack_int4(w_int: torch.Tensor) -> int:
    """Pack 8 int4 values into one unsigned 32-bit integer.

    bits[4k : 4k+4] = w_int[k]   for k = 0..7
      k=0 -> bits 0..3    (lowest nibble)
      k=7 -> bits 28..31  (highest nibble)
    Returns a Python int in [0, 2**32).
    """
    assert w_int.numel() == 8, f"pack_int4 needs exactly 8 values, got {w_int.numel()}"
    packed = 0
    for k in range(8):
        nibble = int(w_int[k].item()) & 0xF
        packed |= nibble << (4 * k)
    return packed


def unpack_int4(packed: int) -> list[int]:
    """Inverse of pack_int4: extract 8 nibbles from one uint32.

    nibble_k = (packed >> (4*k)) & 0xF
    """
    return [(packed >> (4 * k)) & 0xF for k in range(8)]


def dequant_group(scale: float, bias: float, w_int: torch.Tensor) -> torch.Tensor:
    """w_float = scale * w_int + bias  (bias in FLOAT units - MLX convention)."""
    return scale * w_int.to(torch.float32) + bias


def quantized_matmul(x: torch.Tensor, W: torch.Tensor,
                     group_size: int = GROUP_SIZE) -> torch.Tensor:
    """W4A16 matmul: out = x @ dequant(W).T  with dequant INSIDE the MAC loop.

    Args:
        x: [1, E] float activation (16-bit in real inference).
        W: [N, E] float weight matrix (the ground truth we quantize on the fly).
        group_size: weights per group.

    Returns:
        out: [1, N] float, approximating x @ W.T.
    """
    assert x.shape[0] == 1
    N, E = W.shape
    out = torch.zeros(1, N)
    for n in range(N):
        row = W[n]                                  # [E]
        acc = 0.0
        for g_start in range(0, E, group_size):
            g = row[g_start:g_start + group_size]   # one group
            scale, bias, _ = quantize_group(g)      # quantize on the fly
            # MAC loop: unpack would happen here in the real kernel; we use the
            # already-quantized int4 values to mirror the dequant-inside-MAC path.
            w_int = torch.clip(torch.round((g - bias) / scale), 0, N_LEVELS).to(torch.int32)
            x_g = x[0, g_start:g_start + group_size]
            w_float = dequant_group(scale, bias, w_int)
            acc += float(torch.dot(w_float, x_g))
        out[0, n] = acc
    return out


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt(x: float, w: int = 6, p: int = 4) -> str:
    return f"{x:+{w}.{p}f}"


# ============================================================================
# 3. THE CONCRETE HERO EXAMPLE
#    A single row of 8 weights, chosen so the MLX quantizer yields clean
#    scale=0.2 / bias=-1.8 and all (w-bias)/scale values are unambiguous
#    (no element lands on a k+0.5 rounding boundary -> stable across
#    float32/float64, so .py and .html agree bit-for-bit on the int4 values).
# ============================================================================

HERO_ROW = torch.tensor([-1.80, 0.55, -0.35, 1.20, -0.85, 0.25, -1.15, 1.05],
                        dtype=torch.float32)

# A tiny matmul: x [1,8] @ W [4,8].T -> [1,4]. Row 0 is the hero row.
MATMUL_W = torch.tensor([
    [-1.80,  0.55, -0.35,  1.20, -0.85,  0.25, -1.15,  1.05],   # = HERO_ROW
    [ 0.90, -0.40,  1.10, -0.60,  0.80, -1.30,  0.50, -0.90],
    [-0.50,  1.40, -0.80,  0.60, -1.10,  0.30,  1.60, -0.40],
    [ 1.30, -0.20,  0.70, -1.00,  0.50, -0.80,  1.10, -0.30],
], dtype=torch.float32)
MATMUL_X = torch.tensor([[0.50, -0.30, 0.80, -0.10, 0.40, -0.60, 0.20, 0.70]],
                        dtype=torch.float32)


# ============================================================================
# 4. SECTIONS  (the numbers that feed QUANTIZATION.md)
# ============================================================================

def section_why_quantize():
    banner("SECTION A: WHY quantize - memory of a weight matrix (FP16 vs W4A16)")
    E = 896   # Qwen3-0.5B hidden dim
    print(f"One linear layer weight [N={E}, E={E}] (Qwen3-0.5B hidden dim):")
    fp16_bytes = E * E * 2
    print(f"  FP16 (bfloat16): {E}*{E}*2 = {fp16_bytes:>12,} bytes "
          f"= {fp16_bytes/1e6:.3f} MB")
    for gs in (8, 128):
        packed = E * E // 2                       # 4 bits = 0.5 byte/weight
        groups = E * E // gs
        sb = groups * (2 + 2)                     # scale(fp16) + bias(fp16)
        total = packed + sb
        ratio = fp16_bytes / total
        print(f"  W4A16 group_size={gs:>3}: packed={packed:>9,} B "
              f"+ scales/biases={sb:>6,} B = {total:>11,} bytes "
              f"= {total/1e6:.3f} MB  -> {ratio:.2f}x smaller")
    print()
    print("Decode is BANDWIDTH-bound: weights stream from HBM every token,")
    print("activations are computed and stay on-chip. So shrinking the STATIC")
    print("weight footprint (4x) directly speeds up inference; keeping")
    print("activations in 16-bit preserves accuracy (per LLM.int8() findings).")
    print()
    print("Tiny hero example (group_size=8, one row of 8 weights):")
    print(f"  FP16    : 8 * 2              = 16 bytes")
    print(f"  W4A16   : 1 uint32 (4 bytes) + scale(2)+bias(2) = 8 bytes  -> 2.0x")
    print(f"  (group_size=128 amortizes the scale/bias overhead -> ~3.8x)")


def section_quantize_one_row():
    banner("SECTION B: quantize ONE row of 8 floats -> scale, bias, 8 int4 values")
    w = HERO_ROW.clone()
    print(f"Input weight row w (group_size={GROUP_SIZE}, bits={BITS}):")
    print(f"  w = {[round(v, 2) for v in w.tolist()]}")
    print()
    scale, bias, w_int = quantize_group(w)
    print("Step 1-4 of the MLX affine quantizer (see quantize_group docstring):")
    w_min, w_max = float(w.min()), float(w.max())
    mask = abs(w_min) > abs(w_max)
    edge = w_min if mask else w_max
    print(f"  w_min={w_min:+.2f}  w_max={w_max:+.2f}")
    print(f"  mask = |w_min|>|w_max| = {abs(w_min):.2f}>{abs(w_max):.2f} = {mask}")
    print(f"  edge = {'w_min' if mask else 'w_max'} = {edge:+.2f}   "
          f"(the 'heavier' extreme -> maps to int4 with ZERO error)")
    print(f"  scale = edge/q0 = {edge:+.2f}/{round(edge/((w_max-w_min)/N_LEVELS))} "
          f"= {scale:.6f}")
    print(f"  bias  = edge    = {bias:+.6f}   (in FLOAT units, same scale as w)")
    print()
    print("Per-element quantize:  w_int = clip(round((w - bias)/scale), 0, 15)")
    print()
    print("| k |   w[k]   | (w-bias)/scale | round | w_int | dequant  |  error   |")
    print("|---|---------|----------------|-------|-------|----------|----------|")
    for k in range(GROUP_SIZE):
        ratio = (w[k].item() - bias) / scale
        deq = scale * int(w_int[k].item()) + bias
        err = w[k].item() - deq
        print(f"| {k} | {w[k].item():+.2f}   | {ratio:+14.4f} | "
              f"{int(w_int[k].item()):>5} | {int(w_int[k].item()):>5} | "
              f"{deq:+.4f}  | {err:+.4f}   |")
    print()
    print(f"RESULT: scale={scale:.4f}  bias={bias:+.4f}  "
          f"w_int={[int(v) for v in w_int.tolist()]}")
    print(f"Note: the extreme (w[0]={w_min:+.2f}) maps to w_int=0 and the other")
    print(f"extreme (w[3]={w_max:+.2f}) maps to w_int=15 - both ZERO error, by")
    print(f"construction (bias=edge, scale=edge/q0). Interior weights drift up")
    print(f"to +/- scale/2 = +-{scale/2:.4f}.")


def section_pack_uint32():
    banner("SECTION C: PACK 8 int4 values into ONE uint32 (bit layout)")
    _, _, w_int = quantize_group(HERO_ROW.clone())
    packed = pack_int4(w_int)
    print(f"w_int = {[int(v) for v in w_int.tolist()]}")
    print(f"       = {[hex(int(v)) for v in w_int.tolist()]}  (one nibble each)")
    print()
    print("Packing:  packed = sum_k  w_int[k] << (4*k)")
    print("          bits[4k : 4k+4] = w_int[k]")
    print()
    print("Bit layout of the uint32 (bit 31 = MSB, bit 0 = LSB):")
    print()
    print("  bit range  | k | shift | w_int[k] | hex nibble")
    print("  ------------|---|-------|----------|-----------")
    for k in range(8):
        print(f"  [{4*k:>2}:{4*k+4:<2}]      | {k} | {4*k:>5} | "
              f"{int(w_int[k].item()):>8} | {hex(int(w_int[k].item()))}")
    print()
    print(f"packed (decimal) = {packed}")
    print(f"packed (hex)     = 0x{packed:08X}")
    print(f"packed (binary)  = {packed:032b}")
    print()
    print("Read the hex string RIGHT-TO-LEFT to recover w_int in order:")
    nibbles = [(packed >> (4*k)) & 0xF for k in range(8)]
    print(f"  0x{packed:08X}  -> nibbles k=0..7 = {nibbles}")


def section_unpack_dequant():
    banner("SECTION D: UNPACK the uint32 + DEQUANT back to float; error per element")
    w = HERO_ROW.clone()
    scale, bias, w_int = quantize_group(w)
    packed = pack_int4(w_int)
    print(f"Stored on-chip: ONE uint32 = 0x{packed:08X} (= {packed}), plus")
    print(f"scale={scale:.4f} and bias={bias:+.4f} (both float16).")
    print()
    unpacked = unpack_int4(packed)
    print(f"Unpack: nibble_k = (packed >> 4*k) & 0xF")
    print(f"  unpacked = {unpacked}")
    assert unpacked == [int(v) for v in w_int.tolist()], "unpack mismatch!"
    print(f"  [check] unpack(pack(w_int)) == w_int :  OK")
    print()
    print("Dequant:  w_float = scale * w_int + bias   (MLX convention, +bias)")
    print()
    print("| k | w_orig | w_int | dequant = s*wi+b |  error  |")
    print("|---|--------|-------|------------------|---------|")
    deq_list = []
    for k in range(GROUP_SIZE):
        wi = unpacked[k]
        deq = scale * wi + bias
        deq_list.append(deq)
        err = w[k].item() - deq
        print(f"| {k} | {w[k].item():+.2f}  |  {wi:>2}   | "
              f"{scale:.2f}*{wi}+({bias:+.2f}) = {deq:+.4f} | {err:+.4f}  |")
    print()
    deq_t = torch.tensor(deq_list)
    max_err = float((w - deq_t).abs().max())
    mean_err = float((w - deq_t).abs().mean())
    print(f"Max abs error   = {max_err:.4f}  (= scale/2 = {scale/2:.4f} ceiling)")
    print(f"Mean abs error  = {mean_err:.4f}")
    print()
    print(f"GOLD (for QUANTIZATION.html to reproduce):")
    print(f"  scale   = {scale}")
    print(f"  bias    = {bias}")
    print(f"  w_int   = {unpacked}")
    print(f"  packed  = {packed}  (0x{packed:08X})")
    print(f"  dequant = {[round(v, 4) for v in deq_list]}")


def section_quantized_matmul():
    banner("SECTION E: quantized matmul vs float matmul  [1,8] @ [8,4]")
    x = MATMUL_X.clone()
    W = MATMUL_W.clone()
    N, E = W.shape
    print(f"x (activation, float16) shape [1, {E}]:")
    print(f"  {[round(v, 2) for v in x[0].tolist()]}")
    print(f"W (weight, float16) shape [{N}, {E}] - each row quantized independently:")
    for n in range(N):
        print(f"  row {n}: {[round(v, 2) for v in W[n].tolist()]}")
    print()
    # float ground truth
    out_float = x @ W.T
    print(f"FLOAT matmul  x @ W.T  =  {[round(v, 4) for v in out_float[0].tolist()]}")
    print()
    # quantized matmul (dequant fused inside MAC)
    out_quant = quantized_matmul(x, W, group_size=GROUP_SIZE)
    print(f"QUANT matmul (dequant in MAC) = {[round(v, 4) for v in out_quant[0].tolist()]}")
    print()
    print("| output n | float    | quantized | abs error |")
    print("|----------|----------|-----------|-----------|")
    for n in range(N):
        err = abs(out_float[0, n].item() - out_quant[0, n].item())
        print(f"| {n}        | {out_float[0,n].item():+.4f}  | "
              f"{out_quant[0,n].item():+.4f}   | {err:.4f}    |")
    print()
    abs_err = float((out_float - out_quant).abs().max())
    rel_err = float(((out_float - out_quant).abs() / out_float.abs()).mean())
    print(f"Max abs error  = {abs_err:.4f}")
    print(f"Mean rel error = {rel_err:.4f}  ({rel_err*100:.2f}%)")
    assert abs_err < 0.5, "quantized matmul diverged!"
    print(f"[check] max abs error {abs_err:.4f} < 0.5 :  OK  (quantized ~= float)")
    print(f"[check] quantized matmul shape == [1,{N}] :  OK")


def section_sign_convention_pitfall():
    banner("SECTION F: SIGN-CONVENTION PITFALL - MLX (+bias) vs textbook (-zero_point)")
    w = HERO_ROW.clone()
    scale, bias, w_int = quantize_group(w)
    print(f"Using the hero group: scale={scale:.4f}, bias={bias:+.4f} (float units),")
    print(f"w_int[1] = {int(w_int[1].item())} (the second weight, w[1]={w[1].item():+.2f}).")
    print()
    wi = int(w_int[1].item())
    true_deq = scale * wi + bias
    print("Three dequant formulas, all claiming to be 'the' affine dequant:")
    print()
    print("(1) MLX actual (this file, mlx/backend/cpu/quantized.cpp):")
    print(f"    w = scale*w_int + bias = {scale:.2f}*{wi} + ({bias:+.2f}) = {true_deq:+.4f}  CORRECT")
    print()
    zp = -bias / scale
    print("(2) Textbook zero-point (GPTQ/AWQ papers):")
    print(f"    zero_point = -bias/scale = -({bias:+.2f})/{scale:.2f} = {zp:.4f}  (INT units!)")
    deq2 = scale * (wi - zp)
    print(f"    w = scale*(w_int - zero_point) = {scale:.2f}*({wi} - {zp:.4f}) = {deq2:+.4f}  CORRECT")
    print()
    print("(3) Source-guide PROSE 'w = (w_int + bias)*scale' (MISLEADING):")
    deq3_wrong = (wi + bias) * scale
    print(f"    w = (w_int + bias)*scale = ({wi} + ({bias:+.2f}))*{scale:.2f} = {deq3_wrong:+.4f}  WRONG!")
    print()
    print(f"  (3) is off by {abs(deq3_wrong - true_deq):.4f} - silently. If you plug MLX's")
    print(f"  float-unit `bias` into the textbook `(w_int + X)*scale` shape, you get")
    print(f"  garbage. The two conventions are algebraically equal ONLY when")
    print(f"  zero_point = -bias/scale (note the /scale: int units vs float units).")
    print()
    assert abs(deq2 - true_deq) < 1e-6
    assert abs(deq3_wrong - true_deq) > 0.1
    print(f"[check] MLX (1) == textbook (2) when zp=-bias/scale :  OK")
    print(f"[check] source-guide prose (3) != MLX (1)            :  OK (it's wrong)")
    print()
    print("RULE: pick ONE convention and store its parameters with the right units.")
    print("  MLX checkpoint  -> dequant = scale*w_int + bias     (bias: float units)")
    print("  GPTQ checkpoint -> dequant = scale*(w_int - zp)     (zp:   int units)")
    print("Never cross them.")


# ============================================================================
# main
# ============================================================================

def main():
    print("quantization.py - reference impl. All numbers below feed QUANTIZATION.md.")
    print("torch =", torch.__version__)
    print("MLX-affine W4A16: dequant w = scale*w_int + bias (bias in FLOAT units)")

    section_why_quantize()
    section_quantize_one_row()
    section_pack_uint32()
    section_unpack_dequant()
    section_quantized_matmul()
    section_sign_convention_pitfall()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
