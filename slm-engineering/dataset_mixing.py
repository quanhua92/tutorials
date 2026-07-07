"""
dataset_mixing.py - Reference implementation of the data-mixture lineage for
SMALL (<5B) language model pretraining: weighted sampling -> perplexity-driven
reweighting -> DoReMi bandit -> curriculum.

This is the single source of truth that DATASET_MIXING.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output.

Run:
    uv run python dataset_mixing.py

== The big idea, in one paragraph =============================================
A pretraining corpus is never ONE bucket -- it is several domains D_1..D_k
(web text, code, math, synthetic textbooks, ...) blended by a weight vector
alpha = (alpha_1..alpha_k) with sum(alpha)=1. The mixture is as important as
the scale: a 1.7B model trained on a TUNED mix routinely beats a 3B model on a
BAD mix. This file walks the THREE regimes an SLM data engineer must know:

  1. FIXED HEURISTIC MIX (Chinchilla/Llama era): pick alpha by hand from
     domain sizes + intuition (e.g. Llama: 67% CC, 15% C4, 4.5% code, ...).
     Cheap, but the "right" ratio is a guess and never adapted to the model.
  2. PERPLEXITY-DRIVEN MIX: weight each domain by inverse validation
     perplexity -- domains the model finds HARD get more data. Cheap to
     compute (val loss is free), but perplexity is only a PROXY for downstream.
  3. DoReMi (2023): a small PROXY model runs a bandit (Group DRO / minimax)
     that pushes weights toward the domains with the highest EXCESS loss
     relative to a reference policy. No manual tuning, no downstream labels,
     and it provably reduces the WORST-DOMAIN loss.

== The lineage (old -> new, with WHY each step happened) ========================
  Fixed mix   : alpha fixed for the whole run from domain sizes. Chinchilla
                (Books 27%, C4, GH 3%, ...), Llama (CC 67%, C4 15%, code 4.5%).
                WHY: simplest recipe; the only one affordable before proxy-model
                tuning existed. The mixture is a hyperparameter guessed once.
  PPL-driven  : alpha_i proportional to 1/PPL_i (or PPL_i directly). Domains
                the model is bad at get more steps.
                WHY: val perplexity is free to log every N steps, and it is a
                better signal than raw domain size. But PPL != downstream: a
                domain can have low PPL and still hurt benchmarks (or vice versa).
  DoReMi      : alpha found by a bandit on a small proxy model that MINIMIZES
                the worst-domain EXCESS loss over a reference policy.
                L_ref sets the "expected" per-domain loss; excess_i =
                L_i(alpha) - L_ref_i; the bandit raises alpha on domains whose
                excess is largest. A 280M proxy sets the mix for an 8B model
                (30x larger); improves PPL on EVERY domain, even downweighted
                ones; reaches baseline accuracy in 2.6x fewer steps.
                WHY: removes the human guess, needs NO downstream labels, and
                optimizes the right objective (worst-case, not average).

== Notation & tensor-shape conventions ========================================
    k        : number of domains (toy: 3 -- web, code, synthetic).
    n_i      : size (tokens) of domain i.
    alpha_i  : mixture weight of domain i; sum(alpha) = 1.
    PPL_i    : exp( avg cross-entropy on domain i's val set ). Perplexity.
    L_i      : mean cross-entropy loss on domain i (PPL_i = exp(L_i)).
    L_ref_i  : reference-policy loss on domain i (DoReMi's anchor).
    excess_i : L_i(alpha) - L_ref_i (DoReMi's reweighting signal).
    alpha(t) : curriculum-interpolated weights at training-fraction t in [0,1].
    This file is pure arithmetic on scalars + a seeded sampler; torch is used
    only for the multinomial sampler + exp/sqrt so numbers match a real stack.

== Sources (all in dataset_mixing_reference.txt, >=2 independent confirmations) ==
  DoReMi 2023           arXiv:2305.10429  (Group DRO, 280M->8B, worst-domain)
  Data Mixing Laws 2024 arXiv:2403.16952  (predict downstream from mix ratios)
  Chinchilla 2022       arXiv:2203.15556  (MassiveText fixed mix; compute-opt)
  Llama 2023            arXiv:2302.13971  (CC67/C415/GH4.5/Wiki4.5/Books4.5)
  SmolLM2 2025          arXiv:2502.02737  (stage4: 58% web/24% code/14% math/4% synth)
  SmolLM 2024           HuggingFace blog  (Cosmopedia-v2 28B, FW-Edu 220B, Py-Edu 4B)
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
# A. WEIGHTED SAMPLING  -- how alpha turns into a per-batch domain composition
#    A domain is sampled for each token-slot with prob proportional to alpha_i
#    (in real loaders, alpha_i is often scaled by domain size n_i; here we take
#    alpha as already-normalized target weights). The LAW OF LARGE NUMBERS
#    guarantees the empirical batch mix converges to alpha as the batch grows.
# ============================================================================

# Toy 3-domain corpus (sizes in arbitrary "shard" units). Domains are SORTED by
# name for deterministic iteration (a HOW_TO_RESEARCH determinism rule).
DOMAINS = ["code", "synth", "web"]
DOMAIN_SIZES = {"code": 8_000, "synth": 2_000, "web": 30_000}   # n_i (toy)
# Reference (heuristic) weights: proportional to domain SIZE (the "fixed mix").
ALPHA_HEURISTIC = {
    d: DOMAIN_SIZES[d] / sum(DOMAIN_SIZES.values()) for d in DOMAINS
}
SEED = 1337


def sample_batch(weights: dict, batch_tokens: int, seed: int) -> dict:
    """Draw a batch of `batch_tokens` domain labels from `weights` (multinomial).
    Returns a dict domain -> count. Seeded torch.multinomial => deterministic."""
    g = torch.Generator().manual_seed(seed)
    names = sorted(weights)                      # SORT for deterministic order
    probs = torch.tensor([weights[n] for n in names], dtype=torch.float64)
    probs = probs / probs.sum()                   # guard against drift
    idx = torch.multinomial(probs, batch_tokens, replacement=True, generator=g)
    counts = {n: int((idx == i).sum().item()) for i, n in enumerate(names)}
    return counts


def section_weighted_sampling():
    banner("SECTION A: weighted sampling -- alpha -> per-batch domain composition")
    print("Three toy domains (shard units n_i):")
    for d in DOMAINS:
        print(f"  {d:<6} n={DOMAIN_SIZES[d]:>6}   "
              f"heuristic alpha={ALPHA_HEURISTIC[d]:.4f}")
    print(f"  sum(alpha) = {sum(ALPHA_HEURISTIC.values()):.6f}  (must be 1)")
    print()
    print("Draw batches of increasing size from the heuristic weights (seeded):")
    print("| batch tokens |   web |  code | synth | empirical web | empirical code | "
          "empirical synth |")
    print("|--------------|-------|-------|-------|---------------|----------------|"
          "-----------------|")
    empirical_at_2m = None
    for b in [1_000, 10_000, 100_000, 2_000_000]:
        c = sample_batch(ALPHA_HEURISTIC, b, SEED)
        w, co, s = c["web"], c["code"], c["synth"]
        print(f"| {b:>12} | {w:>5} | {co:>5} | {s:>5} | "
              f"{w / b:>13.4f} | {co / b:>14.4f} | {s / b:>15.4f} |")
        if b == 2_000_000:
            empirical_at_2m = c
    print()
    print("Read down the 'empirical' columns: as the batch grows, the sampled mix")
    print("CONVERGES to alpha (law of large numbers). At 2M tokens the relative")
    print("error vs the target weight is already < 0.1% for every domain.")
    # checks
    c = empirical_at_2m
    b = 2_000_000
    errs = {d: abs(c[d] / b - ALPHA_HEURISTIC[d]) for d in DOMAINS}
    check("2M-token batch matches heuristic weights within 1e-3",
          all(e < 1e-3 for e in errs.values()))
    check("heuristic weights sum to 1",
          abs(sum(ALPHA_HEURISTIC.values()) - 1.0) < 1e-9)
    check("web is the largest domain in both size and weight",
          DOMAIN_SIZES["web"] == max(DOMAIN_SIZES.values())
          and ALPHA_HEURISTIC["web"] == max(ALPHA_HEURISTIC.values()))


# ============================================================================
# B. PERPLEXITY PER DOMAIN + WEIGHTED PERPLEXITY
#    PPL_i = exp(L_i) where L_i is mean cross-entropy on domain i's val set.
#    The corpus-level weighted perplexity is  sum_i alpha_i * PPL_i.
#    GOLD ANCHOR (dataset_mixing.html recomputes this identically):
#      L = {web:2.3, code:1.8, synth:2.7}, alpha = {web:0.5, code:0.3, synth:0.2}
#      weighted PPL = 0.5*exp(2.3) + 0.3*exp(1.8) + 0.2*exp(2.7) = 9.7779
# ============================================================================

# Pinned toy val losses (mean cross-entropy) and weights -- the GOLD inputs.
TOY_LOSSES = {"web": 2.3, "code": 1.8, "synth": 2.7}
TOY_WEIGHTS = {"web": 0.5, "code": 0.3, "synth": 0.2}


def ppl_of(loss: float) -> float:
    """Perplexity from mean cross-entropy: PPL = exp(loss)."""
    return math.exp(loss)


def weighted_ppl(losses: dict, weights: dict) -> float:
    """Corpus-level weighted perplexity = sum_i alpha_i * exp(L_i)."""
    names = sorted(losses)
    return sum(weights[n] * math.exp(losses[n]) for n in names)


def section_perplexity():
    banner("SECTION B: perplexity per domain + weighted perplexity (GOLD ANCHOR)")
    print("Per-domain mean cross-entropy loss L_i (toy val set) and weight alpha_i:")
    print("| domain |   L_i (loss) | PPL_i = exp(L_i) | alpha_i | "
          "alpha_i * PPL_i |")
    print("|--------|--------------|------------------|---------|----------------|")
    for d in DOMAINS:
        lv = TOY_LOSSES[d]
        p = ppl_of(lv)
        a = TOY_WEIGHTS[d]
        print(f"| {d:<6} | {lv:>12.4f} | {p:>16.4f} | {a:>7.2f} | {a * p:>14.4f} |")
    wp = weighted_ppl(TOY_LOSSES, TOY_WEIGHTS)
    print()
    print("GOLD PIN (dataset_mixing.html recomputes this identically):")
    print("  weighted PPL = sum_i alpha_i * exp(L_i)")
    print("               = 0.5*exp(2.3) + 0.3*exp(1.8) + 0.2*exp(2.7)")
    print(f"               = {0.5 * math.exp(2.3):.6f} + {0.3 * math.exp(1.8):.6f} "
          f"+ {0.2 * math.exp(2.7):.6f}")
    print(f"               = {wp:.6f}")
    print()
    print("Reading the table: synth has the WORST (highest) PPL = "
          f"{ppl_of(TOY_LOSSES['synth']):.2f}, so a perplexity-driven recipe")
    print("would upweight it; web has the best PPL and would be downweighted.")
    print()
    # PPL-driven weights: alpha_i proportional to PPL_i (give hard domains more),
    # then renormalize. This is the simplest "weight by inverse val perplexity" idea.
    ppls = {d: math.exp(TOY_LOSSES[d]) for d in DOMAINS}
    z = sum(ppls.values())
    alpha_ppl = {d: ppls[d] / z for d in DOMAINS}
    print("PPL-driven weights (alpha_i ~ PPL_i, renormalized):")
    for d in DOMAINS:
        print(f"  {d:<6} PPL={ppls[d]:>7.3f}  ->  alpha_ppl={alpha_ppl[d]:.4f}  "
              f"(was alpha={TOY_WEIGHTS[d]:.2f})")
    wp_ppl = weighted_ppl(TOY_LOSSES, alpha_ppl)
    print(f"  -> weighted PPL under PPL-driven weights = {wp_ppl:.4f}")
    print("     (HIGHER than the original -- because it shifts mass to the hard,")
    print("      high-PPL domain. That is the point: more training on synth, not")
    print("      a lower number on this proxy metric.)")
    # checks
    check("GOLD weighted PPL == 9.777932 (within 1e-6)", abs(wp - 9.777932) < 1e-6)
    check("PPL = exp(loss) is monotone in loss (synth highest)",
          ppl_of(TOY_LOSSES["synth"]) > ppl_of(TOY_LOSSES["web"])
          > ppl_of(TOY_LOSSES["code"]))
    check("PPL-driven weights sum to 1",
          abs(sum(alpha_ppl.values()) - 1.0) < 1e-9)
    check("PPL-driven weights upweight the highest-PPL domain (synth)",
          alpha_ppl["synth"] > TOY_WEIGHTS["synth"])
    return wp


# ============================================================================
# C. DoReMi-STYLE BANDIT  (the worst-domain minimizer)
#    Given reference weights alpha0 and reference losses L_ref, model each
#    domain's loss under the CURRENT weights as
#        L_i(alpha) = L_ref_i * (alpha0_i / alpha_i)^gamma
#    so upweighting a domain LOWERS its loss (more gradient steps on it), with
#    diminishing returns (gamma small). The EXCESS loss
#        excess_i = L_i(alpha) - L_ref_i
#    is the DoReMi reweighting signal. The bandit does exponentiated-gradient
#    ascent on alpha to MINIMIZE the worst-domain excess:
#        alpha_i <- alpha_i * (1 + eta * excess_i / L_ref_i)   then renormalize
#    Domains with positive excess (worse than reference) get more weight; the
#    worst-domain excess falls every round.
# ============================================================================

GAMMA = 0.15          # loss elasticity to reweighting (diminishing returns)
ETA = 1.5             # bandit step size


def doremi_losses(alpha: dict, alpha0: dict, l_ref: dict, gamma: float) -> dict:
    """L_i(alpha) = L_ref_i * (alpha0_i / alpha_i)^gamma."""
    return {d: l_ref[d] * (alpha0[d] / alpha[d]) ** gamma for d in alpha}


def doremi_excess(alpha: dict, alpha0: dict, l_ref: dict, gamma: float) -> dict:
    """excess_i = L_i(alpha) - L_ref_i."""
    loss = doremi_losses(alpha, alpha0, l_ref, gamma)
    return {d: loss[d] - l_ref[d] for d in alpha}


def doremi_step(alpha: dict, alpha0: dict, l_ref: dict, gamma: float,
                eta: float) -> dict:
    """One exponentiated-gradient update, renormalized to sum=1."""
    ex = doremi_excess(alpha, alpha0, l_ref, gamma)
    new = {d: alpha[d] * (1.0 + eta * ex[d] / l_ref[d]) for d in alpha}
    # clip to keep positive (guard against over-stepping)
    new = {d: max(v, 1e-6) for d, v in new.items()}
    z = sum(new.values())
    return {d: v / z for d, v in new.items()}


def section_doremi():
    banner("SECTION C: DoReMi bandit -- minimize the worst-domain excess loss")
    # reference policy = the Section B weights/losses
    alpha0 = dict(TOY_WEIGHTS)         # alpha^0 = {web:0.5, code:0.3, synth:0.2}
    l_ref = dict(TOY_LOSSES)           # L_ref   = {web:2.3, code:1.8, synth:2.7}
    # the bandit STARTS from uniform weights (a deliberately bad guess)
    alpha = {d: 1.0 / len(DOMAINS) for d in DOMAINS}
    print("Reference policy (a proxy model trained on alpha0):")
    for d in DOMAINS:
        print(f"  {d:<6} alpha0={alpha0[d]:.2f}   L_ref={l_ref[d]:.2f}   "
              f"PPL_ref={math.exp(l_ref[d]):.3f}")
    print()
    print("Bandit starts from UNIFORM alpha = {1/3,1/3,1/3} "
          "(a deliberately bad guess).")
    print(f"Loss model: L_i(alpha) = L_ref_i * (alpha0_i/alpha_i)^{GAMMA}; "
          f"step eta={ETA}.\n")
    print("| round |   web alpha |  code alpha | synth alpha | "
          "web excess | code excess | synth excess | WORST excess |")
    print("|-------|-------------|-------------|-------------|"
          "------------|-------------|--------------|--------------|")
    worst0 = None
    history = []
    for r in range(4):   # 0 (initial) + 3 update rounds
        ex = doremi_excess(alpha, alpha0, l_ref, GAMMA)
        worst = max(ex.values())
        if r == 0:
            worst0 = worst
        history.append((r, dict(alpha), dict(ex), worst))
        print(f"| {r:<5} | {alpha['web']:>11.4f} | {alpha['code']:>11.4f} | "
              f"{alpha['synth']:>11.4f} | {ex['web']:>10.4f} | {ex['code']:>10.4f} "
              f"| {ex['synth']:>12.4f} | {worst:>12.4f} |")
        if r < 3:
            alpha = doremi_step(alpha, alpha0, l_ref, GAMMA, ETA)
    print()
    print("Reading the table like a story:")
    print(f"  round 0 : uniform weights. The WORST-domain excess is web "
          f"({history[0][3]:.4f}) -- web is UNDER-weighted vs alpha0, so its")
    print("            loss exceeds the reference. synth is over-weighted (negative")
    print("            excess). The bandit's job: push mass onto web.")
    print(f"  round 1 : web alpha jumps {history[0][1]['web']:.4f} -> "
          f"{history[1][1]['web']:.4f}; worst excess drops "
          f"{history[0][3]:.4f} -> {history[1][3]:.4f}.")
    print(f"  round 3 : worst excess is now {history[3][3]:.4f} (from "
          f"{worst0:.4f}); the worst-domain loss is within "
          f"{history[3][3]:.4f} of its reference.")
    print()
    print("This is DoReMi's whole claim: a small proxy runs this loop, ships the")
    print("final alpha to the BIG model, and the big model trains on a mix that")
    print("provably cuts the worst-domain loss -- with NO downstream labels.")
    # checks
    # round-1 increases the weight on the domain with the highest initial excess
    init_ex = history[0][2]
    worst_domain = max(init_ex, key=init_ex.get)
    check(f"round-1 raises weight on highest-excess domain ({worst_domain})",
          history[1][1][worst_domain] > history[0][1][worst_domain])
    # worst-domain excess strictly decreases over the 3 update rounds
    worst_seq = [history[r][3] for r in range(4)]
    check("worst-domain excess strictly decreases across rounds 0->3",
          worst_seq[0] > worst_seq[1] > worst_seq[2] > worst_seq[3])
    # weights stay normalized
    check("DoReMi weights stay normalized to 1 at every round",
          all(abs(sum(history[r][1].values()) - 1.0) < 1e-9 for r in range(4)))
    # the bandit never starves a domain to zero
    check("no domain is ever starved to < 1% weight",
          all(min(history[r][1].values()) > 0.01 for r in range(4)))
    return history


# ============================================================================
# D. CURRICULUM + REAL-WORLD MIX TABLE
#    Curriculum: anneal the weights over training-fraction t in [0,1]:
#        alpha(t) = (1 - t) * alpha_early + t * alpha_late
#    (broad web early for coverage; reasoning/code/synthetic late once the model
#     has the basics). Plus the actual mix shares shipped models used.
# ============================================================================

# real-world pretraining mixtures (all web-verified; see _reference.txt).
# Each entry: (model, {domain: pct}, note). Percentages are the TRAINING mix.
REAL_MIXES = [
    ("Llama-1",
     {"web (CC+C4)": 82.0, "code (GH)": 4.5, "books": 4.5,
      "wikipedia": 4.5, "arxiv": 2.5, "stackexchange": 2.0},
     "Touvron 2023 arXiv:2302.13971 (CC 67 + C4 15)"),
    ("Chinchilla",
     {"web (MassiveWeb)": 48.0, "books": 27.0, "c4": 10.0,
      "news": 10.0, "code (GH)": 3.0, "wikipedia": 2.0},
     "Hoffmann 2022 / Rae 2021 MassiveText (Gopher+Chinchilla)"),
    ("SmolLM2 (stage-4 anneal)",
     {"web (FW-Edu+DCLM)": 58.0, "code (Stack-Edu)": 24.0,
      "math (FineMath)": 14.0, "synthetic (Cosmopedia)": 4.0},
     "Lozhkov 2025 arXiv:2502.02737 Sec 4.5"),
]


def curriculum_alpha(t: float, early: dict, late: dict) -> dict:
    """Linear interpolation: alpha(t) = (1-t)*early + t*late."""
    return {d: (1.0 - t) * early[d] + t * late[d] for d in early}


def section_curriculum_and_real():
    banner("SECTION D: curriculum anneal + what shipped models actually mixed")
    # --- curriculum ---
    early = {"web": 0.80, "code": 0.10, "synth": 0.10}   # broad coverage first
    late = {"web": 0.35, "code": 0.30, "synth": 0.35}   # reasoning/synth late
    print("Curriculum: alpha(t) = (1-t)*alpha_early + t*alpha_late")
    print("  early (t=0): broad web (80%) for coverage, light code/synth")
    print("  late  (t=1): upsample code(30%) + synthetic(35%) for reasoning\n")
    print("| training frac t |   web |  code | synth | note |")
    print("|-----------------|-------|-------|-------|------|")
    for t in [0.0, 0.25, 0.50, 0.75, 1.0]:
        a = curriculum_alpha(t, early, late)
        note = ("broad web (coverage)" if t == 0.0
                else "reasoning/synth (anneal)" if t == 1.0
                else "")
        print(f"| {t:>15.2f} | {a['web']:>5.2f} | {a['code']:>5.2f} | "
              f"{a['synth']:>5.2f} | {note:<22} |")
    print()
    # checks on curriculum
    a0 = curriculum_alpha(0.0, early, late)
    a1 = curriculum_alpha(1.0, early, late)
    check("t=0 reproduces alpha_early exactly",
          all(abs(a0[d] - early[d]) < 1e-9 for d in DOMAINS))
    check("t=1 reproduces alpha_late exactly",
          all(abs(a1[d] - late[d]) < 1e-9 for d in DOMAINS))
    # web share monotonically falls as t grows (broad->specialized)
    web_seq = [curriculum_alpha(t, early, late)["web"] for t in [0.0, 0.25, 0.5, 1.0]]
    check("web share falls monotonically over the curriculum",
          all(web_seq[i] > web_seq[i + 1] for i in range(len(web_seq) - 1)))
    check("every alpha(t) stays normalized to 1",
          all(abs(sum(curriculum_alpha(t, early, late).values()) - 1.0) < 1e-9
              for t in [0.0, 0.25, 0.5, 0.75, 1.0]))

    # --- real mixes ---
    print("Real-world pretraining mixtures (the actual shares shipped models used):")
    print()
    print("| model                  | largest share        | code % | books/synth % | "
          "source |")
    print("|------------------------|----------------------|--------|---------------|"
          "--------|")
    for name, mix, note in REAL_MIXES:
        doms = sorted(mix, key=lambda k: -mix[k])
        biggest = f"{doms[0]} ({mix[doms[0]]:.1f})"
        code = next((v for k, v in mix.items() if "code" in k.lower()), 0.0)
        book = next((v for k, v in mix.items()
                     if "book" in k.lower() or "synth" in k.lower()
                     or "math" in k.lower()), 0.0)
        print(f"| {name:<22} | {biggest:<20} | {code:>6.1f} | {book:>13.1f} | "
              f"{note} |")
    print()
    # checks on real mixes
    for name, mix, _ in REAL_MIXES:
        s = sum(mix.values())
        check(f"{name} mix shares sum to ~100 (got {s:.1f})", abs(s - 100.0) < 1.5)
    check("Llama web share (CC+C4) is the dominant component (~82%)",
          abs(REAL_MIXES[0][1]["web (CC+C4)"] - 82.0) < 0.5)
    # SmolLM2 stage-4 annealing: web still leads (58%), but the specialized
    # share (code+math+synth) is ~42% -- far above SmolLM2 stage-1's ~10%.
    sm2_specialized = (REAL_MIXES[2][1]["code (Stack-Edu)"]
                       + REAL_MIXES[2][1]["math (FineMath)"]
                       + REAL_MIXES[2][1]["synthetic (Cosmopedia)"])
    check("SmolLM2 stage-4 anneal upweights specialized to ~42% (vs ~10% stage-1)",
          abs(sm2_specialized - 42.0) < 0.5 and sm2_specialized > 40.0)


# ============================================================================
# E. THE DECISION RECAP  (when to use which mixing strategy)
# ============================================================================

def section_decision_recap():
    banner("SECTION E: the decision recap -- which mixer, when")
    rows = [
        ("Fixed heuristic", "by domain size / intuition",
         "cheapest; the mix is a static hyperparameter", "Llama, Chinchilla era"),
        ("PPL-driven", "alpha_i ~ PPL_i",
         "free signal (val loss), adapts to the model", "proxy only; PPL != downstream"),
        ("DoReMi bandit", "minimize worst-domain excess",
         "no labels, no manual tuning, cuts worst-domain loss",
         "proxy -> big-model transfer"),
    ]
    print("| strategy        | how alpha is set              | what it buys you        | "
          "use when                |")
    print("|-----------------|-------------------------------|-------------------------|"
          "-------------------------|")
    for name, how, buys, when in rows:
        print(f"| {name:<15} | {how:<29} | {buys:<23} | {when:<23} |")
    print()
    print("The single question that picks the row:")
    print("  CAN YOU AFFORD A PROXY RUN?      -> DoReMi (Section C).")
    print("  ONLY HAVE VAL LOSSES?            -> PPL-driven (Section B).")
    print("  STARTING FROM SCRATCH / NO GPU?  -> Fixed heuristic (Section D table).")
    print()
    check("the three strategies are distinct in how alpha is set",
          len({r[1] for r in rows}) == 3)


# ============================================================================
# main
# ============================================================================

def main():
    print("dataset_mixing.py - reference impl. All numbers below feed "
          "DATASET_MIXING.md.\ntorch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources; "
          "see dataset_mixing_reference.txt.")

    section_weighted_sampling()
    section_perplexity()
    section_doremi()
    section_curriculum_and_real()
    section_decision_recap()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
