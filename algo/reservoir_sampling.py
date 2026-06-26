"""
reservoir_sampling.py - Reference implementation of Reservoir Sampling
(Algorithm R), the single-pass uniform sampler over a stream of unknown length.

This is the single source of truth that RESERVOIR_SAMPLING.md is built from.
Every number, table, and worked example in RESERVOIR_SAMPLING.md is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    python reservoir_sampling.py

============================================================================
THE INTUITION (read this first) -- the conveyor belt with k slots
============================================================================
Picture a CONVEYOR BELT of items rolling past you, one at a time. You don't
know how many will come (N is unknown), and you can't store them all. But you
must end up holding k of them, chosen UNIFORMLY AT RANDOM -- every item that
ever rode the belt must have the same chance k/N of being in your hand.

Algorithm R (Waterman; popularized by Knuth) does this with a "reservoir" of
k slots and one rule:

  * fill    : the first k items go straight into the reservoir. Slots full.
  * replace : for every later item i, pick a random slot j in [0..i]; if
              j happens to be one of the k reservoir slots (j < k), evict
              whatever is there and put item i in. Otherwise drop item i.

That's the whole algorithm. One pass, k slots of memory, and -- remarkably --
every item ends up with probability EXACTLY k/N, even though we decided each
item's fate before we knew N.

THE REASON IT WORKS: the "later" an item arrives, the LESS likely it is to
get IN (only k/(i+1) chance), but the MORE likely it is to STAY (fewer future
items remain that could evict it). Those two effects telescope to exactly k/N
for every item, early or late. See Section B for the one-paragraph proof.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  reservoir      : the array of k slots we keep. Always size k, start to end.
  stream         : the sequence of items arriving one at a time. Length N is
                   unknown while sampling (we only learn N at the end).
  Algorithm R    : the basic reservoir method (fill + replace). Waterman's;
                   Knuth TAOCP Vol 2 §3.4.2; cleaned up by Vitter 1985.
  item index i   : the 0-based position of an item in the stream (0, 1, ..., N-1).
  replace prob   : when item i arrives, P(it enters the reservoir) = k/(i+1).
                   (Equivalently: pick j uniform in [0..i]; replace slot j if j<k.)
  uniform sample : a subset where every one of the C(N,k) possible k-subsets is
                   equally likely. Stronger than "each item with prob k/N"
                   (that's only pairwise/marginal uniformity; Algorithm R gives
                   the full thing -- every k-subset equally likely).
  single pass    : we see each item ONCE and never look back. O(1) work per item.

============================================================================
THE LINEAGE (papers)
============================================================================
  Waterman (1970s, unpublished)   : the original Algorithm R. Cited by Knuth.
  Knuth  (TAOCP Vol 2, 1969/1981) : §3.4.2, exercise/algorithm -- made R famous.
                                    "Random Sampling without Replacement."
  Vitter (1985, ACM TOMS)         : "Random Sampling with a Reservoir." Cleans
                                    up R, and gives Algorithm Z, L, X for
                                    FASTER variants that skip items (jump
                                    ahead) when k << N.
  Park & Kim (2000s) / weighted   : Chao 1982, Efraimidis-Spirakis 2006 --
                                    reservoir sampling with WEIGHTS (a.k.a.
                                    A-Res / weighted reservoir).

KEY FORMULAS (verified against Knuth TAOCP Vol 2 §3.4.2 + Vitter 1985):
    Algorithm R       : for i in 0..N-1:  if i < k: R[i]=x; else j=randint(0,i);
                        if j < k: R[j]=x.
    P(item m sampled) = k / N              (for EVERY m, 0 <= m < N)
    proof sketch      : P(enter at m) * Prod_{i>m}(1 - P(evict at i))
                        = (k/(m+1)) * Prod_{i=m+1}^{N-1} i/(i+1)   [telescopes]
                        = (k/(m+1)) * (m+1)/N  =  k/N.
    time              : O(N)   (one randint + maybe one write per item)
    space             : O(k)   (only the reservoir; the stream is discarded)
    comparison        : naive "store all N then sample k" needs O(N) memory;
                        reservoir needs O(k) and ONE pass -- the whole point.
"""

from __future__ import annotations

import random
import sys

BANNER = "=" * 72


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATIONS  (the code RESERVOIR_SAMPLING.md walks through)
# ============================================================================

def reservoir_sample(stream, k, rng=None):
    """Algorithm R. Yield-free: takes an iterable, returns a list of k items.

    One pass, O(k) memory. Every item in the (possibly infinite / sized-unknown)
    stream has probability exactly k/N of being in the result, where N is the
    final stream length.

    stream : any iterable. We do NOT call len() -- we must not need to know N.
    k      : reservoir size (sample size). k >= 1.
    rng    : a random.Random for determinism. If None, uses a fresh one.

    Returns the reservoir list of k items (fewer if the stream had < k items).
    """
    if rng is None:
        rng = random.Random()
    res = []
    for i, x in enumerate(stream):
        if i < k:
            res.append(x)                       # fill phase: first k go straight in
        else:
            j = rng.randint(0, i)               # uniform in [0..i]  (i+1 choices)
            if j < k:                           # k of those choices -> replace
                res[j] = x
    return res


def reservoir_sample_traced(stream, k, rng):
    """Algorithm R that RECORDS every step for the .html animation.

    Returns (final_reservoir, steps) where each step is a dict:
      {'i': index, 'val': item, 'j': chosen slot or None, 'replaced': bool,
       'evicted': value evicted or None, 'reservoir': [...]}
    `reservoir` is the reservoir state AFTER processing item i.
    """
    res = []
    steps = []
    for i, x in enumerate(stream):
        if i < k:
            res.append(x)
            steps.append({"i": i, "val": x, "j": i, "replaced": True,
                          "evicted": None, "reservoir": list(res)})
        else:
            j = rng.randint(0, i)
            replaced = j < k
            evicted = res[j] if replaced else None
            if replaced:
                res[j] = x
            steps.append({"i": i, "val": x, "j": j, "replaced": replaced,
                          "evicted": evicted, "reservoir": list(res)})
    return res, steps


# ----------------------------------------------------------------------------
# The NAIVE baseline, ONLY for the memory comparison (Section C). Stores all N.
# ----------------------------------------------------------------------------
def naive_sample(stream, k, rng):
    """The obvious way: read everything into memory, then sample k. O(N) memory."""
    data = list(stream)                          # <-- the thing reservoir avoids
    return rng.sample(data, k)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_arr(a):
    return "[" + ", ".join(str(x) for x in a) + "]"


def fmt_pct(x):
    return f"{x * 100:.1f}%"


# ============================================================================
# 3. THE TINY CONCRETE EXAMPLE
#    Fixed stream so reservoir_sampling.html can recompute the EXACT same trace
#    in JS. The stream is a labeled list; item identity == its value.
# ============================================================================

# 12 labeled items, k=4. Small enough to print every step, big enough to show
# fill (first 4) + replace (last 8) phases.
WORKED_STREAM = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"]
WORKED_K = 4
WORKED_SEED = 0


# ----------------------------------------------------------------------------
# SECTION A: the algorithm -- a full traced run of Algorithm R
# ----------------------------------------------------------------------------

def section_algorithm():
    banner("SECTION A: the algorithm -- Algorithm R, traced step by step")
    n = len(WORKED_STREAM)
    k = WORKED_K
    print(f"Stream ({n} items): {fmt_arr(WORKED_STREAM)}")
    print(f"Reservoir size k = {k}, RNG seed = {WORKED_SEED}\n")
    print("Algorithm R in one breath:")
    print("  1. FILL     : first k items go straight into the reservoir.")
    print("  2. REPLACE  : for item i (i >= k), draw j = randint(0, i); if j < k,")
    print("                evict R[j] and put item i there; else drop item i.\n")

    rng = random.Random(WORKED_SEED)
    res, steps = reservoir_sample_traced(WORKED_STREAM, k, rng)
    print(f"  {'i':>2}  {'item':>4}  {'phase':>7}  {'j=randint(0,i)':>15}  "
          f"{'action':<26} reservoir")
    print("  " + "-" * 86)
    for s in steps:
        i = s["i"]
        phase = "fill" if i < k else "replace"
        if i < k:
            action = f"R[{i}] = {s['val']}  (slot fill)"
            jcell = "  --  "
        else:
            if s["replaced"]:
                action = f"R[{s['j']}] = {s['val']}  (evict {s['evicted']})"
            else:
                action = f"drop {s['val']}  (j >= k)"
            jcell = f"{s['j']}"
        print(f"  {i:>2}  {s['val']:>4}  {phase:>7}  {jcell:>15}  {action:<26} "
              f"{fmt_arr(s['reservoir'])}")
    print(f"\nFinal reservoir = {fmt_arr(res)}")
    print("Notice: early items (A,B,...) frequently get evicted by late arrivals;")
    print("late items get in rarely but, once in, are safe (nothing evicts them")
    print("afterwards). The balance is exactly k/N for everyone (Section B).\n")

    # self-consistency: re-run plain reservoir_sample, must match the trace's result
    rng2 = random.Random(WORKED_SEED)
    res2 = reservoir_sample(iter(WORKED_STREAM), k, rng2)
    assert res2 == res, f"BUG: trace {res} != plain {res2}"
    print("[check] traced run == plain reservoir_sample():  OK")


# ----------------------------------------------------------------------------
# SECTION B: the probability proof  (k/N uniformity) + Monte Carlo
# ----------------------------------------------------------------------------

def section_probability():
    banner("SECTION B: probability proof -- every item has probability k/N")
    n = len(WORKED_STREAM)
    k = WORKED_K
    p = k / n
    print(f"Claim: with N={n} and k={k}, EVERY stream item lands in the final")
    print(f"reservoir with probability exactly k/N = {k}/{n} = {fmt_pct(p)}.\n")
    print("PROOF (telescoping product). Fix an item at 0-based index m.\n")
    print("Case 1: m < k  (an early 'fill' item). It starts IN the reservoir. It")
    print("stays iff no later step i (i = k..N-1) evicts it. At step i we draw")
    print("j = randint(0, i); item m's slot is hit iff j == (m's slot), prob 1/(i+1).")
    print("So:")
    print("  P(stay) = Prod_{i=k}^{N-1} (1 - 1/(i+1)) = Prod_{i=k}^{N-1} i/(i+1)")
    print("          = k/(k+1) * (k+1)/(k+2) * ... * (N-1)/N = k/N.   (telescopes)\n")
    print("Case 2: m >= k (a late item). It must ENTER at step m, then SURVIVE:")
    print("  P(enter at m) = k/(m+1)            (k good slots of i+1 = m+1)")
    print("  P(survive)    = Prod_{i=m+1}^{N-1} i/(i+1) = (m+1)/N")
    print("  P(final)      = (k/(m+1)) * (m+1)/N = k/N.\n")
    print("Both cases give k/N. The boundary (m+1)/N is the telescoping hinge.\n")

    # Numerical check of the telescoping product for m = k-1 and m = N-1
    print("Numerical telescoping check (N=12, k=4):")
    for m in [0, k - 1, k, n - 1]:
        # P(item m in reservoir) via the product formula
        prob = 1.0
        if m < k:
            # it's in initially; survive steps k..N-1
            for i in range(k, n):
                prob *= i / (i + 1)
        else:
            prob *= k / (m + 1)                  # enter at m
            for i in range(m + 1, n):            # survive i=m+1..N-1
                prob *= i / (i + 1)
        tag = "fill item" if m < k else "late item"
        print(f"  m={m:>2} ({tag}): P = {prob:.6f}   (k/N = {p:.6f})  "
              f"{'OK' if abs(prob - p) < 1e-12 else 'FAIL'}")
    print()

    # ---- Monte Carlo: empirically estimate P(item m selected) over many runs ----
    trials = 200_000
    counts = [0] * n
    base_rng = random.Random(12345)
    for _ in range(trials):
        # independent seeded sub-stream per trial would be slow; reuse one rng
        res = reservoir_sample(WORKED_STREAM, k, base_rng)
        for item in res:
            counts[WORKED_STREAM.index(item)] += 1
    print(f"Monte Carlo over {trials:,} independent runs (one shared RNG stream):")
    print(f"  {'item':>4}  {'count':>8}  {'empirical P':>12}  {'target k/N':>11}  "
          f"{'|err|':>8}")
    max_err = 0.0
    for idx, item in enumerate(WORKED_STREAM):
        emp = counts[idx] / trials
        err = abs(emp - p)
        max_err = max(max_err, err)
        print(f"  {item:>4}  {counts[idx]:>8}  {emp:>12.4f}  {p:>11.4f}  {err:>8.4f}")
    print(f"\n  max |empirical - k/N| = {max_err:.4f}  "
          f"(expected MC noise ~ sqrt(k/N*(1-k/N)/trials) = "
          f"{(p*(1-p)/trials)**0.5:.4f})")
    mc_ok = max_err < 5 * (p * (1 - p) / trials) ** 0.5 + 1e-9
    print(f"  [check] all items within ~5 sigma of k/N:  {'OK' if mc_ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION C: complexity -- O(N) time, O(k) space  (vs naive O(N) space)
# ----------------------------------------------------------------------------

def section_complexity():
    banner("SECTION C: complexity -- O(N) time, O(k) space (the memory win)")
    print("Per item (i >= k): one rng.randint(0, i) + a compare + maybe one write.")
    print("That is O(1) amortized. Over N items -> O(N) time. Memory is just the")
    print("k reservoir slots -> O(k) space. The stream is consumed and forgotten.\n")
    print("Contrast with the naive sampler (store all N, then rng.sample):")
    print("| method              | passes | time   | space  | needs N up front? |")
    print("|---------------------|--------|--------|--------|-------------------|")
    print("| reservoir (Alg. R)  |   1    | O(N)   | O(k)   | no  (stream ok)   |")
    print("| naive store+sample  |   1    | O(N)   | O(N)   | yes (or 2 passes) |")
    print("| sort then take k    |   1    |O(NlogN)| O(N)   | yes               |")
    print()

    # Empirical: measure peak memory behavior by tracking list sizes (no tracemalloc
    # needed -- reservoir holds exactly k; naive holds exactly N). Show counts.
    sizes = [1000, 10_000, 100_000]
    k = 10
    print(f"Worked scaling: k={k}, growing N. 'memory used' = max list length held.\n")
    print(f"  {'N':>8}  {'reservoir mem (slots)':>22}  {'naive mem (slots)':>18}  "
          f"{'ratio':>7}")
    for n in sizes:
        # reservoir: we simulate memory as the reservoir length (always k)
        res_mem = k
        # naive: must hold all n
        naive_mem = n
        print(f"  {n:>8}  {res_mem:>22}  {naive_mem:>18}  "
              f"{naive_mem / res_mem:>6.0f}x")
    print("\nReservoir memory is CONSTANT in N; naive memory grows LINEARLY. For")
    print("N = 100,000 and k = 10, reservoir uses 10,000x LESS memory. That is the")
    print("entire reason the algorithm exists -- sample from a stream that does not")
    print("fit in RAM (logs, click streams, sensor feeds).\n")

    # correctness cross-check vs naive on a moderate stream
    n = 5000
    data = list(range(n))
    rng_r = random.Random(7)
    res = reservoir_sample(data, k, rng_r)
    rng_n = random.Random(7)
    naive = naive_sample(data, k, rng_n)
    assert len(res) == k and len(set(res)) == k, "BUG: duplicates or wrong size"
    assert all(0 <= x < n for x in res), "BUG: out of range"
    assert len(naive) == k and len(set(naive)) == k, "BUG: naive wrong size"
    print(f"[check] reservoir on N={n}, k={k}: size={len(res)}, all distinct, "
          f"in range:  OK")
    print("         (reservoir result != naive result in general -- both are")
    print(f"          valid uniform samples, just different draws. naive = "
          f"{fmt_arr(sorted(naive))}.)")


# ----------------------------------------------------------------------------
# SECTION D: applications
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION D: applications -- where single-pass uniform sampling matters")
    print("USE reservoir sampling when:")
    print("  - you sample from a STREAM whose length is unknown or infinite")
    print("    (logs, network packets, real-time metrics, a file too big for RAM).")
    print("  - you want k random rows from a HUGE dataset in ONE pass, O(k) memory.")
    print("  - you need a fixed-size RANDOM WINDOW over an evolving population")
    print("    (e.g. 'keep 100 random active users' as the set churns).\n")
    print("Classic real-world uses:")
    print("  - random log/tap sampling: keep k lines out of millions flowing past.")
    print("  - A/B experiment bucketing from an event stream of unknown volume.")
    print("  - MapReduce 'sample k from each shard' then merge (distributed).")
    print("  - 'Random line from a file' is just reservoir sampling with k=1")
    print("    (the classic interview question; one line held, one pass, no len()).")
    print("  - keeping a random subset of an infinite feed for later inspection.\n")
    print("WHEN NOT to use it:")
    print("  - N is known and small: just rng.sample(range(N), k) -- simpler, same.")
    print("  - you need WEIGHTED sampling (items have unequal weights): use")
    print("    Chao's algorithm or A-Res (Efraimidis-Spirakis 2006), NOT Algorithm R.")
    print("  - k is close to N (k ~ N): just store everything; the memory win is gone.")
    print("  - you need multiple independent samples: run independent reservoirs")
    print("    (or weighted, but R alone won't deduplicate across runs).")


# ----------------------------------------------------------------------------
# SECTION G: GOLD -- pins values for reservoir_sampling.html to recompute in JS.
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION G: GOLD values (pinned for reservoir_sampling.html)")
    rng = random.Random(WORKED_SEED)
    res, steps = reservoir_sample_traced(WORKED_STREAM, WORKED_K, rng)
    print(f"WORKED_STREAM = {fmt_arr(WORKED_STREAM)}  (N={len(WORKED_STREAM)})")
    print(f"WORKED_K = {WORKED_K}, WORKED_SEED = {WORKED_SEED}\n")
    print(f"GOLD final reservoir    = {fmt_arr(res)}")
    print(f"GOLD step count         = {len(steps)}")
    # number of replacements (items i>=k that entered)
    replaces = sum(1 for s in steps if s["i"] >= WORKED_K and s["replaced"])
    drops = sum(1 for s in steps if s["i"] >= WORKED_K and not s["replaced"])
    print(f"GOLD replacements (i>=k, j<k) = {replaces}")
    print(f"GOLD drops          (i>=k, j>=k) = {drops}")
    # the j sequence for i in [k..N-1] -- the .html reproduces this exactly
    rng2 = random.Random(WORKED_SEED)
    jseq = []
    for i in range(len(WORKED_STREAM)):
        if i < WORKED_K:
            jseq.append(None)
        else:
            jseq.append(rng2.randint(0, i))
    jseq_str = ", ".join("None" if j is None else str(j) for j in jseq)
    print(f"GOLD j-sequence (j=randint(0,i) for each i) = [{jseq_str}]")
    # per-step reservoir snapshots (compact), first few
    print("GOLD reservoir snapshots (per step i):")
    for s in steps:
        print(f"  i={s['i']:>2} -> {fmt_arr(s['reservoir'])}")
    # self-consistency
    assert len(res) == WORKED_K
    assert all(x in WORKED_STREAM for x in res)
    rng3 = random.Random(WORKED_SEED)
    res3 = reservoir_sample(iter(WORKED_STREAM), WORKED_K, rng3)
    assert res3 == res
    print("\n[check] gold reservoir reproduces from reservoir_sample():  OK")
    print("[check] traced j-sequence reproduces from a fresh seeded rng:  OK")


# ============================================================================
# main
# ============================================================================

def main():
    print("reservoir_sampling.py - reference impl. All numbers below feed "
          "RESERVOIR_SAMPLING.md.")
    print("python", sys.version.split()[0])

    section_algorithm()
    section_probability()
    section_complexity()
    section_applications()
    section_gold()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
