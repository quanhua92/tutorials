#!/usr/bin/env python3
"""
fraud_detection.py - Real-time fraud detection system design (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds FRAUD_DETECTION.md
and is recomputed identically in fraud_detection.html (gold-checked).

Core model: MULTI-STAGE CASCADE + rule engine + logistic-regression scorer.
  Rule engine      : velocity checks, amount thresholds, geo anomalies, blacklist
  Feature pipeline : sliding-window aggregations (1h / 24h / 30d)
  ML scorer        : logistic regression trained by batch gradient descent
  Decision         : optimal cost-based threshold tau = C_FP / (C_FN + C_FP)
  Cascade          : rules (~3ms,100%) -> ML (~25ms,~30%) -> deep (~40ms,~2%)
  Graph analysis   : account connectivity, 2-hop fraud-ring aggregation (GraphSAGE-style)

Sections:
  1. Rule engine (velocity, amount, geo, blacklist)
  2. Feature pipeline (aggregation windows)
  3. ML scoring (logistic regression on features)
  4. Optimal decision threshold (cost-based)
  5. Real-time vs batch scoring (3-stage cascade)
  6. Graph analysis (account connectivity, fraud rings)
  7. Scale estimation (TPS, storage, latency budget)
  8. GOLD values pinned for fraud_detection.html
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


def sigmoid(z):
    """Numerically stable logistic sigmoid (matches JS Math.exp exactly)."""
    if z >= 0.0:
        ez = math.exp(-z)
        return 1.0 / (1.0 + ez)
    ez = math.exp(z)
    return ez / (1.0 + ez)


# ---------------------------------------------------------------------------
# dataset -- deterministic, reproducible verbatim in JS
# ---------------------------------------------------------------------------
# 8 features per transaction (raw, pre-normalization):
#   [amount, velocity_1h, velocity_amt_1h, geo_kmh,
#    new_device, merchant_risk, graph_fraud_nbrs, is_intl]
# Label: 0 = legit, 1 = fraud.

FEAT_NAMES = [
    "amount", "vel_1h", "vel_amt_1h", "geo_kmh",
    "new_dev", "m_risk", "graph_nbrs", "intl",
]

# normalization divisors (so every feature lands in ~[0,1]); capped at 1.0.
FEAT_MAX = [10000.0, 12.0, 20000.0, 1200.0, 1.0, 1.0, 5.0, 1.0]

TRAIN = [
    # legit (label 0)
    (45.0,    1, 150.0,    0.0, 0, 0.10, 0, 0),
    (89.0,    2, 320.0,    0.0, 0, 0.15, 0, 0),
    (12.0,    1,  60.0,    0.0, 0, 0.05, 0, 0),
    (210.0,   3, 540.0,    0.0, 0, 0.20, 0, 0),
    (55.0,    2, 180.0,  120.0, 0, 0.30, 0, 0),   # legit travel (aircraft)
    (340.0,   1, 340.0,    0.0, 1, 0.25, 0, 0),   # legit first-time device (gift)
    # fraud (label 1)
    (3200.0,  6, 9800.0,   0.0, 1, 0.70, 2, 1),
    (5400.0,  9, 18000.0, 950.0, 1, 0.85, 4, 1),  # impossible travel
    (870.0,   5, 4200.0, 1100.0, 1, 0.60, 3, 1),  # impossible travel
    (1500.0,  7, 7600.0,   0.0, 1, 0.75, 1, 1),
    (4200.0,  4, 8400.0,  40.0, 0, 0.65, 2, 0),
    (2600.0,  8, 11000.0, 880.0, 1, 0.80, 5, 1),
]


def normalize(row):
    out = []
    for i in range(len(row)):
        v = row[i] / FEAT_MAX[i]
        out.append(min(1.0, v))
    return out


# ===========================================================================
# SECTION 1 - Rule engine
# ===========================================================================

# Thresholds -- hard rules that fire BEFORE the ML scorer sees the transaction.
RULE_BLACKLIST_CARDS = {"CARD_EVIL"}        # instantly BLOCK
RULE_MAX_AMOUNT = 4000.0                    # block abnormally large tx
RULE_VEL_1H_COUNT = 6                       # >6 txs in 1h -> block (burst)
RULE_VEL_1H_AMOUNT = 15000.0                # >15k in 1h -> block
RULE_GEO_KMH = 900.0                        # >900 km/h is physically impossible
RULE_REVIEW_NEWDEV_AMOUNT = 1500.0          # new device + high amount -> REVIEW


def rule_engine(tx):
    """Return (decision, reasons[]) for a transaction dict. ~3ms in-memory."""
    reasons = []
    if tx.get("card") in RULE_BLACKLIST_CARDS:
        return "BLOCK", ["blacklisted_card:%s" % tx.get("card")]
    if tx["amount"] > RULE_MAX_AMOUNT:
        reasons.append("amount>%.0f (%.0f)" % (RULE_MAX_AMOUNT, tx["amount"]))
    if tx["vel_1h"] > RULE_VEL_1H_COUNT:
        reasons.append("velocity_1h>%d (%d)" % (RULE_VEL_1H_COUNT, tx["vel_1h"]))
    if tx["vel_amt_1h"] > RULE_VEL_1H_AMOUNT:
        reasons.append("vel_amt_1h>%.0f (%.0f)" %
                       (RULE_VEL_1H_AMOUNT, tx["vel_amt_1h"]))
    if tx["geo_kmh"] > RULE_GEO_KMH:
        reasons.append("impossible_travel>%.0f km/h (%.0f)" %
                       (RULE_GEO_KMH, tx["geo_kmh"]))
    if reasons:
        return "BLOCK", reasons
    if tx["new_device"] == 1 and tx["amount"] >= RULE_REVIEW_NEWDEV_AMOUNT:
        return "REVIEW", ["new_device+amount>=%.0f" % RULE_REVIEW_NEWDEV_AMOUNT]
    return "PASS", []


def section_rules():
    banner("SECTION 1: Rule engine (velocity, amount, geo, blacklist)")
    print("Hard rules run FIRST, in-memory hash lookups (~3ms, 100% of traffic).")
    print("They catch OBVIOUS fraud deterministically and short-circuit the ML")
    print("scorer entirely. Anything PASS-ing falls through to the ML cascade.")
    print()
    print("  blacklist cards           = %s" % sorted(RULE_BLACKLIST_CARDS))
    print("  max amount                > %.0f" % RULE_MAX_AMOUNT)
    print("  velocity 1h (count)       > %d" % RULE_VEL_1H_COUNT)
    print("  velocity 1h (amount sum)  > %.0f" % RULE_VEL_1H_AMOUNT)
    print("  geo velocity              > %.0f km/h  (impossible travel)" % RULE_GEO_KMH)
    print("  new device + amount >= %.0f     -> REVIEW (human look)" %
          RULE_REVIEW_NEWDEV_AMOUNT)
    print()

    tests = [
        ("coffee",     {"amount": 45,   "vel_1h": 1, "vel_amt_1h": 150,
                        "geo_kmh": 0,   "new_device": 0}),
        ("dinner",     {"amount": 210,  "vel_1h": 3, "vel_amt_1h": 540,
                        "geo_kmh": 0,   "new_device": 0}),
        ("big_burst",  {"amount": 3800, "vel_1h": 8, "vel_amt_1h": 18000,
                        "geo_kmh": 0,   "new_device": 1}),
        ("teleport",   {"amount": 1200, "vel_1h": 2, "vel_amt_1h": 2400,
                        "geo_kmh": 2785, "new_device": 1}),  # NYC->London 2h
        ("blacklist",  {"amount": 50,   "vel_1h": 1, "vel_amt_1h": 50,
                        "geo_kmh": 0,   "new_device": 0, "card": "CARD_EVIL"}),
        ("newdev_big", {"amount": 1600, "vel_1h": 1, "vel_amt_1h": 1600,
                        "geo_kmh": 0,   "new_device": 1}),
    ]
    print("  %-12s %-8s %s" % ("tx", "decision", "reasons"))
    results = {}
    for name, tx in tests:
        dec, reasons = rule_engine(tx)
        results[name] = (dec, reasons)
        rstr = "; ".join(reasons) if reasons else "(none -- PASS to ML)"
        print("  %-12s %-8s %s" % (name, dec, rstr))
    print()
    print("  NOTE: 'teleport' is impossible travel -- NYC to London (~5570 km) in")
    print("  2h needs 2785 km/h, faster than any airliner. One of the highest-")
    print("  signal single features in card-not-present fraud.")
    print()

    ok = (results["coffee"][0] == "PASS" and
          results["big_burst"][0] == "BLOCK" and
          results["teleport"][0] == "BLOCK" and
          results["blacklist"][0] == "BLOCK" and
          results["newdev_big"][0] == "REVIEW")
    print("[check] coffee=PASS, big_burst/teleport/blacklist=BLOCK, newdev_big=REVIEW? " +
          ("OK" if ok else "FAIL"))


# ===========================================================================
# SECTION 2 - Feature pipeline (aggregation windows)
# ===========================================================================

# A user's recent transaction history (minutes_ago, amount). The current
# transaction arrives at t=0. Sliding-window features are computed by scanning
# this history -- in production this is Flink -> Redis counters (~3ms).
USER_HISTORY = [
    (5,   120.0),
    (20,   45.0),
    (40,  300.0),
    (90,   60.0),
    (200, 250.0),
]
CUR_AMOUNT = 500.0
WINDOW_30D_COUNT = 28
WINDOW_30D_SUM = 4200.0


def feature_pipeline(history, cur_amount):
    """Build velocity/behavioral features from sliding windows."""
    one_h = [amt for (mins, amt) in history if mins <= 60]
    day = [amt for (mins, amt) in history if mins <= 24 * 60]
    count_1h = len(one_h) + 1                       # +1 = the current tx
    sum_1h = sum(one_h) + cur_amount
    count_24h = len(day) + 1
    sum_24h = sum(day) + cur_amount
    avg_30d = WINDOW_30D_SUM / WINDOW_30D_COUNT
    return {
        "tx_count_1h": count_1h,
        "amount_sum_1h": sum_1h,
        "tx_count_24h": count_24h,
        "amount_sum_24h": sum_24h,
        "amount_avg_30d": avg_30d,
        "amount_zscore": (cur_amount - avg_30d) /
                         max(1.0, math.sqrt(WINDOW_30D_SUM / WINDOW_30D_COUNT)),
    }


def section_features():
    banner("SECTION 2: Feature pipeline (aggregation windows)")
    print("Streaming features are pre-aggregated by Flink into Redis counters so")
    print("the scorer reads them in ~3ms instead of scanning history each time.")
    print("The core idea: every feature is a SLIDING WINDOW over the user's past.")
    print()
    print("  user history (minutes_ago, amount):")
    for m, a in USER_HISTORY:
        print("    %4d min ago   %7.0f" % (m, a))
    print("    + current tx   %7.0f" % CUR_AMOUNT)
    print()

    feats = feature_pipeline(USER_HISTORY, CUR_AMOUNT)
    print("  computed features:")
    for k, v in feats.items():
        print("    %-18s = %.4f" % (k, v))
    print()
    print("  tx_count_1h counts txs within the last 60 min -> 3 prior (5/20/40m)")
    print("  + the current one = 4. This is the velocity signal rules + ML both use.")
    print()

    ok = (feats["tx_count_1h"] == 4 and
          abs(feats["amount_sum_1h"] - 965.0) < 1e-9 and
          feats["tx_count_24h"] == 6 and
          abs(feats["amount_avg_30d"] - 150.0) < 1e-9)
    print("[check] count_1h=4, sum_1h=965, count_24h=6, avg_30d=150? " +
          ("OK" if ok else "FAIL"))


# ===========================================================================
# SECTION 3 - ML scoring (logistic regression)
# ===========================================================================

LR_LR = 0.5
LR_EPOCHS = 2000


def train_lr(data):
    """Batch gradient descent on normalized features. Deterministic."""
    X = [normalize(row) for row in data]
    y = [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
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
            err = p - y[i]
            for j in range(d):
                gw[j] += err * X[i][j]
            gb += err
        for j in range(d):
            w[j] -= LR_LR * gw[j] / n
        b -= LR_LR * gb / n
    return w, b


def lr_score(w, b, row):
    z = b
    xn = normalize(row)
    for j in range(len(w)):
        z += w[j] * xn[j]
    return sigmoid(z)


def section_ml():
    banner("SECTION 3: ML scoring (logistic regression on features)")
    print("Primary scorer is a GBDT (LightGBM) in production, but the math of a")
    print("SCORER is a calibrated P(fraud) over engineered features. We train a")
    print("logistic regression by batch gradient descent -- pure stdlib, no deps.")
    print("  z = b + sum(w_j * x_j);  P(fraud) = sigmoid(z)")
    print()
    print("  normalization divisor per feature (x_j = raw / FEAT_MAX, capped 1.0):")
    for i in range(len(FEAT_NAMES)):
        print("    %-12s div = %7.1f" % (FEAT_NAMES[i], FEAT_MAX[i]))
    print("  train set: %d legit, %d fraud  (real base rate is ~0.1%%; we balance"
          % (6, 6))
    print("  for the toy model and would recalibrate via scale_pos_weight / Platt).")
    print("  lr = %.2f, epochs = %d" % (LR_LR, LR_EPOCHS))
    print()

    w, b = train_lr(TRAIN)
    print("  learned weights (per normalized feature):")
    for j in range(len(w)):
        print("    %-12s %+8.4f" % (FEAT_NAMES[j], w[j]))
    print("    %-12s %+8.4f" % ("(bias)", b))
    print()

    print("  scores on training set (should separate the two classes):")
    print("    %-10s %8s %6s %8s" % ("tx#", "amount", "label", "P(fraud)"))
    for i, row in enumerate(TRAIN):
        p = lr_score(w, b, row)
        print("    t%-9d %8.0f %6d %8.4f" % (i + 1, row[0], 1 if i >= 6 else 0, p))
    print()

    p_legit = lr_score(w, b, TRAIN[1])     # dinner
    p_fraud = lr_score(w, b, TRAIN[7])     # impossible travel
    ok = (p_legit < 0.15 and p_fraud > 0.85)
    print("[check] legit tx P<0.15 (%.4f) and fraud tx P>0.85 (%.4f)? " %
          (p_legit, p_fraud) + ("OK" if ok else "FAIL"))
    return w, b


# ===========================================================================
# SECTION 4 - Optimal decision threshold
# ===========================================================================

C_FN = 535.0       # missed fraud: avg fraud amount + chargeback fee
C_FP = 100.0       # false positive block: CLV x churn probability


def section_threshold(w, b):
    banner("SECTION 4: Optimal decision threshold (cost-based)")
    print("NEVER use threshold 0.5. It assumes equal costs and balanced classes --")
    print("both FALSE in fraud. The cost-optimal threshold is the point where the")
    print("expected cost of a false positive equals that of a false negative:")
    print("  tau = C_FP / (C_FN + C_FP)")
    print()
    print("  C_FN (missed fraud)   = $%.0f   (avg fraud amount + chargeback)" % C_FN)
    print("  C_FP (wrongful block) = $%.0f   (CLV x churn probability)" % C_FP)
    tau = C_FP / (C_FN + C_FP)
    print("  tau = %.0f / (%.0f + %.0f) = %.4f  -> block if P(fraud) > %.2f%%" %
          (C_FP, C_FN, C_FP, tau, tau * 100))
    print()
    print("  Requires CALIBRATED probabilities (Platt scaling / isotonic). On raw")
    print("  unbalanced output, Bayes-correct: p' = p / (p + (1-p)/r) with r the")
    print("  downsampling ratio. Below we apply tau on the trained LR scorer.")
    print()

    REVIEW_LO, REVIEW_HI = tau * 0.6, tau * 1.4   # REVIEW band around tau
    print("  decisions (REVIEW band: P in [%.3f, %.3f] -> human analyst):" %
          (REVIEW_LO, REVIEW_HI))
    print("    %-10s %8s %10s" % ("tx#", "P(fraud)", "decision"))
    decisions = {}
    for i, row in enumerate(TRAIN):
        p = lr_score(w, b, row)
        if p <= REVIEW_LO:
            dec = "ALLOW"
        elif p >= REVIEW_HI:
            dec = "BLOCK"
        else:
            dec = "REVIEW"
        decisions[i] = (p, dec)
        print("    t%-9d %10.4f %10s" % (i + 1, p, dec))
    print()

    # expected cost illustration at tau vs at 0.5
    block_half = sum(1 for i in range(len(TRAIN)) if lr_score(w, b, TRAIN[i]) >= 0.5
                     and i < 6)
    miss_half = sum(1 for i in range(len(TRAIN)) if lr_score(w, b, TRAIN[i]) < 0.5
                    and i >= 6)
    block_tau = sum(1 for i in range(len(TRAIN)) if decisions[i][1] == "BLOCK"
                    and i < 6)
    miss_tau = sum(1 for i in range(len(TRAIN)) if decisions[i][1] == "ALLOW"
                   and i >= 6)
    cost_half = block_half * C_FP + miss_half * C_FN
    cost_tau = block_tau * C_FP + miss_tau * C_FN
    print("  cost on train set @0.5: %d FP x $%.0f + %d FN x $%.0f = $%.0f" %
          (block_half, C_FP, miss_half, C_FN, cost_half))
    print("  cost on train set @tau: %d FP x $%.0f + %d FN x $%.0f = $%.0f" %
          (block_tau, C_FP, miss_tau, C_FN, cost_tau))
    print("  Lower tau blocks more aggressively -> cheaper when fraud is costly.")
    print()

    ok = (abs(tau - 0.1575) < 0.001 and cost_tau <= cost_half + 1e-6)
    print("[check] tau~0.1575 and tau-cost <= 0.5-cost on train? " +
          ("OK" if ok else "FAIL"))
    return tau


# ===========================================================================
# SECTION 5 - Real-time vs batch scoring (cascade)
# ===========================================================================

# Per-stage latency (ms) and fraction of traffic that reaches it.
STAGES = [
    ("rules",    3.0,  1.00),   # 100% of traffic
    ("ML scorer", 25.0, 0.30),  # ~30% pass rules far enough to score
    ("deep model", 40.0, 0.02), # ~2% borderline -> entity embedding + MLP
]


def section_cascade():
    banner("SECTION 5: Real-time vs batch scoring (3-stage cascade)")
    print("A single expensive model on every transaction blows the latency budget.")
    print("Instead: CHEAP filters first, expensive models LAST on the few that")
    print("survive. Each stage eliminates obvious cases for the next.")
    print()
    print("  %-12s %10s %12s %14s" % ("stage", "latency", "traffic %", "avg contrib"))
    avg = 0.0
    p99 = 0.0
    for name, lat, frac in STAGES:
        contrib = lat * frac
        avg += contrib
        p99 += lat              # a worst-case tx hits every stage it can
        print("  %-12s %7.0f ms %12.2f %10.2f ms" %
              (name, lat, frac * 100, contrib))
    print("  %-12s %35s %10.2f ms" % ("avg latency/tx", "(sum contrib)", avg))
    print("  %-12s %35s %10.2f ms" % ("p99 (all stages)", "(sum latency)", p99))
    print("  budget p99 < 100 ms -> %.0f ms slack" % (100 - p99))
    print()
    print("  REAL-TIME path = the cascade above (synchronous, <100ms). BATCH path")
    print("  runs overnight: re-aggregate 30d features, retrain the scorer, refresh")
    print("  GNN entity embeddings, and ingest delayed labels (chargebacks arrive")
    print("  14-30 days later -- never evaluate on the last 30 days).")
    print()

    ok = (abs(avg - 11.3) < 0.01 and abs(p99 - 68.0) < 0.01 and p99 < 100)
    print("[check] avg latency=11.3ms, p99=68ms, under 100ms budget? " +
          ("OK" if ok else "FAIL"))


# ===========================================================================
# SECTION 6 - Graph analysis (account connectivity, fraud rings)
# ===========================================================================

# Entities linked by shared device / IP / card. A new card looks clean alone,
# but 2-hop links to confirmed-fraud accounts reveal a coordinated ring.
ACCOUNTS = ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
FRAUD = {"A4", "A5"}

# shared identifiers -> the accounts that share them (edges in the entity graph)
SHARED = {
    "device": {"D1": ["A1", "A2"], "D2": ["A2", "A4"],
               "D3": ["A3", "A5"], "D4": ["A1", "A6"]},
    "ip":     {"IP1": ["A2", "A3"], "IP2": ["A6", "A7"]},
    "card":   {"C1": ["A1", "A3"]},
}

# per-account risk feature (0-1) for GraphSAGE-style mean aggregation
ACCOUNT_RISK = {"A1": 0.10, "A2": 0.30, "A3": 0.40,
                "A4": 0.90, "A5": 0.85, "A6": 0.20, "A7": 0.15}


def build_adjacency():
    """Adjacency list from shared-identifier edges (undirected, deduped)."""
    adj = {a: set() for a in ACCOUNTS}
    for kind, groups in SHARED.items():
        for members in groups.values():
            for i in range(len(members)):
                for j in range(len(members)):
                    if i != j:
                        adj[members[i]].add(members[j])
    return {a: sorted(s) for a, s in adj.items()}


def graph_features(account, adj):
    """1-hop and 2-hop neighborhood aggregation (GraphSAGE mean-pool style)."""
    one_hop = adj[account]
    two_hop = set()
    for n in one_hop:
        for n2 in adj[n]:
            if n2 != account and n2 not in one_hop:
                two_hop.add(n2)
    one_risk = [ACCOUNT_RISK[a] for a in one_hop]
    two_risk = [ACCOUNT_RISK[a] for a in two_hop]
    one_mean = sum(one_risk) / len(one_risk) if one_risk else 0.0
    two_mean = sum(two_risk) / len(two_risk) if two_risk else 0.0
    fraud_within_2 = len([a for a in one_hop if a in FRAUD] +
                         [a for a in two_hop if a in FRAUD])
    return {
        "1hop": one_hop,
        "2hop": sorted(two_hop),
        "1hop_mean_risk": one_mean,
        "2hop_mean_risk": two_mean,
        "fraud_within_2hops": fraud_within_2,
    }


def section_graph():
    banner("SECTION 6: Graph analysis (account connectivity, fraud rings)")
    print("Transaction-level features see ONE account. Coordinated fraud rings")
    print("share devices, IPs, cards across MANY accounts -- invisible per-tx but")
    print("obvious in the entity graph. GraphSAGE aggregates each node's 1-hop and")
    print("2-hop neighborhood into an embedding; embeddings are pre-computed hourly")
    print("and looked up at serve time (~5ms).")
    print()
    print("  confirmed fraud accounts = %s" % sorted(FRAUD))
    print("  shared-identifier edges:")
    for kind, groups in SHARED.items():
        for gid, members in sorted(groups.items()):
            print("    %-7s %-4s -> %s" % (kind, gid, ",".join(members)))
    print()

    adj = build_adjacency()
    print("  adjacency (who is connected to whom):")
    for a in ACCOUNTS:
        print("    %s -> %s" % (a, ",".join(adj[a]) if adj[a] else "(none)"))
    print()

    print("  GraphSAGE-style aggregation for A1 (the account under review):")
    gf = graph_features("A1", adj)
    print("    1-hop neighbors        = %s" % ",".join(gf["1hop"]))
    print("    2-hop neighbors        = %s" % ",".join(gf["2hop"]))
    print("    1-hop mean risk        = %.4f" % gf["1hop_mean_risk"])
    print("    2-hop mean risk        = %.4f" % gf["2hop_mean_risk"])
    print("    fraud within 2 hops    = %d   <- the ring signal" %
          gf["fraud_within_2hops"])
    print()
    print("  A1 alone is clean (risk 0.10). But A1->A2->A4(fraud) and A1->A3->")
    print("  A5(fraud) via shared card/device. 2 fraud accounts within 2 hops is a")
    print("  strong ring indicator -> boosts P(fraud) on every A1 transaction.")
    print()

    ok = (gf["1hop"] == ["A2", "A3", "A6"] and
          gf["2hop"] == ["A4", "A5", "A7"] and
          abs(gf["1hop_mean_risk"] - 0.3) < 1e-9 and
          abs(gf["2hop_mean_risk"] - 0.6333) < 0.001 and
          gf["fraud_within_2hops"] == 2)
    print("[check] A1 1hop=[A2,A3,A6], 2hop=[A4,A5,A7], fraud2hop=2? " +
          ("OK" if ok else "FAIL"))
    return adj


# ===========================================================================
# SECTION 7 - Scale estimation
# ===========================================================================

def section_scale():
    banner("SECTION 7: Scale estimation")
    tps_avg = 1000
    tps_peak = 5000
    sps = 86400
    bytes_per_tx = 500
    accounts = 10_000_000
    feats_per_account = 50
    bytes_per_feat = 8
    fraud_rate = 0.001

    tx_day = tps_avg * sps
    storage_day = tx_day * bytes_per_tx
    storage_year = storage_day * 365
    fraud_day = tx_day * fraud_rate
    feat_store = accounts * feats_per_account * bytes_per_feat

    print("Assumptions:")
    print("  avg TPS                   = %s /s" % fmt_int(tps_avg))
    print("  peak TPS                  = %s /s  (Visa scale ~24K)" % fmt_int(tps_peak))
    print("  bytes / transaction       = %d (tx row + features + decision)" % bytes_per_tx)
    print("  active accounts           = %s" % fmt_int(accounts))
    print("  features / account        = %d (velocity windows)" % feats_per_account)
    print("  base fraud rate           = %.1f%% (1 in 1000)" % (fraud_rate * 100))
    print()

    print("Throughput:")
    print("  transactions / day        = %s" % fmt_int(tx_day))
    print("  fraud / day               = %s  (~%.1f%%)" %
          (fmt_int(fraud_day), fraud_rate * 100))
    # peak scorer load: each core handles ~8 tx/s at 25ms/tx
    scorer_cores = tps_peak * 0.30 / 8.0
    print("  scorer load at peak       = %.0f tx/s (30%% reach ML) -> ~%.0f scorer-cores"
          % (tps_peak * 0.30, scorer_cores))
    print()

    print("Storage:")
    print("  tx log / day              = %s" % fmt_bytes(storage_day))
    print("  tx log / year             = %s  (archive to S3 Parquet)" %
          fmt_bytes(storage_year))
    print("  feature store (Redis)     = %s  (%s accounts x %d feats x %d B)" %
          (fmt_bytes(feat_store), fmt_int(accounts), feats_per_account, bytes_per_feat))
    print()

    print("Latency budget (p99 < 100ms):")
    print("  rules engine              < 3 ms")
    print("  feature fetch (Redis)     < 5 ms")
    print("  GBDT scorer (CPU)         < 25 ms")
    print("  deep model (borderline)   < 40 ms")
    print("  total (worst case)        < 73 ms  (slack for network/queueing)")
    print()

    ok = (tx_day == 86_400_000 and
          abs(storage_year / 1e12 - 15.768) < 0.01 and
          abs(feat_store / 1e9 - 4.0) < 1e-9 and
          fraud_day == 86_400)
    print("[check] tx/day=86.4M, storage/yr~15.77TB, feature store=4GB, fraud/day=86400? " +
          ("OK" if ok else "FAIL"))


# ===========================================================================
# SECTION 8 - GOLD values pinned for fraud_detection.html
# ===========================================================================

def section_gold(adj, w, b, tau):
    banner("SECTION 8: GOLD values (pinned for fraud_detection.html)")

    # rule engine
    r_teleport = rule_engine({"amount": 1200, "vel_1h": 2, "vel_amt_1h": 2400,
                              "geo_kmh": 2785, "new_device": 1})
    r_coffee = rule_engine({"amount": 45, "vel_1h": 1, "vel_amt_1h": 150,
                            "geo_kmh": 0, "new_device": 0})

    # feature pipeline
    feats = feature_pipeline(USER_HISTORY, CUR_AMOUNT)

    # ML
    p_legit = lr_score(w, b, TRAIN[1])    # dinner
    p_fraud = lr_score(w, b, TRAIN[7])    # impossible travel

    # graph
    gf = graph_features("A1", adj)

    # scale
    tx_day = 1000 * 86400
    storage_year = tx_day * 500 * 365
    feat_store = 10_000_000 * 50 * 8

    gold = [
        ("rule_teleport_decision", r_teleport[0]),
        ("rule_teleport_reasons", ";".join(r_teleport[1])),
        ("rule_coffee_decision", r_coffee[0]),
        ("feat_count_1h", feats["tx_count_1h"]),
        ("feat_sum_1h", round(feats["amount_sum_1h"], 4)),
        ("feat_count_24h", feats["tx_count_24h"]),
        ("feat_avg_30d", round(feats["amount_avg_30d"], 4)),
        ("feat_zscore", round(feats["amount_zscore"], 4)),
        ("lr_lr", LR_LR),
        ("lr_epochs", LR_EPOCHS),
        ("lr_w0_amount", round(w[0], 4)),
        ("lr_w3_geo", round(w[3], 4)),
        ("lr_w6_graph", round(w[6], 4)),
        ("lr_bias", round(b, 4)),
        ("lr_p_legit", round(p_legit, 4)),
        ("lr_p_fraud", round(p_fraud, 4)),
        ("threshold_tau", round(tau, 4)),
        ("c_fn", C_FN),
        ("c_fp", C_FP),
        ("cascade_avg_ms", round(3.0 * 1.0 + 25.0 * 0.3 + 40.0 * 0.02, 4)),
        ("cascade_p99_ms", round(3.0 + 25.0 + 40.0, 4)),
        ("graph_a1_1hop", ",".join(gf["1hop"])),
        ("graph_a1_2hop", ",".join(gf["2hop"])),
        ("graph_a1_1hop_mean", round(gf["1hop_mean_risk"], 4)),
        ("graph_a1_2hop_mean", round(gf["2hop_mean_risk"], 4)),
        ("graph_a1_fraud2hop", gf["fraud_within_2hops"]),
        ("scale_tx_day", tx_day),
        ("scale_storage_year_tb", round(storage_year / 1e12, 3)),
        ("scale_feat_store_gb", round(feat_store / 1e9, 2)),
    ]
    for k, v in gold:
        print("  %-28s = %s" % (k, v))
    print()

    ok = (r_teleport[0] == "BLOCK" and r_coffee[0] == "PASS" and
          feats["tx_count_1h"] == 4 and abs(feats["amount_sum_1h"] - 965.0) < 1e-9 and
          abs(tau - 0.1575) < 0.001 and
          gf["1hop"] == ["A2", "A3", "A6"] and gf["fraud_within_2hops"] == 2 and
          p_legit < 0.15 and p_fraud > 0.85 and
          abs(storage_year / 1e12 - 15.768) < 0.01 and feat_store / 1e9 == 4.0)
    print("[check] GOLD reproduces from rules + features + LR + threshold + graph? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# fraud_detection.py - Real-time fraud detection system simulation")
    print("# Pure Python stdlib only. Numbers below feed FRAUD_DETECTION.md")
    print("# and fraud_detection.html (gold-checked).")

    section_rules()
    section_features()
    w, b = section_ml()
    tau = section_threshold(w, b)
    section_cascade()
    adj = section_graph()
    section_scale()
    section_gold(adj, w, b, tau)
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
