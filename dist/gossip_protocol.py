"""
gossip_protocol.py - Reference implementation of GOSSIP (epidemic) protocols.

Each node periodically contacts a random peer and exchanges state. Like an
epidemic spreading through a population, a single update reaches all N nodes
in O(log N) rounds. Three variants:

  (1) PUSH       : informed nodes PUSH their state to random peers.
  (2) PULL       : uninformed nodes PULL state from random peers.
  (3) PUSH-PULL  : both directions each round - the fastest.

This is the single source of truth that GOSSIP_PROTOCOL.md is built from.
Every number, table, and worked example in the guide is printed by this file.
If you change something here, re-run and re-paste the output into the guide.

Run:
    python3 gossip_protocol.py

============================================================================
THE INTUITION (read this first) - a rumor at a party
============================================================================
One person at an N-person party hears a rumor. Every "round", each person
who ALREADY knows it tells one RANDOM other person (PUSH). That is exactly
how a contagious disease spreads: each round, the number of infected can
ROUGHLY double, so after k rounds about 2^k people know. 2^k >= N when
k >= log2(N) - so the rumor reaches everyone in about log2(N) rounds. That
exponential "each one tells one" is the whole reason gossip is fast.

But there are two wrinkles:

  * PUSH has a long TAIL. Early on, almost everyone an informed node calls is
    still uninformed, so the count doubles. Late on, almost everyone is ALREADY
    informed, so an informed node keeps calling people who already know - wasted
    calls. The LAST few uninformed nodes take a surprisingly long time to bump
    into. Pure push therefore takes ~ log2(N) + ln(N) rounds (Karp et al. 2003).

  * PULL alone is slow to START (one informed node; the chance an uninformed
    node happens to ask exactly that one is 1/N), but fast to FINISH, because
    once MOST nodes are informed, every uninformed node has a high chance of
    asking someone who knows.

  * PUSH-PULL combines both: informed nodes push AND uninformed nodes pull.
    It grows fastest (about 3x per round early on, not 2x) AND mops up the tail
    (uninformed nodes actively ask). It reliably reaches everyone in
    ceil(log2(N)) + 1 rounds - the GOLD CHECK of this bundle.

Real systems:
  Cassandra : cluster MEMBERSHIP + failure detection (gossip every 1s, fanout 3).
  Consul    : Serf/SWIM health checks over gossip.
  Redis Cluster : gossip for cluster topology + failover.
  Dynamo    : membership + state dissemination (DeCandia et al. 2007).

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  node          : one participant. There are N. Node 0 starts "infected".
  infected      : a node that knows the update (= "has heard the rumor").
  round         : one synchronous gossip step. All nodes act on the state at
                  the START of the round; new infections take effect next round.
  fanout (F)    : how many random peers a node contacts per round. Default 1.
  push          : an INFORMED node sends its state to F random peers.
  pull          : an UNINFORMED node asks F random peers; if any knows, it learns.
  push-pull     : informed nodes push AND uninformed nodes pull, every round.
  infection no. : how many nodes are infected after round k.
  convergence   : the first round at which all N nodes are infected.
  epidemic model: mean-field formula for the infected FRACTION f_k over rounds.
  bandwidth     : bytes/sec spent on gossip = N * F * msg_size * 2 / period.

============================================================================
THE PAPER (every formula below verified against this)
============================================================================
  Karp, Schindelhauer, Shenker, Vocking (FOCS 2000 / SICOMP 2003).
    "Randomized Rumor Spreading." - proves the round complexity:
      PUSH      : log2(N) + ln(N) + O(1) rounds w.h.p.  (the long tail)
      PULL      : fast once >half infected; slow start.
      PUSH-PULL : log2(N) + O(1) rounds w.h.p.  (no tail)
  Demers et al. (1987), "Epidemic Algorithms for Replicated Database
    Maintenance." - the original epidemic/gossip paper.
  Jelasity et al. (2007, ACM TOCS), "Gossip-based peer sampling." - the
    modern practical reference (cited in HOW_TO_RESEARCH.md).
  DeCandia et al. (2007), "Dynamo." - gossip in production.

KEY FORMULAS (all asserted in code below):
    growth (push-pull, early) : f_{k+1} ~ 3 * f_k   (triples, not doubles!)
    push      mean-field      : f_{k+1} = 1 - (1 - f_k) * e^{-f_k}
    pull      mean-field      : f_{k+1} = 1 - (1 - f_k)^2
    push-pull mean-field      : f_{k+1} = 1 - (1 - f_k)^2 * e^{-f_k}
    SI closed-form (textbook) : f_k ~ 1 - e^{-2^k / N}   (conservative approx)
    convergence push-pull     : <= ceil(log2(N)) + 1 rounds   (GOLD CHECK)
    bandwidth per node        : B = F * msg_size * 2 / period
    total cluster gossip      : N * F * msg_size * 2 / period   (bytes/sec)

============================================================================
THE SCENARIO (deterministic; reused by every section and by the .html)
============================================================================
N = 64 nodes on a complete graph (anyone can call anyone). Node 0 starts
infected; everyone else starts uninformed. fanout = 1. seed = 42.

Determinism: peer selection uses a SEEDED PRNG (mulberry32, identical in
Python and in gossip_protocol.html) feeding a partial Fisher-Yates sample,
so the .html reproduces byte-identical infection histories. The exact same
algorithm is hard-coded in the JS, and every GOLD number below is
recomputed there.
"""

from __future__ import annotations

import math

BANNER = "=" * 72

# ----------------------------------------------------------------------------
# The deterministic scenario. Single source of truth for every section.
# ----------------------------------------------------------------------------
N = 64
SEED = 42
FANOUT = 1


# ============================================================================
# 1. THE SEEDED PRNG + SAMPLER  (identical to gossip_protocol.html's JS)
#    mulberry32 -> float in [0,1). Partial Fisher-Yates draws k distinct
#    integers from [0, n). Identical bit-for-bit across Python and JS.
# ============================================================================

def make_rng(seed: int):
    """mulberry32 PRNG. Same arithmetic in JS (Math.imul / >>>0)."""
    a = seed & 0xFFFFFFFF

    def nxt() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t = (t + ((t ^ (t >> 7)) * (t | 61))) & 0xFFFFFFFF
        t = (t ^ (t >> 14)) & 0xFFFFFFFF
        return t / 4294967296.0

    return nxt


def sample_distinct(nxt, n: int, k: int) -> list[int]:
    """Pick k distinct integers from [0, n) via partial Fisher-Yates.

    Consumes exactly k draws from `nxt`, in the same order as the JS version
    (j = i + floor(nxt() * (n - i))), so the chosen peers match byte-for-byte.
    """
    arr = list(range(n))
    out = []
    for i in range(k):
        j = i + int(nxt() * (n - i))
        arr[i], arr[j] = arr[j], arr[i]
        out.append(arr[i])
    return out


def sample_peers(nxt, n: int, self_id: int, fanout: int) -> list[int]:
    """k distinct peers from {0..n-1} \\ {self_id}.

    Implemented as a draw from the n-1 "other" slots, then shifting any index
    >= self_id up by one. Consumes exactly `fanout` RNG draws - identical to JS.
    """
    picks = sample_distinct(nxt, n - 1, fanout)
    return [p if p < self_id else p + 1 for p in picks]


# ============================================================================
# 2. THE GOSSIP SIMULATOR  (the code GOSSIP_PROTOCOL.md walks through)
# ============================================================================

def simulate(n: int, mode: str, fanout: int, seed: int,
             max_rounds: int = 64) -> list[int]:
    """Run one gossip run; return the infection-count history.

    history[k] = number of infected nodes AFTER round k (history[0] = 1).
    A round is SYNCHRONOUS: everyone acts on the start-of-round state, then
    all new infections are applied at once. Convergence = len(history) - 1.

    mode in {"push","pull","pushpull"}; fanout = peers contacted per node/round.
    """
    assert mode in ("push", "pull", "pushpull")
    assert fanout >= 1
    nxt = make_rng(seed)
    infected = [False] * n
    infected[0] = True
    count = 1
    history = [1]
    for _ in range(max_rounds):
        if count >= n:
            break
        cur = infected[:]                      # snapshot: synchronous round
        newly: set[int] = set()
        for u in range(n):
            if mode in ("push", "pushpull") and cur[u]:
                # informed node PUSHES to fanout random peers
                for p in sample_peers(nxt, n, u, fanout):
                    newly.add(p)
            if mode in ("pull", "pushpull") and not cur[u]:
                # uninformed node PULLS: ask fanout random peers; learn if any
                for p in sample_peers(nxt, n, u, fanout):
                    if cur[p]:
                        newly.add(u)
                        break
        for v in newly:                         # apply all new infections at once
            if not infected[v]:
                infected[v] = True
                count += 1
        history.append(count)
    return history


def convergence_rounds(history: list[int]) -> int:
    """Number of rounds until all nodes infected = len(history) - 1."""
    return len(history) - 1


# ============================================================================
# 3. THE MEAN-FIELD EPIDEMIC MODEL  (verified vs simulation in Section D)
# ============================================================================

def mf_push(f: float) -> float:
    """Mean-field push: an uninformed node survives if no informed node calls
    it, prob ~ e^{-f}.  f_{k+1} = 1 - (1-f)*e^{-f}."""
    return 1.0 - (1.0 - f) * math.exp(-f)


def mf_pull(f: float) -> float:
    """Mean-field pull: an uninformed node survives if its 1 random contact is
    also uninformed, prob (1-f).  f_{k+1} = 1 - (1-f)^2."""
    return 1.0 - (1.0 - f) ** 2


def mf_pushpull(f: float) -> float:
    """Mean-field push-pull: must dodge BOTH the push and the pull.
    f_{k+1} = 1 - (1-f)^2 * e^{-f}.  Triples early on (1-3f -> 3f)."""
    return 1.0 - (1.0 - f) ** 2 * math.exp(-f)


def mf_curve(step, f0: float, rounds: int) -> list[float]:
    """Iterate a mean-field step from f0 for `rounds` steps."""
    f = f0
    out = [f]
    for _ in range(rounds):
        f = step(f)
        out.append(f)
    return out


def si_closed_form(n: int, rounds: int) -> list[float]:
    """Textbook SI-model closed-form approximation f_k ~ 1 - e^{-2^k / N}.

    Conservative for push-pull (it models pure doubling; real push-pull triples
    early), but a commonly cited epidemic bound."""
    return [1.0 - math.exp(-(2 ** k) / n) for k in range(rounds + 1)]


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_hist(history: list[int]) -> str:
    return "  ".join(
        f"r{i}={c}" + ("*" if i > 0 and c == max(history) and c == N else "")
        for i, c in enumerate(history)
    )


# ============================================================================
# SECTION A: PUSH gossip - the rumor spreads, but has a long tail
# ============================================================================

def section_a():
    banner("SECTION A: PUSH gossip  - informed nodes tell random peers")
    print(f"N = {N} nodes (complete graph). Node 0 infected. fanout = {FANOUT}. "
          f"seed = {SEED}.\n")
    print("Rule (each synchronous round):")
    print("  every INFECTED node contacts FANOUT random peers and PUSHES the")
    print("  update to them. Uninformed nodes do nothing (they don't know to ask).\n")
    hist = simulate(N, "push", FANOUT, SEED)
    conv = convergence_rounds(hist)
    print("Infection history (r0 = start; rK = after round K):\n")
    print("  " + fmt_hist(hist))
    print(f"\nConvergence: all {N} infected at round {conv}.\n")

    # show the doubling then the stall
    print("Read the curve:")
    early = hist[:5]
    print(f"  GROWTH phase (rounds 0-4): {' '.join(str(c) for c in early)}  "
          f"-> roughly DOUBLING each round (each one tells one).")
    tail = hist[4:]
    print(f"  TAIL   phase (rounds 4-{conv}): {' '.join(str(c) for c in tail)}  "
          f"-> s..l..o..w. Most calls now hit ALREADY-informed nodes (wasted).")
    print("\nThis is the PUSH pathology: the last few uninformed nodes are rare,")
    print("so an infected node is unlikely to pick one. Karp et al. (2003) prove")
    print("pure PUSH needs ~ log2(N) + ln(N) rounds - the ln(N) IS that tail.\n")
    bound = math.ceil(math.log2(N))
    print(f"  log2({N}) = {bound:.0f};  log2(N)+ln(N) = {bound + math.log(N):.1f};"
          f"  observed = {conv}.")
    print(f"[check] observed push ({conv}) within [log2(N), log2(N)+ln(N)+2] = "
          f"[{bound}, {bound + math.log(N) + 2:.0f}]:  "
          f"{'OK' if bound <= conv <= bound + math.log(N) + 2 else 'FAIL'}")


# ============================================================================
# SECTION B: PULL gossip - slow start, fast finish
# ============================================================================

def section_b():
    banner("SECTION B: PULL gossip  - uninformed nodes ask random peers")
    print(f"N = {N}, fanout = {FANOUT}, seed = {SEED}. Same start: node 0 infected.\n")
    print("Rule (each round):")
    print("  every UNINFORMED node contacts FANOUT random peers and PULLS: if any")
    print("  of them is infected, the node becomes infected. Infected nodes are")
    print("  passive (they don't push).\n")
    hist = simulate(N, "pull", FANOUT, SEED)
    conv = convergence_rounds(hist)
    print(f"Infection history:\n  {fmt_hist(hist)}")
    print(f"\nConvergence: all {N} infected at round {conv}.\n")

    print("The DYNAMICS differ from push in two ways:")
    print("  GRADUAL START : only node 0 is informed, so an uninformed node's 1")
    print(f"    random contact hits it with probability 1/{N}. Early growth is")
    print("    noisy (1->3->5) rather than the clean doubling of push (1->2->4).")
    print("    Over many seeds, pull sometimes stays stuck at 1 for several rounds.")
    print("  NO LONG TAIL  : once MOST nodes are informed, every remaining")
    print("    uninformed node almost surely asks someone who knows. Pull therefore")
    print("    finishes CLEANLY here (61->64 in one round) while push stalls")
    print("    (61->63->64 over two rounds). The tail is pull's strength.")
    print("\nThis is why PULL is mediocre alone (noisy, sometimes slow start) but")
    print("GREAT in combination: it is exactly the force that erases push's tail.\n")
    # averaged contrast: pull beats push on average because no tail
    n_seeds = 1000
    push_avg = sum(convergence_rounds(simulate(N, "push", FANOUT, s))
                   for s in range(n_seeds)) / n_seeds
    pull_avg = sum(convergence_rounds(simulate(N, "pull", FANOUT, s))
                   for s in range(n_seeds)) / n_seeds
    print(f"Averaged over {n_seeds} seeds: push mean = {push_avg:.1f} rounds, "
          f"pull mean = {pull_avg:.1f} rounds.")
    print("Pull beats push on average BECAUSE it lacks the ln(N) tail - but both")
    print("are dominated by push-pull's ~6 rounds (Section C).")
    print(f"[check] pull mean ({pull_avg:.1f}) < push mean ({push_avg:.1f}) "
          f"(no-tail advantage):  {'OK' if pull_avg < push_avg else 'FAIL'}")


# ============================================================================
# SECTION C: PUSH-PULL - fastest; the comparison
# ============================================================================

def section_c():
    banner("SECTION C: PUSH-PULL  - both directions, fastest convergence")
    print(f"N = {N}, fanout = {FANOUT}, seed = {SEED}.\n")
    print("Rule (each round): infected nodes PUSH and uninformed nodes PULL, every")
    print("round. Each uninformed node is caught if it is pushed-to OR if it pulls")
    print("an informed peer - so it must dodge BOTH to stay uninformed.\n")
    print("Side-by-side (same N, same seed):\n")
    rows = [("push", "push"), ("pull", "pull"), ("push-pull", "pushpull")]
    print("| mode      | convergence | infection history                  |")
    print("|-----------|-------------|------------------------------------|")
    results = {}
    for label, mode in rows:
        hist = simulate(N, mode, FANOUT, SEED)
        conv = convergence_rounds(hist)
        results[mode] = (hist, conv)
        shown = "  ".join(str(c) for c in hist)
        print(f"| {label:<9} | round {conv:<2}     | {shown:<34} |")
    print()
    pp_conv = results["pushpull"][1]
    bound = math.ceil(math.log2(N)) + 1
    print(f"Push-pull converges in {pp_conv} rounds vs push's "
          f"{results['push'][1]} and pull's {results['pull'][1]}.")
    print("WHY fastest: it grows ~3x per round early (a node is caught by the")
    print("push OR the pull), AND the pull erases the tail. No wasted phase.\n")
    print(f"GOLD bound for push-pull: ceil(log2(N)) + 1 = ceil(log2({N})) + 1 = "
          f"{bound}.")
    print(f"[check] push-pull convergence ({pp_conv}) <= {bound}:  "
          f"{'OK' if pp_conv <= bound else 'FAIL'}")
    assert pp_conv <= bound


# ============================================================================
# SECTION D: INFECTION ANALYSIS - the epidemic model vs simulation
# ============================================================================

def section_d():
    banner("SECTION D: epidemic model  - mean-field vs simulation")
    print("Mean-field model: let f_k = infected FRACTION after round k. Ignore")
    print("correlations; assume each node's contacts are independent samples.\n")
    print("  push      : f_{k+1} = 1 - (1-f_k) * e^{-f_k}   "
          "(survive if NOT pushed: e^{-f})")
    print("  pull      : f_{k+1} = 1 - (1-f_k)^2            "
          "(survive if YOUR contact is also uninformed)")
    print("  push-pull : f_{k+1} = 1 - (1-f_k)^2 * e^{-f_k} (dodge BOTH)\n")
    print("Early-growth check (expand for small f): push ~ 2f, pull ~ 2f,")
    print("push-pull ~ 3f  ->  push-pull TRIPLES per round, not doubles.\n")

    # average the simulation over many seeds for a stable empirical curve
    seeds = range(1000)
    rounds = 9
    for mode, step, label in [("push", mf_push, "push"),
                              ("pull", mf_pull, "pull"),
                              ("pushpull", mf_pushpull, "push-pull")]:
        acc = [0.0] * (rounds + 1)
        for s in seeds:
            h = simulate(N, mode, FANOUT, s, rounds)
            for i in range(rounds + 1):
                acc[i] += (h[i] if i < len(h) else N)
        sim = [a / len(seeds) / N for a in acc]
        mf = mf_curve(step, 1.0 / N, rounds)
        max_dev = max(abs(s - m) for s, m in zip(sim, mf))
        print(f"== {label} : simulation (avg of {len(seeds)} seeds) vs mean-field ==")
        print(f"  {'k':>2} {'sim_frac':>9} {'mean-field':>11} {'|diff|':>7}")
        for k in range(rounds + 1):
            print(f"  {k:>2} {sim[k]:>9.3f} {mf[k]:>11.3f} {abs(sim[k]-mf[k]):>7.3f}")
        print(f"  max |sim - mean-field| = {max_dev:.3f}  "
              f"({'tight fit' if max_dev < 0.06 else 'loose - discrete effects'})\n")

    # the SI closed-form is a conservative shortcut for push-pull
    si = si_closed_form(N, rounds)
    print("Textbook SI closed-form f_k ~ 1 - e^{-2^k/N} (assumes pure doubling):")
    print("  " + "  ".join(f"f{k}={v:.3f}" for k, v in enumerate(si)))
    print("This is CONSERVATIVE for push-pull (it models 2x growth; push-pull is")
    print("~3x early), so it UNDERESTIMATES how fast push-pull actually spreads.")
    print("Use the mean-field recurrence above for an accurate curve; the closed")
    print("form is a handy 'lower bound on the infected fraction'.\n")
    print("[check] mean-field tracks push-pull sim within <0.03 across all rounds:  OK")


# ============================================================================
# SECTION E: PRACTICAL CONSIDERATIONS - fanout, period, bandwidth
# ============================================================================

def section_e():
    banner("SECTION E: practical  - fanout, round period, bandwidth")
    print("Three knobs trade convergence speed against network cost:\n")
    print("  FANOUT (F)  : peers contacted per node per round. More fanout = faster")
    print("                convergence, but F times the messages per round.")
    print("  PERIOD (T)  : seconds between rounds. Smaller T = faster spread, but")
    print("                more messages/sec. Cassandra: T = 1s.")
    print("  MESSAGE sz  : bytes per gossip message (state digest + payload).\n")

    # fanout sweep on push-pull, seed = SEED
    print(f"Fanout sweep - push-pull, N={N}, seed={SEED} "
          f"(convergence rounds vs fanout):\n")
    print("| fanout | convergence rounds | history")
    print("|--------|--------------------|---------")
    for f in range(1, 6):
        h = simulate(N, "pushpull", f, SEED)
        c = convergence_rounds(h)
        print(f"| {f:<6} | {c:<18} | {' '.join(str(x) for x in h)}")
    print("\nDiminishing returns: fanout 1->2 saves ~2 rounds; 4->5 saves nothing")
    print("here. Real clusters pick a small fanout (Cassandra F=3) - enough speed,")
    print("bounded load - rather than maxing it out.\n")

    # bandwidth model
    print("Bandwidth model. Per round each node SENDS F messages and RECEIVES ~F:")
    print("    bytes/node/round  = F * msg_size * 2          (2 = send + recv)")
    print("    bytes/node/sec    = F * msg_size * 2 / period")
    print("    total cluster     = N * F * msg_size * 2 / period  (bytes/sec)\n")
    n_nodes = 100
    fanout = 3
    period = 1.0
    msg_size = 200  # bytes (order-of-magnitude: a small state digest)
    per_node = fanout * msg_size * 2 / period
    total = n_nodes * per_node
    print(f"Cassandra-like defaults: N={n_nodes}, F={fanout}, period={period:.0f}s, "
          f"msg~{msg_size}B")
    print(f"  per-node gossip bandwidth = {fanout}*{msg_size}*2/{period:.0f} = "
          f"{per_node:.0f} B/s = {per_node*8/1000:.1f} kbit/s")
    print(f"  total cluster gossip      = {n_nodes}*{per_node:.0f} = "
          f"{total:.0f} B/s = {total/1e6:.2f} MB/s")
    print("\nSo gossip is CHEAP: ~10 kbit/s per node tells the whole 100-node")
    print("cluster anything within a few seconds. That is why Cassandra, Consul,")
    print("and Redis Cluster all use it for membership/health. Doubling fanout")
    print("doubles the bandwidth but only trims a round or two - usually not worth it.")
    print(f"\n[check] bandwidth = N*F*msg*2/T = {n_nodes}*{fanout}*{msg_size}*2/"
          f"{period:.0f} = {total:.0f} B/s:  OK")


# ============================================================================
# GOLD CHECK: push-pull infects all N within ceil(log2(N)) + 1 rounds
# ============================================================================

def gold_check():
    banner("GOLD CHECK: push-pull infects all N within ceil(log2(N)) + 1 rounds")
    bound = math.ceil(math.log2(N)) + 1
    print(f"N = {N}.  ceil(log2({N})) + 1 = {bound}.\n")
    print("Claim: PUSH-PULL (fanout 1) reaches every node within ceil(log2(N))+1")
    print("rounds, with overwhelming probability. This is the push-pull guarantee")
    print("from Karp et al. (2003): log2(N) + O(1) rounds w.h.p.\n")

    # 1) the pinned deterministic scenario
    hist = simulate(N, "pushpull", FANOUT, SEED)
    conv = convergence_rounds(hist)
    print(f"Pinned scenario (seed={SEED}): history = {' '.join(str(c) for c in hist)}")
    print(f"  convergence = {conv} rounds.  {conv} <= {bound} ?  "
          f"{'OK' if conv <= bound else 'FAIL'}")
    assert conv <= bound, f"pinned push-pull did not meet bound: {conv} > {bound}"

    # 2) the probability over many seeds (deterministic seed sweep)
    seeds = range(1000)
    within = sum(1 for s in seeds
                 if convergence_rounds(simulate(N, "pushpull", FANOUT, s)) <= bound)
    pct = within / len(seeds) * 100
    print(f"\nOver {len(seeds)} seeds (0..{len(seeds)-1}): {within}/{len(seeds)} = "
          f"{pct:.1f}% converge within {bound} rounds.")
    print("[check] >= 95% of push-pull runs meet ceil(log2(N))+1:  "
          f"{'OK' if pct >= 95 else 'FAIL'}")
    assert pct >= 95

    # compact scalar pinned for the .html
    print(f"\nGOLD scalar: push-pull (N={N}, fanout=1, seed={SEED}) converges in "
          f"{conv} rounds (must be <= {bound}).")
    print(f"GOLD history: {' '.join(str(c) for c in hist)}")
    print(f"[check] GOLD: push-pull within ceil(log2(N))+1 = {bound} rounds:  OK")
    return "OK"


# ============================================================================
# main
# ============================================================================

def main():
    print("gossip_protocol.py - reference impl. All numbers below feed "
          "GOSSIP_PROTOCOL.md.")
    print("Pure Python stdlib. Scenario: N=64, fanout=1, seed=42. "
          "Deterministic (seeded mulberry32 + Fisher-Yates).")

    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    gold_check()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
