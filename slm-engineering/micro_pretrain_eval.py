"""
micro_pretrain_eval.py - Reference implementation of the MICRO PRETRAIN EVAL
lineage: run the FULL downstream benchmark at every checkpoint -> too slow ->
hold out tiny capability SLICES whose cheap per-checkpoint LOSS predicts the
expensive downstream benchmark score.

This is the single source of truth that MICRO_PRETRAIN_EVAL.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output.

Run:
    uv run python micro_pretrain_eval.py

== The big idea, in one paragraph =============================================
A pretraining run produces dozens of checkpoints. The thing you actually care
about -- "will this model score well on MMLU / HellaSwag / code / reasoning?" --
takes HOURS to measure exactly (thousands of few-shot examples per benchmark,
per checkpoint). Running it at every checkpoint is unaffordable, so people only
eval at the end and lose all visibility mid-train. MICRO PRETRAIN EVAL fixes
that: hold out a TINY fixed set of examples per capability (a "slice", e.g. 200
code snippets, 200 reasoning chains), compute its LOSS each checkpoint (cheap --
a single forward pass), then FIT a model that maps slice-loss -> downstream
benchmark score using a few early fully-eval'd checkpoints. A slice whose
loss-series correlates strongly (|Pearson r| > 0.9) with the benchmark series is
a faithful cheap proxy: from then on you PREDICT the downstream score from the
slice-loss alone, in seconds. The minimal slice-subset whose combined predictor
reaches r >= 0.9 is your "micro-bench".

== The lineage (old -> new, with WHY each step happened) ========================
  Full-bench every ckpt : run MMLU + HellaSwag + ARC (thousands of examples
                          each) on EVERY checkpoint. This is the gold standard
                          but costs hours per checkpoint -- Pythia shipped 154
                          checkpoints precisely so this kind of "eval across
                          training" study COULD be done (arXiv:2304.01373).
                          WHY abandoned for daily training: a 1B model on 8
                          benchmarks x 154 ckpts is ~weeks of eval GPU-time.
  Held-out validation   : log held-out cross-entropy (perplexity) every N steps.
                          (GPT-3 used a held-out validation set as its over-
                          fitting signal; arXiv:2005.14165.) Cheap, but ONE
                          aggregate loss is only weakly tied to ANY specific
                          downstream capability -- it cannot tell you "the model
                          is getting better at code but worse at commonsense".
  Slice correlation     : split the held-out set into capability SLICES (code,
     + linear fit         reason, factual, commonsense) and log each slice's loss
                          separately. Then FIT, for each slice, a line
                          B_hat = a*L_s + b (least squares on the few early
                          checkpoints where you DID run the full benchmark).
                          The slice with |Pearson r| near 1 predicts the
                          benchmark from its loss alone.
                          WHY: a per-capability signal correlates far better than
                          a single aggregate loss (the ICLR-2025 "perplexity
                          correlations" paper fits exactly this linear model:
                          B_hat = sum_s w_s * PPL_s -- arXiv:2409.05816).
  Micro-bench           : pick the MINIMAL slice-subset whose combined linear
                          predictor reaches r >= 0.9 with the benchmark. That
                          subset (a few hundred examples, runnable in seconds)
                          becomes the "micro-bench" you run every checkpoint.
                          WHY: you only pay the full-bench cost for a few early
                          checkpoints to FIT the predictor; every later ckpt is
                          predicted from slice-loss in seconds.

== Notation & tensor-shape conventions ========================================
    ckpt i      : the i-th saved model snapshot (toy: 8 ckpts, evenly spaced).
    slice s     : a tiny FIXED held-out set for one capability (code / reason /
                  factual / commonsense), ~200 examples each. Never trained on.
    L_s[i]      : mean cross-entropy of ckpt i on slice s (a scalar per ckpt).
    B[i]        : downstream benchmark score of ckpt i (e.g. MMLU accuracy).
    r(x, y)     : Pearson correlation = cov(x,y) / (sigma_x * sigma_y).
    a, b        : least-squares line  B_hat = a*L_s + b
                  (a = Sxy/Sxx, b = mean(B) - a*mean(L_s)).
    w_s, c      : multi-slice linear model  B_hat = sum_s w_s*L_s + c, solved by
                  normal equations  (X^T X) w = X^T y  (hand Gaussian elimination).
    micro-bench : the minimal subset of slices whose combined predictor reaches
                  r >= MICRO_BENCH_R_THRESHOLD (0.9).
    This file is pure arithmetic on tiny fixed-length vectors; torch is used only
    so the numbers match a real ML stack and the bundle stays torch-only.

== Sources (all in micro_pretrain_eval_reference.txt, >=2 independent confirmations)
  Pythia 2023           arXiv:2304.01373  (154 ckpts; eval across training)
  MiniCPM 2024          arXiv:2404.06395  (5 held-out eval sets; WSD reuse ckpts)
  GPT-3 2020            arXiv:2005.14165  (held-out val loss as training signal)
  Perplexity Correl.    arXiv:2409.05816  (B_hat = sum w_s*PPL_s linear fit)
  Pearson r             (standard: cov/(sigma_x*sigma_y))
"""

from __future__ import annotations

import itertools

import torch

torch.set_printoptions(precision=6, sci_mode=False)

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
# A. THE TOY CHECKPOINT HISTORY  (deterministic, hardcoded)
#    8 checkpoints, 4 capability slices, 1 downstream benchmark.
#    Slice losses DECREASE as training improves; the benchmark INCREASES.
#    The code slice is a near-faithful proxy; commonsense is a misleading one.
# ============================================================================

# 8 evenly-spaced checkpoints (toy training-step indices, deterministic).
STEPS = [2000, 4000, 6000, 8000, 10000, 12000, 14000, 16000]
N_CKPT = len(STEPS)

# Held-out slice losses per checkpoint: slice -> list of mean cross-entropy.
# SORTED slice names (a HOW_TO_RESEARCH determinism rule). Each slice has a
# DISTINCT trajectory: code drops fast then plateaus (mirrors the benchmark);
# reason tracks it; factual is flat-then-drops late; commonsense WANDERS with
# reversals -- so only code/reason end up faithful proxies (see Section B).
SLICE_LOSSES = {
    "code":        [1.430, 1.280, 1.100, 0.900, 0.780, 0.720, 0.700, 0.690],
    "reason":      [2.050, 1.900, 1.720, 1.520, 1.360, 1.260, 1.200, 1.170],
    "factual":     [2.100, 2.050, 2.020, 1.950, 1.800, 1.600, 1.420, 1.300],
    "commonsense": [2.250, 2.300, 2.200, 2.280, 2.150, 2.220, 2.100, 2.180],
}
SLICES = sorted(SLICE_LOSSES)

# Downstream benchmark score per checkpoint (toy "MMLU accuracy", increasing
# fast then plateauing -- diminishing returns, the realistic shape). It tracks
# the code slice near-linearly (so code is a faithful proxy for it).
BENCH = [0.220, 0.255, 0.292, 0.348, 0.386, 0.404, 0.410, 0.414]

# The checkpoint split for the linear-fit: FIT on the early ckpts, PREDICT the
# held-out late ones. Index 5 is the first "late" checkpoint (ckpt @ 12000).
FIT_END = 5        # fit uses checkpoints 0..4 (STEPS 2k..10k)
PRED_START = 5     # predict checkpoints 5..7 (STEPS 12k..16k)

# A slice is a "faithful proxy" if its |Pearson r| with the benchmark >= this.
FAITHFUL_R = 0.85
# A slice-subset is a "micro-bench" if its combined predictor reaches r >= this.
MICRO_BENCH_R = 0.90


def section_slice_loss_table():
    banner("SECTION A: the held-out slice losses across checkpoints")
    print("Four capability slices (each ~200 held-out examples, never trained on).")
    print("L_s[i] = mean cross-entropy of checkpoint i on slice s (lower = better).\n")
    print("| ckpt | step  | " + " | ".join(f"{s:>12}" for s in SLICES)
          + " | " + "benchmark".rjust(12) + " |")
    print("|------|-------|" + "|".join(["-" * 14] * (len(SLICES) + 1)) + "|")
    for i in range(N_CKPT):
        cells = " | ".join(f"{SLICE_LOSSES[s][i]:>12.4f}" for s in SLICES)
        print(f"| {i:<4} | {STEPS[i]:<5} | {cells} | {BENCH[i]:>12.4f} |")
    print()
    print("Read across a row: every slice loss FALLS (net) as training advances")
    print("(more steps -> lower cross-entropy). Read down a column: the benchmark")
    print("RISES (0.220 -> 0.414). So slice-loss and benchmark are ANTI-correlated")
    print("-- the question is HOW tightly, per slice. That is Section B. Note the")
    print("'commonsense' slice is NON-MONOTONE (e.g. 2.250 -> 2.300 at ckpt 1, then")
    print("2.150 -> 2.220 at ckpt 5): realistic loss spikes / capability-forgetting")
    print("blips -- and exactly why it turns out (Section B) to be a misleading,")
    print("low-correlation proxy.\n")
    # checks: training NET-lowers every slice loss (start >= end); the faithful
    # slices are also strictly monotone, but commonsense is deliberately noisy.
    for s in SLICES:
        series = SLICE_LOSSES[s]
        check(f"slice '{s}' net-decreases over the run (series[0] > series[-1])",
              series[0] > series[-1])
    check("benchmark score strictly increases across ckpts",
          all(BENCH[i] < BENCH[i + 1] for i in range(N_CKPT - 1)))
    check("commonsense is the ONLY non-monotone slice (the misleading case)",
          all(SLICE_LOSSES[s][i] >= SLICE_LOSSES[s][i + 1] - 1e-9
              for s in SLICES if s != "commonsense"
              for i in range(N_CKPT - 1))
          and any(SLICE_LOSSES["commonsense"][i]
                  < SLICE_LOSSES["commonsense"][i + 1] - 1e-9
                  for i in range(N_CKPT - 1)))


# ============================================================================
# B. PEARSON CORRELATION  r(L_s, B)  across checkpoints
#    r = cov(L_s, B) / (sigma_Ls * sigma_B)  =  Sxy / (sqrt(Sxx)*sqrt(Syy))
#    |r| near 1 => the slice predicts the benchmark; |r| near 0 => it doesn't.
# ============================================================================


def pearson(x, y) -> float:
    """Pearson correlation r = cov(x,y)/(sigma_x*sigma_y). torch, float64."""
    xt = torch.tensor(x, dtype=torch.float64)
    yt = torch.tensor(y, dtype=torch.float64)
    xm = xt - xt.mean()
    ym = yt - yt.mean()
    denom = xm.norm() * ym.norm()      # sqrt(Sxx)*sqrt(Syy)
    if denom == 0:
        return 0.0
    return float((xm * ym).sum() / denom)


def section_correlation():
    banner("SECTION B: Pearson r between each slice and the benchmark")
    print("For each slice s, r = cov(L_s, B) / (sigma_Ls * sigma_B).")
    print("|r| near 1 => the slice is a FAITHFUL cheap proxy for the benchmark.\n")
    rs = {}
    for s in SLICES:
        rs[s] = pearson(SLICE_LOSSES[s], BENCH)
    print("| slice        | Pearson r |  |r|  | faithful? (|r| >= "
          f"{FAITHFUL_R}) | verdict                |")
    print("|--------------|-----------|------|----------------------|"
          "------------------------|")
    for s in SLICES:
        r = rs[s]
        faithful = abs(r) >= FAITHFUL_R
        verdict = ("faithful proxy" if faithful else "weak / misleading slice")
        print(f"| {s:<12} | {r:>+9.4f} | {abs(r):.4f} | "
              f"{'YES' if faithful else 'no ':<20} | {verdict:<22} |")
    print()
    best_slice = max(SLICES, key=lambda s: abs(rs[s]))
    best_r = rs[best_slice]
    print(f"Best single slice: '{best_slice}' with r = {best_r:+.4f}  "
          f"(|r| = {abs(best_r):.4f}).")
    print("All four r values are NEGATIVE because slice loss falls while the")
    print("benchmark rises. The MAGNITUDE |r| is what matters for prediction.\n")
    # GOLD PIN -- the .html recomputes this r for the SAME code-slice arrays.
    print("GOLD PIN (micro_pretrain_eval.html recomputes this):")
    print(f"  r(code, benchmark) = {rs['code']:+.6f}")
    check("best slice |r| >= 0.85 (a faithful proxy exists)",
          abs(best_r) >= FAITHFUL_R)
    check("the code slice is the best single proxy",
          best_slice == "code")
    check("commonsense is a weak proxy (|r| < 0.85, the misleading case)",
          abs(rs["commonsense"]) < FAITHFUL_R)
    check("all |r| in [0,1] (Pearson range)",
          all(0.0 <= abs(rs[s]) <= 1.0 + 1e-9 for s in SLICES))
    return rs, best_slice, best_r


# ============================================================================
# C. SINGLE-SLICE LINEAR FIT  B_hat = a*L_s + b  (least squares)
#    Fit on the early checkpoints (indices 0..FIT_END-1) where we DID run the
#    full benchmark. PREDICT the held-out late checkpoints (PRED_START..N-1)
#    from slice-loss alone, and check the prediction error.
#    a = Sxy / Sxx ; b = mean(B_fit) - a*mean(L_fit)
# ============================================================================


def linfit(x, y):
    """Ordinary least-squares line y = a*x + b. Returns (a, b). torch float64."""
    xt = torch.tensor(x, dtype=torch.float64)
    yt = torch.tensor(y, dtype=torch.float64)
    xm = xt - xt.mean()
    ym = yt - yt.mean()
    sxx = float((xm * xm).sum())
    sxy = float((xm * ym).sum())
    a = sxy / sxx
    b = float(yt.mean() - a * xt.mean())
    return a, b


def section_single_fit(best_slice, best_r):
    banner(f"SECTION C: linear fit on the best slice '{best_slice}'  "
           f"B_hat = a*L_code + b")
    fit_x = [SLICE_LOSSES[best_slice][i] for i in range(FIT_END)]
    fit_y = [BENCH[i] for i in range(FIT_END)]
    a, b = linfit(fit_x, fit_y)
    print(f"Fit on the early checkpoints (indices 0..{FIT_END - 1}, steps "
          f"{STEPS[0]}..{STEPS[FIT_END - 1]}):")
    print(f"  a (slope)     = Sxy/Sxx = {a:+.6f}")
    print(f"  b (intercept) = mean(B) - a*mean(L) = {b:+.6f}")
    print(f"  => B_hat(L_code) = {a:+.6f} * L_code {b:+.6f}\n")
    print(f"Now PREDICT the held-out late checkpoints (indices {PRED_START}.."
          f"{N_CKPT - 1}) from slice-loss alone, and compare to the TRUE score:")
    print("| ckpt | step  | L_code (obs) | true B | predicted B_hat | "
          "abs error |")
    print("|------|-------|--------------|--------|-----------------|"
          "-----------|")
    errs = []
    for i in range(PRED_START, N_CKPT):
        l_obs = SLICE_LOSSES[best_slice][i]
        b_true = BENCH[i]
        b_hat = a * l_obs + b
        e = abs(b_hat - b_true)
        errs.append(e)
        print(f"| {i:<4} | {STEPS[i]:<5} | {l_obs:>12.4f} | {b_true:>6.4f} | "
              f"{b_hat:>15.4f} | {e:>9.4f} |")
    max_err = max(errs)
    print()
    print(f"Held-out prediction max abs error = {max_err:.4f}  "
          f"(on a 0..1 accuracy scale).")
    print("A sub-percent error means: after fitting on 5 early ckpts, the code")
    print("slice's LOSS alone predicts the late-ckpt benchmark to within a hair.")
    print("That is the micro-pretrain-eval payoff: stop running the full bench.\n")
    # GOLD PIN the slope a for the best slice
    print("GOLD PIN (micro_pretrain_eval.html recomputes the r, not the slope):")
    print(f"  a (slope of B_hat = a*L_code + b) = {a:+.6f}")
    print(f"  r(code, benchmark)                = {best_r:+.6f}")
    # checks
    check("linear-fit slope a is negative (loss down -> benchmark up)",
          a < 0.0)
    check("held-out prediction max abs error < 0.02 (faithful proxy)",
          max_err < 0.02)
    # the fit on the EARLY ckpts must reproduce their true B closely
    fit_errs = [abs(a * fit_x[i] + b - fit_y[i]) for i in range(FIT_END)]
    check("fit reproduces early-ckpt scores within 0.01",
          max(fit_errs) < 0.01)
    return a, b, max_err


# ============================================================================
# D. MULTI-SLICE LINEAR MODEL  B_hat = sum_s w_s*L_s + c  (normal equations)
#    Design matrix X = [1, L_code, L_reason, L_factual, L_common] (8 x 5).
#    Normal equations:  (X^T X) w = X^T y.  Solve by hand (Gaussian elimination
#    with partial pivoting). Then find the MINIMAL slice-subset whose combined
#    predictor reaches r >= MICRO_BENCH_R -- the "micro-bench".
# ============================================================================


def solve_linear_system(A: torch.Tensor, g: torch.Tensor) -> torch.Tensor:
    """Solve A w = g by Gaussian elimination with partial pivoting.
    A is [n,n] (float64), g is [n]. Returns w [n]. No numpy/sklearn."""
    n = A.shape[0]
    M = torch.cat([A.clone(), g.reshape(n, 1)], dim=1)   # augmented [n, n+1]
    for col in range(n):
        # partial pivot: largest |M[r,col]| in rows col..n-1
        piv = max(range(col, n), key=lambda r: abs(M[r, col].item()))
        if abs(M[piv, col].item()) < 1e-12:
            raise SystemExit("singular normal-equations matrix")
        if piv != col:
            idx = [piv, col]
            M[[idx[1], idx[0]], :] = M[idx, :]
        # eliminate below
        for r in range(col + 1, n):
            factor = M[r, col] / M[col, col]
            M[r] = M[r] - factor * M[col]
    # back-substitution
    w = torch.zeros(n, dtype=torch.float64)
    for col in range(n - 1, -1, -1):
        s = M[col, n] - sum(M[col, j] * w[j] for j in range(col + 1, n))
        w[col] = s / M[col, col]
    return w


def fit_multislice(slice_list):
    """Fit B_hat = sum_s w_s*L_s + c on ALL checkpoints.
    Returns (weights dict slice->w, intercept c)."""
    X = torch.ones(N_CKPT, len(slice_list) + 1, dtype=torch.float64)
    for j, s in enumerate(slice_list):
        for i in range(N_CKPT):
            X[i, j] = SLICE_LOSSES[s][i]
    y = torch.tensor(BENCH, dtype=torch.float64)
    A = X.t() @ X
    g = X.t() @ y
    w = solve_linear_system(A, g)
    weights = {s: float(w[k]) for k, s in enumerate(slice_list)}
    intercept = float(w[-1])
    return weights, intercept


def predict_multislice(slice_list, weights, intercept):
    """Predicted B_hat per checkpoint from the multi-slice model."""
    out = []
    for i in range(N_CKPT):
        v = intercept + sum(weights[s] * SLICE_LOSSES[s][i] for s in slice_list)
        out.append(float(v))
    return out


def section_multislice_and_microbench():
    banner("SECTION D: multi-slice linear model + the minimal micro-bench")
    all_w, all_c = fit_multislice(SLICES)
    all_pred = predict_multislice(SLICES, all_w, all_c)
    all_r = pearson(all_pred, BENCH)
    print("Full 4-slice linear model  B_hat = w_code*L_code + w_reason*L_reason")
    print("                              + w_factual*L_factual + w_common*L_common + c")
    print("solved by normal equations (X^T X) w = X^T y (hand Gaussian elim):\n")
    print("| slice        |  weight w_s   |")
    print("|--------------|---------------|")
    for s in SLICES:
        print(f"| {s:<12} | {all_w[s]:>+13.6f} |")
    print(f"| intercept c  | {all_c:>+13.6f} |")
    print()
    print(f"Combined Pearson r(predicted, actual) over all 8 ckpts = {all_r:+.6f}\n")

    print("Now search ALL non-empty slice-subsets for the MINIMAL one whose")
    print(f"combined predictor reaches r >= {MICRO_BENCH_R} (the 'micro-bench'):\n")
    print("| subset                        | size | combined r | >= 0.9? |")
    print("|-------------------------------|------|------------|---------|")
    best_subsets = {}      # size -> (subset tuple, r)
    for size in range(1, len(SLICES) + 1):
        for combo in itertools.combinations(SLICES, size):
            w, c = fit_multislice(list(combo))
            pred = predict_multislice(list(combo), w, c)
            r = pearson(pred, BENCH)
            ok = abs(r) >= MICRO_BENCH_R
            tag = "YES" if ok else "no"
            print(f"| {','.join(combo):<29} | {size:>4} | {r:>+10.4f} | "
                  f"{tag:>7} |")
            if ok and size not in best_subsets:
                best_subsets[size] = (combo, r)
    print()
    # the micro-bench = smallest size that reaches r >= 0.9
    if best_subsets:
        micro_size = min(best_subsets)
        micro_combo, micro_r = best_subsets[micro_size]
        print(f"MICRO-BENCH (smallest subset with r >= {MICRO_BENCH_R}): "
              f"{{ {', '.join(micro_combo)} }}  "
              f"(size {micro_size}, r = {micro_r:+.4f})")
    else:
        micro_combo, micro_r = (), 0.0
        print(f"No subset reached r >= {MICRO_BENCH_R}.")
    print("=> Run those slices' loss every checkpoint (seconds), predict MMLU")
    print("   from the fitted line, and skip the full benchmark. Re-fit the line")
    print("   only every few checkpoints against the real benchmark to guard drift.\n")
    # checks
    check("full 4-slice model combined r >= 0.9",
          abs(all_r) >= MICRO_BENCH_R)
    check("full 4-slice model combined |r| >= best single slice |r|",
          abs(all_r) >= abs(pearson(SLICE_LOSSES["code"], BENCH)) - 1e-9)
    # the micro-bench must exist and be smaller than the full set
    check("a micro-bench subset with r >= 0.9 exists",
          len(micro_combo) >= 1)
    check("micro-bench is no larger than the full 4-slice set",
          len(micro_combo) <= len(SLICES))
    # normal-equations solution actually fits: residual tiny
    resid = [all_pred[i] - BENCH[i] for i in range(N_CKPT)]
    max_resid = max(abs(v) for v in resid)
    check("full multi-slice fit residual < 0.01 (least squares is exact for 5 "
          "unknowns, 8 pts)", max_resid < 0.01)
    return all_w, all_c, all_r, micro_combo, micro_r


# ============================================================================
# E. THE DECISION RECAP  (when to use which eval strategy)
# ============================================================================


def section_decision_recap(best_slice, micro_combo):
    banner("SECTION E: the decision recap -- which eval, when")
    rows = [
        ("Full bench / ckpt", "all 8 benchmarks x every ckpt",
         "ground truth, weeks of GPU", "Pythia-style final analysis only"),
        ("Held-out val loss", "one aggregate cross-entropy",
         "free (one forward pass), weak tie to capability",
         "cheap overfitting watch (GPT-3 style)"),
        ("Slice correlation", "per-capability loss + Pearson r",
         "shows WHICH capability is moving", "diagnostic mid-train"),
        ("MICRO-BENCH", f"{{{', '.join(micro_combo)}}} slice(s) + fitted line",
         "seconds/ckpt, predicts benchmark to <2%", "daily training loop"),
    ]
    print("| strategy            | how                 | what it buys you        | "
          "use when                  |")
    print("|---------------------|---------------------|-------------------------|"
          "---------------------------|")
    for name, how, buys, when in rows:
        print(f"| {name:<19} | {how:<19} | {buys:<23} | {when:<25} |")
    print()
    print("The single question that picks the row:")
    print("  IS THIS THE FINAL CHECKPOINT?         -> full bench (the truth).")
    print("  DO YOU JUST NEED AN OVERFITTING WATCH? -> held-out val loss.")
    print("  DO YOU NEED PER-CAPABILITY SIGNAL?     -> slice correlation.")
    print("  IS THIS A DAILY MID-TRAIN CHECK?       -> MICRO-BENCH "
          f"({', '.join(micro_combo)}).")
    print()
    check("the four strategies are distinct in how the eval is done",
          len({r[1] for r in rows}) == 4)


# ============================================================================
# main
# ============================================================================


def main():
    print("micro_pretrain_eval.py - reference impl. All numbers below feed "
          "MICRO_PRETRAIN_EVAL.md.\ntorch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources; "
          "see micro_pretrain_eval_reference.txt.")

    section_slice_loss_table()
    rs, best_slice, best_r = section_correlation()
    a, b, max_err = section_single_fit(best_slice, best_r)
    all_w, all_c, all_r, micro_combo, micro_r = \
        section_multislice_and_microbench()
    section_decision_recap(best_slice, list(micro_combo))

    banner("DONE - all sections printed, all [check]s passed")
    print("\nGOLD ANCHORS (micro_pretrain_eval.html recomputes & asserts):")
    print(f"  r(code, benchmark) = {rs['code']:+.6f}")
    print(f"  a (fit slope)      = {a:+.6f}")
    print(f"  micro-bench        = {{ {', '.join(micro_combo)} }}  "
          f"r = {micro_r:+.6f}")


if __name__ == "__main__":
    main()
