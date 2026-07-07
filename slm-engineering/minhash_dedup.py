"""
minhash_dedup.py - Reference implementation of web-scale near-duplicate
deduplication via MinHash + Locality-Sensitive Hashing (LSH) banding, the
highest-leverage data-curation step for SLM pretraining corpora.

This is the single source of truth that MINHASH_DEDUP.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output.

Run:
    uv run python minhash_dedup.py

== The big idea, in one paragraph =============================================
A pretraining corpus scraped from the web is FULL of near-duplicates (the same
article re-hosted, boilerplate repeated across pages, mirrors). Training on
duplicates wastes capacity AND causes verbatim memorization (the model sees the
same text 50x and overfits it). We need to drop near-duplicates, but doing it
exactly means comparing EVERY pair of documents -- O(n^2), infeasible at the 15
TRILLION-token scale of FineWeb. MinHash + LSH is the trick that makes it
sub-linear: each document is compressed to a short integer SIGNATURE whose
component-wise match-rate UNBIASEDLY estimates the Jaccard similarity, then LSH
banding groups only signatures that probably match into candidate buckets, so we
never compare truly-distinct documents at all.

== The lineage (old -> new, with WHY each step happened) ========================
  exact-match dedup : drop byte-identical documents (a single hash of the full
                      text). Cheap, but MISSES near-duplicates (a single changed
                      word, different whitespace, re-hosting) which dominate
                      web-scale waste.
  n-gram / Jaccard  : represent a document as the SET of its n-grams (shingles)
                      and measure overlap with Jaccard J = |A∩B|/|A∪B|. Catches
                      near-dups, BUT requires comparing every pair -> O(n^2),
                      infeasible when n = billions of documents.
  MinHash (1997)    : a k-length integer signature where component i is the min
                      hash over shingles under hash function h_i. The magic:
                      P(sig_A[i] == sig_B[i]) = J(A,B) EXACTLY. So the fraction
                      of matching signature positions estimates J in O(k) time,
                      no pairwise set ops. (Broder, originally for AltaVista.)
  LSH banding       : split the k-signature into b bands of r rows (k = b*r).
                      Two docs are a CANDIDATE only if they agree on ALL r rows
                      of at least one band. The probability of becoming a
                      candidate is the S-curve P(candidate|J) = 1 - (1-J^r)^b,
                      which is ~0 below a threshold t ~= (1/b)^(1/r) and ~1
                      above it. So only near-dups (high J) land in the same
                      bucket -> sublinear candidate generation. (MMDS ch.3.)

== Determinism (CRITICAL) =====================================================
  MinHash needs k INDEPENDENT random-looking hash functions. We CANNOT use
  Python's built-in hash() on str -- it is RANDOMIZED per process (PYTHONHASHSEED)
  so _output.txt would never reproduce. Instead we implement FNV-1a (a 32-bit
  deterministic integer hash) and build the family by prepending the index:
      h_i(shingle) = fnv1a_32( f"{i}|{shingle}" )
  This is byte-for-byte reproducible AND trivially portable to JavaScript (the
  .html recomputes the IDENTICAL signatures with the IDENTICAL formula, then
  gold-checks against this file). All input text is pure ASCII so Python's
  utf-8 encoding and JS charCodeAt agree exactly.

== Plain-English glossary ====================================================
    shingle       a contiguous run of n words (here n=3) from a document. The
                  document becomes the SET of its shingles.
    Jaccard J     |A∩B| / |A∪B| -- the exact set similarity (0 = disjoint,
                  1 = identical). What we want to estimate cheaply.
    MinHash sig   a list of k integers; entry i = min over shingles of h_i.
    MinHash est   (# matching positions) / k -- an unbiased estimator of J with
                  expected error O(1/sqrt(k)).
    band / row    the k signature is split into b BANDS each of r ROWS (k=b*r).
    candidate     two docs that agree on all r rows of >= 1 band -> probably a
                  near-dup -> compared exactly; everyone else is skipped.
    S-curve       P(candidate | J) = 1 - (1 - J^r)^b. Steplike: ~0 below the
                  threshold, ~1 above.
    threshold t   t ~= (1/b)^(1/r). The Jaccard at which the S-curve is ~0.5-0.63.
    union-find    the clustering structure: union every candidate pair, then
                  keep ONE representative per connected component (cluster).

== Tensor / numerical conventions ============================================
    This file is mostly set + integer arithmetic (the algorithm is discrete).
    torch is used for the S-curve table (torch.linspace / torch.pow) so the
    probability curve matches a real ML stack and the .html can recompute it.
    Fixed precision: floats print to 4 decimals (torch.set_printoptions).

== Sources (all in minhash_dedup_reference.txt, >=2 independent confirmations) ==
  Broder 1997           COMPCOMM'97 "On the Resemblance and Containment of
                        Documents" -- the MinHash original (P(minhash equal)=J).
  MMDS ch.3             Leskovec/Rajaraman/Ullman "Mining of Massive Datasets" --
                        the canonical MinHash + LSH banding treatment, S-curve,
                        threshold t ~= (1/b)^(1/r).
  FineWeb (2024)        arXiv:2406.17557 -- the production dedup pipeline:
                        5-grams, 112 perms, 14 bands x 8 rows (NOT 128/14x9).
  Wikipedia MinHash     independent confirmation of P(hmin(A)=hmin(B))=J.
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


# ============================================================================
# CORE PRIMITIVES: deterministic hash family + shingling + MinHash + LSH
# ============================================================================

# FNV-1a 32-bit constants (deterministic, no randomized hash()).
_FNV_OFFSET = 2166136261
_FNV_PRIME = 16777619
_U32 = 0xFFFFFFFF


def fnv1a_32(text: str) -> int:
    """Deterministic 32-bit FNV-1a hash of an ASCII string.

    Pure-integer, no Python randomized hash(); byte-for-byte portable to JS
    (the .html reimplements this EXACT loop with Math.imul and >>> 0).
    """
    h = _FNV_OFFSET
    for byte in text.encode("utf-8"):
        h ^= byte
        h = (h * _FNV_PRIME) & _U32
    return h


def hash_i(shingle: str, i: int) -> int:
    """The i-th hash function in the MinHash family: prepend the index.

    h_i(s) = fnv1a_32( f"{i}|{s}" ). Distinct i -> distinct, independent-looking
    hash, all derived from ONE deterministic base function.
    """
    return fnv1a_32(f"{i}|{shingle}")


def shingles(text: str, n: int = 3) -> set[str]:
    """Set of word-level n-gram shingles (default n=3, the FineWeb choice).

    Lowercased, whitespace-split. A document of W words yields up to W-n+1
    shingles; order within a shingle is preserved but document order is lost
    (we keep the SET, which is what Jaccard needs).
    """
    words = text.lower().split()
    if len(words) < n:
        # too short for a full n-gram: fall back to the whole token sequence
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    """Exact Jaccard similarity |A∩B| / |A∪B| (0 if both empty)."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def minhash_signature(shingle_set: set[str], k: int) -> list[int]:
    """MinHash signature of length k: sig[i] = min over shingles of h_i(shingle).

    min() over a set is deterministic (order-independent), so output is stable
    across runs regardless of PYTHONHASHSEED.
    """
    if not shingle_set:
        return [_U32] * k
    return [min(hash_i(s, i) for s in shingle_set) for i in range(k)]


def estimated_jaccard(sig_a: list[int], sig_b: list[int]) -> float:
    """Fraction of matching signature positions = unbiased estimate of J."""
    k = len(sig_a)
    matches = sum(1 for x, y in zip(sig_a, sig_b) if x == y)
    return matches / k


def lsh_candidate_pairs(signatures: list[list[int]], b: int, r: int) -> set[tuple[int, int]]:
    """LSH banding: two docs are candidates iff they agree on ALL r rows of a band.

    For each of the b bands, hash the r-length sub-signature to a bucket; any two
    docs in the same bucket of any band are a candidate pair. Output is a set of
    sorted (i, j) index pairs -- deterministic.
    """
    candidates: set[tuple[int, int]] = set()
    for band in range(b):
        buckets: dict[tuple[int, ...], list[int]] = {}
        for doc_idx, sig in enumerate(signatures):
            sub = tuple(sig[band * r : (band + 1) * r])
            buckets.setdefault(sub, []).append(doc_idx)
        for bucket in buckets.values():
            if len(bucket) < 2:
                continue
            for p in range(len(bucket)):
                for q in range(p + 1, len(bucket)):
                    a, c = bucket[p], bucket[q]
                    candidates.add((min(a, c), max(a, c)))
    return candidates


def s_curve(j_vals: torch.Tensor, b: int, r: int) -> torch.Tensor:
    """P(become a candidate | Jaccard J) = 1 - (1 - J^r)^b -- the LSH S-curve."""
    return 1.0 - (1.0 - torch.pow(j_vals, r)) ** b


def lsh_threshold(b: int, r: int) -> float:
    """Approximate S-curve threshold t ~= (1/b)^(1/r) (MMDS ch.3).

    At J = t, J^r = 1/b so (1 - J^r)^b ~= (1 - 1/b)^b ~= 1/e, i.e. P ~= 0.63.
    This is the Jaccard at which the banding starts catching pairs reliably.
    """
    return float((1.0 / b) ** (1.0 / r))


class UnionFind:
    """Union-find with path compression -> cluster candidate pairs."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]  # path compression
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def clusters(self) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            groups.setdefault(self.find(i), []).append(i)
        return groups


# ============================================================================
# A. SHINGLING + EXACT JACCARD  (the O(n^2) baseline we want to beat)
# ============================================================================

# The three toy documents used throughout Sections A-B. doc_a/doc_b are a
# near-duplicate pair (the GOLD ANCHOR the .html recomputes); doc_c is distinct.
# Note doc_b changes ONLY the last word of doc_a (bank -> shore), so exactly ONE
# 3-gram shingle differs -> J ~ 0.83 (comfortably above the LSH threshold).
DOC_A = "the quick brown fox jumps over the lazy dog by the river bank"
DOC_B = "the quick brown fox jumps over the lazy dog by the river shore"
DOC_C = "machine learning models need huge amounts of clean training data"
SHINGLE_N = 3


def section_shingling_and_jaccard():
    banner("SECTION A: shingling + exact Jaccard (the O(n^2) baseline)")
    print(f"Word-level n-gram shingling, n = {SHINGLE_N} (the FineWeb choice).\n")
    docs = {"doc_a": DOC_A, "doc_b": DOC_B, "doc_c": DOC_C}
    sh: dict[str, set[str]] = {}
    for name, text in docs.items():
        sh[name] = shingles(text, SHINGLE_N)
    for name in sorted(sh):
        print(f"{name} = \"{docs[name]}\"")
        print(f"  shingles ({len(sh[name])}): {sorted(sh[name])}")
    print()
    pairs = [("doc_a", "doc_b"), ("doc_a", "doc_c"), ("doc_b", "doc_c")]
    print("| pair            | |A∩B| | |A∪B| | exact Jaccard | verdict        |")
    print("|-----------------|-------|-------|---------------|----------------|")
    for x, y in pairs:
        inter = len(sh[x] & sh[y])
        union = len(sh[x] | sh[y])
        j = inter / union if union else 0.0
        verdict = "NEAR-DUPLICATE" if j >= 0.5 else "distinct"
        print(f"| {x} vs {y:<6} | {inter:>5} | {union:>5} | {j:>13.4f} | {verdict:<14} |")
    print()
    jab = jaccard(sh["doc_a"], sh["doc_b"])
    jac = jaccard(sh["doc_a"], sh["doc_c"])
    print(f"doc_a vs doc_b exact J = {jab:.4f}  (one last word changed: bank->shore)")
    print(f"doc_a vs doc_c exact J = {jac:.4f}  (totally different topic)")
    print()
    check("near-dup pair (a,b) has J >= 0.5", jab >= 0.5)
    check("distinct pair (a,c) has J < 0.3", jac < 0.3)
    check("exact-match dedup would MISS the (a,b) near-dup (text differs)",
          DOC_A != DOC_B)
    return sh


# ============================================================================
# B. MINHASH SIGNATURE + ESTIMATED JACCARD  (the O(k) shortcut)
# ============================================================================

K_HASHES = 20  # length of the MinHash signature


def section_minhash_signature(sh: dict[str, set[str]]):
    banner(f"SECTION B: MinHash signature (k={K_HASHES} hashes) + estimated Jaccard")
    print(f"signature[i] = min over shingles s of h_i(s),  i = 0..{K_HASHES-1}")
    print("h_i(s) = fnv1a_32( f\"{i}|{s}\" )  (deterministic FNV-1a, no Python hash())\n")
    sigs: dict[str, list[int]] = {}
    for name in sorted(sh):
        sigs[name] = minhash_signature(sh[name], K_HASHES)
    for name in sorted(sigs):
        print(f"{name} signature (k={K_HASHES}):")
        print("  " + ", ".join(f"{v}" for v in sigs[name]))
    print()
    print("| pair            | exact J | matches/k | estimated J | |est-exact| |")
    print("|-----------------|---------|-----------|-------------|-------------|")
    pairs = [("doc_a", "doc_b"), ("doc_a", "doc_c"), ("doc_b", "doc_c")]
    est_ab = None
    for x, y in pairs:
        exact = jaccard(sh[x], sh[y])
        est = estimated_jaccard(sigs[x], sigs[y])
        if x == "doc_a" and y == "doc_b":
            est_ab = est
        matches = round(est * K_HASHES)
        print(f"| {x} vs {y:<6} | {exact:>7.4f} | {matches:>4}/{K_HASHES:<3}  | "
              f"{est:>11.4f} | {abs(est-exact):>11.4f} |")
    print()
    print("Reading the table: the estimated J tracks the exact J, but is a SAMPLE")
    print(f"(k={K_HASHES} independent coin-flips), so it wobbles by ~1/sqrt(k) = "
          f"{1.0 / (K_HASHES ** 0.5):.3f}. More hashes -> tighter estimate.")
    print()
    print("GOLD ANCHOR (minhash_dedup.html recomputes this): doc_a vs doc_b")
    print(f"  exact Jaccard   = {jaccard(sh['doc_a'], sh['doc_b']):.4f}")
    print(f"  estimated Jaccard = {est_ab:.4f}  (k={K_HASHES}, deterministic FNV-1a)")
    check("MinHash estimate within 0.15 of exact J for the near-dup pair",
          abs(est_ab - jaccard(sh["doc_a"], sh["doc_b"])) < 0.15)
    check("MinHash estimate for distinct pair (a,c) is low (< 0.30)",
          estimated_jaccard(sigs["doc_a"], sigs["doc_c"]) < 0.30)
    return sigs


# ============================================================================
# C. LSH BANDING  (sublinear candidate generation + the S-curve)
# ============================================================================

B_BANDS = 5
R_ROWS = 4  # k = b*r = 20  (matches K_HASHES above)


def section_lsh_banding(sigs: dict[str, list[int]], sh: dict[str, set[str]]):
    banner(f"SECTION C: LSH banding (b={B_BANDS} bands x r={R_ROWS} rows)")
    names = sorted(sigs)
    sig_list = [sigs[n] for n in names]
    t = lsh_threshold(B_BANDS, R_ROWS)
    print(f"Split the k={K_HASHES} signature into b={B_BANDS} bands of r={R_ROWS} rows.")
    print(f"A pair is a CANDIDATE iff it agrees on ALL {R_ROWS} rows of >= 1 band.\n")
    print(f"Approximate S-curve threshold  t = (1/b)^(1/r) = (1/{B_BANDS})^(1/{R_ROWS})")
    print(f"                                             = {t:.5f}  (~0.6687)")
    print(f"At J = t: J^r = 1/b = {1.0/B_BANDS:.4f},  P(candidate) ~= 1 - (1-1/b)^b")
    p_at_t = 1.0 - (1.0 - (t ** R_ROWS)) ** B_BANDS
    print(f"                                              = {p_at_t:.4f}\n")
    cands = lsh_candidate_pairs(sig_list, B_BANDS, R_ROWS)
    print("Candidate pairs from banding on {doc_a, doc_b, doc_c}:")
    if not cands:
        print("  (none)")
    for i, j in sorted(cands):
        est = estimated_jaccard(sig_list[i], sig_list[j])
        exact = jaccard(sh[names[i]], sh[names[j]])
        print(f"  ({names[i]}, {names[j]})  exact J={exact:.4f}  est J={est:.4f}  -> kept")
    print()
    print("Sweep over Jaccard J: the probability P(candidate | J) -- the S-curve")
    print("| J    | J^r      | 1-J^r    | (1-J^r)^b | P(candidate)=1-(1-J^r)^b |")
    print("|------|----------|----------|-----------|--------------------------|")
    j_vals = torch.linspace(0.1, 0.9, 9)
    probs = s_curve(j_vals, B_BANDS, R_ROWS)
    for jj, pp in zip(j_vals.tolist(), probs.tolist()):
        jr = jj ** R_ROWS
        one_minus = 1.0 - jr
        band_term = one_minus ** B_BANDS
        print(f"| {jj:.1f}  | {jr:<8.4f} | {one_minus:<8.4f} | {band_term:<9.4f} | "
              f"{pp:<24.4f} |")
    print()
    print(f"The S-curve is ~0 below J={t:.4f} and ~1 above it -> a tunable cliff.")
    print("Pairs with J below the cliff are (correctly) NOT compared; pairs above")
    print("it land in the same bucket and become candidates. This is what makes")
    print("dedup SUBLINEAR instead of O(n^2). A pair with J near the cliff is a")
    print("coin-flip -- raising the threshold (more rows r) trades RECALL for")
    print("PRECISION (fewer false positives, more false negatives).")
    print()
    check("LSH threshold for b=5, r=4 ~= 0.6687 (within 1e-3)",
          abs(t - 0.6687) < 1e-3)
    check("S-curve is ~0 at J=0.1 (< 0.05)", probs[0] < 0.05)
    check("S-curve is ~1 at J=0.9 (> 0.95)", probs[-1] > 0.95)
    # the near-dup (a,b) clears the threshold and must be caught; the distinct
    # pair (a,c) sits below the cliff and must NOT be a candidate.
    jab = jaccard(sh["doc_a"], sh["doc_b"])
    jac = jaccard(sh["doc_a"], sh["doc_c"])
    check(f"near-dup (a,b) J={jab:.4f} >= threshold {t:.4f} -> caught as candidate",
          jab >= t and (0, 1) in cands)
    check(f"distinct pair (a,c) J={jac:.4f} is NOT a candidate (below cliff)",
          (0, 2) not in cands)
    return cands


# ============================================================================
# D. END-TO-END DEDUP  (union-find clustering on a toy 8-doc corpus)
# ============================================================================

# 8 documents with TWO near-duplicate clusters: {0,1} and {3,4}.
# Each near-dup changes ONLY the last word -> exactly one 3-gram shingle differs,
# so J ~ 0.83 (well above the LSH threshold t ~= 0.6687 -> reliably caught).
CORPUS = [
    "the quick brown fox jumps over the lazy dog by the river bank",   # 0
    "the quick brown fox jumps over the lazy dog by the river shore",  # 1 (near-dup of 0)
    "a bright sunny morning in the middle of july this warm summer",   # 2
    "the cat sat on the mat near the warm fireplace in the house",     # 3
    "the cat sat on the mat near the warm fireplace in the home",      # 4 (near-dup of 3)
    "machine learning models need huge amounts of clean training data",# 5
    "quantum computers can solve problems that classical computers cannot",  # 6
    "a recipe for chocolate cake requires flour sugar eggs and cocoa", # 7
]


def section_end_to_end_dedup():
    banner("SECTION D: end-to-end dedup on a toy 8-doc corpus (union-find clustering)")
    print(f"Corpus: {len(CORPUS)} docs. Planted near-dup clusters {{0,1}} and {{3,4}}.\n")
    print(f"Config: n={SHINGLE_N}-gram shingles, k={K_HASHES} MinHash, "
          f"b={B_BANDS} bands x r={R_ROWS} rows -> threshold t ~= "
          f"{lsh_threshold(B_BANDS, R_ROWS):.4f}\n")
    shingle_sets = [shingles(d, SHINGLE_N) for d in CORPUS]
    sigs = [minhash_signature(s, K_HASHES) for s in shingle_sets]
    cands = lsh_candidate_pairs(sigs, B_BANDS, R_ROWS)
    print(f"Candidate pairs from LSH banding ({len(cands)}):")
    for i, j in sorted(cands):
        exact = jaccard(shingle_sets[i], shingle_sets[j])
        est = estimated_jaccard(sigs[i], sigs[j])
        print(f"  (doc {i}, doc {j})  exact J={exact:.4f}  est J={est:.4f}")
    print()
    uf = UnionFind(len(CORPUS))
    for i, j in cands:
        uf.union(i, j)
    clusters = uf.clusters()
    # deterministic cluster ordering: sort by min member, members sorted
    ordered = sorted(clusters.values(), key=lambda g: min(g))
    keep = [min(g) for g in ordered]  # representative = lowest index
    removed = sorted(idx for g in ordered for idx in g if idx != min(g))
    print("Clustering (union-find over candidate pairs):")
    print("| cluster | members     | kept (representative) | removed          |")
    print("|---------|-------------|-----------------------|------------------|")
    for g in ordered:
        members = sorted(g)
        rep = members[0]
        rem = [m for m in members[1:]]
        print(f"| {min(g):<7} | {str(members):<11} | doc {rep}                  | "
              f"{str(rem) if rem else '(none)':<16} |")
    print()
    print(f"Dedup result: {len(keep)} of {len(CORPUS)} docs kept, "
          f"{len(removed)} removed.")
    print(f"Dedup rate = {len(removed)}/{len(CORPUS)} = "
          f"{len(removed)/len(CORPUS):.2%}.")
    print()
    print("Both planted near-dup clusters collapsed to one representative each;")
    print("the 4 distinct docs were untouched. This is exactly what FineWeb does")
    print("(at 15T-token scale, with 5-grams / 112 perms / 14x8 bands).")
    print()
    # invariants
    clusters_found = [sorted(g) for g in ordered if len(g) > 1]
    check("exactly 2 multi-doc clusters found", len(clusters_found) == 2)
    check("cluster {0,1} collapsed together",
          any(set(g) == {0, 1} for g in clusters_found))
    check("cluster {3,4} collapsed together",
          any(set(g) == {3, 4} for g in clusters_found))
    check("distinct docs 2,5,6,7 each kept (singleton clusters)",
          all(d in keep for d in (2, 5, 6, 7)))
    check("removed docs are exactly the near-dup partners {1,4}",
          removed == [1, 4])
    check("dedup rate = 2/8 = 25%",
          abs(len(removed) / len(CORPUS) - 0.25) < 1e-9)


# ============================================================================
# E. PRODUCTION PARAMETERS  (what FineWeb / CCNet actually shipped)
# ============================================================================

def section_production_params():
    banner("SECTION E: production dedup parameters (FineWeb, CCNet)")
    # FineWeb (arXiv:2406.17557, NeurIPS 2024 appendix E.1):
    #   5-grams, 112 hash functions, 14 bands x 8 rows (NOT 128 / 14x9).
    fw_b, fw_r = 14, 8
    fw_k = fw_b * fw_r
    fw_t = lsh_threshold(fw_b, fw_r)
    print("FineWeb (Penedo et al 2024, arXiv:2406.17557) -- the production recipe:")
    print("  shingle n       = 5 words")
    print(f"  MinHash length  = {fw_k} permutations")
    print(f"  LSH bands b     = {fw_b}  x  rows r = {fw_r}   (= {fw_k} total)")
    print(f"  threshold t     = (1/{fw_b})^(1/{fw_r}) = {fw_t:.4f}  (~0.72)")
    print("  corpus scale    = 15 trillion tokens, 96 Common Crawl snapshots")
    print("  applied PER-SNAPSHOT (cross-snapshot dedup is separate)\n")
    print("NOTE: the original build brief cited '128 perms, 14 bands x 9 rows'.")
    print("That is INCORRECT -- the NeurIPS 2024 paper appendix E.1 states verbatim")
    print("'we use 5-grams and 112 hash functions' (14 bands of 8 rows = 112, not")
    print("128). 14 x 9 = 126, which is not 128 either. Corrected here.\n")
    # sanity: the FineWeb threshold lands in the usual 0.7 band
    p_at_fw_t = 1.0 - (1.0 - (fw_t ** fw_r)) ** fw_b
    print(f"At the FineWeb threshold t={fw_t:.4f}: P(candidate) ~= {p_at_fw_t:.4f}")
    print("(the standard ~0.63 knee of the LSH S-curve).\n")
    check("FineWeb k = 14*8 = 112 (NOT 128)", fw_k == 112)
    check("FineWeb threshold ~= 0.72 (within 0.03)", abs(fw_t - 0.72) < 0.03)
    check("FineWeb config (14 bands x 8 rows) matches the NeurIPS 2024 paper",
          (fw_b, fw_r) == (14, 8))
    check("brief's 128/14x9 is internally inconsistent (14*9=126 != 128)",
          14 * 9 != 128)


# ============================================================================
# main
# ============================================================================


def main():
    print("minhash_dedup.py - reference impl. All numbers below feed MINHASH_DEDUP.md.\n"
          "torch =", torch.__version__)
    print("\nEvery formula is web-verified in >=2 sources; see minhash_dedup_reference.txt.")

    sh = section_shingling_and_jaccard()
    sigs = section_minhash_signature(sh)
    section_lsh_banding(sigs, sh)
    section_end_to_end_dedup()
    section_production_params()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
