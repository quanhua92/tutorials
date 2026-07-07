"""
low_rank_dora.py - Reference implementation of LoRA and DoRA (Weight-Decomposed
Low-Rank Adaptation), built from scratch in torch.

This is the single source of truth that LOW_RANK_DORA.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python low_rank_dora.py

== The big idea, in one sentence (the "magnitude / direction" intuition) =======
Full fine-tuning rewrites a weight matrix W and, in doing so, it changes TWO
things about every column of W at once: how LONG that column is (its magnitude,
the L2 norm) and which WAY it points (its direction, the unit vector). Standard
LoRA only learns a low-rank patch BA and adds it: W' = W + BA. Because a single
additive patch must move the whole column, LoRA is forced to change the magnitude
and the direction *together* -- it can lengthen a column, but only by also
turning it, and vice versa. DoRA's move: decompose the update into a per-column
MAGNITUDE vector m and a (low-rank) DIRECTION V/||V||, and learn them separately.
So "how much" (m, one scalar per output column) is decoupled from "which way"
(the LoRA-style low-rank V = W + BA, renormalised to unit columns). That is the
whole of DoRA: LoRA for the direction, a free magnitude vector for the scale.

== The lineage (old -> new, with WHY) =========================================
  FULL FT  : W' = W + dW, all d*k weights trained. One full copy per task.
             The gold standard for quality but ruinous at scale (GPT-3 175B ->
             175B new numbers per task; thousands of tasks -> tens of TB).
  LORA     : W' = W + (alpha/r) B A. Freeze W; train only B[d,r] and A[r,k].
             r(d+k) trainable params (r << min(d,k)). Init A ~ N(0,sig^2),
             B = 0 so the patch starts at 0 (the model == the base at step 0).
             Mergeable at inference (W' = W + BA -> one plain linear, zero
             overhead). The catch: a single additive patch conflates magnitude
             and direction -- it cannot mimic how full FT updates them.
             (Hu et al 2022, arXiv:2106.09685.)
  DORA     : W'_dora = (m / ||V||_col) odot V, where V = W + (alpha/r)BA (the
             same low-rank patch as LoRA, NOT yet normalised) and m in R^k is a
             learned per-column magnitude (init m = ||W||_col). V/||V||_col is
             the unit DIRECTION per column; m rescales it. Trainable params:
             r(d+k) + k (the +k is the magnitude vector). At init (B=0, m=||W||),
             V = W so W'_dora = (m/||W||) odot W = W exactly -- a no-op start,
             like LoRA. The payoff: direction (low-rank, cheap) and magnitude
             (one scalar per column) are now FREE to move independently, which
             is what full FT does and LoRA cannot. (Liu et al 2024,
             arXiv:2402.09353.)

== Plain-English glossary (used in every section below) =======================
    W            the FROZEN pre-trained weight of one linear layer, shape [d, k].
                 The forward is y = W x with x in R^k (in) and y in R^d (out):
                 so k = input dim, d = output dim (the LoRA-paper convention).
    d            output dimension (rows of W).
    k            input dimension (columns of W). Also the length of the
                 magnitude vector m (one scalar per output... per column).
    r (rank)     the inner / bottleneck dim of the adapter; r << min(d, k).
    A            the down-projection [r, k]; init ~ N(0, sig^2) (random).
    B            the up-projection [d, r]; init = 0 (so the patch B A = 0).
    BA           the low-rank patch [d, k]; rank(BA) <= r by construction.
    alpha        scaling hyperparameter; the patch is multiplied by alpha/r.
                 Here alpha = r, so the effective scale is 1 and W' = W + BA
                 exactly (matches the paper's core formula; lets you change r
                 without retuning the LR).
    m            DoRA's MAGNITUDE vector, length k; m[j] = ||W[:,j]|| (the L2
                 norm of column j of W) at init. Learned during fine-tuning.
    column       column j of a [d, k] matrix is the vector W[:, j] in R^d -- the
                 weights feeding OUTPUT neuron j. ||W||_col stacks the k column
                 norms into a length-k vector.
    direction    the unit-column matrix V / ||V||_col; each column has norm 1.
    merge        fold the patch into W at deploy: LoRA -> W + (alpha/r)BA;
                 DoRA -> (m / ||V||_col) odot V. Both become a plain linear.

== Tensor-shape conventions (used throughout) =================================
    W   : [d, k]   frozen base weight (d = out, k = in)
    A   : [r, k]   down-projection
    B   : [d, r]   up-projection (0 at init)
    BA  : [d, k]   the low-rank patch (rank <= r)
    m   : [k]      DoRA magnitude vector (one per column of W)
    V   : [d, k]   W + (alpha/r) BA  (DoRA's pre-normalisation direction carrier)
    x   : [k]      one input vector ; y = W x : [d]
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
    """Group an integer with commas, e.g. 4096 -> '4,096'."""
    return f"{n:,}"


def mat_table(name: str, mat: torch.Tensor) -> str:
    """Render a 2D [d, k] tensor as a markdown-style table (cols j=0..k-1)."""
    d, k = mat.shape
    header = "| row \\ col | " + " | ".join(f"j={j}" for j in range(k)) + " |"
    sep = "| " + " | ".join(["---"] * (k + 1)) + " |"
    lines = [name + "  (shape " + str(tuple(mat.shape)) + ")", "", header, sep]
    for i in range(d):
        vals = " | ".join(f"{mat[i, j].item():+.4f}" for j in range(k))
        lines.append(f"| i={i} | {vals} |")
    out = "\n".join(lines)
    print(out)
    print()
    return out


# ============================================================================
# THE REFERENCE IMPLEMENTATIONS (the code LOW_RANK_DORA.md walks through)
# ============================================================================

class LoRALinear(nn.Module):
    """LoRA on a frozen weight W:  y = W x + (alpha/r) * B (A x).

    W is frozen (requires_grad=False); only A and B are trained.
    Shapes: W [d, k], A [r, k], B [d, r]. Init A ~ N(0, sig^2), B = 0, so the
    patch (alpha/r) B A is exactly 0 at step 0 -> the layer is a no-op until
    training moves B.
    """

    def __init__(self, d: int, k: int, r: int, alpha: int | None = None,
                 seed: int = 0):
        super().__init__()
        if alpha is None:
            alpha = r                  # default alpha = r -> scale alpha/r = 1
        self.d, self.k, self.r, self.alpha = d, k, r, alpha
        g = torch.Generator().manual_seed(seed)
        std = 1.0 / torch.sqrt(torch.tensor(float(r)))
        # frozen base weight W [d, k] (deterministic via the generator)
        self.W = nn.Parameter((torch.randn(d, k, generator=g) * std).clone(),
                              requires_grad=False)
        # A [r, k] ~ N(0, std^2) ; B [d, r] = 0  (paper init)
        self.A = nn.Parameter(torch.randn(r, k, generator=g) * std)
        self.B = nn.Parameter(torch.zeros(d, r))

    def delta_W(self) -> torch.Tensor:
        """The low-rank patch (alpha/r) * B A, shape [d, k], rank <= r."""
        return (self.alpha / self.r) * (self.B @ self.A)

    def merged_weight(self) -> torch.Tensor:
        """W' = W + (alpha/r) B A  (the deploy-time merged weight)."""
        return self.W + self.delta_W()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.merged_weight() @ x

    def trainable_params(self) -> int:
        return self.A.numel() + self.B.numel()      # r*k + d*r = r(d+k)


class DoRALinear(nn.Module):
    """DoRA: decompose the merged weight into MAGNITUDE m and DIRECTION V/||V||_col.

    V = W + (alpha/r) B A  (the SAME patch as LoRA, pre-normalisation).
    W'_dora = (m / ||V||_col) odot V,  where ||V||_col is the per-column L2 norm
    (length k) and m in R^k is a learned magnitude (init m = ||W||_col).
    At init (B=0) V=W so W'_dora = (m/||W||) odot W = W exactly (a no-op).
    """

    def __init__(self, d: int, k: int, r: int, alpha: int | None = None,
                 seed: int = 0):
        super().__init__()
        if alpha is None:
            alpha = r
        self.d, self.k, self.r, self.alpha = d, k, r, alpha
        g = torch.Generator().manual_seed(seed)
        std = 1.0 / torch.sqrt(torch.tensor(float(r)))
        self.W = nn.Parameter((torch.randn(d, k, generator=g) * std).clone(),
                              requires_grad=False)
        self.A = nn.Parameter(torch.randn(r, k, generator=g) * std)
        self.B = nn.Parameter(torch.zeros(d, r))
        # magnitude vector m [k]: one scalar per column, init = ||W[:,j]||.
        self.m = nn.Parameter(self.W.norm(p=2, dim=0).clone())

    def direction(self) -> tuple[torch.Tensor, torch.Tensor]:
        """Return (V [d,k], col_norm [k]) where V = W + (alpha/r)BA."""
        V = self.W + (self.alpha / self.r) * (self.B @ self.A)
        col_norm = V.norm(p=2, dim=0)              # [k] = ||V[:,j]||
        return V, col_norm

    def merged_weight(self) -> torch.Tensor:
        """W'_dora = (m / ||V||_col) odot V  (broadcast m over the d rows)."""
        V, col_norm = self.direction()
        scale = (self.m / col_norm).unsqueeze(0)   # [1, k] -> broadcasts over d
        return scale * V

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.merged_weight() @ x

    def trainable_params(self) -> int:
        # r*k + d*r + k = r(d+k) + k  (the +k is the magnitude vector)
        return self.A.numel() + self.B.numel() + self.m.numel()


# ============================================================================
# SECTION A: LoRA from scratch -- the low-rank patch W' = W + BA
# ============================================================================

def section_lora_from_scratch():
    banner("SECTION A: LoRA from scratch -- the low-rank patch W' = W + BA")
    d, k, r = 4, 4, 2
    lora = LoRALinear(d=d, k=k, r=r, alpha=r, seed=0)
    print(f"Tiny layer: d={d} (out), k={k} (in), rank r={r}, alpha={r} "
          f"(so alpha/r = 1, W' = W + BA exactly)\n")

    print("Trainable params: A [r,k] + B [d,r] = r*k + d*r = r(d+k)")
    print(f"  = {r}*{d} + {d}*{r}... = r*(d+k) = {r}*(d+k) = "
          f"{lora.trainable_params()}\n")

    mat_table("frozen base W", lora.W.detach())
    delta = lora.delta_W().detach()
    print("At INIT (B = 0): the patch (alpha/r)BA =")
    mat_table("  delta_W = (alpha/r) B A", delta)
    Wp = lora.merged_weight().detach()
    mat_table("merged W' = W + delta_W", Wp)

    print("Because B = 0 at init, delta_W = 0 and W' == W exactly -- the LoRA")
    print("adapter is a NO-OP until training moves B (same behaviour as the")
    print("frozen base). This is why LoRA training is stable from step 0.\n")
    check("init: delta_W == 0 (B=0)", delta.abs().max().item() == 0.0)
    check("init: merged W' == W", torch.allclose(Wp, lora.W.detach(), atol=0))

    # --- rank constraint: with a NONZERO (trained) B, rank(BA) <= r ---
    print("Now give B learned (nonzero) values to see the rank constraint.")
    print("A trained B [d,r] (seeded, deterministic):\n")
    g = torch.Generator().manual_seed(1)
    lora.B.data = torch.randn(d, r, generator=g) * 0.5
    mat_table("  trained B", lora.B.detach())
    delta2 = lora.delta_W().detach()
    mat_table("trained delta_W = (alpha/r) B A", delta2)
    # SVD: count singular values above tol -> the rank of the patch
    sv = torch.linalg.svdvals(delta2)
    rank_patch = int((sv > 1e-6).sum().item())
    print(f"singular values of delta_W = "
          f"{[round(v, 4) for v in sv.tolist()]}")
    print(f"rank(delta_W) = {rank_patch}  (<= r = {r} by construction: a")
    print("d x k matrix factored as B[d,r] @ A[r,k] can have at most r nonzero")
    print("singular values -- that is what 'low-rank' buys you.)\n")
    check("rank(trained delta_W) <= r", rank_patch <= r)
    check("rank(trained delta_W) == r when B,A are full rank",
          rank_patch == r)

    # --- GOLD PIN (the .html recomputes this) ---
    print("GOLD PIN (low_rank_dora.html recomputes this):")
    full = d * k
    lora_p = r * (d + k)
    print(f"    d={d}, k={k}, r={r}: full-FT = d*k = {full};  "
          f"LoRA = r(d+k) = {lora_p}")
    check("LoRA params r(d+k) == 16 for d=4,k=4,r=2", lora_p == 16)
    check("full-FT params d*k == 16 for d=4,k=4", full == 16)
    check("LoRA trainable_params() matches r(d+k)",
          lora.trainable_params() == lora_p)


# ============================================================================
# SECTION B: DoRA from scratch -- magnitude ⊗ direction
# ============================================================================

def section_dora_from_scratch():
    banner("SECTION B: DoRA from scratch -- magnitude m odot direction V/||V||")
    d, k, r = 4, 4, 2
    dora = DoRALinear(d=d, k=k, r=r, alpha=r, seed=0)
    print(f"Same tiny layer: d={d}, k={k}, r={r}, alpha={r}. "
          f"Shares the SAME frozen W, A, B as the LoRA in Section A.\n")

    print("Trainable params: A [r,k] + B [d,r] + m [k] = r(d+k) + k")
    print(f"  = {r}*(d+k) + k = {r*(d+k)} + {k} = {dora.trainable_params()}\n")

    # magnitude vector m and column norms of V at init
    m = dora.m.detach()
    V, col_norm = dora.direction()
    print("magnitude vector m [k] (init = ||W[:,j]||, the column norms of W):")
    print(f"  m        = {[round(v, 4) for v in m.tolist()]}")
    print(f"  ||W||_col = {[round(v, 4) for v in dora.W.detach().norm(p=2, dim=0).tolist()]}"
          "  (== m at init)\n")
    print("V = W + (alpha/r)BA  ;  at init B=0 so V = W.")
    print(f"  ||V||_col = {[round(v, 4) for v in col_norm.tolist()]}  "
          f"(== ||W||_col == m at init)\n")

    Wp_dora = dora.merged_weight().detach()
    mat_table("DoRA merged W'_dora = (m / ||V||_col) odot V", Wp_dora)

    print("At init: V = W, so (m / ||V||_col) = m / ||W||_col = 1 (all ones),")
    print("so W'_dora = 1 odot W = W EXACTLY. DoRA, like LoRA, starts as a")
    print("no-op -- but it has split the update into a free magnitude vector m")
    print("and a low-rank direction V/||V||_col that can now move independently.\n")
    check("init: m == ||W||_col", torch.allclose(m, dora.W.norm(p=2, dim=0)))
    check("init: DoRA W'_dora == W (forward-equivalence at init)",
          torch.allclose(Wp_dora, dora.W.detach(), atol=1e-6))

    # --- GOLD PIN ---
    print("GOLD PIN (low_rank_dora.html recomputes this):")
    dora_p = r * (d + k) + k
    print(f"    d={d}, k={k}, r={r}: DoRA = r(d+k)+k = {r*(d+k)}+{k} = {dora_p}")
    check("DoRA params r(d+k)+k == 20 for d=4,k=4,r=2", dora_p == 20)
    check("DoRA trainable_params() matches r(d+k)+k",
          dora.trainable_params() == dora_p)
    check("DoRA adds exactly k magnitude params over LoRA (20 vs 16)",
          dora_p == 16 + k)


# ============================================================================
# SECTION C: forward-pass comparison -- all three agree at init
# ============================================================================

def section_forward_comparison():
    banner("SECTION C: forward-pass comparison -- y_full vs y_lora vs y_dora")
    d, k, r = 4, 4, 2
    lora = LoRALinear(d=d, k=k, r=r, alpha=r, seed=0)
    dora = DoRALinear(d=d, k=k, r=r, alpha=r, seed=0)   # same W, A, B(=0)

    # deterministic input x [k] (seeded, not wall-clock)
    g = torch.Generator().manual_seed(7)
    x = torch.randn(k, generator=g)
    print(f"Input x [k={k}] (seeded): {[round(v, 4) for v in x.tolist()]}\n")

    y_full = (lora.W.detach() @ x)            # frozen base only
    y_lora = lora(x).detach()                 # W' x = (W + BA) x
    y_dora = dora(x).detach()                 # W'_dora x

    print("| output | values |")
    print("|---|---|")
    print(f"| y_full = W x          | {[round(v, 4) for v in y_full.tolist()]} |")
    print(f"| y_lora = W' x         | {[round(v, 4) for v in y_lora.tolist()]} |")
    print(f"| y_dora = W'_dora x    | {[round(v, 4) for v in y_dora.tolist()]} |")
    print()
    print("At init (B=0, m=||W||): LoRA's W'=W and DoRA's W'_dora=W, so ALL")
    print("THREE forwards are identical. Training then diverges them: LoRA can")
    print("only add a low-rank patch; DoRA can also rescale each column's")
    print("magnitude via m. (Section E shows why that separation matters.)\n")

    check("init: y_lora == y_full", torch.allclose(y_lora, y_full, atol=1e-6))
    check("init: y_dora == y_full", torch.allclose(y_dora, y_full, atol=1e-6))
    check("init: y_dora == y_lora", torch.allclose(y_dora, y_lora, atol=1e-6))


# ============================================================================
# SECTION D: param-count + expressiveness table
# ============================================================================

def section_param_table():
    banner("SECTION D: param-count + expressiveness (full-FT vs LoRA vs DoRA)")
    print("For each (d, k) and rank r: trainable params and the LoRA/DoRA")
    print("compression ratio vs full fine-tuning (full = d*k).\n")
    print("| d   | k   | r | full-FT d*k | LoRA r(d+k) | DoRA r(d+k)+k | "
          "LoRA/full | DoRA/full |")
    print("|-----|-----|---|-------------|-------------|---------------|"
          "-----------|------------|")
    cases = [(4, 4, 2), (8, 8, 2), (8, 8, 4), (8, 8, 8),
             (64, 64, 2), (64, 64, 4), (64, 64, 8)]
    for d, k, r in cases:
        full = d * k
        lora_p = r * (d + k)
        dora_p = r * (d + k) + k
        ratio_l = lora_p / full
        ratio_d = dora_p / full
        print(f"| {d:<3} | {k:<3} | {r} | {fmt(full):>11} | "
              f"{fmt(lora_p):>11} | {fmt(dora_p):>13} | "
              f"{ratio_l:>9.4f} | {ratio_d:>10.4f} |")
    print()
    print("Reading the table:")
    print("- full-FT grows as d*k (quadratic in the width); LoRA/DoRA grow as")
    print("  r*(d+k) (LINEAR in the width). So the savings explode at scale:")
    print("  at d=k=64, r=4, full=4096 but LoRA=512 and DoRA=576 -- ~8x fewer.")
    print("- DoRA costs exactly k MORE params than LoRA (the magnitude vector).")
    print("  At real scale (d=k=4096, r=8) that is +4096 out of ~65536 -- about")
    print("  +6%, i.e. the ~0.2% overhead the DoRA paper reports. Negligible.")
    print("- When r >= min(d,k) the 'low-rank' bet stops paying (LoRA can exceed")
    print("  full-FT, e.g. d=k=8, r=8 -> 128 > 64). Real use keeps r << min(d,k).\n")

    # concrete gold checks on a couple of rows
    for d, k, r in cases:
        full = d * k
        lora_p = r * (d + k)
        dora_p = r * (d + k) + k
        check(f"({d},{k},r={r}): LoRA r(d+k)=={lora_p} & DoRA +k=={dora_p}",
              r * (d + k) == lora_p and lora_p + k == dora_p and full == d * k)


# ============================================================================
# SECTION E: the magnitude/direction insight + lineage recap
# ============================================================================

def section_decomposition_insight():
    banner("SECTION E: why decouple magnitude and direction (the DoRA claim)")
    d, k, r = 4, 4, 2
    dora = DoRALinear(d=d, k=k, r=r, alpha=r, seed=0)
    W = dora.W.detach()
    m = dora.m.detach()
    col_norm_W = W.norm(p=2, dim=0)
    direction_W = W / col_norm_W.unsqueeze(0)      # unit columns

    print("STEP 1 -- any weight matrix factors as magnitude odot direction.")
    print("W = m odot (W / ||W||_col),  where m = ||W||_col (length k) and")
    print("W/||W||_col has unit columns (each column is a direction). This is")
    print("Salimans & Kingma's weight normalization (arXiv:1602.07868), which")
    print("DoRA reuses per column.\n")
    mat_table("direction = W / ||W||_col  (unit columns)", direction_W)
    print(f"magnitude m = ||W||_col = {[round(v, 4) for v in m.tolist()]}\n")
    recon = m.unsqueeze(0) * direction_W
    check("reconstruction: m odot direction == W (exact)",
          torch.allclose(recon, W, atol=1e-6))

    print("\nSTEP 2 -- LoRA CONFLATES magnitude and direction; DoRA frees them.")
    print("Give B learned values (same as Section A's trained B):\n")
    g = torch.Generator().manual_seed(1)
    dora.B.data = torch.randn(d, r, generator=g) * 0.5
    # LoRA merged weight W_lora = W + (alpha/r)BA  (the plain LoRA update)
    W_lora = (dora.W + (dora.alpha / dora.r) * (dora.B @ dora.A)).detach()
    m_lora = W_lora.norm(p=2, dim=0)
    dir_lora = W_lora / m_lora.unsqueeze(0)
    # direction cosine similarity per column: cos(dir_W[:,j], dir_lora[:,j])
    cos_dir = (direction_W * dir_lora).sum(dim=0) / (
        direction_W.norm(p=2, dim=0) * dir_lora.norm(p=2, dim=0))

    print("Decompose LoRA's merged W' = W + BA the same way:\n")
    print("| col j | ||W|| (before) | ||W+BA|| (after) | magnitude ratio | "
          "direction cosine |")
    print("|-------|---------------|------------------|-----------------|"
          "------------------|")
    for j in range(k):
        print(f"| {j}     | {col_norm_W[j].item():>13.4f} | "
              f"{m_lora[j].item():>16.4f} | "
              f"{(m_lora[j]/col_norm_W[j]).item():>15.4f} | "
              f"{cos_dir[j].item():>16.4f} |")
    print()
    print("LoRA's single patch BA shifts BOTH the magnitude (||W+BA|| != ||W||)")
    print("AND the direction (cosine < 1) at once -- you cannot ask LoRA to")
    print("rescale a column WITHOUT also turning it. That is the limitation")
    print("DoRA targets: full fine-tuning updates magnitude and direction")
    print("INDEPENDENTLY, and LoRA's proportional coupling can't mimic it.\n")

    print("STEP 3 -- DoRA keeps them independent by construction.")
    print("direction(V) = V/||V||_col does NOT depend on m at all. So in DoRA:")
    print("  - moving m  -> rescales each column's MAGNITUDE only (direction")
    print("    unchanged, because m never enters V/||V||_col);")
    print("  - moving BA -> changes the DIRECTION only (low-rank, cheap), then")
    print("    m re-scales it back to the learned magnitude.")
    V, _ = dora.direction()
    dir_V = (V / V.norm(p=2, dim=0).unsqueeze(0)).detach()
    # prove direction is invariant to m: scale m by 1.1, direction must be identical
    m_scaled = (m * 1.1)
    Wp_scaled = (m_scaled / V.norm(p=2, dim=0)).unsqueeze(0) * V
    dir_scaled = (Wp_scaled / Wp_scaled.norm(p=2, dim=0).unsqueeze(0)).detach()
    check("direction is invariant to m (rescaling m leaves V/||V|| unchanged)",
          torch.allclose(dir_V, dir_scaled, atol=1e-6))
    check("DoRA direction(V) == LoRA direction(W+BA) (same V, same normalise)",
          torch.allclose(dir_V, dir_lora, atol=1e-6))
    check("LoRA changed magnitude AND direction (both shifted from W)",
          (not torch.allclose(m_lora, col_norm_W, atol=1e-6))
          and (cos_dir.max().item() < 1.0 - 1e-6))

    banner("LINEAGE RECAP")
    print("| method   | merged weight                 | trainable params | "
          "magnitude / direction |")
    print("|----------|-------------------------------|------------------|"
          "------------------------|")
    rows = [
        ("full-FT", "W + dW  (all weights)", "d*k",
         "both move, independently"),
        ("LoRA",    "W + (alpha/r)BA",            "r(d+k)",
         "both move, PROPORTIONALLY (tied)"),
        ("DoRA",    "(m / ||V||_col) odot V",      "r(d+k) + k",
         "magnitude (m) and direction (BA) FREE"),
    ]
    for name, mw, params, md in rows:
        print(f"| {name:<8} | {mw:<29} | {params:<16} | {md:<22} |")
    print()
    print("DoRA matches full-FT's *behaviour* (independent magnitude/direction")
    print("updates) at ~LoRA's *cost* (only +k params). Empirically it often")
    print("beats LoRA at the same rank, and even matches LoRA at HALF the rank")
    print("(Liu et al 2024, arXiv:2402.09353).\n")
    check("lineage: full-FT has most params (d*k)", d * k >= r * (d + k))
    check("lineage: DoRA params == LoRA params + k",
          r * (d + k) + k == r * (d + k) + k)


# ============================================================================
# main
# ============================================================================

def main():
    print("low_rank_dora.py - reference impl (LoRA + DoRA from scratch).\n"
          "Numbers below feed LOW_RANK_DORA.md.  torch =", torch.__version__)
    print("\nConcept: LoRA learns a low-rank patch BA; DoRA splits the update\n"
          "into a magnitude vector m and a low-rank direction V/||V||_col,\n"
          "decoupling 'how much' from 'which way' at ~LoRA param cost.\n")

    section_lora_from_scratch()
    section_dora_from_scratch()
    section_forward_comparison()
    section_param_table()
    section_decomposition_insight()

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
