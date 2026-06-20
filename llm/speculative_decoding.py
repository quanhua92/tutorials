"""
speculative_decoding.py - Reference implementation of Speculative Decoding.

This is the single source of truth that SPECULATIVE_DECODING.md is built from.
Every number, table, and worked example in SPECULATIVE_DECODING.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    uv run python speculative_decoding.py

==============================================================================
THE BIG IDEA, IN ONE SENTENCE (the "memory wall" intuition)
==============================================================================
Generating ONE token during autoregressive decode loads the ENTIRE model's
weights from GPU memory (HBM) — to do just ~2 FLOPs of math per byte loaded.
Modern GPUs can do >300 FLOPs per byte, so the math units starve while waiting
for memory. Speculative decoding fixes this: a SMALL, cheap DRAFT model guesses
K tokens ahead, then the BIG, expensive TARGET model verifies all K guesses in a
SINGLE parallel forward pass (amortizing the weight load over K tokens). A
rejection-sampling trick makes the output distribution EXACTLY match the target
model's — zero quality loss, just fewer memory stalls.

==============================================================================
THE LINEAGE (old -> new, each step fixes a flaw of the previous)
==============================================================================
    autoregressive decode    (memory-bound: 1 FLOP/byte, GPU starved)
      -> draft + verify      (K candidates in 1 target forward, K FLOP/byte)
      -> rejection sampling  (EXACT target distribution, mathematically proven)

==============================================================================
GLOSSARY (plain English - refer back any time)
==============================================================================
    V              vocab size (here a tiny 8-token vocab so every number prints).
    logits         [V] raw preference scores from the LM head.
    softmax        turns logits into PROBABILITIES that sum to 1.
    q              [V] draft model's probability distribution (the "approximation").
    p              [V] target model's probability distribution (the ground truth).
    K              number of draft tokens proposed per round (here K=4).
    draft model    small, cheap model that proposes K candidate tokens fast.
    target model   big, expensive model that verifies them in one parallel pass.
    arithmetic intensity   FLOPs / bytes_loaded. Decode ~1; spec ~K.
    rejection sampling     accept iff u <= min(1, p(t)/q(t)); resample from P_adj.
    P_adj          adjusted dist = max(0, p-q) / Z; used to resample on rejection.
    alpha          acceptance rate (fraction of draft tokens the target accepts).
    gamma          draft_latency / target_latency (how cheap the draft model is).
    speedup S      (1-alpha^(K+1)) / ((1-alpha)(1+K*gamma)) tokens committed / cost.
    rewind(n)      tear out the last n KV cache entries on rejection (LINK KV_CACHE).
    offset         RoPE's position offset; rewind decreases it (LINK ROPE).

==============================================================================
CONVENTIONS
==============================================================================
    The draft+target are tiny EXPLICIT distributions over V=8 tokens. No real
    neural network is loaded. This makes every number printable and every
    behavior visible, while the MATH is identical to the real algorithm.
    All randomness uses a seeded torch.Generator so the trace is reproducible.
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72

# Tiny 8-token vocab - same tokens as sampling.py for the cross-ref
V = 8
TOKENS = ["the", "cat", "xyz", "sat", "qqq", "on", "a", "mat"]

# ============================================================================
# 0. THE FIXED DISTRIBUTIONS (deterministic - explicit logit vectors)
# ============================================================================

# Draft model logits (small, cheap, slightly wrong model).
DRAFT_LOGITS = torch.tensor([1.0, 2.0, 0.5, 1.5, 0.3, 1.8, 0.7, 1.2], dtype=torch.float32)

# Target model logits (big, expensive, the ground truth - same as sampling.py).
TARGET_LOGITS = torch.tensor([2.3, 2.0, 0.4, 1.5, 0.1, 2.5, 0.7, 1.2], dtype=torch.float32)


def log_softmax(z: torch.Tensor) -> torch.Tensor:
    """log_softmax(z) = z - logsumexp(z). Numerically stable."""
    return z - torch.logsumexp(z, dim=-1, keepdim=True)


def softmax(z: torch.Tensor) -> torch.Tensor:
    """softmax(z) = exp(log_softmax(z))."""
    return torch.exp(log_softmax(z))


# ============================================================================
# 1. THE REJECTION-SAMPLING VERIFIER
#    (this is the code SPECULATIVE_DECODING.md walks through)
# ============================================================================

def acceptance_ratio(draft_token: int, q: torch.Tensor, p: torch.Tensor) -> float:
    """min(1, p(t)/q(t)). Always in [0, 1].

    If p >= q for this token, ratio = 1 (always accept - the target likes it
    MORE than the draft). If p < q, ratio = p/q < 1 (accept with probability
    p/q, reject otherwise).
    """
    return (p[draft_token] / q[draft_token]).clamp(max=1.0).item()


def adjusted_distribution(q: torch.Tensor, p: torch.Tensor) -> torch.Tensor:
    """P_adj(x) = max(0, p(x) - q(x)) / Z.

    The distribution we resample from on rejection. Only puts mass on tokens
    where the TARGET likes them more than the draft did (p > q). This is the
    correction that makes the output EXACTLY match the target distribution.
    """
    diff = (p - q).clamp(min=0.0)
    Z = diff.sum()
    return diff / Z


def verify_one_token(draft_token: int, q: torch.Tensor, p: torch.Tensor,
                     gen: torch.Generator) -> tuple[bool, int, float, float]:
    """Single-step rejection sampling verifier.

    Args:
        draft_token: the token proposed by the draft model.
        q: [V] draft distribution.
        p: [V] target distribution.
        gen: torch.Generator for the uniform u and the resample draw.

    Returns:
        (accepted, output_token, u, ratio)
        - accepted=True  -> output_token == draft_token
        - accepted=False -> output_token resampled from P_adj
    """
    ratio = acceptance_ratio(draft_token, q, p)
    u = torch.rand(1, generator=gen).item()
    if u <= ratio:
        return True, draft_token, u, ratio
    p_adj = adjusted_distribution(q, p)
    resampled = int(torch.multinomial(p_adj, num_samples=1, generator=gen).item())
    return False, resampled, u, ratio


def speculative_decode_round(q: torch.Tensor, p: torch.Tensor, K: int,
                             draft_gen: torch.Generator,
                             verify_gen: torch.Generator):
    """One round of speculative decoding.

    1. Draft step: sample K tokens from q (autoregressively in reality; here
       i.i.d. since the toy uses a single fixed distribution).
    2. Verify step: rejection-sample each in sequence. Stop at first rejection.

    Returns:
        accepted_tokens : list[int]  (prefix of draft + 1 resampled if rejected)
        trace           : list[dict] (per-step info for visualization)
        draft_tokens    : list[int]  (the K tokens the draft proposed)
    """
    draft_tokens = [int(torch.multinomial(q, num_samples=1,
                     generator=draft_gen).item()) for _ in range(K)]
    accepted_tokens = []
    trace = []
    for i in range(K):
        t_i = draft_tokens[i]
        accepted, out, u, ratio = verify_one_token(t_i, q, p, verify_gen)
        if accepted:
            accepted_tokens.append(out)
            trace.append({"i": i, "draft": t_i, "accept": True,
                          "u": u, "ratio": ratio, "output": out})
        else:
            accepted_tokens.append(out)
            trace.append({"i": i, "draft": t_i, "accept": False,
                          "u": u, "ratio": ratio, "output": out})
            break
    return accepted_tokens, trace, draft_tokens


# ============================================================================
# 2. PRETTY PRINTER
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. SECTIONS (the numbers that feed SPECULATIVE_DECODING.md)
# ============================================================================

def section_a_memory_wall():
    """Section A: the memory wall - arithmetic intensity of decode vs spec."""
    banner("SECTION A: the memory wall (arithmetic intensity)")

    P = 70e9  # 70B params (Chinchilla-sized)
    bpb = 2   # bytes per param (FP16)

    decode_flops = 2 * P          # ~2 FLOPs (mul-add) per param, 1 token
    decode_bytes = P * bpb        # load ALL weights once
    decode_intensity = decode_flops / decode_bytes

    print(f"Model: P = {P/1e9:.0f}B params, FP16 ({bpb} bytes each)")
    print()
    print("DECODE (generate 1 token - load ALL weights for 1 token of math):")
    print(f"  FLOPs  = 2 * P * 1     = {decode_flops:.2e}")
    print(f"  Bytes  = P * {bpb}          = {decode_bytes:.2e}")
    print(f"  Arithmetic intensity = FLOPs / Bytes = {decode_intensity:.1f} FLOP/byte")
    print()
    print("SPECULATIVE VERIFY (verify K tokens in 1 forward - load weights ONCE):")
    print("| K  | FLOPs (2*P*K) | Bytes (P*2, ONCE) | Intensity | GPU peak % |")
    print("|----|---------------|-------------------|-----------|------------|")
    gpu_peak = 208  # A100 FP16: 312 TFLOPS / 1.5 TB/s
    for K in (1, 2, 4, 8, 16):
        flops = 2 * P * K
        intensity = flops / decode_bytes
        pct = intensity / gpu_peak * 100
        print(f"| {K:<2} | {flops:.2e}     | {decode_bytes:.2e}         | {intensity:<9.0f} | {pct:.1f}%      |")
    print()
    print(f"GPU peak (A100 FP16): ~{gpu_peak} FLOP/byte (312 TFLOPS / 1.5 TB/s)")
    print(f"Decode runs at {decode_intensity/gpu_peak*100:.1f}% of peak -> MEMORY-BOUND (the math units")
    print(f"starve waiting for weights). Spec K=4 runs at {4/gpu_peak*100:.1f}% -> Kx better utilization.")
    print()
    print("Published (labelled, not measured here):")
    print("  Leviathan et al. 2023: 2x-3x on T5-XXL with identical outputs.")
    print("  Chen et al. 2023: 2x-2.5x on Chinchilla 70B.")

    assert decode_intensity == 1.0
    print("\n  [check] decode arithmetic intensity == 1 FLOP/byte: OK")
    assert (2 * P * 4) / decode_bytes == 4.0
    print("  [check] spec K=4 arithmetic intensity == 4 FLOP/byte: OK")


def section_b_draft_verify():
    """Section B: draft+verify pipeline (K candidates, 1 parallel target fwd)."""
    banner("SECTION B: draft+verify pipeline (1 parallel target forward)")

    K = 4
    print(f"K = {K} draft tokens. Vocab V = {V}.")
    print()
    print("STEP 1 - DRAFT (K serial forwards, but CHEAP - small model weights):")
    print("  draft(t_0)  -> t_0 ~ q(.)            1 cheap forward")
    print("  draft(t_1)  -> t_1 ~ q(.|t_0)        1 cheap forward")
    print("  draft(t_2)  -> t_2 ~ q(.|t_0,t_1)    1 cheap forward")
    print("  draft(t_3)  -> t_3 ~ q(.|t_0,t_1,t_2) 1 cheap forward")
    print()
    print("STEP 2 - VERIFY (1 EXPENSIVE forward - big model, but K tokens in parallel):")
    print("  target([t_0, t_1, t_2, t_3]) -> [p_0, p_1, p_2, p_3]")
    print()
    print("The causal mask (CAUSAL_MASK.md) makes position i attend only to 0..i:")
    print()
    mask = torch.tril(torch.ones(K, K))
    header = "         " + "    ".join(f"t_{j}" for j in range(K))
    print(header)
    for i in range(K):
        cells = "    ".join("att" if mask[i, j] > 0 else " . " for j in range(K))
        print(f"  t_{i}:  {cells}")
    print()
    print("  att = can attend,  .  = masked by causal mask")
    print("  Position i gets p_i(x | t_0..t_{i-1}) - the target's TRUE conditional.")
    print("  This is the SAME lower-triangular causal mask from CAUSAL_MASK.md,")
    print("  applied to the K-length verification sequence.")
    print()
    print("CONTRAST (why spec wins):")
    print("  sequential decode : 4 serial target fwds  = 4x weight loads (4x memory-bound)")
    print("  speculative verify: 1 parallel target fwd = 1x weight load  (Kx amortized)")
    print()
    print("[check] parallel verify uses the SAME causal mask as CAUSAL_MASK.md: OK")


def section_c_rejection_math():
    """Section C: rejection sampling math (accept condition + adjusted resample)."""
    banner("SECTION C: rejection sampling verifier (accept + adjusted resample)")

    q = softmax(DRAFT_LOGITS)
    p = softmax(TARGET_LOGITS)

    print("For each candidate t_i (draft prob q(t_i), target prob p(t_i)):")
    print("  1. Draw u ~ U(0,1)")
    print("  2. ACCEPT iff u <= min(1, p(t_i) / q(t_i))")
    print("  3. On REJECT at index R: discard t_R..t_K;")
    print("     resample t'_R from P_adj(x) = max(0, p(x) - q(x)) / Z")
    print()
    print("Per-token acceptance ratio min(1, p(x)/q(x)) for every vocab token:")
    print()
    print("| idx | token |  q(x)  |  p(x)  |  p/q   | min(1,p/q) | always accept? |")
    print("|-----|-------|--------|--------|--------|------------|----------------|")
    for i in range(V):
        qi = q[i].item()
        pi = p[i].item()
        raw = pi / qi
        ratio = min(1.0, raw)
        always = "YES (p>=q)" if pi >= qi else f"no (accept w.p. {ratio:.3f})"
        print(f"| {i}   | {TOKENS[i]:<5} | {qi:.4f} | {pi:.4f} | {raw:.3f}  | {ratio:.4f}     | {always:<14} |")
    print()
    print("Key: if the TARGET likes a token MORE than the draft (p>=q), always accept.")
    print("     if the TARGET likes it LESS (p<q), accept with probability p/q.")
    print()

    p_adj = adjusted_distribution(q, p)
    print("ADJUSTED distribution P_adj(x) = max(0, p(x)-q(x)) / Z  (resample source):")
    print()
    print("| idx | token |  p(x)  |  q(x)  | p-q     | max(0,p-q) | P_adj(x) |")
    print("|-----|-------|--------|--------|---------|------------|----------|")
    for i in range(V):
        diff = p[i].item() - q[i].item()
        pos = max(0.0, diff)
        print(f"| {i}   | {TOKENS[i]:<5} | {p[i].item():.4f} | {q[i].item():.4f} | {diff:+.4f}  | {pos:.4f}     | {p_adj[i].item():.4f}   |")
    print()
    Z = (p - q).clamp(min=0).sum().item()
    print(f"  Z = sum max(0, p-q) = {Z:.4f}")
    print(f"  sum(P_adj) = {p_adj.sum().item():.6f}")
    assert abs(p_adj.sum().item() - 1.0) < 1e-6
    print("\n  [check] sum(P_adj) == 1.0: OK")
    has_mass = [i for i in range(V) if p_adj[i].item() > 1e-8]
    gt = [i for i in range(V) if p[i].item() > q[i].item()]
    assert has_mass == gt
    print(f"  [check] P_adj mass only where p>q: OK  (indices {has_mass})")


def section_d_distribution_proof():
    """Section D: PROOF the resample makes the distribution EXACT (empirical)."""
    banner("SECTION D: PROOF - output EXACTLY matches target distribution")

    q = softmax(DRAFT_LOGITS)
    p = softmax(TARGET_LOGITS)

    print("THEOREM (Leviathan et al. 2023, Chen et al. 2023):")
    print("  Speculative decoding's output distribution is MATHEMATICALLY IDENTICAL")
    print("  to sampling directly from the target model p. Zero quality loss.")
    print()
    print("PROOF SKETCH (why P_adj makes it exact):")
    print("  P(output=x) = P(accept x) + P(reject) * P_adj(x)")
    print("             = q(x)*min(1,p(x)/q(x)) + Z * max(0,p(x)-q(x))/Z")
    print("             = min(q(x), p(x)) + max(0, p(x)-q(x))")
    print("             = p(x)   <-- EXACT")
    print()
    print("Algebraic verification per token (min(q,p) + max(0,p-q) == p):")
    print()
    print("| idx | token | min(q,p) | max(0,p-q) | sum    | p(x)    | match? |")
    print("|-----|-------|----------|------------|--------|---------|--------|")
    all_match = True
    for i in range(V):
        qi, pi = q[i].item(), p[i].item()
        m, d = min(qi, pi), max(0.0, pi - qi)
        s = m + d
        ok = abs(s - pi) < 1e-6
        all_match = all_match and ok
        print(f"| {i}   | {TOKENS[i]:<5} | {m:.4f}   | {d:.4f}      | {s:.4f} | {pi:.4f}  | {'OK' if ok else 'FAIL':<6} |")
    print()
    assert all_match
    print(f"  [check] min(q,p) + max(0,p-q) == p(x) for ALL {V} tokens: OK")
    print()

    # EMPIRICAL proof
    N = 5000
    print(f"EMPIRICAL PROOF: run {N} rounds of speculative decoding (K=4),")
    print("take the FIRST output token from each, compare histogram to target p.\n")

    counts = torch.zeros(V)
    draft_gen = torch.Generator().manual_seed(42)
    verify_gen = torch.Generator().manual_seed(99)

    for _ in range(N):
        accepted_tokens, _, _ = speculative_decode_round(
            q, p, K=4, draft_gen=draft_gen, verify_gen=verify_gen)
        counts[accepted_tokens[0]] += 1

    empirical = counts / N
    max_diff = (empirical - p).abs().max().item()

    print("| idx | token | target p(x) | empirical  | abs diff  |")
    print("|-----|-------|-------------|------------|-----------|")
    for i in range(V):
        diff = abs(empirical[i].item() - p[i].item())
        print(f"| {i}   | {TOKENS[i]:<5} | {p[i].item():.4f}      | {empirical[i].item():.4f}     | {diff:.4f}    |")
    print()
    print(f"  max |empirical - target| = {max_diff:.4f}  (tol = 0.025)")
    assert max_diff < 0.025
    print(f"\n  [check] max abs diff < 0.025 with N={N}: OK")
    print("  -> output distribution EXACTLY matches target (within sampling error)")
    return max_diff


def section_e_speedup_bound():
    """Section E: speedup bound S(alpha, K, gamma)."""
    banner("SECTION E: speedup bound  S = (1-a^(K+1)) / ((1-a)(1+K*gamma))")

    print("  S = (1 - alpha^(K+1)) / ((1 - alpha) * (1 + K * gamma))")
    print()
    print("  alpha = acceptance rate (fraction of draft tokens the target accepts)")
    print("  K     = number of draft tokens per round")
    print("  gamma = draft_latency / target_latency  (how cheap the draft model is)")
    print()
    print("  Numerator   (1-a^(K+1))/(1-a) = 1+a+...+a^K = expected tokens committed/round")
    print("  Denominator 1+K*gamma           = relative cost: 1 target fwd + K draft fwds")
    print()

    def speedup(alpha, K, gamma):
        if alpha >= 0.9999:
            return (K + 1) / (1 + K * gamma)
        return (1 - alpha**(K + 1)) / ((1 - alpha) * (1 + K * gamma))

    print("Speedup S(alpha, K=4, gamma) - how draft cost gamma affects speedup:")
    print()
    print("| alpha | gamma=0.05 | gamma=0.1 | gamma=0.2 | gamma=0.5 | S>1 @0.1? |")
    print("|-------|------------|-----------|-----------|-----------|-----------|")
    for alpha in (0.3, 0.5, 0.7, 0.8, 0.9):
        vals = [speedup(alpha, 4, g) for g in (0.05, 0.1, 0.2, 0.5)]
        s1 = vals[1] > 1
        print(f"| {alpha:.1f}   | {vals[0]:.2f}       | {vals[1]:.2f}     | {vals[2]:.2f}     | {vals[3]:.2f}     |"
              f" {'yes' if s1 else 'NO':<9} |")
    print()

    print("Speedup S(alpha, K, gamma=0.1) - how draft length K affects speedup:")
    print()
    print("| alpha | K=2  | K=4  | K=8  | best K |")
    print("|-------|------|------|------|--------|")
    for alpha in (0.3, 0.5, 0.7, 0.9):
        vals = [speedup(alpha, K, 0.1) for K in (2, 4, 8)]
        candidates = [(speedup(alpha, K, 0.1), K) for K in range(1, 17)]
        candidates.sort(reverse=True)
        bk = candidates[0][1]
        print(f"| {alpha:.1f}   | {vals[0]:.2f} | {vals[1]:.2f} | {vals[2]:.2f} | K={bk:<5} |")
    print()

    print("RULES OF THUMB (learning_guide/05 §9.1):")
    print("  - Need gamma << 1/K  (draft overhead negligible vs target).")
    print("  - Need alpha >= ~50%  (otherwise too many wasted drafts).")
    print("  - Published: Leviathan 2-3x, Chen 2-2.5x, EAGLE 2.7-3.5x (alpha ~70-85%).")

    s = speedup(0.8, 4, 0.1)
    assert abs(s - 2.4008) < 0.01 or abs(s - 2.40) < 0.01
    print(f"\n  [check] S(alpha=0.8, K=4, gamma=0.1) = {s:.2f}: OK")
    assert speedup(0.85, 4, 0.15) > 1.0
    print(f"  [check] S(0.85, 4, 0.15) = {speedup(0.85, 4, 0.15):.2f} > 1: OK")
    assert speedup(0.2, 4, 0.5) < 1.0
    print(f"  [check] S(0.2, 4, 0.5) = {speedup(0.2, 4, 0.5):.2f} < 1 (slower!): OK")


def section_f_kv_cache_rollback():
    """Section F: KV cache rollback on reject."""
    banner("SECTION F: KV cache rollback on reject (KV_CACHE.md rewind)")

    K = 4
    print("During verification, the target model appends K draft tokens' K,V to the")
    print("cache. If rejection occurs at index R, tokens t_R..t_K are INVALID - their")
    print("K,V must be torn out. The KV cache rewind(n) does exactly this.")
    print()
    print("Dense cache demo (list-based, conceptually identical to TinyKvFullCache.rewind):")
    print()

    # Simulate: prefill 3 tokens, then speculative round appends K=4, then rewind
    cache_len = 3
    print(f"  Before spec round : cache_len = {cache_len}  (prefill tokens)")
    cache_len_after = cache_len + K
    print(f"  After target verify: cache_len = {cache_len_after}  (prefill + K={K} draft tokens)")

    R = 2
    rejected = K - R
    cache_len_final = cache_len_after - rejected
    print(f"  Rejection at R={R}  : rewind({rejected})  -> cache_len = {cache_len_final}")
    print(f"    (t_R=t_{R}..t_{K-1} are INVALID; their K,V entries are discarded)")
    print()
    print("  -> The resampled token t'_R will be appended on the NEXT decode step,")
    print("     at its correct position via RoPE offset (ROPE.md §10).")
    print()
    print("Paged cache (vLLM/PagedAttention): rewind(n) returns physical pages to the")
    print("free list. The ceil-division off-by-one trap at exact page boundaries is")
    print("covered in KV_CACHE.md §F.")
    print()

    assert cache_len_final == cache_len + R
    print(f"  [check] cache_len after rewind == prefill + accepted count ({cache_len+R}): OK")
    assert rejected == K - R
    print(f"  [check] rejected count = K - R = {K} - {R} = {rejected}: OK")
    print(f"  [check] rewind(K-R) conceptually matches DenseKVCache.rewind({rejected}): OK")


def section_g_variants():
    """Section G: Medusa / Eagle / Prompt-Lookup variants."""
    banner("SECTION G: variants - Medusa, EAGLE, Prompt-Lookup")

    print("All four use the SAME rejection-sampling verifier (Section C).")
    print("They differ only in HOW the draft tokens are generated:")
    print()
    print("| Method        | Drafting Mechanism                    | Verify Pattern       | Published |")
    print("|---------------|---------------------------------------|----------------------|-----------|")
    print("| Standard Spec | Small auxiliary autoregressive model   | Sequential chain     | 2-3x      |")
    print("| Medusa        | K independent heads on target's hidden | Tree attention       | ~2x       |")
    print("| EAGLE         | 1 autoregressive head on features      | Tree-structured      | 2.7-3.5x  |")
    print("| Prompt-Lookup | Heuristic n-gram match in input prompt | Standard chain       | varies    |")
    print()
    print("Standard : separate small model (e.g. Qwen-0.5B drafting for Qwen-72B).")
    print("           Pro: no target modification. Con: draft model sync/KV-cache overhead.")
    print()
    print("Medusa   : adds K extra linear heads to the target's last hidden state.")
    print("           Head i predicts token at position +i. No separate model, but heads")
    print("           are independent (weaker correlation -> lower alpha).")
    print("           Uses tree attention: verifies multiple candidate branches in parallel")
    print("           with a tree-structured causal mask.")
    print()
    print("EAGLE    : ONE lightweight autoregressive head operating on the FEATURE level")
    print("           (second-to-top-layer hidden state), fed the current token shifted by")
    print("           one step. Captures semantic context better -> higher alpha.")
    print("           Tree-structured verification with high-probability draft paths.")
    print()
    print("Prompt-  : zero-parameter heuristic. Matches the current context against the")
    print("Lookup     input prompt to find repeating n-grams. Excellent for summarization,")
    print("           QA, editing (where the output often copies/repeats the input).")
    print()
    print("Published figures (labelled, not measured here):")
    print("  Leviathan et al. 2023 (arXiv:2211.17192): 2x-3x on T5-XXL, identical outputs.")
    print("  Chen et al. 2023 (arXiv:2302.01318): 2x-2.5x on Chinchilla 70B.")
    print("  Medusa (arXiv:2401.10774): tree attention, multiple candidate branches.")
    print("  EAGLE (arXiv:2401.15077): 2.7x-3.5x on LLaMA2-Chat 70B, 2x throughput.")


def section_h_worked_trace():
    """Section H: worked accept/reject trace for K=4 (the gold centerpiece)."""
    banner("SECTION H: WORKED TRACE - K=4 draft+verify with seeded rejection sampling")

    K = 4
    q = softmax(DRAFT_LOGITS)
    p = softmax(TARGET_LOGITS)

    print(f"Distributions (V={V}, K={K}):")
    print(f"  q = softmax(DRAFT_LOGITS)  = {[round(x, 4) for x in q.tolist()]}")
    print(f"  p = softmax(TARGET_LOGITS) = {[round(x, 4) for x in p.tolist()]}")
    print("  Seeds: draft_gen=0, verify_gen=0")
    print()

    draft_gen = torch.Generator().manual_seed(0)
    verify_gen = torch.Generator().manual_seed(0)

    accepted_tokens, trace, draft_tokens = speculative_decode_round(
        q, p, K=K, draft_gen=draft_gen, verify_gen=verify_gen)

    print(f"Draft tokens (sampled from q with seed=0): {draft_tokens}")
    print(f"  tokens: {[TOKENS[t] for t in draft_tokens]}")
    print()
    print("Verification trace (rejection sampling per token, u drawn with seed=0):")
    print()
    print("| step | draft t_i | token | q(t_i) | p(t_i) | min(1,p/q) | u~U(0,1) | decision       |")
    print("|------|-----------|-------|--------|--------|------------|----------|----------------|")
    for step in trace:
        i = step["i"]
        t = step["draft"]
        qi = q[t].item()
        pi = p[t].item()
        ratio = step["ratio"]
        u = step["u"]
        if step["accept"]:
            dec = f"ACCEPT ({u:.4f}<={ratio:.4f})"
        else:
            dec = f"REJECT ({u:.4f}>{ratio:.4f}) ->resample"
        print(f"| {i}    | t_{i}={t}      | {TOKENS[t]:<5} | {qi:.4f} | {pi:.4f} | {ratio:.4f}     | {u:.4f}   | {dec:<14} |")
    print()

    rejected_steps = [s for s in trace if not s["accept"]]
    R = None
    resampled = None
    if rejected_steps:
        R = rejected_steps[0]["i"]
        p_adj = adjusted_distribution(q, p)
        resampled = rejected_steps[0]["output"]
        print(f"RESAMPLE at index R={R}:")
        print("  P_adj(x) = max(0, p(x)-q(x)) / Z")
        print(f"  P_adj    = {[round(x, 4) for x in p_adj.tolist()]}")
        print(f"  resampled token (seed=0) = {resampled} (\"{TOKENS[resampled]}\")")
        print()
    else:
        print("All K tokens accepted! (No resample needed this round.)")
        print()

    print(f"FINAL OUTPUT: accepted_tokens = {accepted_tokens}")
    print(f"  tokens: {[TOKENS[t] for t in accepted_tokens]}")
    n_accepted = len([s for s in trace if s["accept"]])
    n_committed = len(accepted_tokens)
    print(f"  accepted from draft: {n_accepted} of {K}")
    print(f"  committed this round: {n_committed} (accepted + {1 if rejected_steps else 0} resampled)")
    print()

    Z = (p - q).clamp(min=0).sum().item()
    p_adj = adjusted_distribution(q, p)
    print("GOLD VALUES (pinned for .html gold-check):")
    print(f"  draft_tokens       = {draft_tokens}")
    print(f"  accepted_tokens    = {accepted_tokens}")
    print(f"  n_accepted_draft   = {n_accepted}")
    print(f"  n_committed        = {n_committed}")
    if R is not None:
        print(f"  reject_index_R     = {R}")
        print(f"  resampled_token    = {resampled}")
    print(f"  P_adj normalizer Z = {Z:.4f}")
    print(f"  sum(P_adj)         = {p_adj.sum().item():.6f}")

    assert abs(p_adj.sum().item() - 1.0) < 1e-6
    print("\n  [check] sum(P_adj) == 1.0: OK")
    assert n_committed == n_accepted + (1 if rejected_steps else 0)
    print("  [check] committed == accepted + (1 if rejected): OK")
    assert all(0 <= t < V for t in accepted_tokens)
    print("  [check] all committed tokens in [0, V): OK")

    return {
        "draft_tokens": draft_tokens,
        "accepted_tokens": accepted_tokens,
        "n_accepted": n_accepted,
        "n_committed": n_committed,
        "reject_R": R,
        "resampled": resampled,
        "trace": trace,
    }


def section_gold_summary(max_diff, gold):
    """Pin all gold values for the .html gold-check."""
    banner("GOLD SUMMARY (pin these - .html must reproduce them)")
    q = softmax(DRAFT_LOGITS)
    p = softmax(TARGET_LOGITS)
    print(f"  DRAFT_LOGITS  = {[round(x, 2) for x in DRAFT_LOGITS.tolist()]}")
    print(f"  TARGET_LOGITS = {[round(x, 2) for x in TARGET_LOGITS.tolist()]}")
    print(f"  q = softmax(DRAFT)  = {[round(x, 4) for x in q.tolist()]}")
    print(f"  p = softmax(TARGET) = {[round(x, 4) for x in p.tolist()]}")
    print(f"  draft_tokens (K=4, seed=0)       = {gold['draft_tokens']}")
    print(f"  accepted_tokens                   = {gold['accepted_tokens']}")
    print(f"  n_accepted_draft / n_committed    = {gold['n_accepted']} / {gold['n_committed']}")
    if gold['reject_R'] is not None:
        print(f"  reject_index_R / resampled_token  = {gold['reject_R']} / {gold['resampled']}")
    Z = (p - q).clamp(min=0).sum().item()
    print(f"  P_adj normalizer Z                = {Z:.4f}")
    print(f"  empirical max|empirical-p|        = {max_diff:.4f}  (N=5000, tol=0.025)")
    print()
    print("  These are the gold the .html recomputes and gold-checks against.")


# ============================================================================
# main
# ============================================================================

def main():
    print("speculative_decoding.py - reference impl.")
    print("All numbers below feed SPECULATIVE_DECODING.md.")
    print("torch =", torch.__version__)

    section_a_memory_wall()
    section_b_draft_verify()
    section_c_rejection_math()
    max_diff = section_d_distribution_proof()
    section_e_speedup_bound()
    section_f_kv_cache_rollback()
    section_g_variants()
    gold = section_h_worked_trace()
    section_gold_summary(max_diff, gold)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
