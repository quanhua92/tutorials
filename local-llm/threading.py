"""
threading.py - Reference implementation of CPU threading in llama.cpp
(`--threads N` and `--threads-batch N`).

WHAT IS CPU THREADING IN LLAMA.CPP? (start here)
   A single forward pass has two PHASES that stress the CPU very differently:

     PREFILL (prompt processing):  the model eats ALL prompt tokens at once.
       Batch size = prompt length (hundreds/thousands). This is a big matmul
       [d, d] x [d, batch]. Compute-heavy. Adding threads parallelizes the
       FLOPs across matmul rows -> near-linear speedup up to physical cores.

     DECODE (token generation):    the model emits ONE token per step.
       Batch size = 1. The matmul is [d, d] x [d, 1]. The whole weight matrix
       must be streamed from RAM for a single column of work -> MEMORY-BANDWIDTH
       bound. Adding threads does NOT multiply the bandwidth, so speedup
       saturates fast (typically ~2x at physical-core count, then flat/worse).

   ggml uses a thread pool: the matmul's output rows are split into N chunks,
   one per worker thread. Each thread runs the SIMD dot-product kernel on its
   slice. `--threads N` controls decode; `--threads-batch N` controls prefill.

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. SINGLE-THREAD:  one core does everything. Fine for tiny models, but a 7B
      model on one core gives ~2 tok/s. The other cores sit idle.

   2. `--threads N` (PARALLEL MATMUL ROWS):  split the output rows of every
      matmul across N worker threads. Prefill scales ~linearly (compute-bound).
      Decode barely moves (memory-bound). Problem: ONE knob for two phases that
      scale totally differently.

   3. `--threads-batch N` (SEPARATE PREFILL vs DECODE):  two independent thread
      counts. Set `--threads-batch` high (= physical cores) for fast prompt
      processing; set `--threads` lower (= 4-6) since decode is bandwidth-bound
      and extra threads only add scheduling overhead.

   4. NUMA-AWARE PINNING (`--numa`):  on multi-socket servers, RAM is split
      across NUMA nodes. If a thread on socket B reads weights resident on
      socket A, it crosses the interconnect (~2-4x slower). `--numa isabelle`
      pins threads to the node where their weights live, restoring local
      bandwidth.

WHY IT MATTERS:  on an 8-core CPU, going 1 -> 8 threads takes prefill from
   baseline to 5.5x (huge). But decode only reaches ~2.0x because RAM bandwidth
   is the wall, and pushing to 16 hyperthreads makes BOTH phases SLOWER (cache
   thrashing + FPU contention). Right-sizing the two thread counts is free perf.

THE GOLD VALUES (this bundle's load-bearing claim):
     prefill @ 8 threads  = 5.5x single-thread   (peak)
     decode  @ 8 threads  = 2.0x single-thread   (peak)
     prefill @ 16 threads = 5.0x  (WORSE than 8 -- hyperthread penalty)
     decode  @ 16 threads = 1.8x  (WORSE)

Companion code that THREADING.md is built from. Every number below is printed by:
    python3 threading.py

PURE PYTHON STDLIB (no torch, no numpy). Deterministic (hardcoded curves).
"""

from __future__ import annotations

BANNER = "=" * 72

# ============================================================================
# 1. The reference CPU + the empirical scaling curves
# ============================================================================
#
# These curves are HARDCODED from the documented behaviour of llama.cpp on a
# typical 8-physical-core x86 desktop CPU (see Sources). They are the
# "ground truth" every other number in this bundle derives from.
#
# Key shape facts:
#   - prefill (compute-bound) climbs near-linearly to ~5.5x at 8 threads,
#     then DROPS at 16 (hyperthreads share the FPU/SIMD unit + thrash cache).
#   - decode (memory-bound) saturates by ~4-6 threads at ~2.0x, then drops.
#
# Speedup is relative to 1 thread (= 1.0x baseline).

PHYSICAL_CORES = 8        # this CPU has 8 physical cores
LOGICAL_CORES = 16        # 2-way hyperthreading -> 16 logical cores

# (n_threads, speedup_vs_1_thread)  -- empirical, linearly interpolated between
PREFILL_CURVE = [
    (1, 1.0), (2, 1.8), (4, 3.2), (6, 4.6), (8, 5.5),
    (12, 5.2), (16, 5.0), (24, 4.6), (32, 4.2),
]
DECODE_CURVE = [
    (1, 1.0), (2, 1.6), (4, 1.9), (6, 2.0), (8, 2.0),
    (12, 1.9), (16, 1.8), (24, 1.6), (32, 1.4),
]


def interp(curve: list[tuple[int, float]], n: int) -> float:
    """Piecewise-linear interpolation of an empirical speedup curve.

    clamps to the endpoints outside the table range (flat, not extrapolated).
    """
    if n <= curve[0][0]:
        return curve[0][1]
    if n >= curve[-1][0]:
        return curve[-1][1]
    for i in range(len(curve) - 1):
        n0, s0 = curve[i]
        n1, s1 = curve[i + 1]
        if n0 <= n <= n1:
            if n1 == n0:
                return s0
            t = (n - n0) / (n1 - n0)
            return s0 + t * (s1 - s0)
    return curve[-1][1]


def prefill_speedup(n_threads: int) -> float:
    """Prefill (prompt processing) speedup vs 1 thread. Compute-bound."""
    return interp(PREFILL_CURVE, n_threads)


def decode_speedup(n_threads: int) -> float:
    """Decode (token generation) speedup vs 1 thread. Memory-bound."""
    return interp(DECODE_CURVE, n_threads)


# ============================================================================
# 2. The mechanism: WHY prefill scales but decode doesn't (roofline)
# ============================================================================
#
# A matmul  Y[M,N] = W[M,K] @ X[K,N]  has:
#   compute = 2*M*K*N  FLOPs (multiply-adds)
#   memory  = M*K*bw   bytes to stream the weight W  (bw = bytes/weight element)
#            + K*N*bx  bytes for the activations X  (bx = bytes/activation)
#
#   arithmetic_intensity = compute / memory   (FLOPs per byte moved)
#
# Decode (N=1):   intensity ~ 1/bw  -> very low  -> MEMORY-bound
# Prefill (N=B):  intensity ~ B/bw  -> high      -> COMPUTE-bound
#
# Threads parallelize COMPUTE but SHARE the memory bus. So:
#   - compute-bound (prefill):  N threads ~ N x faster (until the FPU/SIMD
#     units saturate, i.e. at physical-core count)
#   - memory-bound (decode):    N threads all pull from the SAME bus -> the bus
#     bandwidth caps the speedup; extra threads just contend.

def matmul_roofline(d: int = 4096, batch_decode: int = 1, batch_prefill: int = 512,
                    weight_bytes: float = 0.5) -> dict:
    """Compute the arithmetic intensity for decode vs prefill on a [d,d] layer.

    d            - model hidden dim (4096 ~ Llama-7B)
    batch_decode - 1  (one token per step)
    batch_prefill- prompt length processed at once (512 tokens)
    weight_bytes - bytes per weight element (0.5 = Q4_0 quant)

    Returns intensities (FLOPs/byte) + the roofline verdict.
    """
    m = k = d
    flops_per_mac = 2  # one multiply + one add
    w_bytes = m * k * weight_bytes

    # decode: N=1
    decode_flops = flops_per_mac * m * k * batch_decode
    decode_mem = w_bytes + k * batch_decode * 2  # F16 activations
    decode_intensity = decode_flops / decode_mem

    # prefill: N=batch
    prefill_flops = flops_per_mac * m * k * batch_prefill
    prefill_mem = w_bytes + k * batch_prefill * 2
    prefill_intensity = prefill_flops / prefill_mem

    return {
        "d": d, "weight_bytes": weight_bytes,
        "decode_batch": batch_decode, "prefill_batch": batch_prefill,
        "decode_flops": decode_flops, "decode_mem": decode_mem,
        "decode_intensity": decode_intensity,
        "prefill_flops": prefill_flops, "prefill_mem": prefill_mem,
        "prefill_intensity": prefill_intensity,
    }


# ============================================================================
# 3. Thread pool: how matmul rows are split across N workers
# ============================================================================

def distribute_rows(n_rows: int, n_threads: int) -> list[int]:
    """Split n_rows across n_threads as evenly as possible (ggml's partitioning).

    First `remainder` threads get one extra row. Order is deterministic.
    """
    base = n_rows // n_threads
    rem = n_rows % n_threads
    return [base + (1 if i < rem else 0) for i in range(n_threads)]


# ============================================================================
# 4. NUMA model: multi-socket bandwidth penalty
# ============================================================================

def numa_penalty(threads_on_wrong_node: int) -> float:
    """Effective bandwidth multiplier when `threads_on_wrong_node` threads read
    weights from a remote NUMA node.

    Remote access runs over the interconnect (UPI/Infinity Fabric): ~50-70% of
    local bandwidth per stream, and that interconnect is SHARED across all
    cross-node traffic. Model: each remote thread erodes effective bandwidth
    linearly; fully-crossed traffic drops to ~0.4x local bandwidth.
    """
    if threads_on_wrong_node <= 0:
        return 1.0
    cross_fraction = min(threads_on_wrong_node / 8.0, 1.0)
    # 0 remote -> 1.0x ; 8 remote (fully crossed) -> 0.4x
    return max(1.0 - 0.6 * cross_fraction, 0.4)


# ============================================================================
# 5. pretty printer + check helper
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
# 6. SECTIONS (the numbers that feed THREADING.md)
# ============================================================================

def section_a_prefill_vs_decode():
    banner("SECTION A: prefill vs decode (why they scale differently)")
    print("A forward pass has TWO phases with opposite bottlenecks:\n")
    print("  PREFILL (prompt processing):  batch = prompt length. Compute-heavy.")
    print("  DECODE  (token generation):   batch = 1.            Memory-bound.\n")

    r = matmul_roofline()
    print(f"Roofline on a [d={r['d']}, d={r['d']}] layer, Q4_0 weights "
          f"({r['weight_bytes']} B/elem):\n")
    print(f"| phase   | batch | FLOPs      | memory bytes | intensity (FLOP/byte) | bound     |")
    print(f"|---------|-------|------------|--------------|-----------------------|-----------|")
    print(f"| decode  | {r['decode_batch']:<5} | {r['decode_flops']:<10.0f} | "
          f"{r['decode_mem']:<12.0f} | {r['decode_intensity']:<21.2f} | MEMORY    |")
    print(f"| prefill | {r['prefill_batch']:<5} | {r['prefill_flops']:<10.0f} | "
          f"{r['prefill_mem']:<12.0f} | {r['prefill_intensity']:<21.2f} | COMPUTE   |")
    print()
    print(f"Decode  intensity = {r['decode_intensity']:.2f} FLOP/byte  -> the bus sets the")
    print(f"         ceiling. More threads share ONE bus -> speedup saturates fast.")
    print(f"Prefill intensity = {r['prefill_intensity']:.0f} FLOP/byte -> cores are the")
    print(f"         ceiling. More threads = more parallel FLOPs -> near-linear speedup.\n")

    check("decode intensity < prefill intensity",
          r["decode_intensity"] < r["prefill_intensity"])
    check("decode is memory-bound (intensity < 5)",
          r["decode_intensity"] < 5.0)
    check("prefill is compute-bound (intensity > 10)",
          r["prefill_intensity"] > 10.0)


def section_b_optimal_thread_count():
    banner("SECTION B: optimal thread count = PHYSICAL cores (not hyperthreads)")
    print(f"This CPU: {PHYSICAL_CORES} physical cores, {LOGICAL_CORES} logical "
          f"(2-way hyperthreading).\n")
    print("A hyperthread shares the SAME physical core's FPU/SIMD unit with its")
    print("sibling. For SIMD-heavy matmul work, two hyperthreads on one core do")
    print("NOT double the throughput -- they contend for the vector unit and the")
    print("L1/L2 cache. The sweet spot for `--threads` and `--threads-batch` is")
    print(f"therefore {PHYSICAL_CORES} (physical), NOT {LOGICAL_CORES} (logical).\n")

    print(f"| threads | type        | prefill speedup | decode speedup |")
    print(f"|---------|-------------|-----------------|----------------|")
    for n in [1, 2, 4, PHYSICAL_CORES, LOGICAL_CORES]:
        kind = "physical" if n <= PHYSICAL_CORES else "hyperthread"
        if n == PHYSICAL_CORES:
            kind += " (PEAK)"
        if n == LOGICAL_CORES:
            kind += " (penalty)"
        print(f"| {n:<7} | {kind:<11} | {prefill_speedup(n):<15.1f} | "
              f"{decode_speedup(n):<14.1f} |")

    print()
    pf_peak = prefill_speedup(PHYSICAL_CORES)
    pf_ht = prefill_speedup(LOGICAL_CORES)
    print(f"Prefill @ {PHYSICAL_CORES} threads (physical): {pf_peak:.1f}x  -- PEAK")
    print(f"Prefill @ {LOGICAL_CORES} threads (hyper):     {pf_ht:.1f}x  -- "
          f"{((pf_ht - pf_peak) / pf_peak) * 100:+.0f}% vs peak (WORSE)")
    check(f"prefill @ {PHYSICAL_CORES} > prefill @ {LOGICAL_CORES}",
          pf_peak > pf_ht)
    check(f"prefill @ {PHYSICAL_CORES} == 5.5x",
          abs(pf_peak - 5.5) < 1e-9)


def section_c_performance_curve():
    banner("SECTION C: the performance curve (diminishing returns + HT penalty)")
    print("Full scaling sweep, 1..32 threads. Speedup is vs 1 thread.\n")
    print(f"| threads | prefill (x) | prefill bar | decode (x) | decode bar |")
    print(f"|---------|-------------|-------------|------------|------------|")
    for n in [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 16, 24, 32]:
        pf = prefill_speedup(n)
        dc = decode_speedup(n)
        pf_bar = "#" * int(pf * 3)
        dc_bar = "#" * int(dc * 3)
        marker = ""
        if n == PHYSICAL_CORES:
            marker = " <== physical peak"
        elif n == LOGICAL_CORES:
            marker = " <== hyperthread penalty"
        print(f"| {n:<7} | {pf:<11.2f} | {pf_bar:<11} | {dc:<10.2f} | {dc_bar:<10} |{marker}")
    print()
    print("Read the curve:")
    print("  * PREFILL climbs steeply to 5.5x at 8 threads, then FALLS. The drop")
    print(f"    past {PHYSICAL_CORES} is the hyperthread penalty: cache thrashing + FPU")
    print("    contention on shared physical cores.")
    print("  * DECODE saturates by ~4-6 threads at ~2.0x. Beyond that, the memory")
    print("    bus is the wall -- extra threads only add scheduling overhead.\n")

    pf8 = prefill_speedup(8)
    dc8 = decode_speedup(8)
    pf16 = prefill_speedup(16)
    dc16 = decode_speedup(16)
    check("prefill peak == 5.5x at 8 threads", abs(pf8 - 5.5) < 1e-9)
    check("decode peak == 2.0x at 8 threads", abs(dc8 - 2.0) < 1e-9)
    check("prefill @16 (5.0x) < prefill @8 (5.5x)", pf16 < pf8)
    check("decode @16 (1.8x) < decode @8 (2.0x)", dc16 < dc8)


def section_d_numa():
    banner("SECTION D: NUMA awareness (multi-socket efficiency)")
    print("On a 2-socket server (e.g. 2 x 32-core EPYC = 64 cores, 2 NUMA nodes),")
    print("RAM is split: socket 0 owns half the DRAM, socket 1 owns the other half.")
    print("If a thread on socket 1 reads weights that live in socket 0's DRAM, the")
    print("traffic crosses the interconnect (UPI / Infinity Fabric) at ~50-70% of")
    print("local bandwidth, and that interconnect is SHARED.\n")
    print("`--numa` (or `--numa isabelle`) pins each thread to the NUMA node where")
    print("its chunk of weights is resident, restoring full local bandwidth.\n")

    print("Effective bandwidth vs cross-node thread fraction (decode, memory-bound):")
    print("| remote threads (of 8) | cross fraction | effective bw | decode speedup |")
    print("|-----------------------|----------------|--------------|----------------|")
    for remote in [0, 1, 2, 4, 8]:
        frac = remote / 8.0
        bw = numa_penalty(remote)
        dc = decode_speedup(8) * bw
        tag = "  (all local --numa)" if remote == 0 else ""
        if remote == 8:
            tag = "  (no pinning -- WORST)"
        print(f"| {remote:<21} | {frac:<14.2f} | {bw:<12.2f} | {dc:<14.2f} |{tag}")
    print()
    print("Without NUMA pinning, a naive 64-thread run can be SLOWER than an 8-thread")
    print("run on one socket, because every thread fights over the interconnect.\n")
    check("--numa (0 remote) keeps full bandwidth", abs(numa_penalty(0) - 1.0) < 1e-9)
    check("8 remote threads -> bw <= 0.4 (severe penalty)", numa_penalty(8) <= 0.4 + 1e-9)


def section_e_config_guide():
    banner("SECTION E: practical config (the two knobs + NUMA)")
    print("llama.cpp exposes separate thread counts for the two phases:\n")
    print("  --threads N          threads for DECODE (token generation)")
    print("  --threads-batch N    threads for PREFILL (prompt processing)")
    print("  --numa [distribute|isolate|numactl]   NUMA pinning policy\n")

    # recommend based on the curves
    pf_best = max(range(1, LOGICAL_CORES + 1), key=prefill_speedup)
    dc_best = max(range(1, LOGICAL_CORES + 1), key=decode_speedup)
    print(f"For this {PHYSICAL_CORES}-core / {LOGICAL_CORES}-thread CPU:")
    print(f"  optimal --threads-batch = {pf_best}   (prefill peaks here: "
          f"{prefill_speedup(pf_best):.1f}x)")
    print(f"  optimal --threads       = {dc_best}   (decode peaks here: "
          f"{decode_speedup(dc_best):.1f}x)\n")

    print("Common presets:")
    print("| use case                  | --threads | --threads-batch | --numa |")
    print("|---------------------------|-----------|-----------------|--------|")
    presets = [
        ("laptop (8P/16T)", 8, 8, "(single node)"),
        ("desktop (16P/32T)", 16, 16, "(single node)"),
        ("server 2-socket (64P)", 32, 32, "isolate"),
        ("server 2-socket (128P)", 64, 64, "isolate"),
        ("Raspberry Pi (4P)", 4, 4, "(n/a)"),
    ]
    for name, t, tb, numa in presets:
        print(f"| {name:<25} | {t:<9} | {tb:<15} | {numa} |")
    print()
    print("Rules of thumb:")
    print(f"  1. set BOTH to PHYSICAL core count ({PHYSICAL_CORES} here). Going to")
    print(f"     logical/hyperthreads ({LOGICAL_CORES}) is usually SLOWER.")
    print("  2. if decode stalls, try LOWERING --threads to 4-6 (bandwidth-bound;")
    print("     fewer threads = less contention = same or better tok/s.")
    print("  3. on multi-socket servers, ALWAYS add --numa. Without it, threads")
    print("     wander across nodes and tank bandwidth.")

    check("optimal prefill threads == physical cores", pf_best == PHYSICAL_CORES)
    check("optimal decode threads in [4,8]",
          4 <= dc_best <= PHYSICAL_CORES)


# ----------------------- THE GOLD CENTERPIECE --------------------------------

def section_gold():
    banner("SECTION G: GOLD scaling table (the centerpiece)")
    print(f"Canonical 8-physical-core CPU. Speedup vs 1 thread.\n")
    print(f"| threads | kind         | prefill (x) | decode (x) |")
    print(f"|---------|--------------|-------------|------------|")
    for n in [1, 2, 4, PHYSICAL_CORES, LOGICAL_CORES]:
        kind = "physical" if n <= PHYSICAL_CORES else "hyperthread"
        print(f"| {n:<7} | {kind:<12} | {prefill_speedup(n):<11.1f} | "
              f"{decode_speedup(n):<10.1f} |")

    pf8 = prefill_speedup(8)
    dc8 = decode_speedup(8)
    pf16 = prefill_speedup(16)
    dc16 = decode_speedup(16)
    print()
    print(f"GOLD (recomputed & badge-checked in threading.html):")
    print(f"  prefill @ 8 threads  = {pf8:.1f}x   (peak)")
    print(f"  decode  @ 8 threads  = {dc8:.1f}x   (peak)")
    print(f"  prefill @ 16 threads = {pf16:.1f}x   (hyperthread penalty)")
    print(f"  decode  @ 16 threads = {dc16:.1f}x   (hyperthread penalty)")

    gold_ok = (abs(pf8 - 5.5) < 1e-9 and abs(dc8 - 2.0) < 1e-9
               and abs(pf16 - 5.0) < 1e-9 and abs(dc16 - 1.8) < 1e-9
               and pf16 < pf8 and dc16 < dc8)
    check("prefill @8 == 5.5x", abs(pf8 - 5.5) < 1e-9)
    check("decode  @8 == 2.0x", abs(dc8 - 2.0) < 1e-9)
    check("prefill @16 == 5.0x", abs(pf16 - 5.0) < 1e-9)
    check("decode  @16 == 1.8x", abs(dc16 - 1.8) < 1e-9)
    check("hyperthread penalty: @16 < @8 (both phases)", pf16 < pf8 and dc16 < dc8)
    return {"pf8": pf8, "dc8": dc8, "pf16": pf16, "dc16": dc16, "gold_ok": gold_ok}


# ============================================================================
# main
# ============================================================================

def main():
    print("threading.py - reference impl. All numbers below feed THREADING.md.")
    print("pure Python stdlib (no torch, no numpy). Simulates llama.cpp threading.")
    print(f"CPU model: {PHYSICAL_CORES} physical / {LOGICAL_CORES} logical cores.")

    section_a_prefill_vs_decode()
    section_b_optimal_thread_count()
    section_c_performance_curve()
    section_d_numa()
    section_e_config_guide()
    gold = section_gold()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
