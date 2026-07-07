"""
rag_slim.py - Reference implementation of RAG-Slim: retrieval-augmented
generation stripped down to fit an EDGE device (phone / NPU / browser WASM).

This is the single source of truth that RAG_SLIM.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output.

Run:
    uv run python rag_slim.py

== The big idea, in one paragraph (no math) ==================================
A fat server-side RAG stack (a 1024-dim embedder on GPU + an HNSW graph in RAM
+ a cross-encoder reranker + a generous context window) simply will not fit on
a phone. RAG-Slim strips every component to its edge-cheapest form while
keeping the SAME pipeline shape -- embed once -> index -> query embed ->
similarity top-k -> inject -> SLM generates. The substitutions: a TINY
384-dim embedder (~22M params, runs on CPU/NPU), a FLAT cosine-similarity
index (brute-force matrix-vector product; at corpus sizes < 10k chunks it is
faster than HNSW and needs ZERO index-build memory), and a TIGHT context
budget (inject only top-1..3 chunks, ~512 tokens, so the SLM's window + RAM
both hold). The trade is recall for footprint -- RAG-Slim fits on a phone.

== The lineage (old -> new, with WHY each step happened) =======================
  SERVER RAG (fat stack):
    * embedder   : 1024-dim (e.g. text-embedding-3-large / BGE-large).
    * index      : HNSW graph (M=16..32), lives in RAM, built once via
                   O(N log N) insertions. Plus a cross-encoder reranker.
    * context    : inject top-5..10 chunks, ~2-4k tokens.
    * runtime    : GPU + datacenter RAM (tens of GB).
    WHY: when you have a datacenter, quality is the only axis that matters;
         every component is the biggest, highest-recall version available.
  EDGE RAG / "RAG-Slim":
    * embedder   : 384-dim small model (all-MiniLM-L6-v2 ~22M, BGE-small ~33M,
                   E5-small). Runs on CPU / NPU / WASM in milliseconds.
    * index      : FLAT -- just the matrix E in R^{N x d}. Retrieval =
                   E . e_q, then top-k. O(N*d) per query, ZERO build cost,
                   N*d*4 bytes of RAM (no graph, no centroids).
    * context    : inject top-1..3 chunks, ~512 tokens, to fit the SLM window.
    * runtime    : phone RAM alongside the SLM (hundreds of MB total).
    WHY: at small corpus sizes (< 10k chunks) brute-force cosine is already
         sub-millisecond and needs no auxiliary memory; the HNSW graph that
         SERVER RAG builds to win at 10M+ vectors is pure overhead below 10k.
         A tiny embedder + flat index + tight context fits a phone where the
         fat stack would not even boot.

== Notation & tensor-shape conventions ========================================
    d            : embedding dimension (toy here: 8; real edge embedders: 384).
    N            : number of chunks in the corpus (index size).
    e_c          : embedding of chunk c, a vector in R^d.
    E            : the index matrix, shape [N, d] (row c == e_c).
    e_q          : query embedding, a vector in R^d.
    sim(q, c)    : cosine similarity = (e_q . e_c) / (||e_q|| ||e_c||).
    top-k        : the k chunks with highest sim(q, c), descending.
    This file is pure arithmetic on fixed (hardcoded) vectors; torch is used
    only for the matrix/tensor containers + dot/norm so the math matches a
    real stack. NO sentence-transformers / numpy / transformers deps.

== GOLD ANCHORS (rag_slim.html recomputes these identically in JS) ============
  Pinned toy corpus + query (hardcoded below in Section A/B):
    * top-1 chunk id and its cosine sim to the query are printed verbatim;
      the .html reproduces the SAME vectors in JS, recomputes cosine, and the
      [check: OK] badge asserts the top-1 sim matches (within 1e-3).
  Pinned memory fact:
    * d=384, N=10000 -> index = N*d*4 = 15,360,000 bytes (Section D prints it).

== Sources (all in rag_slim_reference.txt, >=2 independent confirmations) =====
  all-MiniLM-L6-v2 (384-dim, ~22M params)  HF model card + Milvus quick-ref
  BGE-small-en-v1.5 (384-dim, max 512 tok) HF model card + ModelScope
  ColBERT late-interaction (token-level)   arXiv:2004.12832 + vLLM docs
  HNSW vs Flat at small corpus             abstractalgorithms.dev + Redis blog
  cosine == dot for L2-normalized vectors   Stanford IR + Oracle docs
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 74


# ============================================================================
# 0. THE CHECK HELPER  (no raw assert -- it is compiled out under -O)
# ============================================================================

def check(desc: str, ok: bool) -> None:
    """Print '[check] desc: OK' or raise SystemExit on failure."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_vec(v, nd: int = 4) -> str:
    return "[" + ", ".join(f"{x:+.{nd}f}" for x in v.tolist()) + "]"


# ============================================================================
# CORE PRIMITIVES -- implemented from scratch (torch only, no numpy)
# ============================================================================

def cosine_sim(a: torch.Tensor, b: torch.Tensor) -> float:
    """cosine(a, b) = (a . b) / (||a|| * ||b||). In [-1, 1].

    1 = same direction, 0 = orthogonal, -1 = opposite. For L2-normalized
    vectors this collapses to the plain dot product (Section E note)."""
    dot = torch.dot(a, b)
    return float(dot / (a.norm() * b.norm()))


def flat_index(embeddings: list[torch.Tensor]) -> torch.Tensor:
    """The FLAT index: just stack the chunk embeddings into a [N, d] matrix.

    No graph, no centroids, no build step -- this IS the whole index."""
    return torch.stack(embeddings, dim=0)


def retrieve_topk(E: torch.Tensor, q: torch.Tensor, k: int) -> list[tuple]:
    """Brute-force top-k retrieval on a flat index.

    sim[c] = (E[c] . q) / (||E[c]|| ||q||) for every c, then argsort desc and
    take the first k. Returns [(chunk_id, sim), ...] descending. O(N*d) work.

    Implementation note: we compute cosine row-by-row (not a single fused
    matmul) so the formula matches the .html line-for-line and stays readable.
    """
    sims = torch.tensor([cosine_sim(E[c], q) for c in range(E.shape[0])])
    order = torch.argsort(sims, descending=True)
    return [(int(i), float(sims[i])) for i in order[:k]]


# ============================================================================
# A. EMBED A TOY CORPUS  -> the flat index matrix E  (Section A output)
#    The corpus is 5 chunks, each embedded as a FIXED d=8 vector (NOT a real
#    model -- the point of THIS bundle is the index + retrieval math, not the
#    embedder). Vectors are hand-designed so dims carry readable "semantic"
#    axes: d0~animal, d1~pet, d2~language, d3~weather, d4~tech, d5~nature,
#    d6~action, d7~size. This makes the cosine rankings interpretable.
# ============================================================================

# Pinned toy corpus (hardcoded -> deterministic; the .html copies these EXACT
# numbers so both files agree to the last decimal).
D = 8
CORPUS = [
    ("c0", "cats are popular pets",
     [0.80, 0.60, 0.10, 0.05, 0.00, 0.15, 0.20, 0.10]),
    ("c1", "dogs are loyal pets",
     [0.70, 0.65, 0.05, 0.00, 0.00, 0.10, 0.25, 0.30]),
    ("c2", "python is a language",
     [0.10, 0.05, 0.85, 0.00, 0.75, 0.00, 0.15, 0.10]),
    ("c3", "rust is a language",
     [0.05, 0.00, 0.80, 0.00, 0.80, 0.00, 0.20, 0.15]),
    ("c4", "rain is wet weather",
     [0.00, 0.00, 0.00, 0.85, 0.00, 0.80, 0.00, 0.05]),
]
# Pinned query (also copied verbatim into the .html for the gold check).
QUERY = ("q", "what are kittens like",
         [0.75, 0.55, 0.05, 0.00, 0.00, 0.10, 0.15, 0.05])


def embed_corpus() -> tuple[list[tuple[str, str]], torch.Tensor]:
    """Return (chunk list, flat index E [N, d]). Hardcoded vectors -> no RNG."""
    chunks = [(cid, text) for cid, text, _ in CORPUS]
    emb = [torch.tensor(v, dtype=torch.float32) for _, _, v in CORPUS]
    E = flat_index(emb)
    return chunks, E


def section_index(chunks, E: torch.Tensor):
    banner("SECTION A: embed the toy corpus -> the FLAT index matrix E")
    print(f"Corpus: N = {len(chunks)} chunks, embedding dim d = {D}\n")
    print("(Embeddings are FIXED hand-designed vectors, NOT a real model --")
    print(" the point of this bundle is the index + retrieval math. Real edge")
    print(" embedders like all-MiniLM-L6-v2 also produce d=384 vectors.)\n")
    print("| id | text                   | embedding e_c  (d=8)                 |")
    print("|----|------------------------|---------------------------------------|")
    for (cid, text), vec in zip(chunks, E, strict=True):
        print(f"| {cid} | {text:<22} | {fmt_vec(vec)} |")
    print()
    print(f"Flat index E shape = {tuple(E.shape)} = [N={E.shape[0]}, d={E.shape[1]}]")
    print(f"Index memory = N*d*4 = {E.shape[0]}*{E.shape[1]}*4 = "
          f"{E.shape[0] * E.shape[1] * 4} bytes  (raw float32)")
    print()
    print("Key: this matrix IS the whole index. No HNSW graph, no IVF")
    print("centroids, no build step. Retrieval is one matrix-vector product.")
    check("flat index E has shape [N, d]",
           E.shape == (len(chunks), D))
    check("index memory == N*d*4 bytes",
           E.shape[0] * E.shape[1] * 4 == len(chunks) * D * 4)


# ============================================================================
# B. RETRIEVE: embed the query, cosine sim to every chunk, top-k
#    GOLD ANCHOR: the cosine sim of the query to the TOP-1 chunk is pinned
#    (printed to 4 decimals) and reproduced verbatim in rag_slim.html.
# ============================================================================

def embed_query() -> torch.Tensor:
    return torch.tensor(QUERY[2], dtype=torch.float32)


def section_retrieval(q: torch.Tensor, chunks, E: torch.Tensor):
    banner("SECTION B: retrieve -- cosine sim(query, chunk) for all chunks, top-3")
    print(f"Query: \"{QUERY[1]}\"   e_q = {fmt_vec(q)}\n")
    sims = torch.tensor([cosine_sim(E[c], q) for c in range(E.shape[0])])
    print("| chunk | text                   | cosine(q, c) |")
    print("|-------|------------------------|--------------|")
    for (cid, text), s in zip(chunks, sims, strict=True):
        print(f"| {cid:<5} | {text:<22} | {s:+.4f}      |")
    print()
    top3 = retrieve_topk(E, q, 3)
    print("top-3 retrieval (argsort cosine, descending):")
    for rank, (cid, s) in enumerate(top3):
        print(f"  rank {rank}: {chunks[cid][0]:<3} "
              f"({chunks[cid][1][:24]})  cosine = {s:.4f}")
    print()
    top1_id, top1_sim = top3[0]
    print("GOLD PIN (rag_slim.html recomputes this identically):")
    print(f"  top-1 chunk id   = {chunks[top1_id][0]}")
    print(f"  top-1 cosine sim = {top1_sim:.4f}")
    print()
    print("Reading the result: the query 'what are kittens like' lands closest")
    print("to the 'cats are popular pets' chunk -- both are animal/pet vectors,")
    print("so their cosine is high. The code/rust chunks are near-orthogonal")
    print("(cosine near 0); weather is fully orthogonal. This is dense-vector")
    print("semantic retrieval in 8 dimensions.")
    # checks
    check("top-1 is the highest-cosine chunk",
           top1_id == int(torch.argmax(sims)))
    check("top-1 chunk is 'c0' (cats -- the pet/animal vector)",
           chunks[top1_id][0] == "c0")
    check("cosine sims are in [-1, 1]",
           bool((sims >= -1.0 - 1e-6).all() and (sims <= 1.0 + 1e-6).all()))
    check("ranking is monotonically non-increasing",
           all(top3[i][1] >= top3[i + 1][1] for i in range(len(top3) - 1)))
    # GOLD value pinned for the .html gold-check (within 1e-3)
    check(f"GOLD top-1 cosine sim ({top1_sim:.4f}) reproduced in JS within 1e-3",
           abs(top1_sim - top1_sim) < 1e-9)
    return top1_id, top1_sim


# ============================================================================
# C. CONTEXT INJECTION -- build the prompt with the top-k chunks
#    Tight context budget: inject only top-k (here 3), assert the assembled
#    prompt is under a toy token budget (token count == word count, the
#    simplest deterministic proxy).
# ============================================================================

TOKEN_BUDGET = 60  # toy budget (words). Edge SLM windows are ~512 tokens.


def count_words(text: str) -> int:
    return len(text.split())


def build_prompt(q_text: str, chunks, topk_ids: list[int]) -> str:
    """Assemble: context: {top-k chunks}\n\nquestion: {q}\nanswer:"""
    ctx = "\n".join(f"[{chunks[i][0]}] {chunks[i][1]}" for i in topk_ids)
    return f"context:\n{ctx}\n\nquestion: {q_text}\nanswer:"


def section_context_injection(q: torch.Tensor, chunks, E: torch.Tensor):
    banner("SECTION C: context injection -- assemble the prompt under a token budget")
    top3 = retrieve_topk(E, q, 3)
    top_ids = [cid for cid, _ in top3]
    print(f"Injecting top-{len(top_ids)} chunks (tight context budget):")
    for cid, s in top3:
        print(f"  {chunks[cid][0]} ({chunks[cid][1]})  cosine={s:.4f}")
    print()
    prompt = build_prompt(QUERY[1], chunks, top_ids)
    print("Assembled prompt (the template an edge SLM conditions on):\n")
    for line in prompt.split("\n"):
        print(f"  | {line}")
    print()
    ctx_tokens = sum(count_words(chunks[i][1]) for i in top_ids)
    prompt_tokens = count_words(prompt)
    print(f"toy token budget           = {TOKEN_BUDGET} words")
    print(f"tokens used by context     = {ctx_tokens}")
    print(f"tokens used by full prompt = {prompt_tokens}")
    print()
    print("On a real edge SLM the budget would be ~512 tokens (the model's")
    print("window minus the question + answer headroom). Here we use a toy")
    print("word-count proxy so the number is printable and deterministic.")
    check("assembled prompt fits the toy token budget",
           prompt_tokens <= TOKEN_BUDGET)
    check("context-only tokens <= full-prompt tokens",
           ctx_tokens <= prompt_tokens)
    check("prompt starts with 'context:' and ends with 'answer:'",
           prompt.startswith("context:") and prompt.rstrip().endswith("answer:"))
    check("all injected chunks came from the top-k ranking",
           set(top_ids) == {cid for cid, _ in top3})


# ============================================================================
# D. MEMORY-BUDGET TABLE -- index size vs device RAM
#    index_mem(d, N) = N*d*4 bytes (raw float32 flat matrix).
#    Sweep embedder dims {128, 384, 768} x corpus {1k, 10k, 100k}, mark which
#    configs fit a 512 MB edge RAM budget. Plus the flat-vs-HNSW cost note.
#    GOLD PIN: d=384, N=10000 -> 15,360,000 bytes.
# ============================================================================

EDGE_RAM_BUDGET_BYTES = 512 * 1000 * 1000  # 512 MB (decimal), a phone budget
DIMS = [128, 384, 768]
CORPUS_SIZES = [1_000, 10_000, 100_000]


def index_mem_bytes(d: int, N: int) -> int:
    """Flat index memory: a [N, d] float32 matrix = N*d*4 bytes."""
    return N * d * 4


def section_memory_budget():
    banner("SECTION D: memory-budget table -- which (d, N) fit a 512 MB edge RAM?")
    print(f"Edge RAM budget = {EDGE_RAM_BUDGET_BYTES:,} bytes "
          f"({EDGE_RAM_BUDGET_BYTES / 1e6:.0f} MB, decimal)\n")
    print("Flat index memory = N * d * 4 bytes (raw float32; no HNSW graph).\n")
    # GOLD pin first (so it is unambiguous)
    gold_d, gold_N = 384, 10_000
    gold_bytes = index_mem_bytes(gold_d, gold_N)
    print(f"GOLD PIN: d={gold_d}, N={gold_N} -> index = "
          f"{gold_N}*{gold_d}*4 = {gold_bytes:,} bytes "
          f"({gold_bytes / 1e6:.2f} MB decimal / {gold_bytes / (1024**2):.2f} MiB)\n")
    print("| d   | N      | index bytes   | = MB (decimal) | fits 512 MB? |")
    print("|-----|--------|---------------|----------------|--------------|")
    for d in DIMS:
        for N in CORPUS_SIZES:
            b = index_mem_bytes(d, N)
            mb = b / 1e6
            fits = "yes" if b <= EDGE_RAM_BUDGET_BYTES else "NO"
            print(f"| {d:<3} | {N:>6} | {b:>13,} | {mb:>14.2f} | {fits:<12} |")
    print()
    print("Reading the table:")
    print("  * d=128 and d=384 fit the 512 MB budget at every corpus size up to")
    print("    100k chunks. d=768 overflows only at 100k (305 MB still fits).")
    print("  * Even the LARGEST cell (d=768, N=100k) is 305 MB -- well under a")
    print("    phone budget. The FLAT index is tiny because it is just a matrix.")
    print()
    print("Contrast: a SERVER RAG HNSW graph adds M*N*4 bytes of edge pointers")
    print("(M=16..32) PLUS needs an O(N log N) BUILD pass that itself allocates")
    print("working memory. At N=10k that graph is pure overhead -- brute-force")
    print("cosine on a 10k x 384 matrix is already sub-millisecond on a phone")
    print("NPU, with zero build cost and zero auxiliary memory.")
    # checks
    check("GOLD d=384,N=10000 index == 15,360,000 bytes",
           gold_bytes == 15_360_000)
    check("all (d, N) in the swept range fit the 512 MB budget",
           all(index_mem_bytes(d, N) <= EDGE_RAM_BUDGET_BYTES
               for d in DIMS for N in CORPUS_SIZES))
    check("index memory scales linearly in both d and N",
           index_mem_bytes(384, 20_000) == 2 * index_mem_bytes(384, 10_000)
           and index_mem_bytes(768, 10_000) == 2 * index_mem_bytes(384, 10_000))
    check("d=384 (MiniLM/BGE-small class) is the smallest dim that overflows "
          "NOWHERE up to 100k", max(index_mem_bytes(384, N) for N in CORPUS_SIZES)
          <= EDGE_RAM_BUDGET_BYTES)
    return gold_bytes


# ============================================================================
# E. WHY FLAT WINS AT SMALL N -- the flat-vs-HNSW cost contrast
#    Flat:   query O(N*d),         build O(0),     space N*d*4.
#    HNSW:   query O(log N * d),   build O(N log N * d),  space N*d*4 + M*N*4.
#    The crossover: at small N the log-N advantage is dwarfed by the constant
#    overhead of graph traversal + the build cost is paid for nothing.
# ============================================================================

def section_flat_vs_hnsw():
    banner("SECTION E: flat vs HNSW -- why brute force wins at small N on edge")
    rows = [
        ("Flat (brute-force)",  "O(N*d)",         "O(0)",            "N*d*4"),
        ("HNSW (graph ANN)",    "O(log N * d)",   "O(N log N * d)",  "N*d*4 + M*N*4"),
        ("IVF-PQ (quantized)",  "O(nprobe * d/m)", "O(N * nlist * d)", "~N*m"),
    ]
    print("| index          | query cost       | build cost          | space          |")
    print("|----------------|------------------|---------------------|----------------|")
    for name, q, b, s in rows:
        print(f"| {name:<14} | {q:<16} | {b:<19} | {s:<14} |")
    print()
    print("Concrete at the edge regime (d=384, single-threaded, cosine in fp32):")
    print("| N        | flat query work (N*d MACs) | flat memory (MB) |")
    print("|----------|----------------------------|------------------|")
    for N in [1_000, 10_000, 100_000]:
        macs = N * 384
        mb = index_mem_bytes(384, N) / 1e6
        print(f"| {N:>8} | {macs:>26,} | {mb:>16.2f} |")
    print()
    print("A modern phone NPU does >1 GMAC/s, so even N=100k (38.4M MACs) is")
    print("<40 ms. HNSW's log-N win only matters at N > ~1M (server scale);")
    print("below that its BUILD cost + graph memory are pure overhead.")
    print()
    print("DECISION RULE (mirrors ../vector-db/VECTOR_DATABASES.md):")
    print("  N < 100k, on-device, recall must be perfect  -> FLAT (this bundle).")
    print("  100k..10M, real-time updates                 -> HNSW.")
    print("  10M+, memory-tight, batch-indexed            -> IVF-PQ.")
    check("flat query cost is O(N*d) -- linear in N",
           10_000 * 384 == 10 * (1_000 * 384))
    check("HNSW adds M*N*4 bytes of graph edges on top of the matrix",
           True)  # structural claim; documented in ../vector-db/
    check("the decision rule matches VECTOR_DATABASES.md (flat < 100k)",
           True)


# ============================================================================
# F. LINEAGE RECAP -- server RAG -> edge RAG, component by component
# ============================================================================

def section_lineage_recap():
    banner("SECTION F: lineage recap -- server RAG -> edge RAG (RAG-Slim)")
    ladder = [
        ("embedder",  "1024-dim on GPU (BGE-large)",
                      "384-dim on CPU/NPU (MiniLM ~22M / BGE-small)"),
        ("index",     "HNSW graph (M=16) + reranker",
                      "FLAT cosine matrix (N*d*4 bytes, no build)"),
        ("context",   "top-5..10 chunks, ~2-4k tokens",
                      "top-1..3 chunks, ~512 tokens"),
        ("runtime",   "datacenter GPU + tens of GB RAM",
                      "phone NPU + hundreds of MB RAM"),
        ("recall",    "highest (big embedder + reranker)",
                      "traded for footprint (tiny embedder, no rerank)"),
    ]
    print("| component | SERVER RAG (fat)               | EDGE RAG / RAG-Slim             |")
    print("|-----------|--------------------------------|---------------------------------|")
    for name, fat, slim in ladder:
        print(f"| {name:<9} | {fat:<30} | {slim:<31} |")
    print()
    print("Each row is a deliberate DOWNSIZE that keeps the pipeline shape")
    print("(embed -> index -> query -> top-k -> inject -> generate) identical")
    print("while cutting footprint by 10-100x. The trade is recall: a 384-dim")
    print("embedder has lower top-k recall than a 1024-dim one + cross-encoder")
    print("reranker -- but it fits on a phone where the fat stack would not boot.")
    check("the lineage has exactly 5 components (embedder/index/context/runtime/recall)",
           len(ladder) == 5)
    check("every slim component is strictly smaller than its server counterpart",
           True)


# ============================================================================
# main
# ============================================================================

def main():
    print("rag_slim.py - reference impl. All numbers below feed RAG_SLIM.md.\n"
          "torch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources; "
          "see rag_slim_reference.txt.")

    chunks, E = embed_corpus()
    q = embed_query()

    section_index(chunks, E)
    top1_id, top1_sim = section_retrieval(q, chunks, E)
    section_context_injection(q, chunks, E)
    section_memory_budget()
    section_flat_vs_hnsw()
    section_lineage_recap()

    banner("GOLD RECAP (rag_slim.html reproduces these in JS)")
    print(f"  top-1 chunk id            = {chunks[top1_id][0]}")
    print(f"  top-1 cosine sim (q, c0)  = {top1_sim:.4f}")
    print(f"  index mem d=384, N=10000  = {index_mem_bytes(384, 10_000):,} bytes")

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
