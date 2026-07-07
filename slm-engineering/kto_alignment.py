"""
kto_alignment.py - Reference implementation of Kahneman-Tversky Optimization
(KTO) for aligning SMALL (<5B) language models on UNPAIRED binary feedback.

This is the single source of truth that KTO_ALIGNMENT.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output.

Run:
    uv run python kto_alignment.py

== The big idea, in one paragraph =============================================
DPO (🔗 DIRECT_PREFERENCE_DPO) aligns a model from PAIRED preference data --
for every prompt x a human must judge "output y_w is better than y_l". That
pairing is expensive to collect: a human must COMPARE two full generations.
But in the real world humans far more often give UNPAIRED binary feedback -- a
thumbs-up or thumbs-down on a SINGLE output. KTO (Ethayarajh et al 2024) shows
that this abundant, cheap signal is enough to match DPO quality, PROVIDED the
loss models how humans actually perceive gains and losses. That model is
PROSPECT THEORY (Kahneman & Tversky 1979/1992): humans are loss-averse (losses
loom larger than gains by a factor lambda ~= 2.25), reference-dependent (we
judge outcomes RELATIVE to a reference point z0), and risk-averse in gains /
risk-seeking in losses. KTO builds a loss that flows the policy's relative
reward r = log(pi_theta) - log(pi_ref) through exactly such an asymmetric
value function. No pairs required.

== The lineage (old -> new, with WHY each step happened) ========================
  RLHF / PPO : train a reward model r_phi on PAIRED preferences, then optimize
                 the policy with PPO against r_phi minus a KL penalty to pi_ref.
                 WHY it works: the reward captures human preference. Why it is
                 painful: two stages (reward model + RL), RL is unstable, and
                 the data is expensive PAIRED preferences.
  DPO (2023) : collapse RLHF into a CLOSED-FORM loss on the (chosen, rejected)
                 PAIR directly:
                 L_DPO = -log sigma( beta*(logratios_chosen - logratios_rejected) )
                 where logratios = log pi_theta(y|x) - log pi_ref(y|x).
                 WHY: same optimal policy as RLHF, no RL, no reward model. But
                 STILL needs PAIRS -- one human judgement comparing two outputs.
  KTO (2024) : observe that humans naturally give UNPAIRED binary feedback
                 (thumbs-up / thumbs-down on ONE output), and that human utility
                 is described by PROSPECT THEORY (an asymmetric, loss-averse
                 value function v). Derive a HALO (human-aware loss) that
                 operates on a SINGLE (x, y, label) triple, modeling the
                 relative reward r_theta through v with a KL reference point z0.
                 WHY: matches/beats DPO at 1B-30B scale using data that is
                 abundant, cheap, and fast to collect -- and KTO can even handle
                 extreme class imbalance (up to 90% fewer desirable examples).

== The two building blocks (verify in >=2 sources; see kto_alignment_reference.txt) ==
  1. RELATIVE REWARD (shared with DPO -- the r_pi building block):
        r_theta(x,y) = log pi_theta(y|x) - log pi_ref(y|x)            (in nats)
     NOTE: KTO factors beta OUT of r_theta and INTO the value function below
     (TRL's `chosen_rewards = beta * chosen_logratios` is the DPO-style form
     with beta folded back in -- the two are equivalent; see Section A).
  2. KT VALUE FUNCTION + KTO LOSS (Ethayarajh 2024 Eq 8, value-function box):
        z0 = KL(pi_theta(y'|x) || pi_ref(y'|x))                       (reference pt)
        v(x,y) = lambda_D * sigma( beta*(r_theta - z0) )   if y desirable
               = lambda_U * sigma( beta*(z0 - r_theta) )   if y undesirable
        L_KTO = E_{x,y}[ lambda_y - v(x,y) ]
     The desirable branch MAXIMIZES the value of a positive r (push r above z0);
     the undesirable branch penalizes a positive r (the model should have put
     LESS mass on a bad output). lambda_y is lambda_D for desirable, lambda_U
     for undesirable (both default 1; tunable for class imbalance / loss
     aversion). z0 is the prospect-theory REFERENCE POINT -- estimated over the
     batch (see Section C) so gains/losses are measured relative to it.

== Notation & conventions =====================================================
    x        : the prompt / input.
    y        : a single model output for x (NO pairing -- one y per example).
    label    : True = desirable (thumbs-up), False = undesirable (thumbs-down).
    logpi    : log pi_theta(y|x) -- the policy's log-prob of y given x.
    logpi_ref: log pi_ref(y|x)   -- the FROZEN reference (SFT) model's log-prob.
    r_theta  : logpi - logpi_ref (the relative reward, in nats; NO beta here).
    beta     : risk-aversion / temperature (>0). Scales how fast v saturates.
    z0       : the KL reference point (prospect theory's z_0), estimated/biased.
    lambda_D : loss-aversion weight for DESIRABLE examples (default 1).
    lambda_U : loss-aversion weight for UNDESIRABLE examples (default 1).
    sigma    : the logistic sigmoid 1/(1+e^-x). Concave in gains, convex in losses.

== Sources (all in kto_alignment_reference.txt, >=2 independent confirmations) ==
  KTO 2024              arXiv:2402.01306  (HALO, Eq 8, KT value fn, z0 estimator)
  HuggingFace TRL       kto_trainer.py    (chosen_losses/rejected_losses impl)
  Prospect Theory       Tversky&Kahneman 1992 (v(z)=z^alpha / -lambda*(-z)^alpha)
  DPO 2023              arXiv:2305.18290  (the shared r_pi = beta*(logpi-logpi_ref))
"""

from __future__ import annotations

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
# THE GOLD INPUTS  (pinned for kto_alignment.html -- both files use THESE)
#    A 4-example UNPAIRED batch. logpi / logpi_ref are GIVEN scalars (as if a
#    forward pass already produced them). label: True=desirable (thumbs-up).
#    Plus a separate vector of mismatched-pair log-ratios for the z0 estimate
#    (a real KTO run gets these from a second forward pass on shifted outputs).
# ============================================================================

BETA = 1.0            # risk-aversion temperature (paper: 0.01-1.0)
LAMBDA_D = 1.0        # desirable loss-aversion weight (paper default 1)
LAMBDA_U = 1.0        # undesirable loss-aversion weight (paper default 1)

# (label, logpi_theta, logpi_ref) -- 4 unpaired examples.
# Designed to show BOTH branches behaving sensibly:
#   - desirables 0,1: policy RAISED prob of a good output (r > 0) -> low loss.
#   - undesirable 2 : policy FAILED to lower prob of a bad output (r > 0) ->
#                     HIGH loss (this is the loss-aversion case in Section D).
#   - undesirable 3 : policy correctly LOWERED prob of a bad output (r < 0).
TOY_BATCH = [
    (True,  -1.0, -1.6),   # r_theta = +0.6
    (True,  -1.2, -1.7),   # r_theta = +0.5
    (False, -0.9, -1.1),   # r_theta = +0.2  (policy did NOT lower a bad output)
    (False, -1.5, -1.0),   # r_theta = -0.5  (policy DID lower a bad output)
]

# Mismatched-pair log-ratios for the biased KL estimator z_hat_0 (paper Sec 4.1).
#   z_hat_0 = max(0, mean_i[ logpi_theta(y_{(i+1)%m}|x_i) - logpi_ref(...) ])
# In a real run these come from a second forward pass on the SHIFTED outputs
# (TRL builds them as KL_input_ids). Here they are hardcoded given scalars.
KL_LOGRATIOS = [0.04, 0.06, -0.02, 0.08]


# ============================================================================
# A. THE RELATIVE REWARD + THE KT VALUE FUNCTION
#    r_theta = logpi_theta - logpi_ref  (the shared DPO/KTO building block).
#    We show BOTH the canonical prospect-theory value function (power form,
#    Tversky & Kahneman 1992 Eq, alpha=0.88, lambda=2.25) AND the KTO logistic
#    replacement that is actually used in the loss (sigma is also concave in
#    gains / convex in losses, but numerically stable).
# ============================================================================

def relative_logratio(logpi: float, logpi_ref: float) -> float:
    """r_theta(x,y) = log pi_theta(y|x) - log pi_ref(y|x).  (nats; NO beta.)"""
    return float(logpi - logpi_ref)


def relative_reward(logpi: float, logpi_ref: float, beta: float) -> float:
    """The DPO-style reward: beta * (logpi - logpi_ref) == beta * r_theta.

    This is the form TRL logs as `chosen_rewards = beta * chosen_logratios`.
    KTO factors beta out of the reward and into the value function; the two
    parameterizations are mathematically identical (see Section A table).
    """
    return beta * relative_logratio(logpi, logpi_ref)


def kt_value_canonical(z: float, lam: float = 2.25, alpha: float = 0.88,
                       z0: float = 0.0) -> float:
    """Canonical Kahneman-Tversky value function (Tversky & Kahneman 1992).

        v(z) =  (z - z0)^alpha             if z >= z0   (gain: concave)
              = -lam * (z0 - z)^alpha      if z <  z0   (loss: steeper by lam)

    Median human params: alpha = 0.88, lam = 2.25 (loss aversion). This is the
    prospect-theory FOUNDATION; KTO replaces the unstable power with a sigmoid
    but keeps the SAME three properties (reference point, concavity, loss avers.).
    """
    zt = torch.tensor(float(z))
    if z >= z0:
        return float(torch.pow(zt - z0, alpha))
    return float(-lam * torch.pow(torch.tensor(z0 - z), alpha))


def kto_value(r_theta: float, desirable: bool, beta: float, lam: float,
              z0: float) -> float:
    """The KTO logistic value function (paper Sec 4.1, value-function box).

        desirable  : v = lambda * sigma( beta * (r_theta - z0) )
        undesirable: v = lambda * sigma( beta * (z0 - r_theta) )

    sigma is concave in gains, convex in losses -- same shape as the canonical
    KT power function, but numerically stable (no exponent blow-up). This is
    what actually appears inside the KTO loss.
    """
    if desirable:
        arg = beta * (r_theta - z0)
    else:
        arg = beta * (z0 - r_theta)
    return float(lam * torch.sigmoid(torch.tensor(float(arg))))


def section_reward_and_value():
    banner("SECTION A: the relative reward r_theta + the KT value function")
    print("The shared DPO/KTO building block -- the RELATIVE REWARD (in nats):")
    print("    r_theta(x,y) = log pi_theta(y|x) - log pi_ref(y|x)")
    print("    relative_reward = beta * r_theta   (the DPO form TRL logs)")
    print()
    print("| logpi_theta | logpi_ref | r_theta (nats) | beta*r (reward) |")
    print("|-------------|-----------|----------------|-----------------|")
    # a few toy points spanning the gain/loss range (deterministic order)
    pts = [(-1.0, -1.6), (-0.9, -1.1), (-1.5, -1.0), (-1.0, -1.0), (-1.0, -0.6)]
    for logpi, logpi_ref in pts:
        r = relative_logratio(logpi, logpi_ref)
        rr = relative_reward(logpi, logpi_ref, BETA)
        print(f"| {logpi:>11.2f} | {logpi_ref:>9.2f} | {r:>14.4f} | {rr:>15.4f} |")
    print()
    print("Reading the table: a POSITIVE r means the policy raised y's prob")
    print("relative to the reference (SFT) model; a NEGATIVE r means it lowered")
    print("it. r=0 is the no-change point. beta simply rescales the axis.")
    print()
    print("---- the KT value function: canonical (power) vs KTO (logistic) ----")
    print("Prospect theory says humans are LOSS-AVERSE: a loss of magnitude d")
    print("hurts MORE than a gain of d pleases, by factor lambda (~2.25). And")
    print("both are measured RELATIVE to a reference point z0. Below: canonical")
    print("KT v(z) = z^0.88 (gain) / -2.25*(-z)^0.88 (loss), z0=0:")
    print()
    print("| z (outcome) | canonical v(z) |  KTO-logistic v(z) | meaning |")
    print("|-------------|----------------|---------------------|---------|")
    for z in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        vc = kt_value_canonical(z, lam=2.25, alpha=0.88, z0=0.0)
        # KTO-logistic analogue: gain branch for z>=0, loss branch (x2.25) for z<0
        if z >= 0.0:
            vk = kto_value(r_theta=z, desirable=True, beta=1.0, lam=1.0, z0=0.0)
        else:
            vk = kto_value(r_theta=z, desirable=False, beta=1.0, lam=2.25, z0=0.0)
        meaning = "reference pt (flat)" if z == 0.0 else (
            "LOSS (steeper)" if z < 0 else "gain (concave)")
        print(f"| {z:>11.2f} | {vc:>14.4f} | {vk:>19.4f} | {meaning} |")
    print()
    print("Both functions share the SAME three prospect-theory properties:")
    print("  (1) a REFERENCE POINT z0=0 (outcomes judged relative to it);")
    print("  (2) CONCAVITY in gains (diminishing sensitivity as z grows);")
    print("  (3) LOSS AVERSION (the loss column is steeper than the gain column).")
    # GOLD LOSS-AVERSION ANCHOR (the brief's second pinned value):
    v_gain = kt_value_canonical(0.5, lam=2.25, alpha=0.88, z0=0.0)
    v_loss = kt_value_canonical(-0.5, lam=2.25, alpha=0.88, z0=0.0)
    print()
    print("GOLD LOSS-AVERSION ANCHOR (canonical KT, lambda=2.25):")
    print(f"  v(+0.5) = 0.5^0.88       = {v_gain:+.4f}   (a gain of half a nat)")
    print(f"  v(-0.5) = -2.25*0.5^0.88 = {v_loss:+.4f}   (a loss of half a nat)")
    print(f"  |v(-0.5)| / v(+0.5)      = {abs(v_loss) / v_gain:.4f}  == lambda "
          f"(losses loom {abs(v_loss) / v_gain:.2f}x larger than gains)")
    # checks
    check("canonical KT is loss-averse: |v(-0.5)| > v(+0.5)",
          abs(v_loss) > v_gain)
    check("the loss-aversion ratio equals lambda exactly (2.25)",
          abs(abs(v_loss) / v_gain - 2.25) < 1e-6)
    check("canonical KT v(0) == 0 (reference point is flat)",
          abs(kt_value_canonical(0.0)) < 1e-9)
    check("relative_reward == beta * relative_logratio",
          abs(relative_reward(-1.0, -1.6, BETA) - BETA * 0.6) < 1e-9)
    check("r_theta is antisymmetric in (logpi, logpi_ref) swap",
          abs(relative_logratio(-1.0, -1.6) + relative_logratio(-1.6, -1.0)) < 1e-9)


# ============================================================================
# B. THE KTO PER-EXAMPLE LOSS (both branches)
#    L_example = lambda_y - v(x,y)
#      desirable  : lambda_D - lambda_D * sigma(beta*(r_theta - z0))
#      undesirable: lambda_U - lambda_U * sigma(beta*(z0 - r_theta))
#    Always >= 0 (since sigma in [0,1] and lambda >= 0) and finite.
# ============================================================================

def kto_example_loss(r_theta: float, desirable: bool, beta: float,
                     lam: float, z0: float) -> float:
    """Per-example KTO loss = lambda_y - v(x,y) (paper Eq 8)."""
    v = kto_value(r_theta, desirable, beta, lam, z0)
    return lam - v


def section_per_example_loss():
    banner("SECTION B: the KTO per-example loss (desirable + undesirable branches)")
    z0 = 0.0   # reference point held at 0 here; Section C estimates it from a batch
    print(f"With beta={BETA}, lambda_D=lambda_U={LAMBDA_D}, z0={z0} (held flat "
          f"here; Section C estimates z0 from a batch):")
    print()
    print("DESIRABLE branch (thumbs-up): the model is REWARDED for raising r")
    print("above z0. v = lambda_D*sigma(beta*(r-z0)); loss = lambda_D - v.")
    print("  -> a large POSITIVE r -> v near lambda_D -> loss near 0 (good).")
    print("  -> a NEGATIVE r (model wrongly lowered a good output) -> loss near lambda_D.")
    print()
    print("| r_theta | desirable v(r) | loss = 1 - v | reading |")
    print("|---------|----------------|--------------|---------|")
    for r in [1.0, 0.5, 0.0, -0.5, -1.0]:
        v = kto_value(r, desirable=True, beta=BETA, lam=LAMBDA_D, z0=z0)
        loss = kto_example_loss(r, True, BETA, LAMBDA_D, z0)
        reading = ("near 0 (great)" if r >= 0.5
                   else "near 1 (bad)" if r <= -0.5 else "boundary")
        print(f"| {r:>7.2f} | {v:>14.4f} | {loss:>12.4f} | {reading} |")
    print()
    print("UNDESIRABLE branch (thumbs-down): the model is PENALIZED for a")
    print("positive r on a bad output. v = lambda_U*sigma(beta*(z0-r)); loss =")
    print("lambda_U - v. NOTE the argument is FLIPPED (z0 - r).")
    print("  -> a NEGATIVE r (model correctly lowered a bad output) -> loss near 0.")
    print("  -> a POSITIVE r (model failed to lower a bad output) -> loss near lambda_U.")
    print()
    print("| r_theta | undesirable v(r) | loss = 1 - v | reading |")
    print("|---------|------------------|--------------|---------|")
    for r in [1.0, 0.5, 0.0, -0.5, -1.0]:
        v = kto_value(r, desirable=False, beta=BETA, lam=LAMBDA_U, z0=z0)
        loss = kto_example_loss(r, False, BETA, LAMBDA_U, z0)
        reading = ("near 1 (penalized)" if r >= 0.5
                   else "near 0 (correct)" if r <= -0.5 else "boundary")
        print(f"| {r:>7.2f} | {v:>16.4f} | {loss:>12.4f} | {reading} |")
    print()
    print("Key contrast: for the SAME r, the two branches demand OPPOSITE")
    print("behaviour. r=+0.5 gives loss 0.3775 on a DESIRABLE example (good --")
    print("the model correctly raised a good output) but loss 0.6225 on an")
    print("UNDESIRABLE example (bad -- the model failed to lower a bad output).")
    print("That sign-flip inside the sigmoid is the whole mechanism.")
    # checks: both branches are non-negative and finite for all r in a sweep
    rs = torch.linspace(-2.0, 2.0, 9).tolist()
    for desirable in (True, False):
        for r in rs:
            loss = kto_example_loss(r, desirable, BETA, LAMBDA_D, z0)
            ok = loss >= -1e-9 and torch.isfinite(torch.tensor(loss))
            check(f"{ 'desirable' if desirable else 'undesirable'} loss finite "
                  f"& >=0 at r={r:.2f}", ok)
    # the desirable and undesirable losses sum to lambda at r == z0 (boundary)
    ld = kto_example_loss(0.0, True, BETA, LAMBDA_D, z0)
    lu = kto_example_loss(0.0, False, BETA, LAMBDA_U, z0)
    check("at r=z0 both branches equal lambda/2 (=0.5 with lambda=1)",
          abs(ld - 0.5) < 1e-6 and abs(lu - 0.5) < 1e-6)
    # r=+0.5 desirable loss < r=+0.5 undesirable loss (the sign-flip effect)
    check("r=+0.5 desirable loss < r=+0.5 undesirable loss",
          kto_example_loss(0.5, True, BETA, 1.0, z0)
          < kto_example_loss(0.5, False, BETA, 1.0, z0))


# ============================================================================
# C. THE KL REFERENCE POINT z0 + THE BATCH LOSS  (GOLD ANCHOR for the .html)
#    z0 is prospect theory's reference point -- the expected reward the human
#    (and the model) compares against. KTO estimates it from the BATCH using a
#    biased, low-variance estimator (paper Sec 4.1):
#        z_hat_0 = max(0, (1/m) * sum_i log pi_theta(y_{(i+1)%m}|x_i)
#                                              - log pi_ref(y_{(i+1)%m}|x_i))
#    The mismatched outputs y_{(i+1)%m} proxy sampling from pi_theta without
#    the cost of actually sampling; the max(0,.) clamp gives a positive bias
#    but lower variance than the unbiased estimator. We do NOT backprop z0.
#    The batch loss averages the per-example branch losses with z0 plugged in.
# ============================================================================

def kl_reference_point(kl_logratios: list[float]) -> float:
    """Biased KL estimator z_hat_0 = max(0, mean(mismatched log-ratios)).

    kl_logratios[i] = log pi_theta(y_{(i+1)%m}|x_i) - log pi_ref(y_{(i+1)%m}|x_i)
    -- the mismatched-pair log-ratios from a second forward pass on SHIFTED
    outputs (TRL: KL_input_ids). Clamped at 0 for positive bias / low variance.
    """
    mean_lr = float(torch.tensor(kl_logratios).mean())
    return float(max(0.0, mean_lr))


def kto_batch_loss(batch: list, kl_logratios: list[float], beta: float,
                   lambda_d: float, lambda_u: float) -> tuple[float, float, list]:
    """KTO batch loss = mean over examples of (lambda_y - v(x,y)), with the
    shared z0 plugged into every v. Returns (batch_loss, z0, per_example)."""
    z0 = kl_reference_point(kl_logratios)
    per_example = []
    total = 0.0
    for label, logpi, logpi_ref in batch:
        r = relative_logratio(logpi, logpi_ref)
        lam = lambda_d if label else lambda_u
        loss = kto_example_loss(r, label, beta, lam, z0)
        v = lam - loss
        per_example.append((label, logpi, logpi_ref, r, v, loss))
        total += loss
    return total / len(batch), z0, per_example


def section_batch_loss():
    banner("SECTION C: KL reference point z0 + batch loss (GOLD ANCHOR)")
    print("The 4-example UNPAIRED toy batch (the GOLD inputs pinned for the .html):")
    print("| i | label        | logpi_theta | logpi_ref | r_theta |")
    print("|---|--------------|-------------|-----------|---------|")
    for i, (label, logpi, logpi_ref) in enumerate(TOY_BATCH):
        r = relative_logratio(logpi, logpi_ref)
        print(f"| {i} | {'desirable  ' if label else 'undesirable'} | "
              f"{logpi:>11.2f} | {logpi_ref:>9.2f} | {r:>7.4f} |")
    print()
    z0 = kl_reference_point(KL_LOGRATIOS)
    print("KL reference point z0 (prospect theory's reference point):")
    print(f"    mismatched-pair log-ratios = {KL_LOGRATIOS}")
    print(f"    z_hat_0 = max(0, mean({KL_LOGRATIOS}))")
    print(f"           = max(0, {torch.tensor(KL_LOGRATIOS).mean().item():+.4f})")
    print(f"           = {z0:.4f}")
    print("    (the max(0,.) clamp gives positive bias / low variance; we do")
    print("     NOT backprop through z0 -- it only controls loss saturation.)")
    print()
    batch_loss, z0, per_ex = kto_batch_loss(TOY_BATCH, KL_LOGRATIOS, BETA,
                                            LAMBDA_D, LAMBDA_U)
    print(f"Per-example value v and loss (beta={BETA}, lambda_D=lambda_U=1, "
          f"z0={z0:.4f}):")
    print("| i | label        | r_theta |   v(x,y) | loss=l-v | branch arg |")
    print("|---|--------------|---------|----------|----------|------------|")
    for i, (label, logpi, logpi_ref, r, v, loss) in enumerate(per_ex):
        arg = BETA * (r - z0) if label else BETA * (z0 - r)
        print(f"| {i} | {'desirable  ' if label else 'undesirable'} | "
              f"{r:>7.4f} | {v:>8.4f} | {loss:>8.4f} | {arg:>+10.4f} |")
    print()
    print("Reading the table like a story:")
    print("  - ex 0,1 (desirable, r>0): the policy correctly RAISED the prob")
    print(f"    of good outputs -> v is high -> loss is LOW ({per_ex[0][5]:.4f}, "
          f"{per_ex[1][5]:.4f}).")
    print("  - ex 2 (undesirable, r=+0.2): the policy FAILED to lower a bad")
    print("    output -> the undesirable branch's flipped argument is NEGATIVE")
    print(f"    -> v is LOW -> loss is HIGH ({per_ex[2][5]:.4f}). This is the")
    print("    example a loss-averse weighting (Section D) will hit hardest.")
    print("  - ex 3 (undesirable, r=-0.5): the policy correctly LOWERED a bad")
    print(f"    output -> flipped argument is positive -> v is high -> loss LOW "
          f"({per_ex[3][5]:.4f}).")
    print()
    print("GOLD PIN (kto_alignment.html recomputes this identically):")
    print("    batch loss = mean(per-example losses)")
    losses = [pe[5] for pe in per_ex]
    terms = " + ".join(f"{ls:.4f}" for ls in losses)
    print(f"              = ({terms}) / 4")
    print(f"              = {batch_loss:.4f}")
    print()
    # checks
    check("batch loss is finite and non-negative",
          torch.isfinite(torch.tensor(batch_loss)) and batch_loss >= 0.0)
    check("z0 == max(0, mean(KL_LOGRATIOS)) == 0.04",
          abs(z0 - 0.04) < 1e-9)
    check("ex 2 (undesirable, r=+0.2) has the HIGHEST loss in the batch",
          per_ex[2][5] == max(pe[5] for pe in per_ex))
    check("desirable examples (r>0) have loss < 0.5 (v > 0.5)",
          all(pe[5] < 0.5 for pe in per_ex if pe[0] and pe[3] > 0))
    check("batch loss is the mean of per-example losses",
          abs(batch_loss - sum(losses) / len(losses)) < 1e-9)
    return batch_loss, z0


# ============================================================================
# D. THE LOSS-AVERSION EFFECT  -- sweep lambda_U (loss-aversion weight)
#    Prospect theory: losses loom larger than gains. In KTO this is the lambda_U
#    weight on the undesirable branch. Sweeping lambda_U up while holding
#    lambda_D=1 makes the undesirable examples' losses count MORE -- the total
#    batch loss rises, and the optimizer is pushed harder to AVOID bad outputs.
#    The canonical prospect-theory lambda ~= 2.25; KTO tunes {lambda_D, lambda_U}
#    to the class balance (paper Eq 9: lambda_D*n_D / (lambda_U*n_U) in [1, 1.5]).
# ============================================================================

def section_loss_aversion():
    banner("SECTION D: the loss-aversion effect -- sweeping lambda_U")
    print("Prospect theory says losses are weighted MORE than gains (lambda ~= 2.25).")
    print("In KTO that knob is lambda_U: the weight on the undesirable branch.")
    print("Holding lambda_D=1 and beta=1, we sweep lambda_U over the toy batch")
    print("(which has 2 undesirable examples, one of which the model got WRONG):")
    print()
    print("| lambda_U | desirables loss | undesirables loss | BATCH loss | "
          "undesirable share |")
    print("|----------|-----------------|-------------------|------------|"
          "-------------------|")
    base_loss, z0, per_ex = kto_batch_loss(TOY_BATCH, KL_LOGRATIOS, BETA,
                                           LAMBDA_D, LAMBDA_U)
    sweep = []
    for lam_u in [0.5, 1.0, 1.5, 2.25]:
        # recompute per-example losses with the new lambda_U (lambda_D fixed at 1)
        des_total = 0.0
        und_total = 0.0
        n_des = 0
        n_und = 0
        for label, logpi, logpi_ref in TOY_BATCH:
            r = relative_logratio(logpi, logpi_ref)
            lam = LAMBDA_D if label else lam_u
            loss = kto_example_loss(r, label, BETA, lam, z0)
            if label:
                des_total += loss
                n_des += 1
            else:
                und_total += loss
                n_und += 1
        batch = (des_total + und_total) / (n_des + n_und)
        und_share = und_total / (des_total + und_total)
        sweep.append((lam_u, batch, und_share))
        print(f"| {lam_u:>8.2f} | {des_total:>15.4f} | {und_total:>17.4f} | "
              f"{batch:>10.4f} | {und_share:>17.4f} |")
    print()
    print("Reading the sweep:")
    print("  - as lambda_U rises, the undesirable examples' losses are scaled UP;")
    print("  - the batch loss INCREASES (the model is punished more for the bad")
    print("    output it failed to lower);")
    print("  - the undesirable share of the total loss grows -- exactly the")
    print("    'losses loom larger' effect from prospect theory.")
    print()
    print("NOTE on tuning (paper Eq 9): for class imbalance, set lambda_D, lambda_U")
    print("so that lambda_D*n_D / (lambda_U*n_U) is in [1, 1.5]. With this batch's")
    print("2:2 balance and lambda_D=1, the paper's rule gives lambda_U in "
          "[0.67, 1.0];")
    print("lambda_U=2.25 would be for a task where avoiding bad outputs (e.g.")
    print("toxicity) matters more than producing good ones.")
    # checks
    batch_losses = [s[1] for s in sweep]
    und_shares = [s[2] for s in sweep]
    check("batch loss is MONOTONE increasing in lambda_U",
          all(batch_losses[i] < batch_losses[i + 1] for i in range(len(batch_losses) - 1)))
    check("undesirable share of loss is MONOTONE increasing in lambda_U",
          all(und_shares[i] < und_shares[i + 1] for i in range(len(und_shares) - 1)))
    check("lambda_U=1.0 reproduces the Section C batch loss exactly",
          abs(sweep[1][1] - base_loss) < 1e-6)
    check("canonical prospect-theory lambda (2.25) gives the highest batch loss",
          sweep[-1][1] == max(batch_losses))


# ============================================================================
# E. THE DPO-vs-KTO DECISION RECAP  (when to use which)
# ============================================================================

def section_decision_recap():
    banner("SECTION E: the decision recap -- DPO (paired) vs KTO (unpaired)")
    rows = [
        ("RLHF / PPO", "reward model + PPO",
         "matches true human prefs", "2 stages, RL unstable, PAIRS needed"),
        ("DPO", "closed-form on (chosen, rejected) PAIRS",
         "no RL, no reward model", "STILL needs preference PAIRS"),
        ("KTO", "closed-form on UNPAIRED binary (thumbs-up/down)",
         "cheap abundant data; matches DPO at 1B-30B",
         "needs KL estimate z0; tune {lambda_D, lambda_U}"),
    ]
    print("| method    | data it needs                       | what it buys you       | "
          "the cost                              |")
    print("|-----------|-------------------------------------|------------------------|"
          "----------------------------------------|")
    for name, data, buys, cost in rows:
        print(f"| {name:<9} | {data:<35} | {buys:<22} | {cost:<38} |")
    print()
    print("The single question that picks the row:")
    print("  CAN YOU GET PAIRS (a human compares 2 outputs)?  -> DPO.")
    print("  ONLY UNPAIRED binary (thumbs-up/down) feedback?  -> KTO.")
    print("  Need the reward model for downstream eval too?   -> RLHF/PPO.")
    print()
    print("Practical: KTO often wins on cost-per-aligned-model because binary")
    print("feedback is ~free in production (every 👍/👎 is a training example),")
    print("whereas DPO pairs need a dedicated annotation pipeline.")
    check("the three methods differ in the data they consume",
          len({r[1] for r in rows}) == 3)


# ============================================================================
# main
# ============================================================================

def main():
    print("kto_alignment.py - reference impl. All numbers below feed "
          "KTO_ALIGNMENT.md.\ntorch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources (the KTO paper "
          "arXiv:2402.01306\n+ HuggingFace TRL + prospect theory 1992); see "
          "kto_alignment_reference.txt.")

    section_reward_and_value()
    section_per_example_loss()
    section_batch_loss()
    section_loss_aversion()
    section_decision_recap()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
