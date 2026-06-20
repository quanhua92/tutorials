"""
rope.py - Reference implementation of Rotary Position Embeddings (RoPE).

This is the single source of truth that ROPE.md is built from. Every number,
table, and worked example in ROPE.md is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    uv run python rope.py

== The big idea, in one sentence (the "compass" intuition) ==================
Imagine every token holds a small compass needle. The token's POSITION tells it
how far to turn that needle: position 0 = no turn at all, position 5 = turn a
lot. When two tokens later compare themselves (a dot product, Q·K), the only
thing that survives the comparison is the DIFFERENCE in how far their needles
turned — i.e. how far apart the two tokens sit. So position is stored as a
rotation, and *relative distance appears for free*. That is the whole of RoPE.

== Plain-English glossary (used in every section below) =====================
    token        one word/piece of the input (e.g. "cat" might be token #3).
    position (m) the token's seat number in the sentence, counting from 0.
    embedding    the list of numbers that represents a token's meaning.
    head dim (D) how many numbers one attention head looks at. Must be EVEN,
                 because we split it into D/2 pairs and rotate each pair.
    pair (j)     two coordinates (x1, x2) treated as one 2-D arrow (a complex
                 number x1 + i·x2). D=8 => 4 pairs (j=0,1,2,3).
    Q / K        Query and Key: the two vectors whose dot product = attention.
    dot product  "how similar are these two vectors?" — big & positive = alike.
    rotation     turning an arrow by an angle without changing its length.
    frequency θ_j  how fast pair j spins per step of position. Small j spins
                   fast (local detail), large j spins slowly (global position).
    complex num.  just a 2-D arrow (x1, x2); multiplying two arrows adds their
                  angles — that is the trick that makes positions cancel.
    RoPE         Rotary Position Embedding = the rotation trick defined here.
    offset       which "seat" a freshly-decoded token is really sitting in
                 (see Section G). Getting it wrong => gibberish.

== Layout ====================================================================
"split" (a.k.a. non-traditional), the layout used by Llama / Qwen / most modern
models. Pairs are formed by the first half and second half of the head
dimension, NOT interleaved adjacent elements.

== Tensor-shape conventions (used throughout) ================================
    B = batch size
    L = sequence length (number of tokens)
    H = number of heads   (query heads for Q; this file stays head-agnostic)
    D = head dimension    (MUST be even; we rotate D/2 pairs)

So a Q tensor is [B, L, H, D]. RoPE is applied while the tensor is in THIS
layout (before the [B, H, L, D] transpose used by attention).
"""

from __future__ import annotations

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code ROPE.md walks through)
# ============================================================================

class RoPE:
    """Rotary Position Embedding, split layout, with KV-cache offset support.

    In compass words: __init__ builds two lookup tables (cos, sin), one row per
    seat number m, that say "for seat m, rotate pair j by this many radians".
    __call__ then looks up the right row and performs D/2 independent rotations
    on the token's head vector — that is the whole job.

    Args:
        dims:     head dimension D (must be even — we rotate D/2 pairs).
        seq_len:  max sequence length -> size of the precomputed cos/sin tables.
        base:     frequency base. 10000 for GPT-NeoX/Llama-classic,
                  1000000 for Qwen3 (YaRN-flavored).
        traditional: False = split layout (Llama/Qwen). True = interleaved.
    """

    def __init__(self, dims: int, seq_len: int, base: float = 10000.0,
                 traditional: bool = False):
        self.dims = dims
        self.half_dims = dims // 2
        self.base = base
        self.traditional = traditional

        # --- frequency vector theta_j = base^(-j / (D/2)),  j = 0..D/2-1 ---
        j = torch.arange(0, self.half_dims, dtype=torch.float32)
        inner = j / self.half_dims                 # [0, 1/h, 2/h, ..., (h-1)/h]
        freqs = self.base ** (-inner)              # [half_dims]  = theta_j

        # --- position vector m = 0..seq_len-1 ---
        t = torch.arange(seq_len, dtype=torch.float32)          # [seq_len]

        # --- angle table: angle[m, j] = m * theta_j  (outer product) ---
        angles = torch.outer(t, freqs)             # [seq_len, half_dims]

        # precompute cos/sin (these are what gets looked up per position)
        self.cos_freqs = torch.cos(angles)         # [seq_len, half_dims]
        self.sin_freqs = torch.sin(angles)         # [seq_len, half_dims]

    def __call__(self, x: torch.Tensor,
                 offset: slice | list[slice] | None = None) -> torch.Tensor:
        """Apply RoPE to x of shape [B, L, H, D].

        offset selects which ROWS of the cos/sin table to use:
            None                    -> rows [0, L)            (basic prefill)
            slice(a, b)             -> rows [a, b)            (single seq)
            [slice(a0,b0), ...]     -> per-batch rows         (left-padded batch)
        """
        B, L, H, D = x.shape

        # 1. pick the right rows of the table
        if offset is None:
            cos_basis = self.cos_freqs[:L, :]
            sin_basis = self.sin_freqs[:L, :]
            b_len = 1
        elif isinstance(offset, slice):
            cos_basis = self.cos_freqs[offset, :]
            sin_basis = self.sin_freqs[offset, :]
            b_len = 1
        else:  # list[slice] -> one slice per batch element
            cos_basis = torch.stack([self.cos_freqs[s, :] for s in offset])
            sin_basis = torch.stack([self.sin_freqs[s, :] for s in offset])
            b_len = B

        # 2. reshape basis for broadcasting: [1 or B, L, 1, D/2]
        cos_basis = cos_basis.reshape(b_len, L, 1, self.half_dims)
        sin_basis = sin_basis.reshape(b_len, L, 1, self.half_dims)

        # 3. split x into the two halves that form each rotation pair
        #    (compass view: x1,x2 are the two coordinates of one 2-D arrow.
        #     We split D coords into 4 arrows when D=8 — the "split" layout.)
        if self.traditional:
            # interleaved: pairs are (dim0,dim1),(dim2,dim3),...
            x_view = x.reshape(B, L, H, self.half_dims, 2)
            x1, x2 = x_view[..., 0], x_view[..., 1]
        else:
            # split: pairs are (dim0, dimD/2), (dim1, dimD/2+1), ...
            x1 = x[..., 0:self.half_dims]          # [B, L, H, D/2]
            x2 = x[..., self.half_dims:self.dims]  # [B, L, H, D/2]

        # 4. complex multiply: (x1 + i*x2) * (cos + i*sin)
        #    This is exactly "rotate the arrow by angle (m*theta_j)".
        #    real/imag below are the two coordinates of the turned arrow.
        real = x1 * cos_basis - x2 * sin_basis     # [B, L, H, D/2]
        imag = x2 * cos_basis + x1 * sin_basis     # [B, L, H, D/2]

        # 5. reassemble back to [B, L, H, D]
        if self.traditional:
            y = torch.stack([real, imag], dim=-1).reshape(B, L, H, D)
        else:
            y = torch.cat([real, imag], dim=-1).reshape(B, L, H, D)

        return y.to(x.dtype)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def matrix_table(name: str, mat: torch.Tensor, row_label: str,
                 col_label: str) -> str:
    """Render a 2D tensor as a markdown-style table string + print it."""
    nrows, ncols = mat.shape
    header = f"| {row_label} \\ {col_label} | " + \
             " | ".join(f"j={j}" for j in range(ncols)) + " |"
    sep = "| " + " | ".join(["---"] * (ncols + 1)) + " |"
    lines = [name, "", header, sep]
    for i in range(nrows):
        vals = " | ".join(f"{mat[i, j].item():+.4f}" for j in range(ncols))
        lines.append(f"| m={i} | {vals} |")
    out = "\n".join(lines)
    print(out)
    print()
    return out


# ============================================================================
# 3. THE SMALL CONCRETE MODEL: D=8, base=10000, L=4
#    Tiny enough to print every number, big enough to show all behavior.
# ============================================================================

def section_frequency_table(rope: RoPE):
    banner("SECTION A: frequency vector  theta_j = base^(-j / (D/2))")
    j = torch.arange(rope.half_dims)
    theta = rope.base ** (-(j.float() / rope.half_dims))
    print(f"D = {rope.dims},  D/2 = {rope.half_dims},  base = {rope.base:.0f}")
    print()
    print("| j  | inner = j/(D/2) | theta_j = base^(-inner) | meaning           |")
    print("|----|----------------|--------------------------|-------------------|")
    for jj in range(rope.half_dims):
        inner = jj / rope.half_dims
        th = theta[jj].item()
        meaning = "FAST rotation (local position)" if jj < rope.half_dims // 2 \
            else "SLOW rotation (long-range position)"
        print(f"| {jj}  | {inner:<14.4f} | {th:<24.6f} | {meaning} |")
    print()
    print("Key: small j -> theta near 1 -> rotates a LOT per step (high freq)")
    print("     large j -> theta near 0 -> barely rotates per step (low freq)")


def section_angle_and_trig_tables(rope: RoPE):
    banner("SECTION B+C: angle table m*theta_j  and the cos / sin lookups")
    angles = torch.outer(torch.arange(rope.cos_freqs.shape[0], dtype=torch.float32),
                         rope.base ** (-(torch.arange(rope.half_dims, dtype=torch.float32)
                                         / rope.half_dims)))
    print(f"Shape of cos/sin tables: {tuple(rope.cos_freqs.shape)}  "
          f"= [seq_len={rope.cos_freqs.shape[0]}, D/2={rope.half_dims}]")
    print("(Only the first L=4 rows are shown.)\n")
    L_show = 4
    matrix_table("ANGLE table  angle[m,j] = m * theta_j   (radians)",
                 angles[:L_show], "m", "j")
    matrix_table("COS table  cos_freqs[m, j]   <- this is what gets looked up",
                 rope.cos_freqs[:L_show], "m", "j")
    matrix_table("SIN table  sin_freqs[m, j]   <- this is what gets looked up",
                 rope.sin_freqs[:L_show], "m", "j")


def section_rotate_one_token(rope: RoPE):
    banner("SECTION D: rotate ONE token at position m=2, step by step")
    D = rope.dims
    # deterministic input so the guide is reproducible (no RNG)
    x = torch.tensor([1.0, 0.5, -0.3, 0.8, 0.2, -0.1, 0.4, 0.6]) \
        if D == 8 else torch.arange(1, D + 1, dtype=torch.float32) / 2.0
    x = x.reshape(1, 1, 1, D)           # [B=1, L=1, H=1, D]  (one token)
    m = 2
    half = rope.half_dims

    print(f"Input token x (D={D}), split layout:\n")
    print("| field         | values" + " " * 24 + "|")
    print("|-------------- |" + "-" * 32 + "|")
    print(f"| x1 (first ½)  | {[round(v,4) for v in x[0,0,0,:half].tolist()]}" \
          .ljust(46) + "|")
    print(f"| x2 (second ½) | {[round(v,4) for v in x[0,0,0,half:].tolist()]}" \
          .ljust(46) + "|")
    print()
    print(f"Position m={m}: we use row m={m} of the cos/sin tables.\n")
    cos = rope.cos_freqs[m]   # [D/2]
    sin = rope.sin_freqs[m]   # [D/2]
    x1 = x[0, 0, 0, :half]
    x2 = x[0, 0, 0, half:]

    print("| pair j | x1  | x2   | cos(m*th_j) | sin(m*th_j) |  "
          "real=x1*cos-x2*sin | imag=x2*cos+x1*sin |")
    print("|--------|-----|------|-------------|-------------|"
          "--------------------|---------------------|")
    real_parts, imag_parts = [], []
    for j in range(half):
        r = x1[j] * cos[j] - x2[j] * sin[j]
        im = x2[j] * cos[j] + x1[j] * sin[j]
        real_parts.append(r.item())
        imag_parts.append(im.item())
        print(f"| {j}      | {x1[j].item():+.1f} | {x2[j].item():+.2f} | "
              f"{cos[j].item():+.4f}      | {sin[j].item():+.4f}      | "
              f"{r.item():+.4f}             | {im.item():+.4f}            |")
    print()
    print("Reassemble (concat real then imag) -> rotated token:\n")
    rotated = rope(x.clone(), offset=slice(m, m + 1))
    result = rotated[0, 0, 0].tolist()
    print(f"  RoPE(x, m=2) = {[round(v, 4) for v in result]}")
    print(f"  original  x  = {[round(v, 4) for v in x[0, 0, 0].tolist()]}")
    # sanity check inline math matches the class
    inline = real_parts + imag_parts
    assert torch.allclose(torch.tensor(inline), rotated[0, 0, 0], atol=1e-4)
    print("\n  [check] inline-by-hand math == RoPE class output:  OK")


def section_full_batch(rope: RoPE):
    banner("SECTION E: full batch  B=1, L=4, H=2, D=8")
    B, L, H, D = 1, 4, 2, 8
    # deterministic content: position + head marker so output is traceable
    x = torch.zeros(B, L, H, D)
    for b in range(B):
        for pos in range(L):
            for h in range(H):
                for d in range(D):
                    x[b, pos, h, d] = round(0.1 * pos + 0.01 * h + 0.001 * (d + 1), 4)
    print(f"Input shape: {tuple(x.shape)}  = [B={B}, L={L}, H={H}, D={D}]\n")
    print("Input x[b=0] (L rows x H*D cols, shown per head):\n")
    for h in range(H):
        print(f"  head h={h}:")
        for pos in range(L):
            vals = [f"{x[0, pos, h, d].item():+.3f}" for d in range(D)]
            print(f"    m={pos}: {vals}")
    print()
    y = rope(x, offset=slice(0, L))
    print("Output RoPE(x) x[b=0] (same layout):\n")
    for h in range(H):
        print(f"  head h={h}:")
        for pos in range(L):
            vals = [f"{y[0, pos, h, d].item():+.3f}" for d in range(D)]
            print(f"    m={pos}: {vals}")
    print()
    norm_in = x.reshape(-1, D).norm(dim=-1)
    norm_out = y.reshape(-1, D).norm(dim=-1)
    print(f"[check] RoPE preserves L2 norm? "
          f"max|‖out‖-‖in‖| = {(norm_out - norm_in).abs().max().item():.2e}  "
          f"(rotation is norm-preserving by construction)")


def section_layouts():
    banner("SECTION F: split (Llama/Qwen) vs traditional (GPT-NeoX) layout")
    D = 8
    rope_split = RoPE(D, seq_len=16, base=10000.0, traditional=False)
    rope_trad = RoPE(D, seq_len=16, base=10000.0, traditional=True)
    x = torch.tensor([[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]]).reshape(1, 1, 1, D)
    print(f"Input x (D=8): {x[0,0,0].tolist()}\n")
    print("Split layout (traditional=False): pairs = (dim0,dim4),(dim1,dim5),...")
    print(f"  x1 = dims [0:4] = {x[0,0,0,:4].tolist()}")
    print(f"  x2 = dims [4:8] = {x[0,0,0,4:].tolist()}\n")
    print("Traditional layout (traditional=True): pairs = (dim0,dim1),(dim2,dim3),...")
    print(f"  x1 = dims [0,2,4,6] = {[x[0,0,0,k].item() for k in range(0,D,2)]}")
    print(f"  x2 = dims [1,3,5,7] = {[x[0,0,0,k].item() for k in range(1,D,2)]}\n")
    ys = rope_split(x.clone(), offset=slice(2, 3))
    yt = rope_trad(x.clone(), offset=slice(2, 3))
    print(f"RoPE at m=2, split:        {[round(v,4) for v in ys[0,0,0].tolist()]}")
    print(f"RoPE at m=2, traditional:  {[round(v,4) for v in yt[0,0,0].tolist()]}")
    print("\nDifferent layouts give DIFFERENT outputs. The checkpoint's config")
    print("decides which one to use. Qwen/Llama = split. Never mix them up.")


def section_offset_kv_cache(rope: RoPE):
    banner("SECTION G: the offset parameter (prefill vs KV-cache decode)")
    D = rope.dims
    # Simulate prefill of 3 tokens, then decoding token #4 (position 3).
    prefill_x = torch.tensor([
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    ]).reshape(1, 3, 1, D)
    # --- PREFILL: process positions 0,1,2 all at once ---
    q_prefill = rope(prefill_x.clone(), offset=slice(0, 3))
    print("PREFILL 3 tokens at once, offset = slice(0, 3)  -> rows [0,1,2]\n")
    for pos in range(3):
        print(f"  m={pos}: {[round(v,4) for v in q_prefill[0,pos,0].tolist()]}")
    print()
    # --- DECODE: only the NEW token, at its true position (3) ---
    new_token = torch.tensor([[0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0]]) \
        .reshape(1, 1, 1, D)
    q_decode_correct = rope(new_token.clone(), offset=slice(3, 4))   # row 3
    q_decode_wrong = rope(new_token.clone(), offset=slice(0, 1))     # row 0!
    print("DECODE the 4th token (true position m=3), one token at a time:\n")
    print(f"  CORRECT offset=slice(3,4) -> use row m=3: "
          f"{[round(v,4) for v in q_decode_correct[0,0,0].tolist()]}")
    print(f"  WRONG   offset=slice(0,1) -> use row m=0: "
          f"{[round(v,4) for v in q_decode_wrong[0,0,0].tolist()]}")
    print()
    # Verify: the 4th token decoded with correct offset should equal what we'd
    # get if we had prefilled all 4 tokens together.
    all_four = torch.cat([prefill_x, new_token], dim=1)   # [1,4,1,D]
    q_all = rope(all_four.clone(), offset=slice(0, 4))
    match = torch.allclose(q_decode_correct[0, 0], q_all[0, 3], atol=1e-5)
    print(f"[check] decode(offset=3) == prefill_all[3]?  {match}  "
          f"(this is why offset matters)")


def section_relative_position_proof(rope: RoPE):
    banner("SECTION H: WHY RoPE encodes RELATIVE position (proof by numbers)")
    D = rope.dims
    half = rope.half_dims
    # fixed raw Q and K for one head (not yet rotated)
    q_raw = torch.tensor([1.0, 0.0, 0.5, -0.3, 0.2, 0.8, -0.1, 0.4]).reshape(1, 1, 1, D)
    k_raw = torch.tensor([0.3, -0.5, 0.7, 0.1, -0.2, 0.6, 0.9, -0.4]).reshape(1, 1, 1, D)

    def rot(vec, m):
        return rope(vec.clone(), offset=slice(m, m + 1))[0, 0, 0]

    def dot(m_q, m_k):
        return float(torch.dot(rot(q_raw, m_q), rot(k_raw, m_k)))

    print("Fixed raw Q and K (one head, D=8). We place Q at position m_q and\n"
          "K at position m_k, then take the dot product Q·K (the attention\n"
          "score numerator). The claim: the score depends ONLY on (m_q - m_k).\n")
    cases = [(2, 1), (5, 4), (10, 9), (2, 0), (5, 3), (10, 8)]
    print("| m_q | m_k | RELATIVE = m_q - m_k |   Q·K score  |")
    print("|-----|-----|--------------------|--------------|")
    scores = {}
    for mq, mk in cases:
        s = dot(mq, mk)
        scores[(mq, mk)] = s
        print(f"| {mq:<3} | {mk:<3} | {mq-mk:<18} | {s:+.6f} |")
    print()
    print("Observe: all three pairs with relative distance = 1 give the SAME score:")
    print(f"  (2,1)={scores[(2,1)]:+.6f}  (5,4)={scores[(5,4)]:+.6f}  "
          f"(10,9)={scores[(10,9)]:+.6f}")
    print("Likewise relative distance = 2 all match:")
    print(f"  (2,0)={scores[(2,0)]:+.6f}  (5,3)={scores[(5,3)]:+.6f}  "
          f"(10,8)={scores[(10,8)]:+.6f}")
    print()
    print("This is the magic: the rotation angle that survives the dot product")
    print("is (m_q - m_k)*theta_j, so absolute positions cancel out.")


# ============================================================================
# main
# ============================================================================

def main():
    print("ROPE.py - reference implementation. All numbers below feed ROPE.md.\n"
          "torch =", torch.__version__)

    # The tiny model used everywhere in the guide:
    rope = RoPE(dims=8, seq_len=32, base=10000.0, traditional=False)

    section_frequency_table(rope)
    section_angle_and_trig_tables(rope)
    section_rotate_one_token(rope)
    section_full_batch(rope)
    section_layouts()
    section_offset_kv_cache(rope)
    section_relative_position_proof(rope)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
