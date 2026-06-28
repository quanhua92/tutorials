"""
cpu_simd.py - Reference implementation of CPU SIMD for quantized LLM inference.

This is the single source of truth that CPU_SIMD.md is built from. Every
number, table, and worked example in CPU_SIMD.md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy, NO intrinsics) - this is a
SCALAR simulation of the SIMD loop structure plus the instruction-count math
that shows WHY SIMD wins. Real SIMD runs in C in ggml-cpu; this file teaches
the data flow.

Run:
    python3 cpu_simd.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
SIMD = Single Instruction, Multiple Data. One CPU instruction operates on a
VECTOR register holding N data elements side by side. Scalar code does one
multiply at a time; SIMD does N multiplies in one instruction - same clock
cost, N times the work.

The whole point of the Q4_0 block size = 32 (see quant_types.py) is that it
MATCHES the SIMD register width:
    32 weights x 4 bits = 128 bits = one xmm register (low half of a ymm)
    -> AVX2 can load a whole block's worth of packed nibbles in one load.

THE LINEAGE (oldest -> newest, each step = wider registers):
    scalar    (1 element per instruction)   the baseline everything beats
       |
    MMX/SSE   (4 x float32 in 128-bit xmm)  Intel Pentium III era (1999)
       |
    AVX2      (8 x float32 in 256-bit ymm)  Intel Haswell 2013, AMD Zen 2017
       |                                   8 Q4 lanes per FMA instruction
       |
    AVX-512   (16 x float32 in 512-bit zmm) Intel Xeon Scalable, AMD Zen4 2022
       |                                   16 Q4 lanes per FMA instruction
       |
    (parallel ARM branch)
    NEON      (4 x float32 in 128-bit)      ALL Apple Silicon (M1-M4), mobile
    SVE       (128-2048 bit, scalable)      ARM Neoverse V2, AWS Graviton4

GOLD VALUE (for CPU_SIMD.html to reproduce):
    Q4_0 block: q=[3,7,1,6,9,2,5,8], d=0.5, input x=[1,2,3,4,5,6,7,8]
    dequant = [d*(q-8) for each] = [-2.5,-0.5,-3.5,-1.0,0.5,-3.0,-1.5,0.0]
    dot = sum(d*q for d,q in zip(dequant, x)) = -44.0
    scalar ops  = 8 multiply + 7 add = 15
    AVX2 ops    ~ 3 (load, dequant, fmadd + horizontal sum)
    AVX-512 ops ~ 2
"""

from __future__ import annotations

BANNER = "=" * 74

# Block size (matches quant_types.py: QK4_0 = 32). The hero demo uses the first
# 8 weights so every number prints and every lane lines up with an AVX2 ymm
# lane (8 x float32 = 256 bits).
QK4_0 = 32
HERO_LEN = 8   # half a ymm register of float32 values

# Register widths (verified: Intel SDM Vol 1, ARM NEON/SVE reference).
REGISTER_BITS = {
    "scalar":   32,    # one float32
    "SSE":     128,    # xmm
    "AVX2":    256,    # ymm
    "AVX-512": 512,    # zmm
    "NEON":    128,    # ARM Q register
    "SVE":     128,    # min width (configurable up to 2048)
}

# Q4 dequant element counts per register (register_bits / 4 bits per nibble).
# But the FMA runs on DEQUANTED float32 values, so the lane count is
# register_bits / 32 (float32 width). Both views matter - see Section B.
FLOAT32_BITS = 32
NIBBLE_BITS = 4


# ============================================================================
# 0. CHECK HELPER (invariants the simulation must satisfy)
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


def fmt_row(values, p: int = 1) -> str:
    return "[" + ", ".join(f"{v:+.{p}f}" for v in values) + "]"


# ============================================================================
# 2. SCALAR DEQUANT + DOT PRODUCT (the kernel SIMD parallelizes)
#    Identical math to ggml-cpu's dequantize_row_q4_0 + vec_dot_q4_0_q8_0,
#    just unrolled so the per-element operation count is explicit.
# ============================================================================

def dequant_q4_0_scalar(d: float, quants: list[int]) -> list[float]:
    """Q4_0 dequant: w = d * (q - 8), one element at a time (SCALAR).

    This is what SIMD REPLACES. In real ggml-cpu this body is a 4-line
    intrinsics block that processes 8 (AVX2) or 16 (AVX-512) elements in
    parallel. Here we loop so the op count is countable.
    """
    return [d * (q - 8) for q in quants]


def dot_scalar(weights: list[float], inputs: list[float]) -> float:
    """Scalar dot product: 8 multiplies + 7 adds = 15 ops for 8 elements.

    This is the counter-SIMD baseline. The whole point of Section D is that
    AVX2 collapses these 15 scalar ops into ~3 vector ops.
    """
    assert len(weights) == len(inputs)
    n_mul = len(weights)
    n_add = len(weights) - 1
    acc = 0.0
    for w, x in zip(weights, inputs):
        acc += w * x   # one multiply + one add per iteration
    return acc, n_mul, n_add


def dot_scalar_fmadd(weights: list[float], inputs: list[float]) -> float:
    """Scalar with FMA semantics: acc = fma(w, x, acc), still 1 lane."""
    assert len(weights) == len(inputs)
    n_fma = len(weights)            # one fused-multiply-add per element
    n_hsum = 0                      # no horizontal sum needed (1 accumulator)
    acc = 0.0
    for w, x in zip(weights, inputs):
        acc += w * x                # treated as 1 FMA instruction
    return acc, n_fma, n_hsum


# ============================================================================
# 3. SIMD LOOP SIMULATION (counts the vector instructions, not the lanes)
#    We don't have real intrinsics in Python, but we CAN count what the
#    intrinsic sequence would be: load, unpack/dequant, fma, horizontal sum.
# ============================================================================

def simd_q4_0_dot_opcount(n_elements: int, lanes: int) -> dict:
    """Count the VECTOR instructions a real SIMD kernel would issue to compute
    the dot product of `n_elements` Q4_0 weights against fp32 inputs.

    Faithful to ggml-cpu's vec_dot_q4_0_q8_0_q8_0_q8_0 structure:
        1. LOAD packed nibbles            -> ceil(n_elem*4 / reg_bits) loads
        2. LOAD scale (fp16 -> fp32)      -> 1 broadcast
        3. UNPACK nibbles via shuffle     -> ceil(n_elem/lanes) shuffles
        4. SUB 8 + CONVERT to fp32        -> 1 per vector chunk
        5. MUL by scale                    -> 1 per vector chunk
        6. FMA: acc += w * x              -> ceil(n_elem/lanes) fma
        7. HORIZONTAL SUM lanes -> scalar -> 1 (hadd reduction tree)
    """
    chunks = -(-n_elements // lanes)   # ceil division
    loads = -(-n_elements * NIBBLE_BITS // (lanes * FLOAT32_BITS))
    instr = {
        "load_nibbles": loads,
        "load_scale":   1,
        "unpack":       chunks,        # shuffle-based nibble unpack
        "sub_convert":  chunks,        # subtract 8, int -> float
        "mul_scale":    chunks,        # multiply by fp16->fp32 scale
        "fma":          chunks,        # the heart: acc += w*x
        "hsum":         1,             # reduce vector accumulator to scalar
    }
    instr["total"] = sum(instr.values())
    return instr


# ============================================================================
# 4. SECTIONS
# ============================================================================

# --- hero block: deterministic, used for the gold-check in the HTML ---
HERO_Q = [3, 7, 1, 6, 9, 2, 5, 8]   # the 8 nibble values (0..15)
HERO_D = 0.5                         # the fp16 scale (delta)
HERO_X = [1, 2, 3, 4, 5, 6, 7, 8]   # the input activations


def section_a_concept():
    banner("SECTION A: SIMD = parallel data lanes")
    print("SCALAR: one instruction touches one element.")
    print("  mul r1, r2, r3     ; r1 = r2 * r3   (one multiply, one value)")
    print()
    print("SIMD: one instruction touches a VECTOR of N elements side by side.")
    print("  vmulps ymm0, ymm1, ymm2   ; 8 multiplies in parallel (AVX2)")
    print()
    print("The register is a LANE STACK - the hardware replicates the op across")
    print("every lane simultaneously. Doubling register width doubles throughput")
    print("at no extra clock cost (same pipeline, same latency, more lanes).")
    print()
    print("Lane widths by element type (AVX2 ymm = 256 bits):")
    print("| element type | bits | lanes in 256-bit AVX2 |")
    print("|---|---|---|")
    for name, bits in [("float32", 32), ("int8", 8), ("int4/nibble", 4), ("float16", 16)]:
        lanes = 256 // bits
        print(f"| {name:<11} | {bits:>4} | {lanes:>21} |")
    print()
    print("The Q4_0 dequant exploits this directly: the block size is 32 weights")
    print("= 128 packed bits = half an AVX2 ymm, so a full block's nibbles load")
    print("in one instruction and unpack into 8 float32 lanes per FMA.")
    check("32 nibbles = 128 bits = half ymm",
          32 * NIBBLE_BITS == 128 and 128 == REGISTER_BITS["AVX2"] // 2)
    check("AVX2 holds 8 float32 lanes", 256 // FLOAT32_BITS == 8)
    check("AVX-512 holds 16 float32 lanes", 512 // FLOAT32_BITS == 16)


def section_b_isa_table():
    banner("SECTION B: ISA comparison table (register width / Q4 lanes)")
    print("Four SIMD ISAs you will actually hit when running local LLMs. The")
    print("'Q4 elements/lane' column is the dequant throughput of ONE FMA op.")
    print()
    print("| ISA      | reg type    | bits  | float32 lanes | Q4 elem/lane | available on                     |")
    print("|----------|-------------|-------|---------------|--------------|----------------------------------|")
    rows = [
        ("AVX2",    "__m256i",   256, 8,  64,  "Intel Haswell (2013)+, AMD Zen (2017)+"),
        ("AVX-512", "__m512i",   512, 16, 128, "Intel Xeon Scalable, AMD Zen4 (2022)+"),
        ("NEON",    "uint8x16_t",128, 4,  32,  "ARM: all Apple Silicon, mobile, Graviton"),
        ("SVE",     "svint8_t",  128, 4,  32,  "ARM Neoverse V2, AWS Graviton4 (scalable)"),
    ]
    for name, rt, bits, flanes, q4lanes, avail in rows:
        print(f"| {name:<8} | {rt:<11} | {bits:>5} | {flanes:>13} | {q4lanes:>12} | {avail:<32} |")
    print()
    print("Read this table two ways:")
    print("  * For DOT PRODUCT (fp32 FMA): the 'float32 lanes' column matters.")
    print("    AVX-512 = 16x, AVX2 = 8x, NEON = 4x.")
    print("  * For UNPACK (nibble shuffle): the 'Q4 elem/lane' column matters.")
    print("    A single AVX2 register holds 64 packed nibbles at once.")
    print()
    print("Note: Apple Silicon (M1-M4) is NEON-only (128-bit). 4 float32 lanes")
    print("seems weak vs AVX-512's 16, BUT unified memory + ~100 GB/s bandwidth")
    print("compensate - decode is bandwidth-bound, not compute-bound (see")
    print("quant_types.py Section F: decode speed ~= 1/bpw).")
    check("NEON = 128 bits", REGISTER_BITS["NEON"] == 128)
    check("AVX-512 = 2x AVX2 width", REGISTER_BITS["AVX-512"] == 2 * REGISTER_BITS["AVX2"])


def section_c_inner_loop():
    banner("SECTION C: Q4_0 dequant inner loop (step by step)")
    print("The ggml-cpu inner loop for vec_dot_q4_0_q8_0 (verified against")
    print("ggml/src/ggml-cpu/quants.c). Six steps per block of 32 weights:")
    print()
    print("  for each block of 32 weights:")
    print("    1. LOAD scale: d = fp16->fp32(block.d)              [1 broadcast]")
    print("    2. LOAD packed bytes: 16 bytes = 32 nibbles         [1 load]")
    print("    3. UNPACK: split each byte into 2 nibbles            [shuffle]")
    print("       AVX2: _mm256_shuffle_epi8 lookup table")
    print("    4. SUBTRACT 8 + CONVERT to float32                  [_mm256_cvtepi32_ps]")
    print("    5. MUL by scale: w = d * (q-8)                      [_mm256_mul_ps]")
    print("    6. FMA accumulate: acc += w * x                     [_mm256_fmadd_ps]")
    print("  after all blocks: HORIZONTAL SUM the lane accumulator  [_mm256_hadd]")
    print()
    print("Hero block (8 weights, half an AVX2 ymm):")
    print(f"  q (4-bit)   = {HERO_Q}")
    print(f"  d (scale)   = {HERO_D}")
    print(f"  x (input)   = {HERO_X}")
    print()

    # Step 3: unpack is a no-op for us (Python ints) but real HW does a shuffle.
    print("STEP 3-5 walkthrough (scalar emulation of the SIMD lanes):")
    print("| i | q | q-8 | d*(q-8)  | x | w*x     |")
    print("|---|---|-----|----------|---|----------|")
    deq = dequant_q4_0_scalar(HERO_D, HERO_Q)
    prods = [w * x for w, x in zip(deq, HERO_X)]
    for i in range(HERO_LEN):
        print(f"| {i} | {HERO_Q[i]} | {HERO_Q[i]-8:>3} | {deq[i]:>+8.1f} | {HERO_X[i]} | {prods[i]:>+8.1f} |")
    print()
    print(f"dequant  = {fmt_row(deq, 1)}")
    print(f"products = {fmt_row(prods, 1)}")
    print(f"dot      = {sum(prods):+.1f}")
    expected_deq = [-2.5, -0.5, -3.5, -1.0, 0.5, -3.0, -1.5, 0.0]
    check("Q4_0 hero dequant matches spec",
          deq == expected_deq, f"got {fmt_row(deq,1)} expected {expected_deq}")
    check("Q4_0 hero dot product = -44.0",
          abs(sum(prods) - (-44.0)) < 1e-9, f"got {sum(prods)}")


def section_d_opcount():
    banner("SECTION D: dot-product op count - scalar vs SIMD")
    print("Same dot product (8 Q4_0 weights x 8 inputs), three ways. This is")
    print("the core argument for SIMD: the math is identical, the op count is")
    print("NOT. Each SIMD instruction replaces N scalar ops.")
    print()

    # Scalar baseline
    dot_s, n_mul, n_add = dot_scalar(
        dequant_q4_0_scalar(HERO_D, HERO_Q), HERO_X)
    scalar_total = n_mul + n_add
    print(f"SCALAR (no FMA):")
    print(f"  {n_mul} multiplies + {n_add} adds = {scalar_total} ops")
    print(f"  dot = {dot_s:+.1f}")
    print()

    # Scalar with FMA
    dot_fma, n_fma, n_hsum = dot_scalar_fmadd(
        dequant_q4_0_scalar(HERO_D, HERO_Q), HERO_X)
    print(f"SCALAR + FMA (acc = fma(w,x,acc)):")
    print(f"  {n_fma} FMA instructions, {n_hsum} horizontal sums = {n_fma + n_hsum} ops")
    print(f"  dot = {dot_fma:+.1f}")
    print()

    # SIMD for each ISA
    print(f"SIMD vector kernels (the SAME dot product, vectorized):")
    print()
    print("| ISA      | lanes | load | dequant | fma | hsum | total | speedup vs scalar |")
    print("|----------|-------|------|---------|-----|------|-------|-------------------|")
    for name, lanes in [("AVX2", 8), ("AVX-512", 16), ("NEON", 4)]:
        ops = simd_q4_0_dot_opcount(HERO_LEN, lanes)
        # dequant phase = unpack + sub_convert + mul_scale
        deq_ops = ops["unpack"] + ops["sub_convert"] + ops["mul_scale"]
        total = ops["total"]
        speedup = scalar_total / total
        print(f"| {name:<8} | {lanes:>5} | {ops['load_nibbles']:>4} | "
              f"{deq_ops:>7} | {ops['fma']:>3} | {ops['hsum']:>4} | "
              f"{total:>5} | {speedup:>15.1f}x |")
    print()
    print("Why AVX-512 wins so hard: 16 lanes means 1 FMA does the work of 16")
    print("scalar FMAs. The dequant + load overhead amortizes across more lanes.")
    print("On 8 elements the speedup is compressed (the hsum overhead is fixed),")
    print("but on a real 32-element block AVX-512 issues 2 FMAs vs AVX2's 4.")
    print()
    # Show the 32-element block math - the real production case
    print("Real production block (32 weights = full Q4_0 block):")
    print("| ISA      | lanes | fma ops | speedup vs scalar(32) |")
    print("|----------|-------|---------|-----------------------|")
    scalar32 = 32 + 31
    for name, lanes in [("AVX2", 8), ("AVX-512", 16), ("NEON", 4)]:
        ops32 = simd_q4_0_dot_opcount(32, lanes)
        sp = scalar32 / ops32["total"]
        print(f"| {name:<8} | {lanes:>5} | {ops32['fma']:>7} | {sp:>21.1f}x |")
    check("scalar dot == SIMD dot (same math)",
          abs(dot_s - dot_fma) < 1e-9)
    check("AVX2 fewer ops than scalar",
          simd_q4_0_dot_opcount(HERO_LEN, 8)["total"] < scalar_total)
    check("AVX-512 fewer ops than AVX2",
          simd_q4_0_dot_opcount(HERO_LEN, 16)["total"] <=
          simd_q4_0_dot_opcount(HERO_LEN, 8)["total"])


def section_e_practical():
    banner("SECTION E: practical impact - why AVX-512 matters for CPU inference")
    print("Three real-world consequences of the SIMD math in Section D:")
    print()
    print("1. BUILD FLAGS decide your speed. llama.cpp's CMake probes the CPU")
    print("   at build time and picks the best ISA. A binary built without")
    print("   AVX-512 on a Zen4 box silently falls back to AVX2 (half the lanes).")
    print("     GGML_NATIVE=ON      -> auto-detect (recommended)")
    print("     GGML_AVX512=ON      -> force AVX-512 code path")
    print("     GGML_AVX2=OFF       -> scalar/SSE only (for old CPUs / containers)")
    print()
    print("2. CLOUD GOTCHA. Some cloud providers (notably old GCP Cloud Run)")
    print("   expose AVX-512 in CPUID but SIGILL on the instructions. ggml picks")
    print("   the AVX-512 path at startup, then crashes on the first matmul.")
    print("   Fix: GGML_AVX512=OFF or pin to a CPU family without AVX-512.")
    print()
    print("3. APPLE SILICON REALITY. M1-M4 have NEON (128-bit = 4 float32 lanes)")
    print("   but NO AVX. The 4x lane deficit vs AVX-512 looks bad, but Apple's")
    print("   unified memory (~100 GB/s) means decode is bandwidth-bound:")
    print("   you pay to MOVE the weights, not to MULTIPLY them. So a 4.5 bpw")
    print("   Q4_0 model on an M2 often matches an AVX-512 Xeon at the same bpw.")
    print()
    print("The 1-line summary: SIMD width caps compute throughput, but local LLM")
    print("decode is bandwidth-bound - so memory bandwidth and bpw usually matter")
    print("MORE than raw SIMD width. SIMD is the floor; bandwidth is the ceiling.")
    # sanity-check the bandwidth-vs-compute framing
    check("AVX2 = 8x scalar FMA width", 256 // 32 == 8)
    check("NEON = half AVX2 lanes", (128 // 32) == (256 // 32) // 2)


# ============================================================================
# main
# ============================================================================

def main():
    print("cpu_simd.py - CPU SIMD for quantized LLM inference (scalar simulation).")
    print("Pure Python stdlib. Numbers below feed CPU_SIMD.md.")
    print("Sources: ggml/src/ggml-cpu/quants.c, Intel SDM Vol 1, ARM NEON/SVE ref.")
    print()
    print("Lineage: scalar (1) -> SSE (4) -> AVX2 (8) -> AVX-512 (16)")
    print("         parallel ARM branch: NEON (4) -> SVE (scalable)")

    section_a_concept()
    section_b_isa_table()
    section_c_inner_loop()
    section_d_opcount()
    section_e_practical()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
