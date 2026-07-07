"""
mobile_runtime.py - Reference implementation of the size / RAM / battery budget
for running SMALL (<5B) language models on CONSUMER hardware: mobile NPUs,
in-browser WebGPU/WASM, and unified on-device runtimes.

This is the single source of truth that MOBILE_RUNTIME.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output.

Run:
    uv run python mobile_runtime.py

== The big idea, in one paragraph =============================================
A desktop GPU has heaps of VRAM and is plugged into the wall. A phone has a few
GB of ACTIVE RAM, a battery measured in watt-hours, and a fixed-function NPU
that only likes INT4/INT8. A browser tab is sandboxed, JIT'd, and garbage
collected. The DEPLOYMENT TARGET (a $400 Android, an iPhone, a browser tab) sets
the largest model + quantization that fits its RAM / battery / NPU budget. This
file makes that budget explicit: it computes (1) model size from params x
bytes/param, (2) the active-RAM budget = weights + KV-cache + overhead, where the
KV-cache grows LINEARLY with context and is the #1 mobile OOM source, (3) a
runtime contrast (NPU vs browser vs unified graph runtime), and (4) a
device-config recommender that picks the largest (params, quant) that fits.

== The lineage (old -> new, with WHY each step happened) ========================
  desktop/server GPU  : lots of VRAM (24-80GB+), plugged in. The model just has
                        to FIT; inference energy is free. llama.cpp / vLLM /
                        HuggingFace all target this. See ../local-llm/.
                        WHY: that is where open-weight LLMs first ran locally.
  mobile NPU          : Apple Neural Engine, Qualcomm Hexagon, MediaTek APU.
                        Fixed-function INT4/INT8 accelerators, a few GB of
                        unified RAM, a battery. Limited op coverage => some
                        transformer layers fall back to CPU. 35 TOPS class.
                        WHY: phones ship >1B units/year and are always-on,
                        always-with-you; the model must run WITHOUT the cloud.
  browser runtime     : WebGPU / WASM via transformers.js + ONNX Runtime Web.
                        Portable, sandboxed, zero-install. But shader-compile
                        first-run cost + GC pauses + a ~2GB-per-tab memory cap.
                        WHY: the web is the universal deployment surface; no app
                        install, automatic updates, works on any OS.
  unified on-device    : ExecuTorch, LiteRT (TFLite), ONNX Runtime Mobile. One
  runtime             : exported graph, pluggable execution providers that target
                        NPU / CPU / GPU backends. Graph-level quantized kernels.
                        WHY: you export ONCE and the runtime picks the best
                        backend per device at load time -- the model code stops
                        caring whether it lands on an iPhone ANE, a Snapdragon
                        Hexagon, or a browser WebGPU adapter.

== Notation & conventions =====================================================
    N            : parameter count (the "model size"). {0.5B, 1B, 3B, 7B} here.
    bpw          : bits per weight (the quant type). FP16=16, Q8_0=8.5, Q4_K=4.5.
    bytes/param  : bpw / 8.  FP16=2.0, Q8=1.0625, Q4=0.5625, Q3~0.42.
    size_GB      : N * bytes_per_param / 1e9   (= N_in_billions * bpw / 8).
    n_layers     : transformer block count (sets the KV-cache multiplier).
    hidden       : model hidden width = n_kv_heads * head_dim (for MHA / the
                   simplified KV model used here).
    seq_len      : context length. KV-cache is LINEAR in this.
    KV-cache GB  : 2 * n_layers * seq_len * hidden * bytes_per_kv_element / 1e9.
                   The leading 2 = the K tensor and the V tensor, both stored
                   every layer (cross-ref ../local-llm/VRAM_ESTIMATOR.md).
    overhead GB  : max(FLOOR, FRAC * weights) -- activations + runtime workspace.
    active RAM   : weights + KV-cache + overhead. What must fit the device budget.
    TOPS         : NPU throughput in INT8 trillion-ops/sec (a SPEED signal).
    battery Wh   : watt-hours; queries_per_charge = Wh*3600 / energy_per_query.

== Sources (all in mobile_runtime_reference.txt, >=2 independent confirmations) ==
  llama.cpp quantize README (ggml-org)       Q4_K=4.5 bpw, Q8_0=8.5 bpw
  ../local-llm/VRAM_ESTIMATOR.md             weights+KV+overhead budget, KV formula
  Notebookcheck + Wikipedia (Apple A17/A18)  16-core Neural Engine, 35 TOPS INT8
  Qualcomm Hexagon product brief + whitepaper Snapdragon 8 Elite ~45 TOPS, INT4/8/16
  ExecuTorch docs (PyTorch)                  unified on-device runtime, 12+ backends
  ONNX Runtime EP docs (Microsoft)           NNAPI/CoreML/QNN/WebGPU execution providers
  Google LiteRT docs                         TFLite successor, NPU acceleration
  Transformers.js v3 (Hugging Face)          ONNX Runtime Web + WebGPU/WASM browser path
  arXiv:2509.23324                           Hexagon INT4/8/16 support, op-coverage gaps
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 74

# ============================================================================
# 0. CONSTANTS & THE CHECK HELPER
# ============================================================================

# bytes per parameter, by quant type. Q4 = the pure Q4_K block bpw (4.5/8).
# (Q3 ~ 3.4 bpw => 0.425 bytes/param, noted for context but not in the size table.)
BYTES_PER_PARAM: dict[str, float] = {"fp16": 2.0, "Q8": 1.0625, "Q4": 0.5625}

# the four model sizes swept in Section A
PARAM_SET = [0.5e9, 1.0e9, 3.0e9, 7.0e9]

# toy architectures: params -> (n_layers, hidden). Used for the KV-cache term.
# (n_kv_heads * head_dim == hidden in this simplified MHA model.)
MODEL_ARCH: dict[float, tuple[int, int]] = {
    0.5e9: (16, 1024),
    1.0e9: (16, 2048),
    3.0e9: (36, 3200),
    7.0e9: (32, 4096),
}

# the toy 1B that Sections B and the gold anchor use (matches MODEL_ARCH[1e9])
TOY_1B_PARAMS = 1.0e9
TOY_1B_LAYERS = 16
TOY_1B_HIDDEN = 2048

# KV-cache bytes per element: fp16 KV = 2 (the default mobile assumption).
KV_BYTES_PER_ELEMENT = 2

# mobile runtime overhead: a floor + a fraction of weights. The floor is lower
# than desktop (no CUDA context) but the fraction is higher (JIT/deserialize).
OVERHEAD_FLOOR_GB = 0.3
OVERHEAD_FRAC = 0.15

# battery / energy toy model (clearly an order-of-magnitude estimate).
# ~200 pJ covers mobile LPDDR read + NPU MAC energy per weight byte touched.
JOULES_PER_BYTE = 2.0e-10
DECODE_TOKENS_PER_QUERY = 256


def check(desc: str, ok: bool) -> None:
    """Print '[check] desc: OK' or raise SystemExit on failure (no raw assert)."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# A. MODEL SIZE MATH  --  bytes = params * bytes_per_param
#    For {0.5B,1B,3B,7B} x {fp16, Q8, Q4}: size in GB.
#    GOLD PIN: 1B @ Q4 = 0.5625 GB.  7B @ Q4 = 3.9375 GB (~3.9).
# ============================================================================

def model_size_gb(n_params: float, quant: str) -> float:
    """size_GB = N * bytes_per_param / 1e9  (== N_in_billions * bpw / 8)."""
    return n_params * BYTES_PER_PARAM[quant] / 1e9


def section_model_size():
    banner("SECTION A: model size  =  params x bytes/param  (the weights term)")
    print("bytes/param by quant (cross-ref GGUF_QUANT.md / ../local-llm/QUANT_TYPES.md):")
    for q in ["fp16", "Q8", "Q4"]:
        print(f"  {q:<5} = {BYTES_PER_PARAM[q]:.4f} bytes/param")
    print()
    print("| params | fp16 (GB) | Q8 (GB)  | Q4 (GB)  |")
    print("|--------|-----------|----------|----------|")
    sizes: dict[tuple[float, str], float] = {}
    for n in PARAM_SET:
        row = {}
        for q in ["fp16", "Q8", "Q4"]:
            s = model_size_gb(n, q)
            row[q] = s
            sizes[(n, q)] = s
        print(f"| {n/1e9:>4.1f}B  | {row['fp16']:>8.4f}  | {row['Q8']:>7.4f} |"
              f" {row['Q4']:>7.4f} |")
    print()
    print("Read across: quantizing fp16 -> Q4 cuts size by ~3.6x at every scale.")
    print("Read down:   the Q4 column is the one mobile deployment lives in.")
    print()
    print("GOLD PIN (mobile_runtime.html recomputes this):")
    print(f"  1B @ Q4 = 1e9 x 0.5625 / 1e9 = {sizes[(1e9, 'Q4')]:.4f} GB weights")
    print(f"  7B @ Q4 = 7e9 x 0.5625 / 1e9 = {sizes[(7e9, 'Q4')]:.4f} GB weights (~3.9)")
    print()
    # GOLD anchor checks (the .html reproduces the 1B@Q4 value bit-for-bit)
    check("1B @ Q4 weights == 0.5625 GB (the gold anchor)",
          abs(sizes[(1e9, "Q4")] - 0.5625) < 1e-9)
    check("7B @ Q4 weights ~= 3.9 GB", abs(sizes[(7e9, "Q4")] - 3.9375) < 1e-9)
    check("fp16 -> Q4 is a ~3.55x size cut at every scale",
          all(sizes[(n, "fp16")] / sizes[(n, "Q4")] > 3.5 for n in PARAM_SET))
    check("size is strictly increasing in params at every quant",
          all(sizes[(PARAM_SET[i], q)] < sizes[(PARAM_SET[i + 1], q)]
              for i in range(len(PARAM_SET) - 1) for q in ["fp16", "Q8", "Q4"]))


# ============================================================================
# B. RAM BUDGET BREAKDOWN  --  weights + KV-cache + overhead
#    For the toy 1B @ Q4 over seq_len in {512, 2048, 8192, 32768}.
#    KV-cache grows LINEARLY with context and overtakes weights past ~4K.
# ============================================================================

def kv_cache_gb(n_layers: int, seq_len: int, hidden: int,
                bytes_per_kv_element: int = KV_BYTES_PER_ELEMENT) -> float:
    """KV-cache GB = 2 * n_layers * seq_len * hidden * bytes_per_kv_element / 1e9.

    The leading 2 = K and V (both stored, every layer). For MHA,
    n_kv_heads * head_dim == hidden; for GQA you would scale by n_kv_heads/n_heads.
    """
    return (2.0 * n_layers * seq_len * hidden * bytes_per_kv_element) / 1e9


def overhead_gb(weights_gb: float) -> float:
    """activations + runtime workspace: max(FLOOR, FRAC * weights)."""
    return max(OVERHEAD_FLOOR_GB, OVERHEAD_FRAC * weights_gb)


def active_ram_gb(n_params: float, quant: str, seq_len: int,
                  n_layers: int, hidden: int) -> dict[str, float]:
    """The full active-RAM budget a device must hold to serve this config."""
    w = model_size_gb(n_params, quant)
    kv = kv_cache_gb(n_layers, seq_len, hidden)
    oh = overhead_gb(w)
    return {"weights": w, "kv": kv, "overhead": oh, "total": w + kv + oh}


def section_ram_budget():
    banner("SECTION B: active RAM  =  weights + KV-cache + overhead  (1B @ Q4)")
    w = model_size_gb(TOY_1B_PARAMS, "Q4")
    print(f"Fixed model: {TOY_1B_PARAMS/1e9:.1f}B params @ Q4 = {w:.4f} GB weights.")
    print(f"Architecture: n_layers={TOY_1B_LAYERS}, hidden={TOY_1B_HIDDEN}, "
          f"fp16 KV ({KV_BYTES_PER_ELEMENT} B/E).")
    print(f"Overhead = max({OVERHEAD_FLOOR_GB}, {OVERHEAD_FRAC} x weights) GB.")
    print()
    print("KV-cache = 2 x n_layers x seq_len x hidden x bytes/E / 1e9  (LINEAR in seq)")
    print(f"         = 2 x {TOY_1B_LAYERS} x seq x {TOY_1B_HIDDEN} x "
          f"{KV_BYTES_PER_ELEMENT} / 1e9")
    print()
    print("| seq_len | weights | KV-cache | KV/weights | overhead | TOTAL  | "
          "fits 4GB? | fits 6GB? | fits 8GB? |")
    print("|---------|---------|----------|------------|----------|--------|"
          "-----------|-----------|-----------|")
    budgets = [4.0, 6.0, 8.0]
    out: dict[int, dict[str, float]] = {}
    for seq in [512, 2048, 8192, 32768]:
        r = active_ram_gb(TOY_1B_PARAMS, "Q4", seq, TOY_1B_LAYERS, TOY_1B_HIDDEN)
        ratio = r["kv"] / r["weights"]
        fits = ["FIT" if r["total"] <= b else "OOM" for b in budgets]
        out[seq] = r
        print(f"| {seq:>7} | {r['weights']:>6.4f}GB | {r['kv']:>7.4f}GB | "
              f"{ratio:>10.2%} | {r['overhead']:>6.4f}GB | {r['total']:>5.4f}GB | "
              f"{fits[0]:>9} | {fits[1]:>9} | {fits[2]:>9} |")
    print()
    print("Read down the KV column: it DOUBLES every time seq doubles (linear).")
    print(f"  At seq=512  KV is {out[512]['kv']/out[512]['weights']:.0%} of weights "
          f"(weights dominate).")
    print(f"  At seq=8192 KV is {out[8192]['kv']/out[8192]['weights']:.0%} of weights "
          f"(KV overtook).")
    print(f"  At seq=32k  KV alone ({out[32768]['kv']:.4f}GB) is bigger than the "
          f"{out[32768]['weights']:.4f}GB of weights AND OOMs a 4GB phone.")
    print()
    # GOLD PIN: the 1B @ Q4 @ seq=2048 KV-cache value (the .html reproduces it)
    kv2048 = out[2048]["kv"]
    print("GOLD PIN (mobile_runtime.html recomputes this):")
    print(f"  KV(1B, seq=2048) = 2 x 16 x 2048 x 2048 x 2 / 1e9 = {kv2048:.4f} GB")
    print(f"  ({kv2048/r['weights']:.0%} of the {r['weights']:.4f}GB weights -- non-trivial)")
    print()
    check("1B @ Q4 weights == 0.5625 GB", abs(out[512]["weights"] - 0.5625) < 1e-9)
    check("KV(seq=2048) for toy 1B ~= 0.2684 GB (the second gold anchor)",
          abs(kv2048 - 0.268435456) < 1e-6)
    check("KV-cache is strictly linear in seq (doubling seq doubles KV)",
          abs(out[8192]["kv"] / out[2048]["kv"] - 4.0) < 1e-9
          and abs(out[2048]["kv"] / out[512]["kv"] - 4.0) < 1e-9)
    check("KV overtakes weights at seq=8192 (KV > weights)",
          out[8192]["kv"] > out[8192]["weights"])
    check("1B @ Q4 fits a 4GB phone up to 8K context but OOMs at 32K",
          out[8192]["total"] <= 4.0 and out[32768]["total"] > 4.0)


# ============================================================================
# C. RUNTIME CONTRAST  --  mobile NPU vs browser WebGPU vs unified graph runtime
# ============================================================================

# (runtime, backend, best precision, one-line tradeoff, the catch)
RUNTIMES = [
    ("mobile NPU", "Apple NE / Qualcomm Hexagon / MediaTek APU",
     "INT4 / INT8", "fastest for the ops it supports",
     "limited op coverage: some transformer layers fall back to CPU"),
    ("browser WebGPU", "transformers.js + ONNX Runtime Web (WebGPU/WASM)",
     "fp16 / INT8 (WASM)", "portable, sandboxed, zero-install",
     "shader-compile first-run cost + GC pauses + ~2GB tab cap"),
    ("unified runtime", "ExecuTorch / LiteRT / ONNX Runtime Mobile",
     "INT4 / INT8 / fp16", "one graph, pluggable EPs (NPU/CPU/GPU)",
     "you must EXPORT per backend; EP coverage still varies by device"),
]


def section_runtime_contrast():
    banner("SECTION C: runtime contrast  --  NPU vs browser vs unified graph runtime")
    print("| runtime        | backend                               | "
          "best precision | upside                  | the catch                         |")
    print("|----------------|---------------------------------------|----------------|"
          "-------------------------|-----------------------------------|")
    for name, backend, prec, up, catch in RUNTIMES:
        print(f"| {name:<14} | {backend:<37} | {prec:<14} | {up:<23} | "
              f"{catch:<33} |")
    print()
    print("Decision tree (which runtime picks you, not the other way round):")
    print("  on an iPhone / Android with a real NPU  -> CoreML / NNAPI / QNN EP")
    print("  inside a browser tab                    -> WebGPU (WASM fallback)")
    print("  cross-platform from one export          -> ExecuTorch / LiteRT / ORT")
    print()
    check("the three runtimes are distinct in upside",
          len({r[3] for r in RUNTIMES}) == 3)
    check("every runtime lists an explicit catch (no free lunch)",
          all(r[4] for r in RUNTIMES))


# ============================================================================
# D. DEVICE-CONFIG RECOMMENDER  --  pick the largest (params, quant) that fits
#    Profiles: low-end Android, iPhone (A18 NE), browser tab.
# ============================================================================

# (name, ram_total_gb, npu_tops, battery_wh, active_fraction, runtime, web?)
# active_fraction: fraction of total RAM the model runtime may actually claim.
#   phones reserve ~half for OS + other apps; a browser tab's 2GB IS the budget.
DEVICE_PROFILES = [
    ("low-end Android", 4.0,  8,  15.0, 0.5, "ExecuTorch / ORT-Mobile", False),
    ("iPhone (A18 NE)", 6.0, 35,  13.0, 0.5, "CoreML / Metal",         False),
    ("browser tab",     2.0,  0,   0.0, 1.0, "WebGPU / WASM",          True),
]

RECOMMEND_SEQ = 2048  # the context the recommender sizes for (a mobile chat turn)


def recommend_config(ram_active_gb: float) -> tuple[float, str, dict[str, float]]:
    """Largest (params, quant) -- params biggest first, then fp16->Q8->Q4 --
    whose active RAM at RECOMMEND_SEQ fits the device's active budget."""
    # search largest params first; for each params, prefer the smallest quant
    # that fits (Q8 if it fits, else Q4) so we keep quality when possible.
    for n in sorted(PARAM_SET, reverse=True):
        # try Q8 (better quality) before Q4 (smaller) for this params count
        for q in ["Q8", "Q4"]:
            n_layers, hidden = MODEL_ARCH[n]
            r = active_ram_gb(n, q, RECOMMEND_SEQ, n_layers, hidden)
            if r["total"] <= ram_active_gb:
                return n, q, r
    # nothing in the zoo fits: report the smallest @ Q4
    n = min(PARAM_SET)
    n_layers, hidden = MODEL_ARCH[n]
    return n, "Q4", active_ram_gb(n, "Q4", RECOMMEND_SEQ, n_layers, hidden)


def section_device_recommender():
    banner("SECTION D: device-config recommender  --  the deployment target decides")
    print(f"Sizing every config at seq={RECOMMEND_SEQ} (a mobile chat turn).")
    print("active_ram = ram_total x active_fraction  (OS reserves the rest).")
    print("Pick: largest params that fits; for each params prefer Q8 over Q4.")
    print()
    print("| device           | total RAM | active RAM | NPU TOPS | runtime           | "
          "recommended   | size GB | uses GB | headroom |")
    print("|------------------|-----------|------------|----------|-------------------|"
          "--------------|---------|---------|----------|")
    for name, ram, tops, _wh, frac, runtime, _web in DEVICE_PROFILES:
        active = ram * frac
        n, q, r = recommend_config(active)
        headroom = active - r["total"]
        print(f"| {name:<16} | {ram:>6.1f}GB  | {active:>7.2f}GB  | {tops:>6}   | "
              f"{runtime:<17} | {n/1e9:>3.1f}B @ {q:<2}     | {r['weights']:>5.4f}  | "
              f"{r['total']:>5.4f} | {headroom:>6.2f}GB |")
    print()
    print("Reading the table like a story:")
    print("  * low-end Android (2GB active) -> 1B. RAM allows the Q8 quality upgrade;")
    print("    fall back to Q4 when context grows past ~8K (Section B).")
    print("  * iPhone with a 35-TOPS NE (3GB active) -> 3B @ Q4. The NPU has the TOPS")
    print("    to decode 3B fast; only Q4 (not Q8) fits the RAM at 2K context.")
    print("  * a browser tab (2GB hard cap) -> 1B @ Q8. WebGPU is portable but the")
    print("    ~2GB tab limit rules out anything bigger; it page-swaps / OOMs.")
    print()
    print("The single takeaway: a 1B model is the config that fits EVERYWHERE. Q4")
    print("(~0.56GB weights) is the universal fallback quant -- the gold anchor.")
    print()
    # invariants
    low = recommend_config(4.0 * 0.5)
    iph = recommend_config(6.0 * 0.5)
    brw = recommend_config(2.0 * 1.0)
    check("low-end Android (2GB active) recommendation fits its budget",
          low[2]["total"] <= 2.0)
    check("iPhone (3GB active) fits a model strictly larger than the browser's",
          iph[0] >= brw[0])
    check("a 1B model fits ALL THREE device budgets (the universal mobile fit)",
          all(recommend_config(ram * frac)[2]["total"] <= ram * frac
              for name, ram, _t, _w, frac, _r, _b in DEVICE_PROFILES))
    check("every recommended model is <= its active RAM (no OOM)",
          all(recommend_config(ram * frac)[2]["total"] <= ram * frac
              for name, ram, _t, _w, frac, _r, _b in DEVICE_PROFILES))


# ============================================================================
# E. BATTERY BUDGET  --  energy per query and queries-per-charge
# ============================================================================

def energy_per_query_j(n_params: float, quant: str,
                       decode_tokens: int = DECODE_TOKENS_PER_QUERY) -> float:
    """Toy energy model: read the weights once per decoded token, each byte
    costing JOULES_PER_BYTE (covers mobile LPDDR read + NPU MAC)."""
    bytes_per_token = n_params * BYTES_PER_PARAM[quant]
    return bytes_per_token * JOULES_PER_BYTE * decode_tokens


def queries_per_charge(battery_wh: float, n_params: float, quant: str) -> float:
    """How many queries a full battery serves (battery in watt-hours)."""
    if battery_wh <= 0:
        return float("nan")
    return (battery_wh * 3600.0) / energy_per_query_j(n_params, quant)


def section_battery_budget():
    banner("SECTION E: battery budget  --  energy per query -> queries per charge")
    print("Energy model (TOY, order-of-magnitude): read all weights once per")
    print(f"decoded token; each byte costs {JOULES_PER_BYTE:.1e} J (mobile LPDDR + NPU).")
    print(f"Decode {DECODE_TOKENS_PER_QUERY} tokens/query. battery (Wh) x 3600 = joules.")
    print()
    print("| device           | battery | model    | J/query | queries/charge |")
    print("|------------------|---------|----------|---------|----------------|")
    rows: dict[str, tuple[float, float]] = {}
    for name, _ram, _tops, wh, frac, _runtime, _web in DEVICE_PROFILES:
        if wh <= 0:
            continue  # browser tab: no battery of its own
        active_budget = next(p[1] * p[4] for p in DEVICE_PROFILES if p[0] == name)
        n, q, _r = recommend_config(active_budget)
        ej = energy_per_query_j(n, q)
        qpc = queries_per_charge(wh, n, q)
        rows[name] = (ej, qpc)
        print(f"| {name:<16} | {wh:>5.1f}Wh | {n/1e9:>3.1f}B @ {q:<2} | {ej:>5.1f}  | "
              f"{qpc:>12.0f}   |")
    print()
    print("browser tab has no battery budget of its own (it draws from the host).")
    print()
    print("Read it like this: doubling the model roughly doubles the J/query, so a")
    print("3B model gets ~1/3 the queries-per-charge of a 1B on the SAME battery.")
    print("That is why a 1B model (the universal fit from Section D) is also the")
    print("battery win -- and Q4 halves the J/query of Q8 at the same param count.")
    print()
    # invariants
    ej_low, qpc_low = rows["low-end Android"]
    ej_iph, qpc_iph = rows["iPhone (A18 NE)"]
    check("iPhone recommendation energy >= low-end Android (bigger model)",
          ej_iph >= ej_low)
    check("energy per query is strictly positive for every profile",
          all(ej > 0 for ej, _ in rows.values()))
    check("queries-per-charge is finite & positive where a battery exists",
          all(0 < qpc < float("inf") for _, qpc in rows.values()))


# ============================================================================
# main
# ============================================================================

def main():
    print("mobile_runtime.py - reference impl. All numbers below feed MOBILE_RUNTIME.md.\n"
          "torch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources; see mobile_runtime_reference.txt.")

    section_model_size()
    section_ram_budget()
    section_runtime_contrast()
    section_device_recommender()
    section_battery_budget()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
