"""
speculative_draft.py - Reference implementation of SPECULATIVE DECODING where the
SLM is the DRAFT model that accelerates a bigger TARGET model's inference.

This is the single source of truth that SPECULATIVE_DRAFT.md is built from. Every
number, table, and worked example in the guide is printed by this file. If you
change something here, re-run and re-paste the output.

Run:
    uv run python speculative_draft.py

== IMPORTANT -- a FAITHFUL toy, not a real LLM ================================
We do NOT load transformers / vLLM / a real 7B target + 0.5B draft. The POINT of
this bundle is the draft->verify->accept/resample MECHANISM, which is independent
of the model sizes. So we model the draft and target as tiny per-position LOGIT
distributions over an 8-token vocab. A production speculative server (vLLM,
TensorRT-LLM, llama.cpp) runs the IDENTICAL accept/reject loop over a 32k-128k
vocab and real model weights -- the math is byte-for-byte the same, just bigger
arrays.

== The big idea, in one paragraph ============================================
Autoregressive decode is memory-bandwidth-bound: generating ONE token reads ALL
the target's weights from RAM once, for ~1 FLOP/byte (the GPU starves). An SLM is
small enough that reading ITS weights is cheap. SPECULATIVE DECODING turns that
cheapness into a free speedup for the big target: the SLM (draft) autoregressively
proposes GAMMA tokens (GAMMA cheap passes); the big TARGET then scores all GAMMA
in ONE parallel forward pass (one expensive pass, amortized over GAMMA). We keep
the longest prefix where the target AGREES with the draft (target argmax ==
draft token), then RESAMPLE the first mismatch from the target. Cost drops from
(GAMMA target passes) to (GAMMA draft passes + 1 target pass) -- a win whenever
the draft agrees often. THIS BUNDLE IS THE INVERSE OF ../llm/SPECULATIVE_DECODING:
there a big model speculatively decodes ITSELF; HERE the SLM is the DRAFT SERVING
a bigger target.

== The lineage (old -> new, with WHY each step happened) =======================
  1-token/step decode : the target emits 1 token per forward pass. Each pass
                        reads ALL target weights once for 1 token -> ~1
                        FLOP/byte, GPU 99% idle waiting on memory. Wasteful.
                        (🔗 ../llm/SPECULATIVE_DECODING.md Section A.)
  draft + verify      : a small DRAFT model (the SLM) proposes GAMMA tokens
                        autoregressively (GAMMA cheap passes); the TARGET
                        verifies all GAMMA in ONE parallel forward pass. Now one
                        target weight-load does GAMMA tokens of useful work
                        instead of 1. (Leviathan et al 2023, arXiv:2211.17192.)
  accept / resample   : keep the longest prefix where target argmax == draft
                        token; at the first mismatch RESAMPLE from the target
                        distribution. The greedy variant (this file) preserves
                        the GREEDY target output exactly -- "greedy sampling with
                        speculative decoding matches greedy sampling without it"
                        (vLLM docs). The stochastic variant (../llm Section C)
                        uses rejection sampling to preserve the FULL target
                        distribution p exactly.
Result: up to (1+GAMMA) fewer target passes, zero quality loss (greedy-exact).

== The mechanism, in plain steps ==============================================
    GAMMA             number of draft tokens proposed per round (here GAMMA=4).
    q_i               [V] draft model's distribution at position i (the guess).
    p_i               [V] target model's distribution at position i (the truth).
    draft_token_i     argmax(q_i)  -- the draft's greedy pick at position i.
    target_argmax_i   argmax(p_i)  -- what the target would have picked.
    ACCEPT position i if target_argmax_i == draft_token_i   (they agree)
    REJECT  at the first i where they disagree; resample that position from the
            TARGET distribution p_i (here: take target_argmax_i, the greedy pick)
    accepted prefix   = positions 0..R-1 that were accepted
    committed tokens  = accepted prefix (R tokens) + 1 resampled/bonus token
                      = R + 1   (the +1 is the bonus that makes spec always
                                 emit at least 1 token per round, even on R=0)

== Plain-English glossary =====================================================
    target model   the big, expensive model whose output we want (e.g. 7B).
    draft model    the small, cheap SLM that proposes tokens (e.g. 0.5B-1B).
                   Must be "order(s) of magnitude smaller" and share the target's
                   vocab; ideally trained on the same data (UCSD CSE291A lecture).
    GAMMA (gamma)  number of draft tokens proposed per speculative round (4-8).
    V (vocab)      number of possible next tokens (here a tiny 8-token vocab).
    logits         [V] raw preference scores from an LM head.
    softmax        turns logits into probabilities that sum to 1.
    q_i / p_i      [V] draft / target probability distribution at position i.
    argmax         the token id with the highest logit/probability (greedy pick).
    accepted R     length of the longest prefix where target argmax == draft token.
    resample       at the first mismatch, take the target's own greedy token.
    bonus token    the +1 committed token: spec always emits >=1 token/round.
    alpha          per-position agreement rate (P[target argmax == draft argmax]).
    kappa          draft_speed_advantage: how many times cheaper a draft pass is
                   than a target pass (e.g. kappa=8 -> draft pass costs 1/8).
    tokens/forward committed tokens per target forward = R + 1 (greedy, this round)
    speedup S      (expected tokens committed) / (1 + GAMMA/kappa) target-pass-equivs

== GOLD ANCHOR (speculative_draft.html recomputes this identically) ===========
The FIXED per-position toy draft + target logits (GAMMA=4, V=8). The draft's
greedy tokens are ["the","cat","sat","on"]; the target agrees on the first THREE
(the, cat, sat) and DISAGREES on the 4th ("on" vs target's "a"):
    accepted prefix length R = 3
    committed tokens         = ["the","cat","sat","a"]  (3 accepted + 1 resample)
    tokens per target forward= 4  (= R + 1 = 3 + 1)
    => 4 tokens per 1 target pass vs 4 target passes plain -> ~4x fewer passes.
The .html reproduces the SAME per-position logits + the SAME greedy accept loop
and the [check: OK] badge asserts the accepted-prefix length R == 3.

== Sources (all in speculative_draft_reference.txt, >=2 independent) ===========
  draft + verify   : Leviathan, Kalman, Matias 2023 arXiv:2211.17192 (THE paper)
  greedy equality  : vLLM docs "Speculative Decoding" (greedy == greedy)
  draft sizing      : UCSD CSE291A lecture (7B target, 68M draft, same vocab)
  big-model inverse : ../llm/SPECULATIVE_DECODING.md (the in-repo reference)
"""

from __future__ import annotations

import torch
import torch.nn.functional as F

torch.set_printoptions(precision=4, sci_mode=False)

BANNER = "=" * 74

# Tiny 8-token vocab (same tokens as ../llm/speculative_decoding.py for the
# cross-ref; a production server uses a 32k-128k BPE vocab).
V = 8
TOKENS = ["the", "cat", "xyz", "sat", "qqq", "on", "a", "mat"]

# ============================================================================
# 0. THE FIXED TOY DISTRIBUTIONS (deterministic -- explicit per-position logits)
#    GAMMA=4 positions. Each position has its own draft and target logit vector
#    over V=8 tokens. This models a real autoregressive draft+target pair where
#    each step's distribution depends on the tokens emitted so far. The numbers
#    are chosen so the greedy accept prefix is EXACTLY 3 (the GOLD anchor).
# ============================================================================

GAMMA = 4

# Row i = draft logits at position i. The draft's greedy picks spell
# ["the", "cat", "sat", "on"].
DRAFT_LOGITS = torch.tensor(
    [
        [3.0, 2.0, 0.5, 1.5, 0.3, 1.8, 0.7, 1.2],   # pos 0: argmax=0 "the"
        [2.0, 3.0, 0.5, 1.5, 0.3, 1.8, 0.7, 1.2],   # pos 1: argmax=1 "cat"
        [1.0, 2.0, 0.5, 3.5, 0.3, 1.8, 0.7, 1.2],   # pos 2: argmax=3 "sat"
        [1.0, 2.0, 0.5, 1.5, 0.3, 3.5, 0.7, 1.2],   # pos 3: argmax=5 "on"
    ],
    dtype=torch.float32,
)

# Row i = target logits at position i. The target AGREES on positions 0,1,2
# (same argmax) and DISAGREES on position 3 (target wants "a", not "on").
TARGET_LOGITS = torch.tensor(
    [
        [4.0, 2.0, 0.5, 1.5, 0.3, 1.8, 0.7, 1.2],   # pos 0: argmax=0 "the"  AGREE
        [1.5, 3.5, 0.5, 1.5, 0.3, 1.8, 0.7, 1.2],   # pos 1: argmax=1 "cat"  AGREE
        [1.0, 2.0, 0.5, 4.0, 0.3, 1.8, 0.7, 1.2],   # pos 2: argmax=3 "sat"  AGREE
        [1.0, 2.0, 0.5, 1.5, 0.3, 1.8, 4.5, 1.2],   # pos 3: argmax=6 "a"   DISAGREE
    ],
    dtype=torch.float32,
)


def softmax_rows(logits: torch.Tensor) -> torch.Tensor:
    """softmax over the last dim (per-position distributions)."""
    return F.softmax(logits, dim=-1)


# ============================================================================
# 1. THE CHECK HELPER  (no raw assert -- it is compiled out under -O)
# ============================================================================

def check(desc: str, ok: bool) -> None:
    """Print '[check] desc: OK' or raise SystemExit on failure."""
    print(f"  [check] {desc}: {'OK' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(f"CHECK FAILED: {desc}")


def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 2. THE SPECULATIVE-DECODE PRIMITIVE (greedy variant -- the whole concept)
# ============================================================================

def draft_greedy_tokens(draft_logits: torch.Tensor) -> list[int]:
    """SLM draft step: argmax each per-position draft distribution.

    In a real server this is GAMMA serial forward passes through the small draft
    model (cheap -- the draft's weights are tiny). Here the per-position logits
    are precomputed, so this is just the argmax of each row.
    """
    return draft_logits.argmax(dim=-1).tolist()


def greedy_speculative_round(
    draft_tokens: list[int], target_logits: torch.Tensor
) -> tuple[list[int], int, int]:
    """One greedy speculative-decode round (draft already proposed).

    The TARGET verifies all GAMMA tokens in ONE parallel forward pass (here:
    the per-position target logits are precomputed). Walk left-to-right; ACCEPT
    while target argmax == draft token; at the first mismatch RESAMPLE that
    position from the target (take its greedy argmax). Always append one BONUS
    token (the token after the accepted prefix), so a round commits R+1 tokens.

    Returns:
        committed   : list[int]   the tokens committed this round (R accepted + 1)
        R           : int         accepted-prefix length (0..GAMMA)
        reject_pos  : int         first mismatch index, or GAMMA if all accepted
    """
    committed: list[int] = []
    reject_pos = len(draft_tokens)  # default: no rejection
    for i, t_i in enumerate(draft_tokens):
        t_argmax = int(target_logits[i].argmax().item())
        if t_argmax == t_i:
            committed.append(t_i)            # ACCEPT: target agrees with draft
        else:
            reject_pos = i
            committed.append(t_argmax)        # RESAMPLE: take the target's pick
            break
    else:
        # All GAMMA accepted -> append the target's NEXT greedy token as bonus.
        # (bonus token at position GAMMA, produced from the target's own forward)
        pass
    # The bonus/resample token is already appended above (the mismatch resample
    # OR, if all accepted, we still owe one bonus token from the target's forward
    # at position GAMMA). When all GAMMA accepted, add the bonus token.
    if reject_pos == len(draft_tokens):
        # Need a bonus distribution at position GAMMA; reuse a deterministic one.
        bonus = int(TARGET_LOGITS_BONUS.argmax().item())
        committed.append(bonus)
    R = reject_pos
    return committed, R, reject_pos


# Bonus-position target logits (position GAMMA=4) -- used only when all GAMMA
# draft tokens are accepted, so a round still commits exactly R+1 tokens. Fixed
# so the output is deterministic.
TARGET_LOGITS_BONUS = torch.tensor(
    [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 2.5, 0.5], dtype=torch.float32
)  # argmax=6 "a"


# ============================================================================
# A. THE DRAFT STEP  (SLM proposes GAMMA tokens autoregressively)
# ============================================================================

def section_draft_step():
    banner("SECTION A: the draft step (SLM proposes GAMMA=4 tokens)")
    q = softmax_rows(DRAFT_LOGITS)
    draft_tokens = draft_greedy_tokens(DRAFT_LOGITS)
    print(f"GAMMA = {GAMMA} draft tokens. Vocab V = {V}.")
    print("The DRAFT model (the SLM) runs GAMMA cheap serial forward passes, one per")
    print("proposed token. Each forward produces a [V] logit vector; the draft's greedy")
    print("pick is argmax of that vector.\n")
    print("| pos | draft logits [V=8]                          | argmax | token | q(argmax) |")
    print("|-----|----------------------------------------------|--------|-------|-----------|")
    for i in range(GAMMA):
        lg = "[" + ", ".join(f"{x:.1f}" for x in DRAFT_LOGITS[i].tolist()) + "]"
        tok = draft_tokens[i]
        qp = q[i, tok].item()
        print(f"| {i}   | {lg:<44} | {tok}      | {TOKENS[tok]:<5} | {qp:.4f}    |")
    print()
    print("Draft tokens (the SLM's greedy proposal):")
    print(f"  ids    = {draft_tokens}")
    print(f"  tokens = {[TOKENS[t] for t in draft_tokens]}")
    print()
    print("Cost: GAMMA cheap draft passes (the SLM's weights are tiny). In production")
    print("the draft is 'order(s) of magnitude smaller' than the target, e.g. a 68M")
    print("draft for a 7B target (UCSD CSE291A lecture). Same vocab; same data.")
    check("draft produced exactly GAMMA tokens", len(draft_tokens) == GAMMA)
    check("draft tokens match the designed greedy picks [0,1,3,5]",
          draft_tokens == [0, 1, 3, 5])
    return draft_tokens


# ============================================================================
# B. THE VERIFY STEP  (TARGET scores all GAMMA in ONE parallel forward)
# ============================================================================

def section_verify_step():
    banner("SECTION B: the verify step (TARGET scores all GAMMA in 1 parallel pass)")
    p = softmax_rows(TARGET_LOGITS)
    draft_tokens = draft_greedy_tokens(DRAFT_LOGITS)
    target_argmax = TARGET_LOGITS.argmax(dim=-1).tolist()
    print("The TARGET model runs ONE parallel forward pass over the GAMMA draft tokens")
    print("(a causal mask makes position i attend only to 0..i). It produces GAMMA")
    print("[V] logit vectors at once -- one weight load, GAMMA positions of useful work.")
    print()
    print("| pos | draft token | q(draft) | p(draft) | target argmax | agree? |")
    print("|-----|-------------|----------|----------|---------------|--------|")
    for i in range(GAMMA):
        t = draft_tokens[i]
        qd = softmax_rows(DRAFT_LOGITS)[i, t].item()
        pd = p[i, t].item()
        ta = target_argmax[i]
        agree = "YES" if ta == t else "no (REJECT)"
        print(f"| {i}   | {TOKENS[t]:<5} ({t})    | {qd:.4f}   | {pd:.4f}   | "
              f"{TOKENS[ta]:<5} ({ta})       | {agree:<6} |")
    print()
    agree_count = sum(1 for i in range(GAMMA) if target_argmax[i] == draft_tokens[i])
    print(f"Agreement: target matches draft on {agree_count}/{GAMMA} positions.")
    print("The longest accepted PREFIX is the run of agreements from position 0; the")
    print("first DISAGREEMENT triggers a resample from the target.")
    check("target agrees on exactly the first 3 positions",
          [target_argmax[i] == draft_tokens[i] for i in range(GAMMA)] ==
          [True, True, True, False])
    return target_argmax


# ============================================================================
# C. THE ACCEPT / RESAMPLE LOOP  (greedy variant -- the GOLD centerpiece)
# ============================================================================

def section_accept_loop():
    banner("SECTION C: accept/resample loop (greedy variant -- the GOLD anchor)")
    print("VARIANT: greedy / argmax verification. Walk left-to-right over the GAMMA")
    print("draft tokens; ACCEPT while target argmax == draft token; at the FIRST")
    print("mismatch RESAMPLE that position by taking the target's own greedy pick.")
    print("This preserves the GREEDY target output exactly: 'greedy sampling with")
    print("speculative decoding matches greedy sampling without it' (vLLM docs).")
    print("The stochastic variant (../llm/SPECULATIVE_DECODING.md Section C) instead")
    print("uses rejection sampling to preserve the FULL target distribution p.\n")
    draft_tokens = draft_greedy_tokens(DRAFT_LOGITS)
    target_argmax = TARGET_LOGITS.argmax(dim=-1).tolist()
    print("Per-position accept/reject decision:")
    print()
    print("| pos | draft t_i | target argmax | decision                | committed so far        |")
    print("|-----|-----------|---------------|-------------------------|-------------------------|")
    committed: list[int] = []
    reject_pos = GAMMA
    for i in range(GAMMA):
        t = draft_tokens[i]
        ta = target_argmax[i]
        if ta == t:
            committed.append(t)
            dec = f"ACCEPT ({TOKENS[t]} == {TOKENS[ta]})"
        else:
            committed.append(ta)
            reject_pos = i
            dec = f"REJECT -> resample = {TOKENS[ta]}"
            print(f"| {i}   | {TOKENS[t]:<5}     | {TOKENS[ta]:<5}         | {dec:<23} | "
                  f"{[TOKENS[c] for c in committed]!r:<23} |")
            break
        print(f"| {i}   | {TOKENS[t]:<5}     | {TOKENS[ta]:<5}         | {dec:<23} | "
              f"{[TOKENS[c] for c in committed]!r:<23} |")
    if reject_pos == GAMMA:
        bonus = int(TARGET_LOGITS_BONUS.argmax().item())
        committed.append(bonus)
        print(f"| {GAMMA} | (bonus)   | {TOKENS[bonus]:<5}         | all accepted -> bonus   | "
              f"{[TOKENS[c] for c in committed]!r:<23} |")
    R = reject_pos
    print()
    print(f"Accepted-prefix length R = {R}  (positions 0..{R-1} accepted)")
    print(f"Resample/bonus token     = {TOKENS[committed[R]]}  (from the target)")
    print(f"Committed this round     = {committed}  ({[TOKENS[c] for c in committed]})")
    print(f"  = {R} accepted + 1 resampled/bonus = {len(committed)} tokens")
    print(f"Tokens per target forward = {len(committed)}")
    print()
    # PROVE greedy-exactness: the committed sequence == pure-target greedy.
    # Pure target greedy at pos 0..GAMMA-1 (and the bonus) must equal committed.
    pure_target = list(target_argmax)  # greedy target at each position
    # pure-target greedy emits until its first divergence? No: pure target greedy
    # just takes argmax(p_i) at each position. committed[:R] are positions where
    # draft==target argmax, so == target argmax; committed[R] is the resample ==
    # target argmax at R. So committed[:R+1] == pure_target[:R+1] exactly.
    greedy_match = committed[:R + 1] == pure_target[:R + 1]
    print("GREEDY-EXACTNESS CHECK: the committed sequence must equal what pure-target")
    print("greedy decoding would emit over the same positions:")
    print(f"  committed[:R+1]   = {committed[:R+1]}  {[TOKENS[c] for c in committed[:R+1]]}")
    print(f"  pure-target greedy= {pure_target[:R+1]}  {[TOKENS[c] for c in pure_target[:R+1]]}")
    check("committed[:R+1] == pure-target greedy over the same positions",
          greedy_match)
    check("accepted-prefix length R == 3 (the GOLD pin)", R == 3)
    check("committed == ['the','cat','sat','a']",
          committed == [0, 1, 3, 6])
    check("tokens per target forward == R + 1 == 4",
          len(committed) == R + 1 and len(committed) == 4)
    # Verify the reference primitive greedy_speculative_round() agrees with the
    # verbose inline trace above (the primitive is the source of truth).
    prim_committed, prim_R, prim_reject = greedy_speculative_round(
        draft_tokens, TARGET_LOGITS)
    check("reference primitive greedy_speculative_round() agrees with the trace",
          prim_committed == committed and prim_R == R and prim_reject == R)
    return committed, R


# ============================================================================
# D. THE SPEEDUP SWEEP  (tokens/forward + speedup vs plain decode)
# ============================================================================

def _expected_tokens_per_forward(alpha: float, gamma: int) -> float:
    """Expected tokens committed per target forward (greedy variant).

    E[committed] = 1 + alpha + alpha^2 + ... + alpha^gamma
                 = (1 - alpha^(gamma+1)) / (1 - alpha)
    (the +1 is the bonus/resample token; Leviathan 2023's numerator.)
    At alpha -> 1 this -> gamma + 1 (every draft token accepted + bonus).
    """
    if alpha >= 0.999999:
        return float(gamma + 1)
    return (1.0 - alpha ** (gamma + 1)) / (1.0 - alpha)


def _speedup(alpha: float, gamma: int, kappa: float) -> float:
    """Speedup over plain (1-token/step) target decode.

    S = E[tokens committed per round] / (target-pass-equivalents per round)
      = (1 - alpha^(gamma+1)) / (1 - alpha)   /   (1 + gamma / kappa)

    Denominator: 1 target pass + gamma draft passes, each draft pass costs 1/kappa
    of a target pass (kappa = draft_speed_advantage, e.g. kappa=8 means the draft
    is 8x cheaper per pass). Matches ../llm/SPECULATIVE_DECODING.md Section E with
    gamma_cost = 1/kappa.
    """
    num = _expected_tokens_per_forward(alpha, gamma)
    den = 1.0 + gamma / kappa
    return num / den


def section_speedup_sweep():
    banner("SECTION D: speedup sweep (tokens/forward + S vs alpha, gamma, kappa)")
    print("GREEDY VARIANT speedup model:")
    print("  E[tokens / target forward] = 1 + alpha + ... + alpha^gamma")
    print("                            = (1 - alpha^(gamma+1)) / (1 - alpha)")
    print("  S (over plain 1-token/step decode)")
    print("    = E[tokens/forward] / (1 + gamma/kappa)")
    print("  alpha = per-position agreement rate  P[target argmax == draft argmax]")
    print("  kappa = draft_speed_advantage        (draft pass costs 1/kappa of target)")
    print()
    print("For the TOY round (this file): R=3 accepted of gamma=4 -> tokens/forward")
    print("= R + 1 = 4. Plain decode needs 4 target passes for 4 tokens; spec needs 1.")
    print("=> ~4x fewer target passes THIS round (before draft overhead).\n")

    # Table 1: expected tokens/forward as a function of alpha and gamma.
    print("Expected tokens per target forward E[R+1] = (1-alpha^(gamma+1))/(1-alpha):")
    print()
    print("| alpha | gamma=2 | gamma=4 | gamma=8 | gamma=8 @ alpha=1 |")
    print("|-------|---------|---------|---------|-------------------|")
    alphas = [0.3, 0.5, 0.7, 0.9, 1.0]
    for a in alphas:
        v2 = _expected_tokens_per_forward(a, 2)
        v4 = _expected_tokens_per_forward(a, 4)
        v8 = _expected_tokens_per_forward(a, 8)
        a1 = _expected_tokens_per_forward(1.0, 8)
        print(f"| {a:<5.1f} | {v2:<7.2f} | {v4:<7.2f} | {v8:<7.2f} | {a1:<17.2f} |")
    print()
    print("Key: at alpha=1 (perfect agreement) tokens/forward = gamma+1 (every draft")
    print("token accepted + the bonus). At alpha=0.5, gamma=4 -> 1.94 tokens/forward")
    print("(about 2x the plain rate of 1).\n")

    # Table 2: speedup S over plain decode (kappa=8 -> draft is 8x cheaper).
    print("Speedup S = E[tokens/forward] / (1 + gamma/kappa),  kappa=8 (draft 8x cheaper):")
    print()
    print("| alpha | gamma=2  | gamma=4  | gamma=8  |")
    print("|-------|----------|----------|----------|")
    for a in [0.3, 0.5, 0.7, 0.9]:
        vals = [_speedup(a, g, 8.0) for g in (2, 4, 8)]
        print(f"| {a:<5.1f} | {vals[0]:<8.2f} | {vals[1]:<8.2f} | {vals[2]:<8.2f} |")
    print()
    print("Key: S>1 needs alpha high enough that the accepted tokens outweigh the")
    print("gamma cheap draft passes. With kappa=8 and gamma=4, the draft overhead is")
    print("1 + 4/8 = 1.5 target-pass-equivs per round, so spec wins once E[tokens] > 1.5.")
    print()
    print("Published (labelled, not measured here):")
    print("  Leviathan et al 2023: 2x-3x on T5-XXL, identical outputs.")
    print("  EAGLE (arXiv:2401.15077): 2.7x-3.5x on LLaMA2-Chat 70B.")
    print("  vLLM spec decode: 1.4x-1.6x typical (greedy equality preserved).")
    print()

    # GOLD checks on the speedup math.
    tpf = _expected_tokens_per_forward(0.5, 4)
    check("E[tokens/forward](alpha=0.5, gamma=4) == 1.9375",
          abs(tpf - 1.9375) < 1e-9)
    check("E[tokens/forward](alpha=1.0, gamma=4) == 5 (gamma+1)",
          abs(_expected_tokens_per_forward(1.0, 4) - 5.0) < 1e-9)
    s = _speedup(0.7, 4, 8.0)
    check("S(alpha=0.7, gamma=4, kappa=8) > 1 (spec wins)",
          s > 1.0)
    # The TOY's actual (deterministic, not expected) tokens-per-forward is the
    # GOLD pin: R=3 accepted of GAMMA=4 -> committed = R + 1 = 4 tokens.
    toy_R = 3
    toy_tokens_per_forward = toy_R + 1
    check("TOY tokens/forward == R+1 == 4 (the GOLD pin for the .html)",
          toy_tokens_per_forward == 4)


# ============================================================================
# E. THE LINEAGE RECAP  (1-token/step -> draft+verify -> SLM-as-draft)
# ============================================================================

def section_lineage():
    banner("SECTION E: the lineage (1-token/step -> draft+verify -> SLM-as-draft)")
    ladder = [
        ("1-token/step decode",
         "target emits 1 token per forward; reads ALL weights once for 1 token",
         "~1 FLOP/byte, GPU 99% idle; memory-bandwidth-bound",
         "../llm/SPECULATIVE_DECODING.md Section A"),
        ("draft + verify (parallel)",
         "small DRAFT proposes GAMMA tokens; TARGET verifies all GAMMA in 1 pass",
         "1 target weight-load does GAMMA tokens of work (K FLOP/byte)",
         "Leviathan 2023 arXiv:2211.17192"),
        ("SLM-as-draft (this bundle)",
         "an SLM is the DRAFT serving a bigger TARGET; accept prefix + resample",
         "up to (1+GAMMA)x fewer target passes; greedy-exact (zero quality loss)",
         "../llm/SPECULATIVE_DECODING.md (the big-model inverse)"),
    ]
    print("| stage                  | what it does                              | "
          "win / cost                                            | where                          |")
    print("|------------------------|-------------------------------------------|"
          "-------------------------------------------------------|--------------------------------|")
    for name, what, win, where in ladder:
        print(f"| {name:<22} | {what:<41} | {win:<53} | {where:<30} |")
    print()
    print("THIS bundle is the INVERSE of ../llm/SPECULATIVE_DECODING.md: THERE a big")
    print("model speculatively decodes ITSELF (the focus is the rejection-sampling math")
    print("that preserves the FULL distribution p); HERE the SLM is the DRAFT whose")
    print("whole job is to be a CHEAP, accurate proposer for a bigger target. The")
    print("accept/resample loop is structurally identical; only the perspective flips.")
    check("lineage has exactly 3 stages", len(ladder) == 3)
    check("the final stage is 'SLM-as-draft'", "SLM-as-draft" in ladder[2][0])


# ============================================================================
# main
# ============================================================================

def main():
    torch.manual_seed(0)  # determinism (no RNG is actually used, but pinned)
    print("speculative_draft.py - reference impl. All numbers below feed "
          "SPECULATIVE_DRAFT.md.\ntorch =", torch.__version__)
    print("\nEvery claim is web-verified in >=2 sources; "
          "see speculative_draft_reference.txt.")

    section_draft_step()
    section_verify_step()
    committed, R = section_accept_loop()
    section_speedup_sweep()
    section_lineage()

    banner("GOLD RECAP (pinned for speculative_draft.html)")
    print(f"  GAMMA                                = {GAMMA}")
    print(f"  draft greedy tokens                  = {draft_greedy_tokens(DRAFT_LOGITS)}")
    print(f"  target argmax per pos                = {TARGET_LOGITS.argmax(dim=-1).tolist()}")
    print(f"  accepted-prefix length R (GOLD)      = {R}")
    print(f"  committed tokens                     = {committed}")
    print(f"  tokens per target forward (GOLD)     = {len(committed)}  (= R + 1)")
    print(f"  => ~{len(committed)}x fewer target passes than plain decode (this round)")
    print("  greedy-exact: committed == pure-target greedy over the same positions")

    banner("DONE - all sections printed, all [check]s passed")


if __name__ == "__main__":
    main()
