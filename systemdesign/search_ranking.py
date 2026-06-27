#!/usr/bin/env python3
"""
search_ranking.py - Search ranking system design simulation (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds SEARCH_RANKING.md
and is recomputed identically in search_ranking.html (gold-checked).

Core model: MULTI-STAGE RANKING PIPELINE built on the inverted index.
  Inverted index  : term -> postings [(doc_id, tf)], the data structure that
                    makes sub-50ms retrieval possible at 100M+ docs.
  TF-IDF          : the vector-space baseline. tf * log(N/df). Ties docs that
                    share the same term frequencies -- blind to length.
  BM25            : the production lexical ranker. Adds term-frequency
                    saturation (k1) and document-length normalization (b) so a
                    short focused doc beats a long rambling one. Breaks TF-IDF
                    ties by penalizing long documents.
  Query expansion : dictionary synonym + pseudo-relevance feedback (Rocchio).
                    Surfaces semantically related docs the literal query misses.
  Learning-to-rank: feature-based linear ranker (BM25 + clicks + CTR +
                    freshness + title-match). Optimizes NDCG, not just match.
  Evaluation      : NDCG@k with graded (2^rel - 1) gain.

Sections:
  1. Inverted index construction (postings, df, document lengths, avgdl)
  2. TF-IDF computation (vector-space baseline; the tie problem)
  3. BM25 scoring (k1 saturation + b length normalization; breaks the tie)
  4. Query expansion (dictionary synonym + Rocchio pseudo-relevance feedback)
  5. Learning-to-rank (feature matrix + linear model + NDCG lift over BM25)
  6. Scale estimation (100M docs, inverted index RAM, ANN, latency budget)
  7. GOLD values pinned for search_ranking.html
"""

import math
import re

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


# ---------------------------------------------------------------------------
# dataset - deterministic, reproducible verbatim in JS
# ---------------------------------------------------------------------------
# 6 short tech docs. The index is built over the BODY only (classic IR); the
# TITLE is consumed separately as the f_exact learning-to-rank feature. Two
# topical clusters (machine-learning docs d1/d2/d3, database docs d4/d5) plus
# a "search" doc d6 that shares the term "learning" with the ML cluster. That
# overlap is what makes ranking HARD: d6 matches the query "machine learning"
# on the term "learning" but is not actually about ML -- the classic lexical
# false friend that learning-to-rank must overcome.
#
# Body lengths are deliberately staggered (d1/d3 = 5 tokens, d2/d4/d6 = 4,
# d5 = 5) so BM25's length normalization visibly breaks the TF-IDF ties AND
# visibly makes one wrong call (it ranks the short off-topic d6 above the
# longer on-topic d3) -- the blind spot LTR corrects.

DOCS = [
    {"id": "d1", "title": "Machine Learning Intro",
     "body": "machine learning model training algorithm"},
    {"id": "d2", "title": "Neural Network Learning",
     "body": "machine learning neural network"},
    {"id": "d3", "title": "Deep Network Training",
     "body": "deep learning neural network training"},
    {"id": "d4", "title": "Database Indexing",
     "body": "database query optimization index"},
    {"id": "d5", "title": "Query Tuning",
     "body": "database index query performance tuning"},
    {"id": "d6", "title": "Search Ranking",
     "body": "web search ranking learning"},
]

DOC_IDS = [d["id"] for d in DOCS]

# behavioral / business features for the learning-to-rank section. These are
# the signals BM25 cannot see: what users clicked, how fresh the doc is, its
# historical CTR. Title-match is derived from the title field.
CLICKS = {"d1": 520, "d2": 480, "d3": 350, "d4": 5, "d5": 3, "d6": 40}
CTR = {"d1": 0.32, "d2": 0.28, "d3": 0.22, "d4": 0.01, "d5": 0.01, "d6": 0.04}
FRESHNESS = {"d1": 0.95, "d2": 0.70, "d3": 0.40, "d4": 0.10, "d5": 0.20, "d6": 0.85}

# human relevance judgments (graded 0-4) for query "machine learning".
JUDGMENTS = {"d1": 4, "d2": 4, "d3": 3, "d4": 0, "d5": 0, "d6": 1}

# synonym dictionary for query expansion (mirrors how a controlled vocabulary
# or a learned expansion like SPLADE broadens a literal query).
EXPANSIONS = {
    "learning": ["deep", "neural", "training"],
    "machine": ["model", "algorithm"],
    "search": ["ranking", "relevance"],
}

BM25_K1 = 1.2
BM25_B = 0.75


def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


# ---------------------------------------------------------------------------
# index construction (BODY ONLY -- title is an LTR feature, not indexed text)
# ---------------------------------------------------------------------------

def build_index(docs):
    """Return (postings, doc_len, df, N, avgdl).

    postings[term][doc_id] = term frequency in that doc's body
    doc_len[doc_id]        = body token count (for BM25 length norm)
    df[term]               = number of docs whose body contains the term
    """
    postings = {}
    doc_len = {}
    df = {}
    for d in docs:
        toks = tokenize(d["body"])
        doc_len[d["id"]] = len(toks)
        seen = set()
        for t in toks:
            postings.setdefault(t, {})
            postings[t][d["id"]] = postings[t].get(d["id"], 0) + 1
            seen.add(t)
        for t in seen:
            df[t] = df.get(t, 0) + 1
    N = len(docs)
    avgdl = sum(doc_len.values()) / float(N)
    return postings, doc_len, df, N, avgdl


# ---------------------------------------------------------------------------
# scoring formulas
# ---------------------------------------------------------------------------

def idf_tfidf(term, df, N):
    """Classic vector-space IDF: log(N / df). Zero when a term is in every doc."""
    if df.get(term, 0) == 0:
        return 0.0
    return math.log(N / float(df[term]))


def idf_bm25(term, df, N):
    """BM25 IDF (Lucene form): log(1 + (N - df + 0.5) / (df + 0.5)). Always > 0."""
    if df.get(term, 0) == 0:
        return 0.0
    return math.log(1.0 + (N - df[term] + 0.5) / (df[term] + 0.5))


def tfidf_score(query, doc_id, postings, df, N):
    """Sum of tf * idf over query terms present in the doc (raw tf, no length norm)."""
    score = 0.0
    for term in set(tokenize(query)):
        tf = postings.get(term, {}).get(doc_id, 0)
        if tf == 0:
            continue
        score += tf * idf_tfidf(term, df, N)
    return score


def bm25_score(query, doc_id, postings, df, N, doc_len, avgdl,
               k1=BM25_K1, b=BM25_B):
    """BM25: sum over query terms of idf * (tf*(k1+1)) / (tf + k1*(1-b + b*dl/avgdl))."""
    score = 0.0
    dl = doc_len[doc_id]
    for term in set(tokenize(query)):
        tf = postings.get(term, {}).get(doc_id, 0)
        if tf == 0:
            continue
        idf = idf_bm25(term, df, N)
        denom = tf + k1 * (1.0 - b + b * dl / avgdl)
        score += idf * (tf * (k1 + 1.0)) / denom
    return score


def rank_by(query, scorer, index, topn=None):
    """Score every doc, drop zeros, sort desc (tie-break by doc id)."""
    postings, doc_len, df, N, avgdl = index
    scored = []
    for did in DOC_IDS:
        if scorer is bm25_score:
            s = scorer(query, did, postings, df, N, doc_len, avgdl)
        else:
            s = scorer(query, did, postings, df, N)
        if s > 1e-12:
            scored.append((did, s))
    scored.sort(key=lambda t: (-t[1], t[0]))
    if topn is not None:
        scored = scored[:topn]
    return scored


# ---------------------------------------------------------------------------
# evaluation - NDCG@k with graded exponential gain (2^rel - 1)
# ---------------------------------------------------------------------------

def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(ranked_doc_ids, judgments, k):
    gains = [(2 ** judgments[d] - 1) for d in ranked_doc_ids[:k]]
    ideal = sorted(judgments.values(), reverse=True)[:k]
    ideal_gains = [(2 ** g - 1) for g in ideal]
    idcg = dcg(ideal_gains)
    if idcg == 0:
        return 0.0
    return dcg(gains) / idcg


# ---------------------------------------------------------------------------
# SECTION 1 - Inverted index
# ---------------------------------------------------------------------------

def section_index(index):
    banner("SECTION 1: Inverted index (postings, df, document lengths)")
    postings, doc_len, df, N, avgdl = index
    print("The inverted index maps each TERM to its POSTING LIST: the docs whose")
    print("body contains it and the term frequency. Retrieval = walk a few posting")
    print("lists and merge -- O(matches), NOT O(corpus). This is why BM25 over")
    print("100M docs finishes in <50ms: it never scans a doc that lacks the term.")
    print()
    print("Corpus (%d docs, body tokenized; title kept aside as a ranker feature):" % N)
    for d in DOCS:
        print("  %s  %-26s len=%2d  \"%s\"" %
              (d["id"], "(" + d["title"] + ")", doc_len[d["id"]], d["body"]))
    print()
    print("avgdl = %.4f tokens" % avgdl)
    print()

    print("Posting lists (term -> doc:tf), df in brackets:")
    for term in sorted(df):
        plist = postings[term]
        cells = ["%s:%d" % (d, plist[d]) for d in DOC_IDS if d in plist]
        print("  %-13s df=%d  [%s]" % (term, df[term], ", ".join(cells)))
    print()

    q = "machine learning"
    print("Multi-term query '%s' -> merge posting lists:" % q)
    inter = set(postings.get("machine", {}).keys()) & set(postings.get("learning", {}).keys())
    union = set(postings.get("machine", {}).keys()) | set(postings.get("learning", {}).keys())
    print("  machine postings  = {%s}" % ", ".join(sorted(postings["machine"].keys())))
    print("  learning postings = {%s}" % ", ".join(sorted(postings["learning"].keys())))
    print("  intersection (AND)= {%s}   -- exact-match candidates" %
          ", ".join(sorted(inter)))
    print("  union (OR)        = {%s}   -- scored, zeros dropped" %
          ", ".join(sorted(union)))
    print()

    ok = (abs(avgdl - 4.5) < 1e-9 and
          df["machine"] == 2 and df["learning"] == 4 and
          postings["learning"]["d6"] == 1 and
          inter == {"d1", "d2"})
    print("[check] avgdl=4.5, df(machine)=2, df(learning)=4, AND={d1,d2}? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 2 - TF-IDF
# ---------------------------------------------------------------------------

def section_tfidf(index):
    banner("SECTION 2: TF-IDF (vector-space baseline -- the tie problem)")
    postings, doc_len, df, N, avgdl = index
    print("TF-IDF = tf * log(N/df). A term common to every doc gets idf 0 (useless);")
    print("a rare term gets a high idf. Score = sum over query terms of tf*idf.")
    print("NO document-length normalization -> two docs with the same term")
    print("frequencies score IDENTICALLY, regardless of total length. That tie is")
    print("the problem BM25 fixes.")
    print()

    q = "machine learning"
    print("Query: '%s'" % q)
    print("  idf(machine)  = log(%d/%d) = %.4f" %
          (N, df["machine"], idf_tfidf("machine", df, N)))
    print("  idf(learning) = log(%d/%d) = %.4f" %
          (N, df["learning"], idf_tfidf("learning", df, N)))
    print()
    print("  %-5s %10s   %s" % ("doc", "tfidf", "terms matched"))
    ranked = rank_by(q, tfidf_score, index)
    by_doc = dict(ranked)
    for did in DOC_IDS:
        s = by_doc.get(did, 0.0)
        if s <= 1e-12:
            continue
        matched = [t for t in tokenize(q) if postings.get(t, {}).get(did, 0) > 0]
        print("  %-5s %10.4f   {%s}" % (did, s, ", ".join(matched)))
    print()

    s_d1 = tfidf_score(q, "d1", postings, df, N)
    s_d2 = tfidf_score(q, "d2", postings, df, N)
    s_d3 = tfidf_score(q, "d3", postings, df, N)
    s_d6 = tfidf_score(q, "d6", postings, df, N)
    print("  TIE: d1=%.4f == d2=%.4f  (both tf=1 for machine & learning)." % (s_d1, s_d2))
    print("  TIE: d3=%.4f == d6=%.4f  (both match only 'learning', tf=1)." % (s_d3, s_d6))
    print("  TF-IDF cannot tell the verbose d1 from the terse d2, nor the on-topic")
    print("  d3 from the off-topic 'search' doc d6. Enter BM25.")
    print()

    ok = (abs(s_d1 - s_d2) < 1e-9 and abs(s_d3 - s_d6) < 1e-9 and
          abs(s_d1 - 1.5041) < 0.001 and abs(s_d3 - 0.4055) < 0.001 and
          ranked[0][0] == "d1")
    print("[check] d1==d2~1.5041 (tie), d3==d6~0.4055 (tie), top=d1? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 3 - BM25
# ---------------------------------------------------------------------------

def section_bm25(index):
    banner("SECTION 3: BM25 (k1 saturation + b length normalization)")
    postings, doc_len, df, N, avgdl = index
    print("BM25 fixes TF-IDF's ties with two knobs:")
    print("  k1=%.1f  term-frequency SATURATION: extra occurrences of a term add" % BM25_K1)
    print("           diminishing score (tf*(k1+1)/(tf+k1...)). Caps keyword stuffing.")
    print("  b =%.2f document-length NORMALIZATION: long docs are penalized because" % BM25_B)
    print("           a match there is less specific (b*dl/avgdl in the denominator).")
    print()
    print("  idf_bm25(machine)  = log(1+(%d-%d+0.5)/(%d+0.5)) = %.4f" %
          (N, df["machine"], df["machine"], idf_bm25("machine", df, N)))
    print("  idf_bm25(learning) = log(1+(%d-%d+0.5)/(%d+0.5)) = %.4f" %
          (N, df["learning"], df["learning"], idf_bm25("learning", df, N)))
    print()

    q = "machine learning"
    print("Query: '%s'   (same query that TIED under TF-IDF)" % q)
    print("  %-5s %6s %8s %8s   %s" % ("doc", "len", "bm25", "tfidf", "note"))
    bm = rank_by(q, bm25_score, index)
    tf_map = dict(rank_by(q, tfidf_score, index))
    notes = {
        "d2": "shortest ML doc (4 tok) -> WINS the d1/d2 tie",
        "d1": "verbose (5 tok) -> demoted below shorter d2",
        "d6": "'learning' only; short -> beats on-topic d3 (!)",
        "d3": "on-topic but longer -> demoted below d6",
    }
    for did, s in bm:
        print("  %-5s %6d %8.4f %8.4f   %s" %
              (did, doc_len[did], s, tf_map.get(did, 0.0), notes.get(did, "")))
    print()

    s_d1 = bm25_score(q, "d1", postings, df, N, doc_len, avgdl)
    s_d2 = bm25_score(q, "d2", postings, df, N, doc_len, avgdl)
    s_d6 = bm25_score(q, "d6", postings, df, N, doc_len, avgdl)
    s_d3 = bm25_score(q, "d3", postings, df, N, doc_len, avgdl)
    order = ",".join(d for d, _ in bm)
    print("  BM25 BREAKS both TF-IDF ties:")
    print("    d2=%.4f > d1=%.4f  (d2 is shorter -> length norm favors it)" % (s_d2, s_d1))
    print("    d6=%.4f > d3=%.4f  (d6 shorter, but d3 is MORE relevant -- a BM25" % (s_d6, s_d3))
    print("    blind spot: pure lexical length-norm promotes the wrong doc here).")
    print("  That blind spot is exactly what learning-to-rank corrects (Section 5).")
    print()

    ok = (s_d2 > s_d1 and s_d6 > s_d3 and order == "d2,d1,d6,d3" and
          abs(s_d2 - 1.5415) < 0.01 and abs(s_d1 - 1.4074) < 0.01)
    print("[check] bm25 d2>d1 (~1.54>1.41), d6>d3, order=d2,d1,d6,d3? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 4 - Query expansion
# ---------------------------------------------------------------------------

def expand_query(query, index, top_k=2):
    """Dictionary expansion + Rocchio pseudo-relevance feedback.

    Returns (expanded_terms, prf_terms [(term, weight)], dict_terms).
    """
    postings, doc_len, df, N, avgdl = index
    base = set(tokenize(query))

    # (a) dictionary synonym expansion (preserve insertion order)
    dict_terms = []
    for t in tokenize(query):
        for syn in EXPANSIONS.get(t, []):
            if syn not in base and syn not in dict_terms and syn in df:
                dict_terms.append(syn)

    # (b) Rocchio PRF: from BM25 top-k docs, rank remaining terms by
    #     sum(doc_bm25 * tf * idf_tfidf).
    bm = rank_by(query, bm25_score, index, topn=top_k)
    prf = {}
    for did, dscore in bm:
        for term, tfs in postings.items():
            if term in base:
                continue
            if did in tfs:
                w = dscore * tfs[did] * idf_tfidf(term, df, N)
                prf[term] = prf.get(term, 0.0) + w
    prf_terms = sorted(prf.items(), key=lambda kv: (-kv[1], kv[0]))

    expanded = list(tokenize(query)) + dict_terms
    return expanded, prf_terms, dict_terms


def section_expansion(index):
    banner("SECTION 4: Query expansion (dictionary + pseudo-relevance feedback)")
    postings, doc_len, df, N, avgdl = index
    print("A literal query misses semantically related docs. Two expansion tactics:")
    print("  (a) DICTIONARY: 'learning' -> [deep, neural, training] (a curated or")
    print("      learned synonym map; SPLADE learns this from data).")
    print("  (b) PRF (Rocchio): take BM25 top-k docs, pull their top idf-weighted")
    print("      terms. The corpus itself suggests what to add.")
    print()

    q = "machine learning"
    expanded, prf_terms, dict_terms = expand_query(q, index)
    print("Query: '%s'" % q)
    print("  dictionary expansion -> +%s" % dict_terms)
    print("  PRF (top-2 docs %s) term weights:" %
          ",".join(d for d, _ in rank_by(q, bm25_score, index, topn=2)))
    for term, w in prf_terms[:5]:
        print("    %-12s %.4f" % (term, w))
    print("  -> expanded query: '%s'" % " ".join(expanded))
    print()

    before = rank_by(q, bm25_score, index)
    after = rank_by(" ".join(expanded), bm25_score, index)
    before_ids = [d for d, _ in before]
    after_ids = [d for d, _ in after]
    print("Ranking BEFORE vs AFTER expansion:")
    print("  %-10s %s" % ("before", ", ".join("%s(%.2f)" % (d, s) for d, s in before)))
    print("  %-10s %s" % ("after", ", ".join("%s(%.2f)" % (d, s) for d, s in after)))
    print()

    d3_before = dict(before).get("d3", 0.0)
    d3_after = dict(after).get("d3", 0.0)
    d3_rank_before = before_ids.index("d3") + 1
    d3_rank_after = after_ids.index("d3") + 1
    print("  d3 ('deep learning neural network training') was rank %d (score %.4f);" %
          (d3_rank_before, d3_before))
    print("  after expansion it jumps to rank %d (score %.4f) -- the added terms" %
          (d3_rank_after, d3_after))
    print("  'deep/neural/training' match d3 exactly. Expansion bridges the lexical")
    print("  gap between 'machine learning' and the deep-network cluster.")
    print()

    ok = ("deep" in expanded and "neural" in expanded and "training" in expanded and
          d3_rank_after < d3_rank_before and d3_after > d3_before)
    print("[check] expanded adds deep/neural/training, d3 rank %d->%d? " %
          (d3_rank_before, d3_rank_after) + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 5 - Learning to rank
# ---------------------------------------------------------------------------

def title_match(query, doc):
    """1 if any query term appears in the doc title, else 0."""
    qterms = set(tokenize(query))
    tterms = set(tokenize(doc["title"]))
    return 1 if qterms & tterms else 0


def build_features(query, candidates, index):
    """Build the (doc -> feature dict) matrix for LTR.

    f_bm25 and f_click are min-max normalized over the candidate set so the
    linear weights are directly comparable; f_ctr/f_fresh are already ~[0,1];
    f_exact is {0,1}.
    """
    postings, doc_len, df, N, avgdl = index
    raw = {}
    for did in candidates:
        doc = next(d for d in DOCS if d["id"] == did)
        raw[did] = {
            "f_bm25": bm25_score(query, did, postings, df, N, doc_len, avgdl),
            "f_click": float(CLICKS[did]),
            "f_ctr": CTR[did],
            "f_fresh": FRESHNESS[did],
            "f_exact": float(title_match(query, doc)),
        }

    def norm(key):
        vals = [raw[d][key] for d in candidates]
        lo, hi = min(vals), max(vals)
        span = hi - lo if hi > lo else 1.0
        return {d: (raw[d][key] - lo) / span for d in candidates}

    n_bm25 = norm("f_bm25")
    n_click = norm("f_click")
    feats = {}
    for did in candidates:
        feats[did] = {
            "f_bm25": n_bm25[did],
            "f_click": n_click[did],
            "f_ctr": raw[did]["f_ctr"],
            "f_fresh": raw[did]["f_fresh"],
            "f_exact": raw[did]["f_exact"],
        }
    return feats


# default production weights (sum to 1.0)
DEFAULT_WEIGHTS = {
    "f_bm25": 0.35, "f_click": 0.30, "f_ctr": 0.15,
    "f_fresh": 0.10, "f_exact": 0.10,
}


def ltr_score(feats, weights, did):
    return sum(weights[k] * feats[did][k] for k in weights)


def section_ltr(index):
    banner("SECTION 5: Learning-to-rank (feature model + NDCG vs BM25)")
    postings, doc_len, df, N, avgdl = index
    print("BM25 only sees text. A ranker must also weigh behavioral and business")
    print("signals. We score each candidate as a WEIGHTED SUM of features, then")
    print("compare its NDCG@4 against BM25 on the same human judgments.")
    print()
    print("  f_bm25 = normalized BM25      f_click = normalized clicks")
    print("  f_ctr  = historical CTR       f_fresh = freshness [0,1]")
    print("  f_exact= title exact-match {0,1}")
    print("  default weights = " +
          ", ".join("%s=%.2f" % (k.split("_")[1], DEFAULT_WEIGHTS[k])
                    for k in DEFAULT_WEIGHTS))
    print()

    q = "machine learning"
    cand = [d for d, s in rank_by(q, bm25_score, index)]   # BM25-retrieved set
    feats = build_features(q, cand, index)

    print("Feature matrix (candidates from BM25 retrieval):")
    print("  %-5s %8s %8s %7s %7s %6s %6s" %
          ("doc", "f_bm25", "f_click", "f_ctr", "f_fresh", "exact", "grade"))
    for did in cand:
        f = feats[did]
        print("  %-5s %8.4f %8.4f %7.2f %7.2f %6d %6d" %
              (did, f["f_bm25"], f["f_click"], f["f_ctr"], f["f_fresh"],
               int(f["f_exact"]), JUDGMENTS[did]))
    print()

    ltr = sorted(cand, key=lambda d: (-ltr_score(feats, DEFAULT_WEIGHTS, d), d))
    bm = rank_by(q, bm25_score, index)
    bm_ids = [d for d, _ in bm]

    print("LTR scores (default weights):")
    for did in ltr:
        print("  %-5s %.4f" % (did, ltr_score(feats, DEFAULT_WEIGHTS, did)))
    print()

    ndcg_bm = ndcg_at_k(bm_ids, JUDGMENTS, 4)
    ndcg_ltr = ndcg_at_k(ltr, JUDGMENTS, 4)
    print("  ranking BM25 : %s" % " > ".join(bm_ids))
    print("  ranking LTR  : %s" % " > ".join(ltr))
    print("  NDCG@4 BM25  = %.4f" % ndcg_bm)
    print("  NDCG@4 LTR   = %.4f   <- LTR wins" % ndcg_ltr)
    print()
    print("  WHY LTR wins: BM25 put d6 (off-topic 'search' doc, grade 1) above d3")
    print("  (on-topic 'neural network training', grade 3) purely because d6 is")
    print("  shorter. LTR's click/freshness features rank d3 above d6, matching")
    print("  human judgment -> NDCG jumps from %.4f to %.4f (perfect ordering)." %
          (ndcg_bm, ndcg_ltr))
    print()

    ok = (ltr[0] == "d1" and ltr[1] == "d2" and ltr[2] == "d3" and ltr[3] == "d6"
          and abs(ndcg_ltr - 1.0) < 1e-9 and ndcg_ltr > ndcg_bm)
    print("[check] LTR order=d1,d2,d3,d6 and NDCG@4=1.0 (> BM25)? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 6 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 6: Scale estimation")
    corpus = 100_000_000          # 100M docs
    avg_tokens = 500              # tokens / doc
    emb_dim = 768
    qps = 10_000
    sps = 86_400

    raw_text = corpus * avg_tokens * 6            # ~6 bytes / token
    inverted_index = raw_text * 0.30              # ~30% of text after compression
    emb_raw = corpus * emb_dim * 4                # float32
    emb_pq = corpus * 32                          # 32-byte PQ codes
    queries_day = qps * sps

    print("Assumptions:")
    print("  document corpus         = %s" % fmt_int(corpus))
    print("  avg tokens / doc        = %d" % avg_tokens)
    print("  embedding dimension     = %d" % emb_dim)
    print("  peak query QPS          = %s /s" % fmt_int(qps))
    print()
    print("Index RAM:")
    print("  raw text                = %s   (%dM docs x %d tokens x 6 B)" %
          (fmt_bytes(raw_text), corpus // 1_000_000, avg_tokens))
    print("  inverted index (30%%)    = %s   (delta+varint compressed postings)" %
          fmt_bytes(inverted_index))
    print("  embeddings raw float32  = %s   (training only, never served)" %
          fmt_bytes(emb_raw))
    print("  embeddings PQ (32 B)    = %s   (served; FAISS IVF+PQ)" %
          fmt_bytes(emb_pq))
    print()
    print("Throughput:")
    print("  queries / day           = %s   (read-heavy)" % fmt_int(queries_day))
    print("  read : write ratio      = ~100 : 1   (search >> indexing)")
    print()
    print("Latency budget (p99 < 150ms):")
    print("  query understanding     <   5 ms")
    print("  BM25 retrieval          <  25 ms   (inverted index, 100M docs)")
    print("  ANN retrieval (dense)   <  30 ms   (FAISS/HNSW, parallel)")
    print("  light ranker (GBDT)     <  15 ms   (1000 -> 100 candidates)")
    print("  cross-encoder (GPU)     <  50 ms   (top-50 re-rank, 1ms each)")
    print("  business re-rank        <   5 ms")
    print("  total                   < 130 ms   (20ms slack for network)")
    print()

    ok = (corpus == 100_000_000 and
          abs(inverted_index / 1e9 - 90.0) < 1e-9 and
          abs(emb_raw / 1e9 - 307.2) < 1e-3 and
          abs(emb_pq / 1e9 - 3.2) < 1e-9)
    print("[check] inverted=90GB, emb raw=307.2GB, emb PQ=3.2GB? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values pinned for search_ranking.html
# ---------------------------------------------------------------------------

def section_gold(index):
    banner("SECTION 7: GOLD values (pinned for search_ranking.html)")
    postings, doc_len, df, N, avgdl = index

    q = "machine learning"

    # TF-IDF
    tf_d1 = tfidf_score(q, "d1", postings, df, N)
    tf_d2 = tfidf_score(q, "d2", postings, df, N)
    tf_d3 = tfidf_score(q, "d3", postings, df, N)
    tf_d6 = tfidf_score(q, "d6", postings, df, N)
    idf_machine = idf_tfidf("machine", df, N)
    idf_learning = idf_tfidf("learning", df, N)

    # BM25
    bm_d1 = bm25_score(q, "d1", postings, df, N, doc_len, avgdl)
    bm_d2 = bm25_score(q, "d2", postings, df, N, doc_len, avgdl)
    bm_d3 = bm25_score(q, "d3", postings, df, N, doc_len, avgdl)
    bm_d6 = bm25_score(q, "d6", postings, df, N, doc_len, avgdl)
    bm_order = ",".join(d for d, _ in rank_by(q, bm25_score, index))

    # expansion
    expanded, _prf, _dict = expand_query(q, index)
    after = rank_by(" ".join(expanded), bm25_score, index)
    d3_rank_after = [d for d, _ in after].index("d3") + 1
    d3_after = dict(after)["d3"]

    # LTR
    cand = [d for d, _ in rank_by(q, bm25_score, index)]
    feats = build_features(q, cand, index)
    ltr = sorted(cand, key=lambda d: (-ltr_score(feats, DEFAULT_WEIGHTS, d), d))
    ltr_order = ",".join(ltr)
    ltr_d1 = ltr_score(feats, DEFAULT_WEIGHTS, "d1")
    ltr_d3 = ltr_score(feats, DEFAULT_WEIGHTS, "d3")
    ltr_d6 = ltr_score(feats, DEFAULT_WEIGHTS, "d6")

    # NDCG
    bm_ids = [d for d, _ in rank_by(q, bm25_score, index)]
    ndcg_bm = ndcg_at_k(bm_ids, JUDGMENTS, 4)
    ndcg_ltr = ndcg_at_k(ltr, JUDGMENTS, 4)

    # scale
    inverted_gb = 100_000_000 * 500 * 6 * 0.30 / 1e9
    emb_raw_gb = 100_000_000 * 768 * 4 / 1e9
    emb_pq_gb = 100_000_000 * 32 / 1e9

    gold = [
        ("avgdl",                 round(avgdl, 4)),
        ("df_machine",            df["machine"]),
        ("df_learning",           df["learning"]),
        ("idf_machine",           round(idf_machine, 4)),
        ("idf_learning",          round(idf_learning, 4)),
        ("tfidf_d1",              round(tf_d1, 4)),
        ("tfidf_d2",              round(tf_d2, 4)),
        ("tfidf_d3",              round(tf_d3, 4)),
        ("tfidf_d6",              round(tf_d6, 4)),
        ("bm25_d1",               round(bm_d1, 4)),
        ("bm25_d2",               round(bm_d2, 4)),
        ("bm25_d3",               round(bm_d3, 4)),
        ("bm25_d6",               round(bm_d6, 4)),
        ("bm25_order",            bm_order),
        ("expanded_terms",        ",".join(expanded)),
        ("expansion_d3_rank",     d3_rank_after),
        ("expansion_d3_score",    round(d3_after, 4)),
        ("ltr_order",             ltr_order),
        ("ltr_d1",                round(ltr_d1, 4)),
        ("ltr_d3",                round(ltr_d3, 4)),
        ("ltr_d6",                round(ltr_d6, 4)),
        ("ndcg_bm25_at4",         round(ndcg_bm, 4)),
        ("ndcg_ltr_at4",          round(ndcg_ltr, 4)),
        ("scale_inverted_gb",     round(inverted_gb, 2)),
        ("scale_emb_raw_gb",      round(emb_raw_gb, 2)),
        ("scale_emb_pq_gb",       round(emb_pq_gb, 2)),
    ]
    for k, v in gold:
        print("  %-24s = %s" % (k, v))
    print()

    ok = (round(avgdl, 4) == 4.5 and
          df["machine"] == 2 and df["learning"] == 4 and
          round(tf_d1, 4) == round(tf_d2, 4) and
          bm_d2 > bm_d1 and bm_d6 > bm_d3 and
          bm_order == "d2,d1,d6,d3" and
          "deep" in expanded and "neural" in expanded and "training" in expanded and
          d3_rank_after <= 2 and
          ltr_order == "d1,d2,d3,d6" and
          round(ndcg_ltr, 4) == 1.0 and ndcg_ltr > ndcg_bm and
          round(inverted_gb, 2) == 90.0 and
          round(emb_raw_gb, 2) == 307.2 and
          round(emb_pq_gb, 2) == 3.2)
    print("[check] GOLD reproduces from index + TF-IDF + BM25 + expansion + LTR? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# search_ranking.py - Search ranking system design simulation")
    print("# Pure Python stdlib only. Numbers below feed SEARCH_RANKING.md")
    print("# and search_ranking.html (gold-checked).")

    index = build_index(DOCS)

    section_index(index)
    section_tfidf(index)
    section_bm25(index)
    section_expansion(index)
    section_ltr(index)
    section_scale()
    section_gold(index)
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
