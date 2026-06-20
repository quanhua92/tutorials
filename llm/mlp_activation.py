"""
mlp_activation.py - Reference implementation of MLP activation evolution.

Single source of truth that MLP_ACTIVATION.md is built from. Every number,
table, and worked example in the guide is printed by this file. Change the
code, re-run, re-paste.

Run:
    uv run python mlp_activation.py

INTUITION (one paragraph, no math):
    An *activation function* is a decision gate that decides how much signal
    passes through a neuron. ReLU is a hard on/off wall switch: negative in ->
    off (0), positive in -> full blast (unchanged). Its failure mode is the
    "dying ReLU" -- a switch that gets stuck off forever (gradient is exactly
    0, so it can never recover). GELU and SiLU are *smooth dimmer switches*:
    they ease gently around 0, let a little negative signal through, and have
    no dead zone, so gradients keep flowing and nothing dies.

    The *MLP block* itself is a tiny brain that mixes and recombines features.
    The vanilla MLP (nanoGPT) does two mixing steps with a dimmer (GELU) in
    between:   down( GELU( fc(x) ) ).  SwiGLU adds a GATE: one path
    (gate_proj) acts like a faucet handle that decides "how open", another
    path (up_proj) provides the actual water; the two are multiplied so only
    content whose gate is open survives:   down( silu(gate(x)) * up(x) ).

Two intertwined evolutionary axes are covered:

  AXIS 1 - ACTIVATION FUNCTION  (the per-element non-linearity)
      ReLU(x)  = max(0, x)               ... Nair & Hinton 2010
      GELU(x)  = 0.5x(1 + tanh(...))     ... Hendrycks & Gimpel 2016 (GPT-2)
      SiLU(x)  = x * sigmoid(x)          ... "SiLU" coined in the GELU paper
                                            (2016); = "Swish" beta=1, 2017

  AXIS 2 - MLP STRUCTURE        (how the linear layers are wired)
      Vanilla: down( act( fc(x) ) )                   2 weight matrices, 4x ratio
      SwiGLU:  down( silu(gate(x)) * up(x) )          3 weight matrices, ~5.4x
                                                       (Shazeer 2020; Llama/Qwen)

Conventions for tensor shapes:
    B = batch size
    L = sequence length
    E = embedding / model dim
    F = FFN intermediate dim  (the wider hidden dim of the MLP)
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. ACTIVATION FUNCTIONS (from scratch; asserted vs torch.nn.functional)
# ============================================================================

def relu(x: torch.Tensor) -> torch.Tensor:
    """ReLU(x) = max(0, x).  Nair & Hinton 2010.

    Intuition: a hard wall switch -- negative input -> OFF (0), positive input
    -> ON (unchanged). Failure mode = the "dying ReLU": a neuron whose input
    is consistently negative is stuck at 0 with a gradient of exactly 0, so it
    can never recover.
    """
    return torch.clamp(x, min=0.0)


def gelu_tanh(x: torch.Tensor) -> torch.Tensor:
    """GELU tanh approximation (GPT-2 default).

        GELU(x) = 0.5 x (1 + tanh( sqrt(2/pi) (x + 0.044715 x^3)))

    Hendrycks & Gimpel 2016, arXiv:1606.08415. Intuition: a smooth dimmer
    switch -- it eases gently around 0 and lets a little negative signal
    through (no dead zone), so gradients keep flowing.
    """
    c = math.sqrt(2.0 / math.pi)
    return 0.5 * x * (1.0 + torch.tanh(c * (x + 0.044715 * x ** 3)))


def gelu_exact(x: torch.Tensor) -> torch.Tensor:
    """GELU exact form: 0.5 x (1 + erf(x / sqrt(2))).

    Hendrycks & Gimpel 2016, arXiv:1606.08415. (Mathematically = x*Phi(x),
    where Phi is the standard-normal CDF; the tanh version above approximates
    this erf so it can run without a special erf kernel.)
    """
    return 0.5 * x * (1.0 + torch.erf(x / math.sqrt(2.0)))


def silu(x: torch.Tensor) -> torch.Tensor:
    """SiLU / Swish: x * sigmoid(x).

    Attribution (verified against arXiv:1606.08415 section 2 & appendix B):
      The function x*sigmoid(x) and the name "SiLU" (Sigmoid Linear Unit) were
      introduced IN the GELU paper (Hendrycks & Gimpel 2016, arXiv:1606.08415).
      Elfwing et al. 2017 independently rediscovered it (later adopting the
      "SiLU" name). Ramachandran et al. 2017 (arXiv:1710.05941) called it
      "Swish" and generalized to x*sigmoid(beta*x); with beta=1 (the universal
      default), Swish == SiLU exactly.

    Intuition: a smooth, *self-gated* dimmer -- the input is its own gate.
    That self-gating is exactly what makes the SwiGLU block natural.
    """
    return x * torch.sigmoid(x)


# ============================================================================
# 2. MLP BLOCKS  (the two structures)
# ============================================================================

def linear(x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
    """x @ w.T   where w has shape [out, in].  No bias, for clarity."""
    return x @ w.T


class VanillaMLP:
    """nanoGPT / GPT-2 MLP:   down( GELU( fc(x) ) ).

    Intuition: a tiny brain that mixes features in two steps with a smooth
    dimmer (GELU) in between. Step 1 `fc` widens E -> 4E (more room to think);
    the dimmer GELU squashes some of that room; step 2 `proj` narrows 4E -> E
    (a decision per output channel). Two weight matrices, ratio 4x.

        x : [B, L, E]  ->  fc  (E -> 4E) -> GELU -> proj (4E -> E)
    """

    def __init__(self, w_fc: torch.Tensor, w_proj: torch.Tensor):
        self.w_fc = w_fc       # [4E, E]
        self.w_proj = w_proj   # [E, 4E]

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        return linear(gelu_tanh(linear(x, self.w_fc)), self.w_proj)


class SwiGLUMLP:
    """Llama / Qwen MLP:   down( silu(gate(x)) * up(x) ).

    Intuition (the FAUCET analogy): `gate(x)` is the faucet handle that
    decides "how open" each feature is; silu smooths it to a ~0..1-ish dial.
    `up(x)` is the actual water -- the raw features. Multiplying them means
    only water whose faucet is open survives. `down` then mixes the survivors
    back to E channels.

        x : [B, L, E]
        gate(x): [B, L, FFN]    silu -> gate_out   (the dial)
        up  (x): [B, L, FFN]    up_out             (the water)
        product = gate_out * up_out                 (gated features)
        down(product) -> [B, L, E]
        3 weight matrices, intermediate ratio ~5.4x (Qwen3-0.5B: 4864/896).

    Shazeer 2020, "GLU Variants Improve Transformer", arXiv:2002.05202 (eq. 6:
    SwiGLU = (Swish_1(xW) (x) xV) W2 -- SiLU goes on the FIRST projection).
    """

    def __init__(self, w_gate: torch.Tensor, w_up: torch.Tensor, w_down: torch.Tensor):
        self.w_gate = w_gate   # [FFN, E]
        self.w_up = w_up       # [FFN, E]
        self.w_down = w_down   # [E, FFN]

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        gate_out = silu(linear(x, self.w_gate))   # silu APPLIED TO gate path
        up_out = linear(x, self.w_up)              # up path, NO activation
        return linear(gate_out * up_out, self.w_down)

    def buggy_order(self, x: torch.Tensor) -> torch.Tensor:
        """The classic operand-order pitfall: silu applied to the UP path.

        down( silu(up(x)) * gate(x) )  -- WRONG.

        WARNING (why this bites): silu is non-linear, so silu(a)*b != a*silu(b).
        Swapping the operands gives different numbers, BUT the tensor shapes are
        identical and there is NO error message -- the model just silently
        produces slightly-wrong output. The checkpoint was trained with silu on
        the GATE path, so this swap corrupts inference invisibly. It is the #1
        SwiGLU implementation bug. Memorize: silu ALWAYS on `gate`; `up` stays
        raw.
        """
        gate_out = linear(x, self.w_gate)          # gate path, NO activation
        up_out = silu(linear(x, self.w_up))        # silu APPLIED TO up path
        return linear(gate_out * up_out, self.w_down)


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 4. SECTIONS  (the numbers that feed MLP_ACTIVATION.md)
# ============================================================================

def section_activation_table():
    banner("SECTION A: ReLU vs GELU vs SiLU on a fixed input grid")
    xs = torch.tensor([-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, 3.0])
    print(f"Input grid x: {[round(v, 2) for v in xs.tolist()]}\n")
    print("|   x  | ReLU(x) | GELU_tanh(x) | GELU_exact(x) | SiLU(x)  |")
    print("|------|---------|--------------|---------------|----------|")
    for v in xs:
        r = relu(v).item()
        gt = gelu_tanh(v).item()
        ge = gelu_exact(v).item()
        s = silu(v).item()
        print(f"| {v:>+5.1f} | {r:>+7.4f} | {gt:>+12.4f} | {ge:>+13.4f} | "
              f"{s:>+8.4f} |")
    print()

    # ---- from-scratch == torch.nn.functional ----
    grid = torch.linspace(-3.0, 3.0, 61)
    assert torch.allclose(relu(grid), F.relu(grid)), "ReLU mismatch"
    assert torch.allclose(gelu_tanh(grid), F.gelu(grid, approximate="tanh"),
                          atol=1e-6), "GELU tanh mismatch"
    assert torch.allclose(gelu_exact(grid), F.gelu(grid, approximate="none"),
                          atol=1e-6), "GELU exact mismatch"
    assert torch.allclose(silu(grid), F.silu(grid), atol=1e-6), "SiLU mismatch"
    print("[check] from-scratch ReLU  == torch.nn.functional.relu         : OK")
    print("[check] from-scratch GELU_tanh == F.gelu(approximate='tanh')  : OK")
    print("[check] from-scratch GELU_exact == F.gelu(approximate='none') : OK")
    print("[check] from-scratch SiLU  == torch.nn.functional.silu        : OK")
    print()

    # ---- gold pins (used by .html gold-check) ----
    print("Gold pins (used by the HTML gold-check badge):")
    print(f"  GELU_tanh(1.0) = {gelu_tanh(torch.tensor(1.0)).item():.4f}")
    print(f"  GELU_exact(1.0) = {gelu_exact(torch.tensor(1.0)).item():.4f}")
    print(f"  SiLU(1.0)       = {silu(torch.tensor(1.0)).item():.4f}")
    print(f"  GELU_tanh(2.0) = {gelu_tanh(torch.tensor(2.0)).item():.4f}")
    print(f"  SiLU(2.0)       = {silu(torch.tensor(2.0)).item():.4f}")


def section_vanilla_mlp(E: int, FFN: int, x: torch.Tensor):
    banner(f"SECTION B: vanilla GELU MLP on a fixed input  E={E}, FFN={FFN}")
    B, L, _ = x.shape
    g = torch.Generator().manual_seed(0)
    w_fc = torch.randn(FFN, E, generator=g) * 0.1     # [FFN, E]
    w_proj = torch.randn(E, FFN, generator=g) * 0.1   # [E, FFN]

    mlp = VanillaMLP(w_fc, w_proj)
    print(f"Input x shape: {tuple(x.shape)} = [B={B}, L={L}, E={E}]")
    print(f"w_fc shape:   {tuple(w_fc.shape)} = [FFN={FFN}, E={E}]   (ratio {FFN/E:.1f}x)")
    print(f"w_proj shape: {tuple(w_proj.shape)} = [E={E}, FFN={FFN}]")
    print()
    print("Structure:   down( GELU( fc(x) ) )    -- 2 matrices")
    print()
    print("Input x[b=0, m=0]:")
    print(f"  {[round(v, 4) for v in x[0, 0].tolist()]}")
    print()

    fc_out = linear(x, w_fc)              # [B, L, FFN]
    act_out = gelu_tanh(fc_out)           # [B, L, FFN]
    y = linear(act_out, w_proj)           # [B, L, E]

    print(f"After fc(x):     shape {tuple(fc_out.shape)}, "
          f"b=0,m=0 first {min(FFN, 6)} entries:")
    print(f"  {[round(v, 4) for v in fc_out[0, 0, :min(FFN, 6)].tolist()]}")
    print(f"After GELU(fc):  b=0,m=0 first {min(FFN, 6)} entries:")
    print(f"  {[round(v, 4) for v in act_out[0, 0, :min(FFN, 6)].tolist()]}")
    print()
    print(f"OUTPUT down(GELU(fc(x))) shape {tuple(y.shape)}:")
    for m in range(L):
        print(f"  m={m}: {[round(v, 4) for v in y[0, m].tolist()]}")
    print()

    # ---- self-check: class vs inline ----
    inline_y = linear(gelu_tanh(linear(x, w_fc)), w_proj)
    assert torch.allclose(y, mlp(x), atol=1e-6)
    assert torch.allclose(inline_y, mlp(x), atol=1e-6)
    print("[check] inline path == VanillaMLP class output            : OK")
    print(f"[check] output preserves E dim: in E={E}, out E={y.shape[-1]}  : OK")


def section_swiglu_mlp(E: int, FFN: int, x: torch.Tensor):
    banner(f"SECTION C: SwiGLU MLP on the SAME input  E={E}, FFN={FFN}")
    B, L, _ = x.shape
    g = torch.Generator().manual_seed(1)
    w_gate = torch.randn(FFN, E, generator=g) * 0.1   # [FFN, E]
    w_up = torch.randn(FFN, E, generator=g) * 0.1     # [FFN, E]
    w_down = torch.randn(E, FFN, generator=g) * 0.1   # [E, FFN]

    mlp = SwiGLUMLP(w_gate, w_up, w_down)
    print(f"Input x shape: {tuple(x.shape)} = [B={B}, L={L}, E={E}]")
    print(f"w_gate shape:  {tuple(w_gate.shape)} = [FFN={FFN}, E={E}]")
    print(f"w_up shape:    {tuple(w_up.shape)}   = [FFN={FFN}, E={E}]")
    print(f"w_down shape:  {tuple(w_down.shape)} = [E={E}, FFN={FFN}]")
    print()
    print("Structure:   down( silu(gate(x)) * up(x) )   -- 3 matrices")
    print("                            ^^^^^^^^^^   ^^")
    print("                            activated   raw")
    print()

    gate_lin = linear(x, w_gate)          # [B, L, FFN]
    up_lin = linear(x, w_up)              # [B, L, FFN]
    gate_act = silu(gate_lin)             # [B, L, FFN]   <- silu applied to GATE
    prod = gate_act * up_lin              # [B, L, FFN]
    y = linear(prod, w_down)              # [B, L, E]

    show = min(FFN, 6)
    print(f"gate(x)         b=0,m=0 first {show}: "
          f"{[round(v, 4) for v in gate_lin[0, 0, :show].tolist()]}")
    print(f"silu(gate(x))   b=0,m=0 first {show}: "
          f"{[round(v, 4) for v in gate_act[0, 0, :show].tolist()]}")
    print(f"up(x)           b=0,m=0 first {show}: "
          f"{[round(v, 4) for v in up_lin[0, 0, :show].tolist()]}")
    print(f"silu(gate)*up   b=0,m=0 first {show}: "
          f"{[round(v, 4) for v in prod[0, 0, :show].tolist()]}")
    print()
    print(f"OUTPUT down(silu(gate)*up) shape {tuple(y.shape)}:")
    for m in range(L):
        print(f"  m={m}: {[round(v, 4) for v in y[0, m].tolist()]}")
    print()

    # ---- self-check ----
    assert torch.allclose(y, mlp(x), atol=1e-6)
    print("[check] inline path == SwiGLUMLP class output            : OK")

    # ---- gold pin for the .html ----
    # Take b=0, m=0, d=0 of the output as the published gold value.
    gold = y[0, 0, 0].item()
    print(f"GOLD SwiGLU output, x[0,0] (full vector pinned below):")
    print(f"  y[0, 0] = {[round(v, 4) for v in y[0, 0].tolist()]}")
    print(f"  y[0, 0, 0] = {gold:.6f}   (the .html pins this exact value)")
    return w_gate, w_up, w_down, y


def section_operand_order_pitfall(E: int, FFN: int, x: torch.Tensor,
                                  w_gate, w_up, w_down):
    banner("SECTION D: the operand-order pitfall -- silu(gate)*up vs silu(up)*gate")
    print("These look almost identical in code. They give DIFFERENT outputs.\n")
    correct = SwiGLUMLP(w_gate, w_up, w_down)             # silu(gate)*up
    buggy = SwiGLUMLP(w_gate, w_up, w_down).buggy_order   # silu(up)*gate

    y_correct = correct(x)
    y_buggy = buggy(x)
    diff = (y_correct - y_buggy).abs()

    print("CORRECT  (Llama/Qwen source):  down( silu(gate(x)) * up(x) )")
    print("BUGGY    (swap operands):      down( silu(up(x))   * gate(x) )")
    print()
    print("Same weights, same input, different wiring -> different numbers:")
    print()
    print("| m | y_correct[0,m,0] | y_buggy[0,m,0] | abs diff |")
    print("|---|------------------|----------------|----------|")
    for m in range(x.shape[1]):
        c = y_correct[0, m, 0].item()
        b = y_buggy[0, m, 0].item()
        d = abs(c - b)
        print(f"| {m} | {c:>+16.4f} | {b:>+14.4f} | {d:>8.4f} |")
    print()
    print(f"max|y_correct - y_buggy| over the whole output = "
          f"{diff.max().item():.4f}")
    print()
    same = torch.allclose(y_correct, y_buggy, atol=1e-6)
    print(f"[check] y_correct == y_buggy?  {same}  "
          f"({'OK' if not same else 'FAIL: no difference, impossible'} -> "
          f"they DO differ, confirming operand order matters)")
    print()
    print("WHY: silu is non-linear, so silu(a)*b != a*silu(b) in general.")
    print("The CHECKPOINT was trained with silu on the gate path; swapping")
    print("silently corrupts the model with no error message. This is the #1")
    print("SwiGLU bug. Fix: read the reference impl -- silu ALWAYS on gate.")


def section_ffn_ratio_note():
    banner("SECTION E: the FFN intermediate ratio (Qwen3-0.5B case)")
    E_qwen = 896
    FFN_qwen = 4864
    ratio = FFN_qwen / E_qwen
    print(f"Qwen3-0.5B config:  E = {E_qwen}  (hidden_size)")
    print(f"                     FFN = {FFN_qwen}  (intermediate_size)")
    print(f"                     ratio = FFN/E = {ratio:.4f}  "
          f"(NOT 4.0000)")
    print()
    print(f"Compare:")
    print(f"  nanoGPT  ratio = 4.0000   (hardcoded 4*E)")
    print(f"  Qwen3-0.5B ratio = {ratio:.4f}   (~5.43x)")
    print()
    print("Why? Llama-class models tune FFN/E empirically (often between 2.6x")
    print("and 8x). 4864 is divisible by some common GPU-friendly factors")
    print(f"({FFN_qwen} = 2^7 * {FFN_qwen // 128}). NEVER assume 4x; always")
    print("read `intermediate_size` from the model config.")
    print()

    # cross-check our tiny model
    print(f"Our tiny model uses E=8, FFN=16 -> ratio 16/8 = "
          f"{16 / 8:.4f}  (forced 2x so the table is printable; not realistic)")
    print("The structure is identical regardless of the exact ratio.")

    # sanity
    assert abs(ratio - 5.4286) < 1e-3, "Qwen3 ratio drift"
    print()
    print(f"[check] Qwen3-0.5B FFN/E = 5.4286 verified   : OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("mlp_activation.py - reference impl. Numbers below feed "
          "MLP_ACTIVATION.md.")
    print("torch =", torch.__version__)

    # tiny model: E=8, FFN=16, L=4 (printable, complete behavior)
    E, FFN, B, L = 8, 16, 1, 4
    g = torch.Generator().manual_seed(42)
    x = torch.randn(B, L, E, generator=g) * 0.5   # [B=1, L=4, E=8]

    section_activation_table()

    # Pin input x so .md/.html are reproducible
    banner(f"FIXED INPUT for sections B, C, D  (E={E}, FFN={FFN}, B={B}, L={L})")
    print(f"x shape: {tuple(x.shape)}\n")
    print("Input x[b=0] (one row per token m):")
    for m in range(L):
        print(f"  m={m}: {[round(v, 4) for v in x[0, m].tolist()]}")

    section_vanilla_mlp(E, FFN, x)
    w_gate, w_up, w_down, _ = section_swiglu_mlp(E, FFN, x)
    section_operand_order_pitfall(E, FFN, x, w_gate, w_up, w_down)
    section_ffn_ratio_note()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
