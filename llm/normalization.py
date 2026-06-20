"""
normalization.py - Reference implementation of the layer-normalization lineage:
    LayerNorm  ->  RMSNorm

This is the single source of truth that NORMALIZATION.md is built from. Every
number, table, and worked example in NORMALIZATION.md is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python normalization.py

============================================================================
 THE IDEA IN PLAIN ENGLISH (no math background needed)
============================================================================
"Normalizing" a token's feature vector means: make sure no single feature is
too loud. A Transformer stacks ~100 blocks; if the numbers are allowed to grow
or shrink freely across that stack, they explode (-> NaN) or vanish (-> dead
gradients). So once per block we re-pin every token to a known, calm scale.

There are two ways to do it, and they differ in exactly one step:

  * LayerNorm (2016): FIRST center everything to zero (subtract the average),
    THEN scale by how spread-out the numbers are (the standard deviation).
  * RMSNorm (2019):  SKIP the centering. Just scale by how loud the numbers
    are on average (the RMS = "root mean square"). It turns out the centering
    barely matters, so RMSNorm drops it to go faster (7-64% faster, per the
    paper). Llama/Mistral/Qwen/Gemma all use RMSNorm; GPT-2 still uses LayerNorm.

============================================================================
 GLOSSARY (every symbol used below, defined once, in plain words)
============================================================================
  x          the input list of numbers (one token's feature vector, length E)
  E          how many numbers are in x (the "feature" / "embedding" axis = 8 here)
  mean / mu  the average of the numbers in x  =  sum(x) / E
  var        the variance = the average of (each number - mean) squared.
             "how spread-out the numbers are." (BIASED: divide by E, not E-1.)
  std        the standard deviation = sqrt(var). "the typical spread."
  RMS        root-mean-square = sqrt( mean(x^2) ). Think of it as "the loudness":
             the average size of the numbers, ignoring plus/minus signs.
  eps        a tiny safety number (1e-5) added inside the square root so we
             NEVER divide by zero even if all inputs are ~0.
  gamma (g)  a LEARNED "volume knob", one per feature. After we calm the scale,
             gamma lets the model re-emphasize features it likes. Starts at 1.
  beta (b)   a LEARNED "shift knob", one per feature, LayerNorm ONLY. Lets the
             model slide features up/down. RMSNorm has NO beta. Starts at 0.
  dtype      "data type" = how many bits a number is stored in.
  float32    32-bit float: ~7 decimal digits of precision (the "safe" precision).
  bfloat16   "brain float 16-bit": only ~2-3 decimal digits of precision.
             Tiny numbers, squared, can round to ZERO here -> disaster (Section D).

============================================================================
 LINEAGE (old -> new)
============================================================================
    LayerNorm (Ba, Kiros, Hinton 2016, arXiv:1607.06450)
        out = (x - mean) / sqrt(var + eps) * gamma + beta
        - subtract mean AND divide by variance; 2 reduction passes; 2 affine params.
    RMSNorm (Zhang & Sennrich 2019, arXiv:1910.07467, NeurIPS 2019)
        out = (x / sqrt(mean(x^2) + eps)) * gamma
        - DROP mean-centering, divide by RMS only; 1 reduction pass; affine gamma only.
        - Hypothesis of the paper (verified in the abstract, verbatim):
          "re-centering invariance [the mean part] is dispensable; re-scaling
          invariance [the RMS part] is what actually helps."
        - Measured speedup vs LayerNorm: 7%-64% on different models.

WHY the switch happened: RMSNorm is 7-64% faster (paper, NeurIPS 2019) at
comparable accuracy. Llama adopted it; Mistral/Qwen/Gemma followed. nanoGPT/GPT-2
still use LayerNorm.

============================================================================
 TENSOR SHAPES (used throughout)
============================================================================
    B = batch size
    L = sequence length (number of tokens)
    E = embedding / model dim  (the feature axis we normalize over; axis=-1)

So an activation tensor is [B, L, E]. Normalization is ALWAYS over the LAST axis E,
done INDEPENDENTLY for every token (every position in every batch element).
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code NORMALIZATION.md walks)
# ============================================================================

def layernorm_from_scratch(x: torch.Tensor, gamma: torch.Tensor,
                           beta: torch.Tensor, eps: float = 1e-5) -> torch.Tensor:
    """LayerNorm over the last axis, implemented from scratch.

    In plain English (5 steps on one token's feature vector x):
      1. UPCAST x to float32 (so squaring tiny numbers is safe; see Section D).
      2. CENTER:  subtract the average -> the numbers now straddle zero.
      3. SCALE:   divide by the standard deviation -> the spread becomes ~1.
      4. RE-EMPHASIZE: multiply each feature by its learned knob gamma,
                       then shift by its learned knob beta.
      5. CAST back to the original precision.

        out = (x - mean) / sqrt(var + eps) * gamma + beta
        where  mean = x.mean(-1),  var = mean((x - mean)^2)   (BIASED / population)

    Two reduction passes (one for mean, one for var) and two affine params.
    Matches torch.nn.LayerNorm semantics (biased variance).
    """
    orig_dtype = x.dtype
    xf = x.to(torch.float32)                       # upcast for numerical safety
    mean = xf.mean(dim=-1, keepdim=True)           # pass 1
    var = ((xf - mean) ** 2).mean(dim=-1, keepdim=True)  # pass 2 (biased)
    normed = (xf - mean) * torch.rsqrt(var + eps)  # normalize
    out = normed * gamma.to(torch.float32) + beta.to(torch.float32)
    return out.to(orig_dtype)


def rmsnorm_from_scratch(x: torch.Tensor, gamma: torch.Tensor,
                         eps: float = 1e-5) -> torch.Tensor:
    """RMSNorm over the last axis, implemented from scratch.

    In plain English (5 steps on one token's feature vector x):
      1. UPCAST x to float32 (mandatory in bf16/fp16; see Section D).
      2. SQUARE each number, then AVERAGE the squares -> "mean(x^2)".
      3. SQUARE-ROOT that -> the RMS, i.e. "how loud the vector is on average".
      4. DIVIDE every original number by the RMS (and multiply by learned gamma).
         (NO mean subtraction, NO beta.)
      5. CAST back to the original precision.

        out = (x / sqrt(mean(x^2) + eps)) * gamma
        where  mean(x^2) = (x^2).mean(-1)   (NO mean subtraction, NO beta)

    ONE reduction pass and ONE affine param (gamma). The float32 upcast is
    MANDATORY in low precision: bfloat16 has only ~8 mantissa bits, so squaring
    small activations and summing loses precision / underflows to zero, making
    the denominator eps-only and exploding the output. (Section D demonstrates.)
    """
    orig_dtype = x.dtype
    xf = x.to(torch.float32)                       # 1. upcast (mandatory in bf16/fp16)
    ms = xf.pow(2).mean(dim=-1, keepdim=True)      # 2. mean of squares (single pass)
    normed = xf * torch.rsqrt(ms + eps)            # 3. scale by 1/RMS
    out = normed * gamma.to(torch.float32)         # 4. affine gamma (no beta)
    return out.to(orig_dtype)                      # 5. cast back


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def vec_table(name: str, vecs: dict, labels: list[str]) -> str:
    """Print one or more length-E vectors as a markdown table.

    vecs: {column_header: tensor of shape [E]}
    labels: per-element row labels (length E)
    """
    E = len(labels)
    headers = "| field |" + "|".join(f" {k} " for k in vecs) + "|"
    sep = "|---|" + "|".join(["---"] * len(vecs)) + "|"
    lines = [name, "", headers, sep]
    for i in range(E):
        cells = " | ".join(f"{vecs[k][i].item():+.6f}" for k in vecs)
        lines.append(f"| {labels[i]} | {cells} |")
    out = "\n".join(lines)
    print(out)
    print()
    return out


# ============================================================================
# 3. THE SMALL CONCRETE MODEL: E=8, the canonical gold input x=[1..8]
#    Tiny enough to print every number, big enough to show all behavior.
#    Deterministic (hardcoded) so output is reproducible.
# ============================================================================

E = 8
EPS = 1e-5
GOLD_X = torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])
DIM_LABELS = [f"d{i}" for i in range(E)]


def section_layernorm_step_by_step():
    banner("SECTION A: LayerNorm step by step  (mean -> var -> normalize -> affine)")
    x = GOLD_X.clone()
    gamma = torch.ones(E)            # learned scale, init to ones
    beta = torch.zeros(E)            # learned shift, init to zeros
    eps = EPS

    mean = x.mean(dim=-1)                      # STEP (center): the average of x
    var = ((x - mean) ** 2).mean(dim=-1)       # STEP (spread): biased population variance
    std = torch.sqrt(var + eps)                # the standard deviation (eps guards div-by-0)
    centered = x - mean                        # x shifted so it straddles zero
    normed = centered / std                    # now the spread is ~1
    out = normed * gamma + beta                # re-emphasize (gamma) and shift (beta)

    print(f"Input x (E={E}): {[round(v,4) for v in x.tolist()]}")
    print(f"gamma (learned scale) = {[round(v,4) for v in gamma.tolist()]}")
    print(f"beta  (learned shift) = {[round(v,4) for v in beta.tolist()]}")
    print(f"eps = {eps}")
    print()
    print("Two reduction passes:")
    print(f"  pass 1  mean(x)             = {mean.item():.6f}")
    print(f"  pass 2  var = mean((x-mu)^2) = {var.item():.6f}   (BIASED, divides by E not E-1)")
    print(f"          sqrt(var + eps)      = {std.item():.6f}")
    print()
    print("Step-by-step per dimension:")
    vec_table("LayerNorm(x): centered, normalized, + affine -> out",
              {
                  "x": x,
                  "x - mean": centered,
                  "(x-mean)/std": normed,
                  "*gamma+beta": out,
              }, DIM_LABELS)
    print("Two things happened: (1) subtract mean -> centered at 0;")
    print("(2) divide by std -> unit variance. gamma/beta then re-scale/shift.")


def section_rmsnorm_step_by_step():
    banner("SECTION B: RMSNorm step by step  (mean(square) -> RMS -> normalize -> *gamma)")
    x = GOLD_X.clone()
    gamma = torch.ones(E)            # learned scale, init to ones
    eps = EPS

    ms = x.pow(2).mean(dim=-1)            # STEP 1+2: square each number, average the squares
    rms = torch.sqrt(ms + eps)            # STEP 3: square root -> "the loudness" (RMS)
    normed = x / rms                      # STEP 4: divide every original number by the RMS
    out = normed * gamma                  # STEP 5: multiply by the learned knob (NO beta)

    print(f"Input x (E={E}): {[round(v,4) for v in x.tolist()]}")
    print(f"gamma (learned scale) = {[round(v,4) for v in gamma.tolist()]}   (no beta!)")
    print(f"eps = {eps}")
    print()
    print("ONE reduction pass (no mean subtraction):")
    print(f"  mean(x^2) = (1/E) * sum(x_i^2) = {ms.item():.6f}")
    print(f"  RMS = sqrt(mean(x^2) + eps)    = {rms.item():.6f}")
    print(f"  NOTE: mean(x) was {x.mean().item():.6f} but RMSNorm IGNORES it.")
    print()
    print("Step-by-step per dimension:")
    vec_table("RMSNorm(x): x^2, normalize by RMS, * gamma -> out",
              {
                  "x": x,
                  "x^2": x.pow(2),
                  "x/RMS": normed,
                  "*gamma": out,
              }, DIM_LABELS)
    print("One thing happened: divide by RMS -> unit MEAN SQUARE (not unit variance).")
    print("The mean is NOT removed, so the output keeps a constant scale per token.")


def section_side_by_side():
    banner("SECTION C: LayerNorm vs RMSNorm side by side on the SAME input")
    x = GOLD_X.clone()
    gamma = torch.ones(E)
    beta = torch.zeros(E)
    eps = EPS

    ln = layernorm_from_scratch(x, gamma, beta, eps)
    rn = rmsnorm_from_scratch(x, gamma, eps)

    # running stats
    ln_mean = x.float().mean().item()
    ln_var = x.float().var(correction=0).item()   # biased, matches LayerNorm
    rms_ms = x.float().pow(2).mean().item()

    print(f"Same input x = {[round(v,4) for v in x.tolist()]}")
    print()
    print("Running statistics computed on x:")
    print(f"  mean(x)        = {ln_mean:+.6f}     <- LayerNorm uses this (subtract)")
    print(f"  var(x) [biases]= {ln_var:.6f}     <- LayerNorm divides by sqrt(this)")
    print(f"  mean(x^2)      = {rms_ms:.6f}     <- RMSNorm divides by sqrt(this)")
    print()
    print("Outputs (gamma=ones, beta=zeros so this is the raw normalized vector):")
    vec_table("LayerNorm vs RMSNorm output on identical x",
              {
                  "x": x,
                  "LayerNorm": ln,
                  "RMSNorm": rn,
                  "diff (LN-RN)": (ln - rn),
              }, DIM_LABELS)

    print("KEY OBSERVATIONS:")
    print(f"  - LayerNorm output has mean  ~ 0: {ln.mean().item():+.6f}")
    print(f"  - RMSNorm   output has mean  ~ {rn.mean().item():+.6f}  (NOT centered)")
    print(f"  - Both have unit-ish spread, but LN centers at 0; RMSN does not.")
    print(f"  - max|LN - RN| = {(ln - rn).abs().max().item():.6f}  <- a real difference.")
    print()
    print("They are NOT interchangeable: swapping them silently changes every")
    print("activation. Read the checkpoint config (Qwen/Llama = RMSNorm).")


def section_upcast_demonstration():
    banner("SECTION D: float32 upcast is MANDATORY in bfloat16  (why we upcast)")
    print("Problem: bfloat16 has only 8 mantissa bits (vs float32's 23). Squaring")
    print("small values AND summing them loses precision; in the worst case the sum")
    print("of squares underflows to 0, RMS becomes sqrt(eps), and the output EXPLODES.\n")

    # ====================================================================
    # PART 1 — PRECISION LOSS (the everyday case): bf16 rounds the sum of
    # squares, so the scale RMSNorm divides by is measurably wrong.
    # ====================================================================
    print("PART 1: precision loss  (small activations, eps = 1e-5)\n")
    x_vals = [0.001, 0.002, 0.0015, 0.003, 0.0025, 0.0018, 0.0022, 0.0017]
    x_bf16 = torch.tensor(x_vals, dtype=torch.bfloat16)
    x_f32 = x_bf16.to(torch.float32)
    eps = EPS

    # WRONG path: square & mean in bfloat16 directly (no upcast)
    ms_bf16 = x_bf16.pow(2).mean()
    normed_bf16 = x_bf16 / torch.sqrt(ms_bf16 + torch.tensor(eps, dtype=torch.bfloat16))
    # RIGHT path: upcast to float32 FIRST (what rmsnorm_from_scratch does)
    ms_f32 = x_f32.pow(2).mean()
    normed_f32 = x_f32 / torch.sqrt(ms_f32 + eps)

    print(f"Input x (8 small values, stored as bfloat16):")
    print(f"  {[f'{v:.4f}' for v in x_bf16.tolist()]}")
    print(f"mean(x^2) computed each way:")
    print(f"  bfloat16 (no upcast) : {ms_bf16.item():.6e}")
    print(f"  float32  (upcast)    : {ms_f32.item():.6e}")
    print(f"  ratio (bf16 / f32)   : {ms_bf16.float().item() / ms_f32.item():.5f}  <- bf16 over-estimates")
    print()
    diff = (normed_bf16.to(torch.float32) - normed_f32).abs().max().item()
    print(f"max| no-upcast  -  upcast | over the output = {diff:.3e}")
    print(f"bfloat16 out: {[f'{v:.4f}' for v in normed_bf16.tolist()]}")
    print(f"float32  out: {[f'{v:.4f}' for v in normed_f32.tolist()]}")
    print()
    print("The two normalizations DIFFER because bf16's 8 mantissa bits cannot")
    print("hold the sum of squares faithfully. In production (E=4096+) this error")
    print("compounds across the reduction. Upcasting to float32 before squaring is")
    print("cheap insurance and is what every production RMSNorm does.\n")

    # ====================================================================
    # PART 2 — CATASTROPHIC UNDERFLOW (the motivation): values so small that
    # bf16 sum-of-squares rounds to EXACTLY 0. Drop eps to 0 and you get NaN;
    # the upcast path keeps the (tiny but nonzero) sum and stays finite.
    # ====================================================================
    print("PART 2: catastrophic underflow  (tiny activations, eps = 0)\n")
    tiny_vals = [i * 1e-22 for i in range(1, 9)]
    xb = torch.tensor(tiny_vals, dtype=torch.bfloat16)
    xf = xb.to(torch.float32)

    ms_bf16_0 = xb.pow(2).mean()        # in bf16
    ms_f32_0 = xf.pow(2).mean()         # in f32

    print(f"Input x (8 tiny values, stored as bfloat16):")
    print(f"  {[f'{v:.2e}' for v in xb.tolist()]}")
    print(f"mean(x^2) with eps = 0:")
    print(f"  bfloat16 (no upcast) : {ms_bf16_0.item():.3e}   <- rounds to EXACTLY 0")
    print(f"  float32  (upcast)    : {ms_f32_0.item():.3e}   <- tiny but nonzero")
    print()
    # divide: bf16 hits 0/0 -> NaN; f32 stays finite
    out_bf16_0 = xb / torch.sqrt(ms_bf16_0)          # sqrt(0)=0 -> 0/0
    out_f32_0 = xf / torch.sqrt(ms_f32_0)
    has_bad = bool(torch.isnan(out_bf16_0).any() or torch.isinf(out_bf16_0).any())
    print(f"x / sqrt(mean(x^2))  with eps = 0:")
    print(f"  bfloat16 (no upcast) : contains NaN/inf? {has_bad}   <- DEAD")
    print(f"  float32  (upcast)    : max |out| = {out_f32_0.abs().max().item():.4f}  (finite, correct)")
    print()
    print("Without the upcast, the bf16 sum of squares underflows to 0 and (with")
    print("eps=0) the division blows up to NaN. Adding eps=1e-5 prevents the NaN")
    print("but still yields a WRONG scale whenever the true mean-square is below")
    print("eps. Upcasting to float32 before squaring is the robust fix: it preserves")
    print("the true (tiny) mean-square so the division stays well-conditioned.")
    print()
    print("This is why every production RMSNorm (LLaMA, Qwen, Mistral, Gemma) upcasts")
    print("x to float32 before squaring, then casts back. See rmsnorm_from_scratch.")


def section_gold_value_and_reference_check():
    banner("SECTION E: gold value + assert from-scratch == torch reference")
    x = GOLD_X.clone()
    gamma = torch.ones(E)
    beta = torch.zeros(E)
    eps = EPS

    # --- THE GOLD VALUE: RMSNorm of x=[1..8], eps=1e-5, gamma=ones ---
    gold = rmsnorm_from_scratch(x, gamma, eps)
    print("THE GOLD VALUE  (pinned into normalization.html for the JS gold-check):")
    print(f"  RMSNorm(x=[1..8], eps={eps}, gamma=ones) =")
    print(f"  {[round(v,6) for v in gold.tolist()]}")
    print()
    # also print the bare scalars the HTML will recompute to match
    ms = x.pow(2).mean().item()
    rms = (ms + eps) ** 0.5
    print(f"  mean(x^2) = {ms:.6f}    RMS = sqrt(mean(x^2)+eps) = {rms:.6f}")
    print(f"  (HTML JS recomputes 1/RMS = {1/rms:.6f}  and multiplies each x[i].)")
    print()

    # --- assert from-scratch RMSNorm matches the manual formula ---
    manual = x * (1.0 / rms)
    assert torch.allclose(gold, manual, atol=1e-6), "from-scratch RMSNorm != manual"
    print("[check] from-scratch RMSNorm == manual  x * (1/RMS):  OK")

    # --- assert from-scratch RMSNorm matches torch's rsqrt path ---
    ref_rn = x * torch.rsqrt(torch.tensor(ms + eps))
    assert torch.allclose(gold, ref_rn, atol=1e-6)
    print("[check] from-scratch RMSNorm == x * rsqrt(mean(x^2)+eps):  OK")
    print()

    # --- assert from-scratch LayerNorm matches torch.nn.LayerNorm ---
    ln = layernorm_from_scratch(x, gamma, beta, eps)
    ref_ln = torch.nn.LayerNorm(E, eps=eps)(x)   # torch reference (gamma=ones, beta=zeros default)
    assert torch.allclose(ln, ref_ln, atol=1e-6), "from-scratch LayerNorm != torch.nn.LayerNorm"
    print("[check] from-scratch LayerNorm == torch.nn.LayerNorm:  OK")

    # --- assert from-scratch LayerNorm matches F.layer_norm ---
    ref_fl = torch.nn.functional.layer_norm(x, (E,), gamma, beta, eps)
    assert torch.allclose(ln, ref_fl, atol=1e-6)
    print("[check] from-scratch LayerNorm == F.layer_norm:  OK")
    print()
    print("Both from-scratch implementations agree with torch's references bit-for-bit")
    print("(within float32 tolerance). The formulas in this file ARE the definitions.")


def section_full_batch():
    banner("SECTION F: full batch  B=1, L=4, E=8  (a real forward call)")
    B, L, EE = 1, 4, E
    # deterministic tiny content so every number is traceable
    x = torch.zeros(B, L, EE)
    for b in range(B):
        for pos in range(L):
            for d in range(EE):
                x[b, pos, d] = round(0.1 * (pos + 1) + 0.01 * (d + 1), 4)
    print(f"Input shape: {tuple(x.shape)} = [B={B}, L={L}, E={EE}]")
    print("Normalization is over the LAST axis (E=8), independently per token.\n")
    print("Input x[b=0] (L rows x E cols):")
    for pos in range(L):
        print(f"  m={pos}: {[round(v,4) for v in x[0,pos].tolist()]}")
    print()

    gamma = torch.ones(EE)
    eps = EPS
    y = rmsnorm_from_scratch(x, gamma, eps)
    print("Output RMSNorm(x) x[b=0] (each row normalized to unit mean-square):")
    for pos in range(L):
        print(f"  m={pos}: {[round(v,4) for v in y[0,pos].tolist()]}")
    print()
    # RMS per token before/after
    rms_in = x.pow(2).mean(dim=-1).sqrt()
    rms_out = y.pow(2).mean(dim=-1).sqrt()
    print(f"[check] RMS per token BEFORE: {[round(v,4) for v in rms_in[0].tolist()]}")
    print(f"[check] RMS per token AFTER : {[round(v,4) for v in rms_out[0].tolist()]}")
    print("        (after ~= 1.0 for every token -> RMSNorm did its job)")


def section_lineage():
    banner("SECTION G: the lineage  LayerNorm -> RMSNorm  (why each step)")
    print("""
LayerNorm   Ba, Kiros, Hinton 2016  (arXiv:1607.06450)
    out = (x - mean) / sqrt(var + eps) * gamma + beta
    - 2 reduction passes (mean, then var)
    - 2 affine params per feature (gamma, beta)
    - gives re-centering AND re-scaling invariance
    - GPT-2 / nanoGPT / original Transformer use this

        |
        |  Zhang & Sennrich (2019) hypothesized:
        |  "re-centering invariance is dispensable;
        |   re-scaling invariance is what actually helps."
        |  -> drop the mean subtraction, keep only the RMS scaling.
        v

RMSNorm     Zhang & Sennrich 2019  (arXiv:1910.07467, NeurIPS 2019)
    out = (x / sqrt(mean(x^2) + eps)) * gamma
    - 1 reduction pass (mean of squares only)
    - 1 affine param per feature (gamma; NO beta)
    - gives re-scaling invariance only
    - 7%-64% faster than LayerNorm at comparable accuracy (the paper)
    - LLaMA / Mistral / Qwen / Gemma / Falcon all use this

MANDATORY in both: float32 upcast of x before squaring when running in
bfloat16/fp16 (else sum-of-squares underflows -> NaN). See Section D.
""")


# ============================================================================
# main
# ============================================================================

def main():
    print("normalization.py - reference implementation. All numbers below feed")
    print("NORMALIZATION.md.")
    print("torch =", torch.__version__)
    print("Lineage: LayerNorm (2016) -> RMSNorm (2019)")

    section_layernorm_step_by_step()
    section_rmsnorm_step_by_step()
    section_side_by_side()
    section_upcast_demonstration()
    section_gold_value_and_reference_check()
    section_full_batch()
    section_lineage()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
