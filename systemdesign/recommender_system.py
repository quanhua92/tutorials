#!/usr/bin/env python3
"""
recommender_system.py - Recommender system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds RECOMMENDER_SYSTEM.md
and is recomputed identically in recommender_system.html (gold-checked).

Core model: MULTI-STAGE FUNNEL + three retriever families.
  Collaborative filtering : item-item cosine over the user-item rating matrix
  Content-based filtering  : item feature vectors -> cosine similarity
  Hybrid                  : weighted blend of CF + content scores
  Cold start              : new user -> popularity; new item -> content-based
  Embedding retrieval     : two-tower dense vectors -> brute kNN vs LSH ANN

The serving funnel (Section 6): 1B items -> 500 -> 100 -> 20 -> final slate,
each stage a progressively more expensive model, all inside a 200ms p99 budget.

Sections:
  1. Collaborative filtering (item-item cosine, rating prediction)
  2. Content-based filtering (item features -> cosine similarity)
  3. Hybrid approach (weighted CF + content scores)
  4. Cold start (new user -> popularity; new item -> content-based)
  5. Embedding-based retrieval (two-tower + brute kNN vs LSH ANN)
  6. Scale estimation (500M DAU, 1B items, index RAM, event storage)
  7. GOLD values pinned for recommender_system.html
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


def norm(a):
    return math.sqrt(sum(x * x for x in a))


def cosine(a, b):
    na, nb = norm(a), norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot(a, b) / (na * nb)


# ---------------------------------------------------------------------------
# dataset — deterministic, reproducible verbatim in JS
# ---------------------------------------------------------------------------
# 6 movies, 6 users. Two clear taste clusters (sci-fi vs comedy) plus a
# "mixed" user (u5) and a denser sci-fi user (u6) so item-item CF has enough
# co-raters (>=2) to produce a reliable similarity graph.
#
# item content features: [scifi, comedy, action, drama]

ITEMS = ["Matrix", "Inception", "Interstellar", "Superbad", "Hangover", "LaLaLand"]

ITEM_FEATURES = {
    "Matrix":      [1, 0, 1, 0],
    "Inception":   [1, 0, 1, 0],
    "Interstellar":[1, 0, 0, 1],
    "Superbad":    [0, 1, 0, 0],
    "Hangover":    [0, 1, 0, 0],
    "LaLaLand":    [0, 0, 0, 1],
}

USERS = ["u1", "u2", "u3", "u4", "u5", "u6"]

# ratings 1-5; missing key = unseen
RATINGS = {
    "u1": {"Matrix": 5, "Inception": 4},
    "u2": {"Matrix": 5, "Inception": 5, "Interstellar": 4},
    "u3": {"Superbad": 5, "Hangover": 4},
    "u4": {"Superbad": 4, "Hangover": 5, "LaLaLand": 3},
    "u5": {"Matrix": 3, "LaLaLand": 5},
    "u6": {"Matrix": 4, "Inception": 5, "Interstellar": 5},
}

MIN_CORATERS = 2   # reliable similarity threshold (kills single-co-rater noise)


def sim_key(a, b):
    """Canonical unordered pair key (alphabetical)."""
    return (a, b) if a <= b else (b, a)


def build_sim_cache():
    """Item-item CF similarities for every pair, keyed by canonical sim_key."""
    cache = {}
    for i in range(len(ITEMS)):
        for j in range(i + 1, len(ITEMS)):
            a, b = ITEMS[i], ITEMS[j]
            cache[sim_key(a, b)] = item_item_cf_sim(a, b)
    return cache


# ---------------------------------------------------------------------------
# SECTION 1 - Collaborative filtering (item-item)
# ---------------------------------------------------------------------------

def item_item_cf_sim(item_a, item_b):
    """Cosine over co-rating users. Returns (similarity, n_coraters)."""
    co = [u for u in USERS if item_a in RATINGS[u] and item_b in RATINGS[u]]
    if not co:
        return 0.0, 0
    va = [RATINGS[u][item_a] for u in co]
    vb = [RATINGS[u][item_b] for u in co]
    return cosine(va, vb), len(co)


def cf_predict(user, item, sim_cache):
    """Predict a user's rating for an item via item-item CF (>=2 co-raters)."""
    num = 0.0
    den = 0.0
    for rated, score in RATINGS[user].items():
        sim, nc = sim_cache[sim_key(item, rated)]
        if nc < MIN_CORATERS:
            continue
        num += sim * score
        den += sim
    if den == 0.0:
        return None
    return num / den


def section_cf():
    banner("SECTION 1: Collaborative filtering (item-item cosine)")
    print("Item-item CF: 'users who liked X also liked Y'. For every item pair")
    print("we cosine the rating VECTORS over their CO-RATING users (those who")
    print("rated both). Pairs with < %d co-raters are dropped as unreliable --" % MIN_CORATERS)
    print("a single co-rater always yields cosine 1.0 (noise).")
    print()

    sim_cache = {}
    print("Item-item similarity matrix (reliable pairs, >= %d co-raters):" % MIN_CORATERS)
    print("  %-13s %-13s %8s %10s" % ("item A", "item B", "cosine", "co-raters"))
    for i in range(len(ITEMS)):
        for j in range(i + 1, len(ITEMS)):
            a, b = ITEMS[i], ITEMS[j]
            sim, nc = item_item_cf_sim(a, b)
            sim_cache[sim_key(a, b)] = (sim, nc)
            mark = "  *" if nc >= MIN_CORATERS else ""
            print("  %-13s %-13s %8.4f %10d%s" % (a, b, sim, nc, mark))
    print("  (* = reliable: >= %d co-raters)" % MIN_CORATERS)
    print()

    user = "u1"
    print("Recommend for %s (rated Matrix=5, Inception=4):" % user)
    print("  %-13s %10s   %s" % ("candidate", "pred(1-5)", "basis"))
    recs = []
    for item in ITEMS:
        if item in RATINGS[user]:
            continue
        pred = cf_predict(user, item, sim_cache)
        if pred is None:
            print("  %-13s %10s   no signal (no reliable neighbor rated it)" % (item, "-"))
        else:
            print("  %-13s %10.2f   neighbor items with >= %d co-raters" %
                  (item, pred, MIN_CORATERS))
            recs.append((item, pred))
    print()

    recs.sort(key=lambda t: -t[1])
    top = recs[0] if recs else None
    print("  CF top pick for %s: %s (predicted %.2f)" %
          (user, top[0], top[1]) if top else "  CF top pick: none")
    print("  NOTE: comedy items (Superbad/Hangover) get NO signal -- no sci-fi")
    print("  fan co-rated them. This is the sparsity problem CF suffers from.")
    print()

    ok = (top is not None and top[0] == "Interstellar" and abs(top[1] - 4.50) < 0.01)
    print("[check] CF recommends Interstellar to u1 at ~4.50? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - Content-based filtering
# ---------------------------------------------------------------------------

def content_predict(user, item):
    """Weighted-avg content-cosine between the candidate and the user's rated items."""
    num = 0.0
    den = 0.0
    for rated, score in RATINGS[user].items():
        sim = cosine(ITEM_FEATURES[item], ITEM_FEATURES[rated])
        num += sim * score
        den += sim
    if den == 0.0:
        return None
    return num / den


def section_content():
    banner("SECTION 2: Content-based filtering (item features -> cosine)")
    print("Each item has a feature vector [scifi, comedy, action, drama].")
    print("Similarity = cosine of feature vectors. A candidate is scored as the")
    print("similarity-weighted average of the user's rated items -- no other")
    print("users needed, so this WORKS for brand-new items (cold start).")
    print()

    print("Item feature matrix:")
    print("  %-13s %s" % ("item", "[scifi comedy action drama]"))
    for item in ITEMS:
        print("  %-13s %s" % (item, ITEM_FEATURES[item]))
    print()

    print("Content-cosine of the two sci-fi seeds:")
    print("  Matrix vs Inception    = %.4f  (identical features)" %
          cosine(ITEM_FEATURES["Matrix"], ITEM_FEATURES["Inception"]))
    print("  Matrix vs Interstellar = %.4f  (share scifi, differ on action/drama)" %
          cosine(ITEM_FEATURES["Matrix"], ITEM_FEATURES["Interstellar"]))
    print("  Matrix vs Superbad     = %.4f  (disjoint genres -> 0)" %
          cosine(ITEM_FEATURES["Matrix"], ITEM_FEATURES["Superbad"]))
    print()

    for user in ("u1", "u5"):
        print("Content-based recs for %s:" % user)
        recs = []
        for item in ITEMS:
            if item in RATINGS[user]:
                continue
            pred = content_predict(user, item)
            if pred is None:
                continue
            recs.append((item, pred))
        recs.sort(key=lambda t: -t[1])
        for item, pred in recs:
            print("  %-13s %8.4f" % (item, pred))
        print("  -> top: %s" % (recs[0][0] if recs else "(none)"))
        print()

    u1_inter = content_predict("u1", "Interstellar")
    u5_inter = content_predict("u5", "Interstellar")
    ok = (abs(u1_inter - 4.5) < 1e-9 and abs(u5_inter - 4.172) < 0.01)
    print("[check] content u1->Interstellar == 4.5 and u5->Interstellar ~4.172? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - Hybrid approach
# ---------------------------------------------------------------------------

def section_hybrid(sim_cache):
    banner("SECTION 3: Hybrid approach (weighted CF + content)")
    print("Blends a COLLABORATIVE signal (what similar users did) with a CONTENT")
    print("signal (what the items are made of). CF captures taste clusters;")
    print("content rescues the sparsity / cold-start holes. Weight w in [0,1].")
    print("  hybrid = w * CF_pred + (1 - w) * content_pred")
    print()

    user = "u5"
    item = "Interstellar"
    cf = cf_predict(user, item, sim_cache)
    cb = content_predict(user, item)
    print("Case: %s -> %s (u5 rated Matrix=3, LaLaLand=5):" % (user, item))
    print("  CF      pred = %.4f   (sci-fi neighbors, pulled DOWN by u5's Matrix=3)" % cf)
    print("  Content pred = %.4f   (Interstellar shares drama with LaLaLand=5)" % cb)
    print("  w=0.5 hybrid  = %.4f" % (0.5 * cf + 0.5 * cb))
    print("  w=0.7 (CF-heavy)= %.4f" % (0.7 * cf + 0.3 * cb))
    print("  w=0.3 (content-heavy)= %.4f" % (0.3 * cf + 0.7 * cb))
    print("  Production default w~0.5; tune offline on NDCG@10, ship the winner.")
    print()

    hybrid = 0.5 * cf + 0.5 * cb
    ok = (abs(cf - 3.0) < 1e-9 and abs(cb - 4.172) < 0.01 and abs(hybrid - 3.586) < 0.01)
    print("[check] u5->Interstellar CF=3.0, content~4.172, hybrid(0.5)~3.586? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Cold start
# ---------------------------------------------------------------------------

def section_coldstart():
    banner("SECTION 4: Cold start (new user / new item)")
    print("CF needs interaction history, so it CANNOT serve a brand-new user or")
    print("item. The fallbacks:")
    print("  NEW USER -> popularity ranking (most-rated / highest-sum items).")
    print("  NEW ITEM -> content-based: find existing items with similar features")
    print("              and inherit their audience until interactions accumulate.")
    print()

    # new user: popularity
    print("NEW USER fallback -- popularity (by rating count, then sum):")
    pop = []
    for item in ITEMS:
        raters = [u for u in USERS if item in RATINGS[u]]
        cnt = len(raters)
        ssum = sum(RATINGS[u][item] for u in raters)
        pop.append((item, cnt, ssum))
    pop.sort(key=lambda t: (-t[1], -t[2]))
    print("  %-13s %8s %8s" % ("item", "count", "sum"))
    for item, cnt, ssum in pop:
        print("  %-13s %8d %8d" % (item, cnt, ssum))
    print("  -> recommend %s first (most-rated), then %s." % (pop[0][0], pop[1][0]))
    print("  GOTCHA: pure popularity concentrates on a few hits -> feedback loop.")
    print()

    # new item: content-based
    new_item = "Dune"
    new_feat = [1, 0, 1, 0]
    print("NEW ITEM fallback -- '%s' features %s (scifi+action):" % (new_item, new_feat))
    nbrs = []
    for item in ITEMS:
        s = cosine(new_feat, ITEM_FEATURES[item])
        nbrs.append((item, s))
    nbrs.sort(key=lambda t: -t[1])
    print("  nearest existing items by content-cosine:")
    for item, s in nbrs[:3]:
        print("    %-13s %.4f" % (item, s))
    audience = []
    for item, s in nbrs:
        if s < 0.999:
            continue
        for u in USERS:
            if item in RATINGS[u] and RATINGS[u][item] >= 4 and u not in audience:
                audience.append(u)
    print("  -> inherit audience of near-duplicates (sim>=1.0): %s" %
          ",".join(audience))
    print("  As clicks on Dune accumulate, CF takes over within hours/days.")
    print()

    ok = (pop[0][0] == "Matrix" and pop[0][1] == 4 and
          nbrs[0][0] == "Matrix" and abs(nbrs[0][1] - 1.0) < 1e-9 and
          audience == ["u1", "u2", "u6"])
    print("[check] new-user top=Matrix(4) and Dune inherits u1,u2,u6? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Embedding-based retrieval (two-tower + ANN)
# ---------------------------------------------------------------------------

# dense "learned" two-tower embeddings (8 items, 4-dim) -- distinct from the
# binary content features, to model a real retrieval index. Deterministic.
ITEM_EMBS = {
    "i1": [0.80, 0.10, 0.75, 0.05],
    "i2": [0.75, 0.20, 0.80, 0.10],
    "i3": [0.70, 0.05, 0.65, 0.30],
    "i4": [0.85, 0.15, 0.70, 0.08],
    "i5": [0.10, 0.85, 0.20, 0.05],
    "i6": [0.15, 0.80, 0.10, 0.10],
    "i7": [0.05, 0.90, 0.15, 0.02],
    "i8": [0.30, 0.30, 0.30, 0.85],
}
QUERY_EMB = [0.82, 0.12, 0.78, 0.06]
LSH_PLANES = [
    [1.0, -1.0, 0.5, -0.5],
    [0.5, 0.5, -1.0, -0.5],
]


def lsh_bucket(vec, planes):
    bits = []
    for p in planes:
        bits.append(1 if dot(vec, p) >= 0 else 0)
    return "".join(str(b) for b in bits)


def section_embeddings():
    banner("SECTION 5: Embedding-based retrieval (two-tower + ANN)")
    print("Two-tower retrieval: a USER tower and an ITEM tower each map their")
    print("inputs to a shared dense embedding space. Score(u, i) = cosine of the")
    print("two embeddings. Item embeddings are PRECOMPUTED offline and indexed;")
    print("retrieval = nearest-neighbor lookup in that index (sub-50ms @ 1B items).")
    print()
    print("Item embeddings (4-dim, deterministic):")
    for k, v in ITEM_EMBS.items():
        print("  %s %s" % (k, v))
    print("  query (user tower) = %s" % QUERY_EMB)
    print()

    # brute-force kNN
    scores = [(k, cosine(QUERY_EMB, v)) for k, v in ITEM_EMBS.items()]
    scores.sort(key=lambda t: -t[1])
    K = 3
    brute_top = scores[:K]
    print("Brute-force kNN (K=%d) -- exact, O(N):" % K)
    for k, s in scores:
        in_top = "  <-- top-%d" % K if (k, s) in brute_top else ""
        print("  %s %.4f%s" % (k, s, in_top))
    brute_ids = [k for k, _ in brute_top]
    print("  brute top-%d = %s" % (K, ",".join(brute_ids)))
    print()

    # LSH ANN
    q_bucket = lsh_bucket(QUERY_EMB, LSH_PLANES)
    buckets = {}
    for k, v in ITEM_EMBS.items():
        b = lsh_bucket(v, LSH_PLANES)
        buckets.setdefault(b, []).append(k)
    print("LSH ANN -- 2 random-projection planes -> 4 buckets (approximate, O(1)):")
    print("  query bucket = '%s'" % q_bucket)
    for b in sorted(buckets):
        mark = "  <-- query bucket" if b == q_bucket else ""
        print("  bucket '%s': %s%s" % (b, ",".join(buckets[b]), mark))
    ann_hits = buckets.get(q_bucket, [])
    overlap = [k for k in brute_ids if k in ann_hits]
    recall = len(overlap) / float(K)
    extras = [k for k in ann_hits if k not in brute_ids]
    print("  ANN retrieved = %s" % ",".join(ann_hits))
    print("  recall@%d = %d/%d = %.4f" % (K, len(overlap), K, recall))
    if extras:
        print("  bucket also returned %s -- false positive(s), rank %d+ by brute." %
              (",".join(extras), K + 1))
        print("  The light/heavy rankers discard these. This is WHY retrieval")
        print("  over-fetches (500) and rankers filter: optimize recall, then")
        print("  precision. At billion-item scale, boundary items straddle planes")
        print("  and recall drops; use multi-table LSH (L tables, union of buckets)")
        print("  + multi-probe to push recall back toward 1.0.")
    else:
        print("  no false positives in bucket this round.")
    print()

    print("Retrieval funnel at scale (serving path):")
    funnel = [("catalog", 1_000_000_000), ("retrieval (ANN)", 500),
              ("light rank (GBDT)", 100), ("heavy rank (DNN)", 20),
              ("final slate", 20)]
    for i in range(len(funnel) - 1):
        n_from, n_to = funnel[i][1], funnel[i + 1][1]
        ratio = n_to / n_from * 100.0
        print("  %-22s %s -> %s  (%.7f%%)" %
              (funnel[i][0] + ":", fmt_int(n_from), fmt_int(n_to), ratio))
    print("  Each stage is a MORE EXPENSIVE model on FEWER candidates.")
    print()

    ok = (brute_ids[0] == "i1" and abs(brute_top[0][1] - 0.9998) < 0.001 and
          q_bucket == "10" and abs(recall - 1.0) < 1e-9)
    print("[check] brute top-1=i1, query bucket=10, recall@3=1.0? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 6: Scale estimation")
    dau = 500_000_000
    catalog = 1_000_000_000
    peak_qps = 10_000
    events_per_user_day = 20
    emb_dim = 128
    sps = 86_400

    events_day = dau * events_per_user_day
    write_qps = events_day / sps
    events_year = events_day * 365
    storage_year = events_year * 100          # ~100 B / event row

    raw_item_index = catalog * emb_dim * 4    # float32
    pq_item_index = catalog * 8               # product quantization, 8 B/item
    user_emb_store = dau * emb_dim * 4

    print("Assumptions:")
    print("  daily active users         = %s" % fmt_int(dau))
    print("  catalog size               = %s items" % fmt_int(catalog))
    print("  peak rec requests          = %s /s (cache-aided)" % fmt_int(peak_qps))
    print("  interaction events/user/day= %d (clicks, watches, skips)" % events_per_user_day)
    print("  embedding dimension        = %d" % emb_dim)
    print()

    print("Throughput:")
    print("  read  QPS peak             = %s /s  (recommendations, cache-aided)" % fmt_int(peak_qps))
    print("  write QPS avg (events)     = %s /s  (%s events/day)" %
          (fmt_int(int(write_qps)), fmt_int(events_day)))
    print("  read:write ratio           = ~1 : %d  (write-heavy event log)" %
          round(events_day / (peak_qps * sps)))
    print()

    print("Embedding index RAM (FAISS IVF + PQ):")
    print("  raw float32 item vectors   = %s   (untenable in RAM)" % fmt_bytes(raw_item_index))
    print("  PQ-compressed item index   = %s   (8 B/item, fits one node)" % fmt_bytes(pq_item_index))
    print("  user embedding store       = %s   (offline features, daily refresh)" % fmt_bytes(user_emb_store))
    print()

    print("Event storage (~100 B / row):")
    print("  events / year              = %s (%.2f T)" % (fmt_int(events_year), events_year / 1e12))
    print("  storage / year             = %s  (archive to S3 Parquet)" % fmt_bytes(storage_year))
    print()

    print("Latency budget (p99 < 200ms):")
    print("  retrieval (ANN)            < 50 ms")
    print("  light ranker (GBDT)        < 20 ms")
    print("  heavy ranker (DNN, GPU)    < 70 ms")
    print("  re-ranking + rules         < 10 ms")
    print("  total                      < 150 ms  (slack for network/queueing)")
    print()

    ok = (dau == 500_000_000 and catalog == 1_000_000_000 and
          abs(pq_item_index / 1e9 - 8.0) < 1e-9 and
          abs(raw_item_index / 1e9 - 512.0) < 1e-9 and
          abs(user_emb_store / 1e9 - 256.0) < 1e-9)
    print("[check] PQ index=8GB, raw=512GB, user emb=256GB? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for recommender_system.html
# ---------------------------------------------------------------------------

def section_gold():
    banner("SECTION 7: GOLD values (pinned for recommender_system.html)")

    # rebuild CF sims
    sim_cache = build_sim_cache()

    cf_u1_inter = cf_predict("u1", "Interstellar", sim_cache)
    cf_u5_inter = cf_predict("u5", "Interstellar", sim_cache)
    cb_u1_inter = content_predict("u1", "Interstellar")
    cb_u5_inter = content_predict("u5", "Interstellar")
    hybrid_u5 = 0.5 * cf_u5_inter + 0.5 * cb_u5_inter

    # CF item-item reliable sims
    sim_matrix_inception = sim_cache[sim_key("Inception", "Matrix")][0]
    sim_superbad_hangover = sim_cache[sim_key("Hangover", "Superbad")][0]

    # popularity
    pop_counts = {item: sum(1 for u in USERS if item in RATINGS[u]) for item in ITEMS}
    pop_top = max(pop_counts, key=lambda it: (pop_counts[it], -ITEMS.index(it)))

    # new item Dune audience
    dune_feat = [1, 0, 1, 0]
    dune_nearest = max(ITEMS, key=lambda it: cosine(dune_feat, ITEM_FEATURES[it]))
    dune_audience = []
    for u in USERS:
        if cosine(dune_feat, ITEM_FEATURES["Matrix"]) >= 0.999 and \
           "Matrix" in RATINGS[u] and RATINGS[u]["Matrix"] >= 4 and u not in dune_audience:
            dune_audience.append(u)

    # embeddings
    emb_scores = [(k, cosine(QUERY_EMB, v)) for k, v in ITEM_EMBS.items()]
    emb_scores.sort(key=lambda t: -t[1])
    brute_top3 = ",".join(k for k, _ in emb_scores[:3])
    brute_top1_score = emb_scores[0][1]
    q_bucket = lsh_bucket(QUERY_EMB, LSH_PLANES)
    ann_bucket = []
    for k, v in ITEM_EMBS.items():
        if lsh_bucket(v, LSH_PLANES) == q_bucket:
            ann_bucket.append(k)
    overlap = [k for k, _ in emb_scores[:3] if k in ann_bucket]
    recall3 = len(overlap) / 3.0

    # scale
    pq_gb = 1_000_000_000 * 8 / 1e9
    raw_gb = 1_000_000_000 * 128 * 4 / 1e9
    user_gb = 500_000_000 * 128 * 4 / 1e9
    events_year_t = 500_000_000 * 20 * 365 / 1e12

    gold = [
        ("cf_u1_inter_pred",      round(cf_u1_inter, 2)),
        ("cf_u5_inter_pred",      round(cf_u5_inter, 2)),
        ("content_u1_inter",      round(cb_u1_inter, 2)),
        ("content_u5_inter",      round(cb_u5_inter, 3)),
        ("hybrid_u5_inter_w05",   round(hybrid_u5, 3)),
        ("cf_sim_matrix_inception", round(sim_matrix_inception, 4)),
        ("cf_sim_superbad_hangover", round(sim_superbad_hangover, 4)),
        ("popularity_top_item",   pop_top),
        ("popularity_matrix_count", pop_counts["Matrix"]),
        ("cold_item_dune_nearest", dune_nearest),
        ("cold_item_dune_audience", ",".join(dune_audience)),
        ("emb_brute_top3",        brute_top3),
        ("emb_brute_top1",        emb_scores[0][0]),
        ("emb_brute_top1_score",  round(brute_top1_score, 4)),
        ("emb_lsh_query_bucket",  q_bucket),
        ("emb_lsh_ann_bucket",    ",".join(ann_bucket)),
        ("emb_recall_at_3",       round(recall3, 4)),
        ("scale_pq_index_gb",     round(pq_gb, 2)),
        ("scale_raw_index_gb",    round(raw_gb, 2)),
        ("scale_user_emb_gb",     round(user_gb, 2)),
        ("scale_events_year_t",   round(events_year_t, 2)),
    ]
    for k, v in gold:
        print("  %-26s = %s" % (k, v))
    print()

    ok = (round(cf_u1_inter, 2) == 4.50 and
          round(cb_u1_inter, 2) == 4.50 and
          round(hybrid_u5, 3) == 3.586 and
          round(sim_matrix_inception, 4) == 0.9848 and
          pop_top == "Matrix" and
          dune_audience == ["u1", "u2", "u6"] and
          emb_scores[0][0] == "i1" and
          round(brute_top1_score, 4) == 0.9998 and
          q_bucket == "10" and
          round(recall3, 4) == 1.0 and
          round(pq_gb, 2) == 8.0 and
          round(raw_gb, 2) == 512.0 and
          round(user_gb, 2) == 256.0)
    print("[check] GOLD reproduces from CF + content + embedding formulas? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# recommender_system.py - Recommender system design simulation")
    print("# Pure Python stdlib only. Numbers below feed RECOMMENDER_SYSTEM.md")
    print("# and recommender_system.html (gold-checked).")

    sim_cache = build_sim_cache()

    section_cf()
    section_content()
    section_hybrid(sim_cache)
    section_coldstart()
    section_embeddings()
    section_scale()
    section_gold()
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
