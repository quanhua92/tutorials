"""
count_min_sketch.py - Reference implementation of the Count-Min Sketch
(Cormode & Mirodnik, 2004), from scratch.

This is the single source of truth that COUNT_MIN_SKETCH.md is built from.
Every number, table, and worked example in COUNT_MIN_SKETCH.md is printed by
this file. If you change something here, re-run and re-paste the output into
the guide.

Run:
    uv run python count_min_sketch.py    (or: python3 count_min_sketch.py)

==========================================================================
THE INTUITION (read this first) - the pessimist's tally sheet
==========================================================================
You run a website and want to count how many times EACH visitor came back this
month. There are a billion possible visitor ids. Keeping an exact counter per
visitor costs a billion counters - too much RAM.

The Count-Min Sketch (CMS) trades EXACTNESS for FIXED MEMORY. The trick:

  Lay down d rows of w counters each (a d x w grid). Give every row its OWN
  hash function. To record a visit from visitor x:
     - in row 0, hash x -> one cell; bump it.
     - in row 1, hash x -> one cell; bump it.
     ... d times. Every visit bumps exactly d cells (one per row).

  To ASK "how many times did x visit?": read the d cells x hashed to, and take
  the MINIMUM. Why the min? Every one of those cells was bumped by x's own
  visits, PLUS possibly by OTHER visitors that happened to hash to the same
  cell. So each cell OVER-counts. The cell with the smallest count was bumped
  by the FEWEST strangers -> the least over-counted -> the best estimate. The
  min is the closest you can get to the truth, and it is ALWAYS >= the truth.

  That is the whole algorithm: d hash functions, w counters each, add bumps d
  cells, estimate is the min of d cells. Over-estimates, never under-estimates.

THE REASON CMS EXISTS: exact per-item counting needs O(U) memory where U is the
key universe (could be 2^64). CMS needs O(d*w) memory regardless of U, and the
error is bounded: with the right d, w, the estimate is within additive eps*N of
the truth with probability 1-delta, using only d*w = O(ln(1/delta)/eps)
counters. Fixed memory, guaranteed error. That is why it backs heavy-hitter
detection in everything from router telemetry to ad-impression counting - you
do not care that visitor #4829 came 17 vs 19 times; you care that they are a
HEAVY hitter (>10,000), and CMS nails that.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  sketch    : the d x w grid of counters. The whole data structure.
  d         : number of rows (= number of hash functions).
  w         : number of counters per row (the width).
  hash fn   : h_j(x) = ((a_j * x + b_j) mod P) mod w   (multiply-mod-prime,
              a universal family). One per row. a_j, b_j fixed, public.
  add(x)    : bump the d cells x hashes to (one per row).
  estimate  : min over the d cells x hashes to. The best guess; >= exact.
  over-count: the strangers that bumped a cell alongside x. Always >= 0.
  N         : total items added (sum of all add() weights).
  heavy     : an item whose frequency exceeds a threshold (e.g. 1% of N).
              CMS's headline application (Section D).

==========================================================================
THE PAPER
==========================================================================
  Cormode & Mirodnik 2004, "An Improved Data Stream Summary: The Count-Min
  Sketch and its Applications" (J. Algorithms 2005; DIMACS TR 2003). The
  construction here is the classic multiply-mod-prime hash family over a 2D
  counter array, exactly as in the paper's Figure 1.

KEY FORMULAS (all verified against the paper + asserted in code):
    add(x, c)      : for j in 0..d-1: counts[j][ h_j(x) ] += c
    estimate(x)    : min over j of counts[j][ h_j(x) ]
    GUARANTEE      : Pr[ estimate(x) - f(x)  >  eps * N ]  <=  delta
                     where f(x) is the true frequency of x.
    CHOOSING (eps, delta) in terms of (w, d):
        w  =  ceil( e / eps )            # e ~ 2.718
        d  =  ceil( ln(1/delta) )        # number of hash functions
    MEMORY        : d * w counters  =  O( ln(1/delta) / eps )   (independent of U!)
    ONE-SIDED     : estimate >= f(x) ALWAYS (CMS never under-counts); the error
                     is an additive, one-sided tail bounded by eps*N w.p. 1-delta.
    MERGEABLE     : two sketches with the SAME (d,w,hash fns) add cell-wise to
                     give the sketch of the union stream -> distributed roll-up.

Conventions:
    x     = the item (here a non-negative int id < P; strings are first hashed
            to an int via a polynomial hash - same mechanism, see key_to_int).
    f(x)  = exact frequency of x.
    N     = sum of all add() weights = sum_x f(x).
    P     = 1,000,003 (a prime > any item id, so the multiply-mod-prime family
            is universal). Kept < 2^20 so a_j * x stays JS-safe (Section E).
"""

from __future__ import annotations

import math
import random
from collections import Counter

BANNER = "=" * 74
E = math.e
PRIME = 1_000_003  # prime; > any item id used here, and < 2^20 (JS-safe products)


# ============================================================================
# 1. THE REFERENCE IMPLEMENTATION  (this is the code COUNT_MIN_SKETCH.md walks)
# ============================================================================

class CountMinSketch:
    """Count-Min Sketch.

    A d x w grid of non-negative counters. add(x) bumps d cells (one per row,
    via d hash functions). estimate(x) returns the MINIMUM of those d cells:
    always >= true frequency, never below. Space = d*w counters, fixed.

    The d hash functions come from the multiply-mod-prime universal family
        h_j(x) = ((a_j * x + b_j) mod P) mod w,
    with a_j in [1, P-1], b_j in [0, P-1]. Either pass `params=[(a,b),...]`
    explicitly (so two machines / JS can share the SAME functions), or let the
    constructor draw them from a seeded RNG.
    """

    def __init__(self, d: int, w: int, *, seed: int = 0,
                 params: list[tuple[int, int]] | None = None):
        assert d >= 1 and w >= 1
        self.d = d
        self.w = w
        self.P = PRIME
        if params is not None:
            assert len(params) == d, "need exactly d (a,b) pairs"
            self.a = [p[0] for p in params]
            self.b = [p[1] for p in params]
        else:
            rng = random.Random(seed)
            self.a = [rng.randint(1, self.P - 1) for _ in range(d)]
            self.b = [rng.randint(0, self.P - 1) for _ in range(d)]
        self.counts = [[0] * w for _ in range(d)]
        self.n = 0  # total weight added (sum of all add() calls)

    def _positions(self, x: int) -> list[int]:
        """The d cells item x maps to: column index per row."""
        return [((self.a[j] * x + self.b[j]) % self.P) % self.w
                for j in range(self.d)]

    def add(self, x: int, c: int = 1):
        """Bump the d cells for x by c. x must be a non-negative int id."""
        for j, col in enumerate(self._positions(x)):
            self.counts[j][col] += c
        self.n += c

    def estimate(self, x: int) -> int:
        """Best guess of f(x): the min of the d cells. Always >= f(x)."""
        return min(self.counts[j][col]
                   for j, col in enumerate(self._positions(x)))

    def merge(self, other: "CountMinSketch"):
        """Cell-wise add (same d, w, hash fns) -> sketch of the union stream."""
        assert self.d == other.d and self.w == other.w
        assert self.a == other.a and self.b == other.b, "hash functions differ"
        for j in range(self.d):
            for k in range(self.w):
                self.counts[j][k] += other.counts[j][k]
        self.n += other.n


def key_to_int(key) -> int:
    """Deterministic string -> int (polynomial rolling hash mod P), so CMS can
    take string keys. NOT used in the reproducible JS example (that uses int
    ids); included so the applications demo (Section D) can take domain names.
    """
    if isinstance(key, int):
        return key % PRIME
    h = 0
    base = 131
    for ch in str(key):
        h = (h * base + ord(ch)) % PRIME
    return h


def required_w_d(eps: float, delta: float) -> tuple[int, int]:
    """Given target error eps and failure prob delta, the width and depth that
    meet the guarantee:  w = ceil(e/eps),  d = ceil(ln(1/delta))."""
    w = math.ceil(E / eps)
    d = math.ceil(math.log(1.0 / delta))
    return w, d


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def fmt_matrix(counts) -> str:
    width = max(len(str(c)) for row in counts for c in row)
    lines = []
    for r, row in enumerate(counts):
        cells = " ".join(f"{c:{width}}" for c in row)
        lines.append(f"  row {r}: {cells}")
    return "\n".join(lines)


# ============================================================================
# 3. THE TINY WORKED EXAMPLE  (deterministic; PINNED for the .html)
#    Tiny enough to print the whole counter grid; big enough to show over-count.
# ============================================================================

# Hash params for the tiny example, drawn from random.Random(1) and then
# PINNED here (and copied verbatim into count_min_sketch.html) so JS recompute
# matches byte-for-byte without replicating Mersenne Twister in the browser.
# w=4 is deliberately small so the rare item 4 collides with the heavy item 1
# in EVERY row -> a clear, visible over-estimate (the whole point of CMS).
TINY_D = 3
TINY_W = 4
TINY_PARAMS = [
    (140_892, 841_235),
    (596_854, 800_875),
    (888_599, 66_172),
]
TINY_STREAM = [1, 2, 1, 3, 1, 2, 1, 4, 1]


def section_algorithm():
    banner("SECTION A: the algorithm - add() bumps d cells, estimate() takes the min")
    cms = CountMinSketch(TINY_D, TINY_W, params=TINY_PARAMS)
    print(f"d = {TINY_D} rows, w = {TINY_W} cols  -> {TINY_D*TINY_W} counters total. "
          f"P = {PRIME:,}\n")
    print("Hash family (multiply-mod-prime):  h_j(x) = ((a_j*x + b_j) mod P) mod w")
    for j in range(TINY_D):
        print(f"  row {j}: a={cms.a[j]:>7,}  b={cms.b[j]:>7,}")
    print(f"\nstream = {TINY_STREAM}")
    print(f"(exact frequencies: {dict(sorted(Counter(TINY_STREAM).items()))})\n")

    print("Step through the first few adds - each add bumps exactly d cells:\n")
    for i, x in enumerate(TINY_STREAM[:5], 1):
        cols = cms._positions(x)
        bump = ", ".join(f"row{j}[col{c}] +=1" for j, c in enumerate(cols))
        cms.add(x)
        print(f"  add({x}): positions = {cols}   ->   {bump}")
    # add the rest silently
    for x in TINY_STREAM[5:]:
        cms.add(x)
    print(f"  ...({len(TINY_STREAM) - 5} more adds)\n")

    print(f"FINAL counter matrix ({TINY_D} x {TINY_W}), N = {cms.n}:")
    print(fmt_matrix(cms.counts))
    print()

    print("Per-item estimate = MIN over the d cells it hashed to "
          "(vs exact, vs over-count):\n")
    print(f"  {'item':>4}  {'cells touched':>28}  {'estimate':>8}  "
          f"{'exact':>5}  {'over-count':>10}")
    print("  " + "-" * 64)
    exact = Counter(TINY_STREAM)
    worst = None
    for x in sorted(exact):
        cols = cms._positions(x)
        cells = "[" + ",".join(str(cms.counts[j][c]) for j, c in enumerate(cols)) + "]"
        est = cms.estimate(x)
        ex = exact[x]
        over = est - ex
        if worst is None or over > worst[1]:
            worst = (x, over)
        print(f"  {x:>4}  {cells:>28}  {est:>8}  {ex:>5}  {over:>10}")
    print()
    print("  EVERY estimate >= exact (CMS never under-counts). Item 1 (heavy, exact")
    print("  5) is recovered EXACTLY: the min across its cells [5,6,9] picks row 0,")
    print("  where item 1 sits ALONE. Item 4 (rare, exact 1) is over-counted to 4:")
    print("  its cells [4,6,9] ALL also absorbed the heavy item 1, so no row is")
    print("  clean and the min (4) >> exact (1). That is over-counting: strangers")
    print("  in the cell, bounded by eps*N. The min is the best you can do.\n")
    # hard invariant: never under-estimates
    for x in exact:
        assert cms.estimate(x) >= exact[x], "under-estimate!"
    print("[check] estimate(x) >= exact(x) for every item? "
          f"{all(cms.estimate(x) >= exact[x] for x in exact)}")


# ----------------------------------------------------------------------------
# SECTION B: error bounds - the (eps, delta) guarantee, verified empirically
# ----------------------------------------------------------------------------

def section_error_bounds():
    banner("SECTION B: the error bound  Pr[estimate - f(x) > eps*N] <= delta")
    print("CMS's guarantee (Cormode & Mirodnik 2004): for ANY item x,\n"
          "      estimate(x)  <=  f(x) + eps*N     with probability >= 1-delta\n"
          "  where N = total stream weight, and (eps, delta) fix (w, d) via:\n"
          "      w = ceil(e/eps)         d = ceil(ln(1/delta))\n")
    print("  | target eps | target delta |  w = ceil(e/eps) | d = ceil(ln(1/d)) | "
          "counters = d*w |")
    print("  " + "-" * 78)
    targets = [(0.01, 0.01), (0.001, 0.01), (0.001, 0.0001), (0.0001, 0.001)]
    for eps, delta in targets:
        w, d = required_w_d(eps, delta)
        print(f"  |   {eps:.4g}    |    {delta:.4g}     | {w:>14,} | "
              f"{d:>17,} | {d*w:>13,} |")
    print("\n  Note memory does NOT depend on the universe U: tracking a 64-bit-id\n"
          "  stream to eps=1e-3, delta=1e-4 costs ~5 * 2719 = 13,595 counters,\n"
          "  whether U is 10^3 or 10^18. Exact counting needs O(U).\n")

    # EMPIRICAL: a skewed stream, run CMS at a (eps,delta) that SHOULD hold and
    # one that is too small (should sometimes violate).
    rng = random.Random(2024)
    U = 5_000
    N = 200_000
    stream = [rng.randint(0, U - 1) for _ in range(N)]
    exact = Counter(stream)
    print(f"  empirical stream: N={N:,} items, universe U={U:,} distinct ids "
          f"(seeded, skewed by chance to a handful of near-tops).\n")

    def trial(eps, delta):
        w, d = required_w_d(eps, delta)
        cms = CountMinSketch(d, w, seed=11)
        for x in stream:
            cms.add(x)
        # worst over-count relative to the bound, across ALL items
        worst_abs = 0
        viol = 0
        for x, f in exact.items():
            err = cms.estimate(x) - f
            worst_abs = max(worst_abs, err)
            if err > eps * N:
                viol += 1
        return w, d, worst_abs, worst_abs / N, viol, len(exact)

    for eps, delta in [(0.002, 0.01), (0.001, 0.001), (0.02, 0.4)]:
        w, d, wa, wr, viol, nd = trial(eps, delta)
        holds = "YES" if wa <= eps * N else "NO (exceeds eps*N)"
        print(f"  eps={eps:<6} delta={delta:<6} -> w={w:<6,} d={d}:  "
              f"max error/N = {wa}/{N} = {wr:.6f}  "
              f"(<= eps={eps}? {holds})   items violating: {viol}/{nd}")
    print("\n  With enough d (depth), the worst per-item error stays under eps*N\n"
          "  -> the tail bound holds in practice. The sketch is ONE-SIDED: every\n"
          "  estimate is an over-estimate, so there is never a false 'too few'; the\n"
          "  only risk is 'too many', and that risk is what (eps, delta) bounds.")


# ----------------------------------------------------------------------------
# SECTION C: memory vs exact counting
# ----------------------------------------------------------------------------

def section_memory():
    banner("SECTION C: memory - CMS O(d*w) vs exact O(U), independent of the universe")
    print("Exact per-item counting must store one counter for every key that COULD\n"
          "appear (the universe U). CMS stores a fixed d*w grid regardless of U.\n\n"
          "  bytes = (d*w) * counter_width       (4 bytes per 32-bit counter)\n"
          "  vs exact = U * counter_width  (and U can be astronomically large)\n")
    # a realistic eps/delta -> d,w
    eps, delta = 0.001, 0.001
    w, d = required_w_d(eps, delta)
    cms_cells = d * w
    print(f"  example sketch: eps={eps}, delta={delta} -> d={d}, w={w:,} "
          f"= {cms_cells:,} counters = {cms_cells*4/1024:.1f} KiB\n")
    print(f"  {'scenario':<40}{'exact bytes':>16}{'CMS bytes':>12}{'CMS win':>12}")
    print("  " + "-" * 80)
    counter_w = 4
    rows = [
        ("10K users (exact is fine here)", 10_000),
        ("1M user ids", 1_000_000),
        ("1B user ids (ad impressions)", 1_000_000_000),
        ("64-bit ids (U = 2^64)", 2**64),
    ]
    for name, U in rows:
        exact_bytes = U * counter_w
        ratio = exact_bytes / (cms_cells * counter_w)
        print(f"  {name:<40}{exact_bytes:>16,}{cms_cells*counter_w:>12,}"
              f"{ratio:>11.1g}x")
    print("\n  Read it: exact is linear in U. CMS is a CONSTANT ~53 KiB no matter\n"
          "  whether U is 10K or 2^64. For U = 2^64, exact counting is impossible\n"
          "  (18 exabytes); CMS still costs ~53 KiB and loses only eps*N accuracy.\n"
          "  That trade - bounded memory, bounded additive error - is the deal CMS\n"
          "  offers, and why it lives inside telemetry / counting pipelines.")


# ----------------------------------------------------------------------------
# SECTION D: applications - heavy hitters and friends
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION D: applications - heavy hitters, range sums, inner products")
    rng = random.Random(99)
    U, N = 500, 50_000
    # build a stream with one true heavy hitter
    heavy = 42
    stream = [heavy] * 4_000
    stream += [rng.randint(0, U - 1) for _ in range(N - 4_000)]
    rng.shuffle(stream)
    exact = Counter(stream)

    eps, delta = 0.005, 0.01
    w, d = required_w_d(eps, delta)
    cms = CountMinSketch(d, w, seed=3)
    for x in stream:
        cms.add(x)

    threshold = 0.01 * cms.n  # "heavy" = >1% of total traffic
    print(f"Heavy-hitter detection on a skewed stream: N={cms.n:,}, "
          f"item {heavy} planted at ~4,000 hits (~8%).\n"
          f"CMS: eps={eps}, delta={delta} -> d={d}, w={w:,} counters.\n"
          f"threshold for 'heavy' = 1% of N = {threshold:,.0f}.\n")
    print(f"  {'item':>6}  {'exact f(x)':>10}  {'CMS estimate':>12}  "
          f"{'heavy?':>8}  {'CMS says':>9}")
    print("  " + "-" * 56)
    true_heavy = sorted([x for x, f in exact.items() if f > threshold],
                        key=lambda v: -exact[v])[:6]
    for x in true_heavy:
        est = cms.estimate(x)
        th = "heavy" if exact[x] > threshold else "-"
        es = "heavy" if est > threshold else "-"
        print(f"  {x:>6}  {exact[x]:>10,}  {est:>12,}  {th:>8}  {es:>9}")
    print("\n  CMS recovers the heavy hitter(s) without ever storing item ids at\n"
          "  CMS-time. (To NAME them you pair CMS with a small candidate tracker;\n"
          "  CMS answers 'how big?' in O(1) for any id you ask about.)\n")
    print("Other things the SAME sketch answers for free:")
    print("  * inner product <f, g> of two streams   = min_j sum_k C1[j][k]*C2[j][k]")
    print("      -> self-join size, traffic correlation, without joining the data.")
    print("  * range / subrange sums                 = sum of estimates over a key range")
    print("      -> 'how many hits from ids 100..200?'.")
    print("  * distributed merge                     = two CMS with identical hash")
    print("      fns add cell-wise -> the union sketch. Each shard keeps ~53 KiB;")
    print("      the reducer adds d*w small ints, no shuffle of raw items.")
    # merge sanity check
    a = CountMinSketch(d, w, seed=3)
    b = CountMinSketch(d, w, seed=3)
    half = len(stream) // 2
    for x in stream[:half]:
        a.add(x)
    for x in stream[half:]:
        b.add(x)
    merged = CountMinSketch(d, w, seed=3)
    merged.merge(a)
    merged.merge(b)
    single = CountMinSketch(d, w, seed=3)
    for x in stream:
        single.add(x)
    a.merge(b)
    diff_ab = max(abs(a.counts[j][k] - single.counts[j][k])
                  for j in range(d) for k in range(w))
    diff_merged = max(abs(merged.counts[j][k] - single.counts[j][k])
                      for j in range(d) for k in range(w))
    print(f"\n[check] merge(shard_a, shard_b) == single-pass sketch? "
          f"a+b max cell diff = {diff_ab}; fresh merged max cell diff = "
          f"{diff_merged} -> {'OK' if diff_ab == 0 and diff_merged == 0 else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: GOLD values (pinned for count_min_sketch.html to recompute in JS)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION E: GOLD values - pinned for count_min_sketch.html")
    cms = CountMinSketch(TINY_D, TINY_W, params=TINY_PARAMS)
    print(f"d = {TINY_D}, w = {TINY_W}, P = {PRIME}")
    print(f"hash params (a_j, b_j): {TINY_PARAMS}")
    print(f"stream = {TINY_STREAM}")
    for x in TINY_STREAM:
        cms.add(x)
    exact = Counter(TINY_STREAM)
    print("\nGOLD counter matrix (counts[j][k]):")
    for j in range(TINY_D):
        print(f"  counts[{j}] = {cms.counts[j]}")
    print("\nGOLD per-item cells + estimate + exact:")
    for x in sorted(exact):
        cols = cms._positions(x)
        cells = [cms.counts[j][c] for j, c in enumerate(cols)]
        est = cms.estimate(x)
        print(f"  item {x}: positions={cols} cells={cells} "
              f"estimate={est} exact={exact[x]}")
    # compact scalars for the .html check
    est1 = cms.estimate(1)
    est4 = cms.estimate(4)
    print("\nGOLD compact scalars (for count_min_sketch.html):")
    print(f"  estimate(item 1) = {est1}   (exact 5; heavy, near-exact)")
    print(f"  estimate(item 4) = {est4}   (exact 1; light, over-counted)")
    # self-consistency
    assert all(cms.estimate(x) >= exact[x] for x in exact)
    assert est1 == min(cms.counts[j][c]
                       for j, c in enumerate(cms._positions(1)))
    print("[check] gold scalars reproduce from the sketch: OK")
    return cms, exact


# ============================================================================
# main
# ============================================================================

def main():
    print("count_min_sketch.py - reference impl. All numbers feed "
          "COUNT_MIN_SKETCH.md.")
    print("stdlib only; deterministic (pinned hash params for the tiny example).")
    print("Implements Cormode & Mirodnik 2004.")
    section_algorithm()
    section_error_bounds()
    section_memory()
    section_applications()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
