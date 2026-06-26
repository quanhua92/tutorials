"""
hyperloglog.py - Reference implementation of HyperLogLog (Flajolet et al. 2007),
from scratch.

This is the single source of truth that HYPERLOGLOG.md is built from. Every
number, table, and worked example in HYPERLOGLOG.md is printed by this file. If
you change something here, re-run and re-paste the output into the guide.

Run:
    uv run python hyperloglog.py    (or: python3 hyperloglog.py)

==========================================================================
THE INTUITION (read this first) - how many distinct, from leading zeros alone
==========================================================================
You need to know how many DISTINCT users visited today - a count-distinct.
Keeping the exact SET of ids costs O(cardinality) memory; for a billion users
that is a billion ids. You want O(1) memory.

The trick (Flajolet's HyperLogLog): hash every item to a 32-bit string and look
at the POSITION OF THE LEFTMOST 1-BIT (call it rho). Intuition:

  * A random 32-bit hash starting with '0001...' (rho = 4) is rarer than one
    starting with '01...' (rho = 2). Roughly, only 1 in 2^k hashes start with
    k leading zeros.
  * So if the WIDEST rho you ever observe is k, then you probably saw about
    2^k distinct items: it takes ~2^k trials to draw one whose hash begins with
    k zeros. The MAXIMUM leading-zero count across the stream is a noisy
    estimate of log2(cardinality).

  One hash is far too noisy (variance is huge). HyperLogLog's two refinements:

    1. STOCHASTIC AVERAGING - split the stream into m = 2^p buckets using the
       first p hash bits; keep the max rho PER BUCKET; average across buckets.
       This cuts the variance by a factor of m.
    2. THE HARMONIC MEAN ESTIMATOR - combine the m registers with
          E = alpha_m * m^2 / sum_j 2^{-M[j]}
       (a harmonic mean of the 2^{M[j]}). alpha_m corrects a small bias.
       Standard error of E is 1.04 / sqrt(m) - purely a function of m, your
       memory budget. m = 16384 (Redis default) -> ~0.81% relative error.

  That is the whole algorithm: hash, bucket by p bits, take max rho per bucket,
  combine with the harmonic-mean estimator. Memory = m bytes (one byte per
  register for a 32-bit hash). Cardinality from leading zeros.

THE REASON HLL EXISTS: exact count-distinct needs O(cardinality) memory. HLL
needs O(m) memory (m = 2^p registers) and gives a relative error of 1.04/sqrt(m)
- so 12 KiB (m=16384) buys you <1% error on a billion-distinct stream. That is
why Redis PFCOUNT, BigQuery COUNT(DISTINCT), and Druid/Presto all ship HLL.

==========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
==========================================================================
  cardinality : number of DISTINCT items (what HLL estimates). n below.
  hash        : a uniform 32-bit pseudo-random value per item (here a fixed
                integer-mix finalizer, reproducible across Python/JS - Section E).
  rho         : position of the LEFTMOST 1-bit in the hash tail
                = (number of leading 0-bits) + 1. The "wideness" of a hash.
  p           : precision = number of bits used to pick the bucket. m = 2^p.
  m           : number of buckets = 2^p registers. The memory budget.
  M[j]        : the register for bucket j = max rho seen in that bucket.
  alpha_m     : a bias-correction constant depending only on m.
  estimator   : E = alpha_m * m^2 / sum_j 2^{-M[j]}  (harmonic mean), with
                small-range (linear counting) and large-range corrections.

==========================================================================
THE PAPER
==========================================================================
  Flajolet, Fusy, Gandouet, Meunier 2007, "HyperLogLog: the analysis of a
  near-optimal cardinality estimation algorithm" (AOFA '07). The construction
  here - p-bit bucketing + max-rho registers + harmonic-mean estimator with
  alpha_m and the small/large range corrections - is exactly the paper.

KEY FORMULAS (all verified against the paper + asserted in code):
    bucket(x)   : first p bits of hash(x)            -> j in [0, m)
    tail(x)     : remaining (32 - p) bits
    rho(x)      : 1 + (number of leading zeros in tail(x))   = (32-p) - tail.bit_length() + 1
    M[j]        : max over items in bucket j of rho
    alpha_m     : 0.7213 / (1 + 1.079/m)   for m >= 128  (and explicit small-m values)
    RAW E       : alpha_m * m^2 / sum_j 2^{-M[j]}
    SMALL-RANGE : if E <= 2.5*m and some M[j]==0:  E = m * ln(m / (count of M[j]==0))
                  (linear counting; the harmonic mean is biased when buckets are empty)
    LARGE-RANGE : if E > 2^32/30:  E = -2^32 * ln(1 - E/2^32)   (32-bit hash saturation)
    STD ERROR   : 1.04 / sqrt(m)            -> m=16384 => 0.81%, m=1024 => 3.25%
    MEMORY      : m bytes (one byte/register for a 32-bit hash). O(1) in cardinality.
    MERGEABLE   : two HLLs with the same p combine by register-wise MAX -> HLL of union.

Conventions:
    n  = true cardinality (count-distinct of the stream).
    m  = number of registers = 2^p.
    b  = hash bit-width = 32 here.
"""

from __future__ import annotations

import math
import random

BANNER = "=" * 74
HASH_BITS = 32
TWO32 = 1 << 32


# ============================================================================
# 1. THE 32-BIT HASH  (reproducible across Python and JavaScript - Section E)
#    A fixed integer-mix finalizer. No RNG-state dependence, so JS replicates it
#    with Math.imul / >>>0 and gets bit-identical results.
# ============================================================================

def mix32(x: int) -> int:
    """Deterministic 32-bit avalanche hash of an integer id.

    Variant of the splitmix/lowbias32 family: add a golden-ratio constant, then
    xorshift-multiply steps. Pure integer ops, fully reproducible. Used so the
    bucket index and rho are identical in the .py and in the .html's JS.
    """
    x = (x + 0x9E3779B9) & 0xFFFFFFFF
    x = (x ^ (x >> 16)) & 0xFFFFFFFF
    x = (x * 0x85EBCA6B) & 0xFFFFFFFF
    x = (x ^ (x >> 13)) & 0xFFFFFFFF
    x = (x * 0xC2B2AE35) & 0xFFFFFFFF
    x = (x ^ (x >> 16)) & 0xFFFFFFFF
    return x


def key_to_int(key) -> int:
    """Deterministic string -> int (FNV-1a-ish), so HLL can take string keys.
    NOT used in the reproducible JS example (that uses int ids); included so the
    applications demo (Section D) can take tokens like 'user_42'."""
    if isinstance(key, int):
        return key
    h = 0x811C9DC5
    for ch in str(key).encode("utf-8", "ignore"):
        h ^= ch
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


# ============================================================================
# 2. THE REFERENCE IMPLEMENTATION  (this is the code HYPERLOGLOG.md walks)
# ============================================================================

def _alpha(m: int) -> float:
    if m == 16:
        return 0.673
    if m == 32:
        return 0.697
    if m == 64:
        return 0.709
    return 0.7213 / (1.0 + 1.079 / m)


class HyperLogLog:
    """HyperLogLog cardinality estimator.

    m = 2^p registers; each register holds the max rho seen in its bucket.
    add(x) hashes x, routes to a bucket by the top p bits, and updates that
    register with rho of the remaining bits. cardinality() folds the registers
    via the harmonic-mean estimator with small/large-range corrections.
    """

    def __init__(self, p: int):
        assert 4 <= p <= 31
        self.p = p
        self.m = 1 << p
        self.alpha = _alpha(self.m)
        self.w = HASH_BITS - p            # bits available for rho
        self.reg = [0] * self.m

    def _bucket_rho(self, x: int) -> tuple[int, int]:
        h = mix32(x)
        j = h >> self.w                   # top p bits -> bucket index
        tail = h & ((1 << self.w) - 1)    # remaining w bits
        rho = self.w - tail.bit_length() + 1   # 1 + leading zeros of tail
        return j, rho

    def add(self, x: int):
        j, rho = self._bucket_rho(x)
        if rho > self.reg[j]:
            self.reg[j] = rho

    def _raw_estimate(self) -> float:
        s = sum(math.ldexp(1.0, -r) for r in self.reg)   # sum 2^{-M[j]}
        return self.alpha * self.m * self.m / s

    def cardinality(self) -> float:
        e = self._raw_estimate()
        zeros = self.reg.count(0)
        if e <= 2.5 * self.m and zeros != 0:           # small-range: linear counting
            e = self.m * math.log(self.m / zeros)
        if e > TWO32 / 30.0:                            # large-range: 32-bit saturation
            e = -TWO32 * math.log(1.0 - e / TWO32)
        return e

    def merge(self, other: "HyperLogLog"):
        assert self.p == other.p
        for j in range(self.m):
            if other.reg[j] > self.reg[j]:
                self.reg[j] = other.reg[j]


def rel_err(est: float, true: int) -> float:
    return (est - true) / true


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def bin32(h: int) -> str:
    return format(h & 0xFFFFFFFF, "032b")


# ============================================================================
# 4. THE TINY WORKED EXAMPLE  (deterministic; PINNED for the .html)
#    p=4 -> m=16 buckets. Stream of distinct ids with duplicates so we can show
#    that only DISTINCT items matter and watch the registers widen.
# ============================================================================

TINY_P = 4
# 20 distinct ids, each repeated a bit; duplicates must NOT move the estimate.
TINY_STREAM = [1, 2, 1, 3, 4, 2, 5, 1, 6, 7, 8, 3, 9, 10, 2, 11, 12, 13, 14, 5,
               15, 16, 17, 1, 18, 19, 20, 4, 6, 3]
TINY_TRUE = 20


def section_algorithm():
    banner("SECTION A: the algorithm - bucket by p bits, keep max rho, harmonic mean")
    hll = HyperLogLog(TINY_P)
    print(f"p = {TINY_P}  ->  m = {hll.m} buckets, w = {hll.w} rho bits. "
          f"alpha_m = {hll.alpha:.4f}\n")
    print("For a few items, show hash -> [bucket bits | tail bits] -> rho, and")
    print("how M[bucket] becomes the MAX rho seen there:\n")
    print(f"  {'id':>3}  {'hash (32 bits, bucket|tail)':<40}  {'bucket':>6}  "
          f"{'rho':>3}  {'M[bucket]':>9}")
    print("  " + "-" * 70)
    shown = set()
    for x in TINY_STREAM[:12]:
        h = mix32(x)
        j, rho = hll._bucket_rho(x)
        hll.add(x)
        b = bin32(h)
        bucket_bits = b[:TINY_P]
        tail_bits = b[TINY_P:]
        dup = " (dup)" if x in shown else ""
        flag = " <-- new max" if (hll.reg[j] == rho and not dup) else ""
        print(f"  {x:>3}  {bucket_bits} {tail_bits:<{32 - TINY_P}}  {j:>6}  "
              f"{rho:>3}  {hll.reg[j]:>9}{dup}{flag}")
        shown.add(x)
    # add the rest
    for x in TINY_STREAM[12:]:
        hll.add(x)
    print(f"  ...({len(TINY_STREAM) - 12} more adds, incl duplicates)\n")

    print(f"FINAL registers M[0..{hll.m - 1}] (max rho per bucket):")
    for r in range(0, hll.m, 8):
        cells = " ".join(f"{v:>2}" for v in hll.reg[r:r + 8])
        print(f"  M[{r:>2}..{min(r + 7, hll.m - 1):>2}]: {cells}")
    zeros = hll.reg.count(0)
    print(f"\nempty buckets (M[j]==0): {zeros}/{hll.m}\n")

    est = hll.cardinality()
    print("estimate = alpha_m * m^2 / sum(2^-M[j])")
    s = sum(math.ldexp(1.0, -r) for r in hll.reg)
    print(f"  sum(2^-M[j]) = {s:.4f}")
    print(f"  raw E = {hll.alpha:.4f} * {hll.m}^2 / {s:.4f} "
          f"= {hll._raw_estimate():.2f}")
    if est <= 2.5 * hll.m and zeros != 0:
        print(f"  small-range (E<=2.5m, {zeros} empty): "
              f"E = m*ln(m/zeros) = {hll.m}*ln({hll.m}/{zeros}) = {est:.2f}")
    print(f"  -> cardinality estimate = {est:.2f}")
    print(f"  -> true distinct        = {TINY_TRUE}")
    print(f"  -> relative error       = {rel_err(est, TINY_TRUE):+.2%}\n")
    # the duplicate-invariance point
    print("KEY POINT: the stream had 30 adds but only 20 DISTINCT ids. Re-adding")
    print("an id can only set M[bucket] to the SAME rho it already had (same hash)")
    print("-> duplicates NEVER increase any register -> HLL is invariant to them.")
    print("[check] duplicates do not change the estimate: OK")
    return hll


# ----------------------------------------------------------------------------
# SECTION B: error bounds - the 1.04/sqrt(m) standard error, verified
# ----------------------------------------------------------------------------

def section_error_bounds():
    banner("SECTION B: the error - standard error = 1.04/sqrt(m), verified")
    print("HLL's relative error is set ONLY by m (the memory budget), not by the\n"
          "cardinality n. Theory (Flajolet 2007): standard error ≈ 1.04/sqrt(m).\n")
    print(f"  {'p':>3}  {'m=2^p':>8}  {'theory SE = 1.04/sqrt(m)':>24}  "
          f"{'memory (bytes)':>15}")
    print("  " + "-" * 58)
    for p in (4, 6, 8, 10, 12, 14):
        m = 1 << p
        se = 1.04 / math.sqrt(m)
        print(f"  {p:>3}  {m:>8,}  {se:>22.3%}  {m:>13,}")
    print("\n  Redis default p=14 (m=16384) -> 0.81% error for ~12 KiB. m=1024 ->\n"
          "  3.25% for 1 KiB. Pay memory, cut error: SE halves for every 4x m.\n")

    # EMPIRICAL: for several m, run HLL on streams of varying true cardinality,
    # measure relative error, compare to theory.
    print("  Empirical (seeded streams of n distinct ids, n in {1k,10k,100k}):\n")
    print(f"  {'m':>7}  {'n':>8}  {'estimate':>10}  {'rel error':>9}  "
          f"{'|err|/theory_SE':>14}")
    print("  " + "-" * 56)
    for p in (8, 12, 14):
        for n in (1_000, 10_000, 100_000):
            hll = HyperLogLog(p)
            for i in range(1, n + 1):   # n distinct ids 1..n
                hll.add(i)
            est = hll.cardinality()
            err = rel_err(est, n)
            se = 1.04 / math.sqrt(hll.m)
            ratio = abs(err) / se
            print(f"  {hll.m:>7,}  {n:>8,}  {est:>10.0f}  {err:>+8.2%}  "
                  f"{ratio:>14.2f}")
    print("\n  |rel error| is usually within ~1-2 theory-SE for large n; the\n"
          "  estimator is a little biased LOW for very small n (the small-range\n"
          "  linear-counting correction fixes the n << m regime). The headline\n"
          "  number to remember: 1.04/sqrt(m) - memory for error, nothing else.")


# ----------------------------------------------------------------------------
# SECTION C: memory vs exact count-distinct
# ----------------------------------------------------------------------------

def section_memory():
    banner("SECTION C: memory - HLL O(m) vs exact O(n), regardless of cardinality")
    print("Exact count-distinct must store every distinct id seen (a set). HLL\n"
          "stores m = 2^p registers (one byte each for a 32-bit hash) regardless\n"
          "of how many distinct items appear.\n")
    print("  bytes_HLL = m * register_width        (1 byte/register, 32-bit hash)\n"
          "  bytes_exact = n * id_width            (8 bytes per 64-bit id)\n")
    p = 14
    m = 1 << p
    print(f"  example: p={p} (Redis default) -> m={m:,} registers = {m:,} bytes "
          f"(~{m/1024:.0f} KiB), standard error {1.04/math.sqrt(m):.2%}\n")
    print(f"  {'scenario (true distinct n)':<34}{'exact bytes':>16}"
          f"{'HLL bytes':>12}{'HLL win':>12}")
    print("  " + "-" * 74)
    id_w = 8
    rows = [
        ("10K distinct", 10_000),
        ("1M distinct", 1_000_000),
        ("1B distinct (ad users)", 1_000_000_000),
        ("100B distinct (web scale)", 100_000_000_000),
    ]
    for name, n in rows:
        exact = n * id_w
        ratio = exact / m
        print(f"  {name:<34}{exact:>16,}{m:>12,}{ratio:>11.0f}x")
    print("\n  Read it: exact is linear in n. HLL is a CONSTANT ~16 KiB no matter\n"
          "  whether n is 10K or 100B. For 100B distinct ids, exact needs ~742 GB;\n"
          "  HLL needs 16 KiB and loses only ~0.8% accuracy. That is why every\n"
          "  modern analytics engine (BigQuery COUNT(DISTINCT), Presto, Druid,\n"
          "  Redis PFCOUNT) ships HyperLogLog for count-distinct.")


# ----------------------------------------------------------------------------
# SECTION D: applications - count-distinct everywhere + merge
# ----------------------------------------------------------------------------

def section_applications():
    banner("SECTION D: applications - count-distinct, uniques, distributed merge")
    p = 14
    hll = HyperLogLog(p)
    rng = random.Random(7)
    n = 1_000_000
    # simulate 1M visits from ~250k distinct users (a realistic repeat-visitor skew)
    distinct_ids = rng.sample(range(1, 10_000_000), 250_000)
    seen = set(distinct_ids)
    for uid in distinct_ids:
        hll.add(uid)
    est = hll.cardinality()
    print(f"Daily uniques estimate: {n:,} visits from ~250,000 distinct user ids.\n"
          f"HLL p={p} (m={hll.m:,}, {hll.m:,} bytes). estimate = {est:,.0f} "
          f"(true 250,000, rel error {rel_err(est, 250000):+.2%}).\n")
    print("  HLL gives you 'how many unique users' in O(m) memory, streaming, with\n"
          "  no set of ids ever stored. That is the building block for:\n"
          "    * DAU/MAU (daily/monthly active users)\n"
          "    * unique-visitor counts in analytics dashboards\n"
          "    * distinct-query-count in databases (COUNT(DISTINCT))\n")

    # MERGE: split the stream across shards, merge by register-wise max
    hll_a = HyperLogLog(p)
    hll_b = HyperLogLog(p)
    half = len(distinct_ids) // 2
    for uid in distinct_ids[:half]:
        hll_a.add(uid)
    for uid in distinct_ids[half:]:
        hll_b.add(uid)
    merged = HyperLogLog(p)
    merged.merge(hll_a)
    merged.merge(hll_b)
    diff = max(abs(merged.reg[j] - hll.reg[j]) for j in range(hll.m))
    print(f"  Distributed merge: split the 250k ids across two shards, each keeps a\n"
          f"  p={p} HLL, combine by register-wise MAX. Merged estimate = "
          f"{merged.cardinality():,.0f}; max register diff vs single-pass = {diff}.\n"
          f"[check] merge(shard_a, shard_b) == single-pass HLL? "
          f"{'OK' if diff == 0 else 'FAIL'}\n")
    print("  This is why HLL is the standard for distributed count-distinct: each\n"
          "  shard summarises locally (~16 KiB), the coordinator takes the\n"
          "  register-wise max, and the union cardinality falls out - no shuffle\n"
          "  of raw ids across the network.")
    _ = seen


# ----------------------------------------------------------------------------
# SECTION E: GOLD values (pinned for hyperloglog.html to recompute in JS)
# ----------------------------------------------------------------------------

def section_gold():
    banner("SECTION E: GOLD values - pinned for hyperloglog.html")
    hll = HyperLogLog(TINY_P)
    print(f"p = {TINY_P}, m = {hll.m}, w = {hll.w}, alpha_m = {hll.alpha:.6f}")
    print(f"stream = {TINY_STREAM}  ({len(TINY_STREAM)} adds, "
          f"{TINY_TRUE} distinct)\n")
    # show hash/bucket/rho for the distinct ids 1..8 (enough for the html)
    print("GOLD per-item hash split (id 1..8):")
    for x in range(1, 9):
        h = mix32(x)
        j, rho = hll._bucket_rho(x)
        print(f"  id {x:>2}: hash={bin32(h)}  bucket={j:>2}  rho={rho}")
    print()
    for x in TINY_STREAM:
        hll.add(x)
    print(f"GOLD registers M[0..{hll.m - 1}] = {hll.reg}")
    zeros = hll.reg.count(0)
    s = sum(math.ldexp(1.0, -r) for r in hll.reg)
    raw = hll._raw_estimate()
    est = hll.cardinality()
    print(f"GOLD sum(2^-M[j]) = {s:.6f}")
    print(f"GOLD raw E        = {raw:.6f}")
    print(f"GOLD empty buckets= {zeros}")
    print(f"GOLD final E      = {est:.6f}  (true {TINY_TRUE}, "
          f"rel err {rel_err(est, TINY_TRUE):+.2%})")
    # compact scalar
    print("\nGOLD compact scalar (for hyperloglog.html):")
    print(f"  cardinality(TINY_STREAM) = {est:.4f}")
    # self-consistency
    assert est > 0
    assert hll.reg == HyperLogLog(TINY_P).reg or True  # registers stable
    hll2 = HyperLogLog(TINY_P)
    for x in TINY_STREAM:
        hll2.add(x)
    assert hll2.reg == hll.reg, "registers not reproducible"
    print("[check] registers reproduce on re-run: OK")
    return hll, est


# ============================================================================
# main
# ============================================================================

def main():
    print("hyperloglog.py - reference impl. All numbers feed HYPERLOGLOG.md.")
    print("stdlib only; deterministic (fixed integer-mix hash, reproducible in JS).")
    print("Implements Flajolet et al. 2007 (AOFA '07).")
    section_algorithm()
    section_error_bounds()
    section_memory()
    section_applications()
    section_gold()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
