#!/usr/bin/env python3
"""
rag_system.py - Retrieval-Augmented Generation system design (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds RAG_SYSTEM.md and is
recomputed identically in rag_system.html (gold-checked).

Core model: the RAG FUNNEL.
  Chunking       : split documents into passages. Fixed-size (sliding window),
                   sentence-aware (snap to boundaries), semantic (split on
                   embedding-similarity drops). Chunking decides WHAT the
                   retriever can ever return.
  Embedding      : a bi-encoder maps text -> dense vector. Here we proxy the
                   dense embedding with TF-IDF (term-frequency * inverse-document-
                   frequency) so the whole pipeline runs in pure stdlib. The
                   MATH of retrieval is identical: vectors + cosine similarity.
  Retrieval      : embed the query, score every chunk by cosine similarity,
                   take top-K. Fast but "shallow" -- the bi-encoder never sees
                   the query and the chunk together.
  Reranking      : a cross-encoder re-scores the top-K by reading the query and
                   the chunk JOINTLY. Accurate but too slow to run over the whole
                   corpus, hence the two-stage funnel (retrieve top-100, rerank
                   to top-5).
  Citation       : trace each generated claim back to (doc_id, chunk_span). The
                   reason RAG can say "I don't know" instead of hallucinating.

Sections:
  1. Chunking strategies (fixed-size, sentence-aware, semantic) on a sample doc
  2. TF-IDF embedding generation (vocab, idf, chunk vectors)
  3. Vector retrieval (cosine similarity, top-K)
  4. Cross-encoder reranking (reorder top-K)
  5. Citation extraction (source tracing + relevance gate)
  6. Scale estimation (10M chunks, embedding storage, latency budget)
  7. GOLD values pinned for rag_system.html
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


def tokenize(text):
    """Lowercase, keep [a-z0-9]+ runs. Identical to the JS mirror."""
    return re.findall(r"[a-z0-9]+", text.lower())


def split_sentences(text):
    """Split on '. ' (period + space). Keeps sentences trimmed & non-empty."""
    parts = re.split(r"\.\s+", text.strip().rstrip("."))
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# dataset - deterministic, mirrored verbatim in JS
# ---------------------------------------------------------------------------
# 4 short tech docs forming a tiny "RAG knowledge base". Two docs share terms
# (doc1 "vector databases" and doc3 "embedding models" both mention embeddings)
# and doc4 ("Reranking") shares "retrieval" with doc1 -- these overlaps are what
# make ranking NON-trivial: cosine retrieval returns several plausible chunks
# and the cross-encoder must separate the truly relevant ones.

DOCS = [
    {"id": "doc1", "title": "Vector Databases",
     "text": ("Vector databases store dense embeddings for fast similarity search. "
              "The embedding model encodes text into high dimensional vectors. "
              "Retrieval ranks candidate passages by cosine similarity. "
              "Qdrant and Weaviate are popular production vector databases.")},
    {"id": "doc2", "title": "Chunking",
     "text": ("Chunking splits a document into smaller passages before embedding. "
              "Fixed-size chunking slides a token window with overlap. "
              "Sentence-aware chunking snaps window boundaries to sentence ends. "
              "Semantic chunking splits where sentence similarity drops.")},
    {"id": "doc3", "title": "Embedding Models",
     "text": ("Embedding models encode text into dense vectors. "
              "The BGE model produces 1024 dimensional embeddings. "
              "E5 models support multilingual retrieval. "
              "Dense embeddings capture semantic meaning for cosine similarity.")},
    {"id": "doc4", "title": "Reranking",
     "text": ("Reranking uses a cross-encoder to score query and document jointly. "
              "The cross-encoder is accurate but too slow for the full corpus. "
              "A two-stage funnel retrieves candidates then reranks them. "
              "Reranking improves precision at the top of the result list.")},
]

# A document used ONLY in Section 1 to show the 3 chunking strategies side by
# side. Topic A (sentences 1-3) is about embeddings/vectors and repeats that
# vocabulary heavily; topic B (sentences 4-6) is about vector-db systems and
# index graphs. The s3->s4 boundary has near-zero shared vocabulary, so
# semantic chunking's adjacent-cosine drops sharply there -> a clean split.
DEMO_DOC = (
    "Embedding models encode text into dense vectors. "
    "Dense vectors and models encode semantic meaning. "
    "The semantic model encodes vectors into embeddings. "
    "Qdrant and Weaviate are production vector databases. "
    "HNSW is the default graph index for approximate search. "
    "The index retrieves candidate passages in milliseconds."
)

# The reference query used through Sections 2-5. It contains "vector",
# "retrieval", "similarity" -- terms spread across doc1 (vector, similarity),
# doc3 (similarity), and doc4 (no direct hit). This is what forces the
# cross-encoder to do real work: cosine returns several chunks that partially
# match, and reranking must promote the ones covering MORE of the query.
QUERY = "vector retrieval similarity search"


# ---------------------------------------------------------------------------
# chunking strategies (Section 1)
# ---------------------------------------------------------------------------

def chunk_fixed_size(text, window=8, overlap=2):
    """Sliding token window of `window` words stepping by (window-overlap).

    Returns list of token-lists. May split mid-sentence -- that is the point.
    """
    toks = tokenize(text)
    if window <= 0:
        return []
    step = max(1, window - overlap)
    chunks = []
    i = 0
    while i < len(toks):
        chunks.append(toks[i:i + window])
        if i + window >= len(toks):
            break
        i += step
    return chunks


def chunk_sentence_aware(text, max_tokens=8):
    """Group whole sentences until adding the next would exceed `max_tokens`.

    Snap to sentence boundaries -> never splits a sentence. A sentence longer
    than the budget becomes its own chunk.
    """
    sents = split_sentences(text)
    chunks = []
    cur = []
    cur_len = 0
    for s in sents:
        stoks = tokenize(s)
        if cur and cur_len + len(stoks) > max_tokens:
            chunks.append(cur)
            cur = []
            cur_len = 0
        cur.extend(stoks)
        cur_len += len(stoks)
    if cur:
        chunks.append(cur)
    return chunks


def chunk_semantic(text, threshold=None):
    """Split between two sentences when their cosine similarity is below the
    mean of all adjacent similarities (the classic "split on the similarity
    drop" rule). Sentence embeddings = TF-IDF over the doc's own vocabulary.
    """
    sents = split_sentences(text)
    if len(sents) <= 1:
        return [tokenize(sents[0])] if sents else []
    sent_toks = [tokenize(s) for s in sents]
    vocab = sorted(set(t for toks in sent_toks for t in toks))
    vidx = {t: i for i, t in enumerate(vocab)}
    df = [0] * len(vocab)
    for toks in sent_toks:
        for t in set(toks):
            df[vidx[t]] += 1
    N = len(sent_toks)
    idf = [math.log(N / df[i]) if df[i] else 0.0 for i in range(len(vocab))]

    def embed(toks):
        v = [0.0] * len(vocab)
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        for t, c in tf.items():
            v[vidx[t]] = c * idf[vidx[t]]
        return v

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    embs = [embed(t) for t in sent_toks]
    sims = [cosine(embs[i], embs[i + 1]) for i in range(len(embs) - 1)]
    thr = threshold if threshold is not None else (sum(sims) / len(sims) if sims else 0.0)
    chunks = []
    cur = list(sent_toks[0])
    for i, sim in enumerate(sims):
        if sim < thr:
            chunks.append(cur)
            cur = list(sent_toks[i + 1])
        else:
            cur.extend(sent_toks[i + 1])
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------------------
# TF-IDF embedding + retrieval (Sections 2-3)
# ---------------------------------------------------------------------------

def build_vocab(chunks):
    """chunks = list of token-lists. Returns (vocab sorted, df dict, idf dict)."""
    df = {}
    for toks in chunks:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    vocab = sorted(df)
    N = len(chunks)
    idf = {t: math.log(N / df[t]) for t in vocab}      # classic TF-IDF idf
    return vocab, df, idf


def tfidf_vec(toks, idf):
    """Sparse TF-IDF vector {term: tf*idf} (terms not in idf are dropped)."""
    tf = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    return {t: c * idf[t] for t, c in tf.items() if t in idf}


def cosine_sparse(a, b):
    dot = sum(a[t] * b.get(t, 0.0) for t in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def retrieve(query_vec, chunk_vecs, top_k=None):
    """Cosine similarity top-K. Returns [(chunk_idx, score)] desc."""
    scored = [(i, cosine_sparse(query_vec, cv)) for i, cv in enumerate(chunk_vecs)]
    scored.sort(key=lambda t: (-t[1], t[0]))
    if top_k is not None:
        scored = scored[:top_k]
    return scored


# ---------------------------------------------------------------------------
# cross-encoder reranking (Section 4)
# ---------------------------------------------------------------------------
# A cross-encoder reads [query, chunk] together and produces a relevance score.
# We simulate its behavior with an IDF-WEIGHTED QUERY COVERAGE signal: how much
# of the query's discriminative mass (sum of query-term idf) is covered by the
# chunk. This is a genuinely different signal from cosine (which is tf-weighted
# dot product magnitude) -- coverage rewards a chunk that touches MORE distinct
# query terms even if its tf magnitude is smaller. That is exactly the kind of
# reorder a real cross-encoder produces: it lifts chunks that the bi-encoder
# ranked low because they were terse but on-topic.

def rerank_score(query_toks, chunk_toks, idf):
    """IDF-weighted query coverage in [0,1].

    = sum(idf[t] for t in query AND chunk) / sum(idf[t] for t in query)
    """
    q_terms = set(t for t in query_toks if t in idf)
    if not q_terms:
        return 0.0
    cset = set(chunk_toks)
    covered = sum(idf[t] for t in q_terms if t in cset)
    total = sum(idf[t] for t in q_terms)
    return covered / total if total else 0.0


def rerank(query_toks, candidates, chunk_toks, idf):
    """Re-score the retrieved candidates; return [(chunk_idx, score)] desc."""
    scored = [(i, rerank_score(query_toks, chunk_toks[i], idf)) for i, _ in candidates]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return scored


# ---------------------------------------------------------------------------
# citation extraction (Section 5)
# ---------------------------------------------------------------------------

def extract_citations(reranked, chunk_meta, threshold=0.5, top_n=3):
    """Build citations from reranked chunks above the relevance threshold.

    Each citation: {doc_id, title, chunk_index, span_text, score}.
    The relevance gate drops low-scoring chunks -- the RAG abstention mechanism.
    """
    cites = []
    for idx, score in reranked[:top_n]:
        if score < threshold:
            continue
        m = chunk_meta[idx]
        cites.append({
            "doc_id": m["doc_id"],
            "title": m["title"],
            "chunk_index": m["chunk_index"],
            "span": " ".join(m["tokens"]),
            "score": score,
        })
    return cites


# ---------------------------------------------------------------------------
# SECTION 1 - Chunking strategies
# ---------------------------------------------------------------------------

def section_chunking():
    banner("SECTION 1: Chunking strategies (fixed-size, sentence-aware, semantic)")
    print("Chunking decides what the retriever can EVER return: a fact split across")
    print("two chunks is retrievable only as fragments; a chunk that merges two")
    print("topics dilutes both. Three strategies on the SAME demo document:\n")
    print('  DEMO_DOC = "%s"' % DEMO_DOC)
    sents = split_sentences(DEMO_DOC)
    print("\n  %d sentences:" % len(sents))
    for i, s in enumerate(sents, 1):
        print("    s%d: \"%s.\"" % (i, s))
    print()

    fixed = chunk_fixed_size(DEMO_DOC, window=8, overlap=2)
    aware = chunk_sentence_aware(DEMO_DOC, max_tokens=8)
    seman = chunk_semantic(DEMO_DOC)

    def show(label, chunks):
        print("  %s -> %d chunks:" % (label, len(chunks)))
        for i, c in enumerate(chunks):
            print("    c%d (%d tok): %s" % (i, len(c), " ".join(c)))
        print()

    show("fixed-size (window=8, overlap=2)", fixed)
    show("sentence-aware (budget=8 tok)", aware)
    show("semantic (split on sim drop)", seman)

    fixed_lens = [len(c) for c in fixed]
    aware_lens = [len(c) for c in aware]
    seman_lens = [len(c) for c in seman]
    print("  %-16s chunks=%d  lens=%s  avg=%.2f" %
          ("fixed-size", len(fixed), fixed_lens, sum(fixed_lens) / len(fixed)))
    print("  %-16s chunks=%d  lens=%s  avg=%.2f" %
          ("sentence-aware", len(aware), aware_lens, sum(aware_lens) / len(aware)))
    print("  %-16s chunks=%d  lens=%s  avg=%.2f" %
          ("semantic", len(seman), seman_lens, sum(seman_lens) / len(seman)))
    print()
    print("  fixed-size can SPLIT a sentence (chunk boundaries ignore grammar);")
    print("  sentence-aware never splits a sentence but may exceed the budget;")
    print("  semantic finds the TOPIC BOUNDARY (embeddings vs systems) and groups")
    print("  sentences by meaning. Production default = sentence-aware; semantic is")
    print("  ~10% better recall on heterogeneous corpora at 2-3x indexing cost.")

    ok = (len(fixed) == 7 and len(aware) == 6 and len(seman) == 4 and
          fixed_lens == [8, 8, 8, 8, 8, 8, 8] and
          aware_lens == [7, 7, 7, 7, 9, 7] and
          seman_lens == [21, 7, 9, 7])
    print("\n[check] fixed=7 lens [8,8,8,8,8,8,8], aware=6 lens [7,7,7,7,9,7], "
          "semantic=4 lens [21,7,9,7]? " + ("OK" if ok else "FAIL"))
    return {"fixed": fixed, "aware": aware, "seman": seman}


# ---------------------------------------------------------------------------
# SECTION 2 - TF-IDF embedding generation
# ---------------------------------------------------------------------------

def section_embedding(chunks):
    banner("SECTION 2: TF-IDF embedding (bi-encoder proxy)")
    print("A bi-encoder maps text -> dense vector. We proxy it with TF-IDF so the")
    print("whole pipeline runs in stdlib. Embedding = a sparse vector of")
    print("tf * idf for every vocabulary term, where idf = log(N/df) rewards terms")
    print("that appear in FEW chunks (discriminative) and zeroes terms in every")
    print("chunk (stop-word-like). Retrieval math is unchanged: vectors + cosine.\n")

    vocab, df, idf = build_vocab(chunks)
    N = len(chunks)
    print("Corpus chunked with sentence-aware (Section 1 default): %d chunks." % N)
    print("Vocabulary size = %d unique terms.\n" % len(vocab))

    print("Document frequency + idf for query-relevant terms:")
    q_terms = [t for t in tokenize(QUERY) if t in idf]
    q_terms = sorted(set(q_terms), key=lambda t: -idf[t])
    print("  %-14s %5s %8s" % ("term", "df", "idf"))
    for t in q_terms:
        print("  %-14s %5d %8.4f" % (t, df[t], idf[t]))
    print()

    chunk_vecs = [tfidf_vec(c, idf) for c in chunks]
    norms = [math.sqrt(sum(v * v for v in vec.values())) for vec in chunk_vecs]
    print("Per-chunk embedding magnitude (L2 norm of the TF-IDF vector):")
    print("  %-10s %8s  %s" % ("chunk", "||v||", "top terms (tf*idf)"))
    for i, (vec, nm) in enumerate(zip(chunk_vecs, norms)):
        top = sorted(vec.items(), key=lambda kv: -kv[1])[:3]
        top_s = ", ".join("%s=%.3f" % (t, w) for t, w in top)
        print("  c%-9d %8.4f  %s" % (i, nm, top_s))
    print()

    q_vec = tfidf_vec(tokenize(QUERY), idf)
    q_norm = math.sqrt(sum(v * v for v in q_vec.values()))
    print("Query embedding: '%s'" % QUERY)
    print("  query tf*idf = {%s}" %
          ", ".join("%s=%.4f" % (t, q_vec[t]) for t in sorted(q_vec, key=lambda x: -q_vec[x])))
    print("  ||q|| = %.4f  (only %d of %d query terms are in vocab)" %
          (q_norm, len(q_vec), len(set(tokenize(QUERY)))))

    ok = (len(vocab) > 0 and all(n > 0 for n in norms) and
          df.get("vector", 0) >= 1 and abs(idf.get("vector", 0)) >= 0.0)
    print("\n[check] vocab>0, all chunk norms>0, 'vector' in vocab? " +
          ("OK" if ok else "FAIL"))
    return vocab, df, idf, chunk_vecs


# ---------------------------------------------------------------------------
# SECTION 3 - Vector retrieval
# ---------------------------------------------------------------------------

def section_retrieval(chunks, chunk_vecs, idf):
    banner("SECTION 3: Vector retrieval (cosine similarity, top-K)")
    print("Embed the query, score every chunk by COSINE SIMILARITY (angle between")
    print("the two normalized vectors), take the top-K. Cosine is scale-invariant")
    print("-- a chunk with small tf magnitude but a matching term angle still scores")
    print("well. That is also its weakness: it rewards 'one strong shared term' over")
    print("'covers the whole query', which is what the cross-encoder fixes next.\n")

    query_vec = tfidf_vec(tokenize(QUERY), idf)
    top = retrieve(query_vec, chunk_vecs, top_k=len(chunk_vecs))
    print("Query: '%s'\n" % QUERY)
    print("  %-5s %9s  %s" % ("rank", "cosine", "chunk"))
    for rank, (idx, s) in enumerate(top, 1):
        mark = "  <- top-%d" % min(rank, 5)
        print("  %-5d %9.4f  c%d: %s%s" %
              (rank, s, idx, " ".join(chunks[idx][:7]), mark if rank <= 5 else ""))
    print()

    topk = retrieve(query_vec, chunk_vecs, top_k=5)
    order = ",".join("c%d" % i for i, _ in topk)
    best = topk[0]
    print("  top-5 cosine order: %s" % order)
    print("  best chunk = c%d (cosine %.4f)" % (best[0], best[1]))
    print("  Note: several chunks share 'vector' or 'similarity' -> cosine returns")
    print("  a PARTIAL-match ordering. The cross-encoder will promote chunks that")
    print("  cover MORE of the query (vector + retrieval + similarity).")

    ok = (best[1] > 0 and len(topk) == 5)
    print("\n[check] best cosine > 0, top-5 returned? " + ("OK" if ok else "FAIL"))
    return topk


# ---------------------------------------------------------------------------
# SECTION 4 - Cross-encoder reranking
# ---------------------------------------------------------------------------

def section_reranking(chunks, topk, idf):
    banner("SECTION 4: Cross-encoder reranking (re-score the top-K jointly)")
    print("A cross-encoder reads [query, chunk] TOGETHER and outputs a relevance")
    print("score. Too slow for the full corpus (~100 docs/GPU-batch), so we only")
    print("run it on the top-K the retriever returned. We simulate its score with")
    print("IDF-WEIGHTED QUERY COVERAGE = sum(idf[t] for t in query AND chunk) /")
    print("sum(idf[t] for t in query). Coverage rewards chunks that touch MORE")
    print("distinct query terms -- a different signal than cosine magnitude.\n")

    r = rerank(tokenize(QUERY), topk, chunks, idf)
    print("Query: '%s'  (terms: %s)\n" %
          (QUERY, ", ".join(sorted(set(t for t in tokenize(QUERY) if t in idf)))))
    print("  %-5s %9s %9s  %s" % ("rank", "cov", "cosine", "chunk"))
    cos_map = dict(topk)
    for rank, (idx, s) in enumerate(r, 1):
        cov_terms = sorted(set(t for t in tokenize(QUERY) if t in idf) &
                           set(chunks[idx]))
        print("  %-5d %9.4f %9.4f  c%d: {%s}" %
              (rank, s, cos_map.get(idx, 0.0), idx, ",".join(cov_terms)))
    print()

    cos_order = ",".join("c%d" % i for i, _ in topk)
    rer_order = ",".join("c%d" % i for i, _ in r)
    print("  cosine order : %s" % cos_order)
    print("  rerank  order: %s" % rer_order)
    if cos_order != rer_order:
        print("  -> cross-encoder REORDERED the top-K (coverage != magnitude).")
    print("  The chunk covering the MOST query terms (vector + retrieval +")
    print("  similarity) is promoted to #1 even if its cosine was not the highest.")

    ok = (len(r) == len(topk) and r[0][1] >= 0.0)
    print("\n[check] rerank preserved top-K size? " + ("OK" if ok else "FAIL"))
    return r


# ---------------------------------------------------------------------------
# SECTION 5 - Citation extraction
# ---------------------------------------------------------------------------

def section_citations(chunks, reranked, idf):
    banner("SECTION 5: Citation extraction (source tracing + relevance gate)")
    print("Each reranked chunk becomes a CITATION: (doc_id, title, chunk_index,")
    print("span_text, score). The relevance gate DROPS chunks below threshold --")
    print("the RAG abstention mechanism ('I don't know' instead of hallucinating).\n")

    chunk_meta = []
    ci_by_doc = {}
    for doc in DOCS:
        cks = chunk_sentence_aware(doc["text"], max_tokens=8)
        for ci, toks in enumerate(cks):
            chunk_meta.append({
                "doc_id": doc["id"],
                "title": doc["title"],
                "chunk_index": ci,
                "tokens": toks,
            })
            ci_by_doc.setdefault(doc["id"], []).append(len(chunk_meta) - 1)

    cites = extract_citations(reranked, chunk_meta, threshold=0.5, top_n=3)
    print("Relevance gate threshold = 0.5  (drop chunks below this coverage).\n")
    print("  %-5s %-6s %-22s %6s  %s" %
          ("rank", "doc", "title", "score", "span"))
    for i, c in enumerate(cites, 1):
        span = c["span"]
        if len(span) > 42:
            span = span[:39] + "..."
        print("  %-5d %-6s %-22s %6.4f  \"%s\"" %
              (i, c["doc_id"], "(" + c["title"] + ")", c["score"], span))
    print()

    if cites:
        top = cites[0]
        print("  Top citation: %s, chunk #%d (score %.4f). The generated answer is" %
              (top["doc_id"], top["chunk_index"], top["score"]))
        print("               grounded in this span; the LLM is constrained to cite it.")
    if len(cites) < len(reranked):
        dropped = len(reranked) - len(cites)
        print("  Relevance gate DROPPED %d chunk(s) below 0.5 -> not cited." % dropped)
    print("  Faithfulness: every claim in the answer must trace to a cited span,")
    print("  checked by an NLI entailment model (DeBERTa) in production.")

    ok = (len(cites) >= 1 and all(c["score"] >= 0.5 for c in cites))
    print("\n[check] at least 1 citation above threshold? " + ("OK" if ok else "FAIL"))
    return cites, chunk_meta


# ---------------------------------------------------------------------------
# SECTION 6 - Scale estimation
# ---------------------------------------------------------------------------

def section_scale():
    banner("SECTION 6: Scale estimation")
    corpus_docs = 10_000_000        # 10M docs
    tokens_per_doc = 500
    tokens_per_chunk = 256
    overlap = 50
    step = tokens_per_chunk - overlap
    chunks_per_doc = math.ceil((tokens_per_doc - tokens_per_chunk) / step) + 1
    chunks = corpus_docs * chunks_per_doc
    emb_dim = 1024                  # BGE-large
    qps = 1_000

    raw_text = corpus_docs * tokens_per_doc * 6                 # ~6 B/token
    emb_raw = chunks * emb_dim * 4                              # float32
    emb_pq = chunks * 64                                         # 64-byte PQ codes
    rerank_gpu = math.ceil(qps / 12)                             # ~12 rerank QPS / A10

    print("Assumptions:")
    print("  document corpus        = %s docs" % fmt_int(corpus_docs))
    print("  avg tokens / doc       = %d" % tokens_per_doc)
    print("  chunk size             = %d tokens, %d overlap (step %d)" %
          (tokens_per_chunk, overlap, step))
    print("  chunks / doc           = ceil((%d-%d)/%d)+1 = %d" %
          (tokens_per_doc, tokens_per_chunk, step, chunks_per_doc))
    print("  embedding dim          = %d (BGE-large-en-v1.5)" % emb_dim)
    print("  peak query QPS         = %s /s" % fmt_int(qps))
    print()
    print("Total chunks indexed     = %s" % fmt_int(chunks))
    print()
    print("Storage:")
    print("  raw text               = %s" % fmt_bytes(raw_text))
    print("  embeddings (float32)   = %s   (chunks x %d dim x 4 B)" %
          (fmt_bytes(emb_raw), emb_dim))
    print("  embeddings (PQ 64 B)   = %s   (served; %.0fx compression)" %
          (fmt_bytes(emb_pq), emb_raw / emb_pq))
    print()
    print("Latency budget (p95 < 1500ms chat):")
    print("  query embedding        <  30 ms   (bi-encoder, GPU)")
    print("  dense retrieval (HNSW) <  15 ms   (parallel with BM25)")
    print("  BM25 retrieval         <  10 ms   (sparse, parallel)")
    print("  RRF fusion             <   2 ms")
    print("  cross-encoder rerank   <  80 ms   (top-100 -> top-10)")
    print("  LLM first token (TTFT) < 400 ms")
    print("  LLM streaming          < 900 ms")
    print("  total p95              <1430 ms   (~70ms slack)")
    print()
    print("Reranker GPU sizing: %s QPS / 12 QPS-per-A10 = %d x A10 GPUs (BGE-reranker)" %
          (fmt_int(qps), rerank_gpu))

    ok = (corpus_docs == 10_000_000 and
          chunks_per_doc == 3 and chunks == 30_000_000 and
          abs(emb_raw / 1e9 - 122.88) < 1e-6 and
          abs(emb_pq / 1e9 - 1.92) < 1e-6 and
          rerank_gpu == 84)
    print("\n[check] chunks/doc=3, total=30M, emb raw=122.88GB, emb PQ=1.92GB, 84 GPUs? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------
# SECTION 7 - GOLD values
# ---------------------------------------------------------------------------

def section_gold(chunks, vocab, df, idf, chunk_vecs, topk, reranked, cites):
    banner("SECTION 7: GOLD values (pinned for rag_system.html)")

    q = tokenize(QUERY)
    q_vec = tfidf_vec(q, idf)
    q_norm = math.sqrt(sum(v * v for v in q_vec.values()))

    # chunking gold (Section 1)
    fixed = chunk_fixed_size(DEMO_DOC, 8, 2)
    aware = chunk_sentence_aware(DEMO_DOC, 8)
    seman = chunk_semantic(DEMO_DOC)

    # retrieval gold
    cos_order = ",".join("c%d" % i for i, _ in topk)
    best_cos = topk[0]

    # rerank gold
    rer_order = ",".join("c%d" % i for i, _ in reranked)
    best_rer = reranked[0]

    # citation gold
    n_cites = len(cites)
    top_cite_score = cites[0]["score"] if cites else 0.0

    gold = [
        ("vocab_size",             len(vocab)),
        ("df_vector",              df.get("vector", 0)),
        ("df_similarity",          df.get("similarity", 0)),
        ("df_retrieval",           df.get("retrieval", 0)),
        ("idf_vector",             round(idf.get("vector", 0.0), 4)),
        ("idf_similarity",         round(idf.get("similarity", 0.0), 4)),
        ("idf_retrieval",          round(idf.get("retrieval", 0.0), 4)),
        ("query_norm",             round(q_norm, 4)),
        ("n_chunks",               len(chunks)),
        ("chunking_fixed_n",       len(fixed)),
        ("chunking_aware_n",       len(aware)),
        ("chunking_semantic_n",    len(seman)),
        ("chunking_fixed_lens",    ",".join(str(len(c)) for c in fixed)),
        ("chunking_aware_lens",    ",".join(str(len(c)) for c in aware)),
        ("chunking_semantic_lens", ",".join(str(len(c)) for c in seman)),
        ("retrieval_cos_order",    cos_order),
        ("retrieval_best_idx",     best_cos[0]),
        ("retrieval_best_cos",     round(best_cos[1], 4)),
        ("rerank_order",           rer_order),
        ("rerank_best_idx",        best_rer[0]),
        ("rerank_best_score",      round(best_rer[1], 4)),
        ("citation_count",         n_cites),
        ("citation_top_score",     round(top_cite_score, 4)),
        ("scale_chunks",           30_000_000),
        ("scale_emb_raw_gb",       round(30_000_000 * 1024 * 4 / 1e9, 2)),
        ("scale_emb_pq_gb",        round(30_000_000 * 64 / 1e9, 4)),
        ("scale_rerank_gpus",      84),
    ]
    for k, v in gold:
        print("  %-24s = %s" % (k, v))
    print()

    ok = (len(vocab) == 91 and
          len(fixed) == 7 and len(aware) == 6 and len(seman) == 4 and
          [len(c) for c in fixed] == [8, 8, 8, 8, 8, 8, 8] and
          [len(c) for c in aware] == [7, 7, 7, 7, 9, 7] and
          [len(c) for c in seman] == [21, 7, 9, 7] and
          round(best_cos[1], 4) == 0.5029 and best_cos[0] == 0 and
          cos_order == "c0,c2,c10,c3,c7" and
          rer_order == "c0,c2,c3,c10,c7" and rer_order != cos_order and
          round(best_rer[1], 4) == 0.75 and
          n_cites == 1 and round(top_cite_score, 4) == 0.75 and
          round(30_000_000 * 1024 * 4 / 1e9, 2) == 122.88 and
          round(30_000_000 * 64 / 1e9, 4) == 1.92 and
          math.ceil(1000 / 12) == 84)
    print("[check] GOLD reproduces from chunking + embedding + retrieval + "
          "reranking + citations? " + ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def build_corpus_chunks():
    """Chunk all DOCS with sentence-aware (the production default) -> flat list
    of (doc_id, title, chunk_index, tokens)."""
    chunks = []
    meta = []
    for doc in DOCS:
        cks = chunk_sentence_aware(doc["text"], max_tokens=8)
        for ci, toks in enumerate(cks):
            chunks.append(toks)
            meta.append({"doc_id": doc["id"], "title": doc["title"],
                         "chunk_index": ci, "tokens": toks})
    return chunks, meta


def main():
    print("# rag_system.py - Retrieval-Augmented Generation system design simulation")
    print("# Pure Python stdlib only. Numbers below feed RAG_SYSTEM.md")
    print("# and rag_system.html (gold-checked).")

    chunk_demo = section_chunking()

    chunks, meta = build_corpus_chunks()
    vocab, df, idf = build_vocab(chunks)
    chunk_vecs = [tfidf_vec(c, idf) for c in chunks]
    q_vec = tfidf_vec(tokenize(QUERY), idf)

    section_embedding(chunks)
    topk = section_retrieval(chunks, chunk_vecs, idf)
    reranked = section_reranking(chunks, topk, idf)
    cites, chunk_meta = section_citations(chunks, reranked, idf)
    section_scale()
    section_gold(chunks, vocab, df, idf, chunk_vecs, topk, reranked, cites)

    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
