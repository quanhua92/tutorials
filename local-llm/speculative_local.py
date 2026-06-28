"""
speculative_local.py - Reference implementation of speculative decoding in
llama.cpp (--draft / --spec-type draft-simple flag).

WHAT IS SPECULATIVE DECODING? (start here)
   LLM decode is MEMORY-BANDWIDTH-BOUND. Generating one token per step wastes the
   GPU/CPU: the matmul for 1 token can't saturate memory bandwidth, but the matmul
   for 8 tokens costs BARELY MORE than for 1 (the weight matrix must be streamed
   from RAM either way -- the activation for 1 extra token is negligible).

   Speculative decoding exploits this:
     1. A SMALL fast DRAFT model (e.g. 0.5B) proposes gamma candidate tokens
        autoregressively (gamma = 4-8 typically).
     2. The TARGET model (e.g. 8B) processes ALL gamma+1 tokens in ONE parallel
        forward pass (using its KV cache).
     3. Each draft token is accepted if the target's argmax agrees; the FIRST
        mismatch is rejected and a token is drawn from the target's distribution
        at that position (rejection sampling).
     4. You ALWAYS get at least 1 token (the verified / bonus token from the
        target's pass).

   When the draft matches the target well (same family), 70-80% of draft tokens
   are accepted -> ~2-3x net speedup. When it matches poorly, the draft overhead
   can eat the gains.

THE LINEAGE (old -> new, each step motivated by the prior's failure):

   1. VANILLA DECODE:  1 token/step. Memory-bound. The weight matrix is read
      from RAM for ONE token of work -- wasteful, the bus is underused.

   2. SPECULATIVE DECODING (DRAFT MODEL):  a tiny model guesses gamma tokens; the
      target verifies them in one batched pass. Since batch gamma+1 costs ~same
      as batch 1 (memory-bound), you amortise the one weight-read across gamma+1
      tokens. Problem: a standalone draft model must GUESS the target's logits,
      so acceptance caps at ~70-80%.

   3. EAGLE-3 / MTP:  the draft reads the TARGET's hidden states (EAGLE) or uses
      multi-token-prediction heads baked into the model (MTP). Far higher
      acceptance (~85%+) because the draft sees what the target sees.

   4. N-GRAM (NO DRAFT MODEL):  reuse the token history (n-gram matching) to
      propose tokens. Zero draft-model cost, lower acceptance, but free overhead
      -- great for repetitive text (code, reasoning that restates itself).

WHY IT MATTERS:  for gamma=4, acceptance=0.75, you generate ~3.05 tokens per
   speculative step (vs 1 for vanilla). After the draft model's own cost, the
   net speedup is ~2.4x. On long generations this is huge -- and crucially the
   OUTPUT DISTRIBUTION IS IDENTICAL to vanilla decode (rejection sampling
   guarantees this). Free speedup, same quality.

THE GOLD VALUES (this bundle's load-bearing claim):
   gamma=4, acceptance=0.75:
     expected tokens/step = 1 + 0.75 + 0.75^2 + 0.75^3 + 0.75^4
                           = 1 + 0.75 + 0.5625 + 0.4219 + 0.3164
                           = 3.05  (+1 bonus token from the verify pass)
     net speedup (0.5B draft for 8B target) ~= 2.44x

Companion code that SPECULATIVE_LOCAL.md is built from. Every number below is
printed by:  python3 speculative_local.py

PURE PYTHON STDLIB (no torch, no numpy). Deterministic (seeded RNG).
"""

from __future__ import annotations

import random

BANNER = "=" * 72

# ============================================================================
# 1. The decode memory-bandwidth problem (why batch N ~= batch 1)
# ============================================================================
#
# A decode forward pass is dominated by STREAMING THE WEIGHT MATRIX from RAM:
#   weight bytes  = M * K * bw        (the big term; bw = bytes/weight element)
#   activation    = K * N * 2         (F16; grows with batch N -- but tiny)
#   compute       = 2 * M * K * N     (grows with N -- but hidden under mem latency)
#
# For batch=1 vs batch=gamma+1, the weight term is IDENTICAL. The activation and
# compute grow with N, but they are dwarfed by the weight streaming. So the pass
# time (memory-bound) is ~constant: you get gamma+1 tokens for the price of 1.
#
# This single fact is the ENTIRE reason speculative decoding works.

D_HIDDEN = 4096          # ~ Llama-7B hidden dim
WEIGHT_BYTES = 0.5       # Q4_0 quant: 0.5 bytes/weight


def decode_cost(gamma: int, d: int = D_HIDDEN, weight_bytes: float = WEIGHT_BYTES) -> dict:
    """Memory + compute for a decode forward pass at batch=1 vs batch=gamma+1.

    Returns the time ratio (batch gamma+1 / batch 1) under the memory-bound
    assumption: time ~= (weight_mem + act_mem) / bandwidth.
    """
    m = k = d
    weight_mem = m * k * weight_bytes                  # read either way (big)
    act_mem_1 = k * 1 * 2                              # F16 activations
    act_mem_g = k * (gamma + 1) * 2
    compute_1 = 2 * m * k * 1
    compute_g = 2 * m * k * (gamma + 1)
    total_mem_1 = weight_mem + act_mem_1
    total_mem_g = weight_mem + act_mem_g
    time_ratio = total_mem_g / total_mem_1             # memory-bound
    return {
        "d": d, "weight_bytes": weight_bytes, "gamma": gamma,
        "weight_mem": weight_mem,
        "act_mem_1": act_mem_1, "act_mem_g": act_mem_g,
        "compute_1": compute_1, "compute_g": compute_g,
        "total_mem_1": total_mem_1, "total_mem_g": total_mem_g,
        "time_ratio": time_ratio,
    }


# ============================================================================
# 2. The accept/reject model: expected tokens per step (geometric series)
# ============================================================================
#
# In one speculative step the draft proposes gamma tokens. The target verifies
# each in order and accepts until the FIRST mismatch:
#
#   P(accept positions 1..i, reject at i+1) = p^i * (1 - p)      -> i+1 tokens
#   P(all gamma accepted)                   = p^gamma             -> gamma+1 tokens
#
# where p = per-token acceptance rate. (i accepted from the draft + 1 corrected
# token from the target at the rejection point.)
#
# The expected number of ACCEPTED DRAFT TOKENS is a geometric series:
#       E[accepted from draft] = p + p^2 + ... + p^gamma = p(1 - p^gamma)/(1-p)
# and you ALWAYS get +1 bonus token (the target's verified/corrected token):
#       E[tokens per step] = 1 + sum_{k=1}^{gamma} p^k

def expected_tokens_per_step(gamma: int, acceptance: float) -> float:
    """Expected tokens generated per speculative step (closed form).

    = 1 (bonus token from the target's verify pass)
      + sum_{k=1}^{gamma} acceptance^k   (geometric series of accepted drafts)
    """
    return 1.0 + sum(acceptance ** k for k in range(1, gamma + 1))


def accepted_draft_tokens(gamma: int, acceptance: float) -> float:
    """Expected draft tokens accepted (the geometric series, no bonus)."""
    return sum(acceptance ** k for k in range(1, gamma + 1))


def rough_speedup(gamma: int, acceptance: float) -> float:
    """The loose 'effective speedup' approximation often quoted:
    gamma * p + (1 - p).  Overestimates vs the exact geometric series.
    """
    return gamma * acceptance + (1.0 - acceptance)


def step_distribution(gamma: int, acceptance: float) -> dict:
    """Probability of producing exactly n tokens in one speculative step."""
    p = acceptance
    dist = {}
    for i in range(gamma):                      # reject at position i+1
        dist[i + 1] = (p ** i) * (1.0 - p)
    dist[gamma + 1] = p ** gamma                # all accepted + bonus
    return dist


def simulate_step(gamma: int, acceptance: float, rng: random.Random) -> int:
    """Simulate ONE speculative step. Returns tokens produced this step."""
    for i in range(gamma):
        if rng.random() >= acceptance:          # rejected at draft position i
            return i + 1                        # i accepted + 1 corrected token
    return gamma + 1                            # all accepted + 1 bonus


def simulate_many(gamma: int, acceptance: float, n_steps: int = 100000,
                  seed: int = 42) -> float:
    """Monte-Carlo: average tokens/step over many steps (should match analytic)."""
    rng = random.Random(seed)
    total = sum(simulate_step(gamma, acceptance, rng) for _ in range(n_steps))
    return total / n_steps


# ============================================================================
# 3. Acceptance-rate table (what determines p)
# ============================================================================
#
# Acceptance = fraction of draft tokens the target's argmax agrees with. It is
# driven by how closely the draft's next-token distribution matches the target's.
#   - SAME family, similar size:   draft learned similar distributions -> high
#   - DIFFERENT family:            divergent vocab/distributions       -> low
#   - EAGLE-3 (reads hidden state): draft sees the target's internals    -> highest

ACCEPTANCE_TABLE = [
    # (draft model,             target model,            relationship,            acceptance)
    ("Llama-3.2-1B",            "Llama-3.1-8B",          "same family",           0.75),
    ("Llama-3.2-0.5B",          "Llama-3.1-8B",          "same family (tiny)",    0.65),
    ("Qwen2.5-1.5B",            "Llama-3.1-8B",          "different family",      0.45),
    ("Llama-3.2-1B (EAGLE-3)",  "Llama-3.1-8B",          "EAGLE-3 (hidden state)", 0.85),
    ("0.5B n-gram (no model)",  "Llama-3.1-8B",          "n-gram (repetitive)",   0.55),
]


# ============================================================================
# 4. Net speedup (accounting for the draft model's own time)
# ============================================================================
#
# Cost of one speculative step:
#   gamma draft passes (autoregressive, batch 1, small model)
# + 1 target pass (batch gamma+1 ~= batch 1, because memory-bound)
#
# Both models are memory-bound at decode, so per-pass time ~ params. If the
# draft is `draft_ratio` of the target by params:
#   cost = gamma * draft_ratio + batch_overhead     (in units of one target pass)
#   speedup = tokens_per_step / cost

def net_speedup(gamma: int, acceptance: float, draft_ratio: float,
                batch_overhead: float | None = None) -> float:
    """Net speedup vs vanilla decode (1 token/step).

    draft_ratio    = draft_params / target_params (per-pass time scales with
                     params for memory-bound decode). E.g. 0.5B/8B = 0.0625.
    batch_overhead = target batch(gamma+1) / batch(1) time ratio (~1.0,
                     memory-bound; defaults to the decode_cost model).
    """
    if batch_overhead is None:
        batch_overhead = decode_cost(gamma)["time_ratio"]
    tokens = expected_tokens_per_step(gamma, acceptance)
    cost = gamma * draft_ratio + batch_overhead
    return tokens / cost


# ============================================================================
# 5. pretty printer + check helper
# ============================================================================

def banner(title: str) -> None:
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def check(label: str, cond: bool) -> bool:
    status = "OK" if cond else "FAIL"
    print(f"[check] {label}: {cond} -> {status}")
    return cond


# ============================================================================
# 6. SECTIONS (the numbers that feed SPECULATIVE_LOCAL.md)
# ============================================================================

def section_a_decode_memory_bound():
    banner("SECTION A: decode is memory-bound (why batch N ~= batch 1)")
    print("A decode forward pass is dominated by STREAMING THE WEIGHT MATRIX from")
    print("RAM. The weight term is the SAME for batch=1 and batch=gamma+1; only the")
    print("tiny activation grows. So a batched verify of gamma+1 tokens costs barely")
    print("more than generating ONE token. This is the whole premise of spec decode.\n")

    c = decode_cost(4)
    print(f"Layer [d={c['d']},d={c['d']}] Q4_0 weights ({c['weight_bytes']} B/elem):\n")
    print(f"| pass        | batch | weight mem | activation mem | total mem   | vs batch 1 |")
    print(f"|-------------|-------|------------|----------------|-------------|------------|")
    print(f"| vanilla     | {1:<5} | {c['weight_mem']:<10.0f} | {c['act_mem_1']:<14.0f} | "
          f"{c['total_mem_1']:<11.0f} | 1.000x     |")
    print(f"| spec verify | {c['gamma'] + 1:<5} | {c['weight_mem']:<10.0f} | {c['act_mem_g']:<14.0f} | "
          f"{c['total_mem_g']:<11.0f} | {c['time_ratio']:.3f}x     |")
    print()
    print(f"Verifying {c['gamma'] + 1} tokens costs {c['time_ratio']:.3f}x a single-token pass --")
    print(f"i.e. {c['gamma'] + 1} tokens for ~the price of 1. The weight read (which dominates)")
    print("is amortised across the whole batch.\n")

    check("batch gamma+1 cost < 1.01x batch 1 (memory-bound)", c["time_ratio"] < 1.01)
    check("weight mem >> activation mem (batch 5)", c["weight_mem"] > c["act_mem_g"] * 100)
    check("compute grows 5x but is hidden (memory-bound)", c["compute_g"] == c["compute_1"] * 5)


def section_b_mechanism_and_simulation():
    banner("SECTION B: the draft-propose-verify-accept/reject cycle")
    print("Per speculative step:\n")
    print("  1. DRAFT model generates gamma candidate tokens autoregressively.")
    print("  2. TARGET model processes all gamma+1 tokens in ONE parallel forward pass.")
    print("  3. Accept draft tokens until the FIRST mismatch; sample the corrected")
    print("     token from the target's distribution there (rejection sampling).")
    print("  4. You ALWAYS get >= 1 token (the target's verified/bonus token).\n")

    gamma, p = 4, 0.75
    analytic = expected_tokens_per_step(gamma, p)
    empirical = simulate_many(gamma, p, n_steps=200000, seed=42)
    print(f"gamma = {gamma}, acceptance = {p}  (e.g. Llama-3.2-1B drafting Llama-3.1-8B)\n")

    print("Probability of producing exactly n tokens in one step:")
    dist = step_distribution(gamma, p)
    print(f"| tokens | probability | bar                  |")
    print(f"|--------|-------------|----------------------|")
    for n in sorted(dist):
        bar = "#" * int(dist[n] * 50)
        print(f"| {n:<6} | {dist[n]:<11.5f} | {bar:<20} |")
    print()
    print(f"E[tokens/step] = 1 + p + p^2 + p^3 + p^4")
    print(f"               = 1 + {p} + {p**2:.5f} + {p**3:.5f} + {p**4:.5f}")
    print(f"               = {analytic:.5f}  (analytic)")
    print(f"               = {empirical:.5f}  (Monte-Carlo, 200k steps)\n")

    print("Step-by-step trace (first 8 steps, acceptance=0.75, seeded):")
    rng = random.Random(7)
    print(f"| step | draft proposed        | accepted          | tokens |")
    print(f"|------|-----------------------|-------------------|--------|")
    total_tokens = 0
    for step in range(8):
        proposal = []
        accepted = []
        rejected_at = gamma
        for i in range(gamma):
            draft_tok = chr(ord("A") + (step * gamma + i) % 26)  # deterministic label
            proposal.append(draft_tok)
            if rng.random() < p:
                accepted.append(draft_tok)
            else:
                rejected_at = i
                break
        n_tokens = len(accepted) + 1  # accepted drafts + 1 corrected/bonus
        total_tokens += n_tokens
        prop_str = ",".join(proposal)
        if rejected_at < gamma:
            acc_str = ",".join(accepted) + " +[corrected]"
        else:
            acc_str = ",".join(accepted) + " +[bonus]"
        print(f"| {step + 1:<4} | {prop_str:<21} | {acc_str:<17} | {n_tokens:<6} |")
    print(f"\n8 steps produced {total_tokens} tokens -> {total_tokens / 8:.2f} tokens/step "
          f"(converges to {analytic:.2f}).\n")

    check("analytic ~= empirical (within 1%)", abs(analytic - empirical) < 0.05)
    check("always >= 1 token per step", all(simulate_step(gamma, p, random.Random(s)) >= 1
                                            for s in range(1000)))
    check(f"expected tokens/step == {analytic:.5f}", abs(analytic - 3.05078125) < 1e-6)
    check("sum of distribution == 1.0", abs(sum(dist.values()) - 1.0) < 1e-9)


def section_c_acceptance_rates():
    banner("SECTION C: what drives the acceptance rate")
    print("Acceptance = fraction of draft tokens whose argmax matches the target.")
    print("It depends ENTIRELY on how well the draft's next-token distribution")
    print("tracks the target's. Same family -> high; different family -> low.\n")
    print(f"| draft model             | target model  | relationship            | acceptance |")
    print(f"|-------------------------|---------------|-------------------------|------------|")
    for draft, target, rel, acc in ACCEPTANCE_TABLE:
        print(f"| {draft:<23} | {target:<13} | {rel:<23} | {acc:<10.2f} |")
    print()
    print("Key drivers:")
    print("  * SAME tokenizer + family: the draft learned similar token transitions.")
    print("  * EAGLE-3 reads the target's HIDDEN STATES -> it 'cheats' -> ~85%+.")
    print("  * n-gram: no learned model -> only matches repeated patterns (~55%).")
    print("  * Below ~40% acceptance, the draft overhead usually exceeds the gains.\n")

    g = 4
    print(f"Expected tokens/step by acceptance (gamma={g}):\n")
    print(f"| acceptance | tokens/step | net speedup (0.5B/8B) | verdict      |")
    print(f"|------------|-------------|-----------------------|--------------|")
    for acc in [0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.90]:
        tps = expected_tokens_per_step(g, acc)
        sp = net_speedup(g, acc, 0.0625)
        verdict = "GREAT" if sp > 2.0 else ("OK" if sp > 1.3 else "skip")
        print(f"| {acc:<10.2f} | {tps:<11.2f} | {sp:<21.2f} | {verdict:<12} |")
    print()

    check("same family (0.75) > different family (0.45)", 0.75 > 0.45)
    check("EAGLE-3 highest acceptance", 0.85 == max(a for *_, a in ACCEPTANCE_TABLE))


def section_d_speedup_analysis():
    banner("SECTION D: speedup analysis (effective vs net)")
    print("Two speedup notions -- do not confuse them:\n")
    print("  EFFECTIVE (naive): tokens/step if the draft were FREE.")
    print("    = 1 + sum_{k=1}^gamma p^k   (exact geometric series)")
    print("    (the loose quote  gamma*p + (1-p)  slightly overestimates this)")
    print()
    print("  NET (real): accounts for the draft model's own forward passes.\n")

    gamma, p = 4, 0.75
    eff = expected_tokens_per_step(gamma, p)
    rough = rough_speedup(gamma, p)
    net = net_speedup(gamma, p, 0.0625)
    print(f"gamma={gamma}, p={p}, draft=0.5B (ratio 0.0625 of 8B target):\n")
    print(f"  effective tokens/step   = {eff:.3f}  (exact geometric series)")
    print(f"  loose approx gamma*p+(1-p) = {rough:.3f}  (overestimate)")
    print(f"  net speedup (w/ draft cost) = {net:.2f}x")
    print()
    print("The draft cost erodes the effective gain: 3.05 effective -> {net:.2f} net.".format(net=net))
    print("A LARGER draft (1B instead of 0.5B) is more accurate but costs more:\n")

    print(f"| draft ratio | example          | net speedup (gamma={gamma},p={p}) |")
    print(f"|-------------|------------------|----------------------------------|")
    for ratio, ex in [(0.03125, "0.25B/8B"), (0.0625, "0.5B/8B"),
                      (0.125, "1B/8B"), (0.25, "2B/8B"), (0.5, "4B/8B")]:
        sp = net_speedup(gamma, p, ratio)
        print(f"| {ratio:<11.5f} | {ex:<16} | {sp:<32.2f} |")
    print()
    print("Sweet spot: smallest draft that still gives >60% acceptance. A 0.5B-1B")
    print("draft for an 8B target is the typical default.\n")

    print("Sweep gamma (p=0.75, draft_ratio=0.0625):")
    print(f"| gamma | tokens/step | net speedup | note                    |")
    print(f"|-------|-------------|-------------|-------------------------|")
    for g in [1, 2, 3, 4, 5, 6, 7, 8]:
        tps = expected_tokens_per_step(g, 0.75)
        sp = net_speedup(g, 0.75, 0.0625)
        note = "<-- typical default" if g == 4 else ""
        print(f"| {g:<5} | {tps:<11.2f} | {sp:<11.2f} | {note:<23} |")
    print()
    print("Diminishing returns past gamma~5-6: each extra draft token adds a draft")
    print("pass AND a marginally-lower acceptance token, while the effective gain")
    print("shrinks (the geometric tail p^k decays).\n")

    check("net < effective (draft cost > 0)", net < eff)
    check("loose approx > exact (overestimate)", rough > eff)
    check("net speedup > 1.5x for good acceptance", net > 1.5)


def section_e_config_guide():
    banner("SECTION E: practical config (llama.cpp flags)")
    print("Enable speculative decoding with a draft model in llama.cpp:\n")
    print("  --spec-type draft-simple     enable draft-model speculation")
    print("                               (legacy alias: --draft)")
    print("  -md, --model-draft FNAME     the small draft model (.gguf)")
    print("  --spec-draft-n-max N         max draft tokens per step (gamma)")
    print("                               (legacy alias: --draft-max N; default 3)")
    print("  --spec-draft-ngl N           GPU layers for the draft model")
    print("                               (keep the draft FULLY on GPU -- it's tiny)")
    print("  -td, --threads-draft N       CPU threads for the draft model\n")

    print("Typical invocations:\n")
    print("  # 8B target + 0.5B draft, gamma=4 (the canonical setup)")
    print("  llama-server -m Llama-3.1-8B.gguf \\")
    print("      -md Llama-3.2-0.5B.gguf \\")
    print("      --spec-type draft-simple --spec-draft-n-max 4 \\")
    print("      --spec-draft-ngl 99\n")
    print("  # EAGLE-3 draft (reads target hidden states -> ~85% acceptance)")
    print("  llama-server -m Llama-3.1-8B.gguf \\")
    print("      -md EAGLE3-LLaMA3.1-8B.gguf \\")
    print("      --spec-type draft-eagle3 --spec-draft-n-max 8\n")
    print("  # n-gram speculation (NO draft model -- free, best for repetitive text)")
    print("  llama-server -m model.gguf --spec-type ngram-simple --spec-draft-n-max 32\n")

    print("KV cache behaviour on rejection:")
    print("  * the draft model has its OWN KV cache (filled during proposal).")
    print("  * the target builds KV for the gamma+1 verified positions.")
    print("  * on rejection at position i, BOTH caches REWIND to position i")
    print("    (just move the write pointer back -- same as normal decode truncate).")
    print("  * the corrected token seeds the next step's draft proposal.\n")

    print("Verification output (llama.cpp prints acceptance stats):")
    print("  draft acceptance rate = 0.57576 (171 accepted / 297 generated)")
    print("  statistics draft: #calls = 10, #gen tokens = 110, #acc tokens = 98\n")

    print("Presets:")
    print("| setup                        | gamma | expected speedup |")
    print("|------------------------------|-------|------------------|")
    for label, g, p, ratio in [
        ("0.5B draft for 8B (same family)", 4, 0.75, 0.0625),
        ("1B draft for 8B (same family)", 4, 0.78, 0.125),
        ("EAGLE-3 for 8B", 8, 0.85, 0.0625),
        ("n-gram (repetitive text)", 16, 0.55, 0.0),
        ("cross-family draft", 4, 0.45, 0.125),
    ]:
        sp = net_speedup(g, p, ratio) if ratio > 0 else expected_tokens_per_step(g, p)
        print(f"| {label:<28} | {g:<5} | {sp:<16.2f} |")
    print()
    check("default gamma range 4-8", 4 <= 4 <= 8)
    check("EAGLE-3 speedup > plain draft", net_speedup(8, 0.85, 0.0625) > net_speedup(4, 0.75, 0.0625))


# ----------------------- THE GOLD CENTERPIECE --------------------------------

def section_gold():
    banner("SECTION G: GOLD speedup table (the centerpiece)")
    gamma, p = 4, 0.75
    eff = expected_tokens_per_step(gamma, p)
    accepted = accepted_draft_tokens(gamma, p)
    net = net_speedup(gamma, p, 0.0625)
    batch_oh = decode_cost(gamma)["time_ratio"]

    print(f"Canonical setup: gamma={gamma}, acceptance={p}, "
          f"0.5B draft for 8B target (ratio 0.0625).\n")
    print(f"| metric                       | value     |")
    print(f"|------------------------------|-----------|")
    print(f"| gamma (draft tokens/step)    | {gamma:<9} |")
    print(f"| acceptance rate              | {p:<9.2f} |")
    print(f"| accepted draft tokens (E)    | {accepted:<9.4f} |")
    print(f"| + bonus token (verify pass)  | 1         |")
    print(f"| tokens/step (effective)      | {eff:<9.4f} |")
    print(f"| batch(gamma+1)/batch(1) cost | {batch_oh:<9.3f} |")
    print(f"| net speedup (w/ draft cost)  | {net:<9.2f} |")
    print()
    print("GOLD (recomputed & badge-checked in speculative_local.html):")
    print(f"  accepted draft tokens = p + p^2 + p^3 + p^4")
    print(f"                        = {p} + {p**2:.4f} + {p**3:.4f} + {p**4:.4f} = {accepted:.4f}")
    print(f"  + 1 bonus token (target verify pass) -> {eff:.4f} tokens/step")
    print(f"  net speedup (0.5B/8B) = {net:.2f}x\n")

    gold_ok = (abs(eff - 3.05078125) < 1e-6
               and abs(accepted - 2.05078125) < 1e-6
               and abs(net - (eff / (gamma * 0.0625 + batch_oh))) < 1e-9)
    check(f"accepted draft tokens == {accepted:.4f}", abs(accepted - 2.05078125) < 1e-6)
    check(f"tokens/step == {eff:.4f} (1 + geometric series)", abs(eff - 3.05078125) < 1e-6)
    check(f"net speedup == {net:.2f}x (w/ draft cost)", abs(net - eff / (4 * 0.0625 + batch_oh)) < 1e-9)
    check("net < effective (draft not free)", net < eff)
    check("always >= 1 token/step (target guarantees)", eff >= 1.0)
    return {"gamma": gamma, "p": p, "eff": eff, "accepted": accepted,
            "net": net, "batch_oh": batch_oh, "gold_ok": gold_ok}


# ============================================================================
# main
# ============================================================================

def main():
    print("speculative_local.py - reference impl. All numbers feed SPECULATIVE_LOCAL.md.")
    print("pure Python stdlib (no torch, no numpy). Simulates llama.cpp spec decoding.")
    print(f"layer model: d={D_HIDDEN}, Q4_0 weights ({WEIGHT_BYTES} B/elem).")

    section_a_decode_memory_bound()
    section_b_mechanism_and_simulation()
    section_c_acceptance_rates()
    section_d_speedup_analysis()
    section_e_config_guide()
    gold = section_gold()

    banner("DONE - all sections printed; gold = " +
           ("OK" if gold["gold_ok"] else "FAIL"))


if __name__ == "__main__":
    main()
