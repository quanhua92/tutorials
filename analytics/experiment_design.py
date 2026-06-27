#!/usr/bin/env python3
"""
experiment_design.py - A/B experiment design simulation (GROUND TRUTH).

Pure Python stdlib only (math, statistics). Every number printed below feeds
EXPERIMENT_DESIGN.md and is recomputed identically in experiment_design.html
(gold-checked).

Sections:
  1. Sample size & power analysis (two-proportion z-test)
  2. p-value computation (z-test for proportions)
  3. Confidence intervals for treatment effect
  4. Multiple testing correction (Bonferroni)
  5. Effect size (Cohen's h for proportions, Cohen's d for continuous)
  6. SRM (Sample Ratio Mismatch) chi-square diagnostic
  7. GOLD values pinned for experiment_design.html
"""

import math
from statistics import NormalDist

# ---------------------------------------------------------------------------
# source-of-truth constants (mirrored in experiment_design.html GOLD)
# ---------------------------------------------------------------------------
# DoorDash-style scenario: 8% baseline conversion, +0.5pp MDE.
BASELINE_RATE = 0.08          # control conversion rate
MDE_ABS = 0.005               # minimum detectable effect (absolute, +0.5pp)
ALPHA = 0.05                  # two-sided significance level
POWER = 0.80                  # statistical power (1 - beta)
DAILY_TRAFFIC_PER_ARM = 13000 # exposed users per arm per day

# z critical values (computed once, used everywhere)
ND = NormalDist()
Z_ALPHA2 = ND.inv_cdf(1.0 - ALPHA / 2.0)   # 1.95996... for alpha=0.05 two-sided
Z_BETA = ND.inv_cdf(POWER)                  # 0.84162... for power=0.80

# Observed A/B result (modest, realistic lift on the primary metric)
CTRL_N = 50000
CTRL_CONV = 5400             # 10.80%
TRT_N = 50000
TRT_CONV = 5750              # 11.50%

# Multiple-testing family: 1 primary + 4 guardrails/secondary (k=5)
# Each row: (name, role, ctrl_conv, trt_conv, n_per_arm)
METRIC_FAMILY = [
    ("conversion", "primary",   5400, 5750, 50000),
    ("click_rate", "guardrail", 8000, 8100, 50000),
    ("retention",  "secondary", 15000, 15600, 50000),
    ("checkout",   "guardrail", 5400, 5380, 50000),
    ("signup",     "secondary", 30000, 30500, 50000),
]

# SRM diagnostic: intended 50/50, observed counts
SRM_OK = (50050, 49950)       # tiny mismatch -> no SRM
SRM_BAD = (52000, 48000)      # real mismatch -> SRM fires

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt(n):
    return "{:,}".format(n)


def pct(x, y):
    return (100.0 * x / y) if y else 0.0


def ascii_bar(value, vmax, width=34):
    n = int(round(width * value / vmax)) if vmax else 0
    return "#" * max(0, min(width, n))


# ---------------------------------------------------------------------------
# Core statistical primitives
# ---------------------------------------------------------------------------
def sample_size_per_arm(p1, mde_abs, alpha=ALPHA, power=POWER):
    """Two-proportion z-test sample size (per arm, unpooled variance)."""
    za = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    zb = NormalDist().inv_cdf(power)
    p2 = p1 + mde_abs
    var_sum = p1 * (1.0 - p1) + p2 * (1.0 - p2)
    return (za + zb) ** 2 * var_sum / (p2 - p1) ** 2


def prop_ztest(c1, n1, c2, n2):
    """Two-sided two-proportion z-test. Returns (p1, p2, se, z, p_value)."""
    p1 = c1 / n1
    p2 = c2 / n2
    p_pool = (c1 + c2) / (n1 + n2)
    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n1 + 1.0 / n2))
    z = ((p2 - p1) / se) if se > 0 else 0.0
    p_value = 2.0 * (1.0 - NormalDist().cdf(abs(z)))
    return p1, p2, se, z, p_value


def diff_ci(c1, n1, c2, n2, alpha=ALPHA):
    """Wald CI for the difference of two proportions (unpooled SE)."""
    p1 = c1 / n1
    p2 = c2 / n2
    se = math.sqrt(p1 * (1.0 - p1) / n1 + p2 * (1.0 - p2) / n2)
    d = p2 - p1
    z = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    return d, d - z * se, d + z * se, se


def cohens_h(p1, p2):
    """Cohen's h effect size for two proportions: 2*arcsin(sqrt(p)) difference."""
    return 2.0 * (math.asin(math.sqrt(p2)) - math.asin(math.sqrt(p1)))


def cohens_d(m1, m2, sd):
    """Cohen's d effect size for continuous: (m1-m2)/sd (pooled sd assumed)."""
    return (m1 - m2) / sd if sd > 0 else 0.0


def chi2_gof_1dof(observed, expected):
    """Chi-square goodness-of-fit (df=1) -> (chi2, p_value)."""
    chi2 = sum((o - e) ** 2 / e for o, e in zip(observed, expected))
    # For df=1: P(X>chi2) = 2*(1 - Phi(sqrt(chi2)))
    p_value = 2.0 * (1.0 - NormalDist().cdf(math.sqrt(chi2)))
    return chi2, p_value


# ---------------------------------------------------------------------------
# SECTION 1 - Sample size & power analysis
# ---------------------------------------------------------------------------
def section_sample_size():
    banner("SECTION 1: Sample size & power analysis (two-proportion z-test)")
    p1 = BASELINE_RATE
    mde = MDE_ABS
    p2 = p1 + mde
    n = sample_size_per_arm(p1, mde)
    n_round = math.ceil(n)
    days = math.ceil(n_round / DAILY_TRAFFIC_PER_ARM)
    print("Formula (per arm):  n = (z_a/2 + z_b)^2 * [p1(1-p1) + p2(1-p2)] / (p2-p1)^2\n")
    print(f"  alpha (two-sided) = {ALPHA}    ->  z_a/2 = {Z_ALPHA2:.5f}")
    print(f"  power             = {POWER}    ->  z_b   = {Z_BETA:.5f}")
    print(f"  baseline p1       = {p1:.4f}   ({pct(int(p1*100),100) if False else p1*100:.1f}% conversion)")
    print(f"  MDE (absolute)    = {mde:.4f}   (+{(mde*100):.2f} pp)")
    print(f"  target  p2        = {p2:.4f}   ({p2*100:.2f}% conversion)")
    print()
    var_sum = p1 * (1.0 - p1) + p2 * (1.0 - p2)
    print(f"  z_a/2 + z_b       = {Z_ALPHA2 + Z_BETA:.5f}   (squared = {(Z_ALPHA2 + Z_BETA)**2:.4f})")
    print(f"  p1(1-p1)+p2(1-p2) = {var_sum:.6f}")
    print(f"  (p2-p1)^2         = {(p2 - p1)**2:.8f}")
    print()
    print(f"=> n per arm       = {n:,.2f}   (round up to {fmt(n_round)})")
    print(f"=> total (both)    = {fmt(2 * n_round)}")
    print(f"=> duration        = {n_round:,} / {DAILY_TRAFFIC_PER_ARM:,} per day = {days} days per arm")
    print()
    print("=> At 8% baseline, a +0.5pp MDE needs ~47.5k users PER ARM at 80% power.")
    print("   If duration exceeds the business window, reach for CUPED / stratification")
    print("   BEFORE lowering power or raising alpha. Never weaken the test for speed.")
    print()
    print("[check] z_a/2 == 1.95996? " + ("OK" if round(Z_ALPHA2, 5) == 1.95996 else "FAIL"))
    print("[check] z_b == 0.84162? " + ("OK" if round(Z_BETA, 5) == 0.84162 else "FAIL"))
    print("[check] n_per_arm rounds to 47,525? " + ("OK" if n_round == 47525 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - p-value computation (z-test for proportions)
# ---------------------------------------------------------------------------
def section_pvalue():
    banner("SECTION 2: p-value computation (two-sided two-proportion z-test)")
    p1, p2, se, z, pval = prop_ztest(CTRL_CONV, CTRL_N, TRT_CONV, TRT_N)
    rel_lift = (p2 / p1 - 1.0) * 100.0
    print(f"Observed result:  control {CTRL_CONV:,}/{CTRL_N:,}   treatment {TRT_CONV:,}/{TRT_N:,}\n")
    print(f"  p_control    = {CTRL_CONV}/{CTRL_N} = {p1:.5f}  ({pct(CTRL_CONV, CTRL_N):.2f}%)")
    print(f"  p_treatment  = {TRT_CONV}/{TRT_N} = {p2:.5f}  ({pct(TRT_CONV, TRT_N):.2f}%)")
    print(f"  pooled p     = {(CTRL_CONV + TRT_CONV) / (CTRL_N + TRT_N):.5f}")
    print(f"  SE (pooled)  = {se:.6f}")
    print()
    print(f"  z = (p2 - p1) / SE = ({p2:.5f} - {p1:.5f}) / {se:.6f} = {z:.4f}")
    print(f"  p-value (two-sided) = 2 * (1 - Phi(|z|)) = {pval:.6f}")
    print()
    verdict = "REJECT H0 (significant)" if pval < ALPHA else "FAIL TO REJECT (not significant)"
    print(f"  vs alpha = {ALPHA}:  {pval:.6f} < {ALPHA}  ->  {verdict}")
    print(f"  relative lift = {p2/p1*100 - 100:+.2f}%   absolute lift = {(p2-p1)*100:+.2f} pp")
    print()
    print("=> A z of ~3.5 (p ~ 0.0004) is strong evidence the treatment moved the")
    print("   metric. But significance != business value: a +0.7pp lift on a 50k/arm")
    print("   sample is detectable; whether it clears the ship-bar MDE is a separate call.")
    print()
    print("[check] z == 3.5164? " + ("OK" if round(z, 4) == 3.5164 else "FAIL"))
    print("[check] p-value == 0.000437? " + ("OK" if round(pval, 6) == 0.000437 else "FAIL"))
    print("[check] relative lift == 6.48%? " + ("OK" if round(rel_lift, 2) == 6.48 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Confidence intervals for treatment effect
# ---------------------------------------------------------------------------
def section_ci():
    banner("SECTION 3: Confidence intervals for treatment effect (Wald)")
    d, lo, hi, se = diff_ci(CTRL_CONV, CTRL_N, TRT_CONV, TRT_N)
    lo_pp, hi_pp, d_pp = lo * 100, hi * 100, d * 100
    print(f"Wald 95% CI for the difference p_treatment - p_control (unpooled SE):\n")
    print(f"  point estimate (p2 - p1) = {d:.5f}  ({d_pp:+.3f} pp)")
    print(f"  SE (unpooled)            = {se:.6f}")
    print(f"  margin (z * SE)          = {Z_ALPHA2 * se:.6f}")
    print(f"  95% CI                   = [{lo:.5f}, {hi:.5f}]")
    print(f"                           = [{lo_pp:+.3f} pp, {hi_pp:+.3f} pp]")
    print()
    crosses_zero = (lo < 0 < hi) or (hi < 0 < lo)
    contains_mde = lo >= MDE_ABS
    print(f"  CI crosses zero?         {'YES (not significant)' if crosses_zero else 'NO (significant)'}")
    print(f"  CI lower bound >= MDE?   {'YES (practically significant)' if contains_mde else 'NO (below ship bar)'}")
    print()
    # bar visualization of the CI
    span = hi - lo
    anchor = min(0.0, lo)
    norm_lo = (lo - anchor) / (hi - anchor) if hi != anchor else 0
    norm_hi = (hi - anchor) / (hi - anchor) if hi != anchor else 0
    print(f"  CI band (pp):  {'0':>7}{'point':>10}{'upper':>10}")
    bar_zero = int(round(34 * (0.0 - anchor) / (hi - anchor))) if hi != anchor else 0
    bar_pt = int(round(34 * (d - anchor) / (hi - anchor))) if hi != anchor else 0
    print(f"  {'[' + format(lo_pp, '+.3f') + ', ' + format(hi_pp, '+.3f') + '] pp':<28}")
    line = [" "] * 36
    for i in range(36):
        if bar_zero <= i <= bar_pt:
            line[i] = "#"
    print("  " + "".join(line))
    print()
    print("=> The CI [0.30, 1.10] pp excludes zero (confirms Section 2 significance),")
    print("   but its LOWER bound (0.30 pp) is below the +0.5pp MDE ship bar. The effect")
    print("   is statistically real but we are NOT 95% sure it clears the business bar.")
    print()
    print("[check] CI lower == 0.003099? " + ("OK" if round(lo, 6) == 0.003099 else "FAIL"))
    print("[check] CI upper == 0.010901? " + ("OK" if round(hi, 6) == 0.010901 else "FAIL"))
    print("[check] CI excludes zero? " + ("OK" if lo > 0 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Multiple testing correction (Bonferroni)
# ---------------------------------------------------------------------------
def section_bonferroni():
    banner("SECTION 4: Multiple testing correction (Bonferroni)")
    k = len(METRIC_FAMILY)
    alpha_bonf = ALPHA / k
    print(f"Family of k={k} tests (1 primary + 4 guardrails/secondary).\n")
    print(f"  raw alpha          = {ALPHA}")
    print(f"  Bonferroni alpha   = alpha / k = {ALPHA}/{k} = {alpha_bonf:.4f}")
    print()
    print(f"  {'#':<3}{'metric':<13}{'role':<11}{'p_ctrl':>9}{'p_trt':>9}{'p-value':>11}"
          f"{'@0.05':>8}{'@Bonf':>8}")
    rows = []
    for i, (name, role, c1, c2, n) in enumerate(METRIC_FAMILY, 1):
        p1 = c1 / n
        p2 = c2 / n
        _p1, _p2, _se, _z, pval = prop_ztest(c1, n, c2, n)
        sig_raw = "YES" if pval < ALPHA else "no"
        sig_bonf = "YES" if pval < alpha_bonf else "no"
        rows.append((name, role, p1, p2, pval, sig_raw, sig_bonf))
        print(f"  {i:<3}{name:<13}{role:<11}{p1*100:>8.2f}%{p2*100:>8.2f}%"
              f"{pval:>11.5f}{sig_raw:>8}{sig_bonf:>8}")
    print()
    n_raw = sum(1 for r in rows if r[5] == "YES")
    n_bonf = sum(1 for r in rows if r[6] == "YES")
    expected_fp = k * ALPHA
    print(f"  significant @ raw 0.05:  {n_raw}/{k}")
    print(f"  significant @ Bonferroni: {n_bonf}/{k}")
    print(f"  expected false positives @ 0.05 without correction: k*alpha = {expected_fp:.2f}")
    print()
    print("=> Without correction, running k=5 tests at alpha=0.05 inflates the family-wise")
    print(f"   error rate to ~{1 - (1 - ALPHA) ** k:.2f}; expect ~{expected_fp:.0f} false positive by construction.")
    print("   Bonferroni (alpha/k) controls the family-wise error for primary + guardrails.")
    print("   Use Benjamini-Hochberg FDR <= 0.10 for secondary metric panels instead.")
    print()
    primary_row = rows[0]
    print("[check] primary p-value == 0.000437? " +
          ("OK" if round(primary_row[4], 6) == 0.000437 else "FAIL"))
    print("[check] Bonferroni alpha == 0.01? " +
          ("OK" if round(alpha_bonf, 4) == 0.01 else "FAIL"))
    print("[check] exactly 3 metrics pass Bonferroni? " +
          ("OK" if n_bonf == 3 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Effect size (Cohen's h / Cohen's d)
# ---------------------------------------------------------------------------
def section_effect_size():
    banner("SECTION 5: Effect size (Cohen's h for proportions, Cohen's d for continuous)")
    p1 = CTRL_CONV / CTRL_N
    p2 = TRT_CONV / TRT_N
    h = cohens_h(p1, p2)
    print("Statistical significance depends on n; effect size does NOT. Report both.\n")
    print("Cohen's h for two proportions  h = 2*[arcsin(sqrt(p2)) - arcsin(sqrt(p1))]:")
    print(f"  arcsin(sqrt({p1:.4f})) = {math.asin(math.sqrt(p1)):.5f}")
    print(f"  arcsin(sqrt({p2:.4f})) = {math.asin(math.sqrt(p2)):.5f}")
    print(f"  h = {h:.4f}")
    h_band = ("negligible (<0.20)" if h < 0.20 else
              "small (0.20-0.50)" if h < 0.50 else
              "medium (0.50-0.80)" if h < 0.80 else "large (>=0.80)")
    print(f"  interpretation: {h_band}")
    print()
    print("  Cohen's h bands:  negligible <0.20 | small 0.20-0.50 | medium 0.50-0.80 | large >=0.80")
    print()
    # Cohen's d worked example (continuous metric, e.g. revenue per user)
    m_ctrl, m_trt, sd_pooled = 4.20, 4.35, 3.10
    d = cohens_d(m_trt, m_ctrl, sd_pooled)
    print(f"Cohen's d worked example (revenue/user, $):")
    print(f"  mean_control = ${m_ctrl:.2f}   mean_treatment = ${m_trt:.2f}   sd_pooled = ${sd_pooled:.2f}")
    print(f"  d = (m_trt - m_ctrl) / sd = ({m_trt:.2f} - {m_ctrl:.2f}) / {sd_pooled:.2f} = {d:.4f}")
    d_band = ("negligible (<0.20)" if d < 0.20 else
              "small (0.20-0.50)" if d < 0.50 else
              "medium (0.50-0.80)" if d < 0.80 else "large (>=0.80)")
    print(f"  interpretation: {d_band}")
    print()
    print("=> A p-value can be tiny on a huge sample yet describe a useless effect.")
    print("   Effect size answers 'does it MATTER?', p-value answers 'is it REAL?'.")
    print("   Always pair them -- especially when arguing for a rollout decision.")
    print()
    print("[check] Cohen's h == 0.0222? " + ("OK" if round(h, 4) == 0.0222 else "FAIL"))
    print("[check] Cohen's d == 0.0484? " + ("OK" if round(d, 4) == 0.0484 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - SRM (Sample Ratio Mismatch) chi-square diagnostic
# ---------------------------------------------------------------------------
def section_srm():
    banner("SECTION 6: SRM (Sample Ratio Mismatch) chi-square diagnostic")
    print("Chi-square goodness-of-fit on observed vs expected assignment counts (df=1).\n")
    expected = (CTRL_N, TRT_N)
    print("  Case A (healthy):  observed " + str(SRM_OK) + "  expected (50000, 50000)")
    chi_ok, p_ok = chi2_gof_1dof(SRM_OK, expected)
    print(f"    chi2 = {chi_ok:.4f}   p-value = {p_ok:.4f}   ->  "
          f"{'SRM OK (keep running)' if p_ok >= 0.001 else 'SRM FIRES (halt)'}")
    print()
    print("  Case B (mismatch): observed " + str(SRM_BAD) + "  expected (50000, 50000)")
    chi_bad, p_bad = chi2_gof_1dof(SRM_BAD, expected)
    print(f"    chi2 = {chi_bad:.4f}   p-value = {p_bad:.8f}   ->  "
          f"{'SRM OK (keep running)' if p_bad >= 0.001 else 'SRM FIRES (halt)'}")
    print()
    print("=> Case B fires SRM at p < 0.001. HALT, do NOT rebalance. Trace the logging")
    print("   chain (bot filter, latency dropout, salt collision, crash on first load),")
    print("   fix the bug, then RESTART enrollment. Every metric on a mismatched experiment")
    print("   is biased -- you cannot trust a z-test if the assignment itself is broken.")
    print()
    print("[check] healthy chi2 == 0.1000? " + ("OK" if round(chi_ok, 4) == 0.1 else "FAIL"))
    print("[check] healthy p-value >= 0.001 (no SRM)? " + ("OK" if p_ok >= 0.001 else "FAIL"))
    print("[check] mismatch chi2 == 160.0000? " + ("OK" if round(chi_bad, 4) == 160.0 else "FAIL"))
    print("[check] mismatch p-value < 0.001 (SRM fires)? " + ("OK" if p_bad < 0.001 else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for experiment_design.html
# ---------------------------------------------------------------------------
def section_gold():
    banner("SECTION 7: GOLD values (pinned for experiment_design.html)")
    n = sample_size_per_arm(BASELINE_RATE, MDE_ABS)
    p1, p2, se, z, pval = prop_ztest(CTRL_CONV, CTRL_N, TRT_CONV, TRT_N)
    d, lo, hi, _ci_se = diff_ci(CTRL_CONV, CTRL_N, TRT_CONV, TRT_N)
    h = cohens_h(p1, p2)
    dd = cohens_d(4.35, 4.20, 3.10)
    k = len(METRIC_FAMILY)
    alpha_bonf = ALPHA / k
    chi_ok, p_ok = chi2_gof_1dof(SRM_OK, (CTRL_N, TRT_N))
    chi_bad, p_bad = chi2_gof_1dof(SRM_BAD, (CTRL_N, TRT_N))
    gold = [
        ("z_alpha2",          f"{Z_ALPHA2:.5f}",       "1.95996"),
        ("z_beta",            f"{Z_BETA:.5f}",         "0.84162"),
        ("n_per_arm",         f"{n:.2f}",              "47524.97"),
        ("n_per_arm_rounded", f"{math.ceil(n)}",       "47525"),
        ("z_stat_primary",    f"{z:.4f}",              "3.5164"),
        ("pvalue_primary",    f"{pval:.6f}",           "0.000437"),
        ("rel_lift_pct",      f"{(p2/p1-1)*100:.2f}",  "6.48"),
        ("abs_lift_pp",       f"{(p2-p1)*100:.3f}",    "0.700"),
        ("ci_lower",          f"{lo:.6f}",             "0.003099"),
        ("ci_upper",          f"{hi:.6f}",             "0.010901"),
        ("cohens_h",          f"{h:.4f}",              "0.0222"),
        ("cohens_d",          f"{dd:.4f}",             "0.0484"),
        ("bonferroni_alpha",  f"{alpha_bonf:.4f}",     "0.0100"),
        ("srm_ok_chi2",       f"{chi_ok:.4f}",         "0.1000"),
        ("srm_ok_pvalue",     f"{p_ok:.4f}",           "0.7518"),
        ("srm_bad_chi2",      f"{chi_bad:.4f}",        "160.0000"),
        ("srm_bad_pvalue",    f"{p_bad:.8f}",          "0.00000000"),
    ]
    print(f"  {'check':<22} {'py recompute':>16} {'GOLD':>12} {'match':>7}")
    all_ok = True
    for label, got, want in gold:
        ok = got == want
        if not ok:
            all_ok = False
        print(f"  {label:<22} {got:>16} {want:>12} {'OK' if ok else 'FAIL':>7}")
    print()
    print("[check] ALL GOLD values reproduce from the experiment-design formulas? " +
          ("OK" if all_ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# experiment_design.py - A/B experiment design simulation")
    print("# Pure Python stdlib only (math, statistics). Numbers below feed")
    print("# EXPERIMENT_DESIGN.md and experiment_design.html (gold-checked).")
    section_sample_size()
    section_pvalue()
    section_ci()
    section_bonferroni()
    section_effect_size()
    section_srm()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
