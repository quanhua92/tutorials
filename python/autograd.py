"""
autograd.py — Phase 5 bundle #30.

GOAL (one line): show, by printing every value, how PyTorch builds a DYNAMIC
computation graph as you run ops and runs reverse-mode autodiff on
.backward() — and the rules around grad accumulation, no_grad, detach, and
leaves that every training loop depends on.

This is the GROUND TRUTH for AUTOGRAD.md. Every number, table, and worked
example in the guide is printed by this file. Change it -> re-run -> re-paste.
Never hand-compute.

Run:
    uv run python autograd.py
"""

from __future__ import annotations

import torch

torch.manual_seed(0)  # deterministic; CPU default.

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers (house style, copied from types_and_truthiness.py)
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
# Section A — requires_grad + leaf tensors
# ----------------------------------------------------------------------------

def section_a_requires_grad_and_leaf() -> None:
    banner("A — requires_grad and the leaf/non-leaf rule")
    print("requires_grad=True tells autograd to track ops on this tensor. A")
    print("tensor is a LEAF if it was created directly by the user (no grad_fn)")
    print("or has requires_grad=False. Leaves are where .grad accumulates.\n")

    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    c = torch.tensor([4.0, 5.0])  # requires_grad defaults to False

    print(f"{'expression':<42}{'value'}")
    print("-" * 70)
    print(f"{'x = torch.tensor([1,2,3], requires_grad=True)':<42}")
    print(f"{'  x.requires_grad':<42}{x.requires_grad}")
    print(f"{'  x.is_leaf':<42}{x.is_leaf}")
    print(f"{'  x.grad_fn':<42}{x.grad_fn}")
    print(f"{'  x.grad (before backward)':<42}{x.grad}")
    print(f"{'c = torch.tensor([4,5]) (default)':<42}")
    print(f"{'  c.requires_grad':<42}{c.requires_grad}")
    print(f"{'  c.is_leaf':<42}{c.is_leaf}")
    print()

    check("x.requires_grad is True", x.requires_grad is True)
    check("x.is_leaf is True (created directly, requires grad)",
          x.is_leaf is True)
    check("x.grad_fn is None (leaves have no creator)", x.grad_fn is None)
    check("x.grad is None before any backward()", x.grad is None)
    check("c.requires_grad is False by default", c.requires_grad is False)
    check("c.is_leaf is True (requires_grad=False -> always leaf)",
          c.is_leaf is True)


# ----------------------------------------------------------------------------
# Section B — a forward pass builds the (dynamic) graph via grad_fn
# ----------------------------------------------------------------------------

def section_b_forward_builds_graph() -> None:
    banner("B — forward pass builds the dynamic graph (grad_fn nodes)")
    print("Each op on a tensor that requires grad attaches a grad_fn: the")
    print("backward node that knows how to differentiate that op. The graph is")
    print("DYNAMIC — rebuilt every iteration, so Python control flow is fair")
    print("game (unlike static TF1 graphs).\n")

    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    y = x**2 + 3
    z = y.sum()

    print(f"{'expression':<28}{'grad_fn':<16}{'is_leaf':<10}{'requires_grad'}")
    print("-" * 68)
    print(f"{'x':<28}{str(x.grad_fn):<16}{x.is_leaf!s:<10}{x.requires_grad}")
    print(f"{'y = x**2 + 3':<28}{type(y.grad_fn).__name__:<16}"
          f"{y.is_leaf!s:<10}{y.requires_grad}")
    print(f"{'z = y.sum()':<28}{type(z.grad_fn).__name__:<16}"
          f"{z.is_leaf!s:<10}{z.requires_grad}")
    print()

    check("z.grad_fn is not None (graph node exists)", z.grad_fn is not None)
    check("y.grad_fn is not None (AddBackward0 names the op)",
          y.grad_fn is not None)
    check("y.is_leaf is False (y was produced by an op)", not y.is_leaf)
    check("y.requires_grad is True (propagated from x)", y.requires_grad)


# ----------------------------------------------------------------------------
# Section C — backward() walks the graph in reverse, filling .grad
# ----------------------------------------------------------------------------

def section_c_backward_computes_grads() -> None:
    banner("C — backward() computes grads (reverse-mode autodiff)")
    print(".backward() walks the graph from the root (z) back to the leaves,")
    print("applying the chain rule. For y = x**2 the analytical derivative is")
    print("dy/dx = 2x; summing leaves dz/dx = 2x elementwise.\n")

    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    z = (x**2 + 3).sum()
    z.backward()

    print(f"z        = {z.item():.0f}   (1+3)+(4+3)+(9+3) = 4+7+12 = 23")
    print(f"x.grad   = {x.grad.tolist()}")
    print(f"2 * x    = {(2 * x).detach().tolist()}   (the analytical derivative)")
    print()

    check("x.grad equals the analytical derivative 2*x (y=x^2 -> dy/dx=2x)",
          torch.equal(x.grad, 2 * x.detach()))
    check("z.item() == 23", z.item() == 23.0)


# ----------------------------------------------------------------------------
# Section D — gradient ACCUMULATION (backward twice doubles .grad)
# ----------------------------------------------------------------------------

def section_d_grad_accumulation() -> None:
    banner("D — gradient accumulation: backward() ADDS to .grad")
    print(".grad is ACCUMULATED, not overwritten. Calling backward() twice on")
    print("the same graph (retain_graph=True) doubles .grad. This is exactly")
    print("why optimizers call zero_grad() every step.  (TRAINING_LOOP)\n")

    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    z = (x**2).sum()
    z.backward(retain_graph=True)
    first = x.grad.clone()
    z.backward()  # walks the SAME graph again -> adds
    second = x.grad.clone()

    print(f"{'call':<16}{'x.grad'}")
    print("-" * 32)
    print(f"{'1st backward':<16}{first.tolist()}")
    print(f"{'2nd backward':<16}{second.tolist()}")
    print(f"\n2 * first == second ?  {torch.equal(2 * first, second)}")
    print()

    check("after 2nd backward x.grad == [4, 8, 12] (doubled)",
          torch.equal(second, torch.tensor([4.0, 8.0, 12.0])))
    check("2*first == second (accumulation ADDS, not overwrites)",
          torch.equal(2 * first, second))


# ----------------------------------------------------------------------------
# Section E — torch.no_grad() / inference_mode() disable tracking
# ----------------------------------------------------------------------------

def section_e_no_grad_and_infer_mode() -> None:
    banner("E — torch.no_grad() / inference_mode() for inference")
    print("Inside these contexts no backward graph is recorded, so new tensors")
    print("have requires_grad=False and grad_fn=None. Use them for inference to")
    print("save memory and time. (infer_mode is faster but its tensors cannot")
    print("re-enter a grad-required graph.)\n")

    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)

    with torch.no_grad():
        y = x**2
    with torch.inference_mode():
        yi = x**2

    print(f"{'context':<27}{'requires_grad':<16}{'grad_fn'}")
    print("-" * 52)
    print(f"{'with torch.no_grad():':<27}{y.requires_grad!s:<16}{y.grad_fn}")
    print(f"{'with torch.infer_mode():':<27}{yi.requires_grad!s:<16}"
          f"{yi.grad_fn}")
    print()

    check("no_grad: y.requires_grad is False", not y.requires_grad)
    check("no_grad: y.grad_fn is None (no graph node)", y.grad_fn is None)
    check("inference_mode: yi.requires_grad is False", not yi.requires_grad)
    check("inference_mode: yi.grad_fn is None", yi.grad_fn is None)


# ----------------------------------------------------------------------------
# Section F — .detach() and the leaf in-place error
# ----------------------------------------------------------------------------

def section_f_detach_and_leaf_inplace() -> None:
    banner("F — .detach() and the leaf-in-place RuntimeError")
    print(".detach() returns a tensor with the same values but disconnected")
    print("from the graph (no grad_fn, is a leaf). Mutating a leaf that")
    print("requires grad IN-PLACE raises RuntimeError — autograd forbids it so")
    print("the history needed for the backward pass stays valid.\n")

    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    y = x**2
    yd = y.detach()

    print(f"{'expression':<22}{'requires_grad':<16}{'grad_fn':<16}{'is_leaf'}")
    print("-" * 64)
    print(f"{'y = x**2':<22}{y.requires_grad!s:<16}"
          f"{type(y.grad_fn).__name__:<16}{y.is_leaf}")
    print(f"{'yd = y.detach()':<22}{yd.requires_grad!s:<16}"
          f"{yd.grad_fn!s:<16}{yd.is_leaf}")
    print(f"\nvalues match: y={y.detach().tolist()}  yd={yd.tolist()}")
    print()

    check("detach: same values as y",
          torch.equal(y.detach(), yd))
    check("detach: requires_grad is False", not yd.requires_grad)
    check("detach: grad_fn is None", yd.grad_fn is None)
    check("detach: result is a leaf", yd.is_leaf)

    # The leaf in-place error.
    leaf = torch.tensor([1.0, 2.0], requires_grad=True)
    raised = False
    msg = ""
    try:
        leaf.add_(1.0)  # in-place op on a grad-requiring leaf
    except RuntimeError as exc:
        raised = True
        msg = str(exc)
    print(f"\nleaf.add_(1.0) -> RuntimeError raised? {raised}")
    print(f"message: \"{msg}\"")
    print()
    check("in-place op on a grad leaf raises RuntimeError", raised)


# ----------------------------------------------------------------------------
# Section G — a manual gradient check (analytical + numerical / gradcheck)
# ----------------------------------------------------------------------------

def section_g_manual_gradient_check() -> None:
    banner("G — manual gradient check: relu(x*w + b)")
    print("A small graph y = relu(x*w + b); L = y.sum(). We hand-derive the")
    print("expected grads, assert backward() matches, and confirm with a")
    print("finite-difference numerical check (float64, the gold standard).\n")

    # Inputs (x constant); weights/bias require grad. Use float64 so the
    # numerical (finite-difference) check is clean to ~1e-5.
    x = torch.tensor([1.0, 2.0, 0.5], dtype=torch.float64)
    w = torch.tensor([2.0, -1.0, 3.0], dtype=torch.float64, requires_grad=True)
    b = torch.tensor([1.0, -1.0, 0.0], dtype=torch.float64, requires_grad=True)

    pre = x * w + b
    y = pre.relu()
    L = y.sum()
    L.backward()

    # Hand derivation:
    #   pre = [1*2+1, 2*-1-1, 0.5*3+0] = [3, -3, 1.5]
    #   relu mask = [1, 0, 1]
    #   dL/dw = mask * x   = [1, 0, 0.5]
    #   dL/db = mask       = [1, 0, 1]
    expected_w = torch.tensor([1.0, 0.0, 0.5], dtype=torch.float64)
    expected_b = torch.tensor([1.0, 0.0, 1.0], dtype=torch.float64)

    print(f"pre       = {pre.detach().tolist()}")
    print(f"y=relu(p) = {y.detach().tolist()}")
    print(f"L = sum(y) = {L.item():.1f}")
    print(f"w.grad    = {w.grad.tolist()}   (hand-derived: {expected_w.tolist()})")
    print(f"b.grad    = {b.grad.tolist()}   (hand-derived: {expected_b.tolist()})")

    # Finite-difference numerical gradient on w (float64 -> clean).
    eps = 1e-6
    num_w = torch.zeros(3, dtype=torch.float64)
    with torch.no_grad():
        wd = w.detach()
        bd = b.detach()
        for i in range(3):
            wp = wd.clone()
            wp[i] += eps
            wm = wd.clone()
            wm[i] -= eps
            num_w[i] = ((x * wp + bd).relu().sum()
                        - (x * wm + bd).relu().sum()) / (2 * eps)
    print(f"numerical = {num_w.tolist()}  (finite-diff, eps={eps})")
    print()

    check("w.grad == hand-derived [1, 0, 0.5]",
          torch.equal(w.grad, expected_w))
    check("b.grad == hand-derived [1, 0, 1]",
          torch.equal(b.grad, expected_b))
    check("numerical grad matches analytical (atol=1e-5)",
          torch.allclose(w.grad, num_w, atol=1e-5))


# ----------------------------------------------------------------------------
# Section H — non-leaf tensors don't retain grad unless retain_grad()
# ----------------------------------------------------------------------------

def section_h_non_leaf_grad_and_retain() -> None:
    banner("H — non-leaf tensors: no .grad unless retain_grad()")
    print("Only LEAF tensors get .grad populated by default. A non-leaf (any")
    print("tensor with a grad_fn) is an intermediate; its .grad stays None")
    print("unless you call .retain_grad() on it before backward().\n")

    x = torch.tensor([1.0, 2.0, 3.0], requires_grad=True)
    y = x**2          # non-leaf intermediate
    y.retain_grad()   # opt in to keeping its grad
    z = y.sum()
    z.backward()

    print(f"{'tensor':<8}{'is_leaf':<10}{'.grad'}")
    print("-" * 34)
    print(f"{'x':<8}{x.is_leaf!s:<10}{x.grad.tolist() if x.grad is not None else None}")
    print(f"{'y':<8}{y.is_leaf!s:<10}{y.grad.tolist() if y.grad is not None else None}")
    print()

    check("x.grad is [2, 4, 6] (leaf accumulates by default)",
          torch.equal(x.grad, torch.tensor([2.0, 4.0, 6.0])))
    check("y.grad is [1, 1, 1] (dL/dy via retain_grad)",
          torch.equal(y.grad, torch.ones(3)))


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("autograd.py — Phase 5 bundle #30.\n"
          "Every value below is computed by this file; the .md guide pastes it\n"
          "verbatim. Nothing is hand-computed. torch "
          f"{torch.__version__} on CPU.")
    section_a_requires_grad_and_leaf()
    section_b_forward_builds_graph()
    section_c_backward_computes_grads()
    section_d_grad_accumulation()
    section_e_no_grad_and_infer_mode()
    section_f_detach_and_leaf_inplace()
    section_g_manual_gradient_check()
    section_h_non_leaf_grad_and_retain()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
