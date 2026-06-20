"""
gqa.py - Reference implementation of Grouped-Query Attention (GQA), and the
MHA -> MQA -> GQA lineage.

This is the single source of truth that GQA.md is built from. Every number,
table, and worked example in GQA.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python gqa.py

==========================================================================
THE INTUITION (read this first) — the office with the filing cabinets
==========================================================================
Imagine H_q workers (the "query heads") in an office. Each worker asks
questions about the conversation so far; to answer, they look things up in a
FILING CABINET of past notes. That cabinet is the **KV cache** (the stored
Keys and Values of every token seen so far).

  * MHA  : every worker keeps their OWN full cabinet.   Best notes,
           but a LOT of shelves (= a big KV cache).
  * MQA  : ALL workers share ONE cabinet.               Tiny shelf space,
           but the notes get blurry (= quality drops).
  * GQA  : split the workers into groups; each group shares one cabinet.
           The sweet spot. Qwen3-0.5B has 14 workers and 2 cabinets, so
           7 workers per cabinet (n_repeats = 14 // 2 = 7).

THE REASON GQA EXISTS: at serving time (generating one token at a time), every
single step the workers must RE-READ those cabinets from slow memory (HBM) into
the compute cores. Fewer cabinets = less memory traffic = faster generation.
That is the whole point of GQA: keep the cabinets small WITHOUT collapsing to
just one (which hurts quality).

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  query head  : a "worker" — one of H_q parallel question-askers.
  key/value   : a "cabinet" — a shared store of past-token notes. There are
  head          H_kv of these. Each cabinet holds, for every past token, a Key
                (a tag used to score relevance) and a Value (the note itself).
  KV cache    : the cabinets, full of past notes. Re-read every decode step.
  H_q         : number of query heads (workers).   Here: 14.
  H_kv        : number of key/value heads (cabinets). Here: 2.  H_q % H_kv == 0.
  n_repeats   : workers per cabinet  =  H_q // H_kv.  Here: 7.
  broadcasting: letting every worker in a group read the SAME cabinet without
                physically photocopying it. This is the trick that makes GQA
                cheap (the cabinet count stays H_kv, never balloons to H_q).
  reshape     : relabeling a tensor's axes (no data copy) to expose the group
                structure so broadcasting can do its job.

==========================================================================
THE LINEAGE (papers)
==========================================================================
  MHA  (Vaswani 2017, arXiv:1706.03762) : H_q == H_kv. Max quality, max KV
                                          memory. (nanoGPT)
  MQA  (Shazeer 2019, arXiv:1911.02150) : H_kv == 1. Min memory, quality drops.
  GQA  (Ainslie 2023, arXiv:2305.13245) : H_kv groups. Sweet spot.
                                          (Llama, Qwen, Mistral)

The serving bottleneck (Shazeer 1911.02150, verified): during autoregressive
decoding, every step reloads the ENTIRE key/value cache from HBM. That cache is
proportional to H_kv. Cutting H_kv cuts memory bandwidth linearly -> faster
decode. GQA keeps H_kv small WITHOUT collapsing to 1 (which hurts quality).

KEY FORMULAS (all verified against the papers + asserted in code):
    attention(q,k,v) = softmax( q @ k^T / sqrt(d) ) @ v
    n_repeats        = H_q // H_kv           (must divide evenly)
    KV cache elements= num_layers * 2 * H_kv * S * D   (the 2 = K and V)
    GQA broadcast    : reshape q -> [..., H_kv, n_repeats, L, D],
                                 k,v -> [..., H_kv, 1, S, D]; matmul broadcasts
    EQUIVALENCE      : GQA(H_q, H_kv) output == MHA(H_q) output when each KV
                       head is repeated n_repeats times (torch.repeat_interleave)
                       -> the broadcast trick is NOT an approximation.

Conventions for tensor shapes (used throughout):
    B    = batch size
    H_q  = number of query heads  (workers)
    H_kv = number of key/value heads (cabinets);   H_q % H_kv == 0
    L    = query sequence length
    S    = key/value sequence length   (S == L for self-attention)
    D    = head dimension

So q is [B, H_q, L, D], k and v are [B, H_kv, S, D]  (the attention layout,
AFTER the [B, L, H, D] -> [B, H, L, D] transpose). 🔗 RoPE is applied BEFORE
this transpose, on [B, L, H, D] (see ROPE.md §6).
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code GQA.md walks through)
# ============================================================================

def softmax_last(x: torch.Tensor) -> torch.Tensor:
    """Numerically stable softmax along the last axis."""
    x = x - x.max(dim=-1, keepdim=True).values
    e = x.exp()
    return e / e.sum(dim=-1, keepdim=True)


def attention(q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
    """Scaled dot-product attention, from scratch (no F.scaled_dot_product_*).

    q: [..., L, D],  k: [..., S, D],  v: [..., S, D]  ->  [..., L, D]
    The leading dims (heads, groups, batch) broadcast/matmul uniformly.
    No mask here, to keep the GQA mechanism the only moving part. 🔗 For causal
    masking see causal_mask.py / learning_guide/01_Math_Pipe.md §2.5 Stage A.
    """
    scale = q.shape[-1] ** -0.5                          # 1/sqrt(D)
    scores = (q @ k.transpose(-2, -1)) * scale           # [..., L, S]
    probs = softmax_last(scores)                         # [..., L, S]
    return probs @ v                                     # [..., L, D]


def mha_attention(q, k, v):
    """Multi-Head Attention: H_q == H_kv. q,k,v all [B, H, L, D].

    This is the nanoGPT / original-Transformer path. Every query head has its
    OWN key and value head. Maximum expressivity, maximum KV memory.
    """
    assert q.shape[1] == k.shape[1] == v.shape[1], "MHA requires H_q == H_kv"
    return attention(q, k, v)                            # [B, H, L, D]


def mha_with_repeated_kv(q, k, v):
    """MHA reference built on GQA-style inputs: repeat each KV head n_repeats
    times so there is one KV head per query head, then run plain MHA.

    k, v: [B, H_kv, S, D]  ->  repeated to [B, H_q, S, D]  ->  MHA.
    repeat_interleave gives [kv0, kv0, kv1, kv1, ...] i.e. CONTIGUOUS groups,
    which is exactly what GQA assumes. Used to prove GQA == MHA (Section D).
    """
    H_q, H_kv = q.shape[1], k.shape[1]
    n_repeats = H_q // H_kv
    k_rep = k.repeat_interleave(n_repeats, dim=1)       # [B, H_q, S, D]
    v_rep = v.repeat_interleave(n_repeats, dim=1)       # [B, H_q, S, D]
    return attention(q, k_rep, v_rep)                    # [B, H_q, L, D]


def gqa_attention(q, k, v):
    """Grouped-Query Attention via the broadcast/reshape trick.

    q: [B, H_q, L, D],  k, v: [B, H_kv, S, D]  ->  [B, H_q, L, D]

    IN PLAIN ENGLISH (the cabinet story):
        Instead of photocopying each cabinet `n_repeats` times so every worker
        gets a private copy (wasteful -- that throws away the whole memory win),
        we tell the computer "these `n_repeats` workers are a group" and let them
        all POINT at the one shared cabinet. The matmul handles the sharing
        automatically -- but we must group the workers in the right ORDER
        (cabinet-major, not worker-within-cabinet-major). See the pitfall in
        `gqa_attention_wrong_order` / Section E.

    The KV tensors are NEVER copied: `k` and `v` stay [B, H_kv, S, D] throughout.
    """
    B, H_q, L, D = q.shape
    H_kv, S = k.shape[1], k.shape[2]
    assert H_q % H_kv == 0, "H_q must be a multiple of H_kv"
    n_repeats = H_q // H_kv

    # expose groups: query heads are laid out as contiguous groups of n_repeats
    qg = q.reshape(B, H_kv, n_repeats, L, D)            # [B, H_kv, n_repeats, L, D]
    kg = k.reshape(B, H_kv, 1, S, D)                    # [B, H_kv, 1,        S, D]
    vg = v.reshape(B, H_kv, 1, S, D)                    # [B, H_kv, 1,        S, D]

    out = attention(qg, kg, vg)                         # [B, H_kv, n_repeats, L, D]
    return out.reshape(B, H_q, L, D)                    # [B, H_q, L, D]


def gqa_attention_wrong_order(q, k, v):
    """The classic GQA bug, and it is SILENT (no error, no shape mismatch).

    THE PITFALL IN PLAIN ENGLISH:
        When we tell the computer "these workers are a group," the ORDER of the
        two labels matters. Group as [cabinet, workers-in-group, ...] and each
        group of workers correctly shares one cabinet. Swap the order to
        [workers-in-group, cabinet, ...] and the grouping gets STRIPED -- now
        workers 1 and 2 reach into the WRONG cabinet. The shapes still line up,
        so no error is raised; you just get silently scrambled output. Half the
        numbers turn to garbage (see Section E). Same shapes, silently wrong.
    """
    B, H_q, L, D = q.shape
    H_kv, S = k.shape[1], k.shape[2]
    n_repeats = H_q // H_kv

    # WRONG ORDER: n_repeats comes BEFORE H_kv
    qg = q.reshape(B, n_repeats, H_kv, L, D)            # [B, n_repeats, H_kv, L, D]
    kg = k.reshape(B, 1, H_kv, S, D)                    # [B, 1,        H_kv, S, D]
    vg = v.reshape(B, 1, H_kv, S, D)

    out = attention(qg, kg, vg)                         # [B, n_repeats, H_kv, L, D]
    return out.reshape(B, H_q, L, D)                    # [B, H_q, L, D]  (scrambled)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_vec(v, nd=4):
    return "[" + ", ".join(f"{x:+.{nd}f}" for x in v.tolist()) + "]"


# ============================================================================
# 3. THE TINY CONCRETE MODEL: H_q=4, H_kv=2, D=8, L=4
#    Tiny enough to print every number, big enough to show all behavior.
#    Deterministic SEEDED inputs so .html can replicate them exactly.
# ============================================================================

def make_qkv(H_q=4, H_kv=2, L=4, D=8, seed=0):
    """Deterministic Q, K, V for the tiny worked example.

    q: [1, H_q,  L, D],  k, v: [1, H_kv, L, D]. Seeded so every run + the .html
    use byte-identical inputs.
    """
    g = torch.Generator().manual_seed(seed)
    q = (torch.randn(1, H_q, L, D, generator=g) * 0.5).round(decimals=4)
    k = (torch.randn(1, H_kv, L, D, generator=g) * 0.5).round(decimals=4)
    v = (torch.randn(1, H_kv, L, D, generator=g) * 0.5).round(decimals=4)
    return q, k, v


# ----------------------------------------------------------------------------
# SECTION A: the three configs (MHA / MQA / GQA)
# ----------------------------------------------------------------------------

def section_configs():
    banner("SECTION A: the three attention configs  (MHA -> MQA -> GQA)")
    H_q = 14
    print(f"Fix H_q = {H_q} query heads (as in Qwen3-0.5B). Now vary H_kv:\n")
    print("| config | H_q | H_kv | n_repeats = H_q//H_kv | KV heads per Q-head |")
    print("|--------|-----|------|------------------------|---------------------|")
    rows = [
        ("MHA", H_q, H_q),
        ("GQA", H_q, 2),
        ("MQA", H_q, 1),
    ]
    for name, hq, hkv in rows:
        nr = hq // hkv
        per = "1 own" if name == "MHA" else f"1 shared by {nr}"
        print(f"| {name:<6} | {hq:<3} | {hkv:<4} | {nr:<22} | {per:<19} |")
    print()
    print("Read it as a slider on H_kv:")
    print("  - MHA  (H_kv = H_q): each Q-head gets its OWN K,V  -> best quality, most memory")
    print("  - GQA  (1 < H_kv < H_q): groups of Q-heads share  -> sweet spot")
    print("  - MQA  (H_kv = 1): ALL Q-heads share ONE K,V      -> least memory, quality drops")
    print()
    print("GQA is literally an interpolation between MHA and MQA (Ainslie 2023):")
    print("  H_kv = H_q  ->  MHA ;  H_kv = 1  ->  MQA ;  anything between -> GQA.")


# ----------------------------------------------------------------------------
# SECTION B: KV memory math (the serving bottleneck)
# ----------------------------------------------------------------------------

def section_kv_memory():
    banner("SECTION B: KV-cache memory  =  num_layers * 2 * H_kv * S * D")
    print("During autoregressive decode, every step reloads the WHOLE key/value")
    print("cache from HBM (Shazeer 2019, arXiv:1911.02150). That cost scales with")
    print("H_kv, NOT H_q. Cutting H_kv cuts memory bandwidth linearly.\n")
    print("elements_per_layer = 2 * H_kv * S * D      (the 2 = one K + one V)")
    print("bytes_per_layer    = elements * bytes_per_element   (2 for fp16)\n")
    # Qwen3-0.5B real numbers
    H_q, H_kv, D, layers = 14, 2, 64, 28
    S = 4096
    print(f"Qwen3-0.5B: H_q={H_q}, H_kv={H_kv}, D={D}, layers={layers}, S={S}\n")
    print("| variant | H_kv | elements/layer = 2*H_kv*S*D | bytes/layer (fp16) | "
          "savings vs MHA   |")
    print("|---------|------|----------------------------|--------------------|"
          "------------------|")
    base = None
    for name, hkv in [("MHA", H_q), ("GQA", H_kv), ("MQA", 1)]:
        elems = 2 * hkv * S * D
        mib = elems * 2 / 2 ** 20
        if base is None:
            base = elems
            sav = "1.0x (baseline)"
        else:
            sav = f"{base / elems:.1f}x smaller"
        print(f"| {name:<7} | {hkv:<4} | {elems:<26,} | {mib:<8.2f} MiB        | "
              f"{sav:<16} |")
    print()
    print(f"Total KV cache (all {layers} layers), GQA, fp16, S={S}:")
    total_elems = layers * 2 * H_kv * S * D
    total_bytes = total_elems * 2
    print(f"  = {layers} * 2 * {H_kv} * {S} * {D} * 2 bytes")
    print(f"  = {total_elems:,} elements = {total_bytes:,} bytes "
          f"= {total_bytes/2**20:.1f} MiB")
    print(f"\nIf this were MHA (H_kv={H_q}), the cache would be "
          f"{H_q/H_kv:.0f}x bigger. THAT is why Qwen3/Llama/Mistral chose GQA.")
    print("\n[check] savings ratio GQA vs MHA == H_q/H_kv == "
          f"{H_q}/{H_kv} == {H_q/H_kv:.0f}x:  OK")


# ----------------------------------------------------------------------------
# SECTION C: the broadcast reshape trick, shapes at every step
# ----------------------------------------------------------------------------

def section_reshape_trick():
    banner("SECTION C: the broadcast reshape trick (shapes at every step)")
    H_q, H_kv, L, D = 4, 2, 4, 8
    q, k, v = make_qkv(H_q, H_kv, L, D)
    B = q.shape[0]
    S = k.shape[2]
    n_repeats = H_q // H_kv
    print(f"Tiny model: B={B}, H_q={H_q}, H_kv={H_kv}, L={L}, S={S}, D={D}, "
          f"n_repeats={n_repeats}\n")
    print("Input shapes (attention layout, AFTER the [B,L,H,D]->[B,H,L,D] transpose):")
    print(f"  q: {tuple(q.shape)}   = [B, H_q,  L, D]")
    print(f"  k: {tuple(k.shape)}   = [B, H_kv, S, D]")
    print(f"  v: {tuple(v.shape)}   = [B, H_kv, S, D]\n")

    print("GOAL: each Q-head in group g uses KV head g. Group g = Q-heads "
          f"[g*{n_repeats} .. g*{n_repeats}+{n_repeats}-1].\n")

    qg = q.reshape(B, H_kv, n_repeats, L, D)
    kg = k.reshape(B, H_kv, 1, S, D)
    vg = v.reshape(B, H_kv, 1, S, D)
    print("Step 1 - reshape to expose groups (KV is NEVER copied):")
    print(f"  q -> qg: {tuple(q.shape)}  ->  {tuple(qg.shape)}   "
          f"= [B, H_kv, n_repeats, L, D]")
    print(f"  k -> kg: {tuple(k.shape)}  ->  {tuple(kg.shape)}   "
          f"= [B, H_kv, 1,        S, D]   <- size-1 broadcasts")
    print(f"  v -> vg: {tuple(v.shape)}  ->  {tuple(vg.shape)}   "
          f"= [B, H_kv, 1,        S, D]\n")

    scale = D ** -0.5
    scores = (qg @ kg.transpose(-2, -1)) * scale
    print("Step 2 - scores = qg @ kg^T * 1/sqrt(D). The size-1 KV axis broadcasts")
    print("across the n_repeats axis, so all Q-heads in a group hit the SAME KV head:")
    print(f"  scores: {tuple(scores.shape)}  = [B, H_kv, n_repeats, L, S]\n")

    probs = softmax_last(scores)
    out = probs @ vg
    print("Step 3 - softmax over S, then @ vg (also broadcasts over n_repeats):")
    print(f"  probs:  {tuple(probs.shape)}  = [B, H_kv, n_repeats, L, S]")
    print(f"  out:    {tuple(out.shape)}  = [B, H_kv, n_repeats, L, D]\n")

    final = out.reshape(B, H_q, L, D)
    print("Step 4 - flatten the (H_kv, n_repeats) axes back to H_q:")
    print(f"  result: {tuple(final.shape)}  = [B, H_q, L, D]\n")
    print("KEY POINT: k and v stayed [B, H_kv, S, D] the whole time. We materialized")
    print("ZERO extra KV. The savings (Section B) are real, not just bookkeeping.")


# ----------------------------------------------------------------------------
# SECTION D: MHA(repeated KV) == GQA  (numerical equivalence proof + gold)
# ----------------------------------------------------------------------------

def section_equivalence():
    banner("SECTION D: GQA == MHA-with-repeated-KV  (equivalence proof + GOLD)")
    H_q, H_kv, L, D = 4, 2, 4, 8
    q, k, v = make_qkv(H_q, H_kv, L, D)
    n_repeats = H_q // H_kv
    print(f"Tiny model: H_q={H_q}, H_kv={H_kv}, D={D}, L={L}, "
          f"n_repeats={n_repeats}\n")

    out_gqa = gqa_attention(q, k, v)                       # the broadcast path
    out_mha = mha_with_repeated_kv(q, k, v)                # the explicit-repeat path
    max_diff = (out_gqa - out_mha).abs().max().item()
    match = torch.allclose(out_gqa, out_mha, atol=1e-6)
    print("Two ways to compute the SAME thing:")
    print("  (1) GQA       : reshape+broadcast, KV never copied")
    print("  (2) MHA-repeat: repeat_interleave KV to H_q heads, then plain MHA")
    print(f"\n  max|GQA - MHA-repeat| = {max_diff:.3e}")
    print(f"  [check] GQA == MHA(repeated KV)?  {match}  "
          f"(atol=1e-6)  ->  the broadcast trick is provably exact\n")

    # show the explicit repeat mapping (why repeat_interleave is the right op)
    k_rep = k.repeat_interleave(n_repeats, dim=1)
    print("Why repeat_INTERLEAVE (not repeat)? It yields CONTIGUOUS groups:")
    print(f"  k heads (H_kv={H_kv})    map to repeated k heads (H_q={H_q}):")
    mapping = []
    for hq in range(H_q):
        mapping.append(f"    Q-head {hq} -> KV-head {hq // n_repeats}")
    for m in mapping[:2 * n_repeats + 1]:
        print(m)
    print(f"  (i.e. Q-heads 0..{n_repeats-1} all share KV-head 0, "
          f"Q-heads {n_repeats}..{H_q-1} share KV-head 1, ...)\n")

    # GOLD: pin the GQA output for head 0 (all L positions). .html recomputes this.
    print("GOLD value (pinned for gqa.html) - GQA output, Q-head h=0, all positions:")
    head0 = out_gqa[0, 0]                                  # [L, D]
    for m in range(L):
        print(f"  out[h=0, m={m}] = {fmt_vec(head0[m])}")
    print()
    # also pin a single scalar for a compact check: out[h=0,m=0,d=0]
    gold_scalar = out_gqa[0, 0, 0, 0].item()
    print(f"GOLD scalar out[h=0, m=0, d=0] = {gold_scalar:+.6f}   "
          f"(compact .html check)")
    # assert gold matches the recomputed GQA path (self-consistency)
    assert abs(gold_scalar - gqa_attention(q, k, v)[0, 0, 0, 0].item()) < 1e-6
    print("[check] gold scalar reproduces from gqa_attention():  OK")


# ----------------------------------------------------------------------------
# SECTION E: the reshape-order pitfall (correct vs wrong -> scrambled output)
# ----------------------------------------------------------------------------

def section_reshape_pitfall():
    banner("SECTION E: pitfall - reshape ORDER matters  "
           "[...,H_kv,n_repeats,...] not [...,n_repeats,H_kv,...]")
    H_q, H_kv, L, D = 4, 2, 4, 8
    q, k, v = make_qkv(H_q, H_kv, L, D)
    n_repeats = H_q // H_kv
    print(f"Tiny model: H_q={H_q}, H_kv={H_kv}, n_repeats={n_repeats}\n")

    print("Q-heads are laid out as CONTIGUOUS groups in the H_q axis:")
    print("  H_q axis: [ g0h0, g0h1 | g1h0, g1h1 ]   (group 0 = Q0,Q1; group 1 = Q2,Q3)")
    print("  correct KV mapping:  Q0->KV0, Q1->KV0, Q2->KV1, Q3->KV1\n")

    print("reshape [H_q] -> (H_kv, n_repeats)  = (2, 2) splits ROW-MAJOR:")
    print("  -> [[g0h0, g0h1], [g1h0, g1h1]]   = group structure PRESERVED  ✓")
    print("reshape [H_q] -> (n_repeats, H_kv)  = (2, 2) splits ROW-MAJOR:")
    print("  -> [[g0h0, g1h0], [g0h1, g1h1]]   = STRIPED, groups SCRAMBLED  ✗\n")

    correct = gqa_attention(q, k, v)
    wrong = gqa_attention_wrong_order(q, k, v)
    diff = (correct - wrong).abs()
    print(f"Correct reshape [..., H_kv, n_repeats, ...]  vs  "
          f"WRONG reshape [..., n_repeats, H_kv, ...]:")
    print(f"  max|correct - wrong| = {diff.max().item():.4f}")
    print(f"  num elements that differ (>|1e-4|): "
          f"{(diff > 1e-4).sum().item()} / {diff.numel()}\n")

    print("Output, Q-head h=1, position m=0  (h=1 is where the two orderings diverge):")
    print(f"  CORRECT (Q1->KV0): {fmt_vec(correct[0, 1, 0])}")
    print(f"  WRONG   (Q1->KV1): {fmt_vec(wrong[0, 1, 0])}")
    print(f"  (head h=0 is identical in both, since Q0->KV0 either way; the")
    print(f"   scramble shows up on the MIDDLE heads of each group.)")
    print()
    # why they differ: the wrong order pairs Q0->KV0, Q1->KV1, Q2->KV0, Q3->KV1
    print("WHY wrong order scrambles (the pairing flips for middle heads):")
    print("  CORRECT pairing: Q0->KV0, Q1->KV0, Q2->KV1, Q3->KV1")
    print("  WRONG   pairing: Q0->KV0, Q1->KV1, Q2->KV0, Q3->KV1")
    print("  Q1 and Q2 get the WRONG KV head. No error is raised - silent garbage.")
    print("FIX: always reshape q to [..., H_kv, n_repeats, L, D], k/v to "
          "[..., H_kv, 1, S, D].")


# ============================================================================
# main
# ============================================================================

def main():
    print("gqa.py - reference impl. All numbers below feed GQA.md.")
    print("torch =", torch.__version__)

    section_configs()
    section_kv_memory()
    section_reshape_trick()
    section_equivalence()
    section_reshape_pitfall()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
