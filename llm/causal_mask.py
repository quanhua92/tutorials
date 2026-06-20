"""
causal_mask.py - Reference implementation of the THREE intertwined attention
mechanics that make a causal LM actually causal AND trainable.

================================================================
  INTUITION FIRST  (read this before the code)
================================================================
Think of a language model as a reader moving through a sentence one token at a
time, where each token is allowed to look back at the notes (tokens) written
*before* it, but never at notes written *after* it.

  (1) CAUSAL MASK  -- "the bouncer."
      The mask is a bouncer at the door between tokens. It lets a token read any
      note written before it, and blocks any note written after it by stamping
      that note's score as -inf. After softmax, exp(-inf) = 0, so a blocked note
      gets EXACTLY 0% probability -- it cannot influence the answer at all.

  (2) k=(S-L) OFFSET  -- "shifting the past/future line."
      During generation the model emits ONE new token at a time (decode), but
      the whole history of old notes is still on file. The bouncer's "past vs
      future" line must shift to the real history length. Without the shift the
      lone new token either sees nothing (cut off) or hallucinates the future.
      The shift is k = S - L: 0 in prefill (L=S), N-1 in decode (L=1, S=N).

  (3) QK-NORM (Qwen3)  -- "quiet re-scaling before the comparison."
      Before comparing queries and keys we quietly re-scale each one so their
      dot products don't blow up into huge, unstable numbers. Big logits make
      softmax collapse to a single 1.0 (one-hot), gradients vanish, training
      stalls. QK-Norm pins each vector's size so logits stay small and softmax
      stays well-behaved.

  SHAPE CHOREOGRAPHY  -- "rotate first, rearrange second."
      Data lives in a box labelled [batch, position, head, feature]. Position
      must be the 'position' axis when we rotate (RoPE); then we rearrange the
      box so 'head' is upfront for the comparison math. Rotate first (still
      [B,L,H,D]), rearrange second (transpose to [B,H,L,D]).

================================================================
  GLOSSARY  (plain-English, in order of first use)
================================================================
  attention   : how a token decides which other tokens matter to it -- score
                each, then take a weighted average.
  query (Q)   : the "question" vector of a token -- what it is looking for.
  key (K)     : the "label" vector of a token -- how it can be found.
  softmax     : turns a list of raw scores into probabilities that sum to 1.
  -inf        : the mask value; exp(-inf) = 0 -> that position gets 0% prob.
  causal      : "cause before effect" -- token i may read only tokens 0..i.
  prefill     : the first pass over the whole prompt (many tokens at once).
  decode      : generating one new token per step after prefill (1 at a time).
  L           : query length = how many NEW tokens this pass asks about.
  S           : key length = how many tokens are in the key store (the history).
  diagonal /  : a grid where cell (l,s) is "open" if s<=l (on/below the diag)
  triangular     and "blocked" otherwise; the bouncer's allow/deny map.
                mask   : QK-Norm = an extra RMSNorm on Q and K before the dot
  QK-Norm       product, so logits stay bounded and softmax stays alive.
  transpose / : rearranging the axes of a multi-dim array without changing the
  reshape       data, so the right axis lines up for the math.

This file is the single source of truth that CAUSAL_MASK.md is built from.
Every number, table, and worked example below is PRINTED by this file -- if you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python causal_mask.py

Conventions for tensor shapes (used throughout):
    B = batch size
    L = query length      (number of NEW tokens this forward)
    S = key/value length  (full sequence length in the KV cache)
    H = number of heads
    D = head dimension

A query tensor after the attention-transpose is [B, H, L, D]; a key/value
tensor is [B, H, S, D]. The mask is [L, S] and broadcasts over B and H.
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (the code CAUSAL_MASK.md walks through)
# ============================================================================

def causal_mask(L: int, S: int, dtype: torch.dtype) -> torch.Tensor:
    """Lower-triangular additive mask of shape [L, S].

    0 where the query is ALLOWED to attend, -inf where it is MASKED.

    The single k=(S-L) diagonal argument is the whole trick:
        prefill:  L == S  -> k = 0          -> standard lower-triangle
        decode:   L == 1, S == N -> k = N-1 -> one row, all allowed
    """
    ones = torch.ones((L, S), dtype=dtype)
    tri = torch.tril(ones, diagonal=(S - L))          # 1 = allow, 0 = mask
    mask = torch.where(tri > 0,
                       torch.tensor(0.0, dtype=dtype),
                       torch.tensor(float("-inf"), dtype=dtype))
    return mask                                          # [L, S]


def scaled_dot_product_attention(query: torch.Tensor,
                                 key: torch.Tensor,
                                 value: torch.Tensor,
                                 scale: float | None = None,
                                 mask: torch.Tensor | None = None
                                 ) -> torch.Tensor:
    """Plain MHA scaled-dot-product attention.

    Shapes: query [B,H,L,D], key/value [B,H,S,D]. Returns [B,H,L,D].

        scores = (Q @ K^T) * scale          # [B,H,L,S]
        scores = scores + mask              # add -inf at future positions
        probs  = softmax(scores, dim=-1)
        out    = probs @ V                  # [B,H,L,D]
    """
    D = query.shape[-1]
    factor = (1.0 / math.sqrt(D)) if scale is None else scale
    scores = torch.matmul(query, key.transpose(-2, -1)) * factor   # [B,H,L,S]
    if mask is not None:
        scores = scores + mask                                      # broadcast
    probs = torch.softmax(scores, dim=-1)                           # [B,H,L,S]
    return torch.matmul(probs, value)                               # [B,H,L,D]


def per_head_rmsnorm(x: torch.Tensor, weight: torch.Tensor,
                     eps: float = 1e-6) -> torch.Tensor:
    """Per-head RMSNorm applied on the D axis.

        x:      [B, L, H, D]   (or [B, H, L, D] - just needs D last)
        weight: [H, D]         (one learned scale per (head, dim))

    RMSNorm does NOT zero-mean; it rescales by the root-mean-square along D:
        rms    = sqrt(mean(x^2, dim=-1) + eps)
        x_hat  = x / rms * weight

    Applied to Q and K inside attention this BOUNDS the per-token vector norm,
    which bounds the pre-softmax logits, which keeps softmax out of saturation.
    """
    rms = torch.sqrt(x.pow(2).mean(dim=-1, keepdim=True) + eps)     # [...,1]
    return x / rms * weight                                          # broadcast over H


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def grid_table(name: str, mat: torch.Tensor, row_label: str,
               col_label: str, cell: str = "{:+.1f}") -> None:
    """Render a 2D tensor [L, S] as a markdown-style grid."""
    nrows, ncols = mat.shape
    print(name)
    print()
    header = f"| {row_label} \\ {col_label} | " + \
             " | ".join(f"s={j}" for j in range(ncols)) + " |"
    sep = "| " + " | ".join(["---"] * (ncols + 1)) + " |"
    print(header)
    print(sep)
    for i in range(nrows):
        vals = " | ".join(cell.format(mat[i, j].item()) for j in range(ncols))
        print(f"| l={i} | {vals} |")
    print()


# ============================================================================
# 3. SECTIONS  (the numbers that feed CAUSAL_MASK.md)
# ============================================================================

def section_a_prefill_mask():
    banner("SECTION A: prefill causal mask  [L=4, S=4], k=(S-L)=0")
    L, S = 4, 4
    mask = causal_mask(L, S, torch.float32)
    print(f"L = {L} (query length),  S = {S} (key length)")
    print(f"k = (S - L) = {S - L}  -> standard lower-triangular triangle")
    print()
    print("Reading the grid:  0 = ALLOWED,  -inf = MASKED (future position)")
    print()
    grid_table("PREFILL mask  mask[l,s]   (0=attend, -inf=blocked)",
               mask, "l (query)", "s (key)")
    print("Token i attends ONLY to positions 0..i. The diagonal and below is")
    print("open; everything strictly above the diagonal (the future) is -inf.")
    print("After softmax, masked positions get probability EXACTLY 0 (because")
    print("exp(-inf) = 0). This is what makes the LM autoregressive.")


def section_b_decode_mask():
    banner("SECTION B: decode causal mask  [L=1, S=4], k=(S-L)=3")
    L, S = 1, 4
    mask = causal_mask(L, S, torch.float32)
    print(f"L = {L} (one new query token),  S = {S} (all cached keys)")
    print(f"k = (S - L) = {S - L}  -> shifts the triangle so the single row is")
    print("                              entirely inside the allowed region")
    print()
    print("Reading the grid:  0 = ALLOWED,  -inf = MASKED")
    print()
    grid_table("DECODE mask  mask[l,s]   (the one query may attend to ALL keys)",
               mask, "l (query)", "s (key)")
    print("This is the WHOLE point of k=(S-L): during decode, the new token is")
    print("the LAST token, so it must see ALL previous keys. The offset slides")
    print("the triangle right by (S-L) so the single row becomes all-allowed.")
    print()
    print("Without the offset (k=0), the decode row would be [0,-inf,-inf,-inf]")
    print("and the new token could only see the FIRST key -> garbage.")
    print("Section D demonstrates exactly that bug.")


def section_c_full_attention():
    banner("SECTION C: full masked attention  B=1, H=1, L=4, S=4, D=8")
    B, H, L, S, D = 1, 1, 4, 4, 8
    # HARDCODED deterministic inputs (no RNG) so the .html can reproduce the
    # EXACT same numbers with the identical vectors. q and k are small readable
    # values; v is one-hot per key so out[l] on dims 0..3 == probs[l,:] directly.
    q = torch.tensor([[
        [ 0.5,  0.2, -0.1,  0.4,  0.3, -0.2,  0.1,  0.5],   # l=0
        [ 0.1, -0.4,  0.3,  0.2, -0.5,  0.1,  0.4, -0.3],   # l=1
        [-0.3,  0.5,  0.2, -0.1,  0.4,  0.3, -0.2,  0.1],   # l=2
        [ 0.4,  0.1, -0.3,  0.5,  0.2, -0.4,  0.3,  0.1],   # l=3
    ]]).reshape(B, H, L, D)
    k = torch.tensor([[
        [ 0.2, -0.1,  0.4,  0.3, -0.2,  0.5,  0.1,  0.3],   # s=0
        [ 0.5,  0.2, -0.3,  0.1,  0.4,  0.3, -0.1,  0.2],   # s=1
        [-0.1,  0.4,  0.2, -0.5,  0.3,  0.1,  0.4, -0.2],   # s=2
        [ 0.3, -0.2,  0.5,  0.1, -0.4,  0.2,  0.3,  0.1],   # s=3
    ]]).reshape(B, H, S, D)
    v = torch.tensor([[
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],            # s=0 (one-hot)
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],            # s=1
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],            # s=2
        [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],            # s=3
    ]]).reshape(B, H, S, D)
    mask = causal_mask(L, S, q.dtype)                              # [L,S]

    print(f"Shapes:  q {tuple(q.shape)}  k {tuple(k.shape)}  v {tuple(v.shape)}")
    print(f"         mask {tuple(mask.shape)}   (broadcast over B,H)")
    print()
    print("v is one-hot per key, so out[l] on dims 0..3 == probs[l,:] exactly.")
    print()

    out_mine = scaled_dot_product_attention(q, k, v, scale=None, mask=mask)

    # gold reference: torch's own scaled_dot_product_attention with the SAME
    # additive mask. attn_mask (float) is ADDED to the scaled scores.
    out_ref = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
    match = torch.allclose(out_mine, out_ref, atol=1e-6)
    print(f"[check] my SDPA == torch SDPA (atol=1e-6)?  {match}")
    assert match, "masked attention does not match torch reference!"

    # show the per-query attention OUTPUT and the per-query prob mass on each key
    scale = 1.0 / math.sqrt(D)
    scores = (q @ k.transpose(-2, -1)) * scale + mask            # [1,1,4,4]
    probs = torch.softmax(scores, dim=-1)                        # [1,1,4,4]
    print()
    print("Masked attention PROBABILITIES  probs[l,s]  (row l sums to 1,")
    print("masked entries are exactly 0):")
    print()
    grid_table("", probs[0, 0], "l (query)", "s (key)", cell="{:.4f}")
    print("Row l=0 puts 100% on s=0 (only itself). Row l=3 spreads over s=0..3.")
    print("Every masked entry is 0.0000 - exactly the autoregressive property.")
    print()
    print("Attention OUTPUT out[l] = sum_s probs[l,s] * v[s]. Because v is")
    print("one-hot, out[l,d] == probs[l,d] for d=0..3 (and 0 for d>=4):")
    print()
    print("| l | out[0]  out[1]  out[2]  out[3]  out[4]  out[5]  out[6]  out[7] |")
    print("|---|--------|--------|--------|--------|--------|--------|--------|--------|")
    for l in range(L):
        vals = " ".join(f"{out_mine[0,0,l,d].item():+.4f}" for d in range(D))
        print(f"| {l} | {vals} |")
    print()
    print("[GOLD] out[0,0,0,:] (the l=0 row, single-token attention output) =")
    gold = [round(v, 4) for v in out_mine[0, 0, 0].tolist()]
    print(f"       {gold}")
    print("[GOLD] out[0,0,3,:] (the l=3 row, full-causal-row output) =")
    gold3 = [round(x, 4) for x in out_mine[0, 0, 3].tolist()]
    print(f"       {gold3}")
    print("(these are the values causal_mask.html gold-checks against)")


def section_d_wrong_mask():
    banner("SECTION D: the WRONG mask on decode (k=0 instead of k=S-L)")
    B, H, L, S, D = 1, 1, 1, 4, 8
    g = torch.Generator().manual_seed(0)
    q = torch.randn(B, H, L, D, generator=g)
    k = torch.randn(B, H, S, D, generator=g)
    v = torch.randn(B, H, S, D, generator=g)
    scale = 1.0 / math.sqrt(D)

    correct_mask = causal_mask(L, S, q.dtype)        # k = S - L = 3  (right)
    # The WRONG mask: build a [1,4] mask but with k=0 (forget the offset).
    # That makes only column s=0 allowed - exactly the prefill formula
    # misapplied to a single decode query.
    wrong_tri = torch.tril(torch.ones((L, S), dtype=q.dtype), diagonal=0)
    wrong_mask = torch.where(wrong_tri > 0,
                             torch.tensor(0.0, dtype=q.dtype),
                             torch.tensor(float("-inf"), dtype=q.dtype))

    print(f"Decode shape: L={L}, S={S}. New token is the LAST key (position {S-1}).")
    print()
    print(f"CORRECT: k = S - L = {S - L}  -> mask shape [{L},{S}]:")
    grid_table("", correct_mask, "l", "s")
    print(f"WRONG:   k = 0            -> mask shape [{L},{S}] (forgot the offset):")
    grid_table("", wrong_mask, "l", "s")

    sc = (q @ k.transpose(-2, -1)) * scale
    probs_correct = torch.softmax(sc + correct_mask, dim=-1)
    probs_wrong = torch.softmax(sc + wrong_mask, dim=-1)

    print("Resulting attention weights over keys s=0..3:")
    print()
    print("| mask used       | probs[0] | probs[1] | probs[2] | probs[3] |")
    print("|-----------------|----------|----------|----------|----------|")
    pc = " | ".join(f"{probs_correct[0,0,0,j].item():.4f}" for j in range(S))
    pw = " | ".join(f"{probs_wrong[0,0,0,j].item():.4f}" for j in range(S))
    print(f"| CORRECT k={S-L}     | {pc} |")
    print(f"| WRONG   k=0     | {pw} |")
    print()
    print("The WRONG mask puts 100%% on s=0 and 0%% on s=1,2,3 - so the new")
    print("decoded token would attend ONLY to the FIRST token of the whole")
    print("prompt and ignore everything after. The output collapses to v[0],")
    print("not a real weighted average. That is silent garbage: no crash, no")
    print("error, just wrong numbers. Always use k=(S-L).")


def section_e_qk_norm():
    banner("SECTION E: QK-Norm (Qwen3) - per-head RMSNorm on Q and K BEFORE dot")
    B, L, H, D = 1, 4, 2, 8
    g = torch.Generator().manual_seed(1)
    # deliberately LARGE inputs so the stability effect is visible
    q_raw = torch.randn(B, L, H, D, generator=g) * 5.0
    k_raw = torch.randn(B, L, H, D, generator=g) * 5.0
    # per-head RMSNorm weights (one scale per (head, dim)); init to ones here
    q_norm_w = torch.ones(H, D)
    k_norm_w = torch.ones(H, D)

    q_normed = per_head_rmsnorm(q_raw, q_norm_w, eps=1e-6)
    k_normed = per_head_rmsnorm(k_raw, k_norm_w, eps=1e-6)

    # move to [B,H,L,D] for the dot product (shape choreography, see Section F)
    q_raw_t = q_raw.transpose(1, 2)
    k_raw_t = k_raw.transpose(1, 2)
    q_normed_t = q_normed.transpose(1, 2)
    k_normed_t = k_normed.transpose(1, 2)

    scale = 1.0 / math.sqrt(D)
    scores_raw = (q_raw_t @ k_raw_t.transpose(-2, -1)) * scale
    scores_normed = (q_normed_t @ k_normed_t.transpose(-2, -1)) * scale

    def norm_per_vec(x):  # L2 norm of each [..,D] vector
        return x.norm(dim=-1)

    print(f"Inputs deliberately scaled x5 (B={B}, L={L}, H={H}, D={D}).")
    print("RMSNorm weight initialised to all-ones so only the RESCALE shows.\n")
    print("| quantity                       | WITHOUT QK-Norm | WITH QK-Norm |")
    print("|--------------------------------|-----------------|--------------|")
    print(f"| max ||q||  (per token,per head)|   {norm_per_vec(q_raw).max().item():.4f}        |"
          f"   {norm_per_vec(q_normed).max().item():.4f}     |")
    print(f"| max ||k||  (per token,per head)|   {norm_per_vec(k_raw).max().item():.4f}        |"
          f"   {norm_per_vec(k_normed).max().item():.4f}     |")
    print(f"| max RMS(q) (per token,per head)|   {torch.sqrt(q_raw.pow(2).mean(-1)).max().item():.4f}        |"
          f"   {torch.sqrt(q_normed.pow(2).mean(-1)).max().item():.4f}     |")
    print(f"| max abs score  (Q.K / sqrt(D)) |   {scores_raw.abs().max().item():.4f}        |"
          f"   {scores_normed.abs().max().item():.4f}     |")
    print(f"| std of scores                  |   {scores_raw.std().item():.4f}        |"
          f"   {scores_normed.std().item():.4f}     |")
    print()
    # RMSNorm pins each vector's RMS to ~1 (times weight). With weight=1, after
    # norm each ||q|| = sqrt(D) = sqrt(8) = 2.8284 exactly.
    expected = math.sqrt(D)
    got = norm_per_vec(q_normed).max().item()
    print(f"[check] with weight=1, ||q_normed|| = sqrt(D) = {expected:.4f}?  "
          f"max observed = {got:.4f}  -> "
          f"{'OK' if abs(got - expected) < 1e-3 else 'FAIL'}")
    assert abs(got - expected) < 1e-3
    print()
    print("Why this matters: softmax saturates when logits spread > ~10. With")
    print("x5 inputs the raw scores range over ~+/-15 -> near-one-hot softmax ->")
    print("near-zero gradients -> training stalls. After QK-Norm the scores are")
    print("bounded (because ||q|| and ||k|| are pinned), so softmax stays in the")
    print("well-conditioned regime. This is the 'cheap training insurance' that")
    print("Qwen3, OLMo2, Gemma2, etc. all adopted. See CAUSAL_MASK.md Sources.")


def section_f_shape_choreography():
    banner("SECTION F: shape choreography  [B,L,H,D] <-> [B,H,L,D]")
    B, L, H, D = 1, 4, 2, 8
    g = torch.Generator().manual_seed(2)
    x = torch.randn(B, L, H * D, generator=g)   # pretend this is wq @ input
    wq = torch.randn(H * D, H * D, generator=g)
    q = (x @ wq).reshape(B, L, H, D)            # [B,L,H,D]

    print("The Qwen3 attention forward pass, with the shape printed at every")
    print("step. The ORDER is what bites people (see CAUSAL_MASK.md pitfalls).\n")
    steps = [
        ("1. project        q = linear(x, wq).reshape(B,L,H,D)", tuple(q.shape)),
        ("2. QK-Norm        q = rms_norm(q, q_norm[H,D])         "
         "(on D axis, BEFORE RoPE)", tuple(q.shape)),
        ("3. RoPE           q = rope(q, offset=slice(0,L))       "
         "(L axis is the position axis)", tuple(q.shape)),
        ("4. transpose      q = q.transpose(1,2)                 "
         "-> [B,H,L,D]", tuple(q.transpose(1, 2).shape)),
        ("5. attention      scores = q @ k^T * scale + mask      "
         "-> [B,H,L,S]", (B, H, L, L)),
        ("6. transpose back q = q.transpose(1,2)                 "
         "-> [B,L,H,D]", tuple(q.transpose(1, 2).transpose(1, 2).shape)),
        ("7. reassemble     out = q.reshape(B, L, H*D)           "
         "-> [B,L,E]", (B, L, H * D)),
    ]
    print("| step                                           | shape          |")
    print("|------------------------------------------------|----------------|")
    for desc, shp in steps:
        print(f"| {desc:<46} | {str(shp):<14} |")
    print()
    print("KEY: steps 2 and 3 (QK-Norm, RoPE) happen while the tensor is still")
    print("[B,L,H,D] - because position is the L axis and both QK-Norm and RoPE")
    print("need to index per-position (L). AFTER the transpose to [B,H,L,D] the")
    print("L axis is in the wrong slot for the cos/sin lookup, so doing RoPE")
    print("post-transpose is the #1 silent-corruption bug.  See ROPE.md section 6.")
    print()
    print("The mask [L,S] is added at step 5 and broadcasts over the B and H")
    print("axes of scores [B,H,L,S] - same mask for every batch, every head.")


# ============================================================================
# main
# ============================================================================

def main():
    print("causal_mask.py - reference impl. Numbers below feed CAUSAL_MASK.md.")
    print("torch =", torch.__version__)
    print()
    print("Three intertwined attention mechanics:")
    print("  (1) WHY causal: add -inf at future positions before softmax")
    print("  (2) The k=(S-L) diagonal offset: one formula for prefill + decode")
    print("  (3) QK-Norm (Qwen3): per-head RMSNorm on Q,K before the dot-product")

    section_a_prefill_mask()
    section_b_decode_mask()
    section_c_full_attention()
    section_d_wrong_mask()
    section_e_qk_norm()
    section_f_shape_choreography()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
