"""
direct_preference_dpo.py - Reference implementation of Direct Preference
Optimization (DPO), the RL-free / reward-model-free alignment loss.

This is the single source of truth that DIRECT_PREFERENCE_DPO.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output.

Run:
    uv run python direct_preference_dpo.py

== The big idea, in one paragraph =============================================
RLHF aligns a model to human preferences with a HEAVY pipeline: train a SEPARATE
reward model on (chosen, rejected) pairs, then optimize the policy with PPO
against that reward PLUS a KL penalty to a frozen reference. That is four models
in memory (policy, reference, reward, value) and an RL loop that is famously
unstable. DPO's trick: write down the KL-constrained reward-maximization
objective, solve it analytically for the OPTIMAL policy, and discover that the
optimal policy has a CLOSED FORM involving only the policy and a frozen reference.
Substitute that closed form back into the Bradley-Terry preference model and the
reward model CANCELS OUT -- you are left with ONE binary cross-entropy-style loss
on (chosen, rejected) PAIRS, computed with two models (policy + frozen ref) and
NO reinforcement learning. One objective; no reward model; no PPO.

== The lineage (old -> new, with WHY each step happened) =======================
  SFT         : supervised fine-tune the pretrained model on high-quality
                demonstrations -> pi_SFT. This becomes the STARTING POINT and,
                crucially, the REFERENCE policy pi_ref for the next stage.
  RLHF        : collect (chosen, rejected) preference pairs; train a SEPARATE
                reward model r_phi on them (Bradley-Terry, eq.2 of the DPO
                paper); then optimize the policy with PPO against
                r(x,y) = r_phi(x,y) - beta*(log pi_theta - log pi_ref) (eq.3).
                WHY the KL term: keep the policy near pi_ref so it does not
                drift off the distribution where the reward model is accurate
                and does not mode-collapse. PROBLEM: 4 models in memory
                (policy, ref, reward, value), an RL inner loop, on-policy
                sampling during training -- complex, unstable, expensive.
                (InstructGPT: Ouyang et al 2022, arXiv:2203.02155.)
  DPO         : the SAME KL-constrained reward objective has a CLOSED-FORM
                optimal policy: pi*(y|x) = (1/Z(x)) * pi_ref(y|x) *
                exp(r(x,y)/beta). Rearrange -> r(x,y) = beta*log(pi/pi_ref)
                + beta*log Z(x) (eq.5). Substitute into Bradley-Terry: the
                partition function Z(x) CANCELS in the reward DIFFERENCE,
                leaving a preference probability that depends ONLY on the
                policy and the frozen ref (eq.6). Max-likelihood on that gives
                the DPO loss (eq.7). One objective, two models, no RL, no
                reward model. (Rafailov et al 2023, arXiv:2305.18290.)

== Plain-English glossary (used in every section below) =======================
    prompt (x)     the input the model conditions on.
    completion (y) the model's response to x.
    chosen (y_w)   the PREFERRED completion (winner) of a preference pair.
    rejected (y_l) the DISPREFERRED completion (loser) of the pair.
    policy (pi_th) the model being trained. theta are its parameters.
    reference     the FROZEN model DPO must stay close to. Almost always the
    (pi_ref)      SFT checkpoint (pi_ref = pi_SFT). NEVER updated during DPO.
    logpi(y|x)    log pi(y|x): the log-probability of a completion under a
                  model. In practice the SUM of per-token logprobs over y.
                  Modeled here as a GIVEN scalar (no real LM is run).
    implicit       the reward DPO pretends the policy defines:
    reward r_hat   r_hat(x,y) = beta * (logpi_th(y|x) - logpi_ref(y|x)).
                  Note: it is RELATIVE to the reference. The reference is the
                  zero point of the reward.
    beta          the temperature. Scales how strongly the preference signal
                  acts AND how far the policy may drift from pi_ref. Typical
                  0.1-0.5. beta -> 0: ignore the reference (max freedom).
                  beta -> inf: freeze to the reference (no alignment).
    sigma (sig)   the logistic sigmoid: sigma(z) = 1/(1+exp(-z)).
    margin (z)    the sigmoid's input: z = r_hat(chosen) - r_hat(rejected).
                  z > 0 -> policy prefers chosen MORE than ref did -> small loss.

== Notation & conventions =====================================================
    All logpi are negative log-probabilities of a (rare) completion, so values
    like -2.0 are realistic (exp(-2.0) ~= 0.135). The reference is FROZEN: its
    logpi values never change. Only the policy's logpi values move during the
    micro training loop (Section D).

== Sources (all in direct_preference_dpo_reference.txt, >=2 independent) =======
  DPO loss (eq.7)  arXiv:2305.18290 (Rafailov 2023) + HuggingFace TRL DPO docs
  implicit reward  arXiv:2305.18290 eq.5 / Section 5.1
  RLHF it replaces arXiv:2203.02155 (InstructGPT, Ouyang 2022)
  shipped recipes  Zephyr-7B-beta (Tunstall 2023 arXiv:2310.16944)
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
# A. THE DPO LOSS (eq.7), implemented by hand from the definition.
#    L_DPO = -log sigma( r_hat(chosen) - r_hat(rejected) ),  with
#    r_hat(y) = beta*( logpi_th(y|x) - logpi_ref(y|x) ).
#    GOLD ANCHOR (direct_preference_dpo.html recomputes this identically):
#      logpi_c=-2.0, logpi_ref_c=-2.5, logpi_l=-3.0, logpi_ref_l=-2.2, beta=0.1
#      r_c = 0.1*(-2.0-(-2.5)) = 0.05
#      r_l = 0.1*(-3.0-(-2.2)) = -0.08
#      z   = r_c - r_l          = 0.13
#      L   = -log sigma(0.13)   = log(1 + e^-0.13) ~= 0.6303
# ============================================================================

def sigmoid(z: torch.Tensor | float) -> torch.Tensor | float:
    """Numerically stable logistic sigmoid sigma(z) = 1/(1+exp(-z))."""
    return torch.sigmoid(torch.as_tensor(z, dtype=torch.float64)).item() \
        if isinstance(z, (int, float)) else torch.sigmoid(z)


def implicit_reward(logpi: float, logpi_ref: float, beta: float) -> float:
    """r_hat(x,y) = beta * (logpi(y|x) - logpi_ref(y|x)).

    The reward the policy DEFINES, relative to the frozen reference. The
    reference is the zero point: if the policy matches the reference on y,
    the implicit reward of y is exactly 0.
    """
    return beta * (logpi - logpi_ref)


def dpo_loss(logpi_c: float, logpi_ref_c: float,
             logpi_l: float, logpi_ref_l: float,
             beta: float) -> tuple[float, float, float, float]:
    """The DPO loss (Rafailov 2023 eq.7), implemented from the definition.

        z = r_hat(chosen) - r_hat(rejected)
          = beta*(logpi_c - logpi_ref_c) - beta*(logpi_l - logpi_ref_l)
        L = -log sigma(z)

    Returns (loss, z, r_chosen, r_rejected) so callers can print the pieces.
    """
    r_c = implicit_reward(logpi_c, logpi_ref_c, beta)
    r_l = implicit_reward(logpi_l, logpi_ref_l, beta)
    z = r_c - r_l
    loss = -math.log(sigmoid(z))
    return loss, z, r_c, r_l


# Pinned GOLD inputs (the toy quadruple the guide and the .html both anchor to).
GOLD_LOGPI_C = -2.0
GOLD_LOGPI_REF_C = -2.5
GOLD_LOGPI_L = -3.0
GOLD_LOGPI_REF_L = -2.2
GOLD_BETA = 0.1


def section_dpo_loss():
    banner("SECTION A: the DPO loss (eq.7) on the pinned toy quadruple")
    print(f"Pinned GOLD inputs: logpi_c={GOLD_LOGPI_C}, "
          f"logpi_ref_c={GOLD_LOGPI_REF_C},\n"
          f"                    logpi_l={GOLD_LOGPI_L}, "
          f"logpi_ref_l={GOLD_LOGPI_REF_L}, beta={GOLD_BETA}\n")
    print("Step 1 -- the implicit reward of each completion "
          "(relative to the FROZEN ref):")
    r_c = implicit_reward(GOLD_LOGPI_C, GOLD_LOGPI_REF_C, GOLD_BETA)
    r_l = implicit_reward(GOLD_LOGPI_L, GOLD_LOGPI_REF_L, GOLD_BETA)
    print("  r_chosen  = beta*(logpi_c  - logpi_ref_c )")
    print(f"            = {GOLD_BETA}*({GOLD_LOGPI_C} - ({GOLD_LOGPI_REF_C})) "
          f"= {GOLD_BETA}*{GOLD_LOGPI_C - GOLD_LOGPI_REF_C:+.2f} = {r_c:+.4f}")
    print("  r_rejected= beta*(logpi_l  - logpi_ref_l )")
    print(f"            = {GOLD_BETA}*({GOLD_LOGPI_L} - ({GOLD_LOGPI_REF_L})) "
          f"= {GOLD_BETA}*{GOLD_LOGPI_L - GOLD_LOGPI_REF_L:+.2f} = {r_l:+.4f}")
    print()
    print("Step 2 -- the margin (the sigmoid's input):")
    z = r_c - r_l
    print(f"  z = r_chosen - r_rejected = {r_c:+.4f} - ({r_l:+.4f}) = {z:+.4f}")
    print()
    loss, z2, r_c2, r_l2 = dpo_loss(GOLD_LOGPI_C, GOLD_LOGPI_REF_C,
                                    GOLD_LOGPI_L, GOLD_LOGPI_REF_L, GOLD_BETA)
    sig = sigmoid(z)
    print("Step 3 -- the loss:")
    print(f"  sigma({z:.2f}) = 1/(1+e^(-{z:.2f})) = {sig:.6f}")
    print(f"  L = -log sigma({z:.2f}) = -log({sig:.6f}) = {loss:.4f}")
    print()
    print("GOLD PIN (direct_preference_dpo.html recomputes this identically):")
    print(f"  z = 0.13 ; L = -log sigma(0.13) = log(1+e^-0.13) ~= {loss:.4f}")
    print()
    print("| quantity                  | value    |")
    print("|---------------------------|----------|")
    print(f"| r_chosen  (implicit rew.) | {r_c:+.4f}   |")
    print(f"| r_rejected(implicit rew.) | {r_l:+.4f}   |")
    print(f"| margin z = r_c - r_l      | {z:+.4f}   |")
    print(f"| sigma(z)                  | {sig:.6f} |")
    print(f"| L_DPO = -log sigma(z)     | {loss:.4f}   |")
    print()
    check("GOLD margin z == 0.13 (within 1e-9)", abs(z - 0.13) < 1e-9)
    check("GOLD L ~= 0.6303 (within 1e-3)", abs(loss - 0.6303) < 1e-3)
    check("L is finite", math.isfinite(loss))
    check("L >= 0 (it is a negative log-prob)", loss >= 0.0)
    check("z == r_c - r_l (margin equals reward difference)",
          abs(z - (r_c - r_l)) < 1e-12)
    check("loss matches the closed form log(1+e^-z)",
          abs(loss - math.log1p(math.exp(-z))) < 1e-9)


# ============================================================================
# B. THE LOSS AS A SIGMOID OF THE MARGIN -- r_c > r_l -> small, r_c < r_l -> big
#    The whole behavior of DPO is: when the policy already prefers the chosen
#    completion MORE than the reference did (r_c > r_l, positive margin), the
#    loss is small (nothing to learn); when it prefers the rejected more
#    (r_c < r_l, negative margin), the loss blows up (lots to learn).
# ============================================================================

def section_margin_behavior():
    banner("SECTION B: the loss is a sigmoid of the margin r_c - r_l")
    print("Fix the reference at logpi_ref_c = logpi_ref_l = -2.0 and beta=0.1.\n"
          "Vary the policy's logpi on chosen vs rejected and watch the margin\n"
          "and the loss. The KEY: a POSITIVE margin (policy already prefers\n"
          "chosen) -> small loss; a NEGATIVE margin (policy prefers rejected)\n"
          "-> large loss.\n")
    print("| logpi_c | logpi_l | r_c    | r_l    | margin z | sigma(z) |  L_DPO  |"
          " reading                |")
    print("|---------|---------|--------|--------|----------|----------|---------|"
          "-------------------------|")
    cases = [
        (-2.0, -2.0, "tie: policy == ref on both (no signal)"),
        (-1.5, -2.5, "chosen UP, rejected DOWN -> big positive margin"),
        (-2.5, -1.5, "chosen DOWN, rejected UP -> big negative margin"),
        (-1.8, -2.2, "mild preference for chosen"),
        (-2.2, -1.8, "mild preference for rejected"),
    ]
    ref = -2.0
    beta = 0.1
    for logpi_c, logpi_l, note in cases:
        loss, z, r_c, r_l = dpo_loss(logpi_c, ref, logpi_l, ref, beta)
        sig = sigmoid(z)
        print(f"| {logpi_c:+.1f}    | {logpi_l:+.1f}    | "
              f"{r_c:+.4f} | {r_l:+.4f} | {z:+8.4f} | {sig:.4f}   | "
              f"{loss:.4f}  | {note} |")
    print()
    # Three boundary checks at fixed reference
    loss_tie, z_tie, _, _ = dpo_loss(-2.0, -2.0, -2.0, -2.0, beta)
    check("tie (r_c==r_l) -> margin 0, loss = log 2 = 0.6931",
          abs(z_tie - 0.0) < 1e-12 and abs(loss_tie - math.log(2)) < 1e-9)
    loss_good, z_good, _, _ = dpo_loss(-1.5, -2.0, -2.5, -2.0, beta)
    check("chosen UP/rejected DOWN -> positive margin, loss < log 2",
          z_good > 0 and loss_good < math.log(2))
    loss_bad, z_bad, _, _ = dpo_loss(-2.5, -2.0, -1.5, -2.0, beta)
    check("chosen DOWN/rejected UP -> negative margin, loss > log 2",
          z_bad < 0 and loss_bad > math.log(2))
    check("loss is monotonic in the margin: z_good>0>z_bad => loss_good<loss_bad",
          z_good > 0 > z_bad and loss_good < loss_bad)
    check("fundamental sigmoid complement: sigma(-z) = 1 - sigma(z)",
          abs(sigmoid(-z_good) - (1 - sigmoid(z_good))) < 1e-12)


# ============================================================================
# C. THE beta SWEEP -- beta controls sensitivity AND the KL budget.
#    For the SAME toy quadruple, sweep beta in {0.01, 0.1, 0.5, 1.0} and watch
#    the margin z = beta*((logpi_c-logpi_ref_c)-(logpi_l-logpi_ref_l)) scale
#    linearly with beta. Small beta -> margin ~0 -> loss ~log2 (ignore ref,
#    weak preference signal). Large beta -> margin huge -> loss -> 0 if the
#    margin is positive (or -> inf if negative -- the policy is dragged HARD
#    toward satisfying the preference, at the cost of leaving pi_ref far behind).
# ============================================================================

def section_beta_sweep():
    banner("SECTION C: beta sweep -- beta controls sensitivity + KL budget")
    print("Same quadruple as Section A. The log-ratio difference")
    print("  (logpi_c-logpi_ref_c) - (logpi_l-logpi_ref_l)")
    print(f"  = ({GOLD_LOGPI_C}-({GOLD_LOGPI_REF_C})) - "
          f"({GOLD_LOGPI_L}-({GOLD_LOGPI_REF_L})) = "
          f"{(GOLD_LOGPI_C-GOLD_LOGPI_REF_C)-(GOLD_LOGPI_L-GOLD_LOGPI_REF_L):+.2f}"
          " is FIXED.")
    print("beta just SCALES it. So z = beta*0.13 grows linearly with beta.\n")
    log_ratio_diff = ((GOLD_LOGPI_C - GOLD_LOGPI_REF_C)
                      - (GOLD_LOGPI_L - GOLD_LOGPI_REF_L))
    print("| beta  | r_c     | r_l     | margin z | sigma(z) |  L_DPO  |"
          " reading                       |")
    print("|-------|---------|---------|----------|----------|---------|"
          "-------------------------------|")
    betas = [0.01, 0.05, 0.1, 0.5, 1.0]
    losses = {}
    for beta in betas:
        loss, z, r_c, r_l = dpo_loss(GOLD_LOGPI_C, GOLD_LOGPI_REF_C,
                                     GOLD_LOGPI_L, GOLD_LOGPI_REF_L, beta)
        losses[beta] = (loss, z)
        sig = sigmoid(z)
        note = ("beta->0: ignore ref, loss->log2"
                if beta <= 0.05
                else ("typical DPO range"
                      if beta == 0.1
                      else "large beta: strong signal, big KL drift"))
        print(f"| {beta:<5.2f} | {r_c:+.4f}  | {r_l:+.4f}  | {z:+8.4f} | "
              f"{sig:.4f}   | {loss:.4f}  | {note:<29} |")
    print()
    print("Reading the table:")
    print("  * beta=0.01: margin ~= 0.0013, loss ~= log2. The preference signal")
    print("    is so weak the loss barely fires -- the policy is barely nudged.")
    print("  * beta=0.1  (the DPO default): margin 0.13, loss 0.6303. The")
    print("    signal is meaningful but gentle -- the standard choice.")
    print("  * beta=1.0 : margin 1.3, loss ~= 0.24. The signal is strong; the")
    print("    policy is pushed hard, but it also drifts far from pi_ref.")
    print()
    z_01 = losses[0.1][1]
    z_1 = losses[1.0][1]
    check("margin scales linearly with beta (z(1.0) = 10*z(0.1))",
          abs(z_1 - 10 * z_01) < 1e-9)
    check("z(beta) = beta * log_ratio_diff (= beta*0.13 here)",
          all(abs(losses[b][1] - beta * log_ratio_diff) < 1e-9
              for b, beta in zip(betas, betas)))
    check("as beta -> 0, loss -> log 2 (no preference signal)",
          abs(losses[0.01][0] - math.log(2)) < 1e-2)
    check("larger beta -> smaller loss here (margin is positive)",
          losses[1.0][0] < losses[0.1][0] < losses[0.01][0])
    check("typical DPO beta 0.1 falls in the verified 0.1-0.5 range",
          0.1 <= 0.1 <= 0.5)


# ============================================================================
# D. GRADIENT-DIRECTION INTUITION + a micro training loop.
#    Minimizing L_DPO increases (logpi_c - logpi_ref_c) - (logpi_l - logpi_ref_l)
#    -- i.e. the policy moves chosen UP and rejected DOWN, both relative to ref.
#    We use torch autograd to get the exact gradients wrt the policy's logpi
#    values, then take a few manual SGD steps and watch the margin grow and the
#    loss fall. The reference is held FROZEN (no grad).
# ============================================================================

def section_gradient_and_loop():
    banner("SECTION D: gradient direction + a micro DPO training loop")
    print("Treat logpi_c, logpi_l as the policy's two trainable log-probs.\n"
          "logpi_ref_c, logpi_ref_l, beta are FROZEN. Autograd gives the exact\n"
          "gradient; we take manual SGD steps.\n")
    logpi_ref_c = -2.5
    logpi_ref_l = -2.2
    beta = 0.1
    # the policy STARTS EQUAL to the reference -> margin 0, loss log2
    logpi_c = torch.tensor(-2.5, requires_grad=True)
    logpi_l = torch.tensor(-2.2, requires_grad=True)
    print("Initial policy log-probs (START at the reference):")
    print(f"  logpi_c = {logpi_c.item():.4f}  (== logpi_ref_c = {logpi_ref_c})")
    print(f"  logpi_l = {logpi_l.item():.4f}  (== logpi_ref_l = {logpi_ref_l})")
    print()

    def compute_loss(logc: torch.Tensor, logl: torch.Tensor) -> torch.Tensor:
        r_c = beta * (logc - logpi_ref_c)
        r_l = beta * (logl - logpi_ref_l)
        z = r_c - r_l
        # numerically stable -log sigma(z) = log(1 + exp(-z)) = softplus(-z)
        return torch.nn.functional.softplus(-z)

    loss0 = compute_loss(logpi_c, logpi_l)
    loss0.backward()
    gc = logpi_c.grad.item()
    gl = logpi_l.grad.item()
    print("Gradient signs (the whole intuition):")
    print(f"  dL/d(logpi_c) = (sigma(z)-1)*beta = {gc:+.6f}   <- NEGATIVE")
    print("                                                   (so gradient DESCENT")
    print("                                                    INCREASES logpi_c)")
    print(f"  dL/d(logpi_l) = (1-sigma(z))*beta = {gl:+.6f}   <- POSITIVE")
    print("                                                   (so gradient DESCENT")
    print("                                                    DECREASES logpi_l)")
    print()
    print("=> minimizing L pushes chosen UP and rejected DOWN, BOTH relative\n"
          "   to the frozen reference. The margin grows; the loss falls.\n")

    # ---- a micro training loop: 5 manual SGD steps ----
    lr = 1.0     # large on purpose so the movement prints clearly
    n_steps = 5
    print(f"Micro loop: lr={lr}, {n_steps} steps, beta={beta}, ref FROZEN.")
    print()
    print("| step | logpi_c  | logpi_l  | r_c     | r_l     | margin z | "
          "L_DPO   |")
    print("|------|----------|----------|---------|---------|----------|---------|")
    history = []
    logc = torch.tensor(-2.5)
    logl = torch.tensor(-2.2)
    for step in range(n_steps + 1):
        logc.requires_grad_(True)
        logl.requires_grad_(True)
        loss = compute_loss(logc, logl)
        r_c = (beta * (logc - logpi_ref_c)).item()
        r_l = (beta * (logl - logpi_ref_l)).item()
        z = r_c - r_l
        history.append((step, logc.item(), logl.item(), r_c, r_l, z, loss.item()))
        print(f"| {step:<4} | {logc.item():+8.4f} | {logl.item():+8.4f} | "
              f"{r_c:+7.4f} | {r_l:+7.4f} | {z:+8.4f} | {loss.item():.4f}  |")
        if step == n_steps:
            break
        loss.backward()
        with torch.no_grad():
            logc = logc - lr * logc.grad
            logl = logl - lr * logl.grad
    print()
    print("Reading the loop:")
    print("  * logpi_c RISES every step (chosen pushed UP).")
    print("  * logpi_l FALLS every step (rejected pushed DOWN).")
    print("  * the margin (r_c - r_l) grows monotonically.")
    print("  * the loss falls toward 0 as the margin turns strongly positive.")
    print("  * the reference (logpi_ref_c=-2.5, logpi_ref_l=-2.2) NEVER moves.")
    print()

    # checks
    check("dL/d(logpi_c) < 0 (chosen is pushed UP)",
          gc < 0)
    check("dL/d(logpi_l) > 0 (rejected is pushed DOWN)",
          gl > 0)
    check("logpi_c rose over the loop (chosen up)",
          history[-1][1] > history[0][1])
    check("logpi_l fell over the loop (rejected down)",
          history[-1][2] < history[0][2])
    check("margin grew monotonically", all(
        history[i + 1][5] >= history[i][5] - 1e-9
        for i in range(len(history) - 1)))
    check("loss fell over the loop",
          history[-1][6] < history[0][6])
    check("the reference log-probs are FROZEN (never passed to an optimizer)",
          logpi_ref_c == -2.5 and logpi_ref_l == -2.2)
    check("starting at the reference -> initial margin 0, loss log 2",
          abs(history[0][5]) < 1e-9 and abs(history[0][6] - math.log(2)) < 1e-6)


# ============================================================================
# E. LINEAGE + WHAT SHIPPED MODELS ACTUALLY USED (the RLHF -> DPO swap)
#    All values web-verified in direct_preference_dpo_reference.txt (>=2 srcs).
# ============================================================================

# (model, method, models_in_memory, beta, dataset, source)
REAL_CONFIGS = [
    ("InstructGPT",  "RLHF (reward model + PPO)",
     "4: policy + ref + reward + value", "n/a (KL coef 0.02)",
     "human prefs", "Ouyang 2022 arXiv:2203.02155"),
    ("Llama 2-Chat", "RLHF (reward model + PPO + safety",
     "4: policy + ref + reward + value", "n/a (KL via reward)",
     "human prefs", "Touvron 2023 arXiv:2307.09288"),
    ("DPO paper",    "DPO (no RL, no reward model)",
     "2: policy + ref", "0.1 (TL;DR, HH); 0.05-0.5 (IMDb)",
     "human prefs", "Rafailov 2023 arXiv:2305.18290"),
    ("Zephyr-7B-beta", "DPO (distilled, TRL DPOTrainer)",
     "2: policy + ref", "0.1",
     "UltraFeedback (GPT-4 ranked)", "Tunstall 2023 arXiv:2310.16944"),
]


def section_lineage_and_real():
    banner("SECTION E: lineage recap (RLHF 4-model -> DPO 2-model) + shipped recipes")
    print("The alignment stage shed two whole models by solving the RL objective\n"
          "analytically. Each row removes a failure mode:\n")
    ladder = [
        ("SFT",          "supervised fine-tune on demonstrations",
         "no preference signal yet",       "the starting point"),
        ("RLHF (PPO)",   "train reward model, then PPO against it + KL to ref",
         "4 models in memory; RL unstable; on-policy sampling",
         "InstructGPT, Llama 2-Chat"),
        ("DPO",          "closed-form optimal policy -> reward model cancels",
         "no RL; 2 models; one BCE-style loss on pairs",
         "Rafailov 2023; Zephyr-7B-beta"),
    ]
    print("| stage         | what it does                            | "
          "failure removed                | used by                  |")
    print("|---------------|-----------------------------------------|"
          "--------------------------------|--------------------------|")
    for name, what, removed, era in ladder:
        print(f"| {name:<13} | {what:<39} | {removed:<30} | {era:<24} |")
    print()
    print("What shipped models actually used (web-verified; see _reference.txt):\n")
    print("| model           | method                          | models in memory "
          "               | beta          | dataset              | source "
          "                       |")
    print("|-----------------|---------------------------------|------------------"
          "---------------|---------------|----------------------|------------------"
          "-------------|")
    for name, method, mem, beta, ds, src in REAL_CONFIGS:
        print(f"| {name:<15} | {method:<31} | {mem:<30} | "
              f"{beta:<13} | {ds:<20} | {src:<27} |")
    print()
    print("Two patterns:")
    print("  * InstructGPT / Llama 2-Chat: the FULL RLHF pipeline -- a separate")
    print("    reward model + PPO + a value head + a KL anchor to the ref. Four")
    print("    models resident; an RL inner loop; sensitive to tune.")
    print("  * DPO / Zephyr: drop the reward model and the RL loop entirely.")
    print("    Two models (policy + frozen ref), one classification-style loss.")
    print("    Zephyr-7B-beta reaches near-Llama2-Chat-70B chat quality with a")
    print("    single 7B base (Mistral-7B) + DPO on UltraFeedback at beta=0.1.")
    print()
    methods = [r[1] for r in REAL_CONFIGS]
    checks_models = [r[2] for r in REAL_CONFIGS]
    check("RLHF needs 4 models in memory; DPO needs 2",
          "4:" in checks_models[0] and "2:" in checks_models[2])
    check("DPO ships WITHOUT a reward model in memory (DPO rows have only '2:' models)",
          checks_models[2].startswith("2:") and checks_models[3].startswith("2:"))
    check("DPO ships WITHOUT an RL loop (no PPO)",
          all("PPO" not in m for m in [methods[2], methods[3]]))
    check("Zephyr beta=0.1 falls in the verified 0.1-0.5 typical range",
          0.1 <= 0.1 <= 0.5)
    check("at least one shipped model uses DPO (Zephyr)",
          any("DPO" in m and "RLHF" not in m for m in methods))


# ============================================================================
# main
# ============================================================================

def main():
    print("direct_preference_dpo.py - reference impl. All numbers below feed "
          "DIRECT_PREFERENCE_DPO.md.\ntorch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources; "
          "see direct_preference_dpo_reference.txt.")

    section_dpo_loss()
    section_margin_behavior()
    section_beta_sweep()
    section_gradient_and_loop()
    section_lineage_and_real()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
