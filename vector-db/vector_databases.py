"""
vector_databases.py - Reference implementation of vector database fundamentals:
embedding representation (TF-IDF as a proxy), similarity metrics (cosine / dot
product / euclidean), ANN algorithms (brute force vs LSH vs HNSW), indexing
strategies (flat, IVF, PQ), and the Qdrant collection model.

This is the SINGLE SOURCE OF TRUTH for VECTOR_DATABASES.md. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

    python3 vector_databases.py > vector_databases_output.txt

Pure Python stdlib only. Deterministic (custom LCG RNG; no external deps, no
PYTHONHASHSEED dependence). The same logic is recomputed in JS by
vector_databases.html and gold-checked.
"""

from __future__ import annotations

import math


# ============================================================================
# DETERMINISTIC RNG - a tiny LCG (Numerical Recipes constants). We roll our
# own so every run is bit-identical and matches the JS in vector_databases.html.
# ============================================================================
class RNG:
    """32-bit linear congruential generator. RNG(42).next() is stable forever."""

    def __init__(self, seed: int = 42) -> None:
        self.state = seed & 0xFFFFFFFF

    def next(self) -> int:
        self.state = (1664525 * self.state + 1013904223) & 0xFFFFFFFF
        return self.state

    def uniform(self, lo: float = 0.0, hi: float = 1.0) -> float:
        return lo + (hi - lo) * (self.next() / 0xFFFFFFFF)

    def gauss(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        u1 = self.uniform(1e-10, 1.0)
        u2 = self.uniform(0.0, 1.0)
        return mu + sigma * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def randint(self, lo: int, hi: int) -> int:
        return lo + (self.next() % (hi - lo + 1))


# ============================================================================
# CORE VECTOR MATH - the three similarity metrics every vector DB supports.
# ============================================================================
def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def norm(a: list[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = norm(a), norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot(a, b) / (na * nb)


def euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def l2_sq(a: list[float], b: list[float]) -> float:
    """Squared euclidean - avoids the sqrt, used everywhere internally."""
    return sum((x - y) ** 2 for x, y in zip(a, b))


def normalize(a: list[float]) -> list[float]:
    n = norm(a)
    return [x / n for x in a] if n > 0 else a[:]


# ============================================================================
# SECTION A DATA - a tiny corpus for TF-IDF. Real embeddings come from a neural
# model (OpenAI, BGE, E5); TF-IDF is the mathematically-grounded proxy that
# needs no model and is fully reproducible here.
# ============================================================================
CORPUS = [
    "the cat sat on the mat",
    "the dog sat on the log",
    "cats and dogs are pets",
    "machine learning models use vectors",
    "vector databases store embeddings",
]


def tokenize(text: str) -> list[str]:
    return text.lower().split()


def build_tfidf(corpus: list[str]):
    """Build TF-IDF vectors for a corpus.

    For term t in document d:
        tf(t, d)      = count of t in d
        idf(t)        = log(N / df(t))      (N = #documents, df = #docs containing t)
        tfidf(t, d)   = tf(t, d) * idf(t)

    Each document becomes a |vocab|-dimensional sparse vector. This is the
    classic sparse retrieval baseline; dense embedding models replace the
    tf-idf values with learned float weights but keep the SAME cosine metric.
    """
    n = len(corpus)
    tokenized = [tokenize(doc) for doc in corpus]
    vocab = sorted({w for toks in tokenized for w in toks})
    vidx = {w: i for i, w in enumerate(vocab)}
    dim = len(vocab)

    df = [0] * dim
    for toks in tokenized:
        for w in set(toks):
            df[vidx[w]] += 1
    idf = [math.log(n / df[i]) if df[i] > 0 else 0.0 for i in range(dim)]

    vectors = []
    for toks in tokenized:
        v = [0.0] * dim
        for w in toks:
            v[vidx[w]] += 1.0
        for i in range(dim):
            v[i] *= idf[i]
        vectors.append(v)
    return vocab, idf, vectors


# ============================================================================
# BRUTE FORCE kNN - the exact ground truth. O(n*d) per query, 100% recall.
# Used to MEASURE how well the ANN algorithms approximate it.
# ============================================================================
def brute_force_knn(points: list[list[float]], query: list[float], k: int):
    scored = sorted(range(len(points)), key=lambda i: l2_sq(query, points[i]))
    dists = [math.sqrt(l2_sq(query, points[i])) for i in scored[:k]]
    return scored[:k], dists


# ============================================================================
# LSH - Locality-Sensitive Hashing via random hyperplane (SimHash) projections.
# Two vectors hashing to the same bit-string likely have a small angle between
# them. Collision probability = (1 - angle/pi). Search checks only candidates
# in the query's bucket (and optionally Hamming-close buckets).
# ============================================================================
def lsh_build(points: list[list[float]], n_planes: int, rng: RNG):
    dim = len(points[0])
    planes = [[rng.gauss(0.0, 1.0) for _ in range(dim)] for _ in range(n_planes)]

    def hash_of(v: list[float]) -> int:
        bits = 0
        for i, p in enumerate(planes):
            if dot(v, p) >= 0.0:
                bits |= (1 << i)
        return bits

    buckets: dict[int, list[int]] = {}
    for idx, v in enumerate(points):
        buckets.setdefault(hash_of(v), []).append(idx)
    return planes, buckets, hash_of


def lsh_search(points, query, planes, buckets, hash_of, k, hamming=0):
    qh = hash_of(query)
    candidates: list[int] = []
    # same bucket + Hamming-distance<=hamming buckets
    for h, idxs in buckets.items():
        if bin(qh ^ h).count("1") <= hamming:
            candidates.extend(idxs)
    # exact distance over candidates only
    scored = sorted(candidates, key=lambda i: l2_sq(query, points[i]))
    res = scored[:k]
    dists = [math.sqrt(l2_sq(query, points[i])) for i in res]
    n_dist = len(candidates)  # distance computations done
    return res, dists, n_dist


# ============================================================================
# HNSW - Hierarchical Navigable Small World. A multi-layer proximity graph:
# layer 0 holds every node; upper layers hold exponentially fewer nodes
# (assigned via floor(-ln(uniform) * mL)). Search starts at the top entry
# point and greedily descends, widening the beam to efSearch at layer 0.
# ============================================================================
def hnsw_assign_layers(n: int, m: int, rng: RNG):
    mL = 1.0 / math.log(m) if m > 1 else 1.0
    layers = []
    for _ in range(n):
        u = rng.uniform(1e-10, 1.0)
        layers.append(int(-math.log(u) * mL))
    return layers, mL


def hnsw_build_layer0(points: list[list[float]], m: int):
    """Build a kNN graph at layer 0: each node connects to its M nearest."""
    n = len(points)
    graph: dict[int, list[int]] = {}
    for i in range(n):
        order = sorted(range(n), key=lambda j: l2_sq(points[i], points[j]))
        graph[i] = [j for j in order if j != i][:m]
    return graph


def hnsw_search(points, graph, layers, query, entry, k, ef):
    """Greedy best-first search on the layer-0 graph with beam width ef.
    Returns (top-k indices, distances, #distance_computations)."""
    visited = {entry}
    d0 = l2_sq(query, points[entry])
    n_dist = 1
    frontier = [(d0, entry)]
    result = [(d0, entry)]
    while frontier:
        frontier.sort()
        if len(result) >= ef and frontier and frontier[0][0] > result[-1][0] and len(result) >= ef:
            break
        _, node = frontier.pop(0)
        for nb in graph.get(node, []):
            if nb not in visited:
                visited.add(nb)
                nd = l2_sq(query, points[nb])
                n_dist += 1
                frontier.append((nd, nb))
                result.append((nd, nb))
                result.sort()
                if len(result) > ef:
                    result = result[:ef]
    result.sort()
    top = result[:k]
    idxs = [n for _, n in top]
    dists = [math.sqrt(d) for d, _ in top]
    return idxs, dists, n_dist


# ============================================================================
# K-MEANS (Lloyd's algorithm) - the engine behind IVF clustering and PQ
# subvector codebooks.
# ============================================================================
def kmeans(points: list[list[float]], k: int, rng: RNG, max_iter: int = 25):
    n = len(points)
    dim = len(points[0])
    # init: pick k distinct points as centroids (k-means++ is overkill here)
    picks: list[int] = []
    while len(picks) < k and len(picks) < n:
        c = rng.randint(0, n - 1)
        if c not in picks:
            picks.append(c)
    centroids = [points[c][:] for c in picks]
    if len(centroids) < k:
        k = len(centroids)

    assignment = [0] * n
    for _ in range(max_iter):
        moved = False
        # assign
        for i in range(n):
            best = min(range(k), key=lambda c: l2_sq(points[i], centroids[c]))
            if assignment[i] != best:
                assignment[i] = best
                moved = True
        # update
        sums = [[0.0] * dim for _ in range(k)]
        counts = [0] * k
        for i in range(n):
            c = assignment[i]
            counts[c] += 1
            for j in range(dim):
                sums[c][j] += points[i][j]
        for c in range(k):
            if counts[c] > 0:
                new_c = [sums[c][j] / counts[c] for j in range(dim)]
                if l2_sq(new_c, centroids[c]) > 1e-12:
                    moved = True
                centroids[c] = new_c
        if not moved:
            break
    return centroids, assignment


# ============================================================================
# IVF - Inverted File Index. K-means partitions the space into nlist cells;
# search probes only the nprobe nearest cells to the query.
# ============================================================================
def ivf_build(points: list[list[float]], nlist: int, rng: RNG):
    centroids, assign = kmeans(points, nlist, rng)
    cells: dict[int, list[int]] = {}
    for i, c in enumerate(assign):
        cells.setdefault(c, []).append(i)
    return centroids, cells


def ivf_search(points, centroids, cells, query, k, nprobe):
    # find nprobe nearest centroids
    corder = sorted(range(len(centroids)), key=lambda c: l2_sq(query, centroids[c]))
    probe = corder[:nprobe]
    candidates: list[int] = []
    for c in probe:
        candidates.extend(cells.get(c, []))
    scored = sorted(candidates, key=lambda i: l2_sq(query, points[i]))
    res = scored[:k]
    dists = [math.sqrt(l2_sq(query, points[i])) for i in res]
    return res, dists, len(candidates)


# ============================================================================
# PRODUCT QUANTIZATION - split each vector into m subvectors; run k-means on
# each sub-dimension to build m codebooks of ksub centroids. Each subvector is
# replaced by a 1-byte code (its nearest centroid index). Reconstruct = glue
# the centroids back together.
# ============================================================================
def pq_train(vectors: list[list[float]], m: int, ksub: int, rng: RNG):
    dim = len(vectors[0])
    sub_dim = dim // m
    codebooks: list[list[list[float]]] = []
    for s in range(m):
        lo = s * sub_dim
        subs = [[v[lo + j] for j in range(sub_dim)] for v in vectors]
        cents, _ = kmeans(subs, ksub, rng)
        codebooks.append(cents)
    return codebooks, sub_dim


def pq_encode_one(v: list[float], codebooks: list, sub_dim: int) -> list[int]:
    m = len(codebooks)
    code = [0] * m
    for s in range(m):
        lo = s * sub_dim
        sub = [v[lo + j] for j in range(sub_dim)]
        best = min(range(len(codebooks[s])), key=lambda c: l2_sq(sub, codebooks[s][c]))
        code[s] = best
    return code


def pq_reconstruct(code: list[int], codebooks: list, sub_dim: int) -> list[float]:
    out: list[float] = []
    for s in range(len(codebooks)):
        out.extend(codebooks[s][code[s]])
    return out


def recall_at_k(truth: list[int], approx: list[int]) -> float:
    if not truth:
        return 0.0
    t = set(truth[: len(approx)])
    got = set(approx)
    return len(t & got) / len(t)


# ============================================================================
# SECTION A - EMBEDDINGS: TF-IDF as a proxy for learned embeddings
# ============================================================================
def section_a() -> None:
    print("=" * 72)
    print("SECTION A - Embeddings: TF-IDF as a proxy representation")
    print("=" * 72)
    print()
    print("A real embedding model (OpenAI, BGE, E5) maps text to a dense float")
    print("vector in a learned latent space. TF-IDF is the mathematically exact")
    print("proxy that needs no model and is fully reproducible here. The SAME")
    print("cosine metric applies to both.")
    print()
    vocab, idf, vecs = build_tfidf(CORPUS)
    n = len(CORPUS)
    print(f"Corpus: {n} documents, vocabulary size = {len(vocab)} dims")
    print()
    toks = [tokenize(d) for d in CORPUS]
    df_map = {w: sum(1 for t in toks if w in set(t)) for w in vocab}
    print("  idf(term) = log(N / df):")
    print(f"  {'term':<14}{'df':>3}{'idf':>9}")
    print("  " + "-" * 26)
    for w in vocab:
        idfw = math.log(n / df_map[w]) if df_map[w] > 0 else 0.0
        print(f"  {w:<14}{df_map[w]:>3}{idfw:>9.3f}")
    print()
    print("Document 0 TF-IDF vector (nonzero terms):")
    d0 = vecs[0]
    nz = [(vocab[i], d0[i]) for i in range(len(vocab)) if abs(d0[i]) > 1e-9]
    for w, val in nz:
        print(f"  {w:<14}{val:>7.3f}")
    print(f"  norm(doc0) = {norm(d0):.3f}")
    print()
    print("A document with zero vector norm means it has no terms that carry")
    print("idf weight above zero (all-stopword docs). Here every doc has signal.")
    print()


# ============================================================================
# SECTION B - SIMILARITY METRICS
# ============================================================================
def section_b() -> None:
    print("=" * 72)
    print("SECTION B - Similarity metrics: cosine, dot product, euclidean")
    print("=" * 72)
    print()
    print("Three metrics; every vector DB supports all three. For L2-normalized")
    print("vectors (norm=1), cosine == dot product exactly -- so most text systems")
    print("use the faster dot product with no quality loss.")
    print()
    a = [1.0, 2.0, 3.0]
    b = [4.0, 5.0, 6.0]
    print(f"  A = {a}")
    print(f"  B = {b}")
    print()
    print(f"  dot(A,B)    = sum(a_i*b_i)            = {dot(a, b):.1f}")
    print(f"  ||A||       = sqrt(sum(a_i^2))        = {norm(a):.4f}")
    print(f"  ||B||                                 = {norm(b):.4f}")
    print(f"  cosine(A,B) = dot / (||A||*||B||)      = {cosine(a, b):.4f}")
    print(f"  euclid(A,B) = sqrt(sum((a_i-b_i)^2))   = {euclidean(a, b):.4f}")
    print()
    print("Identity check: euclidean^2 = ||A||^2 + ||B||^2 - 2*dot(A,B)")
    lhs = l2_sq(a, b)
    rhs = norm(a) ** 2 + norm(b) ** 2 - 2 * dot(a, b)
    print(f"  L2^2 = {lhs:.3f}   ||A||^2+||B||^2-2dot = {rhs:.3f}   match={abs(lhs - rhs) < 1e-9}")
    print()
    # L2-normalized equivalence
    na, nb = normalize(a), normalize(b)
    print("After L2-normalization (||A||=||B||=1):")
    print(f"  cosine(nA,nB) = {cosine(na, nb):.4f}")
    print(f"  dot(nA,nB)    = {dot(na, nb):.4f}   <-- identical (within float eps)")
    print()
    # corpus pairwise cosine
    print("Pairwise cosine between corpus documents (TF-IDF vectors):")
    _, _, vecs = build_tfidf(CORPUS)
    print("        " + "".join(f"  d{j}" for j in range(len(vecs))))
    for i in range(len(vecs)):
        row = f"  d{i}  "
        for j in range(len(vecs)):
            row += f"  {cosine(vecs[i], vecs[j]):.2f}"
        print(row)
    print()
    print("  d0 & d1 ('cat/dog sat on mat/log') share structure -> high cosine.")
    print("  d0 & d4 share almost no terms -> low cosine. This is semantic search.")
    print()


# ============================================================================
# SECTION C - ANN ALGORITHMS: brute force vs LSH vs HNSW
# ============================================================================
def make_points(rng: RNG, n_centers: int = 4, per_center: int = 4, dim: int = 6):
    centers = [[rng.uniform(-1.0, 1.0) for _ in range(dim)] for _ in range(n_centers)]
    points: list[list[float]] = []
    labels: list[int] = []
    for ci in range(n_centers):
        for _ in range(per_center):
            p = [centers[ci][j] + rng.gauss(0.0, 0.20) for j in range(dim)]
            points.append(p)
            labels.append(ci)
    return points, labels


def section_c() -> None:
    print("=" * 72)
    print("SECTION C - ANN algorithms: brute force vs LSH vs HNSW")
    print("=" * 72)
    print()
    print("Exact (brute force) is O(n) per query. ANN trades a little recall for")
    print("speed: LSH hashes similar vectors into the same bucket; HNSW walks a")
    print("multi-layer proximity graph. We measure recall@k against brute force.")
    print()
    rng = RNG(2024)
    points, labels = make_points(rng, n_centers=4, per_center=4, dim=6)
    n = len(points)
    print(f"Dataset: {n} points in 6 dims, 4 clusters (deterministic seed).")
    print()
    query = [points[0][j] + rng.gauss(0.0, 0.10) for j in range(6)]
    k = 3
    print(f"Query = point[0] + small noise. k = {k}.")
    print()

    # ---- brute force ----
    truth, truth_d = brute_force_knn(points, query, k)
    print("Brute force (exact ground truth, 100% recall, n distance comps):")
    print(f"  top-{k} = {truth}   dists = [{', '.join(f'{d:.3f}' for d in truth_d)}]")
    print(f"  distance computations = {n}")
    print()

    # ---- LSH ----
    rng2 = RNG(7)
    planes, buckets, hash_of = lsh_build(points, n_planes=6, rng=rng2)
    lsh_res, lsh_d, lsh_ndist = lsh_search(points, query, planes, buckets, hash_of, k, hamming=1)
    lsh_recall = recall_at_k(truth, lsh_res)
    print("LSH (6 random hyperplanes, Hamming<=1 bucket expansion):")
    print(f"  top-{k} = {lsh_res}   dists = [{', '.join(f'{d:.3f}' for d in lsh_d)}]")
    print(f"  distance computations = {lsh_ndist}   recall@{k} = {lsh_recall:.2f}")
    print(f"  ({len(buckets)} buckets; bucket sizes: {sorted(len(v) for v in buckets.values())})")
    print()

    # ---- HNSW ----
    rng3 = RNG(99)
    layers, mL = hnsw_assign_layers(n, m=4, rng=rng3)
    graph = hnsw_build_layer0(points, m=4)
    entry = 0
    hnsw_res, hnsw_d, hnsw_ndist = hnsw_search(points, graph, layers, query, entry, k, ef=8)
    hnsw_recall = recall_at_k(truth, hnsw_res)
    print("HNSW (M=4, efSearch=8, mL=1/ln(4)=%.3f):" % mL)
    print(f"  layer assignment: {layers}")
    print(f"  top-{k} = {hnsw_res}   dists = [{', '.join(f'{d:.3f}' for d in hnsw_d)}]")
    print(f"  distance computations = {hnsw_ndist}   recall@{k} = {hnsw_recall:.2f}")
    print()

    print("Comparison:")
    print(f"  {'algorithm':<14}{'dists':>7}{'recall@' + str(k):>12}")
    print("  " + "-" * 33)
    print(f"  {'brute force':<14}{n:>7}{1.00:>12.2f}")
    print(f"  {'LSH':<14}{lsh_ndist:>7}{lsh_recall:>12.2f}")
    print(f"  {'HNSW':<14}{hnsw_ndist:>7}{hnsw_recall:>12.2f}")
    print()
    print("HNSW visits far fewer points than brute force while keeping recall")
    print("high; LSH is faster to build but recall depends heavily on the number")
    print("of planes / Hamming expansion. This is why HNSW is the 2025-2026")
    print("production default in Qdrant, Weaviate, Milvus, pgvector, Faiss.")
    print()


# ============================================================================
# SECTION D - INDEXING STRATEGIES: flat, IVF, PQ
# ============================================================================
def section_d() -> None:
    print("=" * 72)
    print("SECTION D - Indexing strategies: flat, IVF, product quantization")
    print("=" * 72)
    print()
    print("FLAT = brute force (100% recall, O(n)). IVF = k-means partitions,")
    print("probe nprobe of them. PQ = compress vectors via subvector codebooks.")
    print()
    rng = RNG(55)
    points, _ = make_points(rng, n_centers=4, per_center=4, dim=6)
    n = len(points)
    query = points[3]
    k = 3

    truth, truth_d = brute_force_knn(points, query, k)
    print(f"Ground truth top-{k} (flat, exact): {truth}")
    print()

    # ---- IVF ----
    rng_ivf = RNG(11)
    centroids, cells = ivf_build(points, nlist=4, rng=rng_ivf)
    ivf_res, ivf_d, ivf_ndist = ivf_search(points, centroids, cells, query, k, nprobe=1)
    ivf_r1 = recall_at_k(truth, ivf_res)
    ivf_res2, ivf_d2, ivf_ndist2 = ivf_search(points, centroids, cells, query, k, nprobe=2)
    ivf_r2 = recall_at_k(truth, ivf_res2)
    print("IVF (nlist=4 partitions via k-means):")
    print(f"  cell sizes: {sorted(len(v) for v in cells.values())}")
    print(f"  nprobe=1 -> top-{k}={ivf_res} recall={ivf_r1:.2f} ({ivf_ndist} dist comps)")
    print(f"  nprobe=2 -> top-{k}={ivf_res2} recall={ivf_r2:.2f} ({ivf_ndist2} dist comps)")
    print("  (nprobe=nlist collapses to brute force: 100% recall.)")
    print()

    # ---- PQ ----
    rng_pq = RNG(3)
    m = 3
    ksub = 4
    codebooks, sub_dim = pq_train(points, m=m, ksub=ksub, rng=rng_pq)
    codes = [pq_encode_one(v, codebooks, sub_dim) for v in points]
    recon = [pq_reconstruct(c, codebooks, sub_dim) for c in codes]
    # reconstruction error
    errs = [euclidean(points[i], recon[i]) for i in range(n)]
    mean_err = sum(errs) / n
    orig_bytes = n * 6 * 4
    pq_bytes = n * m
    print(f"PQ (m={m} subvectors, ksub={ksub} centroids each):")
    print(f"  codes: {codes}")
    print(f"  original size = {n}*6 dims*4 bytes = {orig_bytes} bytes")
    print(f"  PQ size       = {n}*{m} bytes       = {pq_bytes} bytes")
    print(f"  compression ratio = {orig_bytes / pq_bytes:.1f}x")
    print(f"  mean reconstruction error (L2) = {mean_err:.3f}")
    # PQ-based search: distance via reconstructed vectors (ADC simplified)
    pq_dists = sorted(range(n), key=lambda i: l2_sq(query, recon[i]))
    pq_res = pq_dists[:k]
    pq_recall = recall_at_k(truth, pq_res)
    print(f"  PQ top-{k} = {pq_res}   recall@{k} = {pq_recall:.2f}")
    print()
    print("PQ trades recall for massive memory savings (32-256x). Pair with IVF")
    print("(IVF-PQ) for >10M vectors where memory is the bottleneck.")
    print()


# ============================================================================
# SECTION E - QDRANT COLLECTION MODEL + GOTCHAS
# ============================================================================
def section_e() -> None:
    print("=" * 72)
    print("SECTION E - Qdrant collection model + killer gotchas")
    print("=" * 72)
    print()
    print("A Qdrant collection holds points. Each point = (id, vector, payload).")
    print("search(query_vector, k, filter) returns the k nearest matching points.")
    print()
    rng = RNG(8)
    points, labels = make_points(rng, n_centers=2, per_center=3, dim=4)
    collection = []
    for i in range(len(points)):
        collection.append({
            "id": i + 1,
            "vector": [round(x, 3) for x in points[i]],
            "payload": {"cluster": "A" if labels[i] == 0 else "B"},
        })
    print("Collection 'demo' (2D-projected for printing, real dims=4):")
    for p in collection:
        print(f"  id={p['id']}  vec={[round(x,2) for x in p['vector']]}  payload={p['payload']}")
    print()

    query = [round(x, 3) for x in points[0]]
    print(f"search(query=point1, k=3)  -- no filter:")
    res, dists = brute_force_knn(points, query, 3)
    for i, d in zip(res, dists):
        print(f"  id={collection[i]['id']}  cosine={cosine(query, points[i]):.3f}  payload={collection[i]['payload']}")
    print()

    print("search(query, k=3, filter={cluster:'B'})  -- PAYLOAD FILTER (post-filter):")
    filtered_idx = [i for i, p in enumerate(collection) if p["payload"]["cluster"] == "B"]
    fvecs = [points[i] for i in filtered_idx]
    fres, fdists = brute_force_knn(fvecs, query, min(3, len(filtered_idx)))
    for r, d in zip(fres, fdists):
        orig_i = filtered_idx[r]
        print(f"  id={collection[orig_i]['id']}  cosine={cosine(query, points[orig_i]):.3f}  payload={collection[orig_i]['payload']}")
    print()

    print("Memory estimation (the interview math):")
    nv, dimv = 1_000_000, 1024
    raw = nv * dimv * 4
    hnsw_edges = nv * 16 * 4
    sq = nv * dimv * 1
    pq_mem = nv * 64
    print(f"  1M vectors, 1024 dims:")
    print(f"    raw float32          = {raw / 1e9:.2f} GB")
    print(f"    HNSW edges (M=16)    = {hnsw_edges / 1e9:.2f} GB")
    print(f"    scalar quant (uint8) = {sq / 1e9:.2f} GB  (4x compression)")
    print(f"    PQ (m=64)            = {pq_mem / 1e6:.0f} MB   ({raw / pq_mem:.0f}x compression)")
    print()
    print("Killer gotchas")
    print("--------------")
    print("  1. NEVER MIX embedding models in one index. Vectors from different")
    print("     models live in different latent spaces -> cosine is meaningless.")
    print("     Upgrading a model requires re-embedding the ENTIRE corpus.")
    print("  2. For L2-NORMALIZED vectors, cosine == dot product. Use the faster")
    print("     dot-product index; results are identical.")
    print("  3. POST-FILTER can return < k results when the filter is selective")
    print("     (< 1% match). Pre-filter or use Qdrant's filterable HNSW.")
    print("  4. CURSE OF DIMENSIONALITY: above ~2048 dims, distances converge and")
    print("     ANN quality degrades. Use PCA or lower-dim embedding models.")
    print("  5. HNSW memory scales with BOTH n and M. 10M vectors -> 60+ GB RAM.")
    print("     Use scalar/PQ quantization to cut this 4-32x.")
    print("  6. RRF (hybrid search): score(d) = sum_r 1/(k + rank_r(d)), k=60.")
    print("     No training, robust to scale differences, handles missing docs.")
    print()


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()

    # ---- assertions (all deterministic) ----
    # metrics
    assert abs(dot([1, 2, 3], [4, 5, 6]) - 32.0) < 1e-9
    assert abs(cosine([1, 2, 3], [4, 5, 6]) - 32.0 / (norm([1, 2, 3]) * norm([4, 5, 6]))) < 1e-9
    assert abs(euclidean([1, 2, 3], [4, 5, 6]) - math.sqrt(27)) < 1e-9
    # L2-normalized equivalence
    na, nb = normalize([1.0, 2.0, 3.0]), normalize([4.0, 5.0, 6.0])
    assert abs(cosine(na, nb) - dot(na, nb)) < 1e-9
    # euclidean identity
    a, b = [1.0, 2.0, 3.0], [4.0, 5.0, 6.0]
    assert abs(l2_sq(a, b) - (norm(a) ** 2 + norm(b) ** 2 - 2 * dot(a, b))) < 1e-9

    # tfidf
    vocab, idf, vecs = build_tfidf(CORPUS)
    assert len(vocab) > 0
    assert all(norm(v) > 0 for v in vecs)

    # brute force deterministic
    rng = RNG(2024)
    pts, _ = make_points(rng, 4, 4, 6)
    q = [pts[0][j] + RNG(2024).gauss(0, 0.1) for j in range(6)]
    res, _ = brute_force_knn(pts, q, 3)
    assert len(res) == 3

    # LSH builds buckets
    rng2 = RNG(7)
    planes, buckets, hf = lsh_build(pts, 6, rng2)
    assert sum(len(v) for v in buckets.values()) == len(pts)

    # HNSW deterministic
    rng3 = RNG(99)
    layers, mL = hnsw_assign_layers(len(pts), 4, rng3)
    assert len(layers) == len(pts)
    assert abs(mL - 1.0 / math.log(4)) < 1e-9
    graph = hnsw_build_layer0(pts, 4)
    assert all(len(graph[i]) <= 4 for i in graph)

    # kmeans / IVF
    c, a = kmeans(pts, 4, RNG(11))
    assert len(c) == 4
    cents, cells = ivf_build(pts, 4, RNG(11))
    assert sum(len(v) for v in cells.values()) == len(pts)

    # PQ
    cb, sd = pq_train(pts, 3, 4, RNG(3))
    assert len(cb) == 3
    code = pq_encode_one(pts[0], cb, sd)
    assert len(code) == 3
    rec = pq_reconstruct(code, cb, sd)
    assert len(rec) == len(pts[0])

    # recall sanity
    assert recall_at_k([0, 1, 2], [0, 1, 2]) == 1.0
    assert recall_at_k([0, 1, 2], [0, 3, 4]) == (1 / 3) + 1e-15 - 1e-15  # 1/3
    assert abs(recall_at_k([0, 1, 2], [0, 1, 5]) - 2 / 3) < 1e-9

    print("=" * 72)
    print("[check] metrics / tfidf / brute / LSH / HNSW / IVF / PQ ... OK")
    print("=" * 72)
