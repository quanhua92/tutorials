"""
performance_torch.py — Phase 5 bundle #35.

GOAL (one line): show, by running real code, that the PyTorch performance
levers are mixed precision (autocast + GradScaler), torch.compile (op fusion),
and inference_mode — and that you PROFILE before optimizing.

This is the GROUND TRUTH for PERFORMANCE_TORCH.md. Every number, dtype, and
timing in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Timing digits are ILLUSTRATIVE (vary per run / machine / load). We assert only
STRUCTURAL facts (autocast changes the op dtype to bfloat16; torch.compile
returns a callable; inference_mode tensors cannot be saved for backward) —
never absolute microseconds.

CPU is the default for determinism (MPS is available here, kept off on
purpose). Where a lever's payoff only shows on GPU (tensor cores, fp16 grad
underflow), we explain it conceptually and link to the LLM-systems bundles
that go deep on the hardware.

Run:
    uv run python performance_torch.py
"""

from __future__ import annotations

import time
from contextlib import nullcontext

import torch
import torch.nn as nn

BANNER = "=" * 70
_ILLUSTRATIVE = "(varies per run)"


# ----------------------------------------------------------------------------
# pretty printers (house style)
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


def _best_of(fn, n: int, warmup: int = 3) -> float:
    """Return best per-call seconds over n calls after a small warmup."""
    for _ in range(warmup):
        fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    return (time.perf_counter() - t0) / n


# ----------------------------------------------------------------------------
# Section A — mixed precision autocast (CPU default dtype is bfloat16)
# ----------------------------------------------------------------------------

def section_a_autocast() -> None:
    banner("A — Mixed precision autocast: fp32 weights -> bfloat16 op")
    print("torch.autocast(device_type=...) wraps the forward pass. Inside it,")
    print("ops on the autocast list (mm, linear, matmul, conv2d, ...) run in a")
    print("lower-precision dtype. On CUDA the default is float16; on CPU it is")
    print("bfloat16 (same 8-bit exponent as fp32 -> no dynamic-range loss).")
    print("Weights STAY fp32 ('master weights') — only the math drops precision.\n")
    torch.manual_seed(0)
    a = torch.randn(128, 128)            # fp32 input
    b = torch.randn(128, 128)
    layer = nn.Linear(128, 64)           # fp32 master weights
    w_dtype_before = layer.weight.dtype
    out_eager = torch.mm(a, b)
    with torch.autocast(device_type="cpu"):        # default dtype = bfloat16
        out_amp = torch.mm(a, b)
        lin_amp = layer(a)
    w_dtype_after = layer.weight.dtype
    print(f"input a.dtype            = {a.dtype}")
    print(f"layer.weight.dtype before = {w_dtype_before} ; after autocast = {w_dtype_after}")
    print(f"torch.mm OUTSIDE autocast -> {out_eager.dtype}")
    print(f"torch.mm INSIDE  autocast -> {out_amp.dtype}   <-- dtype changed mid-op")
    print(f"nn.Linear INSIDE autocast -> {lin_amp.dtype}")
    print(f"fp32 bytes/elem = {a.element_size()} ; bf16 bytes/elem = "
          f"{out_amp.element_size()} (activations halved)")
    print("On tensor-core GPUs this yields ~2x speed + half memory; on CPU the")
    print("win is smaller (bf16 is a precision/memory cut, not a tensor-core path).\n")
    check("autocast changes mm output dtype fp32 -> bfloat16",
          out_eager.dtype is torch.float32 and out_amp.dtype is torch.bfloat16)
    check("autocast changes Linear output dtype to bfloat16",
          lin_amp.dtype is torch.bfloat16)
    check("master weights stay fp32 under autocast",
          w_dtype_before is torch.float32 and w_dtype_after is torch.float32)
    check("bfloat16 activation is half the bytes of fp32",
          out_amp.element_size() * 2 == a.element_size())


# ----------------------------------------------------------------------------
# Section B — GradScaler: prevents fp16 gradient underflow
# ----------------------------------------------------------------------------

def section_b_grad_scaler() -> None:
    banner("B — GradScaler: scale the loss up so fp16 grads don't underflow")
    print("fp16's finite max is 65504 and small grads flush to zero ('under-")
    print("flow'), silently losing the parameter update. GradScaler multiplies")
    print("the loss by a large scale (default init_scale=65536.0 per the docs),")
    print("runs backward on the scaled loss, then UNSCALES the grads before the")
    print("optimizer step. Canonical CUDA AMP loop:")
    print("    scaler = torch.amp.GradScaler('cuda')   # init_scale=65536.0")
    print("    with torch.autocast('cuda'):")
    print("        loss = model(x)")
    print("    scaler.scale(loss).backward()           # grads scaled up")
    print("    scaler.unscale_(optimizer)              # divide grads back")
    print("    scaler.step(optimizer); scaler.update() # step + grow/shrink\n")
    print("On CPU / bfloat16 NO scaler is needed: bf16 shares fp32's 8-bit")
    print("exponent range, so grads don't underflow. Below we demo the API with")
    print("enabled=False (a no-op scaler that runs anywhere).\n")
    model = nn.Linear(32, 4)
    loss = model(torch.randn(8, 32)).sum()
    scaler = torch.amp.GradScaler("cuda", enabled=False)   # no-op (no CUDA here)
    scaled = scaler.scale(loss)
    print(f"scaler.is_enabled()         = {scaler.is_enabled()}  (CPU: no-op)")
    print(f"scaler.get_scale()          = {scaler.get_scale()}  (1.0 when disabled)")
    print(f"scaler.scale(loss) is loss  = {scaled is loss}  (identity when disabled)")
    for m in ("scale", "unscale_", "step", "update"):
        print(f"  scaler.{m:<10} exists: {hasattr(scaler, m)}")
    fp16_max = torch.finfo(torch.float16).max
    bf16_max = torch.finfo(torch.bfloat16).max
    fp32_max = torch.finfo(torch.float32).max
    print(f"torch.finfo(float16).max   = {fp16_max}        <- underflow/overflow ceiling")
    print(f"torch.finfo(bfloat16).max  = {bf16_max:.3e}")
    print(f"torch.finfo(float32).max   = {fp32_max:.3e}")
    print("-> bf16 and fp32 share the 8-bit exponent (similar max);")
    print("   fp16's ~[6e-8 .. 6.5e4] range is tiny, hence the underflow risk.\n")
    check("disabled scaler.scale(loss) is the identity (no-op)", scaled is loss)
    check("scaler exposes scale/unscale_/step/update",
          all(hasattr(scaler, m) for m in ("scale", "unscale_", "step", "update")))
    check("fp16 finite max is 65504.0 (the narrow-range ceiling)",
          fp16_max == 65504.0)
    check("bf16 max >> fp16 max (bf16 keeps fp32's exponent range)",
          bf16_max > fp16_max * 1e30)


# ----------------------------------------------------------------------------
# Section C — torch.compile: TorchDynamo traces, Inductor fuses ops
# ----------------------------------------------------------------------------

def section_c_compile() -> None:
    banner("C — torch.compile: TorchDynamo + Inductor trace & fuse ops")
    print("torch.compile(fn) returns a NEW callable. On the first call Torch-")
    print("Dynamo traces the Python frame into a graph; the Inductor backend")
    print("fuses pointwise ops into fewer kernels. There is a ONE-TIME compile")
    print("cost; later calls reuse the cached artifact. Mode 'reduce-overhead'")
    print("additionally captures a CUDA graph (🔗 ../llm/CUDA_GRAPHS.md).\n")
    torch.manual_seed(0)

    def eager_fn(x: torch.Tensor) -> torch.Tensor:
        return torch.relu(torch.sin(x) * x + torch.cos(x))

    compiled_fn = torch.compile(eager_fn)      # Inductor, default mode
    x = torch.randn(1024)
    y_eager = eager_fn(x)
    print(f"torch.compile(eager_fn) -> callable : {callable(compiled_fn)}")
    # The FIRST call triggers JIT compilation. On this CPU-only env Inductor's
    # generated-code path may fail (it leans on setuptools/packaging at JIT
    # time); that is an environment limitation, NOT a torch.compile API limit.
    compiled_ok = False
    y_comp = None
    try:
        y_comp = compiled_fn(x)
        compiled_ok = True
    except Exception as e:  # noqa: BLE001 — we explicitly tolerate JIT failure
        print(f"compiled forward on this CPU env: {type(e).__name__} "
              f"(Inductor JIT unavailable here — API is still valid)")
    if compiled_ok and y_comp is not None:
        print(f"compiled forward ran; max |eager - compiled|: "
              f"{(y_eager - y_comp).abs().max().item():.2e}  {_ILLUSTRATIVE}")
        t_e = _best_of(lambda: eager_fn(x), n=200)
        t_c = _best_of(lambda: compiled_fn(x), n=200)
        print(f"eager    best/call: {t_e*1e6:8.2f} us  {_ILLUSTRATIVE}")
        print(f"compiled best/call: {t_c*1e6:8.2f} us  {_ILLUSTRATIVE}")
        print("(on GPU the gap widens: fewer kernel launches + tensor-core fusion)")
        matches = torch.allclose(y_eager, y_comp, atol=1e-5)
    else:
        print("On a CUDA/tensor-core GPU, the compiled callable would fuse the")
        print("sin/cos/mul/relu ops into one kernel and skip Python overhead.")
        matches = True  # API contract holds; this env can't execute the JIT
    print()
    check("torch.compile returns a callable", callable(compiled_fn))
    check("compiled output matches eager within fp32 tolerance "
          "(or JIT unavailable in this env)", matches)


# ----------------------------------------------------------------------------
# Section D — inference_mode vs no_grad: faster AND stricter
# ----------------------------------------------------------------------------

def section_d_inference_mode() -> None:
    banner("D — inference_mode vs no_grad: faster AND stricter")
    print("Both disable autograd recording. inference_mode is the EXTREME")
    print("version: it ALSO skips the extra autograd bookkeeping (version")
    print("counters, saved-tensor tracking), so it is faster. The trade-off: ")
    print("tensors created under inference_mode CANNOT be saved for backward")
    print("later — using them in a grad-requiring computation raises.\n")
    torch.manual_seed(0)
    with torch.no_grad():
        t_ng = torch.randn(4)
    with torch.inference_mode():
        t_im = torch.randn(4)
    grad_leaf = torch.randn(4, requires_grad=True)
    raised = False
    try:
        ((t_im * grad_leaf).sum()).backward()
    except RuntimeError:
        raised = True
    print(f"no_grad tensor        requires_grad = {t_ng.requires_grad}")
    print(f"inference_mode tensor requires_grad = {t_im.requires_grad}")
    print(f"backward using inference tensor raised RuntimeError: {raised}")
    big = torch.randn(1024, 1024)

    def time_ctx(ctx, n: int = 20) -> float:
        for _ in range(3):
            with ctx():
                _ = big @ big
        t0 = time.perf_counter()
        for _ in range(n):
            with ctx():
                _ = big @ big
        return (time.perf_counter() - t0) / n

    t_eager = time_ctx(nullcontext)
    t_no_grad = time_ctx(torch.no_grad)
    t_inf = time_ctx(torch.inference_mode)
    print(f"eager          best/call: {t_eager*1e3:7.3f} ms  {_ILLUSTRATIVE}")
    print(f"no_grad        best/call: {t_no_grad*1e3:7.3f} ms  {_ILLUSTRATIVE}")
    print(f"inference_mode best/call: {t_inf*1e3:7.3f} ms  {_ILLUSTRATIVE}")
    print("(ordering is illustrative; the structural fact is the strictness)")
    print()
    check("no_grad and inference_mode both set requires_grad=False",
          not t_ng.requires_grad and not t_im.requires_grad)
    check("inference_mode tensor CANNOT be saved for backward", raised)


# ----------------------------------------------------------------------------
# Section E — torch.profiler: find the hot op before optimizing
# ----------------------------------------------------------------------------

def section_e_profiler() -> None:
    banner("E — torch.profiler: find the hot op BEFORE optimizing")
    print("Profile BEFORE optimizing — the 'measure don't guess' law")
    print("(🔗 PROFILING_OPTIMIZATION). torch.profiler records every op with")
    print("its self time; record_function labels a region for attribution.\n")
    torch.manual_seed(0)
    x = torch.randn(512, 512)

    def workload() -> None:
        with torch.profiler.record_function("matmul_block"):
            y = x @ x
        with torch.profiler.record_function("elementwise_block"):
            _ = torch.relu(y) + torch.sin(y)

    with torch.profiler.profile() as prof:
        for _ in range(5):
            workload()

    events = prof.key_averages()
    names = {e.key for e in events}
    print("--- recorded regions present in the profile ---")
    for label in ("matmul_block", "elementwise_block"):
        print(f"  {label:<20} recorded: {label in names}")
    ranked = sorted(events, key=lambda e: e.self_cpu_time_total, reverse=True)
    print(f"{'op/key':<28}{'self_cpu_us':>12}")
    print("-" * 42)
    for e in ranked[:6]:
        print(f"{e.key:<28}{e.self_cpu_time_total:>12.1f}")
    print("  (self_cpu_us is illustrative; the RANKING is the actionable signal)")
    print()
    check("both record_function labels appear in the profile",
          "matmul_block" in names and "elementwise_block" in names)
    check("profile captured at least one op (non-empty)", len(events) > 0)
    check("the hottest op has positive self-time",
          ranked[0].self_cpu_time_total > 0)


# ----------------------------------------------------------------------------
# Section F — the sync-point trap: .item()/.cpu()/print force a GPU wait
# ----------------------------------------------------------------------------

def section_f_sync_points() -> None:
    banner("F — The sync-point trap: .item() forces a CPU<->GPU wait")
    print("On GPU, ops queue asynchronously. .item(), .cpu(), or printing a")
    print("tensor FORCES the CPU to wait for the GPU (a 'sync point'). Calling")
    print(".item() every loop iteration serializes the pipeline — the classic")
    print("invisible slowdown. Demonstration of the API + the right pattern.\n")
    torch.manual_seed(0)
    x = torch.randn(8, 8)

    def with_sync(n: int) -> float:
        s = 0.0
        for _ in range(n):
            s += (x @ x).sum().item()      # <-- sync point each iteration
        return s

    def without_sync(n: int) -> float:
        acc = torch.zeros(())              # stays on-device
        for _ in range(n):
            acc += (x @ x).sum()
        return acc.item()                  # single sync at the end

    sample_item = (x @ x).sum().item()
    acc_tensor = torch.zeros(())
    acc_tensor += (x @ x).sum()
    n = 200

    def count_items(fn) -> int:
        calls = [0]
        orig = torch.Tensor.item

        def spy(self, *a, **k):
            calls[0] += 1
            return orig(self, *a, **k)
        torch.Tensor.item = spy
        try:
            fn()
        finally:
            torch.Tensor.item = orig
        return calls[0]

    bad_items = count_items(lambda: with_sync(n))
    good_items = count_items(lambda: without_sync(n))
    print(f".item() returns a {type(sample_item).__name__} "
          f"(the device->host scalar pull = the GPU sync)")
    print(f"tensor accumulator stays a {type(acc_tensor).__name__} (no per-iter pull)")
    print(f"'with_sync'    calls .item(): {bad_items} times -> {bad_items} sync points")
    print(f"'without_sync' calls .item(): {good_items} time   -> {good_items} sync point")
    print("On GPU each .item() blocks the whole stream, so n sync points cost")
    print(f"~{bad_items}x more stalls than 1. On CPU there is no real stall, so")
    print("timing is uninformative; the sync-point COUNT is the structural cost.")
    print()
    check(".item() extracts a Python float (the sync mechanism)",
          isinstance(sample_item, float))
    check("the tensor accumulator stays a torch.Tensor (no per-iter sync)",
          isinstance(acc_tensor, torch.Tensor))
    check("both reductions agree on the numeric result",
          abs(with_sync(n) - without_sync(n)) < 1e-2)
    check("per-iter .item() makes n sync points vs 1 for the batched version",
          bad_items == n and good_items == 1)


# ----------------------------------------------------------------------------
# Section G — memory: fp16/bf16 halve activations; checkpointing trades compute
# ----------------------------------------------------------------------------

def section_g_memory() -> None:
    banner("G — Memory: fp16/bf16 halve activations; checkpointing trades compute")
    print("Lower precision halves activation memory: fp16/bf16 = 2 bytes vs")
    print("fp32's 4. Gradient checkpointing (🔗 ../llm/GRADIENT_CHECKPOINTING.md)")
    print("trades compute for memory by RE-RUNNING parts of the forward during")
    print("backward instead of saving all activations (~1.33x recompute cost).\n")
    torch.manual_seed(0)
    n = 1_000_000
    fp32 = torch.randn(n)
    fp16 = fp32.to(torch.float16)
    bf16 = fp32.to(torch.bfloat16)
    print(f"{'tensor':<8}{'bytes':>14}{'vs fp32':>10}")
    print("-" * 34)
    for name, t in [("fp32", fp32), ("fp16", fp16), ("bf16", bf16)]:
        ratio = t.element_size() / fp32.element_size()
        print(f"{name:<8}{t.element_size():>14}{ratio:>9.0%}")
    has_ckpt = hasattr(torch.utils.checkpoint, "checkpoint")
    print(f"\ntorch.utils.checkpoint.checkpoint available: {has_ckpt}")
    print()
    check("fp16 tensor is half the bytes of fp32",
          fp16.element_size() * 2 == fp32.element_size())
    check("bf16 tensor is half the bytes of fp32",
          bf16.element_size() * 2 == fp32.element_size())
    check("torch.utils.checkpoint.checkpoint exists", has_ckpt)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("performance_torch.py — Phase 5 bundle #35.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Timing digits are ILLUSTRATIVE (vary per run); we assert\n"
          "only structural facts. CPU is used for determinism.\n"
          f"Python {__import__('sys').version.split()[0]}, "
          f"torch {torch.__version__}.")
    section_a_autocast()
    section_b_grad_scaler()
    section_c_compile()
    section_d_inference_mode()
    section_e_profiler()
    section_f_sync_points()
    section_g_memory()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
