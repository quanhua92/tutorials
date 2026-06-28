# GPU Offload (`-ngl`) — split the layer stack across GPU and CPU

> Companion: [gpu_offload.py](https://github.com/quanhua92/tutorials/blob/main/local-llm/gpu_offload.py)
> Live: [gpu_offload.html](./gpu_offload.html)

## 0. TL;DR

A Transformer is a **stack of identical layers** (Llama-3-8B = 32). llama.cpp's
`-ngl N` (**n-gpu-layers**) flag puts the **first N layers on the GPU** (weights
loaded into VRAM once, attention+MLP computed by GPU kernels) and leaves the
**remaining L-N layers on the CPU** (weights in RAM or mmap'd, computed by SIMD
threads). At the single seam between the two blocks, one **activation** tensor is
copied across the PCIe bus (or Apple's unified-memory fabric).

**The one formula to remember:**

```
VRAM_used = weight_per_layer * ngl  +  kv_cache(ctx)  +  runtime_overhead
ngl       = min( floor((gpu_vram - overhead - kv) / weight_per_layer), n_layers )
```

**The key insight:** the thing that crosses the seam every token is the
**activation, not the weights**. For decode (batch=1) that activation is
**8 KiB** — negligible next to the ~145 MiB of weights per layer that move *once*.
So partial offload's bottleneck is the **CPU compute** on the non-offloaded layers,
not the copy. More GPU layers ⇒ fewer CPU layers in the hot path ⇒ faster decode.

**Gold (verified, `[check: OK]` in the `.py` and `.html`):** Llama-3-8B **Q4_K_M**,
**8 GiB** GPU, **4096** ctx → weights **4.52** + KV **0.50** + overhead **0.50** =
**5.52 GiB < 8 GiB** ⇒ **all 32 layers fit** (`-ngl 32`).

---

## 1. What it is (lineage old → new, WHY each step)

```mermaid
graph LR
    C["ALL-CPU  -ngl 0<br/>every layer on CPU<br/>DDR-bandwidth-bound ~9 tok/s"] -->|offload N| P["PARTIAL OFFLOAD  -ngl N<br/>N layers GPU, L-N CPU<br/>one activation crosses the seam"]
    P -->|N = L| F["FULL OFFLOAD  -ngl 999<br/>every layer on GPU<br/>VRAM-bandwidth-bound ~95 tok/s"]
    style C fill:#3a1414,stroke:#c0392b,color:#fff
    style P fill:#3a2a1a,stroke:#e67e22,color:#fff
    style F fill:#1c3a25,stroke:#27ae60,color:#fff
```

| Step | Problem it fixes | What changes |
|---|---|---|
| **1. ALL-CPU (`-ngl 0`)** | — (the origin) | Every layer runs on the CPU. Weights stream from RAM through AVX2/AVX512/NEON. Correct but slow: DDR (~50 GB/s) vs GPU HBM (~1 TB/s). Llama-8B Q4 ≈ 8–12 tok/s |
| **2. PARTIAL (`-ngl N`)** | CPU is the bottleneck | First N layers go to the GPU. Weights move to VRAM **once** at load. Only a tiny activation crosses the seam per token. Each offloaded layer removes one CPU-bound layer from the hot path |
| **3. FULL (`-ngl 999`)** | The remaining CPU layers still cap decode | All layers on the GPU. No CPU layer, no PCIe crossing in the hot path. Decode is now pure VRAM-bandwidth-bound (the ideal) |

**Why it matters:** decode is **memory-bandwidth-bound, not compute-bound**. Moving a
layer from CPU (DDR) to GPU (HBM) raises that layer's bandwidth ~20×, so tok/s
climbs roughly linearly with `ngl` until the model is fully offloaded — then it
**flattens** (extra GPU layers can't help once no CPU layer remains).

---

## 2. The mechanism (internals)

### 2a. The layer split

The model is `L` layers numbered `0..L-1`. `-ngl N` makes `ggml_backend_sched`
assign layers `0..N-1` to the GPU backend (ggml-cuda / ggml-metal / ggml-vulkan)
and layers `N..L-1` to ggml-cpu. It inserts a single `CPY` (copy) node at the seam.

> From gpu_offload.py Section A:
> ```
> | -ngl | GPU layers (0..N-1) | CPU layers (N..31) | boundary at | mode        |
> |------|---------------------|----------------------|-------------|-------------|
> | 0    | (none)              | 0..31                | -           | ALL-CPU     |
> | 8    | 0..7                | 8..31                | after L7    | PARTIAL     |
> | 16   | 0..15               | 16..31               | after L15   | PARTIAL     |
> | 24   | 0..23               | 24..31               | after L23   | PARTIAL     |
> | 32   | 0..31               | (none)               | none        | FULL OFFLOAD |
> 
> Layer visual for -ngl 16 of 32 (G = GPU, . = CPU):
>   L00 [GGGGGGGGGGGGGGGG................] L31
>   GPU: layers 0-15   |   CPU: layers 16-31   |   seam: after L15
> ```

### 2b. VRAM budget per layer

Each offloaded layer parks its weights (attention + MLP) in VRAM. The budget is:

```
VRAM_used = weight_per_layer * ngl  +  kv_cache(ctx)  +  runtime_overhead
```

`weight_per_layer = WEIGHT_GIB[quant] / n_layers`. For Llama-3-8B:

> From gpu_offload.py Section B:
> ```
> | quant  | total weights | per layer | layers in 8GiB* | layers in 16GiB* |
> |--------|---------------|-----------|-----------------|------------------|
> | FP16   |       15.00 GiB |  0.469   |       16/32       |        32/32        |
> | Q8_0   |        7.90 GiB |  0.247   |       30/32       |        32/32        |
> | Q5_K_M |        5.70 GiB |  0.178   |       32/32       |        32/32        |
> | Q4_K_M |        4.52 GiB |  0.141   |       32/32       |        32/32        | <-- GOLD
> | Q4_0   |        4.30 GiB |  0.134   |       32/32       |        32/32        |
> * weights-only ceiling (gpu - overhead, KV not yet counted).
> ```
> At Q4_K_M, ~145 MiB/layer is tiny: an 8 GiB card has room for ~49 layers, but the
> model only HAS 32. **Weights fit easily — the real constraint is the KV cache at
> long context.**

### 2c. The activation transfer bottleneck

The seam copy is an **activation**, not a weight. Its size is

```
activation = batch * seq_len * dim * bytes_per_element
```

> From gpu_offload.py Section C:
> ```
> | phase   | batch | seq_len | dim  | bytes  | human   |
> |---------|-------|---------|------|--------|---------|
> | decode  |   1   |    1    | 4096 |   8192 | 8 KiB   |
> | prefill |   1   |  1024   | 4096 | 8388608| 8 MiB   |
> 
> weight per layer (Q4_K_M) = 145 MiB  (151,666,032 bytes)
>   -> a layer's weights are 18514x bigger than one decode activation.
> Bidirectional seam crossing (activation IN + activation OUT):
>   decode round-trip  = 16 KiB/token   (negligible vs DDR/HBM bw)
>   prefill round-trip = 16 MiB/batch   (still small next to weights)
> [check] decode activation == 8192 B (8 KiB): True -> OK
> [check] prefill(1024) activation == 8 MiB: True -> OK
> ```

**Consequence:** partial offload's runtime cost is the **CPU compute** on the
`L-ngl` non-offloaded layers — the seam copy is rounding error against DDR/HBM
bandwidth. This is why `-ngl 16` on an 8 GiB card is *much* faster than `-ngl 0`,
and `-ngl 32` is faster still, but the curve flattens once full offload is reached.

---

## 3. Practical config / commands

### The flag

```bash
# exact layer count
./llama-server -m model.gguf -ngl 32

# offload as many as possible (modern llama.cpp reads 'auto' by default)
./llama-server -m model.gguf -ngl 99          # legacy "offload everything"
./llama-server -m model.gguf -ngl all         # current literal
./llama-server -m model.gguf --n-gpu-layers 32

# let llama.cpp size it for you (default since 2025)
./llama-server -m model.gguf -ngl auto --fit on
```

Official doc (`tools/server/README.md`): *"`-ngl, --gpu-layers, --n-gpu-layers N`
— max. number of layers to store in VRAM, either an exact number, 'auto', or 'all'
(default: auto)."*

### Related multi-GPU / split flags

| Flag | What it does |
|---|---|
| `-sm, --split-mode {none,layer,row,tensor}` | how to split across multiple GPUs (default `layer` = pipelined) |
| `-ts, --tensor-split N0,N1,...` | fraction of the model per GPU, e.g. `3,1` |
| `-mg, --main-gpu INDEX` | which GPU holds intermediate results + KV (row split) |
| `-fit, --fit [on\|off]` | auto-shrink unset args (ctx, ngl) to fit device memory |
| `-ot, --override-tensor pat=buf` | pin a tensor pattern to a buffer (e.g. MoE experts to CPU) |
| `-cmoe, --cpu-moe` | keep all MoE expert weights on CPU (the ktransformers trick) |

### The decision recipe (3 steps)

```
1. kv     = KV_cache(ctx, dtype)                 # grows with context
2. avail  = gpu_vram - runtime_overhead - kv      # budget for weights
3. ngl    = min( floor(avail / weight_per_layer), n_layers )
```

---

## 4. Worked example (the gold centerpiece)

> From gpu_offload.py Section G:
> ```
> Canonical plan: Llama-3-8B, Q4_K_M, 8 GiB GPU, 4096 ctx, f16 KV.
> 
>   weights (Q4_K_M, all 32) =  4.52 GiB   (0.1412 GiB/layer)
>   KV cache @ 4096 (f16)     =  0.50 GiB   (128 KiB/token)
>   runtime overhead         =  0.50 GiB
>   -------------------------------------------
>   TOTAL VRAM               =  5.52 GiB   (GPU = 8 GiB)
> 
>   avail for weights = 8 - 0.50 - 0.50 = 7.00 GiB
>   max layers        = floor(7.00 / 0.1412) = 49  (model has 32)
>   -> ngl            = min(49, 32) = 32
>   verdict           = ALL 32 layers on GPU  ->  -ngl 32 (or -ngl 999)
> 
>   headroom          = 8 - 5.52 = 2.48 GiB
> [check] total VRAM == 5.52 GiB: True -> OK
> [check] ngl == 32 (ALL layers offloaded): True -> OK
> [check] model fits in 8 GiB (total < gpu): True -> OK
> [check] headroom == 2.48 GiB: True -> OK
> ```

### Decision tree across configs

> From gpu_offload.py Section D:
> ```
> | gpu    | quant  |  ctx  | KV (GiB) | avail | ngl | total | verdict
> |--------|--------|-------|----------|-------|-----|-------|---------------------------
> | 8 GiB  | Q4_K_M |  4096 |    0.50  |  7.00 |  32 |  5.52 | ALL 32 -> -ngl 32
> | 8 GiB  | Q4_K_M | 32768 |    4.00  |  3.50 |  24 |  7.89 | 24/32 GPU, 8 CPU
> | 8 GiB  | Q8_0   |  4096 |    0.50  |  7.00 |  28 |  7.91 | 28/32 GPU, 4 CPU
> | 12 GiB | Q4_K_M |  8192 |    1.00  | 10.50 |  32 |  6.02 | ALL 32 -> -ngl 32
> ```

### Decode-speed curve (illustrative)

> From gpu_offload.py Section D:
> ```
> | -ngl | % on GPU | decode tok/s | gain over CPU-only |
> |------|----------|--------------|--------------------|
> |    0 |       0% |        9.0   | +  0.0             |
> |    8 |      25% |       30.5   | + 21.5             |
> |   16 |      50% |       52.0   | + 43.0             |
> |   24 |      75% |       73.5   | + 64.5             |
> |   32 |     100% |       95.0   | + 86.0  <- FULL OFFLOAD plateau |
> ```
> ~linear in `ngl`, then **flat**: once the last CPU layer is gone, decode is
> VRAM-bandwidth-bound and more GPU layers cannot help.

### Practical configs sweep

> From gpu_offload.py Section E:
> ```
> | GPU   | quant  |   ctx | KV    | weights(GPU) | ngl   | total  | fit? |
> |-------|--------|-------|-------|--------------|-------|--------|------|
> |    8  | Q4_K_M |  4096 | 0.50  |       4.52   | 32/32 |  5.52  | YES  |
> |    8  | Q4_K_M | 32768 | 4.00  |       3.39   | 24/32 |  7.89  | no   |
> |    8  | Q8_0   |  4096 | 0.50  |       6.91   | 28/32 |  7.91  | no   |
> |   12  | Q4_K_M |  8192 | 1.00  |       4.52   | 32/32 |  6.02  | YES  |
> |   12  | Q8_0   |  8192 | 1.00  |       7.90   | 32/32 |  9.40  | YES  |
> |   16  | Q8_0   | 16384 | 2.00  |       7.90   | 32/32 | 10.40  | YES  |
> |   16  | Q4_K_M | 32768 | 4.00  |       4.52   | 32/32 |  9.02  | YES  |
> |   24  | FP16   |  8192 | 1.00  |      15.00   | 32/32 | 16.50  | YES  |
> |   24  | Q4_K_M | 65536 | 8.00  |       4.52   | 32/32 | 13.02  | YES  |
> ```

---

## 5. Pitfalls (trap | symptom | fix)

| Trap | Symptom | Fix |
|---|---|---|
| **"It loads but feels slow"** | high TTFT, weak decode despite `-ngl 99` | Some layers silently fell back to CPU (VRAM hit the cliff). Watch `nvidia-smi`; lower `-ngl` until stable, or quantize KV |
| **Ignoring the KV term** | model fits at 4K, OOMs at 32K | KV grows linearly with ctx (128 KiB/token f16 for Llama-3-8B). Budget it: `total = weights + kv(ctx) + overhead` |
| **`-ngl` larger than the model** | harmless but misleading | `-ngl 999` is clamped to `n_layers`. Use `all`/`auto` for clarity |
| **Setting `-ngl` without `-c`** | auto-sizing picks a tiny ctx or 0 | `-ngl auto` + `-c N` together; `--fit on` reconciles them |
| **Thinking the seam copy is the bottleneck** | over-engineering activation layout | For decode it is 8 KiB — rounding error. The real cost is the CPU layers. Offload more, don't optimize the copy |
| **MoE: every expert is a "layer weight"** | `-ngl N` offloads attention but experts blow up VRAM | Use `-cmoe` / `-ot 'blk\..*\.exp_.*=CPU'` to keep experts on CPU (ktransformers pattern); GPU keeps shared attention |
| **Multi-GPU default is `layer` split** | one GPU idle while the other is full | `-sm row`/`tensor` + `-ts 3,1` to balance; `-mg 0` picks the KV host |
| **Quantize weights, not KV** | weights fit but KV OOMs at long ctx | KV quant is independent: `-ctk q8_0 -ctv q8_0` (or `q4_0`). Halves/quarters the cache term |
| **Assuming full offload always wins** | chasing `-ngl 999` on a too-big model | A smaller model that FULLY fits beats a bigger model that spills to RAM (bandwidth cliff). Prefer fit over size |

---

## 6. Cheat sheet

```
-ngl N   : first N layers -> GPU (VRAM), rest -> CPU (RAM/SIMD).
           -ngl 0 = all-CPU;  -ngl 999 / all = full offload.
           (llama.cpp default is now 'auto' + --fit.)

budget   : VRAM = wpl*ngl + KV(ctx) + overhead
           ngl  = min( floor((gpu - overhead - KV)/wpl), n_layers )

Llama-8B : 32 layers, dim 4096, 8 KV heads, head_dim 128.
  Q4_K_M weights = 4.52 GiB  -> 145 MiB/layer
  KV f16  = 128 KiB/token    -> 0.50 GiB @4K, 4.0 @32K, 8.0 @64K
  overhead = 0.50 GiB

seam     : activation = batch*seq*dim*bytes  (NOT weights)
           decode  = 8 KiB;  prefill(1024) = 8 MiB.
           weights are 18514x bigger; move ONCE at load.
           => bottleneck is CPU compute, not the copy.

curve    : tok/s ~linear in ngl, then FLAT at full offload
           (decode becomes VRAM-bandwidth-bound).

flags    : -ngl / --n-gpu-layers {N|auto|all}
           -sm {none,layer,row,tensor}  -ts N0,N1  -mg IDX
           -ctk/-ctv {f16,q8_0,q4_0}    -cmoe      --fit on

gold     : 8B Q4_K_M, 8GiB, 4K ctx -> 4.52+0.50+0.50 = 5.52 GiB
           -> ALL 32 fit  ->  -ngl 32  (2.48 GiB headroom).
```

---

## 🔗 Cross-references

- **[vram_estimator](./VRAM_ESTIMATOR.md)** — the full VRAM budget this bundle
  splits. `gpu_offload` answers *how many layers*; `vram_estimator` answers *how
  much total* (weights + KV + activations + overhead) for a given model/ctx.
- **[llm/KTRANSFORMERS_OFFLOAD](../llm/KTRANSFORMERS_OFFLOAD.md)** — the same
  idea at MoE scale: CPU holds the expert weights (rarely activated), GPU holds the
  shared attention. `-cmoe` / `-ot` realize it in llama.cpp.
- **[ggml_backend](./GGML_BACKEND.md)** — *what* gets routed. `ggml_backend_sched`
  assigns each layer's `ggml_cgraph` to a backend and inserts the `CPY` seam node;
  `-ngl` is the knob that decides *how many* layers go to the GPU backend.
- **[quant_types](./QUANT_TYPES.md)** — the `Q4_K_M`/`Q8_0` footprints consumed
  here as `WEIGHT_GIB` inputs are derived from the block-quant layouts in that bundle.
- **[kv_cache_quant](./KV_CACHE_QUANT.md)** — `-ctk`/`-ctv` quantize the KV term in
  the budget above (0.50 → 0.25 GiB at 4K), buying headroom for more `ngl`.

## Sources

- [llama.cpp `tools/server/README.md` — `-ngl`, `-sm`, `-ts`, `-mg`, `-fit`, `-cmoe`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp `-ngl` / `--n-gpu-layers` flag (CLI)](https://github.com/ggml-org/llama.cpp) — exact number | `auto` | `all` (default `auto`)
- [llama.cpp Backend wiki](https://github.com/ggml-org/llama.cpp/wiki/Backend) — `ggml_backend_sched` graph split + `CPY` seam nodes
- [Fine-grained control of GPU offloading (llama.cpp discussion #7678)](https://github.com/ggml-org/llama.cpp/discussions/7678) — per-GPU layer split
- [GPU VRAM, CPU Offload, and llama.cpp: The Real Performance Cliff](https://sergiiob.dev/posts/gpu-vram-cpu-offload-llama-cpp-deep-dive/) — bandwidth-cliff analysis, `-ngl` tuning workflow
- [`-ngl 22` cuts wall clock ~60% on RTX 2070S 8GB (HN)](https://news.ycombinator.com/item?id=35939632) — empirical partial-offload speedup
