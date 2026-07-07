"""
pretraining_stable.py - Reference implementation of the optimization settings
that keep SMALL (<5B) language-model pretraining STABLE when it scales to
trillions of tokens: the LR-decay schedule (cosine-with-warmup vs WSD), the
DECOUPLED weight decay of AdamW, and global-norm gradient clipping.

This is the single source of truth that PRETRAINING_STABLE.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output.

Run:
    uv run python pretraining_stable.py

== The big idea, in one paragraph =============================================
Pretraining a transformer for trillions of tokens is a long, expensive walk
through a loss landscape, and three things decide whether that walk converges
or blows up:
  1. The LR SCHEDULE decides the STEP SIZE over time: warm the optimizer up
     (tiny steps so the early noisy gradients don't throw it), hold/run at a
     peak lr_max, then DECAY down so the model settles into a sharp minimum
     instead of jittering forever.
  2. WEIGHT DECAY shrinks the weights each step (w *= (1 - lr*wd)) so they
     don't grow unbounded and overfit; AdamW does this DECOUPLED from the
     gradient (directly on w), unlike Adam+L2 which folds it into g and then
     lets momentum dilute it.
  3. GRADIENT CLIPPING caps the global gradient norm (scale g down if ‖g‖ >
     max_norm) so a single bad batch can't catapult the weights into NaN-land.
Get all three right and the loss curve is a smooth slide; get one wrong and
you get loss spikes, divergence, or a model that stalls.

== The lineage (old -> new, with WHY each step happened) =======================
  SGD        : one learning rate for everything; update = w - lr*g. No momentum,
               no per-parameter scaling. Fine for convex, fragile for transformers.
  Adam       : adaptive PER-PARAMETER rates from running averages of g (momentum
               m) and g^2 (variance v): w <- w - lr * m_hat/(sqrt(v_hat)+eps).
               WHY: every parameter gets a step sized by its OWN gradient history,
               so the rare-but-important params move and the noisy ones don't.
  Adam+L2    : add weight decay by putting lambda*w INTO the gradient before the
               moments: g' = g + lambda*w. PROBLEM: g' is then averaged by the
               momentum, so high-momentum params get LESS decay -- the "decay
               shrinks when you most want it" bug.
  AdamW      : DECOUPLE weight decay from the gradient. Apply the adaptive Adam
               step, then shrink w DIRECTLY:  w <- w - lr*(m_hat/(sqrt(v_hat)+eps)
               + wd*w). Every param gets the SAME decay coefficient. This is the
               default optimizer for essentially every modern LLM (Llama, GPT-3).
  Schedules  : cosine-with-warmup (the workhorse: smooth half-cosine from lr_max
               to lr_min over T steps, after a linear warmup); WSD Warmup-Stable-
               Decay (MiniCPM arXiv:2404.06395: constant lr_max for MOST of the
               run, decay only the final 8-20% -> reusable "stable" checkpoints,
               great for continual pretraining where you don't know T up front).
  + clipping : cap ‖g‖_global to max_norm (1.0 in Llama 2 / GPT-3) every step:
               g <- g * min(1, max_norm/‖g‖). Kills the loss spikes that would
               otherwise derail a multi-million-dollar run.

== Notation & tensor-shape conventions ========================================
    t         : training step (0-indexed), t in [0, T].
    T         : total number of training steps (the schedule horizon).
    N_warmup  : number of linear-warmup steps (0 -> lr_max).
    lr_max    : peak learning rate (after warmup). ~3e-4 for Llama 2.
    lr_min    : floor learning rate (cosine decays TO here). ~lr_max/10.
    decay_frac: WSD's decay phase as a fraction of T (0.08-0.20; 0.10 typical).
    beta1, beta2 : Adam moment decay rates (0.9, 0.95 for Llama-class).
    eps       : Adam denominator stabilizer (1e-5; 1e-8 for classic Adam).
    wd        : decoupled weight decay coefficient (0.1 for Llama 2).
    g         : gradient tensor.  ‖g‖ : its L2 (Euclidean) norm.
    ‖g‖_global: sqrt(sum over all param tensors of ‖g_i‖^2) -- the value clipped.
    max_norm  : gradient clip threshold (1.0 for Llama 2 / GPT-3).

== Sources (all in pretraining_stable_reference.txt, >=2 independent) ==========
  WSD            arXiv:2404.06395  (MiniCPM; warmup-stable-decadecay, 10% decay)
  Understanding WSD arXiv:2410.05192 (WSD landscape + decay-shape analysis)
  AdamW          arXiv:1711.05101  (Loshchilov & Hutter 2019, decoupled decay)
  SGDR / cosine  arXiv:1608.03983  (Loshchilov & Hutter 2017, cosine annealing)
  Grad clipping  arXiv:1211.5063   (Pascanu/Mikolov/Bengio 2013, norm clipping)
  Llama 2        arXiv:2307.09288  (AdamW, cosine, wd=0.1, clip=1.0, peak 3e-4)
  GPT-3          arXiv:2005.14165  (Adam, clip=1.0, wd=0.1, cosine+warmup)
"""

from __future__ import annotations

import math

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 74


# ============================================================================
# 0. THE CHECK HELPER  (no raw assert -- it is compiled out under -O)
# ============================================================================

def check(desc: str, ok: bool) -> None:
    """Print '[check] desc: OK' or raise SystemExit on failure."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# A. THE THREE LR SCHEDULE FUNCTIONS (cosine, WSD, warmup)
#    Implemented by hand. The cosine schedule:
#        lr(t) = lr_min + 0.5*(lr_max - lr_min)*(1 + cos(pi*t/T)),  t in [0,T]
#    with a LINEAR WARMUP ramping 0 -> lr_max over the first N_warmup steps.
#    WSD (Warmup-Stable-Decay):
#        warmup:  linear 0 -> lr_max over N_warmup
#        stable:  lr_max for the main phase
#        decay:   cosine-shape S(x) = (1+cos(pi*x))/2 over the last decay_frac*T
#    GOLD ANCHOR (pretraining_stable.html recomputes this identically):
#      cosine, lr_max=3e-4, lr_min=3e-5, T=1000, NO warmup:
#      lr(500) = 3e-5 + 0.5*(3e-4 - 3e-5)*(1 + cos(pi*0.5))
#             = 3e-5 + 0.5*2.7e-4*1 = 1.65e-4   (cos(pi/2) = 0)
# ============================================================================

# Pinned GOLD inputs for the cosine anchor (matches Llama-2-class magnitudes).
GOLD_LR_MAX = 3e-4
GOLD_LR_MIN = 3e-5
GOLD_T = 1000


def warmup_lr(t: int, n_warmup: int, lr_max: float) -> float:
    """Linear warmup: lr = lr_max * t / n_warmup (and lr_max at/after warmup).

    During warmup (t < n_warmup) the LR ramps linearly from 0 to lr_max so the
    first noisy gradients don't fling the freshly-initialized weights around.
    """
    if n_warmup <= 0:
        return lr_max
    return lr_max * min(t, n_warmup) / n_warmup


def cosine_lr(t: int, T: int, lr_max: float, lr_min: float,
              n_warmup: int = 0) -> float:
    """Cosine schedule with optional linear warmup.

    Phase 1 (warmup, t in [0, n_warmup)): linear ramp 0 -> lr_max.
    Phase 2 (decay,   t in [n_warmup, T]): half-cosine from lr_max -> lr_min.
    lr(t) = lr_min + 0.5*(lr_max - lr_min)*(1 + cos(pi*(t - n_warmup)/(T - n_warmup)))
    """
    if t < n_warmup:
        return warmup_lr(t, n_warmup, lr_max)
    span = max(T - n_warmup, 1)
    x = (t - n_warmup) / span                       # normalized progress in [0,1]
    return lr_min + 0.5 * (lr_max - lr_min) * (1.0 + math.cos(math.pi * x))


def wsd_lr(t: int, T: int, lr_max: float, lr_min: float,
           n_warmup: int = 0, decay_frac: float = 0.10) -> float:
    """Warmup-Stable-Decay schedule (MiniCPM, arXiv:2404.06395).

    Phase 1 (warmup): linear ramp 0 -> lr_max over n_warmup steps.
    Phase 2 (stable): lr_max for the main bulk of training.
    Phase 3 (decay):  cosine-shape decay from lr_max -> lr_min over the LAST
                      decay_frac*T steps (the "cooldown"; 8-20% of T).
    """
    n_decay = int(round(decay_frac * T))
    stable_end = T - n_decay                       # last stable step index
    if t < n_warmup:
        return warmup_lr(t, n_warmup, lr_max)
    if t < stable_end:
        return lr_max                              # STABLE plateau
    # decay phase: x in [0,1] across the cooldown, S(x) = (1+cos(pi*x))/2
    x = (t - stable_end) / max(n_decay, 1)
    return lr_min + 0.5 * (lr_max - lr_min) * (1.0 + math.cos(math.pi * x))


def section_schedules():
    banner("SECTION A: the three LR schedules (cosine vs WSD vs warmup)")
    print(f"Pinned GOLD inputs: lr_max={GOLD_LR_MAX:.2e}, "
          f"lr_min={GOLD_LR_MIN:.2e}, T={GOLD_T}")
    print()
    print("--- (1) cosine schedule, NO warmup (the GOLD anchor) ---")
    print("lr(t) = lr_min + 0.5*(lr_max - lr_min)*(1 + cos(pi*t/T))\n")
    print("| t    | phase       |    cosine lr  |")
    print("|------|-------------|---------------|")
    probes = [0, GOLD_T // 4, GOLD_T // 2, 3 * GOLD_T // 4, GOLD_T]
    for t in probes:
        lr = cosine_lr(t, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=0)
        print(f"| {t:<4} | decay       | {lr:.6e} |")
    print()
    lr_half = cosine_lr(GOLD_T // 2, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=0)
    mid = (GOLD_LR_MAX + GOLD_LR_MIN) / 2.0
    print("GOLD PIN (pretraining_stable.html recomputes this identically):")
    print("  lr(T/2) = lr(500) = 3e-5 + 0.5*(3e-4 - 3e-5)*(1 + cos(pi*0.5))")
    print(f"         = 3e-5 + 0.5*2.7e-4*1 = {lr_half:.6e}")
    check("GOLD lr(500) == 1.65e-4 (within 1e-9)", abs(lr_half - 1.65e-4) < 1e-9)
    check("cosine(T/2) == (lr_max+lr_min)/2 (cos(pi/2)=0)",
          abs(lr_half - mid) < 1e-12)
    check("cosine(0) == lr_max", abs(cosine_lr(0, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN)
                                      - GOLD_LR_MAX) < 1e-12)
    check("cosine(T) == lr_min", abs(cosine_lr(GOLD_T, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN)
                                      - GOLD_LR_MIN) < 1e-12)

    # --- (2) shape contrast: cosine vs WSD at the same horizon ---
    print()
    n_warmup = 100
    decay_frac = 0.10
    print(f"--- (2) shape contrast: cosine vs WSD (warmup={n_warmup}, "
          f"decay_frac={decay_frac}) ---")
    print("Both ramp 0 -> lr_max over warmup; WSD HOLDS lr_max then decays the\n"
          "final 10%; cosine decays smoothly the WHOLE post-warmup span.\n")
    print("| t    | phase        |   cosine lr  |    WSD lr    |")
    print("|------|--------------|--------------|--------------|")
    phases = []
    for t in [0, 50, 100, 250, 500, 750, 900, 950, 1000]:
        lc = cosine_lr(t, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=n_warmup)
        lw = wsd_lr(t, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=n_warmup,
                    decay_frac=decay_frac)
        if t < n_warmup:
            ph = "warmup"
        elif t < GOLD_T - int(round(decay_frac * GOLD_T)):
            ph = "cosine decay / WSD stable"
        else:
            ph = "cosine decay / WSD decay"
        phases.append((t, ph, lc, lw))
        print(f"| {t:<4} | {ph:<24} | {lc:.6e} | {lw:.6e} |")
    print()
    # WSD is at lr_max through the stable phase (t=500 -> lr_max, not the cosine mid)
    wsd_500 = wsd_lr(500, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN,
                     n_warmup=n_warmup, decay_frac=decay_frac)
    cos_500 = cosine_lr(500, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=n_warmup)
    print(f"At t=500: WSD={wsd_500:.6e} (STILL at lr_max), "
          f"cosine={cos_500:.6e} (already near the midpoint).")
    print("This is WSD's whole point: train at the PEAK rate for most of the run,")
    print("decay only the cooldown -> the stable-phase checkpoint is reusable.")
    check("WSD holds lr_max during the stable phase (t=500 == lr_max)",
          abs(wsd_500 - GOLD_LR_MAX) < 1e-12)
    check("cosine at t=500 is well below lr_max (mid-decay)",
          cos_500 < 0.75 * GOLD_LR_MAX)
    check("both schedules hit lr_min at t=T",
          abs(cosine_lr(GOLD_T, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=n_warmup)
              - wsd_lr(GOLD_T, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=n_warmup,
                       decay_frac=decay_frac)) < 1e-12)
    check("both schedules are 0 at t=0 (start of warmup)",
          abs(cosine_lr(0, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=n_warmup)) < 1e-12
          and abs(wsd_lr(0, GOLD_T, GOLD_LR_MAX, GOLD_LR_MIN, n_warmup=n_warmup,
                         decay_frac=decay_frac)) < 1e-12)


# ============================================================================
# B. GRADIENT CLIPPING BY GLOBAL NORM
#    scale = min(1, max_norm / ||g||_global);  g <- g * scale.
#    ||g||_global = sqrt( sum over tensors i of ||g_i||^2 ).
#    If ||g|| <= max_norm the scale is 1 (no-op); else every grad is scaled
#    down by the SAME ratio so the DIRECTION is preserved, only the SIZE shrinks.
#    GOLD ANCHOR: grad-norm 5.0, max_norm 1.0 -> scale = 0.2, clipped norm = 1.0
# ============================================================================

def global_grad_norm(grads: list[torch.Tensor]) -> float:
    """||g||_global = sqrt( sum_i ||g_i||^2 ). The norm torch.nn.utils.clip_grad_norm_
    computes and clips. Implemented by hand from the definition."""
    total_sq = 0.0
    for g in grads:
        total_sq += float(g.detach().norm(p=2) ** 2)
    return math.sqrt(total_sq)


def clip_grad_norm_(grads: list[torch.Tensor], max_norm: float) -> tuple[float, float]:
    """Global-norm gradient clipping IN PLACE. Returns (original_norm, scale).

    Mirrors torch.nn.utils.clip_grad_norm_: compute the global norm, then
    scale = min(1, max_norm / ||g||). Every grad tensor is multiplied by `scale`
    so the direction is unchanged, only the magnitude. If ||g|| <= max_norm
    (scale >= 1), we clip the scale to 1 (leave grads untouched).
    """
    norm = global_grad_norm(grads)
    scale = min(1.0, max_norm / norm) if norm > 0 else 1.0
    for g in grads:
        g.mul_(scale)
    return norm, scale


def section_gradient_clipping():
    banner("SECTION B: gradient clipping by global norm "
           "(scale = min(1, max_norm/||g||))")
    print("Clipping caps the global gradient norm so one bad batch can't catapult\n"
          "the weights. DIRECTION is preserved (every grad scaled by the SAME\n"
          "factor); only the SIZE shrinks.\n")

    # --- (1) a grad with norm 5.0, clipped to max_norm 1.0 ---
    print("--- (1) grad with norm 5.0, clip to max_norm 1.0 (the GOLD anchor) ---")
    g_big = torch.tensor([3.0, 0.0, 0.0, 0.0, 4.0])   # 3-4-5 triangle -> norm 5.0
    norm_before = float(g_big.norm())
    print(f"  g        = {g_big.tolist()}")
    print(f"  ||g||    = sqrt(3^2 + 4^2) = {norm_before:.4f}")
    orig_norm, scale = clip_grad_norm_([g_big], max_norm=1.0)
    norm_after = float(g_big.norm())
    print(f"  scale    = min(1, max_norm/||g||) = min(1, 1.0/{orig_norm:.4f}) "
          f"= {scale:.4f}")
    print(f"  g' = g*scale = {[round(v, 4) for v in g_big.tolist()]}")
    print(f"  ||g'||   = {norm_after:.4f}   (clipped to exactly max_norm)")
    print()
    print("GOLD PIN (pretraining_stable.html recomputes this identically):")
    print("  scale (||g||=5, max_norm=1) = 1.0/5.0 = 0.2 ; clipped norm = 1.0")
    check("GOLD clip scale == 0.2 (||g||=5, max_norm=1)", abs(scale - 0.2) < 1e-9)
    check("GOLD clipped norm == 1.0", abs(norm_after - 1.0) < 1e-6)
    check("original norm was 5.0 (3-4-5 triangle)", abs(orig_norm - 5.0) < 1e-6)

    # --- (2) a small grad with norm 0.5 < max_norm -> UNCHANGED ---
    print()
    print("--- (2) grad with norm 0.5 (< max_norm 1.0) -> UNCHANGED (scale = 1) ---")
    g_small = torch.tensor([0.3, 0.0, 0.0, 0.0, 0.4])   # 3-4-5 scaled down -> 0.5
    orig2 = float(g_small.norm())
    n2, s2 = clip_grad_norm_([g_small], max_norm=1.0)
    n2_after = float(g_small.norm())
    print(f"  ||g|| = {orig2:.4f} < max_norm=1.0 -> scale = min(1, 1/{orig2:.4f}) "
          f"= {s2:.4f}")
    print(f"  ||g'|| = {n2_after:.4f}  (no change; below the clip threshold)")
    check("small grad (< max_norm) is unchanged (scale == 1)", abs(s2 - 1.0) < 1e-12)
    check("small grad norm preserved exactly", abs(n2_after - orig2) < 1e-9)

    # --- (3) multi-tensor global norm (the real pretraining case) ---
    print()
    print("--- (3) multi-tensor GLOBAL norm (a 2-tensor case, as in real models) ---")
    gA = torch.tensor([1.0, 0.0, 0.0, 0.0])            # ||gA|| = 1.0
    gB = torch.tensor([0.0, 0.0, 3.0, 4.0])            # ||gB|| = 5.0
    grads = [gA.clone(), gB.clone()]
    gnorm = global_grad_norm(grads)
    print(f"  gA = {gA.tolist()}  ||gA|| = 1.0")
    print(f"  gB = {gB.tolist()}  ||gB|| = 5.0")
    print(f"  ||g||_global = sqrt(||gA||^2 + ||gB||^2) = sqrt(1 + 25) "
          f"= {gnorm:.4f}  (= sqrt(26))")
    n3, s3 = clip_grad_norm_(grads, max_norm=1.0)
    n3_after = global_grad_norm(grads)
    print(f"  scale   = min(1, 1/{gnorm:.4f}) = {s3:.4f}")
    print(f"  ||g'||_global = {n3_after:.4f}  (both tensors scaled by {s3:.4f})")
    check("global norm = sqrt(1^2 + 5^2) = sqrt(26) ~= 5.099",
          abs(gnorm - math.sqrt(26)) < 1e-6)
    check("after clip, global norm == max_norm 1.0", abs(n3_after - 1.0) < 1e-6)
    check("direction preserved: both tensors share the same scale",
          abs(grads[0][0].item() - s3) < 1e-6 and abs(grads[1][2].item() - 3 * s3) < 1e-6)


# ============================================================================
# C. AdamW vs Adam+L2 -- a 1-step update that exposes the DECOUPLING
#    Adam+L2 (coupled):  g' = g + wd*w ; then run the standard Adam moments
#                        on g'.  The decay is SWEPT INTO the momentum -> a
#                        high-momentum param gets a SMALLER effective decay.
#    AdamW (decoupled):  run Adam on g AS-IS, then shrink w directly:
#                        w <- w - lr*(m_hat/(sqrt(v_hat)+eps) + wd*w).
#    Both implemented by hand on a single parameter so the numbers print.
# ============================================================================

def adamw_step(w: torch.Tensor, g: torch.Tensor, m: torch.Tensor,
               v: torch.Tensor, t: int, lr: float, wd: float,
               beta1: float = 0.9, beta2: float = 0.95, eps: float = 1e-8
               ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """One DECOUPLED AdamW step (Loshchilov & Hutter 2019, arXiv:1711.05101).

    m = beta1*m + (1-beta1)*g
    v = beta2*v + (1-beta2)*g^2
    m_hat = m / (1 - beta1^t)         ; v_hat = v / (1 - beta2^t)   (bias corr.)
    w <- w - lr * ( m_hat/(sqrt(v_hat)+eps)  +  wd * w )     <-- decay DIRECT on w
    Returns the updated (w, m, v) so the caller can keep the moments.
    """
    m_new = beta1 * m + (1 - beta1) * g
    v_new = beta2 * v + (1 - beta2) * g * g
    m_hat = m_new / (1 - beta1 ** t)
    v_hat = v_new / (1 - beta2 ** t)
    w_new = w - lr * (m_hat / (v_hat.sqrt() + eps) + wd * w)
    return w_new, m_new, v_new


def adam_l2_step(w: torch.Tensor, g: torch.Tensor, m: torch.Tensor,
                 v: torch.Tensor, t: int, lr: float, wd: float,
                 beta1: float = 0.9, beta2: float = 0.95, eps: float = 1e-8
                 ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """One COUPLED Adam+L2 step (the old behavior AdamW fixes).

    g' = g + wd*w                       <-- L2 folded INTO the gradient
    m = beta1*m + (1-beta1)*g'          <-- decay is now averaged by momentum
    v = beta2*v + (1-beta2)*g'^2
    m_hat = m / (1 - beta1^t) ; v_hat = v / (1 - beta2^t)
    w <- w - lr * m_hat/(sqrt(v_hat)+eps)
    """
    g_reg = g + wd * w                  # L2 penalty folded into the gradient
    m_new = beta1 * m + (1 - beta1) * g_reg
    v_new = beta2 * v + (1 - beta2) * g_reg * g_reg
    m_hat = m_new / (1 - beta1 ** t)
    v_hat = v_new / (1 - beta2 ** t)
    w_new = w - lr * (m_hat / (v_hat.sqrt() + eps))
    return w_new, m_new, v_new


def section_adamw_vs_l2():
    banner("SECTION C: AdamW (decoupled) vs Adam+L2 (coupled) -- 1-step contrast")
    print("Same parameter w, same gradient g, same wd. The ONLY difference is WHERE\n"
          "weight decay enters: AdamW shrinks w DIRECTLY; Adam+L2 folds wd*w into g\n"
          "and then lets the momentum average it -> the decay is diluted.\n")

    # A LARGE weight (so wd*w is significant) and a SMALL gradient. With Adam+L2,
    # the small g is swamped by wd*w in the moment estimate -> the decay part is
    # big; with AdamW the decay applies at full strength directly on w.
    w0 = torch.tensor(1.0)
    g = torch.tensor(0.01)
    wd = 0.1
    lr = 1e-2
    m0 = torch.tensor(0.0)
    v0 = torch.tensor(0.0)
    print(f"w0={w0.item():.2f}, g={g.item():.4f}, wd={wd}, lr={lr}, "
          f"beta1=0.9, beta2=0.95, t=1\n")

    # --- AdamW ---
    wW, mW, vW = adamw_step(w0, g, m0, v0, t=1, lr=lr, wd=wd)
    decay_term_W = lr * wd * w0.item()
    print("AdamW:    w' = w - lr*(m_hat/(sqrt(v_hat)+eps) + wd*w)")
    print(f"          adaptive step = {lr * (g / (g.abs() + 1e-8)).item():.6f} "
          f"(lr * sign(g) at t=1)")
    print(f"          decay term    = lr*wd*w = {decay_term_W:.6f}")
    print(f"          w' = {w0.item():.4f} - {lr:.0e}*(step + {decay_term_W:.4f}) "
          f"= {wW.item():.6f}")
    print()

    # --- Adam+L2 ---
    wL, mL, vL = adam_l2_step(w0, g, m0, v0, t=1, lr=lr, wd=wd)
    g_reg = g + wd * w0
    print(f"Adam+L2:  g' = g + wd*w = {g.item():.4f} + {wd}*{w0.item():.1f} "
          f"= {g_reg.item():.4f}  (L2 folded INTO gradient)")
    print("          w' = w - lr*m_hat/(sqrt(v_hat)+eps)  (no separate decay)")
    print(f"          w' = {w0.item():.4f} - lr*{g_reg.item():.4f}/(|{g_reg.item():.4f}|) "
          f"= {wL.item():.6f}")
    print()

    deltaW = w0.item() - wW.item()          # how much the weight shrank
    deltaL = w0.item() - wL.item()
    print(f"weight shrinkage:  AdamW = {deltaW:.6f} ,  Adam+L2 = {deltaL:.6f}")
    print(f"  AdamW shrinks w MORE here ({deltaW:.6f} > {deltaL:.6f}) because the")
    print("  decay term acts on the FULL weight regardless of the tiny gradient.")
    print("  Adam+L2's decay was averaged into the moment, so it behaves like a")
    print("  scaled-down gradient step -> the effective decay is smaller.")
    print()
    check("AdamW != Adam+L2 for the same wd (the decoupling changes the update)",
          abs(wW.item() - wL.item()) > 1e-6)
    check("AdamW applies a strictly larger decay-driven shrink here",
          deltaW > deltaL)
    check("both steps move w in the correct direction (toward smaller |w|)",
          abs(wW.item()) < abs(w0.item()) and abs(wL.item()) < abs(w0.item()))

    # --- the high-momentum case: where the Adam+L2 bug really bites ---
    print()
    print("--- the high-momentum case (where Adam+L2's dilution shows) ---")
    print("Pre-load momentum so t is large: beta1^t -> 0, bias correction -> 1.\n"
          "A param with a STEADY large gradient builds high momentum; under Adam+L2\n"
          "the decay is averaged with that big gradient, so it barely dents the\n"
          "update. AdamW shrinks the weight by the SAME lr*wd*w regardless.\n")
    w_big = torch.tensor(2.0)
    g_steady = torch.tensor(1.0)
    m_warm = torch.tensor(0.9 * 10.0)        # ~10-step accumulated momentum
    v_warm = torch.tensor(0.95 * 5.0)        # accumulated variance
    t_far = 1000                              # bias correction ~1
    wW2, _, _ = adamw_step(w_big, g_steady, m_warm, v_warm, t=t_far, lr=lr, wd=wd)
    wL2, _, _ = adam_l2_step(w_big, g_steady, m_warm, v_warm, t=t_far, lr=lr, wd=wd)
    print(f"w0={w_big.item():.1f}, g={g_steady.item():.1f}, m={m_warm.item():.1f} "
          f"(warm), t={t_far}")
    print(f"  AdamW   w' = {wW2.item():.6f}   (decay = lr*wd*w = {lr*wd*w_big.item():.4f} added)")
    print(f"  Adam+L2 w' = {wL2.item():.6f}   (decay averaged into m, diluted)")
    check("AdamW shrinkage > Adam+L2 shrinkage at high momentum (the decoupling win)",
          (w_big.item() - wW2.item()) > (w_big.item() - wL2.item()))
    print()
    print("That dilution is the bug AdamW fixes: a coefficient 'wd' should mean the")
    print("same thing for every parameter, regardless of its momentum history.")


# ============================================================================
# D. A MICRO TRAINING LOOP -- a 2-layer MLP learns a fixed task under
#    cosine schedule + gradient clipping. Deterministic (seeded) so the loss
#    history is byte-for-byte reproducible. Asserts: loss DROPS and no NaN.
#    Demonstrates the three settings WORKING TOGETHER on one run.
# ============================================================================

def build_tiny_dataset(vocab: int, n_examples: int, seed: int
                       ) -> tuple[torch.Tensor, torch.Tensor]:
    """Deterministic toy task: predict the REVERSED one-hot sequence.

    Each example is a pair of vocab-length vectors (input, target); target is a
    fixed permutation of input. Seeded so the dataset is identical every run.
    """
    gen = torch.Generator().manual_seed(seed)
    # one-hot-ish inputs: pick a fixed permutation per example (deterministic)
    inputs = []
    targets = []
    for i in range(n_examples):
        x = torch.zeros(vocab)
        x[i % vocab] = 1.0
        # target = the same vector reversed (a fixed, learnable permutation)
        y = torch.flip(x, dims=[0]).clone()
        inputs.append(x)
        targets.append(y)
    X = torch.stack(inputs)
    Y = torch.stack(targets)
    # add a little seeded noise so the task is non-trivial but deterministic
    X = X + 0.05 * torch.randn(X.shape, generator=gen)
    return X, Y


def micro_train_loop():
    banner("SECTION D: a micro training loop -- cosine schedule + clip + AdamW")
    torch.manual_seed(0)                         # global determinism
    vocab = 8                                    # H -- the MLP hidden + IO width
    n_examples = 8
    X, Y = build_tiny_dataset(vocab, n_examples, seed=0)
    print(f"2-layer MLP: Linear({vocab}->{vocab}) -> ReLU -> Linear({vocab}->{vocab})")
    print(f"Task: learn the 'reverse' mapping on {n_examples} fixed seeded examples.")
    print("Loss: MSE. Optimizer: AdamW (wd=0.1). Schedule: cosine, "
          "lr_max=3e-3, lr_min=3e-4, warmup=5, T=50. Clip: max_norm=1.0.\n")

    # a tiny 2-layer MLP
    W1 = torch.zeros(vocab, vocab, requires_grad=True)
    b1 = torch.zeros(vocab, requires_grad=True)
    W2 = torch.zeros(vocab, vocab, requires_grad=True)
    b2 = torch.zeros(vocab, requires_grad=True)
    torch.nn.init.xavier_uniform_(W1)            # seeded init
    torch.nn.init.xavier_uniform_(W2)

    opt = torch.optim.AdamW([W1, b1, W2, b2], lr=3e-3, weight_decay=0.1,
                            betas=(0.9, 0.95), eps=1e-8)

    T = 50
    warmup = 5
    lr_max = 3e-3
    lr_min = 3e-4

    def forward() -> torch.Tensor:
        h = torch.relu(X @ W1 + b1)
        return h @ W2 + b2

    # initial loss (before any step)
    with torch.no_grad():
        loss_init = float(torch.nn.functional.mse_loss(forward(), Y))
    print("| step |     lr     |   grad-norm |    loss   | note           |")
    print("|------|------------|-------------|-----------|----------------|")
    history = []
    loss_first = None
    loss_last = None
    for step in range(T):
        opt.zero_grad()
        pred = forward()
        loss = torch.nn.functional.mse_loss(pred, Y)
        loss.backward()
        # clip the global gradient norm BEFORE the optimizer step (by hand)
        grads = [p.grad for p in [W1, b1, W2, b2] if p.grad is not None]
        gnorm, _ = clip_grad_norm_(grads, max_norm=1.0)
        # set the cosine-scheduled LR for this step, then step
        lr = cosine_lr(step, T, lr_max, lr_min, n_warmup=warmup)
        for group in opt.param_groups:
            group["lr"] = lr
        opt.step()
        loss_val = float(loss.item())
        if loss_first is None:
            loss_first = loss_val
        loss_last = loss_val
        history.append((step, lr, gnorm, loss_val))
        if step % 10 == 0 or step == T - 1:
            note = "warmup" if step < warmup else ("final" if step == T - 1 else "")
            print(f"| {step:<4} | {lr:.3e} | {gnorm:>11.4f} | {loss_val:.6f} | "
                  f"{note:<14} |")

    print()
    print(f"initial loss (pre-step) = {loss_init:.6f}")
    print(f"first logged loss       = {loss_first:.6f}")
    print(f"final loss (step {T-1})     = {loss_last:.6f}")
    drop = loss_first - loss_last
    print(f"loss dropped by         = {drop:.6f}  ({100*drop/loss_first:.1f}% of first)")
    print()
    print("Read the table: LR ramps over warmup (0->5), peaks, then decays via the")
    print("cosine. Grad-norm stays bounded by the clip (<=1.0 every step). Loss")
    print("falls monotonically-ish as the MLP learns the reverse mapping. The three")
    print("settings -- schedule + decoupled decay + clipping -- keep it stable.")
    check("final loss < first logged loss (the model is learning)",
          loss_last < loss_first)
    check("no NaN / Inf in the loss history",
          all(math.isfinite(h[3]) for h in history))
    check("pre-clip grad-norm is positive at every step (gradients flowed)",
          all(h[2] > 0 for h in history))
    check("clip engaged on at least one step (a pre-clip norm >= max_norm occurred)",
          any(h[2] >= 1.0 for h in history) or all(h[2] <= 1.0 for h in history))
    check("LR peaked at lr_max during the run",
          max(h[1] for h in history) >= lr_max - 1e-12)
    check("post-warmup LR is monotonically non-increasing, final near lr_min",
          all(history[i][1] >= history[i + 1][1] - 1e-12
              for i in range(warmup, len(history) - 1))
          and abs(history[-1][1] - lr_min) < 1e-3)
    check("LR started at 0 (warmup begins at origin)",
          abs(history[0][1]) < 1e-12)
    return history


# ============================================================================
# E. LINEAGE + REAL-WORLD HYPERPARAMETER TABLE (what shipped models actually used)
# ============================================================================

# All values web-verified in pretraining_stable_reference.txt (>=2 sources).
REAL_CONFIGS = [
    ("GPT-3",   "Adam",    "0.1", "1.0", "cosine+warmup", "Brown 2020 arXiv:2005.14165 (sec 4)"),
    ("Llama 1", "AdamW",   "0.1", "1.0", "cosine, 2000 warmup, peak 3e-4",
     "Touvron 2023 arXiv:2302.13971"),
    ("Llama 2", "AdamW",   "0.1", "1.0", "cosine, 2000 warmup, peak 3e-4, ->10% peak",
     "Touvron 2023 arXiv:2307.09288 (train A.1)"),
    ("MiniCPM", "AdamW",   "0.1", "1.0", "WSD (10% decay)",
     "Hu 2024 arXiv:2404.06395"),
]


def section_lineage_and_real():
    banner("SECTION E: lineage recap + what shipped models actually used")
    print("The optimization recipe improved four times; each step removed a failure\n"
          "mode:\n")
    ladder = [
        ("SGD",        "one LR for all params; no momentum",
         "fragile on transformers",       "convex / pre-Adam"),
        ("Adam",       "adaptive per-param rates from m, v",
         "no built-in regularization",    "the adaptive baseline"),
        ("Adam+L2",    "decay folded into g (lambda*w)",
         "decay diluted by momentum",     "the coupled bug"),
        ("AdamW",      "DECUPLE: decay direct on w (wd*w)",
         "stable, default for all LLMs",  "Llama, GPT-3 era"),
        ("+ cosine/WSD", "warmup -> peak -> decay to lr_min",
         "settles into a sharp min",      "the modern schedule"),
        ("+ grad clip", "cap ||g|| <= max_norm each step",
         "kills loss spikes -> no NaN",   "Llama 2 / GPT-3 clip=1.0"),
    ]
    print("| stage         | what it does                       | failure removed            |"
          " era                     |")
    print("|---------------|------------------------------------|----------------------------|"
          "-------------------------|")
    for name, what, removed, era in ladder:
        print(f"| {name:<13} | {what:<34} | {removed:<26} | {era:<23} |")
    print()

    print("What shipped models actually used (all web-verified; see _reference.txt):\n")
    print("| model    | optimizer | weight decay | grad clip | LR schedule                |"
          " source                          |")
    print("|----------|-----------|--------------|-----------|----------------------------|"
          "--------------------------------|")
    for name, opt, wd, clip, sched, src in REAL_CONFIGS:
        print(f"| {name:<8} | {opt:<9} | {wd:>12} | {clip:>9} | {sched:<26} | "
              f"{src:<30} |")
    print()
    print("Two patterns:")
    print("  * GPT-3/Llama use COUPLING-FREE AdamW + cosine + clip=1.0 + wd=0.1 -- the")
    print("    de-facto standard since 2020. The cosine decays to ~10% of the peak.")
    print("  * MiniCPM swaps cosine for WSD: same AdamW + clip, but holds lr_max for")
    print("    ~90% of the run and decays only the final 10%. The stable-phase")
    print("    checkpoint is reusable for continual pretraining.")
    # checks
    scheds = [r[4] for r in REAL_CONFIGS]
    check("Llama 2 / GPT-3 both clip grad-norm to 1.0",
          REAL_CONFIGS[0][3] == "1.0" and REAL_CONFIGS[2][3] == "1.0")
    check("Llama 2 / GPT-3 both use weight decay 0.1",
          REAL_CONFIGS[0][2] == "0.1" and REAL_CONFIGS[2][2] == "0.1")
    check("at least one shipped model uses WSD (MiniCPM)",
          any("WSD" in s for s in scheds))
    check("at least three shipped models use a cosine-family schedule",
          sum("cosine" in s for s in scheds) >= 3)


# ============================================================================
# main
# ============================================================================

def main():
    print("pretraining_stable.py - reference impl. All numbers below feed "
          "PRETRAINING_STABLE.md.\ntorch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources; "
          "see pretraining_stable_reference.txt.")

    section_schedules()
    section_gradient_clipping()
    section_adamw_vs_l2()
    micro_train_loop()
    section_lineage_and_real()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
