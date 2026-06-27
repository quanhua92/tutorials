# Vector Databases — Embeddings, Similarity, ANN, Indexing & the Qdrant Model — A Worked-Example Guide

> **Companion code:** [`vector_databases.py`](https://github.com/quanhua92/tutorials/blob/main/vector-db/vector_databases.py). **Every number is printed by
> `python3 vector_databases.py`** — nothing is hand-computed.
>
> **Live demo:** [`vector_databases.html`](https://github.com/quanhua92/tutorials/blob/main/vector-db/vector_databases.html) — open in a browser: visualize 2D embeddings, compute similarity metrics, and compare ANN algorithm recall live.
>
> **Dashboard:** [`index.html`](https://github.com/quanhua92/tutorials/blob/main/vector-db/index.html) — the front door to this suite.

---

## 0. TL;DR — the one idea

> **The analogy (read this first):** A traditional database answers *"which rows match this filter?"* — exact, structured, O(log n) on an index. A **vector database** answers *"which items are *semantically* similar to this query?"* by storing high-dimensional float vectors and returning the `k` nearest ones under a similarity metric. The whole field is one mechanism reused five ways: **embed → store → measure distance → approximate the search → quantize for memory**.

```
query text ──embedding model──> query vector
                                       │
                            ┌──────────▼──────────┐
                            │  ANN search (HNSW)  │──> top-k nearest vectors ──> payloads
                            └─────────────────────┘
```

Five competencies all hang off this pipeline — change *how* each stage works:

| Stage | This guide's section | What changes |
|---|---|---|
| Embed | §1 (TF-IDF proxy) | what the vector *is* |
| Measure | §2 (similarity metrics) | the distance function |
| Search | §3 (brute force vs LSH vs HNSW) | exact vs approximate |
| Index | §4 (flat, IVF, PQ) | speed/memory trade-off |
| Store | §5 (Qdrant model) | collection, payload, filter |

---

### Pattern Recognition Signals

| Signal in the system description | → Use this approach |
|---|---|
| "find documents *about* X", semantic search, RAG retrieval | ✓ dense vector embeddings + cosine similarity |
| "users similar to Y", recommendations | ✓ user/item embeddings + ANN |
| "invoice #12345", exact keyword match | ✗ use BM25 / traditional DB, **not** vectors |
| corpus < 100K, recall must be perfect | ✓ Flat index (brute force) |
| 100K–10M vectors, real-time updates | ✓ HNSW (M=16–32) |
| 10M+ vectors, memory is the bottleneck | ✓ IVF-PQ (k-means + quantization) |
| need ACID joins with the vectors | ✓ pgvector on existing Postgres |
| hybrid: semantic **and** keyword | ✓ dense + BM25 + RRF fusion |

---

## 1. Embeddings — TF-IDF as a proxy representation

> **The core mechanism:** an embedding maps a piece of text/image/audio to a fixed-length float vector in a latent space where "semantic closeness" = "small distance". Real systems use neural models (OpenAI `text-embedding-3-small`, BGE-large, E5); **TF-IDF** is the mathematically exact, model-free proxy that is fully reproducible here. The cosine metric applies to both identically.

### Worked example — a 5-document corpus, TF-IDF vectors

> From `vector_databases.py` Section A. Vocabulary = 21 terms (the union of all tokens).

**idf(term) = log(N / df)** where N=5 documents, df = documents containing the term:

| term | df | idf |
|---|---|---|
| the / on / sat | 2 | 0.916 |
| cat, dog, machine, vector, … (17 single-doc terms) | 1 | 1.609 |

**Document 0** ("the cat sat on the mat") TF-IDF vector (nonzero terms):

| term | tf-idf |
|---|---|
| the | 1.833 |
| cat | 1.609 |
| mat | 1.609 |
| on | 0.916 |
| sat | 0.916 |

`norm(doc0) = 3.197`. Common terms (the/on/sat) get down-weighted by idf; distinctive terms (cat/mat) dominate. **This is exactly what a learned embedding does — just with neural weights instead of idf.**

---

## 2. Similarity metrics — cosine, dot product, euclidean

> **The core mechanism:** three distance functions; every vector DB supports all three. For **L2-normalized** vectors (‖A‖=‖B‖=1), cosine similarity == dot product **exactly** — so most text systems pre-normalize and use the faster dot-product index with zero quality loss.

### Worked example — A=[1,2,3], B=[4,5,6]

> From `vector_databases.py` Section B.

| quantity | formula | value |
|---|---|---|
| dot(A,B) | Σ aᵢbᵢ | **32.0** |
| ‖A‖ | √Σaᵢ² | 3.7417 |
| ‖B‖ | √Σbᵢ² | 8.7750 |
| **cosine(A,B)** | dot/(‖A‖·‖B‖) | **0.9746** |
| **euclidean(A,B)** | √Σ(aᵢ−bᵢ)² | **5.1962** |

**Identity check:** euclidean² = ‖A‖² + ‖B‖² − 2·dot(A,B). `L2² = 27.000`, RHS = `27.000` — match ✓.

After L2-normalization: `cosine(nA,nB) = 0.9746`, `dot(nA,nB) = 0.9746` — **identical**.

### Pairwise cosine — the 5-document TF-IDF corpus

| | d0 | d1 | d2 | d3 | d4 |
|---|---|---|---|---|---|
| **d0** | 1.00 | **0.49** | 0.00 | 0.00 | 0.00 |
| **d1** | 0.49 | 1.00 | 0.00 | 0.00 | 0.00 |
| **d2** | 0.00 | 0.00 | 1.00 | 0.00 | 0.00 |

`d0` & `d1` ("the cat/dog sat on the mat/log") share structure → **high cosine (0.49)**. `d0` & `d4` share almost no terms → 0.00. **This is semantic search in three lines of math.**

---

## 3. ANN algorithms — brute force vs LSH vs HNSW

> **The core mechanism:** exact (brute force) is O(n) per query — too slow for millions of vectors. ANN trades a little recall for speed: **LSH** hashes similar vectors into the same bucket; **HNSW** walks a multi-layer proximity graph. We measure **recall@k** = |ANN top-k ∩ brute top-k| / k.

### Worked example — 16 points in 6 dims, 4 clusters, k=3

> From `vector_databases.py` Section C. Query = point[0] + small noise. Ground truth (brute force): top-3 = `[0, 3, 1]`, dists = `[0.246, 0.526, 0.540]`.

| algorithm | distance computations | recall@3 | top-3 |
|---|---|---|---|
| **brute force** | 16 | 1.00 | [0, 3, 1] |
| **LSH** (6 hyperplanes, Hamming≤1) | 8 | 1.00 | [0, 3, 1] |
| **HNSW** (M=4, efSearch=8) | 9 | 1.00 | [0, 3, 1] |

HNSW layer assignment (mL = 1/ln(4) = 0.721): `[0,0,0,0,0,0,2,0,0,0,0,0,0,1,0,0]` — most nodes at layer 0, a handful reach the upper layers (the "zoom out" long-range edges).

**LSH bucket sizes:** `[1,1,2,2,2,8]` — 6 buckets for 16 points; the search only distances-computes the 8 candidates in nearby buckets instead of all 16.

**Why HNSW wins in production:** it visits far fewer points than brute force while keeping recall high, and supports incremental insertion (online updates). This is why HNSW is the 2025-2026 default in Qdrant, Weaviate, Milvus, pgvector, and Faiss.

### LSH — random hyperplane (SimHash)

Each of `n_planes` random hyperplanes votes ±1 (sign of dot product). The bit-string is the hash. Two vectors hashing identically likely have a small angle between them; collision probability = `1 − angle/π`. Search checks the query's bucket plus Hamming-`h` neighbors.

### HNSW — the hierarchy

- **Layer 0**: every node, up to `M_max0 = 2·M` neighbors.
- **Layers 1…L**: exponentially fewer nodes, `M` neighbors each (long-range edges).
- **Layer assignment**: `floor(−ln(uniform) · mL)`, `mL = 1/ln(M)`. ~96% of nodes stay at layer 0.
- **Search**: start at the top entry point, greedy-traverse to a local minimum, drop a layer, repeat; widen the beam to `efSearch` at layer 0.

---

## 4. Indexing strategies — flat, IVF, product quantization

> **The core mechanism:** choose your speed/memory/recall trade-off. **Flat** = brute force (100% recall, O(n)). **IVF** = k-means partitions, probe only `nprobe` of them. **PQ** = compress vectors via subvector codebooks for massive memory savings.

### Worked example — 16 points, k=3, ground truth = [3, 0, 1]

> From `vector_databases.py` Section D.

**IVF (nlist=4 partitions via k-means):** cell sizes = `[4,4,4,4]` (balanced).

| nprobe | top-3 | recall | dist comps |
|---|---|---|---|
| 1 | [3, 0, 1] | 1.00 | 4 |
| 2 | [3, 0, 1] | 1.00 | 8 |
| = nlist (4) | [3, 0, 1] | 1.00 | 16 (collapses to brute force) |

**PQ (m=3 subvectors, ksub=4 centroids each):**

| metric | value |
|---|---|
| original size | 16 · 6 dims · 4 bytes = 384 bytes |
| PQ size | 16 · 3 bytes = 48 bytes |
| **compression ratio** | **8.0x** |
| mean reconstruction error (L2) | 0.380 |
| PQ top-3 | [2, 3, 1] |
| recall@3 | 0.67 |

PQ trades recall for massive memory savings (32–256x at scale). **Pair with IVF (IVF-PQ)** for >10M vectors where memory is the bottleneck.

### PQ internals

1. Split each d-dim vector into `m` subvectors of dim `d/m`.
2. Run k-means on each sub-dimension → `m` codebooks of `ksub` (typically 256) centroids.
3. Each subvector → the index of its nearest centroid (1 byte).
4. Distance (ADC): pre-compute query→all-centroids lookups once; per database vector, sum `m` table lookups.

---

## 5. The Qdrant collection model

> **The core mechanism:** a Qdrant **collection** holds **points**. Each point = `(id, vector, payload)`. `search(query_vector, k, filter)` returns the `k` nearest **matching** points. Payload filtering is first-class — Qdrant's *filterable HNSW* adds edges between same-metadata nodes so recall survives selective filters.

### Worked example — collection 'demo', search with and without filter

> From `vector_databases.py` Section E. 6 points, 4 dims, payload `{cluster: 'A'|'B'}`.

**`search(query=point1, k=3)` — no filter:**

| id | cosine | cluster |
|---|---|---|
| 1 | 1.000 | A |
| 3 | 0.968 | A |
| 2 | 0.869 | A |

**`search(query, k=3, filter={cluster:'B'})` — payload filter (post-filter):**

| id | cosine | cluster |
|---|---|---|
| 6 | 0.146 | B |
| 5 | −0.042 | B |
| 4 | −0.122 | B |

Filtering discards cluster-A results entirely. With a **selective** filter (<1% match), post-filter can return fewer than `k` — use pre-filter or Qdrant's filterable HNSW.

### Memory estimation — the interview math (1M vectors, 1024 dims)

| storage | bytes | size |
|---|---|---|
| raw float32 | 1M · 1024 · 4 | **4.10 GB** |
| HNSW edges (M=16) | 1M · 16 · 4 | 0.06 GB |
| scalar quantization (uint8) | 1M · 1024 · 1 | **1.02 GB** (4x) |
| product quantization (m=64) | 1M · 64 | **64 MB** (64x) |

---

### Complexity

> From `vector_databases.py` (Sections A–E).

| Operation | Time | Space |
|---|---|---|
| TF-IDF build (n docs, v vocab) | O(n·v) | O(n·v) |
| cosine / dot / euclidean (d dims) | O(d) | O(1) |
| Brute force kNN | O(n·d) | O(1) |
| LSH build | O(n·planes·d) | O(n) |
| LSH search | O(candidates·d) | O(n) |
| HNSW build | O(n·log n·d) | O(n·M) |
| HNSW search | O(log n·d) | O(ef) |
| IVF build (k-means) | O(n·nlist·iters·d) | O(n) |
| IVF search (nprobe) | O(nprobe·(n/nlist)·d) | O(1) |
| PQ train | O(n·m·ksub·iters·(d/m)) | O(m·ksub) |
| PQ distance (ADC) | O(m) per vector | O(m·ksub) |

### Killer Gotchas

1. **Never mix embedding models** in one index — vectors from different models live in different latent spaces; cosine is meaningless. Upgrading requires re-embedding the **entire** corpus.
2. **For L2-normalized vectors, cosine == dot product.** Pre-normalize once, then use the faster dot-product index — identical results.
3. **Post-filter can return < k** when the filter is selective (<1% match). Pre-filter or use Qdrant's filterable HNSW.
4. **Curse of dimensionality:** above ~2048 dims, distances converge and ANN quality degrades. Use PCA or lower-dim embedding models.
5. **HNSW memory scales with both n and M.** 10M vectors → 60+ GB RAM. Use scalar/PQ quantization to cut this 4–32x.
6. **RRF (hybrid search):** `score(d) = Σ_r 1/(k + rank_r(d))`, k=60. No training, robust to scale differences, handles missing docs.

### Problem / Decision Table

| Scenario | Best index | Why |
|---|---|---|
| < 100K vectors, dev/test | Flat | 100% recall, zero build |
| 100K–10M, real-time updates | HNSW (M=16–32) | best recall-speed, incremental inserts |
| 10M+, batch-indexed, memory-tight | IVF-PQ | 50–100x memory savings |
| already on Postgres, < 1M | pgvector (HNSW) | zero new infra, ACID joins |
| multi-lingual RAG | dense + BM25 + RRF | hybrid catches both semantic and exact-match |

---

## Cross-References

- **qdrant/** — 21 hands-on Qdrant tutorials (text, image, audio, RAG, multimodal, quantization).
- **`vector_databases.html`** — the interactive companion: embedding visualizer, similarity calculator, ANN recall comparison.
- **`index.html`** — dashboard for the whole `vector-db/` suite.
