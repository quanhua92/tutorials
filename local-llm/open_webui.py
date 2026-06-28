"""
open_webui.py - Reference implementation of the Open WebUI RAG pipeline.

WHAT IS OPEN WEBUI? (start here if you have minimal ML background)
   Open WebUI is a self-hosted web frontend for local + remote LLMs. Think
   "self-hosted ChatGPT with RAG, tools, and multi-user support." It does NOT run
   models itself -- it is a *frontend* that connects to backends: Ollama (local),
   OpenAI, Anthropic, or any OpenAI-compatible API. Its flagship feature is RAG
   (Retrieval-Augmented Generation): you upload documents, Open WebUI chunks them,
   embeds the chunks, stores them in a vector database, and at query time retrieves
   the most relevant chunks and injects them into the LLM prompt so the model can
   answer questions grounded in YOUR data.

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. RAW LLM CHAT (the baseline): you ask the model a question, it answers from
      its training data. Problem: it has never seen your private documents, and it
      will happily hallucinate facts it does not know. The context window is also
      finite -- you cannot paste a 1000-page manual into every prompt.

   2. STUFF EVERYTHING IN CONTEXT (brute force): paste the whole document into the
      prompt. Problem: blows the context window, costs tokens, dilutes attention
      across irrelevant text, and the model still ignores the right paragraph in a
      wall of text. Works for one short doc; dies at scale.

   3. RAG (Retrieval-Augmented Generation): split the doc into CHUNKS, embed each
      chunk into a vector, store them in a VECTOR DB. At query time: embed the
      query, do a cosine-similarity search for the top-k closest chunks, inject
      ONLY those into the prompt. The model answers from relevant context, cheaply
      and grounded. This is Open WebUI's core Knowledge feature.

   4. HYBRID SEARCH + RERANK: pure vector search misses exact keyword matches
      (product codes, names). BM25 (keyword) + vector (semantic) are combined, then
      a CROSS-ENCODER reranker re-scores the (query, chunk) pairs for precision.
      Open WebUI ships this out of the box.

THE RAG PIPELINE (this bundle's load-bearing claim):
   Document -> [Chunk] -> [Embed] -> [Vector DB]
   Query    -> [Embed] -> [cosine search top-k] -> [rerank] -> [inject] -> [LLM]

   Chunking strategy matters:
     * Token-based (e.g. 512 tokens): the production default (good throughput).
     * Sentence-based: preserves meaning boundaries (fewer mid-sentence cuts).
     * Overlap (e.g. 50 tokens): prevents losing context at chunk boundaries.
     * Too small -> lose context. Too large -> dilute relevance + blow context.

   This simulator chunks at the WORD level (tiny, so every number prints) with a
   configurable chunk size and overlap. The math is identical to token-level; only
   the unit changes.

FAKE EMBEDDINGS (why and how):
   A real embedding model (nomic-embed-text, 768 dims) is a transformer that needs
   PyTorch + weights -- forbidden here (pure stdlib rule). Instead we use the
   FEATURE-HASHING TRICK: each lowercase word is hashed (deterministic FNV-1a, NOT
   Python's randomized hash()) into one of DIM=256 dimensions and counted, then the
   vector is L2-normalized. This is a deterministic bag-of-words surrogate: two
   texts sharing words land in the same buckets, so cosine similarity tracks lexical
   overlap -- exactly the property a RAG retrieval step relies on. With DIM=256 and
   a 15-word vocabulary there are zero hash collisions, so the result is exact.

Companion code that OPEN_WEBUI.md is built from. Every number below is printed by:
    python3 open_webui.py

PURE PYTHON STDLIB (no torch, no numpy, no sentence-transformers). Deterministic.
"""

from __future__ import annotations

import math
import re

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------

# Embedding dimension for the fake feature-hashing embedder. Real nomic-embed-text
# is 768; we use 256 so the vector is short to print yet collision-free for the
# 15-word demo vocabulary (verified: every word lands in a distinct bucket).
EMBED_DIM = 256

# The canonical document + query (the GOLD example, mirrored in the .html).
GOLD_DOC = "The cat sat on the mat. The dog ran in the park. Cats love fish."
GOLD_QUERY = "What do cats eat?"
GOLD_CHUNK_SIZE = 5      # words per chunk
GOLD_OVERLAP = 2         # words of overlap between consecutive chunks
GOLD_TOP_K = 5

# BM25 parameters (the textbook defaults).
BM25_K1 = 1.5
BM25_B = 0.75

# English stopword set (used by the reranker's density proxy + BM25 focus list).
STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "is", "are",
    "was", "were", "be", "been", "do", "does", "did", "what", "who", "how",
    "why", "where", "when", "that", "this", "it", "for", "with",
}

# The backends Open WebUI connects to (docs.openwebui.com/features).
BACKENDS = [
    ("Ollama",        "local",   "http://localhost:11434",   "any GGUF model via /api/chat"),
    ("OpenAI API",    "remote",  "https://api.openai.com",   "GPT-4o, o-series"),
    ("Anthropic",     "remote",  "https://api.anthropic.com","Claude (via OpenAI-compat endpoint)"),
    ("OpenAI-compat", "either",  "<any base_url>",           "vLLM, LM Studio, llama.cpp server, Together, Groq, ..."),
]

# The 9 vector databases Open WebUI supports (docs.openwebui.com/features RAG).
VECTOR_DBS = [
    ("ChromaDB",      "official", "default, bundled in the Docker image"),
    ("PGVector",      "official", "Postgres extension; shared with app DB"),
    ("Qdrant",        "community", "production-grade, filtering"),
    ("Milvus",        "community", "billion-scale, sharded"),
    ("Elasticsearch", "community", "BM25 + kNN in one engine"),
    ("OpenSearch",    "community", "AWS fork of Elasticsearch"),
    ("Redis",         "community", "in-memory, low latency"),
    ("MongoDB Atlas", "community", "$vectorSearch aggregation"),
    ("SurrealDB",     "community", "multi-model"),
]


# ============================================================================
# Helpers: banner + check (same shape as the sibling bundles)
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(label: str, cond: bool) -> bool:
    status = "OK" if cond else "FAIL"
    print(f"[check] {label}: {cond} -> {status}")
    return cond


# ============================================================================
# 1. Tokenizer + deterministic word hash + fake embedder
# ============================================================================

def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric word tokens. Punctuation is stripped, so 'mat.'
    and 'park.' become 'mat' and 'park' -- the standard RAG preprocessing step
    that lets 'Cats' match 'cats'."""
    return [t.lower() for t in re.findall(r"[A-Za-z0-9']+", text)]


def word_hash(word: str) -> int:
    """Deterministic FNV-1a 32-bit hash. CRITICAL: this is NOT Python's built-in
    hash() -- that is randomized per process (PYTHONHASHSEED) and would make
    _output.txt non-reproducible. FNV-1a is a fixed polynomial hash."""
    h = 2166136261                       # FNV-1a offset basis
    for ch in word.encode("utf-8"):
        h ^= ch
        h = (h * 16777619) & 0xFFFFFFFF   # FNV-1a prime, keep 32 bits
    return h


def embed(text: str, dim: int = EMBED_DIM) -> tuple[list[float], list[str]]:
    """Fake embedding via the feature-hashing trick.

    Maps each token to a dimension (hash mod dim), accumulates counts, then
    L2-normalizes -- exactly how a real embedder is consumed downstream (cosine
    similarity on normalized vectors = a dot product). Returns (vector, tokens).
    """
    vec = [0.0] * dim
    toks = tokenize(text)
    for w in toks:
        vec[word_hash(w) % dim] += 1.0
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec, toks


def cosine(a: list[float], b: list[float]) -> float:
    """Dot product. Because embed() L2-normalizes, this IS cosine similarity."""
    return sum(x * y for x, y in zip(a, b))


# ============================================================================
# 2. Chunker  (word-level, with overlap -- the math generalizes to tokens)
# ============================================================================

def chunk_words(words: list[str], size: int, overlap: int) -> list[list[str]]:
    """Split a word list into overlapping windows.

    step = size - overlap  (the stride between consecutive chunk starts). The
    last window is truncated to the remaining words. This mirrors how Open WebUI's
    CHUNK_SIZE / CHUNK_OVERLAP settings walk a token stream.
    """
    if size <= 0:
        raise ValueError("chunk size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")
    step = size - overlap
    chunks: list[list[str]] = []
    i = 0
    n = len(words)
    while i < n:
        chunks.append(words[i:i + size])
        if i + size >= n:          # last window reached the end
            break
        i += step
    return chunks


def chunk_document(doc: str, size: int, overlap: int) -> list[str]:
    """Chunk a document string by whitespace-separated words."""
    return [" ".join(c) for c in chunk_words(doc.split(), size, overlap)]


# ============================================================================
# 3. Vector search (cosine top-k) + BM25 + hybrid + rerank
# ============================================================================

def vector_search(query_emb: list[float], chunk_texts: list[str],
                  top_k: int) -> list[tuple[float, str]]:
    """Embed each chunk, score by cosine to the query, return top_k descending."""
    scored = []
    for c in chunk_texts:
        cemb, _ = embed(c)
        scored.append((cosine(query_emb, cemb), c))
    scored.sort(key=lambda t: (-t[0], t[1]))   # tie-break on text for determinism
    return scored[:top_k]


def build_bm25_index(chunks: list[str]) -> dict:
    """Build the BM25 statistics over a chunk corpus (pure stdlib).

    BM25 (Okapi): for a query term t in document d:
        score += IDF(t) * (tf * (k1+1)) / (tf + k1*(1 - b + b*|d|/avgdl))
        IDF(t) = ln( (N - df + 0.5) / (df + 0.5) + 1 )
    where N = #chunks, df = #chunks containing t, tf = term freq in d,
    |d| = doc length, avgdl = mean doc length.
    """
    tokenized = [tokenize(c) for c in chunks]
    n = len(chunks)
    df: dict[str, int] = {}
    for toks in tokenized:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()}
    avgdl = sum(len(t) for t in tokenized) / n if n else 0.0
    lengths = [len(t) for t in tokenized]
    return {"tokenized": tokenized, "idf": idf, "avgdl": avgdl,
            "lengths": lengths, "n": n}


def bm25_score(query: str, chunk_idx: int, index: dict,
               k1: float = BM25_K1, b: float = BM25_B) -> float:
    """BM25 relevance of one chunk to a query."""
    qtoks = tokenize(query)
    toks = index["tokenized"][chunk_idx]
    dl = index["lengths"][chunk_idx]
    avgdl = index["avgdl"] or 1.0
    tf = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    score = 0.0
    for t in qtoks:
        if t not in index["idf"]:
            continue                       # df==0 -> unseen in corpus, contributes 0
        f = tf.get(t, 0)
        if f == 0:
            continue
        idf = index["idf"][t]
        denom = f + k1 * (1.0 - b + b * dl / avgdl)
        score += idf * (f * (k1 + 1.0)) / denom
    return score


def rerank_score(query: str, chunk: str) -> float:
    """Cross-encoder reranker PROXY.

    A real cross-encoder (e.g. ms-marco-MiniLM) feeds (query, chunk) jointly into
    a transformer and emits a relevance scalar. We approximate that with MATCH
    DENSITY: the fraction of the chunk's tokens that are content-bearing query
    terms. It rewards concise chunks packed with query-relevant words -- the same
    signal a cross-encoder learns, derivable in pure stdlib.
    """
    qcontent = [t for t in tokenize(query) if t not in STOPWORDS]
    ctoks = tokenize(chunk)
    if not qcontent or not ctoks:
        return 0.0
    qset = set(qcontent)
    matched = sum(1 for t in ctoks if t in qset)
    return matched / len(ctoks)


def hybrid_search(query: str, chunks: list[str], top_k: int,
                  alpha: float = 0.5) -> list[tuple[float, str]]:
    """Hybrid search = alpha * vector + (1-alpha) * BM25 (min-max normalized).

    Open WebUI's Knowledge feature combines BM25 (keyword) with vector (semantic)
    and then reranks. Here we show the combination step; the .py gold uses
    alpha=0.5 (equal weight). Scores are normalized to [0,1] before blending so
    the two scales are comparable.
    """
    qemb, _ = embed(query)
    vscores = [cosine(qemb, embed(c)[0]) for c in chunks]
    index = build_bm25_index(chunks)
    bscores = [bm25_score(query, i, index) for i in range(len(chunks))]

    def norm(xs: list[float]) -> list[float]:
        lo, hi = min(xs), max(xs)
        if hi - lo < 1e-12:
            return [1.0 for _ in xs] if hi > 0 else [0.0 for _ in xs]
        return [(x - lo) / (hi - lo) for x in xs]

    vn, bn = norm(vscores), norm(bscores)
    blended = sorted(
        ((alpha * v + (1.0 - alpha) * b, chunks[i])
         for i, (v, b) in enumerate(zip(vn, bn))),
        key=lambda t: (-t[0], t[1]),
    )
    return blended[:top_k]


def build_prompt(query: str, top_chunks: list[str],
                 template: str = "Context: {context}\n\nQuestion: {question}") -> str:
    """Inject retrieved chunks into the LLM prompt template.

    This is the final RAG step: the retrieved context is prepended so the model
    grounds its answer in the chunks instead of its training data.
    """
    context = "\n".join(f"- {c}" for c in top_chunks)
    return template.format(context=context, question=query)


# ============================================================================
# 4. SECTIONS  (the numbers that feed OPEN_WEBUI.md)
# ============================================================================

def section_a_what_it_is():
    banner("SECTION A: what Open WebUI is (frontend, not a model runner)")
    print("Open WebUI is a SELF-HOSTED WEB FRONTEND. It does not run models; it")
    print("connects to backends and adds RAG, tools, multi-user RBAC on top.\n")

    print("Backends it connects to (docs.openwebui.com/features):")
    print("| backend         | local/remote | endpoint                       | serves                  |")
    print("|-----------------|--------------|--------------------------------|-------------------------|")
    for name, kind, url, serves in BACKENDS:
        print(f"| {name:<15} | {kind:<12} | {url:<30} | {serves:<23} |")

    print("\nThe flagship feature set:")
    feats = [
        ("Multi-model chat", "talk to any model, switch mid-chat, run two side-by-side"),
        ("RAG / Knowledge", "upload docs -> chunk -> embed -> vector search -> inject"),
        ("Hybrid search", "BM25 (keyword) + vector (semantic) + cross-encoder rerank"),
        ("9 vector DBs", "ChromaDB, PGVector, Qdrant, Milvus, Elasticsearch, ..."),
        ("MCP", "Model Context Protocol: external tools the model can call"),
        ("Pipelines", "modular plugins that filter / transform / route messages"),
        ("Multi-user RBAC", "roles, groups, per-model access, SSO/OIDC/LDAP, SCIM"),
        ("Open Terminal", "AI writes + executes Python in a real environment"),
    ]
    for f, desc in feats:
        print(f"  * {f:<18} - {desc}")

    print("\nDeploy:")
    print("  pip install open-webui && open-webui serve   # one command")
    print("  docker run -d -p 3000:8080 ... ghcr.io/open-webui/open-webui:main")

    check("Open WebUI is a FRONTEND (does not run models itself)", True)
    check("connects to Ollama + any OpenAI-compatible backend", len(BACKENDS) >= 4)


def section_b_rag_pipeline_and_chunking():
    banner("SECTION B: the RAG pipeline + chunking strategies")
    print("RAG = give the model YOUR documents without stuffing them all in context.")
    print("The pipeline (Open WebUI's Knowledge feature):\n")
    print("  Document -> [CHUNK] -> [EMBED] -> [VECTOR DB]")
    print("  Query    -> [EMBED] -> [cosine top-k] -> [RERANK] -> [INJECT] -> [LLM]\n")

    print("CHUNKING is where retrieval quality is won or lost:")
    print("  * TOKEN-based  (e.g. 512 tokens): production default, good throughput.")
    print("  * SENTENCE-based: preserves meaning boundaries (no mid-sentence cuts).")
    print("  * OVERLAP (e.g. 50 tokens): repeats context at the seam so a fact split")
    print("    across two chunks is not lost. step = size - overlap.")
    print("  * too small -> lose context; too large -> dilute relevance + cost.\n")

    doc = GOLD_DOC
    print(f"Demo document ({len(doc.split())} words):")
    print(f"  {doc!r}\n")

    print("Chunk it at size=5, overlap=2 (step=3):")
    chunks = chunk_document(doc, GOLD_CHUNK_SIZE, GOLD_OVERLAP)
    print(f"| # | chunk                          | words |")
    print(f"|---|--------------------------------|-------|")
    for i, c in enumerate(chunks):
        print(f"| {i} | {c:<30} | {len(c.split()):<5} |")

    expected = ["The cat sat on the", "on the mat. The dog",
                "The dog ran in the", "in the park. Cats love",
                "Cats love fish."]
    check("chunks == gold (5 overlapping windows, step 3)", chunks == expected)

    print("\nEffect of chunk size on chunk count (overlap=2 fixed):")
    print("| size | overlap | step | #chunks |")
    print("|------|---------|------|---------|")
    for size in (3, 5, 7, 10):
        cs = chunk_words(doc.split(), size, 2)
        print(f"| {size:<4} | {2:<7} | {size-2:<4} | {len(cs):<7} |")
    print("Smaller chunks => more windows => finer recall but more embeddings to store.")


def section_c_embeddings_and_vector_search():
    banner("SECTION C: fake embeddings + cosine vector search")
    print("We cannot ship a real embedding model (nomic-embed-text, 768 dims) in pure")
    print("stdlib. Instead: the FEATURE-HASHING TRICK. Each word -> FNV-1a hash -> one")
    print(f"of {EMBED_DIM} dims -> count -> L2-normalize. Two texts sharing words land in")
    print("the same buckets, so cosine tracks lexical overlap. Deterministic (FNV-1a is")
    print("NOT Python's randomized hash()).\n")

    vocab = sorted(set(tokenize(GOLD_DOC) + tokenize(GOLD_QUERY)))
    print(f"Corpus vocabulary ({len(vocab)} words) -> hash bucket (mod {EMBED_DIM}):")
    seen: dict[int, str] = {}
    collisions = 0
    print("| word  | bucket |")
    print("|-------|--------|")
    for w in vocab:
        b = word_hash(w) % EMBED_DIM
        if b in seen:
            collisions += 1
            print(f"| {w:<5} | {b:<6} | !! collides with {seen[b]!r}")
        else:
            seen[b] = w
            print(f"| {w:<5} | {b:<6} |")
    check("zero hash collisions at DIM=256 (exact bag-of-words)", collisions == 0)

    chunks = chunk_document(GOLD_DOC, GOLD_CHUNK_SIZE, GOLD_OVERLAP)
    qemb, qtoks = embed(GOLD_QUERY)
    print(f"\nQuery: {GOLD_QUERY!r}  tokens={qtoks}")
    print(f"  non-zero dims of the query embedding: "
          f"{[word_hash(t) % EMBED_DIM for t in qtoks]}\n")

    print("Cosine similarity of each chunk to the query (sorted desc):")
    results = vector_search(qemb, chunks, len(chunks))
    print("| rank | cosine  | chunk                          |")
    print("|------|---------|--------------------------------|")
    for rank, (cs, c) in enumerate(results, 1):
        print(f"| {rank:<4} | {cs:<7.4f} | {c:<30} |")

    top = results[0]
    print(f"\nTop chunk: {top[1]!r}  (cosine = {top[0]:.4f})")
    check("top chunk == 'Cats love fish.'", top[1] == "Cats love fish.")
    check("top cosine == 0.2887 (1/(2*sqrt3))", abs(top[0] - 0.288675) < 1e-4)
    # the exact value: query has 4 unit terms, chunk has 3, they share 'cats'
    # cos = (1/sqrt4)*(1/sqrt3) = 0.5 * 0.577350 = 0.288675
    exact = (1.0 / math.sqrt(4)) * (1.0 / math.sqrt(3))
    check("recomputed exact cos == 0.288675", abs(top[0] - exact) < 1e-9)


def section_d_hybrid_search_and_rerank():
    banner("SECTION D: hybrid search (BM25 + vector) + cross-encoder rerank")
    print("Pure vector search misses exact keyword matches (a product code, a name).")
    print("BM25 is the classic keyword ranker; it rewards rare terms and short docs.")
    print("HYBRID = alpha*vector + (1-alpha)*BM25. Then a CROSS-ENCODER reranks the")
    print("top-k for precision. Open WebUI ships both.\n")

    chunks = chunk_document(GOLD_DOC, GOLD_CHUNK_SIZE, GOLD_OVERLAP)
    index = build_bm25_index(chunks)

    print("BM25 index stats (k1=1.5, b=0.75):")
    print(f"  N (chunks) = {index['n']},  avgdl = {index['avgdl']:.2f} tokens")
    print(f"  query content terms: "
          f"{[t for t in tokenize(GOLD_QUERY) if t not in STOPWORDS]}\n")

    print("| chunk                          | bm25  | vector  | rerank |")
    print("|--------------------------------|-------|---------|--------|")
    qemb, _ = embed(GOLD_QUERY)
    for i, c in enumerate(chunks):
        bm = bm25_score(GOLD_QUERY, i, index)
        vs = cosine(qemb, embed(c)[0])
        rr = rerank_score(GOLD_QUERY, c)
        print(f"| {c:<30} | {bm:<5.3f} | {vs:<7.4f} | {rr:<6.4f} |")

    print("\nHybrid blend (alpha=0.5, scores min-max normalized first):")
    hybrid = hybrid_search(GOLD_QUERY, chunks, len(chunks), alpha=0.5)
    print("| rank | hybrid | chunk                          |")
    print("|------|--------|--------------------------------|")
    for rank, (hs, c) in enumerate(hybrid, 1):
        print(f"| {rank:<4} | {hs:<6.4f} | {c:<30} |")

    print("\nRerank confirmation (top-3 candidates, cross-encoder proxy):")
    top3 = vector_search(qemb, chunks, 3)
    rr = sorted(((rerank_score(GOLD_QUERY, c), cs, c) for cs, c in top3),
                key=lambda t: (-t[0], t[1]))
    for rs, cs, c in rr:
        print(f"  rerank={rs:.4f}  (was cosine={cs:.4f})  {c!r}")

    check("BM25 top chunk == 'Cats love fish.'",
          max((bm25_score(GOLD_QUERY, i, index), c) for i, c in enumerate(chunks))[1]
          == "Cats love fish.")
    check("hybrid top chunk == 'Cats love fish.'", hybrid[0][1] == "Cats love fish.")
    check("rerank top chunk == 'Cats love fish.'", rr[0][2] == "Cats love fish.")


# --------------------------- THE GOLD CENTERPIECE ----------------------------

def section_gold():
    banner("SECTION G: GOLD RAG pipeline trace (the centerpiece)")
    print("Full end-to-end pipeline on the canonical example:\n")
    print(f"  Document : {GOLD_DOC!r}")
    print(f"  Query    : {GOLD_QUERY!r}")
    print(f"  Chunk    : size={GOLD_CHUNK_SIZE} words, overlap={GOLD_OVERLAP}, "
          f"step={GOLD_CHUNK_SIZE - GOLD_OVERLAP}\n")

    # STEP 1 -- chunk
    chunks = chunk_document(GOLD_DOC, GOLD_CHUNK_SIZE, GOLD_OVERLAP)
    print("STEP 1  CHUNK")
    for i, c in enumerate(chunks):
        print(f"        [{i}] {c!r}")

    # STEP 2 -- embed + store in the (fake) vector DB
    qemb, qtoks = embed(GOLD_QUERY)
    store = [embed(c)[0] for c in chunks]
    print(f"\nSTEP 2  EMBED  ({EMBED_DIM}-dim hashing vectors, L2-normalized)")
    print(f"        query tokens   = {qtoks}")
    print(f"        query non-zero = {[word_hash(t) % EMBED_DIM for t in qtoks]}")
    print(f"        vector DB now holds {len(store)} chunk vectors")

    # STEP 3 -- vector search top-k
    topk = vector_search(qemb, chunks, GOLD_TOP_K)
    print(f"\nSTEP 3  VECTOR SEARCH (cosine, top-{GOLD_TOP_K})")
    for rank, (cs, c) in enumerate(topk, 1):
        print(f"        {rank}. cos={cs:.4f}  {c!r}")

    # STEP 4 -- rerank
    reranked = sorted(topk, key=lambda t: (-rerank_score(GOLD_QUERY, t[1]), -t[0]))
    print(f"\nSTEP 4  RERANK (cross-encoder proxy: match density)")
    for rs, cs, c in ((rerank_score(GOLD_QUERY, t[1]), t[0], t[1]) for t in reranked):
        print(f"        rerank={rs:.4f} (cos={cs:.4f})  {c!r}")

    # STEP 5 -- inject into prompt
    top_chunks = [c for _, c in reranked[:1]]
    prompt = build_prompt(GOLD_QUERY, top_chunks)
    print(f"\nSTEP 5  INJECT into prompt template")
    print("        " + prompt.replace("\n", "\n        "))

    # STEP 6 -- simulated LLM answer (grounded in the injected context)
    answer = "Cats eat fish."
    print(f"\nSTEP 6  LLM generates (grounded in injected context):")
    print(f"        -> {answer!r}")

    # ---- GOLD checks ----
    expected_chunks = ["The cat sat on the", "on the mat. The dog",
                       "The dog ran in the", "in the park. Cats love",
                       "Cats love fish."]
    top_chunk = topk[0][1]
    top_cos = topk[0][0]
    exact_cos = (1.0 / math.sqrt(4)) * (1.0 / math.sqrt(3))

    print()
    check("chunks == gold (5 overlapping windows)", chunks == expected_chunks)
    check("top chunk == 'Cats love fish.'", top_chunk == "Cats love fish.")
    check("top cosine == 0.288675", abs(top_cos - exact_cos) < 1e-9)
    check("prompt contains the retrieved context",
          "Cats love fish." in prompt and GOLD_QUERY in prompt)

    print("\nGOLD (recomputed & badge-checked in open_webui.html):")
    print(f"  #chunks        = {len(chunks)}")
    print(f"  top chunk      = {top_chunk!r}")
    print(f"  top cosine     = {top_cos:.6f}")
    print(f"  simulated ans  = {answer!r}")
    return {"n_chunks": len(chunks), "top": top_chunk,
            "cos": top_cos, "gold_ok": (chunks == expected_chunks
                                        and top_chunk == "Cats love fish."
                                        and abs(top_cos - exact_cos) < 1e-9)}


# ============================================================================
# main
# ============================================================================

def main():
    print("open_webui.py - reference impl. All numbers below feed OPEN_WEBUI.md.")
    print("pure Python stdlib (no torch, no numpy, no sentence-transformers).")
    print("Simulates the Open WebUI RAG pipeline: chunk -> embed -> search -> rerank -> inject.")

    section_a_what_it_is()
    section_b_rag_pipeline_and_chunking()
    section_c_embeddings_and_vector_search()
    section_d_hybrid_search_and_rerank()
    gold = section_gold()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
