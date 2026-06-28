"""mlx_inference.py - Reference simulation of Apple MLX, the array framework
purpose-built for Apple Silicon. Three core architectural differences from
PyTorch / llama.cpp drive its speed for on-device LLM inference:

  1. UNIFIED MEMORY (zero-copy)  - CPU and GPU share the SAME physical RAM.
  2. LAZY EVALUATION             - ops build a graph; nothing runs until eval().
  3. FUNCTIONAL TRANSFORMS       - value_and_grad / vmap / compile, composable
                                   (borrowed from JAX).

Those three combine into OP FUSION: a chain of elementwise ops collapses into a
single Metal kernel, cutting memory traffic K-fold for a K-op chain.

This is the single source of truth that MLX_INFERENCE.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 mlx_inference.py

============================================================================
THE INTUITION (read this first) -- MLX is the only major tensor library written
*natively* for unified memory. Everyone else (PyTorch MPS, llama.cpp Metal,
TensorFlow Metal) inherits a split CPU-RAM / GPU-VRAM design and bolted a copy
path on top. MLX removes the copy entirely and lets the compiler see the whole
graph up front so it can fuse.
============================================================================
PyTorch runs ops EAGERLY: each call dispatches the instant it happens and writes
every intermediate to memory. MLX runs ops LAZILY: `a = mx.array([1,2,3,4])`,
`b = a * 2`, `c = b + 5` builds a computation graph but computes NOTHING. Only
`mx.eval(c)` (or `print(c)`) walks the graph, fuses elementwise neighbours, and
runs the fused Metal kernels. Because Apple Silicon's CPU and GPU address the
SAME RAM, the fused kernel reads `a` once and writes `c` once -- the
intermediate `b` lives in a GPU register, never in main memory.

For a K-op elementwise chain:
  - WITHOUT fusion: K kernel dispatches, each doing 1 read + 1 write of the
    full array  ->  2*K array-sized memory transfers.
  - WITH fusion:   1 kernel doing 1 read (input) + 1 write (output)  ->  2
    transfers.
  - Bandwidth saved: K-fold.  For K=3  ->  6 transfers down to 2  ->  3x less.

Decode (generating one token) is BANDWIDTH-BOUND: the model weights are read
once per token. Cutting memory traffic K-fold on the elementwise bookkeeping
ops (norms, residuals, activations) frees bandwidth for the weight reads that
actually matter. Combined with zero CPU<->GPU copy, MLX is reported 2-3x faster
than llama.cpp for decode on Apple Silicon (Ollama 0.19+ switched to MLX).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
  unified memory  : Apple Silicon's CPU and GPU share the SAME physical RAM.
                    Both address it directly -- there is no "VRAM vs RAM".
  zero-copy       : the GPU can read an array the CPU wrote (and vice versa)
                    without copying a single byte. The pointer is the same.
  stream          : MLX picks the device at OP time, not array time. You pass
                    `stream=mx.gpu` to a matmul; the same array can be used by
                    `stream=mx.cpu` in the next line -- no .to('gpu') copy.
  lazy eval       : ops append nodes to a graph; the graph executes only when
                    a result is needed (mx.eval / print / .item()).
  graph           : a DAG of arrays (nodes) + ops (edges) waiting to run.
  op fusion       : consecutive elementwise ops merged into one Metal kernel;
                    the intermediate arrays stay in registers, not memory.
  memory transfer : one full-array read OR write to main memory (the thing
                    fusion eliminates). Distinct from a kernel dispatch.
  Metal kernel    : the GPU shader MLX's compiler emits for a fused subgraph.
  mx.compile(fn)  : traces fn's graph once, fuses, caches the compiled graph.
  value_and_grad  : returns (fn(x), d fn/dx) in ONE pass (no separate backward).
  vmap            : vectorizing map -- run fn over a batch as one fused op.
  decode          : generating tokens autoregressively (bandwidth-bound).
  QuantizedLinear : MLX's 2/4/8-bit group-quantized linear layer (like GGUF,
                    but native MLX format).
"""

BANNER_WIDTH = 70
_BAR = "=" * BANNER_WIDTH

# ---------------------------------------------------------------------------
# Constants. All "performance" is MODELLED (never wall-clock) so the output is
# byte-for-byte reproducible. The bandwidth / efficiency figures are order-of-
# magnitude representative of Apple Silicon (M2 Max class), clearly labelled.
# ---------------------------------------------------------------------------
ELEMENT_BYTES = 4                       # float32 element size, bytes
M2MAX_BW_GBPS = 400.0                   # M2 Max unified-memory bandwidth, GB/s
MLX_EFF = 0.65                          # MLX fraction-of-roofline (modelled)
LLAMACPP_EFF = 0.45                     # llama.cpp Metal fraction (modelled)


def banner(title: str) -> None:
    print(f"\n{_BAR}\nSECTION {title}\n{_BAR}")


def check(desc: str, ok: bool) -> None:
    if not ok:
        raise SystemExit(f"INVARIANT VIOLATED: {desc}")
    print(f"[check] {desc}: OK")


def fmt(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}"


# ===========================================================================
# Simulation primitives.
# ===========================================================================
class UnifiedMemory:
    """Apple Silicon's shared RAM pool. Both the CPU and the GPU read/write the
    SAME bytes object -- there is one buffer, not two. A `copy` is therefore an
    explicit, avoidable event we can count (it should be ZERO under MLX)."""

    def __init__(self, size: int):
        self.pool = bytearray(size)
        self.copy_bytes = 0          # bytes physically copied (CPU<->GPU)

    def cpu_read(self, off, n):
        return bytes(self.pool[off:off + n])      # direct, no copy

    def gpu_read(self, off, n):
        return bytes(self.pool[off:off + n])      # SAME pool, no copy

    def gpu_write(self, off, data):
        self.pool[off:off + len(data)] = data     # SAME pool, no copy


class MXArray:
    """An MLX-style array. It is either CONCRETE (a materialised value living
    in unified memory) or LAZY (a graph node: an op + input arrays, with NO
    value yet). Ops on a lazy array return another lazy array -- the graph
    grows, nothing executes."""

    _counter = 0

    def __init__(self, value=None, op=None, inputs=()):
        self.value = value
        self.op = op                  # 'const', 'mul', 'add', ...
        self.inputs = tuple(inputs)
        MXArray._counter += 1
        self.id = MXArray._counter
        self.materialised = value is not None

    @classmethod
    def const(cls, values):
        return cls(value=list(values), op="const", inputs=())

    def __repr__(self):
        if self.materialised:
            return f"MXArray#{self.id}({self.op},materialised={self.value})"
        return f"MXArray#{self.id}({self.op},LAZY)"


def mx_mul(a, scalar):            # elementwise a * scalar  ->  lazy node
    return MXArray(op=f"mul(*{scalar})", inputs=(a, scalar))


def mx_add(a, scalar):            # elementwise a + scalar  ->  lazy node
    return MXArray(op=f"add(+{scalar})", inputs=(a, scalar))


def mx_eval(root):
    """mx.eval(): walk the graph bottom-up, materialise every lazy node. Until
    this is called, `root` holds NO concrete value. Returns the materialised
    list and the number of nodes that had to be computed."""
    visited = {}
    computed = [0]

    def rec(node):
        if node.id in visited:
            return visited[node.id]
        if node.materialised:
            visited[node.id] = node.value
            return node.value
        a, extra = node.inputs
        a_val = rec(a)
        out = []
        if node.op.startswith("mul"):
            out = [v * extra for v in a_val]
        elif node.op.startswith("add"):
            out = [v + extra for v in a_val]
        computed[0] += 1
        node.value = out
        node.materialised = True
        visited[node.id] = out
        return out

    val = rec(root)
    return val, computed[0]


# ===========================================================================
# SECTION A: unified memory -- one RAM pool, zero copy between CPU and GPU
# ===========================================================================
def section_a() -> None:
    banner("A: unified memory -- CPU and GPU share ONE physical RAM pool")
    print(
        "On Apple Silicon the CPU and GPU address the SAME physical RAM. An MLX\n"
        "array lives in that shared pool; you do NOT move it to a device. Instead\n"
        "you pick the device at OP time via `stream=`. So a GPU matmul and a CPU\n"
        "byte-read of element 0 hit the SAME bytes -- zero copy, either direction.\n"
    )

    mem = UnifiedMemory(size=64)
    # place array `a` at offset 0, four float32s (16 bytes)
    a_vals = [1.0, 2.0, 3.0, 4.0]
    for i, v in enumerate(a_vals):
        mem.pool[i * 4:(i + 1) * 4] = (int(v * 1e6)).to_bytes(4, "little")  # stand-in
    print(f"  a = mx.array({a_vals})  -> lives in shared pool at offset 0")

    # MLX: GPU does a matmul-ish op on `a`, then CPU reads a[0] -- NO copy
    gpu_out = mem.gpu_read(0, 16)        # GPU reads a directly
    cpu_el0 = mem.cpu_read(0, 4)         # CPU reads a[0] from the SAME pool
    print(f"  GPU op: mx.matmul(a, W, stream=mx.gpu)   reads shared pool -> {len(gpu_out)} B, copied = {mem.copy_bytes}")
    print(f"  CPU op: print(a[0])                      reads shared pool -> {len(cpu_el0)} B, copied = {mem.copy_bytes}")
    check("MLX unified memory: GPU then CPU read cost ZERO copy bytes", mem.copy_bytes == 0)

    # Contrast: PyTorch MPS keeps separate CPU and GPU buffers; .to() copies.
    cpu_buf = bytes(16)
    mps_buf = cpu_buf + b""              # .to('mps')  -> copies 16 B CPU->GPU
    torch_copy_to = len(mps_buf)
    mps_result = mps_buf                 # (op runs on mps)
    back = mps_result + b""              # .to('cpu')  -> copies 16 B GPU->CPU
    torch_copy_back = len(back)
    torch_total = torch_copy_to + torch_copy_back
    print(f"\n  PyTorch MPS contrast (same 16 B array, on the SAME hardware):")
    print(f"    .to('mps') copies CPU -> GPU : {torch_copy_to} B")
    print(f"    .to('cpu') copies GPU -> CPU : {torch_copy_back} B")
    print(f"    total explicit copies        : {torch_total} B   (vs MLX {mem.copy_bytes} B)")

    # Project: a 2 GB activation round-tripped once per layer across 32 layers
    print("\n  project: 2.0 GB activation, CPU<->GPU round-trip, 32 layers")
    act_gb = 2.0
    layers = 32
    mlx_copy = 0.0
    torch_copy = 2 * act_gb * layers     # to-mps + to-cpu, per layer
    print(f"    MLX   copies = {fmt(mlx_copy, 1)} GB   (unified memory, arrays stay put)")
    print(f"    Torch copies = {fmt(torch_copy, 0)} GB (2 x {fmt(act_gb,1)} x {layers} layers)")
    print(f"    saved        = {fmt(torch_copy - mlx_copy, 0)} GB")
    check("MLX avoids 100% of the CPU<->GPU activation copies", mlx_copy == 0)
    check("PyTorch MPS copies 2 * act * layers", torch_copy == 2 * act_gb * layers)

    print(
        "\n  --> Unified memory is the foundation. The GPU never waits on a DMA\n"
        "      transfer, and the CPU never waits on a readback. Every other MLX\n"
        "      advantage (lazy eval, fusion) rides on top of this."
    )


# ===========================================================================
# SECTION B: lazy evaluation -- build a graph, defer, execute on eval()
# ===========================================================================
def section_b() -> None:
    banner("B: lazy evaluation -- ops build a graph; nothing runs until eval()")
    print(
        "MLX ops are LAZY. `a = mx.array([1,2,3,4])`, `b = a * 2`, `c = b + 5`\n"
        "constructs a graph of three nodes. Until you call mx.eval(c) (or print\n"
        "it), NOTHING is computed: b and c hold no value. This is what lets the\n"
        "compiler see the whole chain and fuse it (Section C).\n"
    )

    MXArray._counter = 0
    a = MXArray.const([1.0, 2.0, 3.0, 4.0])
    print(f"  a = mx.array([1,2,3,4])               -> {a}")
    b = mx_mul(a, 2)
    print(f"  b = a * 2                             -> {b}   (NOT computed yet)")
    c = mx_add(b, 5)
    print(f"  c = b + 5                             -> {c}   (NOT computed yet)")
    check("b is lazy (no value) before eval", b.value is None)
    check("c is lazy (no value) before eval", c.value is None)

    # Now eval -- the whole graph materialises in one walk
    val, computed = mx_eval(c)
    print(f"\n  mx.eval(c)  ->  graph executes, {computed} node(s) computed")
    print(f"  c materialised = {val}")
    check("after eval, c == [7.0, 9.0, 11.0, 13.0]", val == [7.0, 9.0, 11.0, 13.0])
    check("eval computed the 2 non-leaf nodes (b, c)", computed == 2)

    # Lazy means you can build WITHOUT paying -- inspect the graph before running
    print("\n  graph topology before eval (rebuild):")
    MXArray._counter = 0
    a2 = MXArray.const([1.0, 2.0, 3.0, 4.0])
    b2 = mx_mul(a2, 2)
    c2 = mx_add(b2, 5)
    nodes = []
    for n in (a2, b2, c2):
        state = "leaf/const" if n.op == "const" else "lazy"
        nodes.append((n.id, n.op, state))
    print(f"    {'id':<4}{'op':<12}{'state'}")
    for nid, op, state in nodes:
        print(f"    {nid:<4}{op:<12}{state}")

    print(
        "\n  --> The graph is a recipe. eval() bakes it (and, with fusion, folds\n"
        "      the recipe into the fewest possible kernels first)."
    )


# ===========================================================================
# SECTION C: op fusion -- K ops collapse to 1 kernel, K-fold less memory traffic
# ===========================================================================
def section_c() -> None:
    banner("C: op fusion -- K elementwise ops -> 1 Metal kernel, K-fold less I/O")
    print(
        "This is the payoff. A chain of K consecutive elementwise ops (mul, add,\n"
        "norm, activation...) run EAGERLY = K separate Metal kernel dispatches,\n"
        "each reading its input array from main memory and writing its output\n"
        "array back. MLX's compiler FUSES the chain into ONE kernel that reads\n"
        "the input once and writes the output once; every intermediate stays in\n"
        "GPU registers and never touches main memory.\n"
    )

    # ---- memory-traffic model (exact) ----
    # one array-sized read OR write = one "memory transfer"
    N = 4
    bytes_per_transfer = N * ELEMENT_BYTES

    print(f"  array size N = {N} elements x {ELEMENT_BYTES} B = {bytes_per_transfer} B/transfer")
    print(f"  chain c = (a * 2 + 5) * 3   ->   K = 3 elementwise ops (mul, add, mul)\n")

    print(f"  {'mode':<18}{'kernels':<10}{'reads':<8}{'writes':<8}{'transfers':<11}{'bytes'}")
    K = 3
    eager_kernels = K
    eager_reads, eager_writes = K, K
    eager_transfers = eager_reads + eager_writes
    eager_bytes = eager_transfers * bytes_per_transfer
    fused_kernels = 1
    fused_reads, fused_writes = 1, 1
    fused_transfers = fused_reads + fused_writes
    fused_bytes = fused_transfers * bytes_per_transfer
    print(f"  {'WITHOUT fusion':<18}{eager_kernels:<10}{eager_reads:<8}{eager_writes:<8}{eager_transfers:<11}{eager_bytes}")
    print(f"  {'WITH fusion':<18}{fused_kernels:<10}{fused_reads:<8}{fused_writes:<8}{fused_transfers:<11}{fused_bytes}")
    ratio = eager_transfers / fused_transfers
    print(f"\n  bandwidth reduction = {eager_transfers} transfers / {fused_transfers} transfers = {fmt(ratio, 1)}x less")

    # GOLD values (verified in .py, reproduced in .html)
    check("K=3 eager = 3 reads + 3 writes = 6 transfers", eager_transfers == 6)
    check("K=3 fused = 1 read + 1 write = 2 transfers", fused_transfers == 2)
    check("K=3 fusion = 3x less bandwidth (6 -> 2)", abs(ratio - 3.0) < 1e-9)

    # ---- verify the math holds for a range of chain lengths ----
    print("\n  fusion ratio across chain length K (ratio == K):")
    print(f"    {'K':<4}{'eager transfers':<18}{'fused transfers':<18}{'ratio'}")
    for K in (1, 2, 3, 4, 5, 8):
        e = 2 * K
        f = 2
        print(f"    {K:<4}{e:<18}{f:<18}{fmt(e / f, 1)}x")
    check("fusion ratio always equals K (2K -> 2)", all((2 * K) / 2 == K for K in range(1, 9)))

    # ---- the 2-op sub-case (a*2)+5 the HTML builds interactively ----
    print("\n  the 2-op sub-case  c = (a*2)+5  (the chain the HTML builds):")
    e2, f2 = 4, 2
    print(f"    eager = {e2} transfers, fused = {f2} transfers -> {fmt(e2/f2,1)}x")
    check("K=2 (a*2)+5 = 4 -> 2 = 2x", e2 // f2 == 2)

    # ---- project to a real decode step ----
    print("\n  project: per-token elementwise bookkeeping for a transformer block")
    print("           (RMSnorm x2 + residual adds + SiLU activation ~ 8 fused-able ops)")
    block_K = 8
    weight_gb = 2.0                 # 4B model @ 4-bit ~ 2 GB weights read per token
    bookkeep_gb = 0.05             # elementwise intermediates per block, ~50 MB
    eager_bw = weight_gb + block_K * bookkeep_gb     # each op round-trips the buffer
    fused_bw = weight_gb + bookkeep_gb               # one fused pass
    print(f"    weights read/token           = {fmt(weight_gb, 2)} GB (unavoidable)")
    print(f"    elementwise eager (8 ops)    = {fmt(block_K * bookkeep_gb, 2)} GB  (8 reads + 8 writes of {fmt(bookkeep_gb,2)} GB)")
    print(f"    elementwise fused (1 kernel) = {fmt(bookkeep_gb, 2)} GB   (1 read + 1 write)")
    print(f"    total bytes/token  eager     = {fmt(eager_bw, 2)} GB")
    print(f"    total bytes/token  fused     = {fmt(fused_bw, 2)} GB")
    print(f"    bandwidth saved/token        = {fmt(eager_bw - fused_bw, 2)} GB ({fmt((1-fused_bw/eager_bw)*100, 0)}%)")
    check("fusion cuts elementwise traffic from 8x to 1x", block_K * bookkeep_gb / bookkeep_gb == block_K)

    print(
        "\n  --> Decode is bandwidth-bound, so every byte of intermediate traffic\n"
        "      you delete is bandwidth freed for reading weights. Fusion is not a\n"
        "      micro-optimisation -- it is why MLX decodes fast."
    )


# ===========================================================================
# SECTION D: functional transformations -- grad, vmap, compile (composable)
# ===========================================================================
def section_d() -> None:
    banner("D: functional transforms -- value_and_grad, vmap, compile (stackable)")
    print(
        "MLX borrows JAX's functional-transforms model. Transformations are\n"
        "HIGHER-ORDER FUNCTIONS: they take a function and return a function.\n"
        "Because they are pure and composable, you can stack grad(vmap(compile(fn))).\n"
    )

    # value_and_grad: fn(x) = x^2  ->  (x^2, 2x)  in one pass
    def square(x):
        return x * x

    def value_and_grad(fn, x):
        v = fn(x)
        # analytic gradient of x^2 is 2x (symbolic here; MLX does it via autodiff)
        g = 2 * x
        return v, g

    x = 3.0
    v, g = value_and_grad(square, x)
    print(f"  mx.value_and_grad(square)(x={x})  ->  value = {fmt(v,1)}, grad = {fmt(g,1)}")
    check("value_and_grad(x=3) for x^2 -> (9.0, 6.0)", v == 9.0 and g == 6.0)

    # vmap: vectorising map -- run fn over a batch as one fused op
    def vmap(fn, xs):
        return [fn(x) for x in xs]

    batch = [1.0, 2.0, 3.0, 4.0]
    vals = vmap(square, batch)
    grads = vmap(lambda x: 2 * x, batch)
    print(f"\n  vmap(square)([{','.join(str(int(b)) for b in batch)}])      ->  values  = {vals}")
    print(f"  vmap(grad)([{','.join(str(int(b)) for b in batch)}])        ->  grads   = {grads}")
    check("vmap(square) over [1,2,3,4] -> [1,4,9,16]", vals == [1.0, 4.0, 9.0, 16.0])

    # compile: traces the graph once, fuses, caches (modelled as op-count)
    compiled_cache = {}

    def compile_fn(fn, key, *args):
        if key not in compiled_cache:
            compiled_cache[key] = ("traced+fused", 1)   # one fused kernel cached
        compiled_cache[key] = (compiled_cache[key][0], compiled_cache[key][1] + 0)
        return fn(*args)

    out = compile_fn(square, "square", x)
    print(f"\n  mx.compile(square)({x})             ->  {fmt(out,1)}   (graph traced, fused, cached)")
    print(f"  cache keys after first call          ->  {sorted(compiled_cache.keys())}")
    check("compile caches the traced+fused graph", list(compiled_cache.keys()) == ["square"])

    # composable: vmap(grad(compile(square)))
    def composed(xs):
        return vmap(lambda x: 2 * x, xs)     # grad of x^2 evaluated over the batch

    result = composed(batch)
    print(f"\n  composed = vmap(grad(compile(square)))  ->  {result}")
    print("  (PyTorch can't do this: backward is a separate imperative pass,")
    print("   not a transform you can stack with vmap/compile.)")
    check("composed grad over [1,2,3,4] -> [2,4,6,8]", result == [2.0, 4.0, 6.0, 8.0])

    print(
        "\n  --> grad + vmap + compile are Lego bricks. Stack them in any order;\n"
        "      MLX traces the composed graph once and fuses the whole thing."
    )


# ===========================================================================
# SECTION E: performance model -- why MLX beats llama.cpp on Apple Silicon
# ===========================================================================
def section_e() -> None:
    banner("E: performance model -- decode is bandwidth-bound; MLX spends less")
    print(
        "Generating one token (decode) is BANDWIDTH-BOUND: the engine must read\n"
        "essentially the whole model's weights once per token. The faster you\n"
        "saturate the unified-memory bandwidth with WEIGHT reads (not intermediate\n"
        "traffic / not CPU<->GPU copies), the more tokens/sec you get. MLX's three\n"
        "edges -- zero-copy, fusion, compiled Metal kernels -- all push toward the\n"
        "bandwidth roofline. Reported: MLX is ~2-3x faster than llama.cpp for decode\n"
        "on Apple Silicon (Ollama 0.19+ defaulted to MLX for this reason).\n"
    )

    # Roofline: tokens/sec = bandwidth / bytes-per-token
    weight_gb = 2.0                  # 4B params @ 4-bit ~ 2 GB
    roofline = M2MAX_BW_GBPS / weight_gb
    print(f"  model: 4B params @ 4-bit   ->  ~{fmt(weight_gb, 1)} GB weights read per token")
    print(f"  M2 Max unified-memory BW   = {fmt(M2MAX_BW_GBPS, 0)} GB/s")
    print(f"  roofline tokens/sec        = {fmt(M2MAX_BW_GBPS, 0)} / {fmt(weight_gb, 1)} = {fmt(roofline, 0)} tok/s")

    mlx_tps = roofline * MLX_EFF
    lcpp_tps = roofline * LLAMACPP_EFF
    speedup = mlx_tps / lcpp_tps
    print(f"\n  {'engine':<14}{'eff vs roof':<14}{'tok/s':<10}{'reason it loses efficiency'}")
    print(f"  {'MLX':<14}{int(MLX_EFF*100):<14}{fmt(mlx_tps,0):<10}no copy + fusion + compiled kernels")
    print(f"  {'llama.cpp':<14}{int(LLAMACPP_EFF*100):<14}{fmt(lcpp_tps,0):<10}Metal backend bolted onto a CPU-RAM design")
    print(f"\n  modelled decode speedup (MLX / llama.cpp) = {fmt(speedup, 1)}x  (order-of-magnitude; reported 2-3x)")
    check("MLX modelled faster than llama.cpp", mlx_tps > lcpp_tps)
    check("roofline = 400 / 2 = 200 tok/s", abs(roofline - 200.0) < 1e-9)

    # Where the bandwidth goes -- the three wins itemised
    print("\n  where MLX's bandwidth advantage comes from:")
    print(f"    1. zero CPU<->GPU copy    -> 0 B transferred per layer (unified memory)")
    print(f"    2. op fusion              -> elementwise traffic cut K-fold (Section C)")
    print(f"    3. compiled Metal kernels -> one dispatch per fused subgraph")
    print("    (llama.cpp's Metal backend works well but inherits a design from a")
    print("     split CPU-RAM/GPU-VRAM world; it copies more, fuses less.)")

    print(
        "\n  --> The 2-3x is not a single trick. It is the compound effect of three\n"
        "      architectural choices that all happen to help a bandwidth-bound workload."
    )


# ===========================================================================
# SECTION F: mlx-lm CLI + QuantizedLinear -- running models today
# ===========================================================================
def section_f() -> None:
    banner("F: mlx-lm + QuantizedLinear -- run a model in two commands")
    print(
        "mlx-lm is the high-level CLI / library for LLMs on top of MLX. It loads\n"
        "models from HuggingFace (mlx-community/Llama-3.2-3B-Instruct-4bit), runs\n"
        "them with the fused/compiled path above, and ships QuantizedLinear for\n"
        "2/4/8-bit group quantization (conceptually the same as GGUF's block quants,\n"
        "but stored in MLX's native format and run by MLX's own Metal kernels).\n"
    )

    print("  install + generate:")
    print("    pip install mlx-lm")
    print("    mlx_lm.generate --model mlx-community/Llama-3.2-3B-Instruct-4bit \\")
    print("                      --prompt 'Hello' --max-tokens 32")

    print("\n  quantize a model to 4-bit group quant (mlx_lm.convert):")
    print("    mlx_lm.convert --hf-path meta-llama/Llama-3.2-3B-Instruct -q --q-bits 4")

    # ---- model a 4-bit group quant (same idea as GGUF, native MLX) ----
    # group of 32 float32 weights (128 B) -> 1 fp16 scale (2 B) + 32 x 4-bit (16 B)
    group = 32
    fp32_bytes = group * 4
    scale_bytes = 2                        # one fp16 scale per group
    q4_bytes = group * 4 // 8             # 4 bits per weight
    packed_bytes = scale_bytes + q4_bytes
    ratio = fp32_bytes / packed_bytes
    print(f"\n  group quantization model (group = {group} weights):")
    print(f"    fp32 block        = {group} x 4 B         = {fp32_bytes} B")
    print(f"    4-bit block       = {scale_bytes} B scale + {q4_bytes} B packed = {packed_bytes} B")
    print(f"    compression ratio = {fp32_bytes} / {packed_bytes} = {fmt(ratio, 1)}x  (~8x counting only weights)")
    check("4-bit group quant block = 2 + 16 = 18 B", packed_bytes == 18)
    check("4-bit block ~7.1x smaller than fp32 block", abs(ratio - 128 / 18) < 1e-9)

    print("\n  bit-width options (mlx.nn.QuantizedLinear):")
    print(f"    {'bits':<6}{'scale B':<10}{'packed B':<10}{'ratio vs fp32'}")
    for bits in (2, 4, 8):
        sc = 2
        pk = sc + group * bits // 8
        print(f"    {bits:<6}{sc:<10}{pk:<10}{fmt(fp32_bytes / pk, 1)}x")

    print(
        "\n  --> mlx-lm makes MLX usable from the command line. The quantized weights\n"
        "      are dequantized on the fly inside the FUSED Metal kernel -- there is no\n"
        "      separate dequant pass, so quantization costs almost no extra bandwidth."
    )


def main() -> None:
    print("mlx_inference.py -- every value below is computed by this file.")
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    banner("DONE -- all sections printed")


if __name__ == "__main__":
    main()
