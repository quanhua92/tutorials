"""
shared_embeddings.py - Reference implementation of WEIGHT TYING (shared input
embedding + output LM-head projection) for Small Language Models.

This is the single source of truth that SHARED_EMBEDDINGS.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python shared_embeddings.py

== The big idea, in one sentence (the "two hats" intuition) =================
A Transformer reads tokens IN through an embedding table (token id -> vector)
and writes tokens OUT through a projection (vector -> vocab logits). These are
two different jobs, but the table for both has the SAME shape [V, H] (V vocab
rows, H hidden cols). So instead of learning TWO separate [V, H] matrices, we
let ONE matrix wear BOTH hats: the input-lookup table IS the output-projection
matrix (transposed). That single re-binding -- `lm_head.weight = embed.weight`
in torch -- recovers an entire V*H parameter block, which for a 1.5B-scale SLM
is ~100M parameters for free.

== Plain-English glossary (used in every section below) =====================
    V (vocab)    vocabulary size -- how many distinct tokens the model knows.
                 SmolLM2 = 49152, Llama-3 = 128256, Gemma-2 = 256000.
    H (hidden)   hidden dimension -- width of one token's vector. The embedding
                 table is V rows (one per token) by H cols (the vector).
    embed        nn.Embedding(V, H): the INPUT lookup. embed.weight is [V, H].
                 Row i of this table IS token i's input vector.
    lm_head      nn.Linear(H, V, bias=False): the OUTPUT projection. Its weight
                 is stored as [V, H] (out_features, in_features). A token vector
                 x [H] is projected to logits = lm_head.weight @ x -> [V].
    tying        binding the two matrices to the SAME tensor object in memory:
                 `lm_head.weight = embed.weight`. After this, the python `is`
                 test is True -- they are ONE object with two names.
    untied       the opposite: embed.weight and lm_head.weight are two INDEPENDENT
                 [V, H] tensors, learned separately (2*V*H params for the vocab).
    input path   the forward flow token id -> embed lookup -> hidden state.
                 Its gradient flows back INTO embed.weight.
    output path  the forward flow hidden state -> lm_head projection -> logits.
                 Its gradient flows back INTO lm_head.weight.
    shared grad  when TIED, embed.weight.grad gets contributions from BOTH paths
                 simultaneously (input lookup + output projection). This is the
                 gradient-dynamics trade-off the lineage section discusses.

== The lineage (old -> new, with WHY) =========================================
  UNTIED    : embed [V,H]  +  lm_head [V,H]   =  2*V*H params for the vocab.
              Two separate matrices, learned independently. The original
              Transformer (Vaswani 2017) and most LARGE modern models
              (Llama-3-8B, Nemotron, etc.) keep them untied, because at scale the
              parameter budget permits it and the gradient on each matrix is
              "clean" (only one job each) -> better perplexity at 7B+.
  TIED      : lm_head.weight = embed.weight    =  V*H params for the vocab.
              ONE matrix wears both hats. Saves V*H params. Press & Wolf (2017,
              arXiv:1608.05859) and Inan et al (ICLR 2017, arXiv:1611.01462)
              showed tying IMPROVES perplexity (not just saves params) for small
              models. GPT-2, nanoGPT, Pythia, SmolLM2, Gemma-2 all tie. The
              shared weight receives gradient from BOTH the input path and the
              output path, which can need a small LR retune and -- per recent
              work -- can underperform untied at very large scale.

== Tensor-shape conventions (used throughout) ================================
    V = vocab size
    H = hidden dimension
    L = sequence length (number of tokens in the tiny example)

    embed.weight  : [V, H]    (row i = token i's input vector)
    lm_head.weight: [V, H]    (stored as [out_features V, in_features H]; the
                               output projection is logits = W @ x, x is [H])
    token ids     : [L]       (integers in [0, V))
    hidden states : [L, H]    (after the embedding lookup)
    logits        : [L, V]    (after the lm_head projection)

NOTE on torch internals: nn.Linear stores weight as [out_features, in_features],
so nn.Linear(H, V).weight has shape [V, H] -- EXACTLY the same shape as
nn.Embedding(V, H).weight. That shape match is WHY a simple attribute rebind
(`lm_head.weight = embed.weight`) is all the tying ever needs: no copy, no
transpose, the two layers literally share one tensor.
"""

from __future__ import annotations

import torch
import torch.nn as nn

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ----------------------------------------------------------------------------
# PRETTY PRINTERS + the check() helper (no raw assert -- it's compiled out under -O)
# ----------------------------------------------------------------------------

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(desc: str, ok: bool):
    """Print '[check] desc: OK' and exit non-zero on failure (cf. raw assert)."""
    status = "OK" if ok else "FAIL"
    print(f"[check] {desc}: {status}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def fmt(n: int) -> str:
    """Group an integer with commas, e.g. 100663296 -> '100,663,296'."""
    return f"{n:,}"


# ============================================================================
# SECTION A: tied vs untied parameter counts (the structural math)
# ============================================================================

def section_param_counts():
    banner("SECTION A: tied vs untied parameter counts (the structural math)")
    print("Vocabulary params live in two [V, H] matrices:\n"
          "  embed_tokens.weight : [V, H]   (input lookup)\n"
          "  lm_head.weight      : [V, H]   (output projection)\n")
    print("UNTIED: both matrices are independent   -> 2*V*H params\n"
          "TIED  : one matrix wears both hats      ->   V*H params\n"
          "savings = V*H (an entire matrix is recovered)\n")

    cases = [
        ("tiny worked example", 8, 4),
        ("SmolLM2-1.7B", 49152, 2048),
        ("Llama-3-8B", 128256, 4096),
        ("Gemma-2-2B", 256000, 2304),
    ]
    print("| model                | V        | H    | untied 2*V*H | tied V*H  | "
          "savings V*H | savings % |")
    print("|----------------------|----------|------|--------------|-----------|"
          "-------------|-----------|")
    for name, V, H in cases:
        untied = 2 * V * H
        tied = V * H
        savings = tied  # == untied - tied
        pct = 100.0 * savings / untied
        print(f"| {name:<20} | {V:>8} | {H:>4} | {fmt(untied):>12} | "
              f"{fmt(tied):>9} | {fmt(savings):>11} | {pct:>8.2f}% |")
    print()
    print("Every row saves EXACTLY 50% of the vocabulary parameters, because")
    print("tying halves the count (2*V*H -> V*H). The ABSOLUTE savings grow")
    print("with V*H: a tiny 8x4 model saves 32 params; SmolLM2 saves 100,663,296.")
    print()

    # gold anchor pinned for the .html check
    V_smol, H_smol = 49152, 2048
    gold_savings_smol = V_smol * H_smol
    print("GOLD PIN (shared_embeddings.html recomputes this):")
    print(f"    SmolLM2 savings = V*H = {V_smol}*{H_smol} = {gold_savings_smol}")
    check("SmolLM2 tying savings == 100,663,296",
          gold_savings_smol == 100_663_296)

    # tiny worked example gold
    check("tiny V=8,H=4: untied 64, tied 32, savings 32",
          2 * 8 * 4 == 64 and 8 * 4 == 32 and (2 * 8 * 4 - 8 * 4) == 32)
    check("tying always saves exactly 50% of vocab params",
          all((2 * V * H - V * H) * 2 == 2 * V * H for _, V, H in cases))


# ============================================================================
# SECTION B: the torch implementation (build, tie, assert identity)
# ============================================================================

def build_tied_model(V: int, H: int, seed: int = 0):
    """Build a minimal embed + lm_head model with WEIGHT TYING.

    Returns (embed, lm_head) where lm_head.weight IS embed.weight (same object).
    The tying line is `lm_head.weight = embed.weight` -- a plain attribute
    rebind that makes the two Parameter objects point at one tensor.
    """
    torch.manual_seed(seed)
    embed = nn.Embedding(V, H)
    lm_head = nn.Linear(H, V, bias=False)
    # THE TYING LINE: rebind the output projection's weight to the input table.
    lm_head.weight = embed.weight
    return embed, lm_head


def build_untied_model(V: int, H: int, seed: int = 0):
    """Same two layers, but kept INDEPENDENT (2*V*H params)."""
    torch.manual_seed(seed)
    embed = nn.Embedding(V, H)
    lm_head = nn.Linear(H, V, bias=False)
    return embed, lm_head


def count_vocab_params(embed: nn.Embedding, lm_head: nn.Linear) -> int:
    """Unique params across embed + lm_head (accounts for sharing).

    Tied: embed.weight and lm_head.weight are the SAME object, so we count it
    once. Untied: two distinct objects, count both.
    """
    seen = set()
    total = 0
    for p in (embed.weight, lm_head.weight):
        if id(p) not in seen:
            seen.add(id(p))
            total += p.numel()
    return total


def section_torch_implementation():
    banner("SECTION B: the torch implementation (build, tie, assert identity)")
    V, H = 8, 4
    print(f"Tiny model: V={V}, H={H}\n")

    # --- UNTIED: two independent [V, H] matrices ---
    embed_u, head_u = build_untied_model(V, H, seed=0)
    untied_params = count_vocab_params(embed_u, head_u)
    print("UNTIED model:")
    print(f"  embed.weight.shape = {tuple(embed_u.weight.shape)}")
    print(f"  lm_head.weight.shape = {tuple(head_u.weight.shape)}")
    print(f"  embed.weight is lm_head.weight? {embed_u.weight is head_u.weight}")
    print(f"  unique vocab params = {untied_params}  (= 2*V*H = {2 * V * H})\n")

    # --- TIED: one [V, H] matrix wearing both hats ---
    embed_t, head_t = build_tied_model(V, H, seed=0)
    tied_params = count_vocab_params(embed_t, head_t)
    print("TIED model  (after the line: lm_head.weight = embed.weight):")
    print(f"  embed.weight.shape = {tuple(embed_t.weight.shape)}")
    print(f"  lm_head.weight.shape = {tuple(head_t.weight.shape)}")
    print(f"  embed.weight is lm_head.weight? {embed_t.weight is head_t.weight}")
    print(f"  unique vocab params = {tied_params}  (= V*H = {V * H})\n")

    print("The `is` identity is the WHOLE tying mechanism: one tensor object,")
    print("two layer attributes. No copy, no transpose -- nn.Linear(H, V) stores")
    print("its weight as [V, H] (out_features, in_features), which is EXACTLY")
    print("nn.Embedding(V, H).weight's shape. That shape match is why a plain")
    print("attribute rebind is sufficient.\n")

    # --- the GOLD structural checks ---
    check("untied: embed.weight is NOT lm_head.weight",
          embed_u.weight is not head_u.weight)
    check("tied: embed.weight IS lm_head.weight (same object)",
          embed_t.weight is head_t.weight)
    check("tied unique params (32) == half of untied (64)",
          tied_params * 2 == untied_params)
    check("tied unique params == V*H == 32", tied_params == V * H)

    # --- mutating the shared tensor through EITHER name updates BOTH ---
    embed_t.weight.data.zero_()
    check("zeroing via embed.weight also zeroes lm_head.weight (shared object)",
          head_t.weight.abs().sum().item() == 0.0)

    # rebuild after the zero-out so later sections start fresh
    return build_tied_model(V, H, seed=0)


# ============================================================================
# SECTION C: gradient flow -- the shared weight accumulates BOTH paths
# ============================================================================

def section_gradient_flow():
    banner("SECTION C: gradient flow -- the shared weight accumulates BOTH paths")
    V, H, L = 8, 4, 3
    embed, lm_head = build_tied_model(V, H, seed=0)
    print(f"Tiny tied model: V={V}, H={H}, L={L} (sequence of {L} tokens)\n")

    # deterministic input token ids and a deterministic target token id per step
    token_ids = torch.tensor([1, 3, 6])
    targets = torch.tensor([2, 5, 7])

    # --- forward: input path (embed lookup) -> output path (lm_head projection) ---
    hidden = embed(token_ids)              # [L, H]   INPUT PATH  (lookup)
    logits = lm_head(hidden)               # [L, V]   OUTPUT PATH (projection)
    loss = nn.functional.cross_entropy(logits, targets)
    print(f"token_ids  = {token_ids.tolist()}")
    print(f"targets    = {targets.tolist()}")
    print(f"hidden = embed(token_ids)   shape {tuple(hidden.shape)}  "
          f"(INPUT path)")
    print(f"logits = lm_head(hidden)    shape {tuple(logits.shape)}  "
          f"(OUTPUT path)")
    print(f"cross_entropy loss = {loss.item():.4f}\n")

    # --- backward: gradient lands on the SINGLE shared weight ---
    loss.backward()
    shared_grad = embed.weight.grad        # SAME object as lm_head.weight.grad
    print("After loss.backward(), the shared weight's gradient has shape "
          f"{tuple(shared_grad.shape)} and\n"
          f"norm {shared_grad.norm().item():.4f}.\n")

    # --- PROVE the shared grad == input-path grad + output-path grad ---
    # Re-run forward+backward on an UNTIED model with the SAME init values, but
    # split into two independent matrices: one acting as input lookup, one as
    # output projection. Then sum their grads and compare to the tied grad.
    torch.manual_seed(0)                   # same init as the tied build
    embed_in = nn.Embedding(V, H)
    head_out = nn.Linear(H, V, bias=False)
    # give head_out the SAME starting numbers as embed so the forward is identical
    head_out.weight.data.copy_(embed_in.weight.data)
    hidden2 = embed_in(token_ids)
    logits2 = head_out(hidden2)
    loss2 = nn.functional.cross_entropy(logits2, targets)
    loss2.backward()
    grad_input_path = embed_in.weight.grad.clone()    # from the INPUT lookup only
    grad_output_path = head_out.weight.grad.clone()   # from the OUTPUT projection only
    summed = grad_input_path + grad_output_path

    print("Proof that the tied grad == (input-path grad) + (output-path grad):")
    print("  built an UNTIED pair with the SAME init, ran the SAME forward+backward,")
    print("  and summed the two independent gradients.\n")
    print(f"  ||grad on tied shared weight||            = {shared_grad.norm().item():.4f}")
    print(f"  ||grad on untied embed (input path)||     = {grad_input_path.norm().item():.4f}")
    print(f"  ||grad on untied lm_head (output path)||  = {grad_output_path.norm().item():.4f}")
    print(f"  ||input_path + output_path||              = {summed.norm().item():.4f}")
    max_diff = (shared_grad - summed).abs().max().item()
    print(f"  max|tied_grad - (input + output)|         = {max_diff:.3e}\n")

    print("Reading: the output-path gradient dominates here (its norm is larger),")
    print("but BOTH paths contribute. In the tied model the single .grad tensor is")
    print("their SUM. An optimizer step therefore moves the shared weight to satisfy")
    print("both jobs at once -- the gradient-dynamics trade-off of tying.\n")

    check("tied weight.grad IS lm_head.weight.grad (same .grad object)",
          embed.weight.grad is lm_head.weight.grad)
    check("tied grad == input-path grad + output-path grad (sum matches)",
          torch.allclose(shared_grad, summed, atol=1e-6))
    check("the output path contributes a non-trivial gradient",
          grad_output_path.norm().item() > 1e-6)
    check("the input path contributes a non-trivial gradient",
          grad_input_path.norm().item() > 1e-6)


# ============================================================================
# SECTION D: forward output is IDENTICAL tied vs untied (tying is structural)
# ============================================================================

def section_forward_identical():
    banner("SECTION D: forward output is IDENTICAL tied vs untied (structural only)")
    V, H = 8, 4
    token_ids = torch.tensor([0, 4, 7])
    torch.manual_seed(0)
    # one untied model, then we tie it AFTER seeing it works
    embed = nn.Embedding(V, H)
    lm_head = nn.Linear(H, V, bias=False)
    lm_head.weight.data.copy_(embed.weight.data)   # equal values, distinct objects

    # UNTIED forward (two distinct matrices with EQUAL values)
    hidden_u = embed(token_ids)
    logits_u = lm_head(hidden_u)

    # TIE the weights and forward again -- forward must be bit-identical
    lm_head.weight = embed.weight
    hidden_t = embed(token_ids)
    logits_t = lm_head(hidden_t)

    max_diff = (logits_u - logits_t).abs().max().item()
    print(f"token_ids = {token_ids.tolist()}\n")
    print("Untied forward: embed & lm_head are distinct objects with EQUAL values.")
    print("Tied forward  : lm_head.weight = embed.weight (rebind), same values.\n")
    print(f"logits untied (row 0) = {[round(v, 4) for v in logits_u[0].tolist()]}")
    print(f"logits tied   (row 0) = {[round(v, 4) for v in logits_t[0].tolist()]}")
    print(f"\nmax|logits_untied - logits_tied| = {max_diff:.3e}\n")
    print("Conclusion: tying is PURELY structural. As long as the two matrices")
    print("hold equal values, the forward output is bit-identical. Tying only")
    print("CONSTRAINS them to stay equal during training (a single optimizer step")
    print("updates the shared tensor once, from the summed gradient).\n")

    check("tied forward == untied forward (equal values)",
          torch.allclose(logits_u, logits_t, atol=1e-6))
    check("max|untied - tied logits| < 1e-6", max_diff < 1e-6)


# ============================================================================
# SECTION E: real-model savings table (who ties in practice?)
# ============================================================================

def section_real_models():
    banner("SECTION E: real-model savings table (who ties in practice?)")
    # (model, V, H, ties_in_practice, source_note)
    # Verified via each model's HuggingFace config.json on the web.
    models = [
        ("SmolLM2-1.7B",  49152,  2048, True,
         "tie_word_embeddings=true (HuggingFace config.json)"),
        ("Llama-3-8B",    128256, 4096, False,
         "tie_word_embeddings=false (UNTIED -- large model)"),
        ("Gemma-2-2B",    256000, 2304, True,
         "tie_word_embeddings=true (Gemma ties by design)"),
        ("GPT-2 / nanoGPT", 50257, 768, True,
         "lm_head.weight = wte.weight (karpathy/nanoGPT)"),
    ]
    print("For each model: the vocab param block size, the savings if tying is")
    print("used (V*H), and whether the model ACTUALLY ties in its released config.\n")
    print("| model           | V       | H    | untied 2*V*H | tied V*H  | "
          "ties? | note                                  |")
    print("|-----------------|---------|------|--------------|-----------|"
          "-------|---------------------------------------|")
    for name, V, H, ties, note in models:
        untied = 2 * V * H
        tied = V * H
        flag = "yes" if ties else "NO"
        print(f"| {name:<15} | {V:>7} | {H:>4} | {fmt(untied):>12} | "
              f"{fmt(tied):>9} | {flag:<5} | {note:<37} |")
    print()
    print("Read the table: SmolLM2-1.7B TIES and saves 100,663,296 params (one")
    print("entire [49152, 2048] matrix). Gemma-2-2B ties and saves 589,824,000.")
    print("Llama-3-8B does NOT tie -- at 8B scale the parameter budget permits")
    print("two independent matrices, and the cleaner per-path gradient (each")
    print("matrix serves only one job) wins on perplexity. This is the")
    print("tying-vs-untying trade-off in one table.\n")

    smol = next(m for m in models if m[0] == "SmolLM2-1.7B")
    gemma = next(m for m in models if m[0] == "Gemma-2-2B")
    llama = next(m for m in models if m[0] == "Llama-3-8B")
    check("SmolLM2 savings V*H == 100,663,296",
          smol[1] * smol[2] == 100_663_296)
    check("Gemma-2-2B savings V*H == 589,824,000",
          gemma[1] * gemma[2] == 589_824_000)
    check("Llama-3-8B ties in practice? False",
          llama[3] is False)
    check("GPT-2/nanoGPT ties in practice? True",
          next(m for m in models if m[0] == "GPT-2 / nanoGPT")[3] is True)


# ============================================================================
# SECTION F: lineage recap (old -> new, the per-model decision)
# ============================================================================

def section_lineage_recap():
    banner("SECTION F: lineage recap + when to tie vs untie")
    print("The decision, as a function of model scale:\n")
    print("| regime            | recommendation | reason                                |")
    print("|-------------------|----------------|---------------------------------------|")
    rows = [
        ("< 1B params (SLM)", "TIE",
         "V*H savings matter; tying also regularizes (Press & Wolf: improves PPL)"),
        ("1B - 7B",          "usually TIE",
         "Gemma-2-2B ties; SmolLM2-1.7B ties; the savings still buy capacity"),
        (">= 7B",            "often UNTIE",
         "Llama-3-8B unties; budget permits 2 matrices, cleaner gradient wins"),
    ]
    for regime, rec, reason in rows:
        print(f"| {regime:<17} | {rec:<14} | {reason:<37} |")
    print()
    print("The crossover is empirical, not a hard threshold. Recent work finds the")
    print("shared weight's gradient is the SUM of two jobs (input lookup + output")
    print("projection), which biases the tied embeddings toward the output space")
    print("and can hurt perplexity once the parameter budget is large enough to")
    print("afford two separate matrices. For an SLM, tying is the default: it is")
    print("free capacity AND a (small) perplexity win.\n")
    check("SLM regime (<1B) recommendation starts with TIE", rows[0][1] == "TIE")
    check("large regime (>=7B) recommends UNTIE", "UNTIE" in rows[2][1])


# ============================================================================
# main
# ============================================================================

def main():
    print("shared_embeddings.py - reference impl (weight tying for SLMs).\n"
          "Numbers below feed SHARED_EMBEDDINGS.md.  torch =", torch.__version__)
    print("\nConcept: re-bind lm_head.weight = embed.weight so ONE [V, H] matrix\n"
          "wears both the input-lookup hat and the output-projection hat,\n"
          "recovering V*H params (~100M for SmolLM2-1.7B).\n")

    section_param_counts()
    section_torch_implementation()
    section_gradient_flow()
    section_forward_identical()
    section_real_models()
    section_lineage_recap()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
