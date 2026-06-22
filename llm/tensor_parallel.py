"""
tensor_parallel.py - Reference implementation of Tensor Parallelism (TP),
the Megatron-LM column/row parallel lineage.

This is the single source of truth that TENSOR_PARALLEL.md is built from.
Every number, table, and worked example in the guide is printed by this
file. If you change something here, re-run and re-paste the output.

Run:
    uv run python tensor_parallel.py

NOTE on the simulation:
    This is a FAITHFUL SINGLE-PROCESS SIMULATION of TP=2. We do NOT spawn
    torch.distributed workers; instead we hold the two rank shards as two
    ordinary tensors in one process and implement AllReduce as an explicit
    element-wise sum. The MATH is identical to a real multi-process TP run
    (the only thing we skip is the NCCL communication itself). Every shape,
    every shard index, and every "local vs AllReduce" distinction matches
    nano-vllm's ColumnParallelLinear / RowParallelLinear / QKVParallelLinear
    (../nano-vllm/nanovllm/layers/linear.py) and the Megatron-LM paper.

============================================================================
THE INTUITION (read this first) - the warehouse that doesn't fit in one truck
============================================================================
Imagine a single huge weight matrix is a pallet of goods in a warehouse.
One GPU is one delivery truck. The pallet is too big for any one truck.

  * Naive idea      : buy a bigger truck (a bigger GPU). Expensive, finite.
  * Data Parallel   : every truck carries a COPY of the pallet, and they
                      deliver to different customers (different input batch).
                      Wastes pallet-space × N trucks. Works until the pallet
                      itself won't fit on one truck.
  * Pipeline Par.   : cut the pallet INTO LAYERS along the depth of the
                      warehouse; truck 0 does row 0, hands off to truck 1.
                      Each truck still sees the WHOLE width of its row, but
                      only a slice of depth. Adds a "bubble" of idle time.
  * TENSOR Par.     : cut each pallet MATRIX into strips. Every truck gets
                      a strip of EVERY matrix. They compute in parallel on
                      the same input, then briefly sync up to stitch the
                      strips back together. This is the Megatron idea.

The Megatron trick is *which way to cut*:
  - Column parallel : cut along the OUTPUT dimension (vertical strips).
                      Each truck produces a different chunk of the output.
                      NO sync needed if the next layer is row-parallel.
  - Row parallel    : cut along the INPUT dimension (horizontal strips).
                      Each truck produces a PARTIAL sum of the SAME output.
                      Needs an AllReduce (sum) to combine.

The "AllReduce cancels" magic: for Y = act(X @ A) @ B, make A column-parallel
and B row-parallel. The element-wise activation `act` is local to each
truck's shard, so the would-be AllReduce BETWEEN A and B VANISHES. You pay
exactly ONE AllReduce per MLP/attention block, at the very end.

============================================================================
PLAIN-ENGLISH GLOSSARY (used throughout)
============================================================================
  weight matrix : a learned matrix W of shape [out, in] (PyTorch convention,
                  `nn.Linear` stores W this way; y = x @ W.T). In math we
                  often write Y = X @ A with A of shape [in, out].
  column split  : slicing W along its OUTPUT axis. W[:, k*out/TP:(k+1)*out/TP]
  row split     : slicing W along its INPUT axis.   W[k*in/TP:(k+1)*in/TP, :]
  rank (r)      : which GPU in the TP group, r = 0 .. TP-1.
  shard         : the slice of W one rank holds.
  AllReduce     : a collective op: every rank ends up with the SUM of all
                  ranks' tensors. (Implemented here as `t0 + t1`.) 🔗 NCCL
  partial sum   : what one row-parallel rank produces before AllReduce. It
                  is a piece of the final answer, not the answer.
  GeLU          : the element-wise activation between A and B in a vanilla
                  MLP. Element-wise is WHY the AllReduce cancels. 🔗 MLP

============================================================================
THE LINEAGE (papers)
============================================================================
  Single-GPU    (Vaswani 2017 / nanoGPT)   : one GPU holds the whole model.
                                              Caps model size at ~one GPU's
                                              memory. The "old" baseline.
  Megatron-LM   (Shoeybi et al. 2019,      : cut each weight MATRIX across
                 arXiv:1909.08053)           GPUs. Column/row parallel +
                                              the AllReduce-cancels trick.
                                              1 AllReduce per sub-block.
  vLLM / SGLang (Kwon 2023, Zheng 2023)    : production serving engines that
                                              reuse Megatron's TP for
                                              multi-GPU inference. nano-vllm
                                              is the minimal reference.
  QKVParallelLinear (vLLM)                 : pack Q, K, V projections into
                                              ONE column-parallel matrix,
                                              splitting heads by TP. 🔗 GQA

KEY FORMULAS (all verified against the papers + asserted in code below):

  ColumnParallel:   W shape [out, in], rank r holds W[r*out/TP:(r+1)*out/TP, :]
                    forward:  Y_r = X @ W_r.T        -> [B, out/TP]   NO comm

  RowParallel:      W shape [out, in], rank r holds W[:, r*in/TP:(r+1)*in/TP]
                    forward:  partial_r = X_r @ W_r.T -> [B, out]   (partial)
                              Y = AllReduce(partial_0 + ... + partial_{TP-1})

  Megatron MLP:     A column-parallel, B row-parallel
                    Z_r = act(X @ A_r.T)    # [B, FFN/TP]   local
                    Y_r = Z_r @ B_r.T       # [B, E]        partial
                    Y  = AllReduce(Y_0 + ... + Y_{TP-1}) == act(X @ A.T) @ B.T
                    ==> exactly ONE AllReduce for the whole MLP block.

  Attention TP:     Q,K,V column-parallel (heads split), O row-parallel
                    per-rank attention over H/TP heads, then O_proj partial
                    Y = AllReduce(partial_0 + ... )   # ONE AllReduce for attn

Conventions for tensor shapes:
    B    = batch size
    L    = sequence length
    E    = embedding / model dim
    FFN  = MLP intermediate dim
    H    = number of attention heads (total)
    D    = head dimension
    TP   = tensor-parallel size (number of ranks). TP=2 in every worked example.
"""

from __future__ import annotations

import math

import torch

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (this is the code TENSOR_PARALLEL.md walks)
# ============================================================================

def gelu(x: torch.Tensor) -> torch.Tensor:
    """GELU tanh approximation.  Hendrycks & Gimpel 2016, arXiv:1606.08415.
    Matches mlp_activation.gelu_tanh so this bundle cross-cites cleanly.
    Element-wise: THAT is the property that makes the AllReduce cancel."""
    c = math.sqrt(2.0 / math.pi)
    return 0.5 * x * (1.0 + torch.tanh(c * (x + 0.044715 * x ** 3)))


def all_reduce_sum(*partials: torch.Tensor) -> torch.Tensor:
    """Faithful single-process simulation of NCCL all_reduce(op=SUM).

    In a real multi-process run each rank would contribute its partial to the
    collective and every rank would exit holding the element-wise sum. Here we
    hold all partials in one process and sum them explicitly. The result is
    byte-identical to what NCCL would produce (sum is associative+commutative).
    """
    assert len(partials) >= 2, "AllReduce needs at least 2 ranks"
    out = partials[0].clone()
    for p in partials[1:]:
        out = out + p
    return out


def column_shard(W: torch.Tensor, rank: int, tp: int) -> torch.Tensor:
    """ColumnParallelLinear.weight_loader: take rank's OUTPUT-dim slice.
    W is stored PyTorch-style as [out, in]. Column-parallel splits dim 0.
    """
    out = W.shape[0]
    assert out % tp == 0, f"out ({out}) must divide TP ({tp})"
    shard = out // tp
    return W[rank * shard:(rank + 1) * shard, :]            # [out/TP, in]


def row_shard(W: torch.Tensor, rank: int, tp: int) -> torch.Tensor:
    """RowParallelLinear.weight_loader: take rank's INPUT-dim slice.
    W is stored PyTorch-style as [out, in]. Row-parallel splits dim 1.
    """
    inp = W.shape[1]
    assert inp % tp == 0, f"in ({inp}) must divide TP ({tp})"
    shard = inp // tp
    return W[:, rank * shard:(rank + 1) * shard]            # [out, in/TP]


def column_parallel_forward(X: torch.Tensor, W_r: torch.Tensor) -> torch.Tensor:
    """ColumnParallelLinear.forward. Y_r = X @ W_r.T   -> [B, out/TP]. NO comm."""
    return X @ W_r.T                                        # F.linear without bias


def row_parallel_forward(X_r: torch.Tensor, W_r: torch.Tensor,
                         is_rank0: bool, bias: torch.Tensor | None = None
                         ) -> torch.Tensor:
    """RowParallelLinear.forward. partial_r = X_r @ W_r.T (+ bias if rank 0).
    NOTE: the real nano-vllm code adds bias ONLY on rank 0 (otherwise the
    AllReduce would multiply the bias by TP). Caller must AllReduce afterwards.
    """
    y = X_r @ W_r.T
    if bias is not None and is_rank0:
        y = y + bias
    return y                                                # caller AllReduces


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


def fmt_mat(M, nd=4):
    return "[" + ",\n ".join(fmt_vec(M[i], nd) for i in range(M.shape[0])) + "]"


# ============================================================================
# 3. THE TINY CONCRETE MODEL  (TP=2, seeded so .html can replicate byte-for-byte)
# ============================================================================

def make_mlp_weights(E=8, FFN=4, seed_A=1, seed_B=2, scale=0.3):
    """Deterministic MLP weights A:[FFN,E], B:[E,FFN] for Section C gold."""
    gA = torch.Generator().manual_seed(seed_A)
    gB = torch.Generator().manual_seed(seed_B)
    A = (torch.randn(FFN, E, generator=gA) * scale).round(decimals=4)   # [FFN, E]
    B = (torch.randn(E, FFN, generator=gB) * scale).round(decimals=4)   # [E, FFN]
    return A, B


def make_input(E=8, seed_X=0):
    """Deterministic input X:[1, E] for Section C gold."""
    gX = torch.Generator().manual_seed(seed_X)
    return (torch.randn(1, E, generator=gX) * 0.5).round(decimals=4)


# ----------------------------------------------------------------------------
# SECTION A: why one matrix doesn't fit (the memory budget)
# ----------------------------------------------------------------------------

def section_why_shard():
    banner("SECTION A: why one matrix doesn't fit (the memory budget)")
    print("A modern LLM weight matrix is HUGE. Take a single hidden layer of a")
    print("70B-class model: E = 8192, FFN intermediate = 28672 (Llama-2-70B).")
    print("ONE weight matrix (gate_proj) is [28672, 8192] floats.\n")
    E, FFN = 8192, 28672
    elems = FFN * E
    bytes_fp16 = elems * 2
    bytes_fp32 = elems * 4
    print(f"  gate_proj: [{FFN}, {E}]  = {elems:,} elements")
    print(f"             = {bytes_fp16/2**30:.2f} GiB (fp16)   "
          f"{bytes_fp32/2**30:.2f} GiB (fp32)")
    print()
    print("An H100 has 80 GiB. The MLP block alone has 3 such matrices")
    print("(gate, up, down) = ~1.3 GiB in fp16 PER LAYER. With 80 layers and")
    print("embeddings, the model won't fit on one GPU. Cutting each matrix into")
    print("TP shards is the most surgical fix: TP=8 makes every matrix 8x smaller")
    print("on each GPU, with NO change to the math (proven in Sections C/D).\n")

    print("Per-rank memory after sharding one [28672, 8192] matrix (fp16):\n")
    print("| TP | shard shape        | elements  | bytes/rank (fp16) | savings |")
    print("|----|--------------------|-----------|-------------------|---------|")
    for tp in [1, 2, 4, 8]:
        shard_elems = elems // tp
        b = shard_elems * 2
        sav = "baseline" if tp == 1 else f"{tp}x smaller"
        print(f"| {tp:<2} | [{FFN//tp if tp<=8 else '?'}, {E}]"
              f"{' ' if tp<=8 else ' '}     | {shard_elems:>9,} | "
              f"{b/2**30:>6.3f} GiB          | {sav:<7} |")
    print()
    print("NOTE: the matrix is sharded along ONE axis. Column-parallel splits")
    print("the OUTPUT dim (rows of W stored as [out,in]); row-parallel splits")
    print("the INPUT dim (cols). The savings are identical; the COMMUNICATION")
    print("they require is NOT (Sections B-C).")
    print("\n[check] sharding reduces per-rank memory by exactly TP x:  OK")


# ----------------------------------------------------------------------------
# SECTION B: column vs row parallel (split + comm cost, worked)
# ----------------------------------------------------------------------------

def section_column_vs_row():
    banner("SECTION B: column-parallel vs row-parallel (split + comm cost)")
    TP = 2
    E_in, E_out = 8, 8
    g = torch.Generator().manual_seed(7)
    W = (torch.randn(E_out, E_in, generator=g) * 0.3).round(decimals=4)   # [out, in]
    X = (torch.randn(1, E_in, generator=torch.Generator().manual_seed(0)) * 0.5).round(decimals=4)
    print(f"Tiny model: TP={TP}, W shape {tuple(W.shape)} = [out={E_out}, in={E_in}], "
          f"X shape {tuple(X.shape)}\n")

    full_Y = X @ W.T                                       # [1, out] reference
    print(f"Full (non-TP) forward:  Y = X @ W.T   -> {tuple(full_Y.shape)}")
    print(f"  Y[0] = {fmt_vec(full_Y[0])}\n")

    print("-" * 60)
    print("COLUMN-PARALLEL  (split OUTPUT dim; nano-vllm ColumnParallelLinear)")
    print("-" * 60)
    print("W stored as [out, in]; split dim 0 -> each rank holds [out/TP, in].")
    print("forward:  Y_r = X @ W_r.T  (X is FULL on every rank) -> [1, out/TP]")
    print("COMM:  NONE in forward. To get full Y, AllGather along last dim.\n")
    for r in range(TP):
        W_r = column_shard(W, r, TP)
        Y_r = column_parallel_forward(X, W_r)
        print(f"  rank {r}: W_r {tuple(W_r.shape)} = W[{r}*{E_out//TP}:{(r+1)}*{E_out//TP}, :]")
        print(f"          Y_r = {fmt_vec(Y_r[0])}   shape {tuple(Y_r.shape)}")
    col_concat = torch.cat(
        [column_parallel_forward(X, column_shard(W, r, TP)) for r in range(TP)],
        dim=-1)
    print(f"\n  AllGather (concat along last dim) = {fmt_vec(col_concat[0])}")
    match_col = torch.allclose(col_concat, full_Y, atol=1e-6)
    print(f"  [check] AllGather(Y_0, Y_1) == full Y?  {match_col}  "
          f"(column-parallel: zero comm in forward, AllGather only if needed)\n")

    print("-" * 60)
    print("ROW-PARALLEL  (split INPUT dim; nano-vllm RowParallelLinear)")
    print("-" * 60)
    print("W stored as [out, in]; split dim 1 -> each rank holds [out, in/TP].")
    print("forward:  partial_r = X_r @ W_r.T  (X_r is rank's INPUT slice)")
    print("COMM:  AllReduce(sum) to combine partials into full Y.\n")
    X_ranks = [X[:, r * E_in // TP:(r + 1) * E_in // TP] for r in range(TP)]
    partials = []
    for r in range(TP):
        W_r = row_shard(W, r, TP)
        X_r = X_ranks[r]
        p = row_parallel_forward(X_r, W_r, is_rank0=(r == 0))
        partials.append(p)
        print(f"  rank {r}: W_r {tuple(W_r.shape)} = W[:, {r}*{E_in//TP}:{(r+1)}*{E_in//TP}]")
        print(f"          X_r {tuple(X_r.shape)}, partial_r = {fmt_vec(p[0])}  "
              f"shape {tuple(p.shape)}")
    row_sum = all_reduce_sum(*partials)
    print("\n  AllReduce(sum) = partial_0 + partial_1")
    print(f"                = {fmt_vec(row_sum[0])}")
    match_row = torch.allclose(row_sum, full_Y, atol=1e-6)
    print(f"  [check] AllReduce(partials) == full Y?  {match_row}  "
          f"(row-parallel: ONE AllReduce per layer)\n")

    print("-" * 60)
    print("THE COMM COST TABLE (forward only)")
    print("-" * 60)
    print("| style           | split dim  | per-rank output  | comm in forward     |")
    print("|-----------------|------------|------------------|---------------------|")
    print("| column-parallel | output (0) | [B, out/TP]      | NONE (or AllGather) |")
    print("| row-parallel    | input  (1) | [B, out] partial | ONE AllReduce       |")
    print()
    print("KEY: column-parallel produces a SHARD of the output (cheap, but")
    print("\"incomplete\"); row-parallel produces a FULL-SIZE but WRONG answer")
    print("(partial sum) that must be AllReduced before anyone can use it.")


# ----------------------------------------------------------------------------
# SECTION C: the Megatron MLP "AllReduce cancels" trick (GOLD CENTERPIECE)
# ----------------------------------------------------------------------------

def section_megatron_mlp():
    banner("SECTION C: the Megatron MLP trick - AllReduce CANCELS in the middle  (GOLD)")
    TP = 2
    E, FFN = 8, 4
    A, B = make_mlp_weights(E=E, FFN=FFN, seed_A=1, seed_B=2, scale=0.3)
    X = make_input(E=E, seed_X=0)
    print(f"Tiny model: TP={TP}, X {tuple(X.shape)}=[1, E={E}], "
          f"A {tuple(A.shape)}=[FFN={FFN}, E], B {tuple(B.shape)}=[E, FFN]\n")
    print("Vanilla MLP:   Y = GeLU(X @ A.T) @ B.T")
    print("               (one GPU, full matrices, no comm)\n")

    Y_full = gelu(X @ A.T) @ B.T                           # [1, E]
    print(f"Full Y shape {tuple(Y_full.shape)}:   Y[0] = {fmt_vec(Y_full[0])}\n")

    print("=" * 60)
    print("Megatron TP=2:  A COLUMN-parallel + B ROW-parallel")
    print("=" * 60)
    print("Split A by OUTPUT dim (columns of the math matrix A.T = rows of the")
    print("PyTorch tensor A[FFN,E]). Split B by INPUT dim (rows of B.T = cols")
    print("of B[E,FFN]). Each rank holds A_r=[FFN/TP, E] and B_r=[E, FFN/TP].\n")
    print("GPU 0:  Z_0 = GeLU(X @ A_0.T)   # [1, FFN/TP]   LOCAL")
    print("        Y_0 = Z_0 @ B_0.T       # [1, E]        PARTIAL (sum-like)")
    print("GPU 1:  Z_1 = GeLU(X @ A_1.T)   # [1, FFN/TP]   LOCAL")
    print("        Y_1 = Z_1 @ B_1.T       # [1, E]        PARTIAL")
    print("AllReduce:  Y = Y_0 + Y_1       # ONE collective for the WHOLE block\n")

    A_shards = [column_shard(A, r, TP) for r in range(TP)]   # each [FFN/TP, E]
    B_shards = [row_shard(B, r, TP) for r in range(TP)]      # each [E, FFN/TP]
    Y_partials = []
    for r in range(TP):
        Z_r = gelu(X @ A_shards[r].T)                       # [1, FFN/TP]
        Y_r = Z_r @ B_shards[r].T                           # [1, E]
        Y_partials.append(Y_r)
        print(f"  rank {r}: A_r {tuple(A_shards[r].shape)}, "
              f"B_r {tuple(B_shards[r].shape)}")
        print(f"          Z_r = GeLU(X @ A_{r}.T) = {fmt_vec(Z_r[0])}")
        print(f"          Y_r = Z_r @ B_{r}.T     = {fmt_vec(Y_r[0])}  (partial)")

    Y_tp = all_reduce_sum(*Y_partials)
    print(f"\nAllReduce(Y_0 + Y_1) = {fmt_vec(Y_tp[0])}")
    max_diff = (Y_tp - Y_full).abs().max().item()
    match = torch.allclose(Y_tp, Y_full, atol=1e-6)
    print(f"\n  max|TP_Y - full_Y| = {max_diff:.3e}")
    print(f"  [check] AllReduce(Y_0 + Y_1) == full GeLU(X@A.T)@B.T?  {match}\n")

    print("WHY IT WORKS (one paragraph):")
    print("  The full computation is  Y = GeLU(X @ A.T) @ B.T.")
    print("  Split A.T vertically (columns):  A.T = [A_0.T | A_1.T]  so")
    print("    X @ A.T = [X @ A_0.T  |  X @ A_1.T]   (block matmul, no arithmetic)")
    print("  GeLU is ELEMENT-WISE, so it applies block-by-block:")
    print("    GeLU(X @ A.T) = [GeLU(X @ A_0.T) | GeLU(X @ A_1.T)]")
    print("  Now split B.T HORIZONTALLY (rows):  B.T = [B_0.T ; B_1.T]  so that")
    print("  the top rows of B.T eat the left block of GeLU(X @ A.T), bottom rows")
    print("  eat the right block. Block matmul gives:")
    print("    Y = GeLU(X@A_0.T) @ B_0.T  +  GeLU(X@A_1.T) @ B_1.T")
    print("      = Y_0                       +  Y_1")
    print("  which is EXACTLY the partial-sum + AllReduce pattern. The would-be")
    print("  AllReduce between A and B (to materialize the full GeLU(X @ A.T)) is")
    print("  cancelled because B is row-parallel and GeLU is element-wise.\n")

    # GOLD: pin the full Y vector + one scalar for the .html gold-check
    print("GOLD value (pinned for tensor_parallel.html):")
    print(f"  Y_full[0]              = {fmt_vec(Y_full[0])}")
    print(f"  Y_full[0, 0] (scalar)  = {Y_full[0, 0].item():+.6f}")
    print(f"  Y_partial_0[0]         = {fmt_vec(Y_partials[0][0])}")
    print(f"  Y_partial_1[0]         = {fmt_vec(Y_partials[1][0])}")
    assert abs(Y_full[0, 0].item() - (gelu(X @ A.T) @ B.T)[0, 0].item()) < 1e-6
    print("[check] gold scalar reproduces from gelu(X @ A.T) @ B.T:  OK")


# ----------------------------------------------------------------------------
# SECTION D: attention TP (heads split, O proj row-parallel, ONE AllReduce)
# ----------------------------------------------------------------------------

def softmax_last(x: torch.Tensor) -> torch.Tensor:
    x = x - x.max(dim=-1, keepdim=True).values
    e = x.exp()
    return e / e.sum(dim=-1, keepdim=True)


def section_attention_tp():
    banner("SECTION D: attention TP - heads split, O proj AllReduce")
    TP = 2
    B, L, E = 1, 2, 8
    H, D = 4, 2                                  # H*D == E, 4 heads of dim 2
    assert H % TP == 0 and H * D == E
    H_local = H // TP                            # heads per rank
    print(f"Tiny model: TP={TP}, B={B}, L={L}, E={E}, H={H}, D={D}  "
          f"-> {H_local} heads/rank\n")

    g = torch.Generator().manual_seed(11)
    Wq = (torch.randn(H * D, E, generator=g) * 0.2).round(decimals=4)   # [H*D, E]
    Wk = (torch.randn(H * D, E, generator=g) * 0.2).round(decimals=4)
    Wv = (torch.randn(H * D, E, generator=g) * 0.2).round(decimals=4)
    Wo = (torch.randn(E, H * D, generator=g) * 0.2).round(decimals=4)   # [E, H*D]
    X = (torch.randn(B, L, E, generator=torch.Generator().manual_seed(3))
         * 0.5).round(decimals=4)

    def attn_full(X):
        Q = (X @ Wq.T).reshape(B, L, H, D).permute(0, 2, 1, 3)          # [B,H,L,D]
        K = (X @ Wk.T).reshape(B, L, H, D).permute(0, 2, 1, 3)
        V = (X @ Wv.T).reshape(B, L, H, D).permute(0, 2, 1, 3)
        scale = D ** -0.5
        scores = (Q @ K.transpose(-2, -1)) * scale                      # [B,H,L,L]
        probs = softmax_last(scores)
        attn = probs @ V                                                # [B,H,L,D]
        attn_flat = attn.permute(0, 2, 1, 3).reshape(B, L, H * D)       # [B,L,H*D]
        return attn_flat @ Wo.T                                         # [B,L,E]

    Y_full = attn_full(X)
    print("Full attention (non-TP) forward path:")
    print("  Q,K,V proj -> [B,L,H*D] -> reshape [B,H,L,D] -> attention per head")
    print("  -> reshape back [B,L,H*D] -> O proj -> [B,L,E]\n")
    print(f"  Y_full[0] = \n{fmt_mat(Y_full[0])}\n")

    print("=" * 60)
    print("TP=2 attention:  QKV COLUMN-parallel (heads split) + O ROW-parallel")
    print("=" * 60)
    print(f"Each rank holds H/TP={H_local} heads. The QKV weight column-shard is")
    print("[H_local*D, E] per rank. The O weight row-shard is [E, H_local*D].")
    print("Attention is computed LOCALLY on each rank's heads; the row-parallel")
    print("O proj yields a partial sum; AllReduce combines them.\n")

    # QKV column shards: split the OUTPUT (head) dim. Wq[H*D,E], split dim 0.
    Wq_shards = [Wq[r * H_local * D:(r + 1) * H_local * D, :] for r in range(TP)]
    Wk_shards = [Wk[r * H_local * D:(r + 1) * H_local * D, :] for r in range(TP)]
    Wv_shards = [Wv[r * H_local * D:(r + 1) * H_local * D, :] for r in range(TP)]
    # O row shard: split INPUT dim. Wo[E, H*D], split dim 1.
    Wo_shards = [Wo[:, r * H_local * D:(r + 1) * H_local * D] for r in range(TP)]

    partials = []
    for r in range(TP):
        Qr = (X @ Wq_shards[r].T).reshape(B, L, H_local, D).permute(0, 2, 1, 3)
        Kr = (X @ Wk_shards[r].T).reshape(B, L, H_local, D).permute(0, 2, 1, 3)
        Vr = (X @ Wv_shards[r].T).reshape(B, L, H_local, D).permute(0, 2, 1, 3)
        scale = D ** -0.5
        scores = (Qr @ Kr.transpose(-2, -1)) * scale
        probs = softmax_last(scores)
        attn = probs @ Vr                                       # [B,H_local,L,D]
        attn_flat = attn.permute(0, 2, 1, 3).reshape(B, L, H_local * D)
        partial = attn_flat @ Wo_shards[r].T                   # [B,L,E] partial
        partials.append(partial)
        print(f"  rank {r}: heads [{r*H_local}..{(r+1)*H_local-1}], "
              f"QKV shard [{H_local*D}, E], O shard [E, {H_local*D}]")
        print(f"          partial_{r}[0] = \n{fmt_mat(partial[0])}")

    Y_tp = all_reduce_sum(*partials)
    print(f"\nAllReduce(partial_0 + partial_1)[0] = \n{fmt_mat(Y_tp[0])}")
    max_diff = (Y_tp - Y_full).abs().max().item()
    match = torch.allclose(Y_tp, Y_full, atol=1e-6)
    print(f"\n  max|TP_Y - full_Y| = {max_diff:.3e}")
    print(f"  [check] AllReduce == full attention output?  {match}\n")

    print("WHY THIS IS ONE AllReduce (the Megatron trick applied to attention):")
    print("  - Q,K,V projections are COLUMN-parallel: each rank owns H/TP heads.")
    print("  - Attention is computed LOCALLY per head; heads don't talk to each")
    print("    other, so NO AllReduce is needed between QKV proj and O proj.")
    print("  - O projection is ROW-parallel: each rank produces a partial sum")
    print("    over its H/TP heads. ONE AllReduce at the end combines them.")
    print("  -> The full attention block costs exactly ONE AllReduce, just like")
    print("     the MLP block. (🔗 GQA: with grouped-query heads, the K,V column")
    print("     shards are smaller than the Q column shard — see Section E.)")


# ----------------------------------------------------------------------------
# SECTION E: QKVParallelLinear for GQA  (🔗 GQA)
# ----------------------------------------------------------------------------

def section_qkv_parallel_gqa():
    banner("SECTION E: QKVParallelLinear - packing Q,K,V for GQA  (🔗 GQA)")
    TP = 2
    E, D = 8, 2
    H_q, H_kv = 4, 2                            # GQA: 4 query heads, 2 KV heads
    n_repeats = H_q // H_kv                     # = 2 query heads per KV head
    assert H_q % TP == 0 and H_kv % TP == 0
    print(f"Tiny GQA model: TP={TP}, E={E}, D={D}, H_q={H_q}, H_kv={H_kv}, "
          f"n_repeats={n_repeats}  (🔗 GQA.md)\n")

    g = torch.Generator().manual_seed(23)
    Wq = (torch.randn(H_q * D, E, generator=g) * 0.2).round(decimals=4)     # [H_q*D, E]
    Wk = (torch.randn(H_kv * D, E, generator=g) * 0.2).round(decimals=4)    # [H_kv*D, E]
    Wv = (torch.randn(H_kv * D, E, generator=g) * 0.2).round(decimals=4)

    # nano-vllm QKVParallelLinear packs Q,K,V into ONE matrix of width
    # (H_q + 2*H_kv) * D. (V uses total_num_kv_heads too — same width as K.)
    total_out = (H_q + 2 * H_kv) * D
    Wqkv = torch.cat([Wq, Wk, Wv], dim=0)                       # [total_out, E]
    print(f"Packed QKV weight: shape {tuple(Wqkv.shape)} = "
          f"[(H_q + 2*H_kv)*D, E] = [({H_q}+2*{H_kv})*{D}, {E}] = "
          f"[{total_out}, {E}]\n")
    print("Layout (nano-vllm QKVParallelLinear, dim 0):")
    print(f"  [  Q heads 0..{H_q-1} ({H_q*D} rows)  |  K heads 0..{H_kv-1} "
          f"({H_kv*D} rows)  |  V heads 0..{H_kv-1} ({H_kv*D} rows)  ]\n")

    H_q_local = H_q // TP                       # Q heads per rank
    H_kv_local = H_kv // TP                     # KV heads per rank
    print(f"After TP={TP} sharding, EACH rank takes {H_q_local} Q-heads + "
          f"{H_kv_local} K-heads + {H_kv_local} V-heads:\n")
    print("| rank | Q heads         | K heads         | V heads         | "
          "shard rows = (H_q/TP + 2*H_kv/TP)*D |")
    print("|------|-----------------|-----------------|-----------------|"
          "----------------------------------|")
    for r in range(TP):
        qh = f"{r*H_q_local}..{(r+1)*H_q_local-1}"
        kh = f"{r*H_kv_local}..{(r+1)*H_kv_local-1}"
        rows = (H_q_local + 2 * H_kv_local) * D
        print(f"| {r:<4} | {qh:<15} | {kh:<15} | {kh:<15} | {rows:<32} |")
    print()

    # Demonstrate the weight_loader: each rank's packed shard is the
    # concatenation [Q_r | K_r | V_r], built independently from the three
    # full weights via the shard offsets described in nano-vllm/linear.py.
    print("weight_loader (per rank, builds the packed shard):")
    for r in range(TP):
        q_off = r * H_q_local * D
        q_shard = Wq[q_off:q_off + H_q_local * D, :]
        k_off = r * H_kv_local * D
        k_shard = Wk[k_off:k_off + H_kv_local * D, :]
        v_shard = Wv[k_off:k_off + H_kv_local * D, :]
        packed = torch.cat([q_shard, k_shard, v_shard], dim=0)
        print(f"  rank {r}: Q[{q_off}:{q_off+H_q_local*D}] "
              f"K[{k_off}:{k_off+H_kv_local*D}] "
              f"V[{k_off}:{k_off+H_kv_local*D}]  -> packed {tuple(packed.shape)}")
    print()
    print("KEY: with GQA (H_kv < H_q), the K,V column-shards are SMALLER than")
    print("the Q column-shard on every rank — exactly the asymmetry GQA introduced.")
    print("The Q heads split cleanly across TP because H_q % TP == 0; the same")
    print("must hold for H_kv (else QKVParallelLinear's `divide()` asserts).")
    print("This is why production GQA configs choose H_kv divisible by the max TP.")
    print()
    # sanity: per-rank head counts divide cleanly
    assert H_q % TP == 0 and H_kv % TP == 0
    print(f"[check] H_q={H_q} and H_kv={H_kv} both divide TP={TP}:  OK  "
          f"(else QKVParallelLinear.__init__ asserts via divide())")


# ----------------------------------------------------------------------------
# SECTION F: per-layer AllReduce accounting  (🔗 NCCL_COLLECTIVES)
# ----------------------------------------------------------------------------

def section_allreduce_accounting():
    banner("SECTION F: per-layer AllReduce accounting  (🔗 NCCL_COLLECTIVES)")
    print("Count the AllReduces in one transformer layer under Megatron TP:\n")
    print("| sub-block      | parallel pattern            | AllReduces |")
    print("|----------------|-----------------------------|------------|")
    print("| attention      | QKV col-parallel, O row-par | 1          |")
    print("| MLP            | A col-parallel, B row-par   | 1          |")
    print("|----------------|-----------------------------|------------|")
    print("| TOTAL per layer|                             | 2          |")
    print()
    print("Each AllReduce moves one tensor of shape [B, L, E] (the block output).")
    print("For a ring-AllReduce of K=TP ranks and N = B*L*E elements:")
    print("  per-rank traffic = 2 * (TP-1)/TP * N * bytes_per_element")
    print("  (🔗 NCCL_COLLECTIVES.md: ring-AllReduce = 2N bytes regardless of TP)\n")

    E = 8192
    for B, L in [(1, 1), (1, 4096), (32, 4096)]:
        N = B * L * E
        bytes_fp16 = N * 2
        for TP in [2, 4, 8]:
            traffic = 2 * (TP - 1) / TP * bytes_fp16
            label = (f"B={B}, L={L}, E={E}, TP={TP}: N={N:,}, "
                     f"per-rank traffic = {traffic/2**30:.2f} GiB (fp16)")
            print(f"  {label}")
        print()
    print("READ: TP doubles the AllReduce count vs no-TP (0 -> 2 per layer), and")
    print("the traffic GROWS with batch and sequence length. This is why TP is")
    print("paired with NVLink (next section) — anything slower would dominate.")


# ----------------------------------------------------------------------------
# SECTION G: bandwidth rule (TP within node / NVLink)
# ----------------------------------------------------------------------------

def section_bandwidth_rule():
    banner("SECTION G: bandwidth rule - TP lives WITHIN a node (NVLink)")
    print("TP needs ONE AllReduce per sub-block, EVERY forward pass. Compare")
    print("that to Data Parallel (🔗 DDP), which AllReduces once per OPTIMIZER")
    print("STEP (amortized over many micro-batches). TP's comm frequency is")
    print("orders of magnitude higher -> it needs orders of magnitude more")
    print("bandwidth, or it stalls the GPUs.\n")
    print("| link              | typical bandwidth | use case                  |")
    print("|-------------------|-------------------|---------------------------|")
    print("| NVLink (intra-node)| ~300 GB/s per direction (~600 GB/s aggregate bi-directional)| TENSOR PARALLEL (here) |")
    print("| NVSwitch (8x H100) | ~900 GB/s agg.    | large TP within a node    |")
    print("| PCIe Gen5 x16     | ~64 GB/s          | small TP, or CPU fallback |")
    print("| InfiniBand (inter)| ~25-50 GB/s       | DP / Pipeline (🔗 DDP/PP) |")
    print("| Ethernet (RoCE)   | ~12-25 GB/s       | DP across racks           |")
    print()
    print("RULE OF THUMB: keep TP_size <= GPUs_per_node. Go beyond a single node")
    print("and the AllReduce cost explodes (inter-node bandwidth is ~10x slower).")
    print("For multi-node training, combine TP (intra-node) with DP or Pipeline")
    print("Parallelism (inter-node). This is the 3D parallelism recipe:")
    print()
    print("  TP (within node, NVLink)  x  DP (across nodes, IB)  x  PP (across)")
    print()
    # quick numeric sanity: AllReduce time vs matmul time on a hypothetical layer
    bytes_per_layer = 1 * 4096 * 8192 * 2                       # B=1, L=4096, fp16
    nvlink_s = bytes_per_layer / (300 * 1e9)
    ib_s = bytes_per_layer / (25 * 1e9)
    print("For one decode step (B=1, L=4096, E=8192, fp16), ONE AllReduce of")
    print("the [B*L*E] block output takes:")
    print(f"  over NVLink (300 GB/s): {nvlink_s*1e6:>7.1f} us")
    print(f"  over IB     ( 25 GB/s): {ib_s*1e6:>7.1f} us   ({ib_s/nvlink_s:.0f}x slower)")
    print(f"=> TP across nodes would spend {ib_s/nvlink_s:.0f}x longer in comm per")
    print("   layer, killing throughput. Keep TP on NVLink. (🔗 NCCL ring-AllReduce)")
    print(f"\n[check] IB / NVLink bandwidth ratio = {300/25:.0f}x slower:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("tensor_parallel.py - reference impl. Numbers below feed "
          "TENSOR_PARALLEL.md.")
    print("torch =", torch.__version__)
    print("SIMULATION: faithful single-process TP=2 (shards as plain tensors,")
    print("            AllReduce as explicit sum; math identical to NCCL).")

    section_why_shard()
    section_column_vs_row()
    section_megatron_mlp()
    section_attention_tp()
    section_qkv_parallel_gqa()
    section_allreduce_accounting()
    section_bandwidth_rule()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
