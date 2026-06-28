"""
hardware_landscape.py - The 2026 local-LLM hardware landscape, by the numbers.

This is the single source of truth that HARDWARE_LANDSCAPE.md is built from.
Every number, table, and worked example in the .md is printed by this file.
Pure Python stdlib only (NO torch, NO numpy) - this is the *local runtime* side:
how memory capacity decides what fits, and how memory BANDWIDTH decides how fast
decode runs. The two are different specs and beginners conflate them constantly.

Run:
    python3 hardware_landscape.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
"Which computer do I buy to run local LLMs?" splits into TWO independent
questions, answered by TWO different hardware specs:

    1. WILL IT FIT?        -> memory CAPACITY (GB)        [can I load the weights?]
    2. HOW FAST IS DECODE? -> memory BANDWIDTH (GB/s)     [tok/s generation]

LINEAGE (single GPU -> unified memory -> workstation -> budget -> multi-GPU):

  SINGLE GPU (RTX 3090, 24GB):
    The origin. Cheap, fast (936 GB/s), but 24GB caps you at ~8B Q4 fully on GPU.
    To run bigger models you must OFFLOAD layers to CPU (see gpu_offload).

  UNIFIED MEMORY (Mac Studio M3 Ultra, 512GB):
    Apple's trick: CPU + GPU share ONE memory pool. You get laptop-tier bandwidth
    (819 GB/s) but DESKTOP-SERVER capacity (up to 512GB). A 200B+ Q4 model fits
    that no single discrete GPU can hold. Trade-off: bandwidth/GB is ~3x worse
    than GDDR, so tok/s per GB of model is lower than a discrete GPU.

  DESKTOP AI WORKSTATION (DGX Spark / GB10, 128GB + CUDA):
    NVIDIA's answer: 128GB unified LPDDR5X (273 GB/s) + 1 PFLOP FP4 compute +
    the FULL CUDA stack in a Mac-Mini chassis. Wins PREFILL (compute-bound), but
    loses DECODE (its 273 GB/s is the same as a budget Strix Halo).

  BUDGET UNIFIED (AMD Strix Halo / Framework Desktop, 128GB, $2,348):
    The same 128GB / 273 GB/s memory recipe as DGX Spark, at ~HALF the price, but
    on ROCm (not CUDA). Near-identical decode speed; ~5x slower prefill.

  MULTI-GPU DIY (3x RTX 3090, 72GB aggregate):
    The raw-bandwidth play. Three cards in pipeline parallel = 72GB capacity +
    ~936 GB/s effective decode bandwidth (one card streams per layer). Cheapest
    path to 100+ tok/s on a 120B model - at the cost of 1050W and no turnkey stack.

THE ONE FORMULA THIS WHOLE FILE BUILDS ON (the decode roofline):

    decode_tps ~= bandwidth_GBps / bytes_read_per_token

Decode is MEMORY-BANDWIDTH-BOUND, not compute-bound: to emit ONE token the engine
must stream (almost) all the active model weights out of memory once. So tok/s is
set by how fast memory can FEED the compute units, not how fast the units compute.
Prefill is the opposite: it processes the whole prompt in one big matmul batch, so
it is COMPUTE-bound (FLOPS matter) - see Section D.

GOLD VALUE (for HARDWARE_LANDSCAPE.html to reproduce):
    GPT-OSS 120B (MXFP4 MoE) measured decode, effective bytes/token = bw / tps:
        3x RTX 3090:  936 GB/s / 124.03 tps = 7.55 GB/token   (the reference)
        Strix Halo:   273 GB/s /  34.13 tps = 8.00 GB/token   <- gold (rounds clean)
    Same model, ~constant bytes/token across very different hardware => BANDWIDTH-BOUND.
    The HTML pins Strix Halo's 273 / 34.13 = 8.00 GB/token as the gold-check.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# THE 2026 HARDWARE TABLE
#   memory_gb       : usable memory capacity (GB). Unified = CPU+GPU pool.
#   bandwidth_gbs   : peak memory bandwidth (GB/s). The decode-speed spec.
#   backend         : the compute API / runtime that runs the matmuls.
#   price_usd       : representative price (midpoint of the range) for price/perf.
#   price_note      : the real price range (displayed; not used in arithmetic).
#   family          : grouping for the lineage (single/unified/workstation/diy).
#
# RX 7900 XTX bandwidth is 960 GB/s (384-bit x 20 Gbps GDDR6 per the AMD spec
# sheet); the value 819 sometimes quoted online is the Mac Studio M3 Ultra figure.
# 3x RTX 3090 "936 GB/s" is the EFFECTIVE decode bandwidth in llama.cpp's default
# pipeline-parallel layer split (one card streams per layer) - capacity is 3x24=72GB.
# ---------------------------------------------------------------------------
HARDWARE = {
    # --- Apple unified memory: huge capacity, mid bandwidth, MLX/Metal ---
    "Mac Studio M3 Ultra": {
        "memory_gb": 512, "bandwidth_gbs": 819, "backend": "Metal/MLX",
        "price_usd": 9000, "price_note": "~$6-12K (config-dependent)", "family": "unified"},
    "Mac Studio M4 Max": {
        "memory_gb": 128, "bandwidth_gbs": 546, "backend": "Metal/MLX",
        "price_usd": 3000, "price_note": "~$2-4K", "family": "unified"},
    "Mac Mini M4 Pro": {
        "memory_gb": 48, "bandwidth_gbs": 273, "backend": "Metal/MLX",
        "price_usd": 1600, "price_note": "~$1.6K", "family": "unified"},
    # --- NVIDIA DGX Spark: 128GB unified + CUDA + 1 PFLOP FP4 ---
    "DGX Spark (GB10)": {
        "memory_gb": 128, "bandwidth_gbs": 273, "backend": "CUDA",
        "price_usd": 4699, "price_note": "$4,699 (raised Feb 2026)", "family": "workstation"},
    # --- AMD Strix Halo: same memory recipe as Spark, ~half price, ROCm ---
    "AMD Strix Halo": {
        "memory_gb": 128, "bandwidth_gbs": 273, "backend": "ROCm",
        "price_usd": 2348, "price_note": "$2,348 (Framework Desktop)", "family": "workstation"},
    # --- Discrete GPUs: small VRAM, huge bandwidth ---
    "RTX 5090": {
        "memory_gb": 32, "bandwidth_gbs": 1792, "backend": "CUDA",
        "price_usd": 2000, "price_note": "~$2K", "family": "discrete"},
    "RTX 4090": {
        "memory_gb": 24, "bandwidth_gbs": 1008, "backend": "CUDA",
        "price_usd": 1600, "price_note": "~$1.6K", "family": "discrete"},
    "3x RTX 3090": {
        "memory_gb": 72, "bandwidth_gbs": 936, "backend": "CUDA",
        "price_usd": 2500, "price_note": "~$2.5K", "family": "multi-gpu"},
    "RX 7900 XTX": {
        "memory_gb": 24, "bandwidth_gbs": 960, "backend": "ROCm/Vulkan",
        "price_usd": 900, "price_note": "~$900", "family": "discrete"},
}

# ---------------------------------------------------------------------------
# GPT-OSS 120B (MXFP4) measured benchmark - the gold data set.
# Source: hardware-corner.net + aimultiple.com/dgx-spark-alternatives (2026).
#   prefill_tps : prompt-processing speed (tok/s) - COMPUTE-bound.
#   decode_tps  : token-generation speed (tok/s)  - BANDWIDTH-bound.
#   bandwidth   : the memory bandwidth of that system (GB/s).
# Note: GPT-OSS is a MoE model (128 experts, top-4 routed + shared), so only the
# ACTIVE experts are read per token during decode - that is why the effective
# bytes/token (~7-8 GB) is far smaller than the full 60 GB on-disk weights.
# ---------------------------------------------------------------------------
GPT_OSS_120B = {
    "3x RTX 3090":         {"prefill_tps": 1642.0, "decode_tps": 124.03, "bandwidth_gbs": 936},
    "Mac Studio M3 Ultra": {"prefill_tps": None,   "decode_tps": 70.79,  "bandwidth_gbs": 819},
    "DGX Spark (GB10)":    {"prefill_tps": 1723.07, "decode_tps": 38.55,  "bandwidth_gbs": 273},
    "AMD Strix Halo":      {"prefill_tps": 339.87,  "decode_tps": 34.13,  "bandwidth_gbs": 273},
}

# GPT-OSS 120B on-disk footprint (MXFP4 = 4-bit + scale overhead). From the
# benchmark source the file is 59.02 GiB. Used only for the "will it fit" check.
GPT_OSS_120B_WEIGHT_GB = 63.34   # 59.02 GiB -> decimal GB

# Bits-per-weight for the "will it fit / how fast" calculator (see QUANT_TYPES).
BPW = {"Q4_K_M": 4.5, "Q8_0": 8.5, "FP16": 16.0, "MXFP4": 4.0}

# Decode roofline efficiency for a DENSE model on a well-tuned runtime (llama.cpp).
# decode_tps_est = bandwidth / weight_gb * EFFICIENCY. ~0.55 accounts for KV-cache
# reads, attention, and non-ideal memory access patterns. This is for DENSE models;
# MoE models read only active experts and run faster than this estimate.
DECODE_EFFICIENCY = 0.55

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
# 1. THE CORE FORMULAS
# ============================================================================

def weight_gb(params_b: float, bpw: float) -> float:
    """Resident model weight footprint (GB): params_b * bpw / 8.

    The 1e9 from params cancels the 1e9 bytes->GB. Same as vram_estimator.py's
    weights term. This is what must FIT in memory capacity to load the model.
    """
    return params_b * bpw / 8.0


def roofline_decode(bandwidth_gbs: float, weight_gb_: float,
                    efficiency: float = DECODE_EFFICIENCY) -> float:
    """Decode roofline (tok/s): bandwidth / weight * efficiency.

    MEMORY-BANDWIDTH-BOUND. To emit one token the engine streams (almost) all the
    active weights out of memory once; tok/s is set by how fast memory FEEDS the
    compute units. `efficiency` < 1 accounts for KV-cache reads + attention + non-
    ideal access patterns. For MoE, pass the ACTIVE weight (not the full footprint).
    """
    if weight_gb_ <= 0:
        return 0.0
    return bandwidth_gbs / weight_gb_ * efficiency


def effective_bytes_per_token(bandwidth_gbs: float, decode_tps: float) -> float:
    """Implied GB streamed from memory per generated token = bw / tps.

    The diagnostic for "is decode bandwidth-bound?": if this is ~constant across
    very different hardware for the same model, then tok/s is set by bandwidth.
    """
    if decode_tps <= 0:
        return 0.0
    return bandwidth_gbs / decode_tps


def fits(weight_gb_: float, memory_gb: float) -> bool:
    """Will the weights fit in memory? (Capacity check, leaves KV+overhead slack.)

    Real usable memory is ~90% of nominal (OS/CUDA ctx); we leave headroom rather
    than model it here. Cross-ref vram_estimator for the exact KV+overhead budget.
    """
    return weight_gb_ <= memory_gb


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def gb(x: float) -> str:
    return f"{x:>7.1f} GB"


def money(x: float) -> str:
    return f"${x:,.0f}"


# ============================================================================
# 3. SECTIONS
# ============================================================================

def section_a_table():
    banner("SECTION A: THE 2026 HARDWARE TABLE - capacity, bandwidth, price")
    print("The two specs that matter, side by side. Memory CAPACITY (GB) decides")
    print("what fits; memory BANDWIDTH (GB/s) decides decode speed. They are NOT the")
    print("same number and confusing them is the #1 beginner mistake.")
    print()
    print("| hardware                 | mem(GB) | bw(GB/s) | backend     | price       |")
    print("|--------------------------|---------|----------|-------------|-------------|")
    for name in sorted(HARDWARE):
        h = HARDWARE[name]
        print(f"| {name:<24} | {h['memory_gb']:>7} | {h['bandwidth_gbs']:>8} | "
              f"{h['backend']:<11} | {h['price_note']:<11} |")
    print()
    print("Derived value metrics (price / spec = how cheap each unit of capability is):")
    print("| hardware                 | $/GB-mem | $/(GB/s)  | capacity tier | bw tier    |")
    print("|--------------------------|----------|-----------|---------------|------------|")
    for name in sorted(HARDWARE):
        h = HARDWARE[name]
        per_mem = h["price_usd"] / h["memory_gb"]
        per_bw = h["price_usd"] / h["bandwidth_gbs"]
        cap_tier = ("HUGE" if h["memory_gb"] >= 128 else
                    "big" if h["memory_gb"] >= 48 else "small")
        bw_tier = ("FAST" if h["bandwidth_gbs"] >= 800 else
                   "mid" if h["bandwidth_gbs"] >= 400 else "low")
        print(f"| {name:<24} | {per_mem:>7.1f}  | {per_bw:>8.1f}  | "
              f"{cap_tier:<13} | {bw_tier:<10} |")
    print()
    print("Read it in two directions:")
    print("  - DOWN a column: Mac Studio M3 Ultra has the most CAPACITY (512GB);")
    print("    RTX 5090 has the most BANDWIDTH (1792 GB/s). No single box wins both.")
    print("  - ACROSS a row: Strix Halo is ~half the $/GB-mem of DGX Spark for the")
    print("    SAME 128GB/273GB/s recipe - it is the value pick (see Section E).")
    check("Strix Halo cheaper per GB-mem than DGX Spark",
          HARDWARE["AMD Strix Halo"]["price_usd"] / HARDWARE["AMD Strix Halo"]["memory_gb"]
          < HARDWARE["DGX Spark (GB10)"]["price_usd"] / HARDWARE["DGX Spark (GB10)"]["memory_gb"])
    check("no single hardware has both max capacity AND max bandwidth",
          max(h["memory_gb"] for h in HARDWARE.values())
          != max(h["bandwidth_gbs"] for h in HARDWARE.values()))


def section_b_bandwidth_bound():
    banner("SECTION B: WHY DECODE IS BANDWIDTH-BOUND - weights read every token")
    print("During DECODE (generating one token at a time, batch=1), the engine must")
    print("read (almost) ALL the active model weights out of memory ONCE per token.")
    print("Compute is idle waiting on memory. So:")
    print()
    print("    decode_tps ~= bandwidth_GBps / bytes_read_per_token")
    print()
    print("Doubling bandwidth doubles tok/s. Doubling FLOPS does ~nothing for decode")
    print("(it helps PREFILL - see Section D). This is the roofline model.")
    print()
    print("Worked: a DENSE 70B Q4_K_M model. weight = 70 * 4.5 / 8 = "
          f"{weight_gb(70, 4.5):.2f} GB.")
    print("Theoretical peak decode (bw / weight, efficiency=1.0) per hardware:")
    print("| hardware                 | bw(GB/s) | peak tps | est tps* |")
    print("|--------------------------|----------|----------|----------|")
    w70 = weight_gb(70, 4.5)
    for name in sorted(HARDWARE):
        h = HARDWARE[name]
        peak = h["bandwidth_gbs"] / w70
        est = roofline_decode(h["bandwidth_gbs"], w70)
        print(f"| {name:<24} | {h['bandwidth_gbs']:>8} | {peak:>7.1f}  | {est:>6.1f}   |")
    print(f"  * est = peak * {DECODE_EFFICIENCY} (KV-cache reads + attention overhead)")
    print()
    print("Two facts this table forces on you:")
    spark_bw = HARDWARE["DGX Spark (GB10)"]["bandwidth_gbs"]
    gpu3_bw = HARDWARE["3x RTX 3090"]["bandwidth_gbs"]
    mini_bw = HARDWARE["Mac Mini M4 Pro"]["bandwidth_gbs"]
    print(f"  1. 3x3090 ({gpu3_bw} GB/s) decodes {gpu3_bw/spark_bw:.1f}x faster than")
    print(f"     DGX Spark ({spark_bw} GB/s) - PURELY because of bandwidth. Same model.")
    print(f"  2. Mac Mini M4 Pro ({mini_bw} GB/s) is bandwidth-equal to DGX Spark")
    print(f"     ({spark_bw} GB/s) - so it decodes a 70B at the SAME speed, for ~1/3 $.")
    check("3x3090 peak decode > DGX Spark peak decode (more bandwidth)",
          gpu3_bw / w70 > spark_bw / w70)
    check("decode scales linearly with bandwidth (3x3090/DGX == bw ratio)",
          abs((gpu3_bw / w70) / (spark_bw / w70) - gpu3_bw / spark_bw) < 1e-9)
    print()
    print("CAVEAT: this is for DENSE models. MoE models (GPT-OSS, DeepSeek, Qwen3-MoE)")
    print("read only the ACTIVE experts per token (~7-8 GB for GPT-OSS 120B, not the")
    print("full 60 GB on-disk), so they decode MUCH faster than a dense 120B would -")
    print("but the bandwidth-bound law still holds (Section C proves it).")


def section_c_gold_benchmark():
    banner("SECTION C: GPT-OSS 120B BENCHMARK - the measured proof (gold values)")
    print("GPT-OSS 120B in MXFP4 (4-bit), measured across four very different systems.")
    print("Source: hardware-corner.net + aimultiple.com/dgx-spark-alternatives (2026).")
    print("This is the canonical 2026 local-LLM benchmark - the numbers the whole")
    print("landscape is judged against.")
    print()
    print("| system               | prefill(tok/s) | decode(tok/s) | bw(GB/s) |")
    print("|----------------------|----------------|---------------|----------|")
    for name in ["3x RTX 3090", "Mac Studio M3 Ultra", "DGX Spark (GB10)", "AMD Strix Halo"]:
        b = GPT_OSS_120B[name]
        pf = f"{b['prefill_tps']:>11.1f}" if b["prefill_tps"] is not None else f"{'n/a':>11}"
        print(f"| {name:<20} | {pf}  | {b['decode_tps']:>11.2f}   | "
              f"{b['bandwidth_gbs']:>8} |")
    print()
    print("THE DIAGNOSTIC: effective GB streamed per generated token = bw / decode_tps.")
    print("If decode is bandwidth-bound, this is ~constant across all hardware.")
    print("| system               | bw(GB/s) | decode  | GB/token | reads how?        |")
    print("|----------------------|----------|---------|----------|-------------------|")
    for name in ["3x RTX 3090", "Mac Studio M3 Ultra", "DGX Spark (GB10)", "AMD Strix Halo"]:
        b = GPT_OSS_120B[name]
        bpt = effective_bytes_per_token(b["bandwidth_gbs"], b["decode_tps"])
        note = {"3x RTX 3090": "CUDA (most efficient)",
                "Mac Studio M3 Ultra": "Metal/MLX (overhead)",
                "DGX Spark (GB10)": "CUDA (efficient)",
                "AMD Strix Halo": "ROCm"}[name]
        print(f"| {name:<20} | {b['bandwidth_gbs']:>8} | {b['decode_tps']:>6.2f}  | "
              f"{bpt:>7.2f}  | {note} |")
    print()
    print("GB/token clusters at ~7-8 for the CUDA/ROCm systems (active MoE experts),")
    print("~11.6 for the Mac (Metal/MLX moves more per token). The spread is software")
    print("efficiency, NOT a different model - the bandwidth-bound law still holds:")
    print()
    print("  decode(3x3090) / decode(DGX Spark) = "
          f"{GPT_OSS_120B['3x RTX 3090']['decode_tps']/GPT_OSS_120B['DGX Spark (GB10)']['decode_tps']:.2f}"
          f"   vs   bw ratio = {936/273:.2f}")
    print("  -> the ~3.2x measured decode gap tracks the ~3.4x bandwidth gap.")
    print("     That IS the bandwidth-bound signature.")
    spark_d = GPT_OSS_120B["DGX Spark (GB10)"]["decode_tps"]
    strix_d = GPT_OSS_120B["AMD Strix Halo"]["decode_tps"]
    gpu3_d = GPT_OSS_120B["3x RTX 3090"]["decode_tps"]
    check("decode ratio (3x3090/DGX) within 15% of bandwidth ratio",
          abs((gpu3_d / spark_d) / (936 / 273) - 1.0) < 0.15,
          f"{gpu3_d/spark_d:.2f} vs {936/273:.2f}")
    check("same-bandwidth systems decode within 20% (DGX vs Strix, both 273 GB/s)",
          abs(spark_d - strix_d) / max(spark_d, strix_d) < 0.20,
          f"{spark_d} vs {strix_d}")
    print()
    print("GOLD (for HARDWARE_LANDSCAPE.html): Strix Halo effective bytes/token")
    gold_bpt = effective_bytes_per_token(273, 34.13)
    print(f"    273 GB/s / 34.13 tok/s = {gold_bpt:.6f} GB/token  (~8.00 GB/token)")
    check("gold: Strix Halo bytes/token ~= 8.00", abs(gold_bpt - 8.00) < 0.01,
          f"got {gold_bpt:.4f}")


def section_d_prefill_vs_decode():
    banner("SECTION D: PREFILL vs DECODE - compute-bound vs bandwidth-bound")
    print("LLM serving has TWO phases with OPPOSITE bottlenecks. Mixing them up is")
    print("why people buy the wrong hardware.")
    print()
    print("| phase   | what it does              | bottleneck    | wins on...      |")
    print("|---------|---------------------------|---------------|-----------------|")
    print("| PREFILL | process the WHOLE prompt   | COMPUTE(FLOPS)| tensor cores    |")
    print("| DECODE  | emit ONE token at a time   | MEMORY(bw)    | bandwidth (GB/s)|")
    print()
    print("PREFILL batches the entire prompt into one giant matmul - compute units are")
    print("the limit, so FLOPS (tensor-core throughput) sets the speed. DECODE emits one")
    print("token at a time (batch=1), so each weight is read once per token and memory")
    print("BANDWIDTH is the limit - FLOPS sit idle waiting for data.")
    print()
    print("The GPT-OSS 120B benchmark makes the split vivid:")
    print("| system               | prefill | decode  | who wins prefill?   | who wins decode?  |")
    print("|----------------------|---------|---------|---------------------|------------------|")
    for name in ["DGX Spark (GB10)", "AMD Strix Halo", "3x RTX 3090"]:
        b = GPT_OSS_120B[name]
        pf = b["prefill_tps"]
        pf_note = ("1 PFLOP FP4 -> WINS" if name == "DGX Spark (GB10)"
                   else "~50 TOPS -> slow" if name == "AMD Strix Halo"
                   else "fast compute")
        dc_note = ("273 GB/s -> slow" if "273" in str(b["bandwidth_gbs"])
                   else f"{b['bandwidth_gbs']} GB/s")
        dc_note = ("936 GB/s -> WINS" if name == "3x RTX 3090" else dc_note)
        print(f"| {name:<20} | {pf:>6.0f}  | {b['decode_tps']:>6.2f}  | "
              f"{pf_note:<19} | {dc_note:<16} |")
    print()
    pf_spark = GPT_OSS_120B["DGX Spark (GB10)"]["prefill_tps"]
    pf_strix = GPT_OSS_120B["AMD Strix Halo"]["prefill_tps"]
    print(f"  DGX Spark prefill / Strix Halo prefill = {pf_spark/pf_strix:.1f}x")
    print("  -> Spark's 1 PFLOP FP4 tensor cores crush prefill (compute-bound).")
    print("  -> Yet they DECODE at nearly the same speed (both 273 GB/s, bandwidth-bound).")
    print()
    print("RULE OF THUMB: if your workload is LONG PROMPTS / short answers (RAG, code")
    print("completion, document Q&A), prefill dominates -> buy COMPUTE (DGX Spark,")
    print("tensor cores). If it is CHAT / long generation, decode dominates -> buy")
    print("BANDWIDTH (3x3090, Mac Studio). Section F shows you can split the two.")
    check("DGX Spark prefill >> Strix Halo prefill (compute-bound phase)",
          pf_spark > 3 * pf_strix, f"{pf_spark} vs {pf_strix}")
    check("DGX Spark decode ~= Strix Halo decode (bandwidth-bound, same 273 GB/s)",
          abs(GPT_OSS_120B["DGX Spark (GB10)"]["decode_tps"]
              - GPT_OSS_120B["AMD Strix Halo"]["decode_tps"]) < 10)


def section_e_decision():
    banner("SECTION E: 'WHICH TO BUY?' - the decision tree + price/performance")
    print("Pick by your LARGEST model and your budget. Memory capacity is a hard gate")
    print("(it either fits or it doesn't); bandwidth then sets the speed you get.")
    print()
    print("Price/performance for GPT-OSS 120B DECODE (where we have measured tok/s):")
    print("| system               | price    | decode  | $/tok-per-sec | verdict           |")
    print("|----------------------|----------|---------|---------------|-------------------|")
    for name in ["3x RTX 3090", "Mac Studio M3 Ultra", "DGX Spark (GB10)", "AMD Strix Halo"]:
        b = GPT_OSS_120B[name]
        price = HARDWARE[name]["price_usd"]
        per_tps = price / b["decode_tps"]
        verdict = {"3x RTX 3090": "best $/tok-s overall",
                   "Mac Studio M3 Ultra": "biggest models (512GB)",
                   "DGX Spark (GB10)": "prefill + CUDA stack",
                   "AMD Strix Halo": "best unified value"}[name]
        print(f"| {name:<20} | {money(price):>8} | {b['decode_tps']:>6.2f}  | "
              f"{per_tps:>12.0f}  | {verdict} |")
    print()
    per_tps_spark = HARDWARE["DGX Spark (GB10)"]["price_usd"] / GPT_OSS_120B["DGX Spark (GB10)"]["decode_tps"]
    per_tps_strix = HARDWARE["AMD Strix Halo"]["price_usd"] / GPT_OSS_120B["AMD Strix Halo"]["decode_tps"]
    per_tps_3x = HARDWARE["3x RTX 3090"]["price_usd"] / GPT_OSS_120B["3x RTX 3090"]["decode_tps"]
    print(f"  3x3090 $/tok-per-sec = {per_tps_3x:.0f}   (best raw decode value)")
    print(f"  Strix Halo $/tok-per-sec = {per_tps_strix:.0f}   vs   DGX Spark = {per_tps_spark:.0f}")
    print(f"  -> Among 128GB unified boxes, Strix Halo is ~{per_tps_spark/per_tps_strix:.1f}x better")
    print(f"     value than DGX Spark (half the price, same ~273 GB/s decode speed).")
    check("3x3090 is the best raw decode value (lowest $/tps)",
          per_tps_3x == min(
              HARDWARE[n]["price_usd"] / GPT_OSS_120B[n]["decode_tps"]
              for n in GPT_OSS_120B))
    check("Strix Halo beats DGX Spark on $/tps (half price, same bandwidth)",
          per_tps_strix < per_tps_spark)
    print()
    print("DECISION TREE (by what you actually want to run):")
    print()
    print("  Want <= 14B Q4 (chat, fast)?")
    print("    -> single discrete GPU: RTX 5090 (32GB/1792 GB/s) or RTX 4090 (24GB).")
    print("       Best tok/s per dollar; bandwidth is huge; capacity is the only cap.")
    print()
    print("  Want 70B Q4 (strong reasoning, fits in ~40GB)?")
    print("    -> 3x RTX 3090 (72GB, 936 GB/s): fastest decode, cheapest speed.")
    print("    -> Mac Studio M4 Max (128GB, 546 GB/s): single-box, quiet, MLX.")
    print("    -> offload on a single 24GB card is viable but slow (see gpu_offload).")
    print()
    print("  Want 120B-200B+ (GPT-OSS, command-R, huge context)?")
    print("    -> Mac Studio M3 Ultra (512GB): the ONLY single box that holds 200B+ Q4.")
    print("    -> DGX Spark / Strix Halo (128GB): hold up to ~120B Q4, CUDA vs ROCm.")
    print()
    print("  Want the CUDA ecosystem + fast prefill (dev, fine-tuning, agents)?")
    print("    -> DGX Spark. You pay for the stack, not the raw decode speed.")


def section_f_hybrid():
    banner("SECTION F: THE HYBRID TRICK - disaggregate prefill from decode")
    print("Since prefill and decode have OPPOSITE bottlenecks (Section D), no single")
    print("box is optimal at both. EXO Labs' insight: network TWO boxes and let each")
    print("do the phase it is best at. Source: blog.exolabs.net (2026).")
    print()
    print("    DGX Spark (1 PFLOP FP4)  -->  fast PREFILL   [compute-bound phase]")
    print("    Mac Studio M3 Ultra      -->  fast DECODE     [bandwidth-bound phase]")
    print("                networked over 200 Gbps ConnectX-7")
    print()
    print("Measured result on GPT-OSS 120B: this disaggregated pair runs ~2.8x faster")
    print("END-TO-END than the Mac Studio alone (the Spark's prefill removes the Mac's")
    print("weakness; the Mac's 819 GB/s decode removes the Spark's 273 GB/s weakness).")
    print()
    mac_decode = GPT_OSS_120B["Mac Studio M3 Ultra"]["decode_tps"]
    spark_prefill = GPT_OSS_120B["DGX Spark (GB10)"]["prefill_tps"]
    mac_prefill_est = 420  # community-reported Mac prefill on GPT-OSS 120B (approx)
    print(f"  Mac Studio alone:  prefill ~{mac_prefill_est} t/s, decode {mac_decode:.1f} t/s")
    print(f"  Hybrid:            prefill ~{spark_prefill:.0f} t/s (Spark), decode {mac_decode:.1f} t/s (Mac)")
    print(f"  -> prefill speedup ~{spark_prefill/mac_prefill_est:.1f}x, decode unchanged; "
          f"end-to-end ~2.8x (EXO Labs).")
    check("hybrid prefill (Spark) beats Mac-alone prefill",
          spark_prefill > mac_prefill_est, f"{spark_prefill} vs ~{mac_prefill_est}")
    check("hybrid decode (Mac) beats Spark-alone decode",
          mac_decode > GPT_OSS_120B["DGX Spark (GB10)"]["decode_tps"],
          f"{mac_decode} vs {GPT_OSS_120B['DGX Spark (GB10)']['decode_tps']}")
    print()
    print("This is PREFILL/DECODE DISAGGREGATION at the desktop scale - the same idea")
    print("datacenters use (separate prefill pools from decode pools). Cross-ref")
    print("llm/DISAGGREGATED_SERVING for the datacenter version. The win comes from")
    print("NOT forcing one machine's memory system to serve two opposite bottlenecks.")


def section_g_calculator():
    banner("SECTION G: 'WILL IT FIT + HOW FAST?' - the calculator")
    print("Pick a (model size, quant). For each hardware: does it FIT in capacity, and")
    print("if so what decode tok/s do we ESTIMATE? Dense-model roofline at efficiency=")
    print(f"{DECODE_EFFICIENCY} (KV+attention overhead). MoE models run faster than this.")
    print()
    configs = [
        ("8B Q4_K_M",   8.0,  4.5),
        ("8B Q8_0",     8.0,  8.5),
        ("14B Q4_K_M", 14.0,  4.5),
        ("70B Q4_K_M", 70.0,  4.5),
        ("70B Q8_0",   70.0,  8.5),
        ("120B Q4",   120.0,  4.0),
    ]
    for label, params, bpw in configs:
        w = weight_gb(params, bpw)
        print(f"=== {label}  ({params}B @ {bpw} bpw = {w:.1f} GB weights) ===")
        print("| hardware                 | fits? | est decode (tok/s) |")
        print("|--------------------------|-------|--------------------|")
        for name in sorted(HARDWARE):
            h = HARDWARE[name]
            ok = fits(w, h["memory_gb"])
            if ok:
                est = roofline_decode(h["bandwidth_gbs"], w)
                cell = f"{est:>14.1f}     "
            else:
                cell = "  offload (see gpu_offload)"
            print(f"| {name:<24} | {'yes' if ok else 'NO':>5} | {cell} |")
        print()
    print("How to read the calculator:")
    w8 = weight_gb(8.0, 4.5)
    print(f"  - 8B Q4 ({w8:.1f} GB): fits EVERYTHING, even a 24GB card. A single RTX")
    est_5090 = roofline_decode(HARDWARE["RTX 5090"]["bandwidth_gbs"], w8)
    print(f"    5090 estimates ~{est_5090:.0f} tok/s (1792 GB/s is enormous for 4.5 GB).")
    w120 = weight_gb(120.0, 4.0)
    print(f"  - 120B Q4 ({w120:.0f} GB): fits Mac Studio M3 Ultra (512GB), the 128GB")
    print(f"    unified boxes (DGX Spark / Strix Halo / M4 Max), AND 3x RTX 3090 (72GB).")
    print(f"    A single 24-32GB discrete GPU CANNOT hold it -> must offload (gpu_offload).")
    check("8B Q4 fits all hardware (even 24GB)",
          all(fits(w8, h["memory_gb"]) for h in HARDWARE.values()))
    check("120B Q4 does NOT fit a 24GB card",
          not fits(w120, 24))
    check("120B Q4 fits Mac Studio M3 Ultra (512GB)",
          fits(w120, HARDWARE["Mac Studio M3 Ultra"]["memory_gb"]))
    check("RTX 5090 estimates the fastest decode for 8B (most bandwidth)",
          roofline_decode(HARDWARE["RTX 5090"]["bandwidth_gbs"], w8)
          == max(roofline_decode(h["bandwidth_gbs"], w8) for h in HARDWARE.values()))


def section_gold():
    banner("GOLD VALUE - the canonical numbers the HTML must reproduce")
    print("Two gold checks: (1) the bandwidth-bound diagnostic for Strix Halo,")
    print("(2) the decode roofline for a dense 70B on 3x RTX 3090.")
    print()
    bpt = effective_bytes_per_token(273, 34.13)
    print(f"  GOLD 1: Strix Halo effective bytes/token = 273 / 34.13 = {bpt:.6f}")
    print(f"          (rounds to {bpt:.2f} GB/token)")
    check("gold1: 273/34.13 ~= 8.00", abs(bpt - 8.00) < 0.01, f"got {bpt:.4f}")
    print()
    w70 = weight_gb(70, 4.5)
    est = roofline_decode(936, w70, DECODE_EFFICIENCY)
    print(f"  GOLD 2: decode(70B Q4_K_M, 3x3090) = 936 / {w70:.2f} * {DECODE_EFFICIENCY}")
    print(f"          = {est:.2f} tok/s  (estimate; real llama.cpp ~10-15 tok/s)")
    check("gold2: 70B Q4 on 3x3090 estimates in 10-20 tok/s band",
          10.0 < est < 20.0, f"got {est:.2f}")
    print()
    print("  The HTML recomputes GOLD 1 (273/34.13) with the identical formula and")
    print("  shows [check: OK] if it lands on 8.00.")


# ============================================================================
# main
# ============================================================================

def main():
    print("hardware_landscape.py - the 2026 local-LLM hardware landscape, by the numbers.")
    print("Pure Python stdlib. Numbers below feed HARDWARE_LANDSCAPE.md.")
    print("Sources: hardware-corner.net + aimultiple.com/dgx-spark-alternatives (2026).")
    print()
    print("Lineage: single GPU (3090) -> unified (Mac Studio) -> workstation (DGX Spark)")
    print("       -> budget (Strix Halo) -> multi-GPU DIY (3x3090).")

    section_a_table()
    section_b_bandwidth_bound()
    section_c_gold_benchmark()
    section_d_prefill_vs_decode()
    section_e_decision()
    section_f_hybrid()
    section_g_calculator()
    section_gold()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
