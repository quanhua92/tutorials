"""
absolute_pe.py - Reference implementation of ADDITIVE (absolute) position
embeddings: the OTHER family from ROPE.md.

== The big idea, in one sentence (the "seat-number barcode" intuition) ======
Instead of turning a compass needle (RoPE), you STAMP each token with its seat
number, written as a fixed barcode of sin/cos values, and ADD that barcode to
the token. Two tokens then compare their barcodes directly — but the comparison
depends on the EXACT seat numbers, not just how far apart they are. That is the
opposite of RoPE, where only the distance survives.

== Plain-English glossary ===================================================
    token        one word/piece of the input.
    position (m) the token's seat number, counting from 0.
    embedding    the list of numbers representing a token's meaning.
    model dim (E) how many numbers the WHOLE token vector has (NOT per-head).
                 Absolute PE works on E; RoPE works on the per-head D. Never
                 confuse the two.
    barcode      a fixed sin/cos pattern unique to seat m (sinusoidal), OR a
                 learned row of a table (GPT-2 wpe). Either way it is ADDED.
    dot product  "how similar are two vectors?" — the attention score.
    frequency    how fast one sin/cos coordinate wiggles as m grows. Same
                 frequency ladder [1,0.1,0.01,0.001] as RoPE — the deep link.

Covers:
  1. Sinusoidal PE  (original "Attention Is All You Need", 2017)
  2. Learned PE     (nanoGPT / GPT-2 `wpe` table)

Companion code that ABSOLUTE_PE.md is built from. Every number below is
printed by:
    uv run python absolute_pe.py

KEY CONTRAST vs RoPE (see ROPE.md):
  - RoPE      ROTATES Q and K, in [B, L, H, D], in EVERY layer, on pairs.
  - Absolute  ADDS a position vector, ONCE, to the input in [B, L, E].
  The frequency idea is shared; the OPERATION differs. That difference is why
  absolute PE cannot do the relative-position trick (Section E).

Conventions:
    B = batch size
    L = sequence length
    E = embedding / model dim  (NOT the per-head dim D used in RoPE)
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. SINUSOIDAL POSITION EMBEDDING  (original Transformer)
# ============================================================================

class SinusoidalPE:
    """Fixed (non-learned) sinusoidal position embedding.

    In barcode words: this builds a table where row m is the fixed sin/cos
    "barcode" for seat m. __call__ just ADDS that row to the token. No
    rotation, no multiplication — pure addition, once, at the input.

        PE(pos, 2i)   = sin(pos / base^(2i / E))
        PE(pos, 2i+1) = cos(pos / base^(2i / E))

    For i in 0..E/2-1. Each (sin, cos) pair uses the same frequency
    1 / base^(2i/E) = base^(-i/(E/2)).

    Note the frequency base^(-i/(E/2)) is EXACTLY RoPE's theta_j with
    j = i, D = E. Same frequencies; here they are STORED as values to add,
    in RoPE they are used as ANGLES to rotate with.
    """

    def __init__(self, dim: int, seq_len: int, base: float = 10000.0):
        self.dim = dim
        self.half = dim // 2
        i = torch.arange(0, self.half, dtype=torch.float32)        # [E/2]
        div = base ** (2 * i / dim)                                 # [E/2] = base^(2i/E)
        pos = torch.arange(seq_len, dtype=torch.float32).unsqueeze(1)  # [L,1]
        angles = pos / div                                          # [L, E/2]
        pe = torch.zeros(seq_len, dim)
        pe[:, 0::2] = torch.sin(angles)   # even dims get sin
        pe[:, 1::2] = torch.cos(angles)   # odd dims get cos
        self.pe = pe                              # [L, E]  (the table)

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        """Add PE to x of shape [B, L, E]. Returns [B, L, E]."""
        L = x.shape[1]
        return x + self.pe[:L].unsqueeze(0).to(x.dtype)


# ============================================================================
# 2. LEARNED POSITION EMBEDDING  (nanoGPT / GPT-2 `wpe`)
# ============================================================================

class LearnedPE:
    """A learnable table wpe: nn.Embedding(max_len, dim).

    At training time the table is updated by SGD. At inference you just look
    up the row for each position. There is NO formula - the table is data.
    Here we init it deterministically (seeded) so numbers are reproducible.
    """

    def __init__(self, dim: int, max_len: int, seed: int = 0):
        self.dim = dim
        self.max_len = max_len
        g = torch.Generator().manual_seed(seed)
        self.wpe = torch.randn(max_len, dim, generator=g) * 0.02   # [max_len, E]

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        L = x.shape[1]
        return x + self.wpe[:L].unsqueeze(0).to(x.dtype)


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 4. SECTIONS  (the numbers that feed ABSOLUTE_PE.md)
# ============================================================================

def section_frequencies(pe: SinusoidalPE):
    banner("SECTION A: frequencies  div_term = base^(2i/E)  (identical roots as RoPE theta)")
    i = torch.arange(pe.half)
    div = pe.base ** (2 * i / pe.dim) if hasattr(pe, "base") else \
        10000.0 ** (2 * i / pe.dim)
    base = 10000.0
    print(f"E = {pe.dim},  E/2 = {pe.half},  base = {base:.0f}")
    print()
    print("| i | 2i/E | div_term = base^(2i/E) | freq = 1/div_term | "
          "= RoPE's theta_j? |")
    print("|---|------|------------------------|-------------------|------------------|")
    for ii in range(pe.half):
        d = base ** (2 * ii / pe.dim)
        f = 1.0 / d
        rope_theta = base ** (-(ii / pe.half))
        match = "YES (identical)" if abs(f - rope_theta) < 1e-9 else "no"
        print(f"| {ii} | {2*ii/pe.dim:<4.2f} | {d:<22.4f} | {f:<17.6f} | {match} |")
    print()
    print("Takeaway: the SAME frequency ladder [1, 0.1, 0.01, 0.001] powers both")
    print("families. Difference: sinusoidal ADDS sin/cos VALUES; RoPE uses them")
    print("as ROTATION ANGLES.")


def section_sinusoidal_table(pe: SinusoidalPE):
    banner("SECTION B: the sinusoidal PE table  [L, E]")
    L_show = 4
    table = pe.pe[:L_show]
    print(f"Shape: {tuple(pe.pe.shape)} = [seq_len={pe.pe.shape[0]}, E={pe.dim}]")
    print("(First L=4 rows. Even dims = sin, odd dims = cos.)\n")
    header = "| m | " + " | ".join(f"d{d}" for d in range(pe.dim)) + " |"
    sep = "|---|" + "|".join(["---"] * pe.dim) + "|"
    print(header)
    print(sep)
    for m in range(L_show):
        vals = " | ".join(f"{table[m, d].item():+.4f}" for d in range(pe.dim))
        print(f"| {m} | {vals} |")
    print()
    print("Observations:")
    print(" - row m=0: sin(0)=0 on even dims, cos(0)=+1 on odd dims")
    print(" - high-freq dims (d0,d1) wiggle a lot as m grows")
    print(" - low-freq dims (d6,d7) barely change (smooth global signal)")


def section_add_to_embedding(pe: SinusoidalPE):
    banner("SECTION C: ADD PE to token embeddings  (the operation)")
    B, L, E = 1, 4, 8
    tok = torch.zeros(B, L, E)
    for m in range(L):
        for d in range(E):
            tok[0, m, d] = round(0.1 * (d + 1), 4)   # content = same for every pos
    print(f"Input shape: {tuple(tok.shape)} = [B={B}, L={L}, E={E}]")
    print("Token embedding (content identical across positions, so we can see PE):\n")
    for m in range(L):
        print(f"  m={m}: {[round(v,4) for v in tok[0,m].tolist()]}")
    out = pe(tok)
    print("\nAfter x = x + PE[m]:\n")
    for m in range(L):
        print(f"  m={m}: {[round(v,4) for v in out[0,m].tolist()]}")
    print()
    print("Notice: position 0 had sin=0,cos=1 added, so it shifts most on the odd")
    print("(cos) dims. Each row now CARRIES its absolute position as part of the")
    print("vector - the dot product Q.K will 'feel' m and n directly.")


def section_learned_pe(lpe: LearnedPE):
    banner("SECTION D: LEARNED PE (nanoGPT wpe) - a lookup table, no formula")
    L_show = 4
    print(f"wpe table shape: {tuple(lpe.wpe.shape)} = [max_len, E]")
    print(f"(seeded randn*0.02; in real training these are learned by SGD)\n")
    print("First L=4 rows of wpe:\n")
    header = "| m | " + " | ".join(f"d{d}" for d in range(lpe.dim)) + " |"
    sep = "|---|" + "|".join(["---"] * lpe.dim) + "|"
    print(header)
    print(sep)
    for m in range(L_show):
        vals = " | ".join(f"{lpe.wpe[m, d].item():+.4f}" for d in range(lpe.dim))
        print(f"| {m} | {vals} |")
    print()
    print("There is no sin/cos pattern - these are arbitrary learned numbers.")
    print("nanoGPT builds this as  wpe = nn.Embedding(block_size, n_embd)  and")
    print("indexes it by position at the input, right after the token embedding.")


def section_absolute_vs_relative():
    banner("SECTION E: ABSOLUTE vs RELATIVE - the proof (contrast RoPE Section H)")
    E = 8
    pe = SinusoidalPE(E, seq_len=64, base=10000.0)
    q_raw = torch.tensor([1.0, 0.0, 0.5, -0.3, 0.2, 0.8, -0.1, 0.4])
    k_raw = torch.tensor([0.3, -0.5, 0.7, 0.1, -0.2, 0.6, 0.9, -0.4])

    def dot(m_q, m_k):
        q = q_raw + pe.pe[m_q]      # absolute PE added
        k = k_raw + pe.pe[m_k]
        return float(torch.dot(q, k))

    print("Same fixed raw Q,K as RoPE's proof, but we ADD sinusoidal PE instead of")
    print("rotating. Claim: the Q.K score depends on BOTH m_q and m_k SEPARATELY,\n"
          "NOT only on (m_q - m_k).\n")
    cases = [(2, 1), (5, 4), (10, 9), (2, 0), (5, 3), (10, 8)]
    print("| m_q | m_k | relative = m_q-m_k |   Q.K score   |")
    print("|-----|-----|-------------------|---------------|")
    scores = {}
    for mq, mk in cases:
        s = dot(mq, mk)
        scores[(mq, mk)] = s
        print(f"| {mq:<3} | {mk:<3} | {mq-mk:<17} | {s:+.6f} |")
    print()
    rel1 = [scores[k] for k in [(2, 1), (5, 4), (10, 9)]]
    rel2 = [scores[k] for k in [(2, 0), (5, 3), (10, 8)]]
    print(f"distance=1 scores: {[f'{s:+.4f}' for s in rel1]}  -> NOT equal")
    print(f"distance=2 scores: {[f'{s:+.4f}' for s in rel2]}  -> NOT equal")
    print()
    print("CONTRAST with RoPE (ROPE.md Section H): there, distance=1 always gave")
    print("+0.514498 and distance=2 always gave +0.285792 - identical regardless")
    print("of absolute position. Here they all DIFFER. Adding a position vector")
    print("cannot make absolute positions cancel in the dot product; only the")
    print("rotation trick can.")


def section_extrapolation(pe: SinusoidalPE, lpe: LearnedPE):
    banner("SECTION F: EXTRapolation beyond training length")
    print("What happens at a position the model never saw?\n")
    print("SINUSOIDAL: smooth function of m -> just keep evaluating it.")
    m_far = 200
    if m_far < pe.pe.shape[0]:
        far = pe.pe[m_far]
        near = pe.pe[1]
        print(f"  PE[m=1]   : {[round(v,4) for v in near.tolist()]}")
        print(f"  PE[m={m_far}]: {[round(v,4) for v in far.tolist()]}")
        print("  (well-defined for any m, by the formula)\n")
    print("LEARNED wpe: the table only has `max_len` rows.")
    print(f"  wpe has shape {tuple(lpe.wpe.shape)} -> rows 0..{lpe.max_len-1}")
    if m_far >= lpe.max_len:
        print(f"  Position m={m_far} -> INDEX ERROR / no row. Out-of-range.")
        print("  This is why GPT-2/nanoGPT hard-cap context at block_size.")
    print()
    print("LENGTH GENERALIZATION: absolute (esp. learned) is weak here. RoPE +")
    print("YaRN/NTK-aware scaling generalize to longer contexts far more")
    print("gracefully. (Modern LLMs chose RoPE largely for this reason.)")


# ============================================================================
# main
# ============================================================================

def main():
    print("absolute_pe.py - reference impl. Numbers below feed ABSOLUTE_PE.md.")
    print("torch =", torch.__version__)

    # tiny model: E=8, base=10000 (same roots as ROPE.md's D=8)
    sin = SinusoidalPE(dim=8, seq_len=64, base=10000.0)
    learned = LearnedPE(dim=8, max_len=32, seed=0)

    section_frequencies(sin)
    section_sinusoidal_table(sin)
    section_add_to_embedding(sin)
    section_learned_pe(learned)
    section_absolute_vs_relative()
    section_extrapolation(sin, learned)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
