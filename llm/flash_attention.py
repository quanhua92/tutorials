"""
flash_attention.py - Reference implementation of FlashAttention.

This is the single source of truth that FLASH_ATTENTION.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python flash_attention.py

============================================================================
THE IDEA IN PLAIN ENGLISH (full version: FLASH_ATTENTION.md section 0)
============================================================================
Attention builds an N x N table of scores (one cell per token pair). For N=8192
that table is 256 MiB. The naive code writes that whole table to SLOW main memory
(HBM) and reads it right back — that round trip, not the math, is what is slow.
LLMs are starved for MEMORY BANDWIDTH, not compute.

FlashAttention = do the whole attention in TINY CHUNKS (tiles) that fit in the
GPU's FAST scratchpad memory (SRAM), so the giant table is never written to slow
memory at all. Same answer, far less shuffling. It is EXACT, not an approximation.

The clever core is ONLINE SOFTMAX. Standard softmax needs the biggest score in the
WHOLE row before it can compute anything. Online softmax reads the row one tile at
a time and keeps three running numbers:
    m = running HIGH SCORE (max seen so far; starts at -inf)
    l = running SUM        (used to normalize at the end; starts at 0)
    o = running OUTPUT     (the answer, built up tile by tile; starts at 0)
Whenever a tile reveals a NEW higher score, rescale everything accumulated so far
by exp(m_old - m_new) to fix its scale, then add the new tile. At the end divide
o / l. You never needed the whole row at once.

WHAT THIS FILE PROVES (with numbers):
  - Naive attention materializes an [N, N] score matrix in HBM: ~4N^2 traffic.
  - FlashAttention NEVER materializes [N, N]. It tiles K/V through fast SRAM
    and carries a running max m, running sum l, and running output o, updating
    them per tile via the "online softmax" recurrence.
  - The two are MATHEMATICALLY IDENTICAL (exact, not approximate): we assert
    tiled_output == naive_output to atol=1e-5.
  - The win is HBM-traffic reduction (LLM inference is bandwidth-bound), NOT
    fewer FLOPs (same 2N^2*d matmul FLOPs either way).

ANCHOR RECURRENCE (web-verified, see FLASH_ATTENTION.md "## Sources"):
  naive:     out = softmax(Q @ K^T / sqrt(d)) @ V
  per query row, per K/V tile j with scores s = q_tile @ k_tile.T * scale:
      m_new = max(m_old, rowmax(s))
      p     = exp(s - m_new)                         # [Br, Bc]
      l_new = exp(m_old - m_new) * l_old + rowsum(p)
      o_new = exp(m_old - m_new) * o_old + p @ v_tile
      m_old = m_new
  final:     out_row = o / l
  The factor exp(m_old - m_new) is THE whole trick: < 1 when the max rises
  (shrinks the past to the new scale), = 1 when it is unchanged, = 0 on the
  first tile (m_old = -inf -> correctly zeroes the empty accumulators).

GLOSSARY (defined at first use in FLASH_ATTENTION.md section 0.7):
    HBM    = GPU's SLOW, big main memory (round trips here are expensive)
    SRAM   = GPU's FAST, tiny scratchpad (where tiles live)
    tile   = a small chunk (e.g. [Br,Bc] scores) small enough to fit in SRAM
    m,l,o  = running max / running sum / running output, carried per query row

Conventions (tiny model so EVERY per-tile number prints):
    N = sequence length   (number of tokens)
    d = head dimension
    Br = Q tile size (rows)
    Bc = K/V tile size (cols)
"""

from __future__ import annotations

import math

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code the guide walks through)
# ============================================================================

def naive_attention(Q: torch.Tensor, K: torch.Tensor, V: torch.Tensor,
                    scale: float) -> tuple[torch.Tensor, torch.Tensor]:
    """Naive attention that MATERIALIZES the full [N, N] score matrix in HBM.

    Returns (out, scores) so callers can inspect/price the [N, N] matrix.
        scores = Q @ K^T * scale            # [N, N]  <- the whole thing lives in HBM
        probs  = softmax_rowwise(scores)
        out    = probs @ V
    """
    scores = (Q @ K.T) * scale                      # [N, N] materialized
    m = scores.max(dim=-1, keepdim=True).values     # [N, 1] row max
    exp_scores = torch.exp(scores - m)              # [N, N] safe exp
    l = exp_scores.sum(dim=-1, keepdim=True)        # [N, 1] row normalizer
    probs = exp_scores / l                          # [N, N] softmax
    out = probs @ V                                 # [N, d]
    return out, scores


def flash_attention_tiled(Q: torch.Tensor, K: torch.Tensor, V: torch.Tensor,
                          scale: float, Br: int, Bc: int,
                          trace_row: int | None = None) -> torch.Tensor:
    """FlashAttention: tiled, online-softmax, NEVER materializes [N, N].

    Iterates Q in row-tiles of size Br; for each Q-tile streams K,V in col-tiles
    of size Bc through SRAM, maintaining running (m, l, o) per query row.
    Returns out : [N, d], mathematically identical to naive_attention.

    If `trace_row` is set, prints the per-tile (m, l, o) evolution for that one
    query row, including the rescaling factor exp(m_old - m_new).
    """
    N, d = Q.shape
    O = torch.zeros(N, d, dtype=Q.dtype)
    Tr = (N + Br - 1) // Br       # number of Q-tiles
    Tc = (N + Bc - 1) // Bc       # number of K/V-tiles

    for i in range(Tr):
        r0 = i * Br
        br = min(Br, N - r0)                       # rows in this Q-tile
        q_tile = Q[r0:r0 + br]                      # [br, d]  -> SRAM
        m_i = torch.full((br,), float("-inf"))      # running max, per query row
        l_i = torch.zeros(br)                       # running normalizer
        o_i = torch.zeros(br, d, dtype=Q.dtype)     # running output

        local_row = trace_row - r0 if (trace_row is not None
                                       and r0 <= trace_row < r0 + br) else None

        for j in range(Tc):
            c0 = j * Bc
            bc = min(Bc, N - c0)
            k_tile = K[c0:c0 + bc]                   # [bc, d]  -> SRAM
            v_tile = V[c0:c0 + bc]                   # [bc, d]  -> SRAM

            s = (q_tile @ k_tile.T) * scale          # [br, bc]  <- ONE tile only
            rowmax = s.max(dim=-1).values            # [br]
            m_new = torch.maximum(m_i, rowmax)       # [br]
            correction = torch.exp(m_i - m_new)      # [br]  rescale prior accumulators
            p = torch.exp(s - m_new.unsqueeze(-1))   # [br, bc]
            m_old = m_i.clone()                       # capture BEFORE update
            l_old = l_i.clone()
            o_old = o_i.clone()
            l_i = correction * l_i + p.sum(dim=-1)
            o_i = correction.unsqueeze(-1) * o_i + p @ v_tile
            m_i = m_new

            if local_row is not None:
                _trace_tile(local_row, j, c0, bc, s, rowmax, m_old, m_new,
                            correction, p, l_old, l_i, o_old, o_i, m_i)

        O[r0:r0 + br] = o_i / l_i.unsqueeze(-1)      # final normalize
    return O


def flash_attention_broken(Q: torch.Tensor, K: torch.Tensor, V: torch.Tensor,
                           scale: float, Br: int, Bc: int) -> torch.Tensor:
    """The PITFALL variant: omits the exp(m_old - m_new) rescaling of prior
    accumulators. Mathematically WRONG -> diverges from naive (used in Section F).
    """
    N, d = Q.shape
    O = torch.zeros(N, d, dtype=Q.dtype)
    Tr = (N + Br - 1) // Br
    Tc = (N + Bc - 1) // Bc
    for i in range(Tr):
        r0 = i * Br
        br = min(Br, N - r0)
        q_tile = Q[r0:r0 + br]
        m_i = torch.full((br,), float("-inf"))
        l_i = torch.zeros(br)
        o_i = torch.zeros(br, d, dtype=Q.dtype)
        for j in range(Tc):
            c0 = j * Bc
            bc = min(Bc, N - c0)
            k_tile = K[c0:c0 + bc]
            v_tile = V[c0:c0 + bc]
            s = (q_tile @ k_tile.T) * scale
            rowmax = s.max(dim=-1).values
            m_new = torch.maximum(m_i, rowmax)
            # BUG: no rescaling of l_i / o_i when the max moves.
            p = torch.exp(s - m_new.unsqueeze(-1))
            l_i = l_i + p.sum(dim=-1)
            o_i = o_i + p @ v_tile
            m_i = m_new
        O[r0:r0 + br] = o_i / l_i.unsqueeze(-1)
    return O


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def _fmt_vec(v, w=8):
    return "  ".join(f"{x:+.4f}".rjust(w) for x in v)


def _trace_tile(r, j, c0, bc, s, rowmax, m_old, m_new, correction, p,
                l_old, l_i, o_old, o_i, m_i):
    """Print one tile's effect on the traced query row (Section C)."""
    cols = list(range(c0, c0 + bc))
    m_old_str = "-inf" if math.isinf(m_old[r].item()) else f"{m_old[r].item():+.4f}"
    corr_str = "0.0000" if math.isinf(m_old[r].item()) else f"{correction[r].item():+.4f}"
    print(f"  --- K/V tile j={j} (keys {cols}) ---")
    print(f"     scores s        = [{', '.join(f'{x:+.4f}' for x in s[r].tolist())}]")
    print(f"     rowmax(s)       = {rowmax[r].item():+.4f}")
    print(f"     m_old           = {m_old_str}")
    print(f"     m_new           = max(m_old, rowmax) = {m_new[r].item():+.4f}")
    print(f"     correction      = exp(m_old - m_new) = {corr_str}"
          f"   <-- rescales ALL prior accumulators")
    print(f"     p = exp(s-m_new)= [{', '.join(f'{x:.4f}' for x in p[r].tolist())}]")
    print(f"     l_new           = correction*l_old + sum(p) "
          f"= {corr_str}*{l_old[r].item():.4f} + {p[r].sum().item():.4f}"
          f" = {l_i[r].item():+.4f}")
    print(f"     o_new           = correction*o_old + p@v_tile =")
    print(f"                       [{', '.join(f'{x:+.4f}' for x in o_i[r].tolist())}]")
    print(f"     (m,l,o) after   = m={m_i[r].item():+.4f}, "
          f"l={l_i[r].item():+.4f}")


# ============================================================================
# 3. THE SMALL CONCRETE MODEL: N=8, d=8, Br=Bc=4, deterministic seed=0
#    Tiny enough to print every per-tile number; big enough to show rescaling.
# ============================================================================

def make_inputs(seed: int = 0):
    """Deterministic Q, K, V. Rounded to 2 dp so numbers are readable and so the
    .html can recompute the identical matrices. Query row 0 is chosen because its
    global argmax (key 6) lands in tile j=1 -> the rescaling factor is < 1 there."""
    g = torch.Generator().manual_seed(seed)
    N, d = 8, 8
    Q = torch.round(torch.randn(N, d, generator=g) * 0.5, decimals=2)
    K = torch.round(torch.randn(N, d, generator=g) * 0.5, decimals=2)
    V = torch.round(torch.randn(N, d, generator=g) * 0.5, decimals=2)
    return Q, K, V


def section_naive(Q, K, V, scale):
    banner("SECTION A: NAIVE attention MATERIALIZES [N,N] in HBM")
    N, d = Q.shape
    out, scores = naive_attention(Q, K, V, scale)
    nbytes = scores.numel() * scores.element_size()
    print(f"N = {N}, d = {d}, scale = 1/sqrt(d) = {scale:.4f}")
    print(f"Materialized score matrix S = Q @ K^T * scale, shape {tuple(scores.shape)}\n")
    print("S (the [N,N] matrix that naive attention writes to HBM):\n")
    print("| q\\k | " + " | ".join(f"k={j}" for j in range(N)) + " |")
    print("|" + "---|" * (N + 1))
    for i in range(N):
        print(f"| q={i} | " +
              " | ".join(f"{scores[i, j].item():+.4f}" for j in range(N)) + " |")
    print()
    print("HBM traffic estimate for naive attention (per head, per layer):")
    print(f"  S written once  : N*N floats = {N*N} elements "
          f"= {nbytes} bytes")
    print(f"  softmax reads S : N*N = {N*N}")
    print(f"  softmax writes P: N*N = {N*N}")
    print(f"  out = P @ V     : reads N*N + N*d")
    print(f"  => leading term ~4*N^2 = {4*N*N} floats for the score matrix alone")
    print()
    print("Scaling to N=8192, d=64 (4-byte float):")
    big = 8192 * 8192 * 4
    print(f"  N*N*4 bytes = {big} bytes = {big/1024/1024:.0f} MiB per head per layer")
    print("  -> read+written at every one of (layers * heads) calls. Catastrophic.")
    print()
    print("Naive output (out = softmax(S) @ V), shape "
          f"{tuple(out.shape)}:\n")
    for i in range(N):
        print(f"  q={i}: [{', '.join(f'{v:+.4f}' for v in out[i].tolist())}]")
    return out, scores


def section_why_streaming_is_hard(scores):
    banner("SECTION B: standard softmax NEEDS the full row -> streaming is non-obvious")
    N = scores.shape[0]
    print("Standard (safe) softmax for ONE row needs the global max FIRST:\n")
    print("    m     = max(row)          # must see EVERY element first")
    print("    probs = exp(x - m) / sum(exp(x - m))\n")
    print("If we only hold tile j=0 of the row, its local max is NOT the global")
    print("max. As later tiles reveal larger values, every earlier exp() term was")
    print("computed with the WRONG denominator. Naively this forces materializing")
    print("the whole row -> the [N,N] matrix -> back to square one.\n")
    print("Example: row q=0 of S from Section A. The two K/V tiles (Bc=4):\n")
    Bc = 4
    print("| tile | keys  | local rowmax | global max so far |")
    print("|------|-------|--------------|-------------------|")
    gmax = float("-inf")
    for j in range(0, N, Bc):
        tile = scores[0, j:j + Bc]
        lmax = tile.max().item()
        gmax = max(gmax, lmax)
        print(f"| j={j//Bc}   | {list(range(j, j+Bc))} | "
              f"{lmax:+.4f}       | {gmax:+.4f}            |")
    print()
    print("Tile j=1 raises the max from +0.0909 to +0.4049. Any exp() accumulated")
    print("in tile j=0 is now off by a factor of exp(0.0909 - 0.4049). The online")
    print("softmax recurrence (Section C) fixes this WITHOUT keeping the row.")


def section_online_softmax_one_row(Q, K, V, scale):
    banner("SECTION C: ONLINE SOFTMAX on ONE query row (q=0), tile by tile")
    N = Q.shape[0]
    Bc = 4
    print(f"Tracing query row q=0 (one Q-tile Br=N={N}) through K/V tiles of size "
          f"Bc={Bc} (Tc={N//Bc} tiles).\n")
    print("Accumulators start empty: m_old = -inf, l_old = 0, o_old = 0 vector.\n")
    # Br = N puts all queries in one Q-tile so row 0 is traced across both
    # K/V tiles; trace_row=0 selects it. K and V are the real full matrices.
    flash_attention_tiled(Q, K, V, scale, Br=N, Bc=Bc, trace_row=0)
    # Cross-check against the one-shot result for row 0.
    s_full = (Q[0:1] @ K.T * scale)[0]
    m_glob = s_full.max().item()
    l_glob = torch.exp(s_full - m_glob).sum().item()
    o_glob = (torch.softmax(s_full, dim=-1).unsqueeze(0) @ V)[0]
    print()
    print("Cross-check (the tiled recurrence must equal this one-shot result):")
    print(f"  global m  = {m_glob:+.4f}")
    print(f"  global l  = {l_glob:+.4f}")
    print(f"  out = o/l = [{', '.join(f'{x:+.4f}' for x in o_glob.tolist())}]")


def section_full_tiled(Q, K, V, scale, naive_out):
    banner("SECTION D: FULL tiled FlashAttention  Br=Bc=4  on [8,8]")
    Br = Bc = 4
    tiled = flash_attention_tiled(Q, K, V, scale, Br=Br, Bc=Bc)
    print(f"N={Q.shape[0]}, d={Q.shape[1]}, Br={Br}, Bc={Bc}  ->  "
          f"Tr={Q.shape[0]//Br} Q-tiles, Tc={Q.shape[0]//Bc} K/V-tiles")
    print("Each Q-tile streams through BOTH K/V tiles, updating (m,l,o).\n")
    print("Tiled output (out = o / l after the last tile):\n")
    for i in range(Q.shape[0]):
        print(f"  q={i}: [{', '.join(f'{v:+.4f}' for v in tiled[i].tolist())}]")
    diff = (tiled - naive_out).abs().max().item()
    print(f"\n[check] max|tiled - naive| = {diff:.2e}")
    assert torch.allclose(tiled, naive_out, atol=1e-5), "tiled != naive!"
    print("[check] FlashAttention == naive attention (atol=1e-5):  OK  "
          "(EXACT, not approximate)")
    return tiled


def section_per_tile_trace(Q, K, V, scale):
    banner("SECTION E: per-Q-tile, per-KV-tile (m,l,o) trace for Q-tile i=0")
    Br, Bc = 4, 4
    N, d = Q.shape
    Tc = N // Bc
    print(f"Outer loop: Q-tile i=0 (rows q=0..3). Inner loop: K/V tiles "
          f"j=0..{Tc-1}.\n")
    print("For brevity we print the running max m, normalizer l, and the max")
    print("abs entry of the running output o, AFTER each K/V tile, for each of")
    print("the 4 query rows in Q-tile i=0. Watch m step up and l rescale.\n")
    r0 = 0
    br = Br
    q_tile = Q[r0:r0 + br]
    m_i = torch.full((br,), float("-inf"))
    l_i = torch.zeros(br)
    o_i = torch.zeros(br, d, dtype=Q.dtype)
    print("| step | " + " | ".join(f"q={r}: m / l / |o|max" for r in range(br)) + " |")
    print("|" + "---|" * (br + 1))
    for j in range(Tc):
        c0 = j * Bc
        k_tile = K[c0:c0 + Bc]
        v_tile = V[c0:c0 + Bc]
        s = (q_tile @ k_tile.T) * scale
        rowmax = s.max(dim=-1).values
        m_new = torch.maximum(m_i, rowmax)
        correction = torch.exp(m_i - m_new)
        p = torch.exp(s - m_new.unsqueeze(-1))
        l_i = correction * l_i + p.sum(dim=-1)
        o_i = correction.unsqueeze(-1) * o_i + p @ v_tile
        m_i = m_new
        cells = []
        for r in range(br):
            on = o_i[r].abs().max().item()
            cells.append(f"{m_i[r].item():+.3f}/{l_i[r].item():.3f}/{on:.3f}")
        print(f"| j={j}   | " + " | ".join(cells) + " |")
    print()
    print("Reading the table: at tile j=1, q=0's m jumps +0.091 -> +0.405. The")
    print("prior l and o got multiplied by exp(0.091-0.405)=0.731 before the new")
    print("tile's contributions were added. THAT correction is the whole trick.")


def section_equivalence(Q, K, V, scale, naive_out):
    banner("SECTION F: EQUIVALENCE  tiled == naive  (and the rescaling PITFALL)")
    tiled = flash_attention_tiled(Q, K, V, scale, Br=4, Bc=4)
    broken = flash_attention_broken(Q, K, V, scale, Br=4, Bc=4)
    d_good = (tiled - naive_out).abs().max().item()
    d_bad = (broken - naive_out).abs().max().item()
    print("Run the CORRECT tiled algorithm and a BROKEN one that omits the")
    print("exp(m_old - m_new) rescaling of prior accumulators.\n")
    print("| variant              | max|out - naive| | verdict |")
    print("|----------------------|-------------------|---------|")
    print(f"| tiled (correct)      | {d_good:.2e}            | OK      |")
    print(f"| tiled (no rescaling) | {d_bad:.2e}            | WRONG   |")
    assert torch.allclose(tiled, naive_out, atol=1e-5)
    assert d_bad > 1e-3, "broken variant should diverge"
    print()
    print(f"[check] tiled == naive (atol=1e-5):  OK   (diff={d_good:.2e})")
    print(f"[check] broken diverges:             OK   (diff={d_bad:.2e} >> 1e-5)")
    print()
    print("Why the broken one fails: when a later tile raises m, every earlier")
    print("exp(s - m_old) term was computed with a smaller m. They are too large")
    print("by exp(m_old - m_new). Skipping the correction leaves l and o on the")
    print("wrong scale -> output is silently wrong (or NaN if m_old=-inf leaked).")


# ============================================================================
# main
# ============================================================================

def main():
    print("flash_attention.py - reference implementation.\n"
          "Numbers below feed FLASH_ATTENTION.md.  torch =", torch.__version__)

    Q, K, V = make_inputs(seed=0)
    N, d = Q.shape
    scale = 1.0 / math.sqrt(d)

    out_naive, scores = section_naive(Q, K, V, scale)
    section_why_streaming_is_hard(scores)
    section_online_softmax_one_row(Q, K, V, scale)
    tiled = section_full_tiled(Q, K, V, scale, out_naive)
    section_per_tile_trace(Q, K, V, scale)
    section_equivalence(Q, K, V, scale, out_naive)

    banner("GOLD PIN (for FLASH_ATTENTION.md + flash_attention.html)")
    print("Pinned tiled output for N=8, d=8, seed=0, Br=Bc=4 "
          "(MUST equal naive):\n")
    for i in range(N):
        print(f"  q={i}: [{', '.join(f'{v:+.4f}' for v in tiled[i].tolist())}]")

    banner("DONE - all sections printed, all [check] OK")


if __name__ == "__main__":
    main()
