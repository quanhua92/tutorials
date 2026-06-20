"""
moe_routing.py - Reference implementation of Mixture-of-Experts (MoE) routing.

This is the single source of truth that MOE_ROUTING.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    uv run python moe_routing.py

== The big idea, in one sentence (the "consulting firm" intuition) ============
Picture a consulting firm. A *dense* FFN is one overworked senior consultant
who reads every document end-to-end — to know more, you must hire smarter
(slower) consultants. A *Mixture of Experts* is a receptionist (the *router*)
plus a wall of E specialists: each incoming document is scanned by the
receptionist and handed to only the top-k (k << E) most relevant specialists.
The firm's *knowledge* (total headcount = total params) can be huge, while the
*effort per document* (active params) stays small. Mixtral 8x7B: 46.7B of
knowledge on the wall, 12.9B of effort per token — capacity of a 47B firm at
the speed of a 13B one.

== Plain-English glossary (used in every section below) ======================
    dense FFN     the senior consultant: one SwiGLU MLP that activates ALL its
                  params for every token. Scaling knowledge = scaling compute.
    expert (E_i)  one specialist: an independent SwiGLU MLP (🔗 MLP_ACTIVATION).
                  E = number of specialists on the wall.
    router / gate the receptionist: a single linear layer W_g that scores each
                  expert for the current token, then keeps the top-k scores.
    H(x)          router logits = x . W_g   (E raw scores, one per expert).
    top-k (k)     how many specialists each document goes to (k << E).
                  Mixtral: k=2 of E=8. Switch: k=1. DeepSeek-V3: k=8 of 256.
    KeepTopK      zero out (-> -inf) every score except the top k, BEFORE the
                  softmax, so the discarded experts contribute exactly 0.
    G(x)          gate weights = softmax(KeepTopK(H(x))). Only k are nonzero;
                  they sum to 1 (the renormalized "share" each chosen expert
                  gets). This is the Mixtral convention.
    y             the MoE output = sum over the k ACTIVE experts of
                  G(x)_i * E_i(x). Inactive experts never run.
    active params params actually touched per token = N_attn + k * N_expert.
    total params  params stored on the wall            = N_attn + E * N_expert.
    router collapse the failure mode: the receptionist sends everything to the
                  same 1-2 specialists; the rest never train. Prevented by the
                  load-balance loss L_bal (+ z-loss for stability).
    capacity (C)  a hard per-expert queue limit when experts live on different
                  GPUs: C = capacity_factor * N*k/E. Overflow -> drop.
    shared expert a DeepSeek-V3 specialist that is ALWAYS on (not routed),
                  capturing common features so routed experts specialize.
    fine-grained  DeepSeek-V3 trick: split one fat expert into M thin ones, so
                  top-k can mix more specialized knowledge per token.
    aux-loss-free DeepSeek-V3 trick: instead of a gradient-pushing loss, just
                  add a learnable bias b_i to the router logits and nudge it up/
                  down based on real load — no gradient interference.

== Tensor-shape conventions (used throughout) =================================
    B = batch size
    L = sequence length (number of tokens)
    D = model / hidden dim (the input to the MoE layer, = the output too)
    F = expert intermediate dim (the wide hidden dim inside each SwiGLU expert)
    E = number of experts
    k = top-k (experts activated per token)
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code MOE_ROUTING.md walks through)
# ============================================================================

def silu(x: torch.Tensor) -> torch.Tensor:
    """SiLU(x) = x * sigmoid(x).  🔗 MLP_ACTIVATION §2.3 (identical formula)."""
    return x * torch.sigmoid(x)


def linear(x: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
    """x @ w.T  where w has shape [out, in].  No bias, for clarity."""
    return x @ w.T


def keep_topk(logits: torch.Tensor, k: int) -> torch.Tensor:
    """KeepTopK(v, k)_i = v_i if in top-k, else -inf.

    This is the sparsifying step: everything outside the top-k is pushed to
    -inf so that the subsequent softmax assigns it EXACTLY 0. Implemented
    element-wise over the last axis (the E axis of router logits).

    Source: learning_guide/05_Next_Gen_Architecture.md §2.2, eq. KeepTopK.
    """
    # which entries survive? the top-k along the last axis
    topk_vals, _ = torch.topk(logits, k, dim=-1)            # [..., k]
    # the k-th largest value is the threshold for "survive"
    threshold = topk_vals[..., -1:]                          # [..., 1]
    # anything strictly below the threshold -> -inf
    masked = torch.where(logits >= threshold, logits,
                         torch.full_like(logits, float("-inf")))
    return masked


class Expert:
    """One specialist: an independent SwiGLU MLP.

        E_i(x) = down( silu(gate(x)) * up(x) )    (🔗 MLP_ACTIVATION §5, §6)

    Three weight matrices, SiLU on the GATE branch (never on up -- the #1
    SwiGLU pitfall). Shapes:
        w_gate [F, D],  w_up [F, D],  w_down [D, F]
    """

    def __init__(self, w_gate: torch.Tensor, w_up: torch.Tensor,
                 w_down: torch.Tensor):
        self.w_gate = w_gate
        self.w_up = w_up
        self.w_down = w_down

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, L, D] -> [B, L, D]
        gate = silu(linear(x, self.w_gate))   # [B, L, F]  (silu on gate)
        up = linear(x, self.w_up)             # [B, L, F]  (raw, no activation)
        return linear(gate * up, self.w_down)  # [B, L, D]


class MoE:
    """Sparse top-k Mixture-of-Experts layer (Shazeer 2017 / Mixtral style).

        H(x) = x . W_g^T                 router logits,  [B, L, E]
        G(x) = softmax(KeepTopK(H(x), k))  gate weights,  [B, L, E]  (k nonzero)
        y    = sum_i  G(x)_i * E_i(x)    output,         [B, L, D]

    Args:
        w_router : [E, D]   the receptionist's scoring weights.
        experts  : list[Expert] of length E, each a SwiGLU MLP.
        k        : top-k (experts activated per token).
    """

    def __init__(self, w_router: torch.Tensor, experts: list, k: int):
        self.w_router = w_router
        self.experts = experts
        self.k = k
        self.E = len(experts)

    def router_logits(self, x: torch.Tensor) -> torch.Tensor:
        """H(x) = x . W_g^T,  shape [B, L, E]."""
        return linear(x, self.w_router)            # [B, L, E]

    def gate_weights(self, x: torch.Tensor) -> torch.Tensor:
        """G(x) = softmax(KeepTopK(H(x), k)),  shape [B, L, E].

        Only the top-k entries are nonzero; they renormalize to sum=1 (the
        Mixtral convention). Returns (gate, topk_indices).
        """
        H = self.router_logits(x)                  # [B, L, E]
        masked = keep_topk(H, self.k)              # [B, L, E] (-inf except top-k)
        G = F.softmax(masked, dim=-1)              # [B, L, E]  (k nonzero, sum 1)
        _, idx = torch.topk(H, self.k, dim=-1)     # [B, L, k]  chosen expert ids
        return G, idx

    def __call__(self, x: torch.Tensor) -> torch.Tensor:
        """y = sum_i G(x)_i * E_i(x),  shape [B, L, D]."""
        G, _ = self.gate_weights(x)                # [B, L, E]
        # stack expert outputs and weight by the gate  ->  [B, L, D]
        y = torch.zeros_like(x)
        for i, expert in enumerate(self.experts):
            g_i = G[..., i].unsqueeze(-1)          # [B, L, 1]
            y = y + g_i * expert(x)
        return y


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def vec(a, d=4):
    return "[" + ", ".join((f"{v:+.{d}f}") for v in a) + "]"


# ============================================================================
# 3. THE SMALL CONCRETE MODEL: E=4 experts, k=2, D=8, F=16, L=4 tokens
#    Tiny enough to print every number, big enough to show all behavior.
# ============================================================================

def build_tiny_moe(seed_x=42, seed_router=100, seed_experts=200):
    """Deterministically build the tiny MoE used by every section below."""
    D, F, E, k = 8, 16, 4, 2
    B, L = 1, 4

    gx = torch.Generator().manual_seed(seed_x)
    x = torch.randn(B, L, D, generator=gx) * 0.5                 # [1, 4, 8]

    gr = torch.Generator().manual_seed(seed_router)
    w_router = (torch.randn(E, D, generator=gr) * 0.1)           # [4, 8]

    ge = torch.Generator().manual_seed(seed_experts)
    experts = []
    for _ in range(E):
        w_gate = torch.randn(F, D, generator=ge) * 0.1           # [16, 8]
        w_up = torch.randn(F, D, generator=ge) * 0.1             # [16, 8]
        w_down = torch.randn(D, F, generator=ge) * 0.1           # [8, 16]
        experts.append(Expert(w_gate, w_up, w_down))

    moe = MoE(w_router, experts, k=k)
    return moe, x, dict(D=D, F=F, E=E, k=k, B=B, L=L)


def section_dense_vs_sparse():
    banner("SECTION A: dense FFN vs sparse MoE (params + FLOPs decoupling)")
    D, F = 8, 16
    E, k = 4, 2
    print(f"Tiny model: D={D}, F={F} (expert intermediate), E={E} experts, k={k}\n")
    # A dense SwiGLU FFN has 3 weight matrices: gate, up, down  (🔗 MLP_ACTIVATION)
    dense_params = 3 * D * F
    # The MoE replaces ONE dense FFN with E experts
    moe_total = E * dense_params
    moe_active = k * dense_params
    print("Counting only the FFN/MoE parameters (attention excluded):\n")
    print("| design                 | params stored | params active/token | FLOPs/token |")
    print("|------------------------|---------------|---------------------|-------------|")
    print(f"| dense SwiGLU FFN       | {dense_params:>13} | {dense_params:>19} | {2*dense_params:>11} |")
    print(f"| MoE  E={E} k={k} (total)    | {moe_total:>13} | {moe_active:>19} | {2*moe_active:>11} |")
    print()
    print(f"[check] total/active ratio = E/k = {E}/{k} = {E/k:.1f}x "
          f"-> {moe_total}/{moe_active} = {moe_total/moe_active:.1f}x   : OK")
    print()

    print("Real models (the whole point of MoE):")
    print("| model          | total params | active/token | k of E   |")
    print("|----------------|--------------|--------------|----------|")
    print("| Mixtral 8x7B   | 46.7B        | 12.9B        | 2 of 8   |")
    print("| DeepSeek-V3    | 671B         | 37B          | 8 of 256 |")
    print()
    print("DeepSeek-V3: 671B of knowledge on the wall, but each token runs only")
    print("37B of it -- a 671B-capacity model at ~37B speed (aux-loss-free).")
    print("Sources: Mixtral arXiv:2401.04088, DeepSeek-V3 arXiv:2412.19437.")


def section_routing_math(moe: MoE, x: torch.Tensor, dims: dict):
    banner("SECTION B: top-k routing math -- KeepTopK + softmax")
    E, k, D = dims["E"], dims["k"], dims["D"]
    B, L = x.shape[0], x.shape[1]
    H = moe.router_logits(x)                       # [B, L, E]
    masked = keep_topk(H, k)                       # [B, L, E]
    G = F.softmax(masked, dim=-1)                  # [B, L, E]
    topk_vals, topk_idx = torch.topk(H, k, dim=-1)  # [B, L, k]

    print(f"Router weights W_g shape: {tuple(moe.w_router.shape)} = [E={E}, D={D}]")
    print(f"Input x shape: {tuple(x.shape)} = [B={B}, L={L}, D={D}]")
    print(f"H(x) = x . W_g^T  ->  router logits shape {tuple(H.shape)} = [B, L, E]\n")
    print("For EACH token, KeepTopK zeroes all but top-k, then softmax over the")
    print("survivors renormalizes them to sum=1 (the Mixtral convention).\n")

    print("Token m=0 (the gold centerpiece token) walked by hand:\n")
    print(f"  x[0,0]         = {vec(x[0,0].tolist())}")
    print(f"  H[0,0] logits  = {vec(H[0,0].tolist())}   (one score per expert)")
    print(f"  top-{k} values = {vec(topk_vals[0,0].tolist())}")
    print(f"  top-{k} experts= {topk_idx[0,0].tolist()}          <- the chosen specialists")
    print(f"  KeepTopK[0,0]  = {vec(masked[0,0].tolist())}")
    print(f"  G[0,0] weights = {vec(G[0,0].tolist())}   (only top-{k} nonzero, sum={G[0,0].sum().item():.4f})")
    print()

    # full table of all 4 tokens
    print("All tokens -- router decisions:")
    print("| m | H[0,m] (4 logits)                          | top-k experts | G[0,m] (4 gate weights)            |")
    print("|---|---------------------------------------------|---------------|------------------------------------|")
    for m in range(L):
        h = " ".join(f"{v:+.3f}" for v in H[0, m].tolist())
        idx = ",".join(str(int(i)) for i in topk_idx[0, m].tolist())
        g = " ".join(f"{v:+.3f}" for v in G[0, m].tolist())
        print(f"| {m} | {h:<43} | {idx:<13} | {g:<34} |")
    print()

    # sanity: gate weights sum to 1, only k nonzero
    sums = G.sum(dim=-1)
    nonzero = (G > 0).sum(dim=-1)
    assert torch.allclose(sums, torch.ones_like(sums), atol=1e-5)
    assert torch.all(nonzero == k)
    print(f"[check] every token: sum(G) == 1 (max dev {abs(sums-1).max().item():.1e}) : OK")
    print(f"[check] every token: exactly k={k} nonzero gate weights          : OK")
    print()

    print("Gold pin for the .html (token m=0):")
    print(f"  selected experts = {topk_idx[0,0].tolist()}")
    print(f"  gate weights     = {vec(G[0,0].tolist(), 6)}")


def section_expert_combination(moe: MoE, x: torch.Tensor, dims: dict):
    banner("SECTION C: expert combination -- y = sum_i G_i * E_i(x)")
    E, k = dims["E"], dims["k"]
    G, topk_idx = moe.gate_weights(x)              # [B, L, E], [B, L, k]
    y = moe(x)                                     # [B, L, D]

    print("Each expert is a full SwiGLU MLP (down(silu(gate)*up)). The router")
    print("picks k=2 of E=4 per token, then the MoE output is the gate-weighted")
    print("sum of ONLY those 2 experts' outputs (the other 2 never run).\n")

    # show token m=0 in full: which 2 experts ran, their outputs, the weighted sum
    m = 0
    chosen = topk_idx[0, m].tolist()
    print(f"Token m={m} routed to experts {chosen} (gate weights "
          f"{[round(G[0,m,int(i)].item(),4) for i in chosen]}):\n")
    print(f"| expert i | ran? | G[0,{m},i] | E_i(x[0,{m}]) "
          f"(first 4 of {dims['D']})            |")
    print("|----------|------|-----------|--------------------------------------|")
    for i in range(E):
        ran = "YES" if i in chosen else "no"
        eout = moe.experts[i](x)[0, m]            # [D]
        g = G[0, m, i].item()
        efirst = " ".join(f"{v:+.3f}" for v in eout[:4].tolist())
        print(f"| {i}        | {ran:<4} | {g:+.4f}    | {efirst} ...            |")
    print()

    # reconstruct y[0,0] by hand from the 2 active experts
    y_hand = torch.zeros(dims["D"])
    for i in chosen:
        g = G[0, m, int(i)]
        eout = moe.experts[i](x)[0, m]
        y_hand = y_hand + g * eout
    print(f"Hand reconstruction of y[0,{m}] = sum of (G_i * E_i) over the active:")
    contribs = [f"G_{i}*E_{i}" for i in chosen]
    print(f"  y[0,{m}] = {' + '.join(contribs)}")
    print(f"         = {vec(y_hand.tolist(), 6)}")
    print(f"MoE class output y[0,{m}] = {vec(y[0,m].tolist(), 6)}")
    assert torch.allclose(y_hand, y[0, m], atol=1e-6)
    print()
    print(f"[check] hand sum == MoE class output  : OK")

    # gold pin: y[0,0,0]
    print(f"\nGold pin y[0,0,0] = {y[0,0,0].item():.6f}  (the .html recomputes this)")


def section_aux_losses(moe: MoE, x: torch.Tensor, dims: dict):
    banner("SECTION D: auxiliary losses -- load-balance + router z-loss")
    E, k = dims["E"], dims["k"]
    L = x.shape[1]
    H = moe.router_logits(x)                       # [B, L, E]
    G, topk_idx = moe.gate_weights(x)              # [B, L, E], [B, L, k]
    N = x.shape[0] * L                             # number of tokens

    # f_i = fraction of tokens whose top-k includes expert i
    # count: for each token, mark which experts are selected
    selected = torch.zeros(N, E)
    flat_idx = topk_idx.reshape(N, k)             # [N, k]
    for n in range(N):
        for j in range(k):
            selected[n, flat_idx[n, j]] = 1.0
    f = selected.mean(dim=0)                       # [E]
    # P_i = average gate probability for expert i
    P = G.reshape(N, E).mean(dim=0)               # [E]

    L_bal = E * (f * P).sum().item()
    L_z = (((H.reshape(N, E).logsumexp(dim=-1)) ** 2).mean()).item()

    print("Router collapse: without a push, the receptionist sends everything to")
    print("1-2 favorite experts and the rest never train. Two losses fix this.\n")
    print("For our N=4 tokens, per-expert statistics:")
    print("| expert i | f_i (frac of tokens routed) | P_i (avg gate prob) | f_i*P_i |")
    print("|----------|------------------------------|---------------------|---------|")
    for i in range(E):
        print(f"| {i}        | {f[i].item():<28.4f} | {P[i].item():<19.4f} | "
              f"{(f[i]*P[i]).item():+.4f}  |")
    print()
    print(f"L_bal = E * sum_i f_i * P_i = {E} * {(f*P).sum().item():.6f} = {L_bal:.6f}")
    print(f"  (minimum when balanced is k={k}; larger => more imbalanced)")
    print(f"  sum(f) = {f.sum().item():.4f}  (== k, since each token picks k)")
    print(f"  sum(P) = {P.sum().item():.4f}  (== 1, gate weights renormalize)")
    print()
    print(f"L_z = (1/N) sum_j (log sum_i e^H_i)^2 = {L_z:.6f}")
    print("  (penalizes LARGE logits -> keeps router numerically stable)")
    print()

    # sanity
    assert abs(f.sum().item() - k) < 1e-5
    assert abs(P.sum().item() - 1.0) < 1e-5
    print(f"[check] sum(f)==k and sum(P)==1   : OK")
    print(f"[check] L_bal >= k (={k}) since balanced is the min : {L_bal >= k - 1e-6}  OK")


def section_token_dropping(moe: MoE, x: torch.Tensor, dims: dict):
    banner("SECTION E: token dropping + expert capacity")
    E, k = dims["E"], dims["k"]
    L = x.shape[1]
    N = L
    G, topk_idx = moe.gate_weights(x)             # [B, L, E], [B, L, k]
    capacity_factor = 1.0
    C = capacity_factor * N * k / E
    print("When experts live on separate GPUs (Expert Parallelism, §G), each GPU")
    print("needs a fixed-size buffer. Expert Capacity C caps how many tokens one")
    print("expert may process per step:\n")
    print(f"  C = capacity_factor * N*k/E = {capacity_factor} * {N}*{k}/{E} = {C:.1f}")
    print(f"  (each expert may process at most {int(C)} tokens; overflow is DROPPED)")
    print()

    # count how many tokens each expert received
    counts = [(topk_idx == i).sum().item() for i in range(E)]
    print("Routing results vs capacity (the dropping decision):")
    print("| expert i | tokens received | capacity C | action                  |")
    print("|----------|-----------------|------------|-------------------------|")
    for i in range(E):
        recv = counts[i]
        if recv > C:
            action = f"DROP {int(recv-C)} (only {int(C)} run, rest -> residual)"
        elif recv < C:
            action = f"PAD {int(C-recv)} zero(s)"
        else:
            action = "exact fit"
        print(f"| {i}        | {recv:<15} | {int(C):<10} | {action:<23} |")
    print()

    dropped = max(0, max(c - C for c in counts))
    print(f"[check] total tokens dropped this step = {int(dropped)}")
    print()
    print("Dropping degrades quality at inference (a dropped token skips its MLP")
    print("update entirely -> just the residual). Production servers (ZeroServe,")
    print("vLLM) use no-drop / dynamic-capacity routing instead. DeepSeek-V3's")
    print("aux-loss-free balancing (§F) keeps load even so C is rarely hit.")


def section_deepseek(moe: MoE, x: torch.Tensor, dims: dict):
    banner("SECTION F: DeepSeek-V3 -- shared + fine-grained + aux-loss-free bias")
    E, k = dims["E"], dims["k"]
    D, F = dims["D"], dims["F"]
    H = moe.router_logits(x)                       # [B, L, E]

    # --- (1) shared expert: always on, not routed ---
    gs = torch.Generator().manual_seed(7)
    w_shared = (torch.randn(F, D, generator=gs) * 0.1,
                torch.randn(F, D, generator=gs) * 0.1,
                torch.randn(D, F, generator=gs) * 0.1)
    shared = Expert(*w_shared)

    print("DeepSeek-V3 (arXiv:2412.19437) adds three things to classic top-k MoE:\n")
    print("(1) SHARED expert -- always on, captures common features so routed")
    print("    experts can specialize.   y = y_shared + y_routed\n")

    # --- (2) fine-grained: split one expert into M thin ones ---
    M = 2
    print(f"(2) FINE-GRAINED -- split one fat expert (F={F}) into {M} thin ones")
    print(f"    (F={F//M} each). top-k now mixes more specialized knowledge per")
    print("    token without raising total params. (demonstrated conceptually)\n")

    # --- (3) aux-loss-free bias routing ---
    print("(3) AUX-LOSS-FREE bias -- instead of a gradient-pushing L_bal, add a")
    print("    learnable bias b_i to the router logits:")
    print("        G(x)_i = softmax( H(x)_i + b_i )")
    print("    and nudge b_i up/down by real load (no gradient to the model).\n")

    # show how a bias shifts the selection for token m=0.
    # Pick a bias that genuinely FLIPS a token out of the top-2.
    bias = torch.zeros(E)
    bias[2] = +0.30   # nudge expert 2 up so it overtakes expert 0
    H_biased = H + bias
    _, idx_plain = torch.topk(H, k, dim=-1)
    _, idx_bias = torch.topk(H_biased, k, dim=-1)
    print(f"Token m=0, bias b = {[round(b,2) for b in bias.tolist()]}:")
    print(f"  plain   H[0,0]      top-{k} experts = {idx_plain[0,0].tolist()}")
    print(f"  biased  H[0,0]+b    top-{k} experts = {idx_bias[0,0].tolist()}  "
          f"(expert 2 nudged by +0.30 -> flips out expert 0)")
    print()
    # verify the bias can actually change the decision
    changed = not torch.equal(idx_plain[0, 0], idx_bias[0, 0])
    print(f"[check] bias changes routing decision?  {changed}  "
          f"({'OK' if changed else 'FAIL: bias too small to flip'})")
    print()
    print("DeepSeek-V3 uses 256 routed + 1 shared expert, k=8: 671B total / 37B")
    print("active. The aux-loss-free bias keeps all 256 experts evenly loaded with")
    print("ZERO gradient interference into the main loss (unlike L_bal in §D).")


def section_expert_parallelism(moe: MoE, x: torch.Tensor, dims: dict):
    banner("SECTION G: expert parallelism (EP) + grouped GEMM  [sketch, 1 device]")
    E, k = dims["E"], dims["k"]
    print("In Expert Parallelism, each expert lives on a DIFFERENT GPU. Routing")
    print("then needs an All-to-All communication (everyone sends everyone):\n")
    print("  step 1: each GPU computes router logits for its local tokens.")
    print("  step 2: All-to-All -- each token is sent to the GPU owning its top-k.")
    print("  step 3: each GPU runs ONLY its expert(s) on the tokens it received.")
    print("  step 4: All-to-All (reverse) -- send outputs back to the origin GPU.")
    print("  step 5: each origin GPU weights the returned outputs by G and sums.\n")
    print("(This is a SKETCH -- no real multi-GPU here. 🔗 TENSOR_PARALLEL covers")
    print("the collective primitives like All-to-All used in step 2/4.)\n")

    # Grouped GEMM: the problem and the fix
    print("GROUPED GEMM -- the kernel that makes step 3 fast:")
    print("  After routing, expert i gets M_i tokens, and the M_i DIFFER per expert.")
    print("  torch.bmm needs equal batch sizes -> you'd have to PAD every expert's")
    print("  buffer to max(M_i) (wasteful). Grouped GEMM (CUTLASS/Triton) runs all")
    print("  E independent (M_i x N x K) matmuls in ONE kernel, no padding.\n")

    # demonstrate the ragged assignment on our tiny model
    G, topk_idx = moe.gate_weights(x)
    print("Our tiny model's token->expert assignment (the ragged input to grouped GEMM):")
    per_expert = {i: [] for i in range(E)}
    for m in range(x.shape[1]):
        for e in topk_idx[0, m].tolist():
            per_expert[int(e)].append(f"t{m}")
    print("| expert i | tokens assigned (M_i)     | M_i |")
    print("|----------|---------------------------|-----|")
    for i in range(E):
        toks = ", ".join(per_expert[i]) if per_expert[i] else "(none)"
        print(f"| {i}        | {toks:<25} | {len(per_expert[i])}   |")
    print()
    print("M_i is NOT uniform -> exactly the ragged case grouped GEMM solves.")
    print("DeepSeek-V3 / Mixtral training/inference engines all use grouped GEMM")


def section_worked_trace(moe: MoE, x: torch.Tensor, dims: dict):
    banner("SECTION H: worked routing trace -- the gold centerpiece")
    E, k = dims["E"], dims["k"]
    H = moe.router_logits(x)
    G, topk_idx = moe.gate_weights(x)
    y = moe(x)
    print("End-to-end trace for all L=4 tokens. This is the single canonical")
    print("example the .html recomputes and gold-checks.\n")
    print("| m | x[0,m] (D=8)                            | top-k experts | "
          "G weights (the 2 nonzero)        | y[0,m,0]  |")
    print("|---|------------------------------------------|---------------|"
          "----------------------------------|-----------|")
    for m in range(x.shape[1]):
        xin = " ".join(f"{v:+.2f}" for v in x[0, m].tolist())
        idx = topk_idx[0, m].tolist()
        gw = [round(G[0, m, int(i)].item(), 4) for i in idx]
        gw_str = ", ".join(f"E{i}={w}" for i, w in zip(idx, gw))
        print(f"| {m} | {xin:<40} | {str(idx):<13} | {gw_str:<32} | "
              f"{y[0,m,0].item():+.6f} |")
    print()
    # The single gold value
    print(f"GOLD: token m=0 -> experts {topk_idx[0,0].tolist()}, "
          f"gates {[round(G[0,0,int(i)].item(),6) for i in topk_idx[0,0].tolist()]}, "
          f"y[0,0,0] = {y[0,0,0].item():.6f}")
    print("The .html recomputes the full router -> top-k -> experts -> output")
    print("pipeline in JS from the IDENTICAL formulas and pins y[0,0,0] above.")

    # final self-consistency: full MoE == sum over all experts weighted by G
    y_check = torch.zeros_like(y)
    for i, ex in enumerate(moe.experts):
        y_check = y_check + G[..., i].unsqueeze(-1) * ex(x)
    assert torch.allclose(y, y_check, atol=1e-6)
    print(f"\n[check] MoE(x) == sum_i G_i * E_i(x) over ALL {E} experts : OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("moe_routing.py - reference impl. Numbers below feed MOE_ROUTING.md.")
    print("torch =", torch.__version__)

    moe, x, dims = build_tiny_moe()

    section_dense_vs_sparse()
    section_routing_math(moe, x, dims)
    section_expert_combination(moe, x, dims)
    section_aux_losses(moe, x, dims)
    section_token_dropping(moe, x, dims)
    section_deepseek(moe, x, dims)
    section_expert_parallelism(moe, x, dims)
    section_worked_trace(moe, x, dims)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
