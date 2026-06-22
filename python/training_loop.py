"""
training_loop.py — Phase 5 bundle #33.

GOAL (one line): show, by printing every value, that the PyTorch training step
is a precise ritual — optimizer.zero_grad() -> loss.backward() ->
optimizer.step() — and that you control it with optimizer choice, lr
schedulers, train()/eval() mode, gradient clipping, and checkpointing.

This is the GROUND TRUTH for TRAINING_LOOP.md. Every number and worked example
in the guide is printed by this file. Change it -> re-run -> re-paste. Never
hand-compute.

Deterministic: torch.manual_seed(0) before each model construction; CPU only.

Run:
    uv run python training_loop.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

BANNER = "=" * 70


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


def _toy_data() -> tuple[torch.Tensor, torch.Tensor]:
    """Toy regression: y = 3x - 1 on 16 evenly-spaced points in [0, 1]."""
    X = torch.linspace(0, 1, 16).unsqueeze(1)
    Y = 3.0 * X - 1.0
    return X, Y


# ----------------------------------------------------------------------------
# Section A — the canonical step: zero_grad -> backward -> step (loss drops)
# ----------------------------------------------------------------------------

def section_a_canonical_step() -> None:
    banner("A — The canonical step: zero_grad() -> backward() -> step()")
    torch.manual_seed(0)
    X, Y = _toy_data()
    model = nn.Linear(1, 1)
    opt = optim.SGD(model.parameters(), lr=0.1)
    loss_fn = nn.MSELoss()

    initial = loss_fn(model(X), Y).item()
    for _ in range(300):
        opt.zero_grad()
        loss = loss_fn(model(X), Y)
        loss.backward()
        opt.step()
    final = loss_fn(model(X), Y).item()

    print("Toy regression y=3x-1; nn.Linear(1,1); SGD lr=0.1; 300 full-batch")
    print("steps. The canonical ritual per PyTorch docs (optim.html):\n")
    print("  for ...:")
    print("      optimizer.zero_grad()   # 1. clear accumulated grads")
    print("      loss = loss_fn(model(x), y)")
    print("      loss.backward()         # 2. autograd fills .grad  (AUTOGRAD)")
    print("      optimizer.step()        # 3. update params using .grad\n")
    print(f"{'initial loss':<28}{initial:.6f}")
    print(f"{'final loss (300 steps)':<28}{final:.6f}")
    print(f"{'true weight / bias':<28}3.0  -1.0")
    print(f"{'learned weight':<28}{model.weight.item():.6f}")
    print(f"{'learned bias':<28}{model.bias.item():.6f}")
    print()
    check("final loss < initial loss (the ritual works)", final < initial)
    check("loss dropped below 0.001", final < 0.001)


# ----------------------------------------------------------------------------
# Section B — zero_grad is MANDATORY: grads accumulate without it
# ----------------------------------------------------------------------------

def section_b_zero_grad_mandatory() -> None:
    banner("B — zero_grad() is MANDATORY: grads accumulate without it")
    torch.manual_seed(0)
    X, Y = _toy_data()
    loss_fn = nn.MSELoss()

    # WITHOUT zero_grad: 3 backward passes, no step -> grads pile up.
    torch.manual_seed(0)
    model_a = nn.Linear(1, 1)
    norms_nz: list[float] = []
    for i in range(3):
        loss = loss_fn(model_a(X), Y)
        loss.backward()  # no zero_grad — grads accumulate
        norms_nz.append(model_a.weight.grad.abs().item())
    # WITH zero_grad: grads reset each backward.
    torch.manual_seed(0)
    model_b = nn.Linear(1, 1)
    opt = optim.SGD(model_b.parameters(), lr=0.1)
    norms_w: list[float] = []
    for i in range(3):
        opt.zero_grad()
        loss = loss_fn(model_b(X), Y)
        loss.backward()
        norms_w.append(model_b.weight.grad.abs().item())

    print("backward() ADDS to .grad (does NOT overwrite). So skipping")
    print("zero_grad makes grads from every previous step pile up.\n")
    print(f"{'step':<8}{'|grad| WITHOUT zero_grad':<30}"
          f"{'|grad| WITH zero_grad'}")
    print("-" * 64)
    for i in range(3):
        print(f"{i + 1:<8}{norms_nz[i]:<30.6f}{norms_w[i]:.6f}")
    print()
    check("WITHOUT zero_grad: 2nd grad > 1st (accumulated)",
          norms_nz[1] > norms_nz[0])
    check("WITHOUT zero_grad: 3rd grad ~ 3x 1st (linear accumulation)",
          abs(norms_nz[2] - 3 * norms_nz[0]) < 1e-5)
    check("WITH zero_grad: grads stay constant across steps",
          abs(norms_w[0] - norms_w[1]) < 1e-8
          and abs(norms_w[1] - norms_w[2]) < 1e-8)


# ----------------------------------------------------------------------------
# Section C — SGD vs Adam: Adam converges faster on this toy problem
# ----------------------------------------------------------------------------

def section_c_sgd_vs_adam() -> None:
    banner("C — Optimizers: SGD vs Adam (Adam converges faster)")
    torch.manual_seed(0)
    X, Y = _toy_data()
    base = nn.Linear(1, 1)  # shared initial weights
    loss_fn = nn.MSELoss()
    n_steps = 50

    # SGD (vanilla — no momentum)
    m_sgd = nn.Linear(1, 1)
    m_sgd.load_state_dict(base.state_dict())
    opt_sgd = optim.SGD(m_sgd.parameters(), lr=0.1)
    for _ in range(n_steps):
        opt_sgd.zero_grad()
        loss_fn(m_sgd(X), Y).backward()
        opt_sgd.step()
    sgd_loss = loss_fn(m_sgd(X), Y).item()

    # Adam (default betas=(0.9, 0.999))
    m_adam = nn.Linear(1, 1)
    m_adam.load_state_dict(base.state_dict())
    opt_adam = optim.Adam(m_adam.parameters(), lr=0.1)
    for _ in range(n_steps):
        opt_adam.zero_grad()
        loss_fn(m_adam(X), Y).backward()
        opt_adam.step()
    adam_loss = loss_fn(m_adam(X), Y).item()

    print(f"Same init, same data, {n_steps} steps, lr=0.1 for both.\n")
    print(f"{'optimizer':<22}{'final loss':<16}{'learned w':<14}{'learned b'}")
    print("-" * 64)
    print(f"{'SGD (vanilla)':<22}{sgd_loss:<16.6f}"
          f"{m_sgd.weight.item():<14.6f}{m_sgd.bias.item():.6f}")
    print(f"{'Adam (b=0.9,0.999)':<22}{adam_loss:<16.6f}"
          f"{m_adam.weight.item():<14.6f}{m_adam.bias.item():.6f}")
    print(f"\n{'true weight / bias':<22}{'':<16}{'3.000000':<14}-1.000000")
    print()
    check("Adam loss <= SGD loss at same step count", adam_loss <= sgd_loss)


# ----------------------------------------------------------------------------
# Section D — loss functions: MSELoss + CrossEntropyLoss (logits, not one-hot)
# ----------------------------------------------------------------------------

def section_d_loss_functions() -> None:
    banner("D — MSELoss (regression) + CrossEntropyLoss (logits, not softmax)")
    # --- MSELoss ---
    pred = torch.tensor([1.0, 2.0, 3.0])
    target = torch.tensor([1.5, 2.0, 2.5])
    mse = nn.MSELoss()(pred, target).item()
    hand_mse = ((pred - target) ** 2).mean().item()

    # --- CrossEntropyLoss: raw logits (N,C) + integer labels (N,) ---
    logits = torch.tensor([[0.5, -0.5, 1.0], [0.1, 2.0, -0.3]])
    labels = torch.tensor([2, 1])  # class indices, dtype=torch.long
    ce = nn.CrossEntropyLoss()(logits, labels).item()
    nll = nn.NLLLoss()(nn.LogSoftmax(dim=1)(logits), labels).item()

    # Pitfall: passing softmax(logits) double-applies softmax -> wrong loss
    ce_double = nn.CrossEntropyLoss()(
        nn.Softmax(dim=1)(logits), labels
    ).item()

    print("MSELoss: mean((pred - target)^2)")
    print(f"  pred   = {pred.tolist()}")
    print(f"  target = {target.tolist()}")
    print(f"  MSELoss = {mse:.6f}   hand = {hand_mse:.6f}")
    print()
    print("CrossEntropyLoss expects RAW LOGITS + INTEGER class indices.")
    print(f"  logits = {[[round(v, 3) for v in row] for row in logits.tolist()]}")
    print(f"  labels = {labels.tolist()}  (dtype={labels.dtype})")
    print(f"  CE(logits, labels)              = {ce:.6f}")
    print(f"  LogSoftmax+NLLLoss               = {nll:.6f}  (identical)")
    print(f"  CE(softmax(logits), labels)      = {ce_double:.6f}  "
          "(PITFALL: double-softmax)")
    print()
    check("MSELoss == hand-computed mean squared error",
          abs(mse - hand_mse) < 1e-7)
    check("CrossEntropyLoss == LogSoftmax + NLLLoss", abs(ce - nll) < 1e-6)
    check("softmax(logits) gives a DIFFERENT (wrong) loss",
          abs(ce - ce_double) > 0.01)


# ----------------------------------------------------------------------------
# Section E — train()/eval(): toggling mode (Dropout/BatchNorm)
# ----------------------------------------------------------------------------

def section_e_train_eval() -> None:
    banner("E — train()/eval(): toggling self.training (Dropout)")
    torch.manual_seed(0)
    model = nn.Sequential(nn.Linear(4, 4), nn.Dropout(p=0.5))
    x = torch.ones(1, 4)

    model.train()
    train_flag = model.training
    torch.manual_seed(0)
    out_a = model(x)
    torch.manual_seed(1)
    out_b = model(x)

    model.eval()
    eval_flag = model.training
    out_c = model(x)
    out_d = model(x)

    print("model.train() sets self.training=True (recursive). Dropout zeros")
    print("and scales active units. model.eval() sets it False -> Dropout is")
    print("the identity. Always eval() before validation/inference. (NN_MODULE)\n")
    print(f"{'model.training after train()':<42}{train_flag}")
    print(f"{'model.training after eval()':<42}{eval_flag}")
    print(f"{'train: out(seed=0) == out(seed=1)?':<42}{torch.equal(out_a, out_b)}")
    print(f"{'eval:  out == out (deterministic)?':<42}{torch.equal(out_c, out_d)}")
    print()
    check("train() sets training=True", train_flag is True)
    check("eval() sets training=False", eval_flag is False)
    check("train mode: different RNG seeds give different outputs",
          not torch.equal(out_a, out_b))
    check("eval mode: output is deterministic (no dropout)",
          torch.equal(out_c, out_d))


# ----------------------------------------------------------------------------
# Section F — lr scheduler: StepLR / CosineAnnealingLR change lr per epoch
# ----------------------------------------------------------------------------

def section_f_lr_scheduler() -> None:
    banner("F — lr scheduler: StepLR / CosineAnnealingLR (lr changes per epoch)")
    torch.manual_seed(0)
    model = nn.Linear(2, 1)

    # StepLR: gamma=0.1 every step_size=2 epochs.
    opt = optim.SGD(model.parameters(), lr=0.1)
    sched = optim.lr_scheduler.StepLR(opt, step_size=2, gamma=0.1)
    lrs_step: list[float] = []
    for _ in range(6):
        lrs_step.append(opt.param_groups[0]["lr"])
        opt.step()
        opt.zero_grad()
        sched.step()  # call AFTER optimizer.step(), once per epoch

    # CosineAnnealingLR: cosine from initial lr to eta_min over T_max epochs.
    opt2 = optim.SGD(model.parameters(), lr=0.1)
    sched2 = optim.lr_scheduler.CosineAnnealingLR(opt2, T_max=6)
    lrs_cos: list[float] = []
    for _ in range(6):
        lrs_cos.append(opt2.param_groups[0]["lr"])
        opt2.step()
        opt2.zero_grad()
        sched2.step()

    print("scheduler.step() is called ONCE PER EPOCH, AFTER optimizer.step().\n")
    print(f"{'epoch':<8}{'StepLR lr':<18}{'CosineAnnealingLR lr'}")
    print("-" * 44)
    for e in range(6):
        print(f"{e:<8}{lrs_step[e]:<18.6f}{lrs_cos[e]:.6f}")
    print()
    check("StepLR: lr at epoch 0 == 0.1", abs(lrs_step[0] - 0.1) < 1e-12)
    check("StepLR: lr decays to 0.01 at epoch 2 (step_size=2, gamma=0.1)",
          abs(lrs_step[2] - 0.01) < 1e-12)
    check("StepLR: lr decays to 0.001 at epoch 4",
          abs(lrs_step[4] - 0.001) < 1e-12)
    check("CosineAnnealingLR: lr changes across epochs",
          len(set(round(v, 8) for v in lrs_cos)) > 1)
    check("CosineAnnealingLR: starts at initial lr (0.1)",
          abs(lrs_cos[0] - 0.1) < 1e-12)
    check("CosineAnnealingLR: ends near eta_min=0",
          lrs_cos[-1] < 0.01)


# ----------------------------------------------------------------------------
# Section G — gradient clipping: clip_grad_norm_ caps the total grad norm
# ----------------------------------------------------------------------------

def section_g_gradient_clipping() -> None:
    banner("G — clip_grad_norm_: caps the total gradient L2 norm")
    p = nn.Parameter(torch.tensor([3.0, 4.0]))
    p.grad = torch.tensor([3.0, 4.0])  # L2 norm = 5.0
    max_norm = 1.0

    before = p.grad.clone()
    norm_before = p.grad.norm().item()
    total_norm = nn.utils.clip_grad_norm_(
        [p], max_norm
    ).item()
    norm_after = p.grad.norm().item()

    print("clip_grad_norm_ computes the total L2 norm over all param grads,")
    print("and if it exceeds max_norm, scales ALL grads by max_norm/total_norm")
    print("(in-place). Call it AFTER backward(), BEFORE optimizer.step().\n")
    print(f"{'grad before clip':<28}{before.tolist()}  norm={norm_before:.1f}")
    print(f"{'total_norm (returned)':<28}{total_norm:.6f}")
    print(f"{'max_norm':<28}{max_norm}")
    print(f"{'grad after clip':<28}"
          f"{[round(v, 4) for v in p.grad.tolist()]}  norm={norm_after:.6f}")
    print(f"{'scale factor':<28}{max_norm / norm_before:.6f}")
    print()
    check("total_norm returned == original norm (5.0)",
          abs(total_norm - 5.0) < 1e-6)
    check("clipped grad norm <= max_norm", norm_after <= max_norm + 1e-6)
    check("grad was scaled to [0.6, 0.8] (3*0.2, 4*0.2)",
          torch.allclose(p.grad, torch.tensor([0.6, 0.8]), atol=1e-6))


# ----------------------------------------------------------------------------
# Section H — checkpointing: torch.save / torch.load + state_dict
# ----------------------------------------------------------------------------

def section_h_checkpoint() -> None:
    banner("H — Checkpointing: torch.save(model.state_dict(), path)")
    torch.manual_seed(0)
    model = nn.Linear(3, 2)

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "model.pt"
        torch.save(model.state_dict(), path)

        loaded = nn.Linear(3, 2)
        loaded.load_state_dict(torch.load(path, weights_only=True))

        sd_saved = model.state_dict()
        sd_loaded = loaded.state_dict()
        keys_match = set(sd_saved) == set(sd_loaded)
        all_equal = all(
            torch.equal(sd_saved[k], sd_loaded[k]) for k in sd_saved
        )

    print("torch.save serializes the state_dict (params + persistent buffers)")
    print("to disk; torch.load + load_state_dict restores them into a fresh")
    print("model.  (NN_MODULE state_dict)\n")
    print(f"{'saved keys':<32}{list(sd_saved.keys())}")
    print(f"{'keys match after round-trip':<32}{keys_match}")
    print(f"{'all tensors equal':<32}{all_equal}")
    print()
    check("saved and loaded state_dict keys match", keys_match)
    check("all params equal after save/load round-trip", all_equal)


# ----------------------------------------------------------------------------
# Section I — the full loop: epoch x batch via DataLoader
# ----------------------------------------------------------------------------

def section_i_full_loop() -> None:
    banner("I — Full epoch loop over a DataLoader (forward->loss->step)")
    torch.manual_seed(0)
    X, Y = _toy_data()
    ds = TensorDataset(X, Y)
    dl = DataLoader(ds, batch_size=4, shuffle=False)  # (DATA_LOADING)

    model = nn.Linear(1, 1)
    opt = optim.SGD(model.parameters(), lr=0.1)
    loss_fn = nn.MSELoss()

    losses: list[float] = []
    for epoch in range(50):
        epoch_loss = 0.0
        n = 0
        for xb, yb in dl:
            opt.zero_grad()
            pred = model(xb)
            loss = loss_fn(pred, yb)
            loss.backward()
            opt.step()
            epoch_loss += loss.item()
            n += 1
        avg = epoch_loss / n
        losses.append(avg)

    print("TensorDataset(16 pts) -> DataLoader(batch_size=4) -> 4 batches/"
          "epoch x 50 epochs. Mini-batch SGD lr=0.1.\n")
    print(f"{'epoch':<8}{'avg loss (over 4 batches)'}")
    print("-" * 32)
    for e in range(0, 50, 10):
        print(f"{e:<8}{losses[e]:.6f}")
    print(f"{49:<8}{losses[49]:.6f}")
    print()
    check("loss decreases across epochs (final < first)",
          losses[-1] < losses[0])
    check("final epoch loss < 0.05", losses[-1] < 0.05)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    torch.manual_seed(0)
    print("training_loop.py — Phase 5 bundle #33.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed.\n"
          f"torch {torch.__version__} on CPU.")
    section_a_canonical_step()
    section_b_zero_grad_mandatory()
    section_c_sgd_vs_adam()
    section_d_loss_functions()
    section_e_train_eval()
    section_f_lr_scheduler()
    section_g_gradient_clipping()
    section_h_checkpoint()
    section_i_full_loop()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
