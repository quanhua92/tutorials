#!/usr/bin/env python3
"""
customer_ltv.py - Customer Lifetime Value system design (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds CUSTOMER_LTV.md
and is recomputed identically in customer_ltv.html (gold-checked).

Core model: SURVIVAL-BASED CLV + churn logistic + segmentation.
  Cohort retention : Weibull survival S(t) = exp(-(t/lam)^k)  -> D1/D7/D30/D90
  Churn prediction : logistic regression trained by batch gradient descent
  CLV (historical) : ARPU x gm x E[lifespan]            (undiscounted survival area)
  CLV (predictive) : sum ARPU x gm x S(30m)/(1+r)^m     (discounted NPV)
  Discount / NPV   : annual rate -> monthly compound, 36-month horizon
  Segmentation     : Whale / Dolphin / Minnow by CLV percentile + concentration

Sections:
  1. Cohort retention curves (Weibull survival, D1/D7/D30/D90)
  2. Churn prediction (logistic regression on customer features)
  3. CLV -- historical / aggregate (ARPU x gm x expected lifespan)
  4. CLV -- predictive discounted NPV (retention-weighted, discounted)
  5. Discount-rate / NPV sensitivity (NPV vs annual rate)
  6. Customer segmentation by LTV tier (concentration, LTV:CAC)
  7. Scale estimation (50M customers, batch + realtime, storage)
  8. GOLD values pinned for customer_ltv.html
"""

import math

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt_money(n):
    return "$%.2f" % n


def fmt_int(n):
    return "{:,}".format(n)


def sigmoid(z):
    """Numerically stable logistic sigmoid (matches JS Math.exp exactly)."""
    if z >= 0.0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


# ---------------------------------------------------------------------------
# model parameters -- deterministic, reproducible verbatim in JS
# ---------------------------------------------------------------------------

ANNUAL_DISCOUNT = 0.10                          # 10% annual discount rate
R_MONTHLY = (1.0 + ANNUAL_DISCOUNT) ** (1.0 / 12.0) - 1.0   # monthly compound
CLV_HORIZON_MONTHS = 36                        # 3-year CLV window
LIFESPAN_SUM_MONTHS = 120                      # discrete E[lifespan] cutoff (10y)
CAC = 25.0                                     # blended acquisition cost
DAYS = [1, 7, 30, 90]                          # retention checkpoints

# Cohort retention params: lam=Weibull scale (days), k=Weibull shape.
#   k<1 -> hazard decreasing over time (customers who stay get stickier).
COHORTS = {
    "premium":  {"lam": 200.0, "k": 0.60, "arpu": 40.0, "gm": 0.75, "n": 50000},
    "standard": {"lam": 60.0,  "k": 0.70, "arpu": 20.0, "gm": 0.65, "n": 200000},
    "trial":    {"lam": 20.0,  "k": 0.80, "arpu": 8.0,  "gm": 0.50, "n": 750000},
}

# Archetypes for segmentation: (cohort, arpu_mult, count, name).
# Counts sum to 1,000,000 and cohort totals match COHORTS["n"].
ARCHETYPES = [
    ("premium",  1.5,   2000, "premium_whale"),
    ("premium",  1.0,  18000, "premium_core"),
    ("premium",  0.6,  30000, "premium_minnow"),
    ("standard", 1.4,  20000, "standard_high"),
    ("standard", 1.0, 100000, "standard_core"),
    ("standard", 0.5,  80000, "standard_minnow"),
    ("trial",    1.5,  50000, "trial_high"),
    ("trial",    0.9, 200000, "trial_core"),
    ("trial",    0.4, 250000, "trial_minnow"),
    ("trial",    0.2, 250000, "trial_churnfast"),
]


def survival(lam, k, day):
    """Weibull survival: fraction still active at day t. S(0)=1."""
    return math.exp(-((day / lam) ** k))


def discounted_survival_sum(lam, k, horizon, r_monthly):
    """sum_{m=1}^{horizon} S(30m) / (1+r)^m  -- retention x discount factor."""
    total = 0.0
    for m in range(1, horizon + 1):
        total += survival(lam, k, 30.0 * m) / ((1.0 + r_monthly) ** m)
    return total


def expected_lifespan_months(lam, k, max_months=LIFESPAN_SUM_MONTHS):
    """Discrete area under the survival curve = expected tenure (months)."""
    total = 0.0
    for m in range(1, max_months + 1):
        total += survival(lam, k, 30.0 * m)
    return total


def historical_clv(arpu, gm, lam, k):
    """Undiscounted cohort-average CLV = ARPU x gm x E[lifespan]."""
    return arpu * gm * expected_lifespan_months(lam, k)


def predictive_clv(arpu, gm, lam, k, r_monthly=R_MONTHLY, horizon=CLV_HORIZON_MONTHS):
    """Discounted NPV of future cash flows weighted by survival."""
    return arpu * gm * discounted_survival_sum(lam, k, horizon, r_monthly)


# ===========================================================================
# SECTION 1 - Cohort retention curves
# ===========================================================================

def section_retention():
    banner("SECTION 1: Cohort retention curves (Weibull survival)")
    print("Each cohort's retention is a SURVIVAL CURVE: the fraction still active at")
    print("day t. We use the Weibull S(t) = exp(-(t/lam)^k) -- the standard survival")
    print("model (same family as Cox PH / BG-NBD dropout). k<1 = hazard decreasing")
    print("(customers who stay get stickier); a higher lam = slower decay.")
    print()
    print("  %-9s %8s %6s %8s %6s %10s" % ("cohort", "lam", "k", "arpu", "gm", "size"))
    for name, c in COHORTS.items():
        print("  %-9s %8.1f %6.2f %8.1f %6.2f %10s" %
              (name, c["lam"], c["k"], c["arpu"], c["gm"], fmt_int(c["n"])))
    print()
    print("  retention S(t) at D1 / D7 / D30 / D90:")
    print("  %-9s %8s %8s %8s %8s" % ("cohort", "D1", "D7", "D30", "D90"))
    results = {}
    for name, c in COHORTS.items():
        row = {d: survival(c["lam"], c["k"], float(d)) for d in DAYS}
        results[name] = row
        print("  %-9s %8.4f %8.4f %8.4f %8.4f" %
              (name, row[1], row[7], row[30], row[90]))
    print()
    print("  Closed-form Weibull mean tenure E[T]=lam*Gamma(1+1/k) vs discrete")
    print("  120-month survival sum (theory vs the number we actually use):")
    for name, c in COHORTS.items():
        cf_months = c["lam"] * math.gamma(1.0 + 1.0 / c["k"]) / 30.0
        disc = expected_lifespan_months(c["lam"], c["k"])
        print("  %-9s closed-form %7.2f mo   discrete %7.2f mo" % (name, cf_months, disc))
    print()
    print("  The curve is what makes CLV work: retention at day t is the probability")
    print("  the customer is still paying in month t -- the weight on each future cash")
    print("  flow. A flatter curve (premium) -> a longer, richer cash-flow stream.")
    print()

    ok = True
    for name, row in results.items():
        if not (row[1] > row[7] > row[30] > row[90]):
            ok = False
    if not (results["premium"][90] > results["standard"][90] > results["trial"][90]):
        ok = False
    print("[check] retention monotonic D1>D7>D30>D90 and premium>standard>trial at D90? " +
          ("OK" if ok else "FAIL"))
    return results


# ===========================================================================
# SECTION 2 - Churn prediction (logistic regression)
# ===========================================================================

# 6 features per customer (raw, pre-normalization):
#   [tenure_months, freq_per_month, recency_days, support_tickets, num_products, is_premium]
# Label: 0 = active, 1 = churned within next 90 days.
CHURN_FEAT = ["tenure", "freq", "recency", "tickets", "products", "premium"]
CHURN_MAX = [36.0, 8.0, 180.0, 5.0, 5.0, 1.0]

CHURN_TRAIN = [
    # active (label 0): long tenure, high freq, low recency
    (24, 4, 5,   0, 3, 1),
    (18, 3, 12,  1, 2, 0),
    (30, 6, 3,   0, 4, 1),
    (12, 2, 20,  2, 1, 0),
    (36, 5, 8,   1, 5, 1),
    (20, 3, 15,  0, 2, 0),
    # churned (label 1): short tenure, low freq, high recency
    (2,  1, 60,  3, 1, 0),
    (4,  1, 90,  4, 1, 0),
    (3,  2, 75,  2, 1, 0),
    (8,  1, 120, 3, 1, 0),
    (6,  1, 45,  5, 1, 0),
    (1,  1, 30,  1, 1, 0),
]
CHURN_LABELS = [0] * 6 + [1] * 6

LR_LR = 0.5
LR_EPOCHS = 2000


def normalize_churn(row):
    return [min(1.0, row[i] / CHURN_MAX[i]) for i in range(len(row))]


def train_churn_lr(data, labels):
    """Batch gradient descent on normalized features. Deterministic."""
    X = [normalize_churn(r) for r in data]
    n = len(X)
    d = len(X[0])
    w = [0.0] * d
    b = 0.0
    for _ in range(LR_EPOCHS):
        gw = [0.0] * d
        gb = 0.0
        for i in range(n):
            z = b
            for j in range(d):
                z += w[j] * X[i][j]
            p = sigmoid(z)
            err = p - labels[i]
            for j in range(d):
                gw[j] += err * X[i][j]
            gb += err
        for j in range(d):
            w[j] -= LR_LR * gw[j] / n
        b -= LR_LR * gb / n
    return w, b


def churn_score(w, b, row):
    z = b
    xn = normalize_churn(row)
    for j in range(len(w)):
        z += w[j] * xn[j]
    return sigmoid(z)


def section_churn():
    banner("SECTION 2: Churn prediction (logistic regression)")
    print("CHURN SCORING != RETENTION prediction. Churn scoring is a RELATIVE RANK")
    print("(who is most at risk -> save campaign); retention is a CALIBRATED P(active")
    print("in T days). Here we train a logistic churn scorer on engineered features")
    print("-- pure stdlib batch gradient descent. Production uses a GBDT.")
    print("  z = b + sum(w_j * x_j);  P(churn) = sigmoid(z)")
    print()
    print("  normalization divisor per feature (x_j = raw / MAX, capped 1.0):")
    for i in range(len(CHURN_FEAT)):
        print("    %-9s div = %6.1f" % (CHURN_FEAT[i], CHURN_MAX[i]))
    print("  train set: %d active, %d churned  (lr=%.2f, epochs=%d)" %
          (6, 6, LR_LR, LR_EPOCHS))
    print()

    w, b = train_churn_lr(CHURN_TRAIN, CHURN_LABELS)
    print("  learned weights (per normalized feature):")
    for j in range(len(w)):
        print("    %-9s %+8.4f" % (CHURN_FEAT[j], w[j]))
    print("    %-9s %+8.4f" % ("(bias)", b))
    print("  Signs match intuition: tenure/freq/products/premium negative (retentive),")
    print("  recency/tickets positive (churny).")
    print()

    print("  scores on training set (should separate the two classes):")
    print("    %-5s %7s %6s %8s" % ("c#", "tenure", "label", "P(churn)"))
    for i, row in enumerate(CHURN_TRAIN):
        p = churn_score(w, b, row)
        print("    c%-4d %7d %6d %8.4f" % (i + 1, row[0], CHURN_LABELS[i], p))
    print()

    p_active = churn_score(w, b, CHURN_TRAIN[4])    # long-tenure premium
    p_churn = churn_score(w, b, CHURN_TRAIN[9])     # short-tenure high-recency
    ok = (p_active < 0.15 and p_churn > 0.85)
    print("[check] active cust P<0.15 (%.4f) and churner P>0.85 (%.4f)? " %
          (p_active, p_churn) + ("OK" if ok else "FAIL"))
    return w, b


# ===========================================================================
# SECTION 3 - CLV historical / aggregate
# ===========================================================================

def section_historical_clv():
    banner("SECTION 3: CLV -- historical / aggregate (undiscounted)")
    print("The textbook CLV: average revenue per period x gross margin x expected")
    print("customer lifespan. Expected lifespan = area under the survival curve,")
    print("E[lifespan] = sum_{m>=1} S(30m) months. This is an UNDISCOUNTED cohort")
    print("average -- the back-of-envelope number, fine for segmentation, NOT for")
    print("bidding (no time-value of money, no horizon cap).")
    print()
    print("  %-9s %8s %6s %11s %13s" % ("cohort", "arpu", "gm", "E[life] mo", "hist CLV"))
    hist = {}
    for name, c in COHORTS.items():
        life = expected_lifespan_months(c["lam"], c["k"])
        clv = c["arpu"] * c["gm"] * life
        hist[name] = clv
        print("  %-9s %8.1f %6.2f %11.2f %13s" %
              (name, c["arpu"], c["gm"], life, fmt_money(clv)))
    print()
    ok = (hist["premium"] > hist["standard"] > hist["trial"])
    print("[check] historical CLV premium>standard>trial? " + ("OK" if ok else "FAIL"))
    return hist


# ===========================================================================
# SECTION 4 - CLV predictive discounted NPV
# ===========================================================================

def section_predictive_clv(hist):
    banner("SECTION 4: CLV -- predictive discounted NPV")
    print("The PRODUCTION number: present value of future cash flows, weighted by")
    print("per-period survival and discounted. This is what feeds acquisition bidding")
    print("and credit decisions -- a dollar in month 24 is worth less than a dollar")
    print("today, and only if the customer is still active.")
    print("  CLV = sum_{m=1}^{H} ARPU x gm x S(30m) / (1+r)^m")
    print("  annual %.0f%% -> monthly r = %.6f, horizon H = %d months" %
          (ANNUAL_DISCOUNT * 100, R_MONTHLY, CLV_HORIZON_MONTHS))
    print()
    print("  %-9s %12s %12s %10s" % ("cohort", "historical", "predictive", "gap"))
    pred = {}
    for name, c in COHORTS.items():
        pc = predictive_clv(c["arpu"], c["gm"], c["lam"], c["k"])
        pred[name] = pc
        gap = (1.0 - pc / hist[name]) * 100.0
        print("  %-9s %12s %12s %9.1f%%" %
              (name, fmt_money(hist[name]), fmt_money(pc), gap))
    print()
    print("  Predictive < historical because (a) horizon caps at %d mo and (b)" % CLV_HORIZON_MONTHS)
    print("  discounting shrinks far-future cash flows. The gap widens for sticky")
    print("  cohorts (premium) whose value lives further out in time.")
    print()
    ok = (pred["premium"] < hist["premium"] and pred["standard"] < hist["standard"]
          and pred["trial"] < hist["trial"]
          and pred["premium"] > pred["standard"] > pred["trial"])
    print("[check] predictive<historical all cohorts, premium>standard>trial? " +
          ("OK" if ok else "FAIL"))
    return pred


# ===========================================================================
# SECTION 5 - Discount-rate / NPV sensitivity
# ===========================================================================

def section_discount_sensitivity():
    banner("SECTION 5: Discount-rate / NPV sensitivity")
    print("How much is future money worth TODAY? At r=0 the NPV equals the undiscounted")
    print("sum. At r=20% a dollar in 36 months is worth 1/(1.20)^3 = $0.58. CLV is")
    print("highly sensitive to r for sticky cohorts -- the discount rate is a LEVER,")
    print("not a constant: overestimating it undervalues loyal customers and underbids.")
    print()
    rates = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]
    c = COHORTS["standard"]
    print("  standard cohort CLV vs annual discount rate (H=%d mo):" % CLV_HORIZON_MONTHS)
    print("  %8s %12s" % ("rate", "CLV"))
    sens = {}
    for r in rates:
        rm = (1.0 + r) ** (1.0 / 12.0) - 1.0
        v = c["arpu"] * c["gm"] * discounted_survival_sum(c["lam"], c["k"], CLV_HORIZON_MONTHS, rm)
        sens[r] = v
        print("  %7.0f%% %12s" % (r * 100, fmt_money(v)))
    print()
    r0 = c["arpu"] * c["gm"] * discounted_survival_sum(c["lam"], c["k"], CLV_HORIZON_MONTHS, 0.0)
    undisc = c["arpu"] * c["gm"] * expected_lifespan_months(c["lam"], c["k"])
    print("  At r=0%% the %d-mo NPV = %s; the 120-mo E[lifespan] CLV = %s." %
          (CLV_HORIZON_MONTHS, fmt_money(r0), fmt_money(undisc)))
    print("  The gap is the value beyond month %d that the horizon truncates -- the" % CLV_HORIZON_MONTHS)
    print("  reason a 36-mo CLV underestimates a 5-year CLV for loyal cohorts.")
    print()
    ok = (sens[0.0] > sens[0.10] > sens[0.20] > sens[0.30] and r0 < undisc)
    print("[check] CLV falls as discount rate rises, r=0 finite-horizon < E[lifespan]? " +
          ("OK" if ok else "FAIL"))
    return sens


# ===========================================================================
# SECTION 6 - Customer segmentation by LTV tier
# ===========================================================================

def section_segmentation(pred):
    banner("SECTION 6: Customer segmentation by LTV tier")
    print("Score every customer's predictive CLV, then split into tiers by LTV:CAC")
    print("ratio -- the unit of account for acquisition bidding. Whales (LTV:CAC>=3)")
    print("are worth bidding aggressively on; dolphins (>=1) are profitable to defend;")
    print("minnows (<1) lose money to acquire. Tying tiers to CAC (not raw percentile)")
    print("avoids atomic-block straddling and maps straight to bid decisions.")
    print()

    base_clv = {name: pred[name] for name in COHORTS}
    WHALE_CLV = 3.0 * CAC        # LTV:CAC >= 3 -> bid aggressively
    DOLPHIN_CLV = CAC            # LTV:CAC >= 1 -> profitable, defend

    rows = []
    for cohort, mult, count, aname in ARCHETYPES:
        clv = base_clv[cohort] * mult
        rows.append([aname, cohort, mult, count, clv])

    total_n = sum(r[3] for r in rows)
    total_ltv = sum(r[3] * r[4] for r in rows)

    print("  %-16s %9s %10s %9s %11s" % ("archetype", "count", "per-cust", "LTV:CAC", "tier"))
    for r in sorted(rows, key=lambda x: -x[4]):
        aname, cohort, mult, count, clv = r
        if clv >= WHALE_CLV:
            tier = "Whale"
        elif clv >= DOLPHIN_CLV:
            tier = "Dolphin"
        else:
            tier = "Minnow"
        r.append(tier)
        print("  %-16s %9s %10s %9.2f %11s" %
              (aname, fmt_int(count), fmt_money(clv), clv / CAC, tier))
    print()

    tiers = {"Whale": [0, 0.0], "Dolphin": [0, 0.0], "Minnow": [0, 0.0]}
    for r in rows:
        aname, cohort, mult, count, clv, tier = r
        tiers[tier][0] += count
        tiers[tier][1] += count * clv

    print("  %-9s %9s %8s %12s %8s %11s %10s" %
          ("tier", "customers", "%cust", "total LTV", "%LTV", "avg CLV", "LTV:CAC"))
    summary = {}
    for tier in ("Whale", "Dolphin", "Minnow"):
        cnt, ltv = tiers[tier]
        avg = ltv / cnt if cnt else 0.0
        summary[tier] = (cnt, ltv, avg)
        print("  %-9s %9s %7.1f%% %12s %7.1f%% %11s %9.2f" %
              (tier, fmt_int(cnt), cnt / total_n * 100, fmt_money(ltv),
               ltv / total_ltv * 100, fmt_money(avg), avg / CAC))
    print("  %-9s %9s %8s %12s %8s" %
          ("TOTAL", fmt_int(total_n), "100.0%", fmt_money(total_ltv), "100.0%"))
    print()

    w_cnt, w_ltv, w_avg = summary["Whale"]
    d_avg = summary["Dolphin"][2]
    m_avg = summary["Minnow"][2]
    whale_ltv_share = w_ltv / total_ltv
    whale_cust_share = w_cnt / total_n
    print("  Whales are %.1f%% of customers but hold %.1f%% of total LTV -> a %.1fx" %
          (whale_cust_share * 100, whale_ltv_share * 100,
           whale_ltv_share / whale_cust_share))
    print("  concentration. Bid up to 3x CAC on whales, defend dolphins, and do NOT")
    print("  spend acquiring minnows (LTV:CAC < 1 -- every dollar acquired is lost).")
    print()

    ok = (w_avg > d_avg > m_avg and
          w_avg / CAC >= 3.0 and m_avg / CAC < 1.0 and
          whale_ltv_share > whale_cust_share and total_n == 1_000_000)
    print("[check] avg CLV whale>dolphin>minnow, whale LTV:CAC>=3, minnow<1, concentrated? " +
          ("OK" if ok else "FAIL"))
    return summary, WHALE_CLV, DOLPHIN_CLV, total_n, total_ltv


# ===========================================================================
# SECTION 7 - Scale estimation
# ===========================================================================

def section_scale():
    banner("SECTION 7: Scale estimation")
    customers = 50_000_000
    feats_per_cust = 40
    bytes_per_feat = 8
    score_values = 6                # clv, p10, p50, p90, churn_score, retention_prob
    bytes_per_score = 8
    score_history_days = 90
    nightly_runtime_h = 4.0
    realtime_qps = 1000

    feat_store = customers * feats_per_cust * bytes_per_feat
    score_now = customers * score_values * bytes_per_score
    score_history = customers * score_values * bytes_per_score * score_history_days
    nightly_throughput = customers / (nightly_runtime_h * 3600)

    print("Assumptions:")
    print("  active customers             = %s" % fmt_int(customers))
    print("  features / customer          = %d (RFM + velocity aggregates)" % feats_per_cust)
    print("  score values / customer      = %d (clv, p10/p50/p90, churn, retention)" % score_values)
    print("  nightly batch window         = %.0f h" % nightly_runtime_h)
    print("  realtime cancel-flow QPS     = %s /s (<200ms)" % fmt_int(realtime_qps))
    print()

    print("Throughput:")
    print("  nightly refresh              = %s customers / %.0fh = %s/s" %
          (fmt_int(customers), nightly_runtime_h, fmt_int(int(nightly_throughput))))
    print("  realtime lookups (CRM/ads)   = %s /s, cache-aided (Redis)" % fmt_int(realtime_qps))
    print()

    print("Storage:")
    print("  feature store (Redis)        = %s  (%s x %d feats x %d B)" %
          (fmt_gbytes(feat_store), fmt_int(customers), feats_per_cust, bytes_per_feat))
    print("  current scores (Postgres)    = %s  (%s x %d vals x %d B)" %
          (fmt_gbytes(score_now), fmt_int(customers), score_values, bytes_per_score))
    print("  90-day score history         = %s  (archive to S3 Parquet)" %
          fmt_gbytes(score_history))
    print()

    print("Latency budget:")
    print("  realtime CLV/churn lookup    < 5 ms   (Redis feature + cached score)")
    print("  realtime GBDT rescore        < 150 ms  (in-session cancel-flow offer)")
    print("  total (cancel-flow)          < 200 ms budget")
    print("  nightly batch retrain+score  ~4 h (Spark, full 50M)")
    print()

    ok = (customers == 50_000_000 and
          abs(feat_store / 1e9 - 16.0) < 1e-9 and
          abs(score_history / 1e9 - 216.0) < 1e-9 and
          abs(nightly_throughput - 3472.22) < 0.01)
    print("[check] 50M cust, feature store=16GB, 90d history=216GB, nightly ~3472/s? " +
          ("OK" if ok else "FAIL"))


def fmt_gbytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f PB" % n


# ===========================================================================
# SECTION 8 - GOLD values pinned for customer_ltv.html
# ===========================================================================

def section_gold(w, b, ret, hist, pred, sens, seg):
    banner("SECTION 8: GOLD values (pinned for customer_ltv.html)")

    summary, whale_clv, dolphin_clv, total_n, total_ltv = seg

    p_active = churn_score(w, b, CHURN_TRAIN[4])
    p_churn = churn_score(w, b, CHURN_TRAIN[9])

    w_cnt, w_ltv, w_avg = summary["Whale"]

    feat_store = 50_000_000 * 40 * 8
    score_history = 50_000_000 * 6 * 8 * 90

    gold = [
        # retention
        ("ret_premium_d1",  round(ret["premium"][1], 4)),
        ("ret_premium_d7",  round(ret["premium"][7], 4)),
        ("ret_premium_d30", round(ret["premium"][30], 4)),
        ("ret_premium_d90", round(ret["premium"][90], 4)),
        ("ret_standard_d1",  round(ret["standard"][1], 4)),
        ("ret_standard_d30", round(ret["standard"][30], 4)),
        ("ret_standard_d90", round(ret["standard"][90], 4)),
        ("ret_trial_d1",  round(ret["trial"][1], 4)),
        ("ret_trial_d30", round(ret["trial"][30], 4)),
        ("ret_trial_d90", round(ret["trial"][90], 4)),
        # churn LR
        ("churn_lr",        LR_LR),
        ("churn_epochs",    LR_EPOCHS),
        ("churn_w0_tenure", round(w[0], 4)),
        ("churn_w2_recency", round(w[2], 4)),
        ("churn_w3_tickets", round(w[3], 4)),
        ("churn_bias",      round(b, 4)),
        ("churn_p_active",  round(p_active, 4)),
        ("churn_p_churn",   round(p_churn, 4)),
        # CLV
        ("hist_clv_premium",  round(hist["premium"], 2)),
        ("hist_clv_standard", round(hist["standard"], 2)),
        ("hist_clv_trial",    round(hist["trial"], 2)),
        ("pred_clv_premium",  round(pred["premium"], 2)),
        ("pred_clv_standard", round(pred["standard"], 2)),
        ("pred_clv_trial",    round(pred["trial"], 2)),
        ("annual_discount",   ANNUAL_DISCOUNT),
        ("r_monthly",         round(R_MONTHLY, 6)),
        ("clv_horizon",       CLV_HORIZON_MONTHS),
        ("cac",               CAC),
        # discount sensitivity (standard cohort)
        ("disc_standard_r0",   round(sens[0.0], 2)),
        ("disc_standard_r10",  round(sens[0.10], 2)),
        ("disc_standard_r20",  round(sens[0.20], 2)),
        ("disc_standard_r30",  round(sens[0.30], 2)),
        # segmentation
        ("seg_total_customers",   total_n),
        ("seg_total_ltv",         round(total_ltv, 2)),
        ("seg_whale_count",       w_cnt),
        ("seg_whale_avg_clv",     round(w_avg, 2)),
        ("seg_whale_ltvcac",      round(w_avg / CAC, 2)),
        ("seg_whale_ltv_share",   round(w_ltv / total_ltv, 4)),
        ("seg_whale_threshold",   round(whale_clv, 2)),
        ("seg_dolphin_threshold", round(dolphin_clv, 2)),
        # scale
        ("scale_feat_store_gb",    round(feat_store / 1e9, 2)),
        ("scale_score_history_gb", round(score_history / 1e9, 2)),
    ]
    for k, v in gold:
        print("  %-26s = %s" % (k, v))
    print()

    ok = (ret["premium"][1] > ret["premium"][90] and
          ret["premium"][90] > ret["standard"][90] > ret["trial"][90] and
          p_active < 0.15 and p_churn > 0.85 and
          hist["premium"] > pred["premium"] and
          pred["premium"] > pred["standard"] > pred["trial"] and
          sens[0.0] > sens[0.10] > sens[0.20] > sens[0.30] and
          w_avg > CAC and total_n == 1_000_000 and
          abs(feat_store / 1e9 - 16.0) < 1e-9)
    print("[check] GOLD reproduces from retention + churn LR + CLV + discount + segmentation? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# customer_ltv.py - Customer Lifetime Value system design simulation")
    print("# Pure Python stdlib only. Numbers below feed CUSTOMER_LTV.md")
    print("# and customer_ltv.html (gold-checked).")

    ret = section_retention()
    w, b = section_churn()
    hist = section_historical_clv()
    pred = section_predictive_clv(hist)
    sens = section_discount_sensitivity()
    seg = section_segmentation(pred)
    section_scale()
    section_gold(w, b, ret, hist, pred, sens, seg)
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
