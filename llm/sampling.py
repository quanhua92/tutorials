"""
sampling.py - Reference implementation of LLM decoding sampling strategies.

This is the single source of truth that SAMPLING.md is built from. Every
number, table, and worked example in SAMPLING.md is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python sampling.py

==============================================================================
THE INTUITION (read this first — no math needed)
==============================================================================
Picture a LOADED DIE with V faces (V = vocab size, one face per possible next
word). The model does NOT hand you ready-made odds; it hands you a "preference
score" (a *logit*) for every face. Sampling = pick the next word by rolling a
die whose odds are weighted by those scores. The four strategies below are four
ways of *shaping* that die before you roll it:

    greedy      (temp=0)  Always pick the single highest-scoring face.
                          Safe, but repetitive/boring.
    temperature T         How FLAT the die's odds are.
                          High T = flatten the die (more random/diverse).
                          Low  T = sharpen it  (more predictable).
                          T=0   = greedy (degenerate, no roll at all).
    top-k                 Only allow the top k faces; zero the rest.
                          Fixed k is clumsy: sometimes the model is very sure
                          (1 good word) and sometimes unsure (20 decent words),
                          yet k ignores that and always keeps exactly k.
    top-p / nucleus       The fix: keep the SMALLEST set of top faces that
                          together cover p (e.g. 60%) of the probability. It
                          ADAPTS: 1 word when the model is sure, many when it
                          isn't. Always keep the #1 face so we never pick
                          nothing.

==============================================================================
THE LINEAGE (each method fixes a flaw of the previous)
==============================================================================
    greedy (temp=0, argmax)
      -> temperature scaling   (softmax(logits/T))
      -> top-k                 (keep k highest, mask rest to -inf)
      -> top-p / nucleus       (keep smallest set whose cumulative prob >= p)

All four operate on the LM-head LOGITS, then log-softmax, then (optionally)
sample. The only step that needs randomness is the final categorical draw; the
filtering (greedy/top-k/top-p) is fully DETERMINISTIC. This file uses a FIXED
logit vector so every filtered set below is reproducible with no RNG.

==============================================================================
GLOSSARY (every term is defined at first use in SAMPLING.md too)
==============================================================================
    V          vocab size — how many faces the die has (here a tiny 8-token
               "vocab" so every number prints).
    logits     [V]  raw preference scores from the LM head. Can be any real
               number; bigger = the model likes that word more.
    softmax    turns logits into PROBABILITIES that sum to 1. Implemented as
               exp(log_softmax(z)) for numerical stability.
    log_softmax numerically-stable cousin: z - logsumexp(z). We compute this
               first, then exp() it to get probs. Never do log(sum(exp(z)))
               directly — it overflows.
    logprobs   [V]  log_softmax(logits). Always <= 0 (since probs <= 1).
    probs      [V]  exp(logprobs) = softmax(logits). Always in [0,1], sums to 1.
    temperature T   a divisor applied to logits BEFORE softmax. T<1 sharpens,
               T>1 flattens, T=0 = greedy.
    top-k      keep the k highest-scoring tokens, mask the rest to -inf.
    top-p / nucleus  keep the smallest set of tokens whose cumulative prob
               reaches p. The set size ADAPTS to the distribution shape.
    cumsum     cumulative sum — a running total. In top-p we cumsum the
               PROBABILITIES (after exp), NEVER the raw logprobs (see pitfall).
    seed       a fixed starting value for the random number generator so the
               final draw is reproducible. The filtering steps need no seed.
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72

# ============================================================================
# 0. THE FIXED INPUT  (deterministic — no RNG needed for filtering)
# ============================================================================

# 8-token "vocab". Chosen so that at top-p=0.6 the nucleus has 2 tokens while
# top-k=3 keeps 3 tokens — i.e. the two strategies visibly DISAGREE on this
# distribution. That disagreement is the whole point of the guide.
LOGITS = torch.tensor([2.3, 2.0, 0.4, 1.5, 0.1, 2.5, 0.7, 1.2], dtype=torch.float32)
V = LOGITS.shape[0]

# Token labels (purely cosmetic — makes the kept/masked tables readable).
TOKENS = ["the", "cat", "xyz", "sat", "qqq", "on", "a", "mat"]


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code SAMPLING.md walks through)
# ============================================================================

def log_softmax(z: torch.Tensor) -> torch.Tensor:
    """log_softmax(z) = z - logsumexp(z).   Numerically stable."""
    return z - torch.logsumexp(z, dim=-1, keepdim=True)


def softmax(z: torch.Tensor) -> torch.Tensor:
    """softmax(z) = exp(log_softmax(z))."""
    return torch.exp(log_softmax(z))


def greedy(logits: torch.Tensor) -> int:
    """temp=0 / greedy: always pick the face with the highest score (argmax).

    No die roll at all — just the single best face, every time. Deterministic,
    which is why it loops and repeats. Used for evaluation / factual QA.
    """
    return int(torch.argmax(logits, dim=-1))


def temperature_logits(logits: torch.Tensor, temp: float) -> torch.Tensor:
    """Scale logits by 1/temp BEFORE softmax. temp<1 sharpens the die (peaks on
    the favorite), temp>1 flattens it (spreads odds toward the long tail).
    temp=0 is handled separately as greedy (see above), never passed here.
    """
    return logits / temp


def top_k_mask(logits: torch.Tensor, k: int) -> torch.Tensor:
    """Return a COPY of logits with all but the top-k set to -inf.

    Think: keep only the k best faces of the die, blank out the rest. The size
    k is FIXED — that is its weakness (see top_p_mask for the adaptive version).

    (tiny-llm's make_sampler masks the *logprobs*; masking logits or logprobs
    gives the same result because -inf is -inf under any monotone transform.)
    """
    out = logits.clone()
    if k <= 0 or k >= logits.shape[-1]:
        return out
    # indices of the k largest values
    topk_idx = torch.topk(out, k=k, dim=-1).indices
    mask = torch.ones_like(out, dtype=torch.bool)
    mask[topk_idx] = False
    out[mask] = float("-inf")
    return out


def top_p_mask(logits: torch.Tensor, p: float) -> torch.Tensor:
    """Nucleus sampling mask. Keep smallest set whose cumulative prob >= p.

    The adaptive cousin of top-k: the size of the kept set changes with the
    distribution. When the model is sure (one word dominates) the nucleus may
    be a single token; when it is unsure (many plausible words) the nucleus
    grows. Always keeps the top-1 token, so the nucleus is never empty.

    CRITICAL PITFALL (#1 top-p bug): the cumulative sum is taken over
    PROBABILITIES (exp(logprobs)), NOT over logprobs. Log-probs are all <= 0,
    so cumsum(logprobs) stays negative forever and is ALWAYS < any positive p —
    meaning nothing gets masked and the "nucleus" silently becomes the entire
    vocabulary. Do the cumsum on PROBS, never on raw scores. (See Section F.)
    """
    out = logits.clone()
    logprobs = log_softmax(out)
    probs = torch.exp(logprobs)
    # sort descending by probability (= descending by logit)
    sorted_idx = torch.argsort(probs, descending=True)
    sorted_probs = probs[sorted_idx]
    cumsum = torch.cumsum(sorted_probs, dim=-1)
    keep = (cumsum - sorted_probs) < p            # bool mask in sorted order
    keep[0] = True               # always keep the top-1 token
    # scatter back to original order: -inf where we don't keep
    remove_sorted = ~keep
    remove = torch.zeros_like(out, dtype=torch.bool)
    remove[sorted_idx[remove_sorted]] = True
    out[remove] = float("-inf")
    return out


def sample_from(logits: torch.Tensor, seed: int | None = None) -> int:
    """Categorical draw from logits (the ONLY step that uses RNG).

    Fix the `seed` and the roll is reproducible; the deterministic filtering
    steps above need no seed at all.
    """
    if seed is not None:
        torch.manual_seed(seed)
    return int(torch.multinomial(softmax(logits), num_samples=1))


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def dist_table(title: str, logits: torch.Tensor):
    """Print logits, probs, logprobs side by side as a markdown table."""
    lp = log_softmax(logits)
    pr = torch.exp(lp)
    print(f"\n{title}\n")
    print("| idx | token |  logit  |  prob (softmax)  |  logprob (log_softmax) |")
    print("|-----|-------|---------|------------------|------------------------|")
    for i in range(logits.shape[0]):
        lg = logits[i].item()
        # handle -inf for masked entries
        lg_str = f"{lg:+.4f}" if lg != float("-inf") else "  -inf"
        pr_str = f"{pr[i].item():.4f}" if lg != float("-inf") else "0.0000"
        lp_str = f"{lp[i].item():+.4f}" if lg != float("-inf") else "  -inf"
        print(f"| {i}   | {TOKENS[i]:<5} | {lg_str:>7} | {pr_str:>16} | {lp_str:>22} |")
    total = pr.sum().item()
    print(f"\n  sum(probs) = {total:.6f}   (must be 1.0)")


# ============================================================================
# 3. SECTIONS  (the numbers that feed SAMPLING.md)
# ============================================================================

def section_a_distribution():
    banner("SECTION A: the fixed 8-token logit vector -> softmax / log_softmax")
    print(f"LOGITS (V={V}) = {[round(x, 2) for x in LOGITS.tolist()]}")
    print(f"TOKENS         = {TOKENS}")
    dist_table("Full distribution (temp=1, no filtering):", LOGITS)
    # inline-by-hand math vs helper
    inline_lp = LOGITS - torch.logsumexp(LOGITS, dim=-1)
    assert torch.allclose(inline_lp, log_softmax(LOGITS), atol=1e-6)
    print("\n  [check] logits - logsumexp(logits) == log_softmax(logits):  OK")
    assert abs(torch.exp(log_softmax(LOGITS)).sum().item() - 1.0) < 1e-6
    print("  [check] sum(softmax(logits)) == 1.0:                         OK")
    argmax_idx = int(torch.argmax(LOGITS))
    print(f"\n  argmax = idx {argmax_idx} (\"{TOKENS[argmax_idx]}\")  "
          f"— this is what greedy decoding would emit.")


def section_b_temperature():
    banner("SECTION B: temperature sweep  (softmax(logits / T))")
    print("Temperature divides the logits BEFORE softmax. Higher T => flatter\n"
          "distribution (more diverse / lower-confidence); lower T => sharper\n"
          "(more peaked on the argmax). T=0 collapses to a one-hot (= greedy).\n")
    print("| idx | token |  T=0.5   |   T=1.0   |   T=2.0   |")
    print("|-----|-------|----------|-----------|-----------|")
    for T in (0.5, 1.0, 2.0):
        pass  # precompute below
    probs = {T: softmax(LOGITS / T) for T in (0.5, 1.0, 2.0)}
    for i in range(V):
        row = (f"| {i}   | {TOKENS[i]:<5} "
               f"| {probs[0.5][i].item():.4f}   | "
               f"{probs[1.0][i].item():.4f}    | "
               f"{probs[2.0][i].item():.4f}    |")
        print(row)
    print()
    # entropy grows with T (flatter => more uncertainty)
    def entropy(p):
        return float(-(p * torch.log(p + 1e-12)).sum())
    print(f"  entropy(T=0.5) = {entropy(probs[0.5]):.4f} nats  (sharper)")
    print(f"  entropy(T=1.0) = {entropy(probs[1.0]):.4f} nats")
    print(f"  entropy(T=2.0) = {entropy(probs[2.0]):.4f} nats  (flatter => higher)")
    top1_share = {T: probs[T].max().item() for T in (0.5, 1.0, 2.0)}
    print(f"\n  top-1 prob share: T=0.5 -> {top1_share[0.5]:.4f}, "
          f"T=1.0 -> {top1_share[1.0]:.4f}, T=2.0 -> {top1_share[2.0]:.4f}")
    assert top1_share[0.5] > top1_share[1.0] > top1_share[2.0]
    print("\n  [check] top-1 share decreases as T increases (distribution flattens):  OK")


def section_c_greedy():
    banner("SECTION C: greedy decoding (temp=0) = argmax")
    g = greedy(LOGITS)
    print(f"greedy(LOGITS) = argmax = idx {g}  (\"{TOKENS[g]}\")")
    print("\n  temp=0 is a SPECIAL CASE: there is no softmax/sampling step at all.")
    print("  Every call returns the SAME token. Deterministic, repetitive, no")
    print("  diversity — used for evaluation / factual QA.")
    assert g == 5
    print(f"\n  [check] greedy picks idx 5 (\"{TOKENS[5]}\"):  OK")


def section_d_topk():
    banner("SECTION D: top-k=3  (keep the 3 highest logits, mask the rest)")
    masked = top_k_mask(LOGITS, k=3)
    kept_idx = sorted([i for i in range(V) if masked[i] != float("-inf")])
    zeroed_idx = [i for i in range(V) if masked[i] == float("-inf")]
    print(f"KEPT   indices: {kept_idx}   tokens: {[TOKENS[i] for i in kept_idx]}")
    print(f"MASKED indices: {zeroed_idx}   tokens: {[TOKENS[i] for i in zeroed_idx]}\n")
    dist_table(f"Top-k=3 distribution (renormalized over the {len(kept_idx)} kept):", masked)
    print("\n  The 5 masked tokens now have prob 0; the kept 3 share all the mass.")
    print("  top-k is FIXED-SIZE: it always keeps exactly k, regardless of whether")
    print("  the distribution is peaked or flat. That is its weakness (see Section E).")
    assert kept_idx == [0, 1, 5]
    print(f"\n  [check] top-k=3 kept indices == [0, 1, 5]:  OK")


def section_e_topp():
    banner("SECTION E: top-p=0.5 nucleus  (keep smallest set, cumulative prob >= p)")
    print("Algorithm (matches standard implementations):\n"
          "  1. sort tokens DESCENDING by probability\n"
          "  2. compute cumulative sum of the PROBABILITIES (NOT logprobs!)\n"
          "  3. keep tokens where (cumsum - prob) < p\n"
          "  4. ALWAYS keep the top-1 (nucleus is never empty)\n")
    logprobs = log_softmax(LOGITS)
    probs = torch.exp(logprobs)
    sorted_idx = torch.argsort(probs, descending=True)
    sorted_probs = probs[sorted_idx]
    cumsum = torch.cumsum(sorted_probs, dim=-1)
    print(f"Top-p = 0.5\n")
    print("| rank | idx | token |  prob   | cumsum  | prev_cumsum < 0.5? | kept? |")
    print("|------|-----|-------|---------|---------|--------------------|-------|")
    keep = (cumsum - sorted_probs) < 0.5
    keep[0] = True
    for rank in range(V):
        idx = sorted_idx[rank].item()
        pr = sorted_probs[rank].item()
        cs = cumsum[rank].item()
        prev_cs = cs - pr
        lt = "yes" if prev_cs < 0.5 else "no"
        kp = "KEEP" if keep[rank].item() else "mask"
        print(f"| {rank}    | {idx}   | {TOKENS[idx]:<5} | {pr:.4f}  | {cs:.4f}  | {lt:<18} | {kp} |")
    masked = top_p_mask(LOGITS, p=0.5)
    nucleus = sorted([i for i in range(V) if masked[i] != float("-inf")])
    nucleus_mass = sum(probs[i].item() for i in nucleus)
    print(f"\n  NUCLEUS (top-p=0.5) = indices {nucleus}  tokens {[TOKENS[i] for i in nucleus]}")
    print(f"  nucleus prob mass   = {nucleus_mass:.4f}  (>= p=0.5)")
    print(f"\n  CONTRAST top-k=3 -> kept [0, 1, 5]  vs  top-p=0.5 -> kept {nucleus}")
    print("  Here top-p is STRICTER than top-k: the top-2 already cover 52.8% of")
    print("  the mass, which crosses 0.5, so the 3rd token is cut. top-k keeps it anyway.")
    assert nucleus == [0, 5]
    print(f"\n  [check] top-p=0.5 nucleus == [0, 5]:  OK")


def section_f_pitfall():
    banner("SECTION F: PITFALL — cumsum on LOGPROBS (wrong) vs PROBS (right)")
    print("The single most common top-p bug: accumulate the LOG-probabilities\n"
          "instead of the probabilities. Log-probs are NEGATIVE (every logprob\n"
          "< 0), so their cumulative sum stays negative forever and is ALWAYS\n"
          "less than any positive p. Result: NOTHING gets masked — the 'nucleus'\n"
          "is the entire vocabulary. Silent, no error.\n")
    logprobs = log_softmax(LOGITS)
    sorted_idx = torch.argsort(logprobs, descending=True)
    sorted_logprobs = logprobs[sorted_idx]
    sorted_probs = torch.exp(sorted_logprobs)
    cumsum_probs = torch.cumsum(sorted_probs, dim=-1)
    cumsum_logprobs = torch.cumsum(sorted_logprobs, dim=-1)
    p = 0.5
    print(f"p = {p}\n")
    print("| rank | idx | token |  prob   | cumsum(probs) | <p? | "
          " logprob  | cumsum(logprobs) | <p? |")
    print("|------|-----|-------|---------|---------------|-----|"
          "----------|------------------|-----|")
    for rank in range(V):
        idx = sorted_idx[rank].item()
        pr = sorted_probs[rank].item()
        csp = cumsum_probs[rank].item()
        lp = sorted_logprobs[rank].item()
        csl = cumsum_logprobs[rank].item()
        print(f"| {rank}    | {idx}   | {TOKENS[idx]:<5} | {pr:.4f}  | "
              f"{csp:>13.4f} | {'yes' if csp<p else 'no ':<3} | "
              f"{lp:+.4f}  | {csl:>16.4f} | {'yes' if csl<p else 'no ':<3} |")
    keep_probs = (cumsum_probs - sorted_probs) < p
    keep_probs[0] = True
    keep_logprobs = (cumsum_logprobs - sorted_logprobs) < p
    keep_logprobs[0] = True
    nucleus_right = sorted([sorted_idx[i].item() for i in range(V) if keep_probs[i]])
    nucleus_wrong = sorted([sorted_idx[i].item() for i in range(V) if keep_logprobs[i]])
    print(f"\n  CORRECT (cumsum on probs):     nucleus = {nucleus_right}   "
          f"({len(nucleus_right)} tokens)")
    print(f"  WRONG    (cumsum on logprobs): nucleus = {nucleus_wrong}   "
          f"({len(nucleus_wrong)} tokens — EVERYTHING kept!)")
    assert nucleus_right == [0, 5]
    assert nucleus_wrong == list(range(V))
    print("\n  [check] correct nucleus == [0, 5]:                                OK")
    print("  [check] buggy  nucleus == all 8 tokens (no filtering at all):     OK (it's a bug!)")
    print("\n  FIX: always cumsum(exp(logprobs)) == cumsum(probs). Never the raw logprobs.")


def section_g_combined_and_sample():
    banner("SECTION G: combined pipeline + seeded sample (the only RNG step)")
    print("Production order:\n"
          "  1. temp==0  -> return argmax (greedy, no RNG)\n"
          "  2. temp     -> divide logits by temp\n"
          "  3. top-k    -> mask scaled logits to -inf outside top-k\n"
          "  4. top-p    -> mask scaled logits to -inf outside the nucleus\n"
          "  5. categorical draw (THE only random step)\n")
    # typical config
    cfg = dict(temp=0.7, top_k=3, top_p=0.5)
    print(f"Config: {cfg}\n")
    scaled_logits = LOGITS / cfg["temp"]
    masked = top_k_mask(scaled_logits, k=cfg["top_k"])
    masked = top_p_mask(masked, p=cfg["top_p"])
    probs = softmax(masked)
    kept = sorted([i for i in range(V) if masked[i] != float("-inf")])
    print(f"After temp={cfg['temp']}, top-k={cfg['top_k']} then top-p={cfg['top_p']}, kept indices = {kept}")
    print(f"Final renormalized probabilities:\n")
    print("| idx | token |   prob   |")
    print("|-----|-------|----------|")
    for i in range(V):
        v = probs[i].item() if masked[i] != float("-inf") else 0.0
        print(f"| {i}   | {TOKENS[i]:<5} | {v:.4f}   |")
    # seeded draw — reproducible
    torch.manual_seed(0)
    draw = int(torch.multinomial(probs, num_samples=1))
    print(f"\n  torch.manual_seed(0); multinomial -> idx {draw} (\"{TOKENS[draw]}\")")
    # the draw must be one of the kept tokens
    assert draw in kept
    print(f"  [check] drawn idx {draw} is in the kept set {kept}:  OK")
    print("\n  Re-run with the SAME seed -> SAME token. Change the seed -> different")
    print("  token (but always inside the nucleus). That is the only randomness.")


def section_gold_summary():
    banner("GOLD VALUES (pin these — .html must reproduce them)")
    tk3 = top_k_mask(LOGITS, k=3)
    tp5 = top_p_mask(LOGITS, p=0.5)
    kept_k = sorted([i for i in range(V) if tk3[i] != float("-inf")])
    kept_p = sorted([i for i in range(V) if tp5[i] != float("-inf")])
    print(f"  LOGITS vector   : {[round(x, 2) for x in LOGITS.tolist()]}")
    print(f"  top-k=3 kept    : {kept_k}   (deterministic, no RNG)")
    print(f"  top-p=0.5 nucleus: {kept_p}   (deterministic, no RNG)")
    print(f"  greedy (temp=0) : idx {greedy(LOGITS)}   (deterministic, no RNG)")
    print(f"\n  These three are the gold the .html recomputes and gold-checks against.")


# ============================================================================
# main
# ============================================================================

def main():
    print("sampling.py - reference impl. All numbers below feed SAMPLING.md.")
    print("torch =", torch.__version__)

    section_a_distribution()
    section_b_temperature()
    section_c_greedy()
    section_d_topk()
    section_e_topp()
    section_f_pitfall()
    section_g_combined_and_sample()
    section_gold_summary()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
