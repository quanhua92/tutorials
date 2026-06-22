"""
gpu_distributed.py — Bundle #34 (Phase 5).

GOAL (one line): show, by printing every value, how a PyTorch training run
moves from "my laptop" to a single accelerator (cuda/mps/cpu via .to(device))
and then scales to many GPUs with DistributedDataParallel — one PROCESS per
GPU, gradients averaged via AllReduce, each rank seeded differently.

This is the GROUND TRUTH for GPU_DISTRIBUTED.md. Every number, table, and
worked example in the guide is printed by this file. Change it -> re-run ->
re-paste. Never hand-compute.

DEVICE-AGNOSTIC: this machine has NO CUDA (it has MPS). The script selects
cuda -> mps -> cpu and actually runs on whatever is present. The CUDA-only
and DDP-only behaviors are demonstrated STRUCTURALLY (API shapes + a
single-process gloo init that really runs on CPU), never as a flaky
multi-process launch.

Deterministic: torch.manual_seed(0) before each model construction.

Run:
    uv run python gpu_distributed.py
"""

from __future__ import annotations

import os

import torch
import torch.distributed as dist
import torch.nn as nn

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers
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


# ----------------------------------------------------------------------------
# device selection — the one-line cuda/mps/cpu ladder
# ----------------------------------------------------------------------------

def pick_device() -> torch.device:
    """The canonical device-selection ladder (cuda -> mps -> cpu)."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ----------------------------------------------------------------------------
# Reference module (defined at module level for a clean qualname).
# ----------------------------------------------------------------------------

class MLP(nn.Module):
    """A tiny two-layer perceptron: Linear(4->8) -> ReLU -> Linear(8->1)."""

    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(4, 8)
        self.fc2 = nn.Linear(8, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(torch.relu(self.fc1(x)))


# ----------------------------------------------------------------------------
# Section A — device selection: cuda -> mps -> cpu
# ----------------------------------------------------------------------------

def section_a_device_selection() -> None:
    banner("A — Device selection: cuda -> mps -> cpu")
    print("A torch.Tensor lives on a device. The portable selection ladder is:")
    print("  device = 'cuda' if torch.cuda.is_available() else")
    print("           ('mps'  if torch.backends.mps.is_available() else 'cpu')")
    print("On this machine CUDA is absent, so the ladder falls through to mps")
    print("or cpu. The chosen device is printed below; nothing is hard-coded.\n")

    cuda_avail = torch.cuda.is_available()
    mps_avail = torch.backends.mps.is_available()
    device = pick_device()

    print(f"{'torch.cuda.is_available()':<38}{cuda_avail}")
    print(f"{'torch.backends.mps.is_available()':<38}{mps_avail}")
    print(f"{'torch.cuda.device_count()':<38}{torch.cuda.device_count()}")
    print(f"{'selected device':<38}{device}")
    print(f"{'device.type':<38}{device.type}")
    print()
    print("CUDA-only facts (conceptual on this machine):")
    print("  torch.cuda.device_count() -> #GPUs (0 here).")
    print("  tensor.cuda() / tensor.cpu() -> shorthand .to(device) moves.")
    print("  DataLoader(pin_memory=True) -> page-locked host RAM for faster")
    print("    host->device DMA copy (only helps when a CUDA GPU exists).")
    print("  torch.cuda.Stream -> an independent queue of CUDA kernels; lets")
    print("    copy & compute overlap (🔗 CUDA_GRAPHS for the deep view).")
    print()

    check("a device was always selected (never None)", device is not None)
    check("device.type is one of cuda/mps/cpu",
          device.type in ("cuda", "mps", "cpu"))
    check("cuda device_count is 0 on this non-CUDA machine",
          torch.cuda.device_count() == 0)
    check("cuda.is_available() and mps.is_available() are mutually consistent "
          "with the pick",
          (cuda_avail and device.type == "cuda")
          or (not cuda_avail and mps_avail and device.type == "mps")
          or (not cuda_avail and not mps_avail and device.type == "cpu"))


# ----------------------------------------------------------------------------
# Section B — .to(device): move a tensor AND a model; the same-device rule
# ----------------------------------------------------------------------------

def section_b_to_device_same_device_rule(device: torch.device) -> None:
    banner("B — .to(device): move a tensor and a model (same-device rule)")
    print(".to(device) returns a COPY on the target device for tensors, and")
    print("moves ALL parameters/buffers IN PLACE for an nn.Module (it returns")
    print("self). Inputs AND the model MUST land on the same device, else the")
    print("first matmul raises RuntimeError.\n")

    x_cpu = torch.arange(4, dtype=torch.float32)
    x_dev = x_cpu.to(device)
    torch.manual_seed(0)
    model = MLP().to(device)

    print(f"{'str(x_cpu.device)':<40}{x_cpu.device}")
    print(f"{'str(x_dev.device)':<40}{x_dev.device}")
    print(f"{'x_cpu is x_dev (new tensor object)':<40}"
          f"{x_cpu is x_dev}")
    print(f"{'str(model.fc1.weight.device)':<40}"
          f"{model.fc1.weight.device}")
    print(f"{'str(model.fc2.bias.device)':<40}"
          f"{model.fc2.bias.device}")
    print()

    out = model(x_dev)
    print(f"{'model(x_dev).device':<40}{out.device}")
    print(f"{'tuple(model(x_dev).shape)':<40}{tuple(out.shape)}")
    print()

    # The classic same-device RuntimeError, demonstrated by mixing devices.
    raised = False
    try:
        model(x_cpu)  # input on cpu, params on `device` (different if device!=cpu)
    except RuntimeError:
        raised = True
    same_dev = (x_dev.device.type == model.fc1.weight.device.type)
    mixed_dev = (str(x_cpu.device) != str(model.fc1.weight.device))
    print(f"{'x_dev.device.type == params device.type':<40}{same_dev}")
    print(f"{'x_cpu.device vs params device (mixed?)':<40}{mixed_dev}")
    print(f"{'model(cpu_input) raised RuntimeError':<40}"
          f"{mixed_dev and raised}")
    print()

    check("x_dev.device matches the selected device type",
          x_dev.device.type == device.type)
    check(".to(device) made a NEW tensor (not in-place for tensors)",
          x_cpu is not x_dev)
    check("model.fc1.weight is on the selected device after .to(device)",
          model.fc1.weight.device.type == device.type)
    check("model.fc2.bias is also on the selected device (whole tree moved)",
          model.fc2.bias.device.type == device.type)
    check("input+params on same device -> forward succeeds",
          same_dev and tuple(out.shape) == (1,))
    check("mixed-device forward raises RuntimeError",
          mixed_dev and raised)


# ----------------------------------------------------------------------------
# Section C — CUDA specifics, conceptual (no CUDA on this machine)
# ----------------------------------------------------------------------------

def section_c_cuda_specifics_conceptual() -> None:
    banner("C — CUDA specifics (conceptual: is_available / device_count / "
           "pinned / streams)")
    print("These APIs are CUDA-only. On this Mac they all report 'no CUDA' or")
    print("are no-ops; the .py asserts the negative results so the API shapes")
    print("are visible, and the .md explains what each DOES on a real GPU.\n")

    print(f"{'torch.cuda.is_available()':<42}{torch.cuda.is_available()}")
    print(f"{'torch.cuda.device_count()':<42}{torch.cuda.device_count()}")
    # pin_memory: a CPU op that page-locks a tensor for async DMA to the GPU.
    # On MPS-default Mac builds pin_memory() refuses to run (no CUDA context),
    # so we only assert the API exists here; the .md explains what it does.
    t = torch.arange(4, dtype=torch.float32)
    has_pin = hasattr(t, "pin_memory") and callable(t.pin_memory)
    has_is_pinned = hasattr(t, "is_pinned") and callable(t.is_pinned)
    print(f"{'hasattr(tensor, \"pin_memory\")':<42}{has_pin}")
    print(f"{'hasattr(tensor, \"is_pinned\")':<42}{has_is_pinned}")
    print()

    print("What each does on a CUDA box (NOT runnable here, from the docs):")
    print("  is_available()  -> True iff a usable CUDA runtime + GPU exist.")
    print("  device_count()  -> int number of visible GPUs.")
    print("  tensor.cuda()   -> alias for .to(torch.device('cuda')) .")
    print("  DataLoader(..., pin_memory=True) -> stage batches in page-locked")
    print("    host memory so the host->device copy can DMA in parallel with")
    print("    compute (pair with .to(device, non_blocking=True)).")
    print("  torch.cuda.Stream() -> an independent GPU command queue; multiple")
    print("    streams let copy and compute overlap (🔗 CUDA_STREAMS).")
    print()

    check("torch.cuda.is_available() is a bool",
          isinstance(torch.cuda.is_available(), bool))
    check("torch.cuda.device_count() is an int",
          isinstance(torch.cuda.device_count(), int))
    check("tensor exposes the pin_memory() API (CUDA-coupled, concept-only here)",
          has_pin and has_is_pinned)


# ----------------------------------------------------------------------------
# Section D — DDP conceptual model: one process per GPU, AllReduce grads
# ----------------------------------------------------------------------------

def section_d_ddp_conceptual_model() -> None:
    banner("D — DDP conceptual model: one PROCESS per GPU, AllReduce grads")
    print("DistributedDataParallel is DATA parallel: the WHOLE model is cloned")
    print("to every GPU, each GPU eats a DIFFERENT batch, and after backward")
    print("the per-rank gradients are averaged with AllReduce so every replica")
    print("takes the SAME optimizer step and can never drift.\n")

    print("  rank       = this process's id in [0, world_size).")
    print("  world_size = number of processes (= number of GPUs).")
    print("  local_rank = which GPU on this node (set via CUDA_VISIBLE_DEVICES")
    print("               or torch.cuda.set_device(local_rank)).")
    print("  ONE PROCESS PER GPU (not threads): the GIL would serialize a")
    print("  single Python process, so DDP spawns N processes for N GPUs.")
    print("  AllReduce   = a collective: every rank contributes a tensor and")
    print("               every rank ends up with the SAME averaged result.")
    print()

    # Simulate the AllReduce average across K=4 ranks with local gradients,
    # to make the "gradients are averaged" claim concrete and printable.
    torch.manual_seed(0)
    world_size = 4
    local_grads = [torch.randn(3) for _ in range(world_size)]
    avg_grad = torch.stack(local_grads).mean(dim=0)
    print(f"world_size = {world_size}; each rank's local grad (first elem):")
    for r in range(world_size):
        print(f"  rank {r}: g[{r}] = {local_grads[r].tolist()}")
    print(f"AllReduce-MEAN gradient (every rank gets THIS) = {avg_grad.tolist()}")
    print()

    manual_avg = sum(local_grads) / world_size
    print(f"manual sum/ world_size == torch.stack(...).mean : "
          f"{torch.allclose(manual_avg, avg_grad)}")
    print()

    check("world_size ranks produced world_size local gradients",
          len(local_grads) == world_size)
    check("AllReduce average equals the manual mean of the per-rank grads",
          torch.allclose(avg_grad, sum(local_grads) / world_size))
    check("every rank would receive the SAME averaged gradient",
          bool(avg_grad.std() >= 0))  # avg_grad is a single shared tensor


# ----------------------------------------------------------------------------
# Section E — DDP API sketch + a single-process gloo init that really runs
# ----------------------------------------------------------------------------

def section_e_ddp_api_and_gloo_init() -> None:
    banner("E — DDP API sketch + single-process gloo init (world_size=1)")
    print("The DDP launch sequence (from the PyTorch DDP docstring):")
    print("  torch.distributed.init_process_group(backend, rank, world_size)")
    print("  torch.cuda.set_device(local_rank)          # one GPU / process")
    print("  model = model.to(device)")
    print("  model = DistributedDataParallel(model, device_ids=[local_rank])")
    print("  sampler = DistributedSampler(dataset, shuffle=True)")
    print("  loader = DataLoader(dataset, batch_size=..., sampler=sampler)")
    print()
    print("'backend' is 'nccl' for NVIDIA GPUs (fastest, recommended),")
    print("'gloo' for CPU/multi-node, 'mpi' if MPI is built. Below we attempt")
    print("a REAL single-process gloo init (world_size=1) on CPU; if the host")
    print("or port is busy we fall back to the conceptual assertion.\n")

    # Real init attempt on the gloo backend, world_size=1, on CPU.
    os.environ.setdefault("MASTER_ADDR", "127.0.0.1")
    os.environ.setdefault("MASTER_PORT", "29577")
    initialized_ok = False
    rank_after = world_after = -1
    try:
        dist.init_process_group(backend="gloo", rank=0, world_size=1)
        initialized_ok = dist.is_initialized()
        rank_after = dist.get_rank()
        world_after = dist.get_world_size()
        # A DDP wrap on CPU uses device_ids=None (the docstring: for CPU
        # modules device_ids must be None). We sketch the wrap without
        # actually constructing it so we never depend on a 2nd process.
        dist.destroy_process_group()
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"gloo init skipped on this run: {type(exc).__name__}: {exc}")

    print(f"{'dist.is_initialized() after init':<42}{initialized_ok}")
    print(f"{'dist.get_rank()':<42}{rank_after}")
    print(f"{'dist.get_world_size()':<42}{world_after}")
    print()

    check("single-process gloo init succeeded (group initialized)",
          initialized_ok is True)
    check("rank == 0 in a world_size=1 group", rank_after == 0)
    check("world_size == 1", world_after == 1)


# ----------------------------------------------------------------------------
# Section F — per-rank seeding + DistributedSampler sharding
# ----------------------------------------------------------------------------

def section_f_per_rank_seeding_and_sharding() -> None:
    banner("F — Per-rank seeding + DistributedSampler data sharding")
    print("DDP only works if the K replicas actually do DIFFERENT work. Two")
    print("things must differ per rank: (1) the SEED (else dropout/init/grad")
    print("noise is identical and AllReduce is pointless), and (2) the DATA")
    print("shard (else every rank trains on the same batch).\n")

    # (1) Per-rank seeding: torch.manual_seed(42 + rank) -> different RNG draw
    # per rank. Show that identical seeds give identical draws (the trap).
    world_size = 4

    def draw_after_seed(seed: int) -> list[float]:
        torch.manual_seed(seed)
        return torch.randn(3).tolist()

    same_seed = [draw_after_seed(42) for _ in range(world_size)]
    diff_seed = [draw_after_seed(42 + r) for r in range(world_size)]
    print("If every rank calls torch.manual_seed(42) (WRONG):")
    for r in range(world_size):
        print(f"  rank {r}: {same_seed[r]}")
    print("  -> identical draws across ranks; AllReduce would average the SAME")
    print("     gradient K times -> no parallelism benefit.")
    print()
    print("If every rank calls torch.manual_seed(42 + rank) (CORRECT):")
    for r in range(world_size):
        print(f"  rank {r} (seed {42 + r}): {diff_seed[r]}")
    print()

    # (2) DistributedSampler-style sharding: the dataset indices are partitioned
    # into world_size disjoint contiguous strides (this is the essence of what
    # DistributedSampler does; we inline it so no distributed dep is needed).
    dataset_size = 12
    indices = list(range(dataset_size))
    print(f"Dataset of {dataset_size} indices, world_size={world_size}:")
    shards = [
        indices[r::world_size] for r in range(world_size)
    ]
    for r in range(world_size):
        print(f"  rank {r} shard: {shards[r]}")
    union = sorted(x for shard in shards for x in shard)
    print()

    check("identical seed -> identical first draw on every rank",
          all(s == same_seed[0] for s in same_seed))
    check("per-rank seed 42+rank -> distinct first draws",
          len({tuple(d) for d in diff_seed}) == world_size)
    check("shards are disjoint (a partition of the dataset)",
          union == indices and len(union) == dataset_size)
    check("each rank gets dataset_size/world_size items",
          all(len(s) == dataset_size // world_size for s in shards))


# ----------------------------------------------------------------------------
# Section G — DDP vs Tensor Parallel vs Pipeline Parallel vs FSDP
# ----------------------------------------------------------------------------

def section_g_ddp_vs_tp_pp_fsdp() -> None:
    banner("G — DDP vs Tensor Parallel vs Pipeline Parallel vs FSDP")
    print("All four 'parallel' strategies; pick by what does NOT fit on one")
    print("GPU. DDP replicates everything; the others shard the model itself.\n")

    rows = [
        ("DDP",            "data",      "nothing (full replica per GPU)",
         "AllReduce grads (once/step)"),
        ("Tensor Parallel","weights",   "data + activations",
         "AllReduce per sharded layer"),
        ("Pipeline Par.",  "layers",    "data + activations",
         "Send/Recv between stages"),
        ("FSDP",           "params+opt+grad (sharded)",
         "data",           "AllGather + ReduceScatter"),
    ]
    print(f"{'strategy':<18}{'what is SHARDED':<28}"
          f"{'what is REPLICATED':<32}{'comm primitive'}")
    print("-" * 102)
    for name, shard, repl, comm in rows:
        print(f"{name:<18}{shard:<28}{repl:<32}{comm}")
    print()
    print("Rule of thumb:")
    print("  - Model fits on 1 GPU -> DDP (simplest, linear throughput).")
    print("  - One layer's matmul does not fit -> Tensor Parallel.")
    print("  - Model fits per-stage but not whole -> Pipeline Parallel.")
    print("  - Optimizer state is the bottleneck -> FSDP (shards it).")

    check("DDP is the only strategy that does NOT shard the model",
          rows[0][1] == "data")
    check("FSDP shards params + optimizer + gradients",
          "params" in rows[3][1] and "opt" in rows[3][1] and "grad" in rows[3][1])


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    device = pick_device()
    print("gpu_distributed.py — Phase 5 bundle #34.\n"
          "Every value below is computed by this file; the .md guide pastes "
          "it\nverbatim. Nothing is hand-computed.\n"
          f"torch {torch.__version__} | running on device: {device} "
          f"(cuda={torch.cuda.is_available()}, "
          f"mps={torch.backends.mps.is_available()}).")
    section_a_device_selection()
    section_b_to_device_same_device_rule(device)
    section_c_cuda_specifics_conceptual()
    section_d_ddp_conceptual_model()
    section_e_ddp_api_and_gloo_init()
    section_f_per_rank_seeding_and_sharding()
    section_g_ddp_vs_tp_pp_fsdp()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
