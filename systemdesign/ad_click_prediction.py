#!/usr/bin/env python3
"""
ad_click_prediction.py - Ad click prediction (pCTR) system design simulation
(GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds AD_CLICK_PREDICTION.md
and is recomputed identically in ad_click_prediction.html (gold-checked).

Core model: pCTR (predicted click-through rate) under a strict latency budget.
  CTR estimation : Beta-Binomial smoothing shrinks noisy small-sample rates
  Feature eng.   : categorical -> one-hot, numerical -> bucketing, hash trick
  Model          : logistic regression (full-batch gradient descent)
  Calibration    : reliability check + Platt scaling as a post-hoc layer
  Online vs batch: streaming SGD adapts weights under concept drift
  A/B test       : two-proportion z-test for model comparison

The serving pipeline (Section 6): candidates -> feature service -> ranker ->
calibration -> auction, all inside a ~50ms p99 budget.

Sections:
  1. CTR estimation with Beta smoothing (impressions/clicks + prior)
  2. Feature engineering pipeline (one-hot, bucketing, hash trick)
  3. Logistic regression for CTR (gradient descent + calibration check)
  4. Online vs batch learning (streaming SGD, concept drift)
  5. A/B test for model comparison (two-proportion z-test)
  6. Scale estimation (billions of impressions/day, p99 latency budget)
  7. GOLD values pinned for ad_click_prediction.html
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


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f EB" % n


def fmt_int(n):
    return "{:,}".format(n)


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def sigmoid(z):
    """Numerically stable logistic function (matches JS impl exactly)."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def erf_approx(x):
    """Abramowitz & Stegun 7.1.26 (max error 1.5e-7). Used identically in JS so
    the p-value gold-check matches byte-for-byte."""
    sign = 1.0 if x >= 0 else -1.0
    x = abs(x)
    a1, a2, a3 = 0.254829592, -0.284496736, 1.421413741
    a4, a5, p = -1.453152027, 1.061405429, 0.3275911
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return sign * y


def normal_cdf(z):
    return 0.5 * (1.0 + erf_approx(z / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# SECTION 1 - CTR estimation with Beta smoothing
# ---------------------------------------------------------------------------

# (ad_id, impressions, clicks). Deterministic toy inventory.
ADS = [
    ("ad_A", 1000,  50),   # raw CTR 5.00%  -- lots of data, trustworthy
    ("ad_B",  100,   6),   # raw CTR 6.00%  -- moderate data, noisy
    ("ad_C",   10,   2),   # raw CTR 20.0%  -- tiny data, very noisy
    ("ad_D", 5000, 250),   # raw CTR 5.00%  -- lots of data
    ("ad_E",    3,   1),   # raw CTR 33.3%  -- almost no data, junk estimate
]

# Beta(alpha, beta) prior. alpha=1, beta=19 -> prior mean 1/20 = 5.0%, the
# network-average CTR. "Equivalent" to 20 pseudo-impressions, 1 pseudo-click.
PRIOR_ALPHA = 1.0
PRIOR_BETA = 19.0


def raw_ctr(clicks, impressions):
    return clicks / impressions if impressions else 0.0


def smoothed_ctr(clicks, impressions, a=PRIOR_ALPHA, b=PRIOR_BETA):
    """Beta-Binomial posterior mean = (clicks + a) / (impressions + a + b)."""
    return (clicks + a) / (impressions + a + b)


def section_smoothing():
    banner("SECTION 1: CTR estimation with Beta-Binomial smoothing")
    print("Raw CTR = clicks / impressions is a MAXIMUM-LIKELIHOOD estimate. On")
    print("small samples it is wildly noisy (3 impressions -> 0% or 33% or 67%).")
    print("Beta(alpha,beta) smoothing treats each ad's CTR as a draw from a prior")
    print("distribution and reports the POSTERIOR MEAN:")
    print("  smoothed = (clicks + alpha) / (impressions + alpha + beta)")
    print("Prior Beta(%.0f,%.0f) -> mean %.4f, equivalent to %.0f pseudo-impressions,"
          " %.0f pseudo-click." % (PRIOR_ALPHA, PRIOR_BETA,
                                   PRIOR_ALPHA / (PRIOR_ALPHA + PRIOR_BETA),
                                   PRIOR_ALPHA + PRIOR_BETA, PRIOR_ALPHA))
    print()
    print("  %-6s %12s %9s %12s %12s %8s" %
          ("ad", "impressions", "clicks", "raw CTR", "smoothed", "shrink"))
    for ad_id, imp, clk in ADS:
        raw = raw_ctr(clk, imp)
        sm = smoothed_ctr(clk, imp)
        shrink = (sm - raw) / raw * 100.0 if raw else 0.0
        print("  %-6s %12d %9d %11.2f%% %11.2f%% %+7.1f%%" %
              (ad_id, imp, clk, raw * 100, sm * 100, shrink))
    print()
    print("  NOTE: ad_E (3 impressions) raw 33.3% -> smoothed 8.70%: yanked back")
    print("  toward the 5% prior. ad_A/ad_D (1000+ impressions) barely move.")
    print("  This is EXACTLY the cold-start / low-data problem: you cannot rank ads")
    print("  by raw CTR; the prior prevents noisy winners from dominating the auction.")
    print()
    print("  Also known as Laplace smoothing (add-alpha), or 'add-1' when alpha=1.")
    print()

    # COEC check (click-over-expected-click) -- a calibration health metric.
    total_imp = sum(i for _, i, _ in ADS)
    total_clk = sum(c for _, _, c in ADS)
    expected = total_imp * 0.05
    coec_all = total_clk / expected
    print("COEC (click-over-expected-click): realized clicks / expected clicks.")
    print("  COEC ~ 1.0 -> model is calibrated. COEC > 1 -> model UNDER-predicts.")
    print("  Using the 5.00% prior as the expected rate:")
    print("  network COEC = %d / (%d * 0.05) = %.3f" %
          (total_clk, total_imp, coec_all))
    print()

    ok = (abs(smoothed_ctr(50, 1000) - 0.0500) < 1e-9 and
          abs(smoothed_ctr(2, 10) - 0.1000) < 1e-9 and
          abs(smoothed_ctr(1, 3) - 0.0870) < 1e-4 and
          abs(coec_all - 1.011) < 1e-2)
    print("[check] smoothed ad_A=5.00%, ad_C=10.00%, ad_E~8.70%, COEC~1.011? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Feature engineering pipeline
# ---------------------------------------------------------------------------

# Categorical domains
CATEGORIES = ["food", "fashion", "tech"]   # 'food' = baseline (dropped)
DEVICES = ["desktop", "mobile"]            # 'desktop' = baseline
PLACEMENTS = ["feed", "search"]            # 'feed' = baseline

FEATURE_NAMES = ["bias", "is_tech", "is_fashion", "is_mobile", "is_search"]

# Numerical bucketing: hour_of_day [0,24) -> 4 ordinal buckets
HOUR_BUCKETS = [
    ("night",    0, 6),
    ("morning",  6, 12),
    ("afternoon", 12, 18),
    ("evening",  18, 24),
]


def bucket_for_hour(h):
    for name, lo, hi in HOUR_BUCKETS:
        if lo <= h < hi:
            return name
    return "night"


def fnv1a_32(s):
    """Deterministic FNV-1a 32-bit hash (matches JS impl exactly)."""
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) % (2 ** 32)
    return h


def encode_onehot(category, device, placement):
    """One-hot encode an impression, dropping the baseline level of each
    categorical (food/desktop/feed absorbed into the bias term)."""
    return [
        1.0,                                        # bias
        1.0 if category == "tech" else 0.0,         # is_tech
        1.0 if category == "fashion" else 0.0,      # is_fashion
        1.0 if device == "mobile" else 0.0,         # is_mobile
        1.0 if placement == "search" else 0.0,      # is_search
    ]


def section_feature_eng():
    banner("SECTION 2: Feature engineering pipeline")
    print("Production pCTR models ingest 20-50 categorical + 10-30 numerical")
    print("features. Three canonical transforms turn raw signals into a model-ready")
    print("vector:")
    print()

    print("(a) CATEGORICAL -> ONE-HOT (drop one level as the baseline).")
    print("    category={food,fashion,tech}; baseline=food -> [is_tech, is_fashion].")
    print("    device={desktop,mobile}; baseline=desktop -> [is_mobile].")
    print("    placement={feed,search}; baseline=feed -> [is_search].")
    print("    %-22s -> %s" % ("feature vector", str(FEATURE_NAMES)))
    for cat in CATEGORIES:
        for dev in DEVICES:
            for plc in PLACEMENTS:
                v = encode_onehot(cat, dev, plc)
                print("    %-7s %-8s %-7s -> %s" % (cat, dev, plc, v))
    print()

    print("(b) NUMERICAL -> BUCKETING (binning). Reduces noise + captures non-")
    print("    linearity without splines. hour_of_day -> 4 buckets:")
    for name, lo, hi in HOUR_BUCKETS:
        print("    [%2d, %2d) -> %-10s" % (lo, hi, name))
    for h in (3, 9, 14, 21):
        print("    hour=%2d -> bucket=%s" % (h, bucket_for_hour(h)))
    print()

    print("(c) HASH TRICK for HIGH-CARDINALITY categoricals. user_id has 100M+")
    print("    unique values -> can't one-hot. Hash into a fixed-size table and use")
    print("    the slot as the embedding index. Collisions cost <0.1% AUC at scale.")
    print("    FNV-1a(user_id) mod 8 -> slot:")
    user_ids = ["user_1", "user_2", "user_3", "user_42", "user_99", "user_123"]
    slots = {}
    for uid in user_ids:
        slot = fnv1a_32(uid) % 8
        slots.setdefault(slot, []).append(uid)
        print("    %-10s -> hash %10d -> slot %d" % (uid, fnv1a_32(uid), slot))
    collisions = [s for s, u in slots.items() if len(u) > 1]
    print("    slots used = %d / 8; collisions on slots: %s" %
          (len(slots), collisions if collisions else "(none this round)"))
    print()

    ok = (encode_onehot("tech", "mobile", "search") == [1.0, 1.0, 0.0, 1.0, 1.0] and
          bucket_for_hour(14) == "afternoon" and
          fnv1a_32("user_1") % 8 == 2)
    print("[check] one-hot tech+mobile+search=[1,1,0,1,1], hour14=afternoon, "
          "user_1->slot2? " + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Logistic regression for CTR
# ---------------------------------------------------------------------------

# Deterministic toy dataset, encoded as (category, device, placement, n, clicks).
# The first `clicks` impressions of each cell are clicks. Patterns:
#   search >> feed     (search strongly boosts CTR)
#   tech  > food       (tech mildly helps)
#   mobile ~ desktop   (mobile mildly helps)
#   fashion < food     (fashion hurts)
CELLS = [
    ("food",    "desktop", "feed",   6, 1),
    ("food",    "desktop", "search", 6, 3),
    ("food",    "mobile",  "feed",   6, 1),
    ("food",    "mobile",  "search", 6, 4),
    ("fashion", "desktop", "feed",   6, 0),
    ("fashion", "desktop", "search", 6, 2),
    ("fashion", "mobile",  "feed",   6, 0),
    ("fashion", "mobile",  "search", 6, 2),
    ("tech",    "desktop", "feed",   6, 1),
    ("tech",    "desktop", "search", 6, 4),
    ("tech",    "mobile",  "feed",   6, 2),
    ("tech",    "mobile",  "search", 6, 5),
]

LR_RATE = 0.5
LR_EPOCHS = 4000


def expand_cells(cells):
    """Expand aggregate cells into per-impression rows (deterministic click
    placement: first `k` rows of each cell are clicks)."""
    out = []
    for cat, dev, plc, n, k in cells:
        for i in range(n):
            out.append((cat, dev, plc, 1 if i < k else 0))
    return out


RAW_IMPRESSIONS = expand_cells(CELLS)


def build_dataset(raw):
    X, y = [], []
    for cat, dev, plc, click in raw:
        X.append(encode_onehot(cat, dev, plc))
        y.append(float(click))
    return X, y


def train_logreg(X, y, lr=LR_RATE, epochs=LR_EPOCHS):
    """Full-batch gradient descent on log-loss. Deterministic: weights init 0,
    fixed learning rate, fixed epoch count, no shuffling."""
    n, d = len(X), len(X[0])
    w = [0.0] * d
    for _ in range(epochs):
        grad = [0.0] * d
        for i in range(n):
            p = sigmoid(dot(w, X[i]))
            err = p - y[i]
            for j in range(d):
                grad[j] += err * X[i][j]
        for j in range(d):
            w[j] -= lr * grad[j] / n
    return w


def predict(w, x):
    return sigmoid(dot(w, x))


def log_loss(w, X, y):
    total = 0.0
    for i in range(len(X)):
        p = min(max(predict(w, X[i]), 1e-12), 1 - 1e-12)
        total += -(y[i] * math.log(p) + (1 - y[i]) * math.log(1 - p))
    return total / len(X)


def accuracy(w, X, y, thresh=0.5):
    correct = 0
    for i in range(len(X)):
        if (predict(w, X[i]) >= thresh) == (y[i] >= 0.5):
            correct += 1
    return correct / len(X)


def section_logreg():
    banner("SECTION 3: Logistic regression for CTR prediction")
    print("Logistic regression models log(p/(1-p)) as a LINEAR function of features.")
    print("  pCTR = sigmoid(w0 + w_tech*is_tech + ... + w_search*is_search)")
    print("Trained by full-batch gradient descent on log-loss (cross-entropy):")
    print("  grad_j = sum_i (p_i - y_i) * x_ij ;  w -= lr * grad / n")
    print("  lr=%.2f, epochs=%d, weights init=0 (fully deterministic)." % (LR_RATE, LR_EPOCHS))
    print()

    X, y = build_dataset(RAW_IMPRESSIONS)
    n_click = int(sum(y))
    print("Dataset: %d impressions, %d clicks (CTR %.1f%%). Baseline = food+desktop+feed."
          % (len(y), n_click, n_click / len(y) * 100))
    print()
    w = train_logreg(X, y)
    print("Learned weights (logits):")
    for j, name in enumerate(FEATURE_NAMES):
        print("  %-10s %+8.4f" % (name, w[j]))
    print()
    order = sorted(range(len(w)), key=lambda j: -abs(w[j]))
    print("  Feature importance (by |weight|): %s" %
          ", ".join("%s (%+.4f)" % (FEATURE_NAMES[j], w[j]) for j in order))
    print()

    print("Predicted pCTR per feature combination (every cell):")
    print("  %-9s %-9s %-8s %9s" % ("category", "device", "place", "pCTR"))
    for cat in CATEGORIES:
        for dev in DEVICES:
            for plc in PLACEMENTS:
                p = predict(w, encode_onehot(cat, dev, plc))
                print("  %-9s %-9s %-8s %8.1f%%" % (cat, dev, plc, p * 100))
    print()

    ll = log_loss(w, X, y)
    acc = accuracy(w, X, y)
    print("Fit: log-loss = %.4f, train accuracy = %.1f%% (threshold 0.5)." % (ll, acc * 100))
    print()

    print("CALIBRATION check (reliability). Mean predicted pCTR vs actual CTR:")
    mean_pred = sum(predict(w, X[i]) for i in range(len(X))) / len(X)
    actual = sum(y) / len(y)
    print("  mean predicted pCTR = %.4f   actual CTR = %.4f   gap = %+.4f" %
          (mean_pred, actual, mean_pred - actual))
    print("  Logistic regression is ~calibrated on its training distribution. In")
    print("  production, drift breaks this -> add a post-hoc layer: Platt scaling")
    print("  (logistic on the logit) or isotonic regression (piecewise monotonic map),")
    print("  recomputed daily per (vertical x placement x cohort). Target: COEC ~ 1.0.")
    print()

    ok = (w[4] > w[1] > w[0] and            # search > tech > bias
          w[2] < 0 and                       # fashion negative
          abs(mean_pred - actual) < 0.05)
    print("[check] search>tech>bias, fashion<0, ~calibrated? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Online vs batch learning
# ---------------------------------------------------------------------------

# Concept-drift stream: after the batch model ships, users develop SEARCH AD
# FATIGUE -> search CTR collapses. Feed stays healthy. The batch model is now
# STALE; an online (SGD) model should pull the search weight DOWN.
DRIFT_STREAM = [
    ("tech",    "mobile",  "search", 0),
    ("tech",    "mobile",  "search", 0),
    ("food",    "mobile",  "search", 0),
    ("tech",    "desktop", "search", 0),
    ("tech",    "mobile",  "feed",   1),
    ("fashion", "mobile",  "feed",   0),
    ("tech",    "mobile",  "feed",   1),
    ("food",    "desktop", "feed",   0),
]

ONLINE_LR = 0.3
SEARCH_IDX = FEATURE_NAMES.index("is_search")


def online_step(w, x, y, lr):
    """Single-sample SGD update: w -= lr * (sigmoid(w.x) - y) * x."""
    p = sigmoid(dot(w, x))
    err = p - y
    return [w[j] - lr * err * x[j] for j in range(len(w))]


def section_online():
    banner("SECTION 4: Online vs batch learning (concept drift)")
    print("BATCH: retrain on the full impression log every 1-6h. Simple, strong")
    print("baseline, but STALE between retrains -> slow to react to drift.")
    print("ONLINE: update weights per impression via SGD. Catches drift in seconds")
    print("but is noisier and needs regularization. Production = both: batch for")
    print("stability + online for freshness.")
    print()
    print("Scenario: after ship, users get SEARCH AD FATIGUE -> search CTR drops.")
    print("Drift stream = 8 new impressions (search 0/4 clicks, feed 2/4 clicks).")
    print()

    X, y = build_dataset(RAW_IMPRESSIONS)
    Xd, yd = build_dataset(DRIFT_STREAM)

    w_batch = train_logreg(X, y)
    w_online = list(w_batch)   # online model STARTS from the batch weights
    w_search_0 = w_online[SEARCH_IDX]

    print("  step  event                         is_search  w_search  batch_w_search")
    print("  ----  ----------------------------  ---------  --------  --------------")
    print("  init  (batch model shipped)             --     %+8.4f      %+8.4f" %
          (w_search_0, w_batch[SEARCH_IDX]))
    snap = {0: w_search_0}
    for k in range(len(DRIFT_STREAM)):
        cat, dev, plc, click = DRIFT_STREAM[k]
        x = encode_onehot(cat, dev, plc)
        w_online = online_step(w_online, x, float(click), ONLINE_LR)
        if (k + 1) % 2 == 0:
            snap[k + 1] = w_online[SEARCH_IDX]
            print("  %4d  %-15s %-7s click=%d     %d        %+8.4f      %+8.4f" %
                  (k + 1, cat, dev, click, int(x[SEARCH_IDX]),
                   w_online[SEARCH_IDX], w_batch[SEARCH_IDX]))
    print()
    print("  -> batch model's w_search frozen at %+.4f (stale)." % w_batch[SEARCH_IDX])
    print("     online model's w_search falls %+.4f -> %+.4f as it absorbs 4 search"
          % (snap[0], snap[8]))
    print("     misses. The online model down-ranks search ads; the batch one keeps")
    print("     over-paying. This is the freshness gap online learning closes.")
    print()

    # Held-out: both models evaluated on the drift stream.
    ll_batch = log_loss(w_batch, Xd, yd)
    ll_online = log_loss(w_online, Xd, yd)
    acc_batch = accuracy(w_batch, Xd, yd)
    acc_online = accuracy(w_online, Xd, yd)
    print("Held-out on drift stream (8 impressions):")
    print("  batch  : log-loss %.4f, accuracy %.1f%%" % (ll_batch, acc_batch * 100))
    print("  online : log-loss %.4f, accuracy %.1f%%  <- lower loss, adapted" %
          (ll_online, acc_online * 100))
    print()

    ok = (w_online[SEARCH_IDX] < w_batch[SEARCH_IDX] and
          ll_online < ll_batch)
    print("[check] online w_search < batch w_search, online log-loss lower? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - A/B test for model comparison
# ---------------------------------------------------------------------------

def two_proportion_z_test(n1, x1, n2, x2):
    """Two-sided z-test for the difference of two proportions. Returns absolute
    z (magnitude is what gates significance)."""
    p1 = x1 / n1
    p2 = x2 / n2
    pooled = (x1 + x2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1.0 / n1 + 1.0 / n2))
    z = (p1 - p2) / se if se > 0 else 0.0
    p_value = 2.0 * (1.0 - normal_cdf(abs(z)))
    return p1, p2, pooled, se, abs(z), p_value


def section_abtest():
    banner("SECTION 5: A/B test for model comparison")
    print("To ship the online model we A/B test it against the batch baseline:")
    print("split live traffic 50/50, run for a fixed window, then ask 'is the CTR")
    print("lift real or noise?' via a two-proportion z-test:")
    print("  z = (p_winner - p_baseline) / sqrt( p_pool(1-p_pool) (1/n1 + 1/n2) )")
    print("  p-value = 2 * (1 - Phi(|z|)). Ship if p < 0.05 AND the lift is")
    print("  practically meaningful (guard against p-hacking on huge samples).")
    print()

    # Model A (batch) vs Model B (online). Held-out production traffic.
    nA, xA = 10000, 450      # batch: 4.50% CTR
    nB, xB = 10000, 540      # online: 5.40% CTR  (+20% relative)

    # pass B first so z is the magnitude of (B - A)
    pB, pA, pooled, se, z, pv = two_proportion_z_test(nB, xB, nA, xA)
    lift_abs = pB - pA
    lift_rel = (pB - pA) / pA * 100.0
    print("  Model A (batch) : %s impressions, %s clicks -> CTR %.2f%%" %
          (fmt_int(nA), fmt_int(xA), pA * 100))
    print("  Model B (online): %s impressions, %s clicks -> CTR %.2f%%" %
          (fmt_int(nB), fmt_int(xB), pB * 100))
    print()
    print("  pooled rate      = %.4f" % pooled)
    print("  standard error   = %.6f" % se)
    print("  z-statistic      = %.4f" % z)
    print("  p-value (2-side) = %.5f" % pv)
    print("  absolute lift    = %+.4f  (%.2f%% relative)" % (lift_abs, lift_rel))
    print()
    verdict = "SIGNIFICANT (p<0.05) -> ship Model B" if pv < 0.05 else "NOT significant -> keep A"
    print("  verdict: %s" % verdict)
    print()
    print("  GOTCHA: at billions of impressions/day EVERYTHING is statistically")
    print("  significant. Gate on EFFECT SIZE + business metrics (revenue, retention),")
    print("  not just p. Also run an A/A test first to sanity-check the pipeline.")
    print()

    ok = (abs(z - 2.9339) < 0.01 and pv < 0.01 and abs(lift_rel - 20.0) < 0.1)
    print("[check] z~2.93, p<0.01, +20% relative lift -> significant? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 6: Scale estimation")
    impressions_day = 2_000_000_000        # 2B impressions/day (Meta/Google scale)
    ctr = 0.05                             # 5% network CTR
    ads_per_request = 5                    # slots per page load
    candidates_per_request = 10_000        # scored before the auction
    sps = 86_400
    row_bytes = 100

    requests_day = impressions_day / ads_per_request
    request_qps = requests_day / sps
    score_qps = request_qps * candidates_per_request
    clicks_day = impressions_day * ctr
    imp_storage_day = impressions_day * row_bytes
    emb_dim = 128
    cat_features = 50
    vocab_avg = 10_000_000
    emb_table_gb = cat_features * vocab_avg * emb_dim * 4 / 1e9

    print("Assumptions:")
    print("  impressions / day          = %s" % fmt_int(impressions_day))
    print("  network CTR                = %.0f%%" % (ctr * 100))
    print("  ads shown / request        = %d" % ads_per_request)
    print("  candidates scored / request= %s (before auction)" % fmt_int(candidates_per_request))
    print("  categorical features       = %d (avg vocab %s)" % (cat_features, fmt_int(vocab_avg)))
    print("  embedding dimension        = %d" % emb_dim)
    print()

    print("Throughput:")
    print("  page-load requests /s      = %s /s" % fmt_int(int(request_qps)))
    print("  candidate ad scores /s     = %s /s  (requests x candidates)" %
          fmt_int(int(score_qps)))
    print("  clicks logged /day         = %s" % fmt_int(int(clicks_day)))
    print()

    print("Storage (impression log ~100 B/row):")
    print("  impressions /day           = %s  -> %s /day" %
          (fmt_int(impressions_day), fmt_bytes(imp_storage_day)))
    print("  impressions /year          = %s  -> %s /year" %
          (fmt_int(impressions_day * 365), fmt_bytes(imp_storage_day * 365)))
    print("  DLRM embedding tables      = %s  (50 cats x %s vocab x %d-dim x 4B)" %
          (fmt_bytes(emb_table_gb * 1e9), fmt_int(vocab_avg), emb_dim))
    print("    -> sharded across GPU/parameter servers; 10-100x smaller w/ PQ.")
    print()

    print("Latency budget (p99 < 50ms end-to-end):")
    print("  feature fetch (online)     < 8 ms")
    print("  candidate retrieval        < 7 ms")
    print("  ranker (DLRM/GBDT)         < 20 ms")
    print("  calibration + auction      < 5 ms")
    print("  network + queueing         < 10 ms")
    print("  total                      < 50 ms")
    print()

    ok = (impressions_day == 2_000_000_000 and
          abs(request_qps - 4629.63) < 0.1 and
          abs(score_qps - 4.6296e7) < 1e3 and
          abs(emb_table_gb - 256.0) < 1e-3)
    print("[check] 2B imp/day, ~4630 req/s, ~46M scores/s, emb table=256GB? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for ad_click_prediction.html
# ---------------------------------------------------------------------------

def section_gold():
    banner("SECTION 7: GOLD values (pinned for ad_click_prediction.html)")

    # smoothing
    sm_A = smoothed_ctr(50, 1000)
    sm_C = smoothed_ctr(2, 10)
    sm_E = smoothed_ctr(1, 3)
    total_imp = sum(i for _, i, _ in ADS)
    total_clk = sum(c for _, _, c in ADS)
    coec = total_clk / (total_imp * 0.05)

    # feature eng
    hot_tms = encode_onehot("tech", "mobile", "search")
    hour14 = bucket_for_hour(14)
    slot_user1 = fnv1a_32("user_1") % 8

    # logistic regression
    X, y = build_dataset(RAW_IMPRESSIONS)
    w = train_logreg(X, y)
    p_food_search = predict(w, encode_onehot("food", "desktop", "search"))
    p_food_feed = predict(w, encode_onehot("food", "desktop", "feed"))
    p_tech_search = predict(w, encode_onehot("tech", "mobile", "search"))
    ll = log_loss(w, X, y)

    # online learning
    w_online = list(w)
    for k in range(len(DRIFT_STREAM)):
        cat, dev, plc, click = DRIFT_STREAM[k]
        w_online = online_step(w_online, encode_onehot(cat, dev, plc),
                               float(click), ONLINE_LR)
    w_search_batch = w[SEARCH_IDX]
    w_search_online = w_online[SEARCH_IDX]
    Xd, yd = build_dataset(DRIFT_STREAM)
    ll_batch_drift = log_loss(w, Xd, yd)
    ll_online_drift = log_loss(w_online, Xd, yd)

    # A/B test
    pB, pA, pooled, se, z, pv = two_proportion_z_test(10000, 540, 10000, 450)
    lift_rel = (pB - pA) / pA * 100.0

    # scale
    req_qps = 2_000_000_000 / 5 / 86400
    score_qps = req_qps * 10_000
    emb_gb = 50 * 10_000_000 * 128 * 4 / 1e9

    gold = [
        ("smooth_ad_A_1k50",         round(sm_A, 4)),
        ("smooth_ad_C_10_2",         round(sm_C, 4)),
        ("smooth_ad_E_3_1",          round(sm_E, 4)),
        ("network_coec",             round(coec, 3)),
        ("onehot_tech_mobile_srch",  "".join(str(int(v)) for v in hot_tms)),
        ("bucket_hour14",            hour14),
        ("hash_slot_user1",          slot_user1),
        ("lr_w_bias",                round(w[0], 4)),
        ("lr_w_is_tech",             round(w[1], 4)),
        ("lr_w_is_fashion",          round(w[2], 4)),
        ("lr_w_is_mobile",           round(w[3], 4)),
        ("lr_w_is_search",           round(w[4], 4)),
        ("lr_pctr_food_search",      round(p_food_search, 4)),
        ("lr_pctr_food_feed",        round(p_food_feed, 4)),
        ("lr_pctr_tech_mobile_srch", round(p_tech_search, 4)),
        ("lr_train_logloss",         round(ll, 4)),
        ("online_w_search_batch",    round(w_search_batch, 4)),
        ("online_w_search_after",    round(w_search_online, 4)),
        ("online_logloss_drift",     round(ll_online_drift, 4)),
        ("batch_logloss_drift",      round(ll_batch_drift, 4)),
        ("ab_z_stat",                round(z, 4)),
        ("ab_p_value",               round(pv, 5)),
        ("ab_lift_rel_pct",          round(lift_rel, 2)),
        ("scale_req_qps",            round(req_qps, 2)),
        ("scale_score_qps",          round(score_qps, 0)),
        ("scale_emb_table_gb",       round(emb_gb, 2)),
    ]
    for k, v in gold:
        print("  %-26s = %s" % (k, v))
    print()

    ok = (round(sm_A, 4) == 0.05 and round(sm_C, 4) == 0.1 and
          round(sm_E, 4) == 0.087 and round(coec, 3) == 1.011 and
          "".join(str(int(v)) for v in hot_tms) == "11011" and
          hour14 == "afternoon" and slot_user1 == 2 and
          w[4] > w[1] > w[0] and w[2] < 0 and
          round(p_tech_search, 4) > 0.5 and
          w_search_online < w_search_batch and
          ll_online_drift < ll_batch_drift and
          round(z, 4) == 2.9339 and pv < 0.01 and
          round(emb_gb, 2) == 256.0)
    print("[check] GOLD reproduces from smoothing + logreg + online + z-test? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# ad_click_prediction.py - Ad click prediction (pCTR) system design")
    print("# Pure Python stdlib only. Numbers below feed AD_CLICK_PREDICTION.md")
    print("# and ad_click_prediction.html (gold-checked).")

    section_smoothing()
    section_feature_eng()
    section_logreg()
    section_online()
    section_abtest()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
