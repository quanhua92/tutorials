"""
vocab_rationalization.py - Reference implementation of the vocabulary parameter tax.

This is the single source of truth that VOCAB_RATIONALIZATION.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python vocab_rationalization.py

== The big idea, in one paragraph (no math) ==================================
Every Transformer keeps a lookup table that maps each of its V vocabulary tokens to an
H-dimensional vector -- the input embedding. That table alone costs V*H parameters.
The output (lm_head) that turns a hidden state back into V logits costs *another* V*H
parameters -- unless it is WEIGHT-TIED to the input table (🔗 SHARED_EMBEDDINGS). For a
1.5B-class model with H=2048, the modest Llama-3-style V=128k table costs 262.7M params
PER table -- and the giant Gemma-2-256k table costs 524.3M params per table. In a model
that is only ~1.5B parameters total, that "vocab tax" DOMINATES the budget and steals
capacity from the self-attention and MLP blocks that actually do the reasoning. That is
why small/edge models (SmolLM2, V=49152) deliberately keep the vocabulary SMALL: every
million parameters spent on a rare-token row is a million not spent on a deeper/wider
reasoning core. The sweet spot for 1-3B models is ~32k-64k.

== The lineage (old -> new, with WHY) =========================================
  big vocab (Llama-3 V=128256, Gemma-2 V=256000) : multilingual + code coverage, fewer
                 tokens per text -> faster inference per sequence; the tax is bearable
                 because the model is BIG (8B+), so V*H is a small % of N.
  -> SMALL vocab for SLMs (SmolLM2 V=49152)     : the SAME V*H table is now a LARGE %
                 of a small N. Halving V from 128k to 49k at H=2048 FREES ~161M params
                 (= ~2 transformer layers worth) for attention/MLP. Single-language /
                 edge SLMs accept slightly worse token compression to buy back capacity.
  -> weight tying (🔗)                          : whether big or small, tying the
                 lm_head to the embedding recovers one whole V*H table (halves the tax).
                 Nearly all modern SLMs tie; Llama-3 (a big model that can afford not to)
                 is the conspicuous untied example.

== Plain-English glossary =====================================================
    V (vocab_size)  number of tokenizer tokens the model knows (e.g. 49152).
    H (hidden_size) the width of every hidden vector (the embedding dim, e.g. 2048).
    embed table     the [V, H] matrix that looks up a token id -> vector. Costs V*H.
    lm_head         the [H, V] matrix that projects a vector -> V logits. Costs V*H.
    tied            lm_head.weight IS the embed table (transposed) -> only ONE V*H table.
    untied          lm_head is a separate matrix -> TWO V*H tables (2*V*H total tax).
    L (layers)      number of Transformer decoder blocks (depth).
    I (intermediate)MLP inner dim (SwiGLU/GeGLU), typically ~3-4x H.
    N (total)       total parameter count of the model.

== How total params are counted (the param-budget pie) ========================
For a decoder-only Transformer (Llama/Gemma/Qwen style), params decompose as:
    embed          = V*H                       (the input lookup table)
    per layer:
      attention    = 2*H*q_dim + 2*H*kv_dim    (Wq+Wo are H*q_dim each; Wk+Wv are
                                                H*kv_dim each; q_dim=n_heads*head_dim,
                                                kv_dim=n_kv_heads*head_dim -> GQA-aware)
      MLP          = 3*H*I                     (SwiGLU: gate + up + down)
      norms        = 2*H                       (2 RMSNorms/layer; <0.01% of N)
    final norm     = H
    lm_head        = V*H  if untied, else 0    (tied -> 0 extra)
The "body" (L layers of attn+MLP) is where reasoning capacity lives; the "vocab" slice
(embed + lm_head) is a FIXED TAX that grows with V. The pie = vocab slice vs body slice.
(Computed totals below match each model's official size class -- 135M/1.7B/2.6B/8B/1.5B
-- which cross-validates the counter.)

== Shape conventions ==========================================================
    embed.weight : [V, H]      (rows = tokens, cols = hidden dims)
    lm_head.weight: [V, H]     (untied: same shape, independent values; tied: SAME tensor)
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ----------------------------------------------------------------------------
# PRETTY PRINTERS + check() helper (no raw assert -- assert is compiled out by -O)
# ----------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(desc: str, ok: bool):
    """Print '[check] desc: OK' and exit non-zero on failure (assert is unsafe)."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def fmt_m(n: float) -> str:
    """Format a parameter count as e.g. '100.66M' / '1.71B' / '134.52M'."""
    a = abs(n)
    if a >= 1e9:
        return f"{n / 1e9:.2f}B"
    if a >= 1e6:
        return f"{n / 1e6:.2f}M"
    if a >= 1e3:
        return f"{n / 1e3:.2f}K"
    return f"{n:.2f}"


# ============================================================================
# 0. THE PARAM COUNTER (closed-form, config-driven, GQA-aware)
#    The single function every section below calls. Numbers are REAL: feeding the
#    five real-model configs reproduces their official size classes (see Section B).
# ============================================================================

def transformer_params(V: int, H: int, inter: int, L: int,
                       n_heads: int, n_kv_heads: int, head_dim: int,
                       tied: bool) -> dict:
    """Decompose a decoder-only Transformer's parameter count.

    Returns a dict with: embed, attn (per-layer and total), mlp (per-layer and
    total), norms, lm_head (0 if tied), vocab (embed+lm_head), body (L layers),
    total. Norms use 2 RMSNorms per layer (Llama/Qwen style); Gemma-2 uses 4 per
    layer but the extra <0.01% of N is negligible and omitted for uniformity.
    """
    embed = V * H
    q_dim = n_heads * head_dim           # query projection output width
    kv_dim = n_kv_heads * head_dim       # key/value projection output width (GQA)
    attn_layer = 2 * H * q_dim + 2 * H * kv_dim   # Wq+Wo (H*q_dim) + Wk+Wv (H*kv_dim)
    mlp_layer = 3 * H * inter                     # SwiGLU/GeGLU: gate + up + down
    norm_layer = 2 * H                            # input_norm + post_attn_norm
    per_layer = attn_layer + mlp_layer + norm_layer
    body = per_layer * L
    final_norm = H
    lm_head = 0 if tied else V * H
    vocab = embed + lm_head
    total = vocab + body + final_norm
    return {
        "V": V, "H": H, "inter": inter, "L": L, "tied": tied,
        "embed": embed, "attn_layer": attn_layer, "attn_total": attn_layer * L,
        "mlp_layer": mlp_layer, "mlp_total": mlp_layer * L,
        "per_layer": per_layer, "body": body, "final_norm": final_norm,
        "lm_head": lm_head, "vocab": vocab, "total": total,
    }


def embed_params(V: int, H: int) -> int:
    """One embedding table = V*H params (the vocab tax, per table)."""
    return V * H


# ============================================================================
# A. THE V*H FORMULA + TIED vs UNTIED  (gold anchor pinned for vocab_rationalization.html)
# ============================================================================

def section_formula():
    banner("SECTION A: the vocab tax formula  embed = V*H  (tied vs untied)")
    V_grid = [49152, 128256, 256000]
    H_grid = [2048, 3072, 4096]
    print("One embedding table holds V*H numbers (V rows of H dims each):\n")
    print("| V        \\ H   | " + " | ".join(f"H={h}" for h in H_grid) + " |")
    print("|" + "---|" * (len(H_grid) + 1))
    for V in V_grid:
        cells = " | ".join(fmt_m(embed_params(V, h)) for h in H_grid)
        print(f"| V={V:<8}     | {cells} |")
    print()
    print("GOLD ANCHOR (vocab_rationalization.html recomputes & gold-checks this):")
    gold_V, gold_H = 49152, 2048
    gold = embed_params(gold_V, gold_H)
    print(f"    V={gold_V}, H={gold_H}  ->  embed = {gold_V}*{gold_H} = {gold:,} "
          f"({fmt_m(gold)})")
    check("V=49152,H=2048 embed == 100,663,296", gold == 100_663_296)

    print()
    print("TIED vs UNTIED -- the lm_head doubles the tax unless weights are tied:\n")
    print("| V        | H    | tied (1 table) | untied (2 tables) | untied/tied |")
    print("|----------|------|----------------|-------------------|-------------|")
    cases = [(49152, 2048), (128256, 4096), (256000, 2304), (151936, 1536)]
    for V, H in cases:
        tied = embed_params(V, H)
        untied = 2 * tied
        print(f"| {V:<8} | {H:<4} | {tied:>13,} | {untied:>17,} | "
              f"{untied / tied:>11.1f}x |")
    print()
    print("  -> tying recovers exactly ONE V*H table (halves the tax).")
    print("     Llama-3 is UNTIED (2*525.3M = 1.05B of its 8.03B is pure vocab);")
    print("     SmolLM2 / Qwen2.5 / Gemma-2 are TIED (one table).  See Section B.\n")
    # the absurd headline from the brief
    absurd = 2 * embed_params(256000, 2048)
    print("  absurd check: a nominal-1.5B model, H=2048, V=256000, UNTIED would spend")
    print(f"    2 * {embed_params(256000, 2048):,} = {absurd:,} ({fmt_m(absurd)}) on vocab")
    print(f"    ALONE -> {absurd / 1.5e9 * 100:.0f}% of a 1.5B budget consumed by tables.\n")
    check("untied V=256k,H=2048 = 1,048,576,000",
          2 * embed_params(256000, 2048) == 1_048_576_000)


# ============================================================================
# B. THE REAL-MODELS TABLE  (the centerpiece -- configs web-verified from config.json)
#    SmolLM2-135M / SmolLM2-1.7B / Gemma-2-2B / Llama-3-8B / Qwen2.5-1.5B
# ============================================================================

# Web-verified configs (see vocab_rationalization_reference.txt for every URL):
#   - vocab_size, hidden_size, intermediate_size, num_hidden_layers,
#     num_attention_heads, num_key_value_heads, head_dim, tie_word_embeddings
REAL_MODELS = [
    # name,                 V,       H,    I,     L,  heads, kv, head_dim, tied
    ("SmolLM2-135M",      49152,    576,  1536,  30,    9,    3,    64,   True),
    ("SmolLM2-1.7B",      49152,   2048,  8192,  24,   32,   32,    64,   True),
    ("Gemma-2-2B",       256000,   2304,  9216,  26,    8,    4,   256,   True),
    ("Llama-3-8B",       128256,   4096, 14336,  32,   32,    8,   128,   False),
    ("Qwen2.5-1.5B",     151936,   1536,  8960,  28,   12,    2,   128,   True),
]


def section_real_models():
    banner("SECTION B: the real-models table -- the vocab tax across 5 models")
    print("Configs verified from each model's config.json (see _reference.txt).")
    print("Total N is COUNTED from the config (matches each size class exactly).\n")
    print("| model          | V       | H    | tied | embed (V*H)  | total N      | "
          "vocab cost | vocab % |")
    print("|----------------|---------|------|------|--------------|--------------|"
          "------------|---------|")
    rows = []
    for name, V, H, inter, L, nh, nkv, hd, tied in REAL_MODELS:
        p = transformer_params(V, H, inter, L, nh, nkv, hd, tied)
        actual_vocab = p["vocab"]            # embed + (lm_head if untied)
        pct = actual_vocab / p["total"] * 100
        rows.append((name, p, pct))
        print(f"| {name:<14} | {V:>7,} | {H:<4} | {str(tied):<4} | "
              f"{p['embed']:>12,} | {p['total']:>12,} | {actual_vocab:>10,} | "
              f"{pct:>6.1f}% |")
    print()
    print("  read it like this:")
    print("    * Gemma-2-2B (V=256k, TIED): embed alone = 589.8M -> 22.5% of 2.61B.")
    print("      Its vocab table is bigger than ALL of SmolLM2-1.7B. That is the tax.")
    print("    * Llama-3-8B (V=128k, UNTIED): 2 tables = 1.05B -> 13.1% of 8.03B.")
    print("      A big model can afford to UNTIE; an SLM cannot.")
    print("    * SmolLM2-1.7B (V=49k, TIED): embed = 100.7M -> only 5.9% of 1.71B.")
    print("      The 49k vocab is WHY it is a lean SLM, not a vocab-heavy one.\n")
    # determinism: sort to find the min and max vocab% (no dict-order dependence)
    by_pct = sorted(rows, key=lambda r: r[2])
    lo, hi = by_pct[0], by_pct[-1]
    check("max vocab% is Gemma-2-2B", hi[0] == "Gemma-2-2B")
    check("min vocab% is SmolLM2-1.7B", lo[0] == "SmolLM2-1.7B")
    # cross-validate: every computed total lands in its model's size class
    size_band = {
        "SmolLM2-135M":  (1.30e8, 1.40e8),   # ~135M
        "SmolLM2-1.7B":  (1.70e9, 1.72e9),   # ~1.7B
        "Gemma-2-2B":    (2.60e9, 2.62e9),   # ~2.6B
        "Llama-3-8B":    (8.02e9, 8.04e9),   # ~8B
        "Qwen2.5-1.5B":  (1.53e9, 1.55e9),   # ~1.5B
    }
    class_ok = all(lo < p["total"] < hi
                   for name, p, _ in rows
                   for lo, hi in [size_band[name]])
    check("every computed total lands in its model's size class", class_ok)
    return rows


# ============================================================================
# C. THE PARAM-BUDGET PIE -- fixed total N, vary V -> how capacity is reallocated
#    (design exercise: for a nominal 1.5B budget, where does the vocab slice go?)
# ============================================================================

def section_budget_pie(real_rows):
    banner("SECTION C: the param-budget pie -- vocab steals from the body")
    print("Hold the TOTAL budget N fixed and ask: how much goes to vocab vs the")
    print("attention+MLP body (the reasoning core)? Bigger V -> thinner body.\n")

    N, H, L = 1_500_000_000, 2048, 24
    print(f"Fixed nominal budget N = {N:,} ({fmt_m(N)}), H = {H}, L = {L}.\n")
    print("| V        | vocab (tied) | vocab % | body budget  | per-layer budget "
          "| vs V=49k body |")
    print("|----------|--------------|---------|--------------|------------------|"
          "----------------|")
    base_V = 49152
    base_body = N - embed_params(base_V, H)
    for V in [32768, 49152, 65536, 128256, 256000]:
        vocab = embed_params(V, H)                  # tied -> one table
        body = N - vocab
        per_layer = body / L
        print(f"| {V:>8,} | {vocab:>12,} | {vocab / N * 100:>6.1f}%  | "
              f"{body:>12,} | {per_layer:>16,.0f} | {body / base_body:>14.2f}x |")
    print()
    print(f"  * V=49k leaves {base_body:,} ({fmt_m(base_body)}) for the body;")
    print(f"    V=256k leaves only {N - embed_params(256000, H):,} "
          f"({fmt_m(N - embed_params(256000, H))}) -- it EATS ~{fmt_m(embed_params(256000, H) - embed_params(base_V, H))}")
    print("    of capacity (≈6 transformer layers worth of attention+MLP at H=2048).")
    print("  * If the model were UNTIED, double the vocab slice. A 256k untied 1.5B")
    print("    model has NO budget left for a body -- which is why nobody ships that.\n")

    # the untied-absurd check: 2*V*H must stay below N for a body to exist
    check("V=49k tied vocab < N (body exists)",
          embed_params(49152, H) < N)
    check("V=256k UNTIED vocab (2*V*H) eats the MAJORITY of a 1.5B budget",
          2 * embed_params(256000, H) > N / 2)
    # real-model pies (embed vs body vs lm_head) for the .md callout
    print("Real-model pies (embed / body / lm_head slices of N):")
    print("| model          | embed % | body % | lm_head % |")
    print("|----------------|---------|--------|-----------|")
    for name, p, _ in real_rows:
        e = p["embed"] / p["total"] * 100
        b = p["body"] / p["total"] * 100
        lh = p["lm_head"] / p["total"] * 100
        print(f"| {name:<14} | {e:>6.1f}% | {b:>5.1f}% | {lh:>8.1f}% |")
    print()
    check("body is the largest slice in every model",
          all(p["body"] > p["embed"] and p["body"] > p["lm_head"]
              for _, p, _ in real_rows))


# ============================================================================
# D. TOKENS-PER-TEXT THROUGHPUT TRADEOFF  (deterministic illustrative model)
#    Bigger vocab compresses text (fewer tokens) -- but the param tax grows LINEARLY
#    while the compression grows SUBLINEARLY. The curves cross -> a sweet spot.
# ============================================================================

def section_throughput():
    banner("SECTION D: param cost (linear) vs inference compression (sublinear)")
    print("Two forces with vocab size V, for a fixed text corpus:\n")
    print("  (1) PARAM COST:    embed = V*H            -> grows LINEARLY in V.")
    print("  (2) COMPRESSION:   tokens(V) = tokens(V0)*(V0/V)**alpha  (BPE: alpha<1,")
    print("                       sublinear -- bigger vocab packs more chars/token but")
    print("                       with diminishing returns). Inference steps for a fixed")
    print("                       text DROP as tokens drop. Savings = 1 - tokens(V)/V0.\n")
    print("Model (illustrative; alpha = 0.40 is a typical BPE compression exponent):")
    alpha = 0.40
    V0 = 32768                     # baseline small vocab
    H = 2048
    print("| V        | embed params | embed vs V0 | tokens vs V0 | savings/seq | "
          "cost grows faster? |")
    print("|----------|--------------|-------------|--------------|-------------|"
          "---------------------|")
    base_embed = embed_params(V0, H)
    for V in [32768, 49152, 65536, 128256, 256000]:
        emb = embed_params(V, H)
        emb_ratio = emb / base_embed
        tokens_ratio = (V0 / V) ** alpha
        savings = (1 - tokens_ratio) * 100
        faster = "YES (tax > savings)" if emb_ratio > (1 / tokens_ratio) \
            else "no (still worth it)"
        print(f"| {V:>8,} | {emb:>12,} | {emb_ratio:>10.2f}x | "
              f"{tokens_ratio:>12.3f} | {savings:>9.1f}%  | {faster:<19} |")
    print()
    print("  * Param cost scales as V (linear); compression scales as V^(-alpha)")
    print("    (sublinear). So cost outruns compression -- past some point each extra")
    print("    10k tokens of vocab buys less compression than the params it costs.")
    print("  * This is WHY the SLM sweet spot is ~32k-64k: you capture most of the")
    print("    compression of a 128k vocab at a fraction of the param tax.\n")
    # internal-consistency checks on the model (not external facts)
    check("compression is sublinear (tokens drop < linearly as V grows)",
          (V0 / 128256) ** alpha > (V0 / 128256))  # V^-alpha > V^-1 when alpha<1
    check("param cost grows linearly (2x V -> 2x embed)",
          embed_params(2 * V0, H) == 2 * embed_params(V0, H))
    check("alpha in (0,1) so diminishing returns hold", 0 < alpha < 1)


# ============================================================================
# E. THE SLM VOCAB DECISION -- the sweet spot + lineage recap (pinned gold)
# ============================================================================

def section_decision(real_rows):
    banner("SECTION E: the SLM vocab decision -- the ~32k-64k sweet spot")
    print("Rule of thumb (web-verified, see _reference.txt):")
    print("  * 1-3B SLMs (SmolLM2, Qwen2.5-1.5B):  V ~ 49k-152k. SmolLM2 picks 49k")
    print("    deliberately; Qwen2.5 picks 152k because it must cover Chinese+code.")
    print("  * 7B+ models (Llama-3):               V ~ 128k-256k affordable -- the")
    print("    tax is a small % of a big N.\n")
    print("Decision drivers:")
    print("  - multilingual / heavy-code deployment  -> lean BIGGER (more coverage,")
    print("    fewer tokens/text, faster inference per sequence).")
    print("  - single-domain edge SLM (English tool)  -> lean SMALLER (buy back body")
    print("    capacity for attention/MLP). Tie embeddings.  (🔗 SHARED_EMBEDDINGS)\n")

    # the lineage, quantified at H=2048
    print("Lineage quantified (H=2048, tied):")
    print("| era            | model         | V       | embed     | rationale             |")
    print("|----------------|---------------|---------|-----------|-----------------------|")
    lineage = [
        ("big-model era",  "Llama-3-8B",  128256, "525.3M*",  "128k vocab cheap at 8B; untied"),
        ("SLM era",        "SmolLM2-1.7B", 49152, "100.7M",  "smaller vocab frees body capacity"),
    ]
    for era, m, V, emb, why in lineage:
        print(f"| {era:<14} | {m:<13} | {V:>7,} | {emb:>9} | {why:<21} |")
    print("  (*525.3M is one table at H=4096; SmolLM2 row is at H=2048.)\n")
    print("GOLD pinned for vocab_rationalization.html:")
    print(f"    SmolLM2-1.7B embed = 49152 * 2048 = {49152 * 2048:,} "
          f"(~{fmt_m(49152 * 2048)})")
    check("SmolLM2-1.7B embed == 100,663,296", 49152 * 2048 == 100_663_296)
    # the punchline: SmolLM2's vocab slice vs Gemma-2's, same model class
    sm = next(p for n, p, _ in real_rows if n == "SmolLM2-1.7B")
    gem = next(p for n, p, _ in real_rows if n == "Gemma-2-2B")
    print(f"\n  SmolLM2-1.7B vocab slice = {sm['vocab'] / sm['total'] * 100:.1f}% of N")
    print(f"  Gemma-2-2B  vocab slice = {gem['vocab'] / gem['total'] * 100:.1f}% of N")
    check("Gemma-2-2B vocab% > SmolLM2-1.7B vocab%",
          gem["vocab"] / gem["total"] > sm["vocab"] / sm["total"])


# ============================================================================
# main
# ============================================================================

def main():
    print("vocab_rationalization.py - the vocabulary parameter tax.\n"
          "All numbers below feed VOCAB_RATIONALIZATION.md.  torch =", torch.__version__)
    print("\nNOTE: every total N is COUNTED from each model's web-verified config\n"
          "(no marketing numbers, no hand-computed totals). Configs reproduce each\n"
          "model's official size class -- that cross-validates the param counter.")

    section_formula()
    real_rows = section_real_models()
    section_budget_pie(real_rows)
    section_throughput()
    section_decision(real_rows)

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
